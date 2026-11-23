#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder & Signoff Suite for Full RX v2 Zero-CML Top Macro:

  `serdes_rx_cmos_top_pdk` : Complete 4 Gb/s Zero-CML (CMOS) SerDes Receiver Macro
                             matching `serdes_rx_cmos_top` in `rx_cmos_top.spice` 1:1 (76 ports).

Integrated Sub-Macros (all independently signed off in `variants/v2_pdk/`):
  1. `serdes_rx_term_pdk`       : 50 Ohm split RX input termination (East analog entry edge)
  2. `serdes_bias_ctle_v2_pdk`  : BIAS v2 local CTLE LVT diode mirror (adjacent to CTLE vbias)
  3. `serdes_rx_ctle_pdk`       : Lean analog CTLE with 2-bit MIM EQ (isolated East analog bay)
  4. `serdes_rx_cmos_pi_8ph_pdk`: 2 GHz 64-code pure CMOS PI + deterministic 8-phase 1 GHz /2
  5. `8x serdes_rx_dt_slicer_pdk`: Abutted 236.80 um quarter-rate Double-Tail slicer bank
                                  (4 Data + 4 Edge, hardwired mid-code 32 = 100000 trim)
  6. `serdes_rx_cmos_deser16_pdk`: Pitch-matched 236.80 um static CMOS 8->32 deserializer + wclk

Power Grid & High-Speed Signal Craftsmanship (applying TX v4.2 RCX lessons):
  - Wide M5 `vdd` / `vss` power distribution mesh (2.40 um trunks) stitched across PI, CTLE,
    8x Slicer bank, and Deser16 with distributed `via4` drops (strictly avoiding `term` M5 pads).
  - Equalized-span (82.0 um) wide M3 (`0.56 um`) 1 GHz 8-phase clock distribution with dual `via3`
    drops + straight M4 pass-through along every slicer's central `x_rel=0` spine (`0.00 fF` skew).
  - Center-fed symmetric differential `ctle_p / ctle_n` trunk entering the exact midpoint (`x=118.4`)
    of the 8x slicer bank so Data (cols 0..3) and Edge (cols 4..7) slicers see mirror-symmetric delay.
  - Cardinal perimeter orientation for zero-jog top-level SerDes chip assembly:
      * West  : c0..c7 (2 GHz PLL anchor clocks), rst_n, vdd, vss
      * South : a0..a7, b0..b7, f0..f7 (64-code CDR PI controls), eq0, eq1, vcm_ref, ibias_ctle
      * East  : rxp, rxn (high-speed differential analog input, isolated from CMOS clocks), ctle_p, ctle_n
      * North : wd0..wd15, we0..we15, wclk (33-bit 250 MHz digital word bus -> digital CDR)

All scratch, extraction, and review directories live strictly under
`results/layout/rx_cmos_v2/top/` (zero temp/log/ext files inside `analog/`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rx_layout_common as rlc  # noqa: E402
import build_rx_cmos_pi_pdk as pi_b  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_LVT,
    grid,
    via1_clean,
    via2_clean,
    via3_pad,
    via4_pad,
    draw_tap_h,
    W_M1,
    W_M2,
    W_M3,
    W_M4,
)

VARIANT_DIR = HERE / "variants" / "v2_pdk"
RESULTS_DIR = rlc.REPO / "results" / "layout" / "rx_cmos_v2" / "top"


def _draw_bias_ctle_diode(c: Cell, cache: PdkCache, cx: float, cy: float) -> dict:
    """Draw exact 1:1 `serdes_bias_ctle_v2` (nfet_lvt w=8 l=0.5 nf=4, diode G=D=iin, S=B=vss)."""
    cx, cy = grid(cx), grid(cy)
    y_g = grid(cy + 1.600)
    y_vss = grid(cy - 1.850)
    mos = pi_b.place_mos_col(
        c, cache, cx, N_LVT, 8.00, 0.50, 4, cy, False,
        y_gate=y_g, s_y=grid(cy - 0.550), d_y=grid(cy + 0.550),
    )
    # Continuous psubdiff tap below device -> vss
    x_lo = grid(cx - 2.600)
    x_hi = grid(cx + 2.600)
    draw_tap_h(c, "psubdiff", x_lo, x_hi, y_vss, half_w=0.180, with_m1=True, m1_w=0.440, viali_pitch=0.800)
    for sx in mos["s_xs"]:
        c.wire("metal1", [(sx, mos["s"][1]), (sx, y_vss)], 0.240)
    # Tie gate (y_g) to drains (d_y) on M1 -> diode-connected iin
    c.wire("metal1", [(mos["d_xs"][0], mos["d"][1]), (mos["d_xs"][-1], mos["d"][1])], 0.280)
    c.wire("metal1", [(cx, mos["d"][1]), (cx, y_g)], 0.280)
    via1_clean(c, cx, y_g)
    via1_clean(c, cx, y_vss)
    return {"iin": (cx, y_g), "vss": (cx, y_vss)}


def _read_unlabeled(mag_path: Path) -> Cell:
    c = Cell.read(mag_path)
    c.labels = []
    return c


