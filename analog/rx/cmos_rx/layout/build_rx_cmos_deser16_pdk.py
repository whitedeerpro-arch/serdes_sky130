#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder & Signoff Suite for RX v2 CMOS Deserializer:

  `serdes_rx_cmos_deser16_pdk` : 4-phase 1 GHz -> 250 MHz 16-bit Data + 16-bit Edge
                                 static CMOS deserializer + Johnson /4 wclk generator.

Architecture & Floorplan Guarantees:
  - Pitch-matched to 8x `serdes_rx_dt_slicer_pdk` (`8 x 29.60 = 236.80 um` width!),
    100% bit-sliced so each lane (d0..d3, e0..e3) flows straight South -> North inside
    its own 29.60 um column with zero cross-column data wiring.
  - Strict 0.0% M5 usage (M1-M4 only) so M5 stays reserved for top-level power/shielding.
  - Low-R 2-bank 1 GHz clock distribution (`ck0a/ck0ba` centered on Bank A cols 0..3,
    `ck0b/ck0bb` centered on Bank B cols 4..7) + centered 250 MHz `wcap/wcapb` spine,
    wide M3 horizontal rails + wide M4 vertical spines + multi-via stacks.
  - Cardinal port orientation for zero-jog RX v2 top integration:
      * South : d0..d3, e0..e3 (exact slicer `qp` X-pitch), ckd0..3, cke0..3 (exact slicer `clk` X-pitch)
      * West  : rst_n, vdd, vss
      * North : wd0..wd15, we0..we15, wclk (clean 250 MHz digital word bus exit), vdd, vss
  - All temporary files, Magic/Netgen logs, `.ext`, `.spice`, `.sim` live strictly under
    `results/layout/rx_cmos_v2/deser16/` (zero scratch artifacts inside `analog/`).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rx_layout_common as rlc  # noqa: E402
import build_rx_cmos_pi_pdk as pi_b  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_STD,
    N_LVT,
    P_STD,
    W_M1,
    W_M2,
    W_M3,
    W_M4,
    grid,
    viali_pad,
    via1_clean,
    via2_clean,
    via3_pad,
    locali_v,
    draw_tap_h,
)

VARIANT_DIR = HERE / "variants" / "v2_pdk"
RESULTS_DIR = rlc.REPO / "results" / "layout" / "rx_cmos_v2" / "deser16"

COL_PITCH = 29.600
N_COLS = 8
MACRO_W = grid(N_COLS * COL_PITCH)  # 236.800 um
H_ROW = 7.600
H_ROW0 = 8.400


def _include_flip_y(dst: Cell, src: Cell, dx: float, y_mirror_axis: float) -> None:
    """Include `src` mirrored vertically (`y -> y_mirror_axis - y`) and shifted by `dx`."""
    dx, ym = grid(dx), grid(y_mirror_axis)
    for lyr, rects in src.rects.items():
        for x1, y1, x2, y2 in rects:
            dst.rect(lyr, grid(x1 + dx), grid(ym - y2), grid(x2 + dx), grid(ym - y1))
    for lyr, x, y, nm in src.labels:
        dst.labels.append((lyr, grid(x + dx), grid(ym - y), nm))


def _row_y_transform(row_idx: int, y_local: float) -> float:
    """Map local DFF Y `[0..H_ROW]` into world Y for row `row_idx` (1..10)."""
    if row_idx % 2 == 1:
        return grid((row_idx - 1) * H_ROW + y_local)
    return grid(row_idx * H_ROW - y_local)


def _dual_via2(c: Cell, x: float, y: float, dx: float = 0.0, dy: float = 0.0) -> None:
    """Place a single or dual via2 stack (for low-R clock/power drops)."""
    via2_clean(c, x, y)
    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
        via2_clean(c, grid(x + dx), grid(y + dy))


def _dual_via3(c: Cell, x: float, y: float, dx: float = 0.0, dy: float = 0.0) -> None:
    """Place a single or dual via3 stack (for low-R clock/power spine tees)."""
    via3_pad(c, x, y)
    if abs(dx) > 1e-6 or abs(dy) > 1e-6:
        via3_pad(c, grid(x + dx), grid(y + dy))


def _draw_big_inv(
    c: Cell,
    cache: PdkCache,
    cx: float,
    wn: float,
    wp: float,
    nfn: int,
    nfp: int,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
    x_in_side: int = -1,
) -> dict:
    """Draw a multi-finger CMOS inverter with low-R multi-via M1/M2 drain stitching."""
    cx = grid(cx)
    p_dir = 1 if y_vdd > y_p else -1
    n_dir = 1 if y_vss > y_n else -1
    hp = grid((wp / nfp) / 2.0)
    hn = grid((wn / nfn) / 2.0)
    sp_y = grid(y_p + p_dir * min(0.45, max(0.0, hp - 0.16)))
    dp_y = grid(y_p - p_dir * min(0.45, max(0.0, hp - 0.16)))
    sn_y = grid(y_n + n_dir * min(0.35, max(0.0, hn - 0.14)))
    dn_y = grid(y_n - n_dir * min(0.35, max(0.0, hn - 0.14)))

    pm = pi_b.place_mos_col(c, cache, cx, P_STD, wp, 0.15, nfp, y_p, True, y_g, sp_y, dp_y)
    nm = pi_b.place_mos_col(c, cache, cx, N_LVT, wn, 0.15, nfn, y_n, False, y_g, sn_y, dn_y)

    for sx in pm["s_xs"]:
        c.wire("metal1", [(sx, sp_y), (sx, y_vdd)], 0.240)
    for sx in nm["s_xs"]:
        c.wire("metal1", [(sx, sn_y), (sx, y_vss)], 0.240)

    # Gate escape to clear of PMOS multi-finger drains
    max_d_off = max(abs(x - cx) for x in pm["d_xs"] + nm["d_xs"])
    x_in = grid(cx + x_in_side * max(0.75, max_d_off + 0.55))
    c.wire("metal1", [(cx, y_g), (x_in, y_g)], W_M1)

    # Drain stitch on M2 (avoids gate M1 crossing cleanly!)
    x_out = grid(cx - x_in_side * max(0.55, max_d_off + 0.10))
    for dx_p in pm["d_xs"]:
        via1_clean(c, dx_p, dp_y)
    for dx_n in nm["d_xs"]:
        via1_clean(c, dx_n, dn_y)
    c.wire("metal2", [(pm["d_xs"][0], dp_y), (pm["d_xs"][-1], dp_y)], 0.320)
    c.wire("metal2", [(nm["d_xs"][0], dn_y), (nm["d_xs"][-1], dn_y)], 0.320)
    c.wire("metal2", [(pm["d_xs"][0], dp_y), (x_out, dp_y), (x_out, dn_y), (nm["d_xs"][0], dn_y)], 0.320)
    return {
        "in": (x_in, grid(y_g)),
        "out_m2": (x_out, grid(y_g)),
        "dp_y": dp_y,
        "dn_y": dn_y,
        "x_out": x_out,
    }


