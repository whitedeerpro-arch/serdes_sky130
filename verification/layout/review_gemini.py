#!/usr/bin/env python3
"""Reproduce the initial Gemini leaf review against design-side references.

Copies inputs into a fresh results directory. Never extracts in source folders.
Full-chip cells are deliberately outside this first leaf-level review.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO / "verification/maintenance"))
from check import exported_ports  # noqa: E402
from repository_hygiene import digest, retirement_records  # noqa: E402

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


def historical_input(relative: str, retired: dict[Path, dict]) -> Path:
    """Resolve and verify a leaf from the original import or its retirement receipt."""
    original = Path(relative)
    candidates = [original]
    if original.parts[:2] in (("analog", "bias"), ("analog", "ldo")):
        # The import manifest uses the post-merge spelling; some receipts
        # preserve the location before Bias and LDO moved out of common/.
        candidates.append(Path("analog", "common", *original.parts[1:]))
    for candidate in candidates:
        record = retired.get(candidate)
        if record is None:
            continue
        archive = record.get("archive") or record.get("archive_path")
        if not archive:
            raise ValueError(f"Missing archive path in retirement receipt: {candidate}")
        path = REPO / archive
        if not path.is_file():
            raise FileNotFoundError(f"Archived import is unavailable: {path}")
        if path.stat().st_size != record["bytes"] or digest(path) != record["sha256"]:
            raise ValueError(f"Retired import identity changed: {candidate}")
        return path
    path = REPO / original
    if not path.is_file():
        raise FileNotFoundError(f"No live file or retirement receipt for imported input: {relative}")
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    manifest = json.loads((REPO / "analog/layout/import.json").read_text())
    retired = {path: row for _, path, row in retirement_records(REPO)}
    mag_paths = [
        historical_input(relative, retired)
        for relative in manifest["imported_files"]
        if relative.endswith(".mag")
    ]
    cases = [
        (cell, f"{folder}/{cell}.mag", historical_input(f"{folder}/{cell}.mag", retired),
         refs, [historical_input(ref, retired) for ref in refs])
        for folder, cell, refs in CASES
    ]
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, out / "review.py")
    report = {
        "scope": "initial six leaf cells; not full-chip validation",
        "imported_mag_count": len(mag_paths),
        "imported_mag_without_ports": sum(not re.search(r"^port ", p.read_text(), re.M) for p in mag_paths),
        "cases": [],
    }
    for cell, relative, source, refs, ref_paths in cases:
        work = out / cell
        work.mkdir()
        shutil.copy2(source, work / source.name)
        ref = work / "reference.spice"
        ref.write_text("* Design-side references for the import review\n" + "\n".join(p.read_text() for p in ref_paths))
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
            "cell": cell, "source": relative, "source_sha256": digest(source), "references": refs,
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
