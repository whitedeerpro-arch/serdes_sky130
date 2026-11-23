#!/usr/bin/env python3
"""Layout iteration: unit MIMs sharing one bottom plate/switch array per bit.

Preserve each 2x2 MIM and 0.75/0.15 switch finger. The floating bottom plates
of units within one bit are connected: this is an explicit circuit iteration,
not an LVS-equivalent relabelling of r6's independent floating plates.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from serdes_flow.spice import spice_number

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402
from flat_cap_export import export as export_capacitance  # noqa: E402

GRIDS = {1: (1, 1), 2: (2, 1), 4: (2, 2), 8: (4, 2), 16: (4, 4)}


def build(work: Path, units: int) -> dict:
    name = f"pll_vco_cap_group{units}"
    cols, rows = GRIDS[units]
    sw = pdk_device(work, "switch_pdk", "sky130_fd_pr__nfet_01v8",
                    dict(w=.75, l=.15, nf=2 * units, conn_gates=1))
    mim = pdk_device(work, "mim_pdk", "sky130_fd_pr__cap_mim_m3_1", dict(w=2, l=2, stack=0))
    tx, ty = mim.pins("C1")[0]
    # Retain capm, its contact, and the upper electrode. One lower plate and
    # one lower terminal serve the entire group.
    mim.rects.pop("metal3")
    mim.rects.pop("via3")
    mim.rects["metal4"] = [r for r in mim.rects["metal4"] if r[0] < 1]
    result = Cell()
    result.include(sw)
    pitch = 3.0
    xs = [(c - (cols - 1) / 2) * pitch for c in range(cols)]
    ys = [3.4 + r * pitch for r in range(rows)]
    for x in xs:
        for y in ys:
            result.include(mim, dx=x - tx, dy=y - ty)
    plate_left, plate_right = xs[0] - 1.16, xs[-1] + 1.16
    result.rect("metal3", plate_left, ys[0] - 1.16, plate_right, ys[-1] + 1.16)
    sd_x = sorted({(r[0] + r[2]) / 2 for r in sw.rects["ndiffc"]})
    if len(sd_x) != units * 2 + 1:
        raise ValueError("Unexpected switch diffusion geometry")
    for i, x in enumerate(sd_x):
        result.via1(x, 0)
        result.wire("metal2", [(x, 0), (x, .5 if i % 2 else -.9)], .28)
    # Odd shared diffusions are D; even ones are grounded S. Preserve the
    # actual two-finger unit's drain sharing at every pair.
    drains, sources = sd_x[1::2], sd_x[::2]
    if len(drains) > 1:
        result.wire("metal2", [(drains[0], .5), (drains[-1], .5)], .28)
    result.wire("metal2", [(sources[0], -.9), (sources[-1], -.9)], .28)
    bx, by = sw.pins("B")[0]
    result.body_contact(bx, by)
    result.wire("metal2", [(bx, by), (bx, -.9)], .28)
    # Lift the plate above the adjacent source vias; one M3 tab then reaches
    # the common lower electrode without 31 repeated contacts/straps.
    result.wire("metal2", [(drains[len(drains) // 2], .5), (drains[len(drains) // 2], 1.25), (0, 1.25)], .28)
    result.via2(0, 1.25)
    result.wire("metal3", [(0, 1.25), (0, ys[0] - 1.0)], .5)
    # Upper plates: one vertical spine per column and one common top-row rail.
    for x in xs:
        result.wire("metal4", [(x, ys[0]), (x, ys[-1] + .15)], .32)
    if len(xs) > 1:
        result.wire("metal4", [(xs[0], ys[-1]), (xs[-1], ys[-1])], .32)
    gx, gy = sw.pins("G")[0]
    result.wire("metal1", [(gx, gy), (gx, 1.8)], .26)
    result.via1(gx, 1.8)
    result.port("node", "mimcapcontact", xs[0], ys[0])
    result.port("en", "metal2", gx, 1.8)
    result.port("vss", "metal2", bx, by)
    result.write(work / f"{name}.mag")
    ref = ["* Shared-bottom circuit iteration, not the adopted independent-plate reference.",
           f".subckt {name} node en vss"]
    ref += [f"Xc{k} node plate sky130_fd_pr__cap_mim_m3_1 w=2 l=2" for k in range(units)]
    ref += [f"Xsw plate en vss vss sky130_fd_pr__nfet_01v8 w={1.5 * units:g} l=.15 nf={2 * units}",
            f".ends {name}", ""]
    (work / "reference.spice").write_text("\n".join(ref))
    proc = subprocess.run([sys.executable, str(REPO / "verification/layout/check.py"), str(work), name,
                           "--ref", str(work / "reference.spice")], capture_output=True, text=True)
    (work / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr, flush=True)
    text = (work / f"{name}_lvs.spice").read_text()
    caps = re.findall(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1 l=2 w=2$", text, re.M)
    mos = re.findall(r"^X\S+ (\S+) en (\S+) vss sky130_fd_pr__nfet_01v8 .* w=0.75 l=0.15$", text, re.M)
    if len(caps) != units or len(set(caps)) != 1 or len(mos) != 2 * units:
        raise ValueError("Incorrect physical unit count or shared-bottom connectivity")
    plate = caps[0]
    if any({a, b} != {plate, "vss"} for a, b in mos):
        raise ValueError("Switch fingers or body are incorrectly connected")
    audit = export_capacitance(work / f"{name}.ext", work / f"{name}_lvs.spice", work / f"{name}_cap.spice")
    (work / "cap_export_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    pex = (work / f"{name}_cap.spice").read_text()
    cc = [(a, b, spice_number(v) * 1e15) for a, b, v in re.findall(r"^C\S+ (\S+) (\S+) (\S+)$", pex, re.M)]
    def coupling(a, b):
        return sum(v for x, y, v in cc if {a, b} == {x, y})
    summary = dict(cell=name, units=units, grid=[cols, rows], checker_exit=proc.returncode,
        bbox_um=result.bbox(), ports=[p[3] for p in result.labels],
        plate_to_vss_fF=coupling(plate, "vss"), node_to_plate_fF=coupling("node", plate),
        gate_to_plate_fF=coupling("en", plate), node_to_vss_fF=coupling("node", "vss"))
    summary["capacitance_source"] = f"{name}_cap.spice (flat EXT matrix, not legacy ext2spice _pex)"
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if proc.returncode:
        raise RuntimeError(f"Physical checks failed: {work / 'check.log'}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--units", type=int, choices=GRIDS, default=16)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    work = args.output_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    build(work, args.units)


if __name__ == "__main__":
    main()
