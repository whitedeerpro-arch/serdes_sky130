#!/usr/bin/env python3
"""Build 3D Under-MIM Stacked Fused SKY130 PDK Loop Filter (pll_loop_filter_k4_fused_pdk v2).

Implements ``pll_loop_filter_k4_fused`` from ``analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice``:
- PCell-compliant stacked MIM fusion (w = l = 27.22 um <= 30.0 um guard -> 1.500 pF/layer,
  3.000 pF/site across M3-M4 + M4-M5) arranged as a 3x2 1D common-centroid [VDD, VSS, VDD]
  array (6 sites = 6 MIM1 + 6 MIM2 = 18.00 pF total: 6 pF z-vss + 12 pF z-vdd).
- v2 Compact Bus & Under-MIM Overhaul (98.34 x 64.90 um = 6,382.3 um2, -7.4% vs v1 6,893.6 um2):
  * Top M4 ``z`` bus tightened to mbbox[3]+0.80 (+30.02) and Col 1 VSS M5/M3 strap tightened
    to mbbox[3]+2.43 (+31.65, met5.2 = 1.63 um >= 1.60 um), cutting 3.17 um from top overhead.
  * Bottom Col 0/2 VDD M5 bus tightened to mbbox[1]-2.43 (-31.65, met5.2 = 1.63 um) without a
    redundant M3 cross-bar across Col 1, allowing the ``ctrl`` M3 port (-32.00) to sit flush
    inside the bottom macro boundary (-32.45), cutting 2.03 um from bottom overhead.
  * Under-MIM active island [Xinv, Xint, Xfast] (15.4 x 9.1 um, -18.4% CMOS island area) and
    Xrz (+ 2 grounded 0.69 um poly dummies) packed tightly into Col 1 Row 0 (y ~ -20.0 um)
    strictly beneath the VSS-grounded M3 bottom plate: zero M2 bridges over Xrz, zero VDD
    hop over Xrz, and ~2.5x shorter ``ctrl`` route (~14 um vs ~35 um) slashing ``ctrl`` CPEX cap.
  * Preserves all 2026-11-17 review fixes: 12 biased gate-length-matched field-poly MOS dummies
    (6 NMOS -> VSS, 6 PMOS -> VDD), 2 grounded Xrz poly dummies, 0 floating non-device poly,
    shared P+/N+ dual guard frame, and continuous NWELL.
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

MIM1 = "sky130_fd_pr__cap_mim_m3_1"
MIM2 = "sky130_fd_pr__cap_mim_m3_2"
SIDE = 27.22


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def via4(c: Cell, x: float, y: float) -> None:
    c.pad("metal4", x, y, 1.60)
    c.pad("via4", x, y, 1.18)
    c.pad("metal5", x, y, 1.60)


def clean_prim(work: Path, name: str, model: str, params: dict) -> Cell:
    p = pdk_device(work, name, model, params)
    p.rects.pop("checkpaint", None)
    return p


def draw_mim_3x2_stacked(
    work: Path,
) -> tuple[Cell, list[tuple[float, float]], list[tuple[float, float]], list[tuple[float, float]], tuple[float, float, float, float]]:
    lower = pdk_device(work, "mim_lower_3x2", MIM1, dict(w=SIDE, l=SIDE, nx=3, ny=2, stack=1, doports=1))
    upper = pdk_device(work, "mim_upper_3x2", MIM2, dict(w=SIDE, l=SIDE, nx=3, ny=2, doports=1))
    for cell in (lower, upper):
        cell.rects.pop("checkpaint", None)

    lp = sorted(lower.rects["mimcapcontact"], key=lambda r: (r[0], r[1]))
    up = sorted([(-r[2], r[1], -r[0], r[3]) for r in upper.rects["mimcap2contact"]], key=lambda r: (r[0], r[1]))
    if len(lp) != 6 or len(up) != 6:
        raise ValueError(f"Expected 6 stacked recognition plates, got lower={len(lp)} upper={len(up)}")
    dx = grid((lp[0][0] + lp[0][2] - up[0][0] - up[0][2]) / 2.0)
    dy = grid((lp[0][1] + lp[0][3] - up[0][1] - up[0][3]) / 2.0)
    for a, b in zip(lp, up):
        if max(abs(a[k] - b[k] - (dx if k % 2 == 0 else dy)) for k in range(4)) > 0.01:
            raise ValueError("PDK stack-compatible 3x2 MIM arrays do not align")

    top_m4 = sorted((x, y) for _, x, y, lbl in lower.labels if lbl.startswith("C1"))
    bot_m3 = sorted((x, y) for _, x, y, lbl in lower.labels if lbl.startswith("C2"))
    top_m5 = sorted((grid(-x + dx), grid(y + dy)) for _, x, y, lbl in upper.labels if lbl.startswith("C1"))
    if any(len(v) != 3 for v in (top_m4, bot_m3, top_m5)):
        raise ValueError(f"Unexpected stacked column pin counts: {len(top_m4)}, {len(bot_m3)}, {len(top_m5)}")

    lower.labels.clear()
    upper.labels.clear()
    comb = Cell()
    comb.include(lower)
    comb.include(upper, dx=dx, dy=dy, mirror_x=True)
    return comb, top_m4, bot_m3, top_m5, comb.bbox()


def place_w2_mos(
    c: Cell,
    prim: Cell,
    cut_layer: str,
    dx: float,
    dy: float,
    is_pmos: bool,
) -> dict:
    """Place compact guard=0 w=2.0 um MOSFET (PMOS mirrored so G faces inward), strap S/D directly over diff on M2."""
    c.include(prim, dx=dx, dy=dy, mirror_y=is_pmos)
    sds = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    s_xs = sds[::2]
    d_xs = sds[1::2]
    if is_pmos:
        s_bus_y, d_bus_y = grid(dy + 0.48), grid(dy - 0.48)
        gy = grid(dy - prim.pins("G")[0][1])
    else:
        s_bus_y, d_bus_y = grid(dy - 0.48), grid(dy + 0.48)
        gy = grid(dy + prim.pins("G")[0][1])

    for sx in s_xs:
        c.via1(sx, s_bus_y)
    for sx in d_xs:
        c.via1(sx, d_bus_y)
    if len(s_xs) > 1:
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.28)
    if len(d_xs) > 1:
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.28)

    gx0 = grid(dx + min(p[0] for p in prim.pins("G")))
    df_layer = "pdiff" if is_pmos else "ndiff"
    x_df_min = min(r[0] for r in prim.rects[df_layer]) + dx
    x_df_max = max(r[2] for r in prim.rects[df_layer]) + dx
    mk = next(k for k in ("pmoslvt", "pmos", "nmoslvt", "nmos") if k in prim.rects)
    l_f = grid(prim.rects[mk][0][2] - prim.rects[mk][0][0])
    py_lo = min(r[1] for r in prim.rects["poly"])
    py_hi = max(r[3] for r in prim.rects["poly"])
    poly_y1 = grid(dy - py_hi) if is_pmos else grid(dy + py_lo)
    poly_y2 = grid(dy - py_lo) if is_pmos else grid(dy + py_hi)
    # Escape gate left past dummy poly with clean M1 clearance
    gx_esc = grid(x_df_min - l_f - 0.48)
    c.wire("metal1", [(gx_esc, gy), (gx0, gy)], 0.20)
    c.via1(gx_esc, gy)

    return {
        "s_xs": s_xs,
        "d_xs": d_xs,
        "s_bus_y": s_bus_y,
        "d_bus_y": d_bus_y,
        "g_pt": (gx_esc, gy),
        "x_min": grid(x_df_min),
        "x_max": grid(x_df_max),
        "l_f": l_f,
        "poly_y1": poly_y1,
        "poly_y2": poly_y2,
    }


def add_mos_poly_dummy(
    c: Cell,
    x_dum: float,
    l_f: float,
    dy: float,
    is_pmos: bool,
    y_rail: float,
    y_poly_inner: float,
    side_sign: int = 0,
) -> None:
    """Place biased field-poly dummy gate (matching transistor L and inner poly span) tied to VDD/VSS."""
    hw = grid(l_f / 2.0)
    y_cont = grid(dy + 1.32) if is_pmos else grid(dy - 1.32)
    if is_pmos:
        c.rect("poly", grid(x_dum - hw), grid(y_poly_inner), grid(x_dum + hw), grid(y_cont + 0.17))
    else:
        c.rect("poly", grid(x_dum - hw), grid(y_cont - 0.17), grid(x_dum + hw), grid(y_poly_inner))
    x_cont = grid(x_dum + side_sign * 0.060) if l_f < 0.28 else x_dum
    c.pad("poly", x_cont, y_cont, 0.28, 0.34)
    c.pad("polycont", x_cont, y_cont, 0.17, 0.17)
    c.pad("locali", x_cont, y_cont, 0.18, 0.34)
    c.rect("locali", grid(x_cont - 0.085), min(y_cont, y_rail), grid(x_cont + 0.085), max(y_cont, y_rail))


def draw_compact_np_frame(
    c: Cell,
    x1: float,
    x2: float,
    y_vss: float,
    y_vdd: float,
    y_mid: float,
    step: float = 1.40,
) -> None:
    """Draw merged N/P dual guard frame around CMOS island centered at y_mid."""
    x1g, x2g = grid(x1), grid(x2)
    yvss, yvdd = grid(y_vss), grid(y_vdd)
    for yy, is_nw in ((yvss, False), (yvdd, True)):
        dl = "nsubdiff" if is_nw else "psubdiff"
        cl = "nsubdiffcont" if is_nw else "psubdiffcont"
        c.rect(dl, grid(x1g - 0.18), grid(yy - 0.18), grid(x2g + 0.18), grid(yy + 0.18))
        c.rect("locali", grid(x1g - 0.14), grid(yy - 0.14), grid(x2g + 0.14), grid(yy + 0.14))
        xc = grid(x1g + 0.25)
        while xc <= x2g - 0.25 + 1e-6:
            c.pad(cl, xc, yy, 0.17)
            if abs((xc - x1g - 0.25) % step) < 0.05 or abs(xc - (x2g - 0.25)) < 0.5:
                c.pad("viali", xc, yy, 0.17)
                c.pad("metal1", xc, yy, 0.34)
            xc = grid(xc + 0.50)
    for xx in (x1g, x2g):
        for dl, cl, ylo, yhi in (
            ("psubdiff", "psubdiffcont", yvss, grid(y_mid - 1.50)),
            ("nsubdiff", "nsubdiffcont", grid(y_mid + 1.50), yvdd),
        ):
            c.rect(dl, grid(xx - 0.18), ylo, grid(xx + 0.18), yhi)
            c.rect("locali", grid(xx - 0.14), ylo, grid(xx + 0.14), yhi)
            yc = grid(ylo + 0.45)
            while yc <= yhi - 0.35 + 1e-6:
                c.pad(cl, xx, yc, 0.17)
                yc = grid(yc + 0.50)


def build_lf_k4_fused(out: Path) -> dict:
    cell = "pll_loop_filter_k4_fused_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    mim_c, top_m4, bot_m3, top_m5, mbbox = draw_mim_3x2_stacked(w)
    rz = clean_prim(w, "rz_pdk", "sky130_fd_pr__res_high_po_0p69", dict(l=7.59))
    n2 = clean_prim(w, "n2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=2, conn_gates=1, guard=0))
    n4 = clean_prim(w, "n4_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1, guard=0))
    p4 = clean_prim(w, "p4_pdk", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1, guard=0))
    pl4 = clean_prim(w, "pl4_pdk", "sky130_fd_pr__pfet_01v8_lvt", dict(w=2.0, l=0.35, nf=4, conn_gates=1, guard=0))
    pl8 = clean_prim(w, "pl8_pdk", "sky130_fd_pr__pfet_01v8_lvt", dict(w=2.0, l=0.35, nf=8, conn_gates=1, guard=0))

    c = Cell()
    c.include(mim_c)

    # 1. Tightened Stacked MIM Buses (met4.2 >= 0.35 um, met5.2 = 1.63 um >= 1.60 um):
    #    - Shared M4 plate `z` at upper_z = mbbox[3] + 0.80 (+30.02, M4 y = 29.57..30.47)
    #    - Center Col 1 (VSS) M3 & M5 strap at top_vss = mbbox[3] + 2.43 (+31.65, top = +32.45)
    #    - Outer Col 0 & Col 2 (VDD) joined on M5 at lower_vdd = mbbox[1] - 2.43 (-31.65, bot = -32.45)
    #      leaving M3 completely open across Col 1 so `ctrl` port sits flush inside -32.45!
    upper_z = grid(mbbox[3] + 0.80)     # +30.02
    top_vss = grid(mbbox[3] + 2.43)     # +31.65 (M5 bot = +30.85 -> 1.63 um to +29.22; via4 M4 bot = +30.85 -> 0.38 um to upper_z)
    lower_vdd = grid(mbbox[1] - 2.43)   # -31.65 (M5 top = -30.85 -> 1.63 um to -29.22)

    x_z_top_riser = 11.40
    for x, y in top_m4:
        c.rect("metal4", grid(x - 0.50), y, grid(x + 0.50), grid(upper_z + 0.45))
    c.rect("metal4", grid(top_m4[0][0] - 0.60), grid(upper_z - 0.45),
           grid(max(top_m4[-1][0], x_z_top_riser) + 0.60), grid(upper_z + 0.45))

    # Col 1 (idx=1) -> VSS at top_vss
    x_c1_m3, y_c1_m3 = bot_m3[1]
    x_c1_m5, y_c1_m5 = top_m5[1]
    c.rect("metal3", grid(x_c1_m3 - 0.40), y_c1_m3, grid(x_c1_m3 + 0.40), grid(top_vss + 0.40))
    c.rect("metal5", grid(x_c1_m5 - 0.80), y_c1_m5, grid(x_c1_m5 + 0.80), grid(top_vss + 0.80))
    c.wire("metal5", [(x_c1_m5, top_vss), (x_c1_m3, top_vss)], 1.60)
    via3(c, x_c1_m3, top_vss)
    via4(c, x_c1_m3, top_vss)

    # Col 0 & Col 2 (idx=0, 2) -> VDD at lower_vdd (M5 cross-bar only; local M3 drops at Col 0 & Col 2)
    for idx in (0, 2):
        xm3, ym3 = bot_m3[idx]
        xm5, ym5 = top_m5[idx]
        c.rect("metal3", grid(xm3 - 0.40), grid(lower_vdd - 0.40), grid(xm3 + 0.40), ym3)
        c.rect("metal5", grid(xm5 - 0.80), grid(lower_vdd - 0.80), grid(xm5 + 0.80), ym5)
        via3(c, xm3, lower_vdd)
        via4(c, xm3, lower_vdd)
    c.rect("metal5", grid(top_m5[0][0] - 0.80), grid(lower_vdd - 0.80),
           grid(bot_m3[2][0] + 0.80), grid(lower_vdd + 0.80))

    # 2. Compact Under-MIM Island in Col 1 Row 0 VSS Shield (y0 = -20.00, strictly under Col 1 M3!)
    #    Order: [Xinv, Xint, Xfast] on left, Xrz (+ 2 grounded poly dummies) on right ->
    #      * ZERO bridges over Xrz for pre_ref / pre_en / vdd
    #      * Shortest possible ctrl route (Xfast -> Xrz bot -> flush ctrl port at -32.00)
    y0 = -20.00
    y_rz_vss_m1 = grid(y0 - 6.80)       # -26.80
    y_nmos_vss_m1 = grid(y0 - 4.70)     # -24.70
    y_preen_m1 = grid(y0 - 0.90)        # -20.90
    y_preb_m1 = grid(y0 - 0.45)         # -20.45
    y_preref_m1 = grid(y0 + 0.00)       # -20.00
    y_ctrl_m1 = grid(y0 + 0.45)         # -19.55
    y_z_m1 = grid(y0 + 0.90)            # -19.10
    y_pmos_vdd_m1 = grid(y0 + 4.70)     # -15.30

    dy_n, dy_p = grid(y0 - 2.75), grid(y0 + 2.75)  # -22.75, -17.25
    dx_inv, dx_int, dx_fast = -9.50, -4.10, 2.20

    in_n = place_w2_mos(c, n2, "ndiffc", dx_inv, dy_n, False)
    in_p = place_w2_mos(c, p4, "pdiffc", dx_inv, dy_p, True)
    it_n = place_w2_mos(c, n4, "ndiffc", dx_int, dy_n, False)
    it_p = place_w2_mos(c, pl8, "pdiffc", dx_int, dy_p, True)
    fn = place_w2_mos(c, n2, "ndiffc", dx_fast, dy_n, False)
    fp = place_w2_mos(c, pl4, "pdiffc", dx_fast, dy_p, True)

    # Biased gate-length-matched field-poly dummy gates flanking EVERY NMOS (-> VSS) & PMOS (-> VDD)
    dum_gap = 0.075
    for dev, dy_m, is_p, y_rail in (
        (in_n, dy_n, False, y_nmos_vss_m1),
        (it_n, dy_n, False, y_nmos_vss_m1),
        (fn, dy_n, False, y_nmos_vss_m1),
        (in_p, dy_p, True, y_pmos_vdd_m1),
        (it_p, dy_p, True, y_pmos_vdd_m1),
        (fp, dy_p, True, y_pmos_vdd_m1),
    ):
        lf = dev["l_f"]
        y_inner = dev["poly_y1"] if is_p else dev["poly_y2"]
        for side_sign, x_d in (
            (-1, grid(dev["x_min"] - dum_gap - lf / 2.0)),
            (+1, grid(dev["x_max"] + dum_gap + lf / 2.0)),
        ):
            add_mos_poly_dummy(c, x_d, lf, dy_m, is_p, y_rail, y_inner, side_sign=side_sign)

    gr_x1, gr_x2 = -11.90, 4.75
    c.rect("nwell", grid(gr_x1 - 0.45), grid(dy_p - 1.55), grid(gr_x2 + 0.45), grid(y_pmos_vdd_m1 + 0.45))
    draw_compact_np_frame(c, gr_x1, gr_x2, y_nmos_vss_m1, y_pmos_vdd_m1, y0)

    # Xrz on right side of Col 1 (dx_rz = +8.30, dy_rz = -20.00) + 2 grounded flanking 0.69 um poly dummies
    dx_rz, dy_rz = 8.30, y0
    c.include(rz, dx=dx_rz, dy=dy_rz)
    rz_by = grid(dy_rz + rz.pins("B")[0][1])
    rz_gl, rz_gr = grid(dx_rz - 0.91), grid(dx_rz + 0.91)
    rz_gb, rz_gt = rz_by, grid(dy_rz + 6.44)
    for xg, yg in [
        (rz_gl, rz_gb), (dx_rz, rz_gb), (rz_gr, rz_gb),
        (rz_gl, rz_gt), (dx_rz, rz_gt), (rz_gr, rz_gt),
        (rz_gl, dy_rz), (rz_gr, dy_rz),
        (rz_gl, grid(dy_rz - 3.20)), (rz_gr, grid(dy_rz - 3.20)),
        (rz_gl, grid(dy_rz + 3.20)), (rz_gr, grid(dy_rz + 3.20)),
    ]:
        c.pad("viali", xg, yg, 0.17)
        c.pad("metal1", xg, yg, 0.32)
    c.wire("metal1", [(rz_gl, rz_gb), (rz_gl, rz_gt), (rz_gr, rz_gt), (rz_gr, rz_gb), (rz_gl, rz_gb)], 0.30)
    c.wire("metal1", [(dx_rz, rz_by), (dx_rz, y_rz_vss_m1)], 0.32)

    for x_rdum in (grid(dx_rz - 1.65), grid(dx_rz + 1.65)):
        c.rect("poly", grid(x_rdum - 0.345), grid(y0 - 6.40), grid(x_rdum + 0.345), grid(y0 + 5.875))
        c.pad("polycont", x_rdum, grid(y0 - 6.20), 0.17, 0.17)
        c.pad("locali", x_rdum, grid(y0 - 6.20), 0.34, 0.34)
        c.pad("viali", x_rdum, grid(y0 - 6.20), 0.17)
        c.pad("metal1", x_rdum, grid(y0 - 6.20), 0.32)
        c.wire("metal1", [(x_rdum, grid(y0 - 6.20)), (x_rdum, y_rz_vss_m1)], 0.30)

    y_rz_r2 = grid(dy_rz - 4.80)   # ctrl end (-24.80)
    y_rz_r1 = grid(dy_rz + 4.80)   # z end (-15.20)
    c.via1(dx_rz, y_rz_r2)
    c.via1(dx_rz, y_rz_r1)

    # VSS M1 rails -> M2 trunk at x_c1_m3 (+14.43) -> top_vss (+31.65)
    # CMOS VSS rail connects down at gr_x2 (+4.15) to y_rz_vss_m1 (-26.80) to clear Xrz M1 guard cleanly!
    x_vss_m2 = x_c1_m3
    c.wire("metal1", [(gr_x1, y_nmos_vss_m1), (gr_x2, y_nmos_vss_m1), (gr_x2, y_rz_vss_m1),
                      (x_vss_m2, y_rz_vss_m1)], 0.44)
    c.via1(x_vss_m2, y_rz_vss_m1)
    c.wire("metal2", [(x_vss_m2, y_rz_vss_m1), (x_vss_m2, top_vss)], 0.56)
    c.via2(x_vss_m2, top_vss)

    # VDD M1 rail exits straight LEFT from CMOS island (ZERO hop over Xrz!) -> x_vdd_m2 (-18.28) -> lower_vdd
    x_vdd_m2 = bot_m3[0][0]
    c.wire("metal1", [(x_vdd_m2, y_pmos_vdd_m1), (gr_x2, y_pmos_vdd_m1)], 0.44)
    c.via1(x_vdd_m2, y_pmos_vdd_m1)
    c.wire("metal2", [(x_vdd_m2, lower_vdd), (x_vdd_m2, y_pmos_vdd_m1)], 0.56)
    c.via2(x_vdd_m2, lower_vdd)

    # Xinv wiring
    c.wire("metal2", [(in_n["s_xs"][0], in_n["s_bus_y"]), (in_n["s_xs"][0], y_nmos_vss_m1)], 0.28)
    c.via1(in_n["s_xs"][0], y_nmos_vss_m1)
    c.wire("metal2", [(in_p["s_xs"][0], in_p["s_bus_y"]), (in_p["s_xs"][0], y_pmos_vdd_m1)], 0.28)
    c.via1(in_p["s_xs"][0], y_pmos_vdd_m1)
    c.wire("metal2", [(dx_inv, in_n["d_bus_y"]), (dx_inv, in_p["d_bus_y"])], 0.30)
    c.via1(dx_inv, y_preb_m1)

    # Gate ties to pre_en & pre_b (direct horizontal M1 from left port, ZERO bridges over Xrz!)
    for gpt in (in_n["g_pt"], in_p["g_pt"], it_n["g_pt"], fn["g_pt"]):
        c.wire("metal2", [gpt, (gpt[0], y_preen_m1)], 0.24)
        c.via1(gpt[0], y_preen_m1)
    for gpt in (it_p["g_pt"], fp["g_pt"]):
        c.wire("metal2", [gpt, (gpt[0], y_preb_m1)], 0.24)
        c.via1(gpt[0], y_preb_m1)

    x_sig_port = grid(mbbox[0] + 0.80)  # -49.60, under Col 0 M5 overhang & clear of Col 0 M3 (-47.40)
    c.wire("metal1", [(x_sig_port, y_preen_m1), (fn["g_pt"][0], y_preen_m1)], 0.22)
    c.via1(x_sig_port, y_preen_m1)
    c.via2(x_sig_port, y_preen_m1)
    c.pad("metal3", x_sig_port, y_preen_m1, 0.52)

    c.wire("metal1", [(dx_inv, y_preb_m1), (fp["g_pt"][0], y_preb_m1)], 0.22)

    # pre_ref direct horizontal M1 from x_sig_port to Xint.S and Xfast.S (ZERO bridges over Xrz!)
    x_int_ref = grid(it_p["s_xs"][-1] + 0.55)
    c.wire("metal2", [(it_n["s_xs"][-1], it_n["s_bus_y"]), (x_int_ref, it_n["s_bus_y"]),
                      (x_int_ref, it_p["s_bus_y"]), (it_p["s_xs"][-1], it_p["s_bus_y"])], 0.24)
    c.via1(x_int_ref, y_preref_m1)

    x_fast_ref = grid(fp["s_xs"][-1] + 0.55)
    c.wire("metal2", [(fn["s_xs"][-1], fn["s_bus_y"]), (x_fast_ref, fn["s_bus_y"]),
                      (x_fast_ref, fp["s_bus_y"]), (fp["s_xs"][-1], fp["s_bus_y"])], 0.24)
    c.via1(x_fast_ref, y_preref_m1)

    c.wire("metal1", [(x_sig_port, y_preref_m1), (x_fast_ref, y_preref_m1)], 0.22)
    c.via1(x_sig_port, y_preref_m1)
    c.via2(x_sig_port, y_preref_m1)
    c.pad("metal3", x_sig_port, y_preref_m1, 0.52)

    # Xfast node b = ctrl -> ultra-short M2 route directly into Xrz bottom (-24.80) & flush bottom port (-32.00)!
    c.wire("metal2", [(dx_fast, fn["d_bus_y"]), (dx_fast, fp["d_bus_y"])], 0.30)
    c.via1(dx_fast, y_ctrl_m1)
    x_ctrl_drop = 5.95
    c.wire("metal1", [(dx_fast, y_ctrl_m1), (x_ctrl_drop, y_ctrl_m1)], 0.24)
    c.via1(x_ctrl_drop, y_ctrl_m1)
    y_ctrl_port = -32.00  # flush inside lower_vdd M5 (-32.45), clear of Col 1 M3 (-28.42), M3 open across Col 1!
    c.wire("metal2", [(x_ctrl_drop, y_ctrl_m1), (x_ctrl_drop, y_rz_r2),
                      (dx_rz, y_rz_r2), (dx_rz, y_ctrl_port)], 0.38)
    c.via2(dx_rz, y_ctrl_port)
    c.pad("metal3", dx_rz, y_ctrl_port, 0.52)

    # Xint node b = z -> M1 across channel to x_z_up=+5.35 (clears it_p source bus & Xrz!) -> M2 up to y_z_hop -> Xrz top -> upper_z
    c.wire("metal2", [(dx_int, it_n["d_bus_y"]), (dx_int, it_p["d_bus_y"])], 0.32)
    c.via1(dx_int, y_z_m1)
    x_z_up = 5.35
    c.wire("metal1", [(dx_int, y_z_m1), (x_z_up, y_z_m1)], 0.24)
    c.via1(x_z_up, y_z_m1)
    y_z_hop = grid(y_pmos_vdd_m1 + 2.30)  # -13.00 (clears CMOS nwell & Xrz guard top)
    c.wire("metal2", [(x_z_up, y_z_m1), (x_z_up, y_z_hop),
                      (x_z_top_riser, y_z_hop), (x_z_top_riser, upper_z)], 0.44)
    c.wire("metal2", [(dx_rz, y_rz_r1), (dx_rz, y_z_hop)], 0.40)
    c.via2(x_z_top_riser, upper_z)
    via3(c, x_z_top_riser, upper_z)

    # Export exact port order: ctrl z pre_ref pre_en vdd vss
    c.port("ctrl", "metal3", dx_rz, y_ctrl_port)
    c.port("z", "metal4", top_m4[0][0], upper_z)
    c.port("pre_ref", "metal3", x_sig_port, y_preref_m1)
    c.port("pre_en", "metal3", x_sig_port, y_preen_m1)
    c.port("vdd", "metal3", bot_m3[0][0], lower_vdd)
    c.port("vss", "metal3", x_c1_m3, top_vss)
    c.write(w / f"{cell}.mag")

    rx1, ry1 = round((dx_rz - 0.64) * 200), round((dy_rz - 6.08) * 200)
    rx2, ry2 = round((dx_rz + 0.64) * 200), round((dy_rz + 6.08) * 200)
    mag_txt = (w / f"{cell}.mag").read_text()
    mag_txt = mag_txt.replace("<< end >>", f"<< properties >>\nstring MASKHINTS_RPM {rx1} {ry1} {rx2} {ry2}\n<< end >>")
    (w / f"{cell}.mag").write_text(mag_txt)

    ref_lines = [
        "* Physical LVS reference for pll_loop_filter_k4_fused (Vlink cp_in ctrl 0 merged into ctrl)",
        f".subckt {cell} ctrl z pre_ref pre_en vdd vss",
        "Xrz ctrl z vss sky130_fd_pr__res_high_po_0p69 l=7.594",
    ]
    for i in range(2):
        ref_lines.append(f"Xcg1_{i} z vss {MIM1} w={SIDE} l={SIDE}")
        ref_lines.append(f"Xcg2_{i} vss z {MIM2} w={SIDE} l={SIDE}")
    for i in range(4):
        ref_lines.append(f"Xcv1_{i} z vdd {MIM1} w={SIDE} l={SIDE}")
        ref_lines.append(f"Xcv2_{i} vdd z {MIM2} w={SIDE} l={SIDE}")
    ref_lines += [
        "Xinv_n pre_b pre_en vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xinv_p pre_b pre_en vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xfast_n pre_ref pre_en ctrl vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xfast_p pre_ref pre_b ctrl vdd sky130_fd_pr__pfet_01v8_lvt w=8 l=0.35",
        "Xint_n pre_ref pre_en z vss sky130_fd_pr__nfet_01v8 w=8 l=0.15",
        "Xint_p pre_ref pre_b z vdd sky130_fd_pr__pfet_01v8_lvt w=16 l=0.35",
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    mims1 = re.findall(rf"^X\S+ (\S+) (\S+) {MIM1} l=([\d.]+) w=([\d.]+)$", lvs_spice, re.M)
    mims2 = re.findall(rf"^X\S+ (\S+) (\S+) {MIM2} l=([\d.]+) w=([\d.]+)$", lvs_spice, re.M)
    c1_vss = sum(1 for a, b, _, _ in mims1 if {a, b} == {"z", "vss"})
    c1_vdd = sum(1 for a, b, _, _ in mims1 if {a, b} == {"z", "vdd"})
    c2_vss = sum(1 for a, b, _, _ in mims2 if {a, b} == {"z", "vss"})
    c2_vdd = sum(1 for a, b, _, _ in mims2 if {a, b} == {"z", "vdd"})
    if (c1_vss, c1_vdd, c2_vss, c2_vdd) != (2, 4, 2, 4):
        raise ValueError(f"Expected (2,4,2,4) stacked MIM counts, got {(c1_vss, c1_vdd, c2_vss, c2_vdd)}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(w / f"{cell}.mag").bbox()
    return {
        "cell": cell,
        "checker_exit": proc.returncode,
        "drc_boxes": int(drc_m[1]) if drc_m else None,
        "lvs_match": "LVS_MATCH True" in log,
        "lvs_property_errors": "LVS_PROPERTY_ERRORS True" in log,
        "exported_ports": ports_m[1].split() if ports_m else [],
        "mim_sites": {
            "sites": 6,
            "mim_side_um": SIDE,
            "mim1_z_vss": c1_vss,
            "mim1_z_vdd": c1_vdd,
            "mim2_z_vss": c2_vss,
            "mim2_z_vdd": c2_vdd,
        },
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

    r = build_lf_k4_fused(out)
    print(
        f"{r['cell']:32s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | "
        f"size={r['size_um']} um | area={r['area_um2']} um2",
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
