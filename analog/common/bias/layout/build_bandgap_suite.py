#!/usr/bin/env python3
"""
Precision Full-Custom Analog Layout Suite for the Bandgap & Bias Distribution Subsystem (`common/bias`).

Covers all subcircuits in `common/bias/spice/bandgap.spice` and `common/bias/spice/bias_dist.spice`:
  1. `serdes_bg_amp`        : 2-Stage Bandgap Error Amplifier (Common-Centroid Input Pair & LVT PMOS Load + Rz + Cc)
  2. `serdes_bg_ota`        : Single-Stage V->I Error OTA (Common-Centroid Input Pair & LVT PMOS Load + Long-L Tail)
  3. `serdes_bandgap`       : Complete Bandgap + Constant-Swing V->I Core (3x3 Common-Centroid PNP Matrix + Q3,
                              20-Finger Common-Centroid Core PMOS Mirror Xm1..Xm5, 20-Finger Common-Centroid V->I PMOS
                              Array Xmv/Xo0..Xo3, Xamp, Xamp2, Startup Xsp/Xsn/Xsu, Slew Helper Xk, Common-Centroid
                              Unit-Matched Resistors Xr1/Xr2/Xrsa/Xrsb/Xrref + 5-Bit Trim Xrt4..0 & Switches Xs4..0,
                              Shielded MIM Cc=6pF & Cvgi=10pF)
  4. `serdes_bias_ref`      : Distribution-Ready Bandgap Reference Macro (`serdes_bandgap` with `Cvgi=2pF` + `Cvbg=5pF`)
  5. `serdes_ref_vbuf`      : RX Termination Common-Mode Reference Buffer (`Xr=105.2k` + Unity-Gain OTA Follower)
  6. `serdes_ref_pbuf`      : PLL Loop Filter 16:1 Precharge DAC & High-Slew OTA Buffer (`Xr0=95k` + `Xr1..15=2.667k`
                              + 16x Inv/TGate Mux + 300uA Switched LVT Follower)
  7. `serdes_bias_pcopy`    : Unit 4-Finger (10 uA) PMOS Current Copy Cell (`w=24, l=4, nf=4`)
  8. `serdes_bias_pcopy_n20`: 20-Finger (50 uA) PMOS Current Copy Macro for CTLE & Charge Pump
  9. `serdes_bias_pcopy_n85`: 85-Finger (212.5 uA) PMOS Current Copy Macro for CML Tail Bias
  10. `serdes_bias_cml`     : CML Local Tail Bias Diode (`nfet w=5, l=0.5`) + 5 pF Under-MIM Supply Decap (`Cdec`)
  11. `serdes_bias_ctle`    : CTLE Local Branch Bias Diode (`nfet_lvt w=8, l=0.5, nf=4`)
  12. `serdes_bias_cp`      : Charge Pump Local Bias Mirror & Pull-Up/Pull-Down Diodes (`Xdn/Xmn w=5, l=1` + `Xdp w=20, l=1, nf=4`)
"""
from __future__ import annotations

import sys
from pathlib import Path

WORKSPACE_ANALOG = Path(__file__).resolve().parents[3]
PACK_SCRIPTS = WORKSPACE_ANALOG / "layout/scripts"
sys.path.insert(0, str(PACK_SCRIPTS))

from layout_core import LayoutCanvas, LAYER_STYLE, plot_canvas  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

LAYER_STYLE["ppolyres"] = dict(fc="#d946ef", ec="#86198f", alpha=0.72, z=4, label="ppolyres (high_po)")
LAYER_STYLE["pnp"] = dict(fc="#fb7185", ec="#be123c", alpha=0.45, z=5, label="pnp_05v5")

INTER_DIR = WORKSPACE_ANALOG / "common/bias/layout"
OUT_DIR = WORKSPACE_ANALOG / "layout/work"


# =========================================================================
# Sky130A Physical Primitive Builders (Exact Magic Tech Layer Compliance)
# =========================================================================

def draw_guard_ring(
    c: LayoutCanvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    kind: str = "p",          # "p" -> psubdiff (VSS), "n" -> nsubdiff in nwell (VDD)
    width: float = 0.60,
    metal2_ring: bool = True,
    well_margin: float = 0.24,
) -> dict:
    diff_lyr = "psubdiff" if kind == "p" else "nsubdiff"
    cut_lyr = "psubdiffcont" if kind == "p" else "nsubdiffcont"
    if kind == "n":
        c.R("nwell", x1 - well_margin, y1 - well_margin, x2 + well_margin, y2 + well_margin)

    bars = [
        (x1, y1, x2, y1 + width),          # bottom
        (x1, y2 - width, x2, y2),          # top
        (x1, y1, x1 + width, y2),          # left
        (x2 - width, y1, x2, y2),          # right
    ]
    for bx1, by1, bx2, by2 in bars:
        c.R(diff_lyr, bx1, by1, bx2, by2)
        c.R("locali", bx1 + 0.06, by1 + 0.06, bx2 - 0.06, by2 - 0.06)
        c.R("m1", bx1 + 0.05, by1 + 0.05, bx2 - 0.05, by2 - 0.05)
        if metal2_ring:
            c.R("m2", bx1 + 0.05, by1 + 0.05, bx2 - 0.05, by2 - 0.05)

    cy_bot, cy_top = round(y1 + width / 2.0, 3), round(y2 - width / 2.0, 3)
    cx_left, cx_right = round(x1 + width / 2.0, 3), round(x2 - width / 2.0, 3)

    nx = max(2, int((x2 - x1 - 2 * width) / 0.60))
    for i in range(nx + 1):
        cx = round(x1 + width + i * (x2 - x1 - 2 * width) / max(1, nx), 3)
        for cy in (cy_bot, cy_top):
            c.sq(cut_lyr, cx, cy, 0.17)
            c.sq("viali", cx, cy, 0.17)
            if metal2_ring and i % 3 == 0:
                c.via1(cx, cy, pad=0.34)

    ny = max(2, int((y2 - y1 - 2 * width) / 0.60))
    for j in range(ny + 1):
        cy = round(y1 + width + j * (y2 - y1 - 2 * width) / max(1, ny), 3)
        for cx in (cx_left, cx_right):
            c.sq(cut_lyr, cx, cy, 0.17)
            c.sq("viali", cx, cy, 0.17)
            if metal2_ring and j % 3 == 0:
                c.via1(cx, cy, pad=0.34)

    return {
        "bot": (round((x1 + x2) / 2.0, 3), cy_bot),
        "top": (round((x1 + x2) / 2.0, 3), cy_top),
        "left": (cx_left, round((y1 + y2) / 2.0, 3)),
        "right": (cx_right, round((y1 + y2) / 2.0, 3)),
        "bbox": (x1, y1, x2, y2),
    }


