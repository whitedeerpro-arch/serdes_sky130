#!/usr/bin/env python3
"""Tapeout-grade Lean Unified Digital Top Macro v3 P&R, 3-Corner STA, Antenna, DRC & LVS Flow.

Builds ``serdes_digital_top_v3`` combining all 4 SKY130A SerDes digital blocks in one
ultra-compact macro (~99,800 um^2, -46% vs 185,359 um^2 4-block v2):
  - ``tx_ingress_control``    : full-rate 250 MHz (4.0 ns) tx_word_clk
  - ``rx_word_map`` (shared) + ``rx_word_host_shared`` (align + async FIFO)
                              : full-rate 250 MHz (4.0 ns) rx_word_clk & host_clk
  - ``rx_cdr_loop`` (v3)      : 250 MHz 2-tick BBPD pre-accumulator -> internal synchronous /2
                                (125 MHz / 8.0 ns) filter + PI commutator with exact bitwidths
  - ``pll_control_top`` (v3)  : 5-bit VCO coarse ctrl on internal synchronous /4 (62.5 MHz / 16.0 ns)

All temporary files/logs/SPEF/EXT stay strictly under
``results/digital/pnr_v3_unified/serdes_digital_top_v3/``; clean signoff deliverables
(.def, .gds, .v, _pg.v, .png, summary.json) are exported to
``digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Patch, Rectangle

import run_pnr as base

REPO = base.REPO
RESULTS_BASE = REPO / "results/digital/pnr_v3_unified"
VARIANT_BASE = REPO / "digital/pnr/variants/hd_pnr_v3_unified"
VARIANT_V2_SUMMARY = REPO / "digital/pnr/variants/hd_pnr_v2/all_blocks_summary.json"
RESULTS_V2_BASE = REPO / "results/digital/pnr_v2"

BLOCK_NAME = "serdes_digital_top_v3"

UNIFIED_RTL_FILES = [
    "digital/pnr/rtl_v3/mon_sync.sv",
    "digital/pnr/rtl_v3/mon_persist.sv",
    "digital/pnr/rtl_v3/pll_startup_supervisor.sv",
    "digital/pnr/rtl_v3/pll_coarse_ctrl.sv",
    "digital/pnr/rtl_v3/pll_lock_detect.sv",
    "digital/pnr/rtl_v3/pll_control_top.sv",
    "digital/pnr/rtl_v3/tx_ingress_control.sv",
    "digital/pnr/rtl_v3/rx_word_map.sv",
    "digital/pnr/rtl_v3/rx_word_align16.sv",
    "digital/pnr/rtl_v3/rx_async_word_fifo.sv",
    "digital/pnr/rtl_v3/bbpd_window_vote.sv",
    "digital/pnr/rtl_v3/cdr_phase_frequency.sv",
    "digital/pnr/rtl_v3/pi_step_commutator.sv",
    "digital/pnr/rtl_v3/rx_cdr_loop.sv",
    "digital/pnr/rtl_v3/serdes_digital_top_v3.sv",
]

# Exact SKY130A sky130_fd_sc_hd decap MOSFET gate capacitance per cell (in fF)
_C_PER_UM_L_FF = 0.87 * (3.9 * 8.8541878e-3 / 4.230e-3) + 0.55 * (3.9 * 8.8541878e-3 / 4.148e-3)
DECAP_CAP_FF: dict[str, float] = {
    "sky130_fd_sc_hd__decap_3": round(_C_PER_UM_L_FF * 0.59, 3),   # 6.892 fF
    "sky130_fd_sc_hd__decap_4": round(_C_PER_UM_L_FF * 1.05, 3),   # 12.265 fF
    "sky130_fd_sc_hd__decap_6": round(_C_PER_UM_L_FF * 1.97, 3),   # 23.011 fF
    "sky130_fd_sc_hd__decap_8": round(_C_PER_UM_L_FF * 2.89, 3),   # 33.758 fF
    "sky130_fd_sc_hd__decap_12": round(_C_PER_UM_L_FF * 4.73, 3),  # 55.250 fF
}

ALL_CLOCK_NAMES = [
    "ref_clk",
    "pll_clk_div4",
    "tx_word_clk",
    "rx_word_clk",
    "cdr_clk_div2",
    "host_clk",
]


def _bus(name: str, width: int) -> list[str]:
    return [f"{name}[{i}]" for i in range(width)]


@dataclass
class PinGroup:
    key: str
    label: str
    short_label: str
    edge: str  # "bottom", "top", "left", "right"
    frac_start: float
    frac_end: float
    color: str
    pins: list[str]


def build_pin_groups() -> list[PinGroup]:
    """Cardinal directional pin groups matching the real analog + host floorplan."""
    return [
        # SOUTH EDGE — Facing Analog Core (West=PLL, Mid=TX, East=RX)
        PinGroup(
            key="south_pll",
            label="PLL Analog (ref_clk, VCO, CP, PFD)",
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
                ]
                + _bus("vco_code", 5)
                + _bus("switches", 8)
            ),
        ),
        PinGroup(
            key="south_tx",
            label="TX Analog / Serializer",
            short_label="TX Analog",
            edge="bottom",
            frac_start=0.220,
            frac_end=0.345,
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
        PinGroup(
            key="south_rx",
            label="RX Analog (rx_phys[31:0], PI ctrl)",
            short_label="RX Analog (rx_phys[31:0], PI ctrl)",
            edge="bottom",
            frac_start=0.370,
            frac_end=0.975,
            color="#dc2626",
            pins=(
                ["rx_word_clk"]
                + _bus("rx_phys", 32)
                + _bus("rx_phase_code", 6)
                + _bus("rx_select_a", 8)
                + _bus("rx_select_b", 8)
                + _bus("rx_fine_b", 8)
            ),
        ),
        # WEST EDGE — PLL Host Config & Calibration + Global rst_n
        PinGroup(
            key="west_pll_host",
            label="PLL Host Cfg + rst_n",
            short_label="PLL Host Cfg + rst_n",
            edge="left",
            frac_start=0.060,
            frac_end=0.940,
            color="#1d4ed8",
            pins=(
                [
                    "rst_n",
                    "pll_enable",
                    "pll_start",
                    "pll_abort_async",
                ]
                + _bus("pll_tclass", 2)
                + _bus("pll_lo_run", 4)
                + _bus("pll_hi_run", 4)
                + _bus("pll_stop_code", 12)
                + _bus("pll_stop_sel", 3)
            ),
        ),
        # NORTH-WEST EDGE — PLL Host Status
        PinGroup(
            key="north_pll_status",
            label="PLL Status",
            short_label="PLL Status",
            edge="top",
            frac_start=0.025,
            frac_end=0.195,
            color="#0284c7",
            pins=(
                [
                    "pll_locked",
                    "pll_busy",
                    "pll_fault",
                ]
                + _bus("pll_state_id", 3)
                + _bus("pll_fault_code", 3)
                + _bus("pll_lo_code", 4)
                + _bus("pll_hi_code", 4)
                + [
                    "pll_coarse_busy",
                    "pll_coarse_done",
                    "pll_fast_end",
                    "pll_slow_end",
                ]
            ),
        ),
        # NORTH EDGE — Host TX & RX Data + Control + arst_n
        PinGroup(
            key="north_tx_host",
            label="TX Host Ingress",
            short_label="TX Host",
            edge="top",
            frac_start=0.220,
            frac_end=0.345,
            color="#047857",
            pins=(
                [
                    "tx_enable",
                    "tx_in_valid",
                    "tx_word_ready",
                ]
                + _bus("tx_in_data", 16)
            ),
        ),
        PinGroup(
            key="north_rx_host",
            label="RX Host FIFO & Align (host_clk, arst_n)",
            short_label="RX Host FIFO & Align (host_clk, arst_n)",
            edge="top",
            frac_start=0.375,
            frac_end=0.965,
            color="#7c3aed",
            pins=(
                [
                    "arst_n",
                    "host_clk",
                    "host_ready",
                    "host_valid",
                    "host_online",
                    "host_error",
                ]
                + _bus("host_data", 16)
                + [
                    "rx_training_enable",
                    "rx_word_online",
                    "rx_aligned",
                ]
                + _bus("rx_offset", 4)
            ),
        ),
        # EAST EDGE — RX CDR Control, Status & Exact-Width Telemetry
        PinGroup(
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


def build_v3_block_spec(
    die_w: float,
    die_h: float,
    margin_x: float = 3.68,
    margin_y: float = 5.44,
    place_density: float = 0.68,
    setup_margin_ns: float = 0.35,
    hold_margin_ns: float = 0.08,
) -> base.BlockSpec:
    # Snap core box to exact SKY130 unithd grid (0.46 um X, 2.72 um Y)
    x0 = round(round(margin_x / 0.46) * 0.46, 2)
    y0 = round(round(margin_y / 2.72) * 2.72, 2)
    core_w = round(int((die_w - 2 * x0) / 0.46 + 1e-6) * 0.46, 2)
    core_h = round(int((die_h - 2 * y0) / 2.72 + 1e-6) * 2.72, 2)
    x1 = round(x0 + core_w, 2)
    y1 = round(y0 + core_h, 2)
    die_w_s = round(x1 + x0, 2)
    die_h_s = round(y1 + y0, 2)

    return base.BlockSpec(
        name=BLOCK_NAME,
        rtl_files=UNIFIED_RTL_FILES,
        clocks=[
            base.ClockSpec(name="ref_clk", port="ref_clk", period_ns=4.0),
            base.ClockSpec(name="tx_word_clk", port="tx_word_clk", period_ns=4.0),
            base.ClockSpec(name="rx_word_clk", port="rx_word_clk", period_ns=4.0),
            base.ClockSpec(name="host_clk", port="host_clk", period_ns=4.0),
        ],
        reset_ports=["rst_n", "arst_n"],
        async_input_ports=[
            "pll_abort_async",
            "bias_ready_async",
            "pre_ref_ready_async",
            "hi_async",
            "lo_async",
            "pw_late_async",
        ],
        params={"PLL_CODE_BITS": 5},
        die_area=(0.0, 0.0, die_w_s, die_h_s),
        core_area=(x0, y0, x1, y1),
        place_density=place_density,
        pdn_v_pitch=36.0,
        pdn_v_offset=10.0,
        pdn_h_pitch=36.0,
        pdn_h_offset=10.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=setup_margin_ns,
        hold_margin_ns=hold_margin_ns,
        output_load_pf=0.020,
        cts_sink_clustering=True,
    )


def write_v3_sdc(block: base.BlockSpec, path: Path, post_route: bool = False) -> None:
    """Write multi-clock SDC with exact synchronous generated clocks (/4 PLL, /2 CDR)."""
    setup_unc = 0.10 if post_route else 0.15
    hold_unc = 0.05 if post_route else 0.08
    clk_prop = "set_propagated_clock [all_clocks]" if post_route else "set_clock_transition 0.12 [all_clocks]"

    sdc = f"""# Multi-clock SDC for {block.name}
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
# I/O timing constraints (20% period max, 0.50 ns min)
# -----------------------------------------------------------------------------
# PLL inputs on ref_clk (start pulse capture) & pll_clk_div4 (enable + static config)
set_input_delay  -clock ref_clk      -max 0.800 [get_ports {{pll_start}}]
set_input_delay  -clock ref_clk      -min 0.500 [get_ports {{pll_start}}]
set_input_delay  -clock pll_clk_div4 -max 1.600 [get_ports {{pll_enable pll_tclass* pll_lo_run* pll_hi_run* pll_stop_code* pll_stop_sel*}}]
set_input_delay  -clock pll_clk_div4 -min 0.500 [get_ports {{pll_enable pll_tclass* pll_lo_run* pll_hi_run* pll_stop_code* pll_stop_sel*}}]
set_output_delay -clock pll_clk_div4 -max 1.600 [get_ports {{precharge_en pfd_rst_b cp_en pll_locked pll_busy pll_fault pll_state_id* pll_fault_code* vco_code* pll_lo_code* pll_hi_code* pll_coarse_busy pll_coarse_done pll_fast_end pll_slow_end switches*}}]
set_output_delay -clock pll_clk_div4 -min 0.100 [get_ports {{precharge_en pfd_rst_b cp_en pll_locked pll_busy pll_fault pll_state_id* pll_fault_code* vco_code* pll_lo_code* pll_hi_code* pll_coarse_busy pll_coarse_done pll_fast_end pll_slow_end switches*}}]

