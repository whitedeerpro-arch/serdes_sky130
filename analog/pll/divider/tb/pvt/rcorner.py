"""CML prescaler (÷2 ÷2 ÷2) with real bias and PDK resistors: what the ideal-resistor block grid does not see.

    uv run python analog/pll/divider/tb/pvt/rcorner.py <conds> --rpdk hh [--input-pp 0.3] [--pre whold2=80 ...] [--buf wt=24 ...] [--tag x] [--workers 3]

tb_prescaler8_lowov_ngspice.cir.in: 2 GHz sine of --input-pp through the real upstream buffer, 5 fF per tap.  Over the last
16 of 48 ns: differential swing and common mode of each stage's clock at its gates and of its output, output frequency from the
rising crossings (a crossing count is off by one when an edge falls on the window's end), first stage's tail node, feedback frequency.
--pre: parameters of the cell.  --buf: parameters of the upstream buffer.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_prescaler8_lowov_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/divider/rcorner"
STOP = 48e-9
SAVE_FROM = 30e-9
NODES = ["bp", "bn", "xpre.x2.ckp", "xpre.x2.ckn", "xpre.x4.ckp", "xpre.x4.ckn", "xpre.x8.ckp", "xpre.x8.ckn", "d02p", "d02n", "d04p", "d04n", "d08p", "d08n", "fb0", "xpre.x2.xmaster.tail", "vbias", "xpre.vbias_logic"]
PAIRS = (("input", "bp", "bn", 2e9), ("q2 clock", "xpre.x2.ckp", "xpre.x2.ckn", 2e9), ("q4 clock", "xpre.x4.ckp", "xpre.x4.ckn", 1e9), ("q8 clock", "xpre.x8.ckp", "xpre.x8.ckn", 5e8),
         ("q2", "d02p", "d02n", 1e9), ("q4", "d04p", "d04n", 5e8), ("q8", "d08p", "d08n", 2.5e8))


def frequency(t, y):
    e, p = crossings(t, y)
    r = e[p > 0]
    return (len(r) - 1) / (r[-1] - r[0]) if len(r) > 2 else 0.0


def deck(c, rpdk, pp, params, camp, buf=()):
    text = spice.render(TEMPLATE, **spice.corner_values(c), FREQ_HZ=2e9, STOP=f"{STOP:.4e}")
    a = "Xpre bp bn d02p d02n d04p d04n d08p d08n vbias vdd 0 pll_cml_prescaler8"
    assert text.count(a) == 1
    text = text.replace(a, a + (" " + " ".join(params) if params else ""))
    a = "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer"
    assert text.count(a) == 1
    text = text.replace(a, a + (" " + " ".join(buf) if buf else ""))
    a = "input_pp=.3"
    assert text.count(a) == 1
    text = text.replace(a, f"input_pp={pp}")
    lines = []
    for l in text.splitlines():
        if l.startswith("wrdata "):
            l = "set filetype=binary\nwrite pre.raw " + " ".join(f"v({n})" for n in NODES)
        elif l.startswith("tran "):
            l = f"tran 4p {STOP:.4e} {SAVE_FROM:.4e} 4p"
        elif l.startswith("let "):
            continue
        lines.append(l)
    text = "\n".join(lines) + "\n"
    assert text.count(".control\n") == 1
    text = text.replace(".control\n", ".save " + " ".join(f"v({n})" for n in NODES) + "\n.control\n")
    camp.mkdir(parents=True, exist_ok=True)
    return bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, rpdk)


def analyse(path):
    w = spice.Waves(path)
    sel = w.t > STOP - 16e-9
    t = w.t[sel]
    row = {}
    for lab, p, n, want in PAIRS:
        y, cm = (w[f"v({p})"] - w[f"v({n})"])[sel], ((w[f"v({p})"] + w[f"v({n})"]) / 2)[sel]
        row[lab] = dict(swing=float(np.ptp(y)), cm=float(cm.mean()), freq=frequency(t, y), want=want)
    vdd = float(np.max(w["v(fb0)"][sel]))
    row["fb"] = frequency(t, w["v(fb0)"][sel] - vdd / 2)
    v = w["v(xpre.x2.xmaster.tail)"][sel]
    row["tail_min"] = float(v.min())
    row["vbias"], row["vlogic"] = float(w["v(vbias)"][sel].mean()), float(w["v(xpre.vbias_logic)"][sel].mean())
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="+")
    ap.add_argument("--rpdk", default="hh", choices=("tt", "ll", "hh"))
    ap.add_argument("--input-pp", type=float, default=0.3)
    ap.add_argument("--pre", action="append", default=[])
    ap.add_argument("--buf", action="append", default=[])
    ap.add_argument("--tag", default="")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else [Condition.parse(x) for x in a.conds]
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_r{a.rpdk}{a.tag}")
    jobs = [(deck(c, a.rpdk, a.input_pp, a.pre, camp, a.buf), camp / c.tag, dict(timeout_s=3600, meta=dict(condition=c.tag, rpdk=a.rpdk, input_pp=a.input_pp, pre=a.pre, buf=a.buf))) for c in conds]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok and not (ex.run_dir / "pre.raw").exists():
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}", flush=True)
    rows = {}
    print(f"R {a.rpdk}, input {a.input_pp * 1e3:.0f} mVpp, {' '.join(a.pre) or 'default'} buf {' '.join(a.buf) or 'default'}; swing mVpp / CM V / output GHz")
    print(f"{'condition':15s} {'input':>16s} {'x2 gates':>16s} {'x4 gates':>16s} {'x8 gates':>16s} {'q2':>16s} {'q4':>16s} {'q8':>16s} {'fb GHz':>7s} {'tail min':>8s}")
    for c in conds:
        p = camp / c.tag / "pre.raw"
        if not p.exists():
            print(f"{c.tag:15s} missing")
            continue
        r = analyse(p)
        rows[c.tag] = r
        f = lambda k: f"{r[k]['swing'] * 1e3:4.0f}/{r[k]['cm']:.2f}/{r[k]['freq'] / 1e9:.3f}"
        print(f"{c.tag:15s} {f('input'):>16s} {f('q2 clock'):>16s} {f('q4 clock'):>16s} {f('q8 clock'):>16s} {f('q2'):>16s} {f('q4'):>16s} {f('q8'):>16s} {r['fb'] / 1e9:7.4f} {r['tail_min']:8.3f}", flush=True)
    bad = [t for t, r in rows.items() if abs(r["fb"] / 2.5e8 - 1) > 0.002 or any(abs(r[k]["freq"] / r[k]["want"] - 1) > 0.002 for k in ("q2", "q4", "q8"))]
    if rows:
        k = min(rows, key=lambda t: rows[t]["q2"]["swing"])
        print(f"{len(rows)} conditions; divide errors {len(bad)} {bad[:8]}; lowest q2 {rows[k]['q2']['swing'] * 1e3:.0f} mVpp at {k}; lowest q4 {min(r['q4']['swing'] for r in rows.values()) * 1e3:.0f}, q8 {min(r['q8']['swing'] for r in rows.values()) * 1e3:.0f}")
    (camp / "summary.json").write_text(json.dumps(dict(rpdk=a.rpdk, input_pp=a.input_pp, pre=a.pre, buf=a.buf, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
