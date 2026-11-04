"""Bandgap power-up over PVT x resistor corner: does it reach the intended state, how fast, how does it
answer a supply step.

    uv run python analog/common/bias/tb/bandgap_startup/run.py --op CAMPAIGN [--tramp 1u] [--tsettle 15u]
        [--process tt,ss] [--rcorners tt,ll,hh] [--dist]

No nodeset: the supply ramps from 0 to the condition's value in tramp; at tramp + tsettle it steps by
+50 mV.  Per condition, against the operating points of a bandgap_pvt campaign (--op):
  ok         vbg within 2 mV and the reference current within 1 % of the operating point before the step
  t_settle   time from the end of the ramp until vbg stays within 1 mV of its pre-step value
  step       vbg and I*R peak deviation after the supply step, and vbg 2 us after it (line regulation)
--dist: the distribution reference serdes_bias_ref (bias_dist.spice: bandgap + CML / CTLE / CP copies into
the module diodes, their gate capacitance on vgi), --op from a dist_pvt campaign; also the CML copy
current's settling (t_settle_cml_us: within 1 % of its pre-step value) and its step deviation.
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


DIST = """.include "{root}/analog/common/bias/spice/bias_dist.spice"
Xref vbg i0 i1 i2 i3 vgi vdd 0 serdes_bias_ref
Xccml ocml vgi vdd serdes_bias_pcopy n=85
Xcctle octle vgi vdd serdes_bias_pcopy n=20
Xccp ocp vgi vdd serdes_bias_pcopy n=20
Vmcml ocml vcml 0
Xdcml vcml 0 serdes_bias_cml
Xdctle octle 0 serdes_bias_ctle
Xdcp ocp vbp vdd 0 serdes_bias_cp"""


def deck(proc, rc, tramp, dist=False, tsettle=15e-6):
    tstep = tramp + tsettle
    stop = tstep + 5e-6
    vals = spice.corner_values(Condition(proc, 1.8, 27))
    text = spice.render(TEMPLATE, **vals, SECTION=section(proc, rc), TRAMP=f"{tramp:.3e}", TSTEP=f"{tstep:.3e}")
    if dist:
        old = "Xbg vbg i0 i1 i2 i3 vg vgi vdd 0 serdes_bandgap"
        assert text.count(old) == 1
        text = text.replace(old, DIST.format(root=ROOT))
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for v in SUPPLY_V:
        for t in TEMP_C:
            n = f"{proc}_{rc}_v{round(v * 1000)}_t{t}"
            icml = " icml" if dist else ""
            lines += [f"option temp={t}", f"alter Vsup dc={v}", f"tran 2n {stop:.4e} 0 20n", "let iref=i(Vi0)"]
            lines += ["let icml=i(Vmcml)"] if dist else []
            lines += [f"write {n}.raw v(vbg) iref v(i1) v(vdd){icml}", "destroy all"]
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
    extra = {}
    if "icml" in w:
        ic = w["icml"]
        c0 = float(np.mean(ic[pre]))
        badc = np.where(after & (t < tstep) & (np.abs(ic - c0) > 0.01 * abs(c0)))[0]
        extra = dict(icml=c0, t_settle_cml_us=float(t[badc[-1]] - tramp) * 1e6 if len(badc) else 0.0,
                     step_icml_peak_pct=float(np.max(np.abs(ic[post] - c0)) / abs(c0) * 100))
    return dict(ok=bool(ok), **extra, vbg=vb0, iref=i0, d_vbg_op_mv=(vb0 - op["vbg"]) * 1e3, d_i_op_pct=(i0 / op["iref"] - 1) * 100,
                t_settle_us=t_settle * 1e6, step_vbg_peak_mv=float(np.max(np.abs(vbg[post] - vb0)) * 1e3),
                step_ir_peak_pct=float(np.max(np.abs(ir[post] - ir0)) / ir0 * 100),
                step_vbg_2us_mv=float((np.interp(tstep + 2e-6, t, vbg) - vb0) * 1e3))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True, help="bandgap_pvt campaign with the operating points")
    ap.add_argument("--tramp", default="1u")
    ap.add_argument("--tsettle", default="15u", help="from the end of the ramp to the supply step; the operating-point check is just before it")
    ap.add_argument("--process", default=",".join(PROCESS))
    ap.add_argument("--rcorners", default="tt,ll,hh")
    ap.add_argument("--dist", action="store_true", help="serdes_bias_ref with the module copies (bias_dist.spice)")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    tramp = spice.spice_number(a.tramp)
    ops = {(r["process"], r["rcorner"], r["supply"], r["temp"]): r for r in json.loads((ROOT / a.op / "summary.json").read_text())}
    rcs = a.rcorners.split(",")
    procs = a.process.split(",")
    camp = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_ramp{a.tramp}{'_dist' if a.dist else ''}"
    jobs, tstep = [], None
    for p in procs:
        for rc in rcs:
            d, tstep = deck(p, rc, tramp, a.dist, spice.spice_number(a.tsettle))
            jobs.append((d, camp / f"{p}_{rc}", dict(timeout_s=3600, meta=dict(process=p, rcorner=rc, tramp=tramp))))
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in procs:
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
    keys = ("t_settle_us", "step_vbg_peak_mv", "step_ir_peak_pct", "step_vbg_2us_mv")
    keys += ("t_settle_cml_us", "step_icml_peak_pct") if a.dist else ()
    for k in keys:
        x = np.array([r[k] for r in rows])
        print(f"  {k:18s} {x.min():8.3f} .. {x.max():8.3f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
