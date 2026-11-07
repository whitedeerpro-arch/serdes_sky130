"""Full TX over the 45 PVT conditions: per condition probe -> schedule -> RTL data -> 120 ns run, resumable.

    uv run python analog/tx/input_register/tb/full_serializer/pvt45.py start --clock-extra-2g 5 --clock-output-wt 16 \\
        --clock-output-r 240 --driver-params 'rpre=120 wtpre=60 wout=192' [--adopt COND=PROBE,RUN ...] [--workers 4] [--conds ...]
    uv run python analog/tx/input_register/tb/full_serializer/pvt45.py resume <campaign> [--workers 4] [--retry]
    uv run python analog/tx/input_register/tb/full_serializer/pvt45.py status <campaign>
    uv run python analog/tx/input_register/tb/full_serializer/pvt45.py summary <campaign>

Each condition goes through run.py exactly as a single point (its own identity, boundary and smoke checks):
probe (48 ns) -> prepare (registers the loaded word-clock schedule) -> tx_ingress_stimulus.py (RTL data) -> run (120 ns).
One worker carries one condition at a time, so at most --workers ngspice run.  Order: corners.boundary_first.

State per condition in <campaign>/state/<cond>.json (probe / run campaign directories as soon as run.py prints them).
After a reboot, `resume` continues every condition from its last finished step; an interrupted probe or run is resumed
by run.py --resume (case-level), a condition whose campaign still has a live ngspice is waited for, not restarted.
A step that fails (non-zero exit, analysis error) marks the condition `error` with the log; `resume --retry` retries it.
prepare writes config/boundary_conditions.json and is serialised.  --adopt takes finished single points of the same
configuration (plan fields and archived source hashes checked) instead of rerunning them.

Gates (docs/overview/spec.md): serializer and pad nodes 75 mV / 0.15 UI, training, no errors or extra/missing
crossings (serial.meets_draft); remote is a comparison screen.  Function: counting, input boundary, halfword hold,
RTL tags, in-order bit mapping.
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from serdes_flow import boundary, corners, watch
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RUN = HERE / "run.py"
PRODUCER = ROOT / "verification/digital/tx_ingress_stimulus.py"
PARALLEL = ROOT / "results/analog/tx/parallel_serializer"
RESULTS = ROOT / "results/analog/tx/full_pvt45"
PREPARE_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()


def now():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def state_path(camp, cond):
    return camp / "state" / f"{cond}.json"


def load_state(camp, cond):
    p = state_path(camp, cond)
    return json.loads(p.read_text()) if p.exists() else dict(condition=cond, status="queued")


def save_state(camp, st):
    with STATE_LOCK:
        p = state_path(camp, st["condition"])
        p.parent.mkdir(exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(st, indent=1) + "\n")
        tmp.replace(p)


def live(path):
    path = Path(path).resolve()
    return any(p.is_relative_to(path) for p in watch.ngspice_cwds())


def finished(run_camp):
    return run_camp is not None and (ROOT / run_camp / "summary.json").exists()


def failed_analysis(run_camp):
    return run_camp is not None and (ROOT / run_camp / "analysis_error.json").exists()


def call(camp, st, step, argv, record=None):
    """Run a step; stream its output to a log; record the campaign directory run.py prints first."""
    log = camp / "logs" / f"{st['condition']}_{step}_{now()}.log"
    log.parent.mkdir(exist_ok=True)
    st.setdefault("logs", []).append(str(log.relative_to(ROOT)))
    save_state(camp, st)
    with log.open("w") as out:
        proc = subprocess.Popen([sys.executable, *map(str, argv)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            out.write(line)
            out.flush()
            s = line.strip()
            if record and not st.get(record) and s.startswith(str(PARALLEL)):
                st[record] = str(Path(s).relative_to(ROOT))
                save_state(camp, st)
        code = proc.wait()
    if code:
        tail = log.read_text().strip().splitlines()[-3:]
        raise RuntimeError(f"{step} exit {code}: {' | '.join(tail)}")


def wait_live(path):
    while live(ROOT / path):
        time.sleep(30)


def aside(path):
    """An interrupted prepare / producer folder is kept under another name, never deleted."""
    path.rename(path.with_name(f"{path.name}.incomplete.{now()}"))


def advance(camp, plan, cond):
    st = load_state(camp, cond)
    if st["status"] == "done" or (st["status"] in ("error", "fail") and not plan.get("_retry")):
        return st
    st.update(status="running", error=None)
    save_state(camp, st)
    try:
        # probe
        if st.get("probe") and not finished(st["probe"]):
            if failed_analysis(st["probe"]):
                raise RuntimeError(f"probe analysis error: {json.loads((ROOT / st['probe'] / 'analysis_error.json').read_text())['error']}")
            wait_live(st["probe"])
            if not finished(st["probe"]):
                call(camp, st, "probe_resume", [RUN, "probe", "--resume", ROOT / st["probe"]])
        if not st.get("probe"):
            call(camp, st, "probe", [RUN, "probe", "--condition", cond, *plan["clock_args"], *plan["driver_args"]], record="probe")
        if not finished(st["probe"]):
            raise RuntimeError("probe produced no summary")
        probe = ROOT / st["probe"]
        bc_id = "tx_capture_serializer_word_schedule_" + probe.name
        st["boundary_id"] = bc_id
        # schedule
        prepared = probe / "prepared"
        with PREPARE_LOCK:
            registered = bc_id in boundary.registry()
            if prepared.exists() and not ((prepared / "schedule.json").exists() and registered):
                aside(prepared)
            if not prepared.exists():
                call(camp, st, "prepare", [RUN, "prepare", "--probe", probe])
        # RTL data
        producer = prepared / "producer"
        if producer.exists() and not (producer / "manifest.json").exists():
            aside(producer)
        if not producer.exists():
            call(camp, st, "producer", [PRODUCER, "--schedule", prepared / "schedule.json", "--output", producer])
        # dynamic run
        if st.get("run") and not finished(st["run"]):
            if failed_analysis(st["run"]):
                raise RuntimeError(f"run analysis error: {json.loads((ROOT / st['run'] / 'analysis_error.json').read_text())['error']}")
            wait_live(st["run"])
            if not finished(st["run"]):
                call(camp, st, "run_resume", [RUN, "run", "--resume", ROOT / st["run"]])
        if not st.get("run"):
            call(camp, st, "run", [RUN, "run", "--condition", cond, "--bc", bc_id, "--stimulus", producer], record="run")
        if not finished(st["run"]):
            raise RuntimeError("run produced no summary")
        st.update(status="done", grade=grade(ROOT / st["run"]))
    except Exception as e:  # noqa: BLE001 - every failure is recorded per condition, the others go on
        st.update(status="error", error=str(e)[:2000])
    save_state(camp, st)
    print(f"{now()} {cond:15s} {st['status']}" + (f" {st['error'][:160]}" if st.get("error") else f" {brief(st['grade'])}"), flush=True)
    return st


def grade(run_camp):
    s = json.loads((run_camp / "summary.json").read_text())
    out = {}
    for n in ("serializer", "pad", "remote"):
        o = s["outputs"][n]
        out[n] = dict(margin_mv=o["check"]["minimum_signed_margin_v"] * 1e3, spread_ui=o["check"]["transition_spread_ui"],
                      pp_mv=o["check"]["differential_pp_v"] * 1e3, errors=o["check"]["bit_errors"], functional=o["check"]["functional"],
                      in_order=o["mapping"]["in_order"], mapping_spread_ui=o["mapping"]["edge_spread_ui"], meets=o["meets_spec"])
    function = dict(counting=s["counter"]["counting"], input_boundary=s["input_boundary_ok"], halfword_hold=s["halfword_hold_ok"],
                    tags=s["behavioral_tags_align"], words=s["accepted_words"])
    ok_function = all(function[k] is True for k in ("counting", "input_boundary", "halfword_hold", "tags")) and all(out[n]["in_order"] for n in ("serializer", "pad"))
    return dict(outputs=out, function=function, function_ok=ok_function,
                gates_pass=bool(ok_function and out["serializer"]["meets"] and out["pad"]["meets"]))


def brief(g):
    o = g["outputs"]
    return (f"{'PASS' if g['gates_pass'] else 'FAIL'} ser {o['serializer']['margin_mv']:.1f} mV {o['serializer']['spread_ui']:.4f} UI, "
            f"pad {o['pad']['margin_mv']:.1f} mV {o['pad']['spread_ui']:.4f} UI {o['pad']['pp_mv']:.0f} mVpp, remote {o['remote']['spread_ui']:.4f} UI"
            + ("" if g["function_ok"] else " FUNCTION"))


def adopt(camp, plan, spec):
    cond, pair = spec.split("=", 1)
    probe, run = (Path(x) for x in pair.split(","))
    for p in (probe, run):
        pl = json.loads((ROOT / p / "plan.json").read_text())
        if pl["condition"] != cond or pl.get("driver_params") != plan["driver_params"] or \
                [pl["clock_extra_2g"], pl["clock_output_wt"], pl["clock_output_r"]] != plan["clock"]:
            raise ValueError(f"{p}: condition or configuration differs from the campaign")
        for rel, digest in pl["sources"].items():
            if rel in plan["sources"] and plan["sources"][rel] != digest:
                raise ValueError(f"{p}: {rel} differs from the campaign's source")
    if not finished(str(run)):
        raise ValueError(f"{run}: no summary")
    if json.loads((ROOT / run / "plan.json").read_text())["boundary_id"] != "tx_capture_serializer_word_schedule_" + Path(probe).name:
        raise ValueError(f"{run} was not run on {probe}'s schedule")
    st = dict(condition=cond, status="done", probe=str(probe), run=str(run), adopted=True,
              boundary_id="tx_capture_serializer_word_schedule_" + Path(probe).name, grade=grade(ROOT / run))
    save_state(camp, st)


def sources():
    import hashlib
    files = [RUN, Path(__file__), PRODUCER, HERE / "tb_full_ngspice.cir.in", ROOT / "analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice",
             ROOT / "digital/tx/rtl/tx_ingress_control.sv"]
    return {str(f.relative_to(ROOT)): hashlib.sha256(f.read_bytes()).hexdigest() for f in files}


def execute(camp, plan, workers):
    order = plan["conditions"]
    print(f"{camp.relative_to(ROOT)}: {len(order)} conditions, {workers} workers", flush=True)
    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(lambda c: advance(camp, plan, c), order))
    summary(camp)


def status(camp):
    plan = json.loads((camp / "plan.json").read_text())
    alive = watch.ngspice_cwds()
    counts = {}
    for cond in plan["conditions"]:
        st = load_state(camp, cond)
        step = "done" if st["status"] == "done" else ("run" if st.get("run") else "probe" if st.get("probe") else "-")
        active = [k for k in ("probe", "run") if st.get(k) and any(p.is_relative_to((ROOT / st[k]).resolve()) for p in alive)]
        counts[st["status"]] = counts.get(st["status"], 0) + 1
        if st["status"] != "queued":
            print(f"{cond:15s} {st['status']:8s} {step:5s} {'ngspice ' + active[0] if active else '':14s}"
                  + (brief(st["grade"]) if st.get("grade") else (st.get("error") or "")[:150]))
    print(counts)


def summary(camp):
    plan = json.loads((camp / "plan.json").read_text())
    rows = {c: load_state(camp, c) for c in plan["conditions"]}
    done = {c: s for c, s in rows.items() if s["status"] == "done"}
    print(f"{len(done)}/{len(rows)} done; gates (serializer + pad 75 mV / 0.15 UI, function): "
          f"{sum(s['grade']['gates_pass'] for s in done.values())} pass")
    for c, s in sorted(done.items(), key=lambda kv: kv[1]["grade"]["outputs"]["pad"]["spread_ui"], reverse=True)[:10]:
        print(f"  {c:15s} {brief(s['grade'])}")
    for c, s in rows.items():
        if s["status"] not in ("done", "queued"):
            print(f"  {c:15s} {s['status']} {(s.get('error') or '')[:200]}")
    (camp / "summary.json").write_text(json.dumps(dict(plan=plan, rows=rows), indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("start", "resume", "status", "summary"))
    ap.add_argument("campaign", nargs="?", type=Path)
    ap.add_argument("--clock-extra-2g", type=int, default=5)
    ap.add_argument("--clock-output-wt", type=float, default=16)
    ap.add_argument("--clock-output-r", type=float, default=240)
    ap.add_argument("--driver-params", default="rpre=120 wtpre=60 wout=192")
    ap.add_argument("--adopt", action="append", default=[], metavar="COND=PROBE,RUN")
    ap.add_argument("--conds", nargs="*")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--retry", action="store_true")
    a = ap.parse_args()
    if a.mode == "start":
        sys.path.insert(0, str(HERE))
        from run import driver_parameters, output_parameters  # same normalisation as the single-point runner
        wt, r = output_parameters(a.clock_output_wt, a.clock_output_r)
        driver = driver_parameters(a.driver_params)
        conds = [c.tag for c in corners.boundary_first(corners.grid45())]
        if a.conds:
            conds = [c for c in conds if c in set(a.conds)]
        camp = RESULTS / now()
        camp.mkdir(parents=True, exist_ok=False)
        plan = dict(conditions=conds, clock=[a.clock_extra_2g, wt, r], driver_params=driver,
                    clock_args=["--clock-extra-2g", str(a.clock_extra_2g), "--clock-output-wt", str(wt), "--clock-output-r", str(r)],
                    driver_args=["--driver-params", driver] if driver else [], sources=sources(), started=now(),
                    gates="serializer and pad: serial.meets_draft (75 mV / 0.15 UI) + function; remote: comparison")
        (camp / "plan.json").write_text(json.dumps(plan, indent=1) + "\n")
        for spec in a.adopt:
            adopt(camp, plan, spec)
    else:
        camp = (ROOT / a.campaign).resolve()
        plan = json.loads((camp / "plan.json").read_text())
        if a.mode == "status":
            return status(camp)
        if a.mode == "summary":
            return summary(camp)
        changed = [k for k, v in sources().items() if plan["sources"].get(k) != v]
        if [k for k in changed if not k.endswith("pvt45.py")]:
            raise ValueError(f"circuit, runner or data sources changed since the campaign started: {changed}")
        if changed:
            print("note: the orchestrator itself changed since the start (no effect on the simulations)", flush=True)
    plan["_retry"] = a.retry
    execute(camp, plan, a.workers)


if __name__ == "__main__":
    main()
