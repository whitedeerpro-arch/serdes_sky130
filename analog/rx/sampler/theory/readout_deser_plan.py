"""RX readout CMOS 1:4 timing plan (sizing flow: constraints + coarse model, before the circuit).

    uv run python analog/rx/sampler/theory/readout_deser_plan.py [--card CAMPAIGN] [--clocks CAMPAIGN]

Structure (rx_readout_deser16.spice): per clock phase X in {ckq, ckqb, ckm, ckmb} two lanes, each a
4-deep shift register on X rising (stage 0 is the capture flop of the converted CML lane) and a
4-bit word register clocked by a 250 MHz strobe at the opposite phase.  One 2-bit Johnson counter
on ckq gives J0 and J1 (J1 = J0 one cycle later, strobe of the ckqb lanes); retimed copies give the
other strobes: kq = J0 @ ckqb (ckq lanes), km = J0 @ ckm (ckmb lanes), kmb = km @ ckmb (ckm lanes).
The word clock w = not J1 rises at ckq + 3 ns after the J0 rising edge, after all four loads.

Inputs: the lean DFF card (serdes_cmos_dff, analog/common/devices/tb/cmos_dff_card --cell dff) and
the measured CMOS clock half periods H_q = ckqb - ckq, H_m = ckmb - ckm and ckm - ckq of the demux2
p2 campaign (readout_demux).  Per condition every path class gets its setup / hold margin (ps):
  sr        shift register on one edge: hold tcq_min - th, setup 1000 - tcq - tsu
  counter   J1 -> inverter -> J0 on ckq
  kq/km/kmb strobe retiming (the source changes every 2 ns; the nearer sample is the critical one)
  load_X    word register of phase X against its shift register
  word      the 32 word-register outputs against w rising
Strobe and word-clock buffers are two inverters (card buf2).  tcq / tsu / th are per condition, so a
margin is that condition's, not a cross-corner worst stack.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

RESULTS = ROOT / "results/analog/rx/sampler/readout_deser_plan"
CARDS = ROOT / "results/analog/common/devices/cmos_dff_card"
DEMUX = ROOT / "results/analog/rx/sampler/readout_demux"


def latest_card():
    for d in sorted(CARDS.glob("*/summary.json"), reverse=True):
        if json.loads(d.read_text())["cell"] == "serdes_cmos_dff":
            return d.parent


def clock_relations(camp):
    out = {}
    for c in grid45():
        raw = next((camp / c.tag).glob("*.raw"), None)
        if raw is None:
            continue
        w = spice.Waves(raw)
        sel = w.t > 20e-9
        t = w.t[sel]
        vdd = float(np.mean(w["v(vdd)"][sel]))
        r = {}
        for k in ("v(ckq)", "v(xro.ckqb)", "v(ckm)", "v(xro.ckmb)"):
            e, p = crossings(t, w[k][sel], level=vdd / 2)
            r[k] = e[p > 0]
        rel = lambda a, b: float(np.median([(x - b[np.searchsorted(b, x) - 1]) for x in a if np.searchsorted(b, x) > 0]) * 1e12)
        out[c.tag] = dict(h_q=rel(r["v(xro.ckqb)"], r["v(ckq)"]), h_m=rel(r["v(xro.ckmb)"], r["v(ckm)"]),
                          m_q=rel(r["v(ckm)"], r["v(ckq)"]))
    return out


def margins(k, ck):
    """Setup / hold margins (ps) of every path class for one condition."""
    tcq, tcq0 = max(k["tcq_rise_ps"], k["tcq_fall_ps"]), min(k["tcq_rise_ps"], k["tcq_fall_ps"])
    tsu, th, buf = k["tsu_ps"], k["th_ps"], k["buf2_ps"]
    inv = buf / 2
    hq, hm, mq = ck["h_q"], ck["h_m"], ck["m_q"]
    m = {}
    m["sr"] = (1000 - tcq - tsu, tcq0 - th)
    m["counter"] = (1000 - tcq - inv - tsu, tcq0 + inv - th)
    # retime: source changes at tcq after its edge, sampled `d` later (and d - 1000 earlier)
    rt = lambda d: (d - tcq - tsu, tcq0 + 1000 - d - th)
    m["kq"], m["km"], m["kmb"] = rt(hq), rt(mq), rt(hm)
    # load: shift register changes at X + tcq, strobe edge at X + d + tcq_s + buf
    ld = lambda d: (d + tcq0 + buf - tcq - tsu, 1000 - d - tcq - buf + tcq0 - th)
    m["load_q"], m["load_qb"], m["load_m"], m["load_mb"] = ld(hq), ld(1000 - hq), ld(hm), ld(1000 - hm)
    # word-register output change times relative to the J0 edge (ckq), latest and earliest
    # (strobe flop tcq + buffer + word flop tcq after the strobe flop's clock edge)
    late = {g: d + 2 * tcq + buf for g, d in (("qb", 1000), ("q", hq), ("mb", mq), ("m", mq + hm))}
    early = {g: d + 2 * tcq0 + buf for g, d in (("qb", 1000), ("q", hq), ("mb", mq), ("m", mq + hm))}
    w_late, w_early = 3000 + tcq + inv + buf, 3000 + tcq0 + inv + buf
    m["word"] = (w_early - max(late.values()) - tsu, 4000 + min(early.values()) - w_late - th)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--card")
    ap.add_argument("--clocks", default="results/analog/rx/sampler/readout_demux/20261102T114529Z")
    a = ap.parse_args()
    card_dir = (ROOT / a.card) if a.card else latest_card()
    card = {r["condition"]: r for r in json.loads((card_dir / "summary.json").read_text())["rows"]}
    ck = clock_relations(ROOT / a.clocks)
    rows = {tag: margins(card[tag], ck[tag]) for tag in ck}
    names = list(next(iter(rows.values())))
    print(f"card {card_dir.relative_to(ROOT)}, clocks {a.clocks}")
    print(f"{'path':9s} {'setup min':>9s} {'at':>15s} {'hold min':>9s} {'at':>15s}")
    worst = {}
    for n in names:
        su = min(rows, key=lambda t: rows[t][n][0])
        ho = min(rows, key=lambda t: rows[t][n][1])
        worst[n] = dict(setup_ps=rows[su][n][0], setup_at=su, hold_ps=rows[ho][n][1], hold_at=ho)
        print(f"{n:9s} {rows[su][n][0]:9.0f} {su:>15s} {rows[ho][n][1]:9.0f} {ho:>15s}")
    hq = [v["h_q"] for v in ck.values()]
    hm = [v["h_m"] for v in ck.values()]
    mq = [v["m_q"] for v in ck.values()]
    print(f"H_q {min(hq):.0f}..{max(hq):.0f}  H_m {min(hm):.0f}..{max(hm):.0f}  ckm-ckq {min(mq):.0f}..{max(mq):.0f} ps")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    (camp / "plan.json").write_text(json.dumps(dict(card=str(card_dir.relative_to(ROOT)), clocks=a.clocks, clock_relations=ck,
                                                    margins={t: {n: list(v) for n, v in m.items()} for t, m in rows.items()},
                                                    worst=worst), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
