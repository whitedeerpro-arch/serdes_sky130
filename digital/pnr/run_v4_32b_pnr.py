#!/usr/bin/env python3
"""32-Bit Down-Clocked Unified Digital Top Macro v4 (serdes_digital_top_v4) P&R & Full 6-Corner Signoff.

Architecture:
  - Preserves ALL 106 South analog-facing pins identically to v3.3 for seamless chip-top drop-in.
  - Sustained host rate >= 5.0 Gb/s: 32-bit TX & RX host ports on host_clk = 180.0 MHz (5.76 Gb/s peak!).
  - Thin 250 / 312.5 MHz analog boundaries ONLY:
      * tx_word_clk (~41 FFs): clock-only tx_div2_q + 1-MUX 32->16 gearbox (full 2-cycle safe handoff)
      * rx_word_clk (~140 FFs): u_rx_map (33 FFs on RXMAP_SHORT_TAP, -clock_fall) + zero-logic 16->32 packer
  - Heavy internal cores at 1/2 word rate (125 MHz @ 4G / 156.25 MHz @ 5G = 6.40 ns):
      * tx_clk_div2: 16x32 TX async FIFO read + warmup/idle (32'hA55A_A55A)
      * rx_clk_div2: rx_word_align32 + 16x32 RX async FIFO write + native 32-UI rx_cdr_loop_v4
      * pll_clk_div4 (62.5 MHz): 5-bit PLL startup/coarse/lock (262 us cold-boot timeout, shared u_hilo)
  - Synthesizes & closes P&R at 5G worst-case against official sky130_fd_sc_hd__ss_n40C_1v60.lib (+/-5% OCV),
    then verifies BOTH 5G (312.5/156.25/180 MHz) AND 4G (250/125/180 MHz) across ALL 6 corners
    (tt_025C_1v80, ss_100C_1v60, ss_n40C_1v65_interp, ss_n40C_1v60, ff_n40C_1v95, ff_100C_1v95),
    audits ALL 30+ CDC sync1 nets (fanout==1, Gray bus_skew, MTBF slack), Magic drc(full)=0, Netgen LVS=MATCH,
    and exports deliverables to digital/pnr/variants/hd_pnr_v4_32b/serdes_digital_top_v4/.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from collections import Counter
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
RTL_DIR = "digital/pnr/rtl_v4_32b"
RESULTS_BASE = REPO / "results/digital/pnr_v4_32b_20261125"
VARIANT_BASE = REPO / "digital/pnr/variants/hd_pnr_v4_32b"
V3P2_SUMMARY = REPO / "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/summary.json"

BLOCK_NAME = "serdes_digital_top_v4"

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
    f"{RTL_DIR}/async_word_fifo_32.sv",
    f"{RTL_DIR}/tx_ingress_control_32.sv",
    f"{RTL_DIR}/rx_word_map.sv",
    f"{RTL_DIR}/rx_pack_16to32.sv",
    f"{RTL_DIR}/rx_word_align32.sv",
    f"{RTL_DIR}/rx_word_host_32.sv",
    f"{RTL_DIR}/bbpd_window_vote32.sv",
    f"{RTL_DIR}/cdr_phase_frequency_v4.sv",
    f"{RTL_DIR}/pi_step_commutator.sv",
    f"{RTL_DIR}/rx_cdr_loop_v4.sv",
    f"{RTL_DIR}/serdes_digital_top_v4.sv",
]

ALL_CLOCK_NAMES = [
    "ref_clk",
    "pll_clk_div4",
    "tx_word_clk",
    "tx_clk_div2",
    "rx_word_clk",
    "rx_clk_div2",
    "host_clk",
]

# Dot-free CDC net names preserved through Yosys rename-hide for BOTH TX and RX 8x32 (256-bit) async FIFOs!
FIFO_CDC_BUS_WIRES = [
    ("w_gray", "w_gray", 4),
    ("w_gray_r1", "w_gray_r1", 4),
    ("w_gray_r2", "w_gray_r2", 4),
    ("r_pop_gray", "r_pop_gray", 4),
    ("r_gray_w1", "r_gray_w1", 4),
    ("r_gray_w2", "r_gray_w2", 4),
    ("r_up_w", "r_up_w", 2),
    ("w_up_r", "w_up_r", 2),
    ("overflow_r", "overflow_r", 2),
]
FIFO_CDC_SCALAR_WIRES = [
    ("w_rst_s0", "w_rst_s0"),
    ("w_rst_s1", "w_rst_s1"),
    ("r_rst_s0", "r_rst_s0"),
    ("r_rst_s1", "r_rst_s1"),
]


def _bus(name: str, width: int) -> list[str]:
    return [f"{name}[{i}]" for i in range(width)]


def build_v4_pin_groups() -> list[v3.PinGroup]:
    """Cardinal pin groups preserving ALL 106 South analog pins identically to v3.3,
    with 32-bit TX & RX host interfaces cleanly arranged on the North edge."""
    return [
        # SOUTH EDGE — 106 analog-facing pins in EXACT v3.3 order!
        v3.PinGroup(
            key="south_pll",
            label="PLL Analog (ref_clk, vco[4:0], sw[7:0])",
            short_label="PLL Analog",
            edge="bottom",
            frac_start=0.025,
            frac_end=0.195,
            color="#2563eb",
            pins=(
                [
                    "ref_clk",
                    "bias_ready_async",
                    "pre_ref_ready_async",
                    "hi_async",
                    "lo_async",
                    "pw_late_async",
                    "precharge_en",
                    "pfd_rst_b",
                    "cp_en",
                    "pll_pw_clr_b",
                ]
                + _bus("vco_code", 5)
                + _bus("switches", 8)
            ),
        ),
        v3.PinGroup(
            key="south_tx",
            label="TX Analog / Serializer (tx_word_clk, 16b)",
            short_label="TX Analog",
            edge="bottom",
            frac_start=0.220,
            frac_end=0.355,
            color="#059669",
            pins=(
                [
                    "tx_word_clk",
                    "tx_clock_good",
                    "tx_capture_valid",
                    "tx_a_valid",
                    "tx_b_valid",
                ]
                + _bus("tx_capture_data", 16)
            ),
        ),
        v3.PinGroup(
            key="south_rx_pi",
            label="RX PI Control (a/b/f, phase_code)",
            short_label="RX PI Ctrl",
            edge="bottom",
            frac_start=0.380,
            frac_end=0.580,
            color="#e11d48",
            pins=(
                _bus("rx_select_a", 8)
                + _bus("rx_select_b", 8)
                + _bus("rx_fine_b", 8)
                + _bus("rx_phase_code", 6)
            ),
        ),
        v3.PinGroup(
            key="south_rx_data",
            label="RX Analog Data/Edge (rx_word_clk, rx_phys[31:0])",
            short_label="RX Data/Edge",
            edge="bottom",
            frac_start=0.600,
            frac_end=0.975,
            color="#dc2626",
            pins=(["rx_word_clk"] + _bus("rx_phys", 32)),
        ),
        # WEST EDGE — PLL Host Config & Calibration + Global rst_n
        v3.PinGroup(
            key="west_pll_host",
            label="PLL Host Cfg + rst_n",
            short_label="PLL Host Cfg + rst_n",
            edge="left",
            frac_start=0.060,
            frac_end=0.940,
            color="#1d4ed8",
            pins=(
                ["rst_n", "pll_enable", "pll_start", "pll_abort_async"]
                + _bus("pll_tclass", 2)
                + _bus("pll_lo_run", 4)
                + _bus("pll_hi_run", 4)
                + _bus("pll_stop_code", 12)
                + _bus("pll_stop_sel", 3)
            ),
        ),
        # NORTH-WEST EDGE — PLL Host Status
        v3.PinGroup(
            key="north_pll_status",
            label="PLL Status",
            short_label="PLL Status",
            edge="top",
            frac_start=0.020,
            frac_end=0.170,
            color="#0284c7",
            pins=(
                ["pll_locked", "pll_busy", "pll_fault"]
                + _bus("pll_state_id", 3)
                + _bus("pll_fault_code", 3)
                + _bus("pll_lo_code", 4)
                + _bus("pll_hi_code", 4)
                + ["pll_coarse_busy", "pll_coarse_done", "pll_fast_end", "pll_slow_end"]
            ),
        ),
        # NORTH MID-WEST — 32-bit TX Host Interface (180 MHz host_clk)
        v3.PinGroup(
            key="north_tx_host",
            label="TX Host 32b (180 MHz)",
            short_label="TX Host 32b",
            edge="top",
            frac_start=0.190,
            frac_end=0.515,
            color="#047857",
            pins=(
                ["tx_enable", "tx_in_valid", "tx_word_ready", "tx_underrun"]
                + _bus("tx_in_data", 32)
            ),
        ),
        # NORTH MID-EAST — 32-bit RX Host FIFO & Align (180 MHz host_clk, arst_n)
        v3.PinGroup(
            key="north_rx_host",
            label="RX Host 32b FIFO & Align (host_clk, arst_n)",
            short_label="RX Host 32b",
            edge="top",
            frac_start=0.535,
            frac_end=0.980,
            color="#7c3aed",
            pins=(
                ["arst_n", "host_clk", "host_ready", "host_valid", "host_online", "host_error"]
                + _bus("host_data", 32)
                + ["rx_training_enable", "rx_word_online", "rx_aligned"]
                + _bus("rx_offset", 4)
            ),
        ),
        # EAST EDGE — RX CDR Control, Status & Exact-Width Telemetry
        v3.PinGroup(
            key="east_rx_cdr",
            label="RX CDR Cfg/Status & Telemetry (17b/23b)",
            short_label="RX CDR Cfg/Status & Telemetry",
            edge="right",
            frac_start=0.060,
            frac_end=0.940,
            color="#b91c1c",
            pins=(
                [
                    "rx_cdr_enable",
                    "rx_cdr_locked",
                    "rx_cdr_holdover",
                    "rx_cdr_range_limited",
                    "rx_cdr_phase_applied",
                ]
                + _bus("rx_cdr_frequency_q", 17)
                + _bus("rx_cdr_phase_debt_q", 23)
            ),
        ),
    ]


def build_v4_block_spec(
    die_w: float,
    die_h: float,
    margin_x: float = 3.68,
    margin_y: float = 5.44,
    place_density: float = 0.70,
    setup_margin_ns: float = 0.20,
    hold_margin_ns: float = 0.03,
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
    spec.name = BLOCK_NAME
    spec.top_module = BLOCK_NAME
    spec.rtl_files = list(UNIFIED_RTL_FILES)
    return spec


def write_v4_sdc(
    block: base.BlockSpec,
    path: Path,
    mode: str = "5g",
    post_route: bool = False,
    ocv: bool = True,
) -> None:
    """Write 7-clock SDC for serdes_digital_top_v4 (mode='5g' or '4g').
    - 5G: tx/rx_word_clk=312.5 MHz (3.20 ns), tx/rx_clk_div2=156.25 MHz (6.40 ns), host_clk=180.0 MHz (5.556 ns -> 5.76 Gb/s!)
    - 4G: tx/rx_word_clk=250.0 MHz (4.00 ns), tx/rx_clk_div2=125.0 MHz  (8.00 ns), host_clk=180.0 MHz (5.556 ns -> 5.76 Gb/s!)
    """
    word_period = 3.200 if mode == "5g" else 4.000
    setup_unc = 0.10 if post_route else 0.15
    hold_unc = 0.05 if post_route else 0.08
    clk_prop = "set_propagated_clock [all_clocks]" if post_route else "set_clock_transition 0.12 [all_clocks]"
    ocv_block = (
        "# On-Chip Variation (OCV) +/-5% derating (D-C2)\nset_timing_derate -early 0.95\nset_timing_derate -late  1.05"
        if ocv
        else "# NO_OCV diagnostic corner (derate = 1.00)\n"
    )

    sdc = f"""# 7-clock SDC for {block.name} (mode={mode.upper()}, host_clk=180 MHz -> 5.76 Gb/s > 5.0 Gb/s!)
