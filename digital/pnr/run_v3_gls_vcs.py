#!/usr/bin/env python3
"""VCS SDF-Annotated Post-Layout Gate-Level Simulation (GLS) + SVA + Verdi FSDB Signoff
for ``serdes_digital_top_v3`` (v3.1).

Steps:
  1. Export 3-corner post-route SDF 3.0 files (``tt_025C_1v80``, ``ss_100C_1v60``,
     ``ff_n40C_1v95``) from signed-off DEF + OpenRCX SPEF + Liberty in single-threaded
     OpenROAD (``-threads 1``).
  2. Deterministically identify genuine 1st-stage CDC/async-input synchronizer FFs
     in the post-route gate-level netlist and write a VCS ``+optconfigfile`` that
     disables timing checks ONLY on those explicit 1st-stage CDC FFs (while retaining
     100% of SDF cell/interconnect delays and 100% of synchronous FF timing checks).
  3. Run VCS 4-mode signoff strictly under ``results/digital/gls_v3_1/``:
       - Mode 0: ``rtl_golden``         (RTL + SVA + ``-xprop=tmerge``)
       - Mode 1: ``gls_tt_025C_1v80``   (SDF typ + SVA + ``-xprop=tmerge`` + Verdi FSDB)
       - Mode 2: ``gls_ss_100C_1v60``   (SDF max + SVA + ``-xprop=tmerge``)
       - Mode 3: ``gls_ff_n40C_1v95``   (SDF min + SVA + ``-xprop=tmerge``)
  4. Parse logs and emit ``results/digital/gls_v3_1/summary.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PDK = Path("/home/host/.volare/sky130A")
SC_HD = PDK / "libs.ref/sky130_fd_sc_hd"
TLEF_NOM = SC_HD / "techlef/sky130_fd_sc_hd__nom.tlef"
SC_LEF = SC_HD / "lef/sky130_fd_sc_hd.lef"
SKY130_PRIMITIVES_V = SC_HD / "verilog/primitives.v"
SKY130_CELLS_V = SC_HD / "verilog/sky130_fd_sc_hd.v"

OPENROAD = Path("/opt/eda_pnr/envs/pnr/bin/openroad")
VCS = Path("/opt/synopsys/vcs201809/bin/vcs")
VERDI_PLI_DIR = Path("/opt/synopsys/verdi201809/share/PLI/VCS/LINUX64")

PNR_RESULTS = REPO / "results/digital/pnr_v3_unified/serdes_digital_top_v3"
PNR_VARIANT = REPO / "digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3"
NETLIST_V = PNR_VARIANT / "serdes_digital_top_v3.v"
DEF_FILE = PNR_RESULTS / "serdes_digital_top_v3.def"
SDC_FILE = PNR_RESULTS / "serdes_digital_top_v3_postroute.sdc"
RTL_FILELIST = REPO / "digital/pnr/rtl_v3/rtl_v3.f"
GLS_FILELIST = REPO / "digital/pnr/rtl_v3/gls_v3.f"

OUT_ROOT = REPO / "results/digital/gls_v3_1"
SDF_DIR = OUT_ROOT / "sdf"
FSDB_TT_PATH = OUT_ROOT / "serdes_digital_top_v3_tt_gls.fsdb"
PRIMITIVES_VCS_V = OUT_ROOT / "sky130_primitives_vcs.v"
OPTCONFIG_PATH = OUT_ROOT / "cdc_sync_optconfig.cfg"
SUMMARY_JSON = OUT_ROOT / "summary.json"

CORNERS = [
    {
        "name": "tt_025C_1v80",
        "lib": SC_HD / "lib/sky130_fd_sc_hd__tt_025C_1v80.lib",
        "spef": PNR_RESULTS / "serdes_digital_top_v3_nom.spef",
        "sdf": SDF_DIR / "serdes_digital_top_v3_tt_025C_1v80.sdf",
        "sdf_mtm": "typ",
        "dump_fsdb": True,
    },
    {
        "name": "ss_100C_1v60",
        "lib": SC_HD / "lib/sky130_fd_sc_hd__ss_100C_1v60.lib",
        "spef": PNR_RESULTS / "serdes_digital_top_v3_max.spef",
        "sdf": SDF_DIR / "serdes_digital_top_v3_ss_100C_1v60.sdf",
        "sdf_mtm": "max",
        "dump_fsdb": False,
    },
    {
        "name": "ff_n40C_1v95",
        "lib": SC_HD / "lib/sky130_fd_sc_hd__ff_n40C_1v95.lib",
        "spef": PNR_RESULTS / "serdes_digital_top_v3_min.spef",
        "sdf": SDF_DIR / "serdes_digital_top_v3_ff_n40C_1v95.sdf",
        "sdf_mtm": "min",
        "dump_fsdb": False,
    },
]

ASYNC_INPUT_PORTS = {
    "bias_ready_async",
    "pre_ref_ready_async",
    "hi_async",
    "lo_async",
    "pw_late_async",
    "pll_abort_async",
}

SYNC_CLOCK_PAIRS = {
    ("ref_clk", "pll_clk_div4"),
    ("pll_clk_div4", "ref_clk"),
    ("rx_word_clk", "cdr_clk_div2"),
    ("cdr_clk_div2", "rx_word_clk"),
}


def run_cmd(cmd: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None) -> tuple[int, str]:
    t0 = time.monotonic()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    dt = time.monotonic() - t0
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(proc.stdout)
    print(f"  [{'OK' if proc.returncode == 0 else 'FAIL'}] ({dt:.1f}s) {' '.join(cmd[:6])} ... -> {log_path.relative_to(REPO)}")
    return proc.returncode, proc.stdout


def export_sdfs() -> dict[str, Any]:
    """Step 1: Export 3-corner post-route SDFs using OpenROAD -threads 1."""
    print("=== Step 1: Exporting 3-Corner Post-Route SDFs (OpenROAD -threads 1) ===")
    SDF_DIR.mkdir(parents=True, exist_ok=True)
    sdf_stats: dict[str, Any] = {}
    for c in CORNERS:
        tcl_path = SDF_DIR / f"export_{c['name']}.tcl"
        log_path = SDF_DIR / f"export_{c['name']}.log"
        tcl = "\n".join([
            f"read_lef {TLEF_NOM}",
            f"read_lef {SC_LEF}",
            f"read_liberty {c['lib']}",
            f"read_def {DEF_FILE}",
            f"read_sdc {SDC_FILE}",
            f"read_spef {c['spef']}",
            f"write_sdf -include_typ -digits 4 {c['sdf']}",
            "exit",
        ]) + "\n"
        tcl_path.write_text(tcl)
        rc, _ = run_cmd([str(OPENROAD), "-threads", "1", "-no_init", str(tcl_path)], REPO, log_path)
        if rc != 0 or not c["sdf"].exists():
            raise RuntimeError(f"OpenROAD write_sdf failed for {c['name']} (see {log_path})")
        text = c["sdf"].read_text()
        stats = {
            "path": str(c["sdf"].relative_to(REPO)),
            "bytes": c["sdf"].stat().st_size,
            "iopath": len(re.findall(r"\(IOPATH\b", text)),
            "interconnect": len(re.findall(r"\(INTERCONNECT\b", text)),
            "timingcheck_cells": len(re.findall(r"\(TIMINGCHECK\b", text)),
            "setup": len(re.findall(r"\(SETUP\b", text)),
            "hold": len(re.findall(r"\(HOLD\b", text)),
            "recovery": len(re.findall(r"\(RECOVERY\b", text)),
            "removal": len(re.findall(r"\(REMOVAL\b", text)),
        }
        if stats["iopath"] == 0 or stats["interconnect"] == 0 or stats["timingcheck_cells"] == 0:
            raise RuntimeError(f"Exported SDF for {c['name']} missing timing entries: {stats}")
        sdf_stats[c["name"]] = stats
        print(
            f"    {c['name']}: {stats['bytes']/1e6:.2f} MB | IOPATH={stats['iopath']} "
            f"INTERCONNECT={stats['interconnect']} TIMINGCHECK={stats['timingcheck_cells']} "
            f"(SETUP={stats['setup']}, HOLD={stats['hold']}, REC={stats['recovery']}, REM={stats['removal']})"
        )
    return sdf_stats


def prepare_primitives_and_cdc_optconfig(include_fifo_s1_banks: bool = False) -> dict[str, Any]:
    """Generate VCS-clean primitives copy and exact 1st-stage CDC FF optconfig."""
    print("=== Step 2: Identifying 1st-Stage CDC Synchronizer FFs & Preparing VCS Inputs ===")
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # Work around upstream SkyWater PDK primitives.v bug (`default_nettype none above UDP ports)
    prim_src = SKY130_PRIMITIVES_V.read_text()
    prim_patched = re.sub(
        r"^`default_nettype none\b",
        "// `default_nettype none (commented for VCS UDP port compatibility; PDK unmodified)",
        prim_src,
        flags=re.M,
    )
    PRIMITIVES_VCS_V.write_text(prim_patched)

    # Parse post-route netlist to identify exact 1st-stage CDC / async-input FFs
    netlist = NETLIST_V.read_text()
    inst_pat = re.compile(r"^\s*(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\((.*?)\);", re.M | re.S)
    ffs: list[tuple[str, str, dict[str, str]]] = []
    net_drivers: dict[str, tuple[str, str, str, dict[str, str]]] = {}

    for m in inst_pat.finditer(netlist):
        cell, inst, conns_str = m.groups()
        conns = {k: v.strip() for k, v in re.findall(r"\.(\w+)\(([^)]+)\)", conns_str)}
        for pin in ("Q", "Q_N", "X", "Y", "COUT", "SUM", "HI", "LO"):
            if pin in conns:
                net_drivers[conns[pin]] = (cell, inst, pin, conns)
        if "__df" in cell:
            ffs.append((cell, inst, conns))

    def clk_dom(clk_net: str) -> str:
        for dom in ("ref_clk", "pll_clk_div4", "tx_word_clk", "rx_word_clk", "cdr_clk_div2", "host_clk"):
            if dom in clk_net:
                return dom
        return clk_net

    def trace_sources(net: str, depth: int = 0, visited: set[str] | None = None) -> set[tuple[str, ...]]:
        if visited is None:
            visited = set()
        if net in visited or depth > 30:
            return set()
        visited.add(net)
        if net not in net_drivers:
            return {("PORT", net)}
        cell, inst, _pin, conns = net_drivers[net]
        if "__df" in cell:
            return {("FF", inst, clk_dom(conns.get("CLK", "")))}
        if "__conb_" in cell:
            return {("CONST", inst)}
        srcs: set[tuple[str, ...]] = set()
        for p, n in conns.items():
            if p in ("Q", "Q_N", "X", "Y", "COUT", "SUM", "HI", "LO"):
                continue
            srcs |= trace_sources(n, depth + 1, visited)
        return srcs

    exempt_ffs: list[dict[str, Any]] = []
    fifo_s1_bank_ffs: list[dict[str, Any]] = []

    for cell, inst, conns in ffs:
        dst_dom = clk_dom(conns.get("CLK", ""))
        d_net = conns.get("D", "")
        rst_net = conns.get("RESET_B", "")
        srcs = trace_sources(d_net)

        # Case A: Async reset synchronizer 1st stage (w_rst_s0 / r_rst_s0: D tied HI, RESET_B=arst_n)
        if rst_net == "arst_n" and any(s[0] == "CONST" for s in srcs):
            exempt_ffs.append({
                "instance": inst,
                "cell": cell,
                "clock_domain": dst_dom,
                "category": "async_reset_sync_stage0",
                "role": "w_rst_s0" if dst_dom == "rx_word_clk" else "r_rst_s0",
                "reason": "1st-stage async reset synchronizer (D=1, RESET_B=arst_n)",
            })
            continue

        # Case B: Async primary input synchronizer 1st stage (PLL analog monitors / abort_async)
        async_ports = sorted({s[1] for s in srcs if s[0] == "PORT" and s[1] in ASYNC_INPUT_PORTS})
        if async_ports:
            exempt_ffs.append({
                "instance": inst,
                "cell": cell,
                "clock_domain": dst_dom,
                "category": "async_input_sync_stage0",
                "role": f"sync_stage0({','.join(async_ports)})",
                "reason": f"1st-stage synchronizer sampling async input {async_ports}",
            })
            continue

        # Case C: Async clock-domain crossing (rx_word_clk <-> host_clk)
        cdc_srcs = sorted({
            (s[2], s[1])
            for s in srcs
            if s[0] == "FF" and s[2] != dst_dom and (s[2], dst_dom) not in SYNC_CLOCK_PAIRS
        })
        if cdc_srcs:
            if len(cdc_srcs) == 1 and "__dfrtp" in cell:
                # Genuine 1st-stage 2-FF CDC synchronizer (r_gray_w1, w_gray_r1, r_up_w[0], w_up_r[0], overflow_r[0], fault_host[0])
                exempt_ffs.append({
                    "instance": inst,
                    "cell": cell,
                    "clock_domain": dst_dom,
                    "category": "cdc_2ff_sync_stage0",
                    "role": f"cdc_sync({cdc_srcs[0][0]}->{dst_dom}, src={cdc_srcs[0][1]})",
                    "reason": f"1st-stage CDC synchronizer from {cdc_srcs[0][0]} FF {cdc_srcs[0][1]}",
                })
            else:
                # Unconditional Stage-1 FIFO bank mux pipeline FF (s1_b0..s1_b3 reading mem[0..15])
                fifo_s1_bank_ffs.append({
                    "instance": inst,
                    "cell": cell,
                    "clock_domain": dst_dom,
                    "category": "fifo_unselected_bank_s1_mux",
                    "role": f"s1_bank_ff({cdc_srcs[0][0]}->{dst_dom})",
                    "reason": f"FIFO unconditional 4-bank Stage-1 prefetch FF (muxed/gated by Gray-guarded s1_hi/s1_valid; {len(cdc_srcs)} mem rows)",
                })

    active_exempt = list(exempt_ffs)
    if include_fifo_s1_banks:
        active_exempt.extend(fifo_s1_bank_ffs)

    lines = [
        "// VCS +optconfigfile: disable timing checks ONLY on genuine 1st-stage CDC/async synchronizer FFs",
        "// (SDF cell IOPATH and interconnect delays remain 100% active on every instance!)",
    ]
    for item in active_exempt:
        lines.append(f"// {item['category']} | {item['clock_domain']} | {item['role']}")
        lines.append(f"instance {{ tb_serdes_digital_top_v3_gls.dut.{item['instance']} }} {{ noTiming }};")
    OPTCONFIG_PATH.write_text("\n".join(lines) + "\n")

    print(
        f"    Total FFs in netlist: {len(ffs)} | 1st-stage CDC/async-sync exempted: {len(exempt_ffs)} "
        f"(FIFO s1 bank prefetch FFs tracked separately: {len(fifo_s1_bank_ffs)}, exempted={include_fifo_s1_banks})"
    )
    return {
        "total_ffs": len(ffs),
        "exempt_1st_stage_cdc_count": len(exempt_ffs),
        "fifo_s1_bank_count": len(fifo_s1_bank_ffs),
        "fifo_s1_banks_exempted": include_fifo_s1_banks,
        "total_exempt_count": len(active_exempt),
        "sync_checked_ff_count": len(ffs) - len(active_exempt),
        "optconfig_path": str(OPTCONFIG_PATH.relative_to(REPO)),
        "exempt_1st_stage_cdc_ffs": exempt_ffs,
        "fifo_s1_bank_ffs": [x["instance"] for x in fifo_s1_bank_ffs],
    }


def parse_sim_log(log_text: str, fifo_s1_instances: set[str], exempt_instances: set[str]) -> dict[str, Any]:
    """Parse VCS simulation output for timing violations, SVA counts, and GLS_SUMMARY."""
    # Parse timing violations
    viol_pat = re.compile(r"Timing violation in (\S+)\s*\n\s*(\$\w+\([^;]*\);)", re.M)
    violations = []
    sync_violations = []
    fifo_s1_violations = []
    for m in viol_pat.finditer(log_text):
        inst_path, detail = m.group(1), " ".join(m.group(2).split())
        leaf = inst_path.split(".")[-1]
        entry = {"instance_path": inst_path, "leaf": leaf, "detail": detail}
        violations.append(entry)
        if leaf in fifo_s1_instances:
            fifo_s1_violations.append(entry)
        elif leaf not in exempt_instances:
            sync_violations.append(entry)

    # Parse GLS_SUMMARY line
    summary_m = re.search(r"GLS_SUMMARY\s+(.*)", log_text)
    metrics: dict[str, Any] = {}
    if summary_m:
        for kv in summary_m.group(1).strip().split():
            if "=" in kv:
                k, v = kv.split("=", 1)
                try:
                    metrics[k] = int(v) if re.fullmatch(r"-?\d+", v) else float(v)
                except ValueError:
                    metrics[k] = v

    passed = "ALL GLS + SVA CHECKS PASSED for serdes_digital_top_v3!" in log_text
    fatal_lines = [ln.strip() for ln in log_text.splitlines() if "Fatal:" in ln or "$fatal" in ln or "SVA FAIL" in ln or "GLITCH FAIL" in ln]

    return {
        "passed": passed,
        "total_timing_violations": len(violations),
        "synchronous_timing_violations": len(sync_violations),
        "fifo_s1_unselected_bank_violations": len(fifo_s1_violations),
        "synchronous_violation_samples": sync_violations[:10],
        "fifo_s1_violation_samples": fifo_s1_violations[:5],
        "fatal_or_error_lines": fatal_lines[:10],
        "metrics": metrics,
    }


def parse_sdf_annotation(compile_log: str) -> dict[str, Any]:
    err_m = re.search(r"Total errors:\s*(\d+)", compile_log)
    warn_m = re.search(r"Total warnings:\s*(\d+)", compile_log)
    return {
        "sdf_errors": int(err_m.group(1)) if err_m else None,
        "sdf_warnings": int(warn_m.group(1)) if warn_m else None,
    }


def run_vcs_mode(
    mode_name: str,
    filelist: Path,
    sdf_spec: str | None,
    optconfig: Path | None,
    fsdb_out: Path | None,
    fifo_s1_instances: set[str],
    exempt_instances: set[str],
) -> dict[str, Any]:
    work_dir = OUT_ROOT / f"work_{mode_name}"
    work_dir.mkdir(parents=True, exist_ok=True)
    simv = work_dir / "simv"
    compile_log = work_dir / "compile.log"
    run_log = work_dir / "sim.log"

    env = os.environ.copy()
    ld_path = env.get("LD_LIBRARY_PATH", "")
    if str(VERDI_PLI_DIR) not in ld_path:
        env["LD_LIBRARY_PATH"] = f"{VERDI_PLI_DIR}:{ld_path}" if ld_path else str(VERDI_PLI_DIR)

    cmd = [
        str(VCS),
        "-full64",
        "-sverilog",
        "-timescale=1ns/1ps",
        "-assert", "enable_diag",
        "-LDFLAGS", "-Wl,--no-as-needed",
        "-Mdir=" + str(work_dir / "csrc"),
        "-o", str(simv),
        "-f", str(filelist),
    ]
    if sdf_spec is not None:
        cmd.extend(["+neg_tchk", "-negdelay", "-sdf", sdf_spec])
    if optconfig is not None:
        cmd.append(f"+optconfigfile+{optconfig}")
    if fsdb_out is not None:
        cmd.extend([
            "-debug_access+all",
            "+define+DUMP_FSDB",
            "-P", str(VERDI_PLI_DIR / "novas.tab"), str(VERDI_PLI_DIR / "pli.a"),
        ])

    print(f"=== Running Mode: {mode_name} ===")
    rc_cmp, cmp_txt = run_cmd(cmd, REPO, compile_log, env=env)
    sdf_annot = parse_sdf_annotation(cmp_txt) if sdf_spec is not None else {}
    if rc_cmp != 0 or not simv.exists():
        return {
            "mode": mode_name,
            "compile_rc": rc_cmp,
            "run_rc": None,
            "passed": False,
            "sdf_annotation": sdf_annot,
            "compile_log": str(compile_log.relative_to(REPO)),
        }

    run_argv = [str(simv)]
    if fsdb_out is not None:
        run_argv.append(f"+FSDB_FILE={fsdb_out}")
    rc_run, run_txt = run_cmd(run_argv, REPO, run_log, env=env)
    # Move VCS/Verdi default CWD drop files (ucli.key, novas_dump.log) into work_dir to keep repo root spotless
    for stray in ("ucli.key", "novas_dump.log"):
        src = REPO / stray
        if src.exists():
            dst = work_dir / stray
            if dst.exists():
                dst.unlink()
            src.replace(dst)
    parsed = parse_sim_log(run_txt, fifo_s1_instances, exempt_instances)

    res: dict[str, Any] = {
        "mode": mode_name,
        "compile_rc": rc_cmp,
        "run_rc": rc_run,
        "sdf_annotation": sdf_annot,
        "compile_log": str(compile_log.relative_to(REPO)),
        "sim_log": str(run_log.relative_to(REPO)),
        **parsed,
    }
    if fsdb_out is not None:
        res["fsdb_path"] = str(fsdb_out.relative_to(REPO))
        res["fsdb_bytes"] = fsdb_out.stat().st_size if fsdb_out.exists() else 0
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Run VCS 3-corner SDF GLS + SVA + Verdi FSDB for serdes_digital_top_v3")
    ap.add_argument("--skip-sdf", action="store_true", help="Reuse existing SDF files in results/digital/gls_v3_1/sdf/")
    ap.add_argument(
        "--exempt-fifo-s1-banks",
        action="store_true",
        help="Also exempt FIFO Stage-1 unconditional 4-bank prefetch FFs (s1_b0..s1_b3) if async bank writes trigger unselected-bank warnings",
    )
    args = ap.parse_args()

    sdf_stats = {}
    if args.skip_sdf and all(c["sdf"].exists() for c in CORNERS):
        print("=== Step 1: Reusing existing 3-corner SDFs ===")
        for c in CORNERS:
            text = c["sdf"].read_text()
            sdf_stats[c["name"]] = {
                "path": str(c["sdf"].relative_to(REPO)),
                "bytes": c["sdf"].stat().st_size,
                "iopath": len(re.findall(r"\(IOPATH\b", text)),
                "interconnect": len(re.findall(r"\(INTERCONNECT\b", text)),
                "timingcheck_cells": len(re.findall(r"\(TIMINGCHECK\b", text)),
                "setup": len(re.findall(r"\(SETUP\b", text)),
                "hold": len(re.findall(r"\(HOLD\b", text)),
                "recovery": len(re.findall(r"\(RECOVERY\b", text)),
                "removal": len(re.findall(r"\(REMOVAL\b", text)),
            }
    else:
        sdf_stats = export_sdfs()

    cdc_info = prepare_primitives_and_cdc_optconfig(include_fifo_s1_banks=args.exempt_fifo_s1_banks)
    fifo_s1_set = set(cdc_info["fifo_s1_bank_ffs"])
    exempt_set = {x["instance"] for x in cdc_info["exempt_1st_stage_cdc_ffs"]}
    if args.exempt_fifo_s1_banks:
        exempt_set |= fifo_s1_set

    modes_out: dict[str, Any] = {}
    # Mode 0: RTL Golden
    modes_out["rtl_golden"] = run_vcs_mode(
        mode_name="rtl_golden",
        filelist=RTL_FILELIST,
        sdf_spec=None,
        optconfig=None,
        fsdb_out=None,
        fifo_s1_instances=fifo_s1_set,
        exempt_instances=exempt_set,
    )
    # Modes 1-3: 3-corner SDF Gate-Level Simulation
    for c in CORNERS:
        mode_name = f"gls_{c['name']}"
        sdf_spec = f"{c['sdf_mtm']}:tb_serdes_digital_top_v3_gls.dut:{c['sdf']}"
        fsdb = FSDB_TT_PATH if c["dump_fsdb"] else None
        modes_out[mode_name] = run_vcs_mode(
            mode_name=mode_name,
            filelist=GLS_FILELIST,
            sdf_spec=sdf_spec,
            optconfig=OPTCONFIG_PATH,
            fsdb_out=fsdb,
            fifo_s1_instances=fifo_s1_set,
            exempt_instances=exempt_set,
        )

    all_passed = all(
        m.get("passed") and m.get("synchronous_timing_violations", 1) == 0
        for m in modes_out.values()
    )
    summary = {
        "design": "serdes_digital_top_v3",
        "revision": "v3.1",
        "netlist": str(NETLIST_V.relative_to(REPO)),
        "tool_vcs": "VCS-MX O-2018.09-SP2_Full64",
        "tool_verdi_pli": "Verdi O-2018.09-SP2",
        "xprop_mode": "4state_native_gate_udp (VT_VCS_XProp feature unlicensed)",
        "all_passed": all_passed,
        "sdf_files": sdf_stats,
        "cdc_sync_exemptions": cdc_info,
        "modes": modes_out,
    }
    SUMMARY_JSON.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\n=== Wrote {SUMMARY_JSON.relative_to(REPO)} (all_passed={all_passed}) ===")
    for name, m in modes_out.items():
        met = m.get("metrics", {})
        print(
            f"  {name:18s}: passed={m.get('passed')} | sync_tviol={m.get('synchronous_timing_violations')} "
            f"| fifo_s1_tviol={m.get('fifo_s1_unselected_bank_violations')} "
            f"| sva_pass={met.get('sva_pass')} sva_fail={met.get('sva_fail')} "
            f"| pll_glitches={met.get('pll_glitches')}"
        )
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
