"""Publish the explicitly identified HV18 r4 results; never run a simulator.

Verify frozen sources, PDK, decks, executions and every cited output first.
The compact JSON retains coordinates and metric definitions; full evidence
stays in append-only campaigns. Figures distinguish measured local boundaries.
"""
import argparse
from functools import cache
import hashlib
import itertools
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project, spice

ROOT = project.ROOT
FIG = ROOT / "docs/figures/clocking/pll/core"
COLORS = dict(tt="#176c8c", ss="#7b5595", ff="#d27732", sf="#cf4951", fs="#388c70")


@cache
def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(path, expected):
    if sha(path) != expected:
        raise ValueError(f"Evidence changed: {path}")


def load(path):
    data = json.loads(path.read_text())
    if data.get("missing"):
        raise ValueError(f"Incomplete: {path}")
    campaign = ROOT / data["campaign"]
    check(campaign / "plan.json", data["plan_sha256"])
    plan = json.loads((campaign / "plan.json").read_text())
    for rel, h in plan["sources"].items():
        check(campaign / rel, h)
    for rel, h in plan["pdk_sha256"].items():
        check(Path(rel), h)
    entries = plan.get("entries")
    if entries is None:
        entries = [dict(deck="prepared/" + name + ".cir", deck_sha256=h) for name, h in plan["decks"].items()]
    for entry in entries:
        check(campaign / entry["deck"], entry["deck_sha256"])
    allowed_decks = {entry["deck_sha256"] for entry in entries}
    for row in data["rows"]:
        run = ROOT / row["run"]
        for name, h in row["evidence"].items():
            check(run / name, h)
        execution = json.loads((run / "execution.json").read_text())
        if execution["exit_code"] or execution["timed_out"] or execution["log_failures"]:
            raise ValueError(f"Failed execution: {run}")
        check(run / "tb.cir", execution["deck_sha256"])
        if execution["deck_sha256"] not in allowed_decks:
            raise ValueError(f"Unplanned deck: {run}")
        for name, h in execution["inputs_sha256"].items():
            check(run / name, h)
    return data, plan


def bounds(values):
    return [float(min(values)), float(max(values))]


def span(rows, key):
    return bounds([row[key] for row in rows])


def ac_curve(row, kind):
    a = np.loadtxt(ROOT / row["run"] / (row["stem"] + "_" + kind + ".tsv"), skiprows=1)
    return a[:, 0], np.hypot(a[:, 1], a[:, 2])


def grid_figure(data):
    grid = data["grid"]["rows"]
    ac = [r for r in grid if r["ac"]]
    tt = next(r for r in ac if (r["mos"], r["rc"], r["hv_v"], r["host_v"], r["temp_c"], r["load_ma"]) == ("tt", "tt", 3.3, 1.8, 27, 6))
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    ax, bx, cx, dx = axes.flat
    for mos, color in COLORS.items():
        rs = [r for r in grid if r["mos"] == mos]
        ax.scatter([r["load_ma"] + .3 * (r["hv_v"] - 3.3) for r in rs], [1000 * (r["vout_v"] - 1.8) for r in rs], s=8, alpha=.35, color=color, label=mos.upper())
    ax.axhline(-36, color="#a84c43", ls="--"); ax.axhline(36, color="#a84c43", ls="--")
    ax.set(title="1215 DC points; one fixed calibrated code per MOS/RC", xlabel="Load (mA)", ylabel="Output error (mV)", xticks=[2, 6, 10], ylim=(-40, 40))
    ax.legend(ncol=5, fontsize=8)
    for kind, a, ylabel in [("hv", bx, "HV input rejection (dB)"), ("host", cx, "Host to quiet gain (V/V)")]:
        curves = [ac_curve(r, kind)[1] for r in ac]
        hz, nominal = ac_curve(tt, kind)
        curves = np.array(curves)
        if kind == "hv":
            curves = -20 * np.log10(curves); nominal = -20 * np.log10(nominal)
            a.set_ylim(0, 105)
        else:
            a.set_yscale("log")
        a.fill_between(hz, curves.min(axis=0), curves.max(axis=0), color="#176c8c", alpha=.2, label="255 AC boundary points")
        a.semilogx(hz, nominal, color="#176c8c", label="TT / 3.3 V / host 1.8 V / 6 mA")
        a.axvline(20e6 if kind == "hv" else .3e6, ls=":", color="#777")
        a.set(xlim=(1e3, 2e8), xlabel="Frequency (Hz)", ylabel=ylabel, title="Real reference, physical passives, independent supplies")
        a.legend(fontsize=8)
    cal = data["calibration"]["rows"]
    for offset, color in [(-.09, "#388c70"), (0, "#176c8c"), (.09, "#cf4951")]:
        rs = sorted((r for r in cal if (r["mos"], r["rc"], r["offset_v"]) == ("tt", "tt", offset)), key=lambda r: r["trim"])
        dx.plot([r["trim"] for r in rs], [r["vout_v"] for r in rs], color=color, label=f"BG imposed error {offset * 1000:+.0f} mV")
        best = min(rs, key=lambda r: abs(r["vout_v"] - 1.8))
        dx.scatter(best["trim"], best["vout_v"], color=color)
    dx.axhline(1.8, color="#777", ls=":")
    dx.set(title="TT trim range: deterministic stresses, not MC", xlabel="6-bit code (1 shorts a segment)", ylabel="Output (V)")
    dx.legend(fontsize=8)
    for a in axes.flat: a.grid(alpha=.18)
    fig.suptitle("HV18 r4: static supply pins, reference RC, physical R/MIM and voltage trim", fontsize=13)
    fig.savefig(FIG / "ldo_r4_characterization.png", dpi=160); plt.close(fig)


