"""BIAS v2 Post-Layout Verification (CPEX top macro + RCX local sinks & standalone vbuf/pbuf).

Verifies installed extracted netlists in `analog/common/bias/layout/variants/v2_pdk/`:
  1. 135-corner (or 45-corner --fast) PVT OP + DC line regulation of
     `serdes_bias_top_v2_pdk_pex.spice` loaded by extracted RCX local cells
     (`serdes_bias_cml_v2_pdk_rcx`, `serdes_bias_cp_v2_pdk_rcx`, `serdes_bias_ctle_v2_pdk_rcx`),
     with direct apples-to-apples comparison against schematic `bias_v2.spice` baseline.
  2. TT 5-bit `r_ref` trim sweep (all 32 codes 0..31) & 4-bit real-CMOS PBUF sweep (all 16 codes 0..15)
     on extracted `serdes_bias_top_v2_pdk_pex.spice`.
  3. Zero-start 1 us VDD ramp startup + +50 mV/10 ps supply step on TT + 4 extreme corners
     (`tt/tt 1.8V 27C`, `ss/hh 1.65V -40C`, `fs/ll 1.65V 85C`, `ff/ll 1.95V 85C`, `sf/hh 1.95V -40C`).
  4. 512 ns PLL loop-filter precharge transient (`en_pbuf: 0->1`) at `tt/tt 1.8V 27C` and `ss/hh 1.65V -40C`.
  5. Standalone RCX cell checks for `serdes_ref_vbuf_v2_pdk_rcx` and `serdes_ref_pbuf_v2_pdk_rcx`.

Usage:
    uv run python analog/common/bias/tb/v2/run_postlayout.py [--workers 3] [--fast]
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/common/bias/v2"
PDK_DIR = ROOT / "analog/common/bias/layout/variants/v2_pdk"
PRIMS = ROOT / "analog/common/devices/spice/sky130_primitives.spice"
PLVT = ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice"
CMOS = ROOT / "analog/common/devices/spice/cmos_logic.spice"
LF_SPICE = ROOT / "analog/pll/loop_filter/spice/passive_rc_precharge.spice"

TOP_PEX = PDK_DIR / "serdes_bias_top_v2_pdk_pex.spice"
CML_RCX = PDK_DIR / "serdes_bias_cml_v2_pdk_rcx.spice"
CP_RCX = PDK_DIR / "serdes_bias_cp_v2_pdk_rcx.spice"
CTLE_RCX = PDK_DIR / "serdes_bias_ctle_v2_pdk_rcx.spice"
VBUF_RCX = PDK_DIR / "serdes_ref_vbuf_v2_pdk_rcx.spice"
PBUF_RCX = PDK_DIR / "serdes_ref_pbuf_v2_pdk_rcx.spice"

SCH_BASELINE = ROOT / "results/analog/common/bias/v2/20261120T090254Z_pvt_ac/pvt_rows.json"


def section(proc: str, rc: str) -> str:
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def bits_sources(prefix: str, val: int, nbits: int) -> str:
    return "\n".join(f"E{prefix}{k} {prefix}{k} 0 vdd 0 {(val >> k) & 1}" for k in range(nbits))


def top_inst_line(en_node: str = "en_pbuf") -> str:
    # Exact port order from serdes_bias_top_v2_pdk_pex.spice:
    # vbg vcm pref icp i_ldo1 i_ldo0 ictle icml g4 g3 g2 g1 g0 c0 c1 c2 c3 en_pbuf vdd vss
    return (
        "Xtop vbg vcm pref icp i1 i0 ictle icml "
        f"g4 g3 g2 g1 g0 c0 c1 c2 c3 {en_node} vdd 0 serdes_bias_top_v2_pdk"
    )


def common_includes(sec: str) -> list[str]:
    lib = spice.corner_values(Condition("tt", 1.8, 27))["MODEL_LIBRARY"]
    return [
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{TOP_PEX}"',
        f'.include "{CML_RCX}"',
        f'.include "{CP_RCX}"',
        f'.include "{CTLE_RCX}"',
    ]


def build_pvt_deck(proc: str, rc: str, trim: int = 15, pcode: int = 7) -> str:
    sec = section(proc, rc)
    lines = [
        f"* BIAS v2 Post-Layout (CPEX+RCX) PVT OP ({sec})",
        *common_includes(sec),
        "Vdd vdd 0 1.8",
        bits_sources("g", trim, 5),
        bits_sources("c", pcode, 4),
        "Een en_pbuf 0 vdd 0 1",
        top_inst_line(),
        "Vi0 i0 0 0.7",
        "Xrl i1 0 0 sky130_fd_pr__res_high_po w=1 l=18",
        "Cvcm vcm 0 5p",
        "Cpref pref 0 42p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2_pdk",
        "Vmctle ictle vctle 0",
        "Xdctle vctle 0 serdes_bias_ctle_v2_pdk",
        "Vmcp icp vbn 0",
        "Xdcp vbn vbp vdd 0 serdes_bias_cp_v2_pdk",
        "Vtop cml_top 0 1.0",
        "Xrl_cml cml_top cml_dr 0 sky130_fd_pr__res_high_po w=3 l=3.54",
        "Xtail_cml cml_dr vcml 0 0 serdes_nfet w=20 l=0.5 nf=4",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(pref)=1.14",
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


def build_codes_deck() -> str:
    """TT 1.8V 27C: 32-code 5-bit r_ref trim + 16-code real-CMOS PBUF sweep + en_pbuf off/on."""
    lines = [
        "* BIAS v2 Post-Layout 5-bit Trim & 16-Code Real-CMOS PBUF Sweep (tt 1.8V 27C)",
        *common_includes("tt"),
        "Vdd vdd 0 1.8",
        "Vg0 g0 0 1.8",
        "Vg1 g1 0 1.8",
        "Vg2 g2 0 1.8",
        "Vg3 g3 0 1.8",
        "Vg4 g4 0 0",
        "Vc0 c0 0 1.8",
        "Vc1 c1 0 1.8",
        "Vc2 c2 0 1.8",
        "Vc3 c3 0 0",
        "Ven en_pbuf 0 1.8",
        top_inst_line(),
        "Vi0 i0 0 0.7",
        "Xrl i1 0 0 sky130_fd_pr__res_high_po w=1 l=18",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2_pdk",
        "Xdctle ictle 0 serdes_bias_ctle_v2_pdk",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2_pdk",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(pref)=1.14",
        ".temp 27",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    # 32 trim codes (pcode=7, en=1)
    for g in range(32):
        for k in range(5):
            lines.append(f"alter Vg{k} dc={1.8 if (g >> k) & 1 else 0.0}")
        lines += [
            "op",
            "let vbg=v(vbg)",
            "let iref=i(Vi0)",
            "let icml=i(Vmcml)",
            "let ir=v(i1)",
            f"wrdata trim_{g:02d}.tsv vbg iref icml ir",
            "destroy all",
        ]
    # restore trim=15, sweep 16 pbuf codes
    for k in range(5):
        lines.append(f"alter Vg{k} dc={1.8 if (15 >> k) & 1 else 0.0}")
    for c in range(16):
        for k in range(4):
            lines.append(f"alter Vc{k} dc={1.8 if (c >> k) & 1 else 0.0}")
        lines += [
            "op",
            "let pref=v(pref)",
            "let vbg=v(vbg)",
            "let idd=-i(Vdd)",
            f"wrdata pbuf_{c:02d}.tsv pref vbg idd",
            "destroy all",
        ]
    # en_pbuf = 0 check
    lines += [
        "alter Ven dc=0",
        "op",
        "let idd_off=-i(Vdd)",
        "let vbg_off=v(vbg)",
        "let iref_off=i(Vi0)",
        "wrdata en_off.tsv idd_off vbg_off iref_off",
        "destroy all",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def build_startup_deck(proc: str, rc: str, vdd: float, temp: int, tramp: float = 1e-6, tsettle: float = 15e-6) -> tuple[str, float]:
    sec = section(proc, rc)
    tstep = tramp + tsettle
    stop = tstep + 4e-6
    lines = [
        f"* BIAS v2 Post-Layout Zero-Start 1us Ramp + +50mV/10ps Step ({sec} {vdd}V {temp}C)",
        *common_includes(sec),
        f"Vsup sup 0 {vdd}",
        f"Bvdd vdd 0 V=v(sup)*min(max(time/{tramp:.3e},0),1)+0.05*min(max((time-{tstep:.3e})/10p,0),1)",
        bits_sources("g", 15, 5),
        bits_sources("c", 7, 4),
        "Een en_pbuf 0 vdd 0 0",
        top_inst_line(),
        "Vi0 i0 0 0.7",
        "Xrl i1 0 0 sky130_fd_pr__res_high_po w=1 l=18",
        "Cvcm vcm 0 5p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2_pdk",
        "Xdctle ictle 0 serdes_bias_ctle_v2_pdk",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2_pdk",
        # TRUE ZERO-START: NO .nodeset!
        f".temp {temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        f"tran 5n {stop:.4e} 0 25n",
        "let iref=i(Vi0)",
        "let icml=i(Vmcml)",
        "write startup.raw v(vbg) v(vcm) iref v(i1) icml v(vcml) v(vdd)",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines), tstep


def build_pbuf_precharge_deck(sec: str, vdd: float, temp: int, code: int) -> str:
    lines = [
        f"* BIAS v2 Post-Layout PBUF 512ns LF Precharge ({sec} {vdd}V {temp}C code={code})",
        *common_includes(sec),
        f'.include "{CMOS}"',
        f'.include "{LF_SPICE}"',
        f"Vdd vdd 0 {vdd}",
        bits_sources("g", 15, 5),
        bits_sources("c", code, 4),
        "Ben en_pbuf 0 V=v(vdd)*min(max((time-20n)/100p,0),1)",
        top_inst_line(),
        "Vi0 i0 0 0.7",
        "Vi1 i1 0 0.7",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2_pdk",
        "Xdctle ictle 0 serdes_bias_ctle_v2_pdk",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2_pdk",
        "Xlf cpi ctrl z pref en_pbuf vdd 0 pll_loop_filter_precharge",
        ".ic v(ctrl)=0 v(z)=0",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05",
        f".temp {temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 1n 600n 0 2n",
        "let icml=i(Vmcml)",
        "write precharge.raw v(z) v(pref) v(vbg) icml",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def build_standalone_rcx_deck() -> str:
    """Verify standalone serdes_ref_vbuf_v2_pdk_rcx & serdes_ref_pbuf_v2_pdk_rcx at TT 1.8V 27C."""
    lib = spice.corner_values(Condition("tt", 1.8, 27))["MODEL_LIBRARY"]
    lines = [
        "* BIAS v2 Standalone VBUF & PBUF RCX Check (tt 1.8V 27C)",
        f'.lib "{lib}" tt',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{VBUF_RCX}"',
        f'.include "{PBUF_RCX}"',
        "Vdd vdd 0 1.8",
        "Ivin vdd vin_in 10u",
        "Ivib vdd vin_ib 10u",
        "Xvbuf vin_in vin_ib vcm_rcx vdd 0 serdes_ref_vbuf_v2_pdk",
        "Ipin vdd pin_in 10u",
        "Ipib vdd pin_ib 10u",
        "Ven en 0 1.8",
        "Vc0 c0 0 0",
        "Vc1 c1 0 0",
        "Vc2 c2 0 0",
        "Vc3 c3 0 0",
        "Xpbuf pin_in pin_ib pref_rcx en c0 c1 c2 c3 vdd 0 serdes_ref_pbuf_v2_pdk",
        ".temp 27",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_vecnames",
        "set wr_singlescale",
    ]
    for c in range(16):
        for k in range(4):
            lines.append(f"alter Vc{k} dc={1.8 if (c >> k) & 1 else 0.0}")
        lines += [
            "op",
            "let vcm=v(vcm_rcx)",
            "let pref=v(pref_rcx)",
            f"wrdata rcx_{c:02d}.tsv vcm pref",
            "destroy all",
        ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines)


def parse_tsv(path: Path) -> dict[str, float]:
    lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]
    cols = lines[0].split()
    vals = [float(x) for x in lines[-1].split()]
    out: dict[str, float] = {}
    if len(vals) == len(cols):
        for k, v in zip(cols, vals):
            out[k] = v
    else:
        for i, k in enumerate(cols):
            if 2 * i + 1 < len(vals):
                out[k] = vals[2 * i + 1]
    return out


def run_deck(work: Path, deck_text: str, timeout_s: float = 300.0) -> dict:
    t0 = time.monotonic()
    res = spice.run(deck_text, work, timeout_s=timeout_s)
    return {"ok": res.ok, "wall_s": time.monotonic() - t0, "rc": getattr(res, "exit_code", None), "dir": str(work)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--fast", action="store_true", help="Run 5 extreme MOSxRC corners (45 pts) instead of all 15 (135 pts)")
    args = ap.parse_args()

    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_dir = RESULTS / f"{ts}_postlayout"
    out_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.monotonic()

    sch_rows = json.loads(SCH_BASELINE.read_text()) if SCH_BASELINE.exists() else []
    sch_map = {(r["process"], r["rcorner"], r["supply"], r["temp"]): r for r in sch_rows}

    if args.fast:
        pairs = [("tt", "tt"), ("ss", "hh"), ("fs", "ll"), ("ff", "ll"), ("sf", "hh")]
    else:
        pairs = [(p, rc) for p in PROCESS for rc in ("tt", "ll", "hh")]

    # Stage 1: Post-layout PVT OP + codes + standalone RCX
    print(f"[Stage 1] Running {len(pairs)*9}-corner Post-Layout (CPEX+RCX) PVT OP + codes + standalone RCX (workers={args.workers})...")
    jobs: list[tuple[str, Path, str, float]] = []
    for p, rc in pairs:
        jobs.append((f"pvt_{p}_{rc}", out_dir / "pvt" / f"{p}_{rc}", build_pvt_deck(p, rc), 300.0))
    jobs.append(("codes", out_dir / "codes", build_codes_deck(), 300.0))
    jobs.append(("standalone_rcx", out_dir / "standalone_rcx", build_standalone_rcx_deck(), 180.0))

    job_res = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_deck, d, txt, to): name for name, d, txt, to in jobs}
        for f in as_completed(futs):
            name = futs[f]
            r = f.result()
            job_res[name] = r
            print(f"  {name}: ok={r['ok']} ({r['wall_s']:.1f}s)")
            if not r["ok"]:
                raise RuntimeError(f"ngspice failed for {name}: {r}")

    # Parse PVT OP rows & compute deltas vs schematic
    pvt_rows = []
    for p, rc in pairs:
        d = out_dir / "pvt" / f"{p}_{rc}"
        for v in SUPPLY_V:
            for t in TEMP_C:
                tag = f"{p}_{rc}_v{round(v*1000)}_t{t}"
                row = parse_tsv(d / f"{tag}.tsv")
                row.update(process=p, rcorner=rc, supply=v, temp=t)
                sch = sch_map.get((p, rc, v, t))
                if sch:
                    row["dvbg_mv"] = (row["vbg"] - sch["vbg"]) * 1e3
                    row["dvcm_mv"] = (row["vcm"] - sch["vcm"]) * 1e3
                    row["dpref_mv"] = (row["pref"] - sch["pref"]) * 1e3
                    row["diref_pct"] = (row["iref"] / sch["iref"] - 1.0) * 100.0
                    row["dicml_pct"] = (row["icml"] / sch["icml"] - 1.0) * 100.0
                    row["dir_pct"] = (row["ir"] / sch["ir"] - 1.0) * 100.0
                    row["dcml_swing_pct"] = (row["cml_swing"] / sch["cml_swing"] - 1.0) * 100.0
                pvt_rows.append(row)
    (out_dir / "pvt_rows.json").write_text(json.dumps(pvt_rows, indent=2))
    op_map = {(r["process"], r["rcorner"], r["supply"], r["temp"]): r for r in pvt_rows}

    # Compute DC line regulation per (proc, rc, temp)
    line_regs = []
    for p, rc in pairs:
        for t in TEMP_C:
            r_lo = op_map[(p, rc, 1.65, t)]
            r_hi = op_map[(p, rc, 1.95, t)]
            lr_mv_v = (r_hi["vbg"] - r_lo["vbg"]) / 0.30 * 1e3
            line_regs.append({"process": p, "rcorner": rc, "temp": t, "lr_mv_v": lr_mv_v,
                              "lr_db": float(20 * np.log10(max(abs(lr_mv_v) * 1e-3, 1e-9)))})

    # Parse trim & pbuf codes
    trim_rows = []
    for g in range(32):
        r = parse_tsv(out_dir / "codes" / f"trim_{g:02d}.tsv")
        r["code"] = g
        trim_rows.append(r)
    pbuf_rows = []
    for c in range(16):
        r = parse_tsv(out_dir / "codes" / f"pbuf_{c:02d}.tsv")
        r["code"] = c
        pbuf_rows.append(r)
    en_off = parse_tsv(out_dir / "codes" / "en_off.tsv")

    rcx_rows = []
    for c in range(16):
        r = parse_tsv(out_dir / "standalone_rcx" / f"rcx_{c:02d}.tsv")
        r["code"] = c
        rcx_rows.append(r)

    # Stage 2: Zero-start 1us ramp startup + +50mV/10ps step + PBUF 512ns LF precharge
    print(f"\n[Stage 2] Running Post-Layout Zero-Start Startup + +50mV/10ps Step + PBUF Precharge (workers={args.workers})...")
    startup_pts = [
        ("tt", "tt", 1.80, 27),
        ("ss", "hh", 1.65, -40),
        ("fs", "ll", 1.65, 85),
        ("ff", "ll", 1.95, 85),
        ("sf", "hh", 1.95, -40),
    ]
    precharge_pts = [
        ("tt", "tt", 1.80, 27, 7),
        ("ss", "hh", 1.65, -40, 0),
        ("ss", "hh", 1.65, -40, 7),
        ("ss", "hh", 1.65, -40, 15),
    ]
    tramp = 1e-6
    tsettle = 15e-6
    tstep = tramp + tsettle
    tran_jobs: list[tuple[str, Path, str, float]] = []
    for p, rc, v, t in startup_pts:
        tag = f"su_{p}_{rc}_v{round(v*1000)}_t{t}"
        txt, _ = build_startup_deck(p, rc, v, t, tramp, tsettle)
        tran_jobs.append((tag, out_dir / "startup" / tag, txt, 600.0))
    for p, rc, v, t, c in precharge_pts:
        sec = section(p, rc)
        tag = f"pre_{sec}_v{round(v*1000)}_t{t}_c{c}"
        txt = build_pbuf_precharge_deck(sec, v, t, c)
        tran_jobs.append((tag, out_dir / "precharge" / tag, txt, 300.0))

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(run_deck, d, txt, to): name for name, d, txt, to in tran_jobs}
        for f in as_completed(futs):
            name = futs[f]
            r = f.result()
            print(f"  {name}: ok={r['ok']} ({r['wall_s']:.1f}s)")
            if not r["ok"]:
                raise RuntimeError(f"ngspice failed for {name}: {r}")

    # Analyse startup & step
    startup_summary = []
    for p, rc, v, t in startup_pts:
        tag = f"su_{p}_{rc}_v{round(v*1000)}_t{t}"
        w = spice.Waves(out_dir / "startup" / tag / "startup.raw")
        tm = w.t
        vbg, vcm, iref, ir, icml = w["v(vbg)"], w["v(vcm)"], w["iref"], w["v(i1)"], w["icml"]
        pre = (tm > tstep - 1e-6) & (tm < tstep)
        vb0 = float(np.mean(vbg[pre]))
        i0 = float(np.mean(iref[pre]))
        ir0 = float(np.mean(ir[pre]))
        c0 = float(np.mean(icml[pre]))
        op = op_map[(p, rc, v, t)]
        ok = abs(vb0 - op["vbg"]) < 2e-3 and abs(i0 - op["iref"]) < 0.01 * abs(op["iref"])
        after = tm > tramp
        bad_v = np.where(after & (tm < tstep) & (np.abs(vbg - vb0) > 1e-3))[0]
        t_vbg = float(tm[bad_v[-1]] - tramp) * 1e6 if len(bad_v) else 0.0
        bad_c = np.where(after & (tm < tstep) & (np.abs(icml - c0) > 0.01 * abs(c0)))[0]
        t_cml = float(tm[bad_c[-1]] - tramp) * 1e6 if len(bad_c) else 0.0
        post = tm > tstep
        startup_summary.append({
            "corner": f"{p}_{rc} {v:.2f}V {t}C",
            "ok": bool(ok),
            "vbg_v": vb0,
            "d_vbg_op_mv": (vb0 - op["vbg"]) * 1e3,
            "d_i_op_pct": (i0 / op["iref"] - 1.0) * 100.0,
            "t_settle_vbg_us": t_vbg,
            "t_settle_cml_us": t_cml,
            "step_vbg_peak_mv": float(np.max(np.abs(vbg[post] - vb0)) * 1e3),
            "step_icml_peak_pct": float(np.max(np.abs(icml[post] - c0)) / abs(c0) * 100.0),
            "step_ir_peak_pct": float(np.max(np.abs(ir[post] - ir0)) / abs(ir0) * 100.0),
        })

    # Analyse precharge
    precharge_summary = []
    for p, rc, v, t, c in precharge_pts:
        sec = section(p, rc)
        tag = f"pre_{sec}_v{round(v*1000)}_t{t}_c{c}"
        w = spice.Waves(out_dir / "precharge" / tag / "precharge.raw")
        tm = w.t
        vz, vpref, vbg, icml = w["v(z)"], w["v(pref)"], w["v(vbg)"], w["icml"]
        idx_532 = int(np.argmin(np.abs(tm - 532e-9)))
        pre_m = tm < 18e-9
        vbg0 = float(np.mean(vbg[pre_m]))
        ic0 = float(np.mean(icml[pre_m]))
        target = pbuf_rows[c]["pref"] if (p == "tt" and rc == "tt" and v == 1.80 and t == 27) else float(vpref[idx_532])
        precharge_summary.append({
            "case": f"{sec} {v:.2f}V {t}C c={c}",
            "vz_512ns_v": float(vz[idx_532]),
            "vpref_512ns_v": float(vpref[idx_532]),
            "err_vz_vpref_mv": float((vz[idx_532] - vpref[idx_532]) * 1e3),
            "vbg_kick_mv": float(np.max(np.abs(vbg - vbg0)) * 1e3),
            "icml_kick_pct": float(np.max(np.abs(icml - ic0)) / abs(ic0) * 100.0),
        })

    # Aggregate summary
    vbgs = [r["vbg"] for r in pvt_rows]
    vcms = [r["vcm"] for r in pvt_rows]
    irs = [r["ir"] for r in pvt_rows]
    swings = [r["cml_swing"] for r in pvt_rows]
    icmls = [r["icml"] for r in pvt_rows]
    tt_op = op_map[("tt", "tt", 1.80, 27)]
    tt_lr = [x for x in line_regs if x["process"] == "tt" and x["rcorner"] == "tt" and x["temp"] == 27][0]
    worst_lr = max(line_regs, key=lambda x: abs(x["lr_mv_v"]))

    trim_i = [r["iref"] for r in trim_rows]
    trim_mono = all(trim_i[k + 1] > trim_i[k] for k in range(31))
    trim_nom = trim_i[15]
    pbuf_v = [r["pref"] for r in pbuf_rows]
    pbuf_steps = [pbuf_v[k + 1] - pbuf_v[k] for k in range(15)]
    pbuf_mono = all(s > 0 for s in pbuf_steps)

    rcx_v = [r["pref"] for r in rcx_rows]
    rcx_vcm = rcx_rows[0]["vcm"]

    summary = {
        "n_pvt_corners": len(pvt_rows),
        "wall_s": round(time.monotonic() - t_start, 1),
        "tt_op": tt_op,
        "pvt_ranges": {
            "vbg_min_v": min(vbgs), "vbg_max_v": max(vbgs),
            "vbg_spread_pct": (max(vbgs) - min(vbgs)) / (max(vbgs) + min(vbgs)) * 100.0,
            "vcm_min_v": min(vcms), "vcm_max_v": max(vcms),
            "ir_min_mv": min(irs) * 1e3, "ir_max_mv": max(irs) * 1e3,
            "ir_spread_pct": (max(irs) - min(irs)) / (max(irs) + min(irs)) * 100.0,
            "cml_swing_min_mv": min(swings) * 1e3, "cml_swing_max_mv": max(swings) * 1e3,
            "icml_min_ua": min(icmls) * 1e6, "icml_max_ua": max(icmls) * 1e6,
            "dc_line_reg_tt_mv_v": tt_lr["lr_mv_v"],
            "dc_line_reg_tt_db": tt_lr["lr_db"],
            "dc_line_reg_worst": worst_lr,
        },
        "pre_vs_post_delta": {
            "max_abs_dvbg_mv": max(abs(r["dvbg_mv"]) for r in pvt_rows if "dvbg_mv" in r),
            "tt_dvbg_mv": tt_op.get("dvbg_mv"),
            "max_abs_dvcm_mv": max(abs(r["dvcm_mv"]) for r in pvt_rows if "dvcm_mv" in r),
            "tt_dvcm_mv": tt_op.get("dvcm_mv"),
            "max_abs_dpref_mv": max(abs(r["dpref_mv"]) for r in pvt_rows if "dpref_mv" in r),
            "tt_dpref_mv": tt_op.get("dpref_mv"),
            "max_abs_diref_pct": max(abs(r["diref_pct"]) for r in pvt_rows if "diref_pct" in r),
            "tt_diref_pct": tt_op.get("diref_pct"),
            "max_abs_dicml_pct": max(abs(r["dicml_pct"]) for r in pvt_rows if "dicml_pct" in r),
            "tt_dicml_pct": tt_op.get("dicml_pct"),
            "max_abs_dcml_swing_pct": max(abs(r["dcml_swing_pct"]) for r in pvt_rows if "dcml_swing_pct" in r),
        },
        "trim_5bit": {
            "monotonic": trim_mono,
            "i_code0_ua": trim_i[0] * 1e6,
            "i_code15_ua": trim_nom * 1e6,
            "i_code31_ua": trim_i[31] * 1e6,
            "min_pct": (trim_i[0] / trim_nom - 1.0) * 100.0,
            "max_pct": (trim_i[31] / trim_nom - 1.0) * 100.0,
        },
        "pbuf_16code": {
            "monotonic": pbuf_mono,
            "v_code0_v": pbuf_v[0],
            "v_code7_v": pbuf_v[7],
            "v_code15_v": pbuf_v[15],
            "step_min_mv": min(pbuf_steps) * 1e3,
            "step_max_mv": max(pbuf_steps) * 1e3,
            "en_on_idd_ua": pbuf_rows[7]["idd"] * 1e6,
            "en_off_idd_ua": en_off["idd_off"] * 1e6,
            "delta_idd_en_ua": (pbuf_rows[7]["idd"] - en_off["idd_off"]) * 1e6,
        },
        "standalone_rcx": {
            "vbuf_vcm_v": rcx_vcm,
            "pbuf_code0_v": rcx_v[0],
            "pbuf_code7_v": rcx_v[7],
            "pbuf_code15_v": rcx_v[15],
            "pbuf_monotonic": all(rcx_v[k + 1] > rcx_v[k] for k in range(15)),
        },
        "startup_and_step": startup_summary,
        "precharge_512ns": precharge_summary,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print("\n" + "=" * 72)
    print(f"BIAS v2 POST-LAYOUT VERIFICATION SUMMARY ({out_dir.relative_to(ROOT)})")
    print("=" * 72)
    pr = summary["pvt_ranges"]
    dl = summary["pre_vs_post_delta"]
    print(f"PVT ({summary['n_pvt_corners']} corners): Vbg={pr['vbg_min_v']:.4f}..{pr['vbg_max_v']:.4f} V (±{pr['vbg_spread_pct']:.2f}%)")
    print(f"  DC Line Reg: TT={pr['dc_line_reg_tt_mv_v']:+.2f} mV/V ({pr['dc_line_reg_tt_db']:.1f} dB) | "
          f"Worst={pr['dc_line_reg_worst']['lr_mv_v']:+.2f} mV/V ({pr['dc_line_reg_worst']['lr_db']:.1f} dB) "
          f"at {pr['dc_line_reg_worst']['process']}_{pr['dc_line_reg_worst']['rcorner']} {pr['dc_line_reg_worst']['temp']}C")
    print(f"  Vcm={pr['vcm_min_v']:.4f}..{pr['vcm_max_v']:.4f} V | I*R={pr['ir_min_mv']:.2f}..{pr['ir_max_mv']:.2f} mV (±{pr['ir_spread_pct']:.2f}%) | "
          f"CML swing={pr['cml_swing_min_mv']:.1f}..{pr['cml_swing_max_mv']:.1f} mV")
    print(f"Pre- vs Post-Layout Delta (across all {summary['n_pvt_corners']} corners):")
    print(f"  |dVbg| max={dl['max_abs_dvbg_mv']:.3f} mV (TT {dl['tt_dvbg_mv']:+.3f} mV) | "
          f"|dVcm| max={dl['max_abs_dvcm_mv']:.3f} mV | |dPref| max={dl['max_abs_dpref_mv']:.3f} mV")
    print(f"  |dIref| max={dl['max_abs_diref_pct']:.3f}% (TT {dl['tt_diref_pct']:+.3f}%) | "
          f"|dIcml| max={dl['max_abs_dicml_pct']:.3f}% | |dCML_swing| max={dl['max_abs_dcml_swing_pct']:.3f}%")
    tr = summary["trim_5bit"]
    pb = summary["pbuf_16code"]
    print(f"5-bit r_ref trim: mono={tr['monotonic']}, {tr['i_code0_ua']:.3f}..{tr['i_code31_ua']:.3f} uA ({tr['min_pct']:+.2f}%..{tr['max_pct']:+.2f}%)")
    print(f"16-code real-CMOS PBUF: mono={pb['monotonic']}, {pb['v_code0_v']:.4f}..{pb['v_code15_v']:.4f} V "
          f"(step {pb['step_min_mv']:.2f}..{pb['step_max_mv']:.2f} mV), en_pbuf dIdd={pb['delta_idd_en_ua']:.1f} uA")
    sr = summary["standalone_rcx"]
    print(f"Standalone RCX: vbuf vcm={sr['vbuf_vcm_v']:.4f} V | pbuf mono={sr['pbuf_monotonic']} ({sr['pbuf_code0_v']:.4f}..{sr['pbuf_code15_v']:.4f} V)")
    print("Zero-Start Startup + +50 mV/10 ps Step:")
    for s in startup_summary:
        print(f"  {s['corner']:20s}: ok={s['ok']} dVbg={s['d_vbg_op_mv']:+.3f}mV dI={s['d_i_op_pct']:+.3f}% "
              f"t_vbg={s['t_settle_vbg_us']:.2f}us t_cml={s['t_settle_cml_us']:.2f}us | "
              f"step Vbg_pk={s['step_vbg_peak_mv']:.2f}mV Icml_pk={s['step_icml_peak_pct']:.2f}%")
    print("512 ns LF Precharge:")
    for s in precharge_summary:
        print(f"  {s['case']:28s}: vz={s['vz_512ns_v']:.4f}V vpref={s['vpref_512ns_v']:.4f}V "
              f"(err={s['err_vz_vpref_mv']:+.1f}mV) vbg_kick={s['vbg_kick_mv']:.3f}mV icml_kick={s['icml_kick_pct']:.3f}%")
    print(f"Total wall time: {summary['wall_s']:.1f} s")


if __name__ == "__main__":
    main()