# TX ingress (250 MHz tx_word_clk)
set_input_delay  -clock tx_word_clk  -max 0.800 [get_ports {{tx_enable tx_clock_good tx_in_valid tx_in_data*}}]
set_input_delay  -clock tx_word_clk  -min 0.500 [get_ports {{tx_enable tx_clock_good tx_in_valid tx_in_data*}}]
set_output_delay -clock tx_word_clk  -max 0.800 [get_ports {{tx_word_ready tx_capture_data* tx_capture_valid tx_a_valid tx_b_valid}}]
set_output_delay -clock tx_word_clk  -min 0.100 [get_ports {{tx_word_ready tx_capture_data* tx_capture_valid tx_a_valid tx_b_valid}}]

# RX full-rate 250 MHz word map & aligner I/O (rx_word_clk)
set_input_delay  -clock rx_word_clk  -max 0.800 [get_ports {{rx_phys* rx_training_enable}}]
set_input_delay  -clock rx_word_clk  -min 0.500 [get_ports {{rx_phys* rx_training_enable}}]
set_output_delay -clock rx_word_clk  -max 0.800 [get_ports {{rx_word_online rx_aligned rx_offset*}}]
set_output_delay -clock rx_word_clk  -min 0.100 [get_ports {{rx_word_online rx_aligned rx_offset*}}]

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
set_max_fanout 12 [current_design]
set_max_capacitance 0.095 [current_design]
set_max_transition 0.90 [current_design]
"""
    path.write_text(sdc)


def pin_constraints_tcl(pin_groups: list[PinGroup], die_w: float, die_h: float) -> str:
    lines = ["# Cardinal directional pin constraints (South=Analog, West/North/East=Host/Cfg/Status)"]
    for grp in pin_groups:
        span = die_w if grp.edge in ("bottom", "top") else die_h
        b = round(span * grp.frac_start, 2)
        e = round(span * grp.frac_end, 2)
        pins_str = " ".join(grp.pins)
        lines.append(
            f"set_io_pin_constraint -pin_names {{{pins_str}}} -region {grp.edge}:{b:.2f}-{e:.2f}"
        )
    return "\n".join(lines)


def parse_wirelength_from_log(log_text: str) -> dict[str, int]:
    matches = re.findall(r"Total wire length on LAYER (\w+)\s*=\s*(\d+)\s*um\.", log_text)
    if not matches:
        return {"total_um": 0}
    layers: dict[str, int] = {}
    for lyr, val in matches:
        layers[lyr] = int(val)
    layers["total_um"] = sum(v for k, v in layers.items() if k != "total_um")
    return layers


def parse_antenna_violations(ant_rpt: Path, log_text: str = "") -> int:
    m_post = re.findall(r"POST_ROUTE_ANTENNA_VIOLS:\s*(\d+)", log_text)
    if m_post:
        return int(m_post[-1])
    m2 = re.findall(r"ANT-0002\] Found (\d+) net violations", log_text)
    if m2:
        return int(m2[-1])
    if ant_rpt.exists():
        txt = ant_rpt.read_text()
        return len(re.findall(r"^Net\s*-\s*\S+", txt, re.M))
    return 0


def count_cells_in_def(def_path: Path) -> dict[str, Any]:
    txt = def_path.read_text()
    comp_m = re.search(r"COMPONENTS\s+\d+\s*;(.*?)END COMPONENTS", txt, re.S)
    body = comp_m.group(1) if comp_m else txt
    masters = re.findall(r"^\s*-\s+\S+\s+(sky130_fd_sc_hd__\S+)", body, re.M)

    decap_counts = {k: 0 for k in DECAP_CAP_FF}
    fill_counts = {
        "sky130_fd_sc_hd__fill_1": 0,
        "sky130_fd_sc_hd__fill_2": 0,
        "sky130_fd_sc_hd__fill_4": 0,
        "sky130_fd_sc_hd__fill_8": 0,
    }
    tap_count = 0
    diode_count = 0
    std_count = 0

    for m in masters:
        if m in decap_counts:
            decap_counts[m] += 1
        elif m in fill_counts:
            fill_counts[m] += 1
        elif "__tap" in m:
            tap_count += 1
        elif "__diode_" in m:
            diode_count += 1
        else:
            std_count += 1

    total_decap_cells = sum(decap_counts.values())
    total_decap_ff = sum(decap_counts[k] * DECAP_CAP_FF[k] for k in decap_counts)
    total_decap_pf = round(total_decap_ff / 1000.0, 3)

    return {
        "std_cells": std_count,
        "diode_cells": diode_count,
        "tap_cells": tap_count,
        "decap_cells_total": total_decap_cells,
        "decap_breakdown": {k.replace("sky130_fd_sc_hd__", ""): v for k, v in decap_counts.items()},
        "decap_cap_pf": total_decap_pf,
        "decap_cap_ff": round(total_decap_ff, 1),
        "fill_cells_total": sum(fill_counts.values()),
        "fill_breakdown": {k.replace("sky130_fd_sc_hd__", ""): v for k, v in fill_counts.items()},
        "phys_cells": total_decap_cells + sum(fill_counts.values()) + tap_count,
        "total_cells": len(masters),
    }


def verify_pin_regions_in_def(def_path: Path, pin_groups: list[PinGroup], die_w: float, die_h: float) -> dict[str, Any]:
    txt = def_path.read_text()
    pins_m = re.search(r"PINS\s+\d+\s*;(.*?)END PINS", txt, re.S)
    body = pins_m.group(1) if pins_m else ""
    dbu_m = re.search(r"UNITS DISTANCE MICRONS (\d+)", txt)
    dbu = float(dbu_m.group(1)) if dbu_m else 1000.0

    pin_coords: dict[str, tuple[float, float]] = {}
    for entry in body.split(";"):
        nm = re.search(r"-\s+(\S+)\s+\+\s+NET", entry)
        pt = re.search(r"\+\s+(?:PLACED|FIXED)\s+\(\s*([-0-9]+)\s+([-0-9]+)\s*\)", entry)
        if nm and pt:
            name = nm.group(1).replace("\\[", "[").replace("\\]", "]")
            pin_coords[name] = (int(pt.group(1)) / dbu, int(pt.group(2)) / dbu)

    violations: list[str] = []
    group_counts: dict[str, int] = {}
    tol = 2.0
    for grp in pin_groups:
        span = die_w if grp.edge in ("bottom", "top") else die_h
        lo = span * grp.frac_start - tol
        hi = span * grp.frac_end + tol
        cnt = 0
        for pname in grp.pins:
            if pname not in pin_coords:
                violations.append(f"MISSING pin {pname}")
                continue
            x, y = pin_coords[pname]
            cnt += 1
            if grp.edge == "bottom":
                if y > tol or not (lo <= x <= hi):
                    violations.append(f"{pname} at ({x:.1f},{y:.1f}) outside bottom:{lo:.1f}-{hi:.1f}")
            elif grp.edge == "top":
                if abs(die_h - y) > tol or not (lo <= x <= hi):
                    violations.append(f"{pname} at ({x:.1f},{y:.1f}) outside top:{lo:.1f}-{hi:.1f}")
            elif grp.edge == "left":
                if x > tol or not (lo <= y <= hi):
                    violations.append(f"{pname} at ({x:.1f},{y:.1f}) outside left:{lo:.1f}-{hi:.1f}")
            elif grp.edge == "right":
                if abs(die_w - x) > tol or not (lo <= y <= hi):
                    violations.append(f"{pname} at ({x:.1f},{y:.1f}) outside right:{lo:.1f}-{hi:.1f}")
        group_counts[grp.key] = cnt

    return {
        "total_signal_pins_checked": sum(group_counts.values()),
        "group_pin_counts": group_counts,
        "region_violations": len(violations),
        "violation_samples": violations[:10],
    }


def build_v3_synth_lib(src_lib: Path, dst_lib: Path) -> Path:
    """Create filtered SS Liberty for v3.1 Yosys synthesis.

    Matches v3.0 fast_ss filtering while unlocking ``sky130_fd_sc_hd__mux4_2``
    (saves 168 cells / ~901 um^2 in rx_word_host_shared with 0.000 ns SS setup penalty;
    ``fa_*``/``ha_*`` stay excluded because SKY130 HD full-adder 3-PMOS carry delay
    degrades 250/125 MHz rx_cdr_loop SS setup by -0.84 ns).
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
    unlock_compound = {"sky130_fd_sc_hd__mux4_2"}

    out: list[str] = []
    skipping = False
    brace_depth = 0
    for line in lines:
        if not skipping:
            m = cell_re.match(line)
            if m:
                cname = m.group(1)
                exclude = (
                    base.should_exclude_for_synth(cname, drc_exclude, fast_ss=True)
                    or cname in weak_one
                )
                if cname in unlock_compound:
                    exclude = False
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