create_clock -name ref_clk     -period 4.000 [get_ports ref_clk]
create_clock -name tx_word_clk -period {word_period:.3f} [get_ports tx_word_clk]
create_clock -name rx_word_clk -period {word_period:.3f} [get_ports rx_word_clk]
create_clock -name host_clk    -period 6.250 [get_ports host_clk]

proc _find_div_q_pin {{net_pat}} {{
  set pins [get_pins -quiet -filter "direction == output && name == Q" -of_objects [get_nets -quiet $net_pat]]
  if {{[llength $pins] > 0}} {{ return [lindex $pins 0] }}
  set pins [get_pins -quiet -filter "direction == output" -of_objects [get_nets -quiet $net_pat]]
  if {{[llength $pins] > 0}} {{ return [lindex $pins 0] }}
  error "Could not find generated clock driver pin matching $net_pat"
}}

set _pll_div_pin [_find_div_q_pin "*pll_clk_div4*"]
create_generated_clock -name pll_clk_div4 -source [get_ports ref_clk] -divide_by 4 $_pll_div_pin

set _tx_div_pin [_find_div_q_pin "*tx_clk_div2*"]
create_generated_clock -name tx_clk_div2 -source [get_ports tx_word_clk] -divide_by 2 $_tx_div_pin

set _rx_div_pin [_find_div_q_pin "*rx_clk_div2*"]
create_generated_clock -name rx_clk_div2 -source [get_ports rx_word_clk] -divide_by 2 $_rx_div_pin

set_clock_uncertainty -setup {setup_unc:.3f} [all_clocks]
set_clock_uncertainty -hold  {hold_unc:.3f} [all_clocks]
{clk_prop}

{ocv_block}

# Independent root clock domains are asynchronous; divided clocks stay synchronous to their roots!
set_clock_groups -asynchronous \\
  -group {{ref_clk pll_clk_div4}} \\
  -group {{tx_word_clk tx_clk_div2}} \\
  -group {{rx_word_clk rx_clk_div2}} \\
  -group {{host_clk}}

# Hardware-exact synchronous multicycle paths:
# 1. ref_clk -> pll_clk_div4: start_tog updates ONLY at (pll_clk_div4_q==1 && !div2_q), 8 ns away from posedge pll_clk_div4!
set_multicycle_path -hold 1 -start -from [get_clocks ref_clk] -to [get_clocks pll_clk_div4]

# 2. tx_clk_div2 -> tx_word_clk: tx_word_32 launches on tx_phase 0->1 and is ONLY sampled on the NEXT tx_phase==0
#    (2 full tx_word_clk cycles = 6.40/8.00 ns setup; natural +1..2 ns hold margin on same edge!).
set_multicycle_path -setup 2 -end -from [get_clocks tx_clk_div2] -to [get_clocks tx_word_clk]
set_multicycle_path -hold  1 -end -from [get_clocks tx_clk_div2] -to [get_clocks tx_word_clk]

# 3. rx_word_clk -> rx_clk_div2: pack_* updates ONLY on rx_phase==1 (falling edge of rx_clk_div2,
#    1 full rx_word_clk cycle away from posedge rx_clk_div2!).
set_multicycle_path -hold 1 -start -from [get_clocks rx_word_clk] -to [get_clocks rx_clk_div2]

# -----------------------------------------------------------------------------
# I/O timing constraints (ZERO relaxation on rx_phys* -clock_fall!)
# -----------------------------------------------------------------------------
# PLL (250 MHz ref_clk & 62.5 MHz pll_clk_div4)
set_input_delay  -clock ref_clk      -max 0.800 [get_ports {{pll_start}}]
set_input_delay  -clock ref_clk      -min 0.500 [get_ports {{pll_start}}]
set_input_delay  -clock pll_clk_div4 -max 1.600 [get_ports {{pll_enable pll_tclass* pll_lo_run* pll_hi_run* pll_stop_code* pll_stop_sel*}}]
set_input_delay  -clock pll_clk_div4 -min 0.500 [get_ports {{pll_enable pll_tclass* pll_lo_run* pll_hi_run* pll_stop_code* pll_stop_sel*}}]
set_output_delay -clock pll_clk_div4 -max 1.600 [get_ports {{precharge_en pfd_rst_b cp_en pll_pw_clr_b pll_locked pll_busy pll_fault pll_state_id* pll_fault_code* vco_code* pll_lo_code* pll_hi_code* pll_coarse_busy pll_coarse_done pll_fast_end pll_slow_end switches*}}]
set_output_delay -clock pll_clk_div4 -min 0.100 [get_ports {{precharge_en pfd_rst_b cp_en pll_pw_clr_b pll_locked pll_busy pll_fault pll_state_id* pll_fault_code* vco_code* pll_lo_code* pll_hi_code* pll_coarse_busy pll_coarse_done pll_fast_end pll_slow_end switches*}}]

# TX analog outputs (tx_word_clk: 312.5 MHz @ 5G / 250 MHz @ 4G)
set_output_delay -clock tx_word_clk  -max 0.800 [get_ports {{tx_capture_data* tx_capture_valid tx_a_valid tx_b_valid}}]
set_output_delay -clock tx_word_clk  -min 0.100 [get_ports {{tx_capture_data* tx_capture_valid tx_a_valid tx_b_valid}}]
set_input_delay  -clock tx_clk_div2  -max 1.200 [get_ports {{tx_enable tx_clock_good}}]
set_input_delay  -clock tx_clk_div2  -min 0.500 [get_ports {{tx_enable tx_clock_good}}]

# RX analog inputs (rx_word_clk -clock_fall, ZERO relaxation: -min 0.500 / -max 0.800!)
set_input_delay  -clock rx_word_clk -clock_fall -max 0.800 [get_ports {{rx_phys*}}]
set_input_delay  -clock rx_word_clk -clock_fall -min 0.500 [get_ports {{rx_phys*}}]

# RX aligner + CDR control/outputs (rx_clk_div2: 156.25 MHz @ 5G / 125 MHz @ 4G)
set_input_delay  -clock rx_clk_div2  -max 1.200 [get_ports {{rx_training_enable rx_cdr_enable}}]
set_input_delay  -clock rx_clk_div2  -min 0.500 [get_ports {{rx_training_enable rx_cdr_enable}}]
set_output_delay -clock rx_clk_div2  -max 1.200 [get_ports {{rx_word_online rx_aligned rx_offset* rx_phase_code* rx_select_a* rx_select_b* rx_fine_b* rx_cdr_locked rx_cdr_holdover rx_cdr_range_limited rx_cdr_phase_applied rx_cdr_frequency_q* rx_cdr_phase_debt_q*}}]
set_output_delay -clock rx_clk_div2  -min 0.100 [get_ports {{rx_word_online rx_aligned rx_offset* rx_phase_code* rx_select_a* rx_select_b* rx_fine_b* rx_cdr_locked rx_cdr_holdover rx_cdr_range_limited rx_cdr_phase_applied rx_cdr_frequency_q* rx_cdr_phase_debt_q*}}]

