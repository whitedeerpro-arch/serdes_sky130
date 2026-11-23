"""Translate a single supply tone into explicit clock-jitter units.

Small-signal arithmetic, not circuit simulation or a BER prediction. The source
K excludes closed-loop error sensitivity; --loop-gain supplies its magnitude.
The relative-clock examples assume identical transfer functions and no CDR
tracking of this tone. No existing specification is changed.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow.project import ROOT


def tone_jitter(voltage_pp_v, k_hz_per_v, tone_hz, carrier_hz, bit_rate_hz, loop_gain):
    if min(k_hz_per_v, tone_hz, carrier_hz, bit_rate_hz, loop_gain) <= 0 or voltage_pp_v < 0:
        raise ValueError("Positive frequencies, sensitivity and gain, nonnegative voltage required")
    peak_s = k_hz_per_v * voltage_pp_v / 2 * loop_gain / (2 * np.pi * tone_hz * carrier_hz)
    return dict(voltage_pp_v=voltage_pp_v, voltage_peak_v=voltage_pp_v / 2,
                frequency_deviation_peak_hz=k_hz_per_v * voltage_pp_v / 2,
                jitter_peak_s=peak_s, jitter_pp_s=2 * peak_s, jitter_rms_s=peak_s / np.sqrt(2),
                jitter_peak_ui=peak_s * bit_rate_hz, jitter_pp_ui=2 * peak_s * bit_rate_hz,
                equal_tx_rx_relative_pp_ui={
                    "same_response_same_phase": 0.,
                    "same_response_phase_90deg": 2 * peak_s * bit_rate_hz * np.sqrt(2),
                    "same_response_phase_180deg_worst": 4 * peak_s * bit_rate_hz})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--carrier-hz", type=float, default=2e9)
    ap.add_argument("--bit-rate-hz", type=float, default=4e9)
    ap.add_argument("--tone-hz", type=float, default=20e6)
    ap.add_argument("--loop-gain", type=float, default=1.3, help="Assumed |1/(1+L)|, not measured closed-loop gain")
    ap.add_argument("--relative-budget-uipp", type=float, default=.05)
    a = ap.parse_args()
    source = ROOT / "docs/data/pll_supply_choices.json"
    evidence = json.loads(source.read_text())
    sensitivity = {"current_12_6": 160.2e6, "design_gate": 150e6,
                   "retuned_200uA_model": next(r["supply_max_hz_per_v"] for r in evidence["candidates"] if r["name"] == "k4_retuned"),
                   "candidate_400uA_six_measured": evidence["measured"]["k8"]["max_hz_per_v"]}
    rows = {label: [tone_jitter(mvpp * 1e-3, k, a.tone_hz, a.carrier_hz, a.bit_rate_hz, a.loop_gain)
                    for mvpp in (5., 10., 20., 30., 50., 100.)] for label, k in sensitivity.items()}
    budget = {}
    for label, k in sensitivity.items():
        at_one_v = tone_jitter(1., k, a.tone_hz, a.carrier_hz, a.bit_rate_hz, a.loop_gain)
        budget[label] = dict(
            voltage_pp_for_one_clock_peak_0_05ui_v=.05 / at_one_v["jitter_peak_ui"],
            voltage_pp_for_one_clock_pp_0_05ui_v=.05 / at_one_v["jitter_pp_ui"],
            each_voltage_pp_for_two_clocks_worst_relative_budget_v=a.relative_budget_uipp / at_one_v["equal_tx_rx_relative_pp_ui"]["same_response_phase_180deg_worst"])
    # A total eye-width allocation uses peak-to-peak relative jitter. This is an
    # alternate interpretation to audit, not a replacement for the current gate.
    required_k = a.relative_budget_uipp * (2 * np.pi * a.tone_hz * a.carrier_hz) / (2 * .010 * a.loop_gain * a.bit_rate_hz)
    data = dict(args=vars(a), source_path=str(source.relative_to(ROOT)), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                script_path=str(Path(__file__).resolve().relative_to(ROOT)), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                sensitivities_hz_per_v=sensitivity, rows=rows, voltage_budget=budget,
                maximum_k_for_two_equal_10mvpp_rails_at_relative_budget_hz_per_v=required_k,
                assumptions=["Single sinusoidal tone on one PLL rail; K is the LF-loaded open-loop supply sensitivity",
                             "Closed-loop error-sensitivity magnitude is a scalar assumption, not a measured response",
                             "Jitter is time error of a 2 GHz carrier expressed in 4 Gb/s data UI by default",
                             "Relative examples assume equal transfer functions; unknown tone phase requires a worst-case bound, not Gaussian RSS",
                             "CDR does not track the example tone; no buffer/receiver/CP-supply effects, supply PSD or BER is included",
                             "K measured with a 5 mV peak tone is linearly extrapolated; larger tones have not been validated"],
                budget_issue="spec.md subtracts 0.05 UI from a full-width eye budget but derives its supply gate using 0.05 UI peak of one clock; peak/pp and relative TX/RX allocation require reconciliation; current gate retained")
    out = ROOT / "results/verification/pll_ripple_budget" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True)
    (out / "runner.py").write_bytes(Path(__file__).read_bytes())
    (out / "summary.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    compact = dict(data, analysis_path=str((out / "summary.json").relative_to(ROOT)))
    (ROOT / "docs/data/pll_ripple_budget.json").write_text(json.dumps(compact, indent=2, allow_nan=False) + "\n")
    fig, axes = plt.subplots(1, 2, figsize=(11.8, 4.9), layout="constrained")
    vpp = np.linspace(0, .05, 101)
    colors = ("#b45f43", "#777777", "#16857f", "#4a6fba")
    labels = ("Current 12/6, K=160.2 M", "Design gate, K=150 M", "Retuned 200 uA, modeled K=118.9 M", "400 uA, measured max K=121.6 M")
    for (name, k), color, label in zip(sensitivity.items(), colors, labels):
        jitter = [tone_jitter(v, k, a.tone_hz, a.carrier_hz, a.bit_rate_hz, a.loop_gain) for v in vpp]
        axes[0].plot(vpp * 1e3, [r["jitter_pp_s"] * 1e12 for r in jitter], color=color, label=label)
        axes[1].plot(vpp * 1e3, [r["equal_tx_rx_relative_pp_ui"]["same_response_phase_180deg_worst"] for r in jitter], color=color)
    axes[0].set(ylabel="One clock: timing jitter, ps peak-to-peak", title="Ripple is not a functional-failure threshold")
    axes[0].legend(frameon=False, fontsize=8)
    axes[1].axhline(a.relative_budget_uipp, color="#b54f42", linestyle="--", label="0.05 UIpp example relative allocation")
    axes[1].set(ylabel="Two clocks: worst relative jitter, UI peak-to-peak", title="Equal tone amplitudes; opposite effective phase")
    axes[1].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.set_xlabel(f"{a.tone_hz / 1e6:g} MHz supply tone, mV peak-to-peak")
        ax.axvline(10, color="#777", linewidth=.7, linestyle=":")
        ax.grid(alpha=.2)
    fig.suptitle(f"Small-signal illustration: |S|={a.loop_gain:g} assumed, no CDR tracking; not measured closed-loop jitter", fontsize=10)
    fig_path = ROOT / "docs/figures/clocking/pll/core/pll_ripple_scale.png"
    fig.savefig(fig_path, dpi=170)
    plt.close(fig)
    (ROOT / "results/catalog/pll_ripple_budget.json").write_text(json.dumps(dict(
        data="docs/data/pll_ripple_budget.json", analysis=str((out / "summary.json").relative_to(ROOT)),
        figure=str(fig_path.relative_to(ROOT)), status="unit_and_budget_audit; no specification change; not simulation qualification"), indent=2) + "\n")
    for r in rows["current_12_6"]:
        print(f"{r['voltage_pp_v'] * 1e3:g} mVpp -> {r['jitter_pp_s'] * 1e12:.3f} pspp, {r['jitter_pp_ui']:.4f} UIpp per clock")
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
