#!/usr/bin/env python3
"""Physical PDK layout builders for analog/mixed-signal SST blocks:
  1. `sst_slice_unit_pdk` (Tileable N-over-N Differential SST Unit Slice, 8.80 x 25.00 um)
  2. `sst_vdrv_ldo_pdk`   (Compact 1.8 V -> 0.44 V V_drv Sub-Regulator with 3D Under-MIM
                           head-R-consistent res_high_po_1p41, ABBA CC 5T OTA, wide 240/0.15
                           LVT pass FET, and stacked MIM1+MIM2 1.2 pF + 15.3 pF caps)
"""
from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sst_layout_common as slc  # noqa: E402
from sst_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_STD,
    N_LVT,
    P_STD,
    R_2P85,
    R_1P41,
    W_M1,
    W_M2,
    W_M3,
    W_M4,
    grid,
    poly_cont_pad,
    viali_pad,
    via2_clean,
    via3_pad,
    via3_array,
    via4_array,
    via34_pillar,
    locali_v,
    locali_h,
    draw_tap_h,
    draw_tap_v,
    place_stacked_mim,
)

SLICE_PITCH_X = 8.800
SLICE_HALF_X = 4.400
SLICE_Y_PAD_N = -4.960
SLICE_Y_PAD_P = -2.600
SLICE_Y_VSS_PWR = 5.400
SLICE_Y_VDRV = 8.150
SLICE_Y_VSS_DRV = 11.400
SLICE_Y_DIN_P = 14.000
SLICE_Y_DIN_N = 15.000
SLICE_Y_VDD_DRV = 18.800
SLICE_Y_EN_PIN = 19.650


