#!/usr/bin/env python3
"""SKY130A 5.0 Gb/s Shunt-Peaked RX CTLE PDK Physical Layout Builder & Signoff Suite.

Builds, verifies, and installs the two-tier 5G shunt-peaked RX CTLE PDK macro
matching `analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice` (`shunt_480_5g` defaults:
`win=24 nfin=8 wtail=60 nftail=10 l_rload=3.20 l_rdeg=4.14 c_w=9.81 c_l=9.81 wsw=4`,
stacked 10-turn 8.252 nH inductor `rx_ctle_ind_6n5_pdk`):

  1. Active submacro (`serdes_rx_ctle_active_5g_pdk`, 11 ports:
     `inp inn outp outn lp_mid ln_mid eq0 eq1 vbias vdd vss`, 0.0% M5):
     - South MIM-free signal band: centered 2D common-centroid LVT NMOS input quad
       (`Xip/Xin`, w=24 l=0.15 nf=8) with biased poly dummies and P+ guard ring,
       symmetrically flanked by split `res_high_po_2p85 l=3.20` load resistors
       `Xrp` (West) and `Xrn` (East) whose bottom terminals exit South at `x = +-4.60`
       (`lp_mid`/`ln_mid`, exact mirror symmetry), with equal-length East M3 `inp/inn`
       and offset-balanced West M4 `outp/outn` (`|dC| < 0.2 fF`).
     - North 3D Under-MIM band: 3x `9.81 x 9.81 um` MIM1 caps (`Xceq1a/Xceq0/Xceq1b`)
       stacked cleanly over the centered 20-finger shared-diffusion LVT tail sinks
       (`Xtp/Xtn`, w=60 l=0.50 nf=10 each), under-MIM East `Xrdeg` (`l=4.14`), and
       under-MIM West L=0.18 static EQ0/EQ1 inverters, transmission gates & bleed FETs.
     - Verified with unmodified `verification/layout/review_cell.py --rc`
       (Magic `drc(full)=0`, Netgen `LVS=MATCH` with 0 property errors, 0 floating poly).

  2. Integrated flat top macro (`serdes_rx_ctle_shunt_5g_pdk`, 9 perimeter ports:
     `inp inn outp outn eq0 eq1 vbias vdd vss`):
     - Combines `serdes_rx_ctle_active_5g_pdk` (North) + signed-off `rx_ctle_ind_6n5_pdk`
       (`91.6 x 91.6 um`, rotated 180 deg on South so `pa/ct/pb` face North) with
       `6.20 um` clean clearance to the inductor's open-slotted P+ guard ring.
     - Ultra-short (`11.5 um`) mirror-symmetric M5 `lp_mid`/`ln_mid` feeds to `pa`/`pb`,
       zero-via wide `1.80 um` M3 `ct -> vdd` trunk, single-sided West `vss` guard-ring
       tie preserving the open slot (zero eddy loop), and clean perimeter ports
       (`inp/inn/vbias` East, `outp/outn/eq0/eq1` North-West, full-width `vdd/vss` rails).
     - Verified with Magic `drc(full)=0`, 0 floating poly, DC-equivalent Netgen LVS +
       inductor-open interconnect connectivity audit, and post-layout CPEX + inductor
       AC characterization across TT / SS +85C / SS -40C / FF -40C x EQ 00..11.

All scratch, cache, extraction, review, and ngspice outputs live strictly under
`results/layout/rx_cmos_5g/ctle_shunt/` (zero temp/log/ext files inside `analog/`).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

import numpy as np

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
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from serdes_flow import bias, project, spice  # noqa: E402
from serdes_flow.corners import Condition  # noqa: E402

IND_VARIANT_DIR = HERE / "variants" / "ctle_shunt_ind_5g_pdk"
IND_MAG = IND_VARIANT_DIR / "rx_ctle_ind_6n5_pdk.mag"
IND_SUMMARY = IND_VARIANT_DIR / "summary.json"
VARIANT_DIR = HERE / "variants" / "ctle_shunt_5g_pdk"
RESULTS_DIR = REPO / "results" / "layout" / "rx_cmos_5g" / "ctle_shunt"
SHUNT_SPICE = REPO / "analog" / "rx" / "cmos_rx" / "spice" / "rx_ctle_shunt_5g_pdk.spice"

ACTIVE_NAME = "serdes_rx_ctle_active_5g_pdk"
TOP_NAME = "serdes_rx_ctle_shunt_5g_pdk"

ACTIVE_PORTS = [
    "inp", "inn", "outp", "outn", "lp_mid", "ln_mid",
    "eq0", "eq1", "vbias", "vdd", "vss",
]
TOP_PORTS = [
    "inp", "inn", "outp", "outn", "eq0", "eq1", "vbias", "vdd", "vss",
]


# ---------------------------------------------------------------------------
# Reference SPICE Netlist Generators (1:1 from rx_ctle_shunt_5g_pdk.spice)
# ---------------------------------------------------------------------------

def _active_primitive_lines(lp_node: str = "lp_mid", ln_node: str = "ln_mid") -> list[str]:
    """Exact 20 flattened SKY130 primitives of `serdes_rx_ctle_shunt_5g_pdk` (shunt_480_5g defaults)."""
    return [
        f"X1 {lp_node} outp vss sky130_fd_pr__res_high_po_2p85 l=3.2",
        f"X2 {ln_node} outn vss sky130_fd_pr__res_high_po_2p85 l=3.2",
        "X3 outn inp t_sp vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15",
        "X4 outp inn t_sn vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15",
        "X5 t_sp vbias vss vss sky130_fd_pr__nfet_01v8_lvt w=60 l=0.5",
        "X6 t_sn vbias vss vss sky130_fd_pr__nfet_01v8_lvt w=60 l=0.5",
        "X7 t_sp t_sn vss sky130_fd_pr__res_high_po_2p85 l=4.14",
        "X8 t_eq0_b eq0 vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18",
        "X9 t_eq0_b eq0 vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18",
        "X10 t_eq1_b eq1 vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18",
        "X11 t_eq1_b eq1 vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18",
        "X12 t_sp t_cap0 sky130_fd_pr__cap_mim_m3_1 w=9.81 l=9.81",
        "X13 t_sp t_cap1 sky130_fd_pr__cap_mim_m3_1 w=9.81 l=9.81",
        "X14 t_sp t_cap1 sky130_fd_pr__cap_mim_m3_1 w=9.81 l=9.81",
        "X15 t_cap0 eq0 t_sn vss sky130_fd_pr__nfet_01v8 w=4 l=0.18",
        "X16 t_cap0 t_eq0_b t_sn vdd sky130_fd_pr__pfet_01v8 w=8 l=0.18",
        "X17 t_cap1 eq1 t_sn vss sky130_fd_pr__nfet_01v8 w=4 l=0.18",
        "X18 t_cap1 t_eq1_b t_sn vdd sky130_fd_pr__pfet_01v8 w=8 l=0.18",
        "X19 t_cap0 t_eq0_b t_sp vss sky130_fd_pr__nfet_01v8 w=0.42 l=0.5",
        "X20 t_cap1 t_eq1_b t_sp vss sky130_fd_pr__nfet_01v8 w=0.42 l=0.5",
    ]


def write_active_ref_spice(out_path: Path) -> None:
    lines = [
        f"* Exact flattened LVS reference netlist for {ACTIVE_NAME}",
        "* Source: analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice (shunt_480_5g active core)",
        f".subckt {ACTIVE_NAME} " + " ".join(ACTIVE_PORTS),
        *_active_primitive_lines("lp_mid", "ln_mid"),
        f".ends {ACTIVE_NAME}",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))


def write_top_dc_lvs_ref_spice(out_path: Path) -> None:
    """DC-equivalent flat LVS reference for top macro (inductor spiral shorts lp_mid/ln_mid to vdd at DC)."""
    lines = [
        f"* DC-equivalent flat connectivity LVS reference for {TOP_NAME}",
        "* At DC, stacked spiral rx_ctle_ind_6n5_pdk shorts pa (lp_mid), pb (ln_mid), and ct to vdd.",
        f".subckt {TOP_NAME} " + " ".join(TOP_PORTS),
        *_active_primitive_lines("vdd", "vdd"),
        f".ends {TOP_NAME}",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))


def write_top_ref_spice(out_path: Path) -> None:
    """Full schematic reference netlist for integrated `serdes_rx_ctle_shunt_5g_pdk` (including `rx_ctle_ind_6n5_pdk`)."""
    src_txt = SHUNT_SPICE.read_text()
    m = re.search(r"(\.subckt\s+rx_ctle_ind_6n5_pdk\b.*?\.ends\s+rx_ctle_ind_6n5_pdk)", src_txt, re.S)
    if not m:
        raise RuntimeError(f"Could not extract rx_ctle_ind_6n5_pdk from {SHUNT_SPICE}")
    ind_sub = m.group(1).strip()
    lines = [
        f"* Authoritative reference netlist for integrated 5G shunt-peaked RX CTLE ({TOP_NAME})",
        "* Source: analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice (shunt_480_5g defaults)",
        "",
        ind_sub,
        "",
        f".subckt {TOP_NAME} " + " ".join(TOP_PORTS),
        "Xind lp_mid ln_mid vdd vss rx_ctle_ind_6n5_pdk",
        *_active_primitive_lines("lp_mid", "ln_mid"),
        f".ends {TOP_NAME}",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# 1. Active CTLE Submacro (`serdes_rx_ctle_active_5g_pdk`, 0.0% M5)
# ---------------------------------------------------------------------------

def _place_mim_unit(c: Cell, cache: PdkCache, dx: float, dy: float, mirror_x: bool = True) -> dict:
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


def build_rx_ctle_active_5g_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build `serdes_rx_ctle_active_5g_pdk` (`41.40 x 26.10 um`, 0.0% M5).

    Local coordinates: `x in [-20.700, +20.700]`, `y in [0.000, +26.100]`.
      - South band (`y in [0.0, +11.4]`, 100% MIM-free):
          * Centered 2D CC LVT NMOS input quad (`Xip/Xin`, w=24 l=0.15 nf=8) at x = +-2.60
          * Split mirror `res_high_po_2p85 l=3.20` load resistors `Xrp` (-11.20) & `Xrn` (+11.20)
          * South symmetric M4 `lp_mid` (-4.60, 0.00) & `ln_mid` (+4.60, 0.00) facing inductor
          * Equal-length East M3 `inp/inn` (+6.45 / +5.55) and offset-balanced West M4 `outp/outn` (+7.30 / +4.70)
      - North band (`y in [+11.5, +26.1]`, 3D Under-MIM):
          * Centered 20-finger shared-diffusion LVT tail (`Xtp/Xtn`, w=60 l=0.50 nf=10 each)
          * Under-MIM East `Xrdeg` (`res_high_po_2p85 l=4.14` at +14.65)
          * Under-MIM West L=0.18 static EQ0/EQ1 inverters, T-gates & bleed FETs
          * 3x `9.81 x 9.81 um` MIM1 caps (`Xceq1b/Xceq0/Xceq1a`) at `dx = -13.80, 0.00, +13.80`
    """
    c = Cell()

    x_w_port = -20.700
    x_e_port = +20.700
    y_vss_n  = +25.700
    y_s_edge = 0.000

    # Flush North global M2 `vss` rail (`y in [+25.300, +26.100]`)
    c.rect("metal2", x_w_port, grid(y_vss_n - 0.400), x_e_port, grid(y_vss_n + 0.400))

    # =========================================================================
    # NORTH BAND (3D Under-MIM): Xtp/Xtn (20f shared-diff) + Xrdeg (E) + EQ0/1 (W)
    # =========================================================================
    dy_tail = +17.500
    cx_tail = 0.000
    m_tail, inf_tail = cache.build_mos(N_LVT, 6.00, 0.50, 20, dy_tail, False)
    c.include(m_tail, dx=cx_tail)

    t_sds = [grid(cx_tail + x) for x in inf_tail["all_sd_xs"]]  # 21 stripes [-7.90 .. +7.90]
    t_vss_xs = t_sds[::2]                                       # 11 source stripes -> vss
    # Near-exact 1D common-centroid (5 identical interior shared drains each -> 10 fingers = 60 um each!)
    t_sp_xs  = [t_sds[k] for k in (1, 5, 9, 15, 19)]            # [-7.11, -3.95, -0.79, +3.95, +7.11]
    t_sn_xs  = [t_sds[k] for k in (3, 7, 11, 13, 17)]           # [-5.53, -2.37, +0.79, +2.37, +5.53]

    # Tail VSS straps (uniform 0.32 um M1 matching via1 -> zero met1.2 notches)
    y_tail_vss = +19.600
    for sx in t_vss_xs:
        for vy in (+15.000, +16.200, +17.500, +18.800, +20.000):
            viali_pad(c, sx, vy)
        c.wire("metal1", [(sx, +15.000), (sx, +20.000)], 0.320)
        via1_clean(c, sx, y_tail_vss)
    c.wire("metal2", [(t_vss_xs[0], y_tail_vss), (t_vss_xs[-1], y_tail_vss)], 0.440)
    for sx in (t_vss_xs[0], t_vss_xs[5], t_vss_xs[-1]):
        c.wire("metal2", [(sx, y_tail_vss), (sx, y_vss_n)], 0.440)

    # Tail `sp` (y = +15.300 M2) & `sn` (y = +16.700 M2)
    y_tail_sp = +15.300
    y_tail_sn = +16.700
    for dx_s, y_bus in ((t_sp_xs, y_tail_sp), (t_sn_xs, y_tail_sn)):
        for x in dx_s:
            for vy in (+15.300, +16.700, +18.300, +19.900):
                viali_pad(c, x, vy)
            c.wire("metal1", [(x, +15.300), (x, +19.900)], 0.320)
            via1_clean(c, x, y_bus)
        c.wire("metal2", [(dx_s[0], y_bus), (dx_s[-1], y_bus)], 0.440)

    # Tail gates (`vbias`) along North poly bar
    y_tail_g = +21.250
    t_g_pts = tie_mos_gates(
        c, cx_tail, inf_tail, y_bar=+20.900, y_cont=y_tail_g,
        tap_xs=[grid(cx_tail - 6.300), cx_tail, grid(cx_tail + 6.300)],
    )
    c.wire("metal1", [(t_g_pts[0][0], y_tail_g), (t_g_pts[-1][0], y_tail_g)], 0.320)

    # Biased poly dummies flanking Xtp/Xtn -> tied to North guard ring (y = +22.350)
    x_tdum_l = grid(cx_tail + inf_tail["diff_x1"] - 0.140 - 0.250)  # -8.435
    x_tdum_r = grid(cx_tail + inf_tail["diff_x2"] + 0.140 + 0.250)  # +8.435
    y_tail_gr_n = +22.350
    y_tail_gr_s = +13.200
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

    # Route `vbias` East on M1 at y = +23.600 (flush to x_e_port = +20.700)
    y_vbias = +23.600
    xv_bias = t_g_pts[-1][0]  # +6.300
    via1_clean(c, xv_bias, y_tail_g)
    c.wire("metal2", [(xv_bias, y_tail_g), (xv_bias, y_vbias)], 0.340)
    via1_clean(c, xv_bias, y_vbias)
    c.rect("metal1", grid(xv_bias - 0.170), grid(y_vbias - 0.170), x_e_port, grid(y_vbias + 0.170))

    # Under-MIM East: `Xrdeg` (`res_high_po_2p85 l=4.14, nx=1, guard=1`)
    rdeg_c = cache.device(R_2P85, dict(l=4.14, nx=1, m=1, guard=1))
    rd_r1 = rdeg_c.pins("R1")[0]
    rd_r2 = rdeg_c.pins("R2")[0]
    rd_b  = rdeg_c.pins("B")[0]
    rdeg_c.labels.clear()
    dx_rdeg, dy_rdeg = +14.650, +17.600
    c.include(rdeg_c, dx=dx_rdeg, dy=dy_rdeg)
    p_rd_sn = (grid(dx_rdeg + rd_r1[0]), grid(dy_rdeg + rd_r1[1]))  # (+14.650, +21.575)
    p_rd_sp = (grid(dx_rdeg + rd_r2[0]), grid(dy_rdeg + rd_r2[1]))  # (+14.650, +13.625)
    p_rd_b  = (grid(dx_rdeg + rd_b[0]),  grid(dy_rdeg + rd_b[1]))   # (+14.650, +12.885)

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

    # Under-MIM West: EQ0/EQ1 inverters, T-gates, tie FETs (exact X+Y mirror of proven 4G block, shifted -1.80 in X)
    y_eq_vdd = +12.550
    y_eq_p   = +14.350
    y_eq_n   = +18.450
    y_eq_tie = +20.900

    c.rect("nwell", -20.100, +11.950, -10.300, +15.850)
    draw_tap_h(c, "nsubdiff", -19.850, -10.550, y_eq_vdd, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_h(c, "psubdiff", -20.000, x_tgr_l, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)
    draw_tap_v(c, "psubdiff", -20.000, +16.500, y_tail_gr_n, half_w=0.180, with_m1=True, m1_w=0.340)

    # Clean West M2 `vdd` trunk from EQ NWELL bar straight South to flush South edge (y = 0.000)
    x_vdd_act = -20.100
    via1_clean(c, -19.600, y_eq_vdd)
    c.wire("metal2", [(x_vdd_act, y_eq_vdd), (-19.600, y_eq_vdd)], 0.440)
    c.rect("metal2", grid(x_vdd_act - 0.300), y_s_edge, grid(x_vdd_act + 0.300), grid(y_eq_vdd + 0.220))

    via1_clean(c, -19.500, y_tail_gr_n)
    c.wire("metal2", [(-19.500, y_tail_gr_n), (-19.500, y_vss_n)], 0.440)

    m_inv_n, inf_inv_n = cache.build_mos(N_STD, 1.00, 0.18, 1, y_eq_n, False)
    m_inv_p, inf_inv_p = cache.build_mos(P_STD, 2.00, 0.18, 1, y_eq_p, True)
    m_swn,   inf_swn   = cache.build_mos(N_STD, 2.00, 0.18, 2, y_eq_n, False)
    m_swp,   inf_swp   = cache.build_mos(P_STD, 2.00, 0.18, 4, y_eq_p, True)
    m_tie,   inf_tie   = cache.build_mos(N_STD, 0.42, 0.50, 1, y_eq_tie, False)

    cx_eq0, cx_sw0, cx_sw1, cx_eq1 = -11.400, -13.700, -16.700, -18.950
    for cx_inv in (cx_eq0, cx_eq1):
        c.include(m_inv_n, dx=cx_inv)
        c.include(m_inv_p, dx=cx_inv)
    for cx_sw in (cx_sw0, cx_sw1):
        c.include(m_swn, dx=cx_sw)
        c.include(m_swp, dx=cx_sw)
        c.include(m_tie, dx=cx_sw)

    y_eq_gb   = +16.000
    y_eq_g    = +16.850
    y_swp_sn,  y_swp_cap = +13.850, +14.850
    y_swn_cap, y_swn_sn  = +17.850, +18.950

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

        swp_g = tie_mos_gates(c, cx_sw, inf_swp, y_bar=+15.650, y_cont=y_eq_gb, tap_xs=[cx_sw])[0]
        c.wire("metal1", sorted([(x_in_d, y_eq_gb), swp_g], key=lambda p: p[0]), 0.290)

        swn_g = tie_mos_gates(c, cx_sw, inf_swn, y_bar=+17.200, y_cont=y_eq_g, tap_xs=[cx_sw])[0]
        via1_clean(c, gx_tap, y_eq_g)
        via1_clean(c, swn_g[0], y_eq_g)
        c.wire("metal2", sorted([(gx_tap, y_eq_g), swn_g], key=lambda p: p[0]), 0.280)

        tie_g = tie_mos_gates(c, cx_sw, inf_tie, y_bar=+20.450, y_cont=+20.050, tap_xs=[cx_sw])[0]
        c.wire("metal1", [(x_in_d, y_eq_gb), (x_in_d, +20.050)], 0.290)
        c.wire("metal1", sorted([(x_in_d, +20.050), tie_g], key=lambda p: p[0]), 0.290)

        swn_sn  = [grid(cx_sw + x) for x in inf_swn["s_xs"]]
        swn_cap = [grid(cx_sw + x) for x in inf_swn["d_xs"]]
        swp_sn  = [grid(cx_sw + x) for x in inf_swp["s_xs"]]
        swp_cap = [grid(cx_sw + x) for x in inf_swp["d_xs"]]

        for sx in swp_sn:
            viali_pad(c, sx, y_swp_sn)
            via1_clean(c, sx, y_swp_sn)
        c.wire("metal2", [(swp_sn[0], y_swp_sn), (swp_sn[-1], y_swp_sn)], 0.320)

        for sx in swn_sn:
            viali_pad(c, sx, y_swn_sn)
            via1_clean(c, sx, y_swn_sn)
        c.wire("metal2", [(swn_sn[0], y_swn_sn), (swn_sn[-1], y_swn_sn)], 0.320)

        xc_n = swn_cap[0]
        viali_pad(c, xc_n, y_swn_cap)
        via1_clean(c, xc_n, y_swn_cap)
        for sx in swp_cap:
            viali_pad(c, sx, y_swp_cap)
            via1_clean(c, sx, y_swp_cap)
        c.wire("metal2", [(swp_cap[0], y_swp_cap), (swp_cap[-1], y_swp_cap)], 0.320)
        x_cap_br = grid(cx_sw - sgn * 0.650)
        c.wire("metal2", [(xc_n, y_swn_cap), (x_cap_br, y_swn_cap), (x_cap_br, y_swp_cap), (swp_cap[-1], y_swp_cap)], 0.280)

        viali_pad(c, xc_n, +19.150)
        c.wire("metal1", [(xc_n, y_swn_cap), (xc_n, +19.550)], 0.290)
        via1_clean(c, xc_n, +19.550)

        xt_sp  = grid(cx_sw + inf_tie["d_xs"][0])
        xt_cap = grid(cx_sw + inf_tie["s_xs"][0])
        viali_pad(c, xt_cap, y_eq_tie)
        via1_clean(c, xt_cap, y_eq_tie)
        c.wire("metal2", [(xc_n, +19.550), (xc_n, y_eq_tie), (xt_cap, y_eq_tie)], 0.320)

        viali_pad(c, xt_sp, y_eq_tie)
        c.wire("metal1", [(xt_sp, y_eq_tie), (xt_sp, +21.600)], 0.290)

    # Join T-gate `sn` terminals cleanly into tail `sn` M2 bus (y = +16.700)
    c.wire("metal2", [(grid(cx_sw1 + inf_swp["s_xs"][0]), y_swp_sn), (grid(cx_sw0 + inf_swp["s_xs"][-1]), y_swp_sn)], 0.340)
    c.wire("metal2", [(grid(cx_sw1 + inf_swn["s_xs"][0]), y_swn_sn), (grid(cx_sw0 + inf_swn["s_xs"][-1]), y_swn_sn)], 0.340)
    c.wire("metal2", [(-15.200, y_swp_sn), (-15.200, y_swn_sn)], 0.340)
    x_sn_w = -10.350
    c.wire("metal2", [
        (grid(cx_sw0 + inf_swn["s_xs"][-1]), y_swn_sn),
        (x_sn_w, y_swn_sn),
        (x_sn_w, y_tail_sn),
        (t_sn_xs[0], y_tail_sn),
    ], 0.400)

    # Join bleed-FET `sp` terminals cleanly on M1 around tail guard ring -> `t_sp_xs[0]` (-7.110)
    xt1_sp = grid(cx_sw1 + inf_tie["d_xs"][0])
    x_tie_m1 = -10.050
    c.wire("metal1", [(xt1_sp, +21.600), (x_tie_m1, +21.600)], 0.290)
    c.wire("metal1", [(x_tie_m1, +12.600), (x_tie_m1, +21.600)], 0.290)
    c.wire("metal1", [(x_tie_m1, +12.600), (t_sp_xs[0], +12.600)], 0.290)
    via1_clean(c, t_sp_xs[0], +12.600)
    c.wire("metal2", [(t_sp_xs[0], +12.600), (t_sp_xs[0], y_tail_sp)], 0.380)

    # Export `eq0` and `eq1` flush to x_w_port = -20.700 on M1 (crossing cleanly under x_vdd_act=-20.10 M2!)
    y_eq0_out = +11.650
    y_eq1_out = +23.250
    x_eq0_v = grid(cx_eq0 + 0.250)  # -11.150
    x_eq0_drop = -18.800            # 1.30 um clear of x_vdd_act=-20.10 M2!
    c.wire("metal2", [(x_eq0_v, y_eq_g), (x_eq0_v, y_eq0_out), (x_eq0_drop, y_eq0_out)], 0.280)
    via1_clean(c, x_eq0_drop, y_eq0_out)
    c.rect("metal1", x_w_port, grid(y_eq0_out - 0.140), grid(x_eq0_drop + 0.140), grid(y_eq0_out + 0.140))

    x_eq1_v = -18.050
    x_eq1_drop = -18.700
    c.wire("metal2", [(x_eq1_v, y_eq_g), (x_eq1_v, y_eq1_out), (x_eq1_drop, y_eq1_out)], 0.280)
    via1_clean(c, x_eq1_drop, y_eq1_out)
    c.rect("metal1", x_w_port, grid(y_eq1_out - 0.140), grid(x_eq1_drop + 0.140), grid(y_eq1_out + 0.140))

    # 3D-Stacked 3x MIM Caps (pitch 13.800 um -> 2.130 um gap >> 1.340 um capm.11!)
    dy_mim = +17.500
    mim_1b = _place_mim_unit(c, cache, dx=-13.800, dy=dy_mim, mirror_x=True)
    mim_0  = _place_mim_unit(c, cache, dx=  0.000, dy=dy_mim, mirror_x=True)
    mim_1a = _place_mim_unit(c, cache, dx=+13.800, dy=dy_mim, mirror_x=True)

    # Join all 3 C1 (top plate = sp) on M4 at y = +11.450 -> drop at x_sp_drop = t_sp_xs[-1] (+7.110)
    y_mim_sp = +11.450
    for m_info in (mim_1b, mim_0, mim_1a):
        cx1, cy1 = m_info["c1"]
        c.wire("metal4", [(cx1, y_mim_sp), (cx1, cy1)], 0.720)
    c.wire("metal4", [(mim_1b["c1"][0], y_mim_sp), (mim_1a["c1"][0], y_mim_sp)], 0.720)
    x_sp_drop = t_sp_xs[-1]  # +7.110 (cleanly in the 2.13 um gap between mim_0 [+5.835] and mim_1a [+7.965]!)
    via3_pad(c, x_sp_drop, y_mim_sp)
    via2_clean(c, x_sp_drop, y_mim_sp)
    c.wire("metal2", [(x_sp_drop, y_mim_sp), (x_sp_drop, y_tail_sp)], 0.440)

    # Join `cap0` & `cap1` on North M4 (> 1.44 um north of mimcap +22.605 -> ZERO capm.11!)
    y_cap0_m4 = +24.050
    c.wire("metal4", [mim_0["c2"], (mim_0["c2"][0], y_cap0_m4), (cx_sw0, y_cap0_m4)], 0.520)
    via3_pad(c, cx_sw0, y_cap0_m4)
    via2_clean(c, cx_sw0, y_cap0_m4)
    c.wire("metal2", [(cx_sw0, y_eq_tie), (cx_sw0, y_cap0_m4)], 0.340)

    y_cap1_m4 = +24.900
    c.wire("metal4", [mim_1b["c2"], (mim_1b["c2"][0], y_cap1_m4), (mim_1a["c2"][0], y_cap1_m4), mim_1a["c2"]], 0.520)
    via3_pad(c, cx_sw1, y_cap1_m4)
    via2_clean(c, cx_sw1, y_cap1_m4)
    c.wire("metal2", [(cx_sw1, y_eq_tie), (cx_sw1, y_cap1_m4)], 0.340)

    # =========================================================================
    # SOUTH BAND (100% MIM-FREE!): Centered 2D CC Xip/Xin + Split Mirror Xrp | Xrn
    # =========================================================================
    # 2D Common-Centroid Assignment:
    #   NW (-2.60, +8.45) & SE (+2.60, +3.55) = Xip (G=inp, D=outn, S=sp)
    #   NE (+2.60, +8.45) & SW (-2.60, +3.55) = Xin (G=inn, D=outp, S=sn)
    cx_q_l, cx_q_r = -2.600, +2.600
    dy_q_s, dy_q_n = +3.550, +8.450
    m_in_s, inf_in_s = cache.build_mos(N_LVT, 3.00, 0.15, 4, dy_q_s, False)
    m_in_n, inf_in_n = cache.build_mos(N_LVT, 3.00, 0.15, 4, dy_q_n, False)
    for cx_q in (cx_q_l, cx_q_r):
        c.include(m_in_s, dx=cx_q)
        c.include(m_in_n, dx=cx_q)

    # Continuous mirror-symmetric P+ guard ring around centered 2D CC quad
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

    # Biased poly dummies flanking quad -> tied horizontally to vertical guard bars
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
        ("SW", cx_q_l, inf_in_s, +2.700, +4.150, +5.300, +5.550),
        ("SE", cx_q_r, inf_in_s, +2.700, +4.150, +5.300, +5.550),
        ("NW", cx_q_l, inf_in_n, +9.300, +7.850, +6.700, +6.450),
        ("NE", cx_q_r, inf_in_n, +9.300, +7.850, +6.700, +6.450),
    ):
        s_xs = [grid(cx_q + x) for x in inf_r["s_xs"]]
        d_xs = [grid(cx_q + x) for x in inf_r["d_xs"]]
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

    # Equal-Length East `inp` (NW+SE) / `inn` (NE+SW) M3 buses centered around y = +6.000
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

    # Symmetric 2D CC Source Routing (`sp`: NW + SE; `sn`: NE + SW) cleanly into 20f tail!
    x_sn_l = -8.100  # strictly outside t_sp_xs[0] (-7.11) and inside Xrp right edge (-8.945)!
    x_sp_r = +8.100  # strictly outside t_sp_xs[-1] (+7.11) and inside Xrn left edge (+8.945)!
    y_sn_hop = +14.150

    # SE (sp) -> Right channel (+8.10) straight North to y_tail_sp (+15.30) -> West to t_sp_xs[-1] (+7.11)
    c.wire("metal2", [q_s_pts["SE"], (x_sp_r, q_s_pts["SE"][1]), (x_sp_r, y_tail_sp), (t_sp_xs[-1], y_tail_sp)], 0.400)
    # NW (sp) -> Straight North at -2.60 to y_tail_sp (+15.30)
    c.wire("metal2", [q_s_pts["NW"], (cx_q_l, y_tail_sp)], 0.400)

    # SW (sn) -> Left channel (-8.10) straight North to y_tail_sn (+16.70) -> East to t_sn_xs[0] (-5.53)
    c.wire("metal2", [q_s_pts["SW"], (x_sn_l, q_s_pts["SW"][1]), (x_sn_l, y_tail_sn), (t_sn_xs[0], y_tail_sn)], 0.400)
    # NE (sn) -> North at +2.60 to y_sn_hop (+14.15) -> M1 hop under NW(sp) (-2.60) & t_sp_xs[0] (-7.11) -> join SW(sn) at -8.10!
    c.wire("metal2", [q_s_pts["NE"], (cx_q_r, y_sn_hop), (-1.450, y_sn_hop)], 0.380)
    via1_clean(c, -1.450, y_sn_hop)
    c.wire("metal1", [(x_sn_l, y_sn_hop), (-1.450, y_sn_hop)], 0.360)
    via1_clean(c, x_sn_l, y_sn_hop)

    # Split Mirror-Symmetric Load Resistors: `Xrp` (West -11.20) & `Xrn` (East +11.20), `l = 3.20`
    rld1 = cache.device(R_2P85, dict(l=3.20, nx=1, m=1, guard=1))
    r1_out = rld1.pins("R1")[0]   # top (+3.505) -> outp / outn
    r1_lp  = rld1.pins("R2")[0]   # bot (-3.505) -> lp_mid / ln_mid
    r1_b   = rld1.pins("B")[0]    # bot (-4.245) -> vss guard tie
    rld1.labels.clear()

    dx_rp, dx_rn, dy_rld = -11.200, +11.200, +6.000
    c.include(rld1, dx=dx_rp, dy=dy_rld)
    c.include(rld1, dx=dx_rn, dy=dy_rld)

    p_rp_out = (grid(dx_rp + r1_out[0]), grid(dy_rld + r1_out[1]))  # (-11.200, +9.505)
    p_rn_out = (grid(dx_rn + r1_out[0]), grid(dy_rld + r1_out[1]))  # (+11.200, +9.505)
    p_rp_lp  = (grid(dx_rp + r1_lp[0]),  grid(dy_rld + r1_lp[1]))   # (-11.200, +2.495)
    p_rn_ln  = (grid(dx_rn + r1_lp[0]),  grid(dy_rld + r1_lp[1]))   # (+11.200, +2.495)
    p_rp_b   = (grid(dx_rp + r1_b[0]),   grid(dy_rld + r1_b[1]))    # (-11.200, +1.755)
    p_rn_b   = (grid(dx_rn + r1_b[0]),   grid(dy_rld + r1_b[1]))    # (+11.200, +1.755)

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
        # Dual via2 + via3 landing bar into a clean 1.80-wide M4 port pad at South edge y = 0.000
        for dxv in (-0.360, +0.360):
            vx = grid(x_port + dxv)
            via2_clean(c, vx, y_lp_bus)
            via3_pad(c, vx, y_lp_bus)
        c.rect("metal2", grid(x_port - 0.660), grid(y_lp_bus - 0.300), grid(x_port + 0.660), grid(y_lp_bus + 0.300))
        c.rect("metal3", grid(x_port - 0.660), grid(y_lp_bus - 0.260), grid(x_port + 0.660), grid(y_lp_bus + 0.260))
        c.rect("metal4", grid(x_port - 0.900), y_s_edge, grid(x_port + 0.900), grid(y_lp_bus + 0.300))

    # Mirror-Symmetric `outp` (Xrp + SW + NE) & `outn` (Xrn + SE + NW) + Exact Balanced M4 West Exit!
    x_sw_out = grid(cx_q_l + inf_in_s["d_xs"][0])   # -3.080
    x_se_out = grid(cx_q_r + inf_in_s["d_xs"][-1])  # +3.080
    for p_out, x_qd, y_qd in ((p_rp_out, x_sw_out, q_d_pts["SW"][1]), (p_rn_out, x_se_out, q_d_pts["SE"][1])):
        for dxv in (-0.800, 0.000, +0.800):
            via1_clean(c, grid(p_out[0] + dxv), p_out[1])
        c.wire("metal2", [(grid(p_out[0] - 0.800), p_out[1]), (grid(p_out[0] + 0.800), p_out[1])], 0.440)
        c.wire("metal2", [(p_out[0], y_qd), p_out], 0.440)
        via2_clean(c, p_out[0], y_qd)
        via2_clean(c, x_qd, y_qd)
        c.wire("metal3", sorted([(p_out[0], y_qd), (x_qd, y_qd)], key=lambda p: p[0]), 0.400)

    # Point-symmetric diagonal cross-connection around (0.000, +6.000) -> `outp` (+7.30) North of `outn` (+4.70)!
    y_outp_bus = +7.300  # +1.300 above 6.000 (gap to inp=6.45 M3 pad is 0.33 >= 0.30 um)
    y_outn_bus = +4.700  # -1.300 below 6.000 (gap to inn=5.55 M3 pad is 0.33 >= 0.30 um)
    x_sw_in = grid(cx_q_l + inf_in_s["d_xs"][-1])  # -2.120
    x_se_in = grid(cx_q_r + inf_in_s["d_xs"][0])   # +2.120

    # outp: SW (-2.12, 4.15) -> (-0.50, 4.15) -> (-0.50, 7.30) -> M3 to (+1.50, 7.30) -> M2 to (+1.50, 7.85) -> NE (+2.12, 7.85)
    c.wire("metal2", [(x_sw_in, q_d_pts["SW"][1]), (-0.500, q_d_pts["SW"][1]), (-0.500, y_outp_bus)], 0.360)
    via2_clean(c, -0.500, y_outp_bus)
    c.wire("metal3", [(-0.500, y_outp_bus), (+1.500, y_outp_bus)], 0.400)
    via2_clean(c, +1.500, y_outp_bus)
    c.wire("metal2", [(+1.500, y_outp_bus), (+1.500, q_d_pts["NE"][1]), (x_se_in, q_d_pts["NE"][1])], 0.360)

    # outn: SE (+2.12, 4.15) -> (+0.50, 4.15) -> (+0.50, 4.70) -> M3 to (-1.50, 4.70) -> M2 to (-1.50, 7.85) -> NW (-2.12, 7.85)
    c.wire("metal2", [(x_se_in, q_d_pts["SE"][1]), (+0.500, q_d_pts["SE"][1]), (+0.500, y_outn_bus)], 0.360)
    via2_clean(c, +0.500, y_outn_bus)
    c.wire("metal3", [(-1.500, y_outn_bus), (+0.500, y_outn_bus)], 0.400)
    via2_clean(c, -1.500, y_outn_bus)
    c.wire("metal2", [(-1.500, y_outn_bus), (-1.500, q_d_pts["NW"][1]), (x_sw_in, q_d_pts["NW"][1])], 0.360)

    # Offset-balanced M4 West differential exit (cancel Xrp/Xrn M3/M4 asymmetry -> |dC(outp,outn)| < 0.15 fF!)
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


