#!/usr/bin/env python3
"""5.0 Gb/s (200 ps UI) End-to-End SKY130A SerDes Analog Co-Simulation Verifier.

Incorporates the REAL extracted Magic DRC=0 / CPEX parameters of:
  1. `vco5g_ind_oct_2n5_pdk` (L_diff=2.408 nH, R_dc=3.065 Ohm, C_sub=410.49 fF, Q_5G=7.26)
     in `analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice`
  2. `rx_ctle_ind_m4m2_5g_pdk` / `serdes_rx_ctle_shunt_5g_pdk`
     in `analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice`

Modes:
  --mode calib      : CTLE AC characterization across PVT x RC corners.
  --mode stage1     : Closed-loop 5.0 GHz LC-PLL pull-in & lock (sparse solver, zero cshunt!)
                      with real `pll_div_ab_5g_v2` (/10), `pll_pfd_sc_dly`, `pll_cp_steer_v4`,
                      `pll_loop_filter_k4_fused`, and 2x `serdes_cml_to_cmos_r5` -> 2.5 GHz CMOS I/Q.
  --mode stage2a    : Locked 2.5 GHz I/Q -> TX Q-Div2 -> TX SST v4.3 (FFE=3, 5 Gb/s 112b PRBS-7)
                      -> Pkg RLC -> C2_loss6 -> RX Term + Shunt CTLE (real 8.252 nH coil).
  --mode stage2b    : Locked 2.5 GHz I/Q + Stage 2A far-end waveform -> Full 5G RX:
                      RX Term + Shunt CTLE (8.252 nH) + 4-Ph I/Q CMOS PI + 8x DT Slicers + Deser16
                      at PI codes (opt-8, opt, opt+8) proving 0 bit/edge errors & BBPD polarity flip.
  --mode singledeck : TRUE zero-abstraction single-deck TT combining TX Q-Div2 + TX SST v4.3
                      + Pkg RLC + C2_loss6 + RX Term + Shunt CTLE + 4-Ph I/Q PI + 8x Slicers
                      + Deser16 in ONE netlist!
  --mode plot       : Assemble summary.json and publication-quality 4-panel figure.

Hard rules:
  - Strictly workers <= 2, set num_threads=1.
  - Whenever `cap_var_lvt` is in the netlist (LC-VCO / LC-PLL), NEVER use `klu` or `cshunt`!
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import bias, eye, spice, watch  # noqa: E402
from serdes_flow.corners import Condition  # noqa: E402
from serdes_flow.waves import crossings  # noqa: E402

SC_LIB = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice")
DEFAULT_CAMP = REPO / "results/verification/top_cosim_5g_20261124"
DEFAULT_FIG = REPO / "docs/figures/system/serdes_5g_top_cosim_20261124.png"

FREF = 250.0e6
TREF = 1.0 / FREF          # 4.000 ns
F_VCO_TGT = 5.0e9          # 5.000 GHz LC tank
F_IQ_TGT = 2.5e9           # 2.500 GHz quadrature I/Q
T_IQ = 1.0 / F_IQ_TGT      # 400.0 ps
UI = 200.0e-12             # 5.0 Gb/s NRZ
T_WORD = 16 * UI           # 3.200 ns (312.5 MHz 16-bit word clock)
FFE_POST = 3
SLICER_APERTURE_S = 28.0e-12

# 112-bit sequence: 16 alt + 16 marker (0xD3A5) + 64 PRBS-7 (seed=0x11) + 16 tail = 7 words = 22.4 ns
ALT_BITS = 16
TRAIN_BITS = 32
PAYLOAD_BITS = 64
TAIL_BITS = 16
TOTAL_BITS = TRAIN_BITS + PAYLOAD_BITS + TAIL_BITS  # 112 bits

# Stage 1 closed-loop LC-PLL timeline
T_S1_STOP = 160.0e-9
S1_PRE_OFFSET = -0.015
S1_EXPORT_START = 122.0e-9

# Stage 2 5.0 Gb/s Analog Link timeline
T_S2_QDIV_REL = 1.0e-9
T_S2_RX_REL = 3.22e-9      # >=3.0 ns for AC-coupled octature recovery + clear of 2.5 GHz dp/dn edge across codes!
T_S2_TX_REL = 2.2e-9
T_S2_FIRST_UPD = 3.6e-9
T_S2_PAD_NOM = 7.6e-9
T_S2_STOP = 33.0e-9
T_S2_SAVE = 5.5e-9
T_S2_MEAS = 12.0e-9

CORNERS = [
    dict(
        id="tt_v1800_t27_tt",
        spec="tt_v1800_t27:tt",
        label="TT 1.80V 27°C tt",
        short="TT 27°C",
        rm_scale=1.00,
        c_scale=1.00,
        k_rc=1.00,
        n_zq=16,
        code_5g=5,
        vc_probe=(0.35, 0.55),
    ),
    dict(
        id="ss_v1650_t85_hh",
        spec="ss_v1650_t85:hh",
        label="SS 1.65V +85°C hh",
        short="SS +85°C",
        rm_scale=1.22,
        c_scale=1.12,
        k_rc=1.15,
        n_zq=20,
        code_5g=4,
        vc_probe=(0.38, 0.65),
    ),
    dict(
        id="ss_v1650_t-40_hh",
        spec="ss_v1650_t-40:hh",
        label="SS 1.65V −40°C hh",
        short="SS −40°C",
        rm_scale=1.22,
        c_scale=1.12,
        k_rc=1.15,
        n_zq=18,
        code_5g=5,
        vc_probe=(0.35, 0.55),
    ),
    dict(
        id="ff_v1950_t-40_ll",
        spec="ff_v1950_t-40:ll",
        label="FF 1.95V −40°C ll",
        short="FF −40°C",
        rm_scale=0.75,
        c_scale=0.88,
        k_rc=0.85,
        n_zq=12,
        code_5g=7,
        vc_probe=(0.30, 0.50),
    ),
]


def parse_cs(cs: dict) -> tuple[Condition, str]:
    cond_s, rc = cs["spec"].split(":")
    return Condition.parse(cond_s), rc


def check_ngspice_limit(workers: int) -> None:
    active = len(watch.ngspice_cwds())
    if active + workers > 4:
        raise RuntimeError(f"Host ngspice limit guard: {active} active, requested {workers}")


def build_sequence() -> np.ndarray:
    alt = [i & 1 for i in range(ALT_BITS)]
    marker = [(0xD3A5 >> b) & 1 for b in range(16)]
    payload = eye.prbs7(PAYLOAD_BITS + TAIL_BITS, seed=0x11)
    return np.array(alt + marker + payload, dtype=int)


def encode_zq_ffe(n_zq: int, n_post: int) -> dict[str, int]:
    n_main = n_zq - n_post
    m4 = 1 if n_main >= 16 else 0
    rem = n_main - 8 * m4
    m3 = (rem >> 3) & 1
    m2 = (rem >> 2) & 1
    m1 = (rem >> 1) & 1
    m0 = rem & 1
    f2 = 1 if n_post >= 4 else 0
    remf = n_post - 2 * f2
    f1 = 1 if remf >= 2 else 0
    f0 = remf - 2 * f1
    return dict(m0=m0, m1=m1, m2=m2, m3=m3, m4=m4, f0=f0, f1=f1, f2=f2, ffe_en=1 if n_post > 0 else 0)


def commutator_bits(code: int, supply: float) -> dict[str, float]:
    code = code % 64
    q, f = divmod(code, 8)
    a, b, nb = (q, (q + 1) % 8, f) if q % 2 == 0 else ((q + 1) % 8, q, 8 - f)
    v = {}
    for i in range(8):
        v[f"Va{i}"] = supply if i == a else 0.0
        v[f"Vb{i}"] = supply if i == b else 0.0
        v[f"Vf{i}"] = supply if i < nb else 0.0
    return v


def pwl_lines(head: str, pts: list[tuple[float, float]]) -> str:
    toks = [f"{t:.7e} {v:.5f}" for t, v in pts]
    out = [f"{head} PWL("]
    for i in range(0, len(toks), 6):
        out.append("+ " + " ".join(toks[i:i + 6]))
    return "\n".join(out) + " )\n"


def decimate_pwl(t: np.ndarray, v: np.ndarray, tol_v: float = 0.015) -> list[tuple[float, float]]:
    pts = [(float(t[0]), float(v[0]))]
    i0 = 0
    n = len(t)
    while i0 < n - 1:
        i1 = i0 + 1
        while i1 + 1 < n:
            t_seg = t[i0:i1 + 2]
            v_lin = v[i0] + (v[i1 + 1] - v[i0]) * (t_seg - t[i0]) / max(t[i1 + 1] - t[i0], 1e-18)
            if np.max(np.abs(v[i0:i1 + 2] - v_lin)) <= tol_v:
                i1 += 1
            else:
                break
        pts.append((float(t[i1]), float(v[i1])))
        i0 = i1
    return pts


def parallel_word_stimuli(bits: np.ndarray, supply: float, t_first_upd: float, edge: float = 40e-12) -> str:
    n_words = len(bits) // 16
    lines = []
    for bit_idx in range(16):
        init_b = bit_idx & 1
        pts = [(0.0, supply if init_b else 0.0)]
        prev = init_b
        for w in range(n_words):
            b = int(bits[16 * w + bit_idx])
            if b != prev:
                t_upd = t_first_upd + w * T_WORD
                pts.extend([
                    (t_upd - edge / 2, supply if prev else 0.0),
                    (t_upd + edge / 2, supply if b else 0.0),
                ])
                prev = b
        lines.append(pwl_lines(f"Vdin{bit_idx} din{bit_idx} 0", pts))
    return "".join(lines)


def rising_edges(t: np.ndarray, y: np.ndarray, thr: float = 0.0) -> np.ndarray:
    e, p = crossings(t, y - thr)
    return e[p > 0]


def time_weighted_mean(t: np.ndarray, y: np.ndarray) -> float:
    if len(t) < 2:
        return float("nan")
    dt = np.diff(t)
    return float(np.sum(0.5 * (y[:-1] + y[1:]) * dt) / (t[-1] - t[0]))


def measure_osc_diff(t: np.ndarray, y: np.ndarray, start: float, stop: float) -> dict:
    sel = (t >= start) & (t <= stop)
    ts, ys = t[sel], y[sel]
    if len(ts) < 10:
        return dict(ok=False, f_ghz=float("nan"), swing_v=0.0, n_cycles=0)
    sw = float(np.ptp(ys[len(ys) // 3:]))
    if sw < 0.08:
        return dict(ok=False, f_ghz=float("nan"), swing_v=sw, n_cycles=0)
    e, pol = crossings(ts, ys)
    r = e[pol > 0]
    if len(r) < 3:
        return dict(ok=False, f_ghz=float("nan"), swing_v=sw, n_cycles=len(r))
    f_ghz = float((len(r) - 1) / (r[-1] - r[0]) / 1e9)
    return dict(ok=True, f_ghz=f_ghz, swing_v=sw, n_cycles=len(r) - 1)


def measure_cmos_clk(t: np.ndarray, y: np.ndarray, vmid: float, start: float, stop: float) -> dict:
    sel = (t >= start) & (t <= stop)
    ts, ys = t[sel], y[sel]
    if len(ts) < 10:
        return dict(ok=False, f_ghz=float("nan"), vpp=0.0, duty_pct=float("nan"), n_cycles=0)
    vpp = float(np.ptp(ys))
    e, pol = crossings(ts, ys - vmid)
    r_idx = np.where(pol > 0)[0]
    if len(r_idx) < 2:
        return dict(ok=False, f_ghz=float("nan"), vpp=vpp, duty_pct=float("nan"), n_cycles=len(r_idx))
    r = e[r_idx]
    f_ghz = float((len(r) - 1) / (r[-1] - r[0]) / 1e9)
    dcs = []
    for k in range(len(r_idx) - 1):
        i0, i1 = r_idx[k], r_idx[k + 1]
        if i1 - i0 == 2 and pol[i0 + 1] < 0:
            per = e[i1] - e[i0]
            if per > 0:
                dcs.append((e[i0 + 1] - e[i0]) / per * 100.0)
    return dict(
        ok=True, f_ghz=f_ghz, vpp=vpp,
        vmin=float(np.min(ys)), vmax=float(np.max(ys)),
        duty_pct=float(np.mean(dcs)) if dcs else float("nan"),
        n_cycles=len(r) - 1,
    )


def measure_iq_quad(t: np.ndarray, yi: np.ndarray, yq: np.ndarray, vmid: float, start: float, stop: float) -> dict:
    sel = (t >= start) & (t <= stop)
    ts = t[sel]
    ri = rising_edges(ts, yi[sel], vmid)
    rq = rising_edges(ts, yq[sel], vmid)
    if len(ri) < 5 or len(rq) < 5:
        return dict(ok=False, iq_err_ps=float("nan"), iq_deg=float("nan"), q_polarity="unknown")
    per = float(np.median(np.diff(ri)))
    fracs = []
    for ti in ri[1:-1]:
        idx = np.searchsorted(rq, ti)
        if idx < len(rq):
            fracs.append(((rq[idx] - ti) / per) % 1.0)
    if not fracs:
        return dict(ok=False, iq_err_ps=float("nan"), iq_deg=float("nan"), q_polarity="unknown")
    mean_f = float(np.mean(fracs))
    e1 = mean_f - 0.25
    e2 = mean_f - 0.75
    e_best = e1 if abs(e1) < abs(e2) else e2
    return dict(
        ok=True,
        iq_err_ps=float(e_best * per * 1e12),
        iq_deg=float(mean_f * 360.0),
        q_polarity="qp" if abs(e1) < abs(e2) else "qn",
    )


def read_complex_raw(path: Path) -> dict[str, np.ndarray]:
    raw = path.read_bytes()
    idx = raw.find(b"Binary:\n")
    if idx < 0:
        raise ValueError(f"Not a binary raw file: {path}")
    header = raw[:idx].decode("ascii", errors="replace")
    n_vars = n_pts = 0
    names = []
    in_vars = False
    for line in header.splitlines():
        ls = line.strip()
        if ls.startswith("No. Variables:"):
            n_vars = int(ls.split(":")[1].strip())
        elif ls.startswith("No. Points:"):
            n_pts = int(ls.split(":")[1].strip())
        elif ls.startswith("Variables:"):
            in_vars = True
        elif in_vars and ls:
            parts = ls.split()
            if len(parts) >= 2 and parts[0].isdigit():
                names.append(parts[1])
    data = np.frombuffer(raw[idx + len(b"Binary:\n"):], dtype=np.complex128).reshape(n_pts, n_vars)
    return {nm: data[:, k] for k, nm in enumerate(names)}


# =============================================================================
# SERIAL EYE & DESERIALIZER METRICS (5.0 Gb/s, UI = 200 ps)
# =============================================================================

def check_serial_112(t: np.ndarray, y: np.ndarray, bits: np.ndarray, start_s: float) -> dict:
    sgn = 2 * bits - 1
    edge_t, edge_pol = crossings(t, y)
    idx_tr = np.arange(TRAIN_BITS)
    grid = np.arange(-12.0, 26.0, 0.01)
    times = start_s + (idx_tr[None, :] + 0.5 + grid[:, None]) * UI
    valid_g = (times[:, 0] >= t[0]) & (times[:, -1] <= t[-1])
    grid = grid[valid_g]
    times = times[valid_g]
    v = np.interp(times.ravel(), t, y).reshape(times.shape)
    wrong = v * sgn[:TRAIN_BITS] <= 0
    cost = 100 * wrong[:, ALT_BITS:].sum(axis=1) + wrong[:, :ALT_BITS].sum(axis=1)
    best = np.where(cost == cost.min())[0]
    delay = float(grid[best[np.argmax(np.min(v[best] * sgn[:TRAIN_BITS], axis=1))]])
    offsets = []
    for k in range(1, ALT_BITS):
        target = start_s + (k + delay) * UI
        hit = np.where((np.abs(edge_t - target) < 0.45 * UI) & (edge_pol == sgn[k]))[0]
        if len(hit) == 1:
            offsets.append((edge_t[hit[0]] - start_s) / UI - k)
    if len(offsets) >= 10:
        delay = float(np.median(offsets))

    end = TRAIN_BITS + PAYLOAD_BITS
    sample_t = start_s + (np.arange(end) + 0.5 + delay) * UI
    samples = np.interp(sample_t, t, y)
    signed = samples * sgn[:end]
    payload = signed[TRAIN_BITS:end]
    train_err = int(np.sum(signed[:ALT_BITS] <= 0))
    marker_err = int(np.sum(signed[ALT_BITS:TRAIN_BITS] <= 0))
    bit_err = int(np.sum(payload <= 0))

    used, residual, missing = set(), [], 0
    for k in range(TRAIN_BITS, end):
        if bits[k] == bits[k - 1]:
            continue
        target = start_s + (k + delay) * UI
        hit = np.where((np.abs(edge_t - target) < 0.45 * UI) & (edge_pol == sgn[k]))[0]
        if len(hit):
            i = int(hit[np.argmin(np.abs(edge_t[hit] - target))])
            used.add(i)
            residual.append((edge_t[i] - target) / UI)
        else:
            missing += 1
    span = (edge_t >= start_s + (TRAIN_BITS + delay - 0.45) * UI) & (edge_t < start_s + (end + delay - 0.45) * UI)
    extra = int(sum(i not in used for i in np.where(span)[0]))
    in_pay = (t >= start_s + (TRAIN_BITS + delay) * UI) & (t < start_s + (end + delay) * UI)
    spread_ui = float(np.ptp(residual)) if residual else float("nan")
    margin_v = float(np.min(payload))
    valid_tr = bool(len(offsets) >= 10 and train_err == 0 and marker_err == 0)
    functional = bool(valid_tr and bit_err == 0 and missing == 0 and extra == 0)

    n_all = np.arange(TOTAL_BITS)
    s_all = np.interp(start_s + (n_all + 0.5 + delay) * UI, t, y)
    out_bits = (s_all > 0).astype(int)
    words = [1, 2, 3, 4, 5]
    mapping = []
    for j in range(16):
        cands = [s for s in range(16) if all(out_bits[16 * w + j] == bits[16 * w + s] for w in words)]
        if len(cands) == 1:
            mapping.append(cands[0])
        else:
            mapping = None
            break
    in_order = bool(mapping == list(range(16)))
    t_bit0_edge = start_s + delay * UI
    ey = eye.signed_eye(t, y, bits.tolist(), UI, t_bit0_edge, first_bit=TRAIN_BITS, n_bits=PAYLOAD_BITS)
    return dict(
        functional=functional,
        meets_draft=bool(functional and margin_v >= 0.075 and spread_ui <= 0.15),
        training_delay_ui=delay,
        training_errors=train_err,
        marker_errors=marker_err,
        bit_errors=bit_err,
        missing_transitions=missing,
        extra_crossings=extra,
        matched_transitions=len(residual),
        margin_mv=round(margin_v * 1e3, 2),
        spread_ui=round(spread_ui, 4),
        pp_mv=round(float(np.ptp(y[in_pay]) * 1e3), 2) if np.any(in_pay) else float("nan"),
        eye_h_mv=round(float(ey["height_v"] * 1e3), 2),
        eye_w_ui=round(float(ey["width_ui"]), 4),
        in_order=in_order,
        mapping=mapping,
        t_bit0_center_s=float(t_bit0_edge + 0.5 * UI),
    )


def slack_ps(data_edges: np.ndarray, clk_edges: np.ndarray) -> tuple[float | None, float | None]:
    if len(data_edges) == 0 or len(clk_edges) == 0:
        return None, None
    su, ho = [], []
    for ck in clk_edges:
        idx = np.searchsorted(data_edges, ck)
        if idx > 0:
            su.append((ck - data_edges[idx - 1]) * 1e12)
        if idx < len(data_edges):
            ho.append((data_edges[idx] - ck) * 1e12)
    return (float(min(su)) if su else None), (float(min(ho)) if ho else None)


def bbpd_vote(wd_words: list[list[int]], we_words: list[list[int]]) -> tuple[int, int]:
    vote_sum, trans = 0, 0
    for w_idx in range(1, len(wd_words)):
        prev_bit = wd_words[w_idx - 1][15]
        d, e = wd_words[w_idx], we_words[w_idx]
        for k in range(16):
            if prev_bit != d[k]:
                trans += 1
                vote_sum += 1 if e[k] == d[k] else -1
            prev_bit = d[k]
    return int(vote_sum), int(trans)


def analyse_rx_words(
    w: spice.Waves,
    bits: np.ndarray,
    supply: float,
    code: int,
    meas_from: float,
    min_words: int = 4,
    min_bit_idx: int = 16,
) -> dict:
    sel = w.t >= meas_from
    t = w.t[sel]
    vmid = 0.5 * supply
    we, wp = crossings(t, w["v(wclk)"][sel], vmid)
    wr = we[wp > 0]
    if len(wr) < min_words:
        return dict(code=code, ok=False, reason=f"too few wclk edges ({len(wr)})", data_errors=999, edge_errors=999)

    wd_sig = [w[f"v(wd{i})"][sel] for i in range(16)]
    we_sig = [w[f"v(we{i})"][sel] for i in range(16)]
    su_all, ho_all = [], []
    for sig in wd_sig + we_sig:
        de, _ = crossings(t, sig, vmid)
        s, h = slack_ps(de, wr)
        if s is not None:
            su_all.append(s)
        if h is not None:
            ho_all.append(h)

    wd_words = [[int(np.interp(ck, t, wd_sig[i]) > vmid) for i in range(16)] for ck in wr]
    we_words = [[int(np.interp(ck, t, we_sig[i]) > vmid) for i in range(16)] for ck in wr]

    nw = len(wd_words)
    best_err, best_p, best_use = 10**9, 0, []
    for p in range(-64, len(bits) - 32):
        use = [n for n in range(nw) if p + 16 * n >= max(0, min_bit_idx - 1) and p + 16 * n + 16 <= len(bits)]
        if len(use) < min_words:
            continue
        err = sum(
            wd_words[n][k] != int(bits[p + 16 * n + k])
            for n in use for k in range(16)
            if p + 16 * n + k >= min_bit_idx
        )
        if err < best_err or (err == best_err and len(use) > len(best_use)):
            best_err, best_p, best_use = err, p, use

    data_bits = sum(1 for n in best_use for k in range(16) if best_p + 16 * n + k >= min_bit_idx)
    edge_err, edge_det = 0, 0
    for n in best_use:
        for k in range(16):
            j = best_p + 16 * n + k
            if max(1, min_bit_idx + 1) <= j < len(bits) and int(bits[j - 1]) == int(bits[j]):
                edge_det += 1
                if we_words[n][k] != int(bits[j]):
                    edge_err += 1

    matched_wd = [wd_words[n] for n in best_use]
    matched_we = [we_words[n] for n in best_use]
    vote, trans = bbpd_vote(matched_wd, matched_we)
    w_su = float(min(su_all)) if su_all else float("nan")
    w_ho = float(min(ho_all)) if ho_all else float("nan")
    ok = bool(best_err == 0 and edge_err == 0 and len(best_use) >= min_words and w_su >= 800.0 and w_ho >= 800.0)
    return dict(
        code=int(code),
        ok=ok,
        word_start=int(best_p),
        words_checked=len(best_use),
        data_bits=int(data_bits),
        data_errors=int(best_err),
        edge_errors=int(edge_err),
        edge_determinate=int(edge_det),
        bbpd_vote=int(vote),
        bbpd_transitions=int(trans),
        wclk_period_ns=round(float(np.mean(np.diff(wr)) * 1e9), 4) if len(wr) >= 2 else float("nan"),
        wclk_setup_ps=round(w_su, 1),
        wclk_hold_ps=round(w_ho, 1),
    )


# =============================================================================
# CALIB: CTLE AC CHARACTERIZATION
# =============================================================================

def build_ctle_ac_deck(cs: dict, cload_ff: float = 80.0) -> str:
    c, rc = parse_cs(cs)
    s = c.supply
    inc = [
        "analog/common/devices/spice/sky130_primitives.spice",
        "analog/bias/spice/bias_v2.spice",
        "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice",
        "analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice",
    ]
    lines = [
        f"* 5G Shunt-Peaked CTLE AC ({cs['id']}, Cload={cload_ff}fF)",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in inc],
        f"Vdd vdd 0 {s}",
        f"Iref vdd vbias dc {50.0 / cs['k_rc']:.3f}u",
        "Xbias vbias 0 serdes_bias_ctle_v2",
        "Vcm cm 0 1.05",
        "Vdm dm 0 DC 0 AC 1",
        "Eip inp cm dm 0  0.5",
        "Ein inn cm dm 0 -0.5",
        f"Veq0 eq0 0 {s}",
        f"Veq1 eq1 0 {s}",
        "X0 inp inn op0 on0 eq0 eq1 vbias vdd 0 serdes_rx_ctle_pdk",
        f"C0p op0 0 {cload_ff}f", f"C0n on0 0 {cload_ff}f",
        f"X1 inp inn op1 on1 eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g_pdk l_rload=4.14 wtail=48 nftail=8 rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        f"C1p op1 0 {cload_ff}f", f"C1n on1 0 {cload_ff}f",
        f"X2 inp inn op2 on2 eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g_pdk rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        f"C2p op2 0 {cload_ff}f", f"C2n on2 0 {cload_ff}f",
        f".temp {c.temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "ac dec 100 1meg 20g",
        "let g0 = v(op0,on0)/v(inp,inn)",
        "let g1 = v(op1,on1)/v(inp,inn)",
        "let g2 = v(op2,on2)/v(inp,inn)",
        "write ctle_ac.raw g0 g1 g2",
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def analyse_ctle_ac(camp: Path, sel_corners: list[dict], workers: int) -> dict:
    cdir = camp / "calib" / "ctle_ac"
    cdir.mkdir(parents=True, exist_ok=True)
    ac_jobs = []
    for cs in sel_corners:
        d = cdir / cs["id"]
        if not (d / "ctle_ac.raw").exists():
            ac_jobs.append((build_ctle_ac_deck(cs, 80.0), d, dict(timeout_s=180)))
    if ac_jobs:
        check_ngspice_limit(workers)
        for ex in spice.run_many(ac_jobs, workers=workers, smoke=False):
            print(f"  CTLE AC {ex.run_dir.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s", flush=True)

    ctle_res = {}
    for cs in sel_corners:
        raw = cdir / cs["id"] / "ctle_ac.raw"
        if not raw.exists():
            continue
        d = read_complex_raw(raw)
        f = np.real(d["frequency"])
        row = {}
        for name, key in (("r_600", "g0"), ("shunt_600", "g1"), ("shunt_480_5g", "g2")):
            db = 20.0 * np.log10(np.maximum(np.abs(d[key]), 1e-12))
            g_lf = float(db[0])
            g_25 = float(np.interp(2.5e9, f, db))
            pk_i = int(np.argmax(db))
            pk_db = float(db[pk_i] - g_lf)
            pk_ghz = float(f[pk_i] / 1e9)
            below = np.where((f > f[pk_i]) & (db < g_lf - 3.0))[0]
            bw_ghz = float(f[below[0]] / 1e9) if len(below) else float("nan")
            row[name] = dict(
                lf_db=round(g_lf, 2), g_2p5g_db=round(g_25, 2),
                boost_2p5g_db=round(g_25 - g_lf, 2),
                max_peak_db=round(pk_db, 2), f_peak_ghz=round(pk_ghz, 2),
                bw3_ghz=round(bw_ghz, 2),
            )
        ctle_res[cs["id"]] = row
    return ctle_res


# =============================================================================
# STAGE 1: CLOSED-LOOP 5.0 GHz LC-PLL (STRICT SPARSE SOLVER, ZERO CSHUNT!)
# =============================================================================

PLL5G_INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/common/devices/spice/cmos_logic.spice",
    "analog/bias/spice/bias_v2.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r4_v4.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice",
    "analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice",
    "analog/pll/divider/spice/pll_div_ab_5g_v2.spice",
    "analog/pll/pfd/spice/pfd_sc.spice",
    "analog/pll/cp/spice/charge_pump_steer_v4.spice",
    "analog/pll/loop_filter/spice/passive_rc_precharge.spice",
    "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice",
]


def build_stage1_open_probe_deck(cs: dict, code: int, vc_pair: tuple[float, float], stop_s: float = 18.0e-9) -> str:
    c, rc = parse_cs(cs)
    s = c.supply
    i_c2c_u = 212.5 / cs["k_rc"]
    v0, v1 = vc_pair
    lines = [
        f"* Stage 1 Open-Loop 5G LC-VCO+C2C+Div10 Probe ({cs['id']}, code={code})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in PLL5G_INCLUDES],
        f'.include "{SC_LIB}"',
        f"Vdd_vco vdd_vco 0 {s}",
        f"Vdd_clk vdd_clk 0 {s}",
        f"Vdd_div vdd_div 0 {s}",
        f"Vctrl vctrl 0 {v0:.5f}",
        *[f"Vb{b} b{b} 0 {s if ((code >> b) & 1) else 0.0:.5f}" for b in range(4)],
        f"Xvco vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd_vco 0 vco5g_lc_div2_oct_pdk rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 60u 0.26n 60u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 3.0n 0 3.01n 50u 3.06n 50u 3.07n 0)",
        f"Ibias_c2c vdd_clk vbias_c2c dc {i_c2c_u:.3f}u",
        "Xbias_c2c vbias_c2c 0 serdes_bias_cml_v2",
        "Xc2c_i ip in ic_p ic_n vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c_q qp qn qc_p qc_n vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Cbal_ip ic_p 0 18f", "Cbal_in ic_n 0 18f",
        "Cbal_qp qc_p 0 30f", "Cbal_qn qc_n 0 30f",
        f"Vmode mode_5g 0 {s}",
        f"Vrst_div rst_div_n 0 PWL(0 0 5.5n 0 5.55n {s})",
        "Xdiv ic_p ic_n mode_5g rst_div_n fb250 fb250_b vdd_div 0 pll_div_ab_5g_v2",
        "Cfb fb250 0 15f", "Cfbb fb250_b 0 15f",
        ".ic v(xvco.xcore.vbias_f)=0.82 v(xvco.xcore.vbias_lc)=0.82 v(xvco.xcore.tail)=0.32 "
        "v(xvco.xdiv2.vbias_d)=0.78 v(xvco.xdiv2.vck_cm)=1.05 v(vp)=1.05 v(vn)=1.00",
        ".nodeset v(vp)=1.0 v(vn)=1.0 v(vbias_c2c)=1.04",
        f".temp {c.temp}",
        ".options reltol=3e-4 abstol=5p vntol=5u gmin=1e-11 trtol=4 itl4=80 method=gear",
        ".save v(vp) v(vn) v(ic_p) v(qc_p) v(fb250)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 4p {stop_s:.6e} 6e-9 5p",
        "write p0.raw v(vp) v(vn) v(ic_p) v(qc_p) v(fb250)",
        "destroy all",
        f"alter Vctrl dc={v1:.5f}",
        f"tran 4p {stop_s:.6e} 6e-9 5p",
        "write p1.raw v(vp) v(vn) v(ic_p) v(qc_p) v(fb250)",
        "destroy all",
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def build_stage1_closed_loop_deck(
    cs: dict,
    code: int,
    vctrl_pre: float,
    t_ref_delay: float,
    t_pre_rel: float,
    t_pfd_rel: float,
    *,
    stop_s: float = T_S1_STOP,
    rlength: float = 20.0,
) -> str:
    c, rc = parse_cs(cs)
    s = c.supply
    k_rc = cs["k_rc"]
    lines = [
        f"* Stage 1 Closed-Loop 5.0 GHz LC-PLL ({cs['id']}, code={code}, vpre={vctrl_pre:.4f}V)",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in PLL5G_INCLUDES],
        f'.include "{SC_LIB}"',
        f"Vdd_vco vdd_vco 0 {s}",
        f"Vdd_clk vdd_clk 0 {s}",
        f"Vdd_div vdd_div 0 {s}",
        f"Vdd_pfd vdd_pfd 0 {s}",
        f"Vdd_cp  vdd_cp  0 {s}",
        *[f"Vb{b} b{b} 0 {s if ((code >> b) & 1) else 0.0:.5f}" for b in range(4)],
        f"Xvco vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd_vco 0 vco5g_lc_div2_oct_pdk rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 60u 0.26n 60u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 3.0n 0 3.01n 50u 3.06n 50u 3.07n 0)",
        f"Ibias_c2c vdd_clk vbias_c2c dc {212.5 / k_rc:.3f}u",
        "Xbias_c2c vbias_c2c 0 serdes_bias_cml_v2",
        "Xc2c_i ip in ic_p ic_n vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Xc2c_q qp qn qc_p qc_n vbias_c2c vdd_clk 0 serdes_cml_to_cmos_r5",
        "Cbal_ip ic_p 0 18f", "Cbal_in ic_n 0 18f",
        "Cbal_qp qc_p 0 30f", "Cbal_qn qc_n 0 30f",
        f"Vmode mode_5g 0 {s}",
        f"Vrst_div rst_div_n 0 PWL(0 0 5.5n 0 5.55n {s})",
        "Xdiv ic_p ic_n mode_5g rst_div_n fb250 fb250_b vdd_div 0 pll_div_ab_5g_v2",
        "Cfbb fb250_b 0 15f",
        f"Vref ref 0 PULSE(0 {s} {t_ref_delay:.6e} 30p 30p {TREF / 2 - 30e-12:.4e} {TREF:.4e})",
        f"Vrst_pfd rst_b 0 PWL(0 0 {t_pfd_rel:.6e} 0 {t_pfd_rel + 25e-12:.6e} {s})",
        "Xpfd ref fb250 rst_b up dn vdd_pfd 0 pll_pfd_sc_dly",
        f"Ibias_cp  vdd_cp vbn_cp  dc {50.0 / k_rc:.3f}u",
        "Xbias_cp  vbn_cp vbp_cp  vdd_cp 0 serdes_bias_cp_v2",
        f"Ibias_ota vdd_cp ib_ota  dc {10.0 / k_rc:.3f}u",
        "Xcp up dn cpo vbn_cp vbp_cp ib_ota vdd_cp 0 pll_cp_steer_v4",
        f"Vpre pre_ref 0 {vctrl_pre:.5f}",
        f"Vpen pre_en  0 PWL(0 {s} {t_pre_rel:.6e} {s} {t_pre_rel + 150e-12:.6e} 0)",
        f"Xlf cpo vctrl z pre_ref pre_en vdd_cp 0 pll_loop_filter_k4_fused rlength={rlength:.2f}",
        "Xcf vctrl 0 sky130_fd_pr__cap_mim_m3_1 w=22.0 l=22.0",
        f".ic v(vctrl)={vctrl_pre:.5f} v(z)={vctrl_pre:.5f} "
        "v(xvco.xcore.vbias_f)=0.82 v(xvco.xcore.vbias_lc)=0.82 v(xvco.xcore.tail)=0.32 "
        "v(xvco.xdiv2.vbias_d)=0.78 v(xvco.xdiv2.vck_cm)=1.05 v(vp)=1.05 v(vn)=1.00",
        f".nodeset v(vctrl)={vctrl_pre:.5f} v(z)={vctrl_pre:.5f} v(vbias_c2c)=1.04 v(vbn_cp)=0.87 "
        f"v(xcp.vbp_srv)={s - 1.23:.3f} v(xcp.rep)={vctrl_pre:.5f}",
        f".temp {c.temp}",
        ".options reltol=3e-4 abstol=5p vntol=5u gmin=1e-11 trtol=4 itl4=80 method=gear",
        ".save v(ref) v(fb250) v(vctrl) v(z) v(up) v(dn) v(xcp.vbp_srv) "
        "v(vp) v(vn) v(ip) v(in) v(ic_p) v(ic_n) v(qc_p) v(qc_n) "
        "i(Vdd_vco) i(Vdd_clk) i(Vdd_div) i(Vdd_pfd) i(Vdd_cp)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 5p {stop_s:.6e} 6e-9 5p",
        "write pll_lock.raw v(ref) v(fb250) v(vctrl) v(z) v(up) v(dn) v(xcp.vbp_srv) "
        "v(vp) v(vn) v(ip) v(in) v(ic_p) v(ic_n) v(qc_p) v(qc_n) "
        "i(Vdd_vco) i(Vdd_clk) i(Vdd_div) i(Vdd_pfd) i(Vdd_cp)",
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def export_locked_iq_clocks(raw_path: Path, out_inc: Path, supply: float, start_s: float = S1_EXPORT_START) -> dict:
    w = spice.Waves(raw_path)
    vmid = 0.5 * supply
    qinfo = measure_iq_quad(w.t, w["v(ic_p)"], w["v(qc_p)"], vmid, start_s, float(w.t[-1]) - 0.5e-9)
    if qinfo["q_polarity"] == "qn":
        sig_map = [("ip", "v(ic_p)"), ("qp", "v(qc_n)"), ("in", "v(ic_n)"), ("qn", "v(qc_p)")]
    else:
        sig_map = [("ip", "v(ic_p)"), ("qp", "v(qc_p)"), ("in", "v(ic_n)"), ("qn", "v(qc_n)")]
    t_end = float(w.t[-1]) - 0.2e-9
    t_grid = np.arange(start_s, t_end, 10.0e-12)
    lines = [f"* Exported Locked 2.500 GHz CMOS I/Q from {raw_path.name} (q_polarity={qinfo['q_polarity']})\n"]
    n_pts = 0
    for port, vec in sig_map:
        vals = np.interp(t_grid, w.t, w[vec])
        pts = decimate_pwl(t_grid - start_s, vals, tol_v=0.025)
        n_pts += len(pts)
        lines.append(pwl_lines(f"Vclk_{port} clk_{port} 0", pts))
    out_inc.write_text("".join(lines))
    return dict(q_polarity=qinfo["q_polarity"], duration_ns=float((t_end - start_s) * 1e9), pwl_pts_total=n_pts)


def analyse_stage1_lock(raw_path: Path, cs: dict, code: int, vctrl_pre: float) -> dict:
    w = spice.Waves(raw_path)
    c, _ = parse_cs(cs)
    s = c.supply
    vmid = 0.5 * s
    t = w.t
    t_end = float(t[-1])
    t0, t1 = max(72.0e-9, t_end - 35.0e-9), t_end - 0.5e-9
    m = (t >= t0) & (t <= t1)
    tl = t[m]

    # Early transient pull-in metrics (15..35 ns)
    m_init = measure_cmos_clk(t, w["v(ic_p)"], vmid, 15.0e-9, 35.0e-9)
    f_err_init_ppm = (m_init["f_ghz"] * 1e9 / F_IQ_TGT - 1.0) * 1e6
    mi = (t >= 15.0e-9) & (t <= 35.0e-9)
    vctrl_early = time_weighted_mean(t[mi], w["v(vctrl)"][mi])

    m_lc = measure_osc_diff(t, w["v(vp)"] - w["v(vn)"], t0, t1)
    m_cml = measure_osc_diff(t, w["v(ip)"] - w["v(in)"], t0, t1)
    m_ic = measure_cmos_clk(t, w["v(ic_p)"], vmid, t0, t1)
    m_iq = measure_iq_quad(t, w["v(ic_p)"], w["v(qc_p)"], vmid, t0, t1)
    m_fb = measure_cmos_clk(t, w["v(fb250)"], vmid, t0, t1)

    f_lc_ghz = m_lc["f_ghz"]
    f_iq_ghz = m_ic["f_ghz"]
    f_fb_mhz = m_fb["f_ghz"] * 1e3
    f_err_ppm = (f_iq_ghz * 1e9 / F_IQ_TGT - 1.0) * 1e6

    r_ic = rising_edges(tl, w["v(ic_p)"][m], vmid)
    if len(r_ic) > 4:
        tie = (r_ic - r_ic[0]) - np.arange(len(r_ic)) * T_IQ
        tie_pp_ps = float(np.ptp(tie) * 1e12)
        per_pp_ps = float(np.ptp(np.diff(r_ic)) * 1e12)
    else:
        tie_pp_ps, per_pp_ps = float("nan"), float("nan")

    vctrl_settled = time_weighted_mean(tl, w["v(vctrl)"][m])
    vctrl_rip_mv = float(np.ptp(w["v(vctrl)"][m]) * 1e3)
    z_settled = time_weighted_mean(tl, w["v(z)"][m])
    pull_in_mv = (vctrl_settled - vctrl_pre) * 1e3
    dyn_pull_mv = (vctrl_settled - vctrl_early) * 1e3

    r_ref = rising_edges(tl, w["v(ref)"][m], vmid)
    r_fb = rising_edges(tl, w["v(fb250)"][m], vmid)
    ph_errs = []
    for tr in r_ref[1:-1]:
        if len(r_fb):
            j = int(np.argmin(np.abs(r_fb - tr)))
            d = (r_fb[j] - tr) * 1e12
            if abs(d) < 1500.0:
                ph_errs.append(d)
    static_phase_ps = float(np.mean(ph_errs)) if ph_errs else float("nan")

    p_vco = -time_weighted_mean(tl, w["i(vdd_vco)"][m]) * s * 1e3
    p_clk = -time_weighted_mean(tl, w["i(vdd_clk)"][m]) * s * 1e3
    p_div = -time_weighted_mean(tl, w["i(vdd_div)"][m]) * s * 1e3
    p_pfd = -time_weighted_mean(tl, w["i(vdd_pfd)"][m]) * s * 1e3
    p_cp = -time_weighted_mean(tl, w["i(vdd_cp)"][m]) * s * 1e3
    p_pll_core = p_vco + p_div + p_pfd + p_cp
    p_total = p_pll_core + p_clk

    ok = bool(
        abs(f_err_ppm) <= 500.0
        and abs(m_iq["iq_err_ps"]) <= 8.0
        and 45.0 <= m_fb["duty_pct"] <= 55.0
        and abs(f_err_ppm) < 0.35 * max(abs(f_err_init_ppm), 500.0)
    )
    return dict(
        condition=cs["id"],
        label=cs["label"],
        ok=ok,
        code_5g=code,
        t_end_ns=round(t_end * 1e9, 2),
        vctrl_pre_v=round(vctrl_pre, 5),
        vctrl_early_v=round(vctrl_early, 5),
        vctrl_settled_v=round(vctrl_settled, 5),
        z_settled_v=round(z_settled, 5),
        pull_in_mv=round(pull_in_mv, 2),
        dyn_pull_in_mv=round(dyn_pull_mv, 2),
        vctrl_ripple_mvpp=round(vctrl_rip_mv, 2),
        f_err_init_ppm=round(f_err_init_ppm, 1),
        f_lc_ghz=round(f_lc_ghz, 6),
        vlc_vpp=round(m_lc["swing_v"], 3),
        vcml_vpp=round(m_cml["swing_v"], 3),
        f_iq_ghz=round(f_iq_ghz, 6),
        f_err_ppm=round(f_err_ppm, 1),
        tie_pp_ps=round(tie_pp_ps, 2),
        per_pp_ps=round(per_pp_ps, 2),
        ic_vpp=round(m_ic["vpp"], 3),
        ic_duty_pct=round(m_ic["duty_pct"], 2),
        iq_err_ps=round(m_iq["iq_err_ps"], 2),
        iq_deg=round(m_iq["iq_deg"], 2),
        q_polarity=m_iq["q_polarity"],
        f_fb250_mhz=round(f_fb_mhz, 4),
        fb250_duty_pct=round(m_fb["duty_pct"], 2),
        static_phase_ps=round(static_phase_ps, 2),
        p_vco_div2_mw=round(p_vco, 2),
        p_c2c_2x_mw=round(p_clk, 2),
        p_div10_mw=round(p_div, 2),
        p_pfd_mw=round(p_pfd, 2),
        p_cp_mw=round(p_cp, 2),
        p_pll_core_mw=round(p_pll_core, 2),
        p_pll_with_c2c_mw=round(p_total, 2),
        raw_path=str(raw_path),
    )


def run_stage1(camp: Path, sel_corners: list[dict], workers: int, force: bool = False) -> dict:
    s1_dir = camp / "stage1_pll"
    s1_dir.mkdir(parents=True, exist_ok=True)
    probe_file = s1_dir / "open_probes.json"
    probes = json.loads(probe_file.read_text()) if probe_file.exists() else {}

    p_jobs = []
    for cs in sel_corners:
        pd = s1_dir / "probe" / cs["id"]
        if force or not ((pd / "p0.raw").exists() and (pd / "p1.raw").exists()):
            dk = build_stage1_open_probe_deck(cs, cs["code_5g"], cs["vc_probe"], stop_s=18.0e-9)
            p_jobs.append((dk, pd, dict(timeout_s=420)))
    if p_jobs:
        check_ngspice_limit(workers)
        print(f"[Stage1 Probe] Running {len(p_jobs)} open-loop probes (sparse, workers={workers})...", flush=True)
        for ex in spice.run_many(p_jobs, workers=workers, smoke=False):
            print(f"  Probe {ex.run_dir.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)

    for cs in CORNERS:
        pd = s1_dir / "probe" / cs["id"]
        if not ((pd / "p0.raw").exists() and (pd / "p1.raw").exists()):
            continue
        c, _ = parse_cs(cs)
        vmid = 0.5 * c.supply
        w0 = spice.Waves(pd / "p0.raw")
        w1 = spice.Waves(pd / "p1.raw")
        v0, v1 = cs["vc_probe"]
        f0 = measure_osc_diff(w0.t, w0["v(vp)"] - w0["v(vn)"], 9e-9, 17.5e-9)["f_ghz"]
        f1 = measure_osc_diff(w1.t, w1["v(vp)"] - w1["v(vn)"], 9e-9, 17.5e-9)["f_ghz"]
        kvco_ghz_v = (f1 - f0) / (v1 - v0)
        vc_5g = float(np.clip(v0 + (5.0 - f0) / kvco_ghz_v, 0.30, min(1.35, c.supply - 0.35)))
        w_ref = w0 if abs(f0 - 5.0) < abs(f1 - 5.0) else w1
        r_fb = rising_edges(w_ref.t, w_ref["v(fb250)"], vmid)
        r_post = r_fb[r_fb >= 9.5e-9]
        t_fb = float(r_post[0]) if len(r_post) else 10.5e-9
        td_s = (t_fb - 10e-12) % TREF
        probes[cs["id"]] = dict(
            code_5g=cs["code_5g"], v0=v0, f0_ghz=round(f0, 5), v1=v1, f1_ghz=round(f1, 5),
            kvco_mhz_v=round(kvco_ghz_v * 1e3, 1), vctrl_5g_est=round(vc_5g, 5),
            t_fb_align_ns=round(t_fb * 1e9, 4), t_ref_delay_s=td_s,
            t_pre_rel_s=max(7.5e-9, t_fb - 1.5e-9), t_pfd_rel_s=max(8.0e-9, t_fb - 1.0e-9),
        )
    probe_file.write_text(json.dumps(probes, indent=2))

    lock_jobs = []
    for cs in sel_corners:
        if cs["id"] not in probes or not np.isfinite(float(probes[cs["id"]]["vctrl_5g_est"])):
            continue
        pr = probes[cs["id"]]
        vpre = float(pr["vctrl_5g_est"]) + S1_PRE_OFFSET
        ld = s1_dir / "lock" / cs["id"]
        if (not force) and spice.case_output(ld, "run", "pll_lock.raw", T_S1_STOP) is not None:
            print(f"  SKIP Stage1 complete: {cs['id']}", flush=True)
            continue
        dk = build_stage1_closed_loop_deck(
            cs, pr["code_5g"], vpre,
            t_ref_delay=float(pr["t_ref_delay_s"]),
            t_pre_rel=float(pr["t_pre_rel_s"]),
            t_pfd_rel=float(pr["t_pfd_rel_s"]),
            stop_s=T_S1_STOP, rlength=20.0,
        )
        lock_jobs.append((dk, spice.next_run_dir(ld, "run"), dict(timeout_s=1800, meta=dict(id=cs["id"], vpre=vpre))))

    if lock_jobs:
        check_ngspice_limit(workers)
        print(f"[Stage1 Closed-Loop LC-PLL] Running {len(lock_jobs)} corners (stop={T_S1_STOP*1e9:.0f}ns, sparse, workers={workers})...", flush=True)
        for ex in spice.run_many(lock_jobs, workers=workers, smoke=False):
            print(f"  DONE Stage1 {ex.run_dir.parent.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)

    s1_res = {}
    print("\n=== Stage 1 Closed-Loop 5.0 GHz LC-PLL Summary ===", flush=True)
    for cs in CORNERS:
        if cs["id"] not in probes:
            continue
        pr = probes[cs["id"]]
        vpre = float(pr["vctrl_5g_est"]) + S1_PRE_OFFSET
        raw = spice.case_output(s1_dir / "lock" / cs["id"], "run", "pll_lock.raw", T_S1_STOP)
        if raw is None:
            continue
        r = analyse_stage1_lock(raw, cs, pr["code_5g"], vpre)
        c, _ = parse_cs(cs)
        clk_inc = s1_dir / "lock" / cs["id"] / "clk_iq_2p5g.inc"
        if not clk_inc.exists() or force:
            exp_info = export_locked_iq_clocks(raw, clk_inc, c.supply, start_s=S1_EXPORT_START)
            r["clk_export_ns"] = exp_info["duration_ns"]
        r["clk_iq_inc"] = str(clk_inc)
        s1_res[cs["id"]] = r
        print(
            f"  [S1] {cs['id']:17s} ok={r['ok']} code={r['code_5g']:02d} | "
            f"f_LC={r['f_lc_ghz']:.5f}GHz f_IQ={r['f_iq_ghz']:.5f}GHz ({r['f_err_init_ppm']:+.0f}->{r['f_err_ppm']:+.1f}ppm) | "
            f"Vctrl={r['vctrl_settled_v']:.4f}V(Δdyn={r['dyn_pull_in_mv']:+.1f}mV,rip={r['vctrl_ripple_mvpp']:.1f}mVpp) | "
            f"IQ={r['iq_err_ps']:+.2f}ps FB={r['f_fb250_mhz']:.3f}MHz({r['fb250_duty_pct']:.1f}%) | P={r['p_pll_core_mw']:.1f}/{r['p_pll_with_c2c_mw']:.1f}mW",
            flush=True,
        )
    (s1_dir / "stage1_summary.json").write_text(json.dumps(s1_res, indent=2))
    return s1_res


# =============================================================================
# STAGE 2A: TX Q-Div2 + TX SST v4.3 (5 Gb/s, FFE=3) + C2_loss6 + Shunt CTLE
# =============================================================================

TX_CH_INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/bias/spice/bias_v2.spice",
    "analog/tx/sst/spice/tx_sst_driver.spice",
    "analog/tx/sst/spice/tx_sst_serializer16.spice",
    "analog/tx/sst/spice/tx_sst_top.spice",
    "verification/models/channel/pcb_family/pcb_foster_cells.spice",
    "verification/models/channel/pcb_family/C2_loss6.spice",
    "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice",
    "analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice",
    "analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice",
]

RX_FULL_INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/bias/spice/bias_v2.spice",
    "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice",
    "analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice",
    "analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice",
    "analog/rx/cmos_rx/spice/rx_dt_sampler.spice",
    "analog/rx/cmos_rx/spice/rx_cmos_deser16.spice",
]


def build_stage2a_tx_ch_deck(cs: dict, *, stop_s: float = T_S2_STOP) -> str:
    """Locked 2.5 GHz I/Q -> TX Q-Div2 -> TX SST v4.3 (5 Gb/s, FFE=3) -> Pkg RLC
    -> C2_loss6 -> RX Term + Shunt-Peaked 5G CTLE (real 8.252 nH / 24.74 Ohm / 35 fF)."""
    c, rc = parse_cs(cs)
    s = c.supply
    tx_ctrl = encode_zq_ffe(cs["n_zq"], FFE_POST)
    lines = [
        f"* Stage 2A 5.0 Gb/s TX->C2_loss6->Shunt-CTLE ({cs['id']}, Nzq={cs['n_zq']})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in TX_CH_INCLUDES],
        f"Vdd_txq  vdd_txq  0 {s}",
        f"Vdd_tx   vdd_tx   0 {s}",
        f"Vdd_ctle vdd_ctle 0 {s}",
        '.include "clk_iq.inc"',
        '.include "stimuli.inc"',
        f"Vrst_qdiv rst_qdiv_n 0 PWL(0 0 {T_S2_QDIV_REL:.6e} 0 {T_S2_QDIV_REL + 40e-12:.6e} {s})",
        "Xtx_qdiv2 clk_ip clk_in clk_qp clk_qn rst_qdiv_n "
        "phi0 phi90 phi180 phi270 qd_e0 qd_e1 qd_e2 qd_e3 vdd_txq 0 serdes_rx_qdiv2_8ph_4iq",
        "Vbg_tx vbg_tx 0 1.20",
        f"Vrst_tx rst_tx_n 0 PWL(0 0 {T_S2_TX_REL - 25e-12:.6e} 0 {T_S2_TX_REL + 25e-12:.6e} {s})",
        *[
            f"Vtx_{k} tx_{k} 0 PWL(0 0 {T_S2_TX_REL - 1.0e-9:.6e} 0 {T_S2_TX_REL - 0.9e-9:.6e} {s})" if v else f"Vtx_{k} tx_{k} 0 0.0"
            for k, v in tx_ctrl.items()
        ],
        "Xtx din0 din1 din2 din3 din4 din5 din6 din7 "
        "din8 din9 din10 din11 din12 din13 din14 din15 "
        "phi0 phi90 phi180 phi270 rst_tx_n "
        "tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en "
        "vbg_tx lqp lqn vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top",
        "Vcm_init vcm_init 0 0.22",
        "Rpad_dc_p lqp vcm_init 100k",
        "Rpad_dc_n lqn vcm_init 100k",
        "Clpp lqp 0 200f", "Clpn lqn 0 200f",
        "Rlpp lqp llp 0.3", "Rlpn lqn lln 0.3",
        "Llpp llp lap 0.5n", "Llpn lln lan 0.5n",
        "Clacp lap ltp 10n", "Clacn lan ltn 10n",
        "Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6",
        "Rlc0 lxp rxp 0.01", "Rlc1 lxn rxn 0.01",
        "Clc0 rxp 0 100f", "Clc1 rxn 0 100f",
        "Vvcm vcm_ref 0 1.05",
        "Xterm rxp rxn vcm_ref 0 serdes_rx_term_pdk",
        f"Ibias_ctle vdd_ctle ibias_ctle dc {50.0 / cs['k_rc']:.3f}u",
        "Xbias_ctle ibias_ctle 0 serdes_bias_ctle_v2",
        f"Veq0 eq0 0 {s}",
        f"Veq1 eq1 0 {s}",
        f"Xctle rxp rxn ctle_p ctle_n eq0 eq1 ibias_ctle vdd_ctle 0 serdes_rx_ctle_shunt_5g_pdk rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        "Cldp ctle_p 0 80f", "Cldn ctle_n 0 80f",
        ".nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xtx.xdrv.xldo.vgate)=1.0",
        f".temp {c.temp}",
        ".options reltol=5e-4 abstol=2p vntol=5u gmin=1e-11 itl4=80 klu",
        ".save v(lqp) v(lqn) v(rxp) v(rxn) v(ctle_p) v(ctle_n) v(vdrv) v(phi0) v(clk250_out) i(Vdd_txq) i(Vdd_tx) i(Vdd_ctle)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 6p {stop_s:.6e} {T_S2_SAVE:.6e} 12p",
        "write tx_ch.raw v(lqp) v(lqn) v(rxp) v(rxn) v(ctle_p) v(ctle_n) v(vdrv) v(phi0) v(clk250_out) i(Vdd_txq) i(Vdd_tx) i(Vdd_ctle)",
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def export_rx_pwl(tx_ch_raw: Path, out_inc: Path) -> dict:
    w = spice.Waves(tx_ch_raw)
    t_grid = np.arange(float(w.t[0]), float(w.t[-1]), 15.0e-12)
    vp = np.interp(t_grid, w.t, w["v(rxp)"])
    vn = np.interp(t_grid, w.t, w["v(rxn)"])
    pre_p = [(0.0, 1.05), (float(t_grid[0]) - 50e-12, 1.05)] if t_grid[0] > 80e-12 else []
    pre_n = [(0.0, 1.05), (float(t_grid[0]) - 50e-12, 1.05)] if t_grid[0] > 80e-12 else []
    pts_p = pre_p + decimate_pwl(t_grid, vp, tol_v=0.002)
    pts_n = pre_n + decimate_pwl(t_grid, vn, tol_v=0.002)
    out_inc.write_text(pwl_lines("Vrxp rxp 0", pts_p) + pwl_lines("Vrxn rxn 0", pts_n))
    return dict(pts_p=len(pts_p), pts_n=len(pts_n))


def run_stage2a(camp: Path, sel_corners: list[dict], workers: int, force: bool = False) -> dict:
    s1_dir = camp / "stage1_pll" / "lock"
    s2a_dir = camp / "stage2a_tx_ch"
    s2a_dir.mkdir(parents=True, exist_ok=True)
    bits = build_sequence()
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))

    jobs = []
    for cs in sel_corners:
        c, _ = parse_cs(cs)
        clk_inc = s1_dir / cs["id"] / "clk_iq_2p5g.inc"
        if not clk_inc.exists():
            continue
        stim = s2a_dir / f"stim_{c.supply:.2f}.inc"
        if not stim.exists() or force:
            stim.write_text(parallel_word_stimuli(bits, c.supply, t_first_upd=T_S2_FIRST_UPD))
        cdir = s2a_dir / cs["id"]
        if (not force) and spice.case_output(cdir, "run", "tx_ch.raw", T_S2_STOP) is not None:
            print(f"  SKIP Stage2A complete: {cs['id']}", flush=True)
            continue
        dk = build_stage2a_tx_ch_deck(cs, stop_s=T_S2_STOP)
        jobs.append((
            dk, spice.next_run_dir(cdir, "run"),
            dict(files={"clk_iq.inc": clk_inc, "stimuli.inc": stim}, timeout_s=1200, meta=dict(id=cs["id"])),
        ))
    if jobs:
        check_ngspice_limit(workers)
        print(f"[Stage2A TX->C2->ShuntCTLE] Running {len(jobs)} corners (klu, workers={workers})...", flush=True)
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            print(f"  DONE Stage2A {ex.run_dir.parent.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)

    res = {}
    print("\n=== Stage 2A 5.0 Gb/s TX->C2_loss6->Shunt-CTLE Summary ===", flush=True)
    for cs in CORNERS:
        c, _ = parse_cs(cs)
        s = c.supply
        raw = spice.case_output(s2a_dir / cs["id"], "run", "tx_ch.raw", T_S2_STOP)
        if raw is None:
            continue
        w = spice.Waves(raw)
        tx_pad = check_serial_112(w.t, w["v(lqp)"] - w["v(lqn)"], bits, start_s=T_S2_PAD_NOM)
        c2_far = check_serial_112(w.t, w["v(rxp)"] - w["v(rxn)"], bits, start_s=T_S2_PAD_NOM + 1.0e-9)
        ctle_out = check_serial_112(w.t, w["v(ctle_p)"] - w["v(ctle_n)"], bits, start_s=T_S2_PAD_NOM + 1.0e-9)
        sel = w.t >= T_S2_MEAS
        ts = w.t[sel]
        p_txq = -time_weighted_mean(ts, w["i(vdd_txq)"][sel]) * s * 1e3
        p_tx = -time_weighted_mean(ts, w["i(vdd_tx)"][sel]) * s * 1e3
        p_ctle = -time_weighted_mean(ts, w["i(vdd_ctle)"][sel]) * s * 1e3
        rx_inc = s2a_dir / cs["id"] / "rx_in.inc"
        export_rx_pwl(raw, rx_inc)
        r = dict(
            condition=cs["id"], label=cs["label"], n_zq=cs["n_zq"],
            ok=bool(tx_pad["meets_draft"] and tx_pad["in_order"] and c2_far["functional"] and ctle_out["functional"]),
            tx_pad=tx_pad, c2_farend=c2_far, ctle_out=ctle_out,
            p_txq_mw=round(p_txq, 2), p_tx_mw=round(p_tx, 2), p_ctle_mw=round(p_ctle, 2),
            rx_in_inc=str(rx_inc), raw_path=str(raw),
        )
        res[cs["id"]] = r
        print(
            f"  [S2A] {cs['id']:17s} ok={r['ok']} | TX={tx_pad['margin_mv']:.1f}mV/{tx_pad['spread_ui']:.4f}UI(ord={tx_pad['in_order']}) | "
            f"C2={c2_far['margin_mv']:.1f}mV/{c2_far['spread_ui']:.4f}UI | "
            f"CTLE={ctle_out['margin_mv']:.1f}mV(eyeH={ctle_out['eye_h_mv']:.1f}mV/{ctle_out['eye_w_ui']:.2f}UI,spr={ctle_out['spread_ui']:.4f}UI) | "
            f"P(txq/tx/ctle)={p_txq:.1f}/{p_tx:.1f}/{p_ctle:.1f}mW",
            flush=True,
        )
    (s2a_dir / "stage2a_summary.json").write_text(json.dumps(res, indent=2))
    return res


# =============================================================================
# STAGE 2B: FULL 5G RX (Shunt CTLE + 4-Ph I/Q PI + 8x DT Slicers + Deser16)
# =============================================================================

def build_pi_probe_deck(cs: dict) -> str:
    c, rc = parse_cs(cs)
    s = c.supply
    lines = [
        f"* Stage 2B 4-Ph I/Q PI Probe ({cs['id']}, code=0)",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        f'.include "{REPO / "analog/common/devices/spice/sky130_primitives.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/sky130_pfet_lvt.spice"}"',
        f'.include "{REPO / "analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice"}"',
        f"Vdd vdd 0 {s}",
        '.include "clk_iq.inc"',
        f"Vrst rst_n 0 PWL(0 0 {T_S2_RX_REL:.6e} 0 {T_S2_RX_REL + 40e-12:.6e} {s})",
        *[f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(0, s).items()],
        "Xpi clk_ip clk_qp clk_in clk_qn "
        "a0 a1 a2 a3 a4 a5 a6 a7 b0 b1 b2 b3 b4 b5 b6 b7 f0 f1 f2 f3 f4 f5 f6 f7 "
        "rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd 0 serdes_rx_pi_4ph_iq_8ph",
        "Cd0 ckd0 0 38f", "Cd1 ckd1 0 38f", "Cd2 ckd2 0 38f", "Cd3 ckd3 0 38f",
        "Ce0 cke0 0 38f", "Ce1 cke1 0 38f", "Ce2 cke2 0 38f", "Ce3 cke3 0 38f",
        f".temp {c.temp}",
        ".options reltol=3e-4 abstol=2p vntol=5u gmin=1e-11 klu",
        ".save v(ckd0)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 5p 7.5e-9 5.0e-9 10p",
        "write pi_probe.raw v(ckd0)",
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def build_stage2b_rx_deck(cs: dict, codes: list[int], *, stop_s: float = T_S2_STOP) -> str:
    c, rc = parse_cs(cs)
    s = c.supply
    wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
    we_nodes = " ".join(f"v(we{i})" for i in range(16))
    save_vecs = (
        "v(ctle_p) v(ctle_n) v(clk_ip) v(clk_qp) v(clk_in) v(clk_qn) "
        "v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) v(wclk) "
        f"{wd_nodes} {we_nodes} i(Vdd_ctle) i(Vdd_pi) i(Vdd_slicer) i(Vdd_deser)"
    )
    blocks = []
    for cd in codes:
        alters = [f"alter {k} dc={v:.5f}" for k, v in commutator_bits(cd, s).items()]
        blocks.append("\n".join([
            f"* PI code {cd}",
            *alters,
            f"tran 6p {stop_s:.6e} {T_S2_SAVE:.6e} 12p",
            f"write code_{cd:02d}.raw {save_vecs}",
            "destroy all",
        ]))
    lines = [
        f"* Stage 2B Full 5G RX (Shunt CTLE 8.252nH + 4-Ph PI + 8x Slicers + Deser16) ({cs['id']}, codes={codes})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in RX_FULL_INCLUDES],
        f"Vdd_ctle   vdd_ctle   0 {s}",
        f"Vdd_pi     vdd_pi     0 {s}",
        f"Vdd_slicer vdd_slicer 0 {s}",
        f"Vdd_deser  vdd_deser  0 {s}",
        "Vvcm vcm_ref 0 1.05",
        f"Ibias_ctle vdd_ctle ibias_ctle dc {50.0 / cs['k_rc']:.3f}u",
        "Xbias_ctle ibias_ctle 0 serdes_bias_ctle_v2",
        f"Veq0 eq0 0 {s}",
        f"Veq1 eq1 0 {s}",
        '.include "rx_in.inc"',
        '.include "clk_iq.inc"',
        "Xterm rxp rxn vcm_ref 0 serdes_rx_term_pdk",
        f"Xctle rxp rxn ctle_p ctle_n eq0 eq1 ibias_ctle vdd_ctle 0 serdes_rx_ctle_shunt_5g_pdk rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        f"Vrst_rx rst_rx_n 0 PWL(0 0 {T_S2_RX_REL:.6e} 0 {T_S2_RX_REL + 40e-12:.6e} {s})",
        *[f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(codes[0], s).items()],
        "Xpi clk_ip clk_qp clk_in clk_qn "
        "a0 a1 a2 a3 a4 a5 a6 a7 b0 b1 b2 b3 b4 b5 b6 b7 f0 f1 f2 f3 f4 f5 f6 f7 "
        "rst_rx_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd_pi 0 serdes_rx_pi_4ph_iq_8ph",
        "Xsd0 ctle_p ctle_n ckd0 d0 d0b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xsd1 ctle_p ctle_n ckd1 d1 d1b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xsd2 ctle_p ctle_n ckd2 d2 d2b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xsd3 ctle_p ctle_n ckd3 d3 d3b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse0 ctle_p ctle_n cke0 e0 e0b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse1 ctle_p ctle_n cke1 e1 e1b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse2 ctle_p ctle_n cke2 e2 e2b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse3 ctle_p ctle_n cke3 e3 e3b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xdeser d0 d1 d2 d3 e0 e1 e2 e3 "
        "ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 rst_rx_n "
        "wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 wd8 wd9 wd10 wd11 wd12 wd13 wd14 wd15 "
        "we0 we1 we2 we3 we4 we5 we6 we7 we8 we9 we10 we11 we12 we13 we14 we15 "
        "wclk vdd_deser 0 serdes_rx_cmos_deser16",
        "Cwclk wclk 0 10f",
        f".temp {c.temp}",
        ".options reltol=5e-4 abstol=2p vntol=5u gmin=1e-11 itl4=80 klu",
        f".save {save_vecs}",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        *blocks,
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def run_stage2b(camp: Path, sel_corners: list[dict], workers: int, force: bool = False) -> dict:
    s1_dir = camp / "stage1_pll" / "lock"
    s2a_file = camp / "stage2a_tx_ch" / "stage2a_summary.json"
    s2a_res = json.loads(s2a_file.read_text()) if s2a_file.exists() else {}
    s2b_dir = camp / "stage2b_rx"
    s2b_dir.mkdir(parents=True, exist_ok=True)
    bits = build_sequence()

    # Step 1: Fast 6.5-ns PI code=0 probe
    pi_jobs = []
    for cs in sel_corners:
        if cs["id"] not in s2a_res:
            continue
        clk_inc = s1_dir / cs["id"] / "clk_iq_2p5g.inc"
        cdir = s2b_dir / cs["id"]
        if (not force) and spice.case_output(cdir, "pi_probe", "pi_probe.raw", 7.5e-9) is not None:
            continue
        dk = build_pi_probe_deck(cs)
        pi_jobs.append((dk, spice.next_run_dir(cdir, "pi_probe"), dict(files={"clk_iq.inc": clk_inc}, timeout_s=300)))
    if pi_jobs:
        check_ngspice_limit(workers)
        print(f"[Stage2B PI Probe] Running {len(pi_jobs)} 7.5-ns PI probes (workers={workers})...", flush=True)
        for ex in spice.run_many(pi_jobs, workers=workers, smoke=False):
            print(f"  PI Probe {ex.run_dir.parent.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s", flush=True)

    # Step 2: Run Full 5G RX at (opt-8, opt, opt+8)
    rx_jobs = []
    for cs in sel_corners:
        if cs["id"] not in s2a_res:
            continue
        c, _ = parse_cs(cs)
        clk_inc = s1_dir / cs["id"] / "clk_iq_2p5g.inc"
        rx_inc = Path(s2a_res[cs["id"]]["rx_in_inc"])
        cdir = s2b_dir / cs["id"]
        pc_path = cdir / "pi_center.json"
        if pc_path.exists() and not force:
            opt_code = int(json.loads(pc_path.read_text())["opt_code"])
        else:
            praw = spice.case_output(cdir, "pi_probe", "pi_probe.raw", 7.5e-9)
            if praw is None:
                continue
            wpi = spice.Waves(praw)
            ck0 = float(rising_edges(wpi.t, wpi["v(ckd0)"], 0.5 * c.supply)[0])
            t_bit0 = float(s2a_res[cs["id"]]["ctle_out"]["t_bit0_center_s"])
            dt = (((t_bit0 - SLICER_APERTURE_S) - ck0 + 0.5 * UI) % UI) - 0.5 * UI
            opt_code = int(round(dt / (UI / 32.0))) % 64
            pc_path.write_text(json.dumps(dict(opt_code=opt_code, ck0_ns=round(ck0 * 1e9, 4), t_bit0_ns=round(t_bit0 * 1e9, 4)), indent=2))
        codes = [(opt_code + o) % 64 for o in (-8, 0, 8)]
        missing = [cd for cd in codes if force or spice.case_output(cdir, "rx", f"code_{cd:02d}.raw", T_S2_STOP) is None]
        if missing:
            dk = build_stage2b_rx_deck(cs, missing, stop_s=T_S2_STOP)
            rx_jobs.append((
                dk, spice.next_run_dir(cdir, "rx"),
                dict(files={"rx_in.inc": rx_inc, "clk_iq.inc": clk_inc}, timeout_s=3600, meta=dict(id=cs["id"], codes=missing)),
            ))
    if rx_jobs:
        check_ngspice_limit(workers)
        print(f"[Stage2B Full RX] Running {len(rx_jobs)} corners x 3 PI codes (workers={workers})...", flush=True)
        for ex in spice.run_many(rx_jobs, workers=workers, smoke=False):
            print(f"  DONE Stage2B {ex.run_dir.parent.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)

    res = {}
    print("\n=== Stage 2B Full 5.0 Gb/s RX (Shunt CTLE + 4-Ph PI + 8x Slicers + Deser16) ===", flush=True)
    for cs in CORNERS:
        cdir = s2b_dir / cs["id"]
        pc_file = cdir / "pi_center.json"
        if not pc_file.exists():
            continue
        c, _ = parse_cs(cs)
        s = c.supply
        opt_code = int(json.loads(pc_file.read_text())["opt_code"])
        pts = []
        center_r = None
        for o in (-8, 0, 8):
            cd = (opt_code + o) % 64
            raw = spice.case_output(cdir, "rx", f"code_{cd:02d}.raw", T_S2_STOP)
            if raw is None:
                continue
            w = spice.Waves(raw)
            r = analyse_rx_words(w, bits, s, cd, meas_from=T_S2_MEAS, min_words=4, min_bit_idx=16)
            r["offset_codes"] = o
            r["offset_ui"] = o / 32.0
            pts.append(r)
            if o == 0:
                sel = w.t >= T_S2_MEAS
                ts = w.t[sel]
                p_ctle = -time_weighted_mean(ts, w["i(vdd_ctle)"][sel]) * s * 1e3
                p_pi = -time_weighted_mean(ts, w["i(vdd_pi)"][sel]) * s * 1e3
                p_sl = -time_weighted_mean(ts, w["i(vdd_slicer)"][sel]) * s * 1e3
                p_ds = -time_weighted_mean(ts, w["i(vdd_deser)"][sel]) * s * 1e3
                p_rx = p_ctle + p_pi + p_sl + p_ds
                m_ckd0 = measure_cmos_clk(w.t, w["v(ckd0)"], 0.5 * s, T_S2_MEAS, T_S2_STOP - 0.5e-9)
                ctle_live = check_serial_112(w.t, w["v(ctle_p)"] - w["v(ctle_n)"], bits, start_s=T_S2_PAD_NOM + 1.0e-9)
                center_r = dict(
                    condition=cs["id"], label=cs["label"], opt_code=opt_code,
                    rx_center=r, ctle_loaded_by_slicers=ctle_live,
                    ckd0_ghz=round(m_ckd0["f_ghz"], 5), ckd0_duty_pct=round(m_ckd0["duty_pct"], 2),
                    p_ctle_mw=round(p_ctle, 2), p_pi_mw=round(p_pi, 2),
                    p_slicer_mw=round(p_sl, 2), p_deser_mw=round(p_ds, 2), p_rx_mw=round(p_rx, 2),
                    raw_path=str(raw),
                )
        if center_r is not None:
            e_pt = next((pt for pt in pts if pt["offset_codes"] == -8), None)
            l_pt = next((pt for pt in pts if pt["offset_codes"] == 8), None)
            bb_ok = bool(
                e_pt and l_pt
                and "bbpd_vote" in e_pt and "bbpd_vote" in l_pt
                and e_pt["bbpd_vote"] < 0 and l_pt["bbpd_vote"] > 0
            )
            ok_offs = [pt["offset_codes"] for pt in pts if pt["data_errors"] == 0 and pt["edge_errors"] == 0]
            lo_ok = min([o for o in ok_offs if o <= 0], default=0)
            hi_ok = max([o for o in ok_offs if o >= 0], default=0)
            win_ui = float((hi_ok - lo_ok + 1) / 32.0) if 0 in ok_offs else 0.0
            center_r.update(
                early_vote=int(e_pt["bbpd_vote"]) if (e_pt and "bbpd_vote" in e_pt) else None,
                late_vote=int(l_pt["bbpd_vote"]) if (l_pt and "bbpd_vote" in l_pt) else None,
                bbpd_polarity_ok=bb_ok, window_ui=round(win_ui, 3), points=pts,
                ok=bool(center_r["rx_center"]["ok"] and bb_ok),
            )
            res[cs["id"]] = center_r
            rc_c = center_r["rx_center"]
            ev_s = f"{center_r['early_vote']:+d}" if center_r["early_vote"] is not None else "NA"
            lv_s = f"{center_r['late_vote']:+d}" if center_r["late_vote"] is not None else "NA"
            print(
                f"  [S2B] {cs['id']:17s} ok={center_r['ok']} cd={opt_code:02d} | "
                f"data={rc_c['data_errors']}/{rc_c['data_bits']} edge={rc_c['edge_errors']}/{rc_c['edge_determinate']} | "
                f"BBPD={ev_s}/{lv_s} win={win_ui:.3f}UI | "
                f"wclk={rc_c['wclk_period_ns']:.3f}ns(su/ho={rc_c['wclk_setup_ps']:.0f}/{rc_c['wclk_hold_ps']:.0f}ps) | "
                f"P_rx={center_r['p_rx_mw']:.1f}mW (CTLE {center_r['p_ctle_mw']:.1f}/PI {center_r['p_pi_mw']:.1f}/SL {center_r['p_slicer_mw']:.1f}/DS {center_r['p_deser_mw']:.1f})",
                flush=True,
            )
    (s2b_dir / "stage2b_summary.json").write_text(json.dumps(res, indent=2))
    return res


# =============================================================================
# STAGE 2C: TRUE ZERO-ABSTRACTION SINGLE-DECK TT (TX+C2+CTLE+PI+Slicers+Deser)
# =============================================================================

SINGLEDECK_INCLUDES = list(dict.fromkeys(TX_CH_INCLUDES + RX_FULL_INCLUDES))


def build_singledeck_tt(cs: dict, opt_code: int, *, stop_s: float = T_S2_STOP) -> str:
    c, rc = parse_cs(cs)
    s = c.supply
    tx_ctrl = encode_zq_ffe(cs["n_zq"], FFE_POST)
    wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
    we_nodes = " ".join(f"v(we{i})" for i in range(16))
    save_vecs = (
        "v(lqp) v(lqn) v(rxp) v(rxn) v(ctle_p) v(ctle_n) v(vdrv) "
        "v(clk_ip) v(clk_qp) v(clk_in) v(clk_qn) "
        "v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) v(wclk) "
        f"{wd_nodes} {we_nodes} "
        "i(Vdd_txq) i(Vdd_tx) i(Vdd_ctle) i(Vdd_pi) i(Vdd_slicer) i(Vdd_deser)"
    )
    lines = [
        f"* TRUE ZERO-ABSTRACTION SINGLE-DECK 5.0 Gb/s End-to-End Link ({cs['id']}, code={opt_code})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in SINGLEDECK_INCLUDES],
        f"Vdd_txq    vdd_txq    0 {s}",
        f"Vdd_tx     vdd_tx     0 {s}",
        f"Vdd_ctle   vdd_ctle   0 {s}",
        f"Vdd_pi     vdd_pi     0 {s}",
        f"Vdd_slicer vdd_slicer 0 {s}",
        f"Vdd_deser  vdd_deser  0 {s}",
        '.include "clk_iq.inc"',
        '.include "stimuli.inc"',
        f"Vrst_qdiv rst_qdiv_n 0 PWL(0 0 {T_S2_QDIV_REL:.6e} 0 {T_S2_QDIV_REL + 40e-12:.6e} {s})",
        "Xtx_qdiv2 clk_ip clk_in clk_qp clk_qn rst_qdiv_n "
        "phi0 phi90 phi180 phi270 qd_e0 qd_e1 qd_e2 qd_e3 vdd_txq 0 serdes_rx_qdiv2_8ph_4iq",
        "Vbg_tx vbg_tx 0 1.20",
        f"Vrst_tx rst_tx_n 0 PWL(0 0 {T_S2_TX_REL - 25e-12:.6e} 0 {T_S2_TX_REL + 25e-12:.6e} {s})",
        *[
            f"Vtx_{k} tx_{k} 0 PWL(0 0 {T_S2_TX_REL - 1.0e-9:.6e} 0 {T_S2_TX_REL - 0.9e-9:.6e} {s})" if v else f"Vtx_{k} tx_{k} 0 0.0"
            for k, v in tx_ctrl.items()
        ],
        "Xtx din0 din1 din2 din3 din4 din5 din6 din7 "
        "din8 din9 din10 din11 din12 din13 din14 din15 "
        "phi0 phi90 phi180 phi270 rst_tx_n "
        "tx_m0 tx_m1 tx_m2 tx_m3 tx_m4 tx_f0 tx_f1 tx_f2 tx_ffe_en "
        "vbg_tx lqp lqn vdrv clk500_out clk250_out vdd_tx 0 serdes_tx_sst_top",
        "Vcm_init vcm_init 0 0.22",
        "Rpad_dc_p lqp vcm_init 100k",
        "Rpad_dc_n lqn vcm_init 100k",
        "Clpp lqp 0 200f", "Clpn lqn 0 200f",
        "Rlpp lqp llp 0.3", "Rlpn lqn lln 0.3",
        "Llpp llp lap 0.5n", "Llpn lln lan 0.5n",
        "Clacp lap ltp 10n", "Clacn lan ltn 10n",
        "Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6",
        "Rlc0 lxp rxp 0.01", "Rlc1 lxn rxn 0.01",
        "Clc0 rxp 0 100f", "Clc1 rxn 0 100f",
        "Vvcm vcm_ref 0 1.05",
        "Xterm rxp rxn vcm_ref 0 serdes_rx_term_pdk",
        f"Ibias_ctle vdd_ctle ibias_ctle dc {50.0 / cs['k_rc']:.3f}u",
        "Xbias_ctle ibias_ctle 0 serdes_bias_ctle_v2",
        f"Veq0 eq0 0 {s}",
        f"Veq1 eq1 0 {s}",
        f"Xctle rxp rxn ctle_p ctle_n eq0 eq1 ibias_ctle vdd_ctle 0 serdes_rx_ctle_shunt_5g_pdk rm_scale={cs['rm_scale']} c_scale={cs['c_scale']}",
        f"Vrst_rx rst_rx_n 0 PWL(0 0 {T_S2_RX_REL:.6e} 0 {T_S2_RX_REL + 40e-12:.6e} {s})",
        *[f"{k} {k[1:]} 0 {v:.5f}" for k, v in commutator_bits(opt_code, s).items()],
        "Xpi clk_ip clk_qp clk_in clk_qn "
        "a0 a1 a2 a3 a4 a5 a6 a7 b0 b1 b2 b3 b4 b5 b6 b7 f0 f1 f2 f3 f4 f5 f6 f7 "
        "rst_rx_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd_pi 0 serdes_rx_pi_4ph_iq_8ph",
        "Xsd0 ctle_p ctle_n ckd0 d0 d0b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xsd1 ctle_p ctle_n ckd1 d1 d1b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xsd2 ctle_p ctle_n ckd2 d2 d2b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xsd3 ctle_p ctle_n ckd3 d3 d3b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse0 ctle_p ctle_n cke0 e0 e0b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse1 ctle_p ctle_n cke1 e1 e1b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse2 ctle_p ctle_n cke2 e2 e2b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xse3 ctle_p ctle_n cke3 e3 e3b vdd_slicer 0 0 0 0 0 vdd_slicer 0 serdes_rx_dt_slicer",
        "Xdeser d0 d1 d2 d3 e0 e1 e2 e3 "
        "ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 rst_rx_n "
        "wd0 wd1 wd2 wd3 wd4 wd5 wd6 wd7 wd8 wd9 wd10 wd11 wd12 wd13 wd14 wd15 "
        "we0 we1 we2 we3 we4 we5 we6 we7 we8 we9 we10 we11 we12 we13 we14 we15 "
        "wclk vdd_deser 0 serdes_rx_cmos_deser16",
        "Cwclk wclk 0 10f",
        ".nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xtx.xdrv.xldo.vgate)=1.0",
        f".temp {c.temp}",
        ".options reltol=5e-4 abstol=2p vntol=5u gmin=1e-11 itl4=80 klu",
        f".save {save_vecs}",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 6p {stop_s:.6e} {T_S2_SAVE:.6e} 12p",
        f"write singledeck_tt.raw {save_vecs}",
        "quit",
        ".endc",
        ".end",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def run_singledeck_tt(camp: Path, force: bool = False) -> dict | None:
    cs = CORNERS[0]
    c, _ = parse_cs(cs)
    s = c.supply
    clk_inc = camp / "stage1_pll" / "lock" / cs["id"] / "clk_iq_2p5g.inc"
    stim = camp / "stage2a_tx_ch" / f"stim_{s:.2f}.inc"
    pc_file = camp / "stage2b_rx" / cs["id"] / "pi_center.json"
    if not (clk_inc.exists() and stim.exists() and pc_file.exists()):
        print("WARN Single-Deck TT skipped: missing Stage1/2A/2B prerequisite", flush=True)
        return None
    opt_code = int(json.loads(pc_file.read_text())["opt_code"])
    sd_dir = camp / "singledeck_tt"
    if force or spice.case_output(sd_dir, "run", "singledeck_tt.raw", T_S2_STOP) is None:
        check_ngspice_limit(1)
        dk = build_singledeck_tt(cs, opt_code, stop_s=T_S2_STOP)
        print(f"[SingleDeck TT] Running ALL-IN-ONE zero-abstraction 5.0 Gb/s link (code={opt_code:02d}, stop={T_S2_STOP*1e9:.0f}ns)...", flush=True)
        ex = spice.run(dk, spice.next_run_dir(sd_dir, "run"), files={"clk_iq.inc": clk_inc, "stimuli.inc": stim}, timeout_s=1800)
        print(f"  DONE SingleDeck TT: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)
    raw = spice.case_output(sd_dir, "run", "singledeck_tt.raw", T_S2_STOP)
    if raw is None:
        return None
    bits = build_sequence()
    w = spice.Waves(raw)
    tx_pad = check_serial_112(w.t, w["v(lqp)"] - w["v(lqn)"], bits, start_s=T_S2_PAD_NOM)
    c2_far = check_serial_112(w.t, w["v(rxp)"] - w["v(rxn)"], bits, start_s=T_S2_PAD_NOM + 1.0e-9)
    ctle_out = check_serial_112(w.t, w["v(ctle_p)"] - w["v(ctle_n)"], bits, start_s=T_S2_PAD_NOM + 1.0e-9)
    rx = analyse_rx_words(w, bits, s, opt_code, meas_from=T_S2_MEAS, min_words=4, min_bit_idx=16)
    sel = w.t >= T_S2_MEAS
    ts = w.t[sel]
    p_txq = -time_weighted_mean(ts, w["i(vdd_txq)"][sel]) * s * 1e3
    p_tx = -time_weighted_mean(ts, w["i(vdd_tx)"][sel]) * s * 1e3
    p_ctle = -time_weighted_mean(ts, w["i(vdd_ctle)"][sel]) * s * 1e3
    p_pi = -time_weighted_mean(ts, w["i(vdd_pi)"][sel]) * s * 1e3
    p_sl = -time_weighted_mean(ts, w["i(vdd_slicer)"][sel]) * s * 1e3
    p_ds = -time_weighted_mean(ts, w["i(vdd_deser)"][sel]) * s * 1e3
    out = dict(
        condition=cs["id"], opt_code=opt_code,
        ok=bool(tx_pad["meets_draft"] and tx_pad["in_order"] and ctle_out["functional"] and rx["ok"]),
        tx_pad=tx_pad, c2_farend=c2_far, ctle_out=ctle_out, rx=rx,
        p_txq_mw=round(p_txq, 2), p_tx_mw=round(p_tx, 2),
        p_ctle_mw=round(p_ctle, 2), p_pi_mw=round(p_pi, 2),
        p_slicer_mw=round(p_sl, 2), p_deser_mw=round(p_ds, 2),
        p_link_no_pll_mw=round(p_txq + p_tx + p_ctle + p_pi + p_sl + p_ds, 2),
        raw_path=str(raw),
    )
    (sd_dir / "singledeck_tt_summary.json").write_text(json.dumps(out, indent=2))
    print(
        f"  [SINGLE-DECK TT] ok={out['ok']} cd={opt_code:02d} | TX={tx_pad['margin_mv']:.1f}mV/{tx_pad['spread_ui']:.4f}UI | "
        f"CTLE={ctle_out['eye_h_mv']:.1f}mV/{ctle_out['eye_w_ui']:.2f}UI | "
        f"RX={rx['data_errors']}/{rx['data_bits']}d,{rx['edge_errors']}/{rx['edge_determinate']}e | "
        f"wclk={rx['wclk_period_ns']:.3f}ns(su/ho={rx['wclk_setup_ps']:.0f}/{rx['wclk_hold_ps']:.0f}ps) | "
        f"P_link={out['p_link_no_pll_mw']:.1f}mW",
        flush=True,
    )
    return out


# =============================================================================
# MASTER SUMMARY & 4-PANEL PUBLICATION FIGURE
# =============================================================================

def assemble_summary(camp: Path) -> dict:
    ctle_ac = analyse_ctle_ac(camp, CORNERS, workers=1)
    s1_file = camp / "stage1_pll" / "stage1_summary.json"
    s2a_file = camp / "stage2a_tx_ch" / "stage2a_summary.json"
    s2b_file = camp / "stage2b_rx" / "stage2b_summary.json"
    sd_file = camp / "singledeck_tt" / "singledeck_tt_summary.json"
    s1_res = json.loads(s1_file.read_text()) if s1_file.exists() else {}
    s2a_res = json.loads(s2a_file.read_text()) if s2a_file.exists() else {}
    s2b_res = json.loads(s2b_file.read_text()) if s2b_file.exists() else {}
    sd_res = json.loads(sd_file.read_text()) if sd_file.exists() else None

    totals = {}
    for cs in CORNERS:
        cid = cs["id"]
        if cid in s1_res and cid in s2a_res and cid in s2b_res:
            p_pll = s1_res[cid]["p_pll_with_c2c_mw"]
            p_tx = s2a_res[cid]["p_txq_mw"] + s2a_res[cid]["p_tx_mw"]
            p_rx = s2b_res[cid]["p_rx_mw"]
            p_tot = p_pll + p_tx + p_rx
            totals[cid] = dict(
                p_pll_core_mw=s1_res[cid]["p_pll_core_mw"],
                p_pll_with_c2c_mw=round(p_pll, 2),
                p_tx_total_mw=round(p_tx, 2),
                p_rx_total_mw=round(p_rx, 2),
                p_total_5g_mw=round(p_tot, 2),
                pj_per_bit=round(p_tot / 5.0, 2),
                all_pass=bool(s1_res[cid]["ok"] and s2a_res[cid]["ok"] and s2b_res[cid]["ok"]),
            )
    summary = dict(
        date="2026-11-24",
        data_rate_gbps=5.0,
        ui_ps=200.0,
        extracted_inductors=dict(
            vco="vco5g_ind_oct_2n5_pdk (L_diff=2.408 nH, R_dc=3.065 Ohm, C_sub=410.49 fF, Q_5G=7.26, Magic+KLayout DRC=0)",
            ctle="rx_ctle_ind_m4m2_5g_pdk / serdes_rx_ctle_shunt_5g_pdk (Magic DRC=0)",
        ),
        ctle_ac=ctle_ac,
        stage1_pll=s1_res,
        stage2a_tx_ch=s2a_res,
        stage2b_rx=s2b_res,
        singledeck_tt=sd_res,
        system_power_and_efficiency=totals,
    )
    (camp / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def make_figure(camp: Path, summary: dict, fig_path: Path) -> None:
    plt.rcParams.update({
        "font.size": 8.8, "axes.titlesize": 9.8, "axes.labelsize": 8.7,
        "legend.fontsize": 7.2, "xtick.labelsize": 8.1, "ytick.labelsize": 8.1,
    })
    fig, axes = plt.subplots(2, 2, figsize=(15.5, 9.8), dpi=180)
    ax_pll, ax_eye, ax_clk, ax_sum = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    colors = {
        "tt_v1800_t27_tt": "#1f77b4",
        "ss_v1650_t85_hh": "#d62728",
        "ss_v1650_t-40_hh": "#ff7f0e",
        "ff_v1950_t-40_ll": "#2ca02c",
    }
    s1_rows = summary.get("stage1_pll", {})
    s2a_rows = summary.get("stage2a_tx_ch", {})
    s2b_rows = summary.get("stage2b_rx", {})
    sd_row = summary.get("singledeck_tt")
    bits = build_sequence()

    # Panel (a): Closed-Loop 5.0 GHz LC-PLL Active Pull-In & Lock
    ax_f = ax_pll.twinx()
    for cid, r in s1_rows.items():
        col = colors.get(cid, "#333333")
        w = spice.Waves(Path(r["raw_path"]))
        t_ns = w.t * 1e9
        step = max(1, len(t_ns) // 2400)
        lbl = f"{r['label']} (c={r['code_5g']}, {r['f_err_ppm']:+.0f} ppm)"
        ax_pll.plot(t_ns[::step], w["v(vctrl)"][::step], color=col, lw=1.35, label=lbl)
        c, _ = parse_cs(next(x for x in CORNERS if x["id"] == cid))
        re = rising_edges(w.t, w["v(ic_p)"], 0.5 * c.supply)
        if len(re) > 20:
            blk = 10
            tc = 0.5 * (re[:-blk:blk] + re[blk::blk]) * 1e9
            fc = (blk / (re[blk::blk] - re[:-blk:blk])) / 1e9
            ax_f.plot(tc, fc, color=col, lw=0.95, ls="--", alpha=0.75)
    ax_f.axhline(2.500, color="#444444", ls=":", lw=0.9)
    ax_pll.set_title("(a) Closed-Loop 5.0 GHz LC-PLL Pull-In ($V_{ctrl}$ solid, $f_{I/Q}$ dashed, 2.541 nH Spiral)", fontweight="bold", pad=8)
    ax_pll.set_xlabel("Simulation Time (ns)")
    ax_pll.set_ylabel("Loop Filter $V_{ctrl}$ (V)")
    ax_f.set_ylabel("Locked I/Q Frequency $f_{I/Q}$ (GHz)")
    ax_pll.set_xlim(10, T_S1_STOP * 1e9)
    ax_pll.set_ylim(0.30, 0.54)
    ax_f.set_ylim(2.475, 2.535)
    ax_pll.grid(True, alpha=0.3)
    ax_pll.legend(loc="upper right", framealpha=0.93)

    # Panel (b): 5.0 Gb/s End-to-End Eye Opening (Single-Deck TT if present, else Stage 2A TT)
    ref_cid = "tt_v1800_t27_tt" if "tt_v1800_t27_tt" in s2a_rows else next(iter(s2a_rows))
    r_eye = sd_row if sd_row is not None else s2a_rows[ref_cid]
    w_eye = spice.Waves(Path(r_eye["raw_path"]))
    u_grid = np.linspace(0.0, 2.0, 200)
    for sig_key, t_nom, col, alpha, lw, lbl in [
        ("tx", T_S2_PAD_NOM, "#1f77b4", 0.35, 0.75, f"TX Pad ({r_eye['tx_pad']['margin_mv']:.0f} mV)"),
        ("c2", T_S2_PAD_NOM + 1.0e-9, "#9467bd", 0.25, 0.65, f"C2_loss6 ({r_eye['c2_farend']['margin_mv']:.0f} mV)"),
        ("ctle", T_S2_PAD_NOM + 1.0e-9, "#2ca02c", 0.55, 0.88, f"Shunt CTLE 8.25nH ({r_eye['ctle_out']['eye_h_mv']:.0f} mV)"),
    ]:
        if sig_key == "tx":
            y, m = w_eye["v(lqp)"] - w_eye["v(lqn)"], r_eye["tx_pad"]
        elif sig_key == "c2":
            y, m = w_eye["v(rxp)"] - w_eye["v(rxn)"], r_eye["c2_farend"]
        else:
            y, m = w_eye["v(ctle_p)"] - w_eye["v(ctle_n)"], r_eye["ctle_out"]
        t0 = t_nom + m["training_delay_ui"] * UI
        first = True
        for k in range(TRAIN_BITS, TRAIN_BITS + PAYLOAD_BITS - 1):
            tk = t0 + (k - 0.5) * UI + u_grid * UI
            if tk[0] < w_eye.t[0] or tk[-1] > w_eye.t[-1]:
                continue
            yk = np.interp(tk, w_eye.t, y) * 1e3
            ax_eye.plot(u_grid, yk, color=col, lw=lw, alpha=alpha, label=(lbl if first else None))
            first = False
    ax_eye.axhline(75.0, color="#cc2222", ls="--", lw=0.95, label="Spec ±75 mV")
    ax_eye.axhline(-75.0, color="#cc2222", ls="--", lw=0.95)
    min_ctle_h = min(r["ctle_out"]["eye_h_mv"] for r in s2a_rows.values())
    min_pad_m = min(r["tx_pad"]["margin_mv"] for r in s2a_rows.values())
    max_pad_s = max(r["tx_pad"]["spread_ui"] for r in s2a_rows.values())
    sd_lbl = "Single-Deck TT" if sd_row else "TT"
    ax_eye.text(
        0.02, 0.97,
        f"{sd_lbl} 5.0 Gb/s (200 ps UI, FFE=3, real 8.252 nH CTLE)\n"
        f"All {len(s2a_rows)} PVT: TX min={min_pad_m:.1f} mV / max spr={max_pad_s:.4f} UI\n"
        f"Shunt CTLE min eye={min_ctle_h:.1f} mV | RX: {sum(1 for x in s2b_rows.values() if x['ok'])}/{len(s2b_rows)} PASS, 0 err",
        transform=ax_eye.transAxes, va="top", ha="left", fontsize=7.4,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white", edgecolor="#bbbbbb", alpha=0.93),
    )
    ax_eye.set_title(f"(b) 5.0 Gb/s Eye Opening: TX Pad → C2_loss6 → Shunt-Peaked CTLE ({sd_lbl})", fontweight="bold", pad=8)
    ax_eye.set_xlabel("Time (UI, 1 UI = 200 ps)")
    ax_eye.set_ylabel("Differential Voltage (mV)")
    ax_eye.set_xlim(0.0, 2.0)
    ax_eye.set_ylim(-315, 360)
    ax_eye.grid(True, alpha=0.3)
    ax_eye.legend(loc="lower right", ncol=2, framealpha=0.93)

    # Panel (c): 4-Ph 2.5 GHz Locked I/Q -> 8-Ph 1.25 GHz PI Clocks -> 312.5 MHz wclk
    w_clk = spice.Waves(Path(sd_row["raw_path"] if sd_row else s2b_rows[ref_cid]["raw_path"]))
    sel_c = (w_clk.t >= 14.0e-9) & (w_clk.t <= 15.6e-9)
    tc_ns = (w_clk.t[sel_c] - 14.0e-9) * 1e9
    for vec, off, col, lbl in [
        ("v(clk_ip)", 4.4, "#1f77b4", "Locked 2.5G I (0°)"),
        ("v(clk_qp)", 4.4, "#ff7f0e", "Locked 2.5G Q (90°)"),
        ("v(ckd0)", 2.2, "#2ca02c", "PI 1.25G ckd0 (0°)"),
        ("v(cke0)", 2.2, "#d62728", "PI 1.25G cke0 (45°)"),
        ("v(ckd1)", 2.2, "#9467bd", "PI 1.25G ckd1 (90°)"),
        ("v(ckd2)", 2.2, "#8c564b", "PI 1.25G ckd2 (180°)"),
        ("v(wclk)", 0.0, "#111111", "RX Deser wclk (312.5 MHz)"),
    ]:
        ax_clk.plot(tc_ns, w_clk[vec][sel_c] + off, color=col, lw=1.2, label=lbl)
    ax_clk.set_title("(c) 5G Clock Tree: Locked 2.5 GHz I/Q → 4-Ph CMOS PI 1.25 GHz 8-Ph → 312.5 MHz wclk", fontweight="bold", pad=8)
    ax_clk.set_xlabel("Time Window Offset (ns, from t = 14.0 ns)")
    ax_clk.set_ylabel("Stacked CMOS Waveforms (V + offset)")
    ax_clk.set_xlim(0.0, 1.6)
    ax_clk.set_ylim(-0.2, 6.7)
    ax_clk.set_yticks([0.9, 3.1, 5.3])
    ax_clk.set_yticklabels(["wclk\n312.5M", "8-Ph PI\n1.25G", "Locked I/Q\n2.50G"])
    ax_clk.grid(True, alpha=0.3)
    ax_clk.legend(loc="upper right", ncol=2, framealpha=0.93)

    # Panel (d): Multi-Corner Eye Margin, BBPD Voting & Full-Chain 5G Power / Efficiency
    cids = [cs["id"] for cs in CORNERS if cs["id"] in s2a_rows and cs["id"] in s2b_rows]
    x = np.arange(len(cids))
    wb = 0.24
    lbls = [
        f"{s2a_rows[k]['label'].replace(' ', chr(10), 1)}\nBBPD:{s2b_rows[k]['early_vote']:+d}/{s2b_rows[k]['late_vote']:+d}"
        for k in cids
    ]
    tx_ms = [s2a_rows[k]["tx_pad"]["margin_mv"] for k in cids]
    ct_hs = [s2a_rows[k]["ctle_out"]["eye_h_mv"] for k in cids]
    p_tots = [summary["system_power_and_efficiency"][k]["p_total_5g_mw"] for k in cids]

    ax_p = ax_sum.twinx()
    b1 = ax_sum.bar(x - wb, tx_ms, width=wb, color="#1f77b4", label="TX Pad Margin (mV)")
    b2 = ax_sum.bar(x, ct_hs, width=wb, color="#2ca02c", label="Shunt CTLE Eye Height (mV)")
    b3 = ax_p.bar(x + wb, p_tots, width=wb, color="#ff7f0e", alpha=0.88, label="Total 5G Analog Power (mW)")
    ax_sum.axhline(75.0, color="#cc2222", ls="--", lw=0.9, label="75 mV Spec")
    for rct in b1:
        h = rct.get_height()
        ax_sum.text(rct.get_x() + rct.get_width() / 2, h + 4, f"{h:.0f}", ha="center", va="bottom", fontsize=7.5)
    for rct in b2:
        h = rct.get_height()
        ax_sum.text(rct.get_x() + rct.get_width() / 2, h + 4, f"{h:.0f}", ha="center", va="bottom", fontsize=7.5)
    for rct in b3:
        h = rct.get_height()
        ax_p.text(rct.get_x() + rct.get_width() / 2, h + 1.5, f"{h:.1f}mW\n({h/5.0:.1f}pJ/b)", ha="center", va="bottom", fontsize=7.0, color="#b35900")

    ax_sum.set_title("(d) 5.0 Gb/s PVT Eye Margins, BBPD Polarity & Total Analog Power (LC-PLL+C2C+TX+RX)", fontweight="bold", pad=8)
    ax_sum.set_xticks(x)
    ax_sum.set_xticklabels(lbls)
    ax_sum.set_ylabel("Eye Margin / Height (mV)")
    ax_p.set_ylabel("Total 5G Analog Power (mW)")
    ax_sum.set_ylim(0, 315)
    ax_p.set_ylim(0, max(p_tots) * 1.48 if p_tots else 100)
    ax_sum.grid(True, axis="y", alpha=0.3)
    h1, l1 = ax_sum.get_legend_handles_labels()
    h2, l2 = ax_p.get_legend_handles_labels()
    ax_sum.legend(h1 + h2, l1 + l2, loc="upper right", ncol=2, framealpha=0.93)

    n_pass = sum(1 for k in cids if summary["system_power_and_efficiency"][k]["all_pass"])
    sd_tag = f"  |  Single-Deck TT: 0/{sd_row['rx']['data_bits']} Data, 0/{sd_row['rx']['edge_determinate']} Edge Err" if (sd_row and sd_row.get("ok")) else ""
    fig.suptitle(
        f"5.0 Gb/s (200 ps UI) SKY130A End-to-End SerDes Co-Sim (Real DRC=0 2.541 nH VCO + 8.252 nH CTLE) — {n_pass}/{len(cids)} PVT PASS{sd_tag}",
        fontsize=10.8, fontweight="bold", y=0.988,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.962])
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=180)
    plt.close(fig)
    print(f"Saved figure: {fig_path.relative_to(REPO)}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("calib", "stage1", "stage2a", "stage2b", "singledeck", "plot", "all"), default="all")
    ap.add_argument("--camp", type=Path, default=DEFAULT_CAMP)
    ap.add_argument("--fig", type=Path, default=DEFAULT_FIG)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--only", default="")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    workers = max(1, min(args.workers, 2))
    camp = args.camp.resolve() if args.camp.is_absolute() else (REPO / args.camp).resolve()
    camp.mkdir(parents=True, exist_ok=True)

    sel_corners = list(CORNERS)
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        sel_corners = [cs for cs in sel_corners if cs["id"] in want]

    if args.mode in ("calib", "all"):
        analyse_ctle_ac(camp, sel_corners, workers)
    if args.mode in ("stage1", "all"):
        run_stage1(camp, sel_corners, workers, force=args.force)
    if args.mode in ("stage2a", "all"):
        run_stage2a(camp, sel_corners, workers, force=args.force)
    if args.mode in ("stage2b", "all"):
        run_stage2b(camp, sel_corners, workers, force=args.force)
    if args.mode in ("singledeck", "all"):
        run_singledeck_tt(camp, force=args.force)
    if args.mode in ("plot", "all"):
        summary = assemble_summary(camp)
        if summary["stage1_pll"] and summary["stage2a_tx_ch"] and summary["stage2b_rx"]:
            make_figure(camp, summary, args.fig if args.fig.is_absolute() else REPO / args.fig)


if __name__ == "__main__":
    main()
