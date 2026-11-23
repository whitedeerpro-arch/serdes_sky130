"""Generate 1:1 physical floorplan for the 4-Stage Ring VCO (`pll_vco_ring4_sym9_s32p5`).

Schematic placement of the sym9 bare ring; no comparison with the rejected large ring.

Outputs:
- analog/pll/vco/layout/plan/vco_ring4_plan.png
- analog/pll/vco/layout/plan/vco_ring4_plan.json
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
            x0 + w / 2,
            y0 + h / 2,
            label,
            ha="center",
            va="center",
            fontsize=fontsize,
            color=text_color,
            fontweight="bold",
        )


def draw_stage_macro(ax: plt.Axes, cx: float, cy: float, mirror_y: bool, q_name: str, sub_lbl: str) -> None:
    """Draw 1:1 outline of one interlocked VCO stage (`50.86 x 37.48 um` active body)."""
    sy = -1.0 if mirror_y else 1.0

    def y_map(y0: float, y1: float) -> tuple[float, float]:
        ya, yb = sy * y0 + cy, sy * y1 + cy
        return min(ya, yb), abs(yb - ya)

    # Stage outer active box (-25.43..+25.43, -18.74..+18.74)
    by, bh = y_map(-18.74, 18.74)
    add_box(ax, cx - 25.43, by, 50.86, bh, "", fc="#f8fafc", ec="#64748b", lw=1.1, ls="--", alpha=0.55)

    # Left & Right Half-Tanks
    ty, th = y_map(-18.74, 18.74)
    add_box(ax, cx - 25.43, ty, 15.6, th, f"{q_name} Tank-P\n(9 MIMs +\nVaractor)", fc="#fef08a", ec="#ca8a04", fontsize=6.0)
    add_box(ax, cx + 9.83, ty, 15.6, th, f"{q_name} Tank-N\n(9 MIMs +\nVaractor)", fc="#fef08a", ec="#ca8a04", fontsize=6.0)

    # Delay Core (Loads, Diff Pair, Tail)
    ry, rh = y_map(5.2, 16.0)
    add_box(ax, cx - 9.4, ry, 18.8, rh, f"{q_name} Loads (Rp/Rn)\n+ VDD", fc="#dcfce7", ec="#15803d", fontsize=6.0)

    dy, dh = y_map(-3.55, 3.55)
    add_box(ax, cx - 5.25, dy, 10.5, dh, f"{q_name} Diff Pair\n({sub_lbl})", fc="#ede9fe", ec="#5b21b6", fontsize=6.0)

    tly, tlh = y_map(-15.6, -5.8)
    add_box(ax, cx - 2.42, tly, 4.84, tlh, "Xtail", fc="#ffedd5", ec="#c2410c", fontsize=5.5)


def main() -> None:
    fig, ax_ring = plt.subplots(figsize=(10, 8.5), dpi=150)

    # Right Panel: Detailed 1:1 Floorplan of the New 2x2 Interlocked 4-Stage Ring
    ax_ring.set_title(
        "New 4-Stage Ring VCO (pll_vco_ring4_sym9_s32p5) Detailed 1:1 Floorplan\n"
        "(DX = +-26.2 um, DY = +-21.0 um | Central M3/M4 Ring Crossbar + Vertical M2 Control Columns)",
        fontsize=10.5,
        fontweight="bold",
    )

    DX, DY = 26.20, 21.00
    draw_stage_macro(ax_ring, -DX, +DY, False, "X0 (Q0)", "q3n/p -> q0p/n")
    draw_stage_macro(ax_ring, +DX, +DY, False, "X1 (Q1)", "q0p/n -> q1p/n")
    draw_stage_macro(ax_ring, +DX, -DY, True,  "X2 (Q2)", "q1p/n -> q2p/n")
    draw_stage_macro(ax_ring, -DX, -DY, True,  "X3 (Q3)", "q2p/n -> q3p/n")

    # Central horizontal ring routing corridor (y in [-5.2, +5.2] um)
    add_box(
        ax_ring,
        -35.0,
        -5.2,
        70.0,
        10.4,
        "Central Inter-Stage Ring Crossbar (y in [-5.2, +5.2] um)\n"
        "M4 Vertical Stage I/O Trunks + M3 Horizontal Ring Tracks (X0->X1->X2->X3->X0) + VSS/vbias Spine",
        fc="#f3e8ff",
        ec="#7e22ce",
        alpha=0.85,
        fontsize=6.5,
    )

    # Bottom shared M3 control bus (b0..b4, vctrl) at y in [-44.5, -40.8] um
    add_box(
        ax_ring,
        -51.45,
        -44.6,
        102.9,
        3.8,
        "Bottom Shared M3 Control Bus: b0, b1, b2, b3, b4, vctrl (ties all 4 vertical M2 Tank control columns)",
        fc="#dcfce7",
        ec="#15803d",
        fontsize=6.5,
    )

    ax_ring.set_xlim(-58, 58)
    ax_ring.set_ylim(-50, 46)
    ax_ring.set_aspect("equal")
    ax_ring.grid(True, linestyle=":", alpha=0.4)
    ax_ring.set_xlabel("x (um)")
    ax_ring.set_ylabel("y (um)")

    png_path = PLAN_DIR / "vco_ring4_plan.png"
    json_path = PLAN_DIR / "vco_ring4_plan.json"
    fig.savefig(png_path, bbox_inches="tight")
    plt.close(fig)

    plan_meta = dict(
        cell="pll_vco_ring4_sym9_s32p5",
        new_bbox_um=[103.3, 89.2],
        new_area_um2=9214.4,
        quadrant_centers_um=dict(
            X0=[-26.2, 21.0],
            X1=[26.2, 21.0],
            X2=[26.2, -21.0],
            X3=[-26.2, -21.0],
        ),
    )
    json_path.write_text(json.dumps(plan_meta, indent=2) + "\n")
    print(f"wrote {png_path} and {json_path}")


if __name__ == "__main__":
    main()