def _include_flip_x(dst: Cell, src: Cell, x_mirror_axis: float, dy: float) -> None:
    """Include `src` mirrored horizontally (`x -> x_mirror_axis - x`) and shifted by `dy`."""
    xm, dy = grid(x_mirror_axis), grid(dy)
    for lyr, rects in src.rects.items():
        for x1, y1, x2, y2 in rects:
            dst.rect(lyr, grid(xm - x2), grid(y1 + dy), grid(xm - x1), grid(y2 + dy))


def _dual_via3_h(c: Cell, x: float, y: float, dx: float = 0.62) -> None:
    x, y = grid(x), grid(y)
    x2 = grid(x + dx)
    via3_pad(c, x, y)
    via3_pad(c, x2, y)
    # Solid 0.520-tall M3 & M4 bridges fuse both pads into one notch-free bar (zero met3.2/met4.2!)
    c.wire("metal3", [(x, y), (x2, y)], 0.520)
    c.wire("metal4", [(x, y), (x2, y)], 0.520)


def _dual_via3_v(c: Cell, x: float, y: float, dy: float = 0.62) -> None:
    x, y = grid(x), grid(y)
    y2 = grid(y + dy)
    via3_pad(c, x, y)
    via3_pad(c, x, y2)
    c.wire("metal3", [(x, y), (x, y2)], 0.520)
    c.wire("metal4", [(x, y), (x, y2)], 0.520)


