"""Loop re-selection with the supply constraint (PLL closure step 7, option 2): CP current, Rz, Ci, a control-node
capacitor to ground and the Ci split, such that the worst phase margin and the 20 MHz supply sensitivity both hold.

    uv run python analog/pll/top/theory/loop_psrr.py [--ks 4,6,8] [--pm-min 52] [--k-max 120e6] [--top 4]

Phase margin: loop_design.py's plant set (every condition x RC section x usable code, LF sections incl. hl / lh,
2 ns PFD delay), control node = VCO input (--ctrl-load) + precharge gate (--c-pre) + CP output (--c-cp at k = 4,
scaled with k) + dC.  Supply: supply_split.py's two-node model at --freq, Cp and Cpv per stress point fitted to the
measured splits (12 / 6, 11 / 7, 23 / 36); the CP-output change from k = 4 is added to Cp, half of it to VDD.  Kg and
Kl (the VCO's own supply and control-line gains) do not depend on the loop.  The split is searched in steps of
1 / --units of Ci.  Noise: loop_design.jitter on its seven noise corners (PLL rms 10 kHz .. 1 GHz, before the CDR).

Feasible: PM min >= --pm-min, |K| max <= --k-max over the fitted points.  Printed per k: the smallest total
capacitance (Ci + dC) whose worst rms is within --rms-slack of the best feasible one, and the largest PM; the current
loop (k 4, Rz 4.13 k, Ci 18.38 p, no dC, 24 / 36 and 23 / 36) for reference.  Model limits: Kg, Kl and Cp come
from the seven stress points only (the other 38 conditions are not fitted); the CP output C at k != 4 is scaled, not
measured; capture, precharge and CP headroom with the new values are not checked here.
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow.project import ROOT


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


ss = _load("supply_split", "analog/pll/top/theory/supply_split.py")
ld = _load("loop_design", "analog/pll/top/theory/loop_design.py")
OUT = ROOT / "results/analog/pll/top/loop_psrr"
CTRL_LOAD = "results/analog/pll/vco/ctrl_load/20261108T011936Z"
SPLITS = f"{ss.OTHER},results/analog/pll/vco/psrr_lf/20261109T192257Z:{23 / 36:.6f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ks", default="4,6,8")
    ap.add_argument("--pm-min", type=float, default=52.0)
    ap.add_argument("--k-max", type=float, default=120e6, help="|K| bound at --freq over the fitted points, Hz/V")
    ap.add_argument("--freq", type=float, default=20e6)
    ap.add_argument("--units", type=int, default=72)
    ap.add_argument("--c-pre", type=float, default=40e-15, help="precharge gate on the control node, F")
    ap.add_argument("--c-cp", type=float, default=110e-15, help="CP output on the control node at k = 4, F (scaled with k)")
    ap.add_argument("--ctrl-load", default=CTRL_LOAD)
    ap.add_argument("--base", default=ss.BASE)
    ap.add_argument("--other", default=SPLITS)
    ap.add_argument("--delay", type=float, default=2e-9)
    ap.add_argument("--floor", type=float, default=-125.0)
    ap.add_argument("--rms-slack", type=float, default=0.05)
    ap.add_argument("--top", type=int, default=4)
    a = ap.parse_args()
    base = json.loads((ROOT / a.base / "summary.json").read_text())["rows"]
    others = [(json.loads((ROOT / c / "summary.json").read_text())["rows"], float(x)) for c, x in (s.rsplit(":", 1) for s in a.other.split(","))]
    fits = ss.fit(base, others, a.freq)
    extra = lambda k: a.c_pre + a.c_cp * k / 4
    print(f"supply model: {len(fits)} points fitted (residual <= {max(v['resid'] for v in fits.values()):.4f}); control node extra "
          + ", ".join(f"k {k} {extra(float(k)) * 1e15:.0f} fF" for k in a.ks.split(",")), flush=True)

    def kmax(k, rz, ci, dc, alpha):
        d = extra(k) - extra(4)
        return max(abs(v["kg"] + ss.transfer(a.freq, alpha, v["cp"] + d, v["cpv"] + d / 2, v["rz"] * rz / ss.RZ, v["ci"] * ci / ss.CI, dc) * v["kl"])
                   for v in fits.values())

    f = np.logspace(5, np.log10(3e8), 320)
    rzs, cis, dcs = np.geomspace(1.5e3, 6e3, 16), np.geomspace(10e-12, 60e-12, 16), (0.0, 0.1e-12, 0.2e-12)
    camp = OUT / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    result = {}
    for k in (float(x) for x in a.ks.split(",")):
        cload = ld.CtrlLoad(a.ctrl_load, extra(k))
        p = ld.plants(ld.WORKMAP, ld.CPWIN, 1.0, 0.39, cload)
        nz = ld.noise_inputs(a.floor, cload)

        def row(rz, ci, dc, alpha=None):
            ugb, pm = ld.margins(p, k, rz, ci, dc, a.delay, f)
            r = dict(rz=rz, ci=ci, dc=dc, pm_min=float(pm.min()), pm_min_d25=float((pm - 360 * ugb * 0.5e-9).min()),
                     ugb=[float(ugb.min()), float(ugb.max())], worst_pm=p["label"][int(np.argmin(pm))])
            if alpha is None:
                r["k_max"], n = min((kmax(k, rz, ci, dc, n / a.units), n) for n in range(a.units // 2, a.units))
                r["split"] = f"{n}/{a.units}"
            else:
                r["k_max"], r["split"] = kmax(k, rz, ci, dc, alpha), f"{alpha:.4f}"
            return r

        def with_rms(r):
            j = ld.jitter(nz, k, r["rz"], r["ci"], r["dc"], a.delay)
            return dict(r, rms_worst=max(j.values()), cap_pf=(r["ci"] + r["dc"]) * 1e12)

        rows = [row(rz, ci, dc) for rz in rzs for ci in cis for dc in dcs]
        feas = [with_rms(r) for r in rows if r["pm_min"] >= a.pm_min and r["k_max"] <= a.k_max]
        ref = [with_rms(row(ss.RZ, ss.CI, 0.0, n / 36)) for n in (24, 23)] if k == 4 else []
        print(f"\nk={k:g} (Icp {ld.ICP0 * k * 1e6:.0f} uA): {len(feas)}/{len(rows)} loops with PM min >= {a.pm_min} and |K| <= {a.k_max / 1e6:.0f} MHz/V")
        out = dict(feasible=len(feas), reference=ref)
        if feas:
            best = min(r["rms_worst"] for r in feas)
            out["smallest"] = sorted((r for r in feas if r["rms_worst"] <= best * (1 + a.rms_slack)), key=lambda r: r["cap_pf"])[:a.top]
            out["margin"] = sorted(feas, key=lambda r: -r["pm_min"])[:a.top]
            out["best_rms_ps"] = best * 1e12
        print(f"  {'':9s} {'Rz k':>5s} {'Ci p':>5s} {'dC p':>4s} {'split':>6s} {'UGB MHz':>10s} {'PM':>5s} {'+0.5ns':>6s} {'|K| max':>7s} {'rms ps':>6s}  worst PM")
        for tag in ("reference", "smallest", "margin"):
            for r in out.get(tag, []):
                print(f"  {tag:9s} {r['rz'] / 1e3:5.2f} {r['ci'] * 1e12:5.1f} {r['dc'] * 1e12:4.1f} {r['split']:>6s} {r['ugb'][0] / 1e6:4.1f}-{r['ugb'][1] / 1e6:4.1f} "
                      f"{r['pm_min']:5.1f} {r['pm_min_d25']:6.1f} {r['k_max'] / 1e6:7.1f} {r['rms_worst'] * 1e12:6.2f}  {r['worst_pm']}", flush=True)
        result[f"{k:g}"] = out
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), fits={k: dict(cp=v["cp"], cpv=v["cpv"]) for k, v in fits.items()}, result=result), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
