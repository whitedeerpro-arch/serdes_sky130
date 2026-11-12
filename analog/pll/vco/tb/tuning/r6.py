"""VCO r6 (pll_vco_ring4_r6: 5-bit bank, layout parasitics in the schematic): sizing at the range ends, then the code map.

    uv run python analog/pll/vco/tb/tuning/r6.py ends --cands "a=rload=362 wt=22.1;b=..." [--workers 3] [--resume C]
    uv run python analog/pll/vco/tb/tuning/r6.py map [--passive tt,hh,ll] [--workers 3] [--resume C]
    uv run python analog/pll/vco/tb/tuning/r6.py check --resume C [--n 12]      # simulate the model's lock points

Bench of workmap.py (ring + four buffers, real bias), resistors as the layout extracts them (the ring's loads are PDK
fixed-width devices in the netlist; rcorner.to_pdk_fixed for the rest).  Control window [0.90 V, VDD - 0.44 V] (CP
headroom).  Per point 14 ns at a 4 ps step, frequency over the last 5 ns: against 24 ns / 2 ps (speed_check,
2026-11-12, three corners) the frequency is settled to 5e-5 from 7 ns on and the 4 ps step costs -0.017 %; a point
whose frequency differs by more than 0.05 % between the two halves of the window is reported as not settled.

ends   per candidate (parameter overrides of the ring instance): slow end FS 85 C hh code 0 at the window top, fast end
       SF ll code 31 at the window floor.  Margin = how far 2 GHz is inside the reachable range, in % of frequency.
map    45 conditions x passive corners, codes 0 / 15 / 31 at four Vctrl spanning the window.  Model: at each Vctrl
       1 / f is a parabola in the code through the three simulated codes (the period goes with the capacitance; residual
       of that law < 0.8 % on the 4-bit map), f(Vctrl) monotone cubic through the four points.  From it: for every
       condition the codes that put 2 GHz inside the window, the Vctrl of each, the window in LSB steps; for every chip
       (MOS, supply, passive) the codes that hold 2 GHz from -40 to 85 C.
check  simulates conditions at the model's (code, Vctrl) lock point and prints the model error.
"""
import argparse
import importlib.util
import json
import re
import time

import numpy as np
from scipy.interpolate import PchipInterpolator

from serdes_flow import spice
from serdes_flow.corners import Condition, grid45
from serdes_flow.project import ROOT

_w = importlib.util.spec_from_file_location("workmap", ROOT / "analog/pll/vco/tb/tuning/workmap.py")
wm = importlib.util.module_from_spec(_w)
_w.loader.exec_module(wm)
wm.CARDS = "fixed"
wm.STOP, wm.START = 14e-9, 8e-9
DRIFT = 5e-4
RESULTS = ROOT / "results/analog/pll/vco/r6"
NCODE, COARSE, FLOOR, HEAD, TARGET = 32, (0, 15, 31), 0.90, 0.44, 2e9
SLOW = ["fs_v1650_t85:hh", "fs_v1800_t85:hh", "fs_v1950_t85:hh"]
FAST = ["sf_v1650_t-40:ll", "sf_v1800_t-40:ll", "sf_v1950_t-40:ll", "sf_v1800_t27:ll"]
GAIN = ["sf_v1650_t85:hh", "ss_v1650_t85:hh", "ss_v1650_t-40:hh"]      # lowest loop gain (r3 failed at SF 1.65 V 85 C hh): swing at mid code


def top(c):
    return round(c.supply - HEAD, 3)


def vgrid(c):
    return [round(float(v), 3) for v in np.linspace(FLOOR, top(c), 4)]


