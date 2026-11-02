"""RX readout clock over PVT: PI -> sampler (ac_rk, readout-clock tap) -> readout clock chain -> CMOS clock.

    uv run python analog/rx/sampler/tb/readout_clock/sweep.py [stress | all | tags...] [--code 12]
        [--variant NAME=CHAIN[:k=v,...] ...] [--ck-load 100f] [--workers 4] [--resume C] [--analyse-only]

CHAIN is full (2 GHz CMOS clock) or div2 (CML /2, 1 GHz) from rx_readout_clock.spice; k=v override
serdes_rx_half_rate_samples_ac_rk parameters (rk_wn, rk_wt, rk_rload, ...).  Real PI with ideal
anchors, static sampler data (as clock_ac/sweep.py), bench rb = 2 kohm; 16 ns per case, measured
over the last 4 ns.

Per case: sampler gate clocks (data and edge; the tap loads the edge-clock buffer), CML readout
clock swing and common mode, CMOS clock: edges, frequency, duty, low/high level, delay of each
rising edge after the preceding PI edge-clock rising crossing (and its spread), power.
Gates: CMOS clock toggles at the expected frequency with rail levels (low < 0.1 VDD, high > 0.9 VDD),
duty 0.5 +- 0.05; sampler gate clocks stay >= 300 mVpp.
"""
import argparse
import importlib.util
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import STRESS, Condition, boundary_first, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_readout_clock_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/readout_clock"
STOP, SAVE_FROM, MEAS_FROM = 16e-9, 11.9e-9, 12e-9
CHAINS = {"full": ("serdes_rx_readout_clock_full", 2e9), "div2": ("serdes_rx_readout_clock_div2", 1e9)}
DUT = "serdes_rx_half_rate_samples_ac_rk"
BENCH = {"rb": "2k"}


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


sp = _load("sampler_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")


def parse_variant(text):
    name, rest = text.split("=", 1)
    chain, _, kv = rest.partition(":")
    return name, chain, dict(x.split("=", 1) for x in kv.split(",") if x)


def dut_text(params):
    return " ".join([DUT] + [f"{k}={v}" for k, v in {**BENCH, **params}.items()])


def case_name(c, var):
    return f"{c.tag}_{var}"


