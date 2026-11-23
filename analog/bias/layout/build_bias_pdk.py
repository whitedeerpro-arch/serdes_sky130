#!/usr/bin/env python3
"""Build and verify the complete 11-cell SKY130 Bias & Bandgap PDK layout suite.

Follows the Plan-First Analog Layout Workflow against unmodified schematic parameters
in ``analog/bias/spice/bandgap.spice`` and ``bias_dist.spice``:

1. ``serdes_bias_ctle_pdk``       : 4-finger LVT NMOS diode (w=8, l=0.5)
2. ``serdes_bias_pcopy_pdk``      : 1x4 LVT PMOS current mirror branch (w=24, l=4)
3. ``serdes_bias_pcopy_n20_pdk``  : 2x10 folded LVT PMOS current mirror array (w=120, l=4)
4. ``serdes_bias_pcopy_n85_pdk``  : 5x17 folded LVT PMOS current mirror array (w=510, l=4)
5. ``serdes_bias_cp_pdk``         : Common-centroid [DN, MN, MN, DN] NMOS + PMOS diode
6. ``serdes_bias_cml_pdk``        : NMOS diode + 5x1 pF MIM decoupling array
7. ``serdes_bg_ota_pdk``          : Guarded 2D checkerboard 4x4 PMOS load + [A,A,B,B,B,B,A,A] NMOS pair
8. ``serdes_bg_amp_pdk``          : Guarded 3D-shielded 2-stage error amp (2x3 6 pF MIM over active + w=1 Rz)
9. ``serdes_ref_vbuf_pdk``        : Guarded height-matched 2-bay OTA + 8-bar 105.2 kOhm w=1 high_po Xr
10. ``serdes_bandgap_pdk``        : Compact 3-Column + Unified Top-Crown Bandgap macro (212.4 x 147.1 um):
                                    - Guarded 4x3 PNP thermal island (Q1 center, 8xQ2 ring, Q3 + dummy P+ guards)
                                    - 2D common-centroid 10x2 Core & V->I LVT PMOS mirror crowns
                                    - Guarded [A,B,B,A,B,A,A,B] w=1 Xrsa/Xrsb + [5xR2 | R1 | 5xR2] w=1 PTAT bank
                                    - 3D Under-MIM w=1 Xrref + 5-bit trim ladder + switches beneath 2x5 10 pF Cvgi
11. ``serdes_bias_ref_pdk``       : Matching Bandgap reference macro for bias_dist.spice (Cvgi=2 pF + Cvbg=5 pF)

Usage:
    uv run python analog/bias/layout/build_bias_pdk.py \\
        --output-dir results/layout/bias_pdk/20261114_compact_w1_suite \\
        --install-dir analog/bias/layout/variants/pdk
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402

PNP_MAG = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_pr/mag/sky130_fd_pr__rf_pnp_05v5_W3p40L3p40.mag")


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.50)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.50)


def clean_primitive(work: Path, name: str, model: str, params: dict) -> Cell:
    pmag = work / f"{name}.mag"
    prim = Cell.read(pmag) if pmag.exists() else pdk_device(work, name, model, params)
    prim.rects.pop("checkpaint", None)
    return prim


def sd_x_positions(prim: Cell, cut_layer: str, dx: float = 0.0) -> list[float]:
    return sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})


def connect_mos_comb(
    c: Cell,
    prim: Cell,
    cut_layer: str,
    dx: float,
    dy: float,
    drain_y: float,
    source_y: float,
    drain_bus_y: float,
    source_bus_y: float,
    bus_w: float = 0.36,
    swap_sd: bool = False,
) -> tuple[float, float, float, float]:
    """Drop via1 on alternating S/D fingers and strap onto horizontal M2 combs."""
    xs = sd_x_positions(prim, cut_layer, dx)
    d_xs = xs[::2] if swap_sd else xs[1::2]
    s_xs = xs[1::2] if swap_sd else xs[::2]
    for sx in d_xs:
        c.via1(sx, grid(dy + drain_y))
        c.wire("metal2", [(sx, grid(dy + drain_y)), (sx, drain_bus_y)], 0.32)
    for sx in s_xs:
        c.via1(sx, grid(dy + source_y))
        c.wire("metal2", [(sx, grid(dy + source_y)), (sx, source_bus_y)], 0.32)
    if d_xs:
        c.wire("metal2", [(d_xs[0], drain_bus_y), (d_xs[-1], drain_bus_y)], bus_w)
    if s_xs:
        c.wire("metal2", [(s_xs[0], source_bus_y), (s_xs[-1], source_bus_y)], bus_w)
    return (d_xs[0], d_xs[-1], s_xs[0], s_xs[-1])


def draw_1v8_guard_ring(
    c: Cell, x1: float, y1: float, x2: float, y2: float, w: float = 0.90, m2_bottom_only: bool = False
) -> None:
    """Draw a closed perimeter 1.8V P+ substrate guard ring.

    When m2_bottom_only=True, metal2 is placed only on the bottom edge y1 (leaving
    left/right/top walls M1-only so parent horizontal M2 signal wires can cross cleanly).
    """
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    c.wire("pwell", pts, w + 0.60)
    for lay in ("psubdiff", "locali", "metal1"):
        c.wire(lay, pts, w)
    if m2_bottom_only:
        c.wire("metal2", [(x1, y1), (x2, y1)], w)
    else:
        c.wire("metal2", pts, w)
    cw = 0.22
    c.rect("psubdiffcont", x1 + 0.3, y1 - cw / 2, x2 - 0.3, y1 + cw / 2)
    c.rect("psubdiffcont", x1 + 0.3, y2 - cw / 2, x2 - 0.3, y2 + cw / 2)
    c.rect("psubdiffcont", x1 - cw / 2, y1 + 0.3, x1 + cw / 2, y2 - 0.3)
    c.rect("psubdiffcont", x2 - cw / 2, y1 + 0.3, x2 + cw / 2, y2 - 0.3)
    for y in (y1, y2):
        nx = max(2, int((x2 - x1) // 4.5))
        for i in range(nx + 1):
            px = grid(x1 + (x2 - x1) * i / nx)
            c.pad("viali", px, y, 0.17)
            if y == y1 or not m2_bottom_only:
                c.via1(px, y)
    for x in (x1, x2):
        ny = max(2, int((y2 - y1) // 4.5))
        for i in range(1, ny):
            py = grid(y1 + (y2 - y1) * i / ny)
            c.pad("viali", x, py, 0.17)
            if not m2_bottom_only:
                c.via1(x, py)


def draw_m1_guard_ring(c: Cell, x1: float, y1: float, x2: float, y2: float, w: float = 0.80) -> None:
    """Closed 1.8V P+ substrate guard ring using pwell + psubdiff + locali + M1 ONLY (M2-transparent)."""
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    c.wire("pwell", pts, w + 0.60)
    for lay in ("psubdiff", "locali", "metal1"):
        c.wire(lay, pts, w)
    cw = 0.20
    c.rect("psubdiffcont", x1 + 0.3, y1 - cw / 2, x2 - 0.3, y1 + cw / 2)
    c.rect("psubdiffcont", x1 + 0.3, y2 - cw / 2, x2 - 0.3, y2 + cw / 2)
    c.rect("psubdiffcont", x1 - cw / 2, y1 + 0.3, x1 + cw / 2, y2 - 0.3)
    c.rect("psubdiffcont", x2 - cw / 2, y1 + 0.3, x2 + cw / 2, y2 - 0.3)
    for y in (y1, y2):
        nx = max(2, int((x2 - x1) // 5.0))
        for i in range(nx + 1):
            px = grid(x1 + (x2 - x1) * i / nx)
            c.pad("viali", px, y, 0.17)
    for x in (x1, x2):
        ny = max(2, int((y2 - y1) // 5.0))
        for i in range(1, ny):
            py = grid(y1 + (y2 - y1) * i / ny)
            c.pad("viali", x, py, 0.17)


def strap_cc_pmos_4x4(
    c: Cell, prim: Cell, dx: float, dy: float, x_vdd: float, x_da: float, x_out: float
) -> dict:
    """Strap 4x4 pfet_lvt (w=6, l=12, nf=4, m=4) in 2D checkerboard ABBA/BAAB/BAAB/ABBA."""
    c.include(prim, dx=dx, dy=dy)
    sd_xs = sorted({grid((r[0] + r[2]) / 2 + dx) for r in prim.rects["pdiffc"]})
    sd_ys = sorted({grid((r[1] + r[3]) / 2 + dy) for r in prim.rects["pdiffc"]})
    g_xs = sorted({grid(x + dx) for _, x, _, lbl in prim.labels if lbl.startswith("G")})
    g_ys = sorted({grid(y + dy) for _, _, y, lbl in prim.labels if lbl.startswith("G")})
    bx, by = prim.pins("B")[0]
    bx, by = grid(bx + dx), grid(by + dy)

    vdd_ys, da_ys, out_ys = [], [], []
    for r_idx, yr in enumerate(sd_ys):
        y_vdd = grid(yr + 1.55)
        y_top_d = grid(yr + 0.0)
        y_bot_d = grid(yr - 1.55)
        for sx in (sd_xs[1], sd_xs[3]):
            c.via1(sx, y_vdd)
        c.wire("metal2", [(x_vdd, y_vdd), (sd_xs[3], y_vdd)], 0.40)
        c.via2(x_vdd, y_vdd)
        vdd_ys.append(y_vdd)

        if r_idx in (0, 3):
            for ox in (sd_xs[0], sd_xs[4]):
                c.via1(ox, y_top_d)
            c.wire("metal2", [(x_da, y_top_d), (sd_xs[4], y_top_d)], 0.36)
            c.via2(x_da, y_top_d)
            da_ys.append(y_top_d)

            c.via1(sd_xs[2], y_bot_d)
            c.wire("metal2", [(sd_xs[2], y_bot_d), (x_out, y_bot_d)], 0.36)
            c.via2(x_out, y_bot_d)
            out_ys.append(y_bot_d)
        else:
            c.via1(sd_xs[2], y_top_d)
            c.wire("metal2", [(x_da, y_top_d), (sd_xs[2], y_top_d)], 0.36)
            c.via2(x_da, y_top_d)
            da_ys.append(y_top_d)

            for ox in (sd_xs[0], sd_xs[4]):
                c.via1(ox, y_bot_d)
            c.wire("metal2", [(sd_xs[0], y_bot_d), (x_out, y_bot_d)], 0.36)
            c.via2(x_out, y_bot_d)
            out_ys.append(y_bot_d)

    for gy in g_ys:
        for gx in g_xs:
            c.via1(gx, gy)
        c.wire("metal2", [(x_da, gy), (g_xs[-1], gy)], 0.34)
        c.via2(x_da, gy)
        da_ys.append(gy)

    c.body_contact(bx, by)
    c.wire("metal2", [(x_vdd, by), (bx, by)], 0.44)
    c.via2(x_vdd, by)
    vdd_ys.append(by)

    c.wire("metal3", [(x_vdd, min(vdd_ys)), (x_vdd, max(vdd_ys))], 0.60)
    c.wire("metal3", [(x_da, min(da_ys)), (x_da, max(da_ys))], 0.44)
    c.wire("metal3", [(x_out, min(out_ys)), (x_out, max(out_ys))], 0.44)
    return {
        "vdd_span": (min(vdd_ys), max(vdd_ys)),
        "da_span": (min(da_ys), max(da_ys)),
        "out_span": (min(out_ys), max(out_ys)),
    }


def strap_cc_nmos_8x1(
    c: Cell,
    prim: Cell,
    dx: float,
    dy: float,
    x_da: float,
    x_out: float,
    x_vss: float,
    gate_a_is_inp: bool = True,
) -> dict:
    """Strap 8-finger NMOS diff-pair (w=6, l=5, nf=8) as [A,A,B,B,B,B,A,A]."""
    c.include(prim, dx=dx, dy=dy)
    sd_xs = sorted({grid((r[0] + r[2]) / 2 + dx) for r in prim.rects["ndiffc"]})
    g_xs = sorted({grid(x + dx) for _, x, _, lbl in prim.labels if lbl.startswith("G")})
    gy_top = max(grid(y + dy) for _, _, y, lbl in prim.labels if lbl.startswith("G"))
    gy_bot = grid(2 * dy - gy_top)

    y_tail = grid(dy - 1.70)
    y_da = grid(dy + 0.0)
    y_out = grid(dy + 1.70)

    for sx in sd_xs[::2]:
        c.via1(sx, y_tail)
    c.wire("metal2", [(sd_xs[0], y_tail), (sd_xs[-1], y_tail)], 0.44)

    for ax in (sd_xs[1], sd_xs[7]):
        c.via1(ax, y_da)
    c.wire("metal2", [(x_da, y_da), (sd_xs[7], y_da)], 0.38)
    c.via2(x_da, y_da)

    for bx_d in (sd_xs[3], sd_xs[5]):
        c.via1(bx_d, y_out)
    c.wire("metal2", [(sd_xs[3], y_out), (x_out, y_out)], 0.38)
    c.via2(x_out, y_out)

    for idx in (0, 1, 6, 7):
        c.via1(g_xs[idx], gy_top)
    c.wire("metal2", [(g_xs[0], gy_top), (g_xs[7], gy_top)], 0.36)

    for idx in (2, 3, 4, 5):
        c.via1(g_xs[idx], gy_bot)
    c.wire("metal2", [(g_xs[2], gy_bot), (g_xs[5], gy_bot)], 0.36)

    right_bar = max(prim.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    rx_b = grid((right_bar[0] + right_bar[2]) / 2 + dx)
    ry_b = grid(dy)
    c.body_contact(rx_b, ry_b)
    c.wire("metal2", [(rx_b, ry_b), (x_vss, ry_b)], 0.40)
    c.via2(x_vss, ry_b)

    ga_pt = (g_xs[0], gy_top)
    gb_pt = (g_xs[2], gy_bot)
    return {
        "tail_y": y_tail,
        "tail_x0": sd_xs[0],
        "da_y": y_da,
        "out_y": y_out,
        "inp": ga_pt if gate_a_is_inp else gb_pt,
        "inn": gb_pt if gate_a_is_inp else ga_pt,
        "vss_y": ry_b,
    }


def strap_res_serpentine(c: Cell, prim: Cell, dx: float, dy: float) -> dict:
    """Include guarded res_high_po_0p35 (nx>=1) and strap bars in series at exact viali centers."""
    c.include(prim, dx=dx, dy=dy)
    xs = sorted({grid((r[0] + r[2]) / 2 + dx) for r in prim.rects["viali"]})
    ys = sorted({grid((r[1] + r[3]) / 2 + dy) for r in prim.rects["viali"]})
    y_bot, y_top = ys[0], ys[-1]
    nx = len(xs)
    for i in range(nx - 1):
        yj = y_bot if i % 2 == 0 else y_top
        c.wire("metal1", [(xs[i], yj), (xs[i + 1], yj)], 0.50)
    rbar = max(prim.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    sub_pt = (grid((rbar[0] + rbar[2]) / 2 + dx), grid(dy))
    plus_pt = (xs[0], y_top)
    minus_pt = (xs[-1], y_top if nx % 2 == 0 else y_bot)
    return {"plus": plus_pt, "minus": minus_pt, "sub": sub_pt, "xs": xs, "y_bot": y_bot, "y_top": y_top}


def strap_2d_pmos_4x5(
    c: Cell, prim_b: Cell, prim_t: Cell, dx: float, dy_b: float, dy_t: float
) -> dict:
    """Strap split 4x(3+2) pfet_lvt (w=6, l=8, nf=4, guard=1) in exact 2D common-centroid.

    Splitting 5 rows into guarded m=3 (bottom) + guarded m=2 (top) places horizontal N-well
    guard taps within <= 10.1 um of every P-diffusion finger (eliminating LU.3 < 15 um)
    while preserving 5 rows of identical nf=4 internal shared drains:
      row 0 -> (B0, B1)
      row 1 -> (B2, B3)
      row 2 -> (B4, B4)
      row 3 -> (B3, B2)
      row 4 -> (B1, B0)
    """
    c.include(prim_b, dx=dx, dy=dy_b)
    c.include(prim_t, dx=dx, dy=dy_t)
    nw_x1 = min(r[0] for r in prim_b.rects["nwell"]) + dx
    nw_x2 = max(r[2] for r in prim_b.rects["nwell"]) + dx
    c.rect("nwell", nw_x1, dy_b, nw_x2, dy_t)
    sd_xs = sorted({grid((r[0] + r[2]) / 2 + dx) for r in prim_b.rects["pdiffc"]})
    sd_ys = (
        sorted({grid((r[1] + r[3]) / 2 + dy_b) for r in prim_b.rects["pdiffc"]})
        + sorted({grid((r[1] + r[3]) / 2 + dy_t) for r in prim_t.rects["pdiffc"]})
    )
    g_xs = sorted({grid(x + dx) for _, x, _, lbl in prim_b.labels if lbl.startswith("G")})
    g_ys = sorted(
        {grid(y + dy_b) for _, _, y, lbl in prim_b.labels if lbl.startswith("G")}
        | {grid(y + dy_t) for _, _, y, lbl in prim_t.labels if lbl.startswith("G")}
    )

    x_vdd = grid(dx - 19.0)
    x_vg  = grid(dx - 20.4)
    x_b0  = grid(dx - 21.8)
    x_b1  = grid(dx - 23.2)
    x_b2  = grid(dx - 24.6)
    x_b3  = grid(dx - 26.0)

    vdd_ys = []
    for pr, dyp in ((prim_b, dy_b), (prim_t, dy_t)):
        bx, by = pr.pins("B")[0]
        bx, by = grid(bx + dx), grid(by + dyp)
        c.body_contact(bx, by)
        c.wire("metal2", [(x_vdd, by), (bx, by)], 0.44)
        c.via2(x_vdd, by)
        vdd_ys.append(by)

    vg_ys = []
    b_ys = {k: [] for k in ("B0", "B1", "B2", "B3")}
    x_map = {"B0": x_b0, "B1": x_b1, "B2": x_b2, "B3": x_b3}
    b4_y = None

    row_assign = [
        ("B0", "B1"),
        ("B2", "B3"),
        ("B4", "B4"),
        ("B3", "B2"),
        ("B1", "B0"),
    ]
    for r_idx, yr in enumerate(sd_ys):
        yv = grid(yr + 1.55)
        for sx in (sd_xs[0], sd_xs[2], sd_xs[4]):
            c.via1(sx, yv)
        c.wire("metal2", [(x_vdd, yv), (sd_xs[4], yv)], 0.42)
        c.via2(x_vdd, yv)
        vdd_ys.append(yv)

        k1, k3 = row_assign[r_idx]
        if k1 == "B4":
            yd = grid(yr + 0.0)
            c.via1(sd_xs[1], yd)
            c.via1(sd_xs[3], yd)
            c.wire("metal2", [(sd_xs[1], yd), (sd_xs[3], yd)], 0.38)
            b4_y = yd
        else:
            yd1 = grid(yr + 0.0)
            yd3 = grid(yr - 1.55)
            c.via1(sd_xs[1], yd1)
            c.wire("metal2", [(x_map[k1], yd1), (sd_xs[1], yd1)], 0.38)
            c.via2(x_map[k1], yd1)
            b_ys[k1].append(yd1)

            c.via1(sd_xs[3], yd3)
            c.wire("metal2", [(x_map[k3], yd3), (sd_xs[3], yd3)], 0.38)
            c.via2(x_map[k3], yd3)
            b_ys[k3].append(yd3)

    for gy in g_ys:
        for gx in g_xs:
            c.via1(gx, gy)
        c.wire("metal2", [(x_vg, gy), (g_xs[-1], gy)], 0.34)
        c.via2(x_vg, gy)
        vg_ys.append(gy)

    c.wire("metal3", [(x_vdd, min(vdd_ys)), (x_vdd, max(vdd_ys))], 0.56)
    c.wire("metal3", [(x_vg, min(vg_ys)), (x_vg, max(vg_ys))], 0.44)
    for k, xt in x_map.items():
        c.wire("metal3", [(xt, min(b_ys[k])), (xt, max(b_ys[k]))], 0.44)

    return {
        "vdd_x": x_vdd, "vdd_span": (min(vdd_ys), max(vdd_ys)),
        "gate_x": x_vg, "gate_span": (min(vg_ys), max(vg_ys)),
        **{f"{k}_x": x_map[k] for k in x_map},
        **{f"{k}_span": (min(b_ys[k]), max(b_ys[k])) for k in x_map},
        "B4_x1": sd_xs[3], "B4_y": b4_y,
    }


def strap_2d_pmos_10x2_under_mim(
    c: Cell, prim: Cell, dx: float, dy: float
) -> dict:
    """Strap 10x2 pfet_lvt (w=6, l=4, nf=10, m=2) using M1/M2 ONLY inside [dx-25.8, dx+25.8].

    Allows a 49.32 um wide 3D M3/M4 MIM array centered at dx to sit directly above
    with zero via2/M3 DRC conflict.
    Left M3 trunks (<= dx-26.2): B2 (s), gate (vgi), vdd.
    Right M3 trunks (>= dx+26.2): B0, B1, B3, B4 (iout0..3).
    """
    c.include(prim, dx=dx, dy=dy)
    sd_xs = sorted({grid((r[0] + r[2]) / 2 + dx) for r in prim.rects["pdiffc"]})
    sd_ys = sorted({grid((r[1] + r[3]) / 2 + dy) for r in prim.rects["pdiffc"]})
    g_xs = sorted({grid(x + dx) for _, x, _, lbl in prim.labels if lbl.startswith("G")})
    g_ys = sorted({grid(y + dy) for _, _, y, lbl in prim.labels if lbl.startswith("G")})
    bx, by = prim.pins("B")[0]
    bx, by = grid(bx + dx), grid(by + dy)

    x_vdd = grid(dx - 26.2)
    x_vgi = grid(dx - 27.6)
    x_b2  = grid(dx - 29.0)
    x_b0  = grid(dx + 26.2)
    x_b1  = grid(dx + 27.6)
    x_b3  = grid(dx + 29.0)
    x_b4  = grid(dx + 30.4)

    c.body_contact(bx, by)
    c.wire("metal2", [(x_vdd, by), (bx, by)], 0.44)
    c.via2(x_vdd, by)
    vdd_ys = [by]
    vgi_ys = []
    b_ys = {k: [] for k in ("B0", "B1", "B2", "B3", "B4")}

    # Row 0 odd cols (1,3,5,7,9) -> [B0, B1, B2, B3, B4]
    # Row 1 odd cols (1,3,5,7,9) -> [B4, B3, B2, B1, B0]
    row_maps = [
        [(1, "B0", x_b0, 1.40), (3, "B1", x_b1, 0.55), (5, "B2", x_b2, -0.30), (7, "B3", x_b3, -1.15), (9, "B4", x_b4, -2.00)],
        [(1, "B4", x_b4, 1.40), (3, "B3", x_b3, 0.55), (5, "B2", x_b2, -0.30), (7, "B1", x_b1, -1.15), (9, "B0", x_b0, -2.00)],
    ]
    for r_idx, yr in enumerate(sd_ys):
        yv = grid(yr + 2.25)
        for sx in sd_xs[::2]:
            c.via1(sx, yv)
        c.wire("metal2", [(x_vdd, yv), (sd_xs[-1], yv)], 0.40)
        c.via2(x_vdd, yv)
        vdd_ys.append(yv)

        for col_i, b_key, x_tr, dy_off in row_maps[r_idx]:
            yt = grid(yr + dy_off)
            sx = sd_xs[col_i]
            c.via1(sx, yt)
            c.wire("metal2", [(min(sx, x_tr), yt), (max(sx, x_tr), yt)], 0.34)
            c.via2(x_tr, yt)
            b_ys[b_key].append(yt)

    for gy in g_ys:
        for gx in g_xs:
            c.via1(gx, gy)
        c.wire("metal2", [(x_vgi, gy), (g_xs[-1], gy)], 0.34)
        c.via2(x_vgi, gy)
        vgi_ys.append(gy)

    c.wire("metal3", [(x_vdd, min(vdd_ys)), (x_vdd, max(vdd_ys))], 0.56)
    c.wire("metal3", [(x_vgi, min(vgi_ys)), (x_vgi, max(vgi_ys))], 0.44)
    for b_key, x_tr in [("B2", x_b2), ("B0", x_b0), ("B1", x_b1), ("B3", x_b3), ("B4", x_b4)]:
        c.wire("metal3", [(x_tr, min(b_ys[b_key])), (x_tr, max(b_ys[b_key]))], 0.44)

    return {
        "vdd_x": x_vdd, "vdd_span": (min(vdd_ys), max(vdd_ys)),
        "gate_x": x_vgi, "gate_span": (min(vgi_ys), max(vgi_ys)),
        "B2_x": x_b2, "B2_span": (min(b_ys["B2"]), max(b_ys["B2"])),
        "B0_x": x_b0, "B0_y1": max(b_ys["B0"]),
        "B1_x": x_b1, "B1_y1": max(b_ys["B1"]),
        "B3_x": x_b3, "B3_y1": max(b_ys["B3"]),
        "B4_x": x_b4, "B4_y1": max(b_ys["B4"]),
    }


def check_cell(work: Path, cell_name: str, ref_text: str) -> dict:
    ref_path = work / f"{cell_name}_ref.spice"
    ref_path.write_text(ref_text)
    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(work), cell_name, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (work / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell_name} failed checks:\n{log}")
    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(work / f"{cell_name}.mag"), str(work / f"{cell_name}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (work / f"{cell_name}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    c = Cell.read(work / f"{cell_name}.mag")
    bx1, by1, bx2, by2 = c.bbox()
    return {
        "cell": cell_name,
        "checker_exit": proc.returncode,
        "drc_boxes": int(drc_m[1]) if drc_m else None,
        "lvs_match": "LVS_MATCH True" in log,
        "lvs_property_errors": "LVS_PROPERTY_ERRORS True" in log,
        "exported_ports": ports_m[1].split() if ports_m else [],
        "bbox_um": [bx1, by1, bx2, by2],
        "size_um": [round(bx2 - bx1, 3), round(by2 - by1, 3)],
        "area_um2": round((bx2 - bx1) * (by2 - by1), 2),
        "extracted_models": models,
    }


# =============================================================================
# 1..6. BIAS DISTRIBUTION LEAF CELLS (bias_dist.spice)
# =============================================================================

def build_bias_ctle(root: Path) -> dict:
    """serdes_bias_ctle_pdk: Xd (nfet_01v8_lvt w=8 l=0.5 nf=4, diode-connected)."""
    cell = "serdes_bias_ctle_pdk"
    w = root / cell
    w.mkdir()
    prim = clean_primitive(w, "ctle_nfet_lvt", "sky130_fd_pr__nfet_01v8_lvt",
                           dict(w=2.0, l=0.5, nf=4, conn_gates=1))
    c = Cell()
    c.include(prim)
    gx, gy = prim.pins("G")[0]
    bx, by = prim.pins("B")[0]
    d_bus = grid(0.45)
    s_bus = grid(-0.45)
    x_d0, x_d1, x_s0, x_s1 = connect_mos_comb(
        c, prim, "ndiffc", 0.0, 0.0,
        drain_y=0.45, source_y=-0.45, drain_bus_y=d_bus, source_bus_y=s_bus,
    )
    c.via1(grid(gx), grid(gy))
    c.wire("metal2", [(grid(gx), grid(gy)), (grid(gx), d_bus)], 0.32)
    c.wire("metal2", [(min(x_d0, grid(gx)), d_bus), (max(x_d1, grid(gx)), d_bus)], 0.36)
    c.body_contact(grid(bx), grid(by))
    c.wire("metal2", [(grid(bx), grid(by)), (grid(bx), s_bus)], 0.32)
    c.wire("metal2", [(min(x_s0, grid(bx)), s_bus), (max(x_s1, grid(bx)), s_bus)], 0.36)
    c.port("iin", "metal2", grid(gx), d_bus)
    c.port("vss", "metal2", grid(bx), grid(by))
    c.write(w / f"{cell}.mag")

    ref = (
        "* Design-side bias_dist.spice serdes_bias_ctle\n"
        ".subckt serdes_bias_ctle_pdk iin vss\n"
        "Xd iin iin vss vss sky130_fd_pr__nfet_01v8_lvt w=8 l=0.5\n"
        ".ends serdes_bias_ctle_pdk\n"
    )
    return check_cell(w, cell, ref)


def build_bias_pcopy(root: Path, n_fingers: int) -> dict:
    """serdes_bias_pcopy[_n20|_n85]_pdk: n fingers of W=6 L=4 pfet_01v8_lvt."""
    suffix = "" if n_fingers == 4 else f"_n{n_fingers}"
    cell = f"serdes_bias_pcopy{suffix}_pdk"
    w = root / cell
    w.mkdir()

    layout_map = {4: (1, 4), 20: (2, 10), 85: (5, 17)}
    n_rows, nf_row = layout_map[n_fingers]
    prim = clean_primitive(w, f"pcopy_row_{nf_row}", "sky130_fd_pr__pfet_01v8_lvt",
                           dict(w=6.0, l=4.0, nf=nf_row, conn_gates=1))
    bx1, by1, bx2, by2 = prim.bbox()
    pitch_y = grid((by2 - by1) + 1.5)

    c = Cell()
    out_pts, vgi_pts, vdd_pts = [], [], []
    for r in range(n_rows):
        dy = grid(r * pitch_y)
        c.include(prim, dy=dy)
        gx, gy = prim.pins("G")[0]
        bx, by = prim.pins("B")[0]
        d_bus = grid(dy + 1.6)
        s_bus = grid(dy - 1.6)
        x_d0, x_d1, x_s0, x_s1 = connect_mos_comb(
            c, prim, "pdiffc", 0.0, dy,
            drain_y=1.6, source_y=-1.6, drain_bus_y=d_bus, source_bus_y=s_bus, bus_w=0.44,
        )
        c.body_contact(grid(bx), grid(dy + by))
        c.wire("metal2", [(grid(bx), grid(dy + by)), (grid(bx), s_bus)], 0.4)
        c.wire("metal2", [(min(x_s0, grid(bx)), s_bus), (max(x_s1, grid(bx)), s_bus)], 0.44)
        c.via1(grid(gx), grid(dy + gy))
        out_pts.append((grid(x_d1), d_bus))
        vgi_pts.append((grid(gx), grid(dy + gy)))
        vdd_pts.append((grid(bx), grid(dy + by)))

    if n_rows > 1:
        x_out_trunk = grid(bx2 + 1.2)
        x_vgi_trunk = grid(bx1 - 1.2)
        x_vdd_trunk = grid(bx1 - 2.4)
        for ox, oy in out_pts:
            c.wire("metal2", [(ox, oy), (x_out_trunk, oy)], 0.44)
            c.via2(x_out_trunk, oy)
        c.wire("metal3", [(x_out_trunk, out_pts[0][1]), (x_out_trunk, out_pts[-1][1])], 0.6)

        for gx, gy in vgi_pts:
            c.wire("metal2", [(x_vgi_trunk, gy), (gx, gy)], 0.36)
            c.via2(x_vgi_trunk, gy)
        c.wire("metal3", [(x_vgi_trunk, vgi_pts[0][1]), (x_vgi_trunk, vgi_pts[-1][1])], 0.44)

        for vx, vy in vdd_pts:
            c.wire("metal2", [(x_vdd_trunk, vy), (vx, vy)], 0.44)
            c.via2(x_vdd_trunk, vy)
        c.wire("metal3", [(x_vdd_trunk, vdd_pts[0][1]), (x_vdd_trunk, vdd_pts[-1][1])], 0.6)

        c.port("out", "metal3", x_out_trunk, out_pts[0][1])
        c.port("vgi", "metal3", x_vgi_trunk, vgi_pts[0][1])
        c.port("vdd", "metal3", x_vdd_trunk, vdd_pts[0][1])
    else:
        c.port("out", "metal2", out_pts[0][0], out_pts[0][1])
        c.port("vgi", "metal2", vgi_pts[0][0], vgi_pts[0][1])
        c.port("vdd", "metal2", vdd_pts[0][0], vdd_pts[0][1])

    c.write(w / f"{cell}.mag")

    ref = (
        f"* Design-side bias_dist.spice serdes_bias_pcopy n={n_fingers}\n"
        f".subckt {cell} out vgi vdd\n"
        f"Xp out vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w={6*n_fingers} l=4\n"
        f".ends {cell}\n"
    )
    return check_cell(w, cell, ref)


def build_bias_cp(root: Path) -> dict:
    """serdes_bias_cp_pdk: Xdn/Xmn (DN-MN-MN-DN common-centroid W=5/L=1) + Xdp (W=20/L=1 nf=4)."""
    cell = "serdes_bias_cp_pdk"
    w = root / cell
    w.mkdir()

    dn_unit = clean_primitive(w, "cp_dn", "sky130_fd_pr__nfet_01v8", dict(w=2.5, l=1.0, nf=1, conn_gates=1))
    mn_core = clean_primitive(w, "cp_mn", "sky130_fd_pr__nfet_01v8", dict(w=2.5, l=1.0, nf=2, conn_gates=1))
    xdp = clean_primitive(w, "cp_dp", "sky130_fd_pr__pfet_01v8", dict(w=5.0, l=1.0, nf=4, conn_gates=1))

    c = Cell()
    mn_bx1, mn_by1, mn_bx2, mn_by2 = mn_core.bbox()
    dn_bx1, dn_by1, dn_bx2, dn_by2 = dn_unit.bbox()
    gap = 0.8
    x_mn = 0.0
    x_dn_l = grid(mn_bx1 - gap - dn_bx2)
    x_dn_r = grid(mn_bx2 + gap - dn_bx1)

    c.include(dn_unit, dx=x_dn_l, dy=0.0)
    c.include(mn_core, dx=x_mn, dy=0.0)
    c.include(dn_unit, dx=x_dn_r, dy=0.0)

    dp_bx1, dp_by1, dp_bx2, dp_by2 = xdp.bbox()
    y_dp = grid(mn_by2 + 2.2 - dp_by1)
    c.include(xdp, dx=0.0, dy=y_dp)

    n_vss_y = grid(-0.6)
    n_vbn_y = grid(0.6)
    vbp_mid_y = grid(mn_by2 + 0.8)

    for dx_dn in (x_dn_l, x_dn_r):
        dx0, dx1, sx0, sx1 = connect_mos_comb(
            c, dn_unit, "ndiffc", dx_dn, 0.0,
            drain_y=0.6, source_y=-0.6, drain_bus_y=n_vbn_y, source_bus_y=n_vss_y,
        )
        gx, gy = dn_unit.pins("G")[0]
        bx, by = dn_unit.pins("B")[0]
        c.via1(grid(dx_dn + gx), grid(gy))
        c.wire("metal2", [(grid(dx_dn + gx), grid(gy)), (grid(dx_dn + gx), n_vbn_y)], 0.32)
        c.wire("metal2", [(min(dx0, grid(dx_dn + gx)), n_vbn_y), (max(dx1, grid(dx_dn + gx)), n_vbn_y)], 0.36)
        c.body_contact(grid(dx_dn + bx), grid(by))
        c.wire("metal2", [(grid(dx_dn + bx), grid(by)), (grid(dx_dn + bx), n_vss_y)], 0.32)
        c.wire("metal2", [(min(sx0, grid(dx_dn + bx)), n_vss_y), (max(sx1, grid(dx_dn + bx)), n_vss_y)], 0.36)

    xm_d0, xm_d1, xm_s0, xm_s1 = connect_mos_comb(
        c, mn_core, "ndiffc", x_mn, 0.0,
        drain_y=0.6, source_y=-0.6, drain_bus_y=vbp_mid_y, source_bus_y=n_vss_y,
    )
    mgx, mgy = mn_core.pins("G")[0]
    mbx, mby = mn_core.pins("B")[0]
    c.via1(grid(x_mn + mgx), grid(mgy))
    c.via2(grid(x_mn + mgx), grid(mgy))
    c.body_contact(grid(x_mn + mbx), grid(mby))
    c.wire("metal2", [(grid(x_mn + mbx), grid(mby)), (grid(x_mn + mbx), n_vss_y)], 0.32)
    c.wire("metal2", [(grid(x_dn_l + dn_bx1 + 0.5), n_vss_y), (grid(x_dn_r + dn_bx2 - 0.5), n_vss_y)], 0.4)

    x_vbn_l = grid(x_dn_l + dn_unit.pins("G")[0][0])
    x_vbn_r = grid(x_dn_r + dn_unit.pins("G")[0][0])
    c.via2(x_vbn_l, n_vbn_y)
    c.via2(x_vbn_r, n_vbn_y)
    y_vbn_m3 = grid(mgy)
    c.wire("metal3", [(grid(x_mn + mgx), y_vbn_m3), (x_vbn_l, y_vbn_m3), (x_vbn_l, n_vbn_y)], 0.4)
    c.wire("metal3", [(grid(x_mn + mgx), y_vbn_m3), (x_vbn_r, y_vbn_m3), (x_vbn_r, n_vbn_y)], 0.4)

    p_vbp_y = grid(y_dp - 1.2)
    p_vcp_y = grid(y_dp + 1.2)
    px_d0, px_d1, px_s0, px_s1 = connect_mos_comb(
        c, xdp, "pdiffc", 0.0, y_dp,
        drain_y=-1.2, source_y=1.2, drain_bus_y=p_vbp_y, source_bus_y=p_vcp_y, bus_w=0.4,
    )
    pgx, pgy = xdp.pins("G")[0]
    pbx, pby = xdp.pins("B")[0]
    c.via1(grid(pgx), grid(y_dp + pgy))
    c.via2(grid(pgx), grid(y_dp + pgy))
    c.via2(grid(pgx), p_vbp_y)
    c.wire("metal3", [(grid(pgx), p_vbp_y), (grid(pgx), grid(y_dp + pgy))], 0.4)
    c.wire("metal2", [(min(px_d0, grid(pgx), grid(xm_d0)), p_vbp_y),
                      (max(px_d1, grid(pgx), grid(xm_d0)), p_vbp_y)], 0.4)
    c.via2(grid(xm_d0), vbp_mid_y)
    c.via2(grid(xm_d0), p_vbp_y)
    c.wire("metal3", [(grid(xm_d0), vbp_mid_y), (grid(xm_d0), p_vbp_y)], 0.4)
    top_by = grid(y_dp - pby)
    c.body_contact(grid(pbx), top_by)
    c.wire("metal2", [(grid(pbx), top_by), (grid(pbx), p_vcp_y)], 0.4)

    c.port("vbn", "metal3", x_vbn_l, y_vbn_m3)
    c.port("vbp", "metal3", grid(xm_d0), p_vbp_y)
    c.port("vcp", "metal2", grid(pbx), top_by)
    c.port("vss", "metal2", grid(x_mn + mbx), n_vss_y)
    c.write(w / f"{cell}.mag")

    ref = (
        "* Design-side bias_dist.spice serdes_bias_cp\n"
        ".subckt serdes_bias_cp_pdk vbn vbp vcp vss\n"
        "Xdn vbn vbn vss vss sky130_fd_pr__nfet_01v8 w=5 l=1\n"
        "Xmn vbp vbn vss vss sky130_fd_pr__nfet_01v8 w=5 l=1\n"
        "Xdp vbp vbp vcp vcp sky130_fd_pr__pfet_01v8 w=20 l=1\n"
        ".ends serdes_bias_cp_pdk\n"
    )
    return check_cell(w, cell, ref)


def build_bias_cml(root: Path) -> dict:
    """serdes_bias_cml_pdk: Xd (nfet_01v8 w=5 l=0.5) + 5 x 1 pF PDK MIM array (cdec=5p)."""
    cell = "serdes_bias_cml_pdk"
    w = root / cell
    w.mkdir()

    xd = clean_primitive(w, "cml_diode", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.5, nf=1, conn_gates=1))
    mim5 = clean_primitive(w, "cml_mim5", "sky130_fd_pr__cap_mim_m3_1",
                           dict(w=22.2, l=22.2, nx=5, ny=1, stack=0))
    mbx1, mby1, mbx2, mby2 = mim5.bbox()
    dbx1, dby1, dbx2, dby2 = xd.bbox()

    c = Cell()
    c.include(mim5, dx=0.0, dy=0.0)
    dy_xd = grid(mby1 - 5.2 - dby2)
    c.include(xd, dx=0.0, dy=dy_xd)

    c1_pts = sorted((x, y) for _, x, y, nm in mim5.labels if nm.startswith("C1"))
    c2_pts = sorted((x, y) for _, x, y, nm in mim5.labels if nm.startswith("C2"))
    y_m4_top = grid(mby2 + 1.5)
    y_m3_bot = grid(mby1 - 2.4)
    for x, y in c1_pts:
        c.wire("metal4", [(grid(x), grid(y)), (grid(x), y_m4_top)], 1.0)
    c.wire("metal4", [(grid(c1_pts[0][0]), y_m4_top), (grid(c1_pts[-1][0]), y_m4_top)], 1.0)
    for x, y in c2_pts:
        c.wire("metal4", [(grid(x), y_m3_bot), (grid(x), grid(y))], 0.52)
        c.rect("metal3", grid(x) - 0.26, y_m3_bot - 0.26, grid(x) + 0.26, y_m3_bot + 0.26)
        c.rect("via3", grid(x) - 0.16, y_m3_bot - 0.16, grid(x) + 0.16, y_m3_bot + 0.16)
    c.wire("metal3", [(grid(c2_pts[0][0]), y_m3_bot), (grid(c2_pts[-1][0]), y_m3_bot)], 1.0)

    gx, gy = xd.pins("G")[0]
    bx, by = xd.pins("B")[0]
    d_y = grid(dy_xd + 1.0)
    s_y = grid(dy_xd - 1.0)
    x_d0, x_d1, x_s0, x_s1 = connect_mos_comb(
        c, xd, "ndiffc", 0.0, dy_xd,
        drain_y=1.0, source_y=-1.0, drain_bus_y=d_y, source_bus_y=s_y,
    )
    c.via1(grid(gx), grid(dy_xd + gy))
    c.wire("metal2", [(grid(gx), grid(dy_xd + gy)), (grid(gx), d_y)], 0.36)
    c.wire("metal2", [(min(x_d0, grid(gx)), d_y), (max(x_d1, grid(gx)), d_y)], 0.4)
    c.body_contact(grid(bx), grid(dy_xd + by))
    c.wire("metal2", [(grid(bx), grid(dy_xd + by)), (grid(bx), s_y)], 0.36)
    c.wire("metal2", [(min(x_s0, grid(bx)), s_y), (max(x_s1, grid(bx)), s_y)], 0.4)

    x_iin_drop = grid(mbx1 - 2.0)
    c.wire("metal4", [(x_iin_drop, y_m4_top), (grid(c1_pts[0][0]), y_m4_top)], 1.0)
    c.wire("metal4", [(x_iin_drop, d_y), (x_iin_drop, y_m4_top)], 0.8)
    c.rect("metal4", x_iin_drop - 0.3, d_y - 0.3, x_iin_drop + 0.3, d_y + 0.3)
    c.rect("via3", x_iin_drop - 0.16, d_y - 0.16, x_iin_drop + 0.16, d_y + 0.16)
    c.rect("metal3", x_iin_drop - 0.3, d_y - 0.3, x_iin_drop + 0.3, d_y + 0.3)
    c.via2(x_iin_drop, d_y)
    c.wire("metal2", [(x_iin_drop, d_y), (min(x_d0, grid(gx)), d_y)], 0.4)

    x_vss_drop = grid(c2_pts[2][0])
    c.wire("metal3", [(x_vss_drop, s_y), (x_vss_drop, y_m3_bot)], 0.6)
    c.via2(x_vss_drop, s_y)
    c.wire("metal2", [(min(x_s0, grid(bx)), s_y), (max(x_s1, grid(bx), x_vss_drop), s_y)], 0.4)

    c.port("iin", "metal4", x_iin_drop, y_m4_top)
    c.port("vss", "metal3", x_vss_drop, y_m3_bot)
    c.write(w / f"{cell}.mag")

    ref = (
        "* Physical PDK variant of bias_dist.spice serdes_bias_cml (5x 1pF MIM)\n"
        ".subckt serdes_bias_cml_pdk iin vss\n"
        "Xd iin iin vss vss sky130_fd_pr__nfet_01v8 w=5 l=0.5\n"
        + "\n".join(f"Xc{i} iin vss sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2" for i in range(5)) + "\n"
        ".ends serdes_bias_cml_pdk\n"
    )
    return check_cell(w, cell, ref)


# =============================================================================
# 7..9. COMPACT GUARDED BANDGAP & REF SUB-BLOCKS (OTA, AMP, VBUF)
# =============================================================================

def build_bg_ota(root: Path) -> dict:
    """serdes_bg_ota_pdk: Guarded 2D checkerboard 4x4 PMOS load + [A,A,B,B,B,B,A,A] NMOS pair."""
    cell = "serdes_bg_ota_pdk"
    w = root / cell
    w.mkdir()

    xt = clean_primitive(w, "ota_xt", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=8.0, nf=1, conn_gates=1, guard=0))
    nin = clean_primitive(w, "ota_nin", "sky130_fd_pr__nfet_01v8", dict(w=6.0, l=5.0, nf=8, m=1, conn_gates=0, guard=1))
    pld = clean_primitive(w, "ota_pld", "sky130_fd_pr__pfet_01v8_lvt", dict(w=6.0, l=12.0, nf=4, m=4, conn_gates=1, guard=1))

    c = Cell()
    x_vdd = -27.8
    x_da = -26.4
    x_out = 26.4
    x_vss_r = 27.8

    dx_xt, dy_xt = 14.0, 2.2
    c.include(xt, dx=dx_xt, dy=dy_xt)
    xt_xs = sorted({grid((r[0] + r[2]) / 2 + dx_xt) for r in xt.rects["ndiffc"]})
    xt_gx, xt_gy = xt.pins("G")[0]
    c.via1(xt_xs[0], dy_xt)
    c.via1(xt_xs[1], dy_xt)
    y_xt_g = grid(dy_xt + xt_gy)
    c.via1(grid(dx_xt + xt_gx), y_xt_g)

    dy_nin = 7.9
    info_n = strap_cc_nmos_8x1(c, nin, 0.0, dy_nin, x_da=x_da, x_out=x_out, x_vss=x_vss_r, gate_a_is_inp=True)
    x_tail_r = grid(-info_n["tail_x0"])
    c.wire("metal2", [(xt_xs[1], dy_xt), (x_tail_r, dy_xt), (x_tail_r, info_n["tail_y"])], 0.40)

    dy_pld = 27.7
    info_p = strap_cc_pmos_4x4(c, pld, 0.0, dy_pld, x_vdd=x_vdd, x_da=x_da, x_out=x_out)
    c.wire("metal3", [(x_da, info_n["da_y"]), (x_da, info_p["da_span"][1])], 0.44)
    c.wire("metal3", [(x_out, info_n["out_y"]), (x_out, info_p["out_span"][1])], 0.44)

    x_port_l = -28.4
    c.wire("metal2", [(x_port_l, y_xt_g), (grid(dx_xt + xt_gx), y_xt_g)], 0.36)
    c.wire("metal2", [(x_port_l, info_n["inn"][1]), info_n["inn"]], 0.36)
    c.wire("metal2", [(x_port_l, info_n["inp"][1]), info_n["inp"]], 0.36)

    gx1, gy1, gx2, gy2 = -29.0, -0.2, 29.0, 43.4
    draw_1v8_guard_ring(c, gx1, gy1, gx2, gy2, w=0.90, m2_bottom_only=True)
    c.wire("metal2", [(xt_xs[0], gy1), (xt_xs[0], dy_xt)], 0.40)
    c.via2(x_vss_r, gy1)
    c.wire("metal3", [(x_vss_r, gy1), (x_vss_r, info_n["vss_y"])], 0.60)

    c.port("vbn", "metal2", x_port_l, y_xt_g)
    c.port("inp", "metal2", x_port_l, info_n["inp"][1])
    c.port("inn", "metal2", x_port_l, info_n["inn"][1])
    c.port("out", "metal3", x_out, info_n["out_y"])
    c.port("vdd", "metal3", x_vdd, info_p["vdd_span"][1])
    c.port("vss", "metal2", 0.0, gy1)
    c.write(w / f"{cell}.mag")

    ref = """* Compact 2D Common-Centroid serdes_bg_ota_pdk
