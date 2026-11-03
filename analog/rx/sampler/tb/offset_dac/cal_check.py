"""Thresholds of trimmed lanes at given codes, one lane at a time, with optional injected trim currents.

    uv run python analog/rx/sampler/tb/offset_dac/cal_check.py --codes d0=16,d1=40,e0=30,e1=48
        [--inject-ua d0p=19.92,d1n=13.944,e0p=5.976,e1n=29.88] [--cond tt_v1800_t27]
        [--falling] [--reuse <earlier campaign>] [--workers 3]

Checks a calibration result (e.g. the codes the SAR reached in the start-up cosim,
verification/mixed_signal, receiver_cal.cir.in) on the ramp bench of tb/offset_mc without mismatch.
The four samplers share the input buffer and kick back into it, so a lane's threshold depends on
what the other three decide (several mV between "all others 0" and "all others 1").  For each lane:
the threshold at its code with the other three held at code 63 (they decide 0 near zero input, T0)
and at code 0 (they decide 1, T1); with random data the others decide 1 half of the time, so the
operating threshold is (T0 + T1) / 2.  Reference (zero trim, same two environments, no injection):
mean of codes 31 and 32.  The injected sink currents of the cosim are applied, so residual 0 means
the lane is calibrated for the data environment.

The lane also remembers its own decisions (hysteresis, see idle_sweep.py): the rising ramp crosses
at the threshold after a run of 0s.  --falling adds the falling ramp (threshold after a run of 1s);
with random data the lane's previous decision is 1 half of the time, so the data-mode residual is
the mean of the two, and rising minus falling is the hysteresis width.
"""
import argparse
import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor

from serdes_flow import mc, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_s = importlib.util.spec_from_file_location("offset_mc", ROOT / "analog/rx/sampler/tb/offset_mc/run.py")
om = importlib.util.module_from_spec(_s)
_s.loader.exec_module(om)
LANES = om.LANES
RESULTS = ROOT / "results/analog/rx/sampler/offset_dac"
RAMP = 30.0


def threshold(c, lane, code, inject, d, hold_code=63, reuse=(), falling=False):
    """Input (V) at which `lane` flips; a finished run in `d` or in any `reuse` / d.name (same
    lane, code, environment, injection, ramp direction) is reused."""
    a = RAMP * 1e-3
    volts = lambda t: (a - om.SLOPE * (t - om.RAMP_T0)) if falling else (-a + om.SLOPE * (t - om.RAMP_T0))
    for e in (d, *(r / d.name for r in reuse)):
        if (e / mc.MC_FILE).exists():
            return volts(mc.read(e)[0][f"t_{lane}"])
    hold = tuple(l for l in LANES if l != lane)
    net = om.netlist(c, c.process, "ac_trim", RAMP, code, hold, hold_code, falling=falling)
    net += "\n" + "\n".join(f"Iinj_{k} xdut.x{k[:2]}.t{k[2]} 0 dc {v}u" for k, v in inject.items())
    spice.run(mc.deck(net, 1, analysis=om.analysis(RAMP, falling=falling), lets=om.LETS), d, timeout_s=900)
    return volts(mc.read(d)[0][f"t_{lane}"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", required=True, help="d0=..,d1=..,e0=..,e1=..[;second set]")
    ap.add_argument("--inject-ua", default="")
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--falling", action="store_true", help="also the falling ramp (hysteresis, data-mode residual)")
    ap.add_argument("--reuse", default="", help="earlier campaign directories, comma-separated (same condition and "
                    "injection): reuse their finished runs")
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    inject = {k: float(v) for k, v in (x.split("=") for x in a.inject_ua.split(",") if x)}
    reuse = tuple(ROOT / r for r in a.reuse.split(",") if r)
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "_calcheck")
    camp.mkdir(parents=True)
    sets = [dict(x.split("=") for x in s.split(",")) for s in a.codes.split(";")]
    sets = [{k: int(v) for k, v in s.items()} for s in sets]
    dirs = (False, True) if a.falling else (False,)
    # every (lane, what, environment, direction) threshold, run in parallel
    keys = []
    for lane in LANES:
        for f in dirs:
            for h in (63, 0):
                keys += [(lane, f"ref{k}", k, {}, h, f) for k in (31, 32)]
                keys += [(lane, f"code{s[lane]}", s[lane], inject, h, f) for s in sets]
    keys = list({(l, w, h, f): (l, w, k, i, h, f) for l, w, k, i, h, f in keys}.values())
    name = lambda l, w, h, f: f"{l}_{w}_n{h}" + ("_fall" if f else "")
    with ThreadPoolExecutor(a.workers) as ex:
        got = dict(zip([(l, w, h, f) for l, w, k, i, h, f in keys],
                       ex.map(lambda x: threshold(c, x[0], x[2], x[3], camp / name(x[0], x[1], x[4], x[5]), x[4], reuse, x[5]), keys)))
    out = dict(condition=c.tag, code_sets=sets, inject_ua=inject, reuse=[str(r.relative_to(ROOT)) for r in reuse], falling=a.falling, lanes={})
    mv = lambda x: x * 1e3
    for lane in LANES:
        ref = {(h, f): (got[(lane, "ref31", h, f)] + got[(lane, "ref32", h, f)]) / 2 for h in (63, 0) for f in dirs}
        lo = out["lanes"][lane] = dict(kickback_mv=mv(ref[(0, False)] - ref[(63, False)]), sets=[])
        print(f"  {lane}: zero-trim threshold with the others deciding 1 minus deciding 0: {lo['kickback_mv']:+.2f} mV", flush=True)
        if a.falling:
            lo["hysteresis_ref_mv"] = mv(sum(ref[(h, False)] - ref[(h, True)] for h in (63, 0)) / 2)
            print(f"     zero trim: rising minus falling threshold {lo['hysteresis_ref_mv']:+.2f} mV", flush=True)
        for s in sets:
            e = dict(code=s[lane])
            for f in dirs:
                r0 = mv(got[(lane, f"code{s[lane]}", 63, f)] - ref[(63, f)])
                r1 = mv(got[(lane, f"code{s[lane]}", 0, f)] - ref[(0, f)])
                tag = "falling" if f else "rising"
                e[tag] = dict(residual_others0_mv=r0, residual_others1_mv=r1, residual_mean_mv=(r0 + r1) / 2)
                print(f"     code {s[lane]:2d} {tag:7s}: residual {r0:+.2f} (others 0) / {r1:+.2f} (others 1) -> {(r0 + r1) / 2:+.2f} mV", flush=True)
            e.update(e["rising"])          # residual_*: rising ramp (as before --falling existed)
            if a.falling:
                e["residual_data_mv"] = (e["rising"]["residual_mean_mv"] + e["falling"]["residual_mean_mv"]) / 2
                e["hysteresis_mv"] = mv(sum(got[(lane, f"code{s[lane]}", h, False)] - got[(lane, f"code{s[lane]}", h, True)] for h in (63, 0)) / 2)
                print(f"     code {s[lane]:2d}: data mode (mean of both ramps) {e['residual_data_mv']:+.2f} mV, hysteresis {e['hysteresis_mv']:+.2f} mV", flush=True)
            lo["sets"].append(e)
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
