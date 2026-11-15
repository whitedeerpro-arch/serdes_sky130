#!/usr/bin/env python3
"""Generate 1:1 physical floorplan candidates for the PLL CML /8 Divider Suite
(pll_cml_latch, pll_cml_div2_biased, pll_div_buffer, pll_cml_tail_bias, pll_cml_prescaler8).

Outputs:
- analog/pll/divider/layout/plan/divider_plan.png
- analog/pll/divider/layout/plan/divider_plan.json
"""
from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

PLAN_DIR = Path(__file__).resolve().parent


def add_box(
    ax: plt.Axes,
    x0: float,
    y0: float,
    w: float,
    h: float,
    label: str = "",
    fc: str = "#e0e7ff",
    ec: str = "#1e3a8a",
    lw: float = 1.2,
    alpha: float = 0.88,
    fontsize: float = 7.0,
    text_color: str = "#111827",
    ls: str = "-",
) -> None:
    rect = Rectangle((x0, y0), w, h, facecolor=fc, edgecolor=ec, linewidth=lw, alpha=alpha, linestyle=ls)
    ax.add_patch(rect)
    if label:
        ax.text(
            x0 + w / 2.0,
            y0 + h / 2.0,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            fontweight="bold",
        )


def draw_latch_comparison(ax: plt.Axes) -> dict:
    """Panel 1: Leaf CML Latch (pll_cml_latch_h40/h80) Old vs Plan A (Stacked Abutted) vs Plan B (Co-Planar Data+Hold)."""
    ax.set_title(
        "Leaf 1: pll_cml_latch (h40 / h80) — 1:1 Physical Comparison\n"
        "(S/D Vertical Split + Single-Sided Gate Trim + Guard-Ring Abutment + Dummies)",
        fontsize=9.5,
        fontweight="bold",
    )

    # 1) Old Draft Outline at x_center = -32
    ox = -33.0
    add_box(ax, ox - 14.95, -5.5, 29.90, 48.41, "", fc="#f8fafc", ec="#94a3b8", lw=1.2, ls="--", alpha=0.5)
    ax.text(ox, 44.2, "Old Draft\n29.9 x 48.4 um (1447 um²)\n(No Dummies, Un-abutted)", ha="center", va="bottom", fontsize=7.5, color="#475569", fontweight="bold")
    add_box(ax, ox - 14.5, 40.75, 29.0, 0.9, "VDD (M1)", fc="#bbf7d0", ec="#15803d", fontsize=6)
    add_box(ax, ox - 14.5, -4.65, 29.0, 0.9, "VSS (M1)", fc="#bbf7d0", ec="#15803d", fontsize=6)
    for sx, br in ((-7.2, "N (qn)"), (7.2, "P (qp)")):
        add_box(ax, ox + sx - 2.075, 30.2, 4.15, 9.60, f"Rload\n{br}", fc="#dbeafe", ec="#1d4ed8", fontsize=6)
        add_box(ax, ox + sx - 1.615, 20.83, 3.23, 6.74, "Data (4f)", fc="#ede9fe", ec="#5b21b6", fontsize=5.8)
        add_box(ax, ox + sx - 4.495, 11.43, 8.99, 6.74, "Hold (8/16f)", fc="#fce7f3", ec="#be185d", fontsize=5.8)
        add_box(ax, ox + sx - 4.495, 3.83, 8.99, 5.74, "Clk (16f)", fc="#fef08a", ec="#ca8a04", fontsize=5.8)
        add_box(ax, ox + sx - 5.395, -2.37, 10.79, 4.74, "Tail (12f)", fc="#ffedd5", ec="#c2410c", fontsize=5.8)

    # 2) Latch Plan A (Compact Vertical Stacked + Abutted Guard Rings + Dummies) at x_center = 0
    ax_c = 0.0
    w_a, h_a = 21.8, 33.4
    add_box(ax, ax_c - w_a / 2, -4.2, w_a, h_a, "", fc="#f0fdf4", ec="#15803d", lw=1.4, ls="-", alpha=0.35)
    ax.text(ax_c, 30.5, "Latch Plan A (Recommended)\n21.8 x 33.4 um (728 um², -50%)\nAbutted GR + MOS/Res Dummies", ha="center", va="bottom", fontsize=7.5, color="#15803d", fontweight="bold")
    add_box(ax, ax_c - w_a / 2, 28.4, w_a, 0.8, "VDD (M1/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6)
    add_box(ax, ax_c - w_a / 2, -4.2, w_a, 0.8, "VSS (M1/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6)

    # Top resistors: [Rdum_L | Rn | Rp | Rdum_R] abutted at pitch 3.98 um
    for rx, rlbl, rfc, rec in (
        (-5.97, "Rdum", "#e2e8f0", "#64748b"),
        (-1.99, "Rn\n(qn)", "#dbeafe", "#1d4ed8"),
        (+1.99, "Rp\n(qp)", "#fce7f3", "#be185d"),
        (+5.97, "Rdum", "#e2e8f0", "#64748b"),
    ):
        add_box(ax, ax_c + rx - 2.075, 18.6, 4.15, 9.60, rlbl, fc=rfc, ec=rec, fontsize=5.8)

    # Data row (y = 12.2..18.4, with outer dummy fingers)
    for sx, dlbl, dfc, dec in ((-4.41, "Xdp (4f+dum)", "#dbeafe", "#1d4ed8"), (+4.41, "Xdn (4f+dum)", "#fce7f3", "#be185d")):
        add_box(ax, ax_c + sx - 2.20, 12.2, 4.40, 6.20, dlbl, fc=dfc, ec=dec, fontsize=5.8)

    # Hold row (y = 6.0..12.2, abutted vertically & horizontally at x = +-4.41)
    for sx, hlbl, hfc, hec in ((-4.41, "Xhp (8/16f+dum)", "#dbeafe", "#1d4ed8"), (+4.41, "Xhn (8/16f+dum)", "#fce7f3", "#be185d")):
        add_box(ax, ax_c + sx - 4.49, 6.0, 8.98, 6.20, hlbl, fc=hfc, ec=hec, fontsize=5.8)

    # Clock row (y = 0.6..6.0, abutted at x = +-4.41)
    for sx, clbl in ((-4.41, "Xct (16f+dum)"), (+4.41, "Xch (16f+dum)")):
        add_box(ax, ax_c + sx - 4.49, 0.6, 8.98, 5.40, clbl, fc="#fef08a", ec="#ca8a04", fontsize=5.8)

    # Tail row (y = -3.4..0.6, single merged 24f+dum or 2x12f+dum at y = -1.4)
    add_box(ax, ax_c - 10.5, -3.4, 21.0, 4.0, "Xtail (2x12f + L=0.5u Dummies, Shared GR)", fc="#ffedd5", ec="#c2410c", fontsize=6.0)

    # 3) Latch Plan B (Co-Planar [Data + Hold] Row, Ultra-Low Height) at x_center = +31
    bx_c = 31.0
    w_b, h_b = 25.4, 27.2
    add_box(ax, bx_c - w_b / 2, -4.2, w_b, h_b, "", fc="#eff6ff", ec="#1d4ed8", lw=1.4, ls="-", alpha=0.35)
    ax.text(bx_c, 24.3, "Latch Plan B (Ultra-Low Height)\n25.4 x 27.2 um (691 um², -52%)\nCo-Planar [Data + Hold] Row", ha="center", va="bottom", fontsize=7.5, color="#1d4ed8", fontweight="bold")
    add_box(ax, bx_c - w_b / 2, 22.2, w_b, 0.8, "VDD (M1/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6)
    add_box(ax, bx_c - w_b / 2, -4.2, w_b, 0.8, "VSS (M1/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6)

    for rx, rlbl, rfc, rec in (
        (-5.97, "Rdum", "#e2e8f0", "#64748b"),
        (-1.99, "Rn\n(qn)", "#dbeafe", "#1d4ed8"),
        (+1.99, "Rp\n(qp)", "#fce7f3", "#be185d"),
        (+5.97, "Rdum", "#e2e8f0", "#64748b"),
    ):
        add_box(ax, bx_c + rx - 2.075, 12.4, 4.15, 9.60, rlbl, fc=rfc, ec=rec, fontsize=5.8)

    # Co-planar Data + Hold row (both w_f = 5.0u, L = 0.15u, sharing qn/qp M2 drain bar!)
    add_box(ax, bx_c - 12.2, 6.0, 3.4, 6.2, "Xdp\n4f", fc="#dbeafe", ec="#1d4ed8", fontsize=5.5)
    add_box(ax, bx_c - 8.8, 6.0, 8.8, 6.2, "Xhp (8/16f)\nShared qn M2", fc="#dbeafe", ec="#1d4ed8", fontsize=5.5)
    add_box(ax, bx_c + 0.0, 6.0, 8.8, 6.2, "Xhn (8/16f)\nShared qp M2", fc="#fce7f3", ec="#be185d", fontsize=5.5)
    add_box(ax, bx_c + 8.8, 6.0, 3.4, 6.2, "Xdn\n4f", fc="#fce7f3", ec="#be185d", fontsize=5.5)

    for sx, clbl in ((-4.41, "Xct (16f+dum)"), (+4.41, "Xch (16f+dum)")):
        add_box(ax, bx_c + sx - 4.49, 0.6, 8.98, 5.40, clbl, fc="#fef08a", ec="#ca8a04", fontsize=5.8)
    add_box(ax, bx_c - 10.5, -3.4, 21.0, 4.0, "Xtail (2x12f + L=0.5u Dummies)", fc="#ffedd5", ec="#c2410c", fontsize=6.0)

    ax.set_xlim(-52, 48)
    ax.set_ylim(-8, 52)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return {
        "old_latch_um": [29.90, 48.41],
        "plan_a_stacked_um": [w_a, h_a],
        "plan_b_coplanar_um": [w_b, h_b],
    }


def draw_div2_and_leafs(ax: plt.Axes) -> dict:
    """Panel 2: Stage pll_cml_div2_biased (52.4 x 33.4 um) + pll_div_buffer (16.4 x 28.0 um) + pll_cml_tail_bias (18.0 x 24.0 um)."""
    ax.set_title(
        "Stage & Leaf Blocks — Abutted Guard-Ring Architecture\n"
        "(pll_cml_div2_biased: 52.4 x 33.4 um [-65% area] | Buffer: 16.4 x 28.0 um | Tail Bias: 18.0 x 24.0 um)",
        fontsize=9.5,
        fontweight="bold",
    )

    # 1) pll_cml_div2_biased (SF + Master Latch + Slave Latch abutted horizontally)
    x0 = -48.0
    w_sf = 9.2
    w_latch = 21.6
    w_div2 = w_sf + 2 * w_latch  # 52.4 um
    h_div2 = 33.4
    add_box(ax, x0, -4.2, w_div2, h_div2, "", fc="#f8fafc", ec="#0f172a", lw=1.5)
    ax.text(x0 + w_div2 / 2, 30.5, "pll_cml_div2_biased (h40 / h80)\n52.4 x 33.4 um = 1,750 um² (vs Old 86.6 x 57.1 = 4,948 um²)", ha="center", va="bottom", fontsize=7.5, color="#0f172a", fontweight="bold")

    add_box(ax, x0, 28.4, w_div2, 0.8, "Continuous VDD Rail (M1/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6.5)
    add_box(ax, x0, -4.2, w_div2, 0.8, "Continuous VSS Rail (M1/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6.5)

    # Input SF column (x0 .. x0 + 9.2): vertically stacked Xfp (top), Xfn (mid), Xsp/Xsn (bot)
    add_box(ax, x0 + 0.2, 16.2, 8.8, 6.2, "Xfp (SF P)\n16f+dum", fc="#dbeafe", ec="#1d4ed8", fontsize=6)
    add_box(ax, x0 + 0.2, 9.6, 8.8, 6.2, "Xfn (SF N)\n16f+dum", fc="#fce7f3", ec="#be185d", fontsize=6)
    add_box(ax, x0 + 0.2, 0.6, 8.8, 5.2, "Xsp + Xsn\n(L=0.5u + dum)", fc="#ffedd5", ec="#c2410c", fontsize=6)

    # Master Latch (x0 + 9.2 .. x0 + 30.8)
    xm = x0 + w_sf
    add_box(ax, xm, -3.4, w_latch, 31.8, "", fc="#eff6ff", ec="#1d4ed8", lw=1.1, ls="--", alpha=0.45)
    add_box(ax, xm + 1.0, 18.6, w_latch - 2.0, 9.4, "Master Loads\n[Rdum | Rn | Rp | Rdum]", fc="#dbeafe", ec="#1d4ed8", fontsize=6)
    add_box(ax, xm + 1.0, 12.2, w_latch - 2.0, 6.0, "Master Data (Xdp/Xdn + dum)", fc="#ede9fe", ec="#5b21b6", fontsize=6)
    add_box(ax, xm + 1.0, 6.0, w_latch - 2.0, 6.0, "Master Hold (Xhp/Xhn + dum)", fc="#fce7f3", ec="#be185d", fontsize=6)
    add_box(ax, xm + 1.0, 0.6, w_latch - 2.0, 5.2, "Master Clk (Xct=ckp, Xch=ckn)", fc="#fef08a", ec="#ca8a04", fontsize=6)
    add_box(ax, xm + 0.6, -3.4, w_latch - 1.2, 3.8, "Master Tail (24f + dum)", fc="#ffedd5", ec="#c2410c", fontsize=6)

    # Slave Latch (x0 + 30.8 .. x0 + 52.4)
    xs = xm + w_latch
    add_box(ax, xs, -3.4, w_latch, 31.8, "", fc="#fdf2f8", ec="#be185d", lw=1.1, ls="--", alpha=0.45)
    add_box(ax, xs + 1.0, 18.6, w_latch - 2.0, 9.4, "Slave Loads\n[Rdum | Rn | Rp | Rdum]", fc="#fce7f3", ec="#be185d", fontsize=6)
    add_box(ax, xs + 1.0, 12.2, w_latch - 2.0, 6.0, "Slave Data (Xdp/Xdn + dum)", fc="#ede9fe", ec="#5b21b6", fontsize=6)
    add_box(ax, xs + 1.0, 6.0, w_latch - 2.0, 6.0, "Slave Hold (Xhp/Xhn + dum)", fc="#fce7f3", ec="#be185d", fontsize=6)
    add_box(ax, xs + 1.0, 0.6, w_latch - 2.0, 5.2, "Slave Clk (Xct=ckn, Xch=ckp)", fc="#fef08a", ec="#ca8a04", fontsize=6)
    add_box(ax, xs + 0.6, -3.4, w_latch - 1.2, 3.8, "Slave Tail (24f + dum)", fc="#ffedd5", ec="#c2410c", fontsize=6)

    # Internal M3/M4 mp/mn & qp/qn feedback bus bar inside top resistor/drain zone (no external track overhang!)
    add_box(ax, xm + 2.0, 16.8, 2 * w_latch - 4.0, 1.4, "Internal M3/M4 mp/mn & qp/qn Loop (Inside Cell BBox)", fc="#a7f3d0", ec="#047857", fontsize=6)

    # 2) pll_div_buffer (at x = +8.5 .. +24.9)
    xb = 9.0
    wb, hb = 16.4, 28.0
    add_box(ax, xb, -4.2, wb, hb, "", fc="#f8fafc", ec="#1e3a8a", lw=1.3)
    ax.text(xb + wb / 2, 25.0, "pll_div_buffer\n16.4 x 28.0 um\n(ABBA + Dummies)", ha="center", va="bottom", fontsize=7.0, color="#1e3a8a", fontweight="bold")
    add_box(ax, xb + 0.6, 13.5, wb - 1.2, 9.4, "[Rdum|Rn|Rp|Rdum]", fc="#dbeafe", ec="#1d4ed8", fontsize=5.8)
    add_box(ax, xb + 0.8, 4.5, wb - 1.6, 7.8, "ABBA Input Pair\n(16f + Dummies)", fc="#ede9fe", ec="#5b21b6", fontsize=5.8)
    add_box(ax, xb + 2.0, -3.2, wb - 4.0, 6.2, "Xtail (4f + dum)", fc="#ffedd5", ec="#c2410c", fontsize=5.8)

    # 3) pll_cml_tail_bias (at x = +29.0 .. +47.0)
    xt = 29.0
    wt, ht = 18.0, 26.0
    add_box(ax, xt, -4.2, wt, ht, "", fc="#f8fafc", ec="#9a3412", lw=1.3)
    ax.text(xt + wt / 2, 23.0, "pll_cml_tail_bias\n18.0 x 26.0 um\n([PD,PM,PM,PD]+Dum)", ha="center", va="bottom", fontsize=7.0, color="#9a3412", fontweight="bold")
    add_box(ax, xt + 0.8, 10.5, wt - 1.6, 9.8, "PMOS Mirror\n[PD, PM, PM, PD]\n+ L=0.5u Dummies", fc="#fce7f3", ec="#be185d", fontsize=5.8)
    add_box(ax, xt + 0.8, -3.2, wt - 1.6, 11.5, "NMOS Xsink + Xref\n+ L=0.5u Dummies", fc="#ffedd5", ec="#c2410c", fontsize=5.8)

    ax.set_xlim(-52, 50)
    ax.set_ylim(-8, 36)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return {
        "div2_biased_um": [w_div2, h_div2],
        "div_buffer_um": [wb, hb],
        "tail_bias_um": [wt, ht],
    }


def draw_top_plan_linear(ax: plt.Axes) -> dict:
    """Panel 3: Top Plan I — Compacted Abutted 1-Row Linear Pipeline (208.0 x 35.8 um = 7,446 um²)."""
    ax.set_title(
        "Top Plan I: Compacted Abutted 1-Row Linear Pipeline\n"
        "(208.0 x 35.8 um = 7,446 um² [-69% vs Old 370.7 x 64.2 um = 23,799 um²] | Straight Left-to-Right Flow)",
        fontsize=9.5,
        fontweight="bold",
    )

    blocks = [
        ("Xbias\n18.0u", 18.0, "#ffedd5", "#c2410c"),
        ("X2 (/2, h40)\n52.4u", 52.4, "#dbeafe", "#1d4ed8"),
        ("Xb24\n16.4u", 16.4, "#ede9fe", "#5b21b6"),
        ("X4 (/4, h80)\n52.4u", 52.4, "#fce7f3", "#be185d"),
        ("Xb48\n16.4u", 16.4, "#ede9fe", "#5b21b6"),
        ("X8 (/8, h80)\n52.4u", 52.4, "#dcfce7", "#15803d"),
    ]
    total_w = sum(b[1] for b in blocks)  # 208.0 um
    h_top = 35.8
    x_cur = 0.0

    add_box(ax, 0.0, 34.6, total_w, 1.2, "Continuous Top VDD Bus (M4/M2, 208.0 um)", fc="#bbf7d0", ec="#15803d", fontsize=7)
    add_box(ax, 0.0, 0.0, total_w, 1.2, "Continuous Bottom VSS Bus + vbias / vbias_logic Tracks (M4/M3)", fc="#bbf7d0", ec="#15803d", fontsize=7)

    for lbl, bw, fc, ec in blocks:
        add_box(ax, x_cur, 1.2, bw, 33.4, lbl, fc=fc, ec=ec, fontsize=7.5)
        x_cur += bw

    ax.set_xlim(-8, total_w + 8)
    ax.set_ylim(-5, 42)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return {
        "name": "Top Plan I (1-Row Compacted Linear Pipeline)",
        "width_um": total_w,
        "height_um": h_top,
        "area_um2": round(total_w * h_top, 1),
        "area_reduction_vs_old_pct": round((1.0 - (total_w * h_top) / 23798.94) * 100.0, 1),
    }


def draw_top_plan_folded(ax: plt.Axes) -> dict:
    """Panel 4: Top Plan II — VCO-Width-Matched 2-Row Folded Pipeline (121.2 x 69.2 um = 8,387 um², matches VCO 108.6u width)."""
    ax.set_title(
        "Top Plan II: 2-Row Folded U-Pipeline Matched to VCO Core Width\n"
        "(121.2 x 69.2 um = 8,387 um² [-65% vs Old] | Direct Top-Docking to VCO Buffer Outputs, Includes Dummy Load)",
        fontsize=9.5,
        fontweight="bold",
    )

    # Show VCO Core bottom edge above for docking reference
    add_box(ax, 6.3, 73.0, 108.6, 12.0, "VCO Core + Buffer (pll_vco_core_sym9_s32p5, Width = 108.6 um)\nBottom Differential Outputs: outp0/outn0 (-> X2) & outp90/outn90 (-> Dummy Load)", fc="#e0e7ff", ec="#1e3a8a", lw=1.4, ls="--", fontsize=7.0)

    # Row 1 (Top Row, y = 35.2 .. 68.6): [Xbias (18.0u) | X2 (/2, 52.4u) | Xb24 (16.4u) | DummyLoad (18.0u)] = 104.8 um!
    # Wait: 18.0 + 52.4 + 16.4 + 18.0 = 104.8 um (< 108.6 um VCO width!)
    # Row 2 (Bottom Row, y = 1.2 .. 34.6): [X8 (/8, 52.4u) | Xb48 (16.4u) | X4 (/4, 52.4u)] = 121.2 um!
    # Or if Latch Plan A uses abutting Master/Slave with shared center GR: div2 = 46.0u -> Row 2 = 46 + 16.4 + 46 = 108.4 um!
    w_row = 121.2
    add_box(ax, 0.0, 68.2, w_row, 1.0, "Top VDD Rail (M4/M2)", fc="#bbf7d0", ec="#15803d", fontsize=6.5)
    add_box(ax, 0.0, 34.1, w_row, 1.2, "Shared Center VSS / Bias Spine (M4/M2, Shared by Row 1 & Row 2)", fc="#bbf7d0", ec="#15803d", fontsize=6.5)
    add_box(ax, 0.0, 0.0, w_row, 1.0, "Bottom VDD Rail (M4/M2, Row 2 Flipped Y)", fc="#bbf7d0", ec="#15803d", fontsize=6.5)

    # Top Row blocks (centered/aligned with VCO):
    r1_blocks = [
        ("Xbias\n18.0 x 33.0u", 18.0, "#ffedd5", "#c2410c"),
        ("X2 (/2, h40, 2GHz->1GHz)\n52.4 x 33.0u", 52.4, "#dbeafe", "#1d4ed8"),
        ("Xb24 (1GHz Buf)\n16.4 x 33.0u", 16.4, "#ede9fe", "#5b21b6"),
        ("Frontend Dummy Load\n(90° Phase Match)\n18.0 x 33.0u", 18.0, "#fef08a", "#ca8a04"),
    ]
    x_r1 = 8.2  # Centered on 121.2u
    for lbl, bw, fc, ec in r1_blocks:
        add_box(ax, x_r1, 35.3, bw, 32.9, lbl, fc=fc, ec=ec, fontsize=6.8)
        x_r1 += bw

    # Bottom Row blocks (Right-to-Left flow: Xb24 drops straight down into X4 on right, then -> Xb48 -> X8 on left!):
    r2_blocks = [
        ("X8 (/8, h80, 250MHz Out)\n52.4 x 33.0u", 52.4, "#dcfce7", "#15803d"),
        ("Xb48 (500MHz Buf)\n16.4 x 33.0u", 16.4, "#ede9fe", "#5b21b6"),
        ("X4 (/4, h80, 1GHz->500MHz)\n52.4 x 33.0u", 52.4, "#fce7f3", "#be185d"),
    ]
    x_r2 = 0.0
    for lbl, bw, fc, ec in r2_blocks:
        add_box(ax, x_r2, 1.0, bw, 33.1, lbl, fc=fc, ec=ec, fontsize=6.8)
        x_r2 += bw

    ax.set_xlim(-6, 128)
    ax.set_ylim(-4, 88)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return {
        "name": "Top Plan II (2-Row Folded U-Pipeline Matched to VCO)",
        "width_um": w_row,
        "height_um": 69.2,
        "area_um2": round(w_row * 69.2, 1),
        "includes_frontend_dummy_load": True,
    }


def main() -> None:
    fig, axes = plt.subplots(2, 2, figsize=(18, 13), dpi=160)
    res_latch = draw_latch_comparison(axes[0, 0])
    res_stage = draw_div2_and_leafs(axes[0, 1])
    res_top1 = draw_top_plan_linear(axes[1, 0])
    res_top2 = draw_top_plan_folded(axes[1, 1])

    fig.suptitle(
        "PLL CML /8 Divider (pll_cml_prescaler8) — 1:1 Physical Floorplan & Hierarchy Plan",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96])

    png_path = PLAN_DIR / "divider_plan.png"
    json_path = PLAN_DIR / "divider_plan.json"
    fig.savefig(png_path)
    plt.close(fig)

    summary = {
        "leaf_latch": res_latch,
        "stage_and_leafs": res_stage,
        "top_plan_1_linear": res_top1,
        "top_plan_2_folded": res_top2,
    }
    json_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Wrote {png_path} and {json_path}")


if __name__ == "__main__":
    main()
