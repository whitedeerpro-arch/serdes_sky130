"""Local-mismatch MC of the PFD + k = 4 steering CP transfer near zero phase (PLL closure step 6), real bias.

    uv run python analog/pll/pfd/tb/pfd_cp_mc/run.py [--points tt_v1800_t27:1.15,...] [--samples 100] [--chunk 8] [--workers 1]
        [--analyse C]

Per sample one transient: three warm-up periods at zero phase, then one 4 ns period at each phase of PHASES (fb edge
minus ref edge; > 0 = ref leads = net UP).  Net charge per period = integral of i(Vout) over [edge - 0.5 ns, edge + 3.5 ns]
with the CP output held at Vctrl (Vout).  Reported per point: dead-zone check (gain over +-5 ps against gain over
+-40 ps, and the largest deviation from the sample's straight-line fit, in ps of phase; the integration noise is
~0.2 fC = 1 ps per point, so 2 ps local slopes and strict monotonicity are noise tests, kept only as counts), the
zero-charge phase (static offset of the loop: interpolated where the charge changes sign inside PHASES, otherwise
extrapolated along the sample's straight-line fit; the count of extrapolated samples is reported), the charge gain
near zero, and the UP / DN pulse widths in the zero-phase period (the PFD reset width; the lock detector's tau needs it).
Library section <process>_mm (local mismatch only).  Memory: chunk 8 (bias + CP + PFD, ~140 MB per sample assumed).
"""
import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, mc, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_pfd_cp_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/pfd/pfd_cp_mc"
CP_PARAMS = "wn=20 wp=80 wsn=8 wsp=16 up_wn=2 up_wp=8 dn_wn=4 dn_wp=8 pnf=16 nnf=4 ntail=2 cdum=0.3p"
PHASES = [-40e-12, -20e-12, -10e-12, -5e-12, -2e-12, 0.0, 2e-12, 5e-12, 10e-12, 20e-12, 40e-12]
TREF, T0, WARM, TR = 4e-9, 1e-9, 3, 30e-12
ZERO = PHASES.index(0.0)


def edges():
    """ref rising edge times and the phase applied to fb in each period."""
    n = WARM + len(PHASES)
    t = [T0 + k * TREF for k in range(n)]
    ph = [0.0] * WARM + PHASES
    return t, ph


def pwl(times, shifts, vdd):
    pts = [(0.0, 0.0)]
    for t, s in zip(times, shifts):
        r = t + s
        pts += [(r, 0.0), (r + TR, vdd), (r + TREF / 2, vdd), (r + TREF / 2 + TR, 0.0)]
    return " ".join(f"{x:.6e} {y:.4g}" for x, y in pts)


