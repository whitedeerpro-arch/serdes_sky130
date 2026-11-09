"""Coarse re-coding with Vctrl hysteresis over temperature, from a VCO working map; no simulation.

    uv run python analog/pll/vco/tb/tuning/recode_policy.py [<workmap campaign>] [--vlo 0.85,0.9,0.95,1.0] [--edge-margin 0.02]
        [--margin 0.02] [--dt 0.5]

Policy (window comparator on Vctrl, Kvco > 0, a higher code is slower):
  Vctrl > Vhi  ->  code - 1 (the loop re-acquires, Vctrl falls by about one code step)
  Vctrl < Vlo  ->  code + 1
Vhi = VDD - 0.39 V (CP window upper edge) - --edge-margin; Vlo swept.  A switch back needs the temperature to return past a
different point (Schmitt behaviour) as long as the band is wider than the code step at that point; the gap in kelvin is
the hysteresis.  Start: the code whose 2 GHz point is nearest the band centre at the start temperature.

Per chip (MOS x VDD x RC section): Vctrl and Kvco of each code at -40 / 27 / 85 C from the parabola through the simulated
points; a quadratic in T in between.  Temperature profiles: -40 -> 85 -> -40, 85 -> -40 -> 85, 27 -> 85 -> -40 -> 27.
Reported per band: chips where the policy never leaves the band (no needed code unsimulated, no switch that lands outside
or within --margin of the opposite threshold), switches per full excursion, the smallest hysteresis, and the Kvco range
of every visited point (the loop's plant set).
"""
import argparse
import json
from collections import defaultdict

import numpy as np

from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

WORKMAP = "results/analog/pll/vco/workmap/20261106T035710Z"
TEMPS = (-40, 27, 85)


def crossing(vs, f, target=2e9):
    p = np.polyfit(vs, f, 2)
    r = [x.real for x in np.roots([p[0], p[1], p[2] - target]) if abs(x.imag) < 1e-12 and 0.6 <= x.real <= 1.6]
    if not r:
        return None
    v = min(r, key=lambda x: abs(x - 1.1))
    return v, float(np.polyval(np.polyder(p), v)), np.polyder(p)


def chips(workmap):
    wm = json.loads((ROOT / workmap / "summary.json").read_text())
    vs = np.array(wm["vs"])
    out = defaultdict(lambda: defaultdict(dict))            # (process, supply, rc) -> code -> temp -> (v, kvco)
    for key, r in wm["rows"].items():
        cond, rc = key.split(":")
        c = Condition.parse(cond)
        for code, f in r["f"].items():
            x = crossing(vs, f)
            if x:
                out[(c.process, c.supply, rc)][int(code)][c.temp] = x
    return out


ESTIMATED = set()        # (chip, code) whose Vctrl(T) leans on a neighbour's temperature slope


def curve(points, slope=None, tag=None):
    """Vctrl(T) and Kvco(T) of one code from the temperatures where it was simulated: quadratic through three,
    linear through two; one point: the chip's median slope (dV/dT, dK/dT) through it, recorded in ESTIMATED."""
    ts = [t for t in TEMPS if t in points]
    if len(ts) >= 2:
        deg = 2 if len(ts) == 3 else 1
        pv = np.polyfit(ts, [points[t][0] for t in ts], deg)

        def at(t):
            # Kvco: each simulated temperature's own tuning curve at today's Vctrl, interpolated in T (never extrapolated in T)
            v = float(np.polyval(pv, t))
            ks = [float(np.polyval(points[x][2], v)) for x in ts]
            return v, float(np.interp(t, ts, ks))
        return at
    if len(ts) == 1 and slope is not None:
        t0, (v0, k0, dp) = ts[0], points[ts[0]]
        if tag is not None:
            ESTIMATED.add(tag)
        # Vctrl moves with the chip's slope; Kvco from this code's own tuning curve at that Vctrl (not extrapolated in T)
        return lambda t: (v0 + slope[0] * (t - t0), float(np.polyval(dp, v0 + slope[0] * (t - t0))))
    return None


def slopes(codes):
    """Median dVctrl/dT and dKvco/dT of the codes simulated at two or more temperatures."""
    sv, sk = [], []
    for p in codes.values():
        ts = [t for t in TEMPS if t in p]
        if len(ts) >= 2:
            sv.append((p[ts[-1]][0] - p[ts[0]][0]) / (ts[-1] - ts[0]))
            sk.append((p[ts[-1]][1] - p[ts[0]][1]) / (ts[-1] - ts[0]))
    return (float(np.median(sv)), float(np.median(sk))) if sv else None


START = "centre"          # or "temperature": the target rises with the start temperature (PTAT-aware selection)


def target(t0, vlo, vhi):
    if START == "temperature":
        return vlo + (vhi - vlo) * (0.15 + 0.7 * (t0 + 40) / 125)     # cold start low in the band, hot start high
    return (vlo + vhi) / 2


