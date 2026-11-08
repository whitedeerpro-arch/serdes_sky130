"""What one coarse-code switch does to the locked PLL: time-domain phase model, with and without a Vctrl precharge.

    uv run python analog/pll/top/theory/recode_transient.py [--chip tt_v1800:tt] [--temp 85] [--code 6] [--errors 0,10,30,70]
        [--icp 200e-6 --rz 4130 --ci 18.38e-12 --cf 0.5e-12] [--tstop 12e-6]

Model (behavioural, not a circuit): 250 MHz reference, tri-state PFD with reset pulse --trst after the later edge, CP
UP / DN currents, loop filter Cf (VCO control node + any added C) || (Rz + Ci), VCO f(code, Vctrl) from the parabola
through the working map's simulated points at that chip and temperature, divide by 8.  Fixed step --dt.
Sequence: lock on --code (Vctrl started on its 2 GHz point), at --tswitch switch to the faster code (code - 1).
Cases: no precharge; precharge of both loop filter nodes to the new code's 2 GHz Vctrl plus an error (instantaneous,
the CP keeps running).  Reported: peak output time error (TIE of the 2 GHz edges against the ideal grid, relative to
its value just before the switch), the time until |TIE change rate| and the PFD phase error are back inside
--lock-ps for --hold (PFD error: k-th feedback edge against the k-th reference edge, unwrapped), and the reference
cycles slipped (largest PFD error over the reference period).
"""
import argparse
import json
import math
import time

import numpy as np

from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

WORKMAP = "results/analog/pll/vco/workmap/20261106T035710Z"
FREF, N = 250e6, 8


def tuning(chip, temp, workmap=WORKMAP):
    wm = json.loads((ROOT / workmap / "summary.json").read_text())
    vs = np.array(wm["vs"])
    cond, rc = chip.split(":")
    key = f"{cond}_t{temp}:{rc}"
    return {int(k): np.polyfit(vs, f, 2) for k, f in wm["rows"][key]["f"].items()}, key


def v_at(p, target=2e9):
    r = [x.real for x in np.roots([p[0], p[1], p[2] - target]) if abs(x.imag) < 1e-12 and 0.6 <= x.real <= 1.7]
    return min(r, key=lambda x: abs(x - 1.1)) if r else None


def simulate(curves, code, a, v0, pre=None):
    """pre: (time, voltage) of an instantaneous precharge of both LF nodes at the switch."""
    dt, tstop, tsw = a.dt, a.tstop, a.tswitch
    tref = 1 / FREF
    vc = vz = v0
    pa, pb, pcf = (float(x) for x in curves[code])
    # VCO phase in cycles, aligned so the first feedback edge meets the first reference edge (locked start)
    ph = N - ((pa * v0 + pb) * v0 + pcf) * tref * 0.5
    up = dn = False
    reset_at = None
    next_ref = tref * 0.5
    fb_count = 0
    edges = []                      # VCO rising edge times (every N-th: feedback); we keep every 16th to save memory
    tie_t, tie_v = [], []
    pfd_err = []                    # (time, ref - fb) at each feedback edge
    last_ref = None
    fb_since_ref = 0
    slips = 0
    t = 0.0
    nedge = 0
    switched = False
    while t < tstop:
        if not switched and t >= tsw:
            switched = True
            pa, pb, pcf = (float(x) for x in curves[code - 1])
            if pre is not None:
                vc = vz = pre
        f = (pa * vc + pb) * vc + pcf
        old = ph
        ph += f * dt
        if int(ph) != int(old):                         # a VCO rising edge in this step
            te = t + (int(ph) - old) / f
            nedge += 1
            if nedge % 16 == 0:
                tie_t.append(te)
                tie_v.append(te - (nedge - N) / 2e9)
            if nedge % N == 0:                          # feedback edge
                fb_count += 1
                fb_since_ref += 1
                # k-th feedback edge against the k-th reference edge (aligned at the start): unwrapped phase error
                pfd_err.append((te, te - (tref * 0.5 + (fb_count - 1) * tref)))
                if up:
                    reset_at = te + a.trst if reset_at is None else reset_at
                dn = True
        if t + dt >= next_ref > t:
            if fb_since_ref != 1 and last_ref is not None and t > tsw:
                slips += 1
            fb_since_ref = 0
            last_ref = next_ref
            if dn:
                reset_at = next_ref + a.trst if reset_at is None else reset_at
            up = True
            next_ref += tref
        if reset_at is not None and t >= reset_at:
            up = dn = False
            reset_at = None
        i = (a.icp * (1 + a.mismatch / 2) if up else 0.0) - (a.icp * (1 - a.mismatch / 2) if dn else 0.0)
        ir = (vc - vz) / a.rz
        vc += (i - ir) / a.cf * dt
        vz += ir / a.ci * dt
        t += dt
    return np.array(tie_t), np.array(tie_v), slips, np.array(pfd_err)