def jobs_for(vc, todo, params):
    """Decks for the points of todo = [(rc, condition, code, v)] that have no complete waveform under vc."""
    groups = {}
    for rc, c, code, v in todo:
        if spice.case_output(vc, f"{c.process}_{rc}", wm.name(c, code, v), wm.STOP) is None:
            groups.setdefault((c.process, rc), []).append((c, code, v))
    wm.RING_PARAMS = params
    out = []
    tran = f"tran 2p {wm.STOP:.4e} {wm.START:.4e}"
    for (p, rc), pts in groups.items():
        text = wm.deck(p, rc, pts, vc / "snap" / f"{p}_{rc}", 5)
        assert text.count(tran) == len(pts)
        out.append((text.replace(tran, "tran 4p" + tran[7:]), spice.next_run_dir(vc, f"{p}_{rc}"),
                    dict(timeout_s=60 * len(pts) + 900, meta=dict(process=p, passive=rc, points=len(pts), params=params))))
    wm.RING_PARAMS = ""
    return out


UNSETTLED = []


def read(camp, rc, c, code, v):
    """(frequency, differential swing) over the last 5 ns, None without a complete waveform; notes unsettled points."""
    p = spice.case_output(camp, f"{c.process}_{rc}", wm.name(c, code, v), wm.STOP)
    if p is None:
        return None
    w = spice.Waves(p)
    y = w["v(v0p)"] - w["v(v0n)"]
    sel = w.t >= wm.STOP - 5e-9
    e, s = wm.crossings(w.t[sel], y[sel])
    r = e[s > 0]
    if len(r) < 6:
        return None
    h = len(r) // 2
    f1, f2 = h / (r[h] - r[0]), (len(r) - 1 - h) / (r[-1] - r[h])
    if abs(f2 / f1 - 1) > DRIFT:
        UNSETTLED.append((f"{c.tag}:{rc} code {code} {v} V", f2 / f1 - 1))
    return float((len(r) - 1) / (r[-1] - r[0])), float(np.ptp(y[sel]))


def run(jobs, workers):
    print(f"{len(jobs)} decks, {sum(j[2]['meta']['points'] for j in jobs)} points", flush=True)
    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        if not ex.ok:
            print(f"deck {ex.run_dir}: {ex.log_failures[:2]}", flush=True)


def ends(a, camp):
    cands = dict(x.split("=", 1) for x in a.cands.split(";"))
    todo = []
    for spec in SLOW + FAST:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        vs = [round(top(c) - 0.2, 3), round(top(c) - 0.1, 3), top(c)] if spec in SLOW else [FLOOR, FLOOR + 0.1, FLOOR + 0.2]
        todo += [(rc, c, 0 if spec in SLOW else NCODE - 1, v) for v in vs]
    gain = []
    for spec in GAIN:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        gain += [(rc, c, k, round((FLOOR + top(c)) / 2, 3)) for k in (4, 16)]
    todo += gain
    jobs = [j for name, par in cands.items() for j in jobs_for(camp / name, todo, par)]
    run(jobs, a.workers)
    rows = {}
    print("margin % = 2 GHz inside the range end (slow: f at window top above 2 GHz; fast: f at window floor below 2 GHz); swing mVpp diff")
    for name, par in cands.items():
        r = {}
        for rc, c, code, v in todo:
            m = read(camp / name, rc, c, code, v)
            if (rc, c, code, v) in gain:
                rows.setdefault(name, {}).setdefault("gain", {})[f"{c.tag}:{rc}:c{code}"] = m
                continue
            r.setdefault(f"{c.tag}:{rc}", {})[v] = m
        line, worst = f"{name:10s} {par:44s}", {}
        for spec, pts in r.items():
            slow = spec in SLOW
            vend = max(pts) if slow else min(pts)
            if pts[vend] is None:
                line += f" | {spec.split(':')[0]} missing"
                continue
            f, amp = pts[vend]
            mar = (f / TARGET - 1) * (1 if slow else -1)
            vs = sorted(v for v in pts if pts[v])
            fs = [pts[v][0] for v in vs]
            v2 = float(np.interp(TARGET, fs, vs)) if min(fs) <= TARGET <= max(fs) else float("nan")
            rows.setdefault(name, {})[spec] = dict(f_end=f, margin=mar, swing=amp, v_2g=v2, f=dict(zip(map(str, vs), fs)))
            worst["slow" if slow else "fast"] = min(worst.get("slow" if slow else "fast", 9), mar)
            line += f" | {spec.split(':')[0]} {mar * 100:+.1f}% {v2:.3f} V {amp * 1e3:.0f}"
        print(line + f" || worst slow {worst.get('slow', np.nan) * 100:+.1f}% fast {worst.get('fast', np.nan) * 100:+.1f}%", flush=True)
        print("           swing at the low-gain corners: " + ", ".join(f"{k} {m[1] * 1e3:.0f} mVpp at {m[0] / 1e9:.3f} GHz" if m else f"{k} missing"
                                                                       for k, m in rows.get(name, {}).get("gain", {}).items()), flush=True)
    (camp / "ends.json").write_text(json.dumps(dict(cands=cands, rows=rows), indent=1))


