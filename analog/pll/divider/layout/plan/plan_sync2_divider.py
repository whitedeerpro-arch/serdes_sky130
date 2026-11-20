#!/usr/bin/env python3
"""1:1 Physical Floorplan for pll_sync_prescaler8_2stack_pdk.

Uses exact measured PDK block bounding boxes from:
  - results/layout/sync2_divider/pdk_blocks_r5/summary.json
  - PDK device probes for 1p41 (4k/12k), 2p85 (580/960), MIM (15x15/20x20), and OTA/replica FETs.

Generates:
  - analog/pll/divider/layout/plan/sync2_floorplan.png
  - analog/pll/divider/layout/plan/sync2_plan.json
"""
from __future__ import annotations

import json
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as patches

OUT_DIR = Path(__file__).resolve().parent


def box(ax, x, y, w, h, text, fc, ec, lw=1.2, fs=7.2, alpha=0.90, ls="-"):
    r = patches.Rectangle((x, y), w, h, facecolor=fc, edgecolor=ec, linewidth=lw, linestyle=ls, alpha=alpha)
    ax.add_patch(r)
    if text:
        ax.text(x + w / 2.0, y + h / 2.0, text, ha="center", va="center", fontsize=fs, weight="bold", color="#0f172a")


def build_floorplan() -> dict:
    fig, ax = plt.subplots(figsize=(12.5, 9.5), dpi=160)

    # Exact measured PDK block sizes (um)
    col_w = 25.80
    col_gap = 4.20
    pitch = col_w + col_gap  # 30.00 um

    # Core 3-bit array: Col 1 (Bit-0), Col 2 (Bit-1), Col 3 (Bit-2)
    x_bay = 0.0        # Bias + AC-coupling + Clock front-end bay, width = 40.0 um
    w_bay = 40.0
    x_cols = [w_bay + 6.0 + i * pitch for i in range(3)]  # [46.0, 76.0, 106.0]

    # Vertical stack of Core Columns (y=0 at bottom of Mux row):
    y_mux = 0.0        # h = 52.43
    y_m_bot = 55.6     # Master latch: h = 39.88 -> top = 95.48
    y_clk = 95.5       # Shielded M3 clock spine corridor: h = 6.00 (95.5 .. 101.5)
    y_s_bot = 101.5    # Slave latch (mirrored Y so ct/ch face spine): h = 39.88 -> top = 141.38
    y_buf = 144.6      # Out buffer: h = 32.51 -> top = 177.11
    total_h = 177.11
    total_w = x_cols[-1] + col_w  # 131.80 um

    # Outer M4/M5 power ring hint
    box(ax, -4.0, -4.0, total_w + 8.0, total_h + 8.0, "", "#f8fafc", "#64748b", lw=1.2, ls="--", alpha=0.45)

    # 1. Left Bay (x = 0 .. 40.0 um): Replica Bias + AC Coupling + Clock Front-End
    #    Bottom (0 .. 52): Xckpre (25.8 x 34.19) + XRref (15.45 x 16.40) / XRrep (15.45 x 19.80)
    box(ax, 0.0, 0.0, 25.80, 34.19, "Xckpre\n25.80 x 34.19\n(rload=850)", "#dcfce7", "#15803d")
    box(ax, 27.2, 0.0, 12.8, 22.0, "8-T OTA +\nXrep_d/c", "#fef3c7", "#b45309", fs=6.5)
    box(ax, 27.2, 24.0, 12.8, 28.0, "Xref + XRref\n+ XRrep\n(2p85)", "#fce7f3", "#9d174d", fs=6.4)
    #    Mid-low (54 .. 95): Xckdrv (25.8 x 37.51) centered just below clock spine + Xcomp below/side
    box(ax, 0.0, 56.0, 25.80, 37.51, "Xckdrv\n25.80 x 37.51\n(rload=550)", "#bbf7d0", "#166534")
    #    Right of Xckdrv or integrated: two 4k 1p41 (14.01 x 28.72) rotated/vertical along gap or upper bay
    box(ax, 26.8, 56.0, 14.01, 28.72, "Xrbp\n4k 1p41", "#f3e8ff", "#7e22ce", fs=6.2)
    #    Mid-high (102 .. 136): Two 15x15 MIM AC coupling caps (17.16 x 15.40 each, stacked vertically) + Xrbn
    box(ax, 0.0, 102.0, 17.16, 15.40, "Xccp\n15x15 MIM\n17.2x15.4", "#e0e7ff", "#3730a3", fs=6.5)
    box(ax, 0.0, 119.0, 17.16, 15.40, "Xccn\n15x15 MIM\n17.2x15.4", "#e0e7ff", "#3730a3", fs=6.5)
    box(ax, 20.0, 102.0, 14.01, 28.72, "Xrbn\n4k 1p41", "#f3e8ff", "#7e22ce", fs=6.2)
    #    Top-left (138 .. 177): Xcomp 20x20 MIM (22.16 x 20.40) + two 12k 1p41 XRls (14.01 x 63.49)
    #    Wait: 12k 1p41 is 63.49 um long -> place HORIZONTALLY (63.49 x 14.01) cleanly in dedicated top bias strip y=181..213 OR place vertically in dedicated Col -1!
    #    Let's put dedicated top bias strip y = 180.5 .. 212.5 spanning x = 0 .. 131.8 um (keeping height = 212.5, OR widening x_bay by 16 um so XRls fits vertically inside Left Bay!).
    #    Wait: widening x_bay from 40 -> 58 um puts TWO vertical 12k 1p41 + Xcomp cleanly in Left Bay, keeping top flush at 177.11 um!
    ax.clear()

    # Refined Layout: Left Bias/AC Bay (w = 58.0 um) + 3 Synchronized Columns (3 x 30.0 = 85.8 um) -> Total 143.8 x 177.1 um
    w_bay = 56.0
    x_cols = [w_bay + 4.0 + i * pitch for i in range(3)]  # [60.0, 90.0, 120.0]
    total_w = x_cols[-1] + col_w  # 145.80 um

    box(ax, -4.0, -4.0, total_w + 8.0, total_h + 8.0, "", "#f8fafc", "#64748b", lw=1.2, ls="--", alpha=0.45)

    # Left Sub-Col L0 (x = 0 .. 25.8): Outer-Edge Clock Front-End (zero-crossing clkp/clkn entry!)
    x_ck = 0.0
    box(ax, x_ck, 0.0, 25.80, 34.19, "Xckpre\n25.80 x 34.19\n(wn=20, r=850)", "#dcfce7", "#15803d")
    box(ax, x_ck, 37.5, 25.80, 37.51, "Xckdrv\n25.80 x 37.51\n(wn=32, r=550)", "#bbf7d0", "#166534")
    box(ax, x_ck + 4.3, 80.0, 17.16, 15.40, "Xccp\n15x15 MIM", "#e0e7ff", "#3730a3", fs=6.5)
    box(ax, x_ck + 4.3, 98.0, 17.16, 15.40, "Xccn\n15x15 MIM", "#e0e7ff", "#3730a3", fs=6.5)
    box(ax, x_ck + 1.8, 120.0, 22.16, 20.40, "Xcomp (vbias_ck)\n20x20 MIM\n22.16 x 20.40\n(M3/M4 keepout)", "#c7d2fe", "#312e81", fs=6.4)

    # Left Sub-Col L1 (x = 27.6 .. 56.8): Replica Bias + 4k/12k 1p41 Resistors feeding Clock Spine directly
    x_rb = 27.6
    box(ax, x_rb, 0.0, 14.01, 63.49, "XRls_p\n12k 1p41\n14.01x63.49", "#f3e8ff", "#7e22ce", fs=6.5)
    box(ax, x_rb + 15.2, 0.0, 14.01, 63.49, "XRls_n\n12k 1p41\n14.01x63.49", "#f3e8ff", "#7e22ce", fs=6.5)
    box(ax, x_rb, 65.5, 29.2, 28.0, "Replica Half-Latch\n+ 8-T OTA + Xls_p/n\n+ XRref (580) + XRrep (960)", "#fef3c7", "#b45309", fs=6.2)
    box(ax, x_rb, 104.0, 28.72, 14.01, "Xrbp (4k 1p41)\n28.72 x 14.01", "#f3e8ff", "#7e22ce", fs=6.3)
    box(ax, x_rb, 120.0, 28.72, 14.01, "Xrbn (4k 1p41)\n28.72 x 14.01", "#f3e8ff", "#7e22ce", fs=6.3)

    # 3 Synchronized Columns: [Col1: Bit-0] [Col2: Bit-1] [Col3: Bit-2]
    mux_names = ["Xt2\n(Mux2 2-stack)\n25.80 x 52.43", "Xx1\n(Mux2 2-stack)\n25.80 x 52.43", "Xx2\n(Mux2 2-stack)\n25.80 x 52.43"]
    dff_names = ["Xff0", "Xff1", "Xff2"]
    buf_names = ["Xq2buf\n25.80 x 32.51", "Xq4buf\n25.80 x 32.51", "Xq8buf\n25.80 x 32.51"]

    for i, xc in enumerate(x_cols):
        box(ax, xc, y_mux, col_w, 52.43, mux_names[i], "#fde68a", "#b45309", fs=7.0)
        box(ax, xc, y_m_bot, col_w, 39.88, f"{dff_names[i]} Master\n(sync2_latch_pdk)\n25.80 x 39.88", "#bae6fd", "#0369a1", fs=6.8)
        box(ax, xc + 2.0, y_m_bot + 36.2, 5.0, 2.8, "Cseed", "#fecaca", "#b91c1c", fs=5.5)
        box(ax, xc, y_s_bot, col_w, 39.88, f"{dff_names[i]} Slave (flip-Y)\n(sync2_latch_pdk)\n25.80 x 39.88", "#7dd3fc", "#0369a1", fs=6.8)
        box(ax, xc, y_buf, col_w, 32.51, buf_names[i], "#dcfce7", "#15803d", fs=7.0)

    # Shielded M3 Differential Clock Spine (y = 95.5 .. 101.5)
    box(ax, 23.0, y_clk, total_w - 23.0, 6.0, "Shielded M3 Clock Spine: VSS | ckp | VSS | ckn | VSS (Zero-Skew Tap to Xff0 / Xff1 / Xff2)", "#fee2e2", "#dc2626", fs=7.0, alpha=0.88)

    # Power M4/M5 trunk markers
    for y_p, lbl in ((-3.5, "M4 VSS / M5 Vertical Mesh"), (total_h + 1.5, "M4 VDD / M5 Vertical Mesh")):
        ax.plot([-2, total_w + 2], [y_p, y_p], color="#0284c7", lw=3.0)
        ax.text(total_w / 2, y_p + (1.0 if y_p > 0 else -2.2), lbl, ha="center", va="center", fontsize=7.0, color="#0369a1", weight="bold")

    # Port callouts (outward arrows for outputs)
    ax.annotate("clkp/clkn IN\n(from VCO b0)", xy=(x_ck, 14.0), xytext=(-12.0, 14.0),
                arrowprops=dict(arrowstyle="->", lw=1.6, color="#15803d"), fontsize=7.5, weight="bold", color="#15803d", va="center", ha="right")
    for xc, qnm in zip(x_cols, ("q2p/q2n\n(1 GHz)", "q4p/q4n\n(500 MHz)", "q8p/q8n\n(250 MHz)")):
        ax.annotate(qnm, xy=(xc + col_w / 2, total_h + 14.0), xytext=(xc + col_w / 2, y_buf + 32.51),
                    arrowprops=dict(arrowstyle="->", lw=1.5, color="#15803d"), fontsize=7.5, weight="bold", color="#15803d", ha="center", va="bottom")

    ax.set_xlim(-34, total_w + 10)
    ax.set_ylim(-14, total_h + 26)
    ax.set_aspect("equal")
    ax.set_xlabel("X (um)", fontsize=9)
    ax.set_ylabel("Y (um)", fontsize=9)
    ax.set_title(f"pll_sync_prescaler8_2stack_pdk 1:1 Floorplan ({total_w:.1f} x {total_h:.1f} um = {total_w*total_h:.0f} um2)", fontsize=10.5, weight="bold")
    ax.grid(True, linestyle=":", alpha=0.35)
    fig.tight_layout()

    png_path = OUT_DIR / "sync2_floorplan.png"
    fig.savefig(png_path, dpi=160)
    plt.close(fig)

    plan = {
        "name": "pll_sync_prescaler8_2stack_pdk Floorplan (Symmetric Clock-Spine 3-Column Matrix + Replica/AC Bay)",
        "total_size_um": [round(total_w, 2), round(total_h, 2)],
        "area_um2": round(total_w * total_h, 1),
        "column_pitch_um": pitch,
        "core_column_width_um": col_w,
        "left_bay_width_um": w_bay,
        "verified_pdk_blocks_um": {
            "sync2_buf_out_pdk": [25.80, 32.51],
            "sync2_buf_ckpre_pdk": [25.80, 34.19],
            "sync2_buf_ckdrv_pdk": [25.80, 37.51],
            "sync2_latch_pdk": [25.80, 39.88],
            "sync2_mux2_pdk": [25.80, 52.43],
        },
        "remaining_blocks_to_build": [
            "sync2_dff_pdk (2x sync2_latch_pdk + physical Cseed implementation)",
            "sync2_ck_replica_bias_pdk (XRls_p/n 12k 1p41 + XRref/XRrep 2p85 + 8-T OTA + 20x20 MIM Xcomp)",
            "sync2_ck_frontend_pdk (Xckpre + Xckdrv + 2x 15x15 MIM + 2x 4k 1p41)",
            "pll_sync_prescaler8_2stack_pdk (top assembly + M3 shielded clock spine + M4/M5 power mesh)",
        ],
    }
    (OUT_DIR / "sync2_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(f"Wrote {png_path} and sync2_plan.json ({total_w:.2f} x {total_h:.2f} um)")
    return plan


if __name__ == "__main__":
    build_floorplan()
