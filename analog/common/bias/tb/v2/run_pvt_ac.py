"""BIAS v2 comprehensive verification: 135-corner PVT, DC line regulation, 5-bit r_ref trim,
16-code real-transistor pbuf decode, and dual-loop Tian-Middlebrook AC stability + PSRR.

Usage:
    uv run python analog/common/bias/tb/v2/run_pvt_ac.py [--workers 2] [--fast]
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import feedback, spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/common/bias/v2"
BIAS_V2 = ROOT / "analog/common/bias/spice/bias_v2.spice"
PRIMS = ROOT / "analog/common/devices/spice/sky130_primitives.spice"
PLVT = ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice"


def section(proc: str, rc: str) -> str:
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def bits_sources(prefix: str, val: int, nbits: int) -> str:
    lines = []
    for k in range(nbits):
        bit = (val >> k) & 1
        lines.append(f"E{prefix}{k} {prefix}{k} 0 vdd 0 {bit}")
    return "\n".join(lines)


def build_pvt_deck(proc: str, rc: str, trim: int = 15, pcode: int = 7) -> str:
    lib = spice.corner_values(Condition(proc, 1.8, 27))["MODEL_LIBRARY"]
    sec = section(proc, rc)
    lines = [
        f"* BIAS v2 135-corner PVT OP + Line Reg ({sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2}"',
        "Vdd vdd 0 1.8",
        bits_sources("g", trim, 5),
        bits_sources("c", pcode, 4),
        "Een en_pbuf 0 vdd 0 1",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2",
        "Vi0 i0 0 0.7",
        "Xrl i1 0 0 sky130_fd_pr__res_high_po w=1 l=18",
        "Cvcm vcm 0 5p",
        "Cpref pref 0 42p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2",
        "Vmctle ictle vctle 0",
        "Xdctle vctle 0 serdes_bias_ctle_v2",
        "Vmcp icp vbn 0",
        "Xdcp vbn vbp vdd 0 serdes_bias_cp_v2",
        # CML half-circuit swing proxy (20/0.5 nf=4 tail + 500 Ohm high_po load, identical to v1 dist_pvt)
        "Vtop cml_top 0 1.0",
        "Xrl_cml cml_top cml_dr 0 sky130_fd_pr__res_high_po w=3 l=3.54",
        "Xtail_cml cml_dr vcml 0 0 serdes_nfet w=20 l=0.5 nf=4",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(pref)=1.14 v(xtop.xref.s)=1.234 v(xtop.xref.vg)=0.9 v(xtop.vgi)=0.9 v(xtop.xref.ta)=1.05 v(xtop.xref.tb)=1.05",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    vecs = {
        "vbg": "v(vbg)",
        "vcm": "v(vcm)",
        "pref": "v(pref)",
        "iref": "i(Vi0)",
        "ir": "v(i1)",
        "icml": "i(Vmcml)",
        "ictle": "i(Vmctle)",
        "icp": "i(Vmcp)",
        "vcml": "v(vcml)",
        "vctle": "v(vctle)",
        "vbn": "v(vbn)",
        "vbp": "v(vbp)",
        "cml_swing": "v(cml_top)-v(cml_dr)",
        "err_core": "v(xtop.xref.ta)-v(xtop.xref.tb)",
        "err_vi": "v(xtop.xref.s)-v(vbg)",
        "vg": "v(xtop.xref.vg)",
        "vgi": "v(xtop.vgi)",
        "m3_m": "(v(vdd)-v(vbg))-@m.xtop.xref.xm3.xmos.msky130_fd_pr__pfet_01v8_lvt[vdsat]",
        "mv_m": "(v(vdd)-v(xtop.xref.s))-@m.xtop.xref.xmv.xmos.msky130_fd_pr__pfet_01v8_lvt[vdsat]",
        "fa_m": "(v(vdd)-v(xtop.xref.xamp.fa))-@m.xtop.xref.xamp.xfa.xmos.msky130_fd_pr__pfet_01v8_lvt[vdsat]",
        "pcb_m": "(v(xtop.xref.xamp.fa)-v(xtop.xref.vg))-@m.xtop.xref.xamp.xpcb.xmos.msky130_fd_pr__pfet_01v8_lvt[vdsat]",
        "ncb_m": "(v(xtop.xref.vg)-v(xtop.xref.xamp.nb_n))-@m.xtop.xref.xamp.xncb.xmos.msky130_fd_pr__nfet_01v8[vdsat]",
        "nb_m": "v(xtop.xref.xamp.nb_n)-@m.xtop.xref.xamp.xnb.xmos.msky130_fd_pr__nfet_01v8[vdsat]",
        "tail_m": "v(xtop.xref.xamp.tail)-@m.xtop.xref.xamp.xt.xmos.msky130_fd_pr__nfet_01v8[vdsat]",
        "idd": "-i(Vdd)",
    }
    for v in SUPPLY_V:
        for t in TEMP_C:
            tag = f"{proc}_{rc}_v{round(v*1000)}_t{t}"
            lines += [f"option temp={t}", f"alter Vdd dc={v}", "op"]
            lines += [f"let {k}={e}" for k, e in vecs.items()]
            lines += [f"wrdata {tag}.tsv " + " ".join(vecs), "destroy all"]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def make_probe_spice() -> str:
    """Create test-only probed copy of serdes_bias_ref_v2 and serdes_bias_top_v2 exposing loop breaks."""
    txt = BIAS_V2.read_text()
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
    top_p = """
