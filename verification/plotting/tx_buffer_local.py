"""Verify/publish the explicitly identified Xe2 local calibration, no simulation."""
import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project

ROOT = project.ROOT
RUNNER = ROOT / "analog/tx/input_register/tb/final_clock_chain/buffer_local_card.py"


def main(campaign, summary):
    spec = importlib.util.spec_from_file_location("buffer_card", RUNNER)
    card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)
    plan = card.check(campaign, registered=True)
    data = json.loads(summary.read_text())
    if data["status"] != "measured" or len(data["rows"]) != 2:
        raise ValueError("Incomplete card")
    if summary.parent.parent.parent != campaign:
        raise ValueError("Summary from a different campaign")
    points = json.loads((card.SOURCE / "boundary.json").read_text())["points"]
    predictions = {}; evidence = {}
    for row in data["rows"]:
        raw = card.completed(campaign, row["condition"])
        if raw is None or str(raw.relative_to(ROOT)) != row["raw"] or card.digest(raw) != row["raw_sha256"]:
            raise ValueError("Raw evidence changed")
        actual = json.loads(json.dumps(card.measure(campaign, row["condition"], raw, points[row["condition"]]), default=card.json_default, allow_nan=False))
        if actual != row["result"] or not actual["baseline_matches"]:
            raise ValueError("Independent measurement or baseline differs")
        branches = actual["branches"]
        if [b["branch"] for b in branches] != ["baseline", "tail_only", "R_only"]:
            raise ValueError("Unexpected parameters")
        # Two one-axis calibration points: a separable I*R-inspired local model.
        # This is a prediction for the next experiment, not a fourth measurement.
        v = [b["nodes"]["xe2_output"]["differential_pp_v"] for b in branches]
        predictions[row["condition"]] = dict(wt_um=12.8, r_nominal_ohm=320,
            predicted_xe2_pp_v=v[1] * v[2] / v[0],
            predicted_c2g_shift_s=branches[1]["clock_fall_shift_s"] + branches[2]["clock_fall_shift_s"],
            status="ungraded_prediction_only", model="separable amplitude ratios; additive small delay perturbations; no joint simulation")
        run = raw.parent
        evidence[row["condition"]] = {p.name: card.digest(p) for p in [raw, run / "execution.json", run / "tb.cir", run / "simulator.log"]}
    published = dict(scope="TT and FS low-voltage hot, physical archived extra5 clock/slice/driver/channel cut, fixed ideal recorded input/bias/supplies. Only Xe2 changes. Local8bit window, no upstream impedance or full TX/PVT/noise/I17 qualification.",
                     campaign=str(campaign.relative_to(ROOT)), summary=str(summary.relative_to(ROOT)), summary_sha256=card.digest(summary),
                     plan_sha256=card.digest(campaign / "plan.json"), runner_sha256=card.digest(RUNNER), generator_sha256=card.digest(Path(__file__)),
                     parameters=[dict(branch="baseline", wn_um=24, wt_um=16, r_nominal_ohm=400), dict(branch="tail_only", wn_um=24, wt_um=12.8, r_nominal_ohm=400), dict(branch="R_only", wn_um=24, wt_um=16, r_nominal_ohm=320)],
                     evidence=evidence, results=data["rows"], next_joint_prediction=predictions,
                     ungraded=plan["ungraded"])
    output = ROOT / "docs/data/tx_buffer_local.json"
    output.write_text(json.dumps(published, indent=2, allow_nan=False) + "\n")
    (ROOT / "results/catalog/tx_buffer_local.json").write_text(json.dumps(dict(data=str(output.relative_to(ROOT)), data_sha256=card.digest(output), campaign=published["campaign"], summary=published["summary"], summary_sha256=published["summary_sha256"], runner_sha256=published["runner_sha256"], evidence=evidence, scope=published["scope"]), indent=2) + "\n")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), layout="constrained")
    colors = ["#176c8c", "#388c70", "#d27732"]
    labels = ["baseline16/400", "tail12.8/400", "R16/320"]
    for row, ax in zip(data["rows"], axes[0]):
        for n, branch in enumerate(row["result"]["branches"]):
            ax.bar(np.arange(3) + (n - 1) * .23, [branch["nodes"][k]["differential_pp_v"] * 1000 for k in ("xe2_output", "xe3_output", "c2g")], width=.22, label=labels[n], color=colors[n])
        ax.axhspan(200, 400, color="#388c70", alpha=.08)
        ax.axhline(400, ls="--", color="#b34545"); ax.axhline(200, ls=":", color="#777")
        ax.set(xticks=range(3), xticklabels=["Xe2", "Xe3 next stage", "c2g"], ylabel="Observed differential pp (mV)", title=row["condition"], ylim=(0, 600))
        ax.legend(fontsize=7)
    for row, color in zip(data["rows"], ("#176c8c", "#cf4951")):
        branches = row["result"]["branches"]
        axes[1, 0].plot(range(3), [b["clock_fall_shift_s"] * 1e12 for b in branches], "o-", color=color, label=row["condition"])
        axes[1, 1].plot(range(3), [b["metrics"]["transition_spread_ui"] for b in branches], "o-", color=color, label=row["condition"])
    axes[1, 0].set(ylabel="c2g shift from old extra5 (ps)", title="Original extra3-to-extra5 delay retained in sample phase")
    axes[1, 1].set(ylabel="Local eight-bit transition spread (UI)", title="Original training phase plus measured clock propagation")
    axes[1, 1].axhline(.15, ls="--", color="#b34545")
    for ax in axes[1]:
        ax.set_xticks(range(3), ["baseline", "tail only", "R only"]); ax.legend(fontsize=8); ax.grid(alpha=.2)
    fig.suptitle("TX I-17: one non-regenerating stage, calibrated before sizing; other stages still over amplitude", fontsize=12)
    figure = ROOT / "docs/figures/tx/ingress/tx_buffer_local.png"
    fig.savefig(figure, dpi=160); plt.close(fig)
    print(json.dumps(dict(campaign=published["campaign"], next_joint_prediction=predictions, evidence_verified=True), indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    a = ap.parse_args()
    main(a.campaign.resolve(), a.summary.resolve())
