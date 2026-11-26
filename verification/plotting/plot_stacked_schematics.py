#!/usr/bin/env python3
"""ISSCC / IEEE JSSC Style Stacked-Page ("页状叠起") Transistor-Level Schematics
for the two signature array circuits of the SKY130A 4 Gb/s NRZ SerDes:

  1. RX 2 GHz 64-Code Pure CMOS Resistor-Linearized PI (`rx_cmos_pi.spice`)
     -> docs/figures/schematics/rx_pi_stacked_slices.{png,svg}
  2. TX Quarter-Rate 4:1 Fused Low-Vdd N-over-N SST Driver + 2-Tap FFE (`tx_sst_driver.spice`)
     -> docs/figures/schematics/tx_sst_stacked_slices.{png,svg}
"""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon, Rectangle
import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "docs/figures/schematics"

# Clean Analog-Canvas / IEEE JSSC light schematic palette
C_BG = "#ffffff"
C_CARD = "#ffffff"
C_CARD_BACK = "#f8fafc"
C_INK = "#0f172a"
C_MUTED = "#475569"
C_WIRE = "#1e3a8a"       # classic schematic navy wire
C_BLUE = "#1d4ed8"
C_BLUE_LT = "#eff6ff"
C_ORANGE = "#c2410c"
C_ORANGE_LT = "#fff7ed"
C_TEAL = "#0f766e"
C_TEAL_LT = "#f0fdfa"
C_PURPLE = "#6d28d9"
C_PURPLE_LT = "#faf5ff"
C_AMBER = "#b45309"
C_AMBER_LT = "#fffbeb"
C_GREEN = "#15803d"
C_GREEN_LT = "#f0fdf4"
C_RED = "#be123c"
C_GRAY = "#64748b"
C_GRAY_LT = "#f1f5f9"


# ---------------------------------------------------------------------------
# Precision Analog-Canvas-Grade Schematic Symbol Primitives
# ---------------------------------------------------------------------------
def wire(ax, pts, color=C_WIRE, lw=1.45, ls="-", z=10):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=lw, ls=ls, solid_capstyle="round", solid_joinstyle="round", zorder=z)


def arrow(ax, p1, p2, color=C_WIRE, lw=1.5, ls="-", z=11, rad=0.0):
    ax.add_patch(FancyArrowPatch(
        p1, p2, arrowstyle="-|>,head_length=5.5,head_width=3.2",
        color=color, lw=lw, ls=ls, connectionstyle=f"arc3,rad={rad}", zorder=z,
    ))


def dot(ax, x, y, color=C_WIRE, r=0.068, z=14):
    ax.add_patch(Circle((x, y), r, facecolor=color, edgecolor="none", zorder=z))


def pin_diamond(ax, x, y, color=C_RED, s=0.11, z=15):
    pts = [(x - s, y), (x, y + s * 0.72), (x + s, y), (x, y - s * 0.72)]
    ax.add_patch(Polygon(pts, closed=True, facecolor=color, edgecolor="#ffffff", lw=0.7, zorder=z))


def gnd(ax, x, y, s=0.20, color=C_INK, lw=1.35, z=12):
    ax.plot([x, x], [y, y - s * 0.55], color=color, lw=lw, zorder=z)
    ax.plot([x - s, x + s], [y - s * 0.55, y - s * 0.55], color=color, lw=lw + 0.25, zorder=z)
    ax.plot([x - s * 0.62, x + s * 0.62], [y - s * 0.90, y - s * 0.90], color=color, lw=lw, zorder=z)
    ax.plot([x - s * 0.28, x + s * 0.28], [y - s * 1.25, y - s * 1.25], color=color, lw=lw, zorder=z)


def vdd_bar(ax, x, y, label="VDD", s=0.24, color=C_INK, lw=1.4, fs=7.5, z=12):
    ax.plot([x, x], [y, y + s * 0.65], color=color, lw=lw, zorder=z)
    ax.plot([x - s * 0.75, x + s * 0.75], [y + s * 0.65, y + s * 0.65], color=color, lw=lw + 0.4, zorder=z)
    if label:
        ax.text(x, y + s * 0.95, label, ha="center", va="bottom", fontsize=fs, fontweight="bold", color=color, zorder=z)


def draw_mos(ax, x, y, *, pmos=False, flip=False, lvt=False, scale=1.0,
             color="#14532d", lw=1.55, z=12):
    """Draw a crisp 3/4-terminal MOSFET symbol centered at (x, y).

    Default (flip=False): gate enters from LEFT at (x - 0.50*s, y);
      top terminal at (x + 0.24*s, y + 0.52*s), bottom terminal at (x + 0.24*s, y - 0.52*s).
    Returns dict of exact terminal coordinates: {'g', 'top', 'bot'}.
    """
    s = scale
    sgn = -1.0 if flip else 1.0
    xg_plate = x - 0.14 * s * sgn
    xch = x - 0.02 * s * sgn
    xsd = x + 0.24 * s * sgn
    xg_in = x - 0.52 * s * sgn

    # Gate lead (+ bubble for PMOS)
    if pmos:
        br = 0.068 * s
        ax.plot([xg_in, xg_plate - 2 * br * sgn], [y, y], color=color, lw=lw, zorder=z)
        ax.add_patch(Circle((xg_plate - br * sgn, y), br, facecolor="#ffffff", edgecolor=color, lw=lw - 0.1, zorder=z + 1))
    else:
        ax.plot([xg_in, xg_plate], [y, y], color=color, lw=lw, zorder=z)

    # Gate plate (double line hint for LVT if requested)
    ax.plot([xg_plate, xg_plate], [y - 0.28 * s, y + 0.28 * s], color=color, lw=lw + 0.2, zorder=z)
    if lvt:
        ax.plot([xg_plate + 0.045 * s * sgn, xg_plate + 0.045 * s * sgn],
                [y - 0.26 * s, y + 0.26 * s], color="#0d9488", lw=0.9, zorder=z)

    # Channel bar + top/bottom leads
    ax.plot([xch, xch], [y - 0.34 * s, y + 0.34 * s], color=color, lw=lw + 0.35, zorder=z)
    ax.plot([xch, xsd, xsd], [y + 0.26 * s, y + 0.26 * s, y + 0.52 * s], color=color, lw=lw, zorder=z)
    ax.plot([xch, xsd, xsd], [y - 0.26 * s, y - 0.26 * s, y - 0.52 * s], color=color, lw=lw, zorder=z)

    # Source arrow (PMOS arrow points inward at top source; NMOS points outward at bottom source)
    if pmos:
        ay = y + 0.26 * s
        ax.add_patch(Polygon(
            [(xch + 0.06 * s * sgn, ay), (xch + 0.16 * s * sgn, ay + 0.06 * s), (xch + 0.16 * s * sgn, ay - 0.06 * s)],
            closed=True, facecolor=color, edgecolor="none", zorder=z + 1,
        ))
    else:
        ay = y - 0.26 * s
        ax.add_patch(Polygon(
            [(xsd - 0.04 * s * sgn, ay), (xsd - 0.15 * s * sgn, ay + 0.06 * s), (xsd - 0.15 * s * sgn, ay - 0.06 * s)],
            closed=True, facecolor=color, edgecolor="none", zorder=z + 1,
        ))

    return {"g": (xg_in, y), "top": (xsd, y + 0.52 * s), "bot": (xsd, y - 0.52 * s)}


def draw_res_h(ax, x1, x2, y, amp=0.14, nzig=5, color="#14532d", lw=1.6, z=12):
    L = x2 - x1
    stub = L * 0.16
    xs = [x1, x1 + stub]
    ys = [y, y]
    body = L - 2 * stub
    for i in range(nzig):
        xs.append(x1 + stub + body * (i + 0.5) / nzig)
        ys.append(y + (amp if i % 2 == 0 else -amp))
    xs += [x2 - stub, x2]
    ys += [y, y]
    ax.plot(xs, ys, color=color, lw=lw, solid_joinstyle="round", zorder=z)


def draw_cap_h(ax, x1, x2, y, h=0.46, gap=0.13, color=C_PURPLE, lw=1.7, z=12):
    xm = 0.5 * (x1 + x2)
    ax.plot([x1, xm - gap / 2], [y, y], color=color, lw=1.45, zorder=z)
    ax.plot([xm + gap / 2, x2], [y, y], color=color, lw=1.45, zorder=z)
    ax.plot([xm - gap / 2, xm - gap / 2], [y - h / 2, y + h / 2], color=color, lw=lw + 0.5, zorder=z)
    ax.plot([xm + gap / 2, xm + gap / 2], [y - h / 2, y + h / 2], color=color, lw=lw + 0.5, zorder=z)