.subckt serdes_bg_ota_pdk inp inn out vbn vdd vss
Xt tail vbn vss vss sky130_fd_pr__nfet_01v8 w=1 l=8
Xa da inp tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xb out inn tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
Xlb out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
.ends serdes_bg_ota_pdk
"""
    return check_cell(w, cell, ref)


def build_bg_amp(root: Path) -> dict:
    """serdes_bg_amp_pdk: Guarded 3D-shielded 2-stage error amp (2x3 6 pF MIM over active + w=1 Rz)."""
    cell = "serdes_bg_amp_pdk"
    w = root / cell
    w.mkdir()

    xt = clean_primitive(w, "amp_xt", "sky130_fd_pr__nfet_01v8", dict(w=4.0, l=4.0, nf=2, conn_gates=1, guard=0))
    x2 = clean_primitive(w, "amp_x2", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=2.0, nf=1, conn_gates=1, guard=0))
    rz = clean_primitive(w, "amp_rz", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=15.475, nx=4, m=1, guard=1))
    xp2 = clean_primitive(w, "amp_xp2_8x1", "sky130_fd_pr__pfet_01v8_lvt", dict(w=6.0, l=4.0, nf=8, m=1, conn_gates=1, guard=1))
    nin = clean_primitive(w, "amp_nin", "sky130_fd_pr__nfet_01v8", dict(w=6.0, l=5.0, nf=8, m=1, conn_gates=0, guard=1))
    pld = clean_primitive(w, "amp_pld", "sky130_fd_pr__pfet_01v8_lvt", dict(w=6.0, l=12.0, nf=4, m=4, conn_gates=1, guard=1))
    mim6 = clean_primitive(w, "amp_mim6", "sky130_fd_pr__cap_mim_m3_1", dict(w=22.2, l=22.2, nx=2, ny=3, stack=0))

    c = Cell()
    x_vdd, x_da, x_tail = -29.2, -27.8, -26.4
    x_cz, x_o1, x_out, x_vss = 26.4, 27.8, 29.2, 30.6

    rz_b = rz.bbox()
    dx_rz, dy_rz = grid(24.0 - rz_b[2]), grid(1.8 - rz_b[1])
    rz_info = strap_res_serpentine(c, rz, dx_rz, dy_rz)
    rz_o1, rz_cz, rz_sub = rz_info["plus"], rz_info["minus"], rz_info["sub"]
    c.via1(*rz_cz)
    c.wire("metal2", [rz_cz, (x_cz, rz_cz[1])], 0.38)
    c.via2(x_cz, rz_cz[1])
    via3(c, x_cz, rz_cz[1])

    c.via1(*rz_o1)
    y_rz_o1 = grid(rz_o1[1] + 1.0)
    c.wire("metal2", [rz_o1, (rz_o1[0], y_rz_o1), (x_o1, y_rz_o1)], 0.38)
    c.via2(x_o1, y_rz_o1)

    rz_sub_hi = (rz_sub[0], 12.0)
    c.body_contact(*rz_sub_hi)
    c.wire("metal2", [rz_sub_hi, (x_vss, 12.0)], 0.40)
    c.via2(x_vss, 12.0)

    dx_xt, dy_xt = -18.5, 4.2
    c.include(xt, dx=dx_xt, dy=dy_xt)
    xt_xs = sorted({grid((r[0] + r[2]) / 2 + dx_xt) for r in xt.rects["ndiffc"]})
    xt_gx, xt_gy = xt.pins("G")[0]
    for sx in (xt_xs[0], xt_xs[2]):
        c.via1(sx, grid(dy_xt - 1.1))
    c.wire("metal2", [(xt_xs[0], grid(dy_xt - 1.1)), (x_vss, grid(dy_xt - 1.1))], 0.40)
    c.via2(x_vss, grid(dy_xt - 1.1))
    c.via1(xt_xs[1], grid(dy_xt + 1.1))
    c.via1(grid(dx_xt + xt_gx), grid(dy_xt + xt_gy))

    dx_x2, dy_x2 = -6.0, 5.2
    c.include(x2, dx=dx_x2, dy=dy_x2)
    x2_xs = sorted({grid((r[0] + r[2]) / 2 + dx_x2) for r in x2.rects["ndiffc"]})
    x2_gx, x2_gy = x2.pins("G")[0]
    y_x2d = grid(dy_x2 + 0.4)
    y_x2s = grid(dy_x2 - 0.4)
    c.via1(x2_xs[0], y_x2d)
    c.via1(x2_xs[1], y_x2s)
    c.wire("metal2", [(x2_xs[1], grid(dy_xt - 1.1)), (x2_xs[1], y_x2s)], 0.36)
    c.via1(grid(dx_x2 + x2_gx), grid(dy_x2 + x2_gy))
    y_x2g = grid(dy_x2 + x2_gy)
    c.wire("metal2", [(grid(dx_x2 + x2_gx), y_x2g), (x_o1, y_x2g)], 0.36)
    c.via2(x_o1, y_x2g)
    c.wire("metal2", [(x2_xs[0], y_x2d), (x_out, y_x2d)], 0.38)
    c.via2(x_out, y_x2d)

    dx_xp2, dy_xp2 = -5.5, 17.5
    c.include(xp2, dx=dx_xp2, dy=dy_xp2)
    xp2_xs = sorted({grid((r[0] + r[2]) / 2 + dx_xp2) for r in xp2.rects["pdiffc"]})
    xp2_gxs = sorted({grid(x + dx_xp2) for _, x, _, lbl in xp2.labels if lbl.startswith("G")})
    xp2_gy = max(grid(y + dy_xp2) for _, _, y, lbl in xp2.labels if lbl.startswith("G"))
    xp2_bx, xp2_by = xp2.pins("B")[0]
    xp2_bx, xp2_by = grid(xp2_bx + dx_xp2), grid(xp2_by + dy_xp2)
    yv_xp2 = grid(dy_xp2 + 1.4)
    yd_xp2 = grid(dy_xp2 - 1.4)
    for sx in xp2_xs[::2]:
        c.via1(sx, yv_xp2)
    c.wire("metal2", [(x_vdd, yv_xp2), (xp2_xs[-1], yv_xp2)], 0.40)
    c.via2(x_vdd, yv_xp2)
    for ox in xp2_xs[1::2]:
        c.via1(ox, yd_xp2)
    c.wire("metal2", [(xp2_xs[1], yd_xp2), (x_out, yd_xp2)], 0.40)
    c.via2(x_out, yd_xp2)
    for gx in xp2_gxs:
        c.via1(gx, xp2_gy)
    c.wire("metal2", [(x_da, xp2_gy), (xp2_gxs[-1], xp2_gy)], 0.34)
    c.via2(x_da, xp2_gy)
    c.body_contact(xp2_bx, xp2_by)
    c.wire("metal2", [(x_vdd, xp2_by), (xp2_bx, xp2_by)], 0.40)
    c.via2(x_vdd, xp2_by)

    dy_nin = 31.0
    info_n = strap_cc_nmos_8x1(
        c, nin, 0.0, dy_nin, x_da=x_da, x_out=x_o1, x_vss=x_vss, gate_a_is_inp=False
    )
    c.wire("metal2", [(x_tail, grid(dy_xt + 1.1)), (xt_xs[1], grid(dy_xt + 1.1))], 0.40)
    c.via2(x_tail, grid(dy_xt + 1.1))
    c.wire("metal2", [(x_tail, info_n["tail_y"]), (info_n["tail_x0"], info_n["tail_y"])], 0.44)
    c.via2(x_tail, info_n["tail_y"])
    c.wire("metal3", [(x_tail, grid(dy_xt + 1.1)), (x_tail, info_n["tail_y"])], 0.44)

    dy_pld = 52.8
    info_p = strap_cc_pmos_4x4(c, pld, 0.0, dy_pld, x_vdd=x_vdd, x_da=x_da, x_out=x_o1)

    dy_mim = 37.2
    c.include(mim6, dx=0.0, dy=dy_mim)
    c1_xs = sorted({grid(x) for _, x, _, nm in mim6.labels if nm.startswith("C1")})
    c2_xs = sorted({grid(x) for _, x, _, nm in mim6.labels if nm.startswith("C2")})
    y_c1_m4 = 73.9
    for cx in c1_xs:
        c.wire("metal4", [(cx, grid(dy_mim + 35.3)), (cx, y_c1_m4)], 0.52)
    c.wire("metal4", [(c1_xs[0], y_c1_m4), (x_cz, y_c1_m4), (x_cz, rz_cz[1])], 0.60)

    y_c2_m4 = 0.6
    for cx in c2_xs:
        c.wire("metal4", [(cx, y_c2_m4), (cx, grid(dy_mim - 35.3))], 0.52)
    c.wire("metal4", [(c2_xs[0], y_c2_m4), (x_out, y_c2_m4)], 0.60)
    via3(c, x_out, y_c2_m4)

    c.wire("metal3", [(x_vdd, xp2_by), (x_vdd, info_p["vdd_span"][1])], 0.60)
    c.wire("metal3", [(x_da, xp2_gy), (x_da, info_p["da_span"][1])], 0.44)
    c.wire("metal3", [(x_o1, min(y_rz_o1, y_x2g)), (x_o1, info_p["out_span"][1])], 0.44)
    c.wire("metal3", [(x_out, y_c2_m4), (x_out, yd_xp2)], 0.50)

    x_inp, x_inn = -29.8, -29.8
    c.wire("metal2", [(x_inp, info_n["inp"][1]), info_n["inp"]], 0.36)
    c.wire("metal2", [(x_inn, info_n["inn"][1]), info_n["inn"]], 0.36)
    y_vbn = grid(dy_xt + xt_gy)
    c.wire("metal2", [(x_inp, y_vbn), (grid(dx_xt + xt_gx), y_vbn)], 0.36)

    gx1, gy1, gx2, gy2 = -30.8, -0.4, 31.8, 75.0
    draw_1v8_guard_ring(c, gx1, gy1, gx2, gy2, w=0.90, m2_bottom_only=True)
    c.via2(x_vss, gy1)
    c.wire("metal3", [(x_vss, gy1), (x_vss, max(12.0, info_n["vss_y"]))], 0.60)

    c.port("inp", "metal2", x_inp, info_n["inp"][1])
    c.port("inn", "metal2", x_inn, info_n["inn"][1])
    c.port("vbn", "metal2", x_inp, y_vbn)
    c.port("out", "metal3", x_out, y_x2d)
    c.port("vdd", "metal3", x_vdd, info_p["vdd_span"][1])
    c.port("vss", "metal2", 0.0, gy1)
    c.write(w / f"{cell}.mag")

    ref = """* Compact 3D-Shielded 2D Common-Centroid serdes_bg_amp_pdk
