#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder & Signoff Suite for 5.0 Gb/s (1.25 GHz) Hardened
Quarter-Rate StrongARM + 100%-Isolated NMOS-Push-Up SR Slicer (`serdes_rx_dt_slicer_5g_pdk`,
matching `serdes_rx_dt_slicer_5g` in `analog/rx/cmos_rx/spice/rx_dt_sampler_5g.spice`).

1:1 Mechanical & Port Drop-In Replacement for 4G `serdes_rx_dt_slicer_pdk`:
  - Identical bbox `[-14.800, -1.120, +14.800, +30.420]` (`29.60 x 31.54 um`, `SLICE_HALF_X = 14.800`).
  - Identical 4 horizontal abutment supply rails (`vss=0.00, 20.75`; `vdd=11.30, 29.35`), 2 full-width
    NWELL bands (`[8.00, 15.15]` & `[26.10, 29.95]`), and full-width `inp=6.25 / inn=7.05` M3 buses.
  - Identical unbroken central `clk` M4 spine along `X = 0.000` (`y in [-0.900, +17.200]`).
  - Identical 13 port `(name, layer, x, y)` coordinates, `M5 = 0.0%`, Right Wing M4-free,
    and `y in [0.5, 4.5]` M3-free.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
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

REPO = rlc.REPO
SLICE_HALF_X = 14.800
CELL_NAME = "serdes_rx_dt_slicer_5g_pdk"
VARIANT_DIR = HERE / "variants" / "slicer_5g_pdk"
WORK_ROOT = REPO / "results" / "analog" / "rx" / "slicer_5g_hardening_20261125" / "layout_build"
REF_4G_MAG = HERE / "variants" / "v2_pdk" / "serdes_rx_dt_slicer_pdk.mag"


def generate_slicer_5g_ref_spice(out_path: Path, cell_name: str = CELL_NAME) -> list[str]:
    """Flatten `analog/rx/cmos_rx/spice/rx_dt_sampler_5g.spice` into exact SKY130 primitives for Netgen."""
    subckts = rlc._parse_spice_subckts([
        rlc.COMMON_SPICE_DIR / "sky130_primitives.spice",
        rlc.COMMON_SPICE_DIR / "sky130_pfet_lvt.spice",
        rlc.RX_SPICE_DIR / "rx_dt_sampler_5g.spice",
    ])
    top_src = "serdes_rx_dt_slicer_5g"
    top_def = subckts[top_src]
    top_ports = list(top_def["ports"])
    lines: list[str] = [
        f"* Exact flattened LVS reference netlist for {cell_name}",
        f"* Source subckt: {top_src} (analog/rx/cmos_rx/spice/rx_dt_sampler_5g.spice)",
        f".subckt {cell_name} " + " ".join(top_ports),
    ]
    dev_idx = 0

    def expand(sub_name: str, port_map: dict[str, str], env: dict[str, float], prefix: str) -> None:
        nonlocal dev_idx
        sdef = subckts[sub_name]
        local_env = {k: rlc._eval_expr(v, env) for k, v in sdef["defaults"].items()}
        local_env.update(env)
        for inst_name, conns, model, ov in sdef["insts"]:
            mapped_conns = [port_map.get(c, f"{prefix}_{c}") for c in conns]
            child_env = {k: rlc._eval_expr(v, local_env) for k, v in ov.items()}
            if model.startswith("sky130_fd_pr__"):
                dev_idx += 1
                p_strs = [f"w={rlc._fmt_num(child_env['w'])}", f"l={rlc._fmt_num(child_env['l'])}"]
                lines.append(f"X{dev_idx} " + " ".join(mapped_conns) + f" {model} " + " ".join(p_strs))
            elif model in subckts:
                cdef = subckts[model]
                cmap = dict(zip(cdef["ports"], mapped_conns))
                expand(model, cmap, child_env, f"{prefix}_{inst_name}")
            else:
                raise KeyError(f"Unknown model {model} inside {sub_name}")

    init_env = {k: rlc._eval_expr(v, {}) for k, v in top_def["defaults"].items()}
    expand(top_src, {p: p for p in top_ports}, init_env, "t")
    lines.extend([f".ends {cell_name}", ""])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return top_ports


def viali_pad_slim(c: Cell, x: float, y: float) -> None:
    """DRC-clean slim viali M1 pad for L=0.15 um (0.42 um S/D pitch): 0.23x0.37=0.0851 um^2 > met1.6, gap 0.19 > 0.14."""
    x, y = grid(x), grid(y)
    c.pad("viali", x, y, 0.17)
    c.pad("metal1", x, y, 0.23, 0.37)


def _strap_diff_vertical(
    c: Cell,
    xs: list[float],
    y1: float,
    y2: float,
    y_vias: list[float],
    y_bus: float | None = None,
    m1_w: float = 0.230,
    m2_w: float = 0.340,
    x_bus_span: tuple[float, float] | None = None,
    slim: bool = True,
) -> None:
    pad_fn = viali_pad_slim if slim else viali_pad
    for x in xs:
        x = grid(x)
        for vy in y_vias:
            pad_fn(c, x, vy)
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
    via_xs: tuple[float, ...] = (-13.98, +13.98),
) -> None:
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
    swap_sd: bool = False,
) -> dict:
    cx, dy = grid(cx), grid(dy)
    m, inf = cache.build_mos(model, w_f, l_f, nf, dy, is_pmos)
    c.include(m, dx=cx)
    s_raw = inf["d_xs"] if swap_sd else inf["s_xs"]
    d_raw = inf["s_xs"] if swap_sd else inf["d_xs"]
    s_xs = [grid(cx + x) for x in s_raw]
    d_xs = [grid(cx + x) for x in d_raw]

    for sx in s_xs:
        locali_v(c, sx, y_rail, dy)
        viali_pad_slim(c, sx, dy)
        c.wire("metal1", [(sx, min(y_rail, dy)), (sx, max(y_rail, dy))], 0.230)

    vys = [grid(dy - 0.60), dy, grid(dy + 0.60)] if w_f >= 1.8 else (
        [grid(dy - 0.30), grid(dy + 0.30)] if w_f >= 0.9 else [dy]
    )
    _strap_diff_vertical(c, d_xs, min(vys[0], y_d_bus), max(vys[-1], y_d_bus), vys,
                         y_bus=y_d_bus, m1_w=0.230, m2_w=0.340, x_bus_span=x_d_span, slim=True)

    clr = grid(max(0.220, l_f / 2.0 + 0.130))
    y_bar = grid(inf["diff_y2"] + clr) if y_g > dy else grid(inf["diff_y1"] - clr)
    gx_t = grid(g_tap_x if g_tap_x is not None else cx)
    gp = tie_mos_gates(c, cx, inf, y_bar=y_bar, y_cont=y_g, tap_xs=[gx_t])[0]
    return {"cx": cx, "dy": dy, "s_xs": s_xs, "d_xs": d_xs, "g": gp, "inf": inf}


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


