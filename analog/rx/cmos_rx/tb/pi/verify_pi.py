"""Verify 2 GHz 64-Code Pure CMOS Inverter PI + Deterministic Quadrature CMOS /2 (8-Phase 1 GHz).

    uv run python analog/rx/cmos_rx/tb/pi/verify_pi.py [stress | all | tags...] [--codes 0..63] [--pi ...] [--workers 2] [--resume DIR]

Checks:
  1. 6 extreme PVT corners (STRESS) x 64 codes (compatible with pi_step_commutator.sv):
     - 100% monotonicity across 64 codes
     - |INL| <= 0.02 UI (target <= 0.015 UI, 1 UI = 250 ps @ 4 Gb/s)
     - DNL (LSB)
     - 2 GHz quadrature error |D - E - 125 ps|
     - 8-phase 1 GHz spacing accuracy vs ideal [0, 125, 250, 375, 500, 625, 750, 875] ps
     - Total dynamic power (mW) of PI + /2 divider
  2. Reset determinism sweep: 8 rst_n release phases across 500 ps (0..437.5 ps in 62.5 ps steps)
     at TT and SS 1.65 -40 -> verifies zero 180 deg ambiguity between D and E dividers!
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import NOMINAL, STRESS, Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings, time_average

RESULTS = ROOT / "results/analog/rx/cmos_rx/pi"
PERIOD_2G = 0.5e-9
PERIOD_1G = 1.0e-9
UI = 250e-12
STOP = 5.5e-9
SAVE_FROM = 3.4e-9
MEAS_FROM = 3.5e-9
GATE_INL = 0.02
CHUNK_CODES = 32

TEMPLATE = """\
RX CMOS PI + Deterministic 8-Phase 1 GHz /2 Characterization
.lib "@MODEL_LIBRARY@" @CORNER@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "@PROJECT_ROOT@/analog/rx/cmos_rx/spice/rx_cmos_pi.spice"
Vdd vdd 0 @SUPPLY@
* 8 rail-to-rail CMOS 2 GHz anchor clocks spaced 45 deg = 62.5 ps (25 ps edges)
Vc0 c0 0 PULSE(0 @SUPPLY@ 0.0000n 25p 25p 225p 500p)
Vc1 c1 0 PULSE(0 @SUPPLY@ 0.0625n 25p 25p 225p 500p)
Vc2 c2 0 PULSE(0 @SUPPLY@ 0.1250n 25p 25p 225p 500p)
Vc3 c3 0 PULSE(0 @SUPPLY@ 0.1875n 25p 25p 225p 500p)
Vc4 c4 0 PULSE(0 @SUPPLY@ 0.2500n 25p 25p 225p 500p)
Vc5 c5 0 PULSE(0 @SUPPLY@ 0.3125n 25p 25p 225p 500p)
Vc6 c6 0 PULSE(0 @SUPPLY@ 0.3750n 25p 25p 225p 500p)
Vc7 c7 0 PULSE(0 @SUPPLY@ 0.4375n 25p 25p 225p 500p)
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
* Realistic 1 GHz slicer clock input loads (~12 fF per phase)
Cd0 ckd0 0 12f
Cd1 ckd1 0 12f
Cd2 ckd2 0 12f
Cd3 ckd3 0 12f
Ce0 cke0 0 12f
Ce1 cke1 0 12f
Ce2 cke2 0 12f
Ce3 cke3 0 12f
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


def case_name(c: Condition, code: int) -> str:
    return f"{c.tag}_c{code:02d}"