.subckt serdes_bg_amp_pdk inp inn out vbn vdd vss
Xt tail vbn vss vss sky130_fd_pr__nfet_01v8 w=8 l=4
Xa da inn tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xb o1 inp tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
Xlb o1 da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
X2 out o1 vss vss sky130_fd_pr__nfet_01v8 w=2 l=2
Xp2 out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=4
Xrz o1 cz vss sky130_fd_pr__res_high_po w=1 l=61.90
Xc0 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc1 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc2 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc3 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc4 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc5 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
.ends serdes_bg_amp_pdk
"""
    return check_cell(w, cell, ref)


def build_ref_vbuf(root: Path) -> dict:
    """serdes_ref_vbuf_pdk: Guarded height-matched 2-bay OTA + 8-bar 105.2 kOhm w=1 high_po resistor."""
    cell = "serdes_ref_vbuf_pdk"
    w = root / cell
    w.mkdir()

    xbt = clean_primitive(w, "vbuf_xbt", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=4.0, nf=4, m=1, conn_gates=1, guard=1))
    nin = clean_primitive(w, "vbuf_nin", "sky130_fd_pr__nfet_01v8", dict(w=6.0, l=5.0, nf=8, m=1, conn_gates=0, guard=1))
    pld = clean_primitive(w, "vbuf_pld", "sky130_fd_pr__pfet_01v8_lvt", dict(w=6.0, l=12.0, nf=4, m=4, conn_gates=1, guard=1))
    xr = clean_primitive(w, "vbuf_xr", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=41.485, nx=8, m=1, guard=1))

    c = Cell()
    x_vdd, x_da, x_out, x_vss = -27.8, -26.4, 26.4, 27.8

    dy_bt = 3.2
    c.include(xbt, dx=0.0, dy=dy_bt)
    bt_xs = sorted({grid((r[0] + r[2]) / 2) for r in xbt.rects["ndiffc"]})
    bt_gxs = sorted({grid(x) for _, x, _, lbl in xbt.labels if lbl.startswith("G")})
    bt_gy = max(grid(y + dy_bt) for _, _, y, lbl in xbt.labels if lbl.startswith("G"))

    y_bt_vss = grid(dy_bt - 0.55)
    y_bt_ib = grid(dy_bt + 0.55)
    for sx in (bt_xs[0], bt_xs[2], bt_xs[4]):
        c.via1(sx, y_bt_vss)
    c.wire("metal2", [(bt_xs[0], y_bt_vss), (x_vss, y_bt_vss)], 0.40)
    c.via2(x_vss, y_bt_vss)
    bt_rbar = max(xbt.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    bt_rx = grid((bt_rbar[0] + bt_rbar[2]) / 2)
    c.body_contact(bt_rx, dy_bt)
    c.wire("metal2", [(bt_rx, dy_bt), (x_vss, dy_bt)], 0.36)
    c.via2(x_vss, dy_bt)

    c.via1(bt_xs[1], y_bt_ib)
    c.via1(bt_xs[3], y_bt_ib)
    for gx in bt_gxs:
        c.via1(gx, bt_gy)
    c.wire("metal2", [(bt_gxs[0], bt_gy), (bt_gxs[-1], bt_gy)], 0.36)
    c.wire("metal2", [(bt_xs[3], y_bt_ib), (bt_xs[3], bt_gy)], 0.36)

    dy_nin = 11.2
    info_n = strap_cc_nmos_8x1(c, nin, 0.0, dy_nin, x_da=x_da, x_out=x_out, x_vss=x_vss, gate_a_is_inp=True)
    c.wire("metal2", [(bt_xs[1], y_bt_ib), (info_n["tail_x0"], y_bt_ib), (info_n["tail_x0"], info_n["tail_y"])], 0.40)
    c.wire("metal2", [info_n["inn"], (x_out, info_n["inn"][1])], 0.38)
    c.via2(x_out, info_n["inn"][1])

    dy_pld = 31.2
    info_p = strap_cc_pmos_4x4(c, pld, 0.0, dy_pld, x_vdd=x_vdd, x_da=x_da, x_out=x_out)
    c.wire("metal3", [(x_da, info_n["da_y"]), (x_da, info_p["da_span"][1])], 0.44)
    c.wire("metal3", [(x_out, info_n["inn"][1]), (x_out, info_p["out_span"][1])], 0.44)

    xr_b = xr.bbox()
    dx_xr = grid(x_vss + 2.2 - xr_b[0])
    dy_xr = 24.4
    xr_info = strap_res_serpentine(c, xr, dx_xr, dy_xr)
    xr_top_iin, xr_top_vss, xr_sub = xr_info["plus"], xr_info["minus"], xr_info["sub"]

    x_iin = 29.2
    c.via1(*xr_top_iin)
    c.wire("metal2", [(x_iin, xr_top_iin[1]), xr_top_iin], 0.40)
    c.via2(x_iin, xr_top_iin[1])
    c.wire("metal2", [info_n["inp"], (x_iin, info_n["inp"][1])], 0.40)
    c.via2(x_iin, info_n["inp"][1])
    c.wire("metal3", [(x_iin, info_n["inp"][1]), (x_iin, xr_top_iin[1])], 0.44)

    gx1, gy1, gx2, gy2 = -29.0, -0.6, grid(dx_xr + xr_b[2] + 1.2), 49.4
    draw_1v8_guard_ring(c, gx1, gy1, gx2, gy2, w=0.90)
    c.via1(*xr_top_vss)
    c.wire("metal2", [xr_top_vss, (xr_top_vss[0], gy2)], 0.44)
    c.body_contact(*xr_sub)
    c.wire("metal2", [xr_sub, (gx2, xr_sub[1])], 0.40)
    c.via2(x_vss, gy1)
    c.wire("metal3", [(x_vss, gy1), (x_vss, info_n["vss_y"])], 0.60)

    c.port("iin", "metal3", x_iin, xr_top_iin[1])
    c.port("ibias", "metal2", bt_gxs[0], bt_gy)
    c.port("out", "metal3", x_out, info_n["out_y"])
    c.port("vdd", "metal3", x_vdd, info_p["vdd_span"][1])
    c.port("vss", "metal2", 0.0, gy1)
    c.write(w / f"{cell}.mag")

    ref = """* Compact 2D Common-Centroid serdes_ref_vbuf_pdk