# ---------------------------------------------------------------------------
# 2. Integrated Top Macro (`serdes_rx_ctle_shunt_5g_pdk`, flat drop-in)
# ---------------------------------------------------------------------------

def build_rx_ctle_shunt_5g_top(
    active_cell: Cell,
    active_meta: dict,
    include_inductor: bool = True,
    add_ports: bool = True,
) -> tuple[Cell, dict]:
    """Assemble integrated flat `serdes_rx_ctle_shunt_5g_pdk` (`91.60 x 124.40 um`).

    Inductor `rx_ctle_ind_6n5_pdk` (`91.6 x 91.6 um`) sits on SOUTH rotated 180 deg
    (`center = (0.0, -52.000)`, bbox `[-45.8, -97.8, +45.8, -6.2]`), giving `6.20 um`
    clean clearance to the Active CTLE (`y in [0.0, +26.1]`).
    """
    c = Cell()

    # 1. Include Active CTLE (North, labels stripped)
    act_unlbl = rlc.clone_cell(active_cell)
    act_unlbl.labels.clear()
    c.include(act_unlbl, dx=0.0, dy=0.0)

    # 2. Include signed-off Inductor `rx_ctle_ind_6n5_pdk` (South, rotated 180 deg, labels stripped)
    ind_cy = -52.000  # North guard ring outer edge at -52.0 + 45.8 = -6.200 (6.20 um clearance!)
    if include_inductor:
        ind = Cell.read(IND_MAG)
        ind.labels.clear()
        c.include(ind, dx=0.0, dy=ind_cy, mirror_x=True, mirror_y=True)

    x_west = -45.800
    x_east = +45.800
    x_act_w = active_meta["x_w_port"]    # -20.700
    x_act_e = active_meta["x_e_port"]    # +20.700
    x_vdd_act = active_meta["x_vdd_act"] # -20.100
    y_vss_top = active_meta["y_vss_n"]   # +25.700
    y_vdd_top = -3.600                   # centered in 6.20 um clearance bay ([-4.50, -2.70])

    # 3. Ultra-short mirror-symmetric M5 `lp_mid` / `ln_mid` feeds (`x = +-4.600`, `11.5 um` long!)
    #    via4 sits at y = -0.900 (in clearance gap, 0% M5 over active core, 0 stacked via4-over-via3)
    for x_arm in (-4.600, +4.600):
        c.rect("metal4", grid(x_arm - 0.900), -1.800, grid(x_arm + 0.900), +0.600)
        c.pad("via4", x_arm, -0.900, 1.180)
        c.rect("metal5", grid(x_arm - 0.900), -11.500, grid(x_arm + 0.900), 0.000)

    # 4. Low-impedance zero-via `ct -> vdd` wide `1.80 um` M3 rail (+ parallel M4 wings outside |x|>=9.0)
    c.rect("metal3", -0.900, -11.500, +0.900, grid(y_vdd_top + 0.900))  # seamless M3 fusion with ct!
    c.rect("metal3", x_west, grid(y_vdd_top - 0.900), x_east, grid(y_vdd_top + 0.900))
    # Parallel M4 straps on West & East wings (clear of lp_mid/ln_mid at +-4.60) for < 0.7 Ohm rail R
    for xa, xb in ((x_west, -9.000), (+9.000, x_east)):
        c.rect("metal4", xa, grid(y_vdd_top - 0.900), xb, grid(y_vdd_top + 0.900))
        xv = grid(xa + 1.200)
        while xv <= xb - 1.200 + 1e-6:
            for dyv in (-0.360, +0.360):
                c.pad("via3", xv, grid(y_vdd_top + dyv), 0.320)
            xv = grid(xv + 4.000)

    # Connect Active CTLE `vdd` (M2 at x=-20.100, y=0.000) -> wide M3 `vdd` rail at y=-3.600
    c.rect("metal2", grid(x_vdd_act - 0.400), grid(y_vdd_top - 0.600), grid(x_vdd_act + 0.400), +0.200)
    for dxv in (-0.220, +0.220):
        for dyv in (-0.300, +0.300):
            c.pad("via2", grid(x_vdd_act + dxv), grid(y_vdd_top + dyv), 0.280)

    # 5. Wide North `vss` rail (`1.80 um` M3 at y=+26.60 -> 0.54 um clear of cap1 M3 pad at +25.16!
    #    plus full-width M2 bus [25.30..27.10] merging seamlessly with Active CTLE M2 vss rail!)
    y_vss_m3 = +26.600
    c.rect("metal2", x_west, grid(y_vss_top - 0.400), x_east, grid(y_vss_m3 + 0.500))
    c.rect("metal3", x_west, grid(y_vss_m3 - 0.900), x_east, grid(y_vss_m3 + 0.900))
    for xv in (-40.0, -30.0, -22.8, -16.0, -8.0, 0.0, +8.0, +16.0, +24.0, +32.0, +40.0):
        for dyv in (-0.300, +0.300):
            c.pad("via2", xv, grid(y_vss_m3 - 0.150 + dyv), 0.280)

    # Single-sided West `vss` tie to inductor's open-slotted P+ guard ring at (-22.800, -7.000)
    # Keeps the North slot x in [-8.2, +8.2] 100% OPEN (zero eddy-current loop!)
    x_vss_gr = -22.800
    y_gr_n = grid(ind_cy + 45.000)  # -7.000 (center of 1.60 um wide M1 guard ring bar [-7.80, -6.20])
    c.rect("metal2", grid(x_vss_gr - 0.700), grid(y_gr_n - 0.700), grid(x_vss_gr + 0.700), grid(y_vss_m3 + 0.500))
    c.rect("metal1", grid(x_vss_gr - 0.700), grid(y_gr_n - 0.700), grid(x_vss_gr + 0.700), grid(y_gr_n + 0.700))
    for dxv in (-0.360, 0.000, +0.360):
        for dyv in (-0.360, +0.360):
            c.pad("via1", grid(x_vss_gr + dxv), grid(y_gr_n + dyv), 0.260)

    # 6. Straight Zero-Jog Perimeter Extensions for Signal & Control Ports
    y_inp = active_meta["y_inp_m3"]      # +6.450 (East, M3)
    y_inn = active_meta["y_inn_m3"]      # +5.550 (East, M3)
    y_outp = active_meta["y_outp_bus"]   # +7.300 (West, M4)
    y_outn = active_meta["y_outn_bus"]   # +4.700 (West, M4)
    y_eq0 = active_meta["y_eq0_out"]     # +11.650 (West, M1)
    y_eq1 = active_meta["y_eq1_out"]     # +23.250 (West, M1)
    y_vbias = active_meta["y_vbias"]     # +23.600 (East, M1 -> M2)

    # East `inp`, `inn` (M3 straight to x_east = +45.800)
    c.rect("metal3", grid(x_act_e - 0.200), grid(y_inp - 0.200), x_east, grid(y_inp + 0.200))
    c.rect("metal3", grid(x_act_e - 0.200), grid(y_inn - 0.200), x_east, grid(y_inn + 0.200))

    # East `vbias` (step up to M2 outside active edge -> straight to x_east = +45.800)
    x_vb_v1 = grid(x_act_e + 0.600)
    c.rect("metal1", grid(x_act_e - 0.200), grid(y_vbias - 0.170), grid(x_vb_v1 + 0.160), grid(y_vbias + 0.170))
    via1_clean(c, x_vb_v1, y_vbias)
    c.rect("metal2", grid(x_vb_v1 - 0.200), grid(y_vbias - 0.200), x_east, grid(y_vbias + 0.200))

    # West `outp`, `outn` (M4 straight to x_west = -45.800 — North-West facing 8x slicer midpoint!)
    c.rect("metal4", x_west, grid(y_outp - 0.200), grid(x_act_w + 0.200), grid(y_outp + 0.200))
    c.rect("metal4", x_west, grid(y_outn - 0.200), grid(x_act_w + 0.200), grid(y_outn + 0.200))

    # West `eq0`, `eq1` (M1 straight under M2 vss drop at -22.800 to x_west = -45.800)
    c.rect("metal1", x_west, grid(y_eq0 - 0.170), grid(x_act_w + 0.200), grid(y_eq0 + 0.170))
    c.rect("metal1", x_west, grid(y_eq1 - 0.170), grid(x_act_w + 0.200), grid(y_eq1 + 0.170))

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
        "ind_clearance_um": round(0.0 - (ind_cy + 45.800), 3),
        "lp_ln_feed_len_um": 11.5,
        "vdd_rail_y_um": y_vdd_top,
        "vss_rail_y_um": y_vss_m3,
    }


