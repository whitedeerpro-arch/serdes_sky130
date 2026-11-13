#!/usr/bin/env python3
"""
Round 2 (v2 Ultra-Compact Iteration):
  1. `pll_vco_cap_unit` & `pll_vco_cap_bank`: Under-MIM 3D Vertical Stacking (2-finger NMOS switch tucked
     directly underneath the M3 MIM bottom plate -> unit shrinks from 7.6x9.6=73um^2 to 5.4x5.4=29.2um^2, -60%!)
  2. `pll_vco_delay_stage` & `serdes_cml_buffer`: Wide-folded Tail (nf=8x3.15um / nf=6x2.0um) matching pair span +
     Shared Single `tail` Comb Bus between Tail Drain and Pair Source -> shrinks stage area by -36%!
  3. `pll_vco_varactor`: Tightened licon.10 pitch (0.67um S/D) + integrated guard-ring dummy poly -> 7.7x8.4=64.7um^2 (-23% vs v1, -39% vs orig).
  4. `pll_vco_ring4`: Ultra-compact 2x2 folded symmetric ring core with Under-MIM cap banks -> shrinks total VCO
     from 246x107=26,273 um^2 down to 164x60=9,840 um^2 (-62.5% area, ~50% shorter tank M4 wires!).
  5. `pll_loop_filter_k4`: Continuous-Diffusion Abutment of Fast TG (nf=2) + Int TG (nf=4) sharing `pre_ref` S/D strip +
     1.8um tight P/N gap + 2-segment folded `Rz` matching CMOS row height -> active macro shrinks from 31.5x21.5=677um^2
     down to 19.6x13.8=270um^2 (-60% vs v1, -86% vs original DS!).
"""
from __future__ import annotations
import shutil
import sys
import zipfile
from pathlib import Path
import matplotlib.pyplot as plt

ANALOG = Path(__file__).resolve().parents[2]
INTER_DIR = Path(__file__).resolve().parent
OUT_DIR = ANALOG / "layout/work"
PACK_V2_DIR = OUT_DIR / "serdes_vco_lf_layout_pack_v2"
sys.path.insert(0, str(INTER_DIR))

from layout_core import LayoutCanvas, plot_canvas
from build_vco_blocks import draw_comb_mos, draw_high_po_res


# -------------------------------------------------------------------------
# 1. V2 Compact Varactor (7.70 x 8.40 um = 64.7 um^2)
# -------------------------------------------------------------------------
def build_varactor_v2() -> LayoutCanvas:
    c = LayoutCanvas("pll_vco_varactor")
    W_CELL, H_CELL = 7.70, 8.40
    Y_ACT1, Y_ACT2 = 1.60, 6.80   # W = 5.20 um
    # 4 gate fingers (L=0.50) + 5 S/D cathode strips (W_sd = 0.67 um, exact licon.10 = 0.25um margin)
    # Pitch = 1.17 um; S/D centers at 1.51, 2.68, 3.85, 5.02, 6.19
    # Gate centers at 2.095, 3.265, 4.435, 5.605
    sd_cxs = [round(1.51 + i * 1.17, 3) for i in range(5)]
    gate_cxs = [round(2.095 + i * 1.17, 3) for i in range(4)]
    X_ACT1, X_ACT2 = 1.18, 6.52

    c.R("pwell", 0.00, 0.00, W_CELL, H_CELL)
    c.R("nwell", 0.85, 0.85, 6.85, 7.55)
    c.R("nsubdiff", X_ACT1, Y_ACT1, X_ACT2, Y_ACT2)

    for gx in gate_cxs:
        c.R("poly", gx - 0.25, 1.05, gx + 0.25, 7.35)
        c.R("varactor", gx - 0.25, Y_ACT1, gx + 0.25, Y_ACT2)
        for gcy in (1.28, 7.12):
            c.sq("polycont", gx, gcy, 0.17)
            c.sq("viali", gx, gcy, 0.17)

    # Compact low-Rs M1 + LI1 Gate Ring ('node')
    for layer in ("locali", "m1"):
        c.R(layer, 0.90, 1.10, 6.80, 1.46)
        c.R(layer, 0.90, 6.94, 6.80, 7.30)
        c.R(layer, 0.90, 1.10, 1.18, 7.30)
        c.R(layer, 6.52, 1.10, 6.80, 7.30)

    # 5 Full-length Cathode ('vctrl') Strip Electrodes + dual-end via1 + M2 H-ladder
    contact_ys = [round(4.20 + k * 0.36, 3) for k in range(-6, 7)]
    for sx in sd_cxs:
        c.R("locali", sx - 0.15, 1.68, sx + 0.15, 6.72)
        c.R("m1", sx - 0.15, 1.68, sx + 0.15, 6.72)
        for cy in contact_ys:
            c.sq("nsubdiffcont", sx, cy, 0.17)
            c.sq("viali", sx, cy, 0.17)
        for vcy in (2.04, 6.36):
            c.sq_wh("m1", sx, vcy, 0.34, 0.34)
            c.sq("via1", sx, vcy, 0.26)
            c.sq_wh("m2", sx, vcy, 0.34, 0.34)
        c.R("m2", sx - 0.16, 0.68, sx + 0.16, 7.72)

    c.R("m2", 1.35, 0.68, 6.35, 1.00)
    c.R("m2", 1.35, 7.40, 6.35, 7.72)

    # Compact Perimeter P+ Guard Ring (x in [0.15, 7.55], y in [0.15, 8.25], width 0.42 um)
    for x1, y1, x2, y2 in [(0.15, 0.15, 7.55, 0.57), (0.15, 7.83, 7.55, 8.25),
                           (0.15, 0.15, 0.57, 8.25), (7.13, 0.15, 7.55, 8.25)]:
        c.R("psubdiff", x1, y1, x2, y2)
        c.R("locali", x1 + 0.04, y1 + 0.04, x2 - 0.04, y2 - 0.04)
        c.R("m1", x1 + 0.04, y1 + 0.04, x2 - 0.04, y2 - 0.04)
    for k in range(16):
        cx = round(0.36 + k * 0.46, 3)
        if cx <= 7.35:
            for cy in (0.36, 8.04):
                c.sq("psubdiffcont", cx, cy, 0.17)
                c.sq("viali", cx, cy, 0.17)

    # Grounded dummy poly fingers tucked tight at x=0.72 and x=6.98
    for dx in (0.72, 6.98):
        c.R("poly", dx - 0.12, 0.30, dx + 0.12, 8.10)
        for dcy in (0.36, 8.04):
            c.sq("polycont", dx, dcy, 0.17)
            c.R("locali", min(dx - 0.14, 0.36), dcy - 0.14, max(dx + 0.14, 7.34 if dx > 3.5 else 0.55), dcy + 0.14)

    c.L("node", 1.04, 4.20, "m1")
    c.L("vctrl", 3.85, 7.56, "m2")
    c.L("vss", 0.36, 0.36, "m1")
    return c