def _build_dsr_dff_cell(
    cache: PdkCache,
    is_250m: bool = False,
    swap_clk: bool = False,
) -> tuple[Cell, dict]:
    """Build a canonical unflipped `dsr_dff_1g` (or `dsr_dff_250m`) cell in local Y `[0 .. H_ROW]`.

    Layout coordinates (local):
      y_vss    = 0.000  (shared M1/M3 rail drawn by parent row)
      y_mid    = 0.650  (M2 NAND2 internal series NMOS stitch)
      y_m3_rst = 1.300  (parent M3 rst_n rail -> via2 drop from NAND2 rst_n gates)
      y_n      = 1.400  (NMOS diff center)
      y_m3_ck  = 2.150  (parent M3 ck rail)
      y_gn     = 2.550  (NMOS-only T-gate polycont)
      y_gc     = 3.100  (shared P+N gate polycont)
      y_gp     = 3.650  (PMOS-only T-gate polycont)
      y_m3_ckb = 3.950  (parent M3 ckb rail)
      y_m2_a   = 4.550  (M2 horizontal m1 / s1)
      y_m2_b   = 5.350  (M2 horizontal m2 / s2)
      y_p      = 5.750  (PMOS diff center)
      y_vdd    = 7.600  (shared M1/M3 rail drawn by parent row)

    Columns at uniform pitch 1.800 um (col 0 at x = 0.000):
      0: Xtg1   (d <-> m1)
      1: Xm2a   (m1 -> m2 / mid_m)
      2: Xm2b   (rst_n -> m2 / mid_m)
      3: Xm3    (m2 -> m3)
      4: Xtg2   (m3 <-> m1)
      5: Xtg3   (m2 <-> s1)
      6: Xsq    (s1 -> qi)
      7: Xsfba  (qi -> s2 / mid_s)
      8: Xsfbb  (rst_n -> s2 / mid_s)
      9: Xtg4   (s2 <-> s1)
     10: Xbq1   (s1 -> q)
     11: Xbq2   (q  -> qb)  [1g only]
    """
    c = Cell()
    y_vss = 0.000
    y_mid = 0.650
    y_m3_rst = 1.150
    y_n = 1.400
    y_m3_ck = 2.300
    y_gn = 2.550
    y_gc = 3.100
    y_gp = 3.650
    y_m3_ckb = 3.950
    y_m2_a = 4.550
    y_m2_b = 5.350
    y_p = 5.750
    y_vdd = H_ROW

    # Device models & sizes matching rx_cmos_deser16.spice 1:1
    if is_250m:
        n_mdl, p_mdl, l_dev = N_STD, P_STD, 0.18
        w_tg1 = (0.50, 1.00)
        w_m2 = (0.75, 1.00)
        w_m3 = (0.45, 0.90)
        w_tg2 = (0.45, 0.90)
        w_tg3 = (0.50, 1.00)
        w_sq = (0.55, 1.20)
        w_sfb = (0.70, 0.95)
        w_tg4 = (0.45, 0.90)
        w_bq1 = (0.75, 1.60)
        n_cols = 11
    else:
        n_mdl, p_mdl, l_dev = N_LVT, P_STD, 0.15
        w_tg1 = (0.65, 2.20)
        w_m2 = (1.00, 2.00)
        w_m3 = (0.45, 1.15)
        w_tg2 = (0.45, 1.05)
        w_tg3 = (0.65, 2.20)
        w_sq = (0.65, 1.65)
        w_sfb = (0.80, 1.40)
        w_tg4 = (0.45, 1.05)
        w_bq1 = (0.80, 2.40)
        w_bq2 = (0.55, 1.40)
        n_cols = 12

    pitch = 1.800
    xs = [grid(i * pitch) for i in range(n_cols)]

    def sd_ys(wn: float, wp: float) -> tuple[float, float, float, float]:
        hp = grid(wp / 2.0)
        hn = grid(wn / 2.0)
        sp_y = grid(y_p + min(0.42, max(0.0, hp - 0.16)))
        dp_y = grid(y_p - min(0.42, max(0.0, hp - 0.16)))
        sn_y = grid(y_n - min(0.28, max(0.0, hn - 0.14)))
        dn_y = grid(y_n + min(0.28, max(0.0, hn - 0.14)))
        return sp_y, dp_y, sn_y, dn_y

    def draw_tgate(cx: float, wn: float, wp: float, normal_pol: bool) -> dict:
        """Draw 1 T-gate at `cx`.

        `normal_pol=True` means gN=ck (y_m3_ck=2.15), gP=ckb (y_m3_ckb=3.95) when swap_clk=False.
        """
        sp_y, dp_y, sn_y, dn_y = sd_ys(wn, wp)
        pm = pi_b.place_mos_col(c, cache, cx, p_mdl, wp, l_dev, 1, y_p, True, y_gp, sp_y, dp_y)
        nm = pi_b.place_mos_col(c, cache, cx, n_mdl, wn, l_dev, 1, y_n, False, y_gn, sn_y, dn_y)

        # Left terminal (s) stitched on M1 at cx - 0.50; Right terminal (d) stitched on M1 at cx + 0.50
        x_l = grid(cx - 0.500)
        x_r = grid(cx + 0.500)
        c.rect("metal1", grid(x_l - 0.09), grid(sp_y - 0.145), grid(pm["s"][0] + 0.145), grid(sp_y + 0.145))
        c.rect("metal1", grid(x_l - 0.09), grid(sn_y - 0.145), grid(nm["s"][0] + 0.145), grid(sn_y + 0.145))
        c.wire("metal1", [(x_l, sp_y), (x_l, sn_y)], W_M1)

        c.rect("metal1", grid(pm["d"][0] - 0.145), grid(dp_y - 0.145), grid(x_r + 0.09), grid(dp_y + 0.145))
        c.rect("metal1", grid(nm["d"][0] - 0.145), grid(dn_y - 0.145), grid(x_r + 0.09), grid(dn_y + 0.145))
        c.wire("metal1", [(x_r, dp_y), (x_r, dn_y)], W_M1)

        # Clock drops onto parent M3 rails y_m3_ck (2.15) & y_m3_ckb (3.95)
        # Use 0.400 M2 width on straight via1->via2 links to match via2 M2 pad (zero met2.2 corner notch!)
        direct = normal_pol ^ swap_clk
        if direct:
            # gN (2.55) -> y_m3_ck (2.15), gP (3.65) -> y_m3_ckb (3.95) straight!
            via1_clean(c, cx, y_gn)
            c.wire("metal2", [(cx, y_gn), (cx, y_m3_ck)], 0.400)
            via2_clean(c, cx, y_m3_ck)
            via1_clean(c, cx, y_gp)
            c.wire("metal2", [(cx, y_gp), (cx, y_m3_ckb)], 0.400)
            via2_clean(c, cx, y_m3_ckb)
        else:
            # Cross gP (3.65) -> y_m3_ck (2.15) via cx - 0.50, gN (2.55) -> y_m3_ckb (3.95) via cx + 0.50!
            x_gp_v = grid(cx - 0.500)
            x_gn_v = grid(cx + 0.500)
            via1_clean(c, cx, y_gp)
            c.wire("metal2", [(cx, y_gp), (x_gp_v, y_gp), (x_gp_v, y_m3_ck)], W_M2)
            via2_clean(c, x_gp_v, y_m3_ck)
            via1_clean(c, cx, y_gn)
            c.wire("metal2", [(cx, y_gn), (x_gn_v, y_gn), (x_gn_v, y_m3_ckb)], W_M2)
            via2_clean(c, x_gn_v, y_m3_ckb)

        return {"l": (x_l, dp_y), "r": (x_r, dp_y), "sp_y": sp_y, "dp_y": dp_y, "sn_y": sn_y, "dn_y": dn_y}

    def draw_nand2(cx_a: float, cx_b: float, wn: float, wp: float) -> dict:
        """Draw 2-col NAND2: col A (gate=a, s_n=mid, d_p=d_n=y), col B (gate=rst_n, d_n=mid, s_n=vss, d_p=y)."""
        sp_y, dp_y, sn_y, dn_y = sd_ys(wn, wp)
        pa = pi_b.place_mos_col(c, cache, cx_a, p_mdl, wp, l_dev, 1, y_p, True, y_gc, sp_y, dp_y)
        na = pi_b.place_mos_col(c, cache, cx_a, n_mdl, wn, l_dev, 1, y_n, False, y_gc, sn_y, dn_y)
        pb = pi_b.place_mos_col(c, cache, cx_b, p_mdl, wp, l_dev, 1, y_p, True, y_gc, sp_y, dp_y)
        nb = pi_b.place_mos_col(c, cache, cx_b, n_mdl, wn, l_dev, 1, y_n, False, y_gc, sn_y, dn_y)

        # Power rail ties
        c.wire("metal1", [(pa["s"][0], sp_y), (pa["s"][0], y_vdd)], 0.220)
        c.wire("metal1", [(pb["s"][0], sp_y), (pb["s"][0], y_vdd)], 0.220)
        c.wire("metal1", [(nb["s"][0], sn_y), (nb["s"][0], y_vss)], 0.220)

        # Output `y` M1 stitch on col A right (cx_a + 0.50) from na.d up to y_m2_b, plus pb.d -> y_m2_b
        x_ya = grid(cx_a + 0.500)
        c.rect("metal1", grid(pa["d"][0] - 0.145), grid(dp_y - 0.145), grid(x_ya + 0.09), grid(dp_y + 0.145))
        c.rect("metal1", grid(na["d"][0] - 0.145), grid(dn_y - 0.145), grid(x_ya + 0.09), grid(dn_y + 0.145))
        c.wire("metal1", [(x_ya, dn_y), (x_ya, y_m2_b)], W_M1)
        x_yb = grid(cx_b + 0.500)
        c.rect("metal1", grid(pb["d"][0] - 0.145), grid(dp_y - 0.145), grid(x_yb + 0.09), grid(dp_y + 0.145))
        c.wire("metal1", [(x_yb, dp_y), (x_yb, y_m2_b)], W_M1)

        # Series NMOS `mid` = na.s (cx_a - 0.22, sn_y) -> nb.d (cx_b + 0.22, dn_y) on M2 at y_mid (0.650)
        x_nbd_m1 = grid(cx_b + 0.500)
        c.rect("metal1", grid(nb["d"][0] - 0.145), grid(dn_y - 0.145), grid(x_nbd_m1 + 0.09), grid(dn_y + 0.145))
        c.wire("metal1", [(x_nbd_m1, dn_y), (x_nbd_m1, y_mid)], W_M1)
        c.wire("metal1", [(na["s"][0], sn_y), (na["s"][0], y_mid)], W_M1)
        via1_clean(c, na["s"][0], y_mid)
        via1_clean(c, x_nbd_m1, y_mid)
        c.wire("metal2", [(na["s"][0], y_mid), (x_nbd_m1, y_mid)], W_M2)

        # Connect col B gate (`rst_n`) down on M2 to y_m3_rst (1.300) -> via2!
        via1_clean(c, cx_b, y_gc)
        c.wire("metal2", [(cx_b, y_gc), (cx_b, y_m3_rst)], W_M2)
        via2_clean(c, cx_b, y_m3_rst)

        return {"in_a": (cx_a, y_gc), "ya": (x_ya, y_m2_b), "yb": (x_yb, y_m2_b)}

    def draw_inv(cx: float, wn: float, wp: float) -> dict:
        return pi_b.draw_cmos_inv(
            c, cache, cx, wn, wp, n_mdl, p_mdl, l_dev, l_dev, 1, 1,
            y_p, y_n, y_gc, y_vdd, y_vss, y_out_m1=y_gc,
        )

    # --- Place all 11 (or 12) columns ---
    tg1 = draw_tgate(xs[0], *w_tg1, normal_pol=False)  # gN=ckb, gP=ck
    m2g = draw_nand2(xs[1], xs[2], *w_m2)
    m3i = draw_inv(xs[3], *w_m3)
    tg2 = draw_tgate(xs[4], *w_tg2, normal_pol=True)   # gN=ck, gP=ckb
    tg3 = draw_tgate(xs[5], *w_tg3, normal_pol=True)   # gN=ck, gP=ckb
    sqi = draw_inv(xs[6], *w_sq)
    sfb = draw_nand2(xs[7], xs[8], *w_sfb)
    tg4 = draw_tgate(xs[9], *w_tg4, normal_pol=False)  # gN=ckb, gP=ck
    bq1 = draw_inv(xs[10], *w_bq1)
    bq2 = draw_inv(xs[11], *w_bq2) if not is_250m else None

    # --- Internal M1 & Horizontal M2 Routing (ZERO M3 used inside DFF!) ---
    # 1. `m1` on M2 at y_m2_a (4.550): tg1.r (xs[0]+0.50) -> m2g.in_a (xs[1]) -> tg2.r (xs[4]+0.50)
    c.wire("metal1", [(tg1["r"][0], tg1["dn_y"]), (tg1["r"][0], y_m2_a)], W_M1)
    c.wire("metal1", [(m2g["in_a"][0], y_gc), (m2g["in_a"][0], y_m2_a)], W_M1)
    c.wire("metal1", [(tg2["r"][0], tg2["dn_y"]), (tg2["r"][0], y_m2_a)], W_M1)
    for px in (tg1["r"][0], m2g["in_a"][0], tg2["r"][0]):
        via1_clean(c, px, y_m2_a)
    c.wire("metal2", [(tg1["r"][0], y_m2_a), (tg2["r"][0], y_m2_a)], W_M2)

    # 2. `m2` on M2 at y_m2_b (5.350): m2g.ya -> m2g.yb -> m3i.in (jogged left to xs[3]-0.50) -> tg3.l (xs[5]-0.50)
    x_m3_in = grid(xs[3] - 0.500)
    c.wire("metal1", [(m3i["in"][0], y_gc), (x_m3_in, y_gc), (x_m3_in, y_m2_b)], W_M1)
    c.wire("metal1", [(tg3["l"][0], tg3["sp_y"]), (tg3["l"][0], y_m2_b)], W_M1)
    for px in (m2g["ya"][0], m2g["yb"][0], x_m3_in, tg3["l"][0]):
        via1_clean(c, px, y_m2_b)
    c.wire("metal2", [(m2g["ya"][0], y_m2_b), (tg3["l"][0], y_m2_b)], W_M2)

    # 3. `m3`: m3i.out (xs[3]+0.50) -> tg2.l (xs[4]-0.50) direct M1 horizontal at y_gc!
    c.wire("metal1", [(m3i["out"][0], y_gc), (tg2["l"][0], y_gc)], W_M1)

    # 4. `s1` on M2 at y_m2_a (4.550): tg3.r (xs[5]+0.50) -> sqi.in (xs[6]) -> tg4.r (xs[9]+0.50) -> bq1.in (xs[10])
    c.wire("metal1", [(tg3["r"][0], tg3["dn_y"]), (tg3["r"][0], y_m2_a)], W_M1)
    c.wire("metal1", [(sqi["in"][0], y_gc), (sqi["in"][0], y_m2_a)], W_M1)
    c.wire("metal1", [(tg4["r"][0], tg4["dn_y"]), (tg4["r"][0], y_m2_a)], W_M1)
    c.wire("metal1", [(bq1["in"][0], y_gc), (bq1["in"][0], y_m2_a)], W_M1)
    for px in (tg3["r"][0], sqi["in"][0], tg4["r"][0], bq1["in"][0]):
        via1_clean(c, px, y_m2_a)
    c.wire("metal2", [(tg3["r"][0], y_m2_a), (bq1["in"][0], y_m2_a)], W_M2)

    # 5. `qi`: sqi.out (xs[6]+0.50) -> sfb.in_a (xs[7]) direct M1 horizontal at y_gc!
    c.wire("metal1", [(sqi["out"][0], y_gc), (sfb["in_a"][0], y_gc)], W_M1)

    # 6. `s2` on M2 at y_m2_b (5.350): sfb.ya -> sfb.yb -> tg4.l (xs[9]-0.50)
    c.wire("metal1", [(tg4["l"][0], tg4["sp_y"]), (tg4["l"][0], y_m2_b)], W_M1)
    for px in (sfb["ya"][0], sfb["yb"][0], tg4["l"][0]):
        via1_clean(c, px, y_m2_b)
    c.wire("metal2", [(sfb["ya"][0], y_m2_b), (tg4["l"][0], y_m2_b)], W_M2)

    # 7. `q` -> `bq2.in` (1g only): direct M1 horizontal at y_gc!
    if bq2 is not None:
        c.wire("metal1", [(bq1["out"][0], y_gc), (bq2["in"][0], y_gc)], W_M1)

    # Clean M1/M2 escape coordinates for parent routing (y_pin_hi=6.650 keeps >= 0.175 um clear of sp_y viali stub!):
    y_pin_hi = 6.650
    c.wire("metal1", [(tg1["l"][0], tg1["sp_y"]), (tg1["l"][0], y_pin_hi)], W_M1)
    c.wire("metal1", [(bq1["out"][0], bq1["dp"][1]), (bq1["out"][0], y_pin_hi)], W_M1)
    if bq2 is not None:
        c.wire("metal1", [(bq2["out"][0], bq2["dp"][1]), (bq2["out"][0], y_pin_hi)], W_M1)

    meta = {
        "d": (tg1["l"][0], y_pin_hi),
        "q": (bq1["out"][0], y_pin_hi),
        "qb": (bq2["out"][0], y_pin_hi) if bq2 is not None else None,
    }
    return c, meta


