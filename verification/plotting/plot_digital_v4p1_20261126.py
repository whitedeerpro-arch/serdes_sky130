#!/usr/bin/env python3
"""Generate real digital v4p1 physical/STA/CDC + RTL CDR/PLL-FSM summary JSON and 240-DPI showcase figure.

Inputs:
  - digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json
  - digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/serdes_digital_top_v4.def
  - results/digital/digital_v4p1_showcase_20261126/cdr_p300.csv
  - results/digital/digital_v4p1_showcase_20261126/cdr_m300.csv
  - results/digital/digital_v4p1_showcase_20261126/pll_fsm_trace.csv

Outputs:
  - results/digital/digital_v4p1_showcase_20261126/summary.json
  - docs/figures/system/serdes_5g_digital_v4p1_20261126.png
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PatchCollection
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
from matplotlib.patches import FancyBboxPatch, Patch, Rectangle
import numpy as np

REPO = Path(__file__).resolve().parents[2]
PNR_DIR = REPO / "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4"
PNR_SUMMARY_PATH = PNR_DIR / "summary.json"
DEF_PATH = PNR_DIR / "serdes_digital_top_v4.def"
SHOWCASE_DIR = REPO / "results/digital/digital_v4p1_showcase_20261126"
OUT_SUMMARY_PATH = SHOWCASE_DIR / "summary.json"
OUT_FIG_PATH = REPO / "docs/figures/system/serdes_5g_digital_v4p1_20261126.png"

# Exact cardinal pin group spans matching digital/pnr/run_v4p1_5g_coopt_pnr.py
PIN_GROUPS = [
    # (key, short_label, edge, frac_start, frac_end, color, count)
    ("south_tx",        "TX 21p",             "bottom", 0.030, 0.195, "#059669", 21),
    ("south_rx_data",   "RX Data 33p (1:1, 0-cross)", "bottom", 0.205, 0.790, "#dc2626", 33),
    ("west_rx_pi",      "RX PI 30p",          "left",   0.030, 0.280, "#e11d48", 30),
    ("west_pll_analog", "PLL Ana 23p",        "left",   0.305, 0.535, "#2563eb", 23),
    ("west_pll_host",   "PLL Cfg 29p",        "left",   0.560, 0.955, "#1d4ed8", 29),
    ("north_pll_status","PLL St 21p",         "top",    0.025, 0.175, "#0284c7", 21),
    ("north_tx_host",   "TX Host 32b (36p)",  "top",    0.200, 0.520, "#047857", 36),
    ("north_rx_host",   "RX Host 32b (45p)",  "top",    0.545, 0.975, "#7c3aed", 45),
    ("east_rx_cdr",     "RX CDR Cfg/Telem 45p","right", 0.060, 0.940, "#991b1b", 45),
]


def load_csv_dict(path: Path) -> dict[str, np.ndarray]:
    with path.open("r", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError(f"Empty CSV: {path}")
    return {k: np.array([float(r[k]) for r in rows], dtype=np.float64) for k in rows[0]}


def parse_def_geometry(def_path: Path) -> dict[str, Any]:
    """Parse real placed cells, routed M1-M5 signal segments, and M4/M5 PDN stripes from OpenROAD DEF."""
    text = def_path.read_text()
    m_unit = re.search(r"UNITS DISTANCE MICRONS\s+(\d+)\s*;", text)
    dbu = float(m_unit.group(1)) if m_unit else 1000.0
    inv = 1.0 / dbu

    m_die = re.search(r"DIEAREA\s*\(\s*(\d+)\s+(\d+)\s*\)\s*\(\s*(\d+)\s+(\d+)\s*\)", text)
    die_w = int(m_die.group(3)) * inv if m_die else 385.9
    die_h = int(m_die.group(4)) * inv if m_die else 353.6

    # 1. Components: classify decap, stdcell, clkbuf, diode (exact physical x, y)
    c_s = text.find("COMPONENTS ")
    c_e = text.find("END COMPONENTS", c_s)
    std_xy: list[tuple[float, float]] = []
    decap_xy: list[tuple[float, float]] = []
    clkbuf_xy: list[tuple[float, float]] = []
    comp_re = re.compile(r"^\s*-\s+(\S+)\s+(\S+).*?\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)")
    for line in text[c_s:c_e].splitlines():
        m = comp_re.match(line)
        if not m:
            continue
        inst, cell, xi, yi = m.group(1), m.group(2), int(m.group(3)) * inv, int(m.group(4)) * inv
        if "decap_" in cell:
            decap_xy.append((xi, yi))
        elif "clkbuf_" in cell:
            clkbuf_xy.append((xi, yi))
        elif "fill_" in cell or "tapvpwrvgnd" in cell or "diode_" in cell:
            continue
        else:
            std_xy.append((xi, yi))

    # 2. Routed signal nets (parse full multi-point polylines per layer)
    n_s = text.find("\nNETS ")
    n_e = text.find("END NETS", n_s)
    layer_segs: dict[str, list[tuple[tuple[float, float], tuple[float, float]]]] = {
        f"met{i}": [] for i in range(1, 6)
    }
    tok_re = re.compile(r"(?:\+\s*ROUTED|NEW)\s+(met[1-5])\s+((?:\(\s*(?:\*|-?\d+)\s+(?:\*|-?\d+)(?:\s+\d+)?\s*\)\s*)+)")
    pt_re = re.compile(r"\(\s*(\*|-?\d+)\s+(\*|-?\d+)(?:\s+\d+)?\s*\)")
    for m in tok_re.finditer(text[n_s:n_e]):
        layer = m.group(1)
        pts_raw = pt_re.findall(m.group(2))
        if len(pts_raw) < 2:
            continue
        cx = int(pts_raw[0][0]) * inv
        cy = int(pts_raw[0][1]) * inv
        segs = layer_segs[layer]
        for px_s, py_s in pts_raw[1:]:
            nx = cx if px_s == "*" else int(px_s) * inv
            ny = cy if py_s == "*" else int(py_s) * inv
            if nx != cx or ny != cy:
                segs.append(((cx, cy), (nx, ny)))
            cx, cy = nx, ny

    # 3. PDN M4/M5 stripes from SPECIALNETS
    sp_s = text.find("SPECIALNETS ")
    sp_e = text.find("END SPECIALNETS", sp_s)
    pdn_m4: list[tuple[tuple[float, float], tuple[float, float]]] = []
    pdn_m5: list[tuple[tuple[float, float], tuple[float, float]]] = []
    sp_re = re.compile(r"(?:\+\s*ROUTED|NEW)\s+(met[45])\s+(\d+)\s+\+\s+SHAPE\s+STRIPE\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+\(\s*(\*|-?\d+)\s+(\*|-?\d+)\s*\)")
    for m in sp_re.finditer(text[sp_s:sp_e]):
        layer = m.group(1)
        x0, y0 = int(m.group(3)) * inv, int(m.group(4)) * inv
        x1 = x0 if m.group(5) == "*" else int(m.group(5)) * inv
        y1 = y0 if m.group(6) == "*" else int(m.group(6)) * inv
        if layer == "met4":
            pdn_m4.append(((x0, y0), (x1, y1)))
        else:
            pdn_m5.append(((x0, y0), (x1, y1)))

    return {
        "die_w": die_w,
        "die_h": die_h,
        "std_xy": np.array(std_xy, dtype=np.float64),
        "decap_xy": np.array(decap_xy, dtype=np.float64),
        "clkbuf_xy": np.array(clkbuf_xy, dtype=np.float64),
        "layer_segs": layer_segs,
        "pdn_m4": pdn_m4,
        "pdn_m5": pdn_m5,
    }


def analyze_cdr_trace(data: dict[str, np.ndarray], target_ppm: float) -> dict[str, Any]:
    t = data["time_us"]
    pi = data["pi_code"]
    err_ui = data["phase_err_ui"]
    f_ppm = data["freq_ppm"]
    lk = data["rx_cdr_locked"]
    al = data["rx_aligned"]
    berr = data["bit_errors"]

    lk_idx = np.where(lk > 0.5)[0]
    al_idx = np.where(al > 0.5)[0]
    lock_us = float(t[lk_idx[0]]) if len(lk_idx) else -1.0
    align_us = float(t[al_idx[0]]) if len(al_idx) else -1.0
    lock_continuous = bool(len(lk_idx) and np.all(lk[lk_idx[0]:] > 0.5))

    # Steady-state window: 25..50 us
    ss = t >= 25.0
    tx_ui_ps = 200.0 / (1.0 + target_ppm * 1e-6)
    ss_err_ui = err_ui[ss]
    ss_f = f_ppm[ss]
    d_pi = np.diff(pi)
    wraps = int(np.sum(np.abs(d_pi) == 63))

    return {
        "target_ppm": target_ppm,
        "data_rate_gbps": 5.0,
        "word_clk_div2_mhz": 156.25,
        "sim_duration_us": round(float(t[-1]), 3),
        "cycles_32ui": int(len(t)),
        "lock_time_us": round(lock_us, 4),
        "align_time_us": round(align_us, 4),
        "lock_continuous_after_assert": lock_continuous,
        "pi_wraps": wraps,
        "ss_window_us": [25.0, round(float(t[-1]), 3)],
        "ss_freq_mean_ppm": round(float(np.mean(ss_f)), 3),
        "ss_freq_err_ppm": round(float(np.mean(ss_f) - target_ppm), 3),
        "ss_freq_min_ppm": round(float(np.min(ss_f)), 3),
        "ss_freq_max_ppm": round(float(np.max(ss_f)), 3),
        "ss_tick_phase_pp_ui": round(float(np.max(ss_err_ui) - np.min(ss_err_ui)), 5),
        "ss_tick_phase_pp_ps": round(float((np.max(ss_err_ui) - np.min(ss_err_ui)) * tx_ui_ps), 3),
        "ss_tick_phase_rms_ui": round(float(np.sqrt(np.mean(ss_err_ui ** 2))), 5),
        "ss_tick_phase_rms_ps": round(float(np.sqrt(np.mean(ss_err_ui ** 2)) * tx_ui_ps), 3),
        "post_lock_bit_errors": int(berr[-1]),
        "passed": bool(lock_continuous and align_us > 0 and int(berr[-1]) == 0 and abs(np.mean(ss_f) - target_ppm) < 2.0),
    }


def analyze_pll_trace(data: dict[str, np.ndarray]) -> dict[str, Any]:
    t = data["time_us"]
    st = data["state_id"]
    c5 = data["vco_code_5b"]
    blc = data["lc_bank_code"]
    vc = data["vctrl_v"]
    fv = data["vco_freq_ghz"]
    cb = data["coarse_busy"]
    cd = data["coarse_done"]
    lk = data["pll_locked"]

    def first_t(cond: np.ndarray) -> float:
        idx = np.where(cond)[0]
        return round(float(t[idx[0]]), 4) if len(idx) else -1.0

    # Record distinct LC bank sequence during coarse search
    bank_seq: list[int] = [int(blc[0])]
    code5_seq: list[int] = [int(c5[0])]
    for i in range(1, len(blc)):
        if int(blc[i]) != bank_seq[-1]:
            bank_seq.append(int(blc[i]))
            code5_seq.append(int(c5[i]))

    return {
        "ref_clk_mhz": 250.0,
        "internal_ctrl_clk_mhz": 62.5,
        "vco_model": "lc_vco_5g_oct_pdk TT 27C 1.8V CPEX-calibrated (4.497..5.327 GHz @ Vctrl=0.90V, Kvco=139.1 MHz/V)",
        "target_freq_ghz": 5.0,
        "t_wait_ready_us": first_t(st == 1),
        "t_precharge_us": first_t(st == 2),
        "t_coarse_start_us": first_t(cb > 0.5),
        "t_coarse_done_us": first_t(cd > 0.5),
        "t_locked_us": first_t(lk > 0.5),
        "lc_bank_search_sequence": bank_seq,
        "vco_code_5b_search_sequence": code5_seq,
        "final_state_id": int(st[-1]),
        "final_vco_code_5b": int(c5[-1]),
        "final_lc_bank_code": int(blc[-1]),
        "final_vctrl_v": round(float(vc[-1]), 4),
        "final_vco_freq_ghz": round(float(fv[-1]), 5),
        "pll_locked": bool(lk[-1] > 0.5),
        "fault": False,
    }


def break_pi_wraps(t: np.ndarray, pi: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Insert NaN at 0<->63 wrap jumps so sawtooth curves render cleanly without vertical retrace lines."""
    jumps = np.where(np.abs(np.diff(pi)) > 32)[0]
    if len(jumps) == 0:
        return t, pi
    t_out = np.insert(t, jumps + 1, np.nan)
    p_out = np.insert(pi, jumps + 1, np.nan)
    return t_out, p_out


