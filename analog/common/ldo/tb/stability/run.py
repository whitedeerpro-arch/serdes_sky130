"""Dual voltage/current injection of a frozen LDO boundary, 10 Hz to 10 GHz."""
import argparse
import fcntl
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import feedback, project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();REG=ROOT/'analog/common/ldo/tb/regulation/run.py'
spec=importlib.util.spec_from_file_location('ldo_regulation',REG);reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
sha=reg.sha;CORE=Path('analog/common/ldo/spice/ldo_hv18_core.spice')
RUNTIME=[SELF,REG,*[ROOT/('src/serdes_flow/'+p+'.py') for p in ('spice','feedback','project','watch')],ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
OUT=ROOT/'results/analog/common/ldo/stability'


def prepare(parent,pilot):
    parent=parent.resolve();p=reg.verify(parent)
    if p['options'].get('real_bias'):raise ValueError('Start with the ideal-reference LDO loop; host bandgap is a separate loop')
    if any(reg.completed(parent,e) is None for e in p['entries']):raise ValueError('Parent incomplete')
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    shutil.copyfile(parent/'source'/CORE,c/'source/core.spice')
    for path in RUNTIME:
        target=c/'source/runtime'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    base=(parent/p['entries'][-1]['deck']).read_text().split('.control')[0]
    entries=[dict(name='tt',process='tt',cases=[(3.3,27,6)])] if pilot else [dict(name=p,process=p,cases=[(v,t,i) for v in (3.,3.3,3.6) for t in (-40,27,85) for i in (2,6,10)]) for p in ('ss','sf','fs','ff','tt')]
    for e in entries:
        body=base.replace(f'.lib "{project.model_library()}" tt',f'.lib "{project.model_library()}" {e["process"]}')
        lines=[body,'Itest 0 fb 0 ac 0','.control','set num_threads=1','set filetype=binary','set wr_singlescale','set wr_vecnames']
        for v,t,i in e['cases']:
            name=reg.prefix(v,t,i)
            lines += [f'option temp={t}',f'alter Vdd dc={v}',f'alter Iload dc={i}m',f'dc Iload {i}m {i+.001}m 1u',f'write {name}_dc.raw v(out)','destroy all',
                      'alter Vtest acmag=1','alter Itest acmag=0','ac dec 50 10 10g','let tv=-v(div)/v(fb)','let vr=real(tv)','let vi=imag(tv)',f'wrdata {name}_voltage.tsv vr vi','destroy all',
                      'alter Vtest acmag=0','alter Itest acmag=1','ac dec 50 10 10g','let ti=i(Vtest)/(1-i(Vtest))','let ir=real(ti)','let ii=imag(ti)',f'wrdata {name}_current.tsv ir ii','destroy all']
        path=c/'prepared'/(e['name']+'.cir');path.write_text('\n'.join(lines+['quit','.endc','.end','']));e.update(deck=str(path.relative_to(c)),deck_sha256=sha(path))
    plan=dict(parent=str(parent.relative_to(ROOT)),parent_plan_sha256=sha(parent/'plan.json'),pdk_sha256=p['pdk_sha256'],runtime={str(x.relative_to(ROOT)):sha(x) for x in RUNTIME},
              sources={str(x.relative_to(c)):sha(x) for x in (c/'source').rglob('*') if x.is_file()},entries=entries)
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(r/'tb.cir')!=e['deck_sha256'] or ex['inputs_sha256']['core.spice']!=sha(c/'source/core.spice'):continue
            for v,t,i in e['cases']:
                name=reg.prefix(v,t,i);w=spice.Waves(r/(name+'_dc.raw'))
                if len(w.t)!=2 or not np.allclose(w.t,[i*.001,(i+.001)*.001],atol=1e-12,rtol=0):raise ValueError('DC incomplete')
                for kind in ('voltage','current'):
                    a=np.loadtxt(r/(name+'_'+kind+'.tsv'),skiprows=1)
                    if a.shape!=(451,3) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],np.logspace(1,10,451),rtol=1e-6):raise ValueError('AC incomplete')
            return r
        except (OSError,ValueError,KeyError):pass
    return None


def verify(c):
    p=json.loads((c/'plan.json').read_text())
    if reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Snapshot changed')
    for e in p['entries']:
        if sha(c/e['deck'])!=e['deck_sha256']:raise ValueError('Deck changed')
    return p


def analyse(c,p):
    rows=[];missing=[]
    for e in p['entries']:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        for v,t,i in e['cases']:
            name=reg.prefix(v,t,i);a=np.loadtxt(r/(name+'_voltage.tsv'),skiprows=1);b=np.loadtxt(r/(name+'_current.tsv'),skiprows=1)
            tv=a[:,1]+1j*a[:,2];ti=b[:,1]+1j*b[:,2];true=feedback.middlebrook(tv,ti)
            rows.append(dict(process=e['process'],vin_v=v,temp_c=t,load_ma=i,crossings=feedback.unity_crossings(a[:,0],true),
                             voltage_only_crossings=feedback.unity_crossings(a[:,0],tv),min_distance_to_minus_one=float(np.min(abs(1+true))),gain_at_10ghz=float(abs(true[-1])),
                             run=str(r.relative_to(ROOT)),evidence={x.name:sha(x) for x in [r/(name+'_voltage.tsv'),r/(name+'_current.tsv'),r/(name+'_dc.raw'),r/'execution.json']}))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),rows=rows,missing=missing,scope='Full Middlebrook dual injection plus local transient evidence, not whole-PLL/host-loop stability qualification'),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=rows if len(rows)<3 else len(rows),missing=missing),indent=2))


def resume(c,workers):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=verify(c)
        for rel,h in p['runtime'].items():
            if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
        active=watch.ngspice_cwds()
        if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots/already active')
        jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(files={'core.spice':c/'source/core.spice'},timeout_s=600)) for e in p['entries'] if completed(c,e) is None]
        # Parent DC smoke already passed; zero-valued probes preserve the same DUT/DC.
        spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare-from',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path);ap.add_argument('--pilot',action='store_true');ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare_from:print(prepare(a.prepare_from,a.pilot).relative_to(ROOT))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),verify(a.analyse.resolve()))
