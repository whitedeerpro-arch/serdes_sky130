"""Screen TX clock-distribution buffer chains on recorded native taps (seconds per point).

One divided clock (500 MHz or 1 GHz) at one corner: the recorded PLL r4 tap
(clock_replay.cut_period, periodic PWL) drives

    Xa (input stage, r2: wn 20 / wt 12 / 400 ohm, plus trim C) -> extra stages -> Xb

and Xb drives CLOAD per side, a stand-in for the serializer clock port (the
real port is checked in the full replay bench).  Reports differential pp and
crossing slope at every stage output, tap -> output delay, and the supply
current of the chain.  Tail current of a stage is 0.85 mA * wt / 20 (mirror of
the 20 um bias diode), so its largest differential swing is 2 * I * R.

    uv run python analog/tx/serializer/tb/clock_replay/stage_screen.py [bc id]
"""
import importlib.util
import itertools
import sys
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/tx/serializer/clock_replay/stage_screen"
CLOAD = 60e-15
_spec = importlib.util.spec_from_file_location("clock_replay", HERE / "run.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)

R2 = {"500": dict(a=(20, 12, 400), trim=500, extra=(), b=(40, 32, 200)),
      "1g": dict(a=(20, 12, 400), trim=160, extra=(), b=(24, 16, 400))}


def deck(c, clk, chain, taps):
    p, n, _, _ = replay.CLOCKS[clk]
    shift = {k: 0.0 for k in replay.CLOCKS}
    lines, _ = replay.replay_sources(taps, shift)
    src = [l.replace(replay.CLOCKS[clk][2], f"Vinp inp").replace(replay.CLOCKS[clk][3], f"Vinn inn")
           for l in lines if l.startswith((replay.CLOCKS[clk][2].split()[0] + " ", replay.CLOCKS[clk][3].split()[0] + " "))]
    stages = [chain["a"], *chain["extra"], chain["b"]]
    body, prev = [], ("inp", "inn")
    for i, (wn, wt, r) in enumerate(stages):
        out = (f"o{i}p", f"o{i}n")
        body.append(f"X{i} {prev[0]} {prev[1]} {out[0]} {out[1]} vbias vdd 0 serdes_cml_buffer wn={wn} wt={wt} rload={r}")
        if i == 0:
            body.append(f"Ct0p o0p 0 {2 + chain['trim']}f\nCt0n o0n 0 {2 + chain['trim']}f")
        prev = out
    body.append(f"Clp {prev[0]} 0 {CLOAD}\nCln {prev[1]} 0 {CLOAD}")
    vecs = " ".join(f"v(o{i}p) v(o{i}n)" for i in range(len(stages)))
    return f"""stage screen {clk}
.lib "{spice.corner_values(c)['MODEL_LIBRARY']}" {spice.corner_values(c)['CORNER']}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/common/cml_buffer/spice/cml_delay_resistive.spice"
.include "{ROOT}/analog/common/cml_buffer/spice/cml_buffer.spice"
.param supply={c.supply}
Vdd vdd 0 {{supply}}
Vb vb 0 {{supply}}
Iref vb vbias 0.85m
Xbias vbias vbias 0 0 serdes_nfet w=20 l=0.5 nf=4
{chr(10).join(src)}
{chr(10).join(body)}
.temp {c.temp}
.options reltol=1e-4 abstol=1p vntol=1u
.control
set num_threads=1
tran 2p 16n 0 2p
set filetype=binary
write waveforms.raw v(inp) v(inn) {vecs} i(Vdd)
quit
.endc
.end
"""


def measure(w, nstages, period):
    sel = w.t > 8e-9
    res = []
    for i in range(-1, nstages):
        y = (w["inp"] - w["inn"]) if i < 0 else (w[f"o{i}p"] - w[f"o{i}n"])
        e, pol = crossings(w.t, y)
        e = e[e > 8e-9]
        sl = np.mean([abs(np.interp(x + 2e-12, w.t, y) - np.interp(x - 2e-12, w.t, y)) / 4e-12 for x in e[:8]])
        cen = replay.centroid(w.t, y, period, 8e-9, 16e-9)
        res.append(dict(pp_v=float(np.ptp(y[sel])), slope_v_per_s=float(sl), centroid_s=cen))
    for r in res[1:]:
        r["delay_s"] = float((r["centroid_s"] - res[0]["centroid_s"]) % period)
    return res, float(-np.mean(w["i(vdd)"][sel]))


def screen(points, clocks, chains, bc):
    """Screening only: the candidate chains change the input stage, so the load check
    is not applied; the BC id is recorded in summary.json."""
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, keys = [], []
    for pt, clk, (name, ch) in itertools.product(points, clocks, chains.items()):
        if "only" in ch and clk not in ch["only"]:
            continue
        ch = dict(R2[clk], **{k: v for k, v in ch.items() if k != "only"})
        taps, _ = replay.point_taps(pt, bc)
        d = camp / f"{pt}_{clk}_{name}"
        jobs.append((deck(replay.condition(bc, pt), clk, ch, taps), d, {}))
        keys.append((pt, clk, name, ch))
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for (pt, clk, name, ch), (_, d, _) in zip(keys, jobs):
        st, idd = measure(spice.Waves(d / "waveforms.raw"), 2 + len(ch["extra"]), replay.PERIOD[clk])
        rows.append(dict(point=pt, clock=clk, chain=name, spec=ch, stages=st, supply_current_a=idd, bc=bc))
        print(f"{pt:8s} {clk:3s} {name:14s} " + " -> ".join(f"{s['pp_v']*1e3:4.0f}" for s in st)
              + f" mVpp | out slope {st[-1]['slope_v_per_s']*1e-9:.2f} mV/ps | delay {st[-1]['delay_s']*1e12:6.1f} ps"
              f" | I {idd*1e3:.2f} mA", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=2, default=float))
    print(camp.relative_to(ROOT))
    return rows


CHAINS = {
    "r2": {},
    "r2_trim0": dict(trim=0),
    "e24_16_400": dict(trim=0, extra=((24, 16, 400),)),
    "e40_16_600": dict(trim=0, extra=((40, 16, 600),)),
    "e40_24_400": dict(trim=0, extra=((40, 24, 400),)),
    "e2x40_16_600": dict(trim=0, extra=((40, 16, 600), (40, 16, 600))),
    "a600_e40_16_600": dict(a=(20, 12, 600), trim=0, extra=((40, 16, 600),)),
}

if __name__ == "__main__":
    screen(["tt", "ss_hot", "fs_hot"], ["500", "1g"], CHAINS, sys.argv[1] if len(sys.argv) > 1 else "pll_r4_taps@tx_in_r2")
