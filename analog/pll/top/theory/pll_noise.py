"""PLL output phase noise and rms jitter vs loop bandwidth, from the VCO's L(f) (vco_pn.py).

    uv run python analog/pll/top/theory/pll_noise.py --vco <isf campaign> --cpn <cp noise campaign> --bias <dist_noise campaign>
        [--floor -125] [--kvco 519e6] [--kb 2.97e9] [--duty 0.11] [--rc-fc 1e6 --rc-r 32e3]

Linear model (serdes_flow.pnoise.Loop): the VCO and its bias line are high-passed by the loop, the in-band floor
(reference, PFD, divider, at the output) and CP low-passed.  The bandwidth sweep keeps Rz and the pole / zero
ratios, so the crossing scales with Icp and the capacitors with 1 / k; CP current noise scales with k (same current
density).  Integration 10 kHz .. 1 GHz: the rms jitter of the 2 GHz clock.  --hp adds a first-order high-pass (a
CDR's tracking) to the integration.
"""
import argparse
import json

import numpy as np

from serdes_flow import pnoise
from serdes_flow.project import ROOT

UI = 250e-12
T = 300.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vco", required=True)
    ap.add_argument("--floor", type=float, default=-125.0, help="in-band L at the output from reference + PFD + divider, dBc/Hz")
    ap.add_argument("--cpn", required=True, help="cp/tb/noise campaign, 50 uA")
    ap.add_argument("--bias", required=True, help="dist_noise campaign")
    ap.add_argument("--bias-cond", default="tt_v1800_t27")
    ap.add_argument("--no-bias", action="store_true", help="leave the bias line out (a noiseless reference)")
    ap.add_argument("--duty", type=float, default=0.11, help="CP on time / reference period: UP and DN pulse width 445 ps of 4 ns")
    ap.add_argument("--kvco", type=float, default=519e6)
    ap.add_argument("--kb", type=float, default=2.97e9, help="VCO df / dVbias, Hz/V (slow.py --site bias)")
    ap.add_argument("--rc-fc", type=float, default=0.0, help="RC filter corner on the VCO's bias line, Hz")
    ap.add_argument("--rc-r", type=float, default=0.0, help="its series resistor, ohm")
    ap.add_argument("--hp", type=float, default=0.0, help="first-order high-pass corner in the integration, Hz")
    ap.add_argument("--scales", default="1,1.5,2,3,4,6,8")
    ap.add_argument("--tag", default="base", help="pll_noise_<tag>.json next to phase_noise.json")
    a = ap.parse_args()
    pn = json.loads((ROOT / a.vco / "phase_noise.json").read_text())
    f_v, l_v = np.array(pn["offsets"]), np.array(pn["total"])
    f0 = pn["f0"]
    f = np.logspace(4, 9, 1001)
    ext = f > f_v[-1]
    l_vco = 10 ** np.interp(np.log10(f), np.log10(f_v), np.log10(l_v))
    l_vco[ext] = l_v[-1] * (f_v[-1] / f[ext]) ** 2
    base = pnoise.Loop(kvco=a.kvco)
    cp = json.loads((ROOT / a.cpn / "summary.json").read_text())["cases"]["real"]
    s_cp = np.exp(np.interp(np.log(f), np.log(cp["f"]), np.log(cp["s"])))
    cp_seen = pnoise.cp_sampled_psd(f, s_cp, a.duty)
    b = json.loads((ROOT / a.bias / "summary.json").read_text())["conditions"][a.bias_cond]["vcml"]
    s_b = np.exp(np.interp(np.log(f), np.log(b["f"]), np.log(np.array(b["v"]) ** 2)))
    l_bias = None if a.no_bias else pnoise.bias_line_l(f, s_b, a.kb, a.rc_fc or None, a.rc_r, T)
    hp = (f / a.hp) ** 2 / (1 + (f / a.hp) ** 2) if a.hp else 1.0
    print(f"f0 {f0 / 1e9:.3f} GHz, floor {a.floor} dBc/Hz, CP duty {a.duty}, Kvco {a.kvco / 1e6:.0f} MHz/V, Kb {a.kb / 1e9:.2f} GHz/V, bias RC fc {a.rc_fc / 1e6:.2f} MHz R {a.rc_r / 1e3:.0f} k, high-pass {a.hp / 1e6:.2f} MHz")
    print(f"{'k':>4s} {'Icp uA':>7s} {'Ci pF':>6s} {'Cf pF':>6s} {'UGB MHz':>8s} {'PM deg':>7s} | {'rms ps':>7s} {'UI rms':>7s} {'14.07 sigma UI':>14s} | contribution ps: VCO / bias / floor / CP / Rz")
    rows = []
    for k in (float(x) for x in a.scales.split(",")):
        lp = pnoise.scaled_loop(base, k)
        ugb, pm = lp.unity_gain()
        o = pnoise.synthesize(f, lp, l_vco, a.floor, cp_seen * k, t=T, l_bias=l_bias)
        rms = {n: pnoise.rms_jitter(f, v * hp, f0) for n, v in o.items()}
        rows.append(dict(k=k, icp=lp.icp, ci=lp.ci, cf=lp.cf, ugb=ugb, pm=pm, rms=rms, total=o["total"].tolist()))
        print(f"{k:4.1f} {lp.icp * 1e6:7.0f} {lp.ci * 1e12:6.1f} {lp.cf * 1e12:6.2f} {ugb / 1e6:8.2f} {pm:7.1f} | {rms['total'] * 1e12:7.3f} {rms['total'] / UI:7.4f} {14.07 * rms['total'] / UI:14.3f} | "
              f"{rms['VCO'] * 1e12:.2f} / {rms.get('bias line', 0.0) * 1e12:.2f} / {rms['reference, PFD, divider'] * 1e12:.2f} / {rms['CP'] * 1e12:.2f} / {rms['loop filter Rz'] * 1e12:.2f}")
    (ROOT / a.vco / f"pll_noise_{a.tag}.json").write_text(json.dumps(dict(f=f.tolist(), f0=f0, floor=a.floor, cpn=a.cpn, bias=a.bias, duty=a.duty, kvco=a.kvco, kb=a.kb, rc_fc=a.rc_fc, rc_r=a.rc_r, hp=a.hp, rows=rows)))


if __name__ == "__main__":
    main()
