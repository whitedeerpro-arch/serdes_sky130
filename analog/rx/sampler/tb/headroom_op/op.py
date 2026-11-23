"""RX sampler-path bias headroom over PVT: operating point of the sampler link bench.

    uv run python analog/rx/sampler/tb/headroom_op/op.py [all | stress | tags...] [--code 12]
        [--dut stock|ac] [--param KEY=VALUE ...] [--resume C] [--analyse-only]

Renders the sampler link bench (sampler/tb/link_pvt: C2 replay -> CTLE -> PI -> half-rate
samplers) without its .save list and replaces the transient by an operating point.  One deck per
process corner; supply and temperature change in the control block.  At t = 0 the anchors and
the replayed input sit at their initial values, so the latches are in one static state; the
numbers are the bias point, not the swing.

Per condition: headroom Vds - Vdsat of the current-source devices on the sampler path (D0 master
and slave latch tails, sampler input buffer tail, clock level-shift sink, PI restore buffer
tail), their currents, and the common modes that set the stack (shifted clock, sampler input,
PI output).  Gate (proposed, RX plan C1): every tail headroom >= 50 mV in all 45 conditions.
`--param` overrides a DUT parameter (wtail, wsf, wsink, ...) for trials.  `--dut ac` (low-overdrive
tails, AC-coupled clocks): the shift sink is replaced by the clock-buffer tail, and the local
low-overdrive reference diode is reported; ck_cm is then the gate bias v(vck).
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
LINK = ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py"
RESULTS = ROOT / "results/analog/rx/sampler/headroom_op"
GATE_V = 0.05
NF, NF_LVT = "msky130_fd_pr__nfet_01v8", "msky130_fd_pr__nfet_01v8_lvt"

# name -> (node of the device drain, vdsat/id device path); tails share source = vss
_COMMON = {
    "latch_m": ("xdut.xd0.xm.tail", f"m.xdut.xd0.xm.xtail.xmos.{NF}"),
    "latch_s": ("xdut.xd0.xs.tail", f"m.xdut.xd0.xs.xtail.xmos.{NF}"),
    "inbuf": ("xdut.xinput.xgain.tail", f"m.xdut.xinput.xgain.xtail.{NF}"),
}
_PI = {"pi_restore": ("xpi.xmix0.xrestore.xgain.tail", f"m.xpi.xmix0.xrestore.xgain.xtail.{NF}")}
DEVICES_BY_DUT = {
    "stock": {**_COMMON, "shift_sink": ("xdut.cdp", f"m.xdut.xcd.xsp.xmos.{NF}"), **_PI},
    "ac": {**_COMMON, "ck_buf": ("xdut.xcd.xbuf.tail", f"m.xdut.xcd.xbuf.xtail.{NF}"),
           "local_ref": ("xdut.vbias_logic", f"m.xdut.xlb.xref.xmos.{NF}"), **_PI},
}
DEVICES = DEVICES_BY_DUT["stock"]
LEVELS = {
    "ck_cm": "(v(xdut.cdp)+v(xdut.cdn))/2",
    "in_cm": "(v(xdut.bp)+v(xdut.bn))/2",
    "pi_cm": "(v(dp)+v(dn))/2",
    "track": "v(xdut.xd0.xm.track)",
    "clkpair_vgs": f"(v(xdut.cdp)+v(xdut.cdn))/2-v(xdut.xd0.xm.tail)",
}


def _load(name, path):
    import importlib.util
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


sp = _load("sampler_pvt", LINK)


def case_name(c):
    return c.tag


def deck(conds, code, params, variant="stock"):
    c0 = conds[0]
    ctl = "\n".join(f"{k} {k[1]}{k[2]} 0 {v}" for k, v in sp.pi.bits(code, c0.supply).items())
    text = spice.render(sp.TEMPLATE, **spice.corner_values(c0), EQ0_V=c0.supply * (sp.EQ & 1),
                        EQ1_V=c0.supply * (sp.EQ >> 1), CONTROL_SOURCES=ctl, DUT=sp.dut(variant, params),
                        CASES="@CASES@")
    text = "\n".join(l for l in text.splitlines() if not l.startswith(".save"))
    text = text.replace("set filetype=binary", "set wr_singlescale\nset wr_vecnames")
    lets = []
    for k, (node, dev) in DEVICES.items():
        lets += [f"let {k}_vds=v({node})", f"let {k}_vdsat=@{dev}[vdsat]", f"let {k}_id=@{dev}[id]"]
    lets += [f"let {k}={e}" for k, e in LEVELS.items()]
    names = [f"{k}_{q}" for k in DEVICES for q in ("vds", "vdsat", "id")] + list(LEVELS)
    blocks = []
    for c in conds:
        blocks.append("\n".join([f"* case {case_name(c)}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}",
                                 f"alter Vref dc={c.supply}", f"alter Veq0 dc={c.supply * (sp.EQ & 1)}",
                                 f"alter Veq1 dc={c.supply * (sp.EQ >> 1)}"]
                                + [f"alter {k} dc={v}" for k, v in sp.pi.bits(code, c.supply).items()]
                                + ["op"] + lets + [f"wrdata {case_name(c)}.tsv " + " ".join(names), "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def read_case(d, c):
    lines = (Path(d) / f"{case_name(c)}.tsv").read_text().split("\n")
    names, vals = lines[0].split(), [float(x) for x in lines[1].split()]
    return dict(zip(names, vals))


def analyse(v, c):
    r = dict(condition=c.tag)
    for k in DEVICES:
        r[k] = dict(vds=v[f"{k}_vds"], vdsat=v[f"{k}_vdsat"], headroom=v[f"{k}_vds"] - v[f"{k}_vdsat"], id=v[f"{k}_id"])
    r.update({k: v[k] for k in LEVELS})
    r["worst"] = min(DEVICES, key=lambda k: r[k]["headroom"])
    r["ok"] = all(r[k]["headroom"] >= GATE_V for k in DEVICES)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["all"])
    ap.add_argument("--code", type=int, default=12)
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--dut", choices=sorted(DEVICES_BY_DUT), default="stock")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    params = dict(p.split("=", 1) for p in a.param)
    global DEVICES
    DEVICES = DEVICES_BY_DUT[a.dut]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    stim, _ = sp.replay.stimuli("rx_c2_far_nominal@ctle_rc")
    (camp / "stimuli.inc").write_text(stim)
    by_proc = {}
    for c in conds:
        by_proc.setdefault(c.process, []).append(c)
    jobs = [(deck(cs, a.code, params, a.dut), camp / proc,
             dict(files={"stimuli.inc": camp / "stimuli.inc"},
                  meta=dict(process=proc, code=a.code, dut=sp.dut(a.dut, params), conditions=[c.tag for c in cs])))
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
    rows = [analyse(read_case(camp / c.process, c), c) for c in conds]
    (camp / "summary.json").write_text(json.dumps(dict(code=a.code, dut=sp.dut(a.dut, params), params=params, gate_v=GATE_V, rows=rows), indent=1))
    print(f"{'condition':15s} | headroom mV: " + " ".join(f"{k:>10s}" for k in DEVICES) + " | latch Id uA | ck_cm in_cm pi_cm V")
    for r in rows:
        print(f"{r['condition']:15s} | {'':13s}" + " ".join(f"{r[k]['headroom']*1e3:10.0f}" for k in DEVICES)
              + f" | {r['latch_m']['id']*1e6:6.0f} | {r['ck_cm']:.3f} {r['in_cm']:.3f} {r['pi_cm']:.3f}"
              + ("" if r["ok"] else f"  FAIL ({r['worst']})"))
    h = np.array([[r[k]["headroom"] for k in DEVICES] for r in rows])
    print("min headroom mV per device: " + ", ".join(f"{k} {x*1e3:.0f}" for k, x in zip(DEVICES, h.min(0))))
    print(f"{sum(r['ok'] for r in rows)}/{len(rows)} conditions pass the {GATE_V*1e3:.0f} mV gate")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
