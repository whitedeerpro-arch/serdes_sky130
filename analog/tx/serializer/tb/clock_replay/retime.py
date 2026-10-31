"""Retimed TX clock distribution (v2) on the recorded native clocks.

    uv run python analog/tx/serializer/tb/clock_replay/retime.py probe --bc ID [points] [--cfg JSON]

probe: 30 ns at every recorded corner, all four taps at their native relative
       positions (one common shift, as the hardware would see them).  Reports
       per retimer the worst setup / hold of its D transitions against the
       falling edge of its internal clock (follower outputs), the clock
       positions at the serializer inputs relative to 250 MHz compared with the
       r2 calibration run at the same corner (modulo one VCO cycle: whole
       cycles are start states), and the distribution supply power.
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
_spec = importlib.util.spec_from_file_location("clock_replay", HERE / "run.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)
_spec2 = importlib.util.spec_from_file_location("dist_v2", HERE / "variants" / "dist_v2.py")
dist_v2 = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(dist_v2)
RESULTS = ROOT / "results/analog/tx/serializer/clock_replay/retime"
WINDOW = (14e-9, 30e-9)


def deck_with(c, stop, dist, extra):
    d = replay.deck(c, stop, dist, (0, 0, 0, 0))
    vecs = " ".join(extra)
    assert "write waveforms.raw " in d and "\n.control" in d
    # The template saves an explicit list; internal probe nodes must be added to it.
    d = d.replace("\n.control", f"\n.save {vecs}\n.control", 1)
    return d.replace("write waveforms.raw ", f"write waveforms.raw {vecs} ", 1)


def setup_hold(w, clk):
    d = w[f"v(xclocks.d{clk}p)"] - w[f"v(xclocks.d{clk}n)"]
    k = w[f"v(xclocks.xr{clk}.ckp)"] - w[f"v(xclocks.xr{clk}.ckn)"]
    td, _ = crossings(w.t, d)
    tk, kp = crossings(w.t, k)
    fall = tk[kp < 0]
    td = td[(td > WINDOW[0] + 1e-9) & (td < WINDOW[1] - 1e-9)]
    setup = [fall[np.searchsorted(fall, x)] - x for x in td]
    hold = [x - fall[np.searchsorted(fall, x) - 1] for x in td]
    return min(setup), min(hold), len(td)


def positions(w, tag):
    """Clock positions relative to 250 MHz at the serializer inputs minus the r2 calibration
    run's (modulo one VCO cycle); NaN where the calibration grid has no run."""
    got = replay.serializer_centroids(w, *WINDOW)
    want = replay.target_centroids(tag)
    if want is None:
        return {k: float("nan") for k in ("500", "1g", "2g")}
    return {k: replay.wrap((got[k] - got["250"]) - (want[k] - want["250"]), replay.VCO_CYCLE) / 250e-12
            for k in ("500", "1g", "2g")}


def probe(cfg_over, bc, names=None, label="probe", allow_load_mismatch=False):
    netlist = dist_v2.netlist(cfg_over)
    load_ok = boundary.check_load(bc, boundary.input_stage_signature(netlist, replay.DIST_NAME, replay.DIST_INPUTS),
                                  allow_mismatch=allow_load_mismatch)
    camp = RESULTS / f"{label}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True)
    dist = camp / "dist_v2.spice"
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
        jobs.append((deck_with(replay.condition(bc, n), "30n", dist, dist_v2.probe_vectors()), d / "run",
                     dict(files={"stimuli.inc": d / "stimuli.inc"},
                          meta=dict(point=n, cfg=str(cfg_over), bc=bc,
                                    load_check="match" if load_ok else "MISMATCH (allowed)"))))
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for n in names:
        w = spice.Waves(camp / n / "run/waveforms.raw")
        sh = {clk: setup_hold(w, clk) for clk in ("250", "500", "1g")}
        pos = positions(w, replay.condition(bc, n).tag)
        sel = (w.t > WINDOW[0]) & (w.t < WINDOW[1])
        p = float(np.mean(w["pclock"][sel]))
        amp = {k: float(np.ptp(w[v][sel])) for k, v in replay.SER_VEC.items()}
        rows.append(dict(point=n, setup_hold_s=sh, rel_position_error_ui=pos, pclock_w=p, clock_pp_v=amp))
        print(f"{n:8s} " + "  ".join(f"{clk}: s{s*1e12:4.0f}/h{h*1e12:4.0f} ps" for clk, (s, h, _) in sh.items())
              + " | pos vs r2 (rel 250) " + "/".join(f"{pos[k]:+.2f}" for k in pos)
              + f" UI | clk pp " + "/".join(f"{amp[k]*1e3:.0f}" for k in amp) + f" mV | Pclk {p*1e3:.1f} mW", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(cfg=str(cfg_over), bc=bc, rows=rows), indent=1, default=float))
    print(camp.relative_to(ROOT))
    return rows


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("probe",))
    ap.add_argument("points", nargs="*")
    ap.add_argument("--bc", required=True)
    ap.add_argument("--cfg", default="{}", help="JSON overrides of variants/dist_v2.DEFAULT")
    ap.add_argument("--label", default="probe")
    ap.add_argument("--allow-load-mismatch", action="store_true")
    a = ap.parse_args()
    over = json.loads(a.cfg)
    if "ck" in over:                             # JSON lists -> tuples
        over["ck"] = {k: tuple(v) for k, v in over["ck"].items()}
    probe(over, a.bc, a.points or None, a.label, a.allow_load_mismatch)
