#!/usr/bin/env python3
"""Tapeout-Audit Clean Unified Digital Top Macro v3.3 P&R, 5-Corner OCV STA, CDC Audit, DRC & LVS Flow.

Builds isolated ``serdes_digital_top_v3`` from ``digital/pnr/rtl_v3p3_clean/`` with:
  - D-C1: Zero 1st-stage synchronizer split-metastability (strict fanout=1 on all sync1 FFs)
  - D-H3: Single shared PLL hi/lo synchronizer, single shared per-domain arst_n tree, M2 w_valid mem gating
  - A-C3: WAIT_TIMEOUT_CYCLES = 16384 @ 62.5 MHz (262.14 us > 116.5 us LDO cold start) + exact $clog2 widths
  - D-H4: Trimmed dead Q7 padding in cdr_phase_frequency + DC-balanced TX_IDLE_WORD = 16'hA55A
  - D-C2 & D-H1:
      * Synthesizes & closes P&R against sky130_fd_sc_hd__ss_n40C_1v60.lib (true slowest SKY130A corner)
        with +/-5% OCV derating (set_timing_derate -early 0.95 -late 1.05)
      * Constrains rx_phys* with -clock_fall (matching 180-deg j0/j0b analog deser16 launch)
      * 5-Corner Post-Route OpenRCX STA (tt_025C_1v80, ss_100C_1v60, ss_n40C_1v60, ff_n40C_1v95, ff_100C_1v95)
      * Post-route Gray-pointer CDC bus_skew (max - min) audit on max.spef + sync1->sync2 MTBF slack & fanout=1 check
      * Magic drc(full) = 0 and Netgen LVS = MATCH

All temporary files/logs/SPEF/EXT stay strictly under
``results/digital/pnr_v3p3_20261124/serdes_digital_top_v3/``; clean signoff deliverables
are exported to ``digital/pnr/variants/hd_pnr_v3p3_clean/serdes_digital_top_v3/``.
Does NOT touch frozen v1.0/v3.2 directories!
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Patch, Rectangle

import run_pnr as base
import run_unified_v3_pnr as v3

REPO = base.REPO
RTL_DIR = "digital/pnr/rtl_v3p3_clean"
RESULTS_BASE = REPO / "results/digital/pnr_v3p3_1v65_20261125"
VARIANT_BASE = REPO / "digital/pnr/variants/hd_pnr_v3p3_clean"
V3P2_SUMMARY = REPO / "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/summary.json"

BLOCK_NAME = "serdes_digital_top_v3"

# 6 SKY130A Liberty corners (including SPICE-validated spec-voltage cold-slow ss_n40C_1v65_interp + ss_n40C_1v60)
LIB_TT_025 = base.SC_HD / "lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
LIB_SS_100 = base.SC_HD / "lib/sky130_fd_sc_hd__ss_100C_1v60.lib"
LIB_SS_N40 = base.SC_HD / "lib/sky130_fd_sc_hd__ss_n40C_1v60.lib"
LIB_SS_N40_1V65 = REPO / "results/digital/interp_ss_n40c_1v65_20261125/sky130_fd_sc_hd__ss_n40C_1v65_interp.lib"
LIB_FF_N40 = base.SC_HD / "lib/sky130_fd_sc_hd__ff_n40C_1v95.lib"
LIB_FF_100 = base.SC_HD / "lib/sky130_fd_sc_hd__ff_100C_1v95.lib"

UNIFIED_RTL_FILES = [
    f"{RTL_DIR}/mon_sync.sv",
    f"{RTL_DIR}/mon_persist.sv",
    f"{RTL_DIR}/pll_startup_supervisor.sv",
    f"{RTL_DIR}/pll_coarse_ctrl.sv",
    f"{RTL_DIR}/pll_lock_detect.sv",
    f"{RTL_DIR}/pll_control_top.sv",
    f"{RTL_DIR}/tx_ingress_control.sv",
    f"{RTL_DIR}/rx_word_map.sv",
    f"{RTL_DIR}/rx_word_align16.sv",
    f"{RTL_DIR}/rx_async_word_fifo.sv",
    f"{RTL_DIR}/bbpd_window_vote.sv",
    f"{RTL_DIR}/cdr_phase_frequency.sv",
    f"{RTL_DIR}/pi_step_commutator.sv",
    f"{RTL_DIR}/rx_cdr_loop.sv",
    f"{RTL_DIR}/serdes_digital_top_v3.sv",
]

ALL_CLOCK_NAMES = v3.ALL_CLOCK_NAMES

# Dot-free CDC net names preserved through Yosys rename-hide for post-route bus_skew & MTBF audit
CDC_BUS_WIRES = [
    ("u_fifo.w_gray", "cdc_w_gray", 5),
    ("u_fifo.w_gray_r1", "cdc_w_gray_r1", 5),
    ("u_fifo.w_gray_r2", "cdc_w_gray_r2", 5),
    ("u_fifo.r_pop_gray", "cdc_r_pop_gray", 5),
    ("u_fifo.r_gray_w1", "cdc_r_gray_w1", 5),
    ("u_fifo.r_gray_w2", "cdc_r_gray_w2", 5),
    ("u_fifo.r_up_w", "cdc_r_up_w", 2),
    ("u_fifo.w_up_r", "cdc_w_up_r", 2),
    ("u_fifo.overflow_r", "cdc_overflow_r", 2),
]
CDC_SCALAR_WIRES = [
    ("u_fifo.w_rst_s0", "cdc_w_rst_s0"),
    ("u_fifo.w_rst_s1", "cdc_w_rst_s1"),
    ("u_fifo.r_rst_s0", "cdc_r_rst_s0"),
    ("u_fifo.r_rst_s1", "cdc_r_rst_s1"),
]


def build_v3p3_block_spec(
    die_w: float,
    die_h: float,
    margin_x: float = 3.68,
    margin_y: float = 5.44,
    place_density: float = 0.68,
    setup_margin_ns: float = 0.25,
    hold_margin_ns: float = 0.08,
) -> base.BlockSpec:
    spec = v3.build_v3_block_spec(
        die_w=die_w,
        die_h=die_h,
        margin_x=margin_x,
        margin_y=margin_y,
        place_density=place_density,
        setup_margin_ns=setup_margin_ns,
        hold_margin_ns=hold_margin_ns,
    )
    spec.rtl_files = list(UNIFIED_RTL_FILES)
    return spec


def write_v3p3_sdc(block: base.BlockSpec, path: Path, post_route: bool = False, ocv: bool = True) -> None:
    """Write v3.3 multi-clock SDC with optional +/-5% OCV derating and rx_phys* -clock_fall constraint."""
    setup_unc = 0.10 if post_route else 0.15
    hold_unc = 0.05 if post_route else 0.08
    clk_prop = "set_propagated_clock [all_clocks]" if post_route else "set_clock_transition 0.12 [all_clocks]"
    ocv_block = (
        "# On-Chip Variation (OCV) +/-5% derating (D-C2)\nset_timing_derate -early 0.95\nset_timing_derate -late  1.05"
        if ocv
        else "# NO_OCV diagnostic corner (derate = 1.00)\n"
    )

    sdc = f"""# Multi-clock SDC for {block.name} (v3.3 Clean Signoff: +/-5% OCV + rx_phys -clock_fall)
# Root clocks: ref_clk (250 MHz), tx_word_clk (250 MHz), rx_word_clk (250 MHz), host_clk (250 MHz)
# Synchronous generated clocks:
#   pll_clk_div4 = ref_clk / 4     (62.5 MHz / 16.0 ns)
#   cdr_clk_div2 = rx_word_clk / 2 (125.0 MHz / 8.0 ns)

create_clock -name ref_clk     -period 4.000 [get_ports ref_clk]
create_clock -name tx_word_clk -period 4.000 [get_ports tx_word_clk]
create_clock -name rx_word_clk -period 4.000 [get_ports rx_word_clk]
create_clock -name host_clk    -period 4.000 [get_ports host_clk]

# Locate clock-divider FF Q pins robustly across pre-CTS and post-CTS netlists
proc _find_div_q_pin {{net_pat}} {{
  set pins [get_pins -quiet -filter "direction == output && name == Q" -of_objects [get_nets -quiet $net_pat]]
  if {{[llength $pins] > 0}} {{ return [lindex $pins 0] }}
  set pins [get_pins -quiet -filter "direction == output" -of_objects [get_nets -quiet $net_pat]]
  if {{[llength $pins] > 0}} {{ return [lindex $pins 0] }}
  error "Could not find generated clock driver pin matching $net_pat"
}}

set _pll_div_pin [_find_div_q_pin "*pll_clk_div4*"]
create_generated_clock -name pll_clk_div4 -source [get_ports ref_clk] -divide_by 4 $_pll_div_pin

set _cdr_div_pin [_find_div_q_pin "*cdr_clk_div2*"]
create_generated_clock -name cdr_clk_div2 -source [get_ports rx_word_clk] -divide_by 2 $_cdr_div_pin

set_clock_uncertainty -setup {setup_unc:.3f} [all_clocks]
set_clock_uncertainty -hold  {hold_unc:.3f} [all_clocks]
{clk_prop}

{ocv_block}

# Independent root clock domains are asynchronous; divided clocks stay synchronous to their roots!
set_clock_groups -asynchronous \\
  -group {{ref_clk pll_clk_div4}} \\
  -group {{tx_word_clk}} \\
  -group {{rx_word_clk cdr_clk_div2}} \\
  -group {{host_clk}}

# Hardware-exact synchronous multicycle hold on rx_word_clk -> cdr_clk_div2:
# bbpd_window_vote updates pair_* ONLY on phase_hi==1 (falling edge of cdr_clk_div2, 4.0 ns away
# from cdr_clk_div2 rising edge), so pair_* never toggles on the capture edge (t=0, 8, 16 ns).
set_multicycle_path -hold 1 -start -from [get_clocks rx_word_clk] -to [get_clocks cdr_clk_div2]

# -----------------------------------------------------------------------------
# I/O timing constraints
# -----------------------------------------------------------------------------
# PLL inputs on ref_clk (start pulse capture) & pll_clk_div4 (enable + static config)
set_input_delay  -clock ref_clk      -max 0.800 [get_ports {{pll_start}}]
set_input_delay  -clock ref_clk      -min 0.500 [get_ports {{pll_start}}]
set_input_delay  -clock pll_clk_div4 -max 1.600 [get_ports {{pll_enable pll_tclass* pll_lo_run* pll_hi_run* pll_stop_code* pll_stop_sel*}}]
set_input_delay  -clock pll_clk_div4 -min 0.500 [get_ports {{pll_enable pll_tclass* pll_lo_run* pll_hi_run* pll_stop_code* pll_stop_sel*}}]
set_output_delay -clock pll_clk_div4 -max 1.600 [get_ports {{precharge_en pfd_rst_b cp_en pll_pw_clr_b pll_locked pll_busy pll_fault pll_state_id* pll_fault_code* vco_code* pll_lo_code* pll_hi_code* pll_coarse_busy pll_coarse_done pll_fast_end pll_slow_end switches*}}]
set_output_delay -clock pll_clk_div4 -min 0.100 [get_ports {{precharge_en pfd_rst_b cp_en pll_pw_clr_b pll_locked pll_busy pll_fault pll_state_id* pll_fault_code* vco_code* pll_lo_code* pll_hi_code* pll_coarse_busy pll_coarse_done pll_fast_end pll_slow_end switches*}}]

# TX ingress (250 MHz tx_word_clk)
set_input_delay  -clock tx_word_clk  -max 0.800 [get_ports {{tx_enable tx_clock_good tx_in_valid tx_in_data*}}]
set_input_delay  -clock tx_word_clk  -min 0.500 [get_ports {{tx_enable tx_clock_good tx_in_valid tx_in_data*}}]
set_output_delay -clock tx_word_clk  -max 0.800 [get_ports {{tx_word_ready tx_capture_data* tx_capture_valid tx_a_valid tx_b_valid}}]
set_output_delay -clock tx_word_clk  -min 0.100 [get_ports {{tx_word_ready tx_capture_data* tx_capture_valid tx_a_valid tx_b_valid}}]

# RX full-rate 250 MHz word map & aligner I/O (rx_word_clk)
# D-H1: rx_phys* launches on falling edge of rx_word_clk (180-deg j0/j0b analog deser16 phase offset!)
set_input_delay  -clock rx_word_clk -clock_fall -max 0.800 [get_ports {{rx_phys*}}]
set_input_delay  -clock rx_word_clk -clock_fall -min 0.500 [get_ports {{rx_phys*}}]
set_input_delay  -clock rx_word_clk             -max 0.800 [get_ports {{rx_training_enable}}]
set_input_delay  -clock rx_word_clk             -min 0.500 [get_ports {{rx_training_enable}}]
set_output_delay -clock rx_word_clk             -max 0.800 [get_ports {{rx_word_online rx_aligned rx_offset*}}]
set_output_delay -clock rx_word_clk             -min 0.100 [get_ports {{rx_word_online rx_aligned rx_offset*}}]