def build_rx_dt_slicer_5g_pdk(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build 1:1 drop-in `serdes_rx_dt_slicer_5g_pdk` (ports: inp inn clk qp qn t5..t0 vdd vss)."""
    c = Cell()
    hx = SLICE_HALF_X  # 14.800 um -> exact 29.600 um abutment pitch!

    # =========================================================================
    # EXACT 4G GLOBAL BAND Y COORDINATES & SUPPLY RAILS (1:1 mechanical drop-in)
    # =========================================================================
    y_south_port = -0.900
    y_vss_s      =  0.000

    # Band 1
    y_cap_a    =  1.800
    y_cap_g    =  3.300
    y_cap_b    =  4.800
    y_st1_tail =  2.800
    y_st1_n    =  2.650
    y_inp_m3   =  6.250
    y_inn_m3   =  7.050
    y_st1_pg   =  7.850
    y_st1_p    =  9.450
    y_vdd_mid  = 11.300

    # Band 2
    y_st2_p    = 13.300
    y_s2_clk_p = 14.850
    y_cc_onb   = 15.650
    y_cc_opb   = 16.350
    y_wn2_g    = 16.950
    y_st2_n    = 18.450
    y_vss_mid  = 20.750

    # Band 3
    y_sr_n       = 22.800
    y_sr_sp      = 24.450
    y_sr_sn      = 25.000
    y_sr_qp      = 25.550
    y_sr_qn      = 26.050
    y_w3_g       = 25.800
    y_sr_p       = 27.550
    y_vdd_n      = 29.350
    y_north_port = 30.250

    # Exact 4G Continuous Full-Width NWELL Bands
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
    # CENTER CORE (X = 0, STRICT BILATERAL MIRROR): StrongARM + Push-Pull SR
    # =========================================================================
    # --- Band 1 N: Xtail (24/0.15 nf=6) + Xinp/Xinn (14/0.15 nf=4) + tied poly dummies ---
    m_tail, inf_tail = cache.build_mos(N_LVT, 4.00, 0.15, 6, y_st1_tail, False)
    m_in,   inf_in   = cache.build_mos(N_LVT, 3.50, 0.15, 4, y_st1_n,    False)
    c.include(m_tail, dx=0.000)
    cx_in = 3.300
    c.include(m_in, dx=-cx_in)
    c.include(m_in, dx=+cx_in)

    for sgn in (-1, +1):
        xd = grid(sgn * (cx_in + inf_in["hw_diff"] + 0.140 + 0.075))
        pt = add_tied_poly_dummy(c, xd, inf_in["poly_y1"], inf_in["poly_y2"], 0.15,
                                 y_cont=grid(y_st1_n - 1.950), x_cont=grid(xd + sgn * 0.080))
        c.wire("metal1", [pt, (pt[0], y_vss_s)], 0.290)

    y_st1_tail_bus = 1.650
    for sx in inf_tail["s_xs"]:
        locali_v(c, sx, y_vss_s, y_st1_tail)
        _strap_diff_vertical(c, [sx], y_vss_s, grid(y_st1_tail + 1.40),
                             [grid(y_st1_tail - 1.25), y_st1_tail, grid(y_st1_tail + 1.25)])
    _strap_diff_vertical(c, inf_tail["d_xs"], grid(y_st1_tail - 1.40), grid(y_st1_tail + 1.40),
                         [grid(y_st1_tail - 1.25), y_st1_tail, grid(y_st1_tail + 1.25)],
                         y_bus=y_st1_tail_bus)

    y_st1_fn_bus = 3.850
    x_fn_sp = 6.700  # Vertical fn/fp M2 spine (0.28 um clear of +-7.30 t2/tb2 vias; jogs to +-7.20 across y=[12.10,14.15]!)
    all_tail_xs = list(inf_tail["d_xs"])
    for sgn in (-1, +1):
        cx = grid(sgn * cx_in)
        xf = grid(sgn * x_fn_sp)
        s_xs = [grid(cx + x) for x in inf_in["s_xs"]]
        d_xs = [grid(cx + x) for x in inf_in["d_xs"]]
        all_tail_xs.extend(s_xs)
        _strap_diff_vertical(c, s_xs, grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)],
                             y_bus=y_st1_tail_bus)
        _strap_diff_vertical(c, d_xs, grid(y_st1_n - 1.20), grid(y_st1_n + 1.20),
                             [grid(y_st1_n - 1.00), y_st1_n, grid(y_st1_n + 1.00)],
                             y_bus=y_st1_fn_bus,
                             x_bus_span=(min(d_xs[0], xf), max(d_xs[-1], xf)))
        c.wire("metal2", [(xf, y_cap_g), (xf, y_st1_p)], 0.300)
    c.wire("metal2", [(min(all_tail_xs), y_st1_tail_bus), (max(all_tail_xs), y_st1_tail_bus)], 0.360)

    # Full-width horizontal abutment `inp` & `inn` M3 buses + exact mirror gate taps
    c.rect("metal3", -hx, grid(y_inp_m3 - 0.200), +hx, grid(y_inp_m3 + 0.200))
    c.rect("metal3", -hx, grid(y_inn_m3 - 0.200), +hx, grid(y_inn_m3 + 0.200))
    y_in_gc = 5.650
    for sgn, y_m3 in ((-1, y_inp_m3), (+1, y_inn_m3)):
        cx = grid(sgn * cx_in)
        tx = grid(sgn * 2.850)
        tie_mos_gates(c, cx, inf_in, y_bar=grid(y_st1_n + 2.100), y_cont=y_in_gc, tap_xs=[tx])
        via1_clean(c, tx, y_in_gc)
        c.wire("metal2", [(tx, y_in_gc), (tx, y_m3)], 0.300)
        via2_clean(c, tx, y_m3)

    y_tail_gc = 5.450
    tie_mos_gates(c, 0.000, inf_tail, y_bar=5.050, y_cont=y_tail_gc, tap_xs=[0.000])
    via1_clean(c, 0.000, y_tail_gc)
    c.wire("metal2", [(0.000, y_tail_gc), (0.000, y_st1_pg)], 0.300)

    def _wire_eq3(y_row: float, inf_eq: dict, x_jog: float = 1.150) -> None:
        """Exact 180-deg point-symmetric 3-finger equalizer M1/M2 hookup (zero crossings, ad==as)."""
        y_lo = grid(y_row - 0.500)
        y_hi = grid(y_row + 0.500)
        s_xs = [grid(x) for x in inf_eq["s_xs"]]  # [-0.63, +0.21] -> left net (fn / outp_b)
        d_xs = [grid(x) for x in inf_eq["d_xs"]]  # [-0.21, +0.63] -> right net (fp / outn_b)
        for sx in s_xs:
            viali_pad_slim(c, sx, y_lo)
            viali_pad_slim(c, sx, y_hi)
            c.wire("metal1", [(sx, y_lo), (sx, y_hi)], 0.230)
            via1_clean(c, sx, y_lo)
        for dx in d_xs:
            viali_pad_slim(c, dx, y_lo)
            viali_pad_slim(c, dx, y_hi)
            c.wire("metal1", [(dx, y_lo), (dx, y_hi)], 0.230)
            via1_clean(c, dx, y_hi)
        xj = grid(x_jog)
        c.wire("metal2", [(-xj, y_row), (-xj, y_lo), (max(s_xs), y_lo)], 0.340)
        c.wire("metal2", [(+xj, y_row), (+xj, y_hi), (min(d_xs), y_hi)], 0.340)

    # --- Band 1 P: Xpfeq (pfet 4.80/0.15 nf=3) + Xpf1/2 (pfet 6.30/0.15 nf=3) ---
    m_pfeq, inf_pfeq = cache.build_mos(P_STD, 1.60, 0.15, 3, y_st1_p, True)
    m_pf,   inf_pf   = cache.build_mos(P_STD, 2.10, 0.15, 3, y_st1_p, True)
    cx_pf = 3.000
    c.include(m_pfeq, dx=0.000)
    c.include(m_pf, dx=-cx_pf)
    c.include(m_pf, dx=+cx_pf)
    _wire_eq3(y_st1_p, inf_pfeq, x_jog=1.150)

    for sgn in (-1, +1):
        cx = grid(sgn * cx_pf)
        # Swap s_xs/d_xs on sgn<0 so odd-nf=3 Xpf1/2 is 100% bilateral mirror!
        s_raw = inf_pf["d_xs"] if sgn < 0 else inf_pf["s_xs"]
        d_raw = inf_pf["s_xs"] if sgn < 0 else inf_pf["d_xs"]
        for sx in [grid(cx + x) for x in s_raw]:
            locali_v(c, sx, y_st1_p, y_vdd_mid)
            _strap_diff_vertical(c, [sx], grid(y_st1_p - 0.65), y_vdd_mid,
                                 [grid(y_st1_p - 0.60), grid(y_st1_p + 0.60)])
        pf_ds = [grid(cx + x) for x in d_raw]
        _strap_diff_vertical(c, pf_ds, grid(y_st1_p - 0.65), grid(y_st1_p + 0.65),
                             [grid(y_st1_p - 0.60), grid(y_st1_p + 0.60)], y_bus=y_st1_p)
        all_p1d = [grid(sgn * x_fn_sp), grid(sgn * 1.150)] + pf_ds
        c.wire("metal2", [(min(all_p1d), y_st1_p), (max(all_p1d), y_st1_p)], 0.340)

    tie_mos_gates(c, 0.000,  inf_pfeq, y_bar=grid(y_st1_p - 1.100), y_cont=y_st1_pg, tap_xs=[0.000])
    tie_mos_gates(c, -cx_pf, inf_pf,   y_bar=grid(y_st1_p - 1.350), y_cont=y_st1_pg, tap_xs=[-cx_pf])
    tie_mos_gates(c, +cx_pf, inf_pf,   y_bar=grid(y_st1_p - 1.350), y_cont=y_st1_pg, tap_xs=[+cx_pf])
    c.wire("metal1", [(-cx_pf, y_st1_pg), (+cx_pf, y_st1_pg)], 0.290)
    via1_clean(c, 0.000, y_st1_pg)
    via2_clean(c, 0.000, y_st1_pg)
    via3_pad(c, 0.000, y_st1_pg)

    # --- Band 2 P: Xpoeq (pfet 4.80/0.15 nf=3), Xpo1/2 (pfet 6.30/0.15 nf=3), Xlp1s/2s, Xlp1l/2l ---
    m_poeq, inf_poeq = cache.build_mos(P_STD, 1.60, 0.15, 3, y_st2_p, True)
    m_po,   inf_po   = cache.build_mos(P_STD, 2.10, 0.15, 3, y_st2_p, True)
    m_lps,  inf_lps  = cache.build_mos(P_STD, 2.10, 0.15, 4, y_st2_p, True)
    m_lpl,  inf_lpl  = cache.build_mos(P_LVT, 1.60, 0.35, 2, y_st2_p, True)
    gap_d = 0.280
    cx_po  = grid(inf_poeq["hw_diff"] + gap_d + inf_po["hw_diff"])
    cx_lps = grid(cx_po + inf_po["hw_diff"] + gap_d + inf_lps["hw_diff"])
    cx_lpl = grid(cx_lps + inf_lps["hw_diff"] + gap_d + inf_lpl["hw_diff"])
    # Check: cx_po~2.03, cx_lps~4.27, cx_lpl~6.42 (outer poly 6.87 vs +-7.13 t2/tb2 -> 0.26 um poly.2 clear!)
    c.include(m_poeq, dx=0.000)
    _wire_eq3(y_st2_p, inf_poeq, x_jog=1.150)
    for sgn in (-1, +1):
        c.include(m_po,  dx=grid(sgn * cx_po))
        c.include(m_lps, dx=grid(sgn * cx_lps))
        c.include(m_lpl, dx=grid(sgn * cx_lpl))

    for sgn in (-1, +1):
        po_s_raw = inf_po["d_xs"] if sgn < 0 else inf_po["s_xs"]
        po_d_raw = inf_po["s_xs"] if sgn < 0 else inf_po["d_xs"]
        for cx_u, s_raw, yv_off in ((cx_po, po_s_raw, 0.60), (cx_lps, inf_lps["s_xs"], 0.60), (cx_lpl, inf_lpl["s_xs"], 0.40)):
            for sx in [grid(sgn * cx_u + x) for x in s_raw]:
                locali_v(c, sx, y_vdd_mid, y_st2_p)
                _strap_diff_vertical(c, [sx], y_vdd_mid, grid(y_st2_p + yv_off + 0.05),
                                     [grid(y_st2_p - yv_off), grid(y_st2_p + yv_off)])
        po_ds  = [grid(sgn * cx_po  + x) for x in po_d_raw]
        lps_ds = [grid(sgn * cx_lps + x) for x in inf_lps["d_xs"]]
        lpl_ds = [grid(sgn * cx_lpl + x) for x in inf_lpl["d_xs"]]
        _strap_diff_vertical(c, po_ds,  grid(y_st2_p - 0.65), grid(y_st2_p + 0.65),
                             [grid(y_st2_p - 0.60), grid(y_st2_p + 0.60)], y_bus=y_st2_p)
        _strap_diff_vertical(c, lps_ds, grid(y_st2_p - 0.65), grid(y_st2_p + 0.65),
                             [grid(y_st2_p - 0.60), grid(y_st2_p + 0.60)], y_bus=y_st2_p)
        _strap_diff_vertical(c, lpl_ds, grid(y_st2_p - 0.45), grid(y_st2_p + 0.45),
                             [grid(y_st2_p - 0.40), grid(y_st2_p + 0.40)], y_bus=y_st2_p)
        all_ds = [grid(sgn * 1.150)] + po_ds + lps_ds + lpl_ds
        c.wire("metal2", [(min(all_ds), y_st2_p), (max(all_ds), y_st2_p)], 0.340)

    tie_mos_gates(c, 0.000,  inf_poeq, y_bar=grid(y_st2_p + 1.100), y_cont=y_s2_clk_p, tap_xs=[0.000])
    tie_mos_gates(c, -cx_po, inf_po,   y_bar=grid(y_st2_p + 1.350), y_cont=y_s2_clk_p, tap_xs=[-cx_po])
    tie_mos_gates(c, +cx_po, inf_po,   y_bar=grid(y_st2_p + 1.350), y_cont=y_s2_clk_p, tap_xs=[+cx_po])
    c.wire("metal1", [(-cx_po, y_s2_clk_p), (+cx_po, y_s2_clk_p)], 0.290)
    via1_clean(c, 0.000, y_s2_clk_p)
    via2_clean(c, 0.000, y_s2_clk_p)
    via3_pad(c, 0.000, y_s2_clk_p)

    # Exact 4G Central `clk` vertical M4 spine along X=0.000 (y=-0.900 -> y=+17.200 for Deser16 riser!)
    c.wire("metal4", [(0.000, y_south_port), (0.000, 17.200)], 0.440)

    # --- Band 2 N: StrongARM Xln1 (-cx_ln, src=fn, drn=outp_b) & Xln2 (+cx_ln, src=fp, drn=outn_b) ---
    # ZERO-CROSSING ROUTING:
    #   * fn/fp run OUTSIDE Xln at +-x_fn_sp (6.750) -> Xln sources on M2 at y_s2_n_src (19.050, |x| in [2.8..6.75])
    #   * outp_b/outn_b run INSIDE Xln at +-x_ob_in (2.000) from Band 2 P (13.30) -> Xln drains (17.85) ->
    #     straight north past y=19.05 (0.80 um CLEAR of fn/fp!) -> clean M2 jog at y=20.00 out to +-x_ob_sr (4.850) ->
    #     straight north to Band 3 Xisop/Xison gates (25.55)!
    m_ln, inf_ln = cache.build_mos(N_LVT, 2.40, 0.15, 6, y_st2_n, False)
    cx_ln   = cx_lps  # ~4.100 (s_xs start at |x| >= 2.58!)
    x_ob_in = 1.950   # 0.31 um M2 clear of Xln inner s_xs via1 (2.41) & flush with y_st2_p=0.340 M2!
    x_ob_sr = 4.850   # Clean vertical Band-3 outp_b/outn_b riser (clear of x_pu_vdd=4.22 & Xiso_pl!)
    y_s2_n_out = grid(y_st2_n - 0.600)   # 17.850 (drains: outp_b / outn_b)
    y_s2_n_src = grid(y_st2_n + 0.600)   # 19.050 (sources: fn / fp)
    y_ob_jog   = 20.000                  # Above y_s2_n_src=19.05 & below y_vss_mid=20.75!

    for sgn in (-1, +1):
        cx = grid(sgn * cx_ln)
        xf = grid(sgn * x_fn_sp)
        xoi = grid(sgn * x_ob_in)
        xos = grid(sgn * x_ob_sr)
        c.include(m_ln, dx=cx)
        ln_s = [grid(cx + x) for x in inf_ln["s_xs"]]
        ln_d = [grid(cx + x) for x in inf_ln["d_xs"]]
        _strap_diff_vertical(c, ln_s, grid(y_st2_n - 0.80), grid(y_st2_n + 0.80),
                             [grid(y_st2_n - 0.70), grid(y_st2_n + 0.70)], y_bus=y_s2_n_src,
                             x_bus_span=(min(ln_s[0], xf), max(ln_s[-1], xf)))
        _strap_diff_vertical(c, ln_d, grid(y_st2_n - 0.80), grid(y_st2_n + 0.80),
                             [grid(y_st2_n - 0.70), grid(y_st2_n + 0.70)], y_bus=y_s2_n_out,
                             x_bus_span=(min(ln_d[0], xoi), max(ln_d[-1], xoi)))
        # Bilateral mirror fn/fp M2 (y_st1_p=9.45 -> jog out to +-7.20 across Band 2 P [12.10,14.15] -> +-6.70 -> y_s2_n_src=19.05)
        xf_jog = grid(sgn * 7.200)
        c.wire("metal2", [(xf, y_st1_p), (xf, 12.100), (xf_jog, 12.100), (xf_jog, 14.150), (xf, 14.150), (xf, y_s2_n_src)], 0.300)
        # Zero-crossing outp_b/outn_b M2: Band 2 P (13.30) -> Band 2 N (17.85) -> y_ob_jog (20.00) -> x_ob_sr -> y_sr_qp (25.55)!
        c.wire("metal2", [(xoi, y_st2_p), (xoi, y_ob_jog), (xos, y_ob_jog), (xos, y_sr_qp)], 0.300)

    # StrongARM Cross-Coupling (`outn_b` @ y_cc_onb=15.65 -> Left Xlp1/Xln1; `outp_b` @ y_cc_opb=16.35 -> Right Xlp2/Xln2)
    for sgn, y_cc in ((-1, y_cc_onb), (+1, y_cc_opb)):
        cx_s = grid(sgn * cx_lps)
        cx_l = grid(sgn * cx_lpl)
        tie_mos_gates(c, cx_s, inf_lps, y_bar=grid(y_st2_p + 1.350), y_cont=y_cc, tap_xs=[cx_s])
        tie_mos_gates(c, cx_l, inf_lpl, y_bar=grid(y_st2_p + 1.080), y_cont=y_cc, tap_xs=[cx_l])
        tie_mos_gates(c, cx_s, inf_ln,  y_bar=grid(y_st2_n - 1.450), y_cont=y_cc, tap_xs=[cx_s])
    via1_clean(c, +x_ob_in, y_cc_onb)
    c.wire("metal1", [(-cx_lpl, y_cc_onb), (+x_ob_in, y_cc_onb)], 0.290)
    via1_clean(c, -x_ob_in, y_cc_opb)
    c.wire("metal1", [(-x_ob_in, y_cc_opb), (+cx_lpl, y_cc_opb)], 0.290)

    # --- Band 3: 100%-Isolated Simultaneous NMOS-Push-Up Static SR Latch (ZERO DRC, ZERO CROSSING!) ---
    m_ison,  inf_ison  = cache.build_mos(N_LVT, 1.20, 0.15, 2, y_sr_n, False)
    m_isops, inf_isops = cache.build_mos(P_STD, 2.00, 0.15, 3, y_sr_p, True)
    m_isopl, inf_isopl = cache.build_mos(P_LVT, 2.10, 0.35, 1, y_sr_p, True)
    m_srpd,  inf_srpd  = cache.build_mos(N_LVT, 2.50, 0.15, 2, y_sr_n, False)
    m_srpu,  inf_srpu  = cache.build_mos(N_LVT, 2.50, 0.15, 2, y_sr_n, False)
    m_kn,    inf_kn    = cache.build_mos(N_LVT, 0.80, 0.15, 1, y_sr_n, False)
    m_kps,   inf_kps   = cache.build_mos(P_STD, 1.20, 0.15, 2, y_sr_p, True)
    m_kpl,   inf_kpl   = cache.build_mos(P_LVT, 1.00, 0.35, 1, y_sr_p, True)

    # Exact non-overlapping X positions derived directly from `hw_diff` + generous >=0.38 um clearance!
    cx_kn     = 0.700
    cx_sr_pd  = grid(max(2.150, cx_kn + inf_kn["hw_diff"] + 0.380 + inf_srpd["hw_diff"]))
    cx_sr_pu  = grid(cx_sr_pd + inf_srpd["hw_diff"] + 0.380 + inf_srpu["hw_diff"])
    x_pu_vdd  = grid(cx_sr_pu + inf_srpu["s_xs"][-1])  # Outer VDD column of Xpup/Xpun (~4.22, clear of x_ob_sr=4.85!)
    cx_kps    = 0.850
    cx_kpl    = grid(cx_kps + inf_kps["hw_diff"] + 0.380 + inf_kpl["hw_diff"])
    cx_iso_pl = 5.150  # P3: well outside x_ob_sr=4.85!
    cx_iso_np = grid(cx_iso_pl + inf_isopl["hw_diff"] + 0.280 + inf_isops["hw_diff"])  # ~6.77, 0.22 um M2 clear of xr_g2=+7.30!
    x_sp_sp   = grid(cx_iso_pl + inf_isopl["hw_diff"] + 0.140)  # Vertical sp/sn M2 drop cleanly in gap between Xiso_pl & Xiso_ps!
    x_q_out   = 2.250  # EXACT 4G qp (-2.250) / qn (+2.250) North ports!

    for sgn in (-1, +1):
        # 1. Isolator Xisop (-1: outp_b -> sp) / Xison (+1: outn_b -> sn)
        cx_np = grid(sgn * cx_iso_np)
        cx_pl = grid(sgn * cx_iso_pl)
        xsp   = grid(sgn * x_sp_sp)
        xo    = grid(sgn * x_ob_sr)
        c.include(m_ison,  dx=cx_np)
        c.include(m_isops, dx=cx_np)
        c.include(m_isopl, dx=cx_pl)

        for sx in [grid(cx_np + x) for x in inf_ison["s_xs"]]:
            locali_v(c, sx, y_vss_mid, y_sr_n)
            _strap_diff_vertical(c, [sx], y_vss_mid, grid(y_sr_n + 0.35),
                                 [grid(y_sr_n - 0.30), grid(y_sr_n + 0.30)])
        x_in_d = grid(cx_np + inf_ison["d_xs"][0])
        _strap_diff_vertical(c, [x_in_d], grid(y_sr_n - 0.35), grid(y_sr_n + 0.35),
                             [grid(y_sr_n - 0.30), grid(y_sr_n + 0.30)], y_bus=y_sr_n,
                             x_bus_span=(x_in_d, xsp))

        for sx in [grid(cx_np + x) for x in inf_isops["s_xs"]]:
            locali_v(c, sx, y_sr_p, y_vdd_n)
            _strap_diff_vertical(c, [sx], grid(y_sr_p - 0.60), y_vdd_n,
                                 [grid(y_sr_p - 0.55), grid(y_sr_p + 0.55)])
        isops_ds = [grid(cx_np + x) for x in inf_isops["d_xs"]]
        _strap_diff_vertical(c, isops_ds, grid(y_sr_p - 0.60), grid(y_sr_p + 0.60),
                             [grid(y_sr_p - 0.55), grid(y_sr_p + 0.55)], y_bus=y_sr_p)

        x_pl_s = grid(cx_pl + (inf_isopl["d_xs"][0] if sgn < 0 else inf_isopl["s_xs"][0]))
        x_pl_d = grid(cx_pl + (inf_isopl["s_xs"][0] if sgn < 0 else inf_isopl["d_xs"][0]))
        locali_v(c, x_pl_s, y_sr_p, y_vdd_n)
        _strap_diff_vertical(c, [x_pl_s], grid(y_sr_p - 0.60), y_vdd_n,
                             [grid(y_sr_p - 0.55), grid(y_sr_p + 0.55)])
        _strap_diff_vertical(c, [x_pl_d], grid(y_sr_p - 0.60), grid(y_sr_p + 0.60),
                             [grid(y_sr_p - 0.55), grid(y_sr_p + 0.55)], y_bus=y_sr_p)

        all_iso_d = [xsp, x_pl_d] + isops_ds
        c.wire("metal2", [(min(all_iso_d), y_sr_p), (max(all_iso_d), y_sr_p)], 0.340)
        c.wire("metal2", [(xsp, y_sr_n), (xsp, y_sr_p)], 0.300)

        tie_mos_gates(c, cx_np, inf_ison,  y_bar=grid(y_sr_n + 0.850), y_cont=y_sr_qp, tap_xs=[cx_np])
        tie_mos_gates(c, cx_np, inf_isops, y_bar=grid(y_sr_p - 1.250), y_cont=y_sr_qp, tap_xs=[cx_np])
        tie_mos_gates(c, cx_pl, inf_isopl, y_bar=grid(y_sr_p - 1.350), y_cont=y_sr_qp, tap_xs=[cx_pl])
        via1_clean(c, xo, y_sr_qp)
        g_xs_iso = [xo, cx_pl, cx_np]
        c.wire("metal1", [(min(g_xs_iso), y_sr_qp), (max(g_xs_iso), y_sr_qp)], 0.290)

        # 2. Pull-down Xrst (-cx_sr_pd: G=sn, D=qp) & Xset (+cx_sr_pd: G=sp, D=qn)
        cx_pd = grid(sgn * cx_sr_pd)
        c.include(m_srpd, dx=cx_pd)
        for sx in [grid(cx_pd + x) for x in inf_srpd["s_xs"]]:
            locali_v(c, sx, y_vss_mid, y_sr_n)
            _strap_diff_vertical(c, [sx], y_vss_mid, grid(y_sr_n + 0.80),
                                 [grid(y_sr_n - 0.70), grid(y_sr_n + 0.70)])
        dx_pd = grid(cx_pd + inf_srpd["d_xs"][0])
        _strap_diff_vertical(c, [dx_pd], grid(y_sr_n - 0.80), grid(y_sr_n + 0.80),
                             [grid(y_sr_n - 0.70), grid(y_sr_n + 0.70)], y_bus=y_sr_n)

        # 3. Simultaneous NMOS-LVT Push-Up Xpup (-cx_sr_pu: G=sp, S=qp, D=vdd) & Xpun (+cx_sr_pu)
        cx_pu = grid(sgn * cx_sr_pu)
        xv_pu = grid(sgn * x_pu_vdd)
        c.include(m_srpu, dx=cx_pu)
        pu_s = [grid(cx_pu + x) for x in inf_srpu["s_xs"]]
        pu_d = [grid(cx_pu + x) for x in inf_srpu["d_xs"]]
        y_pu_vdd_b = grid(y_sr_n - 0.900)  # 21.900 (strictly below qp bus @ 22.80!)
        _strap_diff_vertical(c, pu_s, grid(y_sr_n - 0.95), grid(y_sr_n + 0.85),
                             [grid(y_sr_n - 0.75), grid(y_sr_n + 0.75)], y_bus=y_pu_vdd_b,
                             x_bus_span=(min(pu_s[0], xv_pu), max(pu_s[-1], xv_pu)))
        # Clean vertical VDD M2 riser strictly OUTSIDE qp/qn (|x| = x_pu_vdd ~ 4.22, clear of pu_d ~ 3.80 & x_ob_sr=4.85!)
        # Offset riser slightly outward (+0.15) so M2 gap from pu_d via1 is >= 0.25 um!
        xv_pu_riser = grid(sgn * (x_pu_vdd + 0.140))
        c.wire("metal2", sorted([(xv_pu, y_pu_vdd_b), (xv_pu_riser, y_pu_vdd_b)], key=lambda p: p[0]), 0.280)
        c.wire("metal2", [(xv_pu_riser, y_pu_vdd_b), (xv_pu_riser, y_vdd_n)], 0.280)
        via1_clean(c, xv_pu_riser, y_vdd_n)
        _strap_diff_vertical(c, pu_d, grid(y_sr_n - 0.85), grid(y_sr_n + 0.85),
                             [grid(y_sr_n - 0.75), grid(y_sr_n + 0.75)], y_bus=y_sr_n)

        # 4. Light 4T Keeper: Xkn, Xkps, Xkpl
        cx_n   = grid(sgn * cx_kn)
        cx_ps  = grid(sgn * cx_kps)
        cx_plk = grid(sgn * cx_kpl)
        xq     = grid(sgn * x_q_out)
        c.include(m_kn,  dx=cx_n)
        c.include(m_kps, dx=cx_ps)
        c.include(m_kpl, dx=cx_plk)

        x_kn_s = grid(cx_n + (inf_kn["s_xs"][0] if sgn < 0 else inf_kn["d_xs"][0]))
        x_kn_d = grid(cx_n + (inf_kn["d_xs"][0] if sgn < 0 else inf_kn["s_xs"][0]))
        locali_v(c, x_kn_s, y_vss_mid, y_sr_n)
        _strap_diff_vertical(c, [x_kn_d], grid(y_sr_n - 0.20), grid(y_sr_n + 0.20), [y_sr_n], y_bus=y_sr_n)

        for sx in [grid(cx_ps + x) for x in inf_kps["s_xs"]]:
            locali_v(c, sx, y_sr_p, y_vdd_n)
            _strap_diff_vertical(c, [sx], grid(y_sr_p - 0.35), y_vdd_n,
                                 [grid(y_sr_p - 0.30), grid(y_sr_p + 0.30)])
        x_kps_d = grid(cx_ps + inf_kps["d_xs"][0])
        _strap_diff_vertical(c, [x_kps_d], grid(y_sr_p - 0.35), grid(y_sr_p + 0.35),
                             [grid(y_sr_p - 0.30), grid(y_sr_p + 0.30)], y_bus=y_sr_p)

        x_kpl_s = grid(cx_plk + (inf_kpl["s_xs"][0] if sgn < 0 else inf_kpl["d_xs"][0]))
        x_kpl_d = grid(cx_plk + (inf_kpl["d_xs"][0] if sgn < 0 else inf_kpl["s_xs"][0]))
        locali_v(c, x_kpl_s, y_sr_p, y_vdd_n)
        _strap_diff_vertical(c, [x_kpl_s], grid(y_sr_p - 0.25), y_vdd_n, [y_sr_p])
        _strap_diff_vertical(c, [x_kpl_d], grid(y_sr_p - 0.25), grid(y_sr_p + 0.25), [y_sr_p], y_bus=y_sr_p)

        all_qn_xs = [pu_d[0], dx_pd, xq, x_kn_d]
        c.wire("metal2", [(min(all_qn_xs), y_sr_n), (max(all_qn_xs), y_sr_n)], 0.340)
        all_qp_xs = [x_kps_d, xq, x_kpl_d]
        c.wire("metal2", [(min(all_qp_xs), y_sr_p), (max(all_qp_xs), y_sr_p)], 0.340)
        c.wire("metal2", [(xq, y_sr_n), (xq, y_north_port)], 0.340)

    # SR Latch Cross-Couple M1 Channels (100% mirror symmetric!)
    via1_clean(c, -x_sp_sp, y_sr_sp)
    tie_mos_gates(c, -cx_sr_pu, inf_srpu, y_bar=grid(y_sr_n + 1.450), y_cont=y_sr_sp, tap_xs=[-cx_sr_pu])
    tie_mos_gates(c, +cx_sr_pd, inf_srpd, y_bar=grid(y_sr_n + 1.450), y_cont=y_sr_sp, tap_xs=[+cx_sr_pd])
    c.wire("metal1", [(-x_sp_sp, y_sr_sp), (+cx_sr_pd, y_sr_sp)], 0.290)

    via1_clean(c, +x_sp_sp, y_sr_sn)
    tie_mos_gates(c, +cx_sr_pu, inf_srpu, y_bar=grid(y_sr_n + 1.450), y_cont=y_sr_sn, tap_xs=[+cx_sr_pu])
    tie_mos_gates(c, -cx_sr_pd, inf_srpd, y_bar=grid(y_sr_n + 1.450), y_cont=y_sr_sn, tap_xs=[-cx_sr_pd])
    c.wire("metal1", [(-cx_sr_pd, y_sr_sn), (+x_sp_sp, y_sr_sn)], 0.290)

    via1_clean(c, -x_q_out, y_sr_qp)
    tie_mos_gates(c, +cx_kn,  inf_kn,  y_bar=grid(y_sr_n + 0.650), y_cont=y_sr_qp, tap_xs=[+cx_kn])
    tie_mos_gates(c, +cx_kps, inf_kps, y_bar=grid(y_sr_p - 0.850), y_cont=y_sr_qp, tap_xs=[+cx_kps])
    tie_mos_gates(c, +cx_kpl, inf_kpl, y_bar=grid(y_sr_p - 0.850), y_cont=y_sr_qp, tap_xs=[+cx_kpl])
    c.wire("metal1", [(-x_q_out, y_sr_qp), (+cx_kpl, y_sr_qp)], 0.290)

    via1_clean(c, +x_q_out, y_sr_qn)
    tie_mos_gates(c, -cx_kn,  inf_kn,  y_bar=grid(y_sr_n + 0.650), y_cont=y_sr_qn, tap_xs=[-cx_kn])
    tie_mos_gates(c, -cx_kps, inf_kps, y_bar=grid(y_sr_p - 0.850), y_cont=y_sr_qn, tap_xs=[-cx_kps])
    tie_mos_gates(c, -cx_kpl, inf_kpl, y_bar=grid(y_sr_p - 0.850), y_cont=y_sr_qn, tap_xs=[-cx_kpl])
    c.wire("metal1", [(-cx_kpl, y_sr_qn), (+x_q_out, y_sr_qn)], 0.290)

    # =========================================================================
    # SYMMETRIC 32:32 DIFFERENTIAL MOS-CAP TRIM BANKS (Band 1 Wings)
    # 100% EXACT island-for-island, finger-for-finger mirror (14.40 um : 14.40 um)!
    # Strictly ordered so EVERY drain M2 track rises straight without crossing any neighbor!
    #   Row A (1.80): c5 @ 12.15 (tr5=12.65), c1 @ 8.75 (tr1=8.75)
    #   Row B (4.80): c0 @ 13.05 (tr0=13.40), c4 @ 11.20 (tr4=11.45), c3 @ 9.50 (tr3=9.50), c2 @ 7.90 (tr2=7.85)
    # =========================================================================
    cap_a_spec = [
        ("c5", 1.80, 4, 12.150, [11.750, 12.650]),
        ("c1", 0.45, 1,  8.750, [8.750]),
    ]
    cap_b_spec = [
        ("c0", 0.45, 1, 13.150, [13.150]),
        ("c4", 1.80, 2, 11.150, [11.150]),
        ("c3", 1.80, 1,  9.500, [9.500]),
        ("c2", 0.90, 1,  7.900, [7.900]),
    ]
    for sgn in (-1, +1):
        poly_xs: list[float] = []
        for row_y, specs in ((y_cap_a, cap_a_spec), (y_cap_b, cap_b_spec)):
            for _nm, wf, nf, cx_abs, taps_abs in specs:
                cx = grid(sgn * cx_abs)
                taps = sorted(grid(sgn * tx) for tx in taps_abs)
                u = _place_mos_cap(c, cache, wf, nf, cx, row_y, y_cap_g, y_cap_g, taps)
                poly_xs.extend([grid(cx + g) for g in u["inf"]["g_xs"]] + taps)
        c.rect("poly", grid(min(poly_xs) - 0.135), grid(y_cap_g - 0.170),
               grid(max(poly_xs) + 0.135), grid(y_cap_g + 0.170))
        xm1_a, xm1_b = sorted((grid(sgn * x_fn_sp), grid(sgn * 13.150)))
        c.wire("metal1", [(xm1_a, y_cap_g), (xm1_b, y_cap_g)], 0.290)
        via1_clean(c, grid(sgn * x_fn_sp), y_cap_g)

    # =========================================================================
    # LEFT & RIGHT WING TRIM INVERTERS + 5 HORIZONTAL M3 `tb5..tb1` BRIDGES
    # ZERO M2 CROSSINGS! Exact 4G M4 `t5..t0` trunk X coordinates on Left; ZERO M4 on Right!
    # =========================================================================
    y_wp1_g = y_st1_pg       #  7.850
    y_wp2_g = y_s2_clk_p     # 14.850
    y_m3_tb = {
        "tb5": 21.650,
        "tb3": 22.800,
        "tb2": 23.700,
        "tb4": 24.600,
        "tb1": 26.700,
    }

    # Exact 4G Left-Wing M4 `t5..t0` port trunk X coordinates (1:1 drop-in!)
    xg_t0 = -12.750
    xg_t4 = -11.850
    xg_t5 = -10.950
    xg_t3 = -10.050
    xg_t1 =  -8.150
    xg_t2 =  -7.300

    # Strictly monotonic, non-overlapping vertical M2 drain tracks (exact mirror for Left tb* and Right td*!)
    x_tr_0   = 13.420  # c0 (13.15) -> Xt0/Xref_on (13.20)
    x_tr_5   = 12.650  # c5 (12.15) -> Xt5/Xtp5 (12.40) -> ends at y=21.90!
    x_tr_4lo = 11.450  # c4 (11.15) -> jogs to x_tr_4hi at y=21.50 (0.50 clear of t5=-10.95 & 0.55 clear of Xt5 drain!)
    x_tr_4hi = 10.750  # Xt4/Xtp4 (10.75) in Band 3 (1.10 clear of t4=-11.85!)
    x_tr_3   =  9.500  # c3 (9.50)  -> Xt3/Xtp3 (9.45) -> ends at y=23.70! (0.55 clear of t3=-10.05!)
    x_tr_1   =  8.750  # c1 (8.75)  -> Xt1/Xtp1 (8.80) (0.75 clear of tr3 & 0.60 clear of t1=-8.15!)
    x_tr_2   =  7.900  # c2 (7.90)  -> Xt2/Xtp2 (7.95) -> ends at y=22.80! (0.85 clear of tr1 & 0.60 clear of t2=-7.30!)

    # --- LEFT WING (`Xt5..Xt0`) ---
    # 1. Xt5 (N: 4x2.00 @ N2, P: 4x2.00 @ P1 + 4x2.00 @ P2 -> exact N=8, P=16; centered @ -12.40, drains in [-12.88..-11.92]!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, -12.400, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=xg_t5, x_d_span=(-12.880, -11.920))
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, -12.400, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=xg_t5, x_d_span=(-12.880, -11.920))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 4, -12.400, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xg_t5, x_d_span=(-12.880, -11.920))
    c.wire("metal2", [(-x_tr_5, y_cap_a), (-x_tr_5, y_m3_tb["tb5"])], 0.300)
    for xv in (-12.650, -12.150, -11.650):
        via1_clean(c, xv, y_cap_a)
    c.wire("metal2", [(-x_tr_5, y_cap_a), (-11.650, y_cap_a)], 0.340)

    # 2. Xt3 (N: 1x2.00 @ N2, P: 2x2.00 @ P1 -> exact N=2, P=4; centered @ -9.45, drains right on -x_tr_3=-9.50!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 2, -9.500, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=xg_t3, x_d_span=(-x_tr_3, -x_tr_3))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 1, -9.500, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xg_t3, x_d_span=(-x_tr_3, -9.260))
    c.wire("metal2", [(-x_tr_3, y_cap_b), (-x_tr_3, y_m3_tb["tb3"])], 0.280)
    via1_clean(c, -9.500, y_cap_b)

    # 3. Xt2 (N: 1x1.00 @ N2, P: 1x2.00 @ P2 -> exact N=1, P=2; centered @ -8.00, swap_sd=True so drain faces -7.90!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, -8.100, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=xg_t2, x_d_span=(-x_tr_2, -7.860))
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, -8.100, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xg_t2, x_d_span=(-x_tr_2, -7.860))
    c.wire("metal2", [(-x_tr_2, y_cap_b), (-x_tr_2, y_m3_tb["tb2"])], 0.280)
    via1_clean(c, -7.900, y_cap_b)

    # 4. Xt4 (N: 2x2.00 @ N3, P: 4x2.00 @ P3 -> exact N=4, P=8; centered @ -10.80, well clear of Xt0=-13.20 & Xt1=-8.80!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, -10.800, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xg_t4, x_d_span=(-11.280, -10.320))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 2, -10.800, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xg_t4, x_d_span=(-10.800, -x_tr_4hi))
    # Clean jog of x_tr_4 from +-11.45 (below y=22.25) -> +-10.75 (strictly ABOVE tb5 end @ 21.65 -> ZERO crossing!)
    y_tr4_jog = 22.250
    c.wire("metal2", [(-x_tr_4lo, y_cap_b), (-x_tr_4lo, y_tr4_jog), (-x_tr_4hi, y_tr4_jog), (-x_tr_4hi, y_sr_p)], 0.280)
    via1_clean(c, -11.150, y_cap_b)
    c.wire("metal2", [(-x_tr_4lo, y_cap_b), (-11.150, y_cap_b)], 0.300)

    # 5. Xt1 (N: 1x1.00 @ N3, P: 1x2.00 @ P3 -> exact N=1, P=2; centered @ -8.85, drain right on -x_tr_1=-8.75!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, -8.850, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xg_t1, x_d_span=(-x_tr_1, -8.610))
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, -8.850, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xg_t1, x_d_span=(-x_tr_1, -8.610))
    c.wire("metal2", [(-x_tr_1, y_cap_a), (-x_tr_1, y_sr_p)], 0.280)
    via1_clean(c, -8.750, y_cap_a)

    # 6. Xt0 (N: 1x1.00 @ N3, P: 1x2.00 @ P3 -> exact N=1, P=2; swap_sd=True so drain faces OUTER -x_tr_0=-13.42!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, -13.200, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xg_t0, x_d_span=(-x_tr_0, -13.440), swap_sd=True)
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, -13.200, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xg_t0, x_d_span=(-x_tr_0, -13.440), swap_sd=True)
    c.wire("metal2", [(-x_tr_0, y_cap_b), (-x_tr_0, y_sr_p)], 0.280)
    via1_clean(c, -13.150, y_cap_b)
    c.wire("metal2", [(-x_tr_0, y_cap_b), (-13.150, y_cap_b)], 0.280)

    # Vertical M4 `t5..t0` South Port Trunks (EXACT 4G X coordinates & top-level hardwire spans!)
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

    # --- RIGHT WING (`Xtp5..Xtp1` + `Xref_on`, ZERO M4, exact mirror of Left Wing!) ---
    xr_g5 = +10.900   # tb5 M2 drop (y_wp1_g=7.85 -> y_m3_tb["tb5"]=21.90; 0.55 clear of +11.45 & 0.85 clear of +10.05!)
    xr_g3 = +10.050   # tb3 M2 drop (y_wp1_g=7.85 -> y_m3_tb["tb3"]=23.70; 0.55 clear of +9.50 & 0.85 clear of +10.90!)
    xr_g2 =  +7.300   # tb2 M2 drop (y_wp2_g=14.85 -> y_m3_tb["tb2"]=22.80; 0.60 clear of +7.90 & 0.55 clear of +6.75!)
    xr_g4 = +11.850   # tb4 M2 hop  (y_m3_tb["tb4"]=24.60 -> y_w3_g=25.80; 1.10 clear of +10.75!)
    xr_g1 =  +8.150   # tb1 M2 hop  (y_w3_g=25.80 -> y_m3_tb["tb1"]=27.60; 0.60 clear of +8.75!)

    # 1. Xtp5 (exact mirror of Xt5 @ +12.40)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, +12.400, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=xr_g5, x_d_span=(+11.920, +12.880))
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, +12.400, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=xr_g5, x_d_span=(+11.920, +12.880))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 4, +12.400, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xr_g5, x_d_span=(+11.920, +12.880))
    for yg in (y_wp1_g, y_wp2_g, y_wn2_g):
        via1_clean(c, xr_g5, yg)
    c.wire("metal2", [(xr_g5, y_wp1_g), (xr_g5, y_m3_tb["tb5"])], 0.280)
    c.wire("metal2", [(+x_tr_5, y_cap_a), (+x_tr_5, y_st2_n)], 0.300)
    for xv in (+11.650, +12.150, +12.650):
        via1_clean(c, xv, y_cap_a)
    c.wire("metal2", [(+11.650, y_cap_a), (+x_tr_5, y_cap_a)], 0.340)

    # 2. Xtp3 (exact mirror of Xt3 @ +9.50)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 2, +9.500, y_st1_p, True,
                    y_vdd_mid, y_st1_p, y_wp1_g, g_tap_x=xr_g3, x_d_span=(+x_tr_3, +x_tr_3))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 1, +9.500, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xr_g3, x_d_span=(+9.260, +x_tr_3), swap_sd=True)
    for yg in (y_wp1_g, y_wn2_g):
        via1_clean(c, xr_g3, yg)
    c.wire("metal2", [(xr_g3, y_wp1_g), (xr_g3, y_m3_tb["tb3"])], 0.280)
    c.wire("metal2", [(+x_tr_3, y_cap_b), (+x_tr_3, y_st2_n)], 0.280)
    via1_clean(c, +9.500, y_cap_b)

    # 3. Xtp2 (exact mirror of Xt2 @ +8.10)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, +8.100, y_st2_p, True,
                    y_vdd_mid, y_st2_p, y_wp2_g, g_tap_x=xr_g2, x_d_span=(+7.860, +x_tr_2), swap_sd=True)
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, +8.100, y_st2_n, False,
                    y_vss_mid, y_st2_n, y_wn2_g, g_tap_x=xr_g2, x_d_span=(+7.860, +x_tr_2), swap_sd=True)
    for yg in (y_wp2_g, y_wn2_g):
        via1_clean(c, xr_g2, yg)
    c.wire("metal2", [(xr_g2, y_wp2_g), (xr_g2, y_m3_tb["tb2"])], 0.280)
    c.wire("metal2", [(+x_tr_2, y_cap_b), (+x_tr_2, y_st2_n)], 0.280)
    via1_clean(c, +7.900, y_cap_b)

    # 4. Xtp4 (exact mirror of Xt4 @ +10.80)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 4, +10.800, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xr_g4, x_d_span=(+10.320, +11.280))
    _place_mos_unit(c, cache, N_STD, 2.00, 0.18, 2, +10.800, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xr_g4, x_d_span=(+x_tr_4hi, +10.800))
    via1_clean(c, xr_g4, y_w3_g)
    c.wire("metal2", [(xr_g4, y_m3_tb["tb4"]), (xr_g4, y_w3_g)], 0.280)
    c.wire("metal2", [(+x_tr_4lo, y_cap_b), (+x_tr_4lo, y_tr4_jog), (+x_tr_4hi, y_tr4_jog), (+x_tr_4hi, y_sr_p)], 0.280)
    via1_clean(c, +11.150, y_cap_b)
    c.wire("metal2", [(+11.150, y_cap_b), (+x_tr_4lo, y_cap_b)], 0.300)

    # 5. Xtp1 (exact mirror of Xt1 @ +8.85)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, +8.850, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=xr_g1, x_d_span=(+8.610, +x_tr_1), swap_sd=True)
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, +8.850, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=xr_g1, x_d_span=(+8.610, +x_tr_1), swap_sd=True)
    via1_clean(c, xr_g1, y_w3_g)
    c.wire("metal2", [(xr_g1, y_w3_g), (xr_g1, y_m3_tb["tb1"])], 0.280)
    c.wire("metal2", [(+x_tr_1, y_cap_a), (+x_tr_1, y_sr_p)], 0.280)
    via1_clean(c, +8.750, y_cap_a)

    # 6. Xref_on (exact mirror of Xt0 @ +13.20; swap_sd=False -> drain faces OUTER +13.44 = +x_tr_0, gate tie at +12.60 -> 0.82 clear!)
    _place_mos_unit(c, cache, P_STD, 2.00, 0.18, 1, +13.200, y_sr_p, True,
                    y_vdd_n, y_sr_p, y_w3_g, g_tap_x=+12.600, x_d_span=(+x_tr_0, +13.440), swap_sd=False)
    _place_mos_unit(c, cache, N_STD, 1.00, 0.18, 1, +13.200, y_sr_n, False,
                    y_vss_mid, y_sr_n, y_w3_g, g_tap_x=+12.600, x_d_span=(+x_tr_0, +13.440), swap_sd=False)
    via1_clean(c, +12.600, y_w3_g)
    via1_clean(c, +12.600, y_vdd_n)
    c.wire("metal2", [(+12.600, y_w3_g), (+12.600, y_vdd_n)], 0.280)
    c.wire("metal2", [(+x_tr_0, y_cap_b), (+x_tr_0, y_sr_p)], 0.280)
    via1_clean(c, +13.150, y_cap_b)
    c.wire("metal2", [(+13.150, y_cap_b), (+x_tr_0, y_cap_b)], 0.280)

    # Connect the 5 static DC M3 bridges (`tb5..tb1`) across Band 3
    bridge_specs = [
        ("tb5", -x_tr_5,   xr_g5),
        ("tb2", -x_tr_2,   xr_g2),
        ("tb3", -x_tr_3,   xr_g3),
        ("tb4", -x_tr_4hi, xr_g4),
        ("tb1", -x_tr_1,   xr_g1),
    ]
    for nm, xl, xr in bridge_specs:
        ym = y_m3_tb[nm]
        via2_clean(c, xl, ym)
        via2_clean(c, xr, ym)
        c.wire("metal3", [(xl, ym), (xr, ym)], 0.340)

    # =========================================================================
    # EXACT 13 PORTS (100% 1:1 coordinate & layer match vs 4G `serdes_rx_dt_slicer_pdk.mag`)
    # =========================================================================
    if add_ports:
        c.port("inp", "metal3", -hx, y_inp_m3)
        c.port("inn", "metal3", -hx, y_inn_m3)
        c.port("clk", "metal4", 0.000, y_south_port)
        c.port("qp",  "metal2", -x_q_out, y_north_port)
        c.port("qn",  "metal2", +x_q_out, y_north_port)
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


def verify_dropin_vs_4g(new_mag: Path, ref_4g_mag: Path = REF_4G_MAG) -> dict:
    """Verify exact 1:1 bbox and 13/13 port `(name, layer, x, y)` match vs 4G `serdes_rx_dt_slicer_pdk.mag`."""
    c_new = Cell.read(new_mag)
    c_ref = Cell.read(ref_4g_mag)
    b_new = [round(v, 3) for v in c_new.bbox()]
    b_ref = [round(v, 3) for v in c_ref.bbox()]
    p_new = {nm: (lyr, round(x, 3), round(y, 3)) for lyr, x, y, nm in c_new.labels}
    p_ref = {nm: (lyr, round(x, 3), round(y, 3)) for lyr, x, y, nm in c_ref.labels}
    mismatches = {}
    for nm in sorted(set(p_new) | set(p_ref)):
        if p_new.get(nm) != p_ref.get(nm):
            mismatches[nm] = {"new": p_new.get(nm), "ref_4g": p_ref.get(nm)}
    return {
        "bbox_new": b_new,
        "bbox_4g": b_ref,
        "bbox_exact_match": b_new == b_ref,
        "port_count_new": len(p_new),
        "port_count_4g": len(p_ref),
        "ports_exact_match": len(mismatches) == 0 and len(p_new) == 13,
        "port_mismatches": mismatches,
    }


def extract_slicer_5g_internal_cpex(pex_path: Path) -> dict[str, dict]:
    """Identify `fn`, `fp`, `outp_b`, `outn_b` from StrongARM `_pex.spice` and report CPEX."""
    node_caps = rlc.parse_all_pex_node_caps(pex_path)
    devs = []
    for ln in pex_path.read_text().splitlines():
        if ln.startswith("X"):
            toks = ln.split()
            if len(toks) >= 6:
                devs.append((toks[1], toks[2], toks[3], toks[4], toks[5]))
    inp_t, inn_t = set(), set()
    for d, g, s, b, mdl in devs:
        if mdl == N_LVT and g == "inp":
            inp_t.update((d, s))
        elif mdl == N_LVT and g == "inn":
            inn_t.update((d, s))
    tail_net = inp_t & inn_t
    fn_net = next(iter(inp_t - tail_net), None)
    fp_net = next(iter(inn_t - tail_net), None)

    outp_b_net = outn_b_net = None
    if fn_net and fp_net:
        for d, g, s, b, mdl in devs:
            if mdl == N_LVT and g not in ("inp", "inn", "clk"):
                if fn_net in (d, s):
                    cand = d if s == fn_net else s
                    if cand != fn_net and cand not in tail_net:
                        outp_b_net = cand
                elif fp_net in (d, s):
                    cand = d if s == fp_net else s
                    if cand != fp_net and cand not in tail_net:
                        outn_b_net = cand
    res = {}
    for label, net in (("fn", fn_net), ("fp", fp_net), ("outp_b", outp_b_net), ("outn_b", outn_b_net)):
        if net and net in node_caps:
            res[label] = {"extracted_net": net, **node_caps[net]}
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--signoff", action="store_true",
                    help="Run independent review_cell.py --rc, render PNG, and install into variants/slicer_5g_pdk/")
    args = ap.parse_args()

    cache = PdkCache(WORK_ROOT / "_pdk_cache")
    w = WORK_ROOT / "dev"
    w.mkdir(parents=True, exist_ok=True)
    cell, meta = build_rx_dt_slicer_5g_pdk(cache, add_ports=True)
    mag = w / f"{CELL_NAME}.mag"
    ref = w / f"{CELL_NAME}_ref.spice"
    cell.write(mag)
    ports = generate_slicer_5g_ref_spice(ref, CELL_NAME)

    rep = rlc.verify_flat_cell(w, CELL_NAME, mag, ref, ports)
    dropin = verify_dropin_vs_4g(mag)
    ic = extract_slicer_5g_internal_cpex(w / f"{CELL_NAME}_pex.spice") if (w / f"{CELL_NAME}_pex.spice").exists() else {}

    out_summary = {
        "cell": CELL_NAME,
        **{k: rep[k] for k in (
            "bbox_um", "width_um", "height_um", "area_um2", "aspect_ratio",
            "drc_total", "drc_rules", "floating_poly",
            "lvs_match", "lvs_property_errors", "lvs_disconnected",
            "port_count_match", "exported_ports", "metal_shares",
        )},
        "dropin_vs_4g": dropin,
        "port_caps_fF": rep.get("parasitics", {}).get("port_caps_fF", {}),
        "internal_caps_fF": ic,
    }
    print(json.dumps(out_summary, indent=2), flush=True)

    phys_ok = (
        rep["drc_total"] == 0
        and rep["floating_poly"] == 0
        and rep["lvs_match"]
        and not rep["lvs_property_errors"]
        and not rep["lvs_disconnected"]
        and rep["port_count_match"]
        and dropin["bbox_exact_match"]
        and dropin["ports_exact_match"]
        and rep["metal_shares"]["share_pct"].get("M5", 100.0) == 0.0
    )
    if not phys_ok:
        print("PHYSICAL CHECK FAILED!", flush=True)
        sys.exit(1)

    if args.signoff:
        rev_dir = WORK_ROOT / "review_rc"
        rev = rlc.run_independent_review(mag, ref, rev_dir)
        VARIANT_DIR.mkdir(parents=True, exist_ok=True)
        for fn in (f"{CELL_NAME}.mag", f"{CELL_NAME}_lvs.spice", f"{CELL_NAME}_pex.spice"):
            shutil.copy2(rev_dir / fn, VARIANT_DIR / fn)
        shutil.copy2(ref, VARIANT_DIR / f"{CELL_NAME}_ref.spice")
        png_p = VARIANT_DIR / f"{CELL_NAME}.png"
        rlc.render_png_plot_mag(VARIANT_DIR / f"{CELL_NAME}.mag", png_p)

        signoff_summary = {
            **out_summary,
            "independent_review": rev,
            "sha256": {
                fn: hashlib.sha256((VARIANT_DIR / fn).read_bytes()).hexdigest()
                for fn in (f"{CELL_NAME}.mag", f"{CELL_NAME}_ref.spice",
                           f"{CELL_NAME}_lvs.spice", f"{CELL_NAME}_pex.spice")
            },
        }
        (VARIANT_DIR / "summary.json").write_text(json.dumps(signoff_summary, indent=2) + "\n")
        print(f"\nSIGNOFF PASSED -> {VARIANT_DIR}", flush=True)


if __name__ == "__main__":
    main()