def netlist(c, vout):
    t, ph = edges()
    text = spice.render(TEMPLATE, **spice.corner_values(c), REF_PWL=pwl(t, [0.0] * len(t), c.supply), FB_PWL=pwl(t, ph, c.supply),
                        CP_PARAMS=CP_PARAMS, VOUT=f"{vout:.4f}")
    text = bias.real(text)
    old = "Ibuf vdd ibuf 10u"
    assert text.count(old) == 1 and "vgi_bias" in text
    text = text.replace(old, "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    text, n = re.subn(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: m[1] + f"{c.process}_mm", text, count=1, flags=re.M | re.I)
    assert n == 1
    return text


def analysis(c):
    t, _ = edges()
    tend = t[-1] + TREF
    h = c.supply / 2
    lines = [f"tran 1p {tend:.5e} 0 5p"]
    for i in range(len(PHASES)):
        e = t[WARM + i]
        lines.append(f"meas tran q{i} integ i(Vout) from={e - 0.5e-9:.5e} to={e + 3.5e-9:.5e}")
    e = t[WARM + ZERO]
    lines += [f"meas tran upw trig v(up) val={h:.3f} rise=1 td={e - 0.5e-9:.5e} targ v(up) val={h:.3f} fall=1 td={e - 0.5e-9:.5e}",
              f"meas tran dnw trig v(dn) val={h:.3f} rise=1 td={e - 0.5e-9:.5e} targ v(dn) val={h:.3f} fall=1 td={e - 0.5e-9:.5e}"]
    return "\n".join(lines), tend


def summarize(rows):
    q = np.array([[r[f"q{i}"] for i in range(len(PHASES))] for r in rows], float)
    ph = np.array(PHASES)
    mono = np.all(np.diff(q, axis=1) > 0, axis=1)
    # dead zone = a flat stretch: every local slope at least half the sample's median slope (the zero-charge point
    # itself is offset by mismatch, so the sign at +-2 ps is not the test)
    slope = np.diff(q, axis=1) / np.diff(ph)
    ok_sign = np.all(slope >= 0.5 * np.median(slope, axis=1, keepdims=True), axis=1)
    zero, extrap, resid = [], 0, []
    for row in q:
        a, b = np.polyfit(ph, row, 1)
        resid.append(np.abs(row - (a * ph + b)).max() / a)            # s of phase
        s = np.where(np.diff(np.sign(row)) > 0)[0]
        if len(s):
            zero.append(np.interp(0.0, row[s[0]:s[0] + 2], ph[s[0]:s[0] + 2]))
        else:
            zero.append(-b / a)
            extrap += 1
    zero = np.array(zero)
    i5, j5 = PHASES.index(-5e-12), PHASES.index(5e-12)
    gain = (q[:, j5] - q[:, i5]) / 10e-12                 # A (charge per period per second of phase)
    gout = (q[:, -1] - q[:, 0]) / (ph[-1] - ph[0])
    return dict(n=len(rows), sign_ok=int(ok_sign.sum()), monotonic=int(mono.sum()), zero_phase=zero, gain=gain,
                zero_extrapolated=extrap, gain_ratio=gain / gout, line_resid_s=np.array(resid),
                upw=np.array([r["upw"] for r in rows], float), dnw=np.array([r["dnw"] for r in rows], float), q=q)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:1.15,ss_v1650_t-40:1.0,ff_v1950_t85:1.3,sf_v1650_t-40:1.0,fs_v1650_t85:1.15")
    ap.add_argument("--samples", type=int, default=100)
    ap.add_argument("--chunk", type=int, default=8)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--analyse")
    ap.add_argument("--resume", help="campaign to continue (mc.run_many resumes by chunk identity)")
    a = ap.parse_args()
    camp = (ROOT / (a.analyse or a.resume)) if (a.analyse or a.resume) else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    lets = {f"q{i}": f"q{i}" for i in range(len(PHASES))} | {"upw": "upw", "dnw": "dnw"}
    jobs, owners = [], []
    for spec in a.points.split(","):
        cond, v = spec.split(":")
        c = Condition.parse(cond)
        net = netlist(c, float(v))
        ana, tend = analysis(c)
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis=ana, lets=lets, t_end=tend), camp / cond / f"chunk{k:02d}",
                         dict(timeout_s=900 + 120 * n, meta=dict(point=spec, samples=n, seed=s))))
            owners.append(cond)
    if a.analyse:
        dirs = [d for d in mc.completed(jobs) if d is not None]
        if len(dirs) < len(jobs):
            print(f"{len(jobs) - len(dirs)} of {len(jobs)} chunks without a complete attempt (not analysed)")
    else:
        dirs = mc.run_many(jobs, workers=a.workers)
    out = {}
    print(f"phases {[round(p * 1e12) for p in PHASES]} ps; charge in fC per period; k from the sample count")
    for spec in a.points.split(","):
        cond = spec.split(":")[0]
        rows = [r for d in dirs if d.parent.name == cond for r in mc.read(d)]
        if not rows:
            continue
        s = summarize(rows)
        kf = stats.k_factor(s["n"])
        z = s["zero_phase"][np.isfinite(s["zero_phase"])]
        out[spec] = dict(samples=s["n"], k=kf, no_flat_stretch=s["sign_ok"], monotonic=s["monotonic"],
                         zero_phase_mean_s=float(z.mean()), zero_phase_sd_s=float(z.std(ddof=1)), zero_phase_bound_s=float(abs(z.mean()) + kf * z.std(ddof=1)),
                         zero_phase_extrapolated=s["zero_extrapolated"], zero_phase_range_s=[float(z.min()), float(z.max())],
                         gain_ratio_5_40=[float(s["gain_ratio"].min()), float(s["gain_ratio"].max())],
                         line_resid_max_s=float(s["line_resid_s"].max()),
                         gain_mean_a=float(s["gain"].mean()), gain_min_a=float(s["gain"].min()),
                         upw_s=[float(s["upw"].min()), float(s["upw"].max())], dnw_s=[float(s["dnw"].min()), float(s["dnw"].max())],
                         q_mean_fc=[float(x) for x in s["q"].mean(axis=0) * 1e15])
        o = out[spec]
        print(f"  {spec:20s} n {s['n']:3d} | gain(+-5)/gain(+-40) {o['gain_ratio_5_40'][0]:.2f}..{o['gain_ratio_5_40'][1]:.2f}, "
              f"line residual <= {o['line_resid_max_s'] * 1e12:.1f} ps (2 ps slopes ok {s['sign_ok']}, monotonic {s['monotonic']}) | "
              f"zero phase {o['zero_phase_mean_s'] * 1e12:+.1f} / sd {o['zero_phase_sd_s'] * 1e12:.1f} / bound {o['zero_phase_bound_s'] * 1e12:.1f} ps "
              f"({o['zero_phase_extrapolated']} extrapolated) | "
              f"gain {o['gain_mean_a'] * 1e6:.0f} uA (min {o['gain_min_a'] * 1e6:.0f}) | UP / DN width {o['upw_s'][0] * 1e12:.0f}-{o['upw_s'][1] * 1e12:.0f} / "
              f"{o['dnw_s'][0] * 1e12:.0f}-{o['dnw_s'][1] * 1e12:.0f} ps", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), phases=PHASES, cp=CP_PARAMS, points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
