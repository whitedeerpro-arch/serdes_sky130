"""Check of the impulse-response method: white current noise in a transient, jitter read from the crossings.

    uv run python analog/pll/vco/tb/phase_noise/direct.py --isf <isf campaign> [--site rp] [--scale 100] [--stop 200n] [--settle 5n]

TRNOISE current sources of one-sided PSD scale * 4kT/400 ohm at every instance of a site in the ring (8 for rp /
mp, 4 for mt).  Phase noise stays small and linear while the jitter gets measurable in a few hundred periods.
The crossings give var(t[k+m] - t[k] - m T) = kappa^2 m T (a random walk), L(df) = f0^2 kappa^2 / df^2 (white
phase-noise slope), to compare with L = n (S / 2) <h^2> / (2 pi df)^2 from isf.py.  Stationary noise, so
this checks <h^2>; the bias modulation alpha(x) of the MOS sources is a separate step.  Bias and resistors as in the
ISF campaign.  --settle: crossings before it are not saved, past the amplitude's settling (about 14 ns at the hot corners).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, pnoise, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_vco_isf_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/vco/phase_noise_direct"
NT = 1e-12                # TRNOISE sample time; one-sided PSD = 2 NA^2 NT


def sites(site):
    if site == "rp":
        return [("vdd", f"v{k}{s}") for k in range(4) for s in "pn"]
    if site == "mp":
        return [(f"v{k}{s}", f"xvco.x{k}.tail") for k in range(4) for s in "pn"]
    return [(f"xvco.x{k}.tail", "0") for k in range(4)]


def deck(c, site, vctrl, code, psd, stop, seed, settle=5e-9, real=False, rpdk=None, camp=None):
    na = np.sqrt(psd / (2 * NT))
    inject = "\n".join(f"In{i} {a} {b} dc 0 trnoise({na:.5e} {NT:.2e} 0 0)" for i, (a, b) in enumerate(sites(site)))
    cfg = {f"CFG{k}": (c.supply if (code >> k) & 1 else 0) for k in range(3)}
    text = spice.render(TEMPLATE, **spice.corner_values(c), VCTRL=vctrl, INJECT=inject, PROBES="", TSTEP="1p", STOP=f"{stop:.5e}",
                        SAVE_FROM=f"{settle:.5e}", OUT="noise.raw", **cfg)
    text = text.replace("set num_threads=1\n", f"set num_threads=1\nset rndseed={seed}\n")
    if real:
        text = bias.real(text)
    if rpdk:
        camp.mkdir(parents=True, exist_ok=True)
        text = bias.section(rcorner.to_pdk(text, camp), c.process, rpdk)
    return text


def kappa(t, y, ms=(4, 8, 16, 32, 64)):
    """kappa^2 per m from the rising crossings, and the mean period."""
    e, p = crossings(t, y)
    r = e[p > 0]
    T = (r[-1] - r[0]) / (len(r) - 1)
    out = {}
    for m in ms:
        d = r[m:] - r[:-m] - m * T
        out[m] = float(np.var(d) / (m * T))
    return T, out, len(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--isf", required=True)
    ap.add_argument("--site", default="rp")
    ap.add_argument("--scale", type=float, default=100.0)
    ap.add_argument("--stop", default="200n")
    ap.add_argument("--settle", default="5n")
    ap.add_argument("--seeds", default="1,2")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    isf = json.loads((ROOT / a.isf / "summary.json").read_text())
    c = Condition.parse(isf["condition"])
    stop = spice.spice_number(a.stop)
    T_K = c.temp + 273.15
    psd = a.scale * 4 * pnoise.K_B * T_K / 400
    rpdk = isf.get("rpdk")
    real = isf.get("bias") == "real"
    settle = spice.spice_number(a.settle)
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{c.tag}_{a.site}" + (f"_r{rpdk}" if rpdk else ""))
    seeds = [int(x) for x in a.seeds.split(",")]
    jobs = [(deck(c, a.site, isf["vctrl"], isf["code"], psd, stop, s, settle, real, rpdk, camp), camp / f"s{s}", dict(timeout_s=7200, meta=dict(site=a.site, psd=psd, seed=s))) for s in seeds]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}", flush=True)
    n = len(sites(a.site))
    o = isf["sites"][a.site]
    pred_k2 = n * psd / 2 * o["h_rms"] ** 2 / (2 * np.pi) ** 2 * o["period"] ** 2
    rows = []
    for s in seeds:
        w = spice.Waves(camp / f"s{s}" / "noise.raw")
        T, k2, nr = kappa(w.t, w["v(v0p)"] - w["v(v0n)"])
        rows.append(dict(seed=s, period=T, crossings=nr, kappa2=k2))
        print(f"seed {s}: {nr} crossings, f0 {1e-9 / T:.4f} GHz, kappa^2 / predicted: " + " ".join(f"m{m} {v / pred_k2:.3f}" for m, v in k2.items()), flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(isf=a.isf, site=a.site, scale=a.scale, psd=psd, predicted_kappa2=pred_k2, rows=rows), indent=1))
    print(f"predicted kappa {np.sqrt(pred_k2):.3e} sqrt(s) at scale {a.scale}", camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