def run_profile(codes, profile, vlo, vhi, margin, chip=None, pick=None):
    """Walk a temperature profile; returns (ok, switches, events, visited Kvco, reason).  pick(cur, t0, vlo, vhi) -> start
    code or None overrides the power-up selection (default: the code nearest target())."""
    sl = slopes(codes)
    cur = {k: curve(p, sl, (chip, k)) for k, p in codes.items()}
    t0 = profile[0]
    if pick is not None:
        k = pick(cur, t0, vlo, vhi)
        if k is None:
            return False, 0, [], [], f"power-up selection found no code at {t0} C"
    else:
        start = [(abs(cur[k](t0)[0] - target(t0, vlo, vhi)), k) for k in cur if cur[k] and vlo <= cur[k](t0)[0] <= vhi]
        if not start:
            return False, 0, [], [], f"no code inside the band at {t0} C"
        k = min(start)[1]
    events, kv = [], []
    for t in profile:
        v, kk = cur[k](t)
        if v > vhi or v < vlo:
            new = k - 1 if v > vhi else k + 1
            if new not in cur or cur[new] is None:
                return False, len(events), events, kv, f"code {new} needed at {t:.1f} C, not simulated"
            nv = cur[new](t)[0]
            room = (nv - vlo) if v > vhi else (vhi - nv)
            events.append(dict(t=float(t), frm=k, to=new, v_after=nv, room=room))
            if not (vlo <= nv <= vhi) or room < margin:
                return False, len(events), events, kv, f"switch {k}->{new} at {t:.1f} C lands at {nv:.3f} V (room {room * 1e3:.0f} mV)"
            k = new
            v, kk = cur[k](t)
        kv.append(kk)
    return True, len(events), events, kv, ""


def hysteresis(codes, vlo, vhi):
    """For each adjacent pair: T1 where the slower code reaches Vhi (switch to the faster), T2 where the faster reaches Vlo."""
    out = []
    ts = np.linspace(-40, 85, 501)
    sl = slopes(codes)
    for k in codes:
        if k - 1 not in codes:
            continue
        a, b = curve(codes[k], sl), curve(codes[k - 1], sl)
        if not a or not b:
            continue
        va = np.array([a(t)[0] for t in ts])
        vb = np.array([b(t)[0] for t in ts])
        up = ts[np.argmax(va >= vhi)] if (va >= vhi).any() else None
        dn = ts[::-1][np.argmax(vb[::-1] <= vlo)] if (vb <= vlo).any() else None
        if up is not None and dn is not None:
            out.append(float(up - dn))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workmap", nargs="?", default=WORKMAP)
    ap.add_argument("--vlo", default="0.85,0.9,0.95,1.0")
    ap.add_argument("--edge-margin", type=float, default=0.02)
    ap.add_argument("--margin", type=float, default=0.02, help="post-switch distance to the opposite threshold")
    ap.add_argument("--dt", type=float, default=0.5)
    ap.add_argument("--start", choices=("centre", "temperature"), default="centre", help="power-up code: nearest the band centre, or a target that rises with the start temperature")
    a = ap.parse_args()
    global START
    START = a.start
    data = chips(a.workmap)
    up = np.arange(-40, 85 + a.dt, a.dt)
    profiles = {"cold start": np.r_[up, up[::-1]], "hot start": np.r_[up[::-1], up], "room start": np.r_[np.arange(27, 85 + a.dt, a.dt), up[::-1], np.arange(-40, 27 + a.dt, a.dt)]}
    result = {}
    for vlo in (float(x) for x in a.vlo.split(",")):
        ok_chips, fails, sw, kvs, hys, never = 0, [], [], [], [], 0
        for chip, codes in sorted(data.items()):
            vhi = chip[1] - 0.39 - a.edge_margin
            good, chip_sw = True, 0
            for pname, prof in profiles.items():
                ok, n, ev, kv, why = run_profile(codes, prof, vlo, vhi, a.margin, chip)
                if not ok:
                    good = False
                    fails.append(f"{chip[0]} {chip[1]:.2f} V {chip[2]} {pname}: {why}")
                    break
                sw.append(n)
                chip_sw += n
                kvs += kv
            if good:
                ok_chips += 1
                never += chip_sw == 0
                hys += hysteresis(codes, vlo, vhi)
        kvs = np.array(kvs) / 1e6
        result[str(vlo)] = dict(ok=ok_chips, never_switch=never, start=a.start, chips=len(data), fails=fails, switches_max=int(max(sw)) if sw else None,
                                hysteresis_min_k=min(hys) if hys else None, kvco=[float(kvs.min()), float(kvs.max())] if len(kvs) else None)
        print(f"band {vlo:.2f} V .. VDD-{0.39 + a.edge_margin:.2f} V, start {a.start}: {ok_chips}/{len(data)} chips keep it over all three profiles ({never} never switch); "
              f"switches per profile <= {result[str(vlo)]['switches_max']}; smallest hysteresis "
              f"{(min(hys) if hys else float('nan')):.1f} K; visited Kvco {kvs.min() if len(kvs) else float('nan'):.0f}-{kvs.max() if len(kvs) else float('nan'):.0f} MHz/V", flush=True)
        est = {c for c in ESTIMATED if c[0] in data}
        print(f"    codes with a single simulated temperature, slope borrowed from the chip: {len(est)}")
        ESTIMATED.clear()
        for f in fails[:6]:
            print("   ", f)
        if len(fails) > 6:
            print(f"    ... {len(fails) - 6} more")
    out = ROOT / "results/analog/pll/vco/recode_policy"
    out.mkdir(parents=True, exist_ok=True)
    import time
    path = out / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    path.write_text(json.dumps(dict(workmap=a.workmap, edge_margin=a.edge_margin, margin=a.margin, result=result), indent=1))
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
