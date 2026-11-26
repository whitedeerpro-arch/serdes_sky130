#!/usr/bin/env python3
"""Publication-grade intuitive schematic & principle diagram of the SKY130A 2 GHz 64-Code
Pure CMOS Resistor-Linearized RX Phase Interpolator + Deterministic 8-Phase 1 GHz QDiv2
(`analog/rx/cmos_rx/spice/rx_cmos_pi.spice`).
"""
from __future__ import annotations

import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle, Polygon
import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT_PNG = REPO / "docs/figures/rx/pi/rx_pi_schematic_explained.png"

# Clean, calm, high-contrast IEEE/JSSC palette
C_BG = "#ffffff"
C_PANEL = "#f8fafc"
C_BORDER = "#cbd5e1"
C_TEXT = "#0f172a"
C_MUTED = "#475569"
C_BLUE = "#1d4ed8"      # Even anchors A / Data channel
C_BLUE_BG = "#dbeafe"
C_ORANGE = "#c2410c"    # Odd anchors B / Edge channel
C_ORANGE_BG = "#ffedd5"
C_TEAL = "#0f766e"      # Mixer / RC summing
C_TEAL_BG = "#ccfbf1"
C_PURPLE = "#6d28d9"    # AC recovery / self-bias
C_PURPLE_BG = "#ede9fe"
C_GREEN = "#15803d"     # QDiv2 / deterministic clocks
C_GREEN_BG = "#dcfce7"
C_GRAY = "#64748b"
C_GRAY_BG = "#f1f5f9"
C_RED = "#be123c"


# ---------------------------------------------------------------------------
# Crisp Schematic Symbol Primitives
# ---------------------------------------------------------------------------
def draw_box(ax, x, y, w, h, text, fc="#ffffff", ec="#334155", tc=C_TEXT,
             fs=8.5, bold=True, lw=1.3, ls="-", r=0.18, z=5, sub=None):
    box = FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0.02,rounding_size={r}",
        facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, zorder=z,
    )
    ax.add_patch(box)
    if sub:
        ax.text(x + w / 2, y + h * 0.63, text, ha="center", va="center",
                fontsize=fs, fontweight="bold" if bold else "normal", color=tc, zorder=z + 1)
        ax.text(x + w / 2, y + h * 0.27, sub, ha="center", va="center",
                fontsize=fs - 1.3, color=C_MUTED, zorder=z + 1)
    else:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center",
                fontsize=fs, fontweight="bold" if bold else "normal", color=tc, zorder=z + 1)


def draw_arrow(ax, p1, p2, color="#334155", lw=1.4, ls="-", ms=10, z=6, rad=0.0):
    arr = FancyArrowPatch(
        p1, p2, arrowstyle="-|>,head_length=5,head_width=3",
        color=color, linewidth=lw, linestyle=ls,
        connectionstyle=f"arc3,rad={rad}", zorder=z,
    )
    ax.add_patch(arr)


def draw_wire(ax, pts, color="#334155", lw=1.4, ls="-", z=4):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, linewidth=lw, linestyle=ls, solid_capstyle="round", zorder=z)


def draw_dot(ax, x, y, color="#334155", r=0.075, z=8):
    ax.add_patch(Circle((x, y), r, facecolor=color, edgecolor="none", zorder=z))


def draw_gnd(ax, x, y, s=0.22, color="#334155", lw=1.3, z=6):
    ax.plot([x, x], [y, y - s * 0.6], color=color, lw=lw, zorder=z)
    ax.plot([x - s, x + s], [y - s * 0.6, y - s * 0.6], color=color, lw=lw + 0.2, zorder=z)
    ax.plot([x - s * 0.62, x + s * 0.62], [y - s * 0.95, y - s * 0.95], color=color, lw=lw, zorder=z)
    ax.plot([x - s * 0.28, x + s * 0.28], [y - s * 1.30, y - s * 1.30], color=color, lw=lw, zorder=z)


def draw_vdd(ax, x, y, s=0.24, label="VDD", color="#334155", lw=1.3, fs=7.2, z=6):
    ax.plot([x, x], [y, y + s * 0.65], color=color, lw=lw, zorder=z)
    ax.plot([x - s * 0.7, x + s * 0.7], [y + s * 0.65, y + s * 0.65], color=color, lw=lw + 0.3, zorder=z)
    if label:
        ax.text(x, y + s * 1.15, label, ha="center", va="bottom", fontsize=fs,
                fontweight="bold", color=color, zorder=z)


def draw_res_h(ax, x1, x2, y, amp=0.16, nzig=5, color=C_TEAL, lw=1.5, z=6):
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


def draw_cap_h(ax, x1, x2, y, h=0.38, gap=0.14, color=C_PURPLE, lw=1.7, z=6):
    xm = 0.5 * (x1 + x2)
    ax.plot([x1, xm - gap / 2], [y, y], color=color, lw=1.4, zorder=z)
    ax.plot([xm + gap / 2, x2], [y, y], color=color, lw=1.4, zorder=z)
    ax.plot([xm - gap / 2, xm - gap / 2], [y - h / 2, y + h / 2], color=color, lw=lw + 0.4, zorder=z)
    ax.plot([xm + gap / 2, xm + gap / 2], [y - h / 2, y + h / 2], color=color, lw=lw + 0.4, zorder=z)


def draw_cap_v(ax, x, y1, y2, w=0.40, gap=0.14, color=C_TEAL, lw=1.7, z=6):
    ym = 0.5 * (y1 + y2)
    ax.plot([x, x], [y1, ym - gap / 2], color=color, lw=1.4, zorder=z)
    ax.plot([x, x], [ym + gap / 2, y2], color=color, lw=1.4, zorder=z)
    ax.plot([x - w / 2, x + w / 2], [ym - gap / 2, ym - gap / 2], color=color, lw=lw + 0.4, zorder=z)
    ax.plot([x - w / 2, x + w / 2], [ym + gap / 2, ym + gap / 2], color=color, lw=lw + 0.4, zorder=z)


