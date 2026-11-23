"""Generate 1:1 physical floorplan candidates for the VCO Differential Delay Stage (pll_vco_delay_r6)
and its Stage-Level Docking with two 9-Block Half-Tanks (pll_vco_half_tank_sym9).

Outputs:
- analog/pll/vco/layout/plan/delay_stage_plan.png
- analog/pll/vco/layout/plan/delay_stage_plan.json
"""
from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[4]
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
    fontsize: float = 7.5,
    text_color: str = "#111827",
    ls: str = "-",
) -> None:
    rect = Rectangle((x0, y0), w, h, facecolor=fc, edgecolor=ec, linewidth=lw, alpha=alpha, linestyle=ls)
    ax.add_patch(rect)
    if label:
        ax.text(
            x0 + w / 2,
            y0 + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            fontweight="bold",
        )


def draw_core_plan_a(ax: plt.Axes) -> dict:
    """Core Plan A: 4-Island ABBA Baseline + S/D Layer Separation (22.8 x 36.4 um)."""
    ax.set_title(
        "Core Plan A: 4-Island ABBA + S/D Separation\n"
        "(22.8 x 36.4 um | 4 Guard Rings | C_out,parasitic ~ 7.6 fF)",
        fontsize=9.5,
        fontweight="bold",
    )
    add_box(ax, -11.4, -18.7, 22.8, 36.4, "", fc="#f8fafc", ec="#64748b", lw=1.0, ls="--", alpha=0.5)

    add_box(ax, -11.4, 16.9, 22.8, 0.8, "VDD (M2)", fc="#bbf7d0", ec="#15803d", fontsize=7)
    add_box(ax, -11.4, -18.7, 22.8, 0.8, "VSS (M2)", fc="#bbf7d0", ec="#15803d", fontsize=7)

    xs = [-8.4, -2.8, 2.8, 8.4]
    branches = ["Rp1\n(outp)", "Rn1\n(outn)", "Rn2\n(outn)", "Rp2\n(outp)"]
    colors = ["#dbeafe", "#fce7f3", "#fce7f3", "#dbeafe"]
    ecs = ["#1d4ed8", "#be185d", "#be185d", "#1d4ed8"]
    for x, br, fc, ec in zip(xs, branches, colors, ecs):
        add_box(ax, x - 2.255, 6.8, 4.51, 10.1, br, fc=fc, ec=ec, fontsize=7)

    add_box(ax, -8.4, 4.15, 16.8, 0.55, "outp bus (M4, 16.8 um)", fc="#60a5fa", ec="#1d4ed8", fontsize=6.5)
    add_box(ax, -8.4, 5.15, 16.8, 0.55, "outn bus (M4, 16.8 um)", fc="#f472b6", ec="#be185d", fontsize=6.5)

    inp_labels = ["A (4f)\noutp", "B (4f)\noutn", "B (4f)\noutn", "A (4f)\noutp"]
    for x, lbl, fc, ec in zip(xs, inp_labels, colors, ecs):
        add_box(ax, x - 1.795, -3.55, 3.59, 7.10, lbl, fc=fc, ec=ec, fontsize=6.5)

    add_box(ax, -9.4, -4.5, 18.8, 0.5, "tail (M2)", fc="#fed7aa", ec="#c2410c", fontsize=6.5)
    add_box(ax, -10.0, -5.4, 20.0, 0.35, "inp (M2)", fc="#93c5fd", ec="#1d4ed8", fontsize=6)
    add_box(ax, -10.0, -6.3, 20.0, 0.35, "inn (M2)", fc="#f9a8d4", ec="#be185d", fontsize=6)

    add_box(ax, -2.415, -16.1, 4.83, 8.40, "Xtail\nnf=4, W=25.2u\nL=0.5u", fc="#ffedd5", ec="#c2410c", fontsize=7)

    ax.set_xlim(-14, 14)
    ax.set_ylim(-20, 19)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return dict(
        name="Core Plan A (4-Island ABBA + S/D Sep)",
        width_um=22.8,
        height_um=36.4,
        area_um2=round(22.8 * 36.4, 1),
        symmetry="Common-Centroid ABBA (4 separate guard rings)",
        outp_span_um=16.8,
        outn_span_um=16.8,
        est_c_out_total_ff=7.6,
    )


