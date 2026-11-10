"""Compare loop re-selection alternatives without changing or simulating a DUT.

Reuses the existing loop and supply models; audits the two explicitly selected
single-tone campaigns from their raw data. Their calibration and noise-model
limits are retained. Results go into a new append-only analysis directory.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from serdes_flow import pnoise, spice
from serdes_flow.project import ROOT

SEARCH = "results/analog/pll/top/loop_psrr/20261110T014436Z/summary.json"
MEASURED = {
    "k4_h13": "results/analog/pll/vco/psrr_lf/20261109T192257Z/summary.json",
    "k8": "results/analog/pll/vco/psrr_lf/20261110T011752Z/summary.json",
}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def identity(path):
    path = Path(path)
    if not path.is_absolute():
        path = ROOT / path
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return {"path": str(path.relative_to(ROOT)), "sha256": h.hexdigest()}


def audit_tones(path, tone):
    """Check execution, deck, exact stop time and independently remeasure K."""
    path = ROOT / path
    doc = json.loads(path.read_text())
    rows = []
    for key, published in sorted(doc["rows"].items()):
        cond, rc, variant = key.split(":")
        matches = []
        for raw in (path.parent / f"{cond}_{rc}").glob(f"{variant}*/tone.raw"):
            run = raw.parent
            ex_path, deck_path = run / "execution.json", run / "tb.cir"
            ex = json.loads(ex_path.read_text())
            if ex.get("exit_code") != 0 or ex.get("timed_out"):
                continue
            deck = deck_path.read_text()
            if identity(deck_path)["sha256"] != ex["deck_sha256"]:
                raise ValueError(f"Deck identity changed: {run}")
            stop = float(re.search(r"(?im)^tran\s+\S+\s+(\S+)", deck)[1])
            waves = spice.Waves(raw)
            if abs(waves.t[-1] - stop) > 1e-15:
                raise ValueError(f"Truncated raw: {run}")
            for vector in ("v(v0p)", "v(v0n)", "v(ctrl)", "v(z)"):
                if vector not in waves:
                    raise ValueError(f"Missing {vector}: {run}")
            q = tone.fit(run, ex["fm"], 12e-9)
            gain = 2 * np.pi * ex["fm"] * q["f0"] * (q["cos"] - 1j * q["sin"]) / ex["amp"]
            if q["periods"] != doc["args"]["periods"]:
                raise ValueError(f"Incomplete tone fit: {run}")
            if not math.isclose(abs(gain), published["k_abs"], rel_tol=1e-10):
                raise ValueError(f"Published K disagrees with raw: {run}")
            if ex["point"] != f"{cond}:{rc}" or ex["lf_cell"] != doc["args"]["lf_cell"]:
                raise ValueError(f"Different plan point: {run}")
            matches.append(dict(key=key, k_abs_hz_per_v=abs(gain), stop_s=stop,
                                frequency_hz=q["f0"], code=published["code"], vctrl_v=published["vctrl"],
                                raw=identity(raw), deck=identity(deck_path), execution=identity(ex_path),
                                pdk_installation_id=ex.get("pdk_installation_id"),
                                log_failures=ex.get("log_failures", []),
                                status="ungraded_numerical_warning" if ex.get("log_failures") else "complete_clean_execution"))
        if len(matches) != 1:
            raise ValueError(f"Need one unambiguous completed waveform: {key}, got {len(matches)}")
        rows.append(matches[0])
    wanted = {f"{point}:lf_20M" for point in doc["args"]["points"].split(",")}
    return dict(summary=identity(path), rows=rows, planned=len(wanted), observed=len(rows),
                missing=sorted(wanted - {r["key"] for r in rows}),
                above_gate=[r["key"] for r in rows if r["k_abs_hz_per_v"] > 150e6],
                max_hz_per_v=max(r["k_abs_hz_per_v"] for r in rows),
                provenance_limit="Original execution inputs_sha256 is empty; raw/deck hashes verified now, not historical include-file provenance")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--search-summary", default=SEARCH)
    ap.add_argument("--cdr-ticks", type=int, default=0, help="0 skips CDR; otherwise a power of 2")
    ap.add_argument("--cdr-candidates", default="k4_retuned,k8")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    if a.cdr_ticks and (a.cdr_ticks < 1024 or a.cdr_ticks & (a.cdr_ticks - 1)):
        ap.error("CDR ticks must be a power of two >= 1024")
    ld = module("choice_loop_design", "analog/pll/top/theory/loop_design.py")
    ss = module("choice_supply_split", "analog/pll/top/theory/supply_split.py")
    tone = module("choice_tone", "analog/pll/vco/tb/phase_noise/psrr_tone.py")
    cdr = module("choice_cdr", "analog/pll/top/theory/cdr_jitter.py")
    search = json.loads((ROOT / a.search_summary).read_text())
    inputs = {a.search_summary, str(ld.LFDATA.relative_to(ROOT)), ld.WORKMAP + "/summary.json", ld.CPWIN + "/summary.json"}
    args = search["args"]
    others = []
    for spec in args["other"].split(","):
        campaign, alpha = spec.rsplit(":", 1)
        inputs.add(campaign + "/summary.json")
        others.append((json.loads((ROOT / campaign / "summary.json").read_text())["rows"], float(alpha)))
    inputs.update(c + "/summary.json" for c in args["base"].split(","))
    inputs.add(args["ctrl_load"] + "/summary.json")
    fits = ss.fit(ss.rows(args["base"]), others, args["freq"])
    r4 = search["result"]["4"]["smallest"][0]
    r6 = search["result"]["6"]["smallest"][1]
    candidates = [
        ("k4_current", 4, 4130., 18.38e-12, 0., 24 / 36),
        ("k4_h13", 4, 4130., 18.38e-12, 0., 23 / 36),
        ("k4_retuned", 4, r4["rz"], r4["ci"], r4["dc"], 47 / 72),
        ("k6_retuned", 6, r6["rz"], r6["ci"], r6["dc"], 48 / 72),
        ("k8", 8, 2170., 33e-12, 0., 22 / 33),
        ("k8_cf100", 8, 2170., 33e-12, 100e-15, 22 / 33),
    ]
    result = []
    freq = np.logspace(5, np.log10(3e8), 640)
    for name, k, rz, ci, cf, alpha in candidates:
        cload = ld.CtrlLoad(args["ctrl_load"], args["c_extra"] + args["c_cp_per_k"] * (k - 4))
        stability = []
        for vlo, headroom in [(1., .39), (.9, .39), (.9, .44)]:
            p = ld.plants(ld.WORKMAP, ld.CPWIN, vlo, headroom, cload)
            u, pm = ld.margins(p, k, rz, ci, cf, args["delay"], freq)
            worst = p["label"][int(pm.argmin())]
            condition, _, code, _, _ = worst.split()
            wm = json.loads((ROOT / ld.WORKMAP / "summary.json").read_text())
            root = ld.crossing(wm["vs"], wm["rows"][condition]["f"][code])
            stability.append(dict(vlo_v=vlo, headroom_v=headroom, plants=len(pm),
                                  conditions=len({label.split()[0] for label in p["label"]}),
                                  kvco_min_hz_per_v=float(p["kvco"].min()),
                                  pm_min_deg=float(pm.min()), worst=worst, worst_vctrl_quad_v=root[0],
                                  pm_min_delay_plus_0_5ns_deg=float((pm - 360 * u * .5e-9).min()),
                                  ugb_hz=[float(u.min()), float(u.max())]))
        delta = args["c_cp_per_k"] * (k - 4)
        gains = {label: float(abs(v["kg"] + ss.transfer(args["freq"], alpha, v["cp"] + delta,
                 v["cpv"] + delta / 2, v["rz"] * rz / ss.RZ, v["ci"] * ci / ss.CI, cf) * v["kl"]))
                 for label, v in fits.items()}
        noise = ld.noise_inputs(args["floor"], cload)
        rms = ld.jitter(noise, k, rz, ci, cf, args["delay"])
        residuals = {}
        if a.cdr_ticks and name in a.cdr_candidates.split(","):
            for label, d in noise.items():
                lp = pnoise.Loop(icp=ld.ICP0 * k, rz=rz, ci=ci, cf=cf + d["cctrl"], kvco=d["kvco"], n=8, delay=args["delay"])
                l = pnoise.synthesize(d["f"], lp, d["l_vco"], d["floor"], d["cp"] * k, l_bias=d["l_bias"])["total"]
                rng = np.random.default_rng(a.seed)
                ti = cdr.phase_series(rng, d["f"], l, d["f0"], a.cdr_ticks) - cdr.phase_series(rng, d["f"], l, d["f0"], a.cdr_ticks)
                e = cdr.run(ti, rng, 9e-12, 4)[a.cdr_ticks // 16:]
                hi = d["f"] > 125e6
                variance_hi = 2 * np.trapezoid(2 * l[hi], d["f"][hi]) / (2 * np.pi * d["f0"]) ** 2
                residuals[label] = float(14.07 * np.sqrt(e.var() + variance_hi) / cdr.UI)
        row = dict(name=name, k=k, icp_a=ld.ICP0 * k, rz_ohm=rz, ci_f=ci, cf_f=cf, alpha=alpha,
                   supply_19_points_hz_per_v=gains, supply_max_hz_per_v=max(gains.values()),
                   stability=stability, pll_rms_s=rms, cdr_14_07_sigma_ui=residuals,
                   delta_mim_mm2=(ci + cf - 18.38e-12) * 1e12 * .00087,
                   delta_nominal_cp_branch_power_w=(k - 4) * ld.ICP0 * 1.8)
        result.append(row)
        print(name, "|K|", round(max(gains.values()) / 1e6, 2), "PM bands", [round(s["pm_min_deg"], 2) for s in stability],
              "rms ps", round(max(rms.values()) * 1e12, 3), "CDR", [round(x, 4) for x in residuals.values()], flush=True)
    for name in ld.NOISE_POINTS:
        path = ld.CORNERS / name / "state.json"
        inputs.add(str(path.relative_to(ROOT)))
        state = json.loads(path.read_text())
        inputs.update((state["isf"] + "/phase_noise.json", state["cp"] + "/summary.json", state["bias"] + "/summary.json"))
    scripts = [Path(__file__).relative_to(ROOT), "analog/pll/top/theory/loop_design.py", "analog/pll/top/theory/supply_split.py",
               "analog/pll/top/theory/cdr_jitter.py", "analog/pll/vco/tb/phase_noise/psrr_tone.py", "src/serdes_flow/pnoise.py", "src/serdes_flow/spice.py"]
    data = dict(args=vars(a), inputs=[identity(p) for p in sorted(inputs)], code=[identity(p) for p in scripts],
                candidates=result, measured={name: audit_tones(path, tone) for name, path in MEASURED.items()},
                limits=["Retuned k4/k6/Cf100 points are models only, not simulated circuits",
                        "Stability uses old three-point quadratic tuning fits and scaled old CP currents; neither window is a measured guarantee",
                        "Noise uses historical three-bit ISF/noise and CP duty/scaling assumptions; not current four-bit qualification",
                        "Supply fits cover 19 operating points at 20 MHz, not full 135 corners, codes or a locked sampled loop",
                        "MIM area coefficient is a prelayout estimate; CP branch-power delta excludes follower and drive changes"])
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out = ROOT / "results/verification/pll_supply_choice" / stamp
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    print(out.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
