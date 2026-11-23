"""Bounded design-review calculations and an optional VCO adjacent-code probe.

uv run python verification/design_coupling_review.py [--probe-vco]
Outputs are append-only. No DUT or acceptance threshold is changed.
"""
import argparse
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import time

from serdes_flow import pnoise, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT


STATES = [
    "sf_v1650_t85_rhh_v5", "fs_v1650_t85_rhh_v5", "fs_v1950_t85_rhh_v5b",
    "ss_v1650_t85_rhh_v5b", "ss_v1650_t-40_rhh_v5", "ff_v1950_t-40_rll_v5b",
    "tt_v1800_t27_rtt_v5b",
]


def calculations():
    rows = []
    for name in STATES:
        path = ROOT / "results/analog/pll/vco/phase_noise_corner" / name / "state.json"
        state = json.loads(path.read_text())
        base = pnoise.Loop(kvco=state["kvco"])
        for k in (2, 3, 4):
            loop = pnoise.scaled_loop(base, k)
            ugb, pm = loop.unity_gain()
            # The model already contains 2 ns PFD delay. Add only hypothetical *extra* path delay.
            _, pm_extra = replace(loop, delay=loop.delay + 0.5e-9).unity_gain()
            # Sensitivity envelope, not foundry-correlated corners: physical LF RC not yet integrated.
            rc_cases = []
            for rf in (0.875, 1, 1.125):
                for cf in (0.88, 1, 1.12):
                    candidate = replace(loop, rz=loop.rz * rf, ci=loop.ci * cf, cf=loop.cf * cf,
                                        icp=loop.icp / rf)
                    f, m = candidate.unity_gain()
                    rc_cases.append(dict(r_scale=rf, c_scale=cf, icp_scale=1 / rf, ugb_hz=f, pm_deg=m))
            rows.append(dict(source=str(path.relative_to(ROOT)), k=k, kvco=base.kvco,
                             ugb_hz=ugb, pm_deg=pm, pm_extra_0p5ns_deg=pm_extra,
                             rc_sensitivity=rc_cases))
    return dict(pll=rows, note="Linear sensitivities, not circuit qualification; existing 2 ns PFD delay retained. "
                "RC factors are illustrative; KVCO is held at each measured operating point.",
                cml_full_steering=dict(single_ended_pp_over_ir=1, differential_pp_over_ir=2,
                                      common_mode_drop_over_ir=0.5),
                startup=dict(wait_timeout_us=4096 / 250e6 * 1e6, measured_bias_max_us=16.3,
                             gap_if_same_origin_us=4096 / 250e6 * 1e6 - 16.3),
                cdr=dict(pi_step_ps=500 / 64, ppm300_step_interval_ns=(500e-12 / 64) / 300e-6 * 1e9,
                         ppm300_turn_interval_us=500e-12 / 300e-6 * 1e6),
                cap_bank=dict(old_max_units=7, proposed_half_unit_max_units=15 / 2,
                              maximum_capacitance_increase_fraction=(15 / 2) / 7 - 1))


def probe_vco(camp):
    path = ROOT / "analog/pll/vco/tb/tuning/range_real.py"
    spec = importlib.util.spec_from_file_location("range_real_review", path)
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    c = Condition("ff", 1.95, -40)
    # The current documented point uses code 7 at 1.475 V. Check code 6 in the B2 range
    # before interpreting this as a hard tuning-range failure.
    codes, volts = [6, 7], [1.05, 1.2, 1.35]
    pilot = rr.deck("ff", "ll", [c], [6], [1.2], camp, stop="24n", start="12n")
    ex = spice.run(pilot, camp / "pilot", timeout_s=300)
    if spice.case_output(camp, "pilot", f"{c.tag}_c6_v1200.raw", 24e-9) is None:
        raise RuntimeError(f"incomplete VCO pilot: {ex.run_dir}")
    deck = rr.deck("ff", "ll", [c], codes, volts, camp, stop="24n", start="12n")
    spice.run(deck, camp / "ff_ll", timeout_s=6 * 150)
    result = []
    for code in codes:
        for v in volts:
            name = f"{c.tag}_c{code}_v{round(v * 1000)}.raw"
            path = spice.case_output(camp, "ff_ll", name, 24e-9)
            if path is None:
                raise RuntimeError(f"incomplete VCO output: {name}")
            f, swing = rr.freq(path)
            result.append(dict(code=code, vctrl_v=v, frequency_hz=f, differential_pp_v=swing,
                               waveform=str(path.relative_to(ROOT))))
    return dict(condition=c.tag, passive_corner="ll", rows=result,
                note="Open loop current r5 DUT, real bias, PDK R, four buffers with 30 fF proxies; "
                     "24 ns, last half of 12..24 ns saved interval measured. No closed-loop/noise/MC claim.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe-vco", action="store_true")
    args = ap.parse_args()
    camp = ROOT / "results/verification/design_coupling_review" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=False)
    result = calculations()
    (camp / "calculations.json").write_text(json.dumps(result, indent=2))
    print(camp, flush=True)
    if args.probe_vco:
        result = probe_vco(camp)
        (camp / "vco_probe.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
