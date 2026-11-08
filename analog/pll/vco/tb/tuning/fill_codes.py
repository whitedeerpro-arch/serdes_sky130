"""Fill the 4-bit VCO working map: every code a chip can use, at all three temperatures, on a finer Vctrl grid.

    uv run python analog/pll/vco/tb/tuning/fill_codes.py [--from <workmap campaign>] [--workers 4] [--resume <campaign>]

The working map (workmap.py) simulated, per condition, the codes near 2 GHz at 0.85 / 1.10 / 1.35 V; a code is often
missing at the temperatures where another code is used, and the parabola through three points is poor below 0.9 V and
above 1.35 V.  Re-coding over temperature (recode_policy.py) and the loop's Kvco range need each usable code's curve at
-40 / 27 / 85 C.  Codes: per chip (MOS x VDD x RC section), those with a 2 GHz crossing in 0.8 V .. VDD - 0.35 V at any
temperature in the source map, one neighbour each side.  Vctrl: 0.80 V upward in 0.15 V steps to VDD - 0.35 V.  Same bench
and measurement as workmap.py (real bias, PDK R, four buffers); one deck per MOS x RC x VDD; case-level resume.
Output summary.json: rows[condition:rc] = dict(vs, f[code], swing[code]).
"""
import argparse
import importlib.util
import json
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("vco_workmap", HERE / "workmap.py")
wm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wm)
SOURCE = "results/analog/pll/vco/workmap/20261106T035710Z"
RESULTS = ROOT / "results/analog/pll/vco/workmap_fill"


def grid(supply):
    return [round(v, 3) for v in np.arange(0.80, supply - 0.35 + 1e-9, 0.15)]


def plan(source):
    src = json.loads((ROOT / source / "summary.json").read_text())
    vs = np.array(src["vs"])
    codes = defaultdict(set)
    for key, r in src["rows"].items():
        cond, rc = key.split(":")
        c = Condition.parse(cond)
        for code, f in r["f"].items():
            p = np.polyfit(vs, f, 2)
            roots = [x.real for x in np.roots([p[0], p[1], p[2] - 2e9]) if abs(x.imag) < 1e-12]
            if any(0.8 <= x <= c.supply - 0.35 for x in roots):
                codes[(c.process, c.supply, rc)].add(int(code))
    pts = []
    for (proc, supply, rc), ks in codes.items():
        use = sorted({k + d for k in ks for d in (-1, 0, 1)} & set(range(16)))
        for temp in (-40, 27, 85):
            c = Condition(proc, supply, temp)
            for k in use:
                for v in grid(supply):
                    pts.append((rc, c, k, v))
    return pts


def deck_name(c, rc):
    return f"{c.process}_{rc}_v{round(c.supply * 1000)}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="source", default=SOURCE)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    pts = plan(a.source)
    groups = defaultdict(list)
    for rc, c, k, v in pts:
        if spice.case_output(camp, deck_name(c, rc), wm.name(c, k, v), wm.STOP) is None:
            groups[(c.process, rc, c.supply)].append((c, k, v))
    todo = sum(len(x) for x in groups.values())
    print(f"{len(pts)} points, {todo} to run in {len(groups)} decks -> {camp.relative_to(ROOT)}", flush=True)
    if todo:
        camp.mkdir(parents=True, exist_ok=True)
        (camp / "plan.json").write_text(json.dumps(dict(source=a.source, points=len(pts), grid="0.80 V + 0.15 V steps to VDD - 0.35 V"), indent=1))
        jobs = [(wm.deck(p, rc, g, camp / "snap" / f"{p}_{rc}_{round(s * 1000)}", 4), spice.next_run_dir(camp, deck_name(g[0][0], rc)),
                 dict(timeout_s=60 * len(g) + 600, meta=dict(process=p, passive=rc, supply=s, points=len(g))))
                for (p, rc, s), g in groups.items()]
        for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
            if not ex.ok:
                print(f"deck {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)
    rows = defaultdict(lambda: dict(vs=None, f={}, swing={}))
    missing = 0
    for rc, c, k, v in pts:
        p = spice.case_output(camp, deck_name(c, rc), wm.name(c, k, v), wm.STOP)
        m = wm.measure(p) if p else None
        r = rows[f"{c.tag}:{rc}"]
        r["vs"] = grid(c.supply)
        if m is None:
            missing += 1
            m = (float("nan"), float("nan"))
        r["f"].setdefault(str(k), []).append(m[0])
        r["swing"].setdefault(str(k), []).append(m[1])
    (camp / "summary.json").write_text(json.dumps(dict(source=a.source, rows=rows), indent=1))
    print(f"{len(rows)} conditions, {missing} points missing; {camp.relative_to(ROOT)}/summary.json", flush=True)


if __name__ == "__main__":
    main()
