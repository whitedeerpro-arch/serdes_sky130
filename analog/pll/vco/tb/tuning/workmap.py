"""VCO working region over 45 conditions x passive corners: which code reaches 2 GHz inside the CP / B2 control range.

    uv run python analog/pll/vco/tb/tuning/workmap.py [--passive tt,hh,ll] [--conds tags] [--vmin 0.95 --vmax 1.35] [--workers 4] [--resume C]
        [--extend 0.7,0.85,1.5 --cp-window <cp/tb/dc/window.py summary.json>] [--bank 4]

Coarse model, then check.  Pass 1 simulates codes 0, 3, 7 at Vctrl vmin, mid, vmax; 1 / f is fitted against the code with a parabola
at each Vctrl (the ring's period goes with its capacitance).  Pass 2 simulates, at every condition, the codes the fit says bracket
2 GHz inside the range, and the table is read from simulated points only; the fit's error against pass 2 is printed.

Real bias and PDK resistors, ring + four buffers, 30 fF (template of tb/phase_noise).  One deck per MOS x passive corner, `alter` over
supply, temperature, code, Vctrl; 24 ns per point, frequency over the last 5 ns (amplitude settles in about 14 ns at the hot corners).
Resume: only points without a complete waveform run again.

--cp-window: also the windows bounded by each condition's measured CP upper edge.
--bank 4: pll_vco_ring4_4b, codes 0..15 in half units (fit from codes 0, 6, 15).
--extend 0.7,0.85,1.5 --resume C: more Vctrl points for the codes near 2 GHz (within 1.6-2.5 GHz at some point), skipping points above
VDD - 0.4 V (the CP's headroom), then for each control window: conditions with a code at 2 GHz, and chips (MOS, supply, passive) with one
code that holds 2 GHz from -40 to 85 C, which is what a code frozen after calibration needs.

Then the same table for a finer bank, from the fit alone (no simulation): 15 half units, so codes 0, 0.5 .. 7.5 in units of today's code,
1 / f parabolic in the code at each Vctrl through the simulated codes.  A model result: pass 2 above bounds the fit's error at the codes it
checks (about 0.05 %), the half codes are not simulated.
"""
import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

TEMPLATE = ROOT / "analog/pll/vco/tb/phase_noise/tb_vco_isf_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/vco/workmap"
STOP, START = 24e-9, 14e-9
CARDS = "generic"   # --cards; module level so extend() / run_points() decks follow it
TARGET = 2e9
BANKS = {3: dict(codes=8, coarse=(0, 3, 7)), 4: dict(codes=16, coarse=(0, 6, 15))}


def name(c, code, v):
    return f"{c.tag}_c{code}_v{round(v * 1000)}.raw"


def deck(process, rc, points, camp, bank=3):
    """points: list of (condition, code, vctrl)."""
    c0 = points[0][0]
    text = spice.render(TEMPLATE, **spice.corner_values(c0), VCTRL=1.2, INJECT="", PROBES="", TSTEP="2p", STOP=f"{STOP:.4e}", SAVE_FROM=f"{START:.4e}", OUT="x.raw", CFG0=0, CFG1=0, CFG2=0)
    text = re.sub(r"\.control.*?\.endc\n", "", text, flags=re.S).replace("reltol=1e-5", "reltol=1e-4")
    if bank == 4:
        old = "ctrl cfg0 cfg1 cfg2 vbias vdd 0 pll_vco_ring4_pvt_candidate"
        assert text.count(old) == 1
        text = text.replace(old, "ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd 0 pll_vco_ring4_4b").replace("Vb2 cfg2 0 0\n", "Vb2 cfg2 0 0\nVb3 cfg3 0 0\n")
        inc = '.include "' + str(ROOT / "analog/pll/vco/spice/vco_ring4_pvt_candidate.spice") + '"'
        assert text.count(inc) == 1
        text = text.replace(inc, inc.replace("vco_ring4_pvt_candidate", "cap_bank_4b") + "\n" + inc.replace("vco_ring4_pvt_candidate", "vco_ring4_4b"))
    camp.mkdir(parents=True, exist_ok=True)
    to_pdk = rcorner.to_pdk_fixed if CARDS == "fixed" else rcorner.to_pdk
    text = bias.section(to_pdk(bias.real(text), camp), process, rc)
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for c, code, v in points:
        lines += [f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}"]
        lines += [f"alter Vb{k} dc={c.supply if (code >> k) & 1 else 0}" for k in range(bank)]
        lines += [f"alter Vctrl dc={v}", f"tran 2p {STOP:.4e} {START:.4e}", f"write {name(c, code, v)} v(v0p) v(v0n)", "destroy all"]
    text = text[: text.rindex(".end")]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def measure(p):
    w = spice.Waves(p)
    y = w["v(v0p)"] - w["v(v0n)"]
    sel = w.t >= STOP - 5e-9
    e, s = crossings(w.t[sel], y[sel])
    r = e[s > 0]
    if len(r) < 4:
        return None
    return float((len(r) - 1) / (r[-1] - r[0])), float(np.ptp(y[sel]))


