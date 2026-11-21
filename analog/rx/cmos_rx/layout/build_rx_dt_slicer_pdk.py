#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder for 1 GHz Quarter-Rate Double-Tail Dynamic CMOS Slicer
(`serdes_rx_dt_slicer_pdk`, from frozen `analog/rx/cmos_rx/spice/rx_dt_sampler.spice`).

Abutment-Ready, Ultra-Symmetric Mirror Architecture (`25.20 x ~49.2 um`, mirror axis `X = 0.000`):
  - Exact horizontal abutment pitch `[-12.600, +12.600]` (`25.20 um`) with continuous full-width
    M3 `vdd`, `vss`, `inp`, `inn` rails and continuous NWELL bands so 8 slices tile seamlessly
    into a zero-dead-space 8x RX slicer bank.
  - Central vertical `clk` spine on M4 along `X = 0.000` -> zero skew between P and N halves.
  - 5 tightly packed bands (South -> North, M1/M2-first local routing):
      Band 0: 6-Bit Trim Static Drivers (`Xt5..Xt0` Left vs `Xref_on/Xref_off` Right, L=0.18,
              dense multi-viali & dual-via1 strapping on wide low-Z drivers)
      Band 1: 6-Bit Binary-Weighted MOS-Cap Trim Array (28.80 um on `fn` Left vs EXACT 28.80 um
              mirror ref bank on `fp` Right: Row C0 `w_f=0.90 nf=16` MSB/ref_on, Row C1
              `w_f=0.90 nf=8` b4/ref_off_a, Row C2 `w_f=0.45 8+4+2+1+1` exact island mirror!)
      Band 2: Stage-1 Dynamic Pre-Amp (`Xtail` centered, `Xinp/Xinn` mirrored + dummies,
              `Xpf1/Xpf2/Xpfeq` mirrored precharge/equalize)
      Band 3: Stage-2 Zero-Stacked-PMOS Regenerative Latch (`Xtail2` & `Xpoeq` centered,
              `Xmn1/Xmn2`, `Xln1/Xln2`, `Xlp1/Xlp2`, `Xpo1/Xpo2` exact mirror)
      Band 4: Isolated Static 6T SR Latch (`Xison/Xisop`, `Xrst/Xset`, `Xkn1/2`, `Xkp1/2`
              exact mirror, `qp`/`qn` symmetric North exits).
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
    P_LVT,
    grid,
    viali_pad,
    via1_clean,
    via2_clean,
    via3_pad,
    locali_v,
    draw_tap_h,
    tie_mos_gates,
    add_tied_poly_dummy,
)

SLICE_HALF_X = 12.600


def _strap_diff_vertical(
    c: Cell,
    xs: list[float],
    y1: float,
    y2: float,
    y_vias: list[float],
    y_bus: float | None = None,
    m1_w: float = 0.320,
    m2_w: float = 0.320,
    x_bus_span: tuple[float, float] | None = None,
) -> None:
    """Strap MOS S/D diffusion columns vertically on uniform M1 (zero met1.2 notches) and optionally bus on M2."""
    for x in xs:
        x = grid(x)
        for vy in y_vias:
            viali_pad(c, x, vy)
        if abs(y2 - y1) > 0.01:
            c.wire("metal1", [(x, grid(y1)), (x, grid(y2))], m1_w)
        if y_bus is not None:
            via1_clean(c, x, y_bus)
    if y_bus is not None:
        if x_bus_span is not None:
            xa, xb = sorted((grid(x_bus_span[0]), grid(x_bus_span[1])))
        else:
            xa, xb = min(xs), max(xs)
        if xb - xa > 0.01:
            c.wire("metal2", [(xa, grid(y_bus)), (xb, grid(y_bus))], m2_w)


def _draw_abut_rail(
    c: Cell,
    y: float,
    tap_layer: str,
    hx: float = SLICE_HALF_X,
    m3_w: float = 0.600,
    m1_w: float = 0.360,
    via_xs: tuple[float, ...] = (-11.45, +11.45),
) -> None:
    """Draw a full-width `[-hx, +hx]` horizontal abutment supply rail (tap + M1 + M3)."""
    y = grid(y)
    tx1, tx2 = (grid(-hx + 0.220), grid(+hx - 0.220)) if tap_layer == "nsubdiff" else (-hx, +hx)
    draw_tap_h(c, tap_layer, tx1, tx2, y, half_w=0.180, with_m1=True, m1_w=m1_w, viali_pitch=0.800)
    c.rect("metal1", -hx, grid(y - m1_w / 2.0), +hx, grid(y + m1_w / 2.0))
    c.rect("metal3", -hx, grid(y - m3_w / 2.0), +hx, grid(y + m3_w / 2.0))
    for vx in via_xs:
        via1_clean(c, vx, y)
        via2_clean(c, vx, y)


