"""Feasible clock common-mode window of the RX sample DFF over PVT (constraint, not a design).

    uv run python analog/rx/sampler/tb/headroom_op/window.py [all | stress | tags...]
        [--dff KEY=VALUE ...] [--resume C] [--analyse-only]

The stock serdes_rx_sample_dff with ideal static inputs: data at the sampler input-buffer output
level (VDD - 0.147 V, measured by headroom_op/op.py), clocks +/-80 mV (--ck-half) around Vck, Vck swept
0.5..1.7 V.  Master holds, slave tracks, so both clock devices and both stacks are exercised.
For every device that carries current (id > 20 % of its tail) headroom = Vds - Vdsat.
Window = the Vck range where all of them are >= GATE (50 mV).  The level-shift law of any
candidate clock path is then checked against the window instead of being designed per corner.
--bias vbias_logic feeds the tails from the PLL r2 local low-overdrive reference (use with
--dff wtail=72 --dff nftail=24, the r2 sizes).  One deck per process, supply and temperature in the control block.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_sample_dff_window_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/clock_cm_window"
GATE_V = 0.05
IN_DROP = 0.147
CK_HALF = 0.08
SWEEP = (0.5, 1.7, 0.005)
NF, NF_LVT = "msky130_fd_pr__nfet_01v8", "msky130_fd_pr__nfet_01v8_lvt"


def devices():
    """(label, drain node, source node, device path) for both latches of instance Xd."""
    out = []
    for lat, (qp, qn) in (("m", ("xd.mp", "xd.mn")), ("s", ("qp", "qn"))):
        pre = f"xd.x{lat}"
        out += [(f"{lat}_dp", qn, f"{pre}.track", f"m.{pre}.xdp.xmos.{NF_LVT}"),
                (f"{lat}_dn", qp, f"{pre}.track", f"m.{pre}.xdn.xmos.{NF_LVT}"),
                (f"{lat}_hp", qn, f"{pre}.hold", f"m.{pre}.xhp.xmos.{NF_LVT}"),
                (f"{lat}_hn", qp, f"{pre}.hold", f"m.{pre}.xhn.xmos.{NF_LVT}"),
                (f"{lat}_ct", f"{pre}.track", f"{pre}.tail", f"m.{pre}.xct.xmos.{NF_LVT}"),
                (f"{lat}_ch", f"{pre}.hold", f"{pre}.tail", f"m.{pre}.xch.xmos.{NF_LVT}"),
                (f"{lat}_tail", f"{pre}.tail", "0", f"m.{pre}.xtail.xmos.{NF}")]
    return out


def case_name(c):
    return c.tag


def deck(conds, dff, ck_half=CK_HALF, bias="vbias"):
    c0 = conds[0]
    devs = devices()
    saves = ".save all " + " ".join(f"@{p}[vdsat] @{p}[id]" for *_, p in devs)
    text = spice.render(TEMPLATE, **spice.corner_values(c0), IN_DROP=IN_DROP, CK_HALF=ck_half, DFF_BIAS=bias,
                        DFF_PARAMS=" ".join(f"{k}={v}" for k, v in dff.items()), SAVES=saves, CASES="@CASES@")
    lets, names = [], ["v(ck)"]
    for lab, d, s, p in devs:
        lets += [f"let {lab}_vds=v({d})-v({s})" if s != "0" else f"let {lab}_vds=v({d})",
                 f"let {lab}_vdsat=@{p}[vdsat]", f"let {lab}_id=@{p}[id]"]
        names += [f"{lab}_vds", f"{lab}_vdsat", f"{lab}_id"]
    blocks = []
    for c in conds:
        blocks.append("\n".join([f"* case {case_name(c)}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}",
                                 f"alter Vref dc={c.supply}", f"dc Vck {SWEEP[0]} {SWEEP[1]} {SWEEP[2]}"]
                                + lets + [f"wrdata {case_name(c)}.tsv " + " ".join(names), "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def read_tsv(path):
    lines = path.read_text().split("\n")
    names = lines[0].split()
    data = np.atleast_2d(np.loadtxt(lines[1:]))
    return {n: data[:, i] for i, n in enumerate(names)}


def analyse(v, c):
    ck = v["v(ck)"]
    labs = [d[0] for d in devices()]
    head = {}
    for lat in "ms":
        itail = np.abs(v[f"{lat}_tail_id"])
        for lab in (l for l in labs if l.startswith(lat + "_")):
            h = v[f"{lab}_vds"] - v[f"{lab}_vdsat"]
            on = np.abs(v[f"{lab}_id"]) > 0.2 * itail
            head[lab] = np.where(on, h, np.inf)
    worst = np.min(np.array(list(head.values())), axis=0)
    ok = worst >= GATE_V
    if ok.any():
        idx = np.flatnonzero(ok)
        lo, hi = float(ck[idx[0]]), float(ck[idx[-1]])
        contiguous = bool(np.all(ok[idx[0]:idx[-1] + 1]))
    else:
        lo = hi = None
        contiguous = False
    i_best = int(np.argmax(worst))
    limiter = lambda i: min(head, key=lambda k: head[k][i])
    return dict(condition=c.tag, supply=c.supply, lo_v=lo, hi_v=hi, contiguous=contiguous,
                best_ck_v=float(ck[i_best]), best_headroom_v=float(worst[i_best]),
                lo_limiter=limiter(max(int(np.flatnonzero(ok)[0]) - 1, 0)) if ok.any() else None,
                hi_limiter=limiter(min(int(np.flatnonzero(ok)[-1]) + 1, len(ck) - 1)) if ok.any() else None,
                tail_id_ua=float(np.abs(v["m_tail_id"][i_best]) * 1e6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["all"])
    ap.add_argument("--dff", action="append", default=[])
    ap.add_argument("--ck-half", type=float, default=CK_HALF, help="static clock half-swing, V")
    ap.add_argument("--bias", choices=["vbias", "vbias_logic"], default="vbias",
                    help="tail bias: global vbias or the local low-overdrive reference (PLL r2)")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    dff = dict(p.split("=", 1) for p in a.dff)
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    by_proc = {}
    for c in conds:
        by_proc.setdefault(c.process, []).append(c)
    jobs = [(deck(cs, dff, a.ck_half, a.bias), camp / proc, dict(meta=dict(process=proc, dff=dff, ck_half_v=a.ck_half, bias=a.bias, conditions=[c.tag for c in cs])))
            for proc, cs in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(conds)} conditions in {len(jobs)} decks: {len(todo)} to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=4, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = [analyse(read_tsv(camp / c.process / f"{case_name(c)}.tsv"), c) for c in conds]
    (camp / "summary.json").write_text(json.dumps(dict(dff=dff, gate_v=GATE_V, in_drop_v=IN_DROP, ck_half_v=a.ck_half, bias=a.bias,
                                                       rows=rows), indent=1))
    print(f"{'condition':15s} | Vck window V (limiters)            | best V / headroom mV | tail uA")
    for r in rows:
        w = (f"{r['lo_v']:.3f}..{r['hi_v']:.3f} ({r['lo_limiter']}, {r['hi_limiter']})" if r["lo_v"] is not None
             else "none")
        print(f"{r['condition']:15s} | {w:34s} | {r['best_ck_v']:.3f} / {r['best_headroom_v']*1e3:4.0f} | {r['tail_id_ua']:.0f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
