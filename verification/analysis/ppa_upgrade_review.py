"""Recompute the 4 Gb/s power/area and 5 Gb/s oscillator comparisons from existing results."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from serdes_flow import pnoise, spice, waves
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results"
VCO4 = RESULTS / "analog/pll/vco/r6_ptat_perf_20261123"
VCO5 = RESULTS / "analog/pll/vco_5g"
TT = "tt_v1800_t27:tt"
INTEGRATION = RESULTS / "verification/project_review/20261124/mixed_signal_link.json"
POWER_RAW = RESULTS / "verification/top_cosim_4g_20261123/singledeck_tt/run.r3/full_chain.raw"
R6_MAP = RESULTS / "analog/pll/vco/r6_ptat/map_p67_28_66/table.json"
LOOP4 = VCO4 / "stage6_synth/summary.json"
NOISE4 = VCO4 / "stage5_noise/summary.json"
LOOP5 = VCO5 / "shootout_20261123/stage6_synth/summary.json"
LOCK5 = VCO5 / "shootout_20261123/stage2_lock/summary.json"
LOOP_A_PLUS = VCO5 / "aplus_lcpll_20261123/ap_stage6_synth/summary.json"
LOCK_A_PLUS = VCO5 / "aplus_lcpll_20261123/ap_stage2_lock/summary.json"
CHANNEL = ROOT / "verification/models/channel/pcb_family/C2_loss6.s4p"
DECK_PFD_DUTY = {
    TT: 0.122, "ss_v1650_t85:hh": 0.180, "sf_v1650_t85:hh": 0.145,
    "fs_v1650_t85:hh": 0.138, "ff_v1950_t-40:ll": 0.077,
}


def load(path):
    return json.loads(path.read_text())


def rail_power():
    receipt = load(INTEGRATION)["singledeck_tt"]
    pll = receipt["pll_dyn"]
    rails = {
        "vin": (3.3, pll["p_pll_ldo_mw"]),
        "vdd_pll": (1.8, pll["p_pll_host_mw"]),
        "vdd_clk": (1.8, pll["p_clk_mw"]),
        "vdd_tx": (1.8, pll["p_tx_mw"]),
        "vdd_ctle": (1.8, receipt["p_ctle_mw"]),
        "vdd_pi": (1.8, receipt["p_pi_mw"]),
        "vdd_slicer": (1.8, receipt["p_slicer_mw"]),
        "vdd_deser": (1.8, receipt["p_deser_mw"]),
    }
    wave = spice.Waves(POWER_RAW)
    window_ns = (45.0, 75.0)
    mask = waves.window(wave.t, *(v * 1e-9 for v in window_ns))
    power = {}
    for rail, (voltage, expected) in rails.items():
        power[rail] = -voltage * 1e3 * waves.time_average(wave[f"i({rail})"][mask], wave.t[mask])
        if not np.isclose(power[rail], expected, rtol=1e-11):
            raise ValueError(f"Rail power changed: {rail}")
    total = sum(power.values())
    clock_power = power["vin"] + power["vdd_pll"] + power["vdd_clk"]
    return dict(window_ns=window_ns, rails_mw=power, analog_input_mw=total,
                pj_per_raw_bit=total / 4, pll_and_clock_fraction=clock_power / total)


def floorplan(path):
    layout = load(path)
    plan = layout["floorplan_kpi"]
    die = plan["die_core"]["area_um2"]
    return dict(core_um2=die, packing=plan["packing"],
                macros=[{k: m[k] for k in ("inst", "cell", "area_um2", "placed_rect_um")}
                        for m in sorted(plan["macros"], key=lambda m: -m["area_um2"])],
                clock_and_bias_manhattan_um={k: v for k, v in plan["critical_routes_manhattan_um"].items()
                                             if k != "tx_to_rx_hs_pad_separation_um"})


def differential_channel_loss():
    with CHANNEL.open() as stream:
        assert next(line for line in stream if line.startswith("#")).split() == ["#", "Hz", "S", "RI", "R", "50"]
        numeric = [line.split("!", 1)[0] for line in stream]
    rows = np.fromstring(" ".join(numeric), sep=" ").reshape(-1, 33)
    # Touchstone publishes by incident port, with the response port varying fastest.
    pairs = rows[:, 1:].reshape(-1, 4, 4, 2)
    transfer = pairs[..., 0] + 1j * pairs[..., 1]
    sdd21 = (transfer[:, 0, 2] - transfer[:, 1, 2] - transfer[:, 0, 3] + transfer[:, 1, 3]) / 2
    loss = -20 * np.log10(np.abs(sdd21))
    return {f"{f:g}_ghz": float(np.interp(f * 1e9, rows[:, 0], loss)) for f in (2.0, 2.5)}


def ring4_noise_budget():
    output = {}
    for condition, row in load(LOOP4).items():
        terms = row["jitter_v4"]["j_10k_100m_ps"]
        floor = sum(terms[k] ** 2 for k in terms if k not in ("total", "VCO")) ** 0.5
        permitted = max(0.0, 1 - floor ** 2) ** 0.5
        output[condition] = dict(
            terms_ps=terms, ideal_vco_floor_ps=floor,
            vco_variance_fraction=(terms["VCO"] / terms["total"]) ** 2,
            vco_allowance_for_1ps=permitted,
            required_vco_psd_reduction_db=20 * np.log10(terms["VCO"] / permitted) if permitted else None,
        )
    return output


def fixed_loops(spectra, lock, cf_pf, budgets_pf):
    """Screen one Rz/Ci across the five corners, keeping UGB below fref/10."""
    cp_noise = load(NOISE4)
    f = np.logspace(4, 8, 801)
    inputs = {}
    for key, row in spectra.items():
        source = "ss_v1650_t-40:hh" if key == "ss_v1650_t85:hh" else key
        cp = cp_noise[source]["cp_v4"]
        cp_psd = np.exp(np.interp(np.log(f), np.log(cp["f"]), np.log(np.maximum(cp["s_i"], 1e-35))))
        vco = np.exp(np.interp(np.log(f), np.log(row["offsets"]), np.log(row["L_total"])))
        temp = Condition.parse(key.split(":")[0]).temp + 273.15
        inputs[key] = (abs(lock[key]["kvco_hz_v"]), row["f0_hz"], temp, vco,
                       pnoise.cp_sampled_psd(f, cp_psd, DECK_PFD_DUTY[key]))

    outcome = {}
    rz_options = np.geomspace(150, 100e3, 61)
    for max_ci in budgets_pf:
        candidates = []
        for ci_pf in np.linspace(10.0, max_ci, 15):
            for rz in rz_options:
                rows = {}
                for key, (kvco, f0, temp, vco, cp) in inputs.items():
                    loop = pnoise.Loop(icp=200e-6, rz=rz, ci=ci_pf * 1e-12,
                                       cf=cf_pf * 1e-12, n=10, kvco=kvco)
                    ugb, phase = loop.unity_gain()
                    # Above fref/10 the delayed linear PFD model is not a design screen.
                    # Reject phase angles that wrapped through -180 degrees as well.
                    if not (1e4 < ugb <= 25e6 and 50.0 <= phase <= 90.0):
                        break
                    total = pnoise.synthesize(f, loop, vco, -123.1, cp, t=temp)["total"]
                    rows[key] = dict(jitter_ps=pnoise.rms_jitter(f, total, f0) * 1e12,
                                     pm_deg=phase, ugb_mhz=ugb / 1e6)
                if len(rows) == len(inputs):
                    worst = max(rows[k]["jitter_ps"] for k in rows)
                    candidates.append(dict(worst_ps=worst, rz_ohm=rz, ci_pf=ci_pf, rows=rows))
        outcome[max_ci] = min(candidates, key=lambda row: row["worst_ps"], default=None)
    return outcome


def run(output, assembly):
    r6 = {k: 2.0 * (1.0 + row["slow_margin"]) for k, row in load(R6_MAP)["rows"].items()}
    shots = load(LOOP5)
    a_plus = load(LOOP_A_PLUS)
    lock = load(LOCK5)
    inputs = [INTEGRATION, POWER_RAW, R6_MAP, LOOP4, NOISE4, LOOP5, LOCK5,
              LOOP_A_PLUS, LOCK_A_PLUS, CHANNEL, assembly]
    report = dict(
        inputs_sha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
        power=rail_power(),
        area=floorplan(assembly),
        channel_diff_insertion_loss_db=differential_channel_loss(),
        ring_4g_budget=ring4_noise_budget(),
        r6_tuning_max_ghz=r6,
        five_g_model_corner_optima={
            name: {k: row["pll"] for k, row in spectrum.items()}
            for name, spectrum in dict(A=shots["A"], C=shots["C"], A_plus=a_plus).items()
        },
        five_g_fixed_loop_constraints=dict(icp_ua=200, ref_mhz=250, n=10,
                                           max_ugb_mhz=25, min_pm_deg=50),
        five_g_fixed_loop={
            "A_plus": fixed_loops(a_plus, load(LOCK_A_PLUS), 0.5, (20, 60, 120, 420)),
            "C": fixed_loops(shots["C"], lock["C"], 0.4, (20, 60, 120, 420)),
            "A_plus_cf_1pf": fixed_loops(a_plus, load(LOCK_A_PLUS), 1.0, (60, 120, 420)),
            "C_cf_0p9pf": fixed_loops(shots["C"], lock["C"], 0.9, (20, 60)),
        },
    )
    with output.open("x") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--assembly", type=Path, required=True)
    args = parser.parse_args()
    run(args.output.resolve(), args.assembly.resolve())
