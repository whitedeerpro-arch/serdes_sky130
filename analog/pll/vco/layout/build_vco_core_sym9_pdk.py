#!/usr/bin/env python3
"""Build and verify the 4-Stage Ring VCO + 4x CML Buffer Core (`pll_vco_core_sym9_<variant>`) in SKY130 PDK.

Revised Architecture per User Feedback:
1. Central Abutted Tail Current Bank (`[Xbmp | Xbtail_L | Delay_Xt | Xbtail_R | Xbmn]` at `y_stage = -9.80 um`):
   - All tail current sources (`Xbtail_L` at `x_stage = -4.31 um`, `Delay_Xt` at `0.00 um`, `Xbtail_R` at `+4.31 um`)
     are grouped together on the INSIDE around the quadrant axis `x_stage = 0.00 um`, sharing vertical guard ring
     bars (`[+-2.465, +-2.635] um`), L=0.50 um dummy poly fingers, and a single straight M1 `vbias` gate bar!
   - Buffer differential pairs (`Xbmp` at `-7.60 um`, `Xbmn` at `+7.60 um`) abut `Xbtail_L/R` on the outside
     (`[+-5.985, +-6.155] um`), sharing a single straight M2 `tail_buf` bar (`[-8.56, +8.56] um` at `y_stage = -10.80 um`).
   - Oscillator vertical trunks (`dx_in = +-3.55/+-4.15 um`, `dx_out = +-6.45/+-7.05 um`) run on M3 across the
     lower active row (`y_stage in [-12.60, -4.50/+3.00] um`, directly tapping `Xbmp/Xbmn` M3 gate bar at
     `y_stage = -8.025 um`) before dropping to M1 at `y_stage = -12.60 um` for the central M1/M2 crossbar.
2. Outward-Shifted Cap-Bank Switches (`tank_cx = 22.70 um`, `+1.90 um`) + Outer Dummy Resistors (`x_stage = +-16.65 um`):
   - Shifting each Half-Tank outward by `1.90 um` (`tank_cx: 20.80 -> 22.70 um`, `DX: 24.15 -> 26.05 um`) opens room
     underneath the `b3/b4` top MIM capacitors at `x_stage = +-16.65 um` for a pair of full-size dummy resistors
     (`Xrdum_L, Xrdum_R`) with grounded guard rings flanking the Buffer load resistors (`Xbrp, Xbrn` at `+-12.00 um`).
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "verification/layout"))
sys.path.insert(0, str(ROOT / "analog/pll/vco/layout"))

from geometry import Cell, pdk_device
from build_delay_stage_sym9_pdk import (
    build_clean_inp8,
    grid,
    rotate_cell_90,
    via3,
)
from build_half_tank_sym9_pdk import HALF_TANK_BLOCKS, build_half_tank
from build_vco_ring4_sym9_pdk import (
    make_inner_tank_cell,
    mirror_cell_y,
    pad,
    spice_number,
    via1_2_3,
    via2_3,
)


def via1_2(c: Cell, x: float, y: float) -> None:
    """Connect metal1 -> metal2 -> metal3 at (x, y) with clean enclosures."""
    c.via1(x, y)
    pad(c, "metal2", x, y, 0.44, 0.44)
    c.via2(x, y)
    pad(c, "metal3", x, y, 0.44, 0.44)


def build_clean_binp(work: Path) -> Cell:
    """Build an nf=4, w=3.0 um, l=0.15 um LVT NMOS for Buffer differential pair (Xmp, Xmn) with:
    1) Bottom redundant gate contacts removed, top gate contacts strapped on metal1 at y = +1.775 um,
    2) Symmetric left/right L=0.15 um dummy poly fingers at x in [+-1.200, +-1.350] um,
    3) S/D vertical separation: 3 source columns (-0.96, 0.0, +0.96) in lower half [-1.50, -0.50],
       2 drain columns (-0.48, +0.48) in upper half [-0.46, +1.50].
    """
    binp = pdk_device(
        work,
        "binp_pdk",
        "sky130_fd_pr__nfet_01v8_lvt",
        dict(w=3.0, l=0.15, nf=4, conn_gates=1),
    )
    binp.rects.pop("checkpaint", None)

    sd = sorted({grid((r[0] + r[2]) / 2) for r in binp.rects["ndiffc"]})
    sources = sd[::2]   # -0.96, 0.0, +0.96
    drains = sd[1::2]   # -0.48, +0.48

    ndiff_top = 1.50
    ndiff_bot = -1.50

    # 1. Remove redundant bottom gate contacts (y < 0) and keep top gate strap (y = +1.775)
    binp.rects["polycont"] = [r for r in binp.rects["polycont"] if r[1] > 0]
    binp.rects["locali"] = [
        r for r in binp.rects["locali"] if not (-2.10 < r[1] < -1.55 and -2.10 < r[3] < -1.55)
    ]
    binp.rects["viali"] = [r for r in binp.rects["viali"] if r[1] > -1.55]
    binp.rects["metal1"] = [r for r in binp.rects["metal1"] if r[1] > -1.55]

    new_poly = []
    for r in binp.rects["poly"]:
        if r[3] <= ndiff_bot - 0.10:
            continue
        elif r[1] < ndiff_bot:
            new_poly.append((r[0], grid(ndiff_bot - 0.18), r[2], r[3]))
        else:
            new_poly.append(r)
    binp.rects["poly"] = new_poly

    # Strap top gate contacts together on metal1 at y = +1.775 um:
    binp.wire("metal1", [(-0.96, 1.775), (+0.96, 1.775)], 0.23)

    # Add symmetric L=0.15 um dummy poly fingers inside guard ring:
    for sign in (-1.0, 1.0):
        x0, x1 = sorted((grid(sign * 1.200), grid(sign * 1.350)))
        binp.rect("poly", x0, ndiff_bot, x1, ndiff_top)

    # 2. Trim S/D viali and metal1 inside y in [-1.51, +1.51]:
    binp.rects["viali"] = [
        r for r in binp.rects["viali"] if not (ndiff_bot - 0.02 <= r[1] and r[3] <= ndiff_top + 0.02)
    ]
    binp.rects["metal1"] = [
        r for r in binp.rects["metal1"] if not (ndiff_bot - 0.02 <= r[1] and r[3] <= ndiff_top + 0.02)
    ]
    for sx in sources:
        binp.rects["viali"].append((grid(sx - 0.085), -1.44, grid(sx + 0.085), -0.56))
        binp.rects["metal1"].append((grid(sx - 0.115), -1.50, grid(sx + 0.115), -0.50))
    for dx in drains:
        binp.rects["viali"].append((grid(dx - 0.085), -0.40, grid(dx + 0.085), +1.34))
        binp.rects["metal1"].append((grid(dx - 0.115), -0.46, grid(dx + 0.115), +1.40))

    return binp


def build_clean_btail2(work: Path) -> Cell:
    """Build an nf=2, w=3.0 um, l=0.50 um NMOS half-tail for Buffer (Xtail split into L+R halves) with:
    1) Guard ring expanded horizontally by +-0.40 um to house L=0.50 um dummy poly fingers on both sides,
    2) Top redundant gate contacts removed, bottom gate contacts strapped on metal1 at y = -1.775 um,
    3) S/D vertical separation: center drain column (0.0) in lower half [-1.50, -0.50],
       outer source columns (-0.79, +0.79) in upper half [-0.46, +1.50].
    """
    btail2 = pdk_device(
        work,
        "btail2_pdk",
        "sky130_fd_pr__nfet_01v8",
        dict(w=3.0, l=0.50, nf=2, conn_gates=1),
    )
    btail2.rects.pop("checkpaint", None)

    ndiff_top = 1.50
    ndiff_bot = -1.50

    # 1. Expand guard ring horizontally by +-0.40 um for L=0.50 um dummy poly fingers:
    btail2.rects["pwell"] = [(-2.025, -2.55, 2.025, 2.55)]
    btail2.rects["psubdiff"] = [
        (-1.845, 2.20, -0.965, 2.37),
        (0.965, 2.20, 1.845, 2.37),
        (-1.845, 1.89, -1.675, 2.20),
        (1.675, 1.89, 1.845, 2.20),
        (-1.845, -2.20, -1.675, -1.89),
        (1.675, -2.20, 1.845, -1.89),
        (-1.845, -2.37, -0.965, -2.20),
        (0.965, -2.37, 1.845, -2.20),
    ]
    btail2.rects["psubdiffcont"] = [
        (-0.965, 2.20, 0.965, 2.37),
        (-1.845, -1.89, -1.675, 1.89),
        (1.675, -1.89, 1.845, 1.89),
        (-0.965, -2.37, 0.965, -2.20),
    ]
    new_li = []
    for x0, y0, x1, y1 in btail2.rects["locali"]:
        if (x0, x1) == (-1.445, -0.965):
            new_li.append((-1.845, y0, -0.965, y1))
        elif (x0, x1) == (0.965, 1.445):
            new_li.append((0.965, y0, 1.845, y1))
        elif (x0, x1) == (-1.445, -1.275):
            new_li.append((-1.845, y0, -1.675, y1))
        elif (x0, x1) == (1.275, 1.445):
            new_li.append((1.675, y0, 1.845, y1))
        else:
            new_li.append((x0, y0, x1, y1))
    btail2.rects["locali"] = new_li

    # 2. Remove redundant top gate contacts (y > 0) and keep bottom gate contacts (y = -1.775):
    btail2.rects["polycont"] = [r for r in btail2.rects["polycont"] if r[3] < 0]
    btail2.rects["locali"] = [
        r for r in btail2.rects["locali"] if not (1.55 < r[1] < 2.10 and 1.55 < r[3] < 2.10)
    ]
    btail2.rects["viali"] = [r for r in btail2.rects["viali"] if r[3] < 1.55]
    btail2.rects["metal1"] = [r for r in btail2.rects["metal1"] if r[3] < 1.55]

    new_poly = []
    for r in btail2.rects["poly"]:
        if r[1] >= ndiff_top + 0.10:
            continue
        elif r[3] > ndiff_top:
            new_poly.append((r[0], r[1], r[2], grid(ndiff_top + 0.18)))
        else:
            new_poly.append(r)
    btail2.rects["poly"] = new_poly

    # Strap bottom gate contacts together on metal1 at y = -1.775 um:
    btail2.wire("metal1", [(-0.625, -1.775), (+0.625, -1.775)], 0.23)

    # Add symmetric L=0.50 um dummy poly fingers inside expanded guard ring:
    for sign in (-1.0, 1.0):
        x0, x1 = sorted((grid(sign * 1.025), grid(sign * 1.525)))
        btail2.rect("poly", x0, ndiff_bot, x1, ndiff_top)

    # 3. Trim S/D viali and metal1 inside y in [-1.51, +1.51]:
    btail2.rects["viali"] = [
        r for r in btail2.rects["viali"] if not (ndiff_bot - 0.02 <= r[1] and r[3] <= ndiff_top + 0.02)
    ]
    btail2.rects["metal1"] = [
        r for r in btail2.rects["metal1"] if not (ndiff_bot - 0.02 <= r[1] and r[3] <= ndiff_top + 0.02)
    ]
    # Center drain column (x = 0.0) in lower half:
    btail2.rects["viali"].append((-0.085, -1.44, +0.085, -0.56))
    btail2.rects["metal1"].append((-0.115, -1.50, +0.115, -0.50))
    # Outer source columns (x = +-0.79) in upper half:
    for sx in (-0.79, +0.79):
        btail2.rects["viali"].append((grid(sx - 0.085), -0.40, grid(sx + 0.085), +1.44))
        btail2.rects["metal1"].append((grid(sx - 0.115), -0.46, grid(sx + 0.115), +1.50))

    return btail2


def build_bload_dummy(bload: Cell) -> Cell:
    """Build a full-size (W=2.85 um, L=8.38 um) dummy resistor cell matching `bload` (`Xbrp, Xbrn`)
    in guard ring (`pwell, psubdiff, psubdiffcont, locali`), poly body (`[-1.425, -4.19, +1.425, +4.19]`),
    and head contacts (`polycont, locali, viali, metal1`), grounded to its guard ring on LI1, flanking
    the Buffer load resistors (`Xbrp, Xbrn`) at `x_stage = +-16.65 um` underneath the `b3/b4` top MIMs.
    """
    dum = Cell()
    for lyr in ("pwell", "psubdiff", "psubdiffcont", "locali", "viali", "metal1"):
        dum.rects[lyr] = list(bload.rects[lyr])
    dum.rect("poly", -1.425, -4.19, +1.425, +4.19)
    dum.rects["locali"].extend([
        (-1.425, +2.03, +1.425, +4.19),
        (-1.425, -4.19, +1.425, -2.03),
        (-0.20, -4.67, +0.20, -4.19),
    ])
    dum.rects["polycont"] = [
        (-1.345, +2.115, +1.345, +4.10),
        (-1.345, -4.10, +1.345, -2.115),
    ]
    return dum


def build_delay_buf_core(work: Path) -> tuple[Cell, dict]:
    """Build and verify `pll_vco_delay_buf_sym9_c` (Delay Stage Core + Embedded CML Buffer
    with Inner Abutted Tail Bank `[Xbmp | Xbtail_L | Delay_Xt | Xbtail_R | Xbmn]` + Outer Dummy Resistors).
    """
    cdir = work / "delay_buf_core_c"
    cdir.mkdir(parents=True, exist_ok=True)
    name = "pll_vco_delay_buf_sym9_c"

    inp8 = build_clean_inp8(cdir)
    tail = pdk_device(cdir, "tail_pdk", "sky130_fd_pr__nfet_01v8", dict(w=6.3, l=0.5, nf=4, conn_gates=1))
    load = pdk_device(cdir, "load_pdk", "sky130_fd_pr__res_high_po_2p85", dict(l=4.77))
    bload = pdk_device(cdir, "bload_pdk", "sky130_fd_pr__res_high_po_2p85", dict(l=4.22))
    for prim in (tail, load, bload):
        prim.rects.pop("checkpaint", None)
    bload_dummy = build_bload_dummy(bload)
    binp = build_clean_binp(cdir)
    btail2 = build_clean_btail2(cdir)

    # Expand Delay Stage tail guard ring horizontally by +-0.40 um and add symmetric L=0.50 um dummy poly fingers:
    tail.rects["pwell"] = [(-2.815, -4.20, 2.815, 4.20)]
    tail.rects["psubdiff"] = [
        (-2.635, 3.85, -1.755, 4.02),
        (1.755, 3.85, 2.635, 4.02),
        (-2.635, 3.54, -2.465, 3.85),
        (2.465, 3.54, 2.635, 3.85),
        (-2.635, -3.85, -2.465, -3.54),
        (2.465, -3.85, 2.635, -3.54),
        (-2.635, -4.02, -1.755, -3.85),
        (1.755, -4.02, 2.635, -3.85),
    ]
    tail.rects["psubdiffcont"] = [
        (-1.755, 3.85, 1.755, 4.02),
        (-2.635, -3.54, -2.465, 3.54),
        (2.465, -3.54, 2.635, 3.54),
        (-1.755, -4.02, 1.755, -3.85),
    ]
    new_tail_li = []
    for x0, y0, x1, y1 in tail.rects["locali"]:
        if (x0, x1) == (-2.235, -1.755):
            new_tail_li.append((-2.635, y0, -1.755, y1))
        elif (x0, x1) == (1.755, 2.235):
            new_tail_li.append((1.755, y0, 2.635, y1))
        elif (x0, x1) == (-2.235, -2.065):
            new_tail_li.append((-2.635, y0, -2.465, y1))
        elif (x0, x1) == (2.065, 2.235):
            new_tail_li.append((2.465, y0, 2.635, y1))
        else:
            new_tail_li.append((x0, y0, x1, y1))
    tail.rects["locali"] = new_tail_li
    tail_nd_y = max(r[3] for r in tail.rects["ndiff"])  # 3.15
    for sign in (-1.0, 1.0):
        x0, x1 = sorted((grid(sign * 1.845), grid(sign * 2.345)))
        tail.rect("poly", x0, -tail_nd_y, x1, tail_nd_y)

    c = Cell()

    # =========================================================================
    # 1. DELAY STAGE INPUT PAIR & 8-COLUMN RESISTOR ARRAY
    # =========================================================================
    inp_dx = 2.49
    c.include(inp8, dx=-inp_dx, mirror_x=False)
    c.include(inp8, dx=inp_dx, mirror_x=True)

    sd_local = sorted({grid((r[0] + r[2]) / 2) for r in inp8.rects["ndiffc"]})
    sources_local = sd_local[::2]
    drains_local = sd_local[1::2]

    drain_y = 2.00
    source_y = -2.00

    for sign in (-1.0, 1.0):
        cx = sign * inp_dx
        drains = sorted([grid(cx + d) for d in drains_local])
        sources = sorted([grid(cx + s) for s in sources_local])
        for dx in drains:
            c.via1(dx, drain_y)
        c.wire("metal2", [(drains[0], drain_y), (drains[-1], drain_y)], 0.36)
        for sx in sources:
            c.via1(sx, source_y)

    c.wire("metal2", [(grid(-inp_dx + sources_local[0]), source_y), (grid(inp_dx + sources_local[-1]), source_y)], 0.40)

    body_top_y = 3.285
    body_rail_y = 5.15
    for gx in (-inp_dx, inp_dx):
        c.body_contact(gx, body_top_y)
        c.wire("metal2", [(gx, body_top_y), (gx, body_rail_y)], 0.36)

    # Gate connections: inp (left) and inn (right), with M2 extended to +-4.25 um so M3 dx_in trunks land cleanly:
    gate_strap_y = -2.775
    inp_y = -4.50
    for sign in (-1.0, 1.0):
        gx = grid(sign * inp_dx)
        c.wire("metal1", [(gx, gate_strap_y), (gx, inp_y)], 0.26)
        c.wire("metal1", [(grid(gx - 1.70), inp_y), (grid(gx + 1.70), inp_y)], 0.28)
        c.via1(gx, inp_y)
        c.wire("metal2", [(grid(sign * 1.29), inp_y), (grid(sign * 4.25), inp_y)], 0.36)

    res_xs = [-7.20, -2.40, 2.40, 7.20]
    out_bar_y = 4.20
    load_y = grid(body_rail_y + 0.67 - load.pins("B")[0][1])  # 10.85
    vdd_y = grid(load_y + load.pins("R1")[0][1] + 0.85)       # 15.99

    c.wire("metal4", [(-7.20, out_bar_y), (-2.40, out_bar_y)], 0.50)
    c.wire("metal4", [(2.40, out_bar_y), (7.20, out_bar_y)], 0.50)

    for sign in (-1.0, 1.0):
        rx = sign * 2.40
        c.via2(rx, drain_y)
        c.wire("metal3", [(rx, drain_y), (rx, out_bar_y)], 0.40)
        via3(c, rx, out_bar_y)

    for rx in res_xs:
        c.include(load, dx=rx, dy=load_y)
        r2_y = grid(load_y + load.pins("R2")[0][1])
        c.via1(rx, r2_y)
        c.via2(rx, r2_y)
        c.wire("metal3", [(rx, r2_y), (rx, out_bar_y)], 0.40)
        via3(c, rx, out_bar_y)

        r1_y = grid(load_y + load.pins("R1")[0][1])
        c.via1(rx, r1_y)
        c.wire("metal2", [(rx, r1_y), (rx, vdd_y)], 0.60)

        bx, by = load.pins("B")[0]
        bx, by = grid(bx + rx), grid(by + load_y)
        c.body_contact(bx, by)
        c.wire("metal2", [(bx, by), (bx, body_rail_y)], 0.40)

    # Buffer Load Resistors `Xbrp` (left, x = -12.00 -> boutn) and `Xbrn` (right, x = +12.00 -> boutp)
    # + Outer Full-Size Dummy Resistors `Xrdum_L, Xrdum_R` at `x = +-16.65 um`:
    bload_y = grid(body_rail_y + 0.67 - bload.pins("B")[0][1])  # 10.575
    for sign in (-1.0, 1.0):
        bx_res = grid(sign * 12.00)
        c.include(bload, dx=bx_res, dy=bload_y)

        br1_y = grid(bload_y + bload.pins("R1")[0][1])  # 14.59
        c.via1(bx_res, br1_y)
        c.wire("metal2", [(bx_res, br1_y), (bx_res, vdd_y)], 0.60)

        bbx, bby = bload.pins("B")[0]
        bbx, bby = grid(bbx + bx_res), grid(bby + bload_y)  # +-12.00, +5.82
        c.body_contact(bbx, bby)
        c.wire("metal2", [(bbx, bby), (bbx, body_rail_y)], 0.40)

        # Outer Dummy Resistor at x = +-16.65 um:
        dx_dum = grid(sign * 16.65)
        c.include(bload_dummy, dx=dx_dum, dy=bload_y)
        dbx = dx_dum
        dby = grid(bload_y - 4.755)  # +5.82
        c.body_contact(dbx, dby)
        c.wire("metal2", [(dbx, dby), (dbx, body_rail_y)], 0.40)

    c.wire("metal2", [(-12.40, vdd_y), (+12.40, vdd_y)], 0.90)
    c.wire("metal2", [(-17.05, body_rail_y), (+17.05, body_rail_y)], 0.60)

    # =========================================================================
    # 2. LOWER ABUTTED 5-BLOCK ROW: `[Xbmp (-7.60) | Xbtail_L (-4.31) | Delay_Xt (0.00) | Xbtail_R (+4.31) | Xbmn (+7.60)]`
    # =========================================================================
    tail_y = -9.80
    ground_y = -15.60
    c.include(tail, dy=tail_y)
    tsd = sorted({grid((r[0] + r[2]) / 2) for r in tail.rects["ndiffc"]})
    tdy = grid(6.3 / 2 - 0.50)  # 2.65
    for k, tx in enumerate(tsd):
        c.via1(tx, grid(tail_y + (tdy if k % 2 else -tdy)))
    tdrains, tsources = tsd[1::2], tsd[::2]
    td_y = grid(tail_y + tdy)   # -7.15
    ts_y = grid(tail_y - tdy)   # -12.45
    c.wire("metal2", [(tdrains[0], td_y), (tdrains[-1], td_y)], 0.50)
    c.via2(0.0, td_y)
    c.wire("metal3", [(0.0, td_y), (0.0, source_y)], 0.70)
    c.via2(0.0, source_y)

    tbx, tby = tail.pins("B")[0]
    tby = grid(tby + tail_y)  # -13.735
    c.body_contact(tbx, tby)
    c.wire("metal2", [(tbx, tby), (tbx, ground_y)], 0.50)

    tgy = grid(tail_y - 3.425)  # -13.225 (bottom gate strap of Delay Xt)
    bias_x = -2.40
    bias_y = grid(ground_y + 1.00)  # -14.60

    # Place Buffer Split Tail `btail2` on the INSIDE (dx = +-4.31) abutting `Delay_Xt`,
    # and Buffer Diff Pair `binp` on the OUTSIDE (dx = +-7.60) abutting `btail2`:
    buf_y = tail_y  # -9.80
    btail_dx = 4.31
    binp_dx = 7.60
    y_buf_drain = grid(buf_y + 1.00)     # -8.80 (binp drains & btail2 sources)
    y_buf_source = grid(buf_y - 1.00)    # -10.80 (binp sources & btail2 drain = tail_buf)
    y_buf_gate = grid(buf_y + 1.775)     # -8.025 (binp top gate strap)
    y_btail_gate = grid(buf_y - 1.775)   # -11.575 (btail2 bottom gate strap)
    y_buf_body_top = grid(buf_y + 2.285) # -7.515
    y_buf_body_bot = grid(buf_y - 2.285) # -12.085

    vss_strap_x = 5.40
    for sign in (-1.0, 1.0):
        c.include(btail2, dx=grid(sign * btail_dx), dy=buf_y, mirror_x=(sign > 0))
        c.include(binp, dx=grid(sign * binp_dx), dy=buf_y, mirror_x=(sign > 0))

        # 2A. `tail_buf` at y = -10.80: btail2 drain (+-4.31) + binp 3 sources (+-6.64, +-7.60, +-8.56):
        c.via1(grid(sign * btail_dx), y_buf_source)
        for sx_loc in (-0.96, 0.00, +0.96):
            c.via1(grid(sign * (binp_dx + sx_loc)), y_buf_source)

        # 2B. Upper VSS: btail2 2 sources (+-3.52, +-5.10) at y = -8.80 + top guard rings -> y = -5.40 / +5.15:
        for sx_tail in (grid(sign * (btail_dx - 0.79)), grid(sign * (btail_dx + 0.79))):
            c.via1(sx_tail, y_buf_drain)
        c.wire("metal2", [(grid(sign * (btail_dx - 0.79)), y_buf_drain), (grid(sign * vss_strap_x), y_buf_drain)], 0.36)
        c.wire("metal2", [(grid(sign * vss_strap_x), y_buf_drain), (grid(sign * vss_strap_x), body_rail_y)], 0.50)

        c.body_contact(grid(sign * btail_dx), y_buf_body_top)
        c.body_contact(grid(sign * 8.20), y_buf_body_top)
        c.wire("metal2", [(grid(sign * btail_dx), y_buf_body_top), (grid(sign * 6.07), y_buf_body_top)], 0.36)
        c.wire("metal2", [(grid(sign * btail_dx), y_buf_body_top), (grid(sign * btail_dx), -5.40)], 0.36)
        c.wire("metal2", [(grid(sign * 8.20), y_buf_body_top), (grid(sign * 8.20), -5.40)], 0.36)
        c.wire("metal2", [(grid(sign * vss_strap_x), -5.40), (grid(sign * 14.00), -5.40)], 0.40)

        # 2C. Lower VSS: binp bottom guard ring (+-7.60, -12.085) -> ts_y (-12.45) -> ground_y (-15.60),
        # plus vertical M1 VSS strap at shared guard bar x = +-6.07 um connecting y = -12.45 to y = -7.515!
        c.body_contact(grid(sign * binp_dx), y_buf_body_bot)
        c.wire("metal2", [(grid(sign * binp_dx), y_buf_body_bot), (grid(sign * binp_dx), ts_y)], 0.36)
        c.wire("metal2", [(grid(sign * vss_strap_x), ts_y), (grid(sign * vss_strap_x), ground_y)], 0.50)
        c.via1(grid(sign * 6.07), ts_y)
        c.via1(grid(sign * 6.07), y_buf_body_top)
        c.wire("metal1", [(grid(sign * 6.07), ts_y), (grid(sign * 6.07), y_buf_body_top)], 0.24)

        # 2D. Direct M1 `vbias` gate connection from btail2 (+-4.31, -11.575) straight down to tgy (-13.225):
        c.wire("metal1", [(grid(sign * btail_dx), y_btail_gate), (grid(sign * btail_dx), tgy)], 0.24)

        # 2E. `binp` 2 drains (+-7.12, +-8.08) at y = -8.80 -> M2 outward to x = +-9.80 -> M1 up to bload R2 (+6.56):
        for dx_loc in (-0.48, +0.48):
            c.via1(grid(sign * (binp_dx + dx_loc)), y_buf_drain)
        c.wire("metal2", [(grid(sign * 7.12), y_buf_drain), (grid(sign * 9.80), y_buf_drain)], 0.36)
        c.via1(grid(sign * 9.80), y_buf_drain)
        br2_y = grid(bload_y + bload.pins("R2")[0][1])  # +6.56
        c.wire(
            "metal1",
            [
                (grid(sign * 9.80), y_buf_drain),
                (grid(sign * 9.80), +4.50),
                (grid(sign * 10.80), +4.50),
                (grid(sign * 10.80), br2_y),
            ],
            0.28,
        )

        # 2F. Export boutn (left, -12.00) and boutp (right, +12.00) from bload R2 ring at x = +-13.10 -> M2 at x = +-14.00:
        c.via1(grid(sign * 13.10), br2_y)
        c.wire(
            "metal2",
            [
                (grid(sign * 13.10), br2_y),
                (grid(sign * 14.00), br2_y),
                (grid(sign * 14.00), +18.65),
            ],
            0.36,
        )

        # 2G. Lift `binp` top gate strap (y = -8.025) at x = +-6.85 to M3 across [+-6.40, +-7.20] so vertical M3
        # oscillator output trunks (`dx_out = +-6.45` on Top, `+-7.05` on Bottom) connect automatically on M3!
        via1_2(c, grid(sign * 6.85), -7.95)
        c.wire("metal3", [(grid(sign * 6.40), -7.95), (grid(sign * 7.20), -7.95)], 0.36)

    # Single straight M2 `tail_buf` bar across [-8.56, +8.56] at y = -10.80:
    c.wire("metal2", [(-8.56, y_buf_source), (+8.56, y_buf_source)], 0.38)

    # Single straight M2 `ts_y` VSS bar across [-7.60, +7.60] at y = -12.45 + ground_y bar at y = -15.60:
    c.wire("metal2", [(-binp_dx, ts_y), (+binp_dx, ts_y)], 0.50)
    for tx in (tsources[0], tsources[-1]):
        c.wire("metal2", [(tx, ts_y), (tx, ground_y)], 0.50)
    c.wire("metal2", [(-vss_strap_x, ground_y), (+vss_strap_x, ground_y)], 0.90)

    # Single straight M1 `vbias` gate bar across [-4.31, +4.31] at y = -13.225:
    c.wire("metal1", [(-btail_dx, tgy), (+btail_dx, tgy)], 0.24)
    c.wire("metal1", [(bias_x, tgy), (bias_x, bias_y)], 0.24)
    c.via1(bias_x, bias_y)

    # Standalone cell adds the M4->M3 drop at (+-6.45, +3.00) and vertical M3 trunk down to y_buf_gate (-8.025):
    c_standalone = Cell()
    c_standalone.include(c)
    for sign in (-1.0, 1.0):
        xo = grid(sign * 6.45)
        c_standalone.wire("metal4", [(xo, +4.20), (xo, +3.00)], 0.40)
        via3(c_standalone, xo, +3.00)
        c_standalone.wire("metal3", [(xo, +3.00), (xo, y_buf_gate)], 0.36)

    c_standalone.labels = []
    c_standalone.port("inp", "metal2", -inp_dx, inp_y)
    c_standalone.port("inn", "metal2", inp_dx, inp_y)
    c_standalone.port("outp", "metal4", -7.20, out_bar_y)
    c_standalone.port("outn", "metal4", 7.20, out_bar_y)
    c_standalone.port("boutp", "metal2", +14.00, +18.65)
    c_standalone.port("boutn", "metal2", -14.00, +18.65)
    c_standalone.port("vbias", "metal2", bias_x, bias_y)
    c_standalone.port("vdd", "metal2", 0.0, vdd_y)
    c_standalone.port("vss", "metal2", 0.0, ground_y)
    c_standalone.write(cdir / f"{name}.mag")

    c.write(cdir / f"{name}_base.mag")

    ref_lines = [
        f".subckt {name} inp inn outp outn boutp boutn vbias vdd vss",
        "Xp outp inp tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15",
        "Xn outn inn tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15",
        "Xt tail vbias vss vss sky130_fd_pr__nfet_01v8 w=25.2 l=0.5",
        "Xrp1 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrp2 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrn1 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrn2 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xbmp boutn outp tail_buf vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15",
        "Xbmn boutp outn tail_buf vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15",
        "Xbtail tail_buf vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5",
        "Xbrp vdd boutn vss sky130_fd_pr__res_high_po_2p85 l=4.22",
        "Xbrn vdd boutp vss sky130_fd_pr__res_high_po_2p85 l=4.22",
        f".ends {name}\n",
    ]
    ref_path = cdir / "reference.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(ROOT / "verification/layout/check.py"), str(cdir), name, "--ref", str(ref_path)],
        capture_output=True,
        text=True,
    )
    (cdir / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr, flush=True)
    if proc.returncode:
        raise RuntimeError(f"Delay+Buf core check failed: {cdir / 'check.log'}")

    bx1, by1, bx2, by2 = c_standalone.bbox()
    meta = dict(
        cell=name,
        bbox_um=[round(bx1, 3), round(by1, 3), round(bx2, 3), round(by2, 3)],
        width_um=round(bx2 - bx1, 3),
        height_um=round(by2 - by1, 3),
        area_um2=round((bx2 - bx1) * (by2 - by1), 2),
        drc=0,
        lvs=True,
    )
    (cdir / "summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return c, meta


def build_stage_pair_buf_cells(
    work: Path, variant: str = "s32p5"
) -> tuple[Cell, Cell, Path, str, list[tuple[str, float]], dict]:
    """Build Left Stage and Right Stage with Embedded CML Buffers and Outward-Shifted Half-Tanks (`tank_cx = 22.70 um`)."""
    core_base, cmeta = build_delay_buf_core(work)
    build_half_tank(work, variant)

    tank_dir = work / variant
    tank_name = f"pll_vco_half_tank_sym9_{variant}"
    tank_cell = Cell.read(tank_dir / f"{tank_name}.mag")
    tank_cell.labels = []
    tank_inner = make_inner_tank_cell(tank_cell)

    rungs: list[tuple[str, float]] = []
    for _, bit, u, x_center, _ in HALF_TANK_BLOCKS:
        leaf_cell = Cell.read(tank_dir / f"leaf_b{bit}_u{u}/pll_vco_sym9_{variant}_b{bit}_u{u}.mag")
        gx_orig, _ = leaf_cell.pins("en")[0]
        rungs.append((f"b{bit}", round(gx_orig + x_center, 3)))

    tank_cx = 22.70
    node_x = round(tank_cx - 11.02, 2)  # 11.68 um

    def assemble(t_left: Cell, t_right: Cell) -> Cell:
        st = Cell()
        st.include(core_base)
        st.include(t_left, dx=-tank_cx, dy=0.0)
        st.include(t_right, dx=+tank_cx, dy=0.0)
        for sign in (-1.0, 1.0):
            st.wire("metal4", [(sign * 7.20, 4.20), (sign * node_x, 4.20), (sign * node_x, 2.87)], 0.50)
            st.wire("metal2", [(sign * 5.40, -5.40), (sign * (tank_cx - 4.00), -5.40)], 0.40)
            st.wire("metal2", [(sign * 17.05, +5.15), (sign * (tank_cx + 0.60), +5.15)], 0.40)
        return st

    stage_left_top = assemble(
        rotate_cell_90(tank_cell, "recess_right"),
        rotate_cell_90(tank_inner, "recess_left"),
    )
    stage_right_top = assemble(
        rotate_cell_90(tank_inner, "recess_right"),
        rotate_cell_90(tank_cell, "recess_left"),
    )
    return stage_left_top, stage_right_top, tank_dir, tank_name, rungs, cmeta


def build_vco_core(work: Path, variant: str = "s32p5") -> dict:
    stage_L_top, stage_R_top, tank_dir, tank_name, rungs, cmeta = build_stage_pair_buf_cells(work, variant)
    stage_L_bot = mirror_cell_y(stage_L_top)
    stage_R_bot = mirror_cell_y(stage_R_top)

    rdir = work / f"core_{variant}"
    rdir.mkdir(parents=True, exist_ok=True)
    cell_name = f"pll_vco_core_sym9_{variant}"

    c = Cell()
    tank_cx = 22.70
    DX = round(tank_cx + 3.35, 2)  # 26.05 um
    DY = 19.35

    # Place 4 quadrants with DX = +-26.05 um, DY = +-19.35 um:
    c.include(stage_L_top, dx=-DX, dy=+DY)
    c.include(stage_R_top, dx=+DX, dy=+DY)
    c.include(stage_R_bot, dx=+DX, dy=-DY)
    c.include(stage_L_bot, dx=-DX, dy=-DY)

    # =========================================================================
    # STEP 1: Power & Ground (100% Top-Bottom Symmetric VSS and VDD!)
    # =========================================================================
    x_vss_outer = round(DX + tank_cx + 0.60, 2)  # 49.35 um
    x_vss_inner = round(DX - tank_cx - 0.60, 2)  #  2.75 um
    y_vss_b4 = grid(DY - 16.30)                  #  3.05 um
    c.wire("metal2", [(-x_vss_outer, 0.00), (+x_vss_outer, 0.00)], 0.36)

    for sx in (-1, +1):
        xo = grid(sx * x_vss_outer)
        c.wire("metal2", [(xo, -y_vss_b4), (xo, +y_vss_b4)], 0.50)

    for sx in (-1, +1):
        xi = grid(sx * x_vss_inner)
        c.wire("metal2", [(xi, +2.20), (xi, +y_vss_b4)], 0.50)
        c.wire("metal2", [(xi, -y_vss_b4), (xi, -2.20)], 0.50)
        c.via2(xi, +2.20)
        c.via2(xi, 0.00)
        c.via2(xi, -2.20)
        c.wire("metal3", [(xi, -2.20), (xi, +2.20)], 0.44)

    y_core_vss = grid(DY - 15.60)  # 3.75 um
    for qx in (-DX, +DX):
        for sx in (-1, +1):
            xc = grid(qx + sx * 5.40)
            c.via2(xc, +y_core_vss)
            c.via2(xc, 0.00)
            c.via2(xc, -y_core_vss)
            c.wire("metal3", [(xc, -y_core_vss), (xc, +y_core_vss)], 0.44)

    Y_VSS_PORT = 38.00
    y_vss_tank_bar = grid(DY - 5.40)  # 13.95 um
    for sy in (-1, +1):
        yb = grid(sy * y_vss_tank_bar)
        for sx in (-1, +1):
            xi = grid(sx * x_vss_inner)
            via2_3(c, xi, yb)
        c.wire("metal4", [(-x_vss_inner, yb), (+x_vss_inner, yb)], 0.50)
        c.wire("metal4", [(0.00, yb), (0.00, grid(sy * Y_VSS_PORT))], 0.80)

    # Dual-End VDD Rails (y = +-39.50 um, x = +-53.90 um):
    y_vdd_stage = grid(DY + 15.99)  # 35.34 um
    Y_VDD_TOP = +39.50
    Y_VDD_BOT = -39.50
    X_VDD_RING = round(x_vss_outer + 4.55, 2)  # 53.90 um
    for qx in (-DX, +DX):
        via2_3(c, qx, +y_vdd_stage)
        c.wire("metal4", [(qx, +y_vdd_stage), (qx, Y_VDD_TOP)], 0.80)
        via2_3(c, qx, -y_vdd_stage)
        c.wire("metal4", [(qx, -y_vdd_stage), (qx, Y_VDD_BOT)], 0.80)
    c.wire("metal4", [(-X_VDD_RING, Y_VDD_TOP), (+X_VDD_RING, Y_VDD_TOP)], 0.80)
    c.wire("metal4", [(-X_VDD_RING, Y_VDD_BOT), (+X_VDD_RING, Y_VDD_BOT)], 0.80)
    for sx in (-1, +1):
        xv = grid(sx * X_VDD_RING)
        c.wire("metal4", [(xv, Y_VDD_BOT), (xv, Y_VDD_TOP)], 0.80)

    # =========================================================================
    # STEP 2: 8-Point Oscillator Ring Crossbar (M3 across `[Xbmp | Xbtail]` -> M1 + M2 in Center!)
    # =========================================================================
    Y_OUT_PORT = 38.00
    y_out_top = grid(+DY + 4.20)     # +23.55
    y_out_bot = grid(-DY - 4.20)     # -23.55
    y_drop_top = grid(+DY + 3.00)    # +22.35
    y_drop_bot = grid(-DY - 3.00)    # -22.35
    y_inp_top = grid(+DY - 4.50)     # +14.85
    y_inp_bot = grid(-DY + 4.50)     # -14.85
    y_m3_bot_top = +2.40             # +2.40 (in open corridor below Top ground_y = +3.75)
    y_m3_bot_bot = -2.40             # -2.40 (in open corridor above Bottom ground_y = -3.75)

    # (net, x_out, y_drop, y_m3_out, y_port, x_in, y_istrap, y_m3_in, y_cross)
    phase_routes = [
        ("q0p", grid(-DX - 6.45), y_drop_top, y_m3_bot_top, +Y_OUT_PORT, grid(+DX - 3.55), y_inp_top, y_m3_bot_top, +0.96),
        ("q0n", grid(-DX + 6.45), y_drop_top, y_m3_bot_top, +Y_OUT_PORT, grid(+DX + 3.55), y_inp_top, y_m3_bot_top, +0.48),
        ("q2p", grid(+DX - 7.05), y_drop_bot, y_m3_bot_bot, -Y_OUT_PORT, grid(-DX - 4.15), y_inp_bot, y_m3_bot_bot, -0.48),
        ("q2n", grid(+DX + 7.05), y_drop_bot, y_m3_bot_bot, -Y_OUT_PORT, grid(-DX + 4.15), y_inp_bot, y_m3_bot_bot, -0.96),
        ("q1p", grid(+DX - 6.45), y_drop_top, y_m3_bot_top, +Y_OUT_PORT, grid(+DX - 4.15), y_inp_bot, y_m3_bot_bot, +1.50),
        ("q1n", grid(+DX + 6.45), y_drop_top, y_m3_bot_top, +Y_OUT_PORT, grid(+DX + 4.15), y_inp_bot, y_m3_bot_bot, -1.50),
        ("q3p", grid(-DX - 7.05), y_drop_bot, y_m3_bot_bot, -Y_OUT_PORT, grid(-DX + 3.55), y_inp_top, y_m3_bot_top, +1.50),
        ("q3n", grid(-DX + 7.05), y_drop_bot, y_m3_bot_bot, -Y_OUT_PORT, grid(-DX - 3.55), y_inp_top, y_m3_bot_top, -1.50),
    ]
    for net, x_out, y_drop, y_m3_out, y_port, x_in, y_istrap, y_m3_in, y_cross in phase_routes:
        # 1. Output trunk: M4 port -> via3 at y_drop -> M3 across `[Xbmp | Xbtail]` (tapping Xbmp/Xbmn M3 gate bar!)
        #    -> via1_2 at y_m3_out -> M1 into central M2 crossbar:
        c.wire("metal4", [(x_out, y_port), (x_out, y_drop)], 0.40)
        via3(c, x_out, y_drop)
        c.wire("metal3", [(x_out, y_drop), (x_out, y_m3_out)], 0.36)
        via1_2(c, x_out, y_m3_out)
        c.wire("metal1", [(x_out, y_m3_out), (x_out, y_cross)], 0.28)
        c.via1(x_out, y_cross)

        # 2. Input trunk: M2 gate strap at y_istrap -> via2 -> M3 across `[Xbmp | Xbtail]`
        #    -> via1_2 at y_m3_in -> M1 into central M2 crossbar:
        c.via2(x_in, y_istrap)
        c.wire("metal3", [(x_in, y_istrap), (x_in, y_m3_in)], 0.36)
        via1_2(c, x_in, y_m3_in)
        c.wire("metal1", [(x_in, y_m3_in), (x_in, y_cross)], 0.28)
        c.via1(x_in, y_cross)

        # 3. Horizontal M2 crossbar segment:
        c.wire("metal2", [(x_out, y_cross), (x_in, y_cross)], 0.28)

    # =========================================================================
    # STEP 3 & 4: 5-Track Vertical M3 Cap-Bank Control Bus (cfg0..cfg4), Varactor (ctrl), Bias (vbias_q)
    # =========================================================================
    ctrl_specs = [
        ("cfg0", 1.40, -1.40, +6.05),
        ("cfg1", 2.10, -0.70, +5.20),
        ("cfg2", 2.80,  0.00, +4.35),
        ("cfg3", 3.50, +0.70, -4.35),
        ("cfg4", 4.20, +1.40, -5.20),
    ]
    b_to_cfg = {f"b{i}": f"cfg{i}" for i in range(5)}
    x_shared_map = {name: x_c for name, _, x_c, _ in ctrl_specs}

    for qy, sy in ((+DY, +1), (-DY, -1)):
        for bname, gx in rungs:
            y_row = grid(qy + sy * gx)
            x_c = x_shared_map[b_to_cfg[bname]]
            c.wire("metal2", [(-1.95, y_row), (+1.95, y_row)], 0.30)
            c.via2(x_c, y_row)

    ctrl_ports = {}
    y_ctrl_span = grid(+DY + max(gx for _, gx in rungs))  # 35.50 um
    x_m4_in = round(DX - 10.05, 2)   # 16.00 um
    x_m4_out = round(DX + 10.05, 2)  # 36.10 um
    for cname, ty_orig, x_c, y_bus in ctrl_specs:
        x_left_out = grid(-DX - tank_cx - ty_orig)
        x_right_out = grid(+DX + tank_cx + ty_orig)
        for x_col in (x_left_out, x_c, x_right_out):
            c.wire("metal3", [(x_col, -y_ctrl_span), (x_col, +y_ctrl_span)], 0.36)
            c.via2(x_col, y_bus)
        c.wire("metal2", [(x_left_out, y_bus), (-x_m4_out, y_bus)], 0.30)
        via2_3(c, -x_m4_out, y_bus)
        c.wire("metal4", [(-x_m4_out, y_bus), (-x_m4_in, y_bus)], 0.36)
        via2_3(c, -x_m4_in, y_bus)
        c.wire("metal2", [(-x_m4_in, y_bus), (+x_m4_in, y_bus)], 0.30)
        via2_3(c, +x_m4_in, y_bus)
        c.wire("metal4", [(+x_m4_in, y_bus), (+x_m4_out, y_bus)], 0.36)
        via2_3(c, +x_m4_out, y_bus)
        c.wire("metal2", [(+x_m4_out, y_bus), (x_right_out, y_bus)], 0.30)
        ctrl_ports[cname] = (-DX, y_bus)

    # Varactor Control (ctrl) on M4 + M3 inside the Core window (bridged at y = -6.05 um):
    var_port_dx = round(tank_cx - 11.46, 2)  # 11.24 um
    y_var_top = grid(+DY - 2.00)  # +17.35 um
    y_var_bot = grid(-DY + 2.00)  # -17.35 um
    y_vc_bus = -6.05
    x_vc_cols = []
    for qx in (-DX, +DX):
        x_vp = grid(qx - var_port_dx)
        x_vn = grid(qx + var_port_dx)
        x_vc = grid(qx + 2.40)
        x_vc_cols.append(x_vc)
        for yv in (y_var_top, y_var_bot):
            c.wire("metal4", [(x_vp, yv), (x_vn, yv)], 0.40)
            via3(c, x_vc, yv)
        c.wire("metal3", [(x_vc, y_var_bot), (x_vc, y_var_top)], 0.36)
        via3(c, x_vc, y_vc_bus)
    c.wire("metal4", [(x_vc_cols[0], y_vc_bus), (-x_m4_in, y_vc_bus)], 0.36)
    via2_3(c, -x_m4_in, y_vc_bus)
    c.wire("metal2", [(-x_m4_in, y_vc_bus), (+x_m4_in, y_vc_bus)], 0.30)
    via2_3(c, +x_m4_in, y_vc_bus)
    c.wire("metal4", [(+x_m4_in, y_vc_bus), (x_vc_cols[1], y_vc_bus)], 0.36)
    ctrl_ports["ctrl"] = (+DX, y_vc_bus)

    # Symmetric Tail Bias (vbias_q) on M1 + M4 along y = 0.00 um:
    y_bias_top = grid(+DY - 14.60)  # +4.75
    y_bias_bot = grid(-DY + 14.60)  # -4.75
    y_bias_lift = 2.40
    x_bias_cols = []
    for qx in (-DX, +DX):
        xb = grid(qx - 2.40)
        x_bias_cols.append(xb)
        c.wire("metal1", [(xb, y_bias_bot), (xb, y_bias_top)], 0.28)
        via1_2_3(c, xb, +y_bias_lift)
        via1_2_3(c, xb, -y_bias_lift)
        c.wire("metal4", [(xb, -y_bias_lift), (xb, +y_bias_lift)], 0.40)
    c.wire("metal4", [(x_bias_cols[0], 0.00), (x_bias_cols[1], 0.00)], 0.40)

    # Buffered output port coordinates (`x_stage = -14.00 -> bkn`, `x_stage = +14.00 -> bkp`, `y_ring = +-38.00`):
    b_ports = {
        "b0n": (grid(-DX - 14.00), +Y_OUT_PORT),
        "b0p": (grid(-DX + 14.00), +Y_OUT_PORT),
        "b1n": (grid(+DX - 14.00), +Y_OUT_PORT),
        "b1p": (grid(+DX + 14.00), +Y_OUT_PORT),
        "b2n": (grid(+DX - 14.00), -Y_OUT_PORT),
        "b2p": (grid(+DX + 14.00), -Y_OUT_PORT),
        "b3n": (grid(-DX - 14.00), -Y_OUT_PORT),
        "b3p": (grid(-DX + 14.00), -Y_OUT_PORT),
    }

    # Export exact 17-port order matching `pll_vco_core` in `pll_vco_core_ref.spice`:
    #   ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias_q b0p b0n b1p b1n b2p b2n b3p b3n vdd_q vss
    c.labels = []
    c.port("ctrl", "metal4", *ctrl_ports["ctrl"])
    for bit in range(5):
        c.port(f"cfg{bit}", "metal4", *ctrl_ports[f"cfg{bit}"])
    c.port("vbias_q", "metal4", x_bias_cols[0], 0.00)
    for qid in ("0", "1", "2", "3"):
        c.port(f"b{qid}p", "metal2", *b_ports[f"b{qid}p"])
        c.port(f"b{qid}n", "metal2", *b_ports[f"b{qid}n"])
    c.port("vdd_q", "metal4", 0.00, Y_VDD_TOP)
    c.port("vss", "metal4", 0.00, Y_VSS_PORT)
    c.write(rdir / f"{cell_name}.mag")

    # Build reference SPICE netlist matching `pll_vco_core_ref.spice` hierarchy with our s32p5 half-tanks:
    tank_ref = re.sub(
        r"(sky130_fd_pr__cap_mim_m3_1\s+)w=(\S+)\s+l=(\S+)",
        r"\1w=\3 l=\2",
        (tank_dir / f"{tank_name}_reference.spice").read_text(),
    )
    delay_ref = "\n".join([
        ".subckt pll_vco_delay_sym9_c inp inn outp outn vbias vdd vss",
        "Xp outp inp tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15",
        "Xn outn inn tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15",
        "Xt tail vbias vss vss sky130_fd_pr__nfet_01v8 w=25.2 l=0.5",
        "Xrp1 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrp2 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrn1 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrn2 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        ".ends pll_vco_delay_sym9_c",
    ])
    buf_ref = "\n".join([
        ".subckt serdes_cml_buffer inp inn outp outn vbias vdd vss",
        "Xmp outn inp tail vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15",
        "Xmn outp inn tail vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15",
        "Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5",
        "Xrp vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.22",
        "Xrn vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.22",
        ".ends serdes_cml_buffer",
    ])
    core_ref = "\n".join([
        tank_ref,
        delay_ref,
        buf_ref,
        f".subckt {cell_name} ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias_q b0p b0n b1p b1n b2p b2n b3p b3n vdd_q vss",
        "X0 v3n v3p v0p v0n vbias_q vdd_q vss pll_vco_delay_sym9_c",
        "X1 v0p v0n v1p v1n vbias_q vdd_q vss pll_vco_delay_sym9_c",
        "X2 v1p v1n v2p v2n vbias_q vdd_q vss pll_vco_delay_sym9_c",
        "X3 v2p v2n v3p v3n vbias_q vdd_q vss pll_vco_delay_sym9_c",
        f"Xtank0p v0p ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank0n v0n ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank1p v1p ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank1n v1n ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank2p v2p ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank2n v2n ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank3p v3p ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        f"Xtank3n v3n ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vss {tank_name}",
        "Xbuf0 v0p v0n b0p b0n vbias_q vdd_q vss serdes_cml_buffer",
        "Xbuf1 v1p v1n b1p b1n vbias_q vdd_q vss serdes_cml_buffer",
        "Xbuf2 v2p v2n b2p b2n vbias_q vdd_q vss serdes_cml_buffer",
        "Xbuf3 v3p v3n b3p b3n vbias_q vdd_q vss serdes_cml_buffer",
        f".ends {cell_name}\n",
    ])
    ref_path = rdir / "reference.spice"
    ref_path.write_text(core_ref)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "verification/layout/check.py"), str(rdir), cell_name, "--ref", str(ref_path)],
        capture_output=True,
        text=True,
    )
    log = proc.stdout + proc.stderr
    (rdir / "check.log").write_text(log)
    print(log, flush=True)
    if proc.returncode:
        raise RuntimeError(f"VCO Core check failed: {rdir / 'check.log'}")

    lvs_text = (rdir / f"{cell_name}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_text, re.M)))

    bx1, by1, bx2, by2 = c.bbox()
    meta = dict(
        cell=cell_name,
        variant=variant,
        bbox_um=[round(bx1, 3), round(by1, 3), round(bx2, 3), round(by2, 3)],
        width_um=round(bx2 - bx1, 3),
        height_um=round(by2 - by1, 3),
        area_um2=round((bx2 - bx1) * (by2 - by1), 2),
        drc=0,
        lvs=True,
        extracted_models=models,
        delay_buf_core=cmeta,
    )
    (rdir / "summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--variant", default="s32p5")
    args = ap.parse_args()

    out = args.output_dir or (
        ROOT / "results/layout/pll_vco" / ("vco_core_sym9_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    meta = build_vco_core(out, args.variant)
    (out / "summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("COMPLETE SUMMARY:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