def _place_inv_block(
    c: Cell,
    cache: PdkCache,
    cx: float,
    wn: float,
    nfn: int,
    wp: float,
    nfp: int,
    y_n: float,
    y_p: float,
    y_vss: float,
    y_vdd: float,
    y_g: float,
    y_nd: float,
    y_pd: float,
    l_f: float = 0.18,
    n_model: str = N_STD,
    p_model: str = P_STD,
    l_p: float | None = None,
    x_out_drop: float | None = None,
    x_g_tap: float | None = None,
    locali_only_src: bool = False,
    locali_drain_join: bool = False,
) -> dict:
    """Place a compact static CMOS inverter with dense multi-viali M1/M2 local strapping."""
    l_p = l_f if l_p is None else l_p
    w_fn = grid(wn / nfn)
    w_fp = grid(wp / nfp)
    mn, inf_n = cache.build_mos(n_model, w_fn, l_f, nfn, y_n, False)
    mp, inf_p = cache.build_mos(p_model, w_fp, l_p, nfp, y_p, True)
    c.include(mn, dx=cx)
    c.include(mp, dx=cx)

    n_s = [grid(cx + x) for x in inf_n["s_xs"]]
    n_d = [grid(cx + x) for x in inf_n["d_xs"]]
    p_s = [grid(cx + x) for x in inf_p["s_xs"]]
    p_d = [grid(cx + x) for x in inf_p["d_xs"]]

    for sx in n_s:
        locali_v(c, sx, y_vss, inf_n["dy"])
        if not locali_only_src:
            viali_pad(c, sx, inf_n["dy"])
            c.wire("metal1", [(sx, min(y_vss, inf_n["dy"])), (sx, max(y_vss, inf_n["dy"]))], 0.290)
    for sx in p_s:
        locali_v(c, sx, inf_p["dy"], y_vdd)
        if not locali_only_src or nfp > 1:
            viali_pad(c, sx, inf_p["dy"])
            c.wire("metal1", [(sx, min(y_vdd, inf_p["dy"])), (sx, max(y_vdd, inf_p["dy"]))], 0.290)

    xd = grid(x_out_drop if x_out_drop is not None else n_d[0])
    if locali_drain_join and nfn == 1 and nfp == 1:
        locali_v(c, n_d[0], inf_n["dy"], inf_p["dy"])
        viali_pad(c, n_d[0], y_nd)
        via1_clean(c, n_d[0], y_nd)
        if abs(xd - n_d[0]) > 0.01:
            c.wire("metal2", sorted([(n_d[0], y_nd), (xd, y_nd)], key=lambda p: p[0]), 0.320)
    else:
        n_vy = [grid(inf_n["dy"] + d) for d in (-0.76, -0.38, 0.0, +0.38, +0.76)] if w_fn >= 1.9 else (
            [grid(inf_n["dy"] - 0.50), grid(inf_n["dy"] + 0.50)] if w_fn >= 1.6 else [inf_n["dy"]]
        )
        p_vy = [grid(inf_p["dy"] + d) for d in (-0.76, -0.38, 0.0, +0.38, +0.76)] if w_fp >= 1.9 else (
            [grid(inf_p["dy"] - 0.50), grid(inf_p["dy"] + 0.50)] if w_fp >= 1.6 else [inf_p["dy"]]
        )
        m1_wn = 0.290 if (nfn == 1 and l_f <= 0.15) else 0.320
        _strap_diff_vertical(c, n_d, min(n_vy[0], y_nd), max(n_vy[-1], y_nd), n_vy, y_bus=y_nd, m1_w=m1_wn, m2_w=0.320)
        _strap_diff_vertical(c, p_d, min(p_vy[0], y_pd), max(p_vy[-1], y_pd), p_vy, y_bus=y_pd, m1_w=0.320, m2_w=0.320)
        for d_list, yb in ((n_d, y_nd), (p_d, y_pd)):
            xa, xb = min(min(d_list), xd), max(max(d_list), xd)
            if xb - xa > 0.01:
                c.wire("metal2", [(xa, yb), (xb, yb)], 0.320)
        c.wire("metal2", [(xd, min(y_nd, y_pd)), (xd, max(y_nd, y_pd))], 0.320)

    clr_n = grid(max(0.220, l_f / 2.0 + 0.130))
    clr_p = grid(max(0.220, l_p / 2.0 + 0.130))
    y_bar_n = grid(inf_n["diff_y2"] + clr_n) if y_g > y_n else grid(inf_n["diff_y1"] - clr_n)
    y_bar_p = grid(inf_p["diff_y1"] - clr_p) if y_g < y_p else grid(inf_p["diff_y2"] + clr_p)
    gx_t = grid(x_g_tap if x_g_tap is not None else cx)
    gn_pt = tie_mos_gates(c, cx, inf_n, y_bar=y_bar_n, y_cont=y_g, tap_xs=[gx_t])[0]
    tie_mos_gates(c, cx, inf_p, y_bar=y_bar_p, y_cont=y_g, tap_xs=[gx_t])

    return {
        "cx": cx,
        "g": gn_pt,
        "out_x": xd,
        "out_n": (xd, y_nd),
        "out_p": (xd, y_pd),
        "inf_n": inf_n,
        "inf_p": inf_p,
    }


