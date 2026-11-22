#!/usr/bin/env python3
"""Build Production-Grade SKY130 PDK Wide-Swing Active-Matching Charge Pump Layout (pll_cp_steer_v4_pdk).

Implements ``pll_cp_steer_v4`` from ``analog/pll/cp/spice/charge_pump_steer_v4.spice``:
  wn=20, wp=112 (2x8x7um), lmirror=1, wsn=8, wsp=24 (8x3um), up_wn=2, up_ln=0.88, up_wp=8,
  dn_wn=4, dn_wp=8, pnf=16, nnf=4, win=24, lin=1, wl=96, ll=1, ntail=2, cdum=12.08x12.08um,
  plus 1/4-scale exact unit-finger replica (Xpr 28/1, Xpsr 6/0.15, Xnsr 2/0.15, Xnr 5/1),
  vbp->5uA->2.5uA servo bias (Xsb_p 2/1, Xsb_n 2/1), 8T rail-to-rail symmetrical servo OTA
  (Xst 1/1, Xsa/Xsb 2/1 LVT, Xsla..d 4/1 LVT, Xsn1..2 4/1), and 3D-stacked Miller MIM cap
  Xcsrv (10.0x14.0um, M3-M4) tucked directly inside the Column 1 NW & SW cavities!
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

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402

MIM_MODEL = "sky130_fd_pr__cap_mim_m3_1"


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def via_stack_14(c: Cell, x: float, y: float) -> None:
    c.via1(x, y)
    c.via2(x, y)
    via3(c, x, y)


def clean_prim(work: Path, name: str, model: str, params: dict) -> Cell:
    p = pdk_device(work, name, model, params)
    p.rects.pop("checkpaint", None)
    return p


def draw_mim(work: Path, name: str, w_um: float, l_um: float) -> Cell:
    mag = work / f"{name}.mag"
    mu.new_cell(mag)
    tcl = work / f"{name}.tcl"
    tcl.write_text(
        f"drc off\nload {name}\nbox values 0 0 0 0\n"
        f"set p [dict merge [sky130::{MIM_MODEL}_defaults] "
        f"[dict create w {w_um} l {l_um} nx 1 ny 1 stack 0]]\n"
        f"sky130::{MIM_MODEL}_draw $p\nsave {name}\nquit -noprompt\n"
    )
    res = mu.run_magic(tcl, work)
    (work / f"{name}.log").write_text(res.log)
    res.need(name)
    mc = Cell.read(mag)
    mc.rects.pop("checkpaint", None)
    mc.labels.clear()
    return mc


def prim_info(prim: Cell, dx: float, dy: float, is_pmos: bool, mirror_y: bool = False) -> dict:
    df = "pdiff" if is_pmos else "ndiff"
    ct = "pdiffc" if is_pmos else "ndiffc"
    mk = next(k for k in ("pmoslvt", "pmos", "nmoslvt", "nmos") if k in prim.rects)
    sds = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[ct]})
    x_min = grid(min(r[0] for r in prim.rects[df]) + dx)
    x_max = grid(max(r[2] for r in prim.rects[df]) + dx)
    y_min = grid(min(r[1] for r in prim.rects[df]) + dy)
    y_max = grid(max(r[3] for r in prim.rects[df]) + dy)
    py_lo = min(r[1] for r in prim.rects["poly"])
    py_hi = max(r[3] for r in prim.rects["poly"])
    poly_y1 = grid(dy - py_hi) if mirror_y else grid(dy + py_lo)
    poly_y2 = grid(dy - py_lo) if mirror_y else grid(dy + py_hi)
    l_f = grid(prim.rects[mk][0][2] - prim.rects[mk][0][0])
    g_pts = []
    for _, gx, gy, lbl in prim.labels:
        if lbl == "G":
            g_pts.append((grid(dx + gx), grid(dy - gy if mirror_y else dy + gy)))
    pcs = sorted(
        [(grid((r[0] + r[2]) / 2.0 + dx), grid(dy - (r[1] + r[3]) / 2.0 if mirror_y else dy + (r[1] + r[3]) / 2.0))
         for r in prim.rects.get("polycont", [])],
        key=lambda p: (p[0], p[1]),
    )
    return dict(
        dx=dx, dy=dy, sds=sds, x_min=x_min, x_max=x_max, y_min=y_min, y_max=y_max,
        poly_y1=poly_y1, poly_y2=poly_y2, l_f=l_f, g_pts=g_pts, pcs=pcs,
    )


def add_poly_dummies_tied(
    c: Cell,
    info: dict,
    tie_to_top: bool,
    tie_mode: str = "none",
    tie_val: float | tuple[float, float] = 0.0,
    gap: float = 0.11,
) -> list[tuple[float, float]]:
    lf = info["l_f"]
    hw = grid(lf / 2.0)
    y_lo, y_hi = info["poly_y1"], info["poly_y2"]
    y_cont = grid(y_hi + 0.05) if (tie_to_top and lf < 0.30) else (
        grid(y_lo - 0.05) if (not tie_to_top and lf < 0.30) else (
            grid(y_hi - 0.17) if tie_to_top else grid(y_lo + 0.17)
        )
    )
    pads = []
    for idx, (side_sign, x_edge) in enumerate(((-1, info["x_min"]), (+1, info["x_max"]))):
        x_d = grid(x_edge + side_sign * (gap + lf / 2.0))
        c.rect("poly", grid(x_d - hw), min(y_lo, grid(y_cont - 0.17)),
               grid(x_d + hw), max(y_hi, grid(y_cont + 0.17)))
        x_c = grid(x_d + side_sign * 0.120) if lf < 0.30 else x_d
        c.pad("poly", x_c, y_cont, 0.30, 0.34)
        c.pad("polycont", x_c, y_cont, 0.17, 0.17)
        c.pad("locali", x_c, y_cont, 0.22, 0.34)
        c.pad("viali", x_c, y_cont, 0.17, 0.17)
        c.pad("metal1", x_c, y_cont, 0.30, 0.30)
        pads.append((x_c, y_cont))
        if tie_mode == "y":
            c.wire("metal1", [(x_c, y_cont), (x_c, float(tie_val))], 0.24)
        elif tie_mode == "walls":
            xw = float(tie_val[idx])
            c.wire("metal1", [(x_c, y_cont), (xw, y_cont)], 0.24)
            c.pad("viali", xw, y_cont, 0.17)
            c.pad("metal1", xw, y_cont, 0.34)
    return pads


def tie_pad_to_wall(c: Cell, pt: tuple[float, float], x_wall: float) -> None:
    c.wire("metal1", [pt, (x_wall, pt[1])], 0.24)
    c.pad("viali", x_wall, pt[1], 0.17)
    c.pad("metal1", x_wall, pt[1], 0.34)


def draw_guard_strip_h(c: Cell, x1: float, x2: float, y: float, is_nwell: bool) -> None:
    dl = "nsubdiff" if is_nwell else "psubdiff"
    cl = "nsubdiffcont" if is_nwell else "psubdiffcont"
    x1g, x2g, yg = grid(x1), grid(x2), grid(y)
    c.rect(dl, grid(x1g - 0.20), grid(yg - 0.20), grid(x2g + 0.20), grid(yg + 0.20))
    c.rect("locali", grid(x1g - 0.16), grid(yg - 0.16), grid(x2g + 0.16), grid(yg + 0.16))
    xc = grid(x1g + 0.25)
    idx = 0
    while xc <= x2g - 0.25 + 1e-6:
        c.pad(cl, xc, yg, 0.17)
        if idx % 2 == 0:
            c.pad("viali", xc, yg, 0.17)
        xc = grid(xc + 0.50)
        idx += 1


def draw_guard_wall_v(c: Cell, x: float, y1: float, y2: float, is_nwell: bool) -> None:
    dl = "nsubdiff" if is_nwell else "psubdiff"
    cl = "nsubdiffcont" if is_nwell else "psubdiffcont"
    xg, y1g, y2g = grid(x), grid(min(y1, y2)), grid(max(y1, y2))
    c.rect(dl, grid(xg - 0.20), y1g, grid(xg + 0.20), y2g)
    c.rect("locali", grid(xg - 0.16), y1g, grid(xg + 0.16), y2g)
    yc = grid(y1g + 0.35)
    while yc <= y2g - 0.35 + 1e-6:
        c.pad(cl, xg, yc, 0.17)
        yc = grid(yc + 0.50)


def strap_sd_bus(c: Cell, xs: list[float], y_bus: float, w: float = 0.26, double_y: float | None = None) -> None:
    for sx in xs:
        c.via1(sx, y_bus)
        if double_y is not None:
            c.via1(sx, double_y)
            c.wire("metal2", [(sx, y_bus), (sx, double_y)], 0.24)
    if len(xs) > 1:
        c.wire("metal2", [(xs[0], y_bus), (xs[-1], y_bus)], w)


def build_cp_steer_v4(out: Path) -> dict:
    cell = "pll_cp_steer_v4_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    # --- PDK primitives ---
    upn_p = clean_prim(w, "upn_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.88, nf=1, conn_gates=1, guard=0))
    n2_p = clean_prim(w, "n2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=2, conn_gates=1, guard=0))
    p4_p = clean_prim(w, "p4_pdk", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1, guard=0))
    nsw8_p = clean_prim(w, "nsw8_pdk", "sky130_fd_pr__nfet_01v8",
                        dict(w=2.0, l=0.15, nf=8, conn_gates=0, guard=0, topc=1, botc=1))
    psw16_p = clean_prim(w, "psw16_3_pdk", "sky130_fd_pr__pfet_01v8",
                         dict(w=3.0, l=0.15, nf=16, conn_gates=0, guard=0, topc=1, botc=1))
    nmir4_p = clean_prim(w, "nmir4_pdk", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=1.0, nf=4, conn_gates=1, guard=0))
    pmir8_p = clean_prim(w, "pmir8_7_pdk", "sky130_fd_pr__pfet_01v8", dict(w=7.0, l=1.0, nf=8, conn_gates=1, guard=0))

    pmir4_r = clean_prim(w, "pmir4_7_pdk", "sky130_fd_pr__pfet_01v8", dict(w=7.0, l=1.0, nf=4, conn_gates=1, guard=0))
    psw2_r = clean_prim(w, "psw2_3_pdk", "sky130_fd_pr__pfet_01v8", dict(w=3.0, l=0.15, nf=2, conn_gates=1, guard=0))
    nsw1_r = clean_prim(w, "nsw1_2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=1, conn_gates=1, guard=0))
    nmir1_r = clean_prim(w, "nmir1_5_pdk", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=1.0, nf=1, conn_gates=1, guard=0))
    sbp1_p = clean_prim(w, "sbp1_2_pdk", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=1.0, nf=1, conn_gates=1, guard=0))
    sbn1_p = clean_prim(w, "sbn1_2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=1.0, nf=1, conn_gates=1, guard=0))
    st1_p = clean_prim(w, "st1_1_pdk", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=1.0, nf=1, conn_gates=1, guard=0))
    sin4_p = clean_prim(w, "sin4_pdk", "sky130_fd_pr__nfet_01v8_lvt",
                        dict(w=1.0, l=1.0, nf=4, conn_gates=0, guard=0, topc=1, botc=1))
    sld4_p = clean_prim(w, "sld4_pdk", "sky130_fd_pr__pfet_01v8_lvt", dict(w=2.0, l=1.0, nf=4, conn_gates=1, guard=0))
    snm4_p = clean_prim(w, "snm4_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=1.0, nf=4, conn_gates=1, guard=0))

    bd1_p = clean_prim(w, "bd1_pdk", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=1.0, nf=1, conn_gates=1, guard=0))
    tail2_p = clean_prim(w, "tail2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=1.0, nf=2, conn_gates=1, guard=0))
    inlvt8_p = clean_prim(w, "inlvt8_pdk", "sky130_fd_pr__nfet_01v8_lvt",
                          dict(w=6.0, l=1.0, nf=8, conn_gates=0, guard=0, topc=1, botc=1))
    ldlvt16_p = clean_prim(w, "ldlvt16_pdk", "sky130_fd_pr__pfet_01v8_lvt",
                           dict(w=6.0, l=1.0, nf=16, conn_gates=1, guard=0))
    cdum_c = draw_mim(w, "cdum_mim_raw", 12.08, 12.08)
    csrv_c = draw_mim(w, "csrv_mim_raw", 10.0, 14.0)

    c = Cell()

    # Global floorplan coordinates
    S = 2.40
    y_vss = -15.55
    y_vdd = 27.00
    x_gl, x_gm1, x_gm2, x_gr = 1.00, grid(13.00 + S), grid(28.00 + S), grid(53.80 + S)
    x_in_port = -0.60
    x_out_port = grid(55.20 + S)

    # Continuous single NWELL
    c.rect("nwell", grid(x_gl - 0.65), 1.75, grid(x_gr + 0.65), grid(y_vdd + 0.65))

    # Full-width quad-layer M1-M4 VDD & VSS rails + P+/N+ horizontal guard strips
    for yr, is_nw in ((y_vss, False), (y_vdd, True)):
        draw_guard_strip_h(c, x_gl, x_gr, yr, is_nw)
        for mlyr, mw in (("metal1", 0.90), ("metal2", 0.90), ("metal3", 1.00), ("metal4", 1.00)):
            c.wire(mlyr, [(x_in_port, yr), (x_gr + 0.40, yr)], mw)
        for xv in (x_in_port, x_gl, 8.00, x_gm1, grid(20.50 + S), x_gm2,
                   grid(35.50 + S), grid(41.00 + S), grid(47.61 + S), x_gr):
            via_stack_14(c, xv, yr)

    # Vertical P+/N+ guard walls
    for xg in (x_gl, x_gm1, x_gm2, x_gr):
        draw_guard_wall_v(c, xg, y_vss, -2.35, False)
        draw_guard_wall_v(c, xg, 2.35, y_vdd, True)

    # Vertical M2 supply trunks along x_gl=1.00 (no M2 crosses x_gl!)
    c.wire("metal2", [(x_gl, y_vss), (x_gl, -5.65)], 0.36)
    c.wire("metal2", [(x_gl, 5.65), (x_gl, y_vdd)], 0.36)
    for yt in (-5.65, 5.65):
        c.pad("viali", x_gl, yt, 0.17)
        c.via1(x_gl, yt)

    # =========================================================================
    # COLUMN 1 (Center Band): Digital Pulse Drivers
    # =========================================================================
    dy_drvn, dy_drvp = -3.90, 3.90
    x_up, x_dn1, x_dn2 = 4.10, 7.45, 10.80

    c.include(upn_p, dx=x_up, dy=dy_drvn)
    c.include(n2_p, dx=x_dn1, dy=dy_drvn)
    c.include(n2_p, dx=x_dn2, dy=dy_drvn)
    c.include(p4_p, dx=x_up, dy=dy_drvp, mirror_y=True)
    c.include(p4_p, dx=x_dn1, dy=dy_drvp, mirror_y=True)
    c.include(p4_p, dx=x_dn2, dy=dy_drvp, mirror_y=True)

    i_upn = prim_info(upn_p, x_up, dy_drvn, False)
    i_dn1n = prim_info(n2_p, x_dn1, dy_drvn, False)
    i_dn2n = prim_info(n2_p, x_dn2, dy_drvn, False)
    i_upp = prim_info(p4_p, x_up, dy_drvp, True, mirror_y=True)
    i_dn1p = prim_info(p4_p, x_dn1, dy_drvp, True, mirror_y=True)
    i_dn2p = prim_info(p4_p, x_dn2, dy_drvp, True, mirror_y=True)

    # Driver sources strapped horizontally on M2 at y=+-5.65 -> left trunk x_gl=1.00
    y_drvn_vss, y_drvp_vdd = -5.65, 5.65
    for info in (i_upn, i_dn1n, i_dn2n):
        strap_sd_bus(c, info["sds"][::2], grid(dy_drvn - 0.55), 0.28)
        c.wire("metal2", [(info["sds"][0], grid(dy_drvn - 0.55)), (info["sds"][0], y_drvn_vss)], 0.30)
    c.wire("metal2", [(x_gl, y_drvn_vss), (i_dn2n["sds"][0], y_drvn_vss)], 0.34)

    for info in (i_upp, i_dn1p, i_dn2p):
        strap_sd_bus(c, info["sds"][::2], grid(dy_drvp + 0.55), 0.28)
        c.wire("metal2", [(info["sds"][0], grid(dy_drvp + 0.55)), (info["sds"][0], y_drvp_vdd)], 0.30)
    c.wire("metal2", [(x_gl, y_drvp_vdd), (i_dn2p["sds"][0], y_drvp_vdd)], 0.34)

    # Driver drains (vertical M2 links)
    for in_i, ip_i, xd in ((i_upn, i_upp, x_up), (i_dn1n, i_dn1p, x_dn1), (i_dn2n, i_dn2p, x_dn2)):
        strap_sd_bus(c, in_i["sds"][1::2], grid(dy_drvn + 0.45), 0.26)
        strap_sd_bus(c, ip_i["sds"][1::2], grid(dy_drvp - 0.45), 0.26)
        c.wire("metal2", [(in_i["sds"][1], grid(dy_drvn + 0.45)), (xd, grid(dy_drvn + 0.45)),
                          (xd, grid(dy_drvp - 0.45)), (ip_i["sds"][1], grid(dy_drvp - 0.45))], 0.28)

    # =========================================================================
    # COLUMN 2: Upgraded Mirrors (Xp 112/1, Xn 20/1) & ABBA Switches (Xps 24/0.15, Xns 8/0.15)
    # =========================================================================
    x_c2 = grid(20.50 + S)
    dy_psw, dy_pmir0, dy_pmir1 = 4.40, 12.60, 21.60
    dy_nsw, dy_nmir = -3.90, -10.15

    c.include(psw16_p, dx=x_c2, dy=dy_psw)
    c.include(pmir8_p, dx=x_c2, dy=dy_pmir0)
    c.include(pmir8_p, dx=x_c2, dy=dy_pmir1, mirror_y=True)
    c.include(nsw8_p, dx=x_c2, dy=dy_nsw)
    c.include(nmir4_p, dx=x_c2, dy=dy_nmir, mirror_y=True)

    i_psw = prim_info(psw16_p, x_c2, dy_psw, True)
    i_pm0 = prim_info(pmir8_p, x_c2, dy_pmir0, True)
    i_pm1 = prim_info(pmir8_p, x_c2, dy_pmir1, True, mirror_y=True)
    i_nsw = prim_info(nsw8_p, x_c2, dy_nsw, False)
    i_nm = prim_info(nmir4_p, x_c2, dy_nmir, False, mirror_y=True)

    add_poly_dummies_tied(c, i_pm0, False, "walls", (x_gm1, x_gm2), gap=0.11)
    add_poly_dummies_tied(c, i_pm1, True, "y", y_vdd, gap=0.11)
    add_poly_dummies_tied(c, i_psw, True, "walls", (x_gm1, x_gm2), gap=0.14)
    add_poly_dummies_tied(c, i_nsw, False, "walls", (x_gm1, x_gm2), gap=0.14)
    add_poly_dummies_tied(c, i_nm, True, "walls", (x_gm1, x_gm2), gap=0.11)

    strap_sd_bus(c, i_pm0["sds"][::2], grid(dy_pmir0 + 2.00), 0.34, double_y=grid(dy_pmir0 + 2.70))
    strap_sd_bus(c, i_pm1["sds"][::2], grid(dy_pmir1 + 2.00), 0.34, double_y=grid(dy_pmir1 + 2.70))
    for sx in (i_pm1["sds"][0], i_pm1["sds"][4], i_pm1["sds"][8]):
        c.wire("metal2", [(sx, grid(dy_pmir1 + 2.00)), (sx, y_vdd)], 0.34)
    for sx in (i_pm0["sds"][0], i_pm0["sds"][8]):
        c.via2(sx, grid(dy_pmir0 + 2.00))
        c.via2(sx, y_vdd)
        c.wire("metal3", [(sx, grid(dy_pmir0 + 2.00)), (sx, y_vdd)], 0.44)

    strap_sd_bus(c, i_pm0["sds"][1::2], grid(dy_pmir0 - 2.00), 0.36, double_y=grid(dy_pmir0 - 2.70))
    strap_sd_bus(c, i_pm1["sds"][1::2], grid(dy_pmir1 - 2.00), 0.36, double_y=grid(dy_pmir1 - 2.70))
    y_psw_ps = grid(dy_psw + 0.90)
    strap_sd_bus(c, i_psw["sds"][::2], y_psw_ps, 0.32)
    for xj in (grid(17.92 + S), grid(23.08 + S)):
        c.via2(xj, grid(dy_pmir1 - 2.00))
        c.via2(xj, grid(dy_pmir0 - 2.00))
        c.via2(xj, y_psw_ps)
        c.wire("metal3", [(xj, y_psw_ps), (xj, grid(dy_pmir1 - 2.00))], 0.44)

    strap_sd_bus(c, i_nm["sds"][::2], grid(dy_nmir - 1.40), 0.34, double_y=grid(dy_nmir - 2.00))
    for sx in i_nm["sds"][::2]:
        c.wire("metal2", [(sx, grid(dy_nmir - 1.40)), (sx, y_vss)], 0.34)
    strap_sd_bus(c, i_nm["sds"][1::2], grid(dy_nmir + 1.40), 0.36, double_y=grid(dy_nmir + 2.00))
    y_nsw_ns = grid(dy_nsw - 0.60)
    strap_sd_bus(c, i_nsw["sds"][::2], y_nsw_ns, 0.32)
    for xj in (grid(19.21 + S), grid(21.79 + S)):
        c.via2(xj, grid(dy_nmir + 1.40))
        c.via2(xj, y_nsw_ns)
        c.wire("metal3", [(xj, grid(dy_nmir + 1.40)), (xj, y_nsw_ns)], 0.44)

    psw_out_xs = [i_psw["sds"][k] for k in (1, 7, 9, 15)]
    psw_dum_xs = [i_psw["sds"][k] for k in (3, 5, 11, 13)]
    y_psw_dum = grid(dy_psw + 0.00)
    y_psw_out = grid(dy_psw - 0.90)
    strap_sd_bus(c, psw_dum_xs, y_psw_dum, 0.22)
    strap_sd_bus(c, psw_out_xs, y_psw_out, 0.18)

    nsw_out_xs = [i_nsw["sds"][k] for k in (1, 7)]
    nsw_dum_xs = [i_nsw["sds"][k] for k in (3, 5)]
    y_nsw_dum = grid(dy_nsw + 0.00)
    y_nsw_out = grid(dy_nsw + 0.60)
    strap_sd_bus(c, nsw_dum_xs, y_nsw_dum, 0.22)
    strap_sd_bus(c, nsw_out_xs, y_nsw_out, 0.18)

    x_out_stem, x_dum_stem = grid(25.30 + S), grid(26.80 + S)
    c.wire("metal2", [(psw_out_xs[-1], y_psw_out), (x_out_stem, y_psw_out),
                      (x_out_stem, y_nsw_out), (nsw_out_xs[-1], y_nsw_out)], 0.20)
    c.wire("metal2", [(psw_dum_xs[-1], y_psw_dum), (x_dum_stem, y_psw_dum),
                      (x_dum_stem, y_nsw_dum), (nsw_dum_xs[-1], y_nsw_dum)], 0.26)

    y_upb_top, y_up_top = 7.20, 7.80
    y_upb_bot, y_up_bot = 1.60, 1.00
    psw_top_pcs = sorted([p for p in i_psw["pcs"] if p[1] > dy_psw])
    psw_bot_pcs = sorted([p for p in i_psw["pcs"] if p[1] < dy_psw])
    for idx, (px, py) in enumerate(psw_top_pcs):
        yt = y_upb_top if idx in (0, 3, 4, 7) else y_up_top
        yv = grid(py + 0.34)
        c.rect("metal1", grid(px - 0.16), py, grid(px + 0.16), grid(yv + 0.16))
        c.via1(px, yv)
        c.wire("metal2", [(px, yv), (px, yt)], 0.22)
        c.via1(px, yt)
    for idx, (px, py) in enumerate(psw_bot_pcs):
        yb = y_upb_bot if idx in (0, 3, 4, 7) else y_up_bot
        yv = grid(py - 0.34)
        c.rect("metal1", grid(px - 0.16), grid(yv - 0.16), grid(px + 0.16), py)
        c.via1(px, yv)
        c.wire("metal2", [(px, yv), (px, yb)], 0.22)
        c.via1(px, yb)

    x_up_j, x_upb_j = grid(14.30 + S), grid(15.10 + S)
    c.wire("metal1", [(x_upb_j, y_upb_top), (psw_top_pcs[7][0], y_upb_top)], 0.24)
    c.wire("metal1", [(x_up_j, y_up_top), (psw_top_pcs[6][0], y_up_top)], 0.24)
    c.wire("metal1", [(x_upb_j, y_upb_bot), (psw_bot_pcs[7][0], y_upb_bot)], 0.24)
    c.wire("metal1", [(x_up_j, y_up_bot), (psw_bot_pcs[6][0], y_up_bot)], 0.24)
    for xj, y1, y2 in ((x_upb_j, y_upb_bot, y_upb_top), (x_up_j, y_up_bot, y_up_top)):
        c.via1(xj, y1)
        c.via1(xj, y2)
        c.wire("metal2", [(xj, y1), (xj, y2)], 0.24)

    y_dnon_top, y_dnb_top = -1.60, -1.00
    y_dnon_bot, y_dnb_bot = -6.05, -6.65
    nsw_top_pcs = sorted([p for p in i_nsw["pcs"] if p[1] > dy_nsw])
    nsw_bot_pcs = sorted([p for p in i_nsw["pcs"] if p[1] < dy_nsw])
    for idx, (px, py) in enumerate(nsw_top_pcs):
        yt = y_dnon_top if idx in (0, 3) else y_dnb_top
        yv = grid(py + 0.34)
        c.rect("metal1", grid(px - 0.16), py, grid(px + 0.16), grid(yv + 0.16))
        c.via1(px, yv)
        c.wire("metal2", [(px, yv), (px, yt)], 0.22)
        c.via1(px, yt)
    for idx, (px, py) in enumerate(nsw_bot_pcs):
        yb = y_dnon_bot if idx in (0, 3) else y_dnb_bot
        yv = grid(py - 0.34)
        c.rect("metal1", grid(px - 0.16), grid(yv - 0.16), grid(px + 0.16), py)
        c.via1(px, yv)
        c.wire("metal2", [(px, yv), (px, yb)], 0.22)
        c.via1(px, yb)

    x_dnb_j, x_dnon_j = grid(14.30 + S), grid(15.10 + S)
    c.wire("metal1", [(x_dnon_j, y_dnon_top), (nsw_top_pcs[3][0], y_dnon_top)], 0.24)
    c.wire("metal1", [(x_dnb_j, y_dnb_top), (nsw_top_pcs[2][0], y_dnb_top)], 0.24)
    c.wire("metal1", [(x_dnon_j, y_dnon_bot), (nsw_bot_pcs[3][0], y_dnon_bot)], 0.24)
    c.wire("metal1", [(x_dnb_j, y_dnb_bot), (nsw_bot_pcs[2][0], y_dnb_bot)], 0.24)
    for xj, y1, y2 in ((x_dnon_j, y_dnon_bot, y_dnon_top), (x_dnb_j, y_dnb_bot, y_dnb_top)):
        c.via1(xj, y1)
        c.via1(xj, y2)
        c.wire("metal2", [(xj, y1), (xj, y2)], 0.24)

    # Connect Col 1 drivers strictly inside center channel
    x_up_g, x_dn1_g, x_dn2_g = 2.50, 5.85, 9.20
    c.wire("metal1", [(x_in_port, y_up_bot), (x_up_j, y_up_bot)], 0.26)
    c.via1(x_up_g, y_up_bot)
    c.wire("metal2", [(x_up_g, i_upn["g_pts"][0][1]), (x_up_g, i_upp["g_pts"][0][1])], 0.24)
    for gp in (i_upp["g_pts"][0], i_upn["g_pts"][0]):
        c.via1(x_up_g, gp[1])
        c.wire("metal1", [(x_up_g, gp[1]), gp], 0.20)

    c.via1(x_up, y_upb_bot)
    c.wire("metal1", [(x_up, y_upb_bot), (x_upb_j, y_upb_bot)], 0.26)

    y_dn_ch = -0.35
    c.wire("metal1", [(x_in_port, y_dn_ch), (x_dn1_g, y_dn_ch)], 0.26)
    c.via1(x_dn1_g, y_dn_ch)
    c.wire("metal2", [(x_dn1_g, i_dn1n["g_pts"][0][1]), (x_dn1_g, i_dn1p["g_pts"][0][1])], 0.24)
    for gp in (i_dn1n["g_pts"][0], i_dn1p["g_pts"][0]):
        c.via1(x_dn1_g, gp[1])
        c.wire("metal1", [(x_dn1_g, gp[1]), gp], 0.20)

    c.via1(x_dn1, y_dnb_top)
    c.wire("metal1", [(x_dn1, y_dnb_top), (x_dnb_j, y_dnb_top)], 0.26)
    c.via1(x_dn2_g, y_dnb_top)
    c.wire("metal2", [(x_dn2_g, i_dn2n["g_pts"][0][1]), (x_dn2_g, i_dn2p["g_pts"][0][1])], 0.24)
    for gp in (i_dn2n["g_pts"][0], i_dn2p["g_pts"][0]):
        c.via1(x_dn2_g, gp[1])
        c.wire("metal1", [(x_dn2_g, gp[1]), gp], 0.20)

    c.via1(x_dn2, y_dnon_top)
    c.wire("metal1", [(x_dn2, y_dnon_top), (x_dnon_j, y_dnon_top)], 0.26)

    # =========================================================================
    # COLUMN 1 NW & SW CAVITIES: Active 1/4 Replica + 8T Symmetrical Servo OTA + 3D Xcsrv
    # =========================================================================
    # --- NW Cavity PMOS placements ---
    dx_sbp, dy_sbp = 3.20, 23.00
    dx_pr, dy_pr = 10.20, 21.60
    dx_psr, dy_psr = 12.60, 12.80
    dx_sla, dy_sla = 6.20, 14.20   # mirror_y=True -> gate at bottom (12.7), VDD bus at top (14.8)
    dx_slb, dy_slb = 6.20, 8.80    # mirror_y=True -> gate at bottom (7.3), VDD bus at top (9.4)

    c.include(sbp1_p, dx=dx_sbp, dy=dy_sbp, mirror_y=True)
    c.include(pmir4_r, dx=dx_pr, dy=dy_pr, mirror_y=True)
    c.include(psw2_r, dx=dx_psr, dy=dy_psr, mirror_y=True)
    c.include(sld4_p, dx=dx_sla, dy=dy_sla, mirror_y=True)
    c.include(sld4_p, dx=dx_slb, dy=dy_slb, mirror_y=True)

    i_sbp = prim_info(sbp1_p, dx_sbp, dy_sbp, True, mirror_y=True)
    i_pr = prim_info(pmir4_r, dx_pr, dy_pr, True, mirror_y=True)
    i_psr = prim_info(psw2_r, dx_psr, dy_psr, True, mirror_y=True)
    i_sla = prim_info(sld4_p, dx_sla, dy_sla, True, mirror_y=True)
    i_slb = prim_info(sld4_p, dx_slb, dy_slb, True, mirror_y=True)

    # Biased poly dummies for NW cavity (all tied cleanly on M1 above each device to x_gl or y_vdd!)
    add_poly_dummies_tied(c, i_pr, True, "y", y_vdd, gap=0.11)
    sla_dpads = add_poly_dummies_tied(c, i_sla, True, "none", 0.0, gap=0.11)
    slb_dpads = add_poly_dummies_tied(c, i_slb, True, "none", 0.0, gap=0.11)
    for dpads, y_tie in ((sla_dpads, 16.05), (slb_dpads, 10.65)):
        for pt in dpads:
            c.wire("metal1", [pt, (pt[0], y_tie)], 0.24)
        c.wire("metal1", [(x_gl, y_tie), (dpads[1][0], y_tie)], 0.24)
        c.pad("viali", x_gl, y_tie, 0.17)
        c.pad("metal1", x_gl, y_tie, 0.34)

    # --- SW Cavity NMOS placements ---
    dx_sbn, dy_sbn = 2.90, -11.60
    dx_st, dy_st = 4.90, -12.00
    dx_snm, dy_snm = 9.00, -11.70  # mirror_y=False -> gate at top (-10.2), VSS at bottom (-12.3)
    dx_nr, dy_nr = 13.70, -10.15
    dx_nsr, dy_nsr = 11.60, -7.20
    dx_sin, dy_sin = 6.20, -7.60

    c.include(sbn1_p, dx=dx_sbn, dy=dy_sbn, mirror_y=True)
    c.include(st1_p, dx=dx_st, dy=dy_st, mirror_y=True)
    c.include(snm4_p, dx=dx_snm, dy=dy_snm)
    c.include(nmir1_r, dx=dx_nr, dy=dy_nr, mirror_y=True)
    c.include(nsw1_r, dx=dx_nsr, dy=dy_nsr)
    c.include(sin4_p, dx=dx_sin, dy=dy_sin)

    i_sbn = prim_info(sbn1_p, dx_sbn, dy_sbn, False, mirror_y=True)
    i_st = prim_info(st1_p, dx_st, dy_st, False, mirror_y=True)
    i_snm = prim_info(snm4_p, dx_snm, dy_snm, False)
    i_nr = prim_info(nmir1_r, dx_nr, dy_nr, False, mirror_y=True)
    i_nsr = prim_info(nsw1_r, dx_nsr, dy_nsr, False)
    i_sin = prim_info(sin4_p, dx_sin, dy_sin, False)

    # Biased poly dummies for sin4: left pad -> x_gl M1; right pad -> via1 + M2 straight up to y_drvn_vss (-5.65)
    sin_dpads = add_poly_dummies_tied(c, i_sin, False, "none", 0.0, gap=0.11)
    tie_pad_to_wall(c, sin_dpads[0], x_gl)
    c.via1(sin_dpads[1][0], sin_dpads[1][1])
    c.wire("metal2", [sin_dpads[1], (sin_dpads[1][0], y_drvn_vss)], 0.24)

    # --- NW & SW Supply Connections (strictly orthogonal, zero signal crossings!) ---
    c.via1(i_sbp["sds"][0], grid(dy_sbp + 0.50))
    c.wire("metal2", [(i_sbp["sds"][0], grid(dy_sbp + 0.50)), (i_sbp["sds"][0], y_vdd)], 0.28)
    strap_sd_bus(c, i_pr["sds"][::2], grid(dy_pr + 2.00), 0.34, double_y=grid(dy_pr + 2.70))
    for sx in i_pr["sds"][::2]:
        c.wire("metal2", [(sx, grid(dy_pr + 2.00)), (sx, y_vdd)], 0.32)

    # Xsla+Xslc & Xslb+Xsld sources -> TOP M2 bus -> left to x_gl M2 VDD trunk
    strap_sd_bus(c, i_sla["sds"][::2], grid(dy_sla + 0.60), 0.28)
    c.wire("metal2", [(x_gl, grid(dy_sla + 0.60)), (i_sla["sds"][0], grid(dy_sla + 0.60))], 0.28)
    strap_sd_bus(c, i_slb["sds"][::2], grid(dy_slb + 0.60), 0.28)
    c.wire("metal2", [(x_gl, grid(dy_slb + 0.60)), (i_slb["sds"][0], grid(dy_slb + 0.60))], 0.28)

    # SW NMOS sources -> VSS
    for sx, sy in ((i_sbn["sds"][0], dy_sbn), (i_st["sds"][0], dy_st)):
        c.via1(sx, sy)
        c.wire("metal2", [(sx, sy), (sx, y_vss)], 0.26)
    strap_sd_bus(c, i_snm["sds"][::2], grid(dy_snm - 0.55), 0.28)
    for sx in i_snm["sds"][::2]:
        c.wire("metal2", [(sx, grid(dy_snm - 0.55)), (sx, y_vss)], 0.28)
    c.via1(i_nr["sds"][0], grid(dy_nr - 1.40))
    c.via1(i_nr["sds"][0], grid(dy_nr - 2.00))
    c.wire("metal2", [(i_nr["sds"][0], grid(dy_nr - 1.40)), (i_nr["sds"][0], y_vss)], 0.32)

    # --- External vbp port -> Xsb_p.G (y=20.80) ---
    y_vbp = 20.80
    c.wire("metal1", [(x_in_port, y_vbp), (i_sbp["g_pts"][0][0], y_vbp)], 0.28)
    c.rect("metal1", grid(i_sbp["g_pts"][0][0] - 0.16), grid(y_vbp - 0.14),
           grid(i_sbp["g_pts"][0][0] + 0.16), i_sbp["g_pts"][0][1])

    # --- sbn net: Xsb_p.D -> M3 vertical at x=1.65 (1.72um clear of mimcap!) -> Xsb_n.D/G & Xst.G ---
    x_sbn_m3 = 1.65
    y_sbp_d = grid(dy_sbp - 0.50)
    c.via1(i_sbp["sds"][1], y_sbp_d)
    c.wire("metal2", [(i_sbp["sds"][1], y_sbp_d), (x_sbn_m3, y_sbp_d)], 0.24)
    c.via2(x_sbn_m3, y_sbp_d)
    y_sbn_bot = grid(dy_sbn - 0.10)
    c.via2(x_sbn_m3, y_sbn_bot)
    c.wire("metal3", [(x_sbn_m3, y_sbn_bot), (x_sbn_m3, y_sbp_d)], 0.32)
    y_sbn_g = grid(i_sbn["g_pts"][0][1] - 0.10)
    c.wire("metal2", [(x_sbn_m3, y_sbn_bot), (x_sbn_m3, y_sbn_g)], 0.24)
    c.via1(x_sbn_m3, y_sbn_g)
    c.wire("metal1", [(x_sbn_m3, y_sbn_g), (i_st["g_pts"][0][0], y_sbn_g)], 0.24)
    c.rect("metal1", grid(i_sbn["g_pts"][0][0] - 0.16), grid(y_sbn_g - 0.12),
           grid(i_sbn["g_pts"][0][0] + 0.16), i_sbn["g_pts"][0][1])
    c.rect("metal1", grid(i_st["g_pts"][0][0] - 0.16), grid(y_sbn_g - 0.12),
           grid(i_st["g_pts"][0][0] + 0.16), i_st["g_pts"][0][1])
    c.via1(i_sbn["sds"][1], dy_sbn)
    c.wire("metal2", [(i_sbn["sds"][1], dy_sbn), (i_sbn["sds"][1], y_sbn_g)], 0.24)
    c.via1(i_sbn["sds"][1], y_sbn_g)

    # --- stail net: sin4 sources S0/S2/S4 centered at dy_sin (-7.60, zero met1.2 notch!) -> M2 down to y=-9.55 -> Xst.D ---
    y_stail = -9.55
    for sx in i_sin["sds"][::2]:
        c.via1(sx, dy_sin)
        c.wire("metal2", [(sx, dy_sin), (sx, y_stail)], 0.24)
    c.wire("metal2", [(i_sin["sds"][0], y_stail), (i_sin["sds"][-1], y_stail)], 0.26)
    c.via1(i_st["sds"][1], dy_st)
    c.wire("metal2", [(i_st["sds"][1], dy_st), (i_st["sds"][1], y_stail)], 0.26)

    # --- vbn horizontal bus at y=-13.55 -> Xnr.G & Xn.G ---
    y_vbn = -13.55
    c.wire("metal1", [(x_in_port, y_vbn), (i_nm["g_pts"][0][0], y_vbn)], 0.28)
    for ginfo in (i_nr, i_nm):
        gx, gy = ginfo["g_pts"][0]
        c.rect("metal1", grid(gx - 0.16), grid(y_vbn - 0.14), grid(gx + 0.16), gy)

    # --- vbp_srv horizontal gate bus at y=17.10: Xpr.G + Xp0.G + Xp1.G + Xslc.D + Xsn2.D + Xcsrv(M3) ---
    y_vbps = 17.10
    x_vbps_up = 9.75   # vertical M2 lane right of i_sla/i_slb (left of x_sda_up=10.45 -> zero M2 crossing!)
    x_sda_up = 10.45
    c.wire("metal1", [(min(i_pr["g_pts"][0][0], x_vbps_up), y_vbps), (i_pm0["g_pts"][0][0], y_vbps)], 0.30)
    c.via1(i_pm0["g_pts"][0][0], y_vbps)
    c.wire("metal2", [(i_pm0["g_pts"][0][0], i_pm0["g_pts"][0][1]),
                      (i_pm0["g_pts"][0][0], i_pm1["g_pts"][0][1])], 0.26)
    c.via1(i_pm0["g_pts"][0][0], i_pm0["g_pts"][0][1])
    c.via1(i_pm1["g_pts"][0][0], i_pm1["g_pts"][0][1])
    c.via1(i_pr["g_pts"][0][0], y_vbps)
    c.wire("metal2", [(i_pr["g_pts"][0][0], y_vbps), i_pr["g_pts"][0]], 0.26)
    c.via1(i_pr["g_pts"][0][0], i_pr["g_pts"][0][1])

    # --- Replica internal nets: psr, nsr, rep, Xpsr.G=vss, Xnsr.G=vdd ---
    y_pr_d = grid(dy_pr - 2.00)
    strap_sd_bus(c, i_pr["sds"][1::2], y_pr_d, 0.32, double_y=grid(dy_pr - 2.65))
    y_psr_s = grid(dy_psr + 0.70)
    strap_sd_bus(c, i_psr["sds"][::2], y_psr_s, 0.26)
    c.wire("metal2", [(i_pr["sds"][3], y_pr_d), (i_psr["sds"][0], y_pr_d), (i_psr["sds"][0], y_psr_s)], 0.28)

    # nsr: Xnr drain (14.345) -> M2 up to y=-6.90 (0.39um clear of Xnr top M1!) -> horizontal M1 straight into Xnsr.S (11.82)
    y_nr_d = grid(dy_nr + 1.20)
    y_nsr_s = -6.90
    y_nsr_d = grid(dy_nsr + 0.45)
    c.via1(i_nr["sds"][1], y_nr_d)
    c.wire("metal2", [(i_nr["sds"][1], y_nr_d), (i_nr["sds"][1], y_nsr_s)], 0.26)
    c.via1(i_nr["sds"][1], y_nsr_s)
    c.wire("metal1", [(i_nsr["sds"][1], y_nsr_s), (i_nr["sds"][1], y_nsr_s)], 0.24)

    # rep vertical M2 trunk at x=12.40 (width 0.24): generous clearance to Xdn2p (x_max=11.92) AND Xpsr right gate pad (12.68)!
    x_rep_trk = 12.40
    c.via1(i_psr["sds"][1], grid(dy_psr - 0.50))
    c.via1(i_nsr["sds"][0], y_nsr_d)
    c.wire("metal2", [(i_psr["sds"][1], grid(dy_psr - 0.50)), (x_rep_trk, grid(dy_psr - 0.50)),
                      (x_rep_trk, y_nsr_d), (i_nsr["sds"][0], y_nsr_d)], 0.24)

    # Xpsr.G = vss: use right gate pin g_pts[-1] (12.84, 10.98) -> right to x=13.90 (never crosses x_rep_trk=12.45!)
    x_psrg_trk = 13.90
    c.via1(i_psr["g_pts"][-1][0], i_psr["g_pts"][-1][1])
    c.wire("metal2", [i_psr["g_pts"][-1], (x_psrg_trk, i_psr["g_pts"][-1][1]), (x_psrg_trk, -2.70)], 0.24)
    c.via1(x_psrg_trk, -2.70)
    tie_pad_to_wall(c, (x_psrg_trk, -2.70), x_gm1)

    # Xnsr.G = vdd: hop RIGHT on M1 at y=-5.55 (cleanly crosses x_rep_trk=12.45 M2!) to x_nsrg_trk=14.60 -> M2 up to N+ wall!
    x_nsrg_trk = 14.60
    nsr_gx, nsr_gy = i_nsr["g_pts"][0]
    y_nsrg_m1 = grid(nsr_gy + 0.35)
    c.rect("metal1", grid(nsr_gx - 0.16), nsr_gy, grid(nsr_gx + 0.16), grid(y_nsrg_m1 + 0.14))
    c.wire("metal1", [(nsr_gx, y_nsrg_m1), (x_nsrg_trk, y_nsrg_m1)], 0.24)
    c.via1(x_nsrg_trk, y_nsrg_m1)
    c.wire("metal2", [(x_nsrg_trk, y_nsrg_m1), (x_nsrg_trk, 2.70)], 0.24)
    c.via1(x_nsrg_trk, 2.70)
    tie_pad_to_wall(c, (x_nsrg_trk, 2.70), x_gm1)

    # --- 8T Symmetrical Servo OTA cross-channel M3 bridges ---
    # 4 vertical M3 bridges: sda (4.91), sdb (7.00), snm (7.71 = i_snm.sds[1]), vbp_srv (9.00)
    x_br_sda, x_br_sdb, x_br_snm, x_br_vbps = 4.91, 7.00, i_snm["sds"][1], 9.00
    y_br_top = 6.40
    c.via2(x_br_sda, -6.40)
    c.via2(x_br_sda, y_br_top)
    c.wire("metal3", [(x_br_sda, -6.40), (x_br_sda, y_br_top)], 0.32)
    c.via2(x_br_sdb, -6.40)
    c.via2(x_br_sdb, y_br_top)
    c.wire("metal3", [(x_br_sdb, -6.40), (x_br_sdb, y_br_top)], 0.32)
    y_snm_d = grid(dy_snm + 0.55)  # -11.15
    for xb in (x_br_snm, x_br_vbps):
        c.via2(xb, y_snm_d)
        c.via2(xb, y_br_top)
        c.wire("metal3", [(xb, y_snm_d), (xb, y_br_top)], 0.32)

    # sda: Xsa.D -> bridge x=4.91 -> M1 at y=6.40 to x_sda_up=10.45 -> M2 up to y_sla_g -> Xsla.D & gate
    c.via1(i_sin["sds"][1], dy_sin)
    c.wire("metal2", [(i_sin["sds"][1], dy_sin), (i_sin["sds"][1], -6.40), (x_br_sda, -6.40)], 0.24)
    y_sla_d = grid(dy_sla - 0.55)  # 13.65
    y_sla_g = i_sla["g_pts"][0][1]  # ~12.88 (bottom of i_sla)
    c.via1(x_br_sda, y_br_top)
    c.wire("metal1", [(x_br_sda, y_br_top), (x_sda_up, y_br_top)], 0.24)
    c.via1(x_sda_up, y_br_top)
    c.wire("metal2", [(x_sda_up, y_br_top), (x_sda_up, y_sla_g)], 0.24)
    c.via1(x_sda_up, y_sla_g)
    c.wire("metal1", [(i_sla["g_pts"][0][0], y_sla_g), (x_sda_up, y_sla_g)], 0.24)
    c.via1(i_sla["sds"][1], y_sla_d)
    c.wire("metal2", [(i_sla["sds"][1], y_sla_d), (i_sla["sds"][1], y_sla_g)], 0.24)
    c.via1(i_sla["sds"][1], y_sla_g)

    # sdb: Xsb.D -> bridge x=7.00 -> Xslb.D & gate (offset gate tap down 0.48um to y=7.00 -> 0.25um clear of gate M1 bar!)
    c.via1(i_sin["sds"][3], dy_sin)
    c.wire("metal2", [(i_sin["sds"][3], dy_sin), (i_sin["sds"][3], -6.40), (x_br_sdb, -6.40)], 0.24)
    y_slb_d = grid(dy_slb - 0.55)  # 8.25
    y_slb_g = i_slb["g_pts"][0][1]  # 7.48
    y_slb_gt = grid(y_slb_g - 0.48)  # 7.00
    c.via1(i_slb["sds"][1], y_slb_d)
    c.wire("metal2", [(x_br_sdb, y_br_top), (x_br_sdb, y_slb_gt), (i_slb["sds"][1], y_slb_gt),
                      (i_slb["sds"][1], y_slb_d)], 0.24)
    c.via1(i_slb["sds"][1], y_slb_gt)
    c.wire("metal1", [(i_slb["g_pts"][0][0], y_slb_gt), (i_slb["sds"][1], y_slb_gt)], 0.24)
    c.rect("metal1", grid(i_slb["g_pts"][0][0] - 0.16), grid(y_slb_gt - 0.12),
           grid(i_slb["g_pts"][0][0] + 0.16), y_slb_g)

    # snm: Xsn1.D (i_snm sds[1] = x_br_snm) & gate -> bridge x_br_snm -> Xsld.D (i_slb sds[3])
    c.via1(i_snm["sds"][1], y_snm_d)
    y_snm_g = i_snm["g_pts"][0][1]
    c.via1(i_snm["g_pts"][0][0], y_snm_g)
    c.wire("metal2", [(i_snm["sds"][1], y_snm_d), (i_snm["sds"][1], y_snm_g),
                      (i_snm["g_pts"][0][0], y_snm_g)], 0.24)
    c.via1(i_slb["sds"][3], y_slb_d)
    c.wire("metal2", [(x_br_snm, y_br_top), (x_br_snm, y_slb_d), (i_slb["sds"][3], y_slb_d)], 0.24)

    # vbp_srv: Xsn2.D (i_snm sds[3]) -> bridge x_br_vbps=9.00 -> right lane x_vbps_up=9.75 -> Xslc.D & y_vbps=17.10
    c.via1(i_snm["sds"][3], y_snm_d)
    c.wire("metal2", [(i_snm["sds"][3], y_snm_d), (x_br_vbps, y_snm_d)], 0.24)
    c.wire("metal2", [(x_br_vbps, y_br_top), (x_br_vbps, 7.00), (x_vbps_up, 7.00), (x_vbps_up, y_vbps)], 0.26)
    c.via1(x_vbps_up, y_vbps)
    y_xslc_hop = 11.90
    c.via1(i_sla["sds"][3], y_sla_d)
    c.wire("metal2", [(i_sla["sds"][3], y_sla_d), (i_sla["sds"][3], y_xslc_hop)], 0.24)
    c.via1(i_sla["sds"][3], y_xslc_hop)
    c.wire("metal1", [(i_sla["sds"][3], y_xslc_hop), (x_vbps_up, y_xslc_hop)], 0.24)
    c.via1(x_vbps_up, y_xslc_hop)

    # --- Xsa (rep) & Xsb (out) gates on sin4 ---
    sin_top_pcs = sorted([p for p in i_sin["pcs"] if p[1] > dy_sin])
    sin_bot_pcs = sorted([p for p in i_sin["pcs"] if p[1] < dy_sin])

    y_xsa_g = -9.05
    for px, py in sin_bot_pcs[0:2]:
        c.rect("metal1", grid(px - 0.16), grid(y_xsa_g - 0.14), grid(px + 0.16), py)
    c.wire("metal1", [(sin_bot_pcs[0][0], y_xsa_g), (x_rep_trk, y_xsa_g)], 0.24)
    c.via1(x_rep_trk, y_xsa_g)
    c.wire("metal2", [(x_rep_trk, y_nsr_d), (x_rep_trk, y_xsa_g)], 0.26)

    # Xsb = fingers 2,3 -> top polyconts -> M1 at y=-6.25 -> x_out_drop=10.25 -> via1+via2+via3 -> elevated low-CPEX M4 straight to x_out_port!
    y_xsb_g = -6.25
    for px, py in sin_top_pcs[2:4]:
        c.rect("metal1", grid(px - 0.16), py, grid(px + 0.16), grid(y_xsb_g + 0.14))
    x_out_drop = 10.25
    c.wire("metal1", [(sin_top_pcs[2][0], y_xsb_g), (x_out_drop, y_xsb_g)], 0.20)
    c.via1(x_out_drop, y_xsb_g)
    c.via2(x_out_drop, y_xsb_g)
    via3(c, x_out_drop, y_xsb_g)
    y_ch_out = -0.95
    c.wire("metal4", [(x_out_drop, y_xsb_g), (x_out_drop, y_ch_out), (x_out_port, y_ch_out)], 0.30)

    # --- 3D-Stacked Miller MIM Cap Xcsrv (10.0 x 14.0 um, M3-M4) directly over NW cavity ---
    dx_csrv, dy_csrv = 9.10, 17.80
    c.include(csrv_c, dx=dx_csrv, dy=dy_csrv)
    x_csrv_bot = grid(dx_csrv + 5.67)
    c.via2(x_csrv_bot, y_vbps)
    c.via1(x_csrv_bot, y_vbps)
    x_csrv_top = x_rep_trk
    y_csrv_tap = 9.10
    c.rect("metal4", grid(x_csrv_top - 0.35), grid(y_csrv_tap - 0.30),
           grid(x_csrv_top + 0.35), grid(dy_csrv - 6.40))
    via3(c, x_csrv_top, y_csrv_tap)
    c.via2(x_csrv_top, y_csrv_tap)

    # =========================================================================
    # COLUMN 3: Follower OTA (Xbd, Xt, Xa/Xb 1D CC, Xla/Xlb 2D CC) + 3D Cdum
    # =========================================================================
    dx_bd, dx_tail, dx_in = grid(31.10 + S), grid(35.10 + S), grid(44.80 + S)
    dy_bd, dy_tail, dy_in = -9.60, -9.60, -8.60
    dx_ld = grid(40.90 + S)
    dy_ld0, dy_ld1 = 6.50, 15.00

    c.include(bd1_p, dx=dx_bd, dy=dy_bd, mirror_y=True)
    c.include(tail2_p, dx=dx_tail, dy=dy_tail, mirror_y=True)
    c.include(inlvt8_p, dx=dx_in, dy=dy_in)
    c.include(ldlvt16_p, dx=dx_ld, dy=dy_ld0)
    c.include(ldlvt16_p, dx=dx_ld, dy=dy_ld1, mirror_y=True)

    i_bd = prim_info(bd1_p, dx_bd, dy_bd, False, mirror_y=True)
    i_tail = prim_info(tail2_p, dx_tail, dy_tail, False, mirror_y=True)
    i_in = prim_info(inlvt8_p, dx_in, dy_in, False)
    i_ld0 = prim_info(ldlvt16_p, dx_ld, dy_ld0, True)
    i_ld1 = prim_info(ldlvt16_p, dx_ld, dy_ld1, True, mirror_y=True)

    bd_dpads = add_poly_dummies_tied(c, i_bd, True, "none", 0.0, gap=0.11)
    tail_dpads = add_poly_dummies_tied(c, i_tail, True, "none", 0.0, gap=0.11)
    y_bt_dum_tie = -6.10
    for pt in (*bd_dpads, *tail_dpads):
        c.wire("metal1", [pt, (pt[0], y_bt_dum_tie)], 0.24)
    c.wire("metal1", [(x_gm2, y_bt_dum_tie), (tail_dpads[1][0], y_bt_dum_tie)], 0.24)
    c.pad("viali", x_gm2, y_bt_dum_tie, 0.17)
    c.pad("metal1", x_gm2, y_bt_dum_tie, 0.34)

    in_dpads = add_poly_dummies_tied(c, i_in, False, "none", 0.0, gap=0.11)
    c.wire("metal1", [in_dpads[0], (in_dpads[0][0], y_vss)], 0.24)
    tie_pad_to_wall(c, in_dpads[1], x_gr)

    add_poly_dummies_tied(c, i_ld0, False, "walls", (x_gm2, x_gr), gap=0.11)
    add_poly_dummies_tied(c, i_ld1, True, "y", y_vdd, gap=0.11)

    # ibias: left port at y=-14.40 (0.85um spacing to y_vbn=-13.55 and 1.15um to y_vss=-15.55 -> clean met3.2!)
    y_ibias = -14.40
    c.wire("metal1", [(x_in_port, y_ibias), (i_tail["g_pts"][0][0], y_ibias)], 0.28)
    c.via1(i_bd["sds"][0], dy_bd)
    c.wire("metal2", [(i_bd["sds"][0], dy_bd), (i_bd["sds"][0], y_vss)], 0.26)
    c.via1(i_bd["sds"][1], dy_bd)
    c.wire("metal2", [(i_bd["sds"][1], dy_bd), (i_bd["sds"][1], y_ibias)], 0.24)
    c.via1(i_bd["sds"][1], y_ibias)
    c.via1(i_bd["g_pts"][0][0], i_bd["g_pts"][0][1])
    c.wire("metal2", [i_bd["g_pts"][0], (i_bd["g_pts"][0][0], y_ibias)], 0.24)
    c.via1(i_bd["g_pts"][0][0], y_ibias)

    strap_sd_bus(c, i_tail["sds"][::2], grid(dy_tail - 1.40), 0.30, double_y=grid(dy_tail - 2.00))
    for sx in i_tail["sds"][::2]:
        c.wire("metal2", [(sx, grid(dy_tail - 1.40)), (sx, y_vss)], 0.30)
    c.via1(i_tail["g_pts"][0][0], i_tail["g_pts"][0][1])
    c.wire("metal2", [i_tail["g_pts"][0], (i_tail["g_pts"][0][0], y_ibias)], 0.24)
    c.via1(i_tail["g_pts"][0][0], y_ibias)

    y_tail_m2 = -10.80
    y_tail_hop = grid(dy_tail + 1.80)
    x_tail_drop = grid(38.00 + S)
    c.via1(i_tail["sds"][1], grid(dy_tail + 1.20))
    c.via1(i_tail["sds"][1], y_tail_hop)
    c.wire("metal2", [(i_tail["sds"][1], grid(dy_tail + 1.20)), (i_tail["sds"][1], y_tail_hop),
                      (x_tail_drop, y_tail_hop), (x_tail_drop, y_tail_m2),
                      (i_in["sds"][0], y_tail_m2)], 0.34)
    strap_sd_bus(c, i_in["sds"][::2], y_tail_m2, 0.34, double_y=grid(y_tail_m2 + 0.65))

    y_in_dum, y_in_da = -6.40, -8.20
    in_da_xs = [i_in["sds"][1], i_in["sds"][7]]
    in_dum_xs = [i_in["sds"][3], i_in["sds"][5]]
    strap_sd_bus(c, in_dum_xs, y_in_dum, 0.30, double_y=grid(y_in_dum - 0.60))
    strap_sd_bus(c, in_da_xs, y_in_da, 0.30, double_y=grid(y_in_da - 0.60))

    in_top_pcs = sorted([p for p in i_in["pcs"] if p[1] > dy_in])
    in_bot_pcs = sorted([p for p in i_in["pcs"] if p[1] < dy_in])
    y_xb_gate = -4.85
    for px, py in in_top_pcs[2:6]:
        c.rect("metal1", grid(px - 0.16), py, grid(px + 0.16), grid(y_xb_gate + 0.14))
    c.wire("metal1", [(in_top_pcs[2][0], y_xb_gate), (in_top_pcs[5][0], y_xb_gate)], 0.28)
    for xdm in in_dum_xs:
        c.via1(xdm, y_xb_gate)
        c.wire("metal2", [(xdm, y_xb_gate), (xdm, y_in_dum)], 0.28)

    y_xa_pad = -12.40
    y_xa_out = -13.10
    x_xa_out_r = grid(51.40 + S)
    for idx in (0, 1, 6, 7):
        px, py = in_bot_pcs[idx]
        c.rect("metal1", grid(px - 0.16), grid(y_xa_pad - 0.14), grid(px + 0.16), py)
    c.wire("metal1", [(in_bot_pcs[0][0], y_xa_pad), (in_bot_pcs[1][0], y_xa_pad)], 0.20)
    c.wire("metal1", [(in_bot_pcs[6][0], y_xa_pad), (in_bot_pcs[7][0], y_xa_pad)], 0.20)
    for px in (in_bot_pcs[0][0], in_bot_pcs[7][0]):
        c.via1(px, y_xa_pad)
        c.wire("metal2", [(px, y_xa_pad), (px, y_xa_out)], 0.18)
    c.wire("metal2", [(in_bot_pcs[0][0], y_xa_out), (x_xa_out_r, y_xa_out)], 0.18)

    strap_sd_bus(c, i_ld0["sds"][::2], grid(dy_ld0 + 1.80), 0.34, double_y=grid(dy_ld0 + 2.40))
    strap_sd_bus(c, i_ld1["sds"][::2], grid(dy_ld1 + 1.80), 0.34, double_y=grid(dy_ld1 + 2.40))
    for k in (0, 4, 8, 12, 16):
        sx = i_ld1["sds"][k]
        c.wire("metal2", [(sx, grid(dy_ld1 + 1.80)), (sx, y_vdd)], 0.34)
    for k in (0, 16):
        sx = i_ld0["sds"][k]
        c.via2(sx, grid(dy_ld0 + 1.80))
        c.via2(sx, y_vdd)
        c.wire("metal3", [(sx, grid(dy_ld0 + 1.80)), (sx, y_vdd)], 0.44)

    ld0_da_xs = [i_ld0["sds"][k] for k in (1, 7, 9, 15)]
    ld0_dum_xs = [i_ld0["sds"][k] for k in (3, 5, 11, 13)]
    ld1_da_xs = [i_ld1["sds"][k] for k in (3, 5, 11, 13)]
    ld1_dum_xs = [i_ld1["sds"][k] for k in (1, 7, 9, 15)]

    y_ld0_da, y_ld0_dum = grid(dy_ld0 - 2.10), grid(dy_ld0 - 0.10)
    y_ld1_da, y_ld1_dum = grid(dy_ld1 - 2.10), grid(dy_ld1 - 0.10)
    strap_sd_bus(c, ld0_da_xs, y_ld0_da, 0.30, double_y=grid(y_ld0_da + 0.65))
    strap_sd_bus(c, ld0_dum_xs, y_ld0_dum, 0.30, double_y=grid(y_ld0_dum + 0.65))
    strap_sd_bus(c, ld1_da_xs, y_ld1_da, 0.30, double_y=grid(y_ld1_da + 0.65))
    strap_sd_bus(c, ld1_dum_xs, y_ld1_dum, 0.30, double_y=grid(y_ld1_dum + 0.65))

    y_ld_gate = 10.75
    x_da_trunk = grid(29.10 + S)
    c.wire("metal1", [(x_da_trunk, y_ld_gate), (i_ld0["g_pts"][-1][0], y_ld_gate)], 0.28)
    for gx in (i_ld0["g_pts"][0][0], i_ld0["g_pts"][7][0], i_ld0["g_pts"][-1][0]):
        y0g, y1g = i_ld0["g_pts"][0][1], i_ld1["g_pts"][0][1]
        c.wire("metal1", [(gx, y0g), (gx, y_ld_gate)], 0.28)
        c.wire("metal1", [(gx, y1g), (gx, y_ld_gate)], 0.28)

    y_ch_da = 1.10
    c.wire("metal2", [(ld1_da_xs[0], y_ld1_da), (x_da_trunk, y_ld1_da),
                      (x_da_trunk, y_ch_da)], 0.32)
    c.wire("metal2", [(ld0_da_xs[0], y_ld0_da), (x_da_trunk, y_ld0_da)], 0.32)
    c.via1(x_da_trunk, y_ld_gate)
    c.via1(x_da_trunk, y_ch_da)
    c.wire("metal1", [(x_da_trunk, y_ch_da), (in_da_xs[0], y_ch_da)], 0.28)
    c.via1(in_da_xs[0], y_ch_da)
    c.wire("metal2", [(in_da_xs[0], y_ch_da), (in_da_xs[0], y_in_da)], 0.30)

    # =========================================================================
    # CENTER CHANNEL: VSS-shielded `out` & matched `dum` + 3D-stacked `Cdum`
    # =========================================================================
    # Single lower VSS guard bar below elevated M4 out trunk (isolates NMOS channel without extra M1-M4 plate cap)
    y_sh_lo, y_ch_dum = -1.95, 0.35
    c.wire("metal1", [(x_gm2, y_sh_lo), (x_gr, y_sh_lo)], 0.20)
    for xg in (x_gm2, x_gr):
        c.via1(xg, y_sh_lo)
        c.wire("metal2", [(xg, y_sh_lo), (xg, y_vss)], 0.26)

    # Tap elevated M4 out trunk at x_out_stem, x_xa_out_r, and x_out_port (all 0.0% M5, minimal CPEX!)
    c.via2(x_out_stem, y_ch_out)
    via3(c, x_out_stem, y_ch_out)
    via3(c, x_xa_out_r, y_ch_out)
    c.via2(x_xa_out_r, y_ch_out)
    c.wire("metal2", [(x_xa_out_r, y_xa_out), (x_xa_out_r, y_ch_out)], 0.18)
    via3(c, x_out_port, y_ch_out)
    c.pad("metal3", x_out_port, y_ch_out, 0.56)

    x_dum_trunk = grid(52.70 + S)
    c.via1(x_dum_stem, y_ch_dum)
    c.wire("metal1", [(x_dum_stem, y_ch_dum), (x_dum_trunk, y_ch_dum)], 0.32)
    c.via1(in_dum_xs[0], y_ch_dum)
    c.wire("metal2", [(in_dum_xs[0], y_ch_dum), (in_dum_xs[0], y_xb_gate)], 0.28)
    c.via1(x_dum_trunk, y_ch_dum)
    c.wire("metal2", [(x_dum_trunk, y_ch_dum), (x_dum_trunk, y_ld1_dum),
                      (ld1_dum_xs[-1], y_ld1_dum)], 0.32)
    c.wire("metal2", [(ld0_dum_xs[-1], y_ld0_dum), (x_dum_trunk, y_ld0_dum)], 0.32)

    dx_cd, dy_cd = grid(40.90 + S), 7.20
    c.include(cdum_c, dx=dx_cd, dy=dy_cd)
    x_cd_vss = grid(dx_cd + 6.71)
    c.wire("metal3", [(x_cd_vss, dy_cd), (x_cd_vss, y_vss)], 1.00)
    x_cd_dum = dx_cd
    c.rect("metal4", grid(x_cd_dum - 0.50), grid(dy_cd + 5.00),
           grid(x_cd_dum + 0.50), grid(y_ld1_dum + 0.35))
    via3(c, x_cd_dum, y_ld1_dum)
    c.via2(x_cd_dum, y_ld1_dum)

    port_y = {
        "up": y_up_bot,
        "dn": y_dn_ch,
        "vbn": y_vbn,
        "vbp": y_vbp,
        "ibias": y_ibias,
    }
    for pname, py in port_y.items():
        c.via1(x_in_port, py)
        c.via2(x_in_port, py)
        c.pad("metal3", x_in_port, py, 0.50)

    c.port("up", "metal3", x_in_port, port_y["up"])
    c.port("dn", "metal3", x_in_port, port_y["dn"])
    c.port("out", "metal3", x_out_port, y_ch_out)
    c.port("vbn", "metal3", x_in_port, port_y["vbn"])
    c.port("vbp", "metal3", x_in_port, port_y["vbp"])
    c.port("ibias", "metal3", x_in_port, port_y["ibias"])
    c.port("vdd", "metal3", x_in_port, y_vdd)
    c.port("vss", "metal3", x_in_port, y_vss)
    c.write(w / f"{cell}.mag")

    ref_lines = [
        "* Physical LVS reference for pll_cp_steer_v4 (k=4, Icp=200 uA, wide-swing + active replica servo)",
        f".subckt {cell} up dn out vbn vbp ibias vdd vss",
        "Xupn up_b up vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.88",
        "Xupp up_b up vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xdn1_n dn_b dn vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xdn1_p dn_b dn vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xdn2_n dn_on dn_b vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xdn2_p dn_on dn_b vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xp ps vbp_srv vdd vdd sky130_fd_pr__pfet_01v8 w=112 l=1",
        "Xps out up_b ps vdd sky130_fd_pr__pfet_01v8 w=24 l=0.15",
        "Xpd dum up ps vdd sky130_fd_pr__pfet_01v8 w=24 l=0.15",
        "Xns out dn_on ns vss sky130_fd_pr__nfet_01v8 w=8 l=0.15",
        "Xnd dum dn_b ns vss sky130_fd_pr__nfet_01v8 w=8 l=0.15",
        "Xn ns vbn vss vss sky130_fd_pr__nfet_01v8 w=20 l=1",
        "Xpr psr vbp_srv vdd vdd sky130_fd_pr__pfet_01v8 w=28 l=1",
        "Xpsr rep vss psr vdd sky130_fd_pr__pfet_01v8 w=6 l=0.15",
        "Xnsr rep vdd nsr vss sky130_fd_pr__nfet_01v8 w=2 l=0.15",
        "Xnr nsr vbn vss vss sky130_fd_pr__nfet_01v8 w=5 l=1",
        "Xsb_p sbn vbp vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=1",
        "Xsb_n sbn sbn vss vss sky130_fd_pr__nfet_01v8 w=2 l=1",
        "Xst stail sbn vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        "Xsa sda rep stail vss sky130_fd_pr__nfet_01v8_lvt w=2 l=1",
        "Xsb sdb out stail vss sky130_fd_pr__nfet_01v8_lvt w=2 l=1",
        "Xsla sda sda vdd vdd sky130_fd_pr__pfet_01v8_lvt w=4 l=1",
        "Xslb sdb sdb vdd vdd sky130_fd_pr__pfet_01v8_lvt w=4 l=1",
        "Xslc vbp_srv sda vdd vdd sky130_fd_pr__pfet_01v8_lvt w=4 l=1",
        "Xsld snm sdb vdd vdd sky130_fd_pr__pfet_01v8_lvt w=4 l=1",
        "Xsn1 snm snm vss vss sky130_fd_pr__nfet_01v8 w=4 l=1",
        "Xsn2 vbp_srv snm vss vss sky130_fd_pr__nfet_01v8 w=4 l=1",
        f"Xcsrv rep vbp_srv {MIM_MODEL} w=10.0 l=14.0",
        "Xbd ibias ibias vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        "Xt tail ibias vss vss sky130_fd_pr__nfet_01v8 w=10 l=1",
        "Xa da out tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xb dum dum tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        "Xlb dum da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        f"Xcdum dum vss {MIM_MODEL} w=12.08 l=12.08",
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False, timeout=120,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True, timeout=120,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(w / f"{cell}.mag").bbox()
    return {
        "cell": cell,
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)

    r = build_cp_steer_v4(out)
    print(
        f"{r['cell']:28s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | "
        f"size={r['size_um']} um | area={r['area_um2']} um2",
        flush=True,
    )
    (out / "summary.json").write_text(json.dumps([r], indent=2) + "\n")
    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        cdir = out / r["cell"]
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
            src = cdir / f"{r['cell']}{ext}"
            if src.exists():
                shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