.subckt serdes_bias_top_v2_probe vbg vcm pref icml ictle icp i_ldo0 i_ldo1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd vss cr ci vr vi
Xref vbg iv_in iv_b ip_in ip_b vgi g4 g3 g2 g1 g0 vdd vss cr ci vr vi serdes_bias_ref_v2_probe
Xvbuf iv_in iv_b vcm vdd vss serdes_ref_vbuf_v2
Xpbuf ip_in ip_b pref en_pbuf c0 c1 c2 c3 vdd vss serdes_ref_pbuf_v2
Xpc_cml  icml   vgi vdd serdes_bias_pcopy_v2 n=85
Xpc_ctle ictle  vgi vdd serdes_bias_pcopy_v2 n=20
Xpc_cp   icp    vgi vdd serdes_bias_pcopy_v2 n=20
Xpc_ldo0 i_ldo0 vgi vdd serdes_bias_pcopy_v2 n=4
Xpc_ldo1 i_ldo1 vgi vdd serdes_bias_pcopy_v2 n=4
.ends serdes_bias_top_v2_probe
"""
    return ref_p + "\n" + top_p


def build_ac_psrr_deck(sec: str, pts: list[tuple[float, int]]) -> str:
    lib = spice.corner_values(Condition("tt", 1.8, 27))["MODEL_LIBRARY"]
    lines = [
        f"* BIAS v2 Dual-Loop Tian-Middlebrook AC Stability + PSRR ({sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2}"',
        make_probe_spice(),
        "Vdd vdd 0 1.8 ac 0",
        bits_sources("g", 15, 5),
        bits_sources("c", 7, 4),
        "Een en_pbuf 0 vdd 0 0",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 cr ci vr vi serdes_bias_top_v2_probe",
        "Vcore ci cr 0 ac 0",
        "Icore 0 ci 0 ac 0",
        "Vvi vi vr 0 ac 0",
        "Ivi 0 vi 0 ac 0",
        "Vi0 i0 0 0.7",
        "Vi1 i1 0 0.7",
        "Cvcm vcm 0 5p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2",
        "Vmctle ictle vctle 0",
        "Xdctle vctle 0 serdes_bias_ctle_v2",
        "Vmcp icp vbn 0",
        "Xdcp vbn vbp vdd 0 serdes_bias_cp_v2",
        "Vtop cml_top 0 1.0",
        "Xrl_cml cml_top cml_dr 0 sky130_fd_pr__res_high_po w=3 l=3.54",
        "Xtail_cml cml_dr vcml 0 0 serdes_nfet w=20 l=0.5 nf=4",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(vr)=1.234 v(vi)=1.234 v(cr)=0.9 v(ci)=0.9 v(xtop.vgi)=0.9 v(xtop.xref.ta)=1.05 v(xtop.xref.tb)=1.05",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    for v, t in pts:
        tag = f"v{round(v*1000)}_t{t}"
        lines += [f"option temp={t}", f"alter Vdd dc={v}"]
        for name, ret, inp in [("core", "cr", "ci"), ("vi", "vr", "vi")]:
            vs, isrc = f"V{name}", f"I{name}"
            lines += [
                f"alter {vs} acmag=1",
                "ac dec 25 10 100meg",
                f"let tv=-v({ret})/v({inp})",
                "let r=real(tv)", "let q=imag(tv)",
                f"wrdata {tag}_{name}_v.tsv r q",
                "destroy all",
                f"alter {vs} acmag=0",
                f"alter {isrc} acmag=1",
                "ac dec 25 10 100meg",
                f"let ti=i({vs})/(1-i({vs}))",
                "let r=real(ti)", "let q=imag(ti)",
                f"wrdata {tag}_{name}_i.tsv r q",
                "destroy all",
                f"alter {isrc} acmag=0",
            ]
        # PSRR sweep
        lines += [
            "alter Vdd acmag=1",
            "ac dec 20 100 1g",
            "let mvbg=mag(v(vbg))",
            "let mvcml=mag(v(vcml))",
            "let mvcm=mag(v(vcm))",
            "let msw=mag(v(cml_dr))",
            f"wrdata {tag}_psrr.tsv mvbg mvcml mvcm msw",
            "destroy all",
            "alter Vdd acmag=0",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def build_trim_pbuf_deck() -> str:
    """Verify 5-bit r_ref trim (0..31) and 4-bit real CMOS pbuf decode (0..15) at TT 1.8V 27C."""
    lib = spice.corner_values(Condition("tt", 1.8, 27))["MODEL_LIBRARY"]
    lines = [
        "* BIAS v2 Trim (0..31) & PBUF 16-code real CMOS decoder sweep (TT 1.8V 27C)",
        f'.lib "{lib}" tt',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2}"',
        "Vdd vdd 0 1.8",
        "Vg4 g4 0 0", "Vg3 g3 0 1.8", "Vg2 g2 0 1.8", "Vg1 g1 0 1.8", "Vg0 g0 0 1.8",
        "Vc3 c3 0 0", "Vc2 c2 0 1.8", "Vc1 c1 0 1.8", "Vc0 c0 0 1.8",
        "Ven en_pbuf 0 1.8",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2",
        "Vi0 i0 0 0.7",
        "Vi1 i1 0 0.7",
        "Xdcml icml 0 serdes_bias_cml_v2",
        "Xdctle ictle 0 serdes_bias_ctle_v2",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(pref)=1.14 v(xtop.xref.s)=1.234 v(xtop.xref.vg)=0.9 v(xtop.vgi)=0.9 v(xtop.xref.ta)=1.05 v(xtop.xref.tb)=1.05",
        ".temp 27",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    for code in range(32):
        for k in range(5):
            lines.append(f"alter Vg{k} dc={1.8 if (code >> k) & 1 else 0.0}")
        lines += [
            "op",
            "let iref=i(Vi0)*1e6", "let vcm=v(vcm)", "let vbg=v(vbg)",
            f"wrdata trim_{code:02d}.tsv iref vcm vbg",
            "destroy all",
        ]
    # Reset trim=15, sweep pbuf codes 0..15
    for k in range(5):
        lines.append(f"alter Vg{k} dc={1.8 if (15 >> k) & 1 else 0.0}")
    for code in range(16):
        for k in range(4):
            lines.append(f"alter Vc{k} dc={1.8 if (code >> k) & 1 else 0.0}")
        lines += [
            "op",
            "let pref=v(pref)", "let tap=v(xtop.xpbuf.tap)",
            f"wrdata pbuf_{code:02d}.tsv pref tap",
            "destroy all",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def read_tsv(path: Path) -> dict[str, float]:
    ls = path.read_text().strip().splitlines()
    return dict(zip(ls[0].split(), (float(x) for x in ls[1].split())))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--fast", action="store_true", help="Run 5 extreme MOSxRC corners instead of all 15")
    args = ap.parse_args()

    camp = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_pvt_ac"
    camp.mkdir(parents=True, exist_ok=True)

    # 1. PVT jobs
    pairs = [("tt", "tt"), ("ss", "hh"), ("ff", "ll"), ("fs", "ll"), ("sf", "hh")] if args.fast else [
        (p, rc) for p in PROCESS for rc in ("tt", "ll", "hh")
    ]
    pvt_jobs = [
        (build_pvt_deck(p, rc), camp / "pvt" / f"{p}_{rc}", dict(timeout_s=600, meta=dict(process=p, rcorner=rc)))
        for p, rc in pairs
    ]
    # 2. AC + PSRR jobs
    ac_profiles = [
        ("tt", [(1.80, 27), (1.65, -40), (1.95, 85)]),
        ("ss_hh", [(1.65, -40), (1.65, 85), (1.95, 85)]),
        ("ff_ll", [(1.65, -40), (1.65, 85), (1.95, 85)]),
        ("fs_ll", [(1.65, -40), (1.65, 85), (1.95, 85)]),
        ("sf_hh", [(1.65, -40), (1.65, 85), (1.95, 85)]),
    ]
    ac_jobs = [
        (build_ac_psrr_deck(sec, pts), camp / "ac" / sec, dict(timeout_s=600, meta=dict(section=sec)))
        for sec, pts in ac_profiles
    ]
    # 3. Trim + PBUF 16-code decode job
    trim_job = [(build_trim_pbuf_deck(), camp / "trim_pbuf", dict(timeout_s=600, meta=dict(kind="trim_pbuf")))]

    all_jobs = pvt_jobs + ac_jobs + trim_job
    print(f"Launching {len(all_jobs)} merged ngspice jobs (workers={args.workers}) -> {camp.relative_to(ROOT)}", flush=True)
    for ex in spice.run_many(all_jobs, workers=args.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)

    # Parse PVT
    pvt_rows = []
    for p, rc in pairs:
        for v in SUPPLY_V:
            for t in TEMP_C:
                f = camp / "pvt" / f"{p}_{rc}" / f"{p}_{rc}_v{round(v*1000)}_t{t}.tsv"
                if f.exists():
                    pvt_rows.append(dict(process=p, rcorner=rc, supply=v, temp=t, **read_tsv(f)))

    print(f"\n=== PVT SUMMARY ({len(pvt_rows)} conditions) ===")
    col = lambda k: np.array([r[k] for r in pvt_rows])
    metrics_spec = [
        ("vbg", 1, "V"), ("vcm", 1, "V"), ("pref", 1, "V"), ("iref", 1e6, "uA"),
        ("ir", 1e3, "mV"), ("icml", 1e6, "uA"), ("cml_swing", 1e3, "mV"),
        ("err_core", 1e3, "mV"), ("err_vi", 1e3, "mV"),
        ("m3_m", 1e3, "mV"), ("mv_m", 1e3, "mV"), ("fa_m", 1e3, "mV"),
        ("pcb_m", 1e3, "mV"), ("ncb_m", 1e3, "mV"), ("nb_m", 1e3, "mV"),
        ("tail_m", 1e3, "mV"), ("idd", 1e3, "mA"),
    ]
    summary = {"n_pvt": len(pvt_rows), "pvt_ranges": {}}
    for k, sc, u in metrics_spec:
        x = col(k) * sc
        lo, hi = float(x.min()), float(x.max())
        summary["pvt_ranges"][k] = dict(min=lo, max=hi, unit=u)
        print(f"  {k:10s}: {lo:9.4f} .. {hi:9.4f} {u}")

    vbg = col("vbg")
    ir = col("ir")
    vbg_spread_pct = float((vbg.max() - vbg.min()) / (2 * np.mean(vbg)) * 100)
    ir_spread_pct = float((ir.max() - ir.min()) / (2 * np.mean(ir)) * 100)
    print(f"  Vbg spread = +-{vbg_spread_pct:.2f}%   |   I*R spread = +-{ir_spread_pct:.2f}%")

    # DC Line regulation
    lrs = []
    for p, rc in pairs:
        for t in TEMP_C:
            r1 = [r for r in pvt_rows if r["process"] == p and r["rcorner"] == rc and r["temp"] == t and r["supply"] == 1.65][0]
            r2 = [r for r in pvt_rows if r["process"] == p and r["rcorner"] == rc and r["temp"] == t and r["supply"] == 1.95][0]
            lr_vbg = (r2["vbg"] - r1["vbg"]) / 0.30 * 1e3
            lr_i = (r2["iref"] - r1["iref"]) / r1["iref"] / 0.30 * 100
            lrs.append(dict(process=p, rcorner=rc, temp=t, lr_vbg_mv_v=lr_vbg, lr_iref_pct_v=lr_i))
    max_lr = max(lrs, key=lambda x: abs(x["lr_vbg_mv_v"]))
    tt27_lr = [x for x in lrs if x["process"] == "tt" and x["rcorner"] == "tt" and x["temp"] == 27][0]
    print(f"  DC Line Reg: TT 27C = {tt27_lr['lr_vbg_mv_v']:+.2f} mV/V ({20*np.log10(abs(tt27_lr['lr_vbg_mv_v'])/1e3):.1f} dB) | "
          f"WORST = {max_lr['lr_vbg_mv_v']:+.2f} mV/V ({20*np.log10(abs(max_lr['lr_vbg_mv_v'])/1e3):.1f} dB) at {max_lr['process']}_{max_lr['rcorner']} {max_lr['temp']}C")
    summary["vbg_spread_pct"] = vbg_spread_pct
    summary["ir_spread_pct"] = ir_spread_pct
    summary["dc_line_reg_tt27_mv_v"] = tt27_lr["lr_vbg_mv_v"]
    summary["dc_line_reg_worst"] = max_lr

    # Parse AC + PSRR
    print("\n=== DUAL-LOOP AC STABILITY (FULL DISTRIBUTION LOAD) ===")
    ac_rows = []
    psrr_rows = []
    for sec, pts in ac_profiles:
        for v, t in pts:
            tag = f"v{round(v*1000)}_t{t}"
            entry = dict(section=sec, supply=v, temp=t)
            for loop in ("core", "vi"):
                dv = np.loadtxt(camp / "ac" / sec / f"{tag}_{loop}_v.tsv", skiprows=1)
                di = np.loadtxt(camp / "ac" / sec / f"{tag}_{loop}_i.tsv", skiprows=1)
                T = feedback.middlebrook(dv[:, 1] + 1j * dv[:, 2], di[:, 1] + 1j * di[:, 2])
                dc_db = float(20 * np.log10(abs(T[0])))
                xs = feedback.unity_crossings(dv[:, 0], T)
                entry[loop] = dict(dc_db=dc_db, crossings=xs)
            ac_rows.append(entry)
            c0 = entry["core"]["crossings"][0]
            v0 = entry["vi"]["crossings"][0]
            print(f"  {sec:6s} {v:.2f}V {t:3d}C | CORE: DC={entry['core']['dc_db']:5.1f}dB UGB={c0['hz']/1e3:5.0f}kHz PM={c0['pm_deg']:5.1f}deg (n={len(entry['core']['crossings'])}) "
                  f"| V->I: DC={entry['vi']['dc_db']:5.1f}dB UGB={v0['hz']/1e3:5.0f}kHz PM={v0['pm_deg']:5.1f}deg (n={len(entry['vi']['crossings'])})")
            dp = np.loadtxt(camp / "ac" / sec / f"{tag}_psrr.tsv", skiprows=1)
            hz = dp[:, 0]
            p_rec = dict(section=sec, supply=v, temp=t)
            for f_hz, fname in [(1e3, "1k"), (1e5, "100k"), (1e6, "1M"), (1e7, "10M"), (1e8, "100M"), (1e9, "1G")]:
                p_rec[fname] = dict(
                    vbg_mv_v=float(np.interp(f_hz, hz, dp[:, 1]) * 1e3),
                    vcml_mv_v=float(np.interp(f_hz, hz, dp[:, 2]) * 1e3),
                    vcm_mv_v=float(np.interp(f_hz, hz, dp[:, 3]) * 1e3),
                )
            psrr_rows.append(p_rec)

    print("\n=== WORST-CASE AC PSRR (mV/V across tested corners) ===")
    for fname in ("1k", "100k", "1M", "10M", "100M", "1G"):
        vbg_w = max(r[fname]["vbg_mv_v"] for r in psrr_rows)
        vcml_w = max(r[fname]["vcml_mv_v"] for r in psrr_rows)
        vcm_w = max(r[fname]["vcm_mv_v"] for r in psrr_rows)
        print(f"  {fname:4s}Hz: vbg={vbg_w:7.2f} mV/V | vcml={vcml_w:7.2f} mV/V | vcm={vcm_w:7.2f} mV/V")

    # Parse Trim & PBUF 16-code decode
    trim_rows = [dict(code=c, **read_tsv(camp / "trim_pbuf" / f"trim_{c:02d}.tsv")) for c in range(32)]
    irefs = [r["iref"] for r in trim_rows]
    mono_trim = all(irefs[i + 1] > irefs[i] for i in range(31))
    nom_i = trim_rows[15]["iref"]
    lo_pct = (trim_rows[0]["iref"] / nom_i - 1) * 100
    hi_pct = (trim_rows[31]["iref"] / nom_i - 1) * 100
    print(f"\n=== 5-BIT R_REF TRIM (TT 1.8V 27C) ===")
    print(f"  Monotonic={mono_trim} | code 0={irefs[0]:.3f} uA ({lo_pct:+.2f}%) | code 15={nom_i:.3f} uA | code 31={irefs[31]:.3f} uA ({hi_pct:+.2f}%)")

    pbuf_rows = [dict(code=c, **read_tsv(camp / "trim_pbuf" / f"pbuf_{c:02d}.tsv")) for c in range(16)]
    prefs = [r["pref"] for r in pbuf_rows]
    mono_pbuf = all(prefs[i + 1] > prefs[i] for i in range(15))
    steps_mv = [(prefs[i + 1] - prefs[i]) * 1e3 for i in range(15)]
    print(f"\n=== 4-BIT REAL CMOS PBUF DECODE (TT 1.8V 27C) ===")
    print(f"  Monotonic={mono_pbuf} | code 0={prefs[0]:.4f} V .. code 15={prefs[15]:.4f} V | step={min(steps_mv):.2f}..{max(steps_mv):.2f} mV")

    summary.update(
        ac=ac_rows,
        psrr=psrr_rows,
        trim=dict(monotonic=mono_trim, code0_ua=irefs[0], code15_ua=nom_i, code31_ua=irefs[31], lo_pct=lo_pct, hi_pct=hi_pct),
        pbuf_decode=dict(monotonic=mono_pbuf, code0_v=prefs[0], code15_v=prefs[15], min_step_mv=min(steps_mv), max_step_mv=max(steps_mv)),
    )
    (camp / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (camp / "pvt_rows.json").write_text(json.dumps(pvt_rows, indent=1) + "\n")
    print(f"\nSaved full results -> {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
