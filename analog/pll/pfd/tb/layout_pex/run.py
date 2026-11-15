"""PFD CPEX versus schematic, with the adopted schematic CP as an unequal load.

CP/Bias are boundary models, not physical DUTs under review. Reuses the original
phase sweep and charge measurement; saves binary waveforms to check missed or
stuck outputs independently of SPICE scalar measurements.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys

import numpy as np
from serdes_flow import clock, project, spice, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from review_cell import sha256

spec = importlib.util.spec_from_file_location("pfd_sc_bench", ROOT / "analog/pll/pfd/tb/pfd_cp_sc/run.py")
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)
POINTS = ["tt_v1800_t27:1.15", "ss_v1650_t-40:1.0", "sf_v1650_t-40:1.0",
          "fs_v1650_t85:1.15", "ss_v1650_t85:1.0", "ff_v1950_t-40:1.3", "ff_v1950_t85:1.3"]


def deck(point, variant, source):
    name, vout = point.split(":")
    c = Condition.parse(name)
    text, tend = sc.deck(c, float(vout), "sc8_dly")
    # Use the physical generator's exact reference, rather than a second copy
    # of the standard-cell topology embedded in an older comparison bench.
    text, n = re.subn(r'^\.include "' + re.escape(sc.SC_LIB) + r'"\n.*?^\.ends pll_pfd_sc\n',
                      f'.include "{source}"\n', text, flags=re.M | re.S)
    assert n == 1
    text = text.replace("Xpfd ref fb rst_b up dn vdd 0 pll_pfd_sc",
                        "Xpfd ref fb rst_b up dn vdd 0 pll_pfd_sc_dly_pdk")
    text = text.replace("quit\n.endc", "wrdata waveforms.tsv v(ref) v(fb) v(up) v(dn) i(Vout)\nquit\n.endc")
    return spice.binary_output(text), tend, c


def summarize(path, c, tend):
    w = spice.Waves(path)
    if w.t[-1] < tend * (1-1e-6):
        raise ValueError("truncated waveform")
    values = sc.parse((path.parent / "simulator.log").read_text())
    if len(values) != len(sc.pm.PHASES) + 2:
        raise ValueError("incomplete charge/pulse measurements")
    r = sc.summarize(values)
    count = {}
    for node in ("ref", "fb", "up", "dn"):
        count[node] = len(clock.edges(w.t, w[node] - c.supply/2, start=12.5e-9, stop=tend-.5e-9))
    # Same local no-dead-zone slope criterion as the established PFD/CP bench.
    # Static offset and width deltas are reported, without inventing a spec.
    r.update(edge_counts=count, functional_passed=all(v == len(sc.pm.PHASES) for v in count.values()),
             dead_zone_passed=bool(0.5 <= r["gain_ratio"] <= 1.5 and r["gain_a"] > 0))
    return r


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--physical-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path)
    ap.add_argument("--resume", type=Path)
    ap.add_argument("--points", nargs="+", default=POINTS)
    ap.add_argument("--workers", type=int, default=2, choices=(1, 2))
    ap.add_argument("--variants", nargs="+", default=["schematic", "cpex", "rcx"],
                    choices=("schematic", "cpex", "rcx"))
    args = ap.parse_args()
    source = args.physical_dir.resolve()
    out = args.resume or args.output_dir or (ROOT / "results/analog/pll/pfd/layout_pex" /
                                            datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ"))
    out = out.resolve()
    files = {"schematic": source / "reference.spice", "cpex": source / "pll_pfd_sc_dly_pdk_pex.spice",
             "rcx": source / "pll_pfd_sc_dly_pdk_rcx.spice"}
    files = {name: files[name] for name in args.variants}
    identity = {name: sha256(file) for name, file in files.items()}
    identity["points"] = args.points
    if args.resume:
        if json.loads((out / "identity.json").read_text()) != identity:
            raise ValueError("resume input identity changed")
    else:
        out.mkdir(parents=True, exist_ok=False)
        (out / "identity.json").write_text(json.dumps(identity, indent=2)+"\n")
    jobs, cases = [], []
    for point in args.points:
        for variant, file in files.items():
            text, tend, c = deck(point, variant, file)
            key = f"{point.split(':')[0]}_{variant}"
            existing = spice.case_output(out, key, "waveforms.raw", t_end=tend)
            if existing is None:
                rdir = spice.next_run_dir(out, key)
                jobs.append((text, rdir, dict(timeout_s=600, meta=dict(point=point, variant=variant))))
            else:
                rdir = existing.parent
            cases.append((point, variant, rdir, c, tend))
    if len(watch.ngspice_cwds()) + args.workers > 4:
        raise RuntimeError("ngspice worker quota occupied")
    # The inherited SPICE scalar measurements refer to 12..57 ns and cannot
    # run in a 1 ns smoke. Keep its circuit/output, omit only those measures.
    if jobs:
        smoke_text = re.sub(r"^meas tran .*\n|^print q0 .*\n", "", jobs[-1][0], flags=re.M)
        smoke_dir = spice.next_run_dir(out, "smoke")
        smoke_ex = spice.run(spice.smoke_deck(smoke_text), smoke_dir, timeout_s=180)
        smoke_w = spice.Waves(smoke_dir / "waveforms.raw")
        if not smoke_ex.ok or smoke_w.t[-1] < 1e-9 * (1-1e-6):
            raise RuntimeError(f"smoke failed: {smoke_dir}")
    for ex in spice.run_many(jobs, workers=args.workers, smoke=False):
        print(ex.run_dir.name, ex.ok, round(ex.elapsed_s, 1), flush=True)
        if not ex.ok:
            raise RuntimeError(f"simulation failed: {ex.run_dir}")
    rows = {}
    for point, variant, rdir, c, tend in cases:
        rows.setdefault(point, {})[variant] = summarize(rdir / "waveforms.raw", c, tend)
    result = dict(identity=identity, rows=rows, scope="nominal local points; CPEX/RCX, schematic CP/Bias; no MC")
    analysis = out / "analysis" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    analysis.mkdir(parents=True, exist_ok=False)
    (analysis / "summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(analysis / "summary.json")


if __name__ == "__main__":
    main()
