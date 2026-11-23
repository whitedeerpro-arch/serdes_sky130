"""Physical candidate: one TT-retargeted MIM per bit, original switch fingers.

Produces its own physical reference and logical-to-physical map. This is a
new capacitor geometry, not an LVS-equivalent drawing of the adopted r6.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from serdes_flow import cap_fusion, project, spice

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / 'verification/layout'))
from geometry import Cell, pdk_device
from flat_cap_export import export

MODEL = 'sky130_fd_pr__cap_mim_m3_1'
TOP = 'pll_vco_cap_bank5_fused'


def checked(work, name, reference):
    ref = work / 'reference.spice'
    ref.write_text(reference)
    proc = subprocess.run([sys.executable, str(ROOT/'verification/layout/check.py'), str(work), name,
                           '--ref', str(ref)], capture_output=True, text=True)
    (work/'check.log').write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError(f'Physical check failed: {work}/check.log\n{proc.stdout[-1500:]}')
    audit = export(work/(name+'.ext'), work/(name+'_lvs.spice'), work/(name+'_cap.spice'))
    (work/'cap_export_audit.json').write_text(json.dumps(audit, indent=2)+'\n')
    print(name, 'DRC/LVS/export passed', flush=True)


def group(work, n, width, length=None, *, switch_fingers=None, finger_w=.75,
          switch_model='sky130_fd_pr__nfet_01v8', switch_l=.15, body_wire_um=.5,
          solid_ground_return=False):
    length=width if length is None else length
    nf=2*n if switch_fingers is None else switch_fingers
    if finger_w<.42 or nf<1:raise ValueError('Outside nfet PCell width/finger guard')
    name = f'pll_vco_fused_group{n}'
    sw = pdk_device(work, 'switch_pdk', switch_model,
                    dict(w=finger_w, l=switch_l, nf=nf, conn_gates=1))
    mim = pdk_device(work, 'mim_pdk', MODEL, dict(w=width, l=length, stack=0))
    tx, ty = mim.pins('C1')[0]
    # The lower electrode connects directly down to the switch on M3.
    # Remove the redundant M4 bottom-contact sleeve and its via3 array.
    lo,hi=tx-width/2,tx+width/2
    bottom,top=ty-length/2,ty+length/2
    mim.rects['metal3']=[(lo-.14,bottom-.14,hi+.14,top+.14)]
    mim.rects.pop('via3',None)
    mim.rects['metal4']=[r for r in mim.rects['metal4']
                        if r[0]<hi and r[2]>lo and r[1]<top and r[3]>bottom]
    c = Cell()
    c.include(sw)
    cy = 2.4 + length/2
    c.include(mim, dx=-tx, dy=cy-ty)
    contact_layer='mvndiffc' if 'mvndiffc' in sw.rects else 'ndiffc'
    xs = sorted({(r[0]+r[2])/2 for r in sw.rects[contact_layer]})
    if len(xs) != nf+1:
        raise ValueError('Switch finger geometry changed')
    drains,sources=xs[1::2],xs[::2]
    for i, x in enumerate(xs):
        c.via1(x, 0)
        c.wire('metal2', [(x, 0), (x, .5 if i%2 else -.9)], .28)
    if len(drains)>1:
        c.wire('metal2', [(drains[0], .5), (drains[-1], .5)], .28)
    c.wire('metal2', [(sources[0], -.9), (sources[-1], -.9)], .28)
    bx, by = sw.pins('B')[0]
    c.body_contact(bx, by)
    c.wire('metal2', [(bx, by), (bx, -.9)], body_wire_um)
    if solid_ground_return:
        # Close shallow same-net notches between body landing and source rail.
        c.rect('metal2', min(sources[0]-.16, bx-.25), by-.16,
               max(sources[-1]+.16, bx+.25), -.74)
    mid=drains[len(drains)//2]
    c.wire('metal2', [(mid, .5), (mid, 1.25), (0, 1.25)], .28)
    c.via2(0, 1.25)
    c.wire('metal3', [(0, 1.25), (0, 2.5)], .5)
    gx, gy = sw.pins('G')[0]
    c.wire('metal1', [(gx, gy), (gx, 1.8)], .26)
    c.via1(gx, 1.8)
    c.port('node', 'mimcapcontact', 0, cy)
    c.port('en', 'metal2', gx, 1.8)
    c.port('vss', 'metal2', bx, by)
    c.write(work/(name+'.mag'))
    ref = f'.subckt {name} node en vss\nXcap node plate {MODEL} w={width:g} l={length:g}\n'
    ref += f'Xsw plate en vss vss {switch_model} w={finger_w*nf:g} l={switch_l} nf={nf}\n.ends {name}\n'
    checked(work, name, ref)
    return name, c, ref


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output-dir', type=Path)
    a = ap.parse_args()
    work = a.output_dir or ROOT/'results/layout/capacitor_fusion'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    work = work.resolve(); work.mkdir(parents=True, exist_ok=False)
    nominal, model_files = cap_fusion.installed()
    unit = nominal.cap_ff(2, 2)
    parts=[]
    for n in (1,2,4,8,16):
        side=cap_fusion.rounded_square(n*unit,grid_um=.01)
        if not 2<=side<=cap_fusion.maximum_square_um():raise ValueError('Outside installed PCell dimension guard')
        sub=work/f'n{n}';sub.mkdir()
        parts.append((side,*group(sub,n,side)))
    common_top=max(cell.bbox()[3] for _,_,cell,_ in parts)
    rail_y=common_top+.64
    result = Cell(); cursor = 0.; points = []; refs = []; mapping = []
    for bit, n in enumerate((1,2,4,8,16)):
        side,name,cell,ref=parts[bit]
        x1,y1,x2,y2 = cell.bbox();dx = cursor-x1;dy = common_top-y2
        result.include(cell, dx=dx, dy=dy)
        qx,qy = cell.pins('node')[0]; qx+=dx;qy+=dy;points.append((qx,qy))
        result.wire('metal4', [(qx,qy),(qx,rail_y)], .32)
        bx,by = cell.pins('vss')[0];bx+=dx;by+=dy
        result.wire('metal2', [(bx,by),(bx,-2.4)], .5)
        gx,gy = cell.pins('en')[0];gx+=dx;gy+=dy;escape=cursor-.6
        result.wire('metal1', [(gx,gy),(escape,gy),(escape,-4)], .26)
        result.via1(escape,-4);result.port(f'b{bit}','metal2',escape,-4)
        cursor += x2-x1+2.;refs.append(ref)
        mapping.append(dict(bit=bit, logical_units=n, logical_mim_um=[2,2],
            physical_mim_um=[side,side], physical_instances=1,
            logical_instances=[f'X{bit}_{i}.Xcap' for i in range(n)], physical_instance=f'Xg{bit}.Xcap',
            target_nominal_ff=n*unit, actual_nominal_ff=nominal.cap_ff(side,side),
            model_value_error=nominal.cap_ff(side,side)/(n*unit)-1,
            switch_finger_w_um=.75, switch_fingers=2*n,
            topology='one shared floating plate per bit; differs from adopted independent plates',
            group=name, bbox_um=[x1+dx,y1+dy,x2+dx,y2+dy]))
    result.wire('metal4',[(points[0][0],rail_y),(points[-1][0],rail_y)],.5)
    result.wire('metal2',[(0,-2.4),(cursor-2,-2.4)],1.)
    root=sum(p[0]*n for p,n in zip(points,(1,2,4,8,16)))/31
    labels=result.labels;result.labels=[]
    result.port('node','metal4',root,rail_y);result.labels+=labels;result.port('vss','metal2',root,-2.4)
    result.write(work/(TOP+'.mag'))
    refs += [f'.subckt {TOP} node b0 b1 b2 b3 b4 vss']
    refs += [f'Xg{bit} node b{bit} vss {m["group"]}' for bit,m in enumerate(mapping)]
    refs += [f'.ends {TOP}\n']
    checked(work,TOP,'\n'.join(refs))
    net=(work/(TOP+'_lvs.spice')).read_text()
    caps=re.findall(r'^X\S+ node (\S+) '+MODEL+r' l=([\d.]+) w=([\d.]+)$',net,re.M)
    if len(caps)!=5 or len({c[0] for c in caps})!=5:
        raise ValueError('Expected five independent floating plates and five MIMs')
    for bit,m in enumerate(mapping):
        mos=re.findall(r'^X\S+ (\S+) b'+str(bit)+r' (\S+) vss sky130_fd_pr__nfet_01v8 .* w=0.75 l=0.15$',net,re.M)
        plates={a if a!='vss' else b for a,b in mos}
        if len(mos)!=m['switch_fingers'] or len(plates)!=1:
            raise ValueError('Finger count or bit connectivity changed')
        plate=plates.pop();m['extracted_plate']=plate
        cap=next(c for c in caps if c[0]==plate)
        if any(abs(float(v)-m['physical_mim_um'][0])>1e-6 for v in cap[1:]):
            raise ValueError('Extracted MIM dimensions differ from generated reference')
    bx1,by1,bx2,by2=result.bbox()
    files=[Path(__file__).resolve(),Path(cap_fusion.__file__),*model_files,
           ROOT/'verification/layout/geometry.py',ROOT/'verification/layout/flat_cap_export.py']
    for p in files:
        dst=work/'source'/p.name;dst.parent.mkdir(exist_ok=True);shutil.copyfile(p,dst)
    summary=dict(cell=TOP,mapping=mapping,bbox_um=[bx1,by1,bx2,by2],area_um2=(bx2-bx1)*(by2-by1),
        mim_count=5,mos_fingers=62,drc=0,lvs=True,ports=['node','b0','b1','b2','b3','b4','vss'],
        pcell_max_square_um=cap_fusion.maximum_square_um(),pdk_id=project.pdk_installation_id(),
        scope='Candidate only: TT main MIM capacitance retarget, physical DRC/LVS; not electrical/PVT/mismatch/switching or adopted r6 qualification',
        sha256={str(p.relative_to(work)):hashlib.sha256(p.read_bytes()).hexdigest() for p in work.rglob('*') if p.is_file()})
    (work/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(work,flush=True)


if __name__=='__main__': main()
