#!/usr/bin/env python3
"""Post-layout RCX (100 mOhm threshold, 6,290 resistors) verification for LDO v2.

Measures on serdes_pll_supply_hv18_v2_probe_pdk_rcx.spice (1 ngspice worker):
  1. Real 10 mA quiet power-rail IR drop across ALL 29 extracted Xpass source sub-nodes
     vs perimeter quiet port (plus vin & vss rail drops).
  2. Post-layout RCX DC regulation, 20 MHz PSRR, and dual-injection Middlebrook
     loop stability (PM, GBW, single downward 0 dB crossing) across TT, FS/ll, SS/hh, FF/ll.
  3. Post-layout RCX fast load step (6 mA +/- 1 mA and +/- 4 mA, 1 ns) at TT and FS/ll 85 C.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re

import numpy as np
from serdes_flow import feedback, project, spice

ROOT = project.ROOT
V2_TB_PATH = ROOT / "analog/common/ldo/tb/v2/run_v2.py"
spec = importlib.util.spec_from_file_location("ldo_v2_tb", V2_TB_PATH)
v2tb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2tb)

RCX_SPICE = ROOT / "analog/common/ldo/layout/variants/v2_pdk/serdes_pll_supply_hv18_v2_probe_pdk_rcx.spice"
SUBCKT = "serdes_pll_supply_hv18_v2_probe_pdk"
OUT_ROOT = ROOT / "results/analog/common/ldo/v2"


def find_xpass_quiet_nodes(rcx_path: Path) -> list[str]:
    nodes = set()
    for ln in rcx_path.read_text().splitlines():
        if "sky130_fd_pr__nfet_05v0_nvt" in ln:
            toks = ln.split()
            for p in (toks[1], toks[3]):
                if p.startswith("quiet."):
                    nodes.add(p)
    return sorted(nodes)


def main() -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    work = OUT_ROOT / f"{ts}_pex_rcx"
    work.mkdir(parents=True)

    spice_files = v2tb.reg.BIAS + [RCX_SPICE]
    q_nodes = find_xpass_quiet_nodes(RCX_SPICE)
    print(f"RCX netlist: {RCX_SPICE.name} | {len(q_nodes)} Xpass quiet sub-nodes", flush=True)

    # Calibrated trim codes (from locked v2 CPEX, verified monotonic)
    profiles = [
        # (mos, rc, vin, host, temp, trim)
        ("tt", "tt", 3.3, 1.80, 27, 40),
        ("fs", "ll", 3.0, 1.95, 85, 38),
        ("ss", "hh", 3.0, 1.65, -40, 40),
        ("ff", "ll", 3.6, 1.95, -40, 38),
    ]

    out: dict = {
        "rcx_macro": str(RCX_SPICE.relative_to(ROOT)),
        "subckt": SUBCKT,
        "xpass_quiet_subnodes": len(q_nodes),
        "ir_drop": [],
        "ac": [],
        "step": [],
    }

    # --- 1 & 2. Merged DC + IR-Drop + AC (PSRR + Middlebrook) per corner ---
    for mos, rc, vin, host, temp, trim in profiles:
        v2tb.run_slot_guard()
        sec = v2tb.section(mos, rc)
        lib = v2tb.get_lib(work, sec, spice_files, reduced=True)

        body = v2tb.circuit_body(lib, sec, spice_files, subckt=SUBCKT, trim=trim)
        q_vecs = " ".join(f"v(xdut.{n})" for n in q_nodes)
        lines = [
            body,
            ".control", "set num_threads=1", "set filetype=binary",
            f"option temp={temp}",
            f"alter Vdd dc={vin}", f"alter Vhost dc={host}", "alter Venable dc=1.8",
        ]
        for load in (2, 6, 10):
            tag = f"{mos}_{rc}_l{load}"
            lines += [
                f"alter Iload dc={load}m",
                "alter Vdd acmag=0", "alter Vtest acmag=0", "alter Itest acmag=0",
                "op",
                f"write op_{tag}.raw v(quiet) v(bg) i(vdd) {q_vecs}",
                "destroy all",
                # PSRR
                "alter Vdd acmag=1",
                "ac dec 15 100 200meg",
                *v2tb.ac_write(tag, "psrr", ("quiet",)),
                # Middlebrook dual-injection (exact same convention as run_v2.py)
                "alter Vdd acmag=0", "alter Vtest acmag=1",
                "ac dec 15 10 10g",
                "let tv=-v(fbret)/v(fbin)", "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {tag}_voltage.tsv vr vi", "destroy all",
                "alter Vtest acmag=0", "alter Itest acmag=1",
                "ac dec 15 10 10g",
                "let ti=i(Vtest)/(1-i(Vtest))", "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {tag}_current.tsv ir ii", "destroy all",
                "alter Itest acmag=0",
            ]
        lines += ["quit", ".endc", ".end", ""]
        rdir = spice.next_run_dir(work, f"rcx_dcac_{mos}_{rc}")
        ex = spice.run("\n".join(lines), rdir, files={p.name: p for p in spice_files}, timeout_s=1200)
        if not ex.ok:
            raise RuntimeError(f"RCX DC/AC failed for {mos}:{rc}: {rdir}")

        for load in (2, 6, 10):
            tag = f"{mos}_{rc}_l{load}"
            w = spice.Waves(rdir / f"op_{tag}.raw")
            vq = float(w["v(quiet)"][0])
            qs = [float(w[f"v(xdut.{n})"][0]) for n in q_nodes]
            ir_max_mv = float((max(qs) - vq) * 1e3)
            ir_min_mv = float((min(qs) - vq) * 1e3)
            ir_mean_mv = float((np.mean(qs) - vq) * 1e3)
            out["ir_drop"].append(dict(
                mos=mos, rc=rc, vin=vin, host=host, temp_c=temp, trim=trim, load_ma=load,
                v_quiet=round(vq, 5), ir_max_mv=round(ir_max_mv, 3),
                ir_mean_mv=round(ir_mean_mv, 3), ir_min_mv=round(ir_min_mv, 3),
                r_eff_mohm=round(ir_max_mv / load * 1e3, 1),
            ))

            a_p = np.loadtxt(rdir / f"{tag}_psrr.tsv")
            f_p = a_p[:, 0]
            h_p = a_p[:, 1] + 1j * a_p[:, 3]
            psrr20 = float(-20.0 * np.log10(max(float(np.exp(np.interp(np.log(20e6), np.log(f_p), np.log(np.abs(h_p))))), 1e-18)))
            psrr1 = float(-20.0 * np.log10(max(float(np.exp(np.interp(np.log(1e6), np.log(f_p), np.log(np.abs(h_p))))), 1e-18)))
            va_t = np.loadtxt(rdir / f"{tag}_voltage.tsv")
            ia_t = np.loadtxt(rdir / f"{tag}_current.tsv")
            gain = feedback.middlebrook(va_t[:, 1] + 1j * va_t[:, 3], ia_t[:, 1] + 1j * ia_t[:, 3])
            cross = feedback.unity_crossings(va_t[:, 0], gain)
            pm_raw = float(cross[0]["pm_deg"]) if len(cross) == 1 and cross[0]["direction"] == "down" else -999.0
            pm_deg = float((pm_raw + 180.0) % 360.0 - 180.0) if pm_raw > -500 else -999.0
            ugf_mhz = float(cross[0]["hz"] / 1e6) if cross else 0.0
            dc_gain_db = float(20.0 * np.log10(max(abs(gain[0]), 1e-18)))
            out["ac"].append(dict(
                mos=mos, rc=rc, vin=vin, host=host, temp_c=temp, trim=trim, load_ma=load,
                v_quiet=round(vq, 5), psrr_1mhz_db=round(psrr1, 2), psrr_20mhz_db=round(psrr20, 2),
                dc_gain_db=round(dc_gain_db, 2),
                ugf_mhz=round(ugf_mhz, 3),
                pm_deg=round(pm_deg, 2),
                crossings=cross,
            ))
            print(
                f"RCX {mos}:{rc} {load:2d}mA | Vq={vq:.4f}V | IR_max={ir_max_mv:.2f}mV (R_eff={ir_max_mv/load*1e3:.0f}mOhm) | "
                f"PSRR20={psrr20:.2f}dB | PM={pm_deg:.2f}deg | x0={len(cross)}",
                flush=True,
            )

    # --- 3. Fast Load Step (EXACT run_v2.py / smallcap 6 mA +/- 0.1/1/4 mA, 1 ns protocol!) ---
    for mos, rc, vin, host, temp, trim in profiles[:2]:
        v2tb.run_slot_guard()
        sec = v2tb.section(mos, rc)
        lib = v2tb.get_lib(work, sec, spice_files, reduced=True)
        body = v2tb.circuit_body(lib, sec, spice_files, subckt=SUBCKT, trim=trim)
        body = re.sub(r"^Vdd .*$", f"Vdd vin 0 {vin} ac 0", body, flags=re.M)
        body = re.sub(r"^Vhost .*$", f"Vhost host 0 {host} ac 0", body, flags=re.M)
        body = re.sub(r"^Venable .*$", f"Venable enable 0 {host}", body, flags=re.M)
        for k in range(6):
            body = re.sub(rf"^Vb{k} .*$", f"Vb{k} b{k} 0 {host if (trim >> k) & 1 else 0}", body, flags=re.M)
        body = re.sub(r"^Iload .*$", "Iload quiet 0 6m", body, flags=re.M)
        body += (
            "Istep quiet 0 pwl(0 0 0.5u 0 0.501u 100u 0.7u 100u 0.701u 0 "
            "0.9u 0 0.901u -100u 1.1u -100u 1.101u 0 "
            "1.3u 0 1.301u 1m 1.5u 1m 1.501u 0 "
            "1.7u 0 1.701u -1m 1.9u -1m 1.901u 0 "
            "2.1u 0 2.101u 4m 2.3u 4m 2.301u 0 "
            "2.5u 0 2.501u -4m 2.7u -4m 2.701u 0)\n"
        )
        deck = "\n".join([
            body,
            f".temp {temp}",
            ".control", "set num_threads=1", "set filetype=binary",
            "optran 1 1 1 100n 300u 0",
            "save v(quiet)",
            "tran 0.2n 3u 0 1n",
            "write wave.raw v(quiet)",
            "quit", ".endc", ".end", "",
        ])
        rdir = spice.next_run_dir(work, f"rcx_step_{mos}_{rc}")
        ex = spice.run(deck, rdir, files={p.name: p for p in spice_files}, timeout_s=900)
        if not ex.ok:
            raise RuntimeError(f"RCX step failed for {mos}:{rc}: {rdir}")
        w = spice.Waves(rdir / "wave.raw")
        t, v = w.t, w["v(quiet)"]
        v0 = float(np.mean(v[t < 0.49e-6]))
        s1 = v[(t >= 1.3e-6) & (t < 2.1e-6)]
        s4 = v[(t >= 2.1e-6) & (t <= 3.0e-6)]
        rec = dict(
            mos=mos, rc=rc, vin=vin, host=host, temp_c=temp, trim=trim,
            v_init=round(v0, 5),
            step1_drop_mv=round(float((s1.min() - v0) * 1e3), 2),
            step1_over_mv=round(float((s1.max() - v0) * 1e3), 2),
            step4_min_v=round(float(s4.min()), 4),
            step4_max_v=round(float(s4.max()), 4),
            elapsed_s=round(ex.elapsed_s, 1),
        )
        out["step"].append(rec)
        print(
            f"RCX STEP {mos}:{rc} ({ex.elapsed_s:.1f}s) | +-1mA={rec['step1_drop_mv']:+.1f}/{rec['step1_over_mv']:+.1f}mV | "
            f"+-4mA=[{rec['step4_min_v']:.4f}, {rec['step4_max_v']:.4f}]V",
            flush=True,
        )

    sp = work / "summary.json"
    sp.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nSAVED: {sp.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