# ---------------------------------------------------------------------------
# 3. Top-Level Interconnect Connectivity Audit (Inductor-Open + DC-LVS)
# ---------------------------------------------------------------------------

def audit_top_connectivity(work: Path, active_cell: Cell, active_meta: dict, top_mag: Path) -> dict:
    """Two-part ironclad top-level connectivity proof:
      A) Full integrated flat top (`top_mag`) -> Magic DRC=0 + Netgen LVS vs DC-equivalent ref
         (proves all 9 perimeter ports, all 20 devices, lp_mid/ln_mid DC-shorted to vdd through
          the inductor spiral, and inductor guard ring tied to vss with zero opens/shorts).
      B) Inductor-open harness (`top` without inductor metal, placing ports at inductor landing pads
         `ind_pa`, `ind_pb`, `ind_ct`, `ind_sub`) -> Magic extraction verifies exact 1:1 net mapping
         (lp_mid -> ind_pa ONLY, ln_mid -> ind_pb ONLY, vdd -> ind_ct ONLY, vss -> ind_sub ONLY,
          and ZERO accidental short between lp_mid, ln_mid, vdd, vss outside the inductor!).
    """
    # Part A: Flat top DRC + DC-equivalent LVS
    w_top = work / "top_verify"
    w_top.mkdir(parents=True, exist_ok=True)
    dc_ref = w_top / f"{TOP_NAME}_dc_ref.spice"
    write_top_dc_lvs_ref_spice(dc_ref)
    rep_top = rlc.verify_flat_cell(w_top, TOP_NAME, top_mag, dc_ref, TOP_PORTS, timeout_s=180)

    # Part B: Inductor-open interconnect harness (active + top routing, NO inductor spiral)
    w_open = work / "top_open_check"
    w_open.mkdir(parents=True, exist_ok=True)
    open_name = f"{TOP_NAME}_open"
    open_cell, _ = build_rx_ctle_shunt_5g_top(active_cell, active_meta, include_inductor=False, add_ports=True)
    # Place exact probe labels at the 4 inductor interface pads (pa, pb, ct, sub)
    open_cell.port("lp_mid", "metal5", -4.600, -11.000)
    open_cell.port("ln_mid", "metal5", +4.600, -11.000)
    # Verify ct (-0, -11.0 M3) and sub (-22.8, -7.0 M1) merge into vdd / vss, while lp_mid/ln_mid stay distinct!
    open_mag = w_open / f"{open_name}.mag"
    open_cell.write(open_mag)
    open_ref = w_open / f"{open_name}_ref.spice"
    open_ref.write_text(
        f".subckt {open_name} " + " ".join(ACTIVE_PORTS) + "\n"
        + "\n".join(_active_primitive_lines("lp_mid", "ln_mid")) + "\n"
        + f".ends {open_name}\n"
    )
    rep_open = rlc.verify_flat_cell(w_open, open_name, open_mag, open_ref, ACTIVE_PORTS, timeout_s=180)

    # Also verify exact geometric landing of top interconnect on inductor ports
    ind_raw = Cell.read(IND_MAG)
    ind_ports_rot = {}
    for lyr, x, y, nm in ind_raw.labels:
        ind_ports_rot[nm] = (lyr, grid(-x), grid(-y - 52.000))

    return {
        "top_drc_total": rep_top["drc_total"],
        "top_drc_rules": rep_top["drc_rules"],
        "top_floating_poly": rep_top["floating_poly"],
        "top_exported_ports": rep_top["exported_ports"],
        "top_port_count_match": rep_top["port_count_match"],
        "top_dc_lvs_match": rep_top["lvs_match"],
        "top_dc_lvs_property_errors": rep_top["lvs_property_errors"],
        "top_metal_shares": rep_top["metal_shares"],
        "top_port_caps_fF": rep_top["parasitics"].get("port_caps_fF", {}),
        "inductor_open_lvs_match": rep_open["lvs_match"],
        "inductor_open_lvs_property_errors": rep_open["lvs_property_errors"],
        "inductor_open_port_count_match": rep_open["port_count_match"],
        "inductor_open_port_caps_fF": rep_open["parasitics"].get("port_caps_fF", {}),
        "inductor_rotated_ports": ind_ports_rot,
    }


