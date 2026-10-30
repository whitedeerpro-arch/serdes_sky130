"""PLL r4 clock frontend with the native VCO: does every branch's full-rate CMOS work?

    uv run python analog/pll/top/tb/pvt_r4/run.py

Same fixed-Vctrl open-loop operating points as the r3 native reconnection
(results/analog/pll/pvt_buffered/20261029T152825Z), plus the SS cold code-6
point.  Window 32-64 ns.  Checks per branch: /2, /4, /8 CML dividers (branch
0), 250 MHz feedback CMOS (four branches) and full-rate CMOS (four branches):
frequency within 1 %, duty 45-55 % for full rate, CMOS low < 0.2 VDD and
high > 0.8 VDD.
"""
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/pll/top/pvt_r4"
R3 = ROOT / "results/analog/pll/pvt_buffered/20261029T152825Z"
POINTS = [  # name, condition, coarse code, Vctrl, r3 run at the same point
    ("tt", "tt_v1800_t27", 5, 1.205, "native_tt"),
    ("ss_hot", "ss_v1650_t85", 6, 1.32, "native_ss_hot"),
    ("fs_hot", "fs_v1650_t85", 5, 1.10, "native_fs_hot"),
    ("ss_cold", "ss_v1650_t-40", 5, 1.112, "native_ss_cold_target2G"),
    ("ss_cold_code6", "ss_v1650_t-40", 6, 1.32, "native_ss_cold"),
]
START, STOP = 32e-9, 64e-9


def _check(t, y, f, level=0.0, cmos_supply=None, duty=False):
    ps = clock.period_stats(t, y - level, START, STOP)
    ok = bool(ps and abs(ps["frequency_hz"] / f - 1) < 0.01)
    r = dict(frequency_hz=ps["frequency_hz"] if ps else None, duty=ps["duty"] if ps else None)
    if duty:
        ok &= bool(ps and 0.45 <= ps["duty"] <= 0.55)
    if cmos_supply:
        m = (t >= START) & (t <= STOP)
        lo, hi = float(y[m].min()), float(y[m].max())
        ok &= lo < 0.2 * cmos_supply and hi > 0.8 * cmos_supply
        r.update(low=lo, high=hi)
    r["ok"] = ok
    return r


def main():
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = []
    for name, tag, code, vctrl, _ in POINTS:
        c = Condition.parse(tag)
        deck = spice.render(HERE / "tb_frontend_ngspice.cir.in", **spice.corner_values(c), CODE=code,
                            CONTROL_SOURCE=vctrl, STOP="64n")
        deck = spice.skip_output_before(spice.binary_output(deck), "30n")
        jobs.append((deck, camp / name, dict(meta=dict(condition=tag, code=code, vctrl=vctrl))))
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for name, tag, code, vctrl, r3name in POINTS:
        c = Condition.parse(tag)
        w = spice.Waves(camp / name / "waveforms.raw")
        t = w.t
        f = clock.period_stats(t, w["b0"], START, STOP)["frequency_hz"]
        div = {k: _check(t, w[f"v(xclock.d0{k}p)"] - w[f"v(xclock.d0{k}n)"], f / k) for k in (2, 4, 8)}
        fb = {b: _check(t, w[v], f / 8, c.supply / 2, c.supply)
              for b, v in enumerate(("v(fb0)", "v(xclock.fb1)", "v(xclock.fb2)", "v(xclock.fb3)"))}
        full = {b: _check(t, w[v], f, c.supply / 2, c.supply, duty=True)
                for b, v in enumerate(("v(c0p)", "v(c1p)", "v(c2p)", "v(c3p)"))}
        m = (t >= START) & (t <= STOP)
        power = float(np.trapezoid(w["pcore"][m], t[m]) / (STOP - START))
        r3 = spice.Waves(R3 / r3name / "waveforms.tsv")
        m3 = (r3.t >= START) & (r3.t <= STOP)
        power_r3 = float(np.trapezoid(r3["pcore"][m3], r3.t[m3]) / (STOP - START))
        row = dict(name=name, condition=tag, code=code, vctrl=vctrl, vco_hz=f, dividers=div, feedback=fb,
                   fullrate=full, core_power_w=power, r3_core_power_w=power_r3,
                   ok=all(x["ok"] for x in [*div.values(), *fb.values(), *full.values()]))
        rows.append(row)
        print(f"{name:14s} {tag:14s} code {code} Vctrl {vctrl:.3f}  VCO {f/1e9:.4f} GHz  "
              f"div {'ok' if all(x['ok'] for x in div.values()) else 'FAIL'}  fb {sum(x['ok'] for x in fb.values())}/4  "
              f"full-rate {sum(x['ok'] for x in full.values())}/4 duty "
              + "/".join(f"{x['duty']:.3f}" if x["duty"] else "-" for x in full.values())
              + f"  core {power*1e3:.1f} mW (r3 {power_r3*1e3:.1f})", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