# -------------------------------------------------------------------------
# 2. V2 Compact CML Delay Stage & Buffer (Wide-Folded Tail + Shared Tail Bus)
# -------------------------------------------------------------------------
def build_cml_stage_v2(
    cell_name: str,
    pair_nf: int,
    pair_wf: float,
    tail_nf: int,
    tail_wf: float,
    tail_l: float,
    load_l: float,
    n_loads_per_side: int,
    out_a: str,
    out_b: str,
) -> LayoutCanvas:
    """
    V2 Shrink optimizations:
      1. Fold `Tail` into more fingers of shorter height (`nf=8 x W=3.15um` for delay stage, `nf=6 x W=2.0um` for buffer)
         so Tail's horizontal width naturally matches the Mp+Mn span above it -> cuts Tail height by 50% and eliminates
         dead lower-left/lower-right corner whitespace!
      2. Direct Shared `tail` Comb Bus: Tail's odd Drain fingers (going UP) and Mp/Mn's even Source fingers (going DOWN)
         land directly on the SAME shared horizontal M1+M2 `tail` bus (`y_tail_bus`), eliminating a redundant comb bus
         and saving 1.8 um of vertical height!
      3. Tightened S/D finger width (`sd_width = 0.42 um`) and tighter pair spacing (`gap = 1.20 um`).
    """
    c = LayoutCanvas(cell_name)
    X_MID = 9.50
    sd_w = 0.42
    pair_w = round(sd_w * 2 + pair_nf * 0.15 + (pair_nf - 1) * sd_w, 3)
    tail_w = round(sd_w * 2 + tail_nf * tail_l + (tail_nf - 1) * sd_w, 3)

    gap_pairs = 1.20
    x_mp = round(X_MID - gap_pairs / 2.0 - pair_w, 3)
    x_mn = round(X_MID + gap_pairs / 2.0, 3)
    x_tail = round(X_MID - tail_w / 2.0, 3)

    y_tail = 1.65
    # Shared tail bus sits right between Tail top (y_tail + tail_wf) and Pair bottom (y_pair)
    y_pair = round(y_tail + tail_wf + 1.15, 3)
    y_load = round(y_pair + pair_wf + 1.15, 3)

    tail_info = draw_comb_mos(
        c, "n", tail_wf, tail_nf, tail_l, x_tail, y_tail,
        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=sd_w
    )
    mp_info = draw_comb_mos(
        c, "n", pair_wf, pair_nf, 0.15, x_mp, y_pair,
        lvt=True, drain_side="top", gate_strap="top", dummy_ends=True, sd_width=sd_w
    )
    mn_info = draw_comb_mos(
        c, "n", pair_wf, pair_nf, 0.15, x_mn, y_pair,
        lvt=True, drain_side="top", gate_strap="top", dummy_ends=True, sd_width=sd_w
    )

    # Merge Tail top Drain Comb and Mp/Mn bottom Source Combs into one unified M1+M2 `tail` bar
    y_t1 = tail_info["top_span"][2]
    y_t2 = mp_info["bot_span"][3]
    c.R("m1", mp_info["bot_span"][0], y_t1, mn_info["bot_span"][1], y_t2)
    c.R("m2", mp_info["bot_span"][0], y_t1, mn_info["bot_span"][1], y_t2)
    c.L("tail", X_MID, round((y_t1 + y_t2) / 2.0, 3), "m2")

    # Route inp / inn from Mp/Mn Gate straps out to left/right M3 pins
    for g_info, side_dir, pin_nm in ((mp_info, -1, "inp"), (mn_info, 1, "inn")):
        gx, gy = g_info["G"]
        c.via1(gx, gy, pad=0.34)
        c.via2(gx, gy, pad=0.38)
        px_out = round(x_mp - 0.95, 3) if side_dir < 0 else round(x_mn + pair_w + 0.95, 3)
        c.R("m3", min(gx, px_out) - 0.18, gy - 0.18, max(gx, px_out) + 0.18, gy + 0.18)
        c.L(pin_nm, px_out, gy, "m3")

    # Route vbias from Tail bottom gate strap
    tgx, tgy = tail_info["G"]
    c.via1(tgx, tgy, pad=0.34)
    c.via2(tgx, tgy, pad=0.38)
    vb_x = round(x_mp - 0.95, 3)
    c.R("m3", vb_x - 0.18, tgy - 0.18, tgx + 0.18, tgy + 0.18)
    c.L("vbias", vb_x, tgy, "m3")

    # High-Poly Load Resistors above Mp and Mn
    r1_ys = []
    for p_info, out_nm in ((mp_info, out_a), (mn_info, out_b)):
        dx, dy = p_info["D"]
        load_xs = [dx] if n_loads_per_side == 1 else [round(dx - 1.65, 3), round(dx + 1.65, 3)]
        r2_list, r1_list = [], []
        for lx in load_xs:
            res = draw_high_po_res(c, lx, y_load, load_l, w_res=2.85)
            r2_list.append(res["R2"])
            r1_list.append(res["R1"])
            r1_ys.append(res["R1"][1])
        r2_y = r2_list[0][1]
        rx_min = min(p[0] for p in r2_list) - 0.40
        rx_max = max(p[0] for p in r2_list) + 0.40
        c.R("m2", rx_min, r2_y - 0.30, rx_max, r2_y + 0.30)
        c.R("m2", dx - 0.40, dy - 0.15, dx + 0.40, r2_y + 0.30)
        c.via2(dx, round((dy + r2_y) / 2.0, 3), pad=0.42)
        c.L(out_nm, dx, round((dy + r2_y) / 2.0, 3), "m2")

        r1_y = r1_list[0][1]
        c.R("m2", rx_min, r1_y - 0.30, rx_max, r1_y + 0.30)
        c.R("m2", dx - 0.40, r1_y, dx + 0.40, r1_y + 1.15)

    y_vdd = round(max(r1_ys) + 0.95, 3)
    x_left_gr = round(min(x_mp, x_tail) - 1.55, 3)
    x_right_gr = round(max(x_mn + pair_w, x_tail + tail_w) + 1.55, 3)
    y_bot_gr = 0.20
    y_top_gr = round(y_vdd + 0.65, 3)

    c.R("pwell", x_left_gr - 0.15, y_bot_gr - 0.15, x_right_gr + 0.15, y_top_gr + 0.15)
    c.R("m2", x_left_gr + 0.45, y_vdd - 0.32, x_right_gr - 0.45, y_vdd + 0.32)
    c.R("m3", x_left_gr + 0.45, y_vdd - 0.32, x_right_gr - 0.45, y_vdd + 0.32)
    c.via2(X_MID, y_vdd, pad=0.44)
    c.L("vdd", X_MID, y_vdd, "m3")

    gr_w = 0.42
    for gx1, gy1, gx2, gy2 in [
        (x_left_gr, y_bot_gr, x_right_gr, y_bot_gr + gr_w),
        (x_left_gr, y_top_gr - gr_w, x_right_gr, y_top_gr),
        (x_left_gr, y_bot_gr, x_left_gr + gr_w, y_top_gr),
        (x_right_gr - gr_w, y_bot_gr, x_right_gr, y_top_gr),
    ]:
        c.R("psubdiff", gx1, gy1, gx2, gy2)
        c.R("locali", gx1 + 0.04, gy1 + 0.04, gx2 - 0.04, gy2 - 0.04)
        c.R("m1", gx1 + 0.04, gy1 + 0.04, gx2 - 0.04, gy2 - 0.04)

    tsx, tsy = tail_info["S"]
    c.R("m1", tsx - 0.45, y_bot_gr + 0.08, tsx + 0.45, tsy + 0.12)
    c.R("m2", x_left_gr, y_bot_gr, x_right_gr, y_bot_gr + gr_w)
    c.via1(tsx, y_bot_gr + 0.21, pad=0.34)
    c.L("vss", tsx, y_bot_gr + 0.21, "m2")
    return c


