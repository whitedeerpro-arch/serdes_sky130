#!/usr/bin/env python3
"""Post-Layout CPEX Verification of Full RX v2 Zero-CML Receiver (`serdes_rx_cmos_top_pdk_pex.spice`).

Drives the Magic-extracted CPEX netlist `serdes_rx_cmos_top_pdk_pex.spice` with the real
signed-off TX v4 SST (FFE=3) -> C2_loss6 far-end waveforms from Stage B across 3 critical PVT
corners (`tt_v1800_t27`, `ss_v1650_t-40`, `ff_v1950_t-40`) using `--workers 2` MAX.

Measures and verifies:
  - 0 data errors across >= 4 full 16-bit PRBS-7 words (>= 64 bits)
  - 0 deterministic edge errors (Alexander BBPD compatibility)
  - wclk period (~4.0 ns) and setup/hold margins (>= 1000 ps)
  - Post-layout CPEX CTLE (EQ3) differential eye height & width
  - Post-layout CPEX unified RX power (mW and pJ/b @ 4 Gb/s) vs schematic baseline

Usage:
    uv run python analog/rx/cmos_rx/tb/postlayout/verify_rx_v2_pex.py [--workers 2] [--resume DIR]
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import numpy as np

from serdes_flow import corners, project, spice
from serdes_flow.waves import crossings, time_average

ROOT = project.ROOT
LINK_TB_DIR = ROOT / "analog/rx/cmos_rx/tb/link"
if str(LINK_TB_DIR) not in sys.path:
    sys.path.insert(0, str(LINK_TB_DIR))

import verify_link as vl  # noqa: E402

TOP_PEX_DEFAULT = ROOT / "results/layout/rx_cmos_v2/top/review/serdes_rx_cmos_top_pdk/serdes_rx_cmos_top_pdk_pex.spice"
PI_PEX_DEFAULT = ROOT / "results/layout/rx_cmos_v2/pi/review/serdes_rx_cmos_pi_8ph_pdk/serdes_rx_cmos_pi_8ph_pdk_pex.spice"
STAGEB_DIR_DEFAULT = ROOT / "results/analog/rx/cmos_rx/link/20261121T152322Z_stageB"
RESULTS_BASE = ROOT / "results/analog/rx/cmos_rx/postlayout_v2"

CRIT3 = [
    corners.Condition("tt", 1.80, 27),
    corners.Condition("ss", 1.65, -40),
    corners.Condition("ff", 1.95, -40),
]


def parse_subckt_ports(spice_path: Path, subckt_name: str) -> list[str]:
    """Extract exact ordered port list from a `.subckt <name> ...` header (handling `+` continuations)."""
    lines = spice_path.read_text().splitlines()
    collecting = False
    toks: list[str] = []
    pat = re.compile(rf"^\.subckt\s+{re.escape(subckt_name)}\b", re.I)
    for ln in lines:
        s = ln.strip()
        if not collecting:
            if pat.match(s):
                collecting = True
                toks.extend(s.split()[2:])
        else:
            if s.startswith("+"):
                toks.extend(s[1:].strip().split())
            else:
                break
    if not toks:
        raise ValueError(f"Could not find .subckt {subckt_name} in {spice_path}")
    return toks


def build_pi_pex_probe_deck(
    c: corners.Condition,
    pi_pex_path: Path,
    pi_ports: list[str],
    c_load_fF: float = 35.0,
) -> str:
    """Fast 5.5-ns CPEX PI phase probe at code=0 to predict exact CPEX ckd0 phase modulo 250 ps."""
    s = c.supply
    port_map = {"vss": "0", "rst_n": "rst_rx_n"}
    conn = " ".join(port_map.get(p, p) for p in pi_ports)
    return f"""* Post-Layout CPEX PI Phase Probe ({c.tag}, code=0)