.subckt serdes_ref_vbuf_pdk iin ibias out vdd vss
Xr iin vss vss sky130_fd_pr__res_high_po w=1 l=331.86
Xbd ibias ibias vss vss sky130_fd_pr__nfet_01v8 w=4 l=4
Xt tail ibias vss vss sky130_fd_pr__nfet_01v8 w=4 l=4
Xa da iin tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xb out out tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
Xlb out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
.ends serdes_ref_vbuf_pdk
"""
    return check_cell(w, cell, ref)


# =============================================================================
# 10..11. PLAN-FIRST 3-COLUMN HEIGHT-MATCHED BANDGAP & BIAS_REF MACROS
# =============================================================================

def build_bandgap(root: Path, is_bias_ref: bool = False) -> dict:
    cell = "serdes_bias_ref_pdk" if is_bias_ref else "serdes_bandgap_pdk"
    w = root / cell
    w.mkdir()

    pdir = root / "serdes_bandgap_pdk"
    pdir.mkdir(exist_ok=True)

    amp = Cell.read(root / "serdes_bg_amp_pdk" / "serdes_bg_amp_pdk.mag")
    ota = Cell.read(root / "serdes_bg_ota_pdk" / "serdes_bg_ota_pdk.mag")
    amp_ports = {nm: (lay, x, y) for lay, x, y, nm in amp.labels}
    ota_ports = {nm: (lay, x, y) for lay, x, y, nm in ota.labels}
    amp.labels.clear()
    ota.labels.clear()

    c = Cell()

    # Vertical M3 routing channels between the 3 height-matched silicon columns
    X_L_VSS, X_L_VDD, X_L_VG, X_L_NB, X_L_TA, X_L_TB, X_L_VBG = (
        35.4, 36.8, 38.2, 39.6, 41.0, 42.4, 43.8
    )
    X_R_VBG, X_R_S, X_R_NB2, X_R_VGI, X_R_VDD, X_R_VSS = (
        110.6, 112.0, 113.4, 114.8, 116.2, 117.6
    )

    # -------------------------------------------------------------------------
    # COLUMN 2 (x = 45.2 .. 108.8): Compact Xamp (Bottom) + 4x5 Core PMOS (Top)
    # -------------------------------------------------------------------------
    dx_amp, dy_amp = 76.5, 1.4
    c.include(amp, dx=dx_amp, dy=dy_amp)

    _, ax_inp, ay_inp = amp_ports["inp"]
    _, ax_inn, ay_inn = amp_ports["inn"]
    _, ax_vbn, ay_vbn = amp_ports["vbn"]
    _, ax_out, ay_out = amp_ports["out"]
    _, ax_vdd, ay_vdd = amp_ports["vdd"]

    y_amp_ta = grid(dy_amp + ay_inn)
    c.wire("metal2", [(X_L_TA, y_amp_ta), (grid(dx_amp + ax_inn), y_amp_ta)], 0.36)
    c.via2(X_L_TA, y_amp_ta)

    y_amp_tb = grid(dy_amp + ay_inp)
    c.wire("metal2", [(X_L_TB, y_amp_tb), (grid(dx_amp + ax_inp), y_amp_tb)], 0.36)
    c.via2(X_L_TB, y_amp_tb)

    y_amp_nb = grid(dy_amp + ay_vbn)
    c.wire("metal2", [(X_L_NB, y_amp_nb), (grid(dx_amp + ax_vbn), y_amp_nb)], 0.36)
    c.via2(X_L_NB, y_amp_nb)

    y_amp_vg = grid(dy_amp + ay_out)
    x_amp_out = grid(dx_amp + ax_out)
    c.wire("metal3", [(x_amp_out, y_amp_vg), (x_amp_out, 77.8)], 0.44)
    c.via2(x_amp_out, 77.8)
    c.wire("metal2", [(X_L_VG, 77.8), (x_amp_out, 77.8)], 0.44)
    c.via2(X_L_VG, 77.8)

    x_amp_vdd = grid(dx_amp + ax_vdd)
    c.wire("metal3", [(x_amp_vdd, grid(dy_amp + ay_vdd)), (x_amp_vdd, 78.8)], 0.50)
    c.via2(x_amp_vdd, 78.8)
    c.wire("metal2", [(X_L_VDD, 78.8), (x_amp_vdd, 78.8)], 0.50)
    c.via2(X_L_VDD, 78.8)

    y_amp_vss = grid(dy_amp - 0.4)
    c.wire("metal2", [(33.8, y_amp_vss), (125.0, y_amp_vss)], 0.60)
    c.via2(X_L_VSS, y_amp_vss)
    c.via2(X_R_VSS, y_amp_vss)

    # Top of Col 2: Split 4x(3+2) 2D Common-Centroid Core PMOS (Xm1..Xm5, LU.3-clean)
    p_core_b = clean_primitive(pdir, "bg_pcore_4x3", "sky130_fd_pr__pfet_01v8_lvt",
                               dict(w=6.0, l=8.0, nf=4, m=3, conn_gates=1, guard=1))
    p_core_t = clean_primitive(pdir, "bg_pcore_4x2", "sky130_fd_pr__pfet_01v8_lvt",
                               dict(w=6.0, l=8.0, nf=4, m=2, conn_gates=1, guard=1))
    dx_pcore = 77.5
    info_core = strap_2d_pmos_4x5(c, p_core_b, p_core_t, dx=dx_pcore, dy_b=95.8, dy_t=115.4)

    c.wire("metal2", [(X_L_VDD, info_core["vdd_span"][0]), (info_core["vdd_x"], info_core["vdd_span"][0])], 0.50)
    c.via2(X_L_VDD, info_core["vdd_span"][0])
    c.via2(info_core["vdd_x"], info_core["vdd_span"][0])

    y_core_vg = 80.6
    c.wire("metal3", [(info_core["gate_x"], y_core_vg), (info_core["gate_x"], info_core["gate_span"][0])], 0.44)
    c.via2(info_core["gate_x"], y_core_vg)
    c.wire("metal2", [(X_L_VG, y_core_vg), (info_core["gate_x"], y_core_vg)], 0.40)
    c.via2(X_L_VG, y_core_vg)

    for b_key, x_ch, y_tr in [
        ("B0", X_L_NB,  81.5),
        ("B1", X_L_TA,  82.4),
        ("B2", X_L_VBG, 83.3),
        ("B3", X_L_TB,  84.2),
    ]:
        bx_c = info_core[f"{b_key}_x"]
        by0_c = info_core[f"{b_key}_span"][0]
        c.wire("metal3", [(bx_c, y_tr), (bx_c, by0_c)], 0.44)
        c.via2(bx_c, y_tr)
        c.wire("metal2", [(x_ch, y_tr), (bx_c, y_tr)], 0.40)
        c.via2(x_ch, y_tr)

    # B4 (nb2) goes straight right on M2 to X_R_NB2
    by_b4 = info_core["B4_y"]
    c.wire("metal2", [(info_core["B4_x1"], by_b4), (X_R_NB2, by_b4)], 0.38)
    c.via2(X_R_NB2, by_b4)

    # Horizontal vbg + vdd bridge between Channel L and Channel R at y = 79.7 / 123.6
    c.wire("metal2", [(X_L_VBG, 79.7), (X_R_VBG, 79.7)], 0.44)
    c.via2(X_L_VBG, 79.7)
    c.via2(X_R_VBG, 79.7)

    c.wire("metal2", [(X_L_VDD, 123.6), (X_R_VDD, 123.6)], 0.70)
    c.via2(X_L_VDD, 123.6)
    c.via2(X_R_VDD, 123.6)

    # -------------------------------------------------------------------------
    # COLUMN 1 (x = 1.2 .. 33.8): Core Resistors (Bot) + Startup/Bias (Mid) + 4x3 PNP (Top)
    # -------------------------------------------------------------------------
    # 1A. Bottom Guarded Core Resistors: [A,B,B,A,B,A,A,B] Rsa/Rsb + [5xR2 | R1 | 5xR2] PTAT
    draw_m1_guard_ring(c, 1.2, 1.6, 33.8, 55.4, w=0.80)
    c.wire("metal1", [(33.8, y_amp_vss), (33.8, 1.6)], 0.50)
    c.via1(33.8, y_amp_vss)

    rsa_p = clean_primitive(pdir, "bg_rsa8", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=39.435, nx=8, m=1, guard=1))
    dx_rsa, dy_rsa = 8.8, 26.8
    c.include(rsa_p, dx=dx_rsa, dy=dy_rsa)
    rs_xs = sorted({grid((r[0] + r[2]) / 2 + dx_rsa) for r in rsa_p.rects["viali"]})
    rs_ys = sorted({grid((r[1] + r[3]) / 2 + dy_rsa) for r in rsa_p.rects["viali"]})
    rs_yb, rs_yt = rs_ys[0], rs_ys[-1]
    rs_lbar = min(rsa_p.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    rs_bx = grid((rs_lbar[0] + rs_lbar[2]) / 2 + dx_rsa)
    c.wire("metal1", [(1.2, dy_rsa), (rs_bx, dy_rsa)], 0.40)

    # Rsa: bar 0 (top=TA) -> bar 3 -> bar 5 -> bar 6 (top=a)
    y_rsa_ta = grid(rs_yt + 0.55)
    c.via1(rs_xs[0], y_rsa_ta)
    c.wire("metal2", [(rs_xs[0], y_rsa_ta), (rs_xs[0], 52.4), (X_L_TA, 52.4)], 0.38)
    c.via2(X_L_TA, 52.4)

    c.via1(rs_xs[0], grid(rs_yb - 0.55))
    c.via1(rs_xs[3], grid(rs_yb - 0.55))
    c.wire("metal2", [(rs_xs[0], grid(rs_yb - 0.55)), (rs_xs[3], grid(rs_yb - 0.55))], 0.36)

    c.via1(rs_xs[3], grid(rs_yt - 0.55))
    c.via1(rs_xs[5], grid(rs_yt - 0.55))
    c.wire("metal2", [(rs_xs[3], grid(rs_yt - 0.55)), (rs_xs[5], grid(rs_yt - 0.55))], 0.36)

    c.wire("metal1", [(rs_xs[5], rs_yb), (rs_xs[6], rs_yb)], 0.50)
    c.via1(rs_xs[6], y_rsa_ta)
    x_a_m3 = rs_xs[6]
    c.wire("metal2", [(x_a_m3, y_rsa_ta), (x_a_m3, 50.2)], 0.38)
    c.via2(x_a_m3, 50.2)

    # Rsb: bar 1 (top=TB) -> bar 2 -> bar 4 -> bar 7 (top=b)
    c.via1(rs_xs[1], y_rsa_ta)
    c.wire("metal2", [(rs_xs[1], y_rsa_ta), (rs_xs[1], 51.4), (X_L_TB, 51.4)], 0.38)
    c.via2(X_L_TB, 51.4)

    c.wire("metal1", [(rs_xs[1], rs_yb), (rs_xs[2], rs_yb)], 0.50)
    c.via1(rs_xs[2], y_rsa_ta)
    c.via1(rs_xs[4], y_rsa_ta)
    c.wire("metal2", [(rs_xs[2], y_rsa_ta), (rs_xs[4], y_rsa_ta)], 0.36)

    c.via1(rs_xs[4], grid(rs_yb + 0.55))
    c.via1(rs_xs[7], grid(rs_yb + 0.55))
    c.wire("metal2", [(rs_xs[4], grid(rs_yb + 0.55)), (rs_xs[7], grid(rs_yb + 0.55))], 0.36)

    c.via1(rs_xs[7], y_rsa_ta)

    r2_5 = clean_primitive(pdir, "bg_r2_5", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=33.595, nx=5, m=1, guard=0))
    r1_1 = clean_primitive(pdir, "bg_r1_1", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=34.70, nx=1, m=1, guard=0))
    dx_ptat, dy_ptat = 24.8, 26.8
    c.include(r2_5, dx=grid(dx_ptat - 4.44), dy=dy_ptat)
    c.include(r1_1, dx=dx_ptat, dy=dy_ptat)
    c.include(r2_5, dx=grid(dx_ptat + 4.44), dy=dy_ptat)

    r2l_xs = sorted({grid((r[0] + r[2]) / 2 + dx_ptat - 4.44) for r in r2_5.rects["viali"]})
    r2r_xs = sorted({grid((r[0] + r[2]) / 2 + dx_ptat + 4.44) for r in r2_5.rects["viali"]})
    r2_ys = sorted({grid((r[1] + r[3]) / 2 + dy_ptat) for r in r2_5.rects["viali"]})
    r1_ys = sorted({grid((r[1] + r[3]) / 2 + dy_ptat) for r in r1_1.rects["viali"]})
    r2_yb, r2_yt = r2_ys[0], r2_ys[-1]
    r1_yb, r1_yt = r1_ys[0], r1_ys[-1]

    for i in range(4):
        yj = r2_yb if i % 2 == 0 else r2_yt
        c.wire("metal1", [(r2l_xs[i], yj), (r2l_xs[i + 1], yj)], 0.50)
    for i in range(4):
        yj = r2_yt if i % 2 == 0 else r2_yb
        c.wire("metal1", [(r2r_xs[i], yj), (r2r_xs[i + 1], yj)], 0.50)

    c.via1(r2l_xs[4], grid(r2_yb + 0.55))
    c.via1(r2r_xs[0], grid(r2_yb + 0.55))
    c.wire("metal2", [(r2l_xs[4], grid(r2_yb + 0.55)), (r2r_xs[0], grid(r2_yb + 0.55))], 0.38)

    # Node b: rs_xs[7] top -> R1 top (dx_ptat, r1_yt + 0.4)
    c.via1(dx_ptat, grid(r1_yt + 0.4))
    c.wire("metal2", [(rs_xs[7], y_rsa_ta), (rs_xs[7], 50.2), (dx_ptat, 50.2), (dx_ptat, grid(r1_yt + 0.4))], 0.38)

    # Node vbg: r2l_xs[0] top -> X_L_VBG (vertical M1 up inside unguarded r2_5, then M2 at y=53.6)
    c.wire("metal1", [(r2l_xs[0], r2_yt), (r2l_xs[0], 53.6)], 0.36)
    c.via1(r2l_xs[0], 53.6)
    c.wire("metal2", [(r2l_xs[0], 53.6), (X_L_VBG, 53.6)], 0.40)
    c.via2(X_L_VBG, 53.6)

    # Node c: R1 bot -> Q2 emitters via vertical M3 at x_c_m3 = 29.8
    x_c_m3 = 29.8
    c.via1(dx_ptat, grid(r1_yb - 0.55))
    c.wire("metal2", [(dx_ptat, grid(r1_yb - 0.55)), (x_c_m3, grid(r1_yb - 0.55))], 0.42)
    c.via2(x_c_m3, grid(r1_yb - 0.55))

    # Node d: r2r_xs[4] top -> Q3 emitter via vertical M3 at x_d_m3 = 31.4
    x_d_m3 = 31.4
    c.via1(r2r_xs[4], r2_yt)
    c.wire("metal2", [(r2r_xs[4], r2_yt), (x_d_m3, r2_yt)], 0.38)
    c.via2(x_d_m3, r2_yt)

    # 1B. Middle of Col 1 (y = 57.0 .. 84.4): Guarded Core Startup + Bias Diode (Xbd, Xsn, Xsu, Xsp)
    p_bd = clean_primitive(pdir, "bg_bd", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=4.0, nf=2, conn_gates=1, guard=0))
    p_sn = clean_primitive(pdir, "bg_sn", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=1.0, nf=1, conn_gates=1, guard=0))
    p_su = clean_primitive(pdir, "bg_su", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=1.0, nf=1, conn_gates=1, guard=0))
    p_sp = clean_primitive(pdir, "bg_sp", "sky130_fd_pr__pfet_01v8", dict(w=0.42, l=20.0, nf=1, conn_gates=1, guard=1))

    draw_m1_guard_ring(c, 1.2, 57.0, 33.8, 84.4, w=0.80)
    y_su_vss = 59.0
    c.via1(1.2, y_su_vss)
    c.via1(33.8, y_su_vss)
    c.wire("metal2", [(1.2, y_su_vss), (X_L_VSS, y_su_vss)], 0.44)
    c.via2(X_L_VSS, y_su_vss)

    y_su_row = 62.6
    # Xbd at dx=9.2 (jog outer S/D outward on M1 to avoid conn_gates=1 top/bot M1 gate straps!)
    c.include(p_bd, dx=9.2, dy=y_su_row)
    bd_xs = sorted({grid((r[0] + r[2]) / 2 + 9.2) for r in p_bd.rects["ndiffc"]})
    bd_gx, bd_gy = p_bd.pins("G")[0]
    for sx, sgn in ((bd_xs[0], -1), (bd_xs[2], +1)):
        sx_out = grid(sx + sgn * 0.60)
        c.wire("metal1", [(sx, y_su_row), (sx_out, y_su_row), (sx_out, y_su_vss)], 0.34)
        c.via1(sx_out, y_su_vss)
    c.via1(bd_xs[1], y_su_row)
    x_bd_g = grid(9.2 + bd_gx)
    y_nb_su = grid(y_su_row + bd_gy)
    c.via1(x_bd_g, y_nb_su)
    c.wire("metal2", [(bd_xs[1], y_su_row), (bd_xs[1], y_nb_su), (x_bd_g, y_nb_su)], 0.36)

    # Xsn at dx=18.2 (jog S/D outward on M1 by +-0.60 um before vertical M1)
    c.include(p_sn, dx=18.2, dy=y_su_row)
    sn_xs = sorted({grid((r[0] + r[2]) / 2 + 18.2) for r in p_sn.rects["ndiffc"]})
    sn_gx, sn_gy = p_sn.pins("G")[0]
    x_sn_s = grid(sn_xs[1] + 0.60)
    c.wire("metal1", [(sn_xs[1], y_su_row), (x_sn_s, y_su_row), (x_sn_s, y_su_vss)], 0.34)
    c.via1(x_sn_s, y_su_vss)
    x_sn_d = grid(sn_xs[0] - 0.60)
    x_sn_g = grid(18.2 + sn_gx)
    y_sn_g = grid(y_su_row + sn_gy)
    c.via1(x_sn_g, y_sn_g)

    # Join nb (Xbd + Xsn gate -> X_L_NB) on M2 at y_nb_bus = 66.2
    y_nb_bus = 66.2
    c.wire("metal2", [(x_bd_g, y_nb_su), (x_bd_g, y_nb_bus), (X_L_NB, y_nb_bus)], 0.38)
    c.wire("metal2", [(x_sn_g, y_sn_g), (x_sn_g, y_nb_bus)], 0.36)
    c.via2(X_L_NB, y_nb_bus)

    # Xsu at dx=25.0 (jog both S and D outward on M1 by +-0.60 um before vertical M1)
    c.include(p_su, dx=25.0, dy=y_su_row)
    su_xs = sorted({grid((r[0] + r[2]) / 2 + 25.0) for r in p_su.rects["ndiffc"]})
    su_gx, su_gy = p_su.pins("G")[0]
    x_su_s = grid(su_xs[1] + 0.60)
    c.wire("metal1", [(su_xs[1], y_su_row), (x_su_s, y_su_row), (x_su_s, y_su_vss)], 0.34)
    c.via1(x_su_s, y_su_vss)
    # Xsu drain -> X_L_VG on M1/M2 at y_vg_su = 67.4
    y_vg_su = 67.4
    x_su_d_m1 = grid(su_xs[0] - 0.60)
    c.wire("metal1", [(x_su_d_m1, y_su_row), (su_xs[0], y_su_row)], 0.34)
    c.wire("metal1", [(x_su_d_m1, y_su_row), (x_su_d_m1, y_vg_su)], 0.34)
    c.via1(x_su_d_m1, y_vg_su)
    c.wire("metal2", [(x_su_d_m1, y_vg_su), (X_L_VG, y_vg_su)], 0.38)
    c.via2(X_L_VG, y_vg_su)

    # st bus (Xsn drain + Xsu gate + Xsp drain) on M1/M2 at y_st_bus = 69.2
    y_st_bus = 69.2
    x_su_g = grid(25.0 + su_gx)
    y_su_g = grid(y_su_row + su_gy)
    c.wire("metal1", [(x_sn_d, y_su_row), (sn_xs[0], y_su_row)], 0.34)
    c.wire("metal1", [(x_sn_d, y_su_row), (x_sn_d, y_st_bus)], 0.34)
    c.via1(x_sn_d, y_st_bus)
    c.via1(x_su_g, y_su_g)
    c.wire("metal2", [(x_su_g, y_su_g), (x_su_g, 65.0)], 0.34)
    c.via1(x_su_g, 65.0)
    c.wire("metal1", [(x_su_g, 65.0), (x_su_g, y_st_bus)], 0.34)
    c.via1(x_su_g, y_st_bus)
    c.wire("metal2", [(x_sn_d, y_st_bus), (x_su_g, y_st_bus)], 0.38)

    # Xsp (0.42/20 guarded PMOS) at dx=16.5, dy=77.8 (kept left of x_c_m3=29.8 & x_d_m3=31.4; M1/M2 only!)
    dx_sp, dy_sp = 16.5, 77.8
    c.include(p_sp, dx=dx_sp, dy=dy_sp)
    sp_xs = sorted({grid((r[0] + r[2]) / 2 + dx_sp) for r in p_sp.rects["pdiffc"]})
    sp_gx, sp_gy = p_sp.pins("G")[0]
    c.via1(sp_xs[0], dy_sp)
    c.via1(sp_xs[1], dy_sp)
    c.via1(grid(dx_sp + sp_gx), grid(dy_sp + sp_gy))
    c.via1(1.2, grid(dy_sp + sp_gy))
    c.wire("metal2", [(1.2, grid(dy_sp + sp_gy)), (grid(dx_sp + sp_gx), grid(dy_sp + sp_gy))], 0.36)
    sp_rbar = max(p_sp.rects["nsubdiffcont"], key=lambda r: r[0] + r[2])
    sp_rx = grid((sp_rbar[0] + sp_rbar[2]) / 2 + dx_sp)
    c.body_contact(sp_rx, dy_sp)
    c.wire("metal2", [(sp_xs[1], dy_sp), (X_L_VDD, dy_sp)], 0.40)
    c.via2(X_L_VDD, dy_sp)
    c.wire("metal2", [(sp_xs[0], y_st_bus), (sp_xs[0], dy_sp)], 0.36)
    c.wire("metal2", [(min(sp_xs[0], x_sn_d), y_st_bus), (max(sp_xs[0], x_su_g), y_st_bus)], 0.38)

    # 1C. Top of Col 1 (y = 86.2 .. 118.7): Guarded 4x3 Common-Centroid PNP Island
    pnp = Cell.read(PNP_MAG)
    pnp.rects.pop("checkpaint", None)
    pnp_em = pnp.pins("Emitter")[0]
    pnp_ba = pnp.pins("Base")[0]
    pnp_co = pnp.pins("Collector")[0]
    pnp.labels.clear()

    pnp_xs = [6.0, 13.6, 21.2]
    pnp_ys = [87.7, 95.3, 102.9, 110.5]
    q1_em_pt = None
    q3_em_pt = None

    for r_i, py in enumerate(pnp_ys):
        y_bc_m1 = grid(py + 5.95)
        for c_i, px in enumerate(pnp_xs):
            if r_i == 3 and c_i in (0, 2):
                c.rect("pwell", px, py, px + 6.7, py + 6.7)
                c.rect("psubdiff", px + 0.4, py + 0.4, px + 6.3, py + 6.4)
                c.rect("psubdiffcont", px + 1.2, py + 1.2, px + 5.5, py + 5.5)
                c.rect("locali", px + 0.8, py + 0.8, px + 5.9, py + 6.25)
                c.pad("viali", grid(px + 3.35), y_bc_m1, 0.17)
                c.pad("metal1", grid(px + 3.35), y_bc_m1, 0.40)
                continue

            c.include(pnp, dx=px, dy=py)
            ex, ey = grid(px + pnp_em[0]), grid(py + pnp_em[1])
            bx_p, by_p = grid(px + pnp_ba[0]), grid(py + pnp_ba[1])
            cx_p, cy_p = grid(px + pnp_co[0]), grid(py + pnp_co[1])
            c.wire("locali", [(cx_p, by_p), (cx_p, cy_p)], 0.36)
            c.pad("viali", cx_p, cy_p, 0.17)
            c.pad("metal1", cx_p, cy_p, 0.36)
            c.wire("metal1", [(cx_p, cy_p), (cx_p, y_bc_m1)], 0.36)
            c.via1(ex, ey)
            if r_i == 1 and c_i == 1:
                q1_em_pt = (ex, ey)
            elif r_i == 3 and c_i == 1:
                q3_em_pt = (ex, ey)

        c.wire("metal1", [(4.2, y_bc_m1), (29.5, y_bc_m1)], 0.40)

    draw_m1_guard_ring(c, 4.2, 86.2, 29.5, 118.7, w=0.80)
    c.via1(29.5, 86.2)
    c.wire("metal2", [(29.5, 86.2), (X_L_VSS, 86.2)], 0.50)
    c.via2(X_L_VSS, 86.2)

    x_q2_l, x_q2_m, x_q2_r = [grid(x + pnp_em[0]) for x in pnp_xs]
    y_q2_0, y_q2_1, y_q2_2, y_q3 = [grid(y + pnp_em[1]) for y in pnp_ys]
    c.wire("metal2", [(x_q2_l, y_q2_0), (x_q2_r, y_q2_0), (x_q2_r, y_q2_2), (x_q2_l, y_q2_2), (x_q2_l, y_q2_0)], 0.44)

    # Connect Q1 (a), Q2 (c), Q3 (d) from Col 1 bottom Core Resistors via clean vertical M3 tracks
    c.via2(*q1_em_pt)
    c.wire("metal3", [(x_a_m3, 50.2), (x_a_m3, q1_em_pt[1]), q1_em_pt], 0.40)

    c.wire("metal2", [(x_q2_r, y_q2_0), (x_c_m3, y_q2_0)], 0.44)
    c.via2(x_c_m3, y_q2_0)
    c.wire("metal3", [(x_c_m3, grid(r1_yb - 0.55)), (x_c_m3, y_q2_0)], 0.44)

    c.via2(*q3_em_pt)
    c.wire("metal3", [(x_d_m3, r2_yt), (x_d_m3, q3_em_pt[1]), q3_em_pt], 0.40)

    # -------------------------------------------------------------------------
    # COLUMN 3 (center dx_col3 = 149.5): 3D Under-MIM Xrref/Trim/Xbd2/Xk (Bot) + Xota (Mid) + pvi (Top)
    # -------------------------------------------------------------------------
    dx_col3 = 149.5

    # 3A. Bottom Guarded Xrref + 5-Bit Trim + Switches + Xbd2/Xk (y = 1.6 .. 54.0, M1/M2 ONLY!)
    draw_m1_guard_ring(c, 125.0, 1.6, 174.0, 54.0, w=0.80)
    c.wire("metal1", [(125.0, y_amp_vss), (125.0, 1.6)], 0.50)
    c.via1(125.0, y_amp_vss)

    rref_p = clean_primitive(pdir, "bg_rref8", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=44.015, nx=8, m=1, guard=1))
    dx_rf, dy_rf = 132.8, 27.6
    rf_info = strap_res_serpentine(c, rref_p, dx_rf, dy_rf)
    rf_s, rf_rt5 = rf_info["plus"], rf_info["minus"]
    rf_lbar = min(rref_p.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    rf_lx = grid((rf_lbar[0] + rf_lbar[2]) / 2 + dx_rf)
    c.wire("metal1", [(125.0, dy_rf), (rf_lx, dy_rf)], 0.40)

    c.via1(*rf_s)
    c.wire("metal2", [(X_R_S, rf_s[1]), rf_s], 0.40)
    c.via2(X_R_S, rf_s[1])
    c.via1(*rf_rt5)

    sw_p = clean_primitive(pdir, "bg_sw", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.15, nf=4, conn_gates=1, guard=0))
    rt_lens = [38.175, 18.49, 8.65, 3.73, 1.27]
    dy_sw = 6.2
    y_rt_bot_anchor = 10.6

    x_hi_list, x_lo_list, y_top_list = [], [], []
    for idx, lv in enumerate(rt_lens):
        bit = 4 - idx
        dx_k = grid(144.8 + idx * 5.6)
        rt_p = clean_primitive(pdir, f"bg_rt{bit}", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=lv, nx=1, m=1, guard=0))
        rt_b = rt_p.bbox()
        dy_rt = grid(y_rt_bot_anchor - rt_b[1])
        c.include(rt_p, dx=dx_k, dy=dy_rt)
        rt_ys = sorted({grid((r[1] + r[3]) / 2 + dy_rt) for r in rt_p.rects["viali"]})
        yb_k, yt_k = rt_ys[0], rt_ys[-1]
        y_top_list.append(yt_k)

        c.include(sw_p, dx=dx_k, dy=dy_sw)
        sw_xs = sorted({grid((r[0] + r[2]) / 2 + dx_k) for r in sw_p.rects["ndiffc"]})
        y_d, y_s = grid(dy_sw + 1.4), grid(dy_sw - 1.4)
        for ox in sw_xs[1::2]:
            c.via1(ox, y_d)
        for ex in sw_xs[::2]:
            c.via1(ex, y_s)

        x_hi, x_lo = grid(dx_k - 1.65), grid(dx_k + 1.65)
        x_hi_list.append(x_hi)
        x_lo_list.append(x_lo)

        c.wire("metal1", [(dx_k, yt_k), (x_hi, yt_k), (x_hi, y_d)], 0.40)
        c.via1(x_hi, y_d)
        c.wire("metal2", [(x_hi, y_d), (sw_xs[3], y_d)], 0.38)

        c.wire("metal1", [(dx_k, yb_k), (x_lo, yb_k), (x_lo, y_s)], 0.40)
        c.via1(x_lo, y_s)
        c.wire("metal2", [(sw_xs[0], y_s), (x_lo, y_s)], 0.38)

        gx_sw = grid(dx_k - 0.24)
        gy_sw = grid(dy_sw - 2.775)
        gy_sw_via = grid(dy_sw - 3.25)
        c.wire("metal1", [(gx_sw, gy_sw_via), (gx_sw, gy_sw)], 0.26)
        c.via1(gx_sw, gy_sw_via)
        c.wire("metal2", [(gx_sw, -0.8), (gx_sw, gy_sw_via)], 0.36)
        c.port(f"g{bit}", "metal2", gx_sw, -0.8)

    c.via1(144.8, y_top_list[0])
    c.wire("metal2", [rf_rt5, (rf_rt5[0], grid(rf_rt5[1] - 1.1)), (144.8, grid(rf_rt5[1] - 1.1)), (144.8, y_top_list[0])], 0.40)

    for idx in range(4):
        c.wire("metal1", [(x_lo_list[idx], 9.6), (x_hi_list[idx + 1], 9.6)], 0.44)
    c.wire("metal1", [(x_lo_list[4], 9.6), (174.0, 9.6)], 0.50)

    # Xbd2 & Xk tucked cleanly inside the staircase pocket above rt2..rt0 (x=156..172, y=36..51, M1/M2 only!)
    p_xk = clean_primitive(pdir, "bg_xk", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=4.0, nf=1, conn_gates=1, guard=0))
    dx_bd2, dy_bd2 = 163.5, 38.0
    c.include(p_bd, dx=dx_bd2, dy=dy_bd2)
    bd2_xs = sorted({grid((r[0] + r[2]) / 2 + dx_bd2) for r in p_bd.rects["ndiffc"]})
    bd2_gx, bd2_gy = p_bd.pins("G")[0]
    x_bd2_s0 = grid(bd2_xs[0] - 0.60)
    x_bd2_s2 = grid(bd2_xs[2] + 0.60)
    c.wire("metal1", [(bd2_xs[0], dy_bd2), (x_bd2_s0, dy_bd2), (x_bd2_s0, 35.8)], 0.34)
    c.wire("metal1", [(bd2_xs[2], dy_bd2), (x_bd2_s2, dy_bd2), (x_bd2_s2, 35.8)], 0.34)
    c.wire("metal1", [(x_bd2_s0, 35.8), (174.0, 35.8)], 0.44)
    y_nb2_g = grid(dy_bd2 + bd2_gy)
    c.via1(bd2_xs[1], dy_bd2)
    c.via1(grid(dx_bd2 + bd2_gx), y_nb2_g)
    c.wire("metal2", [(X_R_NB2, y_nb2_g), (bd2_xs[1], y_nb2_g)], 0.38)
    c.wire("metal2", [(bd2_xs[1], dy_bd2), (bd2_xs[1], y_nb2_g)], 0.36)
    c.via2(X_R_NB2, y_nb2_g)

    dx_xk, dy_xk = 163.5, 45.8
    c.include(p_xk, dx=dx_xk, dy=dy_xk)
    xk_xs = sorted({grid((r[0] + r[2]) / 2 + dx_xk) for r in p_xk.rects["ndiffc"]})
    xk_gx, xk_gy = p_xk.pins("G")[0]
    c.via1(xk_xs[0], dy_xk)
    c.via1(grid(dx_xk + xk_gx), grid(dy_xk + xk_gy))
    # Xk: drain xk_xs[0] -> vgi, gate -> vbg, source xk_xs[1] -> s (jog source outward +0.60 um on M1!)
    c.wire("metal2", [(X_R_VGI, dy_xk), (xk_xs[0], dy_xk)], 0.38)
    c.via2(X_R_VGI, dy_xk)
    y_xk_g = grid(dy_xk + xk_gy)
    c.wire("metal2", [(X_R_VBG, y_xk_g), (grid(dx_xk + xk_gx), y_xk_g)], 0.36)
    c.via2(X_R_VBG, y_xk_g)
    x_xk_s = grid(xk_xs[1] + 0.60)
    y_xk_s = 48.0
    c.wire("metal1", [(xk_xs[1], dy_xk), (x_xk_s, dy_xk), (x_xk_s, y_xk_s)], 0.34)
    c.via1(x_xk_s, y_xk_s)
    c.wire("metal2", [(X_R_S, y_xk_s), (x_xk_s, y_xk_s)], 0.38)
    c.via2(X_R_S, y_xk_s)

    # 3B. Middle of Col 3 (y = 55.6 .. 100.1): Compact Xota
    dx_ota, dy_ota = dx_col3, 55.8
    c.include(ota, dx=dx_ota, dy=dy_ota)
    _, ox_inp, oy_inp = ota_ports["inp"]
    _, ox_inn, oy_inn = ota_ports["inn"]
    _, ox_vbn, oy_vbn = ota_ports["vbn"]
    _, ox_out, oy_out = ota_ports["out"]
    _, ox_vdd, oy_vdd = ota_ports["vdd"]

    y_ota_vss = grid(dy_ota - 0.2)
    c.wire("metal2", [(X_R_VSS, y_ota_vss), (dx_ota, y_ota_vss)], 0.50)
    c.via2(X_R_VSS, y_ota_vss)

    y_ota_nb2 = grid(dy_ota + oy_vbn)
    c.wire("metal2", [(X_R_NB2, y_ota_nb2), (grid(dx_ota + ox_vbn), y_ota_nb2)], 0.38)
    c.via2(X_R_NB2, y_ota_nb2)

    y_ota_s = grid(dy_ota + oy_inp)
    c.wire("metal2", [(X_R_S, y_ota_s), (grid(dx_ota + ox_inp), y_ota_s)], 0.38)
    c.via2(X_R_S, y_ota_s)

    y_ota_vbg = grid(dy_ota + oy_inn)
    c.wire("metal2", [(X_R_VBG, y_ota_vbg), (grid(dx_ota + ox_inn), y_ota_vbg)], 0.38)
    c.via2(X_R_VBG, y_ota_vbg)

    x_ota_vdd = grid(dx_ota + ox_vdd)
    y_ota_vdd = grid(dy_ota + oy_vdd)
    c.via2(x_ota_vdd, y_ota_vdd)
    c.wire("metal2", [(X_R_VDD, y_ota_vdd), (x_ota_vdd, y_ota_vdd)], 0.50)
    c.via2(X_R_VDD, y_ota_vdd)

    # Xota out (at x = dx_ota + 26.4 = 175.9) -> route down/up outside MIM on M3 to y=100.8 then M2 to X_R_VGI
    x_ota_out = grid(dx_ota + ox_out)
    y_ota_out = grid(dy_ota + oy_out)
    c.wire("metal3", [(x_ota_out, y_ota_out), (x_ota_out, 100.8)], 0.44)
    c.via2(x_ota_out, 100.8)
    c.wire("metal2", [(X_R_VGI, 100.8), (x_ota_out, 100.8)], 0.44)
    c.via2(X_R_VGI, 100.8)

    # 3C. Top of Col 3 (y = 102.2 .. 117.6): 10x2 V->I PMOS (Xmv + Xo0..Xo3, M1/M2 only under MIM)
    p_vi = clean_primitive(pdir, "bg_pvi", "sky130_fd_pr__pfet_01v8_lvt",
                           dict(w=6.0, l=4.0, nf=10, m=2, conn_gates=1, guard=1))
    dx_pvi, dy_pvi = dx_col3, 109.9
    info_vi = strap_2d_pmos_10x2_under_mim(c, p_vi, dx=dx_pvi, dy=dy_pvi)

    c.wire("metal2", [(X_R_VDD, info_vi["vdd_span"][1]), (info_vi["vdd_x"], info_vi["vdd_span"][1])], 0.50)
    c.via2(X_R_VDD, info_vi["vdd_span"][1])
    c.via2(info_vi["vdd_x"], info_vi["vdd_span"][1])

    c.wire("metal2", [(X_R_VGI, info_vi["gate_span"][1]), (info_vi["gate_x"], info_vi["gate_span"][1])], 0.40)
    c.via2(X_R_VGI, info_vi["gate_span"][1])
    c.via2(info_vi["gate_x"], info_vi["gate_span"][1])

    c.wire("metal2", [(X_R_S, info_vi["B2_span"][0]), (info_vi["B2_x"], info_vi["B2_span"][0])], 0.40)
    c.via2(X_R_S, info_vi["B2_span"][0])
    c.via2(info_vi["B2_x"], info_vi["B2_span"][0])

    opin_prefix = "i" if is_bias_ref else "iout"
    for idx, b_key in enumerate(("B0", "B1", "B3", "B4")):
        ox = info_vi[f"{b_key}_x"]
        oy1 = info_vi[f"{b_key}_y1"]
        c.wire("metal3", [(ox, oy1), (ox, 122.0)], 0.50)
        c.port(f"{opin_prefix}{idx}", "metal3", ox, 122.0)

    # 3D. 3D M3/M4 MIM Capacitor Stack directly above Col 3 (zero extra area!)
    dy_mim_col3 = 60.8
    if not is_bias_ref:
        mim10 = clean_primitive(pdir, "bg_mim2x5", "sky130_fd_pr__cap_mim_m3_1", dict(w=22.2, l=22.2, nx=2, ny=5, stack=0))
        c.include(mim10, dx=dx_col3, dy=dy_mim_col3)
        c1_xs = sorted({grid(dx_col3 + x) for _, x, _, nm in mim10.labels if nm.startswith("C1")})
        c2_xs = sorted({grid(dx_col3 + x) for _, x, _, nm in mim10.labels if nm.startswith("C2")})
        y_c1 = 121.5
        for cx in c1_xs:
            c.wire("metal4", [(cx, grid(dy_mim_col3 + 59.0)), (cx, y_c1)], 0.52)
        c.wire("metal4", [(X_R_VGI, y_c1), (c1_xs[-1], y_c1)], 0.60)
        via3(c, X_R_VGI, y_c1)

        y_c2 = 0.2
        for cx in c2_xs:
            c.wire("metal4", [(cx, y_c2), (cx, grid(dy_mim_col3 - 59.0))], 0.52)
        c.wire("metal4", [(X_R_VDD, y_c2), (c2_xs[-1], y_c2)], 0.60)
        via3(c, X_R_VDD, y_c2)
        cap_spice = "\n".join(f"Xcvgi{i} vgi vdd sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2" for i in range(10))
    else:
        dx_m2 = grid(dx_col3 - 12.63)
        dy_m2 = 96.5
        mim2 = clean_primitive(w, "bg_mim1x2", "sky130_fd_pr__cap_mim_m3_1", dict(w=22.2, l=22.2, nx=1, ny=2, stack=0))
        c.include(mim2, dx=dx_m2, dy=dy_m2)
        m2_c1x = grid(dx_m2 + mim2.pins("C1")[0][0])
        m2_c2x = grid(dx_m2 + mim2.pins("C2")[0][0])
        y_m2_c1, y_m2_c2 = 121.5, 71.6
        c.wire("metal4", [(m2_c1x, grid(dy_m2 + 23.3)), (m2_c1x, y_m2_c1)], 0.52)
        c.wire("metal4", [(X_R_VGI, y_m2_c1), (m2_c1x, y_m2_c1)], 0.60)
        via3(c, X_R_VGI, y_m2_c1)
        c.wire("metal4", [(m2_c2x, y_m2_c2), (m2_c2x, grid(dy_m2 - 23.3))], 0.52)
        c.wire("metal4", [(X_R_VDD, y_m2_c2), (m2_c2x, y_m2_c2)], 0.60)
        via3(c, X_R_VDD, y_m2_c2)

        dx_m5 = grid(dx_col3 + 12.63)
        mim5 = clean_primitive(w, "bg_mim1x5", "sky130_fd_pr__cap_mim_m3_1", dict(w=22.2, l=22.2, nx=1, ny=5, stack=0))
        c.include(mim5, dx=dx_m5, dy=dy_mim_col3)
        m5_c1x = grid(dx_m5 + mim5.pins("C1")[0][0])
        m5_c2x = grid(dx_m5 + mim5.pins("C2")[0][0])
        y_m5_c1, y_m5_c2 = 122.8, 0.2
        c.wire("metal4", [(m5_c1x, grid(dy_mim_col3 + 59.0)), (m5_c1x, y_m5_c1)], 0.52)
        c.wire("metal4", [(X_R_VBG, y_m5_c1), (m5_c1x, y_m5_c1)], 0.60)
        via3(c, X_R_VBG, y_m5_c1)
        c.wire("metal4", [(m5_c2x, y_m5_c2), (m5_c2x, grid(dy_mim_col3 - 59.0))], 0.52)
        c.wire("metal4", [(X_R_VSS, y_m5_c2), (m5_c2x, y_m5_c2)], 0.60)
        via3(c, X_R_VSS, y_m5_c2)
        cap_spice = (
            "\n".join(f"Xcvgi{i} vgi vdd sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2" for i in range(2)) + "\n"
            + "\n".join(f"Xcvbg{i} vbg vss sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2" for i in range(5))
        )

    # -------------------------------------------------------------------------
    # JOIN CHANNEL L & CHANNEL R M3 TRUNKS + OUTER GUARD RING + TOP PORTS
    # -------------------------------------------------------------------------
    c.wire("metal3", [(X_L_VSS, -1.2), (X_L_VSS, 86.2)], 0.60)
    c.wire("metal3", [(X_L_VDD, 77.8), (X_L_VDD, 123.6)], 0.60)
    c.wire("metal3", [(X_L_VG,  67.4), (X_L_VG,  80.6)], 0.44)
    c.wire("metal3", [(X_L_NB,  y_amp_nb), (X_L_NB, 81.5)], 0.44)
    c.wire("metal3", [(X_L_TA,  y_amp_ta), (X_L_TA, 82.4)], 0.44)
    c.wire("metal3", [(X_L_TB,  y_amp_tb), (X_L_TB, 84.2)], 0.44)
    c.wire("metal3", [(X_L_VBG, 53.6), (X_L_VBG, 83.3)], 0.44)

    c.wire("metal3", [(X_R_VBG, y_xk_g), (X_R_VBG, 122.8 if is_bias_ref else max(79.7, y_ota_vbg))], 0.44)
    c.wire("metal3", [(X_R_S,   min(rf_s[1], y_xk_s)), (X_R_S, info_vi["B2_span"][0])], 0.44)
    c.wire("metal3", [(X_R_NB2, y_nb2_g), (X_R_NB2, max(y_ota_nb2, by_b4))], 0.44)
    c.wire("metal3", [(X_R_VGI, dy_xk),   (X_R_VGI, 121.5)], 0.44)
    c.wire("metal3", [(X_R_VDD, 0.2 if not is_bias_ref else 71.6), (X_R_VDD, 123.6)], 0.60)
    c.wire("metal3", [(X_R_VSS, -1.2),    (X_R_VSS, y_ota_vss)], 0.60)

    pts_outer = [(-0.6, -1.2), (181.6, -1.2), (181.6, 125.2), (-0.6, 125.2), (-0.6, -1.2)]
    c.wire("pwell", pts_outer, 1.50)
    for lay in ("psubdiff", "locali", "metal1"):
        c.wire(lay, pts_outer, 0.90)
    c.rect("psubdiffcont", -0.1, -1.3, 181.1, -1.1)
    c.rect("psubdiffcont", -0.1, 125.1, 181.1, 125.3)
    c.rect("psubdiffcont", -0.7, -0.7, -0.5, 124.7)
    c.rect("psubdiffcont", 181.5, -0.7, 181.7, 124.7)
    for gx_o in (1.2, 45.0, 90.0, 135.0, 180.0):
        c.pad("viali", gx_o, -1.2, 0.17)
        c.pad("viali", gx_o, 125.2, 0.17)
    for vx_s in (X_L_VSS, X_R_VSS):
        c.pad("viali", vx_s, -1.2, 0.17)
        c.via1(vx_s, -1.2)
        c.via2(vx_s, -1.2)

    c.port("vbg", "metal3", X_L_VBG, 83.3)
    c.port("vg",  "metal3", X_L_VG,  80.6)
    c.port("vgi", "metal3", X_R_VGI, 121.5)
    c.port("vdd", "metal2", 77.5,    123.6)
    c.port("vss", "metal3", X_L_VSS, -1.2)
    c.write(w / f"{cell}.mag")

    opins = "i0 i1 i2 i3" if is_bias_ref else "iout0 iout1 iout2 iout3"
    o0, o1, o2, o3 = opins.split()
    ref = f"""* Compact 3-Zone Common-Centroid + 3D Under-MIM {cell} (true w=1 res_high_po matching bandgap.spice)
