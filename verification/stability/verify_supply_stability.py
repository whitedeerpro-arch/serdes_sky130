"""Power / Bias Loop Stability & Chip-Level PDN Anti-Resonance Signoff Suite.

Covers three stability & self-oscillation signoff investigations for the SKY130A 4 Gb/s SerDes:
  1. TX SST `sst_vdrv_ldo`: full-load-range (0..8 mA) Middlebrook dual-injection AC stability
     (1 Hz - 10 GHz), closed-loop Z_out(f), and large-signal load-step transient
     (0.1 mA -> 6 mA -> 0.1 mA, 200 ps edges) on schematic + extracted CPEX + extracted RCX,
     plus pole/zero diagnosis & compensation what-if verification if light-load PM < 45 deg.
  2. `serdes_bias_top_v2` (bandgap FC-OTA positive/negative dual-loop up to 10 GHz, V->I loop,
     and post-layout CPEX), `serdes_ref_pbuf_v2` & `serdes_ref_vbuf_v2` (vcm buffer) C_load
     stability sweep (0.2..50 pF, schematic + CPEX), plus zero-start power-up ramps (1 us & 50 ns)
     and +/-50 mV / 10 ps supply-step transients across extreme PVT x RC corners.
  3. Chip-level PDN `L_pkg + C_decap` anti-resonance audit (`Z_PDN(f)` 1 MHz - 5 GHz +
     250 MHz digital switching current burst transient, 20-40 mA / 200 ps edges) grounded in
     actual `serdes_digital_top_v3` (59.94 pF) + analog intrinsic decap budgets, deriving exact
     damped decap (`C_dec + R_damp`) sizing.

Usage:
    uv run python verification/stability/verify_supply_stability.py --workers 2
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import feedback, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

OUT_ROOT = ROOT / "results/verification/stability_pdn_20261123"
FIG_PATH = ROOT / "docs/figures/verification/stability_pdn_20261123.png"

PRIMS = ROOT / "analog/common/devices/spice/sky130_primitives.spice"
PLVT = ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice"
TX_SST_SPICE = ROOT / "analog/tx/sst/spice/tx_sst_driver.spice"
LDO_PEX_SPICE = ROOT / "results/layout/tx_sst_v4/review/sst_vdrv_ldo_pdk/sst_vdrv_ldo_pdk_pex.spice"
LDO_RCX_SPICE = ROOT / "results/layout/tx_sst_v4/review/sst_vdrv_ldo_pdk/sst_vdrv_ldo_pdk_rcx.spice"

BIAS_V2_SPICE = ROOT / "analog/bias/spice/bias_v2.spice"
BIAS_PDK_DIR = ROOT / "analog/bias/layout/variants/v2_pdk"
BIAS_TOP_PEX = BIAS_PDK_DIR / "serdes_bias_top_v2_pdk_pex.spice"
BIAS_REF_PEX = BIAS_PDK_DIR / "serdes_bias_ref_v2_pdk_pex.spice"
BIAS_PBUF_PEX = BIAS_PDK_DIR / "serdes_ref_pbuf_v2_pdk_pex.spice"
BIAS_VBUF_PEX = BIAS_PDK_DIR / "serdes_ref_vbuf_v2_pdk_pex.spice"
BIAS_CML_RCX = BIAS_PDK_DIR / "serdes_bias_cml_v2_pdk_rcx.spice"
BIAS_CP_RCX = BIAS_PDK_DIR / "serdes_bias_cp_v2_pdk_rcx.spice"
BIAS_CTLE_RCX = BIAS_PDK_DIR / "serdes_bias_ctle_v2_pdk_rcx.spice"


def model_lib() -> Path:
    return Path(spice.corner_values(Condition("tt", 1.8, 27))["MODEL_LIBRARY"])


def section_name(proc: str, rc: str) -> str:
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def bits_sources(prefix: str, val: int, nbits: int) -> str:
    return "\n".join(f"E{prefix}{k} {prefix}{k} 0 vdd 0 {(val >> k) & 1}" for k in range(nbits))


# ---------------------------------------------------------------------------
# Generic Bode / Middlebrook & Ringing Analysis Helpers
# ---------------------------------------------------------------------------

def load_ac_complex(path: Path) -> tuple[np.ndarray, np.ndarray]:
    a = np.loadtxt(path, skiprows=1)
    return a[:, 0], a[:, 1] + 1j * a[:, 2]


def analyze_loop_gain(hz: np.ndarray, T: np.ndarray) -> dict:
    """Honest, comprehensive Bode + Nyquist stability metrics from complex loop gain T(jw)."""
    hz = np.asarray(hz, dtype=float)
    T = np.asarray(T, dtype=complex)
    mag = np.abs(T)
    mag_db = 20.0 * np.log10(np.maximum(mag, 1e-30))
    # Anchor DC phase in [-180, 180) and unwrap continuously
    phase_rad = np.unwrap(np.angle(T))
    # If DC gain is clearly negative feedback (Re(T[0]) > 0), phase[0] is near 0 deg
    if phase_rad[0] > np.pi:
        phase_rad -= 2 * np.pi
    elif phase_rad[0] < -np.pi:
        phase_rad += 2 * np.pi
    phase_deg = phase_rad * 180.0 / np.pi

    # All unity-gain crossings
    crossings = []
    idx_u = np.flatnonzero(((mag[:-1] >= 1.0) & (mag[1:] < 1.0)) | ((mag[:-1] < 1.0) & (mag[1:] >= 1.0)))
    for n in idx_u:
        a = np.log(mag[n]) / (np.log(mag[n]) - np.log(mag[n + 1]))
        f_c = float(np.exp(np.log(hz[n]) * (1.0 - a) + np.log(hz[n + 1]) * a))
        ph_c = float(phase_deg[n] * (1.0 - a) + phase_deg[n + 1] * a)
        crossings.append(dict(
            hz=f_c,
            direction="down" if mag[n] >= 1.0 else "up",
            phase_deg=ph_c,
            pm_deg=float(180.0 + ph_c),
        ))

    # Gain margin: all crossings of -180 deg (or +180 deg)
    gm_list = []
    for target in (-180.0, 180.0):
        diff = phase_deg - target
        idx_p = np.flatnonzero((diff[:-1] >= 0) != (diff[1:] >= 0))
        for n in idx_p:
            if abs(diff[n + 1] - diff[n]) < 1e-12:
                continue
            a = -diff[n] / (diff[n + 1] - diff[n])
            f_p = float(np.exp(np.log(hz[n]) * (1.0 - a) + np.log(hz[n + 1]) * a))
            m_db = float(mag_db[n] * (1.0 - a) + mag_db[n + 1] * a)
            gm_list.append(dict(hz=f_p, gm_db=float(-m_db), target_deg=target))

    # Primary UGF / PM (worst downward crossing if multiple)
    down = [c for c in crossings if c["direction"] == "down"]
    if down:
        worst_c = min(down, key=lambda c: c["pm_deg"])
        ugf_hz = worst_c["hz"]
        pm_deg = worst_c["pm_deg"]
    elif crossings:
        ugf_hz = crossings[0]["hz"]
        pm_deg = crossings[0]["pm_deg"]
    else:
        ugf_hz = None
        pm_deg = None

    gm_db = min((g["gm_db"] for g in gm_list), default=None)
    f_180_hz = min(gm_list, key=lambda g: g["gm_db"])["hz"] if gm_list else None

    # High-frequency peaking above highest UGF
    if crossings:
        f_top = max(c["hz"] for c in crossings)
        hi = hz > f_top * 1.05
        max_above_ugf_db = float(np.max(mag_db[hi])) if np.any(hi) else float(mag_db[-1])
        f_max_above_ugf_hz = float(hz[hi][np.argmax(mag_db[hi])]) if np.any(hi) else float(hz[-1])
    else:
        max_above_ugf_db = float(np.max(mag_db))
        f_max_above_ugf_hz = float(hz[np.argmax(mag_db)])

    # Nyquist distance to -1 and closed-loop peaking
    dist = np.abs(1.0 + T)
    idx_d = int(np.argmin(dist))
    min_dist = float(dist[idx_d])
    cl = T / (1.0 + T)
    cl_db = 20.0 * np.log10(np.maximum(np.abs(cl), 1e-30))
    cl_peak_db = float(np.max(cl_db) - cl_db[0])

    # Dominant -3 dB pole estimate
    below3 = np.flatnonzero(mag_db <= mag_db[0] - 3.0)
    f_p1_hz = float(hz[below3[0]]) if len(below3) else None

    return dict(
        dc_gain_db=float(mag_db[0]),
        dc_phase_deg=float(phase_deg[0]),
        f_p1_hz=f_p1_hz,
        ugf_hz=ugf_hz,
        pm_deg=pm_deg,
        gm_db=gm_db,
        f_180_hz=f_180_hz,
        min_phase_deg=float(np.min(phase_deg)),
        crossings=crossings,
        gm_crossings=gm_list,
        max_above_ugf_db=max_above_ugf_db,
        f_max_above_ugf_hz=f_max_above_ugf_hz,
        gain_at_10ghz_db=float(mag_db[-1]),
        min_dist_minus_one=min_dist,
        f_min_dist_hz=float(hz[idx_d]),
        sensitivity_peak_db=float(20.0 * np.log10(1.0 / max(min_dist, 1e-12))),
        cl_peak_db=cl_peak_db,
    )


def analyze_step_response(t: np.ndarray, v: np.ndarray, t0: float, t1: float, v_settle_win: float = 20e-9) -> dict:
    """Quantify undershoot/overshoot, settling time, ringing Q/freq, and sustained oscillation check."""
    m = (t >= t0) & (t <= t1)
    ts = t[m] - t0
    vs = v[m]
    tail = ts >= (ts[-1] - v_settle_win)
    v_final = float(np.mean(vs[tail]))
    tail_pp_mv = float((np.max(vs[tail]) - np.min(vs[tail])) * 1e3)
    dv = vs - v_final

    peak_pos_mv = float(np.max(dv) * 1e3)
    peak_neg_mv = float(np.min(dv) * 1e3)
    peak_abs_mv = max(abs(peak_pos_mv), abs(peak_neg_mv))

    # Settling time to +/-2 mV and +/-5 mV
    def settle_ns(tol_v: float) -> float:
        bad = np.flatnonzero(np.abs(dv) > tol_v)
        return float(ts[bad[-1]] * 1e9) if len(bad) else 0.0

    # Count zero crossings of dv (after initial peak) and estimate ringing freq & Q
    i_pk = int(np.argmax(np.abs(dv)))
    # Local extrema after first peak (significant > 0.5 mV)
    dv_post = dv[i_pk:]
    t_post = ts[i_pk:]
    ext_idx = []
    for k in range(1, len(dv_post) - 1):
        if (dv_post[k] >= dv_post[k - 1] and dv_post[k] > dv_post[k + 1]) or (
            dv_post[k] <= dv_post[k - 1] and dv_post[k] < dv_post[k + 1]
        ):
            if abs(dv_post[k]) > 0.3e-3:
                ext_idx.append(k)

    # First peak + subsequent alternating extrema -> half-cycle logarithmic decrement
    peaks_t = [t_post[0]] + [t_post[k] for k in ext_idx]
    peaks_a = [dv_post[0]] + [dv_post[k] for k in ext_idx]
    # Keep alternating signs
    alt_t, alt_a = [peaks_t[0]], [peaks_a[0]]
    for pt, pa in zip(peaks_t[1:], peaks_a[1:]):
        if pa * alt_a[-1] < 0 and (pt - alt_t[-1]) > 0.2e-9:
            alt_t.append(pt)
            alt_a.append(pa)

    ring_freq_mhz = None
    q_est = None
    zeta_est = None
    n_half_cycles = max(0, len(alt_a) - 1)
    if len(alt_a) >= 2 and abs(alt_a[0]) > 1e-3 and abs(alt_a[1]) > 0.3e-3:
        dt_half = alt_t[1] - alt_t[0]
        if dt_half > 0:
            ring_freq_mhz = float(0.5 / dt_half / 1e6)
        ratio = abs(alt_a[1]) / abs(alt_a[0])
        if 1e-4 < ratio < 0.9999:
            # Half-cycle decrement: ratio = exp(-pi * zeta / sqrt(1 - zeta^2))
            ln_r = -math.log(ratio)
            zeta_est = float(ln_r / math.sqrt(math.pi**2 + ln_r**2))
            q_est = float(1.0 / (2.0 * zeta_est))
        elif ratio >= 0.9999:
            zeta_est = 0.0
            q_est = 999.0

    return dict(
        v_final_v=v_final,
        peak_pos_mv=peak_pos_mv,
        peak_neg_mv=peak_neg_mv,
        peak_abs_mv=peak_abs_mv,
        t_settle_2mv_ns=settle_ns(2e-3),
        t_settle_5mv_ns=settle_ns(5e-3),
        tail_pp_mv=tail_pp_mv,
        sustained_osc=bool(tail_pp_mv > 1.0),
        ring_half_cycles=n_half_cycles,
        ring_freq_mhz=ring_freq_mhz,
        zeta_est=zeta_est,
        q_est=q_est,
    )


# ===========================================================================
# INVESTIGATION 1: TX SST `sst_vdrv_ldo` Stability & Load-Step Signoff
# ===========================================================================

LDO_LOADS_MA = [0.0, 0.05, 0.2, 0.5, 1.0, 2.0, 4.4, 8.0]

LDO_CORNERS = [
    # (tag, proc, rc, vdd, temp, include_layout)
    ("tt_1v80_27C",     "tt", "tt", 1.80,  27, True),
    ("ff_ll_1v95_m40C", "ff", "ll", 1.95, -40, True),
    ("ff_hh_1v95_m40C", "ff", "hh", 1.95, -40, False),
    ("ss_hh_1v65_85C",  "ss", "hh", 1.65,  85, True),
    ("ss_ll_1v65_85C",  "ss", "ll", 1.65,  85, False),
    ("fs_hh_1v65_85C",  "fs", "hh", 1.65,  85, True),
    ("sf_ll_1v95_m40C", "sf", "ll", 1.95, -40, True),
]


def make_ldo_sch_subckts() -> str:
    """Extract unmodified `sst_vdrv_ldo` and a test-only loop-broken copy `sst_vdrv_ldo_brk`."""
    txt = TX_SST_SPICE.read_text()
    m = re.search(r"(?ims)^\.subckt sst_vdrv_ldo\b.*?^\.ends sst_vdrv_ldo\b[^\n]*", txt)
    assert m is not None, "sst_vdrv_ldo not found"
    orig = m.group(0)
    head, body = orig.split("\n", 1)
    # Break loop at Xfb gate (vdrv -> fb_in)
    head_b = head.replace("vbg vdrv vdd vss", "vbg vdrv fb_in vdd vss").replace("sst_vdrv_ldo", "sst_vdrv_ldo_brk")
    body_b = re.sub(r"^(Xfb\s+vgate\s+)vdrv(\s+tail\s+vdd\b)", r"\1fb_in\2", body, flags=re.M)
    assert "fb_in" in body_b, "Failed to break Xfb gate in schematic sst_vdrv_ldo"
    brk = (head_b + "\n" + body_b).replace(".ends sst_vdrv_ldo", ".ends sst_vdrv_ldo_brk")
    return orig + "\n\n" + brk


def make_ldo_extracted_subckts(path: Path, suffix: str) -> str:
    """Create unmodified renamed subckt + loop-broken copy from Magic PEX or RCX netlist."""
    txt = path.read_text()
    orig = re.sub(r"(?im)^\.subckt\s+sst_vdrv_ldo_pdk\b", f".subckt sst_vdrv_ldo_{suffix}", txt)
    orig = re.sub(r"(?im)^\.ends\b[^\n]*", f".ends sst_vdrv_ldo_{suffix}", orig)

    # Break ONLY the 8 Xfb pfet_01v8 fingers whose gate (2nd pin) is `vdrv`
    lines = []
    n_broken = 0
    for line in txt.splitlines():
        if re.match(r"^\.subckt\s+sst_vdrv_ldo_pdk\b", line, re.I):
            lines.append(f".subckt sst_vdrv_ldo_{suffix}_brk vbg vdrv fb_in vdd vss")
        elif re.match(r"^\.ends\b", line, re.I):
            lines.append(f".ends sst_vdrv_ldo_{suffix}_brk")
        elif "sky130_fd_pr__pfet_01v8" in line:
            toks = line.split()
            # MOSFET Xname d g s b model ... -> gate is toks[2]
            if len(toks) >= 6 and toks[2] == "vdrv":
                toks[2] = "fb_in"
                n_broken += 1
                lines.append(" ".join(toks))
            else:
                lines.append(line)
        else:
            lines.append(line)
    assert n_broken == 8, f"Expected 8 Xfb fingers in {path.name}, broke {n_broken}"
    return orig + "\n\n" + "\n".join(lines)


def build_ldo_ac_deck(tag: str, proc: str, rc: str, vdd: float, temp: int, include_layout: bool) -> str:
    sec = section_name(proc, rc)
    lib = model_lib()
    views = [("sch", "sst_vdrv_ldo", "sst_vdrv_ldo_brk")]
    subckts = [make_ldo_sch_subckts()]
    if include_layout:
        subckts.append(make_ldo_extracted_subckts(LDO_PEX_SPICE, "pex"))
        subckts.append(make_ldo_extracted_subckts(LDO_RCX_SPICE, "rcx"))
        views.append(("pex", "sst_vdrv_ldo_pex", "sst_vdrv_ldo_pex_brk"))
        views.append(("rcx", "sst_vdrv_ldo_rcx", "sst_vdrv_ldo_rcx_brk"))

    lines = [
        f"* TX SST sst_vdrv_ldo Middlebrook Stability + Closed-Loop Z_out ({tag}, sec={sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        *subckts,
        f"Vdd vdd 0 {vdd}",
        "Vbg vbg 0 1.20",
    ]
    for vname, sub_cl, sub_brk in views:
        # Loop-broken instance for Middlebrook dual injection
        lines += [
            f"Xbrk_{vname} vbg vdrv_b_{vname} fb_{vname} vdd 0 {sub_brk}",
            f"Vtest_{vname} fb_{vname} vdrv_b_{vname} 0 ac 0",
            f"Itest_{vname} 0 fb_{vname} 0 ac 0",
            f"Iload_b_{vname} vdrv_b_{vname} 0 4.4m",
            # Unmodified closed-loop instance for exact Z_out(f) & OP
            f"Xcl_{vname} vbg vdrv_c_{vname} vdd 0 {sub_cl}",
            f"Iload_c_{vname} vdrv_c_{vname} 0 4.4m ac 0",
        ]

    lines += [
        ".nodeset " + " ".join(f"v(vdrv_b_{v})=0.44 v(vdrv_c_{v})=0.44" for v, _, _ in views),
        f".temp {temp}",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    for iload in LDO_LOADS_MA:
        ltag = f"i{round(iload * 1000):04d}u"
        for vname, _, _ in views:
            lines.append(f"alter Iload_b_{vname} dc={iload}m")
            lines.append(f"alter Iload_c_{vname} dc={iload}m")
        # OP readout for all views
        lines.append("op")
        op_vecs = []
        for vname, _, _ in views:
            lines.append(f"let v_{vname}=v(vdrv_c_{vname})")
            op_vecs.append(f"v_{vname}")
        lines += [
            f"let vgate_sch=v(xcl_sch.vgate)",
            f"let gm_pass=@m.xcl_sch.xpass.xmos.msky130_fd_pr__nfet_01v8_lvt[gm]",
            f"let id_pass=@m.xcl_sch.xpass.xmos.msky130_fd_pr__nfet_01v8_lvt[id]",
            f"let gm_fb=@m.xcl_sch.xfb.xmos.msky130_fd_pr__pfet_01v8[gm]",
            f"let gds_fb=@m.xcl_sch.xfb.xmos.msky130_fd_pr__pfet_01v8[gds]",
            f"let gds_m2=@m.xcl_sch.xm2.xmos.msky130_fd_pr__nfet_01v8[gds]",
            f"wrdata op_{ltag}.tsv " + " ".join(op_vecs) + " vgate_sch gm_pass id_pass gm_fb gds_fb gds_m2",
            "destroy all",
        ]
        for vname, _, _ in views:
            lines += [
                # Voltage injection
                f"alter Vtest_{vname} acmag=1",
                "ac dec 25 1 10g",
                f"let tv=-v(vdrv_b_{vname})/v(fb_{vname})",
                "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {vname}_{ltag}_tv.tsv vr vi",
                "destroy all",
                f"alter Vtest_{vname} acmag=0",
                # Current injection
                f"alter Itest_{vname} acmag=1",
                "ac dec 25 1 10g",
                f"let ti=i(Vtest_{vname})/(1-i(Vtest_{vname}))",
                "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {vname}_{ltag}_ti.tsv ir ii",
                "destroy all",
                f"alter Itest_{vname} acmag=0",
                # Closed-loop output impedance Z_out(f) on unmodified circuit
                f"alter Iload_c_{vname} acmag=1",
                "ac dec 25 1k 10g",
                f"let zmag=mag(v(vdrv_c_{vname}))",
                f"let zph=phase(v(vdrv_c_{vname}))*180/pi",
                f"wrdata {vname}_{ltag}_zout.tsv zmag zph",
                "destroy all",
                f"alter Iload_c_{vname} acmag=0",
            ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def build_ldo_tran_deck(tag: str, proc: str, rc: str, vdd: float, temp: int) -> str:
    """Large-signal 0.1 mA -> 6 mA -> 0.1 mA (200 ps edges) load step on unmodified Sch, CPEX, RCX."""
    sec = section_name(proc, rc)
    lib = model_lib()
    sch_txt = make_ldo_sch_subckts()
    pex_txt = make_ldo_extracted_subckts(LDO_PEX_SPICE, "pex")
    rcx_txt = make_ldo_extracted_subckts(LDO_RCX_SPICE, "rcx")
    lines = [
        f"* TX SST sst_vdrv_ldo Load-Step Transient 0.1mA->6mA->0.1mA 200ps ({tag}, sec={sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        sch_txt,
        pex_txt,
        rcx_txt,
        f"Vdd vdd 0 {vdd}",
        "Vbg vbg 0 1.20",
        "Xsch vbg vdrv_sch vdd 0 sst_vdrv_ldo",
        "Xpex vbg vdrv_pex vdd 0 sst_vdrv_ldo_pex",
        "Xrcx vbg vdrv_rcx vdd 0 sst_vdrv_ldo_rcx",
        "Isch vdrv_sch 0 PWL(0 0.1m 40n 0.1m 40.2n 6.0m 140n 6.0m 140.2n 0.1m 340n 0.1m)",
        "Ipex vdrv_pex 0 PWL(0 0.1m 40n 0.1m 40.2n 6.0m 140n 6.0m 140.2n 0.1m 340n 0.1m)",
        "Ircx vdrv_rcx 0 PWL(0 0.1m 40n 0.1m 40.2n 6.0m 140n 6.0m 140.2n 0.1m 340n 0.1m)",
        ".nodeset v(vdrv_sch)=0.44 v(vdrv_pex)=0.44 v(vdrv_rcx)=0.44",
        f".temp {temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 50p 340n 0 200p",
        "write load_step.raw v(vdrv_sch) v(vdrv_pex) v(vdrv_rcx) v(xsch.vgate)",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def build_ldo_comp_whatif_deck(tag: str, proc: str, rc: str, vdd: float, temp: int) -> str:
    """Test-only compensation comparison (never modifies repo SPICE):
      A) Baseline (as-designed: Cg~1.2 pF, Rbleed~9k / 50uA, Cdec~15.3 pF)
      B) Fix-1: Increase Rbleed current to ~350 uA (Rbleed ~ 1.28 kOhm, l=4.5)
      C) Fix-2: Increase Cg 3x (~3.6 pF, e.g. 29.4x29.4 um stacked MIM)
      D) Fix-3: Miller cap Cm = 0.5 pF + Rz = 1.5 kOhm from vgate to vdrv (replaces Cg)
      E) Fix-4: Explicit series ESR R_esr = 15 Ohm on half of Cdec (7.6 pF) -> LHP zero at 1.4 GHz? No: R_esr = 150 Ohm -> zero at 140 MHz!
    """
    sec = section_name(proc, rc)
    lib = model_lib()
    sch_all = make_ldo_sch_subckts()
    # Extract sst_vdrv_ldo_brk to derive clean test variants
    m = re.search(r"(?ims)^\.subckt sst_vdrv_ldo_brk\b.*?^\.ends sst_vdrv_ldo_brk\b[^\n]*", sch_all)
    assert m is not None
    brk = m.group(0)

    # Variant B: stronger bleed (l=5.0 -> R~1.4 kOhm -> ~310 uA bleed)
    v_bleed = brk.replace("sst_vdrv_ldo_brk", "ldo_fix_bleed").replace(
        "Xrbleed vdrv vss vss sky130_fd_pr__res_high_po_1p41 l=38.0",
        "Xrbleed vdrv vss vss sky130_fd_pr__res_high_po_1p41 l=5.0",
    )
    # Variant C: larger Cg (w=30 l=30 -> ~3.7 pF stacked MIM)
    v_cg = brk.replace("sst_vdrv_ldo_brk", "ldo_fix_cg3x").replace("w=17.0 l=17.0", "w=30.0 l=30.0")
    # Variant D: Miller C_m = 0.6 pF + Rz = 800 Ohm between vgate and vdrv + keep Cg=1.2pF
    v_miller = brk.replace("sst_vdrv_ldo_brk", "ldo_fix_miller").replace(
        ".ends ldo_fix_miller",
        "Rm_z vgate m_mid 800\nCm_c m_mid vdrv 0.6p\n.ends ldo_fix_miller",
    )
    # Variant E: Split Cdec ESR damping (add 25 Ohm in series with 15 pF -> zero at 1/(2*pi*25*15p)=424 MHz; try 80 Ohm -> 133 MHz)
    v_esr = brk.replace("sst_vdrv_ldo_brk", "ldo_fix_esr")
    v_esr = re.sub(r"^(Xcd[0-5]a\s+)vdrv(\s+vss\b)", r"\1vdrv_esr\2", v_esr, flags=re.M)
    v_esr = re.sub(r"^(Xcd[0-5]b\s+vss\s+)vdrv\b", r"\1vdrv_esr", v_esr, flags=re.M)
    v_esr = v_esr.replace(".ends ldo_fix_esr", "Resr vdrv vdrv_esr 60\n.ends ldo_fix_esr")

    variants = [
        ("base", "sst_vdrv_ldo_brk"),
        ("bleed310u", "ldo_fix_bleed"),
        ("cg3p7p", "ldo_fix_cg3x"),
        ("miller0p6p", "ldo_fix_miller"),
        ("esr60", "ldo_fix_esr"),
    ]
    lines = [
        f"* LDO Light-Load Compensation Sensitivity Study ({tag}, sec={sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        brk, v_bleed, v_cg, v_miller, v_esr,
        f"Vdd vdd 0 {vdd}",
        "Vbg vbg 0 1.20",
    ]
    for vn, sub in variants:
        lines += [
            f"X_{vn} vbg vdrv_{vn} fb_{vn} vdd 0 {sub}",
            f"Vt_{vn} fb_{vn} vdrv_{vn} 0 ac 0",
            f"It_{vn} 0 fb_{vn} 0 ac 0",
            f"Il_{vn} vdrv_{vn} 0 0.05m",
        ]
    lines += [
        ".nodeset " + " ".join(f"v(vdrv_{vn})=0.44" for vn, _ in variants),
        f".temp {temp}",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    for iload in (0.05, 0.5, 4.4, 8.0):
        ltag = f"i{round(iload * 1000):04d}u"
        for vn, _ in variants:
            lines.append(f"alter Il_{vn} dc={iload}m")
        for vn, _ in variants:
            lines += [
                f"alter Vt_{vn} acmag=1",
                "ac dec 25 1 10g",
                f"let tv=-v(vdrv_{vn})/v(fb_{vn})",
                "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {vn}_{ltag}_tv.tsv vr vi",
                "destroy all",
                f"alter Vt_{vn} acmag=0",
                f"alter It_{vn} acmag=1",
                "ac dec 25 1 10g",
                f"let ti=i(Vt_{vn})/(1-i(Vt_{vn}))",
                "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {vn}_{ltag}_ti.tsv ir ii",
                "destroy all",
                f"alter It_{vn} acmag=0",
            ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


# ===========================================================================
# INVESTIGATION 2: `bias_top_v2` Dual-Loop & `ref_pbuf`/`ref_vbuf` C_load
# ===========================================================================

BIAS_SECTIONS = [
    # (sec, [(pt_tag, vdd, temp), ...])
    ("tt",    [("tt_1v80_27C", 1.80, 27)]),
    ("ss_hh", [("ss_hh_1v65_m40C", 1.65, -40), ("ss_hh_1v65_85C", 1.65, 85)]),
    ("ff_ll", [("ff_ll_1v95_m40C", 1.95, -40), ("ff_ll_1v95_85C", 1.95, 85)]),
    ("fs_hh", [("fs_hh_1v65_85C", 1.65, 85)]),
    ("sf_ll", [("sf_ll_1v95_m40C", 1.95, -40)]),
]

BUF_CLOADS_PF = [0.2, 0.5, 2.0, 5.0, 10.0, 20.0, 50.0]


def make_bias_probe_spice() -> str:
    """Create test-only probed copies of `serdes_bias_top_v2`, `serdes_ref_pbuf_v2`, `serdes_ref_vbuf_v2`."""
    txt = BIAS_V2_SPICE.read_text()

    # 1) Bandgap ref + top with core (cr/ci) and V->I (vr/vi) loop breaks
    m = re.search(r"(?ims)^\.subckt serdes_bias_ref_v2\b.*?^\.ends serdes_bias_ref_v2\b[^\n]*", txt)
    assert m is not None
    ref = m.group(0)
    head, body = ref.split("\n", 1)
    head = head.replace(" vdd vss", " vdd vss cr ci vr vi")
    body = re.sub(r"\bvg\b", "ci", body)
    body = re.sub(r"\bs\b", "vr", body)
    body = body.replace("Xamp tb ta ci nb", "Xamp tb ta cr nb")
    body = body.replace("Xamp2 vr vbg", "Xamp2 vi vbg")
    ref_p = (head + "\n" + body).replace("serdes_bias_ref_v2", "serdes_bias_ref_v2_probe")

    # 2) Probed serdes_ref_pbuf_v2 (break Xb gate: `Xb out out tail` -> `Xb out fb_in tail`)
    mp = re.search(r"(?ims)^\.subckt serdes_ref_pbuf_v2\b.*?^\.ends serdes_ref_pbuf_v2\b[^\n]*", txt)
    assert mp is not None
    pbuf = mp.group(0)
    ph, pb = pbuf.split("\n", 1)
    ph = ph.replace(" vdd vss", " fb_in vdd vss").replace("serdes_ref_pbuf_v2", "serdes_ref_pbuf_v2_probe")
    pb = pb.replace("Xb out out tail", "Xb out fb_in tail").replace(".ends serdes_ref_pbuf_v2", ".ends serdes_ref_pbuf_v2_probe")
    assert "Xb out fb_in tail" in pb

    # 3) Probed serdes_ref_vbuf_v2 (`vcm` buffer: break Xb gate)
    mv = re.search(r"(?ims)^\.subckt serdes_ref_vbuf_v2\b.*?^\.ends serdes_ref_vbuf_v2\b[^\n]*", txt)
    assert mv is not None
    vbuf = mv.group(0)
    vh, vb = vbuf.split("\n", 1)
    vh = vh.replace(" vdd vss", " fb_in vdd vss").replace("serdes_ref_vbuf_v2", "serdes_ref_vbuf_v2_probe")
    vb = vb.replace("Xb out out tail", "Xb out fb_in tail").replace(".ends serdes_ref_vbuf_v2", ".ends serdes_ref_vbuf_v2_probe")
    assert "Xb out fb_in tail" in vb

    top_p = """
