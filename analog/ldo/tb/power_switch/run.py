"""Isolation-switch DC screen; no hot-switch/UVLO or complete LDO claim."""
import argparse
import fcntl
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();REG=ROOT/'analog/ldo/tb/regulation/run.py'
spec=importlib.util.spec_from_file_location('ldo_regulation',REG);reg=importlib.util.module_from_spec(spec);spec.loader.exec_module(reg)
CELL=ROOT/'analog/ldo/spice/ldo_power_switch.spice';sha=reg.sha
RUNTIME=[SELF,REG,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/project.py',ROOT/'src/serdes_flow/watch.py',ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
OUT=ROOT/'results/analog/ldo/power_switch'


def stem(v,t):return f'v{round(v*1000)}_t{t}'


def deck(process,cases,smoke=False):
    lines=['* Back-to-back PMOS isolation DC screen',f'.lib "{project.model_library()}" {process}','.include "switch.spice"',
           'Va a 0 1.8','Ven en 0 1.65','Iload b 0 6m','Rbleed b 0 1meg','Xon a b en 0 serdes_ldo_power_switch',
           'Vin offa 0 0','Vout offb 0 1.8','Xoff offa offb 0 0 serdes_ldo_power_switch',
           '.options reltol=1e-5 abstol=1p vntol=1u','.save all','.control','set num_threads=1','set filetype=binary']
    for v,t in cases:
        name=stem(v,t)
        lines += [f'option temp={t}',f'alter Va dc={v}',f'alter Vout dc={v}',f'dc Iload 0 {"1m" if smoke else "10m"} 1m',
                  f'write {name}_on.raw v(a) v(b) v(xon.mid) v(xon.gate) i(Va)','destroy all',
                  'dc Vin 0 1.95 0.05',f'write {name}_off.raw v(offa) v(offb) v(xoff.mid) v(xoff.gate) i(Vin) i(Vout)','destroy all']
    return '\n'.join(lines+['quit','.endc','.end',''])


def prepare():
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    for path in [*RUNTIME,CELL]:
        target=c/'source'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
    cases=[(v,t) for v in (1.65,1.8,1.95) for t in (-40,27,85)]
    entries=[dict(name='smoke',process='tt',cases=[(1.8,27)],smoke=True)]+[dict(name=p,process=p,cases=cases,smoke=False) for p in ('ss','sf','fs','ff','tt')]
    for e in entries:
        p=c/'prepared'/(e['name']+'.cir');p.write_text(deck(e['process'],e['cases'],e['smoke']));e.update(deck=str(p.relative_to(c)),deck_sha256=sha(p))
    plan=dict(pdk_sha256=reg.pdk_identity(),runtime={str(p.relative_to(ROOT)):sha(p) for p in RUNTIME},sources={str(p.relative_to(c)):sha(p) for p in (c/'source').rglob('*') if p.is_file()},cell=str(CELL.relative_to(ROOT)),entries=entries)
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text())
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(r/'tb.cir')!=e['deck_sha256'] or ex['inputs_sha256']['switch.spice']!=sha(c/'source'/CELL.relative_to(ROOT)):continue
            for v,t in e['cases']:
                a=spice.Waves(r/(stem(v,t)+'_on.raw'));b=spice.Waves(r/(stem(v,t)+'_off.raw'))
                if len(a.t)!=(2 if e['smoke'] else 11) or not np.allclose(a.t,np.arange(len(a.t))*.001,atol=1e-12,rtol=0):raise ValueError('On sweep incomplete')
                if len(b.t)!=40 or not np.allclose(b.t,np.arange(40)*.05,atol=1e-9,rtol=0):raise ValueError('Off sweep incomplete')
            return r
        except (OSError,KeyError,ValueError):pass
    return None


def verify(c):
    p=json.loads((c/'plan.json').read_text())
    if reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Frozen source changed')
    for e in p['entries']:
        if sha(c/e['deck'])!=e['deck_sha256']:raise ValueError('Deck changed')
    return p


def analyse(c,p):
    rows=[];missing=[]
    for e in p['entries'][1:]:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        for v,t in e['cases']:
            a=spice.Waves(r/(stem(v,t)+'_on.raw'));b=spice.Waves(r/(stem(v,t)+'_off.raw'))
            rows.append(dict(process=e['process'],vin_v=v,temp_c=t,drop_at_10ma_mv=float((v-a['v(b)'][-1])*1000),
                             off_reverse_at_zero_input_na=float(abs(b['i(vin)'][0])*1e9),off_max_input_current_na=float(np.max(np.abs(b['i(vin)']))*1e9),
                             run=str(r.relative_to(ROOT)),evidence={f.name:sha(f) for f in [r/(stem(v,t)+'_on.raw'),r/(stem(v,t)+'_off.raw'),r/'execution.json']}))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),rows=rows,missing=missing,status='local DC screen; no mode-change, brownout or PLL qualification'),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=len(rows),missing=missing)))


def resume(c,workers):
    with (c/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=verify(c)
        for rel,h in p['runtime'].items():
            if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
        active=watch.ngspice_cwds()
        if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots or already running')
        cell=c/'source'/CELL.relative_to(ROOT);e=p['entries'][0]
        if completed(c,e) is None:spice.run((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),files={'switch.spice':cell},timeout_s=240)
        if completed(c,e) is None:raise ValueError('DC smoke failed')
        jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(files={'switch.spice':cell},timeout_s=300)) for e in p['entries'][1:] if completed(c,e) is None]
        spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path);ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare().relative_to(ROOT))
    elif a.resume:resume(a.resume.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),verify(a.analyse.resolve()))
