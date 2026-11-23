#!/usr/bin/env python3
"""Multi-angle phase, hard-corner, frequency-shmoo, supply-Kd & MC benchmark
comparing 4 pure-CMOS / TSPC 2 GHz /8 prescaler architectures:
  1. cmos_ripple   : pll_cmos_prescaler8_2g (cascaded C2MOS ripple /8)
  2. cmos_sync_s4  : pll_cmos_sync_prescaler8_2g (2 GHz S4 lookahead C2MOS)
  3. tspc9_reclock : pll_tspc9_reclock_prescaler8_2g (9T dynamic TSPC + 1 GHz sync + 2 GHz reclock)
  4. saff_reclock  : pll_saff_reclock_prescaler8_2g (SAFF-TSPC + 1 GHz sync + 2 GHz reclock)
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import numpy as np

from serdes_flow import bias, clock, corners, mc, spice, stats
from serdes_flow.project import ROOT

sys.path.insert(0, str(ROOT / "verification/layout"))
from review_sim import freeze_includes, save_analysis

MODEL_LIB = spice.corner_values(corners.Condition.parse("tt_v1800_t27"))["MODEL_LIBRARY"]
R5_PEX = ROOT / "analog/common/cml_to_cmos/layout/variants/r5_pdk/serdes_cml_to_cmos_r5_pdk_pex.spice"
R5_RCX = ROOT / "results/layout_review/cml_to_cmos_r5_20261118T1445Z_v6/serdes_cml_to_cmos_r5_pdk_rcx.spice"
RESULTS = ROOT / "results/analog/pll/divider/tspc_study"

ARCHS = {
    "cmos_ripple": (
        ROOT / "analog/pll/divider/spice/cmos_prescaler8_2g.spice",
        "pll_cmos_prescaler8_2g",
        [ROOT / "analog/common/devices/spice/cmos_logic.spice"],
    ),
    # cmos_sync_s4 retired on 2026-11-20 (archived under results/maintenance/divider_retirement/20261120/untracked/).
    "tspc9_reclock": (
        ROOT / "analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice",
        "pll_tspc9_reclock_prescaler8_2g",
        [],
    ),
    "saff_reclock": (
        ROOT / "analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice",
        "pll_saff_reclock_prescaler8_2g",
        [],
    ),
    "saff_reclock_pdk": (
        ROOT / "analog/pll/divider/layout/variants/saff_reclock_2g_pdk/pll_saff_reclock_prescaler8_2g_pdk_pex.spice",
        "pll_saff_reclock_prescaler8_2g_pdk",
        [],
    ),
}

HARD9 = [
    ("tt_v1800_t27", "tt"),
    ("ss_v1650_t-40", "hh"),
    ("ss_v1650_t85", "hh"),
    ("fs_v1650_t85", "hh"),
    ("fs_v1650_t-40", "hh"),
    ("sf_v1650_t-40", "ll"),
    ("sf_v1650_t85", "ll"),
    ("ff_v1950_t85", "ll"),
    ("ff_v1950_t-40", "ll"),
]


def _header(lib_sec: str, dut_spice: Path, extra_inc: list[Path], driver_spice: Path | None) -> list[str]:
    inc = [
        f'.lib "{MODEL_LIB}" {lib_sec}',
        f'.include "{ROOT / "analog/common/devices/spice/sky130_primitives.spice"}"',
    ]
    for p in extra_inc:
        inc.append(f'.include "{p}"')
    if driver_spice is not None:
        inc.extend([
            f'.include "{ROOT / "analog/common/cml_buffer/spice/cml_delay_resistive.spice"}"',
            f'.include "{ROOT / "analog/common/cml_buffer/spice/cml_buffer.spice"}"',
            f'.include "{ROOT / "analog/pll/divider/spice/cml_latch.spice"}"',
            f'.include "{ROOT / "analog/pll/divider/spice/cml_div2.spice"}"',
            f'.include "{ROOT / "analog/pll/divider/spice/cml_prescaler8.spice"}"',
            f'.include "{driver_spice}"',
        ])
    inc.append(f'.include "{dut_spice}"')
    return inc


def _make_deck(
    c: corners.Condition,
    rc: str,
    dut_spice: Path,
    subckt: str,
    extra_inc: list[Path],
    freq: float = 2.0e9,
    cq8: float = 20e-15,
    input_pp: float = 0.30,
    stop_ns: float = 30.0,
    skip_ns: float = 11.0,
    driver_spice: Path | None = R5_PEX,
    vdiv_delta: float = 0.0,
    vdiv_ripple_amp: float = 0.0,
    vdiv_ripple_hz: float = 20e6,
    ideal_edge_ps: float = 25.0,
) -> str:
    cv = spice.corner_values(c)
    vsup = float(cv["SUPPLY"])
    vdiv = vsup + vdiv_delta
    if vdiv_ripple_amp > 0.0:
        vdiv_src = f"Vdiv vdiv 0 SIN({vdiv} {vdiv_ripple_amp} {vdiv_ripple_hz} 2n)"
    else:
        vdiv_src = "Vdiv vdiv 0 PWL(0 0 0.5n {vdiv_sup})"
    lines = [
        f"{subckt} {c.tag}:{rc} f={freq/1e9:.3f}G dv={vdiv_delta*1e3:+.1f}mV rip={vdiv_ripple_amp*1e3:.1f}mV",
        *_header(cv["CORNER"], dut_spice, extra_inc, driver_spice),
        f".param supply={vsup} vdiv_sup={vdiv} input_pp={input_pp} freq={freq}",
        vdiv_src,
    ]
    if driver_spice is not None:
        lines.extend([
            "Vdd vdd 0 PWL(0 0 0.5n {supply})",
            "Vrx vrx 0 PWL(0 0 0.5n {supply})",
            "Vreference vref 0 PWL(0 0 0.5n {supply})",
            "Iref vref vbias .85m",
            "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
            "Vp sp 0 SIN({supply-.15} {input_pp/4} {freq})",
            "Vn sn 0 SIN({supply-.15} {-input_pp/4} {freq})",
            "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
            "Xpre bp bn d2p d2n d4p d4n d8p d8n vbias vdd 0 pll_cml_prescaler8",
            "Xrx bp bn clkp clkn vbias vrx 0 serdes_cml_to_cmos_r5_pdk",
        ])
    else:
        per = 1.0 / freq
        tr = ideal_edge_ps * 1e-12
        pw = per / 2.0 - tr
        lines.extend([
            "Vrx vrx 0 PWL(0 0 0.5n {supply})",
            f"Vckp clkp 0 PULSE(0 {{supply}} 1n {tr:.3e} {tr:.3e} {pw:.6e} {per:.6e})",
            f"Vckn clkn 0 PULSE({{supply}} 0 1n {tr:.3e} {tr:.3e} {pw:.6e} {per:.6e})",
        ])
    lines.extend([
        f"Xdiv clkp clkn q2p q2n q4p q4n q8p q8n vdiv 0 {subckt}",
        "Cq2p q2p 0 15f", "Cq2n q2n 0 15f",
        "Cq4p q4p 0 15f", "Cq4n q4n 0 15f",
        f"Cq8p q8p 0 {cq8:.3e}", f"Cq8n q8n 0 {cq8:.3e}",
        f".temp {cv['TEMP_C']}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".save v(clkp) v(clkn) v(q2p) v(q2n) v(q4p) v(q4n) v(q8p) v(q8n) v(vrx) v(vdiv) i(Vrx) i(Vdiv)",
        ".control",
        "set num_threads=1",
        "set wr_singlescale",
        "set wr_vecnames",
        f"tran 2p {stop_ns}n 0 2p uic",
        "let prx=-v(vrx)*i(Vrx)",
        "let pdiv=-v(vdiv)*i(Vdiv)",
        "wrdata waveforms.tsv v(clkp) v(clkn) v(q2p) v(q2n) v(q4p) v(q4n) v(q8p) v(q8n) prx pdiv",
        "quit",
        ".endc",
        ".end",
        "",
    ])
    text = spice.skip_output_before(spice.binary_output("\n".join(lines)), f"{skip_ns}n")
    return bias.section(text, c.process, rc)


def _mean_nearest_ps(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    inner = a[(a > b[0]) & (a < b[-1])]
    if len(inner) == 0:
        inner = a
    return float(np.mean([x - b[np.argmin(np.abs(b - x))] for x in inner]) * 1e12)


def _mean_forward_ps(src: np.ndarray, dst: np.ndarray, max_dt: float) -> float:
    """Mean forward propagation delay dst - src for each dst matching nearest preceding src."""
    if len(src) == 0 or len(dst) == 0:
        return float("nan")
    dts = []
    for d in dst:
        prev = src[src <= d]
        if len(prev) == 0:
            continue
        dt = float(d - prev[-1])
        if 0.0 <= dt <= max_dt:
            dts.append(dt * 1e12)
    return float(np.mean(dts)) if dts else float("nan")


def _logic_metrics(t, sig, supply, expected_hz, start):
    ps = clock.period_stats(t, sig - supply / 2.0, start, min_cycles=2)
    sel = sig[t >= start]
    rises = clock.edges(t, sig - supply / 2.0, start=start)
    bad_per = int(np.count_nonzero(np.abs(np.diff(rises) * expected_hz - 1.0) > 0.2)) if len(rises) >= 2 else -1
    lo, hi = float(sel.min()), float(sel.max())
    good = bool(
        ps
        and abs(ps["frequency_hz"] / expected_hz - 1.0) < 0.01
        and ps["duty"] is not None
        and 0.45 <= ps["duty"] <= 0.55
        and lo < 0.2 * supply
        and hi > 0.8 * supply
        and bad_per == 0
    )
    return dict(
        ok=good,
        freq_ghz=ps["frequency_hz"] / 1e9 if ps else None,
        duty=ps["duty"] if ps else None,
        low=lo,
        high=hi,
        bad_periods=bad_per,
    )


def eval_wave(raw_path: Path, c: corners.Condition, freq: float, start_s: float, vdiv_delta: float = 0.0) -> dict:
    w = spice.Waves(raw_path)
    t = w.t
    m = t >= start_s
    stop_s = float(t[-1]) - 0.5e-9
    vdiv = c.supply + vdiv_delta
    ok = True
    row = dict(
        condition=c.tag,
        freq_ghz=freq / 1e9,
        prx_mw=float(np.mean(w["prx"][m]) * 1e3),
        pdiv_mw=float(np.mean(w["pdiv"][m]) * 1e3),
    )
    for lbl, exp_f, vs in [
        ("clk", freq, c.supply),
        ("q2", freq / 2.0, vdiv),
        ("q4", freq / 4.0, vdiv),
        ("q8", freq / 8.0, vdiv),
    ]:
        for side in ("p", "n"):
            k = lbl if side == "p" else lbl + "n"
            row[k] = _logic_metrics(t, w[f"v({lbl}{side})"], vs, exp_f, start_s)
            if lbl != "clk":
                ok &= row[k]["ok"]

    # Differential signals
    ckd = w["v(clkp)"] - w["v(clkn)"]
    q2d = w["v(q2p)"] - w["v(q2n)"]
    q4d = w["v(q4p)"] - w["v(q4n)"]
    q8d = w["v(q8p)"] - w["v(q8n)"]

    ck_r = clock.edges(t, ckd, +1, start_s, stop_s)
    ck_f = clock.edges(t, ckd, -1, start_s, stop_s)
    q2_r = clock.edges(t, q2d, +1, start_s, stop_s)
    q2_f = clock.edges(t, q2d, -1, start_s, stop_s)
    q4_r = clock.edges(t, q4d, +1, start_s, stop_s)
    q4_f = clock.edges(t, q4d, -1, start_s, stop_s)
    q8_r = clock.edges(t, q8d, +1, start_s, stop_s)
    q8_f = clock.edges(t, q8d, -1, start_s, stop_s)

    # Single-ended p vs n complementary crossing skew (at vdiv/2)
    pn_skew = {}
    for lbl in ("q2", "q4", "q8"):
        pr = clock.edges(t, w[f"v({lbl}p)"] - vdiv / 2.0, +1, start_s, stop_s)
        nf = clock.edges(t, w[f"v({lbl}n)"] - vdiv / 2.0, -1, start_s, stop_s)
        pf = clock.edges(t, w[f"v({lbl}p)"] - vdiv / 2.0, -1, start_s, stop_s)
        nr = clock.edges(t, w[f"v({lbl}n)"] - vdiv / 2.0, +1, start_s, stop_s)
        s1 = _mean_nearest_ps(pr, nf)
        s2 = _mean_nearest_ps(pf, nr)
        pn_skew[lbl] = max((abs(v) for v in (s1, s2) if np.isfinite(v)), default=float("nan"))

    # Binary counting check (allows either up +1 or down -1 mod 8 on active edge)
    best_bad = 999
    best_samp = 0
    for act in (ck_r, ck_f):
        if len(act) < 4:
            continue
        per = float(np.mean(np.diff(act)))
        for frac in (0.15, 0.35, 0.50, 0.70, 0.85):
            samp = act[:-1] + frac * per
            samp = samp[(samp >= start_s) & (samp <= stop_s)]
            if len(samp) < 4:
                continue
            st = (
                ((np.interp(samp, t, q8d) > 0).astype(int) << 2)
                | ((np.interp(samp, t, q4d) > 0).astype(int) << 1)
                | (np.interp(samp, t, q2d) > 0).astype(int)
            )
            diffs = np.diff(st) % 8
            bad = min(int(np.count_nonzero(diffs != 1)), int(np.count_nonzero(diffs != 7)))
            if bad < best_bad:
                best_bad = bad
                best_samp = len(samp)

    # Inter-stage skew (check against nearest q2 edge, rise or fall depending on up/down counter)
    q2_all = np.sort(np.concatenate([q2_r, q2_f]))
    q4_all = np.sort(np.concatenate([q4_r, q4_f]))
    sk4_r = _mean_nearest_ps(q4_r, q2_all)
    sk4_f = _mean_nearest_ps(q4_f, q2_all)
    sk8_r = _mean_nearest_ps(q8_r, q4_all)
    sk8_f = _mean_nearest_ps(q8_f, q4_all)
    sk82_r = _mean_nearest_ps(q8_r, q2_all)
    sk82_f = _mean_nearest_ps(q8_f, q2_all)
    max_sk = max((abs(v) for v in (sk4_r, sk4_f, sk8_r, sk8_f, sk82_r, sk82_f) if np.isfinite(v)), default=float("nan"))

    # Absolute clock-to-q8 propagation delay (relative to nearest preceding ck_r, modulo T_clk)
    per_s = 1.0 / freq
    clk_to_q8_r = _mean_forward_ps(ck_r, q8_r, per_s)
    clk_to_q8_f = _mean_forward_ps(ck_r, q8_f, per_s)

    row["counter"] = dict(counting=(best_bad == 0 and best_samp >= 6), bad_steps=best_bad, samples=best_samp)
    row["skew_ps"] = dict(
        q4_q2=max((abs(v) for v in (sk4_r, sk4_f) if np.isfinite(v)), default=float("nan")),
        q8_q4=max((abs(v) for v in (sk8_r, sk8_f) if np.isfinite(v)), default=float("nan")),
        q8_q2=max((abs(v) for v in (sk82_r, sk82_f) if np.isfinite(v)), default=float("nan")),
        max_abs_interstage=max_sk,
        pn_skew=pn_skew,
    )
    row["delay_ps"] = dict(clk_to_q8_r=clk_to_q8_r, clk_to_q8_f=clk_to_q8_f)
    row["func_ok"] = bool(ok and row["counter"]["counting"])
    row["ok"] = bool(row["func_ok"] and np.isfinite(max_sk) and max_sk <= 35.0)
    return row


def run_batch(camp: Path, jobs_spec: list[dict], workers: int) -> list[dict]:
    jobs, meta = [], []
    for sp in jobs_spec:
        name = sp["name"]
        c = sp["cond"]
        rc = sp["rc"]
        stop_ns = sp.get("stop_ns", 30.0)
        skip_ns = sp.get("skip_ns", 11.0)
        start_s = sp.get("start_s", 14e-9)
        t_end = stop_ns * 1e-9
        prev = spice.case_output(camp, name, "waveforms", t_end=t_end)
        if prev is None:
            dk = _make_deck(
                c, rc, sp["dut_spice"], sp["subckt"], sp["extra_inc"],
                freq=sp.get("freq", 2.0e9),
                stop_ns=stop_ns, skip_ns=skip_ns,
                driver_spice=sp.get("driver_spice", R5_PEX),
                vdiv_delta=sp.get("vdiv_delta", 0.0),
                vdiv_ripple_amp=sp.get("vdiv_ripple_amp", 0.0),
                vdiv_ripple_hz=sp.get("vdiv_ripple_hz", 20e6),
            )
            jobs.append((dk, spice.next_run_dir(camp, name), dict(timeout_s=360, meta=dict(name=name))))
        meta.append((sp, t_end, start_s))
    if jobs:
        for ex in spice.run_many(jobs, workers=workers):
            if not ex.ok:
                print(f"  [SIM_ERR] {ex.run_dir}: {ex.log_failures}", flush=True)
    rows = []
    for sp, t_end, start_s in meta:
        wp = spice.case_output(camp, sp["name"], "waveforms", t_end=t_end)
        if wp is None:
            rows.append(dict(name=sp["name"], arch=sp["arch"], condition=sp["cond"].tag, ok=False, func_ok=False, error="sim_failed"))
            continue
        r = eval_wave(wp, sp["cond"], sp.get("freq", 2.0e9), start_s, vdiv_delta=sp.get("vdiv_delta", 0.0))
        r["name"] = sp["name"]
        r["arch"] = sp["arch"]
        r["rc"] = sp["rc"]
        r["vdiv_delta_mv"] = sp.get("vdiv_delta", 0.0) * 1e3
        rows.append(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["corners", "freq_shmoo", "phase_kd", "ripple_kd", "45corners", "mc", "postlayout"], required=True)
    ap.add_argument("--archs", nargs="+", default=["cmos_ripple", "cmos_sync_s4", "tspc9_reclock", "saff_reclock"])
    ap.add_argument("--resume", type=Path, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--cpex", type=Path, default=None)
    ap.add_argument("--rcx", type=Path, default=None)
    ap.add_argument("--subckt", type=str, default="pll_saff_reclock_prescaler8_2g_pdk")
    args = ap.parse_args()

    camp = args.resume.resolve() if args.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)

    if args.stage == "corners":
        sub = camp / "corners"
        sub.mkdir(parents=True, exist_ok=True)
        specs = []
        for a in args.archs:
            dut_sp, subckt, extra = ARCHS[a]
            for tag, rc in HARD9:
                specs.append(dict(
                    name=f"{a}__{tag}_{rc}", arch=a, cond=corners.Condition.parse(tag), rc=rc,
                    dut_spice=dut_sp, subckt=subckt, extra_inc=extra,
                ))
        rows = run_batch(sub, specs, args.workers)
        save_analysis(sub, dict(stage="corners", rows=rows))
        for a in args.archs:
            ar = [r for r in rows if r["arch"] == a]
            f_ok = sum(1 for r in ar if r.get("func_ok"))
            s_ok = sum(1 for r in ar if r.get("ok"))
            print(f"\n=== {a} ({s_ok}/{len(ar)} PASS, {f_ok}/{len(ar)} FUNC_OK) ===")
            for r in ar:
                if "error" in r:
                    print(f"  {r['condition']:16s} ERROR")
                    continue
                sk = r["skew_ps"]
                pn = sk["pn_skew"]
                fd = lambda v: f"{v:.3f}" if isinstance(v, (int, float)) else "NO"
                print(
                    f"  {r['condition']:15s} {'PASS' if r['ok'] else ('FUNC' if r['func_ok'] else 'FAIL'):4s} "
                    f"bad={r['counter']['bad_steps']:2d} | sk(42/84/82)={sk['q4_q2']:5.1f}/{sk['q8_q4']:5.1f}/{sk['q8_q2']:5.1f}ps | "
                    f"pn={pn['q2']:4.1f}/{pn['q4']:4.1f}/{pn['q8']:4.1f}ps | "
                    f"duty={fd(r['q2']['duty'])}/{fd(r['q4']['duty'])}/{fd(r['q8']['duty'])} | "
                    f"P={r['pdiv_mw']:.2f}mW"
                )

    elif args.stage == "freq_shmoo":
        sub = camp / "freq_shmoo"
        sub.mkdir(parents=True, exist_ok=True)
        specs = []
        shmoo_pts = [
            ("ss_v1650_t-40", "hh", 0.25e9, None, 100.0, 20.0, 28e-9),
            ("ss_v1650_t-40", "hh", 0.50e9, None, 60.0, 12.0, 16e-9),
            ("ss_v1650_t-40", "hh", 1.00e9, None, 40.0, 10.0, 14e-9),
            ("ss_v1650_t-40", "hh", 2.00e9, None, 28.0, 10.0, 13e-9),
            ("ss_v1650_t-40", "hh", 2.50e9, None, 28.0, 10.0, 13e-9),
            ("ss_v1650_t-40", "hh", 2.80e9, None, 28.0, 10.0, 13e-9),
            ("ss_v1650_t-40", "hh", 3.20e9, None, 28.0, 10.0, 13e-9),
            ("ff_v1950_t85", "ll", 0.10e9, None, 200.0, 30.0, 40e-9),
            ("ff_v1950_t85", "ll", 0.25e9, None, 100.0, 20.0, 28e-9),
            ("ss_v1650_t-40", "hh", 1.00e9, R5_PEX, 48.0, 11.0, 15e-9),
            ("ss_v1650_t-40", "hh", 2.25e9, R5_PEX, 30.0, 11.0, 14e-9),
            ("ss_v1650_t-40", "hh", 2.50e9, R5_PEX, 30.0, 11.0, 14e-9),
        ]
        for a in args.archs:
            dut_sp, subckt, extra = ARCHS[a]
            for tag, rc, f, drv, stop_ns, skip_ns, start_s in shmoo_pts:
                dlbl = "r5" if drv is not None else "id"
                specs.append(dict(
                    name=f"{a}__{tag}_{dlbl}_{f/1e9:.2f}G", arch=a, cond=corners.Condition.parse(tag), rc=rc,
                    dut_spice=dut_sp, subckt=subckt, extra_inc=extra, freq=f, driver_spice=drv,
                    stop_ns=stop_ns, skip_ns=skip_ns, start_s=start_s,
                ))
        rows = run_batch(sub, specs, args.workers)
        save_analysis(sub, dict(stage="freq_shmoo", rows=rows))
        for a in args.archs:
            print(f"\n=== FREQ SHMOO: {a} ===")
            for r in [x for x in rows if x["arch"] == a]:
                if "error" in r:
                    print(f"  {r['name']:42s} ERROR")
                    continue
                sk = r["skew_ps"]
                print(
                    f"  {r['name']:42s} {'PASS' if r['ok'] else ('FUNC' if r['func_ok'] else 'FAIL'):4s} "
                    f"bad={r['counter']['bad_steps']:2d} max_sk={sk['max_abs_interstage']:5.1f}ps "
                    f"q2={r['q2']['duty']} q8={r['q8']['duty']} P={r['pdiv_mw']:.2f}mW"
                )

    elif args.stage == "phase_kd":
        sub = camp / "phase_kd"
        sub.mkdir(parents=True, exist_ok=True)
        kd_corners = [
            ("tt_v1800_t27", "tt"),
            ("ss_v1650_t-40", "hh"),
            ("fs_v1650_t85", "hh"),
            ("sf_v1650_t-40", "ll"),
        ]
        specs = []
        for a in args.archs:
            dut_sp, subckt, extra = ARCHS[a]
            for tag, rc in kd_corners:
                for dv in (-0.015, +0.015):
                    specs.append(dict(
                        name=f"{a}__{tag}_{rc}_{'m15' if dv < 0 else 'p15'}", arch=a,
                        cond=corners.Condition.parse(tag), rc=rc,
                        dut_spice=dut_sp, subckt=subckt, extra_inc=extra,
                        driver_spice=None, vdiv_delta=dv,
                    ))
        rows = run_batch(sub, specs, args.workers)
        kd_summary = []
        for a in args.archs:
            print(f"\n=== SUPPLY SENSITIVITY Kd (div VDD +-15 mV, ideal clk): {a} ===")
            for tag, rc in kd_corners:
                rm = next(r for r in rows if r["name"] == f"{a}__{tag}_{rc}_m15")
                rp = next(r for r in rows if r["name"] == f"{a}__{tag}_{rc}_p15")
                if not (rm.get("func_ok") and rp.get("func_ok")):
                    print(f"  {tag:16s} INCOMPLETE")
                    continue
                # Unwrap modulo 500 ps
                dr = (rp["delay_ps"]["clk_to_q8_r"] - rm["delay_ps"]["clk_to_q8_r"] + 250.0) % 500.0 - 250.0
                df = (rp["delay_ps"]["clk_to_q8_f"] - rm["delay_ps"]["clk_to_q8_f"] + 250.0) % 500.0 - 250.0
                kd_r = dr / 30.0
                kd_f = df / 30.0
                kd_avg = 0.5 * (kd_r + kd_f)
                kd_summary.append(dict(arch=a, corner=tag, kd_r=kd_r, kd_f=kd_f, kd_avg=kd_avg,
                                       t_m15=rm["delay_ps"]["clk_to_q8_r"], t_p15=rp["delay_ps"]["clk_to_q8_r"]))
                print(f"  {tag:16s} Kd_rise={kd_r:+6.3f} ps/mV | Kd_fall={kd_f:+6.3f} ps/mV | Kd_avg={kd_avg:+6.3f} ps/mV")
        save_analysis(sub, dict(stage="phase_kd", kd_summary=kd_summary, rows=rows))

    elif args.stage == "45corners":
        for a in args.archs:
            sub = camp / f"pvt45_{a}"
            sub.mkdir(parents=True, exist_ok=True)
            dut_sp, subckt, extra = ARCHS[a]
            specs = []
            for c in corners.boundary_first(corners.grid45()):
                rc = "hh" if c.process in ("ss", "fs") else ("ll" if c.process in ("ff", "sf") else "tt")
                specs.append(dict(
                    name=f"{c.tag}_{rc}", arch=a, cond=c, rc=rc,
                    dut_spice=dut_sp, subckt=subckt, extra_inc=extra,
                ))
            rows = run_batch(sub, specs, args.workers)
            passed = sum(1 for r in rows if r.get("ok"))
            max_sk = max((r["skew_ps"]["max_abs_interstage"] for r in rows if "skew_ps" in r), default=float("nan"))
            max_pn = max((max(r["skew_ps"]["pn_skew"].values()) for r in rows if "skew_ps" in r), default=float("nan"))
            d2 = [r["q2"]["duty"] for r in rows if "q2" in r and r["q2"]["duty"] is not None] + [r["q2n"]["duty"] for r in rows if "q2n" in r and r["q2n"]["duty"] is not None]
            d4 = [r["q4"]["duty"] for r in rows if "q4" in r and r["q4"]["duty"] is not None]
            d8 = [r["q8"]["duty"] for r in rows if "q8" in r and r["q8"]["duty"] is not None]
            pw = [r["pdiv_mw"] for r in rows if "pdiv_mw" in r]
            summ = dict(
                arch=a, passed=passed, total=len(rows), max_skew_ps=max_sk, max_pn_skew_ps=max_pn,
                q2_duty=[min(d2), max(d2)] if d2 else None,
                q4_duty=[min(d4), max(d4)] if d4 else None,
                q8_duty=[min(d8), max(d8)] if d8 else None,
                power_mw=[min(pw), max(pw)] if pw else None,
                rows=rows,
            )
            save_analysis(sub, summ)
            print(
                f"[45corners:{a}] {passed}/{len(rows)} PASS | max_sk={max_sk:.2f} ps | max_pn={max_pn:.2f} ps | "
                f"q2={summ['q2_duty']} q4={summ['q4_duty']} q8={summ['q8_duty']} | P={summ['power_mw']} mW",
                flush=True,
            )

    elif args.stage == "mc":
        for a in args.archs:
            sub = camp / f"mc_{a}"
            sub.mkdir(parents=True, exist_ok=True)
            dut_sp, subckt, extra = ARCHS[a]
            mc_workers = min(args.workers, 3)
            recs = []
            for lib_sec, rc, vpp in [("ss_v1650_t-40_mm", "hh", 0.30), ("fs_v1650_t85_mm", "hh", 0.30)]:
                base_tag = lib_sec.removesuffix("_mm")
                c = corners.Condition.parse(base_tag)
                cv = spice.corner_values(c)
                vmid = c.supply / 2.0
                cdir = sub / lib_sec
                cdir.mkdir(parents=True, exist_ok=True)
                net = "\n".join([
                    f"{subckt} MC {lib_sec}",
                    *_header(c.process, dut_sp, extra, R5_PEX),
                    f".param supply={cv['SUPPLY']} input_pp={vpp} freq=2e9",
                    "Vdd vdd 0 PWL(0 0 0.5n {supply})",
                    "Vrx vrx 0 PWL(0 0 0.5n {supply})",
                    "Vdiv vdiv 0 PWL(0 0 0.5n {supply})",
                    "Vreference vref 0 PWL(0 0 0.5n {supply})",
                    "Iref vref vbias .85m",
                    "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
                    "Vp sp 0 SIN({supply-.15} {input_pp/4} {freq})",
                    "Vn sn 0 SIN({supply-.15} {-input_pp/4} {freq})",
                    "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
                    "Cpre_p bp 0 45f", "Cpre_n bn 0 45f",
                    "Xrx bp bn clkp clkn vbias vrx 0 serdes_cml_to_cmos_r5_pdk",
                    f"Xdiv clkp clkn q2p q2n q4p q4n q8p q8n vdiv 0 {subckt}",
                    "Cq2p q2p 0 15f", "Cq2n q2n 0 15f",
                    "Cq4p q4p 0 15f", "Cq4n q4n 0 15f",
                    "Cq8p q8p 0 20f", "Cq8n q8n 0 20f",
                    f".temp {cv['TEMP_C']}",
                    ".options reltol=1e-4 abstol=1p vntol=1u klu",
                ])
                net = bias.section(net, c.process, rc)
                net = re.sub(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: f"{m[1]}{m[2]}_mm", net, count=1, flags=re.M | re.I)
                net = freeze_includes(net, cdir)
                lets = {
                    "q2r1": "m_q2r1", "q2f1": "m_q2f1", "q2r2": "m_q2r2",
                    "q2nr1": "m_q2nr1", "q2nf1": "m_q2nf1", "q2nr2": "m_q2nr2",
                    "q4r1": "m_q4r1", "q4f1": "m_q4f1", "q4r2": "m_q4r2",
                    "q8r1": "m_q8r1", "q8f1": "m_q8f1", "q8r2": "m_q8r2",
                    "sk2": "m_sk2", "sk4": "m_sk4", "sk8": "m_sk8",
                }
                ana = "\n".join([
                    *[f"let {k} = -1e30" for k in lets],
                    "tran 2p 24n 0 2p uic",
                    "let dq2 = v(q2p) - v(q2n)",
                    "let dq4 = v(q4p) - v(q4n)",
                    "let dq8 = v(q8p) - v(q8n)",
                    f"meas tran m_q2r1 when v(q2p)={vmid:.4f} rise=1 td=14n",
                    f"meas tran m_q2f1 when v(q2p)={vmid:.4f} fall=1 td=14n",
                    f"meas tran m_q2r2 when v(q2p)={vmid:.4f} rise=2 td=14n",
                    f"meas tran m_q2nr1 when v(q2n)={vmid:.4f} rise=1 td=14n",
                    f"meas tran m_q2nf1 when v(q2n)={vmid:.4f} fall=1 td=14n",
                    f"meas tran m_q2nr2 when v(q2n)={vmid:.4f} rise=2 td=14n",
                    f"meas tran m_q4r1 when v(q4p)={vmid:.4f} rise=1 td=14n",
                    f"meas tran m_q4f1 when v(q4p)={vmid:.4f} fall=1 td=14n",
                    f"meas tran m_q4r2 when v(q4p)={vmid:.4f} rise=2 td=14n",
                    f"meas tran m_q8r1 when v(q8p)={vmid:.4f} rise=1 td=14n",
                    f"meas tran m_q8f1 when v(q8p)={vmid:.4f} fall=1 td=14n",
                    f"meas tran m_q8r2 when v(q8p)={vmid:.4f} rise=2 td=14n",
                    "meas tran m_sk2 when dq2=0 cross=1 td=14n",
                    "meas tran m_sk4 when dq4=0 cross=1 td=14n",
                    "meas tran m_sk8 when dq8=0 cross=1 td=14n",
                ])
                jobs = []
                for idx, ch_seed, ch_n in mc.chunks(args.samples, seed=2026, per=8):
                    dk = mc.deck(net, samples=ch_n, seed=ch_seed, analysis=ana, lets=lets, t_end=24e-9)
                    jobs.append((dk, cdir / f"ch_{idx:02d}", dict(meta=dict(tag=lib_sec, chunk=idx, seed=ch_seed))))
                dirs = mc.run_many(jobs, workers=mc_workers)
                rows = mc.read_all(dirs)
                d2p, d2n, d4p, d8p, sk4_ps, sk8_ps = [], [], [], [], [], []
                pass_all = 0
                for row in rows:
                    vals = [row[k] for k in lets]
                    if np.isnan(vals).any() or min(vals) < 0:
                        continue
                    p2 = row["q2r2"] - row["q2r1"]
                    p2n = row["q2nr2"] - row["q2nr1"]
                    p4 = row["q4r2"] - row["q4r1"]
                    p8 = row["q8r2"] - row["q8r1"]
                    if not (900e-12 <= p2 <= 1100e-12 and 900e-12 <= p2n <= 1100e-12
                            and 1850e-12 <= p4 <= 2150e-12 and 3700e-12 <= p8 <= 4300e-12):
                        continue
                    dp2 = ((row["q2f1"] - row["q2r1"]) % p2) / p2
                    dn2 = ((row["q2nf1"] - row["q2nr1"]) % p2n) / p2n
                    dp4 = ((row["q4f1"] - row["q4r1"]) % p4) / p4
                    dp8 = ((row["q8f1"] - row["q8r1"]) % p8) / p8
                    e4 = ((row["sk4"] - row["sk2"] + 250e-12) % 500e-12 - 250e-12) * 1e12
                    e8 = ((row["sk8"] - row["sk2"] + 250e-12) % 500e-12 - 250e-12) * 1e12
                    d2p.append(dp2); d2n.append(dn2); d4p.append(dp4); d8p.append(dp8)
                    sk4_ps.append(e4); sk8_ps.append(e8)
                    if (0.45 <= dp2 <= 0.55 and 0.45 <= dn2 <= 0.55
                            and 0.45 <= dp4 <= 0.55 and 0.45 <= dp8 <= 0.55
                            and abs(e4) <= 35.0 and abs(e8) <= 35.0):
                        pass_all += 1
                lo_ci, hi_ci = stats.yield_ci(pass_all, len(rows))
                rec = dict(
                    arch=a, corner_mm=lib_sec, samples=len(rows), toggle=len(d2p), pass_all=pass_all,
                    yield_ci95=[lo_ci, hi_ci],
                    d2p=stats.summary(d2p) if d2p else None,
                    d2n=stats.summary(d2n) if d2n else None,
                    d4p=stats.summary(d4p) if d4p else None,
                    d8p=stats.summary(d8p) if d8p else None,
                    sk4_ps=stats.summary(sk4_ps) if sk4_ps else None,
                    sk8_ps=stats.summary(sk8_ps) if sk8_ps else None,
                )
                recs.append(rec)
                print(
                    f"[mc:{a}] {lib_sec:18s} toggle={len(d2p)}/{len(rows)} pass={pass_all}/{len(rows)} "
                    f"CI95=[{lo_ci:.4f},{hi_ci:.4f}] sk4={rec['sk4_ps']} sk8={rec['sk8_ps']}",
                    flush=True,
                )
            save_analysis(sub, dict(stage="mc", arch=a, rows=recs))

    elif args.stage == "ripple_kd":
        # Dynamic 20 MHz +-20 mV host-rail supply ripple -> peak-to-peak phase modulation on q8 (50 ns window = 1 full 20 MHz cycle)
        sub = camp / "ripple_kd"
        sub.mkdir(parents=True, exist_ok=True)
        kd_corners = [("tt_v1800_t27", "tt"), ("ss_v1650_t-40", "hh"), ("fs_v1650_t85", "hh")]
        specs = []
        for a in args.archs:
            dut_sp, subckt, extra = ARCHS[a]
            for tag, rc in kd_corners:
                specs.append(dict(
                    name=f"{a}__{tag}_{rc}_rip20m", arch=a, cond=corners.Condition.parse(tag), rc=rc,
                    dut_spice=dut_sp, subckt=subckt, extra_inc=extra,
                    driver_spice=None, vdiv_ripple_amp=0.020, vdiv_ripple_hz=20e6,
                    stop_ns=65.0, skip_ns=12.0, start_s=14e-9,
                ))
        rows = run_batch(sub, specs, args.workers)
        rip_summary = []
        for sp in specs:
            wp = spice.case_output(sub, sp["name"], "waveforms", t_end=65e-9)
            if wp is None:
                continue
            w = spice.Waves(wp)
            t = w.t
            q8d = w["v(q8p)"] - w["v(q8n)"]
            ckd = w["v(clkp)"] - w["v(clkn)"]
            q8r = clock.edges(t, q8d, +1, 14e-9, 64e-9)
            ckr = clock.edges(t, ckd, +1, 13.5e-9, 64.5e-9)
            if len(q8r) < 6 or len(ckr) < 20:
                continue
            # Unwrap q8 rising edge delay relative to ideal 4.000 ns period grid (since ideal 2 GHz clock is exact!)
            idx = np.round((q8r - q8r[0]) / 4e-9)
            phi_ps = (q8r - q8r[0] - idx * 4e-9) * 1e12
            phi_pp = float(phi_ps.max() - phi_ps.min())
            kd_dyn = phi_pp / 40.0  # ps per mV (40 mVpp ripple)
            rec = dict(arch=sp["arch"], corner=sp["cond"].tag, phi_pp_ps=phi_pp, kd_dyn_ps_per_mv=kd_dyn, edges=len(q8r))
            rip_summary.append(rec)
            print(f"[ripple_kd 20MHz 40mVpp] {sp['arch']:15s} {sp['cond'].tag:15s} | phi_pp={phi_pp:5.2f} ps | Kd_dyn={kd_dyn:.3f} ps/mV", flush=True)
        save_analysis(sub, dict(stage="ripple_kd", summary=rip_summary, rows=rows))

    elif args.stage == "postlayout":
        if args.cpex is None or args.rcx is None:
            raise ValueError("--cpex and --rcx required for postlayout")
        sub = camp / "postlayout"
        sub.mkdir(parents=True, exist_ok=True)
        chain7 = [
            ("tt_v1800_t27", "tt"),
            ("fs_v1650_t85", "hh"),
            ("sf_v1650_t-40", "ll"),
            ("ff_v1950_t85", "ll"),
            ("ss_v1650_t-40", "hh"),
            ("ss_v1800_t85", "hh"),
            ("ss_v1650_t85", "hh"),
        ]
        specs = []
        for mode, sp_file, drv in [
            ("cpex", args.cpex.resolve(), R5_PEX),
            ("rcx", args.rcx.resolve(), R5_PEX),
            ("rcxboth", args.rcx.resolve(), R5_RCX),
        ]:
            pts = chain7 if mode != "rcxboth" else chain7[:5]
            for tag, rc in pts:
                specs.append(dict(
                    name=f"{mode}__{tag}_{rc}", arch=mode, cond=corners.Condition.parse(tag), rc=rc,
                    dut_spice=sp_file, subckt=args.subckt, extra_inc=[], driver_spice=drv,
                ))
        rows = run_batch(sub, specs, args.workers)
        save_analysis(sub, dict(stage="postlayout", cpex=str(args.cpex), rcx=str(args.rcx), rows=rows))
        for mode in ("cpex", "rcx", "rcxboth"):
            mr = [r for r in rows if r["arch"] == mode]
            ok_n = sum(1 for r in mr if r.get("ok"))
            print(f"\n=== POSTLAYOUT {mode.upper()} ({ok_n}/{len(mr)} PASS) ===")
            for r in mr:
                if "error" in r:
                    print(f"  {r['condition']:15s} ERROR")
                    continue
                sk = r["skew_ps"]; pn = sk["pn_skew"]
                fd = lambda v: f"{v:.3f}" if isinstance(v, (int, float)) else "NO"
                print(
                    f"  {r['condition']:15s} {'PASS' if r['ok'] else ('FUNC' if r['func_ok'] else 'FAIL'):4s} "
                    f"bad={r['counter']['bad_steps']:2d} | sk(42/84/82)={sk['q4_q2']:5.1f}/{sk['q8_q4']:5.1f}/{sk['q8_q2']:5.1f}ps | "
                    f"pn={pn['q2']:4.1f}/{pn['q4']:4.1f}/{pn['q8']:4.1f}ps | "
                    f"duty={fd(r['q2']['duty'])}/{fd(r['q4']['duty'])}/{fd(r['q8']['duty'])} | P={r['pdiv_mw']:.2f}mW"
                )


if __name__ == "__main__":
    main()
