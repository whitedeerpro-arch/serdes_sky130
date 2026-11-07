"""Local 16-bit staggered ingress: word coherence, selected-input hold and B close.

uv run python analog/tx/input_register/tb/staggered/run.py --run-only tt_v1800_t27
uv run python analog/tx/input_register/tb/staggered/run.py --resume CAMPAIGN

Real bias/PDK R tt; matched ideal CMOS clock or actual receiver/buffer driven
by an ideal CML source. Eight first-rank muxes drive 5 fF/output. No full serializer,
power-up, aperture, mismatch or noise acceptance. All eight words are checked.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

from serdes_flow import bias, clock, rcorner, spice
from serdes_flow.corners import Condition, STRESS, boundary_first
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
DUT = ROOT / "analog/tx/input_register/spice/word_capture16_staggered.spice"
WARMUP = 4e-9
STOP = 40e-9
WORDS = (0xA55A, 0x5AA5, 0, 0xFFFF, 0x0FF0, 0xF00F, 0x1234, 0xECA7, 0xB79C)


def stimulus():
    lines = []
    for lane in range(16):
        values = [(word >> lane) & 1 for word in WORDS]
        points = [f"0 {values[0]}"]
        for k in range(1, len(values)):
            if values[k] != values[k - 1]:
                points += [f"{WARMUP+(4*k+.005)*1e-9:.10e} {values[k-1]}", f"{WARMUP+(4*k+.025)*1e-9:.10e} {values[k]}"]
        lines += [f"Vd{lane} du{lane} 0 PWL({' '.join(points)})", f"Bd{lane} d{lane} 0 V=v(vdd)*v(du{lane})"]
    return "\n".join(lines)


def vectors():
    return ["v(clk)", "v(xcap.clk_b)", "v(vdd)", "v(sp)", "v(sn)", "i(Vclock_sense)"] + [f"v(q{i})" for i in range(16)] + [f"v(c{i}{s})" for i in range(16) for s in ("p", "n")] + [f"v(z{i}{s})" for i in range(8) for s in ("p", "n")] + [f"v(xcap.h{i})" for i in range(8, 16)]


def deck(conditions, params, snap, smoke=False, solver="sparse", clock_mode="ideal"):
    clock_includes = ""
    clock_source = "Bclock clk_driver 0 V=v(vdd)*v(ck_u)"
    if clock_mode == "receiver":
        clock_includes = '\n'.join(f'.include "{ROOT / x}"' for x in CLOCK_SOURCES)
        clock_source = "Xwordclock sp sn clk_driver vbias vdd 0 serdes_tx_word_clock"
    loads = [f"Xc{i} q{i} c{i}p c{i}n vbias vdd 0 serdes_cmos_to_cml_data\nCq{i} q{i} 0 2f" for i in range(16)]
    for i in range(8):
        loads += [f"Xm{i} c{i}p c{i}n c{i+8}p c{i+8}n sp sn z{i}p z{i}n vbias vbias_logic vdd 0 serdes_cml_mux2_lowov wdata=40 wselect=96 wtail=72 nftail=24 wsf=80 rload=500",
                  f"Czp{i} z{i}p 0 5f", f"Czn{i} z{i}n 0 5f"]
    blocks = []
    for c in conditions:
        tran = "tran 2p 1n 0 2p" if smoke else spice.skip_output_before(f"tran 2p {STOP:.8e} 0 2p", "2n")
        blocks += [f"option temp={c.temp}", f"alter Vdd dc={c.supply}", tran,
                   f"write {c.tag}.raw " + " ".join(vectors()), "destroy all"]
    guesses = [f".nodeset v(q{i})=0 v(xcap.s{i})=0" for i in range(16)]
    text = spice.render(HERE / "tb_staggered_ngspice.cir.in", **spice.corner_values(conditions[0]),
                        DATA=stimulus(), PARAMS=" ".join(f"{k}={v}" for k, v in params.items()), LOADS="\n".join(loads),
                        GUESSES="\n".join(guesses), VECTORS=" ".join(vectors()), CASES="\n".join(blocks), SOLVER="klu" if solver == "klu" else "",
                        CLOCK_INCLUDES=clock_includes, CLOCK_SOURCE=clock_source)
    return bias.section(rcorner.to_pdk(bias.real(text), snap), conditions[0].process, "tt")


CLOCK_SOURCES = (
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/tx/input_register/spice/word_clock_receiver.spice",
)


def measure(path, clock_mode="ideal"):
    w = spice.Waves(path)
    if w.t[-1] < STOP * (1 - 1e-7):
        raise ValueError("incomplete transient")
    vdd = float(np.mean(w["vdd"]))
    # Select timing belongs to the MUX CML ports, not the delayed CMOS clock.
    # The original ideal campaign saved only clk; its deck explicitly matches
    # both ideal sources. Never allow this legacy fallback for a real receiver.
    try:
        select = w["sp"] - w["sn"]
    except KeyError:
        if clock_mode != "ideal":
            raise
        select = w["clk"] - vdd / 2
    falls = clock.edges(w.t, select, -1, WARMUP+2e-9, WARMUP+34e-9)
    rises = clock.edges(w.t, select, 1, WARMUP+4e-9, WARMUP+35e-9)
    captures = clock.edges(w.t, w["clk"] - vdd / 2, 1, WARMUP+4e-9, WARMUP+35e-9)
    closes = clock.edges(w.t, w["xcap.clk_b"] - vdd / 2, -1, WARMUP+4e-9, WARMUP+35e-9)
    clock_falls = clock.edges(w.t, w["clk"] - vdd / 2, -1, WARMUP+2e-9, WARMUP+34e-9)
    if len(falls) != 8 or len(rises) != 8 or len(closes) != 8 or len(captures) != 8 or len(clock_falls) != 8:
        raise ValueError(f"wrong phase counts: {len(falls)}, {len(rises)}, {len(closes)}, {len(captures)}")
    if np.any(captures < rises) or np.any(captures > rises + 2e-9) or np.any(closes < captures) or np.any(closes > rises + 2e-9):
        raise ValueError("clock receiver phase/latency outside this word contract")
    rows, separations = [], []
    for k, (a_edge, b_edge) in enumerate(zip(falls, rises)):
        lane_rows, recovered = [], 0
        for lane in range(16):
            edge = a_edge if lane < 8 else b_edge
            start, end = edge - .1e-9, edge + 1.9e-9
            keep = (w.t >= start) & (w.t <= end)
            sign = 1 if (WORDS[k] >> lane) & 1 else -1
            q = w[f"q{lane}"]
            d = w[f"c{lane}p"] - w[f"c{lane}n"]
            z = w[f"z{lane % 8}p"] - w[f"z{lane % 8}n"]
            q_margin = float(np.min((q[keep] - vdd / 2) * sign))
            cml_margin = float(np.min(d[keep] * sign))
            out_sample = float(np.interp(edge + 1e-9, w.t, z))
            recovered |= int(out_sample > 0) << lane
            lane_rows.append(dict(lane=lane, selected_from_s=float(edge), hold_from_s=float(start), hold_until_s=float(end),
                                  cmos_signed_margin_v=q_margin, cml_signed_margin_v=cml_margin,
                                  cmos_hold_ok=q_margin > .3 * vdd, cml_hold_ok=cml_margin > 0,
                                  mux_sample_v=out_sample, mux_sample_ok=out_sample * sign > 0))
            if lane >= 8 and ((WORDS[k] ^ WORDS[k + 1]) >> lane) & 1:
                polarity = 1 if (WORDS[k + 1] >> lane) & 1 else -1
                updates = clock.edges(w.t, w[f"xcap.h{lane}"] - vdd / 2, polarity, float(b_edge), float(b_edge + 1.9e-9))
                if len(updates) != 1:
                    raise ValueError(f"word {k} lane {lane}: expected one next-data transition, got {len(updates)}")
                separations.append(dict(word=k, lane=lane, b_clock_close_s=float(closes[k]),
                                        next_data_arrival_s=float(updates[0]) if len(updates) else None,
                                        separation_ps=float((updates[0] - closes[k]) * 1e12) if len(updates) else None))
        rows.append(dict(word=k, expected=WORDS[k], recovered=recovered, correct=recovered == WORDS[k], lanes=lane_rows))
    values = [s["separation_ps"] for s in separations if s["separation_ps"] is not None]
    return dict(functional=all(r["correct"] and all(l["cmos_hold_ok"] and l["cml_hold_ok"] and l["mux_sample_ok"] for l in r["lanes"]) for r in rows),
                words=rows, b_close_data_separation=separations, minimum_b_close_data_separation_ps=min(values) if values else None,
                separation_is_aperture_proof=False, clock_mode=clock_mode,
                clock_rising_delay_ps=((captures-rises)*1e12).tolist(),
                clock_falling_delay_ps=((clock_falls-falls)*1e12).tolist(),
                warmup_s=WARMUP, valid_control_implemented=False)


def summarize(camp, conditions):
    mode = json.loads((camp / "plan.json").read_text()).get("clock_mode", "ideal")
    rows = []
    for c in conditions:
        row = dict(condition=c.tag, status="missing")
        wave = spice.case_output(camp, c.process, c.tag + ".raw", STOP)
        if wave:
            try:
                row.update(status="measured", waveform=str(wave.relative_to(ROOT)), metrics=measure(wave, mode))
            except (ValueError, KeyError) as error:
                row.update(status="analysis_error", error=str(error))
        rows.append(row)
    result = dict(scope="Local 16-bit capture and complementary launch, actual converters/eight first muxes, real bias/PDK R tt; 5fF first-mux output proxy. Not full serializer, startup, aperture, mismatch or noise qualification", clock_mode=mode, rows=rows)
    tmp = camp / "summary.json.tmp"
    tmp.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    tmp.replace(camp / "summary.json")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--resume", type=Path)
    p.add_argument("--run-only", help="comma-separated subset of the six planned conditions")
    p.add_argument("--workers", type=int, choices=(1, 2), default=2)
    p.add_argument("--param", action="append", default=[])
    p.add_argument("--solver", choices=("sparse", "klu"))
    p.add_argument("--clock", choices=("ideal", "receiver"))
    a = p.parse_args()
    params = dict(x.split("=", 1) for x in a.param)
    if set(params) - {"ckwn", "ckwp", "delaywn", "delaywp"} or any(spice.spice_number(v) <= 0 for v in params.values()):
        p.error("unsupported or nonpositive device size")
    sources = [Path(__file__), HERE / "tb_staggered_ngspice.cir.in", DUT, ROOT / "src/serdes_flow/spice.py", ROOT / "src/serdes_flow/bias.py", ROOT / "src/serdes_flow/rcorner.py"]
    sources += [ROOT / x for x in bias.BIAS_INC]
    sources += [ROOT / "analog/common/devices/spice" / x for x in ("sky130_primitives.spice", "cmos_logic.spice", "cmos_dff.spice")]
    sources += [ROOT / "analog/common/cmos_to_cml/spice/cmos_to_cml_data.spice", ROOT / "analog/common/cml_mux/spice/cml_lowov_cells.spice"]
    sources += [ROOT / x for x in CLOCK_SOURCES]
    sources += [ROOT / "src/serdes_flow/clock.py", ROOT / "src/serdes_flow/corners.py", ROOT / "config/pdk.toml"]
    identity = {str(x.relative_to(ROOT)): hashlib.sha256(x.read_bytes()).hexdigest() for x in sources}
    camp = a.resume.resolve() if a.resume else ROOT / "results/analog/tx/staggered_ingress" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    camp.mkdir(parents=True, exist_ok=True)
    plan_path = camp / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        if plan["sources"] != identity or (params and params != plan["params"]) or (a.solver and a.solver != plan["solver"]) or (a.clock and a.clock != plan["clock_mode"]):
            raise ValueError("changed inputs; use a new campaign")
        params = plan["params"]
        solver = plan["solver"]
        clock_mode = plan["clock_mode"]
        conditions = [Condition.parse(t) for t in plan["conditions"]]
    else:
        if a.resume:
            raise ValueError("no original plan")
        conditions = boundary_first(STRESS)
        solver = a.solver or "sparse"
        clock_mode = a.clock or "ideal"
        plan_path.write_text(json.dumps(dict(sources=identity, params=params, solver=solver, clock_mode=clock_mode, conditions=[c.tag for c in conditions], words=list(WORDS), stop_s=STOP, warmup_s=WARMUP, valid_control_implemented=False), indent=2) + "\n")
    for source in sources:
        dest = camp / "execution" / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest() != identity[str(source.relative_to(ROOT))]:
                raise ValueError(f"source snapshot changed: {dest}")
        else:
            shutil.copyfile(source, dest)
    print(camp, flush=True)
    selected = a.run_only.split(",") if a.run_only else [c.tag for c in conditions]
    if set(selected) - {c.tag for c in conditions}:
        raise ValueError("run-only must be a planned condition")
    groups = {}
    for c in conditions:
        if c.tag in selected and spice.case_output(camp, c.process, c.tag + ".raw", STOP) is None:
            groups.setdefault(c.process, []).append(c)
    if groups:
        first = next(iter(groups.values()))[0]
        smoke = spice.run(deck([first], params, camp / "snap/smoke", True, solver, clock_mode), spice.next_run_dir(camp, "smoke"), timeout_s=150)
        if not smoke.ok or spice.case_output(camp, "smoke", first.tag + ".raw", 1e-9) is None:
            raise RuntimeError(f"smoke failed: {smoke.run_dir}")
        jobs = [(deck(cs, params, camp / "snap" / proc, solver=solver, clock_mode=clock_mode), spice.next_run_dir(camp, proc), dict(timeout_s=180 + 150 * len(cs), meta=dict(conditions=[c.tag for c in cs], params=params, solver=solver, clock_mode=clock_mode))) for proc, cs in groups.items()]
        try:
            for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
                print(ex.run_dir.name, ex.exit_code, round(ex.elapsed_s, 1), flush=True)
        finally:
            summarize(camp, conditions)
    for row in summarize(camp, conditions)["rows"]:
        print(row["condition"], row["status"], row.get("metrics", {}).get("functional"), row.get("metrics", {}).get("minimum_b_close_data_separation_ps"), flush=True)


if __name__ == "__main__":
    main()