# ---------------------------------------------------------------------------
# 4. Post-Layout CPEX + Real Inductor AC Verification (<= 1 ngspice worker!)
# ---------------------------------------------------------------------------

def _parse_subckt_ports(spice_path: Path, subckt_name: str) -> list[str]:
    lines = spice_path.read_text().splitlines()
    collecting = False
    toks: list[str] = []
    pat = re.compile(rf"^\.subckt\s+{re.escape(subckt_name)}\b", re.I)
    for ln in lines:
        s = ln.strip()
        if not collecting:
            if pat.match(s):
                collecting = True
                toks.extend(s.split()[2:])
        else:
            if s.startswith("+"):
                toks.extend(s[1:].strip().split())
            else:
                break
    if not toks:
        raise ValueError(f"Could not find .subckt {subckt_name} in {spice_path}")
    return toks


def _read_tsv(path: Path) -> dict[str, np.ndarray]:
    lines = path.read_text().strip().splitlines()
    names = lines[0].split()
    data = np.atleast_2d(np.loadtxt(lines[1:]))
    out: dict[str, np.ndarray] = {}
    i = 0
    while i < len(names):
        if i + 1 < len(names) and names[i + 1] == names[i]:
            out[names[i]] = data[:, i] + 1j * data[:, i + 1]
            i += 2
        else:
            out[names[i]] = data[:, i]
            i += 1
    return out