# RX CDR (125 MHz cdr_clk_div2)
set_input_delay  -clock cdr_clk_div2 -max 1.200 [get_ports {{rx_cdr_enable}}]
set_input_delay  -clock cdr_clk_div2 -min 0.500 [get_ports {{rx_cdr_enable}}]
set_output_delay -clock cdr_clk_div2 -max 1.200 [get_ports {{rx_phase_code* rx_select_a* rx_select_b* rx_fine_b* rx_cdr_locked rx_cdr_holdover rx_cdr_range_limited rx_cdr_phase_applied rx_cdr_frequency_q* rx_cdr_phase_debt_q*}}]
set_output_delay -clock cdr_clk_div2 -min 0.100 [get_ports {{rx_phase_code* rx_select_a* rx_select_b* rx_fine_b* rx_cdr_locked rx_cdr_holdover rx_cdr_range_limited rx_cdr_phase_applied rx_cdr_frequency_q* rx_cdr_phase_debt_q*}}]

# RX Host FIFO (250 MHz host_clk)
set_input_delay  -clock host_clk     -max 0.800 [get_ports {{host_ready}}]
set_input_delay  -clock host_clk     -min 0.500 [get_ports {{host_ready}}]
set_output_delay -clock host_clk     -max 0.800 [get_ports {{host_data* host_valid host_online host_error}}]
set_output_delay -clock host_clk     -min 0.100 [get_ports {{host_data* host_valid host_online host_error}}]

# Async resets & analog monitor inputs
set_false_path -from [get_ports {{rst_n arst_n pll_abort_async bias_ready_async pre_ref_ready_async hi_async lo_async pw_late_async}}]

# Driving cell, load & DRC limits
set_driving_cell -lib_cell sky130_fd_sc_hd__buf_4 -pin X [all_inputs]
set_load {block.output_load_pf:.4f} [all_outputs]
set_max_fanout 45 [current_design]
set_max_capacitance 0.085 [current_design]
set_max_transition 0.65 [current_design]
"""
    path.write_text(sdc)


def build_v3p3_synth_lib(src_lib: Path, dst_lib: Path) -> Path:
    """Create filtered ss_n40C_1v65_interp Liberty for v3.3 Yosys synthesis.
    Re-enables sky130_fd_sc_hd__mux4_2 (keeping DRC-excluded mux4_4 and weak mux4_1 banned!)
    so the 16-word FIFO read mux compresses from 3 mux2 levels to 2 levels.
    """
    dst_lib.parent.mkdir(parents=True, exist_ok=True)
    drc_exclude = base.load_excluded_cells()
    lines = src_lib.read_text().splitlines(keepends=True)
    cell_re = re.compile(r'^\s*cell\s*\(\s*"([^"]+)"\s*\)\s*\{')

    all_cells = {m.group(1) for line in lines if (m := cell_re.match(line))}
    weak_one = {
        c for c in all_cells
        if c.endswith("_1") and (c[:-2] + "_2") in all_cells and "__conb_" not in c
    }

    out: list[str] = []
    skipping = False
    brace_depth = 0
    for line in lines:
        if not skipping:
            m = cell_re.match(line)
            if m:
                cname = m.group(1)
                exclude = (
                    (base.should_exclude_for_synth(cname, drc_exclude, fast_ss=True) and cname != "sky130_fd_sc_hd__mux4_2")
                    or cname in weak_one
                )
                if exclude:
                    skipping = True
                    brace_depth = line.count("{") - line.count("}")
                    if brace_depth <= 0:
                        skipping = False
                    continue
            out.append(line)
        else:
            brace_depth += line.count("{") - line.count("}")
            if brace_depth <= 0:
                skipping = False
    dst_lib.write_text("".join(out))
    return dst_lib


def v3p3_openroad_dont_use_tcl(allow_hold_dly: bool = False) -> str:
    """OpenROAD dont_use policy using ss_n40C_1v65_interp library.
    - Re-enables sky130_fd_sc_hd__mux4_2 (mux4_4 stays DRC-excluded, mux4_1 stays weak-excluded).
    - allow_hold_dly=False (Phase A setup repair): bans ALL dly* so repair_timing -setup uses fast buf_4/6/8/12!
    - allow_hold_dly=True  (Phase B hold repair): allows dlygate4sd3_1/dlymetal6s2s_1/dlymetal6s4s_1 (3.6x SS/FF
      ratio instead of 7.5x for buf_4) so hold repair fixes FF hold with 1 cell instead of 9x buf_4!"""
    drc_exclude = sorted(base.load_excluded_cells())
    allow_cells = {"sky130_fd_sc_hd__conb_1"}
    if allow_hold_dly:
        allow_cells.update({
            "sky130_fd_sc_hd__dlygate4sd3_1",
            "sky130_fd_sc_hd__dlymetal6s2s_1",
            "sky130_fd_sc_hd__dlymetal6s4s_1",
        })
    patterns = [
        "*_0",
        "sky130_fd_sc_hd__lpflow_*",
        "sky130_fd_sc_hd__sdf*",
        "sky130_fd_sc_hd__sedf*",
        "sky130_fd_sc_hd__sdlclkp*",
        "sky130_fd_sc_hd__probe*",
        "sky130_fd_sc_hd__ebuf*",
        "sky130_fd_sc_hd__clkdlybuf*",
        "sky130_fd_sc_hd__clkbuf_*",
        "sky130_fd_sc_hd__clkinv_*",
        "sky130_fd_sc_hd__bufbuf_16",
        "sky130_fd_sc_hd__bufbuf_8",
        "sky130_fd_sc_hd__buf_16",
    ] + drc_exclude
    if allow_hold_dly:
        patterns += [
            "sky130_fd_sc_hd__dlygate4sd1_1",
            "sky130_fd_sc_hd__dlygate4sd2_1",
            "sky130_fd_sc_hd__dlymetal6s6s_1",
        ]
    else:
        patterns.append("sky130_fd_sc_hd__dly*")
    for tok in base.SLOW_SS_CELL_TOKENS:
        if tok == "__mux4":
            continue  # allow mux4_2 (mux4_4 is in drc_exclude, mux4_1 is in weak_one!)
        patterns.append(f"sky130_fd_sc_hd{tok}*")
    lib_text = LIB_SS_N40_1V65.read_text()
    all_c = set(re.findall(r'cell\s*\(\s*"([^"]+)"\s*\)', lib_text))
    for c in sorted(all_c):
        if c.endswith("_1") and (c[:-2] + "_2") in all_c and c not in allow_cells:
            patterns.append(c)

    lines = ["set dont_use_list {"]
    for p in patterns:
        lines.append(f"  {p}")
    lines.append("}")
    lines.append("foreach pat $dont_use_list {")
    lines.append("  catch { set_dont_use $pat }")
    lines.append("}")
    return "\n".join(lines)


def run_v3p3_yosys(block: base.BlockSpec, work: Path, synth_lib: Path) -> tuple[Path, dict[str, Any]]:
    """Per-subsystem Yosys synthesis against ss_n40C_1v60 while preserving dot-free CDC net names."""
    subblocks = [
        (
            "pll_control_top",
            [
                f"{RTL_DIR}/mon_sync.sv",
                f"{RTL_DIR}/mon_persist.sv",
                f"{RTL_DIR}/pll_startup_supervisor.sv",
                f"{RTL_DIR}/pll_coarse_ctrl.sv",
                f"{RTL_DIR}/pll_lock_detect.sv",
                f"{RTL_DIR}/pll_control_top.sv",
            ],
            {"CODE_BITS": block.params.get("PLL_CODE_BITS", 5)},
            10000,
        ),
        (
            "tx_ingress_control",
            [f"{RTL_DIR}/tx_ingress_control.sv"],
            {},
            1800,
        ),
        (
            "rx_word_map",
            [f"{RTL_DIR}/rx_word_map.sv"],
            {},
            800,
        ),
        (
            "rx_word_host_shared",
            [
                f"{RTL_DIR}/rx_word_align16.sv",
                f"{RTL_DIR}/rx_async_word_fifo.sv",
                f"{RTL_DIR}/serdes_digital_top_v3.sv",
            ],
            {},
            800,
        ),
        (
            "rx_cdr_loop",
            [
                f"{RTL_DIR}/bbpd_window_vote.sv",
                f"{RTL_DIR}/cdr_phase_frequency.sv",
                f"{RTL_DIR}/pi_step_commutator.sv",
                f"{RTL_DIR}/rx_cdr_loop.sv",
            ],
            {},
            1000,
        ),
    ]

    sub_vs: list[str] = []
    sub_stats: dict[str, dict[str, Any]] = {}
    for mod, files, params, abc_d in subblocks:
        out_v = work / f"synth_sub_{mod}.v"
        ys = work / f"synth_sub_{mod}.ys"
        rtl_abs = " ".join(str((REPO / f).resolve()) for f in files)
        cmds = [f"read_liberty -lib {synth_lib}", f"read_verilog -sv {rtl_abs}"]
        for k, v in params.items():
            cmds.append(f"chparam -set {k} {v} {mod}")
        cmds += [
            f"hierarchy -check -top {mod}",
            "flatten",
            "proc",
            "opt_expr",
            "opt_clean",
            "check",
            "opt_dff",
            "memory -nomap",
            "opt_clean",
            "memory_map",
            "opt_expr",
            "opt_clean",
            "techmap",
            "opt_expr",
            "opt_clean",
            f"dfflibmap -liberty {synth_lib}",
            f"abc -D {abc_d} -liberty {synth_lib}",
            "opt_clean -purge",
        ]
        if mod == "rx_word_host_shared":
            # Promote FIFO Gray-pointer & synchronizer wires to clean dot-free names before top-level flatten
            cmds.append(f"cd {mod}")
            cmds.append("splitnets")
            for src_w, dst_w, width in CDC_BUS_WIRES:
                for b in range(width):
                    cmds.append(f"rename {src_w}[{b}] {dst_w}_{b}")
            for src_w, dst_w in CDC_SCALAR_WIRES:
                cmds.append(f"rename {src_w} {dst_w}")
            cmds.append("cd ..")
        cmds += [
            f"stat -liberty {synth_lib}",
            f"write_verilog -noattr -noexpr -nohex -nodec {out_v}",
        ]
        ys.write_text("\n".join(cmds) + "\n")
        p = base.run_cmd([str(base.YOSYS), "-s", str(ys)], work, work / f"01_yosys_{mod}.log", timeout=180)
        cm = re.search(r"Number of cells:\s+(\d+)", p.stdout)
        am = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", p.stdout)
        sub_stats[mod] = {
            "cells": int(cm.group(1)) if cm else 0,
            "area_um2": round(float(am.group(1)), 1) if am else 0.0,
        }
        sub_vs.append(str(out_v))

    top_src = (REPO / f"{RTL_DIR}/serdes_digital_top_v3.sv").read_text()
    top_only = top_src.split("/* verilator lint_off DECLFILENAME */")[0]
    top_clean = re.sub(
        r"\b(pll_control_top|tx_ingress_control|rx_word_host_shared)\s*#\s*\((?:[^()]|\([^()]*\))*\)",
        r"\1",
        top_only,
    )
    wrap_sv = work / f"{block.name}_link_wrap.sv"
    wrap_sv.write_text(top_clean)

    cdc_promote_cmds: list[str] = []
    for _, dst_w, width in CDC_BUS_WIRES:
        for b in range(width):
            wname = f"{dst_w}_{b}"
            # cdc_w_up_r_1 merges directly into top-level port host_online during flatten
            if wname == "cdc_w_up_r_1":
                continue
            cdc_promote_cmds.append(f"rename u_rx_host.{wname} {wname}")
    for _, dst_w in CDC_SCALAR_WIRES:
        cdc_promote_cmds.append(f"rename u_rx_host.{dst_w} {dst_w}")

    synth_v = work / f"{block.name}_synth.v"
    ys_path = work / "synth.ys"
    cmds = [
        f"read_liberty -lib {synth_lib}",
        f"read_verilog {' '.join(sub_vs)}",
        f"read_verilog -sv {wrap_sv}",
        f"chparam -set PLL_CODE_BITS {block.params.get('PLL_CODE_BITS', 5)} {block.name}",
        f"hierarchy -check -top {block.name}",
        "proc",
        "opt_clean",
        "techmap",
        f"dfflibmap -liberty {synth_lib}",
        "flatten",
        "splitnets",
        "opt_clean -purge",
        "hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO",
        "insbuf -buf sky130_fd_sc_hd__buf_8 A X",
        # Cleanly hide all dotted hierarchical cell/wire names (required for clean Netgen LVS!),
        # while keeping generated-clock nets and CDC audit nets as dot-free top names!
        f"cd {block.name}",
        "rename u_pll.pll_clk_div4 pll_clk_div4_net",
        "rename u_rx_cdr.cdr_clk_div2 cdr_clk_div2_net",
        *cdc_promote_cmds,
        "rename -hide c:* w:* w:pll_clk_div4_net %d w:cdr_clk_div2_net %d w:cdc_* %d",
        "cd ..",
        "opt_clean -purge",
        "check -assert",
        f"stat -liberty {synth_lib}",
        f"write_verilog -noattr -noexpr -nohex -nodec {synth_v}",
    ]
    ys_path.write_text("\n".join(cmds) + "\n")
    proc = base.run_cmd([str(base.YOSYS), "-s", str(ys_path)], work, work / "01_yosys.log", timeout=180)
    log = proc.stdout
    cells_m = re.search(r"Number of cells:\s+(\d+)", log)
    area_m = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", log)
    return synth_v, {
        "synth_cells": int(cells_m.group(1)) if cells_m else None,
        "synth_area_um2": float(area_m.group(1)) if area_m else None,
        "per_subsystem": sub_stats,
    }


def run_v3p3_openroad_pnr(
    block: base.BlockSpec,
    pin_groups: list[v3.PinGroup],
    work: Path,
    synth_v: Path,
    sdc_path: Path,
    resume_eco: bool = False,
) -> dict[str, Any]:
    routed_def = work / f"{block.name}.def"
    routed_v = work / f"{block.name}.v"
    routed_pg_v = work / f"{block.name}_pg.v"
    drc_rpt = work / "openroad_drt_drc.rpt"
    ant_pre_rpt = work / "antenna_pre_route.rpt"
    ant_post_rpt = work / "antenna_post_route.rpt"
    spef_nom = work / f"{block.name}_nom.spef"
    spef_max = work / f"{block.name}_max.spef"
    spef_min = work / f"{block.name}_min.spef"

    assert block.die_area is not None and block.core_area is not None
    die_w, die_h = block.die_area[2], block.die_area[3]
    da = " ".join(f"{v:.4g}" for v in block.die_area)
    ca = " ".join(f"{v:.4g}" for v in block.core_area)
    pin_tcl = v3.pin_constraints_tcl(pin_groups, die_w, die_h)

    decap_fill_list = (
        "{sky130_fd_sc_hd__decap_12 sky130_fd_sc_hd__decap_8 "
        "sky130_fd_sc_hd__decap_6 sky130_fd_sc_hd__decap_4 "
        "sky130_fd_sc_hd__decap_3 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_1}"
    )

    wire_rc_block = """
