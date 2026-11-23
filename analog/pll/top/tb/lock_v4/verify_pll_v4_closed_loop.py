#!/usr/bin/env python3
"""Closed-loop transient lock, spur, ripple, and supply integration verification
for the upgraded 2 GHz PLL (pll_top_r6_v4_upgrade.spice):
  - BIAS v2 (serdes_bias_top_v2_ptat) + 28/66 PTAT VCO bias (serdes_bias_cml_blend_v2)
  - LDO v2_cur (serdes_pll_supply_hv18_v2_cur, 1:1 current-mode i_ldo0, 60 pF stacked MIM2)
  - CP v4 (pll_cp_steer_v4, 1/4-replica active servo, wide-swing PMOS)
  - Exact mainline r6 PFD (pll_pfd_sc_dly), LF (pll_loop_filter_k4), VCO (pll_vco_ring4_r6),
    4 CML buffers, and divide-by-8 prescaler (pll_cml_prescaler8).

Usage:
    uv run python analog/pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py --mode smoke --workers 2
    uv run python analog/pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py --mode lock --stop 1.2e-6 --workers 2
    uv run python analog/pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py --mode plot

Strictly caps ngspice concurrency at --workers 2 (num_threads=1, binary_output, skip_output_before, t_end check).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import bias, clock, pll_lock, rcorner, spice, watch  # noqa: E402
from serdes_flow.corners import Condition  # noqa: E402
from serdes_flow.waves import crossings  # noqa: E402

SC_LIB = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice")
PTAT_TABLE = REPO / "results/analog/pll/vco/r6_ptat/map_p67_28_66/table.json"
LDO_V2_SUMMARY = REPO / "results/analog/ldo/v2/20261120T070822.297791Z_schem_pvt/summary.json"
DEFAULT_CAMP = REPO / "results/analog/pll/top/v4_closed_loop_20261123"
DEFAULT_FIG = REPO / "docs/figures/clocking/pll_v4_closed_loop_20261123.png"

TREF = 4e-9  # 250 MHz reference clock
FREF = 250e6
FTGT = 2.0e9

INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/common/devices/spice/cmos_logic.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice",
    "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/pll/vco/spice/cap_bank_5b.spice",
    "analog/pll/vco/spice/vco_delay_r6.spice",
    "analog/pll/vco/spice/vco_ring4_r6.spice",
    "analog/pll/divider/spice/cml_latch.spice",
    "analog/pll/divider/spice/cml_div2.spice",
    "analog/pll/divider/spice/cml_prescaler8.spice",
    "analog/pll/top/spice/clock_frontend_r6q.spice",
    "analog/pll/pfd/spice/pfd_sc.spice",
    "analog/pll/cp/spice/charge_pump_steer_v4.spice",
    "analog/pll/loop_filter/spice/passive_rc_precharge.spice",
    "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice",
    "analog/ldo/spice/ldo_passives.spice",
    "analog/ldo/spice/pll_bias_filter_r4.spice",
    "analog/ldo/spice/ldo_v2_passives.spice",
    "analog/ldo/spice/ldo_hv18_core_v2.spice",
    "analog/ldo/spice/pll_supply_hv18_v2_cur.spice",
    "analog/bias/spice/bias_v2.spice",
    "analog/pll/vco/spice/vco_ptat_bias.spice",
    "analog/pll/top/spice/pll_top_r6_v4_upgrade.spice",
]

# 6 extreme PVT x RC corners with real Vin = 3.0 / 3.3 / 3.6 V into LDO v2_cur
EXTREME_6 = [
    dict(id="tt_v1800_t27_tt",  spec="tt_v1800_t27:tt",  vin=3.3, variant="hv", klu=False, seed_op27=False, label="TT 1.80V 27°C tt (Vin=3.3V)"),
    dict(id="ss_v1650_t-40_hh", spec="ss_v1650_t-40:hh", vin=3.0, variant="hv", klu=True,  seed_op27=False, label="SS 1.65V −40°C hh (Vin=3.0V)"),
    dict(id="ss_v1650_t85_hh",  spec="ss_v1650_t85:hh",  vin=3.0, variant="hv", klu=True,  seed_op27=False, label="SS 1.65V 85°C hh (Vin=3.0V)"),
    dict(id="sf_v1650_t-40_ll", spec="sf_v1650_t-40:ll", vin=3.0, variant="hv", klu=True,  seed_op27=False, label="SF 1.65V −40°C ll (Vin=3.0V)"),
    dict(id="fs_v1650_t85_hh",  spec="fs_v1650_t85:hh",  vin=3.0, variant="hv", klu=True,  seed_op27=False, label="FS 1.65V 85°C hh (Vin=3.0V)"),
    dict(id="ff_v1950_t-40_ll", spec="ff_v1950_t-40:ll", vin=3.6, variant="hv", klu=False, seed_op27=True,  label="FF 1.95V −40°C ll (Vin=3.6V)"),
]

# Additional direct 1.65 V quiet-rail headroom stress corners (exact CP v3 24 mV cliff corners)
HEADROOM_165 = [
    dict(id="sf_v1650_t85_ll_ext165", spec="sf_v1650_t85:ll", vin=1.65, variant="ext", klu=False, seed_op27=False, label="SF 1.65V 85°C ll (Direct 1.65V)"),
    dict(id="ss_v1650_t85_hh_ext165", spec="ss_v1650_t85:hh", vin=1.65, variant="ext", klu=False, seed_op27=False, label="SS 1.65V 85°C hh (Direct 1.65V)"),
]

PROBES = (
    "v(ref) v(fb0) v(ctrl) v(z) v(b0p) v(b0n) "
    "v(xtop.xcore.xclock.v0p) v(xtop.xcore.xclock.v0n) "
    "v(vq) v(vbg) v(xtop.xcore.vbias_q) "
    "v(xtop.xcore.xcp.vbp_srv) v(xtop.xcore.xcp.rep) "
    "v(up) v(dn) i(vin) i(vdd)"
)


def load_tables() -> tuple[dict, dict]:
    ptat = json.loads(PTAT_TABLE.read_text())
    ldo = json.loads(LDO_V2_SUMMARY.read_text())["calibration"]
    return ptat, ldo


def resolve_code_vctrl(ptat: dict, spec: str, variant: str, code_override: int | None = None) -> tuple[str, int, float]:
    """Select the 3-temp common coarse code from the PTAT 28/66 table.

    In HV LDO mode, the VCO runs on quiet ~ 1.80 V regardless of host VDD, so we use
    the process_v1800:rc 3-temp common code. In direct ext mode, we use the point's
    own supply group 3-temp common code.
    """
    cond, rc = spec.split(":")
    c = Condition.parse(cond)
    vco_vdd_tag = "v1800" if variant == "hv" else f"v{round(c.supply * 1000)}"
    frozen_key = f"{c.process}_{vco_vdd_tag}:{rc}"
    row_key = f"{c.process}_{vco_vdd_tag}_t{c.temp}:{rc}"
    row = ptat["rows"][row_key]
    if code_override is not None:
        code = code_override
    else:
        code = int(ptat["frozen"][frozen_key]["best_common"])
    assert str(code) in row["v"], f"{row_key}: code {code} not in valid window {row['codes']}"
    return row_key, code, float(row["v"][str(code)])


def ensure_op27_nodeset(
    camp: Path,
    case_id: str,
    c: Condition,
    rc: str,
    code: int,
    vctrl_target: float,
    variant: str,
    vin: float,
    ldo_trim: int,
    pre_offset: float,
) -> Path:
    """Solve exact 27 C DC OP for the same MOS/VDD/RC corner and write voltage-only .nodeset
    for exact -40 C DC OP convergence (ngspice releases .nodeset prior to final convergence)."""
    seed_dir = (camp / "op27_seeds" / case_id).resolve()
    ns_file = seed_dir / "op27_clean.nodeset"
    if ns_file.exists() and ns_file.stat().st_size > 1000:
        return ns_file
    c27 = Condition(c.process, c.supply, 27)
    deck_tr = build_deck(
        c27, rc, code, vctrl_target, variant, vin, ldo_trim,
        stop=1e-9, skip_before="0", pre_offset=pre_offset,
        tstep="10p", reltol="1e-4", use_klu=True, snap_dir=camp / "snap",
    )
    op_lines = []
    for line in deck_tr.splitlines():
        if line.startswith(".save "):
            continue
        if line.startswith("tran "):
            op_lines.append("op")
        elif line.startswith("write loop.raw"):
            op_lines.append("write op27.raw all")
        else:
            op_lines.append(line)
    ex = spice.run("\n".join(op_lines) + "\n", seed_dir, timeout_s=300)
    if not ex.ok or not (seed_dir / "op27.raw").exists():
        raise RuntimeError(f"op27 seed failed for {case_id}: {ex.log_failures[:3]}")
    wop = spice.Waves(seed_dir / "op27.raw")
    ns_lines = []
    for name in wop.names:
        if not (name.startswith("v(") and name.endswith(")")):
            continue
        node = name[2:-1]
        if "#" in node or node.startswith(("m.", "q.", "b.", "r.", "l.")):
            continue
        if node in ("vdd", "vin", "en_ldo", "ref", "rst_b", "pre_ref", "pre_en") or node.startswith(("t", "g", "cfg")):
            continue
        val = float(wop[name][0])
        if np.isfinite(val):
            ns_lines.append(f".nodeset v({node})={val:.6g}")
    ns_file.write_text("\n".join(ns_lines) + "\n")
    return ns_file


def build_deck(
    c: Condition,
    rc: str,
    code: int,
    vctrl_target: float,
    variant: str,
    vin: float,
    ldo_trim: int,
    *,
    stop: float,
    skip_before: str,
    pre_offset: float,
    tstep: str,
    reltol: str = "5e-4",
    use_klu: bool = True,
    nodeset_file: Path | None = None,
    snap_dir: Path,
) -> str:
    vq0 = 1.80 if variant == "hv" else c.supply
    bias_trim = 15  # nominal BIAS v2 r_ref trim = 01111 (15)
    solver_opt = " klu" if use_klu else ""
    lines = [
        f"* Upgraded 2 GHz PLL Closed-Loop Verification ({c.tag}:{rc}, {variant}, code={code}, Vin={vin}V)",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        *[f'.include "{REPO / p}"' for p in INCLUDES],
        f'.include "{SC_LIB}"',
        f".param supply={c.supply}",
        "Vdd vdd 0 {supply}",
    ]
    if variant == "hv":
        lines += [
            f"Vin vin 0 {vin}",
            "Ven_ldo en_ldo 0 {supply}",
            *[f"Et{k} t{k} 0 vdd 0 {(ldo_trim >> k) & 1}" for k in range(6)],
        ]
    else:
        lines += [
            f"Vin vin 0 {c.supply}",
            "Vq vq 0 {supply}",
            "Ven_ldo en_ldo 0 0",
            *[f"Et{k} t{k} 0 0 0 0" for k in range(6)],
        ]
    lines += [
        *[f"Eg{k} g{k} 0 vdd 0 {(bias_trim >> k) & 1}" for k in range(5)],
        *[f"Ecode{k} cfg{k} 0 vq 0 {(code >> k) & 1}" for k in range(5)],
        f"Vref ref 0 PULSE(0 {{supply}} 2n 30p 30p {TREF / 2 - 30e-12:.4e} {TREF:.4e})",
        "Vreset rst_b 0 PWL(0 0 52n 0 52.02n {supply})",
        f"Vpre pre_ref 0 {vctrl_target + pre_offset:.4f}",
        "Vpen pre_en 0 PWL(0 {supply} 50n {supply} 50.2n 0)",
        "Xtop vin vdd vq 0 ref rst_b en_ldo cfg0 cfg1 cfg2 cfg3 cfg4 "
        "g4 g3 g2 g1 g0 t0 t1 t2 t3 t4 t5 pre_ref pre_en "
        "vbg ctrl z up dn fb0 "
        "b0p b0n b1p b1n b2p b2n b3p b3n d02p d02n d04p d04n d08p d08n "
        "pll_top_r6_v4_upgrade nf_const=28 nf_ptat=66",
        # Deterministic startup kicks (noiseless transient breaks symmetric metastable point)
        "Ikick xtop.xcore.xclock.v0p xtop.xcore.xclock.v0n PWL(0 1u 20p 1u 21p 0)",
        *[f"Ikick{n} {n}p {n}n PWL(0 0 1n 0 1.01n 20u 1.05n 20u 1.06n 0)" for n in ("d02", "d04", "d08")],
    ]
    if nodeset_file is not None:
        lines.append(f'.include "{nodeset_file.resolve()}"')
    else:
        lines += [
            # Clean DC OP nodesets (initial Newton guess only; released before exact OP convergence)
            ".nodeset v(vbg)=1.234 v(xtop.xbias.xref.s)=1.234 v(xtop.xbias.vg)=1.13 "
            "v(xtop.xbias.vgi)=1.10 v(xtop.xbias.xref.ta)=0.99 v(xtop.xbias.xref.tb)=0.99",
            f".nodeset v(xtop.icml)=1.04 v(xtop.icml_vco)=1.04 v(xtop.xcore.vbias_q)=1.04 "
            f"v(xtop.icp)=0.87 v(xtop.i_ldo0)=0.88 v(xtop.i_ldo1)=0.88 v(xtop.vbp)={vq0 - 1.26:.3f}",
            ".nodeset v(xtop.xcore.xclock.xfb0.xrestore.qp)=0 v(xtop.xcore.xclock.xfb0.xrestore.qn)={supply}",
            f".nodeset v(ctrl)={vctrl_target + pre_offset:.4f} v(z)={vctrl_target + pre_offset:.4f} v(vq)={vq0:.3f}",
            f".nodeset v(xtop.xcore.xcp.vbp_srv)={vq0 - 1.23:.3f} v(xtop.xcore.xcp.rep)={vctrl_target + pre_offset:.4f}",
        ]
        if variant == "hv":
            lines.append(
                f".nodeset v(xtop.xldo.xloop.ref_local)=1.233 v(xtop.xldo.fb)=1.232 "
                f"v(xtop.xldo.xloop.xcore.va)={vin - 0.35:.3f} v(xtop.xldo.xloop.xcore.pre_d)={vin - 1.27:.3f} "
                f"v(xtop.xldo.xloop.xcore.pre_g)={vin - 1.27:.3f} v(xtop.xldo.xloop.xcore.casg)={vin:.3f} "
                f"v(xtop.xldo.xloop.xcore.mid)={min(vin - 0.64, 2.85):.3f} v(xtop.xldo.xloop.xcore.gate)={vq0 + 0.56:.3f} "
                f"v(xtop.xldo.xloop.xcore.bp)={vin - 1.53:.3f} v(xtop.xldo.xloop.xcore.tail)={vin - 0.87:.3f} "
                f"v(xtop.xldo.xloop.xcore.d)=0.98 v(xtop.xldo.xloop.xcore.x)=0.76 v(xtop.xldo.xloop.vg_clamp)=0.0"
            )
        for k in range(4):
            for sd in ("p", "n"):
                lines.append(
                    f".nodeset v(xtop.xcore.xclock.v{k}{sd})={vq0 - 0.12:.3f} "
                    f"v(xtop.xcore.xclock.xvco.xv{k}{sd}.p2)={vctrl_target + pre_offset:.4f}"
                )
    probes = PROBES + (" i(vq)" if variant == "ext" else "")
    lines += [
        f".temp {c.temp}",
        f".options reltol={reltol} abstol=1p vntol=1u{solver_opt}",
        f".save {probes}",
        ".control",
        "set num_threads=1",
        f"tran {tstep} {stop:.4e} 0 {tstep}",
        f"wrdata loop.tsv {probes}",
        "quit",
        ".endc",
        ".end",
    ]
    text = spice.binary_output("\n".join(lines) + "\n")
    if skip_before and skip_before != "0":
        text = spice.skip_output_before(text, skip_before)
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed(text, snap_dir)
    return bias.section(text, c.process, rc)


def rising_edges(t: np.ndarray, y: np.ndarray, thr: float | None = None) -> np.ndarray:
    if thr is None:
        thr = 0.5 * (float(np.max(y)) + float(np.min(y)))
    e, p = crossings(t, y - thr)
    return e[p > 0]


def pulse_widths(t: np.ndarray, y: np.ndarray, t0: float, t1: float) -> dict:
    m = (t >= t0) & (t <= t1)
    ts, ys = t[m], y[m]
    thr = 0.5 * (float(np.max(ys)) + float(np.min(ys)))
    ed, sg = crossings(ts, ys - thr)
    widths = []
    for i in range(len(ed) - 1):
        if sg[i] > 0 and sg[i + 1] < 0:
            widths.append(float(ed[i + 1] - ed[i]))
    if not widths:
        return dict(count=0, mean_ps=float("nan"), min_ps=float("nan"), max_ps=float("nan"))
    arr = np.array(widths) * 1e12
    return dict(count=len(widths), mean_ps=float(np.mean(arr)), min_ps=float(np.min(arr)), max_ps=float(np.max(arr)))


def time_weighted_mean(t: np.ndarray, y: np.ndarray) -> float:
    dt = np.diff(t)
    return float(np.sum(0.5 * (y[:-1] + y[1:]) * dt) / (t[-1] - t[0]))


def tone_250m_amp_v(t: np.ndarray, y: np.ndarray, f_tone: float = FREF) -> float:
    """Time-weighted single-tone harmonic extraction (immune to adaptive SPICE timestep)."""
    n_cyc = int(np.floor((t[-1] - t[0]) * f_tone))
    if n_cyc < 2:
        return float("nan")
    t1 = t[-1]
    t0 = t1 - n_cyc / f_tone
    # Interpolate onto dense uniform grid over exact integer number of 250 MHz periods
    nu = max(4096, n_cyc * 64)
    tu = np.linspace(t0, t1, nu, endpoint=False)
    yu = np.interp(tu, t, y)
    yu = yu - np.mean(yu)
    c = 2.0 * np.mean(yu * np.exp(-2j * np.pi * f_tone * (tu - t0)))
    return float(np.abs(c))


def analyse_lock(raw_path: Path, c: Condition, vin: float, variant: str, kvco_nom_hz_v: float = 700e6) -> dict:
    w = spice.Waves(raw_path)
    t = w.t
    t_end = float(t[-1])
    t_late = t_end - 200e-9
    late = t >= t_late

    # Reference & feedback edges
    ref_all = rising_edges(t, w["v(ref)"], thr=0.5 * c.supply)
    fb_all = rising_edges(t, w["v(fb0)"], thr=0.5 * c.supply)

    # Project engineering lock contract (32 cycles = 128 ns window, 8 cycle stride, <=100 ppm, <=20 ps, >=320 ns hold)
    screen = pll_lock.screen(ref_all, fb_all, start=55e-9, stop=t_end, period=TREF)
    # Also compute native_k4 capture_s & static offset metrics
    fb_lock = clock.feedback_lock(ref_all, fb_all, start=55e-9, stop=t_end, period=TREF)

    # Static phase error over last 200 ns: (1) fb0 - ref at PFD input, (2) UP - DN pulse width difference
    ref_l = ref_all[ref_all >= t_late]
    fb_l = fb_all[fb_all >= t_late - TREF]
    if len(ref_l) > 2 and len(fb_l) > 2:
        idx = np.clip(np.searchsorted(fb_l, ref_l), 1, len(fb_l) - 1)
        near = np.where(np.abs(fb_l[idx] - ref_l) < np.abs(fb_l[idx - 1] - ref_l), fb_l[idx], fb_l[idx - 1])
        pe_ps = (near - ref_l) * 1e12
        static_pe_mean_ps = float(np.mean(pe_ps))
        static_pe_pp_ps = float(np.ptp(pe_ps))
    else:
        static_pe_mean_ps = float("nan")
        static_pe_pp_ps = float("nan")

    up_pw = pulse_widths(t, w["v(up)"], t_end - 100e-9, t_end)
    dn_pw = pulse_widths(t, w["v(dn)"], t_end - 100e-9, t_end)
    up_dn_diff_ps = float(up_pw["mean_ps"] - dn_pw["mean_ps"])

    # 2 GHz VCO & buffer output over last 200 ns
    b0 = w["v(b0p)"][late] - w["v(b0n)"][late]
    v0 = w["v(xtop.xcore.xclock.v0p)"][late] - w["v(xtop.xcore.xclock.v0n)"][late]
    t_l = t[late]
    b0_ed, b0_sg = crossings(t_l, b0)
    b0_r = b0_ed[b0_sg > 0]
    f_buf_hz = float((len(b0_r) - 1) / (b0_r[-1] - b0_r[0])) if len(b0_r) > 2 else float("nan")
    f_err_ppm = (f_buf_hz / FTGT - 1.0) * 1e6
    f_err_pct = (f_buf_hz / FTGT - 1.0) * 100.0
    # Fixed 2 GHz TIE peak-to-peak (deterministic modulation + drift)
    if len(b0_r) > 2:
        tie = (b0_r - b0_r[0]) - np.arange(len(b0_r)) * (1.0 / FTGT)
        tie_pp_ps = float(np.ptp(tie) * 1e12)
        per_pp_ps = float(np.ptp(np.diff(b0_r)) * 1e12)
    else:
        tie_pp_ps = float("nan")
        per_pp_ps = float("nan")

    # Control voltage & 250 MHz reference spur ripple over last 200 ns
    ctrl_l = w["v(ctrl)"][late]
    z_l = w["v(z)"][late]
    ctrl_mean = time_weighted_mean(t_l, ctrl_l)
    ctrl_pp_mv = float(np.ptp(ctrl_l) * 1e3)
    ctrl_min = float(np.min(ctrl_l))
    ctrl_max = float(np.max(ctrl_l))
    z_mean = time_weighted_mean(t_l, z_l)
    z_pp_mv = float(np.ptp(z_l) * 1e3)
    vctrl_250m_pk_mv = tone_250m_amp_v(t_l, ctrl_l, FREF) * 1e3
    # FM narrowband spur approximation: Spur_dBc = 20*log10(Kvco * V_m_pk / (2 * f_ref))
    spur_250m_dbc = float(20.0 * np.log10(max(1e-12, kvco_nom_hz_v * (vctrl_250m_pk_mv * 1e-3) / (2.0 * FREF))))

    # Quiet rail, bandgap, PTAT tail bias
    vq_l = w["v(vq)"][late]
    vbg_l = w["v(vbg)"][late]
    vbq_l = w["v(xtop.xcore.vbias_q)"][late]
    vq_mean = time_weighted_mean(t_l, vq_l)
    vq_pp_mv = float(np.ptp(vq_l) * 1e3)
    vbg_mean = time_weighted_mean(t_l, vbg_l)
    vbq_mean = time_weighted_mean(t_l, vbq_l)
    vbq_pp_mv = float(np.ptp(vbq_l) * 1e3)

    # CP v4 servo stability (vbp_srv & rep)
    vsrv_l = w["v(xtop.xcore.xcp.vbp_srv)"][late]
    vrep_l = w["v(xtop.xcore.xcp.rep)"][late]
    vsrv_mean = time_weighted_mean(t_l, vsrv_l)
    vsrv_pp_mv = float(np.ptp(vsrv_l) * 1e3)
    # Split last 200 ns into first/second half to confirm zero growing oscillation
    mid_idx = len(t_l) // 2
    vsrv_pp_first_mv = float(np.ptp(vsrv_l[:mid_idx]) * 1e3)
    vsrv_pp_second_mv = float(np.ptp(vsrv_l[mid_idx:]) * 1e3)
    vsrv_drift_mv = float((time_weighted_mean(t_l[mid_idx:], vsrv_l[mid_idx:]) - time_weighted_mean(t_l[:mid_idx], vsrv_l[:mid_idx])) * 1e3)
    rep_err_mv = float((time_weighted_mean(t_l, vrep_l) - ctrl_mean) * 1e3)

    # Headroom to CP v4 vs CP v3 upper 5%-droop limit
    # Measured CP v4 5% droop upper limit: 1.49 V @ 1.65 V, 1.67 V @ 1.80 V, 1.84 V @ 1.95 V
    # Measured CP v3 5% droop upper limit: 1.26 V @ 1.65 V, 1.42 V @ 1.80 V, 1.57 V @ 1.95 V
    cp_v4_hi = float(np.interp(vq_mean, [1.65, 1.80, 1.95], [1.49, 1.67, 1.84]))
    cp_v3_hi = float(np.interp(vq_mean, [1.65, 1.80, 1.95], [1.26, 1.42, 1.57]))
    cp_v4_headroom_mv = (cp_v4_hi - ctrl_max) * 1e3
    cp_v3_headroom_mv = (cp_v3_hi - ctrl_max) * 1e3

    # Power (PLL + LDO + BIAS)
    i_vin_avg = -time_weighted_mean(t_l, w["i(vin)"][late])
    i_vdd_avg = -time_weighted_mean(t_l, w["i(vdd)"][late])
    if variant == "hv":
        p_hv_ldo_mw = i_vin_avg * vin * 1e3
        p_host_mw = i_vdd_avg * c.supply * 1e3
    else:
        # In ext mode, Vq drives the quiet rail directly at c.supply
        i_vq_avg = -time_weighted_mean(t_l, w["i(vq)"][late]) if "i(vq)" in w.names else 0.0
        p_hv_ldo_mw = (i_vin_avg * vin + i_vq_avg * c.supply) * 1e3
        p_host_mw = i_vdd_avg * c.supply * 1e3
    p_total_mw = p_hv_ldo_mw + p_host_mw

    return dict(
        t_start_s=float(t[0]),
        t_end_s=t_end,
        f_out_ghz=f_buf_hz / 1e9,
        f_err_ppm=f_err_ppm,
        f_err_pct=f_err_pct,
        engineering_locked=bool(screen["locked"]),
        engineering_status=screen["status"],
        hold_s=float(screen["hold_s"]),
        hold_start_s=screen["hold_start_s"],
        capture_s=float(fb_lock["capture_s"]),
        locked_at_end=bool(fb_lock["locked_at_end"]),
        static_pe_fb_ref_ps=static_pe_mean_ps,
        static_pe_fb_ref_pp_ps=static_pe_pp_ps,
        up_pw_mean_ps=up_pw["mean_ps"],
        dn_pw_mean_ps=dn_pw["mean_ps"],
        up_dn_diff_ps=up_dn_diff_ps,
        vctrl_mean_v=ctrl_mean,
        vctrl_min_v=ctrl_min,
        vctrl_max_v=ctrl_max,
        vctrl_ripple_mvpp=ctrl_pp_mv,
        vctrl_250m_pk_mv=vctrl_250m_pk_mv,
        spur_250m_est_dbc=spur_250m_dbc,
        z_mean_v=z_mean,
        z_ripple_mvpp=z_pp_mv,
        vco_swing_mvpp=float(np.ptp(v0) * 1e3),
        buf_swing_mvpp=float(np.ptp(b0) * 1e3),
        tie_pp_ps=tie_pp_ps,
        per_pp_ps=per_pp_ps,
        vq_mean_v=vq_mean,
        vq_ripple_mvpp=vq_pp_mv,
        vbg_mean_v=vbg_mean,
        vbias_q_mean_v=vbq_mean,
        vbias_q_ripple_mvpp=vbq_pp_mv,
        vbp_srv_mean_v=vsrv_mean,
        vbp_srv_ripple_mvpp=vsrv_pp_mv,
        vbp_srv_pp_first100_mv=vsrv_pp_first_mv,
        vbp_srv_pp_second100_mv=vsrv_pp_second_mv,
        vbp_srv_drift_mv=vsrv_drift_mv,
        vrep_minus_ctrl_mv=rep_err_mv,
        cp_v4_hi_v=cp_v4_hi,
        cp_v4_headroom_mv=cp_v4_headroom_mv,
        cp_v3_headroom_mv=cp_v3_headroom_mv,
        i_vin_ma=i_vin_avg * 1e3,
        i_vdd_ma=i_vdd_avg * 1e3,
        p_hv_ldo_mw=p_hv_ldo_mw,
        p_host_mw=p_host_mw,
        p_total_mw=p_total_mw,
    )


def analyse_smoke(raw_path: Path, c: Condition, vin: float) -> dict:
    w = spice.Waves(raw_path)
    t = w.t
    return dict(
        t_end_ns=float(t[-1] * 1e9),
        n_pts=int(len(t)),
        vbg_v=float(w["v(vbg)"][-1]),
        vq_v=float(w["v(vq)"][-1]),
        ctrl_v=float(w["v(ctrl)"][-1]),
        vbias_q_v=float(w["v(xtop.xcore.vbias_q)"][-1]),
        vbp_srv_v=float(w["v(xtop.xcore.xcp.vbp_srv)"][-1]),
        vrep_v=float(w["v(xtop.xcore.xcp.rep)"][-1]),
        vco_diff_pp_mv=float(np.ptp(w["v(xtop.xcore.xclock.v0p)"] - w["v(xtop.xcore.xclock.v0n)"]) * 1e3),
        i_vin_ma=float(-w["i(vin)"][-1] * 1e3),
        i_vdd_ma=float(-w["i(vdd)"][-1] * 1e3),
    )


def make_figure(camp: Path, cases: list[dict], summary_rows: dict, fig_path: Path) -> None:
    colors = ["#1f77b4", "#d62728", "#ff7f0e", "#2ca02c", "#9467bd", "#17becf", "#8c564b", "#e377c2"]
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.2), dpi=160)
    ax_lock, ax_rip, ax_vq, ax_vco = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]

    hv_cases = [cs for cs in cases if cs["variant"] == "hv" and cs["id"] in summary_rows]
    # Panel 1: V_ctrl(t) full lock trajectories
    for i, cs in enumerate(hv_cases):
        r = summary_rows[cs["id"]]
        w = spice.Waves(Path(r["raw_path"]))
        t_ns = w.t * 1e9
        col = colors[i % len(colors)]
        # Downsample cleanly for fast crisp plotting
        step = max(1, len(t_ns) // 4000)
        lbl = f"{cs['label']} [c={r['code']}, {r['f_out_ghz']:.5f} GHz]"
        ax_lock.plot(t_ns[::step], w["v(ctrl)"][::step], color=col, lw=1.3, label=lbl)
    ax_lock.axhline(1.67, color="#444444", ls="--", lw=1.0, label="CP v4 upper 5% bound @1.8V (1.67V)")
    ax_lock.axhline(1.42, color="#aa3333", ls=":", lw=1.0, label="Old CP v3 upper 5% bound @1.8V (1.42V)")
    ax_lock.set_title("(a) Closed-Loop $V_{ctrl}(t)$ Lock Trajectories (6 PVT×RC Corners)", fontweight="bold")
    ax_lock.set_xlabel("Time (ns)")
    ax_lock.set_ylabel("$V_{ctrl}$ (V)")
    ax_lock.grid(True, alpha=0.3)
    ax_lock.legend(fontsize=7.2, loc="lower right", framealpha=0.92)

    # Panel 2: Steady-state V_ctrl AC ripple (last 20 ns = 5 ref cycles) + vbp_srv stability inset/overlay
    for i, cs in enumerate(hv_cases):
        r = summary_rows[cs["id"]]
        w = spice.Waves(Path(r["raw_path"]))
        t = w.t
        m = t >= t[-1] - 20e-9
        t_rel = (t[m] - (t[-1] - 20e-9)) * 1e9
        ctrl_ac = (w["v(ctrl)"][m] - r["vctrl_mean_v"]) * 1e3
        col = colors[i % len(colors)]
        ax_rip.plot(
            t_rel, ctrl_ac, color=col, lw=1.2,
            label=f"{cs['id']} ({r['vctrl_ripple_mvpp']:.1f} mVpp, ΔPW={r['up_dn_diff_ps']:+.1f} ps)"
        )
    ax_rip.set_title("(b) Steady-State $V_{ctrl}$ 250 MHz Ripple (Last 20 ns, AC-Coupled)", fontweight="bold")
    ax_rip.set_xlabel("Relative Time in Steady State (ns)")
    ax_rip.set_ylabel("$V_{ctrl} - \\overline{V_{ctrl}}$ (mV)")
    ax_rip.grid(True, alpha=0.3)
    ax_rip.legend(fontsize=7.2, loc="upper right", framealpha=0.92)

    # Panel 3: LDO v2_cur quiet rail & CP v4 servo vbp_srv stability over last 200 ns
    ax_srv = ax_vq.twinx()
    for i, cs in enumerate(hv_cases):
        r = summary_rows[cs["id"]]
        w = spice.Waves(Path(r["raw_path"]))
        t = w.t
        m = t >= t[-1] - 200e-9
        t_ns = t[m] * 1e9
        step = max(1, int(np.sum(m)) // 2000)
        col = colors[i % len(colors)]
        ax_vq.plot(
            t_ns[::step], w["v(vq)"][m][::step], color=col, lw=1.25,
            label=f"{cs['id']}: Vq={r['vq_mean_v']:.3f}V ({r['vq_ripple_mvpp']:.1f}mVpp)"
        )
        ax_srv.plot(
            t_ns[::step], w["v(xtop.xcore.xcp.vbp_srv)"][m][::step], color=col, lw=0.9, ls="--", alpha=0.75
        )
    ax_vq.set_title("(c) LDO v2_cur Quiet Rail (solid) & CP v4 $v_{bp,srv}$ (dashed, Last 200 ns)", fontweight="bold")
    ax_vq.set_xlabel("Time (ns)")
    ax_vq.set_ylabel("LDO $V_{quiet}$ (V)")
    ax_srv.set_ylabel("CP v4 $v_{bp,srv}$ (V)")
    ax_vq.set_ylim(1.755, 1.855)
    ax_srv.set_ylim(0.38, 0.82)
    ax_vq.grid(True, alpha=0.3)
    ax_vq.legend(fontsize=7.0, loc="upper left", ncol=2, framealpha=0.94)

    # Panel 4: Locked 2 GHz VCO differential waveforms (last 2.5 ns = 5 cycles)
    for i, cs in enumerate(hv_cases):
        r = summary_rows[cs["id"]]
        w = spice.Waves(Path(r["raw_path"]))
        t = w.t
        m = t >= t[-1] - 2.5e-9
        t_rel = (t[m] - (t[-1] - 2.5e-9)) * 1e9
        v0_mv = (w["v(xtop.xcore.xclock.v0p)"][m] - w["v(xtop.xcore.xclock.v0n)"][m]) * 1e3
        col = colors[i % len(colors)]
        ax_vco.plot(
            t_rel, v0_mv, color=col, lw=1.25,
            label=f"{cs['id']}: {r['vco_swing_mvpp']:.0f} mVpp, P={r['p_total_mw']:.1f} mW"
        )
    ax_vco.axhline(200, color="#666666", ls=":", lw=0.9)
    ax_vco.axhline(-200, color="#666666", ls=":", lw=0.9, label="±200 mV (400 mVpp target)")
    ax_vco.set_title("(d) Locked 2 GHz VCO Core Differential Output (Last 2.5 ns)", fontweight="bold")
    ax_vco.set_xlabel("Relative Time in Steady State (ns)")
    ax_vco.set_ylabel("$V_{0p} - V_{0n}$ (mV)")
    ax_vco.grid(True, alpha=0.3)
    ax_vco.legend(fontsize=7.2, loc="lower right", framealpha=0.92)

    fig.suptitle(
        "Upgraded 2 GHz PLL Closed-Loop Integration: BIAS v2 + PTAT 28/66 + LDO v2_cur + CP v4 + Mainline r6",
        fontsize=12.5, fontweight="bold", y=0.992,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(fig_path, dpi=160)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("smoke", "lock", "headroom", "plot"), default="lock")
    ap.add_argument("--camp", type=Path, default=DEFAULT_CAMP)
    ap.add_argument("--fig", type=Path, default=DEFAULT_FIG)
    ap.add_argument("--stop", type=float, default=8.5e-7)
    ap.add_argument("--tstep", default="10p")
    ap.add_argument("--reltol", default="5e-4")
    ap.add_argument("--pre-offset", type=float, default=0.04)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--klu", action="store_true", default=True)
    ap.add_argument("--no-klu", dest="klu", action="store_false")
    ap.add_argument("--only", default="", help="Comma-separated subset of case IDs")
    ap.add_argument("--include-headroom", action="store_true", default=False)
    args = ap.parse_args()

    workers = max(1, min(args.workers, 2))  # Hard cap at 2 concurrent ngspice workers
    camp = args.camp.resolve() if args.camp.is_absolute() else (REPO / args.camp).resolve()
    ptat, ldo_cal = load_tables()

    if args.mode == "headroom":
        cases = list(HEADROOM_165)
    elif args.include_headroom or args.mode == "plot":
        cases = list(EXTREME_6) + list(HEADROOM_165)
    else:
        cases = list(EXTREME_6)

    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        cases = [cs for cs in cases if cs["id"] in want]

    if args.mode == "smoke":
        smoke_dir = camp / "smoke_1ns"
        jobs = []
        meta_map = {}
        for cs in cases:
            cond, rc = cs["spec"].split(":")
            c = Condition.parse(cond)
            row_key, code, vctrl = resolve_code_vctrl(ptat, cs["spec"], cs["variant"])
            trim = int(ldo_cal[f"{c.process}:{rc}"]["trim"])
            d = smoke_dir / cs["id"]
            meta_map[cs["id"]] = (c, rc, row_key, code, vctrl, trim, cs)
            if spice.case_output(d, "run", "loop.raw", 1e-9) is not None:
                continue
            ns_file = (
                ensure_op27_nodeset(camp, cs["id"], c, rc, code, vctrl, cs["variant"], cs["vin"], trim, args.pre_offset)
                if cs.get("seed_op27") else None
            )
            deck = build_deck(
                c, rc, code, vctrl, cs["variant"], cs["vin"], trim,
                stop=1e-9, skip_before="0", pre_offset=args.pre_offset,
                tstep="10p", reltol=args.reltol, use_klu=args.klu and cs.get("klu", True),
                nodeset_file=ns_file, snap_dir=camp / "snap",
            )
            jobs.append((deck, spice.next_run_dir(d, "run"), dict(timeout_s=600, meta=dict(id=cs["id"], mode="smoke"))))
        if jobs:
            active = len(watch.ngspice_cwds())
            if active + workers > 4:
                raise RuntimeError(f"Host ngspice limit guard: {active} already active, requested {workers}")
            for ex in spice.run_many(jobs, workers=workers, smoke=False):
                print(f"SMOKE {ex.run_dir.parent.name}: ok={ex.ok} elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}", flush=True)
        out = {}
        for cs in cases:
            c, rc, row_key, code, vctrl, trim, _ = meta_map[cs["id"]]
            p = spice.case_output(smoke_dir / cs["id"], "run", "loop.raw", 1e-9)
            if p is None:
                print(f"MISSING smoke: {cs['id']}", flush=True)
                continue
            r = analyse_smoke(p, c, cs["vin"])
            out[cs["id"]] = dict(spec=cs["spec"], vin=cs["vin"], variant=cs["variant"], code=code, trim=trim, vctrl_model=vctrl, **r)
            print(
                f"{cs['id']:22s} code={code:2d} trim={trim:2d} | Vbg={r['vbg_v']:.4f}V Vq={r['vq_v']:.4f}V "
                f"Vctrl={r['ctrl_v']:.4f}V Vbp_srv={r['vbp_srv_v']:.4f}V Vrep={r['vrep_v']:.4f}V "
                f"VCOpp={r['vco_diff_pp_mv']:.1f}mV Ivin={r['i_vin_ma']:.2f}mA Ivdd={r['i_vdd_ma']:.2f}mA",
                flush=True,
            )
        smoke_dir.mkdir(parents=True, exist_ok=True)
        (smoke_dir / "smoke_summary.json").write_text(json.dumps(out, indent=2))
        return

    if args.mode in ("lock", "headroom"):
        jobs = []
        meta_map = {}
        for cs in cases:
            cond, rc = cs["spec"].split(":")
            c = Condition.parse(cond)
            row_key, code, vctrl = resolve_code_vctrl(ptat, cs["spec"], cs["variant"])
            trim = int(ldo_cal[f"{c.process}:{rc}"]["trim"])
            d = camp / cs["id"]
            meta_map[cs["id"]] = (c, rc, row_key, code, vctrl, trim, cs)
            if spice.case_output(d, "run", "loop.raw", args.stop) is not None:
                print(f"SKIP complete: {cs['id']} (stop={args.stop*1e9:.0f} ns)", flush=True)
                continue
            ns_file = (
                ensure_op27_nodeset(camp, cs["id"], c, rc, code, vctrl, cs["variant"], cs["vin"], trim, args.pre_offset)
                if cs.get("seed_op27") else None
            )
            use_klu = args.klu and cs.get("klu", True)
            deck = build_deck(
                c, rc, code, vctrl, cs["variant"], cs["vin"], trim,
                stop=args.stop, skip_before="40n", pre_offset=args.pre_offset,
                tstep=args.tstep, reltol=args.reltol, use_klu=use_klu,
                nodeset_file=ns_file, snap_dir=camp / "snap",
            )
            jobs.append((
                deck,
                spice.next_run_dir(d, "run"),
                dict(
                    timeout_s=4 * 3600,
                    meta=dict(
                        id=cs["id"], spec=cs["spec"], variant=cs["variant"], vin=cs["vin"],
                        vco_entry=row_key, code=code, ldo_trim=trim, vctrl_model=vctrl,
                        pre_offset=args.pre_offset, stop=args.stop, tstep=args.tstep,
                        reltol=args.reltol, klu=use_klu, seed_op27=bool(ns_file),
                    ),
                ),
            ))
        if jobs:
            active = len(watch.ngspice_cwds())
            if active + workers > 4:
                raise RuntimeError(f"Host ngspice limit guard: {active} already active, requested {workers}")
            for ex in spice.run_many(jobs, workers=workers, smoke=False):
                print(
                    f"DONE {ex.run_dir.parent.name}/{ex.run_dir.name}: ok={ex.ok} "
                    f"elapsed={ex.elapsed_s:.1f}s fail={ex.log_failures[:2]}",
                    flush=True,
                )

    # Analyse all completed cases in camp
    all_cases = list(EXTREME_6) + list(HEADROOM_165)
    summary_rows = {}
    for cs in all_cases:
        cond, rc = cs["spec"].split(":")
        c = Condition.parse(cond)
        row_key, code, vctrl = resolve_code_vctrl(ptat, cs["spec"], cs["variant"])
        trim = int(ldo_cal[f"{c.process}:{rc}"]["trim"])
        d = camp / cs["id"]
        if not d.exists():
            continue
        # Accept completed raw at args.stop (or any complete run >= 600 ns in plot mode)
        t_req = args.stop if args.mode != "plot" else 600e-9
        p = spice.case_output(d, "run", "loop.raw", t_req)
        if p is None:
            print(f"INCOMPLETE/MISSING: {cs['id']}", flush=True)
            continue
        kvco_raw = ptat["rows"][row_key].get("kvco", 700e6)
        kvco_est = float(kvco_raw) if not isinstance(kvco_raw, dict) else float(kvco_raw.get(str(code), 700e6))
        if kvco_est < 1e5:
            kvco_est *= 1e6
        res = analyse_lock(p, c, cs["vin"], cs["variant"], kvco_nom_hz_v=kvco_est)
        ex_path = p.parent / "execution.json"
        elapsed_s = json.loads(ex_path.read_text()).get("elapsed_s") if ex_path.exists() else None
        summary_rows[cs["id"]] = dict(
            spec=cs["spec"], label=cs["label"], variant=cs["variant"], vin=cs["vin"],
            vco_entry=row_key, code=code, ldo_trim=trim, vctrl_model_v=vctrl,
            elapsed_s=elapsed_s, raw_path=str(p), **res,
        )
        print(
            f"{cs['id']:22s} c={code:2d} | f={res['f_out_ghz']:.6f}GHz ({res['f_err_ppm']:+.2f}ppm) "
            f"lock={res['engineering_locked']} hold={res['hold_s']*1e9:.0f}ns cap={res['capture_s']*1e9:.0f}ns | "
            f"Vctrl={res['vctrl_mean_v']:.4f}V rip={res['vctrl_ripple_mvpp']:.2f}mVpp (250M={res['vctrl_250m_pk_mv']:.2f}mVpk/{res['spur_250m_est_dbc']:.1f}dBc) | "
            f"PE(fb-ref)={res['static_pe_fb_ref_ps']:+.1f}ps ΔPW(UP-DN)={res['up_dn_diff_ps']:+.2f}ps | "
            f"VCO={res['vco_swing_mvpp']:.0f}mVpp Vq={res['vq_mean_v']:.4f}V({res['vq_ripple_mvpp']:.2f}mVpp) "
            f"vbp_srv={res['vbp_srv_mean_v']:.4f}V({res['vbp_srv_ripple_mvpp']:.2f}mVpp,drift={res['vbp_srv_drift_mv']:+.2f}mV) "
            f"HR_v4={res['cp_v4_headroom_mv']:+.0f}mV(v3:{res['cp_v3_headroom_mv']:+.0f}mV) P={res['p_total_mw']:.2f}mW",
            flush=True,
        )

    camp.mkdir(parents=True, exist_ok=True)
    summary_path = camp / "summary.json"
    summary_path.write_text(json.dumps(dict(
        generated_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        stop_s=args.stop,
        tstep=args.tstep,
        pre_offset_v=args.pre_offset,
        klu=args.klu,
        rows=summary_rows,
    ), indent=2))
    print(f"Summary written: {summary_path.relative_to(REPO)}", flush=True)

    if any(cs["id"] in summary_rows for cs in EXTREME_6):
        fig_path = args.fig.resolve() if args.fig.is_absolute() else (REPO / args.fig).resolve()
        make_figure(camp, all_cases, summary_rows, fig_path)
        print(f"Figure written: {fig_path.relative_to(REPO)}", flush=True)


if __name__ == "__main__":
    main()