def v3_openroad_dont_use_tcl() -> str:
    """OpenROAD dont_use policy for v3.1:
    - Exclude clkbuf_* / clkinv_* BEFORE repair_design so resizer NEVER caches clkbuf_16
      as a data/hold buffer (CTS explicit -root_buf / -buf_list still uses clkbuf_16/8/4!).
    - Unlock compact DRC-clean hold delay cells (dlygate4sd1/2/3_1, dlymetal6s2s/4s_1,
      buf_1, buf_2) so repair_timing -hold inserts tiny delay cells instead of giant clkbuf_16!
    - Unlock sky130_fd_sc_hd__mux4_2 while keeping slow _1 logic and 3/4-stack cells excluded.
    """
    drc_exclude = sorted(base.load_excluded_cells())
    allow_cells = {
        "sky130_fd_sc_hd__buf_1",
        "sky130_fd_sc_hd__mux4_2",
        "sky130_fd_sc_hd__dlygate4sd1_1",
        "sky130_fd_sc_hd__dlygate4sd2_1",
        "sky130_fd_sc_hd__dlygate4sd3_1",
        "sky130_fd_sc_hd__dlymetal6s2s_1",
        "sky130_fd_sc_hd__dlymetal6s4s_1",
        "sky130_fd_sc_hd__conb_1",
    }
    patterns = [
        "*_0",
        "sky130_fd_sc_hd__lpflow_*",
        "sky130_fd_sc_hd__sdf*",
        "sky130_fd_sc_hd__sedf*",
        "sky130_fd_sc_hd__sdlclkp*",
        "sky130_fd_sc_hd__probe*",
        "sky130_fd_sc_hd__ebuf*",
        "sky130_fd_sc_hd__clkdlybuf*",
        "sky130_fd_sc_hd__dlymetal6s6s_1",
        "sky130_fd_sc_hd__clkbuf_*",
        "sky130_fd_sc_hd__clkinv_*",
        "sky130_fd_sc_hd__bufbuf_16",
        "sky130_fd_sc_hd__bufbuf_8",
        "sky130_fd_sc_hd__buf_16",
    ] + drc_exclude
    for tok in base.SLOW_SS_CELL_TOKENS:
        if tok == "__mux4":
            patterns += ["sky130_fd_sc_hd__mux4_1", "sky130_fd_sc_hd__mux4_4"]
        else:
            patterns.append(f"sky130_fd_sc_hd{tok}*")
    lib_text = base.LIB_SS.read_text()
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