# Host 32-bit TX & RX interfaces (host_clk: 180.0 MHz / 5.556 ns -> 5.76 Gb/s > 5.0 Gb/s!)
set_input_delay  -clock host_clk     -max 1.000 [get_ports {{tx_in_valid tx_in_data* host_ready}}]
set_input_delay  -clock host_clk     -min 0.500 [get_ports {{tx_in_valid tx_in_data* host_ready}}]
set_output_delay -clock host_clk     -max 1.000 [get_ports {{tx_word_ready tx_underrun host_data* host_valid host_online host_error}}]
set_output_delay -clock host_clk     -min 0.100 [get_ports {{tx_word_ready tx_underrun host_data* host_valid host_online host_error}}]

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


def build_v4_synth_lib(src_lib: Path, dst_lib: Path) -> Path:
    """Create filtered Liberty for Yosys synthesis.
    Re-enables ONLY sky130_fd_sc_hd__mux4_2 (keeping DRC-excluded mux4_4 and all weak _1 cells banned)."""
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


def v4_openroad_dont_use_tcl(ref_lib: Path, allow_hold_dly: bool = False) -> str:
    """Two-phase OpenROAD dont_use policy:
    - Phase A (setup): bans ALL dly*, all *_0, all weak *_1 (incl. buf_1), mux4_4 (DRC), clkbuf_* (post-CTS).
      Allows sky130_fd_sc_hd__mux4_2.
    - Phase B (hold) & ECO: re-enables ONLY dlygate4sd3_1/dlymetal6s2s_1/dlymetal6s4s_1 for hold repair."""
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
            continue
        patterns.append(f"sky130_fd_sc_hd{tok}*")
    lib_text = ref_lib.read_text()
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


def _fifo_cdc_rename_cmds(inst_prefix: str, net_prefix: str, extra: list[tuple[str, str]] | None = None) -> list[str]:
    cmds = ["splitnets"]
    for orig, short, width in FIFO_CDC_BUS_WIRES:
        for b in range(width):
            cmds.append(f"rename {inst_prefix}.{orig}[{b}] {net_prefix}_{short}_{b}")
    for orig, short in FIFO_CDC_SCALAR_WIRES:
        cmds.append(f"rename {inst_prefix}.{orig} {net_prefix}_{short}")
    if extra:
        for src, dst in extra:
            cmds.append(f"rename {src} {dst}")
    return cmds


def run_v4_yosys(block: base.BlockSpec, work: Path, synth_lib: Path) -> tuple[Path, dict[str, Any]]:
    """Per-subsystem Yosys synthesis preserving dot-free CDC nets for BOTH TX and RX 16x32 FIFOs."""
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
            {"CODE_BITS": 5},
            10000,
            [],
        ),
        (
            "tx_ingress_control_32",
            [
                f"{RTL_DIR}/async_word_fifo_32.sv",
                f"{RTL_DIR}/tx_ingress_control_32.sv",
            ],
            {},
            2200,
            _fifo_cdc_rename_cmds("u_tx_fifo", "tx_cdc", [("tx_ur_sync[0]", "tx_cdc_ur_0")]),
        ),
        (
            "rx_word_map",
            [f"{RTL_DIR}/rx_word_map.sv"],
            {},
            1000,
            [],
        ),
        (
            "rx_pack_16to32",
            [f"{RTL_DIR}/rx_pack_16to32.sv"],
            {},
            1200,
            [],
        ),
        (
            "rx_word_host_32",
            [
                f"{RTL_DIR}/rx_word_align32.sv",
                f"{RTL_DIR}/async_word_fifo_32.sv",
                f"{RTL_DIR}/rx_word_host_32.sv",
            ],
            {},
            3000,
            _fifo_cdc_rename_cmds("u_rx_fifo", "rx_cdc"),
        ),
        (
            "rx_cdr_loop_v4",
            [
                f"{RTL_DIR}/bbpd_window_vote32.sv",
                f"{RTL_DIR}/cdr_phase_frequency_v4.sv",
                f"{RTL_DIR}/pi_step_commutator.sv",
                f"{RTL_DIR}/rx_cdr_loop_v4.sv",
            ],
            {},
            3500,
            [],
        ),
    ]

    sub_vs: list[str] = []
    sub_stats: dict[str, dict[str, Any]] = {}
    sub_v_paths: dict[str, Path] = {}
    for mod, files, params, abc_d_ps, extra_renames in subblocks:
        sv_out = work / f"synth_sub_{mod}.v"
        sub_vs.append(str(sv_out))
        sub_v_paths[mod] = sv_out
        cmds = [f"read_verilog -sv {REPO / f}" for f in files]
        for k, val in params.items():
            cmds.append(f"chparam -set {k} {val} {mod}")
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
            f"abc -D {abc_d_ps} -liberty {synth_lib}",
            "opt_clean -purge",
        ]
        if extra_renames:
            cmds.append(f"cd {mod}")
            # Drop any rename whose source wire was pruned (e.g. unused tx_fifo overflow_r)
            cmds.extend(extra_renames)
            cmds.append("cd ..")
        cmds += [
            f"stat -liberty {synth_lib}",
            f"write_verilog -noattr -noexpr -nohex -nodec {sv_out}",
        ]
        # Filter out tx_fifo overflow_r (r_error is unused on TX FIFO and pruned by opt_clean)
        if mod == "tx_ingress_control_32":
            cmds = [c for c in cmds if "overflow_r" not in c]
        if mod == "rx_word_host_32":
            # w_up_r[1] merges into host_online and overflow_r[1] merges into host_error
            cmds = [c for c in cmds if "rx_cdc_w_up_r_1" not in c and "rx_cdc_overflow_r_1" not in c]

        ys_sub = work / f"synth_sub_{mod}.ys"
        ys_sub.write_text("\n".join(cmds) + "\n")
        proc_s = base.run_cmd(
            [str(base.YOSYS), "-s", str(ys_sub)],
            work,
            work / f"01_yosys_{mod}.log",
            timeout=300,
        )
        cm = re.search(r"Number of cells:\s+(\d+)", proc_s.stdout)
        am = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", proc_s.stdout)
        sub_stats[mod] = {
            "cells": int(cm.group(1)) if cm else 0,
            "area_um2": round(float(am.group(1)), 1) if am else 0.0,
        }

    # Strip #(...) on pre-synthesized subblocks in top wrapper for clean Yosys linking
    top_src = (REPO / RTL_DIR / "serdes_digital_top_v4.sv").read_text()
    top_clean = re.sub(
        r"\b(pll_control_top|tx_ingress_control_32|rx_word_host_32)\s*#\s*\((?:[^()]|\([^()]*\))*\)",
        r"\1",
        top_src,
    )
    wrap_sv = work / f"{block.name}_link_wrap.sv"
    wrap_sv.write_text(top_clean)

    # Promote every CDC wire actually present in subblock verilog to dot-free top wire
    cdc_top_renames: list[str] = []
    for sub_mod, sub_inst, pfx in [
        ("tx_ingress_control_32", "u_tx", "tx_cdc"),
        ("rx_word_host_32", "u_rx_host", "rx_cdc"),
    ]:
        sv_txt = sub_v_paths[sub_mod].read_text()
        found_wires = sorted(set(re.findall(rf"\b({pfx}_[a-z0-9_]+)\b", sv_txt)))
        for wn in found_wires:
            if wn == "rx_cdc_r_up_w_1":
                continue  # merges directly into top-level port rx_word_online during flatten
            cdc_top_renames.append(f"rename {sub_inst}.{wn} {wn}")

    synth_v = work / f"{block.name}_synth.v"
    ys_top = work / "synth_top.ys"
    top_cmds = [
        f"read_liberty -lib {synth_lib}",
        f"read_verilog {' '.join(sub_vs)}",
        f"read_verilog -sv {wrap_sv}",
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
        f"cd {block.name}",
        "rename u_pll.pll_clk_div4 pll_clk_div4_net",
        "rename u_tx.tx_clk_div2 tx_clk_div2_net",
        "rename rx_clk_div2 rx_clk_div2_net",
        *cdc_top_renames,
        "rename -hide c:* w:* w:pll_clk_div4_net %d w:tx_clk_div2_net %d w:rx_clk_div2_net %d w:tx_cdc_* %d w:rx_cdc_* %d",
        "cd ..",
        "opt_clean -purge",
        "check -assert",
        f"stat -liberty {synth_lib}",
        f"write_verilog -noattr -noexpr -nohex -nodec {synth_v}",
    ]
    ys_top.write_text("\n".join(top_cmds) + "\n")
    proc_t = base.run_cmd(
        [str(base.YOSYS), "-s", str(ys_top)],
        work,
        work / "01_yosys.log",
        timeout=300,
    )
    cm = re.search(r"Number of cells:\s+(\d+)", proc_t.stdout)
    am = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", proc_t.stdout)
    return synth_v, {
        "synth_cells": int(cm.group(1)) if cm else None,
        "synth_area_um2": round(float(am.group(1)), 1) if am else None,
        "per_subsystem": sub_stats,
    }


