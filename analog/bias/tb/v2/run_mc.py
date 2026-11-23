"""BIAS v2 200-sample tt_mm Monte Carlo (Vbg, Iref, I*R, vcm, err_core, err_vi across 27/-40/85 C).

Usage:
    uv run python analog/bias/tb/v2/run_mc.py [--samples 200] [--workers 2]
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/bias/v2"
BIAS_V2 = ROOT / "analog/bias/spice/bias_v2.spice"
PRIMS = ROOT / "analog/common/devices/spice/sky130_primitives.spice"
PLVT = ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice"

LETS = {
    "vbg": "v(vbg)",
    "vcm": "v(vcm)",
    "iref": "i(Vi0)",
    "ir": "v(i1)",
    "icml": "i(Vmcml)",
    "cml_swing": "v(cml_top)-v(cml_dr)",
    "err_core": "v(xtop.xref.ta)-v(xtop.xref.tb)",
    "err_vi": "v(xtop.xref.s)-v(vbg)",
}


def netlist(section: str, temp: int, supply: float = 1.8) -> str:
    lib = spice.corner_values(Condition("tt", supply, temp))["MODEL_LIBRARY"]
    return "\n".join([
        f"* BIAS v2 MC ({section} {temp}C)",
        f'.lib "{lib}" {section}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2}"',
        f"Vdd vdd 0 {supply}",
        "Eg4 g4 0 vdd 0 0", "Eg3 g3 0 vdd 0 1", "Eg2 g2 0 vdd 0 1", "Eg1 g1 0 vdd 0 1", "Eg0 g0 0 vdd 0 1",
        "Ec3 c3 0 vdd 0 0", "Ec2 c2 0 vdd 0 1", "Ec1 c1 0 vdd 0 1", "Ec0 c0 0 vdd 0 1",
        "Een en_pbuf 0 vdd 0 0",
        "Xtop vbg vcm pref icml ictle icp i0 i1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2",
        "Vi0 i0 0 0.7",
        "Xrl i1 0 0 sky130_fd_pr__res_high_po w=1 l=18",
        "Cvcm vcm 0 5p",
        "Vmcml icml vcml 0",
        "Xdcml vcml 0 serdes_bias_cml_v2",
        "Xdctle ictle 0 serdes_bias_ctle_v2",
        "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
        "Vtop cml_top 0 1.0",
        "Xrl_cml cml_top cml_dr 0 sky130_fd_pr__res_high_po w=3 l=3.54",
        "Xtail_cml cml_dr vcml 0 0 serdes_nfet w=20 l=0.5 nf=4",
        ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(xtop.xref.s)=1.234 v(xtop.xref.vg)=0.9 v(xtop.vgi)=0.9 v(xtop.xref.ta)=1.05 v(xtop.xref.tb)=1.05",
        f".temp {temp}",
        ".options reltol=1e-5 abstol=1p vntol=1u klu",
        "",
    ])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--temps", default="27,-40,85")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    temps = [int(x) for x in args.temps.split(",")]
    camp = RESULTS / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_mc{args.samples}"
    camp.mkdir(parents=True, exist_ok=True)
    jobs = []
    for t in temps:
        jobs.append((mc.deck(netlist("tt", t), 1, seed=args.seed, lets=LETS), camp / f"nom_t{t}", dict(timeout_s=600)))
        for k, s, n in mc.chunks(args.samples, args.seed, per=10):
            jobs.append((mc.deck(netlist("tt_mm", t), n, seed=s, lets=LETS), camp / f"mc_t{t}_c{k:02d}", dict(timeout_s=1800)))

    print(f"Launching {len(jobs)} MC jobs ({args.samples} samples x {len(temps)} temps, workers={args.workers}) -> {camp.relative_to(ROOT)}", flush=True)
    resolved = dict(zip((j[1] for j in jobs), mc.run_many(jobs, workers=args.workers)))
    out = dict(samples=args.samples, temps=temps, per_temp={})
    data = {}
    for t in temps:
        nom = mc.read(resolved[camp / f"nom_t{t}"])[0]
        rows = mc.read_all([resolved[j[1]] for j in jobs if j[1].name.startswith(f"mc_t{t}_c")])
        data[t] = {k: mc.column(rows, k) for k in LETS}
        res = {}
        for k, scale in [("vbg", 1e3), ("vcm", 1e3), ("iref", 1e6), ("ir", 1e3), ("cml_swing", 1e3), ("err_core", 1e3), ("err_vi", 1e3)]:
            x = (data[t][k] - nom[k]) * scale
            s = stats.summary(x)
            lo, hi = stats.tolerance(x)
            res[k] = dict(nominal=nom[k], dev=s, tol3=[lo, hi])
        out["per_temp"][t] = res
        print(
            f"T {t:4d}C: vbg nom={nom['vbg']:.4f}V sigma={res['vbg']['dev']['std']:.2f}mV (3s {res['vbg']['tol3'][0]:+.1f}..{res['vbg']['tol3'][1]:+.1f}mV) "
            f"| vcm sigma={res['vcm']['dev']['std']:.2f}mV "
            f"| iref sigma={res['iref']['dev']['std']/(nom['iref']*1e6)*100:.2f}% "
            f"| I*R sigma={res['ir']['dev']['std']/(nom['ir']*1e3)*100:.2f}% "
            f"| core_err sigma={res['err_core']['dev']['std']:.2f}mV vi_err sigma={res['err_vi']['dev']['std']:.2f}mV"
        )
    if 27 in data and -40 in data and 85 in data:
        tc = (data[85]["vbg"] - data[-40]["vbg"]) * 1e3
        s = stats.summary(tc)
        out["vbg_span_85_m40_mv"] = s
        corr = float(np.corrcoef(data[27]["vbg"], tc)[0, 1])
        print(f"vbg(85)-vbg(-40): mean={s['mean']:+.2f}mV sigma={s['std']:.2f}mV corr_with_27C={corr:+.2f}")
    (camp / "summary.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"Saved -> {camp.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
