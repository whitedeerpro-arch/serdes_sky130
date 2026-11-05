"""Is a running campaign healthy?  One status line per probe; no effect on the simulations.

    uv run python -m serdes_flow.watch CAMPAIGN_DIR [--every 600] [--stall 4]

A probe lists the deck directories (those with tb.cir), counts finished cases (each case writes
one .raw/.tsv when its analysis ends; total = '* case' lines in tb.cir), reads the end of
simulator.log for error lines, and checks which ngspice processes run in which deck (/proc/<pid>/cwd).
States per deck:
  run    ngspice alive, output keeps coming
  STALL  ngspice alive, no new case for > stall x the typical case time (min 10 min)
  ERROR  error line in the log (timestep too small, singular matrix, ...)
  DEAD   no ngspice, no execution.json, cases missing (killed / crashed)
  done / FAIL  execution.json written; FAIL = non-zero exit or timeout
A rerun <deck>.rN (case-level resume) supersedes earlier attempts of the same deck; a deck that
died before plan.json was last written (the current driver) counts as queued, not DEAD.
If the driver wrote CAMPAIGN/plan.json ({"decks": {name: n_cases}}), totals include decks not
started yet.  The probe only reads directory listings and file tails (milliseconds).  Exits when
no ngspice is left in the campaign; the last line is the final state.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

from . import mc

ERR = re.compile(r"error|timestep too small|singular matrix|aborted", re.I)


def ngspice_cwds():
    out = set()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            if Path(f"/proc/{pid}/comm").read_text().strip() == "ngspice":
                out.add(Path(os.readlink(f"/proc/{pid}/cwd")).resolve())
        except OSError:
            continue
    return out


def tail(path, n=20000):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, f.seek(0, 2) - n))
            return f.read().decode(errors="replace")
    except OSError:
        return ""


def deck_state(d, alive, stall, now):
    deck = (d / "tb.cir").read_text(errors="replace")
    is_mc = bool(re.search(r"wrdata\s+mc.tsv", deck))
    total = sum(1 for l in deck.splitlines() if l.startswith("* case "))
    outs = sorted((p.stat().st_mtime for p in d.iterdir()
                   if (p.suffix in (".raw", ".tsv") or p.name.endswith(".raw.gz")) and p.stat().st_size > 0))
    done = len(outs)
    if is_mc:
        m = re.search(r"dowhile mc_k < (\d+)", deck)
        total = int(m[1]) if m else 0
        try:
            done = len(mc.read(d))
        except (OSError, ValueError):
            done = 0
    start = (d / "tb.cir").stat().st_mtime
    marks = [start] + outs
    typical = (marks[-1] - start) / done if done else None
    last = marks[-1]
    ex = d / "execution.json"
    errs = [l.strip() for l in tail(d / "simulator.log").splitlines() if ERR.search(l)]
    e = None
    if ex.exists():
        try:
            e = json.loads(ex.read_text())
        except ValueError:                 # truncated by a crash while being written
            e = None
    if e is not None:
        bad = e.get("exit_code") != 0 or e.get("timed_out") or (total > 0 and done < total)
        if is_mc and "* mc_contract " in deck:
            bad = bad or not mc.complete(d, deck)
        why = "timeout" if e.get("timed_out") else f"exit {e.get('exit_code')}"
        if bad and e.get("exit_code") == 0 and not e.get("timed_out"):
            why = "incomplete output (run audit for details)"
        return ("FAIL" if bad else "done"), done, total, (why if bad else "")
    if errs:
        return "ERROR", done, total, errs[-1][:80]
    if d.resolve() not in alive:
        return "DEAD", done, total, "no ngspice, no execution.json"
    limit = max(stall * typical, 600) if typical else 3 * 3600
    if now - last > limit:
        return "STALL", done, total, f"no new case for {(now - last) / 60:.0f} min (typical {typical / 60:.1f} min)" if typical \
            else f"first case not finished after {(now - last) / 60:.0f} min"
    return "run", done, total, ""


def _base(name):
    m = re.fullmatch(r"(.*)\.r(\d+)", name)
    return (m[1], int(m[2])) if m else (name, 1)


def probe(camp, stall):
    """Reruns (<deck>.rN, case-level resume) supersede earlier attempts: the newest attempt sets
    the state, finished cases are counted once over all attempts."""
    now = time.time()
    alive = ngspice_cwds()
    decks = sorted(p.parent for p in Path(camp).rglob("tb.cir")
                   if not re.search(r"\.(pilot|smoke)(\.r\d+)?$", p.parent.name))
    groups = {}
    for d in decks:
        b, i = _base(str(d.relative_to(camp)))
        groups.setdefault(b, []).append((i, d))
    plan = Path(camp) / "plan.json"
    planned = json.loads(plan.read_text())["decks"] if plan.exists() else {}
    plan_t = plan.stat().st_mtime if plan.exists() else 0.0
    states, done, total, pending = {}, 0, 0, 0
    for b, att in groups.items():
        att.sort()
        s, ndone, n, why = deck_state(att[-1][1], alive, stall, now)
        last = max(q.stat().st_mtime for q in att[-1][1].iterdir())
        if s == "DEAD" and last < plan_t:      # interrupted before the current driver started: rerun pending
            s, pending = "pending", pending + 1
        outs = {q.name for _, d in att for q in d.iterdir()
                if (q.suffix in (".raw", ".tsv") or q.name.endswith(".raw.gz")) and q.stat().st_size > 0}
        n_total = planned.get(b, deck_state(att[0][1], alive, stall, now)[2])
        states[b] = (s, why)
        is_mc = bool(re.search(r"wrdata\s+mc.tsv", (att[-1][1] / "tb.cir").read_text()))
        done += ndone if is_mc else len(outs)
        total += n_total
    bad = {k: v for k, v in states.items() if v[0] in ("STALL", "ERROR", "DEAD", "FAIL")}
    running = sum(v[0] == "run" for v in states.values())
    waiting = {k: n for k, n in planned.items() if k not in groups}
    total += sum(waiting.values())
    queued = f", {len(waiting) + pending} queued" if planned else ""
    head = time.strftime("%H:%M") + (" ABNORMAL" if bad else " ok")
    line = f"{head}: {done}/{total} cases, {running} decks running{queued}"
    if bad:
        line += "; " + "; ".join(f"{k} {s} {why}" for k, (s, why) in bad.items())
    finished = not any(d.resolve() in alive for d in decks)
    return line, finished


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign")
    ap.add_argument("--every", type=float, default=600, help="seconds between probes")
    ap.add_argument("--stall", type=float, default=4, help="stall threshold, multiples of the typical case time")
    a = ap.parse_args()
    while True:
        line, finished = probe(a.campaign, a.stall)
        if finished:                       # confirm: a worker may be between two decks
            time.sleep(5)
            line, finished = probe(a.campaign, a.stall)
        print(("final " if finished else "") + line, flush=True)
        if finished:
            break
        time.sleep(a.every)


if __name__ == "__main__":
    main()
