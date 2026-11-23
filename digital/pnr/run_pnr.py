#!/usr/bin/env python3
"""Automated SKY130A Digital RTL-to-GDS/MAG P&R, 3-Corner STA, Magic DRC & Netgen LVS Flow.

Runs single-threaded OpenROAD 2.0 + Yosys 0.38 + Magic 8.3 + Netgen LVS on
SKY130A ``sky130_fd_sc_hd`` standard cells.

All temporary work files, logs, .ext, .spef, and Tcl scripts are placed under
``results/digital/pnr/<block>/``; only clean signoff deliverables (.def, .gds,
.v, _pg.v, .png, summary.json) are written to
``digital/pnr/variants/hd_pnr/<block>/``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Patch, Rectangle

REPO = Path(__file__).resolve().parents[2]
PDK_ROOT = Path("/home/host/.volare")
PDK = PDK_ROOT / "sky130A"
SC_HD = PDK / "libs.ref/sky130_fd_sc_hd"
OL_HD = PDK / "libs.tech/openlane/sky130_fd_sc_hd"
OL_TECH = PDK / "libs.tech/openlane"

YOSYS = Path("/opt/eda_pnr/envs/pnr/bin/yosys")
OPENROAD = Path("/opt/eda_pnr/envs/pnr/bin/openroad")
MAGIC = Path("/home/host/.local/bin/magic")
MAGIC_RC = PDK / "libs.tech/magic/sky130A.magicrc"

NGC = Path.home() / ".local/eda/netgen/usr/lib/netgen"
NETGENEXEC = NGC / "tcl/netgenexec"
NETGEN_TCL = NGC / "tcl/netgen.tcl"
NETGEN_SETUP = PDK / "libs.tech/netgen/sky130A_setup.tcl"

TLEF_NOM = SC_HD / "techlef/sky130_fd_sc_hd__nom.tlef"
SC_LEF = SC_HD / "lef/sky130_fd_sc_hd.lef"
SC_GDS = SC_HD / "gds/sky130_fd_sc_hd.gds"
SC_MAG_DIR = SC_HD / "mag"
SC_SPICE = SC_HD / "spice/sky130_fd_sc_hd.spice"

LIB_TT = SC_HD / "lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
LIB_SS = SC_HD / "lib/sky130_fd_sc_hd__ss_100C_1v60.lib"
LIB_FF = SC_HD / "lib/sky130_fd_sc_hd__ff_n40C_1v95.lib"

RCX_NOM = OL_TECH / "rules.openrcx.sky130A.nom.magic"
RCX_MAX = OL_TECH / "rules.openrcx.sky130A.max.magic"
RCX_MIN = OL_TECH / "rules.openrcx.sky130A.min.magic"

DRC_EXCLUDE_FILE = OL_HD / "drc_exclude.cells"

RESULTS_BASE = REPO / "results/digital/pnr"
VARIANT_BASE = REPO / "digital/pnr/variants/hd_pnr"
RESULTS_BASE_V2 = REPO / "results/digital/pnr_v2"
VARIANT_BASE_V2 = REPO / "digital/pnr/variants/hd_pnr_v2"


@dataclass
class ClockSpec:
    name: str
    port: str
    period_ns: float = 4.0
    inputs: list[str] = field(default_factory=list)
    fall_inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    fall_outputs: list[str] = field(default_factory=list)


@dataclass
class BlockSpec:
    name: str
    rtl_files: list[str]
    clocks: list[ClockSpec]
    reset_ports: list[str]
    async_input_ports: list[str] = field(default_factory=list)
    params: dict[str, int] = field(default_factory=dict)
    utilization: float = 45.0
    aspect_ratio: float = 0.5
    core_space: float = 4.0
    # Optional explicit die_area/core_area (x0, y0, x1, y1) in um for tiny macros
    die_area: tuple[float, float, float, float] | None = None
    core_area: tuple[float, float, float, float] | None = None
    place_density: float = 0.62
    pdn_v_pitch: float = 24.0
    pdn_v_offset: float = 6.0
    pdn_h_pitch: float = 24.0
    pdn_h_offset: float = 6.0
    use_met5_pdn: bool = True
    abc_target_ps: int = 2800
    setup_margin_ns: float = 0.20
    hold_margin_ns: float = 0.08
    output_load_pf: float = 0.020
    cts_sink_clustering: bool = True


BLOCKS: dict[str, BlockSpec] = {
    "tx_ingress_control": BlockSpec(
        name="tx_ingress_control",
        rtl_files=[
            "digital/tx/rtl/tx_ingress_control.sv",
        ],
        clocks=[
            ClockSpec(
                name="word_clk",
                port="word_clk",
                period_ns=4.0,
                inputs=["enable", "clock_good"],
                fall_inputs=["in_valid", "in_data*"],
                outputs=["word_ready", "capture_data*", "capture_valid", "b_valid"],
                fall_outputs=["a_valid"],
            )
        ],
        reset_ports=["rst_n"],
        die_area=(0.0, 0.0, 46.0, 32.0),
        core_area=(4.6, 5.44, 41.4, 27.2),
        place_density=0.55,
        pdn_v_pitch=18.0,
        pdn_v_offset=7.0,
        pdn_h_pitch=16.0,
        pdn_h_offset=5.0,
        use_met5_pdn=True,
        abc_target_ps=2000,
        setup_margin_ns=0.15,
        hold_margin_ns=0.05,
        output_load_pf=0.015,
        cts_sink_clustering=False,
    ),
    "pll_control_top": BlockSpec(
        name="pll_control_top",
        rtl_files=[
            "digital/common/rtl/mon_sync.sv",
            "digital/common/rtl/mon_persist.sv",
            "digital/pll/rtl/pll_startup_supervisor.sv",
            "digital/pll/rtl/pll_coarse_ctrl.sv",
            "digital/pll/rtl/pll_lock_detect.sv",
            "digital/pll/rtl/pll_control_top.sv",
        ],
        clocks=[
            ClockSpec(
                name="ref_clk",
                port="ref_clk",
                period_ns=4.0,
                inputs=[
                    "enable",
                    "start",
                    "tclass*",
                    "lo_run*",
                    "hi_run*",
                    "stop_code*",
                    "stop_sel*",
                ],
                outputs=[
                    "precharge_en",
                    "pfd_rst_b",
                    "cp_en",
                    "locked",
                    "busy",
                    "fault",
                    "state_id*",
                    "fault_code*",
                    "vco_code*",
                    "lo_code*",
                    "hi_code*",
                    "coarse_busy",
                    "coarse_done",
                    "fast_end",
                    "slow_end",
                    "switches*",
                ],
            )
        ],
        reset_ports=["rst_n"],
        async_input_ports=[
            "abort_async",
            "bias_ready_async",
            "pre_ref_ready_async",
            "hi_async",
            "lo_async",
            "pw_late_async",
        ],
        params={"CODE_BITS": 5},
        utilization=40.0,
        aspect_ratio=0.45,
        core_space=5.0,
        place_density=0.70,
        pdn_v_pitch=32.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=32.0,
        pdn_h_offset=8.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=0.15,
        hold_margin_ns=0.08,
    ),
    "rx_cdr_loop": BlockSpec(
        name="rx_cdr_loop",
        rtl_files=[
            "digital/rx/rtl/bbpd_window_vote.sv",
            "digital/rx/rtl/cdr_phase_frequency.sv",
            "digital/rx/rtl/pi_step_commutator.sv",
            "digital/rx/rtl/rx_cdr_loop.sv",
        ],
        clocks=[
            ClockSpec(
                name="ctrl_clk",
                port="ctrl_clk",
                period_ns=4.0,
                inputs=[
                    "enable",
                    "bundle_valid",
                    "previous_data",
                    "data_samples*",
                    "edge_samples*",
                ],
                outputs=[
                    "phase_code*",
                    "select_a*",
                    "select_b*",
                    "fine_b*",
                    "locked",
                    "holdover",
                    "range_limited",
                    "phase_applied",
                    "frequency_q*",
                    "phase_debt_q*",
                ],
            )
        ],
        reset_ports=["rst_n"],
        utilization=42.0,
        aspect_ratio=0.45,
        core_space=5.0,
        place_density=0.70,
        pdn_v_pitch=36.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=36.0,
        pdn_h_offset=8.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=0.15,
        hold_margin_ns=0.08,
    ),
    "rx_word_host_path": BlockSpec(
        name="rx_word_host_path",
        rtl_files=[
            "digital/rx/rtl/rx_word_map.sv",
            "digital/rx/rtl/rx_word_align16.sv",
            "digital/rx/rtl/rx_async_word_fifo.sv",
            "digital/rx/rtl/rx_word_host_path.sv",
        ],
        clocks=[
            ClockSpec(
                name="word_clk",
                port="word_clk",
                period_ns=4.0,
                inputs=["phys*", "training_enable"],
                outputs=["word_online", "aligned", "offset*"],
            ),
            ClockSpec(
                name="host_clk",
                port="host_clk",
                period_ns=4.0,
                inputs=["host_ready"],
                outputs=["host_data*", "host_valid", "host_online", "host_error"],
            ),
        ],
        reset_ports=["arst_n"],
        utilization=40.0,
        aspect_ratio=0.45,
        core_space=5.0,
        place_density=0.70,
        pdn_v_pitch=36.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=36.0,
        pdn_h_offset=8.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=0.15,
        hold_margin_ns=0.08,
    ),
}

BLOCKS_V2: dict[str, BlockSpec] = {
    "tx_ingress_control": BlockSpec(
        name="tx_ingress_control",
        rtl_files=[
            "digital/pnr/rtl_v2/tx_ingress_control.sv",
        ],
        clocks=[
            ClockSpec(
                name="word_clk",
                port="word_clk",
                period_ns=4.0,
                inputs=["enable", "clock_good", "in_valid", "in_data*"],
                outputs=["word_ready", "capture_data*", "capture_valid", "a_valid", "b_valid"],
            )
        ],
        reset_ports=["rst_n"],
        die_area=(0.0, 0.0, 72.0, 48.0),
        core_area=(4.6, 5.44, 67.16, 40.80),
        place_density=0.58,
        pdn_v_pitch=24.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=20.0,
        pdn_h_offset=6.0,
        use_met5_pdn=True,
        abc_target_ps=2200,
        setup_margin_ns=0.20,
        hold_margin_ns=0.05,
        output_load_pf=0.015,
        cts_sink_clustering=False,
    ),
    "pll_control_top": BlockSpec(
        name="pll_control_top",
        rtl_files=[
            "digital/pnr/rtl_v2/mon_sync.sv",
            "digital/pnr/rtl_v2/mon_persist.sv",
            "digital/pnr/rtl_v2/pll_startup_supervisor.sv",
            "digital/pnr/rtl_v2/pll_coarse_ctrl.sv",
            "digital/pnr/rtl_v2/pll_lock_detect.sv",
            "digital/pnr/rtl_v2/pll_control_top.sv",
        ],
        clocks=[
            ClockSpec(
                name="ref_clk",
                port="ref_clk",
                period_ns=4.0,
                inputs=[
                    "enable",
                    "start",
                    "tclass*",
                    "lo_run*",
                    "hi_run*",
                    "stop_code*",
                    "stop_sel*",
                ],
                outputs=[
                    "precharge_en",
                    "pfd_rst_b",
                    "cp_en",
                    "locked",
                    "busy",
                    "fault",
                    "state_id*",
                    "fault_code*",
                    "vco_code*",
                    "lo_code*",
                    "hi_code*",
                    "coarse_busy",
                    "coarse_done",
                    "fast_end",
                    "slow_end",
                    "switches*",
                ],
            )
        ],
        reset_ports=["rst_n"],
        async_input_ports=[
            "abort_async",
            "bias_ready_async",
            "pre_ref_ready_async",
            "hi_async",
            "lo_async",
            "pw_late_async",
        ],
        params={"CODE_BITS": 5},
        utilization=46.0,
        aspect_ratio=0.80,
        core_space=5.0,
        place_density=0.72,
        pdn_v_pitch=32.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=32.0,
        pdn_h_offset=8.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=0.50,
        hold_margin_ns=0.05,
    ),
    "rx_cdr_loop": BlockSpec(
        name="rx_cdr_loop",
        rtl_files=[
            "digital/pnr/rtl_v2/bbpd_window_vote.sv",
            "digital/pnr/rtl_v2/cdr_phase_frequency.sv",
            "digital/pnr/rtl_v2/pi_step_commutator.sv",
            "digital/pnr/rtl_v2/rx_cdr_loop.sv",
        ],
        clocks=[
            ClockSpec(
                name="ctrl_clk",
                port="ctrl_clk",
                period_ns=4.0,
                inputs=[
                    "enable",
                    "bundle_valid",
                    "previous_data",
                    "data_samples*",
                    "edge_samples*",
                ],
                outputs=[
                    "phase_code*",
                    "select_a*",
                    "select_b*",
                    "fine_b*",
                    "locked",
                    "holdover",
                    "range_limited",
                    "phase_applied",
                    "frequency_q*",
                    "phase_debt_q*",
                ],
            )
        ],
        reset_ports=["rst_n"],
        utilization=46.0,
        aspect_ratio=0.80,
        core_space=5.0,
        place_density=0.72,
        pdn_v_pitch=36.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=36.0,
        pdn_h_offset=8.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=0.50,
        hold_margin_ns=0.06,
    ),
    "rx_word_host_path": BlockSpec(
        name="rx_word_host_path",
        rtl_files=[
            "digital/pnr/rtl_v2/rx_word_map.sv",
            "digital/pnr/rtl_v2/rx_word_align16.sv",
            "digital/pnr/rtl_v2/rx_async_word_fifo.sv",
            "digital/pnr/rtl_v2/rx_word_host_path.sv",
        ],
        clocks=[
            ClockSpec(
                name="word_clk",
                port="word_clk",
                period_ns=4.0,
                inputs=["phys*", "training_enable"],
                outputs=["word_online", "aligned", "offset*"],
            ),
            ClockSpec(
                name="host_clk",
                port="host_clk",
                period_ns=4.0,
                inputs=["host_ready"],
                outputs=["host_data*", "host_valid", "host_online", "host_error"],
            ),
        ],
        reset_ports=["arst_n"],
        utilization=46.0,
        aspect_ratio=0.80,
        core_space=5.0,
        place_density=0.72,
        pdn_v_pitch=36.0,
        pdn_v_offset=8.0,
        pdn_h_pitch=36.0,
        pdn_h_offset=8.0,
        use_met5_pdn=True,
        abc_target_ps=1000,
        setup_margin_ns=0.50,
        hold_margin_ns=0.18,
    ),
}


def run_cmd(
    argv: list[str],
    cwd: Path,
    log_path: Path,
    timeout: int = 300,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env["PDK_ROOT"] = str(PDK_ROOT)
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        argv,
        cwd=cwd,
        env=merged_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    combined = proc.stdout + ("\n--- STDERR ---\n" + proc.stderr if proc.stderr else "")
    log_path.write_text(combined)
    if check and proc.returncode != 0:
        tail = "\n".join(combined.splitlines()[-60:])
        raise RuntimeError(f"Command failed (rc={proc.returncode}): {' '.join(argv)}\nSee {log_path}\n{tail}")
    return proc


def load_excluded_cells() -> set[str]:
    excluded: set[str] = set()
    if DRC_EXCLUDE_FILE.exists():
        for line in DRC_EXCLUDE_FILE.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#"):
                excluded.add(s)
    return excluded


SLOW_SS_CELL_TOKENS = (
    "__nor3",
    "__nor4",
    "__or3",
    "__or4",
    "__nand4",
    "__and4",
    "__o211",
    "__o221",
    "__o31",
    "__o32",
    "__o41",
    "__a211",
    "__a221",
    "__a222",
    "__a31",
    "__a32",
    "__a41",
    "__mux4",
    "__fa_",
    "__ha_",
    "__maj3",
)


def should_exclude_for_synth(cell_name: str, drc_exclude: set[str], fast_ss: bool = False) -> bool:
    if cell_name in drc_exclude:
        return True
    if cell_name.endswith("_0"):
        return True
    bad_tokens = (
        "__lpflow_",
        "__sdf",
        "__sedf",
        "__sdlclkp",
        "__dly",
        "__clkdly",
        "__clkbuf_",
        "__clkinv",
        "__decap_",
        "__fill_",
        "__tap",
        "__diode_",
        "__probe",
        "__ebuf",
        "__macro_sparecell",
        "__dlx",
        "__dlr",
        "__dls",
        "__dlb",
        "__edf",
    )
    if any(tok in cell_name for tok in bad_tokens):
        return True
    if fast_ss and any(tok in cell_name for tok in SLOW_SS_CELL_TOKENS):
        return True
    return False


def build_filtered_synth_lib(src_lib: Path, dst_lib: Path, fast_ss: bool = False) -> Path:
    """Create a Liberty copy with DRC-excluded, special, and weak _1 cells removed for Yosys.

    A ``*_1`` cell is excluded only when a ``*_2`` variant exists in the library
    (matching SKY130 OpenLane ``no_synth.cells`` practice while retaining
    unique ``_1`` cells such as ``dfrtn_1``, ``dfstp_1``, and ``conb_1``).
    When ``fast_ss=True``, also removes 3/4-PMOS-stack cells that take >1.5 ns at SS 100C/1.60V.
    """
    dst_lib.parent.mkdir(parents=True, exist_ok=True)
    drc_exclude = load_excluded_cells()
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
            if m and (should_exclude_for_synth(m.group(1), drc_exclude, fast_ss=fast_ss) or m.group(1) in weak_one):
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


def write_sdc(block: BlockSpec, sdc_path: Path, post_route: bool = False) -> None:
    lines: list[str] = []
    for clk in block.clocks:
        half = clk.period_ns / 2.0
        lines.append(
            f"create_clock -name {clk.name} -period {clk.period_ns:.4g} "
            f"-waveform {{0 {half:.4g}}} [get_ports {clk.port}]"
        )
        unc_s = 0.05 if block.name == "tx_ingress_control" else 0.10
        lines.append(f"set_clock_uncertainty -setup {unc_s:.2f} [get_clocks {clk.name}]")
        lines.append(f"set_clock_uncertainty -hold 0.05 [get_clocks {clk.name}]")
        if post_route:
            lines.append(f"set_propagated_clock [get_clocks {clk.name}]")
        else:
            lines.append(f"set_clock_transition 0.10 [get_clocks {clk.name}]")

    if len(block.clocks) > 1:
        groups = " ".join(f"-group {{{c.name}}}" for c in block.clocks)
        lines.append(f"set_clock_groups -asynchronous {groups}")

    lines.append("set_max_fanout 16 [current_design]")
    lines.append("set_max_transition 0.75 [current_design]")
    clk_ports = " ".join(c.port for c in block.clocks)
    data_in_ports: list[str] = []
    for clk in block.clocks:
        data_in_ports.extend(clk.inputs)
        data_in_ports.extend(clk.fall_inputs)
    data_in_ports.extend(block.reset_ports)
    data_in_ports.extend(block.async_input_ports)
    if data_in_ports:
        lines.append(
            f"set_driving_cell -lib_cell sky130_fd_sc_hd__buf_4 -pin X "
            f"[get_ports {{{' '.join(data_in_ports)}}}]"
        )
    lines.append(f"set_input_transition 0.08 [get_ports {{{clk_ports}}}]")
    lines.append(f"set_load {block.output_load_pf:.4g} [all_outputs]")

    for clk in block.clocks:
        if clk.inputs:
            in_str = " ".join(clk.inputs)
            lines.append(f"set_input_delay -clock {clk.name} -max 0.50 [get_ports {{{in_str}}}]")
            lines.append(f"set_input_delay -clock {clk.name} -min 0.10 [get_ports {{{in_str}}}]")
        if clk.fall_inputs:
            fin_str = " ".join(clk.fall_inputs)
            lines.append(f"set_input_delay -clock {clk.name} -clock_fall -max 0.25 [get_ports {{{fin_str}}}]")
            lines.append(f"set_input_delay -clock {clk.name} -clock_fall -min 0.05 [get_ports {{{fin_str}}}]")
        if clk.outputs:
            out_str = " ".join(clk.outputs)
            lines.append(f"set_output_delay -clock {clk.name} -max 0.50 [get_ports {{{out_str}}}]")
            lines.append(f"set_output_delay -clock {clk.name} -min 0.00 [get_ports {{{out_str}}}]")
        if clk.fall_outputs:
            fout_str = " ".join(clk.fall_outputs)
            lines.append(f"set_output_delay -clock {clk.name} -clock_fall -max 0.50 [get_ports {{{fout_str}}}]")
            lines.append(f"set_output_delay -clock {clk.name} -clock_fall -min 0.00 [get_ports {{{fout_str}}}]")

    if block.reset_ports:
        rst_str = " ".join(block.reset_ports)
        lines.append(f"set_false_path -from [get_ports {{{rst_str}}}]")
    if block.async_input_ports:
        async_str = " ".join(block.async_input_ports)
        lines.append(f"set_false_path -from [get_ports {{{async_str}}}]")

    sdc_path.write_text("\n".join(lines) + "\n")


def run_yosys(block: BlockSpec, work: Path, synth_lib: Path, v2: bool = False) -> tuple[Path, dict[str, Any]]:
    synth_v = work / f"{block.name}_synth.v"
    ys_path = work / "synth.ys"
    rtl_abs = [str((REPO / f).resolve()) for f in block.rtl_files]

    cmds = [
        f"read_liberty -lib {synth_lib}",
        f"read_verilog -sv {' '.join(rtl_abs)}",
    ]
    for pname, pval in block.params.items():
        cmds.append(f"chparam -set {pname} {pval} {block.name}")
    insbuf_cell = "sky130_fd_sc_hd__buf_8" if v2 else "sky130_fd_sc_hd__buf_2"
    if v2:
        # Preserve (* keep *) replicated fanout-splitting registers by skipping opt_merge on kept cells
        cmds += [
            f"hierarchy -check -top {block.name}",
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
            f"abc -D {block.abc_target_ps} -liberty {synth_lib}",
            "splitnets",
            "opt_clean -purge",
            "hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO",
            f"insbuf -buf {insbuf_cell} A X",
            "rename -hide",
            "opt_clean -purge",
            "check -assert",
            f"stat -liberty {synth_lib}",
            f"write_verilog -noattr -noexpr -nohex -nodec {synth_v}",
        ]
    else:
        cmds += [
            f"hierarchy -check -top {block.name}",
            f"synth -top {block.name} -flatten",
            f"dfflibmap -liberty {synth_lib}",
            f"abc -D {block.abc_target_ps} -liberty {synth_lib}",
            "splitnets",
            "opt_clean -purge",
            "hilomap -hicell sky130_fd_sc_hd__conb_1 HI -locell sky130_fd_sc_hd__conb_1 LO",
            f"insbuf -buf {insbuf_cell} A X",
            "rename -hide",
            "opt_clean -purge",
            "check -assert",
            f"stat -liberty {synth_lib}",
            f"write_verilog -noattr -noexpr -nohex -nodec {synth_v}",
        ]
    ys_path.write_text("\n".join(cmds) + "\n")
    proc = run_cmd([str(YOSYS), "-s", str(ys_path)], work, work / "01_yosys.log", timeout=180)
    log = proc.stdout

    cells_m = re.search(r"Number of cells:\s+(\d+)", log)
    area_m = re.search(r"Chip area for module[^\n]*:\s+([0-9.]+)", log)
    return synth_v, {
        "synth_cells": int(cells_m.group(1)) if cells_m else None,
        "synth_area_um2": float(area_m.group(1)) if area_m else None,
    }


def openroad_dont_use_tcl(v2: bool = False) -> str:
    drc_exclude = sorted(load_excluded_cells())
    patterns = [
        "*_0",
        "sky130_fd_sc_hd__lpflow_*",
        "sky130_fd_sc_hd__sdf*",
        "sky130_fd_sc_hd__sedf*",
        "sky130_fd_sc_hd__sdlclkp*",
        "sky130_fd_sc_hd__probe*",
        "sky130_fd_sc_hd__ebuf*",
        "sky130_fd_sc_hd__clkdlybuf*",
        "sky130_fd_sc_hd__dly*",
        "sky130_fd_sc_hd__clkbuf_1",
        "sky130_fd_sc_hd__clkbuf_2",
        "sky130_fd_sc_hd__clkinv_1",
        "sky130_fd_sc_hd__clkinv_2",
    ] + drc_exclude
    if v2:
        # Prevent OpenROAD resizer from downsizing fast _2/_4 cells back to slow _1 or 4-stack cells
        patterns += [f"sky130_fd_sc_hd{tok}*" for tok in SLOW_SS_CELL_TOKENS]
        # Exclude weak _1 logic/FF/buf/inv cells where _2 exists (prevent buf_1 slew bombs on critical paths!)
        lib_text = LIB_SS.read_text()
        all_c = set(re.findall(r'cell\s*\(\s*"([^"]+)"\s*\)', lib_text))
        for c in sorted(all_c):
            if c.endswith("_1") and (c[:-2] + "_2") in all_c:
                if "__conb_1" not in c:
                    patterns.append(c)
    lines = ["set dont_use_list {"]
    for p in patterns:
        lines.append(f"  {p}")
    lines.append("}")
    lines.append("foreach pat $dont_use_list {")
    lines.append("  catch { set_dont_use $pat }")
    lines.append("}")
    return "\n".join(lines)


def run_openroad_pnr(block: BlockSpec, work: Path, synth_v: Path, sdc_path: Path, v2: bool = False) -> dict[str, Any]:
    routed_def = work / f"{block.name}.def"
    routed_v = work / f"{block.name}.v"
    routed_pg_v = work / f"{block.name}_pg.v"
    drc_rpt = work / "openroad_drt_drc.rpt"
    spef_nom = work / f"{block.name}_nom.spef"
    spef_max = work / f"{block.name}_max.spef"
    spef_min = work / f"{block.name}_min.spef"

    if block.die_area and block.core_area:
        da = " ".join(f"{v:.4g}" for v in block.die_area)
        ca = " ".join(f"{v:.4g}" for v in block.core_area)
        fp_cmd = f"initialize_floorplan -die_area {{{da}}} -core_area {{{ca}}} -site unithd"
    else:
        fp_cmd = (
            f"initialize_floorplan -utilization {block.utilization:.2f} "
            f"-aspect_ratio {block.aspect_ratio:.3f} "
            f"-core_space {block.core_space:.2f} -site unithd"
        )

    met5_block = ""
    if block.use_met5_pdn:
        met5_block = f"""
