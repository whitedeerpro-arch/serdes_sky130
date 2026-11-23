"""Additional quiet-pin capacitance: nominal and minimum-PM grid boundary."""
import argparse
import importlib.util
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np
from serdes_flow import feedback, project, spice, watch

ROOT=project.ROOT;SELF=Path(__file__).resolve();RUN=SELF.with_name('run.py')
spec=importlib.util.spec_from_file_location('r4',RUN);r4=importlib.util.module_from_spec(spec);spec.loader.exec_module(r4)
sha=r4.sha;OUT=ROOT/'results/analog/ldo/r4_cap_load';CAPS=(0,10,50,100,300,1000,10000,100000)
PROBE='@m.xdut.xcore.xpass.msky130_fd_pr__nfet_05v0_nvt[vbs]'


def prepare(grid):
    d=json.loads(grid.read_text());rows=d['rows']
    if d['missing']:raise ValueError('Grid incomplete')
    tt=next(x for x in rows if (x['mos'],x['rc'],x['hv_v'],x['host_v'],x['temp_c'],x['load_ma'])==('tt','tt',3.3,1.8,27,6))
    worst=min((x for x in rows if x['ac']),key=lambda x:min(g['pm_deg'] for g in x['crossings']))
    c=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8]);(c/'source').mkdir(parents=True);(c/'prepared').mkdir()
    for path in [SELF,*r4.RUNTIME,*r4.CELLS]:
        q=c/'source'/path.relative_to(ROOT);q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,q)
    entries=[]
    for label,x in [('nominal',tt),('weakest_pm',worst)]:
        lines=[r4.body(r4.section(x['mos'],x['rc'])),'Cexternal quiet 0 1a',
               f'.temp {x["temp_c"]}',f'.nodeset v(rawref)={x["vbg_v"]} v(xbg.xbg.s)={x["vbg_v"]} v(xbg.vg)=.9 v(vgi)={x["host_v"]-.8} v(quiet)={x["vout_v"]} v(xdut.ref_local)={x["vbg_v"]}',
               '.control','set num_threads=1','set filetype=binary','set wr_singlescale','set wr_vecnames',f'alter Vdd dc={x["hv_v"]}',f'alter Vhost dc={x["host_v"]}',f'alter Venable dc={x["host_v"]}',
               *[f'alter Vb{k} dc={x["host_v"] if (x["trim"]>>k)&1 else 0}' for k in range(6)],f'alter Iload dc={x["load_ma"]}m']
        for cap in CAPS:
            stem=f'p{cap}';lines += [f'alter Cexternal {max(cap*1e-12,1e-18):g}', 'alter Itest acmag=0','alter Vtest acmag=1','ac dec 20 10 10g',
                    'let tv=-v(fbret)/v(fbin)','let vr=real(tv)','let vi=imag(tv)',f'let opv=real(0*frequency)-{PROBE}',f'wrdata {stem}_v.tsv vr vi opv','destroy all',
                    'alter Itest acmag=1','alter Vtest acmag=0','ac dec 20 10 10g','let ti=i(Vtest)/(1-i(Vtest))','let ir=real(ti)','let ii=imag(ti)',f'let opv=real(0*frequency)-{PROBE}',f'wrdata {stem}_i.tsv ir ii opv','destroy all']
        path=c/'prepared'/(label+'.cir');path.write_text('\n'.join(lines+['quit','.endc','.end','']))
        entries.append(dict(name=label,boundary=x,deck=str(path.relative_to(c)),deck_sha256=sha(path)))
    p=dict(entries=entries,pdk_sha256=r4.reg.pdk_identity(),grid_summary=str(grid.relative_to(ROOT)),grid_sha256=sha(grid),sources={str(p.relative_to(c)):sha(p) for p in (c/'source').rglob('*') if p.is_file()},runtime={str(p.relative_to(ROOT)):sha(p) for p in [SELF,*r4.RUNTIME]})
    (c/'plan.json').write_text(json.dumps(p,indent=2)+'\n');return c


def run(c,workers):
    p=json.loads((c/'plan.json').read_text())
    if r4.reg.pdk_identity()!=p['pdk_sha256']:raise ValueError('PDK changed')
    for rel,h in p['sources'].items():
        if sha(c/rel)!=h:raise ValueError('Snapshot changed')
    for rel,h in p['runtime'].items():
        if sha(ROOT/rel)!=h:raise ValueError('Runtime changed')
    if len(watch.ngspice_cwds())+workers>4:raise ValueError('No slots')
    files={path.name:c/'source'/path.relative_to(ROOT) for path in r4.CELLS}
    jobs=[((c/e['deck']).read_text(),spice.next_run_dir(c,e['name']),dict(files=files,timeout_s=300)) for e in p['entries']]
    exs=spice.run_many(jobs,workers=workers,smoke=False)
    if any(not ex.ok for ex in exs):raise ValueError('Simulation failed')
    analyse(c,p)


def analyse(c,p):
    rows=[]
    for e in p['entries']:
        valid=[]
        for r in [c/e['name']]+sorted(c.glob(e['name']+'.r[0-9]*')):
            try:
                ex=json.loads((r/'execution.json').read_text())
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and ex['deck_sha256']==e['deck_sha256'] and sha(r/'tb.cir')==e['deck_sha256']:valid.append(r)
            except (OSError,ValueError):pass
        if not valid:raise ValueError('No valid execution')
        r=valid[-1]
        for cap in CAPS:
            a=np.loadtxt(r/f'p{cap}_v.tsv',skiprows=1);b=np.loadtxt(r/f'p{cap}_i.tsv',skiprows=1)
            if a.shape not in ((181,4),(181,5)) or b.shape not in ((181,4),(181,5)) or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)) or not np.allclose(a[:,0],np.logspace(1,10,181),rtol=1e-6):raise ValueError('Incomplete spectrum')
            if (a.shape[1]==5 and np.any(a[:,4]!=0)) or (b.shape[1]==5 and np.any(b[:,4]!=0)):raise ValueError('Complex OP voltage')
            if not np.allclose(a[:,3],e['boundary']['vout_v'],atol=.001,rtol=0) or not np.allclose(b[:,3],e['boundary']['vout_v'],atol=.001,rtol=0):raise ValueError('AC operating point mismatch')
            gain=feedback.middlebrook(a[:,1]+1j*a[:,2],b[:,1]+1j*b[:,2]);rows.append(dict(profile=e['name'],extra_pf=cap,crossings=feedback.unity_crossings(a[:,0],gain),run=str(r.relative_to(ROOT)),evidence={q.name:sha(q) for q in [r/f'p{cap}_v.tsv',r/f'p{cap}_i.tsv',r/'execution.json']}))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    (out/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),rows=rows,missing=[],scope='Two model boundaries, added ideal quiet-pin capacitance. No package/ESD/board parasitics or full cap-load PVT qualification.'),indent=2,allow_nan=False)+'\n')
    print(json.dumps(dict(analysis=str(out.relative_to(ROOT)),rows=rows),indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',type=Path);g.add_argument('--run',type=Path);g.add_argument('--analyse',type=Path);ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve()).relative_to(ROOT))
    elif a.run:run(a.run.resolve(),a.workers)
    else:analyse(a.analyse.resolve(),json.loads((a.analyse/'plan.json').read_text()))
