"""Two r6 range ends with physical half-unit PEX; retain unextracted wiring budget.

14 ns/4 ps, 8..14 ns saved, existing r6 measurement/drift check. One deck per
corner, smoke first, <=2 workers. Only half-unit devices/Cfr/Cbp/AD/AS are
replaced. Ring, varactors, buffers, real bias and cwire=12f are unchanged.
This is not an extracted array/ring, nor closed-loop PLL qualification.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pex", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("r6_layout_ends", ROOT / "analog/pll/vco/tb/tuning/r6.py")
    r6 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r6)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=args.resume)
    pex = args.pex.read_text()
    cap = re.search(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b", pex, re.M)
    top = re.search(r"^\.subckt (\S+) node en vss$", pex, re.M)
    if not cap or not top:
        raise ValueError("Expected validated physical half-unit PEX")
    # Same numerical DC reference as the old planning unit (not a physical R).
    pex = re.sub(r"^\.ends.*$", f"Rdc {cap[1]} vss 1T\n.ends", pex, flags=re.M)
    physical = out / "physical_unit.spice"
    if physical.exists() and physical.read_text() != pex:
        raise ValueError("PEX changed; use a new campaign")
    physical.write_text(pex)
    points = [("hh", Condition.parse("fs_v1650_t85"), 0, 1.21),
              ("ll", Condition.parse("sf_v1650_t-40"), 31, .90)]
    # Keep the shared resistor snapshots untouched so normal resume identity
    # checking still works; use a distinct physical bank include instead.
    wrapper = (
        ".subckt pll_vco_cap_unit6 node en vss params: capw=2 capl=2 sw=1.5\n"
        f"Xphysical node en vss {top[1]}\n.ends pll_vco_cap_unit6"
    )
    bank_text, count = re.subn(r"\.subckt pll_vco_cap_unit6\b.*?\.ends pll_vco_cap_unit6",
        lambda _: wrapper, (ROOT / "analog/pll/vco/spice/cap_bank_5b.spice").read_text(), flags=re.S | re.I)
    if count != 1:
        raise ValueError("Cannot replace half-unit")
    bank = out / "physical_bank.spice"
    if bank.exists() and bank.read_text() != bank_text:
        raise ValueError("Bank changed; use a new campaign")
    bank.write_text(bank_text)
    jobs = r6.jobs_for(out, points, "")
    patched = []
    for deck, dest, opts in jobs:
        deck, n = re.subn(r'^\.include "[^"\n]*/cap_bank_5b.spice"$',
                          lambda _: f'.include "{bank}"', deck, flags=re.M)
        if n != 1:
            raise ValueError("Expected exactly one bank include")
        deck = deck.replace(".control\n", f'.include "{physical}"\n.control\n', 1)
        opts["meta"]["layout_scope"] = "half-unit PEX only; retain cwire=12f; non-extracted ring/bias/buffers"
        patched.append((deck, dest, opts))
    results = spice.run_many(patched, workers=2)
    for result in results:
        if not result.ok:
            raise RuntimeError(f"Corner failed: {result}")
    rows = {}
    base = ROOT / "results/analog/pll/vco/r6/map_20261112T062237Z"
    for rc, c, code, voltage in points:
        measured = r6.read(out, rc, c, code, voltage)
        if measured is None:
            raise ValueError(f"Incomplete endpoint: {c.tag}")
        baseline = r6.read(base, rc, c, code, voltage)
        rows[f"{c.tag}:{rc}"] = dict(code=code, vctrl=voltage, frequency_hz=measured[0],
            swing_vpp=measured[1], margin=(measured[0]/2e9-1)*(1 if code == 0 else -1),
            planning_baseline_hz=baseline[0] if baseline else None)
    report = dict(scope="r6 open-loop ring + four 30fF-loaded buffers; physical half-unit only", rows=rows,
                  retained="12fF/phase wiring allowance; original ring devices/varactors/buffers/real bias",
                  replaced="half-unit physical devices, AD/AS/PD/PS and extracted capacitances; remove its estimated Cfr/Cbp",
                  drift_warnings=r6.UNSETTLED, full_ring_or_PLL_qualified=False)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
