#!/usr/bin/env python3
"""Focused Analog Verification:
  Experiment 1 — 4 Gb/s Polish Verification:
    (a) CP v4.1 dynamic UP/DN switching-skew fix (charge_pump_steer_v4p1_cand.spice)
    (b) TX sst_vdrv_ldo light-load PM fix (Xrbleed l=38 -> 5.0) & 800 mVpp LDO stability/headroom
  Experiment 2 — 5 Gb/s (200 ps UI) TX + RX Feasibility & Bottleneck Probe:
    (a) TX SST 400 mVpp @ 5 Gb/s + new 800 mVpp P-over-N TX candidate @ 4 Gb/s & 5 Gb/s
    (b) RX CTLE AC BW & 5 Gb/s C2_loss6 eye: resistive vs realistic SKY130A met4+met5 shunt peaking
    (c) RX Double-Tail Slicer @ 1.25 GHz (400 ps half-cycle) & CMOS PI + /2 @ 2.5 GHz (f_max + INL)

STRICTLY --workers 2 MAX for ngspice, num_threads=1, spice.binary_output, resumable per case!
Outputs saved under results/analog/link_5g/probe_20261123/.
Figure saved to docs/figures/system/serdes_5g_feasibility_20261123.png.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))

from serdes_flow import bias, eye, project, serial, spice  # noqa: E402
from serdes_flow.waves import crossings, time_average  # noqa: E402

OUT_ROOT = REPO / "results/analog/link_5g/probe_20261123"
FIG_PATH = REPO / "docs/figures/system/serdes_5g_feasibility_20261123.png"

# Core 4 corners for Experiment 2 (and CP uses SF 1.65V 85C instead of SS 85C per spec)
CP_CORNERS = [
    ("tt", "tt", 1.80, 27, 0.90),
    ("sf", "hh", 1.65, 85, 0.95),
    ("ss", "hh", 1.65, -40, 0.95),
    ("ff", "ll", 1.95, -40, 1.15),
]

CORNERS_5G = [
    ("tt", "tt", 1.80, 27),
    ("ss", "hh", 1.65, -40),
    ("ss", "hh", 1.65, 85),
    ("ff", "ll", 1.95, -40),
]

# ZQ calibration codes for existing 400 mVpp N-over-N SST & new 800 mVpp P-over-N SST
TX400_ZQ = {
    ("tt", 1.80, 27): 16,
    ("ss_hh", 1.65, -40): 18,
    ("ss_hh", 1.65, 85): 22,
    ("ff_ll", 1.95, -40): 12,
}


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


def run_resumable(jobs_spec: list[dict], workers: int) -> None:
    """Run ngspice jobs only if their target output file is missing/incomplete."""
    todo = []
    for sp in jobs_spec:
        check_file: Path = sp["check"]
        t_end = sp.get("t_end")
        done = False
        if check_file.exists():
            if t_end is not None and check_file.suffix == ".raw":
                try:
                    w = spice.Waves(check_file)
                    done = len(w.t) > 10 and float(w.t[-1]) >= t_end * 0.999
                except Exception:
                    done = False
            elif check_file.suffix == ".log":
                done = sp.get("log_marker", "") in check_file.read_text(errors="replace")
            else:
                done = check_file.stat().st_size > 100
        if not done:
            rdir = sp["run_dir"]
            if rdir.exists():
                shutil.rmtree(rdir)
            rdir.parent.mkdir(parents=True, exist_ok=True)
            todo.append((sp["deck"], rdir, dict(files=sp.get("files"), timeout_s=sp.get("timeout_s", 600))))
    if todo:
        print(f"  Launching {len(todo)}/{len(jobs_spec)} ngspice runs (workers={workers})...", flush=True)
        for ex in spice.run_many(todo, workers=workers, smoke=False):
            status = "OK" if ex.ok else f"FAIL({ex.log_failures[:2]})"
            print(f"    {ex.run_dir.name:36s}: {status} ({ex.elapsed_s:.1f}s)", flush=True)
    else:
        print(f"  All {len(jobs_spec)} runs already cached on disk.", flush=True)


# =============================================================================
# STAGE 1: CP v4 vs CP v4.1 (DC Window + 250 MHz Ripple & Static dPW)
# =============================================================================
def stage_cp(out: Path, workers: int) -> dict:
    print("\n=== [Stage CP] Experiment 1A: CP v4 vs CP v4.1 DC & 250 MHz Switching-Skew ===", flush=True)
    cdir = out / "cp_v4p1"
    cdir.mkdir(parents=True, exist_ok=True)

    # 1) DC window & UP/DN matching for CP v4.1
    dc_jobs = []
    for proc, rc, vdd, temp, _ in CP_CORNERS:
        tag = f"dc_{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
        rdir = cdir / tag
        base = f"""* CP v4.1 DC sweep {tag}
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/common/devices/spice/cmos_logic.spice"
.include "{REPO}/analog/pll/cp/spice/charge_pump_steer_v4p1_cand.spice"
.param supply={vdd} irefn=50u irefp=50u
Vdd vdd 0 {{supply}}
Vbias vb 0 {{supply}}
In vb vbn {{irefn}}
Ip vbp 0 {{irefp}}
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
Xup vdd 0 ou vbn vbp ibu vdd 0 pll_cp_steer_v4p1_cand
Xdn 0 vdd od vbn vbp ibd vdd 0 pll_cp_steer_v4p1_cand
* ibias: after bias.real
Vout sweep 0 {vdd/2:.3f}
Eu ou 0 sweep 0 1
Ed od 0 sweep 0 1
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u
.control
set num_threads=1
set filetype=binary
dc Vout 0.1 {vdd - 0.05:.3f} 0.01
write dc.raw i(Eu) i(Ed)
quit
.endc
.end
"""
        deck = bias.section(bias.real(base), proc, rc).replace(
            "* ibias: after bias.real",
            "XIbu ibu vgi_bias vdd serdes_bias_pcopy n=4\nXIbd ibd vgi_bias vdd serdes_bias_pcopy n=4",
        )
        dc_jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "dc.raw", timeout_s=180))
    run_resumable(dc_jobs, workers)

    dc_rows = {}
    for proc, rc, vdd, temp, _ in CP_CORNERS:
        tag = f"dc_{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
        w = spice.Waves(cdir / tag / "dc.raw")
        v = w.t
        up, dn = np.abs(w["i(eu)"]), np.abs(w["i(ed)"])
        mid = int(np.argmin(np.abs(v - vdd / 2)))
        ok = (np.abs(up / up[mid] - 1) <= 0.05) & (np.abs(dn / dn[mid] - 1) <= 0.05)
        lo = hi = mid
        while lo > 0 and ok[lo - 1]:
            lo -= 1
        while hi + 1 < len(v) and ok[hi + 1]:
            hi += 1
        mm = np.abs(up - dn) / ((up + dn) / 2.0) * 100.0
        mw = (v >= 0.60 - 1e-6) & (v <= vdd - 0.35 + 1e-6)
        cname = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
        dc_rows[cname] = dict(
            vdd=vdd, lo_v=round(float(v[lo]), 3), hi_v=round(float(v[hi]), 3),
            up_mid_ua=round(float(up[mid] * 1e6), 2), dn_mid_ua=round(float(dn[mid] * 1e6), 2),
            mm_mid_pct=round(float(mm[mid]), 4), mm_win_max_pct=round(float(np.max(mm[mw])), 4),
        )
        print(f"  DC v4.1 {cname:18s}: win=[{v[lo]:.2f}, {v[hi]:.2f}] V | I={up[mid]*1e6:.1f}/{dn[mid]*1e6:.1f} uA | max_mm={np.max(mm[mw]):.3f}%", flush=True)

    # 2) Two-pass 250 MHz ripple & static dPW comparison: v4 vs v4.1
    tref, f0, kvco, rz, ci, cctrl, ton = 4e-9, 2e9, 1e9, 4130.0, 18.38e-12, 0.5e-12, 450e-12
    periods = 14
    t_stop = periods * tref + 1e-9  # 57 ns

    def build_ripple_deck(ver: str, proc: str, rc: str, vdd: float, temp: int, v0: float, dn_delay: float) -> str:
        if ver == "v4":
            inc = f'.include "{REPO}/analog/pll/cp/spice/charge_pump_steer_v4.spice"'
            sub = "pll_cp_steer_v4"
        else:
            inc = f'.include "{REPO}/analog/pll/cp/spice/charge_pump_steer_v4p1_cand.spice"'
            sub = "pll_cp_steer_v4p1_cand"
        dn_start = 1e-9 + dn_delay
        dn_ton = ton - dn_delay
        base = f"""* CP {ver} 250 MHz ripple ({proc}_{rc}, dn_delay={dn_delay*1e12:.2f}ps)
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/common/devices/spice/cmos_logic.spice"
{inc}
.param supply={vdd} irefn=50u irefp=50u
Vdd vdd 0 {{supply}}
Vbias vb 0 {{supply}}
In vb vbn {{irefn}}
Ip vbp 0 {{irefp}}
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4
Vup up 0 PULSE(0 {{supply}} 1n 30p 30p {ton:.5e} 4n)
Vdn dn 0 PULSE(0 {{supply}} {dn_start:.6e} 30p 30p {dn_ton:.5e} 4n)
Xcp up dn ctrl vbn vbp ibcp vdd 0 {sub}
Rz ctrl z {rz}
Ci z 0 {ci}
Cctrl ctrl 0 {cctrl}
* ibias: after bias.real
.ic v(ctrl)={v0:.4f} v(z)={v0:.4f}
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(ctrl) v(z) v(up) v(dn) v(xcp.up_b) v(xcp.dn_on)
.control
set num_threads=1
set filetype=binary
tran 2p {t_stop:.6e} 25n 4p
write ripple.raw v(ctrl) v(z) v(up) v(dn) v(xcp.up_b) v(xcp.dn_on)
quit
.endc
.end
"""
        return bias.section(bias.real(base), proc, rc).replace(
            "* ibias: after bias.real",
            "XIbcp ibcp vgi_bias vdd serdes_bias_pcopy n=4",
        )

    def analyse_ripple(raw: Path) -> dict:
        w = spice.Waves(raw)
        t, vc, vz = w.t, w["v(ctrl)"], w["v(z)"]
        t1 = 1e-9 + (periods - 4) * tref  # 41 ns -> 57 ns (last 4 periods)
        sel = t >= t1
        q = (np.interp(t[-1], t, vz) - np.interp(t1, t, vz)) * ci + (np.interp(t[-1], t, vc) - np.interp(t1, t, vc)) * cctrl
        q_per = q / ((t[-1] - t1) / tref)
        tt, vv = t[sel], vc[sel]
        p = np.polyfit(tt, vv, 1)
        r = vv - np.polyval(p, tt)
        ph = 2 * np.pi * kvco * np.concatenate(([0.0], np.cumsum(0.5 * (r[1:] + r[:-1]) * np.diff(tt))))
        ph -= np.polyval(np.polyfit(tt, ph, 1), tt)
        jit_pp = float(np.ptp(ph) / (2 * np.pi * f0))
        v1 = 2 * abs(np.trapezoid(r * np.exp(-2j * np.pi * tt / tref), tt)) / (tt[-1] - tt[0])
        spur = float(20 * np.log10(max(kvco * v1 / (2 * (1 / tref)), 1e-30)))
        return dict(
            q_per_fc=round(float(q_per * 1e15), 3),
            dpw_ps=round(float(q_per / 200e-6 * 1e12), 2),
            ripple_pp_mv=round(float(np.ptp(r) * 1e3), 2),
            r_min_mv=round(float(np.min(r) * 1e3), 2),
            r_max_mv=round(float(np.max(r) * 1e3), 2),
            jitter_pp_ps=round(float(jit_pp * 1e12), 3),
            spur_dbc=round(float(spur), 2),
        )

    # Pass 1: equal pulses
    p1_jobs = []
    for ver in ("v4", "v4p1"):
        for proc, rc, vdd, temp, v0 in CP_CORNERS:
            tag = f"rip_{ver}_{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}_p1"
            rdir = cdir / tag
            p1_jobs.append(dict(
                deck=build_ripple_deck(ver, proc, rc, vdd, temp, v0, 0.0),
                run_dir=rdir, check=rdir / "ripple.raw", t_end=t_stop, timeout_s=240,
            ))
    run_resumable(p1_jobs, workers)

    # Pass 2: compensated static phase offset
    p2_jobs = []
    p1_res = {}
    for ver in ("v4", "v4p1"):
        for proc, rc, vdd, temp, v0 in CP_CORNERS:
            cname = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
            m1 = analyse_ripple(cdir / f"rip_{ver}_{cname}_p1/ripple.raw")
            p1_res[(ver, cname)] = m1
            dn_delay = -m1["dpw_ps"] * 1e-12
            tag = f"rip_{ver}_{cname}_p2"
            rdir = cdir / tag
            p2_jobs.append(dict(
                deck=build_ripple_deck(ver, proc, rc, vdd, temp, v0, dn_delay),
                run_dir=rdir, check=rdir / "ripple.raw", t_end=t_stop, timeout_s=240,
            ))
    run_resumable(p2_jobs, workers)

    rip_rows = {}
    print(f"\n  {'Corner':<18} | {'v4 rip(mV)':>10} {'v4 dPW(ps)':>10} {'v4 spur':>8} | {'v4.1 rip':>8} {'v4.1 dPW':>9} {'v4.1 spur':>9} | {'Gain':>6}")
    for proc, rc, vdd, temp, _ in CP_CORNERS:
        cname = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
        m4_p1 = p1_res[("v4", cname)]
        m4_p2 = analyse_ripple(cdir / f"rip_v4_{cname}_p2/ripple.raw")
        m41_p1 = p1_res[("v4p1", cname)]
        m41_p2 = analyse_ripple(cdir / f"rip_v4p1_{cname}_p2/ripple.raw")
        rip_rows[cname] = dict(v4_p1=m4_p1, v4_p2=m4_p2, v4p1_p1=m41_p1, v4p1_p2=m41_p2)
        ratio = m4_p2["ripple_pp_mv"] / max(m41_p2["ripple_pp_mv"], 0.1)
        print(
            f"  {cname:<18} | {m4_p2['ripple_pp_mv']:10.2f} {m4_p1['dpw_ps']:+10.2f} {m4_p2['spur_dbc']:8.1f} | "
            f"{m41_p2['ripple_pp_mv']:8.2f} {m41_p1['dpw_ps']:+9.2f} {m41_p2['spur_dbc']:9.1f} | {ratio:5.2f}x",
            flush=True,
        )

    summary = dict(dc_v4p1=dc_rows, ripple=rip_rows)
    (cdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# =============================================================================
# STAGE 2: TX LDO Light-Load PM Fix + 800 mVpp LDO AC Stability & Headroom
# =============================================================================
def stage_ldo(out: Path, workers: int) -> dict:
    print("\n=== [Stage LDO] Experiment 1B: TX LDO Light-Load PM Fix & 800 mVpp LDO Headroom ===", flush=True)
    ldir = out / "tx_ldo"
    ldir.mkdir(parents=True, exist_ok=True)

    # Create AC-broken test copies of sst_vdrv_ldo (lbleed=38 vs 5.0) and sst_vdrv_ldo_800m (lbleed=5.0)
    tx_drv_txt = (REPO / "analog/tx/sst/spice/tx_sst_driver.spice").read_text()
    i0 = tx_drv_txt.index(".subckt sst_vdrv_ldo ")
    i1 = tx_drv_txt.index(".ends sst_vdrv_ldo") + len(".ends sst_vdrv_ldo")
    ldo400_orig = tx_drv_txt[i0:i1]
    ldo400_ac = (
        ldo400_orig
        .replace(".subckt sst_vdrv_ldo vbg vdrv vdd vss params: ltop=63.0 lbot=37.0",
                 ".subckt sst_vdrv_ldo_ac vbg vdrv vdd vss fb_in params: ltop=63.0 lbot=37.0 lbleed=38.0")
        .replace("Xfb  vgate vdrv tail vdd", "Xfb  vgate fb_in tail vdd")
        .replace("Xrbleed vdrv vss vss sky130_fd_pr__res_high_po_1p41 l=38.0",
                 "Xrbleed vdrv vss vss sky130_fd_pr__res_high_po_1p41 l={lbleed}")
        .replace(".ends sst_vdrv_ldo", ".ends sst_vdrv_ldo_ac")
    )

    tx800_txt = (REPO / "analog/link_5g/spice/tx_sst_800m_cand.spice").read_text()
    j0 = tx800_txt.index(".subckt sst_vdrv_ldo_800m ")
    j1 = tx800_txt.index(".ends sst_vdrv_ldo_800m") + len(".ends sst_vdrv_ldo_800m")
    ldo800_orig = tx800_txt[j0:j1]
    ldo800_ac = (
        ldo800_orig
        .replace(".subckt sst_vdrv_ldo_800m vbg vdrv vdd vss params: ltop=4.2 lbot=95.8 lbleed=5.0",
                 ".subckt sst_vdrv_ldo_800m_ac vbg vdrv vdd vss fb_in params: ltop=4.2 lbot=95.8 lbleed=5.0")
        .replace("Xfb   nd    vdrv tail vss", "Xfb   nd    fb_in tail vss")
        .replace(".ends sst_vdrv_ldo_800m", ".ends sst_vdrv_ldo_800m_ac")
    )
    ac_inc = ldir / "ldo_ac_models.spice"
    ac_inc.write_text(ldo400_ac + "\n\n" + ldo800_ac + "\n")

    configs = [
        ("ldo400_orig_l38_light", "sst_vdrv_ldo_ac", "lbleed=38.0", 0.0, 0.44),
        ("ldo400_fix_l5_light",   "sst_vdrv_ldo_ac", "lbleed=5.0",  0.0, 0.44),
        ("ldo400_fix_l5_load4m",  "sst_vdrv_ldo_ac", "lbleed=5.0",  4.5e-3, 0.44),
        ("ldo800_pon_l5_light",   "sst_vdrv_ldo_800m_ac", "lbleed=5.0", 0.0, 1.15),
        ("ldo800_pon_l5_load12m", "sst_vdrv_ldo_800m_ac", "lbleed=5.0", 12.0e-3, 1.15),
        # Also test NMOS-pass 0.86V LDO at 8.5mA to prove 1.65V headroom failure!
        ("ldo800_nmos_0p86_8p5m", "sst_vdrv_ldo_ac", "ltop=28.3 lbot=71.7 lbleed=5.0", 8.5e-3, 0.86),
    ]

    jobs = []
    for proc, rc, vdd, temp in CORNERS_5G:
        cname = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
        rdir = ldir / cname
        blocks = []
        for idx, (cfg_name, sub, par, iload, vinit) in enumerate(configs):
            pass
        # Put all 6 configs in one deck per corner (parallel instances, super fast!)
        insts = []
        ctrls = [".control", "set num_threads=1", "set filetype=binary", "op"]
        for idx, (cfg_name, sub, par, iload, vinit) in enumerate(configs):
            insts.append(f"""
