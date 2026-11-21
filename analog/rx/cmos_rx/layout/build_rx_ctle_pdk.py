#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builders for RX v2 Front-End Analog Units:
  1. `serdes_rx_term_pdk` : 2x 50 Ohm split RX input termination (8x res_high_po_5p73 l=2.34
                            in 2D Common-Centroid ABBA/BAAB inside a shared p-sub guard ring,
                            symmetric low-C M4/M5 inp/inn West ports, M3 East vcm, vss guard tie).
  2. `serdes_rx_ctle_pdk` : Lean 1.31 mW PDK RC-degenerated CTLE:
                            - 2D Common-Centroid LVT NMOS input pair Xip/Xin ([[Ip,In],[In,Ip]])
                            - 16-finger shared-diffusion ABBA LVT NMOS tail sinks Xtp/Xtn
                            - Matched high_po_2p85 load resistors Xrp/Xrn + Under-MIM Rdeg
                            - 3D-stacked 3x 200 fF MIM caps (Ceq0=1x, Ceq1=2x) over tail/Rdeg/EQ
                            - Static L=0.18 EQ inverters, transmission-gate switches & bleed FETs
                            - Ultra-symmetric West inp/inn and East outp/outn (|dC(outp,outn)| << 1 fF).
"""
from __future__ import annotations

from pathlib import Path
import sys

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
    R_5P73,
    MIM1,
    W_M1,
    grid,
    poly_cont_pad,
    viali_pad,
    via1_clean,
    via2_clean,
    via3_pad,
    via4_pad,
    locali_v,
    draw_tap_h,
    draw_tap_v,
    tie_mos_gates,
    add_tied_poly_dummy,
)


# ---------------------------------------------------------------------------
# 1. serdes_rx_term_pdk (2x 50 Ohm 2D Common-Centroid Split Input Termination)
# ---------------------------------------------------------------------------

def build_rx_term_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build `serdes_rx_term_pdk` (ports: inp inn vcm vss).

    2D Common-Centroid ABBA / BAAB using two stacked `nx=4` blocks of
    `sky130_fd_pr__res_high_po_5p73 l=2.34` with continuous shared p-sub guard
    ring and >= 1.1 um RPM spacing (zero rpm.2):
      - Top row (dy = +4.100): P0(-9.315), N0(-3.105), N1(+3.105), P1(+9.315)
      - Bot row (dy = -4.100): N2(-9.315), P2(-3.105), P3(+3.105), N3(+9.315)
    Central horizontal M2+M3 `vcm` spine along y=0.000 exits East; symmetric
    low-C M3->M4->M5 `inp`/`inn` trunks exit West at y = +-2.400.
    """
    c = Cell()

    r4 = cache.device(R_5P73, dict(l=2.34, nx=4, m=1, guard=1))
    xs_bar = [grid(r4.pins(f"R1_{i}")[0][0]) for i in range(4)]  # [-9.315, -3.105, +3.105, +9.315]
    y_r1 = grid(r4.pins("R1_0")[0][1])  # +3.075
    y_r2 = grid(r4.pins("R2_0")[0][1])  # -3.075
    r4.labels.clear()

    # dy = +-4.100 gives 1.11 um RPM spacing (> 0.84 um rpm.2) while merging pwell cleanly
    dy_top = +4.100
    dy_bot = -4.100
    c.include(r4, dx=0.0, dy=dy_top)
    c.include(r4, dx=0.0, dy=dy_bot)

    # Merge the two central guard-ring bars into one continuous p-sub tap strip along y = 0.000
    # (omit extra psubdiffcont here so existing guard-ring contacts keep >= 0.17 um licon.2 spacing)
    c.rect("pwell", -13.010, -0.500, +13.010, +0.500)
    c.rect("psubdiff", -12.830, -0.370, +12.830, +0.370)
    c.rect("locali", -12.830, -0.370, +12.830, +0.370)

    y_top_out = grid(dy_top + y_r1)  # +7.175
    y_top_in  = grid(dy_top + y_r2)  # +1.025
    y_bot_in  = grid(dy_bot + y_r1)  # -1.025
    y_bot_out = grid(dy_bot + y_r2)  # -7.175

    # 1. Central `vcm` spine along y = 0.000 (M2 combs on all 8 inner heads + wide M3 trunk exiting East)
    x_east_vcm = 14.400
    for xb in xs_bar:
        for dxv in (-1.600, 0.000, +1.600):
            vx = grid(xb + dxv)
            via1_clean(c, vx, y_top_in)
            via1_clean(c, vx, y_bot_in)
            c.wire("metal2", [(vx, y_bot_in), (vx, y_top_in)], 0.360)
        via2_clean(c, xb, 0.000)
    c.wire("metal2", [(xs_bar[0] - 1.600, 0.000), (xs_bar[-1] + 1.600, 0.000)], 0.900)
    c.wire("metal3", [(xs_bar[0], 0.000), (x_east_vcm, 0.000)], 0.900)

    # 2. Symmetric `vss` p-sub guard ring tie (East guard bar -> M2 spine -> East port at y = -4.100)
    x_guard_e = 12.745
    for y_tie in (-dy_top, +dy_top):
        viali_pad(c, x_guard_e, y_tie)
        via1_clean(c, x_guard_e, y_tie)
    viali_pad(c, x_guard_e, grid(dy_top + 3.815))
    viali_pad(c, x_guard_e, grid(dy_bot - 3.815))
    c.wire("metal1", [(x_guard_e, grid(dy_bot - 3.815)), (x_guard_e, grid(dy_top + 3.815))], 0.340)
    x_vss_sp = 13.450
    for y_tie in (-dy_top, +dy_top):
        c.wire("metal2", [(x_guard_e, y_tie), (x_vss_sp, y_tie)], 0.400)
    c.wire("metal2", [(x_vss_sp, -dy_top), (x_vss_sp, +dy_top)], 0.440)
    c.wire("metal2", [(x_vss_sp, -dy_top), (x_east_vcm, -dy_top)], 0.440)

    # 3. Ultra-symmetric low-C M3->M4->M5 `inp` & `inn` routing to West ports (ZERO M4 crossings!)
    y_tp, y_tn = +7.550, +6.350
    y_bp, y_bn = -6.350, -7.550
    x_m4_p = -13.900
    x_m4_n = -16.100
    x_west_port = -17.600
    y_port_p, y_port_n = +2.400, -2.400

    head_specs = [
        (xs_bar[0], y_top_out, y_tp),
        (xs_bar[3], y_top_out, y_tp),
        (xs_bar[1], y_top_out, y_tn),
        (xs_bar[2], y_top_out, y_tn),
        (xs_bar[1], y_bot_out, y_bp),
        (xs_bar[2], y_bot_out, y_bp),
        (xs_bar[0], y_bot_out, y_bn),
        (xs_bar[3], y_bot_out, y_bn),
    ]
    for xb, yh, yt in head_specs:
        for dxv in (-1.400, 0.000, +1.400):
            vx = grid(xb + dxv)
            via1_clean(c, vx, yh)
            c.wire("metal2", [(vx, yh), (vx, yt)], 0.360)
            via2_clean(c, vx, yt)
        c.wire("metal2", [(grid(xb - 1.400), yt), (grid(xb + 1.400), yt)], 0.440)

    # Horizontal M3 buses to West M4 risers
    c.wire("metal3", [(x_m4_p, y_tp), (grid(xs_bar[3] + 1.400), y_tp)], 0.560)
    c.wire("metal3", [(x_m4_p, y_bp), (grid(xs_bar[2] + 1.400), y_bp)], 0.560)
    c.wire("metal3", [(x_m4_n, y_tn), (grid(xs_bar[2] + 1.400), y_tn)], 0.560)
    c.wire("metal3", [(x_m4_n, y_bn), (grid(xs_bar[3] + 1.400), y_bn)], 0.560)

    # Vertical M4 risers + direct M5 West exits (inp flies on M5 cleanly OVER inn's M4 riser!)
    for xm4, ya, yb, yp in ((x_m4_p, y_bp, y_tp, y_port_p), (x_m4_n, y_bn, y_tn, y_port_n)):
        via3_pad(c, xm4, ya)
        via3_pad(c, xm4, yb)
        c.wire("metal4", [(xm4, ya), (xm4, yb)], 0.640)
        via4_pad(c, xm4, yp)
        c.wire("metal5", [(x_west_port, yp), (xm4, yp)], 1.800)

    if add_ports:
        c.port("inp", "metal5", x_west_port, y_port_p)
        c.port("inn", "metal5", x_west_port, y_port_n)
        c.port("vcm", "metal3", x_east_vcm,  0.000)
        c.port("vss", "metal2", x_east_vcm,  -dy_top)

    return c, {
        "inp": (x_west_port, y_port_p),
        "inn": (x_west_port, y_port_n),
        "vcm": (x_east_vcm, 0.000),
        "vss": (x_east_vcm, -dy_top),
    }


