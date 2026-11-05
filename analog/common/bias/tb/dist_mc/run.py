"""Bias distribution under local mismatch (Monte Carlo, operating point): what the module sees.

    uv run python analog/common/bias/tb/dist_mc/run.py [--samples 200] [--temps 27] [--workers 3]

Deck of tb/dist_pvt (bandgap -> PMOS copies -> module diodes, swing proxy of a CML half circuit with
a high_po load), library section tt_mm.  The reference error common to all modules (iref, vbg) is
removed by the r_ref trim at test; what stays per module is the copy-to-reference ratio and the
diode-to-tail mismatch.  Reported per quantity: sigma of the deviation from the nominal (no mismatch)
value, total and normalised to the sample's own reference current (post-trim).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

TEMPLATE = ROOT / "analog/common/bias/tb/dist_pvt/tb_bias_dist_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/bias/dist_mc"
LETS = {"vbg": "v(vbg)", "iref": "i(Vi0)", "i_cml": "i(Vmcml)", "i_ctle": "i(Vmctle)", "i_cp": "i(Vmcp)",
        "swing": "1.0-v(dr)", "v_cml": "v(vcml)", "vbn": "v(vbn)", "vbp": "v(vbp)", "i_tail": "(1.0-v(dr))"}


def netlist(section, temp):
    return spice.render(TEMPLATE, **spice.corner_values(Condition("tt", 1.8, temp)), SECTION=section)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--temps", default="27")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--reuse", help="resume the same campaign with unchanged inputs, seeds and sample count")
    a = ap.parse_args()
    temps = [int(x) for x in a.temps.split(",")]
    camp = ROOT / a.reuse if a.reuse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = []
    for t in temps:
        jobs.append((mc.deck(netlist("tt", t), 1, seed=a.seed, lets=LETS), camp / f"nominal_t{t}", dict(timeout_s=600)))
        for k, s, n in mc.chunks(a.samples, a.seed, per=40):          # ngspice leaks per sample; 100 ran out of memory
            jobs.append((mc.deck(netlist("tt_mm", t), n, seed=s, lets=LETS), camp / f"mc_t{t}_c{k:02d}", dict(timeout_s=1800)))
    resolved = dict(zip((j[1] for j in jobs), mc.run_many(jobs, workers=a.workers)))
    out = dict(samples=a.samples, temps=temps, per_temp={})
    for t in temps:
        nom = mc.read(resolved[camp / f"nominal_t{t}"])[0]
        rows = mc.read_all([resolved[j[1]] for j in jobs if j[1].name.startswith(f"mc_t{t}_c")])
        d = {k: mc.column(rows, k) for k in LETS}
        trim = d["iref"] / nom["iref"]          # the per-chip reference error the trim removes
        res = {}
        print(f"T {t} C, {len(d['iref'])} samples (sigma in % of nominal; post-trim = divided by the sample's iref error):")
        for k in ("iref", "i_cml", "i_ctle", "i_cp", "swing"):
            tot = (d[k] / nom[k] - 1) * 100
            post = (d[k] / nom[k] / trim - 1) * 100
            res[k] = dict(nominal=nom[k], total=stats.summary(tot), post_trim=stats.summary(post), post_trim_tol3=list(stats.tolerance(post)))
            print(f"  {k:7s} nominal {nom[k]:.4g}: sigma {res[k]['total']['std']:.2f} %, post-trim {res[k]['post_trim']['std']:.2f} %"
                  f" (3-sigma {res[k]['post_trim_tol3'][0]:+.2f}..{res[k]['post_trim_tol3'][1]:+.2f} %)")
        for k in ("v_cml", "vbn", "vbp"):
            x = (d[k] - nom[k]) * 1e3
            res[k] = dict(nominal=nom[k], dev_mv=stats.summary(x))
            print(f"  {k:7s} nominal {nom[k]:.4f} V: sigma {res[k]['dev_mv']['std']:.2f} mV")
        out["per_temp"][t] = res
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