.lib "{project.model_library()}" {c.process}
.include "{pi_pex_path.resolve()}"
Vdd vdd 0 {s}
{vl.rx_clock_sources(s)}
Vrst rst_rx_n 0 PWL(0 0 0.70n 0 0.75n {s})
{vl.rx_pi_ctrl_sources(0, s)}
Xpi {conn} serdes_rx_cmos_pi_8ph_pdk
Cd0 ckd0 0 {c_load_fF}f
Cd1 ckd1 0 {c_load_fF}f
Cd2 ckd2 0 {c_load_fF}f
Cd3 ckd3 0 {c_load_fF}f
Ce0 cke0 0 {c_load_fF}f
Ce1 cke1 0 {c_load_fF}f
Ce2 cke2 0 {c_load_fF}f
Ce3 cke3 0 {c_load_fF}f
.temp {c.temp}
.options reltol=3e-4 abstol=1p vntol=2u klu
.save v(ckd0)
.control
set num_threads=1
set filetype=binary
tran 5p 5.5e-9 3.5e-9 10p
write pi_pex.raw v(ckd0)
quit
.endc
.end
"""


def build_top_pex_deck(
    c: corners.Condition,
    top_pex_path: Path,
    top_ports: list[str],
    pi_code: int,
    t_stop: float = 26.5e-9,
    t_save: float = vl.B_REPLAY_SAVE,
    rst_rel_ns: float = 0.70,
) -> str:
    """Full post-layout CPEX RX v2 replay deck driven by real TX v4 C2_loss6 far-end waveform."""
    s = c.supply
    port_map = {"vss": "0", "rst_n": "rst_rx_n"}
    conn_list = [port_map.get(p, p) for p in top_ports]
    conn_lines = []
    for i in range(0, len(conn_list), 12):
        prefix = "Xrx " if i == 0 else "+ "
        conn_lines.append(prefix + " ".join(conn_list[i:i + 12]))
    conn_lines.append("+ serdes_rx_cmos_top_pdk")
    wd_nodes = " ".join(f"v(wd{i})" for i in range(16))
    we_nodes = " ".join(f"v(we{i})" for i in range(16))

    return f"""* Post-Layout CPEX RX v2 Top Shifted C2 Replay ({c.tag}, PI={pi_code})
.lib "{project.model_library()}" {c.process}
.include "{top_pex_path.resolve()}"

Vdd vdd 0 {s}
Vvcm vcm_ref 0 1.05
Ibias_ctle vdd ibias_ctle dc 50u
Vrst_rx rst_rx_n 0 PWL(0 0 {rst_rel_ns:.3f}e-9 0 {rst_rel_ns + 0.05:.3f}e-9 {s})
Veq0 eq0 0 {s}
Veq1 eq1 0 {s}
.include "rx_in.inc"
{vl.rx_clock_sources(s)}
{vl.rx_pi_ctrl_sources(pi_code, s)}

{chr(10).join(conn_lines)}
Cwclk wclk 0 10f

