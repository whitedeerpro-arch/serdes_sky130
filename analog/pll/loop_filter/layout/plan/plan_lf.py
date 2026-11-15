#!/usr/bin/env python3
"""True 1:1 SKY130 Floorplan & Under-MIM Architecture Plan for `pll_loop_filter_k4_fused_pdk`.

Generates:
  - ``lf_plan.png``: Two-panel blueprint comparing the legacy 18-MIM layout
    (154.42 x 80.46 um = 12,424.63 um^2) against the 3x2 stacked MIM1+MIM2
    fused architecture (98.34 x 70.10 um = 6,893.63 um^2, -44.5% area), plus
    the zoomed Under-MIM FEOL, guard-ring, and HV routing plan.
  - ``lf_plan.json``: Exact machine-readable dimensions, column partitions,
    track coordinates, and port coordinates extracted from the verified .mag cells.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell  # noqa: E402


def main() -> None:
    orig_mag = REPO / "analog/pll/loop_filter/layout/variants/pdk/pll_loop_filter_k4_pdk.mag"
    fused_mag = REPO / "analog/pll/loop_filter/layout/variants/fused_pdk/pll_loop_filter_k4_fused_pdk.mag"
    orig_c = Cell.read(orig_mag)
    fused_c = Cell.read(fused_mag)

    ob = orig_c.bbox()
    fb = fused_c.bbox()
    orig_w, orig_h = round(ob[2] - ob[0], 3), round(ob[3] - ob[1], 3)
    fused_w, fused_h = round(fb[2] - fb[0], 3), round(fb[3] - fb[1], 3)
    orig_area = round(orig_w * orig_h, 2)
    fused_area = round(fused_w * fused_h, 2)
    area_pct = round((fused_area - orig_area) / orig_area * 100.0, 1)

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(20.0, 9.6), dpi=170, gridspec_kw={"width_ratios": [1.22, 1.0]}
    )

    # ---- Panel 1: True 1:1 Scale Legacy vs Fused Stacked Comparison ----
    # Shift legacy to x0=0, y0=0; place fused cleanly to its right with gap=38 um
    ox_off, oy_off = -ob[0], -ob[1]
    gap_p1 = 38.0
    fx_off, fy_off = orig_w + gap_p1 - fb[0], (orig_h - fused_h) / 2.0 - fb[1]

    # Legacy envelope & 18 MIMs (use mimcapcontact boxes which are 1-per-unit!)
    ax1.add_patch(Rectangle((0, 0), orig_w, orig_h, fc="#f8fafc", ec="#64748b", lw=1.6, ls="--", zorder=1))
    orig_mims = orig_c.rects.get("mimcapcontact", []) or orig_c.rects.get("mimcap", [])
    for r in orig_mims:
        cx = (r[0] + r[2]) / 2.0
        col_vss = (-32.0 < cx < -10.0) or (20.0 < cx < 42.0)
        fc = "#bbf7d0" if col_vss else "#fef08a"
        ec = "#15803d" if col_vss else "#b45309"
        ax1.add_patch(Rectangle((r[0] + ox_off, r[1] + oy_off), r[2] - r[0], r[3] - r[1],
                                fc=fc, ec=ec, lw=0.9, alpha=0.82, zorder=3))
    ax1.text(orig_w / 2.0, orig_h + 5.0,
             f"Legacy `pll_loop_filter_k4_pdk`\n{orig_w:.2f} × {orig_h:.2f} µm = {orig_area:,.2f} µm²\n18 × MIM1 [VDD,VSS,VDD,VDD,VSS,VDD]",
             ha="center", va="bottom", fontsize=8.4, fontweight="bold", color="#334155")

    # Fused envelope & 6 stacked MIM1+MIM2 sites (use mimcapcontact = 6 discrete boxes!)
    ax1.add_patch(Rectangle((orig_w + gap_p1, (orig_h - fused_h) / 2.0), fused_w, fused_h,
                            fc="#eff6ff", ec="#1d4ed8", lw=2.0, zorder=1))
    fused_mims = fused_c.rects.get("mimcapcontact", []) or fused_c.rects.get("mimcap", [])
    for r in fused_mims:
        cx = (r[0] + r[2]) / 2.0
        col_vss = (-15.0 < cx < 13.0)
        fc = "#86efac" if col_vss else "#fde047"
        ec = "#047857" if col_vss else "#b45309"
        ax1.add_patch(Rectangle((r[0] + fx_off, r[1] + fy_off), r[2] - r[0], r[3] - r[1],
                                fc=fc, ec=ec, lw=1.2, alpha=0.88, hatch="///", zorder=3))
        ax1.text(cx + fx_off, (r[1] + r[3]) / 2.0 + fy_off,
                 "3.0 pF\nVSS\n(M3+M5)" if col_vss else "3.0 pF\nVDD\n(M3+M5)",
                 ha="center", va="center", fontsize=6.8, fontweight="bold",
                 color="#064e3b" if col_vss else "#78350f", zorder=5)

    port_offsets = {
        "z": (1.5, 1.5), "vss": (1.5, 1.5),
        "vdd": (1.5, -2.5), "ctrl": (2.0, -2.5),
        "pre_ref": (-12.5, 2.0), "pre_en": (-12.5, -3.5),
    }
    for _, px, py, nm in fused_c.labels:
        ax1.plot(px + fx_off, py + fy_off, "o", ms=5, color="#dc2626", zorder=8)
        dx_t, dy_t = port_offsets.get(nm, (1.2, 1.2))
        ax1.text(px + fx_off + dx_t, py + fy_off + dy_t, nm, fontsize=7.2, fontweight="bold",
                 color="#991b1b", zorder=9, bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="#dc2626", lw=0.5))

    ax1.text(orig_w + gap_p1 + fused_w / 2.0, (orig_h + fused_h) / 2.0 + 5.0,
             f"Fused Stacked `pll_loop_filter_k4_fused_pdk`\n{fused_w:.2f} × {fused_h:.2f} µm = {fused_area:,.2f} µm² ({area_pct}%)\n6 Sites (6 MIM1 + 6 MIM2)",
             ha="center", va="bottom", fontsize=8.4, fontweight="bold", color="#1e3a8a")

    ax1.set_xlim(-10, orig_w + gap_p1 + fused_w + 12)
    ax1.set_ylim(-10, orig_h + 22)
    ax1.set_aspect("equal")
    ax1.grid(True, lw=0.25, alpha=0.4)
    ax1.set_xlabel("x (µm)")
    ax1.set_ylabel("y (µm)")
    ax1.set_title("1. True 1:1 Scale Comparison: 18-Unit 1-Layer vs 6-Site Stacked `MIM1+MIM2`",
                  fontsize=10.2, fontweight="bold", pad=10)

    # ---- Panel 2: Zoomed Under-MIM FEOL + Guard Ring + Track Plan ----
    cols = [
        ("Col 0: VDD Bottom/Top\n(12 pF total w/ Col 2)\n100% Open Below", -47.00, 26.82, "#fef9c3", "#ca8a04", -14.0),
        ("Col 1: Quiet VSS Shield\n(6 pF z–vss)\nCompact CMOS Island + Xrz", -14.29, 26.82, "#dcfce7", "#16a34a", 24.5),
        ("Col 2: VDD Shield\n(6 pF z–vdd)\n100% Open Below", 18.42, 26.82, "#fef9c3", "#ca8a04", 24.5),
    ]
    for title, x0, w, fc, ec, ty in cols:
        ax2.add_patch(Rectangle((x0, -28.22), w, 56.44, fc=fc, ec=ec, lw=1.4, ls="--", alpha=0.35, zorder=1))
        ax2.text(x0 + w / 2.0, ty, title, ha="center", va="center", fontsize=6.6, fontweight="bold", color=ec,
                 bbox=dict(boxstyle="round,pad=0.18", fc="white", ec=ec, lw=0.6, alpha=0.88), zorder=8)

    # Perimeter M4/M5/M3 straps outside MIM
    ax2.add_patch(Rectangle((-34.2, 30.72), 66.7, 1.00, fc="#93c5fd", ec="#1d4ed8", lw=1.0, zorder=3))
    ax2.text(-0.8, 31.22, "M4 `z` Top Bus (y=31.22)", ha="center", va="center", fontsize=6.8, fontweight="bold", color="#1e3a8a")
    ax2.add_patch(Rectangle((-1.6, 34.02), 16.8, 1.60, fc="#d6d3d1", ec="#57534e", lw=1.0, zorder=3))
    ax2.text(6.8, 34.82, "M5 `vss` Strap (y=34.82)", ha="center", va="center", fontsize=6.8, fontweight="bold", color="#292524")
    ax2.add_patch(Rectangle((-34.4, -33.22), 82.3, 1.60, fc="#d6d3d1", ec="#57534e", lw=1.0, zorder=3))
    ax2.text(8.0, -32.42, "M5/M3 `vdd` Bottom Trunk (y=-32.42)", ha="center", va="center", fontsize=6.8, fontweight="bold", color="#292524")

    # Compact Col-1 Merged Nwell + Shared Closed VDD/VSS Guard Rings + Side-mounted Xrz
    ax2.add_patch(Rectangle((-7.10, 1.45), 17.40, 4.20, fc="#fde68a", ec="#d97706", lw=1.2, ls="-", alpha=0.68, zorder=2))
    ax2.add_patch(Rectangle((-6.65, 1.65), 16.50, 3.55, fc="none", ec="#b45309", lw=1.1, ls="--", zorder=3))
    ax2.text(1.6, 10.6, "Compact Merged N-well [-7.10,10.30] + VDD `nsubdiff` Guard Frame (y=[1.65,5.20])",
             ha="center", va="bottom", fontsize=6.4, fontweight="bold", color="#92400e",
             bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="#d97706", lw=0.5, alpha=0.9), zorder=8)
    ax2.add_patch(Rectangle((-6.65, -5.20), 16.50, 3.55, fc="#dbeafe", ec="#15803d", lw=1.1, ls="--", alpha=0.45, zorder=2))
    ax2.text(1.6, -7.8, "Compact VSS `psubdiff` Guard Frame (y=[-5.20,-1.65])",
             ha="center", va="top", fontsize=6.4, fontweight="bold", color="#14532d",
             bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="#15803d", lw=0.5, alpha=0.9), zorder=8)

    # Side-mounted Xrz + 2 flanking pure-poly dummies & compact CMOS strip inside Col 1
    blocks = [
        ("Dum", -12.795, -6.40, 0.69, 12.275, "#fed7aa", "#c2410c"),
        ("Xrz\n0.69×7.59", -11.975, -6.705, 2.35, 13.41, "#f5d0fe", "#86198f"),
        ("Dum", -9.495, -6.40, 0.69, 12.275, "#fed7aa", "#c2410c"),
        ("Xfast.n", -4.425, -4.54, 1.25, 2.88, "#bfdbfe", "#1d4ed8"),
        ("Xfast.p\nLVT", -5.405, 1.60, 3.21, 3.00, "#fecaca", "#b91c1c"),
        ("Xinv.n", -0.125, -4.54, 1.25, 2.88, "#bfdbfe", "#1d4ed8"),
        ("Xinv.p", -0.785, 1.60, 2.57, 3.00, "#fecaca", "#b91c1c"),
        ("Xint.n", 4.895, -4.54, 2.21, 2.88, "#bfdbfe", "#1d4ed8"),
        ("Xint.p\nLVT", 3.115, 1.60, 5.77, 3.00, "#fecaca", "#b91c1c"),
    ]
    for lbl, x0, y0, w, h, fc, ec in blocks:
        ax2.add_patch(Rectangle((x0, y0), w, h, fc=fc, ec=ec, lw=1.0, alpha=0.92, zorder=5))
        ax2.text(x0 + w / 2.0, y0 + h / 2.0, lbl, ha="center", va="center",
                 fontsize=5.0 if w < 1.8 else 5.8, fontweight="bold", color="#111827", zorder=7)
    # Biased field-poly dummy gate indicators inside CMOS island
    for xd in (-4.705, -2.895, -0.405, 1.405, 4.615, 7.385):
        ax2.plot([xd, xd], [-4.65, -1.97], color="#c2410c", lw=1.2, zorder=6)
    for xd in (-5.705, -1.500, 2.350, 9.005):
        ax2.plot([xd, xd], [1.97, 4.65], color="#c2410c", lw=1.3, zorder=6)

    # Horizontal M1 signal tracks in tight middle channel y in [-0.96, +0.96]
    track_specs = [
        (-0.96, "M1/M2 `pre_en` (y=-0.96)", "#2563eb", -34.0, -5.8),
        (-0.48, "M1 `pre_b` (y=-0.48)", "#0284c7", 20.5, -5.8),
        (0.00, "M1/M2 `pre_ref` (y=0.00)", "#7c3aed", -34.0, 5.8),
        (0.48, "M1 `ctrl` (y=+0.48)", "#dc2626", 20.5, 5.8),
        (0.96, "M1 `z` (y=+0.96)", "#059669", 34.0, 5.8),
    ]
    for y_tr, name, col, lx, ly in track_specs:
        x_l = -49.6 if y_tr in (-0.96, 0.00) else (-7.65 if y_tr == 0.48 else (-5.2 if y_tr == -0.48 else 6.0))
        x_r = 11.4 if y_tr == 0.96 else 7.8
        ax2.plot([x_l, x_r], [y_tr, y_tr], color=col, lw=1.15, alpha=0.85, zorder=4)
        ax2.annotate(name, xy=(min(max(lx, x_l + 1), x_r - 1), y_tr), xytext=(lx, ly),
                     fontsize=6.2, fontweight="bold", color=col, ha="center", va="center",
                     arrowprops=dict(arrowstyle="-", color=col, lw=0.7, alpha=0.7),
                     bbox=dict(boxstyle="round,pad=0.12", fc="white", ec=col, lw=0.5, alpha=0.9), zorder=8)

    ax2.plot(-10.8, -34.22, "rv", ms=7, zorder=8)
    ax2.text(-9.2, -34.6, "`ctrl` Port (-10.80, -34.22)", fontsize=7.0, fontweight="bold", color="#b91c1c", va="center")
    ax2.plot([-49.6, -49.6], [-0.96, 0.0], "bo", ms=5, zorder=8)
    ax2.text(-49.2, 5.0, "`pre_en`/`pre_ref`\nM3 Ports (-49.60,\ninside M5 overhang)",
             fontsize=6.2, fontweight="bold", color="#1e40af",
             bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="#1e40af", lw=0.5, alpha=0.9), zorder=8)

    ax2.set_xlim(-53.5, 50.0)
    ax2.set_ylim(-37.5, 38.5)
    ax2.set_aspect("equal")
    ax2.grid(True, lw=0.25, alpha=0.4)
    ax2.set_xlabel("x (µm)")
    ax2.set_ylabel("y (µm)")
    ax2.set_title("2. Under-MIM Shielding, Guard Rings, Merged N-Well & HV Track Plan",
                  fontsize=10.2, fontweight="bold", pad=10)

    fig.suptitle("SKY130 `pll_loop_filter_k4_fused_pdk` — Architecture & Floorplan Blueprint",
                 fontsize=13.0, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0.01, 1, 0.945])
    out_png = HERE / "lf_plan.png"
    fig.savefig(out_png, dpi=170)
    plt.close(fig)

    plan_data = {
        "legacy": {"cell": "pll_loop_filter_k4_pdk", "bbox_um": list(ob), "size_um": [orig_w, orig_h], "area_um2": orig_area, "mim_units": 18},
        "fused": {
            "cell": "pll_loop_filter_k4_fused_pdk",
            "bbox_um": list(fb),
            "size_um": [fused_w, fused_h],
            "area_um2": fused_area,
            "area_reduction_pct": area_pct,
            "mim_sites": 6,
            "mim_layers": "cap_mim_m3_1 + cap_mim_m3_2 (w=l=27.22 um)",
            "column_split": ["Col 0: VDD (6 pF)", "Col 1: VSS (6 pF)", "Col 2: VDD (6 pF)"],
            "under_mim_tracks_y": {
                "rz_vss_m1": -6.80,
                "nmos_vss_guard_m1": -5.20,
                "pre_en_m1": -0.96,
                "pre_b_m1": -0.48,
                "pre_ref_m1": 0.00,
                "ctrl_m1": 0.48,
                "z_m1": 0.96,
                "pmos_vdd_guard_m1": 5.20,
                "vdd_bridge_m1": 7.20,
                "z_bridge_m2": 8.40,
            },
            "xrz_layout": {"dx_um": -10.80, "dy_um": 0.00, "poly_dummies_x_um": [-12.45, -9.15]},
            "cmos_island": {
                "nwell_um": [-7.10, 1.45, 10.30, 5.65],
                "guard_frame_um": [-6.65, -5.20, 9.85, 5.20],
                "dy_n_um": -3.10,
                "dy_p_um": 3.10,
                "pmos_mirror_y": True,
                "devices_dx_um": {"Xfast": -3.80, "Xinv": 0.50, "Xint": 6.00},
                "poly_dummies_n_count": 6,
                "poly_dummies_p_count": 4,
            },
            "ports": {nm: [px, py] for _, px, py, nm in fused_c.labels},
        },
    }
    out_json = HERE / "lf_plan.json"
    out_json.write_text(json.dumps(plan_data, indent=2) + "\n")
    print("Wrote", out_png, "and", out_json)


if __name__ == "__main__":
    main()