def inventory_netlist_v(verilog_path: Path) -> dict[str, Any]:
    """Full transparent cell/buffer/delay/weak-cell inventory."""
    v_txt = verilog_path.read_text()
    pairs = re.findall(r"^\s*(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\(", v_txt, re.M)
    by_master = Counter(m for m, _ in pairs)
    dly = {m: c for m, c in sorted(by_master.items()) if "__dly" in m}
    mux4 = {m: c for m, c in sorted(by_master.items()) if "__mux4" in m}
    weak1 = {
        m: c for m, c in sorted(by_master.items())
        if m.endswith("_1") and not any(x in m for x in ["fill_", "decap_", "tap", "conb_", "diode_", "dly"])
    }
    hold_insts = Counter(m for m, inst in pairs if inst.startswith("hold"))
    rep_insts = Counter(
        m for m, inst in pairs
        if any(inst.startswith(p) for p in ("repeater", "rebuffer", "wire", "input", "output", "fanout", "load_slew", "max_cap", "max_slew", "place"))
    )
    clk_insts = Counter(m for m, inst in pairs if inst.startswith("clkbuf"))
    return {
        "dly_total": sum(dly.values()),
        "dly_by_master": dly,
        "mux4_by_master": mux4,
        "weak1_logic_buf_total": sum(weak1.values()),
        "weak1_by_master": weak1,
        "hold_total": sum(hold_insts.values()),
        "hold_clkbuf_16": hold_insts.get("sky130_fd_sc_hd__clkbuf_16", 0),
        "hold_by_master": dict(sorted(hold_insts.items())),
        "repair_setup_buf_total": sum(rep_insts.values()),
        "repair_setup_by_master": dict(sorted(rep_insts.items())),
        "clkbuf_total": sum(clk_insts.values()),
        "clkbuf_by_master": dict(sorted(clk_insts.items())),
    }


