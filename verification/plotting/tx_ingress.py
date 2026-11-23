"""Snapshot and draw the six-condition loaded ingress card, no simulations.

uv run python verification/plotting/tx_ingress.py --collect CAMPAIGN
uv run python verification/plotting/tx_ingress.py
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

DATA = ROOT / "docs/data/tx_ingress_card.json"
FIGURE = ROOT / "docs/figures/tx/ingress/tx_ingress_loaded_delay.png"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(camp):
    summary_path = camp / "summary.json"
    summary = json.loads(summary_path.read_text())
    rows = summary["rows"]
    envelopes, waves, anomalies = [], [], []
    for row in rows:
        if row["status"] != "measured":
            raise ValueError("card has missing/failed observations")
        path = ROOT / row["waveform"]
        w = spice.Waves(path)
        if w.t[-1] < 24e-9 * (1 - 1e-7):
            raise ValueError("truncated waveform")
        waves.append(dict(path=row["waveform"], sha256=sha(path)))
        vdd = float(np.mean(w["vdd"]))
        for cell, suffix in (("lean", "l"), ("reset", "r")):
            for cap in row["metrics"][cell]["captures"]:
                e = cap["clock_edge_s"]
                for name, y in (("q", w[f"q_{suffix}"] - vdd / 2), ("cml", w[f"cp_{suffix}"] - w[f"cn_{suffix}"])):
                    count = sum(len(clock.edges(w.t, y, polarity, start=e, stop=e + 1e-9)) for polarity in (-1, 1))
                    if count != 1:
                        anomalies.append(dict(condition=row["condition"], selected=row["selected"], cell=cell, edge_s=e, signal=name, crossings=count))
    for condition in dict.fromkeys(r["condition"] for r in rows):
        selected = [r for r in rows if r["condition"] == condition]
        if len(selected) != 2 or {r["selected"] for r in selected} != {True, False}:
            raise ValueError("need selected and unselected observations per condition")
        for cell in ("lean", "reset"):
            ms = [r["metrics"][cell] for r in selected]
            caps = [c for m in ms for c in m["captures"]]
            envelopes.append(dict(condition=condition, cell=cell, functional=all(m["functional"] for m in ms),
                                  tcq_min_ps=min(m["tcq_min_ps"] for m in ms), tcq_max_ps=max(m["tcq_max_ps"] for m in ms),
                                  clock_to_cml_min_ps=min(m["clock_to_cml_min_ps"] for m in ms), clock_to_cml_max_ps=max(m["clock_to_cml_max_ps"] for m in ms),
                                  clock_cap_min_ff=min(c["clock_charge_equivalent_cap_f"] * 1e15 for c in caps),
                                  clock_cap_max_ff=max(c["clock_charge_equivalent_cap_f"] * 1e15 for c in caps)))
    data = dict(scope=summary["scope"], summary=dict(path=str(summary_path.relative_to(ROOT)), sha256=sha(summary_path)),
                plan=dict(path=str((camp / "plan.json").relative_to(ROOT)), sha256=sha(camp / "plan.json")),
                waveforms=waves, envelopes=envelopes, extra_crossing_anomalies=anomalies, captures=120,
                units="ps and fF; per-condition envelopes combine two static mux states and rising/falling data; not jitter or full-PVT qualification")
    DATA.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    (ROOT / "results/catalog/tx_ingress_card.json").write_text(json.dumps(dict(data=str(DATA.relative_to(ROOT)), report="docs/design/tx_ingress.md",
               campaign=str(camp.relative_to(ROOT)), figure=str(FIGURE.relative_to(ROOT)), cases=len(rows), captures=120, extra_crossing_anomalies=len(anomalies)), indent=2) + "\n")
    return data


def plot(data):
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    conditions = list(dict.fromkeys(r["condition"] for r in data["envelopes"]))
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.9))
    for ax, prefix, title in zip(axes, ("tcq", "clock_to_cml"), ("实际转换器负载下：时钟 → CMOS Q", "时钟 → 已加载的 CML 数据对")):
        for cell, offset, color in (("lean", -.12, "#277ca0"), ("reset", .12, "#c77a37")):
            rows = [next(r for r in data["envelopes"] if r["condition"] == c and r["cell"] == cell) for c in conditions]
            lo, hi = [np.array([r[f"{prefix}_{side}_ps"] for r in rows]) / 1000 for side in ("min", "max")]
            ax.errorbar(np.arange(len(rows)) + offset, (hi + lo) / 2, yerr=(hi - lo) / 2, fmt="o", capsize=4, color=color, label=cell)
        labels = [f"{c.process.upper()}\n{c.supply:g}V / {c.temp}°C" for c in map(Condition.parse, conditions)]
        ax.set_xticks(np.arange(len(conditions)), labels, fontsize=8)
        ax.set_ylabel("门限交越延迟 / ns")
        ax.set_title(title)
        ax.grid(axis="y", alpha=.2)
        ax.legend()
    fig.suptitle("TX 字入口单元：两种既有 CMOS DFF 的实测延迟", fontsize=14, fontweight="bold")
    fig.text(.02, .015, "6 压力条件 × MUX 静态选中/未选中；真实偏置/PDK R tt；30 ps 理想时钟端口；范围不是随机抖动。", fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, .94))
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE, dpi=160)
    fig.savefig(FIGURE.with_suffix(".svg"))
    plt.close(fig)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collect", type=Path)
    args = p.parse_args()
    data = collect(args.collect.resolve()) if args.collect else json.loads(DATA.read_text())
    plot(data)
    print(DATA.relative_to(ROOT), FIGURE.relative_to(ROOT))
