"""Recheck six current geometries against fixed PLL review evidence.

No new transistor simulation or native resistance extraction is run. Physical
delivery acceptance and final electrical qualification remain separate.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

from serdes_flow.project import ROOT

sys.path.insert(0, str(ROOT / "verification/layout"))
from review_cell import review


CELLS = [
    ("lf", "analog/pll/loop_filter/layout/variants/pdk", "pll_loop_filter_k4_pdk"),
    ("lf", "analog/pll/loop_filter/layout/variants/fused_pdk", "pll_loop_filter_k4_fused_pdk"),
    ("divider", "analog/pll/divider/layout/variants/review_clean", "pll_cml_prescaler8_pdk_clean"),
    ("divider", "analog/pll/divider/layout/variants/review_clean", "pll_frontend_dummy_load_pdk_clean"),
    ("vco", "analog/pll/vco/layout/variants/sym9_clean", "pll_vco_core_sym9_s32p5_clean"),
    ("receiver", "analog/common/cml_to_cmos/layout/variants/pdk", "serdes_cml_to_cmos_pvt_candidate_pdk"),
]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def require_digest(path, expected):
    if digest(path) != expected:
        raise ValueError(f"Evidence identity changed: {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    catalogs = {}
    evidence = {}
    for module in sorted({item[0] for item in CELLS}):
        path = ROOT / f"results/catalog/pll_layout_review_{module}_20261115.json"
        data = json.loads(path.read_text())
        require_digest(ROOT / data["export"], data["export_sha256"])
        for relative, expected in data["evidence"].items():
            require_digest(ROOT / relative, expected)
            evidence[relative] = expected
        catalogs[module] = data
        evidence[str(path.relative_to(ROOT))] = digest(path)

    def check(item):
        module, relative, cell = item
        directory = ROOT / relative
        mag, ref = directory / f"{cell}.mag", directory / f"{cell}_ref.spice"
        previous = next(p["data"] for p in catalogs[module]["physical"]
                        if p["data"].get("cell") == cell and "inputs" in p["data"])
        require_digest(mag, previous["inputs"][f"{cell}.mag"]["sha256"])
        require_digest(ref, previous["inputs"]["reference.spice"]["sha256"])
        result = review(mag, ref, out / cell)
        if not result["physical_passed"] or result["ports"] != previous["ports"]:
            raise ValueError(f"Physical regression: {cell}")
        print(f"DRC/LVS/ports accepted: {cell}", flush=True)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        physical = list(pool.map(check, CELLS))
    summary = dict(
        status="physical_delivery_accepted_electrical_qualification_partial",
        scope="LF original/fused, divider and dummy clean, sym9 clean core, C6 feedback receiver",
        evidence_identity_verified=len(evidence), evidence=evidence, physical=physical,
        final_electrical_signoff=False,
        divider_rc=dict(status="paused_pending_layout_review", issue="LAYOUT-PLL-DIV-RC-01",
                        physical_failure_confirmed=False),
        report="docs/layout/pll_acceptance_20261115.md",
    )
    path = out / "summary.json"
    path.write_text(json.dumps(summary, indent=2) + "\n")
    catalog = ROOT / "results/catalog/pll_layout_acceptance_20261115.json"
    catalog.write_text(json.dumps(dict(summary=str(path.relative_to(ROOT)), sha256=digest(path),
                                       status=summary["status"], final_electrical_signoff=False),
                                  indent=2) + "\n")
    print(f"Verified {len(evidence)} fixed evidence files; published {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