def draw_sky130_pnp_3p4(c: LayoutCanvas, x0: float, y0: float, emit_label: str | None = None) -> dict:
    W_PNP = 8.40
    col_bars = [
        (x0, y0, x0 + W_PNP, y0 + 0.55),
        (x0, y0 + W_PNP - 0.55, x0 + W_PNP, y0 + W_PNP),
        (x0, y0, x0 + 0.55, y0 + W_PNP),
        (x0 + W_PNP - 0.55, y0, x0 + W_PNP, y0 + W_PNP),
    ]
    for bx1, by1, bx2, by2 in col_bars:
        c.R("psubdiff", bx1, by1, bx2, by2)
        c.R("locali", bx1 + 0.05, by1 + 0.05, bx2 - 0.05, by2 - 0.05)
        c.R("m1", bx1 + 0.05, by1 + 0.05, bx2 - 0.05, by2 - 0.05)
    for k in range(11):
        off = round(0.85 + k * 0.67, 3)
        for cy in (round(y0 + 0.275, 3), round(y0 + W_PNP - 0.275, 3)):
            c.sq("psubdiffcont", round(x0 + off, 3), cy, 0.17)
            c.sq("viali", round(x0 + off, 3), cy, 0.17)
        for cx in (round(x0 + 0.275, 3), round(x0 + W_PNP - 0.275, 3)):
            c.sq("psubdiffcont", cx, round(y0 + off, 3), 0.17)
            c.sq("viali", cx, round(y0 + off, 3), 0.17)

    c.R("nwell", x0 + 1.00, y0 + 1.00, x0 + 7.40, y0 + 7.40)
    base_bars = [
        (x0 + 1.25, y0 + 1.25, x0 + 7.15, y0 + 1.75),
        (x0 + 1.25, y0 + 6.65, x0 + 7.15, y0 + 7.15),
        (x0 + 1.25, y0 + 1.25, x0 + 1.75, y0 + 7.15),
        (x0 + 6.65, y0 + 1.25, x0 + 7.15, y0 + 7.15),
    ]
    for bx1, by1, bx2, by2 in base_bars:
        c.R("nsubdiff", bx1, by1, bx2, by2)
        c.R("locali", bx1 + 0.05, by1 + 0.05, bx2 - 0.05, by2 - 0.05)
        c.R("m1", bx1 + 0.05, by1 + 0.05, bx2 - 0.05, by2 - 0.05)
    for k in range(8):
        off = round(1.95 + k * 0.64, 3)
        for cy in (round(y0 + 1.50, 3), round(y0 + 6.90, 3)):
            c.sq("nsubdiffcont", round(x0 + off, 3), cy, 0.17)
            c.sq("viali", round(x0 + off, 3), cy, 0.17)
        for cx in (round(x0 + 1.50, 3), round(x0 + 6.90, 3)):
            c.sq("nsubdiffcont", cx, round(y0 + off, 3), 0.17)
            c.sq("viali", cx, round(y0 + off, 3), 0.17)

    c.R("m1", x0 + 3.80, y0 + 0.15, x0 + 4.60, y0 + 1.65)
    c.R("m1", x0 + 0.15, y0 + 3.80, x0 + 1.65, y0 + 4.60)

    ex1, ey1, ex2, ey2 = round(x0 + 2.50, 3), round(y0 + 2.50, 3), round(x0 + 5.90, 3), round(y0 + 5.90, 3)
    c.R("pdiff", ex1, ey1, ex2, ey2)
    c.R("pnp", ex1, ey1, ex2, ey2)
    c.R("locali", ex1 + 0.15, ey1 + 0.15, ex2 - 0.15, ey2 - 0.15)
    c.R("m1", ex1 + 0.12, ey1 + 0.12, ex2 - 0.12, ey2 - 0.12)
    c.R("m2", ex1 + 0.20, ey1 + 0.20, ex2 - 0.20, ey2 - 0.20)
    for ix in range(4):
        for iy in range(4):
            cx = round(ex1 + 0.55 + ix * 0.76, 3)
            cy = round(ey1 + 0.55 + iy * 0.76, 3)
            c.sq("pdiffc", cx, cy, 0.17)
            c.sq("viali", cx, cy, 0.17)
            if ix in (1, 2) and iy in (1, 2):
                c.via1(cx, cy, pad=0.38)

    ecx, ecy = round(x0 + 4.20, 3), round(y0 + 4.20, 3)
    if emit_label:
        c.L(emit_label, ecx, ecy, "m2")

    return {
        "E": (ecx, ecy),
        "B": (round(x0 + 4.20, 3), round(y0 + 1.50, 3)),
        "C": (round(x0 + 4.20, 3), round(y0 + 0.28, 3)),
        "bbox": (x0, y0, round(x0 + W_PNP, 3), round(y0 + W_PNP, 3)),
    }


def draw_sky130_high_po_res(
    c: LayoutCanvas,
    xc: float,
    y_bot: float,
    l_body: float,
    w_res: float = 1.41,
    dummy: bool = False,
) -> dict:
    hw = round(w_res / 2.0, 3)
    head_l = 2.16
    y_r2_1 = round(y_bot, 3)
    y_r2_2 = round(y_r2_1 + head_l, 3)
    y_body_2 = round(y_r2_2 + l_body, 3)
    y_r1_2 = round(y_body_2 + head_l, 3)

    c.R("ppolyres", xc - hw, y_r2_2, xc + hw, y_body_2)
    c.R("xpolycontact", xc - hw, y_r2_1, xc + hw, y_r2_2)
    c.R("xpolycontact", xc - hw, y_body_2, xc + hw, y_r1_2)

    r2_cy = round((y_r2_1 + y_r2_2) / 2.0, 3)
    r1_cy = round((y_body_2 + y_r1_2) / 2.0, 3)

    if not dummy:
        for t_y1, t_y2, t_cy in ((y_r2_1, y_r2_2, r2_cy), (y_body_2, y_r1_2, r1_cy)):
            c.R("locali", xc - hw + 0.08, t_y1 + 0.08, xc + hw - 0.08, t_y2 - 0.08)
            c.R("viali", xc - hw + 0.08, t_y1 + 0.09, xc + hw - 0.08, t_y2 - 0.09)
            c.R("m1", xc - hw + 0.05, t_y1 + 0.06, xc + hw - 0.05, t_y2 - 0.06)
            c.R("m2", xc - hw + 0.05, t_cy - 0.55, xc + hw - 0.05, t_cy + 0.55)
            c.via1(xc, t_cy - 0.25, pad=0.36)
            c.via1(xc, t_cy + 0.25, pad=0.36)

    return {
        "R1": (xc, r1_cy),
        "R2": (xc, r2_cy),
        "bbox": (round(xc - hw, 3), y_r2_1, round(xc + hw, 3), y_r1_2),
    }


def draw_sky130_mim_cap(
    c: LayoutCanvas,
    x0: float,
    y0: float,
    w_cap: float = 22.20,
    l_cap: float = 22.20,
) -> dict:
    c.R("m3", x0 - 0.22, y0 - 0.22, x0 + w_cap + 1.85, y0 + l_cap + 0.22)
    c.R("mimcap", x0, y0, x0 + w_cap, y0 + l_cap)
    c.R("mimcapcontact", x0 + 0.20, y0 + 0.20, x0 + w_cap - 0.20, y0 + l_cap - 0.20)
    c.R("m4", x0 + 0.20, y0 + 0.20, x0 + w_cap - 0.20, y0 + l_cap - 0.20)
    c2_x1, c2_x2 = round(x0 + w_cap + 1.05, 3), round(x0 + w_cap + 1.65, 3)
    c.R("via3", c2_x1 + 0.08, y0 + 0.40, c2_x2 - 0.08, y0 + l_cap - 0.40)
    c.R("m4", c2_x1, y0 + 0.20, c2_x2, y0 + l_cap - 0.20)

    return {
        "C1": (round(x0 + w_cap / 2.0, 3), round(y0 + l_cap / 2.0, 3)),
        "C2": (round((c2_x1 + c2_x2) / 2.0, 3), round(y0 + l_cap / 2.0, 3)),
        "bbox": (round(x0 - 0.22, 3), round(y0 - 0.22, 3), round(x0 + w_cap + 1.85, 3), round(y0 + l_cap + 0.22, 3)),
    }