def draw_core_plan_b(ax: plt.Axes) -> dict:
    """Core Plan B: Fused 16-Finger Shared-Guard ABBA + T-Shaped Outline (17.2 x 33.6 um)."""
    ax.set_title(
        "Core Plan B: Fused 16-Finger Shared-Guard ABBA (T-Shape)\n"
        "(Top 17.2u / Mid 9.35u / Bot 4.83u | Common-Centroid | C_out ~ 5.0 fF)",
        fontsize=9.5,
        fontweight="bold",
    )
    add_box(ax, -8.6, -16.8, 17.2, 33.6, "", fc="#f8fafc", ec="#64748b", lw=1.0, ls="--", alpha=0.5)

    add_box(ax, -8.6, 16.0, 17.2, 0.8, "VDD (M2)", fc="#bbf7d0", ec="#15803d", fontsize=7)
    add_box(ax, -4.8, -16.8, 9.6, 0.8, "VSS (M2)", fc="#bbf7d0", ec="#15803d", fontsize=7)

    r_xs = [-6.3, -2.1, 2.1, 6.3]
    branches = ["Rp1\n(outp)", "Rn1\n(outn)", "Rn2\n(outn)", "Rp2\n(outp)"]
    colors = ["#dbeafe", "#fce7f3", "#fce7f3", "#dbeafe"]
    ecs = ["#1d4ed8", "#be185d", "#be185d", "#1d4ed8"]
    for x, br, fc, ec in zip(r_xs, branches, colors, ecs):
        add_box(ax, x - 2.0, 5.6, 4.0, 10.1, br, fc=fc, ec=ec, fontsize=7)

    add_box(ax, -2.1, 4.6, 4.2, 0.55, "outn (4.2u)", fc="#f472b6", ec="#be185d", fontsize=6.5)
    add_box(ax, -6.3, 3.8, 12.6, 0.55, "outp (M4, 12.6u)", fc="#60a5fa", ec="#1d4ed8", fontsize=6.5)

    # Fused 16-finger LVT NMOS array (9.35 x 7.10 um) sharing tail sources at all even columns!
    add_box(ax, -4.675, -3.55, 9.35, 7.10, "", fc="#f1f5f9", ec="#0f172a", lw=1.5)
    add_box(ax, -3.84, -2.5, 1.92, 5.0, "A\n4f", fc="#dbeafe", ec="#1d4ed8", fontsize=6.5)
    add_box(ax, -1.92, -2.5, 3.84, 5.0, "B+B (8f)\ninn/outn", fc="#fce7f3", ec="#be185d", fontsize=6.5)
    add_box(ax, 1.92, -2.5, 1.92, 5.0, "A\n4f", fc="#dbeafe", ec="#1d4ed8", fontsize=6.5)

    add_box(ax, -4.5, -4.3, 9.0, 0.5, "tail (9.0u)", fc="#fed7aa", ec="#c2410c", fontsize=6.5)
    add_box(ax, -4.6, -5.1, 9.2, 0.35, "inp (M2)", fc="#93c5fd", ec="#1d4ed8", fontsize=6)
    add_box(ax, -2.4, -5.8, 4.8, 0.35, "inn (M2)", fc="#f9a8d4", ec="#be185d", fontsize=6)

    add_box(ax, -2.415, -14.8, 4.83, 8.40, "Xtail\nnf=4, W=25.2u\nL=0.5u", fc="#ffedd5", ec="#c2410c", fontsize=7)

    ax.set_xlim(-14, 14)
    ax.set_ylim(-20, 19)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    return dict(
        name="Core Plan B (Fused 16-Finger Shared-Guard ABBA)",
        width_top_um=17.2,
        width_mid_um=9.35,
        width_bot_um=4.83,
        height_um=33.6,
        area_um2=round(17.2 * 33.6, 1),
        symmetry="Common-Centroid ABBA (1 shared active region & guard ring, -25% tail S/D)",
        outp_span_um=12.6,
        outn_span_um=4.2,
        est_c_out_total_ff=5.0,
    )


