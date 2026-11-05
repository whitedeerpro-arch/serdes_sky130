"""RX readout to 16-UI words (CML 1:2 demux + CMOS 1:4) over PVT (real PRBS data).

    uv run python analog/rx/sampler/tb/readout_deser/run.py [stress | all | tags...] [--code 20]
        [--param K=V ...] [--deser serdes_rx_readout_deser16] [--deser-param K=V ...] [--workers 4]
        [--bias ideal|real] [--rpdk tt|ll|hh] [--resume C] [--analyse-only]

C2 far-end replay -> CTLE EQ3 -> PI (code) -> serdes_rx_half_rate_samples_ac_rk -> rx_readout_deser16.spice.
One deck per condition.  The 32 outputs are read at every rising edge of the word clock w.
A 20 aC kick (about the thermal charge of the node) on the read divider at t = 0: without noise the divider can sit
at its balanced state for a long time (17 ns at SS 1.65 V 85 C R hh, words before that fail the check).

Per case:
  word map   EXPECTED gives the chronological position (0 = oldest) in the 16-UI word of every data
             output <lane>_<k>; the edge output paired with a data output (same clock phase and stage)
             is the edge sample just after that data bit.  The word start P is the one offset that
             fits all 16 data outputs jointly; data errors = mismatches against PRBS7 at the expected
             positions (zero errors over ~100 bits is the proof of the map), edge errors = mismatches
             at determinate edges (equal neighbours).  "derived" lists, per data output, the positions
             in -4..19 that fit it alone (diagnostic: with ~6 words a stray position can fit by chance).
  w slack    worst setup (w rising - last output transition) and hold (next transition - w rising)
             over the 32 outputs.
  capture    stage-0 slack: converted lane transitions against the rising edges of its clock phase
             (data lanes; edge lanes resolve late at data transitions and are not graded).
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, boundary, eye, rcorner, spice
from serdes_flow.corners import STRESS, Condition, boundary_first, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_readout_deser_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/readout_deser"
CASE_TIMEOUT_S = 1500
LANES = ("a0", "b0", "ae1", "be1", "a1", "b1", "ae0", "be0")
CLOCK = {"a0": "ckq", "ae1": "ckq", "b0": "ckqb", "be1": "ckqb", "a1": "ckm", "ae0": "ckm", "b1": "ckmb", "be0": "ckmb"}
EDGE_OF = {"ae1": "a0", "be1": "b0", "ae0": "a1", "be0": "b1"}
EXPECTED = {f"{lane}_{k}": base - 4 * k for lane, base in (("a0", 12), ("b1", 13), ("b0", 14), ("a1", 15)) for k in range(4)}

_s = importlib.util.spec_from_file_location("readout_demux", ROOT / "analog/rx/sampler/tb/readout_demux/run.py")
rd = importlib.util.module_from_spec(_s)
_s.loader.exec_module(rd)
sp = rd.sp


def outputs():
    return [f"{lane}_{k}" for lane in LANES for k in range(4)]


def deck(c, code, dut_text, deser, extra=""):
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code, c.supply).items())
    if extra:
        ctl += "\n" + extra
    ctl += "\nIkick xro.xf.dqp xro.xf.dqn PWL(0 1u 20p 1u 21p 0)"
    nodes = outputs() + ["w", "vdd", "xro.ckq", "xro.ckqb", "xro.ckm", "xro.ckmb", "xro.st_q", "xro.st_qb", "xro.st_m",
                         "xro.st_mb", "xro.xwc.j0", "xro.xwc.j1"] + [f"xro.r{lane}" for lane in LANES]
    saves = ".save " + " ".join(f"v({n})" for n in nodes) + " i(Vdd)"
    text = spice.render(TEMPLATE, **spice.corner_values(c), EQ0_V=c.supply, EQ1_V=c.supply,
                        CONTROL_SOURCES=ctl, DUT=dut_text, DEMUX=deser, SAVES=saves, CASES="@CASES@")
    vecs = [f"v({n})" for n in nodes] + ["power"]
    n = rd.case_name(c, code)
    block = "\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}",
                       f"alter Veq0 dc={c.supply * (sp.EQ & 1)}", f"alter Veq1 dc={c.supply * (sp.EQ >> 1)}"]
                      + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
                      + [f"tran 2p {sp.link.STOP:.4e} {sp.link.SAVE_FROM:.4e} 4p", "let power=-v(vdd)*i(Vdd)",
                         f"write {n}.raw " + " ".join(vecs), "destroy all"])
    return text.replace("@CASES@", block)


def word_check(words, bits):
    """words: {output: [bit per word]}.  Fit the word start P with EXPECTED; data / edge errors; derived map."""
    nw = len(next(iter(words.values())))
    first = sp.link.WARM - 8
    data = [o for o in words if o.split("_")[0] in ("a0", "b0", "a1", "b1")]

    def errs(p):
        use = [n for n in range(nw) if p + 16 * n >= first and p + 16 * n + 20 < len(bits)]
        return sum(words[o][n] != bits[p + 16 * n + EXPECTED[o]] for o in data for n in use), use

    cands = [(errs(p), p) for p in range(0, len(bits) - 20)]
    cands = [x for x in cands if len(x[0][1]) >= 4]
    (e, use), p = min(cands, key=lambda x: (x[0][0], -len(x[0][1])))
    derived = {}
    for o in data:
        fit = [i for i in range(-4, 20) if all(words[o][n] == bits[p + 16 * n + i] for n in use if 0 <= p + 16 * n + i < len(bits))]
        derived[o] = fit
    edge_err, determinate = 0, 0
    for o in words:
        lane, k = o.split("_")
        if lane not in EDGE_OF:
            continue
        i = EXPECTED[f"{EDGE_OF[lane]}_{k}"]
        for n in use:
            j = p + 16 * n + i
            if j + 1 < len(bits) and bits[j] == bits[j + 1]:
                determinate += 1
                edge_err += words[o][n] != bits[j]
    return dict(start=p, words=len(use), data_errors=int(e), edge_errors=int(edge_err), edge_determinate=determinate,
                derived={o: v for o, v in derived.items()}, map_ok=bool(e == 0 and all(EXPECTED[o] in v for o, v in derived.items())))


def analyse(path, c, code, bits):
    w = spice.Waves(path)
    t_from = sp.link.T0 + (sp.link.WARM + 6) * sp.link.UI
    sel = w.t >= t_from
    t = w.t[sel]
    g = lambda k: w[k][sel]
    vdd = float(np.mean(g("v(vdd)")))
    out = dict(condition=c.tag, code=code, power_mw=float(np.mean(g("power")) * 1e3))
    we, wp = crossings(t, g("v(w)"), level=vdd / 2)
    wr = we[wp > 0]
    words, su, ho = {}, [], []
    for o in outputs():
        y = g(f"v({o})")
        words[o] = [int(np.interp(x, t, y) > vdd / 2) for x in wr]
        oe, _ = crossings(t, y, level=vdd / 2)
        s, h = rd.slack(oe, wr)
        su += [s] if s is not None else []
        ho += [h] if h is not None else []
    out["w_setup_ps"], out["w_hold_ps"] = (min(su) if su else None), (min(ho) if ho else None)
    out.update(word_check(words, bits))
    cap = {}
    for lane in LANES:
        ce, cp = crossings(t, g(f"v(xro.{CLOCK[lane]})"), level=vdd / 2)
        re_, _ = crossings(t, g(f"v(xro.r{lane})"), level=vdd / 2)
        cap[lane] = rd.slack(re_, ce[cp > 0])
    out["capture"] = {k: list(v) for k, v in cap.items()}
    ds = [min(v) for k, v in cap.items() if k in ("a0", "b0", "a1", "b1") and None not in v]
    out["capture_data_slack_min_ps"] = min(ds) if ds else None
    start = crossings(w.t, w["v(xro.ckq)"], level=vdd / 2)[0]
    out["ck_start_ns"] = float(start[0] * 1e9) if len(start) else None
    tog = lambda k: int(len(crossings(t, g(k), level=vdd / 2)[0]))
    out["toggles"] = dict(w=tog("v(w)"), j0=tog("v(xro.xwc.j0)"), st_q=tog("v(xro.st_q)"), st_m=tog("v(xro.st_m)"),
                          ckq=tog("v(xro.ckq)"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--code", type=int, default=20)
    ap.add_argument("--param", action="append", default=["rk_wn=8", "rk_nfin=2"])
    ap.add_argument("--dut", choices=("ac_rk", "ac_trim_rk"), default="ac_rk", help="sampler block: ac_trim_rk = with the offset trim (all lanes at --cal-code)")
    ap.add_argument("--cal-code", type=int, default=32)
    ap.add_argument("--deser", default="serdes_rx_readout_deser16")
    ap.add_argument("--deser-param", action="append", default=[])
    ap.add_argument("--bc", default="rx_c2_far_nominal@ctle_rc")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rcorner", help="emulate a resistor corner (hh | ll | scale) with constant-swing reference currents (serdes_flow.rcorner)")
    ap.add_argument("--bias", choices=("ideal", "real"), default="ideal", help="real: bandgap reference and module copies (serdes_flow.bias)")
    ap.add_argument("--rpdk", choices=("tt", "ll", "hh"), help="project resistors as PDK high_po, library section MOS x this resistor corner")
    ap.add_argument("--resume")
    ap.add_argument("--reltol", type=float, help="numerics for a resume of failed cases: option reltol=X itl4=200 before tran")
    ap.add_argument("--op-steps", type=int, help="operating point of a resume: .options gminsteps=N srcsteps=N "
                    "(ac_trim_rk TT 1.65 V -40 C: default stepping fails, transient op hangs; 100 converges in ~3 min)")
    ap.add_argument("--case-timeout", type=float, default=CASE_TIMEOUT_S, help="seconds per case (ac_trim_rk needs ~2x the ac_rk time)")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    params = dict(p.split("=", 1) for p in a.param)
    deser = " ".join([a.deser] + a.deser_param)
    trim = a.dut == "ac_trim_rk"
    dut_text = (" ".join(sp.CAL_NODES + ["serdes_rx_half_rate_samples_ac_trim_rk"] + [f"{k}={v}" for k, v in {**rd.BENCH, **params}.items()])
                if trim else rd.dut_text(params))
    extra = sp.cal_sources(a.cal_code) if trim else ""
    boundary.check_load(a.bc, sp.replay.signature())
    camp = (ROOT / a.resume) if a.resume else RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + (f"_ac_trim{a.cal_code}" if trim else "") + ("_realbias" if a.bias == "real" else "") + (f"_r{a.rpdk}" if a.rpdk else ""))
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = sp.replay.stimuli(a.bc)
    (camp / "stimuli.inc").write_text(stim)
    order = boundary_first(conds)
    if not a.analyse_only:                     # a partial re-analysis must not shrink the campaign plan
        (camp / "plan.json").write_text(json.dumps(dict(decks={c.tag: 1 for c in order}), indent=1))
    todo = []
    for c in order:
        if spice.case_output(camp, c.tag, f"{rd.case_name(c, a.code)}.raw", sp.link.STOP) is None and not a.analyse_only:
            dk = deck(c, a.code, dut_text, deser, extra)
            if a.reltol:
                dk = dk.replace("\ntran ", f"\noption reltol={a.reltol} itl4=200\ntran ")
            if a.op_steps:
                if dk.count("\n.options ") != 1:
                    raise ValueError("expected one .options line")
                dk = dk.replace("\n.options ", f"\n.options gminsteps={a.op_steps} srcsteps={a.op_steps} ")
            if a.bias == "real":
                dk = bias.real(dk)
            if a.rpdk:
                dk = bias.section(rcorner.to_pdk(dk, camp), c.process, a.rpdk)
            todo.append(((rcorner.emulate(dk, camp, a.rcorner) if a.rcorner else dk), spice.next_run_dir(camp, c.tag),
                         dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=a.case_timeout,
                              meta=dict(condition=c.tag, bias=a.bias, rpdk=a.rpdk, code=a.code, dut=dut_text, cal_code=(a.cal_code if trim else None), deser=deser, bc=a.bc, reltol=a.reltol, op_steps=a.op_steps))))
    print(f"{len(order)} cases: {len(todo)} to run", flush=True)
    for ex in spice.run_many(todo, workers=a.workers, smoke=True):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: exit {ex.exit_code}, {ex.log_failures[:3]}", flush=True)
    bits = eye.prbs7(sp.link.NBITS)
    rows = []
    print(f"{'condition':15s} | words data/edge err (det) | map | w setup/hold ps | capture min ps | P mW | toggles")
    for c in order:
        p = spice.case_output(camp, c.tag, f"{rd.case_name(c, a.code)}.raw", sp.link.STOP)
        if p is None:
            print(f"{c.tag:15s} | missing")
            continue
        r = analyse(p, c, a.code, bits)
        rows.append(r)
        f = lambda x: "   -" if x is None else f"{x:4.0f}"
        bad = {o: v for o, v in r["derived"].items() if EXPECTED[o] not in v}
        print(f"{c.tag:15s} | {r['words']} {r['data_errors']}/{r['edge_errors']} ({r['edge_determinate']}) | "
              f"{'ok' if r['map_ok'] else 'DIFF ' + str(bad)} | {f(r['w_setup_ps'])}/{f(r['w_hold_ps'])} | "
              f"{f(r['capture_data_slack_min_ps'])} | {r['power_mw']:.1f} | {r['toggles']}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(code=a.code, dut=dut_text, cal_code=(a.cal_code if trim else None), deser=deser, bc=a.bc,
                                                       expected=EXPECTED, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
