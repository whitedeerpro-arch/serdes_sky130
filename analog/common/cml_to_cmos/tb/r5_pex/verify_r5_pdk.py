#!/usr/bin/env python3
"""Post-layout electrical verification for serdes_cml_to_cmos_r5_pdk.

Stages:
  6corners   : CPEX vs unmodified Magic RCX across 6 extreme corners (input_pp=0.3) + plot
  45corners  : Full 45-corner PVT (grid45, boundary_first) on CPEX (input_pp=0.3)
  mc         : 200-sample PEX mismatch MC on tt_v1800_t27_mm & ss_v1650_t-40_mm (input_pp=0.4)
  chain_div8 : 7 extreme corners CPEX r5_pdk -> CPEX pll_cmos_prescaler8_2g_pdk (input_pp=0.3) + plot
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import bias, clock, corners, mc, spice, stats, watch
from serdes_flow.project import ROOT

sys.path.insert(0, str(ROOT / "verification/layout"))
from review_sim import freeze_includes, save_analysis

MODEL_LIB = spice.corner_values(corners.Condition.parse("tt_v1800_t27"))["MODEL_LIBRARY"]

PEX_DIR = ROOT / "analog/common/cml_to_cmos/layout/variants/r5_pdk"
REV_DIR = ROOT / "results/layout_review/cml_to_cmos_r5_20261117T1448Z"
PEX_SPICE = PEX_DIR / "serdes_cml_to_cmos_r5_pdk_pex.spice"
RCX_SPICE = REV_DIR / "serdes_cml_to_cmos_r5_pdk_rcx.spice"
DIV_PEX_SPICE = ROOT / "analog/pll/divider/layout/variants/cmos_2g_pdk/pll_cmos_prescaler8_2g_pdk_pex.spice"

EXTREME6 = [
    corners.Condition.parse("tt_v1800_t27"),
    corners.Condition.parse("ss_v1650_t-40"),
    corners.Condition.parse("fs_v1650_t85"),
    corners.Condition.parse("sf_v1650_t-40"),
    corners.Condition.parse("ff_v1950_t85"),
    corners.Condition.parse("ss_v1650_t85"),
]

CHAIN7 = [
    ("tt_v1800_t27", "tt"),
    ("fs_v1650_t85", "hh"),
    ("sf_v1650_t-40", "ll"),
    ("ff_v1950_t85", "ll"),
    ("ss_v1650_t-40", "hh"),
    ("ss_v1800_t85", "hh"),
    ("ss_v1650_t85", "hh"),
]


def frozen_deck(deck: str, campaign: Path, name: str) -> str:
    """Refuse legacy mutable includes and changed inputs before any reuse."""
    receipt = campaign / "identity.json"
    if not receipt.exists() and any(campaign.rglob("execution.json")):
        raise ValueError("Legacy campaign has no frozen identity; use a new campaign")
    deck = freeze_includes(deck, campaign)
    identity = json.loads(receipt.read_text()) if receipt.exists() else {}
    digest = hashlib.sha256(deck.encode()).hexdigest()
    if name in identity and identity[name] != digest:
        raise ValueError("Campaign inputs changed; use a new campaign")
    identity[name] = digest
    receipt.write_text(json.dumps(identity, indent=2) + "\n")
    return deck


def plot_path(campaign: Path, name: str) -> Path:
    directory = campaign / "plots" / str(time.time_ns())
    directory.mkdir(parents=True, exist_ok=False)
    return directory / name


def validate_rc_source():
    inputs = json.loads((REV_DIR / "inputs.json").read_text())
    for name, item in inputs.items():
        source = PEX_DIR / (name if name.endswith(".mag") else "serdes_cml_to_cmos_r5_pdk_ref.spice")
        if hashlib.sha256(source.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("RC geometry/reference changed; prepare a matching extraction")
    rc = json.loads((REV_DIR / "rc_summary.json").read_text())
    if hashlib.sha256(RCX_SPICE.read_bytes()).hexdigest() != rc["rcx_sha256"]:
        raise ValueError("RCX snapshot changed")
    original_cpex = REV_DIR / PEX_SPICE.name
    if hashlib.sha256(original_cpex.read_bytes()).hexdigest() != rc["cpex_sha256"]:
        raise ValueError("Original CPEX snapshot changed")

    def cards(path):
        rows = [line.split() for line in path.read_text().splitlines()
                if line.strip() and not line.lstrip().startswith("*")]
        return sorted(("C", *sorted(r[1:3]), r[3]) if r[0].startswith("C") else tuple(r) for r in rows)

    # Magic may renumber/reverse C cards without changing the coupled matrix.
    if cards(PEX_SPICE) != cards(original_cpex):
        raise ValueError("CPEX changed relative to the RC extraction")


def logic_metrics(t, signal, supply, expected_hz, start):
    ps = clock.period_stats(t, signal - supply / 2, start, min_cycles=3)
    selected = signal[t >= start]
    rises = clock.edges(t, signal - supply / 2, start=start)
    missing_or_extra = int(np.count_nonzero(np.abs(np.diff(rises) * expected_hz - 1) > .2))
    lo, hi = float(selected.min()), float(selected.max())
    good = bool(ps and abs(ps["frequency_hz"] / expected_hz - 1) < .01
                and ps["duty"] is not None and .45 <= ps["duty"] <= .55
                and lo < .2 * supply and hi > .8 * supply and missing_or_extra == 0)
    return dict(ok=good, freq_ghz=ps["frequency_hz"] / 1e9 if ps else None,
                duty=ps["duty"] if ps else None, low=lo, high=hi,
                missing_or_extra_periods=missing_or_extra)


def _header(lib_sec: str, dut_spice: Path, extra_spice: Path | None = None) -> list[str]:
    lines = [
        f'.lib "{MODEL_LIB}" {lib_sec}',
        f'.include "{ROOT / "analog/common/devices/spice/sky130_primitives.spice"}"',
        f'.include "{ROOT / "analog/common/cml_buffer/spice/cml_delay_resistive.spice"}"',
        f'.include "{ROOT / "analog/common/cml_buffer/spice/cml_buffer.spice"}"',
        f'.include "{ROOT / "analog/pll/divider/spice/cml_latch.spice"}"',
        f'.include "{ROOT / "analog/pll/divider/spice/cml_div2.spice"}"',
        f'.include "{ROOT / "analog/pll/divider/spice/cml_prescaler8.spice"}"',
        f'.include "{dut_spice}"',
    ]
    if extra_spice is not None:
        lines.append(f'.include "{extra_spice}"')
    return lines


def _rx_deck(c: corners.Condition, dut_spice: Path, *, input_pp: float = 0.3,
             stop: str = "18n", skip_before: str = "11n", save_extra: str = "") -> str:
    cv = spice.corner_values(c)
    lines = [
        f"r5_pdk fullrate {c.tag}",
        *_header(cv["CORNER"], dut_spice),
        f".param supply={cv['SUPPLY']} input_pp={input_pp}",
        "Vdd vdd 0 {supply}",
        "Vrx vrx 0 {supply}",
        "Vreference vref 0 {supply}",
        "Iref vref vbias .85m",
        "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
        "Vp sp 0 SIN({supply-.15} {input_pp/4} 2e9)",
        "Vn sn 0 SIN({supply-.15} {-input_pp/4} 2e9)",
        "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
        "Xpre bp bn d2p d2n d4p d4n d8p d8n vbias vdd 0 pll_cml_prescaler8",
        "Xrx bp bn outp outn vbias vrx 0 serdes_cml_to_cmos_r5_pdk",
        "Cop outp 0 20f",
        "Con outn 0 20f",
        f".temp {cv['TEMP_C']}",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ".control",
        "set num_threads=1",
        "set wr_singlescale",
        "set wr_vecnames",
        f"tran 2p {stop} 0 2p",
        "let prx=-v(vrx)*i(Vrx)",
        "let din=v(bp)-v(bn)",
        f"wrdata waveforms.tsv din v(outp) v(outn) prx {save_extra}".strip(),
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return spice.skip_output_before(spice.binary_output("\n".join(lines)), skip_before)


def _eval_rx_wave(wave_path: Path, c: corners.Condition, start_s: float = 12e-9) -> dict:
    w = spice.Waves(wave_path)
    t, m = w.t, w.t >= start_s
    res = dict(
        condition=c.tag,
        input_pp_v=float(np.ptp(w["din"][m])),
        power_mw=float(np.mean(w["prx"][m]) * 1e3),
    )
    ok = True
    duties = {}
    for out in ("v(outp)", "v(outn)"):
        sig = w[out]
        ps = clock.period_stats(t, sig - c.supply / 2.0, start_s)
        lo, hi = float(sig[m].min()), float(sig[m].max())
        good = bool(
            ps
            and abs(ps["frequency_hz"] / 2e9 - 1.0) < 0.01
            and 0.45 <= ps["duty"] <= 0.55
            and lo < 0.2 * c.supply
            and hi > 0.8 * c.supply
        )
        res[out] = dict(
            ok=good,
            freq_ghz=(ps["frequency_hz"] / 1e9 if ps else None),
            duty=(ps["duty"] if ps else None),
            low=lo,
            high=hi,
        )
        duties[out] = ps["duty"] if ps else None
        ok &= good
    # Differential phase error / crossing skew between outp rise and outn fall
    ep_r = clock.edges(t, w["v(outp)"] - c.supply / 2.0, polarity=+1, start=start_s)
    en_f = clock.edges(t, w["v(outn)"] - c.supply / 2.0, polarity=-1, start=start_s)
    if len(ep_r) and len(en_f):
        diffs = np.array([en_f[np.argmin(np.abs(en_f - tr))] - tr for tr in ep_r]) * 1e12
        res["skew_ps"] = float(np.mean(diffs))
    else:
        res["skew_ps"] = None
    res["ok"] = ok
    return res


def run_6corners(camp: Path, workers: int) -> None:
    validate_rc_source()
    sub = camp / "6corners"
    sub.mkdir(parents=True, exist_ok=True)
    jobs, meta = [], []
    for kind, dut in (("cpex", PEX_SPICE), ("rcx", RCX_SPICE)):
        for c in EXTREME6:
            name = f"{kind}_{c.tag}"
            deck = _rx_deck(c, dut, input_pp=0.3, stop="22n", skip_before="11n")
            deck = frozen_deck(deck, sub, name)
            prev = spice.case_output(sub, name, "waveforms", t_end=22e-9)
            if prev is None:
                jobs.append((deck, spice.next_run_dir(sub, name), dict(meta=dict(kind=kind, condition=c.tag))))
            meta.append((kind, c, name))
    if jobs:
        for ex in spice.run_many(jobs, workers=workers):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    rows = []
    fig, axes = plt.subplots(len(EXTREME6), 2, figsize=(13, 12), sharex=True)
    for idx, c in enumerate(EXTREME6):
        for col, kind in enumerate(("cpex", "rcx")):
            name = f"{kind}_{c.tag}"
            wp = spice.case_output(sub, name, "waveforms", t_end=22e-9)
            assert wp is not None
            r = _eval_rx_wave(wp, c, start_s=12e-9)
            r["variant"] = kind
            rows.append(r)
            dp = r["v(outp)"]["duty"] or 0.0
            dn = r["v(outn)"]["duty"] or 0.0
            sk = r["skew_ps"] if r["skew_ps"] is not None else float("nan")
            print(
                f"[6corners] {kind:4s} {c.tag:14s} | {'PASS' if r['ok'] else 'FAIL'} | "
                f"in={r['input_pp_v']*1e3:.0f}mVpp | duty={dp:.4f}/{dn:.4f} | "
                f"skew={sk:+.2f}ps | P={r['power_mw']:.2f}mW",
                flush=True,
            )
            w = spice.Waves(wp)
            m = (w.t >= 18e-9) & (w.t <= 20e-9)
            ax = axes[idx, col]
            ax.plot((w.t[m] - 18e-9) * 1e9, w["v(outp)"][m], label="outp", lw=1.2)
            ax.plot((w.t[m] - 18e-9) * 1e9, w["v(outn)"][m], label="outn", lw=1.2, ls="--")
            ax.set_ylabel("V")
            ax.set_title(f"{kind.upper()} {c.tag} | dp={dp:.3f} skew={sk:+.1f}ps {'PASS' if r['ok'] else 'FAIL'}", fontsize=9)
            ax.grid(True, alpha=0.3)
            if idx == 0 and col == 0:
                ax.legend(fontsize=8)
    axes[-1, 0].set_xlabel("Time - 18 ns (ns)")
    axes[-1, 1].set_xlabel("Time - 18 ns (ns)")
    fig.suptitle("serdes_cml_to_cmos_r5_pdk: 6 Extreme Corners CPEX vs Magic RCX (input_pp=0.3 V)", fontsize=12)
    fig.tight_layout()
    plot = plot_path(camp, "waves_r5_pex_6corners.png")
    fig.savefig(plot, dpi=150)
    plt.close(fig)
    save_analysis(camp, dict(stage="6corners", rows=rows))
    print(f"Saved {plot}", flush=True)


def run_45corners(camp: Path, workers: int) -> None:
    sub = camp / "45corners"
    sub.mkdir(parents=True, exist_ok=True)
    conds = corners.boundary_first(corners.grid45())
    jobs, keys = [], []
    for c in conds:
        deck = _rx_deck(c, PEX_SPICE, input_pp=0.3, stop="18n", skip_before="11n")
        deck = frozen_deck(deck, sub, c.tag)
        prev = spice.case_output(sub, c.tag, "waveforms", t_end=18e-9)
        if prev is None:
            jobs.append((deck, spice.next_run_dir(sub, c.tag), dict(meta=dict(condition=c.tag))))
        keys.append(c)
    if jobs:
        for ex in spice.run_many(jobs, workers=workers):
            assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for c in keys:
        wp = spice.case_output(sub, c.tag, "waveforms", t_end=18e-9)
        assert wp is not None
        r = _eval_rx_wave(wp, c, start_s=12e-9)
        rows.append(r)
        dp = r["v(outp)"]["duty"] or 0.0
        dn = r["v(outn)"]["duty"] or 0.0
        sk = r["skew_ps"] if r["skew_ps"] is not None else float("nan")
        print(
            f"[45corners] {c.tag:14s} | {'PASS' if r['ok'] else 'FAIL'} | "
            f"in={r['input_pp_v']*1e3:.0f}mVpp | duty={dp:.4f}/{dn:.4f} | "
            f"skew={sk:+.2f}ps | P={r['power_mw']:.2f}mW",
            flush=True,
        )
    passed = sum(1 for r in rows if r["ok"])
    dps = [r[k]["duty"] for r in rows for k in ("v(outp)", "v(outn)") if r[k]["duty"] is not None]
    pws = [r["power_mw"] for r in rows]
    sks = [r["skew_ps"] for r in rows if r["skew_ps"] is not None]
    summary = {
        "total": len(rows),
        "passed": passed,
        "duty_range": [min(dps), max(dps)] if dps else None,
        "power_mw_range": [min(pws), max(pws)],
        "skew_ps_range": [min(sks), max(sks)] if sks else None,
        "rows": rows,
    }
    save_analysis(camp, dict(stage="45corners", **summary))
    print(f"45corners summary: {passed}/{len(rows)} PASS | duty={summary['duty_range']} | P={summary['power_mw_range']} mW", flush=True)


def run_mc(camp: Path, workers: int) -> None:
    sub = camp / "mc"
    sub.mkdir(parents=True, exist_ok=True)
    mc_workers = min(workers, 3)
    configs = [
        ("tt_v1800_t27_mm", corners.Condition.parse("tt_v1800_t27"), "tt_mm", 200, 0.4),
        ("ss_v1650_t-40_mm", corners.Condition.parse("ss_v1650_t-40"), "ss_mm", 200, 0.4),
    ]
    out_all = []
    for tag, c, lib_sec, n_samp, vpp in configs:
        cdir = sub / tag
        cdir.mkdir(parents=True, exist_ok=True)
        cv = spice.corner_values(c)
        vmid = c.supply / 2.0
        net = "\n".join([
            f"r5_pdk MC {tag}",
            *_header(lib_sec, PEX_SPICE),
            f".param supply={cv['SUPPLY']} input_pp={vpp}",
            "Vdd vdd 0 {supply}",
            "Vrx vrx 0 {supply}",
            "Vreference vref 0 {supply}",
            "Iref vref vbias .85m",
            "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
            "Vp sp 0 SIN({supply-.15} {input_pp/4} 2e9)",
            "Vn sn 0 SIN({supply-.15} {-input_pp/4} 2e9)",
            "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
            "Xpre bp bn d2p d2n d4p d4n d8p d8n vbias vdd 0 pll_cml_prescaler8",
            "Xrx bp bn outp outn vbias vrx 0 serdes_cml_to_cmos_r5_pdk",
            "Cop outp 0 20f",
            "Con outn 0 20f",
            f".temp {cv['TEMP_C']}",
            ".options reltol=1e-4 abstol=1p vntol=1u klu",
        ])
        net = frozen_deck(net, cdir, "mc_network")
        ana = "\n".join([
            "tran 2p 16n 0 2p",
            f"meas tran m_pr1 when v(outp)={vmid:.4f} rise=1 td=12n",
            f"meas tran m_pf1 when v(outp)={vmid:.4f} fall=1 td=12n",
            f"meas tran m_pr2 when v(outp)={vmid:.4f} rise=2 td=12n",
            f"meas tran m_nr1 when v(outn)={vmid:.4f} rise=1 td=12n",
            f"meas tran m_nf1 when v(outn)={vmid:.4f} fall=1 td=12n",
            f"meas tran m_nr2 when v(outn)={vmid:.4f} rise=2 td=12n",
        ])
        lets = {"pr1": "m_pr1", "pf1": "m_pf1", "pr2": "m_pr2", "nr1": "m_nr1", "nf1": "m_nf1", "nr2": "m_nr2"}
        jobs = []
        for idx, ch_seed, ch_n in mc.chunks(n_samp, seed=1000, per=8):
            dk = mc.deck(net, samples=ch_n, seed=ch_seed, analysis=ana, lets=lets, t_end=16e-9)
            jobs.append((dk, cdir / f"ch_{idx:02d}", dict(meta=dict(tag=tag, chunk=idx, seed=ch_seed))))
        dirs = mc.run_many(jobs, workers=mc_workers)
        rows = mc.read_all(dirs)
        if len(rows) != n_samp:
            raise ValueError(f"Incomplete MC: {len(rows)}/{n_samp}")
        dp_vals, dn_vals, sk_vals = [], [], []
        pass_duty = 0
        for row in rows:
            pr1, pf1, pr2 = row["pr1"], row["pf1"], row["pr2"]
            nr1, nf1, nr2 = row["nr1"], row["nf1"], row["nr2"]
            if np.isnan([pr1, pf1, pr2, nr1, nf1, nr2]).any():
                continue
            per_p, per_n = pr2 - pr1, nr2 - nr1
            if not (450e-12 <= per_p <= 550e-12 and 450e-12 <= per_n <= 550e-12):
                continue
            dp = ((pf1 - pr1) % per_p) / per_p
            dn = ((nf1 - nr1) % per_n) / per_n
            # crossing diff between outp_rise (pr1) and outn_fall (nf1)
            d_pn = ((nf1 - pr1 + per_p / 2.0) % per_p - per_p / 2.0) * 1e12
            dp_vals.append(dp)
            dn_vals.append(dn)
            sk_vals.append(d_pn)
            if 0.45 <= dp <= 0.55 and 0.45 <= dn <= 0.55:
                pass_duty += 1
        lo_ci, hi_ci = stats.yield_ci(pass_duty, len(rows))
        rec = {
            "tag": tag,
            "corner_mm": lib_sec,
            "input_pp_v": vpp,
            "samples": len(rows),
            "toggle": len(dp_vals),
            "pass_duty": pass_duty,
            "yield_ci95": [lo_ci, hi_ci],
            "duty_p_stats": stats.summary(dp_vals) if dp_vals else None,
            "duty_p_tol9973": list(stats.tolerance(dp_vals)) if len(dp_vals) > 2 else None,
            "duty_n_stats": stats.summary(dn_vals) if dn_vals else None,
            "duty_n_tol9973": list(stats.tolerance(dn_vals)) if len(dn_vals) > 2 else None,
            "skew_ps_stats": stats.summary(sk_vals) if sk_vals else None,
        }
        out_all.append(rec)
        print(
            f"[mc] {tag:18s} | toggle={len(dp_vals)}/{len(rows)} | pass_duty={pass_duty}/{len(rows)} "
            f"(CI95=[{lo_ci:.4f}, {hi_ci:.4f}]) | dp_stats={rec['duty_p_stats']} "
            f"| tol9973={rec['duty_p_tol9973']}",
            flush=True,
        )
    save_analysis(camp, dict(stage="mc", rows=out_all))


def run_chain_div8(camp: Path, workers: int) -> None:
    sub = camp / "chain_div8"
    sub.mkdir(parents=True, exist_ok=True)
    jobs, meta = [], []
    for tag, rc in CHAIN7:
        c = corners.Condition.parse(tag)
        cv = spice.corner_values(c)
        lines = [
            f"r5_pdk + cmos_2g_pdk {tag}:{rc}",
            *_header(cv["CORNER"], PEX_SPICE, DIV_PEX_SPICE),
            f".param supply={cv['SUPPLY']} input_pp=0.3",
            "Vdd vdd 0 {supply}",
            "Vrx vrx 0 {supply}",
            "Vdiv vdiv 0 {supply}",
            "Vreference vref 0 {supply}",
            "Iref vref vbias .85m",
            "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
            "Vp sp 0 SIN({supply-.15} {input_pp/4} 2e9)",
            "Vn sn 0 SIN({supply-.15} {-input_pp/4} 2e9)",
            "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
            "Xpre bp bn d2p d2n d4p d4n d8p d8n vbias vdd 0 pll_cml_prescaler8",
            "Xrx bp bn clkp clkn vbias vrx 0 serdes_cml_to_cmos_r5_pdk",
            "Xdiv clkp clkn q2p q2n q4p q4n q8p q8n vdiv 0 pll_cmos_prescaler8_2g_pdk",
            "Cq2p q2p 0 15f", "Cq2n q2n 0 15f",
            "Cq4p q4p 0 15f", "Cq4n q4n 0 15f",
            "Cq8p q8p 0 20f", "Cq8n q8n 0 20f",
            f".temp {cv['TEMP_C']}",
            ".options reltol=1e-4 abstol=1p vntol=1u klu",
            ".control",
            "set num_threads=1",
            "set wr_singlescale",
            "set wr_vecnames",
            "tran 2p 30n 0 2p",
            "let prx=-v(vrx)*i(Vrx)",
            "let pdiv=-v(vdiv)*i(Vdiv)",
            "wrdata waveforms.tsv v(clkp) v(clkn) v(q2p) v(q2n) v(q4p) v(q4n) v(q8p) v(q8n) prx pdiv",
            "quit",
            ".endc",
            ".end",
            "",
        ]
        deck = spice.skip_output_before(spice.binary_output("\n".join(lines)), "11n")
        deck = bias.section(deck, c.process, rc)
        name = f"{tag}"
        deck = frozen_deck(deck, sub, name)
        prev = spice.case_output(sub, name, "waveforms", t_end=30e-9)
        if prev is None:
            jobs.append((deck, spice.next_run_dir(sub, name), dict(meta=dict(condition=tag, rc=rc))))
        meta.append((c, rc, name))
    if jobs:
        for ex in spice.run_many(jobs, workers=workers):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    rows = []
    fig, axes = plt.subplots(len(meta), 1, figsize=(12, 11), sharex=True)
    for idx, (c, rc, name) in enumerate(meta):
        wp = spice.case_output(sub, name, "waveforms", t_end=30e-9)
        assert wp is not None
        w = spice.Waves(wp)
        t, m = w.t, w.t >= 14e-9
        ok = True
        r = dict(condition=c.tag, rc=rc, prx_mw=float(np.mean(w["prx"][m]) * 1e3), pdiv_mw=float(np.mean(w["pdiv"][m]) * 1e3))
        for lbl, exp_f in [("clk", 2e9), ("q2", 1e9), ("q4", .5e9), ("q8", .25e9)]:
            for side in ("p", "n"):
                key = lbl if side == "p" else lbl + "n"
                r[key] = logic_metrics(t, w[f"v({lbl}{side})"], c.supply, exp_f, 14e-9)
                ok &= r[key]["ok"]
        r["ok"] = ok
        rows.append(r)
        print(
            f"[chain_div8] {c.tag:14s}:{rc} | {'PASS' if ok else 'FAIL'} | "
            f"clk={(r['clk']['duty'] or 0):.3f} q2={(r['q2']['duty'] or 0):.3f} q4={(r['q4']['duty'] or 0):.3f} q8={(r['q8']['duty'] or 0):.3f} | "
            f"Prx={r['prx_mw']:.2f}mW Pdiv={r['pdiv_mw']:.2f}mW",
            flush=True,
        )
        m_p = (w.t >= 20e-9) & (w.t <= 28e-9)
        ax = axes[idx]
        ax.plot((w.t[m_p] - 20e-9) * 1e9, w["v(clkp)"][m_p], alpha=0.5, lw=0.8, label="clkp (2G)")
        ax.plot((w.t[m_p] - 20e-9) * 1e9, w["v(q2p)"][m_p], lw=1.0, label="q2p (1G)")
        ax.plot((w.t[m_p] - 20e-9) * 1e9, w["v(q4p)"][m_p], lw=1.1, label="q4p (500M)")
        ax.plot((w.t[m_p] - 20e-9) * 1e9, w["v(q8p)"][m_p], lw=1.4, label="q8p (250M)")
        ax.set_ylabel("V")
        ax.set_title(f"{c.tag}:{rc} | q2={(r['q2']['duty'] or 0):.3f} q4={(r['q4']['duty'] or 0):.3f} q8={(r['q8']['duty'] or 0):.3f} Pdiv={r['pdiv_mw']:.2f}mW", fontsize=9)
        ax.grid(True, alpha=0.3)
        if idx == 0:
            ax.legend(ncol=4, fontsize=8)
    axes[-1].set_xlabel("Time - 20 ns (ns)")
    fig.suptitle("Post-layout Chain: CPEX serdes_cml_to_cmos_r5_pdk -> CPEX pll_cmos_prescaler8_2g_pdk", fontsize=11)
    fig.tight_layout()
    plot = plot_path(camp, "waves_r5_div8_7corners.png")
    fig.savefig(plot, dpi=150)
    plt.close(fig)
    save_analysis(camp, dict(stage="chain_div8", rows=rows))
    print(f"Saved {plot}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["6corners", "45corners", "mc", "chain_div8", "all"], required=True)
    ap.add_argument("--campaign", type=Path, default=None)
    ap.add_argument("--workers", type=int, choices=(1, 2, 3, 4), default=2)
    args = ap.parse_args()
    camp = (args.campaign or (ROOT / "results/analog/common/cml_to_cmos/r5_pdk" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))).resolve()
    camp.mkdir(parents=True, exist_ok=True)
    if len(watch.ngspice_cwds()) + args.workers > 4:
        raise RuntimeError("Global ngspice slots occupied")
    print(f"Campaign: {camp}", flush=True)
    if args.stage in ("6corners", "all"):
        run_6corners(camp, args.workers)
    if args.stage in ("chain_div8", "all"):
        run_chain_div8(camp, args.workers)
    if args.stage in ("45corners", "all"):
        run_45corners(camp, args.workers)
    if args.stage in ("mc", "all"):
        run_mc(camp, args.workers)


if __name__ == "__main__":
    main()
