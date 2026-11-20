"""BIAS v2 zero-start 1 us VDD ramp startup + +50 mV/10 ps supply step + PBUF 512 ns precharge check.

Usage:
    uv run python analog/common/bias/tb/v2/run_startup.py --op <pvt_ac_dir> [--workers 2] [--fast]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
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
    return "\n".join(f"E{prefix}{k} {prefix}{k} 0 vdd 0 {(val >> k) & 1}" for k in range(nbits))


def build_startup_deck(proc: str, rc: str, tramp: float = 1e-6, tsettle: float = 15e-6) -> tuple[str, float]:
    lib = spice.corner_values(Condition(proc, 1.8, 27))["MODEL_LIBRARY"]
    sec = section(proc, rc)
    tstep = tramp + tsettle
    stop = tstep + 4e-6
    lines = [
        f"* BIAS v2 Zero-Start 1us Ramp Startup + +50mV/10ps Supply Step ({sec})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2}"',
        "Vsup sup 0 1.8",
        f"Bvdd vdd 0 V=v(sup)*min(max(time/{tramp:.3e},0),1)+0.05*min(max((time-{tstep:.3e})/10p,0),1)",
        bits_sources("g", 15, 5),
        bits_sources("c", 7, 4),
        "Een en_pbuf 0 vdd 0 0",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2",
        "Vi0 i0 0 0.7",
        "Xrl i1 0 0 sky130_fd_pr__res_high_po w=1 l=18",
        "Cvcm vcm 0 5p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2",
        "Xdctle ictle 0 serdes_bias_ctle_v2",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
        # NO .nodeset! True zero-start!
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
    ]
    for v in SUPPLY_V:
        for t in TEMP_C:
            tag = f"{proc}_{rc}_v{round(v*1000)}_t{t}"
            lines += [
                f"option temp={t}",
                f"alter Vsup dc={v}",
                f"tran 5n {stop:.4e} 0 25n",
                "let iref=i(Vi0)",
                "let icml=i(Vmcml)",
                f"write {tag}.raw v(vbg) iref v(i1) icml v(vcml) v(vdd)",
                "destroy all",
            ]
    lines += ["quit", ".endc", ".end", ""]
    return "\n".join(lines), tstep


def build_pbuf_precharge_deck(sec: str, supply: float, temp: int, code: int) -> str:
    """Verify 512 ns LF precharge (42 pF from 0 V) + zero kick on vgi / icml."""
    lib = spice.corner_values(Condition("tt", supply, temp))["MODEL_LIBRARY"]
    lf = ROOT / "analog/pll/loop_filter/spice/passive_rc_precharge.spice"
    cmos = ROOT / "analog/common/devices/spice/cmos_logic.spice"
    lines = [
        f"* BIAS v2 PBUF 512ns LF Precharge ({sec} {supply}V {temp}C code={code})",
        f'.lib "{lib}" {sec}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{cmos}"',
        f'.include "{BIAS_V2}"',
        f'.include "{lf}"',
        f"Vdd vdd 0 {supply}",
        bits_sources("g", 15, 5),
        bits_sources("c", code, 4),
        "Ben en_pbuf 0 V=v(vdd)*min(max((time-20n)/100p,0),1)",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2",
        "Vi0 i0 0 0.7",
        "Vi1 i1 0 0.7",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2",
        "Xdctle ictle 0 serdes_bias_ctle_v2",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
        "Xlf cpi ctrl z pref en_pbuf vdd 0 pll_loop_filter_precharge",
        ".ic v(ctrl)=0 v(z)=0",
        ".nodeset v(vbg)=1.234 v(xtop.xref.s)=1.234 v(xtop.xref.vg)=0.9 v(xtop.vgi)=0.9 v(xtop.xref.ta)=1.05 v(xtop.xref.tb)=1.05",
        f".temp {temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set filetype=binary",
        "tran 1n 600n 0 2n",
        "let icml=i(Vmcml)",
        "write pbuf.raw v(z) v(pref) v(xtop.xpbuf.tap) v(xtop.vgi) icml",
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


def analyse_startup(raw: Path, op: dict, tramp: float, tstep: float) -> dict:
    w = spice.Waves(raw)
    t = w.t
    vbg, iref, ir, icml = w["v(vbg)"], w["iref"], w["v(i1)"], w["icml"]
    pre = (t > tstep - 1e-6) & (t < tstep)
    vb0, i0, ir0, c0 = float(np.mean(vbg[pre])), float(np.mean(iref[pre])), float(np.mean(ir[pre])), float(np.mean(icml[pre]))
    ok = abs(vb0 - op["vbg"]) < 2e-3 and abs(i0 - op["iref"]) < 0.01 * abs(op["iref"])
    after = t > tramp
    bad_v = np.where(after & (t < tstep) & (np.abs(vbg - vb0) > 1e-3))[0]
    t_settle_vbg = float(t[bad_v[-1]] - tramp) * 1e6 if len(bad_v) else 0.0
    bad_c = np.where(after & (t < tstep) & (np.abs(icml - c0) > 0.01 * abs(c0)))[0]
    t_settle_cml = float(t[bad_c[-1]] - tramp) * 1e6 if len(bad_c) else 0.0
    post = t > tstep
    return dict(
        ok=bool(ok),
        vbg=vb0,
        iref=i0,
        d_vbg_op_mv=(vb0 - op["vbg"]) * 1e3,
        d_i_op_pct=(i0 / op["iref"] - 1) * 100,
        t_settle_vbg_us=t_settle_vbg,
        t_settle_cml_us=t_settle_cml,
        step_vbg_peak_mv=float(np.max(np.abs(vbg[post] - vb0)) * 1e3),
        step_icml_peak_pct=float(np.max(np.abs(icml[post] - c0)) / abs(c0) * 100),
        step_ir_peak_pct=float(np.max(np.abs(ir[post] - ir0)) / abs(ir0) * 100),
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--op", required=True, help="Relative path to pvt_ac campaign containing pvt_rows.json")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--fast", action="store_true", help="Run 5 extreme MOSxRC corners (45 pts) instead of all 15 (135 pts)")
    args = ap.parse_args()

    ops_list = json.loads((ROOT / args.op / "pvt_rows.json").read_text())
    ops = {(r["process"], r["rcorner"], r["supply"], r["temp"]): r for r in ops_list}

    pairs = [("tt", "tt"), ("ss", "hh"), ("ff", "ll"), ("fs", "ll"), ("sf", "hh")] if args.fast else [
        (p, rc) for p in PROCESS for rc in ("tt", "ll", "hh")
    ]
    camp = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_startup{'_fast' if args.fast else '_full135'}"
    camp.mkdir(parents=True, exist_ok=True)

    tramp, tsettle = 1e-6, 15e-6
    jobs = []
    tstep = tramp + tsettle
    for p, rc in pairs:
        d, tstep = build_startup_deck(p, rc, tramp, tsettle)
        jobs.append((d, camp / "tran" / f"{p}_{rc}", dict(timeout_s=1800, meta=dict(process=p, rcorner=rc))))

    # Also check PBUF 512ns LF precharge on TT + hard extremes (codes 0, 7, 15)
    pbuf_cases = [
        ("tt", 1.80, 27, 7),
        ("ss_hh", 1.65, -40, 0),
        ("ss_hh", 1.65, -40, 7),
        ("ss_hh", 1.65, -40, 15),
        ("ff_ll", 1.95, 85, 7),
        ("ff_ll", 1.95, 85, 15),
    ]
    for sec, v, t, c in pbuf_cases:
        tag = f"{sec}_v{round(v*1000)}_t{t}_c{c}"
        jobs.append((build_pbuf_precharge_deck(sec, v, t, c), camp / "pbuf" / tag, dict(timeout_s=600, meta=dict(kind="pbuf"))))

    print(f"Launching {len(jobs)} transient jobs (workers={args.workers}) -> {camp.relative_to(ROOT)}", flush=True)
    for ex in spice.run_many(jobs, workers=args.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)

    rows = []
    for p, rc in pairs:
        for v in SUPPLY_V:
            for t in TEMP_C:
                raw = camp / "tran" / f"{p}_{rc}" / f"{p}_{rc}_v{round(v*1000)}_t{t}.raw"
                if raw.exists() and (p, rc, v, t) in ops:
                    rows.append(dict(process=p, rcorner=rc, supply=v, temp=t, **analyse_startup(raw, ops[(p, rc, v, t)], tramp, tstep)))

    n_ok = sum(1 for r in rows if r["ok"])
    print(f"\n=== ZERO-START 1us RAMP STARTUP + +50mV/10ps STEP ({n_ok}/{len(rows)} OK) ===")
    for k, u in [
        ("t_settle_vbg_us", "us"),
        ("t_settle_cml_us", "us"),
        ("d_vbg_op_mv", "mV"),
        ("d_i_op_pct", "%"),
        ("step_vbg_peak_mv", "mV"),
        ("step_icml_peak_pct", "%"),
        ("step_ir_peak_pct", "%"),
    ]:
        vals = [r[k] for r in rows]
        print(f"  {k:20s}: {min(vals):8.3f} .. {max(vals):8.3f} {u}")
    bad = [r for r in rows if not r["ok"]]
    for r in bad[:10]:
        print("  FAIL:", r)

    print("\n=== PBUF 512ns LF PRECHARGE + VGI KICK ===")
    pbuf_res = []
    for sec, v, t, c in pbuf_cases:
        tag = f"{sec}_v{round(v*1000)}_t{t}_c{c}"
        raw = camp / "pbuf" / tag / "pbuf.raw"
        if not raw.exists():
            continue
        w = spice.Waves(raw)
        tm, z, tap, vgi, icml = w.t, w["v(z)"], w["v(xtop.xpbuf.tap)"], w["v(xtop.vgi)"], w["icml"]
        target = float(tap[-1])
        z512 = float(np.interp(532e-9, tm, z))
        err_mv = (z512 - target) * 1e3
        pre = tm < 18e-9
        ic0 = float(np.mean(icml[pre]))
        vgi0 = float(np.mean(vgi[pre]))
        dvgi_mv = float(np.max(np.abs(vgi - vgi0)) * 1e3)
        dicml_pct = float(np.max(np.abs(icml - ic0)) / abs(ic0) * 100)
        idx10 = np.where((tm > 20e-9) & (np.abs(z - target) > 10e-3))[0]
        t10_ns = float(tm[idx10[-1]] - 20e-9) * 1e9 if len(idx10) else 0.0
        rec = dict(section=sec, supply=v, temp=t, code=c, target_v=target, z512_v=z512,
                   err_512ns_mv=err_mv, t_to_10mv_ns=t10_ns, dvgi_kick_mv=dvgi_mv, dicml_kick_pct=dicml_pct)
        pbuf_res.append(rec)
        print(f"  {sec:6s} {v:.2f}V {t:3d}C c={c:2d}: target={target:.4f}V z@512ns={z512:.4f}V err={err_mv:+6.2f}mV t10mV={t10_ns:5.0f}ns | dvgi={dvgi_mv:.3f}mV dicml={dicml_pct:.3f}%")

    (camp / "summary.json").write_text(json.dumps(dict(startup=rows, pbuf=pbuf_res), indent=2) + "\n")
    print(f"Saved -> {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