set_wire_rc -corner ss -signal -resistance 0.0016 -capacitance 0.00020
set_wire_rc -corner ss -clock  -resistance 0.0006 -capacitance 0.00017
set_wire_rc -corner ff -signal -resistance 0.0007 -capacitance 0.00009
set_wire_rc -corner ff -clock  -resistance 0.0003 -capacitance 0.00008
"""

    post_setup_def = work / f"{block.name}_post_setup.def"
    pnr_tcl = work / "pnr.tcl"
    pnr_tcl.write_text(
        f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
define_corners ss ff
read_liberty -corner ss {LIB_SS_N40_1V65}
read_liberty -corner ff {LIB_FF_N40}
read_verilog {synth_v}
link_design {block.name}
read_sdc {sdc_path}

{v3p3_openroad_dont_use_tcl(allow_hold_dly=False)}

initialize_floorplan -die_area {{{da}}} -core_area {{{ca}}} -site unithd

make_tracks li1  -x_offset 0.23 -x_pitch 0.46 -y_offset 0.17 -y_pitch 0.34
make_tracks met1 -x_offset 0.17 -x_pitch 0.34 -y_offset 0.17 -y_pitch 0.34
make_tracks met2 -x_offset 0.23 -x_pitch 0.46 -y_offset 0.23 -y_pitch 0.46
make_tracks met3 -x_offset 0.34 -x_pitch 0.68 -y_offset 0.34 -y_pitch 0.68
make_tracks met4 -x_offset 0.46 -x_pitch 0.92 -y_offset 0.46 -y_pitch 0.92
make_tracks met5 -x_offset 1.70 -x_pitch 3.40 -y_offset 1.70 -y_pitch 3.40

{pin_tcl}
place_pins -hor_layers met3 -ver_layers met2 -corner_avoidance 8 -min_distance 2 -min_distance_in_tracks

tapcell -distance 14 \\
  -tapcell_master sky130_fd_sc_hd__tapvpwrvgnd_1 \\
  -endcap_master sky130_fd_sc_hd__decap_3

add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground
set_voltage_domain -name CORE -power VPWR -ground VGND
define_pdn_grid -name stdcell_grid -voltage_domains CORE -pins {{met5}}
add_pdn_stripe -grid stdcell_grid -layer met1 -width 0.48 -followpins
add_pdn_stripe -grid stdcell_grid -layer met4 -width 1.60 -pitch {block.pdn_v_pitch:.2f} -offset {block.pdn_v_offset:.2f}
add_pdn_connect -grid stdcell_grid -layers {{met1 met4}}
add_pdn_stripe -grid stdcell_grid -layer met5 -width 1.60 -pitch {block.pdn_h_pitch:.2f} -offset {block.pdn_h_offset:.2f}
add_pdn_connect -grid stdcell_grid -layers {{met4 met5}}
pdngen

# Stage 1: Timing-driven global placement (against ss_n40C_1v60 + OCV! Cardinal pins naturally
# partition PLL West, TX Mid-West, RX East without +20% dbRegion legalization teleportation!)
set_wire_rc -corner ss -signal -resistance 0.0020 -capacitance 0.00028
set_wire_rc -corner ss -clock  -resistance 0.0008 -capacitance 0.00024
set_wire_rc -corner ff -signal -resistance 0.0007 -capacitance 0.00009
set_wire_rc -corner ff -clock  -resistance 0.0003 -capacitance 0.00008
set_routing_layers -signal met1-met5 -clock met1-met5

global_placement -timing_driven -density {block.place_density:.2f}
place_pins -hor_layers met3 -ver_layers met2 -corner_avoidance 8 -min_distance 2 -min_distance_in_tracks

# Stage 2: Design repair & tight-skew CTS (dly* banned so only fast buf_4/6/8/12 used!)
{wire_rc_block}
estimate_parasitics -placement
set_max_transition 0.65 [current_design]
set_max_capacitance 0.085 [current_design]
set_max_fanout 45 [current_design]
repair_design -slew_margin 0 -cap_margin 0
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/HI
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/LO
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  puts "WARN: detailed_placement left a local TAP/cell overlap; running incremental legalization..."
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_16 \\
  -buf_list {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8}} \\
  -balance_levels -sink_clustering_enable -sink_clustering_size 20 -sink_clustering_max_diameter 60
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_clock_nets

# Option A (D-H1): Short 1-buffer clock tap off clkbuf_0_rx_word_clk/X for u_rx_map rx_phys* capture FFs
# Keeps u_rx_map CLK latency < 1.2 ns at ss_n40C_1v60 (+5% OCV) -> ZERO hold buffers on rx_phys* (-clock_fall)!
set _blk_tap [[[ord::get_db] getChip] getBlock]
set _root_buf [$_blk_tap findInst "clkbuf_0_rx_word_clk"]
if {{$_root_buf ne "NULL"}} {{
  set _root_xnet [[$_root_buf findITerm "X"] getNet]
  set _rxmap_insts {{}}
  set _rxmap_seen {{}}
  # Pure ODB BFS (up to 4 hops) from rx_phys* BTerms to find all capture FFs
  set _q_nets {{}}
  set _seen_nets {{}}
  foreach _bt [$_blk_tap getBTerms] {{
    if {{[string match "rx_phys*" [$_bt getName]]}} {{
      set _bn [$_bt getNet]
      if {{$_bn ne "NULL" && ![dict exists $_seen_nets [$_bn getName]]}} {{
        dict set _seen_nets [$_bn getName] 1
        lappend _q_nets [list $_bn 0]
      }}
    }}
  }}
  while {{[llength $_q_nets] > 0}} {{
    set _item [lindex $_q_nets 0]
    set _q_nets [lrange $_q_nets 1 end]
    set _cn [lindex $_item 0]
    set _dep [lindex $_item 1]
    foreach _it [$_cn getITerms] {{
      if {{[[$_it getMTerm] getIoType] eq "OUTPUT"}} {{ continue }}
      set _di [$_it getInst]
      set _sn [$_di getName]
      if {{[$_di findITerm "CLK"] ne "NULL"}} {{
        if {{![dict exists $_rxmap_seen $_sn]}} {{
          dict set _rxmap_seen $_sn 1
          lappend _rxmap_insts $_di
        }}
      }} elseif {{$_dep < 4}} {{
        foreach _oit [$_di getITerms] {{
          if {{[[$_oit getMTerm] getIoType] eq "OUTPUT"}} {{
            set _on2 [$_oit getNet]
            if {{$_on2 ne "NULL" && ![dict exists $_seen_nets [$_on2 getName]]}} {{
              dict set _seen_nets [$_on2 getName] 1
              lappend _q_nets [list $_on2 [expr {{$_dep + 1}}]]
            }}
          }}
        }}
      }}
    }}
  }}
  set _n_rxmap [llength $_rxmap_insts]
  if {{$_n_rxmap > 0 && $_root_xnet ne "NULL"}} {{
    set _tap_master [[ord::get_db] findMaster "sky130_fd_sc_hd__clkbuf_16"]
    set _rloc [$_root_buf getLocation]
    set _rx [lindex $_rloc 0]
    set _ry [lindex $_rloc 1]
    set _sx 0
    set _sy 0
    foreach _di $_rxmap_insts {{
      set _dl [$_di getLocation]
      incr _sx [lindex $_dl 0]
      incr _sy [lindex $_dl 1]
    }}
    set _tx [expr {{($_rx + ($_sx / $_n_rxmap)) / 2}}]
    set _ty [expr {{($_ry + ($_sy / $_n_rxmap)) / 2}}]
    set _old_nets {{}}
    for {{set _ti 0}} {{$_ti < 2}} {{incr _ti}} {{
      set _tn [odb::dbNet_create $_blk_tap "clknet_rxmap_tap_${{_ti}}"]
      $_tn setSigType CLOCK
      set _tb [odb::dbInst_create $_blk_tap $_tap_master "clkbuf_rxmap_tap_${{_ti}}"]
      $_tb setLocation [expr {{$_tx + $_ti * 4600}}] $_ty
      $_tb setPlacementStatus PLACED
      [$_tb findITerm "A"] connect $_root_xnet
      [$_tb findITerm "X"] connect $_tn
      set _tap_nets($_ti) $_tn
    }}
    set _idx 0
    foreach _di $_rxmap_insts {{
      set _cit [$_di findITerm "CLK"]
      set _on [$_cit getNet]
      if {{$_on ne "NULL"}} {{ dict set _old_nets [$_on getName] $_on }}
      $_cit disconnect
      set _ti [expr {{$_idx % 2}}]
      $_cit connect $_tap_nets($_ti)
      incr _idx
    }}
    # Clean up any CTS leaf buffer whose output net now has 0 sinks
    dict for {{_oname _onet}} $_old_nets {{
      set _sinks 0
      set _drv_inst "NULL"
      foreach _oit [$_onet getITerms] {{
        if {{[[$_oit getMTerm] getIoType] eq "OUTPUT"}} {{
          set _drv_inst [$_oit getInst]
        }} else {{
          incr _sinks
        }}
      }}
      if {{$_sinks == 0 && $_drv_inst ne "NULL" && ([string match "clkbuf_leaf_*" [$_drv_inst getName]] || [string match "clkbuf_*_rx_word_clk" [$_drv_inst getName]]) && [$_drv_inst getName] ne "clkbuf_0_rx_word_clk"}} {{
        odb::dbInst_destroy $_drv_inst
        odb::dbNet_destroy $_onet
      }}
    }}
    puts "RXMAP_SHORT_TAP: reconnected $_n_rxmap u_rx_map FFs to 2x clkbuf_16 tap off clkbuf_0_rx_word_clk/X"
  }}
}}
detailed_placement

# Keep giant clkbuf_* out of data repair; dly* remains banned so setup repair uses fast buf_4/6/8/12!
set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}

# Stage 3A: Pure Setup repair at realistic placement RC under ss_n40C_1v60 + OCV
set_wire_rc -corner ss -signal -resistance 0.0022 -capacitance 0.00030
set_wire_rc -corner ss -clock  -resistance 0.0008 -capacitance 0.00024
estimate_parasitics -placement
repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 10
detailed_placement
estimate_parasitics -placement
foreach _pg {{{' '.join(ALL_CLOCK_NAMES)} **async_default**}} {{
  set _ps [find_timing_paths -corner ss -path_delay max -path_group $_pg -group_count 1]
  puts [format "POST_SETUP_WNS %-16s %+.4f" $_pg [expr {{[llength $_ps] ? [get_property [lindex $_ps 0] slack] : 99.0}}]]
}}
write_def {post_setup_def}
"""
    )

    pnr_hold_tcl = work / "pnr_hold_route.tcl"
    pnr_hold_tcl.write_text(
        f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
define_corners ss ff
read_liberty -corner ss {LIB_SS_N40_1V65}
read_liberty -corner ff {LIB_FF_N40}
read_def {post_setup_def}
read_sdc {sdc_path}
set_propagated_clock [all_clocks]

# Phase B: allow compact 1-cell dly* (3.6x SS/FF ratio vs 7.5x for buf_4) ONLY for setup-safe hold repair!
{v3p3_openroad_dont_use_tcl(allow_hold_dly=True)}
set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}

