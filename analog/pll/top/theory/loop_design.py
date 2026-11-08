"""CP current and loop filter for the r5 / 4-bit PLL: worst phase margin over every operating point, jitter, area.

    uv run python analog/pll/top/theory/loop_design.py [--ks 2,3,4] [--delay 2e-9] [--pm-min 50] [--ugb-max 25e6]
        [--workmap <campaign>] [--cp <cp window campaign>] [--top 5]

Linear CP-PLL model (serdes_flow.pnoise.Loop: Cf || (Rz + Ci), N = 8, PFD sampling delay).  Icp = 50 uA x k.

Stability plant set: every condition x RC section of the VCO working map, every usable code whose 2 GHz crossing lies
inside the Vctrl operating band (--vlo .. VDD - --headroom), with the local Kvco of the parabola through the simulated
points (0.85 / 1.10 / 1.35 V).  The band is a coarse-tuning policy: the controller keeps the crossing inside it (by
re-coding when the temperature moves it out); below about 1.0 V the tuning curve is flat and Kvco falls to ~0.1 GHz/V.  CP current:
mean of UP and DN at VDD / 2 in the real-bias CP window campaign, same condition and RC section, times k.  Loop filter:
the poly / MIM candidate's measured R and C for the same RC section, R also at the temperature (docs/data/
pll_pvt_first_results.json); in addition every point with the hl and lh sections (R and C apart).

Noise: the seven corners of analog/pll/vco/tb/phase_noise/corner.py (VCO phase noise, CP current noise x k, bias line,
Kvco there), in-band floor --floor, pnoise.synthesize, rms 10 kHz .. 1 GHz of the 2 GHz clock.  The CDR's tracking is
applied afterwards with cdr_jitter.py to the chosen loops (--write-pll writes their pll_noise json).

Cf in the results is the capacitor to build: the VCO control node's own C (--ctrl-load, at each point's Vctrl) and
--c-extra sit in parallel with it in the model.

Search per k over Rz x Ci x Cf / Ci.  Feasible: min PM >= --pm-min at --delay, max UGB <= --ugb-max.  Reported: the
smallest capacitance whose worst rms is within --rms-slack of the best feasible rms, and the largest-margin loop.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import pnoise
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

UI = 250e-12
N = 8
ICP0 = 50e-6
WORKMAP = "results/analog/pll/vco/workmap/20261106T035710Z"
CPWIN = "results/analog/pll/cp/window/20261106T021356Z"
LFDATA = ROOT / "docs/data/pll_pvt_first_results.json"
CORNERS = ROOT / "results/analog/pll/vco/phase_noise_corner"
NOISE_POINTS = ("sf_v1650_t85_rhh_v5", "fs_v1650_t85_rhh_v5", "fs_v1950_t85_rhh_v5", "ss_v1650_t85_rhh_v5",
                "ss_v1650_t-40_rhh_v5", "ff_v1950_t-40_rll_v5", "tt_v1800_t27_rtt_v5")
OUT = ROOT / "results/analog/pll/top/loop_design"


def lf_factors():
    """R and C of the poly / MIM candidate relative to tt 27 C, per section; R temperature factor at tt."""
    rows = {r["name"]: r["metrics"] for r in json.loads(LFDATA.read_text())["passive_conditions"]}
    r0, c0 = rows["tt_27"]["R_small_signal_ohm"], rows["tt_27"]["cap_unit_f"]
    sec = {s: (rows[f"{s}_27"]["R_small_signal_ohm"] / r0, rows[f"{s}_27"]["cap_unit_f"] / c0) for s in ("tt", "ll", "hh", "hl", "lh")}
    temp = {t: rows[f"tt_{t}"]["R_small_signal_ohm"] / r0 for t in (-40, 27, 85)}
    return sec, temp


def crossing(vs, f, target=2e9):
    """2 GHz crossing of the parabola through the simulated points, and the local Kvco there (Hz/V)."""
    p = np.polyfit(vs, f, 2)
    r = np.roots([p[0], p[1], p[2] - target])
    r = [x.real for x in r if abs(x.imag) < 1e-12 and 0.6 <= x.real <= 1.6]
    if not r:
        return None
    v = min(r, key=lambda x: abs(x - 1.1))
    return v, float(np.polyval(np.polyder(p), v))


class CtrlLoad:
    """VCO control-node capacitance while oscillating (analog/pll/vco/tb/ctrl_load), per process and RC section:
    linear in Vctrl along the curve of the measured condition with the nearest supply (1.80 V: mean of 1.65 and 1.95)."""

    def __init__(self, campaign, extra):
        self.extra = extra
        self.curves = {}
        if not campaign:
            return
        rows = json.loads((ROOT / campaign / "summary.json").read_text())["rows"]
        for key, r in rows.items():
            cond, rc, code, v = key.split(":")
            c = Condition.parse(cond)
            self.curves.setdefault((c.process, rc), {}).setdefault(c.supply, []).append((float(v), r["c_f"]))

    def __call__(self, cond, rc, v):
        if not self.curves:
            return self.extra
        c = Condition.parse(cond)
        by = self.curves[(c.process, rc)]
        def at(supply):
            pts = sorted(by[supply])
            return float(np.interp(v, [x[0] for x in pts], [x[1] for x in pts]))
        sup = sorted(by)
        if c.supply in by:
            val = at(c.supply)
        else:
            lo = max([x for x in sup if x < c.supply], default=sup[0])
            hi = min([x for x in sup if x > c.supply], default=sup[-1])
            val = at(lo) if lo == hi else at(lo) + (at(hi) - at(lo)) * (c.supply - lo) / (hi - lo)
        return val + self.extra


def plants(workmap, cpwin, window_lo=1.0, headroom=0.39, cload=None):
    """Arrays over operating points: gain icp_factor * kvco, R factor, C factor; and labels."""
    wm = json.loads((ROOT / workmap / "summary.json").read_text())
    vs = np.array(wm["vs"])
    cp = json.loads((ROOT / cpwin / "summary.json").read_text())["rows"]
    sec, temp = lf_factors()
    rows = []
    for key, r in wm["rows"].items():
        cond, rc = key.split(":")
        c = Condition.parse(cond)
        hi = c.supply - headroom
        icp = (cp[key]["up"] + cp[key]["dn"]) / 2 / ICP0
        for code in r["usable"]:
            x = crossing(vs, r["f"][str(code)])
            if x and window_lo <= x[0] <= hi and x[1] > 0:
                cc = cload(cond, rc, x[0]) if cload else 0.0
                for lf in (rc, "hl", "lh"):
                    rf, cf = sec[lf]
                    rows.append((icp * x[1], rf * temp.get(c.temp, 1.0), cf, key, code, x[1], icp, lf, cc))
    g = np.array([x[0] for x in rows])
    return dict(g=g, rf=np.array([x[1] for x in rows]), cf=np.array([x[2] for x in rows]),
                label=[f"{x[3]} code {x[4]} LF {x[7]}" for x in rows], kvco=np.array([x[5] for x in rows]), icp=np.array([x[6] for x in rows]),
                cctrl=np.array([x[8] for x in rows]))


def margins(p, k, rz, ci, cf, delay, f):
    """UGB and PM per plant for one loop (vectorised over plants)."""
    s = 2j * np.pi * f[None, :]
    R, Ci, Cf = rz * p["rf"][:, None], ci * p["cf"][:, None], cf * p["cf"][:, None] + p["cctrl"][:, None]
    z = (1 + s * R * Ci) / (s * (Ci + Cf) * (1 + s * R * Ci * Cf / (Ci + Cf)))
    ol = ICP0 * k * p["g"][:, None] * z / (s * N) * np.exp(-s * delay)
    mag = np.abs(ol)
    i = np.argmax(mag < 1, axis=1)                       # first grid point below unity
    lo = np.clip(i - 1, 0, None)
    a, b = np.log(mag[np.arange(len(i)), lo]), np.log(mag[np.arange(len(i)), i])
    w = np.where(a != b, a / (a - b), 0.0)
    lf = np.log(f)
    ugb = np.exp(lf[lo] + w * (lf[i] - lf[lo]))
    ph = np.unwrap(np.angle(ol), axis=1)
    pm = 180 + np.degrees(ph[np.arange(len(i)), lo] + w * (ph[np.arange(len(i)), i] - ph[np.arange(len(i)), lo]))
    return ugb, pm


def noise_inputs(floor, cload=None):
    f = np.logspace(4, 9, 601)
    out = {}
    for name in NOISE_POINTS:
        st = json.loads((CORNERS / name / "state.json").read_text())
        pn = json.loads((ROOT / st["isf"] / "phase_noise.json").read_text())
        f_v, l_v = np.array(pn["offsets"]), np.array(pn["total"])
        l_vco = 10 ** np.interp(np.log10(f), np.log10(f_v), np.log10(l_v))
        ext = f > f_v[-1]
        l_vco[ext] = l_v[-1] * (f_v[-1] / f[ext]) ** 2
        cpd = json.loads((ROOT / st["cp"] / "summary.json").read_text())["cases"]["real"]
        s_cp = np.exp(np.interp(np.log(f), np.log(cpd["f"]), np.log(cpd["s"])))
        bs = json.loads((ROOT / st["bias"] / "summary.json").read_text())["conditions"]
        cond = name.split("_r")[0]
        b = bs.get(cond) or next(iter(bs.values()))
        s_b = np.exp(np.interp(np.log(f), np.log(b["vcml"]["f"]), np.log(np.array(b["vcml"]["v"]) ** 2)))
        rc = name.split("_r")[1][:2]
        out[name] = dict(f=f, f0=pn["f0"], l_vco=l_vco, cp=pnoise.cp_sampled_psd(f, s_cp, 0.11), l_bias=pnoise.bias_line_l(f, s_b, st["kb"]),
                         kvco=st["kvco"], floor=floor, cctrl=cload(cond, rc, st["tune"]["vctrl"]) if cload else 0.0)
    return out


def jitter(nz, k, rz, ci, cf, delay):
    res = {}
    for name, d in nz.items():
        lp = pnoise.Loop(icp=ICP0 * k, rz=rz, ci=ci, cf=cf + d["cctrl"], kvco=d["kvco"], n=N, delay=delay)
        o = pnoise.synthesize(d["f"], lp, d["l_vco"], d["floor"], d["cp"] * k, l_bias=d["l_bias"])
        res[name] = pnoise.rms_jitter(d["f"], o["total"], d["f0"])
    return res


def evaluate(a, cload):
    """One loop: margins over the plant set, and per noise corner a pll_noise-format json for cdr_jitter.py."""
    k, rz, ci, cf = (float(x) for x in a.evaluate.split(","))
    p = plants(a.workmap, a.cp, a.vlo, a.headroom, cload)
    f = np.logspace(5, np.log10(3e8), 640)
    ugb, pm = margins(p, k, rz, ci, cf, a.delay, f)
    nz = noise_inputs(a.floor, cload)
    camp = OUT / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_eval_k{k:g}_rz{rz / 1e3:g}k_ci{ci * 1e12:g}p_cf{cf * 1e12:g}p" + a.tag)
    camp.mkdir(parents=True)
    print(f"k {k:g}, Rz {rz / 1e3:.2f} k, Ci {ci * 1e12:.2f} p, Cf {cf * 1e12:.3f} p (+ control node {p['cctrl'].min() * 1e15:.0f}-{p['cctrl'].max() * 1e15:.0f} fF): "
          f"UGB {ugb.min() / 1e6:.1f}-{ugb.max() / 1e6:.1f} MHz, PM min {pm.min():.1f} deg at {p['label'][int(np.argmin(pm))]}, "
          f"PM at +0.5 ns {(pm - 360 * ugb * 0.5e-9).min():.1f} deg")
    for name, d in nz.items():
        lp = pnoise.Loop(icp=ICP0 * k, rz=rz, ci=ci, cf=cf + d["cctrl"], kvco=d["kvco"], n=N, delay=a.delay)
        o = pnoise.synthesize(d["f"], lp, d["l_vco"], d["floor"], d["cp"] * k, l_bias=d["l_bias"])
        u, m = lp.unity_gain()
        rms = {n: pnoise.rms_jitter(d["f"], v, d["f0"]) for n, v in o.items()}
        (camp / f"pll_noise_{name}.json").write_text(json.dumps(dict(f=d["f"].tolist(), f0=d["f0"], floor=d["floor"], loop=dict(k=k, rz=rz, ci=ci, cf=cf, cctrl=d["cctrl"]),
                                                                     rows=[dict(k=k, icp=ICP0 * k, ci=ci, cf=cf, ugb=u, pm=m, rms=rms, total=o["total"].tolist())])))
        print(f"  {name:22s} Kvco {d['kvco'] / 1e6:5.0f} MHz/V, C ctrl {d['cctrl'] * 1e15:4.0f} fF: UGB {u / 1e6:5.1f} MHz PM {m:5.1f}, rms {rms['total'] * 1e12:5.2f} ps "
              f"(VCO {rms['VCO'] * 1e12:.2f}, Rz {rms['loop filter Rz'] * 1e12:.2f}, CP {rms['CP'] * 1e12:.2f}, floor {rms['reference, PFD, divider'] * 1e12:.2f})", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), ugb=[float(ugb.min()), float(ugb.max())], pm_min=float(pm.min()),
                                                       pm_min_d25=float((pm - 360 * ugb * 0.5e-9).min()), worst=p["label"][int(np.argmin(pm))]), indent=1))
    print(camp.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ks", default="2,3,4")
    ap.add_argument("--delay", type=float, default=2e-9)
    ap.add_argument("--pm-min", type=float, default=50.0)
    ap.add_argument("--ugb-max", type=float, default=25e6)
    ap.add_argument("--floor", type=float, default=-125.0)
    ap.add_argument("--rms-slack", type=float, default=0.05)
    ap.add_argument("--workmap", default=WORKMAP)
    ap.add_argument("--cp", default=CPWIN)
    ap.add_argument("--vlo", type=float, default=1.0, help="lower edge of the Vctrl operating band (coarse code keeps the crossing inside)")
    ap.add_argument("--headroom", type=float, default=0.39, help="upper edge VDD - this (CP window, 5 %% droop)")
    ap.add_argument("--ctrl-load", help="analog/pll/vco/tb/ctrl_load campaign: VCO control-node C added to Cf per point")
    ap.add_argument("--c-extra", type=float, default=40e-15, help="other fixed C on the control node (CP switches, precharge gate), F")
    ap.add_argument("--top", type=int, default=3)
    ap.add_argument("--evaluate", metavar="K,RZ,CI,CF", help="evaluate one loop instead of searching; writes pll_noise json per noise corner")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    cload = CtrlLoad(a.ctrl_load, a.c_extra)
    if a.evaluate:
        return evaluate(a, cload)
    p = plants(a.workmap, a.cp, a.vlo, a.headroom, cload)
    nz = noise_inputs(a.floor, cload)
    f = np.logspace(5, np.log10(3e8), 320)
    print(f"control node C (VCO + {a.c_extra * 1e15:.0f} fF) {p['cctrl'].min() * 1e15:.0f}-{p['cctrl'].max() * 1e15:.0f} fF; "
          f"{len(p['g'])} operating points (condition x RC x code x LF section); Kvco {p['kvco'].min() / 1e6:.0f}-{p['kvco'].max() / 1e6:.0f} MHz/V, "
          f"CP factor {p['icp'].min():.3f}-{p['icp'].max():.3f}; gain spread {p['g'].max() / p['g'].min():.2f}x; LF R x{p['rf'].min():.3f}-{p['rf'].max():.3f}, C x{p['cf'].min():.3f}-{p['cf'].max():.3f}", flush=True)
    camp = OUT / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + a.tag)
    camp.mkdir(parents=True)
    rzs = np.geomspace(1.5e3, 20e3, 24)
    cis = np.geomspace(2e-12, 60e-12, 24)
    ratios = (0.0, 1 / 40, 1 / 30, 1 / 20, 1 / 15, 1 / 10, 1 / 7)          # 0: the control node's own C only
    result = {}
    for k in (float(x) for x in a.ks.split(",")):
        rows = []
        for rz in rzs:
            for ci in cis:
                for q in ratios:
                    cf = ci * q
                    ugb, pm = margins(p, k, rz, ci, cf, a.delay, f)
                    rows.append(dict(rz=rz, ci=ci, cf=cf, pm_min=float(pm.min()), ugb_min=float(ugb.min()), ugb_max=float(ugb.max()),
                                     pm_min_d25=float((pm - 360 * ugb * 0.5e-9).min()), worst=p["label"][int(np.argmin(pm))]))
        feas = [r for r in rows if r["pm_min"] >= a.pm_min and r["ugb_max"] <= a.ugb_max]
        for r in feas:
            j = jitter(nz, k, r["rz"], r["ci"], r["cf"], a.delay)
            r.update(rms=j, rms_worst=max(j.values()), cap_pf=(r["ci"] + r["cf"]) * 1e12)
        if not feas:
            best = max(rows, key=lambda r: r["pm_min"])
            print(f"k={k:g}: no loop with min PM >= {a.pm_min} and UGB <= {a.ugb_max / 1e6:.0f} MHz; best min PM {best['pm_min']:.1f} deg "
                  f"(Rz {best['rz'] / 1e3:.2f} k, Ci {best['ci'] * 1e12:.1f} p, Cf {best['cf'] * 1e12:.2f} p, UGB {best['ugb_min'] / 1e6:.1f}-{best['ugb_max'] / 1e6:.1f} MHz)", flush=True)
            result[str(k)] = dict(feasible=0, best_margin=best)
            continue
        best_rms = min(r["rms_worst"] for r in feas)
        small = sorted((r for r in feas if r["rms_worst"] <= best_rms * (1 + a.rms_slack)), key=lambda r: r["cap_pf"])[:a.top]
        safe = sorted(feas, key=lambda r: -r["pm_min"])[:a.top]
        result[str(k)] = dict(feasible=len(feas), best_rms_ps=best_rms * 1e12, smallest=small, largest_margin=safe)
        print(f"\nk={k:g} (Icp {ICP0 * k * 1e6:.0f} uA): {len(feas)}/{len(rows)} feasible; best worst-corner rms {best_rms * 1e12:.2f} ps", flush=True)
        print(f"  {'':9s} {'Rz k':>6s} {'Ci pF':>6s} {'Cf pF':>6s} {'C pF':>6s} {'UGB MHz':>11s} {'PM min':>6s} {'+0.5ns':>6s} {'rms ps':>6s}  worst PM point")
        for tag, lst in (("smallest", small), ("margin", safe)):
            for r in lst:
                print(f"  {tag:9s} {r['rz'] / 1e3:6.2f} {r['ci'] * 1e12:6.2f} {r['cf'] * 1e12:6.3f} {r['cap_pf']:6.2f} {r['ugb_min'] / 1e6:5.1f}-{r['ugb_max'] / 1e6:4.1f} "
                      f"{r['pm_min']:6.1f} {r['pm_min_d25']:6.1f} {r['rms_worst'] * 1e12:6.2f}  {r['worst']}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), points=len(p["g"]), kvco_range=[float(p["kvco"].min()), float(p["kvco"].max())],
                                                       cp_factor_range=[float(p["icp"].min()), float(p["icp"].max())], result=result), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
