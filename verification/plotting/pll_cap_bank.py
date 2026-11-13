"""Physical shared-plate bank and corrected local AC calibration."""
from pathlib import Path
import argparse
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow.project import ROOT
sys.path.insert(0, str(ROOT / "analog/layout/scripts"))
from layout_core import load_mag_as_canvas, plot_canvas  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layout-run", type=Path, required=True)
    ap.add_argument("--ac-run", type=Path, required=True)
    args = ap.parse_args()
    cell = "pll_vco_cap_bank5_shared"
    geo = json.loads((args.layout_run / "summary.json").read_text())
    ac = json.loads((args.ac_run / "summary.json").read_text())
    fig = plt.figure(figsize=(14, 10), dpi=150)
    grid = fig.add_gridspec(2, 2, height_ratios=[1.2, 1], hspace=.55, wspace=.28)
    ax = fig.add_subplot(grid[0, :])
    plot_canvas(ax, load_mag_as_canvas(args.layout_run / f"{cell}.mag", cell),
                "31 MIMs / five shared floating plates / 62 switch fingers",
                "Physical candidate: full-rule DRC 0, LVS + 7 ports + dimensions checked", show_cuts=True)
    for p in geo["placements"]:
        x1, _, x2, _ = p["bbox_um"]
        ax.text((x1+x2)/2, 15.4, f"bit {p['bit']} : {p['units']} MIM", ha="center", fontsize=9)
    ax.set_ylim(bottom=-5.2, top=16.5)
    x0, y0, x1, y1 = geo["bbox_um"]
    ax.set_title(f"Shared-plate circuit iteration — {x1-x0:.2f} x {y1-y0:.2f} um", fontsize=13, pad=40)
    codes = [r["code"] for r in ac["rows"]]
    planning = np.array([r["planning"] for r in ac["rows"]])
    physical = np.array([r["physical"] for r in ac["rows"]])
    axc, axs = fig.add_subplot(grid[1, 0]), fig.add_subplot(grid[1, 1])
    axc.plot(codes, planning, label="r6 planning", color="#777777")
    axc.plot(codes, physical, ".-", label="physical bank / audited EXT matrix", color="#177987", markersize=3)
    axc.set(xlabel="Code", ylabel="Effective capacitance at 2 GHz (fF)", title="All codes remain monotone")
    axc.legend(fontsize=8)
    axs.plot(codes[:-1], np.diff(physical), ".-", color="#177987", label="physical code increment")
    axs.axhline(np.diff(planning).mean(), color="#777777", linestyle="--", label="planning LSB")
    axs.set(xlabel="Transition k to k+1", ylabel="Capacitance increment (fF)", title="Bit-group parasitics alter the increments")
    axs.legend(fontsize=8)
    for a in (axc, axs):
        a.grid(alpha=.2)
    fig.text(.08, .035, "AC boundary: TT / 27 C, phase DC 1.5 V, control 0 / 1.8 V. Geometry shown is one phase-node bank.\n"
             "Independent floating plates are joined only within each bit. Dynamic code switching / mismatch / full PLL remain separate checks.", fontsize=9)
    fig.subplots_adjust(top=.89, bottom=.13)
    out = ROOT / "docs/figures/layout/pll_r6_cap_bank.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(out)


if __name__ == "__main__":
    main()
