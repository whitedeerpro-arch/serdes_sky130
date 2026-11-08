"""Charge-pump ripple in the locked state and the periodic jitter it puts on the VCO: what the loop filter without Cf carries.

    uv run python analog/pll/cp/tb/ripple/run.py [--k 4] [--conds tt_v1800_t27,...] [--vs 0.95,1.15,edge] [--cctrl 0.25e-12,0.7e-12]
        [--cf 0] [--rz 4130 --ci 18.38e-12] [--ton 0.45e-9] [--kvco 1e9] [--workers 4]

The CP (pll_cp scaled by k: 50 uA references, 50k uA output) gets UP and DN pulses of --ton every 4 ns (a 250 MHz
PFD in lock: both on, then a common reset).  Its output drives Rz + Ci and the VCO control node's capacitance
(--cctrl, plus --cf added).  Two passes per point: equal pulses give the net charge per cycle from UP / DN mismatch;
the DN pulse is then lengthened (or shortened) by the time that cancels it, as the loop does through a static phase
offset.  On the second pass, over the last reference periods: Vctrl ripple, the VCO phase it causes,
phi(t) = 2 pi Kvco integral (Vctrl - mean) dt (drift removed), peak-to-peak as time at 2 GHz; the 250 MHz reference
spur 20 log(Kvco V1 / (2 fref)) from the ripple's fundamental V1; the static phase offset.  Real bias, PDK R.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_cp_ripple_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/cp/ripple"
TREF, F0 = 4e-9, 2e9
PERIODS = 14


def cp_params(k):
    k = float(k)
    return (f"wn={5 * k:g} wp={20 * k:g} wsn={2 * k:g} wsp={4 * k:g} up_wn={0.5 * k:g} up_wp={2 * k:g} "
            f"dn_wn={1 * k:g} dn_wp={2 * k:g} pnf={int(round(4 * k))} nnf={int(round(k))}")


def deck(c, a, v0, cctrl, dn_delay, camp):
    ton = a.ton
    if a.cell == "steer":
        xcp = f"Xcp up dn ctrl vbn vbp ibuf vdd 0 pll_cp_steer {cp_params(a.k)} ntail={a.ntail} cdum={a.cdum:.3e}\nIbuf vdd ibuf 10u"
    else:
        xcp = f"Xcp up dn ctrl vbn vbp vdd 0 pll_cp {cp_params(a.k)}"
    text = spice.render(TEMPLATE, **spice.corner_values(c), XCP=xcp, TON=f"{ton:.4e}", DN_START=f"{1e-9 + dn_delay:.5e}",
                        DN_TON=f"{ton - dn_delay:.5e}", DN_DELAY=f"{dn_delay * 1e12:.1f} ps", RZ=a.rz, CI=a.ci, CCTRL=f"{cctrl + a.cf:.4e}",
                        V0=f"{v0:.4f}", STOP=f"{PERIODS * TREF + 1e-9:.4e}")
    text = spice.binary_output(text)
    camp.mkdir(parents=True, exist_ok=True)
    return bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, a.passive)


def analyse(path, a, cctrl):
    w = spice.Waves(path)
    t, vc, vz = w.t, w["v(ctrl)"], w["v(z)"]
    t1 = 1e-9 + (PERIODS - 4) * TREF          # last four periods
    sel = t >= t1
    # net charge per period from the slow drift of both capacitors
    q = (np.interp(t[-1], t, vz) - np.interp(t1, t, vz)) * a.ci + (np.interp(t[-1], t, vc) - np.interp(t1, t, vc)) * (cctrl + a.cf)
    q_per = q / ((t[-1] - t1) / TREF)
    tt, vv = t[sel], vc[sel]
    # remove the drift (linear) and integrate the ripple into VCO phase
    p = np.polyfit(tt, vv, 1)
    r = vv - np.polyval(p, tt)
    ph = 2 * np.pi * a.kvco * np.concatenate(([0.0], np.cumsum(0.5 * (r[1:] + r[:-1]) * np.diff(tt))))
    ph -= np.polyval(np.polyfit(tt, ph, 1), tt)
    jit_pp = float(np.ptp(ph) / (2 * np.pi * F0))
    v1 = 2 * abs(np.trapezoid(r * np.exp(-2j * np.pi * tt / TREF), tt)) / (tt[-1] - tt[0])
    spur = float(20 * np.log10(max(a.kvco * v1 / (2 * (1 / TREF)), 1e-30)))
    return dict(q_per_c=float(q_per), ripple_pp_v=float(np.ptp(r)), v1_v=float(v1), jitter_pp_s=jit_pp, spur_dbc=spur)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=4)
    ap.add_argument("--conds", default="tt_v1800_t27,ss_v1650_t-40,ff_v1950_t-40,fs_v1650_t85,sf_v1650_t85")
    ap.add_argument("--vs", default="0.95,1.15,edge")
    ap.add_argument("--cctrl", default="0.25e-12,0.7e-12")
    ap.add_argument("--cf", type=float, default=0.0)
    ap.add_argument("--rz", type=float, default=4130)
    ap.add_argument("--ci", type=float, default=18.38e-12)
    ap.add_argument("--ton", type=float, default=0.45e-9)
    ap.add_argument("--kvco", type=float, default=1e9)
    ap.add_argument("--passive", default="tt")
    ap.add_argument("--cell", choices=("drain", "steer"), default="drain", help="pll_cp (drain switches) or pll_cp_steer (current steering + follower)")
    ap.add_argument("--ntail", type=int, default=2, help="steer: follower tail 50 uA x ntail (ideal 10 uA reference)")
    ap.add_argument("--cdum", type=float, default=0.3e-12, help="steer: dummy node capacitor")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{a.cell}_k{a.k:g}_cf{a.cf * 1e12:g}p" + a.tag)
    pts = []
    for tag in a.conds.split(","):
        c = Condition.parse(tag)
        for vv in a.vs.split(","):
            v0 = round(c.supply - 0.41, 3) if vv == "edge" else float(vv)
            for cc in (float(x) for x in a.cctrl.split(",")):
                pts.append((c, v0, cc))
    name = lambda c, v0, cc, n: f"{c.tag}_v{round(v0 * 1000)}_c{round(cc * 1e15)}_{n}"
    # pass 1: equal pulses
    jobs = [(deck(c, a, v0, cc, 0.0, camp / "snap"), camp / name(c, v0, cc, "p1"), dict(timeout_s=900, meta=dict(cond=c.tag, v0=v0, cctrl=cc, dn_delay=0.0)))
            for c, v0, cc in pts]
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)
    icp = 50e-6 * a.k
    second = []
    for c, v0, cc in pts:
        m = analyse(camp / name(c, v0, cc, "p1") / "ripple.raw", a, cc)
        second.append((c, v0, cc, m["q_per_c"] / icp))          # lengthen DN by the time that removes the net charge
    # the DN pulse starts later by dn_delay and ends with UP; a positive net charge needs more DN: start DN earlier
    jobs = [(deck(c, a, v0, cc, -d, camp / "snap"), camp / name(c, v0, cc, "p2"), dict(timeout_s=900, meta=dict(cond=c.tag, v0=v0, cctrl=cc, dn_delay=-d)))
            for c, v0, cc, d in second]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    print(f"{a.cell} CP" + (f" (follower tail {50 * a.ntail} uA, dummy {a.cdum * 1e12:.2f} pF)" if a.cell == "steer" else "") + f", k {a.k:g} (Icp {icp * 1e6:.0f} uA), Rz {a.rz:.0f}, Ci {a.ci * 1e12:.1f} p, Cf added {a.cf * 1e12:.2f} p, pulses {a.ton * 1e12:.0f} ps, Kvco {a.kvco / 1e6:.0f} MHz/V")
    print(f"{'condition':15s} {'Vctrl':>6s} {'Cctrl fF':>8s} | {'net Q fC':>8s} {'offset ps':>9s} | {'ripple mV':>9s} {'jitter pp ps':>12s} {'spur dBc':>8s} {'residual fC':>11s}")
    for (c, v0, cc, d) in second:
        m1 = analyse(camp / name(c, v0, cc, "p1") / "ripple.raw", a, cc)
        m2 = analyse(camp / name(c, v0, cc, "p2") / "ripple.raw", a, cc)
        rows[name(c, v0, cc, "")] = dict(cond=c.tag, v0=v0, cctrl=cc, first=m1, locked=m2, static_offset_s=d)
        print(f"{c.tag:15s} {v0:6.3f} {cc * 1e15:8.0f} | {m1['q_per_c'] * 1e15:8.2f} {d * 1e12:9.1f} | {m2['ripple_pp_v'] * 1e3:9.2f} {m2['jitter_pp_s'] * 1e12:12.3f} "
              f"{m2['spur_dbc']:8.1f} {m2['q_per_c'] * 1e15:11.3f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
