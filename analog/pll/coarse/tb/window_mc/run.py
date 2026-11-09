"""Local-mismatch spread of the PLL Vctrl window thresholds (ladder voltages), library section <process>_mm.

    uv run python analog/pll/coarse/tb/window_mc/run.py [--points tt_v1800_t27,...] [--samples 200] [--chunk 40] [--workers 1]

Deck of window_dc (real bandgap, copies, both ladders at the run-time codes), operating point per sample: vlo and
vdd - vhi.  Mismatch moves the bandgap (vbg, r_ref), the copies and the ladder resistors; the comparators' own offset is
analog/common/monitor/tb/cmp_mc and adds in quadrature (independent devices).  Tolerance bound |mean - design| + k sd.
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

_spec = importlib.util.spec_from_file_location("window_dc", ROOT / "analog/pll/coarse/tb/window_dc/run.py")
wd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wd)
RESULTS = ROOT / "results/analog/pll/coarse/window_mc"


def netlist(c, code_lo, code_hi):
    vals = spice.corner_values(c)
    text = spice.render(wd.TEMPLATE, **vals, SECTION=f"{c.process}_mm", CODE_LO=code_lo, CODE_HI=code_hi)
    text = re.sub(r"^\.temp .*$", f".temp {c.temp}", text, flags=re.M)
    return re.sub(r"^Vz z 0 .*$", "Vz z 0 1.1", text, flags=re.M)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27,ss_v1650_t-40,ff_v1950_t85,sf_v1650_t-40,fs_v1650_t85")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=8, help="~140 MB per sample (bandgap + ladders): 40 hit the 3 GB cap at sample ~21")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--code-lo", type=int, default=5)
    ap.add_argument("--code-hi", type=int, default=3)
    ap.add_argument("--analyse", help="campaign: summarize the rows already written (truncated chunks included), no simulation")
    a = ap.parse_args()
    lets = {"vlo": "v(xw.vlo)", "drop": "v(vdd)-v(xw.vhi)"}
    camp = (ROOT / a.analyse) if a.analyse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, owners = [], []
    for p in a.points.split(","):
        c = Condition.parse(p)
        net = netlist(c, a.code_lo, a.code_hi)
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis="op", lets=lets), camp / p / f"chunk{k:02d}",
                         dict(timeout_s=600 + 10 * n, meta=dict(point=p, samples=n, seed=s))))
            owners.append(p)
    if a.analyse:
        # sample k of a chunk seed is fixed; a memory-truncated chunk keeps its first rows unchanged
        dirs = [j[1] for j in jobs]
        dirs = [d for d in dirs if (d / mc.MC_FILE).exists()]
    else:
        dirs = mc.run_many(jobs, workers=a.workers)
    out = {}
    print("thresholds (local mismatch), mV: mean - design / sd / |mean - design| + k sd")
    for p in a.points.split(","):
        c = Condition.parse(p)
        lo_d, hi_d = wd.design(a.code_lo, a.code_hi, c.supply)
        rows = mc.read_all([d for d, o in zip(dirs, owners) if o == p])
        kf = stats.k_factor(len(rows))
        res = {}
        for key, ref in (("vlo", lo_d), ("drop", c.supply - hi_d)):
            x = np.array([r[key] for r in rows], float)
            res[key] = dict(mean=float(x.mean()), sd=float(x.std(ddof=1)), bias=float(x.mean() - ref), bound=float(abs(x.mean() - ref) + kf * x.std(ddof=1)))
        out[p] = dict(samples=len(rows), k=kf, **res)
        print(f"  {p:16s} n {len(rows):3d} | vlo {res['vlo']['bias'] * 1e3:+.1f} / {res['vlo']['sd'] * 1e3:.1f} / {res['vlo']['bound'] * 1e3:.1f}"
              f" | vdd - vhi {res['drop']['bias'] * 1e3:+.1f} / {res['drop']['sd'] * 1e3:.1f} / {res['drop']['bound'] * 1e3:.1f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