def build_deck(cases, pi_params: str) -> str:
    c0, _ = cases[0]
    blocks = []
    for c, code in cases:
        n = case_name(c, code)
        s = c.supply
        alters = [
            f"option temp={c.temp}",
            f"alter Vdd dc={s}",
            f"alter @Vc0[pulse] = [ 0 {s} 0.0000n 25p 25p 225p 500p ]",
            f"alter @Vc1[pulse] = [ 0 {s} 0.0625n 25p 25p 225p 500p ]",
            f"alter @Vc2[pulse] = [ 0 {s} 0.1250n 25p 25p 225p 500p ]",
            f"alter @Vc3[pulse] = [ 0 {s} 0.1875n 25p 25p 225p 500p ]",
            f"alter @Vc4[pulse] = [ 0 {s} 0.2500n 25p 25p 225p 500p ]",
            f"alter @Vc5[pulse] = [ 0 {s} 0.3125n 25p 25p 225p 500p ]",
            f"alter @Vc6[pulse] = [ 0 {s} 0.3750n 25p 25p 225p 500p ]",
            f"alter @Vc7[pulse] = [ 0 {s} 0.4375n 25p 25p 225p 500p ]",
            f"alter @Vrst[pwl] = [ 0 0 0.70n 0 0.75n {s} ]",
        ] + [f"alter {k} dc={v}" for k, v in commutator_bits(code, s).items()]
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
        **spice.corner_values(c0),
        RST_T="0.70n",
        RST_T2="0.75n",
        PI_PARAMS=pi_params,
        CASES="\n".join(blocks),
    )


def rel_phase(t, y, ref, period, level_y=0.0, level_r=0.0):
    """Mean rising-crossing delay of y after ref, modulo period (in seconds)."""
    sel = t >= MEAS_FROM
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


def analyse_8ph(w: spice.Waves, supply: float):
    """Verify 8-phase 1 GHz divider outputs relative to ckd0: ideal = [0, 125, 250, 375, 500, 625, 750, 875] ps."""
    vmid = 0.5 * supply
    names = ["v(ckd0)", "v(cke0)", "v(ckd1)", "v(cke1)", "v(ckd2)", "v(cke2)", "v(ckd3)", "v(cke3)"]
    ideal_ps = np.array([0.0, 125.0, 250.0, 375.0, 500.0, 625.0, 750.0, 875.0])
    ref = w["v(ckd0)"]
    # Check 1 GHz frequency of ckd0
    sel = w.t >= MEAS_FROM
    e0, p0 = crossings(w.t[sel], ref[sel], vmid)
    e0 = e0[p0 > 0]
    f_ghz = 1.0 / (np.mean(np.diff(e0)) * 1e9) if len(e0) >= 2 else float("nan")
    meas_ps = []
    swings = []
    for nm in names:
        y = w[nm]
        swings.append(float(np.ptp(y[sel])))
        if nm == "v(ckd0)":
            meas_ps.append(0.0)
        else:
            meas_ps.append(rel_phase(w.t, y, ref, PERIOD_1G, vmid, vmid) * 1e12)
    meas_ps = np.array(meas_ps)
    err_ps = (meas_ps - ideal_ps + 500.0) % 1000.0 - 500.0
    return dict(
        freq_ghz=float(f_ghz),
        phases_ps=meas_ps.tolist(),
        err_ps=err_ps.tolist(),
        max_8ph_err_ps=float(np.max(np.abs(err_ps))),
        min_swing_v=float(min(swings)),
    )


def chunk_sub(c: Condition, code: int) -> str:
    return f"{c.tag}_g{code // CHUNK_CODES}"


