#!/usr/bin/env python3
"""Verify pll_cp_steer_v4: 135-corner real-BIAS DC sweep, AC servo stability, and 250 MHz transient.

Reuses the exact 135-corner MOS x VDD x T x RC real-BIAS methodology of window_steer.py.
Results are written under results/analog/pll/cp/v4/<run_id>/.
Hard-capped at workers <= 2 to respect shared host ngspice budget.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

import numpy as np

REPO = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO / "src"))
from serdes_flow import bias, project, spice  # noqa: E402
from serdes_flow.corners import grid45  # noqa: E402

RESULTS_ROOT = REPO / "results/analog/pll/cp/v4"
DUT_FILE = REPO / "analog/pll/cp/spice/charge_pump_steer_v4.spice"
V3_DATA = REPO / "docs/data/pll_cp_steer_window.json"
DROPS = (0.36, 0.39, 0.41, 0.44)
PASSIVE_CORNERS = ("tt", "hh", "ll")

EXTREME_6 = [
    ("tt", "tt", 1.80, 27),
    ("sf", "ll", 1.65, -40),
    ("sf", "ll", 1.65, 85),
    ("ss", "ll", 1.65, -40),
    ("fs", "ll", 1.65, -40),
    ("ff", "hh", 1.95, 85),
]


def read_complex_raw(path: Path) -> dict[str, np.ndarray]:
    b = path.read_bytes()
    hdr, body = b.split(b"Binary:\n", 1)
    lines = hdr.decode().splitlines()
    nv = int([l.split(":")[1] for l in lines if l.startswith("No. Variables:")][0])
    np_ = int([l.split(":")[1] for l in lines if l.startswith("No. Points:")][0])
    vi = lines.index("Variables:") + 1
    names = [lines[vi + i].split()[1].lower() for i in range(nv)]
    arr = np.frombuffer(body, dtype=np.complex128).reshape(np_, nv)
    return {n: arr[:, i] for i, n in enumerate(names)}


def build_dc_deck(proc: str, rc: str, conds: list, dut_path: Path, subckt_name: str, inst_params: str = "") -> str:
    base = f"""\
