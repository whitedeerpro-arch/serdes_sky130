#!/usr/bin/env python3
"""Build mirror-symmetric SKY130 PDK CML-to-CMOS Clock Receiver (Plan C6).

Implements ``serdes_cml_to_cmos_pvt_candidate`` from
``analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice``:
- Plan C6 architecture (Merged Domain NP Guard Rings + Biased Gate Dummies +
  Continuous Poly + Locali + 3-Track M1 Channel):
  1. Merged domain guard rings (appropriate merging + N/P unification):
     - Domain A (Analog SF + Tail: Xfp/Xfn, Xsp/Xsn, Xtail): 4-sided closed
       P-sub guard ring (``psubdiff`` + ``locali`` + ``M1(VSS)``) on left, right,
       top/bottom (y = +/-6.370 um), and center (y = 0).
     - Domain B (Analog Diff-to-SE: Xip/Xin, Xlp/Xln): merged N/P unified
       guard frame (``psubdiff`` in pwell + ``nsubdiff`` in nwell on left/right
       vertical walls, center VSS, outer +/-VDD), separated from Digital by a
       dedicated double guard-wall isolation barrier.
     - Domains C1 (bp, op, dp1..dp3), C2 (set, qp), C3 (rp1..2, bpr, opr):
       three merged N/P unified guard frames (crossover cr2 sits cleanly in the
       inter-domain gap between C2 and C3).
  2. Biased dummy gates tied to VDD (PMOS) / VSS (NMOS):
     - Shared-diffusion ``nf+2`` dummy fingers (D=S=G=B=VSS/VDD) on matched
       supply-sourced multi-finger transistors (``Xtail``, ``Xlp/Xln``, ``op``,
       ``opr``).
     - Adjacent field-poly dummy gates tied to ``VSS`` (NMOS) or ``VDD`` (PMOS)
       flanking signal-outer / domain-edge transistors (``Xfp/Xfn``, ``Xsp/Xsn``,
       ``Xip/Xin``, plus left/right boundaries of C1, C2, C3).
  3. Zero M2 in the entire Digital CMOS & Restorer core; continuous ``poly``
     gates, shared central ``polycont`` row (y = +/-3.200 um), ``locali`` stage
     hops & NAND2 bridges, 3 horizontal M1 tracks, and 2 symmetric M3 crossovers.
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

# Fixed mirrored half-chain Y coordinates (Half-height = 6.960 -> Total height = 13.920 um)
Y_VSS = 0.000
Y_NDIFF_TOP = 2.400
Y_T0 = 2.740
Y_T1 = 3.320
Y_T2 = 3.900
Y_PDIFF_BOT = 4.240
Y_WELL = 3.320
Y_VDD = 6.690
Y_TOP = 7.055

# Guard-ring half-widths (wider than 0.170 locali / 0.180-0.200 M1 so green/cyan ring borders are distinct)
H_TAP_VSS = 0.125   # 0.250 um horizontal psubdiff spine @ Y_VSS (0.275 um clear of ndiff @ 0.400)
H_TAP_VDD = 0.175   # 0.350 um horizontal top/bot tap @ Y_VDD=6.690 (0.275 um clear of diff @ 6.240; 0.190 nwell ov)
V_TAP_WALL = 0.180  # 0.360 um vertical domain guard-ring walls
V_TAP_EDGE = 0.220  # 0.440 um outer left/right vertical guard-ring walls (wider than 0.320 M2)

# Active poly tie-bar Y windows inside channel (>= 0.09 um from diff)
Y_NPOLY_TIE = (2.490, 2.640)
Y_PPOLY_TIE = (4.000, 4.150)

# Dummy polycont Y coordinates (>= 0.175 um from diff locali & >= 0.215 um poly.2 from Y_T1)
Y_NDUM_CONT = 2.765
Y_PDUM_CONT = 3.875


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def poly_cont_pad(c: Cell, x: float, y: float) -> None:
    """Place a DRC-clean poly -> polycont -> locali contact pad."""
    c.pad("poly", x, y, 0.27, 0.34)
    c.pad("polycont", x, y, 0.17, 0.17)
    c.pad("locali", x, y, 0.18, 0.34)


def draw_tap_h(c: Cell, diff_layer: str, x1: float, x2: float, y: float, half_w: float = H_TAP_VDD) -> None:
    c.rect(diff_layer, x1, grid(y - half_w), x2, grid(y + half_w))
    c.rect("locali", x1, grid(y - 0.085), x2, grid(y + 0.085))
    if (x2 - x1) >= 0.48:
        c.rect(diff_layer + "cont", grid(x1 + 0.14), grid(y - 0.085), grid(x2 - 0.14), grid(y + 0.085))


def draw_tap_v(
    c: Cell,
    diff_layer: str,
    x: float,
    y1: float,
    y2: float,
    li_y1: float | None = None,
    li_y2: float | None = None,
    half_w: float = V_TAP_WALL,
) -> None:
    c.rect(diff_layer, grid(x - half_w), grid(y1 - 0.085), grid(x + half_w), grid(y2 + 0.085))
    ly1 = grid((y1 if li_y1 is None else li_y1) - 0.085)
    ly2 = grid((y2 if li_y2 is None else li_y2) + 0.085)
    c.rect("locali", grid(x - 0.085), ly1, grid(x + 0.085), ly2)
    if (y2 - y1) >= 0.70:
        c.rect(
            diff_layer + "cont",
            grid(x - 0.085),
            grid(y1 + 0.255),
            grid(x + 0.085),
            grid(y2 - 0.255),
        )


def viali_on_rail(c: Cell, x: float, y: float) -> None:
    """Place a 0.170 viali on a thin M1 rail with local 0.30x0.24 M1 enclosure (satisfies met1.4/met1.5)."""
    c.pad("viali", x, y, 0.17, 0.17)
    c.pad("metal1", x, y, 0.30, 0.24)


def draw_np_wall(c: Cell, x: float, half_w: float = V_TAP_WALL) -> None:
    """Draw one merged N/P vertical guard-ring leg in y > 0 leaving Y_T1 open for locali hops."""
    draw_tap_v(c, "psubdiff", x, Y_VSS, 2.960, half_w=half_w)
    draw_tap_v(c, "nsubdiff", x, 3.680, Y_VDD, half_w=half_w)
    viali_on_rail(c, x, Y_VSS)
    viali_on_rail(c, x, Y_VDD)


def build_mos(
    work: Path,
    name: str,
    model: str,
    w_f: float,
    l_f: float,
    nf: int,
    dy: float,
    is_pmos: bool,
    *,
    has_sd_dummies: bool = False,
) -> tuple[Cell, dict]:
    """Generate bare MOSFET; if ``has_sd_dummies=True`` add 2 outer supply-tied dummy fingers."""
    total_nf = nf + 2 if has_sd_dummies else nf
    if has_sd_dummies and nf % 2 != 0:
        raise ValueError(f"Shared-diffusion dummy fingers require even active nf, got {nf} for {name}")
    p = pdk_device(
        work,
        name,
        model,
        dict(w=w_f, l=l_f, nf=total_nf, conn_gates=0, topc=0, botc=0, guard=0),
    )
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

    if has_sd_dummies:
        # Contacts: [c0(sup), c1(sup), c2(D), ..., c_{nf}(sup), c_{nf+1}(sup)]
        s_xs = [sds[0]] + sds[1:-1:2] + [sds[-1]]
        d_xs = sds[2:-1:2]
        dum_g_xs = [gxs[0], gxs[-1]]
        act_g_xs = gxs[1:-1]
    else:
        s_xs = sds[::2]
        d_xs = sds[1::2]
        dum_g_xs = []
        act_g_xs = gxs

    return out, {
        "w_diff": grid(diff_x2 - diff_x1),
        "hw_diff": grid((diff_x2 - diff_x1) / 2.0),
        "s_xs": s_xs,
        "d_xs": d_xs,
        "g_xs": act_g_xs,
        "dum_g_xs": dum_g_xs,
        "l_f": l_f,
        "c_y1": c_y1,
        "c_y2": c_y2,
    }


def tie_poly_fingers(
    c: Cell,
    cx: float,
    g_xs: list[float],
    l_f: float,
    y_tie: tuple[float, float],
    y_stub_edge: float,
) -> None:
    """Tie active gate fingers horizontally on poly just inside channel."""
    hw_g = grid(l_f / 2.0)
    for gx in g_xs:
        c.rect("poly", grid(cx + gx - hw_g), min(y_tie[0], y_stub_edge), grid(cx + gx + hw_g), max(y_tie[1], y_stub_edge))
    if len(g_xs) > 1:
        c.rect("poly", grid(cx + g_xs[0] - hw_g), y_tie[0], grid(cx + g_xs[-1] + hw_g), y_tie[1])


def tie_sd_dummy_gates(c: Cell, cx: float, inf: dict, is_pmos: bool) -> None:
    """Tie outer shared-diffusion dummy poly gates to outer supply contact (VSS for N, VDD for P)."""
    if not inf["dum_g_xs"]:
        return
    hw_g = grid(inf["l_f"] / 2.0)
    y_cont = Y_PDUM_CONT if is_pmos else Y_NDUM_CONT
    c_xs = (inf["s_xs"][0], inf["s_xs"][-1])
    for gx_rel, xc_rel in zip(inf["dum_g_xs"], c_xs):
        xg = grid(cx + gx_rel)
        xc = grid(cx + xc_rel)
        if is_pmos:
            c.rect("poly", grid(xg - hw_g), grid(y_cont - 0.170), grid(xg + hw_g), Y_PDIFF_BOT)
        else:
            c.rect("poly", grid(xg - hw_g), Y_NDIFF_TOP, grid(xg + hw_g), grid(y_cont + 0.170))
        poly_cont_pad(c, xg, y_cont)
        bx1 = min(grid(xg - 0.090), grid(xc - 0.085))
        bx2 = max(grid(xg + 0.090), grid(xc + 0.085))
        c.rect("locali", bx1, grid(y_cont - 0.170), bx2, grid(y_cont + 0.170))
        if is_pmos:
            c.rect("locali", grid(xc - 0.085), y_cont, grid(xc + 0.085), Y_VDD)
        else:
            c.rect("locali", grid(xc - 0.085), Y_VSS, grid(xc + 0.085), y_cont)


def add_field_poly_dummy(
    c: Cell,
    x_dum: float,
    l_f: float,
    y_diff_lo: float,
    y_diff_hi: float,
    is_pmos: bool,
    *,
    x_wall: float | None = None,
    x_vdrop: float | None = None,
    drop_locali: bool = True,
) -> None:
    """Place a biased field-poly dummy gate (with outer +0.130 um overhang) tied to VDD/VSS."""
    hw_g = grid(l_f / 2.0)
    y_cont = Y_PDUM_CONT if is_pmos else Y_NDUM_CONT
    if is_pmos:
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
        if drop_locali:
            if is_pmos:
                c.rect("locali", grid(x_vdrop - 0.085), grid(y_cont - 0.085), grid(x_vdrop + 0.085), Y_VDD)
            else:
                c.rect("locali", grid(x_vdrop - 0.085), Y_VSS, grid(x_vdrop + 0.085), grid(y_cont + 0.085))


def connect_col_locali(
    c: Cell,
    cx: float,
    inf_n: dict,
    inf_p: dict,
    *,
    n_s_vss: bool = True,
    p_s_vdd: bool = True,
    n_d_up: bool = True,
    p_d_dn: bool = True,
    bridge_d: bool = True,
    d_trunk_dx: float | None = None,
    xg_dx: float | None = None,
    poly_bridge: bool = True,
) -> dict:
    """Wire a CMOS column's gates (continuous poly + central polycont), dummies, and S/D on locali."""
    if n_s_vss:
        for sx in inf_n["s_xs"]:
            xc = grid(cx + sx)
            c.rect("locali", grid(xc - 0.085), Y_VSS, grid(xc + 0.085), grid(inf_n["c_y1"] + 0.08))
    if p_s_vdd:
        for sx in inf_p["s_xs"]:
            xc = grid(cx + sx)
            c.rect("locali", grid(xc - 0.085), grid(inf_p["c_y2"] - 0.08), grid(xc + 0.085), Y_VDD)

    # Tie active fingers + shared-diffusion outer dummy gates (G=VSS/VDD)
    tie_poly_fingers(c, cx, inf_n["g_xs"], inf_n["l_f"], Y_NPOLY_TIE, Y_NDIFF_TOP)
    tie_poly_fingers(c, cx, inf_p["g_xs"], inf_p["l_f"], Y_PPOLY_TIE, Y_PDIFF_BOT)
    tie_sd_dummy_gates(c, cx, inf_n, is_pmos=False)
    tie_sd_dummy_gates(c, cx, inf_p, is_pmos=True)

    xg = None
    if poly_bridge:
        if xg_dx is None:
            xg_dx = inf_n["g_xs"][0]
        xg = grid(cx + xg_dx)
        x_sp_lo = max(grid(cx + inf_n["g_xs"][0]), grid(cx + inf_p["g_xs"][0]))
        x_sp_hi = min(grid(cx + inf_n["g_xs"][-1]), grid(cx + inf_p["g_xs"][-1]))
        x_spine = grid(min(max(xg, x_sp_lo), x_sp_hi)) if x_sp_lo <= x_sp_hi else grid(cx)
        if x_sp_lo > x_sp_hi:
            c.rect("poly", grid(min(cx + inf_n["g_xs"][0], cx + inf_p["g_xs"][0]) - 0.075), Y_NPOLY_TIE[0],
                   grid(max(cx + inf_n["g_xs"][-1], cx + inf_p["g_xs"][-1]) + 0.075), Y_NPOLY_TIE[1])
        c.rect("poly", grid(x_spine - 0.075), Y_NPOLY_TIE[0], grid(x_spine + 0.075), Y_PPOLY_TIE[1])
        poly_cont_pad(c, xg, Y_T1)
        x_arm_l = min(grid(xg - 0.135), grid(x_spine - 0.075))
        x_arm_r = max(grid(xg + 0.135), grid(x_spine + 0.075))
        c.rect("poly", x_arm_l, grid(Y_T1 - 0.170), x_arm_r, grid(Y_T1 + 0.170))

    xd = None
    if bridge_d:
        n_d_abs = [grid(cx + d) for d in inf_n["d_xs"]] if n_d_up else []
        p_d_abs = [grid(cx + d) for d in inf_p["d_xs"]] if p_d_dn else []
        if d_trunk_dx is not None:
            xd = grid(cx + d_trunk_dx)
        elif p_d_abs:
            xd = p_d_abs[0]
        else:
            xd = n_d_abs[0]
        if n_d_abs:
            for xc in n_d_abs:
                c.rect("locali", grid(xc - 0.085), grid(inf_n["c_y2"] - 0.08), grid(xc + 0.085), grid(Y_T0 + 0.085))
            if len(n_d_abs) > 1 or abs(n_d_abs[0] - xd) > 1e-6:
                lo, hi = min(min(n_d_abs), xd), max(max(n_d_abs), xd)
                c.rect("locali", grid(lo - 0.085), grid(Y_T0 - 0.085), grid(hi + 0.085), grid(Y_T0 + 0.085))
        if p_d_abs:
            for xc in p_d_abs:
                c.rect("locali", grid(xc - 0.085), grid(Y_T2 - 0.085), grid(xc + 0.085), grid(inf_p["c_y1"] + 0.08))
            if len(p_d_abs) > 1 or abs(p_d_abs[0] - xd) > 1e-6:
                lo, hi = min(min(p_d_abs), xd), max(max(p_d_abs), xd)
                c.rect("locali", grid(lo - 0.085), grid(Y_T2 - 0.085), grid(hi + 0.085), grid(Y_T2 + 0.085))
        if n_d_abs and p_d_abs:
            c.rect("locali", grid(xd - 0.085), grid(Y_T0 - 0.085), grid(xd + 0.085), grid(Y_T2 + 0.085))
        elif p_d_abs:
            c.rect("locali", grid(xd - 0.085), grid(Y_T2 - 0.085), grid(xd + 0.085), grid(inf_p["c_y1"] + 0.08))

    return {
        "cx": cx,
        "xg": xg,
        "xd": xd,
        "n_s": [grid(cx + x) for x in inf_n["s_xs"]],
        "n_d": [grid(cx + x) for x in inf_n["d_xs"]],
        "p_d": [grid(cx + x) for x in inf_p["d_xs"]],
    }