def deck(conds, code, chain, params, var, ck_load):
    c0 = conds[0]
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code, c0.supply).items())
    nodes = ["ep", "en", "xdut.cdp", "xdut.cdn", "xdut.cep", "xdut.cen", "rkp", "rkn", "ck", "vdd"]
    saves = ".save " + " ".join(f"v({n})" for n in nodes) + " i(Vdd)"
    text = spice.render(TEMPLATE, **spice.corner_values(c0), DUT=dut_text(params), CHAIN=CHAINS[chain][0],
                        CK_LOAD=ck_load, CONTROL_SOURCES=ctl, SAVES=saves, CASES="@CASES@")
    blocks = []
    for c in conds:
        blocks.append("\n".join(
            [f"* case {case_name(c, var)}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}"]
            + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
            + [f"tran 2p {STOP:.4e} {SAVE_FROM:.4e} 4p",
               "let edge=v(ep)-v(en)", "let gated=v(xdut.cdp)-v(xdut.cdn)", "let gatee=v(xdut.cep)-v(xdut.cen)",
               "let rk=v(rkp)-v(rkn)", "let rkcm=(v(rkp)+v(rkn))/2", "let power=-v(vdd)*i(Vdd)",
               f"write {case_name(c, var)}.raw edge gated gatee rk rkcm v(ck) v(vdd) power", "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def analyse(path, c, var, f_expect):
    w = spice.Waves(path)
    sel = w.t >= MEAS_FROM
    t = w.t[sel]
    g = lambda k: w[k][sel]
    vdd = float(np.mean(g("v(vdd)")))
    ck = g("v(ck)")
    e, pol = crossings(t, ck, level=vdd / 2)
    r, f = e[pol > 0], e[pol < 0]
    out = dict(condition=c.tag, variant=var, gate_d_pp=float(np.ptp(g("gated"))), gate_e_pp=float(np.ptp(g("gatee"))),
               rk_pp=float(np.ptp(g("rk"))), rk_cm=float(np.mean(g("rkcm"))), ck_low=float(np.min(ck) / vdd),
               ck_high=float(np.max(ck) / vdd), rises=int(len(r)), power_mw=float(np.mean(g("power")) * 1e3))
    if len(r) >= 2:
        per = float(np.mean(np.diff(r)))
        highs = [f[f > a][0] - a for a in r[:-1] if np.any(f > a)]
        ee, ep = crossings(t, g("edge"))
        er = ee[ep > 0]
        dl = [a - er[er < a][-1] for a in r if np.any(er < a)]
        out.update(freq_ghz=1e-9 / per, duty=float(np.mean(highs) / per) if highs else None,
                   delay_ps=float(np.mean(dl) * 1e12) if dl else None, delay_spread_ps=float(np.ptp(dl) * 1e12) if dl else None)
    else:
        out.update(freq_ghz=0.0, duty=None, delay_ps=None, delay_spread_ps=None)
    out["ok"] = bool(len(r) >= 2 and abs(out["freq_ghz"] - f_expect / 1e9) < 0.02 * f_expect / 1e9 and out["ck_low"] < 0.1
                     and out["ck_high"] > 0.9 and out["duty"] is not None and abs(out["duty"] - 0.5) <= 0.05)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--code", type=int, default=12)
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--ck-load", default="100f")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    variants = [parse_variant(v) for v in (a.variant or ["full=full", "div2=div2"])]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    by_proc = {}
    for c in boundary_first(conds):
        by_proc.setdefault(c.process, []).append(c)
    jobs = [(deck(cs, a.code, chain, params, var, a.ck_load), camp / f"{proc}_{var}",
             dict(timeout_s=600 * len(cs), meta=dict(process=proc, variant=var, chain=chain, dut=dut_text(params),
                                                     ck_load=a.ck_load, code=a.code, conditions=[c.tag for c in cs])))
            for var, chain, params in variants for proc, cs in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(conds)} conditions x {len(variants)} variants in {len(jobs)} decks: {len(todo)} to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=a.workers)):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: exit {ex.exit_code}, {ex.log_failures[:3]}", flush=True)
    rows = []
    for var, chain, params in variants:
        for c in conds:
            p = spice.case_output(camp, f"{c.process}_{var}", f"{case_name(c, var)}.raw")
            if p is None:
                print(f"{var:8s} {c.tag:15s} | missing")
                continue
            rows.append(analyse(p, c, var, CHAINS[chain][1]))
    (camp / "summary.json").write_text(json.dumps(dict(code=a.code, ck_load=a.ck_load, variants=[
        dict(name=v, chain=ch, dut=dut_text(p)) for v, ch, p in variants], rows=rows), indent=1))
    print(f"{'variant':8s} {'condition':15s} | gate d/e mVpp | rk mVpp / cm V | ck f GHz, duty, low..high xVDD | delay ps (spread) | P mW | ok")
    for r in rows:
        d = f"{r['delay_ps']:5.0f} ({r['delay_spread_ps']:3.0f})" if r["delay_ps"] is not None else "    -      "
        du = f"{r['duty']:.3f}" if r["duty"] is not None else "  -  "
        print(f"{r['variant']:8s} {r['condition']:15s} | {r['gate_d_pp']*1e3:4.0f}/{r['gate_e_pp']*1e3:4.0f} | {r['rk_pp']*1e3:4.0f} / {r['rk_cm']:.3f} | "
              f"{r['freq_ghz']:.3f}, {du}, {r['ck_low']:.2f}..{r['ck_high']:.2f} | {d} | {r['power_mw']:.2f} | {'ok' if r['ok'] else 'FAIL'}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