def model(camp, rc, c):
    """f(code, v) from the simulated coarse codes; None if a point is missing."""
    vs = vgrid(c)
    pts = [[read(camp, rc, c, k, v) for v in vs] for k in COARSE]
    if any(x is None for row in pts for x in row):
        return None
    inv = np.array([[1 / x[0] for x in row] for row in pts])               # code x v
    fit = [np.polyfit(COARSE, inv[:, j], 2) for j in range(len(vs))]
    curves = [PchipInterpolator(vs, [1 / np.polyval(fit[j], n) for j in range(len(vs))]) for n in range(NCODE)]
    return dict(vs=vs, curves=curves, swing=[[x[1] for x in row] for row in pts])


def lock(m, c):
    """{code: Vctrl of 2 GHz} for the codes that reach 2 GHz inside the window."""
    out = {}
    grid = np.linspace(FLOOR, top(c), 400)
    for n, cv in enumerate(m["curves"]):
        f = cv(grid)
        if f.min() <= TARGET <= f.max():
            out[n] = float(np.interp(TARGET, f, grid))
    return out


def table(a, camp):
    conds = grid45()
    rows, chips, miss = {}, {}, 0
    for rc in a.passive.split(","):
        for c in conds:
            m = model(camp, rc, c)
            if m is None:
                miss += 1
                continue
            lk = lock(m, c)
            f0, f31 = float(m["curves"][0](top(c))), float(m["curves"][NCODE - 1](FLOOR))
            ks = sorted(lk)
            step = float(np.median(np.abs(np.diff([lk[k] for k in ks])))) if len(ks) > 1 else float("nan")
            mid = (FLOOR + top(c)) / 2
            best = min(ks, key=lambda k: abs(lk[k] - mid)) if ks else None
            kv = float(m["curves"][best].derivative()(lk[best])) if ks else float("nan")
            rows[f"{c.tag}:{rc}"] = dict(codes=ks, v={str(k): lk[k] for k in ks}, slow_margin=f0 / TARGET - 1, fast_margin=1 - f31 / TARGET, lsb_v=step,
                                         window_lsb=(top(c) - FLOOR) / step if step == step else float("nan"), best=best, kvco=kv,
                                         swing_min=float(np.min(m["swing"])), swing_max=float(np.max(m["swing"])))
            chips.setdefault((c.process, c.supply, rc), {})[c.temp] = lk
    if not rows:
        print("no complete condition")
        return
    print(f"{len(rows)} conditions with a model, {miss} missing")
    for key, lab in (("slow_margin", "slow end (code 0 at window top above 2 GHz)"), ("fast_margin", "fast end (code 31 at window floor below 2 GHz)")):
        w = sorted(rows.items(), key=lambda kv: kv[1][key])[:4]
        print(f"  {lab}: " + ", ".join(f"{k} {r[key] * 100:+.1f}%" for k, r in w))
    n = np.array([len(r["codes"]) for r in rows.values()])
    wl = np.array([r["window_lsb"] for r in rows.values()])
    kv = np.array([r["kvco"] for r in rows.values()])
    print(f"  codes with 2 GHz inside the window: min {n.min()}, median {int(np.median(n))}, max {n.max()}; conditions with < 2: {int((n < 2).sum())}, < 3: {int((n < 3).sum())}")
    print(f"  window / LSB step: min {np.nanmin(wl):.2f}, median {np.nanmedian(wl):.2f};  Kvco at the centred code {np.nanmin(kv) / 1e6:.0f} .. {np.nanmax(kv) / 1e6:.0f} MHz/V")
    print(f"  swing over the simulated points {min(r['swing_min'] for r in rows.values()) * 1e3:.0f} .. {max(r['swing_max'] for r in rows.values()) * 1e3:.0f} mVpp")
    frozen, bad = {}, []
    for (p, v, rc), t in chips.items():
        if len(t) < 3:
            continue
        common = set.intersection(*(set(x) for x in t.values()))
        # margin of a frozen code: its smallest distance to a window edge over temperature
        tp = v - HEAD
        mar = {k: min(min(x[k] - FLOOR, tp - x[k]) for x in t.values()) for k in common}
        frozen[f"{p}_v{round(v * 1000)}:{rc}"] = dict(codes=sorted(common), best_margin_v=max(mar.values()) if mar else None)
        if not common:
            bad.append(f"{p}_v{round(v * 1000)}:{rc}")
    if frozen:
        bm = [x["best_margin_v"] for x in frozen.values() if x["best_margin_v"] is not None]
        print(f"  chips (MOS, supply, passive) with one code for -40 .. 85 C: {len(frozen) - len(bad)} of {len(frozen)}; best frozen code's edge margin min {min(bm) * 1e3:.0f} mV" + (f"; none: {bad}" if bad else ""))
    (camp / "table.json").write_text(json.dumps(dict(rows=rows, frozen=frozen), indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("ends", "map", "table", "check"))
    ap.add_argument("--cands", default="base=")
    ap.add_argument("--passive", default="tt,hh,ll")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / (a.mode + "_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    camp.mkdir(parents=True, exist_ok=True)
    if a.mode == "ends":
        ends(a, camp)
    elif a.mode == "map":
        from serdes_flow.corners import boundary_first
        todo = [(rc, c, k, v) for rc in a.passive.split(",") for c in boundary_first(grid45()) for k in COARSE for v in vgrid(c)]
        run(jobs_for(camp, todo, ""), a.workers)
        table(a, camp)
    elif a.mode == "table":
        table(a, camp)
    else:
        t = json.loads((camp / "table.json").read_text())["rows"]
        pick = sorted(t, key=lambda k: min(t[k]["slow_margin"], t[k]["fast_margin"]))[: a.n // 2]
        rest = [k for k in t if k not in pick]
        pick += rest[:: max(1, len(rest) // (a.n - len(pick)))][: a.n - len(pick)]
        todo, want = [], {}
        for key in pick:
            if t[key]["best"] is None:
                continue
            cond, rc = key.split(":")
            c = Condition.parse(cond)
            k = t[key]["best"]
            v = round(t[key]["v"][str(k)], 3)
            todo.append((rc, c, k, v))
            want[key] = (c, rc, k, v)
        run(jobs_for(camp / "check", todo, ""), a.workers)
        err = []
        for key, (c, rc, k, v) in want.items():
            m = read(camp / "check", rc, c, k, v)
            if m:
                err.append(m[0] / TARGET - 1)
                print(f"  {key:20s} code {k:2d} at {v:.3f} V: {m[0] / 1e9:.4f} GHz ({err[-1] * 100:+.2f}%)")
        if err:
            print(f"model error at the lock points: {min(err) * 100:+.2f} .. {max(err) * 100:+.2f}%")


if __name__ == "__main__":
    main()
    if UNSETTLED:
        print(f"NOT SETTLED ({len(UNSETTLED)} reads): " + ", ".join(f"{k} {d * 100:+.3f}%" for k, d in UNSETTLED[:12]))
