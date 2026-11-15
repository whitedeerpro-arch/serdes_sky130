"""Publish small, fixed-identity PLL layout-review data; never choose latest runs.

Reports are handwritten in module layout/review.md. This only hashes artifacts
and remeasures explicitly named complete waveforms into an append-only export.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from collections import Counter
import re

from serdes_flow import project, spice
from serdes_flow.corners import Condition

ROOT=project.ROOT
BASE=ROOT/"results/layout_review/pll_20261115"


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def waveform(relative,stop,evidence):
    path=BASE/relative/"waveforms.raw"
    ex=json.loads(path.with_name("execution.json").read_text())
    w=spice.Waves(path)
    if ex["exit_code"]!=0 or ex["log_failures"] or w.t[-1]<stop*(1-1e-6):
        raise ValueError(f"Incomplete or failed waveform: {path}")
    evidence.extend([path,path.with_name("execution.json"),path.with_name("tb.cir")])
    # Every frozen project include is retained and hashed, not just the top.
    inputs=path.parent.parent/"inputs"
    if inputs.exists():evidence.extend(p for p in inputs.iterdir() if p.is_file())
    return path


def vco(evidence):
    module=load_module("analog/pll/vco/tb/layout_pex/run.py","vco_layout_measure")
    rows={}
    cases=[("slow_cpex","vco_ramped_probe/fs_v1650_t85_hh_0_1.21_cpex"),
           ("fast_cpex","vco_ramped_fast/sf_v1650_t-40_ll_31_0.90_cpex"),
           ("slow_devices","vco_devices_probe/fs_v1650_t85_hh_0_1.21_devices"),
           ("fast_devices","vco_devices_probe/sf_v1650_t-40_ll_31_0.90_devices")]
    for key,relative in cases:
        rows[key]=module.measure(waveform(relative,24e-9,evidence))
    for relative in ["vco_clean_anchored/fs_v1650_t85_hh_0_1.21_schematic",
                     "vco_clean_anchored/sf_v1650_t-40_ll_31_0.90_schematic"]:
        waveform(relative,24e-9,evidence)
    failed=BASE/"vco_ramped_rc/fs_v1650_t85_hh_0_1.21_rcx"
    evidence.extend(failed/name for name in ["execution.json","simulator.log","tb.cir","waveforms.raw"])
    evidence.extend((BASE/"vco_clean_anchored/inputs").glob("*"))
    evidence.extend((BASE/"vco_ramped_rc/inputs").glob("*"))
    evidence.extend(BASE/"vco_rebuild/core_s32p5"/name for name in ["pll_vco_core_sym9_s32p5.mag","check.log","summary.json"])
    from serdes_flow import boundary
    bc=boundary.get("pll_sym9_dc_bias@layout_review_20261115")
    signature=module.bias_load_signature(BASE/"vco_clean/physical/pll_vco_core_sym9_s32p5_clean_pex.spice","pll_vco_core_sym9_s32p5_clean")
    boundary.check_load(bc["id"],signature)
    return dict(rows=rows,boundary=bc,rc_status="numerical_incomplete",rc_execution=json.loads((failed/"execution.json").read_text()),
        physical=["vco/summary.json","vco_clean/physical/summary.json","vco_clean/cleanup.json","vco_clean/physical/rc_summary.json"],
        scope="CPEX endpoints; calibrated clamped bias, 5ns ramp, 6ns kick, 30fF/output. RC transient incomplete; no PLL/MC/noise signoff")


def divider(evidence):
    module=load_module("analog/pll/divider/tb/layout_pex/run.py","divider_layout_measure")
    cases=[("tt_cpex","divider_clean_performance/tt_v1800_t27_tt_cpex","tt_v1800_t27"),
           ("fs_cpex","divider_fs_cpex/fs_v1650_t85_hh_cpex","fs_v1650_t85")]
    rows={}
    for key,relative,condition in cases:
        rows[key]=module.measure(waveform(relative,48e-9,evidence),Condition.parse(condition))
    rc_states={}
    for tag in ["tt_v1800_t27_tt","fs_v1650_t85_hh"]:
        relative=f"divider_rc_gear/{tag}_rcx"
        path=BASE/relative/"execution.json"
        if not path.exists():
            audit=BASE/relative/"recovered_waveform_audit.json"
            if audit.exists():
                data=json.loads(audit.read_text())
                rc_states[tag]=dict(status="complete_waveform_missing_driver_receipt",execution_qualified=False,
                    observed_functional_passed=data["metrics"]["functional_passed"])
                rows[tag+"_native_rc_observation"]=data["metrics"]
                evidence.extend(BASE/relative/name for name in ["recovered_waveform_audit.json","waveforms.raw","tb.cir","simulator.log"])
                evidence.extend((BASE/"divider_rc_gear/inputs").glob("*"))
            else:rc_states[tag]="not_completed"
            continue
        ex=json.loads(path.read_text());evidence.append(path)
        rc_states[tag]=ex
        if ex["exit_code"]==0 and not ex["log_failures"]:
            condition=tag.rsplit("_",1)[0]
            rows[tag+"_native_rc"]=module.measure(waveform(relative,48e-9,evidence),Condition.parse(condition))
    evidence.extend(BASE/"divider_rebuild/pll_cml_prescaler8_pdk"/name for name in ["pll_cml_prescaler8_pdk.mag","check.log"])
    rc_text=(BASE/"divider_clean/physical/pll_cml_prescaler8_pdk_clean_rcx.spice").read_text()
    counts=Counter(re.sub(r"\.[nt]\d+$","",line.split()[1]) for line in rc_text.splitlines() if re.match(r"^R\S+\s",line))
    network=dict(physical_resistor_instances=16,parasitic_resistor_segments=sum(counts.values()),
        vss_segments=counts["vss"],vdd_segments=counts["vdd"],other_segments=sum(n for k,n in counts.items() if k not in {"vss","vdd"}),
        threshold_ohm=1,interpretation="Discretized network; layer/terminal semantics and reduction convergence not validated")
    return dict(rows=rows,native_rc=rc_states,rc_discretization=network,
        handoff=dict(id="LAYOUT-PLL-DIV-RC-01",status="suspect_pending_layout_review",full_rc_simulation="paused",physical_failure_confirmed=False),
        physical=["pll_cml_prescaler8_pdk/summary.json","divider_clean/physical/summary.json",
        "divider_clean/cleanup.json","divider_clean/physical/rc_summary.json","dummy_clean/physical/summary.json","dummy_clean/cleanup.json"],
        scope="Local TT/FS-hot CPEX /8 with CPEX feedback receiver; 300mVpp sine via schematic buffer; real schematic bias; no MOS45/MC/noise signoff")


def receiver(evidence):
    data=divider(evidence)
    data["physical"]=["receiver/summary.json"]
    data["rc_status"]="rejected: native RC changed AS/PS of two fully supply-shorted dummy MOS"
    evidence.extend((BASE/"receiver"/name) for name in ["rc.log","serdes_cml_to_cmos_pvt_candidate_pdk_rcx.spice"])
    return data


def lf(evidence):
    # Explicit successful analysis identities are added after each local card.
    analyses=["lf_ac/analysis/20261115T144824.915368Z/summary.json",
              "lf_precharge_probe/analysis/20261115T144530.525829Z/summary.json",
              "lf_precharge_100ns/analysis/20261115T145505.028646Z/summary.json"]
    data=[]
    for relative in analyses:
        path=BASE/relative
        data.append(json.loads(path.read_text()));evidence.append(path)
    for campaign in ["lf_ac","lf_precharge_probe","lf_precharge_100ns"]:
        directory=BASE/campaign
        evidence.extend((directory/"inputs").glob("*"))
        for path in directory.glob("*/execution.json"):
            ex=json.loads(path.read_text())
            if ex["exit_code"]!=0 or ex["log_failures"]:raise ValueError(f"Failed LF card: {path}")
            evidence.extend([path,path.with_name("tb.cir")])
            evidence.extend(p for p in path.parent.iterdir() if p.suffix in (".tsv",".raw"))
    evidence.extend(BASE/"lf_fused_rebuild/pll_loop_filter_k4_fused_pdk"/name for name in ["pll_loop_filter_k4_fused_pdk.mag","check.log"])
    return dict(analyses=data,physical=["pll_loop_filter_k4_pdk/summary.json","pll_loop_filter_k4_pdk/rc_summary.json",
        "pll_loop_filter_k4_fused_pdk/summary.json","pll_loop_filter_k4_fused_pdk/rc_summary.json"],
        scope="Local AC CPEX/native RC; independent schematic/CPEX precharge. Native-RC transient not qualified")


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("module",choices=("vco","divider","receiver","lf"))
    args=ap.parse_args()
    evidence=[]
    result=globals()[args.module](evidence)
    physical=[]
    for relative in result.pop("physical"):
        path=BASE/relative;physical.append(dict(source=str(path.relative_to(ROOT)),data=json.loads(path.read_text())))
        evidence.append(path)
        if path.name=="summary.json" and "physical" in path.parts:
            cell=physical[-1]["data"]["cell"]
            evidence.extend(path.with_name(cell+suffix) for suffix in [".mag","_lvs.spice","_pex.spice"])
            evidence.append(path.with_name("check.log"))
    result.update(review_date="2026-11-15",module=args.module,physical=physical,
                  evidence={str(p.relative_to(ROOT)):digest(p) for p in sorted(set(evidence)) if p.is_file()})
    out=BASE/"exports"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    out.mkdir(parents=True,exist_ok=False)
    (out/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
    catalog=ROOT/f"results/catalog/pll_layout_review_{args.module}_20261115.json"
    catalog.write_text(json.dumps(dict(export=str((out/"summary.json").relative_to(ROOT)),
        export_sha256=digest(out/"summary.json"),**result),indent=2)+"\n")
    print(catalog)


if __name__=="__main__":main()
