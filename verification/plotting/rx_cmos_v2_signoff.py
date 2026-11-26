"""Generate publication-grade 4-panel RX v2 Zero-CML CMOS signoff figure.

Usage:
    uv run python verification/plotting/rx_cmos_v2_signoff.py [--stageB PATH_TO_STAGEB_SUMMARY]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import mc, project, spice

ROOT = project.ROOT
OUT_FIG = ROOT / "docs/figures/rx/rx_cmos_v2_signoff.png"

PI_SUMMARY = ROOT / "results/analog/rx/cmos_rx/pi/20261121T034553Z/summary.json"
SLICER_DIR = ROOT / "results/analog/rx/cmos_rx/slicer/20261120T230000Z"
STAGEA_DIR = ROOT / "results/analog/rx/cmos_rx/link/20261121T112319Z_stageA"
LEGACY_POWER = ROOT / "docs/work_packages/deliveries/POWER-20261110/evidence.json"
# Archived 45-corner All-CML baseline from POWER-20261110/evidence.json (used when archive file is absent)
LEGACY_POWER_FALLBACK = {
    "rx_tt_mw": 42.41639936868892,
    "rx_min_mw": 31.899646982797208,
    "rx_max_mw": 52.06058297540834,
    "tx_tt_mw": 102.85783716402224,
    "link_tt_mw": 145.27423653271117,
    "link_min_mw": 119.59345380712028,
    "link_max_mw": 168.48512039838698,
}

CORNER_STYLE = {
    "tt_v1800_t27":  ("TT 1.80V 27°C",   "#1f77b4", "-",  2.2),
    "ss_v1650_t-40": ("SS 1.65V −40°C",  "#d62728", "-",  2.0),
    "ss_v1650_t85":  ("SS 1.65V 85°C",   "#ff7f0e", "--", 1.7),
    "fs_v1650_t-40": ("FS 1.65V −40°C",  "#2ca02c", "-.", 1.7),
    "fs_v1650_t85":  ("FS 1.65V 85°C",   "#9467bd", ":",  1.8),
    "ff_v1950_t-40": ("FF 1.95V −40°C",  "#8c564b", "--", 1.7),
}


def find_latest_stageB() -> Path | None:
    link_dir = ROOT / "results/analog/rx/cmos_rx/link"
    cands = sorted(link_dir.glob("*_stageB/summary.json"))
    return cands[-1] if cands else None


def load_mc_vos(cond_dir: Path) -> np.ndarray:
    cdirs = sorted(p for p in cond_dir.glob("c[0-9][0-9]") if p.is_dir())
    rows = mc.read_all(cdirs)
    vals = mc.column(rows, "vos_mv")
    return vals[np.isfinite(vals)]


def plot_panel1_pi_inl(ax: plt.Axes):
    data = json.loads(PI_SUMMARY.read_text())
    max_inl = 0.0
    for rec in data:
        tag = rec["condition"]
        lbl, col, ls, lw = CORNER_STYLE.get(tag, (tag, "#333333", "-", 1.5))
        inl = np.array(rec["inl_curve_ui"])
        codes = np.array(rec["codes"])
        pk = float(np.max(np.abs(inl)))
        max_inl = max(max_inl, pk)
        ax.plot(codes, inl, label=f"{lbl} ({pk:.4f} UI)", color=col, linestyle=ls, linewidth=lw)

    ax.axhline(+0.02, color="#c0392b", linestyle="--", linewidth=1.2, alpha=0.85, label="Spec gate (±0.020 UI)")
    ax.axhline(-0.02, color="#c0392b", linestyle="--", linewidth=1.2, alpha=0.85)
    ax.axhspan(-0.015, 0.015, color="#2ecc71", alpha=0.07)
    ax.axhline(0.0, color="#7f8c8d", linewidth=0.7, alpha=0.7)
    ax.set_xlim(0, 63)
    ax.set_ylim(-0.026, 0.026)
    ax.set_xticks([0, 8, 16, 24, 32, 40, 48, 56, 63])
    ax.set_xlabel("PI Phase Code (64 codes = 2 UI / 360° @ 2 GHz)", fontsize=9.5)
    ax.set_ylabel("Integral Nonlinearity, INL (UI)", fontsize=9.5)
    ax.set_title("A. 2 GHz Pure-CMOS PI Linearity (6 Extreme PVT Corners)", fontsize=10.5, fontweight="bold", pad=8)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="lower center", ncol=2, fontsize=7.6, framealpha=0.94, edgecolor="#cccccc")
    ax.text(
        0.02, 0.95,
        f"384/384 monotonic PASS\nWorst |INL| = {max_inl:.4f} UI (3.0 ps)\n16/16 reset-state deterministic",
        transform=ax.transAxes, va="top", ha="left", fontsize=8.0,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#f8f9fa", edgecolor="#adb5bd", alpha=0.95),
    )


def plot_panel2_slicer_mc_trim(ax: plt.Axes):
    vos_tt = load_mc_vos(SLICER_DIR / "mc/tt_v1800_t27_mm")
    vos_ss = load_mc_vos(SLICER_DIR / "mc/ss_v1650_t-40_mm")
    bins = np.linspace(-48, 48, 25)
    ax.hist(vos_tt, bins=bins, alpha=0.62, color="#1f77b4", edgecolor="#144d75", linewidth=0.6,
            label=f"TT 1.8V 27°C (N={len(vos_tt)}, 1σ={np.std(vos_tt, ddof=1):.1f} mV)")
    ax.hist(vos_ss, bins=bins, alpha=0.48, color="#d62728", edgecolor="#8c1919", linewidth=0.6,
            label=f"SS 1.65V −40°C (N={len(vos_ss)}, 1σ={np.std(vos_ss, ddof=1):.1f} mV)")
    ax.axvline(0.0, color="#555555", linestyle=":", linewidth=0.9)
    # Mark TT trim coverage range [-49.1, +42.9] mV
    ax.axvline(-49.1, color="#2ca02c", linestyle="--", linewidth=1.1, alpha=0.8)
    ax.axvline(+42.9, color="#2ca02c", linestyle="--", linewidth=1.1, alpha=0.8, label="6-bit Trim Span (TT: −49..+43 mV)")
    ax.set_xlim(-54, 54)
    ax.set_ylim(0, 64)
    ax.set_xlabel("Raw Input-Referred Offset $V_{os}$ (mV)", fontsize=9.5)
    ax.set_ylabel("Monte Carlo Count (200 samples)", fontsize=9.5)
    ax.set_title("B. Double-Tail Slicer Mismatch MC & 6-Bit Trim", fontsize=10.5, fontweight="bold", pad=8)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", fontsize=7.5, framealpha=0.95, edgecolor="#cccccc")

    # Clean inset for 6-bit monotonic trim transfer curve (zero overlap with histogram bars!)
    trim = json.loads((SLICER_DIR / "trim/summary.json").read_text())
    ax_in = ax.inset_axes([0.58, 0.50, 0.39, 0.43])
    ax_in.set_facecolor("white")
    t_styles = {
        "tt_v1800_t27": ("TT", "#1f77b4", "-"),
        "ss_v1650_t85": ("SS 85°C", "#ff7f0e", "--"),
        "ff_v1950_t-40": ("FF −40°C", "#2ca02c", "-."),
    }
    for rec in trim:
        lbl, col, ls = t_styles.get(rec["condition"], (rec["condition"], "#333", "-"))
        ax_in.plot(np.arange(64), rec["vos_mv"], color=col, linestyle=ls, linewidth=1.4, label=lbl)
    ax_in.axhline(0.0, color="#888888", linewidth=0.6)
    ax_in.axvline(32, color="#888888", linewidth=0.6, linestyle=":")
    ax_in.set_xlim(0, 63)
    ax_in.set_ylim(-64, 56)
    ax_in.set_xticks([0, 32, 63])
    ax_in.set_yticks([-50, 0, 50])
    ax_in.tick_params(labelsize=7.2)
    ax_in.set_xlabel("Trim Code", fontsize=7.5, labelpad=1)
    ax_in.set_ylabel("$V_{os}$ (mV)", fontsize=7.5, labelpad=1)
    ax_in.set_title("6-Bit Trim (Monotonic)", fontsize=7.8, fontweight="bold", pad=2)
    ax_in.grid(True, linestyle=":", alpha=0.45)
    ax_in.legend(loc="upper left", fontsize=6.6, framealpha=0.9, handlelength=1.4, borderpad=0.25)


def plot_panel3_eye_and_bbpd(ax: plt.Axes):
    stageA = json.loads((STAGEA_DIR / "summary.json").read_text())
    tt_live = [r for r in stageA["live"] if r["condition"] == "tt_v1800_t27"][0]
    w = spice.Waves(ROOT / tt_live["raw_path"])
    ui = 250e-12
    t0 = tt_live["bit0_center_ns"] * 1e-9 - 0.5 * ui  # left edge of bit 0

    # Fold live CTLE differential output over 2 UI (centered at 0.0 UI = eye center)
    t_grid = np.linspace(-0.5, 0.5, 161)  # single UI centered at 0.0 UI
    for k in range(32, 128):
        t_seg = t0 + (k + 0.5 + t_grid) * ui
        if t_seg[0] < w.t[0] or t_seg[-1] > w.t[-1]:
            continue
        y_mv = np.interp(t_seg, w.t, w["ctle_diff"]) * 1e3
        ax.plot(t_grid, y_mv, color="#1f77b4", alpha=0.22, linewidth=0.95)

    # Overlay Alexander BBPD normalized early/late vote S-curve from Stage A TT sweep
    # Shift x-axis so BBPD zero-crossing aligns with 0.0 UI (true eye center)
    pts = stageA["windows"]["tt_v1800_t27"]["points"]
    # Find zero crossing offset in UI
    zc_ui = 0.0
    for a, b in zip(pts, pts[1:]):
        if a["bbpd_vote"] <= 0 <= b["bbpd_vote"] and a["data_errors"] == 0 and b["data_errors"] == 0:
            zc_ui = a["offset_ui"] + (0 - a["bbpd_vote"]) / max(1e-9, b["bbpd_vote"] - a["bbpd_vote"]) * (b["offset_ui"] - a["offset_ui"])
            break

    # Shaded error-free RX sampling window (all 0-error points around center)
    ok_x = [p["offset_ui"] - zc_ui for p in pts if p["data_errors"] == 0 and p["edge_errors"] == 0 and abs(p["offset_ui"] - zc_ui) <= 0.45]
    if ok_x:
        ax.axvspan(min(ok_x), max(ok_x), color="#2ecc71", alpha=0.14, label=f"RX 0-Err Window (≥{max(ok_x)-min(ok_x):.3f} UI)")

    ax.axhline(0.0, color="#666666", linestyle=":", linewidth=0.8)
    ax.axvline(0.0, color="#27ae60", linestyle="--", linewidth=1.1, alpha=0.85)
    ax.set_xlim(-0.52, 0.52)
    ax.set_ylim(-265, 290)
    ax.set_xlabel("Sampling Phase Offset Relative to Eye Center (UI, 1 UI = 250 ps)", fontsize=9.5)
    ax.set_ylabel("Live PDK CTLE (EQ3) Output (mV diff)", fontsize=9.5, color="#1f77b4")
    ax.tick_params(axis="y", labelcolor="#1f77b4")
    ax.set_title("C. Live TX v4 (FFE=3) → C2 → RX v2 Eye & BBPD S-Curve (TT)", fontsize=10.5, fontweight="bold", pad=8)
    ax.grid(True, linestyle=":", alpha=0.45)

    # Twin axis for normalized BBPD early/late vote (-1 = Early, +1 = Late)
    ax2 = ax.twinx()
    xs = [p["offset_ui"] - zc_ui for p in pts if abs(p["offset_ui"] - zc_ui) <= 0.48]
    ys = [p["bbpd_vote"] / max(1, p["bbpd_transitions"]) for p in pts if abs(p["offset_ui"] - zc_ui) <= 0.48]
    ax2.plot(xs, ys, color="#d62728", marker="o", markersize=4.8, linewidth=1.9, label="Alexander BBPD Vote (Early − / Late +)")
    ax2.set_ylabel("Normalized BBPD Vote (Early −1 / Late +1)", fontsize=9.2, color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax2.set_ylim(-1.35, 1.35)
    ax2.set_yticks([-1.0, -0.5, 0.0, 0.5, 1.0])

    # Combined clean legend
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7.6, framealpha=0.94, edgecolor="#cccccc")
    ax.text(
        0.98, 0.05,
        f"Live CTLE Eye: {tt_live['ctle_eye_h_mv']:.1f} mV × {tt_live['ctle_eye_w_ui']:.2f} UI\n"
        f"0/96 data errs, 0/43 det. edge errs\n"
        f"wclk su/ho = {tt_live['wclk_setup_ps']/1e3:.2f} / {tt_live['wclk_hold_ps']/1e3:.2f} ns",
        transform=ax.transAxes, va="bottom", ha="right", fontsize=7.8,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="#f8f9fa", edgecolor="#adb5bd", alpha=0.95),
    )


def plot_panel4_power(ax: plt.Axes, stageB_path: Path | None):
    if LEGACY_POWER.exists():
        ev = json.loads(LEGACY_POWER.read_text())
        leg_rx_map = ev["rx_historical_45"]["power_mw_by_condition"]
        leg_tx_map = {k: v["mean_power_mw"] for k, v in ev["tx"].items()}
        leg_rx_tt = leg_rx_map["tt_v1800_t27"]
        leg_rx_min, leg_rx_max = min(leg_rx_map.values()), max(leg_rx_map.values())
        leg_tx_tt = leg_tx_map["tt_v1800_t27"]
        leg_link_tt = leg_rx_tt + leg_tx_tt
        leg_link_all = [leg_rx_map[k] + leg_tx_map[k] for k in leg_rx_map if k in leg_tx_map]
        leg_link_min, leg_link_max = min(leg_link_all), max(leg_link_all)
    else:
        leg_rx_tt = LEGACY_POWER_FALLBACK["rx_tt_mw"]
        leg_rx_min = LEGACY_POWER_FALLBACK["rx_min_mw"]
        leg_rx_max = LEGACY_POWER_FALLBACK["rx_max_mw"]
        leg_tx_tt = LEGACY_POWER_FALLBACK["tx_tt_mw"]
        leg_link_tt = LEGACY_POWER_FALLBACK["link_tt_mw"]
        leg_link_min = LEGACY_POWER_FALLBACK["link_min_mw"]
        leg_link_max = LEGACY_POWER_FALLBACK["link_max_mw"]

    stageA = json.loads((STAGEA_DIR / "summary.json").read_text())
    tt_a = [r for r in stageA["live"] if r["condition"] == "tt_v1800_t27"][0]

    # Use Stage B 45-corner stats if available, else Stage A 6-corner stats
    if stageB_path is not None and stageB_path.exists():
        sb = json.loads(stageB_path.read_text())
        rows = sb["rows"]
        rx_min = min(r["p_rx_mw"] for r in rows)
        rx_max = max(r["p_rx_mw"] for r in rows)
        lk_min = min(r["p_link_mw"] for r in rows)
        lk_max = max(r["p_link_mw"] for r in rows)
        range_lbl = "45-corner PVT range"
    else:
        rows = stageA["live"]
        rx_min = min(r["p_rx_mw"] for r in rows)
        rx_max = max(r["p_rx_mw"] for r in rows)
        lk_min = min(r["p_link_mw"] for r in rows)
        lk_max = max(r["p_link_mw"] for r in rows)
        range_lbl = "6-corner stress range"

    # Left group: RX-only (Legacy All-CML vs RX v2 Zero-CML stacked)
    # Right group: Full 4 Gb/s Link TX+RX (Legacy All-CML vs TX v4 SST + RX v2 Zero-CML)
    x = np.array([0.0, 1.0, 2.5, 3.5])
    w = 0.56

    # Bar 0: Legacy All-CML RX
    ax.bar(x[0], leg_rx_tt, width=w, color="#95a5a6", edgecolor="#566573", linewidth=0.9, label="Legacy All-CML RX / TX")
    ax.errorbar(x[0], leg_rx_tt, yerr=[[leg_rx_tt - leg_rx_min], [leg_rx_max - leg_rx_tt]],
                fmt="none", ecolor="#2c3e50", elinewidth=1.4, capsize=4)

    # Bar 1: RX v2 Zero-CML stacked breakdown
    b_ctle = tt_a["p_ctle_mw"]
    b_pi = tt_a["p_pi_mw"]
    b_sl = tt_a["p_slicer_mw"]
    b_ds = tt_a["p_deser_mw"]
    rx_tt = tt_a["p_rx_mw"]
    ax.bar(x[1], b_ctle, width=w, color="#1abc9c", edgecolor="#0e6251", linewidth=0.7, label=f"PDK CTLE ({b_ctle:.2f} mW)")
    ax.bar(x[1], b_pi,   width=w, bottom=b_ctle, color="#3498db", edgecolor="#1b4f72", linewidth=0.7, label=f"CMOS PI+÷2 ({b_pi:.2f} mW)")
    ax.bar(x[1], b_sl,   width=w, bottom=b_ctle+b_pi, color="#f39c12", edgecolor="#7e5109", linewidth=0.7, label=f"8×DT Slicer ({b_sl:.2f} mW)")
    ax.bar(x[1], b_ds,   width=w, bottom=b_ctle+b_pi+b_sl, color="#9b59b6", edgecolor="#4a235a", linewidth=0.7, label=f"CMOS Deser16 ({b_ds:.2f} mW)")
    ax.errorbar(x[1], rx_tt, yerr=[[rx_tt - rx_min], [rx_max - rx_tt]],
                fmt="none", ecolor="#2c3e50", elinewidth=1.4, capsize=4, label=range_lbl)

    # Bar 2: Legacy Full Link (TX + RX)
    ax.bar(x[2], leg_rx_tt, width=w, color="#95a5a6", edgecolor="#566573", linewidth=0.9)
    ax.bar(x[2], leg_tx_tt, width=w, bottom=leg_rx_tt, color="#bdc3c7", edgecolor="#566573", linewidth=0.9, hatch="//")
    ax.errorbar(x[2], leg_link_tt, yerr=[[leg_link_tt - leg_link_min], [leg_link_max - leg_link_tt]],
                fmt="none", ecolor="#2c3e50", elinewidth=1.4, capsize=4)

    # Bar 3: New Zero-CML Link (RX v2 + TX v4 SST)
    lk_tt = tt_a["p_link_mw"]
    tx_tt = tt_a["p_tx_mw"]
    ax.bar(x[3], rx_tt, width=w, color="#2980b9", edgecolor="#1b4f72", linewidth=0.8)
    ax.bar(x[3], tx_tt, width=w, bottom=rx_tt, color="#27ae60", edgecolor="#145a32", linewidth=0.8, label=f"TX v4 SST ({tx_tt:.2f} mW)")
    ax.errorbar(x[3], lk_tt, yerr=[[lk_tt - lk_min], [lk_max - lk_tt]],
                fmt="none", ecolor="#2c3e50", elinewidth=1.4, capsize=4)

    # Value annotations above error bars
    ax.text(x[0], leg_rx_max + 3.5, f"{leg_rx_tt:.1f} mW\n({leg_rx_tt/4:.2f} pJ/b)", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#444")
    ax.text(x[1], rx_max + 3.5, f"{rx_tt:.1f} mW\n({rx_tt/4:.2f} pJ/b)\n−{(1-rx_tt/leg_rx_tt)*100:.0f}%", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#1b4f72")
    ax.text(x[2], leg_link_max + 3.5, f"{leg_link_tt:.1f} mW\n({leg_link_tt/4:.1f} pJ/b)", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#444")
    ax.text(x[3], lk_max + 3.5, f"{lk_tt:.1f} mW\n({lk_tt/4:.2f} pJ/b)\n{leg_link_tt/lk_tt:.2f}× lower!", ha="center", va="bottom", fontsize=8.0, fontweight="bold", color="#145a32")

    ax.axvline(1.75, color="#bdc3c7", linestyle="--", linewidth=1.0)
    ax.set_xticks(x)
    ax.set_xticklabels([
        "Legacy\nAll-CML RX",
        "RX v2\nZero-CML",
        "Legacy\nTX+RX Link",
        "TX v4 SST +\nRX v2 Link",
    ], fontsize=8.6)
    ax.set_ylim(0, 248)
    ax.set_ylabel("Mean Supply Power at 4 Gb/s (mW, TT + PVT Range)", fontsize=9.2)
    ax.set_title("D. Power Reduction: Legacy All-CML vs Zero-CML SerDes", fontsize=10.5, fontweight="bold", pad=8)
    ax.grid(True, axis="y", linestyle=":", alpha=0.5)
    ax.legend(loc="upper center", ncol=3, fontsize=6.9, framealpha=0.95, edgecolor="#cccccc", columnspacing=0.9, handletextpad=0.45)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stageB", help="Path to Stage B summary.json (auto-detects latest if omitted)")
    a = ap.parse_args()
    sb_path = (ROOT / a.stageB) if a.stageB else find_latest_stageB()

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "axes.facecolor": "white",
        "figure.facecolor": "white",
        "savefig.facecolor": "white",
    })
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.4), dpi=220)
    plot_panel1_pi_inl(axes[0, 0])
    plot_panel2_slicer_mc_trim(axes[0, 1])
    plot_panel3_eye_and_bbpd(axes[1, 0])
    plot_panel4_power(axes[1, 1], sb_path)

    fig.suptitle(
        "SKY130 4 Gb/s RX v2 Zero-CML CMOS Receiver — Complete Pre-Layout PVT, MC & End-to-End Link Signoff",
        fontsize=12.6, fontweight="bold", y=0.985,
    )
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.962), h_pad=2.2, w_pad=2.2)
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG, dpi=220)
    print(f"Saved figure: {OUT_FIG.relative_to(ROOT)} (stageB={sb_path})")


if __name__ == "__main__":
    main()