def audit_netlist_v(verilog_path: Path) -> dict[str, Any]:
    """Audit post-route gate-level netlist for hold buffers, clkbuf_16, dly*, and compound cells."""
    txt = verilog_path.read_text()
    cells = re.findall(r"^\s*(sky130_fd_sc_hd__\S+)\s+(\S+)\s*\(", txt, re.M)
    hold_bd: dict[str, int] = {}
    clkbuf_bd: dict[str, int] = {}
    dly_bd: dict[str, int] = {}
    compound_bd: dict[str, int] = {}
    for master, inst in cells:
        short = master.replace("sky130_fd_sc_hd__", "")
        if inst.startswith("hold"):
            hold_bd[short] = hold_bd.get(short, 0) + 1
        if short.startswith("clkbuf_"):
            clkbuf_bd[short] = clkbuf_bd.get(short, 0) + 1
        if short.startswith("dly"):
            dly_bd[short] = dly_bd.get(short, 0) + 1
        if short.startswith(("mux4_", "fa_", "ha_")):
            compound_bd[short] = compound_bd.get(short, 0) + 1
    return {
        "hold_buffers_total": sum(hold_bd.values()),
        "hold_clkbuf_16": hold_bd.get("clkbuf_16", 0),
        "hold_breakdown": dict(sorted(hold_bd.items(), key=lambda kv: (-kv[1], kv[0]))),
        "clkbuf_total_breakdown": dict(sorted(clkbuf_bd.items(), key=lambda kv: (-kv[1], kv[0]))),
        "dly_total": sum(dly_bd.values()),
        "dly_breakdown": dict(sorted(dly_bd.items(), key=lambda kv: (-kv[1], kv[0]))),
        "compound_cells": dict(sorted(compound_bd.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


def run_v3_yosys(block: base.BlockSpec, work: Path, synth_lib: Path) -> tuple[Path, dict[str, Any]]:
    """Per-subsystem Yosys synthesis with domain-appropriate ABC delay targets:
      - 250 MHz data blocks (rx_word_map, rx_word_host_shared): abc -D 1000
      - 250 MHz tx_ingress_control: abc -D 2200
      - 125 MHz rx_cdr_loop (with 250 MHz 2-tick voter): abc -D 2800
      - 62.5 MHz pll_control_top: abc -D 10000 (minimum area!)
    """
    subblocks = [
        (
            "pll_control_top",
            [
                "digital/pnr/rtl_v3/mon_sync.sv",
                "digital/pnr/rtl_v3/mon_persist.sv",
                "digital/pnr/rtl_v3/pll_startup_supervisor.sv",
                "digital/pnr/rtl_v3/pll_coarse_ctrl.sv",
                "digital/pnr/rtl_v3/pll_lock_detect.sv",
                "digital/pnr/rtl_v3/pll_control_top.sv",
            ],
            {"CODE_BITS": block.params.get("PLL_CODE_BITS", 5)},
            10000,
        ),
        (
            "tx_ingress_control",
            ["digital/pnr/rtl_v3/tx_ingress_control.sv"],
            {},
            2200,
        ),
        (
            "rx_word_map",
            ["digital/pnr/rtl_v3/rx_word_map.sv"],
            {},
            1000,
        ),
        (
            "rx_word_host_shared",
            [
                "digital/pnr/rtl_v3/rx_word_align16.sv",
                "digital/pnr/rtl_v3/rx_async_word_fifo.sv",
                "digital/pnr/rtl_v3/serdes_digital_top_v3.sv",
            ],
            {},
            1000,
        ),
        (
            "rx_cdr_loop",
            [
                "digital/pnr/rtl_v3/bbpd_window_vote.sv",
                "digital/pnr/rtl_v3/cdr_phase_frequency.sv",
                "digital/pnr/rtl_v3/pi_step_commutator.sv",
                "digital/pnr/rtl_v3/rx_cdr_loop.sv",
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

    top_src = (REPO / "digital/pnr/rtl_v3/serdes_digital_top_v3.sv").read_text()
    top_only = top_src.split("/* verilator lint_off DECLFILENAME */")[0]
    top_clean = re.sub(
        r"\b(pll_control_top|tx_ingress_control|rx_word_host_shared)\s*#\s*\((?:[^()]|\([^()]*\))*\)",
        r"\1",
        top_only,
    )
    wrap_sv = work / f"{block.name}_link_wrap.sv"
    wrap_sv.write_text(top_clean)

    synth_v = work / f"{block.name}_synth.v"
    ys_path = work / "synth.ys"
    cmds = [
        f"read_liberty -lib {synth_lib}",
        f"read_verilog {' '.join(sub_vs)}",
        f"read_verilog -sv {wrap_sv}",
        f"chparam -set PLL_CODE_BITS {block.params.get('PLL_CODE_BITS', 5)} {block.name}",
        f"hierarchy -check -top {block.name}",
        "flatten",
        "splitnets",
        "opt_clean -purge",
        "hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO",
        "insbuf -buf sky130_fd_sc_hd__buf_8 A X",
        # Cleanly hide all dotted hierarchical cell/wire names (required for clean Netgen LVS!),
        # while promoting the two generated-clock nets to clean dot-free top names!
        f"cd {block.name}",
        "rename u_pll.pll_clk_div4 pll_clk_div4_net",
        "rename u_rx_cdr.cdr_clk_div2 cdr_clk_div2_net",
        "rename -hide c:* w:* w:pll_clk_div4_net %d w:cdr_clk_div2_net %d",
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


def run_v3_magic(block: base.BlockSpec, work: Path, routed_def: Path) -> dict[str, Any]:
    """Magic DEF->MAG/GDS + Full-Rule DRC + LVS extraction with 600s timeout."""
    mag_out = work / f"{block.name}.mag"
    gds_out = work / f"{block.name}.gds"
    lvs_spice = work / f"{block.name}_lvs.spice"

    for old_ext in work.glob("*.ext"):
        old_ext.unlink()
    if mag_out.exists():
        mag_out.unlink()

    tcl_drc = work / "magic_drc_gds.tcl"
    tcl_drc.write_text(
        f"""
drc off
lef read {base.TLEF_NOM}
def read {routed_def}
load {block.name}
select top cell
save {block.name}

cif *hier write disable
gds write {gds_out}

drc style drc(full)
drc euclidean on
drc on
drc check
drc catchup
drc count total
drc listall why
quit -noprompt
"""
    )
    proc_drc = base.run_cmd(
        [str(base.MAGIC), "-noconsole", "-dnull", "-rcfile", str(base.MAGIC_RC), str(tcl_drc)],
        work,
        work / "04a_magic_drc_gds.log",
        timeout=600,
    )
    log_drc = proc_drc.stdout + proc_drc.stderr
    m = re.search(r"Total DRC errors found:\s*(\d+)", log_drc)
    drc_total = int(m.group(1)) if m else -1

    tcl_ext = work / "magic_ext_lvs.tcl"
    tcl_ext.write_text(
        f"""
drc off
load {block.name}
select top cell
extract no all
extract do local
extract unique
extract all
ext2spice lvs
ext2spice -o {lvs_spice}
quit -noprompt
"""
    )
    base.run_cmd(
        [str(base.MAGIC), "-noconsole", "-dnull", "-rcfile", str(base.MAGIC_RC), str(tcl_ext)],
        work,
        work / "04b_magic_ext_lvs.log",
        timeout=600,
    )
    if not gds_out.exists() or not lvs_spice.exists():
        raise RuntimeError(f"Magic did not produce GDS or LVS SPICE for {block.name}; see {work}")
    return {
        "magic_drc_total": drc_total,
        "mag_path": str(mag_out),
        "gds_path": str(gds_out),
        "lvs_spice_path": str(lvs_spice),
    }


def run_v3_openroad_pnr(
    block: base.BlockSpec,
    pin_groups: list[PinGroup],
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
    pin_tcl = pin_constraints_tcl(pin_groups, die_w, die_h)

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

    pnr_tcl = work / "pnr.tcl"
    pnr_tcl.write_text(
        f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
define_corners ss ff
read_liberty -corner ss {base.LIB_SS}
read_liberty -corner ff {base.LIB_FF}
read_verilog {synth_v}
link_design {block.name}
read_sdc {sdc_path}

{v3_openroad_dont_use_tcl()}

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

# Graph-partitioned subsystem regions (PLL West, RX East -> short local wires!)
set blk_fp [[[ord::get_db] getChip] getBlock]
set skip_nets {{VPWR VGND rst_n arst_n ref_clk tx_word_clk rx_word_clk host_clk}}
proc _collect_domain {{blk seed_clks skip_nets}} {{
  set visited {{}}
  set queue {{}}
  foreach clk $seed_clks {{
    foreach reg [all_registers -clock $clk] {{
      set nm [get_full_name $reg]
      set inst [$blk findInst $nm]
      if {{$inst ne "NULL" && ![dict exists $visited $nm]}} {{
        dict set visited $nm $inst
        lappend queue $inst
      }}
    }}
  }}
  set idx 0
  while {{$idx < [llength $queue]}} {{
    set cur [lindex $queue $idx]
    incr idx
    foreach it [$cur getITerms] {{
      set net [$it getNet]
      if {{$net eq "NULL" || [$net isSpecial]}} {{ continue }}
      set nn [$net getName]
      if {{[lsearch -exact $skip_nets $nn] >= 0}} {{ continue }}
      if {{[llength [$net getITerms]] > 120}} {{ continue }}
      foreach oit [$net getITerms] {{
        set oi [$oit getInst]
        set om [[$oi getMaster] getName]
        if {{[string match "*conb*" $om]}} {{ continue }}
        set onm [$oi getName]
        if {{![dict exists $visited $onm]}} {{
          dict set visited $onm $oi
          lappend queue $oi
        }}
      }}
    }}
  }}
  return $queue
}}
set pll_insts [_collect_domain $blk_fp {{ref_clk pll_clk_div4}} $skip_nets]
set tx_insts  [_collect_domain $blk_fp {{tx_word_clk}} $skip_nets]
set rx_insts  [_collect_domain $blk_fp {{rx_word_clk cdr_clk_div2 host_clk}} $skip_nets]
set cx0 [expr {{int({block.core_area[0]} * 1000)}}]
set cy0 [expr {{int({block.core_area[1]} * 1000)}}]
set cx1 [expr {{int({block.core_area[2]} * 1000)}}]
set cy1 [expr {{int({block.core_area[3]} * 1000)}}]
set pll_x1 [expr {{int({die_w} * 0.165 * 1000)}}]
set tx_x0  [expr {{int({die_w} * 0.170 * 1000)}}]
set tx_x1  [expr {{int({die_w} * 0.215 * 1000)}}]
set tx_y0  [expr {{$cy0 + 70000}}]
set tx_y1  [expr {{$cy1 - 70000}}]
set rx_x0  [expr {{int({die_w} * 0.220 * 1000)}}]
set r_pll [odb::dbRegion_create $blk_fp "reg_pll"]
odb::dbBox_create $r_pll $cx0 $cy0 $pll_x1 $cy1
set r_tx  [odb::dbRegion_create $blk_fp "reg_tx"]
odb::dbBox_create $r_tx  $tx_x0 $tx_y0 $tx_x1 $tx_y1
set r_rx  [odb::dbRegion_create $blk_fp "reg_rx"]
odb::dbBox_create $r_rx  $rx_x0 $cy0 $cx1 $cy1
foreach inst $pll_insts {{ $r_pll addInst $inst }}
foreach inst $tx_insts  {{ $r_tx  addInst $inst }}
foreach inst $rx_insts  {{ $r_rx  addInst $inst }}
puts "REGION_COUNTS: pll=[llength $pll_insts] tx=[llength $tx_insts] rx=[llength $rx_insts]"

# Stage 1: Timing-driven global placement
set_wire_rc -corner ss -signal -resistance 0.0020 -capacitance 0.00028
set_wire_rc -corner ss -clock  -resistance 0.0008 -capacitance 0.00024
set_wire_rc -corner ff -signal -resistance 0.0007 -capacitance 0.00009
set_wire_rc -corner ff -clock  -resistance 0.0003 -capacitance 0.00008
set_routing_layers -signal met1-met5 -clock met1-met5

global_placement -timing_driven -density {block.place_density:.2f}
place_pins -hor_layers met3 -ver_layers met2 -corner_avoidance 8 -min_distance 2 -min_distance_in_tracks

# Stage 2: Design repair & CTS (balanced clkbuf_16/8/4 kills 336 ps rx_word_clk skew; moderate cap/fanout avoids useless double-rebuffers!)
{wire_rc_block}
estimate_parasitics -placement
set_max_transition 0.95 [current_design]
set_max_capacitance 0.11 [current_design]
set_max_fanout 14 [current_design]
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
  -buf_list {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4}} \\
  -balance_levels -sink_clustering_enable -sink_clustering_size 16 -sink_clustering_max_diameter 50
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_clock_nets
detailed_placement

# Keep giant clkbuf_* out of data/hold repair (so hold repair uses tiny 4-site buf_2 cells!)
set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}

# Stage 3: Setup + Hold repair at realistic placement RC
set_wire_rc -corner ss -signal -resistance 0.0022 -capacitance 0.00030
set_wire_rc -corner ss -clock  -resistance 0.0008 -capacitance 0.00024
estimate_parasitics -placement
repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 2
detailed_placement

estimate_parasitics -placement
repair_timing -hold -slack_margin {block.hold_margin_ns:.3f} -max_buffer_percent 25
global_placement -incremental -density 0.80
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  puts "WARN: detailed_placement left a local TAP/cell overlap; running incremental legalization..."
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

estimate_parasitics -placement
repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 1
detailed_placement
estimate_parasitics -placement
repair_timing -hold -slack_margin {block.hold_margin_ns:.3f} -max_buffer_percent 15
detailed_placement
if {{[catch {{check_placement -verbose}}]}} {{
  puts "WARN: detailed_placement left a local TAP/cell overlap; running incremental legalization..."
  global_placement -incremental -density 0.85
  detailed_placement
  check_placement -verbose
}}

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

# Priority Decap Fill (decap_12/8/6/4/3 before fill_2/1)
filler_placement {decap_fill_list}
add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground

global_route -congestion_iterations 80 -allow_congestion
set_propagated_clock [all_clocks]
detailed_route -output_drc {drc_rpt} -bottom_routing_layer met1 -top_routing_layer met5 -droute_end_iter 45 -verbose 1

# IMPORTANT: write DEF/Verilog BEFORE check_antennas so Magic parses clean orthogonal DEF wires!
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
        proc = base.run_cmd(
            [str(base.OPENROAD), "-threads", "1", "-no_init", "-exit", str(pnr_tcl)],
            work,
            work / "02_openroad_pnr.log",
            timeout=1800,
        )
        log = proc.stdout

    # Post-route OpenRCX SPEF-driven ECO + Antenna closure loop (exits immediately once closed!)
    sdc_eco = work / f"{block.name}_eco.sdc"
    write_v3_sdc(block, sdc_eco, post_route=True)
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
read_liberty -corner ss {base.LIB_SS}
read_liberty -corner ff {base.LIB_FF}
read_def {routed_def}
read_sdc {sdc_eco}
{v3_openroad_dont_use_tcl()}

read_spef -corner ss {spef_eco_max}
read_spef -corner ff {spef_eco_min}

set init_wns [sta::worst_slack -corner ss -max]
set init_hold_ff [sta::worst_slack -corner ff -min]
set init_hold_ss [sta::worst_slack -corner ss -min]
set init_hold [expr {{$init_hold_ff < $init_hold_ss ? $init_hold_ff : $init_hold_ss}}]
# IMPORTANT: Pass a scratch -report_file here so we do NOT truncate the already-flushed
# ant_post_rpt from the prior pass (OpenROAD buffers -report_file until process exit)!
set init_ant [check_antennas -report_file {work}/_ant_tmp.rpt]
puts [format "ECO_P{eco_pass}_INIT: SS_WNS=%.4f FF_HOLD=%.4f SS_HOLD=%.4f ANT=%d" $init_wns $init_hold_ff $init_hold_ss $init_ant]
if {{$init_wns >= 0.05 && $init_hold >= 0.035 && $init_ant == 0}} {{
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
# On pass 7, perform antenna-only cleanup so we never introduce a new antenna on the final pass!
if {{$init_wns < 0.06 && {eco_pass} <= 6}} {{
  set_clock_uncertainty -setup [expr {{0.10 + {gb}}}] [all_clocks]
  for {{set iter 0}} {{$iter < 25}} {{incr iter}} {{
    set wns [sta::worst_slack -corner ss -max]
    if {{$wns >= 0.05}} {{ break }}
    set seen {{}}
    set improved 0
    foreach clk_grp {{{clk_groups_tcl}}} {{
      set paths [find_timing_paths -corner ss -path_delay max -path_group $clk_grp -group_count 30 -endpoint_count 1 -slack_max 0.06]
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
    puts [format "ECO_P{eco_pass}_ITER %d: swapped=%d SS_WNS_REAL=%.4f SS_TNS_GB=%.4f FF_HOLD=%.4f" $iter $eco_swapped [expr {{[sta::worst_slack -corner ss -max] + {gb}}}] [sta::total_negative_slack -corner ss -max] [sta::worst_slack -corner ff -min]]
    if {{!$improved}} {{ break }}
  }}
  set_clock_uncertainty -setup 0.10 [all_clocks]
}}

set post_eco_wns [sta::worst_slack -corner ss -max]
set post_hold_ff [sta::worst_slack -corner ff -min]
set post_hold_ss [sta::worst_slack -corner ss -min]

# General Hold-Guarded Useful-Skew Clock-Leaf ECO (in-place clkbuf_{2,4,8,16} master sizing only;
# 0 new cells, 0 new nets, 100% LVS clean, strictly guarded by FF_HOLD >= 0.10 ns!).
# Runs only on violating paths where data-cell upsizing has saturated (passes 1..4).
set eco_cloned 0
if {{$post_eco_wns < 0.05 && $post_hold_ff >= 0.10 && {eco_pass} <= 5}} {{
  set launch_leaves {{}}
  set cap_leaves {{}}
  foreach clk_grp {{{clk_groups_tcl}}} {{
    set paths [find_timing_paths -corner ss -path_delay max -path_group $clk_grp -group_count 15 -endpoint_count 1 -slack_max 0.05]
    foreach pe $paths {{
      set sp_pin [get_property $pe startpoint]
      set ep_pin [get_property $pe endpoint]
      if {{$sp_pin eq "" || $ep_pin eq ""}} {{ continue }}
      if {{[$sp_pin is_top_level_port] || [$ep_pin is_top_level_port]}} {{ continue }}
      set sp_inst [$sp_pin instance]
      set ep_inst [$ep_pin instance]
      if {{$sp_inst eq "NULL" || $ep_inst eq "NULL"}} {{ continue }}
      set sp_db [$blk_eco findInst [get_full_name $sp_inst]]
      set ep_db [$blk_eco findInst [get_full_name $ep_inst]]
      if {{$sp_db eq "NULL" || $ep_db eq "NULL"}} {{ continue }}
      foreach {{tag dbff}} [list L $sp_db C $ep_db] {{
        set clk_it [$dbff findITerm CLK]
        if {{$clk_it eq "NULL"}} {{ continue }}
        set cnet [$clk_it getNet]
        if {{$cnet eq "NULL"}} {{ continue }}
        foreach cit [$cnet getITerms] {{
          if {{[[$cit getMTerm] getIoType] eq "OUTPUT"}} {{
            set drv [$cit getInst]
            set dnm [$drv getName]
            set dmn [[$drv getMaster] getName]
            if {{[string match "sky130_fd_sc_hd__clkbuf_*" $dmn]}} {{
              if {{$tag eq "L"}} {{ dict set launch_leaves $dnm $dmn }} else {{ dict set cap_leaves $dnm $dmn }}
            }}
          }}
        }}
      }}
    }}
  }}
  # Record clean clock-leaf master swaps to apply in Python onto the written eco_edit.def
  # (OpenROAD ODB swapMaster on a routed clock net is applied cleanly post-wire-strip).
  set skew_swaps {{}}
  dict for {{lnm lmn}} $launch_leaves {{
    if {{[dict exists $cap_leaves $lnm]}} {{ continue }}
    if {{$lmn eq "sky130_fd_sc_hd__clkbuf_2" || $lmn eq "sky130_fd_sc_hd__clkbuf_4"}} {{
      dict set skew_swaps $lnm "sky130_fd_sc_hd__clkbuf_16"
    }} elseif {{$lmn eq "sky130_fd_sc_hd__clkbuf_8"}} {{
      dict set skew_swaps $lnm "sky130_fd_sc_hd__clkbuf_16"
    }}
  }}
  dict for {{cnm cmn}} $cap_leaves {{
    if {{[dict exists $launch_leaves $cnm]}} {{
      # Shared launch+capture leaf: gently bump clkbuf_4 -> clkbuf_8 if needed
      if {{$cmn eq "sky130_fd_sc_hd__clkbuf_4"}} {{
        dict set skew_swaps $cnm "sky130_fd_sc_hd__clkbuf_8"
      }}
      continue
    }}
    if {{$cmn eq "sky130_fd_sc_hd__clkbuf_16"}} {{
      dict set skew_swaps $cnm "sky130_fd_sc_hd__clkbuf_4"
    }} elseif {{$cmn eq "sky130_fd_sc_hd__clkbuf_8"}} {{
      dict set skew_swaps $cnm "sky130_fd_sc_hd__clkbuf_4"
    }} elseif {{$cmn eq "sky130_fd_sc_hd__clkbuf_4" && $post_eco_wns < -0.10}} {{
      dict set skew_swaps $cnm "sky130_fd_sc_hd__clkbuf_2"
    }}
  }}
  dict for {{snm smn}} $skew_swaps {{
    puts "ECO_P{eco_pass}_SKEWSWAP: $snm -> $smn"
    incr eco_cloned
  }}
}}

set need_hold_fix [expr {{$post_hold_ff < 0.035 || $post_hold_ss < 0.035}}]
if {{$eco_swapped == 0 && $eco_cloned == 0 && !$need_hold_fix && $init_ant == 0}} {{
  puts "ECO_P{eco_pass}_NO_CHANGES"
  exit 0
}}

# Direct ODB post-DRT antenna diode insertion using the already-flushed ant_post_rpt from prior pass!
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
            # Place diode near sink; if pass >= 2 (net already has 1 diode), add 2 diodes to double diffusion ratio!
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
          }} else {{
            puts "WARN_ANT_MISS: net=$cur_net ($net_obj) inst=$iname ($inst_obj)"
          }}
        }}
      }}
    }}
    close $fp
  }}
  puts "ECO_P{eco_pass}_DRT_DIODES_ADDED: $drt_diodes_added"
}}

