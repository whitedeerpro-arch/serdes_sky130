"""Frozen local AC comparisons for a physical one-MIM-per-bit candidate."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import bias, cap_fusion, project, spice, watch

ROOT = project.ROOT
SELF = Path(__file__).resolve()
BASELINE = ROOT/'results/layout/pll_r6/shared_bank_audited/pll_vco_cap_bank5_shared_cap.spice'
NAMES = ('planning', 'shared', 'fused')
FREQUENCIES = (1e6, 20e6, 2e9)
CONDITIONS = [(f'tt_{rc}', 'tt', rc, 1.8, 27) for rc in ('tt','hh','ll','hl','lh')]
CONDITIONS += [('fs_hot_hh','fs','hh',1.65,85), ('sf_cold_ll','sf','ll',1.65,-40)]


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def anchor(text):
    if not text.startswith('* Capacitance matrix from flat EXT node/cap records;'):
        raise ValueError('Audited EXT matrix required')
    top = re.search(r'^\.subckt (\S+) node b0 b1 b2 b3 b4 vss$', text, re.M)[1]
    plates = re.findall(r'^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b',text,re.M)
    # Keep the r6 numerical DC reference per logical half-unit; not physical R.
    commands = []
    for plate in dict.fromkeys(plates):
        gates = set(re.findall(r'^X\S+ '+re.escape(plate)+r' (b[0-4]) vss vss sky130_fd_pr__nfet_01v8\b',text,re.M))
        gates |= set(re.findall(r'^X\S+ vss (b[0-4]) '+re.escape(plate)+r' vss sky130_fd_pr__nfet_01v8\b',text,re.M))
        if len(gates)!=1: raise ValueError('Ambiguous floating-plate bit')
        bit=int(next(iter(gates))[1:])
        commands.append(f'Rdc{bit} {plate} vss {1e12/(2**bit):.12g}')
    return re.sub(r'^\.ends.*$', '\n'.join(commands)+'\n.ends',text,flags=re.M),top


def deck(c, e, fixed):
    name,process,rc,vdd,temp=e
    lines=['MIM fusion local comparison; independent of PLL long capture',f'.lib "{project.model_library()}" tt',
        f'.include "{c}/inputs/planning.spice"',f'.include "{c}/inputs/shared.spice"',
        f'.include "{c}/inputs/fused.spice"',f'.temp {temp}']
    for i,top in enumerate(('pll_vco_cap_bank5','pll_vco_cap_bank5_shared','pll_vco_cap_bank5_fused')):
        lines += [f'Vp{i} q{i} 0 dc 1.5 ac 1',f'X{i} q{i} b0 b1 b2 b3 b4 0 {top}']
    lines += [f'Vb{i} b{i} 0 0' for i in range(5)]
    lines += ['Vfilter fin 0 dc 1.5 ac 1']
    for kind,count,side in [('original',16,22.1965),('retiled',fixed['count'],fixed['side_um'])]:
        lines += [f'Rf_{kind} fin f_{kind} 1meg']
        lines += [f'Xf_{kind}_{i} f_{kind} 0 sky130_fd_pr__cap_mim_m3_1 w={side} l={side}' for i in range(count)]
    lines += ['.control','set num_threads=1','set wr_singlescale','set wr_vecnames','set numdgt=12']
    for code in range(32):
        lines += [f'alter Vb{i} dc={vdd if code>>i&1 else 0}' for i in range(5)]
        for fi,f in enumerate(FREQUENCIES):
            lines += [f'ac lin 1 {f} {f}']
            for i in range(3):
                lines += [f'let c{i} = -imag(i(vp{i}))/(2*pi*frequency)',f'let g{i} = -real(i(vp{i}))']
            lines += [f'wrdata c{code}_f{fi}.tsv '+' '.join(f'c{i} g{i}' for i in range(3)),'destroy all']
    lines += ['ac dec 200 10 1e8','meas ac fc_original when vdb(f_original)=-3.010299956639812 fall=1',
              'meas ac fc_retiled when vdb(f_retiled)=-3.010299956639812 fall=1',
              'wrdata filter.tsv fc_original fc_retiled','quit','.endc','.end','']
    return bias.section('\n'.join(lines),process,rc)


def prepare(physical):
    p=json.loads((physical/'summary.json').read_text())
    if p['mim_count']!=5 or p['mos_fingers']!=62 or not p['lvs'] or p['drc']:
        raise ValueError('Incomplete physical candidate')
    for rel,h in p['sha256'].items():
        if sha(physical/rel)!=h:raise ValueError('Physical input changed')
    c=ROOT/'results/analog/pll/vco/cap_fusion'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    (c/'inputs').mkdir(parents=True)
    shutil.copyfile(ROOT/'analog/pll/vco/spice/cap_bank_5b.spice',c/'inputs/planning.spice')
    for name,path in [('shared',BASELINE),('fused',physical/'pll_vco_cap_bank5_fused_cap.spice')]:
        text,top=anchor(path.read_text());(c/'inputs'/(name+'.spice')).write_text(text)
    m,_=cap_fusion.installed();target=16*m.cap_ff(22.1965,22.1965)
    count=int(np.ceil(target/m.cap_ff(30,30)))
    side=cap_fusion.rounded_square(target/count,grid_um=.01)
    fixed=dict(count=count,side_um=side,target_ff=target,actual_ff=count*m.cap_ff(side,side))
    (c/'prepared').mkdir()
    for e in CONDITIONS:(c/'prepared'/(e[0]+'.cir')).write_text(deck(c,e,fixed))
    prefix=deck(c,CONDITIONS[0],fixed).split('.control')[0]
    smoke=prefix+'\n.save v(q0) v(q1) v(q2)\n.control\nset num_threads=1\ntran 2p 1n 0 2p\nwrdata smoke.tsv v(q0) v(q1) v(q2)\nquit\n.endc\n.end\n'
    smoke=spice.binary_output(spice.skip_output_before(smoke,'0.2n'))
    (c/'prepared/smoke.cir').write_text(smoke)
    sources=[SELF,Path(cap_fusion.__file__),ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/bias.py']
    sources += [p for rc in cap_fusion.RC_FILES for p in cap_fusion.installed(rc)[1]]
    for p in set(sources):
        dest=c/'source'/p.relative_to(ROOT) if p.is_relative_to(ROOT) else c/'source/pdk'/p.name
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    plan=dict(physical=str(physical.relative_to(ROOT)),physical_summary_sha256=sha(physical/'summary.json'),
        conditions=CONDITIONS,fixed_filter=fixed,pdk_id=project.pdk_installation_id(),model_sha256=sha(project.model_library()),
        inputs={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()},
        scope='DC phase1.5V biased AC, all32codes at1MHz/20MHz/2GHz; five TT RC corners plus FS hot hh/SF cold ll; fixed1M/16pF filter model comparison; not oscillating VCO, switching, noise, MC or allPVT qualification')
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def check(c):
    p=json.loads((c/'plan.json').read_text())
    if p['pdk_id']!=project.pdk_installation_id() or p['model_sha256']!=sha(project.model_library()):raise ValueError('PDK changed')
    for n,h in p['inputs'].items():
        if sha(c/n)!=h:raise ValueError('Frozen input changed: '+n)
    return p


def read(c,name):
    for d in reversed([c/name]+sorted(c.glob(name+'.r[0-9]*'))):
        try:
            ex=json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:continue
            if (d/'tb.cir').read_bytes()!=(c/'prepared'/(name+'.cir')).read_bytes():continue
            rows=[]
            for code in range(32):
                for fi,f in enumerate(FREQUENCIES):
                    x=np.atleast_2d(np.loadtxt(d/f'c{code}_f{fi}.tsv',skiprows=1))
                    # c=imag(I)/frequency retains a complex plot flag and
                    # writes real/zero-imag; g=-real(I) writes one real column.
                    if x.shape!=(1,10) or not np.isfinite(x).all() or abs(x[0,0]/f-1)>1e-9:raise ValueError('Incomplete AC row')
                    if not np.allclose(x[0,2::3],0,atol=1e-25,rtol=0):raise ValueError('Unexpected complex metric')
                    rows.append(dict(code=code,hz=f,values={label:dict(c_ff=float(x[0,1+3*i]*1e15),g_s=float(x[0,3+3*i])) for i,label in enumerate(NAMES)}))
            tab=np.atleast_2d(np.loadtxt(d/'filter.tsv',skiprows=1))
            if tab.shape[1] not in (3,5) or not np.isfinite(tab).all():raise ValueError('Missing cutoff')
            if tab[-1,0]<1e8*(1-1e-9) or not np.allclose(tab[:,1:],tab[0,1:],rtol=0,atol=0):raise ValueError('Incomplete filter sweep or nonconstant scalar measurements')
            return dict(run=str(d.relative_to(ROOT)),rows=rows,filter_cutoff_hz=dict(original=float(tab[0,1]),retiled=float(tab[0,2 if tab.shape[1]==3 else 3])),elapsed_s=ex['elapsed_s'])
        except (OSError,ValueError,KeyError):continue
    return None


def analyse(c):
    p=check(c);results=[]
    for e in p['conditions']:
        row=read(c,e[0])
        if row is None:raise ValueError('Incomplete condition '+e[0])
        metrics={}
        for label in NAMES:
            table=[r['values'][label]['c_ff'] for r in row['rows'] if r['hz']==2e9]
            delta=np.diff(table)
            metrics[label]=dict(off_ff=table[0],on_ff=table[-1],min_step_ff=float(delta.min()),max_step_ff=float(delta.max()),monotone=bool(np.all(delta>0)))
        results.append(dict(condition=e,metrics=metrics,**row))
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    shutil.copyfile(SELF,out/'analysis.py')
    result=dict(campaign=str(c.relative_to(ROOT)),scope=p['scope'],plan_sha256=sha(c/'plan.json'),fixed_filter=p['fixed_filter'],rows=results,analysis_source_sha256=sha(SELF))
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(out/'summary.json',flush=True)


def resume(c):
    with (c/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);p=check(c)
        if len(watch.ngspice_cwds())+2>4:raise ValueError('Global NG quota occupied')
        jobs=[((c/'prepared'/(e[0]+'.cir')).read_text(),spice.next_run_dir(c,e[0]),dict(timeout_s=600))
              for e in p['conditions'] if read(c,e[0]) is None]
        if jobs:
            if spice.case_output(c,'smoke','smoke.raw',t_end=1e-9) is None:
                d=spice.next_run_dir(c,'smoke')
                ex=spice.run((c/'prepared/smoke.cir').read_text(),d,timeout_s=180)
                if not ex.ok or spice.Waves(d/'smoke.raw').t[-1]<1e-9*(1-1e-9):raise ValueError('Smoke failed')
            # Explicit transient smoke above; generic smoke requires tran,
            # whereas these measurement decks intentionally contain AC only.
            spice.run_many(jobs,workers=2,smoke=False)
        analyse(c)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path);a=ap.parse_args()
    if a.prepare:print(prepare(a.prepare.resolve()))
    elif a.resume:resume(a.resume.resolve())
    else:analyse(a.analyse.resolve())
