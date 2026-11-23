#!/usr/bin/env python3
"""Build 2 GHz pure-CMOS differential C2MOS /8 prescaler SKY130 PDK layout (pll_cmos_prescaler8_2g_pdk).

Implements `analog/pll/divider/spice/cmos_prescaler8_2g.spice`:
  - Three cascaded mirror-symmetric stages: Xdiv2 (2G->1G), Xdiv4 (1G->500M), Xdiv8 (500M->250M).
  - Each stage uses 11 straight-through columns mirrored across the center VSS spine (y=0),
    with zero-contention series NMOS/PMOS common-mode killers (Xcm_mn*/Xcm_mp*, Xcm_qn*/Xcm_qp*).
  - Gate polycont taps on nf=2/nf=1 devices are offset laterally (dx=-0.46 / -0.22) clear of
    central drains (dx=0.00), eliminating all locali/mcon/M1 spacing violations.
  - Power uses center M1+M4 VSS and top/bottom M1+M2+M3 VDD rails joined by an external-left M4 bridge.
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
W_M3 = 0.36
W_PWR_M1 = 0.36
W_PWR_M2 = 0.52
W_PWR_M3 = 0.56
W_PWR_M4 = 0.80

# Y-coordinates in Top half (Bottom half mirrors across Y_VSS = 0.000)
Y_VSS = 0.000
H_TAP_VSS = 0.145
H_TAP_VDD = 0.175
V_TAP_WALL = 0.180
V_TAP_EDGE = 0.220

Y_N_TOP = 1.940       # Max NMOS w_f = 1.50 -> sits [0.440 .. 1.940], >=0.295 clear of psubdiff
NPOLY_TIE = (2.030, 2.180)
Y_T0 = 2.330          # N-gate polycont + cross-couple local M1 track (0.200 li clear of ndiff)
Y_T1 = 2.950          # Main M1 stage node track (mp / qp_i; Bot: mn / qn_i)
Y_T2 = 3.570          # P-gate polycont track (0.200 li clear of pdiff)
PPOLY_TIE = (3.720, 3.870)
Y_P_BOT = 3.960       # Max PMOS w_f = 3.10 -> sits [3.960 .. 7.060]
Y_VDD = 7.760         # 0.700 clear above max pdiff top (7.060)

Y_M3_CK = 4.700       # Horizontal M3 clock rail (+Y for ckp, -Y for ckn)
Y_M3_FB = 5.500       # Horizontal M3 feedback rail (+Y for qn_i, -Y for qp_i)


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def poly_cont_pad(c: Cell, x: float, y: float) -> None:
    c.pad("poly", x, y, 0.27, 0.34)
    c.pad("polycont", x, y, 0.17, 0.17)
    c.pad("locali", x, y, 0.18, 0.34)


def via3_pad(c: Cell, x: float, y: float) -> None:
    # >= 0.52 x 0.52 = 0.2704 um^2 > 0.24 um^2 Metal3 minimum area rule (met3.6)
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def viali_pad(c: Cell, x: float, y: float) -> None:
    c.pad("viali", x, y, 0.17)
    c.pad("metal1", x, y, 0.28, 0.29)


def draw_tap_h(c: Cell, diff_layer: str, x1: float, x2: float, y: float, half_w: float) -> None:
    c.rect(diff_layer, x1, grid(y - half_w), x2, grid(y + half_w))
    c.rect("locali", x1, grid(y - 0.085), x2, grid(y + 0.085))
    if (x2 - x1) >= 0.48:
        c.rect(diff_layer + "cont", grid(x1 + 0.14), grid(y - 0.085), grid(x2 - 0.14), grid(y + 0.085))


def draw_tap_v(c: Cell, diff_layer: str, x: float, y1: float, y2: float, half_w: float) -> None:
    c.rect(diff_layer, grid(x - half_w), grid(y1 - 0.085), grid(x + half_w), grid(y2 + 0.085))
    c.rect("locali", grid(x - 0.085), grid(y1 - 0.085), grid(x + 0.085), grid(y2 + 0.085))
    if (y2 - y1) >= 0.90:
        c.rect(diff_layer + "cont", grid(x - 0.085), grid(y1 + 0.360), grid(x + 0.085), grid(y2 - 0.360))


def draw_np_wall_band(c: Cell, x: float, y_vss: float, y_t1: float, y_vdd: float, half_w: float) -> None:
    if y_vss < y_vdd:
        draw_tap_v(c, "psubdiff", x, y_vss, grid(y_t1 - 0.360), half_w)
        draw_tap_v(c, "nsubdiff", x, grid(y_t1 + 0.360), y_vdd, half_w)
    else:
        draw_tap_v(c, "nsubdiff", x, y_vdd, grid(y_t1 - 0.360), half_w)
        draw_tap_v(c, "psubdiff", x, grid(y_t1 + 0.360), y_vss, half_w)
    c.pad("viali", x, y_vss, 0.17)
    c.pad("metal1", x, y_vss, 0.32)
    c.pad("viali", x, y_vdd, 0.17)
    c.pad("metal1", x, y_vdd, 0.32)


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


def tie_poly_v(c: Cell, cx: float, g_xs: list[float], l_f: float, y_lo: float, y_hi: float) -> None:
    hw = grid(l_f / 2.0)
    for gx in g_xs:
        c.rect("poly", grid(cx + gx - hw), y_lo, grid(cx + gx + hw), y_hi)


def build_div2_stage(
    c: Cell,
    w: Path,
    st_name: str,
    x_l_wall: float,
    wn: float,
    wp: float,
    wbuf_n: float,
    wbuf_p: float,
    wcm_n: float,
    wcm_p: float,
    is_first: bool,
) -> dict:
    """Place & route one differential C2MOS /2 stage across y=0 starting right of x_l_wall."""
    n_wf, n_nf = grid(wn / 2.0), 2
    p_wf, p_nf = grid(wp / 2.0), 2
    bn_wf, bn_nf = grid(wbuf_n / 2.0), 2
    bp_wf, bp_nf = grid(wbuf_p / 2.0), 2
    cn_wf, cn_nf = grid(wcm_n), 1
    cp_wf, cp_nf = grid(wcm_p / 2.0), 2

    # 11 columns: generous diff/poly gaps (>=0.54 um) keep shifted polycont pads clean of neighbors
    col_specs = [
        ("mp_d",  n_wf,  n_nf,  p_wf,  p_nf,  0.540),
        ("mp_ck", n_wf,  n_nf,  p_wf,  p_nf,  0.600),
        ("k_m",   0.60,  1,     1.30,  1,     0.640),
        ("cm_m1", cn_wf, cn_nf, cp_wf, cp_nf, 0.540),  # Top: P-only; Bot: N-only
        ("cm_m2", cn_wf, cn_nf, cp_wf, cp_nf, 0.560),  # Top: P-only; Bot: N-only
        ("sp_d",  n_wf,  n_nf,  p_wf,  p_nf,  0.600),
        ("sp_ck", n_wf,  n_nf,  p_wf,  p_nf,  0.600),
        ("k_q",   0.60,  1,     1.30,  1,     0.640),
        ("cm_q1", cn_wf, cn_nf, cp_wf, cp_nf, 0.540),  # Top: P-only; Bot: N-only
        ("cm_q2", cn_wf, cn_nf, cp_wf, cp_nf, 0.560),  # Top: P-only; Bot: N-only
        ("ob",    bn_wf, bn_nf, bp_wf, bp_nf, 0.600),
    ]

    cols: dict[str, dict] = {}
    x_edge = grid(x_l_wall + (V_TAP_EDGE if is_first else V_TAP_WALL))
    for cname, wn_c, nfn_c, wp_c, nfp_c, gap_b in col_specs:
        cm_top_only_p = cname in ("cm_m1", "cm_m2", "cm_q1", "cm_q2")
        dy_n = grid(Y_N_TOP - wn_c / 2.0)
        dy_p = grid(Y_P_BOT + wp_c / 2.0)

        cn, inf_n = build_mos(w, f"{st_name}_{cname}_n", "sky130_fd_pr__nfet_01v8", wn_c, 0.15, nfn_c, dy_n, False)
        cp, inf_p = build_mos(w, f"{st_name}_{cname}_p", "sky130_fd_pr__pfet_01v8", wp_c, 0.15, nfp_c, dy_p, True)
        hw = max(inf_n["hw_diff"], inf_p["hw_diff"])
        cx = grid(x_edge + gap_b + hw)
        x_edge = grid(cx + hw)

        if not cm_top_only_p:
            c.include(cn, dx=cx, mirror_y=False)
        c.include(cp, dx=cx, mirror_y=False)

        c.include(cn, dx=cx, mirror_y=True)
        if not cm_top_only_p:
            c.include(cp, dx=cx, mirror_y=True)

        cols[cname] = {
            "cx": cx,
            "hw": hw,
            "inf_n": inf_n,
            "inf_p": inf_p,
            "cm_split": cm_top_only_p,
        }

    x_r_wall = grid(x_edge + 0.600 + V_TAP_WALL)
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []

    def sgn_y(sgn: int, y: float) -> float:
        return grid(sgn * y)

    def locali_v(x: float, y1: float, y2: float) -> None:
        ya, yb = sorted((grid(y1), grid(y2)))
        c.rect("locali", grid(x - 0.085), ya, grid(x + 0.085), yb)

    def locali_h(x1: float, x2: float, y: float) -> None:
        xa, xb = sorted((grid(x1), grid(x2)))
        c.rect("locali", grid(xa - 0.085), grid(y - 0.085), grid(xb + 0.085), grid(y + 0.085))

    def tie_poly_bars(col: dict, sgn: int, tie_n: bool, tie_p: bool, x_ext_l: float | None = None, x_ext_r: float | None = None) -> None:
        cx = col["cx"]
        in_n, in_p = col["inf_n"], col["inf_p"]
        if tie_n:
            g_xs = in_n["g_xs"]
            ya, yb = sorted((sgn_y(sgn, NPOLY_TIE[0]), sgn_y(sgn, NPOLY_TIE[1])))
            tie_poly_v(c, cx, g_xs, 0.15, ya if sgn > 0 else sgn_y(sgn, Y_N_TOP), sgn_y(sgn, Y_N_TOP) if sgn > 0 else yb)
            x1 = grid(min(cx + g_xs[0] - 0.075, (cx + x_ext_l - 0.075) if x_ext_l is not None else 1e9))
            x2 = grid(max(cx + g_xs[-1] + 0.075, (cx + x_ext_r + 0.075) if x_ext_r is not None else -1e9))
            if len(g_xs) > 1 or x_ext_l is not None or x_ext_r is not None:
                c.rect("poly", x1, ya, x2, yb)
        if tie_p:
            g_xs = in_p["g_xs"]
            ya, yb = sorted((sgn_y(sgn, PPOLY_TIE[0]), sgn_y(sgn, PPOLY_TIE[1])))
            tie_poly_v(c, cx, g_xs, 0.15, sgn_y(sgn, Y_P_BOT) if sgn > 0 else ya, yb if sgn > 0 else sgn_y(sgn, Y_P_BOT))
            x1 = grid(min(cx + g_xs[0] - 0.075, (cx + x_ext_l - 0.075) if x_ext_l is not None else 1e9))
            x2 = grid(max(cx + g_xs[-1] + 0.075, (cx + x_ext_r + 0.075) if x_ext_r is not None else -1e9))
            if len(g_xs) > 1 or x_ext_l is not None or x_ext_r is not None:
                c.rect("poly", x1, ya, x2, yb)

    def tap_polycont(col: dict, sgn: int, is_p: bool, y_trk: float, tap_dx: float) -> float:
        """Place polycont strictly clear of diffusion (>=0.090 um poly-to-diff clearance)."""
        cx = col["cx"]
        gx = grid(cx + tap_dx)
        yt = sgn_y(sgn, y_trk)
        poly_cont_pad(c, gx, yt)
        tie_y = PPOLY_TIE if is_p else NPOLY_TIE
        ys = sorted((yt, sgn_y(sgn, tie_y[0]), sgn_y(sgn, tie_y[1])))
        c.rect("poly", grid(gx - 0.135), ys[0], grid(gx + 0.135), ys[-1])
        return gx

    def wire_shared_inv_gate(col: dict, sgn: int, y_trk: float, tap_dx: float) -> float:
        """Join N and P poly across channel at tap_dx (shifted away from drain dx=0.00 / +0.26)."""
        cx = col["cx"]
        tie_poly_bars(col, sgn, tie_n=True, tie_p=True, x_ext_l=tap_dx)
        xg = grid(cx + tap_dx)
        ya, yb = sorted((sgn_y(sgn, NPOLY_TIE[0]), sgn_y(sgn, PPOLY_TIE[1])))
        c.rect("poly", grid(xg - 0.135), ya, grid(xg + 0.135), yb)
        yt = sgn_y(sgn, y_trk)
        poly_cont_pad(c, xg, yt)
        viali_pad(c, xg, yt)
        return xg

    def src_to_rail(col: dict, sgn: int, is_p: bool) -> None:
        inf = col["inf_p"] if is_p else col["inf_n"]
        cx = col["cx"]
        y_rail = sgn_y(sgn, Y_VDD if is_p else Y_VSS)
        for sx in inf["s_xs"]:
            xc = grid(cx + sx)
            y_c = sgn_y(sgn, inf["c_y2"] - 0.06 if is_p else inf["c_y1"] + 0.06)
            locali_v(xc, y_rail, y_c)
            if is_p:
                p_s_pts.append((sgn, xc))
            else:
                n_s_xs.append(xc)

    for sgn in (+1, -1):
        # 1. Sources to power rails
        for nm in ("mp_d", "k_m", "sp_d", "k_q", "ob"):
            src_to_rail(cols[nm], sgn, is_p=True)
            src_to_rail(cols[nm], sgn, is_p=False)
        for nm in ("cm_m2", "cm_q2"):
            src_to_rail(cols[nm], sgn, is_p=(sgn > 0))

        # 2. Internal latch series nodes (n1/n2) on M1 at diffusion mid-Y
        for d_nm, ck_nm in (("mp_d", "mp_ck"), ("sp_d", "sp_ck")):
            cd, cck = cols[d_nm], cols[ck_nm]
            for is_p in (False, True):
                id_info = cd["inf_p"] if is_p else cd["inf_n"]
                ick_info = cck["inf_p"] if is_p else cck["inf_n"]
                y_mid = sgn_y(sgn, (id_info["c_y1"] + id_info["c_y2"]) / 2.0)
                pts = [grid(cd["cx"] + x) for x in id_info["d_xs"]] + [grid(cck["cx"] + x) for x in ick_info["s_xs"]]
                for x in pts:
                    viali_pad(c, x, y_mid)
                c.wire("metal1", [(min(pts), y_mid), (max(pts), y_mid)], W_M1)

        # 3. CM-killer series nodes (p_cmm / n_cmm, p_cmq / n_cmq) on M1 at diffusion mid-Y
        is_p_cm = (sgn > 0)
        for cm1_nm, cm2_nm in (("cm_m1", "cm_m2"), ("cm_q1", "cm_q2")):
            c1, c2 = cols[cm1_nm], cols[cm2_nm]
            i1 = c1["inf_p"] if is_p_cm else c1["inf_n"]
            i2 = c2["inf_p"] if is_p_cm else c2["inf_n"]
            y_mid = sgn_y(sgn, (i2["c_y1"] + i2["c_y2"]) / 2.0)
            pts = [grid(c1["cx"] + x) for x in i1["s_xs"]] + [grid(c2["cx"] + x) for x in i2["d_xs"]]
            for x in pts:
                viali_pad(c, x, y_mid)
            c.wire("metal1", [(min(pts), y_mid), (max(pts), y_mid)], W_M1)

        # 4. Horizontal M1 signal tracks & gate taps (offset clear of drain dx=0.00/+0.26!)
        y1 = sgn_y(sgn, Y_T1)
        y0 = sgn_y(sgn, Y_T0)
        y2 = sgn_y(sgn, Y_T2)

        xg_mp_d = wire_shared_inv_gate(cols["mp_d"], sgn, Y_T1, tap_dx=-0.460)
        xg_sp_d = wire_shared_inv_gate(cols["sp_d"], sgn, Y_T1, tap_dx=-0.460)
        xg_ob   = wire_shared_inv_gate(cols["ob"],   sgn, Y_T1, tap_dx=-0.460)

        for cm2_nm in ("cm_m2", "cm_q2"):
            c2 = cols[cm2_nm]
            # nf=2 on Top (g_xs=[-0.24,+0.24], d=0.00 -> offset gate tap to -0.46), nf=1 on Bot (g_xs=[0], d=+0.26 -> offset -0.22)
            tap_dx = -0.460 if (sgn > 0) else -0.220
            tie_poly_bars(c2, sgn, tie_n=(sgn < 0), tie_p=(sgn > 0), x_ext_l=tap_dx)
            xg_cm2 = tap_polycont(c2, sgn, is_p=(sgn > 0), y_trk=Y_T1, tap_dx=tap_dx)
            viali_pad(c, xg_cm2, y1)
            c2["xg"] = xg_cm2

        # Drains to y_t1
        for nm in ("mp_ck", "k_m", "sp_ck", "k_q", "ob"):
            col = cols[nm]
            xd_n = grid(col["cx"] + col["inf_n"]["d_xs"][0])
            xd_p = grid(col["cx"] + col["inf_p"]["d_xs"][0])
            locali_v(xd_n, sgn_y(sgn, col["inf_n"]["c_y2"] - 0.06), y1)
            locali_v(xd_p, y1, sgn_y(sgn, col["inf_p"]["c_y1"] + 0.06))
            if abs(xd_n - xd_p) > 1e-6:
                locali_h(xd_n, xd_p, y1)
            viali_pad(c, xd_p, y1)
            col["xd"] = xd_p

        for cm1_nm in ("cm_m1", "cm_q1"):
            c1 = cols[cm1_nm]
            i1 = c1["inf_p"] if (sgn > 0) else c1["inf_n"]
            xd = grid(c1["cx"] + i1["d_xs"][0])
            y_d = sgn_y(sgn, i1["c_y1"] + 0.06 if (sgn > 0) else i1["c_y2"] - 0.06)
            locali_v(xd, y1, y_d)
            viali_pad(c, xd, y1)
            c1["xd"] = xd

        # Main M1 track y_t1 for mp/mn (mp_ck.xd -> sp_d.xg) & qp_i/qn_i (sp_ck.xd -> ob.xg)
        c.wire("metal1", [(cols["mp_ck"]["xd"], y1), (xg_sp_d, y1)], W_M1)
        c.wire("metal1", [(cols["sp_ck"]["xd"], y1), (xg_ob, y1)], W_M1)

        # 5. Cross-coupled keeper + CM-killer gates at y_t0
        xg_km = wire_shared_inv_gate(cols["k_m"], sgn, Y_T0, tap_dx=-0.220)
        xg_kq = wire_shared_inv_gate(cols["k_q"], sgn, Y_T0, tap_dx=-0.220)
        cols["k_m"]["xg"] = xg_km
        cols["k_q"]["xg"] = xg_kq
        for cm1_nm, k_xg in (("cm_m1", xg_km), ("cm_q1", xg_kq)):
            c1 = cols[cm1_nm]
            tap_dx = -0.460 if (sgn > 0) else -0.220
            tie_poly_bars(c1, sgn, tie_n=(sgn < 0), tie_p=(sgn > 0), x_ext_l=tap_dx)
            xg_cm1 = tap_polycont(c1, sgn, is_p=(sgn > 0), y_trk=Y_T0, tap_dx=tap_dx)
            viali_pad(c, xg_cm1, y0)
            c.wire("metal1", [(k_xg, y0), (xg_cm1, y0)], W_M1)
            c1["xg"] = xg_cm1

        # 6. Clock gates on mp_ck & sp_ck: N-gate shifted LEFT (dx=-0.46 @ y_t0), P-gate shifted RIGHT (dx=+0.46 @ y_t2)
        for ck_nm in ("mp_ck", "sp_ck"):
            cck = cols[ck_nm]
            tie_poly_bars(cck, sgn, tie_n=True, tie_p=True, x_ext_l=-0.460, x_ext_r=+0.460)
            xg_ck_n = tap_polycont(cck, sgn, is_p=False, y_trk=Y_T0, tap_dx=-0.460)
            xg_ck_p = tap_polycont(cck, sgn, is_p=True,  y_trk=Y_T2, tap_dx=+0.460)
            viali_pad(c, xg_ck_n, y0)
            viali_pad(c, xg_ck_p, y2)
            cck[f"xn_{sgn}"] = xg_ck_n
            cck[f"xp_{sgn}"] = xg_ck_p

    # -------------------------------------------------------------------------
    # Inter-half M2 vertical crossovers + M3 clock & feedback rails
    # -------------------------------------------------------------------------
    # mp (+Y_T1 @ cm_m2.xg) -> down to -Y_T0 (k_m.xg .. cm_m1.xg)
    x_xm_p = cols["cm_m2"]["xg"]
    c.via1(x_xm_p, +Y_T1)
    c.wire("metal1", [(min(cols["k_m"]["xg"], cols["cm_m1"]["xg"], x_xm_p), -Y_T0),
                      (max(cols["k_m"]["xg"], cols["cm_m1"]["xg"], x_xm_p), -Y_T0)], W_M1)
    c.via1(x_xm_p, -Y_T0)
    c.wire("metal2", [(x_xm_p, -Y_T0), (x_xm_p, +Y_T1)], W_M2)

    # mn (-Y_T1 @ k_m.xg) -> up to +Y_T0 (k_m.xg .. cm_m1.xg)
    x_xm_n = cols["k_m"]["xg"]
    c.via1(x_xm_n, -Y_T1)
    c.via1(x_xm_n, +Y_T0)
    c.wire("metal2", [(x_xm_n, -Y_T1), (x_xm_n, +Y_T0)], W_M2)

    # qp_i (+Y_T1 @ cm_q2.xg) -> down to -Y_T0 AND to -Y_M3_FB
    x_xq_p = cols["cm_q2"]["xg"]
    c.via1(x_xq_p, +Y_T1)
    c.wire("metal1", [(min(cols["k_q"]["xg"], cols["cm_q1"]["xg"], x_xq_p), -Y_T0),
                      (max(cols["k_q"]["xg"], cols["cm_q1"]["xg"], x_xq_p), -Y_T0)], W_M1)
    c.via1(x_xq_p, -Y_T0)
    c.via2(x_xq_p, -Y_M3_FB)
    c.wire("metal2", [(x_xq_p, -Y_M3_FB), (x_xq_p, +Y_T1)], W_M2)

    # qn_i (-Y_T1 @ k_q.xg) -> up to +Y_T0 AND to +Y_M3_FB
    x_xq_n = cols["k_q"]["xg"]
    c.via1(x_xq_n, -Y_T1)
    c.via1(x_xq_n, +Y_T0)
    c.via2(x_xq_n, +Y_M3_FB)
    c.wire("metal2", [(x_xq_n, -Y_T1), (x_xq_n, +Y_M3_FB)], W_M2)

    # Feedback M3 bars back to mp_d (col 1): +Y_M3_FB -> Top mp_d.G; -Y_M3_FB -> Bot mp_d.G
    xg_fb = grid(cols["mp_d"]["cx"] - 0.460)
    c.wire("metal3", [(xg_fb, +Y_M3_FB), (x_xq_n, +Y_M3_FB)], W_M3)
    c.via2(xg_fb, +Y_M3_FB)
    c.via1(xg_fb, +Y_T1)
    c.wire("metal2", [(xg_fb, +Y_T1), (xg_fb, +Y_M3_FB)], W_M2)

    c.wire("metal3", [(xg_fb, -Y_M3_FB), (x_xq_p, -Y_M3_FB)], W_M3)
    c.via2(xg_fb, -Y_M3_FB)
    c.via1(xg_fb, -Y_T1)
    c.wire("metal2", [(xg_fb, -Y_M3_FB), (xg_fb, -Y_T1)], W_M2)

    # Clock distribution on M3 (+Y_M3_CK = ckp, -Y_M3_CK = ckn)
    x_ck_in = grid(x_l_wall - 0.160) if is_first else x_l_wall
    x_mp_ck_n = cols["mp_ck"]["xn_1"]
    x_mp_ck_p = cols["mp_ck"]["xp_1"]
    x_sp_ck_n = cols["sp_ck"]["xn_1"]
    x_sp_ck_p = cols["sp_ck"]["xp_1"]

    c.wire("metal3", [(x_ck_in, +Y_M3_CK), (x_sp_ck_p, +Y_M3_CK)], W_M3)
    c.via2(x_mp_ck_n, +Y_M3_CK)
    c.via1(x_mp_ck_n, +Y_T0)
    c.via1(x_mp_ck_n, -Y_T0)
    c.wire("metal2", [(x_mp_ck_n, -Y_T0), (x_mp_ck_n, +Y_M3_CK)], W_M2)

    c.via2(x_sp_ck_p, +Y_M3_CK)
    c.via1(x_sp_ck_p, +Y_T2)
    c.via1(x_sp_ck_p, -Y_T2)
    c.wire("metal2", [(x_sp_ck_p, -Y_T2), (x_sp_ck_p, +Y_M3_CK)], W_M2)

    c.wire("metal3", [(x_ck_in, -Y_M3_CK), (x_sp_ck_n, -Y_M3_CK)], W_M3)
    c.via2(x_mp_ck_p, -Y_M3_CK)
    c.via1(x_mp_ck_p, -Y_T2)
    c.via1(x_mp_ck_p, +Y_T2)
    c.wire("metal2", [(x_mp_ck_p, -Y_M3_CK), (x_mp_ck_p, +Y_T2)], W_M2)

    c.via2(x_sp_ck_n, -Y_M3_CK)
    c.via1(x_sp_ck_n, -Y_T0)
    c.via1(x_sp_ck_n, +Y_T0)
    c.wire("metal2", [(x_sp_ck_n, -Y_M3_CK), (x_sp_ck_n, +Y_T0)], W_M2)

    # Output qp / qn at ob.xd -> tap via M2 up/down to +-Y_M3_CK
    x_out = cols["ob"]["xd"]
    c.via1(x_out, +Y_T1)
    c.via2(x_out, +Y_M3_CK)
    c.wire("metal2", [(x_out, +Y_T1), (x_out, +Y_M3_CK)], W_M2)

    c.via1(x_out, -Y_T1)
    c.via2(x_out, -Y_M3_CK)
    c.wire("metal2", [(x_out, -Y_M3_CK), (x_out, -Y_T1)], W_M2)

    return {
        "x_l_wall": x_l_wall,
        "x_r_wall": x_r_wall,
        "x_ck_in": x_ck_in,
        "x_out": x_out,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_prescaler8_2g(out: Path) -> dict:
    cell = "pll_cmos_prescaler8_2g_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()

    stages_cfg = [
        ("div2", 2.4, 6.2, 3.0, 4.6, 0.7, 1.4),
        ("div4", 1.8, 4.6, 2.2, 4.2, 0.6, 1.3),
        ("div8", 1.5, 3.6, 2.0, 4.2, 0.6, 1.3),
    ]

    x_left_wall = 0.500
    x_cur_wall = x_left_wall
    all_n_s: list[float] = []
    all_p_pts: list[tuple[int, float]] = []
    walls: list[tuple[float, float]] = []
    st_info: list[dict] = []

    for idx, (nm, wn, wp, wbn, wbp, wcn, wcp) in enumerate(stages_cfg):
        info = build_div2_stage(c, w, nm, x_cur_wall, wn, wp, wbn, wbp, wcn, wcp, is_first=(idx == 0))
        hw_l = V_TAP_EDGE if idx == 0 else V_TAP_WALL
        walls.append((info["x_l_wall"], hw_l))
        st_info.append(info)
        all_n_s.extend(info["n_s_xs"])
        all_p_pts.extend(info["p_s_pts"])
        x_cur_wall = info["x_r_wall"]

    walls.append((x_cur_wall, V_TAP_EDGE))

    for k in range(2):
        xa = st_info[k]["x_out"]
        xb = st_info[k + 1]["x_ck_in"]
        c.wire("metal3", [(xa, +Y_M3_CK), (xb, +Y_M3_CK)], W_M3)
        c.wire("metal3", [(xa, -Y_M3_CK), (xb, -Y_M3_CK)], W_M3)

    x_rail_l = grid(x_left_wall - V_TAP_EDGE - 0.140)
    x_rail_r = grid(x_cur_wall + V_TAP_EDGE + 0.140)
    x_out_end = grid(x_rail_r + 0.450)
    c.wire("metal3", [(st_info[2]["x_out"], +Y_M3_CK), (x_out_end, +Y_M3_CK)], W_M3)
    c.wire("metal3", [(st_info[2]["x_out"], -Y_M3_CK), (x_out_end, -Y_M3_CK)], W_M3)

    # Wells
    x_wl = grid(x_rail_l - 0.220)
    x_wr = grid(x_out_end + 0.250)
    c.rect("pwell", x_wl, -Y_T1, x_wr, +Y_T1)
    c.rect("nwell", x_wl, +Y_T1, x_wr, grid(Y_VDD + 0.450))
    c.rect("nwell", x_wl, grid(-Y_VDD - 0.450), x_wr, -Y_T1)

    for xw, hw in walls:
        draw_np_wall_band(c, xw, Y_VSS, +Y_T1, +Y_VDD, hw)
        draw_np_wall_band(c, xw, Y_VSS, -Y_T1, -Y_VDD, hw)

    # Center VSS rail (M1 + M4 spine, never crossed by VDD M4!)
    draw_tap_h(c, "psubdiff", x_rail_l, x_rail_r, Y_VSS, H_TAP_VSS)
    c.wire("metal1", [(x_rail_l, Y_VSS), (x_rail_r, Y_VSS)], W_PWR_M1)
    c.wire("metal4", [(x_left_wall, Y_VSS), (x_rail_r, Y_VSS)], W_PWR_M4)
    for sx in sorted(set(all_n_s)):
        c.pad("viali", sx, Y_VSS, 0.17)
        c.pad("metal1", sx, Y_VSS, 0.32)
    for xw, _ in walls:
        c.pad("viali", xw, Y_VSS, 0.17)
        c.via1(xw, Y_VSS)
        c.via2(xw, Y_VSS)
        via3_pad(c, xw, Y_VSS)

    # Top and bottom VDD rails + clean external-left M4 bridge (clear of M4 VSS starting at x_left_wall!)
    x_vdd_bridge = grid(x_left_wall - 1.100)
    for sgn in (+1, -1):
        yv = grid(sgn * Y_VDD)
        draw_tap_h(c, "nsubdiff", x_rail_l, x_rail_r, yv, H_TAP_VDD)
        c.wire("metal1", [(x_rail_l, yv), (x_rail_r, yv)], W_PWR_M1)
        c.wire("metal2", [(x_rail_l, yv), (x_rail_r, yv)], W_PWR_M2)
        c.wire("metal3", [(x_rail_l, yv), (x_rail_r, yv)], W_PWR_M3)
        for px in sorted({x for s, x in all_p_pts if s == sgn}):
            c.pad("viali", px, yv, 0.17)
            c.pad("metal1", px, yv, 0.32)
        for xw, _ in walls:
            c.pad("viali", xw, yv, 0.17)
            c.via1(xw, yv)
            c.via2(xw, yv)
        via3_pad(c, x_left_wall, yv)
        c.wire("metal4", [(x_vdd_bridge, yv), (x_left_wall, yv)], W_PWR_M4)

    c.wire("metal4", [(x_vdd_bridge, -Y_VDD), (x_vdd_bridge, +Y_VDD)], W_PWR_M4)

    # Ports
    c.port("clkp", "metal3", st_info[0]["x_ck_in"], +Y_M3_CK)
    c.port("clkn", "metal3", st_info[0]["x_ck_in"], -Y_M3_CK)
    c.port("q2p",  "metal3", st_info[0]["x_out"],   +Y_M3_CK)
    c.port("q2n",  "metal3", st_info[0]["x_out"],   -Y_M3_CK)
    c.port("q4p",  "metal3", st_info[1]["x_out"],   +Y_M3_CK)
    c.port("q4n",  "metal3", st_info[1]["x_out"],   -Y_M3_CK)
    c.port("q8p",  "metal3", x_out_end,             +Y_M3_CK)
    c.port("q8n",  "metal3", x_out_end,             -Y_M3_CK)
    c.port("vdd",  "metal4", x_vdd_bridge,          +Y_VDD)
    c.port("vss",  "metal4", x_left_wall,           Y_VSS)

    mag_path = w / f"{cell}.mag"
    c.write(mag_path)

    ref_lines = [
        f"* PDK LVS reference netlist for {cell}",
        f".subckt {cell} clkp clkn q2p q2n q4p q4n q8p q8n vdd vss",
    ]

    def add_div2_ref(sn: str, ckp: str, ckn: str, qp: str, qn: str,
                     wn: float, wp: float, wbn: float, wbp: float, wcn: float, wcp: float) -> None:
        mp, mn = f"{sn}_mp", f"{sn}_mn"
        qpi, qni = f"{sn}_qpi", f"{sn}_qni"
        n1mp, n2mp, n1mn, n2mn = f"{sn}_n1mp", f"{sn}_n2mp", f"{sn}_n1mn", f"{sn}_n2mn"
        n1sp, n2sp, n1sn, n2sn = f"{sn}_n1sp", f"{sn}_n2sp", f"{sn}_n1sn", f"{sn}_n2sn"
        pcmm, ncmm, pcmq, ncmq = f"{sn}_pcmm", f"{sn}_ncmm", f"{sn}_pcmq", f"{sn}_ncmq"
        ref_lines.extend([
            f"X{sn}_mp_p1 {n1mp} {qni} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_mp_p2 {mp} {ckn} {n1mp} vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_mp_n1 {mp} {ckp} {n2mp} vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_mp_n2 {n2mp} {qni} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_mn_p1 {n1mn} {qpi} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_mn_p2 {mn} {ckn} {n1mn} vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_mn_n1 {mn} {ckp} {n2mn} vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_mn_n2 {n2mn} {qpi} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_kmp_n {mp} {mn} vss vss sky130_fd_pr__nfet_01v8 w=0.6 l=0.15",
            f"X{sn}_kmp_p {mp} {mn} vdd vdd sky130_fd_pr__pfet_01v8 w=1.3 l=0.15",
            f"X{sn}_kmn_n {mn} {mp} vss vss sky130_fd_pr__nfet_01v8 w=0.6 l=0.15",
            f"X{sn}_kmn_p {mn} {mp} vdd vdd sky130_fd_pr__pfet_01v8 w=1.3 l=0.15",
            f"X{sn}_cmmn1 {mn} {mp} {ncmm} vss sky130_fd_pr__nfet_01v8 w={wcn} l=0.15",
            f"X{sn}_cmmn2 {ncmm} {mn} vss vss sky130_fd_pr__nfet_01v8 w={wcn} l=0.15",
            f"X{sn}_cmmp1 {mp} {mn} {pcmm} vdd sky130_fd_pr__pfet_01v8 w={wcp} l=0.15",
            f"X{sn}_cmmp2 {pcmm} {mp} vdd vdd sky130_fd_pr__pfet_01v8 w={wcp} l=0.15",
            f"X{sn}_sp_p1 {n1sp} {mp} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_sp_p2 {qpi} {ckp} {n1sp} vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_sp_n1 {qpi} {ckn} {n2sp} vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_sp_n2 {n2sp} {mp} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_sn_p1 {n1sn} {mn} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_sn_p2 {qni} {ckp} {n1sn} vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{sn}_sn_n1 {qni} {ckn} {n2sn} vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_sn_n2 {n2sn} {mn} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{sn}_kqp_n {qpi} {qni} vss vss sky130_fd_pr__nfet_01v8 w=0.6 l=0.15",
            f"X{sn}_kqp_p {qpi} {qni} vdd vdd sky130_fd_pr__pfet_01v8 w=1.3 l=0.15",
            f"X{sn}_kqn_n {qni} {qpi} vss vss sky130_fd_pr__nfet_01v8 w=0.6 l=0.15",
            f"X{sn}_kqn_p {qni} {qpi} vdd vdd sky130_fd_pr__pfet_01v8 w=1.3 l=0.15",
            f"X{sn}_cmqn1 {qni} {qpi} {ncmq} vss sky130_fd_pr__nfet_01v8 w={wcn} l=0.15",
            f"X{sn}_cmqn2 {ncmq} {qni} vss vss sky130_fd_pr__nfet_01v8 w={wcn} l=0.15",
            f"X{sn}_cmqp1 {qpi} {qni} {pcmq} vdd sky130_fd_pr__pfet_01v8 w={wcp} l=0.15",
            f"X{sn}_cmqp2 {pcmq} {qpi} vdd vdd sky130_fd_pr__pfet_01v8 w={wcp} l=0.15",
            f"X{sn}_obp_n {qp} {qpi} vss vss sky130_fd_pr__nfet_01v8 w={wbn} l=0.15",
            f"X{sn}_obp_p {qp} {qpi} vdd vdd sky130_fd_pr__pfet_01v8 w={wbp} l=0.15",
            f"X{sn}_obn_n {qn} {qni} vss vss sky130_fd_pr__nfet_01v8 w={wbn} l=0.15",
            f"X{sn}_obn_p {qn} {qni} vdd vdd sky130_fd_pr__pfet_01v8 w={wbp} l=0.15",
        ])

    add_div2_ref("d2", "clkp", "clkn", "q2p", "q2n", 2.4, 6.2, 3.0, 4.6, 0.7, 1.4)
    add_div2_ref("d4", "q2p",  "q2n",  "q4p", "q4n", 1.8, 4.6, 2.2, 4.2, 0.6, 1.3)
    add_div2_ref("d8", "q4p",  "q4n",  "q8p", "q8n", 1.5, 3.6, 2.0, 4.2, 0.6, 1.3)
    ref_lines.extend([f".ends {cell}", ""])

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
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(mag_path), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(mag_path).bbox()
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

    r = build_prescaler8_2g(out)
    print(
        f"{r['cell']:30s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
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