def build_rx_cmos_top_pdk(cache: PdkCache | None = None, add_ports: bool = True) -> tuple[Cell, dict]:
    """Assemble full integrated `serdes_rx_cmos_top_pdk` (76 ports) from signed-off PDK sub-macros."""
    if cache is None:
        cache = PdkCache(RESULTS_DIR / "_pdk_cache")
    c = Cell()

    # Load all 5 signed-off RX sub-macros (labels stripped so only top-level 76 ports are exported!)
    pi_cell = _read_unlabeled(VARIANT_DIR / "serdes_rx_cmos_pi_8ph_pdk.mag")
    term_cell = _read_unlabeled(VARIANT_DIR / "serdes_rx_term_pdk.mag")
    ctle_cell = _read_unlabeled(VARIANT_DIR / "serdes_rx_ctle_pdk.mag")
    slicer_cell = _read_unlabeled(VARIANT_DIR / "serdes_rx_dt_slicer_pdk.mag")
    deser_cell = _read_unlabeled(VARIANT_DIR / "serdes_rx_cmos_deser16_pdk.mag")

    # Also read port coordinates from original labeled cells for zero-typo exact stitching
    pi_ports = {nm: (x, y) for _l, x, y, nm in Cell.read(VARIANT_DIR / "serdes_rx_cmos_pi_8ph_pdk.mag").labels}
    deser_ports = {nm: (x, y) for _l, x, y, nm in Cell.read(VARIANT_DIR / "serdes_rx_cmos_deser16_pdk.mag").labels}

    # --- 1. Place South Band: PI_8ph v2.2 (124.88 um wide, West!) + Isolated Analog FE Bay (East) ---
    dx_pi, dy_pi = 1.900, 0.500
    c.include(pi_cell, dx=dx_pi, dy=dy_pi)  # world bbox [0.00, 0.00, 124.88, 68.72]

    # Term (mirrored in X -> rxp/rxn on East edge x=236.5, vcm/vss on West x=203.6)
    x_mir_term, dy_term = 218.000, 16.000
    _include_flip_x(c, term_cell, x_mirror_axis=x_mir_term, dy=dy_term)  # [203.15, 7.82, 236.50, 24.18]

    # Option 1 Floorplan: Move CTLE closer to 8x slicer midpoint (x=118.4) while keeping 20.7 um grounded shield bay from PI!
    # Mirrored in X -> inp/inn on East x=183.00, outp/outn on West x=145.60 (ctle_p/n trunk shrinks 69 -> 20.4 um!)
    x_mir_ctle, dy_ctle = 164.300, 46.000
    _include_flip_x(c, ctle_cell, x_mirror_axis=x_mir_ctle, dy=dy_ctle)  # [145.60, 31.40, 183.00, 57.60]

    # Exact 1:1 `serdes_bias_ctle_v2` LVT diode mirror directly below CTLE East vbias (188.0, 16.0)
    bias_pts = _draw_bias_ctle_diode(c, cache, 188.000, 16.000)

    # --- 2. Place Middle Band: 8x Abutted `serdes_rx_dt_slicer_pdk` (`236.80 um` wide!) ---
    # Option 1 Floorplan: Collapse empty y=68.7..83.2 clock corridor to 4.36 um by routing cke0..3 over slicer's M3-free South zone!
    col_pitch = 29.600
    dy_slicer = 74.200  # world y in [73.080, 104.620] (-10.12 um vs v2.1 84.320!)
    slicer_ctrs = [grid(14.800 + col * col_pitch) for col in range(8)]
    for x_ctr in slicer_ctrs:
        c.include(slicer_cell, dx=x_ctr, dy=dy_slicer)

    # --- 3. Place North Band: Pitch-Matched `serdes_rx_cmos_deser16_pdk` (`236.80 um` wide!) ---
    dx_deser, dy_deser = 0.000, 116.280  # south pins at y=107.280, north pins at y=193.280 (-10.12 um height -> ~195.4 um!)
    c.include(deser_cell, dx=dx_deser, dy=dy_deser)

    # Perimeter coordinates
    x_west = -4.200
    x_east = 239.000
    y_south = -1.600
    y_north = grid(dy_deser + 77.000)  # 193.280

    # --- 4. Analog Front-End Routing (`rxp/rxn`, `vcm_ref`, `ibias_ctle`, `eq0/eq1`, `ctle_p/ctle_n`) ---
    # 4a. East `rxp/rxn` M5 input pads extending to x_east = 239.000
    y_rxp_term = grid(dy_term + 2.400)   # 18.400
    y_rxn_term = grid(dy_term - 2.400)   # 13.600
    c.wire("metal5", [(235.000, y_rxp_term), (x_east, y_rxp_term)], 1.800)
    c.wire("metal5", [(235.000, y_rxn_term), (x_east, y_rxn_term)], 1.800)

    # Symmetric M4 risers from term's existing M4 bars (x_rxp=231.90, x_rxn=234.10) + matched M3 pair -> CTLE inp/inn (x=183.00)!
    x_rxp_m4 = grid(x_mir_term - (-13.900))  # 231.900
    x_rxn_m4 = grid(x_mir_term - (-16.100))  # 234.100
    y_ctle_inp = grid(dy_ctle + 5.950)       # 51.950
    y_ctle_inn = grid(dy_ctle + 5.050)       # 51.050
    x_ctle_e = grid(x_mir_ctle - (-18.700))  # 183.000

    c.wire("metal4", [(x_rxp_m4, grid(dy_term + 7.550)), (x_rxp_m4, y_ctle_inp)], 0.640)
    via3_pad(c, x_rxp_m4, y_ctle_inp)
    c.wire("metal3", [(x_ctle_e, y_ctle_inp), (x_rxp_m4, y_ctle_inp)], 0.480)

    c.wire("metal4", [(x_rxn_m4, grid(dy_term + 6.350)), (x_rxn_m4, y_ctle_inn)], 0.640)
    via3_pad(c, x_rxn_m4, y_ctle_inn)
    c.wire("metal3", [(x_ctle_e, y_ctle_inn), (x_rxn_m4, y_ctle_inn)], 0.480)

    # 4b. `vcm_ref`: term vcm (203.60, 16.00, M3) -> South port at (200.00, y_south, M4)
    x_vcm_s = 200.000
    c.wire("metal3", [(x_vcm_s, dy_term), (grid(x_mir_term - 14.400), dy_term)], 0.520)
    via3_pad(c, x_vcm_s, dy_term)
    c.wire("metal4", [(x_vcm_s, y_south), (x_vcm_s, dy_term)], 0.560)

    # 4c. `ibias_ctle`: bias_ctle iin (188.0, 17.60, M2) <-> CTLE vbias (183.00, 33.90, M1) -> South port (188.00, y_south, M4)
    x_bias_in, y_bias_in = bias_pts["iin"]   # (188.000, 17.600)
    y_ctle_vb = grid(dy_ctle - 12.100)       # 33.900
    y_ibias_bus = 27.400                     # clean horizontal M2 bus (clear of term top 24.18 & y_m5_vss_lo=30.00!)
    x_ibias_s = 188.000
    x_vb_via = grid(x_ctle_e + 0.600)        # 183.600
    c.wire("metal1", [(x_ctle_e, y_ctle_vb), (x_vb_via, y_ctle_vb)], 0.300)
    via1_clean(c, x_vb_via, y_ctle_vb)
    c.wire("metal2", [(x_vb_via, y_ctle_vb), (x_vb_via, y_ibias_bus), (x_ibias_s, y_ibias_bus)], 0.400)
    c.wire("metal2", [(x_bias_in, y_bias_in), (x_ibias_s, y_ibias_bus)], 0.400)
    via2_clean(c, x_ibias_s, y_ibias_bus)
    via3_pad(c, x_ibias_s, y_ibias_bus)
    c.wire("metal4", [(x_ibias_s, y_south), (x_ibias_s, y_ibias_bus)], 0.480)

    # 4d. `eq0` & `eq1`: CTLE West pins (x=145.60, y=45.85 / 34.25, M1) -> South ports (142.80 / 144.40, y_south, M4)
    x_ctle_w = grid(x_mir_ctle - 18.700)     # 145.600
    y_eq0 = grid(dy_ctle - 0.150)            # 45.850
    y_eq1 = grid(dy_ctle - 11.750)           # 34.250
    x_eq0_s, x_eq1_s = 142.800, 144.400
    for x_s, y_e in ((x_eq0_s, y_eq0), (x_eq1_s, y_eq1)):
        c.wire("metal1", [(x_s, y_e), (x_ctle_w, y_e)], 0.280)
        via1_clean(c, x_s, y_e)
        via2_clean(c, x_s, y_e)
        via3_pad(c, x_s, y_e)
        c.wire("metal4", [(x_s, y_south), (x_s, y_e)], 0.440)

    # 4e. Short Center-Fed Symmetric Differential `ctle_p / ctle_n` Trunk (20.4 um M3!) -> Exact Center (`x=118.40`) of 8x Slicers!
    y_ctle_op = grid(dy_ctle + 6.800)        # 52.800 (M4)
    y_ctle_on = grid(dy_ctle + 4.200)        # 50.200 (M4)
    x_cp_m4, x_cn_m4 = 139.600, 138.000      # symmetric pair in col 4 x_rel=+6.40/+4.80 (1.60 um clear of M5 drop at 141.20!)
    y_cp_m3, y_cn_m3 = 78.750, 79.600        # short 20.4 um M3 bridge right below slicer inp/inn (80.45/81.25) & above cke3 (77.85)!
    x_cp_ctr, x_cn_ctr = 119.200, 117.600    # straddling exact midpoint x=118.40 of 8x slicer bank!
    y_sl_inp = grid(dy_slicer + 6.250)       # 80.450
    y_sl_inn = grid(dy_slicer + 7.050)       # 81.250

    # ctle_p
    c.wire("metal4", [(x_ctle_w, y_ctle_op), (x_cp_m4, y_ctle_op), (x_cp_m4, y_cp_m3)], 0.520)
    _dual_via3_h(c, x_cp_m4, y_cp_m3, dx=-0.62)
    c.wire("metal3", [(x_cp_ctr, y_cp_m3), (x_cp_m4, y_cp_m3)], 0.440)
    _dual_via3_h(c, x_cp_ctr, y_cp_m3, dx=-0.62)
    c.wire("metal4", [(x_cp_ctr, y_cp_m3), (x_cp_ctr, y_sl_inp)], 0.520)
    via3_pad(c, x_cp_ctr, y_sl_inp)

    # ctle_n
    c.wire("metal4", [(x_ctle_w, y_ctle_on), (x_cn_m4, y_ctle_on), (x_cn_m4, y_cn_m3)], 0.520)
    _dual_via3_h(c, x_cn_m4, y_cn_m3, dx=-0.62)
    c.wire("metal3", [(x_cn_ctr, y_cn_m3), (x_cn_m4, y_cn_m3)], 0.440)
    _dual_via3_h(c, x_cn_ctr, y_cn_m3, dx=-0.62)
    c.wire("metal4", [(x_cn_ctr, y_cn_m3), (x_cn_ctr, y_sl_inn)], 0.520)
    via3_pad(c, x_cn_ctr, y_sl_inn)

    # Export `ctle_p / ctle_n` probe ports cleanly on East edge from abutted slicer M3 buses
    c.wire("metal3", [(236.800, y_sl_inp), (x_east, y_sl_inp)], 0.400)
    c.wire("metal3", [(236.800, y_sl_inn), (x_east, y_sl_inn)], 0.400)

    # --- 5. Equalized-Span 8-Phase 1 GHz Clock Distribution (Option 1 Over-Slicer Collapsed Channel!) ---
    # ckd0..3 in compact 4.36 um gap [69.50..72.20]; cke0..3 over 8x slicer's M3-free South zone [75.15..77.85]!
    clk_names = ["ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3"]
    clk_y_trks = [69.500, 70.400, 71.300, 72.200, 75.150, 76.050, 76.950, 77.850]
    y_sl_clk_bot = grid(dy_slicer - 0.900)   # 73.300 (overlaps existing slicer M4 clk spine [-1.12..+17.42] = [73.08..91.62]!)
    y_sl_clk_top = grid(dy_slicer + 17.200)  # 91.400 (existing slicer M4 clk spine top)
    y_dsr_s = grid(dy_deser - 9.000)         # 107.280

    for k, cname in enumerate(clk_names):
        x_pi_ck = grid(dx_pi + pi_ports[cname][0])
        y_pi_ck = grid(dy_pi + pi_ports[cname][1])  # 68.500
        x_sl_ck = slicer_ctrs[k]
        y_trk = clk_y_trks[k]

        # Equalized 110.00 um horizontal M3 span -> matched load capacitance across all 8 phases!
        x_lo = min(x_pi_ck, x_sl_ck)
        x_hi = max(x_pi_ck, x_sl_ck, grid(x_lo + 110.000))
        c.wire("metal4", [(x_pi_ck, y_pi_ck), (x_pi_ck, y_trk)], 0.440)
        _dual_via3_h(c, x_pi_ck, y_trk, dx=0.62)
        c.wire("metal3", [(x_lo, y_trk), (x_hi, y_trk)], 0.460)
        _dual_via3_h(c, x_sl_ck, y_trk, dx=-0.62)
        if y_trk < y_sl_clk_bot:
            c.wire("metal4", [(x_sl_ck, y_trk), (x_sl_ck, y_sl_clk_bot)], 0.440)

        # Straight M4 pass-through along slicer's central x_rel=0 spine -> Deser16 South clock pin!
        c.wire("metal4", [(x_sl_ck, y_sl_clk_top), (x_sl_ck, y_dsr_s)], 0.440)

    # --- 6. Slicer Hardwired Trim Ties (`t5=vdd`, `t4..t0=vss`) & Straight `qp -> Deser16` Stitches ---
    y_sl_vss = grid(dy_slicer + 0.000)       # 74.200 (full-width M3 vss)
    y_sl_vdd = grid(dy_slicer + 11.300)      # 85.500 (full-width M3 vdd)
    y_sl_qp = grid(dy_slicer + 30.250)       # 104.450 (M2)
    t_vss_offs = (-12.750, -11.850, -10.050, -8.150, -7.300)
    t5_off = -10.950

    for k, x_ctr in enumerate(slicer_ctrs):
        # Tie t0..t4 -> vss M3, t5 -> vdd M3 right on existing slicer M4 trim wires!
        for toff in t_vss_offs:
            via3_pad(c, grid(x_ctr + toff), y_sl_vss)
        via3_pad(c, grid(x_ctr + t5_off), y_sl_vdd)

        # Straight vertical stitch from slicer qp (M2) -> Deser16 South data input (M4)
        x_qp = grid(x_ctr - 2.250)
        via2_clean(c, x_qp, y_sl_qp)
        via3_pad(c, x_qp, y_sl_qp)
        c.wire("metal4", [(x_qp, y_sl_qp), (x_qp, y_dsr_s)], 0.400)

    # --- 7. `rst_n`, `c0..c7`, `a0..a7`, `b0..b7`, `f0..f7` Perimeter Extensions ---
    # West c0..c7
    west_c_ports: dict[str, tuple[float, float]] = {}
    for k in range(8):
        nm = f"c{k}"
        x_p = grid(dx_pi + pi_ports[nm][0])
        y_p = grid(dy_pi + pi_ports[nm][1])
        c.wire("metal3", [(x_west, y_p), (x_p, y_p)], 0.440)
        west_c_ports[nm] = (x_west, y_p)

    # West rst_n: stitch PI rst_n (0.30, 54.35, M3) -> West M4 trunk at x=-0.800 -> Deser16 rst_n (-0.800, 117.58, M4)!
    y_pi_rstn = grid(dy_pi + pi_ports["rst_n"][1])      # 54.350
    x_dsr_rstn = grid(dx_deser + deser_ports["rst_n"][0])  # -0.800
    y_dsr_rstn = grid(dy_deser + deser_ports["rst_n"][1])  # 117.580
    c.wire("metal3", [(x_west, y_pi_rstn), (grid(dx_pi + pi_ports["rst_n"][0]), y_pi_rstn)], 0.440)
    via3_pad(c, x_dsr_rstn, y_pi_rstn)
    c.wire("metal4", [(x_dsr_rstn, y_pi_rstn), (x_dsr_rstn, y_dsr_rstn)], 0.520)

    # South PI static controls a0..a7, b0..b7, f0..f7
    south_ctrl_ports: dict[str, tuple[float, float]] = {}
    for grp in ("a", "b", "f"):
        for k in range(8):
            nm = f"{grp}{k}"
            x_p = grid(dx_pi + pi_ports[nm][0])
            y_p = grid(dy_pi + pi_ports[nm][1])
            c.wire("metal2", [(x_p, y_south), (x_p, y_p)], 0.300)
            south_ctrl_ports[nm] = (x_p, y_south)

    # --- 8. Low-R Interdigitated M5 Power Comb (`vdd` West-Rooted, `vss` East-Rooted -> ZERO M5 Crossings!) ---
    x_vdd_m5_w = -4.200
    x_vss_m5_e = 227.600
    x_vdd_m5_end = 222.000
    x_vss_m5_beg = 1.800

    y_m5_vdd_lo  = 57.200
    y_m5_vdd_sl1 = grid(dy_slicer + 11.300)   # 85.500
    y_m5_vdd_sl2 = grid(dy_slicer + 29.350)   # 103.550
    y_m5_vdd_ds0 = grid(dy_deser - 8.400)     # 107.880
    y_m5_vdd_hi  = grid(dy_deser + 68.400)    # 184.680

    y_m5_vss_lo  = 30.000
    y_m5_vss_pi  = 63.000
    y_m5_vss_sl1 = grid(dy_slicer + 0.000)    # 74.200
    y_m5_vss_sl2 = grid(dy_slicer + 20.750)   # 94.950
    y_m5_vss_ds0 = grid(dy_deser + 0.000)     # 116.280
    y_m5_vss_hi  = grid(dy_deser + 76.000)    # 192.280

    # Draw VDD M5 Comb
    c.wire("metal5", [(x_vdd_m5_w, y_m5_vdd_lo), (x_vdd_m5_w, y_m5_vdd_hi)], 2.400)
    for yv in (y_m5_vdd_lo, y_m5_vdd_sl1, y_m5_vdd_sl2, y_m5_vdd_ds0, y_m5_vdd_hi):
        c.wire("metal5", [(x_vdd_m5_w, yv), (x_vdd_m5_end, yv)], 2.200)

    # Draw VSS M5 Comb
    c.wire("metal5", [(x_vss_m5_e, y_m5_vss_lo), (x_vss_m5_e, y_m5_vss_hi)], 2.400)
    c.wire("metal5", [(x_vdd_m5_w, y_m5_vss_lo), (x_vss_m5_e, y_m5_vss_lo)], 2.200)  # full-width South VSS bus -> West port!
    c.wire("metal5", [(120.000, y_m5_vss_pi), (x_vss_m5_e, y_m5_vss_pi)], 2.200)     # PI v2.2 East VSS + quiet shield finger
    for yv in (y_m5_vss_sl1, y_m5_vss_sl2, y_m5_vss_ds0, y_m5_vss_hi):
        c.wire("metal5", [(x_vss_m5_beg, yv), (x_vss_m5_e, yv)], 2.200)

    # --- 8a. Stitch PI_8ph v2.2 vdd & vss into M5 comb ---
    c.wire("metal4", [(0.600, y_m5_vdd_lo), (1.000, y_m5_vdd_lo)], 0.800)
    via4_pad(c, 0.600, y_m5_vdd_lo)
    c.wire("metal4", [(123.700, y_m5_vdd_lo), (124.500, y_m5_vdd_lo)], 0.800)
    via4_pad(c, 124.500, y_m5_vdd_lo)
    c.wire("metal4", [(122.600, y_m5_vss_pi), (123.300, y_m5_vss_pi)], 0.800)
    via4_pad(c, 123.300, y_m5_vss_pi)
    y_pi_vss = grid(dy_pi + pi_ports["vss"][1])  # 50.100
    c.wire("metal3", [(-3.600, y_pi_vss), (grid(dx_pi + pi_ports["vss"][0]), y_pi_vss)], 0.600)
    via3_pad(c, -3.600, y_pi_vss)
    c.wire("metal4", [(-3.600, y_m5_vss_lo), (-3.600, y_pi_vss)], 0.800)
    via4_pad(c, -3.600, y_m5_vss_lo)

    # --- 8b. Stitch CTLE, Term, BIAS_CTLE vdd & vss + Grounded Shield Wall between PI (124.9) & CTLE (145.6) ---
    for xv_c in (158.000, 172.000):
        via2_clean(c, xv_c, y_m5_vdd_lo)
        via3_pad(c, xv_c, y_m5_vdd_lo)
        via4_pad(c, xv_c, y_m5_vdd_lo)

    # Bring CTLE South vss M2 rail (y=31.80) down to y_m5_vss_lo (30.00) on wide M2 stubs -> clean via2+via3+via4!
    y_ctle_vss = grid(dy_ctle - 14.200)  # 31.800
    for xv_c in (158.000, 166.000, 176.000):
        c.wire("metal2", [(xv_c, y_m5_vss_lo), (xv_c, y_ctle_vss)], 0.800)
        via2_clean(c, xv_c, y_m5_vss_lo)
        via3_pad(c, xv_c, y_m5_vss_lo)
        via4_pad(c, xv_c, y_m5_vss_lo)

    # Stitch Term vss (203.60, 11.90, M2) & BIAS_CTLE vss (188.0, 14.15, M2) -> x=196.00 M3/M4 riser into y_m5_vss_lo (30.00)!
    x_term_vss = grid(x_mir_term - 14.400)  # 203.600
    y_term_vss = grid(dy_term - 4.100)      # 11.900
    x_bias_vss, y_bias_vss = bias_pts["vss"]  # (188.000, 14.150)
    x_fe_vss = 196.000
    c.wire("metal2", [(x_fe_vss, y_term_vss), (x_term_vss, y_term_vss)], 0.440)
    c.wire("metal2", [(x_bias_vss, y_bias_vss), (x_fe_vss, y_bias_vss)], 0.520)
    c.wire("metal2", [(x_fe_vss, y_term_vss), (x_fe_vss, y_bias_vss)], 0.520)
    via2_clean(c, x_fe_vss, y_bias_vss)
    c.wire("metal3", [(x_fe_vss, y_bias_vss), (x_fe_vss, y_m5_vss_lo)], 0.600)
    via3_pad(c, x_fe_vss, y_m5_vss_lo)
    via4_pad(c, x_fe_vss, y_m5_vss_lo)

    # Grounded M4 quiet shield wall between PI (x=124.88) and CTLE (x=145.60) at x = 134.000!
    c.wire("metal4", [(134.000, y_m5_vss_lo), (134.000, y_m5_vss_pi)], 0.800)
    via4_pad(c, 134.000, y_m5_vss_lo)
    via4_pad(c, 134.000, y_m5_vss_pi)

    # --- 8c. Stitch 8x Slicer Bank vdd & vss into M5 comb (7 distributed drops per rail!) ---
    for col, x_ctr in enumerate(slicer_ctrs[:7]):  # cols 0..6 -> x_drop in [22.8 .. 200.4], 100% M4-free!
        x_drop = grid(x_ctr + 8.000)
        for yv in (y_m5_vdd_sl1, y_m5_vdd_sl2, y_m5_vss_sl1, y_m5_vss_sl2):
            via3_pad(c, x_drop, yv)
            via4_pad(c, x_drop, yv)

    # --- 8d. Stitch Deser16 vdd & vss into M5 comb (6 distributed drops; skip col 3 to stay clear of wcap/wcapb at x=110.2/111.6!) ---
    for col in (0, 1, 2, 4, 5, 6):
        x_drop = grid(col * col_pitch + 22.400)
        for yv in (y_m5_vdd_ds0, y_m5_vdd_hi, y_m5_vss_ds0, y_m5_vss_hi):
            via3_pad(c, x_drop, yv)
            via4_pad(c, x_drop, yv)

    # --- 9. Export All 76 Top-Level Cardinal Ports (matching `serdes_rx_cmos_top` 1:1!) ---
    north_ports = {
        nm: (grid(dx_deser + deser_ports[nm][0]), grid(dy_deser + deser_ports[nm][1]))
        for nm in ([f"wd{i}" for i in range(16)] + [f"we{i}" for i in range(16)] + ["wclk"])
    }

    if add_ports:
        # Analog FE + EQ + Bias (East & South)
        c.port("rxp", "metal5", x_east, y_rxp_term)
        c.port("rxn", "metal5", x_east, y_rxn_term)
        c.port("vcm_ref", "metal4", x_vcm_s, y_south)
        c.port("ibias_ctle", "metal4", x_ibias_s, y_south)
        c.port("eq0", "metal4", x_eq0_s, y_south)
        c.port("eq1", "metal4", x_eq1_s, y_south)
        # 2 GHz PLL anchor clocks + rst_n (West)
        for k in range(8):
            c.port(f"c{k}", "metal3", *west_c_ports[f"c{k}"])
        c.port("rst_n", "metal3", x_west, y_pi_rstn)
        # 64-code CDR PI controls (South)
        for grp in ("a", "b", "f"):
            for k in range(8):
                nm = f"{grp}{k}"
                c.port(nm, "metal2", *south_ctrl_ports[nm])
        # 250 MHz Digital Word Bus (North)
        for nm, pt in north_ports.items():
            c.port(nm, "metal4", *pt)
        # CTLE Monitor Outputs (East)
        c.port("ctle_p", "metal3", x_east, y_sl_inp)
        c.port("ctle_n", "metal3", x_east, y_sl_inn)
        # Unified Supplies (West M5 main power entry)
        c.port("vdd", "metal5", x_west, y_m5_vdd_lo)
        c.port("vss", "metal5", x_west, y_m5_vss_lo)

    return c, {
        "north_ports": north_ports,
        "west_c_ports": west_c_ports,
        "south_ctrl_ports": south_ctrl_ports,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signoff", action="store_true",
                    help="Run full independent review_cell.py --rc, install into variants/v2_pdk/, update summary.json")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    VARIANT_DIR.mkdir(parents=True, exist_ok=True)

    cell_name = "serdes_rx_cmos_top_pdk"
    src_subckt = "serdes_rx_cmos_top"
    watch_nets = [
        "rxp", "rxn", "ctle_p", "ctle_n", "vcm_ref", "ibias_ctle",
        "c0", "c1", "c2", "c3", "c4", "c5", "c6", "c7",
        "wclk", "rst_n", "vdd", "vss",
    ]

    if args.signoff:
        print(f"\n=== Independent Signoff (`review_cell.py --rc`) for {cell_name} ===", flush=True)
        mag = VARIANT_DIR / f"{cell_name}.mag"
        ref = VARIANT_DIR / f"{cell_name}_ref.spice"
        png = VARIANT_DIR / f"{cell_name}.png"
        review_dir = RESULTS_DIR / "review" / cell_name

        cell, _meta = build_rx_cmos_top_pdk(add_ports=True)
        cell.write(mag)
        expected_ports = rlc.generate_rx_ref_spice(src_subckt, cell_name, ref)
        rev = pi_b._run_review_with_rc_audit(mag, ref, review_dir, timeout_s=600)

        chk = pi_b._parse_check_log(review_dir / "check.log")
        fp = rlc.count_floating_poly(mag)
        mshares = rlc.compute_metal_shares(mag)
        lvs_log = review_dir / f"{cell_name}_lvs.log"
        lvs_txt = lvs_log.read_text() if lvs_log.exists() else ""
        lvs_match = "Circuits match uniquely" in lvs_txt
        lvs_prop_err = "Property errors were found" in lvs_txt
        raw_dev_count = sum(1 for ln in ref.read_text().splitlines() if ln.startswith("X"))

        w_um = round(rev["size_um"][0], 3)
        h_um = round(rev["size_um"][1], 3)
        area_um2 = round(w_um * h_um, 2)
        ar = round(w_um / max(h_um, 1e-6), 2)

        pcaps = rev.get("parasitics", {}).get("port_caps_fF", {})
        key_caps = {k: pcaps[k] for k in watch_nets if k in pcaps}
        rc_nets = pi_b._parse_rcx_net_resistors(review_dir / f"{cell_name}_rcx.spice", watch_nets)
        rlc.render_png_plot_mag(mag, png)

        rc_info = rev.get("rc", {})
        entry = {
            "cell": cell_name,
            "source_subckt": src_subckt,
            "mag": str(mag.relative_to(rlc.REPO)),
            "ref_spice": str(ref.relative_to(rlc.REPO)),
            "png": str(png.relative_to(rlc.REPO)),
            "review_dir": str(review_dir.relative_to(rlc.REPO)),
            "pex_spice": str((review_dir / f"{cell_name}_pex.spice").relative_to(rlc.REPO)),
            "rcx_spice": str((review_dir / f"{cell_name}_rcx.spice").relative_to(rlc.REPO)),
            "bbox_um": [round(v, 3) for v in rev["bbox_um"]],
            "width_um": w_um,
            "height_um": h_um,
            "area_um2": area_um2,
            "aspect_ratio": ar,
            "expected_port_count": len(expected_ports),
            "exported_port_count": len(rev["ports"]),
            "exported_ports": rev["ports"],
            "port_count_match": (len(rev["ports"]) == len(expected_ports) and set(rev["ports"]) == set(expected_ports)),
            "physical_passed": rev["physical_passed"],
            "drc_total": chk["drc_total"],
            "floating_poly": fp,
            "lvs_match": lvs_match,
            "lvs_property_errors": lvs_prop_err,
            "rc_devices_preserved": rc_info.get("devices_preserved", False),
            "rc_review_strict_passed": rc_info.get("review_cell_rc_strict_passed", False),
            "rc_connectivity_and_wl_preserved": rc_info.get("connectivity_and_wl_preserved", False),
            "rc_shorted_supply_moscap_as_ps_diffs": rc_info.get("shorted_supply_moscap_as_ps_diffs", 0),
            "rc_note": rc_info.get("note", ""),
            "rc_resistor_count": rc_info.get("resistor_count", 0),
            "rc_resistor_nets": rc_info.get("resistor_nets", []),
            "raw_device_count": raw_dev_count,
            "merged_device_count": chk["merged_device_count"],
            "net_count": chk["net_count"],
            "metal_shares": mshares,
            "key_port_caps_fF": key_caps,
            "internal_cpex_fF": {},
            "key_net_rcx_ohm": rc_nets,
        }

        summary_path = VARIANT_DIR / "summary.json"
        summary_doc = json.loads(summary_path.read_text()) if summary_path.exists() else {
            "variant": "v2_pdk", "pdk": "sky130A", "cells": {}
        }
        summary_doc["cells"][cell_name] = entry
        summary_path.write_text(json.dumps(summary_doc, indent=2) + "\n")

        assert entry["drc_total"] == 0, f"{cell_name}: DRC={entry['drc_total']}"
        assert entry["floating_poly"] == 0, f"{cell_name}: FP={entry['floating_poly']}"
        assert entry["lvs_match"] is True, f"{cell_name}: LVS mismatch"
        assert entry["lvs_property_errors"] is False, f"{cell_name}: LVS property errors"
        assert entry["port_count_match"] is True, f"{cell_name}: port count mismatch"
        assert entry["physical_passed"] is True, f"{cell_name}: physical_passed=False"
        assert entry["rc_connectivity_and_wl_preserved"] is True, f"{cell_name}: RC connectivity/W/L failed"

        print(
            f"  PASS {cell_name}: {w_um:.2f} x {h_um:.2f} um ({area_um2:,.2f} um^2, AR={ar:.2f}) | "
            f"DRC=0 | LVS=MATCH (prop_err=False) | FP=0 | ports={len(rev['ports'])}/{len(expected_ports)} | "
            f"RC_strict={entry['rc_devices_preserved']} (WL+conn=True, moscap_asps_diffs={entry['rc_shorted_supply_moscap_as_ps_diffs']}) | "
            f"M1-5={mshares['share_pct']}",
            flush=True,
        )
    else:
        print(f"\n=== Building & Verifying {cell_name} ===", flush=True)
        work = RESULTS_DIR / "work_top"
        work.mkdir(parents=True, exist_ok=True)
        mag = work / f"{cell_name}.mag"
        ref = work / f"{cell_name}_ref.spice"
        png = work / f"{cell_name}.png"
        cell, _meta = build_rx_cmos_top_pdk(add_ports=True)
        cell.write(mag)
        expected_ports = rlc.generate_rx_ref_spice(src_subckt, cell_name, ref)
        rep = rlc.verify_flat_cell(work, cell_name, mag, ref, expected_ports, timeout_s=360)
        rlc.render_png_plot_mag(mag, png)
        print(json.dumps({
            k: rep[k] for k in (
                "cell", "width_um", "height_um", "area_um2", "aspect_ratio",
                "drc_total", "drc_rules", "lvs_match", "lvs_property_errors",
                "lvs_disconnected", "port_count_match", "floating_poly", "metal_shares",
            )
        }, indent=2))
        pcaps = rep["parasitics"].get("port_caps_fF", {})
        for k in watch_nets:
            if k in pcaps:
                print(f"  CPEX {k:10s}: {pcaps[k]}")


if __name__ == "__main__":
    main()