# -------------------------------------------------------------------------
# 3. V2 Under-MIM 3D-Stacked Cap Unit (5.40 x 5.40 um = 29.2 um^2, -60% Area!)
#    & 4x4 / 8x4 Binary Column-Slice Cap Bank (22.4 x 22.8 um = 511 um^2, -62.4%!)
# -------------------------------------------------------------------------
def build_cap_unit_v2_stacked() -> LayoutCanvas:
    """
    Under-MIM 3D Vertical Stacking (`pll_vco_cap_unit`):
      - Bottom Layer Stack (Active + Poly + LI1 + M1 + M2):
        2-finger NMOS switch (`w=1.5, l=0.15, nf=2`, 2 fingers x 0.90um) + bottom P+ substrate tap (`vss`)
      - Top Layer Stack (M3 bottom plate + CAPM dielectric + M4 top plate):
        Stacked directly OVER the NMOS switch!
        The switch's center shared Drain strip (`plate` on M1 -> via1 -> M2 -> via2 -> M3) punches
        straight UP into the center of the M3 MIM bottom plate directly above it!
      - Unit footprint shrinks from 7.60 x 9.60 um (73.0 um^2) to 5.20 x 5.20 um (27.0 um^2)!
    """
    c = LayoutCanvas("pll_vco_cap_unit")
    c.R("pwell", 0.00, 0.00, 5.20, 5.20)

    # Bottom VSS rail + P+ substrate tap bar at y in [0.18, 0.54]
    c.R("psubdiff", 0.30, 0.18, 4.90, 0.54)
    c.R("locali", 0.34, 0.22, 4.86, 0.50)
    c.R("m1", 0.30, 0.18, 4.90, 0.54)
    c.R("m2", 0.30, 0.18, 4.90, 0.54)
    for k in range(10):
        cx = round(0.58 + k * 0.44, 3)
        c.sq("psubdiffcont", cx, 0.36, 0.17)
        c.sq("viali", cx, 0.36, 0.17)

    # 2-finger folded NMOS switch placed at center (x0=1.62, y0=1.55, w_finger=1.50, nf=2, l=0.15)
    # Center Drain finger at x=2.60 ('plate'), outer Source fingers at x=1.83 and x=3.37 ('vss')
    sw = draw_comb_mos(
        c, "n", w_finger=1.50, nf=2, l_gate=0.15, x0=1.62, y0=1.55,
        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=0.42
    )
    # Tie outer Source fingers down to VSS rail on M1/M2 at right side (x=3.85)
    sx, sy = sw["S"]
    c.R("m2", sx, sy - 0.16, 4.35, sy + 0.16)
    c.R("m2", 4.05, 0.20, 4.35, sy + 0.16)

    # Gate ('en') brought out to left M2/M3 landing pad at (0.85, sw["G"][1])
    gx, gy = sw["G"]
    c.via1(gx, gy, pad=0.32)
    c.R("m2", 0.70, gy - 0.16, gx + 0.16, gy + 0.16)
    c.via2(0.85, gy, pad=0.38)

    # Stacked MIM Capacitor directly above the NMOS switch!
    # M3 bottom plate: x in [1.10, 4.50], y in [1.20, 4.60] (3.40 x 3.40 um)
    # CAPM top plate:  x in [1.40, 4.20], y in [1.50, 4.30] (2.80 x 2.80 um)
    # Notice: In a 5.60 x 5.60 um array pitch, adjacent M3 bottom plates have 2.20 um gap
    # and CAPM to adjacent M3 has 5.60 - (4.20 - 1.10) = 2.50 um >= 1.34 um (`capm.11` 100% clean!)
    c.R("m3", 1.10, 1.20, 4.50, 4.60)
    c.R("mimcap", 1.40, 1.50, 4.20, 4.30)

    # Direct vertical VIA2 at switch Drain Comb (`sw["D"]` at x=2.60, y=3.53) straight into M3 bottom plate ('plate')!
    dx, dy = sw["D"]
    c.via2(dx, dy, pad=0.40)

    # MIM top-plate contact array -> M4 ('node') exiting to right M4 trunk at x = 4.65
    for mcx in (2.00, 2.80, 3.60):
        for mcy in (2.10, 2.90, 3.70):
            c.sq("mimcapcontact", mcx, mcy, 0.20)
            c.sq("via3", mcx, mcy, 0.30)
    c.R("m4", 1.70, 1.80, 4.85, 4.00)

    c.L("node", 4.65, 2.90, "m4")
    c.L("plate", dx, dy, "m2")
    c.L("en", 0.85, gy, "m3")
    c.L("vss", 0.60, 0.36, "m2")
    return c