def draw_inv(ax, x, y, w=0.58, h=0.56, fc="#ffffff", ec="#1e293b", lw=1.5, z=6):
    tri = Polygon(
        [(x, y - h / 2), (x, y + h / 2), (x + w, y)],
        closed=True, facecolor=fc, edgecolor=ec, linewidth=lw, zorder=z,
    )
    ax.add_patch(tri)
    r = h * 0.14
    ax.add_patch(Circle((x + w + r, y), r, facecolor="#ffffff", edgecolor=ec, linewidth=lw, zorder=z + 1))
    return x + w + 2 * r


def draw_tgate(ax, x, y, w=0.56, h=0.42, top_lbl="f", bot_lbl="fb", ec=C_BLUE, fc="#ffffff", fs=7.0, z=6):
    """Standard CMOS transmission gate (two opposing triangles + top/bot control leads)."""
    xm = x + w / 2
    t1 = Polygon([(x, y - h / 2), (x, y + h / 2), (xm, y)], closed=True, facecolor=fc, edgecolor=ec, lw=1.3, zorder=z)
    t2 = Polygon([(x + w, y - h / 2), (x + w, y + h / 2), (xm, y)], closed=True, facecolor=fc, edgecolor=ec, lw=1.3, zorder=z)
    ax.add_patch(t1)
    ax.add_patch(t2)
    # Top bubble (PMOS gate) & bottom lead (NMOS gate)
    r = 0.06
    ax.add_patch(Circle((xm, y + h * 0.38), r, facecolor="#ffffff", edgecolor=ec, lw=1.1, zorder=z + 1))
    ax.plot([xm, xm], [y + h * 0.38 + r, y + h * 0.72], color=ec, lw=1.1, zorder=z)
    ax.plot([xm, xm], [y - h * 0.22, y - h * 0.70], color=ec, lw=1.1, zorder=z)
    if top_lbl:
        ax.text(xm, y + h * 0.80, top_lbl, ha="center", va="bottom", fontsize=fs, fontweight="bold", color=ec, zorder=z + 2)
    if bot_lbl:
        ax.text(xm, y - h * 0.78, bot_lbl, ha="center", va="top", fontsize=fs, fontweight="bold", color=ec, zorder=z + 2)
    return x + w


def draw_mos_cap(ax, x, y, is_pmos=False, color=C_GRAY, z=6):
    """Compact gate-only dummy MOS (S=D tied to VDD or VSS)."""
    # Gate plate
    ax.plot([x - 0.25, x - 0.07], [y, y], color=color, lw=1.2, zorder=z)
    ax.plot([x - 0.07, x - 0.07], [y - 0.22, y + 0.22], color=color, lw=1.5, zorder=z)
    # Channel bar
    ax.plot([x + 0.03, x + 0.03], [y - 0.25, y + 0.25], color=color, lw=1.5, zorder=z)
    if is_pmos:
        ax.add_patch(Circle((x - 0.13, y), 0.055, facecolor="#ffffff", edgecolor=color, lw=1.1, zorder=z + 1))
    # Shorted S/D loop to rail
    ax.plot([x + 0.03, x + 0.28, x + 0.28, x + 0.03], [y + 0.20, y + 0.20, y - 0.20, y - 0.20], color=color, lw=1.2, zorder=z)
    if is_pmos:
        draw_vdd(ax, x + 0.28, y + 0.20, s=0.16, label="VDD", color=color, fs=6.3)
    else:
        draw_gnd(ax, x + 0.28, y - 0.20, s=0.16, color=color)


