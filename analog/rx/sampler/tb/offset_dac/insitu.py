"""Trimmed-lane thresholds in the link environment: real CTLE and PI clocks, slow ramp at the CTLE input.

    uv run python analog/rx/sampler/tb/offset_dac/insitu.py --codes "d0=24,d1=36,e0=28,e1=48[;...]"
        [--inject-ua d0p=19.92,...] [--pi-codes 0,4,8] [--cond tt_v1800_t27]

The ramp benches (offset_mc, cal_check) drive the sampler block with ideal tanh clocks at a fixed
common mode; the start-up cosim calibrates with the real CTLE in front and the real PI clocks.  This
bench is the link_pvt one (CTLE EQ3 -> PI -> ac_trim) with the C2 replay replaced by a differential
ramp at the CTLE input (vcm 1.05 V, -30 -> +30 mV over 48 ns): per PI code, each code set (with the
injected trim currents of the cosim) against the zero-trim reference (codes 31 / 32, no injection),
all four lanes on the ramp together in both (lane-to-lane kickback largely cancels in the difference).
Residual = threshold at the code set - reference, referred to the CTLE input.  Repeating at several PI
codes shows whether the offset depends on the clock phase (the PI mixes anchors, so the clock
amplitude / shape moves with the code).
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_s = importlib.util.spec_from_file_location("link_pvt", ROOT / "analog/rx/sampler/tb/link_pvt/pvt.py")
lp = importlib.util.module_from_spec(_s)
_s.loader.exec_module(lp)
LANES = ("d0", "d1", "e0", "e1")
RESULTS = ROOT / "results/analog/rx/sampler/offset_dac"
SLOPE = 0.05 / 40e-9
A = 0.030
T0 = 5e-9
STOP = T0 + 2 * A / SLOPE + 1e-9
SENT = -1e30
VCM = 1.05


def deck(c, pi_code, cases):
    """cases: (label, {lane: code}, {inject: uA}); one row of crossing times per case."""
    ctl = [f"{k} {k[1]}{k[2]} 0 {v}" for k, v in lp.pi.bits(pi_code, c.supply).items()]
    ctl += [f"Vc{n} {n} 0 dc 0" for n in lp.CAL_NODES]
    ctl += [f"Iinj_{l}{s} xdut.x{l}.t{s} 0 dc 0" for l in LANES for s in "pn"]
    dut = " ".join(lp.CAL_NODES + ["serdes_rx_half_rate_samples_ac_trim", "rb=2k"])
    text = spice.render(lp.TEMPLATE, **spice.corner_values(c), EQ0_V=c.supply, EQ1_V=c.supply,
                        CONTROL_SOURCES="\n".join(ctl), DUT=dut, CASES="@CASES@")
    text = text.replace(".save v(op)", ".save v(e0p) v(e0n) v(e1p) v(e1n) v(op)")
    meas = [f"let s_{l} = v({l}p) - v({l}n)" for l in LANES] + [f"meas tran t_{l} when s_{l}=0 rise=1 from=6n" for l in LANES]
    # the link template's control block only sets filetype: one header + row per case, appended
    blocks = ["set wr_vecnames", "set wr_singlescale", "set appendwrite", "setplot const"] + [f"let t_{l} = {SENT}" for l in LANES]
    for label, codes, inj in cases:
        blocks.append(f"* case {label}")
        blocks += [f"alter vc{n} dc={c.supply * ((codes[n[:2]] >> int(n[-1])) & 1)}" for n in lp.CAL_NODES]
        blocks += [f"alter iinj_{l}{s} dc={inj.get(l + s, 0.0) * 1e-6:.6e}" for l in LANES for s in "pn"]
        blocks += [f"tran 2p {STOP:.4e} 0 4p"] + meas + [f"let t_{l} = t_{l}" for l in LANES]
        blocks += ["wrdata xing.tsv " + " ".join(f"t_{l}" for l in LANES), "destroy all", "setplot const"]
    return text.replace("@CASES@", "\n".join(blocks))


def stimuli():
    lines = []
    for leg, s in (("p", 0.5), ("n", -0.5)):
        lines.append(f"Vfar{leg} rx{leg} 0 PWL(0 {VCM - s * A:.6f} {T0:.4e} {VCM - s * A:.6f} {T0 + 2 * A / SLOPE:.4e} {VCM + s * A:.6f})")
    return "\n".join(lines) + "\n"


def read_rows(path):
    rows, names = [], None
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if not p:
            continue
        try:
            vals = [float(x) for x in p]
        except ValueError:
            names = p
            continue
        rows.append({k: (np.nan if v <= SENT / 10 else v) for k, v in zip(names, vals)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", required=True)
    ap.add_argument("--inject-ua", default="")
    ap.add_argument("--pi-codes", default="0,4,8")
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    sets = [{k: int(v) for k, v in (x.split("=") for x in s.split(","))} for s in a.codes.split(";")]
    inject = {k: float(v) for k, v in (x.split("=") for x in a.inject_ua.split(",") if x)}
    pis = [int(x) for x in a.pi_codes.split(",")]
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_insitu")
    camp.mkdir(parents=True)
    (camp / "stimuli.inc").write_text(stimuli())
    cases = [("ref31", {l: 31 for l in LANES}, {}), ("ref32", {l: 32 for l in LANES}, {})]
    cases += [(f"set{i}", s, inject) for i, s in enumerate(sets)]
    jobs = [(deck(c, pc, cases), camp / f"pi{pc:02d}", dict(files={"stimuli.inc": camp / "stimuli.inc"}, timeout_s=600 * len(cases),
                                                             meta=dict(condition=c.tag, pi_code=pc, cases=[x[0] for x in cases])))
            for pc in pis]
    spice.run_many(jobs, workers=a.workers, smoke=False)
    out = dict(condition=c.tag, code_sets=sets, inject_ua=inject, pi_codes={})
    for pc in pis:
        rows = read_rows(camp / f"pi{pc:02d}" / "xing.tsv")
        if len(rows) < len(cases):
            print(f"PI {pc}: incomplete ({len(rows)} of {len(cases)} cases)")
            continue
        ref = {l: (rows[0][f"t_{l}"] + rows[1][f"t_{l}"]) / 2 for l in LANES}
        res = [{l: (r[f"t_{l}"] - ref[l]) * SLOPE * 1e3 for l in LANES} for r in rows[2:]]
        out["pi_codes"][pc] = dict(zero_trim_pair_step_mv={l: (rows[1][f"t_{l}"] - rows[0][f"t_{l}"]) * SLOPE * 1e3 for l in LANES},
                                   residual_mv=res, reference_crossing_s=ref)
        for i, r in enumerate(res):
            print(f"PI {pc:2d} set {i} ({','.join(f'{l}={sets[i][l]}' for l in LANES)}): " + "  ".join(f"{l} {r[l]:+.2f}" for l in LANES) + " mV")
    (camp / "summary.json").write_text(json.dumps(out, indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