def analyse_condition(camp: Path, c: Condition, codes: list[int]) -> dict:
    vmid = 0.5 * c.supply
    ph_d, de_ps, power_mw, max_8ph_err, min_sw = [], [], [], [], []
    for code in codes:
        p = spice.case_output(camp, chunk_sub(c, code), f"{case_name(c, code)}.raw", t_end=STOP)
        if p is None:
            p = spice.case_output(camp, c.process, f"{case_name(c, code)}.raw", t_end=STOP)
        assert p is not None, f"missing {case_name(c, code)}"
        w = spice.Waves(p)
        dp_diff = w["v(dp)"] - w["v(dn)"]
        ep_diff = w["v(ep)"] - w["v(en)"]
        ph_d.append(rel_phase(w.t, dp_diff, w["v(c0)"], PERIOD_2G, 0.0, vmid))
        de = rel_phase(w.t, ep_diff, dp_diff, PERIOD_2G, 0.0, 0.0) * 1e12
        # Quad error vs 125 ps
        de_err = (de - 125.0 + 250.0) % 500.0 - 250.0
        de_ps.append(de_err)
        sel = w.t >= MEAS_FROM
        power_mw.append(time_average(w["pwr"][sel], w.t[sel]) * 1e3)
        d8 = analyse_8ph(w, c.supply)
        max_8ph_err.append(d8["max_8ph_err_ps"])
        min_sw.append(d8["min_swing_v"])

    ph_ui = np.unwrap(np.array(ph_d) / PERIOD_2G * 2.0 * np.pi) / (2.0 * np.pi) * PERIOD_2G / UI
    step = np.diff(ph_ui)
    direction = float(np.sign(np.median(step))) if len(step) else 1.0
    step = step * direction
    lsb = 2.0 / 64.0  # 1/32 UI = 7.8125 ps
    span = float((ph_ui[-1] - ph_ui[0]) * direction) if len(ph_ui) > 1 else 0.0
    fit = ph_ui[0] + direction * np.mean(step) * np.arange(len(codes)) if len(step) else ph_ui
    inl = (ph_ui - fit) * direction
    mono = bool(np.all(step > 0)) if len(step) else True
    inl_max = float(np.max(np.abs(inl)))
    dnl_max = float(np.max(np.abs(step / lsb - np.mean(step) / lsb))) if len(step) else 0.0
    quad_max_ps = float(np.max(np.abs(de_ps)))
    ph8_max_ps = float(np.max(max_8ph_err))
    ok = bool(mono and inl_max <= GATE_INL and ph8_max_ps <= 15.0 and min(min_sw) > 0.9 * c.supply)
    return dict(
        condition=c.tag,
        codes=codes,
        monotonic=mono,
        step_min_lsb=float(step.min() / lsb) if len(step) else 0.0,
        step_max_lsb=float(step.max() / lsb) if len(step) else 0.0,
        dnl_lsb=dnl_max,
        inl_ui=inl_max,
        inl_ps=inl_max * 250.0,
        span_ui=span,
        quad_err_ps=quad_max_ps,
        quad_err_ui=quad_max_ps / 250.0,
        max_8ph_err_ps=ph8_max_ps,
        min_swing_v=float(min(min_sw)),
        power_mw=float(np.mean(power_mw)),
        ok=ok,
        phase_ui=ph_ui.tolist(),
        inl_curve_ui=inl.tolist(),
    )


