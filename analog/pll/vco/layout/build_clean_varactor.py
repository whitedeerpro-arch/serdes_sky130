#!/usr/bin/env python3
"""Retain Gemini's symmetric varactor core; remove invalid guard-crossing dummies.

The four real 5.2/0.5 fingers and continuous guard ring are unchanged. The two
grounded dummy poly bars crossed/touched the P+ guard at their contact ends;
remove those bars and their dedicated contacts/LI links. This is a local leaf
iteration, not a claim of complete VCO layout qualification.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell  # noqa: E402

HERE = Path(__file__).resolve().parent
CELL = "pll_vco_varactor_clean"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    original = Cell.read(HERE / "pll_vco_varactor.mag")
    remove = {
        "poly": [(0.6, .3, .84, 8.1), (6.86, .3, 7.1, 8.1)],
        "polycont": [(x - .085, y - .085, x + .085, y + .085)
                     for x in [.72, 6.98] for y in [.36, 8.04]],
        "locali": [(x1, y - .14, x2, y + .14)
                   for x1, x2 in [(.36, .86), (.36, 7.34)] for y in [.36, 8.04]],
    }
    removed = {}
    for layer, rects in remove.items():
        keys = {tuple(round(v * 200) for v in rect) for rect in rects}
        before = original.rects[layer]
        original.rects[layer] = [r for r in before if tuple(round(v * 200) for v in r) not in keys]
        removed[layer] = len(before) - len(original.rects[layer])
        if removed[layer] != len(rects):
            raise ValueError("Imported source no longer matches the reviewed dummy geometry")
    original.write(out / f"{CELL}.mag")
    ref = out / "reference.spice"
    ref.write_text(re.sub(r"\bpll_vco_varactor\b", CELL, (HERE / "pll_vco_varactor_ref.spice").read_text()))
    proc = subprocess.run([sys.executable, str(REPO / "verification/layout/check.py"), str(out),
                           CELL, "--ref", str(ref)], capture_output=True, text=True)
    (out / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr)
    (out / "summary.json").write_text(json.dumps(dict(cell=CELL, checker_exit=proc.returncode,
        removed_dummy_shapes=removed, bbox_um=original.bbox(),
        retained="four real varactor fingers, matching core placement, gate/cathode straps and body guard"), indent=2) + "\n")
    if proc.returncode:
        raise RuntimeError("Varactor physical checks failed")


if __name__ == "__main__":
    main()