# ---------------------------------------------------------------------------
# Panel (a): 8-Phase Clock Circle & Glitch-Free Octant Commutation
# ---------------------------------------------------------------------------
def draw_panel_a(ax):
    ax.set_xlim(-2.6, 3.65)
    ax.set_ylim(-2.25, 2.35)
    ax.set_aspect("equal")
    ax.axis("off")

    cx, cy, R = -0.55, 0.05, 1.38
    # Highlight active sector 0 (0 deg -> 45 deg)
    th = np.linspace(0, np.pi / 4, 40)
    wx = np.concatenate([[cx], cx + R * np.cos(th), [cx]])
    wy = np.concatenate([[cy], cy + R * np.sin(th), [cy]])
    ax.fill(wx, wy, color="#fef08a", alpha=0.65, zorder=1)
    # Highlight +90 deg Edge sector (90 deg -> 135 deg)
    th_e = np.linspace(np.pi / 2, 3 * np.pi / 4, 40)
    ax.fill(np.concatenate([[cx], cx + R * np.cos(th_e), [cx]]),
            np.concatenate([[cy], cy + R * np.sin(th_e), [cy]]),
            color=C_ORANGE_BG, alpha=0.80, zorder=1)

    ax.add_patch(Circle((cx, cy), R, facecolor="none", edgecolor="#94a3b8", lw=1.3, ls="--", zorder=2))

    # Draw 8 fine interpolated ticks inside Sector 0 (7.81 ps each)
    for k in range(1, 8):
        ang = (k / 8.0) * (np.pi / 4)
        ax.plot([cx + 0.72 * R * np.cos(ang), cx + R * np.cos(ang)],
                [cy + 0.72 * R * np.sin(ang), cy + R * np.sin(ang)],
                color=C_TEAL, lw=1.1, alpha=0.85, zorder=3)

    # Active interpolated vectors: Data (e.g. code 3 = 16.9 deg) & Edge (+90 deg = 106.9 deg)
    ang_d = (3.5 / 8.0) * (np.pi / 4)
    draw_arrow(ax, (cx, cy), (cx + 1.03 * R * np.cos(ang_d), cy + 1.03 * R * np.sin(ang_d)),
               color=C_TEAL, lw=2.3, z=7)
    ax.text(cx + 0.62 * R * np.cos(ang_d) + 0.14, cy + 0.62 * R * np.sin(ang_d) - 0.12,
            "Data dp\n(φ)", fontsize=7.6, fontweight="bold", color=C_TEAL, ha="left", va="center", zorder=8)

    ang_e = ang_d + np.pi / 2
    draw_arrow(ax, (cx, cy), (cx + 1.03 * R * np.cos(ang_e), cy + 1.03 * R * np.sin(ang_e)),
               color=C_ORANGE, lw=2.1, ls="--", z=7)
    ax.text(cx + 0.64 * R * np.cos(ang_e) - 0.08, cy + 0.64 * R * np.sin(ang_e) + 0.12,
            "Edge ep\n(φ+90°)", fontsize=7.4, fontweight="bold", color=C_ORANGE, ha="right", va="center", zorder=8)

    # 8 anchor phases
    for k in range(8):
        ang = k * (np.pi / 4)
        is_even = (k % 2 == 0)
        col = C_BLUE if is_even else C_ORANGE
        px, py = cx + R * np.cos(ang), cy + R * np.sin(ang)
        ax.plot([cx, px], [cy, py], color=col, lw=1.1, alpha=0.45, zorder=3)
        ax.add_patch(Circle((px, py), 0.11, facecolor="#ffffff", edgecolor=col, lw=2.0, zorder=6))
        lx, ly = cx + (R + 0.36) * np.cos(ang), cy + (R + 0.36) * np.sin(ang)
        tag = f"c{k}\n{k*45}°"
        ax.text(lx, ly, tag, ha="center", va="center", fontsize=7.5, fontweight="bold", color=col, zorder=7)

    # Right side explanatory callout card (Glitch-free Even/Odd Commutation)
    bx, by, bw, bh = 1.25, -2.08, 2.35, 4.18
    ax.add_patch(FancyBboxPatch((bx, by), bw, bh, boxstyle="round,pad=0.06,rounding_size=0.14",
                                facecolor="#ffffff", edgecolor=C_BORDER, lw=1.2, zorder=3))
    ax.text(bx + bw / 2, by + bh - 0.18, "Glitch-Free 64-Code Rule", ha="center", va="top",
            fontsize=8.6, fontweight="bold", color=C_TEXT, zorder=4)
    rules = [
        ("● Even Bank A (4:1 Mux)", "c0, c2, c4, c6 via a0,a2,a4,a6", C_BLUE),
        ("● Odd Bank B (4:1 Mux)", "c1, c3, c5, c7 via b1,b3,b5,b7", C_ORANGE),
        ("● 8 Fine Steps / Sector", "8 × 8 = 64 codes / 2 GHz cycle\nStep = 62.5 / 8 = 7.81 ps (1/32 UI)", C_TEAL),
        ("● Zero-Glitch Handoff", "At f = 8'hFF (100% on B=c1):\nA carries 0 weight -> silently\nswitches c0 -> c2, then f\ncounts down 8 -> 0!", C_PURPLE),
        ("● Built-In +90° Edge PI", "Same a/b/f, inputs rotated +2\n(c2..c1) -> exact 0.5 UI edge!", C_GREEN),
    ]
    yy = by + bh - 0.52
    for hdr, body, col in rules:
        ax.text(bx + 0.10, yy, hdr, ha="left", va="top", fontsize=7.4, fontweight="bold", color=col, zorder=5)
        ax.text(bx + 0.14, yy - 0.21, body, ha="left", va="top", fontsize=6.7, color=C_MUTED, linespacing=1.24, zorder=5)
        n_lines = body.count("\n") + 1
        yy -= 0.24 + n_lines * 0.22 + 0.14

    ax.set_title("(a) 2 GHz 8-Phase Anchor Circle & Glitch-Free Commutation",
                 fontsize=10.2, fontweight="bold", color=C_TEXT, pad=8, loc="left")


