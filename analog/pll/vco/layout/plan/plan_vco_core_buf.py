#!/usr/bin/env python3
"""Plan the 4-Stage VCO + 4-Buffer Core (`pll_vco_core_sym9_s32p5`) in SKY130 PDK.

Revised Architecture per User Feedback:
1. Central Abutted Tail Current Bank (`[Xbmp | Xbtail_L | Delay_Xt | Xbtail_R | Xbmn]` at `y_stage = -9.80 um`):
   - All tail current sources (`Xbtail_L` at `x_stage = -4.31 um`, `Delay_Xt` at `0.00 um`, `Xbtail_R` at `+4.31 um`)
     are grouped together on the INSIDE around the quadrant axis `x_stage = 0.00 um`, sharing vertical guard ring
     bars (`[+-2.465, +-2.635] um`), L=0.50 um dummy poly fingers, and a single straight M1 `vbias` gate bar!
   - Buffer differential pairs (`Xbmp` at `-7.60 um`, `Xbmn` at `+7.60 um`) abut `Xbtail_L/R` on the outside
     (`[+-5.985, +-6.155] um`), sharing a single straight M2 `tail_buf` bar (`[-8.56, +8.56] um` at `y_stage = -10.80 um`).
   - Oscillator vertical trunks (`dx_in = +-3.55/+-4.15 um`, `dx_out = +-6.45/+-7.05 um`) run on M3 across the
     lower active row (`y_stage in [-12.40, -4.50/+3.00] um`, directly tapping `Xbmp/Xbmn` M3 gate bar at
     `y_stage = -8.025 um`) before dropping to M1 at `y_stage = -12.40 um` for the central M1/M2 crossbar.
2. Outward-Shifted Cap-Bank Switches (`tank_cx = 22.70 um`, `+1.90 um`) + Outer Dummy Resistors (`x_stage = +-16.65 um`):
   - Shifting each Half-Tank outward by `1.90 um` (`tank_cx: 20.80 -> 22.70 um`, `DX: 24.15 -> 26.05 um`) opens room
     underneath the `b3/b4` top MIM capacitors at `x_stage = +-16.65 um` for a pair of full-size dummy resistors
     (`Xrdum_L, Xrdum_R`) with grounded guard rings flanking the Buffer load resistors (`Xbrp, Xbrn` at `+-12.00 um`).
"""

from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches

PLAN_DIR = Path(__file__).resolve().parent


def build_plan() -> dict:
    dx_q = 26.05
    dy_q = 19.35
    return {
        "cell": "pll_vco_core_sym9_s32p5",
        "bbox_um": [-52.4, -39.6, 52.4, 39.6],
        "width_um": 104.8,
        "height_um": 79.2,
        "area_um2": 8300.16,
        "quadrant_centers_um": {
            "Q0_top_left": [-dx_q, +dy_q],
            "Q1_top_right": [+dx_q, +dy_q],
            "Q2_bot_right": [+dx_q, -dy_q],
            "Q3_bot_left": [-dx_q, -dy_q],
        },
        "per_quadrant_stage_coords_um": {
            "resistor_array_8col": {
                "delay_loads_Xrp12_Xrn12": [-7.20, -2.40, +2.40, +7.20],
                "buffer_loads_Xbrp_Xbrn": [-12.00, +12.00],
                "dummy_loads_Xrdum": [-16.65, +16.65],
                "y_span": [+5.735, +15.96],
            },
            "middle_row": {
                "delay_diff_pair_Xp_Xn": {"x_span": [-5.07, +5.07], "y_span": [-3.37, +3.37]},
                "varactors": {"x_span_each": [10.55, 18.65], "y_span": [-3.76, +3.76]},
            },
            "lower_abutted_5block_row": {
                "delay_tail_Xt": {"center": [0.00, -9.80], "x_span": [-2.635, +2.635], "y_span": [-13.82, -5.78]},
                "buffer_split_tail_XbtailL_R": {
                    "centers": [[-4.31, -9.80], [+4.31, -9.80]],
                    "x_span_each": [2.465, 6.155],
                    "y_span": [-12.17, -7.43],
                    "note": "Directly abuts Delay_Xt on the inside ([+-2.465, +-2.635] um); shares straight M1 vbias bar",
                },
                "buffer_diff_pair_Xbmp_Xbmn": {
                    "centers": [[-7.60, -9.80], [+7.60, -9.80]],
                    "x_span_each": [5.985, 9.215],
                    "y_span": [-12.17, -7.43],
                    "note": "Directly abuts Xbtail_L/R ([+-5.985, +-6.155] um); shares straight M2 tail_buf bar [-8.56, +8.56]",
                },
            },
        },
    }