Xldo_{idx} vbg vdrv_{idx} vdd 0 fbin_{idx} {sub} {par}
Lbrk_{idx} vdrv_{idx} fbin_{idx} 1e6
Cinj_{idx} fbin_{idx} vac 1e6
Iload_{idx} vdrv_{idx} 0 DC {iload:.4e}
""")
            ctrls.append(f"let vd{idx}=v(vdrv_{idx})")
            ctrls.append(f"let vg{idx}=v(xldo_{idx}.vgate)")
            ctrls.append(f"echo LDO_OP {cfg_name} vdrv=$&vd{idx} vgate=$&vg{idx}")
        ctrls.append("ac dec 40 100 1g")
        vecs = []
        for idx in range(len(configs)):
            ctrls.append(f"let lg{idx} = -v(vdrv_{idx})/v(fbin_{idx})")
            vecs.append(f"lg{idx}")
        ctrls += [f"write ldo_ac.raw {' '.join(vecs)}", "quit", ".endc"]
        deck = f"""* TX LDO AC stability & headroom ({cname})
.lib "{project.model_library()}" {proc}_{rc if rc != 'tt' else 'tt'}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{ac_inc}"
Vdd vdd 0 {vdd}
Vbg vbg 0 1.20
Vac vac 0 DC 0 AC 1
{"".join(insts)}
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u
{chr(10).join(ctrls)}
.end
"""
        # sky130.lib.spice uses tt (not tt_tt)
        deck = deck.replace(f'"{project.model_library()}" tt_tt', f'"{project.model_library()}" tt')
        jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "ldo_ac.raw", timeout_s=180))
    run_resumable(jobs, workers)

    rows = {}
    print(f"\n  {'Config':<23} | {'Corner':<16} | {'Vdrv(V)':>7} {'Vgate(V)':>8} {'DC(dB)':>7} {'UGB(MHz)':>9} {'PM(deg)':>8}")
    for proc, rc, vdd, temp in CORNERS_5G:
        cname = f"{proc}_{rc}_v{int(round(vdd*1000))}_t{temp}"
        rdir = ldir / cname
        op_map = {}
        for line in (rdir / "simulator.log").read_text(errors="replace").splitlines():
            if line.startswith("LDO_OP "):
                toks = line.split()
                nm = toks[1]
                kv = dict(t.split("=") for t in toks[2:])
                op_map[nm] = {k: float(v) for k, v in kv.items()}
        ac = read_complex_raw(rdir / "ldo_ac.raw")
        f = np.real(ac["frequency"])
        rows[cname] = {}
        for idx, (cfg_name, _, _, _, _) in enumerate(configs):
            T = ac[f"lg{idx}"]
            mdb = 20 * np.log10(np.maximum(np.abs(T), 1e-12))
            ph = np.unwrap(np.angle(T, deg=True))
            ph -= round(ph[0] / 360.0) * 360.0
            dc_db = float(mdb[0])
            cross = np.where(mdb <= 0)[0]
            if len(cross) and cross[0] > 0:
                k = int(cross[0])
                fr = -mdb[k - 1] / (mdb[k] - mdb[k - 1])
                ugb = float(f[k - 1] * ((f[k] / f[k - 1]) ** fr)) / 1e6
                pm = float(180.0 + ph[k - 1] + fr * (ph[k] - ph[k - 1]))
            else:
                ugb, pm = 0.0, float("nan")
            vd = op_map[cfg_name]["vdrv"]
            vg = op_map[cfg_name]["vgate"]
            rows[cname][cfg_name] = dict(
                vdrv_v=round(vd, 4), vgate_v=round(vg, 4),
                dc_gain_db=round(dc_db, 2), ugb_mhz=round(ugb, 2), pm_deg=round(pm, 2),
            )
            print(f"  {cfg_name:<23} | {cname:<16} | {vd:7.4f} {vg:8.4f} {dc_db:7.1f} {ugb:9.2f} {pm:8.1f}", flush=True)

    (ldir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    return rows


# =============================================================================
# Helper functions for TX & CTLE transient PRBS-7 eye benchmarks
# =============================================================================
def build_sequence(payload_bits: int = 96) -> np.ndarray:
    alt = [i & 1 for i in range(32)]
    marker = [(w >> b) & 1 for w in (0xD3A5, 0x6C9E) for b in range(16)]
    payload = eye.prbs7(payload_bits + 8, seed=0x5D)
    return np.array(alt + marker + payload, dtype=int)


def encode_zq_ffe(n_zq: int, n_post: int) -> dict[str, int]:
    n_main = n_zq - n_post
    assert 0 <= n_main <= 23 and 0 <= n_post <= 5, (n_zq, n_post)
    m4 = 1 if n_main >= 16 else 0
    rem = n_main - 8 * m4
    f2 = 1 if n_post >= 4 else 0
    remf = n_post - 2 * f2
    return dict(
        m0=rem & 1, m1=(rem >> 1) & 1, m2=(rem >> 2) & 1, m3=(rem >> 3) & 1, m4=m4,
        f0=remf - 2 * (1 if remf >= 2 else 0), f1=1 if remf >= 2 else 0, f2=f2,
        ffe_en=1 if n_post > 0 else 0,
    )


def pwl_lines(head: str, pts: list[tuple[float, float]]) -> str:
    toks = [f"{t:.7e} {v:.5f}" for t, v in pts]
    out = [f"{head} PWL("]
    for i in range(0, len(toks), 6):
        out.append("+ " + " ".join(toks[i:i + 6]))
    return "\n".join(out) + " )\n"


def staggered_4ph_stimuli(bits: np.ndarray, supply: float, ui: float, t0: float, edge: float = 25e-12) -> str:
    lines = []
    n_cyc = len(bits) // 4
    init_val = [0, 1, 0, 1]
    for k in range(4):
        pts_p = [(0.0, supply if init_val[k] else 0.0)]
        pts_n = [(0.0, 0.0 if init_val[k] else supply)]
        prev = init_val[k]
        for m in range(n_cyc):
            b = int(bits[4 * m + k])
            if b != prev:
                t_upd = t0 + (4 * m + k - 1) * ui
                vp0, vp1 = (supply if prev else 0.0), (supply if b else 0.0)
                vn0, vn1 = (0.0 if prev else supply), (0.0 if b else supply)
                pts_p.extend([(t_upd - edge / 2, vp0), (t_upd + edge / 2, vp1)])
                pts_n.extend([(t_upd - edge / 2, vn0), (t_upd + edge / 2, vn1)])
                prev = b
        lines.append(pwl_lines(f"Vd{k} d{k} 0", pts_p))
        lines.append(pwl_lines(f"Vdb{k} db{k} 0", pts_n))
    return "".join(lines)


# =============================================================================
# STAGE 3: Experiment 2A — TX SST @ 5 Gb/s & 800 mVpp TX Candidate @ 4G & 5G
# =============================================================================
def stage_tx5g(out: Path, workers: int) -> dict:
    print("\n=== [Stage TX5G] Experiment 2A: TX 400mVpp @ 5G + TX 800mVpp Candidate @ 4G & 5G ===", flush=True)
    tdir = out / "tx_5g"
    tdir.mkdir(parents=True, exist_ok=True)

    # First: ZQ calibration & S11 sweep for 800 mVpp P-over-N candidate across 4 corners
    # Find optimal N_zq for 800 mVpp candidate (quick OP/AC check across N_zq = 10..22)
    cal_jobs = []
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        rdir = tdir / f"cal800_{cname}"
        # Test 1 single slice to measure exact R_pu_slice and R_pd_slice, plus full 16-slice S11
        deck = f"""* 800 mVpp P-over-N slice impedance calibration ({cname})
