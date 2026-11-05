"""Small, paired SKY130 benchmark; retains all decks, logs and scalar MC outputs.

uv run python verification/mc_profile.py --samples 3
Compares only removal of the unused final mc_source; it does not relax solver tolerances.
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import mc, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    args = ap.parse_args()
    if not 2 <= args.samples <= 16:
        ap.error("use 2..16 samples for the bounded profiling experiment")
    spec = importlib.util.spec_from_file_location("offset_mc", ROOT / "analog/rx/sampler/tb/offset_mc/run.py")
    om = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(om)
    camp = ROOT / "results/verification/mc_profile" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    c = Condition("tt", 1.8, 27)
    net = rcorner.to_pdk(om.netlist(c, "tt_mm", "ac_trim", 30, hold=("d1", "e0", "e1")), camp)
    text = mc.deck(net, args.samples, seed=1000, analysis=om.analysis(30), lets=om.LETS,
                   t_end=om.ramp_stop(30), profile=True)
    legacy = text.replace(f"  if mc_k < {args.samples}\n    mc_source\n  end", "  mc_source")
    executions = {}
    for name, deck in (("legacy_tail_reload", legacy), ("bounded_reload", text)):
        print(f"{name}: {camp}", flush=True)
        ex = spice.run(deck, camp / name, timeout_s=900)
        if not mc.complete(camp / name, text):
            raise RuntimeError(f"incomplete profile: {ex.run_dir}")
        executions[name] = ex.elapsed_s
    before, after = [mc.read(camp / n) for n in executions]
    identical = all(np.array_equal(mc.column(before, k), mc.column(after, k), equal_nan=True) for k in before[0])
    result = dict(samples=args.samples, elapsed_s=executions, paired_values_identical=identical,
                  note="Sequential wall times; no general speedup inferred from this small run. See rusage in logs.")
    (camp / "summary.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    if not identical:
        raise RuntimeError("sample sequence changed")


if __name__ == "__main__":
    main()
