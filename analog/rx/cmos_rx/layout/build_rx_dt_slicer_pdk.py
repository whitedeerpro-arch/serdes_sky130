#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder for 1 GHz Quarter-Rate Double-Tail Dynamic CMOS Slicer
(`serdes_rx_dt_slicer_pdk`, from frozen `analog/rx/cmos_rx/spice/rx_dt_sampler.spice`).

Refined v2.1 Winged-Trim Abutment-Ready Architecture (`29.40 x ~31.0 um`, mirror axis `X = 0.000`):
  - Exact horizontal abutment pitch `[-14.700, +14.700]` (`29.40 um`) with continuous full-width
    M3 `vdd`, `vss`, `inp`, `inn` rails and 2 continuous full-width NWELL bands for seamless 8x tiling.
  - Centered `X = 0` Comparator + SR Core (`[-6.05, +6.05]`, strict bilateral mirror symmetry):
      * Band 1: Stage-1 Dynamic Pre-Amp (`Xtail`, `Xinp/Xinn` + dummies, `Xpf1/Xpf2/Xpfeq`)
      * Band 2: Stage-2 Dynamic Regenerative Latch (`Xtail2`, `Xpoeq`, `Xmn1/2`, `Xln1/2`, `Xlp1/2`, `Xpo1/2`)
      * Band 3: Isolated Static 6T SR Latch (`Xison/Xisop`, `Xrst/Xset`, `Xkn1/2`, `Xkp1/2`, `qp`/`qn` North)
      * Central M4 `clk` spine along `X = 0.000` (zero P/N skew).
  - Symmetric Left/Right Wings tucked directly beside `fn` / `fp`:
      * Left Wing (`fn`): 2-row shared-gate `L=0.18` binary-weighted MOS-cap trim array (`28.80 um`) right
        next to Stage-1 `Xinp` drain + 6 static trim inverters (`Xt5..Xt0`) in the upper NWELL/PWELL wing bands.
      * Right Wing (`fp`): Exact island-for-island mirror `32:32` (`14.40 + 14.40 = 28.80 um`) MOS-cap
        reference bank right next to Stage-1 `Xinn` drain + `Xref_on`/`Xref_off` drivers in the upper wing bands.
      * Eliminates the old ~22 um vertical `fn/fp` run to a bottom trim bank -> slashes `fn/fp` CPEX and area!
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

SLICE_HALF_X = 14.800


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
    via_xs: tuple[float, ...] = (-13.85, +13.85),
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


