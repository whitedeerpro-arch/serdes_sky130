"""Local mismatch Monte Carlo of the 200 uA current-steering CP in the locked state.

    uv run python analog/pll/cp/tb/mc/run.py [--points tt_v1800_t27:1.15,...] [--samples 200] [--chunk 25] [--workers 3]

Deck of analog/pll/cp/tb/ripple (pll_cp_steer at k = 4, follower from the bias distribution, Rz 4.13 k + Ci 18.4 pF,
control node 0.4 pF), equal 450 ps UP / DN pulses every 4 ns, library section <process>_mm (local mismatch only).
Per sample over the last four reference periods: net charge per period (UP / DN mismatch; the loop cancels it with a
static phase offset q / Icp) and the peak-to-peak Vctrl ripple of the last period (equal pulses, no offset correction:
an upper bound on the locked ripple).  Points: condition:Vctrl.
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("cp_ripple", ROOT / "analog/pll/cp/tb/ripple/run.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)
RESULTS = ROOT / "results/analog/pll/cp/mc"
CCTRL = 0.4e-12
T1 = 1e-9 + (rp.PERIODS - 4) * rp.TREF
TEND = rp.PERIODS * rp.TREF + 1e-9


def netlist(c, v0, camp):
    a = argparse.Namespace(k=4, cell="steer", ntail=2, cdum=0.3e-12, ideal_ota_bias=False, ton=0.45e-9, rz=4130, ci=18.38e-12, cf=0.0, passive="tt")
    text = rp.deck(c, a, v0, CCTRL, 0.0, camp)
    text = re.sub(r"\.control.*?\.endc\s*", "", text, flags=re.S)
    text = re.sub(r"^\.end\s*$", "", text, flags=re.M)
    text, n = re.subn(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: m[1] + f"{c.process}_mm", text, count=1, flags=re.M | re.I)
    assert n == 1
    return text


ANALYSIS = "\n".join([f"tran 1p {TEND:.4e} 0 2p",
                      f"meas tran vz1 find v(z) at={T1:.4e}", f"meas tran vz2 find v(z) at={TEND:.4e}",
                      f"meas tran vc1 find v(ctrl) at={T1:.4e}", f"meas tran vc2 find v(ctrl) at={TEND:.4e}",
                      f"meas tran rpp pp v(ctrl) from={TEND - rp.TREF:.4e} to={TEND:.4e}"])
LETS = {"q_per": f"((vz2-vz1)*18.38e-12+(vc2-vc1)*{CCTRL:.3e})/4", "ripple_pp": "rpp"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:1.15,ss_v1650_t-40:1.24,sf_v1650_t85:1.24")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=25)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, owners = [], []
    for spec in a.points.split(","):
        cond, v = spec.split(":")
        c = Condition.parse(cond)
        net = netlist(c, float(v), camp / "snap" / cond)
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis=ANALYSIS, lets=LETS, t_end=TEND), camp / spec.replace(":", "_") / f"chunk{k:02d}",
                         dict(timeout_s=600 + 60 * n, meta=dict(point=spec, samples=n, seed=s))))
            owners.append(spec)
    dirs = mc.run_many(jobs, workers=a.workers)
    out = {}
    icp = 200e-6
    print(f"equal 450 ps pulses, control node {CCTRL * 1e12:.1f} pF; k from the sample count")
    print(f"{'point':22s} {'n':>4s} | {'net Q fC mean/sd':>17s} {'offset ps mean/sd':>18s} {'|offset| + k sd ps':>18s} | {'ripple mV mean/max':>18s}")
    for spec in a.points.split(","):
        rows = mc.read_all([d for d, o in zip(dirs, owners) if o == spec])
        q = np.array([r["q_per"] for r in rows], float)
        rpp = np.array([r["ripple_pp"] for r in rows], float)
        kf = stats.k_factor(len(rows))
        off = q / icp
        out[spec] = dict(samples=len(rows), k=kf, q_mean=float(q.mean()), q_sd=float(q.std(ddof=1)), offset_bound_s=float(abs(off.mean()) + kf * off.std(ddof=1)),
                         ripple_mean=float(rpp.mean()), ripple_max=float(rpp.max()))
        print(f"{spec:22s} {len(rows):4d} | {q.mean() * 1e15:8.2f}/{q.std(ddof=1) * 1e15:6.2f} {off.mean() * 1e12:9.1f}/{off.std(ddof=1) * 1e12:6.1f} "
              f"{(abs(off.mean()) + kf * off.std(ddof=1)) * 1e12:18.1f} | {rpp.mean() * 1e3:8.1f}/{rpp.max() * 1e3:7.1f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
