"""RX sampler clock path over PVT and clock-interface sizing: PI -> clock interface -> latch clock pairs.

    uv run python analog/rx/sampler/tb/clock_ac/sweep.py [stress | all | tags...] [--code 12]
        [--variant NAME=DUT[:k=v,k=v...] ...] [--bias ideal|real] [--rpdk tt|ll|hh] [--workers 4]
        [--resume C] [--reltol 1e-3] [--analyse-only]

Ideal anchors drive the real PI; the PI drives the real sampler DUT (sampler/tb/link_pvt
variants), whose data input is static.  14 ns per case, measured over the last 2 ns (4 clock
cycles).  The AC-coupled gates settle with tau = rb (cc + Cgate) ~1.7 ns at the bench rb = 2 kohm;
an 8 ns bench left a decaying differential offset (-7 -> -4 mV per cycle) that read as a 1-2 %
duty error, at 12 ns the residue is < 0.1 %.

Per case: PI output swing, clock-buffer output swing (ac), gate swing and common mode, duty cycle of
the gate clock, and the clock steering of the D0 master latch: the fraction of the tail current
the clock moves between track and hold, (max - min of I_track) / mean(I_track + I_hold).
Default variants: stock and ac (as in rx_half_rate_samples_ac.spice).  ac_trim runs at trim code 32.
Variant keys pi_<name> go to the PI rotator as <name> (pi_cmix=150f), the others to the DUT.
--bias real: bandgap reference and module copies (serdes_flow.bias); --rpdk: project resistors as PDK
high_po, library section MOS corner x this resistor corner (as link_pvt).
Resume: only the cases without a waveform run again, in <deck>.rN (--reltol for the ac_trim cases whose
time step collapses at the default 1e-4, see link_pvt); a case still missing is reported, not fatal.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_clock_ac_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/clock_ac"
STOP, SAVE_FROM, MEAS_FROM = 14e-9, 11.9e-9, 12e-9
NF_LVT = "msky130_fd_pr__nfet_01v8_lvt"
CT = f"@m.xdut.xd0.xm.xct.xmos.{NF_LVT}[id]"
CH = f"@m.xdut.xd0.xm.xch.xmos.{NF_LVT}[id]"


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


sp = _load("sampler_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")


def dut_defaults(subckt="serdes_rx_half_rate_samples_ac"):
    """Default parameters of the DUT subcircuit as written in its .spice file (recorded per campaign,
    so variants given as overrides stay interpretable after the defaults change)."""
    path = ROOT / "analog/rx/sampler/spice/rx_half_rate_samples_ac.spice"
    out, on = {}, False
    for line in path.read_text().splitlines():
        if line.startswith(f".subckt {subckt}"):
            on = True
        elif on and line.startswith("+"):
            out.update(kv.split("=", 1) for kv in line[1:].split() if "=" in kv)
        elif on:
            break
    return out


def parse_variant(text):
    """NAME=DUT[:k=v,k=v] -> (name, dut, params)."""
    name, rest = text.split("=", 1)
    dut, _, kv = rest.partition(":")
    return name, dut, dict(x.split("=", 1) for x in kv.split(",") if x)


def case_name(c, var):
    return f"{c.tag}_{var}"


def deck(conds, code, dut, params, var, real_bias=False, rpdk=None, camp=None, reltol=None):
    c0 = conds[0]
    ac = dut != "stock"
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code, c0.supply).items())
    if dut in ("ac_cal", "ac_trim"):
        ctl += "\n" + sp.cal_sources(32)
    nodes = ["dp", "dn", "xdut.cdp", "xdut.cdn", "vdd"] + (["xdut.xcd.bp", "xdut.xcd.bn"] if ac else [])
    saves = ".save " + " ".join(f"v({n})" for n in nodes) + f" i(Vdd) {CT} {CH}"
    pi_params = " ".join(f"{k[3:]}={v}" for k, v in params.items() if k.startswith("pi_"))
    params = {k: v for k, v in params.items() if not k.startswith("pi_")}
    text = spice.render(TEMPLATE, **spice.corner_values(c0), DUT=sp.dut(dut, params), PI_PARAMS=pi_params, CONTROL_SOURCES=ctl,
                        SAVES=saves, CASES="@CASES@")
    vecs = ["piout", "buf", "gate", "gcm", "ict", "ich", "power"] if ac else ["piout", "gate", "gcm", "ict", "ich", "power"]
    blocks = []
    for c in conds:
        blocks.append("\n".join(
            [f"* case {case_name(c, var)}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}"]
            + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
            + ([f"option reltol={reltol} itl4=200"] if reltol else [])
            + [f"tran 2p {STOP:.4e} {SAVE_FROM:.4e} 4p",
               "let piout=v(dp)-v(dn)", "let gate=v(xdut.cdp)-v(xdut.cdn)", "let gcm=(v(xdut.cdp)+v(xdut.cdn))/2",
               f"let ict={CT}", f"let ich={CH}", "let power=-v(vdd)*i(Vdd)"]
            + (["let buf=v(xdut.xcd.bp)-v(xdut.xcd.bn)"] if ac else [])
            + [f"write {case_name(c, var)}.raw " + " ".join(vecs), "destroy all"]))
    text = text.replace("@CASES@", "\n".join(blocks))
    if real_bias:
        text = bias.real(text)
    if rpdk:
        text = bias.section(rcorner.to_pdk(text, camp), c0.process, rpdk)
    return text


def duty(t, y):
    e, pol = crossings(t, y)
    r, f = e[pol > 0], e[pol < 0]
    if len(r) < 2 or not len(f):
        return None
    per = np.mean(np.diff(r))
    highs = [f[f > a][0] - a for a in r[:-1] if np.any(f > a)]
    return float(np.mean(highs) / per)


def analyse(path, c, var):
    w = spice.Waves(path)
    sel = w.t >= MEAS_FROM
    t = w.t[sel]
    g = lambda k: w[k][sel]
    ict, ich = np.abs(g("ict")), np.abs(g("ich"))
    r = dict(condition=c.tag, variant=var, pi_pp=float(np.ptp(g("piout"))), gate_pp=float(np.ptp(g("gate"))),
             gate_cm=float(np.mean(g("gcm"))), duty=duty(t, g("gate")),
             steering=float(np.ptp(ict) / np.mean(ict + ich)), tail_ua=float(np.mean(ict + ich) * 1e6),
             power_mw=float(np.mean(g("power")) * 1e3))
    try:
        r["buf_pp"] = float(np.ptp(g("buf")))
    except KeyError:
        r["buf_pp"] = None
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--code", type=int, default=12)
    ap.add_argument("--variant", action="append", default=[])
    ap.add_argument("--bias", choices=("ideal", "real"), default="ideal")
    ap.add_argument("--rpdk", choices=("tt", "ll", "hh"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--reltol", type=float)
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    variants = [parse_variant(v) for v in (a.variant or ["stock=stock", "ac=ac"])]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    by_proc = {}
    for c in conds:
        by_proc.setdefault(c.process, []).append(c)
    raw = lambda c, var: next(iter(sorted(camp.glob(f"{c.process}_{var}*/{case_name(c, var)}.raw"))), None)
    todo = []
    for var, dut, params in variants:
        for proc, cs in by_proc.items():
            missing = [c for c in cs if raw(c, var) is None]
            if missing and not a.analyse_only:
                pi = {k[3:]: v for k, v in params.items() if k.startswith("pi_")}
                meta = dict(process=proc, variant=var, dut=sp.dut(dut, {k: v for k, v in params.items() if not k.startswith("pi_")}),
                            pi=pi, code=a.code, bias=a.bias, rpdk=a.rpdk, reltol=a.reltol, conditions=[c.tag for c in missing])
                todo.append((deck(missing, a.code, dut, params, var, a.bias == "real", a.rpdk, camp, a.reltol),
                             spice.next_run_dir(camp, f"{proc}_{var}"), dict(meta=meta)))
    print(f"{len(conds)} conditions x {len(variants)} variants: {len(todo)} decks to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=a.workers)):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:2]}", flush=True)
    rows, absent = [], []
    for var, _, _ in variants:
        for c in conds:
            p = raw(c, var)
            if p is None:
                absent.append(case_name(c, var))
            else:
                rows.append(analyse(p, c, var))
    (camp / "summary.json").write_text(json.dumps(dict(code=a.code, bias=a.bias, rpdk=a.rpdk, dut_defaults=dut_defaults(),
                                                       variants=[dict(name=v, dut=d, params=p) for v, d, p in variants],
                                                       missing=absent, rows=rows), indent=1))
    if absent:
        print(f"missing (rerun with --resume, --reltol): {absent}")
    print(f"{'variant':10s} {'condition':15s} | pi / buf / gate mVpp | gate cm V | duty | steering | tail uA | P mW")
    for r in rows:
        buf = f"{r['buf_pp']*1e3:4.0f}" if r["buf_pp"] is not None else "   -"
        print(f"{r['variant']:10s} {r['condition']:15s} | {r['pi_pp']*1e3:4.0f} / {buf} / {r['gate_pp']*1e3:4.0f} | "
              f"{r['gate_cm']:.3f} | {r['duty']:.3f} | {r['steering']:.2f} | {r['tail_ua']:4.0f} | {r['power_mw']:.2f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
