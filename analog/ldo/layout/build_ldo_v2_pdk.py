#!/usr/bin/env python3
"""Build and verify the LDO v2 Stacked+Fused MIM2 PDK layout (probe & production macros).

Architecture & physical design highlights (~36,500-37,800 um^2, -59% vs smallcap, -80% vs r4):
  1. 60.00 pF Stacked + Fused MIM1/MIM2 bay (M3-M4-M5, tiles <= 29.415 um < 30 um PDK wmax)
     with dense multi-via3 (8-12) + multi-via4 (2-4) outer-plate pillars (zero single-via3 ESR).
  2. 3D Under-MIM passive & low-voltage reuse (strictly M1/M2 under MIM plates):
     - High-R w=0.50 um, l=75.640 um (50 kOhm/bar, nx>=5 shared-RPM DRC=0) filter arrays:
       Xrefres (1.6 MOhm), Xrpre_off (1.2 MOhm), Xrcas (400 kOhm), Xrpre (400 kOhm),
       and shared Xcl_rref+Xcl_rhp (200 kOhm + 50 kOhm).
     - Head-R-calibrated 47-bar unit-matched divider (w=1.0 um, l=11.425 um -> 4.000 kOhm/bar):
       26-bar common-centroid symmetric palindrome interleaving Rtop (10) & Rfixed (16) +
       21-bar binary trim array (R0..R5) with 0.00% head-R ratio error.
     - Active 0.15 um proportional overshoot clamp tucked under Xcout right next to Xpass.
     - Bias copy (reused serdes_bias_pcopy_pdk), enable inverter, ref tgate & reset, 6 trim switches.
  3. MIM-free East Active Analog & Power Column:
     - HV PMOS pre-regulator Xpre_p in isolated vin N-well (>= 2.8 um separation from va N-well).
     - Common-centroid 2D AB/BA quad diff pair Xpl/Xpr + matched NMOS mirrors Xnb/Xnr & Xnl/Xnm.
     - Full-height P+ substrate guard barrier isolating EA from the 10 mA power stage.
     - East IO-edge NVT power stage (Xcas w=2000, Xpass w=1200) with wide M4/M5 power plates
       (>= 16-18 um), dense via2/via3/via4 arrays, and dedicated Kelvin sense from the East
       perimeter quiet port back to Xrtop (< 5 mV RCX IR drop at 10 mA).
  4. All 13 production ports (15 probe ports) exported cleanly on the macro perimeter in exact
     schematic subckt order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "verification/layout"))
from check import exported_ports  # noqa: E402
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402
from summarize_parasitics import summarize_pex_spice  # noqa: E402

SPICE_DIR = REPO / "analog/ldo/spice"
BIAS_SPICE_DIR = REPO / "analog/bias/spice"
COMMON_SPICE_DIR = REPO / "analog/common/devices/spice"
BIAS_LAYOUT_DIR = REPO / "analog/bias/layout/variants/pdk"

M1 = "sky130_fd_pr__cap_mim_m3_1"
M2 = "sky130_fd_pr__cap_mim_m3_2"

PROD_PORTS = ["vin", "host", "quiet", "bg", "vgi", "enable", "t0", "t1", "t2", "t3", "t4", "t5", "vss"]
PROBE_PORTS = ["vin", "host", "quiet", "bg", "vgi", "enable", "t0", "t1", "t2", "t3", "t4", "t5", "fb_return", "fb_input", "vss"]


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via2_clean(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.via2(x, y)
    c.pad("metal3", x, y, 0.52)


def via3_single(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def via3_array(c: Cell, x: float, y: float, nx: int = 2, ny: int = 2, pitch: float = 0.70) -> None:
    x0 = x - (nx - 1) * pitch / 2.0
    y0 = y - (ny - 1) * pitch / 2.0
    hw = (nx - 1) * pitch / 2.0 + 0.35
    hh = (ny - 1) * pitch / 2.0 + 0.35
    c.rect("metal3", grid(x - hw), grid(y - hh), grid(x + hw), grid(y + hh))
    c.rect("metal4", grid(x - hw), grid(y - hh), grid(x + hw), grid(y + hh))
    for ix in range(nx):
        for iy in range(ny):
            c.pad("via3", grid(x0 + ix * pitch), grid(y0 + iy * pitch), 0.32)


def via34_pillar(c: Cell, x: float, y: float, big: bool = True) -> None:
    x, y = grid(x), grid(y)
    if big:
        c.rect("metal3", grid(x - 2.1), grid(y - 2.1), grid(x + 2.1), grid(y + 2.1))
        c.rect("metal4", grid(x - 2.2), grid(y - 2.2), grid(x + 2.2), grid(y + 2.2))
        c.rect("metal5", grid(x - 2.4), grid(y - 2.4), grid(x + 2.4), grid(y + 2.4))
        for vx in (-1.35, -0.45, 0.45, 1.35):
            for vy in (-0.90, 0.0, 0.90):
                c.pad("via3", grid(x + vx), grid(y + vy), 0.32)
        for vx in (-1.05, 1.05):
            for vy in (-1.05, 1.05):
                c.pad("via4", grid(x + vx), grid(y + vy), 1.18)
    else:
        c.rect("metal3", grid(x - 2.1), grid(y - 1.1), grid(x + 2.1), grid(y + 1.1))
        c.rect("metal4", grid(x - 2.2), grid(y - 1.2), grid(x + 2.2), grid(y + 1.2))
        c.rect("metal5", grid(x - 2.4), grid(y - 1.3), grid(x + 2.4), grid(y + 1.3))
        for vx in (-1.35, -0.45, 0.45, 1.35):
            for vy in (-0.45, 0.45):
                c.pad("via3", grid(x + vx), grid(y + vy), 0.32)
        for vx in (-1.05, 1.05):
            c.pad("via4", grid(x + vx), y, 1.18)


def via34_pillar_v(c: Cell, x: float, y: float) -> None:
    """Tall narrow via34 pillar (X half-width 1.3 um) for West macro spine."""
    x, y = grid(x), grid(y)
    c.rect("metal3", grid(x - 1.1), grid(y - 2.1), grid(x + 1.1), grid(y + 2.1))
    c.rect("metal4", grid(x - 1.2), grid(y - 2.2), grid(x + 1.2), grid(y + 2.2))
    c.rect("metal5", grid(x - 1.3), grid(y - 2.4), grid(x + 1.3), grid(y + 2.4))
    for vx in (-0.45, 0.45):
        for vy in (-1.35, -0.45, 0.45, 1.35):
            c.pad("via3", grid(x + vx), grid(y + vy), 0.32)
    for vy in (-1.05, 1.05):
        c.pad("via4", x, grid(y + vy), 1.18)


def via4_array(c: Cell, x: float, y: float, nx: int = 2, ny: int = 2, pitch: float = 2.10) -> None:
    x0 = x - (nx - 1) * pitch / 2.0
    y0 = y - (ny - 1) * pitch / 2.0
    hw = (nx - 1) * pitch / 2.0 + 1.05
    hh = (ny - 1) * pitch / 2.0 + 1.05
    c.rect("metal4", grid(x - hw), grid(y - hh), grid(x + hw), grid(y + hh))
    c.rect("metal5", grid(x - hw - 0.15), grid(y - hh - 0.15), grid(x + hw + 0.15), grid(y + hh + 0.15))
    for ix in range(nx):
        for iy in range(ny):
            c.pad("via4", grid(x0 + ix * pitch), grid(y0 + iy * pitch), 1.18)


def draw_pwell_guard_h(c: Cell, x1: float, x2: float, y: float, h: float = 1.00) -> None:
    x1, x2, y = grid(x1), grid(x2), grid(y)
    c.rect("pwell", grid(x1 - 0.5), grid(y - h / 2 - 0.5), grid(x2 + 0.5), grid(y + h / 2 + 0.5))
    c.rect("mvpsubdiff", x1, grid(y - h / 2), x2, grid(y + h / 2))
    c.rect("mvpsubdiffcont", grid(x1 + 0.2), grid(y - 0.17), grid(x2 - 0.2), grid(y + 0.17))
    c.rect("locali", x1, grid(y - h / 2), x2, grid(y + h / 2))
    c.rect("metal1", x1, grid(y - h / 2), x2, grid(y + h / 2))
    c.rect("metal2", x1, grid(y - 0.36), x2, grid(y + 0.36))
    span = x2 - x1
    n_pts = max(2, int(span // 4.0))
    for i in range(n_pts + 1):
        px = grid(x1 + 0.5 + (span - 1.0) * i / n_pts)
        c.pad("viali", px, y, 0.17)
        c.via1(px, y)


def draw_pwell_guard_v(
    c: Cell, x: float, y1: float, y2: float, w: float = 1.20, m3_y1: float | None = None
) -> None:
    x, y1, y2 = grid(x), grid(y1), grid(y2)
    m3_bot = grid(m3_y1) if m3_y1 is not None else y1
    c.rect("pwell", grid(x - w / 2 - 0.5), grid(y1 - 0.5), grid(x + w / 2 + 0.5), grid(y2 + 0.5))
    c.rect("mvpsubdiff", grid(x - w / 2), y1, grid(x + w / 2), y2)
    c.rect("mvpsubdiffcont", grid(x - 0.17), grid(y1 + 0.2), grid(x + 0.17), grid(y2 - 0.2))
    c.rect("locali", grid(x - w / 2), y1, grid(x + w / 2), y2)
    c.rect("metal1", grid(x - w / 2), y1, grid(x + w / 2), y2)
    c.rect("metal2", grid(x - 0.40), y1, grid(x + 0.40), y2)
    c.rect("metal3", grid(x - 0.50), m3_bot, grid(x + 0.50), y2)
    span = y2 - y1
    n_pts = max(2, int(span // 4.0))
    for i in range(n_pts + 1):
        py = grid(y1 + 0.5 + (span - 1.0) * i / n_pts)
        c.pad("viali", x, py, 0.17)
        c.via1(x, py)
        c.via2(x, py)


def place_stacked_mim(
    c: Cell, work: Path, tag: str, side: float, cols: int, rows: int,
    dx_c: float, dy_c: float, shared_vss: bool = False,
    a_off: float = 1.90, b3_off: float = 1.90, b5_off: float = 2.60, pillar_dx: float = 3.60,
) -> dict:
    """Place an aligned stacked MIM1+MIM2 (M3-M4-M5) block centered at (dx_c, dy_c)."""
    lower = pdk_device(work, f"mim1_{tag}", M1, dict(w=side, l=side, nx=cols, ny=rows, stack=1, doports=1))
    upper = pdk_device(work, f"mim2_{tag}", M2, dict(w=side, l=side, nx=cols, ny=rows, doports=1))
    for cc in (lower, upper):
        cc.rects.pop("checkpaint", None)
    lp = sorted(lower.rects["mimcapcontact"], key=lambda r: (r[0], r[1]))
    up = sorted([(-r[2], r[1], -r[0], r[3]) for r in upper.rects["mimcap2contact"]], key=lambda r: (r[0], r[1]))
    if len(lp) != cols * rows or len(up) != cols * rows:
        raise RuntimeError(f"MIM plate count mismatch for {tag}")
    adx = grid((lp[0][0] + lp[0][2] - up[0][0] - up[0][2]) / 2.0)
    ady = grid((lp[0][1] + lp[0][3] - up[0][1] - up[0][3]) / 2.0)
    for a, b in zip(lp, up):
        if max(abs(a[k] - b[k] - (adx if k % 2 == 0 else ady)) for k in range(4)) > 0.02:
            raise RuntimeError(f"MIM alignment mismatch for {tag}")

    a_pts = sorted([(grid(x + dx_c), grid(y + dy_c)) for _, x, y, nm in lower.labels if nm.startswith("C1")])
    b3_pts = sorted([(grid(x + dx_c), grid(y + dy_c)) for _, x, y, nm in lower.labels if nm.startswith("C2")])
    b5_pts = sorted([(grid(-x + adx + dx_c), grid(y + ady + dy_c)) for _, x, y, nm in upper.labels if nm.startswith("C1")])
    lower.labels.clear()
    upper.labels.clear()

    c.include(lower, dx=dx_c, dy=dy_c)
    c.include(upper, dx=grid(dx_c + adx), dy=grid(dy_c + ady), mirror_x=True)

    # True union bbox of lower + mirrored upper!
    lx1, ly1, lx2, ly2 = lower.bbox()
    ux1, uy1, ux2, uy2 = upper.bbox()
    bx1 = grid(min(lx1 + dx_c, -ux2 + adx + dx_c))
    bx2 = grid(max(lx2 + dx_c, -ux1 + adx + dx_c))
    by1 = grid(min(ly1 + dy_c, uy1 + ady + dy_c))
    by2 = grid(max(ly2 + dy_c, uy2 + ady + dy_c))

    ya = grid(by2 + a_off)
    for x, y in a_pts:
        c.wire("metal4", [(x, y), (x, ya)], 0.80)
    if len(a_pts) > 1:
        c.wire("metal4", [(a_pts[0][0], ya), (a_pts[-1][0], ya)], 0.80)

    yb3 = grid(by1 - b3_off)
    for x, y in b3_pts:
        c.wire("metal3", [(x, y), (x, yb3)], 0.80)
    if len(b3_pts) > 1:
        c.wire("metal3", [(b3_pts[0][0], yb3), (b3_pts[-1][0], yb3)], 1.00)

    yb5 = grid(by2 + b5_off)
    for x, y in b5_pts:
        c.wire("metal5", [(x, y), (x, yb5)], 1.60)
    if len(b5_pts) > 1:
        c.wire("metal5", [(b5_pts[0][0], yb5), (b5_pts[-1][0], yb5)], 1.60)

    b_pin = (b3_pts[0][0], yb3)
    if not shared_vss:
        xg = grid(bx2 + pillar_dx)
        yp = grid(dy_c)
        c.wire("metal3", [(b3_pts[-1][0], yb3), (xg, yb3), (xg, yp)], 1.00)
        c.wire("metal5", [(b5_pts[-1][0], yb5), (xg, yb5), (xg, yp)], 1.60)
        via34_pillar(c, xg, yp, big=False)
        b_pin = (xg, yp)

    return {
        "a": (a_pts[-1][0], ya),
        "a_left": (a_pts[0][0], ya),
        "a_pts": a_pts,
        "ya": ya,
        "b": b_pin,
        "b3_pts": b3_pts,
        "yb3": yb3,
        "b5_pts": b5_pts,
        "yb5": yb5,
        "bbox": (bx1, by1, bx2, by2),
    }


def strap_mos_5v_multirow(
    c: Cell, prim: Cell, cut_layer: str, dx: float, dy: float, tie_sb: bool = False, m3_gate: bool = True
) -> dict:
    p = Cell()
    p.include(prim)
    sd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    sd_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects[cut_layer]})
    fh = sorted({round(r[3] - r[1], 3) for r in prim.rects[cut_layer]})[0]
    g_pts = sorted({(grid(x + dx), grid(y + dy)) for _, x, y, lbl in prim.labels if lbl.startswith("G")})
    bx, by = prim.pins("B")[0]
    bx, by = grid(bx + dx), grid(by + dy)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    d_xs = sd_xs[::2]
    s_xs = sd_xs[1::2]
    g_ys = sorted({y for _, y in g_pts})
    g_xs = sorted({x for x, _ in g_pts})

    via_offsets = [-3.6, 0.0, 3.6] if fh >= 8.0 else ([-1.2, 1.2] if fh >= 3.5 else [0.0])
    y_bot_f = grid(sd_ys[0] + via_offsets[0])
    y_top_f = grid(sd_ys[-1] + via_offsets[-1])
    d_bus_y = grid(max(y_top_f, max(g_ys)) + 0.65)
    s_bus_y = grid(y_bot_f - 0.65)

    for x in d_xs:
        for y0 in sd_ys:
            for vo in via_offsets:
                c.via1(x, grid(y0 + vo))
        c.wire("metal2", [(x, y_bot_f), (x, d_bus_y)], 0.36)
    c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.56)

    for x in s_xs:
        for y0 in sd_ys:
            for vo in via_offsets:
                c.via1(x, grid(y0 + vo))
        c.wire("metal2", [(x, s_bus_y), (x, y_top_f)], 0.36)
    c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.56)

    gx = g_xs[0]
    for gy in g_ys:
        if m3_gate:
            c.via1(gx, gy)
            via2_clean(c, gx, gy)
    if len(g_ys) > 1 and m3_gate:
        c.wire("metal3", [(gx, g_ys[0]), (gx, g_ys[-1])], 0.44)

    c.body_contact(bx, by)
    if tie_sb:
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[0], by), (bx, by)], 0.36)

    return {
        "D": (d_xs[0], d_bus_y),
        "S": (s_xs[0], s_bus_y),
        "d_bus_y": d_bus_y,
        "s_bus_y": s_bus_y,
        "G": (gx, g_ys[0]),
        "gx": gx,
        "g_ys": g_ys,
        "B": (bx, by),
        "d_xs": d_xs,
        "s_xs": s_xs,
    }


def strap_mos_5v_single(
    c: Cell, prim: Cell, cut_layer: str, dx: float, dy: float, tie_sb: bool = False
) -> dict:
    p = Cell()
    p.include(prim)
    sd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    cut_h = max(r[3] - r[1] for r in prim.rects[cut_layer])
    g_pts = sorted({(grid(x + dx), grid(y + dy)) for _, x, y, lbl in prim.labels if lbl.startswith("G")})
    bx, by = prim.pins("B")[0]
    bx, by = grid(bx + dx), grid(by + dy)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    d_xs = sd_xs[::2]
    s_xs = sd_xs[1::2]
    off_y = min(1.8, max(0.5, cut_h / 2.0 - 0.6))
    d_bus_y = grid(dy + off_y)
    s_bus_y = grid(dy - off_y)

    for x in d_xs:
        c.via1(x, d_bus_y)
    if len(d_xs) > 1:
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.40)

    for x in s_xs:
        c.via1(x, s_bus_y)
    if len(s_xs) > 1:
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.40)

    gx, gy = g_pts[0]
    c.via1(gx, gy)
    c.body_contact(bx, by)
    if tie_sb:
        # Tie S to B cleanly at s_xs[0] (offset from bx if nf=1 so no met2.2 with G/D!)
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[0], by), (bx, by)], 0.34)

    return {
        "D": (d_xs[0], d_bus_y),
        "S": (s_xs[0], s_bus_y),
        "G": (gx, gy),
        "B": (bx, by),
        "d_xs": d_xs,
        "s_xs": s_xs,
    }


def strap_mos_5v_single_dummies(
    c: Cell, prim: Cell, cut_layer: str, dx: float, dy: float, tie_outer_to_s: bool = False
) -> dict:
    """Strap a guard=0, conn_gates=0 5V FET with 1 tied-off outer dummy finger on each end.

    Outer dummy fingers (G0, G_last) share continuous active diffusion with the inner active
    array (eliminating outer-finger LOD/STI mismatch).
      - Active S = sd_xs[1::2], active D = sd_xs[2:-1:2]
      - Outer G0 & sd_xs[0] tied together on M1; outer G_last & sd_xs[-1] tied together on M1.
      - If tie_outer_to_s=True (NMOS mirror Xnl/Xnm): outer diffusions tie to s_bus_y (vss),
        so G=S=D=B=vss on both dummy fingers.
      - If tie_outer_to_s=False (PMOS diff pair Xpl/Xpr): outer diffusions export via1 at y=dy
        ("dum_l", "dum_r") for a planar horizontal M2 tie to va (G=D=B=va, S=tail, strictly off).
    """
    p = Cell()
    p.include(prim)
    sd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    cut_h = max(r[3] - r[1] for r in prim.rects[cut_layer])
    g_pts = sorted(
        [(int(lbl[1:]), grid(x + dx), grid(y + dy)) for _, x, y, lbl in prim.labels if lbl.startswith("G")],
        key=lambda t: t[0],
    )
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    s_xs = sd_xs[1::2]
    d_xs = sd_xs[2:-1:2]
    off_y = min(1.8, max(0.5, cut_h / 2.0 - 0.6))
    d_bus_y = grid(dy + off_y)
    s_bus_y = grid(dy - off_y)

    # Inner active gates G1..G_{nf-2}: flush 0.22 um M1 bar inside existing polycont M1 (>=0.16 um clear of S/D M1!)
    # Place via1 at G2 (not G1) so p_pl_a.G stays >=1.6 um clear of x_fbin_p (213.0) via2!
    _, gx1, gy = g_pts[1]
    _, gx_tap, _ = g_pts[2]
    _, gx_last_act, _ = g_pts[-2]
    c.wire("metal1", [(gx1, gy), (gx_last_act, gy)], 0.22)
    c.via1(gx_tap, gy)

    # Outer dummy gates G0 -> sd_xs[0] and G_last -> sd_xs[-1]: solid notch-free M1 corner bridge + vertical drop
    _, gx0, _ = g_pts[0]
    _, gxn, _ = g_pts[-1]
    y_dum = s_bus_y if tie_outer_to_s else grid(dy - 1.00)
    y_m1_top = grid(gy + 0.11)
    y_m1_join = grid(dy + 2.44)
    c.rect("metal1", grid(sd_xs[0] - 0.115), y_m1_join, gx0, y_m1_top)
    c.rect("metal1", gxn, y_m1_join, grid(sd_xs[-1] + 0.115), y_m1_top)
    c.wire("metal1", [(sd_xs[0], y_m1_join), (sd_xs[0], y_dum)], 0.23)
    c.wire("metal1", [(sd_xs[-1], y_m1_join), (sd_xs[-1], y_dum)], 0.23)

    # Active D bus (M2 at d_bus_y)
    for x in d_xs:
        c.via1(x, d_bus_y)
    if len(d_xs) > 1:
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.44)

    # Active S bus (M2 at s_bus_y), plus outer dummy diffusions when tie_outer_to_s=True
    s_all = ([sd_xs[0]] + s_xs + [sd_xs[-1]]) if tie_outer_to_s else s_xs
    for x in s_all:
        c.via1(x, s_bus_y)
    if len(s_all) > 1:
        c.wire("metal2", [(s_all[0], s_bus_y), (s_all[-1], s_bus_y)], 0.44)

    if not tie_outer_to_s:
        c.via1(sd_xs[0], y_dum)
        c.via1(sd_xs[-1], y_dum)

    return {
        "D": (d_xs[0], d_bus_y),
        "S": (s_all[0], s_bus_y),
        "S_right": (s_all[-1], s_bus_y),
        "G": (gx_tap, gy),
        "dum_l": (sd_xs[0], y_dum),
        "dum_r": (sd_xs[-1], y_dum),
        "d_xs": d_xs,
        "s_xs": s_all,
    }


def strap_1v8_m2(
    c: Cell, prim: Cell, cut_layer: str, dx: float, dy: float, tie_sb: bool = False
) -> dict:
    p = Cell()
    p.include(prim)
    sd_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    sd_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects[cut_layer]})
    cut_h = sorted({round(r[3] - r[1], 3) for r in prim.rects[cut_layer]})[0]
    g_pts = sorted({(grid(x + dx), grid(y + dy)) for _, x, y, lbl in prim.labels if lbl.startswith("G")})
    bot_li = min(prim.rects["locali"], key=lambda r: (r[1] + r[3]) / 2.0)
    bx = grid(prim.rects[cut_layer][0][0] - 0.50 + dx)
    by = grid((bot_li[1] + bot_li[3]) / 2.0 + dy)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    d_xs = sd_xs[::2]
    s_xs = sd_xs[1::2]
    g_ys = sorted({y for _, y in g_pts})
    g_xs = sorted({x for x, _ in g_pts})

    if len(sd_ys) == 1:
        off = min(0.80, max(0.32, cut_h / 2.0 - 0.18))
        d_bus_y = grid(sd_ys[0] + off)
        s_bus_y = grid(sd_ys[0] - off)
        for x in d_xs:
            c.via1(x, d_bus_y)
        if len(d_xs) > 1:
            c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.30)
        for x in s_xs:
            c.via1(x, s_bus_y)
        if len(s_xs) > 1:
            c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.30)
        gx, gy = g_xs[0], grid(g_ys[0] + 0.16)
        c.via1(gx, gy)
    else:
        d_bus_y = grid(max(g_ys) + 0.70)
        s_bus_y = grid(sd_ys[0] - cut_h / 2.0 - 0.35)
        for x in d_xs:
            for y0 in sd_ys:
                c.via1(x, y0)
            c.wire("metal2", [(x, sd_ys[0]), (x, d_bus_y)], 0.26)
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.56)
        for x in s_xs:
            for y0 in sd_ys:
                c.via1(x, y0)
            c.wire("metal2", [(x, s_bus_y), (x, sd_ys[-1])], 0.26)
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.56)
        gx_m1 = grid(min(sd_xs) - 1.15)
        for gy in g_ys:
            c.wire("metal1", [(gx_m1, gy), (g_xs[0], gy)], 0.24)
        c.wire("metal1", [(gx_m1, g_ys[0]), (gx_m1, g_ys[-1])], 0.28)
        gx, gy = gx_m1, grid((g_ys[0] + g_ys[-1]) / 2.0)
        c.via1(gx, gy)

    c.body_contact(bx, by)
    if tie_sb:
        if len(sd_ys) > 1:
            # Fill solid M2 patch between S bus and B to avoid narrow M2 notch (< 0.14 um met2.2)
            c.rect("metal2", grid(min(bx, s_xs[0]) - 0.15), grid(by - 0.15), grid(s_xs[0] + 0.15), grid(s_bus_y + 0.28))
        else:
            c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[0], by), (bx, by)], 0.30)

    return {
        "D": (d_xs[0], d_bus_y),
        "D_right": (d_xs[-1], d_bus_y),
        "S": (s_xs[0], s_bus_y),
        "S_right": (s_xs[-1], s_bus_y),
        "G": (gx, gy),
        "B": (bx, by),
        "d_xs": d_xs,
        "s_xs": s_xs,
    }


def place_res_snake(
    c: Cell, prim: Cell, n: int, dx: float, dy: float, split_idx: int | None = None, reverse: bool = False
) -> dict:
    p = Cell()
    p.include(prim)
    pts_r1 = [prim.pins(f"R1_{i}")[0] for i in range(n)]
    pts_r2 = [prim.pins(f"R2_{i}")[0] for i in range(n)]
    bx, by = prim.pins("B")[0]
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)

    r1 = [(grid(x + dx), grid(y + dy)) for x, y in pts_r1]
    r2 = [(grid(x + dx), grid(y + dy)) for x, y in pts_r2]
    b_pt = (grid(bx + dx), grid(by + dy))
    c.body_contact(*b_pt)

    mid_pt = None
    for i in range(n - 1):
        if i % 2 == 0:
            c.wire("metal1", [r2[i], r2[i + 1]], 0.36)
            if split_idx == i + 1:
                mid_pt = r2[i + 1]
        else:
            c.wire("metal1", [r1[i], r1[i + 1]], 0.36)
            if split_idx == i + 1:
                mid_pt = r1[i + 1]

    start = r1[0]
    end = r1[n - 1] if n % 2 == 0 else r2[n - 1]
    if reverse:
        start, end = end, start
    c.via1(*start)
    c.via1(*end)
    if mid_pt is not None:
        c.via1(*mid_pt)
    return {"a": start, "b": end, "mid": mid_pt, "B": b_pt}


def place_res_single(c: Cell, prim: Cell, dx: float, dy: float) -> dict:
    p = Cell()
    p.include(prim)
    r1x, r1y = prim.pins("R1")[0]
    r2x, r2y = prim.pins("R2")[0]
    bx, by = prim.pins("B")[0]
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)
    p1 = (grid(r1x + dx), grid(r1y + dy))
    p2 = (grid(r2x + dx), grid(r2y + dy))
    pb = (grid(bx + dx), grid(by + dy))
    c.via1(*p1)
    c.via1(*p2)
    c.body_contact(*pb)
    return {"R1": p1, "R2": p2, "B": pb}


def place_rdiv_cc26(c: Cell, prim28: Cell, dx: float, dy: float) -> dict:
    p = Cell()
    p.include(prim28)
    r1_all = [(grid(prim28.pins(f"R1_{i}")[0][0] + dx), grid(prim28.pins(f"R1_{i}")[0][1] + dy)) for i in range(28)]
    r2_all = [(grid(prim28.pins(f"R2_{i}")[0][0] + dx), grid(prim28.pins(f"R2_{i}")[0][1] + dy)) for i in range(28)]
    bx, by = prim28.pins("B")[0]
    y_ring_top = grid(-by + dy)
    y_ring_bot = grid(by + dy)
    # Tap continuous guard ring on TOP-WEST edge (strictly north of quiet pin -> zero crossing with Kelvin sense!)
    pb = (grid(r1_all[0][0] - 1.2), y_ring_top)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)
    c.body_contact(*pb)

    # Outer dummy bars 0 & 27: tie BOTH ends straight into the vss locali guard ring (0 A, zero floating poly!)
    for idx_d in (0, 27):
        x_d = r1_all[idx_d][0]
        for pt_end, y_ring in ((r1_all[idx_d], y_ring_top), (r2_all[idx_d], y_ring_bot)):
            c.pad("viali", x_d, y_ring, 0.17)
            c.rect("metal1", grid(x_d - 0.18), grid(y_ring - 0.18), grid(x_d + 0.18), grid(y_ring + 0.18))
            c.wire("metal1", [pt_end, (x_d, y_ring)], 0.36)

    # Inner 26 active bars (1..26): 10 T's (Rtop) + 16 F's (Rfixed) in 100% common-centroid palindrome
    r1 = r1_all[1:27]
    r2 = r2_all[1:27]

    # 10 T's (Rtop) + 16 F's (Rfixed) in 100% common-centroid palindrome with T on outer ends:
    # quiet = r2[0] (FAR WEST), n5 = r2[1] (EAST of quiet), fb_return = r2[24..25] (FAR EAST) -> 100% PLANAR!
    half = "TFFTFTFFTFTFF"
    pattern = list(half + half[::-1])
    t_idx = [i for i, ch in enumerate(pattern) if ch == "T"]
    f_idx = [i for i, ch in enumerate(pattern) if ch == "F"]

    y_top_m1, y_bot_m1 = r1[0][1], r2[0][1]
    y_t_top, y_t_bot = grid(y_top_m1 + 0.90), grid(y_bot_m1 - 0.90)
    y_f_top, y_f_bot = grid(y_top_m1 + 1.45), grid(y_bot_m1 - 1.45)

    # Rtop (T): hops on metal2 (y_t_top / y_t_bot)
    for k in range(len(t_idx) - 1):
        i, j = t_idx[k], t_idx[k + 1]
        if k % 2 == 0:
            if j == i + 1:
                c.wire("metal1", [r1[i], r1[j]], 0.44)
            else:
                c.via1(*r1[i]); c.via1(*r1[j])
                c.wire("metal2", [r1[i], (r1[i][0], y_t_top), (r1[j][0], y_t_top), r1[j]], 0.34)
        else:
            if j == i + 1:
                c.wire("metal1", [r2[i], r2[j]], 0.44)
            else:
                c.via1(*r2[i]); c.via1(*r2[j])
                c.wire("metal2", [r2[i], (r2[i][0], y_t_bot), (r2[j][0], y_t_bot), r2[j]], 0.34)

    # Rfixed (F): hops strictly on metal1 (y_f_top / y_f_bot) -> mathematically ZERO crossings with T (metal2)!
    f_rev = list(reversed(f_idx))
    for k in range(len(f_rev) - 1):
        i, j = f_rev[k], f_rev[k + 1]
        if k % 2 == 0:
            if abs(j - i) == 1:
                c.wire("metal1", [r1[i], r1[j]], 0.44)
            else:
                c.wire("metal1", [r1[i], (r1[i][0], y_f_top), (r1[j][0], y_f_top), r1[j]], 0.36)
        else:
            if abs(j - i) == 1:
                c.wire("metal1", [r2[i], r2[j]], 0.44)
            else:
                c.wire("metal1", [r2[i], (r2[i][0], y_f_bot), (r2[j][0], y_f_bot), r2[j]], 0.36)

    p_quiet = r2[t_idx[0]]
    p_fb_t = r2[t_idx[-1]]
    p_fb_f = r2[f_rev[0]]
    p_n5 = r2[f_rev[-1]]
    for pt in (p_quiet, p_fb_t, p_fb_f, p_n5):
        c.via1(*pt)
    c.wire("metal2", [p_fb_t, (p_fb_t[0], y_t_bot), (p_fb_f[0], y_t_bot), p_fb_f], 0.36)
    return {"quiet": p_quiet, "fb_return": (p_fb_f[0], y_t_bot), "n5": p_n5, "B": pb}


def place_rdiv_trim21(c: Cell, prim23: Cell, dx: float, dy: float) -> dict:
    p = Cell()
    p.include(prim23)
    r1_all = [(grid(prim23.pins(f"R1_{i}")[0][0] + dx), grid(prim23.pins(f"R1_{i}")[0][1] + dy)) for i in range(23)]
    r2_all = [(grid(prim23.pins(f"R2_{i}")[0][0] + dx), grid(prim23.pins(f"R2_{i}")[0][1] + dy)) for i in range(23)]
    bx, by = prim23.pins("B")[0]
    y_ring_top = grid(-by + dy)
    y_ring_bot = grid(by + dy)
    # Tap body contact on the WEST edge of the continuous guard ring (right next to vss tap, clear of n0..n5!)
    pb = (grid(r2_all[0][0] - 1.2), y_ring_bot)
    p.labels.clear()
    c.include(p, dx=dx, dy=dy)
    c.body_contact(*pb)

    # Outer dummy bars 0 & 22: tie BOTH ends straight into the vss locali guard ring (0 A, zero floating poly!)
    for idx_d in (0, 22):
        x_d = r1_all[idx_d][0]
        for pt_end, y_ring in ((r1_all[idx_d], y_ring_top), (r2_all[idx_d], y_ring_bot)):
            c.pad("viali", x_d, y_ring, 0.17)
            c.rect("metal1", grid(x_d - 0.18), grid(y_ring - 0.18), grid(x_d + 0.18), grid(y_ring + 0.18))
            c.wire("metal1", [pt_end, (x_d, y_ring)], 0.36)

    # Inner 21 active trim bars (1..21)
    r1 = r1_all[1:22]
    r2 = r2_all[1:22]

    c.wire("metal1", [r2[0], r2[3]], 0.50)
    c.wire("metal1", [r1[0], r1[5]], 0.50)
    c.wire("metal1", [r2[4], r2[6]], 0.50)
    c.wire("metal1", [r1[6], r1[7]], 0.50)
    c.wire("metal1", [r2[7], r2[8]], 0.50)
    c.wire("metal1", [r1[8], r1[9]], 0.50)
    c.wire("metal1", [r2[9], r2[10]], 0.50)
    c.wire("metal1", [r1[10], r1[11]], 0.50)
    c.wire("metal1", [r2[11], r2[12]], 0.50)
    c.wire("metal1", [r1[12], r1[13]], 0.50)
    for k in range(13, 20):
        if (k - 13) % 2 == 0:
            c.wire("metal1", [r2[k], r2[k + 1]], 0.50)
        else:
            c.wire("metal1", [r1[k], r1[k + 1]], 0.50)

    taps = {
        "vss": r2[0], "n0": r1[3], "n1": r2[5], "n2": r1[6],
        "n3": r1[8], "n4": r1[12], "n5": r1[20], "B": pb,
    }
    for k in ("vss", "n0", "n1", "n2", "n3", "n4", "n5"):
        c.via1(*taps[k])
    return taps


def _make_1level_passives_spice() -> str:
    """Emit electrically-identical 1-level passive subckts to avoid Netgen's 256-char flat-name buffer overflow."""
    def chain_res(name: str, n: int, w: str, l: str) -> str:
        lines = [f".subckt {name} a b sub"]
        for i in range(n):
            na = "a" if i == 0 else f"n{i}"
            nb = "b" if i == n - 1 else f"n{i+1}"
            lines.append(f"Xr{i} {na} {nb} sub sky130_fd_pr__res_high_po w={w} l={l}")
        lines.append(f".ends {name}")
        return "\n".join(lines)

    def par_res(name: str, n: int, w: str, l: str) -> str:
        lines = [f".subckt {name} a b sub"]
        for i in range(n):
            lines.append(f"Xr{i} a b sub sky130_fd_pr__res_high_po w={w} l={l}")
        lines.append(f".ends {name}")
        return "\n".join(lines)

    def par_mim(name: str, n: int, side: str) -> str:
        lines = [f".subckt {name} a b"]
        for i in range(n):
            lines.append(f"Xc1_{i} a b sky130_fd_pr__cap_mim_m3_1 w={side} l={side} mf=1")
            lines.append(f"Xc2_{i} b a sky130_fd_pr__cap_mim_m3_2 w={side} l={side} mf=1")
        lines.append(f".ends {name}")
        return "\n".join(lines)

    return "\n\n".join([
        chain_res("serdes_ldo_v2_rf50k",  1,  "0.5", "75.640"),
        chain_res("serdes_ldo_v2_rf200k", 4,  "0.5", "75.640"),
        chain_res("serdes_ldo_v2_rf400k", 8,  "0.5", "75.640"),
        chain_res("serdes_ldo_v2_rf1p2m", 24, "0.5", "75.640"),
        chain_res("serdes_ldo_v2_rf1p6m", 32, "0.5", "75.640"),
        chain_res("serdes_ldo_v2_r12k",   1,  "1.0", "36.660"),
        chain_res("serdes_ldo_v2_r5k",    1,  "1.0", "14.580"),
        chain_res("serdes_ldo_v2_ru4k",   1,  "1.0", "11.425"),
        par_res("serdes_ldo_v2_rdiv1k",   4,  "1.0", "11.425"),
        par_res("serdes_ldo_v2_rdiv2k",   2,  "1.0", "11.425"),
        chain_res("serdes_ldo_v2_rdiv4k", 1,  "1.0", "11.425"),
        chain_res("serdes_ldo_v2_rdiv8k", 2,  "1.0", "11.425"),
        chain_res("serdes_ldo_v2_rdiv16k", 4, "1.0", "11.425"),
        chain_res("serdes_ldo_v2_rdiv32k", 8, "1.0", "11.425"),
        chain_res("serdes_ldo_v2_rdiv40k", 10, "1.0", "11.425"),
        chain_res("serdes_ldo_v2_rdiv64k", 16, "1.0", "11.425"),
        par_mim("serdes_ldo_v2_mim0p75", 1, "13.500"),
        par_mim("serdes_ldo_v2_mim1p0",  1, "15.600"),
        par_mim("serdes_ldo_v2_mim2p0",  1, "22.195"),
        par_mim("serdes_ldo_v2_mim3p5",  1, "29.415"),
        par_mim("serdes_ldo_v2_mim7p0",  2, "29.415"),
        par_mim("serdes_ldo_v2_mim10p5", 3, "29.415"),
        par_mim("serdes_ldo_v2_mim14p0", 4, "29.415"),
        par_mim("serdes_ldo_v2_mim21p0", 6, "29.415"),
    ])


