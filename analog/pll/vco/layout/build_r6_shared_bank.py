#!/usr/bin/env python3
"""Build a real 5-bit/31-MIM bank with shared floating plate per weighted bit.

Small groups are raised so all MIM arrays end at the same height: this keeps
the phase-node rail short. Configuration exits on M1 in the spaces between
groups, crossing the common M2 ground rail without an accidental via.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

from serdes_flow.spice import spice_number

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell  # noqa: E402
from flat_cap_export import export as export_capacitance  # noqa: E402
from build_r6_cap_group import build as build_group  # noqa: E402

CELL = "pll_vco_cap_bank5_shared"


def build(work: Path) -> dict:
    result = Cell()
    placements = []
    reference = []
    cursor = 0.0
    qpoints = []
    for bit, n in enumerate([1, 2, 4, 8, 16]):
        directory = work / f"n{n}"
        directory.mkdir()
        build_group(directory, n)
        group = Cell.read(directory / f"pll_vco_cap_group{n}.mag")
        x1, y1, x2, y2 = group.bbox()
        dx = cursor - x1
        dy = 13.56 - y2
        result.include(group, dx=dx, dy=dy)
        qx, qy = group.pins("node")[0]
        qx, qy = qx + dx, qy + dy
        qpoints.append((qx, qy))
        result.wire("metal4", [(qx, qy), (qx, 14.2)], .32)
        bx, by = group.pins("vss")[0]
        bx, by = bx + dx, by + dy
        result.wire("metal2", [(bx, by), (bx, -2.4)], .5)
        gx, gy = group.pins("en")[0]
        gx, gy = gx + dx, gy + dy
        escape = cursor - .6
        result.wire("metal1", [(gx, gy), (escape, gy), (escape, -4)], .26)
        result.via1(escape, -4)
        result.port(f"b{bit}", "metal2", escape, -4)
        placements.append(dict(bit=bit, units=n, dx=dx, dy=dy, bbox_um=[x1+dx, y1+dy, x2+dx, y2+dy]))
        cursor += x2 - x1 + 2.0
        reference.append((directory / "reference.spice").read_text())
    result.wire("metal4", [(qpoints[0][0], 14.2), (qpoints[-1][0], 14.2)], .5)
    result.wire("metal2", [(0, -2.4), (cursor - 2, -2.4)], 1.0)
    root = sum(p[0] * n for p, n in zip(qpoints, [1, 2, 4, 8, 16])) / 31
    # Export exactly the reference order node,b0..b4,vss.
    cfg = result.labels
    result.labels = []
    result.port("node", "metal4", root, 14.2)
    result.labels += cfg
    result.port("vss", "metal2", root, -2.4)
    result.write(work / f"{CELL}.mag")
    reference += [f".subckt {CELL} node b0 b1 b2 b3 b4 vss"]
    reference += [f"Xg{bit} node b{bit} vss pll_vco_cap_group{n}" for bit,n in enumerate([1,2,4,8,16])]
    reference += [f".ends {CELL}\n"]
    ref = work / "reference.spice"
    ref.write_text("\n".join(reference))
    proc = subprocess.run([sys.executable, str(REPO / "verification/layout/check.py"), str(work), CELL,
                           "--ref", str(ref)], capture_output=True, text=True)
    (work / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr, flush=True)
    net = (work / f"{CELL}_lvs.spice").read_text()
    plates = re.findall(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1 l=2 w=2$", net, re.M)
    if sorted(Counter(plates).values()) != [1, 2, 4, 8, 16]:
        raise ValueError("MIM count, polarity or bit grouping differs from the circuit")
    plate_by_bit = {}
    mos = re.findall(r"^X\S+ (\S+) (b[0-4]) (\S+) vss sky130_fd_pr__nfet_01v8 .* w=0.75 l=0.15$", net, re.M)
    for bit,n in enumerate([1,2,4,8,16]):
        devices = [(a,b) for a,g,b in mos if g == f"b{bit}"]
        other = {a if a != "vss" else b for a,b in devices}
        if len(devices) != 2*n or len(other) != 1:
            raise ValueError(f"Incorrect switch fingers for bit {bit}")
        plate = other.pop()
        if Counter(plates)[plate] != n or any({a,b} != {plate,"vss"} for a,b in devices):
            raise ValueError(f"Incorrect plate/switch connectivity for bit {bit}")
        plate_by_bit[f"b{bit}"] = plate
    audit = export_capacitance(work / f"{CELL}.ext", work / f"{CELL}_lvs.spice", work / f"{CELL}_cap.spice")
    (work / "cap_export_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    pex = (work / f"{CELL}_cap.spice").read_text()
    caps = [(a,b,spice_number(v)*1e15) for a,b,v in re.findall(r"^C\S+ (\S+) (\S+) (\S+)$", pex, re.M)]
    def coupling(a,b):
        return sum(v for x,y,v in caps if {a,b} == {x,y})
    direct = {p:coupling("node",p) for p in ["vss","b0","b1","b2","b3","b4"]}
    summary = dict(cell=CELL, checker_exit=proc.returncode, units=31, mos_fingers=62,
        circuit_iteration="shared floating plate per weighted bit; same 31 MIM geometries and total switch width",
        placements=placements, bbox_um=result.bbox(), phase_port_um=[root,14.2],
        plate_by_bit=plate_by_bit, phase_direct_fF=direct,
        plate_ground_fF={b:coupling(p,"vss") for b,p in plate_by_bit.items()},
        phase_plate_fF={b:coupling("node",p) for b,p in plate_by_bit.items()})
    summary["capacitance_source"] = f"{CELL}_cap.spice (flat EXT matrix, not legacy ext2spice _pex)"
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if proc.returncode:
        raise RuntimeError(f"Bank physical checks failed: {work / 'check.log'}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    work = args.output_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    build(work)


if __name__ == "__main__":
    main()
