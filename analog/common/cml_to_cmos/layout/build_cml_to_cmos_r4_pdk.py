#!/usr/bin/env python3
"""Build the r4_v4_1d_final full-rate CML-to-CMOS candidate.

Mirror analog/digital paths with double-ended gate contacts and explicit
supply/body straps. The independent physical reference describes the actual
finger geometry. This also supplies primitive helpers for the r5 candidate.
Known SS-cold RC duty and mismatch weaknesses remain open; DRC/LVS does not
qualify those electrical boundaries. Write each build into a new directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402

W_M1 = 0.18
W_M2 = 0.32
W_M3 = 0.40
W_PWR_M1 = 0.32
W_PWR_M2 = 0.44
W_PWR_M3 = 0.60

# =============================================================================
# Y-Coordinates: Strip 1 (Analog, mirrored across y=0) + Strip 2 (Digital, y > 12.55)
# =============================================================================
Y_ANA_VSS = 0.000
Y_A_NBOT = 1.150       # >=0.70um below ndiff for bottom polycont @ 0.620 + poly tie [0.91..1.06]
Y_A_NTOP = 5.150       # Xip/Xin top (w_f=4.0); Xtail top=4.35, Xsp top=4.15
A_NPOLY_TIE_BOT = (0.910, 1.060)
A_NCONT_BOT = 0.620
A_NPOLY_TIE_TOP = (5.240, 5.390)
Y_A_T0 = 5.560
Y_A_T1 = 6.180
Y_A_T2 = 6.800
Y_A_WELL = 6.180       # Domain B pwell/nwell split
Y_A_PBOT = 7.210       # Xfp & Xlp/Xln bottom (w_f=4.0 -> top=11.210)
Y_A_PTOP = 11.210
A_PPOLY_TIE_BOT = (6.970, 7.120)
A_PPOLY_TIE_TOP = (11.300, 11.450)
A_PCONT_TOP = 11.740
Y_A_TOP_GR = 12.300    # Domain A top psubdiff closure ring
Y_VDD1 = 13.200

# Digital half-height = 7.460 around center Y_ANA_VSS = 0.000 -> Digital VDD = +-7.460 (stepped in cleanly from Analog +-13.200)
Y_VDD_DIG = 7.460
Y_DIG_TOP = 7.880

# Digital half-row offset template (relative to Y_DIG_VSS = 20.660; room for dp1..3 p_wf=2.4)
D_N_OFF = 2.440        # ndiff top offset from VSS (2.0 um NMOS sits [0.44 .. 2.44], 0.295 clear of H_TAP_VSS)
D_T0_OFF = 2.790
D_T1_OFF = 3.400
D_T2_OFF = 4.010
D_P_OFF = 4.360        # pdiff bot offset from VSS (2.4 um PMOS sits [4.36 .. 6.76], 0.525 clear of Y_VDD2)
D_NPOLY_OFF = (2.530, 2.680)
D_PPOLY_OFF = (4.120, 4.270)
D_NDUM_OFF = 2.815
D_PDUM_OFF = 3.985

H_TAP_VSS = 0.145
H_TAP_VDD = 0.175
V_TAP_WALL = 0.180
V_TAP_EDGE = 0.220


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def poly_cont_pad(c: Cell, x: float, y: float) -> None:
    c.pad("poly", x, y, 0.27, 0.34)
    c.pad("polycont", x, y, 0.17, 0.17)
    c.pad("locali", x, y, 0.18, 0.34)


def draw_tap_h(c: Cell, diff_layer: str, x1: float, x2: float, y: float, half_w: float) -> None:
    c.rect(diff_layer, x1, grid(y - half_w), x2, grid(y + half_w))
    c.rect("locali", x1, grid(y - 0.085), x2, grid(y + 0.085))
    if (x2 - x1) >= 0.48:
        c.rect(diff_layer + "cont", grid(x1 + 0.14), grid(y - 0.085), grid(x2 - 0.14), grid(y + 0.085))


def draw_tap_v(c: Cell, diff_layer: str, x: float, y1: float, y2: float, half_w: float = V_TAP_WALL) -> None:
    c.rect(diff_layer, grid(x - half_w), grid(y1 - 0.085), grid(x + half_w), grid(y2 + 0.085))
    c.rect("locali", grid(x - 0.085), grid(y1 - 0.085), grid(x + 0.085), grid(y2 + 0.085))
    if (y2 - y1) >= 0.90:
        c.rect(diff_layer + "cont", grid(x - 0.085), grid(y1 + 0.360), grid(x + 0.085), grid(y2 - 0.360))


def via3_pad(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.44)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.44)


def viali_on_rail(c: Cell, x: float, y: float) -> None:
    c.pad("viali", x, y, 0.17)
    c.pad("metal1", x, y, 0.32, 0.32)


def draw_np_wall_band(c: Cell, x: float, y_vss: float, y_t1: float, y_vdd: float, half_w: float = V_TAP_WALL) -> None:
    """Draw N/P vertical guard wall in a standard CMOS half-row leaving y_t1 open for locali."""
    ya, yb = sorted((y_vss, y_vdd))
    if y_vss < y_vdd:
        draw_tap_v(c, "psubdiff", x, y_vss, grid(y_t1 - 0.360), half_w=half_w)
        draw_tap_v(c, "nsubdiff", x, grid(y_t1 + 0.360), y_vdd, half_w=half_w)
    else:
        draw_tap_v(c, "nsubdiff", x, y_vdd, grid(y_t1 - 0.360), half_w=half_w)
        draw_tap_v(c, "psubdiff", x, grid(y_t1 + 0.360), y_vss, half_w=half_w)
    viali_on_rail(c, x, y_vss)
    viali_on_rail(c, x, y_vdd)


def build_mos(
    work: Path,
    name: str,
    model: str,
    w_f: float,
    l_f: float,
    nf: int,
    dy: float,
    is_pmos: bool,
) -> tuple[Cell, dict]:
    p = pdk_device(work, name, model, dict(w=w_f, l=l_f, nf=nf, conn_gates=0, topc=0, botc=0, guard=0))
    out = Cell()
    cut_layer = "pdiffc" if is_pmos else "ndiffc"
    diff_layer = "pdiff" if is_pmos else "ndiff"
    h_clip = grid(w_f / 2.0 + 0.130)

    for layer, rects in p.rects.items():
        if layer in ("viali", "metal1", "pwell", "nwell", "checkpaint"):
            continue
        for x1, y1, x2, y2 in rects:
            if layer == "poly":
                y1 = max(y1, -h_clip)
                y2 = min(y2, h_clip)
                if y2 <= y1:
                    continue
            out.rect(layer, x1, grid(y1 + dy), x2, grid(y2 + dy))

    sds = sorted({grid((r[0] + r[2]) / 2.0) for r in p.rects[cut_layer]})
    gxs = sorted({grid((r[0] + r[2]) / 2.0) for r in p.rects["poly"]})
    diffs = out.rects[diff_layer]
    diff_x1 = grid(min(r[0] for r in diffs))
    diff_x2 = grid(max(r[2] for r in diffs))
    c_y1 = grid(min(r[1] for r in p.rects[cut_layer]) + dy)
    c_y2 = grid(max(r[3] for r in p.rects[cut_layer]) + dy)

    return out, {
        "w_diff": grid(diff_x2 - diff_x1),
        "hw_diff": grid((diff_x2 - diff_x1) / 2.0),
        "s_xs": sds[::2],
        "d_xs": sds[1::2],
        "g_xs": gxs,
        "l_f": l_f,
        "c_y1": c_y1,
        "c_y2": c_y2,
    }


def tie_poly_fingers(c: Cell, cx: float, g_xs: list[float], l_f: float, y_tie: tuple[float, float], y_stub_edge: float) -> None:
    hw_g = grid(l_f / 2.0)
    for gx in g_xs:
        c.rect("poly", grid(cx + gx - hw_g), min(y_tie[0], y_stub_edge), grid(cx + gx + hw_g), max(y_tie[1], y_stub_edge))
    if len(g_xs) > 1:
        c.rect("poly", grid(cx + g_xs[0] - hw_g), y_tie[0], grid(cx + g_xs[-1] + hw_g), y_tie[1])


def add_field_poly_dummy(
    c: Cell,
    x_dum: float,
    l_f: float,
    y_diff_lo: float,
    y_diff_hi: float,
    y_cont: float,
    cont_below_diff: bool,
    y_rail: float,
    *,
    x_wall: float | None = None,
    x_vdrop: float | None = None,
) -> None:
    hw_g = grid(l_f / 2.0)
    if cont_below_diff:
        c.rect("poly", grid(x_dum - hw_g), grid(y_cont - 0.170), grid(x_dum + hw_g), grid(y_diff_hi + 0.130))
    else:
        c.rect("poly", grid(x_dum - hw_g), grid(y_diff_lo - 0.130), grid(x_dum + hw_g), grid(y_cont + 0.170))
    poly_cont_pad(c, x_dum, y_cont)
    if x_wall is not None:
        bx1 = min(grid(x_dum - 0.090), grid(x_wall - 0.085))
        bx2 = max(grid(x_dum + 0.090), grid(x_wall + 0.085))
        c.rect("locali", bx1, grid(y_cont - 0.085), bx2, grid(y_cont + 0.085))
    elif x_vdrop is not None:
        bx1 = min(grid(x_dum - 0.090), grid(x_vdrop - 0.085))
        bx2 = max(grid(x_dum + 0.090), grid(x_vdrop + 0.085))
        c.rect("locali", bx1, grid(y_cont - 0.085), bx2, grid(y_cont + 0.085))
        ry1, ry2 = sorted((y_rail, y_cont))
        c.rect("locali", grid(x_vdrop - 0.085), grid(ry1 - 0.085), grid(x_vdrop + 0.085), grid(ry2 + 0.085))


def strap_m1_sources(
    c: Cell,
    cx: float,
    s_xs: list[float],
    y_lo: float,
    y_hi: float,
    viali_ys: list[float] | None = None,
    width: float = 0.24,
) -> None:
    """Place vertical M1 + explicit non-rail viali along active source fingers to cut locali R in RCX."""
    ys = viali_ys if viali_ys is not None else [grid(y_lo + 0.25), grid((y_lo + y_hi) / 2.0), grid(y_hi - 0.25)]
    for sx in s_xs:
        xc = grid(cx + sx)
        lo_y = min([y_lo] + [grid(yv - 0.145) for yv in ys])
        hi_y = max([y_hi] + [grid(yv + 0.145) for yv in ys])
        c.wire("metal1", [(xc, lo_y), (xc, hi_y)], width)
        for yv in ys:
            yg = grid(yv)
            c.pad("viali", xc, yg, 0.17)
            c.pad("metal1", xc, yg, 0.24, 0.29)


def build_analog_half(w: Path) -> tuple[Cell, dict]:
    """Build one Analog half-chain in y > 0 (mirrored across y=0 for N-path)."""
    h = Cell()

    # Domain A: Xsp(3/0.5) + Xtail(3.2x10=32/0.5) on bottom; Xfp(4x8=32/0.15 LVT) on top
    sp, i_sp = build_mos(w, "sp", "sky130_fd_pr__nfet_01v8", 3.0, 0.50, 1, grid(Y_A_NBOT + 1.500), False)
    tail, i_tl = build_mos(w, "tail", "sky130_fd_pr__nfet_01v8", 3.2, 0.50, 10, grid(Y_A_NBOT + 1.600), False)
    fp, i_fp = build_mos(w, "fp", "sky130_fd_pr__nfet_01v8_lvt", 4.0, 0.15, 8, grid(Y_A_PBOT + 2.000), False)

    x_left_gr = 0.300
    cx_sp = grid(x_left_gr + V_TAP_EDGE + 0.360 + 0.500 + 0.085 + i_sp["hw_diff"])
    x_sp_dl = grid(cx_sp - i_sp["hw_diff"] - 0.085 - 0.250)
    x_sp_dr = grid(cx_sp + i_sp["hw_diff"] + 0.085 + 0.250)
    x_sp_vdrop = grid(x_sp_dr + 0.360)
    x_tl_dl = grid(x_sp_vdrop + 0.360)
    cx_tl = grid(x_tl_dl + 0.250 + 0.085 + i_tl["hw_diff"])
    x_tl_dr = grid(cx_tl + i_tl["hw_diff"] + 0.085 + 0.250)

    cx_fp = grid(cx_tl)
    x_fp_dl = grid(cx_fp - i_fp["hw_diff"] - 0.085 - 0.075)
    x_fp_dr = grid(cx_fp + i_fp["hw_diff"] + 0.085 + 0.075)
    x_sf_gr = grid(max(x_tl_dr + 0.250, x_fp_dr + 0.075) + 0.360 + V_TAP_WALL)

    # Gap A <-> B (cr1 M3 crossover)
    x_cr1_p = grid(x_sf_gr + V_TAP_WALL + 0.340)
    x_cr1_n = grid(x_cr1_p + 0.740)
    x_ad = grid(x_sf_gr + V_TAP_WALL + 0.160)
    x_ana_l_wall = grid(x_cr1_n + 0.360 + V_TAP_WALL)

    # Domain B: Xip(4x4=16) + Xin(4x4=16) bottom; Xlp(4x8=32) + Xln(4x8=32) top
    ip_n, i_ipn = build_mos(w, "ip_n", "sky130_fd_pr__nfet_01v8_lvt", 4.0, 0.15, 4, grid(Y_A_NBOT + 2.000), False)
    ip_p, i_ipp = build_mos(w, "lp_p", "sky130_fd_pr__pfet_01v8",      4.0, 0.15, 8, grid(Y_A_PBOT + 2.000), True)
    in_n, i_inn = build_mos(w, "in_n", "sky130_fd_pr__nfet_01v8_lvt", 4.0, 0.15, 4, grid(Y_A_NBOT + 2.000), False)
    in_p, i_inp = build_mos(w, "ln_p", "sky130_fd_pr__pfet_01v8",      4.0, 0.15, 8, grid(Y_A_PBOT + 2.000), True)

    hw_ana_col = max(i_ipn["hw_diff"], i_ipp["hw_diff"])
    cx_ip = grid(x_ana_l_wall + V_TAP_WALL + 0.780 + hw_ana_col)
    cx_in = grid(cx_ip + hw_ana_col + 1.240 + hw_ana_col)
    x_mir_mid = grid((cx_ip + cx_in) / 2.0)
    x_ana_r_wall = grid(cx_in + hw_ana_col + 0.780 + V_TAP_WALL)

    h.include(sp, dx=cx_sp)
    h.include(tail, dx=cx_tl)
    h.include(fp, dx=cx_fp)
    for nm_c, cx_c in ((ip_n, cx_ip), (in_n, cx_in), (ip_p, cx_ip), (in_p, cx_in)):
        h.include(nm_c, dx=cx_c)

    # Dummies Domain A (all tied to VSS)
    add_field_poly_dummy(h, x_sp_dl, 0.50, Y_A_NBOT, grid(Y_A_NBOT + 3.0), grid(Y_A_T0), False, Y_ANA_VSS, x_wall=x_left_gr)
    add_field_poly_dummy(h, x_sp_dr, 0.50, Y_A_NBOT, grid(Y_A_NBOT + 3.0), grid(Y_A_T0), False, Y_ANA_VSS, x_vdrop=x_sp_vdrop)
    add_field_poly_dummy(h, x_tl_dl, 0.50, Y_A_NBOT, grid(Y_A_NBOT + 3.2), grid(Y_A_T0), False, Y_ANA_VSS, x_vdrop=x_sp_vdrop)
    add_field_poly_dummy(h, x_tl_dr, 0.50, Y_A_NBOT, grid(Y_A_NBOT + 3.2), grid(Y_A_T0), False, Y_ANA_VSS, x_wall=x_sf_gr)
    x_fp_vdrop_l = grid(x_fp_dl - 0.360)
    x_fp_vdrop_r = grid(x_fp_dr + 0.360)
    add_field_poly_dummy(h, x_fp_dl, 0.15, Y_A_PBOT, Y_A_PTOP, grid(Y_A_T2 - 0.02), True, Y_A_TOP_GR, x_vdrop=x_fp_vdrop_l)
    add_field_poly_dummy(h, x_fp_dr, 0.15, Y_A_PBOT, Y_A_PTOP, grid(Y_A_T2 - 0.02), True, Y_A_TOP_GR, x_vdrop=x_fp_vdrop_r)

    # Dummies Domain B (N -> VSS, P -> VDD1)
    for side, cx_c in ((-1, cx_ip), (+1, cx_ip), (-1, cx_in), (+1, cx_in)):
        x_dn = grid(cx_c + side * (i_ipn["hw_diff"] + 0.180))
        x_dp = grid(cx_c + side * (i_ipp["hw_diff"] + 0.180))
        if cx_c == cx_ip and side == -1:
            add_field_poly_dummy(h, x_dn, 0.15, Y_A_NBOT, Y_A_NTOP, grid(Y_A_T0 + 0.02), False, Y_ANA_VSS, x_wall=x_ana_l_wall)
            add_field_poly_dummy(h, x_dp, 0.15, Y_A_PBOT, Y_A_PTOP, grid(Y_A_T2 - 0.02), True, Y_VDD1, x_wall=x_ana_l_wall)
        elif cx_c == cx_in and side == +1:
            add_field_poly_dummy(h, x_dn, 0.15, Y_A_NBOT, Y_A_NTOP, grid(Y_A_T0 + 0.02), False, Y_ANA_VSS, x_wall=x_ana_r_wall)
            add_field_poly_dummy(h, x_dp, 0.15, Y_A_PBOT, Y_A_PTOP, grid(Y_A_T2 - 0.02), True, Y_VDD1, x_wall=x_ana_r_wall)
        else:
            add_field_poly_dummy(h, x_dn, 0.15, Y_A_NBOT, Y_A_NTOP, grid(Y_A_T0 + 0.02), False, Y_ANA_VSS, x_vdrop=x_mir_mid)
            add_field_poly_dummy(h, x_dp, 0.15, Y_A_PBOT, Y_A_PTOP, grid(Y_A_T2 - 0.02), True, Y_VDD1, x_vdrop=x_mir_mid)

    # Wire Domain A:
    # Xsp S->VSS (M1 + locali straight to Y_ANA_VSS), D->fp @ Y_A_T0
    sx_sp = grid(cx_sp + i_sp["s_xs"][0])
    h.rect("locali", grid(sx_sp - 0.085), Y_ANA_VSS, grid(sx_sp + 0.085), grid(i_sp["c_y1"] + 0.08))
    strap_m1_sources(h, cx_sp, i_sp["s_xs"], 0.000, grid(Y_A_NBOT + 2.5), [1.750, 2.500, 3.250])
    dx_sp = grid(cx_sp + i_sp["d_xs"][0])
    h.rect("locali", grid(dx_sp - 0.085), grid(i_sp["c_y2"] - 0.08), grid(dx_sp + 0.085), grid(Y_A_T0 + 0.085))
    for y_sp in (3.650, 4.750, Y_A_T0):
        h.pad("viali", dx_sp, y_sp, 0.17)
        h.pad("metal1", dx_sp, y_sp, 0.29)
    h.wire("metal1", [(dx_sp, 3.650), (dx_sp, Y_A_T0)], W_M1)

    gx_sp = grid(cx_sp - 0.24)
    h.rect("poly", grid(cx_sp - 0.25), grid(Y_A_NBOT + 3.0), grid(cx_sp + 0.25), A_NPOLY_TIE_TOP[1])
    h.rect("poly", grid(gx_sp - 0.135), A_NPOLY_TIE_TOP[0], grid(cx_sp + 0.25), grid(Y_A_T1 + 0.165))
    poly_cont_pad(h, gx_sp, Y_A_T1)
    h.pad("viali", gx_sp, Y_A_T1, 0.17)
    h.pad("metal1", gx_sp, Y_A_T1, 0.29)

    # Xtail S->VSS (locali + M1 source straps straight to Y_ANA_VSS!), D->ap_tail @ y=3.950
    for sx in i_tl["s_xs"]:
        xc = grid(cx_tl + sx)
        h.rect("locali", grid(xc - 0.085), Y_ANA_VSS, grid(xc + 0.085), grid(i_tl["c_y1"] + 0.08))
    strap_m1_sources(h, cx_tl, i_tl["s_xs"], 0.000, 3.450, [1.750, 2.500, 3.250])
    y_ap_tail = 3.950
    for dx in i_tl["d_xs"]:
        xc = grid(cx_tl + dx)
        h.pad("viali", xc, y_ap_tail, 0.17)
        h.pad("metal1", xc, y_ap_tail, 0.29)
    tie_poly_fingers(h, cx_tl, i_tl["g_xs"], i_tl["l_f"], A_NPOLY_TIE_TOP, grid(Y_A_NBOT + 3.2))
    gx_tl = grid(cx_tl)
    poly_cont_pad(h, gx_tl, Y_A_T1)
    h.rect("poly", grid(gx_tl - 0.135), A_NPOLY_TIE_TOP[0], grid(gx_tl + 0.135), grid(Y_A_T1 + 0.165))
    h.pad("viali", gx_tl, Y_A_T1, 0.17)
    h.pad("metal1", gx_tl, Y_A_T1, 0.29)
    x_vbias = 1.120
    h.wire("metal1", [(x_vbias, Y_A_T1), (gx_tl, Y_A_T1)], W_M1)

    # Xfp: D->VDD (M1 @ 10.75 -> dual M2 drops to Y_VDD1), S->fp (M1 @ 7.45 -> dual M2 drops to Y_A_T0)
    # Double-ended poly tie on Xfp (bottom A_PPOLY_TIE_BOT + top A_PPOLY_TIE_TOP + dual M2 straps @ gx_fp & gx_fp2!)
    for dx in i_fp["d_xs"]:
        xc = grid(cx_fp + dx)
        h.pad("viali", xc, 10.750, 0.17)
        h.pad("metal1", xc, 10.750, 0.29)
    h.wire("metal1", [(grid(cx_fp + i_fp["d_xs"][0]), 10.750), (grid(cx_fp + i_fp["d_xs"][-1]), 10.750)], 0.28)
    x_fp_vdd_drop_l = grid(cx_fp + i_fp["d_xs"][0])
    x_fp_vdd_drop = grid(cx_fp + i_fp["d_xs"][-1])
    for xfvd in (x_fp_vdd_drop_l, x_fp_vdd_drop):
        h.via1(xfvd, 10.750)
        h.via1(xfvd, Y_VDD1)
        h.wire("metal2", [(xfvd, 10.750), (xfvd, Y_VDD1)], W_PWR_M2)

    for sx in i_fp["s_xs"]:
        xc = grid(cx_fp + sx)
        h.pad("viali", xc, 7.450, 0.17)
        h.pad("metal1", xc, 7.450, 0.29)
    h.wire("metal1", [(grid(cx_fp + i_fp["s_xs"][0]), 7.450), (grid(cx_fp + i_fp["s_xs"][-1]), 7.450)], 0.26)
    x_fp_drop = grid(cx_fp + i_fp["s_xs"][-1])
    x_fp_drop_l = grid(cx_fp + i_fp["s_xs"][0])
    for xfpd in (x_fp_drop_l, x_fp_drop):
        h.via1(xfpd, 7.450)
        h.via1(xfpd, Y_A_T0)
        h.wire("metal2", [(xfpd, Y_A_T0), (xfpd, 7.450)], W_M2)
    h.wire("metal1", [(dx_sp, Y_A_T0), (x_sf_gr, Y_A_T0)], W_M1)

    # Xfp.G (inp @ Y_A_T2 + double-ended dual-tap poly @ A_PCONT_TOP strapped via M1 + dual M2 @ gx_fp/gx_fp2!)
    tie_poly_fingers(h, cx_fp, i_fp["g_xs"], i_fp["l_f"], A_PPOLY_TIE_BOT, Y_A_PBOT)
    tie_poly_fingers(h, cx_fp, i_fp["g_xs"], i_fp["l_f"], A_PPOLY_TIE_TOP, Y_A_PTOP)
    gx_fp = grid(cx_fp - 0.84)
    gx_fp2 = grid(cx_fp + 0.84)
    for gxf in (gx_fp, gx_fp2):
        h.rect("poly", grid(gxf - 0.135), grid(Y_A_T2 - 0.170), grid(gxf + 0.135), A_PPOLY_TIE_BOT[1])
        poly_cont_pad(h, gxf, Y_A_T2)
        h.pad("viali", gxf, Y_A_T2, 0.17)
        h.pad("metal1", gxf, Y_A_T2, 0.32, 0.32)
        h.rect("poly", grid(gxf - 0.135), A_PPOLY_TIE_TOP[0], grid(gxf + 0.135), grid(A_PCONT_TOP + 0.170))
        poly_cont_pad(h, gxf, A_PCONT_TOP)
        h.pad("viali", gxf, A_PCONT_TOP, 0.17)
        h.pad("metal1", gxf, A_PCONT_TOP, 0.32, 0.32)
        h.via1(gxf, Y_A_T2)
        h.via1(gxf, A_PCONT_TOP)
        h.wire("metal2", [(gxf, Y_A_T2), (gxf, A_PCONT_TOP)], W_M2)
    h.wire("metal1", [(gx_fp, A_PCONT_TOP), (gx_fp2, A_PCONT_TOP)], W_M1)
    x_inp = 2.000
    h.wire("metal1", [(x_inp, Y_A_T2), (gx_fp2, Y_A_T2)], W_M1)

    # ap_tail: Xtail.D -> Xip.S -> Xin.S horizontally along y=3.950!
    for cx_i, i_inm in ((cx_ip, i_ipn), (cx_in, i_inn)):
        for sx in i_inm["s_xs"]:
            xc = grid(cx_i + sx)
            h.pad("viali", xc, y_ap_tail, 0.17)
            h.pad("metal1", xc, y_ap_tail, 0.29)
    h.wire("metal1", [(grid(cx_tl + i_tl["d_xs"][0]), y_ap_tail), (grid(cx_in + i_inn["s_xs"][-1]), y_ap_tail)], 0.26)

    # Domain B gates:
    # Xip.G (fp on Y_A_T0) & Xin.G (fn on Y_A_T1) — double-ended dual-tap poly (top & bottom @ g_xs[0] & g_xs[-1]) via M2!
    for cx_i, i_inm, yt in ((cx_ip, i_ipn, Y_A_T0), (cx_in, i_inn, Y_A_T1)):
        tie_poly_fingers(h, cx_i, i_inm["g_xs"], i_inm["l_f"], A_NPOLY_TIE_TOP, Y_A_NTOP)
        tie_poly_fingers(h, cx_i, i_inm["g_xs"], i_inm["l_f"], A_NPOLY_TIE_BOT, Y_A_NBOT)
        xg1 = grid(cx_i + i_inm["g_xs"][0])
        xg2 = grid(cx_i + i_inm["g_xs"][-1])
        h.wire("metal1", [(xg1, A_NCONT_BOT), (xg2, A_NCONT_BOT)], W_M1)
        for xg_i in (xg1, xg2):
            h.rect("poly", grid(xg_i - 0.135), grid(A_NCONT_BOT - 0.170), grid(xg_i + 0.135), A_NPOLY_TIE_BOT[1])
            poly_cont_pad(h, xg_i, A_NCONT_BOT)
            h.pad("viali", xg_i, A_NCONT_BOT, 0.17)
            h.pad("metal1", xg_i, A_NCONT_BOT, 0.32, 0.32)
            h.via1(xg_i, A_NCONT_BOT)
            # Place top polycont right on yt (Y_A_T0 for Xip, Y_A_T1 for Xin) -> zero shared Y_A_T1 intrusion!
            h.rect("poly", grid(xg_i - 0.135), A_NPOLY_TIE_TOP[0], grid(xg_i + 0.135), grid(yt + 0.170))
            poly_cont_pad(h, xg_i, yt)
            h.pad("viali", xg_i, yt, 0.17)
            h.pad("metal1", xg_i, yt, 0.32, 0.32)
            h.via1(xg_i, yt)
            h.wire("metal2", [(xg_i, A_NCONT_BOT), (xg_i, yt)], W_M2)
        h.wire("metal1", [(x_ana_l_wall, yt), (xg2, yt)], W_M1)

    # Xlp & Xln (w_f=4, nf=8): S->VDD1 (locali + M1 source straps!);
    # G double-ended dual-tap poly: bottom @ Y_A_T2 directly (zero Y_A_T1 intrusion!), top @ d_xs[0]&d_xs[-1] via M2!
    lp_g_top = grid(cx_ip + i_ipp["d_xs"][0])
    ln_g_top = grid(cx_in + i_inp["d_xs"][0])
    for cx_i, i_pm in ((cx_ip, i_ipp), (cx_in, i_inp)):
        for sx in i_pm["s_xs"]:
            xc = grid(cx_i + sx)
            h.rect("locali", grid(xc - 0.085), grid(i_pm["c_y2"] - 0.08), grid(xc + 0.085), Y_VDD1)
        strap_m1_sources(h, cx_i, i_pm["s_xs"], grid(Y_A_PBOT + 0.650), Y_VDD1,
                         [grid(Y_A_PBOT + 0.800), grid((Y_A_PBOT + Y_A_PTOP) / 2.0), grid(Y_A_PTOP - 0.450)])
        tie_poly_fingers(h, cx_i, i_pm["g_xs"], i_pm["l_f"], A_PPOLY_TIE_BOT, Y_A_PBOT)
        tie_poly_fingers(h, cx_i, i_pm["g_xs"], i_pm["l_f"], A_PPOLY_TIE_TOP, Y_A_PTOP)
        xg_b0, xg_b1 = grid(cx_i - 0.84), grid(cx_i + 0.42)
        for xg_b in (xg_b0, xg_b1):
            h.rect("poly", grid(xg_b - 0.135), grid(Y_A_T2 - 0.170), grid(xg_b + 0.135), A_PPOLY_TIE_BOT[1])
            poly_cont_pad(h, xg_b, Y_A_T2)
            h.pad("viali", xg_b, Y_A_T2, 0.17)
            h.pad("metal1", xg_b, Y_A_T2, 0.32, 0.32)
        h.wire("metal1", [(xg_b0, Y_A_T2), (xg_b1, Y_A_T2)], W_M1)
        xg_t0 = grid(cx_i + i_pm["d_xs"][0])
        xg_t1 = grid(cx_i + i_pm["d_xs"][-1])
        for xg_top in (xg_t0, xg_t1):
            h.rect("poly", grid(xg_top - 0.135), A_PPOLY_TIE_TOP[0], grid(xg_top + 0.135), grid(A_PCONT_TOP + 0.170))
            poly_cont_pad(h, xg_top, A_PCONT_TOP)
            h.pad("viali", xg_top, A_PCONT_TOP, 0.17)
            h.pad("metal1", xg_top, A_PCONT_TOP, 0.32, 0.32)
            h.via1(xg_top, A_PCONT_TOP)
        h.wire("metal2", [(xg_t0, A_PCONT_TOP), (xg_t1, A_PCONT_TOP)], W_M2)
        h.via1(xg_b0, Y_A_T2)
        h.wire("metal2", [(xg_b0, Y_A_T2), (xg_b0, A_PCONT_TOP), (xg_t0, A_PCONT_TOP)], W_M2)

    # Xip.D + Xlp.D -> ap_mir
    ip_dxs = [grid(cx_ip + d) for d in i_ipn["d_xs"]]
    lp_dxs = [grid(cx_ip + d) for d in i_ipp["d_xs"]]
    x_mir_v = lp_dxs[-1]
    for xc in ip_dxs:
        h.pad("viali", xc, 4.750, 0.17)
        h.pad("metal1", xc, 4.750, 0.29)
    h.wire("metal1", [(min(min(ip_dxs), x_mir_v), 4.750), (max(max(ip_dxs), x_mir_v), 4.750)], W_M1)
    for xc in lp_dxs:
        h.pad("viali", xc, 7.360, 0.17)
        h.pad("metal1", xc, 7.360, 0.29)
    h.wire("metal1", [(min(lp_dxs), 7.360), (max(lp_dxs), 7.360)], W_M1)
    h.via1(x_mir_v, 4.750)
    h.via1(x_mir_v, Y_A_T2)
    h.via1(x_mir_v, 7.360)
    h.wire("metal2", [(x_mir_v, 4.750), (x_mir_v, 7.360)], W_M2)
    h.wire("metal1", [(grid(cx_ip - 0.84), Y_A_T2), (grid(cx_in + 0.42), Y_A_T2)], W_M1)

    # Xin.D + Xln.D -> ap (vertical exit right of Domain B)
    in_dxs = [grid(cx_in + d) for d in i_inn["d_xs"]]
    ln_dxs = [grid(cx_in + d) for d in i_inp["d_xs"]]
    x_ap_v = ln_dxs[-1]
    for xc in in_dxs:
        h.pad("viali", xc, 4.750, 0.17)
        h.pad("metal1", xc, 4.750, 0.29)
    h.wire("metal1", [(min(min(in_dxs), x_ap_v), 4.750), (max(max(in_dxs), x_ap_v), 4.750)], W_M1)
    for xc in ln_dxs:
        h.pad("viali", xc, 7.360, 0.17)
        h.pad("metal1", xc, 7.360, 0.29)
    h.wire("metal1", [(min(ln_dxs), 7.360), (max(ln_dxs), 7.360)], W_M1)
    h.via1(x_ap_v, 4.750)
    h.via1(x_ap_v, Y_A_T2)
    h.via1(x_ap_v, 7.360)
    h.wire("metal2", [(x_ap_v, 4.750), (x_ap_v, 7.360)], W_M2)

    ana_n_s_xs = sorted({grid(cx_sp + sx) for sx in i_sp["s_xs"]} | {grid(cx_tl + sx) for sx in i_tl["s_xs"]})
    ana_p_s_xs = sorted({grid(cx_ip + sx) for sx in i_ipp["s_xs"]} | {grid(cx_in + sx) for sx in i_inp["s_xs"]})

    return h, {
        "x_vbias": x_vbias,
        "x_inp": x_inp,
        "x_sf_gr": x_sf_gr,
        "x_cr1_p": x_cr1_p,
        "x_cr1_n": x_cr1_n,
        "x_ad": x_ad,
        "x_ana_l_wall": x_ana_l_wall,
        "x_ana_r_wall": x_ana_r_wall,
        "x_left_gr": x_left_gr,
        "x_fp_vdd_drop_l": x_fp_vdd_drop_l,
        "x_fp_vdd_drop": x_fp_vdd_drop,
        "x_ap_v": x_ap_v,
        "x_fp_vdrop_l": x_fp_vdrop_l,
        "x_fp_vdrop_r": x_fp_vdrop_r,
        "cx_fp": cx_fp,
        "x_mir_mid": x_mir_mid,
        "ana_n_s_xs": ana_n_s_xs,
        "ana_p_s_xs": ana_p_s_xs,
    }


def build_digital_half(w: Path, x_dig_l_wall: float) -> tuple[Cell, dict]:
    """Build one Digital half-chain in dy > 0 around local y=0 (embedded at Y_DIG_VSS with mirror_y=False/True)."""
    h = Cell()
    y_vss = 0.000
    y_ndiff_top = D_N_OFF
    y_t0, y_t1, y_t2 = D_T0_OFF, D_T1_OFF, D_T2_OFF
    y_pdiff_bot = D_P_OFF
    y_vdd = 7.460

    specs_c1 = [
        ("bp",  1.8, 3, 1.2, 3, 0.800),  # 5.4/3.6 pre-driver (balanced across RCX ss -40C..85C!)
        ("op",  1.2, 2, 1.2, 4, 0.340),  # 2.4/4.8 (2:1 low-Cg, balanced RCX ss +85C & -40C!)
        ("dp1", 0.8, 1, 2.4, 1, 0.340),  # K3 1.6x delay chain
        ("dp2", 0.8, 1, 2.4, 1, 0.340),
        ("dp3", 0.8, 1, 2.4, 1, 0.340),
    ]
    specs_c2 = [
        ("setb", 1.5, 2, 1.5, 2, 0.800),  # K3 wn=3.0 (1.5x2), wp=3.0 (1.5x2)
        ("seta", 1.5, 2, 1.5, 2, 0.340),
        ("qpb",  2.0, 2, 2.0, 3, 0.340),  # 4/6
        ("qpa",  2.0, 2, 2.0, 3, 0.340),
    ]
    specs_c3 = [
        ("rp1",  2.0, 1, 2.0, 3, 0.800),
        ("rp2",  1.0, 1, 1.5, 2, 0.340),
        ("bprb", 2.0, 1, 1.5, 2, 0.340),
        ("bpra", 2.0, 1, 1.5, 2, 0.340),
        ("opr",  2.0, 2, 2.0, 4, 0.340),
    ]

    dcols: dict[str, dict] = {}

    def place_group(x_start_wall: float, specs: list[tuple]) -> float:
        x_edge = x_start_wall
        for nm, n_wf, n_nf, p_wf, p_nf, gap_b in specs:
            dy_nc = grid(y_ndiff_top - n_wf / 2.0)
            dy_pc = grid(y_pdiff_bot + p_wf / 2.0)
            cn, inf_n = build_mos(w, f"d_{nm}_n", "sky130_fd_pr__nfet_01v8", n_wf, 0.15, n_nf, dy_nc, False)
            cp, inf_p = build_mos(w, f"d_{nm}_p", "sky130_fd_pr__pfet_01v8", p_wf, 0.15, p_nf, dy_pc, True)
            hw_col = max(inf_n["hw_diff"], inf_p["hw_diff"])
            cx = grid(x_edge + gap_b + hw_col)
            h.include(cn, dx=cx)
            h.include(cp, dx=cx)
            dcols[nm] = {"cx": cx, "hw": hw_col, "inf_n": inf_n, "inf_p": inf_p, "n_wf": n_wf, "p_wf": p_wf}
            x_edge = grid(cx + hw_col)
        return x_edge

    x_c1_end = place_group(x_dig_l_wall, specs_c1)
    x_c12_wall = grid(x_c1_end + 0.860)
    x_c2_end = place_group(x_c12_wall, specs_c2)
    x_c2_r_wall = grid(x_c2_end + 0.860)
    x_cr2_n = grid(x_c2_r_wall + V_TAP_WALL + 0.340)
    x_cr2_p = grid(x_cr2_n + 0.740)
    x_c3_l_wall = grid(x_cr2_p + 0.340 + V_TAP_WALL)
    x_c3_end = place_group(x_c3_l_wall, specs_c3)
    x_right_tap = grid(x_c3_end + 0.860)

    def flank(nm: str, side: int, offset: float = 0.220, x_wall: float | None = None, x_vdrop: float | None = None) -> None:
        col = dcols[nm]
        x_dn = grid(col["cx"] + side * (col["inf_n"]["hw_diff"] + offset))
        x_dp = grid(col["cx"] + side * (col["inf_p"]["hw_diff"] + offset))
        add_field_poly_dummy(h, x_dn, 0.15, grid(y_ndiff_top - col["n_wf"]), y_ndiff_top, D_NDUM_OFF, False, y_vss, x_wall=x_wall, x_vdrop=x_vdrop)
        add_field_poly_dummy(h, x_dp, 0.15, y_pdiff_bot, grid(y_pdiff_bot + col["p_wf"]), D_PDUM_OFF, True, y_vdd, x_wall=x_wall, x_vdrop=x_vdrop)

    flank("bp", -1, x_wall=x_dig_l_wall)
    flank("dp3", +1, x_wall=x_c12_wall)
    flank("setb", -1, x_wall=x_c12_wall)
    flank("qpa", +1, x_wall=x_c2_r_wall)
    flank("rp1", -1, x_wall=x_c3_l_wall)
    flank("opr", +1, x_wall=x_right_tap)

    def conn_col(cx: float, inf_n: dict, inf_p: dict, *, n_s: bool = True, p_s: bool = True, n_d: bool = True, p_d: bool = True, d_trunk_dx: float | None = None, xg_dx: float | None = None, skip_ns_m1_ge_d: bool = False) -> dict:
        if n_s:
            for sx in inf_n["s_xs"]:
                xc = grid(cx + sx)
                h.rect("locali", grid(xc - 0.085), y_vss, grid(xc + 0.085), grid(inf_n["c_y1"] + 0.08))
            ns_m1_xs = [sx for sx in inf_n["s_xs"] if not skip_ns_m1_ge_d or sx < min(inf_n["d_xs"])]
            y_ns_hi = grid(min(inf_n["c_y2"], 2.050))
            n_vys = ([grid(inf_n["c_y1"] + 0.140), grid(y_ns_hi - 0.140)]
                     if (y_ns_hi - inf_n["c_y1"]) >= 0.70 else [grid((inf_n["c_y1"] + y_ns_hi) / 2.0)])
            strap_m1_sources(h, cx, ns_m1_xs, y_vss, y_ns_hi, n_vys, width=0.22)
        if p_s:
            for sx in inf_p["s_xs"]:
                xc = grid(cx + sx)
                h.rect("locali", grid(xc - 0.085), grid(inf_p["c_y2"] - 0.08), grid(xc + 0.085), y_vdd)
            y_ps_lo = grid(max(inf_p["c_y1"], 5.100))
            p_vys = ([y_ps_lo + 0.100, grid(inf_p["c_y2"] - 0.100)]
                     if (inf_p["c_y2"] - y_ps_lo) >= 0.70 else [grid((y_ps_lo + inf_p["c_y2"]) / 2.0)])
            strap_m1_sources(h, cx, inf_p["s_xs"], y_ps_lo, y_vdd, p_vys, width=0.22)
        tie_poly_fingers(h, cx, inf_n["g_xs"], inf_n["l_f"], D_NPOLY_OFF, y_ndiff_top)
        tie_poly_fingers(h, cx, inf_p["g_xs"], inf_p["l_f"], D_PPOLY_OFF, y_pdiff_bot)

        xg = grid(cx + (inf_n["g_xs"][0] if xg_dx is None else xg_dx))
        x_sp_lo = max(grid(cx + inf_n["g_xs"][0]), grid(cx + inf_p["g_xs"][0]))
        x_sp_hi = min(grid(cx + inf_n["g_xs"][-1]), grid(cx + inf_p["g_xs"][-1]))
        x_spine = grid(min(max(xg, x_sp_lo), x_sp_hi)) if x_sp_lo <= x_sp_hi else grid(cx)
        if x_sp_lo > x_sp_hi:
            h.rect("poly", grid(min(cx + inf_n["g_xs"][0], cx + inf_p["g_xs"][0]) - 0.075), D_NPOLY_OFF[0],
                   grid(max(cx + inf_n["g_xs"][-1], cx + inf_p["g_xs"][-1]) + 0.075), D_NPOLY_OFF[1])
        h.rect("poly", grid(x_spine - 0.075), D_NPOLY_OFF[0], grid(x_spine + 0.075), D_PPOLY_OFF[1])
        poly_cont_pad(h, xg, y_t1)
        x_al, x_ar = min(grid(xg - 0.135), grid(x_spine - 0.075)), max(grid(xg + 0.135), grid(x_spine + 0.075))
        h.rect("poly", x_al, grid(y_t1 - 0.170), x_ar, grid(y_t1 + 0.170))

        n_d_abs = [grid(cx + d) for d in inf_n["d_xs"]] if n_d else []
        p_d_abs = [grid(cx + d) for d in inf_p["d_xs"]] if p_d else []
        xd = grid(cx + d_trunk_dx) if d_trunk_dx is not None else (p_d_abs[0] if p_d_abs else n_d_abs[0])
        if n_d_abs:
            for xc in n_d_abs:
                h.rect("locali", grid(xc - 0.085), grid(inf_n["c_y2"] - 0.08), grid(xc + 0.085), grid(y_t0 + 0.085))
            if len(n_d_abs) > 1 or abs(n_d_abs[0] - xd) > 1e-6:
                h.rect("locali", grid(min(min(n_d_abs), xd) - 0.085), grid(y_t0 - 0.085), grid(max(max(n_d_abs), xd) + 0.085), grid(y_t0 + 0.085))
        if p_d_abs:
            for xc in p_d_abs:
                h.rect("locali", grid(xc - 0.085), grid(y_t2 - 0.085), grid(xc + 0.085), grid(inf_p["c_y1"] + 0.08))
            if len(p_d_abs) > 1 or abs(p_d_abs[0] - xd) > 1e-6:
                h.rect("locali", grid(min(min(p_d_abs), xd) - 0.085), grid(y_t2 - 0.085), grid(max(max(p_d_abs), xd) + 0.085), grid(y_t2 + 0.085))
        if n_d_abs and p_d_abs:
            h.rect("locali", grid(xd - 0.085), grid(y_t0 - 0.085), grid(xd + 0.085), grid(y_t2 + 0.085))
        elif p_d_abs:
            h.rect("locali", grid(xd - 0.085), grid(y_t2 - 0.085), grid(xd + 0.085), grid(inf_p["c_y1"] + 0.08))
        return {"cx": cx, "xg": xg, "xd": xd,
                "n_s": [grid(cx + x) for x in inf_n["s_xs"]],
                "p_s": [grid(cx + x) for x in inf_p["s_xs"]],
                "n_d": [grid(cx + x) for x in inf_n["d_xs"]],
                "p_d": [grid(cx + x) for x in inf_p["d_xs"]]}

    def wire_nand2(b_nm: str, a_nm: str, xg_b_dx: float, xg_a_dx: float, d_a_dx: float) -> tuple[dict, dict]:
        cb, ca = dcols[b_nm], dcols[a_nm]
        wb = conn_col(cb["cx"], cb["inf_n"], cb["inf_p"], n_s=True, p_s=True, n_d=False, p_d=True,
                      d_trunk_dx=0.00 if len(cb["inf_p"]["d_xs"]) == 1 else cb["inf_p"]["d_xs"][-1], xg_dx=xg_b_dx,
                      skip_ns_m1_ge_d=True)
        wa = conn_col(ca["cx"], ca["inf_n"], ca["inf_p"], n_s=False, p_s=True, n_d=True, p_d=True,
                      d_trunk_dx=d_a_dx, xg_dx=xg_a_dx)
        ym_c = grid((max(cb["inf_n"]["c_y1"], ca["inf_n"]["c_y1"]) + min(cb["inf_n"]["c_y2"], ca["inf_n"]["c_y2"])) / 2.0)
        if len(wb["n_s"]) == 1 and len(wa["n_s"]) == 1:
            h.rect("locali", grid(wb["n_d"][-1] - 0.085), grid(ym_c - 0.12), grid(wa["n_s"][0] + 0.085), grid(ym_c + 0.12))
        else:
            mid_xs = wb["n_d"] + wa["n_s"]
            for xc in mid_xs:
                h.pad("viali", xc, ym_c, 0.17)
                h.pad("metal1", xc, ym_c, 0.29)
            h.wire("metal1", [(min(mid_xs), ym_c), (max(mid_xs), ym_c)], W_M1)
        return wb, wa

    dc_wire = {}
    all_n_s: list[float] = []
    all_p_s: list[float] = []

    def track_col(res: dict) -> dict:
        all_n_s.extend(res["n_s"])
        all_p_s.extend(res["p_s"])
        return res

    dc_wire["bp"] = track_col(conn_col(dcols["bp"]["cx"], dcols["bp"]["inf_n"], dcols["bp"]["inf_p"],
                                       xg_dx=dcols["bp"]["inf_p"]["g_xs"][0],
                                       d_trunk_dx=dcols["bp"]["inf_p"]["d_xs"][-1]))
    dc_wire["op"] = track_col(conn_col(dcols["op"]["cx"], dcols["op"]["inf_n"], dcols["op"]["inf_p"],
                                       xg_dx=dcols["op"]["inf_p"]["g_xs"][0],
                                       d_trunk_dx=dcols["op"]["inf_p"]["d_xs"][-1]))
    for dnm in ("dp1", "dp2", "dp3"):
        dc_wire[dnm] = track_col(conn_col(dcols[dnm]["cx"], dcols[dnm]["inf_n"], dcols[dnm]["inf_p"], xg_dx=-0.22, d_trunk_dx=+0.22))
    wb_set, wa_set = wire_nand2("setb", "seta", -0.38, -0.38, 0.00)
    wb_qp, wa_qp = wire_nand2("qpb", "qpa", -0.64, -0.64, -0.24)
    all_n_s.extend(wb_set["n_s"] + wb_qp["n_s"])
    all_p_s.extend(wb_set["p_s"] + wa_set["p_s"] + wb_qp["p_s"] + wa_qp["p_s"])
    dc_wire["setb"], dc_wire["seta"] = wb_set, wa_set
    dc_wire["qpb"], dc_wire["qpa"] = wb_qp, wa_qp
    dc_wire["rp1"] = track_col(conn_col(dcols["rp1"]["cx"], dcols["rp1"]["inf_n"], dcols["rp1"]["inf_p"], xg_dx=-0.64, d_trunk_dx=+0.72))
    dc_wire["rp2"] = track_col(conn_col(dcols["rp2"]["cx"], dcols["rp2"]["inf_n"], dcols["rp2"]["inf_p"], xg_dx=-0.38,
                                        d_trunk_dx=dcols["rp2"]["inf_n"]["d_xs"][0]))
    wb_bpr, wa_bpr = wire_nand2("bprb", "bpra", -0.38, -0.38, 0.00)
    all_n_s.extend(wb_bpr["n_s"])
    all_p_s.extend(wb_bpr["p_s"] + wa_bpr["p_s"])
    dc_wire["bprb"], dc_wire["bpra"] = wb_bpr, wa_bpr
    dc_wire["opr"] = track_col(conn_col(dcols["opr"]["cx"], dcols["opr"]["inf_n"], dcols["opr"]["inf_p"], xg_dx=-0.64, d_trunk_dx=0.00))

    tapped_pts: set[tuple[float, float]] = set()

    def m1_tap(x: float, y_src: float, y_trk: float) -> None:
        key = (grid(x), grid(y_src))
        if key not in tapped_pts:
            h.pad("viali", x, y_src, 0.17)
            h.pad("metal1", x, y_src, 0.24, 0.29)
            tapped_pts.add(key)
        if abs(y_src - y_trk) > 1e-6:
            h.wire("metal1", [(x, y_src), (x, y_trk)], W_M1)

    def m1_hop(x1: float, x2: float, y: float = y_t1) -> None:
        m1_tap(x1, y, y)
        m1_tap(x2, y, y)
        h.wire("metal1", [(x1, y), (x2, y)], W_M1)

    # bp.G tapped at y_t1 + 2nd polycont strap @ g_xs[1] (0.72um clear of xd=+0.72!) to crush RCX a_4368 poly R;
    # similarly op.G dual-tapped @ g_xs[0] (-0.72) and g_xs[1] (-0.24), 0.72um clear of op.xd (+0.48)!
    xg_bp2 = grid(dcols["bp"]["cx"] + dcols["bp"]["inf_p"]["g_xs"][1])
    poly_cont_pad(h, xg_bp2, y_t1)
    h.rect("poly", grid(dc_wire["bp"]["xg"] - 0.135), grid(y_t1 - 0.170), grid(xg_bp2 + 0.135), grid(y_t1 + 0.170))
    m1_hop(dc_wire["bp"]["xg"], xg_bp2)

    xg_op2 = grid(dcols["op"]["cx"] + dcols["op"]["inf_p"]["g_xs"][1])
    poly_cont_pad(h, xg_op2, y_t1)
    h.rect("poly", grid(dc_wire["op"]["xg"] - 0.135), grid(y_t1 - 0.170), grid(xg_op2 + 0.135), grid(y_t1 + 0.170))
    m1_hop(dc_wire["op"]["xg"], xg_op2)
    m1_hop(dc_wire["bp"]["xd"], dc_wire["op"]["xg"])

    m1_hop(dc_wire["op"]["xd"], dc_wire["dp1"]["xg"])
    # Jump rawp from dp1.G -> seta.G on M2 so dp1->dp2->dp3->setb stay 100% on M1 at y_t1!
    m1_tap(dc_wire["seta"]["xg"], y_t1, y_t1)
    h.via1(dc_wire["dp1"]["xg"], y_t1)
    h.via1(dc_wire["seta"]["xg"], y_t1)
    h.wire("metal2", [(dc_wire["dp1"]["xg"], y_t1), (dc_wire["seta"]["xg"], y_t1)], W_M2)

    m1_hop(dc_wire["dp1"]["xd"], dc_wire["dp2"]["xg"])
    m1_hop(dc_wire["dp2"]["xd"], dc_wire["dp3"]["xg"])
    m1_hop(dc_wire["dp3"]["xd"], dc_wire["setb"]["xg"])

    # set_b -> y_t2 -> qpa.G
    m1_tap(wb_set["xd"], 4.620, y_t2)
    m1_tap(wa_set["xd"], y_t2, y_t2)
    h.rect("locali", grid(dc_wire["qpa"]["xg"] - 0.085), grid(y_t1 - 0.085), grid(dc_wire["qpa"]["xg"] + 0.085), grid(y_t2 + 0.085))
    m1_tap(dc_wire["qpa"]["xg"], y_t2, y_t2)
    h.wire("metal1", [(wb_set["xd"], y_t2), (dc_wire["qpa"]["xg"], y_t2)], W_M1)

    # qp -> y_t0 -> cr2_n & rp1.G & bpra.G
    x_qpb_pd, x_qpa_pd = wb_qp["p_d"][-1], wa_qp["xd"]
    for xc in (x_qpb_pd, x_qpa_pd):
        h.pad("viali", xc, 4.620, 0.17)
        h.pad("metal1", xc, 4.620, 0.24, 0.29)
    h.wire("metal1", [(x_qpb_pd, 4.620), (x_qpa_pd, 4.620)], W_M1)
    h.pad("viali", x_qpa_pd, y_t0, 0.17)
    h.pad("metal1", x_qpa_pd, y_t0, 0.24, 0.29)
    m1_tap(dc_wire["rp1"]["xg"], y_t1, y_t0)
    h.rect("locali", grid(dc_wire["bpra"]["xg"] - 0.085), grid(y_t0 - 0.085), grid(dc_wire["bpra"]["xg"] + 0.085), grid(y_t1 + 0.085))
    m1_tap(dc_wire["bpra"]["xg"], y_t0, y_t0)
    h.wire("metal1", [(x_qpa_pd, y_t0), (dc_wire["bpra"]["xg"], y_t0)], W_M1)

    # qpb.G on y_t1 up to x_c2_r_wall (top-level extends P->cr2_p, N->cr2_n)
    m1_tap(dc_wire["qpb"]["xg"], y_t1, y_t1)
    h.wire("metal1", [(dc_wire["qpb"]["xg"], y_t1), (x_c2_r_wall, y_t1)], W_M1)

    m1_hop(dc_wire["rp1"]["xd"], dc_wire["rp2"]["xg"])
    m1_tap(dc_wire["rp2"]["xd"], y_t2, y_t2)
    h.rect("locali", grid(dc_wire["bprb"]["xg"] - 0.085), grid(y_t1 - 0.085), grid(dc_wire["bprb"]["xg"] + 0.085), grid(y_t2 + 0.085))
    m1_tap(dc_wire["bprb"]["xg"], y_t2, y_t2)
    h.wire("metal1", [(dc_wire["rp2"]["xd"], y_t2), (dc_wire["bprb"]["xg"], y_t2)], W_M1)

    for xc in (wb_bpr["xd"], wa_bpr["xd"]):
        h.pad("viali", xc, 4.620, 0.17)
        h.pad("metal1", xc, 4.620, 0.24, 0.29)
    h.wire("metal1", [(wb_bpr["xd"], 4.620), (wa_bpr["xd"], 4.620)], W_M1)
    m1_hop(wa_bpr["xd"], dc_wire["opr"]["xg"])

    x_out_port = grid(x_right_tap + 0.940)
    m1_tap(dc_wire["opr"]["xd"], y_t1, y_t1)
    h.wire("metal1", [(dc_wire["opr"]["xd"], y_t1), (x_out_port, y_t1)], W_M1)

    return h, {
        "x_bp_g": dc_wire["bp"]["xg"],
        "y_t0": y_t0,
        "y_t1": y_t1,
        "y_t2": y_t2,
        "x_c12_wall": x_c12_wall,
        "x_c2_r_wall": x_c2_r_wall,
        "x_cr2_n": x_cr2_n,
        "x_cr2_p": x_cr2_p,
        "x_c3_l_wall": x_c3_l_wall,
        "x_right_tap": x_right_tap,
        "x_out_port": x_out_port,
        "n_s_xs": sorted(set(all_n_s)),
        "p_s_xs": sorted(set(all_p_s)),
    }


def build_cml_to_cmos_r4(out: Path) -> dict:
    cell = "serdes_cml_to_cmos_r4_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    ana_half, am = build_analog_half(w)
    x_dig_l_wall = grid(am["x_ana_r_wall"] + 1.100)
    dig_half, dm = build_digital_half(w, x_dig_l_wall)

    c = Cell()
    c.include(ana_half, mirror_y=False)  # Analog P (y > 0)
    c.include(ana_half, mirror_y=True)   # Analog N (y < 0)
    c.include(dig_half, mirror_y=False)  # Digital P (y > 0, straight 1D continuation!)
    c.include(dig_half, mirror_y=True)   # Digital N (y < 0, exact mirror symmetry!)

    x_rail_l = 0.180
    x_ana_rail_r = grid(am["x_ana_r_wall"] + V_TAP_WALL + 0.160)
    x_dig_rail_r = grid(dm["x_right_tap"] + V_TAP_EDGE + 0.160)
    x_end = grid(dm["x_out_port"] + 0.450)

    # Wells: Analog (-13.65..+13.65) -> seamless bridge -> Digital (-7.91..+7.91)
    x_wl, x_wr = -0.140, grid(max(x_dig_rail_r, x_end) + 0.250)
    x_ana_well_r = grid(x_ana_rail_r + 0.250)
    x_dig_well_l = grid(x_dig_l_wall - V_TAP_EDGE - 0.220)
    c.rect("pwell", x_wl, grid(-Y_A_TOP_GR - 0.250), am["x_ad"], grid(Y_A_TOP_GR + 0.250))
    c.rect("pwell", am["x_ad"], -Y_A_WELL, x_ana_well_r, Y_A_WELL)
    c.rect("nwell", am["x_ad"], Y_A_WELL, x_ana_well_r, grid(Y_VDD1 + 0.450))
    c.rect("nwell", am["x_ad"], grid(-Y_VDD1 - 0.450), x_ana_well_r, -Y_A_WELL)
    # Continuous VDD-tied nwell bridge above +Y_A_WELL / below -Y_A_WELL (clear of Analog psubdiff!)
    c.rect("nwell", grid(am["x_ana_r_wall"] - 0.100), Y_A_WELL, grid(x_dig_well_l + 0.200), grid(Y_VDD_DIG + 0.450))
    c.rect("nwell", grid(am["x_ana_r_wall"] - 0.100), grid(-Y_VDD_DIG - 0.450), grid(x_dig_well_l + 0.200), -Y_A_WELL)
    # Digital stepped wells (compact height +-7.91 um centered around y=0!)
    c.rect("pwell", x_dig_well_l, grid(-dm["y_t1"]), x_wr, grid(+dm["y_t1"]))
    c.rect("nwell", x_dig_well_l, grid(+dm["y_t1"]), x_wr, grid(Y_VDD_DIG + 0.450))
    c.rect("nwell", x_dig_well_l, grid(-Y_VDD_DIG - 0.450), x_wr, grid(-dm["y_t1"]))

    # Analog Guard Rings & Vertical NP Walls
    xl = am["x_left_gr"]
    for sgn in (+1, -1):
        draw_tap_h(c, "psubdiff", x_rail_l, grid(am["x_sf_gr"] + V_TAP_WALL), sgn * Y_A_TOP_GR, half_w=H_TAP_VSS)
        c.wire("metal1", [(x_rail_l, sgn * Y_A_TOP_GR), (grid(am["x_sf_gr"] + V_TAP_WALL), sgn * Y_A_TOP_GR)], W_PWR_M1)
        for xv in (xl, am["x_fp_vdrop_l"], am["cx_fp"], am["x_fp_vdrop_r"], am["x_sf_gr"]):
            viali_on_rail(c, xv, sgn * Y_A_TOP_GR)
        draw_tap_v(c, "psubdiff", xl, 0.000 if sgn > 0 else -Y_A_TOP_GR, Y_A_TOP_GR if sgn > 0 else 0.000, half_w=V_TAP_EDGE)
        draw_tap_v(c, "psubdiff", am["x_sf_gr"], 0.000 if sgn > 0 else -Y_A_TOP_GR, Y_A_TOP_GR if sgn > 0 else 0.000, half_w=V_TAP_WALL)
        if sgn > 0:
            draw_np_wall_band(c, am["x_ana_l_wall"], Y_ANA_VSS, Y_A_T1, Y_VDD1, half_w=V_TAP_WALL)
            draw_np_wall_band(c, am["x_ana_r_wall"], Y_ANA_VSS, Y_A_T1, Y_VDD1, half_w=V_TAP_WALL)
        else:
            draw_np_wall_band(c, am["x_ana_l_wall"], Y_ANA_VSS, -Y_A_T1, -Y_VDD1, half_w=V_TAP_WALL)
            draw_np_wall_band(c, am["x_ana_r_wall"], Y_ANA_VSS, -Y_A_T1, -Y_VDD1, half_w=V_TAP_WALL)

    # Digital Vertical NP walls around center Y_ANA_VSS = 0.000
    for xw, hw_w in ((x_dig_l_wall, V_TAP_EDGE), (dm["x_c12_wall"], V_TAP_WALL), (dm["x_c2_r_wall"], V_TAP_WALL), (dm["x_c3_l_wall"], V_TAP_WALL), (dm["x_right_tap"], V_TAP_EDGE)):
        draw_np_wall_band(c, xw, Y_ANA_VSS, +dm["y_t1"], +Y_VDD_DIG, half_w=hw_w)
        draw_np_wall_band(c, xw, Y_ANA_VSS, -dm["y_t1"], -Y_VDD_DIG, half_w=hw_w)

    # Center Shared VSS Rail (0.000): psubdiff + M1 + continuous wide M2 (0.70 um) across ENTIRE chip!
    x_ap_drop = grid(am["x_ana_r_wall"] + 0.550)
    ana_walls = [xl, am["x_sf_gr"], am["x_ana_l_wall"], am["x_ana_r_wall"], am["x_fp_vdd_drop"]]
    dig_walls = [x_dig_l_wall, dm["x_c12_wall"], dm["x_c2_r_wall"], dm["x_c3_l_wall"], dm["x_right_tap"]]
    all_walls = ana_walls + dig_walls + [x_ap_drop]

    draw_tap_h(c, "psubdiff", x_rail_l, x_dig_rail_r, Y_ANA_VSS, half_w=H_TAP_VSS)
    c.wire("metal1", [(x_rail_l, Y_ANA_VSS), (x_dig_rail_r, Y_ANA_VSS)], W_PWR_M1)
    c.wire("metal2", [(x_rail_l, Y_ANA_VSS), (x_dig_rail_r, Y_ANA_VSS)], 0.56)
    # Add low-R M3 segments along Y=0 where cr1/cr2/vbias M3 bridges do not cross, + central VSS M3 pin @ x_dig_l_wall!
    x_vss_ana_m3_l = grid(am["x_ana_l_wall"] + 0.780)
    x_vss_ana_m3_r = grid(am["x_ana_r_wall"] - 1.000)
    x_vss_dig_m3_r = grid(dm["x_c2_r_wall"] - 0.400)
    c.wire("metal3", [(x_vss_ana_m3_l, Y_ANA_VSS), (x_vss_ana_m3_r, Y_ANA_VSS)], 0.56)
    c.wire("metal3", [(x_dig_l_wall, Y_ANA_VSS), (x_vss_dig_m3_r, Y_ANA_VSS)], 0.56)
    c.pad("metal3", x_dig_l_wall, Y_ANA_VSS, 0.56, 0.64)
    all_vss_via2_xs = [x_dig_l_wall]
    for sx in dm["n_s_xs"] + am["ana_n_s_xs"]:
        c.pad("viali", sx, Y_ANA_VSS, 0.17)
        if all(abs(sx - ax) > 0.75 for ax in all_walls):
            c.via1(sx, Y_ANA_VSS)
            if ((x_vss_ana_m3_l + 0.25 <= sx <= x_vss_ana_m3_r - 0.25) or (x_dig_l_wall + 0.25 <= sx <= x_vss_dig_m3_r - 0.25)) and all(abs(sx - vx2) > 0.45 for vx2 in all_vss_via2_xs):
                c.via2(sx, Y_ANA_VSS)
                all_vss_via2_xs.append(sx)
    all_vss_sxs = dm["n_s_xs"] + am["ana_n_s_xs"]
    for k in range(44):
        vx = grid(xl + 0.85 + k * (dm["x_right_tap"] - xl - 1.70) / 43)
        if all(abs(vx - ax) > 0.75 for ax in all_walls) and all(abs(vx - sx) > 0.36 for sx in all_vss_sxs):
            viali_on_rail(c, vx, Y_ANA_VSS)
            c.via1(vx, Y_ANA_VSS)
            if ((x_vss_ana_m3_l + 0.25 <= vx <= x_vss_ana_m3_r - 0.25) or (x_dig_l_wall + 0.25 <= vx <= x_vss_dig_m3_r - 0.25)) and all(abs(vx - vx2) > 0.45 for vx2 in all_vss_via2_xs):
                c.via2(vx, Y_ANA_VSS)
                all_vss_via2_xs.append(vx)

    # Analog VDD Rails (+-13.200): M1 + M2 + M3 strapped from xl -> x_ana_rail_r so West M4 trunk ties +-13.20 cleanly!
    draw_tap_h(c, "nsubdiff", grid(am["x_ana_l_wall"] - V_TAP_WALL), x_ana_rail_r, -Y_VDD1, half_w=H_TAP_VDD)
    c.wire("metal1", [(x_rail_l, -Y_VDD1), (x_ana_rail_r, -Y_VDD1)], W_PWR_M1)
    c.wire("metal2", [(x_rail_l, -Y_VDD1), (x_ana_rail_r, -Y_VDD1)], W_PWR_M2)
    c.wire("metal3", [(x_rail_l, -Y_VDD1), (x_ana_rail_r, -Y_VDD1)], W_PWR_M3)
    draw_tap_h(c, "nsubdiff", grid(am["x_ad"] + 0.200), x_ana_rail_r, +Y_VDD1, half_w=H_TAP_VDD)
    c.wire("metal1", [(x_rail_l, +Y_VDD1), (x_ana_rail_r, +Y_VDD1)], W_PWR_M1)
    c.wire("metal2", [(x_rail_l, +Y_VDD1), (x_ana_rail_r, +Y_VDD1)], W_PWR_M2)
    c.wire("metal3", [(x_rail_l, +Y_VDD1), (x_ana_rail_r, +Y_VDD1)], W_PWR_M3)
    for sgn in (+1, -1):
        yv = sgn * Y_VDD1
        c.via1(xl, yv)
        c.via2(xl, yv)
        for xfvd in (am["x_fp_vdd_drop_l"], am["x_fp_vdd_drop"]):
            c.via1(xfvd, yv)
            c.via2(xfvd, yv)
        for sx in am["ana_p_s_xs"]:
            viali_on_rail(c, sx, yv)
            c.via1(sx, yv)
            c.via2(sx, yv)
        for k in range(10):
            vx = grid(am["x_ana_l_wall"] + 0.85 + k * (am["x_ana_r_wall"] - am["x_ana_l_wall"] - 1.70) / 9)
            if all(abs(vx - ax) > 0.75 for ax in ana_walls) and all(abs(vx - sx) > 0.42 for sx in am["ana_p_s_xs"]):
                viali_on_rail(c, vx, yv)
                c.via1(vx, yv)
                c.via2(vx, yv)

    # Digital Compact VDD Rails (+-7.460): nsubdiff + M1 + M2 + M3 (M3 tied to Analog VDD spine @ x_ana_r_wall!)
    x_dig_vdd_l = grid(x_dig_l_wall - V_TAP_EDGE)
    dig_vdd_m2_walls = [am["x_ana_r_wall"], dm["x_right_tap"]]
    for sgn in (+1, -1):
        yv = sgn * Y_VDD_DIG
        draw_tap_h(c, "nsubdiff", x_dig_vdd_l, x_dig_rail_r, yv, half_w=H_TAP_VDD)
        c.wire("metal1", [(x_dig_vdd_l, yv), (x_dig_rail_r, yv)], W_PWR_M1)
        c.wire("metal2", [(x_dig_vdd_l, yv), (x_dig_rail_r, yv)], W_PWR_M2)
        c.wire("metal3", [(am["x_ana_r_wall"], yv), (x_dig_rail_r, yv)], W_PWR_M3)
        for sx in dm["p_s_xs"]:
            c.pad("viali", sx, yv, 0.17)
            if all(abs(sx - ax) > 0.45 for ax in dig_vdd_m2_walls):
                c.via1(sx, yv)
                c.via2(sx, yv)
        for k in range(28):
            vx = grid(x_dig_l_wall + 0.85 + k * (dm["x_right_tap"] - x_dig_l_wall - 1.70) / 27)
            if all(abs(vx - ax) > 0.75 for ax in all_walls) and all(abs(vx - sx) > 0.42 for sx in dm["p_s_xs"]):
                viali_on_rail(c, vx, yv)
                c.via1(vx, yv)
                c.via2(vx, yv)

    # Vertical Power Spines:
    # - Analog Left VSS M2 trunk + central x_dig_l_wall VSS M1/M2/M3/M4 convergence
    for yv in (-Y_A_TOP_GR, Y_ANA_VSS, +Y_A_TOP_GR):
        c.via1(xl, yv)
    c.wire("metal2", [(xl, -Y_A_TOP_GR), (xl, +Y_A_TOP_GR)], 0.60)
    c.via1(x_dig_l_wall, Y_ANA_VSS)
    c.via2(x_dig_l_wall, Y_ANA_VSS)

    # - Central VDD M3 Spine @ x_ana_r_wall tying Analog (+-13.20) <-> Digital (+-7.46) seamlessly!
    xa_r = am["x_ana_r_wall"]
    for yv in (-Y_VDD1, +Y_VDD1, -Y_VDD_DIG, +Y_VDD_DIG):
        c.via1(xa_r, yv) if abs(yv) == Y_VDD1 else None
        c.via2(xa_r, yv) if abs(yv) == Y_VDD1 else None
        via3_pad(c, xa_r, yv)
    c.wire("metal3", [(xa_r, -Y_VDD1), (xa_r, +Y_VDD1)], 0.80)
    # - East Digital VDD M3+M4 Spine @ x_right_tap tying -7.46 <-> +7.46 (outp/outn pass cleanly underneath on M1!)
    xr_t = dm["x_right_tap"]
    for yv in (-Y_VDD_DIG, +Y_VDD_DIG):
        c.via1(xr_t, yv)
        c.via2(xr_t, yv)
        via3_pad(c, xr_t, yv)
    c.wire("metal3", [(xr_t, -Y_VDD_DIG), (xr_t, +Y_VDD_DIG)], 0.60)
    c.wire("metal4", [(xr_t, -Y_VDD_DIG), (xr_t, +Y_VDD_DIG)], 0.80)

    # M4 Perimeter-Only Multi-Feed VDD Ring (West xl, Center xa_r, East xr_t; ZERO M4 crossing over Analog signals!)
    # + Digital M4 VSS bus @ y=0 cleanly inside [x_dig_l_wall + 0.50 .. x_vss_dig_m3_r]!
    x_vss_dig_m4_l = grid(x_dig_l_wall + 0.500)
    x_vss_dig_m4_r = grid(min(x_vss_dig_m3_r, xr_t - 1.500))
    c.wire("metal4", [(x_vss_dig_m4_l, Y_ANA_VSS), (x_vss_dig_m4_r, Y_ANA_VSS)], 0.80)
    for xv in (x_vss_dig_m4_l + 0.10, x_dig_l_wall + 4.0, x_dig_l_wall + 8.5, x_dig_l_wall + 13.5):
        xg = grid(xv)
        if x_vss_dig_m4_l <= xg <= x_vss_dig_m4_r - 0.25:
            via3_pad(c, xg, Y_ANA_VSS)

    # Vertical VDD M4 trunks ONLY on xa_r (Center) and xr_t (East) -> zero M4 near inp/vbias or over fp/fn!
    c.wire("metal4", [(xa_r, -Y_VDD1), (xa_r, +Y_VDD1)], 1.20)
    c.wire("metal4", [(xr_t, -Y_VDD_DIG), (xr_t, +Y_VDD_DIG)], 1.00)

    # Wide M4 horizontal VDD buses (+-Y_VDD1 & +-Y_VDD_DIG) with paired 2x via3 drops!
    for sgn in (+1, -1):
        ya, yd = sgn * Y_VDD1, sgn * Y_VDD_DIG
        c.wire("metal4", [(am["x_fp_vdd_drop_l"], ya), (xa_r, ya)], 1.20)
        c.wire("metal4", [(xa_r, yd), (xr_t, yd)], 1.20)
        for xv in (am["x_fp_vdd_drop_l"], am["x_fp_vdd_drop"], am["ana_p_s_xs"][1], am["ana_p_s_xs"][-2], xa_r):
            xg = grid(xv)
            via3_pad(c, xg, grid(ya - 0.24))
            via3_pad(c, xg, grid(ya + 0.24))
        for xv in (xa_r, grid(x_dig_l_wall + 2.20), grid(x_dig_l_wall + 6.50), grid(dm["x_c12_wall"] + 2.00), grid(dm["x_c2_r_wall"] - 1.50), xr_t):
            via3_pad(c, xv, grid(yd - 0.24))
            via3_pad(c, xv, grid(yd + 0.24))

    # Short Straight-Through Bridge: ap/an (Domain B +-6.80) -> bp.G/bn.G (+-3.40) (~5.5 um total!)
    for sgn in (+1, -1):
        c.wire("metal1", [(am["x_ap_v"], sgn * Y_A_T2), (x_ap_drop, sgn * Y_A_T2)], W_M1)
        c.via1(x_ap_drop, sgn * Y_A_T2)
        c.wire("metal2", [(x_ap_drop, sgn * Y_A_T2), (x_ap_drop, sgn * dm["y_t1"]), (dm["x_bp_g"], sgn * dm["y_t1"])], W_M2)
        c.via1(dm["x_bp_g"], sgn * dm["y_t1"])

    # vbias tie on M3 across y=0
    x_vb = am["x_vbias"]
    for yb in (-Y_A_T1, +Y_A_T1):
        c.via1(x_vb, yb)
        c.via2(x_vb, yb)
    c.wire("metal3", [(x_vb, -Y_A_T1), (x_vb, +Y_A_T1)], W_M3)
    c.pad("metal3", x_vb, +Y_A_T1, 0.40, 0.60)

    # cr1 (fp/fn) M3 crossover inside Analog gap [x_sf_gr .. x_ana_l_wall]
    x1p, x1n = am["x_cr1_p"], am["x_cr1_n"]
    c.wire("metal1", [(am["x_sf_gr"], +Y_A_T0), (x1p, +Y_A_T0)], W_M1)
    c.wire("metal1", [(am["x_sf_gr"], -Y_A_T0), (x1n, -Y_A_T0)], W_M1)
    c.wire("metal1", [(x1n, +Y_A_T1), (am["x_ana_l_wall"], +Y_A_T1)], W_M1)
    c.wire("metal1", [(x1p, -Y_A_T1), (am["x_ana_l_wall"], -Y_A_T1)], W_M1)
    c.wire("metal1", [(x1p, +Y_A_T0), (am["x_ana_l_wall"], +Y_A_T0)], W_M1)
    c.wire("metal1", [(x1n, -Y_A_T0), (am["x_ana_l_wall"], -Y_A_T0)], W_M1)
    for x_cr, y_s, y_d in ((x1p, +Y_A_T0, -Y_A_T1), (x1n, -Y_A_T0, +Y_A_T1)):
        c.via1(x_cr, y_s)
        c.via2(x_cr, y_s)
        c.via1(x_cr, y_d)
        c.via2(x_cr, y_d)
        c.wire("metal3", [(x_cr, y_s), (x_cr, y_d)], W_M3)

    # cr2 (qp/qn) M3 crossover across y=0 inside Digital gap [x_c2_r_wall .. x_c3_l_wall]
    y_qp_t0_p, y_qp_t0_n = +dm["y_t0"], -dm["y_t0"]
    y_qp_t1_p, y_qp_t1_n = +dm["y_t1"], -dm["y_t1"]
    x2n, x2p = dm["x_cr2_n"], dm["x_cr2_p"]
    c.wire("metal1", [(dm["x_c2_r_wall"], y_qp_t1_p), (x2p, y_qp_t1_p)], W_M1)
    c.wire("metal1", [(dm["x_c2_r_wall"], y_qp_t1_n), (x2n, y_qp_t1_n)], W_M1)
    for x_cr, y_s, y_d in ((x2n, y_qp_t0_p, y_qp_t1_n), (x2p, y_qp_t0_n, y_qp_t1_p)):
        c.via1(x_cr, y_s)
        c.via2(x_cr, y_s)
        c.via1(x_cr, y_d)
        c.via2(x_cr, y_d)
        c.wire("metal3", [(x_cr, y_s), (x_cr, y_d)], W_M3)

    # Input (West) & Output (East) M3 ports
    x_inp = am["x_inp"]
    x_out = dm["x_out_port"]
    for xp, yp in ((x_inp, +Y_A_T2), (x_inp, -Y_A_T2), (x_out, +dm["y_t1"]), (x_out, -dm["y_t1"])):
        c.via1(xp, yp)
        c.via2(xp, yp)
        c.pad("metal3", xp, yp, 0.40, 0.60)

    c.port("inp", "metal3", x_inp, +Y_A_T2)
    c.port("inn", "metal3", x_inp, -Y_A_T2)
    c.port("outp", "metal3", x_out, +dm["y_t1"])
    c.port("outn", "metal3", x_out, -dm["y_t1"])
    c.port("vbias", "metal3", x_vb, +Y_A_T1)
    c.port("vdd", "metal4", xa_r, +Y_VDD_DIG)
    c.port("vss", "metal4", x_vss_dig_m4_l, Y_ANA_VSS)
    c.write(w / f"{cell}.mag")

    def inv_lines(inst: str, inp: str, outp: str, wn: float, wp: float) -> list[str]:
        return [
            f"X{inst}_n {outp} {inp} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{inst}_p {outp} {inp} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
        ]

    def nand_lines(inst: str, a: str, b: str, outp: str, wn: float, wp: float) -> list[str]:
        return [
            f"X{inst}_nt {outp} {a} {inst}_mid vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{inst}_nb {inst}_mid {b} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{inst}_pa {outp} {a} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{inst}_pb {outp} {b} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
        ]

    ref_lines = [
        "* Physical LVS reference for serdes_cml_to_cmos_r4_pdk (v3/K3 stacked 2-strip)",
        f".subckt {cell} inp inn outp outn vbias vdd vss",
        "Xfp vdd inp fp vss sky130_fd_pr__nfet_01v8_lvt w=32 l=0.15",
        "Xfn vdd inn fn vss sky130_fd_pr__nfet_01v8_lvt w=32 l=0.15",
        "Xsp fp vbias vss vss sky130_fd_pr__nfet_01v8 w=3 l=0.5",
        "Xsn fn vbias vss vss sky130_fd_pr__nfet_01v8 w=3 l=0.5",
        "Xap_ip ap_mir fp ap_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xap_in ap fn ap_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xap_lp ap_mir ap_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xap_ln ap ap_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xap_t ap_tail vbias vss vss sky130_fd_pr__nfet_01v8 w=32 l=0.5",
        "Xan_ip an_mir fn an_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xan_in an fp an_tail vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15",
        "Xan_lp an_mir an_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xan_ln an an_mir vdd vdd sky130_fd_pr__pfet_01v8 w=32 l=0.15",
        "Xan_t an_tail vbias vss vss sky130_fd_pr__nfet_01v8 w=32 l=0.5",
        *inv_lines("bp", "ap", "bp", 5.4, 3.6),
        *inv_lines("bn", "an", "bn", 5.4, 3.6),
        *inv_lines("op", "bp", "rawp", 2.4, 4.8),
        *inv_lines("on", "bn", "rawn", 2.4, 4.8),
        *inv_lines("dp1", "rawp", "dp1", 0.8, 2.4),
        *inv_lines("dp2", "dp1", "dp2", 0.8, 2.4),
        *inv_lines("dp3", "dp2", "dp3", 0.8, 2.4),
        *inv_lines("dn1", "rawn", "dn1", 0.8, 2.4),
        *inv_lines("dn2", "dn1", "dn2", 0.8, 2.4),
        *inv_lines("dn3", "dn2", "dn3", 0.8, 2.4),
        *nand_lines("set", "rawp", "dp3", "set_b", 3, 3),
        *nand_lines("rst", "rawn", "dn3", "reset_b", 3, 3),
        *nand_lines("qp", "set_b", "qn", "qp", 4, 6),
        *nand_lines("qn", "reset_b", "qp", "qn", 4, 6),
        *inv_lines("rp1", "qp", "rp1", 2, 6),
        *inv_lines("rp2", "rp1", "rp2", 1, 3),
        *inv_lines("rn1", "qn", "rn1", 2, 6),
        *inv_lines("rn2", "rn1", "rn2", 1, 3),
        *nand_lines("bpr", "qp", "rp2", "bp_r", 2, 3),
        *nand_lines("bnr", "qn", "rn2", "bn_r", 2, 3),
        *inv_lines("opr", "bp_r", "outp", 4, 8),
        *inv_lines("onr", "bn_r", "outn", 4, 8),
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"), str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(w / f"{cell}.mag").bbox()
    return {
        "cell": cell,
        "checker_exit": proc.returncode,
        "drc_boxes": int(drc_m[1]) if drc_m else None,
        "lvs_match": "LVS_MATCH True" in log,
        "lvs_property_errors": "LVS_PROPERTY_ERRORS True" in log,
        "exported_ports": ports_m[1].split() if ports_m else [],
        "bbox_um": [bx1, by1, bx2, by2],
        "size_um": [round(bx2 - bx1, 3), round(by2 - by1, 3)],
        "area_um2": round((bx2 - bx1) * (by2 - by1), 2),
        "extracted_models": models,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)

    r = build_cml_to_cmos_r4(out)
    print(
        f"{r['cell']:36s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | size={r['size_um']} um | area={r['area_um2']} um2",
        flush=True,
    )
    (out / "summary.json").write_text(json.dumps([r], indent=2) + "\n")
    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        cdir = out / r["cell"]
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
            src = cdir / f"{r['cell']}{ext}"
            if src.exists():
                shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