def make_reference_spice(out_path: Path, cell_name: str, is_probe: bool) -> Path:
    src_name = "serdes_pll_supply_hv18_v2_probe" if is_probe else "serdes_pll_supply_hv18_v2"
    ports = PROBE_PORTS if is_probe else PROD_PORTS
    # Resolve parameterized wrapper instances in pll_supply_hv18_v2.spice to literal PDK W/L
    # (Netgen's SPICE reader ignores subckt parameter overrides and falls back to default w=1/3/4).
    pll_sp = (SPICE_DIR / "pll_supply_hv18_v2.spice").read_text()
    pll_sp = re.sub(
        r"^Xcopy\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_bias_pcopy\s+n=4\s*$",
        r"Xcopy \1 \2 \3 \3 sky130_fd_pr__pfet_01v8_lvt w=24 l=4 nf=4",
        pll_sp, flags=re.M,
    )
    pll_sp = re.sub(
        r"^Xinv\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_cmos_inv\b[^\n]*$",
        "Xinv_n \\2 \\1 \\4 \\4 sky130_fd_pr__nfet_01v8 w=1 l=0.15\n"
        "Xinv_p \\2 \\1 \\3 \\3 sky130_fd_pr__pfet_01v8 w=2 l=0.15",
        pll_sp, flags=re.M,
    )
    pll_sp = re.sub(
        r"^Xrefgate\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_cmos_tgate\s+wn=2\s+wp=4\b[^\n]*$",
        "Xrefgate_n \\1 \\3 \\2 \\6 sky130_fd_pr__nfet_01v8 w=2 l=0.15\n"
        "Xrefgate_p \\1 \\4 \\2 \\5 sky130_fd_pr__pfet_01v8 w=4 l=0.15",
        pll_sp, flags=re.M,
    )
    pll_sp = re.sub(
        r"^(X\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+serdes_nfet\s+w=([0-9.]+)\s+l=([0-9.]+)\s*$",
        r"\1 \2 \3 \4 \5 sky130_fd_pr__nfet_01v8 w=\6 l=\7",
        pll_sp, flags=re.M,
    )
    chunks = [
        f"* LVS reference netlist for {cell_name}",
        _make_1level_passives_spice(),
        (SPICE_DIR / "ldo_hv18_core_v2.spice").read_text(),
        pll_sp,
        f".subckt {cell_name} " + " ".join(ports),
        f"Xtop " + " ".join(ports) + f" {src_name}",
        f".ends {cell_name}",
        "",
    ]
    out_path.write_text("\n".join(chunks))
    return out_path


