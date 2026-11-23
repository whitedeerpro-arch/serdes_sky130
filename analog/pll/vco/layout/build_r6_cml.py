"""Current r6 delay and extraction buffer from actual PDK devices.

Four identical input groups in A B B A order have coincident centroids.
Each side retains the schematic's total W and finger count; splitting its
array adds source-end diffusion, which must be included in backannotation.
Independent guard contacts, equal-length input routes and equal output rails
are explicit. Resistor bodies go to VSS; buffer loads follow the current
fixed-width resistor mapping, rounded to the 5nm manufacturing grid.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402


def grid(x: float) -> float:
    return round(round(x / .005) * .005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, .5)
    c.pad("via3", x, y, .32)
    c.pad("metal4", x, y, .5)


def build(work: Path, kind: str) -> dict:
    delay = kind == "delay"
    name = "pll_vco_delay_r6_pdk" if delay else "pll_buffer_r6_pdk"
    finger_w, nf_group, tail_w = (5., 4, 6.3) if delay else (3., 2, 3.)
    target_length = 4.77 if delay else (600. - 137.6) / 111.8
    # This centered resistor generator quantizes two ends on a 5nm grid,
    # so its effective length quantum is 10nm.
    length = round(target_length,2)
    inp = pdk_device(work, "input_pdk", "sky130_fd_pr__nfet_01v8_lvt",
                     dict(w=finger_w, l=.15, nf=nf_group, conn_gates=1))
    tail = pdk_device(work, "tail_pdk", "sky130_fd_pr__nfet_01v8",
                      dict(w=tail_w, l=.5, nf=4, conn_gates=1))
    load = pdk_device(work, "load_pdk", "sky130_fd_pr__res_high_po_2p85", dict(l=length))
    # checkpaint is an editing/checking region, not a physical obstruction.
    for primitive in (inp, tail, load):
        primitive.rects.pop("checkpaint", None)
    c = Cell()
    pitch = 5.6 if delay else 3.4
    xs = [grid(x*pitch) for x in [-1.5,-.5,.5,1.5]]
    gx, gy = inp.pins("G")[0]
    body_y = inp.pins("B")[0][1]
    source_y = grid(body_y - .915)
    gates_y = [grid(source_y-1.), grid(source_y-2.)]
    outputs_y = [grid(gy+1.625), grid(gy+2.625)]
    body_rail = grid(outputs_y[1]+.9)
    load_y = grid(body_rail+.67-load.pins("B")[0][1])
    vdd_y = grid(load_y+load.pins("R1")[0][1]+.91)
    tail_y = grid(gates_y[1]-tail.bbox()[3]-1.6)
    ground_y = grid(tail_y+tail.bbox()[1]-2.)
    side_x = grid(xs[-1]+2.5)
    placed = []

    # Each input group has its own identical PDK guard. Odd diffusion stripes
    # are the shared drains; even stripes are sources to the common tail.
    for i, x in enumerate(xs):
        branch = 0 if i in (0,3) else 1
        mirror = x > 0
        sign = -1 if mirror else 1
        c.include(inp, dx=x, mirror_x=mirror)
        sd = sorted({grid(sign*(r[0]+r[2])/2+x) for r in inp.rects["ndiffc"]})
        contact_y = grid(finger_w/2-.5)
        for k,sx in enumerate(sd):
            y = contact_y if k%2 else -contact_y
            c.via1(sx,y)
        drains, sources = sd[1::2], sd[::2]
        if len(drains)>1:
            c.wire("metal2",[(drains[0],contact_y),(drains[-1],contact_y)],.32)
        c.wire("metal2",[(sources[0],-contact_y),(sources[-1],-contact_y)],.32)
        source_escape = sources[-1] if mirror else sources[0]
        c.wire("metal2",[(source_escape,-contact_y),(source_escape,source_y)],.32)
        # M3 risers cross the other output's M4 rail without a via.
        c.wire("metal2",[(drains[0],contact_y),(x,contact_y)],.32)
        c.via2(x,contact_y)
        c.wire("metal3",[(x,contact_y),(x,outputs_y[branch])],.4)
        via3(c,x,outputs_y[branch])
        bx = grid(x+sign*inp.pins("B")[0][0])
        escape = grid(x + (1.6 if mirror else -1.6))
        c.body_contact(bx,body_y)
        # Cross the tail-source M2 descent on M3, otherwise this body strap
        # would short the common tail to VSS below each input group.
        body_lift = grid(bx+(-.25 if mirror else .25))
        c.wire("metal2",[(bx,body_y),(body_lift,body_y)],.32)
        c.via2(body_lift,body_y)
        c.wire("metal3",[(body_lift,body_y),(escape,body_y)],.4)
        c.via2(escape,body_y)
        c.wire("metal2",[(escape,body_y),(escape,body_rail)],.32)
        gate_x = grid(x+sign*gx)
        # Outer A routes make a .5um upward dogleg: both A/B vertical totals
        # and both input rail lengths then match, despite staggered tracks.
        top = grid(gy+.5) if branch == 0 else gy
        points = [(gate_x,gy)]
        if top != gy:
            points.append((gate_x,top))
        points += [(escape,top),(escape,gates_y[branch])]
        c.wire("metal1",points,.22)
        c.via1(escape,gates_y[branch])
        placed.append(dict(group=i,branch="A" if branch == 0 else "B",center_um=[x,0],mirror_x=mirror))
    for y in outputs_y:
        c.wire("metal4",[(xs[0],y),(xs[-1],y)],.5)
    for y in gates_y:
        c.wire("metal2",[(xs[0]-1.6,y),(xs[-1]+1.6,y)],.32)
    c.wire("metal2",[(xs[0]-.96,source_y),(xs[-1]+.96,source_y)],.6)

    c.include(tail,dy=tail_y)
    sd = sorted({grid((r[0]+r[2])/2) for r in tail.rects["ndiffc"]})
    dy = grid(tail_w/2-.5)
    for k,x in enumerate(sd):
        c.via1(x,grid(tail_y+(dy if k%2 else -dy)))
    drains, sources = sd[1::2],sd[::2]
    td, ts = grid(tail_y+dy),grid(tail_y-dy)
    c.wire("metal2",[(drains[0],td),(drains[-1],td)],.5)
    c.via2(0,td)
    c.wire("metal3",[(0,td),(0,source_y)],.7)
    c.via2(0,source_y)
    c.wire("metal2",[(-side_x,ts),(side_x,ts)],.7)
    bx,by = tail.pins("B")[0]
    by = grid(by+tail_y)
    c.body_contact(bx,by)
    c.wire("metal2",[(bx,by),(bx,ground_y)],.5)
    tgx,tgy=tail.pins("G")[0]
    tgy=grid(tgy+tail_y)
    bias_x=grid(-tail.bbox()[2]-.8)
    c.wire("metal1",[(tgx,tgy),(bias_x,tgy),(bias_x,ground_y+1.)],.22)
    c.via1(bias_x,ground_y+1.)

    load_places = list(zip(xs,[0,1,1,0])) if delay else [(-pitch,0),(pitch,1)]
    for x,branch in load_places:
        c.include(load,dx=x,dy=load_y)
        _,ry=load.pins("R2")[0]
        y=grid(ry+load_y)
        c.via1(x,y)
        c.via2(x,y)
        c.wire("metal3",[(x,y),(x,outputs_y[branch])],.4)
        via3(c,x,outputs_y[branch])
        _,ry=load.pins("R1")[0]
        y=grid(ry+load_y)
        c.via1(x,y)
        c.wire("metal2",[(x,y),(x,vdd_y)],.6)
        bx,by=load.pins("B")[0]
        bx,by=grid(bx+x),grid(by+load_y)
        c.body_contact(bx,by)
        c.wire("metal2",[(bx,by),(bx,body_rail)],.4)
    c.wire("metal2",[(-side_x,vdd_y),(side_x,vdd_y)],1.)
    c.wire("metal2",[(-side_x,body_rail),(side_x,body_rail)],.7)
    c.wire("metal2",[(-side_x,ground_y),(side_x,ground_y)],1.)
    for x in [-side_x,side_x]:
        c.wire("metal2",[(x,ground_y),(x,body_rail)],.7)
    branch_outputs = ["outp","outn"] if delay else ["outn","outp"]
    c.port("inp","metal2",0,gates_y[0])
    c.port("inn","metal2",0,gates_y[1])
    for label in ["outp","outn"]:
        b=branch_outputs.index(label)
        c.port(label,"metal4",xs[0] if label == "outp" else xs[-1],outputs_y[b])
    c.port("vbias","metal2",bias_x,ground_y+1.)
    c.port("vdd","metal2",0,vdd_y)
    c.port("vss","metal2",0,ground_y)
    c.write(work/f"{name}.mag")
    # Fixed, design-derived reference is independent of the extracted result.
    total_w = 40 if delay else 12
    ref = [f".subckt {name} inp inn outp outn vbias vdd vss",
           f"Xp {branch_outputs[0]} inp tail vss sky130_fd_pr__nfet_01v8_lvt w={total_w} l=.15",
           f"Xn {branch_outputs[1]} inn tail vss sky130_fd_pr__nfet_01v8_lvt w={total_w} l=.15",
           f"Xt tail vbias vss vss sky130_fd_pr__nfet_01v8 w={tail_w*4:g} l=.5"]
    for i,(_,branch) in enumerate(load_places):
        ref.append(f"Xr{i} vdd {branch_outputs[branch]} vss sky130_fd_pr__res_high_po_2p85 l={length:g}")
    ref.append(f".ends {name}\n")
    (work/"reference.spice").write_text("\n".join(ref))
    p=subprocess.run([sys.executable,str(REPO/"verification/layout/check.py"),str(work),name,
                      "--ref",str(work/"reference.spice")],capture_output=True,text=True)
    (work/"check.log").write_text(p.stdout+p.stderr)
    print(p.stdout+p.stderr,flush=True)
    net=(work/f"{name}_lvs.spice").read_text()
    mos=re.findall(r"^X\S+ (\S+) (\S+) (\S+) vss (sky130_fd_pr__nfet_01v8\S*) .* w=(\S+) l=(\S+)$",net,re.M)
    tail_nodes={n for m in mos if m[1] == "vbias" for n in [m[0],m[2]] if n != "vss"}
    if len(tail_nodes) != 1:
        raise ValueError("Tail must be one internal net separate from VSS")
    tail_node=tail_nodes.pop()
    if len(mos) != nf_group*4+4:
        raise ValueError("Unexpected MOS count or body connection")
    expected={"inp":(total_w,nf_group*2),"inn":(total_w,nf_group*2),"vbias":(tail_w*4,4)}
    for gate,(width,count) in expected.items():
        got=[m for m in mos if m[1]==gate]
        if len(got)!=count or abs(sum(float(m[4]) for m in got)-width)>1e-9:
            raise ValueError(f"Finger count / total width mismatch: {gate}")
        for d,g,s,model,w,l in got:
            nodes={d,s}
            want={"vss", tail_node} if gate=="vbias" else {tail_node,branch_outputs[0 if gate=="inp" else 1]}
            want_model="sky130_fd_pr__nfet_01v8"+("" if gate=="vbias" else "_lvt")
            if (nodes != want or float(l)!=(.5 if gate=="vbias" else .15)
                    or float(w)!=(tail_w if gate=="vbias" else finger_w) or model!=want_model):
                raise ValueError(f"Invalid device topology: {(d,g,s,model,w,l)}")
    resistors=re.findall(r"^X\S+ (\S+) (\S+) vss sky130_fd_pr__res_high_po_2p85 l=(\S+)$",net,re.M)
    if len(resistors)!=len(load_places) or any(float(l)!=length or {a,b} not in [{"vdd","outp"},{"vdd","outn"}] for a,b,l in resistors):
        raise ValueError("Incorrect resistor geometry, count or body")
    report=dict(cell=name,checker_exit=p.returncode,bbox_um=c.bbox(),input_groups=placed,
                physical_fingers=len(mos),resistors=len(resistors),input_width_per_side_um=total_w,
                resistor_target_length_um=target_length,resistor_grid_length_um=length,
                matching="ABBA equal group centroids; mirror placement; matched input route lengths/output rails",
                backannotation_required="actual AD/AS, extra source ends and all interconnect capacitances; no mismatch qualification")
    (work/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
    if p.returncode:
        raise RuntimeError(f"Physical checks failed: {work/'check.log'}")
    return report


def main() -> None:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind",choices=["delay","buffer"],required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    args=ap.parse_args()
    out=args.output_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)
    build(out,args.kind)


if __name__=="__main__":
    main()