def draw_core_plan_c(ax: plt.Axes) -> dict:
    """Core Plan C: Left-Right Mirror Split [P-Branch | N-Branch] (17.2 x 32.6 um)."""
    ax.set_title(
        "Core Plan C: Left-Right Mirror Split [P | N]\n"
        "(17.2 x 32.6 um | Zero outp/outn Crossover | C_out,parasitic ~ 4.1 fF)",
        fontsize=9.5,
        fontweight="bold",
    )
    add_box(ax, -8.6, -16.2, 17.2, 32.6, "", fc="#f8fafc", ec="#64748b", lw=1.0, ls="--", alpha=0.5)

    add_box(ax, -8.6, 15.6, 17.2, 0.8, "VDD (M2)", fc="#bbf7d0", ec="#15803d", fontsize=7)
    add_box(ax, -6.5, -16.2, 13.0, 0.8, "VSS (M2)", fc="#bbf7d0", ec="#15803d", fontsize=7)

    r_xs = [-6.3, -2.1, 2.1, 6.3]
    branches = ["Rp1\n(outp)", "Rp2\n(outp)", "Rn1\n(outn)", "Rn2\n(outn)"]
    colors = ["#dbeafe", "#dbeafe", "#fce7f3", "#fce7f3"]
    ecs = ["#1d4ed8", "#1d4ed8", "#be185d", "#be185d"]
    for x, br, fc, ec in zip(r_xs, branches, colors, ecs):
        add_box(ax, x - 2.0, 5.2, 4.0, 10.1, br, fc=fc, ec=ec, fontsize=7)

    add_box(ax, -7.2, 4.1, 5.4, 0.55, "outp (Left)", fc="#60a5fa", ec="#1d4ed8", fontsize=6.5)
    add_box(ax, 1.8, 4.1, 5.4, 0.55, "outn (Right)", fc="#f472b6", ec="#be185d", fontsize=6.5)

    add_box(ax, -3.5 - 2.755, -3.55, 5.51, 7.10, "Xmp (inp/outp)\nnf=8, W=40u", fc="#dbeafe", ec="#1d4ed8", fontsize=7)
    add_box(ax, 3.5 - 2.755, -3.55, 5.51, 7.10, "Xmn (inn/outn)\nnf=8, W=40u", fc="#fce7f3", ec="#be185d", fontsize=7)

    add_box(ax, -4.5, -4.3, 9.0, 0.5, "tail (M2)", fc="#fed7aa", ec="#c2410c", fontsize=6.5)
    add_box(ax, -6.2, -5.2, 5.0, 0.35, "inp (Left)", fc="#93c5fd", ec="#1d4ed8", fontsize=6.5)
    add_box(ax, 1.2, -5.2, 5.0, 0.35, "inn (Right)", fc="#f9a8d4", ec="#be185d", fontsize=6.5)

    add_box(ax, -2.415, -14.2, 4.83, 8.40, "Xtail\nnf=4, W=25.2u\nL=0.5u", fc="#ffedd5", ec="#c2410c", fontsize=7)

    ax.set_xlim(-14, 14)
    ax.set_ylim(-20, 19)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    return dict(
        name="Core Plan C (Left-Right Mirror Split [P | N])",
        width_um=17.2,
        height_um=32.6,
        area_um2=round(17.2 * 32.6, 1),
        symmetry="Left-Right Mirror Symmetric (Zero outp/outn or inp/inn crossover)",
        outp_span_um=4.2,
        outn_span_um=4.2,
        est_c_out_total_ff=4.1,
    )


