"""Verify 1 GHz Double-Tail Dynamic CMOS Slicer (serdes_rx_dt_slicer):
  1. pvt  : 45-corner PVT at Vcm=1.45 V + Vcm sweep (1.15..1.65 V) on 6 extreme corners:
            100% decision accuracy (+/-10 mV, +/-50 mV), clk->q delay (< 250 ps),
            zero hysteresis (-100mV->+10mV & +100mV->-10mV), kickback on 600 Ohm CTLE source,
            and dynamic power (uW/slicer).
  2. trim : 6-bit offset trim sweep (codes 0..63) on TT 1.8 27, SS 1.65 85, FF 1.95 -40:
            monotonicity, range (>= +/-30 mV), LSB step (<= 1.5 mV).
  3. mc   : 200-sample mismatch MC at tt_v1800_t27_mm & ss_v1650_t-40_mm:
            raw 1-sigma input-referred offset (mV) vs +/-3 sigma inside trim range.

Usage:
    uv run python analog/rx/cmos_rx/tb/slicer/verify_slicer.py --mode [pvt|trim|mc|all] [--conds stress|all] [--workers 2] [--resume DIR]
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, spice
from serdes_flow.corners import NOMINAL, STRESS, Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings, time_average

RESULTS = ROOT / "results/analog/rx/cmos_rx/slicer"

# ---------------------------------------------------------------------------
# 1. PVT / Hysteresis / Kickback / Vcm-sweep bench (12 ns transient per case)
# ---------------------------------------------------------------------------
PVT_T_END = 12e-9
PVT_SAVE_FROM = 0.5e-9

# 11 active clock rising edges at 1.0, 2.0, ..., 11.0 ns (500 ps high / 500 ps low)
# Expected decisions:
#   cyc 1 (1ns):  +50mV -> 1 (warmup)
#   cyc 2 (2ns):  -50mV -> 0 (50mV 1->0)
#   cyc 3 (3ns):  +50mV -> 1 (50mV 0->1)
#   cyc 4 (4ns):  -10mV -> 0 (10mV 1->0)
#   cyc 5 (5ns):  +10mV -> 1 (10mV 0->1)
#   cyc 6 (6ns): -100mV -> 0 (hyst setup -)
#   cyc 7 (7ns):  +10mV -> 1 (hyst test -100->+10)
#   cyc 8 (8ns): +100mV -> 1 (hyst setup +)
#   cyc 9 (9ns):  -10mV -> 0 (hyst test +100->-10)
#   cyc 10(10ns):-100mV -> 0 (kickback test)
#   cyc 11(11ns): +10mV -> 1 (hyst+kickback)
PVT_SEQ_MV = [50, -50, 50, -10, 10, -100, 10, 100, -10, -100, 10]


def _pwl_diff(seq_mv, half_scale=0.5):
    """Build differential PWL changing cleanly at t = 0.65, 1.65, ..., 10.65 ns (350 ps before each clk rise)."""
    pts = [f"0 {seq_mv[0] * 1e-3 * half_scale:.6f}"]
    for k, mv in enumerate(seq_mv):
        v = mv * 1e-3 * half_scale
        if k > 0:
            t_chg = (k + 0.60) * 1e-9
            v_prev = seq_mv[k - 1] * 1e-3 * half_scale
            pts.append(f"{t_chg:.3e} {v_prev:.6f}")
            pts.append(f"{t_chg + 40e-12:.3e} {v:.6f}")
    pts.append(f"{PVT_T_END:.3e} {seq_mv[-1] * 1e-3 * half_scale:.6f}")
    return " ".join(pts)


PVT_TEMPLATE = """\
RX Double-Tail Slicer PVT / Hysteresis / Kickback / Power bench
.lib "@MODEL_LIBRARY@" @CORNER@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "@PROJECT_ROOT@/analog/rx/cmos_rx/spice/rx_dt_sampler.spice"
Vdd vdd 0 @SUPPLY@
Vcm cm 0 @VCM@
* 1 GHz CMOS clock: rising at 1.0, 2.0, ..., 11.0 ns (500 ps high / 500 ps low, 25 ps edges)
Vclk clk 0 PULSE(0 @SUPPLY@ 0.9875n 25p 25p 475p 1n)
* Differential stimulus through 600 Ohm CTLE output impedance (measures realistic kickback!)
Vdp dsrc_p cm PWL(@PWL_P@)
Vdn dsrc_n cm PWL(@PWL_N@)
Rsp dsrc_p inp 600
Rsn dsrc_n inn 600
* Realistic CTLE node cap (~20 fF parasitic + wiring)
Ccp inp 0 20f
Ccn inn 0 20f
* Trim centered at code 32 (t5=1, t4..t0=0)
Vt5 t5 0 @SUPPLY@
Vt4 t4 0 0
Vt3 t3 0 0
Vt2 t2 0 0
Vt1 t1 0 0
Vt0 t0 0 0
Xdut inp inn clk qp qn t5 t4 t3 t2 t1 t0 vdd 0 serdes_rx_dt_slicer @SLICER_PARAMS@
* Realistic downstream deserializer latch input load
Clp qp 0 10f
Cln qn 0 10f
.temp @TEMP_C@
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(clk) v(qp) v(qn) v(inp) v(inn) v(dsrc_p) v(dsrc_n) v(vdd) i(Vdd)
.control
set filetype=binary
@CASES@
quit
.endc
.end
"""


def pvt_case_name(c: Condition, vcm: float) -> str:
    return f"{c.tag}_cm{round(vcm * 1000)}"


def build_pvt_deck(cases, slicer_params: str) -> str:
    c0, vcm0 = cases[0]
    blocks = []
    for c, vcm in cases:
        name = pvt_case_name(c, vcm)
        blocks.append("\n".join([
            f"* case {name}",
            f"option temp={c.temp}",
            f"alter Vdd dc={c.supply}",
            f"alter Vt5 dc={c.supply}",
            f"alter Vcm dc={vcm}",
            f"alter @Vclk[pulse] = [ 0 {c.supply} 0.9875n 25p 25p 475p 1n ]",
            f"tran 2p {PVT_T_END:.3e} {PVT_SAVE_FROM:.3e} 4p",
            "let pwr = -v(vdd)*i(Vdd)",
            "let kb_diff = (v(inp)-v(inn)) - (v(dsrc_p)-v(dsrc_n))",
            "let kb_cm = 0.5*(v(inp)+v(inn)) - 0.5*(v(dsrc_p)+v(dsrc_n))",
            f"write {name}.raw v(clk) v(qp) v(qn) kb_diff kb_cm pwr",
            "destroy all",
        ]))
    return spice.render(
        PVT_TEMPLATE,
        **spice.corner_values(c0),
        VCM=vcm0,
        PWL_P=_pwl_diff(PVT_SEQ_MV, +0.5),
        PWL_N=_pwl_diff(PVT_SEQ_MV, -0.5),
        SLICER_PARAMS=slicer_params,
        CASES="\n".join(blocks),
    )


def analyse_pvt_case(path: Path, c: Condition, vcm: float) -> dict:
    w = spice.Waves(path)
    t = w.t
    vmid = 0.5 * c.supply
    clk_r, pol = crossings(t, w["v(clk)"], vmid)
    clk_r = clk_r[pol > 0]
    qp, qn = w["v(qp)"], w["v(qn)"]

    correct = 0
    delays_50, delays_10, delays_hyst = [], [], []
    for idx, (tc, mv) in enumerate(zip(clk_r[: len(PVT_SEQ_MV)], PVT_SEQ_MV)):
        exp = 1 if mv > 0 else 0
        # Sample settled output at tc + 450 ps (just before precharge ends)
        t_samp = tc + 450e-12
        vp = float(np.interp(t_samp, t, qp))
        vn = float(np.interp(t_samp, t, qn))
        got = 1 if (vp > vmid and vn < vmid) else (0 if (vp < vmid and vn > vmid) else -1)
        if got == exp:
            correct += 1
        # Measure clk->q delay on switching cycles
        if idx >= 1 and ((PVT_SEQ_MV[idx] > 0) != (PVT_SEQ_MV[idx - 1] > 0)):
            mask = (t >= tc) & (t <= tc + 500e-12)
            cr_t, _ = crossings(t[mask], qp[mask] - qn[mask], 0.0)
            td = float(cr_t[0] - tc) if len(cr_t) else float("nan")
            if idx in (1, 2):
                delays_50.append(td)
            elif idx in (3, 4):
                delays_10.append(td)
            elif idx in (6, 8, 10):
                delays_hyst.append(td)

    # Kickback peak during decision window (t >= 2 ns, outside PWL input transitions [k+0.58, k+0.70])
    # Measure kickback strictly in [tc - 50 ps, tc + 400 ps] around clock edges (clean of input step!)
    kb_mask = np.zeros_like(t, dtype=bool)
    for tc in clk_r[1:]:
        kb_mask |= (t >= tc - 20e-12) & (t <= tc + 400e-12)
    kb_diff_pk = float(np.max(np.abs(w["kb_diff"][kb_mask])))
    kb_cm_pk = float(np.max(np.abs(w["kb_cm"][kb_mask])))

    # Dynamic power averaged over [2.0 ns, 11.0 ns] (9 full 1 GHz cycles)
    pmask = (t >= 2.0e-9) & (t <= 11.0e-9)
    pwr_uw = time_average(w["pwr"][pmask], t[pmask]) * 1e6

    td50 = float(np.nanmax(delays_50)) * 1e12 if delays_50 else float("nan")
    td10 = float(np.nanmax(delays_10)) * 1e12 if delays_10 else float("nan")
    tdh = float(np.nanmax(delays_hyst)) * 1e12 if delays_hyst else float("nan")
    max_td = float(np.nanmax([td50, td10, tdh]))
    ok = (correct == len(PVT_SEQ_MV)) and np.isfinite(max_td) and (max_td < 250.0)
    return dict(
        condition=c.tag,
        vcm=vcm,
        correct=correct,
        total=len(PVT_SEQ_MV),
        td_50mv_ps=td50,
        td_10mv_ps=td10,
        td_hyst_ps=tdh,
        td_max_ps=max_td,
        kb_diff_mv=kb_diff_pk * 1e3,
        kb_cm_mv=kb_cm_pk * 1e3,
        power_uw=pwr_uw,
        ok=bool(ok),
    )


def run_pvt(camp: Path, conds, workers: int, slicer_params: str, analyse_only: bool):
    # Full grid at Vcm=1.45 V + Vcm sweep (1.15, 1.30, 1.65) on STRESS corners
    cases = [(c, 1.45) for c in conds]
    stress_set = set(STRESS)
    for c in conds:
        if c in stress_set:
            for vcm in (1.15, 1.30, 1.65):
                cases.append((c, vcm))

    by_proc = {}
    for k in cases:
        by_proc.setdefault(k[0].process, []).append(k)

    pvt_dir = camp / "pvt"
    pvt_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for proc, proc_cases in by_proc.items():
        missing = [
            k for k in proc_cases
            if spice.case_output(pvt_dir, proc, f"{pvt_case_name(*k)}.raw", t_end=PVT_T_END) is None
        ]
        if missing and not analyse_only:
            rdir = spice.next_run_dir(pvt_dir, proc)
            jobs.append((build_pvt_deck(missing, slicer_params), rdir,
                         dict(meta=dict(process=proc, cases=[pvt_case_name(*k) for k in missing]))))

    print(f"Slicer PVT: {len(cases)} total cases ({len(conds)} corners @ 1.45V + Vcm sweep on stress), {len(jobs)} decks to run", flush=True)
    for ex in ([] if analyse_only else spice.run_many(jobs, workers=workers, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)

    rows = []
    for c, vcm in cases:
        p = spice.case_output(pvt_dir, c.process, f"{pvt_case_name(c, vcm)}.raw", t_end=PVT_T_END)
        assert p is not None, f"missing {pvt_case_name(c, vcm)}"
        rows.append(analyse_pvt_case(p, c, vcm))

    (pvt_dir / "summary.json").write_text(json.dumps(rows, indent=1, default=float))
    nom_rows = [r for r in rows if abs(r["vcm"] - 1.45) < 1e-6]
    vcm_rows = [r for r in rows if abs(r["vcm"] - 1.45) >= 1e-6]

    print(f"\n=== Slicer 45-Corner PVT @ Vcm=1.45 V ({len(nom_rows)} corners) ===")
    print(f"Pass: {sum(r['ok'] for r in nom_rows)}/{len(nom_rows)} | "
          f"Worst clk->q (50mV): {max(r['td_50mv_ps'] for r in nom_rows):.1f} ps | "
          f"(10mV): {max(r['td_10mv_ps'] for r in nom_rows):.1f} ps | "
          f"(hyst -100->+10mV): {max(r['td_hyst_ps'] for r in nom_rows):.1f} ps | "
          f"Kickback diff/CM max: {max(r['kb_diff_mv'] for r in nom_rows):.1f}/{max(r['kb_cm_mv'] for r in nom_rows):.1f} mV | "
          f"Power: {min(r['power_uw'] for r in nom_rows):.1f}..{max(r['power_uw'] for r in nom_rows):.1f} uW")
    worst = max(nom_rows, key=lambda r: r["td_max_ps"])
    tt = next((r for r in nom_rows if r["condition"] == "tt_v1800_t27"), nom_rows[0])
    print(f"  TT 1.8V 27C: td_50={tt['td_50mv_ps']:.1f} ps, td_10={tt['td_10mv_ps']:.1f} ps, td_hyst={tt['td_hyst_ps']:.1f} ps, "
          f"kb_diff={tt['kb_diff_mv']:.1f} mV, P={tt['power_uw']:.1f} uW")
    print(f"  Worst ({worst['condition']}): td_50={worst['td_50mv_ps']:.1f} ps, td_10={worst['td_10mv_ps']:.1f} ps, "
          f"td_hyst={worst['td_hyst_ps']:.1f} ps, ok={worst['ok']}")
    if vcm_rows:
        print(f"=== Vcm Sweep (1.15/1.30/1.65 V on stress corners): Pass {sum(r['ok'] for r in vcm_rows)}/{len(vcm_rows)} | "
              f"Worst td={max(r['td_max_ps'] for r in vcm_rows):.1f} ps ===")
        for r in vcm_rows:
            if not r["ok"]:
                print(f"  FAIL {r['condition']} Vcm={r['vcm']}: {r['correct']}/{r['total']} td={r['td_max_ps']:.1f} ps")
    return rows


# ---------------------------------------------------------------------------
# 2. 6-Bit Offset Trim Sweep (codes 0..63 via linear Vdm ramp -> exact Vos)
# ---------------------------------------------------------------------------
TRIM_CONDS = [NOMINAL, Condition("ss", 1.65, 85), Condition("ff", 1.95, -40)]
# Ramp Vdm from -60 mV to +60 mV at 0.5 mV/ns -> 240 ns -> +/-0.25 mV resolution
# Wait: to be fast AND super accurate (+/-0.25 mV) across all 64 codes, use a 60 ns window
# centered on estimated Vos? Even better: 200 ns ramp (-60..+60 mV at 0.6 mV/ns -> 0.3 mV resolution)
# is only 200 cycles x 64 codes = 12.8 us (~12 s per corner in ngspice!).
TRIM_V_START = -0.062
TRIM_V_STOP = +0.062
TRIM_T_STOP = 249e-9   # 0.5 mV/ns slope -> 0.5 mV/cycle -> resolves <=1.0 mV LSBs cleanly!
TRIM_SLOPE = (TRIM_V_STOP - TRIM_V_START) / 248e-9  # 0.5 mV/ns


TRIM_TEMPLATE = """\
RX Double-Tail Slicer 6-Bit Offset Trim Sweep (codes 0..63)
.lib "@MODEL_LIBRARY@" @CORNER@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "@PROJECT_ROOT@/analog/rx/cmos_rx/spice/rx_dt_sampler.spice"
Vdd vdd 0 @SUPPLY@
Vcm cm 0 1.45
* 1 GHz clock: rising at 1.0, 2.0, ..., 248.0 ns
Vclk clk 0 PULSE(0 @SUPPLY@ 0.9875n 25p 25p 475p 1n)
* Linear differential ramp: at t = k ns, V(inp)-V(inn) = V_START + SLOPE * (t - 1n)
Vdm dm 0 PWL(0 @V_START@ 1n @V_START@ 249n @V_STOP@)
Eip inp cm dm 0  0.5
Ein inn cm dm 0 -0.5
Vt5 t5 0 0
Vt4 t4 0 0
Vt3 t3 0 0
Vt2 t2 0 0
Vt1 t1 0 0
Vt0 t0 0 0
Xdut inp inn clk qp qn t5 t4 t3 t2 t1 t0 vdd 0 serdes_rx_dt_slicer @SLICER_PARAMS@
Clp qp 0 10f
Cln qn 0 10f
.temp @TEMP_C@
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(qp)
.control
@CASES@
quit
.endc
.end
"""


def build_trim_deck(c: Condition, slicer_params: str) -> str:
    vmid = 0.5 * c.supply
    blocks = []
    for code in range(64):
        alters = [f"alter Vt{b} dc={c.supply if ((code >> b) & 1) else 0.0}" for b in range(6)]
        blocks.append("\n".join([
            f"* code {code}",
            *alters,
            f"tran 5p {TRIM_T_STOP:.3e} 0 10p",
            f"meas tran t_trip when v(qp)={vmid:.4f} rise=1 td=1.5n",
            f"let vos_mv = ({TRIM_V_START} + {TRIM_SLOPE} * (t_trip - 1.5e-9)) * 1e3",
            f"echo {code} $&t_trip $&vos_mv >> trim.tsv",
            "destroy all",
        ]))
    return spice.render(
        TRIM_TEMPLATE,
        **spice.corner_values(c),
        V_START=f"{TRIM_V_START:.6f}",
        V_STOP=f"{TRIM_V_STOP:.6f}",
        SLICER_PARAMS=slicer_params,
        CASES="\n".join(blocks),
    )


def read_trim_tsv(path: Path):
    rows = []
    for line in path.read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            vals = [float(x) for x in parts]
        except ValueError:
            continue
        rows.append(dict(code=int(round(vals[0])), t_trip_ns=vals[1] * 1e9, vos_mv=vals[2]))
    return rows


def run_trim(camp: Path, workers: int, slicer_params: str, analyse_only: bool):
    trim_dir = camp / "trim"
    trim_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for c in TRIM_CONDS:
        rdir = trim_dir / c.tag
        if (rdir / "execution.json").exists() and (rdir / "trim.tsv").exists():
            continue
        if rdir.exists() and not analyse_only:
            shutil.rmtree(rdir)
        if not analyse_only:
            jobs.append((build_trim_deck(c, slicer_params), rdir, dict(meta=dict(condition=c.tag))))

    print(f"Slicer 6-Bit Trim: {len(TRIM_CONDS)} corners x 64 codes, {len(jobs)} decks to run", flush=True)
    for ex in ([] if analyse_only else spice.run_many(jobs, workers=workers, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)

    summary = []
    print("\n=== Slicer 6-Bit Offset Trim Summary ===")
    for c in TRIM_CONDS:
        rows = read_trim_tsv(trim_dir / c.tag / "trim.tsv")
        assert len(rows) == 64, f"{c.tag}: got {len(rows)} codes"
        vos = np.array([r["vos_mv"] for r in rows])
        steps = np.diff(vos)
        mono = bool(np.all(steps > 0))
        rec = dict(
            condition=c.tag,
            vos_code0_mv=float(vos[0]),
            vos_code32_mv=float(vos[32]),
            vos_code63_mv=float(vos[63]),
            range_neg_mv=float(vos[0]),
            range_pos_mv=float(vos[63]),
            mean_lsb_mv=float(np.mean(steps)),
            min_lsb_mv=float(np.min(steps)),
            max_lsb_mv=float(np.max(steps)),
            monotonic=mono,
            ok=bool(mono and vos[0] <= -30.0 and vos[63] >= 30.0 and np.mean(steps) <= 1.5),
            vos_mv=vos.tolist(),
        )
        summary.append(rec)
        print(
            f"  {c.tag:15s}: range=[{rec['vos_code0_mv']:+6.2f}, {rec['vos_code63_mv']:+6.2f}] mV "
            f"(code32={rec['vos_code32_mv']:+5.2f} mV) | LSB mean={rec['mean_lsb_mv']:.2f} "
            f"(min={rec['min_lsb_mv']:.2f}, max={rec['max_lsb_mv']:.2f}) mV | mono={mono} | ok={rec['ok']}"
        )
    (trim_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


# ---------------------------------------------------------------------------
# 3. 200-Sample Mismatch Monte Carlo (tt_v1800_t27_mm & ss_v1650_t-40_mm)
# ---------------------------------------------------------------------------
MC_T_STOP = 81e-9  # -40 mV to +40 mV at 1.0 mV/ns -> covers > +/-5 sigma, +/-0.5 mV resolution
MC_V_START = -0.040
MC_V_STOP = +0.040
MC_SLOPE = (MC_V_STOP - MC_V_START) / 80e-9

MC_NETLIST = """\
RX Double-Tail Slicer Mismatch MC (code 32 centered)
.lib "@MODEL_LIBRARY@" @CORNER@_mm
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "@PROJECT_ROOT@/analog/rx/cmos_rx/spice/rx_dt_sampler.spice"
Vdd vdd 0 @SUPPLY@
Vcm cm 0 1.45
Vclk clk 0 PULSE(0 @SUPPLY@ 0.9875n 25p 25p 475p 1n)
Vdm dm 0 PWL(0 @V_START@ 1n @V_START@ 81n @V_STOP@)
Eip inp cm dm 0  0.5
Ein inn cm dm 0 -0.5
Vt5 t5 0 @SUPPLY@
Vt4 t4 0 0
Vt3 t3 0 0
Vt2 t2 0 0
Vt1 t1 0 0
Vt0 t0 0 0
Xdut inp inn clk qp qn t5 t4 t3 t2 t1 t0 vdd 0 serdes_rx_dt_slicer @SLICER_PARAMS@
Clp qp 0 10f
Cln qn 0 10f
.temp @TEMP_C@
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(qp)
"""


def run_mc(camp: Path, workers: int, slicer_params: str, samples: int, chunk_size: int, analyse_only: bool):
    mc_dir = camp / "mc"
    mc_dir.mkdir(parents=True, exist_ok=True)
    mc_conds = [NOMINAL, Condition("ss", 1.65, -40)]
    summary = []
    print(f"\n=== Slicer Mismatch MC ({samples} samples/corner, chunk={chunk_size}) ===")
    for ci, c in enumerate(mc_conds):
        vmid = 0.5 * c.supply
        net = spice.render(
            MC_NETLIST,
            **spice.corner_values(c),
            V_START=f"{MC_V_START:.6f}",
            V_STOP=f"{MC_V_STOP:.6f}",
            SLICER_PARAMS=slicer_params,
        )
        analysis = "\n".join([
            f"tran 5p {MC_T_STOP:.3e} 0 10p",
            f"meas tran t_trip when v(qp)={vmid:.4f} rise=1 td=1.5n",
        ])
        lets = dict(
            t_trip="t_trip",
            vos_mv=f"({MC_V_START} + {MC_SLOPE} * (t_trip - 1.5e-9)) * 1e3",
        )
        cdir = mc_dir / f"{c.tag}_mm"
        jobs = []
        for idx, seed, n in mc.chunks(samples, seed=10 + ci, per=chunk_size):
            dtext = mc.deck(net, n, seed=seed, analysis=analysis, lets=lets, t_end=MC_T_STOP)
            jobs.append((dtext, cdir / f"c{idx:02d}", dict(meta=dict(condition=f"{c.tag}_mm", chunk=idx, seed=seed, samples=n))))

        if analyse_only:
            dirs = [d for d in mc.completed(jobs) if d is not None]
        else:
            dirs = mc.run_many(jobs, workers=workers)
        rows = mc.read_all(dirs)
        vos = mc.column(rows, "vos_mv")
        valid = vos[np.isfinite(vos)]
        rec = dict(
            condition=f"{c.tag}_mm",
            samples=len(rows),
            valid=int(len(valid)),
            mean_mv=float(np.mean(valid)),
            sigma_mv=float(np.std(valid, ddof=1)),
            three_sigma_mv=float(3.0 * np.std(valid, ddof=1)),
            min_mv=float(np.min(valid)),
            max_mv=float(np.max(valid)),
        )
        summary.append(rec)
        print(
            f"  {rec['condition']:18s}: N={rec['valid']}/{rec['samples']} | "
            f"mean={rec['mean_mv']:+.2f} mV | 1sigma={rec['sigma_mv']:.2f} mV | "
            f"3sigma={rec['three_sigma_mv']:.2f} mV | range=[{rec['min_mv']:+.2f}, {rec['max_mv']:+.2f}] mV"
        )
    (mc_dir / "summary.json").write_text(json.dumps(summary, indent=1))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("pvt", "trim", "mc", "all"), default="all")
    ap.add_argument("--conds", nargs="*", default=["all"])
    ap.add_argument("--params", default="")
    ap.add_argument("--mc-samples", type=int, default=200)
    ap.add_argument("--mc-chunk", type=int, default=25)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    assert 1 <= a.workers <= 2, "Max 2 concurrent ngspice workers allowed"

    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)

    if a.mode in ("pvt", "all"):
        run_pvt(camp, conds, a.workers, a.params, a.analyse_only)
    if a.mode in ("trim", "all"):
        run_trim(camp, a.workers, a.params, a.analyse_only)
    if a.mode in ("mc", "all"):
        run_mc(camp, a.workers, a.params, a.mc_samples, a.mc_chunk, a.analyse_only)
    print(f"\nSlicer results: {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