def settle_time(t, x, tol, after, hold):
    """First time after `after` from which |x| stays below tol until the end (needs `hold` of record after it)."""
    sel = t >= after
    bad = sel & (np.abs(x) > tol)
    if not bad.any():
        return 0.0
    last = t[bad].max()
    return float(last - after) if last < t[-1] - hold else float("nan")


def metrics(tie_t, tie_v, pfd, a):
    before = (tie_t > a.tswitch - 0.3e-6) & (tie_t < a.tswitch)
    ref = np.mean(tie_v[before])
    d = tie_v - ref
    after = tie_t >= a.tswitch
    peak = float(np.max(np.abs(d[after])))
    # settled: PFD error back to its pre-switch value within lock-ps, held for --hold
    pt, pe = pfd[:, 0], pfd[:, 1]
    e0 = np.median(pe[(pt > a.tswitch - 0.3e-6) & (pt < a.tswitch)])
    settle = settle_time(pt, pe - e0, a.lock_ps, a.tswitch, a.hold)
    worst = float(np.max(np.abs(pe[pt >= a.tswitch] - e0)))
    return peak, settle, float(d[after][-1]), worst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chip", default="tt_v1800:tt")
    ap.add_argument("--temp", type=int, default=85)
    ap.add_argument("--code", type=int)
    ap.add_argument("--errors", default="0,10,30,70", help="precharge errors, mV")
    ap.add_argument("--icp", type=float, default=200e-6)
    ap.add_argument("--rz", type=float, default=4130)
    ap.add_argument("--ci", type=float, default=18.38e-12)
    ap.add_argument("--cf", type=float, default=0.5e-12, help="VCO control node + added, F")
    ap.add_argument("--trst", type=float, default=0.45e-9)
    ap.add_argument("--mismatch", type=float, default=0.0)
    ap.add_argument("--dt", type=float, default=2e-12)
    ap.add_argument("--tswitch", type=float, default=2e-6)
    ap.add_argument("--tstop", type=float, default=8e-6)
    ap.add_argument("--lock-ps", type=float, default=5e-12)
    ap.add_argument("--hold", type=float, default=0.5e-6)
    a = ap.parse_args()
    curves, key = tuning(a.chip, a.temp)
    codes = sorted(k for k, p in curves.items() if v_at(p) and k - 1 in curves and v_at(curves[k - 1]))
    code = a.code if a.code is not None else max(codes, key=lambda k: v_at(curves[k]))
    v0, v1 = v_at(curves[code]), v_at(curves[code - 1])
    print(f"{key}: code {code} at {v0:.3f} V -> code {code - 1}, its 2 GHz point {v1:.3f} V (step {1e3 * (v0 - v1):.0f} mV); "
          f"frequency jump at the switch {100 * (np.polyval(curves[code - 1], v0) / 2e9 - 1):.2f} %", flush=True)
    rows = {}
    for label, pre in [("no precharge", None)] + [(f"precharge {float(e):+g} mV", v1 + float(e) * 1e-3) for e in a.errors.split(",")]:
        t0 = time.time()
        tie_t, tie_v, _, pfd = simulate(curves, code, a, v0, pre)
        peak, settle, final, worst = metrics(tie_t, tie_v, pfd, a)
        slips = int(worst // (1 / FREF))
        rows[label] = dict(peak_tie_s=peak, settle_s=settle, final_tie_s=final, pfd_peak_s=worst, slips=slips)
        print(f"  {label:20s} peak TIE {peak * 1e12:8.1f} ps ({peak / 250e-12:6.2f} UI), PFD peak {worst * 1e9:6.3f} ns, "
              f"back within {a.lock_ps * 1e12:.0f} ps after {settle * 1e9:6.0f} ns, reference cycles slipped {slips}  [{time.time() - t0:.0f} s]", flush=True)
    out = ROOT / "results/analog/pll/top/recode_transient"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{key.replace(':', '_')}_c{code}.json"
    path.write_text(json.dumps(dict(args=vars(a), key=key, code=code, v0=v0, v1=v1, rows=rows), indent=1))
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