def run_reset_determinism(camp: Path, pi_params: str, workers: int, analyse_only: bool):
    """Verify zero 180 deg ambiguity across 8 rst_n release phases spanning a full 500 ps 2 GHz cycle."""
    rdir_root = camp / "reset_det"
    rdir_root.mkdir(parents=True, exist_ok=True)
    test_conds = [NOMINAL, Condition("ss", 1.65, -40)]
    offsets_ps = [0.0, 62.5, 125.0, 187.5, 250.0, 312.5, 375.0, 437.5]
    jobs = []
    for c in test_conds:
        s = c.supply
        blocks = []
        for idx, off in enumerate(offsets_ps):
            t1 = 0.60e-9 + off * 1e-12
            t2 = t1 + 40e-12
            alters = [
                f"alter @Vrst[pwl] = [ 0 0 {t1:.4e} 0 {t2:.4e} {s} ]",
            ] + [f"alter {k} dc={v}" for k, v in commutator_bits(0, s).items()]
            blocks.append("\n".join([
                f"* rst phase {off} ps",
                *alters,
                f"tran 3p {STOP:.3e} {SAVE_FROM:.3e} 6p",
                f"write rst_{idx}.raw v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3)",
                "destroy all",
            ]))
        deck = spice.render(
            TEMPLATE,
            **spice.corner_values(c),
            RST_T="0.60n",
            RST_T2="0.64n",
            PI_PARAMS=pi_params,
            CASES="\n".join(blocks),
        )
        rdir = rdir_root / c.tag
        if not (rdir / "execution.json").exists():
            if rdir.exists() and not analyse_only:
                shutil.rmtree(rdir)
            if not analyse_only:
                jobs.append((deck, rdir, dict(meta=dict(condition=c.tag, test="reset_determinism"))))

    for ex in ([] if analyse_only else spice.run_many(jobs, workers=workers, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)

    print("\n=== Reset Determinism Check (8 rst_n release phases across 500 ps) ===")
    all_ok = True
    out = []
    for c in test_conds:
        errs = []
        for idx, off in enumerate(offsets_ps):
            w = spice.Waves(rdir_root / c.tag / f"rst_{idx}.raw")
            d8 = analyse_8ph(w, c.supply)
            errs.append(d8["max_8ph_err_ps"])
        ok = all(e < 15.0 for e in errs)
        all_ok = all_ok and ok
        out.append(dict(condition=c.tag, offsets_ps=offsets_ps, max_8ph_err_ps=errs, ok=ok))
        print(f"  {c.tag:15s}: max 8-phase err across 8 rst phases = {max(errs):.2f} ps (zero 180-deg flips: {ok})")
    (rdir_root / "summary.json").write_text(json.dumps(out, indent=1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--codes", default="0..63")
    ap.add_argument("--pi", default="")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--skip-reset-det", action="store_true")
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    assert 1 <= a.workers <= 2, "Max 2 concurrent ngspice workers allowed"

    lo, hi = (int(x) for x in a.codes.split(".."))
    codes = list(range(lo, hi + 1))
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)

    keys = [(c, code) for c in conds for code in codes]
    by_chunk = {}
    for k in keys:
        by_chunk.setdefault(chunk_sub(*k), []).append(k)

    jobs = []
    for sub, chunk_cases in by_chunk.items():
        missing = [k for k in chunk_cases if spice.case_output(camp, sub, f"{case_name(*k)}.raw", t_end=STOP) is None]
        if missing and not a.analyse_only:
            rdir = spice.next_run_dir(camp, sub)
            jobs.append((build_deck(missing, a.pi), rdir,
                         dict(timeout_s=2400, meta=dict(chunk=sub, cases=[case_name(*k) for k in missing], pi=a.pi))))

    print(f"CMOS PI + 8-ph /2: {len(keys)} cases in {len(by_chunk)} decks ({len(jobs)} to run)", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(jobs, workers=a.workers, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)

    rows = [analyse_condition(camp, c, codes) for c in conds]
    (camp / "summary.json").write_text(json.dumps(rows, indent=1, default=float))

    print(f"\n{'condition':15s} | mono | step min/max LSB | DNL LSB | INL UI (ps)   | |D-E-125| ps | 8ph err ps | P mW")
    for r in rows:
        print(
            f"{r['condition']:15s} | {'yes' if r['monotonic'] else 'NO '}  | "
            f"{r['step_min_lsb']:5.2f}/{r['step_max_lsb']:5.2f}      | {r['dnl_lsb']:5.2f}   | "
            f"{r['inl_ui']:.4f} ({r['inl_ps']:4.2f}) | {r['quad_err_ps']:8.2f}     | "
            f"{r['max_8ph_err_ps']:6.2f}     | {r['power_mw']:5.2f} {'' if r['ok'] else ' FAIL'}"
        )

    if not a.skip_reset_det:
        run_reset_determinism(camp, a.pi, a.workers, a.analyse_only)

    print(f"\nPI results: {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
