"""Bandgap power-up over PVT x resistor corner: does it reach the intended state, how fast, how does it
answer a supply step.

    uv run python analog/common/bias/tb/bandgap_startup/run.py --op CAMPAIGN [--tramp 1u] [--rcorners tt,ll,hh]

No nodeset: the supply ramps from 0 to the condition's value in tramp; at tramp + 15 us it steps by
+50 mV.  Per condition, against the operating points of a bandgap_pvt campaign (--op):
  ok         vbg within 2 mV and the reference current within 1 % of the operating point before the step
  t_settle   time from the end of the ramp until vbg stays within 1 mV of its pre-step value
  step       vbg and I*R peak deviation after the supply step, and vbg 2 us after it (line regulation)
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
TEMPLATE = HERE / "tb_bandgap_startup_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/bias/bandgap_startup"


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def deck(proc, rc, tramp):
    tstep = tramp + 15e-6
    stop = tstep + 5e-6
    vals = spice.corner_values(Condition(proc, 1.8, 27))
    text = spice.render(TEMPLATE, **vals, SECTION=section(proc, rc), TRAMP=f"{tramp:.3e}", TSTEP=f"{tstep:.3e}")
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for v in SUPPLY_V:
        for t in TEMP_C:
            n = f"{proc}_{rc}_v{round(v * 1000)}_t{t}"
            lines += [f"option temp={t}", f"alter Vsup dc={v}", f"tran 2n {stop:.4e} 0 20n", "let iref=i(Vi0)",
                      f"write {n}.raw v(vbg) iref v(i1) v(vdd)", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""]), tstep


def analyse(raw, op, tramp, tstep):
    w = spice.Waves(raw)
    t, vbg, ir, iref = w.t, w["v(vbg)"], w["v(i1)"], w["iref"]
    pre = (t > tstep - 1e-6) & (t < tstep)
    vb0, i0, ir0 = float(np.mean(vbg[pre])), float(np.mean(iref[pre])), float(np.mean(ir[pre]))
    ok = abs(vb0 - op["vbg"]) < 2e-3 and abs(i0 - op["iref"]) < 0.01 * abs(op["iref"])
    after = t > tramp
    bad = np.where(after & (t < tstep) & (np.abs(vbg - vb0) > 1e-3))[0]
    t_settle = float(t[bad[-1]] - tramp) if len(bad) else 0.0
    post = t > tstep
    return dict(ok=bool(ok), vbg=vb0, iref=i0, d_vbg_op_mv=(vb0 - op["vbg"]) * 1e3, d_i_op_pct=(i0 / op["iref"] - 1) * 100,
                t_settle_us=t_settle * 1e6, step_vbg_peak_mv=float(np.max(np.abs(vbg[post] - vb0)) * 1e3),
                step_ir_peak_pct=float(np.max(np.abs(ir[post] - ir0)) / ir0 * 100),
                step_vbg_2us_mv=float((np.interp(tstep + 2e-6, t, vbg) - vb0) * 1e3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True, help="bandgap_pvt campaign with the operating points")
    ap.add_argument("--tramp", default="1u")
    ap.add_argument("--rcorners", default="tt,ll,hh")
    a = ap.parse_args()
    tramp = spice.spice_number(a.tramp)
    ops = {(r["process"], r["rcorner"], r["supply"], r["temp"]): r for r in json.loads((ROOT / a.op / "summary.json").read_text())}
    rcs = a.rcorners.split(",")
    camp = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_ramp{a.tramp}"
    jobs, tstep = [], None
    for p in PROCESS:
        for rc in rcs:
            d, tstep = deck(p, rc, tramp)
            jobs.append((d, camp / f"{p}_{rc}", dict(timeout_s=3600, meta=dict(process=p, rcorner=rc, tramp=tramp))))
    for ex in spice.run_many(jobs, workers=4, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in PROCESS:
        for rc in rcs:
            for v in SUPPLY_V:
                for t in TEMP_C:
                    raw = camp / f"{p}_{rc}" / f"{p}_{rc}_v{round(v * 1000)}_t{t}.raw"
                    if raw.exists():
                        rows.append(dict(process=p, rcorner=rc, supply=v, temp=t, **analyse(raw, ops[(p, rc, v, t)], tramp, tstep)))
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    bad = [r for r in rows if not r["ok"]]
    print(f"{len(rows)} conditions, {len(rows) - len(bad)} reach the operating point")
    for r in bad[:10]:
        print(f"  NOT OK {r['process']}_{r['rcorner']} {r['supply']} V {r['temp']} C: vbg {r['vbg']:.4f} ({r['d_vbg_op_mv']:+.1f} mV), I {r['d_i_op_pct']:+.1f} %")
    for k in ("t_settle_us", "step_vbg_peak_mv", "step_ir_peak_pct", "step_vbg_2us_mv"):
        x = np.array([r[k] for r in rows])
        print(f"  {k:18s} {x.min():8.3f} .. {x.max():8.3f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