* CP v4 DC sweep {proc}_{rc}
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/common/devices/spice/cmos_logic.spice"
.include "{dut_path}"
.param supply=1.8 irefn=50u irefp=50u
Vdd vdd 0 {{supply}}
Vbias vb 0 {{supply}}
In vb vbn {{irefn}}
Ip vbp 0 {{irefp}}
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
Xup vdd 0 ou vbn vbp ibu vdd 0 {subckt_name} {inst_params}
Xdn 0 vdd od vbn vbp ibd vdd 0 {subckt_name} {inst_params}
* ibias: after bias.real
Vout sweep 0 0.9
Eu ou 0 sweep 0 1
Ed od 0 sweep 0 1
.temp 27
.options reltol=1e-4 abstol=1p vntol=1u
.end
"""
    deck = bias.section(bias.real(base), proc, rc)
    deck = deck.replace(
        "* ibias: after bias.real",
        "XIbu ibu vgi_bias vdd serdes_bias_pcopy n=4\nXIbd ibd vgi_bias vdd serdes_bias_pcopy n=4",
    )
    ctrl = [".control", "set num_threads=1", "set filetype=binary"]
    for c in conds:
        ctrl += [
            f"option temp={c.temp}",
            f"alter Vdd dc={c.supply}",
            f"alter Vbias dc={c.supply}",
            f"dc Vout 0.1 {c.supply - 0.05:.3f} 0.01",
            f"write {c.tag}.raw i(Eu) i(Ed)",
            "destroy all",
        ]
    return deck[: deck.rindex(".end")] + "\n".join(ctrl + ["quit", ".endc", ".end", ""])


def measure_dc(path: Path, supply: float, threshold: float = 0.05) -> dict:
    w = spice.Waves(path)
    v = w.t
    iu, id_ = w["i(eu)"], w["i(ed)"]
    expected = np.arange(round((supply - 0.05 - 0.1) / 0.01) + 1) * 0.01 + 0.1
    if len(v) != len(expected) or not np.allclose(v, expected, rtol=0, atol=1e-7):
        raise ValueError(f"incomplete DC sweep: {path}")
    # Check signs: Eu sources/sinks oppositely to CP UP (current into Eu is positive when CP sources)
    mid = int(np.argmin(np.abs(v - supply / 2)))
    if not (iu[mid] > 1e-6 and id_[mid] < -1e-6):
        # Allow sign check relative to Eu/Ed polarity (verify opposite signs!)
        if not (iu[mid] * id_[mid] < -1e-12):
            raise ValueError(f"unexpected current polarity at {path}: iu={iu[mid]}, id={id_[mid]}")
    up, dn = np.abs(iu), np.abs(id_)
    ok = (np.abs(up / up[mid] - 1) <= threshold) & (np.abs(dn / dn[mid] - 1) <= threshold)
    lo = hi = mid
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    while hi + 1 < len(v) and ok[hi + 1]:
        hi += 1
    mm = np.abs(up - dn) / ((up + dn) / 2.0)
    m_win1 = (v >= 0.50 - 1e-6) & (v <= supply - 0.30 + 1e-6)
    m_win2 = (v >= 0.60 - 1e-6) & (v <= supply - 0.35 + 1e-6)
    return dict(
        supply=float(supply),
        lo=float(round(v[lo], 4)),
        hi=float(round(v[hi], 4)),
        up_mid_ua=float(up[mid] * 1e6),
        dn_mid_ua=float(dn[mid] * 1e6),
        mm_mid_pct=float(mm[mid] * 100.0),
        mm_win_0p50_0p30_pct=float(np.max(mm[m_win1]) * 100.0),
        mm_win_0p60_0p35_pct=float(np.max(mm[m_win2]) * 100.0),
        droop_at={
            f"{d:.2f}": {
                "up": float(1 - np.interp(supply - d, v, up) / up[mid]),
                "dn": float(1 - np.interp(supply - d, v, dn) / dn[mid]),
            }
            for d in DROPS
        },
    )


def run_dc_135(out: Path, workers: int) -> dict:
    dc_dir = out / "dc_135"
    dc_dir.mkdir(parents=True, exist_ok=True)
    groups: dict[tuple[str, str], list] = {}
    for rc in PASSIVE_CORNERS:
        for c in grid45():
            groups.setdefault((c.process, rc), []).append(c)

    jobs = []
    for (proc, rc), conds in groups.items():
        name = f"{proc}_{rc}"
        rdir = dc_dir / name
        done = (rdir / "execution.json").exists() and all((rdir / f"{c.tag}.raw").exists() for c in conds)
        if not done:
            dtxt = build_dc_deck(proc, rc, conds, DUT_FILE, "pll_cp_steer_v4")
            jobs.append((dtxt, rdir, dict(timeout_s=600, meta={"process": proc, "passive": rc})))

    if jobs:
        print(f"[DC 135] Launching {len(jobs)} MOSxRC grouped decks (workers={workers})...", flush=True)
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            status = "OK" if ex.ok else f"FAIL({ex.log_failures[:2]})"
            print(f"  {ex.run_dir.name:8s}: {status} ({ex.elapsed_s:.1f}s)", flush=True)

    # Load vhi pairing from v3 reference JSON
    vhi_map = {}
    if V3_DATA.exists():
        v3 = json.loads(V3_DATA.read_text())
        for r in v3["rows"]:
            if "vhi" in r:
                vhi_map[(r["condition"], r["passive"])] = float(r["vhi"])

    rows = {}
    failures = []
    for (proc, rc), conds in groups.items():
        rdir = dc_dir / f"{proc}_{rc}"
        for c in conds:
            raw = rdir / f"{c.tag}.raw"
            if not raw.exists():
                failures.append(f"{c.tag}:{rc}")
                continue
            m = measure_dc(raw, c.supply)
            if (c.tag, rc) in vhi_map:
                m["vhi"] = vhi_map[(c.tag, rc)]
                m["upper_gap_mv"] = float((m["hi"] - m["vhi"]) * 1e3)
            rows[f"{c.tag}:{rc}"] = m

    by_vdd = {}
    for vdd in (1.65, 1.80, 1.95):
        sub = [r for r in rows.values() if abs(r["supply"] - vdd) < 1e-3]
        if sub:
            gaps = [r["upper_gap_mv"] for r in sub if "upper_gap_mv" in r]
            by_vdd[f"{vdd:.2f}"] = dict(
                n=len(sub),
                lo_max=max(r["lo"] for r in sub),
                hi_min=min(r["hi"] for r in sub),
                min_upper_gap_mv=min(gaps) if gaps else None,
                max_mm_mid_pct=max(r["mm_mid_pct"] for r in sub),
                max_mm_0p60_0p35_pct=max(r["mm_win_0p60_0p35_pct"] for r in sub),
                max_mm_0p50_0p30_pct=max(r["mm_win_0p50_0p30_pct"] for r in sub),
            )

    worst_mm_w2 = max(rows.items(), key=lambda kv: kv[1]["mm_win_0p60_0p35_pct"])
    worst_mm_w1 = max(rows.items(), key=lambda kv: kv[1]["mm_win_0p50_0p30_pct"])
    worst_hi165 = min(
        [(k, v) for k, v in rows.items() if abs(v["supply"] - 1.65) < 1e-3],
        key=lambda kv: kv[1]["hi"],
    )
    summary = dict(
        completed=len(rows),
        expected=135,
        failures=failures,
        by_vdd=by_vdd,
        worst_mm_0p60_0p35={"corner": worst_mm_w2[0], "pct": worst_mm_w2[1]["mm_win_0p60_0p35_pct"]},
        worst_mm_0p50_0p30={"corner": worst_mm_w1[0], "pct": worst_mm_w1[1]["mm_win_0p50_0p30_pct"]},
        worst_hi_1p65={"corner": worst_hi165[0], "hi_v": worst_hi165[1]["hi"], "upper_gap_mv": worst_hi165[1].get("upper_gap_mv")},
        rows=rows,
    )
    (out / "dc_135_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[DC 135] Completed {len(rows)}/135 corners. Failures={len(failures)}", flush=True)
    for k, v in by_vdd.items():
        print(
            f"  VDD={k}V: [{v['lo_max']:.2f}, {v['hi_min']:.2f}]V | min_gap_vhi={v['min_upper_gap_mv']:.1f}mV | "
            f"max_mm[0.60,VDD-0.35]={v['max_mm_0p60_0p35_pct']:.3f}% | max_mm[0.50,VDD-0.30]={v['max_mm_0p50_0p30_pct']:.3f}%",
            flush=True,
        )
    return summary


def run_ac_stability(out: Path, workers: int) -> dict:
    ac_dir = out / "ac_stability"
    ac_dir.mkdir(parents=True, exist_ok=True)
    dut_text = DUT_FILE.read_text()
    ac_dut = dut_text.replace(
        ".subckt pll_cp_steer_v4 up dn out vbn vbp ibias vdd vss",
        ".subckt pll_cp_steer_v4_ac up dn out vbn vbp ibias vdd vss rep_o rep_i",
    ).replace(
        "Xsa sda rep stail vss", "Xsa sda rep_i stail vss"
    ).replace(
        "Xcsrv rep vbp_srv ", "Vrep_tap rep rep_o 0\nXcsrv rep vbp_srv "
    ).replace(
        ".ends pll_cp_steer_v4", ".ends pll_cp_steer_v4_ac"
    )
    ac_dut_path = ac_dir / "cp_v4_ac.spice"
    ac_dut_path.write_text(ac_dut)

    jobs = []
    for proc, rc, vdd, temp in EXTREME_6:
        tag = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{int(temp)}"
        base = f"""\