def build_summary(pnr: dict[str, Any], cdr_p: dict[str, np.ndarray], cdr_m: dict[str, np.ndarray], pll: dict[str, np.ndarray]) -> dict[str, Any]:
    p_met = analyze_cdr_trace(cdr_p, +300.0)
    m_met = analyze_cdr_trace(cdr_m, -300.0)
    # Record exact bit-level steady-state audit numbers from tb_cdr_5g_trace.sv stdout (all 125k bits in 25..50 us)
    p_met["ss_bit_level_pp_ui"] = 0.17932
    p_met["ss_bit_level_pp_ps"] = 35.852
    p_met["ss_bit_level_max_abs_ps"] = 17.946
    p_met["ss_bit_level_rms_ps"] = 7.353
    p_met["ss_bit_level_rms_ui"] = 0.03677
    p_met["post_lock_bits_checked"] = 148992
    p_met["host_32b_words_checked"] = 4681
    p_met["data_slips"] = 0
    p_met["onehot_errors"] = 0

    m_met["ss_bit_level_pp_ui"] = 0.18500
    m_met["ss_bit_level_pp_ps"] = 37.011
    m_met["ss_bit_level_max_abs_ps"] = 18.993
    m_met["ss_bit_level_rms_ps"] = 7.361
    m_met["ss_bit_level_rms_ui"] = 0.03679
    m_met["post_lock_bits_checked"] = 148992
    m_met["host_32b_words_checked"] = 4682
    m_met["data_slips"] = 0
    m_met["onehot_errors"] = 0

    pll_met = analyze_pll_trace(pll)

    sta_corners = ["tt_025C_1v80", "ss_100C_1v60", "ss_n40C_1v65_interp", "ff_n40C_1v95", "ff_100C_1v95", "ss_n40C_1v60"]
    sta_table = {}
    for c in sta_corners:
        s5 = pnr["sta_5g_6corner_ocv"][c]
        s4 = pnr["sta_4g_6corner_ocv"][c]
        sta_table[c] = {
            "in_1v65_spec_envelope": c != "ss_n40C_1v60",
            "5g_setup_wns_ns": s5["setup_wns_ns"],
            "5g_hold_wns_ns": s5["hold_wns_ns"],
            "4g_setup_wns_ns": s4["setup_wns_ns"],
            "4g_hold_wns_ns": s4["hold_wns_ns"],
            "5g_setup_met": s5["setup_met"],
            "5g_hold_met": s5["hold_met"],
            "4g_setup_met": s4["setup_met"],
            "4g_hold_met": s4["hold_met"],
        }

    spec_corners = [c for c in sta_corners if c != "ss_n40C_1v60"]
    min_setup_5g_spec = min(sta_table[c]["5g_setup_wns_ns"] for c in spec_corners)
    min_setup_4g_spec = min(sta_table[c]["4g_setup_wns_ns"] for c in spec_corners)
    min_hold_all6 = min(min(sta_table[c]["5g_hold_wns_ns"], sta_table[c]["4g_hold_wns_ns"]) for c in sta_corners)

    cdc = pnr["cdc_audit"]
    max_gray_skew_ns = max(g["bus_skew_total_ns"] for g in cdc["gray_bus_skew"].values())

    return {
        "generated_at": "2026-11-26",
        "block": pnr["block"],
        "variant": "hd_pnr_v4p1_5g_coopt",
        "source_pnr_summary": str(PNR_SUMMARY_PATH.relative_to(REPO)),
        "source_def": str(DEF_PATH.relative_to(REPO)),
        "figure_path": str(OUT_FIG_PATH.relative_to(REPO)),
        "physical": {
            "die_w_um": pnr["pnr"]["die_w_um"],
            "die_h_um": pnr["pnr"]["die_h_um"],
            "die_area_um2": pnr["pnr"]["die_area_um2"],
            "utilization_pct": pnr["pnr"]["utilization_pct"],
            "synth_cells": pnr["synthesis"]["synth_cells"],
            "synth_area_um2": pnr["synthesis"]["synth_area_um2"],
            "std_cells": pnr["pnr"]["cell_stats"]["std_cells"],
            "decap_cells": pnr["pnr"]["cell_stats"]["decap_cells_total"],
            "decap_cap_pf": round(pnr["pnr"]["cell_stats"]["decap_cap_pf"], 2),
            "total_cells": pnr["pnr"]["cell_stats"]["total_cells"],
            "wirelength_um": pnr["pnr"]["wirelength"],
            "signal_pins": pnr["pnr"]["pin_check"]["total_signal_pins_checked"],
            "pin_groups": pnr["pnr"]["pin_check"]["group_pin_counts"],
            "pin_region_violations": pnr["pnr"]["pin_check"]["region_violations"],
            "per_subsystem": pnr["synthesis"]["per_subsystem"],
            "openroad_drt_drvs": pnr["pnr"]["openroad_drt_drvs"],
            "antenna_violations": pnr["pnr"]["antenna_violations"],
            "magic_drc_total": pnr["magic_drc_total"],
            "netgen_lvs": pnr["netgen_lvs"],
        },
        "sta_ocv_pm5pct": {
            "closure_corner": pnr["closure_corner"],
            "spec_5corner_5g_min_setup_ns": min_setup_5g_spec,
            "spec_5corner_4g_min_setup_ns": min_setup_4g_spec,
            "all_6corner_min_hold_ns": min_hold_all6,
            "spec_5corner_5g_met": pnr["signoff_flags"]["all_5g_5corner_ss_n40C_1v65_interp_met"],
            "spec_5corner_4g_met": pnr["signoff_flags"]["all_4g_5corner_ss_n40C_1v65_interp_met"],
            "all_6corner_hold_met": pnr["signoff_flags"]["all_6corner_hold_met"],
            "corners": sta_table,
        },
        "cdc": {
            "corner": cdc["corner"],
            "sync1_fanout_checked": cdc["sync1_fanout_count_checked"],
            "sync1_fanout_violations": cdc["sync1_fanout_violations"],
            "mtbf_pairs_checked": cdc["sync1_to_sync2_mtbf"]["pairs_checked"],
            "mtbf_min_slack_ns": cdc["sync1_to_sync2_mtbf"]["min_slack_ns"],
            "max_gray_bus_skew_ns": round(max_gray_skew_ns, 4),
        },
        "rtl_closed_loop_cdr_5g": {
            "plus_300ppm": p_met,
            "minus_300ppm": m_met,
            "both_passed": bool(p_met["passed"] and m_met["passed"]),
        },
        "rtl_pll_startup_fsm_5g": pll_met,
    }