# ---------------------------------------------------------------------------
# 2. serdes_rx_ctle_pdk (Lean 1.31 mW PDK RC-Degenerated CTLE)
# ---------------------------------------------------------------------------

def _place_mim_unit(c: Cell, cache: PdkCache, dx: float, dy: float, mirror_x: bool = False) -> dict:
    m = cache.device(MIM1, dict(w=9.81, l=9.81, nx=1, ny=1, stack=0, doports=1))
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
    by1 = grid(dy + bb[1])
    by2 = grid(dy + bb[3])
    return {"c1": p1, "c2": p2, "bbox": (bx1, by1, bx2, by2)}


def build_rx_ctle_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build `serdes_rx_ctle_pdk` (ports: inp inn outp outn eq0 eq1 vbias vdd vss)."""
    c = Cell()

    x_w_port = -19.200
    x_e_port = +19.600
    y_vss_s = -14.800
    y_vdd_n = +13.600

    # Global M2 supply rails (South VSS, North VDD)
    c.wire("metal2", [(x_w_port, y_vss_s), (x_e_port, y_vss_s)], 0.800)
    c.wire("metal2", [(x_w_port, y_vdd_n), (x_e_port, y_vdd_n)], 0.800)

    # =========================================================================
    # SOUTH BAND (3D Under-MIM): Xtp/Xtn (16f ABBA) + Xrdeg + EQ0/EQ1 Switches
    # =========================================================================
    dy_tail = -6.200
    cx_tail = 0.000
    m_tail, inf_tail = cache.build_mos(N_LVT, 6.00, 0.50, 16, dy_tail, False)
    c.include(m_tail, dx=cx_tail)

    t_sds = [grid(cx_tail + x) for x in inf_tail["all_sd_xs"]]
    t_vss_xs = t_sds[::2]
    t_sp_xs  = [t_sds[k] for k in (1, 3, 13, 15)]
    t_sn_xs  = [t_sds[k] for k in (5, 7, 9, 11)]

    # Tail VSS straps (uniform 0.32 um M1 matching via1 -> ZERO met1.2 notches!)
    y_tail_vss = -8.300
    for sx in t_vss_xs:
        for vy in (-8.700, -7.500, -6.200, -4.900, -3.700):
            viali_pad(c, sx, vy)
        c.wire("metal1", [(sx, -8.700), (sx, -3.700)], 0.320)
        via1_clean(c, sx, y_tail_vss)
    c.wire("metal2", [(t_vss_xs[0], y_tail_vss), (t_vss_xs[-1], y_tail_vss)], 0.440)
    for sx in (t_vss_xs[0], t_vss_xs[4], t_vss_xs[-1]):
        c.wire("metal2", [(sx, y_vss_s), (sx, y_tail_vss)], 0.440)

    # Tail sp (y = -4.000 M2) & sn (y = -5.400 M2)
    y_tail_sp = -4.000
    y_tail_sn = -5.400
    for dx_s, y_bus in ((t_sp_xs, y_tail_sp), (t_sn_xs, y_tail_sn)):
        for x in dx_s:
            for vy in (-8.600, -7.000, -5.400, -4.000):
                viali_pad(c, x, vy)
            c.wire("metal1", [(x, -8.600), (x, -4.000)], 0.320)
            via1_clean(c, x, y_bus)
        c.wire("metal2", [(dx_s[0], y_bus), (dx_s[-1], y_bus)], 0.440)

    # Tail gates (`vbias`) along South poly bar
    y_tail_g = -9.950
    t_g_pts = tie_mos_gates(
        c, cx_tail, inf_tail, y_bar=-9.600, y_cont=y_tail_g,
        tap_xs=[grid(cx_tail - 5.200), cx_tail, grid(cx_tail + 5.200)],
    )
    c.wire("metal1", [(t_g_pts[0][0], y_tail_g), (t_g_pts[-1][0], y_tail_g)], 0.320)

    # Biased poly dummies flanking Xtp/Xtn -> tied to South guard ring (y = -11.050)
    x_tdum_l = grid(cx_tail + inf_tail["diff_x1"] - 0.140 - 0.250)
    x_tdum_r = grid(cx_tail + inf_tail["diff_x2"] + 0.140 + 0.250)
    y_tail_gr_s = -11.050
    y_tail_gr_n = -1.900
    for xd in (x_tdum_l, x_tdum_r):
        pt = add_tied_poly_dummy(c, xd, inf_tail["poly_y1"], inf_tail["poly_y2"], 0.50, y_cont=y_tail_g)
        c.wire("metal1", [pt, (xd, y_tail_gr_s)], 0.290)

    # Continuous P+ guard ring around Xtp/Xtn
    x_tgr_l = grid(x_tdum_l - 0.850)
    x_tgr_r = grid(x_tdum_r + 0.850)
    draw_tap_h(c, "psubdiff", x_tgr_l, x_tgr_r, y_tail_gr_s, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", x_tgr_l, x_tgr_r, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_tgr_l, y_tail_gr_s, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_tgr_r, y_tail_gr_s, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    via1_clean(c, x_tgr_r, y_tail_gr_s)
    c.wire("metal2", [(x_tgr_r, y_vss_s), (x_tgr_r, y_tail_gr_s)], 0.400)

    # Route `vbias` West on M1 at y = -12.500 (passes cleanly UNDER t_vss_xs[0] M2 drop at -6.64!)
    y_vbias = -12.500
    xv_bias = t_g_pts[0][0]
    via1_clean(c, xv_bias, y_tail_g)
    c.wire("metal2", [(xv_bias, y_tail_g), (xv_bias, y_vbias)], 0.340)
    via1_clean(c, xv_bias, y_vbias)
    c.wire("metal1", [(x_w_port, y_vbias), (xv_bias, y_vbias)], 0.340)

    # Under-MIM West: `Xrdeg` (`res_high_po_2p85 l=4.14, nx=1, guard=1`)
    rdeg_c = cache.device(R_2P85, dict(l=4.14, nx=1, m=1, guard=1))
    rd_r1 = rdeg_c.pins("R1")[0]
    rd_r2 = rdeg_c.pins("R2")[0]
    rd_b  = rdeg_c.pins("B")[0]
    rdeg_c.labels.clear()
    dx_rdeg, dy_rdeg = -13.000, -6.400
    c.include(rdeg_c, dx=dx_rdeg, dy=dy_rdeg)
    p_rd_sp = (grid(dx_rdeg + rd_r1[0]), grid(dy_rdeg + rd_r1[1]))  # (-13.00, -2.425)
    p_rd_sn = (grid(dx_rdeg + rd_r2[0]), grid(dy_rdeg + rd_r2[1]))  # (-13.00, -10.375)
    p_rd_b  = (grid(dx_rdeg + rd_b[0]),  grid(dy_rdeg + rd_b[1]))   # (-13.00, -11.115)

    viali_pad(c, p_rd_b[0], p_rd_b[1])
    c.wire("metal1", [p_rd_b, (x_tgr_l, p_rd_b[1]), (x_tgr_l, y_tail_gr_s)], 0.340)

    for dxv in (-0.800, 0.000, +0.800):
        via1_clean(c, grid(p_rd_sp[0] + dxv), p_rd_sp[1])
        via1_clean(c, grid(p_rd_sn[0] + dxv), p_rd_sn[1])
    c.wire("metal2", [(grid(p_rd_sp[0] - 0.800), p_rd_sp[1]), (grid(p_rd_sp[0] + 0.800), p_rd_sp[1])], 0.440)
    c.wire("metal2", [(grid(p_rd_sn[0] - 0.800), p_rd_sn[1]), (grid(p_rd_sn[0] + 0.800), p_rd_sn[1])], 0.440)
    x_sp_nw = -9.700
    c.wire("metal2", [p_rd_sp, (x_sp_nw, p_rd_sp[1]), (x_sp_nw, y_tail_sp), (t_sp_xs[0], y_tail_sp)], 0.440)
    c.wire("metal2", [p_rd_sn, (x_sp_nw, p_rd_sn[1]), (x_sp_nw, y_tail_sn), (t_sn_xs[0], y_tail_sn)], 0.440)

    # Under-MIM East: EQ0/EQ1 inverters, T-gates, tie FETs (generous gate channel & diff-to-tap margins)
    y_eq_p   = -3.050
    y_eq_vdd = -1.250
    y_eq_n   = -7.150
    y_eq_tie = -9.600

    c.rect("nwell", 9.000, -4.550, 18.800, -0.650)
    draw_tap_h(c, "nsubdiff", 9.250, 18.550, y_eq_vdd, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", x_tgr_r, 18.700, y_tail_gr_s, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", 18.700, y_tail_gr_s, -5.200, half_w=0.180, with_m1=True, m1_w=0.340)
    via1_clean(c, 18.300, y_eq_vdd)
    c.wire("metal2", [(18.300, y_eq_vdd), (18.700, y_eq_vdd), (18.700, y_vdd_n)], 0.440)
    via1_clean(c, 18.200, y_tail_gr_s)
    c.wire("metal2", [(18.200, y_vss_s), (18.200, y_tail_gr_s)], 0.440)

    m_inv_n, inf_inv_n = cache.build_mos(N_STD, 1.00, 0.18, 1, y_eq_n, False)
    m_inv_p, inf_inv_p = cache.build_mos(P_STD, 2.00, 0.18, 1, y_eq_p, True)
    m_swn,   inf_swn   = cache.build_mos(N_STD, 2.00, 0.18, 2, y_eq_n, False)
    m_swp,   inf_swp   = cache.build_mos(P_STD, 2.00, 0.18, 4, y_eq_p, True)
    m_tie,   inf_tie   = cache.build_mos(N_STD, 0.42, 0.50, 1, y_eq_tie, False)

    cx_eq0, cx_sw0, cx_sw1, cx_eq1 = 10.100, 12.400, 15.400, 17.650
    for cx_inv in (cx_eq0, cx_eq1):
        c.include(m_inv_n, dx=cx_inv)
        c.include(m_inv_p, dx=cx_inv)
    for cx_sw in (cx_sw0, cx_sw1):
        c.include(m_swn, dx=cx_sw)
        c.include(m_swp, dx=cx_sw)
        c.include(m_tie, dx=cx_sw)

    # Clean channel Ys: sw_p gate (`eq_b`) = -4.700, sw_n gate (`eq`) = -5.550
    y_eq_gb = -4.700
    y_eq_g  = -5.550
    y_swp_sn, y_swp_cap = -2.550, -3.550
    y_swn_cap, y_swn_sn = -6.550, -7.650

    for idx, cx_inv, cx_sw, sgn in ((0, cx_eq0, cx_sw0, -1), (1, cx_eq1, cx_sw1, +1)):
        # Inverter poly gate: offset polycont outward by 0.25 um to keep generous li.3 margin from drain locali!
        gx_inv = grid(cx_inv + inf_inv_n["g_xs"][0])
        gx_tap = grid(gx_inv + sgn * 0.250)
        c.rect("poly", grid(gx_inv - 0.090), grid(inf_inv_n["diff_y2"] + 0.050),
               grid(gx_inv + 0.090), grid(inf_inv_p["diff_y1"] - 0.050))
        c.rect("poly", grid(min(gx_inv, gx_tap) - 0.090), grid(y_eq_g - 0.170),
               grid(max(gx_inv, gx_tap) + 0.090), grid(y_eq_g + 0.170))
        poly_cont_pad(c, gx_tap, y_eq_g)
        viali_pad(c, gx_tap, y_eq_g)

        x_in_s = grid(cx_inv + (inf_inv_n["s_xs"][0] if sgn < 0 else inf_inv_n["d_xs"][0]))
        x_in_d = grid(cx_inv + (inf_inv_n["d_xs"][0] if sgn < 0 else inf_inv_n["s_xs"][0]))
        locali_v(c, x_in_s, y_tail_gr_s, inf_inv_n["c_y1"] + 0.05)
        locali_v(c, x_in_s, inf_inv_p["c_y2"] - 0.05, y_eq_vdd)

        locali_v(c, x_in_d, inf_inv_n["c_y2"] - 0.05, inf_inv_p["c_y1"] + 0.05)
        viali_pad(c, x_in_d, y_eq_gb)

        # Xsw_p gates (`eq_b`) at y = -4.700
        swp_g = tie_mos_gates(c, cx_sw, inf_swp, y_bar=-4.350, y_cont=y_eq_gb, tap_xs=[cx_sw])[0]
        c.wire("metal1", sorted([(x_in_d, y_eq_gb), swp_g], key=lambda p: p[0]), 0.290)

        # Xsw_n gates (`eq`) at y = -5.550 -> connect to inverter gate tap via M1 (under drain? No: gx_tap is OUTSIDE!)
        # Wait: gx_tap is on the OUTER side of cx_inv, so M1 from gx_tap to cx_sw would pass x_in_d!
        # Instead, lift gx_tap to M2 at y_eq_g (-5.550) -> fly over x_in_d's M1 cleanly to cx_sw -> via1 down to swn_g!
        swn_g = tie_mos_gates(c, cx_sw, inf_swn, y_bar=-5.900, y_cont=y_eq_g, tap_xs=[cx_sw])[0]
        via1_clean(c, gx_tap, y_eq_g)
        via1_clean(c, swn_g[0], y_eq_g)
        c.wire("metal2", sorted([(gx_tap, y_eq_g), swn_g], key=lambda p: p[0]), 0.280)

        # Xtie gate (`eq_b`) at y = -8.750 -> drop M1 straight down from (x_in_d, y_eq_gb) (ZERO stray viali!)
        tie_g = tie_mos_gates(c, cx_sw, inf_tie, y_bar=-9.150, y_cont=-8.750, tap_xs=[cx_sw])[0]
        c.wire("metal1", [(x_in_d, -8.750), (x_in_d, y_eq_gb)], 0.290)
        c.wire("metal1", sorted([(x_in_d, -8.750), tie_g], key=lambda p: p[0]), 0.290)

        swn_sn  = [grid(cx_sw + x) for x in inf_swn["s_xs"]]
        swn_cap = [grid(cx_sw + x) for x in inf_swn["d_xs"]]
        swp_sn  = [grid(cx_sw + x) for x in inf_swp["s_xs"]]
        swp_cap = [grid(cx_sw + x) for x in inf_swp["d_xs"]]

        # Strap `sn`: top of PMOS (y_swp_sn = -2.550) and bottom of NMOS (y_swn_sn = -7.650)
        for sx in swp_sn:
            viali_pad(c, sx, y_swp_sn)
            via1_clean(c, sx, y_swp_sn)
        c.wire("metal2", [(swp_sn[0], y_swp_sn), (swp_sn[-1], y_swp_sn)], 0.320)

        for sx in swn_sn:
            viali_pad(c, sx, y_swn_sn)
            via1_clean(c, sx, y_swn_sn)
        c.wire("metal2", [(swn_sn[0], y_swn_sn), (swn_sn[-1], y_swn_sn)], 0.320)

        # Strap `cap_k`:
        #   - Xsw_p drains at y_swp_cap (-3.550) on M2
        #   - Xsw_n drain (`xc_n = cx_sw`) at y_swn_cap (-6.550) on M2 -> vertical M2 straight up to y_swp_cap!
        #     Wait: does vertical M2 at `cx_sw` from `-6.55` to `-3.55` cross `y_eq_g` (`-5.55`) M2?!
        #     YES! `swn_g` M2 ended at `cx_sw, -5.55`!
        #     FIX: Put `swn_g` tap at `cx_sw + sgn * 0.24`? Even cleaner: route `swp_cap -> swn_cap` vertically
        #     at `x_cap_br = cx_sw - sgn * 0.55` (on the INNER side toward x = 13.90, opposite `gx_tap`!) — ZERO crossing with `swn_g`!
        #   - And extend `xc_n` (`d1`) straight DOWN on **M1** cleanly UNDER `swn_sn (-7.650)` M2 to `y = -8.250`,
        #     then `via1` -> M2 down to `Xtie.D` (`-9.600`) and MIM M4 drop!
        xc_n = swn_cap[0]
        viali_pad(c, xc_n, y_swn_cap)
        via1_clean(c, xc_n, y_swn_cap)
        for sx in swp_cap:
            viali_pad(c, sx, y_swp_cap)
            via1_clean(c, sx, y_swp_cap)
        c.wire("metal2", [(swp_cap[0], y_swp_cap), (swp_cap[-1], y_swp_cap)], 0.320)
        x_cap_br = grid(cx_sw - sgn * 0.650)  # 13.050 for sw0, 14.750 for sw1 (opposite side of gx_tap!)
        c.wire("metal2", [(xc_n, y_swn_cap), (x_cap_br, y_swn_cap), (x_cap_br, y_swp_cap), (swp_cap[0], y_swp_cap)], 0.280)

        # Extend `xc_n` down on M1 under `swn_sn` M2 (-7.650) to `y = -8.250` -> via1 -> M2 to Xtie.D (-9.600)
        viali_pad(c, xc_n, -7.850)
        c.wire("metal1", [(xc_n, -8.250), (xc_n, y_swn_cap)], 0.290)
        via1_clean(c, xc_n, -8.250)

        xt_sp  = grid(cx_sw + inf_tie["s_xs"][0])
        xt_cap = grid(cx_sw + inf_tie["d_xs"][0])
        viali_pad(c, xt_cap, y_eq_tie)
        via1_clean(c, xt_cap, y_eq_tie)
        c.wire("metal2", [(xc_n, -8.250), (xc_n, y_eq_tie), (xt_cap, y_eq_tie)], 0.320)

        # Tie Xtie.S (`sp`) strictly on M1 down to y = -10.300!
        viali_pad(c, xt_sp, y_eq_tie)
        c.wire("metal1", [(xt_sp, -10.300), (xt_sp, y_eq_tie)], 0.290)

    # Join `sn` across Xsw0 & Xsw1 (M2 at y_swp_sn = -2.55 and y_swn_sn = -7.65, vertical M2 bridge at x = 13.900)
    c.wire("metal2", [(grid(cx_sw0 + inf_swp["s_xs"][0]), y_swp_sn), (grid(cx_sw1 + inf_swp["s_xs"][-1]), y_swp_sn)], 0.340)
    c.wire("metal2", [(grid(cx_sw0 + inf_swn["s_xs"][0]), y_swn_sn), (grid(cx_sw1 + inf_swn["s_xs"][-1]), y_swn_sn)], 0.340)
    c.wire("metal2", [(13.900, y_swn_sn), (13.900, y_swp_sn)], 0.340)
    x_sn_e = 9.050
    c.wire("metal2", [(t_sn_xs[-1], y_tail_sn), (x_sn_e, y_tail_sn), (x_sn_e, y_swn_sn),
                      (grid(cx_sw0 + inf_swn["s_xs"][0]), y_swn_sn)], 0.400)

    # Join Xtie0/1 `sp` strictly on M1 along y = -10.300 -> up on M1 at x = 9.050 -> via1 -> tail `sp` (-4.000)
    xt1_sp = grid(cx_sw1 + inf_tie["s_xs"][0])
    c.wire("metal1", [(9.050, -10.300), (xt1_sp, -10.300)], 0.290)
    c.wire("metal1", [(9.050, -10.300), (9.050, y_tail_sp)], 0.290)
    via1_clean(c, 9.050, y_tail_sp)
    c.wire("metal2", [(t_sp_xs[-1], y_tail_sp), (9.050, y_tail_sp)], 0.360)

    # Export `eq0` (East at y = -0.250, M1 across VDD M2) and `eq1` (East at y = -12.000, M2)
    # Tap eq0 at gx_tap_0 = 9.850 (outer left of Xeq0) -> M2 north to -0.250 -> east to 17.80 -> M1 to x_e_port!
    # Check x = 9.850 going north from -5.55 to -0.25: Xsw0_p starts at 11.40 -> 1.55 um clear of y_swp_sn!
    y_eq0_out = -0.250
    y_eq1_out = -12.000
    x_eq0_v = grid(cx_eq0 - 0.250)  # 9.850
    x_eq1_v = grid(cx_eq1 + 0.250)  # 17.900 -> wait: x_eq1_v = 17.900 goes south to -12.000 (clear of x=18.20 vss drop?
    # 18.20 - 17.90 = 0.30 -> tight with M2 width 0.44 + 0.28 = 0.36! Shift vss drop to x = 18.700! Then gap = 0.80 um!)
    # Let's check: we had vss drop at 18.200; move it right onto the East P+ wall at 18.700? Wait: 18.700 has VDD M2 from -1.25 up to +13.60!
    # Below -1.25 (from -14.80 to -11.05), x = 18.700 is 100% FREE on M2!! So move EQ VSS drop to x = 18.700!
    c.wire("metal2", [(x_eq0_v, y_eq_g), (x_eq0_v, y_eq0_out), (17.800, y_eq0_out)], 0.280)
    via1_clean(c, 17.800, y_eq0_out)
    c.wire("metal1", [(17.800, y_eq0_out), (x_e_port, y_eq0_out)], 0.280)

    # Shift EQ1 drop cleanly to x = 16.750? No, x_eq1_v = 17.900 is 0.80 um clear of 18.700 if we move EQ VSS drop to 18.700!
    #Wait: we already drew `c.wire("metal2", [(18.200, y_vss_s), (18.200, y_tail_gr_s)], 0.440)` above;
    # let's route eq1 from x_eq1_v (17.90) -> y = -8.75? No, just use `x_eq1_drop = 17.150` (clear of 18.20 by 1.05 um!).
    # Wait: x_eq1_v is at 17.90, Xeq1 drain is at 17.415, so M2 west to 16.95 at y = -5.550 (ALREADY CONNECTED to swn1_g!) ->
    # drop straight south on M2 at x = 16.750 (between Xsw1=15.40+0.64=16.04 and Xeq1=17.65-0.38=17.27 -> 100% OPEN!) to -12.000 -> East!
    # Check x = 16.750 vs 18.200 vss drop: eq1 goes east at y = -12.000 -> WOULD cross 18.200 M2!
    # Hop eq1 over 18.200 on M1 at y = -12.000! (y = -12.000 is 0.95 um BELOW y_tail_gr_s = -11.050 -> ZERO M1!)
    x_eq1_v = 16.750
    c.wire("metal2", [(x_eq1_v, y_eq_g), (x_eq1_v, y_eq1_out), (17.400, y_eq1_out)], 0.280)
    via1_clean(c, 17.400, y_eq1_out)
    c.wire("metal1", [(17.400, y_eq1_out), (x_e_port, y_eq1_out)], 0.280)

    # 3D-Stacked 3x MIM Caps (pitch 13.000 um -> 1.530 um gap > 1.340 um capm.11!)
    mim_1a = _place_mim_unit(c, cache, dx=-13.000, dy=-6.400, mirror_x=False)
    mim_0  = _place_mim_unit(c, cache, dx=  0.000, dy=-6.400, mirror_x=False)
    mim_1b = _place_mim_unit(c, cache, dx=+13.000, dy=-6.400, mirror_x=False)

    # Join all 3 C1 (top plate = sp) on M4 at y = +0.150 -> drop at t_sp_xs[-1] (+5.545, clear of sn M2!)
    y_mim_sp = +0.150
    for m_info in (mim_1a, mim_0, mim_1b):
        cx1, cy1 = m_info["c1"]
        c.wire("metal4", [(cx1, cy1), (cx1, y_mim_sp)], 0.800)
    c.wire("metal4", [(mim_1a["c1"][0], y_mim_sp), (mim_1b["c1"][0], y_mim_sp)], 0.800)
    x_sp_drop = t_sp_xs[-1]
    via3_pad(c, x_sp_drop, y_mim_sp)
    via2_clean(c, x_sp_drop, y_mim_sp)
    c.wire("metal2", [(x_sp_drop, y_tail_sp), (x_sp_drop, y_mim_sp)], 0.440)

    # Join `cap0` (mim_0.c2 -> South M4 at y = -13.000, 1.695 um SOUTH of mimcap -11.305 -> ZERO capm.11!)
    y_cap0_m4 = -13.000
    c.wire("metal4", [mim_0["c2"], (mim_0["c2"][0], y_cap0_m4), (cx_sw0, y_cap0_m4)], 0.560)
    via3_pad(c, cx_sw0, y_cap0_m4)
    via2_clean(c, cx_sw0, y_cap0_m4)
    c.wire("metal2", [(cx_sw0, y_cap0_m4), (cx_sw0, y_eq_tie)], 0.340)

    # Join `cap1` (mim_1a.c2 + mim_1b.c2 -> South M4 at y = -13.950, 2.645 um SOUTH of mimcap -> ZERO capm.11!)
    y_cap1_m4 = -13.950
    c.wire("metal4", [mim_1a["c2"], (mim_1a["c2"][0], y_cap1_m4), (mim_1b["c2"][0], y_cap1_m4), mim_1b["c2"]], 0.560)
    via3_pad(c, cx_sw1, y_cap1_m4)
    via2_clean(c, cx_sw1, y_cap1_m4)
    c.wire("metal2", [(cx_sw1, y_cap1_m4), (cx_sw1, y_eq_tie)], 0.340)

    # =========================================================================
    # NORTH BAND (100% MIM-FREE!): 2D CC Xip/Xin + Matched Xrp/Xrn
    # =========================================================================
    cx_q_l, cx_q_r = -7.600, -2.400
    dy_q_b, dy_q_t = +3.800, +9.400
    m_in_b, inf_in_b = cache.build_mos(N_LVT, 3.00, 0.15, 4, dy_q_b, False)
    m_in_t, inf_in_t = cache.build_mos(N_LVT, 3.00, 0.15, 4, dy_q_t, False)
    for cx_q in (cx_q_l, cx_q_r):
        c.include(m_in_b, dx=cx_q)
        c.include(m_in_t, dx=cx_q)

    # Continuous P+ guard ring around 2D CC input quad + tied poly dummies
    y_q_gr_s = +0.950
    y_q_gr_n = +12.250
    x_q_gr_l = -10.800
    x_q_gr_r = +0.800
    draw_tap_h(c, "psubdiff", x_q_gr_l, x_q_gr_r, y_q_gr_s, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", x_q_gr_l, x_q_gr_r, y_q_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_q_gr_l, y_q_gr_s, y_q_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", x_q_gr_r, y_q_gr_s, y_q_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    c.wire("metal1", [(x_tgr_l, y_tail_gr_n), (x_tgr_l, y_q_gr_s)], 0.340)
    c.wire("metal1", [(x_q_gr_r, y_tail_gr_n), (x_q_gr_r, y_q_gr_s)], 0.340)

    for inf_r, y_gr_tie, y_dum_c in ((inf_in_b, y_q_gr_s, +1.750), (inf_in_t, y_q_gr_n, +11.450)):
        xd_l = grid(cx_q_l + inf_r["diff_x1"] - 0.140 - 0.075)
        xd_r = grid(cx_q_r + inf_r["diff_x2"] + 0.140 + 0.075)
        pt_l = add_tied_poly_dummy(c, xd_l, inf_r["poly_y1"], inf_r["poly_y2"], 0.15, y_cont=y_dum_c, x_cont=grid(xd_l - 0.12))
        pt_r = add_tied_poly_dummy(c, xd_r, inf_r["poly_y1"], inf_r["poly_y2"], 0.15, y_cont=y_dum_c, x_cont=grid(xd_r + 0.12))
        c.wire("metal1", [pt_l, (pt_l[0], y_gr_tie)], 0.290)
        c.wire("metal1", [pt_r, (pt_r[0], y_gr_tie)], 0.290)

    q_s_pts: dict[str, tuple[float, float]] = {}
    q_d_pts: dict[str, tuple[float, float]] = {}
    q_g_pts: dict[str, tuple[float, float]] = {}
    for qname, cx_q, inf_r, y_s, y_d, y_gb, y_gc in (
        ("SW", cx_q_l, inf_in_b, +2.850, +4.750, +5.600, +5.950),
        ("SE", cx_q_r, inf_in_b, +2.850, +4.750, +5.600, +5.950),
        ("NW", cx_q_l, inf_in_t, +10.350, +8.450, +7.600, +7.250),
        ("NE", cx_q_r, inf_in_t, +10.350, +8.450, +7.600, +7.250),
    ):
        s_xs = [grid(cx_q + x) for x in inf_r["s_xs"]]
        d_xs = [grid(cx_q + x) for x in inf_r["d_xs"]]
        # Use uniform 0.32 um M1 on SD strips (pitch 0.48 -> gap 0.16 >= 0.14 um, ZERO met1.2 notches!)
        for sx in s_xs:
            for vy in (grid(inf_r["dy"] - 1.00), inf_r["dy"], grid(inf_r["dy"] + 1.00)):
                viali_pad(c, sx, vy)
            c.wire("metal1", [(sx, grid(inf_r["dy"] - 1.00)), (sx, grid(inf_r["dy"] + 1.00))], 0.320)
            via1_clean(c, sx, y_s)
        c.wire("metal2", [(s_xs[0], y_s), (s_xs[-1], y_s)], 0.360)
        q_s_pts[qname] = (cx_q, y_s)

        for dx_i in d_xs:
            for vy in (grid(inf_r["dy"] - 1.00), inf_r["dy"], grid(inf_r["dy"] + 1.00)):
                viali_pad(c, dx_i, vy)
            c.wire("metal1", [(dx_i, grid(inf_r["dy"] - 1.00)), (dx_i, grid(inf_r["dy"] + 1.00))], 0.320)
            via1_clean(c, dx_i, y_d)
        c.wire("metal2", [(d_xs[0], y_d), (d_xs[-1], y_d)], 0.360)
        q_d_pts[qname] = (cx_q, y_d)

        gp = tie_mos_gates(c, cx_q, inf_r, y_bar=y_gb, y_cont=y_gc, tap_xs=[cx_q])[0]
        q_g_pts[qname] = gp

    # Symmetric West `inp` / `inn` M3 buses
    y_inp_m3, y_inn_m3 = +7.250, +5.950
    x_se_m2, x_ne_m2 = -2.900, -1.900
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

    c.wire("metal3", [(x_w_port, y_inp_m3), (x_se_m2, y_inp_m3)], 0.380)
    c.wire("metal3", [(x_w_port, y_inn_m3), (x_ne_m2, y_inn_m3)], 0.380)

    # Connect 2D CC Sources (`sp`: NW + SE; `sn`: SW + NE) cleanly down to tail with ZERO crossings!
    #   - `NW (sp)` drops west of quad at x_sp_nw = -9.700 -> y_tail_sp (-4.000)
    #   - `SE (sp)` drops straight down at cx_q_r = -2.400 -> y_tail_sp (-4.000)
    #   - `NE (sn)` drops down the OPEN CENTER LANE x_sn_ctr = -5.000 (between cx_q_l=-7.60 and cx_q_r=-2.40!)
    #     from +10.350 -> y_sn_mid (-2.700) -> west to x_sn_hop (-8.750), meeting `SW (sn)` at (-7.60, -2.700),
    #     then drops on M1 under `sp` M2 (-4.000) into `y_tail_sn` (-5.400)!
    x_sn_ctr = -5.000
    x_sn_hop = -8.750
    y_sn_mid = -2.700

    c.wire("metal2", [q_s_pts["NW"], (x_sp_nw, q_s_pts["NW"][1]), (x_sp_nw, y_tail_sp)], 0.400)
    c.wire("metal2", [q_s_pts["SE"], (cx_q_r, y_tail_sp)], 0.400)

    c.wire("metal2", [(x_sn_ctr, q_s_pts["NE"][1]), q_s_pts["NE"]], 0.380)
    c.wire("metal2", [(x_sn_ctr, y_sn_mid), (x_sn_ctr, q_s_pts["NE"][1])], 0.380)
    c.wire("metal2", [(x_sn_hop, y_sn_mid), (x_sn_ctr, y_sn_mid)], 0.380)
    c.wire("metal2", [q_s_pts["SW"], (cx_q_l, y_sn_mid)], 0.400)
    via1_clean(c, x_sn_hop, y_sn_mid)
    via1_clean(c, x_sn_hop, y_tail_sn)
    c.wire("metal1", [(x_sn_hop, y_tail_sn), (x_sn_hop, y_sn_mid)], 0.360)
    c.wire("metal2", [(x_sn_hop, y_tail_sn), (t_sn_xs[0], y_tail_sn)], 0.400)

    # North-East: Matched Load Resistors `Xrp | Xrn` (`res_high_po_2p85 l=4.14, nx=2, guard=1`)
    rld_c = cache.device(R_2P85, dict(l=4.14, nx=2, m=1, guard=1))
    rld_p1 = rld_c.pins("R1_0")[0]
    rld_p2 = rld_c.pins("R2_0")[0]
    rld_n1 = rld_c.pins("R1_1")[0]
    rld_n2 = rld_c.pins("R2_1")[0]
    rld_b  = rld_c.pins("B")[0]
    rld_c.labels.clear()

    dx_rld, dy_rld = +8.000, +6.800
    c.include(rld_c, dx=dx_rld, dy=dy_rld)
    p_rp_vdd = (grid(dx_rld + rld_p1[0]), grid(dy_rld + rld_p1[1]))
    p_rn_vdd = (grid(dx_rld + rld_n1[0]), grid(dy_rld + rld_n1[1]))
    p_rp_out = (grid(dx_rld + rld_p2[0]), grid(dy_rld + rld_p2[1]))
    p_rn_out = (grid(dx_rld + rld_n2[0]), grid(dy_rld + rld_n2[1]))
    p_rld_b  = (grid(dx_rld + rld_b[0]),  grid(dy_rld + rld_b[1]))

    for pv in (p_rp_vdd, p_rn_vdd):
        for dxv in (-0.800, 0.000, +0.800):
            via1_clean(c, grid(pv[0] + dxv), pv[1])
        c.wire("metal2", [(grid(pv[0] - 0.800), pv[1]), (grid(pv[0] + 0.800), pv[1])], 0.440)
        c.wire("metal2", [pv, (pv[0], y_vdd_n)], 0.520)

    viali_pad(c, p_rld_b[0], p_rld_b[1])
    c.wire("metal1", [p_rld_b, (p_rld_b[0], y_q_gr_s), (x_q_gr_r, y_q_gr_s)], 0.340)

    # Ultra-symmetric `outp` / `outn` M3 East exit + matched drops to Xrp / Xrn!
    y_outp_bus = +6.100
    y_outn_bus = +7.100
    x_op_j = +1.650
    x_on_j = +2.550

    via2_clean(c, *q_d_pts["SW"])
    c.wire("metal3", [q_d_pts["SW"], (x_op_j, q_d_pts["SW"][1]), (x_op_j, y_outp_bus), (x_e_port, y_outp_bus)], 0.400)
    c.wire("metal2", [q_d_pts["NE"], (x_op_j, q_d_pts["NE"][1]), (x_op_j, y_outp_bus)], 0.360)
    via2_clean(c, x_op_j, y_outp_bus)

    via2_clean(c, *q_d_pts["NW"])
    c.wire("metal3", [q_d_pts["NW"], (x_on_j, q_d_pts["NW"][1]), (x_on_j, y_outn_bus), (x_e_port, y_outn_bus)], 0.400)
    c.wire("metal2", [q_d_pts["SE"], (x_on_j, q_d_pts["SE"][1]), (x_on_j, y_outn_bus)], 0.360)
    via2_clean(c, x_on_j, y_outn_bus)

    for p_out, y_bus in ((p_rp_out, y_outp_bus), (p_rn_out, y_outn_bus)):
        for dxv in (-0.800, 0.000, +0.800):
            via1_clean(c, grid(p_out[0] + dxv), p_out[1])
        c.wire("metal2", [(grid(p_out[0] - 0.800), p_out[1]), (grid(p_out[0] + 0.800), p_out[1])], 0.440)
        via2_clean(c, p_out[0], y_bus)
        c.wire("metal2", [p_out, (p_out[0], y_bus)], 0.440)

    if add_ports:
        c.port("inp",   "metal3", x_w_port, y_inp_m3)
        c.port("inn",   "metal3", x_w_port, y_inn_m3)
        c.port("outp",  "metal3", x_e_port, y_outp_bus)
        c.port("outn",  "metal3", x_e_port, y_outn_bus)
        c.port("eq0",   "metal1", x_e_port, y_eq0_out)
        c.port("eq1",   "metal1", x_e_port, y_eq1_out)
        c.port("vbias", "metal1", x_w_port, y_vbias)
        c.port("vdd",   "metal2", x_w_port, y_vdd_n)
        c.port("vss",   "metal2", x_w_port, y_vss_s)

    return c, {
        "inp": (x_w_port, y_inp_m3),
        "inn": (x_w_port, y_inn_m3),
        "outp": (x_e_port, y_outp_bus),
        "outn": (x_e_port, y_outn_bus),
    }


if __name__ == "__main__":
    import json
    work_root = rlc.REPO / "results/layout/rx_cmos_v2/dev_ctle"
    cache = PdkCache(rlc.REPO / "results/layout/rx_cmos_v2/_pdk_cache")
    for name, src_sub, fn in [
        ("serdes_rx_term_pdk", "serdes_rx_term_pdk", build_rx_term_pdk),
        ("serdes_rx_ctle_pdk", "serdes_rx_ctle_pdk", build_rx_ctle_pdk),
    ]:
        w = work_root / name
        w.mkdir(parents=True, exist_ok=True)
        cell, _meta = fn(cache, add_ports=True)
        mag = w / f"{name}.mag"
        ref = w / f"{name}_ref.spice"
        cell.write(mag)
        ports = rlc.generate_rx_ref_spice(src_sub, name, ref)
        rep = rlc.verify_flat_cell(w, name, mag, ref, ports)
        print(f"=== {name} ===", flush=True)
        print(json.dumps({
            k: rep[k] for k in (
                "width_um", "height_um", "area_um2", "aspect_ratio",
                "drc_total", "drc_rules", "floating_poly",
                "lvs_match", "lvs_property_errors", "lvs_disconnected",
                "port_count_match", "exported_ports", "metal_shares",
            )
        }, indent=2), flush=True)
        pc = rep["parasitics"].get("port_caps_fF", {})
        for k in ("inp", "inn", "outp", "outn", "vcm"):
            if k in pc:
                print(f"  CPEX {k:5s}: {pc[k]}", flush=True)
