"""Which VCO phase can retime each divided TX clock at every corner? (no simulation)

Reads the native_clock records (PLL r4 frontend taps at the TX distribution
input).  For each divided clock (250 MHz = p08, 500 MHz = p24, 1 GHz = p32)
every differential crossing is expressed as a phase of the VCO period T,
relative to the rising crossing of b0 (pb0p - pb0n, buffered VCO phase 0).

A retiming flip-flop clocked by VCO phase phi samples cleanly if every data
transition t satisfies   SETUP <= (phi - t) mod T <= T - HOLD,
i.e. no transition inside [phi - SETUP, phi + HOLD].  The allowed phi range is
intersected over corners and transitions; the eight ring phases are k*T/8
(b0 rising = 0; b0 inverted = T/2), assumed equally spaced (ring symmetry).

    uv run python analog/tx/serializer/tb/clock_replay/retime_phases.py [bc id]
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
RESULTS = ROOT / "results/analog/tx/serializer/clock_replay/retime_phases"
SETUP, HOLD = 130e-12, 40e-12
DIVIDED = {"250": ("p08p", "p08n"), "500": ("p24p", "p24n"), "1g": ("p32p", "p32n")}
GRID = 500                                       # phase grid points per VCO period


def transitions(point, bc):
    run = boundary.point_run(bc, point)
    meta = json.loads((run / "execution.json").read_text())
    w = spice.Waves(run / "waveforms.raw")
    t0 = meta["settle_s"] + 1e-9
    e, pol = crossings(w.t, w["pb0p"] - w["pb0n"])
    ref = e[(pol > 0) & (e > t0)]
    period = float(np.median(np.diff(ref)))
    out = {}
    for clk, (p, n) in DIVIDED.items():
        x, xp = crossings(w.t, w[p] - w[n])
        keep = (x > ref[0]) & (x < ref[-1])
        x, xp = x[keep], xp[keep]
        k = np.searchsorted(ref, x) - 1
        out[clk] = dict(phase=((x - ref[k]) / period).tolist(), polarity=xp.tolist())
    return dict(period_s=period, record=str(run.relative_to(ROOT)), clocks=out)


def allowed(phases, period):
    """Boolean mask over the phase grid: phi samples every transition cleanly."""
    phi = np.arange(GRID) / GRID
    ok = np.ones(GRID, bool)
    for t in phases:
        d = (phi - t) % 1.0 * period
        ok &= (d >= SETUP) & (d <= period - HOLD)
    return ok


def main(bc):
    pts = sorted(boundary.get(bc)["points"])
    data = {p: transitions(p, bc) for p in pts}
    out = dict(bc=bc, setup_s=SETUP, hold_s=HOLD, points=data, clocks={})
    print("transition phase (fraction of the VCO period after b0 rising), min..max per corner:")
    for clk in DIVIDED:
        row = []
        for p in pts:
            ph = np.array(data[p]["clocks"][clk]["phase"])
            row.append(f"{p} {ph.min():.3f}..{ph.max():.3f}")
        print(f"  {clk:4s}", " | ".join(row))
    print(f"allowed sampling phase (setup {SETUP*1e12:.0f} ps, hold {HOLD*1e12:.0f} ps, all corners):")
    for clk in DIVIDED:
        mask = np.ones(GRID, bool)
        for p in pts:
            mask &= allowed(data[p]["clocks"][clk]["phase"], data[p]["period_s"])
        phi = np.arange(GRID) / GRID
        runs, start = [], None
        for i in range(GRID + 1):
            on = mask[i % GRID] if i < GRID else False
            if on and start is None:
                start = i
            if not on and start is not None:
                runs.append((start / GRID, (i - 1) / GRID))
                start = None
        if mask.all():
            runs = [(0.0, 1.0)]
        elif runs and mask[0] and mask[-1] and runs[0][0] == 0.0:   # wrap-around run
            first = runs.pop(0)
            runs[-1] = (runs[-1][0], first[1] + 1.0)
        width = [(b - a) * 500 for a, b in runs]
        cands = []
        for k in range(8):
            f = k / 8
            if mask[int(round(f * GRID)) % GRID]:
                # distance (ps, nominal 500 ps period) to the nearest edge of its allowed run
                for a, b in runs:
                    ff = f if a <= f <= b else f + 1.0
                    if a <= ff <= b:
                        cands.append((k, min(ff - a, b - ff) * 500))
        out["clocks"][clk] = dict(allowed_runs=runs, candidates=cands)
        print(f"  {clk:4s} allowed " + ", ".join(f"[{a:.3f}, {b:.3f}] ({wd:.0f} ps)" for (a, b), wd in zip(runs, width))
              + " | ring phases inside: " + (", ".join(f"k={k} (margin {m:.0f} ps)" for k, m in cands) or "none"))
    RESULTS.mkdir(parents=True, exist_ok=True)
    f = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.json"
    f.write_text(json.dumps(out, indent=1))
    print(f.relative_to(ROOT))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pll_r4_taps@tx_in_r2")
