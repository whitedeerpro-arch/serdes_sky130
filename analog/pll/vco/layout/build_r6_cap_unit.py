#!/usr/bin/env python3
"""Draw the actual r6 half-unit: 2 um MIM and a shared-drain 2x0.75 um switch."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from serdes_flow.spice import spice_number

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402
from flat_cap_export import export as export_capacitance  # noqa: E402

CELL = "pll_vco_cap_unit_r6_pdk"
REF = REPO / "analog/pll/vco/layout/pll_vco_cap_unit_ref.spice"


def build(work: Path, mim_y: float = 0, compact_bottom: bool = False, switch_x: float = 0) -> None:
    sw = pdk_device(work, "switch_pdk", "sky130_fd_pr__nfet_01v8",
                    dict(w=.75, l=.15, nf=2, conn_gates=1))
    mim = pdk_device(work, "mim_pdk", "sky130_fd_pr__cap_mim_m3_1",
                     dict(w=2, l=2, stack=0))
    if compact_bottom:
        # Keep PDK capm/mimcc and the top electrode. Replace the long bottom
        # contact sleeve with one legal via3 and an L-shaped lower electrode.
        # Place its contact directly above the shared drain, reducing plate
        # routing and overlap with the source/guard wiring.
        tx, ty = mim.pins("C1")[0]
        bx = tx + 1.36
        mim.rects["metal3"] = []
        mim.rects["via3"] = []
        mim.rects["metal4"] = [r for r in mim.rects["metal4"] if r[0] < 1]
        mim.rect("metal3", tx - 1.16, ty - 1.16, tx + 1.16, ty + 1.16)
        mim.pad("metal3", bx, ty, .48)
        mim.pad("via3", bx, ty, .32)
        mim.pad("metal4", bx, ty, .50)
        mim.labels = [(layer, bx if name == "C2" else x, y, name) for layer, x, y, name in mim.labels]
    result = Cell()
    result.include(sw, dx=switch_x)
    # Put the switch under the capacitor. Keep all unrelated M3 out of capm.11.
    dx = -mim.pins("C2" if compact_bottom else "C1")[0][0]
    result.include(mim, dx=dx, dy=mim_y)
    sd_x = sorted({(r[0] + r[2]) / 2 + switch_x for r in sw.rects["ndiffc"]})
    assert len(sd_x) == 3
    for x in sd_x:
        result.via1(x, 0)
    # The central shared diffusion is the capacitor plate, the two ends VSS.
    for x in (sd_x[0], sd_x[2]):
        result.wire("metal2", [(x, 0), (x, -.9)], .28)
    result.wire("metal2", [(sd_x[0], -.9), (sd_x[2], -.9)], .28)
    bx, by = sw.pins("B")[0]
    bx += switch_x
    result.body_contact(bx, by)
    result.wire("metal2", [(bx, by), (bx, -.9)], .28)
    cx, cy = mim.pins("C2")[0]
    cx += dx
    cy += mim_y
    if compact_bottom:
        # Lift above the adjacent source vias before placing the wider via2.
        result.wire("metal2", [(sd_x[1], 0), (sd_x[1], .5)], .28)
        if sd_x[1] != cx:
            result.wire("metal2", [(sd_x[1], .5), (cx, .5)], .28)
        result.via2(cx, .5)
        result.wire("metal3", [(cx, .5), (cx, cy)], .4)
    else:
        result.wire("metal2", [(sd_x[1], 0), (sd_x[1], .5), (cx, .5), (cx, cy)], .28)
        result.via2(cx, cy)
    # Exit the gate upward on M1 before lifting it to M2: no drain/gate crossing.
    gx, gy = sw.pins("G")[0]
    gx += switch_x
    result.wire("metal1", [(gx, gy), (gx, 1.8)], .26)
    result.via1(gx, 1.8)
    result.port("node", "mimcapcontact", mim.pins("C1")[0][0] + dx, mim_y)
    result.port("en", "metal2", gx, 1.8)
    result.port("vss", "metal2", bx, by)
    result.write(work / f"{CELL}.mag")
    ref = work / "reference.spice"
    ref.write_text(re.sub(r"\bpll_vco_cap_unit\b", CELL, REF.read_text()))
    proc = subprocess.run([sys.executable, str(REPO / "verification/layout/check.py"), str(work),
                           CELL, "--ref", str(ref)], capture_output=True, text=True)
    (work / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr)
    extracted = (work / f"{CELL}_lvs.spice").read_text()
    cap = re.search(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1 l=2 w=2$", extracted, re.M)
    if not cap:
        raise ValueError("MIM top/bottom electrode assignment is wrong")
    mos = re.findall(r"^X\S+ (\S+) en (\S+) vss sky130_fd_pr__nfet_01v8 .* w=([\d.]+) l=([\d.]+)$", extracted, re.M)
    if len(mos) != 2 or any(set(m[:2]) != {cap[1], "vss"} or m[2:] != ("0.75", "0.15") for m in mos):
        raise ValueError("Switch topology, total width, fingers or body differs from r6")
    audit = export_capacitance(work / f"{CELL}.ext", work / f"{CELL}_lvs.spice", work / f"{CELL}_cap.spice")
    (work / "cap_export_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    pex = (work / f"{CELL}_cap.spice").read_text()
    caps = [(a, b, spice_number(v)) for a, b, v in re.findall(r"^C\S+ (\S+) (\S+) (\S+)$", pex, re.M)]
    def coupling(a, b):
        return sum(v * 1e15 for x, y, v in caps if {a, b} == {x, y})
    summary = dict(cell=CELL, reference=str(REF.relative_to(REPO)), checker_exit=proc.returncode,
                   mim_y_um=mim_y, compact_bottom=compact_bottom, switch_x_um=switch_x,
                   bbox_um=result.bbox(), ports=[p[3] for p in result.labels],
                   plate_to_vss_fF=coupling(cap[1], "vss"),
                   node_to_plate_fF=coupling("node", cap[1]),
                   gate_to_plate_fF=coupling("en", cap[1]))
    summary["capacitance_source"] = f"{CELL}_cap.spice (flat EXT matrix, not legacy ext2spice _pex)"
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    if proc.returncode:
        raise RuntimeError(f"Physical check failed: {work / 'check.log'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--mim-offset-y", type=float, default=0, help="Compare stacked vs separate MIM/switch placement")
    ap.add_argument("--compact-bottom", action="store_true", help="Trim the bottom sleeve and align it to the shared drain")
    ap.add_argument("--switch-offset-x", type=float, default=0, help="Move the switch away from the lower plate")
    args = ap.parse_args()
    work = args.output_dir.resolve()
    work.mkdir(parents=True, exist_ok=False)
    build(work, args.mim_offset_y, args.compact_bottom, args.switch_offset_x)


if __name__ == "__main__":
    main()
