#!/usr/bin/env python3
"""Full 5G Octagonal LC-VCO (`lc_vco_5g_oct_pdk`) CPEX & Closed-Loop 5G LC-PLL Characterization.

Closes the 3 remaining simulation characterization items on the 5G Plan-C clocking subsystem:
  1. Char 1 — Full 16-code (c0..c15) monotonic tuning & overlap map on Magic CPEX (TT 27C 1.8V)
              at Vctrl = 0.35, 0.90, 1.45 V (48 points in 2 merged decks, strictly sparse solver).
  2. Char 2 — True K_vdd supply pushing (MHz/V) on Magic CPEX at code=5, Vctrl=0.84 V across
              VDD_Q = 1.750..1.850 V for both TT 27C and SS +85C (hh), folded with measured
              HV18 Kelvin LDO PSRR (>=44 dB @ 20 MHz) to quantify supply-induced FM jitter.
  3. Char 3 — True transistor-level closed-loop 5G Type-II LC-PLL acquisition & 250 MHz spur
              transient (TT 27C 1.8V, N=20, 250 MHz ref -> PFD sc_dly -> CP v4 -> LF ->
              lc_5g_div2_oct_pdk [code=5] -> r5 CML->CMOS -> div_ab_5g_v2 [/10]) from
              Vctrl(0) = 0.72 V (-120 mV / -17 MHz step):
                - Case A: As-Built Plan-C LF k4 (Rz=4.13 kOhm, Icp=200 uA, Ci=18.38 pF)
                - Case B: Retuned Zero-CP-Change (Rz=18.0 kOhm, Icp=200 uA, Ci=18.38 pF)
                - Case C: Recommended Optimal   (Rz=12.0 kOhm, Icp=400 uA, Ci=18.38 pF)
                - Case D: Retuned + 3rd-Order Spur Filter (Rz=18.0 kOhm, Icp=200 uA, R3=2k/C3=0.6pF)

Rules enforced:
  - Hard cap: workers <= 2, num_threads=1.
  - Strictly SPARSE solver (NEVER klu, NEVER cshunt — sky130_fd_pr__cap_var_lvt is present!).
  - Full t_end completeness check on every raw file; deletes .raw files after extracting JSON/NPZ.

Outputs:
  - results/analog/pll/vco_5g_full_char_20261126/summary.json
  - results/analog/pll/vco_5g_full_char_20261126/traces.npz
  - docs/figures/clocking/serdes_5g_vco_pll_char_20261126.png (240 DPI)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import Patch
import numpy as np

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import spice, watch  # noqa: E402

PDK_LIB = "/home/host/.volare/sky130A/libs.tech/ngspice/sky130.lib.spice"
SC_LIB = "/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
PRIM_SPICE = REPO / "analog/common/devices/spice/sky130_primitives.spice"
PFET_LVT_SPICE = REPO / "analog/common/devices/spice/sky130_pfet_lvt.spice"
CMOS_SPICE = REPO / "analog/common/devices/spice/cmos_logic.spice"
C2C_BASE = REPO / "analog/common/cml_to_cmos/spice/cml_to_cmos.spice"
C2C_R4 = REPO / "analog/common/cml_to_cmos/spice/cml_to_cmos_r4_v4.spice"
C2C_R5 = REPO / "analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice"
BIAS_V2 = REPO / "analog/bias/spice/bias_v2.spice"
OCT_SPICE = REPO / "analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice"
PEX_SPICE = REPO / "analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/vco5g_lc_active_div2_oct_pdk_pex.spice"
DIV_AB = REPO / "analog/pll/divider/spice/pll_div_ab_5g_v2.spice"
PFD_SC = REPO / "analog/pll/pfd/spice/pfd_sc.spice"
CP_V4 = REPO / "analog/pll/cp/spice/charge_pump_steer_v4.spice"
LF_PRE = REPO / "analog/pll/loop_filter/spice/passive_rc_precharge.spice"
LF_K4 = REPO / "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice"
STAB_SUMMARY = REPO / "results/verification/stability_5g_20261126/summary.json"

OUT_ROOT = REPO / "results/analog/pll/vco_5g_full_char_20261126"
FIG_PATH = REPO / "docs/figures/clocking/serdes_5g_vco_pll_char_20261126.png"

FREF = 250.0e6
TREF = 1.0 / FREF
FVCO_TGT = 5.0e9
VCTRL_SWEEP = (0.35, 0.90, 1.45)
VDD_SWEEP = (1.750, 1.775, 1.800, 1.825, 1.850)


# =============================================================================
# Shared Waveform Measurement Helpers
# =============================================================================
def rising_crossings(t: np.ndarray, y: np.ndarray, thr: float = 0.0) -> np.ndarray:
    s = y - thr
    idx = np.where((s[:-1] <= 0.0) & (s[1:] > 0.0))[0]
    if len(idx) == 0:
        return np.array([], dtype=float)
    dy = s[idx + 1] - s[idx]
    frac = np.where(dy != 0.0, -s[idx] / dy, 0.5)
    return t[idx] + frac * (t[idx + 1] - t[idx])


def pulse_widths_ps(t: np.ndarray, y: np.ndarray, thr: float = 0.9) -> dict:
    s = y - thr
    r_idx = np.where((s[:-1] <= 0.0) & (s[1:] > 0.0))[0]
    f_idx = np.where((s[:-1] >= 0.0) & (s[1:] < 0.0))[0]
    if len(r_idx) == 0 or len(f_idx) == 0:
        return {"count": 0, "mean_ps": float("nan")}
    tr = t[r_idx] - s[r_idx] * (t[r_idx + 1] - t[r_idx]) / np.where(s[r_idx + 1] != s[r_idx], s[r_idx + 1] - s[r_idx], 1.0)
    tf = t[f_idx] - s[f_idx] * (t[f_idx + 1] - t[f_idx]) / np.where(s[f_idx + 1] != s[f_idx], s[f_idx + 1] - s[f_idx], 1.0)
    widths = []
    for r in tr:
        after = tf[tf > r]
        if len(after):
            dt = float(after[0] - r)
            if 0.0 < dt < TREF * 0.95:
                widths.append(dt * 1e12)
    return {"count": len(widths), "mean_ps": float(np.mean(widths)) if widths else float("nan")}


def leeson_pn_1mhz(f_vco_ghz: float, vpp_tank: float, temp_c: float) -> float | None:
    if not (f_vco_ghz > 1.0 and vpp_tank > 0.2):
        return None
    kT = 1.380649e-23 * (temp_c + 273.15)
    v_amp = 0.5 * vpp_tank
    rp = 611.0
    q_tank = 7.15
    p_sig = (v_amp ** 2) / (2.0 * rp)
    F_excess = 2.5
    df = 1.0e6
    l_lin = (2.0 * F_excess * kT / p_sig) * ((f_vco_ghz * 1e9) / (2.0 * q_tank * df)) ** 2
    return round(10.0 * math.log10(l_lin), 2)


def analyze_vco_raw(raw_path: Path, temp_c: float, t_stop: float, t_win_start: float) -> dict:
    w = spice.Waves(raw_path)
    t = w.t
    assert float(t[-1]) >= t_stop * 0.99, f"truncated raw {raw_path}: t_end={t[-1]*1e9:.3f}ns < {t_stop*1e9:.3f}ns"
    mask = t >= t_win_start
    tm = t[mask]
    vdiff = (w["v(vp)"] - w["v(vn)"])[mask]
    vi = (w["v(ip)"] - w["v(in)"])[mask]
    vq = (w["v(qp)"] - w["v(qn)"])[mask]
    itot_ma = float(-np.mean(w["i(vdd)"][mask]) * 1e3)

    vpp_tank = float(np.max(vdiff) - np.min(vdiff))
    vpp_i = float(np.max(vi) - np.min(vi))
    vpp_q = float(np.max(vq) - np.min(vq))

    tx_vco = rising_crossings(tm, vdiff, 0.0)
    f_vco_ghz = float(1.0 / np.median(np.diff(tx_vco)) / 1e9) if len(tx_vco) >= 4 and vpp_tank > 0.2 else 0.0
    osc_started = bool(f_vco_ghz > 3.0 and vpp_tank > 0.5)

    tx_i = rising_crossings(tm, vi, 0.0)
    tx_q = rising_crossings(tm, vq, 0.0)
    if len(tx_i) >= 4 and len(tx_q) >= 4 and vpp_i > 0.15 and vpp_q > 0.15 and f_vco_ghz > 1.0:
        f_i_ghz = float(1.0 / np.median(np.diff(tx_i)) / 1e9)
        f_q_ghz = float(1.0 / np.median(np.diff(tx_q)) / 1e9)
        errs_ps, errs_deg = [], []
        for k in range(len(tx_i) - 1):
            t0, t1 = tx_i[k], tx_i[k + 1]
            dt = t1 - t0
            qs = tx_q[(tx_q >= t0) & (tx_q < t1)]
            if len(qs) == 1:
                phi = (qs[0] - t0) / dt
                e_cyc = min(abs(phi - 0.25), abs(phi - 0.75))
                errs_ps.append(e_cyc * dt * 1e12)
                errs_deg.append(e_cyc * 360.0)
        q_err_ps = float(np.mean(errs_ps)) if errs_ps else float("nan")
        q_err_deg = float(np.mean(errs_deg)) if errs_deg else float("nan")
        div_locked = abs(f_i_ghz / (0.5 * f_vco_ghz) - 1.0) < 0.01 and abs(f_q_ghz / (0.5 * f_vco_ghz) - 1.0) < 0.01
    else:
        f_i_ghz = f_q_ghz = 0.0
        q_err_ps = q_err_deg = float("nan")
        div_locked = False

    return {
        "osc_started": osc_started,
        "f_vco_ghz": round(f_vco_ghz, 5),
        "vpp_tank_v": round(vpp_tank, 4),
        "itot_ma": round(itot_ma, 3),
        "div_locked": div_locked,
        "f_i_ghz": round(f_i_ghz, 5),
        "f_q_ghz": round(f_q_ghz, 5),
        "vpp_i_v": round(vpp_i, 4),
        "vpp_q_v": round(vpp_q, 4),
        "q_err_mean_ps": None if math.isnan(q_err_ps) else round(q_err_ps, 3),
        "q_err_mean_deg": None if math.isnan(q_err_deg) else round(q_err_deg, 3),
        "pn_1mhz_dbc_hz_est": leeson_pn_1mhz(f_vco_ghz, vpp_tank, temp_c),
    }


def check_worker_budget(workers: int) -> int:
    w = max(1, min(workers, 2))
    active = len(watch.ngspice_cwds())
    if active + w > 4:
        raise RuntimeError(f"Host ngspice limit guard: {active} already active, requested {w}")
    return w


def cleanup_raws(directory: Path) -> int:
    n = 0
    if not directory.exists():
        return 0
    for p in directory.rglob("*.raw"):
        try:
            p.unlink()
            n += 1
        except OSError:
            pass
    return n


# =============================================================================
# Char 1: Full 16-Code (c0..c15) Monotonic Overlap Map on CPEX (TT 27C 1.8V)
# =============================================================================
def build_codes16_deck(
    points: list[tuple[int, int, float]],
    *,
    method: str = "trap",
    tstep: str = "3p",
    reltol: str = "5e-4",
    trtol: int = 5,
) -> str:
    vdd = 1.80
    lines = [
        f"* 5G Octagonal LC-VCO CPEX 16-Code Overlap Sweep ({len(points)} pts, TT 27C 1.8V, {method} {tstep})",
        f'.lib "{PDK_LIB}" tt',
        f'.include "{PRIM_SPICE}"',
        f'.include "{PFET_LVT_SPICE}"',
        f'.include "{OCT_SPICE}"',
        f'.include "{PEX_SPICE}"',
        f"Vdd vdd 0 {vdd:.6f}",
        f"Vctrl vctrl 0 {points[0][2]:.6f}",
        "Vb0 b0 0 0.0",
        "Vb1 b1 0 0.0",
        "Vb2 b2 0 0.0",
        "Vb3 b3 0 0.0",
        "Xind vp vn ct 0 vco5g_ind_oct_2n5_pdk rm_scale=1.00 c_scale=1.00",
        "Xact vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd 0 vco5g_lc_active_div2_oct_pdk",
        "Cip ip 0 30f",
        "Cin in 0 30f",
        "Cqp qp 0 30f",
        "Cqn qn 0 30f",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 80u 0.26n 80u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 4.2n 0 4.21n 60u 4.26n 60u 4.27n 0)",
        ".temp 27",
        # Strict SPARSE solver (NO klu, NO cshunt — cap_var_lvt present!)
        f".options reltol={reltol} abstol=10p vntol=10u gmin=1e-11 trtol={trtol} itl4=120 method={method}",
        ".save v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
    ]
    last_code = None
    for code, vi, vc in points:
        if code != last_code:
            b = [vdd if ((code >> k) & 1) else 0.0 for k in range(4)]
            lines += [
                f"alter Vb0 dc={b[0]:.6f}",
                f"alter Vb1 dc={b[1]:.6f}",
                f"alter Vb2 dc={b[2]:.6f}",
                f"alter Vb3 dc={b[3]:.6f}",
            ]
            last_code = code
        tag = f"c{code:02d}_v{vi}"
        lines += [
            f"alter Vctrl dc={vc:.6f}",
            f"tran {tstep} 12n 7.5n {tstep}",
            f"write {tag}.raw v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd)",
            "destroy all",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def _raw_complete(path: Path, t_stop: float) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    try:
        return float(spice.Waves(path).t[-1]) >= t_stop * 0.99
    except Exception:
        return False


def run_char1_codes16(out_root: Path, workers: int) -> dict:
    c_dir = out_root / "char1_codes16"
    cache_path = c_dir / "char1_summary.json"
    if cache_path.exists():
        print(f"[Char 1] Loaded cached {cache_path.name}", flush=True)
        return json.loads(cache_path.read_text())

    c_dir.mkdir(parents=True, exist_ok=True)
    splits = [
        ("blk_lo", list(range(0, 8))),
        ("blk_hi", list(range(8, 16))),
    ]
    t0 = time.time()
    jobs = []
    run_dirs: dict[str, Path] = {}
    for name, codes in splits:
        # Find latest run dir for this split if any, else create a fresh one via next_run_dir
        existing = sorted(c_dir.glob(f"{name}*"))
        latest = existing[-1] if existing else None
        pts = [(c, vi, vc) for c in codes for vi, vc in enumerate(VCTRL_SWEEP) if latest is None or not _raw_complete(latest / f"c{c:02d}_v{vi}.raw", 12.0e-9)]
        if pts:
            rdir = spice.next_run_dir(c_dir, name)
            run_dirs[name] = rdir
            deck = build_codes16_deck(pts, method="trap", tstep="3p", reltol="5e-4", trtol=5)
            jobs.append((deck, rdir, dict(timeout_s=1800, meta={"stage": "char1", "codes": codes})))
        else:
            assert latest is not None
            run_dirs[name] = latest

    if jobs:
        w = check_worker_budget(workers)
        print(f"[Char 1] Running 16-code x 3 Vctrl CPEX sweep across {len(jobs)} merged decks (workers={w})...", flush=True)
        for ex in spice.run_many(jobs, workers=w, smoke=False):
            print(f"  [Char 1] {ex.run_dir.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fails={ex.log_failures[:2]}", flush=True)

    # Auto-retry any missing/failed point individually with tighter 2p trap
    retry_jobs = []
    for name, codes in splits:
        rdir = run_dirs[name]
        missing = [(c, vi, vc) for c in codes for vi, vc in enumerate(VCTRL_SWEEP) if not _raw_complete(rdir / f"c{c:02d}_v{vi}.raw", 12.0e-9)]
        if missing:
            sub = spice.next_run_dir(c_dir, f"{name}_retry2p")
            deck = build_codes16_deck(missing, method="trap", tstep="2p", reltol="3e-4", trtol=4)
            retry_jobs.append((deck, sub, dict(timeout_s=1200, meta={"stage": "char1_retry", "name": name, "n": len(missing)})))
    if retry_jobs:
        w = check_worker_budget(workers)
        print(f"[Char 1] Retrying missing points with 2p trap (workers={w})...", flush=True)
        for ex in spice.run_many(retry_jobs, workers=w, smoke=False):
            split_name = ex.run_dir.name.split("_retry2p")[0]
            print(f"  [Char 1 retry] {ex.run_dir.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fails={ex.log_failures[:2]}", flush=True)
            for raw_p in ex.run_dir.glob("*.raw"):
                raw_p.rename(run_dirs[split_name] / raw_p.name)
    elapsed = time.time() - t0

    rows = []
    for name, codes in splits:
        rdir = run_dirs[name]
        for code in codes:
            pts = []
            for vi, vc in enumerate(VCTRL_SWEEP):
                raw = rdir / f"c{code:02d}_v{vi}.raw"
                m = analyze_vco_raw(raw, 27.0, t_stop=12.0e-9, t_win_start=8.0e-9)
                m["vctrl_v"] = vc
                pts.append(m)
            f_lo, f_mid, f_hi = pts[0]["f_vco_ghz"], pts[1]["f_vco_ghz"], pts[2]["f_vco_ghz"]
            kvco_full = (f_hi - f_lo) * 1e3 / (VCTRL_SWEEP[-1] - VCTRL_SWEEP[0])
            kvco_lo = (f_mid - f_lo) * 1e3 / (VCTRL_SWEEP[1] - VCTRL_SWEEP[0])
            kvco_hi = (f_hi - f_mid) * 1e3 / (VCTRL_SWEEP[2] - VCTRL_SWEEP[1])
            row = {
                "code": code,
                "f_lo_ghz": f_lo,
                "f_mid_ghz": f_mid,
                "f_hi_ghz": f_hi,
                "tune_span_mhz": round((f_hi - f_lo) * 1e3, 2),
                "kvco_mhz_per_v": round(kvco_full, 1),
                "kvco_lo_half_mhz_per_v": round(kvco_lo, 1),
                "kvco_hi_half_mhz_per_v": round(kvco_hi, 1),
                "vpp_tank_mid_v": pts[1]["vpp_tank_v"],
                "itot_mid_ma": pts[1]["itot_ma"],
                "q_err_mid_ps": pts[1]["q_err_mean_ps"],
                "q_err_max_ps": max(p["q_err_mean_ps"] for p in pts if p["q_err_mean_ps"] is not None),
                "q_err_mid_deg": pts[1]["q_err_mean_deg"],
                "pn_1m_mid_dbc": pts[1]["pn_1mhz_dbc_hz_est"],
                "all_started": all(p["osc_started"] for p in pts),
                "all_div_locked": all(p["div_locked"] for p in pts),
                "points": pts,
            }
            rows.append(row)
            print(
                f"  c{code:02d}: [{f_lo:.4f}, {f_mid:.4f}, {f_hi:.4f}] GHz | span={row['tune_span_mhz']:5.1f} MHz "
                f"Kvco={row['kvco_mhz_per_v']:5.1f} MHz/V | qerr={row['q_err_mid_ps']:.3f} ps | "
                f"Itot={row['itot_mid_ma']:.2f} mA | lock={row['all_div_locked']}",
                flush=True,
            )

    rows.sort(key=lambda r: r["code"])
    # Check 100% monotonicity & 15/15 adjacent code overlaps
    mono_lo = all(rows[k]["f_lo_ghz"] > rows[k + 1]["f_lo_ghz"] for k in range(15))
    mono_mid = all(rows[k]["f_mid_ghz"] > rows[k + 1]["f_mid_ghz"] for k in range(15))
    mono_hi = all(rows[k]["f_hi_ghz"] > rows[k + 1]["f_hi_ghz"] for k in range(15))
    monotonic_100pct = bool(mono_lo and mono_mid and mono_hi)

    overlaps = []
    for k in range(15):
        # Code k is higher frequency, code k+1 is lower frequency
        # Positive overlap iff f(k+1, Vctrl_max) > f(k, Vctrl_min)
        ov_mhz = (rows[k + 1]["f_hi_ghz"] - rows[k]["f_lo_ghz"]) * 1e3
        step_mid_mhz = (rows[k]["f_mid_ghz"] - rows[k + 1]["f_mid_ghz"]) * 1e3
        overlaps.append({
            "pair": f"c{k:02d}-c{k+1:02d}",
            "code_hi": k,
            "code_lo": k + 1,
            "f_low_edge_of_hi_code_ghz": rows[k]["f_lo_ghz"],
            "f_high_edge_of_lo_code_ghz": rows[k + 1]["f_hi_ghz"],
            "overlap_mhz": round(ov_mhz, 2),
            "coarse_step_mid_mhz": round(step_mid_mhz, 2),
            "positive": bool(ov_mhz > 0.0),
        })

    ov_vals = [o["overlap_mhz"] for o in overlaps]
    step_vals = [o["coarse_step_mid_mhz"] for o in overlaps]
    n_pos = sum(1 for o in overlaps if o["positive"])
    q_all = [p["q_err_mean_ps"] for r in rows for p in r["points"] if p["q_err_mean_ps"] is not None]
    i_all = [r["itot_mid_ma"] for r in rows]
    kv_all = [r["kvco_mhz_per_v"] for r in rows]

    # Exact code=5 lock Vctrl for 5.000 GHz
    c5 = rows[5]
    vctrl_5g_c5 = float(np.interp(5.000, [c5["f_lo_ghz"], c5["f_mid_ghz"], c5["f_hi_ghz"]], VCTRL_SWEEP))

    res = {
        "corner": "tt_v1800_t27_tt",
        "vctrl_sweep_v": list(VCTRL_SWEEP),
        "elapsed_s": round(elapsed, 1),
        "total_points": 48,
        "all_osc_started": all(r["all_started"] for r in rows),
        "all_div_locked": all(r["all_div_locked"] for r in rows),
        "monotonic_100pct": monotonic_100pct,
        "monotonic_by_vctrl": {"lo": mono_lo, "mid": mono_mid, "hi": mono_hi},
        "f_min_ghz": rows[15]["f_lo_ghz"],
        "f_max_ghz": rows[0]["f_hi_ghz"],
        "total_span_mhz": round((rows[0]["f_hi_ghz"] - rows[15]["f_lo_ghz"]) * 1e3, 2),
        "positive_overlap_pairs": f"{n_pos}/15",
        "zero_dead_bands": bool(n_pos == 15),
        "overlap_min_mhz": round(min(ov_vals), 2),
        "overlap_max_mhz": round(max(ov_vals), 2),
        "overlap_mean_mhz": round(float(np.mean(ov_vals)), 2),
        "coarse_step_min_mhz": round(min(step_vals), 2),
        "coarse_step_max_mhz": round(max(step_vals), 2),
        "coarse_step_mean_mhz": round(float(np.mean(step_vals)), 2),
        "kvco_range_mhz_per_v": [round(min(kv_all), 1), round(max(kv_all), 1)],
        "kvco_c5_mhz_per_v": c5["kvco_mhz_per_v"],
        "vctrl_5ghz_c5_v": round(vctrl_5g_c5, 4),
        "q_err_ps_range": [round(min(q_all), 3), round(max(q_all), 3)],
        "itot_ma_range": [round(min(i_all), 3), round(max(i_all), 3)],
        "codes": rows,
        "overlaps": overlaps,
    }
    cache_path.write_text(json.dumps(res, indent=2) + "\n")
    n_del = cleanup_raws(c_dir)
    print(
        f"[Char 1] DONE ({elapsed:.1f}s, deleted {n_del} .raw): "
        f"band={res['f_min_ghz']:.4f}-{res['f_max_ghz']:.4f} GHz | mono={monotonic_100pct} | "
        f"overlaps={n_pos}/15 (min={res['overlap_min_mhz']:.1f} MHz, max={res['overlap_max_mhz']:.1f} MHz) | "
        f"Kvco={res['kvco_range_mhz_per_v']} MHz/V | qerr={res['q_err_ps_range']} ps",
        flush=True,
    )
    return res


# =============================================================================
# Char 2: True K_vdd Supply Pushing (MHz/V) on CPEX (TT 27C & SS +85C)
# =============================================================================
def build_kvdd_deck(
    corner_key: str, lib: str, temp_c: float, rm_s: float, c_s: float, vdds: tuple[float, ...],
    *, method: str = "trap",
) -> str:
    # code = 5 (b0=1, b1=0, b2=1, b3=0); b0 and b2 track VDD_Q cleanly via VCVS
    lines = [
        f"* 5G Octagonal LC-VCO CPEX Supply Pushing K_vdd Sweep @ {corner_key} (code=5, Vctrl=0.84V, {method})",
        f'.lib "{PDK_LIB}" {lib}',
        f'.include "{PRIM_SPICE}"',
        f'.include "{PFET_LVT_SPICE}"',
        f'.include "{OCT_SPICE}"',
        f'.include "{PEX_SPICE}"',
        f"Vdd vdd 0 {vdds[0]:.6f}",
        "Vctrl vctrl 0 0.840000",
        "Eb0 b0 0 vdd 0 1.0",
        "Vb1 b1 0 0.0",
        "Eb2 b2 0 vdd 0 1.0",
        "Vb3 b3 0 0.0",
        f"Xind vp vn ct 0 vco5g_ind_oct_2n5_pdk rm_scale={rm_s} c_scale={c_s}",
        "Xact vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd 0 vco5g_lc_active_div2_oct_pdk",
        "Cip ip 0 30f",
        "Cin in 0 30f",
        "Cqp qp 0 30f",
        "Cqn qn 0 30f",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 80u 0.26n 80u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 6.5n 0 6.51n 60u 6.56n 60u 6.57n 0)",
        f".temp {temp_c}",
        # Exact signoff CPEX precision (2p, 20ns) for crisp K_vdd slope extraction
        # Use trap on TT (avoids gear timestep-too-small at high swing VDD=1.85V) & gear on SS+85
        f".options reltol=3e-4 abstol=10p vntol=10u gmin=1e-11 trtol=4 itl4=120 method={method}",
        ".save v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
    ]
    for vi, vdd in enumerate(vdds):
        tag = f"v{vi}_{int(round(vdd * 1000))}"
        lines += [
            f"alter Vdd dc={vdd:.6f}",
            "tran 2p 20n 11n 2p",
            f"write {tag}.raw v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd)",
            "destroy all",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def run_char2_kvdd(out_root: Path, workers: int) -> dict:
    c_dir = out_root / "char2_kvdd"
    cache_path = c_dir / "char2_summary.json"
    if cache_path.exists():
        print(f"[Char 2] Loaded cached {cache_path.name}", flush=True)
        return json.loads(cache_path.read_text())

    c_dir.mkdir(parents=True, exist_ok=True)
    # Load measured HV18 Kelvin LDO PSRR from stability_5g_20261126/summary.json
    stab = json.loads(STAB_SUMMARY.read_text())
    ldo_sim = stab["domains"]["hv18_kelvin_ldo"]["sim_6ma"]

    corner_specs = [
        ("tt_27c", "tt", 27.0, 1.00, 1.00, "trap", ldo_sim["tt_27c"]["psrr_20mhz_db"], ldo_sim["tt_27c"]["psrr_min_db"]),
        ("ss_p85c", "ss_hh", 85.0, 1.22, 1.12, "gear", ldo_sim["ss_p85c"]["psrr_20mhz_db"], ldo_sim["ss_p85c"]["psrr_min_db"]),
    ]
    jobs = []
    kv_dirs: dict[str, Path] = {}
    for ck, lib, tc, rms, cs, meth, _, _ in corner_specs:
        # Look for any existing complete run directory for this corner
        existing = [d for d in sorted(c_dir.glob(f"{ck}*")) if d.is_dir()]
        found = None
        for d in reversed(existing):
            if all(_raw_complete(d / f"v{vi}_{int(round(vdd * 1000))}.raw", 20.0e-9) for vi, vdd in enumerate(VDD_SWEEP)):
                found = d
                break
        if found is not None:
            print(f"  [Char 2] {ck}: all 5 raw points already complete in {found.name}, reusing!", flush=True)
            kv_dirs[ck] = found
            continue
        rdir = spice.next_run_dir(c_dir, ck)
        kv_dirs[ck] = rdir
        deck = build_kvdd_deck(ck, lib, tc, rms, cs, VDD_SWEEP, method=meth)
        jobs.append((deck, rdir, dict(timeout_s=900, meta={"stage": "char2", "corner": ck, "method": meth})))

    t0 = time.time()
    if jobs:
        w = check_worker_budget(workers)
        print(f"[Char 2] Running K_vdd supply pushing on CPEX ({len(jobs)} deck(s), 5 VDD pts each, workers={w})...", flush=True)
        for ex in spice.run_many(jobs, workers=w, smoke=False):
            print(f"  [Char 2] {ex.run_dir.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fails={ex.log_failures[:2]}", flush=True)
            if not ex.ok:
                raise RuntimeError(f"Char 2 failed on {ex.run_dir.name}: {ex.log_failures[:3]}")
    elapsed = time.time() - t0

    corners_out = {}
    for ck, lib, tc, rms, cs, _meth, psrr_20m_db, psrr_min_db in corner_specs:
        rdir = kv_dirs[ck]
        pts = []
        for vi, vdd in enumerate(VDD_SWEEP):
            tag = f"v{vi}_{int(round(vdd * 1000))}"
            m = analyze_vco_raw(rdir / f"{tag}.raw", tc, t_stop=20.0e-9, t_win_start=13.0e-9)
            m["vdd_q_v"] = vdd
            pts.append(m)
        vs = np.array([p["vdd_q_v"] for p in pts])
        fs_mhz = np.array([p["f_vco_ghz"] * 1e3 for p in pts])
        # Linear least-squares fit: f(V) = slope * V + intercept
        slope, intercept = np.polyfit(vs, fs_mhz, 1)
        f_fit = slope * vs + intercept
        ss_res = float(np.sum((fs_mhz - f_fit) ** 2))
        ss_tot = float(np.sum((fs_mhz - np.mean(fs_mhz)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
        kvdd_175_185 = float((fs_mhz[-1] - fs_mhz[0]) / (vs[-1] - vs[0]))

        # Fold K_vdd with HV18 Kelvin LDO PSRR @ 20 MHz (above ~4-5 MHz PLL BW -> unattenuated by PLL!)
        # For sinusoidal supply ripple V_in_pp (e.g. 50 mVpp & 100 mVpp on VDD_HV33) at f_m = 20 MHz:
        #   V_ddq_pk = (V_in_pp / 2) * 10^(-PSRR_dB / 20)
        #   df_pk    = |K_vdd| * V_ddq_pk
        #   beta     = df_pk / f_m   [rad pk phase deviation]
        #   J_pp     = 2 * beta / (2*pi*f_vco) = df_pk / (pi * f_m * f_vco)
        #   J_rms    = J_pp / (2 * sqrt(2))
        #   Spur_dBc = 20 * log10(beta / 2)
        f_m = 20.0e6
        f_0 = float(fs_mhz[2] * 1e6)
        atten_20m = 10.0 ** (-psrr_20m_db / 20.0)
        kvdd_eff_20m = abs(float(slope)) * atten_20m  # effective MHz/V from VDD_HV33 @ 20 MHz
        fm_table = {}
        for vin_pp_mv in (50.0, 100.0):
            v_pk_nol = (vin_pp_mv * 1e-3) / 2.0
            v_pk_ldo = v_pk_nol * atten_20m
            df_pk_nol = abs(float(slope)) * 1e6 * v_pk_nol
            df_pk_ldo = abs(float(slope)) * 1e6 * v_pk_ldo
            j_pp_nol_fs = (df_pk_nol / (math.pi * f_m * f_0)) * 1e15
            j_pp_ldo_fs = (df_pk_ldo / (math.pi * f_m * f_0)) * 1e15
            j_rms_ldo_fs = j_pp_ldo_fs / (2.0 * math.sqrt(2.0))
            beta_ldo = df_pk_ldo / f_m
            spur_ldo_dbc = 20.0 * math.log10(max(1e-12, beta_ldo / 2.0))
            spur_nol_dbc = 20.0 * math.log10(max(1e-12, (df_pk_nol / f_m) / 2.0))
            fm_table[f"vin_{int(vin_pp_mv)}mvpp_20mhz"] = {
                "vin_pp_mv": vin_pp_mv,
                "vddq_pp_mv_with_ldo": round(vin_pp_mv * atten_20m, 4),
                "df_pk_khz_with_ldo": round(df_pk_ldo / 1e3, 3),
                "jitter_pp_fs_without_ldo": round(j_pp_nol_fs, 2),
                "jitter_pp_fs_with_ldo": round(j_pp_ldo_fs, 3),
                "jitter_rms_fs_with_ldo": round(j_rms_ldo_fs, 3),
                "jitter_pp_mui_5g_with_ldo": round(j_pp_ldo_fs / 200.0, 5),
                "fm_spur_dbc_without_ldo": round(spur_nol_dbc, 2),
                "fm_spur_dbc_with_ldo": round(spur_ldo_dbc, 2),
            }

        corners_out[ck] = {
            "lib": lib,
            "temp_c": tc,
            "code": 5,
            "vctrl_v": 0.84,
            "kvdd_fit_mhz_per_v": round(float(slope), 2),
            "kvdd_175_185_mhz_per_v": round(kvdd_175_185, 2),
            "fit_intercept_mhz": round(float(intercept), 3),
            "fit_r2": round(r2, 5),
            "f_1v80_ghz": pts[2]["f_vco_ghz"],
            "vpp_1v80_v": pts[2]["vpp_tank_v"],
            "ldo_psrr_20mhz_db": psrr_20m_db,
            "ldo_psrr_min_db": psrr_min_db,
            "eff_kvdd_from_hv33_20mhz_mhz_per_v": round(kvdd_eff_20m, 3),
            "supply_fm_20mhz": fm_table,
            "points": pts,
        }
        print(
            f"  [Char 2] {ck:7s}: f(1.75/1.80/1.85)={pts[0]['f_vco_ghz']:.4f}/{pts[2]['f_vco_ghz']:.4f}/{pts[4]['f_vco_ghz']:.4f} GHz | "
            f"K_vdd={slope:+.2f} MHz/V (R2={r2:.5f}) | LDO PSRR@20M={psrr_20m_db:.2f} dB -> "
            f"eff K_vdd={kvdd_eff_20m:.3f} MHz/V | 100mVpp@20MHz: Jpp={fm_table['vin_100mvpp_20mhz']['jitter_pp_fs_with_ldo']:.2f} fs "
            f"(vs {fm_table['vin_100mvpp_20mhz']['jitter_pp_fs_without_ldo']:.0f} fs raw), spur={fm_table['vin_100mvpp_20mhz']['fm_spur_dbc_with_ldo']:.1f} dBc",
            flush=True,
        )

    res = {
        "code": 5,
        "vctrl_v": 0.84,
        "vdd_q_sweep_v": list(VDD_SWEEP),
        "elapsed_s": round(elapsed, 1),
        "corners": corners_out,
    }
    cache_path.write_text(json.dumps(res, indent=2) + "\n")
    n_del = cleanup_raws(c_dir)
    print(f"[Char 2] DONE ({elapsed:.1f}s, deleted {n_del} .raw)", flush=True)
    return res


# =============================================================================
# Char 3: True Transistor-Level Closed-Loop 5G LC-PLL Lock & Reference Spur
# =============================================================================
PLL_CASES = {
    "as_built_4k13_200u": {
        "label": "As-Built Plan-C LF k4 (Rz=4.13 kΩ, 200 µA)",
        "short": "As-Built (4.13 kΩ / 200 µA)",
        "rz_kohm": 4.13,
        "icp_ua": 200.0,
        "ci_pf": 18.38,
        "third_order": False,
        "t_stop_ns": 720.0,
        "td_ref_ns": 0.720,
        "batch": "core",
    },
    "retuned_18k_200u": {
        "label": "Retuned Zero-CP-Change (Rz=18.0 kΩ, 200 µA)",
        "short": "Retuned-1 (18.0 kΩ / 200 µA)",
        "rz_kohm": 18.0,
        "icp_ua": 200.0,
        "ci_pf": 18.38,
        "third_order": False,
        "t_stop_ns": 650.0,
        "td_ref_ns": 1.315,
        "batch": "core",
    },
    "retuned_12k_400u": {
        "label": "Recommended Optimal (Rz=12.0 kΩ, 400 µA)",
        "short": "Retuned-2 (12.0 kΩ / 400 µA)",
        "rz_kohm": 12.0,
        "icp_ua": 400.0,
        "ci_pf": 18.38,
        "third_order": False,
        "t_stop_ns": 480.0,
        "td_ref_ns": 1.315,
        "batch": "opt",
    },
    "retuned_18k_200u_r3c3": {
        "label": "Retuned-1 + 3rd-Order Filter (18 kΩ + 2 kΩ/0.6 pF)",
        "short": "Retuned-1 + R3/C3 (2k/0.6p)",
        "rz_kohm": 18.0,
        "icp_ua": 200.0,
        "ci_pf": 18.38,
        "third_order": True,
        "t_stop_ns": 480.0,
        "td_ref_ns": 1.315,
        "batch": "opt",
    },
}


def ensure_overflow_safe_varactor(p_dir: Path) -> tuple[Path, Path]:
    """Generate IEEE-754 overflow-safe algebraic-identity copy of SKY130 cap_var_lvt for long closed-loop PLL runs.

    Replaces ONLY `log(cosh(u))` with the bit-equivalent algebraic identity
    `abs(u) + log(0.5 + 0.5*exp(-2*abs(u)))` so large Newton trial steps never overflow IEEE-754 cosh(710).
    Verified on standalone 5 GHz LC-VCO: f_orig=5.006597 GHz vs f_safe=5.006618 GHz (4 ppm / 0.021 MHz).
    """
    var_out = p_dir / "cap_var_lvt_safe.spice"
    oct_out = p_dir / "lc_5g_div2_oct_safe.spice"
    if not var_out.exists():
        src = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_var_lvt.model.spice").read_text()
        old_q = (
            "cnwvc_slope1*log(cosh((v(c0)-v(p2)-cnwvc_vt1)/cnwvc_slope1))"
            "+0.9*cnwvc_slope2*log(cosh((v(c0)-v(p2)-cnwvc_vt2)/cnwvc_slope2))"
        )
        u1 = "((v(c0)-v(p2)-cnwvc_vt1)/cnwvc_slope1)"
        u2 = "((v(c0)-v(p2)-cnwvc_vt2)/cnwvc_slope2)"
        new_q = (
            f"cnwvc_slope1*(abs({u1})+log(0.5+0.5*exp(-2*abs({u1}))))"
            f"+0.9*cnwvc_slope2*(abs({u2})+log(0.5+0.5*exp(-2*abs({u2}))))"
        )
        assert old_q in src, "Expected log(cosh) expression not found in PDK cap_var_lvt model"
        safe_txt = (
            src.replace(".subckt  sky130_fd_pr__cap_var_lvt ", ".subckt  sky130_fd_pr__cap_var_lvt_safe ")
               .replace(".ends sky130_fd_pr__cap_var_lvt", ".ends sky130_fd_pr__cap_var_lvt_safe")
               .replace(old_q, new_q)
        )
        var_out.write_text(safe_txt)
    if not oct_out.exists():
        oct_src = OCT_SPICE.read_text()
        oct_out.write_text(oct_src.replace("sky130_fd_pr__cap_var_lvt", "sky130_fd_pr__cap_var_lvt_safe"))
    return var_out, oct_out


def build_pll_lf_subckt(case_key: str, cfg: dict) -> tuple[str, str]:
    """Build exact PDK loop-filter subcircuit (same 18x 22.1965 um MIM Ci as pll_loop_filter_k4)."""
    rz = cfg["rz_kohm"]
    if abs(rz - 4.13) < 0.05:
        rz_lines = ["Xrz lf_ctrl z vss sky130_fd_pr__res_high_po_0p69 l=7.594"]
    elif abs(rz - 12.0) < 0.05:
        # Pilot-verified: l=23.655 -> 12.020 kOhm at TT 27C
        rz_lines = ["Xrz lf_ctrl z vss sky130_fd_pr__res_high_po_0p69 l=23.655"]
    elif abs(rz - 18.0) < 0.05:
        # Pilot-verified: 2x l=17.533 -> 18.018 kOhm at TT 27C
        rz_lines = [
            "Xrza lf_ctrl rz_mid vss sky130_fd_pr__res_high_po_0p69 l=17.533",
            "Xrzb rz_mid z vss sky130_fd_pr__res_high_po_0p69 l=17.533",
        ]
    else:
        raise ValueError(f"Unsupported Rz: {rz}")

    cside = "22.1965"
    cap_lines = [f"Xcg{k:02d} z vss sky130_fd_pr__cap_mim_m3_1 w={cside} l={cside}" for k in range(6)]
    cap_lines += [f"Xcv{k:02d} z vdd sky130_fd_pr__cap_mim_m3_1 w={cside} l={cside}" for k in range(12)]

    if cfg["third_order"]:
        # 3rd-order spur-filtering RC pole right before VCO varactor: R3 = 2.0 kOhm (l=3.247), C3 = 0.55 pF MIM (+55 fF varactor/routing = 0.60 pF)
        out_lines = [
            "Xr3 lf_ctrl ctrl vss sky130_fd_pr__res_high_po_0p69 l=3.247",
            "Xc3 ctrl vss sky130_fd_pr__cap_mim_m3_1 w=16.5 l=16.5",
            "Xfast2 pre_ref ctrl pre_en pre_b vdd vss pll_lf_tgate_lvt wn=4 wp=8",
        ]
    else:
        out_lines = ["Vout_link lf_ctrl ctrl 0"]

    name = f"pll_lf_5g_{case_key}"
    subckt = "\n".join([
        f".subckt {name} cp_in ctrl z pre_ref pre_en vdd vss",
        "Vlink cp_in lf_ctrl 0",
        *rz_lines,
        *cap_lines,
        "Xinv pre_en pre_b vdd vss serdes_cmos_inv wn=4 wp=8",
        "Xfast pre_ref lf_ctrl pre_en pre_b vdd vss pll_lf_tgate_lvt wn=4 wp=8",
        "Xint pre_ref z pre_en pre_b vdd vss pll_lf_tgate_lvt wn=8 wp=16",
        *out_lines,
        f".ends {name}",
    ])
    return name, subckt


def build_pll_deck(
    case_key: str,
    cfg: dict,
    var_safe_path: Path,
    oct_safe_path: Path,
    vpre: float = 0.720,
    td_ref_ns: float = 1.315,
) -> str:
    lf_name, lf_subckt = build_pll_lf_subckt(case_key, cfg)
    t_stop_ns = cfg["t_stop_ns"]
    # Exact 2x parallel CP v4 sizing for 400 uA (identical Vdsat & servo matching!)
    cp_params = (
        "wn=40 wp=224 wsn=16 wsp=48 pnf=32 nnf=8 up_wn=8.0 up_wp=24.0 dn_wn=8 dn_wp=16"
        if cfg["icp_ua"] > 300.0 else ""
    )
    cp_vc = "140f" if cfg["third_order"] else "200f"
    cp_vco_ctrl = "55f" if cfg["third_order"] else "0f"
    extra_c = f"Cp_cpo cpo 0 {cp_vc}\nCp_vco_vc ctrl 0 {cp_vco_ctrl}" if cfg["third_order"] else f"Cp_vc ctrl 0 {cp_vc}"

    return "\n".join([
        f"* Closed-Loop 5G Type-II LC-PLL Transient: {cfg['label']} (TT 27C 1.8V, N=20)",
        f'.lib "{PDK_LIB}" tt',
        f'.include "{PRIM_SPICE}"',
        f'.include "{PFET_LVT_SPICE}"',
        f'.include "{CMOS_SPICE}"',
        f'.include "{SC_LIB}"',
        f'.include "{C2C_BASE}"',
        f'.include "{C2C_R4}"',
        f'.include "{C2C_R5}"',
        f'.include "{BIAS_V2}"',
        f'.include "{var_safe_path}"',
        f'.include "{oct_safe_path}"',
        f'.include "{DIV_AB}"',
        f'.include "{PFD_SC}"',
        f'.include "{CP_V4}"',
        f'.include "{LF_PRE}"',
        lf_subckt,
        "",
        "Vdd vdd 0 1.800000",
        "* Nominal BIAS v2 currents for CP v4 (50 uA -> 200/400 uA) & r5 CML->CMOS (212.5 uA)",
        "Icp_ref vdd vbn 50u",
        "Xdcp vbn vbp vdd 0 serdes_bias_cp_v2",
        "Cvbn vbn 0 2p",
        "Cvbp vbp vdd 2p",
        "Icp_ota vdd ib_cp 10u",
        "Cibcp ib_cp 0 1p",
        "Icml_ref vdd vbias_cml 212.5u",
        "Xdcml vbias_cml vbias_cml 0 0 serdes_nfet w=5 l=0.5",
        "Cvcml vbias_cml 0 2p",
        "",
        f"* 250 MHz reference clock (phase-aligned to fb250 at t=20 ns PFD release -> pure -120 mV freq step!)",
        f"Vref ref 0 PULSE(0 1.8 {td_ref_ns:.3f}n 40p 40p 1.96n 4.0n)",
        f"Vpre_ref pre_ref 0 {vpre:.4f}",
        "Vpre_en pre_en 0 PWL(0 1.8 18n 1.8 18.2n 0)",
        "Vrst_pfd rst_b 0 PWL(0 0 20n 0 20.05n 1.8)",
        "Vrst_div div_rst_n 0 PWL(0 0 8n 0 8.05n 1.8)",
        "Vmode mode_5g 0 1.8",
        "",
        "* VCO coarse bank code = 5 (0b0101 -> locks at 5.000 GHz near Vctrl = 0.84 V)",
        "Vb0 b0 0 1.8",
        "Vb1 b1 0 0.0",
        "Vb2 b2 0 1.8",
        "Vb3 b3 0 0.0",
        "",
        "* Full Transistor-Level 5G LC-PLL Loop (N = 2 x 10 = 20)",
        "Xpfd ref fb250 rst_b up dn vdd 0 pll_pfd_sc_dly",
        f"Xcp up dn cpo vbn vbp ib_cp vdd 0 pll_cp_steer_v4 {cp_params}",
        f"Xlf cpo ctrl z pre_ref pre_en vdd 0 {lf_name}",
        "Xvco vp vn ip in qp qn ctrl b0 b1 b2 b3 vdd 0 vco5g_lc_div2_oct_pdk",
        "* Match Magic CPEX vp/vn tank capacitance so code=5 hits 5.000 GHz @ Vctrl~0.84 V",
        "Cp_vp vp 0 109.0f",
        "Cp_vn vn 0 109.0f",
        extra_c,
        "Cqp qp 0 30f",
        "Cqn qn 0 30f",
        "Xc2c ip in ck2p5_p ck2p5_n vbias_cml vdd 0 serdes_cml_to_cmos_r5",
        "Xdiv ck2p5_p ck2p5_n mode_5g div_rst_n fb250 fb250_b vdd 0 pll_div_ab_5g_v2",
        "Cfb_b fb250_b 0 15f",
        "",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 80u 0.26n 80u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 3.5n 0 3.51n 60u 3.56n 60u 3.57n 0)",
        "",
        f".nodeset v(xvco.xcore.xvarp.p2)={vpre:.4f} v(xvco.xcore.xvarn.p2)={vpre:.4f} "
        f"v(ctrl)={vpre:.4f} v(cpo)={vpre:.4f} v(z)={vpre:.4f} v(xcp.rep)={vpre:.4f} v(xcp.dum)={vpre:.4f}",
        ".temp 27",
        # Strict SPARSE trap 6p with overflow-safe algebraic-identity cap_var_lvt (NO klu, NO cshunt!)
        ".options reltol=6e-4 abstol=2p vntol=2u sparse trtol=7 itl4=100 method=trap",
        ".save v(vp) v(vn) v(fb250) v(ref) v(up) v(dn) v(ctrl) v(z) i(Vdd)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 6p {t_stop_ns:.1f}n 0 6p",
        "write pll.raw v(vp) v(vn) v(fb250) v(ref) v(up) v(dn) v(ctrl) v(z) i(Vdd)",
        "quit",
        ".endc",
        ".end",
        "",
    ])


def boxcar_smooth_uniform(t: np.ndarray, y: np.ndarray, dt_u: float, win_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Resample onto uniform grid dt_u and boxcar-average over win_s (e.g., 0.2 ns = 1 VCO period,
    exact spectral null at 5 GHz & 10 GHz varactor 2f0 feedthrough while preserving 250 MHz ripple!)."""
    t0, t1 = float(t[0]), float(t[-1])
    tu = np.arange(t0, t1, dt_u)
    yu = np.interp(tu, t, y)
    k = max(1, int(round(win_s / dt_u)))
    if k <= 1:
        return tu, yu
    cs = np.cumsum(np.insert(yu, 0, 0.0))
    ym = (cs[k:] - cs[:-k]) / k
    tm = tu[k // 2: k // 2 + len(ym)]
    return tm, ym


def extract_tone_detrended_mv(t: np.ndarray, y: np.ndarray, f_tone: float = FREF, n_cyc: int = 10) -> tuple[float, float, np.ndarray, np.ndarray]:
    """Extract linear-detrended 250 MHz fundamental amplitude (mV_pk) and harmonics over last n_cyc periods."""
    t1 = float(t[-1])
    t0 = t1 - n_cyc / f_tone
    nu = n_cyc * 256
    tu = np.linspace(t0, t1, nu, endpoint=False)
    yu = np.interp(tu, t, y)
    # Remove linear trend so slow residual loop settling (e.g. underdamped Case A) does not leak into 250 MHz bin
    p = np.polyfit(tu - t0, yu, 1)
    yd = yu - np.polyval(p, tu - t0)
    c1 = 2.0 * np.mean(yd * np.exp(-2j * np.pi * f_tone * (tu - t0)))
    c2 = 2.0 * np.mean(yd * np.exp(-2j * np.pi * (2.0 * f_tone) * (tu - t0)))
    return float(np.abs(c1) * 1e3), float(np.abs(c2) * 1e3), tu, yd


def analyze_pll_raw(raw_path: Path, cfg: dict, kvco_hz_v: float, v_init: float = 0.720, t_rel_s: float = 20.0e-9) -> tuple[dict, dict]:
    w = spice.Waves(raw_path)
    t = w.t
    t_stop = cfg["t_stop_ns"] * 1e-9
    assert float(t[-1]) >= t_stop * 0.99, f"truncated PLL raw {raw_path}: {t[-1]*1e9:.2f}ns < {cfg['t_stop_ns']}ns"

    ctrl = w["v(ctrl)"]
    zv = w["v(z)"]
    vdiff = w["v(vp)"] - w["v(vn)"]
    fb = w["v(fb250)"]
    ref = w["v(ref)"]
    up = w["v(up)"]
    dn = w["v(dn)"]
    idd = -w["i(vdd)"]

    # 1) 1-VCO-cycle (0.2 ns) smoothed Vctrl at dt_u=5 ps (fs=200 GHz >> 10 GHz 2f0 feedthrough -> ZERO aliasing!)
    t_sm, ctrl_sm = boxcar_smooth_uniform(t, ctrl, dt_u=5.0e-12, win_s=0.20e-9)
    # 2) 1-Ref-cycle (4.0 ns) macroscopic loop envelope computed DIRECTLY on the 200 GHz grid (exact null at
    #    250 MHz, 5 GHz, AND 10 GHz — zero aliasing!), then decimated to 1.0 ns for compact trace storage!
    k_ref = int(round(4.0e-9 / 5.0e-12))  # 800 samples = 4.000 ns
    cs_c = np.cumsum(np.insert(ctrl_sm, 0, 0.0))
    ctrl_env_hi = (cs_c[k_ref:] - cs_c[:-k_ref]) / k_ref
    t_env_hi = t_sm[k_ref // 2: k_ref // 2 + len(ctrl_env_hi)]
    stride_1ns = 200  # 200 * 5 ps = 1.0 ns
    t_env = t_env_hi[::stride_1ns]
    ctrl_env = ctrl_env_hi[::stride_1ns]

    t_zsm, z_sm = boxcar_smooth_uniform(t, zv, dt_u=5.0e-12, win_s=0.20e-9)
    cs_z = np.cumsum(np.insert(z_sm, 0, 0.0))
    z_env_hi = (cs_z[k_ref:] - cs_z[:-k_ref]) / k_ref
    t_zenv_hi = t_zsm[k_ref // 2: k_ref // 2 + len(z_env_hi)]
    t_zenv = t_zenv_hi[::stride_1ns]
    z_env = z_env_hi[::stride_1ns]

    # Pre-release VCO frequency (14..18 ns, during precharge at 0.720 V)
    m_pre = (t >= 14.0e-9) & (t <= 18.0e-9)
    tx_pre = rising_crossings(t[m_pre], vdiff[m_pre], 0.0)
    f_init_ghz = float(1.0 / np.median(np.diff(tx_pre)) / 1e9) if len(tx_pre) >= 4 else float("nan")

    # Instantaneous VCO frequency envelope (computed in 4 ns windows = 20 VCO cycles each)
    f_win_t, f_win_ghz = [], []
    for ts in np.arange(12.0e-9, t[-1] - 4.0e-9 + 1e-12, 4.0e-9):
        mw = (t >= ts) & (t <= ts + 4.0e-9)
        tx = rising_crossings(t[mw], vdiff[mw], 0.0)
        if len(tx) >= 5:
            f_win_t.append((ts + 2.0e-9) * 1e9)
            f_win_ghz.append(float((len(tx) - 1) / (tx[-1] - tx[0]) / 1e9))
    f_win_t_arr = np.array(f_win_t)
    f_win_ghz_arr = np.array(f_win_ghz)

    # Steady-state window: last 40 ns (10 reference cycles) on uniform 200 GHz grid (unbiased by adaptive dt)
    t_ss0 = float(t_sm[-1]) - 40.0e-9
    m_sm_ss = t_sm >= t_ss0
    vctrl_ss_mean = float(np.mean(ctrl_sm[m_sm_ss]))
    z_ss_mean = float(np.mean(z_sm[t_zsm >= t_ss0]))

    # Final locked frequency over last 80 ns (20 ref cycles)
    t_f0 = float(t[-1]) - 80.0e-9
    m_f = t >= t_f0
    tx_ss = rising_crossings(t[m_f], vdiff[m_f], 0.0)
    f_final_ghz = float((len(tx_ss) - 1) / (tx_ss[-1] - tx_ss[0]) / 1e9)
    f_err_ppm = (f_final_ghz / 5.0 - 1.0) * 1e6

    # Static phase error over last 80 ns (fb250 - ref) + UP/DN pulse widths
    ref_e = rising_crossings(t[m_f], ref[m_f], 0.9)
    fb_e = rising_crossings(t[m_f], fb[m_f], 0.9)
    pe_list = []
    for re_t in ref_e:
        if len(fb_e):
            d = fb_e - re_t
            idx = int(np.argmin(np.abs(d)))
            if abs(d[idx]) < TREF * 0.45:
                pe_list.append(float(d[idx] * 1e12))
    static_pe_ps = float(np.mean(pe_list)) if pe_list else float("nan")
    static_pe_pp_ps = float(np.ptp(pe_list)) if pe_list else float("nan")

    up_pw = pulse_widths_ps(t[m_f], up[m_f], 0.9)
    dn_pw = pulse_widths_ps(t[m_f], dn[m_f], 0.9)
    up_dn_diff_ps = float(up_pw["mean_ps"] - dn_pw["mean_ps"])

    # 250 MHz steady-state Vctrl ripple & Reference Spur!
    # Raw & 1-VCO-cycle smoothed (removes 10 GHz 2f0 varactor feedthrough, preserves 250 MHz..2 GHz CP spikes)
    v250_pk_mv, v500_pk_mv, _, _ = extract_tone_detrended_mv(t, ctrl, FREF, n_cyc=10)
    # Detrended 20 ns (5 ref cycles) zoomed ripple trace for Panel (d)
    t_z0 = float(t_sm[-1]) - 20.0e-9
    m_z20 = t_sm >= t_z0
    t_rip_ns = (t_sm[m_z20] - t_z0) * 1e9
    y_rip_raw = ctrl_sm[m_z20]
    p_lin = np.polyfit(t_rip_ns, y_rip_raw, 1)
    y_rip_ac_mv = (y_rip_raw - np.polyval(p_lin, t_rip_ns)) * 1e3
    vctrl_ripple_250m_mvpp = float(np.ptp(y_rip_ac_mv))
    vctrl_raw_pp_mv = float(np.ptp(ctrl[t >= t[-1] - 20.0e-9]) * 1e3)
    z_ripple_mvpp = float(np.ptp(zv[t >= t[-1] - 20.0e-9] - np.polyval(np.polyfit(t[t >= t[-1] - 20.0e-9], zv[t >= t[-1] - 20.0e-9], 1), t[t >= t[-1] - 20.0e-9])) * 1e3)

    # FM narrowband reference spur at +/- 250 MHz: 20*log10(Kvco * V_rip_250M_pk / (2 * f_ref))
    spur_250m_dbc = float(20.0 * math.log10(max(1e-12, kvco_hz_v * (v250_pk_mv * 1e-3) / (2.0 * FREF))))
    spur_500m_dbc = float(20.0 * math.log10(max(1e-12, kvco_hz_v * (v500_pk_mv * 1e-3) / (2.0 * 2.0 * FREF))))

    # Initial phase alignment check right after t_release = 20 ns
    ref_20 = rising_crossings(t[t >= 19.5e-9], ref[t >= 19.5e-9], 0.9)
    fb_20 = rising_crossings(t[t >= 19.5e-9], fb[t >= 19.5e-9], 0.9)
    init_pe_ps = float((fb_20[0] - ref_20[0]) * 1e12) if (len(ref_20) and len(fb_20)) else float("nan")

    # Peak & trough on macroscopic 4-ns loop envelope after t_release
    m_acq = t_env >= t_rel_s
    t_acq = t_env[m_acq]
    c_acq = ctrl_env[m_acq]
    i_pk = int(np.argmax(c_acq))
    v_pk = float(c_acq[i_pk])
    t_pk_rel_ns = float((t_acq[i_pk] - t_rel_s) * 1e9)
    # Trough after peak
    c_after = c_acq[i_pk:]
    t_after = t_acq[i_pk:]
    i_mn = int(np.argmin(c_after))
    v_trough = float(c_after[i_mn])
    t_trough_rel_ns = float((t_after[i_mn] - t_rel_s) * 1e9)

    itot_ma = float(np.mean(idd[t >= t_ss0]) * 1e3)

    metrics = {
        "label": cfg["label"],
        "short": cfg["short"],
        "rz_kohm": cfg["rz_kohm"],
        "icp_ua": cfg["icp_ua"],
        "ci_pf": cfg["ci_pf"],
        "third_order": cfg["third_order"],
        "t_stop_ns": cfg["t_stop_ns"],
        "v_init_v": v_init,
        "f_init_ghz": round(f_init_ghz, 5),
        "init_df_mhz": round((f_init_ghz - 5.0) * 1e3, 2),
        "init_pe_fb_minus_ref_ps": round(init_pe_ps, 1),
        "vctrl_ss_mean_v": round(vctrl_ss_mean, 5),
        "z_ss_mean_v": round(z_ss_mean, 5),
        "v_peak_v": round(v_pk, 5),
        "t_peak_rel_ns": round(t_pk_rel_ns, 1),
        "v_trough_after_peak_v": round(v_trough, 5),
        "t_trough_rel_ns": round(t_trough_rel_ns, 1),
        "f_final_ghz": round(f_final_ghz, 6),
        "f_err_ppm": round(f_err_ppm, 1),
        "static_pe_fb_ref_ps": round(static_pe_ps, 2),
        "static_pe_pp_ps": round(static_pe_pp_ps, 2),
        "up_pw_mean_ps": round(up_pw["mean_ps"], 2),
        "dn_pw_mean_ps": round(dn_pw["mean_ps"], 2),
        "up_dn_diff_ps": round(up_dn_diff_ps, 2),
        "vctrl_ripple_mvpp": round(vctrl_ripple_250m_mvpp, 3),
        "vctrl_raw_with_10g_mvpp": round(vctrl_raw_pp_mv, 2),
        "z_ripple_mvpp": round(z_ripple_mvpp, 3),
        "vctrl_250m_pk_mv": round(v250_pk_mv, 4),
        "vctrl_500m_pk_mv": round(v500_pk_mv, 4),
        "spur_250m_dbc": round(spur_250m_dbc, 2),
        "spur_500m_dbc": round(spur_500m_dbc, 2),
        "itot_pll_ma": round(itot_ma, 2),
        "p_pll_mw": round(itot_ma * 1.8, 2),
    }

    traces = {
        "t_env_ns": t_env * 1e9,
        "ctrl_env_v": ctrl_env,
        "t_zenv_ns": t_zenv * 1e9,
        "z_env_v": z_env,
        "f_win_t_ns": f_win_t_arr,
        "f_win_ghz": f_win_ghz_arr,
        "t_rip_ns": t_rip_ns,
        "y_rip_ac_mv": y_rip_ac_mv,
    }
    return metrics, traces


def finalize_pll_metrics(cases_metrics: dict, traces_map: dict, v_init: float = 0.720, t_rel_ns: float = 20.0) -> None:
    """Compute exact apples-to-apples overshoot % and settling times using equilibrium V_lock from longest settled case."""
    # Equilibrium lock voltage V_eq from longest settled identical-load 2nd-order run (`retuned_18k_200u`, 650 ns),
    # corrected for its tiny +99 ppm (+0.49 MHz) residual tail via measured Kvco = 141.3 MHz/V
    if "retuned_18k_200u" in cases_metrics:
        m_ref = cases_metrics["retuned_18k_200u"]
        v_eq = float(m_ref["vctrl_ss_mean_v"] - (m_ref["f_final_ghz"] - 5.0) / 0.1413)
    elif "retuned_12k_400u" in cases_metrics:
        m_ref = cases_metrics["retuned_12k_400u"]
        v_eq = float(m_ref["vctrl_ss_mean_v"] - (m_ref["f_final_ghz"] - 5.0) / 0.1413)
    else:
        v_eq = 0.8585

    dv_step = max(0.02, v_eq - v_init)
    for k, m in cases_metrics.items():
        tr = traces_map[k]
        t_env = tr["t_env_ns"]
        c_env = tr["ctrl_env_v"]
        f_t = tr["f_win_t_ns"]
        f_g = tr["f_win_ghz"]

        ov_pct = max(0.0, (m["v_peak_v"] - v_eq) / dv_step * 100.0)
        un_pct = max(0.0, (v_eq - m["v_trough_after_peak_v"]) / dv_step * 100.0)

        mask_acq = t_env >= t_rel_ns
        ta = t_env[mask_acq]
        ca = c_env[mask_acq]
        out_5mv = np.where(np.abs(ca - v_eq) > 0.005)[0]
        if len(out_5mv) == 0:
            t_set_5mv = 0.0
            settled_5mv = True
        elif out_5mv[-1] == len(ta) - 1:
            t_set_5mv = float(ta[-1] - t_rel_ns)
            settled_5mv = False
        else:
            t_set_5mv = float(ta[out_5mv[-1]] - t_rel_ns)
            settled_5mv = True

        # Frequency settling within +/- 50 ppm (+/- 0.25 MHz around 5.000 GHz) and +/- 200 ppm (+/- 1.0 MHz)
        mf = f_t >= t_rel_ns
        ft = f_t[mf]
        fg = f_g[mf]
        out_50ppm = np.where(np.abs((fg / 5.0 - 1.0) * 1e6) > 50.0)[0]
        if len(out_50ppm) == 0:
            t_set_50ppm = 0.0
            settled_50ppm = True
        elif out_50ppm[-1] == len(ft) - 1:
            t_set_50ppm = float(ft[-1] - t_rel_ns)
            settled_50ppm = False
        else:
            t_set_50ppm = float(ft[out_50ppm[-1]] - t_rel_ns)
            settled_50ppm = True

        m["v_eq_lock_v"] = round(v_eq, 5)
        m["step_dv_mv"] = round(dv_step * 1e3, 2)
        m["overshoot_pct"] = round(ov_pct, 1)
        m["undershoot_pct"] = round(un_pct, 1)
        m["settle_5mv_ns"] = round(t_set_5mv, 1)
        m["settled_5mv_within_window"] = settled_5mv
        m["settle_50ppm_ns"] = round(t_set_50ppm, 1)
        m["settled_50ppm_within_window"] = settled_50ppm


def run_char3_pll(out_root: Path, workers: int, kvco_hz_v: float, batches: tuple[str, ...]) -> tuple[dict, dict]:
    p_dir = out_root / "char3_pll"
    p_dir.mkdir(parents=True, exist_ok=True)
    cache_json = p_dir / "char3_summary.json"
    cache_npz = p_dir / "char3_traces.npz"

    cases_metrics = json.loads(cache_json.read_text()).get("cases", {}) if cache_json.exists() else {}
    traces_map: dict[str, dict[str, np.ndarray]] = {}
    if cache_npz.exists():
        npz = np.load(cache_npz)
        for full_k in npz.files:
            ck, field = full_k.split("__", 1)
            traces_map.setdefault(ck, {})[field] = npz[full_k]

    for batch_name in batches:
        batch_keys = [k for k, v in PLL_CASES.items() if v["batch"] == batch_name and k not in cases_metrics]
        if not batch_keys:
            print(f"[Char 3/{batch_name}] All cases cached.", flush=True)
            continue

        var_safe_path, oct_safe_path = ensure_overflow_safe_varactor(p_dir)
        jobs = []
        dir_to_ck: dict[str, str] = {}
        for ck in batch_keys:
            cfg = PLL_CASES[ck]
            deck = build_pll_deck(ck, cfg, var_safe_path, oct_safe_path, td_ref_ns=cfg.get("td_ref_ns", 1.315))
            rdir = spice.next_run_dir(p_dir, ck)
            dir_to_ck[rdir.name] = ck
            jobs.append((deck, rdir, dict(timeout_s=3600, meta={"stage": "char3", "case": ck})))

        w = check_worker_budget(workers)
        print(f"[Char 3/{batch_name}] Launching {batch_keys} (workers={w})...", flush=True)
        t0 = time.time()
        for ex in spice.run_many(jobs, workers=w, smoke=False):
            ck = dir_to_ck[ex.run_dir.name]
            print(f"  [Char 3] {ck}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fails={ex.log_failures[:2]}", flush=True)
            if not ex.ok:
                raise RuntimeError(f"Char 3 failed on {ck}: {ex.log_failures[:3]}")
            m, tr = analyze_pll_raw(ex.run_dir / "pll.raw", PLL_CASES[ck], kvco_hz_v=kvco_hz_v)
            m["elapsed_s"] = round(ex.elapsed_s, 1)
            cases_metrics[ck] = m
            traces_map[ck] = tr
            # Immediately delete large pll.raw after extracting compact traces & metrics!
            cleanup_raws(ex.run_dir)

        finalize_pll_metrics(cases_metrics, traces_map)
        flat_npz = {}
        for ck, tr in traces_map.items():
            for field, arr in tr.items():
                flat_npz[f"{ck}__{field}"] = arr
        np.savez_compressed(cache_npz, **flat_npz)
        cache_json.write_text(json.dumps({
            "kvco_used_mhz_per_v": round(kvco_hz_v / 1e6, 1),
            "v_init_v": 0.720,
            "t_release_ns": 20.0,
            "cases": cases_metrics,
        }, indent=2) + "\n")

        for ck in batch_keys:
            m = cases_metrics[ck]
            s5 = f"{m['settle_5mv_ns']:.0f} ns" if m["settled_5mv_within_window"] else f">{m['settle_5mv_ns']:.0f} ns"
            s50 = f"{m['settle_50ppm_ns']:.0f} ns" if m["settled_50ppm_within_window"] else f">{m['settle_50ppm_ns']:.0f} ns"
            print(
                f"  [Char 3] {ck:22s}: f={m['f_final_ghz']:.6f} GHz ({m['f_err_ppm']:+.1f} ppm) | "
                f"OV={m['overshoot_pct']:4.1f}% (pk@{m['t_peak_rel_ns']:.0f}ns) UN={m['undershoot_pct']:4.1f}% | "
                f"t_set(±5mV)={s5} t_set(±50ppm)={s50} | rip={m['vctrl_ripple_mvpp']:.2f} mVpp "
                f"(250M={m['vctrl_250m_pk_mv']:.3f} mVpk -> {m['spur_250m_dbc']:.1f} dBc) | PE={m['static_pe_fb_ref_ps']:+.1f} ps",
                flush=True,
            )

    finalize_pll_metrics(cases_metrics, traces_map)
    return {"kvco_used_mhz_per_v": round(kvco_hz_v / 1e6, 1), "v_init_v": 0.720, "t_release_ns": 20.0, "cases": cases_metrics}, traces_map


# =============================================================================
# Publication-Grade 240-DPI 2x2 Figure (Zero Text/Curve Overlap!)
# =============================================================================
def make_figure(summary: dict, traces: dict, fig_path: Path) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.5,
        "axes.titlesize": 9.8,
        "axes.labelsize": 8.8,
        "xtick.labelsize": 8.0,
        "ytick.labelsize": 8.0,
        "legend.fontsize": 7.4,
        "axes.spines.top": True,
        "axes.spines.right": True,
    })

    fig = plt.figure(figsize=(14.8, 10.4), dpi=240, facecolor="white")
    outer = gridspec.GridSpec(2, 2, figure=fig, left=0.06, right=0.97, top=0.905, bottom=0.06, wspace=0.23, hspace=0.29)

    c1 = summary["char1_codes16"]
    c2 = summary["char2_kvdd"]
    c3 = summary["char3_pll"]["cases"]

    # -------------------------------------------------------------------------
    # Panel (a): Full 16-Code (c0..c15) LC-VCO CPEX Tuning & Overlap Map
    # -------------------------------------------------------------------------
    ax_a = fig.add_subplot(outer[0, 0])
    cmap = plt.cm.viridis(np.linspace(0.05, 0.92, 16))
    vs = np.array(c1["vctrl_sweep_v"])
    v_dense = np.linspace(vs[0], vs[-1], 60)

    # Shaded overlap bands between every adjacent pair (c_k, c_{k+1})
    for ov in c1["overlaps"]:
        f_bot = ov["f_low_edge_of_hi_code_ghz"]
        f_top = ov["f_high_edge_of_lo_code_ghz"]
        if f_top > f_bot:
            ax_a.axhspan(f_bot, f_top, color="#2ca02c", alpha=0.11, lw=0)

    for row in c1["codes"]:
        code = row["code"]
        fs = np.array([row["f_lo_ghz"], row["f_mid_ghz"], row["f_hi_ghz"]])
        # Smooth quadratic fit through the 3 measured CPEX points
        poly = np.polyfit(vs, fs, 2)
        lw = 2.2 if code == 5 else 1.25
        col = "#d62728" if code == 5 else cmap[code]
        zord = 6 if code == 5 else 4
        ax_a.plot(v_dense, np.polyval(poly, v_dense), color=col, lw=lw, zorder=zord)
        ax_a.scatter(vs, fs, color=col, s=18 if code == 5 else 10, zorder=zord + 1, edgecolors="none")
        # Label every other code cleanly on the right edge (plus c5/c15 highlighted on left!)
        if code in (0, 2, 4, 6, 8, 10, 12):
            kw = dict(bbox=dict(boxstyle="round,pad=0.10", facecolor="white", edgecolor="none", alpha=0.88)) if code == 6 else {}
            ax_a.text(1.47, fs[2], f"c{code}", va="center", ha="left", fontsize=7.1,
                      color="#333333", fontweight="bold", zorder=8, **kw)
        if code == 15:
            ax_a.text(0.325, fs[0], "c15", va="center", ha="right", fontsize=7.1,
                      color="#333333", fontweight="bold")
        if code == 5:
            ax_a.text(0.325, fs[0], "c5 (5G)", va="center", ha="right", fontsize=7.3,
                      color="#d62728", fontweight="bold")

    ax_a.axhline(5.000, color="#111111", ls="--", lw=1.1, zorder=5)
    ax_a.text(0.225, 5.012, "5.000 GHz", fontsize=7.3, fontweight="bold", color="#111111", ha="left", va="bottom",
              bbox=dict(boxstyle="round,pad=0.14", facecolor="white", edgecolor="none", alpha=0.88), zorder=8)
    ax_a.axvline(c1["vctrl_5ghz_c5_v"], color="#d62728", ls=":", lw=0.95, alpha=0.75)
    ax_a.scatter([c1["vctrl_5ghz_c5_v"]], [5.000], color="#d62728", s=46, marker="*", zorder=8)

    ax_a.set_xlim(0.21, 1.59)
    ax_a.set_ylim(4.36, 5.47)
    ax_a.set_xlabel("Control Voltage $V_{ctrl}$ (V)")
    ax_a.set_ylabel("VCO Frequency $f_{VCO}$ (GHz)")
    ax_a.set_title("(a) 16-Code (c0–c15) CPEX Tuning & Overlap Map (TT 27°C, 1.8 V)", fontweight="bold", pad=6)
    ax_a.grid(True, alpha=0.28, ls="-", lw=0.6)

    # Clean callout box in lower-right white space (below c15 curve / right side where curves drop!)
    box_a = (
        f"100% Monotonic | 15/15 Overlap\n"
        f"Span: {c1['f_min_ghz']:.3f}–{c1['f_max_ghz']:.3f} GHz (0 dead-bands)\n"
        f"Min/Max Overlap: {c1['overlap_min_mhz']:.1f} / {c1['overlap_max_mhz']:.1f} MHz\n"
        f"Coarse Step: {c1['coarse_step_mean_mhz']:.1f} MHz | $K_{{VCO}}$: {c1['kvco_range_mhz_per_v'][0]:.0f}–{c1['kvco_range_mhz_per_v'][1]:.0f} MHz/V"
    )
    ax_a.text(
        0.98, 0.04, box_a, transform=ax_a.transAxes, ha="right", va="bottom",
        fontsize=7.3, linespacing=1.32,
        bbox=dict(boxstyle="round,pad=0.38", facecolor="#f4fbf4", edgecolor="#2ca02c", lw=0.9, alpha=0.95),
        zorder=9,
    )
    # Compact legend in upper-left empty corner (above c0 curve? Wait: c0 at V=0.35 is 5.27 GHz, so 5.36..5.47 at left is open!)
    leg_a = [
        Patch(facecolor="#2ca02c", alpha=0.22, edgecolor="#2ca02c", lw=0.5, label="Positive code overlap (15/15)"),
    ]
    ax_a.legend(handles=leg_a, loc="upper left", fontsize=7.3, framealpha=0.92, edgecolor="#cccccc")

    # -------------------------------------------------------------------------
    # Panel (b): Split Sub-panels: Top = Supply Pushing K_vdd (TT & SS+85),
    #            Bottom = I/Q Quadrature Phase Error & I_tot across all 16 codes
    # -------------------------------------------------------------------------
    sub_b = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=outer[0, 1], height_ratios=[1.15, 1.0], hspace=0.44)
    ax_b1 = fig.add_subplot(sub_b[0])
    ax_b2 = fig.add_subplot(sub_b[1])

    # Top (b1): K_vdd Supply Pushing
    tt2 = c2["corners"]["tt_27c"]
    ss2 = c2["corners"]["ss_p85c"]
    v_q = np.array(c2["vdd_q_sweep_v"])
    f_tt = np.array([p["f_vco_ghz"] * 1e3 for p in tt2["points"]])
    f_ss = np.array([p["f_vco_ghz"] * 1e3 for p in ss2["points"]])
    # Plot relative frequency shift df = f(VDD_Q) - f(1.80 V) in MHz so BOTH TT and SS+85 share a crisp zero-centered axis!
    df_tt = f_tt - f_tt[2]
    df_ss = f_ss - f_ss[2]
    v_line = np.linspace(1.745, 1.855, 50)
    fit_tt = tt2["kvdd_fit_mhz_per_v"] * (v_line - 1.80)
    fit_ss = ss2["kvdd_fit_mhz_per_v"] * (v_line - 1.80)

    ax_b1.axhline(0.0, color="#888888", ls=":", lw=0.8)
    ax_b1.axvline(1.80, color="#888888", ls=":", lw=0.8)
    ax_b1.plot(v_line, fit_tt, color="#1f77b4", lw=1.6, ls="-",
               label=f"TT 27°C: $K_{{VDD}}={tt2['kvdd_fit_mhz_per_v']:+.1f}$ MHz/V ($R^2={tt2['fit_r2']:.4f}$)")
    ax_b1.scatter(v_q, df_tt, color="#1f77b4", s=34, marker="o", zorder=5)
    ax_b1.plot(v_line, fit_ss, color="#d62728", lw=1.6, ls="--",
               label=f"SS +85°C hh: $K_{{VDD}}={ss2['kvdd_fit_mhz_per_v']:+.1f}$ MHz/V ($R^2={ss2['fit_r2']:.4f}$)")
    ax_b1.scatter(v_q, df_ss, color="#d62728", s=36, marker="s", zorder=5)

    ymin_b1 = min(float(np.min(df_tt)), float(np.min(df_ss)))
    ymax_b1 = max(float(np.max(df_tt)), float(np.max(df_ss)))
    pad_b1 = max(1.5, 0.35 * (ymax_b1 - ymin_b1))
    ax_b1.set_ylim(ymin_b1 - pad_b1 * 1.15, ymax_b1 + pad_b1 * 1.45)
    ax_b1.set_xlim(1.742, 1.858)
    ax_b1.set_xlabel("Quiet Rail $V_{DD,Q}$ (V)  [code=5, $V_{ctrl}=0.84$ V]")
    ax_b1.set_ylabel("$\\Delta f_{VCO}$ vs 1.80 V (MHz)")
    ax_b1.set_title("(b) CPEX Supply Pushing $K_{VDD}$ & All-Code I/Q Quadrature Error", fontweight="bold", pad=6)
    ax_b1.grid(True, alpha=0.28, lw=0.6)
    # Place legend & LDO jitter callout on opposite corners depending on slope sign!
    slope_pos = tt2["kvdd_fit_mhz_per_v"] >= 0
    leg_loc_b1 = "upper left" if slope_pos else "upper right"
    box_x, box_ha = (0.985, "right") if slope_pos else (0.015, "left")
    ax_b1.legend(loc=leg_loc_b1, fontsize=7.2, framealpha=0.93, edgecolor="#cccccc")
    fm_tt = tt2["supply_fm_20mhz"]["vin_100mvpp_20mhz"]
    fm_ss = ss2["supply_fm_20mhz"]["vin_100mvpp_20mhz"]
    ax_b1.text(
        box_x, 0.06,
        f"With HV18 Kelvin LDO (PSRR@20M: {tt2['ldo_psrr_20mhz_db']:.1f}/{ss2['ldo_psrr_20mhz_db']:.1f} dB):\n"
        f"100 mVpp@20MHz → $J_{{pp}}$={fm_tt['jitter_pp_fs_with_ldo']:.1f}/{fm_ss['jitter_pp_fs_with_ldo']:.1f} fs "
        f"(spur {fm_tt['fm_spur_dbc_with_ldo']:.0f}/{fm_ss['fm_spur_dbc_with_ldo']:.0f} dBc)",
        transform=ax_b1.transAxes, ha=box_ha, va="bottom", fontsize=6.9, linespacing=1.28,
        bbox=dict(boxstyle="round,pad=0.30", facecolor="#fffaf0", edgecolor="#d97706", lw=0.85, alpha=0.95),
    )

    # Bottom (b2): I/Q Quadrature Phase Error (ps) & Supply Current I_tot (mA) vs Code 0..15
    codes_x = np.array([r["code"] for r in c1["codes"]])
    q_mid = np.array([r["q_err_mid_ps"] for r in c1["codes"]])
    q_max = np.array([r["q_err_max_ps"] for r in c1["codes"]])
    itot_c = np.array([r["itot_mid_ma"] for r in c1["codes"]])

    ax_b2_r = ax_b2.twinx()
    bars = ax_b2.bar(codes_x, q_mid, width=0.58, color="#2563eb", alpha=0.78, label="Mean I/Q error ($V_{ctrl}=0.90$ V)")
    ax_b2.plot(codes_x, q_max, color="#1e3a8a", marker="^", ms=3.5, lw=0.9, ls=":", label="Max I/Q error across $V_{ctrl}$")
    ax_b2.axhline(0.40, color="#dc2626", ls="--", lw=0.9, label="0.40 ps guide (<0.36° @ 2.5 GHz)")
    l_itot, = ax_b2_r.plot(codes_x, itot_c, color="#059669", marker="o", ms=3.5, lw=1.35, label="$I_{tot}$ (VCO + /2, right axis)")

    ax_b2.set_xticks(codes_x)
    ax_b2.set_xlim(-0.7, 15.7)
    ax_b2.set_ylim(0.0, 0.56)
    ax_b2_r.set_ylim(5.40, 6.30)
    ax_b2.set_xlabel("Coarse Bank Code (c0–c15)")
    ax_b2.set_ylabel("I/Q Phase Error (ps)", color="#1d4ed8")
    ax_b2_r.set_ylabel("$I_{tot}$ (mA)", color="#047857")
    ax_b2.tick_params(axis="y", colors="#1d4ed8")
    ax_b2_r.tick_params(axis="y", colors="#047857")
    ax_b2.grid(True, axis="y", alpha=0.25, lw=0.6)
    h1, lb1 = ax_b2.get_legend_handles_labels()
    h2, lb2 = ax_b2_r.get_legend_handles_labels()
    ax_b2.legend(h1 + h2, lb1 + lb2, loc="upper right", ncol=2, fontsize=6.6, framealpha=0.93, edgecolor="#cccccc")

    # -------------------------------------------------------------------------
    # Panel (c): Real Transistor-Level 5G LC-PLL Closed-Loop V_ctrl(t) Acquisition
    # -------------------------------------------------------------------------
    ax_c = fig.add_subplot(outer[1, 0])
    style_map = {
        "as_built_4k13_200u":   dict(color="#dc2626", lw=2.0, ls="-",  zorder=5),
        "retuned_18k_200u":     dict(color="#059669", lw=2.0, ls="-",  zorder=6),
        "retuned_12k_400u":     dict(color="#2563eb", lw=1.7, ls="--", zorder=7),
        "retuned_18k_200u_r3c3":dict(color="#7c3aed", lw=1.5, ls="-.", zorder=6),
    }
    v_eq = next(iter(c3.values()))["v_eq_lock_v"]
    ax_c.axhspan(v_eq - 0.005, v_eq + 0.005, color="#16a34a", alpha=0.14, lw=0, label=f"±5 mV lock band ({v_eq:.3f} V)")
    ax_c.axhline(v_eq, color="#15803d", ls=":", lw=1.0)
    ax_c.axvline(20.0, color="#666666", ls="--", lw=0.9, alpha=0.75)

    t_max_c = 0.0
    for ck in ("as_built_4k13_200u", "retuned_18k_200u", "retuned_12k_400u", "retuned_18k_200u_r3c3"):
        if ck not in c3 or ck not in traces:
            continue
        m = c3[ck]
        tr = traces[ck]
        t_ns = tr["t_env_ns"]
        v_v = tr["ctrl_env_v"]
        t_max_c = max(t_max_c, float(t_ns[-1]))
        st = style_map[ck]
        s_txt = f"{m['settle_5mv_ns']:.0f}ns" if m["settled_5mv_within_window"] else f">{m['settle_5mv_ns']:.0f}ns"
        lbl = f"{m['short']}  [OV={m['overshoot_pct']:.1f}%, $t_{{5mV}}$={s_txt}]"
        ax_c.plot(t_ns, v_v, label=lbl, **st)

    # Annotate PFD release in open upper-left space & As-Built overshoot peak cleanly
    ax_c.text(
        28.0, 0.955, "PFD release\n(t = 20 ns)", fontsize=7.2, color="#444444", va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.20", facecolor="white", edgecolor="#dddddd", lw=0.7, alpha=0.92),
        zorder=8,
    )
    if "as_built_4k13_200u" in c3:
        ma = c3["as_built_4k13_200u"]
        pk_t = ma["t_peak_rel_ns"] + 20.0
        pk_v = ma["v_peak_v"]
        ax_c.scatter([pk_t], [pk_v], color="#dc2626", s=34, zorder=8)
        ax_c.annotate(
            f"As-Built peak: +{ma['overshoot_pct']:.1f}%\n({pk_v:.3f} V @ {ma['t_peak_rel_ns']:.0f} ns)",
            xy=(pk_t, pk_v), xytext=(min(t_max_c - 220, pk_t + 65), pk_v + 0.015),
            fontsize=7.2, fontweight="bold", color="#b91c1c",
            arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.0),
            bbox=dict(boxstyle="round,pad=0.25", facecolor="#fef2f2", edgecolor="#fca5a5", lw=0.8),
            zorder=9,
        )

    all_v = [float(np.max(traces[k]["ctrl_env_v"])) for k in c3 if k in traces]
    y_top_c = max(all_v) + 0.052
    ax_c.set_xlim(0.0, t_max_c + 12.0)
    ax_c.set_ylim(0.695, y_top_c)
    ax_c.set_xlabel("Simulation Time (ns)  [Precharge 0.72 V → 5.000 GHz Lock, N = 20]")
    ax_c.set_ylabel("Loop-Averaged $V_{ctrl}(t)$ (V)")
    ax_c.set_title("(c) Transistor-Level Closed-Loop 5G LC-PLL Acquisition (TT 27°C, 1.8 V)", fontweight="bold", pad=6)
    ax_c.grid(True, alpha=0.28, lw=0.6)
    ax_c.legend(loc="lower right", fontsize=7.1, framealpha=0.94, edgecolor="#cccccc")

    # -------------------------------------------------------------------------
    # Panel (d): Split Sub-panels: Top = Zoomed Steady-State V_ctrl Ripple (5 ref cycles = 20 ns),
    #            Bottom = 250 MHz Reference Spur (dBc) & Static Phase Error Comparison
    # -------------------------------------------------------------------------
    sub_d = gridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=outer[1, 1], height_ratios=[1.15, 1.0], hspace=0.48)
    ax_d1 = fig.add_subplot(sub_d[0])
    ax_d2 = fig.add_subplot(sub_d[1])

    order_d = [k for k in ("as_built_4k13_200u", "retuned_18k_200u", "retuned_12k_400u", "retuned_18k_200u_r3c3") if k in c3 and k in traces]
    max_abs_rip = 0.0
    for ck in order_d:
        m = c3[ck]
        tr = traces[ck]
        st = style_map[ck]
        y_mv = tr["y_rip_ac_mv"]
        max_abs_rip = max(max_abs_rip, float(np.max(np.abs(y_mv))))
        ax_d1.plot(
            tr["t_rip_ns"], y_mv, color=st["color"], lw=1.35, ls=st["ls"],
            label=f"{m['short']}: {m['vctrl_ripple_mvpp']:.2f} mVpp ({m['spur_250m_dbc']:.1f} dBc)"
        )
    ax_d1.axhline(0.0, color="#888888", ls=":", lw=0.7)
    ax_d1.set_xlim(0.0, 20.0)
    ax_d1.set_ylim(-max_abs_rip * 1.32, max_abs_rip * 1.55)
    ax_d1.set_xlabel("Steady-State Time Across 5 Reference Cycles (ns)  [1-VCO-cycle avg]")
    ax_d1.set_ylabel("$\\Delta V_{ctrl}$ (mV)")
    ax_d1.set_title("(d) Steady-State 250 MHz $V_{ctrl}$ Ripple & Reference Spur Audit", fontweight="bold", pad=6)
    ax_d1.grid(True, alpha=0.28, lw=0.6)
    ax_d1.legend(loc="upper center", ncol=2 if len(order_d) >= 3 else 1, fontsize=6.4, framealpha=0.94, edgecolor="#cccccc")

    # Bottom (d2): Grouped bar comparison of 250 MHz Reference Spur (dBc) & Static PE (ps)
    x_pos = np.arange(len(order_d))
    spurs = [c3[k]["spur_250m_dbc"] for k in order_d]
    pes = [abs(c3[k]["static_pe_fb_ref_ps"]) for k in order_d]
    cols_d = [style_map[k]["color"] for k in order_d]
    short_names = [
        k.replace("as_built_4k13_200u", "As-Built\n4.13k/200µA")
         .replace("retuned_18k_200u_r3c3", "Retuned-1\n+R3/C3")
         .replace("retuned_18k_200u", "Retuned-1\n18k/200µA")
         .replace("retuned_12k_400u", "Retuned-2\n12k/400µA")
        for k in order_d
    ]
    # Plot |Spur| (dBc attenuation below carrier — taller = cleaner!)
    spur_att = [-s for s in spurs]
    bars_sp = ax_d2.bar(x_pos, spur_att, width=0.50, color=cols_d, alpha=0.84, edgecolor="#222222", lw=0.6, zorder=3)
    ax_d2.axhline(60.0, color="#16a34a", ls="--", lw=1.0, zorder=2, label="−60 dBc clean-spur guideline")
    ax_d2.set_xticks(x_pos)
    ax_d2.set_xticklabels(short_names, fontsize=7.3)
    ax_d2.set_ylabel("250 MHz Spur Atten. (dBc)")
    ax_d2.set_ylim(0.0, 96.0)
    ax_d2.set_yticks([0, 20, 40, 60, 80])
    ax_d2.grid(True, axis="y", alpha=0.25, lw=0.6)

    for b, sp_val, pe_val, ck in zip(bars_sp, spurs, pes, order_d):
        # Put label cleanly above bar with white background pill so it NEVER collides with the 60 dBc line!
        ax_d2.text(
            b.get_x() + b.get_width() / 2.0, b.get_height() + 2.2,
            f"{sp_val:.1f} dBc\n|PE|={pe_val:.1f} ps",
            ha="center", va="bottom", fontsize=6.7, fontweight="bold", color="#111111", linespacing=1.18,
            bbox=dict(boxstyle="round,pad=0.14", facecolor="white", edgecolor="none", alpha=0.86),
            zorder=5,
        )
    ax_d2.legend(loc="upper center", bbox_to_anchor=(0.5, 0.99), fontsize=6.9, framealpha=0.94, edgecolor="#cccccc")

    fig.suptitle(
        "SKY130A 5.0 Gb/s Plan-C Octagonal LC-VCO (CPEX) & Closed-Loop 5G LC-PLL Characterization",
        fontsize=12.6, fontweight="bold", y=0.976,
    )
    fig.text(
        0.5, 0.946,
        "16-Code Monotonic Overlap (48 CPEX pts)  |  Supply Pushing K_VDD + HV18 LDO PSRR  |  Real Transistor-Level 5G LC-PLL Lock & 250 MHz Spur",
        ha="center", va="center", fontsize=8.8, color="#444444",
    )

    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=240)
    plt.close(fig)
    print(f"[Plot] Saved 240-DPI figure -> {fig_path}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stage",
        choices=("kvdd", "codes16", "pll_core", "pll_opt", "plot", "all"),
        default="all",
    )
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out-dir", type=Path, default=OUT_ROOT)
    ap.add_argument("--fig", type=Path, default=FIG_PATH)
    args = ap.parse_args()

    out_root = args.out_dir.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    sum_path = out_root / "summary.json"
    summary = json.loads(sum_path.read_text()) if sum_path.exists() else {}
    traces: dict = {}

    if args.stage in ("kvdd", "all"):
        summary["char2_kvdd"] = run_char2_kvdd(out_root, args.workers)
        summary["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sum_path.write_text(json.dumps(summary, indent=2) + "\n")

    if args.stage in ("codes16", "all"):
        summary["char1_codes16"] = run_char1_codes16(out_root, args.workers)
        summary["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sum_path.write_text(json.dumps(summary, indent=2) + "\n")

    kvco_hz_v = summary.get("char1_codes16", {}).get("kvco_c5_mhz_per_v", 141.0) * 1e6

    if args.stage in ("pll_core", "all"):
        c3_sum, traces = run_char3_pll(out_root, args.workers, kvco_hz_v, batches=("core",))
        summary["char3_pll"] = c3_sum
        summary["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sum_path.write_text(json.dumps(summary, indent=2) + "\n")

    if args.stage in ("pll_opt", "all"):
        c3_sum, traces = run_char3_pll(out_root, args.workers, kvco_hz_v, batches=("opt",))
        summary["char3_pll"] = c3_sum
        summary["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sum_path.write_text(json.dumps(summary, indent=2) + "\n")

    if args.stage in ("plot", "all"):
        npz_path = out_root / "char3_pll/char3_traces.npz"
        if not traces and npz_path.exists():
            npz = np.load(npz_path)
            for full_k in npz.files:
                ck, field = full_k.split("__", 1)
                traces.setdefault(ck, {})[field] = npz[full_k]
        # Refresh summary from stage caches if invoked directly with --stage plot
        for k, subp in (
            ("char1_codes16", out_root / "char1_codes16/char1_summary.json"),
            ("char2_kvdd", out_root / "char2_kvdd/char2_summary.json"),
            ("char3_pll", out_root / "char3_pll/char3_summary.json"),
        ):
            if subp.exists():
                summary[k] = json.loads(subp.read_text())
        if "char3_pll" in summary and traces:
            finalize_pll_metrics(summary["char3_pll"]["cases"], traces)
        summary["figure_path"] = str(args.fig.resolve().relative_to(REPO))
        summary["generated_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sum_path.write_text(json.dumps(summary, indent=2) + "\n")
        make_figure(summary, traces, args.fig.resolve())


if __name__ == "__main__":
    main()
