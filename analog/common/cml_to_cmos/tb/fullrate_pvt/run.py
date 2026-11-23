"""Full-rate CML-to-CMOS receiver variants behind a real extraction buffer.

    uv run python analog/common/cml_to_cmos/tb/fullrate_pvt/run.py VARIANTS [tags...]

VARIANTS is a comma list of names from VARIANTS below.  Pass criteria per
output: 2 GHz, duty 45-55 %, low < 0.2 VDD and high > 0.8 VDD (the clock
screen used for the r3 grid).
"""
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/common/cml_to_cmos/fullrate_pvt"
CANDIDATE = "serdes_cml_to_cmos_pvt_candidate"
PROBES_CANDIDATE = "v(xrx.ap) v(xrx.bp) v(xrx.rawp)"
ACSB = "serdes_cml_to_cmos_acsb"
PROBES_ACSB = "v(xrx.xp) v(xrx.yp) v(xrx.zp)"
VARIANTS = {
    "base": (CANDIDATE, {}),
    "load16": (CANDIDATE, dict(wload=16, wtail=12)),
    "pre36": (CANDIDATE, dict(pre_wn=3.6)),
    "load16_pre36": (CANDIDATE, dict(wload=16, wtail=12, pre_wn=3.6)),
    "big": (CANDIDATE, dict(win=10, wload=16, wtail=16, pre_wn=3.6)),
    "acsb": (ACSB, {}),
    "acsb_cc100": (ACSB, dict(cc="100f")),
}


def run(names, conds, input_pp=0.3, stop="24n", workers=1):
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, keys = [], []
    for name in names:
        cell, params = VARIANTS[name]
        for c in conds:
            deck = spice.render(HERE / "tb_fullrate_ngspice.cir.in", **spice.corner_values(c), INPUT_PP=input_pp,
                                STOP=stop, RX_CELL=cell, RX_PARAMS=" ".join(f"{k}={v}" for k, v in params.items()),
                                EXTRA_INCLUDE=('.include "@PROJECT_ROOT@/analog/common/cml_to_cmos/spice/cml_to_cmos_acsb.spice"'
                                               .replace("@PROJECT_ROOT@", str(ROOT))),
                                NODESET=(".nodeset v(xrx.xrestore.qp)=0 v(xrx.xrestore.qn)={supply}"
                                         if cell == CANDIDATE else "*"),
                                PROBES=PROBES_CANDIDATE if cell == CANDIDATE else PROBES_ACSB)
            # Analysis starts at 12 ns; nothing before 10 ns needs storing.
            deck = spice.skip_output_before(spice.binary_output(deck), "10n")
            jobs.append((deck, camp / f"{name}_{c.tag}", dict(meta=dict(variant=name, condition=c.tag))))
            keys.append((name, c))
    for ex in spice.run_many(jobs, workers=workers):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for (name, c), (_, d, _) in zip(keys, jobs):
        w = spice.Waves(d / "waveforms.tsv")
        t, m = w.t, w.t > 12e-9
        res = dict(variant=name, condition=c.tag, input_pp_v=float(np.ptp(w["din"][m])),
                   input_cm_v=float(np.mean(w["cmin"][m])), power_mw=float(np.mean(w["prx"][m]) * 1e3))
        ok = True
        for out in ("v(outp)", "v(outn)"):
            ps = clock.period_stats(t, w[out] - c.supply / 2, 12e-9)
            lo, hi = float(w[out][m].min()), float(w[out][m].max())
            good = bool(ps and abs(ps["frequency_hz"] / 2e9 - 1) < 0.01 and 0.45 <= ps["duty"] <= 0.55
                        and lo < 0.2 * c.supply and hi > 0.8 * c.supply)
            res[out] = dict(ok=good, duty=ps["duty"] if ps else None, low=lo, high=hi)
            ok &= good
        res["ok"] = ok
        for p in ("v(xrx.ap)", "v(xrx.bp)", "v(xrx.xp)", "v(xrx.yp)"):
            if p in w:
                res[p] = [float(w[p][m].min()), float(w[p][m].max())]
        rows.append(res)
        print(f"{name:14s} {c.tag:14s} in {res['input_pp_v']*1e3:4.0f}mVpp cm {res['input_cm_v']:.3f}  "
              f"{'PASS' if ok else 'FAIL'}  duty {res['v(outp)']['duty'] or 0:.3f}/{res['v(outn)']['duty'] or 0:.3f}  "
              f"P {res['power_mw']:.2f} mW  "
              + " ".join(f"{p[6:8]} {v[0]:.2f}-{v[1]:.2f}" for p, v in res.items() if p.startswith("v(xrx")), flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    names = sys.argv[1].split(",")
    tags = sys.argv[2:]
    conds = grid45() if tags == ["all"] else [Condition.parse(t) for t in tags] if tags else STRESS
    run(names, conds, input_pp=float(os.environ.get("INPUT_PP", 0.3)), workers=int(os.environ.get("WORKERS", 1)))
