#!/usr/bin/env python3
"""SKY130A gm/Id-Optimized W3 5.0 Gb/s Shunt-Peaked RX CTLE PDK Layout Builder (`serdes_rx_ctle_shunt_5g_w3_pdk`).

Implements the gm/Id-synthesized W3 active core + compact 0%-M5 M4+M2 12-turn stacked inductor:
  - Input pair (`Xip/Xin`): `nfet_01v8_lvt`, `w=19.2 l=0.15 nf=8` (2D CC quad, 2.40 um/f, gm/Id ~ 10.7 S/A)
  - Tail sinks (`Xtp/Xtn`): `nfet_01v8_lvt`, `w=90.0 l=0.50 nf=10` each (20f shared-diff 1D CC, 9.00 um/f)
  - Load poly (`Xrp/Xrn`):  `res_high_po_2p85 l=2.83` (trimmed to absorb 66.7 Ohm/arm M4+M2 coil R)
  - Degen poly (`Xrdeg`):   `res_high_po_2p85 l=5.10`
  - Degen MIM (`Xceq0/1a/1b`): 3x `cap_mim_m3_1 w=6.00 l=6.00` (-62.6% MIM area -> higher f_z ~ 0.9 GHz, -42% GD_pp!)
  - EQ switches (`Xsw0/1`): `wsw=8` (`nfet w=8.0 l=0.18 nf=2` / `pfet w=16.0 l=0.18 nf=4`, 4.00 um/f -> halves R_on @ SS+85C!)
  - Stacked inductor: reuses signed-off 57.6 x 57.6 um 0%-M5 M4+M2 coil `rx_ctle_ind_m4m2_5g_pdk` (4.10 nH/arm)

Produces:
  1. `serdes_rx_ctle_active_5g_w3_pdk` (41.40 x 29.00 um, 11 ports, 0% M5, DRC=0, LVS=MATCH, full CPEX)
  2. `serdes_rx_ctle_shunt_5g_w3_pdk`  (57.60 x 94.20 um, 9 ports, 0% M5, DRC=0, FP=0, DC-LVS & Open-LVS MATCH)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rx_layout_common as rlc  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_STD,
    N_LVT,
    P_STD,
    R_2P85,
    MIM1,
    grid,
    poly_cont_pad,
    viali_pad,
    via1_clean,
    via2_clean,
    via3_pad,
    locali_v,
    draw_tap_h,
    draw_tap_v,
    tie_mos_gates,
    add_tied_poly_dummy,
)

REPO = rlc.REPO
IND_COMPACT_MAG = HERE / "variants" / "ctle_shunt_ind_compact_5g_pdk" / "rx_ctle_ind_m4m2_5g_pdk.mag"
VARIANT_DIR = HERE / "variants" / "ctle_shunt_5g_w3_pdk"
RESULTS_DIR = REPO / "results" / "layout" / "rx_ctle_shunt_5g_w3_pdk"

ACTIVE_NAME = "serdes_rx_ctle_active_5g_w3_pdk"
TOP_NAME = "serdes_rx_ctle_shunt_5g_w3_pdk"
ACTIVE_PORTS = [
    "inp", "inn", "outp", "outn", "lp_mid", "ln_mid",
    "eq0", "eq1", "vbias", "vdd", "vss",
]
TOP_PORTS = [
    "inp", "inn", "outp", "outn", "eq0", "eq1", "vbias", "vdd", "vss",
]


def active_primitive_lines_w3(lp_node: str = "lp_mid", ln_node: str = "ln_mid") -> list[str]:
    """Exact 20 flattened SKY130 primitives of gm/Id-optimized W3 5G shunt-peaked CTLE."""
    return [
        f"X1 {lp_node} outp vss sky130_fd_pr__res_high_po_2p85 l=2.83",
        f"X2 {ln_node} outn vss sky130_fd_pr__res_high_po_2p85 l=2.83",
        "X3 outn inp t_sp vss sky130_fd_pr__nfet_01v8_lvt w=19.2 l=0.15",
        "X4 outp inn t_sn vss sky130_fd_pr__nfet_01v8_lvt w=19.2 l=0.15",
        "X5 t_sp vbias vss vss sky130_fd_pr__nfet_01v8_lvt w=90 l=0.5",
        "X6 t_sn vbias vss vss sky130_fd_pr__nfet_01v8_lvt w=90 l=0.5",
        "X7 t_sp t_sn vss sky130_fd_pr__res_high_po_2p85 l=5.1",
        "X8 t_eq0_b eq0 vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18",
        "X9 t_eq0_b eq0 vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18",
        "X10 t_eq1_b eq1 vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18",
        "X11 t_eq1_b eq1 vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18",
        "X12 t_sp t_cap0 sky130_fd_pr__cap_mim_m3_1 w=6 l=6",
        "X13 t_sp t_cap1 sky130_fd_pr__cap_mim_m3_1 w=6 l=6",
        "X14 t_sp t_cap1 sky130_fd_pr__cap_mim_m3_1 w=6 l=6",
        "X15 t_cap0 eq0 t_sn vss sky130_fd_pr__nfet_01v8 w=8 l=0.18",
        "X16 t_cap0 t_eq0_b t_sn vdd sky130_fd_pr__pfet_01v8 w=16 l=0.18",
        "X17 t_cap1 eq1 t_sn vss sky130_fd_pr__nfet_01v8 w=8 l=0.18",
        "X18 t_cap1 t_eq1_b t_sn vdd sky130_fd_pr__pfet_01v8 w=16 l=0.18",
        "X19 t_cap0 t_eq0_b t_sp vss sky130_fd_pr__nfet_01v8 w=0.42 l=0.5",
        "X20 t_cap1 t_eq1_b t_sp vss sky130_fd_pr__nfet_01v8 w=0.42 l=0.5",
    ]


def _place_mim_w3(c: Cell, cache: PdkCache, dx: float, dy: float, mirror_x: bool = True) -> dict:
    m = cache.device(MIM1, dict(w=6.00, l=6.00, nx=1, ny=1, stack=0, doports=1))
    c1 = m.pins("C1")[0]
    c2 = m.pins("C2")[0]
    m.labels.clear()
    dx, dy = grid(dx), grid(dy)
    c.include(m, dx=dx, dy=dy, mirror_x=mirror_x)
    s = -1.0 if mirror_x else +1.0
    p1 = (grid(dx + s * c1[0]), grid(dy + c1[1]))
    p2 = (grid(dx + s * c2[0]), grid(dy + c2[1]))
    bb = m.bbox()
    bx1 = grid(dx + (-bb[2] if mirror_x else bb[0]))
    bx2 = grid(dx + (-bb[0] if mirror_x else bb[2]))
    return {"c1": p1, "c2": p2, "bbox": (bx1, grid(dy + bb[1]), bx2, grid(dy + bb[3]))}


def build_rx_ctle_active_5g_w3_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build gm/Id-optimized W3 active submacro (`41.40 x 29.00 um`, 0.0% M5)."""
    c = Cell()

    x_w_port = -20.700
    x_e_port = +20.700
    y_vss_n  = +29.500
    y_s_edge = 0.000

    # Flush North global M2 `vss` rail (`y in [+28.200, +29.000]`)
    c.rect("metal2", x_w_port, grid(y_vss_n - 0.400), x_e_port, grid(y_vss_n + 0.400))

    # =========================================================================
    # NORTH BAND (3D Under-MIM): 20f x 9.0um Tail (90um/side) + Xrdeg (l=5.10) + wsw=8 EQ
    # =========================================================================
    dy_tail = +18.300  # active diff y in [+13.80 .. +22.80], poly in [+13.67 .. +22.93]
    cx_tail = 0.000
    m_tail, inf_tail = cache.build_mos(N_LVT, 9.00, 0.50, 20, dy_tail, False)
    c.include(m_tail, dx=cx_tail)

    t_sds = [grid(cx_tail + x) for x in inf_tail["all_sd_xs"]]  # 21 stripes [-7.90 .. +7.90]
    t_vss_xs = t_sds[::2]                                       # 11 source stripes -> vss
    t_sp_xs  = [t_sds[k] for k in (1, 5, 9, 15, 19)]            # 1D CC -> 90 um each!
    t_sn_xs  = [t_sds[k] for k in (3, 7, 11, 13, 17)]

    # Tail VSS straps (uniform 0.32 um M1)
    y_tail_vss = +21.300
    for sx in t_vss_xs:
        for vy in (+14.300, +15.800, +17.300, +18.800, +20.300, +21.800):
            viali_pad(c, sx, vy)
        c.wire("metal1", [(sx, +14.300), (sx, +21.800)], 0.320)
        via1_clean(c, sx, y_tail_vss)
    c.wire("metal2", [(t_vss_xs[0], y_tail_vss), (t_vss_xs[-1], y_tail_vss)], 0.440)
    for sx in (t_vss_xs[0], t_vss_xs[5], t_vss_xs[-1]):
        c.wire("metal2", [(sx, y_tail_vss), (sx, y_vss_n)], 0.440)

    # Tail `sp` (y = +15.300 M2) & `sn` (y = +16.900 M2)
    y_tail_sp = +15.300
    y_tail_sn = +16.900
    for dx_s, y_bus in ((t_sp_xs, y_tail_sp), (t_sn_xs, y_tail_sn)):
        for x in dx_s:
            for vy in (+14.400, +15.900, +17.400, +18.900, +20.400, +21.900):
                viali_pad(c, x, vy)
            c.wire("metal1", [(x, +14.400), (x, +21.900)], 0.320)
            via1_clean(c, x, y_bus)
        c.wire("metal2", [(dx_s[0], y_bus), (dx_s[-1], y_bus)], 0.440)

    # Tail gates (`vbias`) along North poly bar (poly_y2 ~ +22.93)
    y_tail_g = +23.750
    t_g_pts = tie_mos_gates(
        c, cx_tail, inf_tail, y_bar=+23.350, y_cont=y_tail_g,
        tap_xs=[grid(cx_tail - 6.300), cx_tail, grid(cx_tail + 6.300)],
    )
    c.wire("metal1", [(t_g_pts[0][0], y_tail_g), (t_g_pts[-1][0], y_tail_g)], 0.320)

    # Biased poly dummies flanking Xtp/Xtn -> tied to North guard ring (y = +25.900)
    x_tdum_l = grid(cx_tail + inf_tail["diff_x1"] - 0.140 - 0.250)  # -8.435
    x_tdum_r = grid(cx_tail + inf_tail["diff_x2"] + 0.140 + 0.250)  # +8.435
    y_tail_gr_n = +25.900
    y_tail_gr_s = +12.700
    for xd in (x_tdum_l, x_tdum_r):
        pt = add_tied_poly_dummy(c, xd, inf_tail["poly_y1"], inf_tail["poly_y2"], 0.50, y_cont=y_tail_g)
        c.wire("metal1", [pt, (xd, y_tail_gr_n)], 0.290)

    # Continuous P+ guard ring around Xtp/Xtn
    x_tgr_l = grid(x_tdum_l - 0.850)  # -9.285
    x_tgr_r = grid(x_tdum_r + 0.850)  # +9.285
    draw_tap_h(c, "psubdiff", x_tgr_l, x_tgr_r, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", x_tgr_l, x_tgr_r, y_tail_gr_s, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_tgr_l, y_tail_gr_s, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_tgr_r, y_tail_gr_s, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    via1_clean(c, x_tgr_l, y_tail_gr_n)
    c.wire("metal2", [(x_tgr_l, y_tail_gr_n), (x_tgr_l, y_vss_n)], 0.400)
    via1_clean(c, x_tgr_r, y_tail_gr_n)
    c.wire("metal2", [(x_tgr_r, y_tail_gr_n), (x_tgr_r, y_vss_n)], 0.400)

    # Route `vbias` East on M1 at y = +27.200 (flush to x_e_port = +20.700)
    y_vbias = +27.200
    xv_bias = t_g_pts[-1][0]  # +6.300
    via1_clean(c, xv_bias, y_tail_g)
    c.wire("metal2", [(xv_bias, y_tail_g), (xv_bias, y_vbias)], 0.340)
    via1_clean(c, xv_bias, y_vbias)
    c.rect("metal1", grid(xv_bias - 0.170), grid(y_vbias - 0.170), x_e_port, grid(y_vbias + 0.170))

    # Under-MIM East: `Xrdeg` (`res_high_po_2p85 l=5.10, nx=1, guard=1`)
    rdeg_c = cache.device(R_2P85, dict(l=5.10, nx=1, m=1, guard=1))
    rd_r1 = rdeg_c.pins("R1")[0]
    rd_r2 = rdeg_c.pins("R2")[0]
    rd_b  = rdeg_c.pins("B")[0]
    rdeg_c.labels.clear()
    dx_rdeg, dy_rdeg = +14.650, +18.300
    c.include(rdeg_c, dx=dx_rdeg, dy=dy_rdeg)
    p_rd_sn = (grid(dx_rdeg + rd_r1[0]), grid(dy_rdeg + rd_r1[1]))
    p_rd_sp = (grid(dx_rdeg + rd_r2[0]), grid(dy_rdeg + rd_r2[1]))
    p_rd_b  = (grid(dx_rdeg + rd_b[0]),  grid(dy_rdeg + rd_b[1]))

    viali_pad(c, p_rd_b[0], p_rd_b[1])
    c.wire("metal1", [(x_tgr_r, y_tail_gr_s), (x_tgr_r, p_rd_b[1]), p_rd_b], 0.340)

    for dxv in (-0.800, 0.000, +0.800):
        via1_clean(c, grid(p_rd_sp[0] + dxv), p_rd_sp[1])
        via1_clean(c, grid(p_rd_sn[0] + dxv), p_rd_sn[1])
    c.wire("metal2", [(grid(p_rd_sp[0] - 0.800), p_rd_sp[1]), (grid(p_rd_sp[0] + 0.800), p_rd_sp[1])], 0.440)
    c.wire("metal2", [(grid(p_rd_sn[0] - 0.800), p_rd_sn[1]), (grid(p_rd_sn[0] + 0.800), p_rd_sn[1])], 0.440)
    x_rdeg_ch = +11.150
    c.wire("metal2", [p_rd_sp, (x_rdeg_ch, p_rd_sp[1]), (x_rdeg_ch, y_tail_sp), (t_sp_xs[-1], y_tail_sp)], 0.440)
    c.wire("metal2", [p_rd_sn, (x_rdeg_ch, p_rd_sn[1]), (x_rdeg_ch, y_tail_sn), (t_sn_xs[-1], y_tail_sn)], 0.440)

    # Under-MIM West: EQ0/EQ1 inverters + doubled wsw=8 T-gates (`4.0 um/f` x 2n/4p!) + tie FETs
    y_eq_vdd = +12.350
    y_eq_p   = +15.150   # p-diff y in [+13.15 .. +17.15] (0.80 um clear of y_eq_vdd!)
    y_eq_n   = +20.950   # n-diff y in [+18.95 .. +22.95], poly_y2 = +23.08
    y_eq_tie = +24.750   # tie diff y in [+24.54 .. +24.96] (0.82 um clear of m_swn poly_y2!)

    c.rect("nwell", -20.100, +11.750, -10.300, +17.650)
    draw_tap_h(c, "nsubdiff", -19.850, -10.550, y_eq_vdd, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", -20.000, x_tgr_l, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", -20.000, +18.300, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)

    # Clean West M2 `vdd` trunk from EQ NWELL bar straight South to flush South edge (y = 0.000)
    x_vdd_act = -20.100
    via1_clean(c, -19.600, y_eq_vdd)
    c.wire("metal2", [(x_vdd_act, y_eq_vdd), (-19.600, y_eq_vdd)], 0.440)
    c.rect("metal2", grid(x_vdd_act - 0.300), y_s_edge, grid(x_vdd_act + 0.300), grid(y_eq_vdd + 0.220))

    via1_clean(c, -19.500, y_tail_gr_n)
    c.wire("metal2", [(-19.500, y_tail_gr_n), (-19.500, y_vss_n)], 0.440)

    m_inv_n, inf_inv_n = cache.build_mos(N_STD, 1.00, 0.18, 1, y_eq_n, False)
    m_inv_p, inf_inv_p = cache.build_mos(P_STD, 2.00, 0.18, 1, y_eq_p, True)
    m_swn,   inf_swn   = cache.build_mos(N_STD, 4.00, 0.18, 2, y_eq_n, False)  # wn = 8.0 um!
    m_swp,   inf_swp   = cache.build_mos(P_STD, 4.00, 0.18, 4, y_eq_p, True)   # wp = 16.0 um!
    m_tie,   inf_tie   = cache.build_mos(N_STD, 0.42, 0.50, 1, y_eq_tie, False)

    cx_eq0, cx_sw0, cx_sw1, cx_eq1 = -11.400, -13.700, -16.700, -18.950
    for cx_inv in (cx_eq0, cx_eq1):
        c.include(m_inv_n, dx=cx_inv)
        c.include(m_inv_p, dx=cx_inv)
    for cx_sw in (cx_sw0, cx_sw1):
        c.include(m_swn, dx=cx_sw)
        c.include(m_swp, dx=cx_sw)
        c.include(m_tie, dx=cx_sw)

    y_eq_gb   = +17.700
    y_eq_g    = +18.500
    y_swp_sn,  y_swp_cap = +14.150, +16.050
    y_swn_cap, y_swn_sn  = +19.950, +21.950

    for idx, cx_inv, cx_sw, sgn in ((0, cx_eq0, cx_sw0, +1), (1, cx_eq1, cx_sw1, -1)):
        gx_inv = grid(cx_inv + inf_inv_n["g_xs"][0])
        gx_tap = grid(gx_inv + sgn * 0.250)
        c.rect("poly", grid(gx_inv - 0.090), grid(inf_inv_p["diff_y2"] + 0.050),
               grid(gx_inv + 0.090), grid(inf_inv_n["diff_y1"] - 0.050))
        c.rect("poly", grid(min(gx_inv, gx_tap) - 0.090), grid(y_eq_g - 0.170),
               grid(max(gx_inv, gx_tap) + 0.090), grid(y_eq_g + 0.170))
        poly_cont_pad(c, gx_tap, y_eq_g)
        viali_pad(c, gx_tap, y_eq_g)

        x_in_s = grid(cx_inv + (inf_inv_n["d_xs"][0] if sgn > 0 else inf_inv_n["s_xs"][0]))
        x_in_d = grid(cx_inv + (inf_inv_n["s_xs"][0] if sgn > 0 else inf_inv_n["d_xs"][0]))
        locali_v(c, x_in_s, inf_inv_n["c_y2"] - 0.05, y_tail_gr_n)
        locali_v(c, x_in_s, y_eq_vdd, inf_inv_p["c_y1"] + 0.05)

        locali_v(c, x_in_d, inf_inv_p["c_y2"] - 0.05, inf_inv_n["c_y1"] + 0.05)
        viali_pad(c, x_in_d, y_eq_gb)

        swp_g = tie_mos_gates(c, cx_sw, inf_swp, y_bar=+17.350, y_cont=y_eq_gb, tap_xs=[cx_sw])[0]
        c.wire("metal1", sorted([(x_in_d, y_eq_gb), swp_g], key=lambda p: p[0]), 0.290)

        swn_g = tie_mos_gates(c, cx_sw, inf_swn, y_bar=+18.750, y_cont=y_eq_g, tap_xs=[cx_sw])[0]
        via1_clean(c, gx_tap, y_eq_g)
        via1_clean(c, swn_g[0], y_eq_g)
        c.wire("metal2", sorted([(gx_tap, y_eq_g), swn_g], key=lambda p: p[0]), 0.280)

        tie_g = tie_mos_gates(c, cx_sw, inf_tie, y_bar=+24.300, y_cont=+23.900, tap_xs=[cx_sw])[0]
        c.wire("metal1", [(x_in_d, y_eq_gb), (x_in_d, +23.900)], 0.290)
        c.wire("metal1", sorted([(x_in_d, +23.900), tie_g], key=lambda p: p[0]), 0.290)

        swn_sn  = [grid(cx_sw + x) for x in inf_swn["s_xs"]]
        swn_cap = [grid(cx_sw + x) for x in inf_swn["d_xs"]]
        swp_sn  = [grid(cx_sw + x) for x in inf_swp["s_xs"]]
        swp_cap = [grid(cx_sw + x) for x in inf_swp["d_xs"]]

        # Multi-contact straps along 4.0 um fingers for ultra-low switch R_on!
        for sx in swp_sn:
            for vy in (+13.650, +14.650, +15.650, +16.650):
                viali_pad(c, sx, vy)
            c.wire("metal1", [(sx, +13.650), (sx, +16.650)], 0.290)
            via1_clean(c, sx, y_swp_sn)
        c.wire("metal2", [(swp_sn[0], y_swp_sn), (swp_sn[-1], y_swp_sn)], 0.360)

        for sx in swn_sn:
            for vy in (+19.450, +20.450, +21.450, +22.450):
                viali_pad(c, sx, vy)
            c.wire("metal1", [(sx, +19.450), (sx, +22.450)], 0.290)
            via1_clean(c, sx, y_swn_sn)
        c.wire("metal2", [(swn_sn[0], y_swn_sn), (swn_sn[-1], y_swn_sn)], 0.360)

        xc_n = swn_cap[0]
        for vy in (+19.450, +20.450, +21.450, +22.450):
            viali_pad(c, xc_n, vy)
        c.wire("metal1", [(xc_n, +19.450), (xc_n, +22.450)], 0.290)
        via1_clean(c, xc_n, y_swn_cap)
        for sx in swp_cap:
            for vy in (+13.650, +14.650, +15.650, +16.650):
                viali_pad(c, sx, vy)
            c.wire("metal1", [(sx, +13.650), (sx, +16.650)], 0.290)
            via1_clean(c, sx, y_swp_cap)
        c.wire("metal2", [(swp_cap[0], y_swp_cap), (swp_cap[-1], y_swp_cap)], 0.360)
        x_cap_br = grid(cx_sw - sgn * 0.650)
        c.wire("metal2", [(xc_n, y_swn_cap), (x_cap_br, y_swn_cap), (x_cap_br, y_swp_cap), (swp_cap[-1], y_swp_cap)], 0.320)

        # Bridge cap node from swn_cap North to bleed FET `xt_cap` at y_eq_tie (+23.850)
        via1_clean(c, xc_n, +22.450)
        xt_sp  = grid(cx_sw + inf_tie["d_xs"][0])
        xt_cap = grid(cx_sw + inf_tie["s_xs"][0])
        viali_pad(c, xt_cap, y_eq_tie)
        via1_clean(c, xt_cap, y_eq_tie)
        c.wire("metal2", [(xc_n, +22.450), (xc_n, y_eq_tie), (xt_cap, y_eq_tie)], 0.320)

        viali_pad(c, xt_sp, y_eq_tie)
        c.wire("metal1", [(xt_sp, y_eq_tie), (xt_sp, +25.250)], 0.290)

    # Join T-gate `sn` terminals cleanly into tail `sn` M2 bus (y = +16.900)
    c.wire("metal2", [(grid(cx_sw1 + inf_swp["s_xs"][0]), y_swp_sn), (grid(cx_sw0 + inf_swp["s_xs"][-1]), y_swp_sn)], 0.360)
    c.wire("metal2", [(grid(cx_sw1 + inf_swn["s_xs"][0]), y_swn_sn), (grid(cx_sw0 + inf_swn["s_xs"][-1]), y_swn_sn)], 0.360)
    c.wire("metal2", [(-15.200, y_swp_sn), (-15.200, y_swn_sn)], 0.360)
    x_sn_w = -10.350
    c.wire("metal2", [
        (grid(cx_sw0 + inf_swn["s_xs"][-1]), y_swn_sn),
        (x_sn_w, y_swn_sn),
        (x_sn_w, y_tail_sn),
        (t_sn_xs[0], y_tail_sn),
    ], 0.440)

    # Join bleed-FET `sp` terminals cleanly on M1 around tail guard ring -> `t_sp_xs[0]` (-7.110)
    xt1_sp = grid(cx_sw1 + inf_tie["d_xs"][0])
    x_tie_m1 = -10.050
    c.wire("metal1", [(xt1_sp, +25.250), (x_tie_m1, +25.250)], 0.290)
    c.wire("metal1", [(x_tie_m1, +12.100), (x_tie_m1, +25.250)], 0.290)
    c.wire("metal1", [(x_tie_m1, +12.100), (t_sp_xs[0], +12.100)], 0.290)
    via1_clean(c, t_sp_xs[0], +12.100)
    c.wire("metal2", [(t_sp_xs[0], +12.100), (t_sp_xs[0], y_tail_sp)], 0.380)

    # Export `eq0` and `eq1` flush to x_w_port = -20.700 on M1 (crossing cleanly under x_vdd_act=-20.10 M2!)
    y_eq0_out = +11.450
    y_eq1_out = +26.950
    x_eq0_v = grid(cx_eq0 + 0.250)  # -11.150
    x_eq0_drop = -18.800
    c.wire("metal2", [(x_eq0_v, y_eq_g), (x_eq0_v, y_eq0_out), (x_eq0_drop, y_eq0_out)], 0.280)
    via1_clean(c, x_eq0_drop, y_eq0_out)
    c.rect("metal1", x_w_port, grid(y_eq0_out - 0.140), grid(x_eq0_drop + 0.140), grid(y_eq0_out + 0.140))

    x_eq1_v = -18.050
    x_eq1_drop = -18.700
    c.wire("metal2", [(x_eq1_v, y_eq_g), (x_eq1_v, y_eq1_out), (x_eq1_drop, y_eq1_out)], 0.280)
    via1_clean(c, x_eq1_drop, y_eq1_out)
    c.rect("metal1", x_w_port, grid(y_eq1_out - 0.140), grid(x_eq1_drop + 0.140), grid(y_eq1_out + 0.140))

    # 3D-Stacked 3x Compact `6.00 x 6.00 um` MIM1 Caps (-62.6% MIM area, huge spacing!)
    dy_mim = +18.300
    mim_1b = _place_mim_w3(c, cache, dx=-13.800, dy=dy_mim, mirror_x=True)
    mim_0  = _place_mim_w3(c, cache, dx=  0.000, dy=dy_mim, mirror_x=True)
    mim_1a = _place_mim_w3(c, cache, dx=+13.800, dy=dy_mim, mirror_x=True)

    # Join all 3 C1 (top plate = sp) on M4 at y = +11.450 -> drop at x_sp_drop = t_sp_xs[-1] (+7.110)
    y_mim_sp = +11.450
    for m_info in (mim_1b, mim_0, mim_1a):
        cx1, cy1 = m_info["c1"]
        c.wire("metal4", [(cx1, y_mim_sp), (cx1, cy1)], 0.720)
    c.wire("metal4", [(mim_1b["c1"][0], y_mim_sp), (mim_1a["c1"][0], y_mim_sp)], 0.720)
    x_sp_drop = t_sp_xs[-1]  # +7.110
    via3_pad(c, x_sp_drop, y_mim_sp)
    via2_clean(c, x_sp_drop, y_mim_sp)
    c.wire("metal2", [(x_sp_drop, y_mim_sp), (x_sp_drop, y_tail_sp)], 0.440)

    # Join `cap0` & `cap1` on North M4 (well clear of 6x6 mimcap top ~ +21.5 -> ZERO capm.11!)
    y_cap0_m4 = +27.650
    c.wire("metal4", [mim_0["c2"], (mim_0["c2"][0], y_cap0_m4), (cx_sw0, y_cap0_m4)], 0.520)
    via3_pad(c, cx_sw0, y_cap0_m4)
    via2_clean(c, cx_sw0, y_cap0_m4)
    c.wire("metal2", [(cx_sw0, y_eq_tie), (cx_sw0, y_cap0_m4)], 0.340)

    y_cap1_m4 = +28.500
    c.wire("metal4", [mim_1b["c2"], (mim_1b["c2"][0], y_cap1_m4), (mim_1a["c2"][0], y_cap1_m4), mim_1a["c2"]], 0.520)
    via3_pad(c, cx_sw1, y_cap1_m4)
    via2_clean(c, cx_sw1, y_cap1_m4)
    c.wire("metal2", [(cx_sw1, y_eq_tie), (cx_sw1, y_cap1_m4)], 0.340)

    # =========================================================================
    # SOUTH BAND (100% MIM-FREE!): 2D CC Xip/Xin (`w=19.2, 2.40 um/f`) + Xrp/Xrn (`l=2.83`)
    # =========================================================================
    cx_q_l, cx_q_r = -2.600, +2.600
    dy_q_s, dy_q_n = +3.550, +8.450
    m_in_s, inf_in_s = cache.build_mos(N_LVT, 2.40, 0.15, 4, dy_q_s, False)
    m_in_n, inf_in_n = cache.build_mos(N_LVT, 2.40, 0.15, 4, dy_q_n, False)
    for cx_q in (cx_q_l, cx_q_r):
        c.include(m_in_s, dx=cx_q)
        c.include(m_in_n, dx=cx_q)

    y_q_gr_s = +1.250
    y_q_gr_n = +10.750
    x_q_gr_l = -5.200
    x_q_gr_r = +5.200
    draw_tap_h(c, "psubdiff", x_q_gr_l, x_q_gr_r, y_q_gr_s, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", x_q_gr_l, x_q_gr_r, y_q_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_q_gr_l, y_q_gr_s, y_q_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_q_gr_r, y_q_gr_s, y_q_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    c.wire("metal1", [(x_q_gr_l, y_q_gr_n), (x_q_gr_l, y_tail_gr_s)], 0.340)
    c.wire("metal1", [(x_q_gr_r, y_q_gr_n), (x_q_gr_r, y_tail_gr_s)], 0.340)

    for inf_r, y_dum_c in ((inf_in_s, dy_q_s), (inf_in_n, dy_q_n)):
        xd_l = grid(cx_q_l + inf_r["diff_x1"] - 0.140 - 0.075)
        xd_r = grid(cx_q_r + inf_r["diff_x2"] + 0.140 + 0.075)
        pt_l = add_tied_poly_dummy(c, xd_l, inf_r["poly_y1"], inf_r["poly_y2"], 0.15, y_cont=y_dum_c, x_cont=grid(xd_l - 0.300))
        pt_r = add_tied_poly_dummy(c, xd_r, inf_r["poly_y1"], inf_r["poly_y2"], 0.15, y_cont=y_dum_c, x_cont=grid(xd_r + 0.300))
        c.wire("metal1", [(x_q_gr_l, y_dum_c), pt_l], 0.290)
        c.wire("metal1", [pt_r, (x_q_gr_r, y_dum_c)], 0.290)

    q_s_pts: dict[str, tuple[float, float]] = {}
    q_d_pts: dict[str, tuple[float, float]] = {}
    q_g_pts: dict[str, tuple[float, float]] = {}
    for qname, cx_q, inf_r, y_s, y_d, y_gb, y_gc in (
        ("SW", cx_q_l, inf_in_s, +2.850, +4.150, +5.150, +5.550),
        ("SE", cx_q_r, inf_in_s, +2.850, +4.150, +5.150, +5.550),
        ("NW", cx_q_l, inf_in_n, +9.150, +7.850, +6.850, +6.450),
        ("NE", cx_q_r, inf_in_n, +9.150, +7.850, +6.850, +6.450),
    ):
        s_xs = [grid(cx_q + x) for x in inf_r["s_xs"]]
        d_xs = [grid(cx_q + x) for x in inf_r["d_xs"]]
        for sx in s_xs:
            for vy in (grid(inf_r["dy"] - 0.75), inf_r["dy"], grid(inf_r["dy"] + 0.75)):
                viali_pad(c, sx, vy)
            c.wire("metal1", [(sx, grid(inf_r["dy"] - 0.75)), (sx, grid(inf_r["dy"] + 0.75))], 0.320)
            via1_clean(c, sx, y_s)
        c.wire("metal2", [(s_xs[0], y_s), (s_xs[-1], y_s)], 0.360)
        q_s_pts[qname] = (cx_q, y_s)

        for dx_i in d_xs:
            for vy in (grid(inf_r["dy"] - 0.75), inf_r["dy"], grid(inf_r["dy"] + 0.75)):
                viali_pad(c, dx_i, vy)
            c.wire("metal1", [(dx_i, grid(inf_r["dy"] - 0.75)), (dx_i, grid(inf_r["dy"] + 0.75))], 0.320)
            via1_clean(c, dx_i, y_d)
        c.wire("metal2", [(d_xs[0], y_d), (d_xs[-1], y_d)], 0.360)
        q_d_pts[qname] = (cx_q, y_d)

        gp = tie_mos_gates(c, cx_q, inf_r, y_bar=y_gb, y_cont=y_gc, tap_xs=[cx_q])[0]
        q_g_pts[qname] = gp

    # Equal-Length East `inp` (NW+SE) / `inn` (NE+SW) M3 buses (exact same Y = +6.45 / +5.55!)
    y_inp_m3, y_inn_m3 = +6.450, +5.550
    x_se_m2, x_ne_m2 = +2.100, +3.100
    c.wire("metal1", [(x_se_m2, y_inn_m3), q_g_pts["SE"]], 0.290)
    via1_clean(c, x_se_m2, y_inn_m3)
    c.wire("metal2", [(x_se_m2, y_inn_m3), (x_se_m2, y_inp_m3)], 0.280)
    via2_clean(c, x_se_m2, y_inp_m3)

    c.wire("metal1", [q_g_pts["NE"], (x_ne_m2, y_inp_m3)], 0.290)
    via1_clean(c, x_ne_m2, y_inp_m3)
    c.wire("metal2", [(x_ne_m2, y_inn_m3), (x_ne_m2, y_inp_m3)], 0.280)
    via2_clean(c, x_ne_m2, y_inn_m3)

    via1_clean(c, *q_g_pts["NW"])
    via2_clean(c, *q_g_pts["NW"])
    via1_clean(c, *q_g_pts["SW"])
    via2_clean(c, *q_g_pts["SW"])

    c.rect("metal3", grid(q_g_pts["NW"][0] - 0.260), grid(y_inp_m3 - 0.190), x_e_port, grid(y_inp_m3 + 0.190))
    c.rect("metal3", grid(q_g_pts["SW"][0] - 0.260), grid(y_inn_m3 - 0.190), x_e_port, grid(y_inn_m3 + 0.190))

    # Symmetric 2D CC Source Routing (`sp`: NW+SE; `sn`: NE+SW) into 20f tail
    x_sn_l = -8.100
    x_sp_r = +8.100
    y_sn_hop = +13.550

    c.wire("metal2", [q_s_pts["SE"], (x_sp_r, q_s_pts["SE"][1]), (x_sp_r, y_tail_sp), (t_sp_xs[-1], y_tail_sp)], 0.400)
    c.wire("metal2", [q_s_pts["NW"], (cx_q_l, y_tail_sp)], 0.400)

    c.wire("metal2", [q_s_pts["SW"], (x_sn_l, q_s_pts["SW"][1]), (x_sn_l, y_tail_sn), (t_sn_xs[0], y_tail_sn)], 0.400)
    c.wire("metal2", [q_s_pts["NE"], (cx_q_r, y_sn_hop), (-1.450, y_sn_hop)], 0.380)
    via1_clean(c, -1.450, y_sn_hop)
    c.wire("metal1", [(x_sn_l, y_sn_hop), (-1.450, y_sn_hop)], 0.360)
    via1_clean(c, x_sn_l, y_sn_hop)

    # Split Mirror-Symmetric Load Resistors: `Xrp` (-11.20) & `Xrn` (+11.20), trimmed `l = 2.83`!
    rld1 = cache.device(R_2P85, dict(l=2.83, nx=1, m=1, guard=1))
    r1_out = rld1.pins("R1")[0]
    r1_lp  = rld1.pins("R2")[0]
    r1_b   = rld1.pins("B")[0]
    rld1.labels.clear()

    dx_rp, dx_rn, dy_rld = -11.200, +11.200, +6.000
    c.include(rld1, dx=dx_rp, dy=dy_rld)
    c.include(rld1, dx=dx_rn, dy=dy_rld)

    p_rp_out = (grid(dx_rp + r1_out[0]), grid(dy_rld + r1_out[1]))
    p_rn_out = (grid(dx_rn + r1_out[0]), grid(dy_rld + r1_out[1]))
    p_rp_lp  = (grid(dx_rp + r1_lp[0]),  grid(dy_rld + r1_lp[1]))
    p_rn_ln  = (grid(dx_rn + r1_lp[0]),  grid(dy_rld + r1_lp[1]))
    p_rp_b   = (grid(dx_rp + r1_b[0]),   grid(dy_rld + r1_b[1]))
    p_rn_b   = (grid(dx_rn + r1_b[0]),   grid(dy_rld + r1_b[1]))

    for pb, x_gr in ((p_rp_b, x_q_gr_l), (p_rn_b, x_q_gr_r)):
        viali_pad(c, pb[0], pb[1])
        c.wire("metal1", [pb, (x_gr, pb[1]), (x_gr, y_q_gr_s)], 0.340)

    # Ultra-Symmetric South `lp_mid` (-4.60, 0.00) & `ln_mid` (+4.60, 0.00) M4 Ports!
    x_lp_port, x_ln_port = -4.600, +4.600
    y_lp_bus = +0.500
    for p_res, x_port in ((p_rp_lp, x_lp_port), (p_rn_ln, x_ln_port)):
        for dxv in (-0.800, 0.000, +0.800):
            via1_clean(c, grid(p_res[0] + dxv), p_res[1])
        c.wire("metal2", [(grid(p_res[0] - 0.800), p_res[1]), (grid(p_res[0] + 0.800), p_res[1])], 0.440)
        c.wire("metal2", [p_res, (p_res[0], y_lp_bus), (x_port, y_lp_bus)], 0.600)
        for dxv in (-0.360, +0.360):
            vx = grid(x_port + dxv)
            via2_clean(c, vx, y_lp_bus)
            via3_pad(c, vx, y_lp_bus)
        c.rect("metal2", grid(x_port - 0.660), grid(y_lp_bus - 0.300), grid(x_port + 0.660), grid(y_lp_bus + 0.300))
        c.rect("metal3", grid(x_port - 0.660), grid(y_lp_bus - 0.260), grid(x_port + 0.660), grid(y_lp_bus + 0.260))
        c.rect("metal4", grid(x_port - 0.900), y_s_edge, grid(x_port + 0.900), grid(y_lp_bus + 0.300))

    # Mirror-Symmetric `outp` & `outn` West Exit (exact same Y = +7.30 / +4.70!)
    x_sw_out = grid(cx_q_l + inf_in_s["d_xs"][0])
    x_se_out = grid(cx_q_r + inf_in_s["d_xs"][-1])
    for p_out, x_qd, y_qd in ((p_rp_out, x_sw_out, q_d_pts["SW"][1]), (p_rn_out, x_se_out, q_d_pts["SE"][1])):
        for dxv in (-0.800, 0.000, +0.800):
            via1_clean(c, grid(p_out[0] + dxv), p_out[1])
        c.wire("metal2", [(grid(p_out[0] - 0.800), p_out[1]), (grid(p_out[0] + 0.800), p_out[1])], 0.440)
        c.wire("metal2", [(p_out[0], y_qd), p_out], 0.440)
        via2_clean(c, p_out[0], y_qd)
        via2_clean(c, x_qd, y_qd)
        c.wire("metal3", sorted([(p_out[0], y_qd), (x_qd, y_qd)], key=lambda p: p[0]), 0.400)

    y_outp_bus = +7.300
    y_outn_bus = +4.700
    x_sw_in = grid(cx_q_l + inf_in_s["d_xs"][-1])
    x_se_in = grid(cx_q_r + inf_in_s["d_xs"][0])

    c.wire("metal2", [(x_sw_in, q_d_pts["SW"][1]), (-0.500, q_d_pts["SW"][1]), (-0.500, y_outp_bus)], 0.360)
    via2_clean(c, -0.500, y_outp_bus)
    c.wire("metal3", [(-0.500, y_outp_bus), (+1.500, y_outp_bus)], 0.400)
    via2_clean(c, +1.500, y_outp_bus)
    c.wire("metal2", [(+1.500, y_outp_bus), (+1.500, q_d_pts["NE"][1]), (x_se_in, q_d_pts["NE"][1])], 0.360)

    c.wire("metal2", [(x_se_in, q_d_pts["SE"][1]), (+0.500, q_d_pts["SE"][1]), (+0.500, y_outn_bus)], 0.360)
    via2_clean(c, +0.500, y_outn_bus)
    c.wire("metal3", [(-1.500, y_outn_bus), (+0.500, y_outn_bus)], 0.400)
    via2_clean(c, -1.500, y_outn_bus)
    c.wire("metal2", [(-1.500, y_outn_bus), (-1.500, q_d_pts["NW"][1]), (x_sw_in, q_d_pts["NW"][1])], 0.360)

    x_v3_outp = +1.500
    x_v3_outn = -1.500
    via3_pad(c, x_v3_outp, y_outp_bus)
    c.rect("metal4", x_w_port, grid(y_outp_bus - 0.200), grid(x_v3_outp + 0.260), grid(y_outp_bus + 0.200))
    via3_pad(c, x_v3_outn, y_outn_bus)
    c.rect("metal4", x_w_port, grid(y_outn_bus - 0.200), grid(x_v3_outn + 0.260), grid(y_outn_bus + 0.200))

    ports = {
        "inp":    ("metal3", x_e_port,  y_inp_m3),
        "inn":    ("metal3", x_e_port,  y_inn_m3),
        "outp":   ("metal4", x_w_port,  y_outp_bus),
        "outn":   ("metal4", x_w_port,  y_outn_bus),
        "lp_mid": ("metal4", x_lp_port, y_s_edge),
        "ln_mid": ("metal4", x_ln_port, y_s_edge),
        "eq0":    ("metal1", x_w_port,  y_eq0_out),
        "eq1":    ("metal1", x_w_port,  y_eq1_out),
        "vbias":  ("metal1", x_e_port,  y_vbias),
        "vdd":    ("metal2", x_vdd_act, y_s_edge),
        "vss":    ("metal2", x_w_port,  y_vss_n),
    }
    if add_ports:
        for nm in ACTIVE_PORTS:
            lyr, px, py = ports[nm]
            c.port(nm, lyr, px, py)

    return c, {
        "ports": {nm: {"layer": lyr, "x_um": px, "y_um": py} for nm, (lyr, px, py) in ports.items()},
        "x_w_port": x_w_port,
        "x_e_port": x_e_port,
        "y_vss_n": y_vss_n,
        "x_vdd_act": x_vdd_act,
        "y_inp_m3": y_inp_m3,
        "y_inn_m3": y_inn_m3,
        "y_outp_bus": y_outp_bus,
        "y_outn_bus": y_outn_bus,
        "y_eq0_out": y_eq0_out,
        "y_eq1_out": y_eq1_out,
        "y_vbias": y_vbias,
    }


def build_w3_ctle_top(
    active_cell: Cell,
    active_meta: dict,
    *,
    include_inductor: bool = True,
    add_ports: bool = True,
) -> tuple[Cell, dict]:
    """Assemble flat W3 `serdes_rx_ctle_shunt_5g_w3_pdk` (`57.60 x 94.20 um`, 0% M5)."""
    c = Cell()
    act_unlbl = rlc.clone_cell(active_cell)
    act_unlbl.labels.clear()
    c.include(act_unlbl, dx=0.0, dy=0.0)

    ind_cy = -35.000
    if include_inductor:
        ind = Cell.read(IND_COMPACT_MAG)
        ind.labels.clear()
        c.include(ind, dx=0.0, dy=ind_cy, mirror_x=True, mirror_y=True)

    x_west, x_east = -28.800, +28.800
    x_act_w = active_meta["x_w_port"]    # -20.700
    x_act_e = active_meta["x_e_port"]    # +20.700
    x_vdd_act = active_meta["x_vdd_act"] # -20.100
    y_vss_top = active_meta["y_vss_n"]   # +28.600
    y_vdd_top = -4.200
    y_vss_m3 = grid(y_vss_top + 0.900)   # +29.500 (strictly North of y_vbias=+26.40 & y_cap1_m4=+27.60!)

    # Mirror-symmetric zero-via M4 `lp_mid`/`ln_mid` feeds
    for sgn in (-1.0, +1.0):
        xa, xi = sgn * 4.600, sgn * 3.000
        c.rect("metal4", grid(xa - 0.600), -2.400, grid(xa + 0.600), +0.400)
        c.rect("metal4", grid(min(xa, xi) - 0.600), -2.400, grid(max(xa, xi) + 0.600), -1.200)
        c.rect("metal4", grid(xi - 0.600), -9.000, grid(xi + 0.600), -1.200)

    # Low-impedance `ct -> vdd` M3 rail at y=-4.20 + M4 wings
    c.rect("metal2", -0.600, -9.000, +0.600, grid(y_vdd_top + 0.600))
    for dxv in (-0.300, +0.300):
        for dyv in (-0.300, +0.300):
            c.pad("via2", dxv, grid(y_vdd_top + dyv), 0.280)
    c.rect("metal3", x_west, grid(y_vdd_top - 0.900), x_east, grid(y_vdd_top + 0.900))
    for xa, xb in ((x_west, -6.400), (+6.400, x_east)):
        c.rect("metal4", xa, grid(y_vdd_top - 0.900), xb, grid(y_vdd_top + 0.900))
        xv = grid(xa + 1.200)
        while xv <= xb - 1.200 + 1e-6:
            for dyv in (-0.360, +0.360):
                c.pad("via3", xv, grid(y_vdd_top + dyv), 0.320)
            xv = grid(xv + 4.000)

    c.rect("metal2", grid(x_vdd_act - 0.400), grid(y_vdd_top - 0.600), grid(x_vdd_act + 0.400), +0.200)
    for dxv in (-0.220, +0.220):
        for dyv in (-0.300, +0.300):
            c.pad("via2", grid(x_vdd_act + dxv), grid(y_vdd_top + dyv), 0.280)

    # Wide North `vss` rail (`1.80 um` M3 at y=+29.50 + full-width M2)
    c.rect("metal2", x_west, grid(y_vss_top - 0.400), x_east, grid(y_vss_m3 + 0.500))
    c.rect("metal3", x_west, grid(y_vss_m3 - 0.900), x_east, grid(y_vss_m3 + 0.900))
    for xv in (-24.0, -16.0, -8.0, 0.0, +8.0, +16.0, +24.0):
        for dyv in (-0.300, +0.300):
            c.pad("via2", xv, grid(y_vss_m3 - 0.150 + dyv), 0.280)

    # Single-sided West `vss` tie to inductor open-slotted P+ guard ring
    x_vss_gr = -22.800
    y_gr_n = grid(ind_cy + 28.000)  # -7.000
    c.rect("metal2", grid(x_vss_gr - 0.700), grid(y_gr_n - 0.700), grid(x_vss_gr + 0.700), grid(y_vss_m3 + 0.500))
    c.rect("metal1", grid(x_vss_gr - 0.700), grid(y_gr_n - 0.700), grid(x_vss_gr + 0.700), grid(y_gr_n + 0.700))
    for dxv in (-0.360, 0.000, +0.360):
        for dyv in (-0.360, +0.360):
            c.pad("via1", grid(x_vss_gr + dxv), grid(y_gr_n + dyv), 0.260)

    # Straight cardinal perimeter extensions
    y_inp, y_inn = active_meta["y_inp_m3"], active_meta["y_inn_m3"]
    y_outp, y_outn = active_meta["y_outp_bus"], active_meta["y_outn_bus"]
    y_eq0, y_eq1 = active_meta["y_eq0_out"], active_meta["y_eq1_out"]
    y_vbias = active_meta["y_vbias"]

    c.rect("metal3", x_act_e, grid(y_inp - 0.190), x_east, grid(y_inp + 0.190))
    c.rect("metal3", x_act_e, grid(y_inn - 0.190), x_east, grid(y_inn + 0.190))
    c.rect("metal4", x_west, grid(y_outp - 0.200), x_act_w, grid(y_outp + 0.200))
    c.rect("metal4", x_west, grid(y_outn - 0.200), x_act_w, grid(y_outn + 0.200))
    c.rect("metal1", x_west, grid(y_eq0 - 0.140), x_act_w, grid(y_eq0 + 0.140))
    c.rect("metal1", x_west, grid(y_eq1 - 0.140), x_act_w, grid(y_eq1 + 0.140))

    x_vb_via = grid(x_act_e + 0.600)
    c.rect("metal1", grid(x_act_e - 0.170), grid(y_vbias - 0.170), grid(x_vb_via + 0.200), grid(y_vbias + 0.170))
    via1_clean(c, x_vb_via, y_vbias)
    c.rect("metal2", grid(x_vb_via - 0.170), grid(y_vbias - 0.170), x_east, grid(y_vbias + 0.170))

    top_ports = {
        "inp":   ("metal3", x_east, y_inp),
        "inn":   ("metal3", x_east, y_inn),
        "outp":  ("metal4", x_west, y_outp),
        "outn":  ("metal4", x_west, y_outn),
        "eq0":   ("metal1", x_west, y_eq0),
        "eq1":   ("metal1", x_west, y_eq1),
        "vbias": ("metal2", x_east, y_vbias),
        "vdd":   ("metal3", x_west, y_vdd_top),
        "vss":   ("metal3", x_west, y_vss_m3),
    }
    if add_ports:
        for nm in TOP_PORTS:
            lyr, px, py = top_ports[nm]
            c.port(nm, lyr, px, py)

    return c, {
        "ports": {nm: {"layer": lyr, "x_um": px, "y_um": py} for nm, (lyr, px, py) in top_ports.items()},
        "ind_center_um": [0.0, ind_cy],
        "vdd_rail_y_um": y_vdd_top,
        "vss_rail_y_um": y_vss_m3,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signoff", action="store_true")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(RESULTS_DIR / "_pdk_cache")

    print(f"\n=== [1/3] Building & Verifying W3 Active Core `{ACTIVE_NAME}` ===")
    w_act = RESULTS_DIR / "active_verify"
    w_act.mkdir(parents=True, exist_ok=True)
    act_cell, act_meta = build_rx_ctle_active_5g_w3_pdk(cache, add_ports=True)
    act_mag = w_act / f"{ACTIVE_NAME}.mag"
    act_cell.write(act_mag)
    act_ref = w_act / f"{ACTIVE_NAME}_ref.spice"
    act_ref.write_text("\n".join([
        f"* Exact W3 active LVS ref for {ACTIVE_NAME}",
        f".subckt {ACTIVE_NAME} " + " ".join(ACTIVE_PORTS),
        *active_primitive_lines_w3("lp_mid", "ln_mid"),
        f".ends {ACTIVE_NAME}", "",
    ]))
    act_res = rlc.verify_flat_cell(w_act, ACTIVE_NAME, act_mag, act_ref, ACTIVE_PORTS, timeout_s=180)
    act_png = RESULTS_DIR / f"{ACTIVE_NAME}.png"
    rlc.render_png_plot_mag(act_mag, act_png)
    print(f"  Active W3: {act_res['width_um']}x{act_res['height_um']} um | "
          f"DRC={act_res['drc_total']} FP={act_res['floating_poly']} "
          f"LVS={act_res['lvs_match']} prop_err={act_res['lvs_property_errors']}")
    if act_res["drc_total"] != 0:
        print("  ACTIVE DRC RULES:", act_res["drc_rules"])
    assert act_res["drc_total"] == 0, f"Active DRC failed: {act_res['drc_rules']}"
    assert act_res["floating_poly"] == 0, "Active floating poly!"
    assert act_res["lvs_match"] and not act_res["lvs_property_errors"], "Active LVS failed!"

    print(f"\n=== [2/3] Building & Verifying Integrated W3 `{TOP_NAME}` (57.6 um M4+M2, 0% M5) ===")
    w_top = RESULTS_DIR / "top_verify"
    w_top.mkdir(parents=True, exist_ok=True)
    top_cell, top_meta = build_w3_ctle_top(act_cell, act_meta, include_inductor=True, add_ports=True)
    top_mag = w_top / f"{TOP_NAME}.mag"
    top_cell.write(top_mag)
    dc_ref = w_top / f"{TOP_NAME}_dc_ref.spice"
    dc_ref.write_text("\n".join([
        f"* DC-equivalent flat LVS ref for {TOP_NAME}",
        f".subckt {TOP_NAME} " + " ".join(TOP_PORTS),
        *active_primitive_lines_w3("vdd", "vdd"),
        f".ends {TOP_NAME}", "",
    ]))
    top_res = rlc.verify_flat_cell(w_top, TOP_NAME, top_mag, dc_ref, TOP_PORTS, timeout_s=180)
    top_png = RESULTS_DIR / f"{TOP_NAME}.png"
    rlc.render_png_plot_mag(top_mag, top_png)
    print(f"  Top W3: {top_res['width_um']}x{top_res['height_um']} um ({top_res['area_um2']} um^2) | "
          f"DRC={top_res['drc_total']} FP={top_res['floating_poly']} "
          f"DC-LVS={top_res['lvs_match']} prop_err={top_res['lvs_property_errors']}")
    if top_res["drc_total"] != 0:
        print("  TOP DRC RULES:", top_res["drc_rules"])
    assert top_res["drc_total"] == 0, f"Top DRC failed: {top_res['drc_rules']}"
    assert top_res["floating_poly"] == 0
    assert top_res["lvs_match"] and not top_res["lvs_property_errors"]

    print(f"\n=== [3/3] Running Inductor-Open Interconnect LVS & CPEX (`{TOP_NAME}_open`) ===")
    w_open = RESULTS_DIR / "open_verify"
    w_open.mkdir(parents=True, exist_ok=True)
    open_name = f"{TOP_NAME}_open"
    open_cell, _ = build_w3_ctle_top(act_cell, act_meta, include_inductor=False, add_ports=True)
    open_cell.port("lp_mid", "metal4", -3.000, -8.500)
    open_cell.port("ln_mid", "metal4", +3.000, -8.500)
    open_mag = w_open / f"{open_name}.mag"
    open_cell.write(open_mag)
    open_ref = w_open / f"{open_name}_ref.spice"
    open_ref.write_text("\n".join([
        f"* Inductor-open LVS ref for {TOP_NAME}",
        f".subckt {open_name} " + " ".join(ACTIVE_PORTS),
        *active_primitive_lines_w3("lp_mid", "ln_mid"),
        f".ends {open_name}", "",
    ]))
    open_res = rlc.verify_flat_cell(w_open, open_name, open_mag, open_ref, ACTIVE_PORTS, timeout_s=180)
    print(f"  Open W3: DRC={open_res['drc_total']} FP={open_res['floating_poly']} "
          f"LVS={open_res['lvs_match']} prop_err={open_res['lvs_property_errors']}")
    assert open_res["drc_total"] == 0
    assert open_res["lvs_match"] and not open_res["lvs_property_errors"]

    open_pex = w_open / f"{open_name}_pex.spice"
    act_pex = w_act / f"{ACTIVE_NAME}_pex.spice"
    sha = hashlib.sha256(top_mag.read_bytes()).hexdigest()

    summary = {
        "variant": "ctle_shunt_5g_w3_pdk",
        "cell": TOP_NAME,
        "active_cell": ACTIVE_NAME,
        "pdk": "sky130A",
        "gmid_design_point": {
            "gm_id_tt_S_A": 10.7,
            "win_um": 19.2, "nfin": 8,
            "wtail_um": 90.0, "nftail": 10,
            "l_rload_um": 2.83, "l_rdeg_um": 5.10,
            "c_mim_w_um": 6.00, "wsw_n_um": 8.0, "wsw_p_um": 16.0,
            "inductor": "rx_ctle_ind_m4m2_5g_pdk (57.6x57.6 um, 4.10 nH/arm, 0% M5)",
        },
        "active_bbox_um": act_res["bbox_um"],
        "active_width_um": act_res["width_um"],
        "active_height_um": act_res["height_um"],
        "bbox_um": top_res["bbox_um"],
        "width_um": top_res["width_um"],
        "height_um": top_res["height_um"],
        "area_um2": top_res["area_um2"],
        "area_mm2": round(top_res["area_um2"] / 1e6, 5),
        "area_vs_m5m3_ctle_pct": round(top_res["area_um2"] / 11477.48 * 100.0, 1),
        "aspect_ratio": top_res["aspect_ratio"],
        "ports": top_meta["ports"],
        "drc_total": top_res["drc_total"],
        "drc_rules": top_res["drc_rules"],
        "floating_poly": top_res["floating_poly"],
        "dc_lvs_match": top_res["lvs_match"],
        "dc_lvs_property_errors": top_res["lvs_property_errors"],
        "inductor_open_drc_total": open_res["drc_total"],
        "inductor_open_lvs_match": open_res["lvs_match"],
        "inductor_open_lvs_property_errors": open_res["lvs_property_errors"],
        "metal_shares": top_res["metal_shares"],
        "inductor_open_port_caps_fF": open_res["parasitics"].get("port_caps_fF", {}),
        "inductor_submacro": str(IND_COMPACT_MAG.relative_to(REPO)),
        "mag_sha256": sha,
    }
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("metal_shares:", summary["metal_shares"]["share_pct"])
    for nm in ("inp", "inn", "outp", "outn", "lp_mid", "ln_mid"):
        pc = summary["inductor_open_port_caps_fF"].get(nm)
        if pc:
            print(f"  OPEN {nm:8s}: {pc}")

    if args.signoff:
        VARIANT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(top_mag, VARIANT_DIR / f"{TOP_NAME}.mag")
        shutil.copy2(top_png, VARIANT_DIR / f"{TOP_NAME}.png")
        shutil.copy2(w_top / f"{TOP_NAME}_lvs.spice", VARIANT_DIR / f"{TOP_NAME}_lvs.spice")
        shutil.copy2(open_pex, VARIANT_DIR / f"{TOP_NAME}_open_pex.spice")
        shutil.copy2(act_pex, VARIANT_DIR / f"{ACTIVE_NAME}_pex.spice")
        shutil.copy2(act_mag, VARIANT_DIR / f"{ACTIVE_NAME}.mag")
        shutil.copy2(act_png, VARIANT_DIR / f"{ACTIVE_NAME}.png")
        shutil.copy2(dc_ref, VARIANT_DIR / f"{TOP_NAME}_ref.spice")
        (VARIANT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"SIGNOFF PASS: {TOP_NAME} -> {VARIANT_DIR}")


if __name__ == "__main__":
    main()
