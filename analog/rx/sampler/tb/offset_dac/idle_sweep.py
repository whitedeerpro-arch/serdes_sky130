"""Code staircase at idle input: where a trimmed lane flips, sweeping its code up and then down.

    uv run python analog/rx/sampler/tb/offset_dac/idle_sweep.py [--lanes d0,e0] [--others hold63,alt]
        [--lo 26 --hi 37] [--step-ns 10] [--pi-code 4] [--cond tt_v1800_t27] [--workers 4]

The start-up SAR (rx_offset_cal) decides at zero differential input, step by step.  The ramp
benches cross the threshold once, from below, so they cannot see a decision that depends on the
lane's own previous decisions (memory / hysteresis) or on how the other lanes are driven during
calibration (the SEQ sequencer toggles them 0 <-> 63 every word).  This bench is the link_pvt one
(CTLE EQ3 -> PI -> ac_trim, ideal anchors) with both far-end legs at vcm 1.05 V: the lane's code
steps lo -> hi -> lo, one code per step, and the fraction of time its output is 1 over the second
half of each step is recorded.  Others: hold63 (decide 0), hold0 (decide 1), alt (0 <-> 63 every
4 ns, as the SEQ sequencer drives them).  Flip codes up vs down = hysteresis in codes.
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_s = importlib.util.spec_from_file_location("link_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")
lp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(lp)
LANES = ("d0", "d1", "e0", "e1")
RESULTS = ROOT / "results/analog/rx/sampler/offset_dac"
VCM = 1.05
T0 = 5e-9
WORD = 4e-9
TR = 100e-12


def staircase(lo, hi):
    return list(range(lo, hi + 1)) + list(range(hi, lo - 1, -1))


def code_pwl(node, codes, step, vdd):
    """PWL for one code bit: level held per step, TR transitions at the step boundaries."""
    k = int(node[-1])
    lvl = [vdd * ((c >> k) & 1) for c in codes]
    pts = [(0.0, lvl[0])]
    for i in range(1, len(codes)):
        t = T0 + i * step
        if lvl[i] != lvl[i - 1]:
            pts += [(t, lvl[i - 1]), (t + TR, lvl[i])]
    return f"Vc{node} {node} 0 PWL(" + " ".join(f"{t:.4e} {v:g}" for t, v in pts) + ")"


def deck(c, lane, others, codes, step, pi_code):
    vdd = c.supply
    ctl = [f"{k} {k[1]}{k[2]} 0 {v}" for k, v in lp.pi.bits(pi_code, vdd).items()]
    for n in lp.CAL_NODES:
        if n.startswith(lane):
            ctl.append(code_pwl(n, codes, step, vdd))
        elif others == "alt":
            ctl.append(f"Vc{n} {n} 0 PULSE(0 {vdd} {T0:.4e} {TR:.1e} {TR:.1e} {WORD - TR:.4e} {2 * WORD:.4e})")
        else:
            ctl.append(f"Vc{n} {n} 0 dc {vdd if others == 'hold63' else 0}")
    dut = " ".join(lp.CAL_NODES + ["serdes_rx_half_rate_samples_ac_trim", "rb=2k"])
    stop = T0 + len(codes) * step
    text = spice.render(lp.TEMPLATE, **spice.corner_values(c), EQ0_V=vdd, EQ1_V=vdd,
                        CONTROL_SOURCES="\n".join(ctl), DUT=dut,
                        CASES=f"tran 2p {stop:.4e} 0 4p\nwrite waves.raw v({lane}p) v({lane}n)")
    return text.replace(".save v(op)", f".save v({lane}p) v({lane}n) v(op)")


def fractions(run_dir, lane, codes, step):
    w = spice.Waves(run_dir / "waves.raw")
    t, s = w.t, w[f"v({lane}p)"] - w[f"v({lane}n)"]
    out = []
    for i in range(len(codes)):
        a, b = T0 + (i + 0.5) * step, T0 + (i + 1) * step
        m = (t >= a) & (t <= b)
        dt = np.diff(t[m])
        out.append(float(np.sum(dt * (s[m][:-1] > 0)) / np.sum(dt)))
    return out


def flips(codes, frac):
    """Codes at which the majority decision changes: (direction, code before, code after)."""
    res = []
    for i in range(1, len(codes)):
        if (frac[i] > 0.5) != (frac[i - 1] > 0.5):
            res.append(("up" if codes[i] > codes[i - 1] else "down", codes[i - 1], codes[i]))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lanes", default="d0,e0")
    ap.add_argument("--others", default="hold63,alt")
    ap.add_argument("--lo", type=int, default=26)
    ap.add_argument("--hi", type=int, default=37)
    ap.add_argument("--step-ns", type=float, default=10.0)
    ap.add_argument("--pi-code", type=int, default=4)
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    codes, step = staircase(a.lo, a.hi), a.step_ns * 1e-9
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_idle")
    camp.mkdir(parents=True)
    (camp / "stimuli.inc").write_text(f"Vfarp rxp 0 dc {VCM}\nVfarn rxn 0 dc {VCM}\n")
    runs = [(l, o) for l in a.lanes.split(",") for o in a.others.split(",")]
    jobs = [(deck(c, l, o, codes, step, a.pi_code), camp / f"{l}_{o}",
             dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=3600, meta=dict(condition=c.tag, lane=l, others=o, codes=codes, step_s=step, pi_code=a.pi_code)))
            for l, o in runs]
    spice.run_many(jobs, workers=a.workers, smoke=False)
    out = dict(condition=c.tag, pi_code=a.pi_code, codes=codes, step_s=step, runs={})
    for l, o in runs:
        d = camp / f"{l}_{o}"
        if not (d / "waves.raw").exists():
            print(f"{l} {o}: no waveform")
            continue
        fr = fractions(d, l, codes, step)
        out["runs"][f"{l}_{o}"] = dict(fraction_one=fr, flips=flips(codes, fr))
        print(f"{l} others {o:6s}: " + " ".join(f"{cd}:{f:.2f}" for cd, f in zip(codes, fr)))
        print(f"   flips: {flips(codes, fr)}")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