add_pdn_stripe -grid stdcell_grid -layer met5 -width 1.60 -pitch {block.pdn_h_pitch:.2f} -offset {block.pdn_h_offset:.2f}
add_pdn_connect -grid stdcell_grid -layers {{met4 met5}}
"""

    pnr_tcl = work / "pnr.tcl"
    cts_cluster_flag = "-sink_clustering_enable" if block.cts_sink_clustering else ""
    pdn_pin_layer = "met5" if block.use_met5_pdn else "met4"
    if v2:
        cts_buf_list = "{sky130_fd_sc_hd__clkbuf_16}"
        cts_extra = "-sink_clustering_size 14 -sink_clustering_max_diameter 50" if block.cts_sink_clustering else ""
        td_flag = "" if block.die_area else "-timing_driven "
        hold_max_buf = 300 if block.die_area else 80
        hold_allow_flag = "-allow_setup_violations " if block.die_area else ""
        pin_pre = "place_pins -hor_layers met3 -ver_layers met2 -random"
        pin_post = "" if block.die_area else "place_pins -hor_layers met3 -ver_layers met2"
        wire_rc_block = """
set_wire_rc -corner ss -signal -resistance 0.0014 -capacitance 0.00018
set_wire_rc -corner ss -clock  -resistance 0.0005 -capacitance 0.00015
set_wire_rc -corner ff -signal -resistance 0.0007 -capacitance 0.00009
set_wire_rc -corner ff -clock  -resistance 0.0003 -capacitance 0.00008
"""
        opt_flow = f"""
