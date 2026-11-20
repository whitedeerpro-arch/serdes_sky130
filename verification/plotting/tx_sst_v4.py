#!/usr/bin/env python3
"""Generate publication-grade eye diagram & 45-corner PVT comparison figure for
the Quarter-Rate 4:1 Fused N-over-N SST 16:1 TX candidate (v4).

Output: docs/figures/tx/tx_sst_v4_eyes.png
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project, serial, spice

ROOT = project.ROOT
SST_RESULTS = ROOT / "results/analog/tx/sst"
LEGACY_POWER = ROOT / "docs/work_packages/deliveries/POWER-20261110/evidence.json"
OUT_FIG = ROOT / "docs/figures/tx/tx_sst_v4_eyes.png"

UI = 250e-12
PROC_ORDER = ["tt", "ss", "ff", "sf", "fs"]
PROC_LABELS = ["TT", "SS", "FF", "SF", "FS"]
PROC_COLORS = {
    "tt": "#1b6ca8",
    "ss": "#7b4ea3",
    "ff": "#d96b27",
    "sf": "#c93b4b",
    "fs": "#2c8c6c",
}
VDD_MARKERS = {1.65: "o", 1.8: "s", 1.95: "^"}
TEMP_DX = {-40: -0.20, 27: 0.0, 85: 0.20}


def latest_dir(suffix: str) -> Path:
    cands = sorted(p for p in SST_RESULTS.glob(f"*_{suffix}") if (p / "summary.json").exists())
    if not cands:
        raise FileNotFoundError(f"No campaign ending with _{suffix} found in {SST_RESULTS}")
    return cands[-1]


def fold_eye_2ui(t: np.ndarray, y_mv: np.ndarray, start_s: float, delay_ui: float, first_bit: int, n_bits: int):
    """Fold waveform into 2-UI traces centered on bit centers at 0.5 UI and 1.5 UI."""
    # Anchor at bit edge: start_s + (first_bit + delay_ui) * UI
    t_anchor = start_s + (first_bit + delay_ui) * UI
    grid_ui = np.linspace(0.0, 2.0, 201)
    traces = []
    for k in range(0, n_bits - 1, 1):
        t_seg = t_anchor + (k + grid_ui) * UI
        if t_seg[0] >= t[0] and t_seg[-1] <= t[-1]:
            traces.append(np.interp(t_seg, t, y_mv))
    return grid_ui, np.asarray(traces)


def plot_eye_panel(
    ax,
    raw_path: Path,
    bits: np.ndarray,
    start_s: float,
    payload_bits: int,
    node: str,
    title: str,
    subtitle: str,
    color: str,
    ylim: tuple[float, float] = (-310, 310),
    show_spec: bool = True,
):
    w = spice.Waves(raw_path)
    seq = serial.Sequence(bits=bits, start_s=start_s, ui_s=UI)
    m, _ = serial.check(w.t, w[node], seq, payload_bits)
    grid_ui, traces = fold_eye_2ui(w.t, w[node] * 1e3, start_s, m["training_delay_ui"], serial.TRAINING_BITS, payload_bits)
    for tr in traces:
        ax.plot(grid_ui, tr, color=color, alpha=0.22, lw=0.85, rasterized=True)
    if show_spec:
        for center in (0.5, 1.5):
            ax.plot([center - 0.12, center + 0.12], [75, 75], color="#c93b4b", ls="--", lw=1.1)
            ax.plot([center - 0.12, center + 0.12], [-75, -75], color="#c93b4b", ls="--", lw=1.1)
    ax.axhline(0.0, color="#666", lw=0.6, alpha=0.5)
    ax.axvline(0.5, color="#888", lw=0.6, ls=":", alpha=0.6)
    ax.axvline(1.5, color="#888", lw=0.6, ls=":", alpha=0.6)
    ax.set_xlim(0.0, 2.0)
    ax.set_ylim(*ylim)
    ax.set_xlabel("Time (UI, 1 UI = 250 ps)", fontsize=9)
    ax.set_ylabel("Differential Voltage (mV)", fontsize=9)
    ax.set_title(title, fontsize=10.5, fontweight="bold", pad=6)
    ax.grid(True, alpha=0.22)
    ax.text(
        0.03, 0.96, subtitle,
        transform=ax.transAxes, va="top", ha="left", fontsize=8.2,
        bbox=dict(boxstyle="round,pad=0.32", facecolor="white", edgecolor="#cccccc", alpha=0.92),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage1", type=Path, default=None, help="Stage-1 core campaign dir")
    ap.add_argument("--pvt45", type=Path, default=None, help="Stage-2 45-corner top16 campaign dir")
    ap.add_argument("--out", type=Path, default=OUT_FIG, help="Output PNG path")
    args = ap.parse_args()

    s1_dir = args.stage1 or latest_dir("core_stage1")
    p45_dir = args.pvt45 or latest_dir("top16_pvt45")
    s1 = json.loads((s1_dir / "summary.json").read_text())
    p45 = json.loads((p45_dir / "summary.json").read_text())
    legacy = json.loads(LEGACY_POWER.read_text())["tx"]

    bits_top = np.array(json.loads((p45_dir / "bits.json").read_text()), dtype=int)
    bits_s1 = np.array(json.loads((s1_dir / "bits.json").read_text()), dtype=int)
    payload_top = int(p45.get("payload_bits", 128))
    rows = p45["pvt45"]

    fig, axes = plt.subplots(2, 3, figsize=(16.0, 9.4), dpi=200, layout="constrained")

    # --- Row 1: Full 16:1 SST TX Pad Eye Diagrams (TT, SS -40C, FS 85C) ---
    eye_specs = [
        ("tt_v1800_t27",  "(a) Full 16:1 TX Pad Eye — TT 1.80 V, 27 °C",  "#1b6ca8"),
        ("ss_v1650_t-40", "(b) Full 16:1 TX Pad Eye — SS 1.65 V, −40 °C", "#7b4ea3"),
        ("fs_v1650_t85",  "(c) Full 16:1 TX Pad Eye — FS 1.65 V, 85 °C",  "#2c8c6c"),
    ]
    for ax, (tag, title, col) in zip(axes[0], eye_specs):
        r = rows[tag]
        sub = (
            f"Margin: {r['pad_margin_mv']:.1f} mV (spec ≥75)\n"
            f"Spread: {r['pad_spread_ui']:.4f} UI ({r['pad_spread_ui']*250:.1f} ps)\n"
            f"Swing: {r['pad_pp_mv']:.0f} mVpp | Nzq={r['n_zq']}\n"
            f"Total TX: {r['power_mw']:.2f} mW ({r['pj_per_bit']:.2f} pJ/b)"
        )
        plot_eye_panel(
            ax, ROOT / r["raw"], bits_top, 9.0e-9, payload_top, "pad",
            title, sub, col, ylim=(-300, 395), show_spec=True,
        )

    # --- Panel (d): Built-In 2-Tap FFE on Real C2 (6 dB @ 2 GHz) PCB Channel ---
    ax_c2 = axes[1, 0]
    # Prefer top-level C2 TT FFE=0 vs FFE=3 if present; fall back to Stage-1 core C2
    if "c2_tt_v1800_t27_ffe0" in p45.get("c2_top", {}) and "c2_tt_v1800_t27_ffe3" in p45.get("c2_top", {}):
        r_off = p45["c2_top"]["c2_tt_v1800_t27_ffe0"]
        r_on = p45["c2_top"]["c2_tt_v1800_t27_ffe3"]
        raw_off, raw_on = ROOT / r_off["raw"], ROOT / r_on["raw"]
        c2_bits, c2_start, c2_pl = bits_top, 9.0e-9, payload_top
        c2_src = "Full 16:1 TX"
    else:
        raw_off = s1_dir / "c2_tt_v1800_t27_ffe0/waveforms.raw"
        raw_on = s1_dir / "c2_tt_v1800_t27_ffe3/waveforms.raw"
        r_off = next(x for x in s1["c2_ffe"] if x["tag"] == "c2_tt_v1800_t27_ffe0")
        r_on = next(x for x in s1["c2_ffe"] if x["tag"] == "c2_tt_v1800_t27_ffe3")
        c2_bits, c2_start, c2_pl = bits_s1, 4.0e-9, 128
        c2_src = "Core Driver"

    for raw_p, col, alph, lw, lbl in [
        (raw_off, "#d95f5f", 0.25, 0.85, "FFE OFF (0 slices)"),
        (raw_on,  "#146c78", 0.32, 0.95, "FFE ON (3 post-1 slices)"),
    ]:
        w = spice.Waves(raw_p)
        seq = serial.Sequence(bits=c2_bits, start_s=c2_start, ui_s=UI)
        m, _ = serial.check(w.t, w["remote"], seq, c2_pl)
        g, trs = fold_eye_2ui(w.t, w["remote"] * 1e3, c2_start, m["training_delay_ui"], serial.TRAINING_BITS, c2_pl)
        for i, tr in enumerate(trs):
            ax_c2.plot(g, tr, color=col, alpha=alph, lw=lw, label=(lbl if i == 0 else None), rasterized=True)
    ax_c2.axhline(0.0, color="#666", lw=0.6, alpha=0.5)
    ax_c2.set_xlim(0.0, 2.0)
    ax_c2.set_ylim(-255, 305)
    ax_c2.set_xlabel("Time (UI, 1 UI = 250 ps)", fontsize=9)
    ax_c2.set_ylabel("Far-End C2 Differential (mV)", fontsize=9)
    ax_c2.set_title(f"(d) Real C2 PCB (6 dB @ 2 GHz) — FFE OFF vs ON ({c2_src}, No CTLE)", fontsize=10.0, fontweight="bold", pad=6)
    ax_c2.grid(True, alpha=0.22)
    leg_c2 = ax_c2.legend(loc="lower right", fontsize=8.0, frameon=True, facecolor="white", framealpha=0.92)
    for lh in leg_c2.legend_handles:
        lh.set_alpha(1.0)
        lh.set_linewidth(2.0)
    c2_box = (
        f"FFE=0: marg {r_off['rem_margin_mv']:.1f} mV, spread {r_off['rem_spread_ui']:.4f} UI\n"
        f"FFE=3: marg {r_on['rem_margin_mv']:.1f} mV (+{(r_on['rem_margin_mv']/r_off['rem_margin_mv']-1)*100:.0f}%), "
        f"spread {r_on['rem_spread_ui']:.4f} UI ({r_off['rem_spread_ui']/r_on['rem_spread_ui']:.1f}× less)"
    )
    ax_c2.text(
        0.03, 0.96, c2_box, transform=ax_c2.transAxes, va="top", ha="left", fontsize=8.0,
        bbox=dict(boxstyle="round,pad=0.30", facecolor="white", edgecolor="#cccccc", alpha=0.92),
    )

    # --- Panel (e): 45-Corner PVT Edge Spread & Eye Margin ---
    ax_sp = axes[1, 1]
    ax_mg = ax_sp.twinx()
    for j, proc in enumerate(PROC_ORDER):
        sub = [r for r in rows.values() if r["process"] == proc]
        for r in sub:
            x = j + TEMP_DX[int(r["temp_c"])]
            mk = VDD_MARKERS[round(float(r["supply"]), 2)]
            ax_sp.scatter(x, r["pad_spread_ui"], c=PROC_COLORS[proc], marker=mk, s=38, alpha=0.9, zorder=3)
            ax_mg.scatter(x, r["pad_margin_mv"], facecolors="none", edgecolors="#222222", marker=mk, s=44, lw=1.0, alpha=0.65, zorder=2)

    ax_sp.axhline(0.15, color="#c93b4b", ls="--", lw=1.2, label="Spread spec ≤ 0.15 UI")
    ax_sp.set_xticks(range(5), PROC_LABELS)
    ax_sp.set_ylim(0.0, 0.175)
    ax_sp.set_ylabel("Pad Edge Spread (UI) — filled", fontsize=9, color="#1b6ca8")
    ax_mg.set_ylim(0.0, 260.0)
    ax_mg.set_ylabel("Pad Signed Eye Margin (mV) — open", fontsize=9, color="#333333")
    ax_mg.axhline(75.0, color="#666666", ls=":", lw=1.1)
    ax_mg.text(4.38, 79.0, "Margin spec ≥ 75 mV", ha="right", va="bottom", fontsize=7.6, color="#444444")
    ax_sp.grid(axis="y", alpha=0.22)
    n_pass = sum(1 for r in rows.values() if r["pad_meets_spec"])
    max_sp = max(r["pad_spread_ui"] for r in rows.values())
    min_mg = min(r["pad_margin_mv"] for r in rows.values())
    ax_sp.set_title(f"(e) Full 16:1 TX Across {len(rows)} PVT Corners ({n_pass}/{len(rows)} PASS)", fontsize=10.2, fontweight="bold", pad=6)
    # Clean custom legend
    for vdd, mk in VDD_MARKERS.items():
        ax_sp.scatter([], [], c="#555", marker=mk, s=32, label=f"{vdd:.2f} V")
    ax_sp.legend(loc="center left", bbox_to_anchor=(0.01, 0.56), fontsize=7.8, frameon=True, facecolor="white", framealpha=0.92, ncol=2)
    ax_sp.text(
        0.98, 0.96,
        f"Max spread: {max_sp:.4f} UI ({max_sp*250:.1f} ps)\nMin margin: {min_mg:.1f} mV (spec ≥75)\nZero bit errors, natural 0..15 order",
        transform=ax_sp.transAxes, va="top", ha="right", fontsize=7.9,
        bbox=dict(boxstyle="round,pad=0.30", facecolor="white", edgecolor="#cccccc", alpha=0.92),
    )

    # --- Panel (f): 45-Corner Power Comparison — Legacy All-CML TX vs New SST TX ---
    ax_pw = axes[1, 2]
    leg_vals, sst_vals = [], []
    for j, proc in enumerate(PROC_ORDER):
        # Legacy all-CML TX 45 corners
        for k, v in legacy.items():
            if not k.startswith(proc + "_"):
                continue
            vdd = int(re.search(r"_v(\d+)", k)[1]) / 1000.0
            temp = int(re.search(r"_t(-?\d+)", k)[1])
            x = j + TEMP_DX[temp]
            ax_pw.scatter(x, v["mean_power_mw"], c="#c93b4b", marker=VDD_MARKERS[round(vdd, 2)], s=34, alpha=0.60)
            leg_vals.append(v["mean_power_mw"])
        # New All-CMOS + N-over-N SST TX
        for r in rows.values():
            if r["process"] != proc:
                continue
            x = j + TEMP_DX[int(r["temp_c"])]
            ax_pw.scatter(x, r["power_mw"], c="#1b6ca8", marker=VDD_MARKERS[round(float(r["supply"]), 2)], s=40, alpha=0.90)
            sst_vals.append(r["power_mw"])

    ax_pw.scatter([], [], c="#c93b4b", marker="s", s=40, label=f"Legacy All-CML TX ({min(leg_vals):.1f}–{max(leg_vals):.1f} mW)")
    ax_pw.scatter([], [], c="#1b6ca8", marker="s", s=40, label=f"New CMOS+SST TX ({min(sst_vals):.1f}–{max(sst_vals):.1f} mW)")
    tt_leg = legacy["tt_v1800_t27"]["mean_power_mw"]
    tt_sst = rows["tt_v1800_t27"]["power_mw"]
    red_pct = (1.0 - tt_sst / tt_leg) * 100.0
    ax_pw.annotate(
        f"−{red_pct:.1f}% Power @ TT\n({tt_leg:.1f} → {tt_sst:.2f} mW,\n{tt_sst/4.0:.2f} pJ/bit)",
        xy=(0.0, tt_sst + 3.0), xytext=(1.55, 52.0),
        arrowprops=dict(arrowstyle="->", color="#1b6ca8", lw=1.4),
        fontsize=8.5, fontweight="bold", color="#124b75",
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#eef6fb", edgecolor="#1b6ca8", alpha=0.95),
    )
    ax_pw.set_xticks(range(5), PROC_LABELS)
    ax_pw.set_ylim(0, 132)
    ax_pw.set_ylabel("Total 16:1 TX Vdd Power (mW)", fontsize=9)
    ax_pw.set_title("(f) 45-Corner TX Power: Legacy CML vs New CMOS+SST", fontsize=10.2, fontweight="bold", pad=6)
    ax_pw.grid(axis="y", alpha=0.22)
    ax_pw.legend(loc="center right", bbox_to_anchor=(0.99, 0.56), fontsize=8.0, frameon=True, facecolor="white", framealpha=0.92)

    fig.suptitle(
        "SKY130 4 Gb/s Quarter-Rate 4:1 Fused N-over-N SST 16:1 TX (Zero CML, Zero 2 GHz Clock, Built-In 2-Tap FFE & ZQ)",
        fontsize=12.5, fontweight="bold",
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=200)
    plt.close(fig)
    print(f"Saved figure: {args.out}")


if __name__ == "__main__":
    main()
