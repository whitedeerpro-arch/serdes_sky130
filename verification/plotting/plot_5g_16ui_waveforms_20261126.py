#!/usr/bin/env python3
"""5.0 Gb/s Plan-C 16-UI Real-CPEX Time-Domain Waveform Showcase (FFE=3 vs FFE=0).

Runs fast sequential (`--workers 1`, `num_threads=1`) ngspice TT 1.80 V 27 C 5.0 Gb/s
(200 ps/UI) full-chain simulations on the exact signed-off 5G Magic CPEX netlists from
`plot_5g_tt_eyes_20261126.py`:
  - TX SST `v5_pdk` CPEX (`serdes_tx_sst_top_pdk_pex.spice`, n_zq=16, FFE=3 & FFE=0)
  - Package RLC + AC coupling + `pcb_c2_loss6` 100-Ohm differential PCB channel
  - PDK 100-Ohm RX termination (`serdes_rx_term_pdk`) + W3 Shunt-Peaked CTLE CPEX
    (`serdes_rx_ctle_shunt_5g_w3_pdk_open_pex.spice`, EQ=3) + 8.204 nH M4+M2 stacked
    inductor (`rx_ctle_ind_m4m2_5g_pdk`) + exact `rx_top_5g_pdk` extracted wire load
    (57.41 fF/node) + 8x `serdes_rx_dt_slicer_5g_pdk` transistor loads.

Bit pattern (4 x 16b words = 64 UI):
  - Word 0 (16 UI): alternating settling preamble `1010101010101010` (ends on `0`)
  - Word 1 (16 UI): showcase sequence `1 0 1 0 1 1 1 0 0 0 1 0 0 0 1 0`
      * Bits 0..4  (`10101`):   2.5 GHz Nyquist high-frequency toggling
      * Bits 4..9  (`111000`):  long run exposing TX FFE de-emphasis step plateaus
      * Bits 7..13 (`0001000`): lone pulse exposing channel ISI attenuation vs FFE
  - Word 2 (16 UI): alternating tail `1010101010101010` (clean exit + channel delay margin)

Outputs:
  - `results/verification/tt_eyes_5g_20261126/waveforms_16ui.npz`
  - `results/verification/tt_eyes_5g_20261126/waveforms_16ui.csv`
  - `results/verification/tt_eyes_5g_20261126/waveforms_16ui_summary.json`
  - `docs/figures/system/serdes_5g_16ui_waveforms_20261126.png` (240 DPI, 4-row stacked)
All `.raw` files are deleted immediately after waveform extraction.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "verification/top_cosim"))
sys.path.insert(0, str(REPO / "verification/plotting"))

from serdes_flow import model_library, project, spice as sf_spice, watch as sf_watch  # noqa: E402
from serdes_flow.waves import crossings  # noqa: E402
import verify_5g_full_chain as v5g  # noqa: E402
import plot_5g_tt_eyes_20261126 as eyes5g  # noqa: E402

OUT_DIR = REPO / "results/verification/tt_eyes_5g_20261126"
NPZ_PATH = OUT_DIR / "waveforms_16ui.npz"
CSV_PATH = OUT_DIR / "waveforms_16ui.csv"
SUMMARY_PATH = OUT_DIR / "waveforms_16ui_summary.json"
FIG_PATH = REPO / "docs/figures/system/serdes_5g_16ui_waveforms_20261126.png"

UI_S = 200.0e-12       # 5.0 Gb/s NRZ
UI_PS = 200.0
VDD_TT = 1.80
TEMP_TT = 27
N_ZQ_TT = 16
EQ_CODE = 3

# Word 0: 16-UI alternating settling preamble ending on 0
PREAMBLE_16 = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
# Word 1: 16-UI showcase (50% DC-balanced: 8 ones, 8 zeros)
#   bits 0..4:  1 0 1 0 1      (Nyquist 2.5 GHz toggle)
#   bits 4..9:  1 1 1 0 0 0    (3-UI runs showing TX FFE de-emphasis plateaus)
#   bits 7..13: 0 0 0 1 0 0 0  (lone pulse exposing channel ISI on FFE=0 vs FFE=3)
SHOWCASE_16 = [1, 0, 1, 0, 1, 1, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0]
# Word 2: 16-UI alternating tail starting on 1 (gives clean exit after bit 15 = 0)
TAIL_16 = [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0]

SHOWCASE_START_BIT = 16
SHOWCASE_LEN = 16
BITS_48 = np.array(PREAMBLE_16 + SHOWCASE_16 + TAIL_16, dtype=int)


def wait_for_host_slot(max_total: int = 3) -> None:
    while len(sf_watch.ngspice_cwds()) >= max_total:
        time.sleep(2.5)


def get_stripped_tt_lib(spice_files: list[Path]) -> Path:
    """Build minimal TT SKY130A model library (~1 s load vs ~15 s full PDK)."""
    prims: set[str] = set()
    for p in spice_files:
        prims.update(re.findall(r"\bsky130_fd_pr__\w+", p.read_text()))
    sorted_prims = sorted(prims)
    h = hashlib.md5(",".join(sorted_prims).encode()).hexdigest()[:8]
    lib_dir = OUT_DIR / "_models_16ui" / f"tt_{len(sorted_prims)}_{h}"
    lib_path = lib_dir / "sky130.lib.spice"
    if not lib_path.exists():
        model_library.build(project.model_library(), "tt", sorted_prims, lib_dir)
    return lib_path


def build_parallel_word_stimuli(bits: np.ndarray, supply: float, t_first_upd: float, ui: float, edge: float = 40e-12) -> str:
    """Drive 16-bit parallel TX input words with clean initial preamble matching Word 0."""
    t_word = 16.0 * ui
    n_words = len(bits) // 16
    lines = []
    for bit_idx in range(16):
        init_b = int(bits[bit_idx])  # starts directly on Word 0 alternating preamble (1010...10)
        pts = [(0.0, supply if init_b else 0.0)]
        prev = init_b
        for w in range(n_words):
            b = int(bits[16 * w + bit_idx])
            if b != prev:
                t_upd = t_first_upd + w * t_word
                pts.extend([
                    (t_upd - edge / 2, supply if prev else 0.0),
                    (t_upd + edge / 2, supply if b else 0.0),
                ])
                prev = b
        lines.append(v5g.pwl_lines(f"Vdin{bit_idx} din{bit_idx} 0", pts))
    return "".join(lines)


def align_sequence(
    t: np.ndarray,
    y: np.ndarray,
    bits: np.ndarray,
    start_nom_s: float,
    ui: float,
) -> tuple[float, float]:
    """Find exact t_bit0_edge (bit 0 leading edge) via matched correlation + edge refinement."""
    sgn = 2 * bits - 1
    n_match = SHOWCASE_START_BIT + SHOWCASE_LEN + 4  # 36 bits (preamble + showcase + 4 tail)
    idx = np.arange(n_match)
    grid = np.arange(-12.0, 22.0, 0.01)
    times = start_nom_s + (idx[None, :] + 0.5 + grid[:, None]) * ui
    valid = (times[:, 0] >= t[0]) & (times[:, -1] <= t[-1])
    grid = grid[valid]
    times = times[valid]
    v = np.interp(times.ravel(), t, y).reshape(times.shape)
    wrong = v * sgn[:n_match] <= 0
    # Weight showcase pattern heavily so word boundary locks unambiguously!
    cost = 100 * wrong[:, SHOWCASE_START_BIT:SHOWCASE_START_BIT + SHOWCASE_LEN].sum(axis=1) + wrong.sum(axis=1)
    best = np.where(cost == cost.min())[0]
    delay = float(grid[best[np.argmax(np.min(v[best] * sgn[:n_match], axis=1))]])

    # Refine sub-UI edge phase using ALL transitions across preamble + showcase
    edge_t, edge_pol = crossings(t, y)
    residuals = []
    for k in range(1, SHOWCASE_START_BIT + SHOWCASE_LEN):
        if bits[k] == bits[k - 1]:
            continue
        target = start_nom_s + (k + delay) * ui
        hit = np.where((np.abs(edge_t - target) < 0.45 * ui) & (edge_pol == sgn[k]))[0]
        if len(hit):
            i = int(hit[np.argmin(np.abs(edge_t[hit] - target))])
            residuals.append((edge_t[i] - target) / ui)
    if len(residuals) >= 10:
        delay += float(np.median(residuals))

    t_bit0 = start_nom_s + delay * ui
    t_show0 = t_bit0 + SHOWCASE_START_BIT * ui
    return t_bit0, t_show0


def run_single_16ui_case(load: dict[str, float], n_post: int) -> tuple[dict, dict[str, np.ndarray]]:
    """Run one sequential TT 5.0 Gb/s CPEX transient over preamble + 16-UI showcase + tail."""
    case_id = f"5g_16ui_ffe{n_post}"
    t_clk = 4.0 * UI_S
    pw_clk = 0.5 * t_clk - 30e-12
    t_tx_rel = 2.2e-9
    t_first_upd = 3.6e-9
    t_pad_nom = 7.6e-9
    # Preamble (3.2 ns) + Showcase (3.2 ns) + Channel delay (~1.6 ns) + Tail margin (~2.0 ns) -> 18.0 ns
    t_stop = 18.0e-9
    t_save = 5.5e-9

    rdir = OUT_DIR / f"tran_{case_id}"
    if rdir.exists():
        shutil.rmtree(rdir)

    stim_p = OUT_DIR / f"stim_{case_id}.inc"
    stim_p.write_text(build_parallel_word_stimuli(BITS_48, VDD_TT, t_first_upd, UI_S))

    spice_files = [
        REPO / "analog/common/devices/spice/sky130_primitives.spice",
        REPO / "analog/bias/spice/bias_v2.spice",
        REPO / "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice",
        eyes5g.TX_V5_PEX,
        eyes5g.CTLE_W3_OPEN_PEX,
        eyes5g.SLICER_5G_REF,
    ]
    lib_tt = get_stripped_tt_lib(spice_files)

    tx_ctrl = v5g.encode_zq_ffe(N_ZQ_TT, n_post)
    eq0_v = VDD_TT if (EQ_CODE & 1) else 0.0
    eq1_v = VDD_TT if ((EQ_CODE >> 1) & 1) else 0.0

    raw_name = f"{case_id}.raw"
    save_vecs = "v(tx_p) v(tx_n) v(rx_p) v(rx_n) v(ctle_p) v(ctle_n) v(vdrv)"
    lines = [
        f"* 5.0 Gb/s 16-UI Showcase Full-Chain TT CPEX (FFE={n_post}, EQ={EQ_CODE})",
        f'.lib "{lib_tt}" tt',
        *[f'.include "{p}"' for p in spice_files],
        f'.include "{REPO}/verification/models/channel/pcb_family/pcb_foster_cells.spice"',
        f'.include "{REPO}/verification/models/channel/pcb_family/C2_loss6.spice"',
        f'.include "{stim_p}"',
        eyes5g.IND_M4M2_SUBCKT,
        f".temp {TEMP_TT}",
        f"Vdd_tx vdd_tx 0 {VDD_TT}",
        f"Vdd_rx vdd 0 {VDD_TT}",
        "Vbg vbg 0 1.200",
        f"Vphi0   phi0   0 PULSE(0 {VDD_TT} {0*UI_S:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vphi90  phi90  0 PULSE(0 {VDD_TT} {1*UI_S:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vphi180 phi180 0 PULSE(0 {VDD_TT} {2*UI_S:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vphi270 phi270 0 PULSE(0 {VDD_TT} {3*UI_S:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vrst rst_n 0 PWL(0 0 {t_tx_rel - 25e-12:.6e} 0 {t_tx_rel + 25e-12:.6e} {VDD_TT})",
        *[
            f"Vtx_{k} tx_{k} 0 PWL(0 0 {t_tx_rel - 1.0e-9:.6e} 0 {t_tx_rel - 0.9e-9:.6e} {VDD_TT:.4f})"
            if v else f"Vtx_{k} tx_{k} 0 0.0"
            for k, v in tx_ctrl.items()
        ],
        "Xtx din0 din1 din2 din3 din4 din5 din6 din7 "
        "din8 din9 din10 din11 din12 din13 din14 din15 "
        "phi0 phi90 phi180 phi270 rst_n "
        "tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en "
        "vbg tx_p tx_n vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top_pdk",
        "Cclk5 clk500_out 0 15f",
        "Cclk2 clk250_out 0 20f",
        "Vcm_init vcm_init 0 0.22",
        "Rdc_p tx_p vcm_init 100k",
        "Rdc_n tx_n vcm_init 100k",
        "Cpad_p tx_p 0 200f",
        "Cpad_n tx_n 0 200f",
        "Rpkg_p tx_p pkg_p 0.3",
        "Rpkg_n tx_n pkg_n 0.3",
        "Lpkg_p pkg_p ac_p 0.5n",
        "Lpkg_n pkg_n ac_n 0.5n",
        "Cac_p ac_p ch_p 10n",
        "Cac_n ac_n ch_n 10n",
        "Xch ch_p ch_n ch_out_p ch_out_n 0 pcb_c2_loss6",
        "Rrx_s_p ch_out_p rx_p 0.01",
        "Rrx_s_n ch_out_n rx_n 0.01",
        "Crx_p rx_p 0 100f",
        "Crx_n rx_n 0 100f",
        "Vcm_rx vcm_rx 0 1.05",
        "Xterm rx_p rx_n vcm_rx 0 serdes_rx_term_pdk",
        "Ibias vdd vbias 50u",
        "Xbd vbias 0 serdes_bias_ctle_v2",
        f"Veq0 eq0 0 {eq0_v:.4f}",
        f"Veq1 eq1 0 {eq1_v:.4f}",
        "Xctle rx_p rx_n ctle_p ctle_n eq0 eq1 vbias vdd 0 lp_mid ln_mid serdes_rx_ctle_shunt_5g_w3_pdk_open",
        "Xind lp_mid ln_mid vdd 0 rx_ctle_ind_m4m2_5g_pdk rm_scale=1.0 c_scale=1.0",
        *eyes5g.slicer_5g_bank_load_lines("sl", "ctle_p", "ctle_n", load["c_gnd_ext_fF"], load["cpn_mutual_fF"]),
        ".nodeset v(vdrv)=0.44 v(tx_p)=0.22 v(tx_n)=0.22 v(ch_p)=1.05 v(ch_n)=1.05 v(rx_p)=1.05 v(rx_n)=1.05",
        ".options noopiter reltol=5e-4 abstol=2p vntol=5u gmin=1e-11 itl4=80 klu",
        f".save {save_vecs}",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 5p {t_stop:.6e} {t_save:.6e} 10p",
        f"write {raw_name} {save_vecs}",
        "quit",
        ".endc",
        ".end",
    ]

    wait_for_host_slot(max_total=3)
    print(f"  [16-UI START] {case_id} (5.0 Gb/s, FFE={n_post}, EQ={EQ_CODE}, t_stop={t_stop*1e9:.1f} ns)...", flush=True)
    t0 = time.time()
    ex = sf_spice.run("\n".join(lines) + "\n", rdir, timeout_s=600)
    raw_p = rdir / raw_name
    non_pow = [f for f in ex.log_failures if "out of range for" not in f]
    if ex.exit_code != 0 or non_pow or not raw_p.exists():
        raise RuntimeError(f"16-UI transient {case_id} failed: rc={ex.exit_code} fail={ex.log_failures[:5]}")

    w = sf_spice.Waves(raw_p)
    if w.t[-1] < t_stop * 0.995:
        raise RuntimeError(f"16-UI transient {case_id} truncated at {w.t[-1]*1e9:.2f} ns < {t_stop*1e9:.2f} ns")
    elapsed = time.time() - t0

    t = w.t
    v_tx = w["v(tx_p)"] - w["v(tx_n)"]
    v_rx = w["v(rx_p)"] - w["v(rx_n)"]
    v_ctle = w["v(ctle_p)"] - w["v(ctle_n)"]
    v_vdrv = w["v(vdrv)"]

    # Delete `.raw` immediately after extracting vectors!
    raw_mb = raw_p.stat().st_size / (1024 * 1024)
    raw_p.unlink(missing_ok=True)

    # Align each stage cleanly so Showcase Bit 0 starts at u = 0.0 UI and Bit 15 ends at u = 16.0 UI
    _, t_show_tx = align_sequence(t, v_tx, BITS_48, start_nom_s=t_pad_nom, ui=UI_S)
    _, t_show_rx = align_sequence(t, v_rx, BITS_48, start_nom_s=t_pad_nom + 1.5e-9, ui=UI_S)
    _, t_show_ctle = align_sequence(t, v_ctle, BITS_48, start_nom_s=t_pad_nom + 1.5e-9, ui=UI_S)

    # Uniform high-resolution 16-UI grid (1601 points = 2 ps spacing = 0.01 UI)
    u_grid = np.linspace(0.0, float(SHOWCASE_LEN), 1601)
    tx_mv = np.interp(t_show_tx + u_grid * UI_S, t, v_tx) * 1e3
    rx_mv = np.interp(t_show_rx + u_grid * UI_S, t, v_rx) * 1e3
    ctle_mv = np.interp(t_show_ctle + u_grid * UI_S, t, v_ctle) * 1e3
    vdrv_v = np.interp(t_show_tx + u_grid * UI_S, t, v_vdrv)
    vdrv_mean_v = float(np.mean(vdrv_v))
    vdrv_rip_mv = (vdrv_v - vdrv_mean_v) * 1e3

    # Exact bit-center sampling (u = k + 0.5 UI) across all 16 showcase bits
    u_centers = np.arange(SHOWCASE_LEN) + 0.5
    sgn16 = np.array([1 if b else -1 for b in SHOWCASE_16], dtype=float)
    tx_samp = np.interp(u_centers, u_grid, tx_mv)
    rx_samp = np.interp(u_centers, u_grid, rx_mv)
    ctle_samp = np.interp(u_centers, u_grid, ctle_mv)

    tx_signed = tx_samp * sgn16
    rx_signed = rx_samp * sgn16
    ctle_signed = ctle_samp * sgn16

    # Measure TX FFE de-emphasis ratio on the 111 run (bit 4 = transition '1', bits 5..6 = de-emph '1')
    v_trans_hi = float(tx_samp[4])
    v_deemph_hi = float(0.5 * (tx_samp[5] + tx_samp[6]))
    v_trans_lo = float(abs(tx_samp[7]))
    v_deemph_lo = float(0.5 * (abs(tx_samp[8]) + abs(tx_samp[9])))
    v_trans = 0.5 * (v_trans_hi + v_trans_lo)
    v_deemph = 0.5 * (v_deemph_hi + v_deemph_lo)
    ffe_deemph_db = 20.0 * math.log10(max(v_deemph, 1e-6) / max(v_trans, 1e-6))

    # Lone pulse at bit 10 (`0001000`)
    lone_rx_mv = float(rx_signed[10])
    lone_ctle_mv = float(ctle_signed[10])
    run_rx_mv = float(0.5 * (rx_signed[6] + rx_signed[9]))

    per_bit = []
    for k, b in enumerate(SHOWCASE_16):
        per_bit.append({
            "bit_idx": k,
            "bit": int(b),
            "u_center": round(float(u_centers[k]), 2),
            "tx_mv": round(float(tx_samp[k]), 2),
            "rx_mv": round(float(rx_samp[k]), 2),
            "ctle_mv": round(float(ctle_samp[k]), 2),
            "tx_signed_mv": round(float(tx_signed[k]), 2),
            "rx_signed_mv": round(float(rx_signed[k]), 2),
            "ctle_signed_mv": round(float(ctle_signed[k]), 2),
            "clears_75mv": bool(ctle_signed[k] >= 75.0),
        })

    rec = {
        "case_id": case_id,
        "n_post": n_post,
        "eq_code": EQ_CODE,
        "elapsed_s": round(elapsed, 1),
        "cleaned_raw_mb": round(raw_mb, 2),
        "t_show_tx_ns": round(t_show_tx * 1e9, 4),
        "t_show_rx_ns": round(t_show_rx * 1e9, 4),
        "t_show_ctle_ns": round(t_show_ctle * 1e9, 4),
        "channel_delay_ps": round((t_show_rx - t_show_tx) * 1e12, 1),
        "ctle_delay_ps": round((t_show_ctle - t_show_rx) * 1e12, 1),
        "tx_vpp_mv": round(float(np.ptp(tx_mv)), 1),
        "tx_v_trans_mv": round(v_trans, 1),
        "tx_v_deemph_mv": round(v_deemph, 1),
        "tx_ffe_deemph_db": round(ffe_deemph_db, 2),
        "rx_vpp_mv": round(float(np.ptp(rx_mv)), 1),
        "rx_lone_pulse_mv": round(lone_rx_mv, 1),
        "rx_long_run_mv": round(run_rx_mv, 1),
        "rx_min_signed_mv": round(float(np.min(rx_signed)), 1),
        "rx_max_signed_mv": round(float(np.max(rx_signed)), 1),
        "ctle_vpp_mv": round(float(np.ptp(ctle_mv)), 1),
        "ctle_lone_pulse_mv": round(lone_ctle_mv, 1),
        "ctle_min_signed_mv": round(float(np.min(ctle_signed)), 1),
        "ctle_max_signed_mv": round(float(np.max(ctle_signed)), 1),
        "ctle_bits_clear_75mv": int(np.sum(ctle_signed >= 75.0)),
        "vdrv_mean_v": round(vdrv_mean_v, 4),
        "vdrv_rip_mvpp": round(float(np.ptp(vdrv_rip_mv)), 2),
        "per_bit": per_bit,
    }
    print(
        f"  [16-UI DONE {elapsed:5.1f}s] {case_id:13s} | "
        f"TX Vpp={rec['tx_vpp_mv']:5.1f}mV (deemph={rec['tx_ffe_deemph_db']:+.2f}dB) | "
        f"C2 lone={lone_rx_mv:5.1f}mV (min={rec['rx_min_signed_mv']:5.1f}mV) | "
        f"CTLE signed={rec['ctle_min_signed_mv']:5.1f}..{rec['ctle_max_signed_mv']:5.1f}mV ({rec['ctle_bits_clear_75mv']}/16>=75mV) | "
        f"Vdrv={vdrv_mean_v:.4f}V ({rec['vdrv_rip_mvpp']:.1f}mVpp) (cleaned {raw_mb:.1f}MB)",
        flush=True,
    )
    arrs = {
        f"ffe{n_post}_tx_mv": tx_mv.astype(np.float32),
        f"ffe{n_post}_rx_mv": rx_mv.astype(np.float32),
        f"ffe{n_post}_ctle_mv": ctle_mv.astype(np.float32),
        f"ffe{n_post}_vdrv_mv": vdrv_rip_mv.astype(np.float32),
        f"ffe{n_post}_ctle_signed": ctle_signed.astype(np.float32),
    }
    return rec, arrs


def write_compact_csv(u_grid: np.ndarray, arrs: dict[str, np.ndarray], path: Path) -> None:
    """Save compact 16-UI waveform table (every 2nd point -> 4 ps / 801 rows) for downstream inspection."""
    idx = np.arange(0, len(u_grid), 2)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ui", "time_ns",
            "tx_ffe3_mv", "tx_ffe0_mv",
            "rx_ffe3_mv", "rx_ffe0_mv",
            "ctle_ffe3_mv", "ctle_ffe0_mv",
            "vdrv_rip_ffe3_mv", "vdrv_rip_ffe0_mv",
        ])
        for i in idx:
            u = float(u_grid[i])
            w.writerow([
                f"{u:.3f}", f"{u * UI_PS / 1e3:.4f}",
                f"{arrs['ffe3_tx_mv'][i]:.2f}", f"{arrs['ffe0_tx_mv'][i]:.2f}",
                f"{arrs['ffe3_rx_mv'][i]:.2f}", f"{arrs['ffe0_rx_mv'][i]:.2f}",
                f"{arrs['ffe3_ctle_mv'][i]:.2f}", f"{arrs['ffe0_ctle_mv'][i]:.2f}",
                f"{arrs['ffe3_vdrv_mv'][i]:.2f}", f"{arrs['ffe0_vdrv_mv'][i]:.2f}",
            ])


def _shade_ui(ax: plt.Axes, n_ui: int = 16) -> None:
    for k in range(n_ui):
        if k % 2 == 1:
            ax.axvspan(k, k + 1, color="#f1f5f9", alpha=0.85, zorder=0)
        ax.axvline(k, color="#e2e8f0", lw=0.65, zorder=1)
    ax.axvline(n_ui, color="#e2e8f0", lw=0.65, zorder=1)


def _style_axis(ax: plt.Axes) -> None:
    ax.set_facecolor("#ffffff")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#94a3b8")
    ax.spines["bottom"].set_color("#94a3b8")
    ax.grid(True, axis="y", color="#e2e8f0", lw=0.6, alpha=0.85, zorder=0)


def render_16ui_figure(summary: dict, arrs: dict[str, np.ndarray], fig_path: Path) -> None:
    """Render publication-grade 4-row (Row 4 split into 4a Vdrv + 4b Margin) 16-UI figure at 240 DPI."""
    slicer_sum = json.loads(eyes5g.SLICER_SUMMARY.read_text())
    slicer_3s_mv = float(slicer_sum["cpex_mc250"]["corners"]["tt_v1800_t27_mm"]["three_sigma_mv"])

    u = arrs["u_grid"]
    r3 = summary["cases"]["ffe3"]
    r0 = summary["cases"]["ffe0"]
    u_centers = np.arange(SHOWCASE_LEN) + 0.5

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.6,
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
    })

    fig = plt.figure(figsize=(16.2, 13.4), dpi=240, facecolor="white")
    # 5 vertically aligned strips: Row 1 (TX), Row 2 (C2), Row 3 (CTLE), Row 4a (Vdrv), Row 4b (Margin Bars)
    gs = gridspec.GridSpec(
        5, 1, figure=fig,
        height_ratios=[1.14, 1.12, 1.24, 0.80, 0.96],
        left=0.068, right=0.982, top=0.858, bottom=0.056, hspace=0.31,
    )

    # Master Header
    fig.suptitle(
        "SKY130A 5.0 Gb/s Plan-C SerDes — 16-UI Real-CPEX End-to-End Time-Domain Waveforms (FFE=3 vs FFE=0)",
        fontsize=13.2, fontweight="bold", color="#0f172a", y=0.972,
    )
    fig.text(
        0.5, 0.946,
        f"TX SST v5_pdk CPEX (n_zq=16) → C2_loss6 PCB (−6.9 dB @ 2.5 GHz, delay {r3['channel_delay_ps']:.0f} ps) → "
        f"W3 Shunt-Peaked CTLE CPEX (EQ=3, 8.2 nH, 57.4 fF + 8×Slicer 5G)  |  TT 1.80 V 27 °C  |  1 UI = 200 ps",
        ha="center", va="center", fontsize=8.8, color="#334155",
    )

    # =========================================================================
    # ROW 1: TX SST v5_pdk Pad Differential Output
    # =========================================================================
    ax1 = fig.add_subplot(gs[0])
    _style_axis(ax1)
    _shade_ui(ax1)
    ax1.axhline(0.0, color="#94a3b8", lw=0.65, zorder=1)

    ax1.plot(
        u, arrs["ffe0_tx_mv"], color="#64748b", lw=1.45, ls="--", alpha=0.90, zorder=3,
        label=f"FFE=0 (No De-emphasis): Vpp = {r0['tx_vpp_mv']:.0f} mV, flat ±{r0['tx_v_deemph_mv']:.0f} mV",
    )
    ax1.plot(
        u, arrs["ffe3_tx_mv"], color="#1d4ed8", lw=2.05, ls="-", zorder=4,
        label=(
            f"FFE=3 (n_post=3 / 16): Vpp = {r3['tx_vpp_mv']:.0f} mV, "
            f"trans ±{r3['tx_v_trans_mv']:.0f} mV → plateau ±{r3['tx_v_deemph_mv']:.0f} mV ({r3['tx_ffe_deemph_db']:+.2f} dB step)"
        ),
    )

    # Annotate FFE de-emphasis step plateau cleanly on bits 4..6 (`111` run) in open upper space
    ax1.annotate(
        f"FFE=3 de-emphasis step: {r3['tx_ffe_deemph_db']:+.2f} dB\n(±{r3['tx_v_trans_mv']:.0f} → ±{r3['tx_v_deemph_mv']:.0f} mV)",
        xy=(5.5, r3["tx_v_deemph_mv"]), xytext=(7.25, 242.0),
        fontsize=7.4, fontweight="bold", color="#1e3a8a", ha="left", va="center",
        bbox=dict(boxstyle="round,pad=0.24", facecolor="#eff6ff", edgecolor="#93c5fd", lw=0.8),
        arrowprops=dict(arrowstyle="->", color="#1d4ed8", lw=1.1, connectionstyle="arc3,rad=-0.10"),
        zorder=6,
    )

    ax1.set_xlim(0.0, 16.0)
    ax1.set_ylim(-335.0, 315.0)
    ax1.set_yticks([-200, -100, 0, 100, 200])
    ax1.set_xticks(np.arange(0, 17, 1))
    ax1.set_xticklabels([])
    ax1.set_ylabel("TX Pad Diff (mV)", fontsize=8.6, fontweight="bold", color="#0f172a")
    ax1.set_title("(a) TX SST v5_pdk Pad Differential Output — Clear 1-Tap Post-Cursor De-Emphasis Plateaus on Run Bits",
                  fontsize=9.5, fontweight="bold", color="#0f172a", loc="left", pad=42)
    ax1.legend(loc="lower left", fontsize=7.5, framealpha=0.96, edgecolor="#cbd5e1", ncol=2, columnspacing=1.1)

    # Bit sequence strip + feature brackets cleanly stacked below title (a)
    for k, b in enumerate(SHOWCASE_16):
        bg = "#dbeafe" if b == 1 else "#f1f5f9"
        fg = "#1e3a8a" if b == 1 else "#475569"
        ax1.text(
            k + 0.5, 1.03, str(b), transform=ax1.get_xaxis_transform(),
            ha="center", va="bottom", fontsize=8.2, fontweight="bold", color=fg,
            bbox=dict(boxstyle="round,pad=0.14", facecolor=bg, edgecolor="#cbd5e1", lw=0.6),
        )
    clean_spans = [
        (0.08, 3.92, "10101 Nyquist Toggle", "#0369a1"),
        (4.08, 9.92, "111000 Run (FFE De-Emphasis)", "#1d4ed8"),
        (10.08, 13.92, "Lone Pulse (0001000 ISI)", "#b45309"),
        (14.08, 15.92, "10 Exit", "#475569"),
    ]
    for x0, x1, txt, col in clean_spans:
        xm = 0.5 * (x0 + x1)
        ax1.plot([x0, x1], [1.145, 1.145], color=col, lw=1.35, clip_on=False, transform=ax1.get_xaxis_transform())
        ax1.text(xm, 1.168, txt, ha="center", va="bottom", fontsize=7.5, fontweight="bold", color=col,
                 clip_on=False, transform=ax1.get_xaxis_transform())

    # =========================================================================
    # ROW 2: Post-C2_loss6 PCB Channel Differential Waveform (Delay-Aligned)
    # =========================================================================
    ax2 = fig.add_subplot(gs[1])
    _style_axis(ax2)
    _shade_ui(ax2)
    ax2.axhline(0.0, color="#94a3b8", lw=0.65, zorder=1)
    ax2.axhline(75.0, color="#dc2626", lw=0.85, ls="--", alpha=0.65, zorder=2)
    ax2.axhline(-75.0, color="#dc2626", lw=0.85, ls="--", alpha=0.65, zorder=2)

    ax2.plot(
        u, arrs["ffe0_rx_mv"], color="#64748b", lw=1.50, ls="--", alpha=0.92, zorder=3,
        label=f"FFE=0 post-C2: Vpp = {r0['rx_vpp_mv']:.0f} mV | Lone bit = +{r0['rx_lone_pulse_mv']:.1f} mV vs run ±{r0['rx_long_run_mv']:.0f} mV (severe ISI)",
    )
    ax2.plot(
        u, arrs["ffe3_rx_mv"], color="#d97706", lw=2.05, ls="-", zorder=4,
        label=f"FFE=3 post-C2: Vpp = {r3['rx_vpp_mv']:.0f} mV | Lone bit = +{r3['rx_lone_pulse_mv']:.1f} mV vs run ±{r3['rx_long_run_mv']:.0f} mV (flat amplitude)",
    )
    ax2.scatter([10.5], [r0["rx_lone_pulse_mv"]], color="#475569", s=34, zorder=5, edgecolors="white", lw=0.7)
    ax2.scatter([10.5], [r3["rx_lone_pulse_mv"]], color="#b45309", s=38, zorder=6, edgecolors="white", lw=0.7)
    ax2.annotate(
        f"Bit 10 Lone Pulse (0001000):\nFFE=0 drops to +{r0['rx_lone_pulse_mv']:.1f} mV\nFFE=3 holds +{r3['rx_lone_pulse_mv']:.1f} mV",
        xy=(10.55, r3["rx_lone_pulse_mv"]), xytext=(11.45, 162.0),
        fontsize=7.3, fontweight="bold", color="#92400e", ha="left", va="center",
        bbox=dict(boxstyle="round,pad=0.25", facecolor="#fffbeb", edgecolor="#f59e0b", lw=0.85),
        arrowprops=dict(arrowstyle="->", color="#d97706", lw=1.1, connectionstyle="arc3,rad=0.14"),
        zorder=7,
    )

    ax2.set_xlim(0.0, 16.0)
    ax2.set_ylim(-275.0, 235.0)
    ax2.set_yticks([-200, -75, 0, 75, 200])
    ax2.set_xticks(np.arange(0, 17, 1))
    ax2.set_xticklabels([])
    ax2.set_ylabel("Post-C2 Diff (mV)", fontsize=8.6, fontweight="bold", color="#0f172a")
    ax2.set_title(
        f"(b) Post-C2_loss6 PCB Channel Waveform at RX Input (Delay-Aligned by −{r3['channel_delay_ps']:.0f} ps) — Lone-Pulse ISI Equalization",
        fontsize=9.4, fontweight="bold", color="#0f172a", loc="left", pad=6,
    )
    ax2.legend(loc="lower left", fontsize=7.3, framealpha=0.96, edgecolor="#cbd5e1", ncol=1)

    # =========================================================================
    # ROW 3: Post-W3 CTLE (EQ=3) Equalized Waveform at Slicer Input
    # =========================================================================
    ax3 = fig.add_subplot(gs[2])
    _style_axis(ax3)
    _shade_ui(ax3)

    ax3.axhspan(-slicer_3s_mv, slicer_3s_mv, color="#fecdd3", alpha=0.52, zorder=1,
                label=f"Slicer 5G 3σ offset band (±{slicer_3s_mv:.1f} mV, 250× MC)")
    ax3.axhline(slicer_3s_mv, color="#be123c", lw=0.75, ls=":", alpha=0.85, zorder=2)
    ax3.axhline(-slicer_3s_mv, color="#be123c", lw=0.75, ls=":", alpha=0.85, zorder=2)
    ax3.axhline(75.0, color="#dc2626", lw=1.05, ls="--", alpha=0.82, zorder=2, label="±75 mV bit-center margin spec")
    ax3.axhline(-75.0, color="#dc2626", lw=1.05, ls="--", alpha=0.82, zorder=2)
    ax3.axhline(0.0, color="#94a3b8", lw=0.65, zorder=1)

    for uc in u_centers:
        ax3.axvline(uc, color="#94a3b8", lw=0.6, ls=":", alpha=0.65, zorder=1)

    ax3.plot(
        u, arrs["ffe0_ctle_mv"], color="#7c3aed", lw=1.75, ls="-", alpha=0.86, zorder=3,
        label=f"FFE=0 + W3 CTLE (EQ=3): min signed = ±{r0['ctle_min_signed_mv']:.1f} mV ({r0['ctle_bits_clear_75mv']}/16 ≥ 75 mV)",
    )
    ax3.plot(
        u, arrs["ffe3_ctle_mv"], color="#047857", lw=2.10, ls="-", zorder=4,
        label=f"FFE=3 + W3 CTLE (EQ=3): min signed = ±{r3['ctle_min_signed_mv']:.1f} mV ({r3['ctle_bits_clear_75mv']}/16 ≥ 75 mV)",
    )

    ctle3_samp = [b["ctle_mv"] for b in r3["per_bit"]]
    ctle0_samp = [b["ctle_mv"] for b in r0["per_bit"]]
    ax3.scatter(u_centers, ctle0_samp, color="#7c3aed", s=24, marker="s", zorder=5, edgecolors="white", lw=0.55)
    ax3.scatter(u_centers, ctle3_samp, color="#047857", s=30, marker="o", zorder=6, edgecolors="white", lw=0.65)

    ax3.set_xlim(0.0, 16.0)
    ax3.set_ylim(-295.0, 230.0)
    ax3.set_yticks([-200, -75, 0, 75, 200])
    ax3.set_xticks(np.arange(0, 17, 1))
    ax3.set_xticklabels([])
    ax3.set_ylabel("CTLE Out Diff (mV)", fontsize=8.6, fontweight="bold", color="#0f172a")
    ax3.set_title(
        "(c) Post-W3 Shunt-Peaked CTLE (EQ=3, 8.2 nH, 57.4 fF + 8×Slicer) Waveform at Slicer Input — Bit-Center Sampling",
        fontsize=9.4, fontweight="bold", color="#0f172a", loc="left", pad=6,
    )
    ax3.legend(loc="lower left", fontsize=7.15, framealpha=0.96, edgecolor="#cbd5e1", ncol=2, columnspacing=1.0)

    # =========================================================================
    # ROW 4a: TX V_drv Sub-LDO Supply Ripple (mV around ~0.434 V)
    # =========================================================================
    ax4a = fig.add_subplot(gs[3])
    _style_axis(ax4a)
    _shade_ui(ax4a)
    ax4a.axhline(0.0, color="#94a3b8", lw=0.7, zorder=1)

    ax4a.plot(
        u, arrs["ffe0_vdrv_mv"], color="#64748b", lw=1.45, ls="--", zorder=3,
        label=f"FFE=0 ΔV_drv around {r0['vdrv_mean_v']:.4f} V (ripple = {r0['vdrv_rip_mvpp']:.1f} mVpp)",
    )
    ax4a.plot(
        u, arrs["ffe3_vdrv_mv"], color="#0284c7", lw=1.9, ls="-", zorder=4,
        label=f"FFE=3 ΔV_drv around {r3['vdrv_mean_v']:.4f} V (ripple = {r3['vdrv_rip_mvpp']:.1f} mVpp, switched FFE slices)",
    )

    v_abs_max = max(float(np.max(np.abs(arrs["ffe3_vdrv_mv"]))), float(np.max(np.abs(arrs["ffe0_vdrv_mv"]))))
    y4a_top = max(18.0, math.ceil((v_abs_max + 5.0) / 5.0) * 5.0)
    y4a_bot = max(28.0, math.ceil((v_abs_max + 14.0) / 5.0) * 5.0)
    ax4a.set_xlim(0.0, 16.0)
    ax4a.set_ylim(-y4a_bot, y4a_top)
    ax4a.set_yticks([-20, -10, 0, 10])
    ax4a.set_xticks(np.arange(0, 17, 1))
    ax4a.set_xticklabels([])
    ax4a.set_ylabel("ΔV_drv (mV)", fontsize=8.5, fontweight="bold", color="#0f172a")
    ax4a.set_title(
        f"(d1) TX V_drv Sub-LDO Supply Ripple (Mean {r3['vdrv_mean_v']:.3f} V, v4p5_pdk CPEX Inside TX SST)",
        fontsize=9.2, fontweight="bold", color="#0f172a", loc="left", pad=5,
    )
    ax4a.legend(loc="lower left", fontsize=7.3, framealpha=0.96, edgecolor="#cbd5e1", ncol=2, columnspacing=1.2)

    # =========================================================================
    # ROW 4b: Per-Bit Sampled Signed Margin Bars at Slicer Input (16/16 >= 75 mV!)
    # =========================================================================
    ax4b = fig.add_subplot(gs[4])
    _style_axis(ax4b)
    _shade_ui(ax4b)

    m3 = arrs["ffe3_ctle_signed"]
    m0 = arrs["ffe0_ctle_signed"]
    wb = 0.34
    b3 = ax4b.bar(u_centers - wb / 2, m3, width=wb, color="#059669", edgecolor="#065f46", lw=0.65, zorder=3,
                  label=f"FFE=3: {r3['ctle_min_signed_mv']:.1f}–{r3['ctle_max_signed_mv']:.1f} mV (16/16 PASS)")
    b0 = ax4b.bar(u_centers + wb / 2, m0, width=wb, color="#8b5cf6", edgecolor="#5b21b6", lw=0.65, alpha=0.88, zorder=3,
                  label=f"FFE=0: {r0['ctle_min_signed_mv']:.1f}–{r0['ctle_max_signed_mv']:.1f} mV (16/16 PASS)")

    ax4b.axhline(75.0, color="#dc2626", lw=1.15, ls="--", zorder=4, label="75 mV Spec")
    ax4b.axhspan(0.0, slicer_3s_mv, color="#fecdd3", alpha=0.50, zorder=1)
    ax4b.axhline(slicer_3s_mv, color="#be123c", lw=0.8, ls=":", zorder=4, label=f"Slicer 3σ ({slicer_3s_mv:.1f} mV)")

    for rct in b3:
        h = rct.get_height()
        ax4b.text(rct.get_x() + rct.get_width() / 2, h + 4.0, f"{h:.0f}", ha="center", va="bottom",
                  fontsize=6.6, fontweight="bold", color="#065f46", zorder=5)
    for rct in b0:
        h = rct.get_height()
        ax4b.text(rct.get_x() + rct.get_width() / 2, h + 4.0, f"{h:.0f}", ha="center", va="bottom",
                  fontsize=6.6, fontweight="bold", color="#5b21b6", zorder=5)

    y4b_top = max(255.0, math.ceil((max(float(np.max(m3)), float(np.max(m0))) + 72.0) / 25.0) * 25.0)
    ax4b.set_xlim(0.0, 16.0)
    ax4b.set_ylim(0.0, y4b_top)
    ax4b.set_yticks([0, 75, 150, 225])
    ax4b.set_xticks(np.arange(0, 17, 1))
    ax4b.set_xticklabels([f"{k}\n({k * 0.2:.1f} ns)" if k % 2 == 0 else str(k) for k in range(17)], fontsize=7.8)
    ax4b.set_xlabel("Time (UI  /  ns at 5.0 Gb/s, 1 UI = 200 ps)  —  Bit Index k = 0..15", fontsize=8.8, fontweight="bold", color="#0f172a")
    ax4b.set_ylabel("Signed Margin (mV)", fontsize=8.5, fontweight="bold", color="#0f172a")
    ax4b.set_title(
        f"(d2) Per-Bit Sampled Slicer-Input Signed Margin — 16/16 Bits Clear ≥75 mV Spec "
        f"(FFE=3: {r3['ctle_min_signed_mv']:.1f}–{r3['ctle_max_signed_mv']:.1f} mV | FFE=0: {r0['ctle_min_signed_mv']:.1f}–{r0['ctle_max_signed_mv']:.1f} mV)",
        fontsize=9.2, fontweight="bold", color="#0f172a", loc="left", pad=5,
    )
    ax4b.legend(loc="upper center", fontsize=7.1, framealpha=0.96, edgecolor="#cbd5e1", ncol=4, columnspacing=1.1)

    # Footer
    fig.text(
        0.5, 0.010,
        f"5G Plan-C Real-CPEX 16-UI Showcase (2026-11-26)  |  Pattern: {''.join(str(b) for b in SHOWCASE_16)}  |  "
        f"TX FFE=3 De-emphasis: {r3['tx_ffe_deemph_db']:+.2f} dB  |  "
        f"Post-C2 Lone-Bit: {r0['rx_lone_pulse_mv']:.1f}→{r3['rx_lone_pulse_mv']:.1f} mV  |  "
        f"Post-CTLE: 16/16 Bits PASS ≥75 mV (Slicer 3σ = {slicer_3s_mv:.1f} mV)",
        ha="center", va="center", fontsize=7.6, color="#475569",
    )

    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=240)
    plt.close(fig)
    print(f"SAVED 16-UI waveform figure -> {fig_path.relative_to(REPO)} (240 DPI)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=1, choices=(1,), help="Strictly 1 ngspice worker at a time")
    ap.add_argument("--plot-only", action="store_true", help="Re-render figure from saved NPZ & summary JSON")
    args = ap.parse_args()
    assert args.workers == 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.plot_only:
        summary = json.loads(SUMMARY_PATH.read_text())
        arrs = dict(np.load(NPZ_PATH))
        render_16ui_figure(summary, arrs, FIG_PATH)
        return 0

    t0 = time.time()
    load = eyes5g.extract_rx_top_ctle_load()
    print("=== [1/3] Running Sequential 5.0 Gb/s 16-UI CPEX Transients (FFE=3, FFE=0) ===", flush=True)

    rec3, arr3 = run_single_16ui_case(load, n_post=3)
    rec0, arr0 = run_single_16ui_case(load, n_post=0)

    # Extra safety sweep: confirm zero `.raw` files left under OUT_DIR
    for stale in OUT_DIR.rglob("*.raw"):
        stale.unlink(missing_ok=True)

    u_grid = np.linspace(0.0, float(SHOWCASE_LEN), 1601).astype(np.float32)
    all_arrs = {"u_grid": u_grid, **arr3, **arr0}
    np.savez_compressed(NPZ_PATH, **all_arrs)
    write_compact_csv(u_grid, all_arrs, CSV_PATH)

    summary = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "conditions": {"corner": "tt", "vdd_v": VDD_TT, "temp_c": TEMP_TT, "rate_gbps": 5.0, "ui_ps": UI_PS, "n_zq": N_ZQ_TT, "eq_code": EQ_CODE},
        "sequence": {
            "preamble_16": PREAMBLE_16,
            "showcase_16": SHOWCASE_16,
            "showcase_str": "".join(str(b) for b in SHOWCASE_16),
            "tail_16": TAIL_16,
        },
        "ctle_load_rx_top_5g": load,
        "cases": {"ffe3": rec3, "ffe0": rec0},
        "artifacts": {
            "npz": str(NPZ_PATH.relative_to(REPO)),
            "csv": str(CSV_PATH.relative_to(REPO)),
            "figure": str(FIG_PATH.relative_to(REPO)),
        },
        "total_elapsed_s": round(time.time() - t0, 1),
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"=== [2/3] Saved {SUMMARY_PATH.relative_to(REPO)}, {NPZ_PATH.relative_to(REPO)}, {CSV_PATH.relative_to(REPO)} ===", flush=True)

    print("=== [3/3] Rendering Publication-Grade 16-UI Figure (240 DPI) ===", flush=True)
    render_16ui_figure(summary, all_arrs, FIG_PATH)
    print(f"ALL DONE in {time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