global_placement {td_flag}-density {block.place_density:.2f} -pad_left 1 -pad_right 1
{pin_post}
estimate_parasitics -placement
set_max_transition 0.55 [current_design]
repair_design -slew_margin 0 -cap_margin 0
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/HI
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/LO
detailed_placement
check_placement -verbose

clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_16 \\
  -buf_list {cts_buf_list} \\
  {cts_cluster_flag} {cts_extra}
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_clock_nets
detailed_placement

repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 1
detailed_placement
estimate_parasitics -placement
repair_timing -hold -slack_margin {block.hold_margin_ns:.3f} {hold_allow_flag}-max_buffer_percent {hold_max_buf}
detailed_placement

global_route -congestion_iterations 60 -allow_congestion
estimate_parasitics -global_routing
repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 1
repair_timing -hold -slack_margin {block.hold_margin_ns:.3f} {hold_allow_flag}-max_buffer_percent {hold_max_buf}
detailed_placement
check_placement -verbose
"""
    else:
        pin_pre = "place_pins -hor_layers met3 -ver_layers met2 -random"
        wire_rc_block = """
set_wire_rc -signal -layer met2
set_wire_rc -clock -layer met3
"""
        opt_flow = f"""
global_placement -density {block.place_density:.2f} -pad_left 1 -pad_right 1
estimate_parasitics -placement
repair_design -max_wire_length 800
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/HI
repair_tie_fanout -separation 0 sky130_fd_sc_hd__conb_1/LO
detailed_placement
check_placement -verbose

