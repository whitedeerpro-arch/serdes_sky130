"""Bounded convergence experiments on the r5 VCO and clock frontend.

uv run python analog/pll/top/tb/convergence/probe.py --levels ring,frontend --solvers klu,sparse

The ring boundary is four buffers with 30 fF per output. ``receivers`` adds
four r4 receivers with 20 fF per CMOS output; ``prescaler`` adds one native
prescaler with 5 fF per tap (other buffers retain 30 fF). The frontend uses
its four native receivers/prescalers and internal loads, without TX or CP/LF.
Seeds ``none`` and ``vco`` retain the historical asymmetric SR guesses;
``free`` omits those guesses. ``vco`` additionally seeds the VCO common mode.
Nodesets are initial Newton guesses, never forced transient initial states.
``--varactors stable`` tests an exact log(cosh) reformulation in a local
model copy; it changes neither the installed PDK nor the project DUT.
Each case first attempts a bounded 1 ns smoke. Resume checks waveform end
time, not process exit status. Failed attempts are retained separately.
"""
import argparse
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from serdes_flow import bias, boundary, clock, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/cmos_logic.spice",
    "analog/common/devices/spice/cmos_dff_reset.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice",
    "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r4.spice",
    "analog/pll/vco/spice/cap_bank_3b.spice",
    "analog/pll/vco/spice/cap_bank_4b.spice",
    "analog/pll/vco/spice/vco_ring4_4b.spice",
    "analog/pll/divider/spice/cml_latch.spice",
    "analog/pll/divider/spice/cml_div2.spice",
    "analog/pll/divider/spice/cml_prescaler8.spice",
    "analog/pll/top/spice/clock_frontend_r5.spice",
]


def preserve_identity(path, identity, prior_attempts=False):
    """Refuse stale resume inputs; never give legacy attempts a new identity."""
    if path.exists():
        if json.loads(path.read_text()) != identity:
            raise ValueError(f"inputs changed: {path}; use a new campaign")
    else:
        if prior_attempts:
            raise ValueError(f"old attempt has no input identity: {path}; use a new campaign")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(identity, indent=2) + "\n")


def circuit_identity():
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(set(INCLUDES + list(bias.BIAS_INC)))}


def registered_initial_state(bc_id, c, rc, workdir):
    entry = boundary.get(bc_id)
    if entry["kind"] != "initial_state_estimate" or entry["consumer_sources"] != circuit_identity():
        raise boundary.BoundaryMismatch("initial-state consumer changed; create and validate a new BC")
    point = entry["points"][f"{c.tag}:{rc}"]
    selected = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"][f"{c.tag}:{rc}"]
    if point["code"] != selected["code"] or point["vctrl_v"] != selected["vctrl"]:
        raise boundary.BoundaryMismatch("initial-state code/control changed")
    source = ROOT / point["initial_state_file"]
    if hashlib.sha256(source.read_bytes()).hexdigest() != point["initial_state_sha256"]:
        raise boundary.BoundaryMismatch("initial-state file changed")
    payload = json.loads(source.read_text())
    if payload["condition"] != c.tag or payload["passive"] != rc:
        raise boundary.BoundaryMismatch("initial-state PVT changed")
    (workdir / "operating_guesses.json").write_text(json.dumps(dict(payload, boundary_id=bc_id), indent=2) + "\n")
    return [f".ic v({node})={v:.12g}" for node, v in payload["values"].items()]


def stable_varactor(workdir):
    """Local test-only model copy: algebraic identity, original PDK untouched."""
    library = Path(spice.corner_values(Condition("tt", 1.8, 27))["MODEL_LIBRARY"])
    src = library.parents[2] / "libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_var_lvt.model.spice"
    original = src.read_text()
    text = original.replace("sky130_fd_pr__cap_var_lvt c0", "serdes_cap_var_lvt_stable c0").replace(
        ".ends sky130_fd_pr__cap_var_lvt", ".ends serdes_cap_var_lvt_stable")
    for k in (1, 2):
        x = f"(v(c0)-v(p2)-cnwvc_vt{k})/cnwvc_slope{k}"
        old = f"log(cosh({x}))"
        assert text.count(old) == 1
        text = text.replace(old, f"(abs({x})+log(1+exp(-2*abs({x})))-log(2))")
    assert "log(cosh(" not in text
    out = workdir / "cap_var_lvt_stable.spice"
    out.write_text("* Test-only exact log(cosh) reformulation; source SHA256 " + hashlib.sha256(original.encode()).hexdigest() + "\n" + text)
    vco = (ROOT / INCLUDES[10]).read_text()
    assert vco.count(" sky130_fd_pr__cap_var_lvt ") == 8
    vco = vco.replace(" sky130_fd_pr__cap_var_lvt ", " serdes_cap_var_lvt_stable ")
    (workdir / "vco_ring4_4b_stable.spice").write_text(vco)
    return out, workdir / "vco_ring4_4b_stable.spice"


