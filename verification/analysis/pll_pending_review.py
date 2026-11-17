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


def bench():
    path = ROOT / "analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py"
    spec = importlib.util.spec_from_file_location("r5_review_measure", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def receiver(evidence):
    module = bench()
    campaign = ROOT / "results/analog/common/cml_to_cmos/r5_pdk/20261117T1451Z"
    rows = []
    for directory in sorted((campaign / "6corners").iterdir()):
        if not (directory / "execution.json").exists():
            continue
        mode, tag = directory.name.split("_", 1)
        w, section, identity = complete(directory, evidence)
        r = module._eval_rx_wave(directory / "waveforms.raw", corners.Condition.parse(tag))
        rows.append(dict(mode=mode, actual_model_section=section,
                         execution_include_hashes_present=identity, **r))
    chain = []
    for directory in sorted((campaign / "chain_div8").iterdir()):
        if not (directory / "execution.json").exists():
            continue
        c = corners.Condition.parse(directory.name)
        w, section, identity = complete(directory, evidence)
        metrics = {f"{node}{side}": module.logic_metrics(w.t, w[f"v({node}{side})"], c.supply, hz, 14e-9)
                   for node, hz in [("clk", 2e9), ("q2", 1e9), ("q4", .5e9), ("q8", .25e9)]
                   for side in ("p", "n")}
        chain.append(dict(condition=c.tag, actual_model_section=section,
                          execution_include_hashes_present=identity, signals=metrics,
                          both_polarities_passed=all(r["ok"] for r in metrics.values())))
    if len(rows) != 12 or len(chain) != 7:
        raise ValueError("Missing receiver review cases")
    source_evidence(ROOT / "analog/common/cml_to_cmos/layout/variants/r5_pdk", evidence)
    source_evidence(BASE / "receiver_r5", evidence)
    source_evidence(BASE / "receiver_r4", evidence)
    source_evidence(BASE / "r5_rebuild/serdes_cml_to_cmos_r5_pdk", evidence)
    return dict(status="changes_requested", issue="LAYOUT-PLL-RX-R5-01", rows=rows, chain=chain,
                scope="Candidate only: SS cold RCX functional failure; old chain hh/ll labels not applied; execution-time include identities absent; no MOS45/PEX MC signoff")


def cmos(evidence):
    module = bench()
    base = ROOT / "results/analog/pll/divider/cmos_prescaler8_2g_pdk"
    rows = []
    for campaign_name, count in [("20261116T223053Z_45corners", 45), ("20261116T221934Z_7corners", 14)]:
        campaign = base / campaign_name
        cases = [p.parent for p in sorted(campaign.glob("*/execution.json"))]
        if len(cases) != count:
            raise ValueError("Missing CMOS divider cases")
        for directory in cases:
            mode, tag = directory.name.split("_", 1) if count == 14 else ("cpex", directory.name)
            c = corners.Condition.parse(tag)
            w, section, identity = complete(directory, evidence)
            metrics = {f"{node}{side}": module.logic_metrics(w.t, w[f"v({node}{side})"], c.supply, hz, 14e-9)
                       for node, hz in [("out", 2e9), ("q2", 1e9), ("q4", .5e9), ("q8", .25e9)]
                       for side in ("p", "n")}
            rows.append(dict(campaign=campaign_name, condition=c.tag, mode=mode,
                             actual_model_section=section, signals=metrics,
                             both_polarities_passed=all(v["ok"] for v in metrics.values()),
                             power_mw=float(np.mean(w["pdiv"][w.t >= 14e-9]) * 1e3),
                             execution_include_hashes_present=identity))
    source_evidence(ROOT / "analog/pll/divider/layout/variants/cmos_2g_pdk", evidence)
    source_evidence(BASE / "divider_cmos", evidence)
    source_evidence(BASE / "cmos_rebuild/pll_cmos_prescaler8_2g_pdk", evidence)
    return dict(status="candidate_geometry_accepted_electrical_evidence_limited", rows=rows,
                scope="r4 CPEX driver + CMOS divider: recomputed both polarities and all periods; original includes not hashed at execution; no final full-RC/MC/startup signoff or adoption")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("module", choices=("lf", "receiver", "cmos"))
    args = ap.parse_args()
    output = BASE / "exports" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True, exist_ok=False)
    evidence = {}
    result = globals()[args.module](evidence)
    sources = [Path(__file__).resolve(), ROOT / "src/serdes_flow/clock.py"]
    if args.module == "lf":
        sources.extend(ROOT / p for p in ["analog/pll/loop_filter/layout/build_lf_fused_pdk.py",
                                          "analog/pll/loop_filter/tb/layout_pex/run.py"])
    if args.module != "lf":
        sources.append(ROOT / "analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py")
        sources.extend(ROOT / p for p in [
            "analog/common/cml_to_cmos/layout/build_cml_to_cmos_r4_pdk.py",
            "analog/common/cml_to_cmos/layout/build_cml_to_cmos_r5_pdk.py",
            "analog/common/cml_to_cmos/spice/cml_to_cmos_r4_v4.spice",
            "analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice",
            "analog/pll/divider/layout/build_cmos_prescaler8_2g_pdk.py",
            "analog/pll/divider/spice/cmos_prescaler8_2g.spice"])
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