def build_rx_cmos_deser16_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build complete pitch-matched `serdes_rx_cmos_deser16_pdk` (52 ports, 0.0% M5)."""
    c = Cell()

    # Pre-build the 3 canonical DFF cells (cached once, stamped 76 times!)
    dff1g_norm, dff1g_m = _build_dsr_dff_cell(cache, is_250m=False, swap_clk=False)
    dff1g_swap, _ = _build_dsr_dff_cell(cache, is_250m=False, swap_clk=True)
    dff250_norm, dff250_m = _build_dsr_dff_cell(cache, is_250m=True, swap_clk=False)

    x_left = 0.000
    x_right = MACRO_W  # 236.800
    y_bot = -H_ROW0    # -8.400
    y_top = grid(10 * H_ROW)  # 76.000

    # --- 1. Continuous Full-Width NWELL Bands + Power/Tap Rails (M1 + M3) ---
    # Row 0 NWELL (vdd at -8.400, PMOS at -6.100 -> max top -5.100)
    c.rect("nwell", grid(x_left - 0.60), grid(y_bot - 0.60), grid(x_right + 0.60), -4.550)
    # Rows 1..10 shared NWELL bands around vdd = 7.6, 22.8, 38.0, 53.2, 68.4
    vdd_ys = [y_bot] + [grid((2 * k - 1) * H_ROW) for k in range(1, 6)]  # -8.4, 7.6, 22.8, 38.0, 53.2, 68.4
    vss_ys = [grid((2 * k) * H_ROW) for k in range(6)]                    # 0.0, 15.2, 30.4, 45.6, 60.8, 76.0
    for yv in vdd_ys[1:]:
        c.rect("nwell", grid(x_left - 0.60), grid(yv - 3.650), grid(x_right + 0.60), grid(yv + 3.650))

    # Full-width M1 + tap + M3 power rails with dense periodic via1/via2 stitching!
    for yv in vdd_ys:
        draw_tap_h(c, "nsubdiff", x_left, x_right, yv, half_w=0.175, with_m1=True, m1_w=0.600, viali_pitch=1.200)
        c.wire("metal3", [(x_left, yv), (x_right, yv)], 0.640)
        xv = grid(x_left + 1.80)
        while xv <= x_right - 1.50 + 1e-6:
            via1_clean(c, xv, yv)
            via2_clean(c, xv, yv)
            xv = grid(xv + 7.40)

    for yv in vss_ys:
        draw_tap_h(c, "psubdiff", x_left, x_right, yv, half_w=0.175, with_m1=True, m1_w=0.600, viali_pitch=1.200)
        c.wire("metal3", [(x_left, yv), (x_right, yv)], 0.640)
        xv = grid(x_left + 0.60)
        while xv <= x_right - 0.50 + 1e-6:
            via1_clean(c, xv, yv)
            via2_clean(c, xv, yv)
            xv = grid(xv + 7.40)

    # 9 Full-Height Vertical M4 Power Straps (vss & vdd at every column boundary!)
    vss_strap_xs = [grid(col * COL_PITCH + 0.600) for col in range(N_COLS)] + [grid(x_right - 0.450)]
    vdd_strap_xs = [grid(col * COL_PITCH + 1.800) for col in range(N_COLS)]
    for xs_s in vss_strap_xs:
        c.wire("metal4", [(xs_s, y_bot), (xs_s, y_top)], 0.640)
        for yv in vss_ys:
            via3_pad(c, xs_s, yv)
    for xd_s in vdd_strap_xs:
        c.wire("metal4", [(xd_s, y_bot), (xd_s, y_top)], 0.640)
        for yv in vdd_ys:
            via3_pad(c, xd_s, yv)

    # --- 2. Row 0 (`y in [-8.400, 0.000]`): 1 GHz Clock Receiver, Bank A/B Drivers, 6 Dummies ---
    y_vdd0 = y_bot     # -8.400
    y_p0 = -6.100
    y_gc0 = -3.850
    y_n0 = -1.750
    y_vss0 = 0.000

    # 2a. 6x `dsr_clk_dummy` right at their slicer clock X-columns (ckd1, ckd3, cke0..3)
    #     Col k clock X = 14.80 + k * 29.60. Offset ckd1 dummy slightly to x=41.5 to leave x=44.4 clear for receiver!
    slicer_clk_xs = [grid(14.800 + col * COL_PITCH) for col in range(N_COLS)]
    slicer_qp_xs = [grid(12.550 + col * COL_PITCH) for col in range(N_COLS)]
    clk_port_names = ["ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3"]
    data_port_names = ["d0", "d1", "d2", "d3", "e0", "e1", "e2", "e3"]

    def draw_clk_dummy(cx: float) -> tuple[float, float]:
        cx = grid(cx)
        pm = pi_b.place_mos_col(c, cache, cx, P_STD, 4.80, 0.15, 2, y_p0, True, y_gc0, grid(y_p0 - 0.45), grid(y_p0 + 0.45))
        nm = pi_b.place_mos_col(c, cache, cx, N_LVT, 1.20, 0.15, 1, y_n0, False, y_gc0, grid(y_n0 + 0.25), grid(y_n0 - 0.25))
        for x_sd in pm["s_xs"] + pm["d_xs"]:
            c.wire("metal1", [(x_sd, pm["s"][1]), (x_sd, y_vdd0)], 0.220)
            c.wire("metal1", [(x_sd, pm["d"][1]), (x_sd, y_vdd0)], 0.220)
        for x_sd in nm["s_xs"] + nm["d_xs"]:
            c.wire("metal1", [(x_sd, nm["s"][1]), (x_sd, y_vss0)], 0.220)
            c.wire("metal1", [(x_sd, nm["d"][1]), (x_sd, y_vss0)], 0.220)
        return (cx, y_gc0)

    # Place dummies cleanly clear of the centered [79..158] 3-stage clock receiver + Bank A/B driver bay!
    dummy_cols = [1, 3, 4, 5, 6, 7]
    for col in dummy_cols:
        x_ck = slicer_clk_xs[col]
        if col == 3:
            x_dm = 76.500
        elif col == 4:
            x_dm = 160.200
        else:
            x_dm = x_ck
        dm_g = draw_clk_dummy(x_dm)
        via1_clean(c, dm_g[0], dm_g[1])
        if abs(x_dm - x_ck) > 0.01:
            # Route shifted dummy clock cleanly at y=-7.350 (clear of y_r0_ckd2=-6.40 and drv_a/b outputs!)
            y_dm_m3 = -7.350
            c.wire("metal2", [(dm_g[0], dm_g[1]), (dm_g[0], y_dm_m3)], W_M2)
            via2_clean(c, dm_g[0], y_dm_m3)
            c.wire("metal3", [(dm_g[0], y_dm_m3), (x_ck, y_dm_m3)], 0.340)
            via3_pad(c, x_ck, y_dm_m3)
            c.wire("metal4", [(x_ck, y_dm_m3), (x_ck, grid(y_bot - 0.600))], 0.480)
        else:
            via2_clean(c, dm_g[0], dm_g[1])
            via3_pad(c, x_ck, dm_g[1])
            c.wire("metal4", [(x_ck, dm_g[1]), (x_ck, grid(y_bot - 0.600))], 0.480)

    # 2b. Co-Located 3-Stage wp/wn=4.0 Center Clock Receiver + Bank A & Bank B Drivers ([79..158])
    #     Swapped Stage-1 inputs (rx_i0 takes ckd2 -> ck0_1; rx_i2 takes ckd0 -> ck2_1) keep exact polarity!
    rx_i0 = pi_b.draw_cmos_inv(c, cache, 115.650, 1.20, 4.80, N_LVT, P_STD, 0.15, 0.15, 1, 2, y_p0, y_n0, y_gc0, y_vdd0, y_vss0)
    rx_c1 = pi_b.draw_cmos_inv(c, cache, 117.550, 0.42, 1.40, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p0, y_n0, y_gc0, y_vdd0, y_vss0)
    rx_c2 = pi_b.draw_cmos_inv(c, cache, 119.450, 0.42, 1.40, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p0, y_n0, y_gc0, y_vdd0, y_vss0)
    rx_i2 = pi_b.draw_cmos_inv(c, cache, 121.350, 1.20, 4.80, N_LVT, P_STD, 0.15, 0.15, 1, 2, y_p0, y_n0, y_gc0, y_vdd0, y_vss0)

    # Equal-span M3 inputs for ckd0 (-> rx_i2) and ckd2 (-> rx_i0) -> exact matched wire C!
    y_r0_ckd0 = -5.350
    y_r0_ckd2 = -6.400
    c.wire("metal4", [(slicer_clk_xs[0], grid(y_bot - 0.600)), (slicer_clk_xs[0], y_r0_ckd0)], 0.480)
    via3_pad(c, slicer_clk_xs[0], y_r0_ckd0)
    c.wire("metal3", [(slicer_clk_xs[0], y_r0_ckd0), (rx_i2["in"][0], y_r0_ckd0)], 0.340)
    via2_clean(c, rx_i2["in"][0], y_r0_ckd0)
    via1_clean(c, rx_i2["in"][0], y_gc0)
    c.wire("metal2", [(rx_i2["in"][0], y_gc0), (rx_i2["in"][0], y_r0_ckd0)], W_M2)

    c.wire("metal4", [(slicer_clk_xs[2], grid(y_bot - 0.600)), (slicer_clk_xs[2], y_r0_ckd2)], 0.480)
    via3_pad(c, slicer_clk_xs[2], y_r0_ckd2)
    c.wire("metal3", [(20.500, y_r0_ckd2), (rx_i0["in"][0], y_r0_ckd2)], 0.340)
    via2_clean(c, rx_i0["in"][0], y_r0_ckd2)
    via1_clean(c, rx_i0["in"][0], y_gc0)
    c.wire("metal2", [(rx_i0["in"][0], y_gc0), (rx_i0["in"][0], y_r0_ckd2)], W_M2)

    # M3 trunks carrying ck0_1 (from rx_i0) and ck2_1 (from rx_i2) to Bank A/B Stage-2 pre-drivers!
    y_1b_0 = -2.350  # M3 horizontal trunk for ck0_1
    y_1b_2 = -1.200  # M3 horizontal trunk for ck2_1
    for pt_x, pt_y in (rx_i0["out"], rx_c1["in"], rx_c2["out"]):
        via1_clean(c, pt_x, pt_y)
        c.wire("metal2", [(pt_x, pt_y), (pt_x, y_1b_0)], W_M2)
        via2_clean(c, pt_x, y_1b_0)
    for pt_x, pt_y in (rx_i2["out"], rx_c2["in"], rx_c1["out"]):
        via1_clean(c, pt_x, pt_y)
        c.wire("metal2", [(pt_x, pt_y), (pt_x, y_1b_2)], W_M2)
        via2_clean(c, pt_x, y_1b_2)

    def draw_clk_bank_drv(x_ctr: float, y_spine_lo: float, x_sp0: float, x_spb: float) -> dict:
        xp0 = grid(x_ctr - 15.500)
        x0  = grid(x_ctr - 7.800)
        xc1 = grid(x_ctr - 1.000)
        xc2 = grid(x_ctr + 1.000)
        x2  = grid(x_ctr + 7.800)
        xp2 = grid(x_ctr + 15.500)
        p0 = _draw_big_inv(c, cache, xp0, 2.40, 9.60, 2, 4, y_p0, y_n0, y_gc0, y_vdd0, y_vss0, x_in_side=-1)
        b0 = _draw_big_inv(c, cache, x0, 9.60, 38.40, 8, 16, y_p0, y_n0, y_gc0, y_vdd0, y_vss0, x_in_side=-1)
        c1 = pi_b.draw_cmos_inv(c, cache, xc1, 0.45, 1.60, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p0, y_n0, y_gc0, y_vdd0, y_vss0)
        c2 = pi_b.draw_cmos_inv(c, cache, xc2, 0.45, 1.60, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p0, y_n0, y_gc0, y_vdd0, y_vss0)
        b2 = _draw_big_inv(c, cache, x2, 9.60, 38.40, 8, 16, y_p0, y_n0, y_gc0, y_vdd0, y_vss0, x_in_side=+1)
        p2 = _draw_big_inv(c, cache, xp2, 2.40, 9.60, 2, 4, y_p0, y_n0, y_gc0, y_vdd0, y_vss0, x_in_side=+1)

        # Stage-2 inputs from M3 trunks y_1b_0 and y_1b_2
        via1_clean(c, p0["in"][0], p0["in"][1])
        c.wire("metal2", [(p0["in"][0], p0["in"][1]), (p0["in"][0], y_1b_0)], W_M2)
        via2_clean(c, p0["in"][0], y_1b_0)

        via1_clean(c, p2["in"][0], p2["in"][1])
        c.wire("metal2", [(p2["in"][0], p2["in"][1]), (p2["in"][0], y_1b_2)], W_M2)
        via2_clean(c, p2["in"][0], y_1b_2)

        # Local Stage-2 -> Stage-3 horizontal M2 stitch at y_gc0 (-3.850)
        via1_clean(c, b0["in"][0], b0["in"][1])
        c.wire("metal2", [(p0["x_out"], y_gc0), (b0["in"][0], y_gc0)], 0.360)
        via1_clean(c, b2["in"][0], b2["in"][1])
        c.wire("metal2", [(b2["in"][0], y_gc0), (p2["x_out"], y_gc0)], 0.360)

        # Stitch outputs to CC aligner on M2: out0 at y=-4.550, outb at y=-3.250 (clear of y_gc0=-3.85!)
        y_o0 = -4.550
        y_ob = -3.250
        via1_clean(c, c1["in"][0], y_gc0)
        via1_clean(c, c2["out"][0], y_gc0)
        c.wire("metal2", [(b0["x_out"], y_o0), (c2["out"][0], y_o0)], 0.360)
        c.wire("metal2", [(c1["in"][0], y_gc0), (c1["in"][0], y_o0)], W_M2)
        c.wire("metal2", [(c2["out"][0], y_gc0), (c2["out"][0], y_o0)], W_M2)

        via1_clean(c, c1["out"][0], y_gc0)
        via1_clean(c, c2["in"][0], y_gc0)
        c.wire("metal2", [(c1["out"][0], y_ob), (b2["x_out"], y_ob)], 0.360)
        c.wire("metal2", [(c1["out"][0], y_gc0), (c1["out"][0], y_ob)], W_M2)
        c.wire("metal2", [(c2["in"][0], y_gc0), (c2["in"][0], y_ob)], W_M2)

        # Bridge out0 & outb up to M4 vertical clock spines (x_sp0, x_spb) with dual via2 + via3!
        _dual_via2(c, b0["x_out"], y_o0, dx=0.56)
        c.wire("metal2", [(b0["x_out"], y_o0), (grid(b0["x_out"] + 0.56), y_o0)], 0.400)
        c.wire("metal3", [(min(b0["x_out"], x_sp0), y_o0), (max(grid(b0["x_out"] + 0.56), x_sp0), y_o0)], 0.520)
        _dual_via3(c, x_sp0, y_o0)

        _dual_via2(c, b2["x_out"], y_ob, dx=-0.56)
        c.wire("metal2", [(b2["x_out"], y_ob), (grid(b2["x_out"] - 0.56), y_ob)], 0.400)
        c.wire("metal3", [(min(grid(b2["x_out"] - 0.56), x_spb), y_ob), (max(b2["x_out"], x_spb), y_ob)], 0.520)
        _dual_via3(c, x_spb, y_ob)
        return {"in0_x": p0["in"][0], "in2_x": p2["in"][0], "y_o0": y_o0, "y_ob": y_ob}

    x_cka_0, x_cka_b = 104.000, 105.400
    x_ckb_0, x_ckb_b = 125.000, 126.400
    drv_a = draw_clk_bank_drv(96.000, y_bot, x_cka_0, x_cka_b)
    drv_b = draw_clk_bank_drv(141.000, y_bot, x_ckb_0, x_ckb_b)

    # Horizontal M3 trunks carrying ck0_1 and ck2_1 between Bank A (79.4) and Bank B (157.6)!
    c.wire("metal3", [(drv_a["in0_x"], y_1b_0), (drv_b["in0_x"], y_1b_0)], 0.340)
    c.wire("metal3", [(drv_a["in2_x"], y_1b_2), (drv_b["in2_x"], y_1b_2)], 0.340)

    # --- 3. Rows 1..10: Stamp 44x `dsr_dff_1g` + 32x `dsr_dff_250m` + Row 6 Word-Clock Drivers ---
    # Lean low-C M3 clock & reset bus rails for every row 1..10 (0.300 um M3 -> cuts clock CPEX ~35% while R < 10 Ohm!)
    y_rst_rails: list[float] = []
    for r in range(1, 11):
        y_rst = _row_y_transform(r, 1.150)
        y_ck = _row_y_transform(r, 2.300)
        y_ckb = _row_y_transform(r, 3.950)
        y_rst_rails.append(y_rst)

        # Full-width rst_n rail across all 8 columns
        c.wire("metal3", [(x_left, y_rst), (x_right, y_rst)], 0.320)

        if r <= 6:
            # Split Bank A [2.4 .. 117.0] (Row 6 stops at 107.6 covering Col 0 + spine, clear of wcap=110.2!)
            # and Bank B [120.8 .. 235.4] (3.8 um center gap!)
            x_a_end = 107.600 if r == 6 else 117.000
            c.wire("metal3", [(2.400, y_ck), (x_a_end, y_ck)], 0.300)
            c.wire("metal3", [(2.400, y_ckb), (x_a_end, y_ckb)], 0.300)
            _dual_via3(c, x_cka_0, y_ck)
            _dual_via3(c, x_cka_b, y_ckb)

            c.wire("metal3", [(120.800, y_ck), (235.400, y_ck)], 0.300)
            c.wire("metal3", [(120.800, y_ckb), (235.400, y_ckb)], 0.300)
            _dual_via3(c, x_ckb_0, y_ck)
            _dual_via3(c, x_ckb_b, y_ckb)
        else:
            # Rows 7..10: full-width 250 MHz wcap / wcapb rails!
            c.wire("metal3", [(2.400, y_ck), (235.400, y_ck)], 0.320)
            c.wire("metal3", [(2.400, y_ckb), (235.400, y_ckb)], 0.320)

    # Vertical M4 1 GHz Bank A & Bank B Clock Spines (Rows 0..6, w=0.520 um -> low R & low C!)
    y_r6_top = max(_row_y_transform(6, 2.300), _row_y_transform(6, 3.950))
    c.wire("metal4", [(x_cka_0, drv_a["y_o0"]), (x_cka_0, y_r6_top)], 0.520)
    c.wire("metal4", [(x_cka_b, drv_a["y_ob"]), (x_cka_b, y_r6_top)], 0.520)
    c.wire("metal4", [(x_ckb_0, drv_b["y_o0"]), (x_ckb_0, y_r6_top)], 0.520)
    c.wire("metal4", [(x_ckb_b, drv_b["y_ob"]), (x_ckb_b, y_r6_top)], 0.520)

    # Vertical M4 `rst_n` Spine at West edge (x = -0.800) + Center (x = 117.600)
    x_rst_w = -0.800
    c.wire("metal4", [(x_rst_w, y_rst_rails[0]), (x_rst_w, y_rst_rails[-1])], 0.520)
    for yr in y_rst_rails:
        c.wire("metal3", [(x_rst_w, yr), (x_left, yr)], 0.360)
        via3_pad(c, x_rst_w, yr)

    # Helper to stamp a DFF in `(col, row)` and return world coords of `(d, q, qb)`
    def place_dff(col: int, row: int, is_250m: bool = False, swap_clk: bool = False) -> dict:
        x0 = grid(col * COL_PITCH + 3.400)
        src = dff250_norm if is_250m else (dff1g_swap if swap_clk else dff1g_norm)
        m = dff250_m if is_250m else dff1g_m
        if row % 2 == 1:
            dy = grid((row - 1) * H_ROW)
            c.include(src, dx=x0, dy=dy)
        else:
            _include_flip_y(c, src, dx=x0, y_mirror_axis=grid(row * H_ROW))
        out = {
            "d": (grid(x0 + m["d"][0]), _row_y_transform(row, m["d"][1])),
            "q": (grid(x0 + m["q"][0]), _row_y_transform(row, m["q"][1])),
            "qb": (grid(x0 + m["qb"][0]), _row_y_transform(row, m["qb"][1])) if m["qb"] is not None else None,
            "row": row,
            "col": col,
        }
        return out

    # Helper: stitch `src_pt (row r)` -> `dst_pt (row r+1)` inside same column cleanly without touching other stages!
    # Departure is always on Q at y_rel=5.250; arrival is always on D at y_rel=6.650 (1.40 um apart in Y!).
    # Alternate M4 vertical hop X between x_d (odd r_s) and x_d + 1.05 (even r_s) -> 100% disjoint stages!
    def connect_same_col_next_row(col: int, src_dff: dict, dst_dff: dict) -> None:
        r_s = src_dff["row"]
        r_d = dst_dff["row"]
        y_m3_s = _row_y_transform(r_s, 5.250)
        y_m3_d = _row_y_transform(r_d, 6.650)
        x_q = src_dff["q"][0]
        x_d = dst_dff["d"][0]
        x_hop = x_d if (r_s % 2 == 1) else grid(x_d + 1.050)
        via1_clean(c, x_q, y_m3_s)
        via2_clean(c, x_q, y_m3_s)
        c.wire("metal3", [(x_hop, y_m3_s), (x_q, y_m3_s)], W_M3)
        via3_pad(c, x_hop, y_m3_s)
        c.wire("metal4", [(x_hop, y_m3_s), (x_hop, y_m3_d)], 0.360)
        via3_pad(c, x_hop, y_m3_d)
        if abs(x_hop - x_d) > 0.01:
            c.wire("metal3", [(x_d, y_m3_d), (x_hop, y_m3_d)], W_M3)
        via2_clean(c, x_d, y_m3_d)
        via1_clean(c, x_d, y_m3_d)

    # Helper: route tap `src_dff.q (row r_s)` -> `dst_dff.d (row r_d in 7..10)` via right-gutter M4 track `trk` (0..3)!
    def connect_tap_to_capture(col: int, trk: int, src_dff: dict, dst_dff: dict) -> None:
        x_trk = grid(col * COL_PITCH + 25.400 + trk * 0.950)
        r_s = src_dff["row"]
        r_d = dst_dff["row"]
        y_m3_s = _row_y_transform(r_s, 5.250)
        y_m3_d = _row_y_transform(r_d, 6.650)
        x_q = src_dff["q"][0]
        x_d = dst_dff["d"][0]
        via1_clean(c, x_q, y_m3_s)
        via2_clean(c, x_q, y_m3_s)
        c.wire("metal3", [(x_q, y_m3_s), (x_trk, y_m3_s)], W_M3)
        via3_pad(c, x_trk, y_m3_s)
        c.wire("metal4", [(x_trk, y_m3_s), (x_trk, y_m3_d)], 0.360)
        via3_pad(c, x_trk, y_m3_d)
        c.wire("metal3", [(x_d, y_m3_d), (x_trk, y_m3_d)], W_M3)
        via2_clean(c, x_d, y_m3_d)
        via1_clean(c, x_d, y_m3_d)

    # Lane schedules: (col, list of (name, swap_clk), tap_names_for_rows_7_8_9_10, out_names_for_rows_7_8_9_10)
    lane_specs = [
        (0, [("d0_a", True), ("d0_p", False), ("d0_0", False), ("d0_1", False), ("d0_2", False), ("d0_3", False)],
            ["d0_0", "d0_1", "d0_2", "d0_3"], ["wd12", "wd8", "wd4", "wd0"]),
        (1, [("d1_p", False), ("d1_0", False), ("d1_1", False), ("d1_2", False), ("d1_3", False)],
            ["d1_0", "d1_1", "d1_2", "d1_3"], ["wd13", "wd9", "wd5", "wd1"]),
        (2, [("d2_p", False), ("d2_0", False), ("d2_1", False), ("d2_2", False), ("d2_3", False)],
            ["d2_0", "d2_1", "d2_2", "d2_3"], ["wd14", "wd10", "wd6", "wd2"]),
        (3, [("d3_a", True), ("d3_0", False), ("d3_1", False), ("d3_2", False), ("d3_3", False)],
            ["d3_0", "d3_1", "d3_2", "d3_3"], ["wd15", "wd11", "wd7", "wd3"]),
        (4, [("e0_a", True), ("e0_p", False), ("e0_0", False), ("e0_1", False), ("e0_2", False), ("e0_3", False)],
            ["e0_0", "e0_1", "e0_2", "e0_3"], ["we13", "we9", "we5", "we1"]),
        (5, [("e1_p", False), ("e1_0", False), ("e1_1", False), ("e1_2", False), ("e1_3", False)],
            ["e1_0", "e1_1", "e1_2", "e1_3"], ["we14", "we10", "we6", "we2"]),
        (6, [("e2_p", False), ("e2_a", True), ("e2_0", False), ("e2_1", False), ("e2_2", False), ("e2_3", False)],
            ["e2_0", "e2_1", "e2_2", "e2_3"], ["we15", "we11", "we7", "we3"]),
        (7, [("e3_a", True), ("e3_0", False), ("e3_1", False), ("e3_2", False), ("e3_3", False), ("e3_4", False)],
            ["e3_1", "e3_2", "e3_3", "e3_4"], ["we12", "we8", "we4", "we0"]),
    ]

    north_out_ports: dict[str, tuple[float, float]] = {}
    y_north_pin = grid(y_top + 1.000)  # 77.000
    y_south_pin = grid(y_bot - 0.600)  # -9.000

    for col, stages, taps, out_names in lane_specs:
        dffs: dict[str, dict] = {}
        prev_dff: dict | None = None
        for idx, (sname, sw) in enumerate(stages):
            row = idx + 1
            df = place_dff(col, row, is_250m=False, swap_clk=sw)
            dffs[sname] = df
            if prev_dff is None:
                # Connect South slicer data input (x = slicer_qp_xs[col]) straight North on M4 to Row 1 D!
                x_in = slicer_qp_xs[col]
                y_m3_d = _row_y_transform(1, 6.650)
                x_d = df["d"][0]
                c.wire("metal4", [(x_in, y_south_pin), (x_in, y_m3_d)], 0.400)
                via3_pad(c, x_in, y_m3_d)
                c.wire("metal3", [(x_d, y_m3_d), (x_in, y_m3_d)], W_M3)
                via2_clean(c, x_d, y_m3_d)
                via1_clean(c, x_d, y_m3_d)
            else:
                connect_same_col_next_row(col, prev_dff, df)
            prev_dff = df

        # Stamp 4x 250 MHz capture DFFs in Rows 7..10 and connect taps + North output exits!
        for k, (tap_nm, out_nm) in enumerate(zip(taps, out_names)):
            cap_row = 7 + k
            cdf = place_dff(col, cap_row, is_250m=True, swap_clk=False)
            connect_tap_to_capture(col, k, dffs[tap_nm], cdf)

            # Route capture Q straight North on clean M4 output track inside column (`x_col + 6.5, 11.5, 16.5, 21.5`)!
            # Avoid center wcap/wcapb/wclk spine region in Col 4 (`x in [125..131]`): col 4 tracks are 124.9, 129.9, 134.9, 139.9
            # -> shift output tracks slightly to `+5.5, +10.0, +14.5, +19.0` (col 4 = 123.9, 128.4, 132.9, 137.4 -> spines at 119.5..122.5 clear!)
            x_out_trk = grid(col * COL_PITCH + 5.800 + k * 4.500)
            y_m3_q = _row_y_transform(cap_row, 5.250)
            x_q = cdf["q"][0]
            via1_clean(c, x_q, y_m3_q)
            via2_clean(c, x_q, y_m3_q)
            c.wire("metal3", [(x_out_trk, y_m3_q), (x_q, y_m3_q)], W_M3)
            via3_pad(c, x_out_trk, y_m3_q)
            c.wire("metal4", [(x_out_trk, y_m3_q), (x_out_trk, y_north_pin)], 0.400)
            north_out_ports[out_nm] = (x_out_trk, y_north_pin)

    # --- 4. Row 6: Johnson /4 (`Xj0` in Col 1, `Xj1` in Col 2 on Bank A!) + 250 MHz Word-Clock Drivers (Col 3) ---
    # Bank A drives exact 23 DFFs (21 data + 2 Johnson /4); Bank B drives exact 23 DFFs (23 edge)!
    # Row 6 is even: vdd at 38.000, vss at 45.600, y_p6 = 39.850, y_gc6 = 42.500, y_n6 = 44.200
    xj0 = place_dff(1, 6, is_250m=False, swap_clk=True)  # ck=ck0ba, ckb=ck0a -> q=j0, qb=j0b
    xj1 = place_dff(2, 6, is_250m=False, swap_clk=True)  # d=j0 -> q=j1, qb=j1b

    # Stitch Johnson /4: j0 (xj0.q -> xj1.d) on M3 at y_rel=6.650; j1b (xj1.qb -> xj0.d) on M3 at y_rel=5.250!
    y_r6_m3_hi = _row_y_transform(6, 6.650)  # 38.950
    y_r6_m3_lo = _row_y_transform(6, 5.250)  # 40.350
    # j0: xj0.q -> xj1.d (and also left to Xwcb1 in Col 3!)
    via1_clean(c, xj0["q"][0], y_r6_m3_hi)
    via2_clean(c, xj0["q"][0], y_r6_m3_hi)
    via1_clean(c, xj1["d"][0], y_r6_m3_hi)
    via2_clean(c, xj1["d"][0], y_r6_m3_hi)
    c.wire("metal3", [(xj0["q"][0], y_r6_m3_hi), (xj1["d"][0], y_r6_m3_hi)], W_M3)

    # j1b: xj1.qb -> xj0.d (M3 at y_r6_m3_lo = 40.350)
    # Note: xj0.d M1 spans from sp_y (y_rel=6.17 -> 39.43) down to dn_y (y_rel=1.68 -> 43.92), so y_r6_m3_lo=40.350 IS ON xj0.d M1!
    # Check M2 at (xj0.d, y_rel=5.250): m1 starts at col0.r, m2 starts at col1 -> col0.l has ZERO M2 at y_rel=5.250!
    via1_clean(c, xj1["qb"][0], y_r6_m3_lo)
    via2_clean(c, xj1["qb"][0], y_r6_m3_lo)
    via1_clean(c, xj0["d"][0], y_r6_m3_lo)
    via2_clean(c, xj0["d"][0], y_r6_m3_lo)
    c.wire("metal3", [(xj0["d"][0], y_r6_m3_lo), (xj1["qb"][0], y_r6_m3_lo)], W_M3)

    # Place 250 MHz word-clock drivers in Row 6 Col 3 (`x in [92..116]`):
    #   vdd = 38.000, y_p6 = 39.850, y_gc6 = 42.500, y_n6 = 44.200, vss = 45.600
    y_vdd6, y_vss6 = 38.000, 45.600
    y_p6, y_gc6, y_n6 = 39.850, 42.500, 44.200
    # Wait: Row 6 Col 3 has M3 rails: ck at 43.45, ckb at 41.65, rst at 44.30!
    # So keep local M2/M3 interconnects of the word-clock drivers cleanly at y in [38.9 .. 40.9] (clear of ckb=41.65 & vdd=38.00)!
    # Layout X in Col 3 [92 .. 116] (completely clear of Bank A spines at 64.6/66.0 and Col 3 power straps at 89.4/90.6!):
    #   Xwclk2 (1.6/3.8 nfn=1 nfp=2): x = 93.80
    #   Xwclk1 (1.0/2.4 nfn=1 nfp=1): x = 96.80
    #   Xwcb1  (1.4/3.4 nfn=1 nfp=2): x = 100.20
    #   Xwcb2  (2.4/5.8 nfn=2 nfp=4): x = 104.20
    #   Xcc_w1 (0.45/1.10)          : x = 107.60
    #   Xcc_w2 (0.45/1.10)          : x = 109.50
    #   Xwc2   (2.4/5.8 nfn=2 nfp=4): x = 113.00
    #   Xwc1   (1.4/3.4 nfn=1 nfp=2): x = 116.50 -> wait: Col 4 vss strap is at 119.0! 116.50 is 2.5 um clear!
    wclk2 = _draw_big_inv(c, cache, 93.800, 1.60, 3.80, 1, 2, y_p6, y_n6, y_gc6, y_vdd6, y_vss6, x_in_side=+1)
    wclk1 = pi_b.draw_cmos_inv(c, cache, 96.800, 1.00, 2.40, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p6, y_n6, y_gc6, y_vdd6, y_vss6)
    wcb1  = _draw_big_inv(c, cache, 100.200, 1.40, 3.40, 1, 2, y_p6, y_n6, y_gc6, y_vdd6, y_vss6, x_in_side=-1)
    wcb2  = _draw_big_inv(c, cache, 104.200, 2.40, 5.80, 2, 4, y_p6, y_n6, y_gc6, y_vdd6, y_vss6, x_in_side=-1)
    wcc1  = pi_b.draw_cmos_inv(c, cache, 107.600, 0.45, 1.10, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p6, y_n6, y_gc6, y_vdd6, y_vss6)
    wcc2  = pi_b.draw_cmos_inv(c, cache, 109.500, 0.45, 1.10, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p6, y_n6, y_gc6, y_vdd6, y_vss6)
    wc2   = _draw_big_inv(c, cache, 113.000, 2.40, 5.80, 2, 4, y_p6, y_n6, y_gc6, y_vdd6, y_vss6, x_in_side=+1)
    wc1   = _draw_big_inv(c, cache, 116.500, 1.40, 3.40, 1, 2, y_p6, y_n6, y_gc6, y_vdd6, y_vss6, x_in_side=+1)

    # Connect `j0` (from xj0.q at 51.5 -> xj1.d at 62.1 -> wcb1.in at 99.4 on y_r6_m3_hi=38.950)!
    c.wire("metal3", [(xj0["q"][0], y_r6_m3_hi), (wcb1["in"][0], y_r6_m3_hi)], W_M3)
    via2_clean(c, wcb1["in"][0], y_r6_m3_hi)
    via1_clean(c, wcb1["in"][0], y_gc6)
    c.wire("metal2", [(wcb1["in"][0], y_gc6), (wcb1["in"][0], y_r6_m3_hi)], W_M2)

    # Connect `j0b` (from xj0.qb at 53.3 -> wclk1.in at 96.8 -> wc1.in at 117.4 on y_j0b=42.550)!
    y_j0b = 42.550
    via1_clean(c, xj0["qb"][0], y_j0b)
    via2_clean(c, xj0["qb"][0], y_j0b)
    c.wire("metal3", [(xj0["qb"][0], y_j0b), (wc1["in"][0], y_j0b)], W_M3)
    for x_tgt in (wc1["in"][0], wclk1["in"][0]):
        via2_clean(c, x_tgt, y_j0b)
        via1_clean(c, x_tgt, y_j0b)
        c.wire("metal1", [(x_tgt, y_gc6), (x_tgt, y_j0b)], W_M1)

    # Local M2 stitches inside word-clock drivers:
    # wclk_b: wclk1.out -> wclk2.in routed at y=43.250 on M2 (clear of wclk1.in j0b via1 at y=42.550!)
    y_wclkb_m2 = 43.250
    via1_clean(c, wclk1["out"][0], y_wclkb_m2)
    c.wire("metal1", [(wclk1["out"][0], y_gc6), (wclk1["out"][0], y_wclkb_m2)], W_M1)
    via1_clean(c, wclk2["in"][0], y_gc6)
    c.wire("metal2", [(wclk2["in"][0], y_gc6), (wclk2["in"][0], y_wclkb_m2), (wclk1["out"][0], y_wclkb_m2)], W_M2)
    # wcapb_i: wcb1.out_m2 -> wcb2.in
    via1_clean(c, wcb2["in"][0], y_gc6)
    c.wire("metal2", [(wcb1["x_out"], y_gc6), (wcb2["in"][0], y_gc6)], W_M2)
    # wcap_i: wc1.out_m2 -> wc2.in
    via1_clean(c, wc2["in"][0], y_gc6)
    c.wire("metal2", [(wc1["x_out"], y_gc6), (wc2["in"][0], y_gc6)], W_M2)

    # wcap (wcb2.out -> wcc1.in -> wcc2.out) at y_wcap = 40.650 on M2 (>= 0.48 um M3 clear of Row 6 ckb=41.65!)
    # wcapb (wcc1.out -> wcc2.in -> wc2.out) at y_wcapb = 43.300 on M2 (>= 0.32 um M3 clear of j0b=42.55, >= 0.19 um M2 clear of wc2.dn_y=43.85!)
    y_wcap_m2 = 40.650
    y_wcapb_m2 = 43.300
    via1_clean(c, wcc1["in"][0], y_gc6)
    via1_clean(c, wcc2["out"][0], y_gc6)
    c.wire("metal2", [(wcb2["x_out"], y_wcap_m2), (wcc2["out"][0], y_wcap_m2)], 0.360)
    c.wire("metal2", [(wcc1["in"][0], y_gc6), (wcc1["in"][0], y_wcap_m2)], W_M2)
    c.wire("metal2", [(wcc2["out"][0], y_gc6), (wcc2["out"][0], y_wcap_m2)], W_M2)

    via1_clean(c, wcc1["out"][0], y_gc6)
    via1_clean(c, wcc2["in"][0], y_gc6)
    c.wire("metal2", [(wcc1["out"][0], y_wcapb_m2), (wc2["x_out"], y_wcapb_m2)], 0.360)
    c.wire("metal2", [(wcc1["out"][0], y_gc6), (wcc1["out"][0], y_wcapb_m2)], W_M2)
    c.wire("metal2", [(wcc2["in"][0], y_gc6), (wcc2["in"][0], y_wcapb_m2)], W_M2)

    # Vertical M4 `wcap` and `wcapb` spines driving Rows 7..10!
    # Check clear X in Col 3/4 for Rows 7..10:
    #   Col 3 output tracks are at 88.8 + [5.8, 10.3, 14.8, 19.3] = [94.6, 99.1, 103.6, 108.1]
    #   Col 3 right gutter tap tracks are at 88.8 + [25.4..28.25] = [114.2..117.05]
    #   Space between 108.1 and 114.2 is `6.1 um` WIDE AND 100% EMPTY ON M4 IN ROWS 7..10!!
    #   Put `x_wcap = 110.200`, `x_wcapb = 111.600` (and `x_wclk = 92.400`, clear of Col 3 vdd strap 90.6 and wd15 at 94.6!)!!
    x_wcap = 110.200
    x_wcapb = 111.600
    x_wclk = 92.400

    # Connect wcap/wcapb from Row 6 M2 up to M4 spines (using y=40.90 and y=43.40? Wait: y=43.45 has Bank A M3 ck!
    # So drop via2+via3 for wcap at (wcb2.x_out=105.0, 40.90) -> short M3? No, Bank A ckb is at 41.65 (gap 0.75 OK!).
    # Wait: wcapb at 43.40 collides with Bank A ck M3 at 43.45!
    # Fix: stop Bank A M3 ck/ckb rails at Row 6 right after Col 0 (since Cols 1, 2, 3 have ZERO 1G DFFs in Row 6!!)!
    # WAIT A SECOND! Check that! In Row 6, Bank A ONLY has `d0_3` in Col 0 (`x < 26`)!
    # Let's check! Yes! Cols 1, 2, 3 are EMPTY in Row 6 except our word-clock drivers!
    # Even simpler: we drew Bank A M3 rails across [2.4..117.0] above — let's connect wcap/wcapb straight via M2->M3->M4 at `y=40.40` (clear of 39.20 j0 and 41.65 ckb!) and `y=45.00`?
    # Better yet: go back and only run Row 6 Bank A ck/ckb up to `x = 68.0` (covering Col 0 AND Bank A spine at 64.6/66.0!) — wait: then Col 3 (`x in [90..118]`) has ZERO Bank A ck/ckb M3 rails in Row 6!!
    # Let's check: we can just use M2 up to `y = 40.90` (wcap) and `y = 43.40` (wcapb) ONCE Row 6 Bank A rails stop at `x = 68.0`!
    # Let's verify: does anything in Row 6 Cols 1..3 use Bank A ck/ckb? NO! Only Col 0 (`d0_3`, `x in [3..24]`)!
    # So we'll shorten Row 6 Bank A M3 rails right below — wait, let's adjust the loop above cleanly in place!

    # Connect wcap (M2 at 40.90) -> M3 -> M4 spine at x_wcap = 110.200
    _dual_via2(c, wcb2["x_out"], y_wcap_m2)
    c.wire("metal3", [(wcb2["x_out"], y_wcap_m2), (x_wcap, y_wcap_m2)], 0.500)
    _dual_via3(c, x_wcap, y_wcap_m2)

    # Connect wcapb (M2 at 43.40) -> M3 -> M4 spine at x_wcapb = 111.600
    _dual_via2(c, wc2["x_out"], y_wcapb_m2)
    c.wire("metal3", [(wc2["x_out"], y_wcapb_m2), (x_wcapb, y_wcapb_m2)], 0.500)
    _dual_via3(c, x_wcapb, y_wcapb_m2)

    y_r10_hi = max(_row_y_transform(10, 2.300), _row_y_transform(10, 3.950))
    c.wire("metal4", [(x_wcap, y_wcap_m2), (x_wcap, y_r10_hi)], 0.600)
    c.wire("metal4", [(x_wcapb, y_wcapb_m2), (x_wcapb, y_r10_hi)], 0.600)
    for r in range(7, 11):
        _dual_via3(c, x_wcap, _row_y_transform(r, 2.300))
        _dual_via3(c, x_wcapb, _row_y_transform(r, 3.950))

    # Route `wclk` from wclk2.x_out (93.25) -> x_wclk (92.40) straight North to North pin!
    via2_clean(c, wclk2["x_out"], y_wcap_m2)
    c.wire("metal3", [(x_wclk, y_wcap_m2), (wclk2["x_out"], y_wcap_m2)], 0.440)
    via3_pad(c, x_wclk, y_wcap_m2)
    c.wire("metal4", [(x_wclk, y_wcap_m2), (x_wclk, y_north_pin)], 0.480)
    north_out_ports["wclk"] = (x_wclk, y_north_pin)

    # --- 5. Export All 52 Cardinal Ports ---
    south_clk_ports = {nm: (slicer_clk_xs[i], y_south_pin) for i, nm in enumerate(clk_port_names)}
    south_data_ports = {nm: (slicer_qp_xs[i], y_south_pin) for i, nm in enumerate(data_port_names)}
    rst_port = (x_rst_w, y_rst_rails[0])
    vdd_port = (vdd_strap_xs[0], y_bot)
    vss_port = (vss_strap_xs[0], 0.000)

    if add_ports:
        for nm, pt in south_data_ports.items():
            c.port(nm, "metal4", *pt)
        for nm, pt in south_clk_ports.items():
            c.port(nm, "metal4", *pt)
        c.port("rst_n", "metal4", *rst_port)
        for nm, pt in north_out_ports.items():
            c.port(nm, "metal4", *pt)
        c.port("vdd", "metal4", *vdd_port)
        c.port("vss", "metal4", *vss_port)

    meta = {
        "south_data": south_data_ports,
        "south_clk": south_clk_ports,
        "north_out": north_out_ports,
        "rst_n": rst_port,
        "vdd": vdd_port,
        "vss": vss_port,
        "vdd_ys": vdd_ys,
        "vss_ys": vss_ys,
        "vdd_strap_xs": vdd_strap_xs,
        "vss_strap_xs": vss_strap_xs,
        "y_bot": y_bot,
        "y_top": y_top,
    }
    return c, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signoff", action="store_true",
                    help="Run full independent review_cell.py --rc, install into variants/v2_pdk/, update summary.json")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    VARIANT_DIR.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(RESULTS_DIR / "_pdk_cache")

    cell_name = "serdes_rx_cmos_deser16_pdk"
    src_subckt = "serdes_rx_cmos_deser16"
    watch_nets = ["ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3",
                  "d0", "d1", "d2", "d3", "e0", "e1", "e2", "e3", "wclk", "rst_n", "vdd", "vss"]

    if args.signoff:
        print(f"\n=== Independent Signoff (`review_cell.py --rc`) for {cell_name} ===", flush=True)
        mag = VARIANT_DIR / f"{cell_name}.mag"
        ref = VARIANT_DIR / f"{cell_name}_ref.spice"
        png = VARIANT_DIR / f"{cell_name}.png"
        review_dir = RESULTS_DIR / "review" / cell_name

        cell, _meta = build_rx_cmos_deser16_pdk(cache, add_ports=True)
        cell.write(mag)
        expected_ports = rlc.generate_rx_ref_spice(src_subckt, cell_name, ref)
        rev = pi_b._run_review_with_rc_audit(mag, ref, review_dir, timeout_s=300)

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
        assert entry["metal_shares"]["share_pct"]["M5"] == 0.0, f"{cell_name}: non-zero M5!"

        print(
            f"  PASS {cell_name}: {w_um:.2f} x {h_um:.2f} um ({area_um2:,.2f} um^2, AR={ar:.2f}) | "
            f"DRC=0 | LVS=MATCH (prop_err=False) | FP=0 | ports={len(rev['ports'])}/{len(expected_ports)} | "
            f"RC_strict={entry['rc_devices_preserved']} (WL+conn=True, moscap_asps_diffs={entry['rc_shorted_supply_moscap_as_ps_diffs']}) | "
            f"M1-5={mshares['share_pct']}",
            flush=True,
        )
    else:
        print(f"\n=== Building & Verifying {cell_name} ===", flush=True)
        work = RESULTS_DIR / "work_deser16"
        work.mkdir(parents=True, exist_ok=True)
        mag = work / f"{cell_name}.mag"
        ref = work / f"{cell_name}_ref.spice"
        png = work / f"{cell_name}.png"
        cell, _meta = build_rx_cmos_deser16_pdk(cache, add_ports=True)
        cell.write(mag)
        expected_ports = rlc.generate_rx_ref_spice(src_subckt, cell_name, ref)
        rep = rlc.verify_flat_cell(work, cell_name, mag, ref, expected_ports, timeout_s=240)
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
                print(f"  CPEX {k:5s}: {pcaps[k]}")


if __name__ == "__main__":
    main()
