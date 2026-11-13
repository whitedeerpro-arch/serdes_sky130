"""Two r6 range ends with a physical unit or complete shared-plate bank.

14 ns/4 ps, 8..14 ns saved, existing r6 measurement/drift check. One deck per
corner, smoke first, <=2 workers. Only half-unit devices/Cfr/Cbp/AD/AS are
replaced. A complete bank debits its direct phase wiring from the existing
12 fF allowance; --keep-full-wire is an explicit additional-load stress.
Ring, varactors, buffers and real bias are unchanged. Not PLL qualification.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re

from serdes_flow import spice
from serdes_flow.spice import spice_number
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from run import validated_netlist


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pex", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--keep-full-wire", action="store_true", help="Retain all 12fF as additional wiring stress for a full bank")
    ap.add_argument("--all-supplies", action="store_true", help="Check FS/hh hot and SF/ll cold at all three supplies")
    args = ap.parse_args()
    spec = importlib.util.spec_from_file_location("r6_layout_ends", ROOT / "analog/pll/vco/tb/tuning/r6.py")
    r6 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r6)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=args.resume)
    if args.resume and any(out.iterdir()) and not (out / "input_identity.json").exists():
        raise ValueError("Legacy campaign lacks bank/budget identity; use a new output directory")
    pex = validated_netlist(args.pex)
    caps = re.findall(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b", pex, re.M)
    top = re.search(r"^\.subckt (\S+) (node (?:en|b0 b1 b2 b3 b4) vss)$", pex, re.M)
    if not caps or not top:
        raise ValueError("Expected validated physical half-unit or shared bank")
    is_bank = top[2] == "node b0 b1 b2 b3 b4 vss"
    plates = Counter(caps)
    if (is_bank and sorted(plates.values()) != [1, 2, 4, 8, 16]) or (not is_bank and len(caps) != 1):
        raise ValueError("Incorrect unit count / plate grouping")
    # Match the per-unit numerical DC reference, without drawing a resistor.
    anchors = "\n".join(f"Rdc{i} {p} vss {1e12/n:.12g}" for i,(p,n) in enumerate(plates.items()))
    pex = re.sub(r"^\.ends.*$", anchors + "\n.ends", pex, flags=re.M)
    physical = out / "physical.spice"
    if physical.exists() and physical.read_text() != pex:
        raise ValueError("PEX changed; use a new campaign")
    physical.write_text(pex)
    points = [("hh", Condition.parse("fs_v1650_t85"), 0, 1.21),
              ("ll", Condition.parse("sf_v1650_t-40"), 31, .90)]
    if args.all_supplies:
        points = [(rc, Condition.parse(f"{process}_v{mv}_t{temp}"), code, round(mv/1000-.44,3) if code == 0 else .9)
                  for mv in [1650,1800,1950]
                  for rc,process,temp,code in [("hh","fs",85,0),("ll","sf",-40,31)]]
    # Keep the shared resistor snapshots untouched so normal resume identity
    # checking still works; use a distinct physical bank include instead.
    original = (ROOT / "analog/pll/vco/spice/cap_bank_5b.spice").read_text()
    budget = dict(total_fF=12.0, bank_direct_fF=0., fringe_excess_fF=0., retained_fF=12.,
                  policy="unit only; all phase wiring allowance retained")
    if is_bank:
        bank_text = (".subckt pll_vco_cap_bank5 node b0 b1 b2 b3 b4 vss params: capw=2 capl=2 sw=1.5\n"
                     f"Xphysical node b0 b1 b2 b3 b4 vss {top[1]}\n.ends pll_vco_cap_bank5\n")
        matrix = [(a,b,spice_number(v)*1e15) for a,b,v in re.findall(r"^C\S+ (\S+) (\S+) (\S+)$",pex,re.M)]
        direct = sum(v for a,b,v in matrix if "node" in (a,b) and (b if a == "node" else a) not in plates)
        fringe = sum(v for a,b,v in matrix if "node" in (a,b) and (b if a == "node" else a) in plates)
        excess = max(0., fringe - 31*.648)
        retained = 12. if args.keep_full_wire else 12. - direct - excess
        if retained < 0:
            raise ValueError("Physical bank consumes more than the 12fF wiring allowance")
        budget = dict(total_fF=12., bank_direct_fF=direct, fringe_excess_fF=excess, retained_fF=retained,
                      policy="full additional 12fF stress" if args.keep_full_wire else "debit bank direct and positive fringe excess; residual for unextracted stage/varactor/buffer wires")
    else:
        wrapper = (".subckt pll_vco_cap_unit6 node en vss params: capw=2 capl=2 sw=1.5\n"
                   f"Xphysical node en vss {top[1]}\n.ends pll_vco_cap_unit6")
        bank_text, count = re.subn(r"\.subckt pll_vco_cap_unit6\b.*?\.ends pll_vco_cap_unit6",
                                   lambda _: wrapper, original, flags=re.S | re.I)
        if count != 1:
            raise ValueError("Cannot replace half-unit")
    bank = out / "physical_bank.spice"
    if bank.exists() and bank.read_text() != bank_text:
        raise ValueError("Bank changed; use a new campaign")
    bank.write_text(bank_text)
    identity = dict(source_netlist=pex, wiring_budget=budget)
    identity_path = out / "input_identity.json"
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("Input/budget changed; use a new campaign")
    identity_path.write_text(json.dumps(identity, indent=2) + "\n")
    jobs = r6.jobs_for(out, points, f"cwire={budget['retained_fF']:.12g}f")
    patched = []
    for deck, dest, opts in jobs:
        deck, n = re.subn(r'^\.include "[^"\n]*/cap_bank_5b.spice"$',
                          lambda _: f'.include "{bank}"', deck, flags=re.M)
        if n != 1:
            raise ValueError("Expected exactly one bank include")
        deck = deck.replace(".control\n", f'.include "{physical}"\n.control\n', 1)
        opts["meta"].update(layout_scope="bank PEX" if is_bank else "half-unit PEX", wiring_budget=budget)
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
    report = dict(scope="r6 open-loop ring + four 30fF-loaded buffers; " + ("physical shared bank" if is_bank else "physical half-unit"), rows=rows,
                  wiring_budget=budget, retained="original ring devices/varactors/buffers/real bias",
                  replaced="bank physical devices, AD/AS/PD/PS and extracted capacitances; remove estimated Cfr/Cbp",
                  drift_warnings=r6.UNSETTLED, full_ring_or_PLL_qualified=False)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
