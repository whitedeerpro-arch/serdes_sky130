#!/usr/bin/env python3
"""True 1:1 SKY130 PDK-Scale Architectural Floorplan Sketch for Bandgap & Bias Suite.

Draws a ``bias_layout_suite_overview``-style floorplan blueprint using exact measured
SKY130 PDK primitive bounding boxes (``sky130_fd_pr__*``) BEFORE writing Magic routing:
  - True ``w=1.0 um`` ``res_high_po_0p35`` bar lengths and pitches
  - True ``L=12 um``, ``L=8 um``, ``L=5 um``, ``L=4 um`` MOSFET gate & active footprints
  - True ``6.70 x 6.70 um`` ``pnp_05v5_W3p40L3p40`` cells
  - True ``22.2 x 22.2 um`` ``cap_mim_m3_1`` arrays rendered as semi-transparent hatched
    M3/M4 overlays so underlying silicon density is 100% visible for review.
"""
from __future__ import annotations

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


PALETTE = {
    "pwell":      ("#f7efe2", "#ccb89d", 1),
    "nwell":      ("#fef3c7", "#d97706", 2),
    "guard_p":    ("#bbf7d0", "#15803d", 3),
    "guard_n":    ("#bae6fd", "#0369a1", 3),
    "pnp":        ("#fecdd3", "#be123c", 5),
    "pnp_em":     ("#fb7185", "#881337", 6),
    "res_body":   ("#e879f9", "#86198f", 5),
    "res_head":   ("#a855f7", "#581c87", 6),
    "pmos_act":   ("#fda4af", "#9f1239", 5),
    "nmos_act":   ("#93c5fd", "#1d4ed8", 5),
    "poly_gate":  ("#ea580c", "#7c2d12", 6),
    "mim_cc":     ("#38bdf8", "#0284c7", 9),
    "mim_cvgi":   ("#fbbf24", "#b45309", 9),
    "mim_cvbg":   ("#34d399", "#047857", 9),
}


def box(ax, x, y, w, h, kind: str, label: str | None = None, fontsize: float = 6.5,
        hatch: str | None = None, alpha: float = 0.88, lw: float = 0.8, ls: str = "-"):
    fc, ec, z = PALETTE[kind]
    r = Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec, linewidth=lw,
                  linestyle=ls, alpha=alpha, hatch=hatch, zorder=z)
    ax.add_patch(r)
    if label:
        ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
                fontsize=fontsize, fontweight="bold", color="#111827",
                zorder=z + 3, bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.72))


def draw_guard(ax, x, y, w, h, kind: str = "guard_p", t: float = 0.85):
    fc, ec, z = PALETTE[kind]
    for rx, ry, rw, rh in [
        (x, y, w, t),
        (x, y + h - t, w, t),
        (x, y, t, h),
        (x + w - t, y, t, h),
    ]:
        ax.add_patch(Rectangle((rx, ry), rw, rh, facecolor=fc, edgecolor=ec, lw=0.5, zorder=z))


def draw_mos_array(ax, x, y, w, h, n_rows: int, nf: int, is_pmos: bool, label: str, fontsize: float = 6.3):
    act_kind = "pmos_act" if is_pmos else "nmos_act"
    pad_x, pad_y = 0.9, 0.8
    iw, ih = w - 2 * pad_x, h - 2 * pad_y
    row_h = ih / n_rows
    for r in range(n_rows):
        ry = y + pad_y + r * row_h + row_h * 0.12
        rh = row_h * 0.76
        box(ax, x + pad_x, ry, iw, rh, act_kind, lw=0.5)
        slot_w = iw / nf
        gw = slot_w * 0.68
        for f in range(nf):
            gx = x + pad_x + f * slot_w + (slot_w - gw) / 2
            ax.add_patch(Rectangle((gx, ry - 0.25), gw, rh + 0.50,
                                   facecolor=PALETTE["poly_gate"][0],
                                   edgecolor=PALETTE["poly_gate"][1],
                                   lw=0.35, alpha=0.88, zorder=6))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fontsize, fontweight="bold", color="#111827", zorder=8,
            bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="#6b7280", lw=0.4, alpha=0.84))


