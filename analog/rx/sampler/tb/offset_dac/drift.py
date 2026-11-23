"""Offset trim after a temperature change: calibrate at T1, operate at T2 (same mismatch sample).

    uv run python analog/rx/sampler/tb/offset_dac/drift.py MC_27 MC_M40 MC_85 [--dac DC --inject INJECT] [--trim CODES]

MC_* are tb/offset_mc campaigns of the same condition apart from temperature, same seed and sample
count (the mismatch draws are identical: the deck is the same, only `.temp` differs), e.g. the
TT 1.8 V runs at 27 / -40 / 85 C.  Per sample and lane the offset at each temperature is read back.
A trim set at T1 cancels off(T1); at T2 it is worth off(T1) * s(T2) / s(T1), where s(T) is the trim
step in mV at T:
  tail-tracking  s = gain x DAC step (tb/offset_dac inject + dc summaries, mean over lanes, same
                 supply / corner as the MC runs): the current DAC of rx_offset_dac.spice
  constant-mV    s = const (a trim whose mV step does not move with temperature)
  measured       s = full-scale step of a trimmed block from `run.py codes` (--trim), e.g. ac_trim
Campaigns written before the serdes_flow.mc fix of 2026-11-03 recorded the load-time draw (not set by
the seed) as sample 0 of every chunk; those samples are dropped (detected from the chunk deck).
Residual(T1 -> T2) = off(T2) - off(T1) s(T2)/s(T1) (quantisation ignored); printed as sigma and the
99.7th percentile of |residual| over samples x lanes, next to the untrimmed |off(T2)|.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from serdes_flow import mc
from serdes_flow.project import ROOT

LANES = ("d0", "d1", "e0", "e1")
SLOPE = 0.05 / 40e-9


def offsets(camp):
    """(condition, array lanes x samples of offset mV) from an offset_mc campaign; load-time draws of
    legacy chunks are NaN."""
    camp = ROOT / camp
    s = json.loads((camp / "summary.json").read_text())
    if "offsets_mv" in s:          # padded per sample index (offset_mc after 2026-11-03)
        return s["condition"], np.array([[np.nan if x is None else x for x in s["offsets_mv"][l]] for l in LANES])
    n0 = s["nominal"]
    off = []
    for ch in sorted((camp / "mc").glob("chunk*")):
        rows = mc.read(ch)
        legacy = "setseed" in (deck := (ch / "tb.cir").read_text()) and not any(
            a.startswith("setseed") and b.strip() == "mc_source" for a, b in zip(deck.splitlines(), deck.splitlines()[1:]))
        for k, r in enumerate(rows):
            off.append([np.nan if (legacy and k == 0) else (r[f"t_{l}"] - n0[f"t_{l}"]) * SLOPE * 1e3 for l in LANES])
    return s["condition"], np.array(off).T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("camps", nargs=3, help="offset_mc campaigns at 27, -40, 85 C")
    ap.add_argument("--dac", default="results/analog/rx/sampler/offset_dac/20261103T035531Z_dc/summary.json")
    ap.add_argument("--inject", default="results/analog/rx/sampler/offset_dac/20261103T034557Z_inject/summary.json")
    ap.add_argument("--trim", help="summary.json of run.py codes (a trimmed block): its step is the third model")
    a = ap.parse_args()
    data = {}
    for c in a.camps:
        cond, off = offsets(c)
        t = int(cond.split("_t")[1])
        data[t] = (cond, off)
    n = min(o.shape[1] for _, o in data.values())
    dc = json.loads((ROOT / a.dac).read_text())["conditions"]
    inj = json.loads((ROOT / a.inject).read_text())["conditions"]
    step = {t: np.mean(list(inj[c]["gain_mv_per_ua"].values())) * dc[c]["step_ua"] for t, (c, _) in data.items()}
    print("trim step (tail-tracking DAC): " + ", ".join(f"{t:+d} C {step[t]:.2f} mV" for t in sorted(step)))
    meas = None
    if a.trim:
        tc = json.loads((ROOT / a.trim).read_text())["conditions"]
        meas = {t: np.mean(list(tc[c]["step_fullscale_mv"].values())) for t, (c, _) in data.items()}
        print("trim step (measured, --trim): " + ", ".join(f"{t:+d} C {meas[t]:.2f} mV" for t in sorted(meas)))
    ok = np.all([np.isfinite(o[:, :n]).all(axis=0) for _, o in data.values()], axis=0)
    data = {t: (c, o[:, :n][:, ok]) for t, (c, o) in data.items()}
    n = int(ok.sum())
    for t in sorted(data):
        o = data[t][1][:, :n]
        print(f"  offset at {t:+d} C: sigma {np.nanstd(o):.2f} mV, 99.7th pct |off| {np.nanpercentile(np.abs(o), 99.7):.1f} mV")
    o27 = data[27][1][:, :n]
    for t in (-40, 85):
        d = data[t][1][:, :n] - o27
        r = np.corrcoef(o27.ravel(), data[t][1][:, :n].ravel())[0, 1]
        k = np.nansum(o27 * data[t][1][:, :n]) / np.nansum(o27 * o27)
        print(f"  {t:+d} C vs 27 C: correlation {r:.3f}, best-fit scale {k:.3f}, sigma of change {np.nanstd(d):.2f} mV")
    print(f"{'cal -> run':>12s} | {'untrimmed |off| 99.7%':>22s} | {'tail-tracking: sigma / 99.7%':>29s} | {'constant-mV: sigma / 99.7%':>27s}"
          + (" | measured: sigma / 99.7%" if meas else ""))
    out = {}
    for t1 in sorted(data):
        for t2 in sorted(data):
            if t1 == t2:
                continue
            o1, o2 = data[t1][1][:, :n], data[t2][1][:, :n]
            res_tail = o2 - o1 * step[t2] / step[t1]
            res_const = o2 - o1
            p = lambda x: float(np.nanpercentile(np.abs(x), 99.7))
            out[f"{t1}->{t2}"] = dict(untrimmed_p997=p(o2), tail_sigma=float(np.nanstd(res_tail)), tail_p997=p(res_tail),
                                     const_sigma=float(np.nanstd(res_const)), const_p997=p(res_const))
            extra = ""
            if meas:
                res_m = o2 - o1 * meas[t2] / meas[t1]
                out[f"{t1}->{t2}"] |= dict(measured_sigma=float(np.nanstd(res_m)), measured_p997=p(res_m))
                extra = f" | {np.nanstd(res_m):9.2f} / {p(res_m):5.1f} mV"
            print(f"{t1:+4d} -> {t2:+4d} C | {p(o2):22.1f} | {np.nanstd(res_tail):12.2f} / {p(res_tail):5.1f} mV"
                  f"     | {np.nanstd(res_const):11.2f} / {p(res_const):5.1f} mV" + extra)
    print(f"{n} samples x 4 lanes; {', '.join(data[t][0] for t in sorted(data))}")
    return out


if __name__ == "__main__":
    main()