def draw_plan(plan: dict, out_png: Path) -> None:
    fig, ax = plt.subplots(figsize=(14, 11), dpi=160)
    ax.set_xlim(-56, 56)
    ax.set_ylim(-43, 43)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", alpha=0.35)
    ax.set_title(
        "Revised PLL VCO + 4x CML Buffer Core Plan (`pll_vco_core_sym9_s32p5`)\n"
        "Inner Abutted Tail Bank `[Xbmp | Xbtail_L | Xt | Xbtail_R | Xbmn]` + Outer Dummy Resistors (`104.8 × 79.2 µm`)",
        fontsize=11.5,
        fontweight="bold",
    )
    ax.set_xlabel("X (µm)")
    ax.set_ylabel("Y (µm)")

    ax.add_patch(
        patches.Rectangle((-52.4, -39.6), 104.8, 79.2, fill=False, edgecolor="black", linewidth=2.0, linestyle="--")
    )

    dx_q = 26.05
    dy_q = 19.35
    quads = [
        ("Q0 (X0 + Xbuf0)", -dx_q, +dy_q, +1),
        ("Q1 (X1 + Xbuf1)", +dx_q, +dy_q, +1),
        ("Q2 (X2 + Xbuf2)", +dx_q, -dy_q, -1),
        ("Q3 (X3 + Xbuf3)", -dx_q, -dy_q, -1),
    ]

    def add_box(x0, y0, x1, y1, color, label=None, alpha=0.45, ec="black", lw=1.0):
        rx0, rx1 = min(x0, x1), max(x0, x1)
        ry0, ry1 = min(y0, y1), max(y0, y1)
        rect = patches.Rectangle((rx0, ry0), rx1 - rx0, ry1 - ry0, facecolor=color, edgecolor=ec, alpha=alpha, lw=lw)
        ax.add_patch(rect)
        if label:
            ax.text((rx0 + rx1) / 2, (ry0 + ry1) / 2, label, ha="center", va="center", fontsize=6.0, fontweight="bold")

    for qname, qx, qy, sy in quads:
        for s_lr in (-1, +1):
            # Half-Tank MIM visual block
            add_box(qx + s_lr * 11.7, qy - sy * 18.6, qx + s_lr * 22.9, qy + sy * 18.6, "#cfd8dc", None, alpha=0.18, ec="#78909c")
            # Varactor
            add_box(qx + s_lr * 10.55, qy - sy * 3.76, qx + s_lr * 18.65, qy + sy * 3.76, "#80cbc4", "Varactor", alpha=0.45)
            # Buffer Load Resistors (+-12.00)
            b_lbl = "Xbuf.Rp\n(bkn)" if s_lr < 0 else "Xbuf.Rn\n(bkp)"
            add_box(
                qx + s_lr * 9.93,
                qy + sy * 5.74,
                qx + s_lr * 14.07,
                qy + sy * 15.42,
                "#ffab91",
                b_lbl,
                alpha=0.75,
                ec="#d84315",
                lw=1.3,
            )
            # Outer Dummy Resistors (+-16.65)
            add_box(
                qx + s_lr * 14.58,
                qy + sy * 5.74,
                qx + s_lr * 18.72,
                qy + sy * 15.42,
                "#e0e0e0",
                "R_dum",
                alpha=0.75,
                ec="#616161",
                lw=1.2,
            )
            # Buffer Split Tail on INSIDE (+-4.31)
            add_box(
                qx + s_lr * 2.465,
                qy + sy * (-12.17),
                qx + s_lr * 6.155,
                qy + sy * (-7.43),
                "#ffd54f",
                "Xbuf\nTail/2",
                alpha=0.85,
                ec="#f57f17",
                lw=1.4,
            )
            # Buffer Diff Pair abutting outside of Tail (+-7.60)
            m_lbl = "Xbuf.Mp" if s_lr < 0 else "Xbuf.Mn"
            add_box(
                qx + s_lr * 5.985,
                qy + sy * (-12.17),
                qx + s_lr * 9.215,
                qy + sy * (-7.43),
                "#ff8a65",
                m_lbl,
                alpha=0.85,
                ec="#bf360c",
                lw=1.4,
            )

        # Delay stage blocks
        add_box(qx - 5.07, qy - sy * 3.37, qx + 5.07, qy + sy * 3.37, "#90caf9", "Delay Xp | Xn", alpha=0.55)
        add_box(qx - 2.635, qy + sy * (-13.82), qx + 2.635, qy + sy * (-5.78), "#ce93d8", "Delay\nXt", alpha=0.70)
        add_box(qx - 9.28, qy + sy * 5.74, qx + 9.28, qy + sy * 15.96, "#a5d6a7", "Delay Loads (4x)", alpha=0.50)

    ax.axhline(0, color="#1565c0", lw=2.0)
    fig.tight_layout()
    fig.savefig(out_png)
    plt.close(fig)


def main() -> None:
    plan = build_plan()
    json_path = PLAN_DIR / "vco_core_buf_plan.json"
    png_path = PLAN_DIR / "vco_core_buf_plan.png"
    json_path.write_text(json.dumps(plan, indent=2) + "\n")
    draw_plan(plan, png_path)
    print(f"Wrote {json_path} and {png_path}")


if __name__ == "__main__":
    main()