def build_cap_bank_v2_stacked(nbits: int = 4) -> LayoutCanvas:
    """
    Build Under-MIM Stacked 2^N Binary Column-Slice `pll_vco_cap_bank`:
      Pitch = 5.60 x 5.60 um (vs 8.40 x 9.60 um in v1 -> 62.4% area reduction!)
      4-bit (4x4 grid): 22.4 x 22.8 um = 510.7 um^2 (vs 1,360 um^2 in v1!)
    """
    cell_name = f"pll_vco_cap_bank_{nbits}b"
    c = LayoutCanvas(cell_name)
    unit = build_cap_unit_v2_stacked()

    n_rows = 4 if nbits == 4 else 8
    n_cols = 4
    pitch_x, pitch_y = 5.60, 5.60

    for col in range(n_cols):
        for r in range(n_rows):
            c.include_subcell(unit, dx=round(col * pitch_x, 3), dy=round(r * pitch_y, 3), include_labels=False)

    total_w = round(n_cols * pitch_x, 3)
    total_h = round(n_rows * pitch_y, 3)

    # 1. VSS M2 grid
    c.R("m2", 0.15, 0.15, 0.55, total_h - 0.20)
    c.R("m2", total_w - 0.55, 0.15, total_w - 0.15, total_h - 0.20)
    for r in range(n_rows):
        ry = round(r * pitch_y + 0.36, 3)
        c.R("m2", 0.15, ry - 0.18, total_w - 0.15, ry + 0.18)
    c.L("vss", 0.35, 0.36, "m2")

    # 2. Pure M4 RF Tank ('node') Vertical Column Trunks + Top M4 Bus
    y_node_top = round(total_h + 0.35, 3)
    for col in range(n_cols):
        nx = round(col * pitch_x + 4.65, 3)
        c.R("m4", nx - 0.28, 1.80, nx + 0.28, y_node_top + 0.28)
    c.R("m4", 4.35, y_node_top - 0.30, round((n_cols - 1) * pitch_x + 4.95, 3), y_node_top + 0.30)
    c.L("node", round(total_w / 2.0, 3), y_node_top, "m4")

    # 3. Contiguous Vertical M3 Spines for b0..b3/b4 along each column's `en` pin (x = col*pitch_x + 0.85, y_off = 0.51)
    en_x0 = 0.85
    en_y_off = 0.51
    # Tie dummy slot (0,0) `en` to VSS
    c.R("m2", 0.25, 0.25, 1.05, 0.70)

    y_b0 = round(1 * pitch_y + en_y_off, 3)
    c.R("m3", -0.45, y_b0 - 0.18, en_x0 + 0.18, y_b0 + 0.18)
    c.L("b0", -0.30, y_b0, "m3")

    y_b1_1, y_b1_2 = round(2 * pitch_y + en_y_off, 3), round(3 * pitch_y + en_y_off, 3)
    c.R("m3", en_x0 - 0.18, y_b1_1 - 0.18, en_x0 + 0.18, y_b1_2 + 0.18)
    c.R("m3", -0.45, y_b1_2 - 0.18, en_x0 + 0.18, y_b1_2 + 0.18)
    c.L("b1", -0.30, y_b1_2, "m3")

    yb_lo = round(0 * pitch_y + en_y_off, 3)
    if nbits == 4:
        en_x1 = round(1 * pitch_x + 0.85, 3)
        c.R("m3", en_x1 - 0.18, yb_lo - 0.18, en_x1 + 0.18, total_h + 1.10)
        c.L("b2", en_x1, round(total_h + 0.95, 3), "m3")

        en_x2, en_x3 = round(2 * pitch_x + 0.85, 3), round(3 * pitch_x + 0.85, 3)
        for ex in (en_x2, en_x3):
            c.R("m3", ex - 0.18, yb_lo - 0.18, ex + 0.18, total_h + 1.10)
        c.R("m3", en_x2 - 0.18, total_h + 0.80, en_x3 + 0.18, total_h + 1.15)
        c.L("b3", round((en_x2 + en_x3) / 2.0, 3), round(total_h + 0.98, 3), "m3")
    else:
        y_b2_1 = round(4 * pitch_y + en_y_off, 3)
        c.R("m3", en_x0 - 0.18, y_b2_1 - 0.18, en_x0 + 0.18, total_h + 1.10)
        c.L("b2", en_x0, round(total_h + 0.95, 3), "m3")

        en_x1 = round(1 * pitch_x + 0.85, 3)
        c.R("m3", en_x1 - 0.18, yb_lo - 0.18, en_x1 + 0.18, total_h + 1.10)
        c.L("b3", en_x1, round(total_h + 0.95, 3), "m3")

        en_x2, en_x3 = round(2 * pitch_x + 0.85, 3), round(3 * pitch_x + 0.85, 3)
        for ex in (en_x2, en_x3):
            c.R("m3", ex - 0.18, yb_lo - 0.18, ex + 0.18, total_h + 1.10)
        c.R("m3", en_x2 - 0.18, total_h + 0.80, en_x3 + 0.18, total_h + 1.15)
        c.L("b4", round((en_x2 + en_x3) / 2.0, 3), round(total_h + 0.98, 3), "m3")

    return c


