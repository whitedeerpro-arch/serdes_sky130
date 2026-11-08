"""Local mismatch Monte Carlo of the 4-bit VCO's frequency at its 2 GHz operating point.

    uv run python analog/pll/vco/tb/mc/run.py [--points tt_v1800_t27:tt,...] [--samples 200] [--chunk 25] [--seed 1] [--workers 4]

Bench of the working map (workmap.py, bank 4: pll_vco_ring4_4b, real bias, PDK R, four buffers), library section
<process>_<rc>_mm (local mismatch only).  Code and Vctrl from config/pll_code_table.json for the condition.  Per sample:
frequency from ten rising periods of v0 after 14 ns.  Reported: mean and sigma of f, sigma as a Vctrl shift (/ Kvco of
the table) and k = 3.28 (200 samples) times that: how far mismatch moves a chip's 2 GHz point.  The coarse code is chosen
per chip from its own frequency (power-up selection), so mismatch counts like a process shift of the whole curve.
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, mc, rcorner, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("vco_workmap", ROOT / "analog/pll/vco/tb/tuning/workmap.py")
wm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wm)
RESULTS = ROOT / "results/analog/pll/vco/mc"
TABLE = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
T0, STOP = 14e-9, 24e-9


def netlist(c, rc, code, vctrl, camp):
    text = spice.render(wm.TEMPLATE, **spice.corner_values(c), VCTRL=vctrl, INJECT="", PROBES="", TSTEP="2p", STOP=f"{STOP:.4e}",
                        SAVE_FROM=f"{T0 - 2e-9:.4e}", OUT="x.raw", CFG0=0, CFG1=0, CFG2=0)
    text = re.sub(r"\.control.*?\.endc\s*", "", text, flags=re.S).replace("reltol=1e-5", "reltol=1e-4")
    text = re.sub(r"^\.end\s*$", "", text, flags=re.M)
    old = "ctrl cfg0 cfg1 cfg2 vbias vdd 0 pll_vco_ring4_pvt_candidate"
    assert text.count(old) == 1
    text = text.replace(old, "ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd 0 pll_vco_ring4_4b").replace("Vb2 cfg2 0 0\n", "Vb2 cfg2 0 0\nVb3 cfg3 0 0\n")
    inc = '.include "' + str(ROOT / "analog/pll/vco/spice/vco_ring4_pvt_candidate.spice") + '"'
    assert text.count(inc) == 1
    text = text.replace(inc, inc.replace("vco_ring4_pvt_candidate", "cap_bank_4b") + "\n" + inc.replace("vco_ring4_pvt_candidate", "vco_ring4_4b"))
    for k in range(4):
        old = f"Vb{k} cfg{k} 0 0"
        assert text.count(old) == 1
        text = text.replace(old, f"Vb{k} cfg{k} 0 {c.supply if (code >> k) & 1 else 0}")
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, rc)
    sec = f"{c.process}_{rc}_mm" if rc != "tt" else f"{c.process}_mm"
    text, n = re.subn(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: m[1] + sec, text, count=1, flags=re.M | re.I)
    assert n == 1
    return text


ANALYSIS = "\n".join([f"tran 2p {STOP:.4e} {T0 - 2e-9:.4e} 2p", "let vd = v(v0p)-v(v0n)",
                      f"meas tran ta when vd=0 rise=2 from={T0:.4e}", f"meas tran tb when vd=0 rise=12 from={T0:.4e}"])
LETS = {"freq": "10/(tb-ta)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:tt,fs_v1650_t85:hh,ss_v1650_t-40:hh,ff_v1950_t-40:ll,sf_v1650_t85:hh")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, owners = [], []
    for spec in a.points.split(","):
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        t = TABLE[f"{cond}:{rc}"]
        net = netlist(c, rc, t["code"], t["vctrl"], camp / "snap" / spec.replace(":", "_"))
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis=ANALYSIS, lets=LETS, t_end=STOP), camp / spec.replace(":", "_") / f"chunk{k:02d}",
                         dict(timeout_s=600 + 90 * n, meta=dict(point=spec, samples=n, seed=s, code=t["code"], vctrl=t["vctrl"]))))
            owners.append(spec)
    dirs = mc.run_many(jobs, workers=a.workers)
    kf = stats.k_factor(a.samples)
    out = {}
    print(f"{a.samples} samples per point, k = {kf:.2f}")
    print(f"{'point':18s} {'code':>4s} {'Vctrl':>6s} | {'f mean GHz':>10s} {'sigma %':>8s} | {'Kvco':>6s} {'sigma mV':>8s} {'k sigma mV':>10s} | {'missing':>7s}")
    for spec in a.points.split(","):
        rows = mc.read_all([d for d, o in zip(dirs, owners) if o == spec])
        f = np.array([r["freq"] for r in rows], float)
        ok = np.isfinite(f) & (f > 0)
        t = TABLE[spec]
        sd = float(np.std(f[ok], ddof=1))
        out[spec] = dict(samples=len(rows), missing=int((~ok).sum()), f_mean=float(np.mean(f[ok])), f_sd=sd, kvco=t["kvco"],
                         vctrl_sd=sd / t["kvco"], vctrl_k_sd=kf * sd / t["kvco"])
        print(f"{spec:18s} {t['code']:4d} {t['vctrl']:6.3f} | {np.mean(f[ok]) / 1e9:10.4f} {100 * sd / np.mean(f[ok]):8.3f} | {t['kvco'] / 1e6:6.0f} "
              f"{1e3 * sd / t['kvco']:8.1f} {1e3 * kf * sd / t['kvco']:10.1f} | {int((~ok).sum()):7d}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), k=kf, points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