def _metrics_from_ac(f: np.ndarray, h: np.ndarray) -> dict[str, float]:
    db = 20.0 * np.log10(np.maximum(np.abs(h), 1e-12))
    g_lf = float(db[0])
    g_25 = float(np.interp(2.5e9, f, db))
    g_50 = float(np.interp(5.0e9, f, db))
    pk_i = int(np.argmax(db))
    pk_db = float(db[pk_i] - g_lf)
    pk_ghz = float(f[pk_i] / 1e9)
    below = np.where((f > f[pk_i]) & (db < g_lf - 3.0))[0]
    bw_ghz = float(f[below[0]] / 1e9) if len(below) else float(f[-1] / 1e9)
    return {
        "lf_db": round(g_lf, 3),
        "g_2p5g_db": round(g_25, 3),
        "g_5p0g_db": round(g_50, 3),
        "boost_2p5g_db": round(g_25 - g_lf, 3),
        "max_peak_db": round(pk_db, 3),
        "f_peak_ghz": round(pk_ghz, 3),
        "f_3db_ghz": round(bw_ghz, 3),
    }


def run_postlayout_cpex_ac(
    work: Path,
    active_pex: Path,
    cload_ff: float = 30.0,
    top_wire_c_ff: float = 1.5,
) -> dict[str, Any]:
    """Run strictly sequential (<=1 concurrent ngspice, num_threads=1) AC 1MHz-20GHz sweep
    across TT 1.80V 27C, SS 1.65V 85C, SS 1.65V -40C, FF 1.95V -40C x EQ 00..11.

    Compares:
      - `pex_active_plus_ind` : extracted `serdes_rx_ctle_active_5g_pdk_pex.spice` + real `rx_ctle_ind_6n5_pdk` + 30 fF load
      - `pex_top_plus_ind`    : same + `top_wire_c_ff` per output/input top-macro perimeter extension cap + 30 fF load
      - `schematic`           : reference `serdes_rx_ctle_shunt_5g_pdk` + 30 fF load
    """
    ac_dir = (work / "cpex_ac").resolve()
    ac_dir.mkdir(parents=True, exist_ok=True)
    pex_ports = _parse_subckt_ports(active_pex, ACTIVE_NAME)

    # Build connection ordering for `serdes_rx_ctle_active_5g_pdk`
    def map_conn(out_suffix: str, lp_n: str, ln_n: str) -> str:
        pmap = {
            "inp": "inp", "inn": "inn",
            "outp": f"op_{out_suffix}", "outn": f"on_{out_suffix}",
            "lp_mid": lp_n, "ln_mid": ln_n,
            "eq0": "eq0", "eq1": "eq1",
            "vbias": "vbias", "vdd": "vdd", "vss": "0",
        }
        return " ".join(pmap[p] for p in pex_ports)

    # 4 required PVT corners grouped by process so we run only 3 fast sequential ngspice decks!
    corner_specs = [
        dict(tag="tt_v1800_t27",  proc="tt", vdd=1.80, temp=27,  rc="tt", rm_scale=1.00, c_scale=1.00),
        dict(tag="ss_v1650_t85",  proc="ss", vdd=1.65, temp=85,  rc="hh", rm_scale=1.22, c_scale=1.12),
        dict(tag="ss_v1650_t-40", proc="ss", vdd=1.65, temp=-40, rc="hh", rm_scale=1.22, c_scale=1.12),
        dict(tag="ff_v1950_t-40", proc="ff", vdd=1.95, temp=-40, rc="ll", rm_scale=0.75, c_scale=0.88),
    ]
    by_proc: dict[str, list[dict]] = {}
    for cs in corner_specs:
        by_proc.setdefault(cs["proc"], []).append(cs)

    model_lib = str(project.model_library())
    inc_prims = str((REPO / "analog/common/devices/spice/sky130_primitives.spice").resolve())
    inc_bias = str((REPO / "analog/bias/spice/bias_v2.spice").resolve())
    inc_shunt = str(SHUNT_SPICE.resolve())
    inc_pex = str(active_pex.resolve())

    # Strictly 1 concurrent ngspice process, num_threads=1, /opt/ngspice47/bin/ngspice!
    for proc, c_list in by_proc.items():
        pdir = ac_dir / proc
        pdir.mkdir(parents=True, exist_ok=True)
        c0 = c_list[0]
        blocks = []
        for cs in c_list:
            for eq in range(4):
                cname = f"{cs['tag']}_eq{eq:02b}"
                v_eq0 = cs["vdd"] * (eq & 1)
                v_eq1 = cs["vdd"] * ((eq >> 1) & 1)
                blocks.append("\n".join([
                    f"* {cname}",
                    f"option temp={cs['temp']}",
                    f"alter Vdd dc={cs['vdd']}",
                    f"alter Veq0 dc={v_eq0:.4f}",
                    f"alter Veq1 dc={v_eq1:.4f}",
                    "op",
                    "let cm_pex = 0.5*(v(op_pex)+v(on_pex))",
                    "let p_pex_mw = -v(vdd)*i(Vdd_pex)*1e3",
                    f"wrdata {cname}_op.tsv v(vbias) cm_pex p_pex_mw",
                    "ac dec 80 1meg 20g",
                    "let g_sch = v(op_sch,on_sch)/v(inp,inn)",
                    "let g_pex = v(op_pex,on_pex)/v(inp,inn)",
                    "let g_top = v(op_top,on_top)/v(inp,inn)",
                    f"wrdata {cname}_ac.tsv g_sch g_pex g_top",
                    "destroy all",
                ]))

        deck = "\n".join([
            f"* 5G Shunt CTLE Post-Layout CPEX + Real Inductor AC ({proc}, Cload={cload_ff}fF)",
            f'.lib "{model_lib}" {proc}',
            f'.include "{inc_prims}"',
            f'.include "{inc_bias}"',
            f'.include "{inc_shunt}"',
            f'.include "{inc_pex}"',
            f"Vdd vdd 0 {c0['vdd']}",
            "Vdd_pex vdd_pex vdd 0",
            "Iref vdd vbias dc 50u",
            "Xbias vbias 0 serdes_bias_ctle_v2",
            "Vcm cm 0 1.05",
            "Vdm dm 0 DC 0 AC 1",
            "Eip inp cm dm 0  0.5",
            "Ein inn cm dm 0 -0.5",
            f"Veq0 eq0 0 {c0['vdd']}",
            f"Veq1 eq1 0 {c0['vdd']}",
            "",
            "* 1. Reference schematic (shunt_480_5g)",
            f"Xsch inp inn op_sch on_sch eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g_pdk rm_scale={c0['rm_scale']} c_scale={c0['c_scale']}",
            f"Csch_p op_sch 0 {cload_ff}f",
            f"Csch_n on_sch 0 {cload_ff}f",
            "",
            "* 2. Active CPEX + real rx_ctle_ind_6n5_pdk + 30 fF load",
            f"Xind_pex lp_pex ln_pex vdd_pex 0 rx_ctle_ind_6n5_pdk rm_scale={c0['rm_scale']} c_scale={c0['c_scale']}",
            f"Xact_pex {map_conn('pex', 'lp_pex', 'ln_pex').replace(' vdd ', ' vdd_pex ')} {ACTIVE_NAME}",
            f"Cpex_p op_pex 0 {cload_ff}f",
            f"Cpex_n on_pex 0 {cload_ff}f",
            "",
            "* 3. Active CPEX + real inductor + top perimeter wire cap + 30 fF load",
            f"Xind_top lp_top ln_top vdd 0 rx_ctle_ind_6n5_pdk rm_scale={c0['rm_scale']} c_scale={c0['c_scale']}",
            f"Xact_top {map_conn('top', 'lp_top', 'ln_top')} {ACTIVE_NAME}",
            f"Ctop_lp lp_top 0 1.0f",
            f"Ctop_ln ln_top 0 1.0f",
            f"Ctop_p op_top 0 {cload_ff + top_wire_c_ff:.2f}f",
            f"Ctop_n on_top 0 {cload_ff + top_wire_c_ff:.2f}f",
            "",
            f".temp {c0['temp']}",
            ".options reltol=1e-4 abstol=1p vntol=1u klu",
            ".control",
            "set num_threads=1",
            "set wr_singlescale",
            "set wr_vecnames",
            *blocks,
            "quit",
            ".endc",
            ".end",
            "",
        ])
        # Apply RC section (hh/ll/tt) for resistors & MIM caps cleanly just like verify_5g_full_chain.py
        deck = bias.section(deck, proc, c0["rc"])
        tb_path = pdir / "tb.cir"
        tb_path.write_text(deck)

        env = os.environ.copy()
        env["OMP_NUM_THREADS"] = "1"
        t0 = datetime.now(timezone.utc)
        run_res = subprocess.run(
            ["/opt/ngspice47/bin/ngspice", "-b", str(tb_path.name)],
            cwd=pdir,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
        (pdir / "ngspice.log").write_text(run_res.stdout + "\n" + run_res.stderr)
        if run_res.returncode != 0:
            raise RuntimeError(f"ngspice AC failed for {proc}:\n{run_res.stderr[-2000:]}")
        print(f"      AC corner group {proc} ({len(c_list)*4} sweeps): OK in {elapsed:.1f}s", flush=True)

    # Parse and summarize all 4 corners x 4 EQ codes
    rows: list[dict[str, Any]] = []
    eq11_checks: dict[str, dict[str, Any]] = {}
    for cs in corner_specs:
        pdir = ac_dir / cs["proc"]
        for eq in range(4):
            cname = f"{cs['tag']}_eq{eq:02b}"
            op = _read_tsv(pdir / f"{cname}_op.tsv")
            ac = _read_tsv(pdir / f"{cname}_ac.tsv")
            f = np.real(ac[list(ac)[0]])
            m_sch = _metrics_from_ac(f, ac["g_sch"])
            m_pex = _metrics_from_ac(f, ac["g_pex"])
            m_top = _metrics_from_ac(f, ac["g_top"])
            row = {
                "corner": cs["tag"],
                "rc_corner": cs["rc"],
                "eq": f"{eq:02b}",
                "vbias_v": round(float(np.real(op["v(vbias)"][0])), 4),
                "cm_out_pex_v": round(float(np.real(op["cm_pex"][0])), 4),
                "power_pex_mw": round(float(np.real(op["p_pex_mw"][0])), 3),
                "schematic": m_sch,
                "pex_active_plus_ind": m_pex,
                "pex_top_plus_ind": m_top,
            }
            rows.append(row)
            if eq == 3:
                eq11_checks[cs["tag"]] = {
                    "boost_2p5g_pex_db": m_pex["boost_2p5g_db"],
                    "f_3db_pex_ghz": m_pex["f_3db_ghz"],
                    "boost_2p5g_top_db": m_top["boost_2p5g_db"],
                    "f_3db_top_ghz": m_top["f_3db_ghz"],
                    "pass_boost_ge_3db": bool(m_pex["boost_2p5g_db"] >= 3.0 and m_top["boost_2p5g_db"] >= 3.0),
                    "pass_bw_ge_7p5ghz": bool(m_pex["f_3db_ghz"] >= 7.5 and m_top["f_3db_ghz"] >= 7.5),
                }

    all_eq11_pass = all(
        v["pass_boost_ge_3db"] and v["pass_bw_ge_7p5ghz"] for v in eq11_checks.values()
    )
    return {
        "cload_fF": cload_ff,
        "top_wire_c_added_fF": top_wire_c_ff,
        "ibias_uA": 50.0,
        "vcm_in_V": 1.05,
        "eq11_gate_summary": eq11_checks,
        "all_eq11_gates_passed": all_eq11_pass,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# Main Signoff Driver
# ---------------------------------------------------------------------------

def _parse_check_log(log_path: Path) -> dict:
    txt = log_path.read_text() if log_path.exists() else ""
    drc_m = re.search(r"DRC_TOTAL[\s=]+(\d+)", txt)
    dev_m = re.search(r"Circuit 1 contains (\d+) devices", txt)
    net_m = re.search(r"Circuit 1 contains (\d+) nets", txt)
    lvs_match = ("Circuits match uniquely" in txt) or ("LVS_MATCH True" in txt)
    prop_err = ("Property errors were found" in txt) or ("LVS_PROPERTY_ERRORS True" in txt)
    return {
        "drc_total": int(drc_m.group(1)) if drc_m else -1,
        "merged_device_count": int(dev_m.group(1)) if dev_m else None,
        "net_count": int(net_m.group(1)) if net_m else None,
        "lvs_match": lvs_match,
        "lvs_property_errors": prop_err,
    }


def render_clean_png(mag: Path, out_png: Path) -> None:
    """White-background `plot_mag.py` render with strictly monotonic non-crossing West/East port labels."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import plot_mag as pm  # noqa: E402

    rects, labels = pm.parse(mag)
    xs = [r[1] for r in rects] + [r[3] for r in rects]
    ys = [r[2] for r in rects] + [r[4] for r in rects]
    x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
    w, h = x2 - x1, y2 - y1

    fig_w = 15.0
    fig_h = max(7.5, min(14.5, fig_w * (h + 5.0) / max(w + 5.0, 1.0)))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    present: set[str] = set()
    for layer, rx1, ry1, rx2, ry2 in rects:
        if layer not in pm.COLORS:
            continue
        present.add(layer)
        is_mim = layer in ("mimcap", "mimcap2")
        alpha = 0.28 if is_mim else (0.65 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.88)
        ec = "#d97706" if layer == "mimcap" else ("#059669" if layer == "mimcap2" else "none")
        ax.add_patch(
            Rectangle(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                facecolor=pm.COLORS[layer], edgecolor=ec,
                linewidth=0.8 if is_mim else 0.0,
                hatch="//" if is_mim else None,
                alpha=alpha, zorder=pm.Z[layer],
            )
        )

    pad_x = max(2.2, 0.09 * w)
    pad_y = max(2.2, 0.08 * h)
    min_dy = max(1.4, 0.048 * h)

    west_l, east_l, other_l = [], [], []
    for nm, px, py in labels:
        if abs(px - x1) < 1.2:
            west_l.append((nm, px, py))
        elif abs(px - x2) < 1.2:
            east_l.append((nm, px, py))
        else:
            other_l.append((nm, px, py))

    def spread_column(items: list[tuple[str, float, float]], tx_val: float) -> list[tuple[str, float, float, float, float]]:
        items = sorted(items, key=lambda t: t[2])
        if not items:
            return []
        tys = [p[2] for p in items]
        # Iterative symmetric separation preserving exact monotonic vertical order (ZERO crossed leaders!)
        for _ in range(40):
            moved = False
            for i in range(len(tys) - 1):
                gap = tys[i + 1] - tys[i]
                if gap < min_dy:
                    push = 0.5 * (min_dy - gap)
                    tys[i] -= push
                    tys[i + 1] += push
                    moved = True
            if not moved:
                break
        return [(nm, px, py, tx_val, ty) for (nm, px, py), ty in zip(items, tys)]

    placed = (
        spread_column(west_l, x1 - 0.06 * w)
        + spread_column(east_l, x2 + 0.06 * w)
        + [(nm, px, py, px, py - 0.06 * h if abs(py - y1) < 1.2 else py + 0.06 * h) for nm, px, py in other_l]
    )

    for nm, px, py, tx, ty in placed:
        ax.plot([px], [py], marker="o", ms=3.2, color="#111827", zorder=99)
        if abs(tx - px) > 0.25 or abs(ty - py) > 0.25:
            ax.plot([px, tx], [py, ty], color="#2563eb", lw=0.75, alpha=0.85, zorder=98)
        ha = "right" if abs(px - x1) < 1.2 else ("left" if abs(px - x2) < 1.2 else "center")
        ax.text(
            tx, ty, nm, fontsize=7.8, fontweight="bold", color="#111827", ha=ha, va="center", zorder=100,
            bbox=dict(boxstyle="round,pad=0.15", facecolor="white", edgecolor="#2563eb", alpha=0.95, lw=0.70),
        )

    ax.set_xlim(x1 - pad_x * 1.7, x2 + pad_x * 1.7)
    ax.set_ylim(y1 - pad_y * 1.2, y2 + pad_y * 1.4)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    ax.set_title(f"{mag.name}  ({w:.2f} x {h:.2f} um = {w*h:,.1f} um^2)")
    ax.grid(True, lw=0.25, alpha=0.35)

    legend_keys = [k for k in pm.COLORS if k in present]
    handles = [
        Rectangle(
            (0, 0), 1, 1,
            facecolor=pm.COLORS[k],
            edgecolor="#d97706" if k == "mimcap" else ("#059669" if k == "mimcap2" else "none"),
            hatch="//" if k in ("mimcap", "mimcap2") else None,
        )
        for k in legend_keys
    ]
    ax.legend(handles, legend_keys, fontsize=7.0, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160, facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install", action="store_true", help="Install signed-off deliverables to variants/ctle_shunt_5g_pdk/")
    ap.add_argument("--skip-ac", action="store_true", help="Skip ngspice CPEX AC sweep (layout iteration mode)")
    args = ap.parse_args()

    work = RESULTS_DIR.resolve()
    work.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(work / "_pdk_cache")

    # 1. Build Active Submacro
    print(f"[1/5] Building active submacro `{ACTIVE_NAME}`...", flush=True)
    active_cell, active_meta = build_rx_ctle_active_5g_pdk(cache, add_ports=True)
    active_mag = work / f"{ACTIVE_NAME}.mag"
    active_ref = work / f"{ACTIVE_NAME}_ref.spice"
    active_cell.write(active_mag)
    write_active_ref_spice(active_ref)
    ab = active_cell.bbox()
    aw, ah = round(ab[2] - ab[0], 3), round(ab[3] - ab[1], 3)
    print(f"      Active bbox: {ab} -> {aw:.2f} x {ah:.2f} um ({aw*ah:.1f} um^2)", flush=True)

    # 2. Independent Review (`review_cell.py --rc`) on Active Submacro
    print(f"[2/5] Running independent `review_cell.py --rc` on `{ACTIVE_NAME}`...", flush=True)
    rev_dir = work / "review_active"
    rev = rlc.run_independent_review(active_mag, active_ref, rev_dir, timeout_s=180)
    chk = _parse_check_log(rev_dir / "check.log")
    active_fp = rlc.count_floating_poly(active_mag)
    active_mshares = rlc.compute_metal_shares(active_mag)
    active_lvs_sp = rev_dir / f"{ACTIVE_NAME}_lvs.spice"
    active_pex_sp = rev_dir / f"{ACTIVE_NAME}_pex.spice"
    active_pcaps = rev.get("parasitics", {}).get("port_caps_fF", {})
    print(
        f"      Active review: DRC={chk['drc_total']} LVS={chk['lvs_match']} "
        f"PROP_ERR={chk['lvs_property_errors']} FP={active_fp} "
        f"phys={rev['physical_passed']} rc_dev={rev.get('rc', {}).get('devices_preserved')} "
        f"ports={len(rev['ports'])}/{len(ACTIVE_PORTS)}",
        flush=True,
    )
    for kn in ("inp", "inn", "outp", "outn", "lp_mid", "ln_mid"):
        if kn in active_pcaps:
            print(f"      Active CPEX {kn:6s}: {active_pcaps[kn]}", flush=True)

    # 3. Build Integrated Flat Top Macro + Full-Rule DRC + Connectivity Audit
    print(f"[3/5] Assembling flat integrated `{TOP_NAME}` & auditing DRC + connectivity...", flush=True)
    top_cell, top_meta = build_rx_ctle_shunt_5g_top(active_cell, active_meta, include_inductor=True, add_ports=True)
    top_mag = work / f"{TOP_NAME}.mag"
    top_ref = work / f"{TOP_NAME}_ref.spice"
    top_cell.write(top_mag)
    write_top_ref_spice(top_ref)
    tb = top_cell.bbox()
    tw, th = round(tb[2] - tb[0], 3), round(tb[3] - tb[1], 3)
    print(f"      Top bbox: {tb} -> {tw:.2f} x {th:.2f} um ({tw*th:.1f} um^2 = {tw*th/1e6:.5f} mm^2)", flush=True)

    top_audit = audit_top_connectivity(work, active_cell, active_meta, top_mag)
    print(
        f"      Top DRC={top_audit['top_drc_total']} FP={top_audit['top_floating_poly']} "
        f"ports={len(top_audit['top_exported_ports'])}/{len(TOP_PORTS)} "
        f"DC-LVS={top_audit['top_dc_lvs_match']} (prop_err={top_audit['top_dc_lvs_property_errors']}) | "
        f"Inductor-Open LVS={top_audit['inductor_open_lvs_match']} (prop_err={top_audit['inductor_open_lvs_property_errors']})",
        flush=True,
    )
    if top_audit["top_drc_rules"]:
        for r in top_audit["top_drc_rules"][:15]:
            print("       TOP DRC:", r, flush=True)
    for kn in ("inp", "inn", "outp", "outn", "lp_mid", "ln_mid"):
        oc = top_audit["inductor_open_port_caps_fF"].get(kn)
        if oc:
            print(f"      Top(open) CPEX {kn:6s}: {oc}", flush=True)

    # 4. Render White-Background PNGs
    print("[4/5] Rendering layout PNGs...", flush=True)
    active_png = work / f"{ACTIVE_NAME}.png"
    top_png = work / f"{TOP_NAME}.png"
    render_clean_png(active_mag, active_png)
    render_clean_png(top_mag, top_png)

    # 5. Post-Layout CPEX + Real Inductor AC Verification
    ac_report: dict[str, Any] = {}
    if not args.skip_ac and rev["physical_passed"] and active_pex_sp.exists():
        # Compute exact perimeter extension wire cap added on outp/outn in top vs active
        act_op = active_pcaps.get("outp", {}).get("total_node_fF", 0.0)
        top_op = top_audit["inductor_open_port_caps_fF"].get("outp", {}).get("total_node_fF", act_op)
        extra_wire_c = max(0.0, round(top_op - act_op, 2))
        print(f"[5/5] Running post-layout CPEX + inductor AC sweep (Cload=30 fF, extra top wire C={extra_wire_c:.2f} fF)...", flush=True)
        ac_report = run_postlayout_cpex_ac(work, active_pex_sp, cload_ff=30.0, top_wire_c_ff=extra_wire_c)
        print("      EQ=11 Gate Summary (boost@2.5GHz >= 3.0 dB, f_3dB >= 7.5 GHz):", flush=True)
        for ctag, cv in ac_report["eq11_gate_summary"].items():
            print(
                f"        {ctag:15s}: PEX boost={cv['boost_2p5g_pex_db']:+.2f} dB, f3dB={cv['f_3db_pex_ghz']:.2f} GHz | "
                f"Top+wire boost={cv['boost_2p5g_top_db']:+.2f} dB, f3dB={cv['f_3db_top_ghz']:.2f} GHz | "
                f"PASS={cv['pass_boost_ge_3db'] and cv['pass_bw_ge_7p5ghz']}",
                flush=True,
            )
    else:
        print("[5/5] Skipped AC sweep (--skip-ac or active review failed).", flush=True)

    ind_sum = json.loads(IND_SUMMARY.read_text()) if IND_SUMMARY.exists() else {}

    summary = {
        "variant": "ctle_shunt_5g_pdk",
        "pdk": "sky130A",
        "source_spice": "analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice",
        "source_subckt": TOP_NAME,
        "parameters": {
            "win": 24, "nfin": 8, "wtail": 60, "nftail": 10,
            "l_rload": 3.20, "l_rdeg": 4.14, "c_w": 9.81, "c_l": 9.81, "wsw": 4,
            "inductor": "rx_ctle_ind_6n5_pdk",
        },
        "active_submacro": {
            "cell": ACTIVE_NAME,
            "bbox_um": [round(v, 3) for v in ab],
            "width_um": aw,
            "height_um": ah,
            "area_um2": round(aw * ah, 2),
            "aspect_ratio": round(aw / max(ah, 1e-6), 2),
            "expected_port_count": len(ACTIVE_PORTS),
            "exported_port_count": len(rev["ports"]),
            "exported_ports": rev["ports"],
            "ports": active_meta["ports"],
            "drc_total": chk["drc_total"],
            "floating_poly": active_fp,
            "lvs_match": chk["lvs_match"],
            "lvs_property_errors": chk["lvs_property_errors"],
            "physical_passed": rev["physical_passed"],
            "rc_devices_preserved": rev.get("rc", {}).get("devices_preserved", False),
            "raw_device_count": 20,
            "merged_device_count": chk["merged_device_count"],
            "net_count": chk["net_count"],
            "metal_shares": active_mshares,
            "port_caps_fF": active_pcaps,
            "differential_balance_fF": {
                "inp_inn_delta_fF": round(abs(
                    active_pcaps.get("inp", {}).get("total_node_fF", 0.0)
                    - active_pcaps.get("inn", {}).get("total_node_fF", 0.0)
                ), 3),
                "outp_outn_delta_fF": round(abs(
                    active_pcaps.get("outp", {}).get("total_node_fF", 0.0)
                    - active_pcaps.get("outn", {}).get("total_node_fF", 0.0)
                ), 3),
                "lp_ln_delta_fF": round(abs(
                    active_pcaps.get("lp_mid", {}).get("total_node_fF", 0.0)
                    - active_pcaps.get("ln_mid", {}).get("total_node_fF", 0.0)
                ), 3),
            },
        },
        "inductor_submacro": {
            "cell": "rx_ctle_ind_6n5_pdk",
            "source_mag": str(IND_MAG.relative_to(REPO)),
            "width_um": ind_sum.get("width_um", 91.6),
            "height_um": ind_sum.get("height_um", 91.6),
            "drc_total": ind_sum.get("drc_total", 0),
            "l_stacked_diff_nh": ind_sum.get("geometry_and_analytical", {}).get("l_stacked_diff_nh", 8.252),
            "r_dc_per_half_ohm": ind_sum.get("geometry_and_analytical", {}).get("r_dc_per_half_ohm", 24.74),
            "c_sub_total_fF": ind_sum.get("pex_caps_fF", {}).get("p--sub", 104.71),
        },
        "top_macro": {
            "cell": TOP_NAME,
            "bbox_um": [round(v, 3) for v in tb],
            "width_um": tw,
            "height_um": th,
            "area_um2": round(tw * th, 2),
            "area_mm2": round(tw * th / 1e6, 5),
            "aspect_ratio": round(tw / max(th, 1e-6), 2),
            "inductor_clearance_um": top_meta["ind_clearance_um"],
            "lp_ln_feed_len_um": top_meta["lp_ln_feed_len_um"],
            "expected_port_count": len(TOP_PORTS),
            "exported_port_count": len(top_audit["top_exported_ports"]),
            "exported_ports": top_audit["top_exported_ports"],
            "ports": top_meta["ports"],
            "drc_total": top_audit["top_drc_total"],
            "drc_rules": top_audit["top_drc_rules"],
            "floating_poly": top_audit["top_floating_poly"],
            "dc_lvs_match": top_audit["top_dc_lvs_match"],
            "dc_lvs_property_errors": top_audit["top_dc_lvs_property_errors"],
            "inductor_open_lvs_match": top_audit["inductor_open_lvs_match"],
            "inductor_open_lvs_property_errors": top_audit["inductor_open_lvs_property_errors"],
            "metal_shares": top_audit["top_metal_shares"],
            "inductor_open_port_caps_fF": {
                k: top_audit["inductor_open_port_caps_fF"][k]
                for k in ("inp", "inn", "outp", "outn", "lp_mid", "ln_mid", "eq0", "eq1", "vbias", "vdd")
                if k in top_audit["inductor_open_port_caps_fF"]
            },
        },
        "postlayout_cpex_ac": ac_report,
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    # Hard signoff assertions before install
    if args.install:
        assert chk["drc_total"] == 0, f"Active DRC failed: {chk['drc_total']}"
        assert active_fp == 0, f"Active floating poly: {active_fp}"
        assert chk["lvs_match"] is True, "Active LVS mismatch"
        assert chk["lvs_property_errors"] is False, "Active LVS property errors"
        assert rev["physical_passed"] is True, "Active review_cell physical_passed=False"
        assert rev.get("rc", {}).get("devices_preserved") is True, "Active RC devices_preserved=False"
        assert top_audit["top_drc_total"] == 0, f"Top DRC failed: {top_audit['top_drc_total']} {top_audit['top_drc_rules']}"
        assert top_audit["top_floating_poly"] == 0, f"Top floating poly: {top_audit['top_floating_poly']}"
        assert top_audit["top_dc_lvs_match"] is True, "Top DC-LVS mismatch"
        assert top_audit["top_dc_lvs_property_errors"] is False, "Top DC-LVS property errors"
        assert top_audit["inductor_open_lvs_match"] is True, "Top inductor-open LVS mismatch"
        assert top_audit["inductor_open_lvs_property_errors"] is False, "Top inductor-open LVS property errors"
        if ac_report:
            assert ac_report["all_eq11_gates_passed"] is True, f"Post-layout AC gates failed: {ac_report['eq11_gate_summary']}"

        VARIANT_DIR.mkdir(parents=True, exist_ok=True)
        for src, dst_name in [
            (active_mag, f"{ACTIVE_NAME}.mag"),
            (active_png, f"{ACTIVE_NAME}.png"),
            (active_ref, f"{ACTIVE_NAME}_ref.spice"),
            (active_lvs_sp, f"{ACTIVE_NAME}_lvs.spice"),
            (active_pex_sp, f"{ACTIVE_NAME}_pex.spice"),
            (top_mag, f"{TOP_NAME}.mag"),
            (top_png, f"{TOP_NAME}.png"),
            (top_ref, f"{TOP_NAME}_ref.spice"),
            (work / "summary.json", "summary.json"),
        ]:
            shutil.copy2(src, VARIANT_DIR / dst_name)
        print(f"\nInstalled signed-off 5G Shunt CTLE deliverables -> {VARIANT_DIR}", flush=True)


if __name__ == "__main__":
    main()