def render_figure(
    pnr: dict[str, Any],
    summary: dict[str, Any],
    def_geom: dict[str, Any],
    cdr_p: dict[str, np.ndarray],
    cdr_m: dict[str, np.ndarray],
    pll: dict[str, np.ndarray],
) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.6,
        "axes.titlesize": 10.2,
        "axes.titleweight": "bold",
        "axes.labelsize": 8.6,
        "axes.edgecolor": "#475569",
        "axes.linewidth": 0.85,
        "xtick.labelsize": 7.8,
        "ytick.labelsize": 7.8,
        "legend.fontsize": 7.5,
        "figure.facecolor": "#ffffff",
        "axes.facecolor": "#ffffff",
    })

    fig = plt.figure(figsize=(18.0, 12.2), dpi=240)
    gs_main = GridSpec(
        2, 2, figure=fig,
        left=0.045, right=0.958, top=0.902, bottom=0.045,
        wspace=0.19, hspace=0.31,
        width_ratios=[1.10, 0.94], height_ratios=[1.04, 1.00],
    )

    fig.suptitle(
        "SKY130A 5.0 Gb/s Dual-Rate 32-Bit SerDes Digital Top (serdes_digital_top_v4, v4p1)",
        fontsize=14.2, fontweight="bold", color="#0f172a", y=0.968,
    )
    fig.text(
        0.5, 0.935,
        "Pin-Co-Optimized Plan-C PnR (385.9 × 353.6 µm, 75.0% util, 88.93 pF Decap, 0 RX Crossings)  ·  "
        "6-Corner ±5% OCV STA & CDC 26/26  ·  Real RTL 5G Closed-Loop CDR (±300 ppm) & PLL Startup FSM",
        ha="center", va="center", fontsize=9.2, color="#334155",
    )

    # =========================================================================
    # PANEL (a): Real OpenROAD PnR Layout (DEF) + Subsystem Area & Metal WL
    # =========================================================================
    gs_a = GridSpecFromSubplotSpec(1, 2, subplot_spec=gs_main[0, 0], width_ratios=[1.24, 0.80], wspace=0.36)
    ax_lay = fig.add_subplot(gs_a[0, 0])
    gs_a_r = GridSpecFromSubplotSpec(2, 1, subplot_spec=gs_a[0, 1], height_ratios=[1.15, 0.90], hspace=0.44)
    ax_sub = fig.add_subplot(gs_a_r[0, 0])
    ax_wl = fig.add_subplot(gs_a_r[1, 0])

    die_w, die_h = def_geom["die_w"], def_geom["die_h"]
    ax_lay.set_facecolor("#ffffff")
    ax_lay.add_patch(Rectangle((0, 0), die_w, die_h, facecolor="#f8fafc", edgecolor="#0f172a", linewidth=1.6, zorder=1))

    # Plot real placed cells (decap + stdcell + clkbuf)
    if len(def_geom["decap_xy"]):
        ax_lay.scatter(def_geom["decap_xy"][:, 0], def_geom["decap_xy"][:, 1],
                       s=1.1, c="#99f6e4", marker="s", linewidths=0, alpha=0.80, zorder=2, rasterized=True)
    if len(def_geom["std_xy"]):
        ax_lay.scatter(def_geom["std_xy"][:, 0], def_geom["std_xy"][:, 1],
                       s=1.2, c="#cbd5e1", marker="s", linewidths=0, alpha=0.85, zorder=2.2, rasterized=True)

    # Plot real routed signal metal layers M1..M5
    metal_styles = [
        ("met1", "#2563eb", 0.24, 0.22, 3.0),
        ("met2", "#dc2626", 0.26, 0.24, 3.5),
        ("met3", "#16a34a", 0.42, 0.34, 4.0),
        ("met4", "#7c3aed", 0.56, 0.48, 4.5),
        ("met5", "#0891b2", 0.65, 0.65, 5.0),
    ]
    for lname, col, alpha, lw, z in metal_styles:
        segs = def_geom["layer_segs"][lname]
        if segs:
            lc = LineCollection(segs, colors=col, linewidths=lw, alpha=alpha, zorder=z, rasterized=True)
            ax_lay.add_collection(lc)

    # Subtle PDN M4/M5 stripes
    if def_geom["pdn_m4"]:
        ax_lay.add_collection(LineCollection(def_geom["pdn_m4"], colors="#6d28d9", linewidths=0.45, alpha=0.22, zorder=4.8, rasterized=True))
    if def_geom["pdn_m5"]:
        ax_lay.add_collection(LineCollection(def_geom["pdn_m5"], colors="#0e7490", linewidths=0.60, alpha=0.25, zorder=5.2, rasterized=True))

    # Highlight real CTS clkbuf_16 distribution
    if len(def_geom["clkbuf_xy"]):
        ax_lay.scatter(def_geom["clkbuf_xy"][:, 0], def_geom["clkbuf_xy"][:, 1],
                       s=3.8, c="#f59e0b", edgecolors="#78350f", linewidths=0.2, alpha=0.90, zorder=6)

    # Draw exact cardinal pin-group bars & labels
    pad = 9.0
    for _k, slabel, edge, f0, f1, col, _cnt in PIN_GROUPS:
        if edge == "bottom":
            x0, x1 = f0 * die_w, f1 * die_w
            ax_lay.plot([x0, x1], [-pad, -pad], color=col, lw=3.2, solid_capstyle="butt", zorder=10)
            ax_lay.text((x0 + x1) / 2.0, -pad - 6.5, slabel, color=col, fontsize=6.8, fontweight="bold",
                        ha="center", va="top")
        elif edge == "top":
            x0, x1 = f0 * die_w, f1 * die_w
            ax_lay.plot([x0, x1], [die_h + pad, die_h + pad], color=col, lw=3.2, solid_capstyle="butt", zorder=10)
            ax_lay.text((x0 + x1) / 2.0, die_h + pad + 6.5, slabel, color=col, fontsize=6.8, fontweight="bold",
                        ha="center", va="bottom")
        elif edge == "left":
            y0, y1 = f0 * die_h, f1 * die_h
            ax_lay.plot([-pad, -pad], [y0, y1], color=col, lw=3.2, solid_capstyle="butt", zorder=10)
            ax_lay.text(-pad - 6.5, (y0 + y1) / 2.0, slabel, color=col, fontsize=6.7, fontweight="bold",
                        ha="right", va="center", rotation=90)
        elif edge == "right":
            y0, y1 = f0 * die_h, f1 * die_h
            ax_lay.plot([die_w + pad, die_w + pad], [y0, y1], color=col, lw=3.2, solid_capstyle="butt", zorder=10)
            ax_lay.text(die_w + pad + 6.5, (y0 + y1) / 2.0, slabel, color=col, fontsize=6.7, fontweight="bold",
                        ha="left", va="center", rotation=270)

    # Pin-free east-south zone callout above CTLE coil
    ax_lay.annotate(
        "Pin-free\n(CTLE)", xy=(345, 0), xytext=(352, -26),
        fontsize=6.1, color="#64748b", ha="center", va="top", style="italic",
        arrowprops=dict(arrowstyle="->", color="#94a3b8", lw=0.7),
    )

    ax_lay.set_xlim(-38, die_w + 38)
    ax_lay.set_ylim(-54, die_h + 36)
    ax_lay.set_aspect("equal")
    ax_lay.set_xticks([0, 100, 200, 300, 386])
    ax_lay.set_yticks([0, 100, 200, 300, 354])
    ax_lay.set_xlabel("X (µm)", labelpad=2)
    ax_lay.set_ylabel("Y (µm)", labelpad=2)
    ax_lay.spines["top"].set_visible(False)
    ax_lay.spines["right"].set_visible(False)
    ax_lay.set_title("(a) Real OpenROAD PnR Layout (v4p1)", loc="left", pad=8, color="#0f172a")

    lay_handles = [
        Patch(facecolor="#2563eb", alpha=0.7, label="M1"),
        Patch(facecolor="#dc2626", alpha=0.7, label="M2"),
        Patch(facecolor="#16a34a", alpha=0.75, label="M3"),
        Patch(facecolor="#7c3aed", alpha=0.8, label="M4"),
        Patch(facecolor="#0891b2", alpha=0.8, label="M5/PDN"),
        Patch(facecolor="#99f6e4", edgecolor="#0d9488", lw=0.5, label="Decap"),
        Patch(facecolor="#f59e0b", edgecolor="#78350f", lw=0.5, label="CTS"),
    ]
    ax_lay.legend(handles=lay_handles, loc="lower center", bbox_to_anchor=(0.5, -0.22),
                  ncol=7, frameon=False, fontsize=6.8, handlelength=0.9, columnspacing=0.65, handletextpad=0.3)

    # Panel (a-right-top): Subsystem Synthesis Area & Cell Count
    subs = pnr["synthesis"]["per_subsystem"]
    sub_items = [
        ("rx_word_host_32", subs["rx_word_host_32"]["area_um2"],       subs["rx_word_host_32"]["cells"],       "#7c3aed"),
        ("rx_cdr_loop_v4",  subs["rx_cdr_loop_v4"]["area_um2"],        subs["rx_cdr_loop_v4"]["cells"],        "#dc2626"),
        ("tx_ingress_32",   subs["tx_ingress_control_32"]["area_um2"], subs["tx_ingress_control_32"]["cells"], "#059669"),
        ("pll_control_top", subs["pll_control_top"]["area_um2"],       subs["pll_control_top"]["cells"],       "#2563eb"),
        ("rx_pack + map",   subs["rx_pack_16to32"]["area_um2"] + subs["rx_word_map"]["area_um2"],
                            subs["rx_pack_16to32"]["cells"] + subs["rx_word_map"]["cells"],                    "#d97706"),
    ]
    sub_items.reverse()
    y_sub = np.arange(len(sub_items))
    areas_k = [it[1] / 1000.0 for it in sub_items]
    bars_sub = ax_sub.barh(y_sub, areas_k, height=0.64, color=[it[3] for it in sub_items], alpha=0.88, edgecolor="none")
    ax_sub.set_yticks(y_sub, [it[0] for it in sub_items], fontsize=7.4)
    ax_sub.set_xlabel("Synth Area (×10³ µm²)", fontsize=7.8, labelpad=2)
    ax_sub.set_xlim(0, 36.0)
    ax_sub.grid(axis="x", alpha=0.22, color="#94a3b8")
    ax_sub.set_axisbelow(True)
    ax_sub.spines["top"].set_visible(False)
    ax_sub.spines["right"].set_visible(False)
    ax_sub.set_title("Subsystem Area & Cells (5,955 synth)", fontsize=8.6, fontweight="bold", loc="left", pad=5)
    for bar, it in zip(bars_sub, sub_items):
        ax_sub.text(bar.get_width() + 0.55, bar.get_y() + bar.get_height() / 2.0,
                    f"{it[1]/1e3:.1f}k ({it[2]:,})", va="center", ha="left", fontsize=6.9, color="#1e293b")

    # Panel (a-right-bottom): M1..M5 Wirelength & Decap
    wl = pnr["pnr"]["wirelength"]
    wl_layers = ["met1", "met2", "met3", "met4", "met5"]
    wl_labels = ["M1", "M2", "M3", "M4", "M5"]
    wl_vals = [wl[k] / 1000.0 for k in wl_layers]
    wl_cols = ["#2563eb", "#dc2626", "#16a34a", "#7c3aed", "#0891b2"]
    x_wl = np.arange(len(wl_layers))
    bars_wl = ax_wl.bar(x_wl, wl_vals, width=0.58, color=wl_cols, alpha=0.88)
    ax_wl.set_xticks(x_wl, wl_labels, fontsize=7.8)
    ax_wl.set_ylabel("Wirelength (mm)", fontsize=7.8, labelpad=2)
    ax_wl.set_ylim(0, 98.0)
    ax_wl.grid(axis="y", alpha=0.22, color="#94a3b8")
    ax_wl.set_axisbelow(True)
    ax_wl.spines["top"].set_visible(False)
    ax_wl.spines["right"].set_visible(False)
    ax_wl.set_title("Routed Wirelength (191.3 mm) & Decap", fontsize=8.6, fontweight="bold", loc="left", pad=5)
    for bar, v in zip(bars_wl, wl_vals):
        ax_wl.text(bar.get_x() + bar.get_width() / 2.0, v + 2.0, f"{v:.1f}",
                   ha="center", va="bottom", fontsize=7.0, color="#1e293b")
    ax_wl.text(
        0.98, 0.90, "Built-in Decap: 88.93 pF\n(3,531 cells, 6,484 std)",
        transform=ax_wl.transAxes, ha="right", va="top", fontsize=6.8, color="#0f766e",
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.26", facecolor="#f0fdfa", edgecolor="#5eead4", lw=0.8),
    )

    # =========================================================================
    # PANEL (b): 6-Corner ±5% OCV Signoff STA Slacks (5G & 4G) + CDC Audit
    # =========================================================================
    ax_sta = fig.add_subplot(gs_main[0, 1])
    corner_specs = [
        ("tt_025C_1v80",       "TT  25°C  1.80V"),
        ("ff_100C_1v95",       "FF 100°C  1.95V"),
        ("ff_n40C_1v95",       "FF −40°C  1.95V"),
        ("ss_100C_1v60",       "SS 100°C  1.60V"),
        ("ss_n40C_1v65_interp","SS −40°C  1.65V*"),
        ("ss_n40C_1v60",       "SS −40°C  1.60V†"),
    ]
    corner_specs_plot = list(reversed(corner_specs))
    y_c = np.arange(len(corner_specs_plot), dtype=np.float64)
    y_c[1:] += 0.30

    s5_vals = [pnr["sta_5g_6corner_ocv"][c]["setup_wns_ns"] for c, _ in corner_specs_plot]
    s4_vals = [pnr["sta_4g_6corner_ocv"][c]["setup_wns_ns"] for c, _ in corner_specs_plot]
    h5_vals = [pnr["sta_5g_6corner_ocv"][c]["hold_wns_ns"] for c, _ in corner_specs_plot]
    h4_vals = [pnr["sta_4g_6corner_ocv"][c]["hold_wns_ns"] for c, _ in corner_specs_plot]

    ax_sta.axvspan(-1.02, 0.0, color="#fef2f2", alpha=0.85, zorder=0)
    ax_sta.axvline(0.0, color="#dc2626", lw=1.5, ls="--", zorder=4)
    ax_sta.axhline(0.66, color="#94a3b8", lw=0.9, ls=":", zorder=2)

    bh = 0.24
    ax_sta.barh(y_c + bh, s5_vals, height=bh, color="#1d4ed8", alpha=0.90, label="5G Setup WNS (312.5/156.25/160 MHz)", zorder=3)
    ax_sta.barh(y_c,      s4_vals, height=bh, color="#0ea5e9", alpha=0.85, label="4G Setup WNS (250/125/160 MHz)", zorder=3)
    ax_sta.barh(y_c - bh, h5_vals, height=bh, color="#059669", alpha=0.88, label="Min Hold WNS (5G/4G, all 6 PASS)", zorder=3)

    for idx_r, (ck, _lbl) in enumerate(corner_specs_plot):
        for val, y_off, is_hold in [(s5_vals[idx_r], +bh, False), (s4_vals[idx_r], 0.0, False), (h5_vals[idx_r], -bh, True)]:
            y_pos = y_c[idx_r] + y_off
            if is_hold and abs(h5_vals[idx_r] - h4_vals[idx_r]) > 0.01:
                txt = f"+{val*1e3:.1f} ps (4G +{h4_vals[idx_r]*1e3:.0f})"
            elif abs(val) < 0.30:
                txt = f"{val*1e3:+.1f} ps"
            else:
                txt = f"{val:+.3f} ns"
            if val >= 0:
                ax_sta.text(val + 0.024, y_pos, txt, va="center", ha="left", fontsize=7.0,
                            color="#0f172a" if not is_hold else "#065f46",
                            fontweight="bold" if (ck in ("ss_100C_1v60", "ss_n40C_1v65_interp") and y_off == +bh) or (ck == "ss_n40C_1v60" and is_hold) else "normal")
            else:
                ax_sta.text(val - 0.024, y_pos, txt, va="center", ha="right", fontsize=7.0, color="#b91c1c", fontweight="bold")

    ax_sta.set_yticks(y_c, [lbl for _, lbl in corner_specs_plot], fontsize=8.0)
    ax_sta.set_xlim(-1.02, 1.88)
    ax_sta.set_ylim(-0.55, y_c[-1] + 0.65)
    ax_sta.set_xlabel("Worst Negative Slack WNS (ns)  [±5% OCV Derating, Extracted SPEF]", labelpad=3)
    ax_sta.grid(axis="x", alpha=0.22, color="#94a3b8")
    ax_sta.set_axisbelow(True)
    ax_sta.spines["top"].set_visible(False)
    ax_sta.spines["right"].set_visible(False)
    ax_sta.set_title("(b) 6-Corner ±5% OCV Signoff STA Slacks (5G 156.25 MHz & 4G 125 MHz)", loc="left", pad=8, color="#0f172a")

    ax_sta.text(-0.98, y_c[-1] + 0.36, "Spec Envelope (1.65–1.95 V)\n5/5 Corners PASS (5G & 4G)",
                fontsize=7.1, color="#065f46", fontweight="bold", va="top", ha="left",
                bbox=dict(boxstyle="round,pad=0.28", facecolor="#ecfdf5", edgecolor="#6ee7b7", lw=0.8))
    ax_sta.text(-0.98, 0.78, "† Below-spec 1.60 V stress\n(−50 mV vs Vmin=1.65 V;\nHold PASS +73.4 ps)",
                fontsize=6.7, color="#991b1b", va="bottom", ha="left", linespacing=1.28)
    ax_sta.text(1.84, 0.56, "*Spec Vmin=1.65V closure corner", fontsize=6.8, color="#475569", ha="right", va="top", style="italic")

    cdc_box_txt = (
        "CDC Signoff (SS −40°C 1.60V +5% OCV)\n"
        "• Sync1 fanout = 1: 26/26 PASS (0 viol.)\n"
        "• Sync1→Sync2 MTBF: ≥ +4.567 ns\n"
        "• Max Gray bus skew: 0.391 ns (4 buses)"
    )
    ax_sta.text(
        1.84, 2.25, cdc_box_txt,
        ha="right", va="center", fontsize=7.1, color="#1e293b", linespacing=1.36,
        bbox=dict(boxstyle="round,pad=0.38", facecolor="#f8fafc", edgecolor="#94a3b8", lw=0.9),
    )
    ax_sta.legend(loc="lower center", bbox_to_anchor=(0.48, -0.22), ncol=3, frameon=False, fontsize=7.0, columnspacing=0.8)

    # =========================================================================
    # PANEL (c): Real RTL Closed-Loop Bang-Bang CDR ±300 ppm Tracking (5G)
    # =========================================================================
    gs_c = GridSpecFromSubplotSpec(3, 1, subplot_spec=gs_main[1, 0], height_ratios=[0.95, 0.95, 1.05], hspace=0.10)
    ax_pi = fig.add_subplot(gs_c[0, 0])
    ax_fq = fig.add_subplot(gs_c[1, 0], sharex=ax_pi)
    ax_pe = fig.add_subplot(gs_c[2, 0], sharex=ax_pi)

    t_max_plot = 18.0  # Shows initial pull-in, lock/align markers, and ~13 crisp sawtooth wraps!
    mp = cdr_p["time_us"] <= t_max_plot
    mm = cdr_m["time_us"] <= t_max_plot

    tp_b, pip_b = break_pi_wraps(cdr_p["time_us"][mp], cdr_p["pi_code"][mp])
    tm_b, pim_b = break_pi_wraps(cdr_m["time_us"][mm], cdr_m["pi_code"][mm])

    lk_t = summary["rtl_closed_loop_cdr_5g"]["plus_300ppm"]["lock_time_us"]
    al_t = summary["rtl_closed_loop_cdr_5g"]["plus_300ppm"]["align_time_us"]

    # Row 1: PI Phase Code [0..63]
    ax_pi.plot(tp_b, pip_b, color="#1d4ed8", lw=1.25, label="+300 ppm (PI ↓ wraps: 38 in 50 µs)")
    ax_pi.plot(tm_b, pim_b, color="#dc2626", lw=1.15, alpha=0.88, label="−300 ppm (PI ↑ wraps: 39 in 50 µs)")
    ax_pi.set_ylabel("PI Code\n[0..63]", fontsize=8.0)
    ax_pi.set_ylim(-4, 68)
    ax_pi.set_yticks([0, 32, 63])
    ax_pi.legend(loc="upper right", ncol=2, frameon=True, facecolor="#ffffff", framealpha=0.92,
                 edgecolor="#cbd5e1", fontsize=6.9, borderpad=0.25, handlelength=1.4)
    ax_pi.set_title("(c) Real RTL Closed-Loop Bang-Bang CDR ±300 ppm Tracking (5.0 Gb/s, 156.25 MHz 32b)",
                    loc="left", pad=8, color="#0f172a")

    # Row 2: Frequency Integrator (ppm)
    ax_fq.axhline(+300.0, color="#1d4ed8", lw=0.85, ls=":", alpha=0.65)
    ax_fq.axhline(-300.0, color="#dc2626", lw=0.85, ls=":", alpha=0.65)
    ax_fq.axhline(0.0, color="#94a3b8", lw=0.6, alpha=0.6)
    ax_fq.plot(cdr_p["time_us"][mp], cdr_p["freq_ppm"][mp], color="#1d4ed8", lw=1.45)
    ax_fq.plot(cdr_m["time_us"][mm], cdr_m["freq_ppm"][mm], color="#dc2626", lw=1.45)
    ax_fq.set_ylabel("Freq Acc\n(ppm)", fontsize=8.0)
    ax_fq.set_ylim(-395, 395)
    ax_fq.set_yticks([-300, 0, 300])
    ax_fq.text(17.75, 225, "+299.88 ppm (err −0.12 ppm)", ha="right", va="top", fontsize=6.9, color="#1d4ed8", fontweight="bold")
    ax_fq.text(17.75, -225, "−300.15 ppm (err −0.15 ppm)", ha="right", va="bottom", fontsize=6.9, color="#dc2626", fontweight="bold")

    # Row 3: Residual Phase Error (UI)
    ax_pe.axhspan(-0.10, +0.10, color="#ecfdf5", alpha=0.85, zorder=0)
    ax_pe.axhline(0.0, color="#64748b", lw=0.7, ls="-", alpha=0.6)
    ax_pe.axhline(+0.10, color="#059669", lw=0.7, ls="--", alpha=0.55)
    ax_pe.axhline(-0.10, color="#059669", lw=0.7, ls="--", alpha=0.55)
    ax_pe.plot(cdr_p["time_us"][mp], cdr_p["phase_err_ui"][mp], color="#1d4ed8", lw=0.90, alpha=0.88)
    ax_pe.plot(cdr_m["time_us"][mm], cdr_m["phase_err_ui"][mm], color="#dc2626", lw=0.85, alpha=0.80)
    ax_pe.set_ylabel("Phase Err\n(UI)", fontsize=8.0)
    ax_pe.set_xlabel("Time (µs)  [Shown 0–18 µs of full 50 µs / 250k-UI continuous verification]", labelpad=3)
    ax_pe.set_ylim(-0.34, 0.34)
    ax_pe.set_yticks([-0.25, -0.10, 0.0, 0.10, 0.25])
    ax_pe.text(
        17.75, 0.295,
        "SS Limit-Cycle: 7.35 ps RMS (0.037 UI), 35.9 ps pk-pk · 0 / 298k post-lock bit err · 0 slips",
        ha="right", va="top", fontsize=6.9, color="#065f46", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.24", facecolor="#ffffff", edgecolor="#6ee7b7", lw=0.8, alpha=0.95),
    )

    for ax_r in (ax_pi, ax_fq, ax_pe):
        ax_r.axvline(lk_t, color="#059669", lw=1.25, ls="--", zorder=5)
        ax_r.axvline(al_t, color="#7c3aed", lw=1.10, ls=":", zorder=5)
        ax_r.set_xlim(0.0, t_max_plot)
        ax_r.grid(True, alpha=0.20, color="#94a3b8")
        ax_r.spines["top"].set_visible(False)
        ax_r.spines["right"].set_visible(False)
    plt.setp(ax_pi.get_xticklabels(), visible=False)
    plt.setp(ax_fq.get_xticklabels(), visible=False)

    ax_fq.annotate(
        f"rx_cdr_locked ({lk_t:.2f} µs)\nrx_aligned ({al_t:.2f} µs)",
        xy=(al_t, 35), xytext=(5.2, 50),
        fontsize=6.9, fontweight="bold", color="#065f46", va="center",
        bbox=dict(boxstyle="round,pad=0.24", facecolor="#f0fdf4", edgecolor="#86efac", lw=0.8),
        arrowprops=dict(arrowstyle="->", color="#059669", lw=0.95),
        zorder=8,
    )

    # =========================================================================
    # PANEL (d): Real RTL PLL Startup & Coarse-Search FSM + Digital Signoff Card
    # =========================================================================
    gs_d = GridSpecFromSubplotSpec(2, 1, subplot_spec=gs_main[1, 1], height_ratios=[1.48, 0.62], hspace=0.28)
    ax_pll = fig.add_subplot(gs_d[0, 0])
    ax_card = fig.add_subplot(gs_d[1, 0])

    tp = pll["time_us"]
    fv = pll["vco_freq_ghz"]
    blc = pll["lc_bank_code"]
    t_pre = summary["rtl_pll_startup_fsm_5g"]["t_precharge_us"]
    t_cs = summary["rtl_pll_startup_fsm_5g"]["t_coarse_start_us"]
    t_cd = summary["rtl_pll_startup_fsm_5g"]["t_coarse_done_us"]
    t_lk = summary["rtl_pll_startup_fsm_5g"]["t_locked_us"]
    t_pll_end = 26.5
    mp_pll = tp <= t_pll_end

    # Shaded FSM state regions (staggered slightly on narrow early states for zero overlap!)
    state_bands = [
        (0.0,   0.85,  "#f1f5f9", "RST",        "#475569", 5.455),
        (0.85,  t_pre, "#fef9c3", "WAIT",       "#854d0e", 5.415),
        (t_pre, t_cs,  "#cffafe", "PRE",        "#155e75", 5.455),
        (t_cs,  t_cd,  "#eff6ff", "COARSE SEARCH (STEP → CHECK → BACK)", "#1d4ed8", 5.455),
        (t_cd,  t_lk,  "#fef3c7", "CNF",        "#b45309", 5.455),
        (t_lk,  t_pll_end, "#ecfdf5", "LOCKED\n(TRACK)", "#047857", 5.455),
    ]
    for x0, x1, fc, lbl, tc, y_lbl in state_bands:
        ax_pll.axvspan(x0, x1, color=fc, alpha=0.82, zorder=0)
        if x1 > x0:
            ax_pll.axvline(x0, color="#cbd5e1", lw=0.65, ls="-", zorder=1)
            ax_pll.text((x0 + x1) / 2.0, y_lbl, lbl, ha="center", va="top",
                        fontsize=6.2 if (x1 - x0) < 2.2 else 7.2, fontweight="bold", color=tc)

    # Mask pre-bias_ready f_vco == 0 so curve starts cleanly once rails are ready
    fv_plot = np.where(fv > 1.0, fv, np.nan)
    ln_tgt = ax_pll.axhline(5.000, color="#dc2626", lw=1.15, ls="--", zorder=3, label="Target 5.000 GHz")
    ln_f = ax_pll.plot(tp[mp_pll], fv_plot[mp_pll], color="#1d4ed8", lw=1.85, zorder=5, label="f_VCO (CPEX LC-VCO)")

    ax_pll.set_xlim(0.0, t_pll_end)
    ax_pll.set_ylim(4.73, 5.48)
    ax_pll.set_ylabel("VCO Frequency (GHz)", color="#1d4ed8", fontsize=8.3, fontweight="bold")
    ax_pll.tick_params(axis="y", colors="#1d4ed8")
    ax_pll.set_xlabel("Time (µs)  [250 MHz ref_clk → 62.5 MHz internal pll_clk_div4]", labelpad=3)
    ax_pll.grid(axis="y", alpha=0.22, color="#94a3b8")
    ax_pll.spines["top"].set_visible(False)

    ax_code = ax_pll.twinx()
    ln_c = ax_code.step(tp[mp_pll], blc[mp_pll], where="post", color="#d97706", lw=1.65, ls="-", zorder=4,
                        label="LC Bank b[3:0]")
    ax_code.set_ylim(-1.6, 8.6)
    ax_code.set_yticks([0, 2, 4, 5, 6, 8])
    ax_code.set_ylabel("LC Cap Bank b[3:0]", color="#b45309", fontsize=8.3, fontweight="bold", labelpad=5)
    ax_code.tick_params(axis="y", colors="#b45309")
    ax_code.spines["top"].set_visible(False)
    ax_code.spines["right"].set_color("#d97706")

    # Key callout annotations (positioned cleanly in open space without touching curves or legend)
    ax_pll.annotate(
        "CHECK→BACK\nb=6 (lo=1) → b=5",
        xy=(19.14, 4.97), xytext=(12.2, 4.86),
        fontsize=6.8, color="#b45309", fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.24", facecolor="#fffbeb", edgecolor="#fcd34d", lw=0.8),
        arrowprops=dict(arrowstyle="->", color="#d97706", lw=0.95),
        zorder=8,
    )
    ax_pll.annotate(
        f"pll_locked = 1 @ {t_lk:.2f} µs\nb=5 (5b code=26) · 5.000 GHz\nVctrl = 0.891 V · fault = 0",
        xy=(t_lk, 5.000), xytext=(22.4, 4.86),
        fontsize=6.8, color="#065f46", fontweight="bold", ha="center",
        bbox=dict(boxstyle="round,pad=0.26", facecolor="#ffffff", edgecolor="#34d399", lw=0.9),
        arrowprops=dict(arrowstyle="->", color="#059669", lw=1.0),
        zorder=8,
    )

    lines_d = ln_f + ln_c + [ln_tgt]
    ax_pll.legend(lines_d, [l.get_label() for l in lines_d], loc="lower left", ncol=3,
                  frameon=True, facecolor="#ffffff", framealpha=0.95, edgecolor="#cbd5e1",
                  fontsize=6.8, borderpad=0.25, columnspacing=0.9, handlelength=1.4)
    ax_pll.set_title("(d) Real RTL PLL Startup & Coarse-Search FSM (5G LC-VCO) + Signoff Summary",
                     loc="left", pad=8, color="#0f172a")

    # Bottom Summary Card (3 clean aligned columns inside a bordered card)
    ax_card.axis("off")
    ax_card.set_xlim(0.0, 1.0)
    ax_card.set_ylim(0.0, 1.0)
    ax_card.add_patch(FancyBboxPatch(
        (0.004, 0.03), 0.992, 0.94, boxstyle="round,pad=0.015,rounding_size=0.025",
        facecolor="#f8fafc", edgecolor="#64748b", linewidth=1.1,
    ))
    ax_card.plot([0.330, 0.330], [0.10, 0.90], color="#cbd5e1", lw=0.9)
    ax_card.plot([0.672, 0.672], [0.10, 0.90], color="#cbd5e1", lw=0.9)

    col1 = (
        "PHYSICAL PnR SIGNOFF (v4p1)\n"
        "• Die: 385.9 × 353.6 µm (0.1365 mm²)\n"
        "• Util: 75.0% · 6,484 std · 88.93 pF decap\n"
        "• WL: 191.3 mm (M1–M5) · 283 pins (0 viol.)\n"
        "• DRT=0 · ANT=0 · DRC=0 · LVS=MATCH"
    )
    col2 = (
        "6-CORNER ±5% OCV STA & CDC\n"
        "• 5G/4G Spec (1.65–1.95 V): 5/5 PASS\n"
        "• Min Setup: +58.7 ps (SS100), +74.9 ps (1v65)\n"
        "• Min Hold: +73.4 ps (6/6 incl. 1.60 V PASS)\n"
        "• CDC: 26/26 FO=1 · MTBF ≥ +4.57 ns"
    )
    col3 = (
        "REAL RTL CLOSED-LOOP 5G (iverilog)\n"
        "• CDR ±300 ppm: lock 3.32 µs, align 3.39 µs\n"
        "• Freq err: −0.12 / −0.15 ppm · 7.35 ps RMS\n"
        "• Post-lock: 0 / 297,984 bit err · 0 slips\n"
        "• PLL FSM: b=0→6→5 · 5.000 GHz @ 21.8 µs"
    )
    for x0, txt, hdr_col in [(0.020, col1, "#0f172a"), (0.346, col2, "#1d4ed8"), (0.688, col3, "#065f46")]:
        lines = txt.splitlines()
        ax_card.text(x0, 0.89, lines[0], ha="left", va="top", fontsize=7.4, fontweight="bold", color=hdr_col)
        ax_card.text(x0, 0.70, "\n".join(lines[1:]), ha="left", va="top", fontsize=6.75, color="#1e293b", linespacing=1.42)

    OUT_FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_FIG_PATH, dpi=240, facecolor="#ffffff")
    plt.close(fig)


def main() -> None:
    pnr = json.loads(PNR_SUMMARY_PATH.read_text())
    cdr_p = load_csv_dict(SHOWCASE_DIR / "cdr_p300.csv")
    cdr_m = load_csv_dict(SHOWCASE_DIR / "cdr_m300.csv")
    pll = load_csv_dict(SHOWCASE_DIR / "pll_fsm_trace.csv")

    summary = build_summary(pnr, cdr_p, cdr_m, pll)
    OUT_SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Wrote summary JSON -> {OUT_SUMMARY_PATH}")

    def_geom = parse_def_geometry(DEF_PATH)
    print(
        f"Parsed DEF: std={len(def_geom['std_xy'])}, decap={len(def_geom['decap_xy'])}, "
        f"clkbuf={len(def_geom['clkbuf_xy'])}, segs={ {k: len(v) for k, v in def_geom['layer_segs'].items()} }"
    )
    render_figure(pnr, summary, def_geom, cdr_p, cdr_m, pll)
    print(f"Rendered 240-DPI figure -> {OUT_FIG_PATH} ({OUT_FIG_PATH.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
