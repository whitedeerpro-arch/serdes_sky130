"""Supply tone to VCO phase modulation, with the loop filter returned to ground or to VDD.

    uv run python analog/pll/vco/tb/phase_noise/psrr_tone.py --isf <isf campaign> [--freqs 20e6,50e6] [--amp 5e-3] [--periods 2]
        [--settle 12e-9] [--alphas 0,1] [--analyse <campaign>]

Free-running VCO at the ISF campaign's code and Vctrl, real bias and PDK resistors as there.  VDD carries a sine of
amplitude --amp from --settle on.  Above the loop bandwidth the loop filter's capacitors hold Vctrl against the node
they return to, so Vctrl carries alpha times the tone: alpha 0 for capacitors to ground, 1 for capacitors to VDD,
in between for capacitors split between the two in that ratio.  The set code bits follow VDD, as a CMOS driver would.

One period after the tone starts is dropped for the bias line's transient.  Over the remaining whole periods the
rising crossings are fitted with t_k = a + b k + c k^2 + A sin(w (t_k - td)) + B cos(w (t_k - td)), td = --settle.
Effective gain, as a phasor against the VDD tone: K = w f0 (B - j A) / amp (Hz/V); B > 0 means f rises with VDD (edges
early when the integral of the tone is largest).  Comparable with the DC Kvdd (alpha 0) and Kvdd + Kvco (alpha 1) from
slow.py.  With two alphas at one frequency, linearity gives the alpha that nulls K and the residual there.
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
RESULTS = ROOT / "results/analog/pll/vco/phase_noise_psrr"


def deck(c, vctrl, code, alpha, fm, amp, settle, stop, rpdk, camp):
    cfg = {f"CFG{k}": c.supply for k in range(3)}
    text = spice.render(TEMPLATE, **spice.corner_values(c), VCTRL=vctrl, INJECT="", PROBES="", TSTEP="1p", STOP=f"{stop:.5e}",
                        SAVE_FROM=f"{settle:.5e}", OUT="tone.raw", **cfg)
    rep = {f"Vdd vdd 0 {c.supply}": f"Vdd vdd 0 DC {c.supply} SIN({c.supply} {amp:.5e} {fm:.5e} {settle:.5e})"}
    for k in range(3):                                         # a set bit is tied to VDD, a clear bit to ground
        old = f"Vb{k} cfg{k} 0 {c.supply}"
        rep[old] = f"Vb{k} cfg{k} vdd 0" if (code >> k) & 1 else f"Vb{k} cfg{k} 0 0"
    if alpha:
        # the tone from ground, not a source stacked on VDD: the stacked form stops at t = 10 fs on a varactor node
        rep[f"Vctrl ctrl 0 {vctrl}"] = f"Vctrl ctrl 0 DC {vctrl} SIN({vctrl} {alpha * amp:.5e} {fm:.5e} {settle:.5e})"
    for old, new in rep.items():
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    camp.mkdir(parents=True, exist_ok=True)
    return bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, rpdk)


def fit(run_dir, fm, td):
    """Phasor gain terms of one deck; first period after the tone's start td dropped."""
    t0 = td + 1 / fm
    w = spice.Waves(run_dir / "tone.raw")
    e, p = crossings(w.t, w["v(v0p)"] - w["v(v0n)"])
    r = e[p > 0]
    n = int((r[-1] - t0) * fm)                                 # whole periods only
    r = r[(r >= t0) & (r <= t0 + n / fm)]
    k = np.arange(len(r), dtype=float)
    w0 = 2 * np.pi * fm * (r - td)
    a = np.column_stack((np.ones_like(k), k, k * k, np.sin(w0), np.cos(w0)))
    x, *_ = np.linalg.lstsq(a, r, rcond=None)
    res = r - a @ x
    return dict(f0=float(1 / x[1]), sin=float(x[3]), cos=float(x[4]), residual=float(res.std()), periods=n, edges=len(r))


def name(alpha, fm):
    return {0.0: "gnd", 1.0: "vdd"}.get(alpha, f"a{alpha:g}") + f"_{fm / 1e6:g}M"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--isf", required=True)
    ap.add_argument("--freqs", default="20e6,50e6")
    ap.add_argument("--amp", type=float, default=5e-3)
    ap.add_argument("--periods", type=int, default=2, help="periods analysed, after one dropped")
    ap.add_argument("--settle", type=float, default=12e-9)
    ap.add_argument("--alphas", default="0,1")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--tag", default="")
    ap.add_argument("--analyse", help="an existing campaign: fit its waves, simulate nothing")
    a = ap.parse_args()
    isf = json.loads((ROOT / a.isf / "summary.json").read_text())
    c = Condition.parse(isf["condition"])
    rpdk = isf["rpdk"]
    camp = ROOT / a.analyse if a.analyse else RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{c.tag}_r{rpdk}{a.tag}")
    freqs = [float(x) for x in a.freqs.split(",")]
    alphas = [float(x) for x in a.alphas.split(",")]
    plan = [(al, fm) for fm in freqs for al in alphas]
    if not a.analyse:
        jobs = []
        for al, fm in plan:
            stop = a.settle + (a.periods + 1) / fm + 1e-9
            jobs.append((deck(c, isf["vctrl"], isf["code"], al, fm, a.amp, a.settle, stop, rpdk, camp), camp / name(al, fm),
                         dict(timeout_s=7200, meta=dict(alpha=al, fm=fm, amp=a.amp))))
        for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
            if not ex.ok:
                print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}", flush=True)
    out, phasor = {}, {}
    print(f"{c.tag} R {rpdk}, code {isf['code']}, Vctrl {isf['vctrl']}: tone {a.amp * 1e3:.1f} mV on VDD; K in MHz/V")
    print(f"{'alpha':>5s} {'f MHz':>6s} {'f0 GHz':>8s} {'dev ps':>7s} {'resid ps':>8s} {'K real':>8s} {'K quad':>8s} {'|K|':>7s}")
    for al, fm in plan:
        q = fit(camp / name(al, fm), fm, a.settle)
        k = 2 * np.pi * fm * q["f0"] * (q["cos"] - 1j * q["sin"]) / a.amp
        q.update(alpha=al, fm=fm, k_real=float(k.real), k_quad=float(k.imag))
        out[name(al, fm)] = q
        phasor[(al, fm)] = k
        print(f"{al:5.2f} {fm / 1e6:6.1f} {q['f0'] / 1e9:8.4f} {np.hypot(q['sin'], q['cos']) * 1e12:7.2f} {q['residual'] * 1e12:8.3f} "
              f"{k.real / 1e6:8.1f} {k.imag / 1e6:8.1f} {abs(k) / 1e6:7.1f}", flush=True)
    null = {}
    if len(alphas) >= 2:
        for fm in freqs:
            k0, k1 = phasor[(alphas[0], fm)], phasor[(alphas[1], fm)]
            slope = (k1 - k0) / (alphas[1] - alphas[0])                  # dK / dalpha, the control line's gain
            base = k0 - alphas[0] * slope
            best = float(-(base * slope.conjugate()).real / abs(slope) ** 2)
            null[f"{fm / 1e6:g}M"] = dict(alpha=best, residual=float(abs(base + best * slope)), kctl=float(abs(slope)))
            print(f"{fm / 1e6:g} MHz: control line |K| {abs(slope) / 1e6:.1f} MHz/V; null at alpha {best:.3f}, residual {abs(base + best * slope) / 1e6:.1f} MHz/V", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(isf=a.isf, amp=a.amp, settle=a.settle, results=out, null=null), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
