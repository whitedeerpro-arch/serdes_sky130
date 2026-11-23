"""Build and verify the 9-Block Fused Mirror-Symmetric 5-Bit VCO Capacitor Bank.

Architecture (approved in analog/pll/vco/layout/plan/cap_bank_plan.json):
- 9 fused MIM capacitor blocks arranged mirror-symmetrically around x = 0:
    [b4_L(8u), b3_L(4u), b2_L(2u), b1_L(1u), b0(1u), b1_R(1u), b2_R(2u), b3_R(4u), b4_R(8u)]
- Exact TT main-MIM capacitance matching via serdes_flow.cap_fusion:
    u1 (1u): 2.00 x 2.00 um
    u2 (2u): 2.00 x 4.15 um
    u4 (4u): 2.60 x 6.58 um
    u8 (8u): 4.60 x 7.65 um
- Fused MOS switch fingers + vertical layer separation (LI1 grounded sources to top
  guard ring, M2 floating central drain directly up via2 into MIM M3 bottom plate,
  bottom gate contact facing the bottom digital control bus).
- Supports 4 switch-width variants per logical unit:
    w150 (1.50 um/u), w100 (1.00 um/u), w075 (0.75 um/u), w050 (0.50 um/u).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from serdes_flow import cap_fusion, project

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from geometry import Cell, pdk_device
from flat_cap_export import export

MODEL_MIM = "sky130_fd_pr__cap_mim_m3_1"
MODEL_SW = "sky130_fd_pr__nfet_01v8"

# Switch finger fusion table: {variant: {(bit, units): (nf, finger_w_um)}}
# Supports both uniform W/u variants (w150, w100, w075, w050) and Pareto W_floor candidates:
# - s31p5: b0=1.5, b1=2.0, b2=4.0, b3=8.0, b4=16.0 um (total S = 31.5 um, alpha = 1, b0 floor = 1.5 um)
# - s32p5: b0=1.5, b1=3.0, b2=4.0, b3=8.0, b4=16.0 um (total S = 32.5 um, alpha = 1, 1u-leaf floor = 1.5 um)
SWITCH_VARIANTS = {
    "w150":  {0: (2, 0.75), 1: (2, 0.75), 2: (2, 1.50), 3: (2, 3.00), 4: (4, 3.00)},
    "s32p5": {0: (2, 0.75), 1: (2, 0.75), 2: (2, 1.00), 3: (2, 2.00), 4: (2, 4.00)},
    "s31p5": {0: (2, 0.75), 1: (2, 0.50), 2: (2, 1.00), 3: (2, 2.00), 4: (2, 4.00)},
    "w100":  {0: (2, 0.50), 1: (2, 0.50), 2: (2, 1.00), 3: (2, 2.00), 4: (2, 4.00)},
    "w075":  {0: (1, 0.75), 1: (1, 0.75), 2: (2, 0.75), 3: (2, 1.50), 4: (2, 3.00)},
    "w050":  {0: (1, 0.50), 1: (1, 0.50), 2: (2, 0.50), 3: (2, 1.00), 4: (2, 2.00)},
}

# 9 symmetric blocks: (instance_name, bit_index, logical_units, x_center_um, cap_w_um)
# Exact 1.60 um capm-to-capm spacing (>= 1.48 um required by capm.11 = 1.34 + 0.14 M3 enclosure)
SYM9_BLOCKS = [
    ("b4_L", 4, 8, -16.30, 4.60),
    ("b3_L", 3, 4, -11.10, 2.60),
    ("b2_L", 2, 2,  -7.20, 2.00),
    ("b1_L", 1, 1,  -3.60, 2.00),
    ("b0_C", 0, 1,   0.00, 2.00),
    ("b1_R", 1, 1,   3.60, 2.00),
    ("b2_R", 2, 2,   7.20, 2.00),
    ("b3_R", 3, 4,  11.10, 2.60),
    ("b4_R", 4, 8,  16.30, 4.60),
]


def checked(work: Path, name: str, reference: str) -> dict:
    ref = work / f"{name}_reference.spice"
    ref.write_text(reference)
    proc = subprocess.run(
        [sys.executable, str(ROOT / "verification/layout/check.py"), str(work), name, "--ref", str(ref)],
        capture_output=True,
        text=True,
    )
    (work / f"{name}_check.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError(f"Physical check failed for {name}: {work}/{name}_check.log\n{proc.stdout[-1500:]}")
    audit = export(work / f"{name}.ext", work / f"{name}_lvs.spice", work / f"{name}_cap.spice")
    (work / f"{name}_cap_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    return audit


def build_fused_leaf(
    work: Path,
    variant: str,
    units: int,
    width: float,
    length: float,
    nf: int,
    finger_w: float,
    switch_l: float = 0.15,
) -> tuple[str, Cell, str, dict]:
    name = f"pll_vco_sym9_{variant}_u{units}"
    sw = pdk_device(work, f"sw_{name}", MODEL_SW, dict(w=finger_w, l=switch_l, nf=nf, conn_gates=1))
    mim = pdk_device(work, f"mim_{name}", MODEL_MIM, dict(w=width, l=length, stack=0))

    tx, ty = mim.pins("C1")[0]
    lo, hi = tx - width / 2, tx + width / 2
    bottom, top = ty - length / 2, ty + length / 2
    mim.rects["metal3"] = [(lo - 0.14, bottom - 0.14, hi + 0.14, top + 0.14)]
    mim.rects.pop("via3", None)
    mim.rects["metal4"] = [
        r for r in mim.rects["metal4"] if r[0] < hi and r[2] > lo and r[1] < top and r[3] > bottom
    ]

    xs = sorted({(r[0] + r[2]) / 2 for r in sw.rects["ndiffc"]})
    if len(xs) != nf + 1:
        raise ValueError(f"Unexpected contact count {len(xs)} for nf={nf}")
    drains, sources = xs[1::2], xs[::2]

    ndiff_top = max(r[3] for r in sw.rects["ndiff"])
    ndiff_right = max(r[2] for r in sw.rects["ndiff"])
    guard_top = max((r[1] + r[3]) / 2 for r in sw.rects["psubdiffcont"])
    gate_bot = min((r[1] + r[3]) / 2 for r in sw.rects["polycont"])

    # Add symmetric left/right dummy poly fingers between outer ndiff and psubdiff guard ring:
    for sign in (-1.0, 1.0):
        sw.rect("poly", round(sign * (ndiff_right + 0.095), 3), -ndiff_top, round(sign * (ndiff_right + 0.245), 3), ndiff_top)

    # Keep bottom gate contact facing bottom control bus; remove top redundant gate contact
    sw.rects["polycont"] = [r for r in sw.rects["polycont"] if r[1] < 0]
    sw.rects["locali"] = [
        r
        for r in sw.rects["locali"]
        if not (ndiff_top + 0.05 < r[1] < guard_top - 0.1 and ndiff_top + 0.05 < r[3] < guard_top - 0.1)
    ]

    def is_src_x(r: tuple[float, float, float, float]) -> bool:
        cx = (r[0] + r[2]) / 2
        return any(abs(cx - sx) < 0.12 for sx in sources) and (-ndiff_top - 0.1 < r[1] < ndiff_top + 0.1)

    sw.rects["viali"] = [r for r in sw.rects["viali"] if r[3] < ndiff_top + 0.05 and not is_src_x(r)]
    sw.rects["metal1"] = [r for r in sw.rects["metal1"] if r[3] < ndiff_top + 0.05 and not is_src_x(r)]

    new_poly = []
    for r in sw.rects["poly"]:
        if r[1] >= ndiff_top + 0.10:
            continue
        elif r[3] > ndiff_top:
            new_poly.append((r[0], r[1], r[2], ndiff_top + 0.18))
        else:
            new_poly.append(r)
    sw.rects["poly"] = new_poly

    c = Cell()
    c.include(sw)
    # Connect grounded sources purely on LI1 up to the top substrate guard bar
    for x in sources:
        c.wire("locali", [(x, 0.0), (x, guard_top)], 0.17)
    # Connect drains via1 + metal2 + via2 directly into MIM bottom plate (metal3)
    for x in drains:
        c.via1(x, 0.0)
    c.wire("metal2", [(drains[0], 0.0), (0.0, 0.0), (drains[-1], 0.0)], 0.40)
    c.via2(0.0, 0.0)

    cy = 0.40 + length / 2
    c.include(mim, dx=-tx, dy=cy - ty)
    c.wire("metal3", [(0.0, 0.0), (0.0, 0.45)], 0.40)

    gx = xs[0] + 0.24
    gy = gate_bot
    escape_x = round(min(xs[0] - 0.35, -0.85), 3)
    c.wire("metal1", [(gx, gy), (escape_x, gy)], 0.23)
    bx, by = sw.pins("B")[0]
    c.body_contact(bx, by)

    c.port("node", "mimcapcontact", 0.0, cy)
    c.port("en", "metal1", escape_x, gy)
    c.port("vss", "metal2", bx, by)
    c.write(work / f"{name}.mag")

    ref = (
        f".subckt {name} node en vss\n"
        f"Xcap node plate {MODEL_MIM} w={width:g} l={length:g}\n"
        f"Xsw plate en vss vss {MODEL_SW} w={nf * finger_w:g} l={switch_l:g} nf={nf}\n"
        f".ends {name}\n"
    )
    audit = checked(work, name, ref)
    meta = dict(
        cell=name,
        logical_units=units,
        mim_w_um=width,
        mim_l_um=length,
        switch_nf=nf,
        switch_finger_w_um=finger_w,
        switch_total_w_um=round(nf * finger_w, 4),
        bbox_um=[round(v, 4) for v in c.bbox()],
        audit=audit,
    )
    return name, c, ref, meta


def build_sym9_bank(work: Path, variant: str) -> dict:
    vdir = work / variant
    vdir.mkdir(parents=True, exist_ok=True)
    nominal, _ = cap_fusion.installed()
    unit_ff = nominal.cap_ff(2.0, 2.0)

    # Exact main-MIM matched lengths for u1, u2, u4, u8
    dims = {
        1: (2.00, 2.00),
        2: (2.00, round(nominal.length_um(2 * unit_ff, 2.00), 2)),
        4: (2.60, round(nominal.length_um(4 * unit_ff, 2.60), 2)),
        8: (4.60, round(nominal.length_um(8 * unit_ff, 4.60), 2)),
    }

    leaves = {}
    refs = []
    for _, bit, u, _, _ in SYM9_BLOCKS:
        if bit in leaves:
            continue
        w_cap, l_cap = dims[u]
        nf, fw = SWITCH_VARIANTS[variant][bit]
        sub = vdir / f"leaf_b{bit}_u{u}"
        sub.mkdir(exist_ok=True)
        lname, lcell, lref, lmeta = build_fused_leaf(sub, f"{variant}_b{bit}", u, w_cap, l_cap, nf, fw)
        leaves[bit] = (lname, lcell, lmeta)
        refs.append(lref)

    top_name = f"pll_vco_cap_bank5_sym9_{variant}"
    bank = Cell()

    # Align all 9 blocks at switch y = 0 so every block has zero floating-plate neck
    # Connect all 9 top plates (metal4) at a top spine above the tallest MIM (u8 top is 0.40 + 7.65 = 8.05)
    max_mim_top = max(0.40 + l_cap for _, l_cap in dims.values())
    rail_y = round(max_mim_top + 0.55, 2)  # 8.60 um

    # Bottom control bus tracks on metal2 (below lowest switch B pin; max fw=4.0 has B at y = -3.16)
    min_sw_bot = min(leaves[bit][1].bbox()[1] for bit in leaves)
    vss_y = round(min_sw_bot - 0.55, 2)
    bit_tracks_y = {
        0: round(vss_y - 0.70, 2),
        1: round(vss_y - 1.30, 2),
        2: round(vss_y - 1.90, 2),
        3: round(vss_y - 2.50, 2),
        4: round(vss_y - 3.10, 2),
    }

    node_xs = []
    vss_xs = []
    bit_gate_xs = {0: [], 1: [], 2: [], 3: [], 4: []}
    block_records = []
    inst_lines = []

    for inst_name, bit, u, x_center, _ in SYM9_BLOCKS:
        lname, lcell, lmeta = leaves[bit]
        w_cap, l_cap = dims[u]
        dy = round(max_mim_top - (0.40 + l_cap), 2)
        bank.include(lcell, dx=x_center, dy=dy)
        nx, ny = lcell.pins("node")[0]
        nx += x_center
        ny += dy
        node_xs.append(nx)
        bank.wire("metal4", [(nx, ny), (nx, rail_y)], 0.36)

        bx, by = lcell.pins("vss")[0]
        bx += x_center
        by += dy
        vss_xs.append(bx)
        bank.wire("metal2", [(bx, by), (bx, vss_y)], 0.40)

        gx, gy = lcell.pins("en")[0]
        gx += x_center
        gy += dy
        ty = bit_tracks_y[bit]
        bank.wire("metal1", [(gx, gy), (gx, ty)], 0.26)
        bank.via1(gx, ty)
        bit_gate_xs[bit].append(gx)

        inst_lines.append(f"X{inst_name} node b{bit} vss {lname}")
        block_records.append(
            dict(
                instance=inst_name,
                bit=bit,
                logical_units=u,
                x_center_um=x_center,
                mim_w_um=w_cap,
                mim_l_um=l_cap,
                target_nominal_ff=round(u * unit_ff, 4),
                actual_nominal_ff=round(nominal.cap_ff(w_cap, l_cap), 4),
                leaf_cell=lname,
                switch_nf=lmeta["switch_nf"],
                switch_finger_w_um=lmeta["switch_finger_w_um"],
                switch_total_w_um=lmeta["switch_total_w_um"],
            )
        )

    # Top M4 spine connecting all 9 blocks symmetrically to x = 0.0
    bank.wire("metal4", [(min(node_xs), rail_y), (max(node_xs), rail_y)], 0.50)

    # Bottom M2 VSS rail connecting all 9 switch body taps symmetrically to x = 0.0
    bank.wire("metal2", [(min(vss_xs), vss_y), (max(vss_xs), vss_y)], 0.60)

    # Bottom M2 symmetric bit bridges for b0..b4
    for bit, gxs in bit_gate_xs.items():
        ty = bit_tracks_y[bit]
        if len(gxs) == 1:
            bank.wire("metal2", [(gxs[0] - 0.25, ty), (gxs[0] + 0.25, ty)], 0.32)
        else:
            bank.wire("metal2", [(min(gxs), ty), (max(gxs), ty)], 0.32)

    # Clear child labels and place top-level ports in standard order: node b0 b1 b2 b3 b4 vss
    bank.labels = []
    bank.port("node", "metal4", 0.0, rail_y)
    for bit, gxs in bit_gate_xs.items():
        ty = bit_tracks_y[bit]
        px = gxs[0] if len(gxs) == 1 else 0.0
        bank.port(f"b{bit}", "metal2", px, ty)
    bank.port("vss", "metal2", 0.0, vss_y)

    bank.write(vdir / f"{top_name}.mag")

    top_ref = (
        "\n".join(refs)
        + f"\n.subckt {top_name} node b0 b1 b2 b3 b4 vss\n"
        + "\n".join(inst_lines)
        + f"\n.ends {top_name}\n"
    )
    audit = checked(vdir, top_name, top_ref)

    # Verify extracted netlist has 9 MIMs and 9 independent local floating plates
    net = (vdir / f"{top_name}_cap.spice").read_text()
    caps = re.findall(r"^X\S+ node (\S+) " + MODEL_MIM + r" l=([\d.]+) w=([\d.]+)$", net, re.M)
    if len(caps) != 9 or len({c[0] for c in caps}) != 9:
        raise ValueError(f"Expected 9 independent floating plates and 9 MIMs in {top_name}, got {len(caps)}")

    bx1, by1, bx2, by2 = bank.bbox()
    w_per_u = sum(b["switch_total_w_um"] for b in block_records) / 31.0
    summary = dict(
        cell=top_name,
        variant=variant,
        switch_width_per_unit_um=round(w_per_u, 4),
        total_switch_width_um=round(sum(b["switch_total_w_um"] for b in block_records), 4),
        total_mos_fingers=sum(b["switch_nf"] for b in block_records),
        mim_count=9,
        floating_plates=9,
        bbox_um=[round(bx1, 3), round(by1, 3), round(bx2, 3), round(by2, 3)],
        width_um=round(bx2 - bx1, 3),
        height_um=round(by2 - by1, 3),
        area_um2=round((bx2 - bx1) * (by2 - by1), 2),
        drc=0,
        lvs=True,
        cap_audit=audit,
        blocks=block_records,
    )
    (vdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[{variant}] {top_name}: DRC=0 LVS=True | {summary['width_um']} x {summary['height_um']} um "
        f"({summary['area_um2']} um^2) | W/u={w_per_u:.2f} um | fingers={summary['total_mos_fingers']}",
        flush=True,
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--variants", default="w150,w100,w075,w050")
    args = ap.parse_args()

    out = args.output_dir or (
        ROOT / "results/layout/pll_vco" / ("sym9_fused_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    summaries = {}
    for v in [x.strip() for x in args.variants.split(",") if x.strip()]:
        summaries[v] = build_sym9_bank(out, v)

    report = dict(
        architecture="9-Block Fused Mirror-Symmetric 5-Bit VCO Capacitor Bank (MIM + MOS Finger Fusion)",
        pdk_id=project.pdk_installation_id(),
        variants=summaries,
    )
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Saved complete 9-block bank build report to:", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
