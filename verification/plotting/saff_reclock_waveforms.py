#!/usr/bin/env python3
"""Plot post-layout RCX_BOTH working waveforms of pll_saff_reclock_prescaler8_2g_pdk v2."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from serdes_flow import clock, spice
from serdes_flow.project import ROOT

POST_DIR = ROOT / "results/analog/pll/divider/tspc_study/20261120_saff_v7_pdk_v2/postlayout"
OUT_PNG = ROOT / "docs/figures/clocking/dividers/saff_reclock_v2_waveforms.png"

CASES = [
    ("rcxboth__tt_v1800_t27_tt", "TT 1.80 V 27 °C (RCX_BOTH)", 1.80),
    ("rcxboth__fs_v1650_t85_hh", "FS 1.65 V 85 °C hh (RCX_BOTH)", 1.65),
    ("rcxboth__ss_v1650_t-40_hh", "SS 1.65 V −40 °C hh (RCX_BOTH)", 1.65),
]


def find_coincident_rise(w: spice.Waves, vdd: float) -> float:
    """Find a steady-state q8p rising edge (t >= 18 ns) where q2p/q4p/q8p align."""
    t = w.t
    th = 0.5 * vdd
    e8 = clock.edges(t, w["q8p"] - th, start=18e-9, stop=26e-9)
    if len(e8) == 0:
        e8 = clock.edges(t, w["q8p"] - th, start=14e-9, stop=29e-9)
    # Pick the q8p rising edge where q2p and q4p ALSO have a rising edge nearby (within 150 ps)
    for t8 in e8:
        e2 = clock.edges(t, w["q2p"] - th, start=t8 - 0.15e-9, stop=t8 + 0.15e-9)
        e4 = clock.edges(t, w["q4p"] - th, start=t8 - 0.15e-9, stop=t8 + 0.15e-9)
        if len(e2) > 0 and len(e4) > 0:
            return float(t8)
    return float(e8[0])


def nearest_crossing(t: np.ndarray, y: np.ndarray, t0: float, th: float) -> float:
    """Find nearest rising or falling 50% crossing around t0."""
    e_r = clock.edges(t, y - th, start=t0 - 0.25e-9, stop=t0 + 0.25e-9)
    e_f = clock.edges(t, th - y, start=t0 - 0.25e-9, stop=t0 + 0.25e-9)
    es = np.concatenate([e_r, e_f])
    if len(es) == 0:
        return float("nan")
    return float(es[np.argmin(np.abs(es - t0))])


def main() -> None:
    fig, axes = plt.subplots(
        len(CASES), 2, figsize=(13.5, 8.6), gridspec_kw={"width_ratios": [2.2, 1.0]}
    )
    plt.subplots_adjust(hspace=0.38, wspace=0.22, left=0.07, right=0.97, top=0.91, bottom=0.07)

    fig.suptitle(
        "pll_saff_reclock_prescaler8_2g_pdk (v2) — Post-Layout Dual-RCX Working Waveforms (r5_pdk RCX → Divider RCX)",
        fontsize=12.5,
        fontweight="bold",
    )

    colors = {
        "clk": ("#4b5563", "#9ca3af"),
        "q2": ("#1d4ed8", "#93c5fd"),
        "q4": ("#047857", "#6ee7b7"),
        "q8": ("#b91c1c", "#fca5a5"),
    }

    for row_idx, (case_dir, title, vdd) in enumerate(CASES):
        w = spice.Waves(POST_DIR / case_dir / "waveforms.raw")
        t = w.t
        th = 0.5 * vdd
        t_ref = find_coincident_rise(w, vdd)
        t_start = t_ref - 1.0e-9
        t_stop = t_ref + 7.0e-9
        m = (t >= t_start) & (t <= t_stop)
        tn = (t[m] - t_start) * 1e9  # 0 .. 8 ns

        # Left panel: stacked rail-to-rail waveforms
        ax = axes[row_idx, 0]
        step = vdd + 0.55
        offsets = {"q8": 0.0, "q4": step, "q2": 2 * step, "clk": 3 * step}
        labels = {"clk": "clk (2 GHz)", "q2": "q2 (1 GHz)", "q4": "q4 (500 MHz)", "q8": "q8 (250 MHz)"}

        for k in ("clk", "q2", "q4", "q8"):
            off = offsets[k]
            cp, cn = colors[k]
            vp = w[f"{k}p"][m]
            vn = w[f"{k}n"][m]
            ax.axhline(off + th, color="#e5e7eb", lw=0.7, ls="--", zorder=0)
            ax.plot(tn, vn + off, color=cn, lw=0.9, ls="--", alpha=0.85, label=f"{k}n" if row_idx == 0 else None)
            ax.plot(tn, vp + off, color=cp, lw=1.25, label=f"{k}p" if row_idx == 0 else None)
            ax.text(
                0.08,
                off + vdd + 0.12,
                labels[k],
                fontsize=8.5,
                fontweight="bold",
                color=cp,
                bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.82),
            )

        # Mark coincident alignment edge
        ax.axvline((t_ref - t_start) * 1e9, color="#d97706", lw=0.9, ls=":", alpha=0.85)
        ax.set_xlim(0.0, 8.0)
        ax.set_ylim(-0.25, 3 * step + vdd + 0.62)
        ax.set_yticks([])
        ax.set_title(title, fontsize=10.5, fontweight="bold", loc="left")
        ax.grid(axis="x", alpha=0.25)
        if row_idx == len(CASES) - 1:
            ax.set_xlabel("Relative Time (ns) — 2 full q8 cycles (16 input clock cycles)", fontsize=9.5)

        # Right panel: zoomed 260 ps transition-edge alignment of q2 / q4 / q8 (011 -> 100)
        axz = axes[row_idx, 1]
        t2 = nearest_crossing(t, w["q2p"], t_ref, th)
        t4 = nearest_crossing(t, w["q4p"], t_ref, th)
        t8 = nearest_crossing(t, w["q8p"], t_ref, th)
        tc = t2 if not np.isnan(t2) else t_ref
        mz = (t >= tc - 130e-12) & (t <= tc + 130e-12)
        tz = (t[mz] - tc) * 1e12  # ps relative to q2p 50% crossing

        for k in ("q2", "q4", "q8"):
            cp, cn = colors[k]
            axz.plot(tz, w[f"{k}p"][mz], color=cp, lw=1.7, label=f"{k}p")
            axz.plot(tz, w[f"{k}n"][mz], color=cn, lw=1.1, ls="--", alpha=0.85)
        axz.axhline(th, color="#6b7280", lw=0.8, ls=":")
        axz.axvline(0.0, color="#1d4ed8", lw=0.8, ls=":")

        sk42 = (t4 - t2) * 1e12
        sk82 = (t8 - t2) * 1e12
        axz.set_title(
            f"011→100 Edge Zoom (q4−q2={sk42:+.1f} ps, q8−q2={sk82:+.1f} ps)",
            fontsize=9.3,
            fontweight="bold",
        )
        axz.set_xlim(-130, 130)
        axz.set_ylim(-0.15, vdd + 0.15)
        axz.set_ylabel("Voltage (V)", fontsize=8.5)
        axz.grid(alpha=0.28)
        if row_idx == 0:
            axz.legend(loc="center right", fontsize=8, frameon=True)
        if row_idx == len(CASES) - 1:
            axz.set_xlabel("Time relative to q2p 50% crossing (ps)", fontsize=9.5)

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=180)
    plt.close(fig)
    print("Saved:", OUT_PNG)


if __name__ == "__main__":
    main()
