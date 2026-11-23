"""Compare physically legal switch widths on the plan's 4.6x7.56um block."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
from serdes_flow import bias, project, spice, watch

ROOT=project.ROOT
sys.path.insert(0,str(ROOT/'analog/pll/vco/layout'))
from build_fused_cap_bank import group

CONDITIONS=[('tt','tt','tt',1.8,27),('fs_hot_hh','fs','hh',1.65,85),('ss_hot_hh','ss','hh',1.65,85),
            ('ss_cold_hh','ss','hh',1.65,-40),('ff_cold_ll','ff','ll',1.95,-40),('tt_hh','tt','hh',1.8,27),('tt_ll','tt','ll',1.8,27)]
WIDTHS=[('w150',16,.75),('w075',8,.75),('w050',8,.5)]


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def make_deck(c,e):
    label,process,rc,vdd,temp=e
    lines=['Extracted rectangular MIM block, switch Q tradeoff',f'.lib "{project.model_library()}" tt',f'.temp {temp}','Ven en 0 0']
    for i,(name,nf,w) in enumerate(WIDTHS):
        lines += [f'.include "{c}/inputs/{name}.spice"',f'Vp{i} q{i} 0 dc 1.5 ac 1',f'X{i} q{i} en 0 {name}']
    lines += ['.control','set num_threads=1','set wr_singlescale','set wr_vecnames','set numdgt=12']
    for state,gate in [('off',0),('on',vdd)]:
        lines += [f'alter Ven dc={gate}']
        for fi,f in enumerate((1e6,20e6,2e9)):
            lines += [f'ac lin 1 {f} {f}']
            for i in range(3):lines += [f'let c{i}=-imag(i(vp{i}))/(2*pi*frequency)',f'let g{i}=-real(i(vp{i}))']
            lines += [f'wrdata {state}_{fi}.tsv '+' '.join(f'c{i} g{i}' for i in range(3)),'destroy all']
    return bias.section('\n'.join(lines+['quit','.endc','.end','']),process,rc)


def prepare():
    c=ROOT/'results/analog/pll/vco/switch_q'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');c.mkdir(parents=True)
    (c/'inputs').mkdir();(c/'prepared').mkdir()
    for name,nf,w in WIDTHS:
        d=c/name;d.mkdir();top,cell,ref=group(d,8,4.6,7.56,switch_fingers=nf,finger_w=w)
        net=(d/(top+'_cap.spice')).read_text();plate=re.search(r'^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b',net,re.M)[1]
        devices=re.findall(r'^X\S+ (\S+) en (\S+) vss sky130_fd_pr__nfet_01v8 .* w=([\d.]+) l=0.15$',net,re.M)
        if len(devices)!=nf or any(abs(float(v)-w)>1e-9 or {a,b}!={plate,'vss'} for a,b,v in devices):
            raise ValueError('Actual finger width/count/connectivity differs')
        net=net.replace(top,name);net=re.sub(r'^\.ends.*$',f'Rdc {plate} vss 125g\n.ends',net,flags=re.M)
        (c/'inputs'/(name+'.spice')).write_text(net)
    for e in CONDITIONS:(c/'prepared'/(e[0]+'.cir')).write_text(make_deck(c,e))
    prefix=make_deck(c,CONDITIONS[0]).split('.control')[0]
    smoke=prefix+'\n.save v(q0) v(q1) v(q2)\n.control\nset num_threads=1\ntran 2p 1n 0 2p\nwrdata smoke.tsv v(q0) v(q1) v(q2)\nquit\n.endc\n.end\n'
    (c/'prepared/smoke.cir').write_text(spice.binary_output(spice.skip_output_before(smoke,'0.2n')))
    for p in [Path(__file__).resolve(),ROOT/'analog/pll/vco/layout/build_fused_cap_bank.py']:
        d=c/'source'/p.name;d.parent.mkdir(exist_ok=True);shutil.copyfile(p,d)
    plan=dict(conditions=CONDITIONS,widths=WIDTHS,mim_um=[4.6,7.56],logical_units=8,
        pdk_id=project.pdk_installation_id(),model_sha256=sha(project.model_library()),
        inputs={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()},
        scope='Isolated 8-unit-equivalent rectangle from nine-block plan; actual MOS/MIM geometry and capacitive EXT; same cap shape, legal switch finger alternatives; nodeDC1.5V, AC small-signal; not routed bank, oscillator phase noise, PVT45 or adopted sizing')
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return c


def read(c,name):
    for d in reversed([c/name]+sorted(c.glob(name+'.r[0-9]*'))):
        try:
            ex=json.loads((d/'execution.json').read_text())
            if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:continue
            if (d/'tb.cir').read_bytes()!=(c/'prepared'/(name+'.cir')).read_bytes():continue
            rows=[]
            for state in ('off','on'):
                for fi,f in enumerate((1e6,20e6,2e9)):
                    x=np.atleast_2d(np.loadtxt(d/f'{state}_{fi}.tsv',skiprows=1))
                    if x.shape!=(1,10) or not np.isfinite(x).all() or abs(x[0,0]/f-1)>1e-9:raise ValueError('Incomplete AC row')
                    if not np.allclose(x[0,2::3],0,atol=1e-25,rtol=0):raise ValueError('Unexpected imaginary metric')
                    for i,(label,nf,w) in enumerate(WIDTHS):
                        cap=float(x[0,1+3*i]);g=float(x[0,3+3*i]);q=2*np.pi*f*cap/g if g>0 else None
                        rows.append(dict(state=state,hz=f,variant=label,width_per_unit_um=nf*w/8,
                            cap_ff=cap*1e15,conductance_s=g,q=float(q) if q else None))
            return dict(run=str(d.relative_to(ROOT)),rows=rows,elapsed_s=ex['elapsed_s'])
        except (OSError,KeyError,ValueError):continue
    return None


def resume(c):
    p=json.loads((c/'plan.json').read_text())
    if p['pdk_id']!=project.pdk_installation_id() or p['model_sha256']!=sha(project.model_library()):raise ValueError('PDK changed')
    for n,h in p['inputs'].items():
        if sha(c/n)!=h:raise ValueError('Input changed')
    if len(watch.ngspice_cwds())+2>4:raise ValueError('Global NG quota occupied')
    if spice.case_output(c,'smoke','smoke.raw',t_end=1e-9) is None:
        d=spice.next_run_dir(c,'smoke');ex=spice.run((c/'prepared/smoke.cir').read_text(),d,timeout_s=180)
        if not ex.ok or spice.Waves(d/'smoke.raw').t[-1]<1e-9*(1-1e-9):raise ValueError('Smoke failed')
    jobs=[((c/'prepared'/(e[0]+'.cir')).read_text(),spice.next_run_dir(c,e[0]),dict(timeout_s=300)) for e in p['conditions'] if read(c,e[0]) is None]
    if jobs:spice.run_many(jobs,workers=2,smoke=False)
    rows=[]
    for e in p['conditions']:
        r=read(c,e[0])
        if r is None:raise ValueError('Incomplete condition '+e[0])
        rows.append(dict(condition=e,**r))
    dest=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');dest.mkdir(parents=True)
    shutil.copyfile(Path(__file__),dest/'analysis.py')
    (dest/'summary.json').write_text(json.dumps(dict(campaign=str(c.relative_to(ROOT)),scope=p['scope'],plan_sha256=sha(c/'plan.json'),rows=rows),indent=2,allow_nan=False)+'\n')
    print(dest/'summary.json',flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);a=ap.parse_args()
    if a.prepare:print(prepare())
    else:resume(a.resume.resolve())