def draw_cap_v(ax, x, y1, y2, w=0.44, gap=0.13, color=C_TEAL, lw=1.7, z=12):
    ym = 0.5 * (y1 + y2)
    ax.plot([x, x], [y1, ym - gap / 2], color=color, lw=1.45, zorder=z)
    ax.plot([x, x], [ym + gap / 2, y2], color=color, lw=1.45, zorder=z)
    ax.plot([x - w / 2, x + w / 2], [ym - gap / 2, ym - gap / 2], color=color, lw=lw + 0.5, zorder=z)
    ax.plot([x - w / 2, x + w / 2], [ym + gap / 2, ym + gap / 2], color=color, lw=lw + 0.5, zorder=z)


def draw_tgate(ax, x, y, w=0.58, h=0.38, top_lbl="f", bot_lbl="fb", ec="#14532d", fc="#dcfce7", fs=6.8, z=12):
    xm = x + w / 2
    ax.add_patch(Polygon([(x, y - h / 2), (x, y + h / 2), (xm, y)], closed=True, facecolor=fc, edgecolor=ec, lw=1.3, zorder=z))
    ax.add_patch(Polygon([(x + w, y - h / 2), (x + w, y + h / 2), (xm, y)], closed=True, facecolor=fc, edgecolor=ec, lw=1.3, zorder=z))
    r = 0.055
    ax.add_patch(Circle((xm, y + h * 0.36), r, facecolor="#ffffff", edgecolor=ec, lw=1.1, zorder=z + 1))
    ax.plot([xm, xm], [y + h * 0.36 + r, y + h * 0.72], color=ec, lw=1.1, zorder=z)
    ax.plot([xm, xm], [y - h * 0.22, y - h * 0.68], color=ec, lw=1.1, zorder=z)
    if top_lbl:
        ax.text(xm, y + h * 0.78, top_lbl, ha="center", va="bottom", fontsize=fs, fontweight="bold", color=ec, zorder=z + 2)
    if bot_lbl:
        ax.text(xm, y - h * 0.76, bot_lbl, ha="center", va="top", fontsize=fs, fontweight="bold", color=ec, zorder=z + 2)
    return x + w


def draw_nand2(ax, x, y, w=0.66, h=0.52, fc="#ffffff", ec=C_INK, lw=1.45, z=12):
    # Classic D-shaped NAND2 body + bubble
    r_arc = h / 2
    x_body = x + w - r_arc
    th = np.linspace(-np.pi / 2, np.pi / 2, 24)
    pts = [(x, y - r_arc), (x_body, y - r_arc)]
    pts += [(x_body + r_arc * np.cos(a), y + r_arc * np.sin(a)) for a in th]
    pts += [(x, y + r_arc)]
    ax.add_patch(Polygon(pts, closed=True, facecolor=fc, edgecolor=ec, lw=lw, zorder=z))
    rb = 0.068
    ax.add_patch(Circle((x + w + rb, y), rb, facecolor="#ffffff", edgecolor=ec, lw=lw, zorder=z + 1))
    return {"in1": (x, y + h * 0.24), "in2": (x, y - h * 0.24), "out": (x + w + 2 * rb, y)}


def draw_inv(ax, x, y, w=0.56, h=0.50, fc="#ffffff", ec=C_INK, lw=1.45, z=12):
    ax.add_patch(Polygon([(x, y - h / 2), (x, y + h / 2), (x + w, y)], closed=True, facecolor=fc, edgecolor=ec, lw=lw, zorder=z))
    rb = 0.065
    ax.add_patch(Circle((x + w + rb, y), rb, facecolor="#ffffff", edgecolor=ec, lw=lw, zorder=z + 1))
    return {"in": (x, y), "out": (x + w + 2 * rb, y)}


def draw_card(ax, x, y, w, h, fc=C_CARD, ec=C_TEAL, lw=1.5, r=0.18, z=5, shadow=False):
    if shadow:
        ax.add_patch(FancyBboxPatch(
            (x + 0.08, y - 0.08), w, h, boxstyle=f"round,pad=0.0,rounding_size={r}",
            facecolor="#cbd5e1", edgecolor="none", alpha=0.45, zorder=z - 1,
        ))
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0.0,rounding_size={r}",
        facecolor=fc, edgecolor=ec, lw=lw, zorder=z,
    ))


