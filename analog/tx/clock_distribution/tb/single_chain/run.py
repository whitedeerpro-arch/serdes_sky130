"""Single-chain TX clock generation experiments.

    uv run python analog/tx/clock_distribution/tb/single_chain/run.py timing [tags...]

timing: one r3 prescaler on phase 0; reports when each tap (/2, /4, /8)
transitions relative to the rising edge of phase 0, i.e. where a retiming
flip-flop clocked by one of the eight VCO phases sees setup/hold.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import STRESS, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/tx/clock_distribution/single_chain"
PERIOD = 500e-12


def timing(conds):
    camp = RESULTS / ("timing_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    jobs = []
    for c in conds:
        deck = spice.render(HERE / "tb_chain_timing_ngspice.cir.in", **spice.corner_values(c),
                            STOP="48n", INITIAL_STATE="")
        jobs.append((deck, camp / c.tag, dict(meta=dict(condition=c.tag, bench="chain_timing"))))
    for ex in spice.run_many(jobs):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c in conds:
        w = spice.Waves(camp / c.tag / "waveforms.tsv")
        t, start = w.t, 24e-9
        ref = clock.edges(t, w["b0"], 1, start)
        row = dict(condition=c.tag)
        # Phase k rising edge relative to b0 rising (ps, mod period).
        for k in range(4):
            e = clock.edges(t, w[f"b{k}"], 1, start)
            row[f"b{k}_rise_ps"] = float(np.median((e - ref[0]) % PERIOD) * 1e12)
        for tap in ("d2", "d4", "d8"):
            stats = clock.period_stats(t, w[tap], start)
            edges = np.sort(np.concatenate([clock.edges(t, w[tap], p, start) for p in (1, -1)]))
            k = np.searchsorted(ref, edges) - 1
            off = (edges[k >= 0] - ref[k[k >= 0]]) * 1e12
            row[tap] = dict(frequency_ghz=stats["frequency_hz"] / 1e9, amplitude_mv=stats["amplitude_pp_v"] * 1e3,
                            delay_after_b0_rise_ps=[float(np.min(off)), float(np.max(off))])
        rows.append(row)
        print(c.tag, {k: (round(v, 1) if isinstance(v, float) else
                          {kk: [round(x, 1) for x in vv] if isinstance(vv, list) else round(vv, 3) for kk, vv in v.items()})
                      for k, v in row.items() if k != "condition"}, flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    step, tags = sys.argv[1], sys.argv[2:]
    conds = [Condition.parse(t) for t in tags] if tags else STRESS
    {"timing": timing}[step](conds)