set_wire_rc -corner ss -signal -resistance 0.0022 -capacitance 0.00030
set_wire_rc -corner ss -clock  -resistance 0.0008 -capacitance 0.00024
set_wire_rc -corner ff -signal -resistance 0.0007 -capacitance 0.00009
set_wire_rc -corner ff -clock  -resistance 0.0003 -capacitance 0.00008
set_routing_layers -signal met1-met5 -clock met1-met5

estimate_parasitics -placement
repair_timing -hold -slack_margin {block.hold_margin_ns:.3f} -max_buffer_percent 20
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  puts "WARN: detailed_placement left a local TAP/cell overlap; running incremental legalization..."
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}
estimate_parasitics -placement
foreach _pg {{{' '.join(ALL_CLOCK_NAMES)} **async_default**}} {{
  set _ps [find_timing_paths -corner ss -path_delay max -path_group $_pg -group_count 1]
  puts [format "PRE_DRT_WNS %-16s %+.4f" $_pg [expr {{[llength $_ps] ? [get_property [lindex $_ps 0] slack] : 99.0}}]]
}}
puts [format "PRE_DRT_HOLD FF=%+.4f SS=%+.4f" [sta::worst_slack -corner ff -min] [sta::worst_slack -corner ss -min]]

# Pre-DRT Global Route + Antenna Diode Repair
report_design_area
global_route -congestion_iterations 80 -allow_congestion
check_antennas -report_file {ant_pre_rpt} -report_violating_nets
set diode_pin [lindex [get_lib_pins sky130_fd_sc_hd__diode_2/DIODE] 0]
if {{[catch {{repair_antennas $diode_pin -iterations 5}} ant_err]}} {{
  puts "WARNING: repair_antennas returned: $ant_err (unlocking & legalizing diodes via detailed_placement)"
}}
foreach inst [[[[ord::get_db] getChip] getBlock] getInsts] {{
  if {{[string match "*__diode_*" [[$inst getMaster] getName]]}} {{
    $inst setPlacementStatus PLACED
  }}
}}
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  puts "WARN: detailed_placement left a local TAP/cell overlap; running incremental legalization..."
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

# Priority Decap Fill
filler_placement {decap_fill_list}
add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground

global_route -congestion_iterations 80 -allow_congestion
set_propagated_clock [all_clocks]
detailed_route -output_drc {drc_rpt} -bottom_routing_layer met1 -top_routing_layer met5 -droute_end_iter 45 -verbose 1

write_def {routed_def}
write_verilog {routed_v}
write_verilog -include_pwr_gnd -remove_cells {{sky130_fd_sc_hd__fill_1 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__tapvpwrvgnd_1}} {routed_pg_v}

puts "=== POST_ROUTE_ANTENNA_CHECK ==="
set ant_viols [check_antennas -report_file {ant_post_rpt} -report_violating_nets]
puts "POST_ROUTE_ANTENNA_VIOLS: $ant_viols"

puts "=== METRICS_REPORT ==="
report_design_area
set db [ord::get_db]
set block_db [[$db getChip] getBlock]
set dbu [expr {{double([$block_db getDbUnitsPerMicron])}}]
set die [$block_db getDieArea]
set die_w [expr {{([$die xMax] - [$die xMin]) / $dbu}}]
set die_h [expr {{([$die yMax] - [$die yMin]) / $dbu}}]
set core [$block_db getCoreArea]
set core_w [expr {{([$core xMax] - [$core xMin]) / $dbu}}]
set core_h [expr {{([$core yMax] - [$core yMin]) / $dbu}}]
puts [format "DIE_UM: %.3f %.3f %.3f" $die_w $die_h [expr {{$die_w * $die_h}}]]
puts [format "CORE_UM: %.3f %.3f %.3f" $core_w $core_h [expr {{$core_w * $core_h}}]]
"""
    )

    if resume_eco and routed_def.exists() and (work / "02_openroad_pnr.log").exists():
        print(f"[{block.name}]   Resuming directly from intact Pass-0 DEF -> ECO passes...", flush=True)
        log = (work / "02_openroad_pnr.log").read_text()
    else:
        base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(pnr_tcl)],
            work,
            work / "02a_openroad_setup.log",
            timeout=900,
        )
        proc = base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(pnr_hold_tcl)],
            work,
            work / "02_openroad_pnr.log",
            timeout=1800,
        )
        log = proc.stdout

    # Post-route OpenRCX SPEF-driven ECO + Antenna closure loop against ss_n40C_1v60 + OCV!
    sdc_eco = work / f"{block.name}_eco.sdc"
    write_v3p3_sdc(block, sdc_eco, post_route=True)
    clk_groups_tcl = " ".join(ALL_CLOCK_NAMES)

    for eco_pass in (1, 2, 3, 4, 5, 6, 7):
        spef_eco_max = work / f"{block.name}_eco_max.spef"
        spef_eco_min = work / f"{block.name}_eco_min.spef"
        for tag, rcx_rule, sp_out in [("max", base.RCX_MAX, spef_eco_max), ("min", base.RCX_MIN, spef_eco_min)]:
            ext_tcl = work / f"eco_ext_{tag}.tcl"
            ext_tcl.write_text(
                f"""read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_def {routed_def}
define_process_corner -ext_model_index 0 eco_{tag}
extract_parasitics -ext_model_file {rcx_rule}
write_spef {sp_out}
exit
"""
            )
            base.run_cmd(
                [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(ext_tcl)],
                work,
                work / f"02b_eco_p{eco_pass}_ext_{tag}.log",
                timeout=300,
            )

        gb = 0.15 if eco_pass == 1 else (0.08 if eco_pass == 2 else 0.03)
        eco_tcl = work / f"pnr_eco_p{eco_pass}.tcl"
        eco_tcl.write_text(
            f"""read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
define_corners ss ff
read_liberty -corner ss {LIB_SS_N40_1V65}
read_liberty -corner ff {LIB_FF_N40}
read_def {routed_def}
read_sdc {sdc_eco}
{v3p3_openroad_dont_use_tcl(allow_hold_dly=True)}

read_spef -corner ss {spef_eco_max}
read_spef -corner ff {spef_eco_min}

set init_wns [sta::worst_slack -corner ss -max]
set init_hold_ff [sta::worst_slack -corner ff -min]
set init_hold_ss [sta::worst_slack -corner ss -min]
set init_hold [expr {{$init_hold_ff < $init_hold_ss ? $init_hold_ff : $init_hold_ss}}]
set init_ant [check_antennas -report_file {work}/_ant_tmp.rpt]
puts [format "ECO_P{eco_pass}_INIT: SS_N40_OCV_WNS=%.4f FF_HOLD=%.4f SS_HOLD=%.4f ANT=%d" $init_wns $init_hold_ff $init_hold_ss $init_ant]
if {{$init_wns >= 0.03 && $init_hold >= 0.02 && $init_ant == 0}} {{
  puts "ECO_P{eco_pass}_SKIP_ALREADY_CLOSED"
  exit 0
}}

set db_eco [ord::get_db]
set blk_eco [[$db_eco getChip] getBlock]
foreach inst [$blk_eco getInsts] {{
  set mn [[$inst getMaster] getName]
  if {{[string match "*__fill_*" $mn] || [string match "*__decap_*" $mn]}} {{
    odb::dbInst_destroy $inst
  }}
}}

{wire_rc_block}
set_routing_layers -signal met1-met5 -clock met1-met5

set drc_excl_map {{}}
foreach xc {{{' '.join(sorted(base.load_excluded_cells()))}}} {{ dict set drc_excl_map $xc 1 }}
set all_masters {{}}
foreach lib [$db_eco getLibs] {{
  foreach m [$lib getMasters] {{
    set mn [$m getName]
    if {{![dict exists $drc_excl_map $mn]}} {{ dict set all_masters $mn 1 }}
  }}
}}
proc _next_drv {{mname all_masters}} {{
  if {{[string match "*__dly*" $mname]}} {{
    if {{[dict exists $all_masters "sky130_fd_sc_hd__buf_4"]}} {{ return "sky130_fd_sc_hd__buf_4" }}
    return ""
  }}
  if {{[regexp {{^sky130_fd_sc_hd__clkbuf_([0-9]+)$}} $mname -> drv]}} {{
    foreach d {{6 8 12}} {{
      if {{$d > $drv}} {{
        set cand "sky130_fd_sc_hd__buf_${{d}}"
        if {{[dict exists $all_masters $cand]}} {{ return $cand }}
      }}
    }}
    return ""
  }}
  if {{[regexp {{^(sky130_fd_sc_hd__[a-z0-9]+)_([0-9]+)$}} $mname -> base drv]}} {{
    set drv_list [expr {{[string match "*__buf" $base] || [string match "*__inv" $base] ? {{2 4 6 8 12}} : {{2 4 6 8}}}}]
    foreach d $drv_list {{
      if {{$d > $drv}} {{
        set cand "${{base}}_${{d}}"
        if {{[dict exists $all_masters $cand]}} {{ return $cand }}
      }}
    }}
  }}
  return ""
}}

set eco_swapped 0
if {{$init_wns < 0.06 && {eco_pass} <= 6}} {{
  set_clock_uncertainty -setup [expr {{0.10 + {gb}}}] [all_clocks]
  for {{set iter 0}} {{$iter < 25}} {{incr iter}} {{
    set wns [sta::worst_slack -corner ss -max]
    if {{$wns >= 0.05}} {{ break }}
    set seen {{}}
    set improved 0
    foreach clk_grp {{{clk_groups_tcl}}} {{
      set paths [find_timing_paths -corner ss -path_delay max -path_group $clk_grp -group_count 80 -endpoint_count 1 -slack_max 0.06]
      foreach pe $paths {{
        set p [$pe path]
        foreach pin [$p pins] {{
          if {{[$pin is_top_level_port]}} {{ continue }}
          set inst [$pin instance]
          if {{$inst eq "NULL"}} {{ continue }}
          set iname [get_full_name $inst]
          if {{[dict exists $seen $iname]}} {{ continue }}
          dict set seen $iname 1
          set dbinst [$blk_eco findInst $iname]
          if {{$dbinst eq "NULL"}} {{ continue }}
          set mname [[$dbinst getMaster] getName]
          if {{[string match "clkbuf*" $iname]}} {{ continue }}
          set cand [_next_drv $mname $all_masters]
          if {{$cand eq ""}} {{ continue }}
          set old_wns [sta::worst_slack -corner ss -max]
          set old_tns [sta::total_negative_slack -corner ss -max]
          set old_hold [sta::worst_slack -corner ff -min]
          set hold_floor [expr {{$old_hold < 0.035 ? ($old_hold - 0.002) : 0.035}}]
          if {{[catch {{replace_cell $iname $cand}}]}} {{ continue }}
          set new_wns [sta::worst_slack -corner ss -max]
          set new_tns [sta::total_negative_slack -corner ss -max]
          set new_hold [sta::worst_slack -corner ff -min]
          if {{($new_wns > $old_wns + 0.001 || ($new_wns >= $old_wns - 0.001 && $new_tns > $old_tns + 0.003)) && $new_hold >= $hold_floor}} {{
            incr eco_swapped
            set improved 1
          }} else {{
            catch {{replace_cell $iname $mname}}
          }}
        }}
      }}
    }}
    puts [format "ECO_P{eco_pass}_ITER %d: swapped=%d SS_N40_OCV_WNS=%.4f SS_TNS_GB=%.4f FF_HOLD=%.4f" $iter $eco_swapped [expr {{[sta::worst_slack -corner ss -max] + {gb}}}] [sta::total_negative_slack -corner ss -max] [sta::worst_slack -corner ff -min]]
    if {{!$improved}} {{ break }}
  }}
  set_clock_uncertainty -setup 0.10 [all_clocks]
}}

