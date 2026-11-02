"""RX readout timing card: element delays and CMOS capture slack over PVT (real PRBS data).

    uv run python analog/rx/sampler/tb/readout_timing/card.py [stress | all | tags...] [--code 20]
        [--chains full,div2] [--param K=V ...] [--workers 4] [--resume C] [--analyse-only]

C2 far-end replay -> CTLE EQ3 -> PI (code) -> serdes_rx_half_rate_samples_ac_rk -> four static data
converters (serdes_cml_to_cmos_data) and the readout clock chain (rx_readout_clock.spice: full =
2 GHz, div2 = CML /2 then 1 GHz) -> four CMOS DFFs.  One deck per condition and chain.

Per case, over the analysed bits:
  clk2q_ps     sampler D0 / D1 output crossing after the triggering gate-clock crossing (median, spread)
  conv_ps      data converter: CML lane crossing -> CMOS output crossing at VDD/2 (min / max)
  clk_path_ps  PI edge-clock rising crossing -> CMOS clock rising crossing (mod one PI period)
  setup_ps / hold_ps  per lane, the worst time from the last CMOS data transition to a CMOS clock
               rising edge and from that edge to the next transition (the capture window position)
These are the element and relation numbers for the readout structure comparison (balance).
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, spice
from serdes_flow.corners import STRESS, Condition, boundary_first, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_readout_timing_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/readout_timing"
CHAINS = {"full": "serdes_rx_readout_clock_full", "div2": "serdes_rx_readout_clock_div2"}
DUT = "serdes_rx_half_rate_samples_ac_rk"
BENCH = {"rb": "2k"}
LANES = ("d0", "d1", "e0", "e1")
CMOS = {"d0": "v(rd0)", "d1": "v(rd1)", "e0": "v(re0)", "e1": "v(re1)"}
CASE_TIMEOUT_S = 600

_s = importlib.util.spec_from_file_location("sampler_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")
sp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(sp)


def dut_text(params):
    return " ".join([DUT] + [f"{k}={v}" for k, v in {**BENCH, **params}.items()])


def case_name(c, chain, code):
    return f"{c.tag}_{chain}_c{code:02d}"


def deck(c, code, chain, params, ck_load):
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code, c.supply).items())
    saves = (".save v(dp) v(dn) v(ep) v(en) v(xdut.cdp) v(xdut.cdn) v(d0p) v(d0n) v(d1p) v(d1n) v(e0p) v(e0n) v(e1p) v(e1n) "
             "v(rkp) v(rkn) v(rd0) v(rd1) v(re0) v(re1) v(ck) v(vdd) i(Vdd)")
    text = spice.render(TEMPLATE, **spice.corner_values(c), EQ0_V=c.supply, EQ1_V=c.supply, CONTROL_SOURCES=ctl,
                        DUT=dut_text(params), CHAIN=CHAINS[chain], CK_LOAD=ck_load, SAVES=saves, CASES="@CASES@")
    n = case_name(c, chain, code)
    block = "\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}",
                       f"alter Veq0 dc={c.supply * (sp.EQ & 1)}", f"alter Veq1 dc={c.supply * (sp.EQ >> 1)}"]
                      + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
                      + [f"tran 2p {sp.link.STOP:.4e} {sp.link.SAVE_FROM:.4e} 4p",
                         "let pie=v(ep)-v(en)", "let gate=v(xdut.cdp)-v(xdut.cdn)", "let d0=v(d0p)-v(d0n)",
                         "let d1=v(d1p)-v(d1n)", "let e0=v(e0p)-v(e0n)", "let e1=v(e1p)-v(e1n)", "let rk=v(rkp)-v(rkn)",
                         "let power=-v(vdd)*i(Vdd)",
                         f"write {n}.raw pie gate d0 d1 e0 e1 rk v(rd0) v(rd1) v(re0) v(re1) v(ck) v(vdd) power",
                         "destroy all"])
    return text.replace("@CASES@", block)


def _after(ts, t):
    i = np.searchsorted(ts, t, side="right")
    return ts[i] if i < len(ts) else None


def _before(ts, t):
    i = np.searchsorted(ts, t, side="left") - 1
    return ts[i] if i >= 0 else None


def analyse(path, c, chain, code):
    w = spice.Waves(path)
    t_from = sp.link.T0 + (sp.link.WARM + 4) * sp.link.UI
    sel = w.t >= t_from
    t = w.t[sel]
    g = lambda k: w[k][sel]
    vdd = float(np.mean(g("v(vdd)")))
    out = dict(condition=c.tag, chain=chain, code=code, power_mw=float(np.mean(g("power")) * 1e3))
    ge, gp = crossings(t, g("gate"))
    # clk->q: per lane polarity of the gate edge that triggers it (the one giving the smaller worst delay)
    for lane in ("d0", "d1"):
        lc, _ = crossings(t, g(lane))
        best = None
        for pol in (1, -1):
            edges = ge[gp == pol]
            dl = np.array([x - _before(edges, x) for x in lc if _before(edges, x) is not None])
            if len(dl) and (best is None or dl.max() < best.max()):
                best = dl
        out[f"clk2q_{lane}_ps"] = float(np.median(best) * 1e12) if best is not None else None
        out[f"clk2q_{lane}_spread_ps"] = float(np.ptp(best) * 1e12) if best is not None else None
    ck_e, ck_p = crossings(t, g("v(ck)"), level=vdd / 2)
    ck_r = ck_e[ck_p > 0]
    pe, pp = crossings(t, g("pie"))
    pe_r = pe[pp > 0]
    cp = [x - _before(pe_r, x) for x in ck_r if _before(pe_r, x) is not None]
    out["ck_rises"] = int(len(ck_r))
    out["clk_path_ps"] = float(np.median(cp) * 1e12) if cp else None
    for lane in LANES:
        lc, lp = crossings(t, g(lane))
        cc, cpol = crossings(t, g(CMOS[lane]), level=vdd / 2)
        conv = []
        for x, p in zip(lc, lp):
            nxt = cc[(cc > x) & (cpol == p)]
            if len(nxt) and nxt[0] - x < 400e-12:
                conv.append(nxt[0] - x)
        out[f"conv_{lane}_min_ps"] = float(min(conv) * 1e12) if conv else None
        out[f"conv_{lane}_max_ps"] = float(max(conv) * 1e12) if conv else None
        su = [k - _before(cc, k) for k in ck_r if _before(cc, k) is not None]
        ho = [_after(cc, k) - k for k in ck_r if _after(cc, k) is not None]
        out[f"setup_{lane}_ps"] = float(min(su) * 1e12) if su else None
        out[f"hold_{lane}_ps"] = float(min(ho) * 1e12) if ho else None
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--code", type=int, default=20)
    ap.add_argument("--chains", default="full,div2")
    ap.add_argument("--param", action="append", default=["rk_wn=8", "rk_nfin=2"])
    ap.add_argument("--ck-load", default="100f")
    ap.add_argument("--bc", default="rx_c2_far_nominal@ctle_rc")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    chains = a.chains.split(",")
    params = dict(p.split("=", 1) for p in a.param)
    boundary.check_load(a.bc, sp.replay.signature())
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = sp.replay.stimuli(a.bc)
    (camp / "stimuli.inc").write_text(stim)
    keys = [(c, ch) for c in boundary_first(conds) for ch in chains]
    if not a.analyse_only:                     # a partial re-analysis must not shrink the campaign plan
        (camp / "plan.json").write_text(json.dumps(dict(decks={f"{c.tag}_{ch}": 1 for c, ch in keys}), indent=1))
    todo = []
    for c, ch in keys:
        name = f"{c.tag}_{ch}"
        if spice.case_output(camp, name, f"{case_name(c, ch, a.code)}.raw") is None and not a.analyse_only:
            todo.append((deck(c, a.code, ch, params, a.ck_load), spice.next_run_dir(camp, name),
                         dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=CASE_TIMEOUT_S,
                              meta=dict(condition=c.tag, chain=ch, code=a.code, dut=dut_text(params), bc=a.bc))))
    print(f"{len(keys)} cases: {len(todo)} to run", flush=True)
    for ex in spice.run_many(todo, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: exit {ex.exit_code}, {ex.log_failures[:3]}", flush=True)
    rows = []
    for c, ch in keys:
        p = spice.case_output(camp, f"{c.tag}_{ch}", f"{case_name(c, ch, a.code)}.raw")
        if p is None:
            print(f"{c.tag:15s} {ch:5s} | missing")
            continue
        rows.append(analyse(p, c, ch, a.code))
    (camp / "summary.json").write_text(json.dumps(dict(code=a.code, dut=dut_text(params), ck_load=a.ck_load, bc=a.bc, rows=rows),
                                                  indent=1, default=float))
    fmt = lambda x: f"{x:4.0f}" if x is not None else "   -"
    print(f"{'condition':15s} chain | clk2q d0/d1 | conv d0 min..max | clk path | setup / hold ps  d0  d1  e0  e1 | P mW")
    for r in rows:
        print(f"{r['condition']:15s} {r['chain']:5s} | {fmt(r['clk2q_d0_ps'])}/{fmt(r['clk2q_d1_ps'])} | "
              f"{fmt(r['conv_d0_min_ps'])}..{fmt(r['conv_d0_max_ps'])} | {fmt(r['clk_path_ps'])} | "
              + " ".join(f"{fmt(r[f'setup_{l}_ps'])}/{fmt(r[f'hold_{l}_ps'])}" for l in LANES) + f" | {r['power_mw']:.1f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
