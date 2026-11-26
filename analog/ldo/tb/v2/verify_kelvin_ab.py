#!/usr/bin/env python3
"""Apples-to-apples RCX A/B verification of LDO v2_cur_pdk vs v2_cur_kelvin_pdk.

Runs both baseline (`v2_cur_pdk`) and optimized (`v2_cur_kelvin_pdk`) extracted
100 mOhm RCX macros under the EXACT same real BIAS v2 (`serdes_bias_ref_v2`)
and PLL load boundary:
  (a) Loop stability (Middlebrook dual-injection PM, GM, UGF, DC gain, crossings)
      across TT 27C, SS/hh -40C, SS/hh +85C, and FS/ll +85C at 2/6/10 mA.
  (b) Supply coupling / PSRR (vin -> quiet, vin -> i_ldo) AND direct AC bias
      coupling (|v(i_ldo)/v(quiet)| via Iload AC perturbation) + 10 mA IR drop.
  (c) Load-step transient (6 mA +/- 1 mA and +/- 4 mA, 1 ns edges):
      quiet droop/overshoot/settling AND transient bias kick on i_ldo & fb_input,
      on BOTH probe (15-port) and production (13-port) RCX macros.

Enforces single-threaded ngspice (`num_threads=1`) and checks global slot limit.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time

import numpy as np
from serdes_flow import feedback, model_library, project, spice, watch

ROOT = project.ROOT
BIAS_V2_FILES = [
    ROOT / "analog/common/devices/spice/sky130_primitives.spice",
    ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice",
    ROOT / "analog/bias/spice/bias_v2.spice",
]

PROBE_SUBCKT = "serdes_pll_supply_hv18_v2_cur_probe_pdk"
PROD_SUBCKT = "serdes_pll_supply_hv18_v2_cur_pdk"

# Profiles: (tag, mos, rc, vin, host, temp_c, trim)
PROFILES = [
    ("tt_27c",   "tt", "tt", 3.3, 1.80,  27, 40),
    ("ss_m40c",  "ss", "hh", 3.0, 1.65, -40, 40),
    ("ss_p85c",  "ss", "hh", 3.0, 1.65,  85, 40),
    ("fs_p85c",  "fs", "ll", 3.0, 1.95,  85, 38),
]


def section(mos: str, rc: str) -> str:
    return mos if rc == "tt" else (rc if mos == "tt" else f"{mos}_{rc}")


def required_primitives(spice_files: list[Path]) -> list[str]:
    text = "\n".join(p.read_text() for p in spice_files)
    return sorted(set(re.findall(r"\bsky130_fd_pr__\w+", text)))


def get_lib(work: Path, sec: str, spice_files: list[Path]) -> Path:
    lib_dir = work / "_models" / sec
    if not (lib_dir / "sky130.lib.spice").exists():
        model_library.build(project.model_library(), sec, required_primitives(spice_files), lib_dir)
    return lib_dir / "sky130.lib.spice"


def wait_for_slot(max_total: int = 3) -> None:
    """Wait until active ngspice count on host is strictly below max_total (respects <=4 rule)."""
    while len(watch.ngspice_cwds()) >= max_total:
        time.sleep(5.0)


def find_xpass_quiet_nodes(rcx_path: Path) -> list[str]:
    nodes = set()
    for ln in rcx_path.read_text().splitlines():
        if "sky130_fd_pr__nfet_05v0_nvt" in ln:
            toks = ln.split()
            for p in (toks[1], toks[3]):
                if p.startswith("quiet."):
                    nodes.add(p)
    return sorted(nodes)


def find_rdiv_quiet_node(rcx_path: Path) -> str | None:
    for ln in rcx_path.read_text().splitlines():
        if "sky130_fd_pr__res_high_po" in ln and "l=11.4" in ln:
            toks = ln.split()
            for p in toks[1:4]:
                if p.startswith("quiet"):
                    return p
    return None


def circuit_body_v2_cur(
    lib_path: Path,
    sec: str,
    spice_files: list[Path],
    subckt: str,
    is_probe: bool,
    vin: float = 3.3,
    host: float = 1.8,
    trim: int = 40,
    load_ma: float = 6.0,
) -> str:
    """Build exact BIAS v2 + LDO v2_cur circuit body (probe or production)."""
    lines = [
        f"* LDO v2_cur A/B RCX deck ({subckt})",
        f'.lib "{lib_path}" {sec}',
    ]
    lines += [f'.include "{p.name}"' for p in spice_files]
    lines += [
        f"Vdd vin 0 {vin} ac 0",
        f"Vhost host 0 {host} ac 0",
        f"Venable enable 0 {host}",
        # Real BIAS v2 bandgap + 10 uA current-mode output (Xo0 = 32/4 pfet_lvt, identical to Xpc_ldo0)
        "Vg4 bg_g4 0 0",
        f"Vg3 bg_g3 0 {host}",
        f"Vg2 bg_g2 0 {host}",
        f"Vg1 bg_g1 0 {host}",
        f"Vg0 bg_g0 0 {host}",
        "Xbg bg i_ldo bg_d1 bg_d2 bg_d3 bg_vgi bg_g4 bg_g3 bg_g2 bg_g1 bg_g0 host 0 serdes_bias_ref_v2",
        "Vd1 bg_d1 0 0.9",
        "Vd2 bg_d2 0 0.9",
        "Vd3 bg_d3 0 0.9",
        *[f"Vb{k} b{k} 0 {host if (trim >> k) & 1 else 0}" for k in range(6)],
    ]
    if is_probe:
        lines += [
            f"Xdut vin host quiet bg i_ldo enable b0 b1 b2 b3 b4 b5 fbret fbin 0 {subckt}",
            "Vtest fbin fbret 0 ac 0",
            "Itest 0 fbin 0 ac 0",
        ]
    else:
        lines += [
            f"Xdut vin host quiet bg i_ldo enable b0 b1 b2 b3 b4 b5 0 {subckt}",
        ]
    lines += [
        f"Iload quiet 0 {load_ma}m ac 0",
        ".options reltol=1e-5 abstol=1p vntol=1u",
    ]
    return "\n".join(lines) + "\n"


def interp_log_mag(f: np.ndarray, h: np.ndarray, hz: float) -> float:
    return float(np.exp(np.interp(np.log(hz), np.log(f), np.log(np.maximum(np.abs(h), 1e-18)))))


def compute_gm_db(hz: np.ndarray, gain: np.ndarray) -> tuple[float | None, float | None]:
    """Gain margin (dB) at the first phase crossing of -180 deg after DC."""
    phase = np.unwrap(np.angle(gain)) * 180.0 / np.pi
    # Ensure DC phase starts near 0 deg (not +/-360)
    while phase[0] > 90.0:
        phase -= 360.0
    while phase[0] < -270.0:
        phase += 360.0
    cross_idx = np.flatnonzero((phase[:-1] >= -180.0) & (phase[1:] < -180.0))
    if len(cross_idx) == 0:
        return None, None
    n = int(cross_idx[0])
    a = (-180.0 - phase[n]) / (phase[n + 1] - phase[n])
    f180 = float(np.exp(np.log(hz[n]) * (1.0 - a) + np.log(hz[n + 1]) * a))
    mag180 = float(np.exp(np.log(max(abs(gain[n]), 1e-18)) * (1.0 - a) + np.log(max(abs(gain[n + 1]), 1e-18)) * a))
    gm_db = float(-20.0 * np.log10(max(mag180, 1e-18)))
    return gm_db, f180 / 1e6


def run_probe_dc_ac(work: Path, variant_name: str, rcx_spice: Path) -> dict:
    spice_files = BIAS_V2_FILES + [rcx_spice]
    q_nodes = find_xpass_quiet_nodes(rcx_spice)
    rdiv_q = find_rdiv_quiet_node(rcx_spice)
    res = {
        "variant": variant_name,
        "rcx_path": str(rcx_spice.relative_to(ROOT)),
        "rcx_sha256": hashlib.sha256(rcx_spice.read_bytes()).hexdigest(),
        "xpass_quiet_subnodes": len(q_nodes),
        "rdiv_quiet_node": rdiv_q,
        "ac": [],
    }

    for prof_tag, mos, rc, vin, host, temp, trim in PROFILES:
        wait_for_slot()
        sec = section(mos, rc)
        lib = get_lib(work, sec, spice_files)
        body = circuit_body_v2_cur(
            lib, sec, spice_files, subckt=PROBE_SUBCKT, is_probe=True,
            vin=vin, host=host, trim=trim, load_ma=6.0,
        )
        q_vecs = " ".join(f"v(xdut.{n})" for n in q_nodes)
        rdiv_vec = f"v(xdut.{rdiv_q})" if rdiv_q else ""
        lines = [
            body,
            ".control", "set num_threads=1", "set filetype=binary",
            f"option temp={temp}",
        ]
        for load in (2, 6, 10):
            tag = f"{prof_tag}_l{load}"
            lines += [
                f"alter Iload dc={load}m",
                "alter Iload acmag=0", "alter Vdd acmag=0", "alter Vtest acmag=0", "alter Itest acmag=0",
                "op",
                f"write op_{tag}.raw v(quiet) v(bg) v(i_ldo) v(fbin) v(fbret) i(vdd) {rdiv_vec} {q_vecs}",
                "destroy all",
                # 1. Supply coupling / PSRR (vin -> quiet, i_ldo, fbin)
                "alter Vdd acmag=1",
                "ac dec 20 100 200meg",
                "let qr=real(v(quiet))", "let qi=imag(v(quiet))",
                "let ir=real(v(i_ldo))", "let ii=imag(v(i_ldo))",
                "let fr=real(v(fbin))",  "let fi=imag(v(fbin))",
                f"wrdata {tag}_psrr.tsv qr qi ir ii fr fi", "destroy all",
                "alter Vdd acmag=0",
                # 2. Direct output-to-bias coupling (Iload AC -> v(i_ldo)/v(quiet) and Zout)
                "alter Iload acmag=1",
                "ac dec 20 10k 200meg",
                "let qr=real(v(quiet))", "let qi=imag(v(quiet))",
                "let ir=real(v(i_ldo))", "let ii=imag(v(i_ldo))",
                "let fr=real(v(fbin))",  "let fi=imag(v(fbin))",
                f"wrdata {tag}_q2b.tsv qr qi ir ii fr fi", "destroy all",
                "alter Iload acmag=0",
                # 3. Middlebrook dual-injection loop stability
                "alter Vtest acmag=1",
                "ac dec 20 10 10g",
                "let tv=-v(fbret)/v(fbin)", "let vr=real(tv)", "let vi=imag(tv)",
                f"wrdata {tag}_voltage.tsv vr vi", "destroy all",
                "alter Vtest acmag=0", "alter Itest acmag=1",
                "ac dec 20 10 10g",
                "let ti=i(Vtest)/(1-i(Vtest))", "let ir=real(ti)", "let ii=imag(ti)",
                f"wrdata {tag}_current.tsv ir ii", "destroy all",
                "alter Itest acmag=0",
            ]
        lines += ["quit", ".endc", ".end", ""]
        rdir = spice.next_run_dir(work, f"{variant_name}_probe_dcac_{prof_tag}")
        ex = spice.run("\n".join(lines), rdir, files={p.name: p for p in spice_files}, timeout_s=1200)
        if not ex.ok:
            raise RuntimeError(f"Probe DC/AC failed for {variant_name} {prof_tag}: {rdir}")

        for load in (2, 6, 10):
            tag = f"{prof_tag}_l{load}"
            w = spice.Waves(rdir / f"op_{tag}.raw")
            vq = float(w["v(quiet)"][0])
            vbg = float(w["v(bg)"][0])
            vildo = float(w["v(i_ldo)"][0])
            qs = [float(w[f"v(xdut.{n})"][0]) for n in q_nodes]
            ir_max_mv = float((max(qs) - vq) * 1e3)
            rdiv_err_mv = float((float(w[f"v(xdut.{rdiv_q})"][0]) - vq) * 1e3) if rdiv_q else 0.0

            # PSRR (wrdata format: freq col0 freq col1 ... -> cols 1,3 for v0; 5,7 for v1; 9,11 for v2)
            ap = np.loadtxt(rdir / f"{tag}_psrr.tsv")
            fp = ap[:, 0]
            hq = ap[:, 1] + 1j * ap[:, 3]
            hi = ap[:, 5] + 1j * ap[:, 7]
            psrr_1m = float(-20.0 * np.log10(interp_log_mag(fp, hq, 1e6)))
            psrr_20m = float(-20.0 * np.log10(interp_log_mag(fp, hq, 20e6)))
            psrr_100m = float(-20.0 * np.log10(interp_log_mag(fp, hq, 100e6)))
            psrr_min = float(-20.0 * np.log10(max(float(np.max(np.abs(hq))), 1e-18)))
            vin2ildo_20m = float(20.0 * np.log10(interp_log_mag(fp, hi, 20e6)))

            # Quiet -> i_ldo AC transfer |v(i_ldo) / v(quiet)|
            aq = np.loadtxt(rdir / f"{tag}_q2b.tsv")
            fq = aq[:, 0]
            zq = aq[:, 1] + 1j * aq[:, 3]
            zi = aq[:, 5] + 1j * aq[:, 7]
            q2i = zi / np.where(np.abs(zq) > 1e-18, zq, 1e-18)
            q2i_1m_db = float(20.0 * np.log10(interp_log_mag(fq, q2i, 1e6)))
            q2i_20m_db = float(20.0 * np.log10(interp_log_mag(fq, q2i, 20e6)))
            q2i_100m_db = float(20.0 * np.log10(interp_log_mag(fq, q2i, 100e6)))
            q2i_peak_db = float(20.0 * np.log10(max(float(np.max(np.abs(q2i))), 1e-18)))

            # Middlebrook loop stability
            va_t = np.loadtxt(rdir / f"{tag}_voltage.tsv")
            ia_t = np.loadtxt(rdir / f"{tag}_current.tsv")
            gain = feedback.middlebrook(va_t[:, 1] + 1j * va_t[:, 3], ia_t[:, 1] + 1j * ia_t[:, 3])
            cross = feedback.unity_crossings(va_t[:, 0], gain)
            pm_raw = float(cross[0]["pm_deg"]) if len(cross) == 1 and cross[0]["direction"] == "down" else -999.0
            pm_deg = float((pm_raw + 180.0) % 360.0 - 180.0) if pm_raw > -500 else -999.0
            ugf_mhz = float(cross[0]["hz"] / 1e6) if cross else 0.0
            dc_gain_db = float(20.0 * np.log10(max(abs(gain[0]), 1e-18)))
            gm_db, f180_mhz = compute_gm_db(va_t[:, 0], gain)

            row = dict(
                profile=prof_tag, mos=mos, rc=rc, vin=vin, host=host, temp_c=temp, trim=trim, load_ma=load,
                v_quiet=round(vq, 5), v_bg=round(vbg, 5), v_ildo=round(vildo, 5),
                ir_max_mv=round(ir_max_mv, 3), rdiv_kelvin_err_mv=round(rdiv_err_mv, 4),
                dc_gain_db=round(dc_gain_db, 2), ugf_mhz=round(ugf_mhz, 3),
                pm_deg=round(pm_deg, 2),
                gm_db=round(gm_db, 2) if gm_db is not None else None,
                f180_mhz=round(f180_mhz, 2) if f180_mhz is not None else None,
                crossings=len(cross),
                psrr_1mhz_db=round(psrr_1m, 2), psrr_20mhz_db=round(psrr_20m, 2),
                psrr_100mhz_db=round(psrr_100m, 2), psrr_min_db=round(psrr_min, 2),
                vin2ildo_20mhz_db=round(vin2ildo_20m, 2),
                q2ildo_1mhz_db=round(q2i_1m_db, 2), q2ildo_20mhz_db=round(q2i_20m_db, 2),
                q2ildo_100mhz_db=round(q2i_100m_db, 2), q2ildo_peak_db=round(q2i_peak_db, 2),
            )
            res["ac"].append(row)
            print(
                f"[{variant_name:10s}] {prof_tag:8s} {load:2d}mA | Vq={vq:.4f}V | "
                f"PM={pm_deg:5.2f}deg GM={str(row['gm_db']):>6s}dB UGF={ugf_mhz:6.2f}MHz | "
                f"PSRR20={psrr_20m:5.2f}dB | q->i_ldo(20/100M)={q2i_20m_db:6.2f}/{q2i_100m_db:6.2f}dB",
                flush=True,
            )
    return res


def settling_time_ns(t: np.ndarray, v: np.ndarray, t0: float, t1: float, v_ref: float, band_mv: float = 2.0) -> float:
    mask = (t >= t0) & (t < t1)
    ts, vs = t[mask], v[mask]
    outside = np.flatnonzero(np.abs(vs - v_ref) > band_mv * 1e-3)
    if len(outside) == 0:
        return 0.0
    idx = min(int(outside[-1]) + 1, len(ts) - 1)
    return float((ts[idx] - t0) * 1e9)


def run_transient_step(work: Path, variant_name: str, rcx_spice: Path, is_probe: bool) -> list[dict]:
    spice_files = BIAS_V2_FILES + [rcx_spice]
    subckt = PROBE_SUBCKT if is_probe else PROD_SUBCKT
    kind = "probe" if is_probe else "prod"
    rows = []

    for prof_tag, mos, rc, vin, host, temp, trim in PROFILES:
        wait_for_slot()
        sec = section(mos, rc)
        lib = get_lib(work, sec, spice_files)
        body = circuit_body_v2_cur(
            lib, sec, spice_files, subckt=subckt, is_probe=is_probe,
            vin=vin, host=host, trim=trim, load_ma=6.0,
        )
        # Identical PLL load step: 6 mA baseline, +/-1 mA (1 ns) and +/-4 mA (1 ns)
        body += (
            "Istep quiet 0 pwl(0 0 "
            "0.4u 0 0.401u 1m 0.8u 1m 0.801u 0 "
            "1.2u 0 1.201u -1m 1.6u -1m 1.601u 0 "
            "2.0u 0 2.001u 4m 2.4u 4m 2.401u 0 "
            "2.8u 0 2.801u -4m 3.2u -4m 3.201u 0)\n"
        )
        vecs = ["v(quiet)", "v(i_ldo)", "v(bg)"] + (["v(fbin)", "v(fbret)"] if is_probe else [])
        deck = "\n".join([
            body,
            f".temp {temp}",
            ".control", "set num_threads=1", "set filetype=binary",
            "optran 1 1 1 100n 300u 0",
            "save " + " ".join(vecs),
            "tran 0.2n 3.6u 0 1n",
            "write wave.raw " + " ".join(vecs),
            "quit", ".endc", ".end", "",
        ])
        rdir = spice.next_run_dir(work, f"{variant_name}_{kind}_step_{prof_tag}")
        ex = spice.run(deck, rdir, files={p.name: p for p in spice_files}, timeout_s=900)
        if not ex.ok:
            raise RuntimeError(f"Step failed for {variant_name} {kind} {prof_tag}: {rdir}")

        w = spice.Waves(rdir / "wave.raw")
        t = w.t
        vq = w["v(quiet)"]
        vi = w["v(i_ldo)"]
        pre = t < 0.39e-6
        v0 = float(np.mean(vq[pre]))
        i0 = float(np.mean(vi[pre]))

        s1 = vq[(t >= 0.4e-6) & (t < 2.0e-6)]
        s4 = vq[(t >= 2.0e-6) & (t <= 3.6e-6)]
        i_s1 = vi[(t >= 0.4e-6) & (t < 2.0e-6)]
        i_s4 = vi[(t >= 2.0e-6) & (t <= 3.6e-6)]

        # Settling after +4mA step (2.0..2.4u) and -4mA unload (2.8..3.2u) to within 2 mV of final
        v_s4_hi_end = float(np.mean(vq[(t >= 2.35e-6) & (t < 2.39e-6)]))
        v_s4_lo_end = float(np.mean(vq[(t >= 3.15e-6) & (t < 3.19e-6)]))
        tset_p4 = settling_time_ns(t, vq, 2.0e-6, 2.4e-6, v_s4_hi_end, band_mv=2.0)
        tset_m4 = settling_time_ns(t, vq, 2.8e-6, 3.2e-6, v_s4_lo_end, band_mv=2.0)

        rec = dict(
            variant=variant_name, kind=kind, profile=prof_tag,
            mos=mos, rc=rc, vin=vin, host=host, temp_c=temp, trim=trim,
            v_init=round(v0, 5), v_ildo_init=round(i0, 5),
            step1_droop_mv=round(float((v0 - s1.min()) * 1e3), 2),
            step1_over_mv=round(float((s1.max() - v0) * 1e3), 2),
            step4_droop_mv=round(float((v0 - s4.min()) * 1e3), 2),
            step4_over_mv=round(float((s4.max() - v0) * 1e3), 2),
            step4_min_v=round(float(s4.min()), 4),
            step4_max_v=round(float(s4.max()), 4),
            settle_p4m_2mv_ns=round(tset_p4, 1),
            settle_m4m_2mv_ns=round(tset_m4, 1),
            ildo_kick_1m_pp_mv=round(float(np.ptp(i_s1) * 1e3), 4),
            ildo_kick_4m_pp_mv=round(float(np.ptp(i_s4) * 1e3), 4),
            ildo_kick_4m_max_mv=round(float(np.max(np.abs(i_s4 - i0)) * 1e3), 4),
            elapsed_s=round(ex.elapsed_s, 1),
        )
        if is_probe:
            vf = w["v(fbin)"]
            f0 = float(np.mean(vf[pre]))
            f_s4 = vf[(t >= 2.0e-6) & (t <= 3.6e-6)]
            rec["fbin_kick_4m_pp_mv"] = round(float(np.ptp(f_s4) * 1e3), 2)
            rec["fbin_init_v"] = round(f0, 5)

        rows.append(rec)
        print(
            f"[{variant_name:10s}/{kind:5s}] STEP {prof_tag:8s} ({ex.elapsed_s:5.1f}s) | "
            f"+/-1mA: -{rec['step1_droop_mv']:.1f}/+{rec['step1_over_mv']:.1f}mV | "
            f"+/-4mA: [{rec['step4_min_v']:.4f}, {rec['step4_max_v']:.4f}]V "
            f"(settle={tset_p4:.0f}/{tset_m4:.0f}ns) | "
            f"i_ldo_kick(4mA)={rec['ildo_kick_4m_pp_mv']:.4f}mVpp",
            flush=True,
        )
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", type=Path,
                    default=ROOT / "results/analog/ldo/v2_cur_kelvin_ab_20261125")
    ap.add_argument("--base-dir", type=Path,
                    default=ROOT / "analog/ldo/layout/variants/v2_cur_pdk")
    ap.add_argument("--opt-dir", type=Path,
                    default=ROOT / "analog/ldo/layout/variants/v2_cur_kelvin_pdk")
    ap.add_argument("--only", choices=("all", "baseline", "kelvin_opt"), default="all")
    ap.add_argument("--summary-name", default="summary.json")
    ap.add_argument("--max-host-slots", type=int, default=4)
    args = ap.parse_args()

    global wait_for_slot
    _orig_wait = wait_for_slot
    wait_for_slot = lambda max_total=args.max_host_slots: _orig_wait(max_total=max_total)

    work = args.work_dir.resolve()
    work.mkdir(parents=True, exist_ok=True)

    summary = {
        "base_dir": str(args.base_dir),
        "opt_dir": str(args.opt_dir),
        "profiles": PROFILES,
        "dc_ac": {},
        "step_probe": {},
        "step_prod": {},
    }

    pairs = [("baseline", args.base_dir.resolve()), ("kelvin_opt", args.opt_dir.resolve())]
    if args.only != "all":
        pairs = [p for p in pairs if p[0] == args.only]

    for name, vdir in pairs:
        probe_rcx = vdir / f"{PROBE_SUBCKT}_rcx.spice"
        prod_rcx = vdir / f"{PROD_SUBCKT}_rcx.spice"
        print(f"\n==================== {name.upper()} ({vdir.name}) ====================", flush=True)
        summary["dc_ac"][name] = run_probe_dc_ac(work, name, probe_rcx)
        summary["step_probe"][name] = run_transient_step(work, name, probe_rcx, is_probe=True)
        summary["step_prod"][name] = run_transient_step(work, name, prod_rcx, is_probe=False)
        (work / args.summary_name).write_text(json.dumps(summary, indent=2) + "\n")

    print(f"\nSAVED: {(work / args.summary_name).relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