def build_sst_slice_unit(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build tileable N-over-N Differential SST Unit Slice (`sst_slice_unit_pdk`).

    Exact schematic devices (`sst_slice_unit`, default params wpu=3.8, wpd=2.6, lres=3.75):
      - Local driver: Xgpb/Xgnb (sst_nand2 wn=0.65 wp=0.55), Xgp/Xgn (sst_inv wn=1.0 wp=2.0)
      - Power stage:  Xpup/Xpun (nfet_01v8_lvt 3.8/0.15 nf=2), Xpdp/Xpdn (2.6/0.15 nf=1)
      - Output R:     Xrp/Xrn (sky130_fd_pr__res_high_po_2p85 l=3.75, shared guard ring)
    """
    c = Cell()
    hx = SLICE_HALF_X

    # ------------------------------------------------------------------
    # Band 0: Matched high-poly 2.85 um resistors (Xrp left, Xrn right)
    # ------------------------------------------------------------------
    res2 = cache.device(R_2P85, dict(l=3.75, nx=2, m=1, guard=1))
    r1_0 = res2.pins("R1_0")[0]   # (-1.665, +3.780) -> swp
    r2_0 = res2.pins("R2_0")[0]   # (-1.665, -3.780) -> pad_p
    r1_1 = res2.pins("R1_1")[0]   # (+1.665, +3.780) -> swn
    r2_1 = res2.pins("R2_1")[0]   # (+1.665, -3.780) -> pad_n
    res2.labels.clear()
    c.include(res2, dx=0.0, dy=0.0)

    # Continuous pwell across slice pitch for abutment
    c.rect("pwell", -hx, -4.785, +hx, 15.400)

    # Symmetric pad_p (y=-2.600) and pad_n (y=-4.960) M4 horizontal bus stubs (exact [-hx, +hx] pitch)
    # Both vertical M2 stubs from R2_0 / R2_1 are exactly 1.180 um long!
    c.rect("metal4", -hx, grid(SLICE_Y_PAD_P - 0.400), +hx, grid(SLICE_Y_PAD_P + 0.400))
    c.rect("metal4", -hx, grid(SLICE_Y_PAD_N - 0.400), +hx, grid(SLICE_Y_PAD_N + 0.400))

    # R2_0 -> pad_p (M1 -> via1 -> M2 north to -2.600 -> via2 -> via3 -> M4)
    xp0, yp0 = grid(r2_0[0]), grid(r2_0[1])
    c.via1(xp0, yp0)
    c.wire("metal2", [(xp0, yp0), (xp0, SLICE_Y_PAD_P)], 0.440)
    via2_clean(c, xp0, SLICE_Y_PAD_P)
    via3_pad(c, xp0, SLICE_Y_PAD_P)

    # R2_1 -> pad_n (M1 -> via1 -> M2 south to -4.960 -> via2 -> via3 -> M4)
    xp1, yp1 = grid(r2_1[0]), grid(r2_1[1])
    c.via1(xp1, yp1)
    c.wire("metal2", [(xp1, yp1), (xp1, SLICE_Y_PAD_N)], 0.440)
    via2_clean(c, xp1, SLICE_Y_PAD_N)
    via3_pad(c, xp1, SLICE_Y_PAD_N)

    # ------------------------------------------------------------------
    # Band 1: Power LVT NMOS switches + vss / vdrv horizontal rails
    # ------------------------------------------------------------------
    draw_tap_h(c, "psubdiff", -hx, +hx, SLICE_Y_VSS_PWR, half_w=0.220)
    c.rect("metal1", -hx, grid(SLICE_Y_VSS_PWR - 0.250), +hx, grid(SLICE_Y_VSS_PWR + 0.250))
    c.rect("metal3", -hx, grid(SLICE_Y_VSS_PWR - 0.400), +hx, grid(SLICE_Y_VSS_PWR + 0.400))
    for tx in (-3.400, 0.000, +3.400):
        viali_pad(c, tx, SLICE_Y_VSS_PWR)
        c.via1(tx, SLICE_Y_VSS_PWR)
        via2_clean(c, tx, SLICE_Y_VSS_PWR)
        # Tie resistor top guard ring (y=+4.520) up to Band 1 vss tap bar (>=0.48 clear of polyres)
        c.rect("psubdiff", grid(tx - 0.180), 4.500, grid(tx + 0.180), SLICE_Y_VSS_PWR)
        locali_v(c, tx, 4.500, SLICE_Y_VSS_PWR)
        viali_pad(c, tx, 4.520)
        c.wire("metal1", [(tx, 4.520), (tx, SLICE_Y_VSS_PWR)], 0.340)

    # Place Xpup/Xpun (3.8/0.15 nf=2 -> w_f=1.90) & Xpdp/Xpdn (2.6/0.15 nf=1 -> w_f=2.60)
    y_pwr = 7.750
    m_pu, inf_pu = cache.build_mos(N_LVT, 1.90, 0.15, 2, y_pwr, False)
    m_pd, inf_pd = cache.build_mos(N_LVT, 2.60, 0.15, 1, y_pwr, False)

    cx_pup, cx_pdp = -2.600, -0.850
    cx_pdn, cx_pun = +0.850, +2.600
    c.include(m_pu, dx=cx_pup)
    c.include(m_pd, dx=cx_pdp)
    c.include(m_pd, dx=cx_pdn)
    c.include(m_pu, dx=cx_pun)

    # Thick M4 vdrv rail across exact slice pitch [-hx, +hx] at SLICE_Y_VDRV (8.150)
    c.rect("metal4", -hx, grid(SLICE_Y_VDRV - 0.600), +hx, grid(SLICE_Y_VDRV + 0.600))

    # Connect Xpup/Xpun outer diffusions (s_xs) -> vdrv M4 rail at y=8.150
    for cx_u in (cx_pup, cx_pun):
        xs_vdrv = [grid(cx_u + x) for x in inf_pu["s_xs"]]
        for xv in xs_vdrv:
            for vy in (7.450, 8.150):
                viali_pad(c, xv, vy)
            c.wire("metal1", [(xv, 7.450), (xv, 8.150)], 0.280)
            c.via1(xv, SLICE_Y_VDRV)
        c.wire("metal2", [(xs_vdrv[0], SLICE_Y_VDRV), (xs_vdrv[-1], SLICE_Y_VDRV)], 0.560)
        via2_clean(c, cx_u, SLICE_Y_VDRV)
        via3_pad(c, cx_u, SLICE_Y_VDRV)

    # Connect swp (left) and swn (right) -> R1_0 / R1_1 via low-R M2 drops at +-1.665
    y_sw = 6.180
    for sgn, cx_u, cx_d, r1_pt in (
        (-1, cx_pup, cx_pdp, r1_0),
        (+1, cx_pun, cx_pdn, r1_1),
    ):
        x_ud = grid(cx_u + inf_pu["d_xs"][0])   # +-2.600
        # For Xpdp (left), outer diff facing Xpup is s_xs[0] (-0.22 -> -1.070);
        # for Xpdn (right), outer diff facing Xpun is d_xs[0] (+0.22 -> +1.070).
        x_dd = grid(cx_d + (inf_pd["s_xs"][0] if sgn < 0 else inf_pd["d_xs"][0]))  # +-1.070
        x_ds = grid(cx_d + (inf_pd["d_xs"][0] if sgn < 0 else inf_pd["s_xs"][0]))  # +-0.630

        # sw node: drop u_d and d_d to y_sw on locali+M1, then M2 down to R1
        locali_v(c, x_ud, y_sw, inf_pu["c_y1"] + 0.060)
        locali_v(c, x_dd, y_sw, inf_pd["c_y1"] + 0.060)
        viali_pad(c, x_ud, y_sw)
        viali_pad(c, x_dd, y_sw)
        viali_pad(c, x_ud, 6.950)
        viali_pad(c, x_dd, 6.950)
        c.wire("metal1", [(x_ud, y_sw), (x_ud, 6.950)], 0.260)
        c.wire("metal1", [(x_dd, y_sw), (x_dd, 6.950)], 0.260)
        c.wire("metal1", sorted([(x_ud, y_sw), (x_dd, y_sw)], key=lambda p: p[0]), 0.320)

        rx, ry = grid(r1_pt[0]), grid(r1_pt[1])
        c.via1(rx, y_sw)
        c.via1(rx, ry)
        c.wire("metal2", [(rx, ry), (rx, y_sw)], 0.500)

        # pulldown source (x_ds = +-0.630) straight down to Band 1 vss rail at y=5.400
        locali_v(c, x_ds, SLICE_Y_VSS_PWR, inf_pd["c_y1"] + 0.060)
        viali_pad(c, x_ds, 6.950)
        c.wire("metal1", [(x_ds, SLICE_Y_VSS_PWR), (x_ds, 6.950)], 0.280)

    # Power NMOS gates gp (y=9.750) and gn (y=10.350)
    y_gp, y_gn = 9.750, 10.350
    # Xpup poly tie -> tap at (-2.600, 9.750)
    for gx in inf_pu["g_xs"]:
        c.rect("poly", grid(cx_pup + gx - 0.075), 8.700, grid(cx_pup + gx + 0.075), 9.450)
    c.rect("poly", grid(cx_pup + inf_pu["g_xs"][0] - 0.075), 9.300,
           grid(cx_pup + inf_pu["g_xs"][-1] + 0.075), 9.450)
    c.rect("poly", grid(cx_pup - 0.135), 9.300, grid(cx_pup + 0.135), y_gp)
    poly_cont_pad(c, cx_pup, y_gp)
    viali_pad(c, cx_pup, y_gp)
    c.via1(cx_pup, y_gp)

    # Xpdn poly (+0.850) -> tap at (+0.850, 9.750)
    c.rect("poly", grid(cx_pdn - 0.075), 9.050, grid(cx_pdn + 0.075), y_gp)
    poly_cont_pad(c, cx_pdn, y_gp)
    viali_pad(c, cx_pdn, y_gp)
    c.via1(cx_pdn, y_gp)
    c.wire("metal2", [(cx_pup, y_gp), (cx_pdn, y_gp)], 0.280)

    # Xpdp poly (-0.850) -> tap at (-0.850, 10.350)
    c.rect("poly", grid(cx_pdp - 0.075), 9.050, grid(cx_pdp + 0.075), y_gn)
    poly_cont_pad(c, cx_pdp, y_gn)
    viali_pad(c, cx_pdp, y_gn)
    c.via1(cx_pdp, y_gn)

    # Xpun poly tie -> tap at (+2.600, 10.350)
    for gx in inf_pu["g_xs"]:
        c.rect("poly", grid(cx_pun + gx - 0.075), 8.700, grid(cx_pun + gx + 0.075), 9.450)
    c.rect("poly", grid(cx_pun + inf_pu["g_xs"][0] - 0.075), 9.300,
           grid(cx_pun + inf_pu["g_xs"][-1] + 0.075), 9.450)
    c.rect("poly", grid(cx_pun - 0.135), 9.300, grid(cx_pun + 0.135), y_gn)
    poly_cont_pad(c, cx_pun, y_gn)
    viali_pad(c, cx_pun, y_gn)
    c.via1(cx_pun, y_gn)
    c.wire("metal2", [(cx_pdp, y_gn), (cx_pun, y_gn)], 0.280)

    # ------------------------------------------------------------------
    # Band 2: Local CMOS drivers (Xgpb, Xgp left; Xgn, Xgnb right)
    # ------------------------------------------------------------------
    draw_tap_h(c, "psubdiff", -hx, +hx, SLICE_Y_VSS_DRV, half_w=0.175)
    c.rect("metal1", -hx, grid(SLICE_Y_VSS_DRV - 0.220), +hx, grid(SLICE_Y_VSS_DRV + 0.220))
    c.rect("metal3", -hx, grid(SLICE_Y_VSS_DRV - 0.300), +hx, grid(SLICE_Y_VSS_DRV + 0.300))
    for tx in (-3.400, 0.000, +3.400):
        viali_pad(c, tx, SLICE_Y_VSS_DRV)
        c.via1(tx, SLICE_Y_VSS_DRV)
        via2_clean(c, tx, SLICE_Y_VSS_DRV)
    # Strap Band 2 vss down to Band 1 vss on M3 along x=0.000 (clear of vdrv M3 islands at +-2.60)
    c.wire("metal3", [(0.000, SLICE_Y_VSS_PWR), (0.000, SLICE_Y_VSS_DRV)], 0.560)

    # Continuous nwell & VDD rail (inset nsubdiff 0.20 um from nwell edges for diff/tap.10 >= 0.18 um)
    c.rect("nwell", -hx, 15.500, +hx, 19.450)
    draw_tap_h(c, "nsubdiff", grid(-hx + 0.200), grid(+hx - 0.200), SLICE_Y_VDD_DRV, half_w=0.175)
    c.rect("metal1", -hx, grid(SLICE_Y_VDD_DRV - 0.220), +hx, grid(SLICE_Y_VDD_DRV + 0.220))
    c.rect("metal3", -hx, grid(SLICE_Y_VDD_DRV - 0.360), +hx, grid(SLICE_Y_VDD_DRV + 0.360))
    # Keep x=0.000 free on M2 so `en` vertical M2 pin exits cleanly to top perimeter!
    for tx in (-3.400, +3.400):
        viali_pad(c, tx, SLICE_Y_VDD_DRV)
        c.via1(tx, SLICE_Y_VDD_DRV)
        via2_clean(c, tx, SLICE_Y_VDD_DRV)
    viali_pad(c, 0.000, SLICE_Y_VDD_DRV)

    # Build local driver MOS devices:
    #   NAND2: N nf=2 w_f=0.65 (series), P nf=2 w_f=0.55 (parallel: mid=vdd, outer=out)
    #   INV:   N nf=1 w_f=1.00, P nf=1 w_f=2.00
    y_dn_top = 13.000
    y_dp_bot = 16.000
    mn_nd, in_nd = cache.build_mos(N_LVT, 0.65, 0.15, 2, grid(y_dn_top - 0.325), False)
    mp_nd, ip_nd = cache.build_mos(P_STD, 0.55, 0.15, 2, grid(y_dp_bot + 0.275), True)
    mn_iv, in_iv = cache.build_mos(N_LVT, 1.00, 0.15, 1, grid(y_dn_top - 0.500), False)
    mp_iv, ip_iv = cache.build_mos(P_STD, 2.00, 0.15, 1, grid(y_dp_bot + 1.000), True)

    cx_nd_l, cx_iv_l = -3.100, -1.050
    cx_iv_r, cx_nd_r = +1.050, +3.100
    for cx_nd in (cx_nd_l, cx_nd_r):
        c.include(mn_nd, dx=cx_nd)
        c.include(mp_nd, dx=cx_nd)
    for cx_iv in (cx_iv_l, cx_iv_r):
        c.include(mn_iv, dx=cx_iv)
        c.include(mp_iv, dx=cx_iv)

    # Horizontal M3 buses for din_p (y=14.000) and din_n (y=15.000) across exact slice pitch [-hx, +hx]
    c.rect("metal3", -hx, grid(SLICE_Y_DIN_P - W_M3 / 2.0), +hx, grid(SLICE_Y_DIN_P + W_M3 / 2.0))
    c.rect("metal3", -hx, grid(SLICE_Y_DIN_N - W_M3 / 2.0), +hx, grid(SLICE_Y_DIN_N + W_M3 / 2.0))

    # Wire left half (Xgpb -> Xgp -> gp) and right half (Xgnb -> Xgn -> gn) symmetrically!
    y_g_en = 14.500
    y_g_out = 13.500
    en_tap_xs = []

    for sgn, cx_nd, cx_iv, y_din, y_gate_pwr in (
        (-1, cx_nd_l, cx_iv_l, SLICE_Y_DIN_P, y_gp),
        (+1, cx_nd_r, cx_iv_r, SLICE_Y_DIN_N, y_gn),
    ):
        # NAND2 gates: outer finger = en (next to vss), inner finger = din (next to gpb/gnb)!
        # Matches `sst_nand2`: Xna(y, a=din, mid, vss) on top, Xnb(mid, b=en, vss, vss) on bottom!
        gx_en  = grid(cx_nd + (in_nd["g_xs"][0] if sgn < 0 else in_nd["g_xs"][-1]))
        gx_din = grid(cx_nd + (in_nd["g_xs"][-1] if sgn < 0 else in_nd["g_xs"][0]))
        en_tap_xs.append(gx_en)

        # Continuous vertical poly connecting N and P gates for both fingers
        for gx in (gx_din, gx_en):
            c.rect("poly", grid(gx - 0.075), y_dn_top, grid(gx + 0.075), y_dp_bot)

        # Contact din gate at y_din (M3 -> via2 -> via1 -> polycont)
        poly_cont_pad(c, gx_din, y_din)
        viali_pad(c, gx_din, y_din)
        c.via1(gx_din, y_din)
        via2_clean(c, gx_din, y_din)

        # Contact en gate at y_g_en (14.500) -> lift to M2 so en crosses cleanly over NAND2 M1 drop!
        poly_cont_pad(c, gx_en, y_g_en)
        viali_pad(c, gx_en, y_g_en)
        c.via1(gx_en, y_g_en)

        # NAND2 diffusions:
        #   NMOS (series): outer diff (toward edge) = vss, center diff = floating mid, inner diff (toward inv) = out!
        #   PMOS (parallel): center diff = vdd, BOTH outer diffs = out!
        x_n_vss = grid(cx_nd + (in_nd["s_xs"][0] if sgn < 0 else in_nd["s_xs"][-1]))
        x_n_out = grid(cx_nd + (in_nd["s_xs"][-1] if sgn < 0 else in_nd["s_xs"][0]))
        x_p_vdd = grid(cx_nd + ip_nd["d_xs"][0])   # center diffusion
        x_p_out0 = grid(cx_nd + ip_nd["s_xs"][0])
        x_p_out1 = grid(cx_nd + ip_nd["s_xs"][-1])

        # NMOS source -> vss, PMOS center -> vdd
        locali_v(c, x_n_vss, SLICE_Y_VSS_DRV, in_nd["c_y1"] + 0.060)
        locali_v(c, x_p_vdd, ip_nd["c_y2"] - 0.060, SLICE_Y_VDD_DRV)

        # Join PMOS outer drains above PMOS on M1 at y = 17.050, drop through open gap x_nd_drop = +-2.150!
        y_nd_pjoin = 17.050
        for xp_o in (x_p_out0, x_p_out1):
            locali_v(c, xp_o, ip_nd["c_y2"] - 0.060, y_nd_pjoin)
            viali_pad(c, xp_o, y_nd_pjoin)
        x_nd_drop = grid(sgn * 2.150)  # strictly in the open gap between NAND2 (+-2.48) and INV (+-1.42)!
        c.wire("metal1", sorted([(x_p_out0, y_nd_pjoin), (x_p_out1, y_nd_pjoin)], key=lambda p: p[0]), W_M1)
        c.wire("metal1", sorted([(x_p_out1 if sgn < 0 else x_p_out0, y_nd_pjoin), (x_nd_drop, y_nd_pjoin)], key=lambda p: p[0]), W_M1)
        locali_v(c, x_n_out, in_nd["c_y2"] - 0.060, y_g_out)
        viali_pad(c, x_n_out, y_g_out)
        c.wire("metal1", sorted([(x_n_out, y_g_out), (x_nd_drop, y_g_out)], key=lambda p: p[0]), W_M1)
        c.wire("metal1", [(x_nd_drop, y_g_out), (x_nd_drop, y_nd_pjoin)], W_M1)

        # Inverter (Xgp / Xgn): shift polycont outward by 0.32 um (clear of drain locali/M1!) with notch-free poly tie
        gx_iv = grid(cx_iv + in_iv["g_xs"][0])
        gx_iv_tap = grid(cx_iv + (0.320 if sgn > 0 else -0.320))
        c.rect("poly", grid(gx_iv - 0.075), y_dn_top, grid(gx_iv + 0.075), y_dp_bot)
        c.rect("poly", grid(min(gx_iv, gx_iv_tap) - 0.075), grid(y_g_out - 0.170),
               grid(max(gx_iv, gx_iv_tap) + 0.075), grid(y_g_out + 0.170))
        poly_cont_pad(c, gx_iv_tap, y_g_out)
        viali_pad(c, gx_iv_tap, y_g_out)
        c.wire("metal1", sorted([(x_nd_drop, y_g_out), (gx_iv_tap, y_g_out)], key=lambda p: p[0]), W_M1)

        # INV sources (outer side toward NAND2) -> vss/vdd; INV drains (inner side toward x=0) -> gp/gn
        x_iv_s = grid(cx_iv + (in_iv["s_xs"][0] if sgn < 0 else in_iv["d_xs"][0]))
        x_iv_d = grid(cx_iv + (in_iv["d_xs"][0] if sgn < 0 else in_iv["s_xs"][0]))  # +-0.830
        locali_v(c, x_iv_s, SLICE_Y_VSS_DRV, in_iv["c_y1"] + 0.060)
        locali_v(c, x_iv_s, ip_iv["c_y2"] - 0.060, SLICE_Y_VDD_DRV)

        # Join INV N & P drains on locali + M1 -> via1 at y=12.500 (strictly clear of y_g_out=13.500!) -> M2 drop!
        locali_v(c, x_iv_d, in_iv["c_y2"] - 0.060, ip_iv["c_y1"] + 0.060)
        y_iv_tap = 12.500
        viali_pad(c, x_iv_d, y_iv_tap)
        c.via1(x_iv_d, y_iv_tap)
        x_m2_drop = grid(sgn * 1.650)
        c.wire("metal2", sorted([(x_iv_d, y_iv_tap), (x_m2_drop, y_iv_tap)], key=lambda p: p[0]), 0.280)
        c.wire("metal2", [(x_m2_drop, y_gate_pwr), (x_m2_drop, y_iv_tap)], 0.280)

    # Join left & right NAND2 `en` gates on M2 at y = 14.500 (clear of x_nd_drop M1!), exit at top (0.0, 19.650)!
    c.wire("metal2", [(en_tap_xs[0], y_g_en), (en_tap_xs[1], y_g_en)], 0.280)
    c.wire("metal2", [(0.000, y_g_en), (0.000, SLICE_Y_EN_PIN)], 0.320)

    if add_ports:
        # Exact schematic port order: din_p din_n en pad_p pad_n vdrv vdd vss
        c.port("din_p", "metal3", -hx, SLICE_Y_DIN_P)
        c.port("din_n", "metal3", -hx, SLICE_Y_DIN_N)
        c.port("en",    "metal2", 0.000, SLICE_Y_EN_PIN)
        c.port("pad_p", "metal4", +hx, SLICE_Y_PAD_P)
        c.port("pad_n", "metal4", +hx, SLICE_Y_PAD_N)
        c.port("vdrv",  "metal4", -hx, SLICE_Y_VDRV)
        c.port("vdd",   "metal3", -hx, SLICE_Y_VDD_DRV)
        c.port("vss",   "metal3", -hx, SLICE_Y_VSS_PWR)

    return c, {
        "pitch_x": SLICE_PITCH_X,
        "half_x": hx,
        "y_pad_p": SLICE_Y_PAD_P,
        "y_pad_n": SLICE_Y_PAD_N,
        "y_vss_pwr": SLICE_Y_VSS_PWR,
        "y_vdrv": SLICE_Y_VDRV,
        "y_vss_drv": SLICE_Y_VSS_DRV,
        "y_din_p": SLICE_Y_DIN_P,
        "y_din_n": SLICE_Y_DIN_N,
        "y_vdd_drv": SLICE_Y_VDD_DRV,
        "y_en_pin": SLICE_Y_EN_PIN,
    }


# ---------------------------------------------------------------------------
# Compact On-Chip V_drv Sub-Regulator (`sst_vdrv_ldo_pdk`)
# ---------------------------------------------------------------------------

def _strap_mos_guard1(
    c: Cell, prim: Cell, cut_layer: str, dx: float, dy: float, tie_sb: bool = False,
    s_bus_off: float | None = None, d_bus_off: float | None = None,
) -> dict:
    """Place a guard=1, conn_gates=1 1.8V MOS primitive and strap D/S on M2 + G/B pins."""
    p = slc.clone_cell(prim)
    sd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    sd_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects[cut_layer]})
    cut_h = sorted({round(r[3] - r[1], 3) for r in prim.rects[cut_layer]})[0]
    g_pts = sorted({(grid(x + dx), grid(y + dy)) for _, x, y, lbl in prim.labels if lbl.startswith("G")})
    # Body contact on bottom guard ring locali bar
    bot_li = min(prim.rects["locali"], key=lambda r: (r[1] + r[3]) / 2.0)
    bx = grid(prim.rects[cut_layer][0][0] - 0.50 + dx)
    by = grid((bot_li[1] + bot_li[3]) / 2.0 + dy)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    d_xs = sd_xs[::2]
    s_xs = sd_xs[1::2]
    g_ys = sorted({y for _, y in g_pts})
    g_xs = sorted({x for x, _ in g_pts})

    if len(sd_ys) == 1:
        off = min(1.20, max(0.35, cut_h / 2.0 - 0.25))
        d_bus_y = grid(sd_ys[0] + (d_bus_off if d_bus_off is not None else +off))
        s_bus_y = grid(sd_ys[0] + (s_bus_off if s_bus_off is not None else -off))
        for x in d_xs:
            c.via1(x, d_bus_y)
        if len(d_xs) > 1:
            c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.36)
        for x in s_xs:
            c.via1(x, s_bus_y)
        if len(s_xs) > 1:
            c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.36)
        gx, gy = g_xs[0], grid(g_ys[0] + 0.16)
        c.via1(gx, gy)
    else:
        # Place D bus strictly ABOVE top guard ring and S bus strictly BELOW bottom guard ring!
        d_bus_y = grid(max(g_ys) + 1.45)
        s_bus_y = grid(by - 1.45)
        vo_list = (-1.6, 0.0, +1.6) if cut_h >= 6.0 else (0.0,)
        for x in d_xs:
            for y0 in sd_ys:
                for vo in vo_list:
                    c.via1(x, grid(y0 + vo))
            c.wire("metal2", [(x, grid(sd_ys[0] + vo_list[0])), (x, d_bus_y)], 0.26)
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 1.00)
        for x in s_xs:
            for y0 in sd_ys:
                for vo in vo_list:
                    c.via1(x, grid(y0 + vo))
            c.wire("metal2", [(x, s_bus_y), (x, grid(sd_ys[-1] + vo_list[-1]))], 0.26)
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 1.00)
        gx_m1 = grid(min(sd_xs) - 1.15)
        for gy in g_ys:
            c.wire("metal1", [(gx_m1, gy), (g_xs[0], gy)], 0.18)
        c.wire("metal1", [(gx_m1, g_ys[0]), (gx_m1, g_ys[-1])], 0.24)
        gx, gy = gx_m1, grid((g_ys[0] + g_ys[-1]) / 2.0)
        c.via1(gx, gy)

    c.body_contact(bx, by)
    if tie_sb:
        c.rect("metal2", grid(min(bx, s_xs[0]) - 0.16), grid(min(by, s_bus_y) - 0.16),
               grid(max(bx, s_xs[0]) + 0.16), grid(max(by, s_bus_y) + 0.16))

    return {
        "D": (d_xs[0], d_bus_y),
        "D_right": (d_xs[-1], d_bus_y),
        "S": (s_xs[0], s_bus_y),
        "S_right": (s_xs[-1], s_bus_y),
        "G": (gx, gy),
        "B": (bx, by),
        "d_xs": d_xs,
        "s_xs": s_xs,
        "sd_ys": sd_ys,
    }


def _place_res_1p41(c: Cell, cache: PdkCache, length: float, dx: float, dy: float) -> dict:
    p = cache.device(R_1P41, dict(l=length, nx=1, m=1, guard=1))
    r1 = p.pins("R1")[0]
    r2 = p.pins("R2")[0]
    b = p.pins("B")[0]
    p.labels.clear()
    dx, dy = grid(dx), grid(dy)
    c.include(p, dx=dx, dy=dy)
    p1 = (grid(r1[0] + dx), grid(r1[1] + dy))
    p2 = (grid(r2[0] + dx), grid(r2[1] + dy))
    pb = (grid(b[0] + dx), grid(b[1] + dy))
    c.via1(*p1)
    c.via1(*p2)
    c.body_contact(*pb)
    return {"R1": p1, "R2": p2, "B": pb}


def build_sst_vdrv_ldo(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build Compact 1.8 V -> 0.44 V V_drv LDO (`sst_vdrv_ldo_pdk`).

    Floorplan (~98 x 92 um = ~9,000 um^2):
      - West Bay (x in [0..61], y in [0..90]):
          * 6 x 24.8x24.8 um stacked MIM1+MIM2 bypass bank (nx=2, ny=3 -> 15.3 pF on M3-M4-M5)
          * 3D Under-MIM (strictly poly/li/M1/M2 below M3!): all 4 head-R-consistent
            single-bar `res_high_po_1p41` resistors: Xrbias (l=80), Xrtop (l=63),
            Xrbot (l=37), Xrbleed (l=38) — zero extra area, 0.00% head-R error!
      - East Column (x in [65..97], y in [0..90]):
          * South (y in [2..23]):   Xcg1/Xcg2 (17x17 um stacked MIM1+MIM2, 1.2 pF)
          * Middle (y in [27..63]): MIM-free Analog OTA & Bias:
              - ABBA common-centroid NMOS mirror Xm1/Xm2 (w=16 l=0.5 nf=4 -> 2x 4.0x2 each)
              - ABBA common-centroid PMOS diff pair Xref/Xfb (w=48 l=0.35 nf=8 -> 2x 6.0x4 each)
              - PMOS tail Xtail (40/0.35 nf=8) + diode bias Xbp_ref (20/0.35 nf=4)
          * North (y in [67..89]):  Wide LVT NMOS pass device Xpass (240/0.15 nf=32 = 7.5x16 m=2)
              with heavy M4+M5 `vdd` and `vdrv` plates feeding East perimeter `vdrv` port!
    """
    c = Cell()

    # ------------------------------------------------------------------
    # Zone 1: West Bay — 6x 24.8x24.8 Stacked MIM1+MIM2 (nx=2, ny=3)
    # ------------------------------------------------------------------
    mim_cd = place_stacked_mim(
        c, cache, side=24.8, cols=2, rows=3,
        dx_c=31.0, dy_c=45.0,
        a_off=1.90, b3_off=1.90, b5_off=2.60,
        pillar_side="west", pillar_dx=4.60,
    )
    # mim_cd bbox is roughly x in [1.7..60.4], y in [4.8..85.2]
    # mim_cd["a"] (M4 = vdrv) at y = ya (~87.1), mim_cd["b"] (M3+M5 = vss) at west pillar x ~ -1.7

    # 3D Under-MIM Resistors (strictly <= M2, well inside x in [6..52], y in [2..88]):
    # Place Xrbias (l=80), Xrtop (l=63), Xrbot (l=37), Xrbleed (l=38) side-by-side vertically!
    # Each res_high_po_1p41 has pwell half-width 1.535 um -> pitch 6.0 um gives ~3.0 um clear gap!
    r_bias = _place_res_1p41(c, cache, 80.0, dx=10.0, dy=45.0)    # y in [2.1..87.9]
    r_top  = _place_res_1p41(c, cache, 63.0, dx=18.0, dy=45.0)    # y in [10.6..79.4]
    r_bot  = _place_res_1p41(c, cache, 37.0, dx=26.0, dy=38.0)    # y in [16.6..59.4]
    r_bld  = _place_res_1p41(c, cache, 38.0, dx=34.0, dy=45.0)    # y in [23.1..66.9]

    # Connect all resistor bodies + bottom terminals (vss) onto a clean Under-MIM M2 VSS spine at y=1.20
    y_vss_bot = 1.200
    x_vss_w, y_vss_w = mim_cd["b"]
    c.wire("metal2", [(min(-8.0, x_vss_w), y_vss_bot), (96.0, y_vss_bot)], 0.800)
    for rinfo in (r_bias, r_top, r_bot, r_bld):
        bx, by = rinfo["B"]
        # Drop resistor body B (shifted left by 1.2 um to avoid R2 pin!) down to y_vss_bot
        xb_drop = grid(bx - 1.200)
        c.wire("metal2", [(bx, by), (xb_drop, by), (xb_drop, y_vss_bot)], 0.360)
    for rinfo in (r_bias, r_bot, r_bld):
        # R2 (bottom terminal) ties straight to vss!
        x2, y2 = rinfo["R2"]
        c.wire("metal2", [(x2, y2), (x2, y_vss_bot)], 0.360)

    # Tie MIM bypass outer plates (vss) west pillar down to y_vss_bot via M3 -> via2 -> M2
    c.wire("metal3", [(x_vss_w, y_vss_bot), (x_vss_w, y_vss_w)], 1.200)
    for vy in (y_vss_bot, 22.0, 68.0):
        via2_clean(c, x_vss_w, vy)
    c.wire("metal2", [(x_vss_w, y_vss_bot), (x_vss_w, 68.0)], 0.800)

    # Divider vref node: r_top.R2 (18.0, 11.595) -> r_bot.R1 (26.0, 58.405) -> route cleanly on M2 to OTA!
    x_vref_bus = 22.000  # open vertical lane between r_top (18.0) and r_bot (26.0)
    c.wire("metal2", [r_top["R2"], (x_vref_bus, r_top["R2"][1]), (x_vref_bus, r_bot["R1"][1]), r_bot["R1"]], 0.360)

    # ------------------------------------------------------------------
    # Zone 2: East-South — Compensation Cap Xcg1/Xcg2 (17x17 Stacked MIM1+MIM2)
    # ------------------------------------------------------------------
    mim_cg = place_stacked_mim(
        c, cache, side=17.0, cols=1, rows=1,
        dx_c=77.0, dy_c=13.5,
        a_off=1.60, b3_off=1.60, b5_off=2.20,
        pillar_side="east", pillar_dx=3.20,
    )
    # Tie mim_cg outer plates (vss) down to y_vss_bot
    xcg_b, ycg_b = mim_cg["b"]
    c.wire("metal3", [(xcg_b, y_vss_bot), (xcg_b, ycg_b)], 1.000)
    via2_clean(c, xcg_b, y_vss_bot)
    c.wire("metal2", [(xcg_b, y_vss_bot), (96.0, y_vss_bot)], 0.800)

    # ------------------------------------------------------------------
    # Zone 3: East-Middle — MIM-Free Analog 5T PMOS-Input OTA + Bias
    # ------------------------------------------------------------------
    # Sub-row 3A (y = 31.0): ABBA Common-Centroid NMOS Current Mirror Xm1/Xm2 (each w=16 l=0.50 nf=4)
    # Split into 4 segments of w_f=4.0 l=0.50 nf=2 (each w=8.0): A(m1) B(m2) B(m2) A(m1)
    p_nmir = cache.device(N_STD, dict(w=4.0, l=0.50, nf=2, m=1, conn_gates=1, guard=1))
    # Place at x = 67.5, 74.5, 81.5, 88.5 (spacing ~7.0 um -> generous clearance!)
    m1_l = _strap_mos_guard1(c, p_nmir, "ndiffc", 67.5, 31.0, tie_sb=True)
    m2_l = _strap_mos_guard1(c, p_nmir, "ndiffc", 74.5, 31.0, tie_sb=True)
    m2_r = _strap_mos_guard1(c, p_nmir, "ndiffc", 81.5, 31.0, tie_sb=True)
    m1_r = _strap_mos_guard1(c, p_nmir, "ndiffc", 88.5, 31.0, tie_sb=True)

    # Shared mirror VSS rail along bottom of Xm1/Xm2 -> tie right to East VSS spine
    y_mir_s = m1_l["S"][1]
    c.wire("metal2", [(m1_l["B"][0], y_mir_s), (xcg_b, y_mir_s)], 0.560)
    via2_clean(c, xcg_b, y_mir_s)
    c.wire("metal3", [(xcg_b, ycg_b), (xcg_b, y_mir_s)], 0.800)

    # Shared mirror gate (`nd`) across all 4 segments + diode-connect to m1_l.D and m1_r.D!
    y_nd_g = 36.050
    y_vg_bus = 37.050
    x_nd_min = min(m1_l["D"][0], m1_l["G"][0])
    for seg in (m1_l, m2_l, m2_r, m1_r):
        c.wire("metal2", [seg["G"], (seg["G"][0], y_nd_g)], 0.320)
    c.wire("metal2", [(x_nd_min, y_nd_g), (m1_r["G"][0], y_nd_g)], 0.400)
    # Connect m1_l.D_right and m1_r.D_right up to y_nd_g (nd node, >= 0.8 um clear of left-side G straps!)
    for seg in (m1_l, m1_r):
        c.wire("metal2", [seg["D_right"], (seg["D_right"][0], y_nd_g)], 0.340)
    # Connect m2_l.D and m2_r.D up to y_vg_bus (vgate node, via M3 bridge over y_nd_g!)
    for seg in (m2_l, m2_r):
        dx_m2, dy_m2 = seg["D"]
        via2_clean(c, dx_m2, dy_m2)
        via2_clean(c, dx_m2, y_vg_bus)
        c.wire("metal3", [(dx_m2, dy_m2), (dx_m2, y_vg_bus)], 0.400)
    c.wire("metal2", [(m2_l["D"][0], y_vg_bus), (m2_r["D"][0], y_vg_bus)], 0.360)

    # Connect vgate (m2_l.D at y_vg_bus) down to Xcg1/Xcg2 middle plate (M4 at mim_cg["a"])!
    x_vg_drop = 64.200
    c.wire("metal2", [(x_vg_drop, y_vg_bus), (m2_l["D"][0], y_vg_bus)], 0.360)
    via2_clean(c, x_vg_drop, y_vg_bus)
    via3_pad(c, x_vg_drop, y_vg_bus)
    c.wire("metal4", [(x_vg_drop, mim_cg["a"][1]), (x_vg_drop, y_vg_bus)], 0.600)
    c.wire("metal4", [(x_vg_drop, mim_cg["a"][1]), mim_cg["a"]], 0.600)

    # Sub-row 3B (y = 44.5): ABBA Common-Centroid PMOS Diff Pair Xref/Xfb (each w=48 l=0.35 nf=8)
    # Split into 4 segments of w_f=6.0 l=0.35 nf=4 (each w=24.0): A(ref) B(fb) B(fb) A(ref)
    p_pdp = cache.device(P_STD, dict(w=6.0, l=0.35, nf=4, m=1, conn_gates=1, guard=1))
    ref_l = _strap_mos_guard1(c, p_pdp, "pdiffc", 67.5, 44.5, tie_sb=False)
    fb_l  = _strap_mos_guard1(c, p_pdp, "pdiffc", 74.5, 44.5, tie_sb=False)
    fb_r  = _strap_mos_guard1(c, p_pdp, "pdiffc", 81.5, 44.5, tie_sb=False)
    ref_r = _strap_mos_guard1(c, p_pdp, "pdiffc", 88.5, 44.5, tie_sb=False)

    # Common `tail` bus across all 4 diff-pair sources (S)
    y_tail_s = ref_l["S"][1]
    c.wire("metal2", [(ref_l["S"][0], y_tail_s), (ref_r["S_right"][0], y_tail_s)], 0.440)
    # Common N-well body tie (`vdd`) along bottom guard ring of diff pair
    y_dp_b = ref_l["B"][1]
    c.wire("metal2", [(ref_l["B"][0], y_dp_b), (ref_r["B"][0], y_dp_b)], 0.400)

    # Connect diff-pair drains down to `nd` (y_nd_g) and `vgate` (y_vg_bus) via M3 vertical drops!
    for seg in (ref_l, ref_r):
        dx_p, dy_p = seg["D_right"]
        via2_clean(c, dx_p, dy_p)
        via2_clean(c, dx_p, y_nd_g)
        c.wire("metal3", [(dx_p, y_nd_g), (dx_p, dy_p)], 0.400)
    # Ensure y_nd_g M2 spans all the way from x_nd_min to ref_r["D_right"][0] (W=0.40 matches via2_clean!)
    c.wire("metal2", [(x_nd_min, y_nd_g), (ref_r["D_right"][0], y_nd_g)], 0.400)

    for seg in (fb_l, fb_r):
        dx_p, dy_p = seg["D_right"]
        via2_clean(c, dx_p, dy_p)
        via2_clean(c, dx_p, y_vg_bus)
        c.wire("metal3", [(dx_p, y_vg_bus), (dx_p, dy_p)], 0.400)
    # Ensure y_vg_bus M2 spans all the way to fb_r["D_right"][0]!
    c.wire("metal2", [(x_vg_drop, y_vg_bus), (fb_r["D_right"][0], y_vg_bus)], 0.360)

    # Connect ABBA gates:
    #   vref -> ref_l.G and ref_r.G on M2 at y = 51.000
    #   vdrv -> fb_l.G and fb_r.G on M2 at y = 51.900
    y_g_ref = 51.000
    y_g_fb  = 51.900
    for seg in (ref_l, ref_r):
        c.wire("metal2", [seg["G"], (seg["G"][0], y_g_ref)], 0.320)
    c.wire("metal2", [(ref_l["G"][0], y_g_ref), (ref_r["G"][0], y_g_ref)], 0.340)
    # Route vref from under-MIM x_vref_bus (22.0, 58.4) -> (22.0, y_g_ref) -> ref_l.G on M2!
    c.wire("metal2", [(x_vref_bus, y_g_ref), (ref_l["G"][0], y_g_ref)], 0.340)

    for seg in (fb_l, fb_r):
        gx, gy = seg["G"]
        # Hop over y_g_ref on M3!
        via2_clean(c, gx, gy)
        via2_clean(c, gx, y_g_fb)
        c.wire("metal3", [(gx, gy), (gx, y_g_fb)], 0.400)
    c.wire("metal2", [(fb_l["G"][0], y_g_fb), (fb_r["G"][0], y_g_fb)], 0.340)

    # Sub-row 3C (y = 58.0): PMOS Current Source Xtail (40/0.35 nf=8) + Diode Xbp_ref (20/0.35 nf=4)
    p_tail = cache.device(P_STD, dict(w=5.0, l=0.35, nf=8, m=1, conn_gates=1, guard=1))
    p_bref = cache.device(P_STD, dict(w=5.0, l=0.35, nf=4, m=1, conn_gates=1, guard=1))
    u_bref = _strap_mos_guard1(c, p_bref, "pdiffc", 69.0, 58.0, tie_sb=True)
    u_tail = _strap_mos_guard1(c, p_tail, "pdiffc", 82.0, 58.0, tie_sb=True)

    # Tie Xtail.D -> diff-pair tail bus (y_tail_s) via M3 at x = 86.0 (or tail D_right)
    xt_d, yt_d = u_tail["D_right"]
    via2_clean(c, xt_d, yt_d)
    via2_clean(c, xt_d, y_tail_s)
    c.wire("metal3", [(xt_d, y_tail_s), (xt_d, yt_d)], 0.440)

    # Tie Xbp_ref.G, Xtail.G, Xbp_ref.D (`vbp`) together on M2 at y = 63.300 -> route west to r_bias.R1!
    y_vbp = 63.300
    c.wire("metal2", [u_bref["G"], (u_bref["G"][0], y_vbp), (u_tail["G"][0], y_vbp), u_tail["G"]], 0.340)
    c.wire("metal2", [u_bref["D"], (u_bref["D"][0], y_vbp)], 0.340)
    # Route vbp west on M2 at y = 89.200 (above r_top/r_bot/r_bld, right next to r_bias.R1 at (10.0, 86.905)!)
    # Or horizontally at y = 63.300? Wait: r_bias is at x=10, r_top at 18, r_bot at 26, r_bld at 34!
    # r_top/r_bot/r_bld ONLY use poly/li/M1 (via1 only at their R1/R2 ends)!
    # Check y of R1/R2 pins:
    #   r_bias.R1 = (10, 86.905)
    #   r_top.R1  = (18, 78.405)  (vbg!)
    #   r_bot.R1  = (26, 58.405)  (vref)
    #   r_bld.R1  = (34, 65.905)  (vdrv)
    # So y = 63.300 is COMPLETELY OPEN across x in [10..69] on M2 (zero via1 at y=63.300!)!
    # Let's check x_vref_bus (x=22.0): x_vref_bus runs y in [11.6..58.4] -> stops at 58.4, 4.9 um below 63.300!
    # So y = 63.300 runs unobstructed straight from u_bref.G all the way to x = 10.0 -> up to r_bias.R1!
    c.wire("metal2", [(r_bias["R1"][0], y_vbp), (u_bref["G"][0], y_vbp)], 0.360)
    c.wire("metal2", [(r_bias["R1"][0], y_vbp), r_bias["R1"]], 0.360)

    # Connect VDD across Xbp_ref.S/B, Xtail.S/B, and diff-pair B -> East VDD vertical M3 spine at x = 93.200
    x_vdd_e = 93.200
    c.wire("metal2", [(u_bref["S"][0], u_bref["S"][1]), (x_vdd_e, u_bref["S"][1])], 0.600)
    c.wire("metal2", [(ref_r["B"][0], y_dp_b), (x_vdd_e, y_dp_b)], 0.500)
    via2_clean(c, x_vdd_e, y_dp_b)
    via2_clean(c, x_vdd_e, u_bref["S"][1])

    # ------------------------------------------------------------------
    # Zone 4: East-North — Wide LVT NMOS Pass FET Xpass (240/0.15 nf=32 = 7.5x16 m=2)
    # ------------------------------------------------------------------
    p_pass = cache.device(N_LVT, dict(w=7.5, l=0.15, nf=16, m=2, conn_gates=1, guard=1))
    # Centered at (80.0, 77.5) -> bbox x in [75.3..84.7], y in [68.4..86.6]
    u_pass = _strap_mos_guard1(c, p_pass, "ndiffc", 80.0, 77.5, tie_sb=False)
    # Note: in u_pass:
    #   D (d_xs = even diffusions) = vdd (north bus at d_bus_y ~ 87.3)
    #   S (s_xs = odd diffusions)  = vdrv (south bus at s_bus_y ~ 67.3)
    #   G = vgate (west side at x ~ 74.2, y ~ 77.5)
    #   B = vss (bottom guard ring at y ~ 68.7)

    # Connect u_pass.B (vss) to East VSS M3 spine at x = xcg_b (~91.7? wait check xcg_b!)
    # Let's place a clean dedicated East VSS spine at x = 95.800 (clear of x_vdd_e = 93.200!)
    x_vss_e = 95.800
    c.wire("metal2", [(xcg_b, y_vss_bot), (x_vss_e, y_vss_bot)], 0.800)
    via2_clean(c, x_vss_e, y_vss_bot)
    c.wire("metal3", [(x_vss_e, y_vss_bot), (x_vss_e, u_pass["B"][1])], 0.800)
    via2_clean(c, x_vss_e, u_pass["B"][1])
    # Wait: u_pass["B"] is at x ~ 75.5, y ~ 68.7 -> route right on M2 at y = 66.200?
    # Better: connect u_pass["B"] west to x = 64.2? No, connect u_pass["B"] at y = 68.7?
    # Wait: u_pass["S"] bus is at y = s_bus_y ~ 67.3, and u_pass["B"] is at y ~ 68.7 (above s_bus_y!).
    # So u_pass["B"] can go WEST to mim_cd's bottom/west VSS, OR lift to M3 at u_pass["B"] and go east!
    # Wait: at u_pass["B"] (x~75.5, y~68.7), vertical M2 bars of Xpass S/D sit over x in [75.8..84.2].
    # So going WEST from u_pass["B"] (75.5 -> 62.5) is 100% clear! Then drop down on M2 at x=62.5 to y_vss_bot!
    # Route u_pass.B (vss) west on M2 to open vertical M3 corridor x_vss_mid = 62.200 -> M3 south to y_vss_bot!
    # (Strictly M3 vertically -> ZERO crossing with horizontal M2 vref=51.0, vbp=63.3, r_bld=65.9!)
    x_vss_mid = 62.200
    c.wire("metal2", [(x_vss_mid, u_pass["B"][1]), u_pass["B"]], 0.440)
    via2_clean(c, x_vss_mid, u_pass["B"][1])
    via2_clean(c, x_vss_mid, y_vss_bot)
    c.wire("metal3", [(x_vss_mid, y_vss_bot), (x_vss_mid, u_pass["B"][1])], 0.600)

    # Connect u_pass.G (vgate) to x_vg_drop (64.200) on M4 (continuing straight up from mim_cg/y_vg_bus M4!)
    # Strictly M4 vertically -> ZERO crossing with horizontal M2 vref, vbp, r_bld!
    c.wire("metal4", [(x_vg_drop, y_vg_bus), (x_vg_drop, u_pass["G"][1])], 0.600)
    via3_pad(c, x_vg_drop, u_pass["G"][1])
    via2_clean(c, x_vg_drop, u_pass["G"][1])
    c.wire("metal2", [(x_vg_drop, u_pass["G"][1]), u_pass["G"]], 0.400)

    # Heavy M3/M4 VDD plate over u_pass.D (top, y = u_pass["D"][1]) -> connect to x_vdd_e & East perimeter!
    y_vdd_top = grid(u_pass["D"][1])
    c.wire("metal2", [(u_pass["D"][0], y_vdd_top), (x_vdd_e, y_vdd_top)], 1.200)
    c.wire("metal3", [(u_pass["D"][0], y_vdd_top), (x_vdd_e, y_vdd_top)], 1.200)
    for vx in (76.5, 79.0, 81.5, 84.0, x_vdd_e):
        via2_clean(c, vx, y_vdd_top)
    c.wire("metal3", [(x_vdd_e, y_dp_b), (x_vdd_e, y_vdd_top)], 1.000)
    via3_array(c, 81.0, y_vdd_top, nx=4, ny=2)
    c.wire("metal4", [(76.0, y_vdd_top), (96.5, y_vdd_top)], 1.600)

    # Heavy M3/M4/M5 VDRV trunk:
    #   Joins: (1) u_pass.S (s_bus_y ~ 67.25), (2) mim_cd["a"] (M4 at ya ~ 87.1),
    #          (3) fb_l/fb_r gates (y_g_fb = 51.900), (4) r_bld.R1 (34.0, 65.905),
    #          (5) East perimeter `vdrv` port at (96.5, y_vdrv_s)!
    y_vdrv_s = grid(u_pass["S"][1])
    c.wire("metal3", [(66.0, y_vdrv_s), (91.0, y_vdrv_s)], 1.400)
    for vx in (76.5, 79.0, 81.5, 84.0):
        via2_clean(c, vx, y_vdrv_s)
    via3_array(c, 80.0, y_vdrv_s, nx=4, ny=2)
    c.wire("metal4", [(66.0, y_vdrv_s), (96.5, y_vdrv_s)], 1.600)

    # Connect vdrv M4 bus (66.0, y_vdrv_s) north on M4 to mim_cd["a"] (y = mim_cd["ya"] ~ 87.1)
    c.wire("metal4", [(66.0, y_vdrv_s), (66.0, mim_cd["ya"]), mim_cd["a"]], 1.600)

    # Connect vdrv Kelvin sense down to OTA fb gates (y_g_fb = 51.900) on M3 at x = 66.0
    # (Strictly M3 vertically -> ZERO crossing with M2 vbp=63.3 or r_bld=65.9!)
    via3_pad(c, 66.0, y_vdrv_s)
    c.wire("metal3", [(66.0, y_g_fb), (66.0, y_vdrv_s)], 0.440)
    via2_clean(c, 66.0, y_g_fb)
    c.wire("metal2", [(66.0, y_g_fb), (fb_l["G"][0], y_g_fb)], 0.360)

    # Connect r_bld.R1 (34.0, 65.905) straight east on M2 to (66.0, y_bld) -> up M2 to (66.0, y_vdrv_s) -> via2!
    # (x_vss_mid=62.2 is on M3, x_vg_drop=64.2 is on M4 -> M2 is 100% unobstructed!)
    y_bld = r_bld["R1"][1]
    c.wire("metal2", [r_bld["R1"], (66.0, y_bld), (66.0, y_vdrv_s)], 0.360)
    via2_clean(c, 66.0, y_vdrv_s)

    # Export `vbg` from r_top.R1 (18.0, 78.405) cleanly north to y=89.500 (strictly above r_bias.R1 at 86.9!)
    # and west to (-4.5, 89.500) on M2 -> zero crossing with r_bias!
    y_vbg = 89.500
    c.wire("metal2", [(-4.5, y_vbg), (r_top["R1"][0], y_vbg), r_top["R1"]], 0.440)

    # Add M5 strap over East vdrv port + East VDD port for ultra-low resistance
    via4_array(c, 92.0, y_vdrv_s, nx=2, ny=1)
    c.wire("metal5", [(89.5, y_vdrv_s), (96.5, y_vdrv_s)], 2.200)

    if add_ports:
        # Exact schematic port order: vbg vdrv vdd vss
        c.port("vbg",  "metal2", -4.5,  y_vbg)
        c.port("vdrv", "metal4", 96.5,  y_vdrv_s)
        c.port("vdd",  "metal4", 96.5,  y_vdd_top)
        c.port("vss",  "metal2", 96.0,  y_vss_bot)

    return c, {
        "vbg":  (-4.5, y_vbg),
        "vdrv": (96.5, y_vdrv_s),
        "vdd":  (96.5, y_vdd_top),
        "vss":  (96.0, y_vss_bot),
    }


if __name__ == "__main__":
    import json
    work_root = slc.REPO / "results/layout/tx_sst_v4/test_analog"
    cache = PdkCache(work_root / "_cache")
    for name, src_sub, fn in [
        ("sst_slice_unit_pdk", "sst_slice_unit", build_sst_slice_unit),
        ("sst_vdrv_ldo_pdk",   "sst_vdrv_ldo",   build_sst_vdrv_ldo),
    ]:
        w = work_root / name
        w.mkdir(parents=True, exist_ok=True)
        cell, meta = fn(cache, add_ports=True)
        mag = w / f"{name}.mag"
        ref = w / f"{name}_ref.spice"
        cell.write(mag)
        ports = slc.generate_ref_spice(src_sub, name, ref)
        rep = slc.verify_flat_cell(w, name, mag, ref, ports)
        print(f"=== {name} ===")
        print(json.dumps({k: v for k, v in rep.items() if k != "parasitics"}, indent=2))
        if rep["parasitics"]:
            print("port_caps_fF:", json.dumps(rep["parasitics"].get("port_caps_fF", {}), indent=2))
