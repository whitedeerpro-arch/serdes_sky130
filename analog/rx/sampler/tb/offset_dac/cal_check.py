"""Thresholds of trimmed lanes at given codes, one lane at a time, with optional injected trim currents.

    uv run python analog/rx/sampler/tb/offset_dac/cal_check.py --codes d0=16,d1=40,e0=30,e1=48
        [--inject-ua d0p=19.92,d1n=13.944,e0p=5.976,e1n=29.88] [--cond tt_v1800_t27]

Checks a calibration result (e.g. the codes the SAR reached in the start-up cosim,
verification/mixed_signal, receiver_cal.cir.in) on the ramp bench of tb/offset_mc without mismatch.
The four samplers share the input buffer and kick back into it, so a lane's threshold depends on
what the other three decide (several mV between "all others 0" and "all others 1").  For each lane:
the threshold at its code with the other three held at code 63 (they decide 0 near zero input, T0)
and at code 0 (they decide 1, T1); with random data the others decide 1 half of the time, so the
operating threshold is (T0 + T1) / 2.  Reference (zero trim, same two environments, no injection):
mean of codes 31 and 32.  The injected sink currents of the cosim are applied, so residual 0 means
the lane is calibrated for the data environment.
"""
import argparse
import importlib.util
import json
import time
from pathlib import Path

from serdes_flow import mc, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_s = importlib.util.spec_from_file_location("offset_mc", ROOT / "analog/rx/sampler/tb/offset_mc/run.py")
om = importlib.util.module_from_spec(_s)
_s.loader.exec_module(om)
LANES = om.LANES
RESULTS = ROOT / "results/analog/rx/sampler/offset_dac"
RAMP = 30.0


def threshold(c, lane, code, inject, d, hold_code=63):
    """Crossing time of `lane`; a finished run in `d` (same lane, code, environment) is reused."""
    if (d / mc.MC_FILE).exists():
        return mc.read(d)[0][f"t_{lane}"]
    hold = tuple(l for l in LANES if l != lane)
    net = om.netlist(c, c.process, "ac_trim", RAMP, code, hold, hold_code)
    net += "\n" + "\n".join(f"Iinj_{k} xdut.x{k[:2]}.t{k[2]} 0 dc {v}u" for k, v in inject.items())
    spice.run(mc.deck(net, 1, analysis=om.analysis(RAMP), lets=om.LETS), d, timeout_s=900)
    r = mc.read(d)[0]
    return r[f"t_{lane}"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", required=True, help="d0=..,d1=..,e0=..,e1=..[;second set]")
    ap.add_argument("--inject-ua", default="")
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--reuse", help="campaign directory: reuse its finished runs")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    inject = {k: float(v) for k, v in (x.split("=") for x in a.inject_ua.split(",") if x)}
    ap_reuse = a.reuse
    camp = (ROOT / ap_reuse) if ap_reuse else RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_calcheck")
    sets = [dict(x.split("=") for x in s.split(",")) for s in a.codes.split(";")]
    sets = [{k: int(v) for k, v in s.items()} for s in sets]
    out = dict(condition=c.tag, code_sets=sets, inject_ua=inject, lanes={})
    mv = lambda x: x * om.SLOPE * 1e3
    for lane in LANES:
        ref = {h: sum(threshold(c, lane, k, {}, camp / f"{lane}_ref{k}_n{h}", h) for k in (31, 32)) / 2 for h in (63, 0)}
        out["lanes"][lane] = dict(kickback_mv=mv(ref[0] - ref[63]), sets=[])
        print(f"  {lane}: zero-trim threshold with the others deciding 1 minus deciding 0: {mv(ref[0] - ref[63]):+.2f} mV", flush=True)
        for s in sets:
            t = {h: threshold(c, lane, s[lane], inject, camp / f"{lane}_code{s[lane]}_n{h}", h) for h in (63, 0)}
            r0, r1 = mv(t[63] - ref[63]), mv(t[0] - ref[0])
            out["lanes"][lane]["sets"].append(dict(code=s[lane], residual_others0_mv=r0, residual_others1_mv=r1, residual_mean_mv=(r0 + r1) / 2))
            print(f"     code {s[lane]:2d}: residual {r0:+.2f} (others 0) / {r1:+.2f} (others 1) -> data environment {(r0 + r1) / 2:+.2f} mV", flush=True)
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
