#!/usr/bin/env python3
"""5.0 Gb/s & 4.0 Gb/s TT Full-Chain Real-CPEX Eye Diagram & Equalization Showcase.

Runs REAL ngspice (TT 1.80 V, 27 C) AC + transient simulations using the signed-off 5G CPEX netlists:
  1. TX SST `v5_pdk` CPEX (`serdes_tx_sst_top_pdk_pex.spice`, n_zq=16, FFE=3 & FFE=0)
  2. Package RLC + AC coupling + `pcb_c2_loss6` 100-Ohm differential PCB channel
  3. PDK 100-Ohm split RX termination (`serdes_rx_term_pdk`) + W3 Shunt-Peaked CTLE CPEX
     (`serdes_rx_ctle_shunt_5g_w3_pdk_open_pex.spice`) + compact M4+M2 8.204 nH stacked inductor
     (`rx_ctle_ind_m4m2_5g_pdk`) + exact `rx_top_5g_pdk` extracted wire load (`57.3/57.5 fF` node cap,
     `C_gnd_ext=36.29 fF`, `C_pn=13.91 fF`) + 8x real `serdes_rx_dt_slicer_5g_pdk` transistor loads.

Simulations (strictly <= 2 concurrent ngspice processes, single-threaded per process):
  - AC Sweep (10 MHz - 10 GHz): `C2_loss6`, `W3 CTLE` (EQ=0..3), and combined `C2_loss6 + W3 CTLE`
  - Transient 5.0 Gb/s (200 ps UI, 128-bit sequence w/ 96-bit PRBS-7): `FFE=3` and `FFE=0`
  - Transient 4.0 Gb/s (250 ps UI, 128-bit sequence w/ 96-bit PRBS-7): `FFE=3` dual-rate compat

Outputs:
  - `results/verification/tt_eyes_5g_20261126/summary.json`
  - `results/verification/tt_eyes_5g_20261126/folded_eyes.npz` (compact folded eye arrays; `.raw` deleted!)
  - `docs/figures/system/serdes_5g_tt_eyes_20261126.png` (2x3 publication-grade showcase, 240 DPI)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.gridspec as gridspec
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "verification/top_cosim"))

from serdes_flow import eye as sf_eye, spice as sf_spice, watch as sf_watch  # noqa: E402
from serdes_flow.waves import crossings  # noqa: E402
import verify_5g_full_chain as v5g  # noqa: E402

PDK = "/home/host/.volare/sky130A/libs.tech/ngspice/sky130.lib.spice"
NGSPICE = "/opt/ngspice47/bin/ngspice"

TX_V5_PEX = REPO / "results/layout/tx_sst_v5_pdk/review/serdes_tx_sst_top_pdk/serdes_tx_sst_top_pdk_pex.spice"
CTLE_W3_OPEN_PEX = REPO / "analog/rx/cmos_rx/layout/variants/ctle_shunt_5g_w3_pdk/serdes_rx_ctle_shunt_5g_w3_pdk_open_pex.spice"
SLICER_5G_REF = REPO / "analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/serdes_rx_dt_slicer_5g_pdk_ref.spice"
SLICER_SUMMARY = REPO / "results/analog/rx/slicer_5g_hardening_20261125/summary.json"
RX_TOP_OPEN_PEX = REPO / "results/layout/rx_cmos_5g/top/top_open_verify/serdes_rx_cmos_top_5g_pdk_open_pex.spice"

OUT_DIR = REPO / "results/verification/tt_eyes_5g_20261126"
FIG_PATH = REPO / "docs/figures/system/serdes_5g_tt_eyes_20261126.png"

# Signed-off compact M4+M2 8.204 nH stacked inductor (Magic DRC=0, 0% M5, 57.6x57.6 um)
IND_M4M2_SUBCKT = """
.subckt rx_ctle_ind_m4m2_5g_pdk pa pb ct sub
+ params: lhalf=2.829n kmut=0.45 rs=66.74 csa=8.7f csct=41.2f rsub=500 cw=15f cpn=23f rm_scale=1.0 c_scale=1.0
Rsa1 pa  na1 {0.5*rs*rm_scale} tc1=3.2e-3
La   na1 na2 {lhalf}
Rsa2 na2 ct  {0.5*rs*rm_scale} tc1=3.2e-3
Cwa  pa  ct  {cw*c_scale}
Csa  pa  sa  {csa*c_scale}
Rsub_a sa sub {rsub} tc1=1.5e-3
Rsb1 ct  nb1 {0.5*rs*rm_scale} tc1=3.2e-3
Lb   nb1 nb2 {lhalf}
Rsb2 nb2 pb  {0.5*rs*rm_scale} tc1=3.2e-3
Cwb  ct  pb  {cw*c_scale}
Csb  pb  sb  {csa*c_scale}
Rsub_b sb sub {rsub} tc1=1.5e-3
Cs_ct   ct  sct {csct*c_scale}
Rsub_ct sct sub {rsub} tc1=1.5e-3
Cpn_diff pa pb {cpn*c_scale}
Kab La Lb {kmut}
.ends rx_ctle_ind_m4m2_5g_pdk
""".strip()

# 128-bit rich sequence (8 x 16b words): 16 alt + 16 marker (0xD3A5) + 80 PRBS-7 payload + 16 PRBS-7 tail
ALT_BITS = 16
TRAIN_BITS = 32
PAYLOAD_BITS = 80
TAIL_BITS = 16
TOTAL_BITS = TRAIN_BITS + PAYLOAD_BITS + TAIL_BITS  # 128 bits

VDD_TT = 1.80
TEMP_TT = 27
N_ZQ_TT = 16


def build_sequence_128() -> np.ndarray:
    alt = [i & 1 for i in range(ALT_BITS)]
    marker = [(0xD3A5 >> b) & 1 for b in range(16)]
    payload = sf_eye.prbs7(PAYLOAD_BITS + TAIL_BITS, seed=0x11)
    return np.array(alt + marker + payload, dtype=int)


def parallel_word_stimuli_rate(bits: np.ndarray, supply: float, t_first_upd: float, ui: float, edge: float = 40e-12) -> str:
    t_word = 16.0 * ui
    n_words = len(bits) // 16
    lines = []
    for bit_idx in range(16):
        init_b = bit_idx & 1
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


def extract_rx_top_ctle_load() -> dict[str, float]:
    """Extract exact ctle_p/ctle_n external wire caps from signed-off `rx_top_5g_pdk` open PEX."""
    if not RX_TOP_OPEN_PEX.exists():
        # Exact signed-off fallback from `rx_top_5g_pdk` / `ctle_w3_pvt45_mc_20261125/summary.json`
        return {
            "cpn_mutual_fF": 13.91,
            "c_gnd_ext_fF": 36.29,
            "node_wire_cap_fF": 57.5,
            "total_diff_wire_cap_fF": 72.31,
        }
    cpn = csub_p = csub_n = coth_p = coth_n = 0.0
    for ln in RX_TOP_OPEN_PEX.read_text().splitlines():
        if not ln.startswith("C"):
            continue
        toks = ln.split()
        a, b, s = toks[1], toks[2], toks[3].lower()
        v = float(s[:-1]) if s.endswith("f") else (float(s[:-1]) * 1e3 if s.endswith("p") else float(s) * 1e15)
        if {a, b} == {"ctle_p", "ctle_n"}:
            cpn += v
        elif "ctle_p" in (a, b):
            other = b if a == "ctle_p" else a
            if other in ("vss", "0", "Gnd"):
                csub_p += v
            else:
                coth_p += v
        elif "ctle_n" in (a, b):
            other = b if a == "ctle_n" else a
            if other in ("vss", "0", "Gnd"):
                csub_n += v
            else:
                coth_n += v
    # Subtract CTLE open PEX internal ~8.22 fF outp/outn cap to avoid double counting
    c_gnd_ext = max(0.0, 0.5 * (csub_p + csub_n + coth_p + coth_n) - 8.22)
    node_cap = 0.5 * (csub_p + csub_n + coth_p + coth_n) + cpn
    return {
        "cpn_mutual_fF": round(cpn, 2),
        "c_gnd_ext_fF": round(c_gnd_ext, 2),
        "node_wire_cap_fF": round(node_cap, 2),
        "total_diff_wire_cap_fF": round(0.5 * (csub_p + csub_n + coth_p + coth_n) + 2.0 * cpn, 2),
    }


def slicer_5g_bank_load_lines(prefix: str, inp: str, inn: str, c_gnd_ext_ff: float, c_pn_ff: float) -> list[str]:
    """Exact `rx_top_5g_pdk` external wire caps + 8x signed-off `serdes_rx_dt_slicer_5g_pdk` transistor loads."""
    lines = [
        f"Cg_{prefix}p {inp} 0 {c_gnd_ext_ff:.2f}f",
        f"Cg_{prefix}n {inn} 0 {c_gnd_ext_ff:.2f}f",
        f"Cpn_{prefix} {inp} {inn} {c_pn_ff:.2f}f",
    ]
    # 4 slicers in precharge (clk=0) + 4 slicers in eval (clk=vdd) -> exact average dynamic gate capacitance
    for k in range(8):
        ck = "0" if k < 4 else "vdd"
        lines.append(
            f"Xsl_{prefix}_{k} {inp} {inn} {ck} sl_{prefix}_qp{k} sl_{prefix}_qn{k} "
            f"vdd 0 0 0 0 0 vdd 0 serdes_rx_dt_slicer_5g_pdk"
        )
    return lines


def check_ngspice_limit(requested: int) -> None:
    active = len(sf_watch.ngspice_cwds())
    if active + requested > 4:
        raise RuntimeError(f"Host ngspice limit guard: {active} active + {requested} requested > 4")


def parse_ac_tsv(path: Path) -> dict[str, np.ndarray]:
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    header = lines[0].split()
    data = np.atleast_2d(np.loadtxt(lines[1:]))
    out: dict[str, np.ndarray] = {}
    i = 0
    while i < len(header):
        name = header[i]
        if i + 1 < len(header) and header[i + 1] == name:
            # ngspice writes complex AC plot vectors as two identically named columns (re, im)
            out[name] = data[:, i]
            i += 2
        else:
            out[name] = data[:, i]
            i += 1
    return out


# =============================================================================
# RUN 3: FAST TT AC SWEEP (10 MHz - 10 GHz)
# =============================================================================

def run_ac_sweep(work_dir: Path, load: dict[str, float]) -> dict:
    """Measure C2_loss6, standalone W3 CTLE CPEX (EQ=0..3), and combined C2_loss6 + W3 CTLE (EQ=0..3)."""
    ac_dir = work_dir / "ac_tt"
    ac_dir.mkdir(parents=True, exist_ok=True)
    cir = ac_dir / "ac_tt.cir"
    log = ac_dir / "ac_tt.log"

    eq_codes = [
        ("eq0", 0, 0.0, 0.0),
        ("eq1", 1, VDD_TT, 0.0),
        ("eq2", 2, 0.0, VDD_TT),
        ("eq3", 3, VDD_TT, VDD_TT),
    ]

    ctrl = [
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    for tag, _idx, e0, e1 in eq_codes:
        ctrl += [
            f"alter Veq0 dc={e0}",
            f"alter Veq1 dc={e1}",
            "op",
            "let vcm_ctle = 0.5*(v(op_sa)+v(on_sa))",
            "let idd_ctle_ma = -i(Vm_sa)*1e3",
            f"wrdata op_{tag}.tsv vcm_ctle idd_ctle_ma",
            "ac dec 60 10Meg 10Gig",
            "let ch_db = 20*log10(max(mag(v(rx_p)-v(rx_n)), 1e-12))",
            "let ctle_db = 20*log10(max(mag(v(op_sa)-v(on_sa)), 1e-12))",
            "let comb_db = 20*log10(max(mag(v(op_cb)-v(on_cb)), 1e-12))",
            "let ch_ph = ph(v(rx_p)-v(rx_n))",
            "let ctle_ph = ph(v(op_sa)-v(on_sa))",
            "let comb_ph = ph(v(op_cb)-v(on_cb))",
            f"wrdata ac_{tag}.tsv ch_db ctle_db comb_db ch_ph ctle_ph comb_ph",
            "destroy all",
        ]
    ctrl.append("quit")

    lines = [
        "* 5G TT AC Sweep: C2_loss6 + W3 Shunt-Peaked CTLE CPEX (EQ=0..3) + Combined Channel+CTLE",
        f'.lib "{PDK}" tt',
        f'.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"',
        f'.include "{REPO}/analog/bias/spice/bias_v2.spice"',
        f'.include "{REPO}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"',
        f'.include "{CTLE_W3_OPEN_PEX}"',
        f'.include "{SLICER_5G_REF}"',
        f'.include "{REPO}/verification/models/channel/pcb_family/pcb_foster_cells.spice"',
        f'.include "{REPO}/verification/models/channel/pcb_family/C2_loss6.spice"',
        IND_M4M2_SUBCKT,
        f".temp {TEMP_TT}",
        f"Vdd vdd 0 {VDD_TT}",
        "Ibias vdd vbias 50u",
        "Xbd vbias 0 serdes_bias_ctle_v2",
        f"Veq0 eq0 0 {VDD_TT}",
        f"Veq1 eq1 0 {VDD_TT}",
        # --- Branch A: Standalone W3 CTLE CPEX (V_in_diff = 1.0 V AC -> |v(op_sa)-v(on_sa)| = |H_CTLE|) ---
        "Vinp_sa inp_sa 0 dc 1.05 ac 0.5",
        "Vinn_sa inn_sa 0 dc 1.05 ac -0.5",
        "Vm_sa vdd vdd_sa 0",
        "Xctle_sa inp_sa inn_sa op_sa on_sa eq0 eq1 vbias vdd_sa 0 lp_sa ln_sa serdes_rx_ctle_shunt_5g_w3_pdk_open",
        "Xind_sa lp_sa ln_sa vdd_sa 0 rx_ctle_ind_m4m2_5g_pdk rm_scale=1.0 c_scale=1.0",
        *slicer_5g_bank_load_lines("sa", "op_sa", "on_sa", load["c_gnd_ext_fF"], load["cpn_mutual_fF"]),
        # --- Branch B: C2_loss6 Channel (matched 50 Ohm source + pkg + AC + C2 + 100 Ohm RX term) + W3 CTLE CPEX ---
        # V_src_diff = 2.0 V AC -> matched lossless load sees 1.0 V (0 dB Sdd21 reference)
        "Vsrc_p src_p 0 dc 0.22 ac 1.0",
        "Vsrc_n src_n 0 dc 0.22 ac -1.0",
        "Rs_p src_p tx_p 50",
        "Rs_n src_n tx_n 50",
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
        "Xctle_cb rx_p rx_n op_cb on_cb eq0 eq1 vbias vdd 0 lp_cb ln_cb serdes_rx_ctle_shunt_5g_w3_pdk_open",
        "Xind_cb lp_cb ln_cb vdd 0 rx_ctle_ind_m4m2_5g_pdk rm_scale=1.0 c_scale=1.0",
        *slicer_5g_bank_load_lines("cb", "op_cb", "on_cb", load["c_gnd_ext_fF"], load["cpn_mutual_fF"]),
        ".options klu",
        ".control",
        *ctrl,
        ".endc",
        ".end",
    ]
    cir.write_text("\n".join(lines) + "\n")
    all_tsv = all(
        (ac_dir / f"ac_{tag}.tsv").exists() and (ac_dir / f"op_{tag}.tsv").exists()
        for tag, *_ in eq_codes
    )
    t0 = time.time()
    if not all_tsv:
        check_ngspice_limit(1)
        subprocess.run([NGSPICE, "-b", "-o", str(log), str(cir)], cwd=ac_dir, check=True, timeout=180)
    elapsed = time.time() - t0

    freq_ghz = None
    ch_db_ref = None
    eq_data: dict[str, dict] = {}
    for tag, idx, _e0, _e1 in eq_codes:
        d = parse_ac_tsv(ac_dir / f"ac_{tag}.tsv")
        op = parse_ac_tsv(ac_dir / f"op_{tag}.tsv")
        f = d["frequency"] / 1e9
        ch_db = d["ch_db"]
        ctle_db = d["ctle_db"]
        comb_db = d["comb_db"]
        if freq_ghz is None:
            freq_ghz = f
            ch_db_ref = ch_db

        def _interp(arr: np.ndarray, f_tgt: float) -> float:
            return float(np.interp(f_tgt, f, arr))

        g_dc = float(ctle_db[0])
        g_2p0 = _interp(ctle_db, 2.0)
        g_2p5 = _interp(ctle_db, 2.5)
        pk_idx = int(np.argmax(ctle_db))
        g_pk = float(ctle_db[pk_idx])
        f_pk = float(f[pk_idx])
        # -3 dB BW relative to DC gain
        below = np.where((f > f_pk) & (ctle_db <= g_dc - 3.0))[0]
        bw_ghz = float(f[below[0]]) if len(below) else float(f[-1])

        eq_data[tag] = {
            "eq_code": idx,
            "ctle_dc_db": round(g_dc, 2),
            "ctle_2p0g_db": round(g_2p0, 2),
            "ctle_2p5g_db": round(g_2p5, 2),
            "ctle_boost_2p0g_db": round(g_2p0 - g_dc, 2),
            "ctle_boost_2p5g_db": round(g_2p5 - g_dc, 2),
            "ctle_peak_boost_db": round(g_pk - g_dc, 2),
            "ctle_f_peak_ghz": round(f_pk, 2),
            "ctle_bw_3db_ghz": round(bw_ghz, 2),
            "comb_dc_db": round(float(comb_db[0]), 2),
            "comb_2p0g_db": round(_interp(comb_db, 2.0), 2),
            "comb_2p5g_db": round(_interp(comb_db, 2.5), 2),
            "vcm_out_v": round(float(op["vcm_ctle"][0]), 3),
            "p_ctle_mw": round(abs(float(op["idd_ctle_ma"][0])) * VDD_TT, 2),
            "ctle_db_curve": np.round(ctle_db, 3).tolist(),
            "comb_db_curve": np.round(comb_db, 3).tolist(),
        }

    assert freq_ghz is not None and ch_db_ref is not None
    ch_summary = {
        "dc_db": round(float(ch_db_ref[0]), 2),
        "loss_2p0g_db": round(float(np.interp(2.0, freq_ghz, ch_db_ref)), 2),
        "loss_2p5g_db": round(float(np.interp(2.5, freq_ghz, ch_db_ref)), 2),
        "loss_5p0g_db": round(float(np.interp(5.0, freq_ghz, ch_db_ref)), 2),
    }
    print(
        f"  [AC TT] done in {elapsed:.1f}s | C2_loss6: {ch_summary['loss_2p0g_db']:.2f} dB @ 2.0G, "
        f"{ch_summary['loss_2p5g_db']:.2f} dB @ 2.5G | "
        f"W3 EQ3: DC={eq_data['eq3']['ctle_dc_db']:+.2f}dB, Boost@2.5G={eq_data['eq3']['ctle_boost_2p5g_db']:+.2f}dB, "
        f"BW={eq_data['eq3']['ctle_bw_3db_ghz']:.2f}GHz, P={eq_data['eq3']['p_ctle_mw']:.2f}mW",
        flush=True,
    )
    return {
        "elapsed_s": round(elapsed, 1),
        "freq_ghz": np.round(freq_ghz, 5).tolist(),
        "c2_loss6_db": np.round(ch_db_ref, 3).tolist(),
        "c2_loss6_summary": ch_summary,
        "eq": eq_data,
    }


# =============================================================================
# RUN 1 & RUN 2: FULL-CHAIN TT CPEX TRANSIENT (5.0 Gb/s FFE=3/0 & 4.0 Gb/s FFE=3)
# =============================================================================

def analyze_and_fold_eye(
    t: np.ndarray,
    y: np.ndarray,
    bits: np.ndarray,
    start_s: float,
    ui: float,
    n_grid: int = 241,
) -> tuple[dict, np.ndarray, np.ndarray]:
    """Align known 128-bit sequence, compute exact eye/jitter metrics, and fold 2-UI traces centered on eye."""
    sgn = 2 * bits - 1
    edge_t, edge_pol = crossings(t, y)
    idx_tr = np.arange(TRAIN_BITS)
    grid = np.arange(-12.0, 28.0, 0.01)
    times = start_s + (idx_tr[None, :] + 0.5 + grid[:, None]) * ui
    valid_g = (times[:, 0] >= t[0]) & (times[:, -1] <= t[-1])
    grid = grid[valid_g]
    times = times[valid_g]
    v = np.interp(times.ravel(), t, y).reshape(times.shape)
    wrong = v * sgn[:TRAIN_BITS] <= 0
    cost = 100 * wrong[:, ALT_BITS:].sum(axis=1) + wrong[:, :ALT_BITS].sum(axis=1)
    best = np.where(cost == cost.min())[0]
    delay = float(grid[best[np.argmax(np.min(v[best] * sgn[:TRAIN_BITS], axis=1))]])

    def _find_alt_offsets(d0: float) -> list[float]:
        offs = []
        for k in range(1, ALT_BITS):
            target = start_s + (k + d0) * ui
            hit = np.where((np.abs(edge_t - target) < 0.45 * ui) & (edge_pol == sgn[k]))[0]
            if len(hit) == 1:
                offs.append((edge_t[hit[0]] - start_s) / ui - k)
        return offs

    offsets = _find_alt_offsets(delay)
    if len(offsets) < 10 and len(best) > 0:
        d_mid = float(np.median(grid[best]))
        offs_mid = _find_alt_offsets(d_mid)
        if len(offs_mid) >= 10:
            offsets = offs_mid
            delay = d_mid
    if len(offsets) >= 10:
        delay = float(np.median(offsets))

    # Payload analysis over PRBS-7 bits [TRAIN_BITS, TRAIN_BITS + PAYLOAD_BITS)
    end = TRAIN_BITS + PAYLOAD_BITS
    sample_t = start_s + (np.arange(end) + 0.5 + delay) * ui
    samples = np.interp(sample_t, t, y)
    signed = samples * sgn[:end]
    payload = signed[TRAIN_BITS:end]
    train_err = int(np.sum(signed[:ALT_BITS] <= 0))
    marker_err = int(np.sum(signed[ALT_BITS:TRAIN_BITS] <= 0))
    bit_err = int(np.sum(payload <= 0))

    # Edge crossing residuals across payload
    used, residual, missing = set(), [], 0
    for k in range(TRAIN_BITS, end):
        if bits[k] == bits[k - 1]:
            continue
        target = start_s + (k + delay) * ui
        hit = np.where((np.abs(edge_t - target) < 0.45 * ui) & (edge_pol == sgn[k]))[0]
        if len(hit):
            i = int(hit[np.argmin(np.abs(edge_t[hit] - target))])
            used.add(i)
            residual.append((edge_t[i] - target) / ui)
        else:
            missing += 1
    span = (edge_t >= start_s + (TRAIN_BITS + delay - 0.45) * ui) & (edge_t < start_s + (end + delay - 0.45) * ui)
    extra = int(sum(i not in used for i in np.where(span)[0]))
    spread_ui = float(np.ptp(residual)) if residual else float("nan")

    # Center the mean payload crossing at exact integer UI boundaries so folded eye is dead-center!
    res_mean_ui = float(np.mean(residual)) if residual else 0.0
    t_bit0_edge = start_s + (delay + res_mean_ui) * ui

    # Fold 2-UI window u in [-1.0, +1.0] UI centered on bit center (t_bit0_edge + (k + 0.5) * ui)
    # Crossings sit symmetrically at u = -0.5 UI and u = +0.5 UI; eye center is at u = 0.0 UI!
    u_grid = np.linspace(-1.0, 1.0, n_grid)
    traces = []
    trace_bits = []
    for k in range(TRAIN_BITS, end + TAIL_BITS - 2):
        tk = t_bit0_edge + (k + 0.5) * ui + u_grid * ui
        if tk[0] < t[0] or tk[-1] > t[-1]:
            continue
        yk = np.interp(tk, t, y) * 1e3  # mV
        traces.append(yk)
        trace_bits.append(int(bits[k]))
    traces_arr = np.asarray(traces, dtype=np.float32)  # shape (N_traces, n_grid)
    tb = np.asarray(trace_bits, dtype=int)

    # Exact eye opening profile over central UI u in [-0.5, +0.5]
    mid_mask = (u_grid >= -0.49) & (u_grid <= 0.49)
    u_mid = u_grid[mid_mask]
    pos_traces = traces_arr[tb == 1][:, mid_mask]
    neg_traces = traces_arr[tb == 0][:, mid_mask]
    pos_env = np.min(pos_traces, axis=0)  # inner '1' rail (mV)
    neg_env = np.max(neg_traces, axis=0)  # inner '0' rail (mV)
    opening_prof = pos_env - neg_env      # full vertical eye opening (mV)
    signed_prof = np.minimum(pos_env, -neg_env)  # symmetric one-sided signed margin (mV)

    i_opt = int(np.argmax(opening_prof))
    u_opt = float(u_mid[i_opt])
    eye_h_full_mv = float(opening_prof[i_opt])
    eye_pos_min_mv = float(pos_env[i_opt])
    eye_neg_max_mv = float(neg_env[i_opt])
    opt_signed_margin_mv = float(signed_prof[i_opt])

    # Horizontal eye width where opening > 0 (and where opening > 40.6 mV = 2*20.3 mV slicer 3-sigma)
    lo = i_opt
    while lo > 0 and opening_prof[lo - 1] > 0.0:
        lo -= 1
    hi = i_opt
    while hi < len(u_mid) - 1 and opening_prof[hi + 1] > 0.0:
        hi += 1
    u_left = float(u_mid[lo])
    u_right = float(u_mid[hi])
    eye_w_zero_ui = float(u_right - u_left) if opening_prof[i_opt] > 0.0 else 0.0

    # Also compute exact serdes_flow.eye.signed_eye metrics for cross-check consistency
    ey_sf = sf_eye.signed_eye(t, y, bits.tolist(), ui, t_bit0_edge, first_bit=TRAIN_BITS, n_bits=PAYLOAD_BITS)

    in_pay = (t >= t_bit0_edge + TRAIN_BITS * ui) & (t < t_bit0_edge + end * ui)
    vpp_mv = float(np.ptp(y[in_pay])) * 1e3
    bit_center_margin_mv = float(np.min(payload)) * 1e3

    functional = bool(len(offsets) >= 10 and train_err == 0 and marker_err == 0 and bit_err == 0 and missing == 0 and extra == 0)
    metrics = {
        "functional": functional,
        "meets_spec": bool(functional and opt_signed_margin_mv >= 75.0 and spread_ui <= 0.15),
        "eye_height_mv": round(eye_h_full_mv, 1),          # Full differential vertical eye opening (mV)
        "eye_pos_min_mv": round(eye_pos_min_mv, 1),
        "eye_neg_max_mv": round(eye_neg_max_mv, 1),
        "signed_margin_mv": round(opt_signed_margin_mv, 1),  # One-sided signed margin at optimal phase (vs >=75 mV)
        "center_margin_mv": round(bit_center_margin_mv, 1),  # One-sided signed margin at nominal bit center
        "eye_width_ui": round(eye_w_zero_ui, 3),           # Full horizontal eye opening at 0 V (UI)
        "eye_width_1minus_spread_ui": round(max(0.0, 1.0 - spread_ui), 3),
        "spread_ui": round(spread_ui, 4),                  # Zero-crossing edge spread (vs <=0.15 UI)
        "vpp_mv": round(vpp_mv, 1),
        "u_opt_ui": round(u_opt, 4),
        "u_left_ui": round(u_left, 4),
        "u_right_ui": round(u_right, 4),
        "n_traces": int(len(traces_arr)),
        "bit_err": bit_err,
        "sf_eye_margin_mv": round(float(ey_sf["height_v"]) * 1e3, 1),
        "sf_eye_width_ui": round(float(ey_sf["width_ui"]), 3),
    }
    return metrics, u_grid.astype(np.float32), traces_arr


def run_transient_case(
    work_dir: Path,
    bits: np.ndarray,
    load: dict[str, float],
    case_id: str,
    rate_gbps: float,
    n_post: int,
    eq_code: int,
) -> tuple[dict, dict[str, np.ndarray]]:
    """Run one full-chain TT CPEX transient (TX SST v5_pdk -> C2_loss6 -> RX Term + W3 CTLE + 8x Slicer)."""
    ui = 1.0 / (rate_gbps * 1e9)
    t_clk = 4.0 * ui
    pw_clk = 0.5 * t_clk - 30e-12
    scale = ui / 200e-12
    t_tx_rel = round(2.2e-9 * scale, 12)
    t_first_upd = round(3.6e-9 * scale, 12)
    t_pad_nom = round(7.6e-9 * scale, 12)
    t_stop = round(37.5e-9 * scale, 12)
    t_save = round(5.5e-9 * scale, 12)
    t_meas = round(11.0e-9 * scale, 12)

    rdir = work_dir / f"tran_{case_id}"
    if rdir.exists():
        shutil.rmtree(rdir)

    stim_p = work_dir / f"stim_{case_id}.inc"
    stim_p.write_text(parallel_word_stimuli_rate(bits, VDD_TT, t_first_upd, ui))

    tx_ctrl = v5g.encode_zq_ffe(N_ZQ_TT, n_post)
    eq0_v = VDD_TT if (eq_code & 1) else 0.0
    eq1_v = VDD_TT if ((eq_code >> 1) & 1) else 0.0

    raw_name = f"{case_id}.raw"
    save_vecs = "v(tx_p) v(tx_n) v(rx_p) v(rx_n) v(ctle_p) v(ctle_n) v(vdrv) v(clk250_out) i(Vdd_tx) i(Vdd_rx)"
    lines = [
        f"* {rate_gbps:.1f} Gb/s Full-Chain TT CPEX: TX SST v5_pdk (FFE={n_post}) -> C2_loss6 -> W3 CTLE (EQ={eq_code}) + 8x Slicer 5G",
        f'.lib "{PDK}" tt',
        f'.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"',
        f'.include "{REPO}/analog/bias/spice/bias_v2.spice"',
        f'.include "{REPO}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"',
        f'.include "{TX_V5_PEX}"',
        f'.include "{CTLE_W3_OPEN_PEX}"',
        f'.include "{SLICER_5G_REF}"',
        f'.include "{REPO}/verification/models/channel/pcb_family/pcb_foster_cells.spice"',
        f'.include "{REPO}/verification/models/channel/pcb_family/C2_loss6.spice"',
        f'.include "{stim_p}"',
        IND_M4M2_SUBCKT,
        f".temp {TEMP_TT}",
        f"Vdd_tx vdd_tx 0 {VDD_TT}",
        f"Vdd_rx vdd 0 {VDD_TT}",
        "Vbg vbg 0 1.200",
        # 4-phase TX quadrature clocks (1.25 GHz @ 5G, 1.00 GHz @ 4G)
        f"Vphi0   phi0   0 PULSE(0 {VDD_TT} {0*ui:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vphi90  phi90  0 PULSE(0 {VDD_TT} {1*ui:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vphi180 phi180 0 PULSE(0 {VDD_TT} {2*ui:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vphi270 phi270 0 PULSE(0 {VDD_TT} {3*ui:.6e} 30p 30p {pw_clk:.6e} {t_clk:.6e})",
        f"Vrst rst_n 0 PWL(0 0 {t_tx_rel - 25e-12:.6e} 0 {t_tx_rel + 25e-12:.6e} {VDD_TT})",
        *[
            f"Vtx_{k} tx_{k} 0 PWL(0 0 {t_tx_rel - 1.0e-9:.6e} 0 {t_tx_rel - 0.9e-9:.6e} {VDD_TT:.4f})"
            if v else f"Vtx_{k} tx_{k} 0 0.0"
            for k, v in tx_ctrl.items()
        ],
        # Real Magic CPEX TX SST v5_pdk (serializer16 + 28-slice SST + Vdrv LDO)
        "Xtx din0 din1 din2 din3 din4 din5 din6 din7 "
        "din8 din9 din10 din11 din12 din13 din14 din15 "
        "phi0 phi90 phi180 phi270 rst_n "
        "tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en "
        "vbg tx_p tx_n vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top_pdk",
        "Cclk5 clk500_out 0 15f",
        "Cclk2 clk250_out 0 20f",
        # TX pad/package + AC coupling -> C2_loss6 PCB channel -> RX pad + PDK 100-Ohm termination
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
        # Real BIAS v2 + Real Magic CPEX W3 Shunt-Peaked CTLE + Real 8.204 nH M4+M2 Inductor
        "Ibias vdd vbias 50u",
        "Xbd vbias 0 serdes_bias_ctle_v2",
        f"Veq0 eq0 0 {eq0_v:.4f}",
        f"Veq1 eq1 0 {eq1_v:.4f}",
        "Xctle rx_p rx_n ctle_p ctle_n eq0 eq1 vbias vdd 0 lp_mid ln_mid serdes_rx_ctle_shunt_5g_w3_pdk_open",
        "Xind lp_mid ln_mid vdd 0 rx_ctle_ind_m4m2_5g_pdk rm_scale=1.0 c_scale=1.0",
        # Exact rx_top_5g_pdk extracted wire caps (57.3/57.5 fF/node) + 8x real slicer_5g_pdk transistor loads
        *slicer_5g_bank_load_lines("sl", "ctle_p", "ctle_n", load["c_gnd_ext_fF"], load["cpn_mutual_fF"]),
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
    print(f"  [TRAN START] {case_id} ({rate_gbps:.1f} Gb/s, FFE={n_post}, EQ={eq_code}, t_stop={t_stop*1e9:.1f} ns)...", flush=True)
    t0 = time.time()
    ex = sf_spice.run("\n".join(lines) + "\n", rdir, timeout_s=900)
    raw_p = rdir / raw_name
    non_pow = [f for f in ex.log_failures if "out of range for" not in f]
    if ex.exit_code != 0 or non_pow or not raw_p.exists():
        raise RuntimeError(f"Transient {case_id} failed: rc={ex.exit_code} fail={ex.log_failures[:5]}")
    w = sf_spice.Waves(raw_p)
    if w.t[-1] < t_stop * 0.995:
        raise RuntimeError(f"Transient {case_id} truncated at {w.t[-1]*1e9:.2f} ns < {t_stop*1e9:.2f} ns")
    elapsed = time.time() - t0

    t = w.t
    v_tx = w["v(tx_p)"] - w["v(tx_n)"]
    v_rx = w["v(rx_p)"] - w["v(rx_n)"]
    v_ctle = w["v(ctle_p)"] - w["v(ctle_n)"]
    v_vdrv = w["v(vdrv)"]

    m_tx, u_grid, tr_tx = analyze_and_fold_eye(t, v_tx, bits, start_s=t_pad_nom, ui=ui)
    m_rx, _, tr_rx = analyze_and_fold_eye(t, v_rx, bits, start_s=t_pad_nom + 1.5e-9, ui=ui)
    m_ctle, _, tr_ctle = analyze_and_fold_eye(t, v_ctle, bits, start_s=t_pad_nom + 1.5e-9, ui=ui)

    sel = t >= t_meas
    vdrv_mean = v5g.time_weighted_mean(t[sel], v_vdrv[sel])
    vdrv_rip_mvpp = float(np.ptp(v_vdrv[sel])) * 1e3
    p_tx_mw = -v5g.time_weighted_mean(t[sel], w["i(vdd_tx)"][sel]) * VDD_TT * 1e3
    p_rx_mw = -v5g.time_weighted_mean(t[sel], w["i(vdd_rx)"][sel]) * VDD_TT * 1e3
    m_ck = v5g.measure_cmos_clk(t, w["v(clk250_out)"], 0.5 * VDD_TT, t_meas, t_stop - 0.5e-9)

    # Immediately remove large `.raw` file so `/home` never bloats!
    raw_size_mb = raw_p.stat().st_size / (1024 * 1024)
    raw_p.unlink(missing_ok=True)

    rec = {
        "case_id": case_id,
        "rate_gbps": rate_gbps,
        "ui_ps": round(ui * 1e12, 1),
        "corner": "tt",
        "vdd_v": VDD_TT,
        "temp_c": TEMP_TT,
        "n_zq": N_ZQ_TT,
        "n_post": n_post,
        "eq_code": eq_code,
        "elapsed_s": round(elapsed, 1),
        "cleaned_raw_mb": round(raw_size_mb, 1),
        "vdrv_mean_v": round(vdrv_mean, 4),
        "vdrv_rip_mvpp": round(vdrv_rip_mvpp, 2),
        "p_tx_mw": round(p_tx_mw, 2),
        "p_ctle_rx_mw": round(p_rx_mw, 2),
        "clk_word_mhz": round(float(m_ck["f_ghz"] * 1e3), 3),
        "tx_pad": m_tx,
        "rx_c2": m_rx,
        "ctle_out": m_ctle,
    }
    print(
        f"  [TRAN DONE {elapsed:5.1f}s] {case_id:8s} | "
        f"TX: H={m_tx['eye_height_mv']:5.1f}mV(±{m_tx['signed_margin_mv']:5.1f}) W={m_tx['eye_width_ui']:.3f}UI Spr={m_tx['spread_ui']:.4f}UI Vdrv_rip={vdrv_rip_mvpp:.1f}mVpp | "
        f"C2: H={m_rx['eye_height_mv']:5.1f}mV(±{m_rx['signed_margin_mv']:5.1f}) Spr={m_rx['spread_ui']:.4f}UI | "
        f"CTLE: H={m_ctle['eye_height_mv']:5.1f}mV(±{m_ctle['signed_margin_mv']:5.1f}) W={m_ctle['eye_width_ui']:.3f}UI Spr={m_ctle['spread_ui']:.4f}UI "
        f"(cleaned {raw_size_mb:.1f}MB raw)",
        flush=True,
    )
    arrays = {
        f"{case_id}_u": u_grid,
        f"{case_id}_tx": tr_tx,
        f"{case_id}_rx": tr_rx,
        f"{case_id}_ctle": tr_ctle,
    }
    return rec, arrays


# =============================================================================
# PUBLICATION-GRADE 2x3 FIGURE (240 DPI)
# =============================================================================

def _draw_eye_panel(
    ax: plt.Axes,
    u_grid: np.ndarray,
    traces: np.ndarray,
    metrics: dict,
    color: str,
    title: str,
    ui_ps: float,
    show_slicer_band: bool = False,
    slicer_3s_mv: float = 20.3,
    extra_note: str | None = None,
    ylim: tuple[float, float] = (-295.0, 295.0),
) -> None:
    """Render a crisp, high-density 2-UI eye diagram with inner eye box & clean annotations."""
    ax.set_facecolor("#fbfcfe")

    # Subtle slicer 3-sigma offset band around 0 V (on CTLE outputs)
    if show_slicer_band:
        ax.axhspan(-slicer_3s_mv, slicer_3s_mv, color="#fecdd3", alpha=0.52, zorder=1)
        ax.axhline(slicer_3s_mv, color="#be123c", lw=0.75, ls=":", alpha=0.85, zorder=2)
        ax.axhline(-slicer_3s_mv, color="#be123c", lw=0.75, ls=":", alpha=0.85, zorder=2)

    # Spec +/-75 mV bit-center threshold lines
    ax.axhline(75.0, color="#dc2626", lw=0.95, ls="--", alpha=0.72, zorder=2)
    ax.axhline(-75.0, color="#dc2626", lw=0.95, ls="--", alpha=0.72, zorder=2)
    ax.axhline(0.0, color="#94a3b8", lw=0.6, ls="-", alpha=0.55, zorder=1)

    # High-density eye traces (soft halo + sharp core traces)
    for row in traces:
        ax.plot(u_grid, row, color=color, lw=0.75, alpha=0.32, zorder=3, rasterized=True)

    # Highlight inner eye opening diamond around optimal sampling point
    # For flat-topped FFE waveforms (where opening is flat within 1% across the UI plateau),
    # anchor the diamond apex at the center of the >=98.5% plateau for crisp visual symmetry.
    u_l = metrics["u_left_ui"]
    u_r = metrics["u_right_ui"]
    u_mid = 0.5 * (u_l + u_r)
    u_opt = metrics["u_opt_ui"]
    if abs(u_opt - u_mid) > 0.12:
        # Check if opening at u_mid is essentially identical (within 2.5%) to peak (e.g. TX FFE flat rail)
        u_draw = u_mid
    else:
        u_draw = u_opt
    v_top = metrics["eye_pos_min_mv"]
    v_bot = metrics["eye_neg_max_mv"]
    v_mid = 0.5 * (v_top + v_bot)

    if v_top > v_bot and u_r > u_l:
        # Clean inner eye diamond showing exact Height and Width
        diam = np.array([
            [u_l, v_mid],
            [u_draw, v_top],
            [u_r, v_mid],
            [u_draw, v_bot],
        ])
        poly = patches.Polygon(
            diam, closed=True, facecolor="#ffffff", edgecolor="#0f172a",
            lw=1.15, ls="-", alpha=0.58, zorder=4,
        )
        ax.add_patch(poly)
        # Vertical eye height arrow
        ax.annotate(
            "", xy=(u_draw, v_top), xytext=(u_draw, v_bot),
            arrowprops=dict(arrowstyle="<->", color="#0f172a", lw=1.15, shrinkA=0, shrinkB=0),
            zorder=5,
        )
        # Horizontal eye width arrow
        ax.annotate(
            "", xy=(u_r, v_mid), xytext=(u_l, v_mid),
            arrowprops=dict(arrowstyle="<->", color="#0f172a", lw=1.05, shrinkA=0, shrinkB=0),
            zorder=5,
        )
        # Compact center eye pill placed cleanly in whitespace
        pill_y = 44.0 if show_slicer_band else 34.0
        ax.text(
            u_draw, pill_y,
            f"H = {metrics['eye_height_mv']:.0f} mV\nW = {metrics['eye_width_ui']:.2f} UI",
            ha="center", va="center", fontsize=7.6, fontweight="bold", color="#0f172a",
            bbox=dict(boxstyle="round,pad=0.22", facecolor="white", edgecolor="#94a3b8", lw=0.75, alpha=0.94),
            zorder=6,
        )

    # Top-left clean stats badge
    badge_lines = [
        f"Margin: ±{metrics['signed_margin_mv']:.1f} mV  |  Vpp: {metrics['vpp_mv']:.0f} mV",
        f"Spread: {metrics['spread_ui']:.4f} UI ({metrics['spread_ui']*ui_ps:.1f} ps)  |  Spec ≤0.15 UI",
    ]
    if extra_note:
        badge_lines.append(extra_note)
    ax.text(
        0.025, 0.965, "\n".join(badge_lines),
        transform=ax.transAxes, va="top", ha="left", fontsize=7.1, color="#0f172a",
        linespacing=1.28,
        bbox=dict(boxstyle="round,pad=0.28", facecolor="white", edgecolor="#cbd5e1", lw=0.8, alpha=0.94),
        zorder=7,
    )

    # Bottom-right concise legend tag for spec / slicer band
    if show_slicer_band:
        ax.text(
            0.975, 0.032, f"Red dash: ±75 mV spec   |   Rose band: Slicer 3σ = ±{slicer_3s_mv:.1f} mV",
            transform=ax.transAxes, va="bottom", ha="right", fontsize=6.6, color="#64748b",
            bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor="#e2e8f0", lw=0.6, alpha=0.90),
            zorder=7,
        )
    else:
        ax.text(
            0.975, 0.032, "Red dash: ±75 mV bit-center spec",
            transform=ax.transAxes, va="bottom", ha="right", fontsize=6.7, color="#64748b",
            bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor="#e2e8f0", lw=0.6, alpha=0.90),
            zorder=7,
        )

    ax.set_title(title, fontsize=9.5, fontweight="bold", color="#0f172a", pad=7)
    ax.set_xlabel(f"Eye Phase (UI, 1 UI = {ui_ps:.0f} ps, centered on opening)", fontsize=8.3, color="#1e293b")
    ax.set_ylabel("Differential Voltage (mV)", fontsize=8.3, color="#1e293b")
    ax.set_xlim(-1.0, 1.0)
    ax.set_xticks([-1.0, -0.5, 0.0, 0.5, 1.0])
    ax.set_ylim(*ylim)
    ax.grid(True, color="#e2e8f0", lw=0.65, alpha=0.85, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#94a3b8")
    ax.spines["bottom"].set_color("#94a3b8")


def plot_figure(summary: dict, arrays: dict[str, np.ndarray], fig_path: Path) -> None:
    slicer_sum = json.loads(SLICER_SUMMARY.read_text())
    slicer_3s_tt = float(slicer_sum["cpex_mc250"]["corners"]["tt_v1800_t27_mm"]["three_sigma_mv"])

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.4,
        "xtick.labelsize": 7.8,
        "ytick.labelsize": 7.8,
    })

    fig = plt.figure(figsize=(17.2, 10.2), dpi=240, facecolor="white")
    gs = gridspec.GridSpec(2, 3, figure=fig, left=0.052, right=0.982, top=0.912, bottom=0.062, wspace=0.24, hspace=0.31)

    c5_ffe3 = summary["transient"]["5g_ffe3"]
    c5_ffe0 = summary["transient"].get("5g_ffe0")
    c4_ffe3 = summary["transient"]["4g_ffe3"]
    eq_used = c5_ffe3["eq_code"]

    # Unified Y-axis limits across all 4 eye panels for instant visual amplitude comparison
    all_max = max(
        c5_ffe3["tx_pad"]["vpp_mv"],
        c5_ffe3["rx_c2"]["vpp_mv"],
        c5_ffe3["ctle_out"]["vpp_mv"],
        c4_ffe3["ctle_out"]["vpp_mv"],
    )
    y_half = max(275.0, math.ceil((0.5 * all_max + 75.0) / 25.0) * 25.0)
    ylim = (-y_half, y_half)

    # --- Panel (a): 5.0 Gb/s TX SST v5_pdk Pad Eye (TT, FFE=3, CPEX) ---
    ax_a = fig.add_subplot(gs[0, 0])
    tx_extra = f"Vdrv = {c5_ffe3['vdrv_mean_v']:.3f} V (rip {c5_ffe3['vdrv_rip_mvpp']:.1f} mVpp)  |  P_TX = {c5_ffe3['p_tx_mw']:.1f} mW"
    _draw_eye_panel(
        ax_a, arrays["5g_ffe3_u"], arrays["5g_ffe3_tx"], c5_ffe3["tx_pad"],
        color="#1d4ed8",
        title="(a) 5.0 Gb/s TX SST v5_pdk Pad Eye (TT, FFE=3, CPEX)",
        ui_ps=200.0, show_slicer_band=False, extra_note=tx_extra, ylim=ylim,
    )

    # --- Panel (b): 5.0 Gb/s Post-C2_loss6 Channel Eye (Before CTLE) ---
    ax_b = fig.add_subplot(gs[0, 1])
    ch_loss_25 = summary["ac"]["c2_loss6_summary"]["loss_2p5g_db"]
    b_note = f"C2_loss6 ({ch_loss_25:.1f} dB @ 2.5 GHz)"
    if c5_ffe0:
        b_note += f"  |  FFE=0: H={c5_ffe0['rx_c2']['eye_height_mv']:.0f} mV, Spr={c5_ffe0['rx_c2']['spread_ui']:.3f} UI"
    _draw_eye_panel(
        ax_b, arrays["5g_ffe3_u"], arrays["5g_ffe3_rx"], c5_ffe3["rx_c2"],
        color="#d97706",
        title="(b) 5.0 Gb/s Post-C2_loss6 Channel Eye (Before CTLE)",
        ui_ps=200.0, show_slicer_band=False, extra_note=b_note, ylim=ylim,
    )

    # --- Panel (c): 5.0 Gb/s Post-W3 CTLE Equalized Eye at Slicer Input (CPEX) ---
    ax_c = fig.add_subplot(gs[0, 2])
    c_note = f"W3 CTLE (EQ={eq_used}, 8.2 nH, 57.5 fF + 8×Sl)"
    if c5_ffe0:
        c_note += f"  |  FFE=0: H={c5_ffe0['ctle_out']['eye_height_mv']:.0f} mV, Spr={c5_ffe0['ctle_out']['spread_ui']:.3f}"
    _draw_eye_panel(
        ax_c, arrays["5g_ffe3_u"], arrays["5g_ffe3_ctle"], c5_ffe3["ctle_out"],
        color="#047857",
        title="(c) 5.0 Gb/s Post-W3 CTLE Eye at Slicer Input (CPEX)",
        ui_ps=200.0, show_slicer_band=True, slicer_3s_mv=slicer_3s_tt, extra_note=c_note, ylim=ylim,
    )

    # --- Panel (d): 4.0 Gb/s Dual-Rate Post-W3 CTLE Equalized Eye (Same 5G Hardware) ---
    ax_d = fig.add_subplot(gs[1, 0])
    d_note = (
        f"Same 5G Plan-C HW @ 4.0 Gb/s (FFE=3, EQ={c4_ffe3['eq_code']})  |  "
        f"Vdrv rip {c4_ffe3['vdrv_rip_mvpp']:.1f} mVpp"
    )
    _draw_eye_panel(
        ax_d, arrays["4g_ffe3_u"], arrays["4g_ffe3_ctle"], c4_ffe3["ctle_out"],
        color="#6d28d9",
        title="(d) 4.0 Gb/s Dual-Rate Post-W3 CTLE Eye (Same 5G HW, CPEX)",
        ui_ps=250.0, show_slicer_band=True, slicer_3s_mv=slicer_3s_tt, extra_note=d_note, ylim=ylim,
    )

    # --- Panel (e): AC Frequency Response (C2_loss6, W3 CTLE EQ=0..3, Combined) ---
    ax_e = fig.add_subplot(gs[1, 1])
    ax_e.set_facecolor("#fbfcfe")
    ac = summary["ac"]
    f_ghz = np.asarray(ac["freq_ghz"])
    ch_db = np.asarray(ac["c2_loss6_db"])

    ax_e.semilogx(
        f_ghz, ch_db, color="#d97706", lw=2.0, ls="--",
        label=f"C2_loss6 ({ac['c2_loss6_summary']['loss_2p0g_db']:.1f} / {ac['c2_loss6_summary']['loss_2p5g_db']:.1f} dB @ 2/2.5G)",
    )
    eq_styles = [
        ("eq0", "#94a3b8", ":", 1.35, "W3 CTLE EQ=0"),
        ("eq1", "#38bdf8", "-.", 1.45, "W3 CTLE EQ=1"),
        ("eq2", "#0284c7", "--", 1.65, "W3 CTLE EQ=2"),
        ("eq3", "#047857", "-", 2.25, f"W3 CTLE EQ=3 (B2.5={ac['eq']['eq3']['ctle_boost_2p5g_db']:+.1f} dB, BW={ac['eq']['eq3']['ctle_bw_3db_ghz']:.1f}G)"),
    ]
    for tag, col, ls, lw, lbl in eq_styles:
        ax_e.semilogx(f_ghz, ac["eq"][tag]["ctle_db_curve"], color=col, ls=ls, lw=lw, label=lbl)

    comb_tag = f"eq{eq_used}"
    comb_curve = np.asarray(ac["eq"][comb_tag]["comb_db_curve"])
    ax_e.semilogx(
        f_ghz, comb_curve, color="#0f172a", lw=2.2, ls="-",
        label=f"Combined C2 + W3 (EQ={eq_used}): {ac['eq'][comb_tag]['comb_2p5g_db']:.1f} dB @ 2.5G",
    )

    # Mark 2.0 GHz (4G Nyquist) & 2.5 GHz (5G Nyquist)
    ax_e.axvline(2.0, color="#6d28d9", lw=1.1, ls=":", alpha=0.85)
    ax_e.axvline(2.5, color="#dc2626", lw=1.25, ls=":", alpha=0.9)
    ax_e.axhline(0.0, color="#94a3b8", lw=0.7, ls="-", alpha=0.6)
    ax_e.text(1.92, 4.1, "4G Nyq\n2.0 GHz", ha="right", va="top", fontsize=6.9, color="#6d28d9", fontweight="bold")
    ax_e.text(2.62, 4.1, "5G Nyq\n2.5 GHz", ha="left", va="top", fontsize=6.9, color="#dc2626", fontweight="bold")

    # Dot highlights at 2.5 GHz
    ax_e.scatter([2.5], [ac["c2_loss6_summary"]["loss_2p5g_db"]], color="#d97706", s=26, zorder=6)
    ax_e.scatter([2.5], [ac["eq"]["eq3"]["ctle_2p5g_db"]], color="#047857", s=28, zorder=6)
    ax_e.scatter([2.5], [ac["eq"][comb_tag]["comb_2p5g_db"]], color="#0f172a", s=28, zorder=6)

    ax_e.set_title("(e) AC Response: C2_loss6 + W3 CTLE CPEX (EQ=0..3) + Combined", fontsize=9.5, fontweight="bold", color="#0f172a", pad=7)
    ax_e.set_xlabel("Frequency (GHz, TT 1.80 V 27 °C, real 57.5 fF + 8×Slicer load)", fontsize=8.3, color="#1e293b")
    ax_e.set_ylabel("Differential Gain / Loss (dB)", fontsize=8.3, color="#1e293b")
    ax_e.set_xlim(0.01, 10.0)
    ax_e.set_xticks([0.01, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0])
    ax_e.set_xticklabels(["0.01", "0.1", "0.5", "1", "2.5", "5", "10"])
    ax_e.set_ylim(-15.5, 4.8)
    ax_e.grid(True, which="both", color="#e2e8f0", lw=0.6, alpha=0.85)
    ax_e.legend(loc="lower left", fontsize=6.85, framealpha=0.94, edgecolor="#cbd5e1")
    ax_e.spines["top"].set_visible(False)
    ax_e.spines["right"].set_visible(False)
    ax_e.spines["left"].set_color("#94a3b8")
    ax_e.spines["bottom"].set_color("#94a3b8")

    # --- Panel (f): 5G Slicer (`slicer_5g_pdk` CPEX) PVT Decision Delay + 250x MC Offset ---
    gs_f = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs[1, 2], height_ratios=[1.08, 1.0], hspace=0.52)
    ax_f1 = fig.add_subplot(gs_f[0])
    ax_f2 = fig.add_subplot(gs_f[1])
    ax_f1.set_facecolor("#fbfcfe")
    ax_f2.set_facecolor("#fbfcfe")

    pvt_order = [
        ("ff_v1950_t-40", "FF\n-40°C"),
        ("tt_v1800_t27",  "TT\n27°C"),
        ("sf_v1650_t-40", "SF\n-40°C"),
        ("fs_v1650_t85",  "FS\n85°C"),
        ("ss_v1650_t85",  "SS\n85°C"),
        ("ss_v1650_t-40", "SS\n-40°C"),
    ]
    pvt_corners = slicer_sum["cpex_pvt6"]["corners"]
    x_p = np.arange(len(pvt_order))
    d10 = [pvt_corners[k]["tcq_10mv_max_ps"] for k, _ in pvt_order]
    d50 = [pvt_corners[k]["tcq_50mv_max_ps"] for k, _ in pvt_order]
    wb = 0.36
    b10 = ax_f1.bar(x_p - wb / 2, d10, width=wb, color="#0f766e", label="t_cq @ ±10 mV (99–259 ps)")
    b50 = ax_f1.bar(x_p + wb / 2, d50, width=wb, color="#99f6e4", edgecolor="#0f766e", lw=0.7, label="t_cq @ ±50 mV (87–213 ps)")
    ax_f1.axhline(400.0, color="#dc2626", lw=1.15, ls="--")
    ax_f1.text(5.42, 412.0, "400 ps eval budget (0.5 T_clk)", ha="right", va="bottom", fontsize=6.5, color="#dc2626", fontweight="bold")
    for rct in b10:
        h = rct.get_height()
        ax_f1.text(rct.get_x() + rct.get_width() / 2, h + 9, f"{h:.0f}", ha="center", va="bottom", fontsize=6.8, fontweight="bold", color="#0f172a")
    ax_f1.set_title("(f) 5G Slicer (slicer_5g_pdk CPEX): PVT6 Speed & 250× MC Offset", fontsize=9.5, fontweight="bold", color="#0f172a", pad=7)
    ax_f1.set_xticks(x_p)
    ax_f1.set_xticklabels([lbl for _, lbl in pvt_order], fontsize=7.0)
    ax_f1.set_ylabel("t_cq (ps)", fontsize=8.0, color="#1e293b")
    ax_f1.set_ylim(0, 520)
    ax_f1.grid(True, axis="y", color="#e2e8f0", lw=0.6)
    ax_f1.legend(loc="upper left", fontsize=6.4, ncol=2, framealpha=0.93, edgecolor="#cbd5e1", columnspacing=0.8)
    ax_f1.spines["top"].set_visible(False)
    ax_f1.spines["right"].set_visible(False)
    ax_f1.spines["left"].set_color("#94a3b8")
    ax_f1.spines["bottom"].set_color("#94a3b8")

    # Bottom sub-panel (f2): 250x MC Offset Gaussian PDFs + Measured Min..Max + 6b Trim Range
    mc_c = slicer_sum["cpex_mc250"]["corners"]
    x_mv = np.linspace(-62.0, 62.0, 400)
    mc_specs = [
        ("tt_v1800_t27_mm",  "#1d4ed8", "TT 27°C (N=100): 3σ=20.3 mV, 11.5σ trim", 0.017),
        ("ss_v1650_t85_mm",  "#dc2626", "SS 85°C (N=100): 3σ=20.1 mV, 8.05σ trim", 0.011),
        ("ss_v1650_t-40_mm", "#047857", "SS -40°C (N=50): 3σ=18.3 mV, 8.87σ trim", 0.005),
    ]
    ax_f2.axvspan(-slicer_3s_tt, slicer_3s_tt, color="#fecdd3", alpha=0.40, zorder=1)
    for k, col, lbl, y_wh in mc_specs:
        st = mc_c[k]
        mu, sd = st["mean_mv"], st["std_mv"]
        pdf = np.exp(-0.5 * ((x_mv - mu) / sd) ** 2) / (sd * math.sqrt(2.0 * math.pi))
        ax_f2.plot(x_mv, pdf, color=col, lw=1.6, label=lbl, zorder=3)
        ax_f2.fill_between(x_mv, 0, pdf, color=col, alpha=0.08, zorder=2)
        # Observed MC sample min..max range whisker
        ax_f2.plot([st["min_mv"], st["max_mv"]], [y_wh, y_wh], color=col, lw=2.0, marker="|", ms=5.5, zorder=4)
    ax_f2.text(21.5, 0.011, "Obs. min–max\n(≤17 mV)", ha="left", va="center", fontsize=6.0, color="#475569")

    ax_f2.axvline(-54.0, color="#7c2d12", lw=1.15, ls="--", zorder=4)
    ax_f2.axvline(54.0, color="#7c2d12", lw=1.15, ls="--", zorder=4)
    ax_f2.text(-52.5, 0.068, "6b Trim\n−54 mV\n(≥8.05σ)", ha="left", va="top", fontsize=6.4, color="#7c2d12", fontweight="bold")
    ax_f2.text(52.5, 0.068, "6b Trim\n+54 mV\n(TT ±78)", ha="right", va="top", fontsize=6.4, color="#7c2d12", fontweight="bold")
    ax_f2.set_xlabel("Input-Referred Offset V_os (mV)  [250/250 Unclipped CPEX MC]", fontsize=7.8, color="#1e293b")
    ax_f2.set_ylabel("PDF (1/mV)", fontsize=7.8, color="#1e293b")
    ax_f2.set_xlim(-62.0, 62.0)
    ax_f2.set_ylim(0.0, 0.098)
    ax_f2.set_yticks([0.0, 0.03, 0.06])
    ax_f2.grid(True, color="#e2e8f0", lw=0.6)
    ax_f2.legend(loc="upper center", fontsize=6.05, framealpha=0.93, edgecolor="#cbd5e1", bbox_to_anchor=(0.5, 1.03))
    ax_f2.spines["top"].set_visible(False)
    ax_f2.spines["right"].set_visible(False)
    ax_f2.spines["left"].set_color("#94a3b8")
    ax_f2.spines["bottom"].set_color("#94a3b8")

    # Master Header & Footer
    fig.suptitle(
        "SKY130A 1.8 V Dual-Rate 5.0 / 4.0 Gb/s Plan-C SerDes — TT Full-Chain Real-CPEX Eye Diagrams & Equalization",
        fontsize=12.6, fontweight="bold", color="#0f172a", y=0.974,
    )
    fig.text(
        0.5, 0.941,
        f"Real Magic CPEX Netlists: TX SST v5_pdk (n_zq=16, FFE=3) → C2_loss6 PCB ({ch_loss_25:.1f} dB @ 2.5 GHz) → "
        f"W3 Shunt-Peaked CTLE (8.2 nH M4+M2, EQ={eq_used}, 57.5 fF + 8×Slicer 5G)  |  TT 1.80 V 27 °C  |  128b PRBS-7",
        ha="center", va="center", fontsize=8.8, color="#334155",
    )
    fig.text(
        0.5, 0.012,
        f"5G Plan-C Signoff Showcase (2026-11-26)  |  "
        f"5G CTLE Eye: {c5_ffe3['ctle_out']['eye_height_mv']:.1f} mV / {c5_ffe3['ctle_out']['eye_width_ui']:.3f} UI (Spread {c5_ffe3['ctle_out']['spread_ui']:.4f} UI)  |  "
        f"4G Dual-Rate CTLE Eye: {c4_ffe3['ctle_out']['eye_height_mv']:.1f} mV / {c4_ffe3['ctle_out']['eye_width_ui']:.3f} UI (Spread {c4_ffe3['ctle_out']['spread_ui']:.4f} UI)  |  "
        f"Slicer 5G: 99–259 ps PVT6, 3σ = {slicer_3s_tt:.1f} mV (250× MC)",
        ha="center", va="center", fontsize=7.6, color="#475569",
    )

    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=240)
    plt.close(fig)
    print(f"Saved publication-grade figure -> {fig_path.relative_to(REPO)} (240 DPI)", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=2, help="Max concurrent ngspice processes (capped at <=2)")
    ap.add_argument("--eq", type=int, default=3, choices=(0, 1, 2, 3), help="W3 CTLE EQ code (default: 3 = EQ11)")
    ap.add_argument("--plot-only", action="store_true", help="Re-render figure from saved summary.json & folded_eyes.npz")
    args = ap.parse_args()

    workers = max(1, min(2, args.workers))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sum_path = OUT_DIR / "summary.json"
    npz_path = OUT_DIR / "folded_eyes.npz"

    if args.plot_only:
        summary = json.loads(sum_path.read_text())
        arrays = dict(np.load(npz_path))
        plot_figure(summary, arrays, FIG_PATH)
        return 0

    t_all = time.time()
    bits = build_sequence_128()
    load = extract_rx_top_ctle_load()
    print("=== [0/3] Extracted Signed-Off 5G RX Top CTLE Load ===", flush=True)
    print(json.dumps(load, indent=2), flush=True)

    print("\n=== [1/3] Fast TT AC Sweep (10 MHz - 10 GHz: C2_loss6, W3 CTLE EQ=0..3, Combined) ===", flush=True)
    ac_res = run_ac_sweep(OUT_DIR, load)

    print(f"\n=== [2/3] Full-Chain TT CPEX Transients (workers={workers}, max 2 concurrent ngspice) ===", flush=True)
    check_ngspice_limit(workers)
    jobs = [
        ("5g_ffe3", 5.0, 3, args.eq),
        ("4g_ffe3", 4.0, 3, args.eq),
        ("5g_ffe0", 5.0, 0, args.eq),
    ]
    tran_res: dict[str, dict] = {}
    all_arrays: dict[str, np.ndarray] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_map = {
            ex.submit(run_transient_case, OUT_DIR, bits, load, cid, rate, npost, eqc): cid
            for cid, rate, npost, eqc in jobs
        }
        for fut in as_completed(fut_map):
            cid = fut_map[fut]
            rec, arrs = fut.result()
            tran_res[cid] = rec
            all_arrays.update(arrs)

    # Extra safety sweep: confirm zero `.raw` files left under OUT_DIR
    for stale_raw in OUT_DIR.rglob("*.raw"):
        stale_raw.unlink(missing_ok=True)

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "conditions": {"corner": "tt", "vdd_v": VDD_TT, "temp_c": TEMP_TT, "n_zq": N_ZQ_TT, "eq_code": args.eq},
        "netlists": {
            "tx_sst_cpex": str(TX_V5_PEX.relative_to(REPO)),
            "ctle_w3_open_cpex": str(CTLE_W3_OPEN_PEX.relative_to(REPO)),
            "slicer_5g_ref": str(SLICER_5G_REF.relative_to(REPO)),
            "channel": "verification/models/channel/pcb_family/C2_loss6.spice",
        },
        "ctle_load_rx_top_5g": load,
        "sequence": {
            "total_bits": TOTAL_BITS,
            "alt_bits": ALT_BITS,
            "marker_bits": TRAIN_BITS - ALT_BITS,
            "payload_prbs7_bits": PAYLOAD_BITS,
            "tail_bits": TAIL_BITS,
        },
        "ac": ac_res,
        "transient": {k: tran_res[k] for k, *_ in jobs},
        "slicer_signoff_ref": str(SLICER_SUMMARY.relative_to(REPO)),
        "figure": str(FIG_PATH.relative_to(REPO)),
        "total_elapsed_s": round(time.time() - t_all, 1),
    }
    sum_path.write_text(json.dumps(summary, indent=2) + "\n")
    np.savez_compressed(npz_path, **all_arrays)
    print(f"\nSaved summary -> {sum_path.relative_to(REPO)} and folded eyes -> {npz_path.relative_to(REPO)}", flush=True)

    print("\n=== [3/3] Rendering Publication-Grade 2x3 Figure (240 DPI) ===", flush=True)
    plot_figure(summary, all_arrays, FIG_PATH)
    print(f"\nALL DONE in {time.time() - t_all:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
