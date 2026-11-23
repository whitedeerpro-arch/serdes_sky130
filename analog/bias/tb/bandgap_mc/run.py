"""Bandgap and reference current under local mismatch (Monte Carlo, operating point) -> trim range.

    uv run python analog/bias/tb/bandgap_mc/run.py [--samples 200] [--section tt] [--temps 27,-40,85]

Same deck as tb/bandgap_pvt (nodeset for the operating point), library section <section>_mm: every
MOS and high_po resistor mismatched (the PNP model has none).  Per sample and temperature: vbg, the
reference current, I * R (high_po load, swing proxy), core and V->I amplifier input errors.
Trim range: the static per-chip error to remove is the vbg deviation from the nominal (no mismatch)
value at 27 C; the range must cover the 3-sigma tolerance interval (stats.tolerance, 95 %
confidence).  The temperature spread of each sample (vbg(85) - vbg(-40)) shows how much a single
room-temperature trim leaves.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = ROOT / "analog/bias/tb/bandgap_pvt/tb_bandgap_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/bias/bandgap_mc"
LETS = {"vcm": "v(vcm)", "vbg": "v(vbg)", "iref": "i(Vi0)", "ir": "v(i1)", "err_core": "v(xbg.ta)-v(xbg.tb)", "err_vi": "v(xbg.s)-v(vbg)"}


def netlist(section, temp, supply=1.8):
    vals = spice.corner_values(Condition("tt", supply, temp))
    return spice.render(TEMPLATE, **vals, SECTION=section)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--section", default="tt")
    ap.add_argument("--temps", default="27,-40,85")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--reuse", help="resume the same campaign with unchanged inputs, seeds and sample count")
    a = ap.parse_args()
    temps = [int(x) for x in a.temps.split(",")]
    camp = ROOT / a.reuse if a.reuse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = []
    for t in temps:
        jobs.append((mc.deck(netlist(a.section, t), 1, seed=a.seed, lets=LETS), camp / f"nominal_t{t}", dict(timeout_s=600)))
        # same seed at every temperature: sample k is the same chip at each temperature
        for k, s, n in mc.chunks(a.samples, a.seed, per=100):
            jobs.append((mc.deck(netlist(f"{a.section}_mm", t), n, seed=s, lets=LETS), camp / f"mc_t{t}_c{k:02d}", dict(timeout_s=1800)))
    resolved = dict(zip((j[1] for j in jobs), mc.run_many(jobs, workers=4)))
    out = dict(section=a.section, samples=a.samples, temps=temps, per_temp={})
    data = {}
    for t in temps:
        nom = mc.read(resolved[camp / f"nominal_t{t}"])[0]
        rows = mc.read_all([resolved[j[1]] for j in jobs if j[1].name.startswith(f"mc_t{t}_c")])
        data[t] = {k: mc.column(rows, k) for k in LETS}
        res = {}
        for k, scale in (("vcm", 1e3), ("vbg", 1e3), ("iref", 1e6), ("ir", 1e3), ("err_core", 1e3), ("err_vi", 1e3)):
            x = (data[t][k] - nom[k]) * scale
            s = stats.summary(x)
            lo, hi = stats.tolerance(x)
            res[k] = dict(nominal=nom[k], dev=s, tol3=[lo, hi])
        out["per_temp"][t] = res
        print(f"T {t:4d}: vcm nominal {nom['vcm']:.4f} V, sigma {res['vcm']['dev']['std']:.2f} mV; vbg nominal {nom['vbg']:.4f} V, sigma {res['vbg']['dev']['std']:.2f} mV (3-sigma {res['vbg']['tol3'][0]:+.1f}..{res['vbg']['tol3'][1]:+.1f} mV)"
              f"; iref sigma {res['iref']['dev']['std'] / (nom['iref'] * 1e6) * 100:.2f} %; I*R sigma {res['ir']['dev']['std'] / (nom['ir'] * 1e3) * 100:.2f} %"
              f"; core err sigma {res['err_core']['dev']['std']:.2f} mV, V->I err sigma {res['err_vi']['dev']['std']:.2f} mV")
    if 27 in data and -40 in data and 85 in data:
        tc = (data[85]["vbg"] - data[-40]["vbg"]) * 1e3
        s = stats.summary(tc)
        out["vbg_span_85_m40_mv"] = s
        corr = float(np.corrcoef(data[27]["vbg"], tc)[0, 1])
        print(f"vbg(85) - vbg(-40) per sample: mean {s['mean']:+.2f}, sigma {s['std']:.2f} mV; correlation with the 27 C error {corr:+.2f}")
    n27 = out["per_temp"].get(27)
    if n27:
        lo, hi = n27["vbg"]["tol3"]
        rng = max(abs(lo), abs(hi))
        print(f"trim: cover +-{rng:.1f} mV ({rng / (n27['vbg']['nominal'] * 1e3) * 100:.2f} % of vbg) plus the systematic PVT spread")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