def draw_res_bank(ax, x, y, w, h, n_bars: int, bar_lens: list[float] | float, label: str, fontsize: float = 6.2):
    pad_x = 0.9
    iw = w - 2 * pad_x
    pitch = iw / max(1, n_bars)
    bw = min(1.0, pitch * 0.58)
    lens = [bar_lens] * n_bars if isinstance(bar_lens, (int, float)) else bar_lens
    for i, bl in enumerate(lens):
        bx = x + pad_x + i * pitch + (pitch - bw) / 2
        by = y + 1.2
        bh = min(h - 2.4, bl)
        ax.add_patch(Rectangle((bx, by), bw, bh, facecolor=PALETTE["res_body"][0],
                               edgecolor=PALETTE["res_body"][1], lw=0.4, alpha=0.88, zorder=5))
        ax.add_patch(Rectangle((bx - 0.1, by), bw + 0.2, min(1.6, bh * 0.2),
                               facecolor=PALETTE["res_head"][0], edgecolor="none", zorder=6))
        ax.add_patch(Rectangle((bx - 0.1, by + bh - min(1.6, bh * 0.2)), bw + 0.2, min(1.6, bh * 0.2),
                               facecolor=PALETTE["res_head"][0], edgecolor="none", zorder=6))
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fontsize, fontweight="bold", color="#111827", zorder=8,
            bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="#86198f", lw=0.45, alpha=0.84))


def draw_pnp_island(ax, x, y):
    # Exact PDK: 3 cols x 4 rows of 6.70x6.70 PNP at 7.60 pitch inside 25.3 x 32.5 guard ring
    w, h = 25.3, 32.5
    draw_guard(ax, x, y, w, h, "guard_p", t=0.80)
    tags = [
        ["Q2", "Q2", "Q2"],
        ["Q2", "Q1", "Q2"],
        ["Q2", "Q2", "Q2"],
        ["DM", "Q3", "DM"],
    ]
    for r in range(4):
        for c in range(3):
            px = x + 1.55 + c * 7.60
            py = y + 1.45 + r * 7.55
            t = tags[r][c]
            if t == "DM":
                box(ax, px, py, 6.7, 6.7, "guard_p", "Dum\nP+", fontsize=5.0)
            else:
                box(ax, px, py, 6.7, 6.7, "pnp", lw=0.6)
                box(ax, px + 1.65, py + 1.65, 3.4, 3.4, "pnp_em", t, fontsize=5.3)


def draw_mim_overlay(ax, x, y, nx: int, ny: int, kind: str, title: str):
    # Exact PDK MIM: nx=1 -> 24.06, nx=2 -> 49.32; ny * 23.80
    w = 24.06 if nx == 1 else (49.32 if nx == 2 else nx * 24.8)
    h = ny * 23.80
    fc, ec, z = PALETTE[kind]
    # Individual 22.2 x 22.2 plates in light translucent tint + dashed border so under-devices stay visible
    dx_p = w / nx
    dy_p = h / ny
    for ix in range(nx):
        for iy in range(ny):
            px = x + ix * dx_p + (dx_p - 22.2) / 2
            py = y + iy * dy_p + (dy_p - 22.2) / 2
            ax.add_patch(Rectangle((px, py), 22.2, 22.2, facecolor=fc, edgecolor=ec,
                                   lw=1.0, ls="--", alpha=0.22, hatch="//", zorder=z))
    ax.add_patch(Rectangle((x, y), w, h, facecolor="none", edgecolor=ec, lw=1.6, ls="-.", zorder=z + 1))
    ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="top",
            fontsize=6.5, fontweight="bold", color=ec, zorder=z + 4,
            bbox=dict(boxstyle="round,pad=0.15", fc="white", ec=ec, lw=0.8, alpha=0.92))


