"""Publish a compact comparison from an explicit, completed model/audit summary."""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow.project import ROOT


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--split-summary", type=Path, required=True)
    a = ap.parse_args()
    source = a.summary.resolve()
    data = json.loads(source.read_text())
    split_source = a.split_summary.resolve()
    split = json.loads(split_source.read_text())
    for record in data["inputs"] + data["code"] + split["inputs"] + split["code"]:
        if hashlib.sha256((ROOT / record["path"]).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Analysis input changed: {record['path']}")
    candidates = {r["name"]: r for r in data["candidates"]}
    names = ["k4_h13", "k4_retuned", "k6_retuned", "k8"]
    labels = ["200 uA\noriginal R/C, 23/36", "200 uA\nretuned R/C + 100 fF", "300 uA\nretuned R/C + 100 fF", "400 uA\nretuned R/C"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), layout="constrained")
    x = np.arange(len(names))
    ax = axes[0]
    ax.bar(x, [candidates[n]["supply_max_hz_per_v"] / 1e6 for n in names], color="#408b9a", alpha=.8, label="19-point supply model")
    for i, n in enumerate(names):
        if n in data["measured"]:
            ax.scatter(i, data["measured"][n]["max_hz_per_v"] / 1e6, color="#c85432", marker="D", s=45,
                       label="Measured maximum (different coverage)" if i == 0 else None, zorder=3)
    ax.axhline(150, color="#b54f42", linestyle="--", label="150 MHz/V gate")
    ax.set(ylabel="20 MHz supply sensitivity (MHz/V)", title="Retuning does not require doubling CP current", ylim=(0, 180))
    ax.legend(fontsize=8, frameon=False, loc="lower left")
    ax = axes[1]
    for j, color, label in [(0, "#408b9a", "Model includes Vctrl >= 1.00 V"), (2, "#d18a46", "Model includes Vctrl >= 0.90 V, H4")]:
        offset = -.18 if j == 0 else .18
        ax.bar(x + offset, [candidates[n]["stability"][j]["pm_min_deg"] for n in names], width=.34, color=color, label=label)
    ax.axhline(50, color="#b54f42", linestyle="--")
    ax.set(ylabel="Minimum phase margin in included model plants (deg)", title="A common dependency: which codes can be visited?", ylim=(0, 65))
    ax.legend(fontsize=8, frameon=False, loc="lower left")
    for ax in axes:
        ax.set_xticks(x, labels, fontsize=8)
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("PLL supply alternatives: models for comparison, not electrical qualification", fontsize=12)
    fig_path = ROOT / "docs/figures/clocking/pll/core/pll_supply_choices.png"
    fig.savefig(fig_path, dpi=170)
    plt.close(fig)
    doc = dict(summary=str(source.relative_to(ROOT)), summary_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
               figure=str(fig_path.relative_to(ROOT)), candidates=data["candidates"],
               split_summary=str(split_source.relative_to(ROOT)), split_summary_sha256=hashlib.sha256(split_source.read_bytes()).hexdigest(),
               programmable_split_bounds=split,
               measured={k: {p: v for p, v in r.items() if p != "rows"} for k, r in data["measured"].items()},
               limits=data["limits"], interpretation="Low-voltage PM values concern all included quadratic-fit code plants, not a validated selection trajectory or measured failure")
    (ROOT / "docs/data/pll_supply_choices.json").write_text(json.dumps(doc, indent=2, allow_nan=False) + "\n")
    (ROOT / "results/catalog/pll_supply_choices.json").write_text(json.dumps(dict(
        data="docs/data/pll_supply_choices.json", figure=doc["figure"], analysis=doc["summary"],
        analysis_sha256=doc["summary_sha256"], split_analysis=doc["split_summary"], split_analysis_sha256=doc["split_summary_sha256"],
        scope="Independent model comparison and raw audit; no DUT changes or new ngspice; not adopted"), indent=2) + "\n")
    print(fig_path.relative_to(ROOT))


if __name__ == "__main__":
    main()
