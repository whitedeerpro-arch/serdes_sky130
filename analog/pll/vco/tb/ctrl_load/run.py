"""Small-signal load of the VCO control node while the ring oscillates: what the loop filter's Cf node really carries.

    uv run python analog/pll/vco/tb/ctrl_load/run.py [--procs tt,ss,ff,sf,fs] [--passive tt,hh,ll] [--conds v1650_t85,v1950_t-40]
        [--vs 1.0,1.15,edge] [--amp 10e-3] [--fm 50e6] [--workers 4] [--analyse <campaign>]

pll_vco_ring4_4b with the bench of the VCO working map (real bias, PDK R, four buffers), at the code of
config/pll_code_table.json for the condition.  Vctrl = DC + a sine of --amp at --fm in series; after 14 ns of settling,
two sine periods are demodulated: Y = I / V at fm, C = Im(Y) / (2 pi fm), G = Re(Y).  The 2 GHz ripple the ring
injects into the node averages out.  'edge' in --vs is the CP window's upper edge, VDD - 0.39 V.
"""
import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

TEMPLATE = ROOT / "analog/pll/vco/tb/phase_noise/tb_vco_isf_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/vco/ctrl_load"
CODES = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
SETTLE = 14e-9


def name(c, code, v):
    return f"{c.tag}_c{code}_v{round(v * 1000)}.raw"


def deck(process, rc, points, camp, amp, fm):
    stop = SETTLE + 2 / fm
    c0 = points[0][0]
    text = spice.render(TEMPLATE, **spice.corner_values(c0), VCTRL=1.2, INJECT="", PROBES="", TSTEP="2p", STOP=f"{stop:.4e}",
                        SAVE_FROM=f"{SETTLE:.4e}", OUT="x.raw", CFG0=0, CFG1=0, CFG2=0)
    text = re.sub(r"\.control.*?\.endc\n", "", text, flags=re.S).replace("reltol=1e-5", "reltol=1e-4")
    old = "ctrl cfg0 cfg1 cfg2 vbias vdd 0 pll_vco_ring4_pvt_candidate"
    assert text.count(old) == 1
    text = text.replace(old, "ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd 0 pll_vco_ring4_4b").replace("Vb2 cfg2 0 0\n", "Vb2 cfg2 0 0\nVb3 cfg3 0 0\n")
    inc = '.include "' + str(ROOT / "analog/pll/vco/spice/vco_ring4_pvt_candidate.spice") + '"'
    assert text.count(inc) == 1
    text = text.replace(inc, inc.replace("vco_ring4_pvt_candidate", "cap_bank_4b") + "\n" + inc.replace("vco_ring4_pvt_candidate", "vco_ring4_4b"))
    old = "Vctrl ctrl 0 1.2"
    assert text.count(old) == 1
    text = text.replace(old, f"Vctrl ctrl_dc 0 1.2\nVsin ctrl ctrl_dc SIN(0 {amp:.4e} {fm:.6e} {SETTLE:.4e})")
    old = ".save v(v0p) v(v0n)"
    assert text.count(old) == 1
    text = text.replace(old, ".save v(ctrl_dc) i(vsin) v(v0p) v(v0n)")
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.section(rcorner.to_pdk(bias.real(text), camp), process, rc)
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for c, code, v in points:
        lines += [f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}"]
        lines += [f"alter Vb{k} dc={c.supply if (code >> k) & 1 else 0}" for k in range(4)]
        lines += [f"alter Vctrl dc={v}", f"tran 2p {stop:.4e} {SETTLE:.4e}", f"write {name(c, code, v)} v(ctrl) v(ctrl_dc) i(vsin) v(v0p) v(v0n)", "destroy all"]
    text = text[: text.rindex(".end")]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def measure(path, fm, amp):
    w = spice.Waves(path)
    t = w.t
    sel = t >= SETTLE
    t, v = t[sel], (w["v(ctrl)"] - w["v(ctrl_dc)"])[sel]
    i = -w["i(vsin)"][sel]                       # current into the ctrl node
    n = int((t[-1] - t[0]) * fm)
    m = t <= t[0] + n / fm
    t, v, i = t[m], v[m], i[m]
    ph = np.exp(-2j * np.pi * fm * t)
    V = 2 * np.trapezoid(v * ph, t) / (t[-1] - t[0])
    I = 2 * np.trapezoid(i * ph, t) / (t[-1] - t[0])
    y = I / V
    yq = w["v(v0p)"][sel][m] - w["v(v0n)"][sel][m]
    from serdes_flow.waves import crossings
    e, s = crossings(t, yq)
    r = e[s > 0]
    f0 = (len(r) - 1) / (r[-1] - r[0]) if len(r) > 3 else float("nan")
    return dict(c_f=float(y.imag / (2 * np.pi * fm)), g_s=float(y.real), v_amp=float(abs(V)), f0=float(f0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--procs", default="tt,ss,ff,sf,fs")
    ap.add_argument("--passive", default="tt,hh,ll")
    ap.add_argument("--conds", default="v1650_t85,v1950_t-40")
    ap.add_argument("--vs", default="1.0,1.15,edge")
    ap.add_argument("--amp", type=float, default=10e-3)
    ap.add_argument("--fm", type=float, default=50e6)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--analyse")
    a = ap.parse_args()
    camp = ROOT / a.analyse if a.analyse else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    groups = {}
    for p in a.procs.split(","):
        for rc in a.passive.split(","):
            pts = []
            for cv in a.conds.split(","):
                c = Condition.parse(f"{p}_{cv}")
                code = CODES[f"{c.tag}:{rc}"]["code"]
                for vv in a.vs.split(","):
                    pts.append((c, code, round(c.supply - 0.39, 3) if vv == "edge" else float(vv)))
            groups[(p, rc)] = pts
    if not a.analyse:
        jobs = [(deck(p, rc, pts, camp / "snap" / f"{p}_{rc}", a.amp, a.fm), spice.next_run_dir(camp, f"{p}_{rc}"),
                 dict(timeout_s=240 * len(pts) + 600, meta=dict(process=p, passive=rc, points=len(pts), amp=a.amp, fm=a.fm)))
                for (p, rc), pts in groups.items()]
        for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
            if not ex.ok:
                print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    print(f"{'condition':15s} {'rc':3s} {'code':>4s} {'Vctrl':>6s} {'f0 GHz':>7s} {'C fF':>7s} {'G uS':>7s}")
    for (p, rc), pts in groups.items():
        for c, code, v in pts:
            path = spice.case_output(camp, f"{p}_{rc}", name(c, code, v), SETTLE + 2 / a.fm)
            if path is None:
                print(f"{c.tag:15s} {rc:3s} missing")
                continue
            m = measure(path, a.fm, a.amp)
            rows[f"{c.tag}:{rc}:{code}:{v}"] = m
            print(f"{c.tag:15s} {rc:3s} {code:4d} {v:6.3f} {m['f0'] / 1e9:7.3f} {m['c_f'] * 1e15:7.1f} {m['g_s'] * 1e6:7.2f}", flush=True)
    c = np.array([r["c_f"] for r in rows.values()])
    print(f"C {c.min() * 1e15:.1f}-{c.max() * 1e15:.1f} fF over {len(c)} points")
    (camp / "summary.json").write_text(json.dumps(dict(amp=a.amp, fm=a.fm, settle=SETTLE, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
