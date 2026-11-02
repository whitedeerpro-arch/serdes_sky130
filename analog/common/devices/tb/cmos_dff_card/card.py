"""CMOS DFF timing card (sizing flow, cell level) over PVT.

    uv run python analog/common/devices/tb/cmos_dff_card/card.py [stress | all | tags...] [--cell reset|dff]
        [--cell-param K=V ...] [--resume C] [--analyse-only]

Cells: reset = serdes_cmos_dff_reset (cmos_dff_reset.spice), dff = serdes_cmos_dff (cmos_dff.spice).

One deck per process corner (supply and temperature changed in the control block).  A 1 GHz clock
and a data line that toggles once per cycle, the toggle swept from 400 ps before to 250 ps after
the clock edge in 10 ps steps (four leading cycles at -500 ps give the nominal clk->q).  Both pass
two inverters; offsets are measured at the DUT pins (VDD/2 crossings).  The DUT drives a second DFF
on the same clock (shift-register load).

Per condition:
  tcq_rise_ps / tcq_fall_ps  clk rising -> q crossing at large setup
  tsu_ps   smallest setup (data before clock) for which the new value is captured and clk->q stays
           within 10 % of nominal for every larger setup
  th_ps    smallest offset after the clock edge (negative: before it) from which the old value is
           always captured
  buf2_ps  two-inverter clock buffer delay (wn=2/wp=4 then wn=4/wp=8, load two DFF clock pins)
Steps are 10 ps, so tsu / th carry +-10 ps of resolution.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_cmos_dff_card_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/devices/cmos_dff_card"
PERIOD, DELAY = 1e-9, 1e-9
LEAD = 4
OFFSETS = [-500e-12] * LEAD + [round(o, 12) for o in np.arange(-400e-12, 251e-12, 10e-12)]
STOP = DELAY + (len(OFFSETS) + 2) * PERIOD
SLEW = 20e-12
CELLS = {"reset": ("serdes_cmos_dff_reset", "{d} clk rst_b {q}"), "dff": ("serdes_cmos_dff", "{d} clk {q}")}


def cell_lines(cell, params):
    name, pins = CELLS[cell]
    p = " ".join(f"{k}={v}" for k, v in params.items())
    return "\n".join([f"Xdut {pins.format(d='d', q='q')} vdd 0 {name} {p}",
                      f"Xload {pins.format(d='q', q='q2')} vdd 0 {name} {p}"])


def data_pwl():
    pts, v = ["0", "0"], 0
    for k, o in enumerate(OFFSETS):
        t = DELAY + 15e-12 + k * PERIOD + o          # source clock crosses 0.5 at DELAY + 15 ps
        pts += [f"{t - SLEW / 2:.4e}", str(v), f"{t + SLEW / 2:.4e}", str(1 - v)]
        v = 1 - v
    return " ".join(pts)


def case_name(c):
    return c.tag


def deck(conds, cell, params):
    c0 = conds[0]
    text = spice.render(TEMPLATE, **spice.corner_values(c0), CELLS=cell_lines(cell, params), CLK_DELAY=f"{DELAY:.4e}", CLK_HIGH=f"{PERIOD / 2 - 30e-12:.4e}",
                        CLK_PERIOD=f"{PERIOD:.4e}", DATA_PWL=data_pwl(), CASES="@CASES@")
    blocks = []
    for c in conds:
        blocks.append("\n".join([f"* case {c.tag}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}",
                                 f"tran 1p {STOP:.4e} 0 2p", f"write {case_name(c)}.raw v(ck0) v(clk) v(d) v(q) v(vdd)",
                                 "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def analyse(path, c):
    w = spice.Waves(path)
    t = w.t
    vdd = float(np.mean(w["v(vdd)"]))
    ce, cp = crossings(t, w["v(clk)"], level=vdd / 2)
    edges = ce[cp > 0]
    se, sp_ = crossings(t, w["v(ck0)"], level=vdd / 2)
    src = se[sp_ > 0]
    de, dp = crossings(t, w["v(d)"], level=vdd / 2)
    qe, qp = crossings(t, w["v(q)"], level=vdd / 2)
    q = lambda x: float(np.interp(x, t, w["v(q)"]) > vdd / 2)
    rows = []
    for k, e in enumerate(edges[:len(OFFSETS)]):
        i = int(np.argmin(np.abs(de - e)))
        if abs(de[i] - e) > 0.6e-9:
            continue
        new = int(dp[i] > 0)
        cap = q(e + 0.8e-9)
        j = np.searchsorted(qe, e)
        tcq = float(qe[j] - e) if j < len(qe) and qe[j] < e + 0.9e-9 else None
        rows.append(dict(o=float(de[i] - e), new=new, cap=int(cap), tcq=tcq, rise=bool(j < len(qe) and qp[j] > 0)))
    lead = [r for r in rows if r["o"] < -0.3e-9 and r["cap"] == r["new"] and r["tcq"] is not None]
    nom = {True: np.median([r["tcq"] for r in lead if r["rise"]]), False: np.median([r["tcq"] for r in lead if not r["rise"]])}
    sweep = sorted(rows, key=lambda r: r["o"])
    tsu = None
    for r in sweep:                                     # most negative offset first
        good = r["o"] < 0 and r["cap"] == r["new"] and r["tcq"] is not None and r["tcq"] <= 1.1 * nom[bool(r["new"])]
        if r["o"] >= 0 or not good:
            break
        tsu = -r["o"]
    th = None
    for r in reversed(sweep):                           # most positive offset first
        if r["cap"] != 1 - r["new"]:
            break
        th = r["o"]
    b = [float(edges[np.searchsorted(edges, s)] - s) for s in src if np.searchsorted(edges, s) < len(edges)]
    return dict(condition=c.tag, tcq_rise_ps=float(nom[True] * 1e12), tcq_fall_ps=float(nom[False] * 1e12),
                tsu_ps=None if tsu is None else tsu * 1e12, th_ps=None if th is None else th * 1e12,
                buf2_ps=float(np.median(b) * 1e12), cycles=len(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["all"])
    ap.add_argument("--cell", default="reset", choices=sorted(CELLS))
    ap.add_argument("--cell-param", action="append", default=[])
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    params = dict(p.split("=", 1) for p in a.cell_param)
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    by_proc = {}
    for c in conds:
        by_proc.setdefault(c.process, []).append(c)
    todo = [(deck(cs, a.cell, params), camp / p, dict(timeout_s=1800, meta=dict(process=p, cell=a.cell, params=params,
                                                                                   cases=[x.tag for x in cs])))
            for p, cs in by_proc.items() if not (camp / p / "execution.json").exists() and not a.analyse_only]
    for ex in spice.run_many(todo, workers=4, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: exit {ex.exit_code}, {ex.log_failures[:3]}", flush=True)
    rows = []
    print(f"{'condition':15s} {'tcq r/f ps':>11s} {'tsu':>5s} {'th':>5s} {'buf2':>5s}")
    for p, cs in by_proc.items():
        for c in cs:
            r = analyse(camp / p / f"{case_name(c)}.raw", c)
            rows.append(r)
            f = lambda x: "  -" if x is None else f"{x:5.0f}"
            print(f"{c.tag:15s} {r['tcq_rise_ps']:5.0f}/{r['tcq_fall_ps']:5.0f} {f(r['tsu_ps'])} {f(r['th_ps'])} {r['buf2_ps']:5.0f}")
    (camp / "summary.json").write_text(json.dumps(dict(cell=CELLS[a.cell][0], params=params, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
