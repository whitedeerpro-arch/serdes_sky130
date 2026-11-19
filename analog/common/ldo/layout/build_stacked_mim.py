"""Independent two-level MIM experiment: M3(b)-M4(a)-M5(b), in parallel.

Use both PDK capacitor generators; align actual recognition plates, connect
every column, and require full DRC/LVS plus exact unmerged device counts.
Original first-layer arrays and installed supply macros remain untouched.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'verification/layout'))
from geometry import Cell,pdk_device
import magicutil as mu

M1='sky130_fd_pr__cap_mim_m3_1'
M2='sky130_fd_pr__cap_mim_m3_2'
SIDE=22.1965


def plates(cell,layer):
    return sorted(cell.rects[layer],key=lambda r:(r[0],r[1]))


def draw(out,units,cols):
    if units<2 or units%2 or (units//2)%cols:raise ValueError('Even units; complete parallel array')
    work=out/f'serdes_ldo_stack{units}_pdk';work.mkdir(parents=True,exist_ok=False)
    n=units//2;rows=n//cols
    lower=pdk_device(work,'lower',M1,dict(w=SIDE,l=SIDE,nx=cols,ny=rows,stack=1,doports=1))
    upper=pdk_device(work,'upper',M2,dict(w=SIDE,l=SIDE,nx=cols,ny=rows,doports=1))
    for c in (lower,upper):c.rects.pop('checkpaint',None)
    # Contact recognition rectangles are whole plates; marker frames are split
    # into four rectangles by Magic. Mirror the upper device so its M4 bottom
    # contact is opposite the lower device's M3 contact (otherwise they short).
    lp=plates(lower,'mimcapcontact')
    up=sorted([(-r[2],r[1],-r[0],r[3]) for r in plates(upper,'mimcap2contact')],key=lambda r:(r[0],r[1]))
    if len(lp)!=n or len(up)!=n:raise ValueError('Wrong number of physical recognition plates')
    dx=round((lp[0][0]+lp[0][2]-up[0][0]-up[0][2])/2,3)
    dy=round((lp[0][1]+lp[0][3]-up[0][1]-up[0][3])/2,3)
    for a,b in zip(lp,up):
        if max(abs(a[k]-b[k]-(dx if k%2==0 else dy)) for k in range(4))>.01:
            raise ValueError('PDK stack-compatible arrays do not align')
    a=[(x,y) for ly,x,y,name in lower.labels if name.startswith('C1')]
    b3=[(x,y) for ly,x,y,name in lower.labels if name.startswith('C2')]
    b5=[(-x+dx,y+dy) for ly,x,y,name in upper.labels if name.startswith('C1')]
    if any(len(v)!=cols for v in (a,b3,b5)):raise ValueError('Missing column terminals')
    c=Cell();c.include(lower);c.include(upper,dx=dx,dy=dy,mirror_x=True)
    x1,y1,x2,y2=c.bbox();ya=round(y2+2,3);yb=round(y2+5,3);yg=round(y1-2,3);xg=round(x2+3,3)
    for x,y in a:c.wire('metal4',[(x,y),(x,ya)],.8)
    c.wire('metal4',[(min(x for x,y in a),ya),(max(x for x,y in a),ya)],.8)
    for x,y in b3:c.wire('metal3',[(x,y),(x,yg)],.8)
    c.wire('metal3',[(min(x for x,y in b3),yg),(xg,yg)],.8)
    for x,y in b5:c.wire('metal5',[(x,y),(x,yb)],1.6)
    c.wire('metal5',[(min(x for x,y in b5),yb),(xg,yb)],1.6)
    c.wire('metal3',[(xg,yg),(xg,yb)],.8)
    c.pad('via3',xg,yb,.32);c.pad('metal3',xg,yb,.50)
    c.pad('metal4',xg,yb,1.60);c.pad('via4',xg,yb,1.18);c.pad('metal5',xg,yb,1.60)
    c.port('a','metal4',a[0][0],ya);c.port('b','metal3',xg,yg)
    cell=work.name;mag=work/(cell+'.mag');c.write(mag)
    ref=work/'reference.spice'
    ref.write_text(f'.subckt {cell} a b\n'+'\n'.join(
        f'X{layer}_{k} {"a b" if layer==1 else "b a"} {model} w={SIDE} l={SIDE}'
        for layer,model in [(1,M1),(2,M2)] for k in range(n))+f'\n.ends {cell}\n')
    result=subprocess.run([sys.executable,str(ROOT/'verification/layout/check.py'),str(work),cell,'--ref',str(ref)],capture_output=True,text=True)
    (work/'check.log').write_text(result.stdout+result.stderr)
    print(result.stdout,flush=True)
    if result.returncode:raise ValueError('Stacked MIM DRC/LVS failed; inspect '+str(work/'check.log'))
    text=(work/(cell+'_lvs.spice')).read_text()
    counts={m:len(re.findall(r'^X\S+ \S+ \S+ '+m+r'\b',text,re.M)) for m in (M1,M2)}
    if counts!={M1:n,M2:n}:raise ValueError('Unmerged extracted device counts differ')
    if not re.search(rf'^\.subckt {cell} a b$',text,re.M):raise ValueError('Stacked MIM ports differ')
    for line in text.splitlines():
        if line.startswith('X') and any(m in line for m in (M1,M2)) and set(line.split()[1:3])!={'a','b'}:
            raise ValueError('A capacitor plate is unconnected or shorted')
    box=c.bbox();record=dict(cell=cell,nominal_pf=units,sites=n,grid=[cols,rows],
        bbox_um=box,area_um2=(box[2]-box[0])*(box[3]-box[1]),drc=0,lvs=True,
        model_counts=counts,ports=['a','b'],alignment_um=[dx,dy],
        scope='PDK-recognized two-level MIM leaf; full-rule DRC/LVS; electrical calibration and macro integration separate',
        sources={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in work.glob('*') if p.is_file()})
    (work/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output-dir',type=Path,required=True)
    ap.add_argument('--units',type=int,default=2);ap.add_argument('--cols',type=int,default=1)
    args=ap.parse_args();out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    shutil_source=out/'builder.py';shutil_source.write_bytes(Path(__file__).read_bytes())
    result=draw(out,args.units,args.cols);(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
