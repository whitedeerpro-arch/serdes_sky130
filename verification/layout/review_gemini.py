#!/usr/bin/env python3
"""Reproduce the initial Gemini leaf review against design-side references.

Copies inputs into a fresh results directory. Never extracts in source folders.
Full-chip cells are deliberately outside this first leaf-level review.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check import exported_ports  # noqa: E402

PASSIVES = "analog/ldo/spice/ldo_passives.spice"
CASES = [
    ("analog/ldo/layout", "serdes_ldo_mim16", [PASSIVES]),
    ("analog/ldo/layout", "serdes_ldo_ref_res", [PASSIVES]),
    ("analog/ldo/layout", "serdes_pll_bias_lowpass_slow_r4",
     [PASSIVES, "analog/ldo/spice/pll_bias_filter_r4.spice"]),
    ("analog/ldo/layout", "serdes_ldo_hv18_core_r4",
     [PASSIVES, "analog/ldo/spice/ldo_hv18_core_r4.spice"]),
    ("analog/pll/vco/layout", "pll_vco_varactor", ["analog/pll/vco/layout/pll_vco_varactor_ref.spice"]),
    ("analog/pll/vco/layout", "pll_vco_cap_unit", ["analog/pll/vco/layout/pll_vco_cap_unit_ref.spice"]),
]


def imported_mags(manifest):
    """Keep the historical import audit reproducible after a draft is retired."""
    catalog = REPO / "results/catalog/retired_pll_top_20261117.json"
    retired = {r["former_path"]: r for r in json.loads(catalog.read_text())["files"]} if catalog.exists() else {}
    paths = []
    for relative in manifest["imported_files"]:
        if not relative.endswith(".mag"):
            continue
        path = REPO / relative
        if not path.is_file():
            record = retired[relative]
            path = (REPO / record["archive"]).resolve()
            if not path.is_relative_to(REPO / "results") or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError(f"Retired import identity changed: {relative}")
        paths.append(path)
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, out / "review.py")
    manifest = json.loads((REPO / "analog/layout/import.json").read_text())
    mag_paths = imported_mags(manifest)
    report = {
        "scope": "initial six leaf cells; not full-chip validation",
        "imported_mag_count": len(mag_paths),
        "imported_mag_without_ports": sum(not re.search(r"^port ", p.read_text(), re.M) for p in mag_paths),
        "cases": [],
    }
    for folder, cell, refs in CASES:
        work = out / cell
        work.mkdir()
        source = REPO / folder / f"{cell}.mag"
        shutil.copy2(source, work / source.name)
        ref = work / "reference.spice"
        ref.write_text("* Current design-side references, unchanged\n" + "\n".join((REPO / p).read_text() for p in refs))
        proc = subprocess.run(
            [sys.executable, str(REPO / "verification/layout/check.py"), str(work), cell, "--ref", str(ref)],
            capture_output=True, text=True, check=False,
        )
        log = proc.stdout + proc.stderr
        (work / "check.log").write_text(log)
        extracted = work / f"{cell}_lvs.spice"
        netlist = extracted.read_text() if extracted.exists() else ""
        drc = re.search(r"^DRC_TOTAL (\d+)$", log, re.M)
        shorted_caps = re.findall(r"^X\S+ (\S+) \1 sky130_fd_pr__cap_mim_m3_1\b", netlist, re.M)
        row = {
            "cell": cell, "source": str(source.relative_to(REPO)), "references": refs,
            "full_rule_drc_boxes": int(drc[1]) if drc else None,
            "netgen_graph_match": "LVS_MATCH True" in log,
            "exported_ports": exported_ports(extracted, cell) if extracted.exists() else [],
            "extracted_models": dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", netlist, re.M))),
            "shorted_mim_leaves": len(shorted_caps),
            "checker_exit": proc.returncode,
        }
        report["cases"].append(row)
        (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"{cell}: DRC={row['full_rule_drc_boxes']}, ports={row['exported_ports']}, checker={proc.returncode}", flush=True)


if __name__ == "__main__":
    main()