def draw_full_macro_plan(ax, is_bias_ref: bool):
    W, H = 166.0, 98.0
    box(ax, 0, 0, W, H, "pwell", lw=1.2)
    draw_guard(ax, 0.6, 0.6, W - 1.2, H - 1.2, "guard_p", t=0.90)

    # --- ZONE 1 (x = 2.2 .. 33.2, w = 31.0, h = 93.6): 4x3 PNP (Top) + CC Core Resistors (Bot) ---
    draw_pnp_island(ax, 4.8, 62.2)  # 25.3 x 32.5 -> top at 94.7 (100% MIM-free!)

    # Guarded Core Resistor Bank: Xrsa/Xrsb (13.02 x 45.26) + [5xR2|R1|5xR2] (15.80 x 38.86)
    draw_guard(ax, 2.4, 3.0, 30.8, 56.5, "guard_p", t=0.75)
    draw_res_bank(ax, 3.4, 7.5, 13.02, 45.26, 8, 39.4, "Xrsa/Xrsb\n8x39.4u\n(ABBA)", fontsize=5.6)
    draw_res_bank(ax, 16.8, 10.5, 15.60, 38.86, 11, 34.0, "5xR2|R1|5xR2\n11x34u\n(CC PTAT)", fontsize=5.6)

    # --- ZONE 2A (x = 35.5 .. 88.5, w = 53.0): Bandgap Core Loop (Xm1..5 + Xamp + Startup) ---
    # Shared Continuous Top N-Well (Xm1..5 5x4 + Xla/Xlb 4x4 + Xp2 8x1 + Xsp)
    box(ax, 36.0, 21.5, 52.0, 73.5, "nwell", lw=0.8)
    draw_guard(ax, 36.0, 21.5, 52.0, 73.5, "guard_n", t=0.65)
    draw_mos_array(ax, 40.4, 64.5, 43.12, 29.73, 4, 5, True,
                   "Xm1..Xm5 Core PMOS\n(5x4 2D-CC, W=24/L=8 x5)", fontsize=6.0)
    draw_mos_array(ax, 36.6, 33.8, 50.83, 29.73, 4, 4, True,
                   "Xamp: Xla/Xlb Load\n(4x4 2D-CC, W=48/L=12)", fontsize=6.0)
    draw_mos_array(ax, 36.8, 25.0, 35.99, 8.19, 1, 8, True,
                   "Xp2 (8x1, 48/4)", fontsize=5.6)
    draw_mos_array(ax, 36.8, 22.1, 21.96, 2.61, 1, 1, True,
                   "Xsp (0.42/20)", fontsize=5.0)

    # Bottom P-Well of Zone 2A: Xa/Xb (44.0 x 8.1) + Rz (7.1 x 21.3) + [Xt, Xbd, X2, Xsn, Xsu]
    draw_guard(ax, 36.0, 3.0, 52.0, 17.8, "guard_p", t=0.65)
    draw_mos_array(ax, 36.6, 11.2, 43.99, 8.10, 1, 8, False,
                   "Xamp: Xa/Xb (8x1 CC, 24/5)", fontsize=5.8)
    draw_res_bank(ax, 80.8, 3.6, 7.10, 21.30, 4, 15.5, "Rz\n20k", fontsize=5.3)
    draw_mos_array(ax, 37.0, 4.2, 8.87, 4.88, 1, 2, False, "Xt\n8/4", fontsize=5.0)
    draw_mos_array(ax, 46.8, 4.6, 8.87, 2.88, 1, 2, False, "Xbd\n4/4", fontsize=5.0)
    draw_mos_array(ax, 56.6, 4.6, 2.58, 2.88, 1, 1, False, "X2", fontsize=4.8)
    draw_mos_array(ax, 60.2, 4.6, 4.20, 2.88, 1, 2, False, "Xsn/su", fontsize=4.8)

    # --- ZONE 2B (x = 90.5 .. 143.5, w = 53.0): V->I Loop (Xmv/Xo0..3 + Xamp2 OTA + Trim Sw) ---
    box(ax, 91.0, 46.0, 52.0, 49.0, "nwell", lw=0.8)
    draw_guard(ax, 91.0, 46.0, 52.0, 49.0, "guard_n", t=0.65)
    draw_mos_array(ax, 94.7, 78.8, 44.57, 15.37, 2, 10, True,
                   "Xmv + Xo0..Xo3 V->I PMOS\n(10x2 2D-CC, W=24/L=4 x5)", fontsize=5.8)
    draw_mos_array(ax, 91.6, 47.5, 50.83, 29.73, 4, 4, True,
                   "Xamp2 (OTA): Xla/Xlb Load\n(4x4 2D-CC, W=48/L=12)", fontsize=6.0)

    draw_guard(ax, 91.0, 3.0, 52.0, 42.0, "guard_p", t=0.65)
    draw_mos_array(ax, 93.0, 35.8, 43.99, 8.10, 1, 8, False,
                   "Xamp2: Xa/Xb (8x1 CC, 24/5)", fontsize=5.8)
    draw_mos_array(ax, 93.0, 31.2, 8.58, 2.60, 1, 1, False, "Xt_ota (1/8)", fontsize=5.0)
    draw_mos_array(ax, 103.0, 31.0, 8.87, 2.88, 1, 2, False, "Xbd2 (4/4)", fontsize=5.0)
    draw_mos_array(ax, 113.5, 31.2, 4.58, 2.40, 1, 1, False, "Xk (1/4)", fontsize=5.0)

    # Bottom of Zone 2B (y = 4 .. 29): 5x Trim Switches Xs4..0 + LSB Trim Resistors Xrt3..0!
    for k in range(5):
        sx = 93.0 + k * 4.4
        draw_mos_array(ax, sx, 4.2, 3.4, 5.88, 1, 4, False, f"Xs{4-k}", fontsize=4.6)
    draw_res_bank(ax, 116.5, 4.2, 24.5, 24.5, 4, [22.65, 12.81, 7.89, 5.43],
                  "Xrt3..Xrt0\n(4 Binary Trim)", fontsize=5.4)

    # --- ZONE 3 (x = 145.0 .. 164.0, w = 19.0): Xrref (8x44u) + Xrt4 (38.2u) ---
    draw_guard(ax, 145.0, 3.0, 18.8, 92.0, "guard_p", t=0.70)
    draw_res_bank(ax, 146.2, 44.2, 13.02, 49.84, 8, 44.0, "Xrref\n112k\n(8x44u)", fontsize=5.6)
    draw_res_bank(ax, 160.0, 45.0, 2.6, 42.34, 1, 38.2, "rt4", fontsize=4.8)
    # Note: bottom 146..162 y=4..42 can alternatively fold half of Xrref or host Cvbg/Cvgi M3/M4 vias;
    # EVEN BETTER: put Xrsa/Xrsb or Xrref split? Wait: let's see how tight 145..164 already is!
    ax.text(154.4, 23.0, "M3/M4 Cap\nVia Drop &\nTrim Routing\n(18 x 38 um)", ha="center", va="center",
            fontsize=5.3, color="#6b7280", style="italic")

    # --- 3D M3/M4 MIM CAPACITOR OVERLAYS (Hatched & Translucent) ---
    draw_mim_overlay(ax, 37.2, 15.0, 2, 3, "mim_cc", "3D MIM: Cc = 6 pF (2x3, M3/M4)")
    if not is_bias_ref:
        draw_mim_overlay(ax, 89.2, 47.0, 1, 2, "mim_cvgi", "Cvgi_A\n2 pF (1x2)")
        draw_mim_overlay(ax, 114.6, 1.4, 2, 4, "mim_cvgi", "3D MIM: Cvgi_B = 8 pF (2x4, Total Cvgi=10 pF)")
        title = "1. serdes_bandgap_pdk Plan — 166.0 x 98.0 um = 16,268 um² (-48% vs 31,244 um²)"
        sub = "Zone 1: 4x3 PNP + CC Rsa/Rsb/R1/R2 | Zone 2A: 5x4 Core PMOS + Xamp + Startup (under 6pF Cc) | Zone 2B+3: V->I + OTA + Rref/Trim (under 10pF Cvgi)"
    else:
        draw_mim_overlay(ax, 89.2, 47.0, 1, 2, "mim_cvgi", "Cvgi = 2 pF\n(1x2)")
        draw_mim_overlay(ax, 114.6, 23.2, 1, 3, "mim_cvbg", "Cvbg_A\n3 pF (1x3)")
        draw_mim_overlay(ax, 139.8, 47.0, 1, 2, "mim_cvbg", "Cvbg_B\n2 pF (Total 5pF)")
        title = "2. serdes_bias_ref_pdk Plan — 166.0 x 98.0 um = 16,268 um² (Chip-Integrated Reference)"
        sub = "Cvgi ALREADY shrunk 10pF -> 2pF (24pF external pcopy gates) + Cvbg = 5pF PSRR filter — 100% 3D-stacked over active/resistors (0 um² cap overhang)"

    # Zone divider annotations at top
    for zx, zlbl in [(17.8, "Zone 1 (31u)"), (62.0, "Zone 2A (53u)"), (117.0, "Zone 2B (53u)"), (154.4, "Z3 (19u)")]:
        ax.text(zx, 99.6, zlbl, ha="center", va="bottom", fontsize=6.8, fontweight="bold", color="#374151")

    ax.set_xlim(-4, W + 4)
    ax.set_ylim(-4, H + 7)
    ax.set_aspect("equal")
    ax.set_title(f"{title}\n{sub}", fontsize=8.4, fontweight="bold", pad=8)
    ax.set_xlabel("x (um)", fontsize=7.5)
    ax.set_ylabel("y (um)", fontsize=7.5)
    ax.tick_params(labelsize=7)
    ax.grid(True, lw=0.25, alpha=0.35)