def run_points(camp, todo, workers, bank=3):
    """Simulate what has no complete waveform, one deck per MOS x passive corner."""
    groups = {}
    for rc, c, code, v in todo:
        if spice.case_output(camp, f"{c.process}_{rc}", name(c, code, v), STOP) is None:
            groups.setdefault((c.process, rc), []).append((c, code, v))
    n = sum(len(x) for x in groups.values())
    print(f"{len(todo)} points, {n} to run in {len(groups)} decks", flush=True)
    jobs = [(deck(p, rc, pts, camp / "snap" / f"{p}_{rc}", bank), spice.next_run_dir(camp, f"{p}_{rc}"), dict(timeout_s=60 * len(pts) + 600, meta=dict(process=p, passive=rc, points=len(pts))))
            for (p, rc), pts in groups.items()]
    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        if not ex.ok:
            print(f"deck {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)


def read(camp, rc, c, code, v):
    p = spice.case_output(camp, f"{c.process}_{rc}", name(c, code, v), STOP)
    return measure(p) if p else None


def extend(camp, passive, conds, extra, workers, cp=None, bank=3):
    base = json.loads((camp / "summary.json").read_text())
    todo = []
    for rc in passive:
        for c in conds:
            f = base["rows"][f"{c.tag}:{rc}"]["f"]
            near = (1.85e9, 2.2e9) if bank == 4 else (1.6e9, 2.5e9)      # half codes are close together: fewer are worth a point
            ks = [int(k) for k, x in f.items() if max(x) >= near[0] and min(x) <= near[1]]
            todo += [(rc, c, k, v) for k in ks for v in extra if v <= c.supply - 0.4]
    run_points(camp, todo, workers, bank)
    vall = sorted(set(base["vs"]) | set(extra))
    table = {}
    for rc in passive:
        for c in conds:
            ks = base["rows"][f"{c.tag}:{rc}"]["f"].keys()
            t = {}
            for k in map(int, ks):
                pts = [(v, read(camp, rc, c, k, v)) for v in vall]
                t[k] = [(v, g[0]) for v, g in pts if g]
            table[(rc, c)] = t

    def finer(t):
        """Half-unit codes from the simulated ones, at each Vctrl with at least three codes."""
        out = {}
        for v in vall:
            got = [(k, dict(pts)[v]) for k, pts in t.items() if v in dict(pts)]
            if len(got) < 2:
                continue
            fit = np.polyfit([k for k, _ in got], [1 / f for _, f in got], min(2, len(got) - 1))
            lo, hi = min(k for k, _ in got) - 1, max(k for k, _ in got) + 1
            for n in range(16):
                if lo <= n / 2 <= hi or (n == 15 and hi >= 7):
                    out.setdefault(n / 2, []).append((v, float(1 / np.polyval(fit, n / 2))))
        return out

    def reach(t, lo, hi):
        """Codes whose f(Vctrl) crosses 2 GHz inside [lo, hi], from the points simulated in that window."""
        out = {}
        for k, pts in t.items():
            if len(pts) < 2:
                continue
            vp, fp = zip(*pts)
            grid = sorted({lo, hi} | {v for v in vp if lo <= v <= hi})   # window edges interpolated, not dropped
            f = np.interp(grid, vp, fp)
            for v0, v1, f0, f1 in zip(grid, grid[1:], f, f[1:]):
                if min(f0, f1) <= TARGET <= max(f0, f1):
                    out[k] = v0 + (TARGET - f0) * (v1 - v0) / (f1 - f0)
                    break
        return out

    windows = {"0.95-1.35 V": lambda c, rc: (0.95, 1.35), "0.85-1.35 V": lambda c, rc: (0.85, 1.35), "0.7-1.35 V": lambda c, rc: (0.7, 1.35), "0.95 V-VDD-0.4": lambda c, rc: (0.95, c.supply - 0.4),
               "0.85 V-VDD-0.4": lambda c, rc: (0.85, c.supply - 0.4), "0.7 V-VDD-0.4": lambda c, rc: (0.7, c.supply - 0.4)}
    if cp:
        edge = json.loads(cp.read_text())["rows"]
        windows.update({"0.85 V-CP edge": lambda c, rc: (0.85, edge[f"{c.tag}:{rc}"]["hi"]), "0.7 V-CP edge": lambda c, rc: (0.7, edge[f"{c.tag}:{rc}"]["hi"]),
                        "0.95 V-CP, 1.35": lambda c, rc: (0.95, min(1.35, edge[f"{c.tag}:{rc}"]["hi"]))})
    summary = {}
    chips = {}
    temps = sorted({c.temp for (_, c) in table})
    for (rc, c), t in table.items():
        chips.setdefault((rc, c.process, c.supply), []).append((c, t))
    for bank_name, view in ((("4 bit, simulated", lambda t: t),) if bank == 4 else (("3 bit, simulated", lambda t: t), ("15 half units, from the fit", finer))):
      print(f"\n{bank_name}\n{'control window':16s} {'no code':>8s} of {len(table)} | one code for all T | one code for cold and room | for room and hot   (of 45 chips)")
      views = {key: view(t) for key, t in table.items()}
      for name_, lim in windows.items():
        none = [f"{c.tag}:{rc}" for (rc, c), t in views.items() if not reach(t, *lim(c, rc))]
        good, bad, low, high = 0, [], 0, 0
        for key, cs in chips.items():
            sets = {c.temp: set(reach(views[(key[0], c)], *lim(c, key[0]))) for c, _ in cs}
            if set.intersection(*sets.values()):
                good += 1
            else:
                bad.append(f"{key[1]}_{round(key[2] * 1000)}_{key[0]}")
            low += bool(sets[temps[0]] & sets[temps[1]])
            high += bool(sets[temps[1]] & sets[temps[2]])
        summary[f"{bank_name}: {name_}"] = dict(none=none, frozen_ok=good, frozen_bad=bad, cold_room=low, room_hot=high, chips=len(chips))
        print(f"{name_:16s} {len(none):8d}        | {good:18d} | {low:26d} | {high:16d}   {none[:4]}", flush=True)
    (camp / "extend.json").write_text(json.dumps(summary, indent=1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passive", default="tt,hh,ll")
    ap.add_argument("--conds", help="comma list; default all 45")
    ap.add_argument("--vmin", type=float, default=0.95)
    ap.add_argument("--vmax", type=float, default=1.35)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--extend", help="more Vctrl points, see above; needs --resume")
    ap.add_argument("--cp-window")
    ap.add_argument("--bank", type=int, default=3, choices=sorted(BANKS))
    ap.add_argument("--cards", default="generic", choices=("generic", "fixed"),
                    help="resistor cards: generic high_po (to_pdk) or the layout-equivalent fixed-width ones (to_pdk_fixed)")
    a = ap.parse_args()
    global CARDS
    CARDS = a.cards
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    conds = [Condition.parse(x) for x in a.conds.split(",")] if a.conds else grid45()
    passive = a.passive.split(",")
    if a.extend:
        extend(camp, passive, conds, [float(x) for x in a.extend.split(",")], a.workers, ROOT / a.cp_window if a.cp_window else None, a.bank)
        return
    vs = (a.vmin, round((a.vmin + a.vmax) / 2, 3), a.vmax)
    coarse, ncode = BANKS[a.bank]["coarse"], BANKS[a.bank]["codes"]
    run_points(camp, [(rc, c, k, v) for rc in passive for c in conds for k in coarse for v in vs], a.workers, a.bank)
    # fit: 1 / f parabola in the code at each Vctrl; codes whose 0.95-1.35 V range is predicted to hold 2 GHz, with one neighbour each side
    want, fits = [], {}
    for rc in passive:
        for c in conds:
            fit = {}
            for v in vs:
                got = [(k, read(camp, rc, c, k, v)) for k in coarse]
                if any(g is None for _, g in got):
                    continue
                fit[v] = np.polyfit([k for k, _ in got], [1 / g[0] for _, g in got], 2)
            fits[(rc, c.tag)] = fit
            if len(fit) < 3:
                print(f"{c.tag} {rc}: pass 1 incomplete", flush=True)
                continue
            pred = {k: [1 / np.polyval(fit[v], k) for v in vs] for k in range(ncode)}
            inside = [k for k in range(ncode) if pred[k][0] <= TARGET <= pred[k][-1]]
            if not inside:
                inside = [min(range(ncode), key=lambda k: min(abs(f - TARGET) for f in pred[k]))]
            for k in sorted(set(inside) | {max(min(inside) - 1, 0), min(max(inside) + 1, ncode - 1)}):
                want += [(rc, c, k, v) for v in vs]
    run_points(camp, want, a.workers, a.bank)
    rows, err = {}, []
    for rc in passive:
        print(f"\n== passive {rc}: 2 GHz inside {a.vmin}-{a.vmax} V; code / Vctrl / Kvco MHz/V / mVpp for the code nearest mid range; all codes that reach it")
        for c in conds:
            pts = {}
            for k in range(ncode):
                got = {v: read(camp, rc, c, k, v) for v in vs}
                if all(g is not None for g in got.values()):
                    pts[k] = got
            fit = fits.get((rc, c.tag), {})
            if len(fit) == 3:
                err += [abs(pts[k][v][0] * np.polyval(fit[v], k) - 1) for k in pts if k not in coarse for v in vs]
            usable = []
            for k, got in pts.items():
                f = [got[v][0] for v in vs]
                if f[0] <= TARGET <= f[-1] or (f[0] >= TARGET >= f[-1]):
                    usable.append(k)
            r = dict(usable=usable, f={str(k): [got[v][0] for v in vs] for k, got in pts.items()}, swing={str(k): [got[v][1] for v in vs] for k, got in pts.items()})
            if usable:
                best = None
                for k in usable:
                    f = [pts[k][v][0] for v in vs]
                    i = 0 if f[0] <= TARGET <= f[1] else 1
                    vt = vs[i] + (TARGET - f[i]) * (vs[i + 1] - vs[i]) / (f[i + 1] - f[i])
                    q = (abs(vt - vs[1]), k, vt, (f[i + 1] - f[i]) / (vs[i + 1] - vs[i]))
                    best = q if best is None or q < best else best
                _, k, vt, kv = best
                r.update(code=k, vctrl=float(vt), kvco=float(kv))
                print(f"{c.tag:15s} code {k} {vt:.3f} V {kv / 1e6:5.0f} MHz/V {np.mean(r['swing'][str(k)]) * 1e3:4.0f} mVpp | usable {usable}", flush=True)
            else:
                near = {k: [round(got[v][0] / 1e9, 3) for v in vs] for k, got in pts.items()}
                print(f"{c.tag:15s} NONE; GHz {near}", flush=True)
            rows[f"{c.tag}:{rc}"] = r
    none = [t for t, r in rows.items() if not r["usable"]]
    single = [t for t, r in rows.items() if len(r["usable"]) == 1]
    codes = [r["code"] for r in rows.values() if "code" in r]
    print(f"\n{len(rows)} conditions; none {len(none)} {none[:12]}; only one code {len(single)} {single[:12]}; selected codes {min(codes) if codes else None}-{max(codes) if codes else None}; "
          f"Kvco {min(r['kvco'] for r in rows.values() if 'kvco' in r) / 1e6:.0f}-{max(r['kvco'] for r in rows.values() if 'kvco' in r) / 1e6:.0f} MHz/V; fit error max {max(err) * 100 if err else float('nan'):.2f} %, mean {np.mean(err) * 100 if err else float('nan'):.2f} %")
    (camp / "summary.json").write_text(json.dumps(dict(vs=vs, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