.lib "{project.model_library()}" {lib_sec}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/tx/sst/spice/tx_sst_driver.spice"
.include "{REPO}/analog/link_5g/spice/tx_sst_800m_cand.spice"
.param vdd_v={vdd}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20
Xldo vbg vdrv vdd 0 sst_vdrv_ldo_800m
* 12 mA nominal load on LDO during calibration
Iload vdrv 0 12m
* Single unit slice driven static HIGH (pad_p->vdrv, pad_n->vss)
Xsl vdd 0 vdd 0 pad_p pad_n vdrv vdd 0 sst_slice_pon_800m
Vtp pad_p 0 DC 0.85
Vtn pad_n 0 DC 0.25
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u
.control
set num_threads=1
op
let vd = v(vdrv)
let vg = v(xldo.vgate)
let rpu_sl = (v(vdrv) - 0.85) / abs(i(Vtp))
let rpd_sl = 0.25 / abs(i(Vtn))
let ravg_sl = 0.5 * (rpu_sl + rpd_sl)
let nzq_opt = ravg_sl / 50.0
echo CAL800 {cname} vdrv=$&vd vgate=$&vg rpu_sl=$&rpu_sl rpd_sl=$&rpd_sl nzq_opt=$&nzq_opt
quit
.endc
.end
"""
        cal_jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "simulator.log", log_marker="CAL800 ", timeout_s=120))
    run_resumable(cal_jobs, workers)

    tx800_zq = {}
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        log = (tdir / f"cal800_{cname}/simulator.log").read_text(errors="replace")
        for line in log.splitlines():
            if line.startswith("CAL800 "):
                kv = dict(t.split("=") for t in line.split()[2:])
                nzq = int(np.clip(round(float(kv["nzq_opt"])), 10, 23))
                # Ensure n_main = nzq - 2 is valid (for flat 800mVpp mode with 2 opposing slices)
                tx800_zq[cname] = dict(
                    n_zq=nzq,
                    vdrv_v=round(float(kv["vdrv"]), 4),
                    vgate_v=round(float(kv["vgate"]), 4),
                    rpu_sl=round(float(kv["rpu_sl"]), 1),
                    rpd_sl=round(float(kv["rpd_sl"]), 1),
                )
                print(
                    f"  CAL800 {cname:<18}: Vdrv={kv['vdrv']}V Vg={kv['vgate']}V | "
                    f"Rpu_sl={float(kv['rpu_sl']):.0f} Rpd_sl={float(kv['rpd_sl']):.0f} -> N_zq={nzq}",
                    flush=True,
                )

    # Full-driver Rout & S11 (1G / 2G / 2.5G) for 800 mVpp P-over-N candidate
    s11_jobs = []
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        nzq = tx800_zq[cname]["n_zq"]
        n_opp = 2
        bc = encode_zq_ffe(nzq, n_opp)
        ctrl_lines = "\n".join(f"Vctrl_{k} {k} 0 {vdd if v else 0.0}" for k, v in bc.items())
        rdir = tdir / f"s11_800_{cname}"
        deck = f"""* 800 mVpp P-over-N Full-Driver Rout & S11 ({cname}, Nzq={nzq}, Nopp={n_opp})
.lib "{project.model_library()}" {lib_sec}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/tx/sst/spice/tx_sst_driver.spice"
.include "{REPO}/analog/link_5g/spice/tx_sst_800m_cand.spice"
.param vdd_v={vdd}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20
Vphi0 phi0 0 {{vdd_v}}
Vphi90 phi90 0 0
Vphi180 phi180 0 0
Vphi270 phi270 0 {{vdd_v}}
Vd0 d0 0 {{vdd_v}}
Vd1 d1 0 0
Vd2 d2 0 0
Vd3 d3 0 0
Vdb0 db0 0 0
Vdb1 db1 0 {{vdd_v}}
Vdb2 db2 0 {{vdd_v}}
Vdb3 db3 0 {{vdd_v}}
{ctrl_lines}
Xdut d0 d1 d2 d3 db0 db1 db2 db3 phi0 phi90 phi180 phi270
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en vbg lqp lqn vdrv vdd 0 serdes_tx_sst_800m_flat
Clpp lqp 0 200f
Clpn lqn 0 200f
Vtest_p lqp 0 DC 0.78 AC 1
Vtest_n lqn 0 DC 0.37 AC 0
.nodeset v(vdrv)=1.15 v(xdut.xldo.vgate)=0.70
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u
.control
set num_threads=1
op
let vd = v(vdrv)
let vg = v(xdut.xldo.vgate)
echo S11_DC {cname} vdrv=$&vd vgate=$&vg
ac dec 30 1e6 5e9
let zout = -1 / i(Vtest_p)
let gamma = (zout - 50) / (zout + 50)
let s11_db = 20 * log10(mag(gamma))
let rdc = mag(zout[0])
meas ac s11_1g find s11_db at=1e9
meas ac s11_2g find s11_db at=2e9
meas ac s11_2p5g find s11_db at=2.5e9
echo S11_AC {cname} rout_dc=$&rdc s11_1g=$&s11_1g s11_2g=$&s11_2g s11_2p5g=$&s11_2p5g
quit
.endc
.end
"""
        s11_jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "simulator.log", log_marker="S11_AC ", timeout_s=120))
    run_resumable(s11_jobs, workers)

    s11_rows = {}
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        kv = {}
        for line in (tdir / f"s11_800_{cname}/simulator.log").read_text(errors="replace").splitlines():
            if line.startswith(("S11_DC ", "S11_AC ")):
                for tok in line.split()[2:]:
                    k, v = tok.split("=", 1)
                    kv[k] = float(v)
        s11_rows[cname] = {k: round(v, 3) for k, v in kv.items()}
        s11_rows[cname]["n_zq"] = tx800_zq[cname]["n_zq"]
        print(
            f"  S11_800 {cname:<18}: Rout={kv['rout_dc']:5.2f} Ohm | "
            f"S11(1G/2G/2.5G)={kv['s11_1g']:6.2f}/{kv['s11_2g']:6.2f}/{kv['s11_2p5g']:6.2f} dB | "
            f"Vdrv={kv['vdrv']:.3f}V Vg={kv['vgate']:.3f}V",
            flush=True,
        )

    # Now build transient eye simulations!
    payload_bits = 96  # 64 training + 96 PRBS-7 + 8 tail = 168 bits (fast & accurate!)
    bits = build_sequence(payload_bits)
    (tdir / "bits.json").write_text(json.dumps(bits.tolist()))
    total_bits = len(bits)
    t0 = 4.0e-9

    def build_tx_deck(
        *, dut_kind: str, rate_gbps: float, lib_sec: str, vdd: float, temp: int,
        n_zq: int, n_post: int, channel: str, stim_file: str,
    ) -> tuple[str, float]:
        ui = 1.0 / (rate_gbps * 1e9)
        t_clk = 4 * ui
        tr = 25e-12 if rate_gbps >= 5.0 else 30e-12
        pw = 0.5 * t_clk - tr
        tf0 = 0.50 * t_clk - tr / 2
        tr90 = 0.25 * t_clk - tr / 2
        tr180 = 0.50 * t_clk - tr / 2
        tf270 = 0.25 * t_clk - tr / 2
        bc = encode_zq_ffe(n_zq, n_post)
        ctrl_lines = "\n".join(
            f"Vctrl_{k} {k} 0 PWL(0 0 0.5e-9 0 0.6e-9 {{vdd_v}})" if v else f"Vctrl_{k} {k} 0 0.0"
            for k, v in bc.items()
        )
        if channel == "rlc16":
            ch_inc = f'.include "{REPO}/verification/models/channel/diff_rlc16.spice"'
            ch_inst = "Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16"
            t_stop = t0 + total_bits * ui + 2.0e-9
        else:
            ch_inc = (
                f'.include "{REPO}/verification/models/channel/pcb_family/pcb_foster_cells.spice"\n'
                f'.include "{REPO}/verification/models/channel/pcb_family/C2_loss6.spice"'
            )
            ch_inst = "Xchannel ltp ltn lxp lxn 0 pcb_c2_loss6"
            t_stop = t0 + total_bits * ui + 4.0e-9

        if dut_kind == "tx400":
            extra_inc = ""
            sub = "serdes_tx_sst_driver"
            vcm_init = 0.22
            nodeset = ".nodeset v(vdrv)=0.44 v(lqp)=0.22 v(lqn)=0.22 v(xdut.xldo.vgate)=1.0"
        elif dut_kind == "tx800_flat":
            extra_inc = (
                f'.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"\n'
                f'.include "{REPO}/analog/link_5g/spice/tx_sst_800m_cand.spice"'
            )
            sub = "serdes_tx_sst_800m_flat"
            vcm_init = 0.575
            nodeset = ".nodeset v(vdrv)=1.15 v(lqp)=0.575 v(lqn)=0.575 v(xdut.xldo.vgate)=0.90"
        else:  # tx800_ffe
            extra_inc = (
                f'.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"\n'
                f'.include "{REPO}/analog/link_5g/spice/tx_sst_800m_cand.spice"'
            )
            sub = "serdes_tx_sst_800m_cand"
            vcm_init = 0.575
            nodeset = ".nodeset v(vdrv)=1.15 v(lqp)=0.575 v(lqn)=0.575 v(xdut.xldo.vgate)=0.90"

        deck = f"""* TX {dut_kind} @ {rate_gbps:.1f} Gb/s ({lib_sec}, {vdd}V, {temp}C, Nzq={n_zq}, Npost={n_post}, ch={channel})