clock_tree_synthesis -root_buf sky130_fd_sc_hd__clkbuf_16 \\
  -buf_list {{sky130_fd_sc_hd__clkbuf_4 sky130_fd_sc_hd__clkbuf_8 sky130_fd_sc_hd__clkbuf_16}} \\
  {cts_cluster_flag}
set_propagated_clock [all_clocks]
estimate_parasitics -placement
repair_clock_nets
detailed_placement

repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 50
detailed_placement
estimate_parasitics -placement
repair_timing -setup -slack_margin {block.setup_margin_ns:.3f} -max_buffer_percent 50
repair_timing -hold -slack_margin {block.hold_margin_ns:.3f} -allow_setup_violations -max_buffer_percent 50
detailed_placement
check_placement -verbose
"""
    eco_post_route = ""
    pnr_tcl.write_text(
        f"""
read_lef {TLEF_NOM}
read_lef {SC_LEF}
define_corners ss ff
read_liberty -corner ss {LIB_SS}
read_liberty -corner ff {LIB_FF}
read_verilog {synth_v}
link_design {block.name}
read_sdc {sdc_path}

{openroad_dont_use_tcl(v2=v2)}

{fp_cmd}

make_tracks li1  -x_offset 0.23 -x_pitch 0.46 -y_offset 0.17 -y_pitch 0.34
make_tracks met1 -x_offset 0.17 -x_pitch 0.34 -y_offset 0.17 -y_pitch 0.34
make_tracks met2 -x_offset 0.23 -x_pitch 0.46 -y_offset 0.23 -y_pitch 0.46
make_tracks met3 -x_offset 0.34 -x_pitch 0.68 -y_offset 0.34 -y_pitch 0.68
make_tracks met4 -x_offset 0.46 -x_pitch 0.92 -y_offset 0.46 -y_pitch 0.92
make_tracks met5 -x_offset 1.70 -x_pitch 3.40 -y_offset 1.70 -y_pitch 3.40

{pin_pre}

tapcell -distance 14 \\
  -tapcell_master sky130_fd_sc_hd__tapvpwrvgnd_1 \\
  -endcap_master sky130_fd_sc_hd__decap_3

add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground
set_voltage_domain -name CORE -power VPWR -ground VGND
define_pdn_grid -name stdcell_grid -voltage_domains CORE -pins {{{pdn_pin_layer}}}
add_pdn_stripe -grid stdcell_grid -layer met1 -width 0.48 -followpins
add_pdn_stripe -grid stdcell_grid -layer met4 -width 1.60 -pitch {block.pdn_v_pitch:.2f} -offset {block.pdn_v_offset:.2f}
add_pdn_connect -grid stdcell_grid -layers {{met1 met4}}
{met5_block}
pdngen

{wire_rc_block}
set_routing_layers -signal met1-met5 -clock met1-met5

{opt_flow}

filler_placement {{sky130_fd_sc_hd__decap_12 sky130_fd_sc_hd__decap_8 sky130_fd_sc_hd__decap_6 sky130_fd_sc_hd__decap_4 sky130_fd_sc_hd__decap_3 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_1}}
add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground

