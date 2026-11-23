#!/usr/bin/env python3
"""Build and verify the 4-Stage Ring VCO (`pll_vco_ring4_sym9_<variant>`) in SKY130 PDK.

Architecture (Structured 4-Step Layer-Segregated Quad Topology, `DX = +-24.15 um, DY = +-19.00 um`):
1. Zero Central Tank Gap (`DY = 19.00 um`):
   - Top (`X0, X1`) and Bottom (`X3, X2`) Half-Tanks abut directly at `y = 0` (`0.52 um` MIM-to-MIM spacing).
2. Step 1 — Power & Ground ("VSS拉到中间，两端两个VDD"):
   - Central `VSS`: Full-width horizontal `M2` ground spine at `y = 0.00 um` (`x in [-45.55, +45.55] um`) +
     central vertical `M4` ground spine at `x = 0.00 um` (`y in [-38.00, +38.00] um`), tying all 4 Half-Tank
     `VSS` columns (`x = +-45.55, +-2.75 um`) and all 4 Core `VSS` columns (`x = qx +- 5.40 um`) into the center.
   - Dual-End `VDD`: Top horizontal `M4` `VDD` rail (`y = +39.00 um`) and Bottom horizontal `M4` `VDD` rail
     (`y = -42.70 um`) feed the top (`X0, X1`) and bottom (`X3, X2`) load resistor banks from the two ends,
     closed into a ring by outer vertical `M4` columns (`x = +-50.80 um`).
3. Step 2 — 8-Point Oscillator Ring Crossbar on `M1 + M2` ("8点振荡器过线使用M1 M2"):
   - All 8 stage inputs (`inp/inn`) and 8 stage outputs (`outp/outn`) drop vertically into the center on `M1`
     (`dx_in = +-3.55 / +-4.15 um`, `dx_out = +-6.45 / +-7.05 um`, all 16 vertical `M1` trunks at unique X!).
   - In `y in [-1.50, +1.50] um` (underneath the abutting `b4` MIMs on `M3/M4` and underneath the vertical `M3`
     control buses!), 6 horizontal `M2` tracks (`y = +-0.48, +-0.96, +-1.50 um`) symmetrically straddle the
     central `y = 0.00 um` `M2` `VSS` ground shield.
4. Step 3 & 4 — Varactor (`vctrl`), Shared-Center Cap-Bank Control (`b0..b4`) on `M2 + M3`, and Bias (`vbias`):
   - The two inner Half-Tanks (`X0.Tank-N + X1.Tank-P` on top, `X3.Tank-N + X2.Tank-P` on bottom) merge their
     horizontal `M2` switch/varactor fingers (`x in [-1.95, +1.95] um`) onto ONE shared 6-track vertical `M3`
     control bus right down `x in [-1.75, +1.75] um`.
   - The 3 vertical `M3` control columns (Left Outer, Shared Center, Right Outer) tie onto 6 horizontal `M2`
     bus tracks at the bottom (`y = -38.40 .. -41.40 um`), alongside `vbias` at `y = -42.00 um`.
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
sys.path.insert(0, str(ROOT / "analog/pll/vco/layout"))

from build_delay_stage_sym9_pdk import (
    Cell,
    build_delay_core_c,
    grid,
    rotate_cell_90,
    via3,
)
from build_half_tank_sym9_pdk import HALF_TANK_BLOCKS, build_half_tank


def mirror_cell_y(src: Cell) -> Cell:
    """Return a new Cell reflected across the X-axis (`y -> -y`)."""
    dst = Cell()
    for layer, rects in src.rects.items():
        for x1, y1, x2, y2 in rects:
            dst.rect(layer, x1, -y2, x2, -y1)
    return dst


def pad(c: Cell, layer: str, x: float, y: float, w: float, h: float | None = None) -> None:
    h = w if h is None else h
    c.rect(layer, x - w / 2, y - h / 2, x + w / 2, y + h / 2)


def via2_3(c: Cell, x: float, y: float) -> None:
    """Connect metal2 -> metal3 -> metal4 at (x, y) with clean enclosures."""
    c.via2(x, y)
    pad(c, "metal3", x, y, 0.50, 0.50)
    via3(c, x, y)


def via1_2_3(c: Cell, x: float, y: float) -> None:
    """Connect metal1 -> metal2 -> metal3 -> metal4 at (x, y) with clean enclosures."""
    c.via1(x, y)
    pad(c, "metal2", x, y, 0.44, 0.44)
    via2_3(c, x, y)


def spice_number(text: str) -> float:
    scale = {"f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9}
    m = re.match(r"^([+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?)([a-zA-Z]*)$", text.strip())
    if not m:
        raise ValueError(f"Cannot parse SPICE number: {text!r}")
    val = float(m.group(1))
    suf = m.group(2).lower()
    return val * scale.get(suf, 1.0)


def make_inner_tank_cell(tank_cell: Cell) -> Cell:
    """Strip the individual M2->M3 control bus above y_orig = 1.56 um (and via2/M3 at y >= 1.20 um)
    so the inner left and right half-tanks can butt-join their M2 fingers at y_orig = 1.40 um
    onto the single shared 6-track vertical M3 bus down x = 0.
    """
    inner = Cell()
    for layer, rects in tank_cell.rects.items():
        kept = []
        for r in rects:
            if layer in ("via2", "metal3") and r[1] >= 1.10:
                continue
            if layer == "metal2" and r[3] > 1.58:
                continue
            kept.append(r)
        if kept:
            inner.rects[layer] = kept
    return inner


def build_stage_pair_cells(work: Path, variant: str = "s32p5") -> tuple[Cell, Cell, Path, str, list[tuple[str, float]]]:
    """Build Left Stage (`Outer Tank-P + Core + Inner Tank-N`) and Right Stage (`Inner Tank-P + Core + Outer Tank-N`)."""
    build_delay_core_c(work)
    build_half_tank(work, variant)

    tank_dir = work / variant
    tank_name = f"pll_vco_half_tank_sym9_{variant}"
    tank_cell = Cell.read(tank_dir / f"{tank_name}.mag")
    tank_cell.labels = []
    tank_inner = make_inner_tank_cell(tank_cell)

    # Extract exact x_orig (which becomes y_stage after 90-deg rotation) of every switch gate finger (b0..b4):
    rungs: list[tuple[str, float]] = []
    for _, bit, u, x_center, _ in HALF_TANK_BLOCKS:
        leaf_cell = Cell.read(tank_dir / f"leaf_b{bit}_u{u}/pll_vco_sym9_{variant}_b{bit}_u{u}.mag")
        gx_orig, _ = leaf_cell.pins("en")[0]
        rungs.append((f"b{bit}", round(gx_orig + x_center, 3)))

    core_clean = Cell.read(work / "delay_core_c/pll_vco_delay_sym9_c.mag")
    core_clean.labels = []

    tank_cx = 20.80
    node_x = round(tank_cx - 11.02, 2)  # 9.78 um

    def assemble(t_left: Cell, t_right: Cell) -> Cell:
        st = Cell()
        st.include(core_clean)
        st.include(t_left, dx=-tank_cx, dy=0.0)
        st.include(t_right, dx=+tank_cx, dy=0.0)
        for sign in (-1.0, 1.0):
            st.wire("metal4", [(sign * 7.20, 4.20), (sign * node_x, 4.20), (sign * node_x, 2.87)], 0.50)
            st.wire("metal2", [(sign * 5.40, -5.40), (sign * (tank_cx - 4.00), -5.40)], 0.40)
            st.wire("metal2", [(sign * 12.40, +5.15), (sign * (tank_cx + 0.60), +5.15)], 0.40)
        return st

    # Left stage: Outer Tank-P (full M3 bus) on left, Inner Tank-N (shared M2 entry) on right
    stage_left_top = assemble(
        rotate_cell_90(tank_cell, "recess_right"),
        rotate_cell_90(tank_inner, "recess_left"),
    )
    # Right stage: Inner Tank-P (shared M2 entry) on left, Outer Tank-N (full M3 bus) on right
    stage_right_top = assemble(
        rotate_cell_90(tank_inner, "recess_right"),
        rotate_cell_90(tank_cell, "recess_left"),
    )
    return stage_left_top, stage_right_top, tank_dir, tank_name, rungs


def build_vco_ring4(work: Path, variant: str = "s32p5") -> dict:
    stage_L_top, stage_R_top, tank_dir, tank_name, rungs = build_stage_pair_cells(work, variant)
    stage_L_bot = mirror_cell_y(stage_L_top)
    stage_R_bot = mirror_cell_y(stage_R_top)

    rdir = work / f"ring4_{variant}"
    rdir.mkdir(parents=True, exist_ok=True)
    cell_name = f"pll_vco_ring4_sym9_{variant}"

    c = Cell()
    DX = 24.15
    DY = 19.35
    tank_cx = 20.80

    # Place 4 quadrants with DY = +-19.35 um (exact capm.11 abutment of top and bottom capacitor banks!):
    # X0 (Top-Left), X1 (Top-Right), X2 (Bottom-Right), X3 (Bottom-Left)
    c.include(stage_L_top, dx=-DX, dy=+DY)
    c.include(stage_R_top, dx=+DX, dy=+DY)
    c.include(stage_R_bot, dx=+DX, dy=-DY)
    c.include(stage_L_bot, dx=-DX, dy=-DY)

    # =========================================================================
    # STEP 1: Power & Ground (100% Top-Bottom Symmetric VSS and VDD!)
    # =========================================================================
    # 1A. Central VSS Spine (`y = 0.00 um` on M2 across [-45.55, +45.55], plus symmetric top/bottom M4 spines):
    x_vss_outer = round(DX + tank_cx + 0.60, 2)  # 45.55 um
    x_vss_inner = round(DX - tank_cx - 0.60, 2)  #  2.75 um
    y_vss_b4 = grid(DY - 16.30)                  #  3.05 um
    c.wire("metal2", [(-x_vss_outer, 0.00), (+x_vss_outer, 0.00)], 0.36)

    # Outer Left & Right Half-Tank M2 VSS columns (x = +-45.55) tie across [-3.05, +3.05] to y = 0.00:
    # (Note: inside each Half-Tank, VSS bridges |y| in [3.80, 6.60] on M1 so M2 is open for central bridges!)
    for sx in (-1, +1):
        xo = grid(sx * x_vss_outer)
        c.wire("metal2", [(xo, -y_vss_b4), (xo, +y_vss_b4)], 0.50)

    # Inner Left & Right Half-Tank VSS columns (x = +-2.75) step over M2 crossbar on M3 in [-2.20, +2.20]
    # and drop via2 onto the y = 0.00 M2 VSS spine:
    for sx in (-1, +1):
        xi = grid(sx * x_vss_inner)
        c.wire("metal2", [(xi, +2.20), (xi, +y_vss_b4)], 0.50)
        c.wire("metal2", [(xi, -y_vss_b4), (xi, -2.20)], 0.50)
        c.via2(xi, +2.20)
        c.via2(xi, 0.00)
        c.via2(xi, -2.20)
        c.wire("metal3", [(xi, -2.20), (xi, +2.20)], 0.44)

    # Left & Right Core vertical VSS straps (x = qx +- 5.40) step over M2 crossbar on M3 in [-3.75, +3.75]
    # and drop via2 onto the y = 0.00 M2 VSS spine:
    y_core_vss = grid(DY - 15.60)  # 3.75 um
    for qx in (-DX, +DX):
        for sx in (-1, +1):
            xc = grid(qx + sx * 5.40)
            c.via2(xc, +y_core_vss)
            c.via2(xc, 0.00)
            c.via2(xc, -y_core_vss)
            c.wire("metal3", [(xc, -y_core_vss), (xc, +y_core_vss)], 0.44)

    # Symmetric Top (+13.95..+38.00) and Bottom (-38.00..-13.95) vertical M4 VSS spines at x = 0.00 um:
    Y_VSS_PORT = 38.00
    y_vss_tank_bar = grid(DY - 5.40)  # 13.95 um
    for sy in (-1, +1):
        yb = grid(sy * y_vss_tank_bar)
        for sx in (-1, +1):
            xi = grid(sx * x_vss_inner)
            via2_3(c, xi, yb)
        c.wire("metal4", [(-x_vss_inner, yb), (+x_vss_inner, yb)], 0.50)
        c.wire("metal4", [(0.00, yb), (0.00, grid(sy * Y_VSS_PORT))], 0.80)

    # 1B. Symmetric Dual-End VDD Rails ("两端两个VDD", y = +-39.50 um, x = +-50.10 um):
    y_vdd_stage = grid(DY + 15.99)  # 35.34 um
    Y_VDD_TOP = +39.50
    Y_VDD_BOT = -39.50
    X_VDD_RING = 50.10
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
    # STEP 2: 8-Point Oscillator Ring Crossbar on M1 + M2 ("8点振荡器过线使用M1 M2")
    # =========================================================================
    # Stage X coordinates for vertical M1 trunks (all 16 vertical M1 trunks have unique X!):
    #   Top stages (X0, X1):    dx_out = +-6.45, dx_in = +-3.55
    #   Bottom stages (X3, X2): dx_out = +-7.05, dx_in = +-4.15
    Y_OUT_PORT = 38.00
    y_out_top = grid(+DY + 4.20)     # +23.55 (M4 out_bar)
    y_out_bot = grid(-DY - 4.20)     # -23.55 (M4 out_bar)
    y_drop_top = grid(+DY + 3.00)    # +22.35 (M4 -> M1 step-down point)
    y_drop_bot = grid(-DY - 3.00)    # -22.35 (M4 -> M1 step-down point)
    y_inp_top = grid(+DY - 4.50)     # +14.85 (M1 inp_y bar)
    y_inp_bot = grid(-DY + 4.50)     # -14.85 (M1 inp_y bar)

    # (net, x_out, y_out_bar, y_drop, y_port, x_in, y_in_strap, y_cross_m2)
    phase_routes = [
        # Upper Horizontal Pair (X0 -> X1) above y = 0.00 M2 VSS shield:
        ("q0p", grid(-DX - 6.45), y_out_top, y_drop_top, +Y_OUT_PORT, grid(+DX - 3.55), y_inp_top, +0.96),
        ("q0n", grid(-DX + 6.45), y_out_top, y_drop_top, +Y_OUT_PORT, grid(+DX + 3.55), y_inp_top, +0.48),
        # Lower Horizontal Pair (X2 -> X3) below y = 0.00 M2 VSS shield (180-deg symmetric to q0p/n):
        ("q2p", grid(+DX - 7.05), y_out_bot, y_drop_bot, -Y_OUT_PORT, grid(-DX - 4.15), y_inp_bot, -0.48),
        ("q2n", grid(+DX + 7.05), y_out_bot, y_drop_bot, -Y_OUT_PORT, grid(-DX + 4.15), y_inp_bot, -0.96),
        # Right Column Vertical Pair (X1 -> X2) at y = +-1.50 um:
        ("q1p", grid(+DX - 6.45), y_out_top, y_drop_top, +Y_OUT_PORT, grid(+DX - 4.15), y_inp_bot, +1.50),
        ("q1n", grid(+DX + 6.45), y_out_top, y_drop_top, +Y_OUT_PORT, grid(+DX + 4.15), y_inp_bot, -1.50),
        # Left Column Möbius Pair (X3 -> X0) at y = +-1.50 um:
        ("q3p", grid(-DX - 7.05), y_out_bot, y_drop_bot, -Y_OUT_PORT, grid(-DX + 3.55), y_inp_top, +1.50),
        ("q3n", grid(-DX + 7.05), y_out_bot, y_drop_bot, -Y_OUT_PORT, grid(-DX - 3.55), y_inp_top, -1.50),
    ]
    q_ports = {}
    for net, x_out, y_obar, y_drop, y_port, x_in, y_istrap, y_cross in phase_routes:
        # 1. Exported M4 port stub from out_bar to top/bottom edge + M4->M1 drop at y_drop:
        c.wire("metal4", [(x_out, y_port), (x_out, y_drop)], 0.40)
        via1_2_3(c, x_out, y_drop)
        # 2. Vertical M1 output trunk from y_drop into central M2 crossbar:
        c.wire("metal1", [(x_out, y_drop), (x_out, y_cross)], 0.28)
        c.via1(x_out, y_cross)
        # 3. Vertical M1 input trunk from stage M1 gate strap directly into central M2 crossbar:
        c.wire("metal1", [(x_in, y_istrap), (x_in, y_cross)], 0.28)
        c.via1(x_in, y_cross)
        # 4. Horizontal M2 crossbar segment:
        c.wire("metal2", [(x_out, y_cross), (x_in, y_cross)], 0.28)
        q_ports[net] = (x_out, y_port)

    # =========================================================================
    # STEP 3 & 4: 5-Track Vertical M3 Cap-Bank Control Bus (b0..b4) Bridged in Center via M2+M4,
    #             Varactor (vctrl) Routed on M4+M3 Inside Core, and Symmetric Bias (vbias)
    # =========================================================================
    # 3A. 5-Track Vertical M3 Control Bus (b0..b4) + Central M2/M4 Bridges at y = +-4.35, +-5.20, +6.05 um (0.85 um pitch):
    ctrl_specs = [
        # (name, ty_orig, x_center_shared_m3, y_central_bridge)
        ("b0", 1.40, -1.40, +6.05),
        ("b1", 2.10, -0.70, +5.20),
        ("b2", 2.80,  0.00, +4.35),
        ("b3", 3.50, +0.70, -4.35),
        ("b4", 4.20, +1.40, -5.20),
    ]
    x_shared_map = {name: x_c for name, _, x_c, _ in ctrl_specs}

    # Butt-join Left Inner and Right Inner Half-Tanks across [-1.95, +1.95] on M2 rungs and drop 1 via2 per rung:
    for qy, sy in ((+DY, +1), (-DY, -1)):
        for cname, gx in rungs:
            y_row = grid(qy + sy * gx)
            x_c = x_shared_map[cname]
            c.wire("metal2", [(-1.95, y_row), (+1.95, y_row)], 0.30)
            c.via2(x_c, y_row)

    # Run the 3 vertical 5-track M3 control columns symmetrically in [-34.80, +34.80] um and bridge them
    # across the center at y_bus (M2 under b4_bot MIMs + M4 over Left/Right Cores!):
    ctrl_ports = {}
    y_ctrl_span = grid(+DY + max(gx for _, gx in rungs))  # 35.50 um
    x_m4_in = 16.00
    x_m4_out = 32.30
    for cname, ty_orig, x_c, y_bus in ctrl_specs:
        x_left_out = grid(-DX - tank_cx - ty_orig)
        x_right_out = grid(+DX + tank_cx + ty_orig)
        for x_col in (x_left_out, x_c, x_right_out):
            c.wire("metal3", [(x_col, -y_ctrl_span), (x_col, +y_ctrl_span)], 0.36)
            c.via2(x_col, y_bus)
        # Central horizontal bridge: M2 under MIMs + M4 across Cores!
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

    # 3B. Varactor Control (vctrl) on M4 + M3 inside the Core window (bridged at y = -6.05 um, symmetric to b0):
    # Each varactor's M4 vctrl pin is at (x_stage = +-9.34, y_stage = -2.00) -> y_ring = +-17.35 um.
    y_var_top = grid(+DY - 2.00)  # +17.35 um
    y_var_bot = grid(-DY + 2.00)  # -17.35 um
    y_vc_bus = -6.05
    x_vc_cols = []
    for qx in (-DX, +DX):
        x_vp = grid(qx - 9.34)
        x_vn = grid(qx + 9.34)
        x_vc = grid(qx + 2.40)
        x_vc_cols.append(x_vc)
        for yv in (y_var_top, y_var_bot):
            c.wire("metal4", [(x_vp, yv), (x_vn, yv)], 0.40)
            via3(c, x_vc, yv)
        c.wire("metal3", [(x_vc, y_var_bot), (x_vc, y_var_top)], 0.36)
        via3(c, x_vc, y_vc_bus)
    # Connect Left Core vctrl (x_vc_cols[0] = -21.75) and Right Core vctrl (x_vc_cols[1] = +26.55) at y = -5.85 um:
    c.wire("metal4", [(x_vc_cols[0], y_vc_bus), (-x_m4_in, y_vc_bus)], 0.36)
    via2_3(c, -x_m4_in, y_vc_bus)
    c.wire("metal2", [(-x_m4_in, y_vc_bus), (+x_m4_in, y_vc_bus)], 0.30)
    via2_3(c, +x_m4_in, y_vc_bus)
    c.wire("metal4", [(+x_m4_in, y_vc_bus), (x_vc_cols[1], y_vc_bus)], 0.36)
    ctrl_ports["vctrl"] = (+DX, y_vc_bus)

    # 3C. Symmetric Tail Bias (vbias) on M1 + M4 along y = 0.00 um:
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

    # Export exact 17-port order matching `vco_ring4_r6.spice`:
    #   q0p q0n q1p q1n q2p q2n q3p q3n vctrl b0 b1 b2 b3 b4 vbias vdd vss
    c.labels = []
    for qid in ("0", "1", "2", "3"):
        c.port(f"q{qid}p", "metal4", *q_ports[f"q{qid}p"])
        c.port(f"q{qid}n", "metal4", *q_ports[f"q{qid}n"])
    c.port("vctrl", "metal4", *ctrl_ports["vctrl"])
    for bit in range(5):
        c.port(f"b{bit}", "metal4", *ctrl_ports[f"b{bit}"])
    c.port("vbias", "metal4", x_bias_cols[0], 0.00)
    c.port("vdd", "metal4", 0.00, Y_VDD_TOP)
    c.port("vss", "metal4", 0.00, Y_VSS_PORT)
    c.write(rdir / f"{cell_name}.mag")

    # Build reference SPICE netlist for LVS verification
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
    ring_ref = "\n".join([
        tank_ref,
        delay_ref,
        f".subckt {cell_name} q0p q0n q1p q1n q2p q2n q3p q3n vctrl b0 b1 b2 b3 b4 vbias vdd vss",
        "X0 q3n q3p q0p q0n vbias vdd vss pll_vco_delay_sym9_c",
        "X1 q0p q0n q1p q1n vbias vdd vss pll_vco_delay_sym9_c",
        "X2 q1p q1n q2p q2n vbias vdd vss pll_vco_delay_sym9_c",
        "X3 q2p q2n q3p q3n vbias vdd vss pll_vco_delay_sym9_c",
        f"Xtank0p q0p vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank0n q0n vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank1p q1p vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank1n q1n vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank2p q2p vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank2n q2n vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank3p q3p vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f"Xtank3n q3n vctrl b0 b1 b2 b3 b4 vss {tank_name}",
        f".ends {cell_name}\n",
    ])
    ref_path = rdir / "reference.spice"
    ref_path.write_text(ring_ref)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "verification/layout/check.py"), str(rdir), cell_name, "--ref", str(ref_path)],
        capture_output=True,
        text=True,
    )
    log = proc.stdout + proc.stderr
    (rdir / "check.log").write_text(log)
    print(log, flush=True)
    if proc.returncode:
        raise RuntimeError(f"Ring4 check failed: {rdir / 'check.log'}")

    # Extract per-phase parasitic capacitances from _pex.spice
    pex_text = (rdir / f"{cell_name}_pex.spice").read_text()
    lvs_text = (rdir / f"{cell_name}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_text, re.M)))
    mim_plates = set(re.findall(r"^X\S+\s+q[0-3][pn]\s+(\S+)\s+sky130_fd_pr__cap_mim_m3_1\b", lvs_text, re.M))
    caps = [
        (a, b, spice_number(v) * 1e15)
        for a, b, v in re.findall(r"^C\S+\s+(\S+)\s+(\S+)\s+(\S+)$", pex_text, re.M)
    ]
    phase_direct_fF = {}
    for qn in ("q0p", "q0n", "q1p", "q1n", "q2p", "q2n", "q3p", "q3n"):
        tot = sum(
            v for a, b, v in caps
            if qn in (a, b) and (b if a == qn else a) not in mim_plates
        )
        phase_direct_fF[qn] = round(tot, 4)

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
        floating_bit_plates=len(mim_plates),
        phase_non_plate_cap_fF=phase_direct_fF,
    )
    (rdir / "summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--variant", default="s32p5")
    args = ap.parse_args()

    out = args.output_dir or (
        ROOT / "results/layout/pll_vco" / ("vco_ring4_sym9_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    meta = build_vco_ring4(out, args.variant)
    (out / "summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    print("COMPLETE SUMMARY:", json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
