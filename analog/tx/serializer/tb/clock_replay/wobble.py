"""Clock wobble bands at the serializer inputs, per process corner (no simulation).

A manufactured chip has one process corner; supply and temperature move.  So
for each process the four TX clocks are overlaid over the V/T points of a
native-position replay campaign (clock_replay native mode, or retime probe),
and the interval each edge sweeps is filled.

Positions are taken relative to a 250 MHz falling edge at the serializer input
(the word clock the data is aligned to).  500 MHz and 1 GHz records can sit in
different divider start states (whole VCO cycles, 2 UI apart); that part is
removed against the group's reference point before the band is measured, since
the start-state detector and remap handle it.

    uv run python analog/tx/serializer/tb/clock_replay/wobble.py <campaign dir> [...]
"""
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

RESULTS = ROOT / "results/analog/tx/serializer/clock_replay/wobble"
UI = 250e-12
VCO = 500e-12
CLOCKS = (("250", "d250", 4e-9), ("500", "d500", 2e-9), ("1g", "d1g", 1e-9), ("2g", "ds", 0.5e-9))
T_FROM = 30e-9                                   # reference 250 MHz fall: first one after this
INK, MUTED = "#222222", "#888888"
PROC_ORDER = ("tt", "ss", "ff", "fs", "sf")
SERIES = ("#2a6fb0", "#d0762c", "#3a9a5b", "#9b59b6", "#c0392b", "#7f8c8d")


def centroid(t, y, period):
    e, pol = crossings(t, y)
    ph = np.where(pol > 0, e, e - period / 2) / period
    return float(np.angle(np.mean(np.exp(2j * np.pi * ph))) / (2 * np.pi)) * period


def load(run_dir):
    meta = json.loads((run_dir / "execution.json").read_text())
    tag = meta.get("condition") or meta.get("cut", {}) and None
    w = spice.Waves(run_dir / "waveforms.raw")
    e, pol = crossings(w.t, w["d250"])
    t0 = e[(pol < 0) & (e > T_FROM)][0]
    win = (w.t > t0 - 3 * UI) & (w.t < t0 + 19 * UI)
    out = dict(t=(w.t[win] - t0), clocks={})
    for clk, vec, period in CLOCKS:
        y = w[vec][win]
        sel = (w.t > t0 - period) & (w.t < t0 + 2 * period)
        out["clocks"][clk] = dict(y=y, phase=centroid(w.t[sel] - t0, w[vec][sel], period))
    return out


def condition_of(run_dir):
    meta = json.loads((run_dir / "execution.json").read_text())
    bc = meta.get("bc")
    point = meta.get("point")
    if bc:
        from serdes_flow import boundary
        return boundary.get(bc)["points"][point]["condition"]
    return point


def wrap(x, p):
    return (x + p / 2) % p - p / 2


def campaign_runs(camp):
    runs = []
    for d in sorted(camp.iterdir()):
        r = d / "run"
        if spice.has_waves(r) and (r / "execution.json").exists():
            runs.append((d.name, r))
    return runs


def bands(camp, out):
    runs = [(name, condition_of(r), load(r)) for name, r in campaign_runs(camp)]
    groups = {}
    for name, tag, data in runs:
        groups.setdefault(tag.split("_")[0], []).append((name, tag, data))
    procs = [p for p in PROC_ORDER if p in groups]
    fig, axes = plt.subplots(len(CLOCKS), len(procs), figsize=(4.6 * len(procs), 1.9 * len(CLOCKS)),
                             sharex=True, squeeze=False)
    summary = {}
    for j, proc in enumerate(procs):
        members = sorted(groups[proc], key=lambda m: m[1])
        ref = members[0][2]
        summary[proc] = {}
        for i, (clk, _, period) in enumerate(CLOCKS):
            ax = axes[i, j]
            offs = []
            for k, (name, tag, data) in enumerate(members):
                c = data["clocks"][clk]
                d = wrap(c["phase"] - ref["clocks"][clk]["phase"], period)
                state = round(d / VCO) * VCO if clk in ("500", "1g") else 0.0
                offs.append(d - state)
                ax.plot((data["t"] - state) / UI, c["y"], color=SERIES[k % len(SERIES)], lw=1.0,
                        label=tag if i == 0 else None)
            lo, hi = min(offs), max(offs)
            # fill the sweep of every edge of the reference waveform
            e, _ = crossings(ref["t"], ref["clocks"][clk]["y"])
            for x in e:
                ax.axvspan((x + lo) / UI, (x + hi) / UI, color="#f2b134", alpha=0.35, lw=0)
            ax.axhline(0, color=MUTED, lw=0.4)
            ax.set_xlim(-1, 17)
            ax.set_title(f"{proc.upper()} {clk}: band {(hi - lo) / UI:.2f} UI", fontsize=8, color=INK)
            summary[proc][clk] = dict(band_ui=(hi - lo) / UI, offsets_ui={m[1]: o / UI for m, o in zip(members, offs)})
        axes[0, j].legend(fontsize=6, loc="lower left", frameon=False)
        axes[-1, j].set_xlabel("UI from 250 MHz fall", fontsize=8)
    for i, (clk, _, _) in enumerate(CLOCKS):
        axes[i, 0].set_ylabel(f"{clk} diff V", fontsize=8)
    fig.suptitle(f"{camp.relative_to(ROOT)}: serializer-input clocks per process over its V/T points "
                 "(start states removed; shaded = edge sweep)", fontsize=9)
    fig.tight_layout()
    png = out / f"{camp.name}.png"
    fig.savefig(png, dpi=100)
    plt.close(fig)
    for proc, s in summary.items():
        print(f"{proc.upper()} ({len(groups[proc])} pts): " + "  ".join(f"{k} {v['band_ui']:.2f}" for k, v in s.items())
              + " UI")
    return summary, png


if __name__ == "__main__":
    out = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True)
    allsum = {}
    for a in sys.argv[1:]:
        camp = (ROOT / a).resolve()
        print(camp.relative_to(ROOT))
        s, png = bands(camp, out)
        allsum[str(camp.relative_to(ROOT))] = s
        print(png.relative_to(ROOT))
    (out / "summary.json").write_text(json.dumps(allsum, indent=1, default=float))
