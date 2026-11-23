"""Plan HV-to-1.8 V versus LV-to-1.5 V supply variants without simulation.

Reuses existing measured same-code roots and one fixed nominal waveform.
All 1.5 V extensions, regulator performance and power envelopes are ungraded.
"""
import hashlib
import importlib.util
import json
import math
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT

CONFIG = ROOT / "config/pll_supply_variants.toml"
STATIC = ROOT / "docs/data/vco_control_windows.json"
NOMINAL = ROOT / "results/analog/pll/vco/phase_noise_isf_4b/20261109T140720.206962Z_be7f42ae/freq_1195000000"


def identity(path):
    path = Path(path)
    return dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def load_roots():
    data = json.loads(STATIC.read_text())["analysis"]
    inputs = [identity(STATIC)]
    for prefix in ("source", "fill"):
        path = ROOT / data[prefix + "_path"]
        record = identity(path)
        if record["sha256"] != data[prefix + "_sha256"]:
            raise ValueError(f"VCO input identity changed: {path}")
        inputs.append(record)
    path = ROOT / "verification/analysis/vco_control_windows.py"
    spec = importlib.util.spec_from_file_location("supply_arch_windows", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    repeated = module.analyse(json.loads((ROOT / data["source_path"]).read_text()), json.loads((ROOT / data["fill_path"]).read_text()),
                              data["source_sha256"], data["fill_sha256"], data["source_path"], data["fill_path"])
    if repeated["conditions"] != data["conditions"]:
        raise ValueError("Measured-root publication does not match source/fill")
    inputs.append(identity(path))
    roots = {}
    for key, r in data["conditions"].items():
        for code, curve in r["curves"].items():
            values = curve["crossings"]
            if len(values) == 1 and values[0]["kvco_hz_per_v"] > 0:
                roots[(key, int(code))] = values[0]
    return roots, inputs


def nominal_nodes():
    raw, deck, execution = (NOMINAL / x for x in ("frequency.raw", "tb.cir", "execution.json"))
    e = json.loads(execution.read_text())
    if e["exit_code"] != 0 or e["timed_out"] or e["log_failures"] or identity(deck)["sha256"] != e["deck_sha256"]:
        raise ValueError("Nominal waveform execution/deck identity invalid")
    w = spice.Waves(raw)
    if abs(w.t[-1] - 24e-9) > 1e-15:
        raise ValueError("Nominal waveform truncated")
    sel = w.t >= 19e-9
    t = w.t[sel]
    def stats(values):
        return dict(min_v=float(values.min()), max_v=float(values.max()),
                    time_mean_v=float(np.trapezoid(values, t) / (t[-1] - t[0])))
    cm = (w["v(v0p)"][sel] + w["v(v0n)"][sel]) / 2
    tail = w["v(xvco.x0.tail)"][sel]
    return dict(condition="TT 1.8 V 27 C, Rtt, K6, Vctrl=1.195 V, real bias, four buffers/30 fF per leg",
                common_mode=stats(cm), tail=stats(tail),
                hypothetical_rigid_0_3v_shift_tail_min_v=float(tail.min() - .3),
                limit="Rigid node shift is a headroom illustration; not a 1.5 V operating point or VDS-VDSAT check",
                inputs=[identity(raw), identity(deck), identity(execution)])


def main():
    cfg = tomllib.loads(CONFIG.read_text())
    roots, inputs = load_roots()
    inputs += [identity(CONFIG), identity(Path(__file__).resolve()), identity(ROOT / "src/serdes_flow/spice.py"),
               identity(ROOT / "analog/pll/vco/spice/vco_ring4_4b.spice"),
               identity(ROOT / "analog/common/cml_buffer/spice/cml_buffer.spice"),
               identity(ROOT / "analog/bias/spice/bias_dist.spice")]
    power = []
    for name, v in cfg["variants"].items():
        for current in cfg["planning"]["load_currents_ma"]:
            # mA * V = mW. No assumption that this is measured domain current.
            power.append(dict(variant=name, assumed_current_ma=current,
                              input_power_mw=v["vin_nominal_v"] * current,
                              load_power_mw=v["vout_nominal_v"] * current,
                              pass_loss_mw=(v["vin_nominal_v"] - v["vout_nominal_v"]) * current,
                              efficiency=v["vout_nominal_v"] / v["vin_nominal_v"]))
    headroom = {name: dict(nominal_v=v["vin_nominal_v"] - v["vout_nominal_v"],
                          min_dc_v=v["vin_min_v"] - v["vout_nominal_v"] * (1 + v["vout_tolerance_fraction"]),
                          min_with_tone_v=v["vin_min_v"] - v["vout_nominal_v"] * (1 + v["vout_tolerance_fraction"])
                                          - cfg["planning"]["example_input_tone_mvpp"] / 2000)
                for name, v in cfg["variants"].items() if name != "bypass18"}
    for r in headroom.values():
        r["necessary_pass_ron_ceiling_ohm"] = {
            str(i): r["min_with_tone_v"] / (i * 1e-3) for i in cfg["planning"]["load_currents_ma"]}
    low = cfg["vco_projection"]
    bands = {str(v): dict(cp_upper_proxy_v=v-low["cp_headroom_proxy_v"], h4_upper_proxy_v=v-low["monitor_upper_drop_proxy_v"],
                         window_width_with_old_lower_v=v-low["monitor_upper_drop_proxy_v"]-low["current_lower_threshold_v"])
             for v in (1.8, 1.65, 1.5)}
    projections = []
    # Directly paired roots only; no borrowed neighbouring-code derivative.
    for (key, code), r in sorted(roots.items()):
        if "_v1650_" not in key:
            continue
        other = key.replace("_v1650_", "_v1800_")
        if (other, code) not in roots:
            continue
        high = roots[(other, code)]
        slope = (high["v"] - r["v"]) / .15
        estimate = r["v"] - .15 * slope
        projections.append(dict(condition_at_1v65=key, code=code, observed_1v65=r, observed_1v80=high,
                                supply_secant_v_per_v=slope, hypothetical_1v50_root_v=estimate,
                                status="out_of_measured_supply_range; no frequency/gain/swing/noise guarantee"))
    wanted = [("tt_v1650_t27:tt", 6), ("fs_v1650_t85:hh", 1), ("sf_v1650_t-40:ll", 15)]
    examples = [p for p in projections if (p["condition_at_1v65"], p["code"]) in wanted]
    missing = [dict(condition_at_1v65=key, code=k) for key, k in wanted
               if not any(p["condition_at_1v65"] == key and p["code"] == k for p in examples)]
    transient = [dict(step_ma=i, unserved_step_ns=cfg["planning"]["unserved_step_ns"],
                      allowed_droop_mv=cfg["planning"]["example_output_droop_mv"],
                      required_cap_pf=i * cfg["planning"]["unserved_step_ns"] / cfg["planning"]["example_output_droop_mv"] * 1000)
                 for i in cfg["planning"]["transient_step_ma"]]
    for r in transient:
        r["area_proxy_mm2"] = r["required_cap_pf"] * cfg["planning"]["cap_area_mm2_per_pf"]
    target = cfg["planning"]["example_local_tone_target_mvpp"]
    psrr = [dict(input_mvpp=x, output_target_mvpp=target, required_attenuation_db=20*math.log10(x/target))
            for x in cfg["planning"]["input_tones_mvpp"]]
    nodes = nominal_nodes()
    data = dict(status="planning_only_no_new_simulation", configuration=cfg, inputs=inputs, power=power,
                headroom=headroom, bands=bands, projections=projections, examples=examples, missing_examples=missing,
                nominal_existing_nodes=nodes, transient_charge_bound=transient, psrr_examples=psrr,
                static_current_input_power_ratio_lv15_vs_direct18=1.0,
                dynamic_capacitive_input_power_ratio_lv15_vs_direct18=cfg["variants"]["lv15"]["vout_nominal_v"] / cfg["variants"]["lv15"]["vin_nominal_v"],
                limitations=["No LDO circuit, transistor sizing, output capacitance, PSRR or stability is qualified",
                             "4/6/10 mA are load budgets; Iq, startup and reverse-blocking losses excluded",
                             "1.5 V CP upper edge, monitor window and VCO roots are planning proxies outside the measured supply range",
                             "Charge-bound C values assume the regulator supplies none of the additional current for the stated delay; not selected Cout",
                             "VCO current can stay similar at lower voltage, but full PVT headroom, cap-bank switch loss and noise remain unknown"])
    data["bands_scope"] = "CP/monitor upper proxies apply only if CP/monitor rails are also lowered; not lv15_core with CP retained at 1.8 V"
    out = ROOT / "results/verification/pll_supply_architectures" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True)
    (out / "runner.py").write_bytes(Path(__file__).read_bytes())
    (out / "summary.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    (ROOT / "docs/data/pll_supply_architectures.json").write_text(json.dumps(dict(data, analysis=str((out / "summary.json").relative_to(ROOT))), indent=2, allow_nan=False) + "\n")
    publish(data)
    (ROOT / "results/catalog/pll_supply_architectures.json").write_text(json.dumps(dict(
        status=data["status"], data="docs/data/pll_supply_architectures.json", config=str(CONFIG.relative_to(ROOT)),
        analysis=str((out / "summary.json").relative_to(ROOT)),
        figure="docs/figures/clocking/pll/core/pll_supply_architectures.png",
        diagram="docs/figures/clocking/pll/core/pll_supply_variants.png",
        design="docs/design/pll_supply_variants.md"), indent=2) + "\n")
    print("Headroom", json.dumps(headroom))
    print("Same-code paired roots", len(projections), "examples", [(p["condition_at_1v65"], p["code"], p["hypothetical_1v50_root_v"]) for p in examples])
    print("Existing TT tail min", nodes["tail"]["min_v"], "rigid-shift proxy", nodes["hypothetical_rigid_0_3v_shift_tail_min_v"])
    print(out.relative_to(ROOT))


def publish(data):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.6), layout="constrained")
    colors = {"hv18": "#b26e42", "bypass18": "#6b8191", "lv15": "#187e86"}
    currents = np.array(data["configuration"]["planning"]["load_currents_ma"])
    for name, label in [("hv18", "3.3 -> 1.8 V"), ("lv15", "1.8 -> 1.5 V")]:
        rows = [p for p in data["power"] if p["variant"] == name]
        axes[0].plot(currents, [r["pass_loss_mw"] for r in rows], marker="o", color=colors[name], label=label)
    axes[0].set(xlabel="Assumed regulated load (mA)", ylabel="Pass-device dissipation (mW)", title="Same-current comparison; Iq excluded")
    axes[0].legend(frameon=False, fontsize=9)
    x = np.arange(2)
    for dx, field, label in [(-.17, "nominal_v", "Nominal"), (.17, "min_with_tone_v", "Low input, +2% output, 20 mVpp tone")]:
        axes[1].bar(x+dx, [data["headroom"][name][field] for name in ("hv18", "lv15")], width=.32, label=label)
    axes[1].set_xticks(x, ["3.3 -> 1.8 V", "1.8 -> 1.5 V"])
    axes[1].set(ylabel="Available regulator headroom (V)", title="Headroom is not a PSRR guarantee")
    axes[1].legend(frameon=False, fontsize=8)
    for p in data["examples"]:
        label = p["condition_at_1v65"].replace("_v1650", "") + f" K{p['code']}"
        line, = axes[2].plot([1.65, 1.8], [p["observed_1v65"]["v"], p["observed_1v80"]["v"]], marker="o", label=label)
        axes[2].plot([1.5, 1.65], [p["hypothetical_1v50_root_v"], p["observed_1v65"]["v"]], linestyle="--", color=line.get_color())
        axes[2].scatter(1.5, p["hypothetical_1v50_root_v"], facecolors="none", edgecolors=line.get_color())
    axes[2].plot([1.5, 1.8], [1.5-.44, 1.8-.44], color="#777", linestyle=":", label="VDD - 0.44 V proxy")
    axes[2].set(xlabel="VCO local supply (V)", ylabel="2 GHz control voltage (V)", title="Solid: measured brackets\nDashed: unverified 1.5 V extension")
    axes[2].legend(frameon=False, fontsize=7)
    for ax in axes:
        ax.grid(alpha=.2)
        ax.title.set_fontsize(10)
    fig.suptitle("Supply VAR planning: existing data + arithmetic only, no new circuit simulation", fontsize=11)
    fig.savefig(ROOT / "docs/figures/clocking/pll/core/pll_supply_architectures.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    main()