global_route -congestion_iterations 60 -allow_congestion
set_propagated_clock [all_clocks]
detailed_route -output_drc {drc_rpt} -bottom_routing_layer met1 -top_routing_layer met5 -droute_end_iter 35 -verbose 1
{eco_post_route}
write_def {routed_def}
write_verilog {routed_v}
write_verilog -include_pwr_gnd -remove_cells {{sky130_fd_sc_hd__fill_1 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__tapvpwrvgnd_1}} {routed_pg_v}

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
set std_cnt 0
set phys_cnt 0
foreach inst [$block_db getInsts] {{
  set mname [[$inst getMaster] getName]
  if {{[string match "*__fill_*" $mname] || [string match "*__decap_*" $mname] || [string match "*__tap*" $mname]}} {{
    incr phys_cnt
  }} else {{
    incr std_cnt
  }}
}}
puts [format "DIE_UM: %.3f %.3f %.3f" $die_w $die_h [expr {{$die_w * $die_h}}]]
puts [format "CORE_UM: %.3f %.3f %.3f" $core_w $core_h [expr {{$core_w * $core_h}}]]
puts [format "INST_COUNTS: std=%d phys=%d total=%d" $std_cnt $phys_cnt [expr {{$std_cnt + $phys_cnt}}]]
"""
    )

    proc = run_cmd(
        [str(OPENROAD), "-threads", "1", "-no_init", "-exit", str(pnr_tcl)],
        work,
        work / "02_openroad_pnr.log",
        timeout=1200,
    )
    log = proc.stdout

    # Post-route OpenRCX ECO closure passes (up to 3 SPEF-driven passes; stops immediately once SS>=+0.02 & FF_hold>=+0.005!)
    if v2 and not block.die_area:
        sdc_eco = work / f"{block.name}_eco.sdc"
        write_sdc(block, sdc_eco, post_route=True)
        for eco_pass in (1, 2, 3):
            spef_eco_max = work / f"{block.name}_eco_max.spef"
            spef_eco_min = work / f"{block.name}_eco_min.spef"
            for tag, rcx_rule, sp_out in [("max", RCX_MAX, spef_eco_max), ("min", RCX_MIN, spef_eco_min)]:
                ext_tcl = work / f"eco_ext_{tag}.tcl"
                ext_tcl.write_text(
                    f"""read_lef {TLEF_NOM}
read_lef {SC_LEF}
read_def {routed_def}
define_process_corner -ext_model_index 0 eco_{tag}
extract_parasitics -ext_model_file {rcx_rule}
write_spef {sp_out}
exit
"""
                )
                run_cmd([str(OPENROAD), "-threads", "1", "-no_init", "-exit", str(ext_tcl)],
                        work, work / f"02b_eco_p{eco_pass}_ext_{tag}.log", timeout=180)

            gb = 0.20 if eco_pass == 1 else (0.10 if eco_pass == 2 else 0.05)
            eco_tcl = work / f"pnr_eco_p{eco_pass}.tcl"
            eco_tcl.write_text(
                f"""read_lef {TLEF_NOM}
read_lef {SC_LEF}
define_corners ss ff
read_liberty -corner ss {LIB_SS}
read_liberty -corner ff {LIB_FF}
read_def {routed_def}
read_sdc {sdc_eco}
{openroad_dont_use_tcl(v2=True)}

read_spef -corner ss {spef_eco_max}
read_spef -corner ff {spef_eco_min}

set init_wns [sta::worst_slack -corner ss -max]
set init_hold [sta::worst_slack -corner ff -min]
puts [format "ECO_P{eco_pass}_INIT: SS_WNS=%.4f FF_HOLD=%.4f" $init_wns $init_hold]
if {{{eco_pass} > 1 && $init_wns >= 0.02 && $init_hold >= 0.005}} {{
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

# SPEF-driven greedy replace_cell ECO directly on exact post-route max/min SPEF
# (avoids RSZ-0021 wire-load downsizing, adds ZERO extra buffers, preserves FF hold!)
set all_masters {{}}
foreach lib [$db_eco getLibs] {{
  foreach m [$lib getMasters] {{ dict set all_masters [$m getName] 1 }}
}}
proc _next_drv {{mname all_masters}} {{
  if {{[regexp {{^(sky130_fd_sc_hd__[a-z0-9]+)_([0-9]+)$}} $mname -> base drv]}} {{
    foreach d {{2 4 6 8 12 16}} {{
      if {{$d > $drv}} {{
        set cand "${{base}}_${{d}}"
        if {{[dict exists $all_masters $cand]}} {{ return $cand }}
      }}
    }}
  }}
  return ""
}}
set eco_swapped 0
set_clock_uncertainty -setup [expr {{0.10 + {gb}}}] [all_clocks]
for {{set iter 0}} {{$iter < 25}} {{incr iter}} {{
  set wns [sta::worst_slack -corner ss -max]
  if {{$wns >= 0.02}} {{ break }}
  set paths [find_timing_paths -corner ss -path_delay max -group_count 40 -endpoint_count 1 -slack_max 0.02]
  if {{[llength $paths] == 0}} {{ break }}
  set seen {{}}
  set improved 0
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
      if {{[string match "*clkbuf*" $mname] || [string match "*clkinv*" $mname]}} {{ continue }}
      set cand [_next_drv $mname $all_masters]
      if {{$cand eq ""}} {{ continue }}
      set old_wns [sta::worst_slack -corner ss -max]
      set old_tns [sta::total_negative_slack -corner ss -max]
      set old_hold [sta::worst_slack -corner ff -min]
      set hold_floor [expr {{$old_hold < 0.025 ? ($old_hold - 0.002) : 0.025}}]
      if {{[catch {{replace_cell $iname $cand}}]}} {{ continue }}
      set new_wns [sta::worst_slack -corner ss -max]
      set new_tns [sta::total_negative_slack -corner ss -max]
      set new_hold [sta::worst_slack -corner ff -min]
      if {{($new_wns > $old_wns + 0.001 || ($new_wns >= $old_wns - 0.001 && $new_tns > $old_tns + 0.005)) && $new_hold >= $hold_floor}} {{
        incr eco_swapped
        set improved 1
      }} else {{
        catch {{replace_cell $iname $mname}}
      }}
    }}
  }}
  puts [format "ECO_P{eco_pass}_ITER %d: swapped=%d SS_WNS_REAL=%.4f SS_TNS_GB=%.4f FF_HOLD=%.4f" $iter $eco_swapped [expr {{[sta::worst_slack -corner ss -max] + {gb}}}] [sta::total_negative_slack -corner ss -max] [sta::worst_slack -corner ff -min]]
  if {{!$improved}} {{ break }}
}}
set_clock_uncertainty -setup 0.10 [all_clocks]
set need_hold_fix [expr {{[sta::worst_slack -corner ff -min] < 0.015}}]
if {{$eco_swapped == 0 && !$need_hold_fix}} {{
  puts "ECO_P{eco_pass}_NO_CHANGES"
  exit 0
}}
if {{$need_hold_fix}} {{
  estimate_parasitics -placement
  repair_timing -hold -slack_margin 0.05 -max_buffer_percent 15
}}
detailed_placement
check_placement -verbose

filler_placement {{sky130_fd_sc_hd__decap_12 sky130_fd_sc_hd__decap_8 sky130_fd_sc_hd__decap_6 sky130_fd_sc_hd__decap_4 sky130_fd_sc_hd__decap_3 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_1}}
add_global_connection -net VPWR -inst_pattern {{.*}} -pin_pattern {{^VPWR$|^VPB$}} -power
add_global_connection -net VGND -inst_pattern {{.*}} -pin_pattern {{^VGND$|^VNB$}} -ground

global_route -congestion_iterations 60 -allow_congestion
set_propagated_clock [all_clocks]
detailed_route -output_drc {drc_rpt} -bottom_routing_layer met1 -top_routing_layer met5 -droute_end_iter 35 -verbose 1

