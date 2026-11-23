"""TX clock state detector: does every divider start state give its own static code?

    uv run python analog/tx/clock_distribution/tb/state_detector/run.py [tags...]

Branch 0 (reference, 250 MHz word clock chain) starts in a fixed state; the
branch-2 /2 and /4 stages and the branch-3 /2 stage are forced into each of
their combinations with .ic, giving the 4 x 2 relative states.  For each run:
the true relative state measured from the waveforms (branch-2 /4 delay after
branch-0 /4, branch-3 /2 delay after branch-0 /2, in VCO cycles), the
detector's CMOS code (a, b, c), whether the code is static, and the setup/hold
slack of each detector flip-flop.
"""
import json
import sys
import time
from itertools import product
from pathlib import Path

import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import STRESS, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/tx/clock_distribution/state_detector"
CYCLE = 500e-12


def initial_state(c, s22, s24, s32):
    """.ic lines: each /2 stage's slave output q and master m = not q."""
    hi, lo = c.supply - 0.1, c.supply - 0.5
    lines = []
    for branch, stage, q in [(0, 2, 1), (0, 4, 1), (0, 8, 1), (2, 2, s22), (2, 4, s24), (2, 8, 1),
                             (3, 2, s32), (3, 4, 1), (3, 8, 1), (1, 2, 1), (1, 4, 1), (1, 8, 1)]:
        qp, qn = (hi, lo) if q else (lo, hi)
        lines.append(f".ic v(d{branch}{stage}p)={qp} v(d{branch}{stage}n)={qn} "
                     f"v(xpre{branch}.m{stage}p)={qn} v(xpre{branch}.m{stage}n)={qp}")
    return "\n".join(lines)


def _delay_cycles(t, ref, sig, period, start):
    """Delay of sig rising edges after the preceding ref rising edge, in VCO cycles (rounded)."""
    r = clock.edges(t, ref, 1, start)
    s = clock.edges(t, sig, 1, start)
    k = np.searchsorted(r, s) - 1
    d = (s[k >= 0] - r[k[k >= 0]]) % period
    return d / CYCLE


def _slack(t, data, ck, start):
    """min setup / hold (ps) of a flip-flop that captures on the clock's falling edge."""
    samp = clock.edges(t, ck, -1, start)
    tr = np.sort(np.concatenate([clock.edges(t, data, q, start - 3e-9) for q in (1, -1)]))
    i = np.searchsorted(tr, samp)
    ok = (i > 0) & (i < len(tr))
    return float(np.min(samp[ok] - tr[i[ok] - 1]) * 1e12), float(np.min(tr[i[ok]] - samp[ok]) * 1e12)


def main(conds, workers=4):
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    states = list(product((0, 1), (0, 1), (0, 1)))
    jobs = []
    for c in conds:
        for s22, s24, s32 in states:
            deck = spice.render(HERE / "tb_state_detector_ngspice.cir.in", **spice.corner_values(c),
                                STOP="30n", INITIAL_STATE=initial_state(c, s22, s24, s32))
            # Analysis starts at 12 ns (15 ns minus a 3 ns look-back).
            deck = spice.skip_output_before(spice.binary_output(deck), "10n")
            jobs.append((deck, camp / f"{c.tag}_{s22}{s24}{s32}",
                         dict(meta=dict(condition=c.tag, forced=[s22, s24, s32]))))
    for ex in spice.run_many(jobs, workers=workers):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c in conds:
        for s22, s24, s32 in states:
            w = spice.Waves(camp / f"{c.tag}_{s22}{s24}{s32}" / "waveforms.tsv")
            t, start = w.t, 15e-9
            d500 = _delay_cycles(t, w["r4"], w["c24"], 4 * CYCLE, start)
            d1g = _delay_cycles(t, w["r2"], w["c32"], 2 * CYCLE, start)
            tail = t > t[-1] - 8e-9
            code = []
            static = True
            for bit in "abc":
                v = w["bit" + bit][tail]
                code.append(int(np.mean(v) > c.supply / 2))
                static &= bool(np.ptp(v) < 0.2 * c.supply)   # a toggling bit means a transparent latch
            slack = dict(a=_slack(t, w["r4"], w["k24"], start), b=_slack(t, w["r2"], w["k22"], start),
                         c=_slack(t, w["r2"], w["k32"], start))
            expected = [int(round(np.median(d500))) // 2, int(round(np.median(d500))) % 2, int(round(np.median(d1g)))]
            row = dict(condition=c.tag, forced=[s22, s24, s32], expected_code=expected, correct=code == expected,
                       state_500_cycles=round(float(np.median(d500)), 2), state_1g_cycles=round(float(np.median(d1g)), 2),
                       code=code, static=static, slack_ps=slack)
            rows.append(row)
            print(f"{c.tag:14s} forced {s22}{s24}{s32}  500 lag {row['state_500_cycles']:.2f} cyc  1G lag "
                  f"{row['state_1g_cycles']:.2f} cyc  code {''.join(map(str, code))} {'OK' if row['correct'] else 'WRONG'} static {static}  "
                  + " ".join(f"{k}:{v[0]:.0f}/{v[1]:.0f}" for k, v in slack.items()), flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    tags = sys.argv[1:]
    import os
    main([Condition.parse(t) for t in tags] if tags else STRESS, workers=int(os.environ.get("WORKERS", 4)))
