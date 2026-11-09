"""Power-up coarse-code selection schemes against temperature excursions, from the VCO working map; no simulation.

    uv run python analog/pll/vco/tb/tuning/powerup_policy.py [<workmap campaign>] [--vlo 0.90] [--dvlo 0] [--dvhi 0]
        [--schemes ideal,count3,count2,window3,window1] [--tsense-err 10] [--count-n 64] [--step 5]

Every chip (MOS x VDD x RC) powers up at T0 = -40 .. 85 C (--step) and then walks T0 -> 85 -> -40 -> T0 and
T0 -> -40 -> 85 -> T0 with the run-time rule of recode_policy.py (Vctrl window [Vlo, VDD - 0.41 V], one code per crossing).
Schemes for the power-up code (hardware needed in brackets):

  ideal     exact temperature, target = Vlo + (Vhi - Vlo)(0.15 + 0.7 (T0 + 40) / 125), the nearest code   (reference)
  countK    K temperature classes from an estimate T0 + e (e in {-E, 0, +E}, --tsense-err), an absolute precharge target
            per class (B2 reference, 0.95-1.35 V in 26.7 mV steps), the code whose open-loop frequency at the target is
            nearest 2 GHz as an N-reference-cycle count would see it          [frequency counter, temperature estimate]
  windowK   no counter: closed-loop search, step one code whenever Vctrl leaves the window; the search starts at the fast
            end (cold class), the middle (room) or the slow end (hot) -- the first code that locks inside the window
            wins                                                              [window comparators, temperature estimate]
  window1   as windowK from the middle code, no temperature information        [window comparators only]
  pwinK     windowK with power-up thresholds: the ladders move during the search (cold: first code from the fast end
            above Vlo + d_cold; hot: first from the slow end below Vhi - d_hot; middle: from the fast end above
            Vlo + d_mid, --pwin), then return to the run-time codes             [window comparators, temperature estimate]
  slowvK    from the slow end only (the divider never runs more than ~one code step above 2 GHz): the first code with
            Vctrl <= VDD - stop(class) (hi comparator, ladder moved), back one code if that is below Vlo
  slowgK    as slowvK with absolute stops (lo comparator's ground-referenced ladder)
                                                                                [window comparators, temperature estimate]

Threshold errors: --dvlo / --dvhi shift the comparator trip points (offset + reference error) from their design values.
Reported per scheme: (chip, T0) cases that keep the window over both excursions, chips that never switch from any T0,
and the switch count of the worst excursion.
"""
import argparse
import importlib.util
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np

from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("recode_policy", Path(__file__).with_name("recode_policy.py"))
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

B2_LO, B2_HI, B2_STEP = 0.95, 1.35, 0.4 / 15
LADDER = dict(g_hi=1.0)   # per-chip relative gain of the VDD-referenced ladder (stop thresholds share it with vhi)
CLASS_EDGES = {2: (22.5,), 3: (0.0, 50.0), 4: (-10.0, 22.5, 55.0)}


def classes(k):
    """Class edges and representative temperatures (class centres over -40 .. 85 C)."""
    edges = (-40.0,) + CLASS_EDGES[k] + (85.0,)
    return CLASS_EDGES[k], [(a + b) / 2 for a, b in zip(edges[:-1], edges[1:])]


def frac(t):
    return 0.15 + 0.7 * (t + 40) / 125


def b2(v):
    """Nearest B2 precharge code voltage."""
    return B2_LO + B2_STEP * round((min(max(v, B2_LO), B2_HI) - B2_LO) / B2_STEP)


def lock_points(cur, t0):
    return {k: cur[k](t0) for k in cur if cur[k]}


def pick_ideal(cur, t0, vlo, vhi):
    pts = lock_points(cur, t0)
    tgt = vlo + (vhi - vlo) * frac(t0)
    inside = [(abs(v - tgt), k) for k, (v, kv) in pts.items() if vlo <= v <= vhi]
    return min(inside)[1] if inside else None