# ===========================================================================
# FIGURE 1: RX PI STACKED-PAGE TRANSISTOR SCHEMATIC (rx_cmos_pi.spice)
# ===========================================================================
def build_rx_pi_stacked():
    fig, ax = plt.subplots(figsize=(17.6, 9.6), dpi=240, facecolor=C_BG)
    ax.set_xlim(0.0, 18.2)
    ax.set_ylim(-0.35, 9.95)
    ax.set_aspect("equal")
    ax.axis("off")

    # Title banner
    ax.text(0.30, 9.62, "RX 2 GHz 64-Code Pure CMOS Resistor-Linearized Phase Interpolator — Stacked-Slice Transistor Schematic",
            fontsize=13.5, fontweight="bold", color=C_INK, ha="left", va="center")
    ax.text(0.30, 9.24, "Circuit: analog/rx/cmos_rx/spice/rx_cmos_pi.spice  ·  Full Chip Array = 2 Channels (Data 0°/180°, Edge +90°/+270°) × 2 Polarities (p/n) × 8 Slices = 32 Identical Slices",
            fontsize=8.9, color=C_MUTED, ha="left", va="center")

    # -----------------------------------------------------------------------
    # LEFT: Stage 1 — 4:1 Static LVT Transmission-Gate Coarse Octant Muxes
    # -----------------------------------------------------------------------
    # Rear stacked card representing complementary (-180 deg) polarity & +90 deg Edge channel
    draw_card(ax, 0.56, 2.38, 3.30, 5.55, fc="#f1f5f9", ec="#94a3b8", lw=1.1, z=2)
    ax.text(3.74, 7.72, "n-leg (180°) & Edge (+90°)", fontsize=6.8, fontweight="bold", color=C_GRAY, ha="right", va="center", zorder=3)
    draw_card(ax, 0.30, 2.10, 3.30, 5.55, fc="#ffffff", ec=C_BLUE, lw=1.5, z=4, shadow=True)
    ax.text(1.95, 7.36, "Stage 1: 4:1 LVT-TG Mux", fontsize=8.8, fontweight="bold", color=C_BLUE, ha="center", va="center", zorder=6)
    ax.text(1.95, 7.06, "pi_mux4_tg (0.00 ps pin skew)", fontsize=7.1, color=C_MUTED, ha="center", va="center", zorder=6)

    # Even Bank A (top inside left card)
    ax.add_patch(FancyBboxPatch((0.46, 4.78), 2.98, 2.02, boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor=C_BLUE_LT, edgecolor="#93c5fd", lw=1.0, zorder=5))
    ax.text(0.58, 6.62, "Even Bank A (one-hot a0,2,4,6)", fontsize=7.0, fontweight="bold", color=C_BLUE, ha="left", zorder=6)
    for k, (lbl, yy) in enumerate((("c0 (0°)", 6.30), ("c2 (90°)", 5.88), ("c4 (180°)", 5.46), ("c6 (270°)", 5.04))):
        ax.text(0.52, yy, lbl, fontsize=6.4, fontweight="bold", color=C_BLUE, ha="left", va="center", zorder=7)
        wire(ax, [(1.25, yy), (1.50, yy)], color=C_BLUE, lw=1.1, z=7)
        xe = draw_tgate(ax, 1.50, yy, w=0.42, h=0.22, top_lbl="", bot_lbl="", ec=C_BLUE, fc="#ffffff", z=8)
        wire(ax, [(xe, yy), (2.22, yy)], color=C_BLUE, lw=1.1, z=7)
    wire(ax, [(2.22, 5.04), (2.22, 6.30)], color=C_BLUE, lw=1.3, z=7)
    dot(ax, 2.22, 5.67, color=C_BLUE, r=0.055, z=9)
    wire(ax, [(2.22, 5.67), (2.48, 5.67)], color=C_BLUE, lw=1.3, z=7)
    inv_a = draw_inv(ax, 2.48, 5.67, w=0.46, h=0.42, fc="#ffffff", ec=C_BLUE, lw=1.4, z=8)
    ax.text(2.74, 5.26, "1.8/8.4µm", fontsize=6.0, color=C_BLUE, ha="center", zorder=8)
    wire(ax, [inv_a["out"], (3.95, 5.67)], color=C_BLUE, lw=1.8, z=11)

    # Odd Bank B (bottom inside left card)
    ax.add_patch(FancyBboxPatch((0.46, 2.38), 2.98, 2.02, boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor=C_ORANGE_LT, edgecolor="#fdba74", lw=1.0, zorder=5))
    ax.text(0.58, 4.22, "Odd Bank B (one-hot b1,3,5,7)", fontsize=7.0, fontweight="bold", color=C_ORANGE, ha="left", zorder=6)
    for k, (lbl, yy) in enumerate((("c1 (45°)", 3.90), ("c3 (135°)", 3.48), ("c5 (225°)", 3.06), ("c7 (315°)", 2.64))):
        ax.text(0.52, yy, lbl, fontsize=6.4, fontweight="bold", color=C_ORANGE, ha="left", va="center", zorder=7)
        wire(ax, [(1.25, yy), (1.50, yy)], color=C_ORANGE, lw=1.1, z=7)
        xe = draw_tgate(ax, 1.50, yy, w=0.42, h=0.22, top_lbl="", bot_lbl="", ec=C_ORANGE, fc="#ffffff", z=8)
        wire(ax, [(xe, yy), (2.22, yy)], color=C_ORANGE, lw=1.1, z=7)
    wire(ax, [(2.22, 2.64), (2.22, 3.90)], color=C_ORANGE, lw=1.3, z=7)
    dot(ax, 2.22, 3.27, color=C_ORANGE, r=0.055, z=9)
    wire(ax, [(2.22, 3.27), (2.48, 3.27)], color=C_ORANGE, lw=1.3, z=7)
    inv_b = draw_inv(ax, 2.48, 3.27, w=0.46, h=0.42, fc="#ffffff", ec=C_ORANGE, lw=1.4, z=8)
    ax.text(2.74, 2.86, "1.8/8.4µm", fontsize=6.0, color=C_ORANGE, ha="center", zorder=8)
    wire(ax, [inv_b["out"], (3.95, 3.27)], color=C_ORANGE, lw=1.8, z=11)

    # -----------------------------------------------------------------------
    # CENTER HERO: 8 STACKED PAGES (`pi_slice_r` Slice 0 in front .. Slice 7 in back!)
    # -----------------------------------------------------------------------
    sx0, sy0, sw, sh = 4.35, 1.35, 6.40, 5.75
    dx, dy = 0.28, 0.24
    # Draw receding back pages Slice 7 down to Slice 1 (classic ISSCC stacked-sheet effect!)
    back_specs = [
        (7, "Slice 7 (f[7])", "#e2e8f0", "#64748b"),
        (6, "Slice 6 (f[6])", "#e6eef6", "#64748b"),
        (5, "Slice 5 (f[5])", "#ebf3f9", "#475569"),
        (4, "Slice 4 (f[4])", "#eff7fb", "#475569"),
        (3, "Slice 3 (f[3])", "#f3fafc", "#0f766e"),
        (2, "Slice 2 (f[2])", "#f6fcfd", "#0f766e"),
        (1, "Slice 1 (f[1])", "#f9fefe", "#0f766e"),
    ]
    # Vertical bus risers distributing ca, cb to all 8 stacked pages + mix bus collecting all 8!
    for k, lbl, fc_k, ec_k in back_specs:
        xk = sx0 + k * dx
        yk = sy0 + k * dy
        z_k = 10 - k
        draw_card(ax, xk, yk, sw, sh, fc=fc_k, ec=ec_k, lw=1.05, r=0.16, z=z_k)
        # Clean page tab label on upper-right visible ledge of each stacked card!
        ax.text(xk + sw - 0.14, yk + sh - 0.12, lbl, fontsize=6.7, fontweight="bold",
                color=ec_k, ha="right", va="top", zorder=z_k + 0.5)
        # Right-side R_sum tap from each back slice onto the diagonal/vertical `mix` bus!
        y_tap = yk + 3.85
        wire(ax, [(xk + sw, y_tap), (12.95, y_tap)], color=C_TEAL, lw=1.05, ls="-", z=z_k + 0.4)
        dot(ax, 12.95, y_tap, color=C_TEAL, r=0.052, z=15)

    # Diagonal thermometer control bus annotation f[0..7] along top-left staircase
    wire(ax, [(sx0 + 0.65, sy0 + sh + 0.20), (sx0 + 7 * dx + 0.65, sy0 + 7 * dy + sh + 0.20)],
         color=C_RED, lw=1.6, ls="--", z=16)
    ax.text(sx0 + 2.3 * dx, sy0 + 4.8 * dy + sh + 0.15, "Thermometer Code f[7:0]\n(k slices → cb, 8−k → ca)",
            fontsize=7.6, fontweight="bold", color=C_RED, ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.18", fc="#fff1f2", ec=C_RED, lw=0.9), zorder=17)

    # FRONT HERO PAGE: Slice 0 (Full Transistor-Level Schematic of `pi_slice_r`!)
    draw_card(ax, sx0, sy0, sw, sh, fc="#ffffff", ec=C_TEAL, lw=2.0, r=0.18, z=20, shadow=True)
    ax.text(sx0 + 0.22, sy0 + sh - 0.26, "Slice 0  (Front Page of ×8 Stack — pi_slice_r)",
            fontsize=9.1, fontweight="bold", color=C_TEAL, ha="left", va="center", zorder=22)
    ax.text(sx0 + sw - 0.18, sy0 + sh - 0.26, "f[0] / fb[0]",
            fontsize=8.0, fontweight="bold", color=C_RED, ha="right", va="center",
            bbox=dict(boxstyle="round,pad=0.14", fc="#fff1f2", ec=C_RED, lw=0.8), zorder=22)

    # Sub-region 1 inside front card: Active Signal Path (top half)
    ax.add_patch(FancyBboxPatch((sx0 + 0.20, sy0 + 2.65), sw - 0.40, 2.65,
                                boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor=C_TEAL_LT, edgecolor="#99f6e4", lw=1.0, zorder=21))
    ax.text(sx0 + 0.34, sy0 + 5.14, "Active Weighting Leg (5.8 kΩ Linearizing R)",
            fontsize=7.2, fontweight="bold", color=C_TEAL, ha="left", va="center", zorder=22)

    # Connect ca & cb buses into front Slice 0 (with vertical taps down to dummy!)
    y_ca = sy0 + 4.32
    y_cb = sy0 + 3.30
    wire(ax, [(3.95, 5.67), (3.95, y_ca), (sx0 + 1.05, y_ca)], color=C_BLUE, lw=1.8, z=23)
    wire(ax, [(3.95, 3.27), (3.95, y_cb), (sx0 + 1.05, y_cb)], color=C_ORANGE, lw=1.8, z=23)
    # Indicate ca/cb also fan up to back slices 1..7!
    arrow(ax, (3.95, 5.67), (3.95, 7.15), color=C_BLUE, lw=1.3, ls="--", z=16)
    ax.text(3.95, 7.22, "ca →\nSlices 1..7", fontsize=6.6, fontweight="bold", color=C_BLUE, ha="center", va="bottom", zorder=17)
    ax.text(sx0 + 0.18, y_ca + 0.15, "ca", fontsize=8.0, fontweight="bold", color=C_BLUE, ha="left", zorder=24)
    ax.text(sx0 + 0.18, y_cb + 0.15, "cb", fontsize=8.0, fontweight="bold", color=C_ORANGE, ha="left", zorder=24)

    # Active transmission gates Xsa / Xsb
    xe1 = draw_tgate(ax, sx0 + 1.05, y_ca, w=0.58, h=0.36, top_lbl="f0", bot_lbl="fb0", ec=C_BLUE, fc="#eff6ff", fs=6.5, z=24)
    xe2 = draw_tgate(ax, sx0 + 1.05, y_cb, w=0.58, h=0.36, top_lbl="fb0", bot_lbl="f0", ec=C_ORANGE, fc="#fff7ed", fs=6.5, z=24)
    ax.text(sx0 + 1.34, y_ca + 0.44, "Xsa (LVT)", fontsize=6.1, color=C_BLUE, ha="center", zorder=24)
    ax.text(sx0 + 1.34, y_cb - 0.50, "Xsb (LVT)", fontsize=6.1, color=C_ORANGE, ha="center", zorder=24)
    wire(ax, [(xe1, y_ca), (sx0 + 1.98, y_ca), (sx0 + 1.98, y_cb), (xe2, y_cb)], color=C_WIRE, lw=1.45, z=23)
    y_mid = 0.5 * (y_ca + y_cb)
    dot(ax, sx0 + 1.98, y_mid, color=C_WIRE, r=0.06, z=25)
    wire(ax, [(sx0 + 1.98, y_mid), (sx0 + 2.55, y_mid)], color=C_WIRE, lw=1.5, z=23)
    ax.text(sx0 + 2.26, y_mid + 0.14, "sel", fontsize=7.0, fontweight="bold", color=C_INK, ha="center", zorder=24)

    # Real Transistor-Level Lean Inverter (Xinv_p 1.70/0.15 + Xinv_n 0.42/0.15 LVT)
    mp = draw_mos(ax, sx0 + 3.08, y_mid + 0.56, pmos=True, lvt=False, scale=0.80, color="#14532d", z=24)
    mn = draw_mos(ax, sx0 + 3.08, y_mid - 0.56, pmos=False, lvt=True, scale=0.80, color="#14532d", z=24)
    wire(ax, [(sx0 + 2.55, y_mid), (sx0 + 2.55, mp["g"][1]), mp["g"]], color=C_WIRE, lw=1.45, z=23)
    wire(ax, [(sx0 + 2.55, y_mid), (sx0 + 2.55, mn["g"][1]), mn["g"]], color=C_WIRE, lw=1.45, z=23)
    dot(ax, sx0 + 2.55, y_mid, color=C_WIRE, r=0.055, z=25)
    vdd_bar(ax, mp["top"][0], mp["top"][1], label="VDD", s=0.14, fs=6.3, z=24)
    gnd(ax, mn["bot"][0], mn["bot"][1], s=0.14, z=24)
    wire(ax, [mp["bot"], mn["top"]], color=C_WIRE, lw=1.5, z=23)
    dot(ax, mp["bot"][0], y_mid, color=C_WIRE, r=0.06, z=25)
    ax.text(sx0 + 3.48, y_mid + 0.58, "Xinv_p\n1.70/0.15", fontsize=6.1, color="#14532d", ha="left", va="center", zorder=24)
    ax.text(sx0 + 3.48, y_mid - 0.56, "Xinv_n LVT\n0.42/0.15", fontsize=6.1, color="#0d9488", ha="left", va="center", zorder=24)

    # Summing resistor Xres (high_po_0p69, 5.8 kOhm) -> mix bus
    wire(ax, [(mp["bot"][0], y_mid), (sx0 + 4.35, y_mid)], color=C_TEAL, lw=1.6, z=23)
    ax.text(sx0 + 3.92, y_mid + 0.14, "drv", fontsize=6.8, color=C_MUTED, ha="center", zorder=24)
    draw_res_h(ax, sx0 + 4.35, sx0 + 5.75, y_mid, amp=0.15, nzig=5, color=C_TEAL, lw=1.8, z=24)
    ax.text(sx0 + 5.05, y_mid + 0.28, "Xres = 5.8 kΩ", fontsize=7.4, fontweight="bold", color=C_TEAL, ha="center", zorder=24)
    ax.text(sx0 + 5.05, y_mid - 0.28, "high_po_0p69 (l=10.8µm)", fontsize=6.1, color=C_MUTED, ha="center", va="top", zorder=24)
    wire(ax, [(sx0 + 5.75, y_mid), (12.95, y_mid)], color=C_TEAL, lw=2.2, z=23)
    pin_diamond(ax, sx0 + sw, y_mid, color=C_TEAL, s=0.10, z=26)

    # Sub-region 2 inside front card: Constant-Load Passive Dummy (bottom half)
    ax.add_patch(FancyBboxPatch((sx0 + 0.20, sy0 + 0.22), sw - 0.40, 2.25,
                                boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor=C_GRAY_LT, edgecolor="#cbd5e1", lw=1.0, ls="--", zorder=21))
    ax.text(sx0 + 0.34, sy0 + 2.34, "Passive Constant-Load Dummy (0 µW Drive, 0.00 ps Bow)",
            fontsize=6.9, fontweight="bold", color=C_GRAY, ha="left", va="center", zorder=22)

    y_da = sy0 + 1.58
    y_db = sy0 + 0.74
    dot(ax, sx0 + 0.62, y_ca, color=C_BLUE, r=0.055, z=25)
    dot(ax, sx0 + 0.82, y_cb, color=C_ORANGE, r=0.055, z=25)
    wire(ax, [(sx0 + 0.62, y_ca), (sx0 + 0.62, y_da), (sx0 + 1.05, y_da)], color=C_BLUE, lw=1.1, ls="--", z=23)
    wire(ax, [(sx0 + 0.82, y_cb), (sx0 + 0.82, y_db), (sx0 + 1.05, y_db)], color=C_ORANGE, lw=1.1, ls="--", z=23)
    xd1 = draw_tgate(ax, sx0 + 1.05, y_da, w=0.58, h=0.31, top_lbl="fb0", bot_lbl="", ec=C_GRAY, fc="#ffffff", fs=6.2, z=24)
    xd2 = draw_tgate(ax, sx0 + 1.05, y_db, w=0.58, h=0.31, top_lbl="", bot_lbl="f0", ec=C_GRAY, fc="#ffffff", fs=6.2, z=24)
    wire(ax, [(xd1, y_da), (sx0 + 1.98, y_da), (sx0 + 1.98, y_db), (xd2, y_db)], color=C_GRAY, lw=1.25, z=23)
    y_dmid = 0.5 * (y_da + y_db)
    dot(ax, sx0 + 1.98, y_dmid, color=C_GRAY, r=0.05, z=25)
    wire(ax, [(sx0 + 1.98, y_dmid), (sx0 + 2.55, y_dmid)], color=C_GRAY, lw=1.3, z=23)
    ax.text(sx0 + 2.26, y_dmid + 0.13, "dum", fontsize=6.7, color=C_GRAY, ha="center", zorder=24)

    dmp = draw_mos(ax, sx0 + 3.08, y_dmid + 0.40, pmos=True, scale=0.64, color=C_GRAY, z=24)
    dmn = draw_mos(ax, sx0 + 3.08, y_dmid - 0.40, pmos=False, lvt=True, scale=0.64, color=C_GRAY, z=24)
    wire(ax, [(sx0 + 2.55, y_dmid), (sx0 + 2.55, dmp["g"][1]), dmp["g"]], color=C_GRAY, lw=1.2, z=23)
    wire(ax, [(sx0 + 2.55, y_dmid), (sx0 + 2.55, dmn["g"][1]), dmn["g"]], color=C_GRAY, lw=1.2, z=23)
    # Short S=D to VDD / VSS on dummy MOS caps!
    wire(ax, [dmp["top"], (dmp["top"][0] + 0.25, dmp["top"][1]), (dmp["top"][0] + 0.25, dmp["bot"][1]), dmp["bot"]], color=C_GRAY, lw=1.15, z=23)
    vdd_bar(ax, dmp["top"][0] + 0.25, dmp["top"][1], label="VDD", s=0.13, color=C_GRAY, fs=6.0, z=24)
    wire(ax, [dmn["top"], (dmn["top"][0] + 0.25, dmn["top"][1]), (dmn["top"][0] + 0.25, dmn["bot"][1]), dmn["bot"]], color=C_GRAY, lw=1.15, z=23)
    gnd(ax, dmn["bot"][0] + 0.25, dmn["bot"][1], s=0.13, color=C_GRAY, z=24)
    ax.text(sx0 + 3.82, y_dmid, "Matched MOS Gate Caps\n(Xdp 1.70/0.15, Xdn 0.42/0.15)\nS=D tied to rail → 0 dynamic I!\nC(ca) = C(cb) for ALL codes 0..8",
            fontsize=6.5, color=C_MUTED, ha="left", va="center", linespacing=1.32, zorder=24)

    # -----------------------------------------------------------------------
    # RIGHT: Shared `mix` Summing Bus + C_mim + AC Self-Biased LVT Recovery
    # -----------------------------------------------------------------------
    # Bold vertical summing bus collecting Slice 0..Slice 7!
    wire(ax, [(12.95, y_mid), (12.95, sy0 + 7 * dy + 3.85)], color=C_TEAL, lw=2.6, z=22)
    dot(ax, 12.95, y_mid, color=C_TEAL, r=0.085, z=25)
    ax.text(12.95, sy0 + 7 * dy + 4.18, "Shared Node mix\n(Σ 8 slices)", fontsize=7.3, fontweight="bold",
            color=C_TEAL, ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.14", fc="#ffffff", ec=C_TEAL, lw=0.8), zorder=25)

    # C_mim = 37 fF hanging off shared `mix` node
    wire(ax, [(12.95, y_mid), (12.95, 3.65)], color=C_TEAL, lw=1.8, z=22)
    draw_cap_v(ax, 12.95, 2.80, 3.65, w=0.46, gap=0.13, color=C_TEAL, lw=1.8, z=23)
    gnd(ax, 12.95, 2.80, s=0.18, color=C_TEAL, z=23)
    ax.text(12.95, 2.26, "Xcmix = 37 fF\n(4.1×4.1µm MIM1)\nτ_mix ≈ 43 ps", fontsize=6.7, fontweight="bold",
            color=C_TEAL, ha="center", va="top", zorder=24)

    # Stage 3 Card: AC Self-Biased LVT Recovery + Matched Output Buffer
    draw_card(ax, 13.55, 2.25, 4.45, 5.65, fc="#ffffff", ec=C_PURPLE, lw=1.6, r=0.18, z=20, shadow=True)
    ax.text(15.78, 7.62, "Stage 3: AC Self-Biased Recovery", fontsize=8.5, fontweight="bold", color=C_PURPLE, ha="center", va="center", zorder=22)
    ax.text(15.78, 7.34, "pi_ac_rec + Matched Output LVT Buf", fontsize=6.9, color=C_MUTED, ha="center", va="center", zorder=22)

    # mix -> C_ac -> acp -> Self-biased LVT inverter (R_fb) -> r1p -> Output LVT inverter -> dp
    wire(ax, [(12.95, y_mid), (13.74, y_mid)], color=C_TEAL, lw=2.0, z=23)
    draw_cap_h(ax, 13.74, 14.42, y_mid, h=0.46, gap=0.13, color=C_PURPLE, lw=1.8, z=24)
    ax.text(14.08, y_mid + 0.34, "C_ac\n37 fF", fontsize=6.7, fontweight="bold", color=C_PURPLE, ha="center", va="bottom", zorder=24)

    wire(ax, [(14.42, y_mid), (14.84, y_mid)], color=C_PURPLE, lw=1.55, z=23)
    dot(ax, 14.62, y_mid, color=C_PURPLE, r=0.06, z=25)
    ax.text(14.62, y_mid - 0.24, "acp", fontsize=6.7, fontweight="bold", color=C_PURPLE, ha="center", zorder=24)

    # Real transistor-level LVT Recovery Inverter (Wp/Wn = 6.60/1.65 = 4.00)
    rp = draw_mos(ax, 15.32, y_mid + 0.58, pmos=True, lvt=True, scale=0.80, color=C_PURPLE, z=24)
    rn = draw_mos(ax, 15.32, y_mid - 0.58, pmos=False, lvt=True, scale=0.80, color=C_PURPLE, z=24)
    wire(ax, [(14.84, y_mid), (14.84, rp["g"][1]), rp["g"]], color=C_PURPLE, lw=1.45, z=23)
    wire(ax, [(14.84, y_mid), (14.84, rn["g"][1]), rn["g"]], color=C_PURPLE, lw=1.45, z=23)
    dot(ax, 14.84, y_mid, color=C_PURPLE, r=0.055, z=25)
    vdd_bar(ax, rp["top"][0], rp["top"][1], label="VDD", s=0.14, color=C_PURPLE, fs=6.2, z=24)
    gnd(ax, rn["bot"][0], rn["bot"][1], s=0.14, color=C_PURPLE, z=24)
    wire(ax, [rp["bot"], rn["top"]], color=C_PURPLE, lw=1.5, z=23)
    dot(ax, rp["bot"][0], y_mid, color=C_PURPLE, r=0.06, z=25)
    ax.text(15.30, y_mid - 1.40, "LVT Inv (6.60/0.35,\n1.65/0.15, Wp/Wn=4)", fontsize=6.1, color=C_PURPLE, ha="center", va="top", zorder=24)

    # R_fb = 12.3 kOhm pure negative DC feedback loop over LVT inverter
    wire(ax, [(14.62, y_mid), (14.62, y_mid + 1.48), (14.82, y_mid + 1.48)], color=C_RED, lw=1.4, z=23)
    draw_res_h(ax, 14.82, 15.84, y_mid + 1.48, amp=0.12, nzig=5, color=C_RED, lw=1.55, z=24)
    wire(ax, [(15.84, y_mid + 1.48), (15.96, y_mid + 1.48), (15.96, y_mid)], color=C_RED, lw=1.4, z=23)
    dot(ax, 15.96, y_mid, color=C_PURPLE, r=0.06, z=25)
    ax.text(15.32, y_mid + 1.70, "R_fb = 12.3 kΩ (Auto V_M = VDD/2)", fontsize=6.6, fontweight="bold", color=C_RED, ha="center", zorder=24)

    # Output matched LVT buffer -> dp / dn -> QDiv2
    wire(ax, [(rp["bot"][0], y_mid), (16.24, y_mid)], color=C_PURPLE, lw=1.55, z=23)
    ob = draw_inv(ax, 16.24, y_mid, w=0.54, h=0.52, fc=C_BLUE_LT, ec=C_BLUE, lw=1.6, z=24)
    ax.text(16.52, y_mid - 0.40, "Out LVT\n10.64/2.66", fontsize=6.0, color=C_BLUE, ha="center", va="top", zorder=24)
    arrow(ax, ob["out"], (17.78, y_mid), color=C_BLUE, lw=2.0, z=24)
    ax.text(17.34, y_mid + 0.18, "dp (2 GHz)\n50.0% duty", fontsize=6.8, fontweight="bold", color=C_BLUE, ha="center", va="bottom", zorder=25)

    # Bottom architecture takeaway strip
    ax.add_patch(FancyBboxPatch((0.30, 0.02), 17.60, 0.96, boxstyle="round,pad=0.02,rounding_size=0.14",
                                facecolor="#f8fafc", edgecolor="#cbd5e1", lw=1.1, zorder=5))
    ax.text(0.55, 0.68, "Full-Chip Array Replication Summary:", fontsize=8.3, fontweight="bold", color=C_INK, ha="left", va="center", zorder=6)
    ax.text(0.55, 0.30,
            "• 1 Single-Ended Mixer = 8 stacked pi_slice_r pages (above)    "
            "• 1 Diff PI Channel = p + n (16 slices, 4× 4:1 TG Mux, 1× pi_ac_rec)    "
            "• Full RX PI = Data (0°/180°) + Edge (+90°/+270°) = 32 Slices Total (~7 mW, |INL| ≤ 0.015 UI)",
            fontsize=7.6, color=C_MUTED, ha="left", va="center", zorder=6)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        p = OUT_DIR / f"rx_pi_stacked_slices.{ext}"
        fig.savefig(p, dpi=240, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    print(f"[stacked] Saved {OUT_DIR / 'rx_pi_stacked_slices.png'} & .svg")


# ===========================================================================
# FIGURE 2: TX N-over-N SST STACKED-SLICE TRANSISTOR SCHEMATIC (tx_sst_driver.spice)
# ===========================================================================
def build_tx_sst_stacked():
    fig, ax = plt.subplots(figsize=(17.8, 9.8), dpi=240, facecolor=C_BG)
    ax.set_xlim(0.0, 18.4)
    ax.set_ylim(-0.35, 10.15)
    ax.set_aspect("equal")
    ax.axis("off")

    # Title banner
    ax.text(0.30, 9.80, "TX Quarter-Rate 4:1 Fused Low-Vdd N-over-N SST Driver + Free 2-Tap FFE — Stacked-Slice Transistor Schematic",
            fontsize=13.3, fontweight="bold", color=C_INK, ha="left", va="center")
    ax.text(0.30, 9.42, "Circuit: analog/tx/sst/spice/tx_sst_driver.spice  ·  Zero CML · Zero 2 GHz Clock · 28 Identical N-over-N Slices (23 Main + 5 Post-1 FFE) · 13.97 mW @ 4 Gb/s (−86.4% vs CML)",
            fontsize=8.7, color=C_MUTED, ha="left", va="center")

    # -----------------------------------------------------------------------
    # LEFT TOP: Quarter-Rate 4:1 Pulse Generator + Main / Post-1 FFE MUXes
    # -----------------------------------------------------------------------
    draw_card(ax, 0.30, 4.95, 4.35, 4.05, fc="#ffffff", ec=C_BLUE, lw=1.5, r=0.18, z=5, shadow=True)
    ax.text(2.47, 8.72, "Quarter-Rate 4:1 Fused Pre-Driver", fontsize=8.8, fontweight="bold", color=C_BLUE, ha="center", va="center", zorder=7)
    ax.text(2.47, 8.43, "1 GHz clocks only (zero 2 GHz logic!)", fontsize=7.0, color=C_MUTED, ha="center", va="center", zorder=7)

    # Pulse generator box
    ax.add_patch(FancyBboxPatch((0.48, 7.42), 3.98, 0.80, boxstyle="round,pad=0.02,rounding_size=0.10",
                                facecolor=C_GREEN_LT, edgecolor=C_GREEN, lw=1.0, zorder=6))
    ax.text(2.47, 7.96, "sst_pulsegen_4ph (4× 1 GHz φ0..270° → p0..p3)", fontsize=7.0, fontweight="bold", color=C_GREEN, ha="center", va="center", zorder=7)
    ax.text(2.47, 7.64, "25% duty (250 ps) strobes: p_k = NOR2(c_{k+1}, c_{k+2})", fontsize=6.0, color=C_MUTED, ha="center", va="center", zorder=7)

    # Main 4:1 MUX box
    ax.add_patch(FancyBboxPatch((0.48, 6.26), 3.98, 0.96, boxstyle="round,pad=0.02,rounding_size=0.10",
                                facecolor=C_BLUE_LT, edgecolor=C_BLUE, lw=1.1, zorder=6))
    ax.text(2.47, 6.96, "Main-Cursor 4:1 Static CMOS MUX (Xmux_m)", fontsize=7.2, fontweight="bold", color=C_BLUE, ha="center", va="center", zorder=7)
    ax.text(2.47, 6.56, "Data: (d0, d1, d2, d3) gated by p0..p3 → mp / mn (4 Gb/s)\n5-stage tapered NAND2/NOR2/INV (FO ≤ 2.8)",
            fontsize=6.3, color=C_MUTED, ha="center", va="center", linespacing=1.28, zorder=7)

    # Post-1 FFE 4:1 MUX box
    ax.add_patch(FancyBboxPatch((0.48, 5.10), 3.98, 0.96, boxstyle="round,pad=0.02,rounding_size=0.10",
                                facecolor=C_ORANGE_LT, edgecolor=C_ORANGE, lw=1.1, zorder=6))
    ax.text(2.47, 5.80, "Free Post-1 FFE 4:1 MUX (Xmux_f, delay-matched)", fontsize=7.2, fontweight="bold", color=C_ORANGE, ha="center", va="center", zorder=7)
    ax.text(2.47, 5.40, "Rotated 1 UI & Inverted: (db3, db0, db1, db2) → fp / fn\nNo 4 Gb/s delay FF needed! (ffe_en=0 → fp=fn=0)",
            fontsize=6.3, color=C_MUTED, ha="center", va="center", linespacing=1.28, zorder=7)

    # -----------------------------------------------------------------------
    # LEFT BOTTOM: On-Chip Low-Vdd Sub-Regulator (`sst_vdrv_ldo`: 1.8V -> 0.44V)
    # -----------------------------------------------------------------------
    draw_card(ax, 0.30, 1.30, 4.35, 3.30, fc=C_AMBER_LT, ec=C_AMBER, lw=1.5, r=0.18, z=5, shadow=True)
    ax.text(2.47, 4.34, "On-Chip V_drv LDO (sst_vdrv_ldo)", fontsize=8.7, fontweight="bold", color=C_AMBER, ha="center", va="center", zorder=7)
    ax.text(2.47, 4.06, "1.8 V → V_drv ≈ 0.44 V (All-Transistor SKY130)", fontsize=6.9, color=C_MUTED, ha="center", va="center", zorder=7)

    # Mini real schematic inside LDO card: R-divider -> 5T PMOS OTA -> W=240u LVT NMOS Pass -> V_drv
    ax.add_patch(FancyBboxPatch((0.50, 2.75), 1.05, 0.92, boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor="#ffffff", edgecolor=C_AMBER, lw=1.0, zorder=7))
    ax.text(1.02, 3.36, "Vbg 1.2V\nR-Div", fontsize=6.5, fontweight="bold", color=C_AMBER, ha="center", va="center", zorder=8)
    ax.text(1.02, 2.96, "63/37µm\n→0.446V", fontsize=5.9, color=C_MUTED, ha="center", va="center", zorder=8)

    # 5T OTA triangle
    ota_x, ota_y = 1.88, 3.20
    ax.add_patch(Polygon([(ota_x, ota_y - 0.42), (ota_x, ota_y + 0.42), (ota_x + 0.80, ota_y)],
                         closed=True, facecolor="#ffffff", edgecolor=C_AMBER, lw=1.35, zorder=8))
    ax.text(ota_x + 0.28, ota_y, "5T\nOTA", fontsize=6.4, fontweight="bold", color=C_AMBER, ha="center", va="center", zorder=9)
    wire(ax, [(1.55, 3.32), (ota_x, 3.32)], color=C_AMBER, lw=1.3, z=8)

    # Wide LVT NMOS Pass Follower (W=240u, L=0.15u, nf=32)
    mpass = draw_mos(ax, 3.45, 3.20, pmos=False, lvt=True, scale=0.80, color=C_AMBER, z=9)
    wire(ax, [(ota_x + 0.80, ota_y), mpass["g"]], color=C_AMBER, lw=1.4, z=8)
    vdd_bar(ax, mpass["top"][0], mpass["top"][1], label="VDD 1.8V", s=0.14, color=C_AMBER, fs=6.2, z=9)
    ax.text(3.84, 3.20, "Xpass LVT\n240/0.15\n(nf=32)", fontsize=6.0, fontweight="bold", color=C_AMBER, ha="left", va="center", zorder=9)
    # Feedback from V_drv back to OTA '-' input + bleed + 15.3 pF MIM
    wire(ax, [mpass["bot"], (mpass["bot"][0], 2.24), (1.70, 2.24), (1.70, 3.05), (ota_x, 3.05)], color=C_AMBER, lw=1.25, z=8)
    dot(ax, mpass["bot"][0], 2.24, color=C_AMBER, r=0.06, z=10)
    ax.text(2.47, 1.76, "Xrbleed (l=5.0µm) + 6× Stacked MIM1+MIM2 (15.3 pF)\nLow-Vgs NMOS Follower → >0.6 V headroom @ 1.65 V!",
            fontsize=6.2, color=C_MUTED, ha="center", va="center", linespacing=1.28, zorder=8)

    # Thick golden V_drv bus running right into ALL 28 stacked SST slices!
    wire(ax, [(mpass["bot"][0], 2.24), (5.05, 2.24), (5.05, 6.05)], color=C_AMBER, lw=2.6, z=14)
    ax.text(5.05, 4.18, "V_drv ≈ 0.44 V (all 28 slices)", fontsize=6.7, fontweight="bold",
            color=C_AMBER, ha="center", va="center", rotation=90,
            bbox=dict(boxstyle="round,pad=0.14", fc=C_AMBER_LT, ec=C_AMBER, lw=0.8), zorder=16)

    # -----------------------------------------------------------------------
    # CENTER-RIGHT HERO: DUAL STACKED-PAGE SST ARRAY (23 Main + 5 FFE = 28 Slices!)
    # -----------------------------------------------------------------------
    sx0, sy0, sw, sh = 5.45, 1.35, 7.50, 5.75
    dx, dy = 0.30, 0.25

    # Back 3 stacked pages = POST-1 FFE BANKS (Orange: f2=2x, f1=2x, f0=1x -> 5 slices total!)
    ffe_cards = [
        (7, "FFE Bank f2 (×2 slices)  [fp, fn]", "#ffedd5", C_ORANGE),
        (6, "FFE Bank f1 (×2 slices)  [fp, fn]", "#fff1e0", C_ORANGE),
        (5, "FFE Bank f0 (×1 slice)   [fp, fn]", "#fff7ed", C_ORANGE),
    ]
    # Middle 4 stacked pages = MAIN CURSOR BINARY BANKS (Blue: m4=8x, m3=8x, m2=4x, m1=2x!)
    main_cards = [
        (4, "Main Bank m4 (×8 slices)  [mp, mn]", "#dbeafe", C_BLUE),
        (3, "Main Bank m3 (×8 slices)  [mp, mn]", "#e4efff", C_BLUE),
        (2, "Main Bank m2 (×4 slices)  [mp, mn]", "#edf4ff", C_BLUE),
        (1, "Main Bank m1 (×2 slices)  [mp, mn]", "#f5f9ff", C_BLUE),
    ]
    for k, lbl, fc_k, ec_k in ffe_cards + main_cards:
        xk = sx0 + k * dx
        yk = sy0 + k * dy
        z_k = 12 - k
        draw_card(ax, xk, yk, sw, sh, fc=fc_k, ec=ec_k, lw=1.15, r=0.16, z=z_k)
        ax.text(xk + sw - 0.14, yk + sh - 0.12, lbl, fontsize=6.8, fontweight="bold",
                color=ec_k, ha="right", va="top", zorder=z_k + 0.5)
        # Right-side pad_p / pad_n summing taps into the shared differential 50-Ohm pad bus!
        yp_k = yk + 4.05
        yn_k = yk + 2.25
        wire(ax, [(xk + sw, yp_k), (15.55, yp_k)], color=C_BLUE, lw=1.1, z=z_k + 0.4)
        wire(ax, [(xk + sw, yn_k), (16.15, yn_k)], color=C_RED, lw=1.1, z=z_k + 0.4)
        dot(ax, 15.55, yp_k, color=C_BLUE, r=0.055, z=18)
        dot(ax, 16.15, yn_k, color=C_RED, r=0.055, z=18)

    # Diagonal FFE & Main input routing into the stacked staircase
    wire(ax, [(4.46, 6.74), (5.25, 6.74), (5.25, 4.95), (sx0 + 0.45, 4.95)], color=C_BLUE, lw=1.8, z=22)
    ax.text(5.12, 7.22, "mp / mn\n(Main 4Gb/s)", fontsize=6.6, fontweight="bold", color=C_BLUE, ha="center", va="bottom",
            bbox=dict(boxstyle="round,pad=0.14", fc=C_BLUE_LT, ec=C_BLUE, lw=0.8), zorder=24)
    # Orange fp/fn climbs straight into rear FFE stack (k=5..7)
    wire(ax, [(4.46, 5.58), (4.80, 5.58), (4.80, 8.65), (sx0 + 5 * dx + 0.45, 8.65)], color=C_ORANGE, lw=1.6, ls="--", z=16)
    arrow(ax, (sx0 + 5 * dx + 0.45, 8.65), (sx0 + 5 * dx + 0.45, sy0 + 5 * dy + sh), color=C_ORANGE, lw=1.5, z=17)
    ax.text(5.65, 8.76, "fp / fn (Post-1 FFE, rotated 1 UI & inverted) → 5 Rear Orange Slices",
            fontsize=7.3, fontweight="bold", color=C_ORANGE, ha="left", va="bottom",
            bbox=dict(boxstyle="round,pad=0.14", fc=C_ORANGE_LT, ec=C_ORANGE, lw=0.8), zorder=18)

    # FRONT HERO PAGE: Slice m0 (×1) — FULL TRANSISTOR-LEVEL `sst_slice_unit`!!
    draw_card(ax, sx0, sy0, sw, sh, fc="#ffffff", ec=C_BLUE, lw=2.1, r=0.18, z=20, shadow=True)
    ax.text(sx0 + 0.22, sy0 + sh - 0.26, "Unit Slice m0  (Front Page of 28-Slice Array — sst_slice_unit, 800 Ω/slice)",
            fontsize=8.9, fontweight="bold", color=C_BLUE, ha="left", va="center", zorder=22)

    # 1) Left half of front card: Zero-Stacked-PMOS Local Enable Driver (NAND2 -> INV)
    ax.add_patch(FancyBboxPatch((sx0 + 0.20, sy0 + 0.48), 2.55, 4.65, boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor=C_GRAY_LT, edgecolor="#cbd5e1", lw=1.0, zorder=21))
    ax.text(sx0 + 1.48, sy0 + 4.94, "Zero-Stacked-PMOS Local Drv", fontsize=7.1, fontweight="bold", color=C_INK, ha="center", zorder=22)
    ax.text(sx0 + 1.48, sy0 + 4.66, "en=0 → gp=gn=0 (Hi-Z, 0 dyn I!)", fontsize=6.2, color=C_MUTED, ha="center", zorder=22)

    y_p_drv = sy0 + 3.68
    y_n_drv = sy0 + 1.92
    nd_p = draw_nand2(ax, sx0 + 0.65, y_p_drv, w=0.62, h=0.46, fc="#ffffff", ec=C_BLUE, lw=1.45, z=23)
    nd_n = draw_nand2(ax, sx0 + 0.65, y_n_drv, w=0.62, h=0.46, fc="#ffffff", ec=C_RED, lw=1.45, z=23)
    iv_p = draw_inv(ax, sx0 + 1.75, y_p_drv, w=0.52, h=0.46, fc="#ffffff", ec=C_BLUE, lw=1.45, z=23)
    iv_n = draw_inv(ax, sx0 + 1.75, y_n_drv, w=0.52, h=0.46, fc="#ffffff", ec=C_RED, lw=1.45, z=23)
    wire(ax, [nd_p["out"], iv_p["in"]], color=C_BLUE, lw=1.4, z=23)
    wire(ax, [nd_n["out"], iv_n["in"]], color=C_RED, lw=1.4, z=23)
    wire(ax, [(sx0 + 0.28, nd_p["in1"][1]), nd_p["in1"]], color=C_BLUE, lw=1.4, z=23)
    wire(ax, [(sx0 + 0.28, nd_n["in2"][1]), nd_n["in2"]], color=C_RED, lw=1.4, z=23)
    ax.text(sx0 + 0.30, nd_p["in1"][1] + 0.14, "din_p", fontsize=6.6, fontweight="bold", color=C_BLUE, ha="left", zorder=24)
    ax.text(sx0 + 0.30, nd_n["in2"][1] - 0.20, "din_n", fontsize=6.6, fontweight="bold", color=C_RED, ha="left", zorder=24)
    # Shared enable `en`
    wire(ax, [(sx0 + 0.44, sy0 + 0.90), (sx0 + 0.44, nd_p["in2"][1]), nd_p["in2"]], color=C_GREEN, lw=1.35, z=23)
    wire(ax, [(sx0 + 0.44, nd_n["in1"][1]), nd_n["in1"]], color=C_GREEN, lw=1.35, z=23)
    dot(ax, sx0 + 0.44, nd_n["in1"][1], color=C_GREEN, r=0.055, z=25)
    ax.text(sx0 + 0.44, sy0 + 0.72, "en (m0)\n1.8V", fontsize=6.5, fontweight="bold", color=C_GREEN, ha="center", va="center", zorder=24)
    ax.text(sx0 + 1.50, y_p_drv - 0.42, "1.0/1.2µm → 1.1/2.2µm", fontsize=5.9, color=C_MUTED, ha="center", zorder=23)
    ax.text(sx0 + 1.50, y_n_drv - 0.42, "Full 0–1.8 V Gate Swing!", fontsize=6.0, fontweight="bold", color=C_INK, ha="center", zorder=23)

    # 2) Right half of front card: N-over-N Differential Bridge + high_po_2p85 Series Resistors!
    ax.add_patch(FancyBboxPatch((sx0 + 2.95, sy0 + 0.48), 4.35, 4.65, boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor="#fffdf5", edgecolor="#fcd34d", lw=1.1, zorder=21))
    ax.text(sx0 + 5.12, sy0 + 4.94, "Low-Vdd N-over-N Output Bridge (ZERO PMOS!)", fontsize=7.5, fontweight="bold", color=C_AMBER, ha="center", zorder=22)

    # Shared V_drv = 0.44 V rail across top of N-over-N bridge
    y_vdrv = sy0 + 4.54
    wire(ax, [(5.05, y_vdrv), (sx0 + 5.60, y_vdrv)], color=C_AMBER, lw=2.3, z=23)
    ax.text(sx0 + 4.45, y_vdrv + 0.10, "V_drv ≈ 0.44 V", fontsize=7.0, fontweight="bold", color=C_AMBER, ha="center", zorder=24)

    # Positive Half-Bridge (Xpup + Xpdp -> swp -> Xrp -> pad_p)
    x_leg_p = sx0 + 3.92
    x_leg_n = sx0 + 5.38
    y_up = sy0 + 3.85
    y_dn = sy0 + 1.58
    y_swp = sy0 + 3.15
    y_swn = sy0 + 2.25

    mpup = draw_mos(ax, x_leg_p, y_up, pmos=False, lvt=True, scale=0.84, color=C_BLUE, z=24)
    mpdp = draw_mos(ax, x_leg_p, y_dn, pmos=False, lvt=True, scale=0.84, color=C_BLUE, z=24)
    wire(ax, [mpup["top"], (mpup["top"][0], y_vdrv)], color=C_AMBER, lw=1.7, z=23)
    dot(ax, mpup["top"][0], y_vdrv, color=C_AMBER, r=0.06, z=25)
    wire(ax, [mpup["bot"], mpdp["top"]], color=C_BLUE, lw=1.6, z=23)
    gnd(ax, mpdp["bot"][0], mpdp["bot"][1], s=0.15, color=C_INK, z=24)

    # Negative Half-Bridge (Xpun + Xpdn -> swn -> Xrn -> pad_n)
    mpun = draw_mos(ax, x_leg_n, y_up, pmos=False, lvt=True, scale=0.84, color=C_RED, z=24)
    mpdn = draw_mos(ax, x_leg_n, y_dn, pmos=False, lvt=True, scale=0.84, color=C_RED, z=24)
    wire(ax, [mpun["top"], (mpun["top"][0], y_vdrv)], color=C_AMBER, lw=1.7, z=23)
    dot(ax, mpun["top"][0], y_vdrv, color=C_AMBER, r=0.06, z=25)
    wire(ax, [mpun["bot"], mpdn["top"]], color=C_RED, lw=1.6, z=23)
    gnd(ax, mpdn["bot"][0], mpdn["bot"][1], s=0.15, color=C_INK, z=24)

    # Labels on the 4 LVT NMOS switches
    ax.text(x_leg_p + 0.30, y_up + 0.16, "Xpup\n3.8/0.15\nLVT N", fontsize=5.9, fontweight="bold", color=C_BLUE, ha="left", va="center", zorder=24)
    ax.text(x_leg_p + 0.30, y_dn - 0.10, "Xpdp\n2.6/0.15\nLVT N", fontsize=5.9, fontweight="bold", color=C_BLUE, ha="left", va="center", zorder=24)
    ax.text(x_leg_n + 0.30, y_up + 0.16, "Xpun\n3.8/0.15", fontsize=5.9, fontweight="bold", color=C_RED, ha="left", va="center", zorder=24)
    ax.text(x_leg_n + 0.30, y_dn - 0.10, "Xpdn\n2.6/0.15", fontsize=5.9, fontweight="bold", color=C_RED, ha="left", va="center", zorder=24)

    # Gate routing gp & gn (cross-connected to differential N-over-N legs!)
    wire(ax, [iv_p["out"], (sx0 + 3.22, y_p_drv), (sx0 + 3.22, mpup["g"][1]), mpup["g"]], color=C_BLUE, lw=1.45, z=23)
    wire(ax, [(sx0 + 3.22, y_p_drv), (sx0 + 3.22, sy0 + 2.74), (sx0 + 4.78, sy0 + 2.74), (sx0 + 4.78, mpdn["g"][1]), mpdn["g"]],
         color=C_BLUE, lw=1.15, ls=":", z=23)
    dot(ax, sx0 + 3.22, y_p_drv, color=C_BLUE, r=0.055, z=25)
    ax.text(sx0 + 2.98, y_p_drv + 0.14, "gp", fontsize=7.0, fontweight="bold", color=C_BLUE, ha="center", zorder=24)

    wire(ax, [iv_n["out"], (sx0 + 3.10, y_n_drv), (sx0 + 3.10, mpdp["g"][1]), mpdp["g"]], color=C_RED, lw=1.45, z=23)
    wire(ax, [(sx0 + 3.10, y_n_drv), (sx0 + 3.10, sy0 + 2.52), (sx0 + 4.66, sy0 + 2.52), (sx0 + 4.66, mpun["g"][1]), mpun["g"]],
         color=C_RED, lw=1.15, ls=":", z=23)
    dot(ax, sx0 + 3.10, y_n_drv, color=C_RED, r=0.055, z=25)
    ax.text(sx0 + 2.98, y_n_drv + 0.14, "gn", fontsize=7.0, fontweight="bold", color=C_RED, ha="center", zorder=24)

    # Series PDK resistors Xrp & Xrn (res_high_po_2p85, l=3.75 um -> ~560 Ohm + ~240 Ohm Ron = 800 Ohm!)
    dot(ax, mpup["bot"][0], y_swp, color=C_BLUE, r=0.065, z=25)
    wire(ax, [(mpup["bot"][0], y_swp), (sx0 + 5.88, y_swp)], color=C_BLUE, lw=1.6, z=23)
    draw_res_h(ax, sx0 + 5.88, sx0 + 7.12, y_swp, amp=0.14, nzig=5, color=C_BLUE, lw=1.75, z=24)
    ax.text(sx0 + 6.50, y_swp + 0.24, "Xrp (high_po_2p85)", fontsize=6.4, fontweight="bold", color=C_BLUE, ha="center", zorder=24)
    wire(ax, [(sx0 + 7.12, y_swp), (15.55, y_swp)], color=C_BLUE, lw=2.2, z=23)
    pin_diamond(ax, sx0 + sw, y_swp, color=C_BLUE, s=0.10, z=26)

    dot(ax, mpun["bot"][0], y_swn, color=C_RED, r=0.065, z=25)
    wire(ax, [(mpun["bot"][0], y_swn), (sx0 + 5.88, y_swn)], color=C_RED, lw=1.6, z=23)
    draw_res_h(ax, sx0 + 5.88, sx0 + 7.12, y_swn, amp=0.14, nzig=5, color=C_RED, lw=1.75, z=24)
    ax.text(sx0 + 6.50, y_swn - 0.26, "Xrn (l=3.75µm, 70% R_out)", fontsize=6.3, fontweight="bold", color=C_RED, ha="center", va="top", zorder=24)
    wire(ax, [(sx0 + 7.12, y_swn), (16.15, y_swn)], color=C_RED, lw=2.2, z=23)
    pin_diamond(ax, sx0 + sw, y_swn, color=C_RED, s=0.10, z=26)

    # -----------------------------------------------------------------------
    # RIGHT: Bold Shared Differential 50-Ohm Output Bus (`pad_p`, `pad_n`) & ZQ/FFE Summary
    # -----------------------------------------------------------------------
    wire(ax, [(15.55, y_swp), (15.55, sy0 + 7 * dy + 4.05)], color=C_BLUE, lw=2.6, z=22)
    wire(ax, [(16.15, y_swn), (16.15, sy0 + 7 * dy + 2.25)], color=C_RED, lw=2.6, z=22)
    dot(ax, 15.55, y_swp, color=C_BLUE, r=0.085, z=25)
    dot(ax, 16.15, y_swn, color=C_RED, r=0.085, z=25)

    # Differential Pad Exits to 100-Ohm Channel
    arrow(ax, (15.55, 6.20), (17.05, 6.20), color=C_BLUE, lw=2.4, z=24)
    arrow(ax, (16.15, 4.90), (17.05, 4.90), color=C_RED, lw=2.4, z=24)
    draw_card(ax, 17.05, 4.35, 1.15, 2.45, fc="#f8fafc", ec=C_INK, lw=1.4, r=0.14, z=22)
    ax.text(17.62, 6.22, "pad_p", fontsize=8.0, fontweight="bold", color=C_BLUE, ha="center", va="center", zorder=24)
    ax.text(17.62, 5.56, "100 Ω\nDiff\nPCB\nChannel", fontsize=7.0, fontweight="bold", color=C_INK, ha="center", va="center", zorder=24)
    ax.text(17.62, 4.88, "pad_n", fontsize=8.0, fontweight="bold", color=C_RED, ha="center", va="center", zorder=24)

    # Compact ZQ + FFE formula box on right bottom (strictly below pad_n bus y=3.60!)
    draw_card(ax, 15.10, 1.28, 3.12, 2.08, fc="#f0fdf4", ec=C_GREEN, lw=1.2, r=0.14, z=20)
    ax.text(16.66, 3.16, "Constant-50 Ω ZQ + FFE", fontsize=7.8, fontweight="bold", color=C_GREEN, ha="center", zorder=22)
    ax.text(15.26, 2.92,
            "• Total ON: N_zq = N_m + N_f ≈ 16\n"
            "  → R_out = 800 Ω / 16 = 50.0 Ω\n"
            "• FFE = 3 (13M + 3F) on C2 PCB:\n"
            "  spread 0.127 → 0.034 UI (3.7×)\n"
            "• Series reuse: ~2.2 mA vs 8 mA CML",
            fontsize=6.3, color=C_INK, ha="left", va="top", linespacing=1.28, zorder=22)

    # Bottom takeaway strip
    ax.add_patch(FancyBboxPatch((0.30, 0.02), 17.90, 0.96, boxstyle="round,pad=0.02,rounding_size=0.14",
                                facecolor="#f8fafc", edgecolor="#cbd5e1", lw=1.1, zorder=5))
    ax.text(0.55, 0.68, "Why Low-Vdd N-over-N SST Crushes CML in SKY130A:", fontsize=8.3, fontweight="bold", color=C_INK, ha="left", va="center", zorder=6)
    ax.text(0.55, 0.30,
            "• Pull-up & pull-down BOTH use 1.8 V-driven LVT NMOS (V_gs = 1.36–1.80 V deep triode!) — completely dodges SKY130's slow high-|Vthp| PMOS!    "
            "• 45/45 PVT PASS: 201–213 mV pad margin, 0.004–0.060 UI spread, 10.6–19.5 mW total TX.",
            fontsize=7.5, color=C_MUTED, ha="left", va="center", zorder=6)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        p = OUT_DIR / f"tx_sst_stacked_slices.{ext}"
        fig.savefig(p, dpi=240, bbox_inches="tight", facecolor=C_BG)
    plt.close(fig)
    print(f"[stacked] Saved {OUT_DIR / 'tx_sst_stacked_slices.png'} & .svg")


def main() -> None:
    build_rx_pi_stacked()
    build_tx_sst_stacked()


if __name__ == "__main__":
    main()