if {{$need_hold_fix}} {{
  set_dont_use {{sky130_fd_sc_hd__clkbuf_16 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_2}}
  estimate_parasitics -placement
  repair_timing -hold -slack_margin 0.08 -max_buffer_percent 10
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
# Write edited netlist/placement to a clean DEF and exit so detailed_route runs in a fresh
# OpenROAD process (eliminates stale STA/ODB pointers after dbNet_destroy / structural edits!).
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

        # Apply any recorded useful-skew clock-leaf master swaps cleanly onto eco_edit.def
        # before the fresh OpenROAD legalization + route process!
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
read_liberty {base.LIB_SS}
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

    wl = parse_wirelength_from_log(log)
    cell_stats = count_cells_in_def(routed_def)
    netlist_audit = audit_netlist_v(routed_v)
    ant_viols = parse_antenna_violations(ant_post_rpt, log)
    pin_check = verify_pin_regions_in_def(
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


def run_v3_sta_3corner(block: base.BlockSpec, work: Path, pnr_info: dict[str, Any]) -> dict[str, Any]:
    """3-corner OpenRCX post-route STA reporting overall AND per-clock (all 6 clocks) worst setup/hold."""
    sdc_post = work / f"{block.name}_postroute.sdc"
    write_v3_sdc(block, sdc_post, post_route=True)

    corners = [
        ("tt_025C_1v80", base.LIB_TT, base.RCX_NOM, Path(pnr_info["spef_nom"])),
        ("ss_100C_1v60", base.LIB_SS, base.RCX_MAX, Path(pnr_info["spef_max"])),
        ("ff_n40C_1v95", base.LIB_FF, base.RCX_MIN, Path(pnr_info["spef_min"])),
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
    for cname, lib_path, rcx_rule, spef_path in corners:
        tcl = work / f"sta_{cname}.tcl"
        tcl.write_text(
            f"""
read_lef {base.TLEF_NOM}
read_lef {base.SC_LEF}
read_liberty {lib_path}
read_def {pnr_info["routed_def"]}
read_sdc {sdc_post}

define_process_corner -ext_model_index 0 {cname}
extract_parasitics -ext_model_file {rcx_rule}
write_spef {spef_path}
read_spef {spef_path}

puts "=== SETUP_WORST ==="
report_checks -path_delay max -sort_by_slack -format full_clock_expanded -digits 4
puts "=== HOLD_WORST ==="
report_checks -path_delay min -sort_by_slack -format full_clock_expanded -digits 4
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
            "per_clock": per_clk,
        }
    return sta_results


def render_v3_png(
    block: base.BlockSpec,
    pin_groups: list[PinGroup],
    mag_path: Path,
    png_path: Path,
    pnr_info: dict[str, Any],
    sta_info: dict[str, Any],
    drc_total: int,
    lvs_status: str,
) -> None:
    """Crisp white-background layout PNG with color-coded cardinal pin group banners & labels."""
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
            (0.0, 0.0),
            die_w,
            die_h,
            facecolor="#fafafa",
            edgecolor="#0f172a",
            linewidth=1.8,
            zorder=0,
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

        edges: dict[str, list[tuple[str, float, float]]] = {"top": [], "bottom": [], "left": [], "right": []}
        for name, x, y in pin_labels:
            d_top, d_bot = abs(die_h - y), abs(y)
            d_left, d_right = abs(x), abs(die_w - x)
            m = min(d_top, d_bot, d_left, d_right)
            if m == d_top:
                edges["top"].append((name, x, y))
            elif m == d_bot:
                edges["bottom"].append((name, x, y))
            elif m == d_left:
                edges["left"].append((name, x, y))
            else:
                edges["right"].append((name, x, y))

        min_gap_x = max(7.0, die_w / 44.0)
        min_gap_y = max(6.8, die_h / 34.0)
        off_pin = 3.0
        for edge_name, pts in edges.items():
            if edge_name in ("top", "bottom"):
                pts.sort(key=lambda t: t[1])
                last = -1e9
                for name, x, y in pts:
                    if x - last < min_gap_x:
                        continue
                    last = x
                    ty = die_h + off_pin if edge_name == "top" else -off_pin
                    va = "bottom" if edge_name == "top" else "top"
                    ax.text(
                        x, ty, name, fontsize=5.3, color=pin_color.get(name, "#0f172a"),
                        ha="center", va=va, rotation=90, zorder=55,
                    )
            else:
                pts.sort(key=lambda t: t[2])
                last = -1e9
                for name, x, y in pts:
                    if y - last < min_gap_y:
                        continue
                    last = y
                    tx = -off_pin if edge_name == "left" else die_w + off_pin
                    ha = "right" if edge_name == "left" else "left"
                    ax.text(
                        tx, y, name, fontsize=5.3, color=pin_color.get(name, "#0f172a"),
                        ha=ha, va="center", zorder=55,
                    )

    group_handles: list[Patch] = []
    b_off_x = 54.0
    b_off_y = 38.0
    for grp in pin_groups:
        group_handles.append(Patch(facecolor=grp.color, label=f"{grp.label} ({len(grp.pins)})"))
        if grp.edge == "bottom":
            x0, x1 = die_w * grp.frac_start, die_w * grp.frac_end
            yb = -b_off_y
            ax.plot([x0, x1], [yb, yb], color=grp.color, linewidth=2.6, zorder=60)
            ax.plot([x0, x0], [yb, yb + 3.0], color=grp.color, linewidth=1.8, zorder=60)
            ax.plot([x1, x1], [yb, yb + 3.0], color=grp.color, linewidth=1.8, zorder=60)
            ax.text(
                0.5 * (x0 + x1), yb - 3.5, f"{grp.short_label} [{len(grp.pins)}]",
                fontsize=7.4, fontweight="bold", color=grp.color, ha="center", va="top", zorder=62,
            )
        elif grp.edge == "top":
            x0, x1 = die_w * grp.frac_start, die_w * grp.frac_end
            yt = die_h + b_off_y
            ax.plot([x0, x1], [yt, yt], color=grp.color, linewidth=2.6, zorder=60)
            ax.plot([x0, x0], [yt - 3.0, yt], color=grp.color, linewidth=1.8, zorder=60)
            ax.plot([x1, x1], [yt - 3.0, yt], color=grp.color, linewidth=1.8, zorder=60)
            ax.text(
                0.5 * (x0 + x1), yt + 3.5, f"{grp.short_label} [{len(grp.pins)}]",
                fontsize=7.4, fontweight="bold", color=grp.color, ha="center", va="bottom", zorder=62,
            )
        elif grp.edge == "left":
            y0, y1 = die_h * grp.frac_start, die_h * grp.frac_end
            xl = -b_off_x
            ax.plot([xl, xl], [y0, y1], color=grp.color, linewidth=2.6, zorder=60)
            ax.plot([xl, xl + 3.0], [y0, y0], color=grp.color, linewidth=1.8, zorder=60)
            ax.plot([xl, xl + 3.0], [y1, y1], color=grp.color, linewidth=1.8, zorder=60)
            ax.text(
                xl - 4.0, 0.5 * (y0 + y1), f"{grp.short_label} [{len(grp.pins)}]",
                fontsize=7.4, fontweight="bold", color=grp.color, ha="right", va="center", rotation=90, zorder=62,
            )
        elif grp.edge == "right":
            y0, y1 = die_h * grp.frac_start, die_h * grp.frac_end
            xr = die_w + b_off_x
            ax.plot([xr, xr], [y0, y1], color=grp.color, linewidth=2.6, zorder=60)
            ax.plot([xr - 3.0, xr], [y0, y0], color=grp.color, linewidth=1.8, zorder=60)
            ax.plot([xr - 3.0, xr], [y1, y1], color=grp.color, linewidth=1.8, zorder=60)
            ax.text(
                xr + 4.0, 0.5 * (y0 + y1), f"{grp.short_label} [{len(grp.pins)}]",
                fontsize=7.4, fontweight="bold", color=grp.color, ha="left", va="center", rotation=270, zorder=62,
            )

    pad_x = 74.0
    pad_y = 58.0
    ax.set_xlim(-pad_x, die_w + pad_x)
    ax.set_ylim(-pad_y, die_h + pad_y)
    ax.set_aspect("equal")
    ax.set_xlabel("x (µm)   —   SOUTH EDGE FACES ANALOG CORE (PLL | TX | RX)", fontsize=9.5, fontweight="bold")
    ax.set_ylabel("y (µm)", fontsize=9.5)
    ax.grid(True, linestyle="--", linewidth=0.35, color="#cbd5e1", alpha=0.8)

    cs = pnr_info["cell_stats"]
    tt_s = sta_info["tt_025C_1v80"]["setup_wns_ns"]
    ss_s = sta_info["ss_100C_1v60"]["setup_wns_ns"]
    ff_h = sta_info["ff_n40C_1v95"]["hold_wns_ns"]
    wl_mm = pnr_info["wirelength"]["total_um"] / 1000.0

    subtitle = (
        f"Die {die_w:.1f}×{die_h:.1f} µm ({pnr_info['die_area_um2']:.0f} µm² = {pnr_info['die_area_um2']/1e6:.4f} mm²) | "
        f"StdCells={cs['std_cells']} | Util={pnr_info['utilization_pct']:.1f}% | WL={wl_mm:.1f} mm\n"
        f"Decap={cs['decap_cells_total']} cells ({cs['decap_cap_pf']:.1f} pF) | Diodes={cs['diode_cells']} | "
        f"Ant={pnr_info['antenna_violations']} | DRT={pnr_info['openroad_drt_drvs']} | DRC={drc_total} | LVS={lvs_status}\n"
        f"Multi-Rate RCX STA (250M Data / 125M CDR / 62.5M PLL): TT setup={tt_s:+.3f} ns | SS(100°C/1.60V) setup={ss_s:+.3f} ns | FF(-40°C/1.95V) hold={ff_h:+.3f} ns"
    )
    ax.set_title(
        f"SKY130A Lean Unified Digital Top Macro — {block.name}\n{subtitle}",
        fontsize=9.8,
        fontweight="bold",
        pad=10,
    )

    leg1 = ax.legend(
        handles=layer_handles, loc="upper left", bbox_to_anchor=(1.015, 1.00),
        frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=7.2, title="Layers", title_fontsize=8,
    )
    ax.add_artist(leg1)
    ax.legend(
        handles=group_handles, loc="lower left", bbox_to_anchor=(1.015, 0.00),
        frameon=True, facecolor="white", edgecolor="#cbd5e1", fontsize=7.0, title="Cardinal Pin Groups", title_fontsize=8,
    )

    fig.tight_layout()
    fig.savefig(png_path, dpi=180, facecolor="white")
    plt.close(fig)


def collect_v2_baseline() -> dict[str, Any]:
    if not VARIANT_V2_SUMMARY.exists():
        return {}
    rows = json.loads(VARIANT_V2_SUMMARY.read_text())
    total_die = total_core = total_design = 0.0
    total_std = total_wl = total_decap_cells = total_diodes = 0
    total_decap_ff = 0.0
    per_block: list[dict[str, Any]] = []
    for r in rows:
        b = r["block"]
        p = r["pnr"]
        total_die += p["die_area_um2"]
        total_core += p["core_w_um"] * p["core_h_um"]
        total_design += p["design_area_um2"]
        total_std += p["std_cells"]
        bdir = RESULTS_V2_BASE / b
        wl_um = 0
        for cand in sorted(bdir.glob("02c_openroad_eco_p*.log"), reverse=True) + [bdir / "02_openroad_pnr.log"]:
            if cand.exists():
                wl = parse_wirelength_from_log(cand.read_text())
                if wl["total_um"] > 0:
                    wl_um = wl["total_um"]
                    break
        total_wl += wl_um
        def_path = REPO / r["artifacts"]["def"]
        cs = count_cells_in_def(def_path) if def_path.exists() else {}
        dc = cs.get("decap_cells_total", 0)
        dff = cs.get("decap_cap_ff", 0.0)
        dd = cs.get("diode_cells", 0)
        total_decap_cells += dc
        total_decap_ff += dff
        total_diodes += dd
        per_block.append(
            {
                "block": b,
                "die_w_um": p["die_w_um"],
                "die_h_um": p["die_h_um"],
                "die_area_um2": p["die_area_um2"],
                "std_cells": p["std_cells"],
                "utilization_pct": p["utilization_pct"],
                "wirelength_um": wl_um,
                "decap_cells": dc,
                "decap_cap_pf": round(dff / 1000.0, 3),
                "diode_cells": dd,
                "ss_setup_wns_ns": r["sta_250mhz"]["ss_100C_1v60"]["setup_wns_ns"],
                "ff_hold_wns_ns": r["sta_250mhz"]["ff_n40C_1v95"]["hold_wns_ns"],
            }
        )
    return {
        "per_block": per_block,
        "sum_die_area_um2": round(total_die, 3),
        "sum_core_area_um2": round(total_core, 3),
        "sum_design_area_um2": round(total_design, 1),
        "weighted_utilization_pct": round(100.0 * total_design / max(total_core, 1.0), 1),
        "sum_std_cells": total_std,
        "sum_wirelength_um": total_wl,
        "sum_decap_cells": total_decap_cells,
        "sum_decap_cap_pf": round(total_decap_ff / 1000.0, 3),
        "sum_diode_cells": total_diodes,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Lean Unified serdes_digital_top_v3 P&R & Signoff Flow")
    ap.add_argument("--die-w", type=float, default=338.10, help="Target die width in um (default: 338.10)")
    ap.add_argument("--die-h", type=float, default=307.36, help="Target die height in um (default: 307.36)")
    ap.add_argument("--place-density", type=float, default=0.70, help="Global placement density (default: 0.70)")
    ap.add_argument("--setup-margin", type=float, default=0.35, help="Pre-route setup repair margin ns (default: 0.35)")
    ap.add_argument("--hold-margin", type=float, default=0.08, help="Pre-route hold repair margin ns (default: 0.08)")
    ap.add_argument("--resume-eco", action="store_true", help="Resume ECO/STA/DRC/LVS/PNG from existing Pass-0 DEF")
    args = ap.parse_args()

    t0 = time.time()
    block = build_v3_block_spec(
        die_w=args.die_w,
        die_h=args.die_h,
        place_density=args.place_density,
        setup_margin_ns=args.setup_margin,
        hold_margin_ns=args.hold_margin,
    )
    pin_groups = build_pin_groups()

    work = RESULTS_BASE / block.name
    work.mkdir(parents=True, exist_ok=True)
    variant_dir = VARIANT_BASE / block.name
    variant_dir.mkdir(parents=True, exist_ok=True)

    synth_lib = build_v3_synth_lib(
        base.LIB_SS,
        RESULTS_BASE / "_work/sky130_fd_sc_hd__ss_v31_synth.lib",
    )

    print(
        f"[{block.name}] Die target: {block.die_area[2]:.2f}x{block.die_area[3]:.2f} um "
        f"({block.die_area[2]*block.die_area[3]:.0f} um^2), "
        f"pins={sum(len(g.pins) for g in pin_groups)}",
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
        print(f"[{block.name}] 1/6 Reusing intact Yosys netlist ({synth_info['synth_cells']} cells, {synth_info['synth_area_um2']:.1f} um^2)...", flush=True)
    else:
        print(f"[{block.name}] 1/6 Yosys per-subsystem synthesis (250M data / 125M CDR / 62.5M PLL)...", flush=True)
        synth_v, synth_info = run_v3_yosys(block, work, synth_lib)
        print(
            f"[{block.name}]   synth_cells={synth_info['synth_cells']} "
            f"synth_area={synth_info['synth_area_um2']:.1f} um^2",
            flush=True,
        )
        for mod, st in synth_info["per_subsystem"].items():
            print(f"[{block.name}]     - {mod:20s}: {st['cells']:5d} cells, {st['area_um2']:8.1f} um^2", flush=True)

    sdc_path = work / f"{block.name}.sdc"
    write_v3_sdc(block, sdc_path, post_route=False)

    print(f"[{block.name}] 2/6 OpenROAD P&R + Cardinal Pins + Decap + Antenna + ECO (1 thread)...", flush=True)
    pnr_info = run_v3_openroad_pnr(block, pin_groups, work, synth_v, sdc_path, resume_eco=args.resume_eco)
    na = pnr_info["netlist_audit"]
    print(
        f"[{block.name}]   Die={pnr_info['die_w_um']:.2f}x{pnr_info['die_h_um']:.2f} um "
        f"({pnr_info['die_area_um2']:.0f} um^2) | Util={pnr_info['utilization_pct']:.1f}% | "
        f"Std={pnr_info['std_cells']} | Decap={pnr_info['cell_stats']['decap_cells_total']} "
        f"({pnr_info['cell_stats']['decap_cap_pf']:.2f} pF) | Diodes={pnr_info['cell_stats']['diode_cells']} | "
        f"Ant={pnr_info['antenna_violations']} | DRT={pnr_info['openroad_drt_drvs']} | "
        f"WL={pnr_info['wirelength']['total_um']} um | PinRegionViols={pnr_info['pin_check']['region_violations']}\n"
        f"[{block.name}]   NetlistAudit: hold_total={na['hold_buffers_total']} (hold_clkbuf_16={na['hold_clkbuf_16']}, "
        f"breakdown={na['hold_breakdown']}) | dly={na['dly_total']} | compound={na['compound_cells']}",
        flush=True,
    )

    print(f"[{block.name}] 3/6 3-Corner Post-Route OpenRCX STA (all 6 clocks)...", flush=True)
    sta_info = run_v3_sta_3corner(block, work, pnr_info)
    for cname, s in sta_info.items():
        print(
            f"[{block.name}]   {cname}: setup_wns={s['setup_wns_ns']:+.4f} ns (met={s['setup_met']}), "
            f"hold_wns={s['hold_wns_ns']:+.4f} ns (met={s['hold_met']})",
            flush=True,
        )
        for clk_n, cs_clk in s["per_clock"].items():
            sw = cs_clk["setup_wns_ns"]
            hw = cs_clk["hold_wns_ns"]
            sw_s = f"{sw:+.4f}" if sw is not None else "n/a"
            hw_s = f"{hw:+.4f}" if hw is not None else "n/a"
            print(f"[{block.name}]     {clk_n:14s}: setup={sw_s} ns, hold={hw_s} ns", flush=True)

    print(f"[{block.name}] 4/6 Magic DEF->MAG/GDS + Full-Rule DRC + LVS extraction...", flush=True)
    magic_info = run_v3_magic(block, work, Path(pnr_info["routed_def"]))
    print(f"[{block.name}]   Magic full DRC = {magic_info['magic_drc_total']}", flush=True)

    print(f"[{block.name}] 5/6 Netgen LVS...", flush=True)
    lvs_info = base.run_netgen_lvs(block, work, Path(magic_info["lvs_spice_path"]), Path(pnr_info["routed_pg_v"]))
    print(f"[{block.name}]   Netgen LVS = {lvs_info['lvs_status']}", flush=True)

    print(f"[{block.name}] 6/6 Rendering crisp white-background layout PNG...", flush=True)
    png_work = work / f"{block.name}.png"
    render_v3_png(
        block,
        pin_groups,
        Path(magic_info["mag_path"]),
        png_work,
        pnr_info,
        sta_info,
        magic_info["magic_drc_total"],
        lvs_info["lvs_status"],
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

    baseline = collect_v2_baseline()
    elapsed = round(time.time() - t0, 1)
    summary = {
        "block": block.name,
        "variant": "hd_pnr_v3_unified",
        "params": block.params,
        "rtl_files": block.rtl_files,
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
        "sta_3corner": sta_info,
        "magic_drc_total": magic_info["magic_drc_total"],
        "netgen_lvs": lvs_info["lvs_status"],
        "lvs_match": lvs_info["lvs_match"],
        "v2_separate_baseline": baseline,
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
    print(f"[{block.name}] COMPLETE in {elapsed}s -> {variant_dir / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