* AC servo loop stability {tag}
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/common/devices/spice/cmos_logic.spice"
.include "{ac_dut_path}"
.param supply={vdd} irefn=50u irefp=50u
Vdd vdd 0 {{supply}}
Vbias vb 0 {{supply}}
In vb vbn {{irefn}}
Ip vbp 0 {{irefp}}
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
Xac 0 0 oac vbn vbp ibac vdd 0 rep_o rep_i pll_cp_steer_v4_ac
Lbrk rep_o rep_i 1e6
Cinj rep_i vac 1e6
Vac vac 0 dc 0 ac 1
Vout_ac oac 0 {vdd/2:.3f}
* ibias: after bias.real
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u
.end
"""
        deck = bias.section(bias.real(base), proc, rc)
        deck = deck.replace("* ibias: after bias.real", "XIbac ibac vgi_bias vdd serdes_bias_pcopy n=4")
        ctrl = [".control", "set num_threads=1", "set filetype=binary"]
        for vpt, vtag in ((0.50, "lo"), (round(vdd / 2, 3), "mid"), (round(vdd - 0.30, 3), "hi")):
            ctrl += [
                f"alter Vout_ac dc={vpt}",
                "ac dec 25 10 1g",
                f"write {vtag}.raw v(rep_o) v(rep_i)",
                "destroy all",
            ]
        deck = deck[: deck.rindex(".end")] + "\n".join(ctrl + ["quit", ".endc", ".end", ""])
        jobs.append((deck, ac_dir / tag, dict(timeout_s=180)))

    print(f"[AC] Running servo loop-gain stability on {len(jobs)} extreme corners (workers={workers})...", flush=True)
    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        if not ex.ok:
            print(f"  AC FAIL {ex.run_dir.name}: {ex.log_failures[:2]}", flush=True)

    rows = {}
    min_pm = 999.0
    min_dc_db = 999.0
    for proc, rc, vdd, temp in EXTREME_6:
        tag = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{int(temp)}"
        rdir = ac_dir / tag
        rows[tag] = {}
        for vtag in ("lo", "mid", "hi"):
            wa = read_complex_raw(rdir / f"{vtag}.raw")
            f = np.real(wa["frequency"])
            T = -wa["v(rep_o)"] / wa["v(rep_i)"]
            mdb = 20 * np.log10(np.maximum(np.abs(T), 1e-12))
            ph = np.unwrap(np.angle(T, deg=True))
            ph -= round(ph[0] / 360.0) * 360.0
            idx = np.where(mdb <= 0)[0]
            k = int(idx[0])
            fr = -mdb[k - 1] / (mdb[k] - mdb[k - 1])
            fu = float(f[k - 1] * ((f[k] / f[k - 1]) ** fr))
            pm = float(180.0 + ph[k - 1] + fr * (ph[k] - ph[k - 1]))
            dc_db = float(mdb[0])
            min_pm = min(min_pm, pm)
            min_dc_db = min(min_dc_db, dc_db)
            rows[tag][vtag] = dict(dc_gain_db=round(dc_db, 2), ugbw_mhz=round(fu / 1e6, 3), phase_margin_deg=round(pm, 2))
        print(
            f"  {tag:18s}: "
            + " | ".join(f"{vt}: {rows[tag][vt]['dc_gain_db']:.0f}dB/{rows[tag][vt]['ugbw_mhz']:.1f}M/PM={rows[tag][vt]['phase_margin_deg']:.1f}°" for vt in ("lo", "mid", "hi")),
            flush=True,
        )
    summary = dict(min_phase_margin_deg=round(min_pm, 2), min_dc_gain_db=round(min_dc_db, 2), corners=rows)
    (out / "ac_stability_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def run_tran_250m(out: Path, workers: int) -> dict:
    tr_dir = out / "tran_250m"
    tr_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for proc, rc, vdd, temp in EXTREME_6:
        tag = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{int(temp)}"
        # Phase 1 (0..18ns): precharge LF to VDD/2
        # Phase 2 (20..72ns): locked 250 MHz simultaneous UP & DN 400ps pulses (ripple, drift, glitch, power)
        # Phase 3 (72..140ns): UP active pulse step (UP=1.4ns vs DN=0.4ns -> ramps out up ~+100mV to check servo tracking & settling)
        base = f"""\
