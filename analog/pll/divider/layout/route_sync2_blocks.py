#!/usr/bin/env python3
"""Compact M1/M2 signal router for sync2_latch_pdk, sync2_buf_out_pdk, sync2_mux2_pdk, and sync2_dff_pdk.

Uses compact placements from place_sync2_blocks.py (zero M4, zero bloat) and verifies:
  - DRC=0, LVS=True, PROP_ERR=False, zero disconnected ports (via check.py)
  - Zero floating nodes in Magic native RC extraction (review_cell.extract_rc)
  - Annotated WIP/final PNG plots for visual inspection (via plot_mag.py)

Usage:
    uv run python analog/pll/divider/layout/route_sync2_blocks.py --out results/layout/sync2_divider/compact_routed
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
sys.path.insert(0, str(REPO / "analog/pll/divider/layout"))

import place_sync2_blocks as pb  # noqa: E402
import review_cell  # noqa: E402
from build_prescaler8_pdk import run_signoff  # noqa: E402
from check import exported_ports  # noqa: E402
from geometry import Cell  # noqa: E402
from summarize_parasitics import summarize_pex_spice  # noqa: E402

grid = pb.grid


def signoff_plot_and_rc(w: Path, name: str, ref_text: str) -> dict:
    """Always plot PNG first, then run DRC/LVS signoff + RCX floating-node audit."""
    w.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{name}.mag"), str(w / f"{name}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    for stale in (w / f"{name}.res.ext", w / f"{name}.ext", w / f"{name}_rcx.spice"):
        if stale.exists():
            stale.unlink()
    info = run_signoff(w, name, ref_text)
    rcx = w / f"{name}_rcx.spice"
    if rcx.exists():
        rcx.unlink()
    try:
        rc = review_cell.extract_rc(w, name)
        rc_note = f"ok (R={rc['resistor_count']})"
    except Exception as e:
        rc_note = str(e)
    txt = rcx.read_text() if rcx.exists() else ""
    non_cap = set()
    for line in txt.splitlines():
        if not line.startswith("C") and not line.startswith("*") and not line.startswith("."):
            non_cap.update(line.split()[1:])
    float_a = sorted({
        t for l in txt.splitlines() if l.startswith("C")
        for t in l.split()[1:3] if t.startswith("a_") and t not in non_cap
    })
    ports = exported_ports(w / f"{name}_lvs.spice", name)
    pex = summarize_pex_spice(w / f"{name}_pex.spice", ports)
    info["rc_note"] = rc_note
    info["floating_a_nodes"] = float_a
    info["port_caps_fF"] = {k: round(v["total_node_fF"], 3) for k, v in pex["port_caps_fF"].items()}
    print(f"  RC audit {name:20s}: float_a={len(float_a)} | {rc_note} | caps={info['port_caps_fF']}", flush=True)
    return info


def via3(c: Cell, x: float, y: float) -> None:
    """Place single SKY130 via3 (0.32 um Magic min) with M3>=0.24um2 (0.52um) and 0.50um M4 pads."""
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.50)


def strap_compact_fet(
    c: Cell, prim: Cell, dx: float, dy: float, y_s_off: float = -0.65, y_d_off: float = +0.65, double_via: bool = False,
) -> dict:
    """Place horizontal M2 S/D straps strictly inside diff_y and M1 top/bot gate links; return terminal points."""
    d_xs = sorted({grid(x + dx) for _, x, _, lb in prim.labels if lb.startswith("D")})
    s_xs = sorted({grid(x + dx) for _, x, _, lb in prim.labels if lb.startswith("S")})
    if len(d_xs) == 2 and prim.labels[-1][1] > 0:
        pass
    # Fallback explicit D/S finger scan for nf=1,2,4 (supports both ndiffc & pdiffc)
    nd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects.get("ndiffc", prim.rects.get("pdiffc", []))})
    # Notice labels tell which index is D vs S!
    d_lbls = {grid(x + dx) for _, x, _, lb in prim.labels if lb.startswith("D")}
    if nd_xs and d_lbls:
        d_idx_parity = next(i % 2 for i, vx in enumerate(nd_xs) if vx in d_lbls)
        d_xs = [vx for i, vx in enumerate(nd_xs) if i % 2 == d_idx_parity]
        s_xs = [vx for i, vx in enumerate(nd_xs) if i % 2 != d_idx_parity]

    ys = grid(dy + y_s_off)
    yd = grid(dy + y_d_off)
    voffs = (-0.23, +0.23) if (double_via and abs(y_d_off - y_s_off) >= 1.25) else (0.0,)
    for x in s_xs:
        for vo in voffs:
            c.via1(x, grid(ys + vo))
        if len(voffs) > 1:
            c.wire("metal2", [(x, grid(ys + voffs[0])), (x, grid(ys + voffs[-1]))], 0.32)
    if len(s_xs) >= 2:
        c.wire("metal2", [(s_xs[0], ys), (s_xs[-1], ys)], 0.34)
    for x in d_xs:
        for vo in voffs:
            c.via1(x, grid(yd + vo))
        if len(voffs) > 1:
            c.wire("metal2", [(x, grid(yd + voffs[0])), (x, grid(yd + voffs[-1]))], 0.32)
    if len(d_xs) >= 2:
        c.wire("metal2", [(d_xs[0], yd), (d_xs[-1], yd)], 0.34)

    pc_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects["polycont"]})
    pc_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects["polycont"]})
    gy_b, gy_t = pc_ys[0], pc_ys[-1]
    gx_l, gx_r = pc_xs[0], pc_xs[-1]
    for gy in (gy_b, gy_t):
        c.wire("metal1", [(gx_l - 0.14, gy), (gx_r + 0.14, gy)], 0.23)

    return dict(d_xs=d_xs, s_xs=s_xs, yd=yd, ys=ys, gy_b=gy_b, gy_t=gy_t, gx_l=gx_l, gx_r=gx_r)


def add_outer_gate_loop(c: Cell, st: dict, dx: float, sgn: float, loop_off: float = 1.40) -> tuple[float, float]:
    """Connect top & bottom gate M1 rails along the outer edge (x = dx + sgn*loop_off) and return via1-ready tap."""
    gx_edge = grid(st["gx_l"] - 0.10 if sgn < 0 else st["gx_r"] + 0.10)
    gx_loop = grid(dx + sgn * loop_off)  # inside +-3.005 dummy poly (clear of M1 guard ring +-3.825!)
    c.wire("metal1", [(gx_edge, st["gy_b"]), (gx_loop, st["gy_b"]), (gx_loop, st["gy_t"]), (gx_edge, st["gy_t"])], 0.23)
    return gx_loop, st["gy_b"]


def tie_segmented_center_dummies(c: Cell, dx_c: float, ys_rows: list[float], gy_bot: float) -> None:
    """Tie segmented center dummy poly strips to bottom guard ring via vertical locali spine (keeps M1/M2/poly free in gaps)."""
    # Put polycont + poly pad at bottom of bottom row's dummy poly and at center of upper rows, joined by 0.20 um locali
    y_gr_li = grid(gy_bot + 0.41)
    y_top = max(ys_rows)
    c.rect("locali", grid(dx_c - 0.10), y_gr_li, grid(dx_c + 0.10), grid(y_top + 0.17))
    for yr in ys_rows:
        c.rect("poly", grid(dx_c - 0.17), grid(yr - 0.17), grid(dx_c + 0.17), grid(yr + 0.17))
        c.rect("polycont", grid(dx_c - 0.085), grid(yr - 0.085), grid(dx_c + 0.085), grid(yr + 0.085))
        c.rect("locali", grid(dx_c - 0.17), grid(yr - 0.17), grid(dx_c + 0.17), grid(yr + 0.17))


def route_latch_core(
    c: Cell, pcache: Path, dx_c: float, gx1: float, gx2: float, gy1: float, gy2: float,
    tie_l: bool, tie_r: bool, y_res: float = 18.600, export_pins: bool = True,
) -> dict:
    """Route a complete compact 2-stack CML latch in pure locali + M1 + M2 (zero M3/M4)."""
    p_clk = pb.mos_prim(pcache, "l_clk", "sky130_fd_pr__nfet_01v8_lvt", 5.0, 0.15, 4)
    p_dat = pb.mos_prim(pcache, "l_dat", "sky130_fd_pr__nfet_01v8_lvt", 4.0, 0.15, 4)
    p_hld = pb.mos_prim(pcache, "l_hld", "sky130_fd_pr__nfet_01v8_lvt", 3.5, 0.15, 4)
    p_res = pb.res_prim(pcache, "l_r480", "sky130_fd_pr__res_high_po_2p85", 3.063)

    pb.build_latch_core(c, pcache, dx_c, gx1, gx2, tie_l=tie_l, tie_r=tie_r, y_res=y_res)

    dx_m, dx_r = 1.600, 1.750
    y_clk, y_dat, y_hld = 0.000, 6.200, 11.700
    tie_segmented_center_dummies(c, dx_c, [y_clk, y_dat, y_hld], gy1)

    # Strap S/D & gates for all 6 LVT FETs (double via1 per finger on M1->M2 to cut Rs/Rd & EM stress!)
    st_clk_l = strap_compact_fet(c, p_clk, grid(dx_c - dx_m), y_clk, -0.75, +0.75, double_via=True)
    st_clk_r = strap_compact_fet(c, p_clk, grid(dx_c + dx_m), y_clk, -0.75, +0.75, double_via=True)
    st_dat_l = strap_compact_fet(c, p_dat, grid(dx_c - dx_m), y_dat, -0.70, +0.70, double_via=True)
    st_dat_r = strap_compact_fet(c, p_dat, grid(dx_c + dx_m), y_dat, -0.70, +0.70, double_via=True)
    st_hld_l = strap_compact_fet(c, p_hld, grid(dx_c - dx_m), y_hld, -0.65, +0.65, double_via=True)
    st_hld_r = strap_compact_fet(c, p_hld, grid(dx_c + dx_m), y_hld, -0.65, +0.65, double_via=True)

    # Outer double-ended gate loops for ct/ch/dp/dn/hp/hn
    g_ct = add_outer_gate_loop(c, st_clk_l, grid(dx_c - dx_m), -1.0)
    g_ch = add_outer_gate_loop(c, st_clk_r, grid(dx_c + dx_m), +1.0)
    g_dp = add_outer_gate_loop(c, st_dat_l, grid(dx_c - dx_m), -1.0)
    g_dn = add_outer_gate_loop(c, st_dat_r, grid(dx_c + dx_m), +1.0)
    add_outer_gate_loop(c, st_hld_l, grid(dx_c - dx_m), -1.0)
    add_outer_gate_loop(c, st_hld_r, grid(dx_c + dx_m), +1.0)

    # 1. VSS: Xct.S & Xch.S drop straight down on M2 to bottom guard ring M1 (y = gy1 + 0.225, double via1!)
    y_vss_gr = grid(gy1 + 0.225)
    for st in (st_clk_l, st_clk_r):
        xs_mid = st["s_xs"][0] if len(st["s_xs"]) == 1 else grid(0.5 * (st["s_xs"][0] + st["s_xs"][-1]))
        c.wire("metal2", [(xs_mid, st["ys"]), (xs_mid, y_vss_gr)], 0.36)
        c.via1(grid(xs_mid - 0.23), y_vss_gr); c.via1(grid(xs_mid + 0.23), y_vss_gr)
        c.wire("metal2", [(grid(xs_mid - 0.23), y_vss_gr), (grid(xs_mid + 0.23), y_vss_gr)], 0.32)

    # 2. track: Xct.D (d_xs[-1] = dx_c - 0.64) up M2 to y=3.35 -> via1 -> M1 across -> via1 -> M2 up to Xdp.S & Xdn.S!
    y_trk = 3.350
    x_trk_l, x_trk_r = st_dat_l["s_xs"][-1], st_dat_r["s_xs"][0]  # dx_c - 1.12, dx_c + 1.12
    c.wire("metal2", [(st_clk_l["d_xs"][-1], st_clk_l["yd"]), (st_clk_l["d_xs"][-1], y_trk), (x_trk_l, y_trk)], 0.32)
    c.via1(x_trk_l, y_trk)
    c.wire("metal1", [(x_trk_l, y_trk), (x_trk_r, y_trk)], 0.26)
    c.via1(x_trk_r, y_trk)
    c.wire("metal2", [(x_trk_l, y_trk), (x_trk_l, st_dat_l["ys"])], 0.32)
    c.wire("metal2", [(x_trk_r, y_trk), (x_trk_r, st_dat_r["ys"])], 0.32)

    # 3. hold: Xch.D (yd=0.75) -> M2 across to center dx_c -> straight UP dx_c (M2!) to y=11.05 (Xhp.S & Xhn.S!)
    c.wire("metal2", [(dx_c, st_clk_r["yd"]), (st_clk_r["d_xs"][0], st_clk_r["yd"])], 0.34)
    c.wire("metal2", [(dx_c, st_clk_r["yd"]), (dx_c, st_hld_l["ys"])], 0.32)
    c.wire("metal2", [(st_hld_l["s_xs"][-1], st_hld_l["ys"]), (st_hld_r["s_xs"][0], st_hld_r["ys"])], 0.34)

    # 4. qn (left) & qp (right): M2 along x = dx_c +- 2.56 (outside S straps!) up to XRn/XRp R2 (y_res - 3.435)!
    r_r2 = grid(y_res - 3.435)
    r_r1 = grid(y_res + 3.435)
    x_qn_bus, x_qp_bus = st_dat_l["d_xs"][0], st_dat_r["d_xs"][-1]  # dx_c - 2.56, dx_c + 2.56
    x_rn, x_rp = grid(dx_c - dx_r), grid(dx_c + dx_r)
    c.wire("metal2", [(x_qn_bus, st_dat_l["yd"]), (x_qn_bus, st_hld_l["yd"])], 0.34)
    c.wire("metal2", [(x_rn, st_hld_l["yd"]), (x_rn, r_r2)], 0.36)
    c.via1(x_rn, r_r2)

    c.wire("metal2", [(x_qp_bus, st_dat_r["yd"]), (x_qp_bus, st_hld_r["yd"])], 0.34)
    c.wire("metal2", [(x_rp, st_hld_r["yd"]), (x_rp, r_r2)], 0.36)
    c.via1(x_rp, r_r2)

    # 5. Cross-coupling in inter-row M1 gaps (passing cleanly UNDER M2!):
    #    - qn -> Xhn.G via M1 at y=9.10 (gap between dat top 8.59 & hld bot 9.56!)
    y_xc_qn = 9.080
    c.via1(x_qn_bus, y_xc_qn)
    c.wire("metal1", [(x_qn_bus, y_xc_qn), (grid(dx_c + dx_m), y_xc_qn), (grid(dx_c + dx_m), st_hld_r["gy_b"])], 0.22)
    #    - qp -> Xhp.G via M1 at y=14.35 (gap between hld top 13.84 & res R2 15.165!)
    y_xc_qp = 14.350
    c.via1(x_qp_bus, y_xc_qp)
    c.wire("metal2", [(x_rp, st_hld_r["yd"]), (x_qp_bus, st_hld_r["yd"]), (x_qp_bus, y_xc_qp)], 0.32)
    c.wire("metal1", [(x_qp_bus, y_xc_qp), (grid(dx_c - dx_m), y_xc_qp), (grid(dx_c - dx_m), st_hld_l["gy_t"])], 0.22)

    # 6. Pin exports (M2 over outer M1 guard ring, zero M3/M4!)
    x_port_l = grid(dx_c - 4.275) if export_pins else grid(gx_dp_pt := g_dp[0] - 0.50)
    x_port_r = grid(dx_c + 4.275) if export_pins else grid(g_dn[0] + 0.50)
    # ct, ch, dp, dn -> via1 -> M2 outward
    pts = {}
    for nm, gpt, px in (("ct", g_ct, x_port_l), ("dp", g_dp, x_port_l), ("ch", g_ch, x_port_r), ("dn", g_dn, x_port_r)):
        c.via1(*gpt)
        c.wire("metal2", [gpt, (px, gpt[1])], 0.34)
        pts[nm] = (px, gpt[1])

    # Top VDD bar connecting XRn.R1 & XRp.R1 on M2 (clear over top M1 guard ring!)
    c.via1(x_rn, r_r1); c.via1(x_rp, r_r1)
    c.wire("metal2", [(x_rn, r_r1), (x_rp, r_r1)], 0.44)
    pts["vdd"] = (dx_c, r_r1)
    pts["vss"] = (dx_c, y_vss_gr)
    pts["qn"] = (x_rn, r_r2)
    pts["qp"] = (x_rp, r_r2)

    if export_pins:
        for pnm in ("dp", "dn", "qp", "qn", "ct", "ch", "vdd"):
            c.port(pnm, "metal2", *pts[pnm])
        c.port("vss", "metal1", *pts["vss"])
    return pts


def build_routed_latch(out: Path, pcache: Path) -> dict:
    w = out / "sync2_latch_pdk"
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw = 0.45
    gx1, gy1, gx2, gy2 = -4.275, -4.040, +4.275, +23.310
    route_latch_core(c, pcache, 0.0, gx1, gx2, gy1, gy2, tie_l=True, tie_r=True, y_res=18.600, export_pins=True)
    pb.add_p_guard_ring(c, gx1, gy1, gx2, gy2, rw=rw)
    c.write(w / "sync2_latch_pdk.mag")
    l_res = round((480.0 - 137.6) / 111.8, 3)
    ref = "\n".join([
        ".subckt sync2_latch_pdk dp dn qp qn ct ch vdd vss",
        f"XRp vdd qp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd qn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        "Xdp qn dp track vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15 nf=4",
        "Xdn qp dn track vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15 nf=4",
        "Xhp qn qp hold vss sky130_fd_pr__nfet_01v8_lvt w=14 l=0.15 nf=4",
        "Xhn qp qn hold vss sky130_fd_pr__nfet_01v8_lvt w=14 l=0.15 nf=4",
        "Xct track ct vss vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15 nf=4",
        "Xch hold ch vss vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15 nf=4",
        ".ends sync2_latch_pdk",
        "",
    ])
    return signoff_plot_and_rc(w, "sync2_latch_pdk", ref)


def route_buf_core(
    c: Cell,
    pcache: Path,
    name: str,
    dx_c: float,
    x_gr_l: float,
    x_gr_r: float,
    gy1: float,
    gy2: float,
    wn: float = 24,
    wt: float = 12,
    rload: float = 550,
    export_edges: bool = True,
) -> dict:
    """Place + route one CML buffer core at x=dx_c, returning pin coordinates and net params."""
    p_tail = pb.mos_prim(pcache, f"{name}_tail", "sky130_fd_pr__nfet_01v8", round(wt / 4, 3), 0.5, 4)
    p_in   = pb.mos_prim(pcache, f"{name}_in",   "sky130_fd_pr__nfet_01v8_lvt", round(wn / 4, 3), 0.15, 4)
    l_res  = round((rload - 137.6) / 111.8, 3)
    p_res  = pb.res_prim(pcache, f"{name}_res",  "sky130_fd_pr__res_high_po_2p85", l_res)

    y_tail = 0.000
    y_in   = grid(p_tail.bbox()[3] + 0.90 + p_in.bbox()[3])
    y_res  = grid(y_in + p_in.bbox()[3] + 1.00 + p_res.bbox()[3])

    pb.build_buf_core(c, pcache, name, dx_c, 0.0, wn, wt, rload, x_gr_l, x_gr_r, True, True)
    # Tie center dummy poly (y_in) UPWARD via locali between resistors to top guard ring; Xtail flanking dummies (+-2.025) DOWN to bottom GR
    y_gr_bot_li = grid(gy1 + 0.41)
    y_gr_top_li = grid(gy2 - 0.41)
    c.rect("locali", grid(dx_c - 0.10), grid(y_in - 0.17), grid(dx_c + 0.10), y_gr_top_li)
    c.rect("poly", grid(dx_c - 0.17), grid(y_in - 0.17), grid(dx_c + 0.17), grid(y_in + 0.17))
    c.rect("polycont", grid(dx_c - 0.085), grid(y_in - 0.085), grid(dx_c + 0.085), grid(y_in + 0.085))
    c.rect("locali", grid(dx_c - 0.17), grid(y_in - 0.17), grid(dx_c + 0.17), grid(y_in + 0.17))
    for sgn in (-1.0, +1.0):
        xt_d = grid(dx_c + sgn * (1.725 + 0.30))
        c.rect("poly", grid(xt_d - 0.17), grid(y_tail - 0.17), grid(xt_d + 0.17), grid(y_tail + 0.17))
        c.rect("polycont", grid(xt_d - 0.085), grid(y_tail - 0.085), grid(xt_d + 0.085), grid(y_tail + 0.085))
        c.rect("locali", grid(xt_d - 0.17), y_gr_bot_li, grid(xt_d + 0.17), grid(y_tail + 0.17))

    st_t = strap_compact_fet(c, p_tail, dx_c, y_tail, -0.65, +0.65)
    st_l = strap_compact_fet(c, p_in, grid(dx_c - 1.60), y_in, -0.75, +0.75)
    st_r = strap_compact_fet(c, p_in, grid(dx_c + 1.60), y_in, -0.75, +0.75)

    g_in = add_outer_gate_loop(c, st_l, grid(dx_c - 1.60), -1.0)
    g_ip = add_outer_gate_loop(c, st_r, grid(dx_c + 1.60), +1.0)
    # Xtail gate strap left out to x=dx_c-2.45 (clear of -2.025 dummy locali pad!)
    xb_tap = grid(dx_c - 2.45)
    c.wire("metal1", [(st_t["gx_l"] - 0.10, st_t["gy_b"]), (xb_tap, st_t["gy_b"]), (xb_tap, st_t["gy_t"]), (st_t["gx_l"] - 0.10, st_t["gy_t"])], 0.23)
    c.via1(xb_tap, st_t["gy_b"])

    y_vss_gr = grid(gy1 + 0.225)
    for xs in st_t["s_xs"]:
        c.wire("metal2", [(xs, st_t["ys"]), (xs, y_vss_gr)], 0.34)
        c.via1(xs, y_vss_gr)

    y_br = grid(0.5 * (p_tail.bbox()[3] + y_in - p_in.bbox()[3]))
    c.wire("metal2", [(dx_c, st_t["yd"]), (dx_c, y_br)], 0.34)
    c.via1(dx_c, y_br)
    c.wire("metal1", [(st_l["s_xs"][-1], y_br), (st_r["s_xs"][0], y_br)], 0.28)
    for sx in (st_l["s_xs"][-1], st_r["s_xs"][0]):
        c.via1(sx, y_br)
        c.wire("metal2", [(sx, y_br), (sx, st_l["ys"])], 0.34)

    r_r2, r_r1 = grid(y_res - 3.750), grid(y_res + 3.750)
    xr_l, xr_r = grid(dx_c - 1.75), grid(dx_c + 1.75)
    c.wire("metal2", [(xr_l, st_l["yd"]), (xr_l, r_r2)], 0.36); c.via1(xr_l, r_r2)
    c.wire("metal2", [(xr_r, st_r["yd"]), (xr_r, r_r2)], 0.36); c.via1(xr_r, r_r2)
    c.via1(xr_l, r_r1); c.via1(xr_r, r_r1)
    c.wire("metal2", [(xr_l, r_r1), (xr_r, r_r1)], 0.44)

    c.via1(*g_in)
    c.via1(*g_ip)
    if export_edges:
        c.wire("metal2", [(xb_tap, st_t["gy_b"]), (-4.275, st_t["gy_b"])], 0.34)
        c.wire("metal2", [g_in, (-4.275, g_in[1])], 0.34)
        c.wire("metal2", [g_ip, (+4.275, g_ip[1])], 0.34)
        inp_pt, inn_pt, vb_pt = (-4.275, g_in[1]), (+4.275, g_ip[1]), (-4.275, st_t["gy_b"])
    else:
        inp_pt, inn_pt, vb_pt = g_in, g_ip, (xb_tap, st_t["gy_b"])

    return {
        "inp": inp_pt, "inn": inn_pt,
        "outn": (xr_l, r_r2), "outp": (xr_r, r_r2),
        "vbias": vb_pt, "y_vb": st_t["gy_b"],
        "y_vdd": r_r1, "y_vss": y_vss_gr,
        "l_res": l_res,
    }


def build_routed_buf(out: Path, pcache: Path, name: str = "sync2_buf_out_pdk", wn: float = 24, wt: float = 12, rload: float = 550) -> dict:
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw = 0.45
    gx1, gx2 = -4.275, +4.275
    p_tail = pb.mos_prim(pcache, f"{name}_tail", "sky130_fd_pr__nfet_01v8", round(wt / 4, 3), 0.5, 4)
    l_res  = round((rload - 137.6) / 111.8, 3)
    p_in   = pb.mos_prim(pcache, f"{name}_in",   "sky130_fd_pr__nfet_01v8_lvt", round(wn / 4, 3), 0.15, 4)
    p_res  = pb.res_prim(pcache, f"{name}_res",  "sky130_fd_pr__res_high_po_2p85", l_res)
    y_in   = grid(p_tail.bbox()[3] + 0.90 + p_in.bbox()[3])
    y_res  = grid(y_in + p_in.bbox()[3] + 1.00 + p_res.bbox()[3])
    gy1, gy2 = grid(-p_tail.bbox()[3] - 0.65 - rw), grid(y_res + p_res.bbox()[3] + 0.65 + rw)

    pb.add_p_guard_ring(c, gx1, gy1, gx2, gy2, rw=rw)
    pts = route_buf_core(c, pcache, name, 0.0, grid(gx1 + rw - 0.04), grid(gx2 - rw + 0.04), gy1, gy2, wn, wt, rload, export_edges=True)

    c.port("inp", "metal2", *pts["inp"])
    c.port("inn", "metal2", *pts["inn"])
    c.port("outn", "metal2", *pts["outn"])
    c.port("outp", "metal2", *pts["outp"])
    c.port("vbias", "metal2", *pts["vbias"])
    c.port("vdd", "metal2", 0.0, pts["y_vdd"])
    c.port("vss", "metal1", 0.0, pts["y_vss"])
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} inp inn outp outn vbias vdd vss",
        f"XRp vdd outn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd outp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"Xmp outn inp tail vss sky130_fd_pr__nfet_01v8_lvt w={wn} l=0.15 nf=4",
        f"Xmn outp inn tail vss sky130_fd_pr__nfet_01v8_lvt w={wn} l=0.15 nf=4",
        f"Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w={wt} l=0.5 nf=4",
        f".ends {name}",
        "",
    ])
    return signoff_plot_and_rc(w, name, ref)


def build_routed_buf_bank3(out: Path, pcache: Path) -> dict:
    """Routed 3-column output buffer bank [Xq2 | Xq4 | Xq8] separated by vertical psubdiff walls."""
    name = "sync2_buf_bank3_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw, pitch = 0.45, 8.400
    xs = (-pitch, 0.0, +pitch)
    walls = (-pitch / 2.0, +pitch / 2.0)
    gx1, gx2 = grid(xs[0] - 4.275), grid(xs[-1] + 4.275)
    p_tail = pb.mos_prim(pcache, "b_out_tail", "sky130_fd_pr__nfet_01v8", 3.0, 0.5, 4)
    p_in   = pb.mos_prim(pcache, "b_out_in",   "sky130_fd_pr__nfet_01v8_lvt", 6.0, 0.15, 4)
    l_res  = round((550.0 - 137.6) / 111.8, 3)
    p_res  = pb.res_prim(pcache, "b_out_res",  "sky130_fd_pr__res_high_po_2p85", l_res)
    y_in   = grid(p_tail.bbox()[3] + 0.90 + p_in.bbox()[3])
    y_res  = grid(y_in + p_in.bbox()[3] + 1.00 + p_res.bbox()[3])
    gy1, gy2 = grid(-p_tail.bbox()[3] - 0.65 - rw), grid(y_res + p_res.bbox()[3] + 0.65 + rw)

    pb.add_p_guard_ring(c, gx1, gy1, gx2, gy2, rw=rw)
    for wx in walls:
        pb.add_p_vertical_wall(c, wx, gy1, gy2, rw=rw)

    tags = ("q2", "q4", "q8")
    col_pts = []
    for i, (dx, tag) in enumerate(zip(xs, tags)):
        xl = grid(gx1 + rw - 0.04) if i == 0 else grid(walls[i - 1] + rw / 2.0 - 0.04)
        xr = grid(gx2 - rw + 0.04) if i == 2 else grid(walls[i] - rw / 2.0 + 0.04)
        pts = route_buf_core(c, pcache, "b_out", dx, xl, xr, gy1, gy2, 24, 12, 550, export_edges=False)
        col_pts.append((tag, pts))
        for pnm in ("inp", "inn", "outp", "outn"):
            c.port(f"{tag}_{pnm}", "metal2", *pts[pnm])

    # Shared M3 horizontal vbias bar (jumps cleanly over each column's M2 Xtail.S drops!) & M2 VDD bar
    y_vb, y_vdd, y_vss = col_pts[0][1]["y_vb"], col_pts[0][1]["y_vdd"], col_pts[0][1]["y_vss"]
    for _, pts in col_pts:
        c.via2(*pts["vbias"])
    c.wire("metal3", [(gx1, y_vb), (gx2, y_vb)], 0.36)
    c.wire("metal2", [(grid(xs[0] - 1.75), y_vdd), (grid(xs[-1] + 1.75), y_vdd)], 0.44)
    c.port("vbias", "metal3", gx1, y_vb)
    c.port("vdd", "metal2", 0.0, y_vdd)
    c.port("vss", "metal1", 0.0, y_vss)
    c.write(w / f"{name}.mag")

    pin_list = " ".join(f"{t}_{p}" for t in tags for p in ("inp", "inn", "outp", "outn"))
    ref = [f".subckt {name} {pin_list} vbias vdd vss"]
    for t in tags:
        ref.extend([
            f"XRp_{t} vdd {t}_outn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
            f"XRn_{t} vdd {t}_outp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
            f"Xmp_{t} {t}_outn {t}_inp tail_{t} vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15 nf=4",
            f"Xmn_{t} {t}_outp {t}_inn tail_{t} vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15 nf=4",
            f"Xtail_{t} tail_{t} vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5 nf=4",
        ])
    ref.extend([f".ends {name}", ""])
    return signoff_plot_and_rc(w, name, "\n".join(ref))


def route_mux_core(
    c: Cell,
    pcache: Path,
    dx_c: float,
    x_gr_l: float,
    x_gr_r: float,
    gy1: float,
    gy2: float,
    export_edges: bool = True,
) -> dict:
    """Place + route one 2:1 CML Mux core at x=dx_c, returning pin coordinates."""
    p_tail = pb.mos_prim(pcache, "m_tail", "sky130_fd_pr__nfet_01v8", 3.0, 0.5, 2)
    p_sel  = pb.mos_prim(pcache, "m_sel",  "sky130_fd_pr__nfet_01v8_lvt", 6.0, 0.15, 4)
    p_dat  = pb.mos_prim(pcache, "m_dat",  "sky130_fd_pr__nfet_01v8_lvt", 3.0, 0.15, 4)
    l_res  = round((1100.0 - 137.6) / 111.8, 3)
    p_res  = pb.res_prim(pcache, "m_r1100", "sky130_fd_pr__res_high_po_2p85", l_res)

    y_tail = 0.000
    y_sel  = grid(p_tail.bbox()[3] + 0.90 + p_sel.bbox()[3])
    y_rowa = grid(y_sel + p_sel.bbox()[3] + 0.90 + p_dat.bbox()[3])
    y_rowb = grid(y_rowa + p_dat.bbox()[3] + 0.90 + p_dat.bbox()[3])
    y_res  = grid(y_rowb + p_dat.bbox()[3] + 1.00 + p_res.bbox()[3])

    pb.build_mux_core(c, pcache, dx_c, 0.0, x_gr_l, x_gr_r, True, True)
    # Tie segmented center dummies (y_sel, y_rowa, y_rowb) UPWARD via locali between resistors to top guard ring;
    # Xtail flanking dummies (+-1.235) tie DOWNWARD via locali to bottom guard ring!
    y_gr_bot_li = grid(gy1 + 0.41)
    y_gr_top_li = grid(gy2 - 0.41)
    c.rect("locali", grid(dx_c - 0.10), grid(y_sel - 0.17), grid(dx_c + 0.10), y_gr_top_li)
    for yr in (y_sel, y_rowa, y_rowb):
        c.rect("poly", grid(dx_c - 0.17), grid(yr - 0.17), grid(dx_c + 0.17), grid(yr + 0.17))
        c.rect("polycont", grid(dx_c - 0.085), grid(yr - 0.085), grid(dx_c + 0.085), grid(yr + 0.085))
        c.rect("locali", grid(dx_c - 0.17), grid(yr - 0.17), grid(dx_c + 0.17), grid(yr + 0.17))
    for sgn in (-1.0, +1.0):
        xt_d = grid(dx_c + sgn * (0.935 + 0.30))
        c.rect("poly", grid(xt_d - 0.17), grid(y_tail - 0.17), grid(xt_d + 0.17), grid(y_tail + 0.17))
        c.rect("polycont", grid(xt_d - 0.085), grid(y_tail - 0.085), grid(xt_d + 0.085), grid(y_tail + 0.085))
        c.rect("locali", grid(xt_d - 0.17), y_gr_bot_li, grid(xt_d + 0.17), grid(y_tail + 0.17))

    st_t  = strap_compact_fet(c, p_tail, dx_c, y_tail, -0.65, +0.65)
    st_sl = strap_compact_fet(c, p_sel,  grid(dx_c - 1.60), y_sel,  -0.75, +0.75)
    st_sr = strap_compact_fet(c, p_sel,  grid(dx_c + 1.60), y_sel,  -0.75, +0.75)
    st_al = strap_compact_fet(c, p_dat,  grid(dx_c - 1.60), y_rowa, -0.60, +0.60)
    st_ar = strap_compact_fet(c, p_dat,  grid(dx_c + 1.60), y_rowa, -0.60, +0.60)
    st_bl = strap_compact_fet(c, p_dat,  grid(dx_c - 1.60), y_rowb, -0.60, +0.60)
    st_br = strap_compact_fet(c, p_dat,  grid(dx_c + 1.60), y_rowb, -0.60, +0.60)

    y_vss_gr = grid(gy1 + 0.225)
    for xs in st_t["s_xs"]:
        c.wire("metal2", [(xs, st_t["ys"]), (xs, y_vss_gr)], 0.34)
        c.via1(xs, y_vss_gr)

    y_br0 = grid(0.5 * (p_tail.bbox()[3] + y_sel - p_sel.bbox()[3]))
    c.wire("metal2", [(dx_c, st_t["yd"]), (dx_c, y_br0)], 0.32); c.via1(dx_c, y_br0)
    c.wire("metal1", [(st_sl["s_xs"][-1], y_br0), (st_sr["s_xs"][0], y_br0)], 0.26)
    for sx in (st_sl["s_xs"][-1], st_sr["s_xs"][0]):
        c.via1(sx, y_br0); c.wire("metal2", [(sx, y_br0), (sx, st_sl["ys"])], 0.32)

    y_bra = grid(0.5 * (y_sel + p_sel.bbox()[3] + y_rowa - p_dat.bbox()[3]))
    c.wire("metal2", [(st_sl["d_xs"][-1], st_sl["yd"]), (st_sl["d_xs"][-1], y_bra)], 0.32); c.via1(st_sl["d_xs"][-1], y_bra)
    c.wire("metal1", [(st_al["s_xs"][-1], y_bra), (st_ar["s_xs"][0], y_bra)], 0.26)
    for sx in (st_al["s_xs"][-1], st_ar["s_xs"][0]):
        c.via1(sx, y_bra); c.wire("metal2", [(sx, y_bra), (sx, st_al["ys"])], 0.32)

    c.wire("metal2", [(dx_c, st_sr["yd"]), (st_sr["d_xs"][0], st_sr["yd"])], 0.32)
    c.wire("metal2", [(dx_c, st_sr["yd"]), (dx_c, st_bl["ys"])], 0.32)
    c.wire("metal2", [(st_bl["s_xs"][-1], st_bl["ys"]), (st_br["s_xs"][0], st_br["ys"])], 0.32)

    r_r2, r_r1 = grid(y_res - 6.210), grid(y_res + 6.210)
    xr_l, xr_r = grid(dx_c - 1.75), grid(dx_c + 1.75)
    c.wire("metal2", [(st_al["d_xs"][0], st_al["yd"]), (st_bl["d_xs"][0], st_bl["yd"])], 0.34)
    c.wire("metal2", [(xr_l, st_bl["yd"]), (xr_l, r_r2)], 0.36); c.via1(xr_l, r_r2)
    c.wire("metal2", [(st_ar["d_xs"][-1], st_ar["yd"]), (st_br["d_xs"][-1], st_br["yd"])], 0.34)
    c.wire("metal2", [(xr_r, st_br["yd"]), (xr_r, r_r2)], 0.36); c.via1(xr_r, r_r2)
    c.via1(xr_l, r_r1); c.via1(xr_r, r_r1)
    c.wire("metal2", [(xr_l, r_r1), (xr_r, r_r1)], 0.44)

    xb_tap = grid(dx_c - 1.80)
    c.wire("metal1", [(st_t["gx_l"] - 0.10, st_t["gy_b"]), (xb_tap, st_t["gy_b"]), (xb_tap, st_t["gy_t"]), (st_t["gx_l"] - 0.10, st_t["gy_t"])], 0.23)
    c.via1(xb_tap, st_t["gy_b"])
    if export_edges:
        c.wire("metal2", [(xb_tap, st_t["gy_b"]), (-4.275, st_t["gy_b"])], 0.34)

    pts = {}
    for nm, st, sgn, loff in (
        ("sn", st_sl, -1.0, 1.40), ("sp", st_sr, +1.0, 1.40),
        ("ap", st_al, -1.0, 1.40), ("an", st_ar, +1.0, 1.40),
        ("bp", st_bl, -1.0, 1.54), ("bn", st_br, +1.0, 1.54),
    ):
        g_pt = add_outer_gate_loop(c, st, grid(dx_c + sgn * 1.60), sgn, loop_off=loff)
        c.via1(*g_pt)
        if export_edges:
            px = -4.275 if sgn < 0 else +4.275
            c.wire("metal2", [g_pt, (px, g_pt[1])], 0.34)
            pts[nm] = (px, g_pt[1])
        else:
            pts[nm] = g_pt
    pts["qn"] = (xr_l, r_r2)
    pts["qp"] = (xr_r, r_r2)
    pts["vbias"] = (-4.275, st_t["gy_b"]) if export_edges else (xb_tap, st_t["gy_b"])
    pts["y_vb"] = st_t["gy_b"]
    pts["y_vdd"] = r_r1
    pts["y_vss"] = y_vss_gr
    pts["l_res"] = l_res
    return pts


def build_routed_mux2(out: Path, pcache: Path) -> dict:
    name = "sync2_mux2_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw = 0.45
    gx1, gx2 = -4.275, +4.275
    p_tail = pb.mos_prim(pcache, "m_tail", "sky130_fd_pr__nfet_01v8", 3.0, 0.5, 2)
    p_sel  = pb.mos_prim(pcache, "m_sel",  "sky130_fd_pr__nfet_01v8_lvt", 6.0, 0.15, 4)
    p_dat  = pb.mos_prim(pcache, "m_dat",  "sky130_fd_pr__nfet_01v8_lvt", 3.0, 0.15, 4)
    l_res  = round((1100.0 - 137.6) / 111.8, 3)
    p_res  = pb.res_prim(pcache, "m_r1100", "sky130_fd_pr__res_high_po_2p85", l_res)
    y_sel  = grid(p_tail.bbox()[3] + 0.90 + p_sel.bbox()[3])
    y_rowa = grid(y_sel + p_sel.bbox()[3] + 0.90 + p_dat.bbox()[3])
    y_rowb = grid(y_rowa + p_dat.bbox()[3] + 0.90 + p_dat.bbox()[3])
    y_res  = grid(y_rowb + p_dat.bbox()[3] + 1.00 + p_res.bbox()[3])
    gy1, gy2 = grid(-p_tail.bbox()[3] - 0.65 - rw), grid(y_res + p_res.bbox()[3] + 0.65 + rw)

    pb.add_p_guard_ring(c, gx1, gy1, gx2, gy2, rw=rw)
    pts = route_mux_core(c, pcache, 0.0, grid(gx1 + rw - 0.04), grid(gx2 - rw + 0.04), gy1, gy2, export_edges=True)
    for pnm in ("ap", "an", "bp", "bn", "sp", "sn", "qp", "qn", "vbias"):
        c.port(pnm, "metal2", *pts[pnm])
    c.port("vdd", "metal2", 0.0, pts["y_vdd"])
    c.port("vss", "metal1", 0.0, pts["y_vss"])
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} ap an bp bn sp sn qp qn vbias vdd vss",
        f"XRp vdd qp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd qn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        "Xap qn ap ta vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
        "Xan qp an ta vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
        "Xbp qn bp tb vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
        "Xbn qp bn tb vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
        "Xsa ta sn tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15 nf=4",
        "Xsb tb sp tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15 nf=4",
        "Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w=6 l=0.5 nf=2",
        f".ends {name}",
        "",
    ])
    return signoff_plot_and_rc(w, name, ref)


def build_routed_mux_bank3(out: Path, pcache: Path) -> dict:
    """Routed 3-column CML 2:1 mux bank [Xx1 | Xt2 | Xx2] separated by vertical psubdiff walls."""
    name = "sync2_mux_bank3_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw, pitch = 0.45, 8.400
    xs = (-pitch, 0.0, +pitch)
    walls = (-pitch / 2.0, +pitch / 2.0)
    gx1, gx2 = grid(xs[0] - 4.275), grid(xs[-1] + 4.275)
    p_tail = pb.mos_prim(pcache, "m_tail", "sky130_fd_pr__nfet_01v8", 3.0, 0.5, 2)
    p_sel  = pb.mos_prim(pcache, "m_sel",  "sky130_fd_pr__nfet_01v8_lvt", 6.0, 0.15, 4)
    p_dat  = pb.mos_prim(pcache, "m_dat",  "sky130_fd_pr__nfet_01v8_lvt", 3.0, 0.15, 4)
    l_res  = round((1100.0 - 137.6) / 111.8, 3)
    p_res  = pb.res_prim(pcache, "m_r1100", "sky130_fd_pr__res_high_po_2p85", l_res)
    y_sel  = grid(p_tail.bbox()[3] + 0.90 + p_sel.bbox()[3])
    y_rowa = grid(y_sel + p_sel.bbox()[3] + 0.90 + p_dat.bbox()[3])
    y_rowb = grid(y_rowa + p_dat.bbox()[3] + 0.90 + p_dat.bbox()[3])
    y_res  = grid(y_rowb + p_dat.bbox()[3] + 1.00 + p_res.bbox()[3])
    gy1, gy2 = grid(-p_tail.bbox()[3] - 0.65 - rw), grid(y_res + p_res.bbox()[3] + 0.65 + rw)

    pb.add_p_guard_ring(c, gx1, gy1, gx2, gy2, rw=rw)
    for wx in walls:
        pb.add_p_vertical_wall(c, wx, gy1, gy2, rw=rw)

    tags = ("x1", "t2", "x2")
    col_pts = []
    for i, (dx, tag) in enumerate(zip(xs, tags)):
        xl = grid(gx1 + rw - 0.04) if i == 0 else grid(walls[i - 1] + rw / 2.0 - 0.04)
        xr = grid(gx2 - rw + 0.04) if i == 2 else grid(walls[i] - rw / 2.0 + 0.04)
        pts = route_mux_core(c, pcache, dx, xl, xr, gy1, gy2, export_edges=False)
        col_pts.append((tag, pts))
        for pnm in ("ap", "an", "bp", "bn", "sp", "sn", "qp", "qn"):
            c.port(f"{tag}_{pnm}", "metal2", *pts[pnm])

    y_vb, y_vdd, y_vss = col_pts[0][1]["y_vb"], col_pts[0][1]["y_vdd"], col_pts[0][1]["y_vss"]
    for _, pts in col_pts:
        c.via2(*pts["vbias"])
    c.wire("metal3", [(gx1, y_vb), (gx2, y_vb)], 0.36)
    c.wire("metal2", [(grid(xs[0] - 1.75), y_vdd), (grid(xs[-1] + 1.75), y_vdd)], 0.44)
    c.port("vbias", "metal3", gx1, y_vb)
    c.port("vdd", "metal2", 0.0, y_vdd)
    c.port("vss", "metal1", 0.0, y_vss)
    c.write(w / f"{name}.mag")

    pin_list = " ".join(f"{t}_{p}" for t in tags for p in ("ap", "an", "bp", "bn", "sp", "sn", "qp", "qn"))
    ref = [f".subckt {name} {pin_list} vbias vdd vss"]
    for t in tags:
        ref.extend([
            f"XRp_{t} vdd {t}_qp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
            f"XRn_{t} vdd {t}_qn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
            f"Xap_{t} {t}_qn {t}_ap ta_{t} vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
            f"Xan_{t} {t}_qp {t}_an ta_{t} vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
            f"Xbp_{t} {t}_qn {t}_bp tb_{t} vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
            f"Xbn_{t} {t}_qp {t}_bn tb_{t} vss sky130_fd_pr__nfet_01v8_lvt w=12 l=0.15 nf=4",
            f"Xsa_{t} ta_{t} {t}_sn tail_{t} vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15 nf=4",
            f"Xsb_{t} tb_{t} {t}_sp tail_{t} vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15 nf=4",
            f"Xtail_{t} tail_{t} vbias vss vss sky130_fd_pr__nfet_01v8 w=6 l=0.5 nf=2",
        ])
    ref.extend([f".ends {name}", ""])
    return signoff_plot_and_rc(w, name, "\n".join(ref))


def build_routed_dff(out: Path, pcache: Path) -> dict:
    """Route compact side-by-side DFF ([Master | Xseed | Slave]): local M1/M2 inside latches + clean M3 clock cross-bars."""
    name = "sync2_dff_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw = 0.45
    dx_l = 4.300
    gx1, gy1, gx2, gy2 = grid(-dx_l - 3.175 - 0.65 - rw), -4.040, grid(+dx_l + 3.175 + 0.65 + rw), +23.310
    p_m = route_latch_core(c, pcache, -dx_l, gx1, gx2, gy1, gy2, tie_l=True, tie_r=False, y_res=18.600, export_pins=False)
    p_s = route_latch_core(c, pcache, +dx_l, gx1, gx2, gy1, gy2, tie_l=False, tie_r=True, y_res=18.600, export_pins=False)
    # Also tie Master outer-right & Slave outer-left dummy poly strips at x=+-1.295 via localispine down to bottom GR!
    y_gr_li = grid(gy1 + 0.41)
    for xd_m in (-1.295, +1.295):
        c.rect("locali", grid(xd_m - 0.10), y_gr_li, grid(xd_m + 0.10), 11.87)
        for yr in (0.0, 6.2, 11.7):
            c.rect("poly", grid(xd_m - 0.17), grid(yr - 0.17), grid(xd_m + 0.17), grid(yr + 0.17))
            c.rect("polycont", grid(xd_m - 0.085), grid(yr - 0.085), grid(xd_m + 0.085), grid(yr + 0.085))
            c.rect("locali", grid(xd_m - 0.17), grid(yr - 0.17), grid(xd_m + 0.17), grid(yr + 0.17))

    # Xseed at (0.0, 18.600)
    p_seed = pb.mos_prim(pcache, "seed", "sky130_fd_pr__nfet_01v8", 1.0, 0.5, 1)
    c.include(p_seed, dx=0.0, dy=18.600)
    pb.add_p_guard_ring(c, gx1, gy1, gx2, gy2, rw=rw)

    # Wire Xseed: D/S (-0.395, +0.395, 18.6) -> M1 bridge out to x=+0.65 (0.17um clear of top gate strap, under M2 VDD) -> top GR = VSS;
    # Gate (0.0, 18.6-0.775 = 17.825) -> via1 -> M2 left to Master qp (-2.55, 15.165)
    c.wire("metal1", [(-0.395, 18.6), (+0.78, 18.6), (+0.78, grid(gy2 - 0.225))], 0.22)
    c.via1(0.0, 17.825)
    c.wire("metal2", [(0.0, 17.825), (p_m["qp"][0], 17.825), p_m["qp"]], 0.32)

    # Connect Master & Slave top VDD (y=22.035 M2) across x=0
    c.wire("metal2", [p_m["vdd"], p_s["vdd"]], 0.44)

    # Master -> Slave data bridges:
    #   mp (Master qp: -2.55, 15.165) -> Slave dp (+0.80, 4.70) via x=-0.25 (clear of p_m["dn"] at -0.80 & Xseed at x=0!)
    c.wire("metal2", [p_m["qp"], (-0.25, p_m["qp"][1]), (-0.25, p_s["dp"][1]), p_s["dp"]], 0.32)

    #   mn (Master qn: -6.05, 15.165) -> Slave dn (+7.80, 3.975): hop on M3 at y=14.35 cleanly BELOW all 4 ppolyres bodies!
    y_mn_b = 14.350
    c.via2(p_m["qn"][0], y_mn_b)
    c.wire("metal3", [(p_m["qn"][0], y_mn_b), (p_s["dn"][0], y_mn_b)], 0.34)
    c.via2(p_s["dn"][0], y_mn_b)
    c.wire("metal2", [(p_s["dn"][0], y_mn_b), p_s["dn"]], 0.32)

    # Clock buses ckp (Master ct + Slave ch) & ckn (Master ch + Slave ct): rise on M2 FIRST, then single via2 at bus y -> zero M3 crossing!
    y_ckp, y_ckn = -0.900, -2.100
    for pt in (p_m["ct"], p_s["ch"]):
        c.wire("metal2", [pt, (pt[0], y_ckp)], 0.32)
        c.via2(pt[0], y_ckp)
    c.wire("metal3", [(gx1, y_ckp), (gx2, y_ckp)], 0.36)

    for pt in (p_m["ch"], p_s["ct"]):
        c.wire("metal2", [pt, (pt[0], y_ckn)], 0.32)
        c.via2(pt[0], y_ckn)
    c.wire("metal3", [(gx1, y_ckn), (gx2, y_ckn)], 0.36)

    # Export dp, dn (offset dn M3 down to y=3.225 off-axis from dp M2 @ 3.975 to reduce dp/dn Miller coupling!), qp, qn, ckp, ckn, vdd, vss
    c.port("dp", "metal2", gx1, p_m["dp"][1])
    c.wire("metal2", [p_m["dp"], (gx1, p_m["dp"][1])], 0.34)
    y_dn = 3.225
    c.wire("metal2", [p_m["dn"], (p_m["dn"][0], y_dn)], 0.32)
    c.via2(p_m["dn"][0], y_dn)
    c.wire("metal3", [(p_m["dn"][0], y_dn), (gx1, y_dn)], 0.34)
    c.port("dn", "metal3", gx1, y_dn)
    c.port("qp", "metal2", *p_s["qp"])
    c.port("qn", "metal2", *p_s["qn"])
    c.port("ckp", "metal3", gx1, y_ckp)
    c.port("ckn", "metal3", gx1, y_ckn)
    c.port("vdd", "metal2", 0.0, p_m["vdd"][1])
    c.port("vss", "metal1", 0.0, grid(gy1 + 0.225))
    c.write(w / f"{name}.mag")

    l_res = round((480.0 - 137.6) / 111.8, 3)
    ref = "\n".join([
        ".subckt sync2_latch_pdk dp dn qp qn ct ch vdd vss",
        f"XRp vdd qp vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        f"XRn vdd qn vss sky130_fd_pr__res_high_po_2p85 l={l_res}",
        "Xdp qn dp track vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15 nf=4",
        "Xdn qp dn track vss sky130_fd_pr__nfet_01v8_lvt w=16 l=0.15 nf=4",
        "Xhp qn qp hold vss sky130_fd_pr__nfet_01v8_lvt w=14 l=0.15 nf=4",
        "Xhn qp qn hold vss sky130_fd_pr__nfet_01v8_lvt w=14 l=0.15 nf=4",
        "Xct track ct vss vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15 nf=4",
        "Xch hold ch vss vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15 nf=4",
        ".ends sync2_latch_pdk",
        "",
        f".subckt {name} dp dn qp qn ckp ckn vdd vss",
        "Xm dp dn mp mn ckp ckn vdd vss sync2_latch_pdk",
        "Xs mp mn qp qn ckn ckp vdd vss sync2_latch_pdk",
        "Xseed vss mp vss vss sky130_fd_pr__nfet_01v8 w=1.0 l=0.5 nf=1",
        f".ends {name}",
        "",
    ])
    return signoff_plot_and_rc(w, name, ref)


def build_routed_ck_frontend(out: Path, pcache: Path) -> dict:
    """Route active-only mirror-symmetric clock front-end (4-strip 2k Xrbp/Xrbn + Xckpre + Xckdrv)."""
    name = "sync2_ck_frontend_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw = 0.45

    p_t12  = pb.mos_prim(pcache, "fe_t12", "sky130_fd_pr__nfet_01v8", 3.0, 0.5, 4)
    p_in20 = pb.mos_prim(pcache, "fe_i20", "sky130_fd_pr__nfet_01v8_lvt", 5.0, 0.15, 4)
    p_in32 = pb.mos_prim(pcache, "fe_i32", "sky130_fd_pr__nfet_01v8_lvt", 8.0, 0.15, 4)
    l_850  = round((850.0 - 137.6) / 111.8, 3)
    l_550  = round((550.0 - 137.6) / 111.8, 3)
    l_2k   = round((2000.0 - 256.0) / 230.04, 3)
    p_r850 = pb.res_prim(pcache, "fe_r850", "sky130_fd_pr__res_high_po_2p85", l_850)
    p_r550 = pb.res_prim(pcache, "fe_r550", "sky130_fd_pr__res_high_po_2p85", l_550)
    p_r2k  = pb.res_prim(pcache, "fe_r2k",  "sky130_fd_pr__res_high_po_1p41", l_2k)

    y_tail = 0.000
    for xt in (-5.350, 0.000, +5.350):
        c.include(p_t12, dx=xt, dy=y_tail)
        pb.add_single_dummies(c, p_t12, xt, y_tail)

    y_in_pre = grid(p_t12.bbox()[3] + 1.35 + p_in20.bbox()[3])
    y_in_drv = grid(p_t12.bbox()[3] + 1.35 + p_in32.bbox()[3])
    for sgn in (-1.0, +1.0):
        c.include(p_in20, dx=grid(sgn * 1.650), dy=y_in_pre)
        c.include(p_in32, dx=grid(sgn * 5.350), dy=y_in_drv)

    y_row3_bot = grid(y_in_drv + p_in32.bbox()[3] + 1.40)
    y_r850 = grid(y_row3_bot + p_r850.bbox()[3])
    y_r550 = grid(y_row3_bot + p_r550.bbox()[3])
    for sgn in (-1.0, +1.0):
        c.include(p_r850, dx=grid(sgn * 1.750), dy=y_r850)
        c.include(p_r550, dx=grid(sgn * 5.450), dy=y_r550)

    gx1 = grid(-8.450)
    gx2 = grid(+8.450)
    gy1_b = grid(-p_t12.bbox()[3] - 1.15 - rw)
    x_edge_l, x_edge_r = grid(gx1 + rw - 0.04), grid(gx2 - rw + 0.04)
    pb.add_pair_dummies(c, p_in20, 0.0, y_in_pre, 1.650, x_edge_l, x_edge_r, tie_outer_l=False, tie_outer_r=False)
    for sgn in (-1.0, +1.0):
        diff_y = max(r[3] for r in p_in32.rects["ndiff"])
        for xo in (grid(sgn * 3.900), grid(sgn * (5.350 + 1.105 + 0.30))):
            c.rect("poly", grid(xo - 0.075), grid(y_in_drv - diff_y - 0.20), grid(xo + 0.075), grid(y_in_drv + diff_y + 0.20))

    # Top 4-strip common-centroid 2k bias resistor bank inside SAME unified P-guard ring (no redundant inner r2k ring!)
    y_r850_top = grid(y_r850 + p_r850.bbox()[3])
    y_r2k = grid(y_r850_top + 1.30 + p_r2k.bbox()[3])
    pitch_2k = 2.050
    for idx in (1, 2, 3, 4):
        c.include(p_r2k, dx=grid((idx - 2.5) * pitch_2k), dy=y_r2k)
    y_poly = max(r[3] for r in p_r2k.rects["xpolycontact"])
    y_res = max(r[3] for r in p_r2k.rects["ppolyres"])
    r2k_gy2 = grid(y_r2k + p_r2k.bbox()[3] + 0.65 + rw)
    for idx, x_gr in ((0, x_edge_l), (5, x_edge_r)):
        xd = grid((idx - 2.5) * pitch_2k)
        c.rect("poly", grid(xd - 0.705), grid(y_r2k - y_poly), grid(xd + 0.705), grid(y_r2k + y_poly))
        c.rect("polycont", grid(xd - 0.500), grid(y_r2k + y_res + 0.30), grid(xd + 0.500), grid(y_r2k + y_poly - 0.30))
        c.rect("polycont", grid(xd - 0.500), grid(y_r2k - y_poly + 0.30), grid(xd + 0.500), grid(y_r2k - y_res - 0.30))
        c.rect("locali", grid(xd - 0.705), grid(y_r2k + y_res), grid(xd + 0.705), grid(y_r2k + y_poly))
        c.rect("locali", grid(xd - 0.705), grid(y_r2k - y_poly), grid(xd + 0.705), grid(y_r2k - y_res))
        # Tie outer dummy locali directly out to unified outer guard ring locali at BOTH top & bottom pads
        c.rect("locali", min(grid(xd), x_gr), grid(y_r2k + y_res + 0.20), max(grid(xd), x_gr), grid(y_r2k + y_poly - 0.20))
        c.rect("locali", min(grid(xd), x_gr), grid(y_r2k - y_poly + 0.20), max(grid(xd), x_gr), grid(y_r2k - y_res - 0.20))
    pb.add_p_guard_ring(c, gx1, gy1_b, gx2, r2k_gy2, rw=rw)

    # Tie inner & outer dummy poly cleanly in unified P-well (float_a = 0):
    y_bot_li_b = grid(gy1_b + 0.41)
    y_top_li_b = grid(r2k_gy2 - 0.41)
    y_t_tie = grid(-p_t12.bbox()[3] - 0.45)  # -2.390: well below p_t12 poly (-1.94) & ndiff (-1.50)
    y_pre_tie = grid(y_in_pre + p_in20.bbox()[3] + 0.45)   # 9.620: above p_in20 poly (9.17)
    y_drv_tie = grid(y_in_drv + p_in32.bbox()[3] + 0.45)   # 12.620: above p_in32 poly (12.17), below r850/r550
    c.rect("locali", -0.10, grid(y_in_pre - 0.17), +0.10, y_top_li_b)
    c.rect("poly", -0.17, grid(y_in_pre - 0.17), +0.17, grid(y_in_pre + 0.17))
    c.rect("polycont", -0.085, grid(y_in_pre - 0.085), +0.085, grid(y_in_pre + 0.085))
    c.rect("locali", -0.17, grid(y_in_pre - 0.17), +0.17, grid(y_in_pre + 0.17))
    for xt_d in (-7.375, -3.325, -2.025, +2.025, +3.325, +7.375):
        c.rect("poly", grid(xt_d - 0.075), grid(y_t_tie - 0.17), grid(xt_d + 0.075), grid(y_tail))
        c.rect("poly", grid(xt_d - 0.17), grid(y_t_tie - 0.17), grid(xt_d + 0.17), grid(y_t_tie + 0.17))
        c.rect("polycont", grid(xt_d - 0.085), grid(y_t_tie - 0.085), grid(xt_d + 0.085), grid(y_t_tie + 0.085))
        c.rect("locali", grid(xt_d - 0.17), y_bot_li_b, grid(xt_d + 0.17), grid(y_t_tie + 0.17))
    for sgn, x_gr in ((-1.0, x_edge_l), (+1.0, x_edge_r)):
        xo = grid(sgn * (5.350 + 1.105 + 0.30))
        c.rect("poly", grid(xo - 0.075), grid(y_in_drv), grid(xo + 0.075), grid(y_drv_tie + 0.17))
        c.rect("poly", grid(xo - 0.17), grid(y_drv_tie - 0.17), grid(xo + 0.17), grid(y_drv_tie + 0.17))
        c.rect("polycont", grid(xo - 0.085), grid(y_drv_tie - 0.085), grid(xo + 0.085), grid(y_drv_tie + 0.085))
        c.rect("locali", min(grid(xo - 0.17), x_gr), grid(y_drv_tie - 0.17), max(grid(xo + 0.17), x_gr), grid(y_drv_tie + 0.17))
        # Xpre outer (+-3.055) & Xdrv inner (+-3.900) -> meet @ y_drv_tie into x=+-3.60 (clear r850/r550) -> at y=24.6 jog to x=+-4.10 (between P1/P2 & Dum_L/R) -> top GR
        x_sp = grid(sgn * 3.600)
        x_sp2 = grid(sgn * 4.100)
        x_po = grid(sgn * 3.055)
        x_di = grid(sgn * 3.900)
        c.rect("poly", grid(x_po - 0.075), grid(y_in_pre), grid(x_po + 0.075), grid(y_pre_tie + 0.17))
        c.rect("poly", grid(x_po - 0.17), grid(y_pre_tie - 0.17), grid(x_po + 0.17), grid(y_pre_tie + 0.17))
        c.rect("polycont", grid(x_po - 0.085), grid(y_pre_tie - 0.085), grid(x_po + 0.085), grid(y_pre_tie + 0.085))
        c.rect("locali", grid(x_po - 0.17), grid(y_pre_tie - 0.17), grid(x_po + 0.17), grid(y_drv_tie + 0.17))
        c.rect("poly", grid(x_di - 0.075), grid(y_in_drv), grid(x_di + 0.075), grid(y_drv_tie + 0.17))
        c.rect("poly", grid(x_di - 0.17), grid(y_drv_tie - 0.17), grid(x_di + 0.17), grid(y_drv_tie + 0.17))
        c.rect("polycont", grid(x_di - 0.085), grid(y_drv_tie - 0.085), grid(x_di + 0.085), grid(y_drv_tie + 0.085))
        c.rect("locali", min(x_po, x_di) - 0.17, grid(y_drv_tie - 0.17), max(x_po, x_di) + 0.17, grid(y_drv_tie + 0.17))
        c.rect("locali", grid(x_sp - 0.10), grid(y_drv_tie - 0.17), grid(x_sp + 0.10), 24.700)
        c.rect("locali", min(x_sp, x_sp2) - 0.10, 24.500, max(x_sp, x_sp2) + 0.10, 24.700)
        c.rect("locali", grid(x_sp2 - 0.10), 24.500, grid(x_sp2 + 0.10), y_top_li_b)

    # Strap FET terminals
    st_tdl = strap_compact_fet(c, p_t12, -5.350, y_tail, -0.65, +0.65)
    st_tp  = strap_compact_fet(c, p_t12,  0.000, y_tail, -0.65, +0.65)
    st_tdr = strap_compact_fet(c, p_t12, +5.350, y_tail, -0.65, +0.65)
    st_ip  = strap_compact_fet(c, p_in20, -1.650, y_in_pre, -1.00, +1.00)
    st_in  = strap_compact_fet(c, p_in20, +1.650, y_in_pre, -1.00, +1.00)
    st_dl  = strap_compact_fet(c, p_in32, -5.350, y_in_drv, -1.50, +1.50)
    st_dr  = strap_compact_fet(c, p_in32, +5.350, y_in_drv, -1.50, +1.50)

    # 1. VSS: all 3 tail S -> M2 down to bottom guard ring + M1 bridges between bottom & top guard rings
    y_vss_gr = grid(gy1_b + 0.225)
    for st in (st_tdl, st_tp, st_tdr):
        for xs in st["s_xs"]:
            c.wire("metal2", [(xs, st["ys"]), (xs, y_vss_gr)], 0.34)
            c.via1(xs, y_vss_gr)
    for xv in (-6.00, +6.00):
        pass  # Unified outer P-guard ring replaces redundant inner r2k ring

    # 2. vbias: continuous M1 horizontal across all 3 tail bottom gates -> step down-left to (-7.05, -2.20) clear of D0/GR! -> via1 -> M2 left
    c.wire("metal1", [(st_tdl["gx_l"] - 0.14, st_tp["gy_b"]), (st_tdr["gx_r"] + 0.14, st_tp["gy_b"])], 0.23)
    c.wire("metal1", [(st_tdl["gx_l"] - 0.14, st_tp["gy_b"]), (-7.05, st_tp["gy_b"]), (-7.05, -2.20)], 0.23)
    c.via1(-7.05, -2.20)
    c.wire("metal2", [(-7.05, -2.20), (-12.000, -2.20)], 0.34)

    # 3. tail_pre (x=0 -> M1 y=2.95 -> Xmp_pre.S -1.17 & Xmn_pre.S +1.17) and
    #    tail_drv (M1 across [-5.83..+5.83] y=2.30 -> both clear >= 0.25um across 1.50um inter-row channel!)
    y_br_pre, y_br_drv = 2.920, 2.300
    c.wire("metal2", [(0.0, st_tp["yd"]), (0.0, y_br_pre)], 0.34); c.via1(0.0, y_br_pre)
    c.wire("metal1", [(st_ip["s_xs"][-1], y_br_pre), (st_in["s_xs"][0], y_br_pre)], 0.24)
    for sx in (st_ip["s_xs"][-1], st_in["s_xs"][0]):
        c.via1(sx, y_br_pre); c.wire("metal2", [(sx, y_br_pre), (sx, st_ip["ys"])], 0.32)

    c.wire("metal1", [(st_dl["s_xs"][0], y_br_drv), (st_dr["s_xs"][-1], y_br_drv)], 0.24)
    for xdrv, st_d, sx_t in ((-5.350, st_dl, st_dl["s_xs"][0]), (+5.350, st_dr, st_dr["s_xs"][-1])):
        c.wire("metal2", [(xdrv, st_tp["yd"]), (xdrv, y_br_drv)], 0.34); c.via1(xdrv, y_br_drv)
        c.via1(sx_t, y_br_drv); c.wire("metal2", [(sx_t, y_br_drv), (sx_t, st_d["ys"])], 0.34)

    # 4. Preamp drains (ck_mid_n @ -1.75, ck_mid_p @ +1.75) -> R2 (12.905) & M2 over to Xdrv gates (extend M1 to +-3.90 clear of ndiffc!)
    r850_r2, r850_r1 = grid(y_r850 - 5.090), grid(y_r850 + 5.090)
    r550_r2, r550_r1 = grid(y_r550 - 3.750), grid(y_r550 + 3.750)
    c.wire("metal2", [(-1.650, st_ip["yd"]), (-1.750, st_ip["yd"]), (-1.750, r850_r2)], 0.34); c.via1(-1.750, r850_r2)
    c.wire("metal2", [(+1.650, st_in["yd"]), (+1.750, st_in["yd"]), (+1.750, r850_r2)], 0.34); c.via1(+1.750, r850_r2)
    c.wire("metal1", [(-4.630, st_dl["gy_t"]), (-3.900, st_dl["gy_t"])], 0.23)
    c.via1(-3.900, st_dl["gy_t"]); c.wire("metal2", [(-3.900, st_dl["gy_t"]), (-1.750, st_dl["gy_t"])], 0.32)
    c.wire("metal1", [(+4.630, st_dr["gy_t"]), (+3.900, st_dr["gy_t"])], 0.23)
    c.via1(+3.900, st_dr["gy_t"]); c.wire("metal2", [(+3.900, st_dr["gy_t"]), (+1.750, st_dr["gy_t"])], 0.32)

    # 5. Driver drains (ck_pre_p @ -5.45, ck_pre_n @ +5.45) -> R2 (12.905)
    c.wire("metal2", [(-5.350, st_dl["yd"]), (-5.450, st_dl["yd"]), (-5.450, r550_r2)], 0.36); c.via1(-5.450, r550_r2)
    c.wire("metal2", [(+5.350, st_dr["yd"]), (+5.450, st_dr["yd"]), (+5.450, r550_r2)], 0.36); c.via1(+5.450, r550_r2)

    # 6. Top VDD bar connecting XR_drv.R1 (+-5.45) & XR_pre.R1 (+-1.75) on M2,
    # then M1 step @ (+7.20, 10.60) -> M2 out past elongated Xccn (+12.15) and straight UP to y_vdd_top
    for xr, rr1 in ((-5.450, r550_r1), (-1.750, r850_r1), (+1.750, r850_r1), (+5.450, r550_r1)):
        c.via1(xr, rr1)
        if rr1 < r850_r1:
            c.wire("metal2", [(xr, rr1), (xr, r850_r1)], 0.38)
    c.wire("metal2", [(-5.450, r850_r1), (+5.450, r850_r1)], 0.44)
    c.via1(+5.450, r850_r1)
    y_r2k_top = grid(y_r2k + 5.695)
    y_vdd_top = grid(r2k_gy2 - 0.225)
    c.wire("metal1", [(+5.450, r850_r1), (+7.200, r850_r1), (+7.200, 10.600)], 0.36)
    c.via1(+7.200, 10.600)
    c.wire("metal2", [(+7.200, 10.600), (+12.150, 10.600), (+12.150, y_vdd_top)], 0.44)

    # 7. clkp / clkn inputs (extend Xpre top gate M1 out to +-3.10 clear of Xpre.D0 +-2.61 -> via1 -> via2 -> M3 outward to +-12.00!)
    for pnm, g_in_x, xp_out, gx_out in (("clkp", -2.370, -3.100, -12.000), ("clkn", +2.370, +3.100, +12.000)):
        c.wire("metal1", [(g_in_x, st_ip["gy_t"]), (xp_out, st_ip["gy_t"])], 0.23)
        c.via1(xp_out, st_ip["gy_t"]); c.via2(xp_out, st_ip["gy_t"])
        c.wire("metal3", [(xp_out, st_ip["gy_t"]), (gx_out, st_ip["gy_t"])], 0.36)
        c.port(pnm, "metal3", gx_out, st_ip["gy_t"])

    # 8. Top 4-strip 2k bias resistors: [P1(-3.075) | N1(-1.025) | N2(+1.025) | P2(+3.075)]
    r2k_bot, r2k_top = grid(y_r2k - 5.695), grid(y_r2k + 5.695)
    xp1, xn1, xn2, xp2 = (grid((idx - 2.5) * pitch_2k) for idx in (1, 2, 3, 4))
    # N series on M1 top; P series on M2 top
    c.wire("metal1", [(xn1, r2k_top), (xn2, r2k_top)], 0.34)
    c.via1(xp1, r2k_top); c.via1(xp2, r2k_top)
    c.wire("metal2", [(xp1, r2k_top), (xp2, r2k_top)], 0.34)
    # Bottom: N2 & P2 -> vbias_ck (M2 right to +5.95, up to y_vb_top, left to -12.00); P1=ckp; N1=ckn
    c.wire("metal1", [(xn2, r2k_bot), (xp2, r2k_bot)], 0.34)
    c.via1(xp2, r2k_bot)
    y_vb_top = grid(r2k_top + 0.75)
    c.wire("metal2", [(xp2, r2k_bot), (+5.950, r2k_bot), (+5.950, y_vb_top), (-12.000, y_vb_top)], 0.34)
    c.via1(xp1, r2k_bot)
    c.via1(xn1, r2k_bot)

    # 9. Mirror-symmetric elongated vertical MIM coupling caps (8.4 x 26.8 = 225.12 um2, narrow ~24um total width!)
    m_fe = pb.pdk_device(pcache, "fe_m84x268", "sky130_fd_pr__cap_mim_m3_1", dict(w=8.4, l=26.8))
    m_fe.rects.pop("checkpaint", None)
    c.include(m_fe, dx=-6.400, dy=25.400)                 # C2(M3): x[-11.68..-1.12], y[11.80..39.00], mimcap y[12.00..38.80]
    c.include(m_fe, dx=+6.400, dy=25.400, mirror_x=True)  # C2(M3): x[+1.12..+11.68], y[11.80..39.00], mimcap y[12.00..38.80]
    # ck_pre_p (-5.45) & ck_pre_n (+5.45) drop via2+via3 at y=10.35 (1.39um below mimcap @ 12.00, capm.11 OK) -> M4 up into C1
    for xpre_m in (-5.450, +5.450):
        c.via2(xpre_m, 10.350); via3(c, xpre_m, 10.350)
        c.wire("metal4", [(xpre_m, 10.350), (xpre_m, 12.600)], 0.38)
    # ckp (-2.10) & ckn (+2.10) tap C2 M3 in the mimcap-free inner strip [+-1.12..+-3.08] -> port @ top y=39.00
    c.wire("metal2", [(xp1, r2k_bot), (xp1, 29.000), (-2.100, 29.000)], 0.34)
    c.via2(-2.100, 29.000)
    c.wire("metal2", [(xn1, r2k_bot), (xn1, 29.000), (+2.100, 29.000)], 0.34)
    c.via2(+2.100, 29.000)

    c.port("ck_pre_p", "metal2", -5.450, r550_r2)
    c.port("ck_pre_n", "metal2", +5.450, r550_r2)
    c.port("ckp", "metal3", -2.100, 38.800)
    c.port("ckn", "metal3", +2.100, 38.800)
    c.port("vbias_ck", "metal2", -12.000, y_vb_top)
    c.port("vbias", "metal2", -12.000, -2.20)
    c.port("vdd", "metal2", +12.150, y_vdd_top)
    c.port("vss", "metal1", 0.0, y_vss_gr)
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} clkp clkn ck_pre_p ck_pre_n ckp ckn vbias vbias_ck vdd vss",
        f"XRp_pre vdd ck_mid_n vss sky130_fd_pr__res_high_po_2p85 l={l_850}",
        f"XRn_pre vdd ck_mid_p vss sky130_fd_pr__res_high_po_2p85 l={l_850}",
        "Xmp_pre ck_mid_n clkp tail_pre vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15 nf=4",
        "Xmn_pre ck_mid_p clkn tail_pre vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15 nf=4",
        "Xtail_pre tail_pre vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5 nf=4",
        f"XRp_drv vdd ck_pre_p vss sky130_fd_pr__res_high_po_2p85 l={l_550}",
        f"XRn_drv vdd ck_pre_n vss sky130_fd_pr__res_high_po_2p85 l={l_550}",
        "Xmn_drv ck_pre_p ck_mid_n tail_drv vss sky130_fd_pr__nfet_01v8_lvt w=32 l=0.15 nf=4",
        "Xmp_drv ck_pre_n ck_mid_p tail_drv vss sky130_fd_pr__nfet_01v8_lvt w=32 l=0.15 nf=4",
        "Xtail_drv_l tail_drv vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5 nf=4",
        "Xtail_drv_r tail_drv vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5 nf=4",
        "Xccp ck_pre_p ckp sky130_fd_pr__cap_mim_m3_1 w=8.4 l=26.8",
        "Xccn ck_pre_n ckn sky130_fd_pr__cap_mim_m3_1 w=8.4 l=26.8",
        f"Xrbp1 ckp mid_bp vss sky130_fd_pr__res_high_po_1p41 l={l_2k}",
        f"Xrbp2 mid_bp vbias_ck vss sky130_fd_pr__res_high_po_1p41 l={l_2k}",
        f"Xrbn1 ckn mid_bn vss sky130_fd_pr__res_high_po_1p41 l={l_2k}",
        f"Xrbn2 mid_bn vbias_ck vss sky130_fd_pr__res_high_po_1p41 l={l_2k}",
        f".ends {name}",
        "",
    ])
    return signoff_plot_and_rc(w, name, ref)


def build_routed_replica_bias(out: Path, pcache: Path) -> dict:
    """Route compact side-by-side replica bias (~40 x 39 um matching Frontend height, single unified P-well)."""
    name = "sync2_ck_replica_bias_pdk"
    w = out / name
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()
    rw = 0.45

    p_n5x1 = pb.mos_prim(pcache, "rb_n5x1", "sky130_fd_pr__nfet_01v8", 5.0, 0.5, 1)
    p_ls   = pb.mos_prim(pcache, "rb_ls",   "sky130_fd_pr__nfet_01v8", 2.5, 2.0, 2)
    p_mn   = pb.mos_prim(pcache, "rb_mn",   "sky130_fd_pr__nfet_01v8", 4.0, 0.5, 2)
    p_ota  = pb.mos_prim(pcache, "rb_ota",  "sky130_fd_pr__nfet_01v8_lvt", 3.0, 0.5, 4)
    p_repc = pb.mos_prim(pcache, "rb_repc", "sky130_fd_pr__nfet_01v8_lvt", 5.0, 0.15, 2)
    p_repd = pb.mos_prim(pcache, "rb_repd", "sky130_fd_pr__nfet_01v8_lvt", 4.0, 0.15, 2)
    p_pm   = pb.mos_prim(pcache, "rb_pm",   "sky130_fd_pr__pfet_01v8", 6.0, 0.5, 4)
    l_580  = round((580.0 - 137.6) / 111.8, 3)
    l_960  = round((960.0 - 137.6) / 111.8, 3)
    l_4k   = round((4000.0 - 256.0) / 230.04, 3)
    p_r580 = pb.res_prim(pcache, "rb_r580", "sky130_fd_pr__res_high_po_2p85", l_580)
    p_r960 = pb.res_prim(pcache, "rb_r960", "sky130_fd_pr__res_high_po_2p85", l_960)
    p_r4k  = pb.res_prim(pcache, "rb_r4k",  "sky130_fd_pr__res_high_po_1p41", l_4k)

    x_L, x_R = -9.500, +11.500
    y_n1 = 3.000
    y_n2 = grid(y_n1 + p_n5x1.bbox()[3] + 1.35 + p_mn.bbox()[3])
    y_rep_bot = grid(y_n2 + p_mn.bbox()[3] + 1.15)
    y_r580 = grid(y_rep_bot + p_r580.bbox()[3])
    y_r960 = grid(y_rep_bot + p_r960.bbox()[3])
    y_repc = grid(y_rep_bot + p_repc.bbox()[3] + 1.20)
    y_repd = grid(y_rep_bot + p_repd.bbox()[3] + 1.20)

    gx1_p, gx2_p = -18.500, +21.000
    gy1_p = -1.100
    gy2_p = grid(max(y_r580 + p_r580.bbox()[3], y_r960 + p_r960.bbox()[3]) + 0.65 + rw)
    x_edge_l, x_edge_r = grid(gx1_p + rw - 0.04), grid(gx2_p - rw + 0.04)
    y_bot_li, y_top_li = grid(gy1_p + 0.41), grid(gy2_p - 0.41)

    # Left half: 6-strip 4k resistor bank centered at x_L = -9.500
    y_r4k = grid(gy1_p + rw + 1.00 + p_r4k.bbox()[3])
    pitch_r = 2.050
    for idx in (1, 2, 3, 4, 5, 6):
        c.include(p_r4k, dx=grid(x_L + (idx - 3.5) * pitch_r), dy=y_r4k)
    y_poly = max(r[3] for r in p_r4k.rects["xpolycontact"])
    y_res = max(r[3] for r in p_r4k.rects["ppolyres"])
    for idx, tie_x in ((0, True), (7, False)):
        xd = grid(x_L + (idx - 3.5) * pitch_r)
        c.rect("poly", grid(xd - 0.705), grid(y_r4k - y_poly), grid(xd + 0.705), grid(y_r4k + y_poly))
        c.rect("polycont", grid(xd - 0.500), grid(y_r4k + y_res + 0.30), grid(xd + 0.500), grid(y_r4k + y_poly - 0.30))
        c.rect("polycont", grid(xd - 0.500), grid(y_r4k - y_poly + 0.30), grid(xd + 0.500), grid(y_r4k - y_res - 0.30))
        c.rect("locali", grid(xd - 0.705), grid(y_r4k + y_res), grid(xd + 0.705), grid(y_r4k + y_poly))
        c.rect("locali", grid(xd - 0.705), grid(y_r4k - y_poly), grid(xd + 0.705), grid(y_r4k - y_res))
        if tie_x:
            c.rect("locali", min(xd, x_edge_l), grid(y_r4k + y_res + 0.20), max(xd, x_edge_l), grid(y_r4k + y_poly - 0.20))
            c.rect("locali", min(xd, x_edge_l), grid(y_r4k - y_poly + 0.20), max(xd, x_edge_l), grid(y_r4k - y_res - 0.20))
        else:
            c.rect("locali", grid(xd - 0.20), grid(y_r4k + y_res + 0.20), grid(xd + 0.20), y_top_li)
            c.rect("locali", grid(xd - 0.20), y_bot_li, grid(xd + 0.20), grid(y_r4k - y_res - 0.20))

    # Right half: active servo + replica inside unified P-guard ring
    c.include(p_n5x1, dx=grid(x_R - 7.00), dy=y_n1)
    c.include(p_ls,   dx=grid(x_R - 2.90), dy=y_n1)
    c.include(p_ls,   dx=grid(x_R + 2.90), dy=y_n1)
    c.include(p_n5x1, dx=grid(x_R + 7.00), dy=y_n1)

    c.include(p_mn,  dx=grid(x_R - 6.90), dy=y_n2)
    c.include(p_ota, dx=grid(x_R - 2.15), dy=y_n2)
    c.include(p_ota, dx=grid(x_R + 2.15), dy=y_n2)
    c.include(p_mn,  dx=grid(x_R + 6.90), dy=y_n2)
    pb.add_pair_dummies(c, p_ota, x_R, y_n2, 2.15, x_edge_l, x_edge_r, tie_outer_l=False, tie_outer_r=False)

    c.include(p_r580, dx=grid(x_R - 6.80), dy=y_r580)
    c.include(p_repc, dx=grid(x_R - 1.60), dy=y_repc)
    c.include(p_repd, dx=grid(x_R + 1.60), dy=y_repd)
    c.include(p_r960, dx=grid(x_R + 6.80), dy=y_r960)
    pb.add_pair_dummies(c, p_repc, x_R, y_repc, 1.60, x_edge_l, x_edge_r, tie_outer_l=False, tie_outer_r=False)

    pb.add_p_guard_ring(c, gx1_p, gy1_p, gx2_p, gy2_p, rw=rw)

    # Top-right PMOS mirror bank in nwell
    y_pm = grid(gy2_p + 1.40 + p_pm.bbox()[3] + 0.65 + rw)
    pm_xs = (grid(x_R - 6.90), grid(x_R - 2.35), grid(x_R + 2.35), grid(x_R + 6.90))
    for px in pm_xs:
        c.include(p_pm, dx=px, dy=y_pm)
    gx1_n, gx2_n = grid(pm_xs[0] - 1.905 - 0.85 - rw), grid(pm_xs[-1] + 1.905 + 0.85 + rw)
    gy1_n, gy2_n = grid(y_pm - p_pm.bbox()[3] - 0.65 - rw), grid(y_pm + p_pm.bbox()[3] + 1.15 + rw)
    pb.add_pair_dummies(c, p_pm, x_R, y_pm, 2.35, grid(gx1_n + rw - 0.04), grid(gx2_n - rw + 0.04), tie_outer_l=False, tie_outer_r=False)
    for px_out, xg_n in ((grid(pm_xs[0] - 1.905 - 0.30), grid(gx1_n + rw - 0.04)), (grid(pm_xs[-1] + 1.905 + 0.30), grid(gx2_n - rw + 0.04))):
        c.rect("poly", grid(px_out - 0.075), grid(y_pm - 2.95), grid(px_out + 0.075), grid(y_pm + 2.95))
        c.rect("poly", grid(px_out - 0.17), grid(y_pm - 0.17), grid(px_out + 0.17), grid(y_pm + 0.17))
        c.rect("polycont", grid(px_out - 0.085), grid(y_pm - 0.085), grid(px_out + 0.085), grid(y_pm + 0.085))
        c.rect("locali", min(grid(px_out - 0.17), xg_n), grid(y_pm - 0.17), max(grid(px_out + 0.17), xg_n), grid(y_pm + 0.17))
    pb.add_n_guard_ring(c, gx1_n, gy1_n, gx2_n, gy2_n, rw=rw)

    # Tie segmented center dummies & outer dummies cleanly (float_a = 0!)
    c.rect("locali", grid(x_R - 0.10), grid(y_n2 - 0.17), grid(x_R + 0.10), y_top_li)
    for yr in (y_n2, y_repc):
        c.rect("poly", grid(x_R - 0.17), grid(yr - 0.17), grid(x_R + 0.17), grid(yr + 0.17))
        c.rect("polycont", grid(x_R - 0.085), grid(yr - 0.085), grid(x_R + 0.085), grid(yr + 0.085))
        c.rect("locali", grid(x_R - 0.17), grid(yr - 0.17), grid(x_R + 0.17), grid(yr + 0.17))
    y_pm_tie = grid(y_pm + 3.55)
    for xd_o, yd_o, y_top_o, y_stem in (
        (grid(x_R - 4.175), y_n2, y_top_li, y_n2), (grid(x_R + 4.175), y_n2, y_top_li, y_n2),
        (grid(x_R - 2.525), y_repc, y_top_li, y_repc), (grid(x_R + 2.525), y_repc, y_top_li, y_repc),
        (grid(x_R - 4.375), y_pm_tie, grid(gy2_n - 0.41), y_pm), (grid(x_R + 4.375), y_pm_tie, grid(gy2_n - 0.41), y_pm),
    ):
        if y_stem != yd_o:
            c.rect("poly", grid(xd_o - 0.075), grid(y_stem), grid(xd_o + 0.075), grid(yd_o + 0.17))
        c.rect("poly", grid(xd_o - 0.17), grid(yd_o - 0.17), grid(xd_o + 0.17), grid(yd_o + 0.17))
        c.rect("polycont", grid(xd_o - 0.085), grid(yd_o - 0.085), grid(xd_o + 0.085), grid(yd_o + 0.085))
        c.rect("locali", grid(xd_o - 0.17), grid(yd_o - 0.17), grid(xd_o + 0.17), y_top_o)
    c.rect("poly", grid(x_R - 0.17), grid(y_pm - 0.17), grid(x_R + 0.17), grid(y_pm + 0.17))
    c.rect("polycont", grid(x_R - 0.085), grid(y_pm - 0.085), grid(x_R + 0.085), grid(y_pm + 0.085))
    c.rect("locali", grid(x_R - 0.17), grid(y_pm - 0.17), grid(x_R + 0.17), grid(gy2_n - 0.41))

    # Strap every FET
    st_rs   = strap_compact_fet(c, p_n5x1, grid(x_R - 7.00), y_n1, -0.70, +0.70)
    st_lsp  = strap_compact_fet(c, p_ls,   grid(x_R - 2.90), y_n1, -0.50, +0.50)
    st_lsn  = strap_compact_fet(c, p_ls,   grid(x_R + 2.90), y_n1, -0.50, +0.50)
    st_otat = strap_compact_fet(c, p_n5x1, grid(x_R + 7.00), y_n1, -0.70, +0.70)

    st_mn1  = strap_compact_fet(c, p_mn,  grid(x_R - 6.90), y_n2, -0.75, +0.75)
    st_otap = strap_compact_fet(c, p_ota, grid(x_R - 2.15), y_n2, -0.65, +0.65)
    st_otan = strap_compact_fet(c, p_ota, grid(x_R + 2.15), y_n2, -0.65, +0.65)
    st_mn2  = strap_compact_fet(c, p_mn,  grid(x_R + 6.90), y_n2, -0.75, +0.75)

    st_repc = strap_compact_fet(c, p_repc, grid(x_R - 1.60), y_repc, -0.90, +0.90)
    st_repd = strap_compact_fet(c, p_repd, grid(x_R + 1.60), y_repd, -0.75, +0.75)

    st_mp1  = strap_compact_fet(c, p_pm, grid(x_R - 6.90), y_pm, +1.10, -1.10)
    st_mp3  = strap_compact_fet(c, p_pm, grid(x_R - 2.35), y_pm, +1.10, -1.10)
    st_mp4  = strap_compact_fet(c, p_pm, grid(x_R + 2.35), y_pm, +1.10, -1.10)
    st_mp2  = strap_compact_fet(c, p_pm, grid(x_R + 6.90), y_pm, +1.10, -1.10)

    # ---- Routing ----
    y_vss_gr = grid(gy1_p + 0.225)
    y_vdd_gr = grid(gy2_n - 0.225)

    # 1. Left 6-strip 4k bank: [N1, P1, P2, N2, N3, P3]
    xn1, xp1, xp2, xn2, xn3, xp3 = (grid(x_L + (idx - 3.5) * pitch_r) for idx in (1, 2, 3, 4, 5, 6))
    r_bot, r_top = grid(y_r4k - 10.045), grid(y_r4k + 10.045)
    c.wire("metal1", [(xp1, r_bot), (xp2, r_bot)], 0.34)
    c.wire("metal1", [(xn2, r_bot), (xn3, r_bot)], 0.34)
    y_rtop_n12, y_rtop_p23 = grid(r_top + 0.60), grid(r_top + 1.15)
    c.wire("metal1", [(xn1, r_top), (xn1, y_rtop_n12)], 0.30); c.via1(xn1, y_rtop_n12)
    c.wire("metal1", [(xn2, r_top), (xn2, y_rtop_n12)], 0.30); c.via1(xn2, y_rtop_n12)
    c.wire("metal2", [(xn1, y_rtop_n12), (xn2, y_rtop_n12)], 0.34)
    c.wire("metal1", [(xp2, r_top), (xp2, y_rtop_p23), (xp3, y_rtop_p23), (xp3, r_top)], 0.30)
    c.wire("metal1", [(xp1, r_top), (xp1, 23.250)], 0.30); c.via1(xp1, 23.250)
    c.via1(xn3, r_top)
    c.via1(xn1, r_bot); c.via1(xp3, r_bot)

    # 2. Row B sources -> bottom M1 VSS rail (y_vss_gr = -0.875) & vbias gate bus (y_vb_n1 = 0.275 M1 -> right port M2)
    c.wire("metal2", [(st_rs["s_xs"][0], st_rs["ys"]), (st_rs["s_xs"][0], 0.000), (grid(x_R - 6.25), 0.000), (grid(x_R - 6.25), y_vss_gr)], 0.34)
    c.via1(grid(x_R - 6.25), y_vss_gr)
    for st in (st_lsp, st_lsn, st_otat):
        c.wire("metal2", [(st["s_xs"][0], st["ys"]), (st["s_xs"][0], y_vss_gr)], 0.34)
        c.via1(st["s_xs"][0], y_vss_gr)
    y_vb_n1 = st_rs["gy_b"]  # 0.275
    c.wire("metal1", [(st_rs["gx_l"] - 0.14, y_vb_n1), (grid(x_R + 8.30), y_vb_n1)], 0.23)
    for st_l, x_g in ((st_lsp, grid(x_R - 2.90)), (st_lsn, grid(x_R + 2.90))):
        c.wire("metal1", [(x_g, y_vb_n1), (x_g, st_l["gy_b"])], 0.23)
    c.via1(grid(x_R + 8.30), y_vb_n1)
    c.wire("metal2", [(grid(x_R + 8.30), y_vb_n1), (gx2_n, y_vb_n1)], 0.34)

    # 3. r4k -> active M2/M3 links (ZERO M3 under Xcomp!)
    r580_r2, r580_r1 = grid(y_r580 - 3.885), grid(y_r580 + 3.885)
    r960_r2, r960_r1 = grid(y_r960 - 5.585), grid(y_r960 + 5.585)
    # vref @ x=+2.35 (M2) -> at y=11.40 hops to M3 over rep_out (y=12.65) -> y=13.40 back to M2 -> XRref.R2 (x=+4.70)
    c.wire("metal2", [(xn1, r_bot), (xn1, -0.350), (+2.350, -0.350), (+2.350, 11.400)], 0.34)
    c.via2(+2.350, 11.400)
    c.wire("metal3", [(+2.350, 11.400), (+2.350, r580_r2)], 0.34)
    c.via2(+2.350, r580_r2)
    c.wire("metal2", [(+2.350, r580_r2), (grid(x_R - 6.80), r580_r2)], 0.34)
    c.via1(grid(x_R - 6.80), r580_r2)
    c.wire("metal2", [(+2.350, st_rs["yd"]), (st_rs["d_xs"][0], st_rs["yd"])], 0.34)

    # rep_out @ x=+1.55 -> y=12.65 M2 across (passes UNDER vref@2.35, nm@3.15, in_p@6.80, in_n@15.80 ALL on M3!) -> XRrep.R2 & Xrepd.D
    c.wire("metal2", [(xp3, r_bot), (xp3, 0.900), (+1.550, 0.900), (+1.550, 12.650), (grid(x_R + 6.80), 12.650), (grid(x_R + 6.80), r960_r2)], 0.34)
    c.via1(grid(x_R + 6.80), r960_r2)
    c.wire("metal2", [(st_repd["d_xs"][-1], 12.650), (st_repd["d_xs"][-1], st_repd["yd"])], 0.34)

    # in_p drops at x_inp_c=+6.80 on M3 over in_n (22.45 M2) & rep_out (12.65 M2) down to Xls_p.D & Xotap.G
    x_inp_c = grid(x_R - 4.70)
    c.wire("metal2", [(xp1, 23.250), (x_inp_c, 23.250)], 0.34)
    c.via2(x_inp_c, 23.250)
    c.wire("metal3", [(x_inp_c, 23.250), (x_inp_c, st_lsp["yd"])], 0.34)
    c.via2(x_inp_c, st_lsp["yd"])
    c.wire("metal2", [(x_inp_c, st_lsp["yd"]), (st_lsp["d_xs"][0], st_lsp["yd"])], 0.34)
    c.wire("metal2", [(x_inp_c, st_lsp["yd"]), (x_inp_c, st_otap["gy_b"])], 0.34)
    c.via1(x_inp_c, st_otap["gy_b"])
    c.wire("metal1", [(x_inp_c, st_otap["gy_b"]), (st_otap["gx_l"], st_otap["gy_b"])], 0.24)

    # in_n routes at y=22.450 (clears r580_r1@21.29 & xn3>xn2) to x_inn_c=+15.80 -> M3 down to Xls_n.D & Xotan.G
    x_inn_c = grid(x_R + 4.30)
    c.wire("metal2", [(xn3, r_top), (xn3, 22.450), (x_inn_c, 22.450)], 0.34)
    c.via2(x_inn_c, 22.450)
    c.wire("metal3", [(x_inn_c, 22.450), (x_inn_c, st_lsn["yd"])], 0.34)
    c.via2(x_inn_c, st_lsn["yd"])
    c.wire("metal2", [(st_lsn["d_xs"][-1], st_lsn["yd"]), (x_inn_c, st_lsn["yd"])], 0.34)
    c.wire("metal2", [(x_inn_c, st_lsn["yd"]), (x_inn_c, st_otan["gy_b"])], 0.34)
    c.via1(x_inn_c, st_otan["gy_b"])
    c.wire("metal1", [(st_otan["gx_r"], st_otan["gy_b"]), (x_inn_c, st_otan["gy_b"])], 0.24)

    # 4. Row C: ota_t, mirror S, mirror G/D nm
    y_ota_t = grid(y_n1 + 3.55)
    c.wire("metal2", [(st_otat["d_xs"][0], st_otat["yd"]), (st_otat["d_xs"][0], y_ota_t)], 0.34); c.via1(st_otat["d_xs"][0], y_ota_t)
    c.wire("metal1", [(st_otap["s_xs"][0], y_ota_t), (st_otat["d_xs"][0], y_ota_t)], 0.26)
    for sx in (st_otap["s_xs"][0], st_otan["s_xs"][0]):
        c.via1(sx, y_ota_t); c.wire("metal2", [(sx, y_ota_t), (sx, st_otap["ys"])], 0.32)

    c.wire("metal2", [(st_mn1["s_xs"][0], st_mn1["ys"]), (st_mn1["s_xs"][0], y_vss_gr)], 0.34); c.via1(st_mn1["s_xs"][0], y_vss_gr)
    c.wire("metal2", [(st_mn2["s_xs"][0], st_mn2["ys"]), (grid(x_R + 5.80), st_mn2["ys"]), (grid(x_R + 5.80), y_vss_gr)], 0.34); c.via1(grid(x_R + 5.80), y_vss_gr)

    y_gap = grid(0.5 * (gy2_p + gy1_n))
    y_nm_g, y_vb_g = grid(y_gap - 0.35), grid(y_gap + 0.35)
    c.wire("metal1", [(st_mn1["gx_l"] - 0.14, st_mn1["gy_t"]), (grid(x_R - 8.35), st_mn1["gy_t"])], 0.23); c.via1(grid(x_R - 8.35), st_mn1["gy_t"])
    c.wire("metal2", [(grid(x_R - 8.35), st_mn1["yd"]), (grid(x_R - 8.35), st_mn1["gy_t"])], 0.32)
    c.wire("metal1", [(st_mn2["gx_r"] + 0.14, st_mn2["gy_t"]), (grid(x_R + 8.30), st_mn2["gy_t"])], 0.23); c.via1(grid(x_R + 8.30), st_mn2["gy_t"])
    # nm rises on M3 along x=+3.15 (over rep_out, in_p, in_n M2!) up to y_nm_g
    c.wire("metal2", [(st_mn1["d_xs"][0], st_mn1["yd"]), (grid(x_R - 8.35), st_mn1["yd"])], 0.32)
    c.via2(grid(x_R - 8.35), st_mn1["yd"])
    c.wire("metal3", [(grid(x_R - 8.35), st_mn1["yd"]), (grid(x_R - 8.35), y_nm_g)], 0.32)
    c.via2(grid(x_R - 8.35), y_nm_g)
    c.wire("metal2", [(grid(x_R - 8.35), y_nm_g), (grid(x_R + 8.30), y_nm_g), (grid(x_R + 8.30), st_mn2["gy_t"])], 0.32)
    c.wire("metal2", [(grid(x_R + 2.35), st_mp4["yd"]), (grid(x_R + 3.00), st_mp4["yd"])], 0.34); c.via2(grid(x_R + 3.00), st_mp4["yd"])
    c.wire("metal3", [(grid(x_R + 3.00), st_mp4["yd"]), (grid(x_R + 3.00), y_nm_g)], 0.34); c.via2(grid(x_R + 3.00), y_nm_g)

    # 5. Replica row D: rep_track, Xrep_c.S=vss (hops on M3 over in_p/in_n M2 buses!), Xrep_d.G=vdd
    c.wire("metal2", [(st_repd["s_xs"][0], st_repd["ys"]), (st_repc["d_xs"][-1], st_repd["ys"]), (st_repc["d_xs"][-1], st_repc["yd"])], 0.34)
    y_top_vss_p = grid(gy2_p - 0.225)
    c.wire("metal2", [(st_repc["s_xs"][0], st_repc["ys"]), (grid(x_R - 2.80), st_repc["ys"])], 0.34)
    c.via2(grid(x_R - 2.80), st_repc["ys"])
    c.wire("metal3", [(grid(x_R - 2.80), st_repc["ys"]), (grid(x_R - 2.80), y_top_vss_p)], 0.34)
    c.via2(grid(x_R - 2.80), y_top_vss_p); c.via1(grid(x_R - 2.80), y_top_vss_p)
    c.wire("metal1", [(grid(x_R + 1.36), st_repd["gy_t"]), (grid(x_R + 0.72), st_repd["gy_t"])], 0.23)
    c.via1(grid(x_R + 0.72), st_repd["gy_t"]); c.via2(grid(x_R + 0.72), st_repd["gy_t"])
    c.wire("metal3", [(grid(x_R + 0.72), st_repd["gy_t"]), (grid(x_R + 0.72), y_vdd_gr)], 0.34)
    c.via2(grid(x_R + 0.72), y_vdd_gr); c.via1(grid(x_R + 0.72), y_vdd_gr)

    # 6. XRref.R1 & XRrep.R1 -> top VDD guard ring via M3
    for xr_v, rr1_v in ((grid(x_R - 6.80), r580_r1), (grid(x_R + 6.80), r960_r1)):
        c.via1(xr_v, rr1_v); c.via2(xr_v, rr1_v)
        c.wire("metal3", [(xr_v, rr1_v), (xr_v, y_vdd_gr)], 0.36)
        c.via2(xr_v, y_vdd_gr); c.via1(xr_v, y_vdd_gr)

    # 7. PMOS row S -> top y_vdd_gr + wide M2 VDD bar across top edge
    for stp in (st_mp1, st_mp3, st_mp4, st_mp2):
        for sx in stp["s_xs"]:
            c.wire("metal2", [(sx, stp["ys"]), (sx, y_vdd_gr)], 0.34); c.via1(sx, y_vdd_gr)
    c.wire("metal2", [(gx1_p, y_vdd_gr), (gx2_n, y_vdd_gr)], 0.44)

    # 8. OTA drains np & nn -> M3 up to PMOS bottom gates
    c.via2(grid(x_R - 1.75), st_otap["yd"]); c.wire("metal3", [(grid(x_R - 1.75), st_otap["yd"]), (grid(x_R - 1.75), st_mp3["gy_b"])], 0.34); c.via2(grid(x_R - 1.75), st_mp3["gy_b"])
    c.via1(grid(x_R - 1.75), st_mp3["gy_b"]); c.via1(grid(x_R - 6.90), st_mp1["gy_b"])
    c.wire("metal1", [(grid(x_R - 6.90), st_mp1["gy_b"]), (grid(x_R - 1.75), st_mp3["gy_b"])], 0.24)
    c.wire("metal2", [(grid(x_R - 6.90), st_mp1["yd"]), (grid(x_R - 6.90), st_mp1["gy_b"])], 0.32)

    c.via2(grid(x_R + 1.75), st_otan["yd"]); c.wire("metal3", [(grid(x_R + 1.75), st_otan["yd"]), (grid(x_R + 1.75), st_mp4["gy_b"])], 0.34); c.via2(grid(x_R + 1.75), st_mp4["gy_b"])
    c.via1(grid(x_R + 1.75), st_mp4["gy_b"]); c.via1(grid(x_R + 6.90), st_mp2["gy_b"])
    c.wire("metal1", [(grid(x_R + 1.75), st_mp4["gy_b"]), (grid(x_R + 6.90), st_mp2["gy_b"])], 0.24)
    c.wire("metal2", [(grid(x_R + 6.90), st_mp2["gy_b"]), (grid(x_R + 6.90), st_mp2["yd"])], 0.32)

    # 9. vbias_ck output: Xmp3.D + Xmn2.D + Xrep_c.G -> M2 right edge (gx2_n, y_vb_g)
    c.wire("metal2", [(grid(x_R - 2.35), st_mp3["yd"]), (grid(x_R - 2.35), y_vb_g), (gx2_n, y_vb_g)], 0.34)
    c.via2(grid(x_R + 7.69), st_mn2["yd"]); c.wire("metal3", [(grid(x_R + 7.69), st_mn2["yd"]), (grid(x_R + 7.69), y_vb_g)], 0.34); c.via2(grid(x_R + 7.69), y_vb_g)
    c.wire("metal1", [(grid(x_R - 1.36), st_repc["gy_t"]), (grid(x_R - 0.75), st_repc["gy_t"])], 0.23)
    c.via1(grid(x_R - 0.75), st_repc["gy_t"]); c.via2(grid(x_R - 0.75), st_repc["gy_t"])
    c.wire("metal3", [(grid(x_R - 0.75), st_repc["gy_t"]), (grid(x_R - 0.75), y_vb_g)], 0.34); c.via2(grid(x_R - 0.75), y_vb_g)

    # 10. 3D-stacked Xcomp MIM capacitor (20x20 @ (-9.50, 10.60) over left r4k): C2(M3)=vss (left tie), C1(M4)=vbias_ck (tap inside mimcapcontact @ -2.00!)
    m20 = pb.mim_prim(pcache, "rb_m20", 20)
    c.include(m20, dx=-9.500, dy=10.600)  # mimcapcontact=[-20.18..-0.58, 0.80..20.40], C2(M3)=[-20.58..+1.58]
    c.wire("metal3", [(x_edge_l, 20.600), (x_edge_l, 22.000)], 0.40)
    c.via2(x_edge_l, 22.000); c.via1(x_edge_l, 22.000)
    c.wire("metal4", [(-2.000, 19.800), (-2.000, y_vb_g)], 0.40)
    via3(c, -2.000, y_vb_g)
    c.via2(-2.000, y_vb_g)
    c.wire("metal2", [(-2.000, y_vb_g), (grid(x_R - 2.35), y_vb_g)], 0.36)

    c.port("vbias", "metal2", gx2_n, y_vb_n1)
    c.port("vbias_ck", "metal2", gx2_n, y_vb_g)
    c.port("vdd", "metal2", gx2_n, y_vdd_gr)
    c.port("vss", "metal1", 0.0, y_vss_gr)
    c.write(w / f"{name}.mag")

    ref = "\n".join([
        f".subckt {name} vbias vbias_ck vdd vss",
        "Xref_sink vref vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=0.5 nf=1",
        f"XRref vdd vref vss sky130_fd_pr__res_high_po_2p85 l={l_580}",
        f"XRrep vdd rep_out vss sky130_fd_pr__res_high_po_2p85 l={l_960}",
        "Xrep_d rep_out vdd rep_track vss sky130_fd_pr__nfet_01v8_lvt w=8 l=0.15 nf=2",
        "Xrep_c rep_track vbias_ck vss vss sky130_fd_pr__nfet_01v8_lvt w=10 l=0.15 nf=2",
        "Xls_p in_p vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=2.0 nf=2",
        f"XRls_p1 in_p mp1 vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        f"XRls_p2 mp1 mp2 vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        f"XRls_p3 mp2 rep_out vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        "Xls_n in_n vbias vss vss sky130_fd_pr__nfet_01v8 w=5 l=2.0 nf=2",
        f"XRls_n1 vref mn1 vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        f"XRls_n2 mn1 mn2 vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
        f"XRls_n3 mn2 in_n vss sky130_fd_pr__res_high_po_1p41 l={l_4k}",
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
    return signoff_plot_and_rc(w, name, ref)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=REPO / "results/layout/sync2_divider/compact_routed")
    ap.add_argument("--install-dir", type=Path, default=REPO / "analog/pll/divider/layout/variants/sync2_routed")
    ap.add_argument("--cells", default="all", help="Comma-separated subset (latch,buf,mux2,dff,frontend,bias) or 'all'")
    a = ap.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    pcache = out / "_prims"
    pcache.mkdir(exist_ok=True)

    builders = {
        "latch": ("sync2_latch_pdk", build_routed_latch),
        "buf": ("sync2_buf_out_pdk", build_routed_buf),
        "buf_bank3": ("sync2_buf_bank3_pdk", build_routed_buf_bank3),
        "mux2": ("sync2_mux2_pdk", build_routed_mux2),
        "mux_bank3": ("sync2_mux_bank3_pdk", build_routed_mux_bank3),
        "dff": ("sync2_dff_pdk", build_routed_dff),
        "frontend": ("sync2_ck_frontend_pdk", build_routed_ck_frontend),
        "bias": ("sync2_ck_replica_bias_pdk", build_routed_replica_bias),
    }
    keys = list(builders) if a.cells == "all" else [k.strip() for k in a.cells.split(",") if k.strip()]
    summary_p = out / "summary.json"
    res = json.loads(summary_p.read_text()) if (summary_p.exists() and a.cells != "all") else {}
    for k in keys:
        cname, fn = builders[k]
        res[cname] = fn(out, pcache)
    summary_p.write_text(json.dumps(res, indent=2))
    if a.install_dir:
        inst = a.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        for cell in res:
            for ext in (".mag", ".png"):
                src = out / cell / f"{cell}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
