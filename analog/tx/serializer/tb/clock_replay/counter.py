"""Counter-based TX clock distribution (v3, structure S4) on the recorded native clocks.

    uv run python analog/tx/serializer/tb/clock_replay/counter.py probe --bc ID [points] [--cfg v3|JSON] [--label L]

probe: 30 ns at every recorded corner (the 2 GHz tap drives everything).  Reports
  * function: the (q2 q1 q0) state read 100 ps after each clock fall counts up by
    one every cycle (binary relation intact);
  * clk->q of each bit after the falling crossing of the counter's internal clock;
  * worst setup / hold of the next-state inputs d1, d2 at the masters;
  * select-clock positions at the serializer inputs relative to 250M, minus the
    r2 ideal placement 0.162 / 0.320 / 0.982 UI (folded to +-0.5 UI);
  * clock pp at the serializer and the distribution supply power.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import boundary, spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent


def _load(name, path):
    s = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


replay = _load("clock_replay", HERE / "run.py")
retime = _load("retime", HERE / "retime.py")
dist_v3 = _load("dist_v3", HERE / "variants" / "dist_v3.py")
RESULTS = ROOT / "results/analog/tx/serializer/clock_replay/counter"
WINDOW = (14e-9, 30e-9)
UI = 250e-12
TARGET = {"500": 0.162, "1g": 0.320, "2g": 0.982}


def diff(w, a):
    return w[f"v(xclocks.{a}p)"] - w[f"v(xclocks.{a}n)"]


def check(w):
    t = w.t
    ck, pk = crossings(t, diff(w, "xcnt.ck"))
    falls = ck[(pk < 0) & (ck > WINDOW[0]) & (ck < WINDOW[1] - 0.2e-9)]
    bits = [diff(w, f"q{i}") for i in range(3)]
    state = [sum((np.interp(f + 100e-12, t, b) > 0) << i for i, b in enumerate(bits)) for f in falls]
    steps = np.diff(state) % 8
    # steady counting from the last irregular step on (a noise-free start-up can linger)
    bad = [i for i, s in enumerate(steps) if s not in (1,)]
    since = falls[bad[-1] + 1] if bad else falls[0]
    counting = bool(len(steps) and (not bad or bad[-1] < len(steps) - 16))
    allf = ck[pk < 0]
    cq = {}
    for i, b in enumerate(bits):
        e, _ = crossings(t, b)
        e = e[(e > WINDOW[0]) & (e < WINDOW[1])]
        cq[f"q{i}"] = float(np.median([x - allf[np.searchsorted(allf, x) - 1] for x in e]))
    su, ho = [], []
    for d in ("d1", "d2"):
        e, _ = crossings(t, diff(w, f"xcnt.{d}"))
        e = e[(e > WINDOW[0]) & (e < WINDOW[1] - 0.6e-9)]
        su += [allf[np.searchsorted(allf, x)] - x for x in e]
        ho += [x - allf[np.searchsorted(allf, x) - 1] for x in e]
    return dict(counting=counting, counting_since_s=float(since), clk_to_q_s=cq,
                setup_min_s=float(min(su)), hold_min_s=float(min(ho)))


def positions(w):
    got = replay.serializer_centroids(w, *WINDOW)
    return {k: float(replay.wrap((got[k] - got["250"]) / UI - TARGET[k], 1.0)) for k in TARGET}


def probe(cfg, bc, names=None, label="probe"):
    netlist = dist_v3.netlist(cfg)
    boundary.check_load(bc, boundary.input_stage_signature(netlist, replay.DIST_NAME, replay.DIST_INPUTS))
    camp = RESULTS / f"{label}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True)
    dist = camp / "dist_v3.spice"
    dist.write_text(netlist)
    ideal = replay.ideal_centroids()
    names = names or sorted(boundary.get(bc)["points"])
    jobs = []
    for n in names:
        taps, _ = replay.point_taps(n, bc)
        text, _ = replay.stimuli(taps, replay.source_shifts(taps, "native", ideal))
        d = camp / n
        d.mkdir()
        (d / "stimuli.inc").write_text(text)
        jobs.append((retime.deck_with(replay.condition(bc, n), "30n", dist, dist_v3.probe_vectors()), d / "run",
                     dict(files={"stimuli.inc": d / "stimuli.inc"}, meta=dict(point=n, cfg=str(cfg), bc=bc))))
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for n in names:
        w = spice.Waves(camp / n / "run/waveforms.raw")
        c = check(w)
        pos = positions(w)
        sel = (w.t > WINDOW[0]) & (w.t < WINDOW[1])
        amp = {k: float(np.ptp(w[v][sel])) for k, v in replay.SER_VEC.items()}
        p = float(np.mean(w["pclock"][sel]))
        rows.append(dict(point=n, **c, position_error_ui=pos, clock_pp_v=amp, pclock_w=p))
        print(f"{n:14s} {'count from ' + format(c['counting_since_s']*1e9, '.1f') + ' ns' if c['counting'] else 'NOT COUNTING'} | clk->q " +
              "/".join(f"{c['clk_to_q_s'][k]*1e12:.0f}" for k in ("q0", "q1", "q2")) +
              f" ps | d setup {c['setup_min_s']*1e12:4.0f} hold {c['hold_min_s']*1e12:4.0f} ps"
              f" | pos err 500/1g/2g " + "/".join(f"{pos[k]:+.2f}" for k in TARGET) +
              " UI | pp " + "/".join(f"{amp[k]*1e3:.0f}" for k in replay.SER_VEC) + f" mV | Pclk {p*1e3:.1f} mW", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(cfg=str(cfg), bc=bc, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("probe",))
    ap.add_argument("points", nargs="*")
    ap.add_argument("--bc", required=True)
    ap.add_argument("--cfg", default="v3", help="preset in variants/dist_v3.PRESETS or JSON overrides of DEFAULT")
    ap.add_argument("--label", default="probe")
    a = ap.parse_args()
    probe(dist_v3.resolve(a.cfg), a.bc, a.points or None, a.label)