def run_drc_lvs_pex_rcx(work: Path, cell: str, ref: Path, extract_rcx: bool = True) -> dict:
    mag = work / f"{cell}.mag"
    lvs_sp = work / f"{cell}_lvs.spice"
    pex_sp = work / f"{cell}_pex.spice"
    rcx_sp = work / f"{cell}_rcx.spice"
    lvs_log = work / f"{cell}_lvs.log"

    tcl = work / "_check_pex.tcl"
    tcl.write_text("\n".join([
        "drc euclidean on",
        "drc style drc(full)",
        f"load {cell}",
        "select top cell",
        "drc check",
        "drc catchup",
        'puts "DRC_TOTAL=[drc list count total]"',
        "puts [drc listall why]",
        "extract all",
        "ext2spice lvs",
        f"ext2spice -o {lvs_sp.name}",
        "ext2spice cthresh 0",
        "ext2spice rthresh infinite",
        f"ext2spice -o {pex_sp.name}",
        "quit -noprompt",
        "",
    ]))
    res = mu.run_magic(tcl, work)
    (work / "_check_pex.log").write_text(res.log)
    res.need(f"DRC+PEX {cell}")

    m_drc = re.search(r"DRC_TOTAL=(\d+)", res.log)
    drc_total = int(m_drc.group(1)) if m_drc else -1

    ng = mu.netgen(lvs_sp, cell, ref, lvs_log, work)
    lvs_txt = lvs_log.read_text() if lvs_log.exists() else (ng.stdout + ng.stderr)
    lvs_match = "Circuits match uniquely" in lvs_txt
    lvs_prop_err = "Property errors were found" in lvs_txt

    ports = exported_ports(lvs_sp, cell) if lvs_sp.exists() else []
    parasitics = summarize_pex_spice(pex_sp, ports) if pex_sp.exists() else {}

    rcx_info = None
    if extract_rcx and drc_total == 0 and lvs_match:
        rc_tcl = work / "_rcx.tcl"
        rc_tcl.write_text("\n".join([
            "drc off",
            f"load {cell}",
            "select top cell",
            "extresist threshold 100",
            "extresist minres 100",
            "extract do resistance",
            "extract all",
            "ext2spice lvs",
            "ext2spice cthresh 0",
            "ext2spice extresist on",
            f"ext2spice -o {rcx_sp.name}",
            "quit -noprompt",
            "",
        ]))
        rc_res = mu.run_magic(rc_tcl, work)
        (work / "_rcx.log").write_text(rc_res.log)
        rc_res.need(f"RCX {cell}")
        rc_lines = rcx_sp.read_text().splitlines()
        r_count = sum(1 for ln in rc_lines if re.match(r"^R\S+\s", ln))
        rcx_info = dict(threshold_mohm=100, minres_mohm=100, resistor_count=r_count, path=str(rcx_sp))

    box = Cell.read(mag).bbox()
    w_um = round(box[2] - box[0], 3)
    h_um = round(box[3] - box[1], 3)
    return dict(
        cell=cell,
        bbox_um=list(box),
        width_um=w_um,
        height_um=h_um,
        area_um2=round(w_um * h_um, 2),
        drc_total=drc_total,
        lvs_match=lvs_match,
        lvs_property_errors=lvs_prop_err,
        exported_ports=ports,
        parasitics=parasitics,
        rcx=rcx_info,
    )


