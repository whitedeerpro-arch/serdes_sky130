"""VCO phase impulse response at its noise sites.

    uv run python analog/pll/vco/tb/phase_noise/isf.py [--cond tt_v1800_t27] [--vctrl 1.205] [--code 5]
        [--sites rp,mp,mt] [--charge 0.5e-15] [--phases 32] [--every 10] [--period 0.5e-9] [--cover 1.25] [--workers 1]

One transient per site (tb_vco_isf_ngspice.cir.in): a charge pulse every `every` periods + `cover`/`phases` of a
period, serdes_flow.pnoise.impulse_response.  Sites of stage 0, by symmetry the same in every stage (the n
side half a cycle later):
  rp  load: vdd -> v0p     mp  input device: v0p -> tail     mt  tail device: tail -> vss
--period must be the ring's real period: `every` periods of error move the sweep, 0.1 % at every 10 is 5 ps a pulse
against a 19.5 ps step, and a ring slower than --period sweeps less than the cycle.  So the nominal sweep is
--cover cycles, and a largest gap in the phases above 0.08 of the cycle stops the run: the mean and rms over the
cycle interpolate across it.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, pnoise, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_vco_isf_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/vco/phase_noise_isf"
SITES = {"rp": ("vdd", "v0p"), "mp": ("v0p", "xvco.x0.tail"), "mt": ("xvco.x0.tail", "0")}
LVT = "msky130_fd_pr__nfet_01v8_lvt"
REG = "msky130_fd_pr__nfet_01v8"
PROBES = {"mp": [f"@m.xvco.x0.xmp.{LVT}[gm]", f"@m.xvco.x0.xmp.{LVT}[id]"],
          "mt": [f"@m.xvco.x0.xtail.{REG}[gm]", f"@m.xvco.x0.xtail.{REG}[id]"], "rp": []}
SETTLE = 8e-9
TSTEP = "1p"


def finish(text, c, real, rpdk, camp):
    """Real bias and PDK resistors, as in the RX benches."""
    if real:
        text = bias.real(text)
    if rpdk:
        camp.mkdir(parents=True, exist_ok=True)
        text = bias.section(rcorner.to_pdk(text, camp), c.process, rpdk)
    return text


def deck(c, site, vctrl, code, period, every, phases, charge, real=False, rpdk=None, camp=None, settle=SETTLE, cover=1.25):
    a, b = SITES[site]
    spacing = every * period + cover * period / phases
    stop = settle + (phases + 2) * spacing
    pwl, centres = pnoise.pulse_train(settle, spacing, phases + 1, charge)
    inject = f"Iinj {a} {b} {pwl}"
    cfg = {f"CFG{k}": (c.supply if (code >> k) & 1 else 0) for k in range(3)}
    text = spice.render(TEMPLATE, **spice.corner_values(c), VCTRL=vctrl, INJECT=inject, PROBES=" ".join(PROBES[site]), TSTEP=TSTEP,
                        STOP=f"{stop:.5e}", SAVE_FROM=f"{settle - 3e-9:.5e}", OUT=f"{site}.raw", **cfg)
    return finish(text, c, real, rpdk, camp), centres


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--vctrl", type=float, default=1.205)
    ap.add_argument("--code", type=int, default=5)
    ap.add_argument("--sites", default="rp,mp,mt")
    ap.add_argument("--charge", type=float, default=0.5e-15)
    ap.add_argument("--phases", type=int, default=32)
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--period", type=float, default=0.5e-9)
    ap.add_argument("--cover", type=float, default=1.25)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--tag", default="")
    ap.add_argument("--bias", default="ideal", choices=("ideal", "real"))
    ap.add_argument("--rpdk", choices=("tt", "ll", "hh"))
    ap.add_argument("--settle", type=float, default=SETTLE, help="before the first pulse; a weak corner's amplitude takes > 8 ns")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    sites = a.sites.split(",")
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{c.tag}{a.tag}")
    jobs, cents = [], {}
    for s in sites:
        text, cents[s] = deck(c, s, a.vctrl, a.code, a.period, a.every, a.phases, a.charge, a.bias == "real", a.rpdk, camp, a.settle, a.cover)
        jobs.append((text, camp / s, dict(timeout_s=7200, meta=dict(condition=c.tag, site=s, vctrl=a.vctrl, code=a.code, charge=a.charge))))
    t0 = time.time()
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}", flush=True)
    out = dict(condition=c.tag, vctrl=a.vctrl, code=a.code, charge=a.charge, every=a.every, bias=a.bias, rpdk=a.rpdk, settle=a.settle, sites={})
    for s in sites:
        w = spice.Waves(camp / s / f"{s}.raw")
        imp = pnoise.impulse_response(w.t, w["v(v0p)"] - w["v(v0n)"], cents[s], a.charge)
        sel = w.t > w.t[-1] - 3e-9
        gap = float(np.max(np.diff(np.r_[imp.x, imp.x[0] + 1])))
        out["sites"][s] = dict(x=imp.x.tolist(), h=imp.h.tolist(), period=imp.period, gap=gap, h_rms=float(np.sqrt(pnoise.white_coefficient(imp))),
                               h_mean=pnoise.slow_coefficient(imp), swing=float(np.ptp((w["v(v0p)"] - w["v(v0n)"])[sel])))
        o = out["sites"][s]
        print(f"{s}: f0 {1e-9 / imp.period:.4f} GHz, {len(imp.x)} points, h rms {o['h_rms']:.4e} mean {o['h_mean']:+.4e} rad/C, peak {np.max(np.abs(imp.h)):.3e}, largest gap {gap:.3f}, swing {o['swing'] * 1e3:.0f} mVpp", flush=True)
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    worst = max(o["gap"] for o in out["sites"].values())
    if worst > 0.08:
        raise RuntimeError(f"{camp.relative_to(ROOT)}: phase gap {worst:.3f} of the cycle; set --period to the real period")
    print(f"{time.time() - t0:.0f} s", camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
