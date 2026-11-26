"""Verify 5 Gb/s (2.5 GHz Half-Rate -> 1.25 GHz 8-Phase Quarter-Rate) Pure CMOS PI + Deterministic QDiv2.

Usage:
  # Fast 2-corner or 4-corner sizing sweep:
  uv run python analog/rx/cmos_rx/tb/pi_5g_study/verify_pi_5g.py --mode sweep [--corners fast|4c] [--pi "..."] [--tag name]
  # Full 4-corner signoff + fine-code monotonicity + reset hygiene & determinism:
  uv run python analog/rx/cmos_rx/tb/pi_5g_study/verify_pi_5g.py --mode signoff [--pi "..."] [--codes 0..16]

Strict constraints:
  - Uses ONLY analog/rx/cmos_rx/spice/rx_cmos_pi_5g_cand.spice (never touches 4G production files).
  - Writes ONLY to results/analog/rx/pi_5g_study_20261124/.
  - Enforces AT MOST 2 concurrent ngspice workers (num_threads=1 via serdes_flow.spice).
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings, time_average

RESULTS_ROOT = ROOT / "results/analog/rx/pi_5g_study_20261124"
DUT_SPICE = ROOT / "analog/rx/cmos_rx/spice/rx_cmos_pi_5g_cand.spice"

PERIOD_2P5G = 0.4e-9      # 400 ps (2.500 GHz)
PERIOD_1P25G = 0.8e-9     # 800 ps (1.250 GHz)
UI_5G = 200e-12           # 200 ps (5 Gb/s)
FINE_LSB_PS = 6.25        # 400 ps / 64 = 6.25 ps
LOAD_FF = 40.0            # 40 fF per ckd0..3, cke0..3 phase

STOP = 5.0e-9
SAVE_FROM = 3.2e-9
MEAS_FROM = 3.2e-9        # 1.8 ns window = 2.25 full 1.25 GHz periods (guarantees >=2 rising crossings on all 8 phases)
STOP_RST = 5.6e-9
MEAS_FROM_RST = 3.6e-9    # 2.0 ns window after 1.60..1.95 ns rst_n release

CORNERS_4 = [
    Condition("tt", 1.80, 27),
    Condition("ss", 1.65, -40),
    Condition("ss", 1.65, 85),
    Condition("ff", 1.95, -40),
]
CORNERS_FAST = [
    Condition("tt", 1.80, 27),
    Condition("ss", 1.65, 85),
]

TEMPLATE = """\
RX 5G (2.5 GHz -> 1.25 GHz 8-ph) CMOS PI + Deterministic QDiv2 Verification
.lib "@MODEL_LIBRARY@" @CORNER@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "@DUT_SPICE@"
Vdd vdd 0 @SUPPLY@
* 8 rail-to-rail CMOS 2.500 GHz anchor clocks spaced 45 deg = 50.0 ps (20 ps edges, 50% duty)
Vc0 c0 0 PULSE(0 @SUPPLY@ 0.000n 20p 20p 180p 400p)
Vc1 c1 0 PULSE(0 @SUPPLY@ 0.050n 20p 20p 180p 400p)
Vc2 c2 0 PULSE(0 @SUPPLY@ 0.100n 20p 20p 180p 400p)
Vc3 c3 0 PULSE(0 @SUPPLY@ 0.150n 20p 20p 180p 400p)
Vc4 c4 0 PULSE(0 @SUPPLY@ 0.200n 20p 20p 180p 400p)
Vc5 c5 0 PULSE(0 @SUPPLY@ 0.250n 20p 20p 180p 400p)
Vc6 c6 0 PULSE(0 @SUPPLY@ 0.300n 20p 20p 180p 400p)
Vc7 c7 0 PULSE(0 @SUPPLY@ 0.350n 20p 20p 180p 400p)
* Reset released cleanly at @RST_T@
Vrst rst_n 0 PWL(0 0 @RST_T@ 0 @RST_T2@ @SUPPLY@)
* Commutator controls (pi_step_commutator.sv format)
Va0 a0 0 0
Va1 a1 0 0
Va2 a2 0 0
Va3 a3 0 0
Va4 a4 0 0
Va5 a5 0 0
Va6 a6 0 0
Va7 a7 0 0
Vb0 b0 0 0
Vb1 b1 0 0
Vb2 b2 0 0
Vb3 b3 0 0
Vb4 b4 0 0
Vb5 b5 0 0
Vb6 b6 0 0
Vb7 b7 0 0
Vf0 f0 0 0
Vf1 f1 0 0
Vf2 f2 0 0
Vf3 f3 0 0
Vf4 f4 0 0
Vf5 f5 0 0
Vf6 f6 0 0
Vf7 f7 0 0
Xdut c0 c1 c2 c3 c4 c5 c6 c7
+ a0 a1 a2 a3 a4 a5 a6 a7
+ b0 b1 b2 b3 b4 b5 b6 b7
+ f0 f1 f2 f3 f4 f5 f6 f7
+ rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd 0 serdes_rx_cmos_pi_8ph @PI_PARAMS@
* Realistic 40 fF 1.25 GHz DT slicer + deser16 clock loads per phase
Cd0 ckd0 0 40f
Cd1 ckd1 0 40f
Cd2 ckd2 0 40f
Cd3 ckd3 0 40f
Ce0 cke0 0 40f
Ce1 cke1 0 40f
Ce2 cke2 0 40f
Ce3 cke3 0 40f
.temp @TEMP_C@
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(c0) v(dp) v(dn) v(ep) v(en) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) v(vdd) i(Vdd)
.control
set filetype=binary
@CASES@
quit
.endc
.end
"""

# Separate-supply deck to measure exact static reset current of QDiv2 while 2.5 GHz PI clocks are actively toggling!
RESET_HYGIENE_TEMPLATE = """\
RX 5G Reset Hygiene & Determinism Check (Split PI/Div supplies)
.lib "@MODEL_LIBRARY@" @CORNER@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "@DUT_SPICE@"
Vdd_pi  vdd_pi  0 @SUPPLY@
Vdd_div vdd_div 0 @SUPPLY@
Vc0 c0 0 PULSE(0 @SUPPLY@ 0.000n 20p 20p 180p 400p)
Vc1 c1 0 PULSE(0 @SUPPLY@ 0.050n 20p 20p 180p 400p)
Vc2 c2 0 PULSE(0 @SUPPLY@ 0.100n 20p 20p 180p 400p)
Vc3 c3 0 PULSE(0 @SUPPLY@ 0.150n 20p 20p 180p 400p)
Vc4 c4 0 PULSE(0 @SUPPLY@ 0.200n 20p 20p 180p 400p)
Vc5 c5 0 PULSE(0 @SUPPLY@ 0.250n 20p 20p 180p 400p)
Vc6 c6 0 PULSE(0 @SUPPLY@ 0.300n 20p 20p 180p 400p)
Vc7 c7 0 PULSE(0 @SUPPLY@ 0.350n 20p 20p 180p 400p)
Vrst rst_n 0 PWL(0 0 @RST_T@ 0 @RST_T2@ @SUPPLY@)
Va0 a0 0 @SUPPLY@
Va1 a1 0 0
Va2 a2 0 0
Va3 a3 0 0
Va4 a4 0 0
Va5 a5 0 0
Va6 a6 0 0
Va7 a7 0 0
Vb0 b0 0 0
Vb1 b1 0 @SUPPLY@
Vb2 b2 0 0
Vb3 b3 0 0
Vb4 b4 0 0
Vb5 b5 0 0
Vb6 b6 0 0
Vb7 b7 0 0
Vf0 f0 0 0
Vf1 f1 0 0
Vf2 f2 0 0
Vf3 f3 0 0
Vf4 f4 0 0
Vf5 f5 0 0
Vf6 f6 0 0
Vf7 f7 0 0
Xpi c0 c1 c2 c3 c4 c5 c6 c7
+ a0 a1 a2 a3 a4 a5 a6 a7
+ b0 b1 b2 b3 b4 b5 b6 b7
+ f0 f1 f2 f3 f4 f5 f6 f7
+ dp dn ep en vdd_pi 0 serdes_rx_pi_rotator_2g @PI_ROT_PARAMS@
Xdiv dp dn ep en rst_n ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd_div 0 serdes_rx_qdiv2_8ph @DIV_PARAMS@
Cd0 ckd0 0 40f
Cd1 ckd1 0 40f
Cd2 ckd2 0 40f
Cd3 ckd3 0 40f
Ce0 cke0 0 40f
Ce1 cke1 0 40f
Ce2 cke2 0 40f
Ce3 cke3 0 40f
.temp @TEMP_C@
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(rst_n) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) i(Vdd_div) i(Vdd_pi)
.control
set filetype=binary
@CASES@
quit
.endc
.end
"""


def commutator_bits(code: int, supply: float) -> dict[str, float]:
    """Exact port encoding matching digital/rx/rtl/pi_step_commutator.sv."""
    q, f = divmod(code, 8)
    a, b, nb = (q, (q + 1) % 8, f) if q % 2 == 0 else ((q + 1) % 8, q, 8 - f)
    v = {}
    for i in range(8):
        v[f"Va{i}"] = supply if i == a else 0.0
        v[f"Vb{i}"] = supply if i == b else 0.0
        v[f"Vf{i}"] = supply if i < nb else 0.0
    return v


def split_pi_div_params(pi_params: str) -> tuple[str, str]:
    """Split unified serdes_rx_cmos_pi_8ph params into rotator params and qdiv2 params."""
    div_keys = {"wn_ld", "wn_le", "pn_div", "pn_ck", "wn_buf"}
    rot_toks, div_toks = [], []
    for tok in pi_params.split():
        k = tok.split("=", 1)[0].strip()
        if k in div_keys:
            div_toks.append(tok)
        else:
            rot_toks.append(tok)
    return " ".join(rot_toks), " ".join(div_toks)


def case_name(c: Condition, code: int) -> str:
    return f"{c.tag}_c{code:02d}"


def build_deck(c: Condition, codes: list[int], pi_params: str) -> str:
    s = c.supply
    blocks = []
    for code in codes:
        n = case_name(c, code)
        alters = [f"alter {k} dc={v}" for k, v in commutator_bits(code, s).items()]
        blocks.append("\n".join([
            f"* case {n}",
            *alters,
            f"tran 3p {STOP:.3e} {SAVE_FROM:.3e} 6p",
            "let pwr = -v(vdd)*i(Vdd)",
            f"write {n}.raw v(c0) v(dp) v(dn) v(ep) v(en) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) pwr",
            "destroy all",
        ]))
    return spice.render(
        TEMPLATE,
        **spice.corner_values(c),
        DUT_SPICE=str(DUT_SPICE),
        RST_T="1.40n",
        RST_T2="1.44n",
        PI_PARAMS=pi_params,
        CASES="\n".join(blocks),
    )


def rel_phase(t, y, ref, period, level_y=0.0, level_r=0.0, meas_from=MEAS_FROM):
    """Mean rising-crossing delay of y after ref, modulo period (in seconds)."""
    sel = t >= meas_from
    ey, py = crossings(t[sel], y[sel], level_y)
    er, pr = crossings(t[sel], ref[sel], level_r)
    ey, er = ey[py > 0], er[pr > 0]
    if len(ey) == 0 or len(er) == 0:
        return float("nan")
    d = np.array([x - er[np.searchsorted(er, x) - 1] for x in ey if np.searchsorted(er, x) > 0]) % period
    if len(d) == 0:
        return float("nan")
    ang = np.angle(np.mean(np.exp(2j * np.pi * d / period)))
    return float(ang / (2.0 * np.pi) * period % period)


def duty_cycle_pct(t, y, level, meas_from=MEAS_FROM):
    """Mean high-time duty cycle (%) between consecutive rising/falling crossings."""
    sel = t >= meas_from
    ec, pc = crossings(t[sel], y[sel], level)
    if len(ec) < 3:
        return float("nan")
    highs, periods = [], []
    for i in range(len(ec) - 2):
        if pc[i] > 0 and pc[i + 1] < 0 and pc[i + 2] > 0:
            highs.append(ec[i + 1] - ec[i])
            periods.append(ec[i + 2] - ec[i])
    if not highs:
        return float("nan")
    return float(100.0 * np.mean(np.array(highs) / np.array(periods)))


def analyse_wave_8ph(w: spice.Waves, supply: float, meas_from=MEAS_FROM) -> dict:
    vmid = 0.5 * supply
    names = ["v(ckd0)", "v(cke0)", "v(ckd1)", "v(cke1)", "v(ckd2)", "v(cke2)", "v(ckd3)", "v(cke3)"]
    ideal_ps = np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0])
    sel = w.t >= meas_from
    ref = w["v(ckd0)"]

    freqs, swings, duties, meas_ps = [], [], [], []
    for nm in names:
        y = w[nm]
        swings.append(float(np.ptp(y[sel])))
        duties.append(duty_cycle_pct(w.t, y, vmid, meas_from))
        e, p = crossings(w.t[sel], y[sel], vmid)
        er = e[p > 0]
        freqs.append(1.0 / (np.mean(np.diff(er)) * 1e9) if len(er) >= 2 else float("nan"))
        if nm == "v(ckd0)":
            meas_ps.append(0.0)
        else:
            meas_ps.append(rel_phase(w.t, y, ref, PERIOD_1P25G, vmid, vmid, meas_from) * 1e12)

    meas_ps = np.array(meas_ps)
    err_ps = (meas_ps - ideal_ps + 400.0) % 800.0 - 400.0

    # Specific D-E spacing: (cke_k - ckd_k) vs 100 ps for k=0..3
    de_pairs = [
        (meas_ps[1] - meas_ps[0]) % 800.0,
        (meas_ps[3] - meas_ps[2]) % 800.0,
        (meas_ps[5] - meas_ps[4]) % 800.0,
        (meas_ps[7] - meas_ps[6]) % 800.0,
    ]
    de_errs = [((x - 100.0 + 400.0) % 800.0 - 400.0) for x in de_pairs]

    # Specific quadrature spacing: (ckd_{k+1} - ckd_k) & (cke_{k+1} - cke_k) vs 200 ps
    quad_pairs = [
        (meas_ps[2] - meas_ps[0]) % 800.0,
        (meas_ps[4] - meas_ps[2]) % 800.0,
        (meas_ps[6] - meas_ps[4]) % 800.0,
        (meas_ps[0] - meas_ps[6]) % 800.0,
        (meas_ps[3] - meas_ps[1]) % 800.0,
        (meas_ps[5] - meas_ps[3]) % 800.0,
        (meas_ps[7] - meas_ps[5]) % 800.0,
        (meas_ps[1] - meas_ps[7]) % 800.0,
    ]
    quad_errs = [((x - 200.0 + 400.0) % 800.0 - 400.0) for x in quad_pairs]

    locked = all(np.isfinite(f) and abs(f - 1.25) < 0.02 for f in freqs)
    min_sw = float(min(swings))
    min_sw_pct = 100.0 * min_sw / supply
    duty_min = float(np.nanmin(duties)) if any(np.isfinite(duties)) else float("nan")
    duty_max = float(np.nanmax(duties)) if any(np.isfinite(duties)) else float("nan")
    de_max_abs = float(np.nanmax(np.abs(de_errs))) if any(np.isfinite(de_errs)) else float("nan")
    de_mean = float(np.nanmean(de_pairs)) if any(np.isfinite(de_pairs)) else float("nan")
    quad_max_abs = float(np.nanmax(np.abs(quad_errs))) if any(np.isfinite(quad_errs)) else float("nan")
    err8_max = float(np.nanmax(np.abs(err_ps))) if any(np.isfinite(err_ps)) else float("nan")

    # PI 2.5 GHz internal outputs (if saved)
    pi_diag = {}
    if all(k in w.names for k in ("v(dp)", "v(dn)", "v(ep)", "v(en)")):
        dp_diff = w["v(dp)"] - w["v(dn)"]
        ep_diff = w["v(ep)"] - w["v(en)"]
        pi_de = rel_phase(w.t, ep_diff, dp_diff, PERIOD_2P5G, 0.0, 0.0, meas_from) * 1e12
        pi_de_err = (pi_de - 100.0 + 200.0) % 400.0 - 200.0
        pi_diag = dict(
            dp_swing_v=float(np.ptp(w["v(dp)"][sel])),
            dp_duty_pct=duty_cycle_pct(w.t, w["v(dp)"], vmid, meas_from),
            dp_diff_duty_pct=duty_cycle_pct(w.t, dp_diff, 0.0, meas_from),
            pi_de_err_ps=float(pi_de_err),
        )

    return dict(
        locked=bool(locked),
        freq_ghz_min=float(np.nanmin(freqs)) if any(np.isfinite(freqs)) else float("nan"),
        freq_ghz_max=float(np.nanmax(freqs)) if any(np.isfinite(freqs)) else float("nan"),
        min_swing_v=min_sw,
        min_swing_pct=min_sw_pct,
        duty_min_pct=duty_min,
        duty_max_pct=duty_max,
        duties_pct=[float(d) for d in duties],
        de_mean_ps=de_mean,
        de_err_max_ps=de_max_abs,
        de_errs_ps=[float(x) for x in de_errs],
        quad_err_max_ps=quad_max_abs,
        max_8ph_err_ps=err8_max,
        phases_ps=[float(x) for x in meas_ps],
        err_ps=[float(x) for x in err_ps],
        **pi_diag,
    )


def analyse_condition(camp: Path, c: Condition, codes: list[int]) -> dict:
    vmid = 0.5 * c.supply
    ph_d_s, ph_ckd0_s, powers_mw = [], [], []
    per_code = []
    for code in codes:
        p = spice.case_output(camp / "corners", c.tag, f"{case_name(c, code)}.raw", t_end=STOP)
        if p is None:
            p = camp / "corners" / c.tag / f"{case_name(c, code)}.raw"
        assert p is not None and p.exists(), f"missing {case_name(c, code)}"
        w = spice.Waves(p)
        assert float(w.t[-1]) >= STOP * 0.99, f"truncated {p}: t_end={w.t[-1]}"
        dp_diff = w["v(dp)"] - w["v(dn)"]
        ph_d_s.append(rel_phase(w.t, dp_diff, w["v(c0)"], PERIOD_2P5G, 0.0, vmid))
        ph_ckd0_s.append(rel_phase(w.t, w["v(ckd0)"], w["v(c0)"], PERIOD_2P5G, vmid, vmid))
        sel = w.t >= MEAS_FROM
        pwr_mw = time_average(w["pwr"][sel], w.t[sel]) * 1e3
        powers_mw.append(pwr_mw)
        d8 = analyse_wave_8ph(w, c.supply)
        d8["code"] = code
        d8["power_mw"] = pwr_mw
        per_code.append(d8)

    # Unwrap phase vs code (in ps)
    ph_rad = np.array(ph_d_s) / PERIOD_2P5G * 2.0 * np.pi
    if np.all(np.isfinite(ph_rad)):
        ph_ps = np.unwrap(ph_rad) / (2.0 * np.pi) * PERIOD_2P5G * 1e12
        diffs = np.diff(ph_ps)
        d_codes = np.diff(np.array(codes, dtype=float))
        step_per_code = diffs / d_codes
        direction = float(np.sign(np.median(step_per_code))) if len(step_per_code) else 1.0
        step_ps = step_per_code * direction
        step_raw = diffs * direction
        span_ps = float((ph_ps[-1] - ph_ps[0]) * direction) if len(ph_ps) > 1 else 0.0
        # Best-fit / endpoint-fit INL over swept codes
        if len(codes) > 1:
            mean_step = span_ps / (codes[-1] - codes[0])
            ideal = ph_ps[0] + direction * mean_step * (np.array(codes) - codes[0])
            inl_ps = (ph_ps - ideal) * direction
        else:
            mean_step = FINE_LSB_PS
            inl_ps = np.zeros_like(ph_ps)
        mono = bool(np.all(step_raw > 0)) if len(step_raw) else True
        min_step_ps = float(np.min(step_ps)) if len(step_ps) else float("nan")
        max_step_ps = float(np.max(step_ps)) if len(step_ps) else float("nan")
        dnl_lsb = float(np.max(np.abs(step_ps / FINE_LSB_PS - 1.0))) if len(step_ps) else float("nan")
        inl_max_ps = float(np.max(np.abs(inl_ps)))
        inl_max_ui = inl_max_ps / 200.0
    else:
        ph_ps = np.full(len(codes), np.nan)
        inl_ps = np.full(len(codes), np.nan)
        mono = False
        min_step_ps = max_step_ps = dnl_lsb = inl_max_ps = inl_max_ui = span_ps = float("nan")

    all_locked = all(x["locked"] for x in per_code)
    min_sw_v = float(min(x["min_swing_v"] for x in per_code))
    min_sw_pct = float(min(x["min_swing_pct"] for x in per_code))
    duty_min = float(np.nanmin([x["duty_min_pct"] for x in per_code]))
    duty_max = float(np.nanmax([x["duty_max_pct"] for x in per_code]))
    de_err_max = float(np.nanmax([x["de_err_max_ps"] for x in per_code]))
    de_mean = float(np.nanmean([x["de_mean_ps"] for x in per_code]))
    quad_err_max = float(np.nanmax([x["quad_err_max_ps"] for x in per_code]))
    err8_max = float(np.nanmax([x["max_8ph_err_ps"] for x in per_code]))
    pi_de_err_max = float(np.nanmax([abs(x.get("pi_de_err_ps", np.nan)) for x in per_code]))
    dp_sw_min = float(np.nanmin([x.get("dp_swing_v", np.nan) for x in per_code]))
    dp_duty_min = float(np.nanmin([x.get("dp_duty_pct", np.nan) for x in per_code]))
    dp_duty_max = float(np.nanmax([x.get("dp_duty_pct", np.nan) for x in per_code]))
    pwr_mean_mw = float(np.mean(powers_mw))
    pjb = pwr_mean_mw / 5.0  # 5 Gb/s -> mW / (Gb/s) = pJ/b

    ok = bool(
        all_locked
        and min_sw_pct >= 90.0
        and 45.0 <= duty_min and duty_max <= 55.0
        and de_err_max <= 12.0
        and quad_err_max <= 10.0
        and mono
        and (np.isnan(inl_max_ps) or inl_max_ps <= 8.0)
    )

    return dict(
        condition=c.tag,
        supply_v=c.supply,
        temp_c=c.temp,
        codes=codes,
        locked=all_locked,
        min_swing_v=min_sw_v,
        min_swing_pct=min_sw_pct,
        duty_min_pct=duty_min,
        duty_max_pct=duty_max,
        de_mean_ps=de_mean,
        de_err_max_ps=de_err_max,
        quad_err_max_ps=quad_err_max,
        max_8ph_err_ps=err8_max,
        pi_de_err_max_ps=pi_de_err_max,
        dp_swing_min_v=dp_sw_min,
        dp_duty_range_pct=[dp_duty_min, dp_duty_max],
        monotonic=mono,
        step_min_ps=min_step_ps,
        step_max_ps=max_step_ps,
        dnl_lsb=dnl_lsb,
        inl_max_ps=inl_max_ps,
        inl_max_ui=inl_max_ui,
        span_ps=span_ps,
        power_mw=pwr_mean_mw,
        energy_pjb=pjb,
        ok=ok,
        phase_ps=[float(x) for x in ph_ps],
        inl_curve_ps=[float(x) for x in inl_ps],
    )


def run_reset_hygiene(camp: Path, conds: list[Condition], pi_params: str, workers: int) -> list[dict]:
    """Check static reset current (< 20 uA) + 8-phase rst_n release determinism across full 400 ps period."""
    rroot = camp / "reset_hygiene"
    rroot.mkdir(parents=True, exist_ok=True)
    rot_params, div_params = split_pi_div_params(pi_params)
    offsets_ps = [0.0, 50.0, 100.0, 150.0, 200.0, 250.0, 300.0, 350.0]

    jobs = []
    for c in conds:
        s = c.supply
        missing_idx = [
            idx for idx in range(len(offsets_ps))
            if spice.case_output(rroot, c.tag, f"rst_{idx}.raw", t_end=STOP_RST) is None
        ]
        if not missing_idx:
            continue
        blocks = []
        for idx in missing_idx:
            off = offsets_ps[idx]
            t1 = 1.60e-9 + off * 1e-12
            t2 = t1 + 40e-12
            # For idx==0 save from t=0 to measure exact static reset current during [1.0ns, 1.5ns] while PI runs rail-to-rail
            t_save = 0.0 if idx == 0 else 3.2e-9
            blocks.append("\n".join([
                f"* rst phase {off} ps",
                f"alter @Vrst[pwl] = [ 0 0 {t1:.4e} 0 {t2:.4e} {s} ]",
                f"tran 3p {STOP_RST:.3e} {t_save:.3e} 6p",
                f"write rst_{idx}.raw v(rst_n) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) i(Vdd_div) i(Vdd_pi)",
                "destroy all",
            ]))
        deck = spice.render(
            RESET_HYGIENE_TEMPLATE,
            **spice.corner_values(c),
            DUT_SPICE=str(DUT_SPICE),
            RST_T="1.60n",
            RST_T2="1.64n",
            PI_ROT_PARAMS=rot_params,
            DIV_PARAMS=div_params,
            CASES="\n".join(blocks),
        )
        rdir = spice.next_run_dir(rroot, c.tag)
        jobs.append((deck, rdir, dict(timeout_s=1800, meta=dict(condition=c.tag, test="reset_hygiene", missing=missing_idx))))

    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        assert ex.ok, (ex.run_dir, ex.log_failures)

    results = []
    for c in conds:
        errs_8ph, de_errs, locked_all = [], [], True
        i_rst_ua = float("nan")
        i_div_run_ma = float("nan")
        i_pi_run_ma = float("nan")
        for idx, off in enumerate(offsets_ps):
            p = spice.case_output(rroot, c.tag, f"rst_{idx}.raw", t_end=STOP_RST)
            assert p is not None, f"missing reset wave {c.tag} rst_{idx}.raw"
            w = spice.Waves(p)
            assert float(w.t[-1]) >= STOP_RST * 0.99, f"truncated reset wave {p}"
            if idx == 0:
                sel_rst = (w.t >= 1.0e-9) & (w.t <= 1.5e-9)
                i_rst_ua = abs(time_average(w["i(vdd_div)"][sel_rst], w.t[sel_rst])) * 1e6
                sel_run = w.t >= MEAS_FROM_RST
                i_div_run_ma = abs(time_average(w["i(vdd_div)"][sel_run], w.t[sel_run])) * 1e3
                i_pi_run_ma = abs(time_average(w["i(vdd_pi)"][sel_run], w.t[sel_run])) * 1e3
            d8 = analyse_wave_8ph(w, c.supply, meas_from=MEAS_FROM_RST)
            errs_8ph.append(d8["max_8ph_err_ps"])
            de_errs.append(d8["de_err_max_ps"])
            locked_all = locked_all and d8["locked"]
        zero_ambiguity = bool(locked_all and all(e < 15.0 for e in errs_8ph))
        ok = bool(zero_ambiguity and i_rst_ua < 20.0)
        results.append(dict(
            condition=c.tag,
            static_rst_current_ua=float(i_rst_ua),
            div_run_current_ma=float(i_div_run_ma),
            pi_run_current_ma=float(i_pi_run_ma),
            offsets_ps=offsets_ps,
            max_8ph_err_ps=[float(x) for x in errs_8ph],
            worst_8ph_err_ps=float(max(errs_8ph)),
            worst_de_err_ps=float(max(de_errs)),
            zero_180deg_ambiguity=zero_ambiguity,
            ok=ok,
        ))
    return results


def parse_codes(spec: str) -> list[int]:
    if ".." in spec:
        lo, hi = (int(x) for x in spec.split(".."))
        return list(range(lo, hi + 1))
    return [int(x) for x in spec.split(",")]


def print_table(rows: list[dict]):
    hdr = (
        f"{'condition':14s} | lock | sw%   | duty min/max %  | D-E mean (err) ps | "
        f"quad err | 8ph err | mono | step min/max ps | INL ps (UI)    | P mW (pJ/b)"
    )
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['condition']:14s} | {'YES ' if r['locked'] else 'FAIL'} | {r['min_swing_pct']:5.1f} | "
            f"{r['duty_min_pct']:5.2f} / {r['duty_max_pct']:5.2f}   | "
            f"{r['de_mean_ps']:6.2f} ({r['de_err_max_ps']:5.2f})   | "
            f"{r['quad_err_max_ps']:6.2f}   | {r['max_8ph_err_ps']:5.2f}   | "
            f"{'yes ' if r['monotonic'] else 'NO  '} | "
            f"{r['step_min_ps']:5.2f} / {r['step_max_ps']:5.2f}   | "
            f"{r['inl_max_ps']:5.2f} ({r['inl_max_ui']:.4f}) | "
            f"{r['power_mw']:5.2f} ({r['energy_pjb']:.2f}){'' if r['ok'] else ' FAIL'}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["sweep", "signoff"], default="sweep")
    ap.add_argument("--corners", choices=["fast", "cold", "4c"], default="fast")
    ap.add_argument("--codes", default=None)
    ap.add_argument("--pi", default="")
    ap.add_argument("--tag", default="")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--skip-reset", action="store_true")
    a = ap.parse_args()
    assert 1 <= a.workers <= 2, "Strict limit: max 2 concurrent ngspice processes!"

    if a.mode == "signoff":
        conds = CORNERS_4
        codes = parse_codes(a.codes) if a.codes else list(range(0, 17))
        camp = RESULTS_ROOT
    else:
        if a.corners == "fast":
            conds = CORNERS_FAST
        elif a.corners == "cold":
            conds = [Condition("ss", 1.65, -40), Condition("ff", 1.95, -40)]
        else:
            conds = CORNERS_4
        codes = parse_codes(a.codes) if a.codes else [0, 2, 4, 6, 8]
        sub = a.tag or time.strftime("sweep_%Y%m%dT%H%M%SZ", time.gmtime())
        camp = RESULTS_ROOT / "sweeps" / sub

    camp.mkdir(parents=True, exist_ok=True)

    jobs = []
    (camp / "corners").mkdir(parents=True, exist_ok=True)
    for c in conds:
        if a.mode == "signoff":
            missing_codes = [
                code for code in codes
                if spice.case_output(camp / "corners", c.tag, f"{case_name(c, code)}.raw", t_end=STOP) is None
            ]
            if not missing_codes:
                continue
            rdir = spice.next_run_dir(camp / "corners", c.tag)
            deck = build_deck(c, missing_codes, a.pi)
            jobs.append((deck, rdir, dict(timeout_s=3600, meta=dict(condition=c.tag, codes=missing_codes, pi=a.pi))))
        else:
            rdir = camp / "corners" / c.tag
            if rdir.exists():
                shutil.rmtree(rdir)
            deck = build_deck(c, codes, a.pi)
            jobs.append((deck, rdir, dict(timeout_s=2400, meta=dict(condition=c.tag, codes=codes, pi=a.pi))))

    t0 = time.time()
    print(f"5G CMOS PI ({a.mode}): {len(conds)} corners x {len(codes)} codes ({len(jobs)} decks to run), load={LOAD_FF:.0f} fF, workers={a.workers}", flush=True)
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    elapsed = time.time() - t0
    print(f"Transient simulations finished in {elapsed:.1f} s", flush=True)

    rows = [analyse_condition(camp, c, codes) for c in conds]
    print_table(rows)
    for r in rows:
        print(
            f"  [diag] {r['condition']:14s}: PI dp_sw={r['dp_swing_min_v']:.3f}V, "
            f"dp_duty={r['dp_duty_range_pct'][0]:.2f}..{r['dp_duty_range_pct'][1]:.2f}%, "
            f"PI_DE_err={r['pi_de_err_max_ps']:.2f}ps"
        )

    rst_rows = []
    if a.mode == "signoff" and not a.skip_reset:
        print("\nRunning 4-corner reset hygiene (<20 uA) + 8-phase determinism sweep...", flush=True)
        rst_rows = run_reset_hygiene(camp, conds, a.pi, a.workers)
        print(f"\n{'condition':14s} | I_rst uA | I_pi mA | I_div mA | worst 8ph err ps | zero 180-deg ambig | ok")
        for rr in rst_rows:
            print(
                f"{rr['condition']:14s} | {rr['static_rst_current_ua']:8.3f} | "
                f"{rr['pi_run_current_ma']:7.2f} | {rr['div_run_current_ma']:8.2f} | "
                f"{rr['worst_8ph_err_ps']:16.2f} | {str(rr['zero_180deg_ambiguity']):18s} | {rr['ok']}"
            )

    summary = dict(
        mode=a.mode,
        dut_spice=str(DUT_SPICE.relative_to(ROOT)),
        pi_params=a.pi,
        freq_pi_ghz=2.5,
        freq_div_ghz=1.25,
        load_ff=LOAD_FF,
        codes=codes,
        corners=rows,
        reset_hygiene=rst_rows,
        all_ok=bool(all(r["ok"] for r in rows) and (all(rr["ok"] for rr in rst_rows) if rst_rows else True)),
    )
    (camp / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(f"\nWrote summary: {(camp / 'summary.json').relative_to(ROOT)}")


if __name__ == "__main__":
    main()