def draw_interdigitated_mos_row(
    c: LayoutCanvas,
    kind: str,
    w_finger: float,
    l_gate: float,
    x0: float,
    y0: float,
    finger_map: list[tuple[str, str, str]],
    lvt: bool = False,
    sd_width: float = 0.52,
    dummy_ends: bool = True,
    gate_tracks_top: list[str] | None = None,
    drain_tracks_bot: list[str] | None = None,
) -> dict:
    nd_layer = "ndiff" if kind == "n" else "pdiff"
    cut_layer = "ndiffc" if kind == "n" else "pdiffc"
    mark_layer = ("nmoslvt" if lvt else "nmos") if kind == "n" else ("pmoslvt" if lvt else "pmos")

    nf = len(finger_map)
    pitch = round(sd_width + l_gate, 3)
    end_sd = sd_width
    total_w = round(end_sd * 2 + nf * l_gate + (nf - 1) * sd_width, 3)
    y1, y2 = round(y0, 3), round(y0 + w_finger, 3)

    c.R(nd_layer, x0, y1, x0 + total_w, y2)

    g_nets = gate_tracks_top if gate_tracks_top is not None else list(dict.fromkeys(f[0] for f in finger_map))
    d_nets = drain_tracks_bot if drain_tracks_bot is not None else list(dict.fromkeys(f[1] for f in finger_map))

    source_on_top = (kind == "p")

    if source_on_top:
        y_src_1, y_src_2 = round(y2 + 0.28, 3), round(y2 + 0.72, 3)
        gate_track_ys = {gn: round(y_src_2 + 0.48 + idx * 0.72, 3) for idx, gn in enumerate(g_nets)}
        drain_track_ys = {dn: round(y1 - 0.48 - idx * 0.72, 3) for idx, dn in enumerate(d_nets)}
    else:
        y_src_1, y_src_2 = round(y1 - 0.72, 3), round(y1 - 0.28, 3)
        gate_track_ys = {gn: round(y_src_1 - 0.48 - idx * 0.72, 3) for idx, gn in enumerate(g_nets)}
        drain_track_ys = {dn: round(y2 + 0.48 + idx * 0.72, 3) for idx, dn in enumerate(d_nets)}

    gate_xs = []
    for i, (gn, dn, sn) in enumerate(finger_map):
        gx1 = round(x0 + end_sd + i * pitch, 3)
        gx2 = round(gx1 + l_gate, 3)
        gcx = round((gx1 + gx2) / 2.0, 3)
        gate_xs.append(gcx)
        gy_target = gate_track_ys[gn]
        if source_on_top:
            c.R("poly", gx1, round(y1 - 0.22, 3), gx2, round(gy_target + 0.20, 3))
        else:
            c.R("poly", gx1, round(gy_target - 0.20, 3), gx2, round(y2 + 0.22, 3))
        c.R(mark_layer, gx1, y1, gx2, y2)

        pad_w = max(0.36, min(l_gate, 0.60))
        c.sq_wh("poly", gcx, gy_target, pad_w, 0.38)
        c.sq("polycont", gcx, gy_target, 0.17)
        c.sq("locali", gcx, gy_target, 0.34)
        c.sq("viali", gcx, gy_target, 0.17)
        c.via1(gcx, gy_target, pad=0.34)

    if dummy_ends:
        for d_gx in (round(x0 - 0.32, 3), round(x0 + total_w + 0.14, 3)):
            c.R("poly", d_gx, round(y1 - 0.22, 3), round(d_gx + 0.18, 3), round(y2 + 0.22, 3))

    gate_ports = {}
    gx_span1, gx_span2 = round(x0 - 0.20, 3), round(x0 + total_w + 0.20, 3)
    for gn, gy_t in gate_track_ys.items():
        c.R("m2", gx_span1, gy_t - 0.18, gx_span2, gy_t + 0.18)
        gate_ports[gn] = (round((gx_span1 + gx_span2) / 2.0, 3), gy_t)

    n_cuts = max(1, int((w_finger - 0.28 - 0.17) / 0.38) + 1)
    span_y = (n_cuts - 1) * 0.38
    cut_y0 = round((y1 + y2) / 2.0 - span_y / 2.0, 3)
    cut_ys = [round(cut_y0 + k * 0.38, 3) for k in range(n_cuts)]

    src_cy = round((y_src_1 + y_src_2) / 2.0, 3)
    c.R("locali", gx_span1, y_src_1, gx_span2, y_src_2)
    c.R("m1", gx_span1, y_src_1, gx_span2, y_src_2)
    c.R("m2", gx_span1, y_src_1, gx_span2, y_src_2)

    drain_ports = {}
    for dn, dy_t in drain_track_ys.items():
        c.R("m2", gx_span1, dy_t - 0.18, gx_span2, dy_t + 0.18)
        drain_ports[dn] = (round((gx_span1 + gx_span2) / 2.0, 3), dy_t)

    for i in range(nf + 1):
        if i == 0:
            sx = round(x0 + end_sd / 2.0, 3)
        elif i == nf:
            sx = round(x0 + total_w - end_sd / 2.0, 3)
        else:
            sx = round(x0 + end_sd + i * pitch - sd_width / 2.0, 3)

        is_drain = (i % 2 == 1)
        if not is_drain:
            sy1 = round(y1 + 0.08, 3) if source_on_top else y_src_1
            sy2 = y_src_2 if source_on_top else round(y2 - 0.08, 3)
            c.R("locali", sx - 0.14, sy1, sx + 0.14, sy2)
            c.R("m1", sx - 0.14, sy1, sx + 0.14, sy2)
            c.via1(sx, src_cy, pad=0.34)
        else:
            dn = finger_map[i - 1][1]
            dy_t = drain_track_ys[dn]
            sy1 = dy_t - 0.16 if source_on_top else round(y1 + 0.08, 3)
            sy2 = round(y2 - 0.08, 3) if source_on_top else dy_t + 0.16
            c.R("locali", sx - 0.14, min(y1 + 0.08, dy_t), sx + 0.14, max(y2 - 0.08, dy_t))
            c.R("m1", sx - 0.14, sy1, sx + 0.14, sy2)
            c.via1(sx, dy_t, pad=0.34)

        for cy in cut_ys:
            c.sq(cut_layer, sx, cy, 0.17)
            c.sq("viali", sx, cy, 0.17)

    y_min_all = min([y1, y_src_1] + list(gate_track_ys.values()) + list(drain_track_ys.values())) - 0.25
    y_max_all = max([y2, y_src_2] + list(gate_track_ys.values()) + list(drain_track_ys.values())) + 0.25

    return {
        "S": (round((gx_span1 + gx_span2) / 2.0, 3), src_cy),
        "G_map": gate_ports,
        "D_map": drain_ports,
        "span_x": (gx_span1, gx_span2),
        "bbox": (gx_span1, round(y_min_all, 3), gx_span2, round(y_max_all, 3)),
    }


def route_m3_bus(c: LayoutCanvas, pts: list[tuple[float, float]], x_trunk: float):
    """Connect a list of M2 anchor points `(x, y)` onto a shared vertical M3 trunk at `x_trunk` via `via2`."""
    for px, py in pts:
        c.via2(px, py)
        c.R("m3", min(px, x_trunk) - 0.22, py - 0.20, max(px, x_trunk) + 0.22, py + 0.20)
    y_lo = min(p[1] for p in pts)
    y_hi = max(p[1] for p in pts)
    c.R("m3", x_trunk - 0.25, y_lo - 0.22, x_trunk + 0.25, y_hi + 0.22)


# =========================================================================
# CELL 1: `serdes_bg_amp` (2-Stage Bandgap Error Amplifier)
# =========================================================================
def build_serdes_bg_amp() -> LayoutCanvas:
    """
    `.subckt serdes_bg_amp inp inn out vbn vdd vss`
      - Left Active Bay (`x = 2..98`):
          * Bottom P-Well: `Xt` (`w=8, l=4`), `X2` (`w=2, l=2`), Common-Centroid Input Pair `Xa/Xb` (`w=24, l=5`, `A-A-B-B-B-B-A-A`)
          * Top N-Well: 2nd Stage Load `Xp2` (`w=48, l=4`), Common-Centroid Active Load `Xla/Xlb` (`w=48, l=12`, `LA*2-LB*2-LB*2-LA*2`)
      - Right Passive Bay (`x = 100..146`, zero MIM overlay on differential input pair!):
          * `Rz = 20 kOhm` (`2 x res_high_po_1p41 l=40.77` in series, `o1 -> cz`)
          * `Cc = 6 pF` (`2 x 2` / `2 x 3` MIM array: `C1` top plate on M4 = `cz`, `C2` bottom plate on M3 = `out`)
    """
    c = LayoutCanvas("serdes_bg_amp")
    W_CELL, H_CELL = 148.0, 48.0
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.5, 0.5, W_CELL - 0.5, H_CELL - 0.5, kind="p", width=0.60)

    # Left Active Bay: Bottom NMOS Row (`y = 5.0`)
    xt_row = draw_interdigitated_mos_row(
        c, "n", w_finger=4.0, l_gate=4.0, x0=3.0, y0=5.0,
        finger_map=[("vbn", "tail", "vss"), ("vbn", "tail", "vss")],
        lvt=False,
    )
    x2_row = draw_interdigitated_mos_row(
        c, "n", w_finger=2.5, l_gate=2.0, x0=15.0, y0=5.0,
        finger_map=[("o1", "out", "vss"), ("o1", "out", "vss")],
        lvt=False,
    )
    ab_row = draw_interdigitated_mos_row(
        c, "n", w_finger=6.0, l_gate=5.0, x0=23.5, y0=5.0,
        finger_map=[
            ("inn", "da", "tail"), ("inn", "da", "tail"),
            ("inp", "o1", "tail"), ("inp", "o1", "tail"),
            ("inp", "o1", "tail"), ("inp", "o1", "tail"),
            ("inn", "da", "tail"), ("inn", "da", "tail"),
        ],
        lvt=False,
    )

    # Left Active Bay: Top LVT PMOS N-Well (`x = 2.2 .. 98.5, y = 21.5 .. 45.2`)
    draw_guard_ring(c, 2.2, 21.5, 98.5, 45.2, kind="n", width=0.55)
    xp2_row = draw_interdigitated_mos_row(
        c, "p", w_finger=6.0, l_gate=4.0, x0=3.8, y0=26.5,
        finger_map=[("da", "out", "vdd")] * 8, lvt=True,
    )
    lalb_row = draw_interdigitated_mos_row(
        c, "p", w_finger=12.0, l_gate=6.0, x0=44.5, y0=24.5,
        finger_map=[
            ("da", "da", "vdd"), ("da", "da", "vdd"),
            ("da", "o1", "vdd"), ("da", "o1", "vdd"),
            ("da", "o1", "vdd"), ("da", "o1", "vdd"),
            ("da", "da", "vdd"), ("da", "da", "vdd"),
        ],
        lvt=True,
    )

    # Right Passive Bay (`x = 100.5 .. 145.5`): `Rz = 20 kOhm` + Dedicated `Cc = 6 pF` MIM Array
    rz1 = draw_sky130_high_po_res(c, xc=102.0, y_bot=3.5, l_body=36.0, w_res=1.41)
    rz2 = draw_sky130_high_po_res(c, xc=105.5, y_bot=3.5, l_body=36.0, w_res=1.41)
    c.R("m2", 101.5, rz1["R1"][1] - 0.35, 106.0, rz1["R1"][1] + 0.35)

    # 2x2 Array of `17.5 x 18.0 um` MIM Caps (`Cc = 6 pF`, cleanly placed in Right Passive Bay `x = 108.5..144.5`)
    mim_cells = []
    for col in range(2):
        for row in range(2):
            mx = round(108.8 + col * 18.2, 3)
            my = round(4.5 + row * 21.0, 3)
            mc = draw_sky130_mim_cap(c, mx, my, w_cap=15.5, l_cap=18.0)
            mim_cells.append(mc)
            c.R("m4", mc["C1"][0] - 0.35, 4.5, mc["C1"][0] + 0.35, 42.5)
    # Tie `cz` (`rz2.R2`) to MIM top plates (`C1` on M4)
    c.via2(rz2["R2"][0], rz2["R2"][1])
    c.via3(rz2["R2"][0], rz2["R2"][1])
    c.R("m4", rz2["R2"][0] - 0.35, 4.2, 138.0, 4.9)

    # Point-to-point M3 buses for `tail`, `da`, `o1`, `out`:
    route_m3_bus(c, [xt_row["D_map"]["tail"], ab_row["S"]], x_trunk=11.5)
    route_m3_bus(c, [ab_row["D_map"]["da"], lalb_row["D_map"]["da"], lalb_row["G_map"]["da"], xp2_row["G_map"]["da"]], x_trunk=42.0)
    route_m3_bus(c, [ab_row["D_map"]["o1"], lalb_row["D_map"]["o1"], x2_row["G_map"]["o1"], rz1["R2"]], x_trunk=72.0)
    route_m3_bus(c, [x2_row["D_map"]["out"], xp2_row["D_map"]["out"]], x_trunk=18.5)
    # Connect `out` M3 trunk to MIM bottom plates (`C2` on M3)
    c.R("m3", 18.2, 19.2, 142.0, 19.8)

    c.L("inp", ab_row["G_map"]["inp"][0], ab_row["G_map"]["inp"][1], "m2")
    c.L("inn", ab_row["G_map"]["inn"][0], ab_row["G_map"]["inn"][1], "m2")
    c.L("vbn", xt_row["G_map"]["vbn"][0], xt_row["G_map"]["vbn"][1], "m2")
    c.L("out", 18.5, 19.5, "m3")
    c.L("da", 42.0, 20.0, "m3")
    c.L("o1", 72.0, 20.0, "m3")
    c.L("cz", mim_cells[2]["C1"][0], mim_cells[2]["C1"][1], "m4")
    c.L("vdd", 50.0, 44.9, "m2")
    c.L("vss", 50.0, 0.8, "m2")
    return c


