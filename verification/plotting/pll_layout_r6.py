"""Render actual PLL leaf geometry, with explicit iteration/qualification labels."""
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from serdes_flow.project import ROOT

sys.path.insert(0, str(ROOT / "analog/layout/scripts"))
from layout_core import load_mag_as_canvas, plot_canvas  # noqa: E402


def main() -> None:
    source = ROOT / "analog/pll/vco/layout/variants/r6_pdk"
    fig, axes = plt.subplots(1, 2, figsize=(13, 7), dpi=160)
    for ax, name, text in [
        (axes[0], "pll_vco_cap_unit_r6_pdk", "r6 half-unit: 2 x 2 um MIM / shared-drain 2 x 0.75 um NMOS"),
        (axes[1], "pll_vco_varactor_clean", "Gemini core retained: 4 x 5.2/0.5 um varactors / continuous guard"),
    ]:
        canvas = load_mag_as_canvas(source / f"{name}.mag", name)
        plot_canvas(ax, canvas, text, "Full-rule DRC / LVS / exported ports checked", show_cuts=True)
    fig.text(.07, .15, "Compact contact candidate; electrical adoption pending.\nNot a complete PLL layout.",
             fontsize=9, va="top")
    fig.text(.56, .15, "Invalid guard-crossing dummy bars removed.\nElectrical matching/noise remain separate checks.",
             fontsize=9, va="top")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=6, fontsize=8, frameon=False)
    fig.subplots_adjust(bottom=.26, top=.90, wspace=.25)
    out = ROOT / "docs/figures/layout/pll/pll_r6_leaves.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
