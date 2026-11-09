"""Fill the 4-bit VCO working map: every code a chip can use, at all three temperatures, on a finer Vctrl grid.

    uv run python analog/pll/vco/tb/tuning/fill_codes.py [--from <workmap campaign>] [--workers 4] [--resume <campaign>] [--missing-only]

The working map (workmap.py) simulated, per condition, the codes near 2 GHz at 0.85 / 1.10 / 1.35 V; a code is often
missing at the temperatures where another code is used, and the parabola through three points is poor below 0.9 V and
above 1.35 V.  Re-coding over temperature (recode_policy.py) and the loop's Kvco range need each usable code's curve at
-40 / 27 / 85 C.  Codes: per chip (MOS x VDD x RC section), those with a 2 GHz crossing in 0.8 V .. VDD - 0.35 V at any
temperature in the source map, one neighbour each side.  Vctrl: 0.80 V upward in 0.15 V steps to VDD - 0.35 V.  Same bench
and measurement as workmap.py (real bias, PDK R, four buffers); one deck per MOS x RC x VDD; case-level resume.
--missing-only: only the (code, temperature) pairs the source map lacks; counts depend on the supplied source map. The
recoding model needs each usable code at all three temperatures, the denser grid on codes it already has is a refinement.
Output summary.json: rows[condition:rc] = dict(vs, f[code], swing[code]).
"""
import argparse
import hashlib
import importlib.util
import json
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

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


def plan_missing(source):
    """Only the temperatures a usable code is missing in the source map (the codes with a 2 GHz crossing in
    0.8 V .. VDD - 0.35 V at some temperature, no neighbours), on the same Vctrl grid as plan()."""
    src = json.loads((ROOT / source / "summary.json").read_text())
    vs = np.array(src["vs"])
    have = defaultdict(lambda: defaultdict(set))           # chip -> code -> temperatures simulated
    use = defaultdict(set)
    for key, r in src["rows"].items():
        cond, rc = key.split(":")
        c = Condition.parse(cond)
        chip = (c.process, c.supply, rc)
        for code, f in r["f"].items():
            have[chip][int(code)].add(c.temp)
            p = np.polyfit(vs, f, 2)
            roots = [x.real for x in np.roots([p[0], p[1], p[2] - 2e9]) if abs(x.imag) < 1e-12]
            if any(0.8 <= x <= c.supply - 0.35 for x in roots):
                use[chip].add(int(code))
    pts = []
    for (proc, supply, rc), ks in use.items():
        for temp in (-40, 27, 85):
            c = Condition(proc, supply, temp)
            for k in sorted(ks):
                if temp not in have[(proc, supply, rc)][k]:
                    pts += [(rc, c, k, v) for v in grid(supply)]
    return pts


def deck_name(c, rc):
    return f"{c.process}_{rc}_v{round(c.supply * 1000)}"


def collect(pts, lookup, measure):
    """Only complete, measured code grids enter the matrices; retain all other observations."""
    groups = {}
    for rc, c, k, v in pts:
        key = (c.tag, rc, k)
        groups.setdefault(key, (c, {}))[1][float(v)] = lookup(rc, c, k, v)
    rows = defaultdict(lambda: dict(vs=None, f={}, swing={}))
    partial = []
    for (tag, rc, code), (c, paths) in sorted(groups.items()):
        vs = [float(v) for v in grid(c.supply)]
        observations = []
        for v in vs:
            path = paths.get(v)
            value = None
            reason = ('missing_waveform' if v in paths else 'not_planned') if path is None else None
            if path is not None:
                try:
                    value = measure(path)
                    if value is None or len(value) != 2 or not np.all(np.isfinite(value)):
                        value, reason = None, 'measurement_failed'
                except (ValueError, OSError, KeyError, IndexError):
                    value, reason = None, 'measurement_failed'
            observations.append(dict(v=v, path=str(path) if path is not None else None,
                                     f=float(value[0]) if value is not None else None,
                                     swing=float(value[1]) if value is not None else None, reason=reason))
        key = f'{tag}:{rc}'
        row = rows[key]
        row['vs'] = vs
        if all(x['reason'] is None for x in observations):
            row['f'][str(code)] = [x['f'] for x in observations]
            row['swing'][str(code)] = [x['swing'] for x in observations]
        else:
            partial.append(dict(condition=key, code=code, existing_v=[x['v'] for x in observations if x['reason'] is None],
                                missing_v=[x['v'] for x in observations if x['reason'] is not None], observations=observations))
    return dict(rows=dict(rows), partial_rows=partial)


def analysis_dir(camp):
    path = camp / 'analysis' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
    path.mkdir(parents=True, exist_ok=False)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="source", default=SOURCE)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--collect-only", action="store_true", help="collect existing outputs into a new analysis directory; never simulate")
    ap.add_argument("--missing-only", action="store_true", help="only the temperatures a usable code lacks in the source map; "
                    "points of the full plan already simulated in the campaign are kept in the summary")
    a = ap.parse_args()
    if a.collect_only and not a.resume:
        ap.error('--collect-only requires --resume')
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    pts = plan(a.source)
    if a.missing_only:
        need = plan_missing(a.source)
        keep = set(need)
        pts = need + [x for x in pts if x not in keep and spice.case_output(camp, deck_name(x[1], x[0]), wm.name(x[1], x[2], x[3]), wm.STOP) is not None]
    groups = defaultdict(list)
    for rc, c, k, v in pts:
        if spice.case_output(camp, deck_name(c, rc), wm.name(c, k, v), wm.STOP) is None:
            groups[(c.process, rc, c.supply)].append((c, k, v))
    todo = sum(len(x) for x in groups.values())
    print(f"{len(pts)} points, {todo} to run in {len(groups)} decks -> {camp.relative_to(ROOT)}", flush=True)
    if todo and not a.collect_only:
        camp.mkdir(parents=True, exist_ok=True)
        run_plan = analysis_dir(camp) / 'run_plan.json'
        source_hash = hashlib.sha256((ROOT / a.source / 'summary.json').read_bytes()).hexdigest()
        run_plan.write_text(json.dumps(dict(source=a.source, source_summary_sha256=source_hash, points=len(pts),
                                            missing_only=a.missing_only, pending_points=todo,
                                            grid="0.80 V + 0.15 V steps to VDD - 0.35 V"), indent=1) + '\n')
        jobs = [(wm.deck(p, rc, g, camp / "snap" / f"{p}_{rc}_{round(s * 1000)}", 4), spice.next_run_dir(camp, deck_name(g[0][0], rc)),
                 dict(timeout_s=60 * len(g) + 600, meta=dict(process=p, passive=rc, supply=s, points=len(g))))
                for (p, rc, s), g in groups.items()]
        for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
            if not ex.ok:
                print(f"deck {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)
    result = collect(pts, lambda rc, c, k, v: spice.case_output(camp, deck_name(c, rc), wm.name(c, k, v), wm.STOP), wm.measure)
    source_hash = hashlib.sha256((ROOT / a.source / 'summary.json').read_bytes()).hexdigest()
    result.update(source=a.source, source_summary_sha256=source_hash, missing_only=a.missing_only)
    out = analysis_dir(camp) / 'summary.json'
    out.write_text(json.dumps(result, indent=1, allow_nan=False) + '\n')
    print(f"{len(result['rows'])} conditions, {len(result['partial_rows'])} partial code rows; {out.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