# ---------------------------------------------------------------------------
# Panel (b): Full 5-Stage Block Diagram (serdes_rx_cmos_pi_8ph)
# ---------------------------------------------------------------------------
def draw_panel_b(ax):
    ax.set_xlim(0.0, 12.6)
    ax.set_ylim(-0.3, 5.2)
    ax.axis("off")

    # Data Channel dashed container (top half)
    ax.add_patch(FancyBboxPatch((1.85, 1.55), 7.65, 3.25, boxstyle="round,pad=0.06,rounding_size=0.16",
                                facecolor="#eff6ff", edgecolor=C_BLUE, lw=1.2, ls="--", zorder=1))
    ax.text(2.05, 4.62, "Data PI Channel (`Xch_d` -> 0° / 180° : dp, dn)", fontsize=8.4,
            fontweight="bold", color=C_BLUE, ha="left", va="center", zorder=2)

    # Edge Channel compact parallel container (bottom)
    ax.add_patch(FancyBboxPatch((1.85, 0.12), 7.65, 1.15, boxstyle="round,pad=0.06,rounding_size=0.16",
                                facecolor="#fff7ed", edgecolor=C_ORANGE, lw=1.2, ls="--", zorder=1))
    ax.text(2.05, 1.07, "Edge PI Channel (Xch_e -> +90°/+270°: ep, en) — Same Circuit, Inputs +90°",
            fontsize=7.5, fontweight="bold", color=C_ORANGE, ha="left", va="center", zorder=2)
    draw_box(ax, 2.05, 0.26, 1.95, 0.58, "4:1 LVT TG Muxes", fc="#ffffff", ec=C_ORANGE, tc=C_ORANGE, fs=7.5,
             sub="E:{c2,4,6,0} O:{c3,5,7,1}")
    draw_box(ax, 4.35, 0.26, 2.25, 0.58, "8-Slice R-Linear Mixer", fc="#ffffff", ec=C_TEAL, tc=C_TEAL, fs=7.5,
             sub="Same f[7:0], C_mim=37 fF")
    draw_box(ax, 6.95, 0.26, 2.35, 0.58, "AC Self-Biased Rec + Buf", fc="#ffffff", ec=C_PURPLE, tc=C_PURPLE, fs=7.5,
             sub="50% duty -> ep, en (2 GHz)")
    draw_arrow(ax, (4.00, 0.55), (4.35, 0.55), color=C_ORANGE, lw=1.3)
    draw_arrow(ax, (6.60, 0.55), (6.95, 0.55), color=C_TEAL, lw=1.3)

    # Stage 0: Shared 2 GHz Input Buffers
    draw_box(ax, 0.15, 1.40, 1.30, 2.60, "Shared\n2 GHz\nBuffers", fc=C_GRAY_BG, ec="#475569", fs=8.0,
             sub="8× pi_inv_lvt\n1.6 / 6.4 µm")
    ax.text(0.80, 4.22, "From PLL\nc0..c7 (45°)", ha="center", va="bottom", fontsize=7.6, fontweight="bold", color=C_TEXT)
    draw_arrow(ax, (0.80, 4.20), (0.80, 4.00), color=C_TEXT, lw=1.3)

    # Fanout from Shared Buffers to Data & Edge channels
    draw_wire(ax, [(1.45, 3.65), (2.05, 3.65)], color=C_BLUE, lw=1.4)
    draw_wire(ax, [(1.45, 2.55), (2.05, 2.55)], color=C_ORANGE, lw=1.4)
    draw_wire(ax, [(1.68, 3.65), (1.68, 0.55), (2.05, 0.55)], color=C_GRAY, lw=1.2, ls=":")
    draw_dot(ax, 1.68, 3.65, color=C_GRAY, r=0.055)

    # Stage 1: Coarse 4:1 Muxes inside Data Channel
    draw_box(ax, 2.05, 3.22, 1.95, 1.05, "Even 4:1 TG Mux", fc=C_BLUE_BG, ec=C_BLUE, tc=C_BLUE, fs=8.0,
             sub="c0,c2,c4,c6 -> cap/can\n(a0,a2,a4,a6 one-hot)")
    draw_box(ax, 2.05, 1.88, 1.95, 1.05, "Odd 4:1 TG Mux", fc=C_ORANGE_BG, ec=C_ORANGE, tc=C_ORANGE, fs=8.0,
             sub="c1,c3,c5,c7 -> cbp/cbn\n(b1,b3,b5,b7 one-hot)")

    # Stage 2: 8-Slice Resistor-Linearized Phase Mixer
    draw_box(ax, 4.35, 2.12, 2.25, 1.95, "8-Slice Resistor\nPhase Mixer\n(`pi_mixer8` ×2)", fc=C_TEAL_BG, ec=C_TEAL, tc=C_TEAL, fs=8.1,
             sub="8× R=5.8 kΩ + C_mim=37 fF\nτ_mix ≈ 43 ps (0.00 ps bow)")
    draw_arrow(ax, (4.00, 3.74), (4.35, 3.55), color=C_BLUE, lw=1.5)
    draw_arrow(ax, (4.00, 2.40), (4.35, 2.65), color=C_ORANGE, lw=1.5)
    ax.text(4.16, 3.92, "ca", fontsize=7.3, fontweight="bold", color=C_BLUE, ha="center")
    ax.text(4.16, 2.15, "cb", fontsize=7.3, fontweight="bold", color=C_ORANGE, ha="center")

    # Digital control arrow entering from top
    ax.text(5.48, 5.02, "CDR Digital Controls: a[0,2,4,6], b[1,3,5,7], f[7:0] (static DC, 0 µW switching)",
            ha="center", va="center", fontsize=7.8, fontweight="bold", color=C_RED,
            bbox=dict(boxstyle="round,pad=0.22", fc="#fff1f2", ec=C_RED, lw=0.9))
    draw_arrow(ax, (3.02, 4.82), (3.02, 4.28), color=C_RED, lw=1.2)
    draw_arrow(ax, (5.48, 4.82), (5.48, 4.08), color=C_RED, lw=1.2)

    # Stage 3: AC-Coupled Self-Biased Recovery + Output Buffer
    draw_box(ax, 6.95, 2.12, 2.35, 1.95, "AC Self-Biased\nLVT Recovery\n+ Output Buf", fc=C_PURPLE_BG, ec=C_PURPLE, tc=C_PURPLE, fs=8.1,
             sub="37 fF MIM + 12.3 kΩ R_fb\nAuto V_M=VDD/2, 50% duty")
    draw_arrow(ax, (6.60, 3.10), (6.95, 3.10), color=C_TEAL, lw=1.6)
    ax.text(6.77, 3.30, "mixp\nmixn", fontsize=6.8, fontweight="bold", color=C_TEAL, ha="center", va="bottom")

    # Stage 4: Deterministic 8-Phase 1 GHz Quadrature /2
    draw_box(ax, 9.90, 0.40, 2.52, 3.65, "Deterministic\nQuadrature ÷2\n(qdiv2_8ph)", fc=C_GREEN_BG, ec=C_GREEN, tc=C_GREEN, fs=8.3,
             sub="Master Johnson ÷2 (dp/dn)\n+ Resample Latches (ep/en)\nZero 180° Ambiguity!")
    draw_arrow(ax, (9.30, 3.10), (9.90, 3.10), color=C_BLUE, lw=1.7)
    ax.text(9.60, 3.26, "dp,dn\n2 GHz", fontsize=6.8, fontweight="bold", color=C_BLUE, ha="center")
    draw_arrow(ax, (9.30, 0.55), (9.90, 0.85), color=C_ORANGE, lw=1.7)
    ax.text(9.62, 0.30, "ep,en\n2 GHz", fontsize=6.8, fontweight="bold", color=C_ORANGE, ha="center", va="top")

    # Final 8-phase 1 GHz outputs
    ax.text(11.16, 4.30, "To 8× Double-Tail Slicers:\nckd0..3 (Data 0/90/180/270°)\ncke0..3 (Edge 45/135/225/315°)\n1.000 GHz · ~7 mW Total",
            ha="center", va="bottom", fontsize=7.0, fontweight="bold", color=C_GREEN,
            bbox=dict(boxstyle="round,pad=0.20", fc="#f0fdf4", ec=C_GREEN, lw=0.9))
    draw_arrow(ax, (11.16, 4.05), (11.16, 4.28), color=C_GREEN, lw=1.5)

    ax.set_title("(b) End-to-End 5-Stage Signal Flow (serdes_rx_cmos_pi_8ph, ~7 mW @ TT, |INL| ≤ 0.015 UI)",
                 fontsize=10.2, fontweight="bold", color=C_TEXT, pad=8, loc="left")