def render_png(mag: Path, out_png: Path, title: str) -> None:
    """Render .mag layout using the repo's crisp white-background SKY130 palette (plot_mag.py)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import plot_mag as pm

    rects, labels = pm.parse(mag)
    xs = [r[1] for r in rects] + [r[3] for r in rects]
    ys = [r[2] for r in rects] + [r[4] for r in rects]
    x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
    w, h = x2 - x1, y2 - y1

    fig, ax = plt.subplots(figsize=(18, max(7.6, 18 * h / max(w, 1.0))), dpi=180)
    ax.set_facecolor("white")

    present = set()
    for layer, rx1, ry1, rx2, ry2 in rects:
        if layer not in pm.COLORS:
            continue
        present.add(layer)
        is_mim = layer in ("mimcap", "mimcap2")
        alpha = 0.28 if is_mim else (0.62 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.90)
        ec = "#d97706" if layer == "mimcap" else ("#059669" if layer == "mimcap2" else "none")
        ax.add_patch(
            Rectangle(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                facecolor=pm.COLORS[layer],
                edgecolor=ec, linewidth=0.7 if is_mim else 0.0,
                hatch="//" if is_mim else None,
                alpha=alpha, zorder=pm.Z[layer],
            )
        )

    for zx, lbl in [(92, "Zone 1: 60 pF Stacked MIM2 Bay + Under-MIM Passives / Divider / Clamp"),
                    (230, "Zone 2: EA + Pre-Reg\n(MIM-free)"),
                    (282, "Zone 3: Power\nXcas | Xpass")]:
        ax.text(zx, y2 + 2.2, lbl, color="#1e3a8a", fontsize=8.5, ha="center", va="bottom", fontweight="bold", zorder=110)

    west_stagger = {"enable": (-10.5, +4.2), "bg": (-10.5, +0.8), "vgi": (-10.5, -2.6), "host": (-10.5, -6.0)}
    for nm, px, py in labels:
        ax.plot(px, py, "o", color="#111827", markersize=4.0, markeredgecolor="#ffffff", markeredgewidth=0.6, zorder=105)
        if nm in west_stagger:
            dx_l, dy_l = west_stagger[nm]
            ax.annotate(
                nm, xy=(px, py), xytext=(px + dx_l, py + dy_l),
                color="#111827", fontsize=7.5, fontweight="bold", ha="right", va="center", zorder=110,
                arrowprops=dict(arrowstyle="-", color="#2563eb", lw=0.9),
                bbox=dict(boxstyle="round,pad=0.14", facecolor="#ffffff", edgecolor="#2563eb", alpha=0.95),
            )
        else:
            ax.text(
                px, py, f" {nm}", color="#111827", fontsize=8.0, fontweight="bold", zorder=110,
                bbox=dict(boxstyle="round,pad=0.14", facecolor="#ffffff", edgecolor="#2563eb", alpha=0.92),
            )

    ax.set_xlim(x1 - 24, x2 + 26)
    ax.set_ylim(y1 - 11, y2 + 11)
    ax.set_aspect("equal")
    ax.set_xlabel("X (µm)")
    ax.set_ylabel("Y (µm)")
    ax.grid(True, lw=0.25, alpha=0.35)
    ax.set_title(f"{title}  ({w:.1f} × {h:.1f} µm = {w*h:,.0f} µm²)", fontsize=12, fontweight="bold")
    legend_keys = [k for k in pm.COLORS if k in present]
    handles = [Rectangle((0, 0), 1, 1, facecolor=pm.COLORS[k],
                         edgecolor="#d97706" if k == "mimcap" else ("#059669" if k == "mimcap2" else "none"),
                         hatch="//" if k in ("mimcap", "mimcap2") else None) for k in legend_keys]
    ax.legend(handles, legend_keys, fontsize=6.2, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0, ncol=1)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def build_supply_v2(out: Path, is_probe: bool, extract_rcx: bool = True) -> dict:
    """Build complete flat LDO v2 supply macro (~37,000 um^2, DRC=0, LVS=MATCH)."""
    cell = "serdes_pll_supply_hv18_v2_probe_pdk" if is_probe else "serdes_pll_supply_hv18_v2_pdk"
    work = out / cell
    work.mkdir(parents=True, exist_ok=True)
    pwork = work / "_prims"
    pwork.mkdir(exist_ok=True)

    specs = {
        "nvt_25x2": ("sky130_fd_pr__nfet_05v0_nvt", dict(w=10.0, l=0.9, nf=25, m=2, poverlap=0, conn_gates=1, guard=1)),
        "nvt_15x2": ("sky130_fd_pr__nfet_05v0_nvt", dict(w=10.0, l=0.9, nf=15, m=2, poverlap=0, conn_gates=1, guard=1)),
        "pre_p":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=15, m=2, conn_gates=1, guard=1)),
        "pre_d":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=15, m=4, conn_gates=1, guard=1)),
        "p2_150":   ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=15, m=2, conn_gates=1, guard=1)),
        "pt_120":   ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=12, m=2, conn_gates=1, guard=1)),
        "pl_60":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=1.0, nf=14, m=1, conn_gates=0, guard=0)),
        "pd_30":    ("sky130_fd_pr__pfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=6,  m=1, conn_gates=1, guard=1)),
        "nb_30":    ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=6,  m=1, conn_gates=1, guard=1)),
        "nl_20":    ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0, l=2.0, nf=6,  m=1, conn_gates=0, guard=0)),
        "pre_sink": ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=3.0, l=2.0, nf=3,  m=1, conn_gates=1, guard=1)),
        "n2_90":    ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0,  l=0.5, nf=18, m=1, conn_gates=1, guard=1)),
        "off_10":   ("sky130_fd_pr__nfet_g5v0d10v5", dict(w=5.0,  l=0.5, nf=2,  m=1, conn_gates=1, guard=1)),
        "rref32":   ("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=32, m=1, guard=1)),
        "rpreoff24":("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=24, m=1, guard=1)),
        "rf8":      ("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=8,  m=1, guard=1)),
        "rf5":      ("sky130_fd_pr__res_high_po_0p35", dict(w=0.5, l=75.640, nx=5,  m=1, guard=1)),
        "rdiv26":   ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=11.425, nx=28, m=1, guard=1)),
        "rdiv21":   ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=11.425, nx=23, m=1, guard=1)),
        "r12k":     ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=36.660, nx=1, m=1, guard=1)),
        "r5k":      ("sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=14.580, nx=1, m=1, guard=1)),
        "clamp_144":("sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.15, nf=18, m=2, conn_gates=1, guard=1)),
        "clp2_96":  ("sky130_fd_pr__pfet_01v8", dict(w=6.0, l=0.15, nf=16, m=1, conn_gates=1, guard=1)),
        "cln1_56":  ("sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.15, nf=14, m=1, conn_gates=1, guard=1)),
        "clnref_24":("sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.15, nf=6,  m=1, conn_gates=1, guard=1)),
        "n_w4_nf2": ("sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=2,  m=1, conn_gates=1, guard=1)),
        "p_w4_nf2": ("sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=2,  m=1, conn_gates=1, guard=1)),
        "sw_n20":   ("sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.15, nf=4,  m=1, conn_gates=1, guard=1)),
        "n_w2":     ("sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
        "n_w1":     ("sky130_fd_pr__nfet_01v8", dict(w=1.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
        "p_w2":     ("sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
        "p_w4":     ("sky130_fd_pr__pfet_01v8", dict(w=4.0, l=0.15, nf=1,  m=1, conn_gates=1, guard=1)),
    }
    prims: dict[str, Cell] = {}
    for nm, (mdl, par) in specs.items():
        p = pdk_device(pwork, nm, mdl, par)
        p.rects.pop("checkpaint", None)
        prims[nm] = p

    pcopy_raw = Cell.read(BIAS_LAYOUT_DIR / "serdes_bias_pcopy_pdk.mag")
    pcopy_raw.rects.pop("checkpaint", None)
    pcopy_pins_local = {nm: pcopy_raw.pins(nm)[0] for nm in ("out", "vgi", "vdd")}
    pcopy_raw.labels.clear()

    top = Cell()

    # =========================================================================
    # ZONE 1 (x in [-6.1, 211.5]):
    #   60.00 pF Stacked + Fused MIM1/MIM2 Bay (5x3 Large + 1-col Small + Xcff below Xrefcap!)
    #   Exact M5 & cap2m clearances verified >= 1.7 um (M5) and >= 1.45 um (cap2m)!
    # =========================================================================
    #   Xccas   (M5 left -2.245, right 67.3)  @ (34.0, +0.5)
    #   Xrefcap (M5 left 70.5,   right 103.0) @ (87.2, +2.0)  -> bottom M5 -45.13, alley x=69.0
    #   Xcva    (M5 left 108.05, right 177.6) @ (144.3, -15.2) -> bottom M5 -46.62, top +16.22
    #   Xcout   (M5 left 108.05, right 177.6) @ (144.3, +35.6) -> bottom M5 +20.48, top +50.71
    m_ccas = place_stacked_mim(top, pwork, "ccas", 29.415, 2, 3, dx_c=33.4,  dy_c=+0.5,  shared_vss=True, a_off=7.9, b3_off=2.0, b5_off=5.5)
    m_cref = place_stacked_mim(top, pwork, "cref", 29.415, 1, 3, dx_c=87.6,  dy_c=+4.5,  shared_vss=True, a_off=1.9, b3_off=2.0, b5_off=2.5)
    m_cva  = place_stacked_mim(top, pwork, "cva",  29.415, 2, 2, dx_c=144.3, dy_c=-15.4, shared_vss=True, a_off=1.9, b3_off=2.0, b5_off=2.5)
    m_cout = place_stacked_mim(top, pwork, "cout", 29.415, 2, 1, dx_c=144.3, dy_c=+36.15, shared_vss=True, a_off=2.2, b3_off=1.9, b5_off=2.6)

    # Single-column Small/Medium Stacked MIM Strip (chp/cpre at x_c=194.2, pillar_dx=2.8 -> pillar right 211.22, 0.45 um clear of x_gt_m3 211.9!)
    m_chp  = place_stacked_mim(top, pwork, "chp",  22.195, 1, 1, dx_c=194.2, dy_c=+38.7, shared_vss=False, a_off=1.5, b3_off=1.8, b5_off=2.5, pillar_dx=2.8)
    m_cpre = place_stacked_mim(top, pwork, "cpre", 22.195, 1, 1, dx_c=194.2, dy_c=+10.9, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=2.8)
    m_cc   = place_stacked_mim(top, pwork, "cc",   15.600, 1, 1, dx_c=193.2, dy_c=-13.5, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=3.2)
    m_cghf = place_stacked_mim(top, pwork, "cghf", 15.600, 1, 1, dx_c=193.2, dy_c=-34.5, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=3.6)
    m_cbp  = place_stacked_mim(top, pwork, "cbp",  13.500, 1, 1, dx_c=193.2, dy_c=-54.4, shared_vss=False, a_off=1.6, b3_off=1.8, b5_off=2.5, pillar_dx=2.8)

    # 6th small cap Xcff (0.75 pF, 13.5x13.5) tucked below Xrefcap @ (87.6, -54.8), b5_off=2.5 -> >= 1.85 um clear of m_cref!
    m_cff  = place_stacked_mim(top, pwork, "cff",  13.500, 1, 1, dx_c=87.6,  dy_c=-54.8, shared_vss=False, a_off=1.8, b3_off=1.8, b5_off=2.5, pillar_dx=3.0)

    # --- Shared Heavy M3/M5 Ground Frame around 5x3 Large MIM Bay ---
    x_vss_west = -5.30
    x_vss_mid  = 105.4
    y_vss_m3_bot = -48.8
    y_vss_m5_top = +54.3
    # Stub 1: Xccas bottom M3 -> x_vss_west (stops at x=50.5, 18.5 um WEST of x_rloc_al!)
    top.wire("metal3", [(x_vss_west, y_vss_m3_bot), (m_ccas["b3_pts"][-1][0], y_vss_m3_bot)], 1.2)
    # Stub 2: Xrefcap bottom M3 -> x_vss_mid (starts at x=87, 18 um EAST of x_rloc_al!)
    top.wire("metal3", [(m_cref["b3_pts"][0][0], m_cref["yb3"]), (x_vss_mid, m_cref["yb3"])], 1.2)
    # Stub 3: Xcva bottom M3 -> x_vss_mid (at y=-48.8, strictly NORTH of p_sws G @ -50.4!)
    top.wire("metal3", [(x_vss_mid, y_vss_m3_bot), (m_cva["b3_pts"][-1][0], y_vss_m3_bot)], 1.2)
    top.wire("metal5", [(x_vss_west, y_vss_m5_top), (175.0, y_vss_m5_top)], 1.8)
    # Step vss M5 north to y=+55.92 (bottom +55.12, 1.615 um > 1.60 DRC clear of m_chp M5 +53.505!) across to x_vgb=251.5!
    y_vss_m5_east = +55.92
    top.wire("metal5", [(175.0, y_vss_m5_top), (175.0, y_vss_m5_east), (251.5, y_vss_m5_east)], 1.6)
    for mm in (m_ccas, m_cva):
        for bx, _ in mm["b3_pts"]:
            top.wire("metal3", [(bx, mm["yb3"]), (bx, y_vss_m3_bot)], 1.2)
    for mm in (m_ccas, m_cref, m_cout):
        for bx, _ in mm["b5_pts"]:
            top.wire("metal5", [(bx, mm["yb5"]), (bx, y_vss_m5_top)], 1.6)
    # Xcva top M5 (+18.5) & Xcout bottom M3 (+19.2) tied cleanly into x_vss_mid with mid-height via3+via4!
    top.wire("metal5", [(x_vss_mid, m_cva["yb5"]), (m_cva["b5_pts"][-1][0], m_cva["yb5"])], 1.6)
    top.wire("metal3", [(x_vss_mid, m_cout["yb3"]), (m_cout["b3_pts"][-1][0], m_cout["yb3"])], 1.6)
    top.wire("metal3", [(x_vss_west, y_vss_m3_bot), (x_vss_west, y_vss_m5_top)], 1.6)
    top.wire("metal5", [(x_vss_west, y_vss_m3_bot), (x_vss_west, y_vss_m5_top)], 1.6)
    via34_pillar_v(top, x_vss_west, +53.5)
    via34_pillar_v(top, x_vss_west, -50.2)
    top.wire("metal3", [(x_vss_mid, -51.4), (x_vss_mid, y_vss_m5_top)], 1.6)
    top.wire("metal5", [(x_vss_mid, -51.4), (x_vss_mid, y_vss_m5_top)], 1.6)
    # Slim in-spine via3+via4 ties at (x_vss_mid, +53.5) & (x_vss_mid, +18.8) -> shorts m_cout bottom M3 directly to M5!
    for y_mv in (+53.5, +18.8):
        top.rect("metal3", grid(x_vss_mid - 0.8), grid(y_mv - 0.8), grid(x_vss_mid + 0.8), grid(y_mv + 0.8))
        top.rect("metal4", grid(x_vss_mid - 0.8), grid(y_mv - 0.8), grid(x_vss_mid + 0.8), grid(y_mv + 0.8))
        for vx in (-0.35, 0.35):
            for vy in (-0.35, 0.35):
                top.pad("via3", grid(x_vss_mid + vx), grid(y_mv + vy), 0.32)
        top.pad("via4", x_vss_mid, y_mv, 1.18)
    via34_pillar_v(top, x_vss_mid, -51.4)

    # =========================================================================
    # UNDER-MIM PASSIVES, MATCHED DIVIDER, CLAMP & SOUTH CTRL (M1/M2 under MIM!)
    # Planar High-R order: p_rcas (rev) | p_rref | p_rpreoff | p_rpre | p_rcl_arr
    # =========================================================================
    p_rcas    = place_res_snake(top, prims["rf8"],        8, dx=11.0,  dy=+2.5, reverse=True)
    p_rref    = place_res_snake(top, prims["rref32"],    32, dx=43.0,  dy=+2.5)
    p_rpreoff = place_res_snake(top, prims["rpreoff24"], 24, dx=84.5,  dy=+2.5)
    p_rpre    = place_res_snake(top, prims["rf8"],        8, dx=109.0, dy=+2.5)
    p_rcl_arr = place_res_snake(top, prims["rf5"],        5, dx=124.5, dy=+2.5, split_idx=4)

    # Matched 47-bar divider cleanly under Xcva (dx=163.5 -> rdiv_bot.n5 @ 178.3, 2.1 um WEST of x_fbret_p 180.4!)
    p_rdiv_top = place_rdiv_cc26(top, prims["rdiv26"], dx=163.5, dy=-11.5)
    p_rdiv_bot = place_rdiv_trim21(top, prims["rdiv21"], dx=163.5, dy=-37.0)

    # Active Overshoot Clamp tucked cleanly BELOW y=+45.5 (p_cl_r1 @ +24.8 -> R1=+45.0 < +46.2, B=+3.9 < +6.3!)
    p_cl_r1   = place_res_single(top, prims["r12k"], dx=150.0, dy=+24.8)
    p_cl_r2   = place_res_single(top, prims["r5k"],  dx=164.5, dy=+12.5)
    p_clamp   = strap_1v8_m2(top, prims["clamp_144"], "ndiffc", dx=181.5, dy=+38.0, tie_sb=True)
    p_cl_p2   = strap_1v8_m2(top, prims["clp2_96"],   "pdiffc", dx=181.5, dy=+25.0, tie_sb=True)
    p_cl_n1   = strap_1v8_m2(top, prims["cln1_56"],   "ndiffc", dx=181.5, dy=+14.5, tie_sb=True)
    p_cl_nref = strap_1v8_m2(top, prims["clnref_24"], "ndiffc", dx=181.5, dy=+5.5,  tie_sb=True)
    p_cl_en   = strap_1v8_m2(top, prims["p_w4_nf2"],  "pdiffc", dx=194.5, dy=+25.0, tie_sb=True)
    p_cl_off  = strap_1v8_m2(top, prims["n_w4_nf2"],  "ndiffc", dx=194.5, dy=+14.5, tie_sb=True)
    p_cl_off2 = strap_1v8_m2(top, prims["n_w4_nf2"],  "ndiffc", dx=194.5, dy=+5.5,  tie_sb=True)

    # Xrzero (5k) tucked under m_cc/m_cghf at (203.5, -22.5) (M1/M2 ONLY!)
    p_rzero   = place_res_single(top, prims["r5k"], dx=203.5, dy=-22.5)

    # MIM-free South Control, Bias Copy, Xboff/Xoff/Xn2, and 6 Trim Switches (directly below rdiv_bot!)
    y_south_dev = -52.5
    p_tg_n  = strap_1v8_m2(top, prims["n_w2"], "ndiffc", dx=5.0,  dy=y_south_dev, tie_sb=False)
    p_tg_p  = strap_1v8_m2(top, prims["p_w4"], "pdiffc", dx=13.5, dy=y_south_dev, tie_sb=False)
    p_inv_n = strap_1v8_m2(top, prims["n_w1"], "ndiffc", dx=22.0, dy=y_south_dev, tie_sb=True)
    p_inv_p = strap_1v8_m2(top, prims["p_w2"], "pdiffc", dx=30.0, dy=y_south_dev, tie_sb=True)
    p_rst_n = strap_1v8_m2(top, prims["n_w2"], "ndiffc", dx=38.0, dy=y_south_dev, tie_sb=True)
    dx_copy, dy_copy = 55.0, -51.8
    top.include(pcopy_raw, dx=dx_copy, dy=dy_copy)
    p_copy = {k: (grid(v[0] + dx_copy), grid(v[1] + dy_copy)) for k, v in pcopy_pins_local.items()}

    # Xboff, Xoff, Xn2 (w=5, H=7.58 um!) cleanly in MIM-free gap x=[111..136], y=-53.2!
    p_boff = strap_mos_5v_single(top, prims["off_10"], "mvndiffc", dx=112.0, dy=-53.2, tie_sb=True)
    p_off  = strap_mos_5v_single(top, prims["off_10"], "mvndiffc", dx=119.5, dy=-53.2, tie_sb=True)
    p_n2   = strap_mos_5v_single(top, prims["n2_90"],  "mvndiffc", dx=131.5, dy=-53.2, tie_sb=True)

    # 6 Trim switches Xs0..Xs5 in 100% MIM-free bay DIRECTLY BELOW rdiv_bot (x=[147.0..177.0], 5.5 um WEST of m_cbp 182.5!)
    sw_xs = [147.0, 153.0, 159.0, 165.0, 171.0, 177.0]
    p_sws = [strap_1v8_m2(top, prims["sw_n20"], "ndiffc", dx=sx, dy=-53.4, tie_sb=(k == 0)) for k, sx in enumerate(sw_xs)]

    # =========================================================================
    # ZONE 2 (x in [211.9, 248.6], y in [-60.2, +55.7], 100% MIM-FREE!):
    #   Error Amplifier & HV PMOS Pre-Regulator
    # =========================================================================
    x_ea = 230.2
    # Xpre_p in ISOLATED vin N-well (y in [+41.5, +55.7])
    p_pre_p = strap_mos_5v_multirow(top, prims["pre_p"], "mvpdiffc", dx=x_ea, dy=+48.6, tie_sb=True)

    # Continuous va N-well (y in [-42.4, +38.6], >= 2.9 um clear of vin N-well!)
    top.rect("nwell", grid(x_ea - 19.6), -42.4, grid(x_ea + 19.6), +38.6)
    p_pre_d = strap_mos_5v_multirow(top, prims["pre_d"],  "mvpdiffc", dx=x_ea, dy=+25.1, tie_sb=True)
    p_p2    = strap_mos_5v_multirow(top, prims["p2_150"], "mvpdiffc", dx=x_ea, dy=+4.2,  tie_sb=True)
    p_pt    = strap_mos_5v_multirow(top, prims["pt_120"], "mvpdiffc", dx=x_ea, dy=-10.4, tie_sb=True)

    # Common-centroid 2D AB/BA diff pair with 1 tied-off outer dummy finger on EACH end (8 va-tied dummies total!)
    p_pl_a = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea - 9.7), dy=-21.8, tie_outer_to_s=False)
    p_pr_a = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea + 9.7), dy=-21.8, tie_outer_to_s=False)
    p_pr_b = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea - 9.7), dy=-30.0, tie_outer_to_s=False)
    p_pl_b = strap_mos_5v_single_dummies(top, prims["pl_60"], "mvpdiffc", dx=grid(x_ea + 9.7), dy=-30.0, tie_outer_to_s=False)

    p_pd = strap_mos_5v_single(top, prims["pd_30"], "mvpdiffc", dx=grid(x_ea - 9.0), dy=-38.2, tie_sb=True)
    # Dedicated va N-well tap below p_pl_b (right counterpart to p_pd -> keeps LU.3 P-diff to N-tap < 6 um << 15 um!)
    ntap_x1, ntap_x2, ntap_y = grid(x_ea + 2.0), grid(x_ea + 18.0), -38.2
    top.rect("mvnsubdiff", ntap_x1, grid(ntap_y - 0.5), ntap_x2, grid(ntap_y + 0.5))
    top.rect("mvnsubdiffcont", grid(ntap_x1 + 0.2), grid(ntap_y - 0.17), grid(ntap_x2 - 0.2), grid(ntap_y + 0.17))
    top.rect("locali", ntap_x1, grid(ntap_y - 0.5), ntap_x2, grid(ntap_y + 0.5))
    top.rect("metal1", ntap_x1, grid(ntap_y - 0.5), ntap_x2, grid(ntap_y + 0.5))
    for nx_t in (grid(x_ea + 4.0), grid(x_ea + 10.0), grid(x_ea + 16.0)):
        top.pad("viali", nx_t, ntap_y, 0.17)
        top.via1(nx_t, ntap_y)
    top.wire("metal2", [(grid(x_ea + 4.0), ntap_y), (249.6, ntap_y)], 0.48)
    via2_clean(top, 249.6, ntap_y)

    y_ea_gb = -43.9
    draw_pwell_guard_h(top, grid(x_ea - 19.0), grid(x_ea + 19.0), y_ea_gb, h=1.00)

    p_nb       = strap_mos_5v_single(top, prims["nb_30"],    "mvndiffc", dx=grid(x_ea - 10.0), dy=-48.6, tie_sb=True)
    p_nr       = strap_mos_5v_single(top, prims["nb_30"],    "mvndiffc", dx=grid(x_ea + 10.0), dy=-48.6, tie_sb=True)
    # Matched NMOS active mirror Xnl/Xnm with 1 tied-off outer dummy finger on EACH end (4 vss-tied dummies total!)
    p_nl       = strap_mos_5v_single_dummies(top, prims["nl_20"], "mvndiffc", dx=217.6, dy=-56.4, tie_outer_to_s=True)
    p_nm       = strap_mos_5v_single_dummies(top, prims["nl_20"], "mvndiffc", dx=232.6, dy=-56.4, tie_outer_to_s=True)
    p_pre_sink = strap_mos_5v_single(top, prims["pre_sink"], "mvndiffc", dx=245.1, dy=-56.4, tie_sb=True)

    # =========================================================================
    # ZONE 3 (x in [250.9, 306.0], y in [-52, +54], 100% MIM-FREE!):
    #   Full-Height P+ Guard Barrier + East IO-Edge NVT Power Stage + Wide M4/M5 Plates
    # =========================================================================
    y_vss_south = -63.8
    x_vgb = 251.5
    # End M1/M2/pwell at y=-60.5 so y_kelv_m2 (-62.7) passes cleanly UNDER M3 down to y_vss_south (-64.0)!
    draw_pwell_guard_v(top, x_vgb, -60.5, +50.0, w=1.20, m3_y1=y_vss_south)

    pwr_ys = [+38.0, +12.5, -13.0, -38.5]
    x_cas = 269.0
    x_pass = 296.0
    p_cas = [strap_mos_5v_multirow(top, prims["nvt_25x2"], "mvndiffc", dx=x_cas, dy=py, tie_sb=False) for py in pwr_ys]
    # p_pass gates stay on metal2 (m3_gate=False!) so gx_pass vertical M2 passes 100% cleanly UNDER mid M3 bridges!
    p_pass = [strap_mos_5v_multirow(top, prims["nvt_15x2"], "mvndiffc", dx=x_pass, dy=py, tie_sb=False, m3_gate=False) for py in pwr_ys]

    # =========================================================================
    # STRICT ZERO-CROSSING MULTI-LAYER INTERCONNECT ROUTING
    # =========================================================================

    # --- 1. POWER PLATE: vin (M4 ends at y=+49.6 so quiet M4 +52.5 & casg M4 +55.2 pass under vin M5!) ---
    x_vin_p1, x_vin_p2 = 258.0, 274.0
    top.rect("metal4", x_vin_p1, -48.0, x_vin_p2, +49.6)
    top.rect("metal5", x_vin_p1, -48.0, x_vin_p2, +56.0)  # M5-only north of +49.6!
    for pc in p_cas:
        dy_b = pc["d_bus_y"]
        for xv in (260.0, 264.0, 268.0, 272.0):
            top.via2(xv, dy_b)
            via3_array(top, xv, dy_b, nx=2, ny=2)
    for yv4 in (-43.0, -23.0, -3.0, +17.0, +37.0, +47.5):
        via4_array(top, 266.0, yv4, nx=4, ny=1, pitch=2.4)
    # vin -> Xpre_p.S/B (M2 -> M3/M4 @ y=+42.0 -> vin M4 plate)
    via2_clean(top, x_ea, p_pre_p["s_bus_y"])
    via3_array(top, x_ea, p_pre_p["s_bus_y"], nx=2, ny=1)
    top.wire("metal4", [(x_ea, p_pre_p["s_bus_y"]), (x_ea, +42.0), (x_vin_p1 + 2.0, +42.0)], 1.4)
    # vin -> Xcpre.b (pillar at x~209, y=+11.0): M5 straight East into vin M5 plate!
    top.wire("metal5", [m_cpre["b"], (x_vin_p1 + 2.0, m_cpre["b"][1])], 1.8)
    # vin -> Xrcas.a & Xrpre_off.a (M2 at y=+49.6 -> M3 drop at x=210.0 OVER pre_d & pre_g to y=+42.0 -> M2 into Xpre_p.S!)
    y_vin_m2 = +49.6
    for pt in (p_rcas["a"], p_rpreoff["a"]):
        top.wire("metal2", [pt, (pt[0], y_vin_m2)], 0.44)
    top.wire("metal2", [(p_rcas["a"][0], y_vin_m2), (210.0, y_vin_m2)], 0.48)
    via2_clean(top, 210.0, y_vin_m2)
    top.wire("metal3", [(210.0, y_vin_m2), (210.0, +42.2)], 0.48)
    via2_clean(top, 210.0, +42.2)
    top.wire("metal2", [(210.0, +42.2), (p_pre_p["s_xs"][0], +42.2), (p_pre_p["s_xs"][0], p_pre_p["s_bus_y"])], 0.48)

    # --- 2. POWER BRIDGE: mid (Xcas.S -> Xpass.D, M3-only horizontal bridges + vertical M3 spine tying all 4 rows!) ---
    for pc, pp in zip(p_cas, p_pass):
        for xm in (278.5, 281.5):
            top.via2(xm, pc["s_bus_y"])
            top.wire("metal3", [(xm, pc["s_bus_y"]), (xm, pp["d_bus_y"])], 1.40)
        for xp_m in (288.0, 292.0, 296.0, 300.0):
            top.via2(xp_m, pp["d_bus_y"])
        top.wire("metal3", [(278.5, pp["d_bus_y"]), (300.0, pp["d_bus_y"])], 1.60)
        top.wire("metal3", [(259.0, pc["s_bus_y"]), (281.5, pc["s_bus_y"])], 1.40)
    top.wire("metal3", [(281.5, p_cas[-1]["s_bus_y"]), (281.5, p_pass[0]["d_bus_y"])], 1.60)

    # --- 3. POWER PLATE: quiet (M4+M5 17.5 um wide plate on East IO edge -> wide M4 trunk at y=+53.3!) ---
    x_q_p1, x_q_p2 = 288.0, 305.5
    top.rect("metal4", x_q_p1, -49.5, x_q_p2, +54.5)
    top.rect("metal5", x_q_p1, -49.5, x_q_p2, +54.5)
    for pp in p_pass:
        sy_b = pp["s_bus_y"]
        for xq in (290.0, 294.0, 298.0, 302.0):
            for dx_v2 in (-0.45, 0.0, +0.45):
                top.via2(grid(xq + dx_v2), sy_b)
            via3_array(top, xq, sy_b, nx=3, ny=2)
    for yv4 in (-45.0, -25.0, -10.0, 0.0, +15.0, +35.0, +49.5):
        via4_array(top, 297.5, yv4, nx=5, ny=1, pitch=2.4)

    # Wide M4-only quiet trunk at y = m_cout["ya"] (+53.2, width 1.8 -> 100% DRC clear of m_chp & casg!)
    y_q_m4 = grid(m_cout["ya"])
    for ax_c, ay_c in m_cout["a_pts"]:
        top.wire("metal4", [(ax_c, ay_c), (ax_c, y_q_m4)], 1.4)
    top.wire("metal4", [(m_cout["a_left"][0], y_q_m4), (x_q_p1 + 2.0, y_q_m4)], 1.8)
    # Parallel M3 under-straps on quiet trunk across 3 clean spans ([179.0..208.4], [217.5..246.5], [256.5..288.0])!
    top.wire("metal3", [(179.0, y_q_m4), (208.4, y_q_m4)], 1.6)
    for xq_m3 in (180.0, 189.0, 198.0, 206.0):
        via3_array(top, xq_m3, y_q_m4, nx=2, ny=2)
    top.wire("metal3", [(217.5, y_q_m4), (246.5, y_q_m4)], 1.6)
    for xq_m3 in (218.5, 226.0, 234.0, 241.0, 245.5):
        via3_array(top, xq_m3, y_q_m4, nx=2, ny=2)
    top.wire("metal3", [(256.8, y_q_m4), (288.0, y_q_m4)], 1.6)
    for xq_m3 in (258.0, 266.0, 274.0, 282.0, 287.0):
        via3_array(top, xq_m3, y_q_m4, nx=2, ny=2)
    # Connect Xcl_chp.b UP on M3 at x = m_chp["b"][0] - 0.8 (clear of vin M3 drop @ 210.0!) to y_q_m4 -> via3_array into quiet M4!
    x_q_up = grid(m_chp["b"][0] - 0.8)
    top.wire("metal3", [(x_q_up, m_chp["b"][1]), (x_q_up, y_q_m4)], 1.6)
    via3_array(top, x_q_up, y_q_m4, nx=3, ny=2)
    # Drop quiet down from m_chp["b"] on M3 -> wide M2 + 4x via2 to Xclamp.D & 3x via2 to Xcl_p2.S!
    x_q_cl = x_q_up
    for dy_v2 in (-0.6, 0.0, +0.6, +1.2):
        via2_clean(top, x_q_cl, grid(p_clamp["D"][1] + dy_v2))
    top.wire("metal2", [(p_clamp["D"][0], p_clamp["D"][1]), (x_q_cl, p_clamp["D"][1])], 2.0)
    top.wire("metal2", [(p_clamp["d_xs"][0], p_clamp["D"][1]), (p_clamp["d_xs"][-1], p_clamp["D"][1])], 1.2)
    top.wire("metal3", [(x_q_cl, grid(p_clamp["D"][1] + 1.2)), (x_q_cl, grid(p_cl_p2["S"][1] - 0.6))], 1.4)
    for dy_p2 in (-0.45, 0.0, +0.45):
        via2_clean(top, x_q_cl, grid(p_cl_p2["S"][1] + dy_p2))
    top.wire("metal2", [(p_cl_p2["S"][0], p_cl_p2["S"][1]), (x_q_cl, p_cl_p2["S"][1])], 1.20)
    top.wire("metal2", [p_cl_en["S"], (p_cl_en["S"][0], p_cl_p2["S"][1])], 0.40)
    top.wire("metal2", [p_cl_r1["R1"], (p_cl_r1["R1"][0], +45.4), (p_clamp["D"][0], +45.4), p_clamp["D"]], 0.44)

    # DEDICATED KELVIN SENSE TRACE (quiet_sense): leaves exact East perimeter quiet port (304.8, -48.5) -> M2 along y=-62.7 -> Xcff.b & M3 bridge over South tracks to Xrtop.quiet!
    y_kelv_tap = -48.5
    via3_single(top, 304.8, y_kelv_tap)
    via2_clean(top, 304.8, y_kelv_tap)
    y_kelv_m2 = -62.7
    top.wire("metal2", [(304.8, y_kelv_tap), (304.8, y_kelv_m2), (m_cff["b"][0], y_kelv_m2)], 0.44)
    # Tap Xcff.b (pillar at x~97.2, y=-54.2) down on M3 to y_kelv_m2 (strictly clear of vss M3 which stops at x=74!)
    via2_clean(top, m_cff["b"][0], y_kelv_m2)
    top.wire("metal3", [(m_cff["b"][0], y_kelv_m2), m_cff["b"]], 0.60)
    # Jump OVER South M2 tracks (y=-62.7 -> -50.2) on M3 at x=139.2 (1.6 um SOUTH of y_vss_m3_bot -48.6!), then M2 NORTH to p_rdiv_top["quiet"]!
    x_kelv_up = 139.2
    via2_clean(top, x_kelv_up, y_kelv_m2)
    top.wire("metal3", [(x_kelv_up, y_kelv_m2), (x_kelv_up, -50.2)], 0.44)
    via2_clean(top, x_kelv_up, -50.2)
    top.wire("metal2", [(x_kelv_up, -50.2), (x_kelv_up, p_rdiv_top["quiet"][1]), p_rdiv_top["quiet"]], 0.44)

    # --- 4. POWER GROUND: vss (South trunk on M4 ONLY across [72..218] so Xcff.b, t0..t5 & fb ports pass cleanly UNDER!) ---
    top.wire("metal4", [(x_vss_west, y_vss_south), (305.0, y_vss_south)], 1.6)
    top.wire("metal3", [(x_vss_west, y_vss_south), (72.0, y_vss_south)], 1.4)
    top.wire("metal3", [(220.0, y_vss_south), (305.0, y_vss_south)], 1.4)
    for xv_s in (x_vss_west, 70.0, 222.0, x_vgb, 304.0):
        via3_array(top, xv_s, y_vss_south, nx=2, ny=2)
    top.wire("metal3", [(x_vss_west, y_vss_south), (x_vss_west, y_vss_m3_bot)], 1.4)
    # Connect x_vss_mid (105.4) bottom pillar to South M4 vss via M4 stub (NEVER touching M3!)
    top.wire("metal4", [(x_vss_mid, -51.4), (x_vss_mid, y_vss_south)], 1.6)
    # Connect Xcghf.b (pillar at x~204.2, y=-32.0) to y_ea_gb (-43.9)!
    top.wire("metal3", [m_cghf["b"], (m_cghf["b"][0], y_ea_gb)], 1.0)
    via2_clean(top, m_cghf["b"][0], y_ea_gb)
    top.wire("metal2", [(m_cghf["b"][0], y_ea_gb), (x_ea - 19.0, y_ea_gb)], 0.80)

    # Power stage bodies (Xcas & Xpass) -> x_vgb; jump UNDER x_gpass_m2 (286.4) on M1 [285.2..287.8] -> ZERO short to gate!
    for pc, pp in zip(p_cas, p_pass):
        yb = pc["B"][1]
        top.wire("metal2", [(x_vgb, yb), pc["B"], (285.2, yb)], 0.52)
        top.via1(285.2, yb)
        top.wire("metal1", [(285.2, yb), (287.8, yb)], 0.52)
        top.via1(287.8, yb)
        top.wire("metal2", [(287.8, yb), pp["B"]], 0.52)

    # EA guard bar & EA NMOS bodies/sources -> x_vgb (p_nl & p_nm tie active S + outer dummy fingers via S!)
    top.wire("metal2", [(x_ea - 19.0, y_ea_gb), (x_vgb, y_ea_gb)], 0.80)
    for pm in (p_nb, p_nr, p_pre_sink):
        top.wire("metal2", [pm["B"], (x_vgb, pm["B"][1])], 0.48)
    top.wire("metal2", [p_nl["S"], (x_vgb, p_nl["S"][1])], 0.56)

    # Under-MIM High-R bodies -> M2 bar at y=-44.5 -> x_vss_west (stops at x=135.5, WEST of Kelvin 139.2!)
    y_hr_b = -44.5
    top.wire("metal2", [(x_vss_west, y_hr_b), (135.5, y_hr_b)], 0.52)
    via2_clean(top, x_vss_west, y_hr_b)
    for pr in (p_rcas, p_rref, p_rpreoff, p_rpre, p_rcl_arr):
        top.wire("metal2", [pr["B"], (pr["B"][0], y_hr_b)], 0.40)

    # South Ctrl, Xboff/Xoff/Xn2 & Trim Switches bodies -> M2 vss bus at y=-57.24 (width 0.36 -> clear of B & y_trk_en!)
    y_sw_vss = -57.24
    top.wire("metal2", [(x_vss_west, y_sw_vss), (180.0, y_sw_vss)], 0.36)
    via2_clean(top, x_vss_west, y_sw_vss)
    for pm in (p_tg_n, p_inv_n, p_rst_n, p_boff, p_off, p_n2, *p_sws):
        top.wire("metal2", [pm["B"], (pm["B"][0], y_sw_vss)], 0.34)

    # Divider vss & Xrzero.B: rdiv_bot vss/B drops straight down x=141.5 (between Kelvin 139.2 & p_sws[0] 147.0) to y_sw_vss!
    top.wire("metal2", [p_rdiv_bot["vss"], (p_rdiv_bot["vss"][0], -45.36), (141.5, -45.36), (141.5, y_sw_vss)], 0.42)
    top.wire("metal2", [p_rdiv_bot["B"], (141.5, p_rdiv_bot["B"][1])], 0.42)
    top.wire("metal2", [p_rdiv_top["B"], (135.5, p_rdiv_top["B"][1]), (135.5, y_hr_b)], 0.44)
    top.wire("metal2", [p_rzero["B"], (210.8, p_rzero["B"][1]), (210.8, y_ea_gb), (x_ea - 19.0, y_ea_gb)], 0.44)

    # Clamp vss -> vertical M2 at x=210.4 + LOW-R M4 BRIDGE directly to x_vgb (251.5) at y=p_clamp["S_right"][1] (+33.16)!
    # Cuts Xclamp source ground resistance from ~30 Ohm -> ~2.2 Ohm (eliminates source degeneration during 4 mA/1 ns unload!)
    x_cl_vss = 210.4
    y_cl_gnd = p_clamp["S_right"][1]
    top.wire("metal2", [(x_cl_vss, y_ea_gb), (x_cl_vss, y_cl_gnd)], 0.56)
    top.wire("metal2", [(x_cl_vss, p_cl_n1["B"][1]), (x_cl_vss, y_cl_gnd)], 1.20)
    top.wire("metal2", [(x_cl_vss, y_ea_gb), (x_ea - 19.0, y_ea_gb)], 0.56)
    top.wire("metal2", [p_clamp["S"], (x_cl_vss, y_cl_gnd)], 2.20)
    # 1x5 vertical via2 + 1x5 vertical via3 (X half-width 0.35 -> 0.85 um clear of pre_g M3 211.8!) -> 2.8 um M4 bridge to x_vgb!
    for dy_v in (-1.2, -0.6, 0.0, +0.6, +1.2):
        via2_clean(top, x_cl_vss, grid(y_cl_gnd + dy_v))
    via3_array(top, x_cl_vss, y_cl_gnd, nx=1, ny=5, pitch=0.60)
    top.wire("metal4", [(x_cl_vss, y_cl_gnd), (x_vgb, y_cl_gnd)], 2.80)
    via3_array(top, x_vgb, y_cl_gnd, nx=2, ny=4, pitch=0.60)
    # Parallel M4 + M5 ground super-highway along x_vgb: ties m_cout M5 (+54.3) & Xclamp.S (+33.16) directly to vss port!
    # Jumps cleanly over vin M5 (+10.9, width 1.8) via x_vgb M4/M3, leaving >= 5 um M5 clearance on both sides!
    top.wire("metal4", [(x_vgb, -47.0), (x_vgb, +21.5)], 2.20)
    for y_r in (-45.0, -25.0, -5.0, +15.0, +20.0):
        via3_array(top, x_vgb, y_r, nx=2, ny=2)
    top.wire("metal5", [(x_vgb, +18.0), (x_vgb, grid(y_vss_m5_east - 0.7))], 3.00)
    via4_array(top, x_vgb, y_cl_gnd, nx=1, ny=2, pitch=2.1)
    via4_array(top, x_vgb, +19.2, nx=1, ny=1)
    y_vss_m5_south = -63.50
    top.wire("metal5", [(x_vgb, grid(y_vss_m5_south + 0.4)), (x_vgb, +3.6)], 3.00)
    for yv_g in (+1.5, -20.0, -43.0):
        via4_array(top, x_vgb, yv_g, nx=1, ny=2, pitch=2.1)
    top.wire("metal5", [(x_vgb, y_vss_m5_south), (304.5, y_vss_m5_south)], 2.20)
    top.wire("metal4", [(x_vgb, y_vss_m5_south), (304.5, y_vss_m5_south)], 2.20)
    via4_array(top, x_vgb, y_vss_m5_south, nx=2, ny=1, pitch=2.1)
    via4_array(top, 303.0, y_vss_m5_south, nx=2, ny=1, pitch=2.1)
    top.wire("metal2", [p_cl_n1["B"], (x_cl_vss, p_cl_n1["B"][1])], 1.00)
    for pm in (p_cl_nref, p_cl_off, p_cl_off2):
        top.wire("metal2", [pm["B"], (x_cl_vss, pm["B"][1])], 0.38)
    top.wire("metal2", [p_cl_r2["R2"], (p_cl_r2["R2"][0], +2.5), (x_cl_vss, +2.5)], 0.44)
    top.wire("metal2", [p_cl_r2["B"], (p_cl_r2["B"][0], +2.5)], 0.44)
    # p_cl_r1["B"] (~+3.9, strictly below cl_nb +6.3!) drops straight to y=+2.5 -> p_cl_r2["B"]!
    top.wire("metal2", [p_cl_r1["B"], (p_cl_r1["B"][0], +2.5), (p_cl_r2["B"][0], +2.5)], 0.42)

    # --- 5. HV PRE-REGULATOR NETS: pre_d, pre_g, va ---
    # pre_d: M2 @ y=+47.3 (NORTH of y_preg_m2=+46.2 so p_rpre["b"] NEVER crosses pre_d!) -> M3 vertical at x=212.4 (0.24 um WEST of p_pre_p 212.84!)
    via2_clean(top, p_pre_d["gx"], p_pre_d["d_bus_y"])
    top.wire("metal3", [(p_pre_d["gx"], p_pre_d["g_ys"][0]), (p_pre_d["gx"], p_pre_d["d_bus_y"])], 0.52)
    x_pred_m3 = p_pre_d["d_xs"][-1]
    via2_clean(top, x_pred_m3, p_pre_d["d_bus_y"])
    top.wire("metal3", [(x_pred_m3, p_pre_d["d_bus_y"]), (x_pred_m3, p_pre_sink["D"][1])], 0.48)
    via2_clean(top, x_pred_m3, p_pre_sink["D"][1])
    top.wire("metal2", [(x_pred_m3, p_pre_sink["D"][1]), p_pre_sink["D"]], 0.44)
    y_pred_m2 = +47.3
    top.wire("metal2", [p_rpreoff["b"], (p_rpreoff["b"][0], y_pred_m2), (p_rpre["a"][0], y_pred_m2), p_rpre["a"]], 0.40)
    top.wire("metal2", [(p_rpre["a"][0], y_pred_m2), (212.4, y_pred_m2)], 0.40)
    via2_clean(top, 212.4, y_pred_m2)
    via2_clean(top, 212.8, p_pre_d["d_bus_y"])
    top.wire("metal3", [(212.4, y_pred_m2), (212.5, y_pred_m2), (212.5, +38.8), (212.8, +38.8), (212.8, p_pre_d["d_bus_y"])], 0.36)
    top.wire("metal2", [(212.8, p_pre_d["d_bus_y"]), p_pre_d["D"]], 0.48)

    # pre_g: M2 @ y=+46.2 -> via2 at x=211.3 (0.80 um clear of vin 210.0 & 0.58 um clear of pre_d via2 212.4!)
    # -> steps East to x=211.8 at y=+41.2 (NORTH of m_chp.b pillar +39.8!) -> down to m_cpre.a & up to p_pre_p.gx!
    y_preg_m2 = +46.2
    top.wire("metal2", [p_rpre["b"], (p_rpre["b"][0], y_preg_m2), (211.3, y_preg_m2)], 0.40)
    via2_clean(top, 211.3, y_preg_m2)
    top.wire("metal3", [(211.8, m_cpre["ya"]), (211.8, +41.2), (211.3, +41.2), (211.3, p_pre_p["g_ys"][0]), (p_pre_p["gx"], p_pre_p["g_ys"][0])], 0.36)
    via3_single(top, 211.8, m_cpre["ya"])
    top.wire("metal4", [m_cpre["a"], (211.8, m_cpre["ya"])], 0.56)

    # va: EA East spine at x=249.6
    x_va_m3 = 249.6
    for pm_va in (p_pre_p, p_pre_d, p_p2, p_pt):
        y_t = pm_va["d_bus_y"] if pm_va is p_pre_p else pm_va["s_bus_y"]
        via2_clean(top, x_va_m3, y_t)
        top.wire("metal2", [(pm_va["d_xs"][-1] if pm_va is p_pre_p else pm_va["s_xs"][-1], y_t), (x_va_m3, y_t)], 0.56)
    top.wire("metal2", [p_pd["S"], (x_va_m3, p_pd["S"][1])], 0.48)
    via2_clean(top, x_va_m3, p_pd["S"][1])
    # Tie all 8 outer diff-pair dummy fingers (p_pl_a/p_pr_a @ -21.8, p_pr_b/p_pl_b @ -30.0) straight to va!
    for pq_l in (p_pl_a, p_pr_b):
        yd = pq_l["dum_l"][1]
        top.wire("metal2", [pq_l["dum_l"], (x_va_m3, yd)], 0.44)
        via2_clean(top, x_va_m3, yd)
    top.wire("metal3", [(x_va_m3, p_pd["S"][1]), (x_va_m3, p_pre_p["d_bus_y"])], 0.90)
    # Route Xcva.a M4 up the clean 1.59 um alley x=178.34 (width 0.40 -> >=0.59 um met4.5b clear on BOTH sides!)
    y_va_m4_pass = +25.4
    top.wire("metal4", [m_cva["a"], (178.34, m_cva["ya"]), (178.34, y_va_m4_pass), (180.5, y_va_m4_pass)], 0.40)
    top.wire("metal4", [(180.5, y_va_m4_pass), (x_va_m3, y_va_m4_pass)], 0.60)
    via3_array(top, x_va_m3, y_va_m4_pass, nx=2, ny=2)
    # Connect Xcbp.b (pillar at x~203.8, y=-54.4) UP to y=-50.5 (4.85 um BELOW m_cbp.ya -45.65!) -> M4 east to x_va_m3!
    top.wire("metal3", [m_cbp["b"], (m_cbp["b"][0], -50.5)], 0.64)
    via3_single(top, m_cbp["b"][0], -50.5)
    top.wire("metal4", [(m_cbp["b"][0], -50.5), (x_va_m3, -50.5)], 0.64)
    via3_single(top, x_va_m3, -50.5)
    top.wire("metal3", [(x_va_m3, -50.5), (x_va_m3, p_pd["S"][1])], 0.64)

    # --- 6. CASCODE GATE: casg (starts at p_rcas["b"][0] ~ 7 so Xrcas.b connects straight into Xccas.a & gx_cas!) ---
    gx_cas = p_cas[0]["gx"]  # ~ 254.7 (strictly WEST of vin M4/M5 plate 258.0!)
    top.wire("metal3", [(gx_cas, p_cas[-1]["g_ys"][0]), (gx_cas, p_cas[0]["g_ys"][-1])], 0.56)
    y_casg_m4 = grid(m_ccas["ya"])  # +55.53
    top.wire("metal4", [(p_rcas["b"][0], y_casg_m4), (gx_cas, y_casg_m4)], 0.80)
    via3_array(top, gx_cas, y_casg_m4, nx=2, ny=2)
    top.wire("metal3", [(gx_cas, p_cas[0]["g_ys"][-1]), (gx_cas, y_casg_m4)], 0.56)
    # Tap Xrcas.b (LEFT side x~7!) straight NORTH on M2 to y_casg_m4 (100% planar, WEST of everything!)
    top.wire("metal2", [p_rcas["b"], (p_rcas["b"][0], y_casg_m4)], 0.44)
    via2_clean(top, p_rcas["b"][0], y_casg_m4)
    via3_single(top, p_rcas["b"][0], y_casg_m4)

    # --- 7. REFERENCE PATH & SOUTH CONTROL BUSES (0.52 um M2 pitch, 0.28 wire + 0.24 gap >> 0.14 DRC!) ---
    y_trk_en   = -57.84
    y_trk_bg   = -58.36
    y_trk_vgi  = -58.88
    y_trk_host = -59.40
    y_trk_off  = -59.92
    y_trk_rloc = -60.44
    y_trk_gate = -60.96
    y_trk_x    = -61.48
    y_trk_ib   = -62.00

    def drop_to_m2_track(pt: tuple[float, float], y_trk: float, x_off: float = 0.0) -> float:
        x0 = grid(pt[0] + x_off)
        if abs(x_off) > 0.01:
            top.wire("metal2", [pt, (x0, pt[1])], 0.28)
        via2_clean(top, x0, pt[1])
        top.wire("metal3", [(x0, pt[1]), (x0, y_trk)], 0.34)
        via2_clean(top, x0, y_trk)
        return x0

    # bg: tg_n.D & tg_p.D (x_off = +0.1, >= 1.1 um clear of B @ -1.0 and G @ +1.3!)
    x_bg_l = drop_to_m2_track(p_tg_n["D"], y_trk_bg, x_off=+0.1)
    x_bg_r = drop_to_m2_track(p_tg_p["D"], y_trk_bg, x_off=+0.1)
    top.wire("metal2", [(-5.4, y_trk_bg), (x_bg_r, y_trk_bg)], 0.28)

    # ref_start: tg_n.S & tg_p.S -> x=20.5 -> jumps UNDER y_hr_b (-44.5, M2) on M1 [-46.0..-43.0] -> p_rref["a"]!
    for p_tg in (p_tg_n, p_tg_p):
        xs = grid(p_tg["S"][0] + 2.2)
        top.wire("metal2", [p_tg["S"], (xs, p_tg["S"][1]), (xs, -49.0)], 0.30)
    top.wire("metal2", [(grid(p_tg_n["S"][0] + 2.2), -49.0), (20.5, -49.0), (20.5, -46.0)], 0.38)
    top.via1(20.5, -46.0)
    top.wire("metal1", [(20.5, -46.0), (20.5, -43.0)], 0.38)
    top.via1(20.5, -43.0)
    top.wire("metal2", [(20.5, -43.0), (20.5, +43.5), (p_rref["a"][0], +43.5), p_rref["a"]], 0.38)

    # ref_local: Xrefres.b (x~62) -> via2 at (69.0, +44.0) -> M3 OVER y_vin_m2 (+49.6) to m_cref.ya & down to y_trk_rloc!
    x_rloc_al = 69.0
    top.wire("metal4", [m_cref["a"], (x_rloc_al, m_cref["ya"])], 0.60)
    via3_single(top, x_rloc_al, m_cref["ya"])
    top.wire("metal2", [p_rref["b"], (p_rref["b"][0], +44.0), (x_rloc_al, +44.0)], 0.42)
    via2_clean(top, x_rloc_al, +44.0)
    top.wire("metal3", [(x_rloc_al, m_cref["ya"]), (x_rloc_al, y_trk_rloc)], 0.44)
    via2_clean(top, x_rloc_al, y_trk_rloc)
    x_rst_d = drop_to_m2_track(p_rst_n["D"], y_trk_rloc, x_off=+0.1)
    x_rloc_ea = 216.2
    top.wire("metal2", [(x_rst_d, y_trk_rloc), (x_rloc_ea, y_trk_rloc)], 0.28)
    via2_clean(top, x_rloc_ea, y_trk_rloc)
    top.wire("metal3", [(x_rloc_ea, y_trk_rloc), (x_rloc_ea, grid(p_pr_a["G"][1] + 1.10))], 0.40)
    # Planar common-centroid quad: RIGHT device uses +1.10 (higher), LEFT device uses +0.30 (lower) -> ZERO crossing!
    for ppr, dy_r in ((p_pr_a, +1.10), (p_pr_b, +0.30)):
        yr = grid(ppr["G"][1] + dy_r)
        via2_clean(top, x_rloc_ea, yr)
        top.wire("metal2", [(x_rloc_ea, yr), (ppr["G"][0], yr), ppr["G"]], 0.34)

    # host (B @ x_off = -1.0 -> >= 1.1 um clear of D @ +0.1!)
    x_h1 = drop_to_m2_track(p_tg_p["B"], y_trk_host, x_off=-1.0)
    x_h2 = drop_to_m2_track(p_inv_p["B"], y_trk_host, x_off=-1.0)
    x_h3 = drop_to_m2_track(p_copy["vdd"], y_trk_host, x_off=0.0)
    top.wire("metal2", [(-5.4, y_trk_host), (x_h3, y_trk_host)], 0.28)

    # enable (G @ x_off = +1.3 -> >= 1.2 um clear of D @ +0.1!)
    x_e1 = drop_to_m2_track(p_tg_n["G"], y_trk_en, x_off=+1.3)
    x_e2 = drop_to_m2_track(p_inv_n["G"], y_trk_en, x_off=+1.3)
    x_e3 = drop_to_m2_track(p_inv_p["G"], y_trk_en, x_off=+1.3)
    top.wire("metal2", [(-5.4, y_trk_en), (x_e3, y_trk_en)], 0.28)

    # vgi: jog SOUTH on M2 to y=-50.8 (2.2 um SOUTH of m_ccas M3 stub -48.6!) before M3 drop!
    vgi_drop_pt = (p_copy["vgi"][0], -50.8)
    top.wire("metal2", [p_copy["vgi"], vgi_drop_pt], 0.34)
    x_vgi = drop_to_m2_track(vgi_drop_pt, y_trk_vgi, x_off=0.0)
    top.wire("metal2", [(-5.4, y_trk_vgi), (x_vgi, y_trk_vgi)], 0.28)

    # off: run North on M2 at x_cl_off_bus=199.2 (EAST of rdiv_top 188.8 & WEST of p_rzero 202.0!), then M1 across [0.0..+27.0] UNDER all clamp M2!
    x_o1 = drop_to_m2_track(p_inv_n["D"], y_trk_off, x_off=+0.1)
    x_o2 = drop_to_m2_track(p_inv_p["D"], y_trk_off, x_off=+0.1)
    x_o3 = drop_to_m2_track(p_tg_p["G"], y_trk_off, x_off=+1.3)
    x_o4 = drop_to_m2_track(p_rst_n["G"], y_trk_off, x_off=+1.3)
    x_o5 = drop_to_m2_track(p_boff["G"], y_trk_off, x_off=-0.8)
    x_o6 = drop_to_m2_track(p_off["G"], y_trk_off, x_off=-0.8)
    x_cl_off_bus = 199.2
    top.wire("metal2", [(x_o3, y_trk_off), (x_cl_off_bus, y_trk_off), (x_cl_off_bus, -2.0)], 0.30)
    top.via1(x_cl_off_bus, -2.0)
    top.wire("metal1", [(x_cl_off_bus, -2.0), (x_cl_off_bus, p_cl_en["G"][1])], 0.36)
    for pcl_o in (p_cl_off2, p_cl_off, p_cl_en):
        top.via1(x_cl_off_bus, pcl_o["G"][1])
        top.wire("metal2", [pcl_o["G"], (x_cl_off_bus, pcl_o["G"][1])], 0.34)

    # ibias (offset p_nb.D -> 214.8 & p_nb.G -> 217.3, cleanly clear of x_fbin_p=212.8, x_rloc_ea=216.2 & x_bp_m3=218.5!)
    x_ib0 = drop_to_m2_track(p_copy["out"], y_trk_ib, x_off=0.0)
    drop_to_m2_track(p_boff["D"], y_trk_ib, x_off=+1.5)
    drop_to_m2_track(p_nb["D"], y_trk_ib, x_off=+1.5)
    drop_to_m2_track(p_nb["G"], y_trk_ib, x_off=+2.8)
    for pt_ib in (p_nr["G"], p_pre_sink["G"]):
        drop_to_m2_track(pt_ib, y_trk_ib, x_off=0.0)
    top.wire("metal2", [(x_ib0, y_trk_ib), (p_pre_sink["G"][0], y_trk_ib)], 0.28)

    # --- 8. ERROR AMPLIFIER INTERNAL NETS: bp, tail, d, x, cz, gate ---
    # bp: x=218.5 M3 spine; p_nr["D"] jogs NORTH to y=-45.3 (M2, clear of y_ea_gb -43.9 & p_nb.G -45.8, passes UNDER x_d/x_x M3!)
    x_bp_m3 = 218.5
    top.wire("metal2", [p_nr["D"], (p_nr["D"][0], -45.3), (x_bp_m3, -45.3)], 0.38)
    via2_clean(top, x_bp_m3, -45.3)
    top.wire("metal3", [(x_bp_m3, -45.3), (x_bp_m3, p_p2["g_ys"][-1])], 0.44)
    for pt_bp in (p_pd["D"], p_pd["G"]):
        top.wire("metal2", [pt_bp, (x_bp_m3, pt_bp[1])], 0.38)
        via2_clean(top, x_bp_m3, pt_bp[1])
    top.wire("metal3", [(x_bp_m3, p_pt["g_ys"][0]), (p_pt["gx"], p_pt["g_ys"][0])], 0.44)
    top.wire("metal3", [(x_bp_m3, p_p2["g_ys"][0]), (p_p2["gx"], p_p2["g_ys"][0])], 0.44)
    via3_single(top, x_bp_m3, m_cbp["ya"])
    top.wire("metal4", [m_cbp["a"], (x_bp_m3, m_cbp["ya"])], 0.56)

    # tail: x=230.2 M3 spine
    x_tail_m3 = x_ea
    for pq in (p_pl_a, p_pr_a, p_pr_b, p_pl_b):
        top.wire("metal2", [pq["S"], (x_tail_m3, pq["S"][1])], 0.44)
        via2_clean(top, x_tail_m3, pq["S"][1])
    via2_clean(top, x_tail_m3, p_pt["d_bus_y"])
    top.wire("metal3", [(x_tail_m3, p_pl_b["S"][1]), (x_tail_m3, p_pt["d_bus_y"])], 0.52)

    # d: x=221.5 M3 spine (spans ALL the way down to p_nl["D"][1] = -54.60!)
    x_d_m3 = 221.5
    for pd_pt in (p_pl_a["D"], p_nl["D"], p_nl["G"], p_nm["G"]):
        top.wire("metal2", [pd_pt, (x_d_m3, pd_pt[1])], 0.38)
        via2_clean(top, x_d_m3, pd_pt[1])
    plb_r = (p_pl_b["d_xs"][-1], p_pl_b["D"][1])
    top.wire("metal2", [plb_r, (plb_r[0], -30.2), (x_d_m3, -30.2)], 0.38)
    via2_clean(top, x_d_m3, -30.2)
    top.wire("metal3", [(x_d_m3, p_nl["D"][1]), (x_d_m3, p_pl_a["D"][1])], 0.44)

    # x: x=236.5 M3 spine; p_rzero["R1"] runs M1 over x_cl_vss -> M2 down at x=211.4 -> East at y=-34.5 (cleanly between p_pl_b & p_pd!) to x_x_m3!
    x_x_m3 = 236.5
    for px_pt in (p_pr_a["D"], p_nm["D"]):
        top.wire("metal2", [px_pt, (x_x_m3, px_pt[1])], 0.38)
        via2_clean(top, x_x_m3, px_pt[1])
    prb_r = (p_pr_b["d_xs"][-1], p_pr_b["D"][1])
    top.wire("metal2", [prb_r, (prb_r[0], -29.2), (x_x_m3, -29.2)], 0.38)
    via2_clean(top, x_x_m3, -29.2)
    top.wire("metal3", [(x_x_m3, y_trk_x), (x_x_m3, p_pr_a["D"][1])], 0.44)
    via2_clean(top, x_x_m3, y_trk_x)
    # Route p_rzero["R1"] down on M1 at x=209.2 (WEST of x_cl_vss=210.4 & p_pl_a/p_pr_b dum_l=211.47!) -> jump East at y=-34.5 -> M2 to x_x_m3!
    top.wire("metal1", [p_rzero["R1"], (209.2, p_rzero["R1"][1]), (209.2, -34.5), (211.4, -34.5)], 0.38)
    top.via1(211.4, -34.5)
    top.wire("metal2", [(211.4, -34.5), (x_x_m3, -34.5)], 0.38)
    via2_clean(top, x_x_m3, -34.5)
    x_n2g = drop_to_m2_track(p_n2["G"], y_trk_x, x_off=-1.2)
    top.wire("metal2", [(x_n2g, y_trk_x), (x_x_m3, y_trk_x)], 0.30)

    # cz: Xrzero.R2 -> x=208.5 (0.9 um clear of m_cc["b"] pillar right 207.6!) -> M3/M4 to Xccomp.a
    top.wire("metal2", [p_rzero["R2"], (208.5, p_rzero["R2"][1])], 0.40)
    via2_clean(top, 208.5, p_rzero["R2"][1])
    top.wire("metal3", [(208.5, p_rzero["R2"][1]), (208.5, m_cc["ya"])], 0.44)
    via3_single(top, 208.5, m_cc["ya"])
    top.wire("metal4", [m_cc["a"], (208.5, m_cc["ya"])], 0.56)

    # gate: x_gt_m3 = 211.9 -> Stage B M2 @ -52.2 -> x_gpass_m2 = 286.2 -> M1 horizontal taps UNDER p_pass d_xs[0] (287.07, M2) to gx_pass!
    gx_pass = p_pass[0]["gx"]  # ~ 287.67
    x_gpass_m2 = 286.2
    top.wire("metal2", [(x_gpass_m2, -52.2), (x_gpass_m2, p_pass[0]["g_ys"][-1])], 0.48)
    for pp in p_pass:
        for gy in pp["g_ys"]:
            top.via1(x_gpass_m2, gy)
            top.wire("metal1", [(x_gpass_m2, gy), (gx_pass, gy)], 0.24)
    x_gt_m3 = 211.9
    top.wire("metal2", [p_p2["D"], (x_gt_m3, p_p2["d_bus_y"])], 0.48)
    via2_clean(top, x_gt_m3, p_p2["d_bus_y"])
    top.wire("metal4", [m_cc["b"], (x_gt_m3, m_cc["b"][1])], 0.56)
    via3_single(top, x_gt_m3, m_cc["b"][1])
    via3_single(top, x_gt_m3, m_cghf["ya"])
    top.wire("metal4", [m_cghf["a"], (x_gt_m3, m_cghf["ya"])], 0.56)
    x_offd = drop_to_m2_track(p_off["D"], y_trk_gate, x_off=+0.5)
    x_n2d  = drop_to_m2_track(p_n2["D"],  y_trk_gate, x_off=+1.0)
    top.wire("metal2", [(x_offd, y_trk_gate), (x_gt_m3, y_trk_gate)], 0.34)
    via2_clean(top, x_gt_m3, y_trk_gate)
    top.wire("metal3", [(x_gt_m3, y_trk_gate), (x_gt_m3, p_p2["d_bus_y"])], 0.46)
    # 2-stage zero-crossing bridge to Xpass gates at y=-52.2 (nx=1, ny=2 via3 -> narrow M3 clear of x_fbin_p=213.0!):
    y_gt_br = -52.2
    x_gt_step = 253.8
    via3_array(top, x_gt_m3, y_gt_br, nx=1, ny=2)
    top.wire("metal4", [(x_gt_m3, y_gt_br), (x_gt_step, y_gt_br)], 0.64)
    via3_single(top, x_gt_step, y_gt_br)
    via2_clean(top, x_gt_step, y_gt_br)
    top.wire("metal2", [(x_gt_step, y_gt_br), (x_gpass_m2, y_gt_br)], 0.56)

    # --- 9. FEEDBACK DIVIDER, TRIM SWITCHES, CFF & LOOP-BREAK PORTS ---
    top.wire("metal2", [p_rdiv_top["n5"], (p_rdiv_top["n5"][0], -23.8), (p_rdiv_bot["n5"][0], -23.8), p_rdiv_bot["n5"]], 0.42)
    for k in range(5):
        xm = grid((p_sws[k]["D_right"][0] + p_sws[k + 1]["S"][0]) / 2.0)
        top.wire("metal2", [p_sws[k]["D_right"], (xm, p_sws[k]["D_right"][1]), (xm, p_sws[k + 1]["S"][1]), p_sws[k + 1]["S"]], 0.32)
    for k in range(6):
        tap_pt = p_rdiv_bot[f"n{k}"]
        # Exit UP from D_right (1.6 um EAST of G -> ZERO short to t0..t5!)
        sw_d = p_sws[k]["D_right"]
        yk = grid(-46.0 - k * 0.56)  # -46.0 .. -48.80
        top.wire("metal2", [tap_pt, (tap_pt[0], yk), (sw_d[0], yk), sw_d], 0.28)

    # fb_return: Xcff.a stays at m_cff["ya"] (-45.8, strictly NORTH of m_cff C2 via3!) east to x=100.5, then -47.8 to x_fbret_p=180.4!
    y_trim_port = -64.5
    x_fbret_p = 180.4
    top.wire("metal4", [m_cff["a"], (100.5, m_cff["ya"]), (100.5, -47.8), (x_fbret_p, -47.8)], 0.50)
    via3_single(top, x_fbret_p, -47.8)
    via2_clean(top, x_fbret_p, -47.8)
    top.wire("metal2", [p_rdiv_top["fb_return"], (x_fbret_p, p_rdiv_top["fb_return"][1]), (x_fbret_p, -47.8)], 0.42)
    top.wire("metal3", [(x_fbret_p, -47.8), (x_fbret_p, y_trim_port)], 0.44)

    # fb_input: planar common-centroid quad (p_pl_a LEFT uses +0.60, p_pl_b RIGHT uses +1.10 -> ZERO met2.2 / crossing!)
    x_fbin_p = 213.0
    top.wire("metal3", [(x_fbin_p, y_trim_port), (x_fbin_p, grid(p_pl_a["G"][1] + 0.60))], 0.40)
    for ppl, dy_f in ((p_pl_a, +0.60), (p_pl_b, +1.10)):
        yf = grid(ppl["G"][1] + dy_f)
        via2_clean(top, x_fbin_p, yf)
        top.wire("metal2", [(x_fbin_p, yf), (ppl["G"][0], yf), ppl["G"]], 0.34)

    if not is_probe:
        top.wire("metal3", [(x_fbret_p, y_trim_port), (x_fbin_p, y_trim_port)], 0.48)

    # --- 10. ACTIVE OVERSHOOT CLAMP INTERNAL NETS (100% zero-crossing M1/M2!) ---
    # cl_en_n: p_cl_en["D"] exits WEST to 192.2 first (clear of p_cl_en["G"]!) -> y=+30.0 -> p_rcl_arr["a"]
    top.wire("metal2", [p_cl_en["D"], (192.2, p_cl_en["D"][1]), (192.2, +30.0), (p_rcl_arr["a"][0], +30.0), p_rcl_arr["a"]], 0.36)
    # cl_nb: p_rcl_arr["mid"] steps East to x=128.5, jumps UNDER cl_en_n (+30.0) & cl_in (+16.9) on M1 -> y=+6.3 -> p_cl_nref["D"]/["G"]
    top.wire("metal2", [p_cl_nref["D"], (p_cl_nref["D"][0], p_cl_nref["G"][1]), p_cl_nref["G"]], 0.34)
    top.wire("metal2", [p_rcl_arr["mid"], (128.5, p_rcl_arr["mid"][1]), (128.5, +32.0)], 0.36)
    top.via1(128.5, +32.0)
    top.wire("metal1", [(128.5, +32.0), (128.5, +14.0)], 0.36)
    top.via1(128.5, +14.0)
    top.wire("metal2", [(128.5, +14.0), (128.5, p_cl_nref["D"][1]), p_cl_nref["D"]], 0.36)
    # cl_in: p_rcl_arr["b"] (-35) steps East to x=130.5, jumps UNDER cl_nb (+6.3) on M1 [+4.5..+8.5] -> p_cl_n1["G"];
    # p_cl_off["D"] exits WEST to 192.2 at y=+15.26 (STRICTLY SOUTH of p_cl_off["G"] +15.94!) then UP to +16.93!
    top.wire("metal2", [p_rcl_arr["b"], (130.5, p_rcl_arr["b"][1]), (130.5, +4.5)], 0.36)
    top.via1(130.5, +4.5)
    top.wire("metal1", [(130.5, +4.5), (130.5, +8.5)], 0.36)
    top.via1(130.5, +8.5)
    top.wire("metal2", [(130.5, +8.5), (130.5, p_cl_n1["G"][1]), p_cl_n1["G"], (192.2, p_cl_n1["G"][1]), (192.2, p_cl_off["D"][1]), p_cl_off["D"]], 0.36)
    # Xcl_chp.a (M4 @ +51.4) -> M3 down at x=215.2 -> M3 West at y=+15.2 over x_cl_vss to x=208.0 -> M2 to p_cl_off["D"]!
    x_chpa_m3 = 215.2
    top.wire("metal4", [m_chp["a"], (x_chpa_m3, m_chp["ya"])], 0.50)
    via3_single(top, x_chpa_m3, m_chp["ya"])
    top.wire("metal3", [(x_chpa_m3, m_chp["ya"]), (x_chpa_m3, p_cl_off["D"][1]), (208.0, p_cl_off["D"][1])], 0.42)
    via2_clean(top, 208.0, p_cl_off["D"][1])
    top.wire("metal2", [(208.0, p_cl_off["D"][1]), p_cl_off["D"]], 0.36)
    # v_b: multi-via1 M1 jumps for fast sub-ns clamp propagation!
    top.wire("metal2", [p_cl_r1["R2"], (152.8, p_cl_r1["R2"][1])], 0.40)
    top.via1(152.8, p_cl_r1["R2"][1])
    top.wire("metal1", [(152.8, p_cl_r1["R2"][1]), (152.8, +20.0)], 0.40)
    top.via1(152.8, +20.0)
    top.wire("metal2", [(152.8, +20.0), (174.0, +20.0), (174.0, p_cl_p2["G"][1]), p_cl_p2["G"]], 0.56)
    top.wire("metal2", [p_cl_n1["D"], (174.0, p_cl_n1["D"][1])], 0.56)
    for dx_v in (-0.22, +0.22):
        top.via1(grid(174.0 + dx_v), p_cl_n1["D"][1])
        top.via1(grid(174.0 + dx_v), +20.0)
    top.wire("metal1", [(174.0, p_cl_n1["D"][1]), (174.0, +20.0)], 0.72)
    # vg_clamp: multi-via1 M1 jump at x=187.5 + wide M2 into p_clamp["G"] (cuts R4649 40 Ohm -> <8 Ohm!)
    top.wire("metal2", [p_cl_r2["R1"], (p_cl_r2["R1"][0], +28.5)], 0.40)
    top.via1(p_cl_r2["R1"][0], +28.5)
    top.wire("metal1", [(p_cl_r2["R1"][0], +28.5), (p_cl_r2["R1"][0], +31.5)], 0.40)
    top.via1(p_cl_r2["R1"][0], +31.5)
    top.wire("metal2", [(p_cl_r2["R1"][0], +31.5), (191.0, +31.5)], 0.56)
    top.wire("metal2", [p_cl_p2["D_right"], (187.5, p_cl_p2["D_right"][1]), (187.5, +28.5)], 0.64)
    for dx_v in (-0.22, +0.22):
        top.via1(grid(187.5 + dx_v), +28.5)
        top.via1(grid(187.5 + dx_v), +31.5)
    top.wire("metal1", [(187.5, +28.5), (187.5, +31.5)], 0.76)
    top.wire("metal2", [(175.0, +31.5), (175.0, p_clamp["G"][1]), p_clamp["G"]], 0.64)
    top.wire("metal2", [p_cl_off2["D"], (191.0, p_cl_off2["D"][1])], 0.36)
    top.via1(191.0, p_cl_off2["D"][1])
    top.wire("metal1", [(191.0, p_cl_off2["D"][1]), (191.0, +31.5)], 0.36)
    top.via1(191.0, +31.5)

    # --- 11. TRIM BIT PERIMETER ROUTING (t0..t5 on M3 straight South to y_trim_port, passing UNDER vss M4!) ---
    for k in range(6):
        gx, gy = p_sws[k]["G"]
        via2_clean(top, gx, gy)
        top.wire("metal3", [(gx, gy), (gx, y_trim_port)], 0.40)

    # =========================================================================
    # EXPORT ALL 13 PRODUCTION (OR 15 PROBE) PORTS ON MACRO PERIMETER
    # =========================================================================
    top.port("vin",    "metal5", 266.0, +55.7)
    top.port("host",   "metal2", -5.4,  y_trk_host)
    top.port("quiet",  "metal5", 305.0, 0.0)
    top.port("bg",     "metal2", -5.4,  y_trk_bg)
    top.port("vgi",    "metal2", -5.4,  y_trk_vgi)
    top.port("enable", "metal2", -5.4,  y_trk_en)
    for k in range(6):
        top.port(f"t{k}", "metal3", p_sws[k]["G"][0], y_trim_port)
    if is_probe:
        top.port("fb_return", "metal3", x_fbret_p, y_trim_port)
        top.port("fb_input",  "metal3", x_fbin_p,  y_trim_port)
    top.port("vss",    "metal4", 304.5, y_vss_south)

    mag = work / f"{cell}.mag"
    top.write(mag)
    ref = make_reference_spice(work / f"{cell}_ref.spice", cell, is_probe=is_probe)
    rec = run_drc_lvs_pex_rcx(work, cell, ref, extract_rcx=extract_rcx)
    rec["is_probe"] = is_probe
    rec["expected_ports"] = PROBE_PORTS if is_probe else PROD_PORTS
    rec["ports_exact_match"] = rec["exported_ports"] == rec["expected_ports"]

    title = f"{cell} | DRC={rec['drc_total']}, LVS={'MATCH' if rec['lvs_match'] else 'FAIL'}"
    render_png(mag, work / f"{cell}.png", title)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    ap.add_argument("--probe-only", action="store_true")
    ap.add_argument("--no-rcx", action="store_true")
    args = ap.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    records = []
    rec_probe = build_supply_v2(out, is_probe=True, extract_rcx=not args.no_rcx)
    records.append(rec_probe)
    print(json.dumps({k: v for k, v in rec_probe.items() if k != "parasitics"}, indent=2), flush=True)

    if not args.probe_only:
        rec_prod = build_supply_v2(out, is_probe=False, extract_rcx=not args.no_rcx)
        records.append(rec_prod)
        print(json.dumps({k: v for k, v in rec_prod.items() if k != "parasitics"}, indent=2), flush=True)

    summary = {
        "architecture": "LDO v2: Active PMOS Pre-Regulator + High-R Cascode Filter + 0.15um Overshoot Clamp + 60.0 pF Stacked Fused MIM2",
        "total_mim_pf": 60.0,
        "smallcap_area_um2": 90066.22,
        "r4_area_um2": 181560.03,
        "macros": records,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        for r in records:
            cname = r["cell"]
            cdir = out / cname
            for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice", "_rcx.spice"):
                src = cdir / f"{cname}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
