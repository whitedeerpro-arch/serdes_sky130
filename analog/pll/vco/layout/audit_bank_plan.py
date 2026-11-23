"""Audit actual rectangular bank-plan blocks without changing the floorplan.

Builds isolated physical block cards at the drawn dimensions and at a nearby
PDK-main-C retarget. All keep the adopted switch width; not the plan's separate
switch-shrinking proposal, nor a routed nine-block bank qualification.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import cap_fusion, project, spice, watch
from build_fused_cap_bank import group

ROOT=project.ROOT


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--plan',type=Path,required=True);a=ap.parse_args()
    src=a.plan.resolve();plan=json.loads(src.read_text());m,files=cap_fusion.installed()
    out=ROOT/'results/layout/capacitor_fusion_plan'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    source=out/'source';source.mkdir()
    for p in [src,src.with_name('plan_cap_bank.py'),Path(__file__).resolve(),Path(cap_fusion.__file__),Path(__file__).with_name('build_fused_cap_bank.py'),*files]:
        shutil.copyfile(p,source/p.name)
    cards=[];records=[]
    for bit in ('b0','b2','b3','b4'):
        b=plan['blocks'][bit];n=b['units_eq']//b['count'];w=b['w_um'];length=b['l_um']
        exact=m.length_um(n*m.cap_ff(2,2),w)
        choices=[np.floor(exact/.01)*.01,np.ceil(exact/.01)*.01]
        adjusted=round(min(choices,key=lambda l:abs(m.cap_ff(w,l)-n*m.cap_ff(2,2))),2)
        record=dict(bit=bit,blocks=b['count'],logical_units_per_block=n,drawn_um=[w,length],
            main_c_drawn_ff=m.cap_ff(w,length),main_c_target_ff=n*m.cap_ff(2,2),
            main_c_drawn_relative_error=m.cap_ff(w,length)/(n*m.cap_ff(2,2))-1,
            length_exact_main_c_match_um=exact,main_c_matched_um=[w,adjusted],
            domain='MIM upper=node; lower=local floating plate; same bit only',
            boundary='same original switch W1.5um/logical unit; .75um fingers; no W shrink')
        records.append(record)
        for variant,l in [('drawn',length),('matched',adjusted)] if bit!='b0' else [('drawn',length)]:
            label=variant+'_'+bit;work=out/label;work.mkdir()
            name,cell,ref=group(work,n,w,l)
            text=(work/(name+'_cap.spice')).read_text()
            cap=re.search(r'^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1 l=([\d.]+) w=([\d.]+)$',text,re.M)
            if cap is None or abs(float(cap[2])-l)>1e-6 or abs(float(cap[3])-w)>1e-6:
                raise ValueError('Extracted rectangle differs from plan-derived dimensions')
            text=text.replace(name,label)
            text=re.sub(r'^\.ends.*$',f'Rdc {cap[1]} vss {1e12/n:.12g}\n.ends',text,flags=re.M)
            (out/(label+'.spice')).write_text(text)
            cards.append(dict(label=label,bit=bit,variant=variant,n=n,path=label+'.spice',width_um=w,length_um=l,bbox_um=cell.bbox()))
    prefix=['Rectangular plan block AC; no routed bank interactions',f'.lib "{project.model_library()}" tt','.temp 27','Ven en 0 0']
    for i,c in enumerate(cards):prefix += [f'.include "{out/c["path"]}"',f'Vp{i} q{i} 0 dc 1.5 ac 1',f'X{i} q{i} en 0 {c["label"]}']
    smoke='\n'.join(prefix)+'\n.save v(q0)\n.control\nset num_threads=1\ntran 2p 1n 0 2p\nwrdata smoke.tsv v(q0)\nquit\n.endc\n.end\n'
    smoke=spice.binary_output(spice.skip_output_before(smoke,'0.2n'))
    ctl=['.control','set num_threads=1','set wr_singlescale','set wr_vecnames','set numdgt=12']
    for state,v in [('off',0),('on',1.8)]:
        ctl += [f'alter Ven dc={v}']
        for fi,f in enumerate((1e6,2e9)):
            ctl += [f'ac lin 1 {f} {f}']
            ctl += [f'let c{i}=-imag(i(vp{i}))/(2*pi*frequency)' for i in range(len(cards))]
            ctl += [f'wrdata {state}_{fi}.tsv '+' '.join(f'c{i}' for i in range(len(cards))),'destroy all']
    text='\n'.join(prefix+ctl+['quit','.endc','.end',''])
    (out/'prepared.cir').write_text(text);(out/'smoke.cir').write_text(smoke)
    snapshots={str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()}
    (out/'inputs.json').write_text(json.dumps(dict(plan_path=str(src.relative_to(ROOT)),plan_sha256=sha(src),
        pdk_id=project.pdk_installation_id(),model_sha256=sha(project.model_library()),snapshots=snapshots),indent=2)+'\n')
    if len(watch.ngspice_cwds())>=4:raise ValueError('Global NG slots occupied')
    for name,deck in [('smoke',smoke),('ac',text)]:
        ex=spice.run(deck,out/name,timeout_s=300)
        if not ex.ok:raise ValueError('Local plan card failed')
        if name=='smoke' and spice.Waves(out/name/'smoke.raw').t[-1]<1e-9*(1-1e-9):raise ValueError('Truncated smoke')
    for state in ('off','on'):
        for fi,f in enumerate((1e6,2e9)):
            tab=np.atleast_2d(np.loadtxt(out/'ac'/f'{state}_{fi}.tsv',skiprows=1))
            if tab.shape!=(1,1+2*len(cards)) or not np.isfinite(tab).all() or abs(tab[0,0]/f-1)>1e-9:raise ValueError('Incomplete plan AC table')
            if not np.allclose(tab[0,2::2],0,atol=1e-25,rtol=0):raise ValueError('Unexpected imaginary metric')
            for i,c in enumerate(cards):c[f'{state}_{int(f)}_ff']=float(tab[0,1+2*i]*1e15)
    result=dict(campaign=str(out.relative_to(ROOT)),plan_identity=dict(path=str(src.relative_to(ROOT)),sha256=sha(source/src.name)),
        records=records,cards=cards,
        scope='Isolated rectangles at actual plan dimensions and main-C-matched lengths; original switches; TT27C nodeDC1.5V gates0/1.8V AC1MHz/2GHz; not nine-block routing, matching, switch resizing, oscillator, fullPVT or adoption qualification')
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(out/'summary.json',flush=True)


if __name__=='__main__':main()