# ---------------------------------------------------------------------------
# Panel (c): Transistor-Level Core Schematic (pi_slice_r + pi_mixer8 + pi_ac_rec)
# ---------------------------------------------------------------------------
def draw_panel_c(ax):
    ax.set_xlim(0.0, 12.6)
    ax.set_ylim(-0.20, 5.20)
    ax.axis("off")

    # Left Sub-box: Single Resistor-Linearized Mixer Slice (x8)
    ax.add_patch(FancyBboxPatch((0.10, 0.12), 6.25, 4.82, boxstyle="round,pad=0.05,rounding_size=0.16",
                                facecolor="#ffffff", edgecolor=C_TEAL, lw=1.3, zorder=1))
    ax.text(3.22, 4.74, "1 of 8 Mixer Slices (pi_slice_r ×8) → Node mix",
            fontsize=8.0, fontweight="bold", color=C_TEAL, ha="center", va="center", zorder=2)

    # Active Path highlight
    ax.add_patch(FancyBboxPatch((0.28, 2.30), 5.05, 2.15, boxstyle="round,pad=0.04,rounding_size=0.12",
                                facecolor="#f0fdfa", edgecolor="#99f6e4", lw=1.0, zorder=2))
    ax.text(0.40, 4.28, "Active Weighting Leg (f=0 → ca, f=1 → cb)",
            fontsize=7.2, fontweight="bold", color=C_TEAL, ha="left", va="center", zorder=3)

    # ca & cb input buses on left
    ax.text(0.46, 3.68, "ca", fontsize=8.0, fontweight="bold", color=C_BLUE, ha="right", va="center")
    ax.text(0.46, 2.84, "cb", fontsize=8.0, fontweight="bold", color=C_ORANGE, ha="right", va="center")
    draw_wire(ax, [(0.52, 3.68), (1.12, 3.68)], color=C_BLUE, lw=1.6)
    draw_wire(ax, [(0.52, 2.84), (1.12, 2.84)], color=C_ORANGE, lw=1.6)
    draw_dot(ax, 0.76, 3.68, color=C_BLUE, r=0.055)
    draw_dot(ax, 0.94, 2.84, color=C_ORANGE, r=0.055)
    draw_wire(ax, [(0.76, 3.68), (0.76, 1.48), (1.12, 1.48)], color=C_BLUE, lw=1.1, ls="--")
    draw_wire(ax, [(0.94, 2.84), (0.94, 0.72), (1.12, 0.72)], color=C_ORANGE, lw=1.1, ls="--")

    # Active 2:1 LVT TG mux
    x_end1 = draw_tgate(ax, 1.12, 3.68, w=0.56, h=0.36, top_lbl="f", bot_lbl="fb", ec=C_BLUE, fc="#eff6ff", fs=6.6)
    x_end2 = draw_tgate(ax, 1.12, 2.84, w=0.56, h=0.36, top_lbl="fb", bot_lbl="f", ec=C_ORANGE, fc="#fff7ed", fs=6.6)
    draw_wire(ax, [(x_end1, 3.68), (1.96, 3.68), (1.96, 2.84), (x_end2, 2.84)], color="#334155", lw=1.4)
    draw_dot(ax, 1.96, 3.26, color="#334155", r=0.055)
    draw_wire(ax, [(1.96, 3.26), (2.42, 3.26)], color="#334155", lw=1.5)
    ax.text(2.19, 3.42, "sel", fontsize=6.8, color=C_MUTED, ha="center")

    # Lean LVT CMOS Inverter (0.42/1.70 um)
    x_inv_out = draw_inv(ax, 2.42, 3.26, w=0.60, h=0.58, fc="#ffffff", ec=C_TEAL, lw=1.6)
    ax.text(2.74, 2.78, "Lean Inv\n0.42/1.70µm", fontsize=6.4, color=C_TEAL, ha="center", va="top")

    # Summing resistor high_po_0p69 (5.8 kOhm)
    draw_wire(ax, [(x_inv_out, 3.26), (3.42, 3.26)], color=C_TEAL, lw=1.5)
    ax.text(3.32, 3.44, "drv", fontsize=6.6, color=C_MUTED, ha="center")
    draw_res_h(ax, 3.42, 4.78, 3.26, amp=0.16, nzig=5, color=C_TEAL, lw=1.7)
    ax.text(4.10, 3.55, "R_sum = 5.8 kΩ", fontsize=7.0, fontweight="bold", color=C_TEAL, ha="center")
    ax.text(4.10, 2.92, "(high_po_0p69,\nlinearizes I)", fontsize=6.3, color=C_MUTED, ha="center", va="top")

    # Shared summing node `mix` + 7 other parallel slices + C_mim = 37 fF
    draw_wire(ax, [(4.78, 3.26), (6.58, 3.26)], color=C_TEAL, lw=2.0)
    draw_dot(ax, 5.75, 3.26, color=C_TEAL, r=0.08)
    ax.text(5.75, 3.50, "mix", fontsize=8.0, fontweight="bold", color=C_TEAL, ha="center")
    for dy in (0.45, 0.72):
        draw_wire(ax, [(5.35, 3.26 + dy), (5.75, 3.26)], color=C_TEAL, lw=1.0, ls=":")
    ax.text(5.75, 4.22, "×8 slices\n(k on B,\n8−k on A)", fontsize=6.5, fontweight="bold", color=C_TEAL, ha="center", va="center",
            bbox=dict(boxstyle="round,pad=0.14", fc="#ffffff", ec=C_TEAL, lw=0.8))

    # C_mim = 37 fF to GND at `mix`
    draw_wire(ax, [(5.75, 3.26), (5.75, 2.38)], color=C_TEAL, lw=1.5)
    draw_cap_v(ax, 5.75, 1.48, 2.38, w=0.44, gap=0.14, color=C_TEAL, lw=1.8)
    draw_gnd(ax, 5.75, 1.48, s=0.19, color=C_TEAL)
    ax.text(5.75, 0.92, "C_mim\n37 fF\nτ≈43 ps", fontsize=6.6, fontweight="bold", color=C_TEAL, ha="center", va="top")

    # Passive Constant-Load Dummy sub-box
    ax.add_patch(FancyBboxPatch((0.28, 0.22), 4.78, 1.94, boxstyle="round,pad=0.04,rounding_size=0.12",
                                facecolor=C_GRAY_BG, edgecolor="#cbd5e1", lw=1.0, ls="--", zorder=2))
    ax.text(0.40, 2.02, "Passive Dummy (Opposite f/fb → 0.00 ps Bow)",
            fontsize=6.9, fontweight="bold", color=C_GRAY, ha="left", va="center", zorder=3)
    xd1 = draw_tgate(ax, 1.12, 1.44, w=0.56, h=0.32, top_lbl="fb", bot_lbl="", ec=C_GRAY, fc="#ffffff", fs=6.2)
    xd2 = draw_tgate(ax, 1.12, 0.72, w=0.56, h=0.32, top_lbl="", bot_lbl="f", ec=C_GRAY, fc="#ffffff", fs=6.2)
    draw_wire(ax, [(xd1, 1.44), (1.96, 1.44), (1.96, 0.72), (xd2, 0.72)], color=C_GRAY, lw=1.2)
    draw_dot(ax, 1.96, 1.08, color=C_GRAY, r=0.05)
    draw_wire(ax, [(1.96, 1.08), (2.48, 1.08)], color=C_GRAY, lw=1.2)
    draw_wire(ax, [(2.48, 1.34), (2.48, 0.80)], color=C_GRAY, lw=1.2)
    draw_mos_cap(ax, 2.74, 1.34, is_pmos=True, color=C_GRAY)
    draw_mos_cap(ax, 2.74, 0.80, is_pmos=False, color=C_GRAY)
    ax.text(3.28, 1.08, "Gate-cap only\n(S=D tied to rail)\nKeeps C(ca)=C(cb)\nfor ALL codes!",
            fontsize=6.4, color=C_MUTED, ha="left", va="center")

    # Right Sub-box: Zero-Static-DC AC-Coupled Self-Biased LVT Recovery + Output Buf
    ax.add_patch(FancyBboxPatch((6.60, 0.12), 5.90, 4.82, boxstyle="round,pad=0.05,rounding_size=0.16",
                                facecolor="#ffffff", edgecolor=C_PURPLE, lw=1.3, zorder=1))
    ax.text(9.55, 4.74, "AC Self-Biased LVT Recovery (pi_ac_rec) + Buf",
            fontsize=8.0, fontweight="bold", color=C_PURPLE, ha="center", va="center", zorder=2)

    # Signal line mix -> C_ac -> acp -> Inv_lvt -> r1p -> Output Inv -> dp
    draw_wire(ax, [(6.58, 3.26), (7.02, 3.26)], color=C_TEAL, lw=2.0)
    draw_cap_h(ax, 7.02, 7.92, 3.26, h=0.52, gap=0.15, color=C_PURPLE, lw=1.9)
    ax.text(7.47, 3.66, "C_ac = 37 fF", fontsize=7.1, fontweight="bold", color=C_PURPLE, ha="center")
    ax.text(7.47, 2.86, "(MIM1 blocks\nDC offset)", fontsize=6.3, color=C_MUTED, ha="center", va="top")

    draw_wire(ax, [(7.92, 3.26), (8.62, 3.26)], color=C_PURPLE, lw=1.6)
    draw_dot(ax, 8.26, 3.26, color=C_PURPLE, r=0.065)
    ax.text(8.26, 3.00, "acp", fontsize=7.0, fontweight="bold", color=C_PURPLE, ha="center")

    x_rec_out = draw_inv(ax, 8.62, 3.26, w=0.68, h=0.68, fc=C_PURPLE_BG, ec=C_PURPLE, lw=1.7)
    ax.text(8.98, 2.78, "LVT Inv\n1.65/6.60µm", fontsize=6.5, fontweight="bold", color=C_PURPLE, ha="center", va="top")

    draw_wire(ax, [(x_rec_out, 3.26), (10.22, 3.26)], color=C_PURPLE, lw=1.6)
    draw_dot(ax, 9.82, 3.26, color=C_PURPLE, r=0.065)
    ax.text(9.82, 3.00, "r1p", fontsize=7.0, fontweight="bold", color=C_PURPLE, ha="center")

    # Negative DC feedback resistor R_fb = 12.3 kOhm above LVT inverter
    draw_wire(ax, [(8.26, 3.26), (8.26, 4.14), (8.48, 4.14)], color=C_RED, lw=1.4)
    draw_res_h(ax, 8.48, 9.62, 4.14, amp=0.13, nzig=5, color=C_RED, lw=1.5)
    draw_wire(ax, [(9.62, 4.14), (9.82, 4.14), (9.82, 3.26)], color=C_RED, lw=1.4)
    ax.text(9.06, 4.38, "R_fb = 12.3 kΩ (Negative DC Feedback)", fontsize=6.9, fontweight="bold", color=C_RED, ha="center")

    # Output buffer (matched Wp/Wn = 4.00)
    x_buf_out = draw_inv(ax, 10.22, 3.26, w=0.68, h=0.68, fc=C_BLUE_BG, ec=C_BLUE, lw=1.7)
    ax.text(10.58, 2.78, "Out LVT Buf\n2.66/10.64µm", fontsize=6.5, fontweight="bold", color=C_BLUE, ha="center", va="top")
    draw_arrow(ax, (x_buf_out, 3.26), (12.32, 3.26), color=C_BLUE, lw=1.9)
    ax.text(11.82, 3.46, "dp / dn\n(2 GHz)", fontsize=7.4, fontweight="bold", color=C_BLUE, ha="center", va="bottom")

    # Why AC self-biased recovery works (strictly inside right sub-box!)
    ax.add_patch(FancyBboxPatch((6.82, 0.25), 5.46, 1.92, boxstyle="round,pad=0.05,rounding_size=0.12",
                                facecolor="#faf5ff", edgecolor="#d8b4fe", lw=1.0, zorder=2))
    ax.text(6.98, 2.00, "Why This Beats CML or Cross-Coupled Latches:",
            fontsize=7.3, fontweight="bold", color=C_PURPLE, ha="left", va="center", zorder=3)
    pts_c = [
        "1. R_fb self-biases acp at V_M = VDD/2 (~0.34 ns)",
        "   → 50.0% duty across ALL PVT (even SS −40 °C).",
        "2. Matched Wp/Wn = 4.00 LVT-PMOS (l=0.35) + LVT-NMOS",
        "   avoids high-Vthp dead zone with 0 mA tail bias.",
        "3. High R_sum (5.8 kΩ >> R_on) keeps phase mixing",
        "   linear → |INL| ≤ 0.015 UI, ~7 mW total PI power.",
    ]
    yy = 1.76
    for line in pts_c:
        ax.text(6.98, yy, line, fontsize=6.5, color=C_TEXT, ha="left", va="top", zorder=3)
        yy -= 0.245

    ax.set_title("(c) Transistor-Level Core: Constant-Load R-Linearized Slice & Self-Biased AC Recovery",
                 fontsize=10.2, fontweight="bold", color=C_TEXT, pad=8, loc="left")


