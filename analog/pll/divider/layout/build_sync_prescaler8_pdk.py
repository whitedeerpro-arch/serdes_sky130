#!/usr/bin/env python3
"""PDK Layout Generator (Building Blocks + Power-Mesh Architecture) for pll_sync_prescaler8_2stack.

Addresses all physical root causes diagnosed in the legacy pll_cml_prescaler8 layout:
  1. Double-ended poly gate contacts (`trim_top_gate=False`): both top and bottom gate rails
     strapped on M1/M2 across compact 3-6 um fingers (cutting gate poly R by >10x).
  2. Thick M4 horizontal VDD/VSS rails + vertical M5 mesh straps (eliminating M1 IR droop/bounce).
  3. Matched dual-column placement with flanking poly dummies & dummy poly resistors.
  4. Calibrated fixed-width resistors (res_high_po_2p85 for <=2k, res_high_po_1p41 for >=4k).

Usage:
    uv run python analog/pll/divider/layout/build_sync_prescaler8_pdk.py --out results/layout/sync2_divider/run1
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
sys.path.insert(0, str(REPO / "analog/pll/divider/layout"))
from build_prescaler8_pdk import build_res_dummy, grid, prepare_mos_prim, run_signoff, strap_mos_split, via3  # noqa: E402
from geometry import Cell, pdk_device  # noqa: E402


def signoff_with_plot(w: Path, cell: str, ref_text: str) -> dict:
    """Render PNG even if DRC/LVS fails, then run standard DRC/LVS signoff."""
    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    return run_signoff(w, cell, ref_text)


def via4(c: Cell, x: float, y: float) -> None:
    c.pad("metal4", x, y, 1.60)
    c.pad("via4", x, y, 1.18)
    c.pad("metal5", x, y, 1.60)


def strap_double_gates(c: Cell, prim: Cell, dx: float, dy: float, mirror_x: bool = False) -> tuple[float, float, float, float]:
    """Connect BOTH top and bottom gate bars of a trim_top_gate=False MOS primitive cleanly."""
    sign = -1 if mirror_x else 1
    pc_xs = sorted({grid(sign * (r[0] + r[2]) / 2.0 + dx) for r in prim.rects["polycont"]})
    pc_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects["polycont"]})
    gy_bot, gy_top = pc_ys[0], pc_ys[-1]
    gx_lo, gx_hi = pc_xs[0], pc_xs[-1]
    for gy in (gy_bot, gy_top):
        c.wire("metal1", [(gx_lo - 0.14, gy), (gx_hi + 0.14, gy)], 0.23)
    return gy_bot, gy_top, gx_lo, gx_hi


def tie_mos_gr(c: Cell, prim: Cell, dx: float, dy: float, x_rail_l: float, x_rail_r: float) -> tuple[float, float]:
    """Tie local psubdiffcont ring at left/right sides to vertical M1 VSS rails."""
    sc_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects["psubdiffcont"]})
    yb, yt = sc_ys[0], sc_ys[-1]
    for y in (yb, yt):
        for sx in (grid(dx - 1.50), grid(dx + 1.50)):
            c.pad("viali", sx, y, 0.17)
            c.pad("metal1", sx, y, 0.32)
        c.wire("metal1", [(x_rail_l, y), (x_rail_r, y)], 0.34)
    return yb, yt


def add_power_mesh(c: Cell, x_l: float, x_r: float, vss_y: float, vdd_y: float, x_straps: list[float]) -> None:
    """Wide M4 horizontal power trunks + stacked vias down to M1 at multiple X straps."""
    c.wire("metal4", [(x_l, vss_y), (x_r, vss_y)], 1.80)
    c.wire("metal4", [(x_l, vdd_y), (x_r, vdd_y)], 1.80)
    c.wire("metal1", [(x_l, vss_y), (x_r, vss_y)], 1.00)
    c.wire("metal1", [(x_l, vdd_y), (x_r, vdd_y)], 1.00)
    for xs in x_straps:
        for py in (vss_y, vdd_y):
            c.via1(xs, py)
            c.via2(xs, py)
            c.pad("metal3", xs, py, 0.56)
            via3(c, xs, py)


def tie_res_array(c: Cell, res_r_y: float, side_x: float, top_gr_y: float) -> None:
    """Extend vertical M1 VSS rails along resistor bay and tie outer/inner resistor guard rings solidly to VSS."""
    c.wire("metal1", [(-side_x, top_gr_y - 0.25), (-side_x, res_r_y + 0.50)], 0.60)
    c.wire("metal1", [(side_x, top_gr_y - 0.25), (side_x, res_r_y + 0.50)], 0.60)
    # Outer vertical psubdiffcont legs of dum (-8.20 +- 1.99) -> side rails
    for rx_out, rx_rail in ((-8.200 - 1.99, -side_x), (+8.200 + 1.99, +side_x)):
        c.pad("viali", rx_out, res_r_y, 0.17)
        c.pad("metal1", rx_out, res_r_y, 0.34)
        c.wire("metal1", [(min(rx_out, rx_rail), res_r_y), (max(rx_out, rx_rail), res_r_y)], 0.34)
    # Inner vertical psubdiffcont legs of active resistors (-4.22 + 1.99 = -2.23, +2.23) -> drop to bridged MOS top GR
    for sx in (-4.220 + 1.99, +4.220 - 1.99):
        c.pad("viali", sx, res_r_y, 0.17)
        c.pad("metal1", sx, res_r_y, 0.34)
    c.wire("metal1", [(-4.220 + 1.99, res_r_y), (+4.220 - 1.99, res_r_y)], 0.34)
    c.wire("metal1", [(0.0, res_r_y), (0.0, top_gr_y)], 0.34)
    c.wire("metal1", [(-4.00, top_gr_y), (+4.00, top_gr_y)], 0.34)


def build_sync2_buf(out: Path, pcache: Path, name: str = "sync2_buf_out_pdk", wn: float = 24, nfin: int = 4, wt: float = 12, nft: int = 4, rload: float = 550) -> tuple[dict, Cell, dict]:
    """Matched 2-stack CML buffer with double-ended poly gates, grounded dummy poly resistors, and M4 power trunks."""
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    inp = prepare_mos_prim(pcache, f"{name}_in", "sky130_fd_pr__nfet_01v8_lvt", dict(w=round(wn / nfin, 3), l=0.15, nf=nfin, conn_gates=1), trim_top_gate=False, add_dummies=False)
    tail = prepare_mos_prim(pcache, f"{name}_tail", "sky130_fd_pr__nfet_01v8", dict(w=round(wt / nft, 3), l=0.50, nf=nft, conn_gates=1), trim_top_gate=False, add_dummies=False)
    l_res = round((rload - 137.6) / 111.8, 3)
    res = pdk_device(pcache, f"{name}_res", "sky130_fd_pr__res_high_po_2p85", dict(l=l_res))
    res.rects.pop("checkpaint", None)
    dum = build_res_dummy(res)

    c = Cell()
    col_x = 5.400
    res_xs = (-8.200, -4.220, +4.220, +8.200)
    side_x = 12.000
    tail_y = 0.000
    tail_bot = tail.bbox()[1]
    ground_y = grid(tail_bot - 1.600)
    inp_y = grid(tail.bbox()[3] + 2.400 - inp.bbox()[1])
    res_r_y = grid(inp_y + inp.bbox()[3] + 2.200 - res.bbox()[1])
    vdd_y = grid(res_r_y + res.bbox()[3] + 1.800)

    # Tail centered at (0, 0)
    c.include(tail, dx=0.0, dy=tail_y)
    td_xs, ts_xs, td_y, ts_y = strap_mos_split(c, tail, 0.0, tail_y, False)
    tgy_b, tgy_t, tgx_l, tgx_r = strap_double_gates(c, tail, 0.0, tail_y)
    for sx in ts_xs:
        c.wire("metal2", [(sx, ts_y), (sx, ground_y)], 0.36)
        c.via1(sx, ground_y)
    c.wire("metal2", [(ts_xs[0], ground_y), (ts_xs[-1], ground_y)], 0.44)
    # Route vbias strap OUT of tail M1/M2 footprint (x_vb = -3.00 < -2.415) to avoid tail M1 spacing & M2 vss short
    x_vb = -3.00
    x_tg_loop = -3.60
    c.wire("metal1", [(x_tg_loop, tgy_b), (tgx_r + 0.14, tgy_b)], 0.23)
    c.wire("metal1", [(x_tg_loop, tgy_b), (x_tg_loop, tgy_t), (tgx_l - 0.14, tgy_t)], 0.23)
    c.via1(x_vb, tgy_b)
    c.via2(x_vb, tgy_b)
    c.wire("metal3", [(-side_x, tgy_b), (side_x, tgy_b)], 0.44)

    # Vertical VSS M1 side rails connecting MOS guard rings down to ground_y
    c.wire("metal1", [(-side_x, ground_y), (-side_x, inp_y + inp.bbox()[3])], 0.60)
    c.wire("metal1", [(side_x, ground_y), (side_x, inp_y + inp.bbox()[3])], 0.60)
    tie_mos_gr(c, tail, 0.0, tail_y, -side_x, side_x)

    # Input pair: Xmp (-col_x, drives outn) & Xmn (+col_x, drives outp)
    in_pts = {}
    out_pts = {}
    r2_y = grid(res_r_y - 3.435 - (res.bbox()[3] - 7.75 if False else 0.0))
    # Query exact R1/R2 of res
    r1_loc = next(y for _, _, y, lb in res.labels if lb == "R1")
    r2_loc = next(y for _, _, y, lb in res.labels if lb == "R2")
    r1_y = grid(res_r_y + r1_loc)
    r2_y = grid(res_r_y + r2_loc)

    for sgn, nm, onm, rx in ((-1.0, "inp", "outn", -4.220), (+1.0, "inn", "outp", +4.220)):
        dx = sgn * col_x
        c.include(inp, dx=dx, dy=inp_y, mirror_x=(sgn > 0))
        d_xs, s_xs, id_y, is_y = strap_mos_split(c, inp, dx, inp_y, (sgn > 0))
        gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, inp, dx, inp_y, (sgn > 0))
        _, top_gr_y = tie_mos_gr(c, inp, dx, inp_y, -side_x if sgn < 0 else dx - 1.6, dx + 1.6 if sgn < 0 else side_x)
        # Double-ended gate tie around outer side -> M3 port
        gx_side = grid(dx + sgn * 2.20)
        gx_edge = gx_l - 0.14 if sgn < 0 else gx_r + 0.14
        c.wire("metal1", [(gx_edge, gy_b), (gx_side, gy_b), (gx_side, gy_t), (gx_edge, gy_t)], 0.23)
        px_in = grid(dx + sgn * 3.10)
        c.wire("metal1", [(gx_side, gy_b), (px_in, gy_b)], 0.23)
        c.via1(px_in, gy_b)
        c.via2(px_in, gy_b)
        c.pad("metal3", px_in, gy_b, 0.56)
        in_pts[nm] = (px_in, gy_b)

        # Sources to tail drain (M2 vertical drops into shared tail M2 bar at td_y)
        c.wire("metal2", [(dx, is_y), (dx, td_y)], 0.44)
        # Drains up to resistor R2 via M3
        ox = grid(dx - sgn * 0.48)
        c.via2(ox, id_y)
        c.wire("metal3", [(ox, id_y), (ox, r2_y), (rx, r2_y)], 0.44)
        c.via2(rx, r2_y)
        c.via1(rx, r2_y)
        c.pad("metal3", rx, r2_y, 0.44)
        out_pts[onm] = (rx, r2_y)

    c.wire("metal2", [(-col_x, td_y), (col_x, td_y)], 0.48)
    for tdx in td_xs:
        c.wire("metal2", [(tdx, td_y), (0.0, td_y)], 0.36)

    # Resistors: dummies at -8.200, +8.200; active at -4.220 (outn), +4.220 (outp)
    for rx in (-8.200, +8.200):
        c.include(dum, dx=rx, dy=res_r_y)
    for rx in (-4.220, +4.220):
        c.include(res, dx=rx, dy=res_r_y)
        c.wire("metal1", [(rx, r1_y), (rx, vdd_y)], 0.56)

    c.wire("metal2", [(-5.00, ground_y), (+5.00, ground_y)], 0.44)
    tie_res_array(c, res_r_y, side_x, top_gr_y)
    add_power_mesh(c, -side_x, side_x, ground_y, vdd_y, [-5.000, 0.0, +5.000])

    c.port("inp", "metal3", *in_pts["inp"])
    c.port("inn", "metal3", *in_pts["inn"])
    c.port("outp", "metal3", *out_pts["outp"])
    c.port("outn", "metal3", *out_pts["outn"])
    c.port("vbias", "metal3", -side_x, tgy_b)
    c.port("vdd", "metal4", 0.0, vdd_y)
    c.port("vss", "metal4", 0.0, ground_y)
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} inp inn outp outn vbias vdd vss",
        f"XRp vdd outn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd outp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"Xmp outn inp tail vss sky130_fd_pr__nfet_01v8_lvt w={wn} l=0.15 nf={nfin}",
        f"Xmn outp inn tail vss sky130_fd_pr__nfet_01v8_lvt w={wn} l=0.15 nf={nfin}",
        f"Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w={wt} l=0.5 nf={nft}",
        f".ends {name}",
        "",
    ])
    meta = dict(ports=dict(inp=in_pts["inp"], inn=in_pts["inn"], outp=out_pts["outp"], outn=out_pts["outn"], vbias=(-side_x, tgy_b)), vdd_y=vdd_y, ground_y=ground_y)
    return signoff_with_plot(w, name, ref), c, meta


def build_sync2_latch(out: Path, pcache: Path, name: str = "sync2_latch_pdk", wdata: float = 16, whold: float = 14, wclock: float = 20, rload: float = 480) -> tuple[dict, Cell, dict]:
    """2-stack CML D-latch with dual-column symmetry, double-ended gates, and M4 power trunks."""
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    p_clk = prepare_mos_prim(pcache, f"{name}_clk", "sky130_fd_pr__nfet_01v8_lvt", dict(w=round(wclock / 4, 3), l=0.15, nf=4, conn_gates=1), trim_top_gate=False, add_dummies=False)
    p_hld = prepare_mos_prim(pcache, f"{name}_hld", "sky130_fd_pr__nfet_01v8_lvt", dict(w=round(whold / 4, 3), l=0.15, nf=4, conn_gates=1), trim_top_gate=False, add_dummies=False)
    p_dat = prepare_mos_prim(pcache, f"{name}_dat", "sky130_fd_pr__nfet_01v8_lvt", dict(w=round(wdata / 4, 3), l=0.15, nf=4, conn_gates=1), trim_top_gate=False, add_dummies=False)
    l_res = round((rload - 137.6) / 111.8, 3)
    res = pdk_device(pcache, f"{name}_res", "sky130_fd_pr__res_high_po_2p85", dict(l=l_res))
    res.rects.pop("checkpaint", None)
    dum = build_res_dummy(res)

    c = Cell()
    col_x = 5.400
    side_x = 12.000
    clk_y = 0.000
    ground_y = grid(clk_y + p_clk.bbox()[1] - 1.600)
    hold_y = grid(clk_y + p_clk.bbox()[3] + 2.400 - p_hld.bbox()[1])
    data_y = grid(hold_y + p_hld.bbox()[3] + 2.400 - p_dat.bbox()[1])
    res_r_y = grid(data_y + p_dat.bbox()[3] + 2.200 - res.bbox()[1])
    vdd_y = grid(res_r_y + res.bbox()[3] + 1.800)

    c.wire("metal1", [(-side_x, ground_y), (-side_x, data_y + p_dat.bbox()[3])], 0.60)
    c.wire("metal1", [(side_x, ground_y), (side_x, data_y + p_dat.bbox()[3])], 0.60)

    # Bottom clock pair: Xct at -col_x (drains=track), Xch at +col_x (drains=hold)
    clk_pts = {}
    cd_y = None
    for sgn, nm, x_tr in ((-1.0, "ct", -2.20), (+1.0, "ch", +2.20)):
        dx = sgn * col_x
        c.include(p_clk, dx=dx, dy=clk_y, mirror_x=(sgn > 0))
        d_xs, s_xs, cd_y, cs_y = strap_mos_split(c, p_clk, dx, clk_y, (sgn > 0))
        gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, p_clk, dx, clk_y, (sgn > 0))
        tie_mos_gr(c, p_clk, dx, clk_y, -side_x if sgn < 0 else dx - 1.6, dx + 1.6 if sgn < 0 else side_x)
        gx_side = grid(dx + sgn * 2.20)
        gx_edge = gx_l - 0.14 if sgn < 0 else gx_r + 0.14
        c.wire("metal1", [(gx_edge, gy_b), (gx_side, gy_b), (gx_side, gy_t), (gx_edge, gy_t)], 0.23)
        px = grid(dx + sgn * 3.10)
        c.wire("metal1", [(gx_side, gy_b), (px, gy_b)], 0.23)
        c.via1(px, gy_b); c.via2(px, gy_b); c.pad("metal3", px, gy_b, 0.56)
        clk_pts[nm] = (px, gy_b)
        for sx in s_xs:
            c.wire("metal2", [(sx, cs_y), (sx, ground_y)], 0.36)
            c.via1(sx, ground_y)
        c.wire("metal2", [(min(d_xs[0], x_tr), cd_y), (max(d_xs[-1], x_tr), cd_y)], 0.44)
        c.via2(x_tr, cd_y)

    # Cross-coupled hold pair (L=-col_x: drain=qn, gate=qp; R=+col_x: drain=qp, gate=qn)
    hs_y = hd_y = None
    h_gate_pts = {}
    for sgn, gnm in ((-1.0, "qp"), (+1.0, "qn")):
        dx = sgn * col_x
        rx = sgn * 4.220
        c.include(p_hld, dx=dx, dy=hold_y, mirror_x=(sgn > 0))
        d_xs, s_xs, hd_y, hs_y = strap_mos_split(c, p_hld, dx, hold_y, (sgn > 0))
        gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, p_hld, dx, hold_y, (sgn > 0))
        tie_mos_gr(c, p_hld, dx, hold_y, -side_x if sgn < 0 else dx - 1.6, dx + 1.6 if sgn < 0 else side_x)
        gx_side = grid(dx + sgn * 2.20)
        gx_edge = gx_l - 0.14 if sgn < 0 else gx_r + 0.14
        c.wire("metal1", [(gx_edge, gy_b), (gx_side, gy_b), (gx_side, gy_t), (gx_edge, gy_t)], 0.23)
        ix = grid(sgn * 3.10)
        gx_in = gx_r + 0.14 if sgn < 0 else gx_l - 0.14
        c.wire("metal1", [(min(ix, gx_in), gy_b), (max(ix, gx_in), gy_b)], 0.23)
        c.via1(ix, gy_b); c.via2(ix, gy_b); c.pad("metal3", ix, gy_b, 0.56)
        h_gate_pts[gnm] = (ix, gy_b)
        c.wire("metal2", [(min(d_xs[0], rx), hd_y), (max(d_xs[-1], rx), hd_y)], 0.44)
        c.via2(rx, hd_y)
    c.wire("metal2", [(-col_x, hs_y), (+col_x, hs_y)], 0.44)
    c.via2(+2.20, hs_y)
    c.wire("metal3", [(+2.20, cd_y), (+2.20, hs_y)], 0.44)

    # Data pair (L=-col_x: gate=dp, drain=qn; R=+col_x: gate=dn, drain=qp)
    ds_y = dd_y = None
    in_pts = {}
    for sgn, nm in ((-1.0, "dp"), (+1.0, "dn")):
        dx = sgn * col_x
        rx = sgn * 4.220
        c.include(p_dat, dx=dx, dy=data_y, mirror_x=(sgn > 0))
        d_xs, s_xs, dd_y, ds_y = strap_mos_split(c, p_dat, dx, data_y, (sgn > 0))
        gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, p_dat, dx, data_y, (sgn > 0))
        _, top_gr_y = tie_mos_gr(c, p_dat, dx, data_y, -side_x if sgn < 0 else dx - 1.6, dx + 1.6 if sgn < 0 else side_x)
        gx_side = grid(dx + sgn * 2.20)
        gx_edge = gx_l - 0.14 if sgn < 0 else gx_r + 0.14
        c.wire("metal1", [(gx_edge, gy_b), (gx_side, gy_b), (gx_side, gy_t), (gx_edge, gy_t)], 0.23)
        px = grid(dx + sgn * 3.10)
        c.wire("metal1", [(gx_side, gy_b), (px, gy_b)], 0.23)
        c.via1(px, gy_b); c.via2(px, gy_b); c.pad("metal3", px, gy_b, 0.56)
        in_pts[nm] = (px, gy_b)
        c.wire("metal2", [(min(d_xs[0], rx), dd_y), (max(d_xs[-1], rx), dd_y)], 0.44)
        c.via2(rx, dd_y)
    c.wire("metal2", [(-col_x, ds_y), (+col_x, ds_y)], 0.44)
    c.via2(-2.20, ds_y)
    c.wire("metal3", [(-2.20, cd_y), (-2.20, ds_y)], 0.44)

    r1_y = grid(res_r_y + next(y for _, _, y, lb in res.labels if lb == "R1"))
    r2_y = grid(res_r_y + next(y for _, _, y, lb in res.labels if lb == "R2"))
    for rx in (-8.200, +8.200):
        c.include(dum, dx=rx, dy=res_r_y)
    out_pts = {}
    for sgn, onm in ((-1.0, "qn"), (+1.0, "qp")):
        rx = sgn * 4.220
        c.include(res, dx=rx, dy=res_r_y)
        c.wire("metal1", [(rx, r1_y), (rx, vdd_y)], 0.56)
        c.via1(rx, r2_y); c.via2(rx, r2_y); c.pad("metal3", rx, r2_y, 0.44)
        c.wire("metal3", [(rx, hd_y), (rx, r2_y)], 0.44)
        out_pts[onm] = (rx, r2_y)

    yc_qp = grid(data_y + p_dat.bbox()[1] - 0.50)
    yc_qn = grid(yc_qp - 1.10)
    for target_rx, gate_pt, yc in ((+4.220, h_gate_pts["qp"], yc_qp), (-4.220, h_gate_pts["qn"], yc_qn)):
        gx, gy = gate_pt
        c.wire("metal3", [(gx, gy), (gx, yc)], 0.44)
        via3(c, gx, yc)
        via3(c, target_rx, yc)
        c.wire("metal4", [(min(gx, target_rx), yc), (max(gx, target_rx), yc)], 0.48)

    c.wire("metal2", [(-6.40, ground_y), (+6.40, ground_y)], 0.44)
    tie_res_array(c, res_r_y, side_x, top_gr_y)
    add_power_mesh(c, -side_x, side_x, ground_y, vdd_y, [-5.000, 0.0, +5.000])
    c.port("dp", "metal3", *in_pts["dp"])
    c.port("dn", "metal3", *in_pts["dn"])
    c.port("qp", "metal3", *out_pts["qp"])
    c.port("qn", "metal3", *out_pts["qn"])
    c.port("ct", "metal3", *clk_pts["ct"])
    c.port("ch", "metal3", *clk_pts["ch"])
    c.port("vdd", "metal4", 0.0, vdd_y)
    c.port("vss", "metal4", 0.0, ground_y)
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} dp dn qp qn ct ch vdd vss",
        f"XRp vdd qp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd qn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"Xdp qn dp track vss sky130_fd_pr__nfet_01v8_lvt w={wdata} l=0.15 nf=4",
        f"Xdn qp dn track vss sky130_fd_pr__nfet_01v8_lvt w={wdata} l=0.15 nf=4",
        f"Xhp qn qp hold vss sky130_fd_pr__nfet_01v8_lvt w={whold} l=0.15 nf=4",
        f"Xhn qp qn hold vss sky130_fd_pr__nfet_01v8_lvt w={whold} l=0.15 nf=4",
        f"Xct track ct vss vss sky130_fd_pr__nfet_01v8_lvt w={wclock} l=0.15 nf=4",
        f"Xch hold ch vss vss sky130_fd_pr__nfet_01v8_lvt w={wclock} l=0.15 nf=4",
        f".ends {name}",
        "",
    ])
    meta = dict(ports=dict(dp=in_pts["dp"], dn=in_pts["dn"], qp=out_pts["qp"], qn=out_pts["qn"], ct=clk_pts["ct"], ch=clk_pts["ch"]), vdd_y=vdd_y, ground_y=ground_y)
    return signoff_with_plot(w, name, ref), c, meta


def build_sync2_mux2(out: Path, pcache: Path, name: str = "sync2_mux2_pdk", wdata: float = 12, wselect: float = 24, wtail: float = 6, rload: float = 1100) -> tuple[dict, Cell, dict]:
    """SF-free 2-stack CML 2:1 mux with double-ended gates, grounded dummy poly resistors, and M4 power trunks."""
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    p_tail = prepare_mos_prim(pcache, f"{name}_tail", "sky130_fd_pr__nfet_01v8", dict(w=round(wtail / 2, 3), l=0.50, nf=2, conn_gates=1), trim_top_gate=False, add_dummies=False)
    p_sel = prepare_mos_prim(pcache, f"{name}_sel", "sky130_fd_pr__nfet_01v8_lvt", dict(w=round(wselect / 4, 3), l=0.15, nf=4, conn_gates=1), trim_top_gate=False, add_dummies=False)
    p_dat = prepare_mos_prim(pcache, f"{name}_dat", "sky130_fd_pr__nfet_01v8_lvt", dict(w=round(wdata / 4, 3), l=0.15, nf=4, conn_gates=1), trim_top_gate=False, add_dummies=False)
    l_res = round((rload - 137.6) / 111.8, 3)
    res = pdk_device(pcache, f"{name}_res", "sky130_fd_pr__res_high_po_2p85", dict(l=l_res))
    res.rects.pop("checkpaint", None)
    dum = build_res_dummy(res)

    c = Cell()
    col_x = 5.400
    side_x = 12.000
    tail_y = 0.000
    ground_y = grid(tail_y + p_tail.bbox()[1] - 1.600)
    sel_y = grid(tail_y + p_tail.bbox()[3] + 2.400 - p_sel.bbox()[1])
    rowa_y = grid(sel_y + p_sel.bbox()[3] + 2.400 - p_dat.bbox()[1])
    rowb_y = grid(rowa_y + p_dat.bbox()[3] + 2.400 - p_dat.bbox()[1])
    res_r_y = grid(rowb_y + p_dat.bbox()[3] + 2.200 - res.bbox()[1])
    vdd_y = grid(res_r_y + res.bbox()[3] + 1.800)

    c.wire("metal1", [(-side_x, ground_y), (-side_x, rowb_y + p_dat.bbox()[3])], 0.60)
    c.wire("metal1", [(side_x, ground_y), (side_x, rowb_y + p_dat.bbox()[3])], 0.60)

    c.include(p_tail, dx=0.0, dy=tail_y)
    td_xs, ts_xs, td_y, ts_y = strap_mos_split(c, p_tail, 0.0, tail_y, False)
    tgy_b, tgy_t, tgx_l, tgx_r = strap_double_gates(c, p_tail, 0.0, tail_y)
    for sx in ts_xs:
        c.wire("metal2", [(sx, ts_y), (sx, ground_y)], 0.36)
        c.via1(sx, ground_y)
    c.wire("metal2", [(ts_xs[0], ground_y), (ts_xs[-1], ground_y)], 0.44)
    x_vb, x_tg_loop = -3.00, -3.60
    c.wire("metal1", [(x_tg_loop, tgy_b), (tgx_r + 0.14, tgy_b)], 0.23)
    c.wire("metal1", [(x_tg_loop, tgy_b), (x_tg_loop, tgy_t), (tgx_l - 0.14, tgy_t)], 0.23)
    c.via1(x_vb, tgy_b); c.via2(x_vb, tgy_b)
    c.wire("metal3", [(-side_x, tgy_b), (side_x, tgy_b)], 0.44)
    tie_mos_gr(c, p_tail, 0.0, tail_y, -side_x, side_x)

    sel_pts = {}
    sd_y = None
    for sgn, nm, x_tr in ((-1.0, "sn", -2.20), (+1.0, "sp", +2.20)):
        dx = sgn * col_x
        c.include(p_sel, dx=dx, dy=sel_y, mirror_x=(sgn > 0))
        d_xs, s_xs, sd_y, ss_y = strap_mos_split(c, p_sel, dx, sel_y, (sgn > 0))
        gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, p_sel, dx, sel_y, (sgn > 0))
        tie_mos_gr(c, p_sel, dx, sel_y, -side_x if sgn < 0 else dx - 1.6, dx + 1.6 if sgn < 0 else side_x)
        gx_side = grid(dx + sgn * 2.20)
        gx_edge = gx_l - 0.14 if sgn < 0 else gx_r + 0.14
        c.wire("metal1", [(gx_edge, gy_b), (gx_side, gy_b), (gx_side, gy_t), (gx_edge, gy_t)], 0.23)
        px = grid(dx + sgn * 3.10)
        c.wire("metal1", [(gx_side, gy_b), (px, gy_b)], 0.23)
        c.via1(px, gy_b); c.via2(px, gy_b); c.pad("metal3", px, gy_b, 0.56)
        sel_pts[nm] = (px, gy_b)
        c.wire("metal2", [(dx, ss_y), (dx, td_y)], 0.44)
        c.wire("metal2", [(min(d_xs[0], x_tr), sd_y), (max(d_xs[-1], x_tr), sd_y)], 0.44)
        c.via2(x_tr, sd_y)
    c.wire("metal2", [(-col_x, td_y), (+col_x, td_y)], 0.48)
    for tdx in td_xs:
        c.wire("metal2", [(tdx, td_y), (0.0, td_y)], 0.36)

    in_pts = {}
    d_ys = {}
    for row_y, pfx, x_tr in ((rowa_y, "a", -2.20), (rowb_y, "b", +2.20)):
        dd_y = ds_y = None
        for sgn, suff in ((-1.0, "p"), (+1.0, "n")):
            dx = sgn * col_x
            rx = sgn * 4.220
            nm = f"{pfx}{suff}"
            c.include(p_dat, dx=dx, dy=row_y, mirror_x=(sgn > 0))
            d_xs, s_xs, dd_y, ds_y = strap_mos_split(c, p_dat, dx, row_y, (sgn > 0))
            gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, p_dat, dx, row_y, (sgn > 0))
            _, top_gr_y = tie_mos_gr(c, p_dat, dx, row_y, -side_x if sgn < 0 else dx - 1.6, dx + 1.6 if sgn < 0 else side_x)
            gx_side = grid(dx + sgn * 2.20)
            gx_edge = gx_l - 0.14 if sgn < 0 else gx_r + 0.14
            c.wire("metal1", [(gx_edge, gy_b), (gx_side, gy_b), (gx_side, gy_t), (gx_edge, gy_t)], 0.23)
            px = grid(dx + sgn * 3.10)
            c.wire("metal1", [(gx_side, gy_b), (px, gy_b)], 0.23)
            c.via1(px, gy_b); c.via2(px, gy_b); c.pad("metal3", px, gy_b, 0.56)
            in_pts[nm] = (px, gy_b)
            c.wire("metal2", [(min(d_xs[0], rx), dd_y), (max(d_xs[-1], rx), dd_y)], 0.44)
            c.via2(rx, dd_y)
        d_ys[pfx] = dd_y
        c.wire("metal2", [(-col_x, ds_y), (+col_x, ds_y)], 0.44)
        c.via2(x_tr, ds_y)
        c.wire("metal3", [(x_tr, sd_y), (x_tr, ds_y)], 0.44)

    r1_y = grid(res_r_y + next(y for _, _, y, lb in res.labels if lb == "R1"))
    r2_y = grid(res_r_y + next(y for _, _, y, lb in res.labels if lb == "R2"))
    for rx in (-8.200, +8.200):
        c.include(dum, dx=rx, dy=res_r_y)
    out_pts = {}
    for sgn, onm in ((-1.0, "qn"), (+1.0, "qp")):
        rx = sgn * 4.220
        c.include(res, dx=rx, dy=res_r_y)
        c.wire("metal1", [(rx, r1_y), (rx, vdd_y)], 0.56)
        c.via1(rx, r2_y); c.via2(rx, r2_y); c.pad("metal3", rx, r2_y, 0.44)
        c.wire("metal3", [(rx, d_ys["a"]), (rx, r2_y)], 0.44)
        out_pts[onm] = (rx, r2_y)

    c.wire("metal2", [(-5.00, ground_y), (+5.00, ground_y)], 0.44)
    tie_res_array(c, res_r_y, side_x, top_gr_y)
    add_power_mesh(c, -side_x, side_x, ground_y, vdd_y, [-5.000, 0.0, +5.000])
    for nm in ("ap", "an", "bp", "bn"):
        c.port(nm, "metal3", *in_pts[nm])
    c.port("sp", "metal3", *sel_pts["sp"])
    c.port("sn", "metal3", *sel_pts["sn"])
    c.port("qp", "metal3", *out_pts["qp"])
    c.port("qn", "metal3", *out_pts["qn"])
    c.port("vbias", "metal3", -side_x, tgy_b)
    c.port("vdd", "metal4", 0.0, vdd_y)
    c.port("vss", "metal4", 0.0, ground_y)
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} ap an bp bn sp sn qp qn vbias vdd vss",
        f"XRp vdd qp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd qn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"Xap qn ap ta vss sky130_fd_pr__nfet_01v8_lvt w={wdata} l=0.15 nf=4",
        f"Xan qp an ta vss sky130_fd_pr__nfet_01v8_lvt w={wdata} l=0.15 nf=4",
        f"Xbp qn bp tb vss sky130_fd_pr__nfet_01v8_lvt w={wdata} l=0.15 nf=4",
        f"Xbn qp bn tb vss sky130_fd_pr__nfet_01v8_lvt w={wdata} l=0.15 nf=4",
        f"Xsa ta sn tail vss sky130_fd_pr__nfet_01v8_lvt w={wselect} l=0.15 nf=4",
        f"Xsb tb sp tail vss sky130_fd_pr__nfet_01v8_lvt w={wselect} l=0.15 nf=4",
        f"Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w={wtail} l=0.5 nf={2}",
        f".ends {name}",
        "",
    ])
    meta = dict(ports=dict(**in_pts, sp=sel_pts["sp"], sn=sel_pts["sn"], qp=out_pts["qp"], qn=out_pts["qn"], vbias=(-side_x, tgy_b)), vdd_y=vdd_y, ground_y=ground_y)
    return signoff_with_plot(w, name, ref), c, meta


def build_sync2_dff(out: Path, pcache: Path, latch_c: Cell, latch_p: dict, name: str = "sync2_dff_pdk") -> tuple[dict, Cell, dict]:
    """Master (Y-mirrored) + center shielded M3 clock spine + Slave + MOS-cap Xseed DFF."""
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    seed = prepare_mos_prim(pcache, f"{name}_seed", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=0.50, nf=1, conn_gates=1), trim_top_gate=False, split_sd=False, add_dummies=False)

    c = Cell()
    side_x = 12.000
    dy_m = 0.000
    dy_s = 20.000  # Master top VSS at +5.15, Slave bot VSS at +14.85 (9.70 um central clock + Xseed bay)
    c.include(latch_c, dx=0.0, dy=dy_m, mirror_y=True)
    c.include(latch_c, dx=0.0, dy=dy_s, mirror_y=False)

    # Connect side VSS rails and vertical M4->M2 VSS bridge across central gap
    vss_m = -latch_p["ground_y"]        # +5.15
    vss_s = dy_s + latch_p["ground_y"] # +14.85
    vdd_m = -latch_p["vdd_y"]           # -32.93
    vdd_s = dy_s + latch_p["vdd_y"]     # +52.93
    c.wire("metal1", [(-side_x, vss_m - 0.5), (-side_x, vss_s + 0.5)], 0.60)
    c.wire("metal1", [(+side_x, vss_m - 0.5), (+side_x, vss_s + 0.5)], 0.60)
    for xs in (-5.00, +5.00):
        c.wire("metal4", [(xs, vss_m), (xs, vss_s)], 1.20)

    # Shielded M3 horizontal clock buses spanning cell width (-side_x .. +side_x)
    y_ckp, y_ckn = 7.100, 12.900
    c.wire("metal3", [(-side_x, y_ckp), (side_x, y_ckp)], 0.44)
    c.wire("metal3", [(-side_x, y_ckn), (side_x, y_ckn)], 0.44)

    # Master/Slave clock taps (Master ct/ch on M3 at y=+2.775, Slave ct/ch at y=+17.225):
    # - Master ct (-8.50, +2.775) -> ckp (M3 straight up to 7.10; clear of x=+-5.00 power vias!)
    # - Master ch (+8.50, +2.775) -> ckn (drop to M2 at 2.775, up along x=+7.20 to 12.90 -> M3)
    # - Slave ch (+8.50, +17.225) -> ckp (drop to M2 at 17.225, route x=+9.50 down to 7.10 -> M3)
    # - Slave ct (-8.50, +17.225) -> ckn (M3 straight down to 12.90)
    m_ct = (latch_p["ports"]["ct"][0], -latch_p["ports"]["ct"][1])
    m_ch = (latch_p["ports"]["ch"][0], -latch_p["ports"]["ch"][1])
    s_ct = (latch_p["ports"]["ct"][0], dy_s + latch_p["ports"]["ct"][1])
    s_ch = (latch_p["ports"]["ch"][0], dy_s + latch_p["ports"]["ch"][1])
    c.wire("metal3", [m_ct, (m_ct[0], y_ckp)], 0.44)
    c.wire("metal3", [s_ct, (s_ct[0], y_ckn)], 0.44)
    c.via2(m_ch[0], m_ch[1]); c.wire("metal2", [m_ch, (7.20, m_ch[1]), (7.20, y_ckn)], 0.44); c.via2(7.20, y_ckn)
    c.via2(s_ch[0], s_ch[1]); c.wire("metal2", [s_ch, (9.50, s_ch[1]), (9.50, y_ckp)], 0.44); c.via2(9.50, y_ckp)

    # Master qp(mp) (+4.22, -23.255) -> via2 -> M2 horizontal y=-24.90 to x=-10.60 -> M2 up to Slave dp (-8.50, +34.725)
    # Master qn(mn) (-4.22, -23.255) -> M3 to y=-21.70 -> via2 -> M2 horizontal to x=+10.60 -> M2 up to Slave dn (+8.50, +34.725)
    m_qp = (latch_p["ports"]["qp"][0], -latch_p["ports"]["qp"][1])
    m_qn = (latch_p["ports"]["qn"][0], -latch_p["ports"]["qn"][1])
    s_dp = (latch_p["ports"]["dp"][0], dy_s + latch_p["ports"]["dp"][1])
    s_dn = (latch_p["ports"]["dn"][0], dy_s + latch_p["ports"]["dn"][1])
    x_mp, x_mn = -10.600, +10.600
    y_mp_cross, y_mn_cross = grid(m_qp[1] - 1.65), grid(m_qn[1] + 1.55)
    c.wire("metal3", [m_qp, (m_qp[0], y_mp_cross)], 0.44)
    c.via2(m_qp[0], y_mp_cross)
    c.wire("metal2", [(m_qp[0], y_mp_cross), (x_mp, y_mp_cross), (x_mp, s_dp[1])], 0.44)
    c.via2(x_mp, s_dp[1])
    c.wire("metal3", [(x_mp, s_dp[1]), s_dp], 0.44)

    c.wire("metal3", [m_qn, (m_qn[0], y_mn_cross)], 0.44)
    c.via2(m_qn[0], y_mn_cross)
    c.wire("metal2", [(m_qn[0], y_mn_cross), (x_mn, y_mn_cross), (x_mn, s_dn[1])], 0.44)
    c.via2(x_mn, s_dn[1])
    c.wire("metal3", [(x_mn, s_dn[1]), s_dn], 0.44)

    # Place Xseed MOS-cap (w=1.0, l=0.5, nf=1) centered at (0.0, 10.0) cleanly with zero M1 collisions
    seed_y = 10.000
    c.include(seed, dx=0.0, dy=seed_y)
    c.wire("metal4", [(0.0, vss_m), (0.0, vss_s)], 1.20)
    # Connect D/S across center (y=seed_y, well inside [-0.50..+0.50]) -> outer right loop down to B (0.0, seed_y-1.285) -> M4
    c.rect("metal1", -0.51, grid(seed_y - 0.50), +0.51, grid(seed_y + 0.50))
    c.via1(0.0, seed_y); c.via2(0.0, seed_y); via3(c, 0.0, seed_y)
    yb_seed = grid(seed_y - 1.285)
    c.pad("viali", 0.0, yb_seed, 0.17); c.pad("metal1", 0.0, yb_seed, 0.34)
    c.wire("metal1", [(0.0, yb_seed), (+1.45, yb_seed), (+1.45, seed_y), (+0.45, seed_y)], 0.23)
    # Gate out horizontally inside built-in polycont M1 band (y=seed_y+0.69..0.86) -> via1 at x=-2.00 -> M2 left to x_mp
    gy_seed = grid(seed_y + 0.775)
    c.wire("metal1", [(-2.00, gy_seed), (0.0, gy_seed)], 0.17)
    c.via1(-2.00, gy_seed)
    c.wire("metal2", [(x_mp, gy_seed), (-2.00, gy_seed)], 0.34)

    # Join bottom Master VDD (vdd_m) and top Slave VDD (vdd_s) along outer M4 buses? Expose both or strap side M4?
    # Note: in top-level array, bottom VDD feeds Mux+Master VDD and top VDD feeds Slave+OutBuf VDD! Or bridge left/right M4?
    # Bridge x=-12.0 on M4 outside cell, OR wait: latch already uses M4 inside at yc_qp/yc_qn; side x=+-11.8 M4 would pass right through!
    # Keep x=-11.8 M5 vertical VDD strap joining vdd_m and vdd_s cleanly!
    for xm5 in (-11.60, +11.60):
        via4(c, xm5, vdd_m)
        via4(c, xm5, vdd_s)
        c.wire("metal5", [(xm5, vdd_m), (xm5, vdd_s)], 1.60)

    m_dp = (latch_p["ports"]["dp"][0], -latch_p["ports"]["dp"][1])
    m_dn = (latch_p["ports"]["dn"][0], -latch_p["ports"]["dn"][1])
    s_qp = (latch_p["ports"]["qp"][0], dy_s + latch_p["ports"]["qp"][1])
    s_qn = (latch_p["ports"]["qn"][0], dy_s + latch_p["ports"]["qn"][1])
    c.port("dp", "metal3", *m_dp)
    c.port("dn", "metal3", *m_dn)
    c.port("qp", "metal3", *s_qp)
    c.port("qn", "metal3", *s_qn)
    c.port("ckp", "metal3", -side_x, y_ckp)
    c.port("ckn", "metal3", -side_x, y_ckn)
    c.port("vdd", "metal4", 0.0, vdd_s)
    c.port("vss", "metal4", 0.0, vss_s)
    c.write(w / f"{name}.mag")

    l_ref = (out / "sync2_latch_pdk" / "sync2_latch_pdk_ref.spice").read_text()
    ref = l_ref + "\n" + "\n".join([
        f".subckt {name} dp dn qp qn ckp ckn vdd vss",
        "Xm dp dn mp mn ckp ckn vdd vss sync2_latch_pdk",
        "Xs mp mn qp qn ckn ckp vdd vss sync2_latch_pdk",
        "Xseed vss mp vss vss sky130_fd_pr__nfet_01v8 w=1.0 l=0.5 nf=1",
        f".ends {name}",
        "",
    ])
    meta = dict(ports=dict(dp=m_dp, dn=m_dn, qp=s_qp, qn=s_qn, ckp=(-side_x, y_ckp), ckn=(-side_x, y_ckn)), vdd_m=vdd_m, vdd_s=vdd_s, vss_m=vss_m, vss_s=vss_s)
    return signoff_with_plot(w, name, ref), c, meta


def build_sync_res_dummy(res_prim: Cell) -> Cell:
    """Build grounded dummy resistor matching exact xpolycontact width of any PDK res_high_po card (2p85 or 1p41)."""
    dum = Cell()
    for lyr in ("pwell", "psubdiff", "psubdiffcont", "locali", "viali", "metal1"):
        if lyr in res_prim.rects:
            dum.rects[lyr] = list(res_prim.rects[lyr])
    xp_l = min(r[0] for r in res_prim.rects["xpolycontact"])
    xp_r = max(r[2] for r in res_prim.rects["xpolycontact"])
    y_poly = max(r[3] for r in res_prim.rects["xpolycontact"])
    y_res = max(r[3] for r in res_prim.rects["ppolyres"])
    y_gr = max(r[3] for r in res_prim.rects["psubdiffcont"])
    dum.rect("poly", xp_l, -y_poly, xp_r, y_poly)
    dum.rects["locali"].extend([
        (xp_l, +y_res, xp_r, +y_poly),
        (xp_l, -y_poly, xp_r, -y_res),
        (-0.20, -y_gr, +0.20, -y_poly),
    ])
    dum.rects["polycont"] = list(res_prim.rects["viali"])
    return dum


def strap_mos_single(c: Cell, prim: Cell, dx: float, dy: float) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    """For nf=1 MOS (no split_sd): fill D/S M1 strips cleanly and return (d_pt, s_pt, g_pt) on M1/M2."""
    d_x = grid(next(x for _, x, _, lb in prim.labels if lb == "D") + dx)
    s_x = grid(next(x for _, x, _, lb in prim.labels if lb == "S") + dx)
    g_x = grid(next(x for _, x, _, lb in prim.labels if lb == "G") + dx)
    pc_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects["polycont"]})
    gy_b, gy_t = pc_ys[0], pc_ys[-1]
    c.rect("metal1", d_x - 0.16, dy - 0.50, d_x + 0.16, dy + 0.50)
    c.rect("metal1", s_x - 0.16, dy - 0.50, s_x + 0.16, dy + 0.50)
    c.via1(d_x, grid(dy + 0.25))
    c.via1(s_x, grid(dy - 0.25))
    gx_out = grid(dx + prim.bbox()[0] - 0.35)
    c.wire("metal1", [(g_x, gy_b), (gx_out, gy_b), (gx_out, gy_t), (g_x, gy_t)], 0.23)
    return (d_x, grid(dy + 0.25)), (s_x, grid(dy - 0.25)), (g_x, gy_t)


def place_split_mos(c: Cell, prim: Cell, dx: float, dy: float, x_rail_l: float, x_rail_r: float, tie_gr: bool = False, mirror_x: bool = False) -> dict:
    """Include a split-SD double-gated MOS primitive, strap D/S/G cleanly (no cross-row M1 shorts)."""
    c.include(prim, dx=dx, dy=dy, mirror_x=mirror_x)
    d_xs, s_xs, d_y, s_y = strap_mos_split(c, prim, dx, dy, mirror_x)
    gy_b, gy_t, gx_l, gx_r = strap_double_gates(c, prim, dx, dy, mirror_x)
    if not mirror_x:
        gx_edge, gx_out = gx_l - 0.14, grid(dx + prim.bbox()[0] - 0.35)
    else:
        gx_edge, gx_out = gx_r + 0.14, grid(dx + prim.bbox()[2] + 0.35)
    c.wire("metal1", [(gx_edge, gy_b), (gx_out, gy_b), (gx_out, gy_t), (gx_edge, gy_t)], 0.23)
    if tie_gr:
        sc_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects["psubdiffcont"]})
        c.pad("viali", dx, sc_ys[0], 0.17); c.pad("metal1", dx, sc_ys[0], 0.32)
        c.wire("metal1", [(x_rail_l, sc_ys[0]), (x_rail_r, sc_ys[0])], 0.30)
    d_pt = (grid(0.5 * (d_xs[0] + d_xs[-1])), d_y)
    s_pt = (grid(0.5 * (s_xs[0] + s_xs[-1])), s_y)
    if len(d_xs) == 1:
        c.via1(d_xs[0], d_y)
    if len(s_xs) == 1:
        c.via1(s_xs[0], s_y)
    return dict(d=d_pt, s=s_pt, g=(gx_out, gy_b), gy_b=gy_b, gy_t=gy_t, d_xs=d_xs, s_xs=s_xs)


def build_sync2_replica_bias(out: Path, pcache: Path, name: str = "sync2_ck_replica_bias_pdk", place_only: bool = False) -> tuple[dict, Cell, dict]:
    """Half-scale replica latch + resistive level-shift + 8-T OTA + 20x20 MIM compensation cap.

    Placement-first bottom-to-top row order:
      VSS (0.0) -> Xcomp 20x20 (14.0) -> XRls_p/n 12k (57.5) -> Row N1 (92.5)
      -> Row N2 (106.8) -> [12um channel] -> Row P PMOS (127.0) -> VDD (135.5) -> Row R2 Replica/Ref (146.5) -> Top VSS (156.0)
    """
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    kw_s = dict(trim_top_gate=False, split_sd=False, add_dummies=False)
    kw_m = dict(trim_top_gate=False, split_sd=True, add_dummies=False)
    p_n5x1 = prepare_mos_prim(pcache, f"{name}_n5x1", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.5, nf=1, conn_gates=1), **kw_s)
    p_ls   = prepare_mos_prim(pcache, f"{name}_ls",   "sky130_fd_pr__nfet_01v8", dict(w=2.5, l=2.0, nf=2, conn_gates=1), **kw_m)
    p_mn   = prepare_mos_prim(pcache, f"{name}_mn",   "sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.5, nf=2, conn_gates=1), **kw_m)
    p_ota  = prepare_mos_prim(pcache, f"{name}_ota",  "sky130_fd_pr__nfet_01v8_lvt", dict(w=3.0, l=0.5, nf=4, conn_gates=1), **kw_m)
    p_repd = prepare_mos_prim(pcache, f"{name}_repd", "sky130_fd_pr__nfet_01v8_lvt", dict(w=4.0, l=0.15, nf=2, conn_gates=1), **kw_m)
    p_repc = prepare_mos_prim(pcache, f"{name}_repc", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=2, conn_gates=1), **kw_m)
    p_pm   = prepare_mos_prim(pcache, f"{name}_pm",   "sky130_fd_pr__pfet_01v8", dict(w=6.0, l=0.5, nf=4, conn_gates=1), **kw_m)

    l_580 = round((580.0 - 137.6) / 111.8, 3)
    l_960 = round((960.0 - 137.6) / 111.8, 3)
    l_12k = round((12000.0 - 256.0) / 230.04, 3)
    r_ref = pdk_device(pcache, f"{name}_r580", "sky130_fd_pr__res_high_po_2p85", dict(l=l_580)); r_ref.rects.pop("checkpaint", None)
    r_rep = pdk_device(pcache, f"{name}_r960", "sky130_fd_pr__res_high_po_2p85", dict(l=l_960)); r_rep.rects.pop("checkpaint", None)
    r_12k = pdk_device(pcache, f"{name}_r12k", "sky130_fd_pr__res_high_po_1p41", dict(l=l_12k)); r_12k.rects.pop("checkpaint", None)
    dum12 = build_sync_res_dummy(r_12k)
    m_20  = pdk_device(pcache, f"{name}_m20",  "sky130_fd_pr__cap_mim_m3_1", dict(w=20, l=20)); m_20.rects.pop("checkpaint", None)

    c = Cell()
    side_x = 19.500
    vdd_x  = 14.200  # Strictly inside +-14.2 so outer bus channels (+-15..+-18) and side VSS (+-19.5) stay wide open!
    ground_y = 0.000
    y_cap = 13.000   # Row 1: Xcomp 20x20 MIM [2.80 .. 23.20] (>= 2.1 um below rep_out M3!)
    y_r12 = 57.500   # Row 2: XRls 12k 1p41 [29.065 .. 85.935]
    y_n1  = 92.500   # Row 3: Xref_sink (-11.5), Xls_p (-4.2), Xls_n (+4.2), Xota_t (+11.5) [88.95 .. 96.05]
    y_n2  = 106.800  # Row 4: Xmn1 (-11.5), Xota_dp (-4.2), Xota_dn (+4.2), Xmn2 (+11.5) [103.75 .. 109.85]
    y_pm  = 127.000  # Row 5: Xmp1 (-9.0), Xmp3 (-3.0), Xmp4 (+3.0), Xmp2 (+9.0) [122.905 .. 131.095]
    vdd_y = 135.500  # VDD M4/M1 trunk [+-14.2]
    y_r2  = 146.500  # Row 6: XRref (-11.0), Xrep_c (-3.2), Xrep_d (+3.2), XRrep (+11.0) [139.91 .. 153.09]
    top_vss_y = 156.000

    # Side M1 VSS rails & bottom/top power rails
    c.wire("metal1", [(-side_x, ground_y), (-side_x, top_vss_y)], 0.60)
    c.wire("metal1", [(+side_x, ground_y), (+side_x, top_vss_y)], 0.60)
    c.wire("metal4", [(-side_x, ground_y), (+side_x, ground_y)], 1.80)
    c.wire("metal1", [(-side_x, ground_y), (+side_x, ground_y)], 1.00)
    c.wire("metal1", [(-side_x, top_vss_y), (+side_x, top_vss_y)], 0.60)
    c.wire("metal4", [(-vdd_x, vdd_y), (+vdd_x, vdd_y)], 1.80)
    c.wire("metal1", [(-vdd_x, vdd_y), (+vdd_x, vdd_y)], 1.00)
    for py, xlist in ((ground_y, (-8.0, 0.0, +8.0)), (vdd_y, (-6.0, 0.0, +6.0))):
        for xs in xlist:
            c.via1(xs, py); c.via2(xs, py); c.pad("metal3", xs, py, 0.56); via3(c, xs, py)

    # Row 1: Xcomp 20x20 MIM
    c.include(m_20, dx=0.0, dy=y_cap)

    # Row 2: XRls_p/n (x=+-4.20) + dummies (x=+-11.00)
    for rx in (-11.00, +11.00):
        c.include(dum12, dx=rx, dy=y_r12)
    c.include(r_12k, dx=-4.20, dy=y_r12)
    c.include(r_12k, dx=+4.20, dy=y_r12)
    gr12_bot = grid(y_r12 + min((r[1] + r[3]) / 2.0 for r in r_12k.rects["psubdiffcont"]))
    for rx in (-11.00, -4.20, +4.20, +11.00):
        c.pad("viali", rx, gr12_bot, 0.17); c.pad("metal1", rx, gr12_bot, 0.34)
    c.wire("metal1", [(-side_x, gr12_bot), (+side_x, gr12_bot)], 0.34)

    # Row 3: Xref_sink (-11.5), Xls_p (-4.2), Xls_n (+4.2, mirror_x), Xota_t (+11.5)
    c.include(p_n5x1, dx=-11.5, dy=y_n1); r_sink = strap_mos_single(c, p_n5x1, -11.5, y_n1)
    ls_p = place_split_mos(c, p_ls, -4.2, y_n1, -side_x, +side_x, mirror_x=False)
    ls_n = place_split_mos(c, p_ls, +4.2, y_n1, -side_x, +side_x, mirror_x=True)
    c.include(p_n5x1, dx=+11.5, dy=y_n1); o_tail = strap_mos_single(c, p_n5x1, +11.5, y_n1)
    y_gr3 = 87.600
    c.wire("metal1", [(-side_x, y_gr3), (+side_x, y_gr3)], 0.34)
    for rx, pr in ((-11.5, p_n5x1), (-4.2, p_ls), (+4.2, p_ls), (+11.5, p_n5x1)):
        yb = grid(y_n1 + min((r[1] + r[3]) / 2.0 for r in pr.rects["psubdiffcont"]))
        c.pad("viali", rx, yb, 0.17); c.pad("metal1", rx, yb, 0.34)
        c.wire("metal1", [(rx, yb), (rx, y_gr3)], 0.30)

    # Row 4: Xmn1 (-13.0), Xota_dp (-4.2), Xota_dn (+4.2, mirror_x), Xmn2 (+13.0, mirror_x)
    mn1  = place_split_mos(c, p_mn,  -13.0, y_n2, -side_x, -13.0, mirror_x=False)
    otap = place_split_mos(c, p_ota,  -4.2, y_n2, -4.2, +4.2, mirror_x=False)
    otan = place_split_mos(c, p_ota,  +4.2, y_n2, -4.2, +4.2, mirror_x=True)
    mn2  = place_split_mos(c, p_mn,  +13.0, y_n2, +13.0, +side_x, mirror_x=True)
    y_gr4 = 102.300
    c.wire("metal1", [(-side_x, y_gr4), (+side_x, y_gr4)], 0.30)
    for rx, pr in ((-13.0, p_mn), (-4.2, p_ota), (+4.2, p_ota), (+13.0, p_mn)):
        yb = grid(y_n2 + min((r[1] + r[3]) / 2.0 for r in pr.rects["psubdiffcont"]))
        c.pad("viali", rx, yb, 0.17); c.pad("metal1", rx, yb, 0.34)
        c.wire("metal1", [(rx, yb), (rx, y_gr4)], 0.28)

    # Row 5: 4 PMOS at x=(-9.0, -3.0, +3.0, +9.0) in merged nwell (mp4/mp2 mirrored!)
    c.rect("nwell", -11.8, grid(y_pm - 4.15), +11.8, grid(y_pm + 4.15))
    pms = {}
    for px, pnm, mx in ((-9.0, "mp1", False), (-3.0, "mp3", False), (+3.0, "mp4", True), (+9.0, "mp2", True)):
        pm = place_split_mos(c, p_pm, px, y_pm, -11.8, +11.8, tie_gr=False, mirror_x=mx)
        pms[pnm] = pm
        sc_ys = sorted({grid((r[1] + r[3]) / 2.0 + y_pm) for r in p_pm.rects["nsubdiffcont"]})
        c.pad("viali", px, sc_ys[-1], 0.17); c.pad("metal1", px, sc_ys[-1], 0.32)
        c.wire("metal1", [(px, sc_ys[-1]), (px, vdd_y)], 0.32)
    c.wire("metal1", [(-11.0, grid(y_pm + 3.83)), (+11.0, grid(y_pm + 3.83))], 0.32)

    # Row 6: XRref (-11.0), Xrep_c (-3.2), Xrep_d (+3.2), XRrep (+11.0)
    c.include(r_ref, dx=-11.0, dy=y_r2)
    repc = place_split_mos(c, p_repc, -3.2, y_r2, -4.5, 0.0, mirror_x=False)
    repd = place_split_mos(c, p_repd, +3.2, y_r2, 0.0, +4.5, mirror_x=False)
    c.include(r_rep, dx=+11.0, dy=y_r2)
    y_gr6 = 138.600
    c.wire("metal1", [(-side_x, y_gr6), (+side_x, y_gr6)], 0.30)
    for rx, pr in ((-11.0, r_ref), (-3.2, p_repc), (+3.2, p_repd), (+11.0, r_rep)):
        yb = grid(y_r2 + min((r[1] + r[3]) / 2.0 for r in pr.rects["psubdiffcont"]))
        c.pad("viali", rx, yb, 0.17); c.pad("metal1", rx, yb, 0.34)
        c.wire("metal1", [(rx, yb), (rx, y_gr6)], 0.28)

    if place_only:
        c.port("vbias", "metal3", -side_x, 98.0)
        c.port("vbias_ck", "metal3", +side_x, 114.5)
        c.port("vdd", "metal4", 0.0, vdd_y)
        c.port("vss", "metal4", 0.0, ground_y)
        p_mag = w / f"{name}_place.mag"
        p_png = w / f"{name}_place.png"
        c.write(p_mag)
        subprocess.run(
            [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(p_mag), str(p_png)],
            cwd=REPO, check=True, capture_output=True,
        )
        bx1, by1, bx2, by2 = c.bbox()
        return dict(cell=name, mode="place_only", png=str(p_png), size_um=[round(bx2 - bx1, 3), round(by2 - by1, 3)]), c, {}

    # ================= Signal Routing (Layered Manhattan) =================
    # Strengthen vertical side M2 VSS straps along +-side_x (vbias/vbias_ck exit on M3!)
    for xs in (-side_x, +side_x):
        c.wire("metal2", [(xs, ground_y), (xs, top_vss_y)], 0.60)
        for yv in (ground_y, gr12_bot, y_gr3, mn1["s"][1], y_gr4, y_gr6, top_vss_y):
            c.via1(xs, yv)

    # 1. Xcomp bottom plate C2 (+10.82, y_cap) -> straight M3/M2 drop to VSS ground_y=0.0
    x_c2 = grid(next(x for _, x, _, lb in m_20.labels if lb == "C2"))
    x_c1 = grid(next(x for _, x, _, lb in m_20.labels if lb == "C1"))
    c.wire("metal3", [(x_c2, y_cap), (x_c2, 2.80)], 0.60)
    c.via2(x_c2, 2.80)
    c.wire("metal2", [(x_c2, 2.80), (x_c2, ground_y)], 0.60)
    c.via1(x_c2, ground_y)

    # 2. Row 3 VSS sources -> M2 bar at y_gr3=87.60
    c.wire("metal2", [(-side_x, y_gr3), (+side_x, y_gr3)], 0.44)
    for sp in (r_sink[1], ls_p["s"], ls_n["s"], o_tail[1]):
        c.wire("metal2", [sp, (sp[0], y_gr3)], 0.36)
        c.via1(sp[0], y_gr3)

    # 3. Row 3 vbias gates -> M1 horizontal bar at y_vb=98.0 -> M3 port at -side_x
    y_vb = 98.000
    c.wire("metal1", [(-side_x + 1.30, y_vb), (o_tail[2][0], y_vb)], 0.28)
    c.via1(-side_x + 1.30, y_vb); c.via2(-side_x + 1.30, y_vb)
    c.wire("metal3", [(-side_x, y_vb), (-side_x + 1.30, y_vb)], 0.44)
    c.pad("metal3", -side_x, y_vb, 0.56)
    for gx, gy in (r_sink[2], (ls_p["g"][0], ls_p["gy_t"]), (ls_n["g"][0], ls_n["gy_t"]), o_tail[2]):
        c.wire("metal1", [(gx, gy), (gx, y_vb)], 0.23)

    # 4. Row 3->4 in_p/in_n & OTA tail (y_otat=100.8) & mn1/mn2 sources -> VSS
    y_otat = 100.800
    c.wire("metal2", [otap["s"], (otap["s"][0], y_otat), (o_tail[0][0], y_otat), o_tail[0]], 0.36)
    c.wire("metal2", [otan["s"], (otan["s"][0], y_otat)], 0.36)
    for sp, xr in ((mn1["s"], -side_x), (mn2["s"], +side_x)):
        c.wire("metal2", [sp, (xr, sp[1])], 0.36)

    r12_top = grid(y_r12 + max(y for _, _, y, lb in r_12k.labels if lb in ("R1", "R2")))
    r12_bot = grid(y_r12 + min(y for _, _, y, lb in r_12k.labels if lb in ("R1", "R2")))
    for rx_r, ls, ota in ((-4.20, ls_p, otap), (+4.20, ls_n, otan)):
        c.via1(rx_r, r12_top); c.via2(rx_r, r12_top)
        c.wire("metal3", [(rx_r, r12_top), (rx_r, ls["d"][1])], 0.36)
        c.via2(rx_r, ls["d"][1])
        c.wire("metal2", [(min(rx_r, ota["g"][0]), ls["d"][1]), (max(rx_r, ota["g"][0]), ls["d"][1])], 0.36)
        c.via2(ota["g"][0], ls["d"][1])
        c.wire("metal3", [(ota["g"][0], ls["d"][1]), ota["g"]], 0.36)
        c.via2(*ota["g"]); c.via1(*ota["g"])

    # 5. Row 5 PMOS drains + Row 6 XRref/XRrep bottom + Xrep_d gate -> VDD (vdd_y=135.5)
    for pnm in ("mp1", "mp3", "mp4", "mp2"):
        dp = pms[pnm]["d"]
        c.wire("metal2", [dp, (dp[0], vdd_y)], 0.36); c.via1(dp[0], vdd_y)
    rr_bot = grid(y_r2 + min(y for _, _, y, lb in r_ref.labels if lb in ("R1", "R2")))
    rr_top = grid(y_r2 + max(y for _, _, y, lb in r_ref.labels if lb in ("R1", "R2")))
    rp_bot = grid(y_r2 + min(y for _, _, y, lb in r_rep.labels if lb in ("R1", "R2")))
    rp_top = grid(y_r2 + max(y for _, _, y, lb in r_rep.labels if lb in ("R1", "R2")))
    for rx_v in (-11.00, +11.00):
        yb_loc = rr_bot if rx_v < 0 else rp_bot
        c.via1(rx_v, yb_loc)
        c.wire("metal2", [(rx_v, yb_loc), (rx_v, vdd_y)], 0.40)
        c.via1(rx_v, vdd_y)
    c.via1(*repd["g"])
    c.wire("metal2", [repd["g"], (repd["g"][0], vdd_y)], 0.32)
    c.via1(repd["g"][0], vdd_y)

    # 6. Replica branch: Xrep_c source -> VSS, Xrep_c drain <-> Xrep_d source, Xrep_d drain -> rep_out
    c.wire("metal2", [repc["s"], (repc["s"][0], y_gr6)], 0.36); c.via1(repc["s"][0], y_gr6)
    c.wire("metal2", [repd["s"], (repc["d"][0], repd["s"][1]), repc["d"]], 0.36)
    c.wire("metal2", [repd["d"], (repd["d"][0], rp_top), (+11.00, rp_top)], 0.36); c.via1(+11.00, rp_top)

    # 7. vref (x=-16.5 M3) & rep_out (x=+16.5 M3) outer vertical channels down to XRls_n/XRls_p
    x_vref, x_repout = -16.500, +16.500
    c.via1(-11.00, rr_top); c.via2(-11.00, rr_top)
    c.wire("metal3", [(-11.00, rr_top), (x_vref, rr_top), (x_vref, 27.20)], 0.38)
    c.via2(x_vref, r_sink[0][1])
    c.wire("metal2", [r_sink[0], (x_vref, r_sink[0][1])], 0.34)
    c.via2(x_vref, 27.20)
    c.wire("metal2", [(x_vref, 27.20), (+4.20, 27.20)], 0.38)
    c.via2(+4.20, 27.20)
    c.wire("metal3", [(+4.20, 27.20), (+4.20, r12_bot)], 0.38)
    c.via2(+4.20, r12_bot); c.via1(+4.20, r12_bot)

    c.via2(+11.00, rp_top)
    c.wire("metal3", [(+11.00, rp_top), (x_repout, rp_top), (x_repout, 25.50), (-4.20, 25.50), (-4.20, r12_bot)], 0.38)
    c.via2(-4.20, r12_bot); c.via1(-4.20, r12_bot)

    # 8. Channel N2-P Manhattan tracks: horizontal M2 buses (y_nm=112.0, y_vck=114.5, y_nn=117.0, y_np=119.5) + vertical M3 drops!
    y_nm, y_vck, y_nn, y_np = 112.000, 114.500, 117.000, 119.500
    # nm bus
    c.wire("metal2", [(mn1["g"][0], y_nm), (mn2["g"][0], y_nm)], 0.38)
    for pt, up_or_dn in ((mn1["g"], "g"), (mn1["d"], "d"), (pms["mp4"]["s"], "s"), (mn2["g"], "g")):
        if up_or_dn == "g":
            c.via1(*pt)
        c.via2(*pt)
        c.wire("metal3", [pt, (pt[0], y_nm)], 0.36)
        c.via2(pt[0], y_nm)
    # nn bus
    c.wire("metal2", [(otan["d"][0], y_nn), (pms["mp2"]["g"][0], y_nn)], 0.38)
    for pt, up_or_dn in ((otan["d"], "d"), (pms["mp4"]["g"], "g"), (pms["mp2"]["s"], "s"), (pms["mp2"]["g"], "g")):
        if up_or_dn == "g":
            c.via1(*pt)
        c.via2(*pt)
        c.wire("metal3", [pt, (pt[0], y_nn)], 0.36)
        c.via2(pt[0], y_nn)
    # np bus
    c.wire("metal2", [(pms["mp1"]["g"][0], y_np), (max(pms["mp3"]["g"][0], otap["d"][0]), y_np)], 0.38)
    for pt, up_or_dn in ((pms["mp1"]["g"], "g"), (pms["mp1"]["s"], "s"), (otap["d"], "d"), (pms["mp3"]["g"], "g")):
        if up_or_dn == "g":
            c.via1(*pt)
        c.via2(*pt)
        c.wire("metal3", [pt, (pt[0], y_np)], 0.36)
        c.via2(pt[0], y_np)
    # vbias_ck bus (M2 from x=-14.8 to +18.2 at y=114.5)
    c.wire("metal2", [(-14.80, y_vck), (+side_x - 1.30, y_vck)], 0.44)
    for pt in (pms["mp3"]["s"], mn2["d"]):
        c.via2(*pt)
        c.wire("metal3", [pt, (pt[0], y_vck)], 0.40)
        c.via2(pt[0], y_vck)
    # Export vbias_ck RIGHT via M3 stub (no touch +side_x M2)
    c.via2(+side_x - 1.30, y_vck)
    c.wire("metal3", [(+side_x - 1.30, y_vck), (+side_x, y_vck)], 0.44)
    c.pad("metal3", +side_x, y_vck, 0.56)
    # Drop vbias_ck LEFT on M4 at x=-14.80 down to Xcomp C1 (x_c1, y_cap)
    c.via2(-14.80, y_vck); via3(c, -14.80, y_vck)
    c.wire("metal4", [(-14.80, y_vck), (-14.80, y_cap), (x_c1, y_cap)], 0.48)
    # Route vbias_ck UP on M3 at x=-1.20 (empty PMOS gap) -> y=141.0 -> left to repc["g"]
    c.via2(-1.20, y_vck)
    c.wire("metal3", [(-1.20, y_vck), (-1.20, 141.00), (repc["g"][0], 141.00), repc["g"]], 0.36)
    c.via2(*repc["g"]); c.via1(*repc["g"])

    c.port("vbias", "metal3", -side_x, y_vb)
    c.port("vbias_ck", "metal3", +side_x, y_vck)
    c.port("vdd", "metal4", 0.0, vdd_y)
    c.port("vss", "metal4", 0.0, ground_y)
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} vbias vbias_ck vdd vss",
        "Xref_sink vref vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=0.5 nf=1",
        f"XRref vdd vref vss sky130_fd_pr__res_high_po_2p85 l={l_580}",
        f"XRrep vdd rep_out vss sky130_fd_pr__res_high_po_2p85 l={l_960}",
        "Xrep_d rep_out vdd rep_track vss sky130_fd_pr__nfet_01v8_lvt w=8 l=0.15 nf=2",
        "Xrep_c rep_track vbias_ck vss vss sky130_fd_pr__nfet_01v8_lvt w=10 l=0.15 nf=2",
        "Xls_p in_p vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=2.0 nf=2",
        f"XRls_p rep_out in_p vss sky130_fd_pr__res_high_po_1p41 l={l_12k}",
        "Xls_n in_n vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=2.0 nf=2",
        f"XRls_n vref in_n vss sky130_fd_pr__res_high_po_1p41 l={l_12k}",
        "Xota_t ota_t vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=0.5 nf=1",
        "Xota_dp np in_p ota_t vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.5 nf=4",
        "Xota_dn nn in_n ota_t vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.5 nf=4",
        "Xmp1 np np vdd vdd sky130_fd_pr__pfet_01v8 w=24 l=0.5 nf=4",
        "Xmp3 vbias_ck np vdd vdd sky130_fd_pr__pfet_01v8 w=24 l=0.5 nf=4",
        "Xmp2 nn nn vdd vdd sky130_fd_pr__pfet_01v8 w=24 l=0.5 nf=4",
        "Xmp4 nm nn vdd vdd sky130_fd_pr__pfet_01v8 w=24 l=0.5 nf=4",
        "Xmn1 nm nm vss vss sky130_fd_pr__nfet_01v8 w=8 l=0.5 nf=2",
        "Xmn2 vbias_ck nm vss vss sky130_fd_pr__nfet_01v8 w=8 l=0.5 nf=2",
        "Xcomp vbias_ck vss sky130_fd_pr__cap_mim_m3_1 w=20 l=20",
        f".ends {name}",
        "",
    ])
    meta = dict(ports=dict(vbias=(-side_x, y_vb), vbias_ck=(+side_x, y_vck)), vdd_y=vdd_y, ground_y=ground_y)
    return signoff_with_plot(w, name, ref), c, meta


def build_sync2_ck_frontend(out: Path, pcache: Path, ckpre_c: Cell, ckpre_p: dict, ckdrv_c: Cell, ckdrv_p: dict, name: str = "sync2_ck_frontend_pdk", place_only: bool = False) -> tuple[dict, Cell, dict]:
    """2-stage AC-coupled clock front-end: Xckpre + Xckdrv (mirror_x) + 2x 15x15 MIM + 2x 4k 1p41 bias resistors."""
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    l_4k = round((4000.0 - 256.0) / 230.04, 3)
    r_4k = pdk_device(pcache, f"{name}_r4k", "sky130_fd_pr__res_high_po_1p41", dict(l=l_4k)); r_4k.rects.pop("checkpaint", None)
    dum4 = build_sync_res_dummy(r_4k)
    m_15 = pdk_device(pcache, f"{name}_m15", "sky130_fd_pr__cap_mim_m3_1", dict(w=15, l=15)); m_15.rects.pop("checkpaint", None)

    c = Cell()
    side_x = 12.900
    dy_pre = grid(-ckpre_c.bbox()[1])          # bottom at y=0.0
    dy_drv = grid(ckpre_c.bbox()[3] + dy_pre + 4.20 - ckdrv_c.bbox()[1])  # ~4.2 um gap above Xckpre
    drv_top = grid(dy_drv + ckdrv_c.bbox()[3])
    y_ccp = grid(drv_top + 4.20 + 7.70)        # 15x15 MIM h=15.4 (+-7.7)
    y_ccn = grid(y_ccp + 15.40 + 3.60)         # 3.6 um gap between MIM caps
    y_rb  = grid(y_ccn + 7.70 + 7.20 + 11.05)  # 4k 1p41 h=22.1 (+-11.05), ample capm.11 margin!
    top_gr_y = grid(y_rb + 11.40)

    c.include(ckpre_c, dx=0.0, dy=dy_pre)
    # Mirror X on Xckdrv so Xckpre.outp (+4.22) feeds Xckdrv.inp (+8.50) and outn (-4.22) feeds inn (-8.50) with ZERO crossover!
    c.include(ckdrv_c, dx=0.0, dy=dy_drv, mirror_x=True)
    c.include(m_15, dx=0.0, dy=y_ccp)
    c.include(m_15, dx=0.0, dy=y_ccn)
    for rx in (-10.00, +10.00):
        c.include(dum4, dx=rx, dy=y_rb)
    for rx in (-3.80, +3.80):
        c.include(r_4k, dx=rx, dy=y_rb)

    # VDD M5 straps linking Xckpre and Xckdrv VDD trunks cleanly
    vdd_pre = grid(dy_pre + ckpre_p["vdd_y"])
    vdd_drv = grid(dy_drv + ckdrv_p["vdd_y"])
    vss_pre = grid(dy_pre + ckpre_p["ground_y"])
    vss_drv = grid(dy_drv + ckdrv_p["ground_y"])
    for xm5 in (-11.60, +11.60):
        via4(c, xm5, vdd_pre); via4(c, xm5, vdd_drv)
        c.wire("metal5", [(xm5, vdd_pre), (xm5, vdd_drv)], 1.60)
    # Outer M1 VSS vertical guard-ring continuity up to resistor bay + continuous M2 VSS rails (-11.80, +11.80) from vss_pre to gr_bot
    gr_bot = grid(y_rb + min((r[1] + r[3]) / 2.0 for r in r_4k.rects["psubdiffcont"]))
    for xs in (-12.40, +12.40):
        c.wire("metal1", [(xs, grid(y_rb - 11.40)), (xs, top_gr_y)], 0.56)
    for rx in (-10.00, -3.80, +3.80, +10.00):
        c.pad("viali", rx, gr_bot, 0.17); c.pad("metal1", rx, gr_bot, 0.34)
    c.wire("metal1", [(-12.40, gr_bot), (+12.40, gr_bot)], 0.34)

    if place_only:
        c.port("clkp", "metal3", ckpre_p["ports"]["inp"][0], grid(dy_pre + ckpre_p["ports"]["inp"][1]))
        c.port("clkn", "metal3", ckpre_p["ports"]["inn"][0], grid(dy_pre + ckpre_p["ports"]["inn"][1]))
        c.port("ckp", "metal3", side_x, grid(y_rb - 13.50))
        c.port("ckn", "metal3", side_x, grid(y_rb - 11.00))
        c.port("vbias", "metal3", -side_x, grid(dy_pre + ckpre_p["ports"]["vbias"][1]))
        c.port("vbias_ck", "metal3", -side_x, grid(y_rb + 10.05))
        c.port("vdd", "metal4", 0.0, vdd_drv)
        c.port("vss", "metal4", 0.0, vss_pre)
        p_mag = w / f"{name}_place.mag"
        p_png = w / f"{name}_place.png"
        c.write(p_mag)
        subprocess.run(
            [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(p_mag), str(p_png)],
            cwd=REPO, check=True, capture_output=True,
        )
        bx1, by1, bx2, by2 = c.bbox()
        return dict(cell=name, mode="place_only", png=str(p_png), size_um=[round(bx2 - bx1, 3), round(by2 - by1, 3)]), c, {}

    # ================= Signal & Power Continuity Routing =================
    # 1. Connect vss_pre <-> vss_drv <-> gr_bot along vertical M2 straps at x=+-11.80 (clear of buf inner M2 [+-5.5] & M5 via4!)
    for xm2 in (-11.80, +11.80):
        c.wire("metal2", [(xm2, vss_pre), (xm2, gr_bot)], 0.56)
        for yv in (vss_pre, vss_drv, gr_bot):
            c.via1(xm2, yv)

    # 2. vbias M3 continuity between Xckpre and Xckdrv along x=-12.40 + export M3 stub to -side_x
    vb_pre = grid(dy_pre + ckpre_p["ports"]["vbias"][1])
    vb_drv = grid(dy_drv + ckdrv_p["ports"]["vbias"][1])
    c.wire("metal3", [(-12.40, vb_pre), (-12.40, vb_drv)], 0.44)
    c.wire("metal3", [(-side_x, vb_pre), (-12.40, vb_pre)], 0.44)
    c.pad("metal3", -side_x, vb_pre, 0.56)

    # 3. Xckpre (outp=+4.22, outn=-4.22) -> Xckdrv (mirror_x: inp=+8.50, inn=-8.50) via M3, hopping M2 over Xckdrv's vbias M3 rail!
    pre_outp = (ckpre_p["ports"]["outp"][0], grid(dy_pre + ckpre_p["ports"]["outp"][1]))
    pre_outn = (ckpre_p["ports"]["outn"][0], grid(dy_pre + ckpre_p["ports"]["outn"][1]))
    drv_inp  = (-ckdrv_p["ports"]["inp"][0], grid(dy_drv + ckdrv_p["ports"]["inp"][1]))
    drv_inn  = (-ckdrv_p["ports"]["inn"][0], grid(dy_drv + ckdrv_p["ports"]["inn"][1]))
    y_jog1 = grid(vdd_pre - 2.00)
    y_vb_lo, y_vb_hi = grid(vb_drv - 1.60), grid(vb_drv + 1.60)
    for po, di in ((pre_outp, drv_inp), (pre_outn, drv_inn)):
        c.wire("metal3", [po, (po[0], y_jog1), (di[0], y_jog1), (di[0], y_vb_lo)], 0.44)
        c.via2(di[0], y_vb_lo)
        c.wire("metal2", [(di[0], y_vb_lo), (di[0], y_vb_hi)], 0.44)
        c.via2(di[0], y_vb_hi)
        c.wire("metal3", [(di[0], y_vb_hi), di], 0.44)

    # 4. Xckdrv (mirror_x: outp=-4.22, outn=+4.22) -> Xccp/Xccn bottom plate C2 (+8.32)
    drv_outp = (-ckdrv_p["ports"]["outp"][0], grid(dy_drv + ckdrv_p["ports"]["outp"][1]))
    drv_outn = (-ckdrv_p["ports"]["outn"][0], grid(dy_drv + ckdrv_p["ports"]["outn"][1]))
    x_c1 = grid(next(x for _, x, _, lb in m_15.labels if lb == "C1"))
    x_c2 = grid(next(x for _, x, _, lb in m_15.labels if lb == "C2"))
    # ck_pre_p (-4.22) -> left to -8.32 below vdd_drv -> up to y_m2_bridge=76.2 -> M2 across to +8.32 -> M3 up to Xccp C2
    y_jog2 = grid(vdd_drv - 2.10)
    y_br2  = grid(drv_top + 1.40)
    c.wire("metal3", [drv_outp, (drv_outp[0], y_jog2), (-8.32, y_jog2), (-8.32, y_br2)], 0.44)
    c.via2(-8.32, y_br2)
    c.wire("metal2", [(-8.32, y_br2), (x_c2, y_br2)], 0.44)
    c.via2(x_c2, y_br2)
    c.wire("metal3", [(x_c2, y_br2), (x_c2, y_ccp)], 0.44)
    # ck_pre_n (+4.22) -> right to +10.10 below vdd_drv -> M3 straight up x=+10.10 (>>1.34 um outside mimcap!) to y_ccn -> Xccn C2
    c.wire("metal3", [drv_outn, (drv_outn[0], y_jog2), (10.10, y_jog2), (10.10, y_ccn), (x_c2, y_ccn)], 0.44)

    # 5. Top plates C1 (-0.88) -> 4k bottom R2 (ckp=-3.80, ckn=+3.80) -> RIGHT M3 ports at +side_x
    rb_bot = grid(y_rb + min(y for _, _, y, lb in r_4k.labels if lb in ("R1", "R2")))
    rb_top = grid(y_rb + max(y for _, _, y, lb in r_4k.labels if lb in ("R1", "R2")))
    y_ckp_bus = grid(y_ccn + 10.60)  # >= 3.1 um above Xccn top mimcap edge (capm.11!)
    y_ckn_bus = rb_bot
    # ckp: Xccp C1 (-0.88, y_ccp) -> M4 left to x=-10.30 (>=1.7 um outside mimcap!) -> via3 -> M3 up to rb_bot (-3.80) & drop to M2 y_ckp_bus -> +10.20 -> M3 port
    c.wire("metal4", [(x_c1, y_ccp), (-10.30, y_ccp)], 0.48)
    via3(c, -10.30, y_ccp)
    c.wire("metal3", [(-10.30, y_ccp), (-10.30, rb_bot), (-3.80, rb_bot)], 0.44)
    c.via1(-3.80, rb_bot); c.via2(-3.80, rb_bot)
    c.wire("metal3", [(-3.80, rb_bot), (-3.80, y_ckp_bus)], 0.44)
    c.via2(-3.80, y_ckp_bus)
    c.wire("metal2", [(-3.80, y_ckp_bus), (+10.20, y_ckp_bus)], 0.44)
    c.via2(+10.20, y_ckp_bus)
    c.wire("metal3", [(+10.20, y_ckp_bus), (+side_x, y_ckp_bus)], 0.44)
    # ckn: Xccn C1 (-0.88, y_ccn) -> M4 up to y_ccn_m4 (+9.60, >= 1.82 um above mimcap!) -> M4 right to +3.80 -> via3 -> M3 up to rb_bot (+3.80) -> M3 right to +side_x
    y_ccn_m4 = grid(y_ccn + 9.60)
    c.wire("metal4", [(x_c1, y_ccn), (x_c1, y_ccn_m4), (+3.80, y_ccn_m4)], 0.48)
    via3(c, +3.80, y_ccn_m4)
    c.wire("metal3", [(+3.80, y_ccn_m4), (+3.80, y_ckn_bus), (+side_x, y_ckn_bus)], 0.44)
    c.via1(+3.80, y_ckn_bus); c.via2(+3.80, y_ckn_bus)

    # 6. 4k top R1 -> vbias_ck on M3 exiting LEFT at (-side_x, rb_top)
    c.via1(-3.80, rb_top); c.via2(-3.80, rb_top)
    c.via1(+3.80, rb_top); c.via2(+3.80, rb_top)
    c.wire("metal3", [(-side_x, rb_top), (+3.80, rb_top)], 0.44)

    clkp_pt = (ckpre_p["ports"]["inp"][0], grid(dy_pre + ckpre_p["ports"]["inp"][1]))
    clkn_pt = (ckpre_p["ports"]["inn"][0], grid(dy_pre + ckpre_p["ports"]["inn"][1]))
    c.port("clkp", "metal3", *clkp_pt)
    c.port("clkn", "metal3", *clkn_pt)
    c.port("ckp", "metal3", +side_x, y_ckp_bus)
    c.port("ckn", "metal3", +side_x, y_ckn_bus)
    c.port("vbias", "metal3", -side_x, vb_pre)
    c.port("vbias_ck", "metal3", -side_x, rb_top)
    c.port("vdd", "metal4", 0.0, vdd_drv)
    c.port("vss", "metal4", 0.0, vss_pre)
    c.write(w / f"{name}.mag")

    pre_ref = (out / "sync2_buf_ckpre_pdk" / "sync2_buf_ckpre_pdk_ref.spice").read_text()
    drv_ref = (out / "sync2_buf_ckdrv_pdk" / "sync2_buf_ckdrv_pdk_ref.spice").read_text()
    ref = pre_ref + "\n" + drv_ref + "\n" + "\n".join([
        f".subckt {name} clkp clkn ckp ckn vbias vbias_ck vdd vss",
        "Xckpre clkp clkn ck_mid_p ck_mid_n vbias vdd vss sync2_buf_ckpre_pdk",
        "Xckdrv ck_mid_p ck_mid_n ck_pre_p ck_pre_n vbias vdd vss sync2_buf_ckdrv_pdk",
        "Xccp ckp ck_pre_p sky130_fd_pr__cap_mim_m3_1 w=15 l=15",
        "Xccn ckn ck_pre_n sky130_fd_pr__cap_mim_m3_1 w=15 l=15",
        f"Xrbp ckp vbias_ck vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        f"Xrbn ckn vbias_ck vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        f".ends {name}",
        "",
    ])
    meta = dict(ports=dict(clkp=clkp_pt, clkn=clkn_pt, ckp=(+side_x, y_ckp_bus), ckn=(+side_x, y_ckn_bus), vbias=(-side_x, vb_pre), vbias_ck=(-side_x, rb_top)), vdd_pre=vdd_pre, vdd_drv=vdd_drv, vss_pre=vss_pre, vss_drv=vss_drv)
    return signoff_with_plot(w, name, ref), c, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "results/layout/sync2_divider/pdk_blocks")
    ap.add_argument("--only", default="all", help="Comma-separated subset, 'p1', 'replica', or 'all'")
    ap.add_argument("--place-only", action="store_true", help="Placement-first mode (render *_place.png before signal routing)")
    a = ap.parse_args()
    a.out = a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=True)
    pcache = a.out / "_prims"
    pcache.mkdir(exist_ok=True)
    if a.only == "replica":
        r_res, _, _ = build_sync2_replica_bias(a.out, pcache, place_only=a.place_only)
        print(json.dumps(r_res, indent=2))
        return
    if a.only == "frontend":
        _, c_pre, m_pre = build_sync2_buf(a.out, pcache, "sync2_buf_ckpre_pdk", wn=20, nfin=4, wt=12, nft=4, rload=850)
        _, c_drv, m_drv = build_sync2_buf(a.out, pcache, "sync2_buf_ckdrv_pdk", wn=32, nfin=4, wt=24, nft=4, rload=550)
        f_res, _, _ = build_sync2_ck_frontend(a.out, pcache, c_pre, m_pre, c_drv, m_drv, place_only=a.place_only)
        print(json.dumps(f_res, indent=2))
        return
    b_out, _, _ = build_sync2_buf(a.out, pcache, "sync2_buf_out_pdk", wn=24, nfin=4, wt=12, nft=4, rload=550)
    b_pre, _, _ = build_sync2_buf(a.out, pcache, "sync2_buf_ckpre_pdk", wn=20, nfin=4, wt=12, nft=4, rload=850)
    b_drv, _, _ = build_sync2_buf(a.out, pcache, "sync2_buf_ckdrv_pdk", wn=32, nfin=4, wt=24, nft=4, rload=550)
    l_res, l_cell, l_meta = build_sync2_latch(a.out, pcache)
    m_res, _, _ = build_sync2_mux2(a.out, pcache)
    d_res, _, _ = build_sync2_dff(a.out, pcache, l_cell, l_meta)
    res = {
        "sync2_buf_out_pdk": b_out,
        "sync2_buf_ckpre_pdk": b_pre,
        "sync2_buf_ckdrv_pdk": b_drv,
        "sync2_latch_pdk": l_res,
        "sync2_mux2_pdk": m_res,
        "sync2_dff_pdk": d_res,
    }
    if a.only != "p1":
        r_res, _, _ = build_sync2_replica_bias(a.out, pcache)
        res["sync2_ck_replica_bias_pdk"] = r_res
    (a.out / "summary.json").write_text(json.dumps(res, indent=2))
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