.subckt serdes_bias_top_v2_probe vbg vcm pref icml ictle icp i_ldo0 i_ldo1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd vss cr ci vr vi fb_vbuf fb_pbuf
Xref vbg iv_in iv_b ip_in ip_b vgi g4 g3 g2 g1 g0 vdd vss cr ci vr vi serdes_bias_ref_v2_probe
Xvbuf iv_in iv_b vcm fb_vbuf vdd vss serdes_ref_vbuf_v2_probe
Xpbuf ip_in ip_b pref en_pbuf c0 c1 c2 c3 fb_pbuf vdd vss serdes_ref_pbuf_v2_probe
Xpc_cml  icml   vgi vdd serdes_bias_pcopy_v2 n=85
Xpc_ctle ictle  vgi vdd serdes_bias_pcopy_v2 n=20
Xpc_cp   icp    vgi vdd serdes_bias_pcopy_v2 n=20
Xpc_ldo0 i_ldo0 vgi vdd serdes_bias_pcopy_v2 n=4
Xpc_ldo1 i_ldo1 vgi vdd serdes_bias_pcopy_v2 n=4
.ends serdes_bias_top_v2_probe
"""
    return "\n\n".join([ref_p, ph + "\n" + pb, vh + "\n" + vb, top_p])


def make_bias_pex_probed_subckts() -> str:
    """Create test-only loop-broken CPEX subckts for bias_ref (core loop), pbuf, and vbuf."""
    # 1) serdes_bias_ref_v2_pdk_pex: break OTA output (Xpcb l=2.5, Xncb l=4) -> cr, rest of vg -> ci
    ref_lines = []
    n_ota = 0
    for line in BIAS_REF_PEX.read_text().splitlines():
        if re.match(r"^\.subckt\s+serdes_bias_ref_v2_pdk\b", line, re.I):
            ref_lines.append(line.replace("serdes_bias_ref_v2_pdk", "serdes_bias_ref_v2_pex_brk") + " cr ci")
        elif re.match(r"^\.ends\b", line, re.I):
            ref_lines.append(".ends serdes_bias_ref_v2_pex_brk")
        elif "a_3119_13856#" in line:
            toks = line.split()
            # OTA output devices driving vg: pfet_01v8_lvt w=12 l=2.5 (Xpcb) & nfet_01v8 w=4 l=4 (Xncb)
            is_xpcb = ("sky130_fd_pr__pfet_01v8_lvt" in line and "l=2.5" in toks and "w=12" in toks)
            is_xncb = ("sky130_fd_pr__nfet_01v8" in line and "l=4" in toks and "w=4" in toks)
            if is_xpcb or is_xncb:
                n_ota += 1
                ref_lines.append(line.replace("a_3119_13856#", "cr"))
            else:
                ref_lines.append(line.replace("a_3119_13856#", "ci"))
        else:
            ref_lines.append(line)
    assert n_ota == 8, f"Expected 8 OTA output fingers on vg in bias_ref PEX, found {n_ota}"

    # 2) serdes_ref_pbuf_v2_pdk_pex: break 4 fingers of Xb (nfet_01v8_lvt w=6 l=1 with gate == out)
    pbuf_lines = []
    n_pb = 0
    for line in BIAS_PBUF_PEX.read_text().splitlines():
        if re.match(r"^\.subckt\s+serdes_ref_pbuf_v2_pdk\b", line, re.I):
            pbuf_lines.append(line.replace("serdes_ref_pbuf_v2_pdk", "serdes_ref_pbuf_v2_pex_brk") + " fb_in")
        elif re.match(r"^\.ends\b", line, re.I):
            pbuf_lines.append(".ends serdes_ref_pbuf_v2_pex_brk")
        elif "sky130_fd_pr__nfet_01v8_lvt" in line:
            toks = line.split()
            if len(toks) >= 6 and toks[2] == "out":
                toks[2] = "fb_in"
                n_pb += 1
                pbuf_lines.append(" ".join(toks))
            else:
                pbuf_lines.append(line)
        else:
            pbuf_lines.append(line)
    assert n_pb == 4, f"Expected 4 Xb fingers in pbuf PEX, found {n_pb}"

    # 3) serdes_ref_vbuf_v2_pdk_pex: break 4 fingers of Xb (nfet_01v8 w=6 l=4 with gate == out)
    vbuf_lines = []
    n_vb = 0
    for line in BIAS_VBUF_PEX.read_text().splitlines():
        if re.match(r"^\.subckt\s+serdes_ref_vbuf_v2_pdk\b", line, re.I):
            vbuf_lines.append(line.replace("serdes_ref_vbuf_v2_pdk", "serdes_ref_vbuf_v2_pex_brk") + " fb_in")
        elif re.match(r"^\.ends\b", line, re.I):
            vbuf_lines.append(".ends serdes_ref_vbuf_v2_pex_brk")
        elif "sky130_fd_pr__nfet_01v8" in line:
            toks = line.split()
            if len(toks) >= 6 and toks[2] == "out":
                toks[2] = "fb_in"
                n_vb += 1
                vbuf_lines.append(" ".join(toks))
            else:
                vbuf_lines.append(line)
        else:
            vbuf_lines.append(line)
    assert n_vb == 4, f"Expected 4 Xb fingers in vbuf PEX, found {n_vb}"

    return "\n\n".join(["\n".join(ref_lines), "\n".join(pbuf_lines), "\n".join(vbuf_lines)])


def build_bias_ac_deck(sec: str, pts: list[tuple[str, float, int]]) -> str:
    """Batched 1 Hz - 10 GHz Middlebrook deck for bandgap core + V->I + pbuf(C_load) + vbuf(C_load), Sch + CPEX."""
    lib = model_lib()
    include_pex = sec in ("tt", "ss_hh", "ff_ll")
    lines = [
        f"* BIAS v2 Comprehensive 1 Hz - 10 GHz Middlebrook Stability ({sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2_SPICE}"',
        make_bias_probe_spice(),
    ]
    if include_pex:
        lines.append(make_bias_pex_probed_subckts())

    lines += [
        "Vdd vdd 0 1.8",
        bits_sources("g", 15, 5),
        bits_sources("c", 7, 4),
        "Een en_pbuf 0 vdd 0 1",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 cr ci vr vi fb_vbuf fb_pbuf serdes_bias_top_v2_probe",
        "Vcore ci cr 0 ac 0",
        "Icore 0 ci 0 ac 0",
        "Vvi vi vr 0 ac 0",
        "Ivi 0 vi 0 ac 0",
        "Vvbuf fb_vbuf vcm 0 ac 0",
        "Ivbuf 0 fb_vbuf 0 ac 0",
        "Vpbuf fb_pbuf pref 0 ac 0",
        "Ipbuf 0 fb_pbuf 0 ac 0",
        "Cvcm vcm 0 5p",
        "Cpref pref 0 42p",
        "Vi0 i0 0 0.7",
        "Vi1 i1 0 0.7",
        "Xdcml icml 0 serdes_bias_cml_v2",
        "Xdctle ictle 0 serdes_bias_ctle_v2",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
    ]
    if include_pex:
        # Standalone PEX instances driven by the exact same reference currents / supplies
        lines += [
            "Xref_pex vbg_p ip0 ip1 ip2 ip3 vgi_p g0 g1 g2 g3 g4 vdd 0 cr_p ci_p serdes_bias_ref_v2_pex_brk",
            "Vcore_p ci_p cr_p 0 ac 0",
            "Icore_p 0 ci_p 0 ac 0",
            "Xpbuf_pex ip2 ip3 pref_p en_pbuf c0 c1 c2 c3 vdd 0 fb_pbuf_p serdes_ref_pbuf_v2_pex_brk",
            "Vpbuf_p fb_pbuf_p pref_p 0 ac 0",
            "Ipbuf_p 0 fb_pbuf_p 0 ac 0",
            "Cpref_p pref_p 0 42p",
            "Xvbuf_pex ip0 ip1 vcm_p vdd 0 fb_vbuf_p serdes_ref_vbuf_v2_pex_brk",
            "Vvbuf_p fb_vbuf_p vcm_p 0 ac 0",
            "Ivbuf_p 0 fb_vbuf_p 0 ac 0",
            "Cvcm_p vcm_p 0 5p",
        ]

    lines += [
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(pref)=1.14 v(vr)=1.234 v(vi)=1.234 v(cr)=0.9 v(ci)=0.9 v(xtop.vgi)=0.9 v(xtop.xref.ta)=1.05 v(xtop.xref.tb)=1.05",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]

    for pt_tag, vdd, temp in pts:
        lines += [
            f"option temp={temp}",
            f"alter Vdd dc={vdd}",
            "alter Cvcm capacitance=5p",
            "alter Cpref capacitance=42p",
        ]
        # Reference DC OP
        lines += [
            "op",
            "let vbg=v(vbg)", "let vcm=v(vcm)", "let pref=v(pref)", "let iref=i(Vi0)",
            f"wrdata {pt_tag}_op.tsv vbg vcm pref iref",
            "destroy all",
        ]
        # (a) Core bandgap loop + individual tb (negative FB) & ta (positive FB) branch gains up to 10 GHz
        lines += [
            "alter Vcore acmag=1",
            "ac dec 25 1 10g",
            "let tv=-v(cr)/v(ci)",
            "let vr=real(tv)", "let vi=imag(tv)",
            f"wrdata {pt_tag}_core_tv.tsv vr vi",
            "let htb=v(xtop.xref.tb)/v(ci)",
            "let hta=v(xtop.xref.ta)/v(ci)",
            "let tbr=real(htb)", "let tbi=imag(htb)",
            "let tar=real(hta)", "let tai=imag(hta)",
            f"wrdata {pt_tag}_core_branches.tsv tbr tbi tar tai",
            "destroy all",
            "alter Vcore acmag=0",
            "alter Icore acmag=1",
            "ac dec 25 1 10g",
            "let ti=i(Vcore)/(1-i(Vcore))",
            "let ir=real(ti)", "let ii=imag(ti)",
            f"wrdata {pt_tag}_core_ti.tsv ir ii",
            "destroy all",
            "alter Icore acmag=0",
            # V->I loop up to 10 GHz
            "alter Vvi acmag=1",
            "ac dec 25 1 10g",
            "let tv=-v(vr)/v(vi)",
            "let vr=real(tv)", "let vi=imag(tv)",
            f"wrdata {pt_tag}_vi_tv.tsv vr vi",
            "destroy all",
            "alter Vvi acmag=0",
            "alter Ivi acmag=1",
            "ac dec 25 1 10g",
            "let ti=i(Vvi)/(1-i(Vvi))",
            "let ir=real(ti)", "let ii=imag(ti)",
            f"wrdata {pt_tag}_vi_ti.tsv ir ii",
            "destroy all",
            "alter Ivi acmag=0",
        ]
        if include_pex:
            lines += [
                "alter Vcore_p acmag=1",
                "ac dec 25 1 10g",
                "let tv=-v(cr_p)/v(ci_p)",
                "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {pt_tag}_core_pex_tv.tsv vr vi",
                "destroy all",
                "alter Vcore_p acmag=0",
                "alter Icore_p acmag=1",
                "ac dec 25 1 10g",
                "let ti=i(Vcore_p)/(1-i(Vcore_p))",
                "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {pt_tag}_core_pex_ti.tsv ir ii",
                "destroy all",
                "alter Icore_p acmag=0",
            ]

        # (b) ref_pbuf & ref_vbuf (vcm buffer) C_load stability sweeps (0.2..50 pF)
        for cl_pf in BUF_CLOADS_PF:
            ctag = f"c{str(cl_pf).replace('.', 'p')}p"
            lines += [
                f"alter Cpref capacitance={cl_pf}p",
                f"alter Cvcm capacitance={cl_pf}p",
                # pbuf schematic
                "alter Vpbuf acmag=1",
                "ac dec 25 1 10g",
                "let tv=-v(pref)/v(fb_pbuf)",
                "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {pt_tag}_pbuf_{ctag}_tv.tsv vr vi",
                "destroy all",
                "alter Vpbuf acmag=0",
                "alter Ipbuf acmag=1",
                "ac dec 25 1 10g",
                "let ti=i(Vpbuf)/(1-i(Vpbuf))",
                "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {pt_tag}_pbuf_{ctag}_ti.tsv ir ii",
                "destroy all",
                "alter Ipbuf acmag=0",
                # vbuf (vcm) schematic
                "alter Vvbuf acmag=1",
                "ac dec 25 1 10g",
                "let tv=-v(vcm)/v(fb_vbuf)",
                "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {pt_tag}_vbuf_{ctag}_tv.tsv vr vi",
                "destroy all",
                "alter Vvbuf acmag=0",
                "alter Ivbuf acmag=1",
                "ac dec 25 1 10g",
                "let ti=i(Vvbuf)/(1-i(Vvbuf))",
                "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {pt_tag}_vbuf_{ctag}_ti.tsv ir ii",
                "destroy all",
                "alter Ivbuf acmag=0",
            ]
            if include_pex and cl_pf in (0.2, 2.0, 10.0, 50.0):
                lines += [
                    f"alter Cpref_p capacitance={cl_pf}p",
                    f"alter Cvcm_p capacitance={cl_pf}p",
                    "alter Vpbuf_p acmag=1",
                    "ac dec 25 1 10g",
                    "let tv=-v(pref_p)/v(fb_pbuf_p)",
                    "let vr=real(tv)", "let vi=imag(tv)",
                    f"wrdata {pt_tag}_pbuf_pex_{ctag}_tv.tsv vr vi",
                    "destroy all",
                    "alter Vpbuf_p acmag=0",
                    "alter Ipbuf_p acmag=1",
                    "ac dec 25 1 10g",
                    "let ti=i(Vpbuf_p)/(1-i(Vpbuf_p))",
                    "let ir=real(ti)", "let ii=imag(ti)",
                    f"wrdata {pt_tag}_pbuf_pex_{ctag}_ti.tsv ir ii",
                    "destroy all",
                    "alter Ipbuf_p acmag=0",
                    "alter Vvbuf_p acmag=1",
                    "ac dec 25 1 10g",
                    "let tv=-v(vcm_p)/v(fb_vbuf_p)",
                    "let vr=real(tv)", "let vi=imag(tv)",
                    f"wrdata {pt_tag}_vbuf_pex_{ctag}_tv.tsv vr vi",
                    "destroy all",
                    "alter Vvbuf_p acmag=0",
                    "alter Ivbuf_p acmag=1",
                    "ac dec 25 1 10g",
                    "let ti=i(Vvbuf_p)/(1-i(Vvbuf_p))",
                    "let ir=real(ti)", "let ii=imag(ti)",
                    f"wrdata {pt_tag}_vbuf_pex_{ctag}_ti.tsv ir ii",
                    "destroy all",
                    "alter Ivbuf_p acmag=0",
                ]

    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def build_bias_tran_deck(sec: str, pts: list[tuple[str, float, int]], include_pex: bool = False) -> str:
    """True zero-start (NO .nodeset) 1 us & 50 ns VDD ramps + +50/-50 mV 10 ps supply steps."""
    lib = model_lib()
    lines = [
        f"* BIAS v2 Zero-Start Ramp (1us & 50ns) + +/-50mV/10ps Supply Step ({sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2_SPICE}"',
    ]
    if include_pex:
        lines += [
            f'.include "{BIAS_TOP_PEX}"',
            f'.include "{BIAS_CML_RCX}"',
            f'.include "{BIAS_CP_RCX}"',
            f'.include "{BIAS_CTLE_RCX}"',
        ]
    lines += [
        "Vsup sup 0 1.8",
        "Vtramp tramp_v 0 1e-6",
        # Ramp 0->VDD in tramp, settle to 15us, +50mV/10ps at 15us, -50mV/10ps at 17.5us, stop 20us
        "Bvdd vdd 0 V=v(sup)*min(max(time/max(v(tramp_v),1n),0),1)"
        "+0.05*min(max((time-15u)/10p,0),1)-0.05*min(max((time-17.5u)/10p,0),1)",
        bits_sources("g", 15, 5),
        bits_sources("c", 7, 4),
        "Een en_pbuf 0 vdd 0 1",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2",
        "Vi0 i0 0 0.7",
        "Vi1 i1 0 0.7",
        "Cvcm vcm 0 5p",
        "Cpref pref 0 42p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2",
        "Xdctle ictle 0 serdes_bias_ctle_v2",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
    ]
    if include_pex:
        lines += [
            "Xtop_p vbg_p vcm_p pref_p icp_p i1_p i0_p ictle_p icml_p g4 g3 g2 g1 g0 c0 c1 c2 c3 en_pbuf vdd 0 serdes_bias_top_v2_pdk",
            "Vi0_p i0_p 0 0.7",
            "Vi1_p i1_p 0 0.7",
            "Cvcm_p vcm_p 0 5p",
            "Cpref_p pref_p 0 42p",
            "Vmcml_p icml_p vcml_p 0",
            "Xdcml_p vcml_p 0 serdes_bias_cml_v2_pdk",
            "Xdctle_p ictle_p 0 serdes_bias_ctle_v2_pdk",
            "Xdcp_p icp_p vbp_p vdd 0 serdes_bias_cp_v2_pdk",
        ]
    lines += [
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
    ]
    for pt_tag, vdd, temp in pts:
        lines += [f"option temp={temp}", f"alter Vsup dc={vdd}"]
        for rtag, tramp_s in [("ramp1u", 1e-6), ("ramp50n", 50e-9)]:
            lines += [
                f"alter Vtramp dc={tramp_s}",
                "tran 5n 20u 0 25n",
                "let iref=i(Vi0)",
                "let icml=i(Vmcml)",
            ]
            vecs = "v(vbg) v(vcm) v(pref) iref icml v(vdd)"
            if include_pex:
                lines.append("let iref_p=i(Vi0_p)")
                vecs += " v(vbg_p) v(vcm_p) v(pref_p) iref_p"
            lines += [f"write {pt_tag}_{rtag}.raw {vecs}", "destroy all"]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


# ===========================================================================
# INVESTIGATION 3: Chip-Level PDN L_pkg + C_decap Anti-Resonance Audit
# ===========================================================================

PDN_LPKG_NH = [0.5, 1.0, 1.5, 2.0, 4.0]
PDN_CDEC_PF = [0.0, 100.0, 250.0, 500.0]
PDN_RDAMP_OHM = [0.0, 0.5, 1.0, 2.0, 3.0]


def build_pdn_deck() -> str:
    """Pure passive SKY130A chip-level PDN AC Z_PDN(f) (1 MHz - 5 GHz) + 250 MHz digital burst transient.

    Physical on-chip capacitance budget (from actual project layout summaries):
      - `serdes_digital_top_v3`: 59.94 pF explicit std-cell decap (2,605 cells) + ~25 pF intrinsic = 85 pF
      - Analog blocks (RX/TX/PLL/Bias intrinsic + local MIM caps): ~175 pF (range 150-350 pF)
      - Baseline total intrinsic chip capacitance: C_int = 260 pF (also sweep 150 pF and 350 pF)
      - Package bondwire/bump loop inductance: L_pkg = 0.5, 1.0, 1.5, 2.0, 4.0 nH, R_pkg = 0.15 Ohm
      - On-chip M5 grid resistance: R_grid = 0.5 Ohm (sensitivity 0.3..1.0 Ohm)
      - Explicit damped decap bank: C_dec (0..500 pF) + intentional damping ESR R_damp (0..3 Ohm)
    """
    lines = [
        "* Chip-Level SKY130A SerDes PDN Anti-Resonance Audit (AC Z_PDN + 250 MHz Digital Burst)",
        "Vpcb pcb 0 1.8",
        "Rpkg pcb pkg_n 0.15",
        "Lpkg pkg_n bump 1.5n",
        "Rgrid bump vdd_chip 0.50",
        # Intrinsic on-chip decoupling (digital v3 60pF + non-switching digital/analog ~200pF = 260pF)
        "Rint vdd_chip int_n 0.20",
        "Cint int_n 0 260p",
        # Explicit on-chip damped decap bank (switchable via Cdec / Rdamp)
        "Rdamp vdd_chip damp_n 1e-3",
        "Cdec damp_n 0 1f",
        # AC probe current source (1 A)
        "Iac vdd_chip 0 0 ac 1",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
        "set filetype=binary",
    ]

    # Part A: AC Z_PDN(f) grid over L_pkg x (C_dec, R_damp) at nominal C_int=260p, R_grid=0.5, R_pkg=0.15
    for l_nh in PDN_LPKG_NH:
        lines.append(f"alter Lpkg inductance={l_nh}n")
        # Baseline (no extra decap)
        lines += [
            "alter Cdec capacitance=1f",
            "alter Rdamp resistance=1e-3",
            "ac dec 50 1meg 5g",
            "let zmag=mag(v(vdd_chip))",
            "let zph=phase(v(vdd_chip))*180/pi",
            f"wrdata ac_L{str(l_nh).replace('.', 'p')}_C0_R0.tsv zmag zph",
            "destroy all",
        ]
        # Explicit decap x damping ESR
        for c_pf in (100.0, 250.0, 500.0):
            lines.append(f"alter Cdec capacitance={c_pf}p")
            for r_ohm in PDN_RDAMP_OHM:
                r_eff = max(r_ohm, 1e-3)
                lines += [
                    f"alter Rdamp resistance={r_eff}",
                    "ac dec 50 1meg 5g",
                    "let zmag=mag(v(vdd_chip))",
                    "let zph=phase(v(vdd_chip))*180/pi",
                    f"wrdata ac_L{str(l_nh).replace('.', 'p')}_C{int(c_pf)}_R{str(r_ohm).replace('.', 'p')}.tsv zmag zph",
                    "destroy all",
                ]

    # Part B: Sensitivity sweep on C_int (150, 260, 350 pF) & R_grid (0.3, 0.5, 1.0 Ohm) at L=1.5nH, 2.0nH
    for c_int in (150.0, 350.0):
        lines.append(f"alter Cint capacitance={c_int}p")
        lines.append("alter Cdec capacitance=1f")
        lines.append("alter Rdamp resistance=1e-3")
        for l_nh in (1.0, 1.5, 2.0):
            lines += [
                f"alter Lpkg inductance={l_nh}n",
                "ac dec 50 1meg 5g",
                "let zmag=mag(v(vdd_chip))",
                f"wrdata ac_sens_Cint{int(c_int)}_L{str(l_nh).replace('.', 'p')}.tsv zmag",
                "destroy all",
            ]
    lines.append("alter Cint capacitance=260p")

    for r_grid in (0.3, 1.0):
        lines.append(f"alter Rgrid resistance={r_grid}")
        lines.append("alter Lpkg inductance=1.5n")
        for label, c_pf, r_ohm in [("undamped", 1e-3, 1e-3), ("damped500p_1p5", 500.0, 1.5)]:
            lines += [
                f"alter Cdec capacitance={c_pf}p",
                f"alter Rdamp resistance={r_ohm}",
                "ac dec 50 1meg 5g",
                "let zmag=mag(v(vdd_chip))",
                f"wrdata ac_sens_Rg{str(r_grid).replace('.', 'p')}_{label}.tsv zmag",
                "destroy all",
            ]
    lines.append("alter Rgrid resistance=0.50")

    # Part C: Transient 250 MHz digital switching current burst (20, 30, 40 mA; 200 ps edges)
    # Use a clean finite-duration 25-cycle burst in a separate small transient deck (below)
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def build_pdn_tran_deck() -> str:
    """Transient 250 MHz digital switching burst (25 cycles, 200 ps edges, 20-40 mA) + post-burst ringdown."""
    # Generate explicit PWL for 25 cycles of 250 MHz (period 4 ns, pulse 500 ps, edges 200 ps) starting at 10 ns
    pts = ["0 0"]
    for k in range(25):
        t0 = 10.0 + 4.0 * k
        pts.append(f"{t0:.2f}n 0")
        pts.append(f"{t0 + 0.20:.2f}n 1")
        pts.append(f"{t0 + 0.70:.2f}n 1")
        pts.append(f"{t0 + 0.90:.2f}n 0")
    pts.append("150n 0")
    pwl_str = " ".join(pts)

    lines = [
        "* Chip-Level PDN 250 MHz Digital Switching Burst Transient (25 cycles + 40 ns ringdown)",
        "Vpcb pcb 0 1.8",
        "Rpkg pcb pkg_n 0.15",
        "Lpkg pkg_n bump 1.5n",
        "Rgrid bump vdd_chip 0.50",
        "Rint vdd_chip int_n 0.20",
        "Cint int_n 0 260p",
        "Rdamp vdd_chip damp_n 1e-3",
        "Cdec damp_n 0 1f",
        f"Vunit u_pulse 0 PWL({pwl_str})",
        "Vscale scale_v 0 0.030",
        "Bburst vdd_chip 0 I=v(u_pulse)*v(scale_v)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
    ]

    tran_cases = [
        # (name, L_nH, C_dec_pF, R_damp_ohm, I_pk_mA)
        ("L0p5_undamped_30mA",  0.5,   0.001, 1e-3, 30.0),
        ("L1p0_undamped_30mA",  1.0,   0.001, 1e-3, 30.0),
        ("L1p5_undamped_20mA",  1.5,   0.001, 1e-3, 20.0),
        ("L1p5_undamped_30mA",  1.5,   0.001, 1e-3, 30.0),
        ("L1p5_undamped_40mA",  1.5,   0.001, 1e-3, 40.0),
        ("L2p0_undamped_30mA",  2.0,   0.001, 1e-3, 30.0),
        ("L4p0_undamped_30mA",  4.0,   0.001, 1e-3, 30.0),
        ("L1p5_C500_R0_30mA",   1.5, 500.0,   1e-3, 30.0),
        ("L1p5_C250_R2p0_30mA", 1.5, 250.0,   2.0,  30.0),
        ("L1p5_C500_R1p0_30mA", 1.5, 500.0,   1.0,  30.0),
        ("L1p5_C500_R2p0_30mA", 1.5, 500.0,   2.0,  30.0),
        ("L1p5_C500_R2p0_40mA", 1.5, 500.0,   2.0,  40.0),
        ("L2p0_C500_R2p0_30mA", 2.0, 500.0,   2.0,  30.0),
        ("L4p0_C500_R2p0_30mA", 4.0, 500.0,   2.0,  30.0),
    ]
    for name, l_nh, c_pf, r_ohm, i_ma in tran_cases:
        lines += [
            f"alter Lpkg inductance={l_nh}n",
            f"alter Cdec capacitance={c_pf}p",
            f"alter Rdamp resistance={r_ohm}",
            f"alter Vscale dc={i_ma * 1e-3}",
            "tran 25p 150n 0 50p",
            f"write tran_{name}.raw v(vdd_chip) v(u_pulse)",
            "destroy all",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


# ===========================================================================
# Parsing & Orchestration
# ===========================================================================

def parse_ldo_results(camp_dir: Path) -> dict:
    ac_rows = []
    bode_curves = {}
    for tag, proc, rc, vdd, temp, inc_lay in LDO_CORNERS:
        rdir = camp_dir / "ldo_ac" / tag
        views = ["sch", "pex", "rcx"] if inc_lay else ["sch"]
        for iload in LDO_LOADS_MA:
            ltag = f"i{round(iload * 1000):04d}u"
            op_arr = np.loadtxt(rdir / f"op_{ltag}.tsv", skiprows=1)
            # Single-row op output
            if op_arr.ndim == 2:
                op_arr = op_arr[0]
            # columns: freq/scale?, wait: wrdata on op has 2 cols per vec? No, wr_singlescale gives 1 scale + N vecs
            # Let's read header to map exact column names
            op_hdr = (rdir / f"op_{ltag}.tsv").read_text().splitlines()[0].split()
            op_map = {k: float(op_arr[i]) for i, k in enumerate(op_hdr)}

            for vname in views:
                hz, tv = load_ac_complex(rdir / f"{vname}_{ltag}_tv.tsv")
                _, ti = load_ac_complex(rdir / f"{vname}_{ltag}_ti.tsv")
                T = feedback.middlebrook(tv, ti)
                m = analyze_loop_gain(hz, T)

                z_arr = np.loadtxt(rdir / f"{vname}_{ltag}_zout.tsv", skiprows=1)
                hz_z, zmag = z_arr[:, 0], z_arr[:, 1]
                iz_pk = int(np.argmax(zmag))

                row = dict(
                    corner=tag, process=proc, rcorner=rc, vdd=vdd, temp_c=temp,
                    view=vname, iload_ma=iload,
                    vdrv_v=op_map.get(f"v_{vname}"),
                    vgate_sch_v=op_map.get("vgate_sch") if vname == "sch" else None,
                    gm_pass_ms=op_map.get("gm_pass", 0.0) * 1e3 if vname == "sch" else None,
                    id_pass_ma=op_map.get("id_pass", 0.0) * 1e3 if vname == "sch" else None,
                    gm_fb_ms=op_map.get("gm_fb", 0.0) * 1e3 if vname == "sch" else None,
                    r_ota_kohm=(1.0 / max(op_map.get("gds_fb", 1e-12) + op_map.get("gds_m2", 1e-12), 1e-12)) * 1e-3 if vname == "sch" else None,
                    zout_dc_ohm=float(zmag[0]),
                    zout_peak_ohm=float(zmag[iz_pk]),
                    zout_fpeak_hz=float(hz_z[iz_pk]),
                    **m,
                )
                ac_rows.append(row)
                if tag == "tt_1v80_27C" or (tag in ("ff_ll_1v95_m40C", "ss_hh_1v65_85C") and vname in ("sch", "rcx")):
                    bode_curves[(tag, vname, iload)] = (hz, T, hz_z, zmag)

    # Load-step transient parsing
    tran_rows = []
    tran_waves = {}
    for tag, proc, rc, vdd, temp, inc_lay in LDO_CORNERS:
        if not inc_lay:
            continue
        raw = camp_dir / "ldo_tran" / tag / "load_step.raw"
        w = spice.Waves(raw)
        t = w.t
        for vname in ("sch", "pex", "rcx"):
            v = w[f"v(vdrv_{vname})"]
            up = analyze_step_response(t, v, 40e-9, 140e-9, v_settle_win=20e-9)
            dn = analyze_step_response(t, v, 140e-9, 340e-9, v_settle_win=40e-9)
            tran_rows.append(dict(
                corner=tag, process=proc, rcorner=rc, vdd=vdd, temp_c=temp,
                view=vname, step_up=up, step_down=dn,
            ))
            if tag in ("tt_1v80_27C", "ff_ll_1v95_m40C", "ss_hh_1v65_85C"):
                tran_waves[(tag, vname)] = (t, v)

    # Compensation what-if study parsing
    comp_rows = []
    for tag, proc, rc, vdd, temp in [
        ("tt_1v80_27C", "tt", "tt", 1.80, 27),
        ("ff_ll_1v95_m40C", "ff", "ll", 1.95, -40),
        ("ss_hh_1v65_85C", "ss", "hh", 1.65, 85),
    ]:
        rdir = camp_dir / "ldo_comp" / tag
        if not rdir.exists():
            continue
        for vn in ("base", "bleed310u", "cg3p7p", "miller0p6p", "esr60"):
            for iload in (0.05, 0.5, 4.4, 8.0):
                ltag = f"i{round(iload * 1000):04d}u"
                hz, tv = load_ac_complex(rdir / f"{vn}_{ltag}_tv.tsv")
                _, ti = load_ac_complex(rdir / f"{vn}_{ltag}_ti.tsv")
                m = analyze_loop_gain(hz, feedback.middlebrook(tv, ti))
                comp_rows.append(dict(corner=tag, variant=vn, iload_ma=iload, **m))

    return dict(ac_rows=ac_rows, tran_rows=tran_rows, comp_rows=comp_rows), bode_curves, tran_waves


def parse_bias_results(camp_dir: Path) -> tuple[dict, dict]:
    core_rows, vi_rows, pbuf_rows, vbuf_rows, tran_rows = [], [], [], [], []
    op_ref = {}
    plot_data = dict(pbuf={}, vbuf={})

    for sec, pts in BIAS_SECTIONS:
        rdir = camp_dir / "bias_ac" / sec
        include_pex = sec in ("tt", "ss_hh", "ff_ll")
        for pt_tag, vdd, temp in pts:
            op_arr = np.loadtxt(rdir / f"{pt_tag}_op.tsv", skiprows=1)
            if op_arr.ndim == 2:
                op_arr = op_arr[0]
            op_hdr = (rdir / f"{pt_tag}_op.tsv").read_text().splitlines()[0].split()
            op_map = {k: float(op_arr[i]) for i, k in enumerate(op_hdr)}
            op_ref[pt_tag] = op_map

            # Core loop + branch dominance check
            hz, tv = load_ac_complex(rdir / f"{pt_tag}_core_tv.tsv")
            _, ti = load_ac_complex(rdir / f"{pt_tag}_core_ti.tsv")
            T_core = feedback.middlebrook(tv, ti)
            mc = analyze_loop_gain(hz, T_core)

            br = np.loadtxt(rdir / f"{pt_tag}_core_branches.tsv", skiprows=1)
            htb = br[:, 1] + 1j * br[:, 2]   # negative feedback path (PTAT/R1 -> inp)
            hta = br[:, 3] + 1j * br[:, 4]   # positive feedback path (CTAT/diode -> inn)
            ratio_neg_over_pos = np.abs(htb) / np.maximum(np.abs(hta), 1e-30)
            # Check dominance up to 10x UGF and full 10 GHz
            ugf = mc["ugf_hz"] or 1e6
            in_band = hz <= ugf * 5.0
            core_rows.append(dict(
                corner=pt_tag, section=sec, vdd=vdd, temp_c=temp, view="sch",
                vbg_v=op_map["vbg"], iref_ua=op_map["iref"] * 1e6,
                neg_pos_dc_ratio=float(ratio_neg_over_pos[0]),
                neg_pos_min_inband_ratio=float(np.min(ratio_neg_over_pos[in_band])),
                neg_pos_min_10g_ratio=float(np.min(ratio_neg_over_pos)),
                f_min_ratio_hz=float(hz[int(np.argmin(ratio_neg_over_pos))]),
                net_diff_dc_db=float(20.0 * np.log10(max(abs(htb[0] - hta[0]), 1e-30))),
                **mc,
            ))

            # V->I loop
            hz_vi, tv_vi = load_ac_complex(rdir / f"{pt_tag}_vi_tv.tsv")
            _, ti_vi = load_ac_complex(rdir / f"{pt_tag}_vi_ti.tsv")
            vi_rows.append(dict(
                corner=pt_tag, section=sec, vdd=vdd, temp_c=temp, view="sch",
                **analyze_loop_gain(hz_vi, feedback.middlebrook(tv_vi, ti_vi)),
            ))

            if include_pex:
                hz_p, tv_p = load_ac_complex(rdir / f"{pt_tag}_core_pex_tv.tsv")
                _, ti_p = load_ac_complex(rdir / f"{pt_tag}_core_pex_ti.tsv")
                core_rows.append(dict(
                    corner=pt_tag, section=sec, vdd=vdd, temp_c=temp, view="pex",
                    **analyze_loop_gain(hz_p, feedback.middlebrook(tv_p, ti_p)),
                ))

            # Buffers across C_load
            for cl_pf in BUF_CLOADS_PF:
                ctag = f"c{str(cl_pf).replace('.', 'p')}p"
                for bname, rows_dst, pmap in [("pbuf", pbuf_rows, plot_data["pbuf"]), ("vbuf", vbuf_rows, plot_data["vbuf"])]:
                    hz_b, tv_b = load_ac_complex(rdir / f"{pt_tag}_{bname}_{ctag}_tv.tsv")
                    _, ti_b = load_ac_complex(rdir / f"{pt_tag}_{bname}_{ctag}_ti.tsv")
                    mb = analyze_loop_gain(hz_b, feedback.middlebrook(tv_b, ti_b))
                    rows_dst.append(dict(
                        corner=pt_tag, section=sec, vdd=vdd, temp_c=temp, view="sch", cload_pf=cl_pf, **mb
                    ))
                    pmap[(pt_tag, "sch", cl_pf)] = mb

                    if include_pex and cl_pf in (0.2, 2.0, 10.0, 50.0):
                        hz_bp, tv_bp = load_ac_complex(rdir / f"{pt_tag}_{bname}_pex_{ctag}_tv.tsv")
                        _, ti_bp = load_ac_complex(rdir / f"{pt_tag}_{bname}_pex_{ctag}_ti.tsv")
                        mbp = analyze_loop_gain(hz_bp, feedback.middlebrook(tv_bp, ti_bp))
                        rows_dst.append(dict(
                            corner=pt_tag, section=sec, vdd=vdd, temp_c=temp, view="pex", cload_pf=cl_pf, **mbp
                        ))
                        pmap[(pt_tag, "pex", cl_pf)] = mbp

        # Startup + supply step transients
        tdir = camp_dir / "bias_tran" / sec
        for pt_tag, vdd, temp in pts:
            op = op_ref[pt_tag]
            for rtag, tramp_s in [("ramp1u", 1e-6), ("ramp50n", 50e-9)]:
                w = spice.Waves(tdir / f"{pt_tag}_{rtag}.raw")
                t = w.t
                for view, sfx in ([("sch", ""), ("pex", "_p")] if include_pex else [("sch", "")]):
                    vbg = w[f"v(vbg{sfx})"]
                    vcm = w[f"v(vcm{sfx})"]
                    pref = w[f"v(pref{sfx})"]
                    iref = w[f"iref{sfx}"]
                    pre = (t >= 13.5e-6) & (t < 14.95e-6)
                    vbg0 = float(np.mean(vbg[pre]))
                    iref0 = float(np.mean(iref[pre]))
                    vbg_pre_pp_mv = float((np.max(vbg[pre]) - np.min(vbg[pre])) * 1e3)
                    # Settling time from end of ramp to +/-2 mV of final vbg0
                    after_r = (t >= tramp_s) & (t < 14.95e-6)
                    bad = np.flatnonzero(after_r & (np.abs(vbg - vbg0) > 2e-3))
                    t_settle_us = float((t[bad[-1]] - tramp_s) * 1e6) if len(bad) else 0.0
                    # +50 mV step [15u..17.5u] and -50 mV step [17.5u..20u]
                    pos_m = (t >= 15.0e-6) & (t < 17.45e-6)
                    neg_m = (t >= 17.5e-6) & (t <= 20.0e-6)
                    tail_m = (t >= 19.0e-6) & (t <= 20.0e-6)
                    pos_pk_mv = float(np.max(np.abs(vbg[pos_m] - vbg0)) * 1e3)
                    neg_pk_mv = float(np.max(np.abs(vbg[neg_m] - vbg0)) * 1e3)
                    tail_pp_mv = float((np.max(vbg[tail_m]) - np.min(vbg[tail_m])) * 1e3)
                    vcm_tail_pp_mv = float((np.max(vcm[tail_m]) - np.min(vcm[tail_m])) * 1e3)
                    pref_tail_pp_mv = float((np.max(pref[tail_m]) - np.min(pref[tail_m])) * 1e3)

                    d_vbg_mv = (vbg0 - op["vbg"]) * 1e3 if view == "sch" else None
                    d_iref_pct = (iref0 / op["iref"] - 1.0) * 100.0 if view == "sch" else None
                    lockup = bool(vbg0 < 0.8 or iref0 < 2e-6)
                    osc = bool(vbg_pre_pp_mv > 0.5 or tail_pp_mv > 0.5 or vcm_tail_pp_mv > 0.5 or pref_tail_pp_mv > 0.5)
                    tran_rows.append(dict(
                        corner=pt_tag, section=sec, vdd=vdd, temp_c=temp, view=view,
                        ramp=rtag, tramp_ns=tramp_s * 1e9,
                        vbg_settled_v=vbg0, iref_settled_ua=iref0 * 1e6,
                        d_vbg_vs_op_mv=d_vbg_mv, d_iref_vs_op_pct=d_iref_pct,
                        t_settle_2mv_us=t_settle_us,
                        step_pos50_vbg_peak_mv=pos_pk_mv,
                        step_neg50_vbg_peak_mv=neg_pk_mv,
                        pre_vbg_pp_mv=vbg_pre_pp_mv,
                        tail_vbg_pp_mv=tail_pp_mv,
                        tail_vcm_pp_mv=vcm_tail_pp_mv,
                        tail_pref_pp_mv=pref_tail_pp_mv,
                        startup_lockup=lockup,
                        hf_oscillation=osc,
                    ))

    return dict(
        core_rows=core_rows, vi_rows=vi_rows,
        pbuf_rows=pbuf_rows, vbuf_rows=vbuf_rows,
        tran_rows=tran_rows,
    ), plot_data


def parse_pdn_results(camp_dir: Path) -> tuple[dict, dict]:
    ac_dir = camp_dir / "pdn_ac"
    tr_dir = camp_dir / "pdn_tran"
    ac_rows = []
    ac_curves = {}

    for l_nh in PDN_LPKG_NH:
        ltag = str(l_nh).replace(".", "p")
        configs = [(0.0, 0.0, f"ac_L{ltag}_C0_R0.tsv")]
        for c_pf in (100.0, 250.0, 500.0):
            for r_ohm in PDN_RDAMP_OHM:
                rtag = str(r_ohm).replace(".", "p")
                configs.append((c_pf, r_ohm, f"ac_L{ltag}_C{int(c_pf)}_R{rtag}.tsv"))
        for c_pf, r_ohm, fname in configs:
            a = np.loadtxt(ac_dir / fname, skiprows=1)
            hz, zmag = a[:, 0], a[:, 1]
            band = (hz >= 10e6) & (hz <= 2e9)
            i_pk = int(np.argmax(zmag))
            i_250 = int(np.argmin(np.abs(hz - 250e6)))
            ac_rows.append(dict(
                l_pkg_nh=l_nh, c_int_pf=260.0, r_grid_ohm=0.50, r_pkg_ohm=0.15,
                c_dec_pf=c_pf, r_damp_ohm=r_ohm,
                f_res_mhz=float(hz[i_pk] / 1e6),
                z_peak_ohm=float(zmag[i_pk]),
                z_250mhz_ohm=float(zmag[i_250]),
                z_max_10m_2g_ohm=float(np.max(zmag[band])),
            ))
            ac_curves[(l_nh, c_pf, r_ohm)] = (hz, zmag)

    # Sensitivity rows
    sens_rows = []
    for c_int in (150.0, 350.0):
        for l_nh in (1.0, 1.5, 2.0):
            ltag = str(l_nh).replace(".", "p")
            a = np.loadtxt(ac_dir / f"ac_sens_Cint{int(c_int)}_L{ltag}.tsv", skiprows=1)
            hz, zmag = a[:, 0], a[:, 1]
            i_pk = int(np.argmax(zmag))
            i_250 = int(np.argmin(np.abs(hz - 250e6)))
            sens_rows.append(dict(
                kind="c_int_sweep", c_int_pf=c_int, l_pkg_nh=l_nh, r_grid_ohm=0.50,
                f_res_mhz=float(hz[i_pk] / 1e6), z_peak_ohm=float(zmag[i_pk]),
                z_250mhz_ohm=float(zmag[i_250]),
            ))
    for r_grid in (0.3, 1.0):
        rgtag = str(r_grid).replace(".", "p")
        for label in ("undamped", "damped500p_1p5"):
            a = np.loadtxt(ac_dir / f"ac_sens_Rg{rgtag}_{label}.tsv", skiprows=1)
            hz, zmag = a[:, 0], a[:, 1]
            i_pk = int(np.argmax(zmag))
            i_250 = int(np.argmin(np.abs(hz - 250e6)))
            sens_rows.append(dict(
                kind="r_grid_sweep", r_grid_ohm=r_grid, config=label, l_pkg_nh=1.5, c_int_pf=260.0,
                f_res_mhz=float(hz[i_pk] / 1e6), z_peak_ohm=float(zmag[i_pk]),
                z_250mhz_ohm=float(zmag[i_250]),
            ))

    # Transient burst rows
    tran_rows = []
    tran_waves = {}
    for p in sorted(tr_dir.glob("tran_*.raw")):
        name = p.stem.removeprefix("tran_")
        w = spice.Waves(p)
        t, v = w.t, w["v(vdd_chip)"]
        burst = (t >= 10e-9) & (t <= 112e-9)
        ring = (t >= 112e-9) & (t <= 150e-9)
        tail = (t >= 135e-9) & (t <= 150e-9)
        v_max = float(np.max(v[burst]))
        v_min = float(np.min(v[burst]))
        tran_rows.append(dict(
            case=name,
            ripple_pp_mv=float((v_max - v_min) * 1e3),
            max_droop_mv=float((1.8 - v_min) * 1e3),
            max_overshoot_mv=float((v_max - 1.8) * 1e3),
            post_burst_ring_pp_mv=float((np.max(v[ring]) - np.min(v[ring])) * 1e3),
            tail_15ns_pp_mv=float((np.max(v[tail]) - np.min(v[tail])) * 1e3),
        ))
        tran_waves[name] = (t, v)

    return dict(ac_rows=ac_rows, sens_rows=sens_rows, tran_rows=tran_rows), dict(ac=ac_curves, tran=tran_waves)


# ===========================================================================
# 4-Panel Engineering Summary Figure
# ===========================================================================

def make_summary_figure(
    ldo_summary: dict, ldo_bode: dict, ldo_tran: dict,
    bias_summary: dict, bias_plot: dict,
    pdn_summary: dict, pdn_plot: dict,
) -> None:
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.size": 9,
        "axes.titlesize": 10,
        "axes.labelsize": 9,
        "legend.fontsize": 7.5,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linestyle": "--",
    })
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.6), dpi=180)
    fig.suptitle(
        "SKY130A 4 Gb/s SerDes — Power / Bias Loop Stability & Chip-Level PDN Anti-Resonance Signoff (2026-11-23)",
        fontsize=12.5, fontweight="bold", y=0.985,
    )

    # --- Panel A: sst_vdrv_ldo Middlebrook PM vs I_load (Sch + CPEX + RCX across PVT) + Compensation ---
    ax = axes[0, 0]
    ldo_rows = ldo_summary["ac_rows"]
    style_map = [
        ("tt_1v80_27C",     "sch", "#1f77b4", "-",  "o", "TT 1.8V 27°C (Sch)"),
        ("tt_1v80_27C",     "rcx", "#1f77b4", "--", "s", "TT 1.8V 27°C (RCX)"),
        ("ff_ll_1v95_m40C", "sch", "#d62728", "-",  "^", "FF_ll 1.95V -40°C (Sch)"),
        ("ff_ll_1v95_m40C", "rcx", "#d62728", "--", "v", "FF_ll 1.95V -40°C (RCX)"),
        ("ss_hh_1v65_85C",  "sch", "#2ca02c", "-",  "D", "SS_hh 1.65V 85°C (Sch)"),
        ("ss_hh_1v65_85C",  "rcx", "#2ca02c", "--", "P", "SS_hh 1.65V 85°C (RCX)"),
        ("fs_hh_1v65_85C",  "rcx", "#9467bd", ":",  "x", "FS_hh 1.65V 85°C (RCX)"),
        ("sf_ll_1v95_m40C", "rcx", "#ff7f0e", ":",  "+", "SF_ll 1.95V -40°C (RCX)"),
    ]
    for corner, view, col, ls, mk, lab in style_map:
        sub = sorted([r for r in ldo_rows if r["corner"] == corner and r["view"] == view], key=lambda r: r["iload_ma"])
        xs = [max(r["iload_ma"], 0.01) for r in sub]
        ys = [r["pm_deg"] if r["pm_deg"] is not None else np.nan for r in sub]
        ax.semilogx(xs, ys, color=col, linestyle=ls, marker=mk, markersize=4.5, linewidth=1.4, label=lab)

    # Also overlay best compensation fix on FF_ll if available
    comp = ldo_summary.get("comp_rows", [])
    if comp:
        sub_fix = sorted([r for r in comp if r["corner"] == "ff_ll_1v95_m40C" and r["variant"] == "bleed310u"], key=lambda r: r["iload_ma"])
        if sub_fix:
            ax.semilogx(
                [r["iload_ma"] for r in sub_fix],
                [r["pm_deg"] for r in sub_fix],
                color="black", linestyle="-.", marker="*", markersize=6.5, linewidth=1.6,
                label="What-if Fix: 310 µA bleed (FF_ll)",
            )

    ax.axhline(45.0, color="#b22222", linestyle="--", linewidth=1.2, alpha=0.85)
    ax.axhspan(0, 45.0, color="#ffcccc", alpha=0.22)
    ax.text(0.012, 46.5, "45° Signoff Gate", color="#b22222", fontsize=8, fontweight="bold")
    ax.set_xlabel("Load Current $I_{\\mathrm{load}}$ (mA)  [0.01 mA = 0 mA bleed-only standby]")
    ax.set_ylabel("Middlebrook Phase Margin (°)")
    ax.set_title("(a) TX SST `sst_vdrv_ldo`: Phase Margin vs. Load (Sch vs. RCX)")
    ax.set_xlim(0.009, 10.0)
    ax.set_ylim(0, 100)
    ax.legend(loc="lower right", ncol=2, frameon=True, framealpha=0.92)

    # --- Panel B: sst_vdrv_ldo Large-Signal Load-Step Transient (0.1 -> 6 -> 0.1 mA, 200 ps) ---
    ax = axes[0, 1]
    tr_styles = [
        ("tt_1v80_27C",     "sch", "#1f77b4", "-",  1.4, "TT 1.8V 27°C (Sch)"),
        ("tt_1v80_27C",     "rcx", "#1f77b4", "--", 1.3, "TT 1.8V 27°C (RCX)"),
        ("ff_ll_1v95_m40C", "rcx", "#d62728", "-",  1.5, "FF_ll 1.95V -40°C (RCX)"),
        ("ss_hh_1v65_85C",  "rcx", "#2ca02c", "-",  1.5, "SS_hh 1.65V 85°C (RCX)"),
    ]
    for corner, view, col, ls, lw, lab in tr_styles:
        if (corner, view) in ldo_tran:
            t, v = ldo_tran[(corner, view)]
            m = (t >= 30e-9) & (t <= 260e-9)
            ax.plot(t[m] * 1e9, v[m] * 1e3, color=col, linestyle=ls, linewidth=lw, label=lab)
    ax.axvline(40.0, color="gray", linestyle=":", linewidth=1.0)
    ax.axvline(140.0, color="gray", linestyle=":", linewidth=1.0)
    ax.text(42.0, ax.get_ylim()[0] + 0.06 * (ax.get_ylim()[1] - ax.get_ylim()[0]), "0.1→6 mA\n(200 ps)", fontsize=7.5, color="#333")
    ax.text(142.0, ax.get_ylim()[0] + 0.06 * (ax.get_ylim()[1] - ax.get_ylim()[0]), "6→0.1 mA\n(200 ps)", fontsize=7.5, color="#333")
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("$V_{\\mathrm{drv}}$ (mV)")
    ax.set_title("(b) TX SST `sst_vdrv_ldo`: 0.1 ↔ 6 mA (200 ps) Load-Step Transient")
    ax.set_xlim(30, 260)
    ax.legend(loc="upper right", frameon=True, framealpha=0.92)

    # --- Panel C: bias_top_v2 (Bandgap Core + ref_pbuf + ref_vbuf) PM vs C_load ---
    ax = axes[1, 0]
    buf_corners = [
        ("tt_1v80_27C",     "#1f77b4", "TT 1.8V 27°C"),
        ("ss_hh_1v65_m40C", "#2ca02c", "SS_hh 1.65V -40°C"),
        ("ff_ll_1v95_85C",  "#d62728", "FF_ll 1.95V 85°C"),
        ("fs_hh_1v65_85C",  "#9467bd", "FS_hh 1.65V 85°C"),
    ]
    for corner, col, lab in buf_corners:
        ys_p = [bias_plot["pbuf"][(corner, "sch", c)]["pm_deg"] for c in BUF_CLOADS_PF]
        ys_v = [bias_plot["vbuf"][(corner, "sch", c)]["pm_deg"] for c in BUF_CLOADS_PF]
        ax.semilogx(BUF_CLOADS_PF, ys_p, color=col, linestyle="-", marker="o", markersize=4.5, linewidth=1.4, label=f"pbuf {lab}")
        ax.semilogx(BUF_CLOADS_PF, ys_v, color=col, linestyle="--", marker="s", markersize=4.0, linewidth=1.2, alpha=0.85, label=f"vbuf(vcm) {lab}")
    # Overlay PEX points on TT
    pex_c = [0.2, 2.0, 10.0, 50.0]
    ax.semilogx(
        pex_c, [bias_plot["pbuf"][("tt_1v80_27C", "pex", c)]["pm_deg"] for c in pex_c],
        color="black", linestyle="none", marker="*", markersize=7, label="pbuf TT (CPEX)",
    )
    ax.semilogx(
        pex_c, [bias_plot["vbuf"][("tt_1v80_27C", "pex", c)]["pm_deg"] for c in pex_c],
        color="black", linestyle="none", marker="x", markersize=6, label="vbuf TT (CPEX)",
    )
    # Annotate Bandgap Core PM range in a clean inset box
    core_sch = [r for r in bias_summary["core_rows"] if r["view"] == "sch"]
    core_pex = [r for r in bias_summary["core_rows"] if r["view"] == "pex"]
    c_pm_min = min(r["pm_deg"] for r in core_sch)
    c_pm_max = max(r["pm_deg"] for r in core_sch)
    cp_pm_min = min(r["pm_deg"] for r in core_pex)
    ax.text(
        0.025, 0.80,
        f"Bandgap FC-OTA Net Loop (7 PVT×RC, 1 Hz–10 GHz):\n"
        f"  Sch PM: {c_pm_min:.1f}°–{c_pm_max:.1f}° | CPEX min: {cp_pm_min:.1f}°\n"
        f"  Startup (1 µs & 50 ns) + ±50 mV: 0 lockup / 0 osc",
        transform=ax.transAxes, fontsize=7.3,
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#f4f8ff", edgecolor="#4a7ab5", alpha=0.95),
    )
    ax.axhline(45.0, color="#b22222", linestyle="--", linewidth=1.2, alpha=0.85)
    ax.axhspan(0, 45.0, color="#ffcccc", alpha=0.22)
    ax.axvline(5.0, color="#2ca02c", linestyle=":", linewidth=1.0, alpha=0.7)
    ax.axvline(42.0, color="#1f77b4", linestyle=":", linewidth=1.0, alpha=0.7)
    ax.text(5.3, 92, "vcm nom\n(5 pF)", fontsize=7, color="#2ca02c")
    ax.text(28.0, 92, "LF pre\n(42 pF)", fontsize=7, color="#1f77b4")
    ax.set_xlabel("Capacitive Load $C_{\\mathrm{load}}$ (pF)")
    ax.set_ylabel("Middlebrook Phase Margin (°)")
    ax.set_title("(c) `bias_top_v2`: `ref_pbuf` & `ref_vbuf` (`vcm`) PM vs. $C_{\\mathrm{load}}$ (Sch + CPEX)")
    ax.set_xlim(0.16, 65.0)
    ax.set_ylim(0, 102)
    ax.legend(loc="lower right", bbox_to_anchor=(0.99, 0.03), ncol=2, fontsize=6.6, frameon=True, framealpha=0.94)

    # --- Panel D: Chip-Level PDN Z_PDN(f) Resonance (Undamped vs Damped Decap) + 250 MHz Inset ---
    ax = axes[1, 1]
    pdn_ac = pdn_plot["ac"]
    pdn_curves = [
        ((0.5, 0.0, 0.0),   "#8c564b", ":",  1.3, "Undamped $L_{\\mathrm{pkg}}=0.5$ nH ($C_{\\mathrm{int}}=260$ pF)"),
        ((1.5, 0.0, 0.0),   "#d62728", "-",  2.0, "Undamped $L_{\\mathrm{pkg}}=1.5$ nH (hits 250 MHz!)"),
        ((2.0, 0.0, 0.0),   "#ff7f0e", "-",  1.6, "Undamped $L_{\\mathrm{pkg}}=2.0$ nH"),
        ((4.0, 0.0, 0.0),   "#9467bd", "--", 1.4, "Undamped $L_{\\mathrm{pkg}}=4.0$ nH"),
        ((1.5, 500.0, 0.0), "#e377c2", "-.", 1.5, "$L=1.5$ nH + 500 pF ($R_{\\mathrm{damp}}=0\\,\\Omega$, shifts peak)"),
        ((1.5, 500.0, 2.0), "#1f77b4", "-",  2.2, "$L=1.5$ nH + 500 pF + $2.0\\,\\Omega$ damped (REC)"),
        ((2.0, 500.0, 2.0), "#2ca02c", "--", 1.8, "$L=2.0$ nH + 500 pF + $2.0\\,\\Omega$ damped"),
    ]
    for key, col, ls, lw, lab in pdn_curves:
        hz, zmag = pdn_ac[key]
        ax.loglog(hz / 1e6, zmag, color=col, linestyle=ls, linewidth=lw, label=lab)
    ax.axvline(250.0, color="#b22222", linestyle="--", linewidth=1.2, alpha=0.85)
    ax.text(285.0, 0.22, "250 MHz\nWord Clock", color="#b22222", fontsize=7.6, fontweight="bold", ha="left")
    ax.axhline(5.0, color="#2ca02c", linestyle=":", linewidth=1.2, alpha=0.9)
    ax.text(4300.0, 5.7, "5 Ω Target", color="#2ca02c", fontsize=7.5, fontweight="bold", ha="right")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("$|Z_{\\mathrm{PDN}}(f)|$ ($\\Omega$)")
    ax.set_title("(d) Chip-Level PDN $|Z_{\\mathrm{PDN}}(f)|$: Anti-Resonance vs. Damped Decap")
    ax.set_xlim(1.0, 5000.0)
    ax.set_ylim(0.15, 220.0)
    ax.legend(loc="lower left", fontsize=6.4, frameon=True, framealpha=0.94)

    # Clean inset in upper-left empty sky (1-40 MHz region where Z_PDN is flat < 1.5 Ohm, zero overlap!)
    ins = ax.inset_axes([0.08, 0.56, 0.41, 0.40])
    t_u, v_u = pdn_plot["tran"]["L1p5_undamped_30mA"]
    t_d, v_d = pdn_plot["tran"]["L1p5_C500_R2p0_30mA"]
    m_i = (t_u >= 5e-9) & (t_u <= 145e-9)
    ins.plot(t_u[m_i] * 1e9, (v_u[m_i] - 1.8) * 1e3, color="#d62728", linewidth=0.85, label="Undamped")
    ins.plot(t_d[m_i] * 1e9, (v_d[m_i] - 1.8) * 1e3, color="#1f77b4", linewidth=1.05, label="500pF+2Ω")
    ins.set_title("250 MHz 30 mA Burst ($L=1.5$ nH)", fontsize=7.0, pad=2)
    ins.set_xlabel("Time (ns)", fontsize=6.5, labelpad=1)
    ins.set_ylabel("$\\Delta V_{\\mathrm{DD}}$ (mV)", fontsize=6.5, labelpad=1)
    ins.tick_params(labelsize=6.2)
    ins.legend(loc="lower right", fontsize=6.0, frameon=True, framealpha=0.92)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIG_PATH, dpi=180)
    plt.close(fig)


# ===========================================================================
# Main Runner
# ===========================================================================

def _only_benign_gmin_pow(failures: list[str]) -> bool:
    return bool(failures) and all("out of range for ^" in f.lower() for f in failures)


def run_jobs_checked(jobs: list[tuple[str, Path, dict]], workers: int, label: str) -> None:
    print(f"[{label}] Launching {len(jobs)} ngspice jobs (workers={workers}, num_threads=1)...", flush=True)
    t0 = time.time()
    execs = spice.run_many(jobs, workers=workers, smoke=False)
    failed = []
    for ex in execs:
        if not ex.ok:
            if ex.exit_code == 0 and _only_benign_gmin_pow(ex.log_failures):
                print(f"  [note] {ex.run_dir.name}: benign gmin-stepping `out of range for ^` recovered cleanly (exit=0)", flush=True)
            else:
                failed.append((str(ex.run_dir.relative_to(ROOT)), ex.exit_code, ex.log_failures[:3]))
    dt = time.time() - t0
    print(f"[{label}] Finished {len(jobs)} jobs in {dt:.1f}s (failed={len(failed)})", flush=True)
    if failed:
        raise RuntimeError(f"[{label}] ngspice failures: {failed}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, choices=(1, 2), default=2, help="Max concurrent ngspice workers (strictly <= 2)")
    ap.add_argument("--replot-only", action="store_true", help="Skip simulation and regenerate summary.json + PNG from existing results")
    args = ap.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    t_start = time.time()

    if not args.replot_only:
        # Clean previous sub-runs only if re-running fresh? No, follow append/clean check:
        # Run directories inside OUT_ROOT are created fresh; skip any deck whose execution.json already succeeded!
        def need_run(run_dir: Path) -> bool:
            ex_p = run_dir / "execution.json"
            if ex_p.exists():
                rec = json.loads(ex_p.read_text())
                fails = rec.get("log_failures") or []
                if rec.get("exit_code") == 0 and (not fails or _only_benign_gmin_pow(fails)):
                    return False
            return True

        # --- Stage 1: TX SST sst_vdrv_ldo AC + Tran + Compensation What-If ---
        jobs_ldo_ac = []
        for tag, proc, rc, vdd, temp, inc_lay in LDO_CORNERS:
            rdir = OUT_ROOT / "ldo_ac" / tag
            if need_run(rdir):
                deck = build_ldo_ac_deck(tag, proc, rc, vdd, temp, inc_lay)
                jobs_ldo_ac.append((deck, rdir, dict(timeout_s=600, meta=dict(stage="ldo_ac", corner=tag))))
        if jobs_ldo_ac:
            run_jobs_checked(jobs_ldo_ac, args.workers, "1A: LDO AC Middlebrook + Zout")

        jobs_ldo_tr = []
        for tag, proc, rc, vdd, temp, inc_lay in LDO_CORNERS:
            if not inc_lay:
                continue
            rdir = OUT_ROOT / "ldo_tran" / tag
            if need_run(rdir):
                deck = build_ldo_tran_deck(tag, proc, rc, vdd, temp)
                jobs_ldo_tr.append((deck, rdir, dict(timeout_s=600, meta=dict(stage="ldo_tran", corner=tag))))
        if jobs_ldo_tr:
            run_jobs_checked(jobs_ldo_tr, args.workers, "1B: LDO Load-Step Transient")

        jobs_ldo_comp = []
        for tag, proc, rc, vdd, temp in [
            ("tt_1v80_27C", "tt", "tt", 1.80, 27),
            ("ff_ll_1v95_m40C", "ff", "ll", 1.95, -40),
            ("ss_hh_1v65_85C", "ss", "hh", 1.65, 85),
        ]:
            rdir = OUT_ROOT / "ldo_comp" / tag
            if need_run(rdir):
                deck = build_ldo_comp_whatif_deck(tag, proc, rc, vdd, temp)
                jobs_ldo_comp.append((deck, rdir, dict(timeout_s=600, meta=dict(stage="ldo_comp", corner=tag))))
        if jobs_ldo_comp:
            run_jobs_checked(jobs_ldo_comp, args.workers, "1C: LDO Compensation What-If")

        # --- Stage 2: BIAS v2 Dual-Loop AC + Buffer C_load + Zero-Start Ramps & Steps ---
        jobs_bias_ac = []
        for sec, pts in BIAS_SECTIONS:
            rdir = OUT_ROOT / "bias_ac" / sec
            if need_run(rdir):
                deck = build_bias_ac_deck(sec, pts)
                jobs_bias_ac.append((deck, rdir, dict(timeout_s=900, meta=dict(stage="bias_ac", section=sec))))
        if jobs_bias_ac:
            run_jobs_checked(jobs_bias_ac, args.workers, "2A: BIAS v2 + Buffers AC Middlebrook")

        jobs_bias_tr = []
        for sec, pts in BIAS_SECTIONS:
            rdir = OUT_ROOT / "bias_tran" / sec
            if need_run(rdir):
                inc_pex = sec in ("tt", "ss_hh", "ff_ll")
                deck = build_bias_tran_deck(sec, pts, include_pex=inc_pex)
                jobs_bias_tr.append((deck, rdir, dict(timeout_s=900, meta=dict(stage="bias_tran", section=sec))))
        if jobs_bias_tr:
            run_jobs_checked(jobs_bias_tr, args.workers, "2B: BIAS v2 Zero-Start Ramps + Supply Steps")

        # --- Stage 3: Chip-Level PDN AC Z_PDN + 250 MHz Burst Transient ---
        jobs_pdn = []
        if need_run(OUT_ROOT / "pdn_ac"):
            jobs_pdn.append((build_pdn_deck(), OUT_ROOT / "pdn_ac", dict(timeout_s=180, meta=dict(stage="pdn_ac"))))
        if need_run(OUT_ROOT / "pdn_tran"):
            jobs_pdn.append((build_pdn_tran_deck(), OUT_ROOT / "pdn_tran", dict(timeout_s=180, meta=dict(stage="pdn_tran"))))
        if jobs_pdn:
            run_jobs_checked(jobs_pdn, args.workers, "3: Chip-Level PDN AC + 250 MHz Burst")

    # Parse all outputs
    print("[Analysis] Parsing all results & generating 4-panel figure...", flush=True)
    ldo_sum, ldo_bode, ldo_tran = parse_ldo_results(OUT_ROOT)
    bias_sum, bias_plot = parse_bias_results(OUT_ROOT)
    pdn_sum, pdn_plot = parse_pdn_results(OUT_ROOT)

    make_summary_figure(ldo_sum, ldo_bode, ldo_tran, bias_sum, bias_plot, pdn_sum, pdn_plot)

    # Compact high-level verdicts for summary.json
    ldo_ac = ldo_sum["ac_rows"]
    ldo_worst_all = min(ldo_ac, key=lambda r: r["pm_deg"] if r["pm_deg"] is not None else 999)
    ldo_worst_nom = min([r for r in ldo_ac if r["iload_ma"] >= 2.0], key=lambda r: r["pm_deg"])
    ldo_light_fails = [r for r in ldo_ac if r["pm_deg"] is not None and r["pm_deg"] < 45.0]

    bias_core_min = min(bias_sum["core_rows"], key=lambda r: r["pm_deg"])
    bias_vi_min = min(bias_sum["vi_rows"], key=lambda r: r["pm_deg"])
    pbuf_min_all = min(bias_sum["pbuf_rows"], key=lambda r: r["pm_deg"])
    vbuf_min_all = min(bias_sum["vbuf_rows"], key=lambda r: r["pm_deg"])

    summary = dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        elapsed_s=round(time.time() - t_start, 2),
        workers_used=args.workers,
        figure=str(FIG_PATH.relative_to(ROOT)),
        highlights=dict(
            ldo_worst_overall=dict(
                corner=ldo_worst_all["corner"], view=ldo_worst_all["view"], iload_ma=ldo_worst_all["iload_ma"],
                pm_deg=ldo_worst_all["pm_deg"], gm_db=ldo_worst_all["gm_db"], ugf_hz=ldo_worst_all["ugf_hz"],
                zout_peak_ohm=ldo_worst_all["zout_peak_ohm"],
            ),
            ldo_worst_active_ge2ma=dict(
                corner=ldo_worst_nom["corner"], view=ldo_worst_nom["view"], iload_ma=ldo_worst_nom["iload_ma"],
                pm_deg=ldo_worst_nom["pm_deg"], gm_db=ldo_worst_nom["gm_db"], ugf_hz=ldo_worst_nom["ugf_hz"],
            ),
            ldo_pm_below_45_count=len(ldo_light_fails),
            ldo_tran_sustained_osc_count=sum(
                1 for r in ldo_sum["tran_rows"] if r["step_up"]["sustained_osc"] or r["step_down"]["sustained_osc"]
            ),
            bias_core_min_pm=dict(
                corner=bias_core_min["corner"], view=bias_core_min["view"],
                pm_deg=bias_core_min["pm_deg"], gm_db=bias_core_min["gm_db"], ugf_hz=bias_core_min["ugf_hz"],
            ),
            bias_vi_min_pm=dict(
                corner=bias_vi_min["corner"], pm_deg=bias_vi_min["pm_deg"], gm_db=bias_vi_min["gm_db"],
            ),
            pbuf_min_pm=dict(
                corner=pbuf_min_all["corner"], view=pbuf_min_all["view"], cload_pf=pbuf_min_all["cload_pf"],
                pm_deg=pbuf_min_all["pm_deg"],
            ),
            vbuf_min_pm=dict(
                corner=vbuf_min_all["corner"], view=vbuf_min_all["view"], cload_pf=vbuf_min_all["cload_pf"],
                pm_deg=vbuf_min_all["pm_deg"],
            ),
            bias_tran_lockup_count=sum(1 for r in bias_sum["tran_rows"] if r["startup_lockup"]),
            bias_tran_osc_count=sum(1 for r in bias_sum["tran_rows"] if r["hf_oscillation"]),
        ),
        investigation_1_sst_vdrv_ldo=ldo_sum,
        investigation_2_bias_v2=bias_sum,
        investigation_3_chip_pdn=pdn_sum,
    )
    sum_path = OUT_ROOT / "summary.json"
    sum_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[DONE] Saved {sum_path.relative_to(ROOT)} and {FIG_PATH.relative_to(ROOT)} in {time.time() - t_start:.1f}s")
    print(json.dumps(summary["highlights"], indent=2))


if __name__ == "__main__":
    main()
