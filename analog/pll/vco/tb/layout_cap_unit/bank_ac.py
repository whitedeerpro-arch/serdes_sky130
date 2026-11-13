"""All 32 bank codes at TT/27C: planning reference vs physical shared bank.

Local biased AC (not an oscillating VCO). One library load, 32 one-point
analyses. Outputs contain only real capacitances, <= 10 kB total. Optional
family reduction must be compared with full-library data before reuse.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re

from serdes_flow import spice, model_library
from serdes_flow.project import ROOT, model_library as library_path
from run import read_capacitance_row, validated_netlist


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pex", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--reduced", action="store_true")
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pex = validated_netlist(args.pex)
    top = re.search(r"^\.subckt (\S+) node b0 b1 b2 b3 b4 vss$", pex, re.M)
    plates = Counter(re.findall(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b", pex, re.M))
    if not top or sorted(plates.values()) != [1,2,4,8,16]:
        raise ValueError("Expected validated shared 31-unit bank")
    anchors = "\n".join(f"Rdc{i} {plate} vss {1e12/n:.12g}" for i,(plate,n) in enumerate(plates.items()))
    pex = re.sub(r"^\.ends.*$", anchors + "\n.ends", pex, flags=re.M)
    physical = out / "physical.spice"
    physical.write_text(pex)
    library = library_path()
    if args.reduced:
        library = model_library.build(library, "tt", ["sky130_fd_pr__nfet_01v8", "sky130_fd_pr__cap_mim_m3_1"], out / "models")
    lines = ["Physical shared bank vs r6 planning, all codes", f'.lib "{library}" tt',
             f'.include "{ROOT / "analog/pll/vco/spice/cap_bank_5b.spice"}"',
             f'.include "{physical}"', ".temp 27", "Vp0 q0 0 dc 1.5 ac 1", "Vp1 q1 0 dc 1.5 ac 1"]
    lines += [f"Vb{i} b{i} 0 0" for i in range(5)]
    lines += ["X0 q0 b0 b1 b2 b3 b4 0 pll_vco_cap_bank5",
              f"X1 q1 b0 b1 b2 b3 b4 0 {top[1]}",
              ".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale", "set numdgt=12"]
    for code in range(32):
        lines += [f"alter Vb{i} dc={1.8 if code>>i&1 else 0}" for i in range(5)]
        lines += ["ac lin 1 2e9 2e9", "let c0 = -imag(i(vp0))/(2*pi*frequency)",
                  "let c1 = -imag(i(vp1))/(2*pi*frequency)", f"wrdata code{code}.tsv c0 c1", "destroy all"]
    lines += ["quit", ".endc", ".end", ""]
    result = spice.run("\n".join(lines), out / "simulation", timeout_s=180)
    if not result.ok:
        raise RuntimeError(f"AC failed: {result}")
    rows = [dict(code=code, **read_capacitance_row(result.run_dir / f"code{code}.tsv", ["planning","physical"],2e9))
            for code in range(32)]
    steps = [rows[i+1]["physical"]-rows[i]["physical"] for i in range(31)]
    report = dict(scope="TT/27C nodeDC1.5V, code0/1.8V, 2GHz small-signal; not transient VCO/PVT qualification",
        source=str(args.pex.resolve()), reduced=args.reduced, elapsed_s=result.elapsed_s, rows=rows,
        physical_monotone=all(step>0 for step in steps), step_fF=steps, min_step_fF=min(steps), max_step_fF=max(steps))
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ["rows","step_fF"]},indent=2))
    print("endpoints",rows[0],rows[-1])


if __name__ == "__main__":
    main()