write_def {routed_def}
write_verilog {routed_v}
write_verilog -include_pwr_gnd -remove_cells {{sky130_fd_sc_hd__fill_1 sky130_fd_sc_hd__fill_2 sky130_fd_sc_hd__fill_4 sky130_fd_sc_hd__fill_8 sky130_fd_sc_hd__tapvpwrvgnd_1}} {routed_pg_v}

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
set std_cnt 0
set phys_cnt 0
foreach inst [$block_db getInsts] {{
  set mname [[$inst getMaster] getName]
  if {{[string match "*__fill_*" $mname] || [string match "*__decap_*" $mname] || [string match "*__tap*" $mname]}} {{
    incr phys_cnt
  }} else {{
    incr std_cnt
  }}
}}
puts [format "DIE_UM: %.3f %.3f %.3f" $die_w $die_h [expr {{$die_w * $die_h}}]]
puts [format "CORE_UM: %.3f %.3f %.3f" $core_w $core_h [expr {{$core_w * $core_h}}]]
puts [format "INST_COUNTS: std=%d phys=%d total=%d" $std_cnt $phys_cnt [expr {{$std_cnt + $phys_cnt}}]]
"""
            )
            proc = run_cmd(
                [str(OPENROAD), "-threads", "1", "-no_init", "-exit", str(eco_tcl)],
                work,
                work / f"02c_openroad_eco_p{eco_pass}.log",
                timeout=1200,
            )
            if "=== METRICS_REPORT ===" in proc.stdout:
                log = proc.stdout
            if f"ECO_P{eco_pass}_SKIP_ALREADY_CLOSED" in proc.stdout or f"ECO_P{eco_pass}_NO_CHANGES" in proc.stdout:
                break

    die_m = re.search(r"DIE_UM:\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", log)
    core_m = re.search(r"CORE_UM:\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)", log)
    cnt_m = re.search(r"INST_COUNTS:\s+std=(\d+)\s+phys=(\d+)\s+total=(\d+)", log)
    util_m = re.search(r"Design area\s+([0-9.]+)\s+u\^2\s+([0-9.]+)%\s+utilization", log)

    drt_viols = 0
    if drc_rpt.exists():
        drt_viols = len(re.findall(r"^\s*violation type:", drc_rpt.read_text(), re.M))

    return {
        "die_w_um": float(die_m.group(1)) if die_m else None,
        "die_h_um": float(die_m.group(2)) if die_m else None,
        "die_area_um2": float(die_m.group(3)) if die_m else None,
        "core_w_um": float(core_m.group(1)) if core_m else None,
        "core_h_um": float(core_m.group(2)) if core_m else None,
        "std_cells": int(cnt_m.group(1)) if cnt_m else None,
        "phys_cells": int(cnt_m.group(2)) if cnt_m else None,
        "total_cells": int(cnt_m.group(3)) if cnt_m else None,
        "design_area_um2": float(util_m.group(1)) if util_m else None,
        "utilization_pct": float(util_m.group(2)) if util_m else None,
        "openroad_drt_drvs": drt_viols,
        "routed_def": str(routed_def),
        "routed_v": str(routed_v),
        "routed_pg_v": str(routed_pg_v),
        "spef_nom": str(spef_nom),
        "spef_max": str(spef_max),
        "spef_min": str(spef_min),
    }


def run_sta_3corner(block: BlockSpec, work: Path, pnr_info: dict[str, Any]) -> dict[str, Any]:
    sdc_post = work / f"{block.name}_postroute.sdc"
    write_sdc(block, sdc_post, post_route=True)

    corners = [
        ("tt_025C_1v80", LIB_TT, RCX_NOM, Path(pnr_info["spef_nom"])),
        ("ss_100C_1v60", LIB_SS, RCX_MAX, Path(pnr_info["spef_max"])),
        ("ff_n40C_1v95", LIB_FF, RCX_MIN, Path(pnr_info["spef_min"])),
    ]
    sta_results: dict[str, Any] = {}
    for cname, lib_path, rcx_rule, spef_path in corners:
        tcl = work / f"sta_{cname}.tcl"
        tcl.write_text(
            f"""
read_lef {TLEF_NOM}
read_lef {SC_LEF}
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
puts "=== SUMMARY ==="
puts "SETUP_WNS: [sta::worst_slack -max]"
puts "SETUP_TNS: [sta::total_negative_slack -max]"
puts "HOLD_WNS: [sta::worst_slack -min]"
puts "HOLD_TNS: [sta::total_negative_slack -min]"
report_check_types -max_slew -max_capacitance -max_fanout -violators
"""
        )
        proc = run_cmd(
            [str(OPENROAD), "-threads", "1", "-no_init", "-exit", str(tcl)],
            work,
            work / f"03_sta_{cname}.log",
            timeout=180,
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
        }
    return sta_results


def run_magic_drc_gds_ext(block: BlockSpec, work: Path, routed_def: Path) -> dict[str, Any]:
    mag_out = work / f"{block.name}.mag"
    gds_out = work / f"{block.name}.gds"
    lvs_spice = work / f"{block.name}_lvs.spice"

    # Clean stale .ext and .mag files so Magic read/extraction is fresh
    for old_ext in work.glob("*.ext"):
        old_ext.unlink()
    if mag_out.exists():
        mag_out.unlink()

    # Pass 1: DEF -> MAG + GDS + Full-rule Magic DRC (uses pre-verified PDK .mag views via magicrc addpath)
    tcl_drc = work / "magic_drc_gds.tcl"
    tcl_drc.write_text(
        f"""
drc off
lef read {TLEF_NOM}
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
    proc_drc = run_cmd(
        [str(MAGIC), "-noconsole", "-dnull", "-rcfile", str(MAGIC_RC), str(tcl_drc)],
        work,
        work / "04a_magic_drc_gds.log",
        timeout=180,
    )
    log_drc = proc_drc.stdout + proc_drc.stderr
    m = re.search(r"Total DRC errors found:\s*(\d+)", log_drc)
    drc_total = int(m.group(1)) if m else -1

    # Pass 2: Fast LVS netlist extraction (disable parasitic R/C extraction via extract no all)
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
    run_cmd(
        [str(MAGIC), "-noconsole", "-dnull", "-rcfile", str(MAGIC_RC), str(tcl_ext)],
        work,
        work / "04b_magic_ext_lvs.log",
        timeout=180,
    )
    if not gds_out.exists() or not lvs_spice.exists():
        raise RuntimeError(f"Magic did not produce GDS or LVS SPICE for {block.name}; see {work}")
    return {
        "magic_drc_total": drc_total,
        "mag_path": str(mag_out),
        "gds_path": str(gds_out),
        "lvs_spice_path": str(lvs_spice),
    }


def _prepare_pg_verilog_for_lvs(routed_pg_v: Path, out_v: Path) -> Path:
    """Explicitly bind unused HI/LO pins on sky130_fd_sc_hd__conb_1 to stub wires.

    OpenROAD ``write_verilog -include_pwr_gnd`` omits unconnected tie-cell pins,
    whereas Magic SPICE extraction emits all 6 subckt terminals (giving fanout 1
    on the unused pin). Binding each unused pin to a unique floating wire yields
    a 1:1 topological match in Netgen without altering the circuit.
    """
    text = routed_pg_v.read_text()
    counter = [0]
    extra_wires: list[str] = []

    def fix_conb(m: re.Match[str]) -> str:
        body = m.group(0)
        if ".HI(" not in body:
            w = f"_lvs_unused_hi_{counter[0]}"
            counter[0] += 1
            extra_wires.append(w)
            if "(.VGND" in body:
                body = body.replace("(.VGND", f"(.HI({w}),\n    .VGND", 1)
            else:
                body = body.replace("(", f"(.HI({w}),\n    ", 1)
        if ".LO(" not in body:
            w = f"_lvs_unused_lo_{counter[0]}"
            counter[0] += 1
            extra_wires.append(w)
            if "(.VGND" in body:
                body = body.replace("(.VGND", f"(.LO({w}),\n    .VGND", 1)
            else:
                body = body.replace("(", f"(.LO({w}),\n    ", 1)
        return body

    fixed = re.sub(r"sky130_fd_sc_hd__conb_1\s+\S+\s*\([^;]+\);", fix_conb, text)
    if extra_wires:
        wire_decl = "\n".join(f" wire {w};" for w in extra_wires) + "\n"
        fixed = fixed.replace(" sky130_fd_sc_hd__", wire_decl + " sky130_fd_sc_hd__", 1)
    out_v.write_text(fixed)
    return out_v


def run_netgen_lvs(block: BlockSpec, work: Path, lvs_spice: Path, routed_pg_v: Path) -> dict[str, Any]:
    out_log = work / "05_netgen_lvs.rpt"
    pg_lvs_v = _prepare_pg_verilog_for_lvs(routed_pg_v, work / f"{block.name}_pg_lvs.v")
    shim = work / "_netgen_local.tcl"
    shim.write_text(
        NETGEN_TCL.read_text().replace(
            "load /usr/lib/netgen/tcl/tclnetgen.so",
            f"load {NGC}/tcl/tclnetgen.so",
        )
    )
    run_tcl = work / "_netgen_run.tcl"
    run_tcl.write_text(
        f"""
set argv {{}}
set argc 0
source {shim}
set c1 [readnet spice {lvs_spice}]
set c2 [readnet spice {SC_SPICE}]
readnet verilog {pg_lvs_v} $c2
lvs [list $c1 {block.name}] [list $c2 {block.name}] {NETGEN_SETUP} {out_log}
quit
"""
    )
    proc = run_cmd(
        [str(NETGENEXEC), str(run_tcl)],
        work,
        work / "05_netgen_stdout.log",
        timeout=180,
        check=False,
    )
    rpt_text = out_log.read_text() if out_log.exists() else ""
    matched = (
        "Circuits match uniquely." in rpt_text
        and "Property errors were found." not in rpt_text
        and "Pin matching failed" not in rpt_text
        and "Netlists do not match" not in rpt_text
        and "(no matching pin)" not in rpt_text
    )
    return {
        "lvs_match": matched,
        "lvs_status": "MATCH" if matched else "MISMATCH",
        "netgen_rc": proc.returncode,
        "lvs_report": str(out_log),
    }


