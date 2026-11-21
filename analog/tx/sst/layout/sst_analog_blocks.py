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


def _strap_pass_single_row(
    c: Cell, prim: Cell, dx: float, dy: float, y_vdd_bus: float, y_vdrv_bus: float, x_g_tap: float,
) -> dict:
    """Place single-row 32-finger LVT NMOS pass FET (w=7.5, l=0.15, nf=32, m=1) with
    collinear North D (vdd) and South S (vdrv) M2 buses, West gate tap, and West guard-ring body tie."""
    dx, dy = grid(dx), grid(dy)
    y_vdd_bus, y_vdrv_bus, x_g_tap = grid(y_vdd_bus), grid(y_vdrv_bus), grid(x_g_tap)
    p = slc.clone_cell(prim)
    sd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects["ndiffc"]})
    g_pts = sorted({(grid(x + dx), grid(y + dy)) for _, x, y, lbl in prim.labels if lbl.startswith("G")})
    # West vertical guard-ring bar center (psubdiff/locali x in [dx-8.335, dx-8.165])
    west_li_x = grid(min(r[0] for r in prim.rects["psubdiff"]) + 0.085 + dx)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    d_xs = sd_xs[::2]   # 17 fingers -> vdd (North)
    s_xs = sd_xs[1::2]  # 16 fingers -> vdrv (South)
    g_x0, g_y = g_pts[0][0], g_pts[0][1]

    vo_list = (-2.400, 0.000, +2.400)
    for x in d_xs:
        for vo in vo_list:
            c.via1(x, grid(dy + vo))
        c.wire("metal2", [(x, grid(dy + vo_list[0])), (x, y_vdd_bus)], 0.240)
    c.wire("metal2", [(d_xs[0], y_vdd_bus), (d_xs[-1], y_vdd_bus)], 1.000)

    for x in s_xs:
        for vo in vo_list:
            c.via1(x, grid(dy + vo))
        c.wire("metal2", [(x, y_vdrv_bus), (x, grid(dy + vo_list[-1]))], 0.240)
    c.wire("metal2", [(s_xs[0], y_vdrv_bus), (s_xs[-1], y_vdrv_bus)], 1.000)

    # Gate M1 extension West from gate bar (y = g_y ~ 84.125) to x_g_tap (clear of ndiffc M1 & d_xs[0] M2)
    c.wire("metal1", [(x_g_tap, g_y), (g_x0, g_y)], 0.180)
    c.via1(x_g_tap, g_y)

    # Multi-point body tie along West guard ring (strictly clear of gate M1 and South vdrv M2)
    by1, by2 = grid(dy - 2.000), grid(dy + 0.800)
    for by in (by1, by2):
        c.body_contact(west_li_x, by)
    c.wire("metal2", [(west_li_x, by1), (west_li_x, by2)], 0.340)

    return {
        "D": (d_xs[0], y_vdd_bus),
        "D_right": (d_xs[-1], y_vdd_bus),
        "S": (s_xs[0], y_vdrv_bus),
        "S_right": (s_xs[-1], y_vdrv_bus),
        "G": (x_g_tap, g_y),
        "B": (west_li_x, by1),
        "d_xs": d_xs,
        "s_xs": s_xs,
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

    Floorplan (~86.50 x 88.62 um = ~7,666 um^2, flush West edge xmin = 0.000):
      - West Bay (x in [0.0..60.5], y in [0.8..89.4]):
          * 6 x 24.8x24.8 um stacked MIM1+MIM2 bypass bank (nx=2, ny=3 -> 15.3 pF on M3-M4-M5,
            pillar_side="none", joined to mim_cg via one shared central via34_pillar at x=63.0, y=48.0)
          * 3D Under-MIM (strictly poly/li/M1/M2 below M3!): all 4 head-R-consistent
            single-bar `res_high_po_1p41` resistors: Xrbias (l=80), Xrtop (l=63),
            Xrbot (l=37), Xrbleed (l=38) — zero extra area, 0.00% head-R error!
      - Central VSS Corridor (x = 63.0):
          * Shared M3+M5 VSS trunk + single `via34_pillar(63.0, 48.0)` tying both MIM outer plates,
            NMOS mirror sources/bodies, and Xpass guard ring cleanly down to `yb3=2.90` & `y_vss_bot=1.20`.
      - East Column (centered at x_c = 74.0, x in [64.1..86.5]):
          * South (y in [4.5..22.3]):   Xcg1/Xcg2 (17x17 um stacked MIM1+MIM2, 1.2 pF, pillar_side="none"),
            routing `vgate` straight North on M4 over the M4-free OTA!
          * Middle (y in [28.2..61.8]): MIM-free Analog 5T PMOS-Input OTA & Bias at crisp 5.20 um pitch:
              - ABBA common-centroid NMOS mirror Xm1/Xm2 (4x 4.0x2, unified pwell)
              - ABBA common-centroid PMOS diff pair Xref/Xfb (4x 6.0x4, unified nwell)
              - PMOS diode bias Xbp_ref (20/0.35 nf=4) + tail Xtail (40/0.35 nf=8)
          * North (y in [74.0..86.2]):  Single-row wide LVT NMOS pass FET Xpass (w=7.5, l=0.15, nf=32, m=1)
            with collinear `D (vdd)` at `y_vdd_t = 85.40` and `S (vdrv)` at `y_vdrv_t = 74.75`!
    """
    c = Cell()
    x_east_edge = 86.500
    x_east_port = 86.000
    x_vss_mid = 63.000
    x_vdd_e = 85.000
    x_c = 74.000
    y_vss_bot = 1.200
    y_vdrv_t = 74.750
    y_vdd_t = 85.400

    # ------------------------------------------------------------------
    # Zone 1: West Bay — 6x 24.8x24.8 Stacked MIM1+MIM2 (xmin = 0.000!)
    # ------------------------------------------------------------------
    mim_cd = place_stacked_mim(
        c, cache, side=24.8, cols=2, rows=3,
        dx_c=31.625, dy_c=45.000,
        a_off=1.90, b3_off=1.90, b5_off=2.60,
        pillar_side="none",
    )
    # mim_cd: metal5 x in [0.000..58.210], metal4 x in [0.110..60.250], metal3 x in [3.000..60.490]
    # mim_cd: ya = 87.100, yb3 = 2.900, yb5 = 87.800

    # 3D Under-MIM Resistors (strictly <= M2, well inside x in [6..52], y in [2..88]):
    r_bias = _place_res_1p41(c, cache, 80.0, dx=10.0, dy=45.0)    # y in [2.1..87.9]
    r_top  = _place_res_1p41(c, cache, 63.0, dx=18.0, dy=45.0)    # y in [10.6..79.4]
    r_bot  = _place_res_1p41(c, cache, 37.0, dx=26.0, dy=38.0)    # y in [16.6..59.4]
    r_bld  = _place_res_1p41(c, cache, 38.0, dx=34.0, dy=45.0)    # y in [23.1..66.9]

    # Continuous M2 VSS spine along bottom edge (exact flush [0.000 .. x_east_edge])
    c.rect("metal2", 0.000, grid(y_vss_bot - 0.400), x_east_edge, grid(y_vss_bot + 0.400))
    for rinfo in (r_bias, r_top, r_bot, r_bld):
        bx, by = rinfo["B"]
        xb_drop = grid(bx - 1.200)
        c.wire("metal2", [(bx, by), (xb_drop, by), (xb_drop, y_vss_bot)], 0.360)
    for rinfo in (r_bias, r_bot, r_bld):
        x2, y2 = rinfo["R2"]
        c.wire("metal2", [(x2, y2), (x2, y_vss_bot)], 0.360)

    # Divider vref node: r_top.R2 (18.0, 11.595) -> r_bot.R1 (26.0, 58.405) on M2
    x_vref_bus = 22.000
    c.wire("metal2", [r_top["R2"], (x_vref_bus, r_top["R2"][1]), (x_vref_bus, r_bot["R1"][1]), r_bot["R1"]], 0.360)

    # ------------------------------------------------------------------
    # Zone 2: East-South — Compensation Cap Xcg1/Xcg2 (17x17 Stacked MIM1+MIM2)
    # ------------------------------------------------------------------
    mim_cg = place_stacked_mim(
        c, cache, side=17.0, cols=1, rows=1,
        dx_c=74.900, dy_c=13.400,
        a_off=1.60, b3_off=1.595, b5_off=2.60,
        pillar_side="none",
    )
    # mim_cg: mimcap x in [65.52..82.52] (center 74.02), yb3 = 2.900 (collinear with mim_cd.yb3!),
    #         ya = 23.905, yb5 = 24.505, a = (74.020, 23.905)

    # Shared continuous M3 VSS rail at yb3 = 2.900 joining mim_cd and mim_cg bottom M3 plates!
    yb3 = mim_cd["yb3"]  # 2.900
    c.wire("metal3", [(mim_cd["b3_pts"][0][0], yb3), (mim_cg["b3_pts"][0][0], yb3)], 1.000)
    for vx in (29.700, 59.990, x_vss_mid, mim_cg["b3_pts"][0][0]):
        c.wire("metal3", [(vx, y_vss_bot), (vx, yb3)], 0.800)
        via2_clean(c, vx, y_vss_bot)

    # Shared central M5+M3 VSS pillar at (x_vss_mid=63.0, y_pil=48.0) in the M4/M5-free corridor:
    #   - Joins mim_cd M5 (yb5=87.80) and mim_cg M5 (yb5=24.505) on one straight M5 spine at x=63.0!
    #   - Ties M5 <-> M3 via ONE via34_pillar(63.0, 48.0), running straight South on M3 to yb3=2.90!
    y_pil = 48.000
    c.wire("metal5", [(mim_cd["b5_pts"][-1][0], mim_cd["yb5"]), (x_vss_mid, mim_cd["yb5"])], 1.600)
    c.wire("metal5", [(x_vss_mid, mim_cg["yb5"]), (x_vss_mid, mim_cd["yb5"])], 1.600)
    c.wire("metal5", [(x_vss_mid, mim_cg["yb5"]), (mim_cg["b5_pts"][0][0], mim_cg["yb5"])], 1.600)
    via34_pillar(c, x_vss_mid, y_pil, big=False)
    c.wire("metal3", [(x_vss_mid, y_vss_bot), (x_vss_mid, y_pil)], 0.800)

    # ------------------------------------------------------------------
    # Zone 3: East-Middle — MIM-Free Analog 5T PMOS-Input OTA + Bias
    #         1:1 vertically aligned ABBA columns at crisp 5.20 um pitch!
    # ------------------------------------------------------------------
    ota_pitch = 5.200
    xs_ota = [grid(x_c + (k - 1.5) * ota_pitch) for k in range(4)]  # [66.20, 71.40, 76.60, 81.80]

    # Sub-row 3A (y = 31.20): ABBA Common-Centroid NMOS Current Mirror Xm1/Xm2 (4x 4.0x2)
    y_nmir = 31.200
    p_nmir = cache.device(N_STD, dict(w=4.0, l=0.50, nf=2, m=1, conn_gates=1, guard=1))
    m1_l = _strap_mos_guard1(c, p_nmir, "ndiffc", xs_ota[0], y_nmir, tie_sb=True)
    m2_l = _strap_mos_guard1(c, p_nmir, "ndiffc", xs_ota[1], y_nmir, tie_sb=True)
    m2_r = _strap_mos_guard1(c, p_nmir, "ndiffc", xs_ota[2], y_nmir, tie_sb=True)
    m1_r = _strap_mos_guard1(c, p_nmir, "ndiffc", xs_ota[3], y_nmir, tie_sb=True)
    c.rect("pwell", grid(xs_ota[0] - 1.625), grid(y_nmir - 3.050), grid(xs_ota[-1] + 1.625), grid(y_nmir + 3.050))

    # Shared mirror VSS rail along bottom of Xm1/Xm2 -> tie West into central M3 VSS trunk at x=63.0!
    y_mir_s = m1_l["S"][1]
    c.wire("metal2", [(x_vss_mid, y_mir_s), (m1_r["S_right"][0], y_mir_s)], 0.560)
    via2_clean(c, x_vss_mid, y_mir_s)

    # Shared mirror gate (`nd`) across all 4 segments + diode-connect to m1_l.D_right and m1_r.D_right
    y_nd_g = 36.100
    y_vg_bus = 37.200
    x_nd_min = min(m1_l["D"][0], m1_l["G"][0])
    for seg in (m1_l, m2_l, m2_r, m1_r):
        c.wire("metal2", [seg["G"], (seg["G"][0], y_nd_g)], 0.320)
    c.wire("metal2", [(x_nd_min, y_nd_g), (m1_r["G"][0], y_nd_g)], 0.400)
    for seg in (m1_l, m1_r):
        c.wire("metal2", [seg["D_right"], (seg["D_right"][0], y_nd_g)], 0.340)
    for seg in (m2_l, m2_r):
        dx_m2, dy_m2 = seg["D"]
        via2_clean(c, dx_m2, dy_m2)
        via2_clean(c, dx_m2, y_vg_bus)
        c.wire("metal3", [(dx_m2, dy_m2), (dx_m2, y_vg_bus)], 0.400)
    c.wire("metal2", [(m2_l["D"][0], y_vg_bus), (m2_r["D"][0], y_vg_bus)], 0.360)

    # Sub-row 3B (y = 44.50): ABBA Common-Centroid PMOS Diff Pair Xref/Xfb (4x 6.0x4, unified nwell!)
    y_pdp = 44.500
    p_pdp = cache.device(P_STD, dict(w=6.0, l=0.35, nf=4, m=1, conn_gates=1, guard=1))
    ref_l = _strap_mos_guard1(c, p_pdp, "pdiffc", xs_ota[0], y_pdp, tie_sb=False)
    fb_l  = _strap_mos_guard1(c, p_pdp, "pdiffc", xs_ota[1], y_pdp, tie_sb=False)
    fb_r  = _strap_mos_guard1(c, p_pdp, "pdiffc", xs_ota[2], y_pdp, tie_sb=False)
    ref_r = _strap_mos_guard1(c, p_pdp, "pdiffc", xs_ota[3], y_pdp, tie_sb=False)
    c.rect("nwell", grid(xs_ota[0] - 2.115), grid(y_pdp - 4.095), grid(xs_ota[-1] + 2.115), grid(y_pdp + 4.095))

    # Common `tail` bus across all 4 diff-pair sources + common N-well body tie (`vdd`)
    y_tail_s = ref_l["S"][1]
    c.wire("metal2", [(ref_l["S"][0], y_tail_s), (ref_r["S_right"][0], y_tail_s)], 0.440)
    y_dp_b = ref_l["B"][1]
    c.wire("metal2", [(ref_l["B"][0], y_dp_b), (ref_r["B"][0], y_dp_b)], 0.400)

    # Connect diff-pair drains down to `nd` (y_nd_g) and `vgate` (y_vg_bus) via M3 vertical drops
    for seg in (ref_l, ref_r):
        dx_p, dy_p = seg["D_right"]
        via2_clean(c, dx_p, dy_p)
        via2_clean(c, dx_p, y_nd_g)
        c.wire("metal3", [(dx_p, y_nd_g), (dx_p, dy_p)], 0.400)
    c.wire("metal2", [(x_nd_min, y_nd_g), (ref_r["D_right"][0], y_nd_g)], 0.400)

    for seg in (fb_l, fb_r):
        dx_p, dy_p = seg["D_right"]
        via2_clean(c, dx_p, dy_p)
        via2_clean(c, dx_p, y_vg_bus)
        c.wire("metal3", [(dx_p, y_vg_bus), (dx_p, dy_p)], 0.400)
    c.wire("metal2", [(m2_l["D"][0], y_vg_bus), (fb_r["D_right"][0], y_vg_bus)], 0.360)

    # Connect ABBA gates: vref -> ref_l/ref_r at y=50.80, vdrv -> fb_l/fb_r at y=51.80
    y_g_ref = 50.800
    y_g_fb  = 51.800
    for seg in (ref_l, ref_r):
        c.wire("metal2", [seg["G"], (seg["G"][0], y_g_ref)], 0.320)
    c.wire("metal2", [(x_vref_bus, y_g_ref), (ref_r["G"][0], y_g_ref)], 0.340)

    for seg in (fb_l, fb_r):
        gx, gy = seg["G"]
        via2_clean(c, gx, gy)
        via2_clean(c, gx, y_g_fb)
        c.wire("metal3", [(gx, gy), (gx, y_g_fb)], 0.400)
    c.wire("metal2", [(fb_l["G"][0], y_g_fb), (fb_r["G"][0], y_g_fb)], 0.340)

    # Sub-row 3C (y = 58.20): PMOS Diode Xbp_ref (20/0.35 nf=4) + Tail Xtail (40/0.35 nf=8)
    y_bias = 58.200
    p_tail = cache.device(P_STD, dict(w=5.0, l=0.35, nf=8, m=1, conn_gates=1, guard=1))
    p_bref = cache.device(P_STD, dict(w=5.0, l=0.35, nf=4, m=1, conn_gates=1, guard=1))
    u_bref = _strap_mos_guard1(c, p_bref, "pdiffc", 68.800, y_bias, tie_sb=True)
    u_tail = _strap_mos_guard1(c, p_tail, "pdiffc", 78.400, y_bias, tie_sb=True)

    # Tie Xtail.D -> diff-pair tail bus (y_tail_s) via vertical M3 at u_tail.D_right
    xt_d, yt_d = u_tail["D_right"]
    via2_clean(c, xt_d, yt_d)
    via2_clean(c, xt_d, y_tail_s)
    c.wire("metal3", [(xt_d, y_tail_s), (xt_d, yt_d)], 0.440)

    # Tie Xbp_ref.G, Xtail.G, Xbp_ref.D (`vbp`) on M2 at y = 63.500 -> straight West to r_bias.R1!
    y_vbp = 63.500
    c.wire("metal2", [u_bref["G"], (u_bref["G"][0], y_vbp), (u_tail["G"][0], y_vbp), u_tail["G"]], 0.340)
    c.wire("metal2", [u_bref["D"], (u_bref["D"][0], y_vbp)], 0.340)
    c.wire("metal2", [(r_bias["R1"][0], y_vbp), (u_bref["G"][0], y_vbp)], 0.360)
    c.wire("metal2", [(r_bias["R1"][0], y_vbp), r_bias["R1"]], 0.360)

    # Connect VDD across Xbp_ref.S/B, Xtail.S/B, and diff-pair B -> single clean East VDD spine (x=85.0)
    c.wire("metal2", [(u_bref["S"][0], u_bref["S"][1]), (x_vdd_e, u_bref["S"][1])], 0.600)
    c.wire("metal2", [(ref_r["B"][0], y_dp_b), (x_vdd_e, y_dp_b)], 0.500)
    via2_clean(c, x_vdd_e, y_dp_b)
    via2_clean(c, x_vdd_e, u_bref["S"][1])

    # ------------------------------------------------------------------
    # Zone 4: East-North — Single-Row Wide LVT Pass FET (w=7.5, l=0.15, nf=32, m=1)
    #         Collinear D (vdd) at y_vdd_t = 85.40, S (vdrv) at y_vdrv_t = 74.75!
    # ------------------------------------------------------------------
    p_pass = cache.device(N_LVT, dict(w=7.5, l=0.15, nf=32, m=1, conn_gates=1, guard=1))
    x_vg_m3 = 65.200
    u_pass = _strap_pass_single_row(c, p_pass, x_c, 80.100, y_vdd_t, y_vdrv_t, x_g_tap=x_vg_m3)

    # Tie Xpass West guard ring (vss) straight West on M2 into central M3 VSS trunk at x_vss_mid = 63.0!
    c.wire("metal2", [(x_vss_mid, u_pass["B"][1]), u_pass["B"]], 0.440)
    via2_clean(c, x_vss_mid, u_pass["B"][1])
    c.wire("metal3", [(x_vss_mid, y_pil), (x_vss_mid, u_pass["B"][1])], 0.800)

    # Route `vgate` straight North on M4 from mim_cg["a"] (74.02, 23.905) through y_vg_bus (37.20)
    # over the M4-free OTA up to y=71.80, then M3 underpass under y_vdrv_t M4 at x=65.20 into Xpass.G!
    x_vg_c = mim_cg["a"][0]  # 74.020
    y_vg_hop = 71.800
    via2_clean(c, x_vg_c, y_vg_bus)
    via3_pad(c, x_vg_c, y_vg_bus)
    c.wire("metal4", [mim_cg["a"], (x_vg_c, y_vg_hop), (x_vg_m3, y_vg_hop)], 0.600)
    via3_pad(c, x_vg_m3, y_vg_hop)
    c.wire("metal3", [(x_vg_m3, y_vg_hop), (x_vg_m3, u_pass["G"][1])], 0.400)
    via2_clean(c, x_vg_m3, u_pass["G"][1])

    # Heavy M2/M3/M4 VDD rail over Xpass.D (y_vdd_t = 85.400) -> East VDD spine & East perimeter!
    c.wire("metal2", [(u_pass["D"][0], y_vdd_t), (x_vdd_e, y_vdd_t)], 1.000)
    c.wire("metal3", [(u_pass["D"][0], y_vdd_t), (x_vdd_e, y_vdd_t)], 1.200)
    for vx in (67.0, 69.5, 72.0, 74.5, 77.0, 79.5, 81.5, x_vdd_e):
        via2_clean(c, vx, y_vdd_t)
    c.wire("metal3", [(x_vdd_e, y_dp_b), (x_vdd_e, y_vdd_t)], 1.000)
    via3_array(c, 71.0, y_vdd_t, nx=4, ny=2)
    via3_array(c, 77.5, y_vdd_t, nx=4, ny=2)
    c.rect("metal4", 66.300, grid(y_vdd_t - 0.800), x_east_edge, grid(y_vdd_t + 0.800))

    # Heavy M2/M3/M4/M5 VDRV trunk over Xpass.S (y_vdrv_t = 74.750):
    #   Joins: Xpass.S, mim_cd["a"] (ya=87.10), OTA fb gates (y_g_fb=51.80), r_bld.R1, East port!
    #   M3 stops at x=82.20 (>= 2.30 um clear of x_vdd_e=85.00 M3 spine!); M4+M5 cross cleanly East!
    c.wire("metal3", [(66.500, y_vdrv_t), (82.000, y_vdrv_t)], 1.400)
    for vx in (67.0, 69.5, 72.0, 74.5, 77.0, 79.5, 81.5):
        via2_clean(c, vx, y_vdrv_t)
    via3_array(c, 71.0, y_vdrv_t, nx=4, ny=2)
    via3_array(c, 77.5, y_vdrv_t, nx=4, ny=2)
    c.rect("metal4", 61.700, grid(y_vdrv_t - 0.800), x_east_edge, grid(y_vdrv_t + 0.800))

    # Connect vdrv M4 trunk north at x=62.500 to mim_cd["a"] (y = 87.100)
    x_vdrv_m4 = 62.500
    c.wire("metal4", [(x_vdrv_m4, y_vdrv_t), (x_vdrv_m4, mim_cd["ya"]), mim_cd["a"]], 1.600)

    # Connect vdrv Kelvin sense down to OTA fb gates (y_g_fb=51.80) + r_bld.R1 on M3 at x = 66.500
    x_fb_sense = 66.500
    c.wire("metal3", [(x_fb_sense, y_g_fb), (x_fb_sense, y_vdrv_t)], 0.440)
    via2_clean(c, x_fb_sense, y_g_fb)
    c.wire("metal2", [(x_fb_sense, y_g_fb), (fb_l["G"][0], y_g_fb)], 0.360)
    y_bld = r_bld["R1"][1]
    c.wire("metal2", [r_bld["R1"], (x_fb_sense, y_bld)], 0.360)
    via2_clean(c, x_fb_sense, y_bld)

    # M5 low-R reinforcement over East vdrv exit (strictly >= 15 um clear of x_vss_mid=63.0 M5!)
    via4_array(c, 81.500, y_vdrv_t, nx=2, ny=1)
    c.rect("metal5", 79.000, grid(y_vdrv_t - 1.100), x_east_edge, grid(y_vdrv_t + 1.100))

    # Export `vbg` cleanly West at flush x = 0.000, y = 89.200 (above r_bias top 87.90)
    y_vbg = 89.200
    c.rect("metal2", 0.000, grid(y_vbg - 0.220), grid(r_top["R1"][0] + 0.220), grid(y_vbg + 0.220))
    c.wire("metal2", [(r_top["R1"][0], y_vbg), r_top["R1"]], 0.440)

    if add_ports:
        # Exact schematic port order: vbg vdrv vdd vss
        c.port("vbg",  "metal2", 0.000,       y_vbg)
        c.port("vdrv", "metal4", x_east_port, y_vdrv_t)
        c.port("vdd",  "metal4", x_east_port, y_vdd_t)
        c.port("vss",  "metal2", x_east_port, y_vss_bot)

    return c, {
        "vbg":  (0.000,       y_vbg),
        "vdrv": (x_east_port, y_vdrv_t),
        "vdd":  (x_east_port, y_vdd_t),
        "vss":  (x_east_port, y_vss_bot),
        "x_east_edge": x_east_edge,
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
