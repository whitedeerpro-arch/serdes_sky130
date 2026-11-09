"""Local-mismatch offset of the monitor comparator (serdes_cmp), real bandgap bias, library section <process>_mm.

    uv run python analog/common/monitor/tb/cmp_mc/run.py [--points tt_v1800_t27,ss_v1650_t-40,...] [--cms 0.9,1.3]
        [--samples 200] [--chunk 8] [--workers 3]

Deck of cmp_trip (inn = Vcm, inp = Vcm + a +-30 mV triangle, 60 us per edge); per sample and common mode the static
offset = mean of the rising and falling trip points.
The input sources are ideal, so the result is the comparator's own offset (bias mismatch only moves its tail current).
Tolerance bound |mean| + k sd with k from the sample count (serdes_flow.stats).
"""
import argparse
import importlib.util
import json
import re
import time

import numpy as np

from serdes_flow import mc, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("cmp_trip", ROOT / "analog/common/monitor/tb/cmp_trip/run.py")
tr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tr)
A, TR = 0.03, 60e-6
RESULTS = ROOT / "results/analog/common/monitor/cmp_mc"


LEAD = 5e-6          # each segment: Vn steps, inp stays at Vn - A for LEAD, then the triangle
SEG = LEAD + 2 * TR


def netlist(c, params, cms):
    """One transient per sample: segment j holds inn at cms[j] and runs one triangle on inp - inn."""
    vals = spice.corner_values(c)
    tri, vn = [], []
    for j, cm in enumerate(cms):
        t = j * SEG
        tri += [(t, -A), (t + LEAD, -A), (t + LEAD + TR, A), (t + SEG - 1e-9, -A)]
        vn += [(t, cm), (t + SEG - 1e-9, cm)]
    fmt = lambda pts: " ".join(f"{x:.9g} {y:.6g}" for x, y in pts)
    text = spice.render(tr.TEMPLATE, **vals, SECTION=f"{c.process}_mm", CMP_PARAMS=params, NCOPY=1, PWL=fmt(tri))
    text, n = re.subn(r"^Vn inn 0 .*$", f"Vn inn 0 PWL({fmt(vn)})", text, flags=re.M)
    assert n == 1
    return re.sub(r"^\.temp .*$", f".temp {c.temp}", text, flags=re.M)


def analysis(c, cms):
    h = c.supply / 2
    lines = [f"tran {TR / 3000:.4g} {len(cms) * SEG:.6g} 0 {TR / 3000:.4g}"]
    for i in range(len(cms)):
        t = i * SEG
        lines += [f"meas tran tup{i} when v(out)={h:.4f} rise=1 from={t + LEAD / 2:.6g} to={t + LEAD + TR + 1e-6:.6g}",
                  f"meas tran tdn{i} when v(out)={h:.4f} fall=1 from={t + LEAD + TR:.6g} to={t + SEG:.6g}"]
    return "\n".join(lines)


def offset_expr(i):
    """Static offset from the two crossing times of segment i (see cmp_trip.read)."""
    t = i * SEG
    up = f"(-{A}+{2 * A}*(tup{i}-{t + LEAD:.9g})/{TR})"
    dn = f"({A}-{2 * A}*(tdn{i}-{t + LEAD + TR:.9g})/{TR})"
    return f"({up}+{dn})/2"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27,ss_v1650_t-40,ff_v1950_t85,sf_v1650_t-40,fs_v1650_t85")
    ap.add_argument("--cms", default="0.9,1.3")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--cmp-params", default="")
    a = ap.parse_args()
    cms = [float(x) for x in a.cms.split(",")]
    lets = {f"off{i}": offset_expr(i) for i, cm in enumerate(cms)}
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, owners = [], []
    for p in a.points.split(","):
        c = Condition.parse(p)
        net = netlist(c, a.cmp_params, cms)
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis=analysis(c, cms), lets=lets, t_end=len(cms) * SEG), camp / p / f"chunk{k:02d}",
                         dict(timeout_s=600 + 30 * n, meta=dict(point=p, samples=n, seed=s))))
            owners.append(p)
    dirs = mc.run_many(jobs, workers=a.workers)
    out = {}
    print(f"comparator offset (trip - Vcm), mV: mean / sd / |mean| + k sd")
    for p in a.points.split(","):
        rows = mc.read_all([d for d, o in zip(dirs, owners) if o == p])
        kf = stats.k_factor(len(rows))
        res = {}
        for i, cm in enumerate(cms):
            x = np.array([r[f"off{i}"] for r in rows], float)
            x = x[np.isfinite(x)]
            res[str(cm)] = dict(n=int(len(x)), mean=float(x.mean()), sd=float(x.std(ddof=1)), bound=float(abs(x.mean()) + kf * x.std(ddof=1)))
        out[p] = dict(samples=len(rows), k=kf, cm=res)
        print(f"  {p:16s} n {len(rows):3d} k {kf:.2f} | " + " | ".join(
            f"cm {cm}: {res[str(cm)]['mean'] * 1e3:+.2f} / {res[str(cm)]['sd'] * 1e3:.2f} / {res[str(cm)]['bound'] * 1e3:.2f}" for cm in cms), flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
