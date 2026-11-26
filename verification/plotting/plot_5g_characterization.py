#!/usr/bin/env python3
"""Render standalone figures from the archived 5G staged co-simulation summary."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.backends.backend_pdf import PdfPages

COLORS = ("#22648a", "#b45617", "#14816d", "#74488a")


def finish(fig, name, output, pdf):
    fig.savefig(output / f"{name}.png", dpi=180)
    pdf.savefig(fig)
    plt.close(fig)


def plot(summary, output):
    pll = list(summary["stage1_pll"].values())
    ids = [row["condition"] for row in pll]
    tx = [summary["stage2a_tx_ch"][key] for key in ids]
    rx = [summary["stage2b_rx"][key] for key in ids]
    power = [summary["system_power_and_efficiency"][key] for key in ids]
    labels = [row["label"].rsplit(" ", 1)[0] for row in pll]
    x = np.arange(len(ids))
    footer = "24 Nov 2026  |  Archived staged 5 Gb/s co-simulation"
    output.mkdir(parents=True)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.axisbelow": True})

    with PdfPages(output / "5g_characterization.pdf") as pdf:
        fig, axes = plt.subplots(1, 2, figsize=(10, 4.2), layout="constrained")
        fig.suptitle("Link voltage margin and edge spread", fontsize=15)
        stages = ("TX pad", "C2 far-end", "CTLE / stage 2A", "CTLE / slicer load")
        samples = [list(d[k] for k in ("tx_pad", "c2_farend", "ctle_out")) +
                   [r["ctle_loaded_by_slicers"]] for d, r in zip(tx, rx)]
        for ax, key, limit, unit in zip(axes, ("margin_mv", "spread_ui"), (75, 0.15),
                                        ("Signed bit-center margin (mV)", "Edge spread (UI)")):
            ax.set_xticks(range(4), stages)
            for i, (row, label) in enumerate(zip(samples, labels)):
                values = [p[key] for p in row]
                ax.plot(range(3), values[:3], "o-", label=label, color=COLORS[i])
                ax.scatter(3, values[3], marker="D", color=COLORS[i], s=36)
            ax.axhline(limit, color="#963844", ls="--", label=f"Draft limit {limit}")
            ax.set_ylabel(unit)
            ax.tick_params(axis="x", labelrotation=16)
            ax.grid(axis="y", alpha=.22)
        axes[0].legend(frameon=False, fontsize=8)
        axes[1].annotate("TT: 0.1615 UI", (3, samples[0][-1]["spread_ui"]),
                         xytext=(-93, 14), textcoords="offset points")
        fig.supxlabel(footer + "  |  Diamonds show the separate stage 2B CTLE measurement", fontsize=8)
        finish(fig, "link_margin", output, pdf)

        fig, axes = plt.subplots(1, 2, figsize=(10, 4.1), layout="constrained")
        fig.suptitle("PLL quadrature and divider duty cycle", fontsize=15)
        axes[0].axhspan(-8, 8, color="#dcefea")
        axes[0].bar(x, [r["iq_err_ps"] for r in pll], width=.5, color=COLORS[0])
        axes[0].set_ylim(-9, 9)
        axes[0].set_ylabel("I/Q error relative to nearest quadrature (ps)")
        axes[0].set_title("Stage 1 acceptance band ±8 ps")
        axes[1].plot(x, [r["ic_duty_pct"] for r in pll], "o-", label="2.5 GHz I", color=COLORS[0])
        axes[1].plot(x, [r["fb250_duty_pct"] for r in pll], "s-", label="250 MHz feedback", color=COLORS[1])
        axes[1].axhline(50, lw=.8, color="#777")
        axes[1].set_ylabel("Duty cycle (%)")
        axes[1].legend(frameon=False)
        for ax in axes:
            ax.set_xticks(x, labels, rotation=14)
            ax.grid(axis="y", alpha=.24)
        fig.supxlabel(footer + "  |  Completed corners only", fontsize=8)
        finish(fig, "pll_clock_quality", output, pdf)

        fig, ax = plt.subplots(figsize=(8.8, 4.5), layout="constrained")
        groups = ("PLL + CML→CMOS", "TX + divider", "RX")
        keys = ("p_pll_with_c2c_mw", "p_tx_total_mw", "p_rx_total_mw")
        bottom = np.zeros(len(ids))
        for i, (group, key) in enumerate(zip(groups, keys)):
            values = np.array([r[key] for r in power])
            ax.bar(x, values, bottom=bottom, color=COLORS[i], label=group, width=.54)
            for pos, y, val in zip(x, bottom, values):
                ax.text(pos, y + val/2, f"{val:.1f}", va="center", ha="center", color="white")
            bottom += values
        for pos, y, r in zip(x, bottom, power):
            if abs(y-r["p_total_5g_mw"]) > .03:
                raise ValueError("Power total does not match stage attribution")
            ax.text(pos, y+1.7, f'{r["pj_per_bit"]:.2f} pJ/bit', ha="center")
        ax.set_xticks(x, labels)
        ax.set_ylim(0, bottom.max() * 1.24)
        ax.set_title("Analog power by stage", fontsize=15)
        ax.set_ylabel("Average power (mW)")
        ax.legend(frameon=False, ncol=3, loc="upper center")
        ax.grid(axis="y", alpha=.2)
        fig.supxlabel(footer + "  |  Digital power excluded", fontsize=8)
        finish(fig, "analog_power", output, pdf)

        fig, axes = plt.subplots(1, len(ids), figsize=(10, 4.0), sharey=True, layout="constrained")
        fig.suptitle("RX phase probes and BBPD response", fontsize=15)
        for ax, row, label in zip(axes, rx, labels):
            ax.axhline(0, color="#8d8d8d", linewidth=.8)
            ax.set_title(label)
            for p in row["points"]:
                ok = p["ok"]
                ax.scatter(p["offset_ui"], p["bbpd_vote"], marker="o" if ok else "x", s=52,
                           color=COLORS[0] if ok else "#a92842")
                if not ok:
                    ax.annotate(f'{p["data_errors"]}/{p["data_bits"]} bit errors',
                                (p["offset_ui"], p["bbpd_vote"]), xytext=(-5, -19),
                                textcoords="offset points", ha="right", color="#a92842", fontsize=9)
            ax.set_xticks([-.25, 0, .25])
            ax.set_xlim(-.36, .36)
            ax.set_ylim(-30, 30)
            ax.set_xlabel("Offset from selected PI code (UI)")
            ax.grid(axis="y", alpha=.2)
        axes[0].set_ylabel("Signed BBPD vote sum")
        fig.supxlabel(footer + "  |  Discrete probes, 64 checked bits per point", fontsize=8)
        finish(fig, "rx_phase_probes", output, pdf)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("summary", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    plot(json.loads(args.summary.read_text()), args.output)