def draw_subblocks_and_comparison(ax_sub, ax_cmp):
    # Panel 3: Compacted Standalone serdes_bg_amp_pdk (56.5 x 75.0) + serdes_bg_ota_pdk (54.8 x 44.5)
    # Place side-by-side in one coordinate frame for 1:1 visual inspection
    # Left: serdes_bg_amp_pdk at x=0..56.5, y=0..75.0
    W_AMP, H_AMP = 56.5, 75.0
    box(ax_sub, 0, 0, W_AMP, H_AMP, "pwell", lw=1.1)
    draw_guard(ax_sub, 0.5, 0.5, W_AMP - 1.0, H_AMP - 1.0, "guard_p", t=0.85)
    box(ax_sub, 2.2, 23.0, W_AMP - 4.4, 49.8, "nwell", lw=0.7)
    draw_mos_array(ax_sub, 2.8, 42.2, 50.83, 29.73, 4, 4, True, "Xla/Xlb (4x4 CC, 48/12)", fontsize=6.0)
    draw_mos_array(ax_sub, 2.8, 24.0, 35.99, 8.19, 1, 8, True, "Xp2 (8x1, 48/4)", fontsize=5.8)
    draw_mos_array(ax_sub, 2.8, 12.2, 43.99, 8.10, 1, 8, False, "Xa/Xb (8x1 CC, 24/5)", fontsize=5.8)
    draw_res_bank(ax_sub, 47.2, 11.5, 7.10, 21.30, 4, 15.5, "Rz\n20k", fontsize=5.4)
    draw_mos_array(ax_sub, 3.2, 3.2, 8.87, 4.88, 1, 2, False, "Xt (8/4)", fontsize=5.3)
    draw_mos_array(ax_sub, 14.0, 3.8, 2.58, 2.88, 1, 1, False, "X2", fontsize=5.0)
    draw_mim_overlay(ax_sub, 3.6, 2.0, 2, 3, "mim_cc", "3D Cc = 6 pF (2x3)")
    ax_sub.text(W_AMP / 2, H_AMP + 2.0, "serdes_bg_amp_pdk\n56.5 x 75.0 um = 4,238 um² (-25.5%)",
                ha="center", va="bottom", fontsize=7.5, fontweight="bold")

    # Right: serdes_bg_ota_pdk at x=66..120.8, y=0..44.5
    ox = 66.0
    W_OTA, H_OTA = 54.8, 44.5
    box(ax_sub, ox, 0, W_OTA, H_OTA, "pwell", lw=1.1)
    draw_guard(ax_sub, ox + 0.5, 0.5, W_OTA - 1.0, H_OTA - 1.0, "guard_p", t=0.85)
    box(ax_sub, ox + 1.6, 13.2, W_OTA - 3.2, 30.2, "nwell", lw=0.7)
    draw_mos_array(ax_sub, ox + 2.0, 13.6, 50.83, 29.73, 4, 4, True, "Xla/Xlb (4x4 CC, 48/12)", fontsize=6.0)
    draw_mos_array(ax_sub, ox + 2.5, 4.2, 43.99, 8.10, 1, 8, False, "Xa/Xb (8x1 CC, 24/5)", fontsize=5.8)
    draw_mos_array(ax_sub, ox + 47.0, 4.2, 5.2, 8.10, 1, 1, False, "Xt\n1/8\n(rot)", fontsize=5.0)
    ax_sub.text(ox + W_OTA / 2, H_OTA + 2.0, "serdes_bg_ota_pdk\n54.8 x 44.5 um = 2,439 um² (-23.5%)\n(Xt rotated beside Xa/Xb -> 0 dead row!)",
                ha="center", va="bottom", fontsize=7.2, fontweight="bold")

    ax_sub.set_xlim(-4, 126)
    ax_sub.set_ylim(-4, 84)
    ax_sub.set_aspect("equal")
    ax_sub.set_title("3. Compacted Sub-Amplifiers (1:1 PDK Scale — Eliminating Empty Rows & Side Margins)",
                     fontsize=8.4, fontweight="bold", pad=8)
    ax_sub.set_xlabel("x (um)", fontsize=7.5)
    ax_sub.set_ylabel("y (um)", fontsize=7.5)
    ax_sub.tick_params(labelsize=7)
    ax_sub.grid(True, lw=0.25, alpha=0.35)

    # Panel 4: serdes_ref_vbuf_pdk (69.5 x 50.5) + Footprint Shrink Comparison Box
    W_VB, H_VB = 69.5, 50.5
    box(ax_cmp, 0, 0, W_VB, H_VB, "pwell", lw=1.1)
    draw_guard(ax_cmp, 0.5, 0.5, W_VB - 1.0, H_VB - 1.0, "guard_p", t=0.85)
    box(ax_cmp, 1.8, 18.2, 51.6, 30.8, "nwell", lw=0.7)
    draw_mos_array(ax_cmp, 2.2, 18.7, 50.83, 29.73, 4, 4, True, "Xla/Xlb (4x4 CC, 48/12)", fontsize=5.8)
    draw_mos_array(ax_cmp, 2.8, 9.0, 43.99, 8.10, 1, 8, False, "Xa/Xb (8x1 CC, 24/5)", fontsize=5.8)
    draw_mos_array(ax_cmp, 2.8, 3.2, 18.83, 4.10, 1, 4, False, "Xbd + Xt (4x 2/4)", fontsize=5.3)
    draw_res_bank(ax_cmp, 54.4, 1.6, 13.02, 47.31, 8, 41.5, "Xr\n105.2k\n(8x41.5u)", fontsize=5.6)
    ax_cmp.text(W_VB / 2, H_VB + 2.0, "serdes_ref_vbuf_pdk\n69.5 x 50.5 um = 3,510 um² (-22.5%)",
                ha="center", va="bottom", fontsize=7.3, fontweight="bold")

    # Right side of Panel 4: 1:1 Footprint Comparison of Bandgap Top Macro (scaled 0.5x to fit)
    cx0 = 82.0
    s = 0.42
    # Argon (389 x 162 -> 63,018)
    ax_cmp.add_patch(Rectangle((cx0, 2.0), 389 * s, 162 * s, fc="#fee2e2", ec="#dc2626", lw=1.2, ls=":", zorder=1))
    ax_cmp.text(cx0 + 389 * s - 2, 2.0 + 162 * s - 3, "Argon Ad-hoc\n389 x 162 um\n(63,018 um²)",
                ha="right", va="top", fontsize=6.3, color="#991b1b", fontweight="bold")
    # Previous v1 PDK (212.4 x 147.1 -> 31,244)
    ax_cmp.add_patch(Rectangle((cx0, 2.0), 212.4 * s, 147.1 * s, fc="#fef3c7", ec="#d97706", lw=1.2, ls="--", zorder=2))
    ax_cmp.text(cx0 + 212.4 * s - 2, 2.0 + 147.1 * s - 2.5, "Prev PDK v1\n212 x 147 um\n(31,244 um²)",
                ha="right", va="top", fontsize=6.2, color="#92400e", fontweight="bold")
    # New Plan-First v2 PDK (166 x 98 -> 16,268)
    ax_cmp.add_patch(Rectangle((cx0, 2.0), 166.0 * s, 98.0 * s, fc="#dcfce7", ec="#15803d", lw=1.8, zorder=3))
    ax_cmp.text(cx0 + 166.0 * s / 2, 2.0 + 98.0 * s / 2,
                "New Plan-First v2\n166 x 98 um\n16,268 um²\n(-48% vs v1 | -74% vs Argon)",
                ha="center", va="center", fontsize=6.4, color="#14532d", fontweight="bold")

    ax_cmp.set_xlim(-4, 250)
    ax_cmp.set_ylim(-4, 76)
    ax_cmp.set_aspect("equal")
    ax_cmp.set_title("4. serdes_ref_vbuf_pdk Plan & Bandgap Macro Footprint Evolution",
                     fontsize=8.4, fontweight="bold", pad=8)
    ax_cmp.set_xlabel("x (um)", fontsize=7.5)
    ax_cmp.set_ylabel("y (um)", fontsize=7.5)
    ax_cmp.tick_params(labelsize=7)
    ax_cmp.grid(True, lw=0.25, alpha=0.35)


