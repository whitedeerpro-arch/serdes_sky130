"""Publish fixed-input pending-layout reviews without launching simulation."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import corners, netlist, spice
from serdes_flow.project import ROOT

BASE = ROOT / "results/layout_review/pll_pending_20261117"


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def complete(directory, evidence):
    deck, receipt = directory / "tb.cir", directory / "execution.json"
    text = deck.read_text()
    ex = json.loads(receipt.read_text())
    stop = netlist.number(re.search(r"^tran\s+\S+\s+(\S+)", text, re.M)[1])
    wave = directory / "waveforms.raw"
    w = spice.Waves(wave)
    if (ex["exit_code"] != 0 or ex["timed_out"] or ex["log_failures"]
            or ex["deck_sha256"] != digest(deck) or w.t[-1] < stop * (1 - 1e-6)
            or not np.all(np.isfinite(w.data))):
        raise ValueError(f"Incomplete or inconsistent run: {directory}")
    evidence.update((p, digest(p)) for p in [deck, receipt, wave, directory / "simulator.log"])
    section = re.search(r'^\.lib\s+"[^"]+"\s+(\S+)', text, re.M)[1]
    return w, section, bool(ex.get("inputs_sha256"))


def source_evidence(directory, evidence):
    for path in directory.glob("*"):
        if path.is_file() and path.suffix in (".mag", ".spice", ".json", ".py"):
            evidence[path] = digest(path)


def lf(evidence):
    analyses = [BASE / p for p in [
        "lf_dummy_ac/analysis/20261117T115418.545234Z/summary.json",
        "lf_dummy_precharge/analysis/20261117T115818.555744Z/summary.json"]]
    data = [json.loads(p.read_text()) for p in analyses]
    for p in analyses:
        evidence[p] = digest(p)
    for campaign in (BASE / "lf_dummy_ac", BASE / "lf_dummy_precharge"):
        for receipt in campaign.glob("*/execution.json"):
            ex = json.loads(receipt.read_text())
            if ex["exit_code"] != 0 or ex["timed_out"] or ex["log_failures"]:
                raise ValueError(receipt)
            if (receipt.parent / "waveforms.raw").exists():
                complete(receipt.parent, evidence)
            else:
                for name in ("impedance.tsv", "feedthrough.tsv"):
                    table = np.loadtxt(receipt.parent / name, skiprows=1)
                    if table[-1, 0] < 1e9 or not np.all(np.isfinite(table)):
                        raise ValueError("Incomplete LF AC table")
        for p in campaign.rglob("*"):
            if p.is_file() and p.suffix in (".spice", ".json", ".cir", ".tsv", ".raw"):
                evidence[p] = digest(p)
    source_evidence(BASE / "lf_dummy_rebuild/pll_loop_filter_k4_fused_pdk", evidence)
    source_evidence(ROOT / "analog/pll/loop_filter/layout/variants/fused_pdk", evidence)
    return dict(status="local_geometry_and_cpex_screen_accepted", analyses=data,
                scope="Seven local AC/precharge points; no new native RC, full-loop, MC or noise qualification")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("module", choices=("lf",))
    args = ap.parse_args()
    output = BASE / "exports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True, exist_ok=False)
    evidence = {}
    result = globals()[args.module](evidence)
    sources = [Path(__file__).resolve(), ROOT / "src/serdes_flow/clock.py"]
    if args.module != "lf":
        sources.append(ROOT / "analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py")
    for source in sources:
        target = output / source.name
        shutil.copy2(source, target)
        evidence[target] = digest(target)
    result.update(module=args.module, evidence={str(p.relative_to(ROOT)): h for p, h in sorted(evidence.items())},
                  final_electrical_signoff=False)
    path = output / "summary.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    catalog = ROOT / f"results/catalog/pll_pending_{args.module}_review_20261117.json"
    catalog.write_text(json.dumps(dict(summary=str(path.relative_to(ROOT)), sha256=digest(path),
                                       status=result["status"], final_electrical_signoff=False), indent=2) + "\n")
    print(path.relative_to(ROOT), result["status"], f"{len(evidence)} evidence hashes")


if __name__ == "__main__":
    main()
