"""RX sampler over PVT: recorded C2 far-end (BC) -> CTLE (EQ3) -> PI-clocked half-rate samplers.

    uv run python analog/rx/sampler/tb/link_pvt/pvt.py [stress | all | tags...] --bc rx_c2_far_nominal@ctle_rc
        [--codes 0:32:2] [--resume C] [--analyse-only]

For every condition the PI code is swept over one UI (codes 0..31 cover 1 UI; step 2 = 1/16 UI).
Decisions: D0 (data-clock rising) and D1 (falling) read just before the next edge of the same
polarity, merged in time order and compared with the PRBS7 at the best integer bit offset.
Sampler eye width = the longest circular run of codes with zero errors (aperture, set-up,
PI non-linearity and CTLE output all included); its centre is the code a CDR would settle near.
"""
import argparse
import importlib.util
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, eye, spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


replay = _load("ctle_replay", ROOT / "analog/rx/ctle/tb/link_eye/replay.py")
link = replay.link
pi = _load("pi_pvt", ROOT / "analog/rx/pi/tb/rotation/pvt.py")
TEMPLATE = HERE / "tb_rx_sampler_link_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/link_pvt"
EQ = 3
CODE_UI = 2.0 / 64               # one PI code = 1/32 UI


def case_name(c, code):
    return f"{c.tag}_c{code:02d}"


def deck(cases):
    c0, code0 = cases[0]
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in pi.bits(code0, c0.supply).items())
    text = spice.render(TEMPLATE, **spice.corner_values(c0), EQ0_V=c0.supply, EQ1_V=c0.supply,
                        CONTROL_SOURCES=ctl, CASES="@CASES@")
    blocks = []
    for c, code in cases:
        n = case_name(c, code)
        blocks.append("\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}",
                                 f"alter Veq0 dc={c.supply * (EQ & 1)}", f"alter Veq1 dc={c.supply * (EQ >> 1)}"]
                                + [f"alter {k} dc={v}" for k, v in pi.bits(code, c.supply).items()]
                                + [f"tran 2p {link.STOP:.4e} {link.SAVE_FROM:.4e} 4p",
                                   "let ctle=v(op)-v(on)", "let ck=v(xdut.cdp)-v(xdut.cdn)", "let d0=v(d0p)-v(d0n)",
                                   "let d1=v(d1p)-v(d1n)", "let inbuf=v(xdut.bp)-v(xdut.bn)", "let power=-v(vdd)*i(Vdd)",
                                   f"write {n}.raw ctle ck d0 d1 inbuf power", "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def decisions(w, t_from):
    e, pol = crossings(w.t, w["ck"])
    out = []
    for p, q in ((1, "d0"), (-1, "d1")):
        edges = e[pol == p]
        for a, b in zip(edges[:-1], edges[1:]):
            if a >= t_from:
                out.append((a, 1 if np.interp(b - 30e-12, w.t, w[q]) > 0 else 0))
    out.sort()
    return [b for _, b in out]


def errors(dec, bits):
    """Fewest mismatches over integer offsets of the decision stream against the PRBS bits."""
    best = (len(dec), None)
    for j0 in range(link.WARM - 8, len(bits) - len(dec) + 1):
        if j0 < 0:
            continue
        m = sum(d != bits[j0 + k] for k, d in enumerate(dec))
        if m < best[0]:
            best = (m, j0)
    return best


def analyse_case(d, c, code, bits):
    w = spice.Waves(Path(d) / f"{case_name(c, code)}.raw")
    t_from = link.T0 + (link.WARM + 4) * link.UI
    dec = decisions(w, t_from)
    nerr, j0 = errors(dec, bits)
    sel = w.t > t_from
    return dict(code=code, errors=int(nerr), decisions=len(dec), offset_bits=j0,
                inbuf_pp=float(np.ptp(w["inbuf"][sel])), ck_pp=float(np.ptp(w["ck"][sel])),
                power_mw=float(np.mean(w["power"][sel]) * 1e3))


def window(codes, ok):
    """Longest circular run of passing codes (codes cover one UI)."""
    n = len(codes)
    if all(ok):
        return n, codes[0]
    best, start = 0, None
    for i in range(n):
        if ok[i] and not ok[i - 1]:
            k = 0
            while ok[(i + k) % n] and k < n:
                k += 1
            if k > best:
                best, start = k, i
    return best, (codes[(start + best // 2) % n] if start is not None else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--bc", default="rx_c2_far_nominal@ctle_rc")
    ap.add_argument("--codes", default="0:32:2")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    lo, hi, st = (int(x) for x in a.codes.split(":"))
    codes = list(range(lo, hi, st))
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    boundary.check_load(a.bc, replay.signature())
    camp = (ROOT / a.resume) if a.resume else RESULTS / f"{a.bc.split('@')[0]}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = replay.stimuli(a.bc)
    (camp / "stimuli.inc").write_text(stim)
    bits = eye.prbs7(link.NBITS)
    keys = [(c, code) for c in conds for code in codes]
    by_proc = {}
    for k in keys:
        by_proc.setdefault(k[0].process, []).append(k)
    jobs = [(deck(cases), camp / proc, dict(files={"stimuli.inc": camp / "stimuli.inc"},
                                            meta=dict(process=proc, bc=a.bc, eq=EQ, codes=codes,
                                                      conditions=sorted({c.tag for c, _ in cases}))))
            for proc, cases in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(keys)} cases in {len(jobs)} decks: {len(jobs) - len(todo)} kept, {len(todo)} to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=4, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    print(f"{'condition':15s} | errors per code {codes[0]}..{codes[-1]} step {st} | window | centre | inbuf/ck pp mV | P mW")
    for c in conds:
        cs = [analyse_case(camp / c.process, c, code, bits) for code in codes]
        ok = [x["errors"] == 0 for x in cs]
        run, centre = window(codes, ok)
        width = run * st * CODE_UI
        r = dict(condition=c.tag, per_code=cs, window_codes=run, width_ui=width, centre_code=centre,
                 inbuf_pp_min=min(x["inbuf_pp"] for x in cs), ck_pp_min=min(x["ck_pp"] for x in cs),
                 power_mw=float(np.mean([x["power_mw"] for x in cs])))
        rows.append(r)
        print(f"{c.tag:15s} | " + " ".join(f"{x['errors']:2d}" for x in cs) + f" | {width:.2f} UI | {centre} | "
              f"{r['inbuf_pp_min']*1e3:.0f}/{r['ck_pp_min']*1e3:.0f} | {r['power_mw']:.2f}")
    (camp / "summary.json").write_text(json.dumps(dict(bc=a.bc, eq=EQ, codes=codes, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
