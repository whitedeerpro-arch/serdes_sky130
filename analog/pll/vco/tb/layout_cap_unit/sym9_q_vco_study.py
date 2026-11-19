"""Complete 9-Block Mirror-Symmetric Fused Cap Bank: Q-Variation, C_off, and Oscillating VCO Study.

Compares 6 complete 5-bit bank models/extractions:
  1. planning_31u : schematic 31-unit 2x2 um planning model (cap_bank_5b.spice)
  2. shared_31u   : extracted 31-unit 2x2 um shared-plate physical bank (1265 um^2, 62 fingers)
  3. sym9_w150    : extracted 9-block mirror-symmetric fused bank (W/u = 1.50 um, 22 fused fingers)
  4. sym9_w100    : extracted 9-block mirror-symmetric fused bank (W/u = 1.00 um, 18 fused fingers)
  5. sym9_w075    : extracted 9-block mirror-symmetric fused bank (W/u = 0.75 um, 15 fused fingers)
  6. sym9_w050    : extracted 9-block mirror-symmetric fused bank (W/u = 0.50 um, 15 fused fingers)

Part A: 32-code AC extraction (1 MHz, 20 MHz, 2 GHz) across 8 PVT/RC corners:
  - C_off (Code 0), C_on (Code 31), C_on(2GHz)/C_on(1MHz) roll-off, Q_on(2GHz),
    parallel tank loss conductance G_on(2GHz) & R_p(2GHz), and 31-step DNL monotonicity.

Part B: Actual oscillating 4-stage CML Ring VCO + 4 buffers + real bias transient simulation
  (14 ns / 4 ps, settled 8..14 ns window) across 5 critical frequency-range and Q-stress points:
  1. fs_v1650_t85:hh  Code  0 Vctrl=1.210V (Slow-MOS / High-RC hot corner: f_max margin above 2 GHz)
  2. sf_v1650_t-40:ll Code 31 Vctrl=0.900V (Fast-MOS / Low-RC cold corner: f_min margin below 2 GHz)
  3. ss_v1650_t85:hh  Code 31 Vctrl=1.055V (Worst hot slow-MOS corner with ALL 31 units ON: Q_on & swing stress)
  4. ss_v1650_t85:hh  Code 16 Vctrl=1.055V (Mid-code hot slow-MOS loop-gain / swing check)
  5. sf_v1650_t85:hh  Code 16 Vctrl=1.055V (Lowest loop-gain corner from r6.py)
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import bias, project, spice, watch
from serdes_flow.corners import Condition
from serdes_flow.spice import spice_number

ROOT = project.ROOT
SHARED_31U_PEX = ROOT / "results/layout/pll_r6/shared_bank_audited/pll_vco_cap_bank5_shared_cap.spice"

AC_CONDITIONS = [
    ("tt_tt", "tt", "tt", 1.80, 27),
    ("tt_hh", "tt", "hh", 1.80, 27),
    ("tt_ll", "tt", "ll", 1.80, 27),
    ("fs_hot_hh", "fs", "hh", 1.65, 85),
    ("ss_hot_hh", "ss", "hh", 1.65, 85),
    ("sf_hot_hh", "sf", "hh", 1.65, 85),
    ("sf_cold_ll", "sf", "ll", 1.65, -40),
    ("ff_cold_ll", "ff", "ll", 1.95, -40),
]
FREQUENCIES = (1e6, 20e6, 2e9)


def prepare_anchored_bank(pex_path: Path, subckt_alias: str) -> tuple[str, dict]:
    pex_path = pex_path.resolve()
    text = pex_path.read_text()
    if not text.startswith("* Capacitance matrix from flat EXT node/cap records;"):
        raise ValueError(f"Expected audited _cap.spice: {pex_path}")
    top_m = re.search(r"^\.subckt (\S+) ([^\n]+)$", text, re.M)
    if not top_m or set(top_m[2].split()) != {"node", "b0", "b1", "b2", "b3", "b4", "vss"}:
        raise ValueError(f"Missing 7-port bank subckt in {pex_path}")
    orig_top = top_m[1]
    text = re.sub(r"^\.subckt \S+ [^\n]+$", f".subckt {orig_top} node b0 b1 b2 b3 b4 vss", text, count=1, flags=re.M)
    caps = re.findall(r"^X\S+ node (\S+) sky130_fd_pr__cap_mim_m3_1\b", text, re.M)
    plates = Counter(caps)

    # Determine logical unit weight per floating plate for 1 Tohm/unit DC reference
    anchors = []
    for i, plate in enumerate(plates):
        gates = set(
            re.findall(r"^X\S+ " + re.escape(plate) + r" (b[0-4]) vss vss sky130_fd_pr__nfet_01v8\b", text, re.M)
        )
        gates |= set(
            re.findall(r"^X\S+ vss (b[0-4]) " + re.escape(plate) + r" vss sky130_fd_pr__nfet_01v8\b", text, re.M)
        )
        if len(gates) != 1:
            raise ValueError(f"Ambiguous gate for plate {plate} in {pex_path}")
        bit = int(next(iter(gates))[1:])
        # In sym9, b1..b4 are split into 2 symmetric plates (each weight 2^(bit-1)), while b0 is 1 plate (weight 1)
        bit_plates = [
            p
            for p in plates
            if set(
                re.findall(
                    r"^X\S+ (?:vss (b[0-4]) " + re.escape(p) + "|" + re.escape(p) + r" (b[0-4]) vss) vss",
                    text,
                    re.M,
                )[0]
            )
            - {""}
            == {f"b{bit}"}
        ]
        n_plates_for_bit = len(bit_plates)
        unit_weight = (2**bit) / n_plates_for_bit
        anchors.append(f"Rdc{i} {plate} vss {1e12 / unit_weight:.12g}")

    matrix = [(a, b, spice_number(v) * 1e15) for a, b, v in re.findall(r"^C\S+ (\S+) (\S+) (\S+)$", text, re.M)]
    direct_ff = sum(v for a, b, v in matrix if "node" in (a, b) and (b if a == "node" else a) not in plates)
    fringe_ff = sum(v for a, b, v in matrix if "node" in (a, b) and (b if a == "node" else a) in plates)
    plate_gnd_ff = sum(v for a, b, v in matrix if (a in plates or b in plates) and "node" not in (a, b))
    # Debit only direct node-to-ground/control routing capacitance from the 12 fF phase wire allowance
    # (for fused banks, fringe_ff is already lower than 31 * 0.648 = 20.09 fF!)
    excess_fringe_ff = max(0.0, fringe_ff - 31.0 * 0.648)
    retained_wire_ff = max(0.0, 12.0 - direct_ff - excess_fringe_ff)

    patched = re.sub(r"^\.ends.*$", "\n".join(anchors) + "\n.ends", text, flags=re.M)
    patched = re.sub(rf"\b{re.escape(orig_top)}\b", subckt_alias, patched)
    info = dict(
        source=str(pex_path.relative_to(ROOT)),
        mim_count=len(caps),
        floating_plates=len(plates),
        node_direct_fF=round(direct_ff, 4),
        node_to_plate_fringe_fF=round(fringe_ff, 4),
        plate_to_gnd_ctrl_metal_fF=round(plate_gnd_ff, 4),
        retained_phase_wire_fF=round(retained_wire_ff, 4),
    )
    return patched, info


def run_ac_study(out_dir: Path, bank_models: list[tuple[str, str]]) -> dict:
    ac_dir = out_dir / "ac_study"
    ac_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for cname, proc, rc, vdd, temp in AC_CONDITIONS:
        lines = [
            f"Complete 5-bit bank AC Q & C_off study ({cname})",
            f'.lib "{project.model_library()}" tt',
            f'.include "{out_dir / "banks_all.spice"}"',
            f".temp {temp}",
        ]
        for i, (label, subckt) in enumerate(bank_models):
            lines += [f"Vp{i} q{i} 0 dc 1.5 ac 1", f"X{i} q{i} b0 b1 b2 b3 b4 0 {subckt}"]
        lines += [f"Vb{bit} b{bit} 0 0" for bit in range(5)]
        lines += [".control", "set num_threads=1", "set wr_singlescale", "set wr_vecnames", "set numdgt=12"]
        for code in range(32):
            lines += [f"alter Vb{bit} dc={vdd if (code >> bit) & 1 else 0}" for bit in range(5)]
            for fi, freq in enumerate(FREQUENCIES):
                lines += [f"ac lin 1 {freq} {freq}"]
                for i in range(len(bank_models)):
                    lines += [
                        f"let c{i} = -imag(i(vp{i}))/(2*pi*frequency)",
                        f"let g{i} = -real(i(vp{i}))",
                    ]
                lines += [
                    f"wrdata c{code}_f{fi}.tsv " + " ".join(f"c{i} g{i}" for i in range(len(bank_models))),
                    "destroy all",
                ]
        lines += ["quit", ".endc", ".end", ""]
        deck = bias.section("\n".join(lines), proc, rc)
        rdir = spice.next_run_dir(ac_dir, cname)
        jobs.append((deck, rdir, dict(timeout_s=300)))

    if len(watch.ngspice_cwds()) + 2 > 4:
        raise RuntimeError("Host ngspice quota occupied")
    ex_list = spice.run_many(jobs, workers=2, smoke=False)
    for ex in ex_list:
        if not ex.ok:
            raise RuntimeError(f"AC deck failed: {ex.run_dir}")

    summary = {}
    for (cname, proc, rc, vdd, temp), (_, rdir, _) in zip(AC_CONDITIONS, jobs):
        c_by_model = {label: {f: [] for f in FREQUENCIES} for label, _ in bank_models}
        g_by_model = {label: {f: [] for f in FREQUENCIES} for label, _ in bank_models}
        for code in range(32):
            for fi, freq in enumerate(FREQUENCIES):
                arr = np.atleast_2d(np.loadtxt(rdir / f"c{code}_f{fi}.tsv", skiprows=1))
                for i, (label, _) in enumerate(bank_models):
                    c_by_model[label][freq].append(float(arr[0, 1 + 3 * i] * 1e15))
                    g_by_model[label][freq].append(float(arr[0, 3 + 3 * i]))
        csum = {}
        for label, _ in bank_models:
            c2g = np.array(c_by_model[label][2e9])
            c1m = np.array(c_by_model[label][1e6])
            g2g = np.array(g_by_model[label][2e9])
            diffs = np.diff(c2g)
            q_on_2g = float(2 * np.pi * 2e9 * (c2g[-1] * 1e-15) / g2g[-1]) if g2g[-1] > 0 else None
            q_off_2g = float(2 * np.pi * 2e9 * (c2g[0] * 1e-15) / g2g[0]) if g2g[0] > 0 else None
            q_c16_2g = float(2 * np.pi * 2e9 * (c2g[16] * 1e-15) / g2g[16]) if g2g[16] > 0 else None
            rp_on_ohm = float(1.0 / g2g[-1]) if g2g[-1] > 0 else None
            csum[label] = dict(
                c_off_2GHz_fF=round(float(c2g[0]), 3),
                c_off_per_unit_fF=round(float(c2g[0] / 31.0), 4),
                c_on_2GHz_fF=round(float(c2g[-1]), 3),
                c_on_1MHz_fF=round(float(c1m[-1]), 3),
                c_on_2GHz_over_1MHz_pct=round(float((c2g[-1] / c1m[-1] - 1.0) * 100.0), 2),
                delta_c_2GHz_fF=round(float(c2g[-1] - c2g[0]), 3),
                c_on_over_c_off=round(float(c2g[-1] / c2g[0]), 2),
                q_on_2GHz=round(q_on_2g, 2) if q_on_2g else None,
                q_c16_2GHz=round(q_c16_2g, 2) if q_c16_2g else None,
                q_off_2GHz=round(q_off_2g, 1) if q_off_2g else None,
                g_on_2GHz_uS=round(float(g2g[-1] * 1e6), 2),
                rp_on_2GHz_ohm=round(rp_on_ohm, 1) if rp_on_ohm else None,
                min_lsb_step_fF=round(float(diffs.min()), 3),
                max_lsb_step_fF=round(float(diffs.max()), 3),
                monotone=bool(np.all(diffs > 0)),
                code_table_2GHz_fF=[round(float(x), 3) for x in c2g],
            )
        summary[cname] = csum
    return summary


def run_vco_transient_study(
    out_dir: Path,
    physical_banks: list[tuple[str, str, float]],
) -> dict:
    spec = importlib.util.spec_from_file_location("r6_mod", ROOT / "analog/pll/vco/tb/tuning/r6.py")
    r6 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r6)

    points = [
        ("hh", Condition.parse("fs_v1650_t85"), 0, 1.210, "slow_end_c0"),
        ("ll", Condition.parse("sf_v1650_t-40"), 31, 0.900, "fast_end_c31"),
        ("hh", Condition.parse("ss_v1650_t85"), 31, 1.055, "hot_ss_c31_q_stress"),
        ("hh", Condition.parse("ss_v1650_t85"), 16, 1.055, "hot_ss_c16_gain"),
        ("hh", Condition.parse("sf_v1650_t85"), 16, 1.055, "hot_sf_c16_lowgain"),
    ]
    todo = [(rc, cond, code, vctrl) for rc, cond, code, vctrl, _ in points]

    tran_dir = out_dir / "vco_tran"
    tran_dir.mkdir(parents=True, exist_ok=True)
    all_jobs = []

    for label, subckt, retained_wire_ff in physical_banks:
        vdir = tran_dir / label
        vdir.mkdir(parents=True, exist_ok=True)
        bank_wrapper = (
            ".subckt pll_vco_cap_bank5 node b0 b1 b2 b3 b4 vss params: capw=2 capl=2 sw=1.5\n"
            f"Xphysical node b0 b1 b2 b3 b4 vss {subckt}\n"
            ".ends pll_vco_cap_bank5\n"
        )
        wrapper_path = vdir / "physical_bank_wrapper.spice"
        wrapper_path.write_text(bank_wrapper)

        jobs = r6.jobs_for(vdir, todo, f"cwire={retained_wire_ff:.12g}f")
        for deck, dest, opts in jobs:
            deck, n = re.subn(
                r'^\.include "[^"\n]*/cap_bank_5b\.spice"$',
                lambda _: f'.include "{wrapper_path}"',
                deck,
                flags=re.M,
            )
            if n != 1:
                raise ValueError("Expected exactly one cap_bank_5b.spice include")
            deck = deck.replace(".control\n", f'.include "{out_dir / "banks_all.spice"}"\n.control\n', 1)
            all_jobs.append((deck, dest, opts))

    if len(watch.ngspice_cwds()) + 2 > 4:
        raise RuntimeError("Host ngspice quota occupied")
    ex_list = spice.run_many(all_jobs, workers=2, smoke=False)
    for ex in ex_list:
        if not ex.ok:
            raise RuntimeError(f"VCO transient deck failed: {ex.run_dir}")

    results = {}
    for label, subckt, retained_wire_ff in physical_banks:
        vdir = tran_dir / label
        row = dict(retained_phase_wire_fF=retained_wire_ff, points={})
        for rc, cond, code, vctrl, tag in points:
            m = r6.read(vdir, rc, cond, code, vctrl)
            if m is None:
                raise RuntimeError(f"Missing waveform read for {label} {tag}")
            freq_hz, swing_vpp = m
            margin_pct = None
            if tag == "slow_end_c0":
                margin_pct = round((freq_hz / 2e9 - 1.0) * 100.0, 2)
            elif tag == "fast_end_c31":
                margin_pct = round((1.0 - freq_hz / 2e9) * 100.0, 2)
            row["points"][tag] = dict(
                corner=f"{cond.tag}:{rc}",
                code=code,
                vctrl_v=vctrl,
                freq_ghz=round(freq_hz / 1e9, 4),
                freq_mhz=round(freq_hz / 1e6, 2),
                swing_mvpp=round(swing_vpp * 1e3, 1),
                margin_2ghz_pct=margin_pct,
            )
        results[label] = row
    return results


def plot_summary(out_dir: Path, ac_summary: dict, vco_summary: dict, plot_path: Path) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.2), dpi=160)
    variants = ["shared_31u", "sym9_w150", "sym9_w100", "sym9_w075", "sym9_w050"]
    labels = ["31u Shared\n(W=1.50)", "Sym9 Fused\nW=1.50/u", "Sym9 Fused\nW=1.00/u", "Sym9 Fused\nW=0.75/u", "Sym9 Fused\nW=0.50/u"]

    # Panel 1: C_off (fF) and Q_on (2 GHz) across TT and FS/SS hot hh
    ax = axes[0]
    c_off_tt = [ac_summary["tt_tt"][v]["c_off_2GHz_fF"] for v in variants]
    c_off_hh = [ac_summary["fs_hot_hh"][v]["c_off_2GHz_fF"] for v in variants]
    x = np.arange(len(variants))
    b1 = ax.bar(x - 0.18, c_off_tt, width=0.35, label="C_off (TT 27C)", color="#2b6cb0")
    b2 = ax.bar(x + 0.18, c_off_hh, width=0.35, label="C_off (FS 85C hh)", color="#ed8936")
    ax.axhline(20.0, color="#e53e3e", linestyle="--", linewidth=1.2, label="20 fF target")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Total Bank C_off at Code 0 (fF)")
    ax.set_title("1. Off-State Capacitance C_off Reduction")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, loc="upper right")
    for bar in b1:
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.8, f"{bar.get_height():.1f}", ha="center", fontsize=7.5)

    # Panel 2: Port Q at Code 31 (2 GHz) across PVT corners
    ax = axes[1]
    for cname, clabel, col, mk in [
        ("ff_cold_ll", "FF 1.95V -40C ll", "#38a169", "^"),
        ("sf_cold_ll", "SF 1.65V -40C ll (Fast End C31)", "#3182ce", "s"),
        ("tt_tt", "TT 1.80V 27C tt", "#4a5568", "o"),
        ("ss_hot_hh", "SS 1.65V 85C hh (Hot Slow C31)", "#dd6b20", "D"),
        ("fs_hot_hh", "FS 1.65V 85C hh", "#e53e3e", "v"),
    ]:
        qs = [ac_summary[cname][v]["q_on_2GHz"] for v in variants]
        ax.plot(x, qs, marker=mk, linewidth=1.8, label=clabel, color=col)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Complete Bank Port Q at Code 31 (2 GHz)")
    ax.set_title("2. Port Q_on Variation Across PVT Corners")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7.5, loc="upper right")

    # Panel 3: Actual Oscillating VCO Swing (mVpp) and Tuning Range Margin (%)
    ax = axes[2]
    sw_c0_fs = [vco_summary[v]["points"]["slow_end_c0"]["swing_mvpp"] for v in variants]
    sw_c31_sf = [vco_summary[v]["points"]["fast_end_c31"]["swing_mvpp"] for v in variants]
    sw_c31_ss = [vco_summary[v]["points"]["hot_ss_c31_q_stress"]["swing_mvpp"] for v in variants]
    sw_c16_sf = [vco_summary[v]["points"]["hot_sf_c16_lowgain"]["swing_mvpp"] for v in variants]
    ax.plot(x, sw_c0_fs, "o-", label="FS 1.65V 85C hh (Code 0)", color="#2b6cb0", linewidth=1.8)
    ax.plot(x, sw_c31_sf, "s-", label="SF 1.65V -40C ll (Code 31)", color="#38a169", linewidth=1.8)
    ax.plot(x, sw_c16_sf, "^-", label="SF 1.65V 85C hh (Code 16)", color="#dd6b20", linewidth=1.8)
    ax.plot(x, sw_c31_ss, "D--", label="SS 1.65V 85C hh (Code 31 Q-stress)", color="#e53e3e", linewidth=1.8)
    ax.axhline(400.0, color="#e53e3e", linestyle=":", linewidth=1.3, label="400 mVpp Target")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=8.5)
    ax.set_ylabel("Oscillating VCO Diff Swing (mVpp)")
    ax.set_title("3. Oscillating Ring-VCO Swing vs Switch Q")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7.5, loc="lower left")

    fig.tight_layout()
    fig.savefig(plot_path)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--bank-build-dir",
        type=Path,
        default=ROOT / "results/layout/pll_vco/20261115_sym9_fused_bank_v1",
    )
    ap.add_argument("--output-dir", type=Path, default=None)
    args = ap.parse_args()

    out = args.output_dir or (
        ROOT / "results/analog/pll/vco/sym9_q_vco_study" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Assemble all bank subcircuits into a single include file
    planning_txt = (ROOT / "analog/pll/vco/spice/cap_bank_5b.spice").read_text()
    planning_txt = re.sub(r"\bpll_vco_cap_bank5\b", "bank_planning_31u", planning_txt)

    chunks = [planning_txt]
    bank_info = {}
    ac_models = [("planning_31u", "bank_planning_31u")]
    vco_banks = []

    shared_txt, s_info = prepare_anchored_bank(SHARED_31U_PEX, "bank_shared_31u")
    chunks.append(shared_txt)
    bank_info["shared_31u"] = s_info
    ac_models.append(("shared_31u", "bank_shared_31u"))
    vco_banks.append(("shared_31u", "bank_shared_31u", s_info["retained_phase_wire_fF"]))

    for v in ("w150", "w100", "w075", "w050"):
        pex_path = args.bank_build_dir / v / f"pll_vco_cap_bank5_sym9_{v}_cap.spice"
        alias = f"bank_sym9_{v}"
        label = f"sym9_{v}"
        b_txt, b_info = prepare_anchored_bank(pex_path, alias)
        chunks.append(b_txt)
        bank_info[label] = b_info
        ac_models.append((label, alias))
        vco_banks.append((label, alias, b_info["retained_phase_wire_fF"]))

    (out / "banks_all.spice").write_text("\n\n".join(chunks) + "\n")

    print("Running Part A: 32-code AC extraction across 8 PVT/RC corners...", flush=True)
    ac_summary = run_ac_study(out, ac_models)

    print("Running Part B: Oscillating 4-stage Ring VCO transient simulation across 5 corners...", flush=True)
    vco_summary = run_vco_transient_study(out, vco_banks)

    plot_path = ROOT / "analog/pll/vco/layout/plan/sym9_q_vco_tradeoff.png"
    plot_summary(out, ac_summary, vco_summary, plot_path)

    report = dict(
        campaign=str(out.relative_to(ROOT)),
        bank_extractions=bank_info,
        ac_summary=ac_summary,
        vco_transient_summary=vco_summary,
        plot=str(plot_path.relative_to(ROOT)),
    )
    (out / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Saved complete study summary to:", out / "summary.json", flush=True)


if __name__ == "__main__":
    main()