.lib "{project.model_library()}" {lib_sec}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/tx/sst/spice/tx_sst_driver.spice"
{extra_inc}
{ch_inc}
.param vdd_v={vdd}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20
Vphi0   phi0   0 PULSE({{vdd_v}} 0 {tf0:.6e}   {tr:.3e} {tr:.3e} {pw:.6e} {t_clk:.6e})
Vphi90  phi90  0 PULSE(0 {{vdd_v}} {tr90:.6e}  {tr:.3e} {tr:.3e} {pw:.6e} {t_clk:.6e})
Vphi180 phi180 0 PULSE(0 {{vdd_v}} {tr180:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {t_clk:.6e})
Vphi270 phi270 0 PULSE({{vdd_v}} 0 {tf270:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {t_clk:.6e})
{ctrl_lines}
.include "{stim_file}"
Xdut d0 d1 d2 d3 db0 db1 db2 db3 phi0 phi90 phi180 phi270
+ m0 m1 m2 m3 m4 f0 f1 f2 ffe_en vbg lqp lqn vdrv vdd 0 {sub}
Vcm_init vcm_init 0 {vcm_init}
Rpad_dc_p lqp vcm_init 100k
Rpad_dc_n lqn vcm_init 100k
Clpp lqp 0 200f
Clpn lqn 0 200f
Rlpp lqp llp 0.3
Rlpn lqn lln 0.3
Llpp llp lap 0.5n
Llpn lln lan 0.5n
Clacp lap ltp 10n
Clacn lan ltn 10n
{ch_inst}
Rlc0 lxp lrp 0.01
Rlc1 lxn lrn 0.01
Clc0 lrp 0 100f
Clc1 lrn 0 100f
Vlcm lcm 0 0.9
Rlterm0 lrp lcm 50
Rlterm1 lrn lcm 50
{nodeset}
.temp {temp}
.options reltol=2e-4 abstol=1p vntol=2u klu
.save v(lqp) v(lqn) v(lrp) v(lrn) v(vdrv) v(xdut.p0) v(xdut.mp) v(vdd) i(Vdd)
.control
set num_threads=1
tran 3p {t_stop:.6e} 0 4p
let pad = v(lqp) - v(lqn)
let remote = v(lrp) - v(lrn)
let vdrv_v = v(vdrv)
let p0_v = v(xdut.p0)
let mp_v = v(xdut.mp)
let power = -v(vdd) * i(Vdd)
wrdata waveforms.tsv pad remote vdrv_v p0_v mp_v power
quit
.endc
.end
"""
        deck = spice.skip_output_before(deck, "2.5e-9")
        deck = spice.binary_output(deck)
        return deck, t_stop

    # Build stimulus files for 4G and 5G per supply
    stim_cache = {}
    for rate_gbps in (4.0, 5.0):
        ui = 1.0 / (rate_gbps * 1e9)
        edge = 25e-12 if rate_gbps >= 5.0 else 30e-12
        for vdd in (1.65, 1.80, 1.95):
            sp = tdir / f"stim_{int(rate_gbps)}g_v{int(round(vdd*1000))}.inc"
            if not sp.exists():
                sp.write_text(staggered_4ph_stimuli(bits, vdd, ui, t0, edge))
            stim_cache[(rate_gbps, vdd)] = sp

    # Define cases:
    # 1) Existing tx400 @ 5 Gb/s: 4 corners rlc16 (FFE=0) + 4 corners C2_loss6 (FFE=3) + TT C2_loss6 (FFE=0)
    # 2) New tx800 @ 4 Gb/s: 4 corners rlc16 (flat 800mVpp, n_opp=2)
    # 3) New tx800 @ 5 Gb/s: 4 corners rlc16 (flat 800mVpp, n_opp=2) + TT & SS 85C C2_loss6 (FFE=3)
    tx_cases = []
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        n400 = TX400_ZQ[(lib_sec, vdd, temp)]
        n800 = tx800_zq[cname]["n_zq"]
        tx_cases.append(("tx400", 5.0, lib_sec, vdd, temp, n400, 0, "rlc16"))
        tx_cases.append(("tx400", 5.0, lib_sec, vdd, temp, n400, 3, "c2"))
        tx_cases.append(("tx800_flat", 4.0, lib_sec, vdd, temp, n800, 2, "rlc16"))
        tx_cases.append(("tx800_flat", 5.0, lib_sec, vdd, temp, n800, 2, "rlc16"))
        if cname in ("tt_v1800_t27", "ss_hh_v1650_t85"):
            tx_cases.append(("tx800_ffe", 5.0, lib_sec, vdd, temp, n800, 3, "c2"))
    tx_cases.append(("tx400", 5.0, "tt", 1.80, 27, 16, 0, "c2"))

    jobs = []
    meta = []
    for dut_kind, rate_gbps, lib_sec, vdd, temp, n_zq, n_post, ch in tx_cases:
        tag = f"{dut_kind}_{int(rate_gbps)}g_{lib_sec}_v{int(round(vdd*1000))}_t{temp}_{ch}_f{n_post}"
        rdir = tdir / tag
        deck, t_stop = build_tx_deck(
            dut_kind=dut_kind, rate_gbps=rate_gbps, lib_sec=lib_sec, vdd=vdd, temp=temp,
            n_zq=n_zq, n_post=n_post, channel=ch, stim_file="stimuli.inc",
        )
        jobs.append(dict(
            deck=deck, run_dir=rdir, check=rdir / "waveforms.raw", t_end=t_stop,
            files={"stimuli.inc": stim_cache[(rate_gbps, vdd)]}, timeout_s=600,
        ))
        meta.append((tag, dut_kind, rate_gbps, lib_sec, vdd, temp, n_zq, n_post, ch))

    run_resumable(jobs, workers)

    rows = []
    print(
        f"\n  {'Tag':<38} | {'PadPP':>6} {'PadMrg':>7} {'PadSpr':>7} | {'RemMrg':>7} {'RemSpr':>7} | "
        f"{'Vdrv':>5} {'P0pp':>5} {'Pwr':>6} {'pJ/b':>5}"
    )
    for tag, dut_kind, rate_gbps, lib_sec, vdd, temp, n_zq, n_post, ch in meta:
        raw = tdir / tag / "waveforms.raw"
        if not raw.exists():
            print(f"  MISSING {tag}")
            continue
        ui = 1.0 / (rate_gbps * 1e9)
        w = spice.Waves(raw)
        seq = serial.Sequence(bits=bits, start_s=t0, ui_s=ui)
        pad_m, _ = serial.check(w.t, w["pad"], seq, payload_bits)
        rem_m, _ = serial.check(w.t, w["remote"], seq, payload_bits)
        pad_eye = eye.signed_eye(w.t, w["pad"], bits.tolist(), ui, t0, first_bit=serial.TRAINING_BITS, n_bits=payload_bits)
        rem_eye = eye.signed_eye(w.t, w["remote"], bits.tolist(), ui, t0, first_bit=serial.TRAINING_BITS, n_bits=payload_bits)
        t_win = (w.t >= t0 + serial.TRAINING_BITS * ui) & (w.t <= t0 + (serial.TRAINING_BITS + payload_bits) * ui)
        pwr_mw = float(np.trapezoid(w["power"][t_win], w.t[t_win]) / (w.t[t_win][-1] - w.t[t_win][0])) * 1e3
        vdrv_mean = float(np.mean(w["vdrv_v"][t_win]))
        vdrv_rip_mv = float(np.ptp(w["vdrv_v"][t_win]) * 1e3)
        p0_pp = float(np.ptp(w["p0_v"][t_win]))
        mp_pp = float(np.ptp(w["mp_v"][t_win]))
        # Measure p0 pulse width at VDD/2
        p0_t, p0_pol = crossings(w.t[t_win], w["p0_v"][t_win], 0.5 * vdd)
        pws = []
        for idx_c in range(len(p0_t) - 1):
            if p0_pol[idx_c] > 0 and p0_pol[idx_c + 1] < 0:
                pws.append((p0_t[idx_c + 1] - p0_t[idx_c]) * 1e12)
        p0_pw_ps = float(np.mean(pws)) if pws else 0.0

        rec = dict(
            tag=tag, dut_kind=dut_kind, rate_gbps=rate_gbps, corner=lib_sec, vdd=vdd, temp=temp,
            n_zq=n_zq, n_post=n_post, channel=ch,
            pad_functional=bool(pad_m["functional"]), pad_errors=int(pad_m["bit_errors"]),
            pad_pp_mv=round(pad_m["differential_pp_v"] * 1e3, 1),
            pad_margin_mv=round(pad_m["minimum_signed_margin_v"] * 1e3, 1),
            pad_eye_h_mv=round(pad_eye["height_v"] * 1e3, 1),
            pad_eye_w_ui=round(pad_eye["width_ui"], 3),
            pad_spread_ui=round(float(pad_m["transition_spread_ui"]), 4) if pad_m["transition_spread_ui"] is not None else None,
            rem_functional=bool(rem_m["functional"]), rem_errors=int(rem_m["bit_errors"]),
            rem_pp_mv=round(rem_m["differential_pp_v"] * 1e3, 1),
            rem_margin_mv=round(rem_m["minimum_signed_margin_v"] * 1e3, 1),
            rem_eye_h_mv=round(rem_eye["height_v"] * 1e3, 1),
            rem_eye_w_ui=round(rem_eye["width_ui"], 3),
            rem_spread_ui=round(float(rem_m["transition_spread_ui"]), 4) if rem_m["transition_spread_ui"] is not None else None,
            vdrv_mean_v=round(vdrv_mean, 4), vdrv_ripple_mvpp=round(vdrv_rip_mv, 1),
            p0_pp_v=round(p0_pp, 3), p0_pw_ps=round(p0_pw_ps, 1), mp_pp_v=round(mp_pp, 3),
            power_mw=round(pwr_mw, 2), pj_per_bit=round(pwr_mw / rate_gbps, 2),
        )
        rows.append(rec)
        pspr = f"{rec['pad_spread_ui']:7.4f}" if rec["pad_spread_ui"] is not None else "   None"
        rspr = f"{rec['rem_spread_ui']:7.4f}" if rec["rem_spread_ui"] is not None else "   None"
        print(
            f"  {tag:<38} | {rec['pad_pp_mv']:6.1f} {rec['pad_margin_mv']:7.1f} {pspr} | "
            f"{rec['rem_margin_mv']:7.1f} {rspr} | {vdrv_mean:5.3f} {p0_pp:5.2f} {pwr_mw:6.2f} {rec['pj_per_bit']:5.2f}",
            flush=True,
        )

    summary = dict(cal800=tx800_zq, s11_800=s11_rows, transient=rows)
    (tdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# =============================================================================
# STAGE 4: Experiment 2B-1 — RX CTLE AC & 5 Gb/s Transient Eye (R vs Shunt-Peaking)
# =============================================================================
def stage_ctle(out: Path, workers: int) -> dict:
    print("\n=== [Stage CTLE] Experiment 2B-1: RX CTLE Resistive vs met4+met5 Shunt-Peaking @ 5 Gb/s ===", flush=True)
    cdir = out / "rx_ctle_5g"
    cdir.mkdir(parents=True, exist_ok=True)

    # 1) AC response at Cload = 80 fF (nominal) and 120 fF (post-layout parasitic stress)
    ac_jobs = []
    for cload_ff in (80, 120):
        for proc, rc, vdd, temp in CORNERS_5G:
            lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
            cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}_c{cload_ff}"
            rdir = cdir / f"ac_{cname}"
            deck = f"""* RX CTLE AC comparison (R vs Shunt-Peaking met4+met5, {cname})
.lib "{project.model_library()}" {lib_sec}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/bias/spice/bias_v2.spice"
.include "{REPO}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"
.include "{REPO}/analog/link_5g/spice/rx_ctle_shunt_5g_cand.spice"
Vdd vdd 0 {vdd}
Iref vdd vbias 50u
Xbias vbias 0 serdes_bias_ctle_v2
Vcm cm 0 1.05
Vdm dm 0 DC 0 AC 1
Eip inp cm dm 0  0.5
Ein inn cm dm 0 -0.5
Veq0 eq0 0 {vdd}
Veq1 eq1 0 {vdd}
* 0) Existing resistive CTLE (600 Ohm)
X0 inp inn op0 on0 eq0 eq1 vbias vdd 0 serdes_rx_ctle_pdk
C0p op0 0 {cload_ff}f
C0n on0 0 {cload_ff}f
* 1) Drop-in shunt-peaking CTLE (Lhalf=4.5nH, k=0.45 -> Leff=6.53nH, same 600 Ohm & 1.31 mW)
X1 inp inn op1 on1 eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g
C1p op1 0 {cload_ff}f
C1n on1 0 {cload_ff}f
* 2) 5G-tuned shunt-peaking CTLE (RL=480 Ohm, wtail=60, 1.6 mW, Lhalf=4.5nH k=0.45)
X2 inp inn op2 on2 eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g l_rload=3.20 wtail=60 nftail=10
C2p op2 0 {cload_ff}f
C2n on2 0 {cload_ff}f
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u klu
.control
set num_threads=1
set filetype=binary
ac dec 100 1meg 20g
let g0 = v(op0,on0)/v(inp,inn)
let g1 = v(op1,on1)/v(inp,inn)
let g2 = v(op2,on2)/v(inp,inn)
write ctle_ac.raw g0 g1 g2
quit
.endc
.end
"""
            ac_jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "ctle_ac.raw", timeout_s=120))
    run_resumable(ac_jobs, workers)

    ac_rows = {}
    vnames = [("r_only", "g0"), ("shunt_600", "g1"), ("shunt_480_5g", "g2")]
    print(f"\n  {'Corner/Load':<24} | {'Variant':<13} | {'LF(dB)':>6} {'@2.5G':>6} {'Pk2.5G':>7} {'MaxPk':>7} {'BW3(GHz)':>9}")
    for cload_ff in (80, 120):
        for proc, rc, vdd, temp in CORNERS_5G:
            lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
            cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}_c{cload_ff}"
            d = read_complex_raw(cdir / f"ac_{cname}/ctle_ac.raw")
            f = np.real(d["frequency"])
            ac_rows[cname] = {}
            for vn, gk in vnames:
                db = 20 * np.log10(np.maximum(np.abs(d[gk]), 1e-12))
                g_lf = float(db[0])
                g_25 = float(np.interp(2.5e9, f, db))
                pk_idx = int(np.argmax(db))
                below = np.where(db < g_lf - 3.0)[0]
                bw = float(f[below[0]] / 1e9) if len(below) else float("nan")
                ac_rows[cname][vn] = dict(
                    lf_db=round(g_lf, 2), g_2p5g_db=round(g_25, 2), peaking_2p5g_db=round(g_25 - g_lf, 2),
                    max_pk_db=round(float(db[pk_idx] - g_lf), 2), max_pk_ghz=round(float(f[pk_idx] / 1e9), 2),
                    bw3_ghz=round(bw, 2),
                )
                print(
                    f"  {cname:<24} | {vn:<13} | {g_lf:+6.2f} {g_25:+6.2f} {g_25-g_lf:+7.2f} "
                    f"{db[pk_idx]-g_lf:+7.2f} {bw:9.2f}",
                    flush=True,
                )

    # 2) Transient 5 Gb/s C2_loss6 eye comparison (all 3 CTLEs in parallel driven by 5 Gb/s 400 mVpp FFE=3 launch!)
    payload_bits = 96
    bits = build_sequence(payload_bits)
    ui = 200e-12
    t0 = 3.0e-9
    t_stop = t0 + len(bits) * ui + 4.0e-9  # ~40.6 ns

    # Build clean 5 Gb/s 400 mVpp (200 mV single-ended peak -> 400 mVpp diff into 100 Ohm; no TX FFE so CTLE equalizes C2_loss6!)
    def build_5g_ffe_pwl(bits_arr: np.ndarray, v_amp_oc: float = 0.22, alpha: float = 0.0, tr: float = 25e-12) -> tuple[str, str]:
        # Ideal double-terminated source: src_p = +/- v_amp_oc, src_n = -/+ v_amp_oc -> open-circuit diff = +/- 2*v_amp_oc = 880 mVpp -> 440 mVpp launch!
        pts_p, pts_n = [(0.0, 0.0)], [(0.0, 0.0)]
        prev_b = 0
        prev_v = 0.0
        for n, b in enumerate(bits_arr):
            s_cur = 1.0 if b else -1.0
            s_prv = 1.0 if prev_b else -1.0
            v = v_amp_oc * ((1.0 - alpha) * s_cur - alpha * s_prv)
            t_e = t0 + n * ui
            pts_p.extend([(t_e - tr / 2, prev_v), (t_e + tr / 2, v)])
            pts_n.extend([(t_e - tr / 2, -prev_v), (t_e + tr / 2, -v)])
            prev_b = int(b)
            prev_v = v
        return pwl_lines("Vsrc_p src_p 0", pts_p), pwl_lines("Vsrc_n src_n 0", pts_n)

    stim_5g = cdir / "stim_5g_c2_noffe.inc"
    if not stim_5g.exists():
        sp, sn = build_5g_ffe_pwl(bits)
        stim_5g.write_text(sp + sn)

    tr_jobs = []
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        rdir = cdir / f"tran5g_{cname}"
        deck = f"""* RX CTLE 5 Gb/s C2_loss6 Transient Eye Comparison ({cname})