def draw_half_tank_outline(ax: plt.Axes, cx: float, cy: float, orientation: str, label_prefix: str, color_node: str) -> None:
    """Draw the exact 1:1 silhouette of pll_vco_half_tank_sym9 (37.48 x 16.93 um)."""
    blocks = [
        (-16.3, 4.6, -10.88, -3.09, "8u"),
        (-11.1, 2.6, -8.81, -2.09, "4u"),
        (-7.2, 2.0, -5.88, -1.59, "2u"),
        (-3.6, 2.0, -3.61, -1.46, "1u"),
        (0.0, 2.0, -3.61, -1.46, "1u"),
        (3.6, 2.0, -3.61, -1.46, "1u"),
        (7.2, 2.0, -5.88, -1.59, "2u"),
        (11.1, 2.6, -8.81, -2.09, "4u"),
        (16.3, 4.6, -10.88, -3.09, "8u"),
    ]

    def tr_rect(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if orientation == "recess_down":
            tpts = [(cx + x, cy + y) for x, y in pts]
        elif orientation == "recess_up":
            tpts = [(cx + x, cy - y) for x, y in pts]
        elif orientation == "recess_right":
            tpts = [(cx - y, cy + x) for x, y in pts]
        elif orientation == "recess_left":
            tpts = [(cx + y, cy + x) for x, y in pts]
        else:
            raise ValueError(orientation)
        xs = [p[0] for p in tpts]
        ys = [p[1] for p in tpts]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

    bx, by, bw, bh = tr_rect(-18.74, -12.30, 18.74, 4.63)
    add_box(ax, bx, by, bw, bh, "", fc="#f8fafc", ec="#94a3b8", lw=1.0, ls="--", alpha=0.45)

    ux, uy, uw, uh = tr_rect(-18.74, 0.0, 18.74, 4.63)
    add_box(ax, ux, uy, uw, uh, f"{label_prefix}\nvss / b0..b4 / vctrl", fc="#dcfce7", ec="#15803d", fontsize=6.5)

    for x_c, w_c, y_b, y_t, u_lbl in blocks:
        mx, my, mw, mh = tr_rect(x_c - w_c / 2, y_b, x_c + w_c / 2, y_t)
        add_box(ax, mx, my, mw, mh, u_lbl, fc="#fef08a", ec="#ca8a04", fontsize=5.5)

    vx, vy, vw, vh = tr_rect(-3.85, -12.30, 3.85, -3.90)
    add_box(ax, vx, vy, vw, vh, "Varactor\n(in recess)", fc="#bae6fd", ec="#0284c7", fontsize=6.5)

    nx, ny, nw, nh = tr_rect(-2.87, -11.4, 2.87, -10.6)
    add_box(ax, nx, ny, nw, nh, "node", fc=color_node, ec="#111827", fontsize=6.5)


def draw_stage_docking_lr(ax: plt.Axes) -> dict:
    """Docking Plan I: Left-Right Interlocked Inward-Recess (~46.5 x 37.5 um)."""
    ax.set_title(
        "Stage Docking Plan I: Left-Right Interlocked Inward-Recess\n"
        "(46.5 x 37.5 um = 1742 um^2 | T-Shape Delay Core interlocks with Tank recesses | < 1.5u node wire)",
        fontsize=9.5,
        fontweight="bold",
    )
    # T-shaped Delay Core in center:
    # Top resistors: x in [-8.3, +8.3], y in [5.2, 15.6]
    add_box(ax, -8.3, 5.2, 8.1, 10.4, "Rp1, Rp2\n(outp loads)", fc="#dbeafe", ec="#1d4ed8", fontsize=6.5)
    add_box(ax, 0.2, 5.2, 8.1, 10.4, "Rn1, Rn2\n(outn loads)", fc="#fce7f3", ec="#be185d", fontsize=6.5)
    # Middle fused 16-finger LVT input pair: x in [-4.68, +4.68], y in [-3.55, +3.55]
    add_box(ax, -4.68, -3.55, 9.36, 7.10, "Diff Pair\n(9.35 x 7.1u)", fc="#ede9fe", ec="#5b21b6", fontsize=6.5)
    # Bottom tail current source: x in [-2.42, +2.42], y in [-14.2, -5.8]
    add_box(ax, -2.42, -14.2, 4.84, 8.40, "Xtail\n(4.8 x 8.4u)", fc="#ffedd5", ec="#c2410c", fontsize=6.5)

    # Because the middle of the Delay Core is only +-4.68 um wide, Tank-P and Tank-N slide INWARD
    # so their varactor inner edges (cx +- 12.30) sit at x = +-6.30 um (cx = +-18.60 um)!
    # Notice: at y in [5.2, 15.6] (where the resistors are +-8.3 um), the Tank MIMs are 2u/4u/8u
    # whose inner edges are at cx +- (5.88..10.88), leaving plenty of room!
    draw_half_tank_outline(ax, cx=-18.60, cy=0.0, orientation="recess_right", label_prefix="Tank-P", color_node="#60a5fa")
    draw_half_tank_outline(ax, cx=18.60, cy=0.0, orientation="recess_left", label_prefix="Tank-N", color_node="#f472b6")

    # Direct short M4 straps (< 1.5 um!) from Delay outp/outn into the two facing recess nodes!
    add_box(ax, -7.8, 2.8, 3.2, 2.4, "outp M4", fc="#60a5fa", ec="#1d4ed8", alpha=0.75, fontsize=6.5)
    add_box(ax, 4.6, 2.8, 3.2, 2.4, "outn M4", fc="#f472b6", ec="#be185d", alpha=0.75, fontsize=6.5)

    ax.set_xlim(-27, 27)
    ax.set_ylim(-21, 21)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return dict(
        name="Stage Docking Plan I (Left-Right Interlocked Inward-Recess / 左右互补咬合式)",
        width_um=46.46,
        height_um=37.48,
        area_um2=round(46.46 * 37.48, 1),
        aspect_ratio=round(46.46 / 37.48, 2),
        highlights=[
            "T-shaped Delay Core (wide top resistors 16.6u, narrow mid diff pair 9.35u, narrow bot tail 4.83u) interlocks with the two inward-facing Half-Tank recesses",
            "Half-Tank width (37.48 um) matches Delay Core height (~33.6 um) almost 1:1",
            "outp and outn M4 connections from Delay Core to Half-Tank recess `node` are < 1.5 um long",
            "All digital control buses (b0..b4, vctrl) sit on the far left/right outer edges",
        ],
    )


def draw_stage_docking_tb(ax: plt.Axes) -> dict:
    """Docking Plan II: Top-Bottom Opposing-Recess (37.5 x 68.1 um)."""
    ax.set_title(
        "Stage Docking Plan II: Top-Bottom Opposing-Recess\n"
        "(37.5 x 68.1 um = 2551 um^2 | Top Tank-P + Mid Delay + Bot Tank-N)",
        fontsize=9.5,
        fontweight="bold",
    )
    add_box(ax, -8.6, -16.8, 17.2, 33.6, "Differential Delay Core\n(17.2 x 33.6 um)", fc="#ede9fe", ec="#5b21b6", fontsize=7.5)

    draw_half_tank_outline(ax, cx=0.0, cy=29.4, orientation="recess_down", label_prefix="Tank-P (Top)", color_node="#60a5fa")
    draw_half_tank_outline(ax, cx=0.0, cy=-29.4, orientation="recess_up", label_prefix="Tank-N (Bot)", color_node="#f472b6")

    add_box(ax, -1.5, 4.0, 3.0, 14.5, "M4 outp", fc="#60a5fa", ec="#1d4ed8", alpha=0.55, fontsize=6.5)
    add_box(ax, -1.5, -18.5, 3.0, 14.5, "M4 outn", fc="#f472b6", ec="#be185d", alpha=0.55, fontsize=6.5)

    ax.set_xlim(-26, 26)
    ax.set_ylim(-37, 37)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.4)
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    return dict(
        name="Stage Docking Plan II (Top-Bottom Opposing-Recess / 上下对咬夹心式)",
        width_um=37.48,
        height_um=68.06,
        area_um2=round(37.48 * 68.06, 1),
        aspect_ratio=round(37.48 / 68.06, 2),
        highlights=[
            "Narrow horizontal pitch (37.48 um), tall vertical height (68.06 um)",
            "outn has to route downward across the input/tail region (~18 um M4) to reach bottom Tank-N recess",
        ],
    )


