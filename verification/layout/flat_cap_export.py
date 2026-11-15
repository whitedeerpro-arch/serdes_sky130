"""Audited capacitance export for flat MOS/MIM cells from Magic EXT records.

The installed 8.3.685 ext2spice redistributes subcircuit gate self-capacitance
as if every subcircuit were a resistor body. Preserve the EXT capacitance
matrix and use its independently checked LVS output only for devices.

Deliberately limited to flat cells without aliases/resistor bodies: reject
unsupported extraction records rather than silently losing their semantics.
"""
from __future__ import annotations

from collections import defaultdict
import argparse
import json
from pathlib import Path
import re
import shlex


def export(ext: Path, lvs: Path, output: Path) -> dict:
    rows = [shlex.split(line) for line in ext.read_text().splitlines() if line.strip()]
    if any(r[0] in {"use", "equiv", "merge", "killnode", "subcap", "resist"} for r in rows):
        raise ValueError("Only flat, unaliased MOS/MIM extraction supported")
    classes = {
        r[1] if not (r[1] == "subckt" and r[2].startswith("sky130_fd_pr__cap_var")) else "varsubckt"
        for r in rows
        if r[0] == "device"
    }
    if classes - {"msubckt", "csubckt", "varsubckt"}:
        raise ValueError(f"Unsupported device bodies: {classes}")
    scales = [r for r in rows if r[0] == "scale"]
    subs = [r[1] for r in rows if r[0] == "substrate"]
    if len(scales) != 1 or len(subs) != 1:
        raise ValueError("Expected one capacitance scale and one substrate net")
    scale = float(scales[0][2]) * 1e-18
    substrate = subs[0]
    matrix = defaultdict(float)
    node_self = {}
    for r in rows:
        if r[0] in {"node", "substrate"}:
            value = float(r[3]) * scale
            if value < 0:
                raise ValueError("Negative EXT self-capacitance")
            node_self[r[1]] = value
            if value and r[1] != substrate:
                matrix[tuple(sorted((r[1], substrate)))] += value
        elif r[0] == "cap":
            value = float(r[3]) * scale
            if value < 0:
                raise ValueError("Negative EXT coupling capacitance")
            if r[1] != r[2] and value:
                matrix[tuple(sorted((r[1], r[2])))] += value
    text = lvs.read_text()
    if re.search(r"^[Cc]\S*\s", text, re.M):
        raise ValueError("Device-only LVS input required")
    if len(re.findall(r"^\.subckt\b", text, re.M | re.I)) != 1:
        raise ValueError("One flat subcircuit required")
    caps = "\n".join(f"Cpex{i} {a} {b} {value:.12g}" for i,((a,b),value) in enumerate(sorted(matrix.items())))
    text, n = re.subn(r"^\.ends.*$", lambda _: caps + "\n.ends", text, flags=re.M | re.I)
    if n != 1:
        raise ValueError("Missing flat subcircuit end")
    if output.exists():
        raise FileExistsError(output)
    output.write_text("* Capacitance matrix from flat EXT node/cap records; device attributes from LVS.\n" + text)
    return dict(method="flat_EXT_matrix_plus_LVS_devices", ext=str(ext), lvs=str(lvs),
                output=str(output), substrate=substrate, capacitor_count=len(matrix),
                self_fF={k:v*1e15 for k,v in node_self.items()},
                limits="flat MOS/MIM/varactor only; no aliases, hierarchy or resistor-body handling")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ext", type=Path)
    ap.add_argument("lvs", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()
    report = export(args.ext, args.lvs, args.output)
    args.output.with_suffix(".audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
