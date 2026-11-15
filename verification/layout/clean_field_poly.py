"""Remove electrically floating field-poly islands from a frozen layout candidate.

Only EXT nodes of type `p` absent from every extracted device terminal are
eligible. Their connected poly rectangles must have no poly contacts. Active
gates, resistor dummies and all guard rings remain. The source is never edited.
This trades field-poly edge density for defined electrostatics and simulation;
a future grounded dummy must be replanned with legal contact/guard clearance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shlex
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"verification/layout"))
from geometry import Cell
from review_cell import review,sha256


def touch(a,b):
    return min(a[2],b[2])>=max(a[0],b[0])-1e-8 and min(a[3],b[3])>=max(a[1],b[1])-1e-8


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-dir",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--top",default="pll_vco_core_sym9_s32p5")
    args=ap.parse_args()
    source=args.source_dir.resolve();out=args.output_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)
    old=args.top;new=old+"_clean"
    rows=[shlex.split(l) for l in (source/(old+".ext")).read_text().splitlines() if l.strip()]
    if any(r[0] in {"use","merge","equiv"} for r in rows):raise ValueError("flat unaliased EXT required")
    if [r for r in rows if r[0]=="scale"] != [["scale","1000","1","500000"]]:
        raise ValueError("Unvalidated EXT length/capacitance scale")
    device_tokens={token for r in rows if r[0]=="device" for token in r[1:]}
    nodes=[r for r in rows if r[0]=="node" and r[6]=="p" and r[1] not in device_tokens]
    c=Cell.read(source/(old+".mag"))
    polys=c.rects["poly"]
    remove=set()
    for node in nodes:
        # The EXT scale's linear unit is 0.005 um in this technology.
        x,y=int(node[4])/200,int(node[5])/200
        selected={i for i,r in enumerate(polys) if r[0]-1e-8<=x<=r[2]+1e-8 and r[1]-1e-8<=y<=r[3]+1e-8}
        if not selected:raise ValueError(f"No field poly at {node[1]}")
        while True:
            expanded=selected|{i for i,r in enumerate(polys) if any(touch(r,polys[j]) for j in selected)}
            if expanded==selected:break
            selected=expanded
        if any(touch(polys[i],contact) for i in selected for contact in c.rects.get("polycont",[])):
            raise ValueError(f"Contacted poly unexpectedly classified floating: {node[1]}")
        remove|=selected
    c.rects["poly"]=[r for i,r in enumerate(polys) if i not in remove]
    c.write(out/(new+".mag"))
    reference=re.sub(rf"\b{old}\b",new,(source/"reference.spice").read_text())
    (out/"reference.spice").write_text(reference)
    (out/"cleanup.json").write_text(json.dumps(dict(source=str(source.relative_to(ROOT)),
        mag_sha256=sha256(source/(old+".mag")),ext_sha256=sha256(source/(old+".ext")),
        removed_nodes=[r[1] for r in nodes],removed_rects=[polys[i] for i in sorted(remove)],
        rationale=__doc__),indent=2)+"\n")
    r=review(out/(new+".mag"),out/"reference.spice",out/"physical")
    print("removed",len(nodes),"floating nodes;",len(remove),"poly rectangles; physical_passed",r["physical_passed"])
    if not r["physical_passed"]:raise SystemExit(1)


if __name__=="__main__":main()