def dynamic_figure(data):
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    ax, bx, cx, dx = axes.flat
    for row in data["startup"]["rows"]:
        if row["mode"] != "hv10": continue
        w = spice.Waves(ROOT / row["raw"])
        color = COLORS[row["mos"]]
        label = f"{row['mos'].upper()}/{row['rc']} {row['temp_c']} C"
        ax.plot(w.t * 1e6, w["out_v"], color=color, alpha=.8, label=label)
        bx.plot(w.t * 1e6, w["tail_v"], color=color, alpha=.8)
    ax.set(title="Actual BG cold start and enable cycle; 180 ohm load", xlabel="Time (us)", ylabel="Quiet (V)")
    ax.legend(fontsize=7, ncol=2)
    bx.set(title="1 Mohm / 16 pF tail filter; 1 pF gate surrogate", xlabel="Time (us)", ylabel="Tail-bias voltage (V)")
    for a in (ax, bx):
        a.axvspan(180, 200, color="#e6b85d", alpha=.17)
        a.set_xlim(0, 360)
    for row in data["noise"]["rows"]:
        if row["mode"] != "hv10": continue
        w = spice.Waves(ROOT / row["run"] / "hv10_noise.raw")
        cx.loglog(w.t, w["onoise_spectrum"] * 1e9, color=COLORS[row["mos"]], alpha=.8)
    cx.set(title="DC noise, 6 profiles; pass currents checked after noise", xlabel="Frequency (Hz)", ylabel="Quiet noise (nV/sqrt(Hz))")
    for key, style in [("bias_fast", "--"), ("bias_slow", "-")]:
        for row in data[key]["rows"]:
            a = np.loadtxt(ROOT / row["run"] / "ac.tsv", skiprows=1)
            ratio = np.hypot(a[:, 3], a[:, 4]) / np.hypot(a[:, 1], a[:, 2])
            # Do not advertise the model's >90dB high-frequency rejection;
            # wire feedthrough and extraction are absent.
            s = a[:, 0] <= 4e6
            dx.semilogx(a[s, 0], -20 * np.log10(ratio[s]), ls=style, color=COLORS[row["point"][:2]], label=("100k" if key == "bias_fast" else "1M") + " " + row["point"].split(":")[0])
    dx.set(title="Tail filter AC on actual VCO + 4 buffer gates", xlabel="Frequency (Hz)", ylabel="Attenuation vs original bias (dB)", xlim=(1e3, 4e6))
    dx.legend(fontsize=6, ncol=2)
    for a in axes.flat: a.grid(alpha=.18)
    fig.suptitle("HV18 r4 local dynamic/noise boundaries; no full PLL transient or jitter qualification", fontsize=12)
    fig.savefig(FIG / "ldo_r4_startup_noise_bias.png", dpi=160); plt.close(fig)