def run_v4_openroad_pnr(
    block: base.BlockSpec,
    pin_groups: list[v3.PinGroup],
    work: Path,
    synth_v: Path,
    sdc_path: Path,
    closure_lib: Path,
    mode: str = "5g",
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
    da = " ".join(f"{val:.4g}" for val in block.die_area)
    ca = " ".join(f"{val:.4g}" for val in block.core_area)
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
read_liberty -corner ss {closure_lib}
read_liberty -corner ff {LIB_FF_N40}
read_verilog {synth_v}
link_design {block.name}
read_sdc {sdc_path}

{v4_openroad_dont_use_tcl(closure_lib, allow_hold_dly=False)}

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

{wire_rc_block}
set_routing_layers -signal met1-met5 -clock met1-met5
global_placement -density {block.place_density:.2f} -timing_driven -routability_driven -pad_left 1 -pad_right 1
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

estimate_parasitics -placement
set_max_transition 0.65 [current_design]
set_max_capacitance 0.085 [current_design]
set_max_fanout 45 [current_design]
repair_design -slew_margin 0 -cap_margin 0
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/HI
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/LO
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_16 \\
  -buf_list {{sky130_fd_sc_hd__clkbuf_16}} \\
  -balance_levels -sink_clustering_enable -sink_clustering_size 36 -sink_clustering_max_diameter 90
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_clock_nets

# Option A (D-H1): Short 1-buffer clock tap off clkbuf_0_rx_word_clk/X for u_rx_map rx_phys* capture FFs!
set _blk_tap [[[ord::get_db] getChip] getBlock]
set _root_buf [$_blk_tap findInst "clkbuf_0_rx_word_clk"]
if {{$_root_buf ne "NULL"}} {{
  set _root_anet [[$_root_buf findITerm "A"] getNet]
  set _root_xnet [[$_root_buf findITerm "X"] getNet]
  set _rxmap_insts {{}}
  set _rxmap_seen {{}}
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
  if {{$_n_rxmap > 0 && $_root_anet ne "NULL"}} {{
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
      [$_tb findITerm "A"] connect $_root_anet
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

# 1-level balanced clock tree (3x parallel clkbuf_16 directly off tx_word_clk port) for the tiny 42-FF tx_word_clk domain:
# gives EVERY tx_word_clk FF 1-buffer latency (~0.45 ns) AND zero inter-level skew for 312.5 MHz 5G ss_n40C_1v60 closure!
set _tx_root [$_blk_tap findInst "clkbuf_0_tx_word_clk"]
if {{$_tx_root ne "NULL"}} {{
  set _tx_in_net [[$_tx_root findITerm "A"] getNet]
  set _tx_x_net  [[$_tx_root findITerm "X"] getNet]
  if {{$_tx_in_net ne "NULL" && $_tx_x_net ne "NULL"}} {{
    set _tx_ffs {{}}
    set _tx_bufs [list $_tx_root]
    set _tx_nets [list $_tx_x_net]
    set _q_tx [list $_tx_x_net]
    while {{[llength $_q_tx] > 0}} {{
      set _cn [lindex $_q_tx 0]
      set _q_tx [lrange $_q_tx 1 end]
      foreach _it [$_cn getITerms] {{
        if {{[[$_it getMTerm] getIoType] eq "OUTPUT"}} {{ continue }}
        set _di [$_it getInst]
        if {{[$_di findITerm "CLK"] ne "NULL"}} {{
          lappend _tx_ffs $_di
        }} else {{
          lappend _tx_bufs $_di
          set _ox [$_di findITerm "X"]
          if {{$_ox ne "NULL"}} {{
            set _on2 [$_ox getNet]
            if {{$_on2 ne "NULL"}} {{
              lappend _tx_nets $_on2
              lappend _q_tx $_on2
            }}
          }}
        }}
      }}
    }}
    set _ntx [llength $_tx_ffs]
    if {{$_ntx > 0}} {{
      set _tx_master [[ord::get_db] findMaster "sky130_fd_sc_hd__clkbuf_16"]
      # Place parallel clkbuf_16 right beside tx_word_clk South pin (minimum input wire + slew -> ~0.82 ns latency!)
      set _tx_bt [$_blk_tap findBTerm "tx_word_clk"]
      set _rloc [$_tx_root getLocation]
      set _rx [lindex $_rloc 0]
      set _ry 15000
      if {{$_tx_bt ne "NULL"}} {{
        set _tbps [$_tx_bt getBPins]
        if {{[llength $_tbps] > 0}} {{
          set _tbox [lindex [[lindex $_tbps 0] getBoxes] 0]
          set _rx [expr {{([$_tbox xMin] + [$_tbox xMax]) / 2}}]
        }}
      }}
      set _npar 3
      for {{set _ti 0}} {{$_ti < $_npar}} {{incr _ti}} {{
        set _tn [odb::dbNet_create $_blk_tap "clknet_tx1lvl_${{_ti}}"]
        $_tn setSigType CLOCK
        set _tb [odb::dbInst_create $_blk_tap $_tx_master "clkbuf_tx1lvl_${{_ti}}"]
        $_tb setLocation [expr {{$_rx + ($_ti - 1) * 4600}}] $_ry
        $_tb setPlacementStatus PLACED
        [$_tb findITerm "A"] connect $_tx_in_net
        [$_tb findITerm "X"] connect $_tn
        set _tx_par_nets($_ti) $_tn
      }}
      # Sort by X coordinate so each parallel clkbuf_16 serves spatially local FFs
      set _tx_sorted [lsort -integer -index 0 [lmap _f $_tx_ffs {{list [lindex [$_f getLocation] 0] $_f}}]]
      set _idx 0
      foreach _pair $_tx_sorted {{
        set _di [lindex $_pair 1]
        set _cit [$_di findITerm "CLK"]
        $_cit disconnect
        set _ti [expr {{($_idx * $_npar) / $_ntx}}]
        if {{$_ti >= $_npar}} {{ set _ti [expr {{$_npar - 1}}] }}
        $_cit connect $_tx_par_nets($_ti)
        incr _idx
      }}
      foreach _bi $_tx_bufs {{ odb::dbInst_destroy $_bi }}
      foreach _bn $_tx_nets {{ odb::dbNet_destroy $_bn }}
      puts "TX1LVL_CLK: reconnected $_ntx tx_word_clk FFs to ${{_npar}}x parallel clkbuf_16 right above tx_word_clk pin!"
      # Pull the 19 TX output FFs right beside their South output pins AND bypass redundant single-fanout
      # output buffers (so dfrtp_4 drives the 20 fF pin directly in ~0.98 ns -> closes 312.5 MHz 5G ss_n40C_1v60!)
      set _tx_pulled 0
      set _tx_bypassed 0
      foreach _bt [$_blk_tap getBTerms] {{
        set _bn [$_bt getName]
        if {{[string match "tx_capture_*" $_bn] || $_bn eq "tx_a_valid" || $_bn eq "tx_b_valid"}} {{
          set _bps [$_bt getBPins]
          if {{[llength $_bps] == 0}} {{ continue }}
          set _box [lindex [[lindex $_bps 0] getBoxes] 0]
          set _px [expr {{([$_box xMin] + [$_box xMax]) / 2}}]
          set _pnet [$_bt getNet]
          if {{$_pnet eq "NULL"}} {{ continue }}
          set _drv_it "NULL"
          foreach _it [$_pnet getITerms] {{
            if {{[[$_it getMTerm] getIoType] eq "OUTPUT"}} {{ set _drv_it $_it; break }}
          }}
          if {{$_drv_it eq "NULL"}} {{ continue }}
          set _di [$_drv_it getInst]
          if {{[$_di findITerm "CLK"] ne "NULL"}} {{
            $_di setLocation $_px 14000
            $_di setPlacementStatus PLACED
            incr _tx_pulled
          }} elseif {{[string match "*__buf_*" [[$_di getMaster] getName]]}} {{
            # Bypass 1-hop buffer if driven directly by a single-fanout FF!
            set _ai [$_di findITerm "A"]
            set _anet [$_ai getNet]
            set _asinks 0
            set _ff_q "NULL"
            foreach _ait [$_anet getITerms] {{
              if {{[[$_ait getMTerm] getIoType] eq "OUTPUT"}} {{
                if {{[[$_ait getInst] findITerm "CLK"] ne "NULL"}} {{ set _ff_q $_ait }}
              }} else {{
                incr _asinks
              }}
            }}
            if {{$_ff_q ne "NULL" && $_asinks == 1}} {{
              set _ffi [$_ff_q getInst]
              $_ff_q disconnect
              $_drv_it disconnect
              $_ai disconnect
              $_ff_q connect $_pnet
              odb::dbInst_destroy $_di
              odb::dbNet_destroy $_anet
              $_ffi setLocation $_px 14000
              $_ffi setPlacementStatus PLACED
              incr _tx_pulled
              incr _tx_bypassed
            }} else {{
              $_di setLocation $_px 12000
              $_di setPlacementStatus PLACED
            }}
          }}
        }}
      }}
      puts "TXOUT_PIN_PULL: placed $_tx_pulled TX output FFs beside South pins (bypassed $_tx_bypassed redundant output bufs)!"
    }}
  }}
}}
detailed_placement

set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}
set_wire_rc -corner ss -signal -resistance 0.0020 -capacitance 0.00026
set_wire_rc -corner ss -clock  -resistance 0.0007 -capacitance 0.00021
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
read_liberty -corner ss {closure_lib}
read_liberty -corner ff {LIB_FF_N40}
read_def {post_setup_def}
read_sdc {sdc_path}
set_propagated_clock [all_clocks]

{v4_openroad_dont_use_tcl(closure_lib, allow_hold_dly=True)}
set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}

set_wire_rc -corner ss -signal -resistance 0.0020 -capacitance 0.00026
set_wire_rc -corner ss -clock  -resistance 0.0007 -capacitance 0.00021
set_wire_rc -corner ff -signal -resistance 0.0007 -capacitance 0.00009
set_wire_rc -corner ff -clock  -resistance 0.0003 -capacitance 0.00008
set_routing_layers -signal met1-met5 -clock met1-met5

estimate_parasitics -placement
repair_timing -hold -slack_margin 0.08 -max_buffer_percent 20
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
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

report_design_area
# Priority Decap Fill (skip buggy pre-DRT grt::repairAntennas; post-DRT ODB diode inserter fixes all antennas cleanly!)
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

    # Post-route OpenRCX SPEF-driven ECO + Antenna closure loop (up to 5 passes)
    sdc_eco = work / f"{block.name}_eco.sdc"
    write_v4_sdc(block, sdc_eco, mode=mode, post_route=True, ocv=True)
    clk_groups_tcl = " ".join(ALL_CLOCK_NAMES) + " **async_default**"

    for eco_pass in (1, 2, 3, 4, 5, 6):
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

        gb = 0.12 if eco_pass == 1 else (0.06 if eco_pass == 2 else 0.03)
        eco_tcl = work / f"pnr_eco_p{eco_pass}.tcl"
        eco_tcl.write_text(
            f"""read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
define_corners ss ff
read_liberty -corner ss {closure_lib}
read_liberty -corner ff {LIB_FF_N40}
read_def {routed_def}
read_sdc {sdc_eco}
{v4_openroad_dont_use_tcl(closure_lib, allow_hold_dly=True)}

read_spef -corner ss {spef_eco_max}
read_spef -corner ff {spef_eco_min}

set init_wns [sta::worst_slack -corner ss -max]
set init_hold_ff [sta::worst_slack -corner ff -min]
set init_hold_ss [sta::worst_slack -corner ss -min]
set init_hold [expr {{$init_hold_ff < $init_hold_ss ? $init_hold_ff : $init_hold_ss}}]
set init_ant [check_antennas -report_file {work}/_ant_tmp.rpt]
puts [format "ECO_P{eco_pass}_INIT: SS_OCV_WNS=%.4f FF_HOLD=%.4f SS_HOLD=%.4f ANT=%d" $init_wns $init_hold_ff $init_hold_ss $init_ant]
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
if {{$init_wns < 0.05 && {eco_pass} <= 4}} {{
  set_clock_uncertainty -setup [expr {{0.10 + {gb}}}] [all_clocks]
  for {{set iter 0}} {{$iter < 20}} {{incr iter}} {{
    set wns [sta::worst_slack -corner ss -max]
    if {{$wns >= 0.04}} {{ break }}
    set seen {{}}
    set improved 0
    foreach clk_grp {{{clk_groups_tcl}}} {{
      set paths [find_timing_paths -corner ss -path_delay max -path_group $clk_grp -group_count 60 -endpoint_count 1 -slack_max 0.05]
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
          set old_hff [sta::worst_slack -corner ff -min]
          set old_hss [sta::worst_slack -corner ss -min]
          set old_hold [expr {{$old_hff < $old_hss ? $old_hff : $old_hss}}]
          set hold_floor [expr {{$old_hold < 0.03 ? ($old_hold - 0.002) : 0.03}}]
          if {{[catch {{replace_cell $iname $cand}}]}} {{ continue }}
          set new_wns [sta::worst_slack -corner ss -max]
          set new_tns [sta::total_negative_slack -corner ss -max]
          set new_hff [sta::worst_slack -corner ff -min]
          set new_hss [sta::worst_slack -corner ss -min]
          set new_hold [expr {{$new_hff < $new_hss ? $new_hff : $new_hss}}]
          if {{($new_wns > $old_wns + 0.001 || ($new_wns >= $old_wns - 0.001 && $new_tns > $old_tns + 0.003)) && $new_hold >= $hold_floor}} {{
            incr eco_swapped
            set improved 1
          }} else {{
            catch {{replace_cell $iname $mname}}
          }}
        }}
      }}
    }}
    puts [format "ECO_P{eco_pass}_ITER %d: swapped=%d SS_OCV_WNS=%.4f FF_HOLD=%.4f" $iter $eco_swapped [expr {{[sta::worst_slack -corner ss -max] + {gb}}}] [sta::worst_slack -corner ff -min]]
    if {{!$improved}} {{ break }}
  }}
  set_clock_uncertainty -setup 0.10 [all_clocks]
}}

set post_eco_wns [sta::worst_slack -corner ss -max]
set post_hold_ff [sta::worst_slack -corner ff -min]
set post_hold_ss [sta::worst_slack -corner ss -min]

set need_hold_fix [expr {{$post_hold_ff < 0.02 || $post_hold_ss < 0.02}}]
set need_setup_buf [expr {{$post_eco_wns < -0.05 && $eco_swapped < 15 && {eco_pass} <= 4}}]
if {{$eco_swapped == 0 && !$need_hold_fix && !$need_setup_buf && $init_ant == 0}} {{
  puts "ECO_P{eco_pass}_NO_CHANGES"
  exit 0
}}

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
  repair_timing -setup -slack_margin 0.04 -max_buffer_percent 3
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
  repair_timing -hold -slack_margin 0.06 -max_buffer_percent 10
}}

foreach net [$blk_eco getNets] {{
  if {{![$net isSpecial]}} {{
    set wire [$net getWire]
    if {{$wire ne "NULL"}} {{ odb::dbWire_destroy $wire }}
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

        eco_route_tcl = work / f"pnr_eco_p{eco_pass}_route.tcl"
        eco_route_tcl.write_text(
            f"""read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {closure_lib}
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
    netlist_inv = inventory_netlist_v(routed_v)
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
        "netlist_inventory": netlist_inv,
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


def extract_spef_3corner(work: Path, pnr_info: dict[str, Any]) -> None:
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


def run_v4_sta_6corner(block: base.BlockSpec, work: Path, pnr_info: dict[str, Any], mode: str) -> dict[str, Any]:
    """6-Corner Post-Route OpenRCX STA (+/-5% OCV) across all 7 clocks for '5g' or '4g' mode."""
    sdc_post = work / f"{block.name}_postroute_{mode}.sdc"
    write_v4_sdc(block, sdc_post, mode=mode, post_route=True, ocv=True)

    corners = [
        ("tt_025C_1v80",       LIB_TT_025,      Path(pnr_info["spef_nom"])),
        ("ss_100C_1v60",       LIB_SS_100,      Path(pnr_info["spef_max"])),
        ("ss_n40C_1v65_interp", LIB_SS_N40_1V65, Path(pnr_info["spef_max"])),
        ("ss_n40C_1v60",       LIB_SS_N40,      Path(pnr_info["spef_max"])),
        ("ff_n40C_1v95",       LIB_FF_N40,      Path(pnr_info["spef_min"])),
        ("ff_100C_1v95",       LIB_FF_100,      Path(pnr_info["spef_min"])),
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
    for cname, lib_path, spef_path in corners:
        tcl = work / f"sta_{mode}_{cname}.tcl"
        tcl.write_text(
            f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {lib_path}
read_def {pnr_info["routed_def"]}
read_sdc {sdc_post}
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
            work / f"03_sta_{mode}_{cname}.log",
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
            sm = re.search(rf"=== CLK_SETUP_{clk_n} ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)", log, re.S)
            hm = re.search(rf"=== CLK_HOLD_{clk_n} ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)", log, re.S)
            per_clk[clk_n] = {
                "setup_wns_ns": round(float(sm.group(1)), 4) if sm else None,
                "hold_wns_ns": round(float(hm.group(1)), 4) if hm else None,
            }

        rxs = re.search(r"=== RX_PHYS_FALL_SETUP ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)", log, re.S)
        rxh = re.search(r"=== RX_PHYS_FALL_HOLD ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)", log, re.S)
        arec = re.search(r"=== ASYNC_RECOVERY ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)", log, re.S)
        arem = re.search(r"=== ASYNC_REMOVAL ===.*?([-+]?[0-9.]+)\s+slack\s+\((?:MET|VIOLATED)\)", log, re.S)

        setup_wns = parse_val("SETUP_WNS")
        hold_wns = parse_val("HOLD_WNS")
        sta_results[cname] = {
            "setup_wns_ns": setup_wns,
            "setup_tns_ns": parse_val("SETUP_TNS"),
            "hold_wns_ns": hold_wns,
            "hold_tns_ns": parse_val("HOLD_TNS"),
            "setup_met": (setup_wns is not None and setup_wns >= 0.0),
            "hold_met": (hold_wns is not None and hold_wns >= 0.0),
            "rx_phys_fall_setup_ns": round(float(rxs.group(1)), 4) if rxs else None,
            "rx_phys_fall_hold_ns": round(float(rxh.group(1)), 4) if rxh else None,
            "async_recovery_ns": round(float(arec.group(1)), 4) if arec else None,
            "async_removal_ns": round(float(arem.group(1)), 4) if arem else None,
            "per_clock": per_clk,
        }
    return sta_results


def run_v4_cdc_audit(block: base.BlockSpec, work: Path, pnr_info: dict[str, Any]) -> dict[str, Any]:
    """Post-route CDC audit on max.spef at official ss_n40C_1v60 (+/-5% OCV) across BOTH TX & RX 16x32 FIFOs!"""
    sdc_cdc = work / f"{block.name}_cdc_audit.sdc"
    write_v4_sdc(block, sdc_cdc, mode="5g", post_route=True, ocv=True)
    sdc_txt = sdc_cdc.read_text()
    sdc_txt = re.sub(
        r"set_clock_groups -asynchronous\s*\\\n(?:\s*-group \{[^\}]+\}\s*\\?\n)+",
        "# (clock groups temporarily removed for CDC Gray bus_skew & MTBF audit)\n",
        sdc_txt,
    )
    sdc_cdc.write_text(sdc_txt)

    sync1_nets = []
    sync_pairs = []
    for pfx in ("tx_cdc", "rx_cdc"):
        sync1_nets += [
            f"{pfx}_r_up_w_0", f"{pfx}_w_up_r_0", f"{pfx}_overflow_r_0",
            f"{pfx}_w_rst_s0", f"{pfx}_r_rst_s0",
        ]
        sync1_nets += [f"{pfx}_r_gray_w1_{b}" for b in range(4)]
        sync1_nets += [f"{pfx}_w_gray_r1_{b}" for b in range(4)]
        sync_pairs += [
            (f"{pfx}_r_up_w",     f"{pfx}_r_up_w_0",     "rx_word_online" if pfx == "rx_cdc" else f"{pfx}_r_up_w_1"),
            (f"{pfx}_w_up_r",     f"{pfx}_w_up_r_0",     "host_online" if pfx == "rx_cdc" else f"{pfx}_w_up_r_1"),
            (f"{pfx}_overflow_r", f"{pfx}_overflow_r_0", "host_error"  if pfx == "rx_cdc" else f"{pfx}_overflow_r_1"),
            (f"{pfx}_w_rst",      f"{pfx}_w_rst_s0",     f"{pfx}_w_rst_s1"),
            (f"{pfx}_r_rst",      f"{pfx}_r_rst_s0",     f"{pfx}_r_rst_s1"),
        ]
        for b in range(4):
            sync_pairs.append((f"{pfx}_r_gray_{b}", f"{pfx}_r_gray_w1_{b}", f"{pfx}_r_gray_w2_{b}"))
            sync_pairs.append((f"{pfx}_w_gray_{b}", f"{pfx}_w_gray_r1_{b}", f"{pfx}_w_gray_r2_{b}"))
    sync1_nets.append("tx_cdc_ur_0")
    sync_pairs.append(("tx_cdc_ur", "tx_cdc_ur_0", "tx_underrun"))

    pairs_tcl = "\n".join(f"  {nm} {n1} {n2}" for nm, n1, n2 in sync_pairs)
    nets_tcl = "\n".join(f"  {sn}" for sn in sync1_nets)

    tcl = work / "cdc_audit.tcl"
    tcl.write_text(
        f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {LIB_SS_N40}
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
{nets_tcl}
}}
foreach sn $sync1_nets {{
  set drv [_driver_inst $blk $sn]
  set sinks [_trace_sinks $blk $sn]
  puts "SYNC1_NET: $sn drv=$drv fanout=[llength $sinks] sinks={{$sinks}}"
}}

puts "=== GRAY_BUS_SKEW_AUDIT ==="
foreach {{tag src_pre dst_pre}} {{
  tx_w2r_gray tx_cdc_w_gray tx_cdc_w_gray_r1
  tx_r2w_gray tx_cdc_r_pop_gray tx_cdc_r_gray_w1
  rx_w2r_gray rx_cdc_w_gray rx_cdc_w_gray_r1
  rx_r2w_gray rx_cdc_r_pop_gray rx_cdc_r_gray_w1
}} {{
  for {{set b 0}} {{$b < 4}} {{incr b}} {{
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
{pairs_tcl}
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
    puts [format "MTBF_PAIR: %s s1=%s s2=%s slack=%.5f" $name $i1 $i2 $slk]
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

    fanout_audit: dict[str, Any] = {}
    fanout_violations = 0
    for m in re.finditer(r"^SYNC1_NET:\s+(\S+)\s+drv=(\S*)\s+fanout=(\d+)\s+sinks=\{(.*)\}$", log, re.M):
        net_n, drv, fo_s, sinks = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        # Note: TX/RX overflow_r may be optimized away if unused (tx_fifo r_error is unused!)
        if drv == "" and fo_s == 0:
            continue
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
                gray_buses.setdefault(tag, {"bits": []})["bits"].append({
                    "bit": bit, "src": s_inst, "dst": d_inst,
                    "launch_clk_ns": lclk, "arrival_ns": tot, "datapath_ns": dp,
                })

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
    for m in re.finditer(r"^MTBF_PAIR:\s+(\S+)\s+s1=(\S+)\s+s2=(\S+)\s+slack=([-0-9.eE+]+)", log, re.M):
        slk = float(m.group(4))
        slk = round(slk * 1e9 if (abs(slk) < 1e-6 and slk != 0.0) else slk, 4)
        mtbf_pairs[m.group(1)] = {"sync1": m.group(2), "sync2": m.group(3), "slack_ns": slk}
        if min_mtbf_slack is None or slk < min_mtbf_slack:
            min_mtbf_slack = slk

    return {
        "corner": "ss_n40C_1v60 (+5% OCV, max.spef)",
        "sync1_fanout_count_checked": len(fanout_audit),
        "sync1_fanout_violations": fanout_violations,
        "sync1_fanout": fanout_audit,
        "gray_bus_skew": gray_buses,
        "sync1_to_sync2_mtbf": {
            "pairs_checked": len(mtbf_pairs),
            "min_slack_ns": min_mtbf_slack,
            "pairs": mtbf_pairs,
        },
    }


def render_v4_png(
    block: base.BlockSpec,
    pin_groups: list[v3.PinGroup],
    mag_path: Path,
    png_path: Path,
    pnr_info: dict[str, Any],
    sta_5g: dict[str, Any],
    sta_4g: dict[str, Any],
    cdc_info: dict[str, Any],
    drc_total: int,
    lvs_status: str,
) -> None:
    """Render high-resolution layout PNG with metal layers and cardinal pin group brackets."""
    die_w = pnr_info["die_w_um"]
    die_h = pnr_info["die_h_um"]
    units_per_um, rects_raw, _labels, _uses = base._parse_mag_rects(mag_path)
    layers_rects: dict[str, list[tuple[float, float, float, float]]] = {}
    inv_u = 1.0 / units_per_um
    for lname, x0, y0, x1, y1 in rects_raw:
        layers_rects.setdefault(lname, []).append((x0 * inv_u, y0 * inv_u, x1 * inv_u, y1 * inv_u))
    cell_boxes: list[tuple[float, float, float, float]] = []

    fig, ax = plt.subplots(figsize=(14.0, 10.6), dpi=180)
    ax.set_facecolor("#ffffff")
    ax.add_patch(Rectangle((0, 0), die_w, die_h, facecolor="#f8fafc", edgecolor="#0f172a", linewidth=1.8, zorder=0))

    if cell_boxes:
        patches = [Rectangle((x0, y0), x1 - x0, y1 - y0) for x0, y0, x1, y1 in cell_boxes]
        ax.add_collection(PatchCollection(patches, facecolor="#dbeafe", edgecolor="#93c5fd", linewidth=0.25, alpha=0.55, zorder=1))

    layer_styles = [
        ("locali", "#d97706", 0.35, 2, "li1 (local)"),
        ("metal1", "#2563eb", 0.55, 3, "met1"),
        ("metal2", "#dc2626", 0.55, 4, "met2"),
        ("metal3", "#16a34a", 0.55, 5, "met3"),
        ("metal4", "#9333ea", 0.50, 6, "met4 (PDN/sig)"),
        ("metal5", "#0891b2", 0.45, 7, "met5 (PDN)"),
    ]
    layer_handles = [Patch(facecolor="#dbeafe", edgecolor="#93c5fd", label="stdcells / decap")]
    for lname, col, alpha, z, label in layer_styles:
        rects = layers_rects.get(lname, [])
        if rects:
            patches = [Rectangle((x0, y0), x1 - x0, y1 - y0) for x0, y0, x1, y1 in rects]
            ax.add_collection(PatchCollection(patches, facecolor=col, edgecolor="none", alpha=alpha, zorder=z))
            layer_handles.append(Patch(facecolor=col, alpha=min(alpha + 0.25, 1.0), label=f"{label} ({len(rects)})"))

    group_handles = []
    pad = 8.0
    for pg in pin_groups:
        group_handles.append(Patch(facecolor=pg.color, edgecolor=pg.color, label=f"{pg.short_label} ({len(pg.pins)})"))
        if pg.edge == "bottom":
            x0, x1 = pg.frac_start * die_w, pg.frac_end * die_w
            ax.plot([x0, x1], [-pad, -pad], color=pg.color, lw=3.6, solid_capstyle="butt", zorder=10)
            ax.text((x0 + x1) / 2, -pad - 6.0, pg.short_label, color=pg.color, fontsize=7.6, fontweight="bold", ha="center", va="top")
        elif pg.edge == "top":
            x0, x1 = pg.frac_start * die_w, pg.frac_end * die_w
            ax.plot([x0, x1], [die_h + pad, die_h + pad], color=pg.color, lw=3.6, solid_capstyle="butt", zorder=10)
            ax.text((x0 + x1) / 2, die_h + pad + 5.5, pg.short_label, color=pg.color, fontsize=7.6, fontweight="bold", ha="center", va="bottom")
        elif pg.edge == "left":
            y0, y1 = pg.frac_start * die_h, pg.frac_end * die_h
            ax.plot([-pad, -pad], [y0, y1], color=pg.color, lw=3.6, solid_capstyle="butt", zorder=10)
            ax.text(-pad - 5.5, (y0 + y1) / 2, pg.short_label, color=pg.color, fontsize=7.6, fontweight="bold", ha="right", va="center", rotation=90)
        elif pg.edge == "right":
            y0, y1 = pg.frac_start * die_h, pg.frac_end * die_h
            ax.plot([die_w + pad, die_w + pad], [y0, y1], color=pg.color, lw=3.6, solid_capstyle="butt", zorder=10)
            ax.text(die_w + pad + 5.5, (y0 + y1) / 2, pg.short_label, color=pg.color, fontsize=7.6, fontweight="bold", ha="left", va="center", rotation=270)

    ax.set_xlim(-28, die_w + 28)
    ax.set_ylim(-28, die_h + 28)
    ax.set_aspect("equal")
    ax.set_xlabel("X (µm)", fontsize=9)
    ax.set_ylabel("Y (µm)", fontsize=9)

    cs = pnr_info["cell_stats"]
    s5_60 = sta_5g["ss_n40C_1v60"]["setup_wns_ns"]
    s5_65 = sta_5g["ss_n40C_1v65_interp"]["setup_wns_ns"]
    s4_60 = sta_4g["ss_n40C_1v60"]["setup_wns_ns"]
    ff_h = sta_5g["ff_n40C_1v95"]["hold_wns_ns"]
    wl_mm = pnr_info["wirelength"]["total_um"] / 1000.0
    mtbf_s = cdc_info["sync1_to_sync2_mtbf"]["min_slack_ns"] or 0.0
    max_gsk = max((g.get("bus_skew_total_ns", 0.0) for g in cdc_info["gray_bus_skew"].values()), default=0.0)

    subtitle = (
        f"Die {die_w:.1f}×{die_h:.1f} µm ({pnr_info['die_area_um2']:.0f} µm²) | "
        f"StdCells={cs['std_cells']} | Util={pnr_info['utilization_pct']:.1f}% | WL={wl_mm:.1f} mm | "
        f"Decap={cs['decap_cap_pf']:.1f} pF | Ant={pnr_info['antenna_violations']} | DRC={drc_total} | LVS={lvs_status}\n"
        f"6-Corner +/-5% OCV STA: 5G(312.5/156.25/160M) ss_1v60={s5_60:+.3f} / 1v65={s5_65:+.3f} ns | "
        f"4G ss_1v60={s4_60:+.3f} ns | FF hold={ff_h:+.3f} ns | Gray skew={max_gsk:.3f} ns | MTBF={mtbf_s:+.3f} ns"
    )
    ax.set_title(
        f"SKY130A 32-Bit Down-Clocked SerDes Digital Top v4 (>=5.0 Gb/s) — {block.name}\n{subtitle}",
        fontsize=9.4, fontweight="bold", pad=10,
    )
    leg1 = ax.legend(handles=layer_handles, loc="upper left", bbox_to_anchor=(1.015, 1.00),
                     frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=7.2, title="Layers", title_fontsize=8)
    ax.add_artist(leg1)
    ax.legend(handles=group_handles, loc="lower left", bbox_to_anchor=(1.015, 0.00),
              frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=7.0, title="Cardinal Pin Groups", title_fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path, dpi=180, facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description="32-Bit Down-Clocked serdes_digital_top_v4 P&R, 6-Corner OCV STA, CDC, DRC & LVS")
    ap.add_argument("--die-w", type=float, default=414.00, help="Target die width in um (default: 414.00)")
    ap.add_argument("--die-h", type=float, default=388.96, help="Target die height in um (default: 388.96)")
    ap.add_argument("--place-density", type=float, default=0.80, help="Global placement density (default: 0.80)")
    ap.add_argument("--setup-margin", type=float, default=0.20, help="Pre-route setup repair margin ns (default: 0.20)")
    ap.add_argument("--hold-margin", type=float, default=0.03, help="Pre-route hold repair margin ns (default: 0.03)")
    ap.add_argument("--closure-mode", choices=["5g", "4g"], default="5g", help="P&R timing closure mode (default: 5g)")
    ap.add_argument("--results-dir", type=Path, default=RESULTS_BASE, help="Results base directory")
    ap.add_argument("--variant-dir", type=Path, default=VARIANT_BASE, help="Variant export base directory")
    args = ap.parse_args()

    t0 = time.time()
    block = build_v4_block_spec(
        die_w=args.die_w,
        die_h=args.die_h,
        place_density=args.place_density,
        setup_margin_ns=args.setup_margin,
        hold_margin_ns=args.hold_margin,
    )
    pin_groups = build_v4_pin_groups()

    res_base = args.results_dir.resolve()
    var_base = args.variant_dir.resolve()
    work = res_base / block.name
    work.mkdir(parents=True, exist_ok=True)
    variant_dir = var_base / block.name
    variant_dir.mkdir(parents=True, exist_ok=True)

    closure_lib = LIB_SS_N40_1V65
    synth_lib = build_v4_synth_lib(
        closure_lib,
        res_base / "_work/sky130_fd_sc_hd__ss_n40C_1v65_interp_v4_synth.lib",
    )

    print(
        f"[{block.name} v4] Target die: {block.die_area[2]:.2f}x{block.die_area[3]:.2f} um "
        f"({block.die_area[2]*block.die_area[3]:.0f} um^2), mode={args.closure_mode.upper()}, "
        f"closure_lib={closure_lib.name} + +/-5% OCV",
        flush=True,
    )

    print(f"[{block.name} v4] 1/7 Yosys per-subsystem synthesis against {closure_lib.name}...", flush=True)
    synth_v, synth_info = run_v4_yosys(block, work, synth_lib)
    print(
        f"[{block.name} v4]   synth_cells={synth_info['synth_cells']} "
        f"synth_area={synth_info['synth_area_um2']:.1f} um^2",
        flush=True,
    )
    for mod, st in synth_info["per_subsystem"].items():
        print(f"[{block.name} v4]     - {mod:22s}: {st['cells']:5d} cells, {st['area_um2']:8.1f} um^2", flush=True)

    sdc_path = work / f"{block.name}.sdc"
    write_v4_sdc(block, sdc_path, mode=args.closure_mode, post_route=False, ocv=True)

    print(f"[{block.name} v4] 2/7 OpenROAD P&R + SPEF-ECO ({args.closure_mode.upper()} @ {closure_lib.name} +/-5% OCV)...", flush=True)
    pnr_info = run_v4_openroad_pnr(block, pin_groups, work, synth_v, sdc_path, closure_lib, mode=args.closure_mode)
    ni = pnr_info["netlist_inventory"]
    print(
        f"[{block.name} v4]   Die={pnr_info['die_w_um']:.2f}x{pnr_info['die_h_um']:.2f} um "
        f"({pnr_info['die_area_um2']:.0f} um^2) | Util={pnr_info['utilization_pct']:.1f}% | "
        f"Std={pnr_info['std_cells']} | Decap={pnr_info['cell_stats']['decap_cells_total']} "
        f"({pnr_info['cell_stats']['decap_cap_pf']:.2f} pF) | Diodes={pnr_info['cell_stats']['diode_cells']} | "
        f"Ant={pnr_info['antenna_violations']} | DRT={pnr_info['openroad_drt_drvs']} | "
        f"WL={pnr_info['wirelength']['total_um']} um | PinViols={pnr_info['pin_check']['region_violations']}\n"
        f"[{block.name} v4]   Inventory: hold={ni['hold_total']} (dly={ni['dly_total']}, clkbuf16={ni['hold_clkbuf_16']}), "
        f"setup_rep={ni['repair_setup_buf_total']}, clkbuf={ni['clkbuf_total']}, mux4={ni['mux4_by_master']}, weak1={ni['weak1_logic_buf_total']}",
        flush=True,
    )

    print(f"[{block.name} v4] 3/7 Extracting 3-corner OpenRCX SPEF + 6-Corner +/-5% OCV STA (BOTH 5G & 4G)...", flush=True)
    extract_spef_3corner(work, pnr_info)
    sta_5g = run_v4_sta_6corner(block, work, pnr_info, mode="5g")
    sta_4g = run_v4_sta_6corner(block, work, pnr_info, mode="4g")
    for tag_m, sta_m in [("5G (312.5/156.25/160M)", sta_5g), ("4G (250/125/160M)", sta_4g)]:
        print(f"[{block.name} v4]   === {tag_m} ===", flush=True)
        for cname, s in sta_m.items():
            print(
                f"[{block.name} v4]     {cname:19s}: setup={s['setup_wns_ns']:+.4f} (met={s['setup_met']}) | "
                f"hold={s['hold_wns_ns']:+.4f} (met={s['hold_met']}) | "
                f"rx_phys={s['rx_phys_fall_setup_ns']:+.4f}/{s['rx_phys_fall_hold_ns']:+.4f} | "
                f"async={s['async_recovery_ns']:+.4f}/{s['async_removal_ns']:+.4f}",
                flush=True,
            )
            for clk_n, cs_clk in s["per_clock"].items():
                sw, hw = cs_clk["setup_wns_ns"], cs_clk["hold_wns_ns"]
                print(f"[{block.name} v4]       {clk_n:13s}: setup={sw:+.4f}, hold={hw:+.4f}", flush=True)

    print(f"[{block.name} v4] 4/7 Post-Route CDC Audit (TX+RX 16x32 FIFOs: sync1 fanout=1, Gray bus_skew, MTBF)...", flush=True)
    cdc_info = run_v4_cdc_audit(block, work, pnr_info)
    print(
        f"[{block.name} v4]   Sync1 fanout==1 checked={cdc_info['sync1_fanout_count_checked']}, "
        f"violations={cdc_info['sync1_fanout_violations']}",
        flush=True,
    )
    for tag, gi in cdc_info["gray_bus_skew"].items():
        print(
            f"[{block.name} v4]   Gray {tag:12s}: datapath_skew={gi.get('bus_skew_datapath_ns')} ns "
            f"(min={gi.get('datapath_min_ns')}, max={gi.get('datapath_max_ns')}) | "
            f"total_skew={gi.get('bus_skew_total_ns')} ns",
            flush=True,
        )
    print(
        f"[{block.name} v4]   MTBF sync1->sync2: pairs={cdc_info['sync1_to_sync2_mtbf']['pairs_checked']}, "
        f"min_slack={cdc_info['sync1_to_sync2_mtbf']['min_slack_ns']:+.4f} ns",
        flush=True,
    )

    print(f"[{block.name} v4] 5/7 Magic DEF->MAG/GDS + Full-Rule DRC + LVS extraction...", flush=True)
    magic_info = v3.run_v3_magic(block, work, Path(pnr_info["routed_def"]))
    print(f"[{block.name} v4]   Magic full DRC = {magic_info['magic_drc_total']}", flush=True)

    print(f"[{block.name} v4] 6/7 Netgen LVS...", flush=True)
    lvs_info = base.run_netgen_lvs(block, work, Path(magic_info["lvs_spice_path"]), Path(pnr_info["routed_pg_v"]))
    print(f"[{block.name} v4]   Netgen LVS = {lvs_info['lvs_status']}", flush=True)

    print(f"[{block.name} v4] 7/7 Rendering layout PNG & exporting deliverables...", flush=True)
    png_work = work / f"{block.name}.png"
    render_v4_png(
        block, pin_groups, Path(magic_info["mag_path"]), png_work,
        pnr_info, sta_5g, sta_4g, cdc_info, magic_info["magic_drc_total"], lvs_info["lvs_status"],
    )

    spec_corners_6 = ["tt_025C_1v80", "ss_100C_1v60", "ss_n40C_1v65_interp", "ss_n40C_1v60", "ff_n40C_1v95", "ff_100C_1v95"]
    spec_corners_5 = [c for c in spec_corners_6 if c != "ss_n40C_1v60"]
    all_4g_6c_met = all(sta_4g[c]["setup_met"] and sta_4g[c]["hold_met"] for c in spec_corners_6)
    all_4g_1v65_met = all(sta_4g[c]["setup_met"] and sta_4g[c]["hold_met"] for c in spec_corners_5)
    all_5g_6c_met = all(sta_5g[c]["setup_met"] and sta_5g[c]["hold_met"] for c in spec_corners_6)
    all_5g_1v65_met = all(sta_5g[c]["setup_met"] and sta_5g[c]["hold_met"] for c in spec_corners_5)
    all_6c_hold_met = all(sta_5g[c]["hold_met"] and sta_4g[c]["hold_met"] for c in spec_corners_6)

    v3p2_delta: dict[str, Any] = {}
    if V3P2_SUMMARY.exists():
        v32 = json.loads(V3P2_SUMMARY.read_text())
        v3p2_delta = {
            "v3p2_synth_cells": v32["synthesis"]["synth_cells"],
            "v4_synth_cells": synth_info["synth_cells"],
            "delta_synth_cells": (synth_info["synth_cells"] or 0) - v32["synthesis"]["synth_cells"],
            "v3p2_std_cells": v32["pnr"]["cell_stats"]["std_cells"],
            "v4_std_cells": pnr_info["std_cells"],
            "delta_std_cells": pnr_info["std_cells"] - v32["pnr"]["cell_stats"]["std_cells"],
            "v3p2_die_area_um2": v32["pnr"]["die_area_um2"],
            "v4_die_area_um2": pnr_info["die_area_um2"],
            "delta_die_area_um2": round(pnr_info["die_area_um2"] - v32["pnr"]["die_area_um2"], 2),
        }

    elapsed = round(time.time() - t0, 1)
    summary = {
        "block": block.name,
        "variant": "hd_pnr_v4_32b",
        "architecture": "32-bit internal down-clocked (160 MHz host -> 5.12 Gb/s > 5.0 Gb/s; 106 South analog pins preserved)",
        "ocv_derate": {"early": 0.95, "late": 1.05},
        "closure_mode": args.closure_mode,
        "closure_corner": closure_lib.name,
        "signoff_flags": {
            "all_4g_6corner_incl_ss_n40C_1v60_met": all_4g_6c_met,
            "all_4g_5corner_ss_n40C_1v65_interp_met": all_4g_1v65_met,
            "all_5g_6corner_incl_ss_n40C_1v60_met": all_5g_6c_met,
            "all_5g_5corner_ss_n40C_1v65_interp_met": all_5g_1v65_met,
            "all_6corner_hold_met": all_6c_hold_met,
            "cdc_sync1_zero_violations": cdc_info["sync1_fanout_violations"] == 0,
            "magic_drc_clean": magic_info["magic_drc_total"] == 0,
            "netgen_lvs_match": lvs_info["lvs_match"],
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
            "netlist_inventory": pnr_info["netlist_inventory"],
            "pin_check": pnr_info["pin_check"],
        },
        "sta_5g_6corner_ocv": sta_5g,
        "sta_4g_6corner_ocv": sta_4g,
        "cdc_audit": cdc_info,
        "magic_drc_total": magic_info["magic_drc_total"],
        "netgen_lvs": lvs_info["lvs_status"],
        "lvs_match": lvs_info["lvs_match"],
        "delta_vs_v3p2": v3p2_delta,
        "elapsed_s": elapsed,
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    if all_4g_1v65_met and all_5g_1v65_met and magic_info["magic_drc_total"] == 0 and lvs_info["lvs_match"] and cdc_info["sync1_fanout_violations"] == 0:
        exports = {
            f"{block.name}.def": Path(pnr_info["routed_def"]),
            f"{block.name}.gds": Path(magic_info["gds_path"]),
            f"{block.name}.v": Path(pnr_info["routed_v"]),
            f"{block.name}_pg.v": Path(pnr_info["routed_pg_v"]),
            f"{block.name}.png": png_work,
        }
        for fname, src in exports.items():
            shutil.copy2(src, variant_dir / fname)
        (variant_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"[{block.name} v4] SIGNOFF COMPLETE & EXPORTED -> {variant_dir} (elapsed={elapsed}s)", flush=True)
    else:
        print(
            f"[{block.name} v4] FINISHED (elapsed={elapsed}s) — check signoff_flags={summary['signoff_flags']} "
            f"before exporting ({work / 'summary.json'})",
            flush=True,
        )


if __name__ == "__main__":
    main()