def build_half_chain(w: Path) -> tuple[Cell, dict]:
    """Build one Plan-C5 half-chain in y > 0 (mirrored across y = 0 for the N path)."""
    h = Cell()

    # =========================================================================
    # 1. Domain A — Analog SF + Tail (4-sided closed psubdiff guard ring)
    #    Bottom (ndiff [0.40, 2.40]): [ dum_sp_L | Xsp | dum_sp_R | dum_tl_L | Xtail(nf=4) | dum_tl_R ]
    #    Top    (ndiff [4.00, 6.00]): [ dum_fp_L | Xfp(nf=10) | dum_fp_R ]
    # =========================================================================
    sp, i_sp = build_mos(w, "sp", "sky130_fd_pr__nfet_01v8", 2.0, 0.50, 1, 1.400, False)
    tail, i_tl = build_mos(w, "tail", "sky130_fd_pr__nfet_01v8", 2.0, 0.50, 4, 1.400, False)
    fp, i_fp = build_mos(w, "fp", "sky130_fd_pr__nfet_01v8_lvt", 2.0, 0.15, 10, 5.240, False)

    x_left_gr = 0.265
    # Leave >= 0.360 um between wall/vdrop and dummy polycont (licon.9+psdm.5a >= 0.235 um!)
    cx_sp = grid(x_left_gr + V_TAP_EDGE + 0.360 + 0.500 + 0.085 + i_sp["hw_diff"])
    x_sp_dl = grid(cx_sp - i_sp["hw_diff"] - 0.085 - 0.250)
    x_sp_dr = grid(cx_sp + i_sp["hw_diff"] + 0.085 + 0.250)
    x_sp_vdrop = grid(x_sp_dr + 0.360)
    x_tl_dl = grid(x_sp_vdrop + 0.360)
    cx_tl = grid(x_tl_dl + 0.250 + 0.085 + i_tl["hw_diff"])
    x_tl_dr = grid(cx_tl + i_tl["hw_diff"] + 0.085 + 0.250)
    cx_fp = grid(x_left_gr + V_TAP_EDGE + 0.360 + 0.150 + 0.085 + i_fp["hw_diff"])
    x_fp_dl = grid(cx_fp - i_fp["hw_diff"] - 0.085 - 0.075)
    x_fp_dr = grid(cx_fp + i_fp["hw_diff"] + 0.085 + 0.075)

    x_sf_gr = grid(max(x_tl_dr + 0.250, x_fp_dr + 0.075) + 0.360 + V_TAP_WALL)

    h.include(sp, dx=cx_sp)
    h.include(tail, dx=cx_tl)
    h.include(fp, dx=cx_fp)

    # Field-poly VSS-tied dummy gates symmetrically flanking Xsp (L=0.50), Xtail (L=0.50), Xfp (L=0.15)
    add_field_poly_dummy(h, x_sp_dl, 0.50, 0.400, Y_NDIFF_TOP, False, x_wall=x_left_gr)
    add_field_poly_dummy(h, x_sp_dr, 0.50, 0.400, Y_NDIFF_TOP, False, x_vdrop=x_sp_vdrop)
    add_field_poly_dummy(h, x_tl_dl, 0.50, 0.400, Y_NDIFF_TOP, False, x_vdrop=x_sp_vdrop)
    add_field_poly_dummy(h, x_tl_dr, 0.50, 0.400, Y_NDIFF_TOP, False, x_wall=x_sf_gr)

    add_field_poly_dummy(h, x_fp_dl, 0.15, Y_PDIFF_BOT, 6.240, True, x_wall=x_left_gr)
    add_field_poly_dummy(h, x_fp_dr, 0.15, Y_PDIFF_BOT, 6.240, True, x_wall=x_sf_gr)

    # Xsp: S -> VSS; G (vbias) -> polycont @ T1; D -> fp on locali up to T0
    h.rect("locali", grid(cx_sp + i_sp["s_xs"][0] - 0.085), Y_VSS, grid(cx_sp + i_sp["s_xs"][0] + 0.085), grid(i_sp["c_y1"] + 0.08))
    dx_sp = grid(cx_sp + i_sp["d_xs"][0])
    h.rect("locali", grid(dx_sp - 0.085), grid(i_sp["c_y2"] - 0.08), grid(dx_sp + 0.085), grid(Y_T0 + 0.085))
    h.pad("viali", dx_sp, Y_T0, 0.17)
    h.pad("metal1", dx_sp, Y_T0, 0.29)

    gx_sp = grid(cx_sp - 0.24)
    h.rect("poly", grid(cx_sp - 0.25), Y_NDIFF_TOP, grid(cx_sp + 0.25), Y_NPOLY_TIE[1])
    h.rect("poly", grid(gx_sp - 0.135), Y_NPOLY_TIE[0], grid(cx_sp + 0.25), grid(Y_T1 + 0.165))
    poly_cont_pad(h, gx_sp, Y_T1)
    h.pad("viali", gx_sp, Y_T1, 0.17)
    h.pad("metal1", gx_sp, Y_T1, 0.29)

    # Xtail (nf=4, flanked by L=0.50 field-poly VSS-tied dummies): S -> VSS; D -> ap_tail M1 @ y = 0.850; G -> vbias @ T1
    for sx in i_tl["s_xs"]:
        xc = grid(cx_tl + sx)
        h.rect("locali", grid(xc - 0.085), Y_VSS, grid(xc + 0.085), grid(i_tl["c_y1"] + 0.08))
    y_ap_tail = 0.850
    for dx in i_tl["d_xs"]:
        xc = grid(cx_tl + dx)
        h.pad("viali", xc, y_ap_tail, 0.17)
        h.pad("metal1", xc, y_ap_tail, 0.29)
    tie_poly_fingers(h, cx_tl, i_tl["g_xs"], i_tl["l_f"], Y_NPOLY_TIE, Y_NDIFF_TOP)
    gx_tl = grid(cx_tl)
    poly_cont_pad(h, gx_tl, Y_T1)
    h.rect("poly", grid(gx_tl - 0.135), Y_NPOLY_TIE[0], grid(gx_tl + 0.135), grid(Y_T1 + 0.165))
    h.pad("viali", gx_tl, Y_T1, 0.17)
    h.pad("metal1", gx_tl, Y_T1, 0.29)

    # vbias M1 along T1 from x_vbias = 0.900 (>= 0.25 um from x_left_gr M2) -> Xsp.G -> Xtail.G
    x_vbias = 0.900
    h.wire("metal1", [(x_vbias, Y_T1), (gx_tl, Y_T1)], W_M1)

    # Crossover 1 (fp / fn M3) placed cleanly between Domain A (x_sf_gr) and Domain B (x_ana_l_wall)
    x_cr1_p = grid(x_sf_gr + V_TAP_WALL + 0.320)
    x_cr1_n = grid(x_cr1_p + 0.720)
    x_ad = grid(x_sf_gr + V_TAP_WALL + 0.160)       # pwell/nwell boundary right outside Domain A psubdiff wall!
    x_ana_l_wall = grid(x_cr1_n + 0.360 + V_TAP_WALL)

    # Xfp (in Domain A pwell, y=[4.24, 6.24]):
    # - Drain (5 fingers = VDD): collected on horizontal M1 @ y=5.960 -> crosses x_sf_gr into nwell VDD rail @ x_ana_l_wall
    # - Source (6 fingers = fp): horizontal M1 @ y=4.460 -> M2 drop at s_xs[1] (~2.14, clear of x_inp!) -> T0 -> cr1
    for dx in i_fp["d_xs"]:
        xc = grid(cx_fp + dx)
        h.pad("viali", xc, 5.960, 0.17)
        h.pad("metal1", xc, 5.960, 0.29)
    h.wire("metal1", [(grid(cx_fp + i_fp["d_xs"][0]), 5.960), (x_ana_l_wall, 5.960)], 0.26)
    h.wire("metal1", [(x_ana_l_wall, 5.960), (x_ana_l_wall, Y_VDD)], 0.30)

    for sx in i_fp["s_xs"]:
        xc = grid(cx_fp + sx)
        h.pad("viali", xc, 4.460, 0.17)
        h.pad("metal1", xc, 4.460, 0.29)
    h.wire("metal1", [(grid(cx_fp + i_fp["s_xs"][0]), 4.460), (grid(cx_fp + i_fp["s_xs"][-1]), 4.460)], 0.24)
    x_fp_drop = grid(cx_fp + i_fp["s_xs"][3])
    h.via1(x_fp_drop, 4.460)
    h.via1(x_fp_drop, Y_T0)
    h.wire("metal2", [(x_fp_drop, Y_T0), (x_fp_drop, 4.460)], W_M2)
    h.wire("metal1", [(dx_sp, Y_T0), (x_cr1_n, Y_T0)], W_M1)

    # Xfp.G (inp on T2 = 3.900)
    tie_poly_fingers(h, cx_fp, i_fp["g_xs"], i_fp["l_f"], Y_PPOLY_TIE, Y_PDIFF_BOT)
    gx_fp = grid(cx_fp - 0.72)
    h.rect("poly", grid(gx_fp - 0.135), grid(3.740 - 0.170), grid(gx_fp + 0.135), Y_PPOLY_TIE[1])
    poly_cont_pad(h, gx_fp, 3.740)
    h.rect("locali", grid(gx_fp - 0.090), grid(3.740 - 0.170), grid(gx_fp + 0.090), grid(Y_T2 + 0.100))
    h.pad("viali", gx_fp, Y_T2, 0.17)
    h.pad("metal1", gx_fp, Y_T2, 0.29)
    x_inp = 1.660
    h.wire("metal1", [(x_inp, Y_T2), (gx_fp, Y_T2)], W_M1)

    # =========================================================================
    # 2. Domain B — Analog Diff-to-SE Core (Merged NP Unified Guard Ring):
    #    [ x_ana_l_wall | ip/lp(nf=6) | in/ln(nf=6) | x_ana_r_wall ]
    # =========================================================================
    ip_n, i_ipn = build_mos(w, "ip_n", "sky130_fd_pr__nfet_01v8_lvt", 2.0, 0.15, 3, 1.400, False)
    ip_p, i_ipp = build_mos(w, "lp_p", "sky130_fd_pr__pfet_01v8",      2.0, 0.15, 4, 5.240, True, has_sd_dummies=True)
    in_n, i_inn = build_mos(w, "in_n", "sky130_fd_pr__nfet_01v8_lvt", 2.0, 0.15, 3, 1.400, False)
    in_p, i_inp = build_mos(w, "ln_p", "sky130_fd_pr__pfet_01v8",      2.0, 0.15, 4, 5.240, True, has_sd_dummies=True)

    hw_ana_col = max(i_ipn["hw_diff"], i_ipp["hw_diff"])
    cx_ip = grid(x_ana_l_wall + V_TAP_WALL + 0.440 + hw_ana_col)
    cx_in = grid(cx_ip + hw_ana_col + 0.580 + hw_ana_col)
    x_ana_r_wall = grid(cx_in + hw_ana_col + 0.440 + V_TAP_WALL)

    for nm_c, cx_c in ((ip_n, cx_ip), (in_n, cx_in), (ip_p, cx_ip), (in_p, cx_in)):
        h.include(nm_c, dx=cx_c)

    # Field-poly VSS-tied dummy gates flanking Xip & Xin inside Xlp/Xln column footprint (2 per wing)
    x_ip_dl1 = grid(cx_ip - i_ipn["hw_diff"] - 0.160)
    x_ip_dl2 = grid(x_ip_dl1 - 0.490)
    x_ip_dr1 = grid(cx_ip + i_ipn["hw_diff"] + 0.160)
    x_ip_dr2 = grid(x_ip_dr1 + 0.490)
    x_in_dl1 = grid(cx_in - i_inn["hw_diff"] - 0.160)
    x_in_dl2 = grid(x_in_dl1 - 0.490)
    x_in_dr1 = grid(cx_in + i_inn["hw_diff"] + 0.160)
    x_in_dr2 = grid(x_in_dr1 + 0.490)
    x_mir_mid = grid((cx_ip + cx_in) / 2.0)

    add_field_poly_dummy(h, x_ip_dl2, 0.15, 0.400, Y_NDIFF_TOP, False, x_wall=x_ana_l_wall)
    add_field_poly_dummy(h, x_ip_dl1, 0.15, 0.400, Y_NDIFF_TOP, False, x_wall=x_ana_l_wall)
    add_field_poly_dummy(h, x_ip_dr1, 0.15, 0.400, Y_NDIFF_TOP, False, x_vdrop=x_mir_mid)
    add_field_poly_dummy(h, x_ip_dr2, 0.15, 0.400, Y_NDIFF_TOP, False, x_vdrop=x_mir_mid)
    add_field_poly_dummy(h, x_in_dl2, 0.15, 0.400, Y_NDIFF_TOP, False, x_vdrop=x_mir_mid)
    add_field_poly_dummy(h, x_in_dl1, 0.15, 0.400, Y_NDIFF_TOP, False, x_vdrop=x_mir_mid)
    add_field_poly_dummy(h, x_in_dr1, 0.15, 0.400, Y_NDIFF_TOP, False, x_wall=x_ana_r_wall)
    add_field_poly_dummy(h, x_in_dr2, 0.15, 0.400, Y_NDIFF_TOP, False, x_wall=x_ana_r_wall)

    # ap_tail: Xtail.D -> Xip.S -> Xin.S along M1 at y = y_ap_tail (0.850)
    for cx_i in (cx_ip, cx_in):
        for sx in i_ipn["s_xs"]:
            xc = grid(cx_i + sx)
            h.pad("viali", xc, y_ap_tail, 0.17)
            h.pad("metal1", xc, y_ap_tail, 0.29)
    h.wire("metal1", [(grid(cx_tl + i_tl["d_xs"][0]), y_ap_tail), (grid(cx_in + i_inn["s_xs"][-1]), y_ap_tail)], 0.24)

    # Xip.G (fp on T0 = 2.740) & Xin.G (fn on T1 = 3.320)
    for cx_i, i_inm, yt in ((cx_ip, i_ipn, Y_T0), (cx_in, i_inn, Y_T1)):
        tie_poly_fingers(c=h, cx=cx_i, g_xs=i_inm["g_xs"], l_f=i_inm["l_f"], y_tie=Y_NPOLY_TIE, y_stub_edge=Y_NDIFF_TOP)
        xg_i = grid(cx_i - 0.52)
        if yt == Y_T0:
            h.rect("poly", grid(xg_i - 0.135), Y_NPOLY_TIE[0], grid(xg_i + 0.135), grid(Y_T1 + 0.165))
            poly_cont_pad(h, xg_i, Y_T1)
            h.rect("locali", grid(xg_i - 0.085), grid(Y_T0 - 0.085), grid(xg_i + 0.085), grid(Y_T1 + 0.165))
            h.pad("viali", xg_i, Y_T0, 0.17)
            h.pad("metal1", xg_i, Y_T0, 0.29)
            h.wire("metal1", [(x_cr1_p, Y_T0), (xg_i, Y_T0)], W_M1)
        else:
            h.rect("poly", grid(xg_i - 0.135), Y_NPOLY_TIE[0], grid(xg_i + 0.135), grid(Y_T1 + 0.170))
            poly_cont_pad(h, xg_i, Y_T1)
            h.pad("viali", xg_i, Y_T1, 0.17)
            h.pad("metal1", xg_i, Y_T1, 0.29)
            h.wire("metal1", [(x_cr1_p, Y_T1), (xg_i, Y_T1)], W_M1)

    # Xlp & Xln (nf=6 with VDD-tied shared-diff dummy fingers; join ap_mir on M1 @ T2 so dummies stay 100% isolated!)
    for cx_i in (cx_ip, cx_in):
        for sx in i_ipp["s_xs"]:
            xc = grid(cx_i + sx)
            h.rect("locali", grid(xc - 0.085), grid(i_ipp["c_y2"] - 0.08), grid(xc + 0.085), Y_VDD)
        tie_poly_fingers(h, cx_i, i_ipp["g_xs"], i_ipp["l_f"], Y_PPOLY_TIE, Y_PDIFF_BOT)
        tie_sd_dummy_gates(h, cx_i, i_ipp, is_pmos=True)
        # Central polycont spine for active mirror gates -> locali up to T2 (3.900) -> viali
        h.rect("poly", grid(cx_i - 0.135), grid(Y_T1 - 0.165), grid(cx_i + 0.135), Y_PPOLY_TIE[1])
        poly_cont_pad(h, cx_i, Y_T1)
        h.rect("locali", grid(cx_i - 0.085), grid(Y_T1 - 0.085), grid(cx_i + 0.085), grid(Y_T2 + 0.085))
        h.pad("viali", cx_i, Y_T2, 0.17)
        h.pad("metal1", cx_i, Y_T2, 0.29)

    # Xip.D + Xlp.D (ap_mir)
    for xc in [grid(cx_ip + d) for d in i_ipn["d_xs"]]:
        h.pad("viali", xc, 2.050, 0.17)
        h.pad("metal1", xc, 2.050, 0.29)
    h.wire("metal1", [(grid(cx_ip + i_ipn["d_xs"][0]), 2.050), (grid(cx_ip + i_ipn["d_xs"][-1]), 2.050)], W_M1)
    for xc in [grid(cx_ip + d) for d in i_ipp["d_xs"]]:
        h.pad("viali", xc, 4.540, 0.17)
        h.pad("metal1", xc, 4.540, 0.29)
    h.wire("metal1", [(grid(cx_ip + i_ipp["d_xs"][0]), 4.540), (grid(cx_ip + i_ipp["d_xs"][-1]), 4.540)], W_M1)
    x_mir_v = grid(cx_ip + i_ipp["d_xs"][-1])
    h.via1(x_mir_v, 2.050)
    h.via1(x_mir_v, 4.540)
    h.wire("metal2", [(x_mir_v, 2.050), (x_mir_v, 4.540)], W_M2)
    h.wire("metal1", [(x_mir_v, 4.540), (x_mir_v, Y_T2)], W_M1)
    h.wire("metal1", [(cx_ip, Y_T2), (cx_in, Y_T2)], W_M1)

    # Xin.D + Xln.D (ap -> T2 = 3.900 -> bp.G)
    for xc in [grid(cx_in + d) for d in i_inn["d_xs"]]:
        h.pad("viali", xc, 2.050, 0.17)
        h.pad("metal1", xc, 2.050, 0.29)
    h.wire("metal1", [(grid(cx_in + i_inn["d_xs"][0]), 2.050), (grid(cx_in + i_inn["d_xs"][-1]), 2.050)], W_M1)
    for xc in [grid(cx_in + d) for d in i_inp["d_xs"]]:
        h.pad("viali", xc, 4.540, 0.17)
        h.pad("metal1", xc, 4.540, 0.29)
    h.wire("metal1", [(grid(cx_in + i_inp["d_xs"][0]), 4.540), (grid(cx_in + i_inp["d_xs"][-1]), 4.540)], W_M1)
    x_ap_v = grid(cx_in + i_inp["d_xs"][-1])
    h.via1(x_ap_v, 2.050)
    h.via1(x_ap_v, Y_T2)
    h.via1(x_ap_v, 4.540)
    h.wire("metal2", [(x_ap_v, 2.050), (x_ap_v, 4.540)], W_M2)

    # =========================================================================
    # 3. Digital Restorer in 3 Merged NP Sub-Blocks (C1, C2, C3):
    #    Double isolation wall between Domain B (x_ana_r_wall) and C1 (x_dig_l_wall)
    # =========================================================================
    x_dig_l_wall = grid(x_ana_r_wall + 0.660)

    # Specification: (name, n_wf, n_nf, p_wf, p_nf, gap_before, sd_dummies)
    c1_specs = [
        ("bp",   1.8, 1, 1.8, 2, 0.780, False),  # left field-poly dummies clear of V_TAP_WALL
        ("op",   2.0, 2, 2.0, 6, 0.300, True),   # shared-diff nf+2 dummies!
        ("dp1",  0.5, 1, 1.5, 1, 0.300, False),
        ("dp2",  0.5, 1, 1.5, 1, 0.300, False),
        ("dp3",  0.5, 1, 1.5, 1, 0.300, False),
    ]
    c2_specs = [
        ("setb", 2.0, 1, 1.5, 2, 0.780, False),  # left field-poly dummies clear of V_TAP_WALL
        ("seta", 2.0, 1, 1.5, 2, 0.300, False),
        ("qpb",  2.0, 2, 2.0, 3, 0.300, False),
        ("qpa",  2.0, 2, 2.0, 3, 0.300, False),
    ]
    c3_specs = [
        ("rp1",  2.0, 1, 2.0, 3, 0.780, False),  # left field-poly dummies clear of V_TAP_WALL
        ("rp2",  1.0, 1, 1.5, 2, 0.300, False),
        ("bprb", 2.0, 1, 1.5, 2, 0.300, False),
        ("bpra", 2.0, 1, 1.5, 2, 0.300, False),
        ("opr",  2.0, 2, 2.0, 4, 0.300, True),   # shared-diff nf+2 dummies!
    ]

    dcols: dict[str, dict] = {}

    def place_dig_group(x_start_wall: float, specs: list[tuple]) -> float:
        x_edge = x_start_wall
        for nm, n_wf, n_nf, p_wf, p_nf, gap_b, has_dum in specs:
            dy_nc = grid(Y_NDIFF_TOP - n_wf / 2.0)
            dy_pc = grid(Y_PDIFF_BOT + p_wf / 2.0)
            cn, inf_n = build_mos(w, f"{nm}_n", "sky130_fd_pr__nfet_01v8", n_wf, 0.15, n_nf, dy_nc, False, has_sd_dummies=has_dum)
            cp, inf_p = build_mos(w, f"{nm}_p", "sky130_fd_pr__pfet_01v8", p_wf, 0.15, p_nf, dy_pc, True, has_sd_dummies=has_dum)
            hw_col = max(inf_n["hw_diff"], inf_p["hw_diff"])
            cx = grid(x_edge + gap_b + hw_col)
            h.include(cn, dx=cx)
            h.include(cp, dx=cx)
            dcols[nm] = {"cx": cx, "hw": hw_col, "inf_n": inf_n, "inf_p": inf_p, "n_wf": n_wf, "p_wf": p_wf}
            x_edge = grid(cx + hw_col)
        return x_edge

    x_c1_end = place_dig_group(x_dig_l_wall, c1_specs)
    x_c12_wall = grid(x_c1_end + 0.780)  # room for dp3-right field-poly dummies clear of V_TAP_WALL
    x_c2_end = place_dig_group(x_c12_wall, c2_specs)
    x_c2_r_wall = grid(x_c2_end + 0.780)  # room for qpa-right field-poly dummies clear of V_TAP_WALL

    # Crossover 2 (qp / qn M3) sits cleanly in the inter-domain space between C2 and C3!
    x_cr2_n = grid(x_c2_r_wall + V_TAP_WALL + 0.320)
    x_cr2_p = grid(x_cr2_n + 0.720)
    x_c3_l_wall = grid(x_cr2_p + 0.320 + V_TAP_WALL)

    x_c3_end = place_dig_group(x_c3_l_wall, c3_specs)
    x_right_tap = grid(x_c3_end + 0.620)
    x_end = grid(x_right_tap + V_TAP_EDGE + 0.300)

    # Independent NMOS / PMOS field-poly dummies aligned to each device's actual diff edge
    def flank_n(nm: str, side: int, offset: float = 0.160, x_wall: float | None = None, x_vdrop: float | None = None) -> None:
        col = dcols[nm]
        x_d = grid(col["cx"] + side * (col["inf_n"]["hw_diff"] + offset))
        add_field_poly_dummy(h, x_d, 0.15, grid(Y_NDIFF_TOP - col["n_wf"]), Y_NDIFF_TOP, False, x_wall=x_wall, x_vdrop=x_vdrop)

    def flank_p(nm: str, side: int, offset: float = 0.160, x_wall: float | None = None, x_vdrop: float | None = None) -> None:
        col = dcols[nm]
        x_d = grid(col["cx"] + side * (col["inf_p"]["hw_diff"] + offset))
        add_field_poly_dummy(h, x_d, 0.15, Y_PDIFF_BOT, grid(Y_PDIFF_BOT + col["p_wf"]), True, x_wall=x_wall, x_vdrop=x_vdrop)

    flank_n("bp", -1, x_wall=x_dig_l_wall)
    flank_p("bp", -1, x_wall=x_dig_l_wall)
    flank_n("bp", +1, offset=0.210, x_vdrop=grid(dcols["bp"]["cx"] + 1.150))
    flank_n("dp1", -1, x_vdrop=grid(dcols["dp1"]["cx"] - 0.885))
    flank_n("dp3", +1, offset=0.240, x_wall=x_c12_wall)
    flank_p("dp3", +1, offset=0.240, x_wall=x_c12_wall)
    flank_n("setb", -1, x_wall=x_c12_wall)
    flank_p("setb", -1, x_wall=x_c12_wall)
    flank_n("qpa", +1, x_wall=x_c2_r_wall)
    flank_p("qpa", +1, offset=0.210, x_wall=x_c2_r_wall)
    flank_n("rp1", -1, x_wall=x_c3_l_wall)
    flank_p("rp1", -1, x_wall=x_c3_l_wall)

    # Connect Digital columns
    dc_wire: dict[str, dict] = {}
    dc_wire["bp"] = connect_col_locali(h, dcols["bp"]["cx"], dcols["bp"]["inf_n"], dcols["bp"]["inf_p"], xg_dx=-0.38, d_trunk_dx=0.00)
    dc_wire["op"] = connect_col_locali(h, dcols["op"]["cx"], dcols["op"]["inf_n"], dcols["op"]["inf_p"], xg_dx=-1.26, d_trunk_dx=0.00)
    for dnm in ("dp1", "dp2", "dp3"):
        dc_wire[dnm] = connect_col_locali(h, dcols[dnm]["cx"], dcols[dnm]["inf_n"], dcols[dnm]["inf_p"], xg_dx=-0.22, d_trunk_dx=+0.22)

    def wire_nand2(b_nm: str, a_nm: str, xg_b_dx: float, xg_a_dx: float, d_a_dx: float) -> tuple[dict, dict]:
        cb, ca = dcols[b_nm], dcols[a_nm]
        wb = connect_col_locali(
            h, cb["cx"], cb["inf_n"], cb["inf_p"],
            n_s_vss=True, p_s_vdd=True, n_d_up=False, p_d_dn=True, bridge_d=True,
            d_trunk_dx=0.00 if len(cb["inf_p"]["d_xs"]) == 1 else cb["inf_p"]["d_xs"][-1],
            xg_dx=xg_b_dx,
        )
        wa = connect_col_locali(
            h, ca["cx"], ca["inf_n"], ca["inf_p"],
            n_s_vss=False, p_s_vdd=True, n_d_up=True, p_d_dn=True, bridge_d=True,
            d_trunk_dx=d_a_dx, xg_dx=xg_a_dx,
        )
        ym_lo = max(cb["inf_n"]["c_y1"], ca["inf_n"]["c_y1"]) + 0.10
        ym_hi = min(cb["inf_n"]["c_y2"], ca["inf_n"]["c_y2"]) - 0.10
        ym_c = grid((ym_lo + ym_hi) / 2.0)
        if len(wb["n_s"]) == 1 and len(wa["n_s"]) == 1:
            h.rect("locali", grid(wb["n_d"][-1] - 0.085), grid(ym_c - 0.12), grid(wa["n_s"][0] + 0.085), grid(ym_c + 0.12))
        else:
            mid_xs = wb["n_d"] + wa["n_s"]
            for xc in mid_xs:
                h.pad("viali", xc, ym_c, 0.17)
                h.pad("metal1", xc, ym_c, 0.29)
            h.wire("metal1", [(min(mid_xs), ym_c), (max(mid_xs), ym_c)], W_M1)
        return wb, wa

    wb_set, wa_set = wire_nand2("setb", "seta", -0.38, -0.38, 0.00)
    dc_wire["setb"], dc_wire["seta"] = wb_set, wa_set

    wb_qp, wa_qp = wire_nand2("qpb", "qpa", -0.64, -0.64, -0.24)
    dc_wire["qpb"], dc_wire["qpa"] = wb_qp, wa_qp

    dc_wire["rp1"] = connect_col_locali(h, dcols["rp1"]["cx"], dcols["rp1"]["inf_n"], dcols["rp1"]["inf_p"], xg_dx=-0.64, d_trunk_dx=+0.72)
    dc_wire["rp2"] = connect_col_locali(h, dcols["rp2"]["cx"], dcols["rp2"]["inf_n"], dcols["rp2"]["inf_p"], xg_dx=-0.38, d_trunk_dx=0.00)
    wb_bpr, wa_bpr = wire_nand2("bprb", "bpra", -0.38, -0.38, 0.00)
    dc_wire["bprb"], dc_wire["bpra"] = wb_bpr, wa_bpr
    dc_wire["opr"] = connect_col_locali(h, dcols["opr"]["cx"], dcols["opr"]["inf_n"], dcols["opr"]["inf_p"], xg_dx=-0.88, d_trunk_dx=0.00)

    # =========================================================================
    # 4. Pure-Locali Adjacent Stage Hops (y = Y_T1 = 3.320) & M1 Track Routing
    # =========================================================================
    def li_hop(x1: float, x2: float, y: float = Y_T1) -> None:
        h.rect("locali", grid(min(x1, x2) - 0.085), grid(y - 0.085), grid(max(x1, x2) + 0.085), grid(y + 0.085))

    def m1_tap(x: float, y_src: float, y_trk: float) -> None:
        h.pad("viali", x, y_src, 0.17)
        h.pad("metal1", x, y_src, 0.29)
        if abs(y_src - y_trk) > 1e-6:
            h.wire("metal1", [(x, y_src), (x, y_trk)], W_M1)

    # ap: Xin.D/Xln.D -> T2 (3.900) -> bp.G
    m1_tap(dc_wire["bp"]["xg"], Y_T1, Y_T2)
    h.wire("metal1", [(x_ap_v, Y_T2), (dc_wire["bp"]["xg"], Y_T2)], W_M1)

    # bp.D -> op.G (ON LOCALI)
    li_hop(dc_wire["bp"]["xd"], dc_wire["op"]["xg"])

    # rawp: op.D -> T1 (3.320) -> dp1.G & seta.G
    m1_tap(dc_wire["op"]["xd"], Y_T1, Y_T1)
    m1_tap(dc_wire["dp1"]["xg"], Y_T1, Y_T1)
    m1_tap(dc_wire["seta"]["xg"], Y_T1, Y_T1)
    h.wire("metal1", [(dc_wire["op"]["xd"], Y_T1), (dc_wire["seta"]["xg"], Y_T1)], W_M1)

    # dp1 -> dp2 -> dp3 -> setb.G (ON LOCALI @ Y_T1, cleanly passing through x_c12_wall well gap!)
    li_hop(dc_wire["dp1"]["xd"], dc_wire["dp2"]["xg"])
    li_hop(dc_wire["dp2"]["xd"], dc_wire["dp3"]["xg"])
    li_hop(dc_wire["dp3"]["xd"], dc_wire["setb"]["xg"])

    # set_b: setb.P.D -> seta.P.D -> T2 (3.900) -> qpa.G
    m1_tap(wb_set["xd"], 4.540, Y_T2)
    m1_tap(wa_set["xd"], Y_T2, Y_T2)
    li_hop(dc_wire["qpa"]["xg"], dc_wire["qpa"]["xg"], Y_T1)
    h.rect("locali", grid(dc_wire["qpa"]["xg"] - 0.085), grid(Y_T1 - 0.085), grid(dc_wire["qpa"]["xg"] + 0.085), grid(Y_T2 + 0.085))
    m1_tap(dc_wire["qpa"]["xg"], Y_T2, Y_T2)
    h.wire("metal1", [(wb_set["xd"], Y_T2), (dc_wire["qpa"]["xg"], Y_T2)], W_M1)

    # qp -> cr2_n -> rp1.G & bpra.G on T0 (2.740)
    x_qpb_pd = wb_qp["p_d"][-1]
    x_qpa_pd = wa_qp["xd"]
    h.pad("viali", x_qpb_pd, 4.540, 0.17)
    h.pad("metal1", x_qpb_pd, 4.540, 0.29)
    h.pad("viali", x_qpa_pd, 4.540, 0.17)
    h.pad("metal1", x_qpa_pd, 4.540, 0.29)
    h.wire("metal1", [(x_qpb_pd, 4.540), (x_qpa_pd, 4.540)], W_M1)
    h.pad("viali", x_qpa_pd, Y_T0, 0.17)
    h.pad("metal1", x_qpa_pd, Y_T0, 0.29)
    m1_tap(dc_wire["rp1"]["xg"], Y_T1, Y_T0)
    h.rect("locali", grid(dc_wire["bpra"]["xg"] - 0.085), grid(Y_T0 - 0.085), grid(dc_wire["bpra"]["xg"] + 0.085), grid(Y_T1 + 0.085))
    m1_tap(dc_wire["bpra"]["xg"], Y_T0, Y_T0)
    h.wire("metal1", [(x_qpa_pd, Y_T0), (dc_wire["bpra"]["xg"], Y_T0)], W_M1)

    # qn arrives from cr2_p on T1 (3.320) -> qpb.G
    m1_tap(dc_wire["qpb"]["xg"], Y_T1, Y_T1)
    h.wire("metal1", [(dc_wire["qpb"]["xg"], Y_T1), (x_cr2_p, Y_T1)], W_M1)

    # rp1.D -> rp2.G (ON LOCALI)
    li_hop(dc_wire["rp1"]["xd"], dc_wire["rp2"]["xg"])

    # rp2.D -> T2 (3.900) -> bprb.G
    m1_tap(dc_wire["rp2"]["xd"], Y_T2, Y_T2)
    h.rect("locali", grid(dc_wire["bprb"]["xg"] - 0.085), grid(Y_T1 - 0.085), grid(dc_wire["bprb"]["xg"] + 0.085), grid(Y_T2 + 0.085))
    m1_tap(dc_wire["bprb"]["xg"], Y_T2, Y_T2)
    h.wire("metal1", [(dc_wire["rp2"]["xd"], Y_T2), (dc_wire["bprb"]["xg"], Y_T2)], W_M1)

    # bp_r: bprb.P.D -> bpra.P.D -> opr.G (ON LOCALI)
    h.pad("viali", wb_bpr["xd"], 4.540, 0.17)
    h.pad("metal1", wb_bpr["xd"], 4.540, 0.29)
    h.pad("viali", wa_bpr["xd"], 4.540, 0.17)
    h.pad("metal1", wa_bpr["xd"], 4.540, 0.29)
    h.wire("metal1", [(wb_bpr["xd"], 4.540), (wa_bpr["xd"], 4.540)], W_M1)
    li_hop(wa_bpr["xd"], dc_wire["opr"]["xg"])

    # outp: opr.D -> T1 (3.200) -> x_out_port (clear of x_right_tap VDD M2 strap)
    x_out_port = grid(x_right_tap + 0.720)
    m1_tap(dc_wire["opr"]["xd"], Y_T1, Y_T1)
    h.wire("metal1", [(dc_wire["opr"]["xd"], Y_T1), (x_out_port, Y_T1)], W_M1)
    x_end = max(x_end, grid(x_out_port + 0.450))

    # =========================================================================
    # 5. Merged Domain Wells, Guard Rings & Power Rails
    # =========================================================================
    h.rect("pwell", 0.000, 0.000, x_ad, Y_TOP)
    h.rect("pwell", x_ad, 0.000, x_end, Y_WELL)
    h.rect("nwell", x_ad, Y_WELL, x_end, Y_TOP)

    # Domain A closed 4-sided P-sub guard ring (y = 0 bottom, y = Y_VDD top, left x_left_gr, right x_sf_gr)
    draw_tap_h(h, "psubdiff", 0.180, grid(x_sf_gr + V_TAP_WALL), Y_VDD, half_w=H_TAP_VDD)
    draw_tap_v(h, "psubdiff", x_left_gr, Y_VSS, Y_VDD, half_w=V_TAP_EDGE)
    draw_tap_v(h, "psubdiff", x_sf_gr, Y_VSS, Y_VDD, half_w=V_TAP_WALL)
    h.wire("metal1", [(0.180, Y_VDD), (grid(x_sf_gr + V_TAP_WALL), Y_VDD)], 0.20)
    for xc in (x_left_gr, grid((x_left_gr + x_sf_gr) / 2.0), x_sf_gr):
        viali_on_rail(h, xc, Y_VDD)

    # Continuous center VSS tap bar + M1 rail across all domains
    draw_tap_h(h, "psubdiff", 0.180, grid(x_right_tap + V_TAP_EDGE), Y_VSS, half_w=H_TAP_VSS)
    h.wire("metal1", [(0.180, Y_VSS), (grid(x_right_tap + V_TAP_EDGE), Y_VSS)], 0.18)
    for xc in (x_left_gr, 1.150, x_sf_gr, x_mir_mid):
        viali_on_rail(h, xc, Y_VSS)

    # Continuous top VDD nsubdiff tap bar + M1 rail across Domain B + C1 + C2 + C3
    draw_tap_h(h, "nsubdiff", grid(x_ana_l_wall - V_TAP_WALL), grid(x_right_tap + V_TAP_EDGE), Y_VDD, half_w=H_TAP_VDD)
    h.wire("metal1", [(grid(x_ana_l_wall - V_TAP_WALL), Y_VDD), (grid(x_right_tap + V_TAP_EDGE), Y_VDD)], 0.20)

    # Vertical NP guard-ring walls closing Domains B, C1, C2, C3 (double-walled A/D barrier!)
    for xw in (x_ana_l_wall, x_ana_r_wall, x_dig_l_wall, x_c12_wall, x_c2_r_wall, x_c3_l_wall):
        draw_np_wall(h, xw, half_w=V_TAP_WALL)
    draw_np_wall(h, x_right_tap, half_w=V_TAP_EDGE)

    return h, {
        "x_vbias": x_vbias,
        "x_inp": x_inp,
        "x_cr1_p": x_cr1_p,
        "x_cr1_n": x_cr1_n,
        "x_cr2_n": x_cr2_n,
        "x_cr2_p": x_cr2_p,
        "x_out_port": x_out_port,
        "x_right_tap": x_right_tap,
        "x_left_gr": x_left_gr,
    }


