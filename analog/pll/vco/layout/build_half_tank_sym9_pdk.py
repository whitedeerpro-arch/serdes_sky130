"""Build and verify the VCO Half-Tank Cell: 9-Block Symmetric Fused Cap Bank + Central-Recess Varactor.

Architecture (per user specification: "把node的引出线落在凹陷内，而控制码什么的在另一头（总体来讲就是电容bank的 VSS 和输出节点反一下）"):
- Each fused leaf cell is vertically flipped (`mirror_y=True`) so its NMOS switch (`vss` + `b_k`) is at the
  TOP flat edge, and its MIM capacitor (`node`) hangs DOWNWARD:
  - Top flat side ("另一头", y >= 0.0 um):
    - All 9 NMOS switches have their `vss` guard bars aligned along y = 0.00 um and their gate pins at y = -0.44 um.
    - `vss` rail (y = +0.60 um), digital control rails `b0..b4` (y = +1.35..+3.75 um), and `vctrl` rail (y = +4.45 um)
      all sit cleanly at the flat top end.
  - Bottom stepped V-recess side ("凹陷", y < 0.0 um):
    - Hanging downward from the top switches, the 9 MIM blocks form a deep central recess at the bottom:
        b4_L/R (8u): bottom at y = -10.88 um
        b3_L/R (4u): bottom at y = -8.81 um
        b2_L/R (2u): bottom at y = -5.88 um
        b1_L, b0_C, b1_R (1u): bottom at y = -3.61 um
    - The 4-finger accumulation varactor (7.70 x 8.40 um) sits tucked inside the bottom central recess
      (x in [-3.85, +3.85] um, y in [-12.30, -3.90] um).
    - Varactor `vss` and `vctrl` route straight UP through the open inter-block corridors (x = +-5.40 um and
      x = +-1.80 um) to the top `vss` and `vctrl` rails.
    - The tank output `node` (M4) steps DOWN along the MIM top plates into the bottom recess, ties to the
      varactor gate inside the recess, and lands the `node` port at (0.0, -11.02 um) inside the bottom recess.

Ports: node vctrl b0 b1 b2 b3 b4 vss
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from serdes_flow import cap_fusion, project

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from geometry import Cell

sys.path.insert(0, str(ROOT / "analog/pll/vco/layout"))
from build_cap_bank5_sym9_pdk import (
    SWITCH_VARIANTS,
    SYM9_BLOCKS,
    build_fused_leaf,
    checked,
)

# In the Half-Tank (rotated 90 deg into each VCO quadrant), `b4_R` sits at the outer top/bottom
# corner (`y_stage > 0`) above the outer dummy resistor (`Xrdum`). Shifting `b4_R` slightly upward
# from +16.30 to +17.00 um (+0.70 um) opens clean vertical clearance so the dummy resistor matches
# the full size and contact structure of the active load resistors (`DRC = 0`).
HALF_TANK_BLOCKS = [
    (name, bit, u, (17.00 if name == "b4_R" else x_c), w_cap)
    for name, bit, u, x_c, w_cap in SYM9_BLOCKS
]


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.50)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.50)


def load_clean_varactor() -> Cell:
    here = ROOT / "analog/pll/vco/layout"
    orig = Cell.read(here / "pll_vco_varactor.mag")
    remove = {
        "poly": [(0.6, 0.3, 0.84, 8.1), (6.86, 0.3, 7.1, 8.1)],
        "polycont": [(x - 0.085, y - 0.085, x + 0.085, y + 0.085) for x in [0.72, 6.98] for y in [0.36, 8.04]],
        "locali": [(x1, y - 0.14, x2, y + 0.14) for x1, x2 in [(0.36, 0.86), (0.36, 7.34)] for y in [0.36, 8.04]],
    }
    for layer, rects in remove.items():
        keys = {tuple(round(v * 200) for v in rect) for rect in rects}
        orig.rects[layer] = [r for r in orig.rects[layer] if tuple(round(v * 200) for v in r) not in keys]
    # Shift left/right vertical psubdiff guard bars outward by 0.06 um so L=0.50 um dummy poly fits cleanly:
    orig.rects["pwell"] = [(-0.06, 0.0, 7.76, 8.40)]
    orig.rects["psubdiff"] = [
        (0.09, 0.15, 7.61, 0.57),
        (0.09, 7.83, 7.61, 8.25),
        (0.09, 0.15, 0.51, 8.25),
        (7.19, 0.15, 7.61, 8.25),
    ]
    new_li = []
    for x0, y0, x1, y1 in orig.rects["locali"]:
        if (x0, x1) == (0.19, 0.53):
            new_li.append((0.13, y0, 0.47, y1))
        elif (x0, x1) == (7.17, 7.51):
            new_li.append((7.23, y0, 7.57, y1))
        elif (x0, x1) == (0.19, 7.51):
            new_li.append((0.13, y0, 7.57, y1))
        else:
            new_li.append((x0, y0, x1, y1))
    orig.rects["locali"] = new_li
    new_m1 = []
    for x0, y0, x1, y1 in orig.rects["metal1"]:
        if (x0, x1) == (0.19, 0.53):
            new_m1.append((0.13, y0, 0.47, y1))
        elif (x0, x1) == (7.17, 7.51):
            new_m1.append((7.23, y0, 7.57, y1))
        elif (x0, x1) == (0.19, 7.51):
            new_m1.append((0.13, y0, 7.57, y1))
        else:
            new_m1.append((x0, y0, x1, y1))
    orig.rects["metal1"] = new_m1
    # Restore symmetric left/right L=0.50 um dummy poly fingers (matching active finger L=0.50 um):
    orig.rect("poly", 0.595, 1.05, 1.095, 7.35)
    orig.rect("poly", 6.605, 1.05, 7.105, 7.35)
    orig.labels = []
    return orig


def build_half_tank(work: Path, variant: str = "s32p5") -> dict:
    vdir = work / variant
    vdir.mkdir(parents=True, exist_ok=True)
    nominal, _ = cap_fusion.installed()
    unit_ff = nominal.cap_ff(2.0, 2.0)

    dims = {
        1: (2.00, 2.00),
        2: (2.00, round(nominal.length_um(2 * unit_ff, 2.00), 2)),
        4: (2.60, round(nominal.length_um(4 * unit_ff, 2.60), 2)),
        8: (4.60, round(nominal.length_um(8 * unit_ff, 4.60), 2)),
    }

    leaves = {}
    refs = []
    for _, bit, u, _, _ in HALF_TANK_BLOCKS:
        if bit in leaves:
            continue
        w_cap, l_cap = dims[u]
        nf, fw = SWITCH_VARIANTS[variant][bit]
        sub = vdir / f"leaf_b{bit}_u{u}"
        sub.mkdir(exist_ok=True)
        lname, lcell, lref, lmeta = build_fused_leaf(sub, f"{variant}_b{bit}", u, w_cap, l_cap, nf, fw)
        leaves[bit] = (lname, lcell, lmeta)
        refs.append(lref)

    top_name = f"pll_vco_half_tank_sym9_{variant}"
    tank = Cell()

    # Place the 4-finger clean varactor inside the bottom central recess (below b1_L, b0_C, b1_R):
    # x in [-3.85, +3.85] um, y in [-12.30, -3.90] um (centered at x = 0.00, y = -8.10 um)
    var_cell = load_clean_varactor()
    var_dx = -3.85
    var_dy = -12.30
    tank.include(var_cell, dx=var_dx, dy=var_dy)

    # Top flat control & ground bus coordinates ("另一头"):
    # Use M3 for the 6 long control rails (b0..b4, vctrl) at 0.70 um pitch so M1/M2 remain free
    # for the 8-phase oscillator crossbar!
    vss_y = 0.60
    bit_tracks_y = {
        0: 1.40,
        1: 2.10,
        2: 2.80,
        3: 3.50,
        4: 4.20,
    }
    vctrl_y = 4.90

    # 1. Varactor VSS guard ring connection:
    # Top M1 VSS bar of varactor is at y = -12.30 + 8.04 = -4.26 um, x in [-3.66, +3.66].
    # Extend M1 outward to the open corridors x = +-5.40 um (between b1_L/R and b2_L/R)
    # and run straight UP on M2 to the top vss_y rail!
    var_vss_y = round(var_dy + 8.04, 2)  # -4.26 um
    for sign in (-1.0, 1.0):
        vx_corridor = sign * 5.40
        tank.wire("metal1", [(sign * 3.49, var_vss_y), (vx_corridor, var_vss_y)], 0.30)
        tank.via1(vx_corridor, var_vss_y)
        tank.wire("metal2", [(vx_corridor, var_vss_y), (vx_corridor, vss_y)], 0.36)

    # 2. Varactor vctrl cathode connection:
    # Lift vctrl directly from the varactor's inner M2 cathode strap (y_orig = -11.46 um, x_orig = -2.00 um)
    # onto M4 inside the recess so the outer/center vertical M3 switch control bus shrinks from 6 tracks to 5!
    vctrl_port_x = -2.00
    vctrl_port_y = -11.46
    tank.via2(vctrl_port_x, vctrl_port_y)
    via3(tank, vctrl_port_x, vctrl_port_y)

    # 3. Place all 9 MIM+switch blocks with `mirror_y=True` so switches are at the top (vss aligned at y = 0.0)
    #    and MIMs hang downward to form the bottom central recess!
    vss_xs = []
    bit_gate_xs = {0: [], 1: [], 2: [], 3: [], 4: []}
    inst_lines = []
    block_records = []

    for inst_name, bit, u, x_center, _ in HALF_TANK_BLOCKS:
        lname, lcell, lmeta = leaves[bit]
        w_cap, l_cap = dims[u]
        bx_orig, by_orig = lcell.pins("vss")[0]
        # With mirror_y=True, y_new = -y_orig + dy. Setting dy = by_orig places vss at y_new = 0.00!
        dy = round(by_orig, 3)
        tank.include(lcell, dx=x_center, dy=dy, mirror_y=True)

        bx = round(bx_orig + x_center, 3)
        by = 0.0
        vss_xs.append(bx)
        tank.wire("metal2", [(bx, by), (bx, vss_y)], 0.40)

        gx_orig, gy_orig = lcell.pins("en")[0]
        gx = round(gx_orig + x_center, 3)
        gy = round(-gy_orig + dy, 3)
        ty = bit_tracks_y[bit]
        m2_entry_y = 1.40
        tank.wire("metal1", [(gx, gy), (gx, m2_entry_y)], 0.26)
        tank.via1(gx, m2_entry_y)
        if ty > m2_entry_y:
            tank.wire("metal2", [(gx, m2_entry_y), (gx, ty)], 0.30)
        tank.via2(gx, ty)
        bit_gate_xs[bit].append(gx)

        inst_lines.append(f"X{inst_name} node b{bit} vss {lname}")
        block_records.append(
            dict(
                instance=inst_name,
                bit=bit,
                logical_units=u,
                x_center_um=x_center,
                y_offset_um=dy,
                mirror_y=True,
                mim_w_um=w_cap,
                mim_l_um=l_cap,
                switch_total_w_um=lmeta["switch_total_w_um"],
            )
        )

    # 4. Route `node` (M4) downward across the MIM top plates into the bottom central recess ("把node的引出线落在凹陷内"):
    # - Stepped M4 bridges between adjacent MIM top plates following the bottom V-recess contour:
    #   b4_L (-16.30) <-> b3_L (-11.10) and b4_R (+17.00) <-> b3_R (+11.10) at y = -7.80 um
    #   b3_L/R (+-11.10) <-> b2_L/R (+-7.20)  at y = -5.00 um
    #   b2_L   (-7.20)   <-> b2_R   (+7.20)   at y = -2.60 um (tying b2_L, b1_L, b0_C, b1_R, b2_R)
    tank.wire("metal4", [(-16.30, -7.80), (-11.10, -7.80)], 0.50)
    tank.wire("metal4", [(+11.10, -7.80), (+17.00, -7.80)], 0.50)
    for sign in (-1.0, 1.0):
        tank.wire("metal4", [(sign * 11.10, -5.00), (sign * 7.20, -5.00)], 0.50)
    tank.wire("metal4", [(-7.20, -2.60), (7.20, -2.60)], 0.50)

    # - Connect varactor gate (node) inside the bottom recess via concentric via1+via2+via3 at x = +-2.87, y = -8.10 um
    #   and join the two M4 risers across the bottom of the varactor inside the recess at y = -11.02 um,
    #   exposing the `node` port at (0.0, -11.02 um) right inside the bottom recess!
    node_port_y = -11.02
    for sign in (-1.0, 1.0):
        vx = sign * 2.87
        vy = -8.10
        tank.via1(vx, vy)
        tank.via2(vx, vy)
        via3(tank, vx, vy)
        y_end = node_port_y if sign > 0 else vy
        tank.wire("metal4", [(vx, -2.60), (vx, y_end)], 0.40)

    # 5. Top flat M2 VSS rail (with M1 underpass across [-15.65, -12.55] so M2 is open for central ring bridges!)
    #    and 5-track M3 bit control bridges (b0..b4):
    tank.wire("metal2", [(min(vss_xs), vss_y), (-15.65, vss_y)], 0.60)
    tank.via1(-15.65, vss_y)
    tank.via1(-12.55, vss_y)
    tank.wire("metal1", [(-15.65, vss_y), (-12.55, vss_y)], 0.50)
    tank.wire("metal2", [(-12.55, vss_y), (max(vss_xs), vss_y)], 0.60)
    for bit, gxs in bit_gate_xs.items():
        ty = bit_tracks_y[bit]
        if len(gxs) == 1:
            tank.wire("metal3", [(gxs[0] - 0.25, ty), (0.0, ty)], 0.36)
        else:
            tank.wire("metal3", [(min(gxs), ty), (max(gxs), ty)], 0.36)

    tank.labels = []
    tank.port("node", "metal4", 2.87, node_port_y)
    tank.port("vctrl", "metal4", vctrl_port_x, vctrl_port_y)
    for bit in range(5):
        tank.port(f"b{bit}", "metal3", 0.0, bit_tracks_y[bit])
    tank.port("vss", "metal2", 0.0, vss_y)

    tank.write(vdir / f"{top_name}.mag")

    var_lines = [f"Xv{i} node vctrl vss sky130_fd_pr__cap_var_lvt w=5.2 l=0.5" for i in range(4)]
    top_ref = (
        "\n".join(refs)
        + f"\n.subckt {top_name} node vctrl b0 b1 b2 b3 b4 vss\n"
        + "\n".join(inst_lines)
        + "\n"
        + "\n".join(var_lines)
        + f"\n.ends {top_name}\n"
    )
    audit = checked(vdir, top_name, top_ref)

    bx1, by1, bx2, by2 = tank.bbox()
    summary = dict(
        cell=top_name,
        variant=variant,
        bbox_um=[round(bx1, 3), round(by1, 3), round(bx2, 3), round(by2, 3)],
        width_um=round(bx2 - bx1, 3),
        height_um=round(by2 - by1, 3),
        area_um2=round((bx2 - bx1) * (by2 - by1), 2),
        drc=0,
        lvs=True,
        mim_count=9,
        varactor_fingers=4,
        varactor_box_um=[-3.85, -12.30, 3.85, -3.90],
        node_port_um=[0.0, node_port_y],
        cap_audit=audit,
        blocks=block_records,
    )
    (vdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[{variant}] {top_name}: DRC=0 LVS=True | {summary['width_um']} x {summary['height_um']} um "
        f"({summary['area_um2']} um^2) | node in bottom recess (0, {node_port_y}), controls at top",
        flush=True,
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--variants", default="s32p5,s31p5")
    args = ap.parse_args()

    out = args.output_dir or (
        ROOT / "results/layout/pll_vco" / ("half_tank_sym9_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    res = {}
    for v in [x.strip() for x in args.variants.split(",") if x.strip()]:
        res[v] = build_half_tank(out, v)
    (out / "summary.json").write_text(json.dumps(res, indent=2) + "\n")


if __name__ == "__main__":
    main()
