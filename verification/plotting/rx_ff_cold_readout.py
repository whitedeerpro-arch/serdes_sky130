"""Read-only verification/publication of the fixed FF W40 DC and readout test.

Explicit inputs only. DC-only publication does not imply functional readout.
Full publication independently repeats the original word/mapping analysis.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import boundary, eye, project, spice
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = ROOT / "analog/rx/sampler/tb/cold_readout_layers"


def module(name):
    sys.path.insert(0, str(HERE))
    try:
        spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
        obj = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(obj)
        return obj
    finally:
        sys.path.pop(0)


def equal(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        return isinstance(b, (int, float)) and not isinstance(b, bool) and np.isclose(a, b, rtol=1e-10, atol=1e-10)
    return a == b


def main(dc_campaign, pilot_path, full_path):
    dc = module("ff_direct_dc")
    plan, candidate = dc.verify(dc_campaign, registered=True)
    dc_run = dc_campaign / "ff_direct_dc"
    result = dc.assess(dc_campaign, dc_run, candidate)
    inputs = dict(dc_campaign=str(dc_campaign.relative_to(ROOT)), dc_plan_sha256=dc.sha(dc_campaign / "plan.json"),
                  dc_raw_sha256=dc.sha(dc_run / "op.raw"), dc_execution_sha256=dc.sha(dc_run / "execution.json"),
                  collector_sha256=dc.sha(Path(__file__)))
    data = dict(scope="FF1.95V/-40C/hh,current W40,PI20/trim32/rb2k,real bias,fixed nominal C2 replay and ideal phase anchors; no physical startup, native PLL, full PVT, noise or BER qualification",
                dc=result, provenance=inputs, publication="dc_only", short_window_functional_checks_pass=None)
    if pilot_path is not None:
        m = module("ff_transient_dc")
        campaign = full_path.parent.parent.parent
        if pilot_path.parent.parent.parent != campaign or m.PARENT != dc_campaign:
            raise ValueError("Different transient or DC parent")
        mp, nodes = m.verify(campaign, registered=True)
        evidence = {}
        checked = {}
        for case, path in [("pilot", pilot_path), ("full", full_path)]:
            summary = json.loads(path.read_text())
            row = summary["result"]
            run = ROOT / row["run"]
            if run.parent != campaign or row["case"] != case or row["status"] != "observed" or row["error"] is not None:
                raise ValueError("Incomplete run or wrong boundary")
            if dc.sha(run / "execution.json") != row["execution_sha256"] or dc.sha(run / "wave.raw") != row["raw_sha256"]:
                raise ValueError("Run evidence changed")
            info = m.assess(campaign, run, case, nodes)
            if not equal(info, row["stages"]):
                raise ValueError("Transient health changed")
            evidence[case] = dict(summary=str(path.relative_to(ROOT)), summary_sha256=dc.sha(path), run=str(run.relative_to(ROOT)),
                                  raw_sha256=row["raw_sha256"], execution_sha256=row["execution_sha256"])
            checked[case] = (row, run)
        row, run = checked["full"]
        analyzer = m.fs.load_analysis()
        boundary.check_load(m.REPLAY, analyzer.sp.replay.signature())
        actual = analyzer.analyse(run / "wave.raw", Condition("ff", 1.95, -40), 20, eye.prbs7(analyzer.sp.link.NBITS))
        if not equal(actual, row["readout_analysis"]):
            raise ValueError("Independent analysis differs")
        window = [analyzer.sp.link.T0 + (analyzer.sp.link.WARM + 6) * analyzer.sp.link.UI, 44.75e-9]
        if not equal(window, row["analysis_window_s"]):
            raise ValueError("Measurement window changed")
        data.update(publication="dc_and_full_transient", campaign=str(campaign.relative_to(ROOT)), analysis=actual,
                    measurement_window_ns=[x * 1e9 for x in window], data_bits=16 * actual["words"],
                    single_lane_ambiguities={k: v for k, v in actual["derived"].items() if len(v) != 1},
                    short_window_functional_checks_pass=bool(actual["words"] >= 4 and actual["data_errors"] == 0 and actual["edge_errors"] == 0 and actual["map_ok"]))
        inputs.update(transient_plan_sha256=dc.sha(campaign / "plan.json"), evidence=evidence,
                      analyzer_sources=mp["source_hashes"], replay_bc=m.REPLAY, seed_bc=m.BC)
        w = spice.Waves(run / "wave.raw")
        fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True, layout="constrained")
        ns = w.t * 1e9
        axes[0].plot(ns, w["v(rxp)"] - w["v(rxn)"], lw=.8, color="#176c8c")
        axes[0].set_ylabel("C2 input\ndifference (V)")
        axes[1].plot(ns, w["v(xro.ckq)"], lw=.7, label="ckq")
        axes[1].plot(ns, w["v(w)"], lw=1, label="word clock")
        axes[1].set_ylabel("Clock (V)"); axes[1].legend(fontsize=8)
        for n, key in enumerate(("a0_0", "b0_2", "a1_0", "b1_0")):
            axes[2].plot(ns, w[f"v({key})"] / 1.95 + n * 1.4, lw=.8)
        axes[2].set_yticks([0, 1.4, 2.8, 4.2], ["a0_0", "b0_2", "a1_0", "b1_0"])
        axes[2].set(xlabel="Time (ns)", ylabel="Word outputs\n(offset)")
        for ax in axes:
            ax.axvspan(0, window[0] * 1e9, color=".92", zorder=-5)
            ax.set_xlim(0, 44.75); ax.grid(alpha=.2)
        fig.suptitle(f"FF cold W40: {actual['words']} usable words; data errors {actual['data_errors']}, edge errors {actual['edge_errors']}\nFixed C2/ideal phases; same-FF soft DC guesses, no solver fallback", fontsize=11)
        figure = ROOT / "docs/figures/rx/readout/ff_cold_w40_words.png"
        figure.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(figure, dpi=160); plt.close(fig)
        data["figure"] = str(figure.relative_to(ROOT))
    output = ROOT / "docs/data/rx_ff_cold_readout.json"
    output.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    catalog = dict(data=str(output.relative_to(ROOT)), data_sha256=dc.sha(output), publication=data["publication"],
                   scope=data["scope"], provenance=inputs)
    (ROOT / "results/catalog/rx_ff_cold_readout.json").write_text(json.dumps(catalog, indent=2) + "\n")
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dc-campaign", type=Path, required=True)
    ap.add_argument("--pilot-summary", type=Path)
    ap.add_argument("--full-summary", type=Path)
    a = ap.parse_args()
    if bool(a.pilot_summary) != bool(a.full_summary):
        ap.error("pilot and full summaries must be supplied together")
    main(a.dc_campaign.resolve(), a.pilot_summary.resolve() if a.pilot_summary else None,
         a.full_summary.resolve() if a.full_summary else None)