# =========================================================================
# CELL 2: `serdes_bg_ota` (Single-Stage V->I Error OTA)
# =========================================================================
def build_serdes_bg_ota() -> LayoutCanvas:
    c = LayoutCanvas("serdes_bg_ota")
    W_CELL, H_CELL = 66.0, 44.0
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.5, 0.5, W_CELL - 0.5, H_CELL - 0.5, kind="p", width=0.60)

    xt_row = draw_interdigitated_mos_row(
        c, "n", w_finger=2.0, l_gate=8.0, x0=3.0, y0=4.5,
        finger_map=[("vbn", "tail", "vss")], lvt=False,
    )
    ab_row = draw_interdigitated_mos_row(
        c, "n", w_finger=6.0, l_gate=5.0, x0=15.0, y0=4.5,
        finger_map=[
            ("inp", "da", "tail"), ("inp", "da", "tail"),
            ("inn", "out", "tail"), ("inn", "out", "tail"),
            ("inn", "out", "tail"), ("inn", "out", "tail"),
            ("inp", "da", "tail"), ("inp", "da", "tail"),
        ],
        lvt=False,
    )

    draw_guard_ring(c, 2.2, 19.5, W_CELL - 2.2, H_CELL - 2.2, kind="n", width=0.55)
    lalb_row = draw_interdigitated_mos_row(
        c, "p", w_finger=11.5, l_gate=5.5, x0=13.0, y0=22.5,
        finger_map=[
            ("da", "da", "vdd"), ("da", "da", "vdd"),
            ("da", "out", "vdd"), ("da", "out", "vdd"),
            ("da", "out", "vdd"), ("da", "out", "vdd"),
            ("da", "da", "vdd"), ("da", "da", "vdd"),
        ],
        lvt=True,
    )

    route_m3_bus(c, [xt_row["D_map"]["tail"], ab_row["S"]], x_trunk=12.0)
    route_m3_bus(c, [ab_row["D_map"]["da"], lalb_row["D_map"]["da"], lalb_row["G_map"]["da"]], x_trunk=28.0)
    route_m3_bus(c, [ab_row["D_map"]["out"], lalb_row["D_map"]["out"]], x_trunk=46.0)

    c.L("inp", ab_row["G_map"]["inp"][0], ab_row["G_map"]["inp"][1], "m2")
    c.L("inn", ab_row["G_map"]["inn"][0], ab_row["G_map"]["inn"][1], "m2")
    c.L("vbn", xt_row["G_map"]["vbn"][0], xt_row["G_map"]["vbn"][1], "m2")
    c.L("out", 46.0, 18.0, "m3")
    c.L("da", 28.0, 18.0, "m3")
    c.L("tail", ab_row["S"][0], ab_row["S"][1], "m2")
    c.L("vdd", 33.0, H_CELL - 2.5, "m2")
    c.L("vss", 33.0, 0.8, "m2")
    return c