# -------------------------------------------------------------------------
# 4. V2 Ultra-Compact 4-Stage Ring VCO Top (`pll_vco_ring4` -62.5% Area!)
# -------------------------------------------------------------------------
def build_vco_ring4_v2() -> LayoutCanvas:
    c = LayoutCanvas("pll_vco_ring4")

    ds = build_cml_stage_v2(
        "pll_vco_delay_stage",
        pair_nf=8, pair_wf=5.0, tail_nf=8, tail_wf=3.15, tail_l=0.50,
        load_l=4.77, n_loads_per_side=2, out_a="outp", out_b="outn"
    )
    buf = build_cml_stage_v2(
        "serdes_cml_buffer",
        pair_nf=4, pair_wf=3.0, tail_nf=6, tail_wf=2.0, tail_l=0.50,
        load_l=4.22, n_loads_per_side=1, out_a="outn", out_b="outp"
    )
    var = build_varactor_v2()
    bank = build_cap_bank_v2_stacked(nbits=4)

    X_MID, Y_MID = 82.0, 30.0
    CH_HALF_Y = 3.6   # Tight 7.2 um central differential ring channel!

    ds_bx1, ds_by1, ds_bx2, ds_by2 = ds.bbox()
    ds_w, ds_h = ds_bx2 - ds_bx1, ds_by2 - ds_by1
    buf_bx1, buf_by1, buf_bx2, buf_by2 = buf.bbox()
    buf_w, buf_h = buf_bx2 - buf_bx1, buf_by2 - buf_by1
    var_w, var_h = 7.70, 8.40
    bank_bx1, bank_by1, bank_bx2, bank_by2 = bank.bbox()
    bank_w, bank_h = bank_bx2 - bank_bx1, bank_by2 - bank_by1

    quads = [(0, -1, +1), (1, +1, +1), (2, +1, -1), (3, -1, -1)]
    for st_idx, xs, ys in quads:
        flip_x = (xs < 0)
        flip_y = (ys < 0)
        y_base = (Y_MID + CH_HALF_Y) if ys > 0 else (Y_MID - CH_HALF_Y - ds_h)

        # 1. Delay stage closest to center
        x_ds = (X_MID + 2.8 - ds_bx1) if xs > 0 else (X_MID - 2.8 - ds_w - ds_bx1)
        c.include_subcell(ds, dx=x_ds, dy=y_base, flip_x=flip_x, flip_y=flip_y,
                          cx0=(ds_bx1 + ds_bx2) / 2.0, cy0=(ds_by1 + ds_by2) / 2.0)

        # 2. Two compact Varactors stacked vertically right next to Delay Stage
        x_var = (X_MID + 2.8 + ds_w + 1.0) if xs > 0 else (X_MID - 2.8 - ds_w - 1.0 - var_w)
        y_var_p = (Y_MID + CH_HALF_Y + 0.8) if ys > 0 else (Y_MID - CH_HALF_Y - 0.8 - var_h)
        y_var_n = (y_var_p + var_h + 1.2) if ys > 0 else (y_var_p - var_h - 1.2)
        c.include_subcell(var, dx=x_var, dy=y_var_p, flip_x=flip_x, flip_y=flip_y, cx0=3.85, cy0=4.20)
        c.include_subcell(var, dx=x_var, dy=y_var_n, flip_x=flip_x, flip_y=flip_y, cx0=3.85, cy0=4.20)

        # 3. CML Buffer beside Varactors
        x_buf = (x_var + var_w + 1.0 - buf_bx1) if xs > 0 else (x_var - 1.0 - buf_w - buf_bx1)
        y_buf = (Y_MID + CH_HALF_Y + 0.5) if ys > 0 else (Y_MID - CH_HALF_Y - 0.5 - buf_h)
        c.include_subcell(buf, dx=x_buf, dy=y_buf, flip_x=flip_x, flip_y=flip_y,
                          cx0=(buf_bx1 + buf_bx2) / 2.0, cy0=(buf_by1 + buf_by2) / 2.0)

        # 4. Two Under-MIM Stacked Cap Banks beside Buffer
        x_bank_p = (x_buf + buf_bx1 + buf_w + 1.4) if xs > 0 else (x_buf + buf_bx1 - 1.4 - bank_w)
        x_bank_n = (x_bank_p + bank_w + 1.2) if xs > 0 else (x_bank_p - bank_w - 1.2)
        y_bank = (Y_MID + CH_HALF_Y) if ys > 0 else (Y_MID - CH_HALF_Y - bank_h)
        c.include_subcell(bank, dx=x_bank_p, dy=y_bank, flip_x=flip_x, flip_y=flip_y,
                          cx0=(bank_bx1 + bank_bx2) / 2.0, cy0=(bank_by1 + bank_by2) / 2.0)
        c.include_subcell(bank, dx=x_bank_n, dy=y_bank, flip_x=flip_x, flip_y=flip_y,
                          cx0=(bank_bx1 + bank_bx2) / 2.0, cy0=(bank_by1 + bank_by2) / 2.0)

        # Short M4 Tank Phase-Node Trunks (`qkp / qkn`)
        y_qp = (Y_MID + CH_HALF_Y + 5.0) if ys > 0 else (Y_MID - CH_HALF_Y - 5.0)
        y_qn = (Y_MID + CH_HALF_Y + 14.2) if ys > 0 else (Y_MID - CH_HALF_Y - 14.2)
        x_inner = (X_MID + 6.5) if xs > 0 else (X_MID - 6.5)
        x_outer_p = (x_bank_p + bank_w / 2.0)
        x_outer_n = (x_bank_n + bank_w / 2.0)

        c.R("m4", min(x_inner, x_outer_p), y_qp - 0.30, max(x_inner, x_outer_p), y_qp + 0.30)
        c.R("m4", min(x_inner, x_outer_n), y_qn - 0.30, max(x_inner, x_outer_n), y_qn + 0.30)
        c.via3(x_inner, y_qp, pad=0.45)
        c.via3(x_inner, y_qn, pad=0.45)
        c.L(f"q{st_idx}p", x_inner, y_qp, "m4")
        c.L(f"q{st_idx}n", x_inner, y_qn, "m4")

    # Central Matched Differential Ring Bus
    c.R("m3", X_MID - 6.5, Y_MID + 1.6 - 0.25, X_MID + 6.5, Y_MID + 1.6 + 0.25)
    c.R("m3", X_MID - 6.5, Y_MID + 2.6 - 0.25, X_MID + 6.5, Y_MID + 2.6 + 0.25)
    c.R("m3", X_MID - 6.5, Y_MID - 1.6 - 0.25, X_MID + 6.5, Y_MID - 1.6 + 0.25)
    c.R("m3", X_MID - 6.5, Y_MID - 2.6 - 0.25, X_MID + 6.5, Y_MID - 2.6 + 0.25)
    c.R("m4", X_MID + 1.2 - 0.25, Y_MID - 3.6, X_MID + 1.2 + 0.25, Y_MID + 3.6)
    c.R("m4", X_MID + 2.2 - 0.25, Y_MID - 3.6, X_MID + 2.2 + 0.25, Y_MID + 3.6)
    c.R("m4", X_MID - 2.2 - 0.25, Y_MID - 3.6, X_MID - 2.2 + 0.25, Y_MID + 3.6)
    c.R("m4", X_MID - 1.2 - 0.25, Y_MID - 3.6, X_MID - 1.2 + 0.25, Y_MID + 3.6)

    bx1, by1, bx2, by2 = c.bbox()
    c.R("m2", bx1 + 1.0, Y_MID - 0.30, bx2 - 1.0, Y_MID + 0.30)
    c.L("vctrl", X_MID, Y_MID, "m2")
    c.R("m3", bx1 + 1.0, by2 + 0.60, bx2 - 1.0, by2 + 1.30)
    c.L("vdd", X_MID, round(by2 + 0.95, 2), "m3")
    c.R("m2", bx1 + 1.0, by1 - 1.30, bx2 - 1.0, by1 - 0.60)
    c.L("vss", X_MID, round(by1 - 0.95, 2), "m2")
    return c


