"""RX sampler over PVT: recorded C2 far-end (BC) -> CTLE (EQ3) -> PI-clocked half-rate samplers.

    uv run python analog/rx/sampler/tb/link_pvt/pvt.py [stress | all | tags...] --bc rx_c2_far_nominal@ctle_rc
        [--dut stock|ac] [--param KEY=VALUE ...] [--codes 0:32:2] [--gate-codes 12,20,28 [--full stress]]
        [--workers 4] [--resume C] [--analyse-only]

For every condition the PI code is swept over one UI (codes 0..31 cover 1 UI; step 2 = 1/16 UI).
Decisions: D0 (data-clock rising) and D1 (falling) read just before the next edge of the same
polarity, merged in time order and compared with the PRBS7 at the best integer bit offset.
Sampler eye width = the longest circular run of codes with zero errors (aperture, set-up,
PI non-linearity and CTLE output all included); its centre is the code a CDR would settle near.

DUT variants (--dut): stock = serdes_rx_half_rate_samples (source-follower clock shift, global-bias
tails); ac = serdes_rx_half_rate_samples_ac (low-overdrive tails, AC-coupled CML clock buffers).
Bench setting for ac: rb = 2 kohm instead of 50 kohm, so the coupling capacitors settle in ~1.5 ns
instead of ~40 ns (the bench is 45 ns).  The mean gate level is v(vck) for any rb (no DC path); the
2 GHz clock amplitude through rb differs by < 0.2 %.  --param overrides DUT parameters.

Gate mode (--gate-codes): conditions outside --full (default the STRESS set) are run only at the
given codes, chosen to span the 0.5 UI window gate around the eye centre (codes 12 / 20 / 28 =
centre 20 +- 0.25 UI for the C2 replay: every full sweep so far had its errors at codes 0-6 only).
PASS = no error at any gate code, i.e. an error-free window >= the span, assuming the error-free
codes are contiguous (true in every full sweep).  Full-sweep conditions report the window width.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, eye, rcorner, spice
from serdes_flow.corners import STRESS, Condition, boundary_first, grid45
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
CASE_TIMEOUT_S = 600             # per case (normal 1.4-2.2 min); a deck's timeout scales with its cases
DUTS = {"stock": "serdes_rx_half_rate_samples", "ac": "serdes_rx_half_rate_samples_ac"}
BENCH_PARAMS = {"ac": {"rb": "2k"}}


def dut(variant="stock", params=None):
    """Subcircuit name plus parameter overrides for the Xdut line."""
    p = {**BENCH_PARAMS.get(variant, {}), **(params or {})}
    return " ".join([DUTS[variant]] + [f"{k}={v}" for k, v in p.items()])


def case_name(c, code):
    return f"{c.tag}_c{code:02d}"


def deck(cases, dut_text=DUTS["stock"]):
    c0, code0 = cases[0]
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in pi.bits(code0, c0.supply).items())
    text = spice.render(TEMPLATE, **spice.corner_values(c0), EQ0_V=c0.supply, EQ1_V=c0.supply,
                        CONTROL_SOURCES=ctl, DUT=dut_text, CASES="@CASES@")
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


def case_path(camp, c, code):
    name = f"{case_name(c, code)}.raw"
    return spice.case_output(camp, c.tag, name) or spice.case_output(camp, c.process, name)


def analyse_case(path, c, code, bits):
    w = spice.Waves(path)
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
    ap.add_argument("--dut", choices=sorted(DUTS), default="stock")
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--gate-codes", help="comma list; conditions outside --full only run these codes")
    ap.add_argument("--full", default="stress", help="conditions with the full code sweep: stress | all | tags")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rcorner", help="emulate a resistor corner (hh | ll | scale) with constant-swing reference currents (serdes_flow.rcorner)")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    lo, hi, st = (int(x) for x in a.codes.split(":"))
    codes = list(range(lo, hi, st))
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    boundary.check_load(a.bc, replay.signature())
    params = dict(p.split("=", 1) for p in a.param)
    dut_text = dut(a.dut, params)
    tag = a.bc.split('@')[0] + ("" if a.dut == "stock" else f"_{a.dut}")
    camp = (ROOT / a.resume) if a.resume else RESULTS / f"{tag}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = replay.stimuli(a.bc)
    (camp / "stimuli.inc").write_text(stim)
    bits = eye.prbs7(link.NBITS)
    full = (set(conds) if a.full == "all" else set(STRESS) if a.full == "stress"
            else {Condition.parse(x) for x in a.full.split(",")})
    gate = [int(x) for x in a.gate_codes.split(",")] if a.gate_codes else None
    codes_for = lambda c: codes if (gate is None or c in full) else gate
    keys = [(c, code) for c in conds for code in codes_for(c)]
    # one deck per condition (keeps 4 workers busy and decks short); campaigns before 2026-11-01
    # used one deck per process, still found by case_path
    by_deck = {}
    for k in keys:
        by_deck.setdefault(k[0].tag, []).append(k)
    if not a.analyse_only:                     # a partial re-analysis must not shrink the campaign plan
        (camp / "plan.json").write_text(json.dumps(dict(decks={d: len(v) for d, v in by_deck.items()}), indent=1))
    # case-level resume: only cases without a readable waveform are (re)run, in <deck> or <deck>.rN
    out = lambda c, code: case_path(camp, c, code)
    todo = []
    order = [c.tag for c in boundary_first(conds)]          # run order only: boundary answers first
    for deck_name, cases in sorted(by_deck.items(), key=lambda kv: order.index(kv[0])):
        missing = [k for k in cases if out(*k) is None]
        if missing and not a.analyse_only:
            todo.append(((rcorner.emulate(deck(missing, dut_text), camp, a.rcorner) if a.rcorner else deck(missing, dut_text)), spice.next_run_dir(camp, deck_name),
                         dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=CASE_TIMEOUT_S * len(missing),
                              meta=dict(process=missing[0][0].process, bc=a.bc, eq=EQ, codes=codes, dut=dut_text,
                                        conditions=sorted({c.tag for c, _ in missing}),
                                        cases=[case_name(*k) for k in missing]))))
    print(f"{len(keys)} cases, {len(by_deck)} decks: {sum(len(j[2]['meta']['cases']) for j in todo)} cases to run "
          f"in {len(todo)} decks", flush=True)
    for ex in spice.run_many(todo, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: exit {ex.exit_code}, {ex.log_failures[:3]}", flush=True)
    rows = []
    print(f"{'condition':15s} | errors per code {codes[0]}..{codes[-1]} step {st} | window | centre | inbuf/ck pp mV | P mW")
    for c in conds:
        cc = codes_for(c)
        paths = [out(c, code) for code in cc]
        if None in paths:
            print(f"{c.tag:15s} | incomplete: {sum(p is None for p in paths)} cases missing (rerun with --resume)")
            continue
        cs = [analyse_case(p, c, code, bits) for p, code in zip(paths, cc)]
        ok = [x["errors"] == 0 for x in cs]
        if cc is not codes:
            span = (max(cc) - min(cc)) * CODE_UI
            r = dict(condition=c.tag, mode="gate", per_code=cs, gate_codes=cc, gate_span_ui=span, gate_pass=all(ok),
                     inbuf_pp_min=min(x["inbuf_pp"] for x in cs), ck_pp_min=min(x["ck_pp"] for x in cs),
                     power_mw=float(np.mean([x["power_mw"] for x in cs])))
            rows.append(r)
            print(f"{c.tag:15s} | gate codes {','.join(map(str, cc))}: " + " ".join(f"{x['errors']:2d}" for x in cs)
                  + f" | {'PASS' if all(ok) else 'FAIL'} (>= {span:.2f} UI) | {r['inbuf_pp_min']*1e3:.0f}/{r['ck_pp_min']*1e3:.0f} | {r['power_mw']:.2f}")
            continue
        run, centre = window(codes, ok)
        width = run * st * CODE_UI
        r = dict(condition=c.tag, mode="full", per_code=cs, window_codes=run, width_ui=width, centre_code=centre,
                 inbuf_pp_min=min(x["inbuf_pp"] for x in cs), ck_pp_min=min(x["ck_pp"] for x in cs),
                 power_mw=float(np.mean([x["power_mw"] for x in cs])))
        rows.append(r)
        print(f"{c.tag:15s} | " + " ".join(f"{x['errors']:2d}" for x in cs) + f" | {width:.2f} UI | {centre} | "
              f"{r['inbuf_pp_min']*1e3:.0f}/{r['ck_pp_min']*1e3:.0f} | {r['power_mw']:.2f}")
    (camp / "summary.json").write_text(json.dumps(dict(bc=a.bc, eq=EQ, codes=codes, gate_codes=gate, full=a.full, dut=dut_text, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