# ---------------------------------------------------------------------------
# Crisp white-background Magic layout renderer (parses hierarchical .mag + PDK cell .mag)
# ---------------------------------------------------------------------------
LAYER_STYLE: list[tuple[str, str, float]] = [
    ("nwell", "#fef3c7", 0.70),
    ("pdiff", "#fdba74", 0.85),
    ("ndiff", "#93c5fd", 0.85),
    ("psubdiff", "#a7f3d0", 0.80),
    ("nsubdiff", "#bae6fd", 0.80),
    ("poly", "#ea580c", 0.90),
    ("nmos", "#c2410c", 0.95),
    ("pmos", "#e11d48", 0.95),
    ("locali", "#a78bfa", 0.60),
    ("m1", "#3b82f6", 0.78),
    ("via1", "#15803d", 0.95),
    ("m2", "#0d9488", 0.78),
    ("via2", "#1e293b", 0.95),
    ("m3", "#ef4444", 0.80),
    ("via3", "#1e293b", 0.95),
    ("m4", "#7c3aed", 0.72),
    ("via4", "#0f172a", 0.95),
    ("m5", "#b45309", 0.65),
]
LAYER_NAMES = {k for k, _, _ in LAYER_STYLE}


def _parse_mag_rects(path: Path) -> tuple[float, list[tuple[str, int, int, int, int]], list[tuple[str, int, int]], list[tuple[str, tuple[int, int, int, int, int, int]]]]:
    """Parse a Magic .mag file into (units_per_um, rects, labels, uses)."""
    units_per_um = 200.0
    layer: str | None = None
    rects: list[tuple[str, int, int, int, int]] = []
    labels: list[tuple[str, int, int]] = []
    uses: list[tuple[str, tuple[int, int, int, int, int, int]]] = []
    cur_use: str | None = None

    for raw in path.read_text(errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("magscale "):
            parts = line.split()
            if len(parts) == 3:
                num, den = int(parts[1]), int(parts[2])
                # sky130A base lambda = 10nm = 0.01um -> 100 units/um; magscale 1 2 -> 200 units/um
                units_per_um = 100.0 * (den / num)
        elif line.startswith("<< ") and line.endswith(" >>"):
            cur = line[3:-3].strip()
            if cur == "metal1":
                cur = "m1"
            elif cur == "metal2":
                cur = "m2"
            elif cur == "metal3":
                cur = "m3"
            elif cur == "metal4":
                cur = "m4"
            elif cur == "metal5":
                cur = "m5"
            elif cur in ("viali", "mcon"):
                cur = "locali"
            layer = cur
        elif line.startswith("rect ") and layer in LAYER_NAMES:
            parts = line.split()
            if len(parts) == 5:
                rects.append((layer, int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
        elif line.startswith("rlabel ") or line.startswith("flabel "):
            parts = line.split()
            if len(parts) >= 8:
                idx = 3 if parts[2] in ("s", "f") else 2
                if len(parts) >= idx + 5:
                    try:
                        x1, y1, x2, y2 = int(parts[idx]), int(parts[idx + 1]), int(parts[idx + 2]), int(parts[idx + 3])
                        lbl = parts[-1].replace("\\[", "[").replace("\\]", "]")
                        labels.append((lbl, (x1 + x2) // 2, (y1 + y2) // 2))
                    except ValueError:
                        pass
        elif line.startswith("use "):
            parts = line.split()
            if len(parts) >= 2:
                cur_use = parts[1]
        elif line.startswith("transform ") and cur_use is not None:
            parts = line.split()
            if len(parts) == 7:
                t = tuple(int(v) for v in parts[1:7])
                uses.append((cur_use, t))  # type: ignore[arg-type]
                cur_use = None
    return units_per_um, rects, labels, uses


def render_layout_png(
    block: BlockSpec,
    mag_path: Path,
    png_path: Path,
    pnr_info: dict[str, Any],
    sta_info: dict[str, Any],
    drc_total: int,
    lvs_status: str,
    title_suffix: str = "",
) -> None:
    u_top, top_rects, top_labels, uses = _parse_mag_rects(mag_path)

    # Cache standard-cell rectangles from PDK mag/ directory (and work dir if present)
    cell_cache: dict[str, tuple[float, list[tuple[str, int, int, int, int]]]] = {}
    layer_boxes: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k, _, _ in LAYER_STYLE}

    # Add top-level routing, PDN, and pins
    for lyr, x1, y1, x2, y2 in top_rects:
        layer_boxes[lyr].append((x1 / u_top, y1 / u_top, (x2 - x1) / u_top, (y2 - y1) / u_top))

    # Expand standard-cell instances with exact Magic affine transforms
    for cell_name, (a, b, c, d, e, f) in uses:
        if cell_name not in cell_cache:
            cand = SC_MAG_DIR / f"{cell_name}.mag"
            if not cand.exists():
                cand = mag_path.parent / f"{cell_name}.mag"
            if cand.exists():
                uc, crects, _, _ = _parse_mag_rects(cand)
                # Keep representative FEOL/M1 layers so plot is crisp and fast
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

    die_w = pnr_info.get("die_w_um") or 50.0
    die_h = pnr_info.get("die_h_um") or 30.0
    ar = max(0.35, min(1.5, die_h / max(die_w, 1.0)))
    fig_w = 14.0
    fig_h = max(6.5, min(12.0, fig_w * ar + 1.8))

    fig, ax = plt.subplots(figsize=(fig_w, fig_h), facecolor="white")
    ax.set_facecolor("white")

    # Draw die boundary
    ax.add_patch(
        Rectangle(
            (0.0, 0.0),
            die_w,
            die_h,
            facecolor="#fafafa",
            edgecolor="#0f172a",
            linewidth=1.5,
            zorder=0,
        )
    )

    legend_handles: list[Patch] = []
    for z, (lyr, color, alpha) in enumerate(LAYER_STYLE, start=1):
        boxes = layer_boxes[lyr]
        if not boxes:
            continue
        patches = [Rectangle((x, y), w, h) for x, y, w, h in boxes]
        pc = PatchCollection(patches, facecolor=color, edgecolor="none", alpha=alpha, zorder=z)
        ax.add_collection(pc)
        legend_handles.append(Patch(facecolor=color, alpha=min(1.0, alpha + 0.15), label=lyr))

    # Plot peripheral I/O pin markers with non-overlapping rotated labels
    pin_labels = [(n, x / u_top, y / u_top) for n, x, y in top_labels if n not in ("VPWR", "VGND")]
    if pin_labels:
        px = [p[1] for p in pin_labels]
        py = [p[2] for p in pin_labels]
        ax.scatter(px, py, s=8, color="#0f172a", marker="s", zorder=50)
        # Group pins by edge and sort along edge to enforce clean spacing
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
        min_gap_x = max(1.3, die_w / 38.0)
        min_gap_y = max(1.3, die_h / 26.0)
        off = max(0.8, 0.015 * max(die_w, die_h))
        for edge_name, pts in edges.items():
            if edge_name in ("top", "bottom"):
                pts.sort(key=lambda t: t[1])
                last = -1e9
                for name, x, y in pts:
                    if x - last < min_gap_x:
                        continue
                    last = x
                    ty = die_h + off if edge_name == "top" else -off
                    va = "bottom" if edge_name == "top" else "top"
                    ax.text(x, ty, name, fontsize=5.5, color="#0f172a", ha="center", va=va, rotation=90, zorder=55)
            else:
                pts.sort(key=lambda t: t[2])
                last = -1e9
                for name, x, y in pts:
                    if y - last < min_gap_y:
                        continue
                    last = y
                    tx = -off if edge_name == "left" else die_w + off
                    ha = "right" if edge_name == "left" else "left"
                    ax.text(tx, y, name, fontsize=5.5, color="#0f172a", ha=ha, va="center", zorder=55)

    pad_x = max(4.5, 0.11 * die_w)
    pad_y = max(5.5, 0.16 * die_h)
    ax.set_xlim(-pad_x, die_w + pad_x)
    ax.set_ylim(-pad_y, die_h + pad_y)
    ax.set_aspect("equal")
    ax.set_xlabel("x (µm)", fontsize=10)
    ax.set_ylabel("y (µm)", fontsize=10)
    ax.grid(True, linestyle="--", linewidth=0.35, color="#cbd5e1", alpha=0.8)

    ss_s = sta_info["ss_100C_1v60"]["setup_wns_ns"]
    ff_h = sta_info["ff_n40C_1v95"]["hold_wns_ns"]
    tt_s = sta_info["tt_025C_1v80"]["setup_wns_ns"]
    subtitle = (
        f"Die {die_w:.1f}×{die_h:.1f} µm ({pnr_info['die_area_um2']:.0f} µm²) | "
        f"StdCells={pnr_info['std_cells']} | Util={pnr_info['utilization_pct']:.1f}% | "
        f"DRT DRVs={pnr_info['openroad_drt_drvs']} | Magic DRC={drc_total} | LVS={lvs_status}\n"
        f"250 MHz Post-Route RCX STA: TT setup={tt_s:+.3f} ns, SS(100C/1.60V) setup={ss_s:+.3f} ns, FF(-40C/1.95V) hold={ff_h:+.3f} ns"
    )
    ax.set_title(f"SKY130A sky130_fd_sc_hd P&R{title_suffix} — {block.name}\n{subtitle}", fontsize=10, fontweight="bold", pad=10)
    ax.legend(
        handles=legend_handles,
        loc="upper left",
        bbox_to_anchor=(1.01, 1.0),
        frameon=True,
        facecolor="white",
        edgecolor="#cbd5e1",
        fontsize=7.5,
        title="Layers",
        title_fontsize=8,
    )
    fig.tight_layout()
    fig.savefig(png_path, dpi=180, facecolor="white")
    plt.close(fig)


def run_block(block_name: str, v2: bool = False) -> dict[str, Any]:
    block_map = BLOCKS_V2 if v2 else BLOCKS
    results_base = RESULTS_BASE_V2 if v2 else RESULTS_BASE
    variant_base = VARIANT_BASE_V2 if v2 else VARIANT_BASE
    block = block_map[block_name]
    t0 = time.time()
    work = results_base / block.name
    work.mkdir(parents=True, exist_ok=True)
    variant_dir = variant_base / block.name
    variant_dir.mkdir(parents=True, exist_ok=True)

    if v2:
        synth_lib = build_filtered_synth_lib(LIB_SS, results_base / "_work/sky130_fd_sc_hd__ss_fast_synth.lib", fast_ss=True)
    else:
        synth_lib = build_filtered_synth_lib(LIB_TT, results_base / "_work/sky130_fd_sc_hd__tt_synth.lib")

    tag = f"{block.name}{'_v2' if v2 else ''}"
    print(f"[{tag}] 1/6 Yosys synthesis...", flush=True)
    synth_v, synth_info = run_yosys(block, work, synth_lib, v2=v2)

    sdc_path = work / f"{block.name}.sdc"
    write_sdc(block, sdc_path, post_route=False)

    print(f"[{tag}] 2/6 OpenROAD P&R + OpenRCX (1 thread)...", flush=True)
    pnr_info = run_openroad_pnr(block, work, synth_v, sdc_path, v2=v2)

    print(f"[{tag}] 3/6 3-Corner Post-Route STA (TT / SS / FF)...", flush=True)
    sta_info = run_sta_3corner(block, work, pnr_info)

    print(f"[{tag}] 4/6 Magic DEF->MAG/GDS + Full DRC + LVS extraction...", flush=True)
    magic_info = run_magic_drc_gds_ext(block, work, Path(pnr_info["routed_def"]))

    print(f"[{tag}] 5/6 Netgen LVS...", flush=True)
    lvs_info = run_netgen_lvs(block, work, Path(magic_info["lvs_spice_path"]), Path(pnr_info["routed_pg_v"]))

    print(f"[{tag}] 6/6 Rendering white-background layout PNG...", flush=True)
    png_work = work / f"{block.name}.png"
    render_layout_png(
        block,
        Path(magic_info["mag_path"]),
        png_work,
        pnr_info,
        sta_info,
        magic_info["magic_drc_total"],
        lvs_info["lvs_status"],
        title_suffix=" (v2)" if v2 else "",
    )

    # Export clean deliverables to digital/pnr/variants/hd_pnr[_v2]/<block>/
    exports = {
        f"{block.name}.def": Path(pnr_info["routed_def"]),
        f"{block.name}.gds": Path(magic_info["gds_path"]),
        f"{block.name}.v": Path(pnr_info["routed_v"]),
        f"{block.name}_pg.v": Path(pnr_info["routed_pg_v"]),
        f"{block.name}.png": png_work,
    }
    for fname, src in exports.items():
        shutil.copy2(src, variant_dir / fname)

    elapsed = round(time.time() - t0, 1)
    summary = {
        "block": block.name,
        "variant": "hd_pnr_v2" if v2 else "hd_pnr",
        "params": block.params,
        "rtl_files": block.rtl_files,
        "clocks_mhz": {c.name: round(1000.0 / c.period_ns, 2) for c in block.clocks},
        "synthesis": synth_info,
        "pnr": {
            "die_w_um": pnr_info["die_w_um"],
            "die_h_um": pnr_info["die_h_um"],
            "die_area_um2": pnr_info["die_area_um2"],
            "core_w_um": pnr_info["core_w_um"],
            "core_h_um": pnr_info["core_h_um"],
            "std_cells": pnr_info["std_cells"],
            "phys_cells": pnr_info["phys_cells"],
            "total_cells": pnr_info["total_cells"],
            "design_area_um2": pnr_info["design_area_um2"],
            "utilization_pct": pnr_info["utilization_pct"],
            "openroad_drt_drvs": pnr_info["openroad_drt_drvs"],
        },
        "sta_250mhz": sta_info,
        "magic_drc_total": magic_info["magic_drc_total"],
        "netgen_lvs": lvs_info["lvs_status"],
        "lvs_match": lvs_info["lvs_match"],
        "artifacts": {
            "variant_dir": str(variant_dir.relative_to(REPO)),
            "results_dir": str(work.relative_to(REPO)),
            "png": str((variant_dir / f"{block.name}.png").relative_to(REPO)),
            "gds": str((variant_dir / f"{block.name}.gds").relative_to(REPO)),
            "def": str((variant_dir / f"{block.name}.def").relative_to(REPO)),
            "verilog": str((variant_dir / f"{block.name}.v").relative_to(REPO)),
        },
        "elapsed_s": elapsed,
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (variant_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[{tag}] DONE in {elapsed}s | cells={pnr_info['std_cells']} | "
        f"{pnr_info['die_w_um']:.1f}x{pnr_info['die_h_um']:.1f} um | "
        f"DRT={pnr_info['openroad_drt_drvs']} | DRC={magic_info['magic_drc_total']} | "
        f"LVS={lvs_info['lvs_status']} | "
        f"TT_setup={sta_info['tt_025C_1v80']['setup_wns_ns']} ns | "
        f"SS_setup={sta_info['ss_100C_1v60']['setup_wns_ns']} ns | "
        f"FF_hold={sta_info['ff_n40C_1v95']['hold_wns_ns']} ns",
        flush=True,
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description="SKY130A Digital RTL-to-GDS/MAG P&R Flow")
    ap.add_argument(
        "--v2",
        action="store_true",
        help="Run timing-closed v2 RTL flow (outputs to digital/pnr/variants/hd_pnr_v2)",
    )
    ap.add_argument(
        "blocks",
        nargs="*",
        choices=list(BLOCKS.keys()),
        help="Blocks to run (default: all 4 blocks)",
    )
    args = ap.parse_args()
    block_map = BLOCKS_V2 if args.v2 else BLOCKS
    variant_base = VARIANT_BASE_V2 if args.v2 else VARIANT_BASE
    targets = args.blocks or list(block_map.keys())
    all_summaries: list[dict[str, Any]] = []
    for name in targets:
        all_summaries.append(run_block(name, v2=args.v2))
    # Refresh all_blocks_summary.json whenever all 4 block summaries exist
    existing: list[dict[str, Any]] = []
    for name in block_map:
        sp = variant_base / name / "summary.json"
        if sp.exists():
            existing.append(json.loads(sp.read_text()))
    if len(existing) == len(block_map):
        summary_path = variant_base / "all_blocks_summary.json"
        summary_path.write_text(json.dumps(existing, indent=2) + "\n")


if __name__ == "__main__":
    main()