# =========================================================================
# CELL 3 & 4: `serdes_bandgap` & `serdes_bias_ref`
# =========================================================================
def build_serdes_bandgap_full(cell_name: str = "serdes_bandgap", with_cvbg: bool = False) -> LayoutCanvas:
    c = LayoutCanvas(cell_name)
    W_BG, H_BG = 176.0, 58.0
    c.R("pwell", 0.0, 0.0, W_BG, H_BG)
    draw_guard_ring(c, 0.5, 0.5, W_BG - 0.5, H_BG - 0.5, kind="p", width=0.65)

    # =====================================================================
    # ZONE 1: Vertically Centered 4x3 Common-Centroid PNP BJT Matrix (`x = 2.2 .. 35.2, y = 2.2 .. 55.8`)
    #   - Rows 0..2: 3x3 Common-Centroid PTAT Matrix (`Q1` at center `(1,1)` -> `a`; 8 outer `Q2` -> `c`)
    #   - Row 3: `Q_dum_L` + `Q3` (center -> `d`) + `Q_dum_R`
    # =====================================================================
    draw_guard_ring(c, 2.2, 2.2, 35.2, 55.8, kind="p", width=0.55)
    pnp_pitch_x, pnp_pitch_y = 9.80, 11.20
    q2_emitters = []
    q1_emit = (0.0, 0.0)
    for r in range(3):
        for col in range(3):
            px = round(4.0 + col * pnp_pitch_x, 3)
            py = round(5.2 + r * pnp_pitch_y, 3)
            lbl = "a" if (r == 1 and col == 1) else None
            pcell = draw_sky130_pnp_3p4(c, px, py, emit_label=lbl)
            if r == 1 and col == 1:
                q1_emit = pcell["E"]
            else:
                q2_emitters.append(pcell["E"])

    e_x0, e_x2 = q2_emitters[0][0], q2_emitters[-1][0]
    e_y0, e_y2 = q2_emitters[0][1], q2_emitters[-1][1]
    c.R("m2", e_x0 - 0.35, e_y0 - 0.35, e_x2 + 0.35, e_y0 + 0.35)
    c.R("m2", e_x0 - 0.35, e_y2 - 0.35, e_x2 + 0.35, e_y2 + 0.35)
    c.R("m2", e_x0 - 0.35, e_y0 - 0.35, e_x0 + 0.35, e_y2 + 0.35)
    c.R("m2", e_x2 - 0.35, e_y0 - 0.35, e_x2 + 0.35, e_y2 + 0.35)
    c.L("c", e_x2, e_y2, "m2")

    q_dum_l = draw_sky130_pnp_3p4(c, 4.0, round(5.2 + 3 * pnp_pitch_y, 3), emit_label=None)
    q3_cell = draw_sky130_pnp_3p4(c, round(4.0 + pnp_pitch_x, 3), round(5.2 + 3 * pnp_pitch_y, 3), emit_label="d")
    q_dum_r = draw_sky130_pnp_3p4(c, round(4.0 + 2 * pnp_pitch_x, 3), round(5.2 + 3 * pnp_pitch_y, 3), emit_label=None)
    for dm in (q_dum_l, q_dum_r):
        c.R("m2", dm["E"][0] - 0.25, dm["C"][1], dm["E"][0] + 0.25, dm["E"][1])

    # =====================================================================
    # ZONE 2: Center Matched Mirrors (`Xm1..Xm5`, `Xmv/Xo0..3`) & Amplifiers (`x = 36.8 .. 118.8`)
    # =====================================================================
    # 2A. Top Quiet N-Well (`x = 36.8 .. 118.8, y = 30.0 .. 55.8`)
    draw_guard_ring(c, 36.8, 30.0, 118.8, 55.8, kind="n", width=0.55)

    core_pmos_fmap = [
        ("vg", "nb", "vdd"), ("vg", "nb", "vdd"),
        ("vg", "ta", "vdd"), ("vg", "ta", "vdd"),
        ("vg", "tb", "vdd"), ("vg", "tb", "vdd"),
        ("vg", "vbg", "vdd"), ("vg", "vbg", "vdd"),
        ("vg", "nb2", "vdd"), ("vg", "nb2", "vdd"),
        ("vg", "nb2", "vdd"), ("vg", "nb2", "vdd"),
        ("vg", "vbg", "vdd"), ("vg", "vbg", "vdd"),
        ("vg", "tb", "vdd"), ("vg", "tb", "vdd"),
        ("vg", "ta", "vdd"), ("vg", "ta", "vdd"),
        ("vg", "nb", "vdd"), ("vg", "nb", "vdd"),
    ]
    core_pmos = draw_interdigitated_mos_row(
        c, "p", w_finger=6.0, l_gate=2.0, x0=38.8, y0=45.0,
        finger_map=core_pmos_fmap, lvt=True,
    )

    amp_pmos_fmap = [
        ("da1", "da1", "vdd"), ("da1", "o1", "vdd"), ("da1", "o1", "vdd"), ("da1", "da1", "vdd"),
        ("da1", "vg", "vdd"), ("da1", "vg", "vdd"),
        ("da2", "da2", "vdd"), ("da2", "vgi", "vdd"), ("da2", "vgi", "vdd"), ("da2", "da2", "vdd"),
    ]
    amp_pmos = draw_interdigitated_mos_row(
        c, "p", w_finger=6.0, l_gate=1.5, x0=93.0, y0=45.0,
        finger_map=amp_pmos_fmap, lvt=True,
    )

    vi_pmos_fmap = [
        ("vgi", "iout0", "vdd"), ("vgi", "iout0", "vdd"),
        ("vgi", "iout1", "vdd"), ("vgi", "iout1", "vdd"),
        ("vgi", "s", "vdd"),     ("vgi", "s", "vdd"),
        ("vgi", "iout2", "vdd"), ("vgi", "iout2", "vdd"),
        ("vgi", "iout3", "vdd"), ("vgi", "iout3", "vdd"),
        ("vgi", "iout3", "vdd"), ("vgi", "iout3", "vdd"),
        ("vgi", "iout2", "vdd"), ("vgi", "iout2", "vdd"),
        ("vgi", "s", "vdd"),     ("vgi", "s", "vdd"),
        ("vgi", "iout1", "vdd"), ("vgi", "iout1", "vdd"),
        ("vgi", "iout0", "vdd"), ("vgi", "iout0", "vdd"),
    ]
    vi_pmos = draw_interdigitated_mos_row(
        c, "p", w_finger=6.0, l_gate=1.8, x0=38.8, y0=33.2,
        finger_map=vi_pmos_fmap, lvt=True,
    )
    xsp_mos = draw_interdigitated_mos_row(
        c, "p", w_finger=2.5, l_gate=4.5, x0=94.0, y0=33.8,
        finger_map=[("vss", "st", "vdd"), ("vss", "st", "vdd")], lvt=False,
    )

    # 2B. Bottom Isolated P-Well (`x = 36.8 .. 118.8, y = 2.2 .. 28.8`)
    draw_guard_ring(c, 36.8, 2.2, 118.8, 28.8, kind="p", width=0.55)

    amp1_in = draw_interdigitated_mos_row(
        c, "n", w_finger=6.0, l_gate=2.2, x0=38.8, y0=17.5,
        finger_map=[
            ("ta", "da1", "tail1"), ("tb", "o1", "tail1"),
            ("tb", "o1", "tail1"),  ("ta", "da1", "tail1"),
        ],
        lvt=False,
    )
    amp2_in = draw_interdigitated_mos_row(
        c, "n", w_finger=6.0, l_gate=2.2, x0=54.5, y0=17.5,
        finger_map=[
            ("s", "da2", "tail2"),   ("vbg", "vgi", "tail2"),
            ("vbg", "vgi", "tail2"), ("s", "da2", "tail2"),
        ],
        lvt=False,
    )
    # Split `bias_aux` into two 4-finger groups (`diodes_tails` and `startup_slew`) so each has only <= 3 gate/drain tracks!
    diodes_tails = draw_interdigitated_mos_row(
        c, "n", w_finger=4.5, l_gate=2.0, x0=70.5, y0=17.8,
        finger_map=[
            ("nb", "nb", "vss"),   ("nb", "tail1", "vss"),
            ("nb2", "nb2", "vss"), ("nb2", "tail2", "vss"),
        ],
        lvt=False,
    )
    startup_slew = draw_interdigitated_mos_row(
        c, "n", w_finger=4.5, l_gate=2.0, x0=92.5, y0=17.8,
        finger_map=[
            ("o1", "vg", "vss"), ("nb", "st", "vss"),
            ("st", "vg", "vss"), ("vbg", "vgi", "s"),
        ],
        lvt=False,
    )

    trim_switches = {}
    trim_defs = [
        ("Xs4", "g4", "rt5", "rt4", 39.0),
        ("Xs3", "g3", "rt4", "rt3", 55.0),
        ("Xs2", "g2", "rt3", "rt2", 71.0),
        ("Xs1", "g1", "rt2", "rt1", 87.0),
        ("Xs0", "g0", "rt1", "vss", 103.0),
    ]
    for sw_nm, g_net, d_net, s_net, sx0 in trim_defs:
        trim_switches[sw_nm] = draw_interdigitated_mos_row(
            c, "n", w_finger=5.0, l_gate=0.35, x0=sx0, y0=4.8,
            finger_map=[(g_net, d_net, s_net)] * 4,
            lvt=False,
        )

    # =====================================================================
    # ZONE 3: Right Common-Centroid Unit-Matched High-Poly Resistor Array
    #         + Shielded Top-Layer MIM Capacitor Bank (`x = 120.2 .. 174.5`)
    # =====================================================================
    draw_guard_ring(c, 120.2, 2.2, 174.5, 55.8, kind="p", width=0.55)

    res_strips = []
    x_res0 = 122.8
    pitch_r = 2.75
    for idx in range(18):
        rx = round(x_res0 + idx * pitch_r, 3)
        is_dum = (idx in (0, 17))
        r_info = draw_sky130_high_po_res(c, xc=rx, y_bot=4.5, l_body=45.0, w_res=1.41, dummy=is_dum)
        res_strips.append(r_info)
        if idx in (1, 3, 5, 8, 10, 12, 14):
            nx = round(x_res0 + (idx + 1) * pitch_r, 3)
            jy = r_info["R1"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)
        elif idx in (6, 13, 15):
            nx = round(x_res0 + (idx + 1) * pitch_r, 3)
            jy = r_info["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)

    # Explicit Point-to-Point M3 Interconnect Buses + Via2 Drops across Zones 1, 2, 3:
    # 1. `a` (`Q1.E` -> `Xrsa` strip 1 R2)
    c.via2(q1_emit[0], q1_emit[1])
    c.via2(res_strips[1]["R2"][0], res_strips[1]["R2"][1])
    c.R("m3", q1_emit[0], q1_emit[1] - 0.22, res_strips[1]["R2"][0], q1_emit[1] + 0.22)
    c.R("m3", res_strips[1]["R2"][0] - 0.22, res_strips[1]["R2"][1], res_strips[1]["R2"][0] + 0.22, q1_emit[1] + 0.22)

    # 2. `c` (`Q2` ring -> `Xr1` strip 7 R2)
    c.via2(e_x2, e_y2)
    c.via2(res_strips[7]["R2"][0], res_strips[7]["R2"][1])
    c.R("m3", e_x2, e_y2 - 0.22, res_strips[7]["R2"][0], e_y2 + 0.22)
    c.R("m3", res_strips[7]["R2"][0] - 0.22, res_strips[7]["R2"][1], res_strips[7]["R2"][0] + 0.22, e_y2 + 0.22)

    # 3. `d` (`Q3.E` -> `Xr2` strip 5 R2)
    c.via2(q3_cell["E"][0], q3_cell["E"][1])
    c.via2(res_strips[5]["R2"][0], res_strips[5]["R2"][1])
    c.R("m3", q3_cell["E"][0], q3_cell["E"][1] - 0.22, res_strips[5]["R2"][0], q3_cell["E"][1] + 0.22)
    c.R("m3", res_strips[5]["R2"][0] - 0.22, res_strips[5]["R2"][1], res_strips[5]["R2"][0] + 0.22, q3_cell["E"][1] + 0.22)

    # 4. `ta`, `tb`, `vbg`, `s`, `rt5..rt1` horizontal M3 trunks + vertical risers with Via2
    route_m3_bus(c, [core_pmos["D_map"]["ta"], amp1_in["G_map"]["ta"], res_strips[2]["R2"]], x_trunk=44.0)
    route_m3_bus(c, [core_pmos["D_map"]["tb"], amp1_in["G_map"]["tb"], res_strips[4]["R2"]], x_trunk=49.5)
    route_m3_bus(c, [core_pmos["D_map"]["vbg"], amp2_in["G_map"]["vbg"], res_strips[9]["R1"]], x_trunk=60.5)
    route_m3_bus(c, [vi_pmos["D_map"]["s"], amp2_in["G_map"]["s"], res_strips[12]["R2"]], x_trunk=66.0)
    route_m3_bus(c, [core_pmos["D_map"]["nb"], diodes_tails["D_map"]["nb"], diodes_tails["G_map"]["nb"]], x_trunk=75.0)
    route_m3_bus(c, [core_pmos["D_map"]["nb2"], diodes_tails["D_map"]["nb2"], diodes_tails["G_map"]["nb2"]], x_trunk=84.0)
    route_m3_bus(c, [amp_pmos["D_map"]["vg"], core_pmos["G_map"]["vg"], startup_slew["D_map"]["vg"]], x_trunk=98.0)
    route_m3_bus(c, [amp_pmos["D_map"]["vgi"], vi_pmos["G_map"]["vgi"], startup_slew["D_map"]["vgi"]], x_trunk=108.0)

    # Connect `rt5..rt1` trim switches to `res_strips[12..16]`
    for idx_t, (sw_nm, g_net, d_net, s_net, sx0) in enumerate(trim_defs):
        sw_d = trim_switches[sw_nm]["D_map"][d_net]
        r_pt = res_strips[12 + idx_t]["R2"]
        c.via2(sw_d[0], sw_d[1])
        c.via2(r_pt[0], r_pt[1])
        y_tr = round(11.6 + idx_t * 0.55, 3)
        c.R("m3", sw_d[0] - 0.20, min(sw_d[1], y_tr), sw_d[0] + 0.20, max(sw_d[1], y_tr))
        c.R("m3", sw_d[0], y_tr - 0.18, r_pt[0], y_tr + 0.18)
        c.R("m3", r_pt[0] - 0.20, min(r_pt[1], y_tr), r_pt[0] + 0.20, max(r_pt[1], y_tr))

    # Shielded Top-Layer MIM Capacitor Bank (`M3 + mimcap + M4`) over Zone 3 (`x = 122.5 .. 171.5`)
    mim_cc = draw_sky130_mim_cap(c, 122.5, 30.5, w_cap=21.5, l_cap=21.5)
    mim_cvgi = draw_sky130_mim_cap(c, 122.5, 5.5, w_cap=21.5, l_cap=21.5)
    mim_cvbg = draw_sky130_mim_cap(c, 148.0, 30.5, w_cap=21.5, l_cap=21.5)
    mim_cvgi2 = draw_sky130_mim_cap(c, 148.0, 5.5, w_cap=21.5, l_cap=21.5)

    # Labels (non-overlapping coordinates)
    c.L("vbg", 60.5, 41.5, "m3")
    c.L("vg", core_pmos["G_map"]["vg"][0], core_pmos["G_map"]["vg"][1], "m2")
    c.L("vgi", vi_pmos["G_map"]["vgi"][0], vi_pmos["G_map"]["vgi"][1], "m2")
    c.L("iout0", vi_pmos["D_map"]["iout0"][0] - 18.0, vi_pmos["D_map"]["iout0"][1], "m2")
    c.L("iout1", vi_pmos["D_map"]["iout1"][0] - 6.0, vi_pmos["D_map"]["iout1"][1], "m2")
    c.L("iout2", vi_pmos["D_map"]["iout2"][0] + 6.0, vi_pmos["D_map"]["iout2"][1], "m2")
    c.L("iout3", vi_pmos["D_map"]["iout3"][0] + 18.0, vi_pmos["D_map"]["iout3"][1], "m2")
    for sw_nm, g_net, d_net, s_net, sx0 in trim_defs:
        gx, gy = trim_switches[sw_nm]["G_map"][g_net]
        c.L(g_net, gx, gy, "m2")
    c.L("ta", 44.0, 41.5, "m3")
    c.L("tb", 49.5, 41.5, "m3")
    c.L("s", 66.0, 31.0, "m3")
    c.L("Cc_6pF", mim_cc["C1"][0] - 3.0, mim_cc["C1"][1], "m4")
    c.L("Cvgi", mim_cvgi["C1"][0] - 2.0, mim_cvgi["C1"][1], "m4")
    if with_cvbg:
        c.L("Cvbg_5pF", mim_cvbg["C1"][0] - 3.0, mim_cvbg["C1"][1], "m4")
    c.L("vdd", 78.0, 55.4, "m2")
    c.L("vss", 78.0, 0.85, "m2")
    return c


# =========================================================================
# CELL 5: `serdes_ref_vbuf` (RX Termination Common-Mode Reference Buffer)
# =========================================================================
def build_serdes_ref_vbuf() -> LayoutCanvas:
    c = LayoutCanvas("serdes_ref_vbuf")
    W_CELL, H_CELL = 92.0, 44.0
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.5, 0.5, W_CELL - 0.5, H_CELL - 0.5, kind="p", width=0.60)

    bdt_row = draw_interdigitated_mos_row(
        c, "n", w_finger=4.0, l_gate=4.0, x0=3.0, y0=4.5,
        finger_map=[("ibias", "ibias", "vss"), ("ibias", "tail", "vss")],
        lvt=False,
    )
    ab_row = draw_interdigitated_mos_row(
        c, "n", w_finger=6.0, l_gate=5.0, x0=16.5, y0=4.5,
        finger_map=[
            ("iin", "da", "tail"),  ("iin", "da", "tail"),
            ("out", "out", "tail"), ("out", "out", "tail"),
            ("out", "out", "tail"), ("out", "out", "tail"),
            ("iin", "da", "tail"),  ("iin", "da", "tail"),
        ],
        lvt=False,
    )

    draw_guard_ring(c, 2.2, 19.5, 63.5, H_CELL - 2.2, kind="n", width=0.55)
    lalb_row = draw_interdigitated_mos_row(
        c, "p", w_finger=11.5, l_gate=5.5, x0=14.5, y0=22.5,
        finger_map=[
            ("da", "da", "vdd"),  ("da", "da", "vdd"),
            ("da", "out", "vdd"), ("da", "out", "vdd"),
            ("da", "out", "vdd"), ("da", "out", "vdd"),
            ("da", "da", "vdd"),  ("da", "da", "vdd"),
        ],
        lvt=True,
    )

    r_strips = []
    for i in range(8):
        rx = round(66.5 + i * 2.80, 3)
        rs = draw_sky130_high_po_res(c, xc=rx, y_bot=3.5, l_body=32.5, w_res=1.41)
        r_strips.append(rs)
        if i < 7:
            nx = round(66.5 + (i + 1) * 2.80, 3)
            jy = rs["R1"][1] if (i % 2 == 0) else rs["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)

    route_m3_bus(c, [bdt_row["D_map"]["tail"], ab_row["S"]], x_trunk=13.5)
    route_m3_bus(c, [ab_row["G_map"]["iin"], r_strips[0]["R2"]], x_trunk=64.8)
    route_m3_bus(c, [ab_row["D_map"]["da"], lalb_row["D_map"]["da"], lalb_row["G_map"]["da"]], x_trunk=29.5)
    route_m3_bus(c, [ab_row["D_map"]["out"], lalb_row["D_map"]["out"], ab_row["G_map"]["out"]], x_trunk=47.5)

    c.L("iin", r_strips[0]["R2"][0], r_strips[0]["R2"][1], "m2")
    c.L("ibias", bdt_row["G_map"]["ibias"][0], bdt_row["G_map"]["ibias"][1], "m2")
    c.L("out", 47.5, 18.0, "m3")
    c.L("da", 29.5, 18.0, "m3")
    c.L("vdd", 32.0, H_CELL - 2.5, "m2")
    c.L("vss", 32.0, 0.8, "m2")
    return c


# =========================================================================
# CELL 6: `serdes_ref_pbuf` (Loop Filter 16:1 Precharge DAC + Buffer)
# =========================================================================
def build_serdes_ref_pbuf() -> LayoutCanvas:
    c = LayoutCanvas("serdes_ref_pbuf")
    W_CELL, H_CELL = 144.0, 46.0
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.5, 0.5, W_CELL - 0.5, H_CELL - 0.5, kind="p", width=0.60)

    # Zone 1 (`x = 3.0 .. 44.5`): `Xr0` (6 strips = 95k) + `Xr1..Xr15` (15 tap strips = 15 x 2.667k, fully series-jumpered!)
    for i in range(6):
        rx = round(4.2 + i * 2.75, 3)
        rs = draw_sky130_high_po_res(c, xc=rx, y_bot=4.0, l_body=34.0, w_res=1.41)
        if i < 5:
            nx = round(4.2 + (i + 1) * 2.75, 3)
            jy = rs["R1"][1] if (i % 2 == 0) else rs["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)

    bot_taps, top_taps = [], []
    for k in range(8):
        rx = round(22.0 + k * 2.75, 3)
        rb = draw_sky130_high_po_res(c, xc=rx, y_bot=4.0, l_body=13.0, w_res=1.41)
        bot_taps.append(rb)
        if k < 7:
            nx = round(22.0 + (k + 1) * 2.75, 3)
            jy = rb["R1"][1] if (k % 2 == 0) else rb["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)
        rt = draw_sky130_high_po_res(c, xc=rx, y_bot=24.5, l_body=13.0, w_res=1.41)
        top_taps.append(rt)
        if k < 7:
            nx = round(22.0 + (k + 1) * 2.75, 3)
            jy = rt["R1"][1] if (k % 2 == 0) else rt["R2"][1]
            c.R("m2", rx - 0.45, jy - 0.35, nx + 0.45, jy + 0.35)
    # Bridge `Xr0` output to `bot_taps[0]` and `bot_taps[-1]` up to `top_taps[-1]`
    c.R("m2", 17.95, 4.5, 22.45, 5.2)
    c.R("m2", 40.95, bot_taps[-1]["R2"][1], 41.55, top_taps[-1]["R2"][1])

    # Zone 2 (`x = 46.5 .. 86.5`):
    #   - Left Bank (`x = 48.0..65.0`): 16x CMOS Inverter (`Xi0..15`, NMOS bottom + PMOS top)
    #   - Right Bank (`x = 67.5..84.5`): 16x CMOS Transmission Gate Mux (`Xg0..15`, NMOS bottom + PMOS top)
    draw_guard_ring(c, 46.5, 23.5, 86.5, H_CELL - 2.2, kind="n", width=0.50)
    inv_n_row = draw_interdigitated_mos_row(
        c, "n", w_finger=5.0, l_gate=0.45, x0=48.0, y0=5.5,
        finger_map=[("s_in", "sb_out", "vss")] * 16, lvt=False,
    )
    inv_p_row = draw_interdigitated_mos_row(
        c, "p", w_finger=7.0, l_gate=0.45, x0=48.0, y0=26.5,
        finger_map=[("s_in", "sb_out", "vdd")] * 16, lvt=False,
    )
    mux_n_row = draw_interdigitated_mos_row(
        c, "n", w_finger=5.0, l_gate=0.45, x0=67.5, y0=5.5,
        finger_map=[("s_mux", "tap", "t_tap")] * 16, lvt=False,
    )
    mux_p_row = draw_interdigitated_mos_row(
        c, "p", w_finger=7.0, l_gate=0.45, x0=67.5, y0=26.5,
        finger_map=[("sb_out", "tap", "t_tap")] * 16, lvt=False,
    )
    # Horizontal M3 tap bus bundle carrying the ladder taps from Zone 1 into the 16:1 TG Mux in Zone 2
    for tidx in range(8):
        ty = round(14.0 + tidx * 1.15, 3)
        c.R("m3", 22.0, ty - 0.18, 83.5, ty + 0.18)
    route_m3_bus(c, [inv_n_row["D_map"]["sb_out"], inv_p_row["D_map"]["sb_out"], mux_p_row["G_map"]["sb_out"]], x_trunk=65.8)
    route_m3_bus(c, [mux_n_row["D_map"]["tap"], mux_p_row["D_map"]["tap"]], x_trunk=85.2)

    # Zone 3 (`x = 88.5 .. 141.8`): High-Slew 300 uA Switched LVT Follower (`Xt`, `Xst`, `Xa/Xb` LVT, `Xla/Xlb` LVT)
    draw_guard_ring(c, 88.5, 22.5, 141.8, H_CELL - 2.2, kind="n", width=0.55)
    tail_sw = draw_interdigitated_mos_row(
        c, "n", w_finger=5.5, l_gate=0.80, x0=90.0, y0=5.8,
        finger_map=[("ibias", "tail", "ts")] * 6 + [("en", "ts", "vss")] * 6,
        lvt=False,
    )
    ab_lvt = draw_interdigitated_mos_row(
        c, "n", w_finger=6.0, l_gate=1.00, x0=114.0, y0=5.8,
        finger_map=[
            ("tap", "da", "tail"),  ("tap", "da", "tail"),
            ("out", "out", "tail"), ("out", "out", "tail"),
            ("out", "out", "tail"), ("out", "out", "tail"),
            ("tap", "da", "tail"),  ("tap", "da", "tail"),
        ],
        lvt=True,
    )
    lalb_lvt = draw_interdigitated_mos_row(
        c, "p", w_finger=11.0, l_gate=1.20, x0=92.0, y0=25.5,
        finger_map=[
            ("da", "da", "vdd"),  ("da", "da", "vdd"),
            ("da", "out", "vdd"), ("da", "out", "vdd"),
            ("da", "out", "vdd"), ("da", "out", "vdd"),
            ("da", "da", "vdd"),  ("da", "da", "vdd"),
        ] * 2,
        lvt=True,
    )

    route_m3_bus(c, [mux_n_row["D_map"]["tap"], mux_p_row["D_map"]["tap"], ab_lvt["G_map"]["tap"]], x_trunk=85.2)
    route_m3_bus(c, [tail_sw["D_map"]["tail"], ab_lvt["S"]], x_trunk=112.2)
    route_m3_bus(c, [ab_lvt["D_map"]["da"], lalb_lvt["D_map"]["da"], lalb_lvt["G_map"]["da"]], x_trunk=118.5)
    route_m3_bus(c, [ab_lvt["G_map"]["out"], ab_lvt["D_map"]["out"], lalb_lvt["D_map"]["out"]], x_trunk=129.5)

    c.L("iin", 22.0, 40.5, "m2")
    c.L("ibias", tail_sw["G_map"]["ibias"][0] - 5.0, tail_sw["G_map"]["ibias"][1], "m2")
    c.L("en", tail_sw["G_map"]["en"][0] + 5.0, tail_sw["G_map"]["en"][1], "m2")
    c.L("tap", 85.2, 20.0, "m3")
    c.L("out", 129.5, 20.0, "m3")
    c.L("vdd", 115.0, H_CELL - 2.5, "m2")
    c.L("vss", 115.0, 0.8, "m2")
    return c


# =========================================================================
# CELLS 7..12: Local Bias Distribution & Module Diode Cells (`bias_dist.spice`)
# =========================================================================
def build_serdes_bias_pcopy(n_fingers: int = 4, cell_name: str = "serdes_bias_pcopy") -> LayoutCanvas:
    c = LayoutCanvas(cell_name)
    if n_fingers <= 4:
        n_rows, nf_row, l_draw = 1, n_fingers, 4.0
    elif n_fingers <= 20:
        n_rows, nf_row, l_draw = 2, 10, 2.2
    else:
        n_rows, nf_row, l_draw = 5, 17, 1.8

    row_pitch = 10.5
    w_est = round(5.5 + nf_row * (l_draw + 0.52) + 2.5, 3)
    h_est = round(4.0 + n_rows * row_pitch, 3)
    c.R("pwell", 0.0, 0.0, w_est, h_est)
    draw_guard_ring(c, 0.5, 0.5, w_est - 0.5, h_est - 0.5, kind="n", width=0.55)

    out_pts, vgi_pts = [], []
    for r in range(n_rows):
        ry = round(2.8 + r * row_pitch, 3)
        row_info = draw_interdigitated_mos_row(
            c, "p", w_finger=6.0, l_gate=l_draw, x0=2.5, y0=ry,
            finger_map=[("vgi", "out", "vdd")] * nf_row, lvt=True,
        )
        out_pts.append(row_info["D_map"]["out"])
        vgi_pts.append(row_info["G_map"]["vgi"])

    ox = round(w_est * 0.35, 3)
    gx = round(w_est * 0.65, 3)
    route_m3_bus(c, out_pts, x_trunk=ox)
    route_m3_bus(c, vgi_pts, x_trunk=gx)

    c.L("out", ox, out_pts[0][1], "m3")
    c.L("vgi", gx, vgi_pts[-1][1], "m3")
    c.L("vdd", round(w_est / 2.0, 3), round(h_est - 0.8, 3), "m2")
    return c


def build_serdes_bias_cml() -> LayoutCanvas:
    c = LayoutCanvas("serdes_bias_cml")
    W_CELL, H_CELL = 32.0, 28.0
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.5, 0.5, W_CELL - 0.5, H_CELL - 0.5, kind="p", width=0.55)

    xd = draw_interdigitated_mos_row(
        c, "n", w_finger=5.0, l_gate=0.50, x0=3.0, y0=4.0,
        finger_map=[("iin", "iin", "vss"), ("iin", "iin", "vss")],
        lvt=False,
    )
    gx, gy = xd["G_map"]["iin"]
    dx, dy = xd["D_map"]["iin"]
    c.via2(gx, gy)
    c.via2(dx, dy)
    c.R("m3", gx - 0.30, min(gy, dy) - 0.22, gx + 0.30, max(gy, dy) + 0.22)

    mim = draw_sky130_mim_cap(c, 3.5, 3.2, w_cap=24.5, l_cap=21.0)
    c.via3(gx, dy)

    c.L("iin", mim["C1"][0], mim["C1"][1], "m4")
    c.L("vss", 16.0, 0.8, "m2")
    return c


def build_serdes_bias_ctle() -> LayoutCanvas:
    c = LayoutCanvas("serdes_bias_ctle")
    W_CELL, H_CELL = 12.0, 9.5
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.4, 0.4, W_CELL - 0.4, H_CELL - 0.4, kind="p", width=0.50)

    xd = draw_interdigitated_mos_row(
        c, "n", w_finger=2.5, l_gate=0.50, x0=2.2, y0=3.2,
        finger_map=[("iin", "iin", "vss")] * 4,
        lvt=True,
    )
    gx, gy = xd["G_map"]["iin"]
    dx, dy = xd["D_map"]["iin"]
    c.via2(gx, gy)
    c.via2(dx, dy)
    c.R("m3", gx - 0.25, min(gy, dy) - 0.20, gx + 0.25, max(gy, dy) + 0.20)

    c.L("iin", gx, dy, "m3")
    c.L("vss", 6.0, 0.65, "m2")
    return c