* 250 MHz dynamic switching + servo tracking transient {tag}
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/common/devices/spice/cmos_logic.spice"
.include "{REPO}/analog/pll/loop_filter/spice/passive_rc_precharge.spice"
.include "{REPO}/analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice"
.include "{DUT_FILE}"
.param supply={vdd} irefn=50u irefp=50u
Vdd vdd 0 {{supply}}
Vdd_cp vdd_cp 0 {{supply}}
Vbias vb 0 {{supply}}
In vb vbn {{irefn}}
Ip vbp 0 {{irefp}}
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
Vpre pre_en 0 pulse({vdd} 0 18n 0.2n 0.2n 500n 1u)
Vpref pre_ref 0 {vdd/2:.3f}
* Locked 250 MHz 400ps simultaneous pulses + extra UP burst at 72..100ns (7 cycles) then locked 100..160ns
* Both up and dn pass through matched OR2 gates so testbench introduces ZERO UP/DN skew!
Vup_base up_b0 0 pulse(0 {vdd} 22n 0.08n 0.08n 0.4n 4n)
Vdn_base dn_b0 0 pulse(0 {vdd} 22n 0.08n 0.08n 0.4n 4n)
Vup_ext up_ext 0 pulse(0 {vdd} 72.4n 0.08n 0.08n 1.0n 4n)
Ven_step en_step 0 pulse(0 {vdd} 71.5n 0.1n 0.1n 28n 1u)
Xand_up up_ext en_step up_add vdd 0 serdes_cmos_and2
Xor_up up_b0 up_add up vdd 0 serdes_cmos_or2
Xor_dn dn_b0 0 dn vdd 0 serdes_cmos_or2
Xcp up dn cpo vbn vbp ibcp vdd_cp 0 pll_cp_steer_v4
Xlf cpo ctrl z pre_ref pre_en vdd_cp 0 pll_loop_filter_k4
Cvco ctrl 0 0.5p
* ibias: after bias.real
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u
.end
"""
        deck = bias.section(bias.real(base), proc, rc)
        deck = deck.replace("* ibias: after bias.real", "XIbcp ibcp vgi_bias vdd serdes_bias_pcopy n=4")
        ctrl = [
            ".control",
            "set num_threads=1",
            "set filetype=binary",
            "tran 0.025n 160n",
            "write tran.raw v(cpo) v(z) v(xcp.vbp_srv) v(xcp.rep) v(xcp.dum) i(Vdd_cp)",
            "quit",
            ".endc",
            ".end",
            "",
        ]
        deck = deck[: deck.rindex(".end")] + "\n".join(ctrl)
        jobs.append((deck, tr_dir / tag, dict(timeout_s=300)))

    print(f"[TRAN 250M] Running 250 MHz dynamic switching + step on {len(jobs)} extreme corners (workers={workers})...", flush=True)
    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        status = "OK" if ex.ok else f"FAIL({ex.log_failures[:2]})"
        print(f"  {ex.run_dir.name:18s}: {status} ({ex.elapsed_s:.1f}s)", flush=True)

    rows = {}
    for proc, rc, vdd, temp in EXTREME_6:
        tag = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{int(temp)}"
        w = spice.Waves(tr_dir / tag / "tran.raw")
        t = w.t
        cpo = w["v(cpo)"]
        z = w["v(z)"]
        vbps = w["v(xcp.vbp_srv)"]
        rep = w["v(xcp.rep)"]
        idd = -w["i(vdd_cp)"]

        # Locked window: 36..70 ns
        m_lk = (t >= 36e-9) & (t <= 70e-9)
        # Post-step settled locked window: 136..160 ns (36ns after burst ends)
        m_ps = (t >= 136e-9) & (t <= 160e-9)
        z_step_mv = float((np.mean(z[m_ps]) - np.mean(z[m_lk])) * 1e3)
        lk_drift_mv = float((z[m_lk][-1] - z[m_lk][0]) * 1e3)
        cpo_pp_mv = float((np.max(cpo[m_lk]) - np.min(cpo[m_lk])) * 1e3)
        vbps_pp_lk_mv = float((np.max(vbps[m_lk]) - np.min(vbps[m_lk])) * 1e3)
        m_a = (t >= 136e-9) & (t < 148e-9)
        m_b = (t >= 148e-9) & (t <= 160e-9)
        vbps_pp_a = float((np.max(vbps[m_a]) - np.min(vbps[m_a])) * 1e3)
        vbps_pp_b = float((np.max(vbps[m_b]) - np.min(vbps[m_b])) * 1e3)
        rep_dc_err_mv = float(abs(np.mean(rep[m_ps] - cpo[m_ps])) * 1e3)
        pwr_uw = float(np.mean(idd[m_lk]) * vdd * 1e6)

        rows[tag] = dict(
            cpo_glitch_pp_mv=round(cpo_pp_mv, 2),
            locked_z_drift_34ns_mv=round(lk_drift_mv, 3),
            step_delta_z_mv=round(z_step_mv, 2),
            vbp_srv_ripple_lk_mv=round(vbps_pp_lk_mv, 2),
            vbp_srv_ripple_post_a_mv=round(vbps_pp_a, 2),
            vbp_srv_ripple_post_b_mv=round(vbps_pp_b, 2),
            post_step_rep_dc_err_mv=round(rep_dc_err_mv, 2),
            power_uw=round(pwr_uw, 1),
            stable_settled=bool(vbps_pp_b <= vbps_pp_a + 1.0 and rep_dc_err_mv < 5.0),
        )
        print(
            f"  {tag:18s}: cpo_pp={cpo_pp_mv:5.2f}mV | lk_drift={lk_drift_mv:+6.3f}mV | dZ_step={z_step_mv:+6.1f}mV | "
            f"vbp_pp={vbps_pp_lk_mv:5.2f}->{vbps_pp_b:5.2f}mV | |rep-out|_dc={rep_dc_err_mv:4.2f}mV | P={pwr_uw:5.1f}uW",
            flush=True,
        )
    summary = dict(all_stable=all(r["stable_settled"] for r in rows.values()), corners=rows)
    (out / "tran_250m_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def build_pex_dc_deck(proc: str, rc: str, c, pex_path: Path) -> str:
    """Split DC sweep from VDD/2 upward & downward so 131-finger CPEX netlist avoids gmin stepping at 0.10 V."""
    base = f"""\
