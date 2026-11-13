"""Compare actual half-unit PEX with r6's planning model before array replication.

One TT/27C deck, all variants and two gate states, two AC frequencies. This is
local calibration, not VCO/PVT qualification. Off plates use the same 1 Tohm DC
reference as the planning model. Only two real-valued AC rows/state are saved;
the shared waveform reader does not yet support complex binary AC plots.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT, model_library


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layout", action="append", required=True, help="name=path/to/pex.spice")
    ap.add_argument("--node-dc", type=float, default=1.5)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    lines = ["R6 physical half-unit calibration", f'.lib "{model_library()}" tt',
             f'.include "{ROOT / "analog/pll/vco/spice/cap_bank_5b.spice"}"', ".temp 27"]
    names = ["planning"]
    lines += [f"Vp0 n0 0 dc {args.node_dc} ac 1", "Ven en 0 0", "X0 n0 en 0 pll_vco_cap_unit6"]
    sources = {}
    for i, item in enumerate(args.layout, 1):
        name, path = item.split("=", 1)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in names:
            raise ValueError(f"Invalid/duplicate name: {name}")
        text = Path(path).read_text()
        top = re.search(r"^\.subckt (\S+) node en vss$", text, re.M)
        cap = re.search(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b", text, re.M)
        if not top or not cap:
            raise ValueError(f"Expected a validated half-unit PEX: {path}")
        text = re.sub(rf"\b{re.escape(top[1])}\b", f"unit_{name}", text)
        snapshot = out / f"{name}.spice"
        snapshot.write_text(text)
        lines += [f'.include "{snapshot}"', f"Vp{i} n{i} 0 dc {args.node_dc} ac 1",
                  f"X{i} n{i} en 0 unit_{name}", f"Rop{i} x{i}.{cap[1]} 0 1T"]
        names.append(name)
        sources[name] = str(Path(path).resolve())
    lines += [".control", "set num_threads=1", "set wr_singlescale", "set wr_vecnames", "set numdgt=12"]
    for state, level in [("off", 0), ("on", 1.8)]:
        lines += [f"alter Ven dc={level}"]
        for freq in [1e6, 2e9]:
            lines += [f"ac lin 1 {freq} {freq}"]
            lines += [f"let c{i} = -imag(i(vp{i}))/(2*pi*frequency)" for i in range(len(names))]
            lines += [f"wrdata {state}_{int(freq)}.tsv " + " ".join(f"c{i}" for i in range(len(names))), "destroy all"]
    lines += ["quit", ".endc", ".end", ""]
    result = spice.run("\n".join(lines), out / "simulation", timeout_s=180)
    if not result.ok:
        raise RuntimeError(f"AC calibration failed: {result}")
    measurements = {}
    for state in ["off", "on"]:
        measurements[state] = {name: {} for name in names}
        for freq, field in [(1e6, "c_1MHz_fF"), (2e9, "c_2GHz_fF")]:
            table = np.atleast_2d(np.loadtxt(result.run_dir / f"{state}_{int(freq)}.tsv", skiprows=1))
            # ngspice keeps the AC plot complex even after imag() conversion;
            # wrdata emits real/imaginary pairs. Require the unused part zero.
            if table.shape != (1, 2 * len(names) + 1) or not np.isfinite(table).all():
                raise ValueError("Incomplete AC result")
            if not np.allclose(table[:, 2::2], 0, atol=1e-25, rtol=0):
                raise ValueError("Expected real-valued effective capacitance")
            if abs(table[0, 0] / freq - 1) > 1e-9:
                raise ValueError("AC frequency mismatch")
            for i, name in enumerate(names):
                measurements[state][name][field] = float(table[0, 2 * i + 1] * 1e15)
    report = dict(scope="TT/27C DC-biased AC, not oscillating VCO or PVT qualification",
                  node_dc=args.node_dc, gate_on_v=1.8, off_plate_dc_reference_ohm=1e12,
                  sources=sources, measurements=measurements)
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