# ---------------------------------------------------------------------------
# Panel (d): Waveform Intuition (Linear RC Interpolation + Deterministic QDiv2)
# ---------------------------------------------------------------------------
def draw_panel_d(ax):
    ax.set_xlim(0.0, 12.6)
    ax.set_ylim(-0.35, 5.25)
    ax.axis("off")

    # Top half: Intuitive RC-Summed Waveform Interpolation (k = 0, 2, 4, 6, 8)
    ax.add_patch(FancyBboxPatch((0.15, 2.35), 12.30, 2.55, boxstyle="round,pad=0.05,rounding_size=0.14",
                                facecolor="#ffffff", edgecolor=C_BORDER, lw=1.1, zorder=1))
    ax.text(0.35, 4.72, "1. How 8 Resistor Slices Linearly Interpolate Phase (Sector 0: ca = 0°, cb = 45° = 62.5 ps)",
            fontsize=8.3, fontweight="bold", color=C_TEXT, ha="left", va="center", zorder=2)

    # Embedded coordinate box for waveform inside [0.75..7.6] x [2.62..4.42]
    x0, x1, y0, y1 = 0.85, 7.35, 2.68, 4.35
    ax.plot([x0, x1], [y0, y0], color="#94a3b8", lw=0.9, zorder=2)
    ax.plot([x0, x0], [y0, y1], color="#94a3b8", lw=0.9, zorder=2)
    ym = 0.5 * (y0 + y1)
    ax.plot([x0, x1], [ym, ym], color=C_RED, lw=1.1, ls="--", zorder=3)
    ax.text(x1 + 0.08, ym, "V_M = VDD/2\n(AC slicer)", fontsize=6.9, fontweight="bold", color=C_RED, ha="left", va="center")
    ax.text(x0 - 0.08, y1, "1.8V", fontsize=6.6, color=C_MUTED, ha="right", va="center")
    ax.text(x0 - 0.08, y0, "0V", fontsize=6.6, color=C_MUTED, ha="right", va="center")

    # Analytical RC-filtered step response of weighted sum of ca (t=0) and cb (t=62.5 ps)
    t_ps = np.linspace(-35.0, 220.0, 400)
    tau = 43.0
    def rc_step(t, t_edge):
        u = np.clip(t - t_edge, 0.0, None)
        return 1.0 - np.exp(-u / tau)

    # Ideal input edges ca (0 ps) & cb (62.5 ps) shown as crisp square ramps
    t_to_x = lambda tp: x0 + (tp + 35.0) / 255.0 * (x1 - x0)
    v_to_y = lambda v: y0 + v * (y1 - y0)

    ca_sq = np.clip((t_ps - 0.0) / 14.0, 0.0, 1.0)
    cb_sq = np.clip((t_ps - 62.5) / 14.0, 0.0, 1.0)
    ax.plot(t_to_x(t_ps), v_to_y(ca_sq), color=C_BLUE, lw=1.7, ls=":", alpha=0.85, zorder=3)
    ax.plot(t_to_x(t_ps), v_to_y(cb_sq), color=C_ORANGE, lw=1.7, ls=":", alpha=0.85, zorder=3)
    ax.text(t_to_x(5.0), y1 + 0.05, "ca (0°)", fontsize=7.0, fontweight="bold", color=C_BLUE, ha="center")
    ax.text(t_to_x(67.5), y1 + 0.05, "cb (45°)", fontsize=7.0, fontweight="bold", color=C_ORANGE, ha="center")

    # 5 interpolated RC-summed mix curves for k = 0, 2, 4, 6, 8
    colors_k = [C_BLUE, "#0284c7", C_TEAL, "#d97706", C_ORANGE]
    cross_xs = []
    for idx, k in enumerate((0, 2, 4, 6, 8)):
        w_b = k / 8.0
        vmix = (1.0 - w_b) * rc_step(t_ps, 0.0) + w_b * rc_step(t_ps, 62.5)
        ax.plot(t_to_x(t_ps), v_to_y(vmix), color=colors_k[idx], lw=1.8 if k == 4 else 1.4, zorder=4)
        # Find VDD/2 crossing
        ic = int(np.argmin(np.abs(vmix - 0.5)))
        cx_k = t_to_x(t_ps[ic])
        cross_xs.append(cx_k)
        ax.add_patch(Circle((cx_k, ym), 0.065, facecolor=colors_k[idx], edgecolor="#ffffff", lw=0.8, zorder=7))

    # Annotate equal 7.81 ps spacing
    ax.annotate("", xy=(cross_xs[-1], y0 - 0.14), xytext=(cross_xs[0], y0 - 0.14),
                arrowprops=dict(arrowstyle="<->", color=C_TEAL, lw=1.3))
    ax.text(0.5 * (cross_xs[0] + cross_xs[-1]), y0 - 0.22,
            "k = 0..8 spans 62.5 ps (8 equal 7.81 ps steps)", fontsize=7.0, fontweight="bold", color=C_TEAL, ha="center", va="top")

    # Right summary inside waveform box
    ax.text(8.85, 4.18, "Why τ_mix ≈ 43 ps Matters:", fontsize=7.8, fontweight="bold", color=C_TEAL, ha="left", va="top")
    wf_notes = [
        "• Too small τ (fast edge):",
        "  staircase plateau -> bad DNL!",
        "• Too large τ (slow edge):",
        "  2 GHz amplitude collapses!",
        "• τ ≈ 0.7 × 62.5 ps ≈ 43 ps:",
        "  smooth ramp overlaps ca & cb",
        "  -> linear crossing @ VDD/2!",
    ]
    yy = 3.88
    for line in wf_notes:
        ax.text(8.85, yy, line, fontsize=6.9, color=C_TEXT if line.startswith("•") else C_MUTED,
                fontweight="bold" if line.startswith("•") else "normal", ha="left", va="top")
        yy -= 0.22

    # Bottom half: Deterministic Quadrature /2 (`serdes_rx_qdiv2_8ph`)
    ax.add_patch(FancyBboxPatch((0.15, 0.08), 12.30, 2.08, boxstyle="round,pad=0.05,rounding_size=0.14",
                                facecolor="#f0fdf4", edgecolor=C_GREEN, lw=1.2, zorder=1))
    ax.text(0.35, 1.96, "2. Deterministic Quadrature ÷2 (`serdes_rx_qdiv2_8ph`): How It Guarantees Zero 180° Data/Edge Swap",
            fontsize=8.3, fontweight="bold", color=C_GREEN, ha="left", va="center", zorder=2)

    # Master Johnson /2 (Xld0 <-> Xld1 clocked by dp/dn)
    draw_box(ax, 0.55, 0.92, 1.55, 0.72, "Latch Xld0", fc=C_BLUE_BG, ec=C_BLUE, tc=C_BLUE, fs=7.6, sub="ck = dp/dn")
    draw_box(ax, 2.65, 0.92, 1.55, 0.72, "Latch Xld1", fc=C_BLUE_BG, ec=C_BLUE, tc=C_BLUE, fs=7.6, sub="ck = dn/dp")
    draw_arrow(ax, (2.10, 1.28), (2.65, 1.28), color=C_BLUE, lw=1.5)
    ax.text(2.38, 1.42, "d0/d2", fontsize=6.7, fontweight="bold", color=C_BLUE, ha="center")
    # Feedback inverted loop below Xld0/Xld1
    draw_wire(ax, [(4.20, 1.28), (4.55, 1.28), (4.55, 0.56), (0.32, 0.56), (0.32, 1.28)], color=C_BLUE, lw=1.3)
    draw_arrow(ax, (0.32, 1.28), (0.55, 1.28), color=C_BLUE, lw=1.3)
    ax.text(2.44, 0.44, "Inverted Johnson ÷2 feedback (d3, d1)\n→ 1 GHz ckd0..3 (0°/90°/180°/270°)",
            fontsize=6.5, color=C_BLUE, ha="center", va="top", fontweight="bold")

    # Resampling Latches (Xle0, Xle1 clocked by ep/en)
    draw_box(ax, 5.55, 1.05, 1.95, 0.62, "Resample Xle0", fc=C_ORANGE_BG, ec=C_ORANGE, tc=C_ORANGE, fs=7.5, sub="D=d0/d2, ck=ep/en")
    draw_box(ax, 5.55, 0.24, 1.95, 0.62, "Resample Xle1", fc=C_ORANGE_BG, ec=C_ORANGE, tc=C_ORANGE, fs=7.5, sub="D=d1/d3, ck=en/ep")
    draw_dot(ax, 2.38, 1.28, color=C_BLUE, r=0.055)
    draw_wire(ax, [(2.38, 1.28), (2.38, 1.75), (5.05, 1.75), (5.05, 1.36)], color=C_BLUE, lw=1.2, ls="--")
    draw_arrow(ax, (5.05, 1.36), (5.55, 1.36), color=C_BLUE, lw=1.3)
    draw_dot(ax, 4.55, 0.55, color=C_BLUE, r=0.055)
    draw_arrow(ax, (4.55, 0.55), (5.55, 0.55), color=C_BLUE, lw=1.3)

    # Output buffers & key insight on right
    draw_arrow(ax, (7.50, 1.36), (8.25, 1.36), color=C_ORANGE, lw=1.5)
    draw_arrow(ax, (7.50, 0.55), (8.25, 0.55), color=C_ORANGE, lw=1.5)
    ax.text(7.88, 1.48, "e0/e2", fontsize=6.7, fontweight="bold", color=C_ORANGE, ha="center")
    ax.text(7.88, 0.67, "e1/e3", fontsize=6.7, fontweight="bold", color=C_ORANGE, ha="center")

    ax.add_patch(FancyBboxPatch((8.28, 0.24), 3.95, 1.45, boxstyle="round,pad=0.05,rounding_size=0.12",
                                facecolor="#ffffff", edgecolor=C_GREEN, lw=1.1, zorder=3))
    ax.text(8.42, 1.50, "Why Resample Instead of 2nd ÷2?", fontsize=7.5, fontweight="bold", color=C_GREEN, ha="left", va="center", zorder=4)
    ax.text(8.42, 1.28,
            "• Two independent ÷2 dividers can wake\n"
            "  up 180° out of phase after reset!\n"
            "• Sampling master d0..d3 with ep/en\n"
            "  forces cke0..3 to trail ckd0..3 by\n"
            "  EXACTLY +45° (125 ps = 0.5 UI)!",
            fontsize=6.7, color=C_TEXT, ha="left", va="top", linespacing=1.25, zorder=4)

    ax.set_title("(d) Working Principle: Linear RC Phase Mixing & Ambiguity-Free 8-Phase 1 GHz Division",
                 fontsize=10.2, fontweight="bold", color=C_TEXT, pad=6, loc="left")


