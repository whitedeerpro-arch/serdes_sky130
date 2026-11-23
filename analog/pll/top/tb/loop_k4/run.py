"""The k = 4 loop with its circuits: capture from the precharge and the response to a reference phase step.

    uv run python analog/pll/top/tb/loop_k4/run.py [--points fs_v1950_t-40:ll:7,...] [--pre-offset 0.04] [--step 100e-12] [--workers 4]

Transistor PFD (pll_pfd), current-steering CP (pll_cp_steer, k = 4, follower from the bias distribution), PDK loop filter
(pll_loop_filter_k4: Rz 4.13 k, 18 x 1 pF MIM, no Cf) with its precharge gates; real bias, PDK R.  The VCO + /8 is
behavioural: the working map's parabola f(V) of the given code and condition, and the control node capacitance
measured there (ctrl_load, interpolated at the 2 GHz Vctrl).  Sequence: precharge both LF nodes to the 2 GHz Vctrl
+ --pre-offset (B2's tolerance), release at 50 ns, PFD out of reset at 52 ns; capture; at --tstep the reference
moves --step later.  Reported: capture time (|PFD error - final| < 20 ps and the feedback period, averaged over 16 reference periods, within 100 ppm until the step),
the step response's overshoot and 2 % settling, and the same from the linear model (pnoise.Loop, the delay as a
first-order Pade) at that Kvco and load: the circuit-level check of the phase margin.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
from scipy import signal

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_loop_k4_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/top/loop_k4"
WORKMAP = "results/analog/pll/vco/workmap/20261106T035710Z"
CTRL_LOAD = "results/analog/pll/vco/ctrl_load/20261108T011936Z"
TREF = 4e-9
_spec = importlib.util.spec_from_file_location("loop_design", ROOT / "analog/pll/top/theory/loop_design.py")
ld = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ld)


def cp_params(k=4):
    return (f"wn={5 * k:g} wp={20 * k:g} wsn={2 * k:g} wsp={4 * k:g} up_wn={0.5 * k:g} up_wp={2 * k:g} dn_wn={k:g} dn_wp={2 * k:g} "
            f"pnf={4 * k} nnf={k} ntail=2 cdum=0.3p")


def ref_pwl(supply, stop, tstep, step):
    pts, t = ["0 0"], 2e-9
    while t < stop:
        s = t + (step if t >= tstep else 0.0)
        pts += [f"{s:.6e} 0", f"{s + 30e-12:.6e} {supply}", f"{s + TREF / 2:.6e} {supply}", f"{s + TREF / 2 + 30e-12:.6e} 0"]
        t += TREF
    lines = ["Vref ref 0 PWL("] + ["+ " + " ".join(pts[i:i + 8]) for i in range(0, len(pts), 8)]
    return "\n".join(lines) + " )\n"


def point(spec, cload):
    cond, rc, code = spec.split(":")
    wm = json.loads((ROOT / WORKMAP / "summary.json").read_text())
    f = wm["rows"][f"{cond}:{rc}"]["f"][code]
    a2, a1, a0 = np.polyfit(wm["vs"], f, 2)
    v0, kv = ld.crossing(np.array(wm["vs"]), f)
    return Condition.parse(cond), rc, int(code), (a0, a1, a2), v0, kv, cload(cond, rc, v0)


def deck(c, rc, coef, v0, cl, a, camp):
    text = spice.render(TEMPLATE, **spice.corner_values(c), CP=cp_params(), VPRE=f"{v0 + a.pre_offset:.4f}", TREL="50n", TREL2="50.2n",
                        A0=f"{coef[0]:.6e}", A1=f"{coef[1]:.6e}", A2=f"{coef[2]:.6e}", CLOAD=f"{cl:.4e}", STOP=f"{a.stop:.4e}")
    text = text.replace("Vreset rst_b 0 PWL(0 0 1n 0 1.02n {supply})", "Vreset rst_b 0 PWL(0 0 52n 0 52.02n {supply})")
    text = spice.binary_output(text)
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.real(text)
    old = "Ibuf vdd ibuf 10u"
    assert text.count(old) == 1
    text = text.replace(old, "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc)


def linear_step(kv, cl, tstop=3e-6):
    lp = ld.pnoise.Loop(icp=200e-6, rz=4130, ci=18e-12, cf=cl, kvco=kv, n=8, delay=2e-9)
    k = lp.icp * lp.kvco / lp.n
    # OL(s) = k Z(s) / s * exp(-s tau); Z = (1 + s R Ci) / (s (Ci + Cf) (1 + s R Ci Cf / (Ci + Cf)))
    cs, tp = lp.ci + lp.cf, lp.rz * lp.ci * lp.cf / (lp.ci + lp.cf)
    num = k * np.array([lp.rz * lp.ci, 1.0])
    den = np.polymul([cs * tp, cs, 0.0], [1.0, 0.0])
    pn, pd = [-lp.delay / 2, 1.0], [lp.delay / 2, 1.0]          # first-order Pade of the delay
    oln, old = np.polymul(num, pn), np.polymul(den, pd)
    cl_n, cl_d = oln, np.polyadd(old, oln)
    t, y = signal.step(signal.lti(cl_n, cl_d), T=np.linspace(0, tstop, 6000))
    return float(y.max() - 1), settle(t, y)


def settle(t, y, tol=0.02):
    bad = np.abs(y - 1) > tol
    return float(t[np.where(bad)[0][-1]]) if bad.any() else 0.0


def analyse(path, a):
    w = spice.Waves(path)
    t = w.t
    er, _ = crossings(t, w["v(ref)"] - w["v(ref)"].max() / 2)
    ef, _ = crossings(t, w["v(fb)"] - w["v(fb)"].max() / 2)
    pr = np.diff(np.sign(np.interp(er, t, np.gradient(w["v(ref)"], t)))) if False else None
    ref_r = er[np.interp(er + 5e-12, t, w["v(ref)"]) > w["v(ref)"].max() / 2]
    fb_r = ef[np.interp(ef + 5e-12, t, w["v(fb)"]) > w["v(fb)"].max() / 2]
    ref_r, fb_r = ref_r[ref_r > 55e-9], fb_r[fb_r > 55e-9]
    # pair each reference edge with the nearest feedback edge
    idx = np.clip(np.searchsorted(fb_r, ref_r), 1, len(fb_r) - 1)
    near = np.where(np.abs(fb_r[idx] - ref_r) < np.abs(fb_r[idx - 1] - ref_r), fb_r[idx], fb_r[idx - 1])
    e = near - ref_r
    pre = ref_r < a.tstep
    e_lock = np.median(e[pre][-50:])
    # frequency from the feedback edge intervals (the mean over each reference period), not the instantaneous f_ghz,
    # which carries the CP ripple (tens of mV x Kvco: ~2 %, far above 100 ppm)
    # averaged over 16 reference periods: single periods carry ~1 ps of cycle-to-cycle residue in lock (> 0.4 ps = 100 ppm)
    per = np.diff(near, prepend=near[0] - TREF)
    cum = np.cumsum(np.where(pre, per, 0.0))
    mean16 = np.array([(cum[i] - (cum[i - 16] if i >= 16 else 0.0)) / min(i + 1, 16) for i in range(len(per))])   # trailing, pre-step only
    bad = pre & ((np.abs(e - e_lock) > 20e-12) | (np.abs(mean16 / TREF - 1) > 1e-4))
    capture = float(ref_r[bad].max() - 52e-9) if bad.any() else 0.0
    # step: the output phase follows the reference shift; y = (fb shift) / step
    post = ref_r >= a.tstep
    nominal = ref_r[post] - a.step                      # reference edges where they would have been
    y = (near[post] - nominal - e_lock) / a.step
    ts = ref_r[post] - a.tstep
    return dict(capture_s=capture, e_lock_s=float(e_lock), overshoot=float(y.max() - 1), settle_s=settle(ts, y), y_final=float(np.median(y[-50:])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="fs_v1950_t-40:ll:7,fs_v1650_t85:ll:7,fs_v1800_t85:hh:1,tt_v1800_t27:tt:6")
    ap.add_argument("--pre-offset", type=float, default=0.04)
    ap.add_argument("--step", type=float, default=100e-12)
    ap.add_argument("--tstep", type=float, default=2.5e-6)
    ap.add_argument("--stop", type=float, default=4.5e-6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="")
    ap.add_argument("--grid", metavar="RC", help="all 45 conditions at this RC section (tt/hh/ll), code from config/pll_code_table.json, boundary first")
    ap.add_argument("--resume", help="campaign to continue: only points without a finished waveform run")
    a = ap.parse_args()
    if a.grid:
        from serdes_flow.corners import boundary_first, grid45
        table = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
        a.points = ",".join(f"{c.tag}:{a.grid}:{table[f'{c.tag}:{a.grid}']['code']}" for c in boundary_first(grid45()))
    cload = ld.CtrlLoad(CTRL_LOAD, 40e-15)
    camp = ROOT / a.resume if a.resume else RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + a.tag)
    if not a.resume:
        camp.mkdir(parents=True)
        (camp / "plan.json").write_text(json.dumps(dict(args=vars(a)), indent=1))
    pts = [point(s, cload) for s in a.points.split(",")]
    jobs = []
    for spec, (c, rc, code, coef, v0, kv, cl) in zip(a.points.split(","), pts):
        d = camp / spec.replace(":", "_")
        if spice.case_output(d, "run", "loop.raw", a.stop) is not None:
            continue
        d.mkdir(parents=True, exist_ok=True)
        (d / "ref.inc").write_text(ref_pwl(c.supply, a.stop, a.tstep, a.step))
        jobs.append((deck(c, rc, coef, v0, cl, a, camp / "snap"), spice.next_run_dir(d, "run"), dict(files={"ref.inc": d / "ref.inc"}, timeout_s=7200,
                     meta=dict(point=spec, v0=v0, kvco=kv, cload=cl, pre_offset=a.pre_offset, step=a.step))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    print(f"precharge offset {a.pre_offset * 1e3:+.0f} mV, reference step {a.step * 1e12:.0f} ps at {a.tstep * 1e6:.1f} us")
    print(f"{'point':24s} {'V0':>6s} {'Kvco':>6s} {'Cload fF':>8s} | {'capture ns':>10s} {'offset ps':>9s} | {'overshoot':>9s} {'settle ns':>9s} | {'linear ov':>9s} {'settle ns':>9s}")
    for spec, (c, rc, code, coef, v0, kv, cl) in zip(a.points.split(","), pts):
        p = spice.case_output(camp / spec.replace(":", "_"), "run", "loop.raw", a.stop)
        if p is None:
            print(f"{spec:24s} missing")
            continue
        m = analyse(p, a)
        lo, ls = linear_step(kv, cl)
        rows[spec] = dict(v0=v0, kvco=kv, cload=cl, **m, linear_overshoot=lo, linear_settle_s=ls)
        print(f"{spec:24s} {v0:6.3f} {kv / 1e6:6.0f} {cl * 1e15:8.0f} | {m['capture_s'] * 1e9:10.0f} {m['e_lock_s'] * 1e12:9.1f} | "
              f"{m['overshoot'] * 100:8.1f}% {m['settle_s'] * 1e9:9.0f} | {lo * 100:8.1f}% {ls * 1e9:9.0f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
