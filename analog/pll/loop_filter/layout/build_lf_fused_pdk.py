#!/usr/bin/env python3
"""Build 3D Under-MIM Stacked Fused SKY130 PDK Loop Filter (pll_loop_filter_k4_fused_pdk).

Implements ``pll_loop_filter_k4_fused`` from ``analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice``:
- PCell-compliant stacked MIM fusion (w = l = 27.22 um <= 30.0 um guard -> 1.500 pF/layer,
  3.000 pF/site across M3-M4 + M4-M5) arranged as a 3x2 1D common-centroid [VDD, VSS, VDD]
  array (6 sites = 6 MIM1 + 6 MIM2 = 18.00 pF total: 6 pF z-vss + 12 pF z-vdd).
- Shared middle M4 integrator plate ``z`` extracted on the top bus; Column 0 & 2 M3/M5
  bottom/top plates strapped to ``vdd`` at the bottom; Column 1 (center) M3/M5 plates
  strapped to ``vss`` at the top.
- ``Xrz`` (res_high_po_0p69, l=7.594 um) and ``Xfast`` LVT transmission gate placed
  strictly beneath Column 1's VSS-grounded M3 bottom plate so ``ctrl`` picks up zero
  parasitic coupling to VDD.
- ``Xinv`` and ``Xint`` LVT transmission gate stacked beneath Column 2 using strict
  HV M1/M2 routing (zero via2/M3/M4/M5 inside the MIM footprint).
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
    """Place compact guard=0 w=2.0 um MOSFET (PMOS mirrored so G faces inward), strap S/D onto M2."""
    c.include(prim, dx=dx, dy=dy, mirror_y=is_pmos)
    sds = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    s_xs = sds[::2]
    d_xs = sds[1::2]
    if is_pmos:
        s_y_pin, d_y_pin = grid(dy + 0.46), grid(dy - 0.46)
        s_bus_y, d_bus_y = grid(dy + 1.45), grid(dy - 1.45)
        gy = grid(dy - prim.pins("G")[0][1])
    else:
        s_y_pin, d_y_pin = grid(dy - 0.46), grid(dy + 0.46)
        s_bus_y, d_bus_y = grid(dy - 1.45), grid(dy + 1.45)
        gy = grid(dy + prim.pins("G")[0][1])

    for sx in s_xs:
        c.via1(sx, s_y_pin)
        c.wire("metal2", [(sx, s_y_pin), (sx, s_bus_y)], 0.24)
    for sx in d_xs:
        c.via1(sx, d_y_pin)
        c.wire("metal2", [(sx, d_y_pin), (sx, d_bus_y)], 0.24)
    if len(s_xs) > 1:
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.28)
    if len(d_xs) > 1:
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.28)

    gx0 = grid(dx + min(p[0] for p in prim.pins("G")))
    df_layer = "pdiff" if is_pmos else "ndiff"
    x_df_min = min(r[0] for r in prim.rects[df_layer]) + dx
    x_df_max = max(r[2] for r in prim.rects[df_layer]) + dx
    gx_esc = grid(x_df_min - 0.85) if dx < -2.0 else grid(x_df_min - 0.50)
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
    }


def add_mos_poly_dummy(
    c: Cell,
    x_dum: float,
    l_f: float,
    dy: float,
    is_pmos: bool,
    y_rail: float,
) -> None:
    """Place biased field-poly dummy gate (overhangs diff in Y) tied to VDD (PMOS) or VSS (NMOS)."""
    hw = grid(l_f / 2.0)
    y_cont = grid(dy + 1.55) if is_pmos else grid(dy - 1.55)
    if is_pmos:
        c.rect("poly", grid(x_dum - hw), grid(dy - 1.13), grid(x_dum + hw), grid(y_cont + 0.17))
    else:
        c.rect("poly", grid(x_dum - hw), grid(y_cont - 0.17), grid(x_dum + hw), grid(dy + 1.13))
    c.pad("poly", x_dum, y_cont, 0.28, 0.34)
    c.pad("polycont", x_dum, y_cont, 0.17, 0.17)
    c.pad("locali", x_dum, y_cont, 0.18, 0.34)
    c.rect("locali", grid(x_dum - 0.085), min(y_cont, y_rail), grid(x_dum + 0.085), max(y_cont, y_rail))


def draw_compact_np_frame(
    c: Cell,
    x1: float,
    x2: float,
    y_vss: float,
    y_vdd: float,
    step: float = 1.40,
) -> None:
    """Draw merged N/P dual guard frame (closed FEOL rails + side walls leaving |y|<1.3 open for M1)."""
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
    # Vertical side N/P guard walls (keep N-tap >= 0.20 um inside nwell y>=1.45)
    for xx in (x1g, x2g):
        for dl, cl, ylo, yhi in (
            ("psubdiff", "psubdiffcont", yvss, -1.65),
            ("nsubdiff", "nsubdiffcont", 1.65, yvdd),
        ):
            c.rect(dl, grid(xx - 0.18), ylo, grid(xx + 0.18), yhi)
            c.rect("locali", grid(xx - 0.14), ylo, grid(xx + 0.14), yhi)
            yc = grid(ylo + 0.50)
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

    # 1. Stacked MIM power/node buses cleanly outside array recognition box:
    #    - Shared M4 top/mid plate `z` collects all 3 columns at y = upper_z (mbbox[3] + 2.00)
    #    - Center Col 1 (VSS) M3 & M5 run up past upper_z to top_vss (mbbox[3] + 5.60) and join
    #    - Outer Col 0 & Col 2 (VDD) M3 & M5 run down to lower_vdd (mbbox[1] - 3.20) and join
    upper_z = grid(mbbox[3] + 2.00)     # +31.22
    top_vss = grid(mbbox[3] + 5.60)     # +34.82 (M5 met5.2 gap to MIM2 top edge >= 5.0 um)
    lower_vdd = grid(mbbox[1] - 3.20)   # -32.42 (M5 met5.2 gap to Col 1 M5 bottom >= 3.0 um)

    x_z_top_riser = 11.40
    for x, y in top_m4:
        c.rect("metal4", grid(x - 0.50), y, grid(x + 0.50), grid(upper_z + 0.50))
    c.rect("metal4", grid(top_m4[0][0] - 0.60), grid(upper_z - 0.50),
           grid(max(top_m4[-1][0], x_z_top_riser) + 0.60), grid(upper_z + 0.50))

    # Col 1 (idx=1) -> VSS at top_vss
    x_c1_m3, y_c1_m3 = bot_m3[1]
    x_c1_m5, y_c1_m5 = top_m5[1]
    c.rect("metal3", grid(x_c1_m3 - 0.40), y_c1_m3, grid(x_c1_m3 + 0.40), grid(top_vss + 0.40))
    c.rect("metal5", grid(x_c1_m5 - 0.80), y_c1_m5, grid(x_c1_m5 + 0.80), grid(top_vss + 0.80))
    c.wire("metal5", [(x_c1_m5, top_vss), (x_c1_m3, top_vss)], 1.60)
    via3(c, x_c1_m3, top_vss)
    via4(c, x_c1_m3, top_vss)

    # Col 0 & Col 2 (idx=0, 2) -> VDD at lower_vdd
    for idx in (0, 2):
        xm3, ym3 = bot_m3[idx]
        xm5, ym5 = top_m5[idx]
        c.rect("metal3", grid(xm3 - 0.40), grid(lower_vdd - 0.40), grid(xm3 + 0.40), ym3)
        c.rect("metal5", grid(xm5 - 0.80), grid(lower_vdd - 0.80), grid(xm5 + 0.80), ym5)
        via3(c, xm3, lower_vdd)
        via4(c, xm3, lower_vdd)
    c.rect("metal3", grid(bot_m3[0][0] - 0.40), grid(lower_vdd - 0.40),
           grid(bot_m3[2][0] + 0.40), grid(lower_vdd + 0.40))
    c.rect("metal5", grid(top_m5[0][0] - 0.80), grid(lower_vdd - 0.80),
           grid(bot_m3[2][0] + 0.80), grid(lower_vdd + 0.80))

    # 2. Side-mounted Xrz (+ 2 pure-poly dummies) & ultra-compact CMOS island inside Col 1 VSS shield
    y_rz_vss_m1 = -6.80
    y_nmos_vss_m1 = -5.20
    y_preen_m1 = -0.96
    y_preb_m1 = -0.48
    y_preref_m1 = 0.00
    y_ctrl_m1 = 0.48
    y_z_m1 = 0.96
    y_pmos_vdd_m1 = 5.20

    # Xrz placed on left side of Col 1 alongside CMOS strip, plus 2 symmetric flanking pure-poly dummies
    dx_rz, dy_rz = -10.80, 0.00
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

    # Flanking pure-poly dummy bars for Xrz (0.69 um wide, no xpolycontact -> zero LVS change)
    for x_rdum in (grid(dx_rz - 1.65), grid(dx_rz + 1.65)):
        c.rect("poly", grid(x_rdum - 0.345), -6.40, grid(x_rdum + 0.345), 5.875)
        c.pad("polycont", x_rdum, -6.20, 0.17, 0.17)
        c.pad("locali", x_rdum, -6.20, 0.34, 0.34)
        c.pad("viali", x_rdum, -6.20, 0.17)
        c.pad("metal1", x_rdum, -6.20, 0.32)
        c.wire("metal1", [(x_rdum, -6.20), (x_rdum, y_rz_vss_m1)], 0.30)

    y_rz_r2 = grid(dy_rz - 4.80)   # ctrl end (-4.80)
    y_rz_r1 = grid(dy_rz + 4.80)   # z end (+4.80)
    c.via1(dx_rz, y_rz_r2)
    c.via1(dx_rz, y_rz_r1)

    # Ultra-compact CMOS strip: Xfast (-3.80) | Xinv (+0.50) | Xint (+6.00), height = 10.4 um
    dy_n, dy_p = -3.10, 3.10
    dx_fast, dx_inv, dx_int = -3.80, 0.50, 6.00

    fn = place_w2_mos(c, n2, "ndiffc", dx_fast, dy_n, False)
    fp = place_w2_mos(c, pl4, "pdiffc", dx_fast, dy_p, True)
    in_n = place_w2_mos(c, n2, "ndiffc", dx_inv, dy_n, False)
    in_p = place_w2_mos(c, p4, "pdiffc", dx_inv, dy_p, True)
    it_n = place_w2_mos(c, n4, "ndiffc", dx_int, dy_n, False)
    it_p = place_w2_mos(c, pl8, "pdiffc", dx_int, dy_p, True)

    # Biased field-poly dummy gates flanking EVERY NMOS (-> VSS) and EVERY PMOS (-> VDD)
    for x_nd in (
        grid(fn["x_min"] - 0.28), grid(fn["x_max"] + 0.28),
        grid(in_n["x_min"] - 0.28), grid(in_n["x_max"] + 0.28),
        grid(it_n["x_min"] - 0.28), grid(it_n["x_max"] + 0.28),
    ):
        add_mos_poly_dummy(c, x_nd, 0.15, dy_n, False, y_nmos_vss_m1)
    for x_pd, lf in (
        (grid(fp["x_min"] - 0.30), 0.35),
        (-1.50, 0.25),
        (2.35, 0.25),
        (grid(it_p["x_max"] + 0.30), 0.35),
    ):
        add_mos_poly_dummy(c, x_pd, lf, dy_p, True, y_pmos_vdd_m1)

    gr_x1, gr_x2 = -6.65, 9.85
    c.rect("nwell", grid(gr_x1 - 0.45), 1.45, grid(gr_x2 + 0.45), 5.65)
    draw_compact_np_frame(c, gr_x1, gr_x2, y_nmos_vss_m1, y_pmos_vdd_m1)

    # VSS M1 rails -> M2 trunk at x_c1_m3 (+14.43, right outside Col 1) -> top_vss (via2 outside MIM)
    x_vss_m2 = x_c1_m3
    c.wire("metal1", [(-12.50, y_rz_vss_m1), (x_vss_m2, y_rz_vss_m1)], 0.44)
    c.via1(x_vss_m2, y_rz_vss_m1)
    c.wire("metal1", [(gr_x1, y_nmos_vss_m1), (x_vss_m2, y_nmos_vss_m1)], 0.44)
    c.via1(x_vss_m2, y_nmos_vss_m1)
    c.wire("metal2", [(x_vss_m2, y_rz_vss_m1), (x_vss_m2, top_vss)], 0.56)
    c.via2(x_vss_m2, top_vss)

    # VDD M1 rail -> hop over Xrz (y=+7.20 M1) -> Col 0/1 gap x_vdd_m2 = bot_m3[0][0] (-18.28) -> lower_vdd
    x_vdd_m2 = bot_m3[0][0]
    y_vdd_bridge = 7.20
    c.wire("metal1", [(gr_x1, y_pmos_vdd_m1), (gr_x2, y_pmos_vdd_m1)], 0.44)
    c.via1(gr_x1, y_pmos_vdd_m1)
    c.wire("metal2", [(gr_x1, y_pmos_vdd_m1), (gr_x1, y_vdd_bridge)], 0.44)
    c.via1(gr_x1, y_vdd_bridge)
    c.wire("metal1", [(x_vdd_m2, y_vdd_bridge), (gr_x1, y_vdd_bridge)], 0.44)
    c.via1(x_vdd_m2, y_vdd_bridge)
    c.wire("metal2", [(x_vdd_m2, lower_vdd), (x_vdd_m2, y_vdd_bridge)], 0.56)
    c.via2(x_vdd_m2, lower_vdd)

    # Xinv wiring
    c.wire("metal2", [(in_n["s_xs"][0], in_n["s_bus_y"]), (in_n["s_xs"][0], y_nmos_vss_m1)], 0.28)
    c.via1(in_n["s_xs"][0], y_nmos_vss_m1)
    c.wire("metal2", [(in_p["s_xs"][0], in_p["s_bus_y"]), (in_p["s_xs"][0], y_pmos_vdd_m1)], 0.28)
    c.via1(in_p["s_xs"][0], y_pmos_vdd_m1)
    c.wire("metal2", [(dx_inv, in_n["d_bus_y"]), (dx_inv, in_p["d_bus_y"])], 0.30)
    c.via1(dx_inv, y_preb_m1)

    # Gate ties to pre_en (-0.84) and pre_b (-0.42)
    for gpt in (fn["g_pt"], in_n["g_pt"], in_p["g_pt"], it_n["g_pt"]):
        c.wire("metal2", [gpt, (gpt[0], y_preen_m1)], 0.24)
        c.via1(gpt[0], y_preen_m1)
    for gpt in (fp["g_pt"], it_p["g_pt"]):
        c.wire("metal2", [gpt, (gpt[0], y_preb_m1)], 0.24)
        c.via1(gpt[0], y_preb_m1)

    x_sig_port = grid(mbbox[0] + 0.80)  # -49.60, under M5 overhang and clear of Col 0 M3 (-47.00)
    x_ov_l, x_ov_r = -13.50, -8.40      # M2 bridge across Xrz (avoids Xrz M1 shield & passes under ctrl M2)
    c.wire("metal1", [(x_sig_port, y_preen_m1), (x_ov_l, y_preen_m1)], 0.22)
    c.via1(x_sig_port, y_preen_m1)
    c.via1(x_ov_l, y_preen_m1)
    c.wire("metal2", [(x_ov_l, y_preen_m1), (x_ov_r, y_preen_m1)], 0.22)
    c.via1(x_ov_r, y_preen_m1)
    c.wire("metal1", [(x_ov_r, y_preen_m1), (it_n["g_pt"][0], y_preen_m1)], 0.22)
    c.via2(x_sig_port, y_preen_m1)
    c.pad("metal3", x_sig_port, y_preen_m1, 0.52)

    c.wire("metal1", [(fp["g_pt"][0], y_preb_m1), (it_p["g_pt"][0], y_preb_m1)], 0.22)

    # Xfast t-gate: node b = ctrl (dx_fast) -> x_ctrl_riser (-7.65) -> Xrz bottom (-4.80) -> ctrl port
    c.wire("metal2", [(dx_fast, fn["d_bus_y"]), (dx_fast, fp["d_bus_y"])], 0.30)
    c.via1(dx_fast, y_ctrl_m1)
    x_ctrl_riser = -7.65
    c.wire("metal1", [(x_ctrl_riser, y_ctrl_m1), (dx_fast, y_ctrl_m1)], 0.22)
    c.via1(x_ctrl_riser, y_ctrl_m1)
    y_ctrl_port = grid(lower_vdd - 1.80)  # -34.22
    c.wire("metal2", [(x_ctrl_riser, y_ctrl_m1), (x_ctrl_riser, -8.20),
                      (dx_rz, -8.20), (dx_rz, y_rz_r2)], 0.38)
    c.wire("metal2", [(dx_rz, -8.20), (dx_rz, y_ctrl_port)], 0.40)
    c.via2(dx_rz, y_ctrl_port)
    c.pad("metal3", dx_rz, y_ctrl_port, 0.52)

    # Xfast node a = pre_ref -> y_preref_m1 (0.00)
    x_fast_ref = grid(fp["s_xs"][-1] + 0.55)
    c.wire("metal2", [(fn["s_xs"][-1], fn["s_bus_y"]), (x_fast_ref, fn["s_bus_y"]),
                      (x_fast_ref, fp["s_bus_y"]), (fp["s_xs"][-1], fp["s_bus_y"])], 0.24)
    c.via1(x_fast_ref, y_preref_m1)

    # Xint t-gate: node b = z (dx_int) -> upper_z via x_z_top_riser (+11.40), bridged over island to Xrz top (+4.80)
    c.wire("metal2", [(dx_int, it_n["d_bus_y"]), (dx_int, it_p["d_bus_y"])], 0.32)
    c.via1(dx_int, y_z_m1)
    c.wire("metal1", [(dx_int, y_z_m1), (x_z_top_riser, y_z_m1)], 0.22)
    c.via1(x_z_top_riser, y_z_m1)
    c.wire("metal2", [(dx_rz, y_rz_r1), (dx_rz, 8.40), (x_z_top_riser, 8.40),
                      (x_z_top_riser, y_z_m1)], 0.40)
    c.wire("metal2", [(x_z_top_riser, 8.40), (x_z_top_riser, upper_z)], 0.48)
    c.via2(x_z_top_riser, upper_z)
    via3(c, x_z_top_riser, upper_z)

    # Xint node a = pre_ref -> y_preref_m1 -> M2 bridge across Xrz -> left port x_sig_port
    x_int_ref = grid(it_p["s_xs"][-1] + 0.55)
    c.wire("metal2", [(it_n["s_xs"][-1], it_n["s_bus_y"]), (x_int_ref, it_n["s_bus_y"]),
                      (x_int_ref, it_p["s_bus_y"]), (it_p["s_xs"][-1], it_p["s_bus_y"])], 0.24)
    c.via1(x_int_ref, y_preref_m1)
    c.wire("metal1", [(x_ov_r, y_preref_m1), (x_int_ref, y_preref_m1)], 0.22)
    c.via1(x_ov_r, y_preref_m1)
    c.wire("metal2", [(x_ov_l, y_preref_m1), (x_ov_r, y_preref_m1)], 0.22)
    c.via1(x_ov_l, y_preref_m1)
    c.wire("metal1", [(x_sig_port, y_preref_m1), (x_ov_l, y_preref_m1)], 0.22)
    c.via1(x_sig_port, y_preref_m1)
    c.via2(x_sig_port, y_preref_m1)
    c.pad("metal3", x_sig_port, y_preref_m1, 0.52)

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
