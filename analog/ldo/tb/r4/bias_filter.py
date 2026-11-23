"""Tail-bias RC candidate on three identified, frozen PLL AC boundaries.

No oscillator transient: this checks source loading, DC drop and host->gate
AC attenuation. Kb/jitter and actual PLL capture require separate validation.
"""
import argparse
import importlib.util
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();RUN=SELF.with_name('run.py')
spec=importlib.util.spec_from_file_location('r4',RUN);r4=importlib.util.module_from_spec(spec);spec.loader.exec_module(r4)
sha=r4.sha;OUT=ROOT/'results/analog/ldo/r4_bias_filter'
PARENT=ROOT/'results/analog/pll/vco/bias_path_ac/20261110T101744Z/summary.json'
POINTS=('tt_v1800_t27:tt','fs_v1950_t-40:hh','sf_v1650_t85:hh')
INC=re.compile(r'^\.include\s+"([^"]+)"',re.M|re.I)
VECS=('vbias','vbias_q','vgi_bias','bias_vbg')


def prepare(slow=False):
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    p=json.loads(PARENT.read_text());copied={};orig={}
    def copy(path):
        path=path.resolve()
        if path in copied:return copied[path]
        target=c/'source'/(sha(path)[:12]+'_'+path.name);copied[path]=target;orig[str(path)]=sha(path)
        text=INC.sub(lambda m:f'.include "{copy(Path(m[1]))}"',path.read_text());target.write_text(text);return target
    passive=copy(ROOT/'analog/ldo/spice/ldo_passives.spice')
    macro=ROOT/('analog/ldo/spice/pll_bias_filter_r4.spice' if slow else 'analog/ldo/spice/pll_supply_hv18_r4.spice')
    cellname='serdes_pll_bias_lowpass_slow_r4' if slow else 'serdes_pll_bias_lowpass_r4'
    cell=macro.read_text().split('.subckt '+cellname,1)[1]
    cell='.subckt '+cellname+cell[:cell.index('.ends '+cellname)]+'.ends '+cellname+'\n'
    (c/'source/filter.spice').write_text(cell);orig[str(macro)]=sha(macro)
    entries=[]
    for point in POINTS:
        run=ROOT/p['rows'][point]['run'];baseline=run/'tb.cir';ex=json.loads((run/'execution.json').read_text())
        if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=sha(baseline):raise ValueError('Baseline execution invalid')
        text=INC.sub(lambda m:f'.include "{copy(Path(m[1]))}"',baseline.read_text()).split('.control')[0]
        text='* R4 local tail-gate filter on frozen real-bias PLL AC boundary\n'+'\n'.join(text.splitlines()[1:])+'\n'
        # Keep the PMOS current copy and local diode on original vbias. Only
        # oscillator and first buffer gates move across the added RC.
        lines=text.splitlines();count=0
        for i,line in enumerate(lines):
            if line.lower().startswith(('xvco ','xbuf')):
                if line.count(' vbias ')!=1:raise ValueError('Unexpected gate connection')
                lines[i]=line.replace(' vbias ',' vbias_q ');count+=1
        if count!=5:raise ValueError('Expected one VCO and four buffers')
        lines += [f'.include "{passive}"',f'.include "{c}/source/filter.spice"',f'Xtail_filter vbias vbias_q 0 {cellname}',
                  '.control','set num_threads=1','set filetype=binary','set wr_vecnames','set wr_singlescale','op','write op.raw v(vbias) v(vbias_q)',
                  'destroy all','ac dec 40 1k 100meg']
        for n,node in enumerate(VECS):lines += [f'let r{n}=real(v({node}))',f'let q{n}=imag(v({node}))']
        lines += ['wrdata ac.tsv '+' '.join(f'r{n} q{n}' for n in range(len(VECS))),'quit','.endc','.end','']
        name=point.replace(':','_');path=c/'prepared'/(name+'.cir');path.write_text('\n'.join(lines))
        entries.append(dict(name=name,point=point,deck=str(path.relative_to(c)),deck_sha256=sha(path),baseline=str(run.relative_to(ROOT)),baseline_sha256=sha(baseline)))
    shutil.copyfile(SELF,c/'source/runner.py')
    plan=dict(entries=entries,slow=slow,pdk_sha256=r4.reg.pdk_identity(),parent_summary=str(PARENT.relative_to(ROOT)),parent_summary_sha256=sha(PARENT),
              originals=orig,sources={str(x.relative_to(c)):sha(x) for x in (c/'source').iterdir()},runtime={str(x.relative_to(ROOT)):sha(x) for x in [SELF,*r4.RUNTIME]})
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def completed(c,e):
    for r in reversed([c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*'))):
        try:
            ex=json.loads((r/'execution.json').read_text());a=np.loadtxt(r/'ac.tsv',skiprows=1);w=spice.Waves(r/'op.raw')
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['deck_sha256']!=e['deck_sha256'] or sha(r/'tb.cir')!=e['deck_sha256']:continue
            if a.shape!=(201,9) or not np.all(np.isfinite(a)) or not np.allclose(a[:,0],np.logspace(3,8,201),rtol=1e-6) or len(w.t)!=1:raise ValueError('Output incomplete')
            return r
        except (OSError,ValueError,KeyError):pass
    return None


def analyse(c,p):
    rows=[];missing=[]
    for e in p['entries']:
        r=completed(c,e)
        if r is None:missing.append(e['name']);continue
        a=np.loadtxt(r/'ac.tsv',skiprows=1);w=spice.Waves(r/'op.raw');original=a[:,1]+1j*a[:,2];filtered=a[:,3]+1j*a[:,4]
        readings={str(int(f)):dict(original_mv_v=float(np.interp(np.log(f),np.log(a[:,0]),abs(original))*1000),filtered_mv_v=float(np.interp(np.log(f),np.log(a[:,0]),abs(filtered))*1000),
                                  attenuation_db=float(-20*np.log10(np.interp(np.log(f),np.log(a[:,0]),abs(filtered/original))))) for f in (1e5,3e5,1e6,4e6,2e7)}
        ratio=abs(filtered/original);fc=float(np.exp(np.interp(1/np.sqrt(2),ratio[::-1],np.log(a[::-1,0]))))
        rows.append(dict(point=e['point'],dc_original_v=float(w['v(vbias)'][0]),dc_filtered_v=float(w['v(vbias_q)'][0]),fc_hz=fc,readings=readings,
                         run=str(r.relative_to(ROOT)),evidence={x.name:sha(x) for x in [r/'ac.tsv',r/'op.raw',r/'execution.json']}))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),rows=rows,missing=missing,scope=__doc__),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=rows,missing=missing),indent=2))


def resume(c,workers):
    p=json.loads((c/'plan.json').read_text())
    if r4.reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Snapshot changed')
    for rel,h in p['runtime'].items():
        if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
    active=watch.ngspice_cwds()
    if any(x.is_relative_to(c) for x in active) or len(active)+workers>4:raise ValueError('No slots/already running')
    jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(timeout_s=240)) for e in p['entries'] if completed(c,e) is None]
    spice.run_many(jobs,workers=workers,smoke=False);analyse(c,p)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);ap.add_argument('--slow',action='store_true');ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.slow).relative_to(ROOT))
    else:resume(a.resume.resolve(),a.workers)
