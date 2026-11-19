"""Physical SVT/LVT/native switch alternatives: Q, Coff, Ron and leakage."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np
from serdes_flow import bias,project,spice,watch

ROOT=project.ROOT
sys.path.insert(0,str(ROOT/'analog/pll/vco/layout'))
from build_fused_cap_bank import group

DEVICES=[('svt','nfet_01v8',.15),('lvt','nfet_01v8_lvt',.15),('native3','nfet_03v3_nvt',.5),('native5','nfet_05v0_nvt',.9)]
CONDITIONS=[('tt','tt','tt',1.8,27),('fs_hot_hh','fs','hh',1.65,85),('ss_hot_hh','ss','hh',1.65,85),
            ('ss_cold_hh','ss','hh',1.65,-40),('ff_hot_ll','ff','ll',1.95,85),('sf_hot_ll','sf','ll',1.95,85)]


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    c=ROOT/'results/analog/pll/vco/switch_devices'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');c.mkdir(parents=True)
    (c/'inputs').mkdir();(c/'prepared').mkdir();direct=[];physical=[]
    for i,(label,short,length) in enumerate(DEVICES):
        model='sky130_fd_pr__'+short;d=c/label;d.mkdir()
        # Native models have narrow discrete width bins; 0.5um fingers are
        # physically drawable but outside their installed SPICE bins.
        # Use 4x1um for all four alternatives, keeping total W=4um.
        name,cell,ref=group(d,8,4.6,7.56,switch_fingers=4,finger_w=1,switch_model=model,switch_l=length)
        net=(d/(name+'_cap.spice')).read_text();plate=re.search(r'^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b',net,re.M)[1]
        mos=[line for line in net.splitlines() if re.search(r'\b'+model+r'\b',line)]
        if len(mos)!=4:raise ValueError('MOS finger count differs')
        for j,line in enumerate(mos):
            parts=line.split();parts[0]=f'Xtest{i}_{j}'
            for k in (1,3):parts[k]='dt'+str(i) if parts[k]==plate else '0' if parts[k]=='vss' else parts[k]
            parts[2]='gt';parts[4]='0';direct.append(' '.join(parts))
        net=net.replace(name,label);net=re.sub(r'^\.ends.*$',f'Rdc {plate} vss 125g\n.ends',net,flags=re.M)
        (c/'inputs'/(label+'.spice')).write_text(net)
        physical.append(dict(label=label,model=model,length_um=length,total_width_um=4,fingers=4,finger_w_um=1,bbox_um=cell.bbox(),drc=0,lvs=True))
    texts={}
    for label,process,rc,vdd,temp in CONDITIONS:
        body=['MOS alternative local comparison',f'.lib "{project.model_library()}" tt',f'.temp {temp}','Ven en 0 0','Vgtest gt 0 0']
        for i,(name,_,_) in enumerate(DEVICES):body += [f'.include "{c}/inputs/{name}.spice"',f'Vp{i} q{i} 0 dc 1.5 ac 1',f'X{i} q{i} en 0 {name}',f'Vdt{i} dt{i} 0 .1']
        body+=direct
        ctl=['.control','set num_threads=1','set wr_singlescale','set wr_vecnames','set numdgt=12']
        for vi,vd in enumerate((.1,.3,.6)):
            ctl += ['alter Vgtest dc=0']+[f'alter Vdt{i} dc={vd}' for i in range(4)]+['op']
            ctl += [f'let ileak{i}=-i(vdt{i})' for i in range(4)]
            ctl += [f'wrdata leak{vi}.tsv '+' '.join(f'ileak{i}' for i in range(4)),'destroy all']
        ctl += [f'alter Vgtest dc={vdd}']+[f'alter Vdt{i} dc=.01' for i in range(4)]+['op']
        ctl += [f'let ron{i}=.01/(-i(vdt{i}))' for i in range(4)]+['wrdata ron.tsv '+' '.join(f'ron{i}' for i in range(4)),'destroy all']
        for state,v in [('off',0),('on',vdd)]:
            ctl += [f'alter Ven dc={v}','ac lin 1 2e9 2e9']
            for i in range(4):ctl += [f'let c{i}=-imag(i(vp{i}))/(2*pi*frequency)',f'let g{i}=-real(i(vp{i}))']
            ctl += [f'wrdata {state}.tsv '+' '.join(f'c{i} g{i}' for i in range(4)),'destroy all']
        deck=bias.section('\n'.join(body+ctl+['quit','.endc','.end','']),process,rc)
        texts[label]=deck;(c/'prepared'/(label+'.cir')).write_text(deck)
    smoke=texts['tt'].split('.control')[0]+'\n.save v(q0)\n.control\nset num_threads=1\ntran 2p 1n 0 2p\nwrdata smoke.tsv v(q0)\nquit\n.endc\n.end\n'
    smoke=spice.binary_output(spice.skip_output_before(smoke,'0.2n'));(c/'prepared/smoke.cir').write_text(smoke)
    for p in (Path(__file__).resolve(),ROOT/'analog/pll/vco/layout/build_fused_cap_bank.py'):
        d=c/'source'/p.name;d.parent.mkdir(exist_ok=True);shutil.copyfile(p,d)
    plan=dict(devices=physical,conditions=CONDITIONS,pdk_id=project.pdk_installation_id(),model_sha256=sha(project.model_library()),
              snapshots={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()})
    (c/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    if len(watch.ngspice_cwds())+2>4:raise ValueError('NG slots occupied')
    ex=spice.run(smoke,c/'smoke',timeout_s=180)
    if not ex.ok or spice.Waves(c/'smoke/smoke.raw').t[-1]<1e-9*(1-1e-9):raise ValueError('Smoke failed')
    runs=spice.run_many([(text,c/name,dict(timeout_s=300)) for name,text in texts.items()],workers=2,smoke=False)
    if any(not ex.ok for ex in runs):raise ValueError('Device card execution failed')
    rows=[]
    for e in CONDITIONS:
        d=c/e[0];measurements={name:dict(device=physical[i]) for i,(name,_,_) in enumerate(DEVICES)}
        for name in ('off','on'):
            x=np.atleast_2d(np.loadtxt(d/(name+'.tsv'),skiprows=1))
            if x.shape!=(1,13) or not np.isfinite(x).all() or abs(x[0,0]/2e9-1)>1e-9 or not np.allclose(x[0,2::3],0,atol=1e-25,rtol=0):raise ValueError('Incomplete AC result')
            for i,(label,_,_) in enumerate(DEVICES):
                cap=float(x[0,1+3*i]);g=float(x[0,3+3*i])
                measurements[label][name]=dict(cap_ff=cap*1e15,conductance_s=g,q=2*np.pi*2e9*cap/g if g>0 else None)
        for file,field in [('ron.tsv','ron_ohm'),('leak0.tsv','off_current_vds010_a'),('leak1.tsv','off_current_vds030_a'),('leak2.tsv','off_current_vds060_a')]:
            x=np.atleast_2d(np.loadtxt(d/file,skiprows=1))
            if x.shape!=(1,5) or not np.isfinite(x).all():raise ValueError('Incomplete DC result')
            for i,(label,_,_) in enumerate(DEVICES):measurements[label][field]=float(x[0,i+1])
        rows.append(dict(condition=e,measurements=measurements,run=str(d.relative_to(ROOT))))
    result=dict(campaign=str(c.relative_to(ROOT)),plan_sha256=sha(c/'plan.json'),rows=rows,
        scope='Four actual physical isolated cap/switch blocks W4um/nf4 (1um fingers within all installed model bins), minimum PCell lengths per model; nodeDC1.5V at2GHz, gate0/VDD. Separate transistor-only DC tests at Vds10mV(on) or .1/.3/.6V(off). No complete bank, oscillator/noise/MC/adoption qualification')
    (c/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(c/'summary.json',flush=True)


if __name__=='__main__':main()