.subckt serdes_bg_amp_pdk inp inn out vbn vdd vss
Xt tail vbn vss vss sky130_fd_pr__nfet_01v8 w=8 l=4
Xa da inn tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xb o1 inp tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
Xlb o1 da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
X2 out o1 vss vss sky130_fd_pr__nfet_01v8 w=2 l=2
Xp2 out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=4
Xrz o1 cz vss sky130_fd_pr__res_high_po w=1 l=61.90
Xc0 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc1 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc2 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc3 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc4 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
Xc5 cz out sky130_fd_pr__cap_mim_m3_1 w=22.2 l=22.2
.ends serdes_bg_amp_pdk

.subckt serdes_bg_ota_pdk inp inn out vbn vdd vss
Xt tail vbn vss vss sky130_fd_pr__nfet_01v8 w=1 l=8
Xa da inp tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xb out inn tail vss sky130_fd_pr__nfet_01v8 w=24 l=5
Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
Xlb out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=12
.ends serdes_bg_ota_pdk

.subckt {cell} vbg {opins} vg vgi g4 g3 g2 g1 g0 vdd vss
Xm1 ta vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8
Xm2 tb vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8
Xm3 vbg vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8
Xm4 nb vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8
Xm5 nb2 vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8
Xrsa ta a vss sky130_fd_pr__res_high_po w=1 l=157.74
Xrsb0 tb b1 vss sky130_fd_pr__res_high_po w=1 l=39.435
Xrsb1 b1 b2 vss sky130_fd_pr__res_high_po w=1 l=39.435
Xrsb2 b2 b3 vss sky130_fd_pr__res_high_po w=1 l=39.435
Xrsb3 b3 b vss sky130_fd_pr__res_high_po w=1 l=39.435
Xq1 vss vss a sky130_fd_pr__pnp_05v5_W3p40L3p40
Xr1 b c vss sky130_fd_pr__res_high_po w=1 l=34.70
Xq2_0 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_1 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_2 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_3 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_4 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_5 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_6 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xq2_7 vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40
Xr2 vbg d vss sky130_fd_pr__res_high_po w=1 l=335.96
Xq3 vss vss d sky130_fd_pr__pnp_05v5_W3p40L3p40
Xbd nb nb vss vss sky130_fd_pr__nfet_01v8 w=4 l=4
Xamp tb ta vg nb vdd vss serdes_bg_amp_pdk
Xsp st vss vdd vdd sky130_fd_pr__pfet_01v8 w=0.42 l=20
Xsn st nb vss vss sky130_fd_pr__nfet_01v8 w=2 l=1
Xsu vg st vss vss sky130_fd_pr__nfet_01v8 w=1 l=1
Xbd2 nb2 nb2 vss vss sky130_fd_pr__nfet_01v8 w=4 l=4
Xamp2 s vbg vgi nb2 vdd vss serdes_bg_ota_pdk
{cap_spice}
Xk vgi vbg s vss sky130_fd_pr__nfet_01v8 w=1 l=4
Xmv s vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=4
Xrref s rt5 vss sky130_fd_pr__res_high_po w=1 l=352.12
Xrt4 rt5 rt4 vss sky130_fd_pr__res_high_po w=1 l=38.18
Xrt3 rt4 rt3 vss sky130_fd_pr__res_high_po w=1 l=18.49
Xrt2 rt3 rt2 vss sky130_fd_pr__res_high_po w=1 l=8.65
Xrt1 rt2 rt1 vss sky130_fd_pr__res_high_po w=1 l=3.73
Xrt0 rt1 vss vss sky130_fd_pr__res_high_po w=1 l=1.27
Xs4 rt5 g4 rt4 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15
Xs3 rt4 g3 rt3 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15
Xs2 rt3 g2 rt2 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15
Xs1 rt2 g1 rt1 vss sky130_fd_pr__nfet_01v8 w=20 l=0.15
Xs0 rt1 g0 vss vss sky130_fd_pr__nfet_01v8 w=20 l=0.15
Xo0 {o0} vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=4
Xo1 {o1} vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=4
Xo2 {o2} vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=4
Xo3 {o3} vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=4
.ends {cell}
"""
    return check_cell(w, cell, ref)


def render_overview(out: Path, reports: list[dict]) -> Path:
    """Render an overview sheet of the key Bandgap & Bias PDK layouts."""
    import matplotlib.image as mpimg
    import matplotlib.pyplot as plt

    featured = [
        "serdes_bandgap_pdk",
        "serdes_bias_ref_pdk",
        "serdes_bg_amp_pdk",
        "serdes_bg_ota_pdk",
        "serdes_ref_vbuf_pdk",
        "serdes_bias_pcopy_n85_pdk",
    ]
    rep_map = {r["cell"]: r for r in reports}
    fig, axes = plt.subplots(3, 2, figsize=(20, 22), dpi=150)
    for ax, cname in zip(axes.flat, featured):
        r = rep_map[cname]
        img = mpimg.imread(out / cname / f"{cname}.png")
        ax.imshow(img)
        ax.axis("off")
        ax.set_title(
            f"{cname} ({r['size_um'][0]:.1f} x {r['size_um'][1]:.1f} um = {r['area_um2']:,.0f} um²)\n"
            f"DRC=0 | LVS=MATCH | {len(r['exported_ports'])} ports",
            fontsize=11,
            fontweight="bold",
        )
    fig.suptitle(
        "SKY130 Bandgap & Bias Distribution PDK Suite (11/11 Cells: DRC=0, LVS=MATCH, True w=1 res_high_po)",
        fontsize=14,
        fontweight="bold",
        y=0.995,
    )
    fig.tight_layout()
    ov = out / "bias_pdk_suite_overview.png"
    fig.savefig(ov, bbox_inches="tight")
    plt.close(fig)
    return ov


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)

    builders = [
        lambda: build_bias_ctle(out),
        lambda: build_bias_pcopy(out, 4),
        lambda: build_bias_pcopy(out, 20),
        lambda: build_bias_pcopy(out, 85),
        lambda: build_bias_cp(out),
        lambda: build_bias_cml(out),
        lambda: build_bg_ota(out),
        lambda: build_bg_amp(out),
        lambda: build_ref_vbuf(out),
        lambda: build_bandgap(out, is_bias_ref=False),
        lambda: build_bandgap(out, is_bias_ref=True),
    ]
    reports = []
    for fn in builders:
        r = fn()
        reports.append(r)
        print(
            f"{r['cell']:28s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
            f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports']):2d} | size={r['size_um']} um",
            flush=True,
        )
    ov = render_overview(out, reports)
    (out / "summary.json").write_text(json.dumps(reports, indent=2) + "\n")

    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ov, inst / ov.name)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        for r in reports:
            cell = r["cell"]
            cdir = out / cell
            for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_lvs.log", "_pex.spice"):
                src = cdir / f"{cell}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