.lib "{project.model_library()}" {lib_sec}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/bias/spice/bias_v2.spice"
.include "{REPO}/analog/rx/cmos_rx/spice/rx_ctle_pdk.spice"
.include "{REPO}/analog/link_5g/spice/rx_ctle_shunt_5g_cand.spice"
.include "{REPO}/verification/models/channel/pcb_family/pcb_foster_cells.spice"
.include "{REPO}/verification/models/channel/pcb_family/C2_loss6.spice"
Vdd vdd 0 {vdd}
Iref vdd vbias 50u
Xbias vbias 0 serdes_bias_ctle_v2
Vcm cm 0 1.05
Veq0 eq0 0 {vdd}
Veq1 eq1 0 {vdd}
* 5 Gb/s 400 mVpp FFE=3/16 source -> 50 Ohm -> pkg -> C2_loss6 -> RX term
.include "stim.inc"
Rs_p src_p pad_p 50
Rs_n src_n pad_n 50
Cp_p pad_p 0 200f
Cp_n pad_n 0 200f
Lp_p pad_p ac_p 0.5n
Lp_n pad_n ac_n 0.5n
Cac_p ac_p ch_p 10n
Cac_n ac_n ch_n 10n
Xch ch_p ch_n rx_p rx_n 0 pcb_c2_loss6
Crx_p rx_p 0 100f
Crx_n rx_n 0 100f
Xterm rx_p rx_n cm 0 serdes_rx_term_pdk
* Drive all 3 CTLEs via ideal unity buffers so each sees the exact same RX input eye (80 fF slicer load)
Eip0 inp0 cm rx_p cm 1
Ein0 inn0 cm rx_n cm 1
X0 inp0 inn0 op0 on0 eq0 eq1 vbias vdd 0 serdes_rx_ctle_pdk
C0p op0 0 80f
C0n on0 0 80f
Eip1 inp1 cm rx_p cm 1
Ein1 inn1 cm rx_n cm 1
X1 inp1 inn1 op1 on1 eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g
C1p op1 0 80f
C1n on1 0 80f
Eip2 inp2 cm rx_p cm 1
Ein2 inn2 cm rx_n cm 1
X2 inp2 inn2 op2 on2 eq0 eq1 vbias vdd 0 serdes_rx_ctle_shunt_5g l_rload=3.20 wtail=60 nftail=10
C2p op2 0 80f
C2n on2 0 80f
.temp {temp}
.options reltol=2e-4 abstol=1p vntol=2u klu
.save v(rx_p) v(rx_n) v(op0) v(on0) v(op1) v(on1) v(op2) v(on2)
.control
set num_threads=1
tran 3p {t_stop:.6e} 0 4p
let rx_in = v(rx_p) - v(rx_n)
let out_r = v(op0) - v(on0)
let out_s600 = v(op1) - v(on1)
let out_s480 = v(op2) - v(on2)
wrdata eye5g.tsv rx_in out_r out_s600 out_s480
quit
.endc
.end
"""
        deck = spice.skip_output_before(deck, "2.0e-9")
        deck = spice.binary_output(deck)
        tr_jobs.append(dict(
            deck=deck, run_dir=rdir, check=rdir / "eye5g.raw", t_end=t_stop,
            files={"stim.inc": stim_5g}, timeout_s=600,
        ))
    run_resumable(tr_jobs, workers)

    tr_rows = {}
    seq = serial.Sequence(bits=bits, start_s=t0, ui_s=ui)
    print(f"\n  {'Corner':<18} | {'Node':<10} | {'PP(mV)':>7} {'Margin(mV)':>10} {'EyeH(mV)':>9} {'EyeW(UI)':>9} {'Spread(UI)':>10}")
    for proc, rc, vdd, temp in CORNERS_5G:
        lib_sec = "tt" if (proc == "tt" and rc == "tt") else f"{proc}_{rc}"
        cname = f"{lib_sec}_v{int(round(vdd*1000))}_t{temp}"
        w = spice.Waves(cdir / f"tran5g_{cname}/eye5g.raw")
        tr_rows[cname] = {}
        for k in ("rx_in", "out_r", "out_s600", "out_s480"):
            m, _ = serial.check(w.t, w[k], seq, payload_bits)
            ey = eye.signed_eye(w.t, w[k], bits.tolist(), ui, t0, first_bit=serial.TRAINING_BITS, n_bits=payload_bits)
            tr_rows[cname][k] = dict(
                functional=bool(m["functional"]), errors=int(m["bit_errors"]),
                pp_mv=round(m["differential_pp_v"] * 1e3, 1),
                margin_mv=round(m["minimum_signed_margin_v"] * 1e3, 1),
                eye_h_mv=round(ey["height_v"] * 1e3, 1),
                eye_w_ui=round(ey["width_ui"], 3),
                spread_ui=round(float(m["transition_spread_ui"]), 4) if m["transition_spread_ui"] is not None else None,
            )
            spr = f"{tr_rows[cname][k]['spread_ui']:10.4f}" if tr_rows[cname][k]["spread_ui"] is not None else "      None"
            print(
                f"  {cname:<18} | {k:<10} | {tr_rows[cname][k]['pp_mv']:7.1f} {tr_rows[cname][k]['margin_mv']:10.1f} "
                f"{tr_rows[cname][k]['eye_h_mv']:9.1f} {tr_rows[cname][k]['eye_w_ui']:9.3f} {spr}",
                flush=True,
            )

    summary = dict(ac=ac_rows, tran_5g=tr_rows)
    (cdir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# =============================================================================
# STAGE 5: Experiment 2B-2 & 2B-3 — Double-Tail Slicer (1.25 GHz) & CMOS PI + /2 (2.5 GHz)
# =============================================================================
def commutator_bits(code: int, supply: float) -> dict[str, float]:
    q, f = divmod(code, 8)
    a, b, nb = (q, (q + 1) % 8, f) if q % 2 == 0 else ((q + 1) % 8, q, 8 - f)
    v = {}
    for i in range(8):
        v[f"Va{i}"] = supply if i == a else 0.0
        v[f"Vb{i}"] = supply if i == b else 0.0
        v[f"Vf{i}"] = supply if i < nb else 0.0
    return v


def stage_rxclk(out: Path, workers: int) -> dict:
    print("\n=== [Stage RXCLK] Experiment 2B-2/3: Slicer @ 1.25 GHz & CMOS PI + /2 @ 2.0-3.0 GHz ===", flush=True)
    rroot = out / "rx_clk_5g"
    rroot.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # A) Double-Tail Slicer at 1.25 GHz (800 ps period = 400 ps eval + 400 ps reset)
    # -------------------------------------------------------------------------
    sdir = rroot / "slicer_1p25g"
    sdir.mkdir(parents=True, exist_ok=True)
    # 13 cycles at 0.8 ns spacing: rising edges at 0.8, 1.6, ..., 10.4 ns
    seq_mv = [50, -50, 50, -10, 10, -5, 5, -100, 10, 100, -10, -100, 5]
    t_per = 0.8e-9  # 1.25 GHz
    t_stop_s = (len(seq_mv) + 1) * t_per  # 11.2 ns

    def pwl_slicer(half_scale: float) -> str:
        pts = [f"0 {seq_mv[0] * 1e-3 * half_scale:.6f}"]
        for k, mv in enumerate(seq_mv):
            v = mv * 1e-3 * half_scale
            if k > 0:
                t_chg = (k + 0.55) * t_per
                vp = seq_mv[k - 1] * 1e-3 * half_scale
                pts.append(f"{t_chg:.4e} {vp:.6f}")
                pts.append(f"{t_chg + 30e-12:.4e} {v:.6f}")
        pts.append(f"{t_stop_s:.4e} {seq_mv[-1] * 1e-3 * half_scale:.6f}")
        return " ".join(pts)

    sl_jobs = []
    for proc, rc, vdd, temp in CORNERS_5G:
        cname = f"{proc}_v{int(round(vdd*1000))}_t{temp}"
        rdir = sdir / cname
        deck = f"""* Double-Tail Slicer @ 1.25 GHz (400 ps eval / 400 ps reset) — {cname}
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/rx/cmos_rx/spice/rx_dt_sampler.spice"
Vdd vdd 0 {vdd}
Vcm cm 0 1.45
* 1.25 GHz clock: rising at 0.8, 1.6, ..., 10.4 ns (tr=tf=20ps, pw=380ps -> 400ps high / 400ps low)
Vclk clk 0 PULSE(0 {vdd} 0.790n 20p 20p 380p 800p)
Vdp dsrc_p cm PWL({pwl_slicer(+0.5)})
Vdn dsrc_n cm PWL({pwl_slicer(-0.5)})
Rsp dsrc_p inp 600
Rsn dsrc_n inn 600
Ccp inp 0 20f
Ccn inn 0 20f
Vt5 t5 0 {vdd}
Vt4 t4 0 0
Vt3 t3 0 0
Vt2 t2 0 0
Vt1 t1 0 0
Vt0 t0 0 0
Xdut inp inn clk qp qn t5 t4 t3 t2 t1 t0 vdd 0 serdes_rx_dt_slicer
Clp qp 0 10f
Cln qn 0 10f
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(clk) v(qp) v(qn) v(inp) v(inn) v(dsrc_p) v(dsrc_n) v(xdut.xcomp.fn) v(xdut.xcomp.fp) v(xdut.outp_b) v(vdd) i(Vdd)
.control
set num_threads=1
set filetype=binary
tran 2p {t_stop_s:.4e} 0.4n 4p
let pwr = -v(vdd)*i(Vdd)
let kb_diff = (v(inp)-v(inn)) - (v(dsrc_p)-v(dsrc_n))
write slicer.raw v(clk) v(qp) v(qn) v(xdut.xcomp.fn) v(xdut.outp_b) kb_diff pwr
quit
.endc
.end
"""
        sl_jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "slicer.raw", t_end=t_stop_s, timeout_s=180))
    run_resumable(sl_jobs, workers)

    sl_rows = {}
    print(f"\n  [Slicer @ 1.25 GHz (400 ps half-cycle)]")
    print(f"  {'Corner':<16} | {'Acc':>6} | {'td50(ps)':>8} {'td10(ps)':>8} {'td5(ps)':>8} {'tdHyst':>8} | {'Margin':>8} {'PreV':>6} {'KB(mV)':>7} {'P(uW)':>7}")
    for proc, rc, vdd, temp in CORNERS_5G:
        cname = f"{proc}_v{int(round(vdd*1000))}_t{temp}"
        w = spice.Waves(sdir / cname / "slicer.raw")
        t = w.t
        vmid = 0.5 * vdd
        clk_r, pol = crossings(t, w["v(clk)"], vmid)
        clk_r = clk_r[pol > 0]
        qp, qn = w["v(qp)"], w["v(qn)"]
        correct = 0
        d50, d10, d5, dhyst = [], [], [], []
        pre_mins = []
        for idx, (tc, mv) in enumerate(zip(clk_r[: len(seq_mv)], seq_mv)):
            exp = 1 if mv > 0 else 0
            vp = float(np.interp(tc + 370e-12, t, qp))
            vn = float(np.interp(tc + 370e-12, t, qn))
            got = 1 if (vp > vmid and vn < vmid) else (0 if (vp < vmid and vn > vmid) else -1)
            if got == exp:
                correct += 1
            # Precharge completeness just before rising edge (tc - 10 ps)
            pre_mins.append(float(np.interp(tc - 10e-12, t, w["v(xdut.xcomp.fn)"])))
            if idx >= 1 and ((seq_mv[idx] > 0) != (seq_mv[idx - 1] > 0)):
                mask = (t >= tc) & (t <= tc + 400e-12)
                cr, _ = crossings(t[mask], qp[mask] - qn[mask], 0.0)
                td = float(cr[0] - tc) * 1e12 if len(cr) else float("nan")
                if idx in (1, 2):
                    d50.append(td)
                elif idx in (3, 4):
                    d10.append(td)
                elif idx in (5, 6):
                    d5.append(td)
                elif idx in (8, 10, 12):
                    dhyst.append(td)
        td50 = float(np.nanmax(d50))
        td10 = float(np.nanmax(d10))
        td5 = float(np.nanmax(d5))
        tdh = float(np.nanmax(dhyst))
        margin_ps = 400.0 - max(td10, tdh)
        kb_mask = np.zeros_like(t, dtype=bool)
        for tc in clk_r[1: len(seq_mv)]:
            kb_mask |= (t >= tc - 15e-12) & (t <= tc + 350e-12)
        kb_mv = float(np.max(np.abs(w["kb_diff"][kb_mask])) * 1e3)
        pmask = (t >= 1.6e-9) & (t <= 10.4e-9)
        pwr_uw = float(time_average(w["pwr"][pmask], t[pmask]) * 1e6)
        pre_v = float(min(pre_mins))
        sl_rows[cname] = dict(
            correct=correct, total=len(seq_mv),
            td_50mv_ps=round(td50, 1), td_10mv_ps=round(td10, 1), td_5mv_ps=round(td5, 1),
            td_hyst_ps=round(tdh, 1), half_cycle_margin_ps=round(margin_ps, 1),
            precharge_min_v=round(pre_v, 3), kb_diff_mv=round(kb_mv, 1), power_uw=round(pwr_uw, 1),
            ok=bool(correct == len(seq_mv) and margin_ps > 50.0),
        )
        print(
            f"  {cname:<16} | {correct:2d}/{len(seq_mv):2d}  | {td50:8.1f} {td10:8.1f} {td5:8.1f} {tdh:8.1f} | "
            f"{margin_ps:+8.1f} {pre_v:6.3f} {kb_mv:7.1f} {pwr_uw:7.1f}",
            flush=True,
        )

    # -------------------------------------------------------------------------
    # B) CMOS PI + /2 f_max Sweep (2.0..3.0 GHz, separate clean deck per freq!)
    # -------------------------------------------------------------------------
    pdir = rroot / "pi_5g"
    pdir.mkdir(parents=True, exist_ok=True)
    freqs_ghz = [2.0, 2.25, 2.5, 2.75, 3.0]

    def build_pi_single_deck(proc: str, vdd: float, temp: int, f_ghz: float, code: int, pi_params: str = "") -> tuple[str, float]:
        per = 1.0 / (f_ghz * 1e9)
        tr = 25e-12 if f_ghz <= 2.25 else 20e-12
        pw = 0.5 * per - tr
        t_stop = 5.5e-9
        t_save = 3.2e-9
        cb = commutator_bits(code, vdd)
        c_lines = "\n".join(f"Vc{k} c{k} 0 PULSE(0 {vdd} {k*per/8.0:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {per:.6e})" for k in range(8))
        ctrl_lines = "\n".join(f"{k} {k[1:].lower()} 0 {val}" for k, val in cb.items())
        deck = f"""* RX CMOS PI + /2 ({proc} {vdd}V {temp}C, f={f_ghz:.2f}GHz, code={code})
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/rx/cmos_rx/spice/rx_cmos_pi.spice"
Vdd vdd 0 {vdd}
{c_lines}
Vrst rst_n 0 PWL(0 0 0.70n 0 0.75n {vdd})
{ctrl_lines}
Xdut c0 c1 c2 c3 c4 c5 c6 c7
+ a0 a1 a2 a3 a4 a5 a6 a7
+ b0 b1 b2 b3 b4 b5 b6 b7
+ f0 f1 f2 f3 f4 f5 f6 f7
+ rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd 0 serdes_rx_cmos_pi_8ph {pi_params}
Cd0 ckd0 0 38f
Cd1 ckd1 0 38f
Cd2 ckd2 0 38f
Cd3 ckd3 0 38f
Ce0 cke0 0 38f
Ce1 cke1 0 38f
Ce2 cke2 0 38f
Ce3 cke3 0 38f
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(c0) v(dp) v(dn) v(ep) v(en) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) v(xdut.xpi.xch_d.mixp) v(xdut.xpi.xch_d.r1p) v(vdd) i(Vdd)
.control
set num_threads=1
set filetype=binary
tran 2.5p {t_stop:.3e} {t_save:.3e} 5p
let pwr = -v(vdd)*i(Vdd)
write pi.raw v(c0) v(dp) v(dn) v(ep) v(en) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) v(xdut.xpi.xch_d.mixp) v(xdut.xpi.xch_d.r1p) pwr
quit
.endc
.end
"""
        return deck, t_stop

    # 1) Frequency sweep at TT, SS -40C, SS 85C, FF -40C (code 4 = 50/50 mid-interpolation)
    #    PLUS a quick 5G-tuned mixer check (lres=7.6 cmix_w=3.2 -> ~40% lower tau_mix) at SS -40C!
    fmax_jobs = []
    fmax_meta = []
    for variant, pi_par, c_list in [
        ("baseline", "", CORNERS_5G),
        ("tuned5g", "lres=7.6 cmix_w=3.2", [("tt", "tt", 1.80, 27), ("ss", "hh", 1.65, -40), ("ss", "hh", 1.65, 85)]),
    ]:
        for proc, rc, vdd, temp in c_list:
            for fg in freqs_ghz:
                tag = f"fmax_{variant}_{proc}_v{int(round(vdd*1000))}_t{temp}_f{int(round(fg*100))}"
                rdir = pdir / tag
                deck, t_stop = build_pi_single_deck(proc, vdd, temp, fg, code=4, pi_params=pi_par)
                fmax_jobs.append(dict(deck=deck, run_dir=rdir, check=rdir / "pi.raw", t_end=t_stop, timeout_s=180))
                fmax_meta.append((tag, variant, f"{proc}_v{int(round(vdd*1000))}_t{temp}", vdd, fg))
    run_resumable(fmax_jobs, workers)

    fmax_rows = {}
    print(f"\n  [CMOS PI + /2 f_max Sweep (code=4 50/50 mix, 38 fF load)]")
    print(f"  {'Variant/Corner':<28} | {'fin':>5} | {'mixPP':>6} {'r1PP':>6} {'dpPP':>6} {'f_dp':>6} | {'ckdPP':>6} {'f_div':>6} {'P(mW)':>6} {'Status'}")
    for tag, variant, cname, vdd, fg in fmax_meta:
        raw = pdir / tag / "pi.raw"
        if not raw.exists():
            continue
        w = spice.Waves(raw)
        t = w.t
        sel = t >= 3.5e-9
        mix_pp = float(np.ptp(w["v(xdut.xpi.xch_d.mixp)"][sel]))
        r1_pp = float(np.ptp(w["v(xdut.xpi.xch_d.r1p)"][sel]))
        dp_pp = float(np.ptp(w["v(dp)"][sel]))
        ckd_pp = float(np.ptp(w["v(ckd0)"][sel]))
        ed, pd = crossings(t[sel], w["v(dp)"][sel] - w["v(dn)"][sel], 0.0)
        ed = ed[pd > 0]
        f_dp = float(1.0 / (np.mean(np.diff(ed)) * 1e9)) if len(ed) >= 2 else 0.0
        ec, pc = crossings(t[sel], w["v(ckd0)"][sel], 0.5 * vdd)
        ec = ec[pc > 0]
        f_div = float(1.0 / (np.mean(np.diff(ec)) * 1e9)) if len(ec) >= 2 else 0.0
        pwr_mw = float(time_average(w["pwr"][sel], t[sel]) * 1e3)
        pi_ok = abs(f_dp - fg) < 0.02 * fg and dp_pp > 0.85 * vdd
        div_ok = abs(f_div - fg / 2.0) < 0.02 * (fg / 2.0) and ckd_pp > 0.85 * vdd
        status = "PASS" if (pi_ok and div_ok) else ("PI_ONLY" if pi_ok else "FAIL")
        key = f"{variant}:{cname}"
        fmax_rows.setdefault(key, []).append(dict(
            fin_ghz=fg, mix_pp_v=round(mix_pp, 3), r1_pp_v=round(r1_pp, 3),
            dp_pp_v=round(dp_pp, 3), f_dp_ghz=round(f_dp, 3),
            ckd_pp_v=round(ckd_pp, 3), f_div_ghz=round(f_div, 3),
            power_mw=round(pwr_mw, 2), pi_ok=pi_ok, div_ok=div_ok, status=status,
        ))
        print(
            f"  {key:<28} | {fg:5.2f} | {mix_pp:6.3f} {r1_pp:6.3f} {dp_pp:6.3f} {f_dp:6.3f} | "
            f"{ckd_pp:6.3f} {f_div:6.3f} {pwr_mw:6.2f} {status}",
            flush=True,
        )

    # 2) At 2.5 GHz (5 Gb/s): 16-code sweep (codes 0,4,8,...,60) on TT & FF & SS 85C & SS -40C
    #    using 1 clean multi-code deck per corner (just changing static DC Va/Vb/Vf, NEVER changing Vc period!)
    codes_16 = list(range(0, 36, 4))  # 9 codes (0..32 step 4 -> 180 deg = 1 full 5G UI: 4 sectors + 4 50/50 mid-points!)
    per_2p5 = 0.4e-9
    per_1p25 = 0.8e-9
    ui_5g = 0.2e-9
    t_stop_c = 4.2e-9
    t_save_c = 2.6e-9

    def build_pi_2p5_codes_deck(proc: str, vdd: float, temp: int, pi_params: str = "") -> str:
        tr = 20e-12
        pw = 0.5 * per_2p5 - tr
        c_lines = "\n".join(f"Vc{k} c{k} 0 PULSE(0 {vdd} {k*per_2p5/8.0:.6e} {tr:.3e} {tr:.3e} {pw:.6e} {per_2p5:.6e})" for k in range(8))
        init_ctrl = "\n".join(f"{k} {k[1:].lower()} 0 0" for k in commutator_bits(0, vdd))
        blocks = []
        for code in codes_16:
            alters = [f"alter {k} dc={val}" for k, val in commutator_bits(code, vdd).items()]
            blocks.append("\n".join([
                f"* code {code}",
                *alters,
                f"tran 3p {t_stop_c:.3e} {t_save_c:.3e} 6p",
                "let pwr = -v(vdd)*i(Vdd)",
                f"write c{code:02d}.raw v(c0) v(dp) v(dn) v(ep) v(en) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) pwr",
                "destroy all",
            ]))
        return f"""* RX CMOS PI + /2 2.5 GHz 9-code sweep ({proc} {vdd}V {temp}C)