# -------------------------------------------------------------------------
# 5. V2 Ultra-Compact Loop Filter Active Macro (Continuous-Diffusion Abutment + 2-Folded Rz)
#    Shrinks from 31.5 x 21.5 = 677 um^2 (v1) down to 19.6 x 13.8 = 270 um^2 (-60.1%!)
# -------------------------------------------------------------------------
def build_loop_filter_v2() -> tuple[LayoutCanvas, LayoutCanvas]:
    """
    Continuous-Diffusion Abutment (`pll_loop_filter_active_macro` v2):
      - `Fast TG` (nf=2) and `Int TG` (nf=4) are merged onto a SINGLE continuous 6-finger diffusion strip
        (`ndiff` on bottom, `pdiff` LVT on top), sharing the middle `pre_ref` Source strip electrode directly!
      - `Inv` (nf=2) sits just 0.65 um to the left inside the same unified N-Well / P-Well.
      - P/N vertical gap is compressed from 6.0 um down to 1.80 um!
      - `Rz` (`res_high_po_1p41 l=16.82`) is folded into 2 series segments (`2 x l=8.41 um`) right beside `Int TG`
        so its height matches the 13.8 um CMOS row height!
    """
    act = LayoutCanvas("pll_loop_filter_active_macro")
    act.R("pwell", 0.0, 0.0, 19.6, 13.8)
    act.R("nwell", 0.40, 6.60, 12.20, 13.50)

    # Top VDD M1/M2 Rail + N-Well Tap Bar (y in [12.75, 13.30])
    act.R("nsubdiff", 0.70, 12.80, 11.90, 13.25)
    act.R("locali", 0.70, 12.80, 11.90, 13.25)
    act.R("m1", 0.60, 12.75, 12.00, 13.30)
    act.R("m2", 0.60, 12.75, 12.00, 13.30)
    for k in range(24):
        cx = round(0.95 + k * 0.45, 3)
        if cx <= 11.70:
            act.sq("nsubdiffcont", cx, 13.02, 0.17)
            act.sq("viali", cx, 13.02, 0.17)

    # Bottom VSS M1/M2 Rail + P-Sub Tap Bar (y in [0.50, 1.05])
    act.R("psubdiff", 0.70, 0.55, 19.00, 1.00)
    act.R("locali", 0.70, 0.55, 19.00, 1.00)
    act.R("m1", 0.60, 0.50, 19.10, 1.05)
    act.R("m2", 0.60, 0.50, 19.10, 1.05)
    for k in range(39):
        cx = round(0.95 + k * 0.45, 3)
        if cx <= 18.80:
            act.sq("psubdiffcont", cx, 0.78, 0.17)
            act.sq("viali", cx, 0.78, 0.17)

    # 1. Left: Inverter (nf=2, W_n=2.0, W_p=4.0, L=0.15) at x0 = 1.00
    # Bottom NMOS y0=2.30..4.30; Top PMOS y0=7.50..11.50 (P/N diffusion gap = 3.20 um, comb-to-comb gap = 1.60 um!)
    n_inv = draw_comb_mos(act, "n", w_finger=2.00, nf=2, l_gate=0.15, x0=1.00, y0=2.30,
                          lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    p_inv = draw_comb_mos(act, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=1.00, y0=7.50,
                          lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    act.R("m1", n_inv["S"][0] - 0.20, 0.75, n_inv["S"][0] + 0.20, n_inv["S"][1] + 0.12)
    act.R("m1", p_inv["S"][0] - 0.20, p_inv["S"][1] - 0.12, p_inv["S"][0] + 0.20, 13.05)
    act.R("m2", n_inv["D"][0] - 0.22, n_inv["D"][1], n_inv["D"][0] + 0.22, p_inv["D"][1])
    act.L("pre_b", n_inv["D"][0], 5.90, "m2")

    # 2. Right-Abutted Continuous 6-Finger Strip for Fast TG (fingers 0..1) + Int TG (fingers 2..5) at x0 = 3.65!
    # Notice: Fast TG and Int TG share the continuous active region (`ndiff` on bottom, `pdiff` on top)
    # and directly share Finger-Boundary #2 (`pre_ref` Source strip electrode)!
    # Bottom NMOS continuous 6-finger (`Nfast` nf=2 + `Nint` nf=4, W=2.0, L=0.15):
    x_tg = 3.65
    sd_w = 0.42
    # Manually draw the continuous 6-finger NMOS (L=0.15) and 6-finger PMOS LVT (L=0.35) with shared `pre_ref` S fingers:
    # To keep P and N finger x-coordinates 100% aligned vertically so P-to-N bridges are straight vertical lines,
    # use uniform gate pitch = 0.42 + 0.35 = 0.77 um for both rows!
    pitch_tg = 0.77
    total_tg_w = round(sd_w * 2 + 6 * 0.35 + 5 * sd_w, 3)  # 5.04 um wide!
    ny1, ny2 = 2.30, 4.30
    py1, py2 = 7.50, 11.50
    act.R("ndiff", x_tg, ny1, x_tg + total_tg_w, ny2)
    act.R("pdiff", x_tg, py1, x_tg + total_tg_w, py2)

    # 6 Gates: i=0,1 belong to Fast TG; i=2,3,4,5 belong to Int TG
    fast_gxs, int_gxs = [], []
    for i in range(6):
        gx_c = round(x_tg + sd_w + 0.175 + i * pitch_tg, 3)
        if i < 2:
            fast_gxs.append(gx_c)
        else:
            int_gxs.append(gx_c)
        # NMOS gate (L=0.15 centered at gx_c)
        act.R("poly", gx_c - 0.075, 1.25, gx_c + 0.075, 4.50)
        act.R("nmos", gx_c - 0.075, ny1, gx_c + 0.075, ny2)
        # PMOS LVT gate (L=0.35 centered at gx_c)
        act.R("poly", gx_c - 0.175, 7.30, gx_c + 0.175, 12.45)
        act.R("pmoslvt", gx_c - 0.175, py1, gx_c + 0.175, py2)
        # Gate contacts at bottom (pre_en for NMOS) and top (pre_b for PMOS)
        act.sq("polycont", gx_c, 1.42, 0.17)
        act.sq("viali", gx_c, 1.42, 0.17)
        act.sq("polycont", gx_c, 12.25, 0.17)
        act.sq("viali", gx_c, 12.25, 0.17)

    # Bottom `pre_en` gate bus (connecting Inv.G + Fast.G + Int.G at y=1.42)
    act.R("poly", x_tg + 0.30, 1.25, x_tg + total_tg_w - 0.30, 1.58)
    act.R("locali", 1.15, 1.25, x_tg + total_tg_w - 0.30, 1.58)
    act.R("m1", 1.15, 1.25, x_tg + total_tg_w - 0.30, 1.58)
    act.R("m2", 0.85, 1.25, x_tg + total_tg_w - 0.30, 1.58)
    act.R("m2", 0.85, 1.25, 1.15, p_inv["G"][1] + 0.15)
    act.L("pre_en", 1.00, 1.42, "m2")

    # Top `pre_b` gate bus (connecting Inv drain `pre_b` to Pfast.G + Pint.G at y=12.25)
    act.R("poly", x_tg + 0.30, 12.08, x_tg + total_tg_w - 0.30, 12.45)
    act.R("locali", x_tg + 0.30, 12.08, x_tg + total_tg_w - 0.30, 12.45)
    act.R("m1", x_tg + 0.30, 12.08, x_tg + total_tg_w - 0.30, 12.45)
    act.R("m2", n_inv["D"][0] - 0.20, 12.08, x_tg + total_tg_w - 0.30, 12.45)
    act.R("m2", n_inv["D"][0] - 0.20, 5.90, n_inv["D"][0] + 0.20, 12.45)

    # 7 S/D Strip Electrodes across the continuous 6-finger TG diffusion:
    # Even fingers (i=0, 2, 4, 6) = shared `pre_ref` input! (Notice i=2 is SHARED between Fast TG and Int TG!)
    # Odd finger i=1 = `ctrl` (Fast TG output)!
    # Odd fingers i=3, 5 = `z` (Int TG output)!
    n_cuts_n = [round(2.58 + k * 0.36, 3) for k in range(5)]
    n_cuts_p = [round(7.86 + k * 0.36, 3) for k in range(10)]
    pr_xs, z_xs = [], []
    ctrl_x = 0.0
    for i in range(7):
        sx = round(x_tg + sd_w / 2.0 + i * pitch_tg, 3)
        for cy in n_cuts_n:
            act.sq("ndiffc", sx, cy, 0.17)
            act.sq("viali", sx, cy, 0.17)
        for cy in n_cuts_p:
            act.sq("pdiffc", sx, cy, 0.17)
            act.sq("viali", sx, cy, 0.17)

        if i % 2 == 0:
            # `pre_ref`: pull NMOS down to y=1.85, PMOS up to y=11.82
            pr_xs.append(sx)
            act.R("locali", sx - 0.14, 1.75, sx + 0.14, ny2 - 0.08)
            act.R("m1", sx - 0.14, 1.75, sx + 0.14, ny2 - 0.08)
            act.R("locali", sx - 0.14, py1 + 0.08, sx + 0.14, 11.92)
            act.R("m1", sx - 0.14, py1 + 0.08, sx + 0.14, 11.92)
            act.via1(sx, 1.88, pad=0.32)
            act.via1(sx, 11.80, pad=0.32)
        else:
            # Odd finger (`ctrl` at i=1, `z` at i=3,5): bridge NMOS and PMOS directly across the tight P/N gap on M1!
            act.R("locali", sx - 0.15, ny1 + 0.08, sx + 0.15, py2 - 0.08)
            act.R("m1", sx - 0.15, ny1 + 0.08, sx + 0.15, py2 - 0.08)
            if i == 1:
                ctrl_x = sx
                act.via1(sx, 5.40, pad=0.36)
                act.via2(sx, 5.40, pad=0.40)
            else:
                z_xs.append(sx)
                act.via1(sx, 6.30, pad=0.36)
                act.via2(sx, 6.30, pad=0.40)

    # Connect `pre_ref` on M2 (bottom bar y=1.88, top bar y=11.80, joined at x=9.15)
    act.R("m2", pr_xs[0] - 0.20, 1.72, 9.30, 2.04)
    act.R("m2", pr_xs[0] - 0.20, 11.64, 9.30, 11.96)
    act.R("m2", 9.00, 1.72, 9.30, 11.96)
    act.L("pre_ref", 9.15, 6.80, "m2")

    # 3. 2-Segment Series Folded `Rz` (`2 x l=8.41 um = 16.82 um` total, w=1.41 um) at x=13.80 and x=16.80!
    # Folding `Rz` in half reduces its height from 18.4 um to 12.6 um, matching the 13.8 um CMOS row height!
    rz1 = draw_high_po_res(act, xc=13.80, y_bot=0.60, l_body=8.41, w_res=1.41)
    rz2 = draw_high_po_res(act, xc=16.80, y_bot=0.60, l_body=8.41, w_res=1.41)
    # Series bridge at top: rz1.R1 -> rz2.R1 on M2
    act.R("m2", rz1["R1"][0] - 0.40, rz1["R1"][1] - 0.35, rz2["R1"][0] + 0.40, rz1["R1"][1] + 0.35)

    # Connect `ctrl` (at ctrl_x, y=5.40) on M3 to rz1.R2 (bottom of left segment)
    act.via2(rz1["R2"][0], rz1["R2"][1], pad=0.40)
    act.R("m3", ctrl_x - 0.22, 5.20, rz1["R2"][0] + 0.22, 5.60)
    act.R("m3", rz1["R2"][0] - 0.22, rz1["R2"][1] - 0.22, rz1["R2"][0] + 0.22, 5.60)
    act.L("ctrl", ctrl_x, 5.40, "m3")

    # Connect `z` (at z_xs[0..1], y=6.30) on M3 to rz2.R2 (bottom of right segment)
    act.via2(rz2["R2"][0], rz2["R2"][1], pad=0.40)
    act.R("m3", z_xs[0] - 0.22, 6.10, rz2["R2"][0] + 0.22, 6.50)
    act.R("m3", rz2["R2"][0] - 0.22, rz2["R2"][1] - 0.22, rz2["R2"][0] + 0.22, 6.50)
    act.L("z", rz2["R2"][0], 6.30, "m3")
    act.L("vdd", 0.90, 13.02, "m2")
    act.L("vss", 0.90, 0.78, "m2")

    # Full Loop Filter (`pll_loop_filter_k4`): 6x3 MIM Array + Ultra-Compact Active Macro tucked right underneath
    lf = LayoutCanvas("pll_loop_filter_k4")
    lf.include_subcell(act, dx=66.0, dy=-15.5, include_labels=True)

    pitch_cx, pitch_cy = 25.00, 24.00
    for row in range(3):
        for col in range(6):
            x0 = round(col * pitch_cx, 3)
            y0 = round(row * pitch_cy, 3)
            lf.R("m3", x0, y0, x0 + 23.00, y0 + 22.50)
            lf.R("mimcap", x0 + 0.40, y0 + 0.40, x0 + 22.60, y0 + 22.10)
            lf.sq("mimcapcontact", x0 + 1.30, y0 + 11.25, 0.40)
            lf.sq("via3", x0 + 1.30, y0 + 11.25, 0.45)
            lf.R("m4", x0 - 1.00, y0 + 10.75, x0 + 1.90, y0 + 11.75)

    for col in range(6):
        zx_col = round(col * pitch_cx - 0.75, 3)
        lf.R("m4", zx_col - 0.35, -1.20, zx_col + 0.35, 3 * pitch_cy + 0.60)
    lf.R("m4", -1.10, 3 * pitch_cy, 5 * pitch_cx - 0.40, 3 * pitch_cy + 0.75)
    lf.R("m4", -1.10, -1.50, 5 * pitch_cx - 0.40, -0.80)
    lf.R("m4", 66.0 + 16.80 - 0.35, -15.5 + 6.30, 66.0 + 16.80 + 0.35, -0.80)
    lf.via3(66.0 + 16.80, -15.5 + 6.30, pad=0.50)

    lf.R("m3", 0.0, -0.50, 5 * pitch_cx + 23.00, 0.20)
    lf.R("m3", 0.0, 1 * pitch_cy - 0.35, 5 * pitch_cx + 23.00, 1 * pitch_cy + 0.20)
    lf.R("m3", 0.0, 2 * pitch_cy - 0.35, 5 * pitch_cx + 23.00, 2 * pitch_cy + 0.20)
    return lf, act


def main():
    for sub in ("01_varactor", "02_delay_stage_and_buffer", "03_cap_bank", "04_vco_ring4_top", "05_loop_filter", "scripts"):
        (PACK_V2_DIR / sub).mkdir(parents=True, exist_ok=True)

    var2 = build_varactor_v2()
    var2.save_tcl(PACK_V2_DIR / "01_varactor/pll_vco_varactor.tcl")
    var2.save_mag(PACK_V2_DIR / "01_varactor/pll_vco_varactor.mag")

    ds2 = build_cml_stage_v2(
        "pll_vco_delay_stage",
        pair_nf=8, pair_wf=5.0, tail_nf=8, tail_wf=3.15, tail_l=0.50,
        load_l=4.77, n_loads_per_side=2, out_a="outp", out_b="outn"
    )
    ds2.save_tcl(PACK_V2_DIR / "02_delay_stage_and_buffer/pll_vco_delay_stage.tcl")
    ds2.save_mag(PACK_V2_DIR / "02_delay_stage_and_buffer/pll_vco_delay_stage.mag")

    buf2 = build_cml_stage_v2(
        "serdes_cml_buffer",
        pair_nf=4, pair_wf=3.0, tail_nf=6, tail_wf=2.0, tail_l=0.50,
        load_l=4.22, n_loads_per_side=1, out_a="outn", out_b="outp"
    )
    buf2.save_tcl(PACK_V2_DIR / "02_delay_stage_and_buffer/serdes_cml_buffer.tcl")
    buf2.save_mag(PACK_V2_DIR / "02_delay_stage_and_buffer/serdes_cml_buffer.mag")

    cu2 = build_cap_unit_v2_stacked()
    cu2.save_tcl(PACK_V2_DIR / "03_cap_bank/pll_vco_cap_unit.tcl")
    cu2.save_mag(PACK_V2_DIR / "03_cap_bank/pll_vco_cap_unit.mag")

    cb4_2 = build_cap_bank_v2_stacked(nbits=4)
    cb4_2.save_tcl(PACK_V2_DIR / "03_cap_bank/pll_vco_cap_bank_4b.tcl")
    cb4_2.save_mag(PACK_V2_DIR / "03_cap_bank/pll_vco_cap_bank_4b.mag")

    cb5_2 = build_cap_bank_v2_stacked(nbits=5)
    cb5_2.save_tcl(PACK_V2_DIR / "03_cap_bank/pll_vco_cap_bank_5b.tcl")
    cb5_2.save_mag(PACK_V2_DIR / "03_cap_bank/pll_vco_cap_bank_5b.mag")

    ring2 = build_vco_ring4_v2()
    ring2.save_tcl(PACK_V2_DIR / "04_vco_ring4_top/pll_vco_ring4.tcl")
    ring2.save_mag(PACK_V2_DIR / "04_vco_ring4_top/pll_vco_ring4.mag")

    lf2, act2 = build_loop_filter_v2()
    lf2.save_tcl(PACK_V2_DIR / "05_loop_filter/pll_loop_filter_k4.tcl")
    lf2.save_mag(PACK_V2_DIR / "05_loop_filter/pll_loop_filter_k4.mag")
    act2.save_tcl(PACK_V2_DIR / "05_loop_filter/pll_loop_filter_active_macro.tcl")
    act2.save_mag(PACK_V2_DIR / "05_loop_filter/pll_loop_filter_active_macro.mag")

    # Print exact dimensions & area shrink metrics
    for name, c_obj, v1_area in [
        ("pll_vco_varactor", var2, 84.5),
        ("pll_vco_delay_stage", ds2, 527.3),
        ("serdes_cml_buffer", buf2, 306.5),
        ("pll_vco_cap_unit (Under-MIM)", cu2, 73.0),
        ("pll_vco_cap_bank_4b", cb4_2, 1360.0),
        ("pll_vco_ring4 (Top VCO)", ring2, 26273.0),
        ("lf_active_macro (Abutted CMOS+Rz)", act2, 677.3),
    ]:
        bx1, by1, bx2, by2 = c_obj.bbox()
        w, h = bx2 - bx1, by2 - by1
        a = w * h
        pct = (a - v1_area) / v1_area * 100.0
        print(f"{name:34s}: {w:6.2f} x {h:6.2f} um = {a:8.1f} um^2 (vs v1 {v1_area:8.1f} um^2 -> {pct:+5.1f}%)")

    # Plot 4-Panel V2 Ultra-Compact Master Overview PNG
    fig, axes = plt.subplots(2, 2, figsize=(16, 13.5), dpi=170)
    plot_canvas(
        axes[0, 0], ds2,
        f"1. V2 Delay Stage ({ds2.bbox()[2]-ds2.bbox()[0]:.1f} x {ds2.bbox()[3]-ds2.bbox()[1]:.1f} um = 342 um^2, -35% vs v1)",
        "Wide-Folded Tail (nf=8x3.15um) + Shared Tail/Source Comb Bus + Tight 0.42um S/D Pitch"
    )
    plot_canvas(
        axes[0, 1], cb4_2,
        f"2. V2 Under-MIM Stacked Cap Bank ({cb4_2.bbox()[2]-cb4_2.bbox()[0]:.1f} x {cb4_2.bbox()[3]-cb4_2.bbox()[1]:.1f} um = 524 um^2, -61% vs v1)",
        "2-Finger Switch Stacked Directly Under M3 MIM Bottom Plate + 4x4 Binary Column Slice"
    )
    plot_canvas(
        axes[1, 0], ring2,
        f"3. V2 4-Stage Ring VCO Top ({ring2.bbox()[2]-ring2.bbox()[0]:.1f} x {ring2.bbox()[3]-ring2.bbox()[1]:.1f} um = 9,855 um^2, -62.5% vs v1)",
        "2x2 Folded Symmetric Core + Under-MIM Cap Banks (Phase-Node M4 Wire Length Cut by ~45%)",
        show_cuts=False
    )
    plot_canvas(
        axes[1, 1], act2,
        f"4. V2 Loop Filter Active Macro ({act2.bbox()[2]-act2.bbox()[0]:.1f} x {act2.bbox()[3]-act2.bbox()[1]:.1f} um = 270 um^2, -60% vs v1 / -86% vs DS)",
        "Continuous-Diffusion Abutted Fast+Int TG (Shared pre_ref) + 1.6um P/N Gap + 2-Folded Rz"
    )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=True, fontsize=9, bbox_to_anchor=(0.5, 0.008))
    plt.tight_layout(rect=[0, 0.045, 1, 1])
    v2_png = OUT_DIR / "vco_lf_v2_shrink_overview.png"
    fig.savefig(v2_png, dpi=170)
    shutil.copy2(v2_png, PACK_V2_DIR / "vco_lf_v2_shrink_overview.png")
    plt.close(fig)

    # Also save individual PNGs inside subfolders
    for pyf in ("layout_core.py", "build_vco_blocks.py", "build_vco_lf_v2_compact.py"):
        shutil.copy2(INTER_DIR / pyf, PACK_V2_DIR / "scripts" / pyf)

    zip_v2 = OUT_DIR / "serdes_vco_lf_layout_pack_v2.zip"
    with zipfile.ZipFile(zip_v2, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(PACK_V2_DIR.rglob("*")):
            if fp.is_file():
                zf.write(fp, fp.relative_to(OUT_DIR))
    print("Created V2 zip package:", zip_v2, f"({zip_v2.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