.temp {c.temp}
.options reltol=4e-4 abstol=2p vntol=5u klu
.save v(ctle_p) v(ctle_n) v(wclk) {wd_nodes} {we_nodes} i(Vdd)
.control
set num_threads=1
set filetype=binary
tran 6p {t_stop:.6e} {t_save:.6e} 12p
let ctle_diff = v(ctle_p) - v(ctle_n)
let p_rx = -{s}*i(Vdd)
write rx_pex.raw ctle_diff v(wclk) {wd_nodes} {we_nodes} p_rx
quit
.endc
.end
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=2, help="Max concurrent ngspice workers (capped at 2)")
    ap.add_argument("--top-pex", type=Path, default=TOP_PEX_DEFAULT)
    ap.add_argument("--pi-pex", type=Path, default=PI_PEX_DEFAULT)
    ap.add_argument("--stageb-dir", type=Path, default=STAGEB_DIR_DEFAULT)
    ap.add_argument("--resume", type=Path, default=None, help="Existing campaign dir to resume")
    ap.add_argument("--code-offsets", type=int, nargs="*", default=[0],
                    help="Optional PI code offsets around predicted opt_code_pex (default: [0])")
    args = ap.parse_args()

    workers = min(max(1, args.workers), 2)
    if args.resume is not None:
        camp = args.resume.resolve()
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        camp = (RESULTS_BASE / f"{ts}_rx_v2_cpex").resolve()
    camp.mkdir(parents=True, exist_ok=True)

    assert args.top_pex.exists(), f"Missing top CPEX netlist: {args.top_pex}"
    assert args.pi_pex.exists(), f"Missing PI CPEX netlist: {args.pi_pex}"

    top_ports = parse_subckt_ports(args.top_pex, "serdes_rx_cmos_top_pdk")
    pi_ports = parse_subckt_ports(args.pi_pex, "serdes_rx_cmos_pi_8ph_pdk")
    bits = vl.build_sequence()
    (camp / "bits.json").write_text(json.dumps(bits.tolist()))

    # Load schematic baseline summary for honest comparison
    schem_summary = json.loads((args.stageb_dir / "summary.json").read_text())
    schem_by_cond = {r["condition"]: r for r in schem_summary.get("rows", [])}

    # Step 1: Fast CPEX PI phase probe on the 3 critical corners -> exact CPEX opt_code!
    probe_dir = camp / "pi_probe"
    probe_dir.mkdir(parents=True, exist_ok=True)
    probe_jobs = []
    for c in CRIT3:
        if spice.case_output(probe_dir, c.tag, "pi_pex.raw", t_end=5.5e-9) is None:
            rdir = spice.next_run_dir(probe_dir, c.tag)
            dk = build_pi_pex_probe_deck(c, args.pi_pex, pi_ports)
            probe_jobs.append((dk, rdir, dict(timeout_s=900, meta=dict(condition=c.tag, stage="pi_pex_probe"))))
    if probe_jobs:
        print(f"[Step 1] Running {len(probe_jobs)} CPEX PI phase probes (workers={workers})...", flush=True)
        for ex in spice.run_many(probe_jobs, workers=workers, smoke=False):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    # Prepare shifted PWL inputs from Stage B TX->C2 waveforms & predict CPEX opt_code
    pwl_dir = camp / "pwl"
    pwl_dir.mkdir(parents=True, exist_ok=True)
    pred_info: dict[str, dict] = {}
    for c in CRIT3:
        tx_raw = args.stageb_dir / "pre" / f"tx_{c.tag}" / "tx_c2.raw"
        assert tx_raw.exists(), f"Missing Stage B TX waveform: {tx_raw}"
        pwl_inc = pwl_dir / f"rx_in_{c.tag}.inc"
        if not pwl_inc.exists():
            vl.write_shifted_pwl(
                tx_raw, pwl_inc, step_ps=20.0,
                shift_s=vl.B_REPLAY_SHIFT, t_stop=26.5e-9,
            )
        wtx = spice.Waves(tx_raw)
        t_bit0, tx_eye = vl.find_bit0_center(wtx.t, wtx["ctle_diff"], bits)
        ppi = spice.case_output(probe_dir, c.tag, "pi_pex.raw", t_end=5.5e-9)
        assert ppi is not None
        wpi = spice.Waves(ppi)
        e_ck, p_ck = crossings(wpi.t, wpi["v(ckd0)"], 0.5 * c.supply)
        rising = e_ck[p_ck > 0]
        v_ck = wpi["v(ckd0)"]
        pi_toggled = len(rising) > 0
        if pi_toggled:
            ck0 = float(rising[0])
            # Account for ~15 ps extra CTLE+slicer CPEX delay relative to schematic 35 ps aperture
            slicer_ap_pex = vl.SLICER_APERTURE_S + 15e-12
            dt = (((t_bit0 - slicer_ap_pex) - ck0 + 0.5 * vl.UI) % vl.UI) - 0.5 * vl.UI
            opt_code = int(round(dt / (vl.UI / 32.0))) % 64
        else:
            ck0 = float("nan")
            opt_code = int(schem_by_cond.get(c.tag, {}).get("code", 0))
            print(
                f"  [WARN] {c.tag} CPEX PI probe did NOT toggle! v(ckd0)={v_ck.min():.3f}..{v_ck.max():.3f} V "
                f"(fallback code={opt_code})",
                flush=True,
            )
        pred_info[c.tag] = dict(
            condition=c.tag,
            pi_probe_toggled=pi_toggled,
            pi_probe_ckd0_pp_v=round(float(v_ck.max() - v_ck.min()), 4),
            opt_code_pex=opt_code,
            ck0_ns=ck0 * 1e9 if pi_toggled else None,
            bit0_center_ns=t_bit0 * 1e9,
            pwl_inc=str(pwl_inc),
            tx_raw=str(tx_raw.relative_to(ROOT)),
            schem_ctle_eye_h_mv=tx_eye["ctle_eye_h_mv"],
        )
    (camp / "pi_probe_summary.json").write_text(json.dumps(pred_info, indent=2) + "\n")

    # Step 2: Run full extracted `serdes_rx_cmos_top_pdk_pex.spice` on all 3 critical corners!
    sim_dir = camp / "rx_pex"
    sim_dir.mkdir(parents=True, exist_ok=True)
    jobs = []
    for c in CRIT3:
        c0 = pred_info[c.tag]["opt_code_pex"]
        pwl_inc = Path(pred_info[c.tag]["pwl_inc"])
        for off in args.code_offsets:
            cd = (c0 + off) % 64
            case_name = f"{c.tag}_c{cd:02d}"
            if spice.case_output(sim_dir, case_name, "rx_pex.raw", t_end=26.5e-9) is None:
                rdir = spice.next_run_dir(sim_dir, case_name)
                dk = build_top_pex_deck(c, args.top_pex, top_ports, cd, t_stop=26.5e-9)
                jobs.append((
                    dk, rdir,
                    dict(
                        files={"rx_in.inc": pwl_inc},
                        timeout_s=3600,
                        meta=dict(condition=c.tag, code=cd, offset=off, stage="rx_top_pex"),
                    ),
                ))
    if jobs:
        print(f"[Step 2] Running {len(jobs)} full RX v2 Top CPEX transient sims (workers={workers})...", flush=True)
        for ex in spice.run_many(jobs, workers=workers, smoke=False):
            assert ex.ok, (ex.run_dir, ex.log_failures)

    # Step 3: Analyse results (data/edge errors, wclk setup/hold, CPEX CTLE eye, power vs schematic!)
    rows = []
    for c in CRIT3:
        c0 = pred_info[c.tag]["opt_code_pex"]
        for off in args.code_offsets:
            cd = (c0 + off) % 64
            case_name = f"{c.tag}_c{cd:02d}"
            p = spice.case_output(sim_dir, case_name, "rx_pex.raw", t_end=26.5e-9)
            assert p is not None, f"Missing output for {case_name}"
            w = spice.Waves(p)
            r = vl.analyse_rx_words(w, bits, c.supply, cd, meas_from=vl.B_REPLAY_MEAS, min_words=4, min_bit_idx=4)
            sel = w.t >= vl.B_REPLAY_MEAS
            p_rx_mw = float(time_average(w["p_rx"][sel], w.t[sel]) * 1e3)
            # Measure post-layout CTLE eye on shifted time axis (+B_REPLAY_SHIFT)
            _, pex_eye = vl.find_bit0_center(w.t + vl.B_REPLAY_SHIFT, w["ctle_diff"], bits)
            sc = schem_by_cond.get(c.tag, {})
            r.update(
                condition=c.tag,
                offset_codes=int(off),
                raw_path=str(p.relative_to(ROOT)),
                pex_ctle_eye_h_mv=round(pex_eye["ctle_eye_h_mv"], 2),
                pex_ctle_eye_w_ui=round(pex_eye["ctle_eye_w_ui"], 4),
                p_rx_pex_mw=round(p_rx_mw, 3),
                rx_pex_pj_per_bit=round(p_rx_mw / 4.0, 3),
                p_rx_schem_mw=round(float(sc.get("p_rx_mw", float("nan"))), 3),
                delta_power_pct=round(100.0 * (p_rx_mw - float(sc.get("p_rx_mw", p_rx_mw))) / max(float(sc.get("p_rx_mw", 1.0)), 1e-6), 2),
            )
            rows.append(r)
            print(
                f"  {c.tag:14s} code={cd:02d} (off={off:+d}) | ok={r['ok']} | "
                f"d_err={r.get('data_errors', 'NA')}/{r.get('data_bits', 'NA')} "
                f"e_err={r.get('edge_errors', 'NA')}/{r.get('edge_determinate', 'NA')} | "
                f"bbpd={r.get('bbpd_vote', 0):+d}/{r.get('bbpd_transitions', 0)} | "
                f"wclk su/ho={r.get('wclk_setup_ps', float('nan')):.0f}/{r.get('wclk_hold_ps', float('nan')):.0f} ps | "
                f"CTLE_eye={r['pex_ctle_eye_h_mv']:.1f} mV / {r['pex_ctle_eye_w_ui']:.3f} UI | "
                f"P_pex={r['p_rx_pex_mw']:.2f} mW ({r['rx_pex_pj_per_bit']:.2f} pJ/b, "
                f"{r['delta_power_pct']:+.1f}% vs schem {r['p_rx_schem_mw']:.2f} mW)"
                + (f" [{r['reason']}]" if 'reason' in r else ""),
                flush=True,
            )

    summary = {
        "top_pex": str(args.top_pex.relative_to(ROOT)),
        "pi_pex": str(args.pi_pex.relative_to(ROOT)),
        "stageb_ref": str(args.stageb_dir.relative_to(ROOT)),
        "campaign_dir": str(camp.relative_to(ROOT)),
        "all_passed": all(r["ok"] for r in rows),
        "rows": rows,
    }
    (camp / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"\nWrote {camp / 'summary.json'} (all_passed={summary['all_passed']})", flush=True)


if __name__ == "__main__":
    main()