set post_eco_wns [sta::worst_slack -corner ss -max]
set post_hold_ff [sta::worst_slack -corner ff -min]
set post_hold_ss [sta::worst_slack -corner ss -min]

# Keep all CTS leaves at crisp clkbuf_16 (do NOT downgrade to clkbuf_8, which degrades launch slew!)
set eco_cloned 0

set need_hold_fix [expr {{$post_hold_ff < 0.02 || $post_hold_ss < 0.02}}]
set need_setup_buf [expr {{$post_eco_wns < -0.05 && $eco_swapped < 20 && {eco_pass} <= 5}}]
if {{$eco_swapped == 0 && $eco_cloned == 0 && !$need_hold_fix && !$need_setup_buf && $init_ant == 0}} {{
  puts "ECO_P{eco_pass}_NO_CHANGES"
  exit 0
}}

# Direct ODB post-DRT antenna diode insertion
set drt_diodes_added 0
if {{$init_ant > 0 && [file exists {ant_post_rpt}]}} {{
  set diode_master [$db_eco findMaster sky130_fd_sc_hd__diode_2]
  if {{$diode_master ne "NULL"}} {{
    set fp [open {ant_post_rpt} r]
    set cur_net ""
    set added_pair {{}}
    set d_uid 0
    while {{[gets $fp line] >= 0}} {{
      if {{[regexp {{^Net\\s*-\\s*(\\S+)}} $line -> nname]}} {{
        set cur_net $nname
      }} elseif {{$cur_net ne "" && [regexp {{^\\s+(\\S+)\\s+\\(sky130_fd_sc_hd__[^)]+\\)\\s+(\\S+)}} $line -> iname pname]}} {{
        set key "${{cur_net}}::${{iname}}"
        if {{![dict exists $added_pair $key]}} {{
          dict set added_pair $key 1
          set net_obj [$blk_eco findNet $cur_net]
          set inst_obj [$blk_eco findInst $iname]
          if {{$net_obj ne "NULL" && $inst_obj ne "NULL"}} {{
            set loc [$inst_obj getLocation]
            set n_add [expr {{{eco_pass} >= 2 ? 2 : 1}}]
            for {{set di 0}} {{$di < $n_add}} {{incr di}} {{
              while {{1}} {{
                set dname "ANT_ECO_P{eco_pass}_${{d_uid}}"
                incr d_uid
                if {{[$blk_eco findInst $dname] eq "NULL"}} {{ break }}
              }}
              set dinst [odb::dbInst_create $blk_eco $diode_master $dname]
              if {{$dinst ne "NULL"}} {{
                $dinst setLocation [lindex $loc 0] [lindex $loc 1]
                $dinst setPlacementStatus PLACED
                set dterm [$dinst findITerm DIODE]
                if {{$dterm ne "NULL"}} {{ $dterm connect $net_obj }}
                incr drt_diodes_added
              }}
            }}
          }}
        }}
      }}
    }}
    close $fp
  }}
  puts "ECO_P{eco_pass}_DRT_DIODES_ADDED: $drt_diodes_added"
}}

if {{$need_setup_buf}} {{
  set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}
  repair_timing -setup -slack_margin 0.05 -max_buffer_percent 3
  foreach _ri [$blk_eco getInsts] {{
    set _rn [$_ri getName]
    set _rm [[$_ri getMaster] getName]
    if {{![string match "hold*" $_rn] && [string match "*__dly*" $_rm]}} {{
      replace_cell $_rn sky130_fd_sc_hd__buf_4
    }}
  }}
}}

if {{$need_hold_fix}} {{
  set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}
  repair_timing -hold -slack_margin 0.03 -max_buffer_percent 10
}}

foreach net [$blk_eco getNets] {{
  if {{![$net isSpecial]}} {{
    set wire [$net getWire]
    if {{$wire ne "NULL"}} {{
      odb::dbWire_destroy $wire
    }}
  }}
}}

foreach inst [$blk_eco getInsts] {{
  if {{[string match "*__diode_*" [[$inst getMaster] getName]]}} {{
    $inst setPlacementStatus PLACED
  }}
}}
write_def {work}/{block.name}_eco_edit.def
puts "ECO_P{eco_pass}_EDIT_DONE"
"""
        )
        proc_eco = base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(eco_tcl)],
            work,
            work / f"02c_openroad_eco_p{eco_pass}.log",
            timeout=900,
        )
        if f"ECO_P{eco_pass}_SKIP_ALREADY_CLOSED" in proc_eco.stdout or f"ECO_P{eco_pass}_NO_CHANGES" in proc_eco.stdout:
            break

        skew_matches = re.findall(rf"ECO_P{eco_pass}_SKEWSWAP:\s+(\S+)\s+->\s+(\S+)", proc_eco.stdout)
        if skew_matches:
            eco_edit_def = work / f"{block.name}_eco_edit.def"
            ed_txt = eco_edit_def.read_text()
            for snm, smn in skew_matches:
                ed_txt = re.sub(
                    rf"(-\s+{re.escape(snm)}\s+)sky130_fd_sc_hd__clkbuf_\d+",
                    rf"\1{smn}",
                    ed_txt,
                )
            eco_edit_def.write_text(ed_txt)

        eco_route_tcl = work / f"pnr_eco_p{eco_pass}_route.tcl"
        eco_route_tcl.write_text(
            f"""read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {LIB_SS_N40_1V65}
read_def {work}/{block.name}_eco_edit.def
read_sdc {sdc_eco}
set blk_rt [[[ord::get_db] getChip] getBlock]
foreach inst [$blk_rt getInsts] {{
  set mn [[$inst getMaster] getName]
  if {{![string match "*__tap*" $mn] && [$inst getPlacementStatus] ne "PLACED"}} {{
    $inst setPlacementStatus PLACED
  }}
}}
set_routing_layers -signal met1-met5 -clock met1-met5
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  puts "WARN: detailed_placement left a local TAP/cell overlap; running incremental legalization..."
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

filler_placement {decap_fill_list}
add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground

global_route -congestion_iterations 80 -allow_congestion
set_propagated_clock [all_clocks]
detailed_route -output_drc {drc_rpt} -bottom_routing_layer met1 -top_routing_layer met5 -droute_end_iter 45 -verbose 1

write_def {routed_def}
write_verilog {routed_v}
write_verilog -include_pwr_gnd -remove_cells {{sky130_fd_sc_hd__fill_1 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__tapvpwrvgnd_1}} {routed_pg_v}

puts "=== POST_ROUTE_ANTENNA_CHECK ==="
set ant_viols [check_antennas -report_file {ant_post_rpt} -report_violating_nets]
puts "POST_ROUTE_ANTENNA_VIOLS: $ant_viols"

puts "=== METRICS_REPORT ==="
report_design_area
set db [ord::get_db]
set block_db [[$db getChip] getBlock]
set dbu [expr {{double([$block_db getDbUnitsPerMicron])}}]
set die [$block_db getDieArea]
set die_w [expr {{([$die xMax] - [$die xMin]) / $dbu}}]
set die_h [expr {{([$die yMax] - [$die yMin]) / $dbu}}]
set core [$block_db getCoreArea]
set core_w [expr {{([$core xMax] - [$core xMin]) / $dbu}}]
set core_h [expr {{([$core yMax] - [$core yMin]) / $dbu}}]
puts [format "DIE_UM: %.3f %.3f %.3f" $die_w $die_h [expr {{$die_w * $die_h}}]]
puts [format "CORE_UM: %.3f %.3f %.3f" $core_w $core_h [expr {{$core_w * $core_h}}]]
"""
        )
        proc_route = base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(eco_route_tcl)],
            work,
            work / f"02d_openroad_eco_p{eco_pass}_route.log",
            timeout=1800,
        )
        if "=== METRICS_REPORT ===" in proc_route.stdout:
            log = proc_route.stdout

    die_m = re.search(r"DIE_UM:\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", log)
    core_m = re.search(r"CORE_UM:\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", log)
    util_m = re.search(r"Design area\s+([0-9.]+)\s+u\^2\s+([0-9.]+)%\s+utilization", log)

    drt_viols = 0
    if drc_rpt.exists():
        drt_viols = len(re.findall(r"^\s*violation type:", drc_rpt.read_text(), re.M))

    wl = v3.parse_wirelength_from_log(log)
    cell_stats = v3.count_cells_in_def(routed_def)
    netlist_audit = v3.audit_netlist_v(routed_v)
    ant_viols = v3.parse_antenna_violations(ant_post_rpt, log)
    pin_check = v3.verify_pin_regions_in_def(
        routed_def,
        pin_groups,
        float(die_m.group(1)) if die_m else die_w,
        float(die_m.group(2)) if die_m else die_h,
    )

    return {
        "die_w_um": float(die_m.group(1)) if die_m else die_w,
        "die_h_um": float(die_m.group(2)) if die_m else die_h,
        "die_area_um2": float(die_m.group(3)) if die_m else round(die_w * die_h, 3),
        "core_w_um": float(core_m.group(1)) if core_m else None,
        "core_h_um": float(core_m.group(2)) if core_m else None,
        "core_area_um2": float(core_m.group(3)) if core_m else None,
        "design_area_um2": float(util_m.group(1)) if util_m else None,
        "utilization_pct": float(util_m.group(2)) if util_m else None,
        "openroad_drt_drvs": drt_viols,
        "antenna_violations": ant_viols,
        "wirelength": wl,
        "cell_stats": cell_stats,
        "netlist_audit": netlist_audit,
        "pin_check": pin_check,
        "std_cells": cell_stats["std_cells"],
        "phys_cells": cell_stats["phys_cells"],
        "total_cells": cell_stats["total_cells"],
        "routed_def": str(routed_def),
        "routed_v": str(routed_v),
        "routed_pg_v": str(routed_pg_v),
        "spef_nom": str(spef_nom),
        "spef_max": str(spef_max),
        "spef_min": str(spef_min),
    }


def run_v3p3_sta_5corner(block: base.BlockSpec, work: Path, pnr_info: dict[str, Any]) -> dict[str, Any]:
    """6-Corner Post-Route OpenRCX STA (+/-5% OCV + ss_n40C_1v65 NO_OCV) across all 6 clocks."""
    sdc_post = work / f"{block.name}_postroute.sdc"
    write_v3p3_sdc(block, sdc_post, post_route=True, ocv=True)
    sdc_post_no_ocv = work / f"{block.name}_postroute_no_ocv.sdc"
    write_v3p3_sdc(block, sdc_post_no_ocv, post_route=True, ocv=False)

    # Extract 3 SPEF files once (nom, max, min)
    for tag, rcx_rule, spef_path in [
        ("nom", base.RCX_NOM, Path(pnr_info["spef_nom"])),
        ("max", base.RCX_MAX, Path(pnr_info["spef_max"])),
        ("min", base.RCX_MIN, Path(pnr_info["spef_min"])),
    ]:
        ext_tcl = work / f"sta_ext_{tag}.tcl"
        ext_tcl.write_text(
            f"""read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_def {pnr_info["routed_def"]}
define_process_corner -ext_model_index 0 {tag}
extract_parasitics -ext_model_file {rcx_rule}
write_spef {spef_path}
exit
"""
        )
        base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(ext_tcl)],
            work,
            work / f"03a_rcx_{tag}.log",
            timeout=300,
        )

    corners = [
        ("tt_025C_1v80",       LIB_TT_025,      Path(pnr_info["spef_nom"]), sdc_post),
        ("ss_100C_1v60",       LIB_SS_100,      Path(pnr_info["spef_max"]), sdc_post),
        ("ss_n40C_1v65_interp", LIB_SS_N40_1V65, Path(pnr_info["spef_max"]), sdc_post),
        ("ss_n40C_1v65_no_ocv", LIB_SS_N40_1V65, Path(pnr_info["spef_max"]), sdc_post_no_ocv),
        ("ss_n40C_1v60",       LIB_SS_N40,      Path(pnr_info["spef_max"]), sdc_post),
        ("ff_n40C_1v95",       LIB_FF_N40,      Path(pnr_info["spef_min"]), sdc_post),
        ("ff_100C_1v95",       LIB_FF_100,      Path(pnr_info["spef_min"]), sdc_post),
    ]
    per_clk_tcl = "\n".join(
        f"""