def main() -> None:
    fig = plt.figure(figsize=(18, 14), dpi=150)
    gs = fig.add_gridspec(2, 6, height_ratios=[1.0, 1.05], hspace=0.28, wspace=0.35)

    ax_a = fig.add_subplot(gs[0, 0:2])
    ax_b = fig.add_subplot(gs[0, 2:4])
    ax_c = fig.add_subplot(gs[0, 4:6])

    ax_lr = fig.add_subplot(gs[1, 0:3])
    ax_tb = fig.add_subplot(gs[1, 3:6])

    meta_a = draw_core_plan_a(ax_a)
    meta_b = draw_core_plan_b(ax_b)
    meta_c = draw_core_plan_c(ax_c)
    meta_lr = draw_stage_docking_lr(ax_lr)
    meta_tb = draw_stage_docking_tb(ax_tb)

    fig.suptitle(
        "VCO Differential Delay Stage (pll_vco_delay_r6) & Half-Tank Docking Floorplan Candidates (1:1 Scale)",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )

    png_path = PLAN_DIR / "delay_stage_plan.png"
    json_path = PLAN_DIR / "delay_stage_plan.json"
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)

    plan_data = dict(
        core_candidates=[meta_a, meta_b, meta_c],
        stage_docking_candidates=[meta_lr, meta_tb],
        recommendation=dict(
            core="Core Plan B (Fused 16-Finger Shared-Guard ABBA) or Core Plan C (Left-Right Mirror Split [P | N])",
            docking="Stage Docking Plan I (Left-Right Interlocked Inward-Recess / 左右互补咬合式)",
        ),
    )
    json_path.write_text(json.dumps(plan_data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {png_path} and {json_path}")


if __name__ == "__main__":
    main()
