#!/usr/bin/env python3
"""Fast 3-corner ngspice verification of Wave 2A real-PDK candidate cells:
  1. `pll_vctrl_window_cmos` (zero B-sources, 4->16 static CMOS decoder, 16-tap sweep + cmp trip)
  2. `pll_phase_window_pdk`  (zero ideal caps, 6x real MIM 2.2x2.2 um delay threshold + sticky latch)
  3. `pll_cp_steer_v4_en`    (real `cp_en` gating: high-Z off-leakage & matched I_UP/I_DN on-state)
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

OUT = REPO / "results/verification/wave2a_candidates_20261124"
CORNERS = [
    ("tt_v1800_t27", "tt"),
    ("ss_v1650_t-40", "hh"),
    ("ff_v1950_t85", "ll"),
]


def run_vctrl_window(c: Condition, rc: str, out: Path) -> dict:
    s = c.supply
    lines = [
        f"* pll_vctrl_window_cmos verification ({c.process}_{c.supply}_{c.temp}:{rc})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        f'.include "{REPO / "analog/common/devices/spice/sky130_primitives.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/sky130_pfet_lvt.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/cmos_logic.spice"}"',
        f'.include "{REPO / "analog/common/monitor/spice/monitor.spice"}"',
        f'.include "{REPO / "analog/common/monitor/spice/monitor_cmos.spice"}"',
        f'.include "{REPO / "analog/pll/coarse/spice/vctrl_window_cmos.spice"}"',
        f"Vdd vdd 0 {s}",
        "Ilo vdd ilo 5u", "Ihi vdd ihi 5u", "Ibh vdd ibh 2.5u", "Ibl vdd ibl 2.5u",
        "Vz z 0 1.0",
        *[f"Vlo{k} lo{k} 0 {s if ((5 >> k) & 1) else 0.0}" for k in range(4)],
        *[f"Vhi{k} hi{k} 0 {s if ((3 >> k) & 1) else 0.0}" for k in range(4)],
        "Xwin z hi lo lo3 lo2 lo1 lo0 hi3 hi2 hi1 hi0 ilo ihi ibh ibl vdd 0 pll_vctrl_window_cmos",
        f".temp {c.temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        # Sweep all 16 codes on both ladders via op
        *[
            line for code in range(16) for line in (
                *[f"alter Vlo{k} dc={s if ((code >> k) & 1) else 0.0}" for k in range(4)],
                *[f"alter Vhi{k} dc={s if ((code >> k) & 1) else 0.0}" for k in range(4)],
                "op",
                f"write tap_{code:02d}.raw v(xwin.vlo) v(xwin.vhi)",
                "destroy all",
            )
        ],
        # Restore runtime codes (lo=5, hi=3) and DC sweep z from 0.6V to VDD-0.1V
        *[f"alter Vlo{k} dc={s if ((5 >> k) & 1) else 0.0}" for k in range(4)],
        *[f"alter Vhi{k} dc={s if ((3 >> k) & 1) else 0.0}" for k in range(4)],
        f"dc Vz 0.60 {s - 0.10:.3f} 0.005",
        "write sweep.raw v(z) v(hi) v(lo) v(xwin.vlo) v(xwin.vhi)",
        "quit",
        ".endc",
        ".end",
    ]
    dk = bias.section("\n".join(lines) + "\n", c.process, rc)
    ex = spice.run(dk, out, timeout_s=180)
    if not ex.ok:
        return dict(ok=False, fail=ex.log_failures[:3])
    vlos, vhis = [], []
    for code in range(16):
        w = spice.Waves(out / f"tap_{code:02d}.raw")
        vlos.append(float(w["v(xwin.vlo)"][0]))
        vhis.append(float(w["v(xwin.vhi)"][0]))
    lo_mono = all(vlos[i + 1] > vlos[i] + 0.005 for i in range(15))
    hi_mono = all(vhis[i + 1] < vhis[i] - 0.005 for i in range(15))
    ws = spice.Waves(out / "sweep.raw")
    z = ws["v(z)"]
    hi_v, lo_v = ws["v(hi)"], ws["v(lo)"]
    vlo_ref = float(np.median(ws["v(xwin.vlo)"]))
    vhi_ref = float(np.median(ws["v(xwin.vhi)"]))
    lo_trip = float(z[np.where(lo_v < 0.5 * s)[0][0]]) if np.any(lo_v < 0.5 * s) else float("nan")
    hi_trip = float(z[np.where(hi_v > 0.5 * s)[0][0]]) if np.any(hi_v > 0.5 * s) else float("nan")
    ok = bool(lo_mono and hi_mono and abs(lo_trip - vlo_ref) < 0.025 and abs(hi_trip - vhi_ref) < 0.025)
    return dict(
        ok=ok, lo_mono=lo_mono, hi_mono=hi_mono,
        vlo_0_15=[round(vlos[0], 4), round(vlos[-1], 4)],
        vhi_0_15=[round(vhis[0], 4), round(vhis[-1], 4)],
        vlo_code5=round(vlo_ref, 4), lo_trip=round(lo_trip, 4),
        vhi_code3=round(vhi_ref, 4), hi_trip=round(hi_trip, 4),
    )


def run_phase_window(c: Condition, rc: str, out: Path) -> dict:
    s = c.supply
    # Test 1: short 100ps pulse (should NOT trip), Test 2: wide 1.2ns pulse (MUST trip & stick), Test 3: clr_b resets!
    lines = [
        f"* pll_phase_window_pdk verification ({c.process}_{c.supply}_{c.temp}:{rc})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        f'.include "{REPO / "analog/common/devices/spice/sky130_primitives.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/cmos_logic.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/cmos_dff_reset.spice"}"',
        f'.include "{REPO / "analog/pll/pfd/spice/phase_window_pdk.spice"}"',
        f"Vdd vdd 0 {s}",
        f"Vclr clr_b 0 PWL(0 0 1n 0 1.05n {s} 12n {s} 12.05n 0 13n 0 13.05n {s})",
        f"Vup up 0 PWL(0 0 3n 0 3.03n {s} 3.13n {s} 3.16n 0 7n 0 7.03n {s} 8.23n {s} 8.26n 0)",
        "Vdn dn 0 0",
        "Xpw up dn clr_b late vdd 0 pll_phase_window_pdk",
        "Clate late 0 5f",
        f".temp {c.temp}",
        ".options reltol=3e-4 abstol=2p vntol=5u",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 5p 15n 0 10p",
        "write pw.raw v(up) v(xpw.e) v(xpw.dly) v(clr_b) v(late)",
        "quit",
        ".endc",
        ".end",
    ]
    dk = bias.section("\n".join(lines) + "\n", c.process, rc)
    ex = spice.run(dk, out, timeout_s=180)
    if not ex.ok:
        return dict(ok=False, fail=ex.log_failures[:3])
    w = spice.Waves(out / "pw.raw")
    t, e, dly, late = w.t, w["v(xpw.e)"], w["v(xpw.dly)"], w["v(late)"]
    # Measure delay tau_d on the wide pulse around 7ns
    sel = (t >= 6.9e-9) & (t <= 9.0e-9)
    t_e = float(t[sel][np.where(e[sel] > 0.5 * s)[0][0]])
    t_d = float(t[sel][np.where(dly[sel] > 0.5 * s)[0][0]])
    tau_ps = (t_d - t_e) * 1e12
    v_after_short = float(np.interp(6.0e-9, t, late))
    v_after_wide = float(np.interp(11.0e-9, t, late))
    v_after_clr = float(np.interp(14.5e-9, t, late))
    ok = bool(v_after_short < 0.1 * s and v_after_wide > 0.9 * s and v_after_clr < 0.1 * s and 120.0 < tau_ps < 1100.0)
    return dict(
        ok=ok, tau_d_ps=round(tau_ps, 1),
        v_short_v=round(v_after_short, 4), v_wide_v=round(v_after_wide, 4), v_clr_v=round(v_after_clr, 4),
    )


def run_cp_en(c: Condition, rc: str, out: Path) -> dict:
    s = c.supply
    vout_test = round(0.55 * s, 3)
    lines = [
        f"* pll_cp_steer_v4_en verification ({c.process}_{c.supply}_{c.temp}:{rc})",
        f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}',
        f'.include "{REPO / "analog/common/devices/spice/sky130_primitives.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/sky130_pfet_lvt.spice"}"',
        f'.include "{REPO / "analog/common/devices/spice/cmos_logic.spice"}"',
        f'.include "{REPO / "analog/bias/spice/bias_v2.spice"}"',
        f'.include "{REPO / "analog/pll/cp/spice/charge_pump_steer_v4.spice"}"',
        f'.include "{REPO / "analog/pll/cp/spice/charge_pump_steer_v4_en.spice"}"',
        f"Vdd vdd 0 {s}",
        "Ibias_cp vdd vbn 50u",
        "Xbias_cp vbn vbp vdd 0 serdes_bias_cp_v2",
        "Ibias_ota vdd ib_ota 10u",
        "Vup up 0 0",
        "Vdn dn 0 0",
        "Ven cp_en 0 0",
        f"Vout out 0 {vout_test}",
        "Xcp up dn cp_en out vbn vbp ib_ota vdd 0 pll_cp_steer_v4_en",
        f".temp {c.temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        # 1) cp_en=0, up=VDD, dn=0 -> must be high-Z!
        f"alter Vup dc={s}", "alter Vdn dc=0", "alter Ven dc=0",
        "op", "write off_up.raw i(Vout)", "destroy all",
        # 2) cp_en=0, up=0, dn=VDD -> must be high-Z!
        "alter Vup dc=0", f"alter Vdn dc={s}", "alter Ven dc=0",
        "op", "write off_dn.raw i(Vout)", "destroy all",
        # 3) cp_en=VDD, up=VDD, dn=0 -> I_UP
        f"alter Vup dc={s}", "alter Vdn dc=0", f"alter Ven dc={s}",
        "op", "write on_up.raw i(Vout)", "destroy all",
        # 4) cp_en=VDD, up=0, dn=VDD -> I_DN
        "alter Vup dc=0", f"alter Vdn dc={s}", f"alter Ven dc={s}",
        "op", "write on_dn.raw i(Vout)", "destroy all",
        "quit",
        ".endc",
        ".end",
    ]
    dk = bias.section("\n".join(lines) + "\n", c.process, rc)
    ex = spice.run(dk, out, timeout_s=180)
    if not ex.ok:
        return dict(ok=False, fail=ex.log_failures[:3])
    # i(Vout) > 0 means current flowing INTO Vout (sourcing from CP -> I_UP = i(Vout))
    i_off_up = abs(float(spice.Waves(out / "off_up.raw")["i(vout)"][0])) * 1e9
    i_off_dn = abs(float(spice.Waves(out / "off_dn.raw")["i(vout)"][0])) * 1e9
    i_up = float(spice.Waves(out / "on_up.raw")["i(vout)"][0]) * 1e6
    i_dn = -float(spice.Waves(out / "on_dn.raw")["i(vout)"][0]) * 1e6
    mismatch_pct = abs(i_up - i_dn) / max(0.5 * (abs(i_up) + abs(i_dn)), 1e-6) * 100.0
    ok = bool(i_off_up < 50.0 and i_off_dn < 50.0 and i_up > 120.0 and i_dn > 120.0 and mismatch_pct < 2.0)
    return dict(
        ok=ok, i_off_up_na=round(i_off_up, 2), i_off_dn_na=round(i_off_dn, 2),
        i_up_ua=round(i_up, 2), i_dn_ua=round(i_dn, 2), mismatch_pct=round(mismatch_pct, 3),
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {}
    all_ok = True
    for cond_s, rc in CORNERS:
        c = Condition.parse(cond_s)
        key = f"{cond_s}_{rc}"
        print(f"=== Corner {key} ===", flush=True)
        r_win = run_vctrl_window(c, rc, OUT / key / "vctrl_window")
        r_pw = run_phase_window(c, rc, OUT / key / "phase_window")
        r_cp = run_cp_en(c, rc, OUT / key / "cp_v4_en")
        summary[key] = dict(vctrl_window=r_win, phase_window=r_pw, cp_v4_en=r_cp)
        print(f"  vctrl_window: {r_win}", flush=True)
        print(f"  phase_window: {r_pw}", flush=True)
        print(f"  cp_v4_en    : {r_cp}", flush=True)
        if not (r_win.get("ok") and r_pw.get("ok") and r_cp.get("ok")):
            all_ok = False
    summary["all_ok"] = all_ok
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nALL_OK={all_ok} -> {OUT / 'summary.json'}", flush=True)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