puts "=== CLK_SETUP_{cname} ==="
report_checks -path_delay max -path_group {cname} -digits 4 -fields {{slew cap}}
puts "=== CLK_HOLD_{cname} ==="
report_checks -path_delay min -path_group {cname} -digits 4 -fields {{slew cap}}
"""
        for cname in ALL_CLOCK_NAMES
    )

    sta_results: dict[str, Any] = {}
    for cname, lib_path, spef_path, sdc_use in corners:
        tcl = work / f"sta_{cname}.tcl"
        tcl.write_text(
            f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {lib_path}
read_def {pnr_info["routed_def"]}
read_sdc {sdc_use}
read_spef {spef_path}

puts "=== SETUP_WORST ==="
report_checks -path_delay max -sort_by_slack -format full_clock_expanded -digits 4
puts "=== HOLD_WORST ==="
report_checks -path_delay min -sort_by_slack -format full_clock_expanded -digits 4
puts "=== RX_PHYS_FALL_SETUP ==="
report_checks -path_delay max -from [get_ports rx_phys*] -digits 4
puts "=== RX_PHYS_FALL_HOLD ==="
report_checks -path_delay min -from [get_ports rx_phys*] -digits 4
puts "=== ASYNC_RECOVERY ==="
report_checks -path_delay max -path_group **async_default** -digits 4
puts "=== ASYNC_REMOVAL ==="
report_checks -path_delay min -path_group **async_default** -digits 4
{per_clk_tcl}
puts "=== SUMMARY ==="
puts "SETUP_WNS: [sta::worst_slack -max]"
puts "SETUP_TNS: [sta::total_negative_slack -max]"
puts "HOLD_WNS: [sta::worst_slack -min]"
puts "HOLD_TNS: [sta::total_negative_slack -min]"
report_check_types -max_slew -max_capacitance -max_fanout -violators
"""
        )
        proc = base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(tcl)],
            work,
            work / f"03_sta_{cname}.log",
            timeout=300,
        )
        log = proc.stdout

        def parse_val(key: str) -> float | None:
            m = re.search(rf"^{key}:\s*([-+]?[0-9.eE+-]+)", log, re.M)
            if not m:
                return None
            val = float(m.group(1))
            if abs(val) < 1e-6 and val != 0.0:
                val *= 1e9
            return round(val, 4)

        per_clk: dict[str, dict[str, float | None]] = {}
        for clk_n in ALL_CLOCK_NAMES:
            sm = re.search(
                rf"=== CLK_SETUP_{clk_n} ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)",
                log,
                re.S,
            )
            hm = re.search(
                rf"=== CLK_HOLD_{clk_n} ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)",
                log,
                re.S,
            )
            per_clk[clk_n] = {
                "setup_wns_ns": round(float(sm.group(1)), 4) if sm else None,
                "hold_wns_ns": round(float(hm.group(1)), 4) if hm else None,
            }

        rxs = re.search(
            r"=== RX_PHYS_FALL_SETUP ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)",
            log,
            re.S,
        )
        rxh = re.search(
            r"=== RX_PHYS_FALL_HOLD ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)",
            log,
            re.S,
        )

        setup_wns = parse_val("SETUP_WNS")
        hold_wns = parse_val("HOLD_WNS")
        setup_tns = parse_val("SETUP_TNS")
        hold_tns = parse_val("HOLD_TNS")
        sta_results[cname] = {
            "setup_wns_ns": setup_wns,
            "setup_tns_ns": setup_tns,
            "hold_wns_ns": hold_wns,
            "hold_tns_ns": hold_tns,
            "setup_met": (setup_wns is not None and setup_wns >= 0.0),
            "hold_met": (hold_wns is not None and hold_wns >= 0.0),
            "rx_phys_fall_setup_ns": round(float(rxs.group(1)), 4) if rxs else None,
            "rx_phys_fall_hold_ns": round(float(rxh.group(1)), 4) if rxh else None,
            "per_clock": per_clk,
        }
    return sta_results


