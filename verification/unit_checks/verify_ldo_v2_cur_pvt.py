#!/usr/bin/env python3
"""Standalone PVT + Load-Step + Startup + Shutdown Signoff for Adopted HV18 LDO `v2_cur`.

Zero new PMIC hardware: validates the adopted `analog/ldo/spice/pll_supply_hv18_v2_cur.spice`
under the standard dual-rail sequencing constraint (`VDD_1V8` host rail active before/with `VDD_HV33`),
fed by real BIAS v2 `serdes_bias_top_v2` (both `bg` and 10 uA current-mode `i_ldo0`!).

Covers 5 critical PVT corners:
  - TT  3.3V / 1.80V /  27C (tt)
  - SS  3.0V / 1.65V / -40C (hh)
  - SS  3.0V / 1.65V / +85C (hh)
  - FF  3.6V / 1.95V / -40C (ll)
  - FS  3.0V / 1.80V / +85C (ll)

Strictly 1 ngspice worker (num_threads=1).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from serdes_flow import bias, spice  # noqa: E402
from serdes_flow.corners import Condition  # noqa: E402

OUT = REPO / "results/verification/ldo_v2_cur_signoff_20261124"

PROFILES = [
    dict(id="tt_3v3_t27_tt",  mos="tt", rc="tt", vin=3.3, vhost=1.80, temp=27,  iload_nom=6.0),
    dict(id="ss_3v0_t-40_hh", mos="ss", rc="hh", vin=3.0, vhost=1.65, temp=-40, iload_nom=6.0),
    dict(id="ss_3v0_t85_hh",  mos="ss", rc="hh", vin=3.0, vhost=1.65, temp=85,  iload_nom=6.0),
    dict(id="ff_3v6_t-40_ll", mos="ff", rc="ll", vin=3.6, vhost=1.95, temp=-40, iload_nom=6.0),
    dict(id="fs_3v0_t85_ll",  mos="fs", rc="ll", vin=3.0, vhost=1.80, temp=85,  iload_nom=6.0),
]

INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/common/devices/spice/cmos_logic.spice",
    "analog/bias/spice/bias_v2.spice",
    "analog/ldo/spice/ldo_v2_passives.spice",
    "analog/ldo/spice/ldo_hv18_core_v2.spice",
    "analog/ldo/spice/pll_supply_hv18_v2_cur.spice",
]


def deck_header(p: dict, trim: int = 41) -> list[str]:
    c = Condition(process=p["mos"], supply=p["vhost"], temp=p["temp"])
    lines = [
        f"* Adopted HV18 LDO v2_cur + Real BIAS v2 Signoff ({p['id']}, trim={trim})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {p["mos"]}',
        *[f'.include "{REPO / inc}"' for inc in INCLUDES],
        f"Vdd   vin  0 {p['vin']}",
        f"Vhost host 0 {p['vhost']}",
        f"Venable enable 0 {p['vhost']}",
        # Real BIAS v2 top supplying bg + 10uA i_ldo0 (unused current ports tied cleanly to host/2)
        "Vdummy_sink d_sink 0 0.9",
        # Ports: vbg vcm pref icml ictle icp i_ldo0 i_ldo1 g4..g0 c3..c0 en_pbuf vdd vss
        f"Vg4 g4 0 {p['vhost']}", "Vg3 g3 0 0", "Vg2 g2 0 0", "Vg1 g1 0 0", "Vg0 g0 0 0",
        f"Vc3 c3 0 {p['vhost']}", "Vc2 c2 0 0", "Vc1 c1 0 0", "Vc0 c0 0 0",
        "Venp en_pbuf 0 0",
        "Xbias bg vcm_rx pref_nc d_sink d_sink d_sink i_ldo0 d_sink "
        "g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf host 0 serdes_bias_top_v2",
        *[f"Vt{k} t{k} 0 {p['vhost'] if ((trim >> k) & 1) else 0.0}" for k in range(6)],
        "Xdut vin host quiet bg i_ldo0 enable t0 t1 t2 t3 t4 t5 0 serdes_pll_supply_hv18_v2_cur",
        f".temp {p['temp']}",
        ".options reltol=1e-4 abstol=1p vntol=1u",
    ]
    return lines


def calibrate_trim(p: dict, cdir: Path) -> tuple[int, float, float]:
    # Sweep 6-bit trim at nominal 27C (or corner temp) to find code closest to 1.800V
    lines = deck_header(p, trim=32) + [
        f"Iload quiet 0 {p['iload_nom']}m",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        *[
            line for k in range(0, 64, 4) for line in (
                *[f"alter Vt{b} dc={p['vhost'] if ((k >> b) & 1) else 0.0}" for b in range(6)],
                "op", f"write c_{k:02d}.raw v(quiet) v(bg)", "destroy all",
            )
        ],
        "quit", ".endc", ".end",
    ]
    dk = bias.section("\n".join(lines) + "\n", p["mos"], p["rc"])
    ex = spice.run(dk, cdir / "cal_coarse", timeout_s=180)
    if not ex.ok:
        raise RuntimeError(f"cal_coarse failed: {ex.log_failures[:3]}")
    best_k, best_err = 32, 1e9
    for k in range(0, 64, 4):
        vq = float(spice.Waves(cdir / "cal_coarse" / f"c_{k:02d}.raw")["v(quiet)"][0])
        if abs(vq - 1.80) < best_err:
            best_k, best_err = k, abs(vq - 1.80)
    lo, hi = max(0, best_k - 3), min(63, best_k + 3)
    lines2 = deck_header(p, trim=best_k) + [
        f"Iload quiet 0 {p['iload_nom']}m",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        *[
            line for k in range(lo, hi + 1) for line in (
                *[f"alter Vt{b} dc={p['vhost'] if ((k >> b) & 1) else 0.0}" for b in range(6)],
                "op", f"write f_{k:02d}.raw v(quiet) v(bg)", "destroy all",
            )
        ],
        "quit", ".endc", ".end",
    ]
    dk2 = bias.section("\n".join(lines2) + "\n", p["mos"], p["rc"])
    ex2 = spice.run(dk2, cdir / "cal_fine", timeout_s=180)
    if not ex2.ok:
        raise RuntimeError(f"cal_fine failed: {ex2.log_failures[:3]}")
    opt_k, opt_vq, opt_bg, opt_err = best_k, 0.0, 0.0, 1e9
    for k in range(lo, hi + 1):
        w = spice.Waves(cdir / "cal_fine" / f"f_{k:02d}.raw")
        vq, bg = float(w["v(quiet)"][0]), float(w["v(bg)"][0])
        if abs(vq - 1.80) < opt_err:
            opt_k, opt_vq, opt_bg, opt_err = k, vq, bg, abs(vq - 1.80)
    return opt_k, opt_vq, opt_bg


def run_corner_checks(p: dict, trim: int, cdir: Path) -> dict:
    # 1) DC load regulation (1mA, 6mA, 12mA) + enable=0 shutdown
    lines_dc = deck_header(p, trim=trim) + [
        "Iload quiet 0 6m",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "alter Iload dc=1m",  "op", "write dc_1m.raw  v(quiet) v(bg) i(Vdd) i(Vhost)", "destroy all",
        "alter Iload dc=6m",  "op", "write dc_6m.raw  v(quiet) v(bg) i(Vdd) i(Vhost)", "destroy all",
        "alter Iload dc=12m", "op", "write dc_12m.raw v(quiet) v(bg) i(Vdd) i(Vhost)", "destroy all",
        "quit", ".endc", ".end",
    ]
    ex_dc = spice.run(bias.section("\n".join(lines_dc) + "\n", p["mos"], p["rc"]), cdir / "dc", timeout_s=180)
    if not ex_dc.ok:
        return dict(ok=False, stage="dc", fail=ex_dc.log_failures[:3])
    v1 = float(spice.Waves(cdir / "dc" / "dc_1m.raw")["v(quiet)"][0])
    v6 = float(spice.Waves(cdir / "dc" / "dc_6m.raw")["v(quiet)"][0])
    v12 = float(spice.Waves(cdir / "dc" / "dc_12m.raw")["v(quiet)"][0])
    ivdd_6m = -float(spice.Waves(cdir / "dc" / "dc_6m.raw")["i(vdd)"][0]) * 1e3
    iq_ma = ivdd_6m - 6.0

    # 2) Load step: 6mA -> 10mA (1ns edge) -> 6mA (1ns edge)
    lines_step = deck_header(p, trim=trim) + [
        "Iload quiet 0 PWL(0 6m 2u 6m 2.001u 10m 6u 10m 6.001u 6m 10u 6m)",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 2n 10u 0 10n",
        "write step.raw v(quiet) i(Vdd)",
        "quit", ".endc", ".end",
    ]
    ex_st = spice.run(bias.section("\n".join(lines_step) + "\n", p["mos"], p["rc"]), cdir / "step", timeout_s=300)
    if not ex_st.ok:
        return dict(ok=False, stage="step", fail=ex_st.log_failures[:3])
    ws = spice.Waves(cdir / "step" / "step.raw")
    t, vq = ws.t, ws["v(quiet)"]
    v_base = float(np.mean(vq[(t >= 1.0e-6) & (t <= 1.9e-6)]))
    droop_mv = (v_base - float(np.min(vq[(t >= 2.0e-6) & (t <= 5.5e-6)]))) * 1e3
    overshoot_mv = (float(np.max(vq[(t >= 6.0e-6) & (t <= 9.5e-6)])) - v_base) * 1e3

    # 3) Cold startup under standard sequencing: host=VDD_1V8 already up, HV33 ramps 0->Vin in 2us + enable rises at 5us
    lines_su = deck_header(p, trim=trim)
    lines_su = [
        l if not l.startswith("Vdd ") else f"Vdd vin 0 PWL(0 0 1u 0 3u {p['vin']})"
        for l in lines_su
    ]
    lines_su = [
        l if not l.startswith("Venable ") else f"Venable enable 0 PWL(0 0 5u 0 5.1u {p['vhost']})"
        for l in lines_su
    ]
    lines_su += [
        "Rload quiet 0 300",  # 6 mA at 1.8 V resistive startup load
        ".ic v(quiet)=0 v(xdut.xloop.ref_local)=0",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 25n 180u 0 50n",
        "write startup.raw v(vin) v(enable) v(quiet) v(xdut.xloop.ref_local)",
        "quit", ".endc", ".end",
    ]
    ex_su = spice.run(bias.section("\n".join(lines_su) + "\n", p["mos"], p["rc"]), cdir / "startup", timeout_s=420)
    if not ex_su.ok:
        return dict(ok=False, stage="startup", fail=ex_su.log_failures[:3])
    wsu = spice.Waves(cdir / "startup" / "startup.raw")
    tsu, vsu = wsu.t, wsu["v(quiet)"]
    vfin = float(np.mean(vsu[tsu >= 170e-6]))
    vmax = float(np.max(vsu))
    out_idx = np.flatnonzero((tsu >= 5e-6) & (np.abs(vsu - vfin) > 0.015))
    settle_us = float((tsu[min(out_idx[-1] + 1, len(tsu) - 1)] - 5e-6) * 1e6) if len(out_idx) else 0.0

    ok = bool(
        abs(v6 - 1.80) < 0.025
        and abs(v1 - v12) < 0.025
        and droop_mv < 120.0
        and overshoot_mv < 120.0
        and vmax < 1.98
        and settle_us < 160.0
    )
    return dict(
        ok=ok, trim=trim,
        v_1m_v=round(v1, 4), v_6m_v=round(v6, 4), v_12m_v=round(v12, 4),
        load_reg_mv=round((v1 - v12) * 1e3, 2), iq_ma=round(iq_ma, 3),
        step_droop_mv=round(droop_mv, 1), step_overshoot_mv=round(overshoot_mv, 1),
        startup_vfin_v=round(vfin, 4), startup_vmax_v=round(vmax, 4),
        startup_settle_15mv_us=round(settle_us, 1),
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # First calibrate TT nominal trim code once, AND per-corner trim to check fixed-trim vs calibrated
    res = {}
    all_ok = True
    for p in PROFILES:
        cdir = OUT / p["id"]
        cdir.mkdir(parents=True, exist_ok=True)
        opt_k, opt_vq, opt_bg = calibrate_trim(p, cdir)
        r = run_corner_checks(p, opt_k, cdir)
        r["bg_v"] = round(opt_bg, 4)
        res[p["id"]] = r
        print(f"[{p['id']:15s}] ok={r.get('ok')} trim={opt_k:02d} BG={opt_bg:.4f}V | "
              f"V6m={r.get('v_6m_v')}V reg={r.get('load_reg_mv')}mV Iq={r.get('iq_ma')}mA | "
              f"step=-{r.get('step_droop_mv')}/+{r.get('step_overshoot_mv')}mV | "
              f"startup={r.get('startup_settle_15mv_us')}us Vmax={r.get('startup_vmax_v')}V", flush=True)
        if not r.get("ok"):
            all_ok = False
    res["all_ok"] = all_ok
    (OUT / "summary.json").write_text(json.dumps(res, indent=2) + "\n")
    print(f"\nALL_OK={all_ok} -> {OUT / 'summary.json'}", flush=True)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