def main() -> None:
    out = Path(__file__).with_name("bias_pdk_floorplan_plan.png")
    fig, axes = plt.subplots(2, 2, figsize=(18.5, 13.5), dpi=165)
    draw_full_macro_plan(axes[0, 0], is_bias_ref=False)
    draw_full_macro_plan(axes[0, 1], is_bias_ref=True)
    draw_subblocks_and_comparison(axes[1, 0], axes[1, 1])

    legend_items = [
        ("pnp_em", "PNP BJT (6.7x6.7u)"),
        ("pmos_act", "LVT PMOS Active + Gate"),
        ("nmos_act", "NMOS Active + Gate"),
        ("res_body", "w=1 high_po Resistor"),
        ("nwell", "Continuous Shared N-Well"),
        ("guard_p", "M1 P+ Guard Ring"),
        ("mim_cc", "3D MIM Cc (6 pF)"),
        ("mim_cvgi", "3D MIM Cvgi (10p / 2p)"),
        ("mim_cvbg", "3D MIM Cvbg (5 pF)"),
    ]
    handles = [
        Rectangle((0, 0), 1, 1, fc=PALETTE[k][0], ec=PALETTE[k][1],
                  alpha=0.35 if k.startswith("mim_") else 0.88,
                  hatch="//" if k.startswith("mim_") else None, label=lbl)
        for k, lbl in legend_items
    ]
    fig.legend(handles=handles, loc="lower center", ncol=5, frameon=True, fontsize=8.5, bbox_to_anchor=(0.5, 0.006))
    fig.suptitle(
        "SKY130 Bandgap & Bias Suite — True 1:1 PDK-Scale Floorplan Blueprint (Plan-First Before Magic Routing)",
        fontsize=13.5, fontweight="bold", y=0.992,
    )
    plt.tight_layout(rect=[0, 0.05, 1, 0.975])
    fig.savefig(out, dpi=165)
    plt.close(fig)
    print("Saved floorplan blueprint:", out)


if __name__ == "__main__":
    main()