def build_cml_to_cmos(out: Path) -> dict:
    cell = "serdes_cml_to_cmos_pvt_candidate_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    half, meta = build_half_chain(w)
    c = Cell()
    c.include(half, mirror_y=False)  # P path (y > 0)
    c.include(half, mirror_y=True)   # N path (y < 0)

    # 1. Tie +VDD and -VDD rails on M2 at x_right_tap + M3 port
    x_vdd = meta["x_right_tap"]
    c.via1(x_vdd, +Y_VDD)
    c.via1(x_vdd, -Y_VDD)
    c.wire("metal2", [(x_vdd, -Y_VDD), (x_vdd, +Y_VDD)], W_M3)
    c.via2(x_vdd, +Y_VDD)
    c.pad("metal3", x_vdd, +Y_VDD, 0.40, 0.60)

    # 2. Tie +vbias and -vbias on M2 at x_vbias + M3 port
    x_vbias = meta["x_vbias"]
    c.via1(x_vbias, +Y_T1)
    c.via1(x_vbias, -Y_T1)
    c.wire("metal2", [(x_vbias, -Y_T1), (x_vbias, +Y_T1)], W_M2)
    c.via2(x_vbias, +Y_T1)
    c.pad("metal3", x_vbias, +Y_T1, 0.40, 0.60)

    # 3. Central VSS M3 port on left-end VSS guard strap (clear of x_vbias = 0.820!)
    x_gr_vss = meta["x_left_gr"]
    c.via1(x_gr_vss, +Y_VDD)
    c.via1(x_gr_vss, Y_VSS)
    c.via1(x_gr_vss, -Y_VDD)
    c.wire("metal2", [(x_gr_vss, -Y_VDD), (x_gr_vss, +Y_VDD)], W_M2)
    c.via2(x_gr_vss, Y_VSS)
    c.pad("metal3", x_gr_vss, Y_VSS, 0.40, 0.60)

    # 4. Symmetric M3 Cross-Over 1 (fp/fn) and Cross-Over 2 (qp/qn)
    for x_cr, y_s, y_d in (
        (meta["x_cr1_p"], +Y_T0, -Y_T1),
        (meta["x_cr1_n"], -Y_T0, +Y_T1),
        (meta["x_cr2_p"], +Y_T0, -Y_T1),
        (meta["x_cr2_n"], -Y_T0, +Y_T1),
    ):
        c.via1(x_cr, y_s)
        c.via2(x_cr, y_s)
        c.via1(x_cr, y_d)
        c.via2(x_cr, y_d)
        c.wire("metal3", [(x_cr, y_s), (x_cr, y_d)], W_M3)

    # 5. Input & Output M3 ports (0.40 x 0.60 um M3 pads for met3.6 >= 0.24 um^2)
    x_inp = meta["x_inp"]
    x_out = meta["x_out_port"]
    for xp, yp in ((x_inp, +Y_T2), (x_inp, -Y_T2), (x_out, +Y_T1), (x_out, -Y_T1)):
        c.via1(xp, yp)
        c.via2(xp, yp)
        c.pad("metal3", xp, yp, 0.40, 0.60)

    c.port("inp", "metal3", x_inp, +Y_T2)
    c.port("inn", "metal3", x_inp, -Y_T2)
    c.port("outp", "metal3", x_out, +Y_T1)
    c.port("outn", "metal3", x_out, -Y_T1)
    c.port("vbias", "metal3", x_vbias, +Y_T1)
    c.port("vdd", "metal3", x_vdd, +Y_VDD)
    c.port("vss", "metal3", x_gr_vss, Y_VSS)
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
        "* Physical LVS reference for serdes_cml_to_cmos_pvt_candidate (Plan C5: merged NP guard rings + tied dummy gates)",
        f".subckt {cell} inp inn outp outn vbias vdd vss",
        "Xfp vdd inp fp vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15",
        "Xfn vdd inn fn vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15",
        "Xsp fp vbias vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.5",
        "Xsn fn vbias vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.5",
        "Xap_ip ap_mir fp ap_tail vss sky130_fd_pr__nfet_01v8_lvt w=6 l=0.15",
        "Xap_in ap fn ap_tail vss sky130_fd_pr__nfet_01v8_lvt w=6 l=0.15",
        "Xap_lp ap_mir ap_mir vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xap_ln ap ap_mir vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xap_t ap_tail vbias vss vss sky130_fd_pr__nfet_01v8 w=8 l=0.5",
        "Xan_ip an_mir fn an_tail vss sky130_fd_pr__nfet_01v8_lvt w=6 l=0.15",
        "Xan_in an fp an_tail vss sky130_fd_pr__nfet_01v8_lvt w=6 l=0.15",
        "Xan_lp an_mir an_mir vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xan_ln an an_mir vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xan_t an_tail vbias vss vss sky130_fd_pr__nfet_01v8 w=8 l=0.5",
        *inv_lines("bp", "ap", "bp", 1.8, 3.6),
        *inv_lines("bn", "an", "bn", 1.8, 3.6),
        *inv_lines("op", "bp", "rawp", 4, 12),
        *inv_lines("on", "bn", "rawn", 4, 12),
        *inv_lines("dp1", "rawp", "dp1", 0.5, 1.5),
        *inv_lines("dp2", "dp1", "dp2", 0.5, 1.5),
        *inv_lines("dp3", "dp2", "dp3", 0.5, 1.5),
        *inv_lines("dn1", "rawn", "dn1", 0.5, 1.5),
        *inv_lines("dn2", "dn1", "dn2", 0.5, 1.5),
        *inv_lines("dn3", "dn2", "dn3", 0.5, 1.5),
        *nand_lines("set", "rawp", "dp3", "set_b", 2, 3),
        *nand_lines("rst", "rawn", "dn3", "reset_b", 2, 3),
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
        "* Shared-diffusion left/right biased dummy fingers (D=S=G=B=VSS for NMOS, VDD for PMOS)",
        "Xdum_lpl_l vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lpl_r vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lnl_l vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lnl_r vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lpr_l vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lpr_r vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lnr_l vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_lnr_r vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_op_nl vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_op_nr vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_on_nl vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_on_nr vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_op_pl vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_op_pr vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_on_pl vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_on_pr vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_opr_nl vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_opr_nr vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_onr_nl vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_onr_nr vss vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xdum_opr_pl vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_opr_pr vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_onr_pl vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        "Xdum_onr_pr vdd vdd vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"), str(w), cell, "--ref", str(ref_path)],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO,
        check=True,
        capture_output=True,
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

    r = build_cml_to_cmos(out)
    print(
        f"{r['cell']:36s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | size={r['size_um']} um",
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