def make_count(nclass, err, n_count, vlo_design, targets):
    edges, reps = classes(nclass)

    def pick(cur, t0, vlo, vhi):
        c = int(np.searchsorted(edges, t0 + err))
        tgt = b2(targets[c])
        pts = lock_points(cur, t0)
        # open-loop frequency at the precharge target, linearised at the lock point; the count resolves 1 / N
        best = None
        for k, (v, kv) in pts.items():
            df = kv * (tgt - v) / 2e9
            q = round(df * n_count)
            key = (abs(q), (v if c < len(reps) // 2 else -v))        # ties: cold classes take the lower Vctrl
            if best is None or key < best[0]:
                best = (key, k)
        return best[1] if best else None
    return pick


def make_window(nclass, err):
    edges, reps = classes(nclass) if nclass > 1 else ((), [27.0])

    def pick(cur, t0, vlo, vhi):
        pts = lock_points(cur, t0)
        if not pts:
            return None
        lo, hi = min(pts), max(pts)
        c = int(np.searchsorted(edges, t0 + err)) if edges else 0
        k = 0 if (nclass > 1 and c == 0) else (15 if (nclass > 1 and c == nclass - 1) else 7)
        for _ in range(32):
            if k < lo:                       # faster than every code that reaches 2 GHz: Vctrl rails low
                k += 1
                continue
            if k > hi:
                k -= 1
                continue
            v = pts[k][0]
            if v > vhi:
                if k - 1 not in pts and k - 1 >= lo:
                    return None
                k -= 1
            elif v < vlo:
                if k + 1 not in pts and k + 1 <= hi:
                    return None
                k += 1
            else:
                return k
        return None
    return pick


def make_pwin(nclass, err, deltas):
    """Window search with power-up thresholds (the run-time ladders set to other codes during the search): cold class
    from the fast end, accept the first code with Vctrl >= Vlo + d_cold; hot class from the slow end, accept the first
    with Vctrl <= Vhi - d_hot; middle classes from the fast end with Vlo + d_mid.  No counter; VDD enters through Vhi."""
    edges = classes(nclass)[0]

    def pick(cur, t0, vlo, vhi):
        pts = lock_points(cur, t0)
        if not pts:
            return None
        c = int(np.searchsorted(edges, t0 + err))
        order = sorted(pts)
        if c == nclass - 1:
            for k in reversed(order):                      # slow end first: Vctrl falls code by code
                if pts[k][0] <= vhi - deltas[-1]:
                    return k if pts[k][0] >= vlo else None
            return None
        d = deltas[0] if c == 0 else deltas[1]
        for k in order:                                    # fast end first: Vctrl rises code by code
            if pts[k][0] >= vlo + d:
                return k if pts[k][0] <= vhi else None
        return None
    return pick


def make_slow(nclass, err, stops, ref):
    """Search from the slow end only (code 15 -> faster; the divider never sees more than ~one code step above 2 GHz):
    stop at the first code whose locked Vctrl is at or below Vstop(class); if that code is below Vlo (a step wider
    than the room under Vstop), go back one code.  ref 'v': Vstop = VDD - stop (the hi comparator's VDD-referenced
    ladder), 'g': Vstop = stop (the lo comparator's ground-referenced ladder)."""
    edges = classes(nclass)[0] if nclass > 1 else ()

    def pick(cur, t0, vlo, vhi):
        pts = lock_points(cur, t0)
        if not pts:
            return None
        c = int(np.searchsorted(edges, t0 + err)) if edges else 0
        vdd = vhi + 0.41
        vstop = (vdd - stops[c] * LADDER["g_hi"]) if ref == "v" else stops[c]
        vstop = min(vstop, vhi)
        order = sorted(pts, reverse=True)                  # slow end first: Vctrl falls code by code
        for i, k in enumerate(order):
            if pts[k][0] <= vstop:
                if pts[k][0] < vlo and i > 0:
                    return order[i - 1]
                return k
        return None
    return pick


RANDOM = dict(sig_lo=0.0, sig_hi=0.0, draws=1, seed=1)   # per-chip ladder errors: relative sigma of vlo and of vdd - vhi


def evaluate(data, pick_for_err, errs, vlo, dvlo, dvhi, margin, step):
    """All chips x start temperatures x sensor errors (x random ladder draws); returns counts."""
    rng = np.random.default_rng(RANDOM["seed"])
    items = []
    for chip, codes in sorted(data.items()):
        for d in range(RANDOM["draws"]):
            g_lo = 1 + rng.normal(0, RANDOM["sig_lo"]) if RANDOM["sig_lo"] else 1.0
            g_hi = 1 + rng.normal(0, RANDOM["sig_hi"]) if RANDOM["sig_hi"] else 1.0
            items.append((chip, codes, g_lo, g_hi))
    t0s = np.arange(-40, 85 + 1e-9, step)
    dt = 0.5
    cases = ok = 0
    worst = Counter()
    never = 0
    fails = []
    for chip, codes, g_lo, g_hi in items:
        LADDER["g_hi"] = g_hi
        vhi = chip[1] - 0.41 * g_hi + dvhi
        lo = vlo * g_lo + dvlo
        chip_switch = 0
        chip_ok = True
        for t0 in t0s:
            up = np.arange(t0, 85 + dt, dt)
            down = np.arange(85, -40 - dt, -dt)
            back = np.arange(-40, t0 + dt, dt)
            prof_a = np.r_[up, down, back]
            prof_b = np.r_[np.arange(t0, -40 - dt, -dt), np.arange(-40, 85 + dt, dt), np.arange(85, t0 - dt, -dt)]
            for e in errs:
                cases += 1
                good, n_max = True, 0
                for prof in (prof_a, prof_b):
                    res, n, ev, kv, why = rp.run_profile(codes, prof, lo, vhi, margin, chip, pick=pick_for_err(e))
                    if not res:
                        good = False
                        fails.append(f"{chip[0]} {chip[1]:.2f} V {chip[2]} T0 {t0:.0f} e {e:+.0f}: {why}")
                        break
                    n_max = max(n_max, n)
                if good:
                    ok += 1
                    worst[n_max] += 1
                    chip_switch += n_max
                else:
                    chip_ok = False
        never += chip_ok and chip_switch == 0
    return dict(cases=cases, ok=ok, never_switch_chips=never, chip_draws=len(items), worst_switches=dict(sorted(worst.items())), fails=fails)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("workmap", nargs="?", default=rp.WORKMAP)
    ap.add_argument("--vlo", type=float, default=0.90)
    ap.add_argument("--dvlo", type=float, default=0.0)
    ap.add_argument("--dvhi", type=float, default=0.0)
    ap.add_argument("--margin", type=float, default=0.02)
    ap.add_argument("--schemes", default="ideal,count4,count3,count2,window3,window1")
    ap.add_argument("--tsense-err", type=float, default=10.0)
    ap.add_argument("--count-n", type=int, default=64)
    ap.add_argument("--targets", default="", help="absolute precharge target per class, e.g. 3:1.00,1.12,1.25;2:1.02,1.22")
    ap.add_argument("--step", type=float, default=5.0)
    ap.add_argument("--sig-lo", type=float, default=0.0, help="per-chip relative sigma of vlo (window_mc: ~0.028 untrimmed)")
    ap.add_argument("--sig-hi", type=float, default=0.0, help="per-chip relative sigma of vdd - vhi and of the VDD-referenced stops (~0.034)")
    ap.add_argument("--draws", type=int, default=1, help="random ladder draws per chip")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pwin", default="0.05,0.12,0.05", help="pwinK power-up threshold offsets: cold (above Vlo), middle (above Vlo), hot (below Vhi)")
    ap.add_argument("--stops-v", default="0.62;0.70,0.50;0.70,0.58,0.48",
                    help="slowvK stop thresholds as VDD - x per class, for K = 1;2;3 (cold .. hot)")
    ap.add_argument("--stops-g", default="1.05;0.98,1.20;0.97,1.07,1.20",
                    help="slowgK absolute stop thresholds per class, for K = 1;2;3 (cold .. hot)")
    a = ap.parse_args()
    RANDOM.update(sig_lo=a.sig_lo, sig_hi=a.sig_hi, draws=a.draws, seed=a.seed)
    data = rp.chips(a.workmap)
    vhi_mid = 1.8 - 0.41
    targets = {k: [a.vlo + (vhi_mid - a.vlo) * frac(t) for t in classes(k)[1]] for k in CLASS_EDGES}
    for spec in filter(None, a.targets.split(";")):
        k, vs = spec.split(":")
        targets[int(k)] = [float(x) for x in vs.split(",")]
    errs = (-a.tsense_err, 0.0, a.tsense_err) if a.tsense_err else (0.0,)
    deltas = [float(x) for x in a.pwin.split(",")]
    out = {}
    print(f"window {a.vlo + a.dvlo:.3f} V .. VDD - {0.41 - a.dvhi:.3f} V, sensor error +-{a.tsense_err:.0f} K, count N {a.count_n}, starts every {a.step:.0f} C")
    for s in a.schemes.split(","):
        if s == "ideal":
            r = evaluate(data, lambda e: pick_ideal, (0.0,), a.vlo, a.dvlo, a.dvhi, a.margin, a.step)
        elif s.startswith("count"):
            k = int(s[5:])
            r = evaluate(data, lambda e, k=k: make_count(k, e, a.count_n, a.vlo, targets[k]), errs, a.vlo, a.dvlo, a.dvhi, a.margin, a.step)
            r["targets"] = [round(b2(v), 4) for v in targets[k]]
        elif s.startswith("slow"):
            # slow<ref><K>, e.g. slowv3 / slowg2; stops from --stops-v / --stops-g (one per class)
            ref, k = s[4], int(s[5:])
            stops = [float(x) for x in (a.stops_v if ref == "v" else a.stops_g).split(";")[[1, 2, 3].index(k) if k <= 3 else 0].split(",")]
            r = evaluate(data, lambda e, k=k, st=stops, ref=ref: make_slow(k, e, st, ref), errs if k > 1 else (0.0,), a.vlo, a.dvlo, a.dvhi, a.margin, a.step)
            r["stops"] = stops
        elif s.startswith("pwin"):
            k = int(s[4:])
            r = evaluate(data, lambda e, k=k: make_pwin(k, e, deltas), errs, a.vlo, a.dvlo, a.dvhi, a.margin, a.step)
            r["deltas"] = deltas
        elif s.startswith("window"):
            k = int(s[6:])
            r = evaluate(data, lambda e, k=k: make_window(k, e), errs if k > 1 else (0.0,), a.vlo, a.dvlo, a.dvhi, a.margin, a.step)
        else:
            raise SystemExit(f"unknown scheme {s}")
        out[s] = r
        extra = "".join(f" {key} {r[key]}" for key in ("targets", "deltas", "stops") if key in r)
        zero = r["worst_switches"].get(0, 0) / max(r["ok"], 1)
        print(f"{s:8s}: {r['ok']}/{r['cases']} cases keep the window; {r['never_switch_chips']}/{r['chip_draws']} chip draws never switch; "
              f"no switch in {zero * 100:.0f} % of kept cases; worst-excursion switches {r['worst_switches']}{extra}", flush=True)
        for f in r["fails"][:3]:
            print("     ", f)
        if len(r["fails"]) > 3:
            print(f"      ... {len(r['fails']) - 3} more")
    path = ROOT / "results/analog/pll/vco/powerup_policy" / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(args=vars(a), result=out), indent=1))
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