.lib "{project.model_library()}" {proc}
.include "{REPO}/analog/common/devices/spice/sky130_primitives.spice"
.include "{REPO}/analog/common/devices/spice/sky130_pfet_lvt.spice"
.include "{REPO}/analog/rx/cmos_rx/spice/rx_cmos_pi.spice"
Vdd vdd 0 {vdd}
{c_lines}
Vrst rst_n 0 PWL(0 0 0.70n 0 0.75n {vdd})
{init_ctrl}
Xdut c0 c1 c2 c3 c4 c5 c6 c7
+ a0 a1 a2 a3 a4 a5 a6 a7
+ b0 b1 b2 b3 b4 b5 b6 b7
+ f0 f1 f2 f3 f4 f5 f6 f7
+ rst_n dp dn ep en ckd0 ckd1 ckd2 ckd3 cke0 cke1 cke2 cke3 vdd 0 serdes_rx_cmos_pi_8ph {pi_params}
Cd0 ckd0 0 38f
Cd1 ckd1 0 38f
Cd2 ckd2 0 38f
Cd3 ckd3 0 38f
Ce0 cke0 0 38f
Ce1 cke1 0 38f
Ce2 cke2 0 38f
Ce3 cke3 0 38f
.temp {temp}
.options reltol=1e-4 abstol=1p vntol=1u klu
.save v(c0) v(dp) v(dn) v(ep) v(en) v(ckd0) v(ckd1) v(ckd2) v(ckd3) v(cke0) v(cke1) v(cke2) v(cke3) v(vdd) i(Vdd)
.control
set num_threads=1
set filetype=binary
{chr(10).join(blocks)}
quit
.endc
.end
"""

    c16_jobs = []
    c16_meta = []
    for variant, pi_par, c_list in [
        ("baseline", "", CORNERS_5G),
        ("tuned5g", "lres=7.6 cmix_w=3.2", [("tt", "tt", 1.80, 27), ("ss", "hh", 1.65, -40), ("ss", "hh", 1.65, 85)]),
    ]:
        for proc, rc, vdd, temp in c_list:
            cname = f"{proc}_v{int(round(vdd*1000))}_t{temp}"
            rdir = pdir / f"codes2p5_{variant}_{cname}"
            c16_jobs.append(dict(
                deck=build_pi_2p5_codes_deck(proc, vdd, temp, pi_par),
                run_dir=rdir, check=rdir / f"c{codes_16[-1]:02d}.raw", t_end=t_stop_c, timeout_s=1200,
            ))
            c16_meta.append((variant, cname, vdd, rdir))
    run_resumable(c16_jobs, workers)

    def rel_phase(t, y, ref, period, ly=0.0, lr=0.0):
        sel = t >= 2.8e-9
        ey, py = crossings(t[sel], y[sel], ly)
        er, pr = crossings(t[sel], ref[sel], lr)
        ey, er = ey[py > 0], er[pr > 0]
        if len(ey) == 0 or len(er) == 0:
            return float("nan")
        d = np.array([x - er[np.searchsorted(er, x) - 1] for x in ey if np.searchsorted(er, x) > 0]) % period
        if len(d) == 0:
            return float("nan")
        ang = np.angle(np.mean(np.exp(2j * np.pi * d / period)))
        return float(ang / (2.0 * np.pi) * period % period)

    c16_rows = {}
    print(f"\n  [CMOS PI + /2 @ 2.5 GHz (16-code sweep across 360 deg)]")
    print(f"  {'Variant:Corner':<28} | {'Mono':>4} | {'INL(UI/ps)':>13} | {'QuadErr(ps)':>11} | {'8phErr(ps)':>10} | {'MinSw(V)':>8} {'P(mW)':>6}")
    names8 = ["v(ckd0)", "v(cke0)", "v(ckd1)", "v(cke1)", "v(ckd2)", "v(cke2)", "v(ckd3)", "v(cke3)"]
    ideal8_ps = np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0])
    for variant, cname, vdd, rdir in c16_meta:
        vmid = 0.5 * vdd
        ph_d, q_errs, err8_max, min_sw, pwrs = [], [], [], [], []
        valid = True
        for code in codes_16:
            raw = rdir / f"c{code:02d}.raw"
            if not raw.exists():
                valid = False
                break
            w = spice.Waves(raw)
            dp_diff = w["v(dp)"] - w["v(dn)"]
            ep_diff = w["v(ep)"] - w["v(en)"]
            ph_d.append(rel_phase(w.t, dp_diff, w["v(c0)"], per_2p5, 0.0, vmid))
            de = rel_phase(w.t, ep_diff, dp_diff, per_2p5, 0.0, 0.0) * 1e12
            q_errs.append((de - 100.0 + 200.0) % 400.0 - 200.0)
            sel = w.t >= 2.8e-9
            pwrs.append(float(time_average(w["pwr"][sel], w.t[sel]) * 1e3))
            ref = w["v(ckd0)"]
            meas8 = [0.0] + [rel_phase(w.t, w[nm], ref, per_1p25, vmid, vmid) * 1e12 for nm in names8[1:]]
            e8 = (np.array(meas8) - ideal8_ps + 400.0) % 800.0 - 400.0
            err8_max.append(float(np.nanmax(np.abs(e8))))
            min_sw.append(min(float(np.ptp(w[nm][sel])) for nm in names8))
        key = f"{variant}:{cname}"
        if not valid or any(np.isnan(ph_d)):
            c16_rows[key] = dict(ok=False, note="failed_or_nan")
            print(f"  {key:<28} | FAIL (missing or non-oscillating)")
            continue
        ph_ui = np.unwrap(np.array(ph_d) / per_2p5 * 2.0 * np.pi) / (2.0 * np.pi) * per_2p5 / ui_5g
        step = np.diff(ph_ui)
        direction = float(np.sign(np.median(step)))
        step = step * direction
        fit = ph_ui[0] + direction * np.mean(step) * np.arange(len(codes_16))
        inl = (ph_ui - fit) * direction
        mono = bool(np.all(step > 0))
        inl_ui = float(np.max(np.abs(inl)))
        inl_ps = inl_ui * 200.0
        q_max = float(np.nanmax(np.abs(q_errs)))
        e8_max = float(np.nanmax(err8_max))
        msw = float(min(min_sw))
        pmw = float(np.mean(pwrs))
        ok = bool(mono and inl_ui <= 0.025 and e8_max <= 15.0 and msw > 0.85 * vdd)
        c16_rows[key] = dict(
            monotonic=mono, inl_ui=round(inl_ui, 4), inl_ps=round(inl_ps, 2),
            quad_err_ps=round(q_max, 2), max_8ph_err_ps=round(e8_max, 2),
            min_swing_v=round(msw, 3), power_mw=round(pmw, 2), ok=ok,
        )
        print(
            f"  {key:<28} | {'yes' if mono else 'NO ':>4} | {inl_ui:.4f} ({inl_ps:4.2f}) | "
            f"{q_max:11.2f} | {e8_max:10.2f} | {msw:8.3f} {pmw:6.2f} {'' if ok else 'FAIL'}",
            flush=True,
        )

    summary = dict(slicer_1p25g=sl_rows, pi_fmax=fmax_rows, pi_2p5g_codes=c16_rows)
    (rroot / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


# =============================================================================
# STAGE 6: Generate Crisp 4-Panel Figure -> docs/figures/system/serdes_5g_feasibility_20261123.png
# =============================================================================
def stage_plot(out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    print("\n=== [Stage PLOT] Generating 4-panel figure ===", flush=True)
    FIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    cp_sum = json.loads((out / "cp_v4p1/summary.json").read_text())
    tx_sum = json.loads((out / "tx_5g/summary.json").read_text())
    ctle_sum = json.loads((out / "rx_ctle_5g/summary.json").read_text())
    rx_sum = json.loads((out / "rx_clk_5g/summary.json").read_text())

    plt.rcParams.update({
        "font.size": 9.5,
        "axes.titlesize": 10.5,
        "axes.titleweight": "bold",
        "axes.labelsize": 9.5,
        "legend.fontsize": 8.2,
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "axes.grid": True,
        "grid.alpha": 0.28,
        "grid.linestyle": "--",
    })

    fig, axes = plt.subplots(2, 2, figsize=(13.6, 9.6), dpi=180)
    fig.patch.set_facecolor("white")

    # -------------------------------------------------------------------------
    # Panel (a): CP v4 vs v4.1 250 MHz Switching Glitch (TT & SF 1.65V 85C)
    # -------------------------------------------------------------------------
    ax = axes[0, 0]
    plot_cp = [
        ("v4",   "sf_hh_v1650_t85", "#d62728", "--", 1.8, "CP v4 (SF 1.65V 85°C)"),
        ("v4",   "tt_tt_v1800_t27", "#ff7f0e", "--", 1.5, "CP v4 (TT 1.80V 27°C)"),
        ("v4p1", "sf_hh_v1650_t85", "#1f77b4", "-",  2.2, "CP v4.1 fix (SF 1.65V 85°C)"),
        ("v4p1", "tt_tt_v1800_t27", "#2ca02c", "-",  2.0, "CP v4.1 fix (TT 1.80V 27°C)"),
    ]
    t_ref0 = 49.0e-9  # Start of a clean locked reference pulse (1 + 12*4 = 49 ns)
    for ver, cname, col, ls, lw, lbl in plot_cp:
        w = spice.Waves(out / f"cp_v4p1/rip_{ver}_{cname}_p2/ripple.raw")
        m = (w.t >= t_ref0 - 0.15e-9) & (w.t <= t_ref0 + 1.35e-9)
        tt_ns = (w.t[m] - t_ref0) * 1e9
        vc = w["v(ctrl)"][m]
        vc_rel = (vc - vc[0]) * 1e3
        rip_val = cp_sum["ripple"][cname][f"{ver}_p2"]["ripple_pp_mv"]
        dpw_val = cp_sum["ripple"][cname][f"{ver}_p1"]["dpw_ps"]
        ax.plot(tt_ns, vc_rel, color=col, linestyle=ls, linewidth=lw,
                label=f"{lbl}: {rip_val:.1f} mVpp (ΔPW {dpw_val:+.1f} ps)")
    ax.axhline(0, color="#666666", lw=0.8, alpha=0.6)
    ax.axvspan(0.0, 0.45, color="#eef4ff", alpha=0.5, zorder=0)
    ax.text(0.225, 0.94, "450 ps UP/DN\nPulse Window", transform=ax.get_xaxis_transform(),
            ha="center", va="top", fontsize=7.8, color="#335588")
    ax.set_title("(a) CP v4 vs v4.1: 250 MHz V_ctrl Switching Glitch Fix")
    ax.set_xlabel("Time Relative to Reference Edge (ns)")
    ax.set_ylabel("ΔV_ctrl (mV)")
    ax.set_xlim(-0.15, 1.35)
    ax.legend(loc="lower right", framealpha=0.92)

    # -------------------------------------------------------------------------
    # Panel (b): TX 5 Gb/s Pad Eye Diagrams — 400 mVpp N-over-N vs 800 mVpp P-over-N (TT & SS -40C)
    # -------------------------------------------------------------------------
    ax = axes[0, 1]
    ui_5g = 200e-12
    t0_tx = 4.0e-9
    eye_specs = [
        ("tx800_flat_5g_tt_v1800_t27_rlc16_f2",       "#1f77b4", 0.35, "800 mVpp P-over-N (TT)"),
        ("tx800_flat_5g_ss_hh_v1650_t-40_rlc16_f2",   "#9467bd", 0.30, "800 mVpp P-over-N (SS 1.65V −40°C)"),
        ("tx400_5g_tt_v1800_t27_rlc16_f0",            "#2ca02c", 0.40, "400 mVpp N-over-N (TT)"),
        ("tx400_5g_ss_hh_v1650_t-40_rlc16_f0",        "#d62728", 0.40, "400 mVpp N-over-N (SS 1.65V −40°C)"),
    ]
    tx_by_tag = {r["tag"]: r for r in tx_sum["transient"]}
    for tag, col, alph, lbl in eye_specs:
        raw = out / "tx_5g" / tag / "waveforms.raw"
        if not raw.exists():
            continue
        w = spice.Waves(raw)
        # Align zero-crossings to 0.0 / 1.0 / 2.0 UI so eye openings center cleanly at 0.5 & 1.5 UI!
        m_al = (w.t >= t0_tx + 64 * ui_5g) & (w.t <= t0_tx + 128 * ui_5g)
        zc, _ = crossings(w.t[m_al], w["pad"][m_al], 0.0)
        if len(zc):
            ph = ((zc - t0_tx) % ui_5g) / ui_5g
            ang = np.angle(np.mean(np.exp(2j * np.pi * ph)))
            t_off = (ang / (2.0 * np.pi) % 1.0) * ui_5g
        else:
            t_off = 0.0
        t_seg = np.linspace(0, 2 * ui_5g, 180)
        first = True
        for bi in range(64, 128, 2):
            ts = t0_tx + bi * ui_5g + t_off
            if ts + 2 * ui_5g > w.t[-1]:
                break
            yy = np.interp(ts + t_seg, w.t, w["pad"]) * 1e3
            ax.plot(t_seg / ui_5g, yy, color=col, alpha=alph, lw=0.85,
                    label=(f"{lbl}: {tx_by_tag[tag]['pad_margin_mv']:.0f} mV / {tx_by_tag[tag]['pad_spread_ui']:.3f} UI"
                           if first else None))
            first = False
    ax.axhline(+75, color="#888888", ls=":", lw=1.0)
    ax.axhline(-75, color="#888888", ls=":", lw=1.0)
    ax.text(1.97, 82, "±75 mV spec", ha="right", va="bottom", fontsize=7.6, color="#555555")
    ax.set_title("(b) TX SST @ 5 Gb/s (200 ps UI): 400 mVpp vs 800 mVpp Pad Eyes")
    ax.set_xlabel("Time (UI, 1 UI = 200 ps, crossing-aligned)")
    ax.set_ylabel("Differential Pad Voltage (mV)")
    ax.set_xlim(0.0, 2.0)
    ax.set_ylim(-640, 620)
    ax.legend(loc="lower center", fontsize=7.4, framealpha=0.94, ncol=1)

    # -------------------------------------------------------------------------
    # Panel (c): RX CTLE AC Response (80 fF) + 5 Gb/s C2_loss6 Eye Height Inset
    # -------------------------------------------------------------------------
    ax = axes[1, 0]
    ac_plot_specs = [
        ("tt_v1800_t27_c80",      "g0", "#7f7f7f", "--", 1.6, "R-only 600Ω (TT)"),
        ("tt_v1800_t27_c80",      "g1", "#1f77b4", "-",  2.0, "Shunt-Peak 600Ω (TT)"),
        ("tt_v1800_t27_c80",      "g2", "#2ca02c", "-",  2.0, "Shunt-Peak 480Ω 5G (TT)"),
        ("ss_hh_v1650_t85_c80",   "g0", "#d62728", "--", 1.6, "R-only 600Ω (SS 85°C)"),
        ("ss_hh_v1650_t85_c80",   "g1", "#ff7f0e", "-",  2.0, "Shunt-Peak 600Ω (SS 85°C)"),
        ("ss_hh_v1650_t85_c80",   "g2", "#9467bd", "-",  1.9, "Shunt-Peak 480Ω 5G (SS 85°C)"),
    ]
    for cname, gk, col, ls, lw, lbl in ac_plot_specs:
        d = read_complex_raw(out / f"rx_ctle_5g/ac_{cname}/ctle_ac.raw")
        f_ghz = np.real(d["frequency"]) / 1e9
        db = 20 * np.log10(np.maximum(np.abs(d[gk]), 1e-12))
        vn = {"g0": "r_only", "g1": "shunt_600", "g2": "shunt_480_5g"}[gk]
        bw = ctle_sum["ac"][cname][vn]["bw3_ghz"]
        ax.semilogx(f_ghz, db, color=col, linestyle=ls, linewidth=lw, label=f"{lbl} (BW {bw:.1f}G)")
    ax.axvline(2.5, color="#333333", ls=":", lw=1.2)
    ax.text(2.75, 5.7, "5 Gb/s Nyquist\n(2.5 GHz)", fontsize=8.0, color="#333333", va="top")
    ax.set_title("(c) RX CTLE AC Peaking & BW (80 fF): R-Only vs SKY130 met4+met5 Shunt-Peak")
    ax.set_xlabel("Frequency (GHz)")
    ax.set_ylabel("Differential Gain (dB)")
    ax.set_xlim(0.05, 20.0)
    ax.set_ylim(-7.5, 7.2)
    ax.legend(loc="lower left", fontsize=7.1, framealpha=0.94)

    # Clean inset bar showing 5 Gb/s C2_loss6 CTLE Eye Height (mV) at TT & SS 85°C
    ins = ax.inset_axes([0.62, 0.13, 0.35, 0.35])
    ins.set_facecolor("white")
    x_pos = np.arange(2)
    w_bar = 0.25
    tr5 = ctle_sum["tran_5g"]
    c_keys = ["tt_v1800_t27", "ss_hh_v1650_t85"]
    eh_r = [tr5[k]["out_r"]["eye_h_mv"] for k in c_keys]
    eh_s6 = [tr5[k]["out_s600"]["eye_h_mv"] for k in c_keys]
    eh_s4 = [tr5[k]["out_s480"]["eye_h_mv"] for k in c_keys]
    ins.bar(x_pos - w_bar, eh_r, w_bar, color="#888888", label="R-only")
    ins.bar(x_pos,         eh_s6, w_bar, color="#1f77b4", label="L-600Ω")
    ins.bar(x_pos + w_bar, eh_s4, w_bar, color="#2ca02c", label="L-480Ω")
    ins.set_xticks(x_pos)
    ins.set_xticklabels(["TT", "SS 85°C"], fontsize=7.5)
    ins.set_ylabel("EyeH (mV)", fontsize=7.3)
    ins.set_ylim(0, 235)
    ins.set_title("5G C2 Eye Height (400mV TX)", fontsize=7.6, fontweight="bold")
    ins.tick_params(labelsize=7.2)
    ins.legend(fontsize=6.4, loc="upper center", ncol=3, handlelength=0.8, columnspacing=0.5, framealpha=0.92)
    ins.grid(True, axis="y", alpha=0.3)

    # -------------------------------------------------------------------------
    # Panel (d): RX Clocking & Slicer 5 Gb/s Margin Summary (PI f_max + Slicer 1.25 GHz delay)
    # -------------------------------------------------------------------------
    ax = axes[1, 1]
    pi_f = rx_sum["pi_fmax"]
    f_styles = [
        ("baseline:tt_v1800_t27",    "#2ca02c", "-o",  "PI+÷2 Baseline (TT 1.8V 27°C)"),
        ("baseline:ss_v1650_t-40",   "#ff7f0e", "-s",  "PI+÷2 Baseline (SS 1.65V −40°C)"),
        ("baseline:ss_v1650_t85",    "#d62728", "--^", "PI+÷2 Baseline (SS 1.65V 85°C)"),
        ("tuned5g:ss_v1650_t85",     "#1f77b4", "-D",  "PI+÷2 5G-Tuned (SS 1.65V 85°C)"),
    ]
    for key, col, fmt, lbl in f_styles:
        if key not in pi_f:
            continue
        pts = pi_f[key]
        xs = [p["fin_ghz"] for p in pts]
        vdd_k = 1.80 if "1800" in key else (1.95 if "1950" in key else 1.65)
        ys = [(p["ckd_pp_v"] / vdd_k * 100.0) if p["div_ok"] else 0.0 for p in pts]
        ax.plot(xs, ys, fmt, color=col, lw=2.0, ms=5.5, label=lbl)
    ax.axvline(2.5, color="#333333", ls=":", lw=1.2)
    ax.text(2.47, 74, "5 Gb/s Target\n(2.5 GHz PI)", ha="right", va="center", fontsize=8.0, color="#333333",
            bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="#cccccc", alpha=0.9))
    ax.set_title("(d) RX 5 Gb/s Clocking (PI+÷2 f_max) & Slicer (1.25 GHz) Margin")
    ax.set_xlabel("PI Input Clock Frequency (GHz)")
    ax.set_ylabel("Locked ÷2 Output Swing (% VDD; 0 = Unlock)")
    ax.set_xlim(1.95, 3.05)
    ax.set_ylim(-8, 120)
    ax.legend(loc="lower left", fontsize=7.3, framealpha=0.94)

    # Inset showing Double-Tail Slicer clk->q delay @ 1.25 GHz vs 400 ps half-cycle budget
    ins2 = ax.inset_axes([0.58, 0.25, 0.39, 0.42])
    ins2.set_facecolor("white")
    sl = rx_sum["slicer_1p25g"]
    sl_keys = ["ff_v1950_t-40", "tt_v1800_t27", "ss_v1650_t85", "ss_v1650_t-40"]
    sl_lbls = ["FF -40°", "TT 27°", "SS 85°", "SS -40°"]
    y_pos = np.arange(len(sl_keys))
    td10s = [sl[k]["td_10mv_ps"] for k in sl_keys]
    tdhs = [sl[k]["td_hyst_ps"] for k in sl_keys]
    ins2.barh(y_pos - 0.17, td10s, 0.32, color="#1f77b4", label="±10 mV")
    ins2.barh(y_pos + 0.17, tdhs,  0.32, color="#ff7f0e", label="Hyst 5mV")
    ins2.axvline(400, color="#d62728", ls="--", lw=1.2)
    ins2.text(392, 0.05, "400 ps\nhalf-cyc", ha="right", va="bottom", fontsize=6.6, color="#d62728")
    ins2.set_yticks(y_pos)
    ins2.set_yticklabels(sl_lbls, fontsize=6.9)
    ins2.set_xlabel("Slicer clk→q (ps)", fontsize=7.2)
    ins2.set_title("DT Slicer @ 1.25 GHz (13/13 PASS)", fontsize=7.4, fontweight="bold")
    ins2.set_xlim(0, 435)
    ins2.tick_params(labelsize=6.9)
    ins2.legend(fontsize=6.3, loc="lower right", framealpha=0.92)
    ins2.grid(True, axis="x", alpha=0.3)

    fig.suptitle("SKY130A 1.8 V SerDes — 4 Gb/s Micro-Fix Polish & 5 Gb/s (200 ps UI) Feasibility Probe",
                 fontsize=12.5, fontweight="bold", y=0.985)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(FIG_PATH, dpi=180)
    plt.close(fig)
    print(f"  Saved 4-panel figure: {FIG_PATH.relative_to(REPO)}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stage",
        choices=("cp", "ldo", "tx5g", "ctle", "rxclk", "plot", "all"),
        default="all",
    )
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    workers = min(max(1, args.workers), 2)  # STRICTLY <= 2 concurrent ngspice!
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    print(f"Output dir: {OUT_ROOT} (workers={workers})", flush=True)

    if args.stage in ("cp", "all"):
        stage_cp(OUT_ROOT, workers)
    if args.stage in ("ldo", "all"):
        stage_ldo(OUT_ROOT, workers)
    if args.stage in ("tx5g", "all"):
        stage_tx5g(OUT_ROOT, workers)
    if args.stage in ("ctle", "all"):
        stage_ctle(OUT_ROOT, workers)
    if args.stage in ("rxclk", "all"):
        stage_rxclk(OUT_ROOT, workers)
    if args.stage in ("plot", "all"):
        stage_plot(OUT_ROOT)


if __name__ == "__main__":
    main()
