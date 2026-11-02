"""Monte Carlo with the SKY130 statistical sections (ngspice agauss + mc_source).

    text = mc.deck(netlist, samples=200, seed=1, analysis="op", lets={"vth1": "@m.xm1.msky130...[vth]"})
    ex = spice.run(text, run_dir)
    rows = mc.read(run_dir)            # one dict per sample, keys = the lets

`netlist` is a complete deck without a .control block (and without .end).  Library section:
'<corner>_mm' varies local mismatch only (mc_mm_switch = 1); 'mc' varies global process
(mc_pr_switch = 1).  Per sample: the analysis, the `let` expressions, one `wrdata` row appended to
mc.tsv, then `mc_source`, which re-sources the circuit and re-evaluates every agauss (a new sample)
without reloading the model files (~0.2 s per sample for a few tens of devices; the first model
load is ~15 s).  setseed makes a run reproducible.  The loop counter lives in the const plot and every
analysis plot is destroyed after its row is written, so long runs do not accumulate plots.
Only analyses that leave a scalar per `let` (op, or `meas`-style reductions) are supported.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MC_FILE = "mc.tsv"


def deck(netlist: str, samples: int, *, seed: int = 1, analysis: str = "op", lets: dict[str, str]) -> str:
    names = list(lets)
    body = [f"  let {k} = {v}" for k, v in lets.items()]
    ctl = ["", ".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale", "set appendwrite",
           f"setseed {int(seed)}", "let mc_k = 0", f"dowhile mc_k < {int(samples)}", f"  {analysis}"] + body + [
           f"  wrdata {MC_FILE} " + " ".join(names), "  destroy all", "  setplot const", "  let mc_k = mc_k + 1",
           "  mc_source", "end", "quit", ".endc", ".end", ""]
    return netlist.rstrip() + "\n" + "\n".join(ctl)


def read(run_dir) -> list[dict]:
    """Rows of mc.tsv (a header line precedes every appended row)."""
    rows, names = [], None
    for line in (Path(run_dir) / MC_FILE).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            vals = [float(x) for x in parts]
        except ValueError:
            names = parts
            continue
        rows.append(dict(zip(names, vals)))
    return rows


def column(rows, key):
    return np.array([r[key] for r in rows])
