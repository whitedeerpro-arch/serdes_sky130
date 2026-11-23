"""Local-mismatch spread of the temperature sense trip temperatures (serdes_tsense_vbe vs serdes_vref_gnd), real bandgap.

    uv run python analog/common/monitor/tb/tsense_mc/run.py [--points tt_v1800,ss_v1650,ff_v1950] [--codes 3,9,14]
        [--samples 200] [--chunk 25] [--workers 1]

Deck of tsense_dc with library section <process>_mm (resistor tt); per sample a `dc temp -40 125 1` sweep and the
temperature where the sense voltage crosses each listed ladder tap.  Mismatch: bandgap (vbg, r_ref), the two copies
(sense and ladder), the resistors; the PNP model has no mismatch term, so VBE's own spread is not in this result.
The comparator offset (cmp_mc) adds offset / |slope| (~1.7 mV/K).
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import mc, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("tsense_dc", ROOT / "analog/common/monitor/tb/tsense_dc/run.py")
td = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(td)
RESULTS = ROOT / "results/analog/common/monitor/tsense_mc"


def netlist(proc, supply, ts, lad, ncopy):
    vals = spice.corner_values(Condition(proc, supply, 27))
    return spice.render(td.TEMPLATE, **vals, SECTION=f"{proc}_mm", TS_PARAMS=ts, LAD_PARAMS=lad, NCOPY=ncopy)


def read_tolerant(run_dir):
    """mc.read, but an interrupted chunk's unfinished last line is dropped instead of failing the chunk."""
    try:
        return mc.read(run_dir)
    except ValueError:
        rows, names = [], None
        for line in (run_dir / mc.MC_FILE).read_text().splitlines():
            parts = line.split()
            try:
                vals = [float(x) for x in parts]
            except ValueError:
                names = names or parts
                continue
            if names and len(vals) == len(names):
                rows.append({k: (float("nan") if v <= mc.SENTINEL / 10 else v) for k, v in zip(names, vals)})
        return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800,ss_v1650,ff_v1950")
    ap.add_argument("--codes", default="3,9,14")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=8, help="~140 MB per sample (bandgap + ladder): 25 hit the 3 GB cap at sample ~21")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--ts", default="rs=23k")
    ap.add_argument("--lad", default="r0=85.6k rstep=1.57k")
    ap.add_argument("--ncopy", type=int, default=4)
    ap.add_argument("--analyse", help="campaign: summarize the rows already written (truncated chunks included), no simulation")
    a = ap.parse_args()
    codes = [int(x) for x in a.codes.split(",")]
    analysis = "\n".join(["dc temp -40 125 0.5"] + [f"meas dc t{k} when v(vs)=v(xlad.t{k})" for k in codes])
    lets = {f"trip{k}": f"t{k}" for k in codes}
    camp = (ROOT / a.analyse) if a.analyse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, owners = [], []
    for p in a.points.split(","):
        proc, v = p.split("_v")
        net = netlist(proc, int(v) / 1000, a.ts, a.lad, a.ncopy)
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis=analysis, lets=lets), camp / p / f"chunk{k:02d}",
                         dict(timeout_s=600 + 20 * n, meta=dict(point=p, samples=n, seed=s))))
            owners.append(p)
    if a.analyse:
        # sample k of a chunk seed is fixed; a memory-truncated or interrupted chunk keeps its first rows unchanged
        dirs = [j[1] for j in jobs if (j[1] / mc.MC_FILE).exists()]
    else:
        dirs = mc.run_many(jobs, workers=a.workers)
    out = {}
    print("trip temperature (local mismatch), C: mean / sd / k sd")
    for p in a.points.split(","):
        rows = [r for d in dirs if d.parent.name == p for r in (read_tolerant(d) if a.analyse else mc.read(d))]
        if not rows:
            print(f"  {p:10s} no samples")
            continue
        kf = stats.k_factor(len(rows))
        res = {}
        for k in codes:
            x = np.array([r[f"trip{k}"] for r in rows], float)
            x = x[np.isfinite(x)]
            res[str(k)] = dict(n=int(len(x)), mean=float(x.mean()), sd=float(x.std(ddof=1)))
        out[p] = dict(samples=len(rows), k=kf, codes=res)
        print(f"  {p:10s} n {len(rows):3d} k {kf:.2f} | " + " | ".join(
            f"code {k}: {res[str(k)]['mean']:6.1f} / {res[str(k)]['sd']:4.2f} / {kf * res[str(k)]['sd']:5.1f}" for k in codes), flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
