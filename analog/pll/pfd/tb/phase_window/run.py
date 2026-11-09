"""Lock-detector phase window (pll_phase_window) driven by the real PFD: flag threshold over 45 conditions.

    uv run python analog/pll/pfd/tb/phase_window/run.py [--params "cd=10f"] [--workers 1] [--analyse C]

One deck per MOS corner and supply (clock swing = supply), temperature in the control block.  Per condition one
transient: WARM zero-phase periods, then per phase of PHASES (fb edge minus ref edge, both signs) one test period
followed by a zero-phase spacer period.  The flag is cleared 1.2 ns before each test edge and read 2.5 ns after it.
The spacer keeps fb's low time >= 1.1 ns: back-to-back +800 / -800 ps periods left 0.4 ns, and the PFD (clock-to-Q
~0.8 ns at SS 1.65 V -40 C) missed an fb edge.  Per test period the xor pulse width (integral of e / VDD over the
period) is checked against |phase| (a missed edge gives a ns-long pulse).  Threshold = midpoint between the largest
|phase| that leaves the flag clear and the smallest that sets it (per sign); a non-monotonic flag pattern is reported.
Requirement (pll_lock_detect.sv): the threshold above the locked static offset at every condition (PFD + CP MC:
|mean| + k sd 51-189 ps), far below acquisition errors (ns).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_phase_window_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/pfd/phase_window"
MAG = [0, 60, 120, 150, 180, 210, 240, 270, 300, 350, 400, 450, 500, 600, 700, 800, 900]
PHASES = [0.0] + [s * m * 1e-12 for m in MAG[1:] for s in (1, -1)]
TREF, T0, TR, TREAD, WARM = 4e-9, 2e-9, 30e-12, 2.5e-9, 2
PULSE_TOL = 150e-12            # a missed PFD edge leaves a pulse of ns


def sequence():
    """Per-period fb shifts (warm-up, then test / spacer pairs) and the indices of the test periods."""
    seq, test = [0.0] * WARM, []
    for p in PHASES:
        test.append(len(seq))
        seq += [p, 0.0]
    return seq, test


def pwls(v):
    seq, test = sequence()
    all_t = [T0 + k * TREF for k in range(len(seq))]
    def clock(shifts):
        pts = [(0.0, 0.0)]
        for t, s in zip(all_t, shifts):
            r = t + s
            pts += [(r, 0.0), (r + TR, v), (r + TREF / 2, v), (r + TREF / 2 + TR, 0.0)]
        return " ".join(f"{x:.6e} {y:.4g}" for x, y in pts)
    times = [all_t[k] for k in test]
    clr = [(0.0, 0.0), (0.5e-9, 0.0), (0.5e-9 + TR, v)]
    for t in times:
        a = t - 1.2e-9
        clr += [(a, v), (a + TR, 0.0), (a + 0.2e-9, 0.0), (a + 0.2e-9 + TR, v)]
    return clock([0.0] * len(seq)), clock(seq), " ".join(f"{x:.6e} {y:.4g}" for x, y in clr), times, all_t[-1] + TREF


def deck(proc, v, params):
    ref, fb, clr, times, tend = pwls(v)
    text = spice.render(TEMPLATE, **spice.corner_values(Condition(proc, v, 27)), REF_PWL=ref, FB_PWL=fb, CLR_PWL=clr, PW_PARAMS=params)
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    names = [f"f{k}" for k in range(len(PHASES))] + [f"a{k}" for k in range(len(PHASES))]
    for t in TEMP_C:
        lines += [f"option temp={t}", f"tran 2p {tend:.5e} 0 5p"]
        lines += [f"meas tran f{k} find v(late) at={tk + TREAD:.5e}" for k, tk in enumerate(times)]
        lines += [f"meas tran a{k} integ v(xw.e) from={tk - 1.0e-9:.5e} to={tk + TREAD:.5e}" for k, tk in enumerate(times)]
        lines += [f"wrdata {proc}_v{round(v * 1000)}_t{t}.tsv " + " ".join(names), "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def threshold(flags, sign):
    pts = sorted((abs(p), f) for p, f in zip(PHASES, flags) if p == 0 or np.sign(p) == sign)
    clear = [m for m, f in pts if not f]
    setm = [m for m, f in pts if f]
    mono = not (clear and setm and max(clear) > min(setm))
    if not setm:
        return None, mono
    lo = max([m for m in clear if m < min(setm)], default=0.0)
    return (lo + min(setm)) / 2, mono


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", default="cd=10f")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--analyse", help="campaign to re-read without simulating")
    a = ap.parse_args()
    camp = ROOT / a.analyse if a.analyse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    if not a.analyse:
        jobs = [(deck(p, v, a.params), camp / f"{p}_v{round(v * 1000)}", dict(timeout_s=3600, meta=dict(process=p, supply=v)))
                for p in PROCESS for v in SUPPLY_V]
        for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
            if not ex.ok:
                print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)
    rows = []
    for p in PROCESS:
        for v in SUPPLY_V:
            for t in TEMP_C:
                f = camp / f"{p}_v{round(v * 1000)}" / f"{p}_v{round(v * 1000)}_t{t}.tsv"
                if not f.exists():
                    continue
                head, data = f.read_text().split("\n")[:2]
                col = dict(zip(head.split(), (float(x) for x in data.split())))
                n = len(PHASES)
                flags = [col[f"f{k}"] > v / 2 for k in range(n)]
                width = [col[f"a{k}"] / v for k in range(n)]               # xor pulse width, s
                dev = [w - abs(ph) for w, ph in zip(width, PHASES)]
                tp, mp = threshold(flags, 1)
                tn, mn = threshold(flags, -1)
                rows.append(dict(process=p, supply=v, temp=t, flags=flags, th_pos=tp, th_neg=tn, monotonic=bool(mp and mn),
                                 zero_clear=not flags[0], xor_width_dev_s=[min(dev), max(dev)], pulses_ok=all(abs(d) < PULSE_TOL for d in dev)))
    (camp / "summary.json").write_text(json.dumps(dict(params=a.params, phases=PHASES, rows=rows), indent=1))
    ths = [x for r in rows for x in (r["th_pos"], r["th_neg"]) if x is not None]
    lo = min(rows, key=lambda r: min(x for x in (r["th_pos"], r["th_neg"]) if x is not None) if ths else 0)
    hi = max(rows, key=lambda r: max(x for x in (r["th_pos"], r["th_neg"]) if x is not None) if ths else 0)
    print(f"{len(rows)} conditions; zero phase clear {sum(r['zero_clear'] for r in rows)}/{len(rows)}, monotonic {sum(r['monotonic'] for r in rows)}/{len(rows)}, "
          f"no threshold within 900 ps: {sum(r['th_pos'] is None or r['th_neg'] is None for r in rows)}, "
          f"xor width = |phase| +- {PULSE_TOL * 1e12:.0f} ps in every test period: {sum(r['pulses_ok'] for r in rows)}/{len(rows)} "
          f"(deviation {min(r['xor_width_dev_s'][0] for r in rows) * 1e12:+.0f} .. {max(r['xor_width_dev_s'][1] for r in rows) * 1e12:+.0f} ps)")
    if ths:
        print(f"threshold {min(ths) * 1e12:.0f} .. {max(ths) * 1e12:.0f} ps  (lowest {lo['process']} {lo['supply']} {lo['temp']}, highest {hi['process']} {hi['supply']} {hi['temp']})")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