def main() -> None:
    fig = plt.figure(figsize=(19.2, 11.8), dpi=240, facecolor=C_BG)
    gs = fig.add_gridspec(2, 2, width_ratios=[1.05, 1.05], height_ratios=[1.0, 1.04],
                          left=0.02, right=0.985, top=0.895, bottom=0.025, wspace=0.075, hspace=0.16)

    ax_a = fig.add_subplot(gs[0, 0])
    ax_b = fig.add_subplot(gs[0, 1])
    ax_c = fig.add_subplot(gs[1, 0])
    ax_d = fig.add_subplot(gs[1, 1])

    draw_panel_a(ax_a)
    draw_panel_b(ax_b)
    draw_panel_c(ax_c)
    draw_panel_d(ax_d)

    fig.suptitle(
        "SKY130A 4 Gb/s NRZ SerDes — RX 2 GHz 64-Code Pure CMOS Phase Interpolator & Deterministic 1 GHz QDiv2 (`rx_cmos_pi.spice`)",
        fontsize=13.5, fontweight="bold", color=C_TEXT, y=0.968,
    )
    fig.text(
        0.5, 0.938,
        "Zero CML · Zero Static Tail Current (~7 mW @ TT) · 100% Real SKY130 MOS / high_po R / MIM1 · |INL| ≤ 0.015 UI across PVT · 0°/180° Ambiguity-Free",
        ha="center", va="center", fontsize=9.8, color=C_MUTED,
    )

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=240, facecolor=C_BG)
    plt.close(fig)
    print(f"[plot_rx_pi_schematic] Saved {OUT_PNG} ({OUT_PNG.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
