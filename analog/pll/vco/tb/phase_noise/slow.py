"""Check of the mean impulse response <h>: a DC current at a noise site shifts the frequency.

    uv run python analog/pll/vco/tb/phase_noise/slow.py --isf <isf campaign> [--site mt] [--current 2e-6] [--stop 30n]

A current I at every instance of a site (n of them) adds I T <h> of phase per period at each, so
df = n I <h> / (2 pi).  Slow noise (flicker, bias line) converts through <h>, while white noise converts through
rms(h); direct.py checks the second, this one the first.  One deck per sign of I, both from the same settling,
the frequency from the last 20 periods' rising crossings.

--site bias: an offset in series with the VCO's bias line instead (--current is then volts), df / dVbias in
Hz/V, which is what turns the bias line's noise into phase noise: all four tails move together.  --site ctrl: the same
on the varactor control line, Kvco.  --site vdd: on the supply, with the bias on its own ideal supply (the direct path
through the loads and the common mode) or with --bias real (+ the bias line, DC only: the line's filter is in dist_psrr).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_vco_isf_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/vco/phase_noise_slow"
LINES = ("bias", "ctrl", "vdd")


def sites(site):
    if site == "rp":
        return [("vdd", f"v{k}{s}") for k in range(4) for s in "pn"]
    if site == "mp":
        return [(f"v{k}{s}", f"xvco.x{k}.tail") for k in range(4) for s in "pn"]
    return [(f"xvco.x{k}.tail", "0") for k in range(4)]


def deck(c, site, vctrl, code, current, stop, real=False, rpdk=None, camp=None):
    cfg = {f"CFG{k}": (c.supply if (code >> k) & 1 else 0) for k in range(3)}
    inject = "" if site in LINES else "\n".join(f"Is{i} {a} {b} dc {current:.5e}" for i, (a, b) in enumerate(sites(site)))
    if site == "ctrl":
        vctrl += current
    text = spice.render(TEMPLATE, **spice.corner_values(c), VCTRL=vctrl, INJECT=inject, PROBES="", TSTEP="1p", STOP=f"{stop:.5e}",
                        SAVE_FROM=f"{stop - 15e-9:.5e}", OUT="dc.raw", **cfg)
    if site == "bias":
        old = "cfg2 vbias vdd 0 pll_vco_ring4_pvt_candidate"
        assert text.count(old) == 1
        text = text.replace(old, "cfg2 vbias_v vdd 0 pll_vco_ring4_pvt_candidate").replace("Xref vbias vbias 0 0", f"Vbx vbias_v vbias {current:.5e}\nXref vbias vbias 0 0")
    if site == "vdd":
        old = f"Vdd vdd 0 {c.supply}"
        assert text.count(old) == 1
        text = text.replace(old, f"Vdd vdd 0 {c.supply + current:.6f}")
    text = bias.real(text) if real else text
    if rpdk:
        camp.mkdir(parents=True, exist_ok=True)
        text = bias.section(rcorner.to_pdk(text, camp), c.process, rpdk)
    return text


def freq(camp_dir):
    w = spice.Waves(camp_dir / "dc.raw")
    e, p = crossings(w.t, w["v(v0p)"] - w["v(v0n)"])
    r = e[p > 0][-21:]
    return (len(r) - 1) / (r[-1] - r[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--isf", required=True)
    ap.add_argument("--site", default="mt")
    ap.add_argument("--current", type=float, default=2e-6)
    ap.add_argument("--stop", default="30n")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--bias", default=None, choices=("ideal", "real"), help="default: as the ISF campaign")
    a = ap.parse_args()
    isf = json.loads((ROOT / a.isf / "summary.json").read_text())
    c = Condition.parse(isf["condition"])
    stop = spice.spice_number(a.stop)
    a.bias = a.bias or isf.get("bias", "ideal")
    rpdk = isf.get("rpdk")
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{c.tag}_{a.site}_{a.bias}" + (f"_r{rpdk}" if rpdk else ""))
    signs = {"p": a.current, "z": 0.0, "n": -a.current}
    jobs = [(deck(c, a.site, isf["vctrl"], isf["code"], v, stop, a.bias == "real", rpdk, camp), camp / k, dict(timeout_s=1800, meta=dict(site=a.site, current=v))) for k, v in signs.items()]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}", flush=True)
    f = {k: freq(camp / k) for k in signs}
    measured = (f["p"] - f["n"]) / (2 * a.current)
    predicted = None
    if a.site in LINES:
        print(f"{a.site}: f {f['n'] / 1e9:.5f} / {f['z'] / 1e9:.5f} / {f['p'] / 1e9:.5f} GHz at -/0/+ {a.current * 1e3:.1f} mV; df/dV {measured:+.4e} Hz/V", flush=True)
    else:
        n = len(sites(a.site))                                     # Hz/A at all n instances
        predicted = n * isf["sites"][a.site]["h_mean"] / (2 * np.pi)
        print(f"{a.site}: f {f['n'] / 1e9:.5f} / {f['z'] / 1e9:.5f} / {f['p'] / 1e9:.5f} GHz at -/0/+ {a.current * 1e6:.1f} uA x {n}; "
              f"df/dI measured {measured:+.4e}, predicted from <h> {predicted:+.4e} Hz/A", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(isf=a.isf, site=a.site, current=a.current, f=f, measured=measured, predicted=predicted), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