def _place_mos_unit(
    c: Cell,
    cache: PdkCache,
    model: str,
    w_f: float,
    l_f: float,
    nf: int,
    cx: float,
    dy: float,
    is_pmos: bool,
    y_rail: float,
    y_d_bus: float,
    y_g: float,
    g_tap_x: float | None = None,
    x_d_span: tuple[float, float] | None = None,
    locali_only_src: bool = False,
    tie_gate: bool = True,
) -> dict:
    """Place a single wing MOS (PMOS or NMOS), strap source to `y_rail`, drain to M2 at `y_d_bus`, and gate at `y_g`."""
    cx, dy = grid(cx), grid(dy)
    m, inf = cache.build_mos(model, w_f, l_f, nf, dy, is_pmos)
    c.include(m, dx=cx)
    s_xs = [grid(cx + x) for x in inf["s_xs"]]
    d_xs = [grid(cx + x) for x in inf["d_xs"]]

    for sx in s_xs:
        locali_v(c, sx, y_rail, dy)
        if not locali_only_src:
            viali_pad(c, sx, dy)
            c.wire("metal1", [(sx, min(y_rail, dy)), (sx, max(y_rail, dy))], 0.290)

    vys = [grid(dy - 0.60), dy, grid(dy + 0.60)] if w_f >= 1.8 else (
        [grid(dy - 0.30), grid(dy + 0.30)] if w_f >= 0.9 else [dy]
    )
    m1_w = 0.290 if (nf == 1 and l_f <= 0.15) else 0.320
    _strap_diff_vertical(c, d_xs, min(vys[0], y_d_bus), max(vys[-1], y_d_bus), vys,
                         y_bus=y_d_bus, m1_w=m1_w, m2_w=0.320, x_bus_span=x_d_span)

    gp = None
    if tie_gate:
        clr = grid(max(0.220, l_f / 2.0 + 0.130))
        y_bar = grid(inf["diff_y2"] + clr) if y_g > dy else grid(inf["diff_y1"] - clr)
        gx_t = grid(g_tap_x if g_tap_x is not None else cx)
        gp = tie_mos_gates(c, cx, inf, y_bar=y_bar, y_cont=y_g, tap_xs=[gx_t])[0]

    return {"cx": cx, "dy": dy, "s_xs": s_xs, "d_xs": d_xs, "g": gp, "inf": inf}


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
        n_vy = [grid(inf_n["dy"] + d) for d in (-0.60, 0.0, +0.60)] if w_fn >= 1.8 else (
            [grid(inf_n["dy"] - 0.50), grid(inf_n["dy"] + 0.50)] if w_fn >= 1.5 else [inf_n["dy"]]
        )
        p_vy = [grid(inf_p["dy"] + d) for d in (-0.60, 0.0, +0.60)] if w_fp >= 1.8 else (
            [grid(inf_p["dy"] - 0.50), grid(inf_p["dy"] + 0.50)] if w_fp >= 1.5 else [inf_p["dy"]]
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


def _place_mos_cap(
    c: Cell,
    cache: PdkCache,
    w_f: float,
    nf: int,
    cx: float,
    dy: float,
    y_gb: float,
    y_gc: float,
    g_taps: list[float],
) -> dict:
    """Place an L=0.18 NMOS MOS-cap island, strap S/D densely on M1, and tie gates to `y_gc`."""
    cx, dy = grid(cx), grid(dy)
    mc, inf = cache.build_mos(N_STD, w_f, 0.18, nf, dy, False)
    c.include(mc, dx=cx)
    sds = [grid(cx + x) for x in inf["all_sd_xs"]]
    if w_f >= 1.6:
        for sx in sds:
            for dvy in (-0.580, 0.000, +0.580):
                viali_pad(c, sx, grid(dy + dvy))
        c.rect("metal1", grid(sds[0] - 0.145), grid(dy - 0.725), grid(sds[-1] + 0.145), grid(dy + 0.725))
    elif w_f >= 0.8:
        for sx in sds:
            viali_pad(c, sx, grid(dy - 0.190))
            viali_pad(c, sx, grid(dy + 0.190))
        c.rect("metal1", grid(sds[0] - 0.145), grid(dy - 0.335), grid(sds[-1] + 0.145), grid(dy + 0.335))
    else:
        for sx in sds:
            viali_pad(c, sx, dy)
        c.wire("metal1", [(sds[0], dy), (sds[-1], dy)], 0.290)
    gpts = tie_mos_gates(c, cx, inf, y_bar=y_gb, y_cont=y_gc, tap_xs=g_taps)
    return {"cx": cx, "dy": dy, "sds": sds, "gpts": gpts, "inf": inf}


def build_rx_dt_slicer_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build `serdes_rx_dt_slicer_pdk` (ports: inp inn clk qp qn t5 t4 t3 t2 t1 t0 vdd vss)."""
    c = Cell()
    hx = SLICE_HALF_X  # 14.700 um -> total width = 29.400 um

    # =========================================================================
    # GLOBAL BAND Y COORDINATES (3-Band Winged Architecture: ~31.0 um tall!)
    # =========================================================================
    y_south_port = -0.900
    y_vss_s      =  0.000   # South VSS abutment rail

    # Band 1: Stage-1 Pre-Amp (Core) + 2-Row Shared-Gate MOS-Cap Trim/Ref Banks (Wings)
    y_cap_a   =  1.800      # Cap Row A (w_f=1.80 -> [0.90, 2.70])
    y_cap_g   =  3.300      # Shared fn/fp gate bar between Row A & Row B!
    y_cap_b   =  4.800      # Cap Row B (w_f=1.80 -> [3.90, 5.70])
    y_st1_n   =  2.650      # Stage-1 NMOS (w_f=3.50 -> [0.90, 4.40])
    y_inp_m3  =  6.250      # Full-width abutment inp M3 bus (centered cleanly between Cap Row B & Row P1!)
    y_inn_m3  =  7.050      # Full-width abutment inn M3 bus
    y_st1_pg  =  7.850      # Stage-1 PMOS clk gate + Wing P1 gate channel
    y_st1_p   =  9.450      # Stage-1 PMOS (w_f=1.80) & Wing P1 (w_f=2.00 -> [8.45, 10.45])
    y_vdd_mid = 11.300      # Shared VDD abutment rail (NWELL Band A: [8.00, 15.15])

    # Band 2: Stage-2 Regenerative Latch (Core) + Wing P2/N2 Trim Drivers (Wings)
    y_st2_p    = 13.300     # Stage-2 PMOS (w_f=2.25 -> [12.175, 14.425]) & Wing P2 (w_f=2.00)
    y_s2_clk_p = 14.850     # Stage-2 PMOS clk gate
    y_cc_onb   = 15.550     # outn_b cross-couple
    y_cc_opb   = 16.350     # outp_b cross-couple
    y_st2_n    = 18.450     # Stage-2 NMOS (w_f=2.40 -> [17.25, 19.65]) & Wing N2 (w_f=2.00)
    y_vss_mid  = 20.750     # Shared VSS abutment rail

    # Band 3: Isolated 6T SR Latch (Core) + Wing N3/P3 Trim Drivers (Wings)
    y_sr_n       = 22.800   # SR NMOS (w_f=2.40 -> [21.60, 24.00]) & Wing N3 (w_f=2.00/1.00)
    y_sr_ch1     = 24.800   # qp / iso / wing gate channel
    y_sr_ch2     = 25.600   # qn channel
    y_sr_p       = 27.550   # SR PMOS (w_f=1.60) & Wing P3 (w_f=2.00 -> [26.55, 28.55])
    y_vdd_n      = 29.350   # North VDD abutment rail (NWELL Band C: [26.10, 29.95])
    y_north_port = 30.250

    # Continuous full-width NWELL bands (2 clean bands -> seamless 8x horizontal abutment!)
    c.rect("nwell", -hx,  8.000, +hx, 15.150)
    c.rect("nwell", -hx, 26.100, +hx, 29.950)

    x_vss_sp = 13.980
    x_vdd_sp = 14.530

    for yv in (y_vss_s, y_vss_mid):
        _draw_abut_rail(c, yv, "psubdiff", hx=hx, via_xs=(-x_vss_sp, +x_vss_sp))
    for yv in (y_vdd_mid, y_vdd_n):
        _draw_abut_rail(c, yv, "nsubdiff", hx=hx, via_xs=(-x_vdd_sp, +x_vdd_sp))

    for sgn in (-1, +1):
        xv_d = grid(sgn * x_vdd_sp)
        xv_s = grid(sgn * x_vss_sp)
        c.wire("metal2", [(xv_d, y_vdd_mid), (xv_d, y_vdd_n)], 0.320)
        c.wire("metal2", [(xv_s, y_vss_s), (xv_s, y_vss_mid)], 0.320)

    # =========================================================================
    # CENTER SPINE (X = 0): Stage-1 Pre-Amp + Stage-2 Latch + 6T SR Latch
    # =========================================================================
    # --- Stage-1 NMOS (`Xtail`, `Xinp`, `Xinn`, dummies) ---
    m_st1_tail, inf_st1_tail = cache.build_mos(N_LVT, 3.50, 0.15, 2, y_st1_n, False)
    m_st1_in,   inf_st1_in   = cache.build_mos(N_LVT, 3.50, 0.18, 4, y_st1_n, False)
    c.include(m_st1_tail, dx=0.000)
    cx_in = 3.000
    c.include(m_st1_in, dx=-cx_in)
    c.include(m_st1_in, dx=+cx_in)

    for sgn in (-1, +1):
        xd = grid(sgn * (cx_in + inf_st1_in["hw_diff"] + 0.140 + 0.090))
        pt = add_tied_poly_dummy(c, xd, inf_st1_in["poly_y1"], inf_st1_in["poly_y2"], 0.18,
                                 y_cont=grid(y_st1_n - 1.950), x_cont=grid(xd + sgn * 0.100))
        c.wire("metal1", [pt, (pt[0], y_vss_s)], 0.290)

    y_st1_tail_bus = grid(y_st1_n - 1.000)  # 1.650
    for sx in inf_st1_tail["s_xs"]:
        locali_v(c, sx, y_vss_s, y_st1_n)
        _strap_diff_vertical(c, [sx], y_vss_s, grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)])
    _strap_diff_vertical(c, inf_st1_tail["d_xs"], grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                         [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)], y_bus=y_st1_tail_bus)

    y_st1_fn_bus = grid(y_st1_n + 1.000)    # 3.650
    x_fn_sp = 6.200                         # Single straight vertical fn/fp M2 spine (3.30 -> 15.80, ZERO jogs!)
    all_tail_xs = list(inf_st1_tail["d_xs"])
    for sgn in (-1, +1):
        cx = grid(sgn * cx_in)
        xf = grid(sgn * x_fn_sp)
        s_xs = [grid(cx + x) for x in inf_st1_in["s_xs"]]
        d_xs = [grid(cx + x) for x in inf_st1_in["d_xs"]]
        all_tail_xs.extend(s_xs)
        _strap_diff_vertical(c, s_xs, grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)], y_bus=y_st1_tail_bus)
        _strap_diff_vertical(c, d_xs, grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)], y_bus=y_st1_fn_bus,
                             x_bus_span=(min(d_xs[0], xf), max(d_xs[-1], xf)))
        c.wire("metal2", [(xf, y_cap_g), (xf, y_st1_p)], 0.340)
    c.wire("metal2", [(min(all_tail_xs), y_st1_tail_bus), (max(all_tail_xs), y_st1_tail_bus)], 0.360)

    # Full-width horizontal abutment `inp` & `inn` M3 buses + exact mirror gate taps
    c.rect("metal3", -hx, grid(y_inp_m3 - 0.200), +hx, grid(y_inp_m3 + 0.200))
    c.rect("metal3", -hx, grid(y_inn_m3 - 0.200), +hx, grid(y_inn_m3 + 0.200))
    y_in_gc = grid((y_inp_m3 + y_inn_m3) / 2.0)  # 5.650
    for sgn, y_m3 in ((-1, y_inp_m3), (+1, y_inn_m3)):
        cx = grid(sgn * cx_in)
        tx = grid(sgn * 2.550)
        tie_mos_gates(c, cx, inf_st1_in, y_bar=grid(y_st1_n + 2.100), y_cont=y_in_gc, tap_xs=[tx])
        via1_clean(c, tx, y_in_gc)
        c.wire("metal2", [(tx, min(y_in_gc, y_m3)), (tx, max(y_in_gc, y_m3))], 0.320)
        via2_clean(c, tx, y_m3)

    # Xtail gate (`clk`) -> M2 under inp/inn M3 -> Stage-1 PMOS clk gate bar at y_st1_pg
    y_tail_gc = grid(y_st1_n + 2.200)
    tie_mos_gates(c, 0.000, inf_st1_tail, y_bar=grid(y_st1_n + 2.050), y_cont=y_tail_gc, tap_xs=[0.000])
    via1_clean(c, 0.000, y_tail_gc)
    c.wire("metal2", [(0.000, y_tail_gc), (0.000, y_st1_pg)], 0.320)

    # --- Stage-1 PMOS (`Xpfeq`, `Xpf1`, `Xpf2`) ---
    m_pfeq, inf_pfeq = cache.build_mos(P_STD, 2.10, 0.18, 1, y_st1_p, True)
    m_pf,   inf_pf   = cache.build_mos(P_STD, 1.70, 0.15, 3, y_st1_p, True)
    c.include(m_pfeq, dx=0.000)
    c.include(m_pf,   dx=-cx_in)
    c.include(m_pf,   dx=+cx_in)

    for sgn in (-1, +1):
        cx = grid(sgn * cx_in)
        for sx in [grid(cx + x) for x in inf_pf["s_xs"]]:
            locali_v(c, sx, y_st1_p, y_vdd_mid)
            _strap_diff_vertical(c, [sx], grid(y_st1_p - 0.50), y_vdd_mid,
                                 [grid(y_st1_p - 0.45), grid(y_st1_p + 0.45)], m1_w=0.280)
        pf_ds = [grid(cx + x) for x in inf_pf["d_xs"]]
        _strap_diff_vertical(c, pf_ds, grid(y_st1_p - 0.50), grid(y_st1_p + 0.50),
                             [grid(y_st1_p - 0.45), grid(y_st1_p + 0.45)], y_bus=y_st1_p, m1_w=0.280)
        x_eq_d = grid(inf_pfeq["s_xs"][0] if sgn < 0 else inf_pfeq["d_xs"][0])
        viali_pad(c, x_eq_d, y_st1_p)
        via1_clean(c, x_eq_d, y_st1_p)
        all_p1d = [grid(sgn * x_fn_sp), x_eq_d] + pf_ds
        c.wire("metal2", [(min(all_p1d), y_st1_p), (max(all_p1d), y_st1_p)], 0.320)

    tie_mos_gates(c, 0.000,  inf_pfeq, y_bar=grid(y_st1_p - 1.250), y_cont=y_st1_pg, tap_xs=[0.000])
    tie_mos_gates(c, -cx_in, inf_pf,   y_bar=grid(y_st1_p - 1.150), y_cont=y_st1_pg, tap_xs=[-cx_in])
    tie_mos_gates(c, +cx_in, inf_pf,   y_bar=grid(y_st1_p - 1.150), y_cont=y_st1_pg, tap_xs=[+cx_in])
    c.wire("metal1", [(-cx_in, y_st1_pg), (+cx_in, y_st1_pg)], 0.290)
    via1_clean(c, 0.000, y_st1_pg)
    via2_clean(c, 0.000, y_st1_pg)
    via3_pad(c, 0.000, y_st1_pg)

    # --- Stage-2 Dynamic Regenerative Latch (`Xpoeq`, `Xlp`, `Xpo`, `Xtail2`, `Xln`, `Xmn`) ---
    cx_lp = 2.600
    cx_po = 5.200
    cx_po_p = 4.950
    m_poeq, inf_poeq = cache.build_mos(P_STD, 2.10, 0.18, 1, y_st2_p, True)
    m_lp,   inf_lp   = cache.build_mos(P_STD, 2.25, 0.18, 4, y_st2_p, True)
    m_po,   inf_po   = cache.build_mos(P_STD, 1.70, 0.15, 3, y_st2_p, True)
    c.include(m_poeq, dx=0.000)
    for sgn in (-1, +1):
        c.include(m_lp, dx=grid(sgn * cx_lp))
        c.include(m_po, dx=grid(sgn * cx_po_p))

    for sgn in (-1, +1):
        for sx in [grid(sgn * cx_lp + x) for x in inf_lp["s_xs"]]:
            locali_v(c, sx, y_vdd_mid, y_st2_p)
            _strap_diff_vertical(c, [sx], y_vdd_mid, grid(y_st2_p + 0.70),
                                 [grid(y_st2_p - 0.65), grid(y_st2_p + 0.65)])
        for sx in [grid(sgn * cx_po_p + x) for x in inf_po["s_xs"]]:
            locali_v(c, sx, y_vdd_mid, y_st2_p)
            _strap_diff_vertical(c, [sx], y_vdd_mid, grid(y_st2_p + 0.50),
                                 [grid(y_st2_p - 0.45), grid(y_st2_p + 0.45)], m1_w=0.280)
        x_eq_d = grid(inf_poeq["s_xs"][0] if sgn < 0 else inf_poeq["d_xs"][0])
        viali_pad(c, x_eq_d, y_st2_p)
        via1_clean(c, x_eq_d, y_st2_p)
        lp_ds = [grid(sgn * cx_lp + x) for x in inf_lp["d_xs"]]
        po_ds = [grid(sgn * cx_po_p + x) for x in inf_po["d_xs"]]
        _strap_diff_vertical(c, lp_ds, grid(y_st2_p - 0.70), grid(y_st2_p + 0.70),
                             [grid(y_st2_p - 0.65), grid(y_st2_p + 0.65)], y_bus=y_st2_p)
        _strap_diff_vertical(c, po_ds, grid(y_st2_p - 0.50), grid(y_st2_p + 0.50),
                             [grid(y_st2_p - 0.45), grid(y_st2_p + 0.45)], y_bus=y_st2_p, m1_w=0.280)
        all_ds = [x_eq_d] + lp_ds + po_ds
        c.wire("metal2", [(min(all_ds), y_st2_p), (max(all_ds), y_st2_p)], 0.320)

    tie_mos_gates(c, 0.000,    inf_poeq, y_bar=grid(y_st2_p + 1.250), y_cont=y_s2_clk_p, tap_xs=[0.000])
    tie_mos_gates(c, -cx_po_p, inf_po,   y_bar=grid(y_st2_p + 1.150), y_cont=y_s2_clk_p, tap_xs=[-cx_po_p])
    tie_mos_gates(c, +cx_po_p, inf_po,   y_bar=grid(y_st2_p + 1.150), y_cont=y_s2_clk_p, tap_xs=[+cx_po_p])
    for xck in (-cx_po_p, 0.000, +cx_po_p):
        via1_clean(c, xck, y_s2_clk_p)
        via2_clean(c, xck, y_s2_clk_p)
    via3_pad(c, 0.000, y_s2_clk_p)
    c.wire("metal3", [(-cx_po_p, y_s2_clk_p), (+cx_po_p, y_s2_clk_p)], 0.360)

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
        locali_v(c, sx, y_st2_n, y_vss_mid)
        _strap_diff_vertical(c, [sx], grid(y_st2_n - 0.45), y_vss_mid,
                             [grid(y_st2_n - 0.35), grid(y_st2_n + 0.35)])
    _strap_diff_vertical(c, inf_tail2["d_xs"], grid(y_st2_n - 0.50), grid(y_st2_n + 0.50),
                         [grid(y_st2_n - 0.35), grid(y_st2_n + 0.35)], y_bus=y_vbot2)

    vbot2_xs = list(inf_tail2["d_xs"])
    x_ob_core = 4.100
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
        x_ob = grid(sgn * x_ob_core)
        c.wire("metal2", [(x_ob, y_st2_p), (x_ob, y_s2_n_out)], 0.360)
    c.wire("metal2", [(min(vbot2_xs), y_vbot2), (max(vbot2_xs), y_vbot2)], 0.380)

    y_tail2_g = grid(y_st2_n - 1.250)
    tie_mos_gates(c, 0.000, inf_tail2, y_bar=grid(y_st2_n - 1.000), y_cont=y_tail2_g, tap_xs=[0.000])
    via1_clean(c, 0.000, y_tail2_g)
    via2_clean(c, 0.000, y_tail2_g)
    via3_pad(c, 0.000, y_tail2_g)

    # Central `clk` vertical M4 spine along `X = 0.000` (only ~17.3 um long -> low clk CPEX!)
    c.wire("metal4", [(0.000, y_south_port), (0.000, y_tail2_g)], 0.440)

    # Straight vertical `fn` / `fp` from Stage-1 PMOS (`y_st1_p`) -> Stage-2 `Xmn1/2.G` (`y_mn_g`) at `±x_fn_sp`!
    y_mn_g = grid(y_st2_n - 1.850)  # 15.800
    for sgn in (-1, +1):
        xf = grid(sgn * x_fn_sp)
        cx = grid(sgn * cx_po)
        c.wire("metal2", [(xf, y_st1_p), (xf, y_mn_g)], 0.340)
        via1_clean(c, xf, y_mn_g)
        gp = tie_mos_gates(c, cx, inf_mn, y_bar=grid(y_st2_n - 1.450), y_cont=y_mn_g, tap_xs=[cx])[0]
        c.wire("metal1", sorted([(xf, y_mn_g), gp], key=lambda p: p[0]), 0.290)

    # Stage-2 Cross-Coupling (`outn_b`, `outp_b`) — EXACT MIRROR
    for sgn, y_cc in ((-1, y_cc_opb), (+1, y_cc_onb)):
        cx = grid(sgn * cx_lp)
        tie_mos_gates(c, cx, inf_lp, y_bar=grid(y_st2_p + 1.400), y_cont=y_cc, tap_xs=[cx])
        tie_mos_gates(c, cx, inf_ln, y_bar=grid(y_st2_n - 1.250), y_cont=y_cc, tap_xs=[cx])
    via1_clean(c, -x_ob_core, y_cc_onb)
    c.wire("metal1", [(-x_ob_core, y_cc_onb), (+cx_lp, y_cc_onb)], 0.290)
    via1_clean(c, +x_ob_core, y_cc_opb)
    c.wire("metal1", [(-cx_lp, y_cc_opb), (+x_ob_core, y_cc_opb)], 0.290)

    # --- Band 3: Isolated 6T Static SR Latch ---
    cx_iso = 5.200
    cx_sr  = 3.100
    cx_kp  = 1.300

    u_ison = _place_inv_block(
        c, cache, cx=-cx_iso, wn=1.5, nfn=1, wp=3.2, nfp=2,
        y_n=y_sr_n, y_p=y_sr_p, y_vss=y_vss_mid, y_vdd=y_vdd_n,
        y_g=y_sr_ch1, y_nd=y_sr_n, y_pd=y_sr_p,
        l_f=0.15, n_model=N_LVT, p_model=P_LVT, l_p=0.35,
        x_out_drop=-4.300, locali_only_src=True,
    )
    u_isop = _place_inv_block(
        c, cache, cx=+cx_iso, wn=1.5, nfn=1, wp=3.2, nfp=2,
        y_n=y_sr_n, y_p=y_sr_p, y_vss=y_vss_mid, y_vdd=y_vdd_n,
        y_g=y_sr_ch1, y_nd=y_sr_n, y_pd=y_sr_p,
        l_f=0.15, n_model=N_LVT, p_model=P_LVT, l_p=0.35,
        x_out_drop=+4.300, locali_only_src=True,
    )
    for sgn, u_iso in ((-1, u_ison), (+1, u_isop)):
        xo = grid(sgn * x_fn_sp)  # ±6.250 (strictly above fn/fp which ended at y=15.80!)
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
            locali_v(c, sx, y_vss_mid, y_sr_n)
            _strap_diff_vertical(c, [sx], y_vss_mid, grid(y_sr_n + 0.80),
                                 [grid(y_sr_n - 0.70), grid(y_sr_n + 0.70)])
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
        locali_v(c, x_kn_s, y_vss_mid, y_sr_n)
        _strap_diff_vertical(c, [x_kn_d], grid(y_sr_n - 0.25), grid(y_sr_n + 0.25), [y_sr_n], y_bus=y_sr_n, m1_w=0.290)

        for sx in [grid(cx + x) for x in inf_kp["s_xs"]]:
            locali_v(c, sx, y_sr_p, y_vdd_n)
            _strap_diff_vertical(c, [sx], grid(y_sr_p - 0.40), y_vdd_n,
                                 [grid(y_sr_p - 0.35), grid(y_sr_p + 0.35)])
        x_kp_d = grid(cx + inf_kp["d_xs"][0])
        _strap_diff_vertical(c, [x_kp_d], grid(y_sr_p - 0.40), grid(y_sr_p + 0.40),
                             [grid(y_sr_p - 0.35), grid(y_sr_p + 0.35)], y_bus=y_sr_p)

        x_q_out = grid(sgn * 2.250)
        c.wire("metal2", sorted([(grid(sgn * cx_sr), y_sr_n), (x_kn_d, y_sr_n)], key=lambda p: p[0]), 0.320)
        c.wire("metal2", sorted([(x_kp_d, y_sr_p), (x_q_out, y_sr_p)], key=lambda p: p[0]), 0.320)
        c.wire("metal2", [(x_q_out, y_sr_n), (x_q_out, y_north_port)], 0.340)

    for sgn, y_qcc in ((-1, y_sr_ch2), (+1, y_sr_ch1)):
        cx = grid(sgn * cx_kp)
        tie_mos_gates(c, cx, inf_kn, y_bar=grid(y_sr_n + 0.800), y_cont=y_qcc, tap_xs=[cx])
        tie_mos_gates(c, cx, inf_kp, y_bar=grid(y_sr_p - 1.100), y_cont=y_qcc, tap_xs=[cx])
    via1_clean(c, -2.250, y_sr_ch1)
    c.wire("metal1", [(-2.250, y_sr_ch1), (+cx_kp, y_sr_ch1)], 0.290)
    via1_clean(c, +2.250, y_sr_ch2)
    c.wire("metal1", [(-cx_kp, y_sr_ch2), (+2.250, y_sr_ch2)], 0.290)

    # =========================================================================
    # SYMMETRIC LEFT (`fn`) & RIGHT (`fp`) WINGED MOS-CAP BANKS (Band 0)
    # Exact island-for-island, finger-for-finger mirror (28.80 um : 28.80 um)!
    # All Row A & Row B gate contacts on y_cap_g = 3.300 are spaced >= 0.60 um apart (ZERO mcon/li/poly DRC!).
    #   Row A (y = 1.80): MSB (8x1.80 @ +-11.35), b1/ref (1x0.90 @ +-8.35), dum/ref (1x0.45 @ +-5.65)
    #   Row B (y = 4.80): b0/ref (1x0.45 @ +-13.10), b4/ref (4x1.80 @ +-10.35),
    #                     b3/ref (2x1.80 @ +-8.25),  b2/ref (1x1.80 @ +-6.95)
    #   Shared gate M1 bar at y_cap_g = 3.300 feeds directly into fn/fp at x = +-6.250!
    # =========================================================================
    # Single flush 0.34 um poly gate bar at y_cap_g = 3.300 for BOTH Row A & Row B (ZERO poly.2 notches!)
    y_gba = y_cap_g
    y_gbb = y_cap_g

    # Left Wing (`fn`): binary-weighted 28.80 um (14.40 + 7.20 + 3.60 + 1.80 + 0.90 + 0.45 + 0.45)
    cap_a_left = [
        ("c5", 1.80, 8, -11.350, [-12.350, -11.150]),
        ("c1", 0.90, 1,  -8.350, [-8.350]),
        ("cd", 0.45, 1,  -5.650, [-5.650]),
    ]
    cap_b_left = [
        ("c0", 0.45, 1, -13.100, [-13.100]),
        ("c4", 1.80, 4, -10.350, [-10.350, -9.550]),
        ("c3", 1.80, 2,  -8.350, [-8.350]),
        ("c2", 1.80, 1,  -6.950, [-6.950]),
    ]
    # Right Wing (`fp`): uniform w_f = 1.80 um for Xcp_on (8x1.80=14.40) & Xcp_off ((1+4+2+1)x1.80=14.40 -> ZERO LVS prop_err!)
    cap_a_right = [
        ("cp_on",   1.80, 8, +11.350, [+11.150, +12.350]),
        ("cp_off1", 1.80, 1,  +8.350, [+8.350]),
    ]
    cap_b_right = [
        ("cp_off4", 1.80, 4, +10.350, [+9.550, +10.350]),
        ("cp_off3", 1.80, 2,  +8.350, [+8.350]),
        ("cp_off2", 1.80, 1,  +6.950, [+6.950]),
    ]

    for sgn, row_a, row_b in ((-1, cap_a_left, cap_b_left), (+1, cap_a_right, cap_b_right)):
        all_gxs: list[float] = [grid(sgn * x_fn_sp)]
        poly_xs: list[float] = []
        for _nm, wf, nf, cx, taps in row_a:
            u = _place_mos_cap(c, cache, wf, nf, cx, y_cap_a, y_gba, y_cap_g, taps)
            all_gxs.extend(taps)
            poly_xs.extend([grid(cx + g) for g in u["inf"]["g_xs"]] + taps)
        for _nm, wf, nf, cx, taps in row_b:
            u = _place_mos_cap(c, cache, wf, nf, cx, y_cap_b, y_gbb, y_cap_g, taps)
            all_gxs.extend(taps)
            poly_xs.extend([grid(cx + g) for g in u["inf"]["g_xs"]] + taps)
        # Flush 0.34 um poly spine matching poly_cont_pad height [3.13, 3.47] -> ZERO poly.2 notches!
        c.rect("poly", grid(min(poly_xs) - 0.135), grid(y_cap_g - 0.170),
               grid(max(poly_xs) + 0.135), grid(y_cap_g + 0.170))
        # Exact mirror M1 gate bar span ([+-5.65 .. +-13.10]) so fn and fp see identical M1 length & environment!
        xm1_a, xm1_b = sorted((grid(sgn * 5.650), grid(sgn * 13.100)))
        c.wire("metal1", [(xm1_a, y_cap_g), (xm1_b, y_cap_g)], 0.290)
        via1_clean(c, grid(sgn * x_fn_sp), y_cap_g)

    # Connect Left `Xcnd` (-5.65, y_cap_a) <-> Right `r_off` vertical spine (+8.80, y_cap_a) cleanly on M2 at y = 0.650!
    y_roff_tie = 0.650
    via1_clean(c, -5.650, y_cap_a)
    c.wire("metal2", [(-5.650, y_cap_a), (-5.650, y_roff_tie), (+8.800, y_roff_tie), (+8.800, y_cap_a)], 0.320)

    # =========================================================================
    # LEFT WING TRIM INVERTERS (`Xt5..Xt0`, L=0.18, inside Band 1P / 2P / 2N / 3N / 3P)
    #   Band 1/2 drivers (`t5, t3, t2`): live strictly <= y_st2_n
    #   Band 3 drivers (`t4, t1, t0`):   live strictly in N3/P3, gate at y_w3_g
    #   ALL 6 M4 gate trunks have >= 0.85 um pitch AND >= 0.22 um M2 clearance at every via!
    # =========================================================================
    y_wp1_g = y_st1_pg                #  7.750
    y_wp2_g = y_s2_clk_p              # 14.750
    y_wn2_g = grid(y_st2_n - 1.600)   # 16.750
    y_w3_g  = y_sr_ch1                # 24.700

    # Dedicated non-overlapping M2 vertical drain drop tracks in Left Wing:
    x_tb0 = -13.450          # -> Xcn0 @ -13.10
    x_tb5 = -12.150          # -> Xcn5 @ -11.35
    x_tb4 =  -9.400          # -> Xcn4 @ -10.35
    x_tb1 =  -8.800          # -> Xcn1 @ -8.35
    x_tb3 =  -7.950          # -> Xcn3 @ -8.35
    x_tb2 =  -6.730          # -> Xcn2 @ -6.95 (ZERO crossing with fn=-6.20!)

    # Dedicated non-overlapping M4 gate trunk X coordinates (>= 0.85 um pitch, ZERO M2 collision!):
    xg_t0 = -12.750
    xg_t4 = -11.850
    xg_t5 = -10.950
    xg_t3 = -10.050
    xg_t1 =  -8.150
    xg_t2 =  -7.300

    # 1. Xt5 (N: 8x2.00 @ N2, P: 8x2.00 @ P1 + 8x2.00 @ P2 -> exact N=16, P=32)
    cx_t5 = -11.350
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 8, cx_t5, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=xg_t5)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 8, cx_t5, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=xg_t5)
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 8, cx_t5, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xg_t5)
    c.wire("metal2", [(x_tb5, y_cap_a), (x_tb5, y_st2_n)], 0.400)
    for xv in (-12.350, -11.350, -10.350):
        via1_clean(c, xv, y_cap_a)
    c.wire("metal2", [(-12.350, y_cap_a), (-10.350, y_cap_a)], 0.440)

    # 2. Xt3 (N: 2x2.00 @ N2, P: 4x2.00 @ P1 -> exact N=4, P=8)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, -7.850, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=-8.150, x_d_span=(-8.330, -7.370))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 2, -8.300, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=-8.300, x_d_span=(-8.300, x_tb3))
    c.wire("metal1", [(xg_t3, y_wp1_g), (-8.150, y_wp1_g)], 0.290)
    c.wire("metal1", [(xg_t3, y_wn2_g), (-8.300, y_wn2_g)], 0.290)
    c.wire("metal2", [(x_tb3, y_cap_b), (x_tb3, y_st2_n)], 0.300)
    c.wire("metal2", [(-8.350, y_cap_b), (x_tb3, y_cap_b)], 0.320)
    via1_clean(c, -8.350, y_cap_b)

    # 3. Xt2 (N: 1x2.00 @ N2, P: 2x2.00 @ P2 -> exact N=2, P=4; mirrored N at -7.00 so source is clear of outn_b=-6.20!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 2, -7.050, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=xg_t2, x_d_span=(-7.050, x_tb2))
    m_t2n, inf_t2n = cache.build_mos(N_STD, 2.00, 0.18, 1, y_st2_n, False)
    cx_t2n = -7.000
    c.include(m_t2n, dx=cx_t2n)
    x_t2n_s = grid(cx_t2n + inf_t2n["d_xs"][0])  # right SD = -6.760 -> VSS
    x_t2n_d = grid(cx_t2n + inf_t2n["s_xs"][0])  # left  SD = -7.240 -> tb2!
    locali_v(c, x_t2n_s, y_vss_mid, y_st2_n)
    viali_pad(c, x_t2n_s, y_st2_n)
    c.wire("metal1", [(x_t2n_s, y_st2_n), (x_t2n_s, y_vss_mid)], 0.290)
    _strap_diff_vertical(c, [x_t2n_d], grid(y_st2_n - 0.60), grid(y_st2_n + 0.60),
                         [grid(y_st2_n - 0.60), y_st2_n, grid(y_st2_n + 0.60)],
                         y_bus=y_st2_n, m1_w=0.320, m2_w=0.320, x_bus_span=(x_t2n_d, x_tb2))
    tie_mos_gates(c, cx_t2n, inf_t2n, y_bar=grid(inf_t2n["diff_y1"] - 0.220), y_cont=y_wn2_g, tap_xs=[xg_t2])
    c.wire("metal2", [(x_tb2, y_cap_b), (x_tb2, y_st2_n)], 0.280)
    c.wire("metal2", [(-6.950, y_cap_b), (x_tb2, y_cap_b)], 0.320)
    via1_clean(c, -6.950, y_cap_b)

    # 4. Xt4 (N: 4x2.00 @ N3, P: 8x2.00 @ P3 -> exact N=8, P=16)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 8, -10.750, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xg_t4, x_d_span=(-12.190, -9.310))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 4, -10.500, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xg_t4, x_d_span=(-10.980, x_tb4))
    c.wire("metal2", [(x_tb4, y_cap_b), (x_tb4, y_sr_p)], 0.340)
    c.wire("metal2", [(-10.350, y_cap_b), (x_tb4, y_cap_b)], 0.340)
    via1_clean(c, -10.350, y_cap_b)
    via1_clean(c, x_tb4, y_cap_b)

    # 5. Xt1 (N: 1x1.00 @ N3, P: 1x2.00 @ P3 -> exact N=1, P=2)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, -7.650, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xg_t1, x_d_span=(x_tb1, -7.410))
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, -8.500, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xg_t1, x_d_span=(x_tb1, -8.260))
    c.wire("metal2", [(x_tb1, y_cap_a), (x_tb1, y_sr_p)], 0.280)
    c.wire("metal2", [(x_tb1, y_cap_a), (-8.350, y_cap_a)], 0.320)
    via1_clean(c, -8.350, y_cap_a)

    # 6. Xt0 (N: 1x1.00 @ N3, P: 1x2.00 @ P3 -> exact N=1, P=2; gate tap at -13.15 -> M1 east to xg_t0=-12.75!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, -13.480, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=-13.150, x_d_span=(x_tb0, -13.240))
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, -13.150, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=-13.150, x_d_span=(x_tb0, -12.910))
    c.wire("metal1", [(-13.150, y_w3_g), (xg_t0, y_w3_g)], 0.290)
    c.wire("metal2", [(x_tb0, y_cap_b), (x_tb0, y_sr_p)], 0.280)
    c.wire("metal2", [(x_tb0, y_cap_b), (-13.100, y_cap_b)], 0.320)
    via1_clean(c, -13.100, y_cap_b)

    # Vertical M4 `t5..t0` South Port Trunks (>= 0.85 um pitch, ZERO M2 collision!)
    t_port_specs = [
        ("t0", xg_t0, [y_w3_g]),
        ("t4", xg_t4, [y_w3_g]),
        ("t5", xg_t5, [y_wp1_g, y_wp2_g, y_wn2_g]),
        ("t3", xg_t3, [y_wp1_g, y_wn2_g]),
        ("t1", xg_t1, [y_w3_g]),
        ("t2", xg_t2, [y_wp2_g, y_wn2_g]),
    ]
    t_port_xs: dict[str, float] = {}
    for tnm, xt, y_hits in t_port_specs:
        t_port_xs[tnm] = xt
        for yh in y_hits:
            via1_clean(c, xt, yh)
            via2_clean(c, xt, yh)
            via3_pad(c, xt, yh)
        c.wire("metal4", [(xt, y_south_port), (xt, max(y_hits))], 0.380)

    # =========================================================================
    # RIGHT WING REF INVERTERS (`Xref_on` & `Xref_off`, L=0.18, mirror-packed!)
    # =========================================================================
    # 1. Xref_on (input tied to VDD; N: 8x2.00 @ N2, P: 8x2.00 @ P1 + 8x2.00 @ P2)
    cx_ron = +11.350
    x_ron_dr = +12.150  # EXACT mirror of x_tb5 (-12.150) crossing y_cap_g!
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 8, cx_ron, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=+13.350)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 8, cx_ron, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=+13.350)
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 8, cx_ron, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=+13.350)
    for yg in (y_wp1_g, y_wp2_g, y_wn2_g):
        via1_clean(c, +13.350, yg)
    via1_clean(c, +13.350, y_vdd_mid)
    c.wire("metal2", [(+13.350, y_wp1_g), (+13.350, y_wn2_g)], 0.280)

    c.wire("metal2", [(x_ron_dr, y_cap_a), (x_ron_dr, y_st2_n)], 0.400)
    for xv in (+10.350, +11.350, +12.350):
        via1_clean(c, xv, y_cap_a)
    c.wire("metal2", [(+10.350, y_cap_a), (+12.350, y_cap_a)], 0.440)

    # 2. Xref_off (input tied to VSS; N: 8x2.00 @ N3, P: 4x2.00 @ P1 + 4x2.00 @ P2 + 8x2.00 @ P3)
    x_roff_a = +8.800   # EXACT mirror of x_tb1 (-8.800) crossing y_cap_g!
    x_roff_g = +6.730   # EXACT mirror of x_tb2 (-6.730), clear of fp/outp_b=+6.20 & roff_pa/pb drains >= 7.37!
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, +7.850, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=x_roff_g, x_d_span=(+7.370, x_roff_a))
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, +7.850, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=x_roff_g, x_d_span=(+7.370, x_roff_a))
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 8, +11.200, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=+13.350, x_d_span=(x_roff_a, +12.640))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 8, +11.200, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=+13.350, x_d_span=(x_roff_a, +12.640))

    via1_clean(c, +13.350, y_w3_g)
    via1_clean(c, +13.350, y_vss_mid)
    c.wire("metal2", [(+13.350, y_vss_mid), (+13.350, y_w3_g)], 0.280)
    for yg in (y_wp1_g, y_wp2_g, y_vss_mid):
        via1_clean(c, x_roff_g, yg)
    # Extend VSS M2 shield along x_roff_g (+6.73) up to y_sr_ch1 to match Left Wing neighbor environment on outp_b!
    c.wire("metal2", [(x_roff_g, y_wp1_g), (x_roff_g, y_sr_ch1)], 0.280)

    # Connect `r_off` down to ALL Right uniform-1.80 `Xcp_off` islands + low-R mirror straps across Row A/B!
    c.wire("metal2", [(x_roff_a, y_cap_a), (x_roff_a, y_sr_p)], 0.360)
    c.wire("metal2", [(+6.950, y_cap_b), (+10.750, y_cap_b)], 0.340)
    for xr in (+6.950, +8.350, +9.950, +10.750):
        via1_clean(c, xr, y_cap_b)
    c.wire("metal2", [(+8.350, y_cap_a), (x_roff_a, y_cap_a)], 0.320)
    via1_clean(c, +8.350, y_cap_a)
    # Mirror-matched low-R `r_off` vertical straps across y_cap_g (all >= 0.19 um clear of +8.35 via1 & +8.80 spine & +10.35 r_on!)
    for xmr in (+6.950, +7.850, +9.450):
        c.wire("metal2", [(xmr, y_roff_tie), (xmr, y_cap_b)], 0.300)
    c.wire("metal2", [(+6.950, y_roff_tie), (+9.450, y_roff_tie)], 0.320)
    # Low-R `r_on` secondary vertical straps across y_cap_g (mirroring Left Wing density over fn, clear of Row B 4.80!)
    c.wire("metal2", [(+10.350, y_cap_a), (+12.850, y_cap_a)], 0.440)
    via1_clean(c, +12.850, y_cap_a)
    for xon_s in (+10.650, +11.400, +12.850):
        c.wire("metal2", [(xon_s, y_cap_a), (xon_s, 3.950)], 0.320)

    if add_ports:
        c.port("inp", "metal3", -hx, y_inp_m3)
        c.port("inn", "metal3", -hx, y_inn_m3)
        c.port("clk", "metal4", 0.000, y_south_port)
        c.port("qp",  "metal2", -2.250, y_north_port)
        c.port("qn",  "metal2", +2.250, y_north_port)
        for tnm in ("t5", "t4", "t3", "t2", "t1", "t0"):
            c.port(tnm, "metal4", t_port_xs[tnm], y_south_port)
        c.port("vdd", "metal3", -hx, y_vdd_n)
        c.port("vss", "metal3", -hx, y_vss_s)

    return c, {
        "pitch_x": grid(2 * hx),
        "y_inp": y_inp_m3,
        "y_inn": y_inn_m3,
        "y_vdd_rails": [y_vdd_mid, y_vdd_n],
        "y_vss_rails": [y_vss_s, y_vss_mid],
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
    work_root = rlc.REPO / "results/layout/rx_cmos_v2/opt_v2_1/dev_slicer"
    cache = PdkCache(rlc.REPO / "results/layout/rx_cmos_v2/_pdk_cache")
    w = work_root / "serdes_rx_dt_slicer_pdk"
    w.mkdir(parents=True, exist_ok=True)
    cell, _meta = build_rx_dt_slicer_pdk(cache, add_ports=True)
    mag = w / "serdes_rx_dt_slicer_pdk.mag"
    ref = w / "serdes_rx_dt_slicer_pdk_ref.spice"
    cell.write(mag)
    ports = rlc.generate_rx_ref_spice("serdes_rx_dt_slicer", "serdes_rx_dt_slicer_pdk", ref)
    rep = rlc.verify_flat_cell(w, "serdes_rx_dt_slicer_pdk", mag, ref, ports)
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
            print(f"  CPEX {k:5s}: {pc[k]}", flush=True)
    ic = extract_slicer_internal_cpex(w / "serdes_rx_dt_slicer_pdk_pex.spice")
    for k, v in ic.items():
        print(f"  INT  {k:6s}: {v}", flush=True)
