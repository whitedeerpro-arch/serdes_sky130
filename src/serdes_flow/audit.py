"""Read-only campaign cost/completeness audit, separate from electrical acceptance.

uv run python -m serdes_flow.audit CAMPAIGN [--output NEW.json]
Audits stored attempts, including retries; summed elapsed time is process wall time, not CPU
time or campaign makespan. Waveforms are checked against each write's preceding tran stop.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re

from . import mc, spice
from .watch import ngspice_cwds, tail


def inspect(d: Path, alive: set) -> dict:
    text = (d / "tb.cir").read_text()
    try:
        ex = json.loads((d / "execution.json").read_text())
    except (OSError, ValueError):
        ex = {}
    log = tail(d / "simulator.log", 100000)
    row = dict(directory=str(d), elapsed_s=ex.get("elapsed_s"), exit_code=ex.get("exit_code"),
               log_flag_count=len(ex.get("log_failures", [])), kind="waveform", expected=0, completed=0)
    if re.search(r"wrdata\s+mc.tsv", text):
        row["kind"] = "mc"
        try:
            c = mc.contract(text)
            row["contract_complete"] = mc.complete(d, text)
        except ValueError:
            m = re.search(r"dowhile mc_k < (\d+)", text)
            c = dict(samples=int(m[1]) if m else 0, t_end=None)
            row["legacy_no_end_contract"] = True
        row["expected"] = c["samples"]
        try:
            rows = mc.read(d)
            row["completed"] = len(rows)
            row["rows_with_nonfinite_metric"] = sum(any(not math.isfinite(v) for v in r.values()) for r in rows)
            if c["t_end"] is not None:
                row["completed"] = sum(r.get("mc_t_end", float("nan")) >= c["t_end"] * (1 - 1e-6) for r in rows)
        except (OSError, ValueError):
            row["unreadable_rows"] = True
    else:
        end = None
        failures = []
        for line in text.splitlines():
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0].lower() == "tran" and len(tokens) >= 3:
                end = spice.spice_number(tokens[2])
            if tokens[0].lower() not in ("write", "wrdata") or len(tokens) < 2:
                continue
            name = tokens[1]
            if not name.endswith((".raw", ".tsv")):
                continue
            row["expected"] += 1
            try:
                w = spice.Waves(d / name)
                if end is not None and (len(w.t) == 0 or w.t[-1] < end * (1 - 1e-6)):
                    failures.append(dict(file=name, reason="truncated", end_s=float(w.t[-1]) if len(w.t) else None, expected_s=end))
                else:
                    row["completed"] += 1
            except (OSError, ValueError, IndexError) as exc:
                failures.append(dict(file=name, reason=type(exc).__name__))
        row["output_failures"] = failures
    if d.resolve() in alive:
        state = "running"
    elif not ex:
        state = "interrupted"
    elif ex.get("timed_out"):
        state = "timeout"
    elif ex.get("exit_code") != 0:
        state = "process_failed"
    elif row["expected"] == 0:
        state = "ungraded_no_output_contract"
    elif row["completed"] != row["expected"] or row.get("contract_complete") is False:
        state = "incomplete_output"
    else:
        state = "simulation_complete"
    row["state"] = state
    row["stuck_in_transient_op"] = "Transient op started" in log and "Initial Transient Solution" not in log and row["completed"] == 0
    row["memory_limit_seen"] = "Not enough memory" in log or "approaching max data size" in log
    return row


def audit(campaign):
    camp = Path(campaign)
    alive = ngspice_cwds()
    rows = [inspect(p.parent, alive) for p in sorted(camp.rglob("tb.cir"))]
    states, seconds = Counter(), Counter()
    for r in rows:
        states[r["state"]] += 1
        seconds[r["state"]] += r["elapsed_s"] or 0
    plan = camp / "plan.json"
    planned = json.loads(plan.read_text()).get("decks", {}) if plan.exists() else {}
    started = {re.sub(r"\.r\d+$", "", str(Path(r["directory"]).relative_to(camp))) for r in rows}
    return dict(campaign=str(camp), states=dict(states), summed_process_wall_s=dict(seconds),
                planned_decks=len(planned) if planned else None, not_started=sorted(set(planned) - started),
                note="Completion is not electrical pass. MC nonfinite values may include intentionally held lanes. "
                     "Historical MC lacks per-sample end-time proof. Costs include every attempt; unknown interrupted time is excluded.",
                attempts=rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("campaign")
    ap.add_argument("--output", help="new JSON file; existing files are never overwritten")
    args = ap.parse_args()
    result = audit(args.campaign)
    if args.output:
        p = Path(args.output)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("x") as f:
            json.dump(result, f, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "attempts"}, indent=2))


if __name__ == "__main__":
    main()