def build_serdes_bias_cp() -> LayoutCanvas:
    c = LayoutCanvas("serdes_bias_cp")
    W_CELL, H_CELL = 16.5, 22.0
    c.R("pwell", 0.0, 0.0, W_CELL, H_CELL)
    draw_guard_ring(c, 0.4, 0.4, W_CELL - 0.4, 9.8, kind="p", width=0.50)
    draw_guard_ring(c, 0.4, 10.6, W_CELL - 0.4, H_CELL - 0.4, kind="n", width=0.50)

    n_row = draw_interdigitated_mos_row(
        c, "n", w_finger=2.5, l_gate=1.00, x0=2.5, y0=3.2,
        finger_map=[
            ("vbn", "vbn", "vss"), ("vbn", "vbp", "vss"),
            ("vbn", "vbp", "vss"), ("vbn", "vbn", "vss"),
        ],
        lvt=False,
    )
    p_row = draw_interdigitated_mos_row(
        c, "p", w_finger=5.0, l_gate=1.00, x0=2.5, y0=12.8,
        finger_map=[("vbp", "vbp", "vcp")] * 4,
        lvt=False,
    )

    route_m3_bus(c, [n_row["G_map"]["vbn"], n_row["D_map"]["vbn"]], x_trunk=5.8)
    route_m3_bus(c, [n_row["D_map"]["vbp"], p_row["D_map"]["vbp"], p_row["G_map"]["vbp"]], x_trunk=10.8)

    c.L("vbn", 5.8, n_row["D_map"]["vbn"][1], "m3")
    c.L("vbp", 10.8, 11.5, "m3")
    c.L("vcp", 8.2, H_CELL - 0.65, "m2")
    c.L("vss", 8.2, 0.65, "m2")
    return c


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Regenerate Gemini candidates; does not validate them.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    cells = [
        ("serdes_bg_amp",          build_serdes_bg_amp()),
        ("serdes_bg_ota",          build_serdes_bg_ota()),
        ("serdes_bandgap",         build_serdes_bandgap_full("serdes_bandgap", with_cvbg=False)),
        ("serdes_bias_ref",        build_serdes_bandgap_full("serdes_bias_ref", with_cvbg=True)),
        ("serdes_ref_vbuf",        build_serdes_ref_vbuf()),
        ("serdes_ref_pbuf",        build_serdes_ref_pbuf()),
        ("serdes_bias_pcopy",      build_serdes_bias_pcopy(4, "serdes_bias_pcopy")),
        ("serdes_bias_pcopy_n20",  build_serdes_bias_pcopy(20, "serdes_bias_pcopy_n20")),
        ("serdes_bias_pcopy_n85",  build_serdes_bias_pcopy(85, "serdes_bias_pcopy_n85")),
        ("serdes_bias_cml",        build_serdes_bias_cml()),
        ("serdes_bias_ctle",       build_serdes_bias_ctle()),
        ("serdes_bias_cp",         build_serdes_bias_cp()),
    ]

    bias_layout_dir = args.output_dir.resolve()
    bias_layout_dir.mkdir(parents=True, exist_ok=True)

    for name, canvas in cells:
        for d in (bias_layout_dir,):
            canvas.save_mag(d / f"{name}.mag")
            canvas.save_tcl(d / f"{name}.tcl")
        bx1, by1, bx2, by2 = canvas.bbox()
        w, h = round(bx2 - bx1, 2), round(by2 - by1, 2)
        n_rects = sum(len(v) for v in canvas.rects.values())
        n_labels = len(canvas.labels)
        print(f"{name:24s} : {w:6.2f} x {h:6.2f} um = {w*h:8.1f} um^2 | rects={n_rects:4d} | labels={n_labels:2d}")

    fig, axes = plt.subplots(2, 2, figsize=(16.5, 13.5), dpi=160)
    plot_canvas(axes[0, 0], cells[2][1], "1. serdes_bandgap (Full Bandgap + Constant-Swing V->I Core)",
                "Zone 1: 4x3 Common-Centroid PNP + Q3 | Zone 2: 20-Finger CC Mirrors & OTAs | Zone 3: CC Resistors + Shielded MIM", show_cuts=False)
    plot_canvas(axes[0, 1], cells[0][1], "2. serdes_bg_amp (2-Stage Bandgap Error Amplifier)",
                "Left Bay: CC Xa/Xb (w=24, l=5) + Xla/Xlb (w=48, l=12) | Right Passive Bay: Rz (20k) + Cc (6pF)", show_cuts=False)
    plot_canvas(axes[1, 0], cells[4][1], "3. serdes_ref_vbuf (RX Termination Common-Mode Reference Buffer)",
                "Common-Centroid Unity-Gain Follower OTA + 8-Segment Serpentine Xr (105.2 kOhm)", show_cuts=False)
    plot_canvas(axes[1, 1], cells[5][1], "4. serdes_ref_pbuf (PLL Loop Filter 16:1 Precharge DAC + 300uA Follower)",
                "Zone 1: Xr0 (95k) + 15-Tap Ladder | Zone 2: 16x Inv + 16x TG Mux | Zone 3: 300uA Switched LVT Follower", show_cuts=False)
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=True, fontsize=8.5, bbox_to_anchor=(0.5, 0.008))
    plt.tight_layout(rect=[0, 0.045, 1, 1])
    for d in (bias_layout_dir,):
        fig.savefig(d / "bias_layout_suite_overview.png", dpi=160)
    plt.close(fig)



if __name__ == "__main__":
    main()
