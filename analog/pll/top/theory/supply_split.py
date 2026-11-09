"""Supply tone to the VCO through the k = 4 loop filter: fit the control node, then search the Ci split and an added
control-node capacitor (PLL closure step 7).

    uv run python analog/pll/top/theory/supply_split.py [--base C,...] [--other C:alpha,...] [--freq 20e6]
        [--units 36] [--dcs 0,50e-15,100e-15,200e-15,300e-15] [--gate 150e6]

Network at the tone frequency (VDD = 1, small signal): node z carries Ci split into alpha Ci to VDD and (1 - alpha) Ci
to ground; Rz joins z to the control node, whose own capacitance Cp (VCO input, CP output, precharge gate) has the part
Cpv referenced to VDD.  vctrl / vdd = H(alpha, Cp, Cpv), and the VCO's frequency moves by K = K_gnd + H (K_vdd - K_gnd),
with K_gnd / K_vdd the ideal-control variants of analog/pll/vco/tb/psrr_lf (control fixed / carrying the tone).
Per point Cp and Cpv are fitted to the lf runs of the base campaigns (gnd, vdd and the 12 / 6 filter; rows of several
campaigns are merged) and of every --other campaign (its alpha given); a point needs gnd, vdd and at least one lf run
(one split determines Cp and Cpv exactly, more give a residual); Rz and Ci are the nominal values times the RC section and temperature factors of
docs/design/pll_loop.md.  Printed: the fit (and its residual), then |K| per point for every split n / --units and
added control-to-ground capacitor dC.  dC is a loop-filter Cf: its phase-margin cost comes from loop_design.py
--evaluate with --c-extra.  Points without gnd / vdd runs (FF cold failed at the first step) are left out.
"""
import argparse
import json

import numpy as np
from scipy.optimize import least_squares

from serdes_flow.project import ROOT

BASE = "results/analog/pll/vco/psrr_lf/20261109T145047Z"
OTHER = "results/analog/pll/vco/psrr_lf/20261109T180645Z:0.6111"
RZ, CI, ALPHA0 = 4.13e3, 18.38e-12, 12 / 18
R_RC = {"tt": 1.0, "hh": 1.154, "ll": 0.846}          # 7.508 / 6.508 and 5.508 / 6.508 k at 27 C
C_RC = {"tt": 1.0, "hh": 1.123, "ll": 0.880}          # 44.93 / 40 and 35.21 / 40 pF
R_T = {-40: 0.973, 27: 1.0, 85: 1.0317}               # 6.332 / 6.508 and 6.714 / 6.508 k


def transfer(f, alpha, cp, cpv, rz, ci, dc=0.0):
    """vctrl / vdd: nodes z (Ci split) and ctrl (Cp, Cpv of it to VDD, dC to ground), Rz between them."""
    s = 2j * np.pi * f
    m = np.array([[-s * ci - 1 / rz, 1 / rz], [1 / rz, -1 / rz - s * (cp + dc)]])
    b = np.array([-s * alpha * ci, -s * cpv])
    return np.linalg.solve(m, b)[1]


def rows(campaigns):
    """summary.json rows of one or more psrr_lf campaigns (comma separated), merged."""
    out = {}
    for c in filter(None, campaigns.split(",")):
        out.update(json.loads((ROOT / c / "summary.json").read_text())["rows"])
    return out


def k_of(row):
    return complex(row["k_real"], row["k_quad"])


def fit(base, others, f):
    tag = f"{f / 1e6:g}M"
    out = {}
    for key in sorted(k[: -len(f":gnd_{tag}")] for k in base if k.endswith(f":gnd_{tag}")):
        if f"{key}:vdd_{tag}" not in base:
            continue
        cond, rc = key.split(":")
        t = int(cond.split("_t")[1])
        rz, ci = RZ * R_RC[rc] * R_T[t], CI * C_RC[rc]
        kg = k_of(base[f"{key}:gnd_{tag}"])
        kl = k_of(base[f"{key}:vdd_{tag}"]) - kg
        meas = [(ALPHA0, (k_of(base[f"{key}:lf_{tag}"]) - kg) / kl)] if f"{key}:lf_{tag}" in base else []
        meas += [(a, (k_of(rows[f"{key}:lf_{tag}"]) - kg) / kl) for rows, a in others if f"{key}:lf_{tag}" in rows]
        if not meas:
            continue

        def res(x):
            e = [transfer(f, a, x[0] * 1e-12, x[1] * 1e-12, rz, ci) - h for a, h in meas]
            return [v for z in e for v in (z.real, z.imag)]
        r = least_squares(res, [0.5, 0.4], bounds=([0, 0], [5, 5]))
        out[key] = dict(cp=r.x[0] * 1e-12, cpv=r.x[1] * 1e-12, rz=rz, ci=ci, kg=kg, kl=kl, resid=float(np.abs(r.fun).max()), n=len(meas))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE, help="psrr_lf campaigns (comma separated) with gnd, vdd and lf runs of the 12 / 6 filter")
    ap.add_argument("--other", default=OTHER, help="campaign:alpha of lf runs with another split (comma separated)")
    ap.add_argument("--freq", type=float, default=20e6)
    ap.add_argument("--units", type=int, default=36)
    ap.add_argument("--dcs", default="0,50e-15,100e-15,150e-15,200e-15,300e-15")
    ap.add_argument("--gate", type=float, default=150e6)
    a = ap.parse_args()
    base = rows(a.base)
    others = []
    for spec in filter(None, a.other.split(",")):
        c, alpha = spec.rsplit(":", 1)
        others.append((json.loads((ROOT / c / "summary.json").read_text())["rows"], float(alpha)))
    fits = fit(base, others, a.freq)
    print(f"fit at {a.freq / 1e6:g} MHz (Cp total on the control node, Cpv of it to VDD; residual in units of H)")
    for k, v in fits.items():
        print(f"  {k:20s} Cp {v['cp'] * 1e15:4.0f} fF  Cpv {v['cpv'] * 1e15:4.0f} fF  beta {v['cpv'] / v['cp']:.2f}  "
              f"Rz {v['rz'] / 1e3:.2f} k  Ci {v['ci'] * 1e12:.1f} p  ({v['n']} splits, residual {v['resid']:.4f})")
    print(f"|K| MHz/V per point ({', '.join(k.split(':')[0] for k in fits)}); gate {a.gate / 1e6:.0f}")
    best = []
    for n in range(a.units // 2, a.units + 1):
        for dc in (float(x) for x in a.dcs.split(",")):
            ks = [abs(v["kg"] + transfer(a.freq, n / a.units, v["cp"], v["cpv"], v["rz"], v["ci"], dc) * v["kl"]) for v in fits.values()]
            best.append((max(ks), n, dc, ks))
    for worst, n, dc, ks in sorted(best)[:12]:
        print(f"  {n:2d}/{a.units} ({n / a.units:.3f}) dC {dc * 1e15:3.0f} fF: " + " ".join(f"{k / 1e6:5.0f}" for k in ks) + f"  max {worst / 1e6:5.1f}")
    for worst, n, dc, ks in sorted(b for b in best if b[2] == 0)[:4]:
        print(f"  without dC: {n:2d}/{a.units} ({n / a.units:.3f}) max {worst / 1e6:5.1f}")


if __name__ == "__main__":
    main()
