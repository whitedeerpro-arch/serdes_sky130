"""RX readout with CML 1:2 demux + matched conversion over PVT (real PRBS data).

    uv run python analog/rx/sampler/tb/readout_demux/run.py [stress | all | tags...] [--code 20]
        [--param K=V ...] [--demux serdes_rx_readout_demux2] [--demux-param K=V ...] [--workers 4] [--resume C] [--analyse-only]

C2 far-end replay -> CTLE EQ3 -> PI (code) -> serdes_rx_half_rate_samples_ac_rk -> demux block
(rx_readout_demux2.spice).  One deck per condition.

Per case:
  CML demux slack: for each of the 8 demux DFFs, the worst setup (capture edge - last lane crossing)
    and hold (next lane crossing - capture edge); capture edge = the domain clock crossing at the
    divider output (q falling for "a", q rising for "b"; m likewise), lane = the sampler output.
  CMOS slack: for each of the 8 CMOS DFFs, worst setup / hold of its converted lane against the
    rising edge of its CMOS domain clock (ckq / ckqb / ckm / ckmb).
  Data check: the four data sub-lanes (D0 a/b in domain Q with E1, D1 a/b in domain M with E0) each carry every 4th
    bit; the CMOS DFF outputs read just before the next capture edge are compared with the PRBS7 at
    the best offset (errors = mismatches).
  Edge check: an edge sample between bits j and j+1 must equal them when bits[j] == bits[j+1]; at a
    data transition either value is a valid phase-detector vote (the edge latch is often metastable
    there and resolves late, so edge-lane transition times spread over the window and their slack
    is not a pass criterion).  Edge sub-lanes carry every 4th edge sample; errors = mismatches at
    the determinate positions for the best offset.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, eye, spice
from serdes_flow.corners import STRESS, Condition, boundary_first, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_readout_demux_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/readout_demux"
DUT = "serdes_rx_half_rate_samples_ac_rk"
BENCH = {"rb": "2k"}
CASE_TIMEOUT_S = 900
# sub-lane: (sampler lane, domain, edge of the domain clock that changes it (+1 rising / -1 falling))
SUB = {"a0": ("d0", "q", -1), "b0": ("d0", "q", 1), "ae1": ("e1", "q", -1), "be1": ("e1", "q", 1),
       "a1": ("d1", "m", -1), "b1": ("d1", "m", 1), "ae0": ("e0", "m", -1), "be0": ("e0", "m", 1)}
CK = {("q", 1): "v(ckq)", ("q", -1): "v(xro.ckqb)", ("m", 1): "v(ckm)", ("m", -1): "v(xro.ckmb)"}

_s = importlib.util.spec_from_file_location("sampler_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")
sp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(sp)


def dut_text(params):
    return " ".join([DUT] + [f"{k}={v}" for k, v in {**BENCH, **params}.items()])


def case_name(c, code):
    return f"{c.tag}_c{code:02d}"


def deck(c, code, params, demux):
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code, c.supply).items())
    cml = ["d0p", "d0n", "d1p", "d1n", "e0p", "e0n", "e1p", "e1n", "xro.qp", "xro.qn", "xro.mp", "xro.mn"]
    for s in SUB:
        cml += [f"xro.{s}p", f"xro.{s}n"]
    cmos = [f"xro.r{s}" for s in SUB] + [f"q{s}" for s in SUB] + ["ckq", "xro.ckqb", "ckm", "xro.ckmb", "vdd"]
    saves = ".save " + " ".join(f"v({n})" for n in cml + cmos) + " i(Vdd)"
    text = spice.render(TEMPLATE, **spice.corner_values(c), EQ0_V=c.supply, EQ1_V=c.supply, CONTROL_SOURCES=ctl,
                        DUT=dut_text(params), DEMUX=demux, SAVES=saves, CASES="@CASES@")
    lets = [f"let {l}=v({l}p)-v({l}n)" for l in ("d0", "d1", "e0", "e1")]
    lets += ["let ckq_cml=v(xro.qp)-v(xro.qn)", "let ckm_cml=v(xro.mp)-v(xro.mn)"]
    lets += [f"let s_{s}=v(xro.{s}p)-v(xro.{s}n)" for s in SUB]
    vecs = ["d0", "d1", "e0", "e1", "ckq_cml", "ckm_cml"] + [f"s_{s}" for s in SUB] + [f"v(xro.r{s})" for s in SUB] \
        + [f"v(q{s})" for s in SUB] + ["v(ckq)", "v(xro.ckqb)", "v(ckm)", "v(xro.ckmb)", "v(vdd)", "power"]
    n = case_name(c, code)
    block = "\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}",
                       f"alter Veq0 dc={c.supply * (sp.EQ & 1)}", f"alter Veq1 dc={c.supply * (sp.EQ >> 1)}"]
                      + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
                      + [f"tran 2p {sp.link.STOP:.4e} {sp.link.SAVE_FROM:.4e} 4p"] + lets + ["let power=-v(vdd)*i(Vdd)",
                         f"write {n}.raw " + " ".join(vecs), "destroy all"])
    return text.replace("@CASES@", block)


def slack(data_t, cap_t):
    """Worst setup and hold of transitions data_t around capture instants cap_t (s)."""
    su, ho = [], []
    for k in cap_t:
        i = np.searchsorted(data_t, k)
        if i > 0:
            su.append(k - data_t[i - 1])
        if i < len(data_t):
            ho.append(data_t[i] - k)
    return (float(min(su) * 1e12) if su else None, float(min(ho) * 1e12) if ho else None)


def stride_errors(dec, bits, stride):
    best = (len(dec), None)
    for j0 in range(sp.link.WARM - 8, len(bits) - stride * (len(dec) - 1)):
        if j0 < 0:
            continue
        m = sum(d != bits[j0 + stride * k] for k, d in enumerate(dec))
        if m < best[0]:
            best = (m, j0)
    return best


def edge_errors(dec, bits, stride=4):
    """Fewest mismatches at determinate edge positions (bits[j] == bits[j+1]) over offsets."""
    truth = [bits[j] if bits[j] == bits[j + 1] else None for j in range(len(bits) - 1)]
    best = (len(dec), None, 0)
    for j0 in range(sp.link.WARM - 8, len(truth) - stride * (len(dec) - 1)):
        if j0 < 0:
            continue
        pos = [(d, truth[j0 + stride * k]) for k, d in enumerate(dec) if truth[j0 + stride * k] is not None]
        m = sum(d != v for d, v in pos)
        if (m, -len(pos)) < (best[0], -best[2]):
            best = (m, j0, len(pos))
    return best


def analyse(path, c, code, bits):
    w = spice.Waves(path)
    t_from = sp.link.T0 + (sp.link.WARM + 6) * sp.link.UI
    sel = w.t >= t_from
    t = w.t[sel]
    g = lambda k: w[k][sel]
    vdd = float(np.mean(g("v(vdd)")))
    out = dict(condition=c.tag, code=code, power_mw=float(np.mean(g("power")) * 1e3), sub={})
    dom = {d: crossings(t, g(f"ck{d}_cml")) for d in ("q", "m")}
    for s, (lane, d, edge) in SUB.items():
        le, _ = crossings(t, g(lane))
        de, dp = dom[d]
        cml_su, cml_ho = slack(le, de[dp == edge])
        cap_name = CK[(d, -edge)]                     # captured on the opposite edge
        ce, cp = crossings(t, g(cap_name), level=vdd / 2)
        cap = ce[cp > 0]
        re_, _ = crossings(t, g(f"v(xro.r{s})"), level=vdd / 2)
        cm_su, cm_ho = slack(re_, cap)
        r = dict(cml_setup_ps=cml_su, cml_hold_ps=cml_ho, cmos_setup_ps=cm_su, cmos_hold_ps=cm_ho, captures=int(len(cap)))
        q = g(f"v(q{s})")
        dec = [int(np.interp(b - 30e-12, t, q) > vdd / 2) for a, b in zip(cap[:-1], cap[1:])]
        if lane.startswith("d"):
            r["errors"], r["offset"] = stride_errors(dec, bits, 4)
            r["bits"] = len(dec)
        else:
            r["errors"], r["offset"], r["bits"] = edge_errors(dec, bits)
        out["sub"][s] = r
    subs = list(out["sub"].values())
    worst = lambda a, b: [min(x[a], x[b]) for x in subs if x[a] is not None and x[b] is not None]
    cm, cs = worst("cml_setup_ps", "cml_hold_ps"), worst("cmos_setup_ps", "cmos_hold_ps")
    out["cml_slack_min_ps"] = min(cm) if cm else None
    out["cmos_slack_min_ps"] = min(cs) if cs else None
    dsub = [out["sub"][k] for k in ("a0", "b0", "a1", "b1")]
    ds = [min(x["cmos_setup_ps"], x["cmos_hold_ps"]) for x in dsub if x["cmos_setup_ps"] is not None and x["cmos_hold_ps"] is not None]
    out["cmos_data_slack_min_ps"] = min(ds) if ds else None
    out["data_errors"] = sum(out["sub"][k]["errors"] for k in ("a0", "b0", "a1", "b1"))
    out["edge_errors"] = sum(out["sub"][k]["errors"] for k in ("ae0", "be0", "ae1", "be1"))
    # toggle census: domain clocks (CML, CMOS) and converted lanes
    out["toggles"] = dict(q_cml=int(len(dom["q"][0])), m_cml=int(len(dom["m"][0])),
                          **{k: int(len(crossings(t, g(v), level=vdd / 2)[0])) for k, v in
                             (("ckq", "v(ckq)"), ("ckm", "v(ckm)"), ("ra0", "v(xro.ra0)"), ("ra1", "v(xro.ra1)"))},
                          d0=int(len(crossings(t, g("d0"))[0])), a0_cml=int(len(crossings(t, g("s_a0"))[0])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--code", type=int, default=20)
    ap.add_argument("--param", action="append", default=["rk_wn=8", "rk_nfin=2"])
    ap.add_argument("--demux", default="serdes_rx_readout_demux2")
    ap.add_argument("--demux-param", action="append", default=[])
    ap.add_argument("--bc", default="rx_c2_far_nominal@ctle_rc")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    params = dict(p.split("=", 1) for p in a.param)
    demux = " ".join([a.demux] + a.demux_param)
    boundary.check_load(a.bc, sp.replay.signature())
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = sp.replay.stimuli(a.bc)
    (camp / "stimuli.inc").write_text(stim)
    order = boundary_first(conds)
    (camp / "plan.json").write_text(json.dumps(dict(decks={c.tag: 1 for c in order}), indent=1))
    todo = []
    for c in order:
        if spice.case_output(camp, c.tag, f"{case_name(c, a.code)}.raw") is None and not a.analyse_only:
            todo.append((deck(c, a.code, params, demux), spice.next_run_dir(camp, c.tag),
                         dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=CASE_TIMEOUT_S,
                              meta=dict(condition=c.tag, code=a.code, dut=dut_text(params), demux=demux, bc=a.bc))))
    print(f"{len(order)} cases: {len(todo)} to run", flush=True)
    for ex in spice.run_many(todo, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: exit {ex.exit_code}, {ex.log_failures[:3]}", flush=True)
    bits = eye.prbs7(sp.link.NBITS)
    rows = []
    for c in order:
        p = spice.case_output(camp, c.tag, f"{case_name(c, a.code)}.raw")
        if p is None:
            print(f"{c.tag:15s} | missing")
            continue
        rows.append(analyse(p, c, a.code, bits))
    (camp / "summary.json").write_text(json.dumps(dict(code=a.code, dut=dut_text(params), demux=demux, bc=a.bc, rows=rows),
                                                  indent=1, default=float))
    f = lambda x: f"{x:4.0f}" if x is not None else "   -"
    print(f"{'condition':15s} | data err a0 b0 a1 b1 | edge err ae1 be1 ae0 be0 (determinate) | data CML slack min | "
          f"data CMOS slack min | P mW")
    for r in rows:
        s = r["sub"]
        dcml = min(min(s[k]["cml_setup_ps"], s[k]["cml_hold_ps"]) for k in ("a0", "b0", "a1", "b1"))
        print(f"{r['condition']:15s} | " + " ".join(f"{s[k]['errors']}/{s[k]['bits']}" for k in ("a0", "b0", "a1", "b1"))
              + " | " + " ".join(f"{s[k]['errors']}/{s[k]['bits']}" for k in ("ae1", "be1", "ae0", "be0"))
              + f" | {dcml:4.0f} | {f(r['cmos_data_slack_min_ps'])} | {r['power_mw']:.1f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