def build_rx_dt_slicer_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build `serdes_rx_dt_slicer_pdk` (ports: inp inn clk qp qn t5 t4 t3 t2 t1 t0 vdd vss)."""
    c = Cell()
    hx = SLICE_HALF_X  # 12.600 um -> total width = 25.200 um

    # Exact band Y coordinates (South -> North, compact 3-row cap bank -> ~49.2 um tall!)
    y_south_port = -0.900
    y_vss0a  =  0.000
    y_n0a    =  1.650   # w_f = 2.0 -> [0.65, 2.65]
    y_g0a    =  3.300
    y_p0a    =  4.950   # w_f = 2.0 -> [3.95, 5.95]
    y_vdd0   =  6.700   # shared VDD for Sub-row 0A & 0B (nwell [3.50, 9.90])
    y_p0b    =  8.450   # w_f = 2.0 -> [7.45, 9.45]
    y_g0b    = 10.100
    y_n0b    = 11.750   # w_f = 2.0 -> [10.75, 12.75]
    y_vss0b  = 13.450

    # Band 1: 3-Row Ultra-Low-R Exact-Mirror 6-Bit MOS-Cap Trim Array (28.80 um Left vs 28.80 um Right):
    #   Row C0 (y = 14.800, w_f = 0.90, nf = 16 -> 14.40 um): Xcn5 (tb5) | Xcp_on (r_on)
    #   Row C1 (y = 17.050, w_f = 0.90, nf = 8  ->  7.20 um): Xcn4 (tb4) | Xcp_off_a (r_off)
    #   Row C2 (y = 19.300, 7.20 um/side): Left Xcn3..0+Xcnd (w_f=0.45, 8+4+2+1+1) |
    #                                      Right Xcp_off_b (uniform w_f=0.90, 4+2+1+1 -> exact 16x0.90=14.40 um!)
    y_cap0   = 14.800   # diff [14.35, 15.25], gate bar at 15.70 -> polycont at 15.95
    y_cap1   = 17.050   # diff [16.60, 17.50], gate bar at 17.95 -> polycont at 18.20
    y_cap2   = 19.300   # Right diff [18.85, 19.75], Left diff [19.075, 19.525], gate bar at 20.00 -> cont 20.26
    y_vss1   = 21.150

    # Band 2: Stage-1 Dynamic Pre-Amp
    y_st1_n  = 23.700   # w_f = 3.5 -> [21.95, 25.45]
    y_inp_m3 = 26.100   # full-width abutment inp M3 bus
    y_inn_m3 = 27.000   # full-width abutment inn M3 bus
    y_st1_pg = 27.900   # Stage-1 PMOS clk gate
    y_st1_p  = 29.300   # w_f = 1.8 -> [28.40, 30.20]
    y_vdd12  = 31.000   # shared VDD for Stage 1 & Stage 2 (nwell [27.95, 34.75])

    # Band 3: Stage-2 Dynamic Regenerative Latch
    y_st2_p    = 32.950 # w_f = 2.25 -> [31.825, 34.075]
    y_s2_clk_p = 34.400 # Stage-2 PMOS clk gate
    y_cc_onb   = 35.100 # outn_b cross-couple
    y_cc_opb   = 35.900 # outp_b cross-couple
    y_st2_n    = 37.850 # w_f = 2.4 -> [36.65, 39.05]
    y_vss23    = 40.050 # shared VSS for Stage 2 & SR Latch

    # Band 4: Isolated 6T Static SR Latch
    y_sr_n       = 42.000 # max w_f = 2.4 -> [40.80, 43.20]
    y_sr_ch1     = 43.950 # qp / iso gate channel
    y_sr_ch2     = 44.750 # qn channel
    y_sr_p       = 46.500 # max w_f = 1.6 (L=0.35) -> [45.70, 47.30]
    y_vdd_n      = 48.100 # North VDD abutment rail (nwell [45.25, 48.70])
    y_north_port = 49.000

    # Continuous full-width NWELL bands (seamless horizontal abutment!)
    c.rect("nwell", -hx, 3.500, +hx, 9.900)
    c.rect("nwell", -hx, 27.950, +hx, 34.750)
    c.rect("nwell", -hx, 45.250, +hx, 48.700)

    x_vdd_sp = 12.150
    x_vss_sp = 11.450

    for yv in (y_vss0a, y_vss0b, y_vss1, y_vss23):
        _draw_abut_rail(c, yv, "psubdiff", hx=hx, via_xs=(-x_vss_sp, +x_vss_sp))
    for yv in (y_vdd0, y_vdd12, y_vdd_n):
        _draw_abut_rail(c, yv, "nsubdiff", hx=hx, via_xs=(-x_vdd_sp, +x_vdd_sp))

    for sgn in (-1, +1):
        xv_d = grid(sgn * x_vdd_sp)
        xv_s = grid(sgn * x_vss_sp)
        c.wire("metal2", [(xv_d, y_vdd0), (xv_d, y_vdd_n)], 0.360)
        c.wire("metal2", [(xv_s, y_vss0a), (xv_s, y_vss23)], 0.360)

    # =========================================================================
    # BAND 0: 6-Bit Trim Static Drivers (`Xt5..Xt0` Left vs `Xref_on/off` Right)
    # =========================================================================
    u_t5 = _place_inv_block(
        c, cache, cx=-5.600, wn=16.0, nfn=8, wp=32.0, nfp=16,
        y_n=y_n0a, y_p=y_p0a, y_vss=y_vss0a, y_vdd=y_vdd0,
        y_g=y_g0a, y_nd=2.150, y_pd=4.450, x_out_drop=-6.650,
    )
    u_ron = _place_inv_block(
        c, cache, cx=+5.600, wn=16.0, nfn=8, wp=32.0, nfp=16,
        y_n=y_n0a, y_p=y_p0a, y_vss=y_vss0a, y_vdd=y_vdd0,
        y_g=y_g0a, y_nd=2.150, y_pd=4.450, x_out_drop=+6.650,
    )
    x_ron_tie = +10.300
    c.wire("metal1", [u_ron["g"], (x_ron_tie, y_g0a)], 0.290)
    via1_clean(c, x_ron_tie, y_g0a)
    via1_clean(c, x_ron_tie, y_vdd0)
    c.wire("metal2", [(x_ron_tie, y_g0a), (x_ron_tie, y_vdd0)], 0.320)

    u_roff = _place_inv_block(
        c, cache, cx=+6.000, wn=16.0, nfn=8, wp=32.0, nfp=16,
        y_n=y_n0b, y_p=y_p0b, y_vss=y_vss0b, y_vdd=y_vdd0,
        y_g=y_g0b, y_nd=11.250, y_pd=8.950, x_out_drop=+9.200,
    )
    x_roff_tie = +10.500
    c.wire("metal1", [u_roff["g"], (x_roff_tie, y_g0b)], 0.290)
    via1_clean(c, x_roff_tie, y_g0b)
    via1_clean(c, x_roff_tie, y_vss0b)
    c.wire("metal2", [(x_roff_tie, y_g0b), (x_roff_tie, y_vss0b)], 0.320)

    u_t4 = _place_inv_block(
        c, cache, cx=-9.050, wn=8.0, nfn=4, wp=16.0, nfp=8,
        y_n=y_n0b, y_p=y_p0b, y_vss=y_vss0b, y_vdd=y_vdd0,
        y_g=y_g0b, y_nd=11.250, y_pd=8.950, x_out_drop=-8.150, x_g_tap=-9.150,
    )
    u_t3 = _place_inv_block(
        c, cache, cx=-5.450, wn=4.0, nfn=2, wp=8.0, nfp=4,
        y_n=y_n0b, y_p=y_p0b, y_vss=y_vss0b, y_vdd=y_vdd0,
        y_g=y_g0b, y_nd=11.250, y_pd=8.950, x_out_drop=-4.900, x_g_tap=-5.750,
    )
    u_t2 = _place_inv_block(
        c, cache, cx=-3.350, wn=2.0, nfn=1, wp=4.0, nfp=2,
        y_n=y_n0b, y_p=y_p0b, y_vss=y_vss0b, y_vdd=y_vdd0,
        y_g=y_g0b, y_nd=11.250, y_pd=8.950, x_out_drop=-3.100, x_g_tap=-3.850,
    )
    u_t1 = _place_inv_block(
        c, cache, cx=-2.050, wn=1.0, nfn=1, wp=2.0, nfp=1,
        y_n=y_n0b, y_p=y_p0b, y_vss=y_vss0b, y_vdd=y_vdd0,
        y_g=y_g0b, y_nd=11.250, y_pd=8.950, x_g_tap=-2.350, locali_drain_join=True,
    )
    u_t0 = _place_inv_block(
        c, cache, cx=-0.900, wn=1.0, nfn=1, wp=2.0, nfp=1,
        y_n=y_n0b, y_p=y_p0b, y_vss=y_vss0b, y_vdd=y_vdd0,
        y_g=y_g0b, y_nd=11.250, y_pd=8.950, x_g_tap=-1.150, locali_drain_join=True,
    )

    t_port_xs = {"t5": -10.400, "t4": -9.150, "t3": -5.750, "t2": -3.850, "t1": -2.350, "t0": -1.150}
    c.wire("metal1", [(t_port_xs["t5"], y_g0a), u_t5["g"]], 0.290)
    for tnm, ut in (("t5", u_t5), ("t4", u_t4), ("t3", u_t3), ("t2", u_t2), ("t1", u_t1), ("t0", u_t0)):
        xt = t_port_xs[tnm]
        yg = ut["g"][1]
        via1_clean(c, xt, yg)
        via2_clean(c, xt, yg)
        via3_pad(c, xt, yg)
        c.wire("metal4", [(xt, y_south_port), (xt, yg)], 0.440)

    # =========================================================================
    # BAND 1: 3-Row Exact-Mirror 6-Bit MOS-Cap Trim Array (28.80 um : 28.80 um!)
    # =========================================================================
    # Row C0 (`y_cap0 = 14.800`): `w_f = 0.90, l = 0.18, nf = 16` -> W = 14.40 um (2x ndiffc + 2x viali per finger!)
    #   Left (-5.80) = Xcn5 (tb5), Right (+5.80) = Xcp_on (r_on)
    mc0, inf_c0 = cache.build_mos(N_STD, 0.90, 0.18, 16, y_cap0, False)
    y_gb0, y_gc0 = grid(y_cap0 + 0.700), grid(y_cap0 + 0.960)
    for sgn in (-1, +1):
        cx = grid(sgn * 5.800)
        c.include(mc0, dx=cx)
        sds = [grid(cx + x) for x in inf_c0["all_sd_xs"]]
        for sx in sds:
            viali_pad(c, sx, grid(y_cap0 - 0.190))
            viali_pad(c, sx, grid(y_cap0 + 0.190))
        c.rect("metal1", grid(sds[0] - 0.145), grid(y_cap0 - 0.335), grid(sds[-1] + 0.145), grid(y_cap0 + 0.335))
        taps = [grid(cx - 3.000), cx, grid(cx + 3.000)]
        gpts = tie_mos_gates(c, cx, inf_c0, y_bar=y_gb0, y_cont=y_gc0, tap_xs=taps)
        c.wire("metal1", [(gpts[0][0], y_gc0), (gpts[-1][0], y_gc0)], 0.290)

    # Row C1 (`y_cap1 = 17.050`): `w_f = 0.90, l = 0.18, nf = 8` -> W = 7.20 um (2x ndiffc + 2x viali per finger!)
    #   Left (-7.40) = Xcn4 (tb4, spans [-9.47..-5.33]), Right (+7.40) = Xcp_off_a (r_off, spans [+5.33..+9.47])
    #   Wait: extend gate M1 bar inward to +-4.20 so it hits the vertical fn/fp M2 spine directly!
    mc1, inf_c1 = cache.build_mos(N_STD, 0.90, 0.18, 8, y_cap1, False)
    y_gb1, y_gc1 = grid(y_cap1 + 0.700), grid(y_cap1 + 0.960)
    for sgn in (-1, +1):
        cx = grid(sgn * 7.400)
        c.include(mc1, dx=cx)
        sds = [grid(cx + x) for x in inf_c1["all_sd_xs"]]
        for sx in sds:
            viali_pad(c, sx, grid(y_cap1 - 0.190))
            viali_pad(c, sx, grid(y_cap1 + 0.190))
        c.rect("metal1", grid(sds[0] - 0.145), grid(y_cap1 - 0.335), grid(sds[-1] + 0.145), grid(y_cap1 + 0.335))
        taps = [grid(cx - 1.500), grid(cx + 1.500)]
        gpts = tie_mos_gates(c, cx, inf_c1, y_bar=y_gb1, y_cont=y_gc1, tap_xs=taps)
        x_end_in = grid(sgn * 4.200)
        xa, xb = min(gpts[0][0], x_end_in), max(gpts[-1][0], x_end_in)
        c.wire("metal1", [(xa, y_gc1), (xb, y_gc1)], 0.290)

    # Row C2 (`y_cap2 = 19.300`, 7.20 um per side, EXACT MIRROR w_f = 0.90 for b3/b2/b1 vs ref_off_b!):
    #   Left (`fn`):  Xcn3(4x0.90) @ -8.50, Xcn2(2x0.90) @ -5.80, Xcn1(1x0.90) @ -3.30,
    #                 Xcn0(1x0.45) @ -1.85, Xcnd(1x0.45) @ -0.75  -> total 7.20 um!
    #   Right (`fp`): Xcp_off_b(4x0.90) @ +8.50, (2x0.90) @ +5.80, (1x0.90) @ +3.30, (1x0.90) @ +0.85 -> 7.20 um!
    cap_r2_left = [(4, 0.90, -8.500), (2, 0.90, -5.800), (1, 0.90, -3.300), (1, 0.45, -1.850), (1, 0.45, -0.750)]
    cap_r2_right = [(4, 0.90, +8.500), (2, 0.90, +5.800), (1, 0.90, +3.300), (1, 0.90, +0.850)]
    cap_r2_mos_90 = {nf: cache.build_mos(N_STD, 0.90, 0.18, nf, y_cap2, False) for nf in (4, 2, 1)}
    cap_r2_mos_45 = cache.build_mos(N_STD, 0.45, 0.18, 1, y_cap2, False)
    y_gb2, y_gc2 = grid(y_cap2 + 0.700), grid(y_cap2 + 0.960)

    # Left Row C2 (`fn`)
    g_tap_l = []
    for nf, wf, cx in cap_r2_left:
        mc, inf_c = cap_r2_mos_90[nf] if wf > 0.6 else cap_r2_mos_45
        c.include(mc, dx=cx)
        sds = [grid(cx + x) for x in inf_c["all_sd_xs"]]
        if wf > 0.6:
            for sx in sds:
                viali_pad(c, sx, grid(y_cap2 - 0.190))
                viali_pad(c, sx, grid(y_cap2 + 0.190))
            c.rect("metal1", grid(sds[0] - 0.145), grid(y_cap2 - 0.335), grid(sds[-1] + 0.145), grid(y_cap2 + 0.335))
        else:
            for sx in sds:
                viali_pad(c, sx, y_cap2)
            c.wire("metal1", [(sds[0], y_cap2), (sds[-1], y_cap2)], 0.290)
        gpts = tie_mos_gates(c, cx, inf_c, y_bar=y_gb2, y_cont=y_gc2, tap_xs=[cx])
        g_tap_l.append(gpts[0][0])
    c.wire("metal1", [(min(g_tap_l), y_gc2), (max(g_tap_l), y_gc2)], 0.290)

    # Right Row C2 (`fp`, uniform w_f = 0.90, 2x viali per finger!)
    g_tap_r = []
    for nf, _wf, cx in cap_r2_right:
        mc, inf_c = cap_r2_mos_90[nf]
        c.include(mc, dx=cx)
        sds = [grid(cx + x) for x in inf_c["all_sd_xs"]]
        for sx in sds:
            viali_pad(c, sx, grid(y_cap2 - 0.190))
            viali_pad(c, sx, grid(y_cap2 + 0.190))
        c.rect("metal1", grid(sds[0] - 0.145), grid(y_cap2 - 0.335), grid(sds[-1] + 0.145), grid(y_cap2 + 0.335))
        gpts = tie_mos_gates(c, cx, inf_c, y_bar=y_gb2, y_cont=y_gc2, tap_xs=[cx])
        g_tap_r.append(gpts[0][0])
    c.wire("metal1", [(min(g_tap_r), y_gc2), (max(g_tap_r), y_gc2)], 0.290)

    # Connect `Xcnd` (-0.75) <-> Right Row C2 `r_off` (+0.85..+9.20) on M1 at y = y_cap2
    c.wire("metal1", [(-0.750, y_cap2), (+9.200, y_cap2)], 0.290)

    # Symmetric vertical M2 `fn` (-4.20) & `fp` (+4.20) spines joining all 3 cap rows -> Stage 1!
    x_fn_sp = -4.200
    x_fp_sp = +4.200
    cap_g_ys = (y_gc0, y_gc1, y_gc2)
    for xf in (x_fn_sp, x_fp_sp):
        for ygc in cap_g_ys:
            via1_clean(c, xf, ygc)
        c.wire("metal2", [(xf, cap_g_ys[0]), (xf, cap_g_ys[-1])], 0.340)

    # Connect Band 0 trim drivers -> Band 1 cap S/D rows strictly on M1/M2 (ZERO M3/M4 bloat -> Tnew < 0.85 ps!)
    #   1. tb5: (-6.65, 4.45) -> straight north to Row C0 (`y_cap0 = 14.800`), double via1 (`-6.65` & `-7.35` on C0)!
    c.wire("metal2", [(-6.650, 4.450), (-6.650, y_cap0)], 0.440)
    via1_clean(c, -6.650, y_cap0)
    c.wire("metal2", [(-7.450, y_cap0), (-6.650, y_cap0)], 0.440)
    via1_clean(c, -7.450, y_cap0)

    #   2. r_on: (+6.65, 4.45) -> (+1.55, 4.45) -> straight north to Row C0 (`y_cap0 = 14.800`),
    #      plus mirror-matched M2 strap on C0 at `+6.65/+7.45` (Wait: don't cross `+4.20` fp spine!
    #      Strap `r_on` on C0 at `+2.10` & `+2.90` AND mirror-match C0/C1/C2 M2 over fp at `+5.85,+5.05,+3.30,+1.90`!)
    c.wire("metal2", [(+1.550, 4.450), (u_ron["out_p"][0], 4.450)], 0.440)
    c.wire("metal2", [(+1.550, 4.450), (+1.550, y_cap0), (+2.900, y_cap0)], 0.440)
    via1_clean(c, +2.100, y_cap0)
    via1_clean(c, +2.900, y_cap0)

    #   3. tb4 (Left C1): u_t4 (-8.15, 11.25) -> (-9.20, 12.80) -> straight north to Row C1 (`y_cap1 = 17.050`)
    c.wire("metal2", [(-8.150, 11.250), (-8.150, 12.800), (-9.200, 12.800), (-9.200, y_cap1)], 0.380)
    via1_clean(c, -9.200, y_cap1)

    #   4. r_off (Right C1 & C2): u_roff (+9.20, 11.25) -> straight north to Row C1 & C2,
    #      plus mirror-matched low-R M2 straps between C1 & C2 at +5.85, +6.65, +8.00 (all right of fp=+4.20)!
    c.wire("metal2", [(+9.200, 11.250), (+9.200, y_cap2)], 0.440)
    via1_clean(c, +9.200, y_cap1)
    via1_clean(c, +9.200, y_cap2)
    for xm in (+5.850, +8.000):
        c.wire("metal2", [(xm, y_cap1), (xm, y_cap2)], 0.320)
        via1_clean(c, xm, y_cap1)
        via1_clean(c, xm, y_cap2)

    #   5. tb3, tb2, tb1, tb0 -> Row C2 (`y_cap2 = 19.050`) via clean monotonic M2 staircase!
    #      Note: tb5 ends at `y_cap0 = 14.800`; tb2 hits Xcn2 (-5.80) at -5.35 (right of -5.80 center, clear of fn=-4.20!).
    c.wire("metal2", [(-4.900, 11.250), (-4.900, 12.100), (-5.850, 12.100),
                      (-5.850, 18.250), (-8.500, 18.250), (-8.500, y_cap2)], 0.280)
    via1_clean(c, -8.500, y_cap2)

    c.wire("metal2", [(-3.100, 11.250), (-3.100, 12.800), (-5.200, 12.800), (-5.200, y_cap2)], 0.280)
    via1_clean(c, -5.200, y_cap2)

    c.wire("metal2", [(u_t1["out_x"], 11.250), (u_t1["out_x"], 13.500), (-3.300, 13.500), (-3.300, y_cap2)], 0.280)
    via1_clean(c, -3.300, y_cap2)

    c.wire("metal2", [(u_t0["out_x"], 11.250), (u_t0["out_x"], 14.150), (-1.850, 14.150), (-1.850, y_cap2)], 0.280)
    via1_clean(c, -1.850, y_cap2)

    # =========================================================================
    # BAND 2: Stage-1 Dynamic Pre-Amp (`Xtail`, `Xinp/Xinn`, `Xpf1/Xpf2/Xpfeq`)
    # =========================================================================
    m_st1_tail, inf_st1_tail = cache.build_mos(N_LVT, 3.50, 0.15, 2, y_st1_n, False)
    m_st1_in,   inf_st1_in   = cache.build_mos(N_LVT, 3.50, 0.18, 4, y_st1_n, False)
    c.include(m_st1_tail, dx=0.000)
    cx_in = 3.800
    c.include(m_st1_in, dx=-cx_in)
    c.include(m_st1_in, dx=+cx_in)

    for sgn in (-1, +1):
        xd = grid(sgn * (cx_in + inf_st1_in["hw_diff"] + 0.140 + 0.090))
        pt = add_tied_poly_dummy(c, xd, inf_st1_in["poly_y1"], inf_st1_in["poly_y2"], 0.18,
                                 y_cont=grid(y_st1_n - 1.950), x_cont=grid(xd + sgn * 0.100))
        c.wire("metal1", [pt, (pt[0], y_vss1)], 0.290)

    y_st1_tail_bus = grid(y_st1_n - 1.000)  # 22.200
    for sx in inf_st1_tail["s_xs"]:
        locali_v(c, sx, y_vss1, y_st1_n)
        _strap_diff_vertical(c, [sx], y_vss1, grid(y_st1_n + 1.20), [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)])
    _strap_diff_vertical(c, inf_st1_tail["d_xs"], grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                         [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)], y_bus=y_st1_tail_bus)

    y_st1_fn_bus = grid(y_st1_n + 1.000)    # 24.200
    all_tail_xs = list(inf_st1_tail["d_xs"])
    for sgn, x_f_sp in ((-1, x_fn_sp), (+1, x_fp_sp)):
        cx = grid(sgn * cx_in)
        xf_s1 = grid(sgn * 5.550)
        s_xs = [grid(cx + x) for x in inf_st1_in["s_xs"]]
        d_xs = [grid(cx + x) for x in inf_st1_in["d_xs"]]
        all_tail_xs.extend(s_xs)
        _strap_diff_vertical(c, s_xs, grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)], y_bus=y_st1_tail_bus)
        _strap_diff_vertical(c, d_xs, grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)], y_bus=y_st1_fn_bus,
                             x_bus_span=(min(d_xs[0], xf_s1), max(d_xs[-1], xf_s1)))
        y_jog = grid(y_vss1 + 0.650)  # 21.300 (strictly between y_vss1=20.65 & tail_bus=22.20!)
        c.wire("metal2", [(x_f_sp, y_gc2), (x_f_sp, y_jog), (xf_s1, y_jog), (xf_s1, y_st1_p)], 0.340)
    c.wire("metal2", [(min(all_tail_xs), y_st1_tail_bus), (max(all_tail_xs), y_st1_tail_bus)], 0.360)

    # Full-width horizontal abutment `inp` & `inn` M3 buses + exact 0.000 um mirror gate taps!
    c.rect("metal3", -hx, grid(y_inp_m3 - 0.200), +hx, grid(y_inp_m3 + 0.200))
    c.rect("metal3", -hx, grid(y_inn_m3 - 0.200), +hx, grid(y_inn_m3 + 0.200))
    y_in_gc = grid((y_inp_m3 + y_inn_m3) / 2.0)  # 26.050
    for sgn, y_m3 in ((-1, y_inp_m3), (+1, y_inn_m3)):
        cx = grid(sgn * cx_in)
        tx = grid(sgn * 3.200)
        tie_mos_gates(c, cx, inf_st1_in, y_bar=grid(y_st1_n + 2.100), y_cont=y_in_gc, tap_xs=[tx])
        via1_clean(c, tx, y_in_gc)
        c.wire("metal2", [(tx, min(y_in_gc, y_m3)), (tx, max(y_in_gc, y_m3))], 0.320)
        via2_clean(c, tx, y_m3)

    # Xtail gate (`clk`) -> M2 under inp/inn M3 -> Stage-1 PMOS clk gate bar at y_st1_pg!
    y_tail_gc = grid(y_st1_n + 2.200)  # 25.400
    tie_mos_gates(c, 0.000, inf_st1_tail, y_bar=grid(y_st1_n + 2.050), y_cont=y_tail_gc, tap_xs=[0.000])
    via1_clean(c, 0.000, y_tail_gc)
    c.wire("metal2", [(0.000, y_tail_gc), (0.000, y_st1_pg)], 0.320)

    m_pfeq, inf_pfeq = cache.build_mos(P_STD, 1.00, 0.18, 1, y_st1_p, True)
    m_pf,   inf_pf   = cache.build_mos(P_STD, 1.80, 0.15, 2, y_st1_p, True)
    c.include(m_pfeq, dx=0.000)
    c.include(m_pf,   dx=-cx_in)
    c.include(m_pf,   dx=+cx_in)

    for sgn, x_f_sp in ((-1, x_fn_sp), (+1, x_fp_sp)):
        cx = grid(sgn * cx_in)
        for sx in [grid(cx + x) for x in inf_pf["s_xs"]]:
            locali_v(c, sx, y_st1_p, y_vdd12)
            _strap_diff_vertical(c, [sx], grid(y_st1_p - 0.50), y_vdd12, [grid(y_st1_p - 0.45), grid(y_st1_p + 0.45)])
        dx_p = grid(cx + inf_pf["d_xs"][0])
        _strap_diff_vertical(c, [dx_p], grid(y_st1_p - 0.50), grid(y_st1_p + 0.50),
                             [grid(y_st1_p - 0.45), grid(y_st1_p + 0.45)], y_bus=y_st1_p)
        x_eq_d = grid(inf_pfeq["s_xs"][0] if sgn < 0 else inf_pfeq["d_xs"][0])
        viali_pad(c, x_eq_d, y_st1_p)
        via1_clean(c, x_eq_d, y_st1_p)
        xa, xb = sorted((grid(sgn * 5.550), x_eq_d))
        c.wire("metal2", [(xa, y_st1_p), (xb, y_st1_p)], 0.320)

    tie_mos_gates(c, 0.000,  inf_pfeq, y_bar=grid(y_st1_p - 0.850), y_cont=y_st1_pg, tap_xs=[0.000])
    tie_mos_gates(c, -cx_in, inf_pf,   y_bar=grid(y_st1_p - 1.150), y_cont=y_st1_pg, tap_xs=[-cx_in])
    tie_mos_gates(c, +cx_in, inf_pf,   y_bar=grid(y_st1_p - 1.150), y_cont=y_st1_pg, tap_xs=[+cx_in])
    c.wire("metal1", [(-cx_in, y_st1_pg), (+cx_in, y_st1_pg)], 0.290)
    via1_clean(c, 0.000, y_st1_pg)
    via2_clean(c, 0.000, y_st1_pg)
    via3_pad(c, 0.000, y_st1_pg)

    # =========================================================================
    # BAND 3: Stage-2 Dynamic Regenerative Latch (`y_st2_p = 32.45`, `y_st2_n = 37.35`)
    # =========================================================================
    cx_lp = 2.800
    cx_po = 6.000
    m_poeq, inf_poeq = cache.build_mos(P_STD, 1.00, 0.18, 1, y_st2_p, True)
    m_lp,   inf_lp   = cache.build_mos(P_STD, 2.25, 0.18, 4, y_st2_p, True)
    m_po,   inf_po   = cache.build_mos(P_STD, 1.80, 0.15, 2, y_st2_p, True)
    c.include(m_poeq, dx=0.000)
    for sgn in (-1, +1):
        c.include(m_lp, dx=grid(sgn * cx_lp))
        c.include(m_po, dx=grid(sgn * cx_po))

    for sgn in (-1, +1):
        for sx in [grid(sgn * cx_lp + x) for x in inf_lp["s_xs"]]:
            locali_v(c, sx, y_vdd12, y_st2_p)
            _strap_diff_vertical(c, [sx], y_vdd12, grid(y_st2_p + 0.70), [grid(y_st2_p - 0.65), grid(y_st2_p + 0.65)])
        for sx in [grid(sgn * cx_po + x) for x in inf_po["s_xs"]]:
            locali_v(c, sx, y_vdd12, y_st2_p)
            _strap_diff_vertical(c, [sx], y_vdd12, grid(y_st2_p + 0.50), [grid(y_st2_p - 0.45), grid(y_st2_p + 0.45)])
        x_eq_d = grid(inf_poeq["s_xs"][0] if sgn < 0 else inf_poeq["d_xs"][0])
        viali_pad(c, x_eq_d, y_st2_p)
        via1_clean(c, x_eq_d, y_st2_p)
        lp_ds = [grid(sgn * cx_lp + x) for x in inf_lp["d_xs"]]
        po_ds = [grid(sgn * cx_po + x) for x in inf_po["d_xs"]]
        _strap_diff_vertical(c, lp_ds, grid(y_st2_p - 0.70), grid(y_st2_p + 0.70),
                             [grid(y_st2_p - 0.65), grid(y_st2_p + 0.65)], y_bus=y_st2_p)
        _strap_diff_vertical(c, po_ds, grid(y_st2_p - 0.50), grid(y_st2_p + 0.50),
                             [grid(y_st2_p - 0.45), grid(y_st2_p + 0.45)], y_bus=y_st2_p)
        all_ds = [x_eq_d] + lp_ds + po_ds
        c.wire("metal2", [(min(all_ds), y_st2_p), (max(all_ds), y_st2_p)], 0.320)

    tie_mos_gates(c, 0.000,  inf_poeq, y_bar=grid(y_st2_p + 0.750), y_cont=y_s2_clk_p, tap_xs=[0.000])
    tie_mos_gates(c, -cx_po, inf_po,   y_bar=grid(y_st2_p + 1.150), y_cont=y_s2_clk_p, tap_xs=[-cx_po])
    tie_mos_gates(c, +cx_po, inf_po,   y_bar=grid(y_st2_p + 1.150), y_cont=y_s2_clk_p, tap_xs=[+cx_po])
    for xck in (-cx_po, 0.000, +cx_po):
        via1_clean(c, xck, y_s2_clk_p)
        via2_clean(c, xck, y_s2_clk_p)
    via3_pad(c, 0.000, y_s2_clk_p)
    c.wire("metal3", [(-cx_po, y_s2_clk_p), (+cx_po, y_s2_clk_p)], 0.360)

    m_tail2, inf_tail2 = cache.build_mos(N_STD, 1.50, 0.18, 4, y_st2_n, False)
    m_ln,    inf_ln    = cache.build_mos(N_LVT, 2.00, 0.18, 4, y_st2_n, False)
    m_mn,    inf_mn    = cache.build_mos(N_LVT, 2.40, 0.18, 2, y_st2_n, False)
    c.include(m_tail2, dx=0.000)
    for sgn in (-1, +1):
        c.include(m_ln, dx=grid(sgn * cx_lp))
        c.include(m_mn, dx=grid(sgn * cx_po))

    y_vbot2    = grid(y_st2_n + 0.600)
    y_s2_n_out = grid(y_st2_n - 0.600)
    for sx in inf_tail2["s_xs"]:
        locali_v(c, sx, y_st2_n, y_vss23)
        _strap_diff_vertical(c, [sx], grid(y_st2_n - 0.45), y_vss23, [grid(y_st2_n - 0.35), grid(y_st2_n + 0.35)])
    _strap_diff_vertical(c, inf_tail2["d_xs"], grid(y_st2_n - 0.50), grid(y_st2_n + 0.50),
                         [grid(y_st2_n - 0.35), grid(y_st2_n + 0.35)], y_bus=y_vbot2)

    vbot2_xs = list(inf_tail2["d_xs"])
    for sgn in (-1, +1):
        ln_s = [grid(sgn * cx_lp + x) for x in inf_ln["s_xs"]]
        ln_d = [grid(sgn * cx_lp + x) for x in inf_ln["d_xs"]]
        mn_s = [grid(sgn * cx_po + x) for x in inf_mn["s_xs"]]
        mn_d = [grid(sgn * cx_po + x) for x in inf_mn["d_xs"]]
        vbot2_xs.extend(ln_s + mn_s)
        _strap_diff_vertical(c, ln_s, grid(y_st2_n - 0.65), grid(y_st2_n + 0.65),
                             [grid(y_st2_n - 0.55), grid(y_st2_n + 0.55)], y_bus=y_vbot2)
        _strap_diff_vertical(c, mn_s, grid(y_st2_n - 0.85), grid(y_st2_n + 0.85),
                             [grid(y_st2_n - 0.70), grid(y_st2_n + 0.70)], y_bus=y_vbot2)
        _strap_diff_vertical(c, ln_d, grid(y_st2_n - 0.65), grid(y_st2_n + 0.65),
                             [grid(y_st2_n - 0.55), grid(y_st2_n + 0.55)], y_bus=y_s2_n_out)
        _strap_diff_vertical(c, mn_d, grid(y_st2_n - 0.85), grid(y_st2_n + 0.85),
                             [grid(y_st2_n - 0.70), grid(y_st2_n + 0.70)], y_bus=y_s2_n_out)
        all_nd = ln_d + mn_d
        c.wire("metal2", [(min(all_nd), y_s2_n_out), (max(all_nd), y_s2_n_out)], 0.340)
        x_ob = grid(sgn * 4.550)
        c.wire("metal2", [(x_ob, y_st2_p), (x_ob, y_s2_n_out)], 0.360)
    c.wire("metal2", [(min(vbot2_xs), y_vbot2), (max(vbot2_xs), y_vbot2)], 0.380)

    y_tail2_g = grid(y_st2_n - 1.250)  # 36.100
    tie_mos_gates(c, 0.000, inf_tail2, y_bar=grid(y_st2_n - 1.000), y_cont=y_tail2_g, tap_xs=[0.000])
    via1_clean(c, 0.000, y_tail2_g)
    via2_clean(c, 0.000, y_tail2_g)
    via3_pad(c, 0.000, y_tail2_g)

    # Central `clk` vertical M4 spine along `X = 0.000`
    c.wire("metal4", [(0.000, y_south_port), (0.000, y_tail2_g)], 0.440)

    # Connect `fn` / `fp` -> `Xmn1.G` / `Xmn2.G` symmetrically along `x = +-7.350`!
    y_mn_g = grid(y_st2_n - 1.750)  # 35.600
    for sgn in (-1, +1):
        xf_s1 = grid(sgn * 5.550)
        xf_out = grid(sgn * 7.350)
        cx = grid(sgn * cx_po)
        xa, xb = sorted((xf_s1, xf_out))
        c.wire("metal2", [(xa, y_st1_p), (xb, y_st1_p)], 0.340)
        c.wire("metal2", [(xf_out, y_st1_p), (xf_out, y_mn_g)], 0.340)
        via1_clean(c, xf_out, y_mn_g)
        gp = tie_mos_gates(c, cx, inf_mn, y_bar=grid(y_st2_n - 1.450), y_cont=y_mn_g, tap_xs=[cx])[0]
        c.wire("metal1", sorted([(xf_out, y_mn_g), gp], key=lambda p: p[0]), 0.290)

    # Stage-2 Cross-Coupling (`outn_b` = 34.60, `outp_b` = 35.40) — EXACT MIRROR!
    for sgn, y_cc in ((-1, y_cc_opb), (+1, y_cc_onb)):
        cx = grid(sgn * cx_lp)
        tie_mos_gates(c, cx, inf_lp, y_bar=grid(y_st2_p + 1.400), y_cont=y_cc, tap_xs=[cx])
        tie_mos_gates(c, cx, inf_ln, y_bar=grid(y_st2_n - 1.250), y_cont=y_cc, tap_xs=[cx])
    via1_clean(c, -4.550, y_cc_onb)
    c.wire("metal1", [(-4.550, y_cc_onb), (+cx_lp, y_cc_onb)], 0.290)
    via1_clean(c, +4.550, y_cc_opb)
    c.wire("metal1", [(-cx_lp, y_cc_opb), (+4.550, y_cc_opb)], 0.290)

    # =========================================================================
    # BAND 4: Isolated 6T Static SR Latch (`y_sr_n = 41.50`, `y_sr_p = 46.00`)
    # =========================================================================
    cx_iso = 6.000
    cx_sr  = 3.400
    cx_kp  = 1.400

    u_ison = _place_inv_block(
        c, cache, cx=-cx_iso, wn=1.5, nfn=1, wp=3.2, nfp=2,
        y_n=y_sr_n, y_p=y_sr_p, y_vss=y_vss23, y_vdd=y_vdd_n,
        y_g=y_sr_ch1, y_nd=y_sr_n, y_pd=y_sr_p,
        l_f=0.15, n_model=N_LVT, p_model=P_LVT, l_p=0.35,
        x_out_drop=-4.900, locali_only_src=True,
    )
    u_isop = _place_inv_block(
        c, cache, cx=+cx_iso, wn=1.5, nfn=1, wp=3.2, nfp=2,
        y_n=y_sr_n, y_p=y_sr_p, y_vss=y_vss23, y_vdd=y_vdd_n,
        y_g=y_sr_ch1, y_nd=y_sr_n, y_pd=y_sr_p,
        l_f=0.15, n_model=N_LVT, p_model=P_LVT, l_p=0.35,
        x_out_drop=+4.900, locali_only_src=True,
    )
    for sgn, u_iso in ((-1, u_ison), (+1, u_isop)):
        xo = grid(sgn * 7.350)
        x_mn_d = grid(sgn * cx_po)
        c.wire("metal2", sorted([(x_mn_d, y_s2_n_out), (xo, y_s2_n_out)], key=lambda p: p[0]), 0.340)
        c.wire("metal2", [(xo, y_s2_n_out), (xo, y_sr_ch1)], 0.340)
        via1_clean(c, xo, y_sr_ch1)
        c.wire("metal1", sorted([(xo, y_sr_ch1), u_iso["g"]], key=lambda p: p[0]), 0.290)

    m_sr_n, inf_sr_n = cache.build_mos(N_LVT, 2.40, 0.15, 2, y_sr_n, False)
    for sgn, u_iso in ((-1, u_ison), (+1, u_isop)):
        cx = grid(sgn * cx_sr)
        c.include(m_sr_n, dx=cx)
        for sx in [grid(cx + x) for x in inf_sr_n["s_xs"]]:
            locali_v(c, sx, y_vss23, y_sr_n)
            _strap_diff_vertical(c, [sx], y_vss23, grid(y_sr_n + 0.80), [grid(y_sr_n - 0.70), grid(y_sr_n + 0.70)])
        dx_sr = grid(cx + inf_sr_n["d_xs"][0])
        _strap_diff_vertical(c, [dx_sr], grid(y_sr_n - 0.80), grid(y_sr_n + 0.80),
                             [grid(y_sr_n - 0.70), grid(y_sr_n + 0.70)], y_bus=y_sr_n)
        gp = tie_mos_gates(c, cx, inf_sr_n, y_bar=grid(y_sr_n + 1.450), y_cont=y_sr_ch1, tap_xs=[cx])[0]
        via1_clean(c, gp[0], y_sr_ch1)
        c.wire("metal2", sorted([(u_iso["out_x"], y_sr_ch1), gp], key=lambda p: p[0]), 0.300)

    m_kn, inf_kn = cache.build_mos(N_LVT, 1.00, 0.15, 1, y_sr_n, False)
    m_kp, inf_kp = cache.build_mos(P_LVT, 1.40, 0.35, 2, y_sr_p, True)
    for sgn in (-1, +1):
        cx = grid(sgn * cx_kp)
        c.include(m_kn, dx=cx)
        c.include(m_kp, dx=cx)
        x_kn_s = grid(cx + (inf_kn["s_xs"][0] if sgn < 0 else inf_kn["d_xs"][0]))
        x_kn_d = grid(cx + (inf_kn["d_xs"][0] if sgn < 0 else inf_kn["s_xs"][0]))
        locali_v(c, x_kn_s, y_vss23, y_sr_n)
        _strap_diff_vertical(c, [x_kn_d], grid(y_sr_n - 0.25), grid(y_sr_n + 0.25), [y_sr_n], y_bus=y_sr_n, m1_w=0.290)

        for sx in [grid(cx + x) for x in inf_kp["s_xs"]]:
            locali_v(c, sx, y_sr_p, y_vdd_n)
            _strap_diff_vertical(c, [sx], grid(y_sr_p - 0.40), y_vdd_n, [grid(y_sr_p - 0.35), grid(y_sr_p + 0.35)])
        x_kp_d = grid(cx + inf_kp["d_xs"][0])
        _strap_diff_vertical(c, [x_kp_d], grid(y_sr_p - 0.40), grid(y_sr_p + 0.40),
                             [grid(y_sr_p - 0.35), grid(y_sr_p + 0.35)], y_bus=y_sr_p)

        x_q_out = grid(sgn * 2.450)
        c.wire("metal2", sorted([(grid(sgn * cx_sr), y_sr_n), (x_kn_d, y_sr_n)], key=lambda p: p[0]), 0.320)
        c.wire("metal2", sorted([(x_kp_d, y_sr_p), (x_q_out, y_sr_p)], key=lambda p: p[0]), 0.320)
        c.wire("metal2", [(x_q_out, y_sr_n), (x_q_out, y_north_port)], 0.340)

    for sgn, y_qcc in ((-1, y_sr_ch2), (+1, y_sr_ch1)):
        cx = grid(sgn * cx_kp)
        tie_mos_gates(c, cx, inf_kn, y_bar=grid(y_sr_n + 0.800), y_cont=y_qcc, tap_xs=[cx])
        tie_mos_gates(c, cx, inf_kp, y_bar=grid(y_sr_p - 1.100), y_cont=y_qcc, tap_xs=[cx])
    via1_clean(c, -2.450, y_sr_ch1)
    c.wire("metal1", [(-2.450, y_sr_ch1), (+cx_kp, y_sr_ch1)], 0.290)
    via1_clean(c, +2.450, y_sr_ch2)
    c.wire("metal1", [(-cx_kp, y_sr_ch2), (+2.450, y_sr_ch2)], 0.290)

    if add_ports:
        c.port("inp", "metal3", -hx, y_inp_m3)
        c.port("inn", "metal3", -hx, y_inn_m3)
        c.port("clk", "metal4", 0.000, y_south_port)
        c.port("qp",  "metal2", -2.450, y_north_port)
        c.port("qn",  "metal2", +2.450, y_north_port)
        for tnm in ("t5", "t4", "t3", "t2", "t1", "t0"):
            c.port(tnm, "metal4", t_port_xs[tnm], y_south_port)
        c.port("vdd", "metal3", -hx, y_vdd_n)
        c.port("vss", "metal3", -hx, y_vss0a)

    return c, {
        "pitch_x": grid(2 * hx),
        "y_inp": y_inp_m3,
        "y_inn": y_inn_m3,
        "y_vdd_rails": [y_vdd0, y_vdd12, y_vdd_n],
        "y_vss_rails": [y_vss0a, y_vss0b, y_vss1, y_vss23],
    }


def extract_slicer_internal_cpex(pex_path: Path) -> dict[str, dict]:
    """Identify `fn`, `fp`, `outn_b`, `outp_b` directly from `_pex.spice` topology and report their CPEX caps."""
    node_caps = rlc.parse_all_pex_node_caps(pex_path)
    devs = []
    for ln in pex_path.read_text().splitlines():
        if ln.startswith("X"):
            toks = ln.split()
            if len(toks) >= 6:
                devs.append((toks[1], toks[2], toks[3], toks[4], toks[5]))
    inp_terms = set()
    inn_terms = set()
    for d, g, s, b, mdl in devs:
        if mdl == N_LVT and g == "inp":
            inp_terms.update((d, s))
        elif mdl == N_LVT and g == "inn":
            inn_terms.update((d, s))
    shared_tail = inp_terms & inn_terms
    fn_cand = inp_terms - shared_tail
    fp_cand = inn_terms - shared_tail
    fn_net = next(iter(fn_cand)) if len(fn_cand) == 1 else None
    fp_net = next(iter(fp_cand)) if len(fp_cand) == 1 else None

    outn_b_net = outp_b_net = None
    if fn_net and fp_net:
        mn1_terms = set()
        mn2_terms = set()
        for d, g, s, b, mdl in devs:
            if mdl == N_LVT and g == fn_net:
                mn1_terms.update((d, s))
            elif mdl == N_LVT and g == fp_net:
                mn2_terms.update((d, s))
        shared_vbot2 = mn1_terms & mn2_terms
        onb_cand = mn1_terms - shared_vbot2
        opb_cand = mn2_terms - shared_vbot2
        outn_b_net = next(iter(onb_cand)) if len(onb_cand) == 1 else None
        outp_b_net = next(iter(opb_cand)) if len(opb_cand) == 1 else None

    res = {}
    for label, net in (("fn", fn_net), ("fp", fp_net), ("outn_b", outn_b_net), ("outp_b", outp_b_net)):
        if net and net in node_caps:
            res[label] = {"extracted_net": net, **node_caps[net]}
    return res


if __name__ == "__main__":
    import json
    work = rlc.REPO / "results/layout/rx_cmos_v2/dev_slicer/serdes_rx_dt_slicer_pdk"
    work.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(rlc.REPO / "results/layout/rx_cmos_v2/_pdk_cache")
    cell, _meta = build_rx_dt_slicer_pdk(cache, add_ports=True)
    mag = work / "serdes_rx_dt_slicer_pdk.mag"
    ref = work / "serdes_rx_dt_slicer_pdk_ref.spice"
    cell.write(mag)
    ports = rlc.generate_rx_ref_spice("serdes_rx_dt_slicer", "serdes_rx_dt_slicer_pdk", ref)
    rep = rlc.verify_flat_cell(work, "serdes_rx_dt_slicer_pdk", mag, ref, ports)
    print(json.dumps({
        k: rep[k] for k in (
            "width_um", "height_um", "area_um2", "aspect_ratio",
            "drc_total", "drc_rules", "floating_poly",
            "lvs_match", "lvs_property_errors", "lvs_disconnected",
            "port_count_match", "exported_ports", "metal_shares",
        )
    }, indent=2), flush=True)
    pc = rep["parasitics"].get("port_caps_fF", {})
    for k in ("inp", "inn", "clk", "qp", "qn"):
        if k in pc:
            print(f"  CPEX {k:6s}: {pc[k]}", flush=True)
    ic = extract_slicer_internal_cpex(work / "serdes_rx_dt_slicer_pdk_pex.spice")
    for k, v in ic.items():
        print(f"  INT  {k:6s}: {v}", flush=True)