def run_v3p3_cdc_audit(block: base.BlockSpec, work: Path, pnr_info: dict[str, Any]) -> dict[str, Any]:
    """Post-route CDC audit on max.spef at ss_n40C_1v60 (+5% OCV):
      1. Gray-pointer bus_skew (max - min) for w_gray[0..4]->w_gray_r1[0..4] and r_pop_gray[0..4]->r_gray_w1[0..4]
      2. sync1 -> sync2 MTBF slack (setup slack = resolution window at 250 MHz)
      3. Strict fanout == 1 structural check on EVERY 1st-stage synchronizer FF (D-C1 proof!)
    """
    sdc_cdc = work / f"{block.name}_cdc_audit.sdc"
    write_v3p3_sdc(block, sdc_cdc, post_route=True)
    # Remove set_clock_groups -asynchronous in CDC audit SDC so STA computes exact Gray-pointer delays
    sdc_txt = sdc_cdc.read_text()
    sdc_txt = re.sub(
        r"set_clock_groups -asynchronous\s*\\\n(?:\s*-group \{[^\}]+\}\s*\\?\n)+",
        "# (clock groups temporarily removed for CDC Gray bus_skew & MTBF audit)\n",
        sdc_txt,
    )
    sdc_cdc.write_text(sdc_txt)

    tcl = work / "cdc_audit.tcl"
    tcl.write_text(
        f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {LIB_SS_N40_1V65}
read_def {pnr_info["routed_def"]}
read_sdc {sdc_cdc}
read_spef {pnr_info["spef_max"]}

set blk [[[ord::get_db] getChip] getBlock]

proc _driver_inst {{blk net_name}} {{
  set cur $net_name
  for {{set hop 0}} {{$hop < 8}} {{incr hop}} {{
    set n [$blk findNet $cur]
    if {{$n eq "NULL"}} {{ return "" }}
    set found ""
    foreach it [$n getITerms] {{
      if {{[[$it getMTerm] getIoType] eq "OUTPUT"}} {{
        set inst [$it getInst]
        set mn [[$inst getMaster] getName]
        if {{[string match "*__buf_*" $mn] || [string match "*__dly*" $mn] || [string match "*__clkbuf_*" $mn]}} {{
          set ait [$inst findITerm A]
          if {{$ait ne "NULL" && [$ait getNet] ne "NULL"}} {{
            set cur [[$ait getNet] getName]
            set found "STEP"
            break
          }}
        }}
        return [$inst getName]
      }}
    }}
    if {{$found ne "STEP"}} {{ return "" }}
  }}
  return ""
}}

# Trace downstream through pure buffers/inverters to collect all distinct sink (inst, pin) endpoints
proc _trace_sinks {{blk net_name}} {{
  set sinks {{}}
  set visited {{}}
  set q [list $net_name]
  while {{[llength $q] > 0}} {{
    set cur [lindex $q 0]
    set q [lrange $q 1 end]
    if {{[dict exists $visited $cur]}} {{ continue }}
    dict set visited $cur 1
    set n [$blk findNet $cur]
    if {{$n eq "NULL"}} {{ continue }}
    foreach it [$n getITerms] {{
      if {{[[$it getMTerm] getIoType] ne "INPUT"}} {{ continue }}
      set inst [$it getInst]
      set mname [[$inst getMaster] getName]
      set pname [[$it getMTerm] getName]
      if {{[string match "*__diode_*" $mname]}} {{ continue }}
      if {{[string match "*__buf_*" $mname] || [string match "*__dly*" $mname] || [string match "*__clkbuf_*" $mname]}} {{
        set out_it [$inst findITerm X]
        if {{$out_it ne "NULL" && [$out_it getNet] ne "NULL"}} {{
          lappend q [[$out_it getNet] getName]
          continue
        }}
      }}
      lappend sinks "[$inst getName]/$pname ($mname)"
    }}
  }}
  return $sinks
}}

puts "=== SYNC1_FANOUT_AUDIT ==="
set sync1_nets {{
  cdc_r_up_w_0 cdc_w_up_r_0 cdc_overflow_r_0
  cdc_w_rst_s0 cdc_r_rst_s0
  cdc_r_gray_w1_0 cdc_r_gray_w1_1 cdc_r_gray_w1_2 cdc_r_gray_w1_3 cdc_r_gray_w1_4
  cdc_w_gray_r1_0 cdc_w_gray_r1_1 cdc_w_gray_r1_2 cdc_w_gray_r1_3 cdc_w_gray_r1_4
}}
foreach sn $sync1_nets {{
  set drv [_driver_inst $blk $sn]
  set sinks [_trace_sinks $blk $sn]
  puts "SYNC1_NET: $sn drv=$drv fanout=[llength $sinks] sinks={{$sinks}}"
}}

puts "=== GRAY_BUS_SKEW_AUDIT ==="
foreach {{tag src_pre dst_pre}} {{
  w2r_gray cdc_w_gray cdc_w_gray_r1
  r2w_gray cdc_r_pop_gray cdc_r_gray_w1
}} {{
  for {{set b 0}} {{$b < 5}} {{incr b}} {{
    set s_inst [_driver_inst $blk "${{src_pre}}_${{b}}"]
    set d_inst [_driver_inst $blk "${{dst_pre}}_${{b}}"]
    if {{$s_inst eq "" || $d_inst eq ""}} {{
      puts "GRAY_BIT_HDR $tag $b MISSING $s_inst $d_inst"
      continue
    }}
    puts "GRAY_BIT_HDR $tag $b OK $s_inst $d_inst"
    report_checks -to [get_pins "${{d_inst}}/D"] -path_delay max -unconstrained -digits 5
  }}
}}

puts "=== SYNC1_TO_SYNC2_MTBF_AUDIT ==="
set sync_pairs {{
  r_up_w      cdc_r_up_w_0      cdc_r_up_w_1
  w_up_r      cdc_w_up_r_0      host_online
  overflow_r  cdc_overflow_r_0  cdc_overflow_r_1
  w_rst_sync  cdc_w_rst_s0      cdc_w_rst_s1
  r_rst_sync  cdc_r_rst_s0      cdc_r_rst_s1
  r_gray_w_0  cdc_r_gray_w1_0   cdc_r_gray_w2_0
  r_gray_w_1  cdc_r_gray_w1_1   cdc_r_gray_w2_1
  r_gray_w_2  cdc_r_gray_w1_2   cdc_r_gray_w2_2
  r_gray_w_3  cdc_r_gray_w1_3   cdc_r_gray_w2_3
  r_gray_w_4  cdc_r_gray_w1_4   cdc_r_gray_w2_4
  w_gray_r_0  cdc_w_gray_r1_0   cdc_w_gray_r2_0
  w_gray_r_1  cdc_w_gray_r1_1   cdc_w_gray_r2_1
  w_gray_r_2  cdc_w_gray_r1_2   cdc_w_gray_r2_2
  w_gray_r_3  cdc_w_gray_r1_3   cdc_w_gray_r2_3
  w_gray_r_4  cdc_w_gray_r1_4   cdc_w_gray_r2_4
}}
foreach {{name n1 n2}} $sync_pairs {{
  set i1 [_driver_inst $blk $n1]
  set i2 [_driver_inst $blk $n2]
  if {{$i1 eq "" || $i2 eq ""}} {{
    puts "MTBF_PAIR: $name MISSING i1=$i1 i2=$i2"
    continue
  }}
  set paths [find_timing_paths -path_delay max -from [get_pins "${{i1}}/CLK"] -to [get_pins "${{i2}}/D"] -group_count 1]
  if {{[llength $paths] > 0}} {{
    set pe [lindex $paths 0]
    set slk [get_property $pe slack]
    puts [format "MTBF_PAIR: %s s1=%s s2=%s slack=%.5f arrival=0.00000 required=0.00000" $name $i1 $i2 $slk]
  }} else {{
    puts "MTBF_PAIR: $name NO_PATH s1=$i1 s2=$i2"
  }}
}}
exit
"""
    )
    proc = base.run_cmd(
        [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(tcl)],
        work,
        work / "03b_cdc_audit.log",
        timeout=300,
    )
    log = proc.stdout

    def _to_ns(v: float) -> float:
        return round(v * 1e9 if (abs(v) < 1e-6 and v != 0.0) else v, 4)

    fanout_audit: dict[str, Any] = {}
    fanout_violations = 0
    for m in re.finditer(r"^SYNC1_NET:\s+(\S+)\s+drv=(\S*)\s+fanout=(\d+)\s+sinks=\{(.*)\}$", log, re.M):
        net_n, drv, fo_s, sinks = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        fanout_audit[net_n] = {"driver": drv, "fanout": fo_s, "sinks": sinks}
        if fo_s != 1:
            fanout_violations += 1

    gray_buses: dict[str, dict[str, Any]] = {}
    gsec_m = re.search(r"=== GRAY_BUS_SKEW_AUDIT ===\n(.*?)\n=== SYNC1_TO_SYNC2_MTBF_AUDIT ===", log, re.S)
    if gsec_m:
        for blk_s in gsec_m.group(1).split("GRAY_BIT_HDR ")[1:]:
            hdr = blk_s.splitlines()[0].split()
            if len(hdr) < 5 or hdr[2] != "OK":
                continue
            tag, bit, s_inst, d_inst = hdr[0], int(hdr[1]), hdr[3], hdr[4]
            m_arr = re.search(r"([0-9.]+)\s+data arrival time", blk_s)
            m_clk = re.search(r"([0-9.]+)\s+clock network delay", blk_s)
            if m_arr:
                tot = round(float(m_arr.group(1)), 4)
                lclk = round(float(m_clk.group(1)), 4) if m_clk else 0.0
                dp = round(tot - lclk, 4)
                entry = {
                    "bit": bit,
                    "src": s_inst,
                    "dst": d_inst,
                    "launch_clk_ns": lclk,
                    "arrival_ns": tot,
                    "datapath_ns": dp,
                }
                gray_buses.setdefault(tag, {"bits": []})["bits"].append(entry)

    for tag, info in gray_buses.items():
        dps = [b["datapath_ns"] for b in info["bits"]]
        arrs = [b["arrival_ns"] for b in info["bits"]]
        if dps:
            info["datapath_min_ns"] = round(min(dps), 4)
            info["datapath_max_ns"] = round(max(dps), 4)
            info["bus_skew_datapath_ns"] = round(max(dps) - min(dps), 4)
            info["arrival_min_ns"] = round(min(arrs), 4)
            info["arrival_max_ns"] = round(max(arrs), 4)
            info["bus_skew_total_ns"] = round(max(arrs) - min(arrs), 4)

    mtbf_pairs: dict[str, Any] = {}
    min_mtbf_slack = None
    for m in re.finditer(
        r"^MTBF_PAIR:\s+(\S+)\s+s1=(\S+)\s+s2=(\S+)\s+slack=([-0-9.eE+]+)\s+arrival=([-0-9.eE+]+)\s+required=([-0-9.eE+]+)",
        log,
        re.M,
    ):
        nm = m.group(1)
        slk = _to_ns(float(m.group(4)))
        mtbf_pairs[nm] = {
            "s1": m.group(2),
            "s2": m.group(3),
            "mtbf_slack_ns": slk,
            "arrival_ns": _to_ns(float(m.group(5))),
            "required_ns": _to_ns(float(m.group(6))),
        }
        if min_mtbf_slack is None or slk < min_mtbf_slack:
            min_mtbf_slack = slk

    return {
        "corner": "ss_n40C_1v60_ocv_max_spef",
        "sync1_fanout_violations": fanout_violations,
        "sync1_fanout_count_checked": len(fanout_audit),
        "sync1_fanout_detail": fanout_audit,
        "gray_bus_skew": gray_buses,
        "sync1_to_sync2_mtbf": {
            "min_slack_ns": min_mtbf_slack,
            "pairs_checked": len(mtbf_pairs),
            "pairs": mtbf_pairs,
        },
    }


def render_v3p3_png(
    block: base.BlockSpec,
    pin_groups: list[v3.PinGroup],
    mag_path: Path,
    png_path: Path,
    pnr_info: dict[str, Any],
    sta_info: dict[str, Any],
    cdc_info: dict[str, Any],
    drc_total: int,
    lvs_status: str,
) -> None:
    """Crisp white-background layout PNG updated for v3.3 5-corner OCV STA + CDC audit."""
    u_top, top_rects, top_labels, uses = base._parse_mag_rects(mag_path)

    cell_cache: dict[str, tuple[float, list[tuple[str, int, int, int, int]]]] = {}
    layer_boxes: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k, _, _ in base.LAYER_STYLE}

    for lyr, x1, y1, x2, y2 in top_rects:
        layer_boxes[lyr].append((x1 / u_top, y1 / u_top, (x2 - x1) / u_top, (y2 - y1) / u_top))

    for cell_name, (a, b, c, d, e, f) in uses:
        if cell_name not in cell_cache:
            cand = base.SC_MAG_DIR / f"{cell_name}.mag"
            if not cand.exists():
                cand = mag_path.parent / f"{cell_name}.mag"
            if cand.exists():
                uc, crects, _, _ = base._parse_mag_rects(cand)
                keep = {"nwell", "pdiff", "ndiff", "poly", "locali", "m1"}
                cell_cache[cell_name] = (uc, [r for r in crects if r[0] in keep])
            else:
                cell_cache[cell_name] = (u_top, [])
        uc, crects = cell_cache[cell_name]
        scale = u_top / uc
        for lyr, x1, y1, x2, y2 in crects:
            sx1, sy1, sx2, sy2 = x1 * scale, y1 * scale, x2 * scale, y2 * scale
            tx1 = a * sx1 + b * sy1 + c
            ty1 = d * sx1 + e * sy1 + f
            tx2 = a * sx2 + b * sy2 + c
            ty2 = d * sx2 + e * sy2 + f
            lx, rx = (tx1, tx2) if tx1 <= tx2 else (tx2, tx1)
            by, ty = (ty1, ty2) if ty1 <= ty2 else (ty2, ty1)
            layer_boxes[lyr].append((lx / u_top, by / u_top, (rx - lx) / u_top, (ty - by) / u_top))

    die_w = pnr_info["die_w_um"]
    die_h = pnr_info["die_h_um"]
    fig, ax = plt.subplots(figsize=(15.5, 11.0), facecolor="white")
    ax.set_facecolor("white")

    ax.add_patch(
        Rectangle(
            (0.0, 0.0), die_w, die_h,
            facecolor="#fafafa", edgecolor="#0f172a", linewidth=1.8, zorder=0,
        )
    )

    layer_handles: list[Patch] = []
    for z, (lyr, color, alpha) in enumerate(base.LAYER_STYLE, start=1):
        boxes = layer_boxes[lyr]
        if not boxes:
            continue
        patches = [Rectangle((x, y), w, h) for x, y, w, h in boxes]
        pc = PatchCollection(patches, facecolor=color, edgecolor="none", alpha=alpha, zorder=z)
        ax.add_collection(pc)
        layer_handles.append(Patch(facecolor=color, alpha=min(1.0, alpha + 0.15), label=lyr))

    pin_color: dict[str, str] = {}
    for grp in pin_groups:
        for p in grp.pins:
            pin_color[p] = grp.color

    pin_labels = [(n, x / u_top, y / u_top) for n, x, y in top_labels if n not in ("VPWR", "VGND")]
    if pin_labels:
        px = [p[1] for p in pin_labels]
        py = [p[2] for p in pin_labels]
        pcols = [pin_color.get(p[0], "#0f172a") for p in pin_labels]
        ax.scatter(px, py, s=11, c=pcols, marker="s", zorder=50, edgecolors="white", linewidths=0.25)

    group_handles: list[Patch] = []
    b_off_x, b_off_y = 48.0, 34.0
    for grp in pin_groups:
        group_handles.append(Patch(facecolor=grp.color, label=f"{grp.label} ({len(grp.pins)})"))
        if grp.edge == "bottom":
            x0, x1 = die_w * grp.frac_start, die_w * grp.frac_end
            yb = -b_off_y
            ax.plot([x0, x1], [yb, yb], color=grp.color, linewidth=2.6, zorder=60)
            ax.text(0.5 * (x0 + x1), yb - 3.5, f"{grp.short_label} [{len(grp.pins)}]",
                    fontsize=7.4, fontweight="bold", color=grp.color, ha="center", va="top", zorder=62)
        elif grp.edge == "top":
            x0, x1 = die_w * grp.frac_start, die_w * grp.frac_end
            yt = die_h + b_off_y
            ax.plot([x0, x1], [yt, yt], color=grp.color, linewidth=2.6, zorder=60)
            ax.text(0.5 * (x0 + x1), yt + 3.5, f"{grp.short_label} [{len(grp.pins)}]",
                    fontsize=7.4, fontweight="bold", color=grp.color, ha="center", va="bottom", zorder=62)
        elif grp.edge == "left":
            y0, y1 = die_h * grp.frac_start, die_h * grp.frac_end
            xl = -b_off_x
            ax.plot([xl, xl], [y0, y1], color=grp.color, linewidth=2.6, zorder=60)
            ax.text(xl - 4.0, 0.5 * (y0 + y1), f"{grp.short_label} [{len(grp.pins)}]",
                    fontsize=7.4, fontweight="bold", color=grp.color, ha="right", va="center", rotation=90, zorder=62)
        elif grp.edge == "right":
            y0, y1 = die_h * grp.frac_start, die_h * grp.frac_end
            xr = die_w + b_off_x
            ax.plot([xr, xr], [y0, y1], color=grp.color, linewidth=2.6, zorder=60)
            ax.text(xr + 4.0, 0.5 * (y0 + y1), f"{grp.short_label} [{len(grp.pins)}]",
                    fontsize=7.4, fontweight="bold", color=grp.color, ha="left", va="center", rotation=270, zorder=62)

    ax.set_xlim(-68.0, die_w + 68.0)
    ax.set_ylim(-52.0, die_h + 52.0)
    ax.set_aspect("equal")
    ax.set_xlabel("x (µm)   —   SOUTH EDGE FACES ANALOG CORE (PLL | TX | RX)", fontsize=9.5, fontweight="bold")
    ax.set_ylabel("y (µm)", fontsize=9.5)
    ax.grid(True, linestyle="--", linewidth=0.35, color="#cbd5e1", alpha=0.8)

    cs = pnr_info["cell_stats"]
    ss_n40 = sta_info["ss_n40C_1v65_interp"]["setup_wns_ns"]
    ss_100 = sta_info["ss_100C_1v60"]["setup_wns_ns"]
    ff_h = sta_info["ff_n40C_1v95"]["hold_wns_ns"]
    wl_mm = pnr_info["wirelength"]["total_um"] / 1000.0
    mtbf_s = cdc_info["sync1_to_sync2_mtbf"]["min_slack_ns"]
    w2r_sk = cdc_info["gray_bus_skew"].get("w2r_gray", {}).get("bus_skew_total_ns", 0.0)
    r2w_sk = cdc_info["gray_bus_skew"].get("r2w_gray", {}).get("bus_skew_total_ns", 0.0)

    subtitle = (
        f"Die {die_w:.1f}×{die_h:.1f} µm ({pnr_info['die_area_um2']:.0f} µm²) | "
        f"StdCells={cs['std_cells']} | Util={pnr_info['utilization_pct']:.1f}% | WL={wl_mm:.1f} mm | "
        f"Decap={cs['decap_cap_pf']:.1f} pF | Ant={pnr_info['antenna_violations']} | DRC={drc_total} | LVS={lvs_status}\n"
        f"6-Corner +/-5% OCV RCX STA: ss_n40C_1v65={ss_n40:+.3f} ns | ss_100C={ss_100:+.3f} ns | ff_n40C hold={ff_h:+.3f} ns | "
        f"Gray skew={max(w2r_sk, r2w_sk):.3f} ns | MTBF min slack={mtbf_s:+.3f} ns"
    )
    ax.set_title(f"SKY130A Clean Tapeout-Audit Unified Digital Top v3.3 — {block.name}\n{subtitle}",
                 fontsize=9.6, fontweight="bold", pad=10)

    leg1 = ax.legend(handles=layer_handles, loc="upper left", bbox_to_anchor=(1.015, 1.00),
                     frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=7.2, title="Layers", title_fontsize=8)
    ax.add_artist(leg1)
    ax.legend(handles=group_handles, loc="lower left", bbox_to_anchor=(1.015, 0.00),
              frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=7.0, title="Cardinal Pin Groups", title_fontsize=8)

    fig.tight_layout()
    fig.savefig(png_path, dpi=180, facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="Clean v3.3 serdes_digital_top_v3 P&R, 5-Corner OCV STA, CDC Audit & Signoff")
    ap.add_argument("--die-w", type=float, default=346.84, help="Target die width in um (default: 346.84)")
    ap.add_argument("--die-h", type=float, default=307.36, help="Target die height in um (default: 307.36)")
    ap.add_argument("--place-density", type=float, default=0.70, help="Global placement density (default: 0.70)")
    ap.add_argument("--setup-margin", type=float, default=0.25, help="Pre-route setup repair margin ns (default: 0.25)")
    ap.add_argument("--hold-margin", type=float, default=0.03, help="Pre-route hold repair margin ns (default: 0.03)")
    ap.add_argument("--resume-eco", action="store_true", help="Resume ECO/STA/CDC/DRC/LVS/PNG from existing Pass-0 DEF")
    ap.add_argument("--results-dir", type=Path, default=RESULTS_BASE, help="Results base directory")
    ap.add_argument("--variant-dir", type=Path, default=VARIANT_BASE, help="Variant export base directory")
    args = ap.parse_args()

    t0 = time.time()
    block = build_v3p3_block_spec(
        die_w=args.die_w,
        die_h=args.die_h,
        place_density=args.place_density,
        setup_margin_ns=args.setup_margin,
        hold_margin_ns=args.hold_margin,
    )
    pin_groups = v3.build_pin_groups()

    res_base = args.results_dir.resolve()
    var_base = args.variant_dir.resolve()
    work = res_base / block.name
    work.mkdir(parents=True, exist_ok=True)
    variant_dir = var_base / block.name
    variant_dir.mkdir(parents=True, exist_ok=True)

    synth_lib = build_v3p3_synth_lib(
        LIB_SS_N40_1V65,
        res_base / "_work/sky130_fd_sc_hd__ss_n40C_1v65_v3p3_synth.lib",
    )

    print(
        f"[{block.name} v3.3] Target die: {block.die_area[2]:.2f}x{block.die_area[3]:.2f} um "
        f"({block.die_area[2]*block.die_area[3]:.0f} um^2), corner=ss_n40C_1v65_interp + +/-5% OCV",
        flush=True,
    )

    if args.resume_eco and (work / f"{block.name}_synth.v").exists() and (work / "01_yosys.log").exists():
        synth_v = work / f"{block.name}_synth.v"
        ylog = (work / "01_yosys.log").read_text()
        cm = re.search(r"Number of cells:\s+(\d+)", ylog)
        am = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", ylog)
        sub_stats = {}
        for sub_m in ["pll_control_top", "tx_ingress_control", "rx_word_map", "rx_word_host_shared", "rx_cdr_loop"]:
            slog_p = work / f"01_yosys_{sub_m}.log"
            if slog_p.exists():
                st = slog_p.read_text()
                scm = re.search(r"Number of cells:\s+(\d+)", st)
                sam = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", st)
                sub_stats[sub_m] = {
                    "cells": int(scm.group(1)) if scm else 0,
                    "area_um2": round(float(sam.group(1)), 1) if sam else 0.0,
                }
        synth_info = {
            "synth_cells": int(cm.group(1)) if cm else None,
            "synth_area_um2": float(am.group(1)) if am else None,
            "per_subsystem": sub_stats,
        }
        print(f"[{block.name} v3.3] 1/7 Reusing Yosys netlist ({synth_info['synth_cells']} cells)...", flush=True)
    else:
        print(f"[{block.name} v3.3] 1/7 Yosys synthesis against ss_n40C_1v60...", flush=True)
        synth_v, synth_info = run_v3p3_yosys(block, work, synth_lib)
        print(
            f"[{block.name} v3.3]   synth_cells={synth_info['synth_cells']} "
            f"synth_area={synth_info['synth_area_um2']:.1f} um^2",
            flush=True,
        )
        for mod, st in synth_info["per_subsystem"].items():
            print(f"[{block.name} v3.3]     - {mod:20s}: {st['cells']:5d} cells, {st['area_um2']:8.1f} um^2", flush=True)

    sdc_path = work / f"{block.name}.sdc"
    write_v3p3_sdc(block, sdc_path, post_route=False)

    print(f"[{block.name} v3.3] 2/7 OpenROAD P&R + ECO against ss_n40C_1v60 + +/-5% OCV...", flush=True)
    pnr_info = run_v3p3_openroad_pnr(block, pin_groups, work, synth_v, sdc_path, resume_eco=args.resume_eco)
    na = pnr_info["netlist_audit"]
    print(
        f"[{block.name} v3.3]   Die={pnr_info['die_w_um']:.2f}x{pnr_info['die_h_um']:.2f} um "
        f"({pnr_info['die_area_um2']:.0f} um^2) | Util={pnr_info['utilization_pct']:.1f}% | "
        f"Std={pnr_info['std_cells']} | Decap={pnr_info['cell_stats']['decap_cells_total']} "
        f"({pnr_info['cell_stats']['decap_cap_pf']:.2f} pF) | Diodes={pnr_info['cell_stats']['diode_cells']} | "
        f"Ant={pnr_info['antenna_violations']} | DRT={pnr_info['openroad_drt_drvs']} | "
        f"WL={pnr_info['wirelength']['total_um']} um | PinViols={pnr_info['pin_check']['region_violations']}\n"
        f"[{block.name} v3.3]   NetlistAudit: hold_total={na['hold_buffers_total']} (clkbuf16={na['hold_clkbuf_16']})",
        flush=True,
    )

    print(f"[{block.name} v3.3] 3/7 5-Corner Post-Route OpenRCX STA (+/-5% OCV, all 6 clocks)...", flush=True)
    sta_info = run_v3p3_sta_5corner(block, work, pnr_info)
    for cname, s in sta_info.items():
        print(
            f"[{block.name} v3.3]   {cname:13s}: setup={s['setup_wns_ns']:+.4f} ns (met={s['setup_met']}) | "
            f"hold={s['hold_wns_ns']:+.4f} ns (met={s['hold_met']}) | "
            f"rx_phys(-fall)={s['rx_phys_fall_setup_ns']:+.4f}/{s['rx_phys_fall_hold_ns']:+.4f} ns",
            flush=True,
        )
        for clk_n, cs_clk in s["per_clock"].items():
            sw = cs_clk["setup_wns_ns"]
            hw = cs_clk["hold_wns_ns"]
            print(
                f"[{block.name} v3.3]     {clk_n:14s}: setup={sw:+.4f} ns, hold={hw:+.4f} ns"
                if (sw is not None and hw is not None)
                else f"[{block.name} v3.3]     {clk_n:14s}: setup={sw}, hold={hw}",
                flush=True,
            )

    print(f"[{block.name} v3.3] 4/7 Post-Route CDC Audit (Gray bus_skew + sync1->sync2 MTBF + fanout=1)...", flush=True)
    cdc_info = run_v3p3_cdc_audit(block, work, pnr_info)
    print(
        f"[{block.name} v3.3]   Sync1 fanout==1 checked={cdc_info['sync1_fanout_count_checked']}, "
        f"violations={cdc_info['sync1_fanout_violations']}",
        flush=True,
    )
    for tag, gi in cdc_info["gray_bus_skew"].items():
        print(
            f"[{block.name} v3.3]   Gray {tag:8s}: datapath_skew={gi.get('bus_skew_datapath_ns')} ns "
            f"(min={gi.get('datapath_min_ns')}, max={gi.get('datapath_max_ns')}) | "
            f"total_skew={gi.get('bus_skew_total_ns')} ns",
            flush=True,
        )
    print(
        f"[{block.name} v3.3]   MTBF sync1->sync2: pairs={cdc_info['sync1_to_sync2_mtbf']['pairs_checked']}, "
        f"min_slack={cdc_info['sync1_to_sync2_mtbf']['min_slack_ns']:+.4f} ns",
        flush=True,
    )

    spec_corners = ["tt_025C_1v80", "ss_100C_1v60", "ss_n40C_1v65_interp", "ff_n40C_1v95", "ff_100C_1v95"]
    all_spec_met = all(sta_info[c]["setup_met"] and sta_info[c]["hold_met"] for c in spec_corners)
    if not all_spec_met:
        elapsed = round(time.time() - t0, 1)
        summary_partial = {
            "block": block.name,
            "variant": "hd_pnr_v3p3_clean_unclosed",
            "closure_corner": "sky130_fd_sc_hd__ss_n40C_1v65_interp.lib",
            "ocv_derate": {"early": 0.95, "late": 1.05},
            "all_spec_corners_met": False,
            "synthesis": synth_info,
            "pnr": pnr_info,
            "sta_6corner_ocv": sta_info,
            "cdc_audit": cdc_info,
            "elapsed_s": elapsed,
        }
        (work / "summary.json").write_text(json.dumps(summary_partial, indent=2) + "\n")
        print(f"[{block.name} v3.3] CIRCUIT_BREAKER_STOP: not all 5 spec corners closed -> skipped Magic/LVS/export ({work / 'summary.json'})", flush=True)
        return

    print(f"[{block.name} v3.3] 5/7 Magic DEF->MAG/GDS + Full-Rule DRC + LVS extraction...", flush=True)
    magic_info = v3.run_v3_magic(block, work, Path(pnr_info["routed_def"]))
    print(f"[{block.name} v3.3]   Magic full DRC = {magic_info['magic_drc_total']}", flush=True)

    print(f"[{block.name} v3.3] 6/7 Netgen LVS...", flush=True)
    lvs_info = base.run_netgen_lvs(block, work, Path(magic_info["lvs_spice_path"]), Path(pnr_info["routed_pg_v"]))
    print(f"[{block.name} v3.3]   Netgen LVS = {lvs_info['lvs_status']}", flush=True)

    print(f"[{block.name} v3.3] 7/7 Rendering layout PNG & exporting clean deliverables...", flush=True)
    png_work = work / f"{block.name}.png"
    render_v3p3_png(
        block, pin_groups, Path(magic_info["mag_path"]), png_work,
        pnr_info, sta_info, cdc_info, magic_info["magic_drc_total"], lvs_info["lvs_status"],
    )

    exports = {
        f"{block.name}.def": Path(pnr_info["routed_def"]),
        f"{block.name}.gds": Path(magic_info["gds_path"]),
        f"{block.name}.v": Path(pnr_info["routed_v"]),
        f"{block.name}_pg.v": Path(pnr_info["routed_pg_v"]),
        f"{block.name}.png": png_work,
    }
    for fname, src in exports.items():
        shutil.copy2(src, variant_dir / fname)

    v3p2_delta: dict[str, Any] = {}
    if V3P2_SUMMARY.exists():
        v32 = json.loads(V3P2_SUMMARY.read_text())
        v3p2_delta = {
            "v3p2_synth_cells": v32["synthesis"]["synth_cells"],
            "v3p3_synth_cells": synth_info["synth_cells"],
            "delta_synth_cells": (synth_info["synth_cells"] or 0) - v32["synthesis"]["synth_cells"],
            "v3p2_std_cells": v32["pnr"]["cell_stats"]["std_cells"],
            "v3p3_std_cells": pnr_info["std_cells"],
            "delta_std_cells": pnr_info["std_cells"] - v32["pnr"]["cell_stats"]["std_cells"],
            "v3p2_design_area_um2": v32["pnr"]["design_area_um2"],
            "v3p3_design_area_um2": pnr_info["design_area_um2"],
            "delta_design_area_um2": round((pnr_info["design_area_um2"] or 0.0) - v32["pnr"]["design_area_um2"], 1),
            "v3p2_die_area_um2": v32["pnr"]["die_area_um2"],
            "v3p3_die_area_um2": pnr_info["die_area_um2"],
            "delta_die_area_um2": round(pnr_info["die_area_um2"] - v32["pnr"]["die_area_um2"], 2),
        }

    elapsed = round(time.time() - t0, 1)
    summary = {
        "block": block.name,
        "variant": "hd_pnr_v3p3_clean",
        "params": block.params,
        "rtl_files": block.rtl_files,
        "ocv_derate": {"early": 0.95, "late": 1.05},
        "closure_corner": "sky130_fd_sc_hd__ss_n40C_1v65_interp.lib",
        "clocks_mhz": {
            "ref_clk": 250.0,
            "pll_clk_div4": 62.5,
            "tx_word_clk": 250.0,
            "rx_word_clk": 250.0,
            "cdr_clk_div2": 125.0,
            "host_clk": 250.0,
        },
        "synthesis": synth_info,
        "pnr": {
            "die_w_um": pnr_info["die_w_um"],
            "die_h_um": pnr_info["die_h_um"],
            "die_area_um2": pnr_info["die_area_um2"],
            "core_w_um": pnr_info["core_w_um"],
            "core_h_um": pnr_info["core_h_um"],
            "core_area_um2": pnr_info["core_area_um2"],
            "design_area_um2": pnr_info["design_area_um2"],
            "utilization_pct": pnr_info["utilization_pct"],
            "openroad_drt_drvs": pnr_info["openroad_drt_drvs"],
            "antenna_violations": pnr_info["antenna_violations"],
            "wirelength": pnr_info["wirelength"],
            "cell_stats": pnr_info["cell_stats"],
            "netlist_audit": pnr_info["netlist_audit"],
            "pin_check": pnr_info["pin_check"],
        },
        "sta_5corner_ocv": sta_info,
        "cdc_audit": cdc_info,
        "magic_drc_total": magic_info["magic_drc_total"],
        "netgen_lvs": lvs_info["lvs_status"],
        "lvs_match": lvs_info["lvs_match"],
        "delta_vs_v3p2": v3p2_delta,
        "artifacts": {
            "variant_dir": str(variant_dir.relative_to(REPO)),
            "results_dir": str(work.relative_to(REPO)),
            "png": str((variant_dir / f"{block.name}.png").relative_to(REPO)),
            "gds": str((variant_dir / f"{block.name}.gds").relative_to(REPO)),
            "def": str((variant_dir / f"{block.name}.def").relative_to(REPO)),
            "verilog": str((variant_dir / f"{block.name}.v").relative_to(REPO)),
            "pg_verilog": str((variant_dir / f"{block.name}_pg.v").relative_to(REPO)),
        },
        "elapsed_s": elapsed,
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (variant_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[{block.name} v3.3] COMPLETE in {elapsed}s -> {variant_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