def cap_figure(data):
    fig, ax = plt.subplots(figsize=(8, 4.6), layout="constrained")
    for profile, color in [("nominal", "#176c8c"), ("weakest_pm", "#cf4951")]:
        rs = [r for r in data["cap_load"]["rows"] if r["profile"] == profile]
        ax.plot([max(r["extra_pf"], 1) for r in rs], [min(x["pm_deg"] for x in r["crossings"]) for r in rs], "o-", color=color, label=profile.replace("_", " "))
    ax.set_xscale("log")
    ax.set(xticks=[1, 10, 100, 1000, 10000, 100000], xticklabels=["0", "10", "100", "1k", "10k", "100k"], xlabel="ADDED quiet-pin capacitance (pF); on-chip 100 pF already present", ylabel="Dual-injection phase margin (deg)", title="Two boundaries only: arbitrary external decoupling is not qualified", ylim=(0, 90))
    ax.legend(); ax.grid(alpha=.2)
    fig.savefig(FIG / "ldo_r4_cap_load.png", dpi=160); plt.close(fig)


def main(manifest):
    config = json.loads(manifest.read_text())
    data = {}; plans = {}; inputs = {}
    for key, rel in config["inputs"].items():
        path = ROOT / rel
        if key == "resistor_noise":
            d = json.loads(path.read_text()); c = ROOT / d["campaign"]
            check(c / "run/execution.json", d["execution_sha256"])
            for name, row in d["rows"].items(): check(c / "run" / (name + ".raw"), row["raw_sha256"])
            check(c / "passives.spice", d["cell_sha256"])
            data[key] = d
        else:
            data[key], plans[key] = load(path)
        inputs[key] = dict(summary=rel, sha256=sha(path), campaign=data[key]["campaign"], rows=len(data[key]["rows"]))
    expected_counts = dict(calibration=1088, grid=1215, passives=27, startup=18, noise=18, bias_fast=3, bias_slow=3, cap_load=16)
    if any(len(data[k]["rows"]) != n for k, n in expected_counts.items()): raise ValueError("Unexpected result count")
    grid = data["grid"]["rows"]; ac = [r for r in grid if r["ac"]]
    coordinates = {(r["mos"], r["rc"], r["hv_v"], r["host_v"], r["temp_c"], r["load_ma"]) for r in grid}
    if coordinates != set(itertools.product(COLORS, ("ll", "tt", "hh"), (3., 3.3, 3.6), (1.65, 1.8, 1.95), (-40, 27, 85), (2, 6, 10))): raise ValueError("Grid coordinates differ")
    if len(ac) != 255 or any(len(r["crossings"]) != 1 or r["crossings"][0]["direction"] != "down" for r in ac): raise ValueError("Unexpected crossings")
    codes = data["calibration"]["calibration_codes"]
    cal_groups = itertools.groupby(sorted(data["calibration"]["rows"], key=lambda r: (r["mos"], r["rc"], r["offset_v"], r["trim"])), key=lambda r: (r["mos"], r["rc"], r["offset_v"]))
    for _, group in cal_groups:
        rs = list(group)
        if [r["trim"] for r in rs] != list(range(64)) or np.any(np.diff([r["vout_v"] for r in rs]) <= 0):
            raise ValueError("Calibration missing codes or nonmonotonic")
    if any(r["trim"] != codes[r["mos"] + ":" + r["rc"]]["trim"] for r in grid): raise ValueError("Retuned code inside grid")
    if any(not r.get("post_noise_pass_current_verified") for r in data["noise"]["rows"]): raise ValueError("Noise pass-current check missing")
    if any("output_noise_rms_uv" in r for r in data["startup"]["rows"]): raise ValueError("Uncertified startup noise must not be published")
    cells = plans["grid"]["cell_sha256"]
    for key in ("grid", "startup"):
        if plans[key]["calibration_sha256"] != inputs["calibration"]["sha256"]:
            raise ValueError("Different calibration parent")
    if plans["cap_load"]["grid_sha256"] != inputs["grid"]["sha256"]:
        raise ValueError("Different cap-load parent")
    check(ROOT / data["startup"]["campaign"] / "plan.json", plans["noise"]["startup_plan_sha256"])
    for rel, h in cells.items():
        check(ROOT / rel, h)
        if plans["calibration"]["cell_sha256"][rel] != h: raise ValueError("Calibration DUT differs")
        for key in ("startup", "noise", "cap_load"):
            check(ROOT / data[key]["campaign"] / "source" / rel, h)
    tail = ROOT / "analog/ldo/spice/pll_bias_filter_r4.spice"
    for key in ("startup", "noise"):
        check(ROOT / data[key]["campaign"] / "source" / tail.relative_to(ROOT), sha(tail))
    for key in ("bias_fast", "bias_slow"):
        passive = ROOT / "analog/ldo/spice/ldo_passives.spice"
        check(passive, plans[key]["originals"][str(passive)])
        check(ROOT / plans[key]["parent_summary"], plans[key]["parent_summary_sha256"])
    check(tail, plans["bias_slow"]["originals"][str(tail)])
    fallback_count = sum((ROOT / r / "simulator.log").read_text().count("Transient op started") for r in {x["run"] for x in grid})
    if fallback_count: raise ValueError("Grid AC bias needs explicit certification after transient OP fallback")
    stats = {key: span(grid, key) for key in ("vout_v", "vin_excess_ua", "host_power_mw")}
    stats.update({key: span(ac, key) for key in ("psrr_20mhz_db", "host_300khz_v_v", "host_1mhz_v_v", "host_20mhz_v_v")})
    stats["middlebrook_pm_deg"] = bounds([r["crossings"][0]["pm_deg"] for r in ac])
    stats["grid_transient_op_fallback_count"] = fallback_count
    stats["noise_rms_uv"] = {mode: span([r for r in data["noise"]["rows"] if r["mode"] == mode], "rms_uv") for mode in ("hv2", "hv10", "tail")}
    for mode in ("hv2", "hv10"):
        rs = [r for r in data["startup"]["rows"] if r["mode"] == mode]
        stats[mode + "_startup"] = {key: span(rs, key) for key in ("peak_v", "final_v", "off_floor_v", "final_pp_mv")}
    columns = ["mos", "rc", "hv_v", "host_v", "temp_c", "load_ma", "trim", "vout_v", "vin_excess_ua", "host_power_mw", "run", "stem"]
    compact = [[r[k] for k in columns] for r in grid]
    cal_tt = [{k: r[k] for k in ("trim", "offset_v", "vout_v")} for r in data["calibration"]["rows"] if (r["mos"], r["rc"]) == ("tt", "tt")]
    published = dict(revision=config["revision"], status="local_circuit_candidate_not_integrated", manifest=str(manifest.relative_to(ROOT)), manifest_sha256=sha(manifest), generator_sha256=sha(Path(__file__)), inputs=inputs, cell_sha256=cells, statistics=stats, calibration_codes=codes, calibration_tt_stress=cal_tt, grid_columns=columns, grid=compact, ac=[{k: v for k, v in r.items() if k != "evidence"} for r in ac], supplementary={k: data[k] for k in ("passives", "startup", "noise", "bias_fast", "bias_slow", "cap_load", "resistor_noise")}, exclusions=["No full PLL integration, supply-induced jitter or correlated reference/tail-noise synthesis", "Noise check certifies both pass currents, not all slow-node biases", "No complete HV/PNP mismatch model coverage or statistical yield", "Only two boundaries for added capacitance; no PEX/pad/package/board model", "No UVLO/quiet-ready controller or runtime supply-mode changes", "Startup uses resistive loads,12pF vgi distribution and1pF tail-gate surrogates"])
    output = ROOT / "docs/data/ldo_r4.json"
    output.write_text(json.dumps(published, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    catalog = dict(revision=config["revision"], status=published["status"], data=str(output.relative_to(ROOT)), data_sha256=sha(output), inputs=inputs, statistics=stats)
    (ROOT / "results/catalog/ldo_r4.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    FIG.mkdir(parents=True, exist_ok=True)
    grid_figure(data); dynamic_figure(data); cap_figure(data)
    print(json.dumps(dict(output=str(output.relative_to(ROOT)), statistics=stats, verified_evidence_files=sha.cache_info().currsize), indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=ROOT / "config/ldo_r4_evidence.json")
    main(ap.parse_args().manifest.resolve())