def assembled_seed(source, c, rc, workdir, initial=False):
    """Compose same-condition module OP guesses; no forced initial state."""
    rows = json.loads((source / "summary.json").read_text())["rows"].values()
    values, provenance = {}, []
    for level in ("receivers", "prescaler"):
        matches = [r for r in rows if r["condition"] == c.tag and r["passive"] == rc and r["level"] == level
                   and r["status"] == "measured" and r["varactor"] == "native" and r["seed"] == "none"]
        if len(matches) != 1:
            raise ValueError(f"need one completed native {level} source at {c.tag}:{rc}")
        log = ROOT / matches[0]["smoke"]["directory"] / "simulator.log"
        data = {}
        for line in log.read_text().splitlines():
            m = re.fullmatch(r"([a-z][\w.]*)\s+([-+\d.eE]+)", line)
            if m:
                data[m[1]] = float(m[2])
        if len(data) < 100:
            raise ValueError(f"missing initial operating point: {log}")
        provenance.append(dict(level=level, path=str(log.relative_to(ROOT)), sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        if level == "receivers":
            for node, v in data.items():
                if not node.startswith("xpll.") and not initial:
                    continue
                node = re.sub(r"^xpll\.cm([0-3][pn])$", r"c\1", node)
                node = re.sub(r"^xpll\.b0([pn])$", r"pb0\1", node)
                values[node] = v
            # Identical restorer helper; only seed its internal balanced OP,
            # not the different feedback receiver's analogue gain stages.
            for node, v in data.items():
                if node.startswith("xpll.xrx0.xrestore."):
                    for k in range(4):
                        values[node.replace("xrx0", f"xfb{k}")] = v
        else:
            taps = {0: ("p02", "p04", "p08"), 1: ("xpll.d12", "xpll.d14", "xpll.d18"),
                    2: ("p22", "p24", "xpll.d28"), 3: ("p32", "xpll.d34", "xpll.d38")}
            for node, v in data.items():
                if node.startswith("xpll.xpre0."):
                    for k in range(4):
                        values[node.replace("xpre0", f"xpre{k}")] = v
                m = re.fullmatch(r"xpll.q([248])([pn])", node)
                if m:
                    for k in range(4):
                        values[taps[k][(2, 4, 8).index(int(m[1]))] + m[2]] = v
    payload = dict(condition=c.tag, passive=rc, kind="prebiased initial voltages" if initial else "Newton guesses only", sources=provenance, values=values)
    (workdir / "operating_guesses.json").write_text(json.dumps(payload, indent=2) + "\n")
    return [f".{('ic' if initial else 'nodeset')} v({node})={v:.12g}" for node, v in values.items()]


def deck(c, rc, level, solver, seed, varactor, stop, workdir, seed_source=None, seed_bc=None):
    table = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
    point = table[f"{c.tag}:{rc}"]
    code, ctrl = point["code"], point["vctrl"]
    lines = ["r5 isolated convergence experiment",
             f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vdummy vdum 0 {supply}",
              "Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
              f"Vctrl ctrl 0 {ctrl}", "Vreset rst_b 0 PWL(0 0 1n 0 1.02n {supply})"]
    lines += [f"Vcode{k} cfg{k} 0 {(code >> k & 1) * c.supply}" for k in range(4)]
    if level != "frontend":
        lines += [".subckt ring_boundary ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd vss",
                  "Xvco v0p v0n v1p v1n v2p v2n v3p v3n ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd vss pll_vco_ring4_4b"]
        for k in range(4):
            lines += [f"Xbuf{k} v{k}p v{k}n b{k}p b{k}n vbias vdd vss serdes_cml_buffer"]
            if level == "receivers":
                lines += [f"Xrx{k} b{k}p b{k}n cm{k}p cm{k}n vbias vdd vss serdes_cml_to_cmos_r4",
                          f"Cp{k} cm{k}p vss 20f", f"Cn{k} cm{k}n vss 20f"]
            elif level == "prescaler" and k == 0:
                lines += ["Xpre0 b0p b0n q2p q2n q4p q4n q8p q8n vbias vdd vss pll_cml_prescaler8"]
                lines += [f"C{k}{s} q{k}{s} vss 5f" for k in (2, 4, 8) for s in ("p", "n")]
            else:
                lines += [f"Cp{k} b{k}p vss 30f", f"Cn{k} b{k}n vss 30f"]
        lines += [".ends ring_boundary", "Xpll ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd 0 ring_boundary"]
    else:
        lines += ["Xpll ctrl cfg0 cfg1 cfg2 cfg3 vbias rst_b fb0 c0p c0n c1p c1n c2p c2n c3p c3n vdd vdum 0",
                  "+ pb0p pb0n p02p p02n p04p p04n p08p p08n p22p p22n p24p p24n p32p p32n pll_clock_frontend_r5"]
        if seed not in {"free", "assembled", "prebiased"}:
            for k in range(4):
                for cell in ("rx", "fb"):
                    lines += [f".nodeset v(xpll.x{cell}{k}.xrestore.qp)=0 v(xpll.x{cell}{k}.xrestore.qn)={{supply}}"]
    lines += ["Ikick xpll.v0p xpll.v0n PWL(0 1u 20p 1u 21p 0)"]
    if seed == "vco":
        # Balanced, plausible common mode; no differential startup preference.
        for k in range(4):
            for s in ("p", "n"):
                lines += [f".nodeset v(xpll.v{k}{s})={c.supply - .12} v(xpll.xvco.xv{k}{s}.p2)={ctrl}"]
    if seed in {"assembled", "prebiased"}:
        if level != "frontend" or (seed_source is None and seed_bc is None):
            raise ValueError("assembled seed needs --levels frontend and --seed-source CAMPAIGN")
        workdir.mkdir(parents=True, exist_ok=True)
        if seed_bc:
            if seed != "prebiased":
                raise ValueError("--seed-bc supports only --seeds prebiased")
            lines += registered_initial_state(seed_bc, c, rc, workdir)
        else:
            lines += assembled_seed(seed_source, c, rc, workdir, initial=seed == "prebiased")
    probes = ["v(vbias)", "v(bias_vbg)", "v(ctrl)"]
    probes += [f"v(xpll.v{k}{s})" for k in range(4) for s in ("p", "n")]
    probes += [f"v(xpll.xvco.xv{k}{s}.p2)" for k in range(4) for s in ("p", "n")]
    probes += [f"v({'pb0' if level == 'frontend' and k == 0 else f'xpll.b{k}'}{s})" for k in range(4) for s in ("p", "n")]
    if level == "frontend":
        probes += [f"v(p0{k}{s})" for k in (2, 4, 8) for s in ("p", "n")]
        probes += [f"v(c{k}{s})" for k in range(4) for s in ("p", "n")] + ["v(fb0)"]
        probes += [f"v(xpll.fb{k})" for k in (1, 2, 3)]
    elif level == "receivers":
        probes += [f"v(xpll.cm{k}{s})" for k in range(4) for s in ("p", "n")]
    elif level == "prescaler":
        probes += [f"v(xpll.q{k}{s})" for k in (2, 4, 8) for s in ("p", "n")]
    lines += [f".temp {c.temp}", f".options reltol=1e-4 abstol=1p vntol=1u {'klu' if solver == 'klu' else ''}",
              ".save " + " ".join(probes), ".control", "set num_threads=1", "set filetype=binary",
              f"tran 4p {stop:.8e} {max(0, stop - 20e-9):.8e} 4p", "write waveforms.raw " + " ".join(probes),
              "quit", ".endc", ".end", ""]
    workdir.mkdir(parents=True, exist_ok=True)
    text = bias.section(rcorner.to_pdk(bias.real("\n".join(lines)), workdir), c.process, rc)
    if seed == "prebiased":
        text = re.sub(r"^\.nodeset .*\n", "", text, flags=re.M)
        text = re.sub(r"^(tran .*)$", r"\1 uic", text, flags=re.M)
    if varactor == "stable":
        model, vco = stable_varactor(workdir)
        old = str(workdir / "pdk_resistors" / INCLUDES[10])
        assert text.count(old) == 1
        text = text.replace(f'.include "{old}"', f'.include "{model}"\n.include "{vco}"')
    return text


def measure(path, level, supply):
    w = spice.Waves(path)
    start = w.t[-1] - 5e-9
    b0 = "pb0" if level == "frontend" else "xpll.b0"
    nodes = {"vco": ("xpll.v0p", "xpll.v0n"), "buffer": (b0 + "p", b0 + "n")}
    if level == "frontend":
        nodes.update({f"div{k}": (f"p0{k}p", f"p0{k}n") for k in (2, 4, 8)})
    elif level == "prescaler":
        nodes.update({f"div{k}": (f"xpll.q{k}p", f"xpll.q{k}n") for k in (2, 4, 8)})
    stats = {key: clock.period_stats(w.t, w[p] - w[n], start=max(w.t[0], w.t[-1] - 16e-9) if key.startswith('div') else start)
             for key, (p, n) in nodes.items()}
    use = w.t >= start
    stats["max_varactor_internal_drop_v"] = float(max(np.max(np.abs(w[f"xpll.xvco.xv{k}{s}.p2"][use] - w["ctrl"][use])) for k in range(4) for s in ("p", "n")))
    stats["bias_vbg_v"] = float(np.mean(w["bias_vbg"][use]))
    vco = stats["vco"]
    stats["division_ratio_error"] = {f"div{k}": float(stats[f"div{k}"]["frequency_hz"] * k / vco["frequency_hz"] - 1)
                                     if vco and stats[f"div{k}"] else None for k in (2, 4, 8)} if level in {"frontend", "prescaler"} else {}
    if level in {"frontend", "receivers"}:
        fullrate = {}
        for k in range(4):
            node = f"c{k}p" if level == "frontend" else f"xpll.cm{k}p"
            y = w[node]
            ps = clock.period_stats(w.t, y - supply / 2, start=start)
            fullrate[str(k)] = dict(period=ps, low_v=float(y[use].min()), high_v=float(y[use].max()))
        stats["fullrate"] = fullrate
    if level == "frontend":
        stats["feedback"] = {str(k): clock.period_stats(w.t, w["fb0" if k == 0 else f"xpll.fb{k}"] - supply / 2,
                                                       start=max(w.t[0], w.t[-1] - 16e-9)) for k in range(4)}
    return stats


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--condition", default="ff_v1950_t-40")
    p.add_argument("--passive", default="ll")
    p.add_argument("--levels", default="ring,frontend")
    p.add_argument("--solvers", default="klu,sparse")
    p.add_argument("--seeds", default="none")
    p.add_argument("--varactors", default="native")
    p.add_argument("--seed-source", type=Path)
    p.add_argument("--seed-bc", help="registered and checked prebiased initial-state boundary id")
    p.add_argument("--stop", type=float, default=24e-9)
    p.add_argument("--timeout", type=float, default=240)
    p.add_argument("--workers", type=int, choices=range(1, 5), default=2)
    p.add_argument("--resume", type=Path)
    a = p.parse_args()
    if a.seed_source and a.seed_bc:
        p.error("choose --seed-source or --seed-bc")
    c = Condition.parse(a.condition)
    if a.stop < 12e-9:
        p.error("--stop must be >=12 ns for a settled measurement window")
    levels, solvers, seeds, varactors = a.levels.split(","), a.solvers.split(","), a.seeds.split(","), a.varactors.split(",")
    if not set(levels) <= {"ring", "receivers", "prescaler", "frontend"} or not set(solvers) <= {"klu", "sparse"} or not set(seeds) <= {"none", "vco", "free", "assembled", "prebiased"} or not set(varactors) <= {"native", "stable"} or a.passive not in {"tt", "hh", "ll"}:
        p.error("invalid experiment selection")
    camp = a.resume or ROOT / "results/analog/pll/convergence" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    camp.mkdir(parents=True, exist_ok=True)
    print(camp, flush=True)
    dependencies = set(INCLUDES + list(bias.BIAS_INC)) | {str(Path(__file__).resolve().relative_to(ROOT)), "config/pll_code_table.json"}
    source_identity = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sorted(dependencies)}
    if a.seed_source:
        source_identity[str(a.seed_source.resolve() / "summary.json")] = hashlib.sha256((a.seed_source / "summary.json").read_bytes()).hexdigest()
        for row in json.loads((a.seed_source / "summary.json").read_text())["rows"].values():
            if row.get("status") == "measured" and row["condition"] == c.tag and row["passive"] == a.passive and row["level"] in {"receivers", "prescaler"}:
                log = ROOT / row["smoke"]["directory"] / "simulator.log"
                source_identity[str(log.relative_to(ROOT))] = hashlib.sha256(log.read_bytes()).hexdigest()
    if a.seed_bc:
        entry = boundary.get(a.seed_bc)
        source_identity["boundary"] = entry
        point = entry["points"][f"{c.tag}:{a.passive}"]
        actual = hashlib.sha256((ROOT / point["initial_state_file"]).read_bytes()).hexdigest()
        if actual != point["initial_state_sha256"]:
            raise boundary.BoundaryMismatch("initial-state file changed")

    def run(level, solver, seed, varactor):
        tag = f"{c.tag}_{a.passive}_{level}_{solver}_{seed}_{varactor}"
        identity = dict(condition=c.tag, passive=a.passive, level=level, solver=solver, seed=seed, varactor=varactor,
                        stop_s=a.stop, sources=source_identity)
        preserve_identity(camp / "inputs" / f"{tag}.json", identity, prior_attempts=bool(list(camp.glob(tag + "*"))))
        path = spice.case_output(camp, tag, "waveforms.raw", a.stop)
        result = dict(condition=c.tag, passive=a.passive, level=level, solver=solver, seed=seed, varactor=varactor)
        if path is None:
            text = deck(c, a.passive, level, solver, seed, varactor, a.stop, camp / "snap" / tag, a.seed_source, a.seed_bc)
            smoke_dir = spice.next_run_dir(camp, tag + ".smoke")
            smoke = re.sub(r"^tran .*", "tran 4p 1n 0 4p" + (" uic" if seed == "prebiased" else ""), text, flags=re.M)
            ex = spice.run(smoke, smoke_dir, timeout_s=a.timeout, meta=dict(stage="smoke", **result))
            result["smoke"] = dict(directory=str(smoke_dir.relative_to(ROOT)), elapsed_s=ex.elapsed_s, exit_code=ex.exit_code)
            if spice.case_output(camp, tag + ".smoke", "waveforms.raw", 1e-9) is None:
                log = (smoke_dir / "simulator.log").read_text(errors="replace")
                stage = "solver" if "Direct Linear Solver" in log else "model_setup"
                return tag, dict(**result, status="smoke_incomplete", last_stage=stage, log_failures=ex.log_failures[:5])
            run_dir = spice.next_run_dir(camp, tag)
            ex = spice.run(text, run_dir, timeout_s=a.timeout, meta=dict(stage="full", **result))
            result["execution"] = dict(directory=str(run_dir.relative_to(ROOT)), elapsed_s=ex.elapsed_s, exit_code=ex.exit_code)
            path = spice.case_output(camp, tag, "waveforms.raw", a.stop)
        if path is None:
            return tag, dict(**result, status="incomplete")
        try:
            return tag, dict(**result, status="measured", waveform=str(path.relative_to(ROOT)), metrics=measure(path, level, c.supply))
        except (ValueError, KeyError) as e:
            return tag, dict(**result, status="measurement_error", error=str(e))

    summary_path = camp / "summary.json"
    rows = json.loads(summary_path.read_text())["rows"] if summary_path.exists() else {}
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        todo = [pool.submit(run, l, s, n, v) for l in levels for s in solvers for n in seeds for v in varactors]
        for future in as_completed(todo):
            tag, row = future.result()
            rows[tag] = row
            tmp = camp / "summary.json.tmp"
            tmp.write_text(json.dumps(dict(scope="convergence only; open-loop, fixed code/control, prebiased supply", rows=rows), indent=2) + "\n")
            tmp.replace(summary_path)
            print(tag, row["status"], row.get("metrics", {}).get("vco"), flush=True)


if __name__ == "__main__":
    main()