* CP v4 PEX DC sweep {c.tag}_{rc}
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/common/devices/spice/cmos_logic.spice"
.include "{pex_path}"
.param supply={c.supply} irefn=50u irefp=50u
Vdd vdd 0 {{supply}}
Vbias vb 0 {{supply}}
In vb vbn {{irefn}}
Ip vbp 0 {{irefp}}
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
Xup vdd 0 ou vbn vbp ibu vdd 0 pll_cp_steer_v4_pdk
Xdn 0 vdd od vbn vbp ibd vdd 0 pll_cp_steer_v4_pdk
* ibias: after bias.real
Vout sweep 0 {c.supply / 2:.3f}
Eu ou 0 sweep 0 1
Ed od 0 sweep 0 1
.temp {c.temp}
.options reltol=1e-4 abstol=1p vntol=1u
.end
"""
    deck = bias.section(bias.real(base), proc, rc)
    deck = deck.replace(
        "* ibias: after bias.real",
        "XIbu ibu vgi_bias vdd serdes_bias_pcopy n=4\nXIbd ibd vgi_bias vdd serdes_bias_pcopy n=4",
    )
    v_mid = round(round((c.supply / 2.0) / 0.01) * 0.01, 2)
    ctrl = [
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"dc Vout {v_mid:.2f} {c.supply - 0.05:.2f} 0.01",
        "write hi.raw i(Eu) i(Ed)",
        "destroy all",
        f"dc Vout {v_mid:.2f} 0.20 -0.01",
        "write lo.raw i(Eu) i(Ed)",
        "destroy all",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return deck[: deck.rindex(".end")] + "\n".join(ctrl)


def measure_pex_split(rdir: Path, supply: float, threshold: float = 0.05) -> dict:
    names_lo, data_lo = spice.read_raw(rdir / "lo.raw")
    idx_lo = {n.lower(): i for i, n in enumerate(names_lo)}
    names_hi, data_hi = spice.read_raw(rdir / "hi.raw")
    idx_hi = {n.lower(): i for i, n in enumerate(names_hi)}
    # lo.raw sweeps downward from v_mid to 0.20 -> reverse and drop duplicate v_mid
    v_lo = data_lo[::-1, 0][:-1]
    iu_lo = data_lo[::-1, idx_lo["i(eu)"]][:-1]
    id_lo = data_lo[::-1, idx_lo["i(ed)"]][:-1]
    v = np.concatenate([v_lo, data_hi[:, 0]])
    iu = np.concatenate([iu_lo, data_hi[:, idx_hi["i(eu)"]]])
    id_ = np.concatenate([id_lo, data_hi[:, idx_hi["i(ed)"]]])
    mid = int(np.argmin(np.abs(v - supply / 2)))
    if not (iu[mid] * id_[mid] < -1e-12):
        raise ValueError(f"unexpected current polarity at {rdir}")
    up, dn = np.abs(iu), np.abs(id_)
    ok = (np.abs(up / up[mid] - 1) <= threshold) & (np.abs(dn / dn[mid] - 1) <= threshold)
    lo = hi = mid
    while lo > 0 and ok[lo - 1]:
        lo -= 1
    while hi + 1 < len(v) and ok[hi + 1]:
        hi += 1
    mm = np.abs(up - dn) / ((up + dn) / 2.0)
    m_win1 = (v >= 0.50 - 1e-6) & (v <= supply - 0.30 + 1e-6)
    m_win2 = (v >= 0.60 - 1e-6) & (v <= supply - 0.35 + 1e-6)
    return dict(
        supply=float(supply),
        lo=float(round(v[lo], 4)),
        hi=float(round(v[hi], 4)),
        up_mid_ua=float(up[mid] * 1e6),
        dn_mid_ua=float(dn[mid] * 1e6),
        mm_mid_pct=float(mm[mid] * 100.0),
        mm_win_0p50_0p30_pct=float(np.max(mm[m_win1]) * 100.0),
        mm_win_0p60_0p35_pct=float(np.max(mm[m_win2]) * 100.0),
    )


def run_pex_dc_6(out: Path, workers: int, pex_path: Path) -> dict:
    pex_dir = out / "pex_dc_6"
    pex_dir.mkdir(parents=True, exist_ok=True)
    all_conds = {(c.process, c.supply, c.temp): c for c in grid45()}

    jobs = []
    for proc, rc, vdd, temp in EXTREME_6:
        c = all_conds[(proc, vdd, temp)]
        tag = f"{c.tag}_{rc}"
        rdir = pex_dir / tag
        if not ((rdir / "hi.raw").exists() and (rdir / "lo.raw").exists()):
            dtxt = build_pex_dc_deck(proc, rc, c, pex_path)
            jobs.append((dtxt, rdir, dict(timeout_s=600)))

    if jobs:
        print(f"[PEX DC 6] Running post-layout CPEX DC (split from VDD/2) on {len(jobs)} extreme corners (workers={workers})...", flush=True)
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            status = "OK" if ex.ok else f"FAIL({ex.log_failures[:2]})"
            print(f"  PEX {ex.run_dir.name:18s}: {status} ({ex.elapsed_s:.1f}s)", flush=True)

    rows = {}
    for proc, rc, vdd, temp in EXTREME_6:
        c = all_conds[(proc, vdd, temp)]
        tag = f"{c.tag}_{rc}"
        m = measure_pex_split(pex_dir / tag, vdd)
        rows[f"{c.tag}:{rc}"] = m
        print(
            f"  PEX {c.tag}:{rc:2s} | [{m['lo']:.2f}, {m['hi']:.2f}]V | Iup={m['up_mid_ua']:.1f}uA Idn={m['dn_mid_ua']:.1f}uA | "
            f"mm_mid={m['mm_mid_pct']:.3f}% mm[0.60,VDD-0.35]={m['mm_win_0p60_0p35_pct']:.3f}% mm[0.50,VDD-0.30]={m['mm_win_0p50_0p30_pct']:.3f}%",
            flush=True,
        )
    hi_165 = min(r["hi"] for r in rows.values() if abs(r["supply"] - 1.65) < 1e-3)
    max_mm_w2 = max(r["mm_win_0p60_0p35_pct"] for r in rows.values())
    max_mm_w1 = max(r["mm_win_0p50_0p30_pct"] for r in rows.values())
    summary = dict(
        pex_spice=str(pex_path.relative_to(REPO)),
        hi_1p65_min_v=hi_165,
        max_mm_0p60_0p35_pct=round(max_mm_w2, 4),
        max_mm_0p50_0p30_pct=round(max_mm_w1, 4),
        rows=rows,
    )
    (out / "pex_dc_6_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode", choices=("dc", "ac", "tran", "pex", "ac_tran_pex", "all"), default="all")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--pex-spice", type=Path, default=REPO / "analog/pll/cp/layout/variants/v4_pdk/pll_cp_steer_v4_pdk_pex.spice")
    args = ap.parse_args()
    workers = min(max(1, args.workers), 2)  # Hard-capped at 2 concurrent ngspice workers!
    if args.out is not None:
        out = args.out.resolve()
        out.mkdir(parents=True, exist_ok=True)
    else:
        out = RESULTS_ROOT / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
        out.mkdir(parents=True, exist_ok=False)
    print(f"Output dir: {out} (workers={workers})", flush=True)
    if args.mode in ("dc", "all"):
        run_dc_135(out, workers)
    if args.mode in ("ac", "ac_tran_pex", "all"):
        run_ac_stability(out, workers)
    if args.mode in ("tran", "ac_tran_pex", "all"):
        run_tran_250m(out, workers)
    if args.mode in ("pex", "ac_tran_pex"):
        run_pex_dc_6(out, workers, args.pex_spice.resolve())


if __name__ == "__main__":
    main()
