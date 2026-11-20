"""LDO v2 comprehensive single-worker verification & exploration testbench.

Reuses the exact boundary conditions, real bandgap/bias copy, dual-injection
Middlebrook loop stability, 1kHz-200MHz noise, 180us zero-start startup, and
6mA +/- 0.1/1/4 mA (1ns) load-step protocols from analog/common/ldo/tb/cap_sizing/
for 100% apples-to-apples comparison against r4 and smallcap.

Strictly enforces max 1 concurrent ngspice worker (respecting host 4-slot limit).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import feedback, model_library, project, spice, watch

ROOT = project.ROOT
REG_PATH = ROOT / "analog/common/ldo/tb/regulation/run.py"
spec = importlib.util.spec_from_file_location("ldo_reg_v2", REG_PATH)
reg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reg)

V2_CELLS = reg.BIAS + [
    ROOT / "analog/common/ldo/spice/ldo_v2_passives.spice",
    ROOT / "analog/common/ldo/spice/ldo_hv18_core_v2.spice",
    ROOT / "analog/common/ldo/spice/pll_supply_hv18_v2.spice",
]
OUT_ROOT = ROOT / "results/analog/common/ldo/v2"

DC_VECTORS = (
    "v(quiet)", "v(bg)", "v(xdut.ref_local)", "v(xdut.ibias)",
    "v(xdut.xcore.gate)", "v(xdut.xcore.casg)", "v(xdut.xcore.va)",
    "v(xdut.xcore.pre_g)", "v(xdut.xcore.mid)", "v(xdut.vg_clamp)",
    "v(xdut.cl_nb)", "i(vdd)", "i(vhost)",
)
AC_NODES = ("quiet", "xdut.ref_local", "bg", "xdut.ibias", "xdut.xcore.gate")


def section(mos: str, rc: str) -> str:
    return mos if rc == "tt" else (rc if mos == "tt" else f"{mos}_{rc}")


def required_primitives(spice_files: list[Path]) -> list[str]:
    text = "\n".join(p.read_text() for p in spice_files)
    return sorted(set(re.findall(r"\bsky130_fd_pr__\w+", text)))


def get_lib(work: Path, sec: str, spice_files: list[Path], reduced: bool) -> Path:
    if not reduced:
        return project.model_library()
    lib_dir = work / "_models" / sec
    if not (lib_dir / "sky130.lib.spice").exists():
        model_library.build(project.model_library(), sec, required_primitives(spice_files), lib_dir)
    return lib_dir / "sky130.lib.spice"


def circuit_body(lib_path: Path, sec: str, spice_files: list[Path], subckt: str = "serdes_pll_supply_hv18_v2_probe", trim: int = 41) -> str:
    lines = [
        f"* LDO v2 verification deck ({subckt})",
        f'.lib "{lib_path}" {sec}',
    ]
    lines += [f'.include "{p.name}"' for p in spice_files]
    lines += [
        "Vdd vin 0 3.3 ac 0",
        "Vhost host 0 1.8 ac 0",
        "Venable enable 0 1.8",
        "Voffset bg rawref 0 ac 0",
        "Xbg rawref host host host host vgi host 0 serdes_bias_ref trim=15",
        *[f"Vb{k} b{k} 0 {1.8 if (trim >> k) & 1 else 0}" for k in range(6)],
        f"Xdut vin host quiet bg vgi enable b0 b1 b2 b3 b4 b5 fbret fbin 0 {subckt}",
        "Vtest fbin fbret 0 ac 0",
        "Itest 0 fbin 0 ac 0",
        "Iload quiet 0 6m",
        ".options reltol=1e-5 abstol=1p vntol=1u",
    ]
    return "\n".join(lines) + "\n"


def interp_ac(a: np.ndarray, hz: float, col: int = 0) -> float:
    v = a[:, 1 + col * 2] + 1j * a[:, 2 + col * 2]
    return float(np.exp(np.interp(np.log(hz), np.log(a[:, 0]), np.log(np.abs(v)))))


def ac_write(stem: str, kind: str, nodes: tuple[str, ...]) -> list[str]:
    lines, names = [], []
    for n, node in enumerate(nodes):
        lines += [f"let r{n}=real(v({node}))", f"let q{n}=imag(v({node}))"]
        names += [f"r{n}", f"q{n}"]
    return lines + [f"wrdata {stem}_{kind}.tsv " + " ".join(names), "destroy all"]


def run_slot_guard() -> None:
    active = len(watch.ngspice_cwds())
    if active >= 4:
        raise RuntimeError(f"Global ngspice slot limit reached ({active}/4 active)")


def calibrate_corners(work: Path, corners: list[tuple[str, str]], spice_files: list[Path],
                      subckt: str, reduced: bool, pex_mode: bool = False) -> dict[str, dict]:
    """Calibrate trim code at 27C / HV3.3 / host1.8 / 6mA once per MOS/RC corner."""
    codes = {}
    for mos, rc in corners:
        run_slot_guard()
        sec = section(mos, rc)
        lib = get_lib(work, sec, spice_files, reduced)
        lines = [
            circuit_body(lib, sec, spice_files, subckt=subckt),
            ".control", "set num_threads=1", "set filetype=binary",
            "option temp=27", "alter Vdd dc=3.3", "alter Vhost dc=1.8", "alter Venable dc=1.8",
            "alter Iload dc=6m",
        ]
        for k in range(64):
            lines += [f"alter Vb{b} dc={1.8 if (k >> b) & 1 else 0}" for b in range(6)]
            lines += ["op", f"write cal_{k:02d}.raw v(quiet) v(bg)", "destroy all"]
        lines += ["quit", ".endc", ".end", ""]
        rdir = spice.next_run_dir(work, f"cal_{mos}_{rc}")
        ex = spice.run("\n".join(lines), rdir, files={p.name: p for p in spice_files}, timeout_s=900)
        if not ex.ok:
            raise RuntimeError(f"Calibration failed for {mos}:{rc}: {rdir}")
        vouts = [float(spice.Waves(rdir / f"cal_{k:02d}.raw")["v(quiet)"][0]) for k in range(64)]
        diffs = np.diff(vouts)
        monotonic = bool(np.all(diffs > 0))
        best = int(np.argmin([abs(v - 1.8) for v in vouts]))
        codes[f"{mos}:{rc}"] = dict(
            trim=best, vout_v=vouts[best], vout_min=vouts[0], vout_max=vouts[-1],
            monotonic=monotonic, min_step_mv=float(diffs.min() * 1e3), max_step_mv=float(diffs.max() * 1e3),
            vouts=vouts,
        )
        print(f"CAL {mos}:{rc} -> trim={best}, vout={vouts[best]:.5f}V, range=[{vouts[0]:.4f}, {vouts[-1]:.4f}]V, "
              f"mono={monotonic}, step=[{diffs.min()*1e3:.2f}, {diffs.max()*1e3:.2f}] mV", flush=True)
    return codes


def run_dc_ac_suite(work: Path, suite: str, codes: dict[str, dict], spice_files: list[Path],
                    subckt: str, reduced: bool, pex_mode: bool = False) -> list[dict]:
    if suite == "screen":
        groups = [
            ("tt", "tt", [(3.3, 1.8, 27, 2), (3.3, 1.8, 27, 6), (3.3, 1.8, 27, 10)]),
            ("fs", "ll", [(3.0, 1.95, 85, 2), (3.0, 1.95, 85, 10), (3.6, 1.95, 85, 2), (3.0, 1.65, 85, 10)]),
            ("ss", "hh", [(3.0, 1.65, -40, 2), (3.0, 1.65, -40, 10)]),
            ("sf", "hh", [(3.0, 1.65, 85, 2), (3.0, 1.65, 85, 10)]),
            ("ff", "ll", [(3.6, 1.95, -40, 2), (3.6, 1.95, -40, 10)]),
        ]
    elif suite == "pvt":
        groups = [
            (mos, rc, [
                (h, u, t, i)
                for h in (3.0, 3.6, 3.3)
                for u in (1.65, 1.95, 1.8)
                for t in (-40, 85, 27)
                for i in (2, 10, 6)
            ])
            for mos in ("fs", "ss", "sf", "ff", "tt")
            for rc in ("ll", "hh", "tt")
        ]
    else:
        raise ValueError(suite)

    dc_vecs = ("v(quiet)", "v(bg)", "i(vdd)", "i(vhost)") if pex_mode else DC_VECTORS
    ac_nodes = ("quiet", "bg") if pex_mode else AC_NODES
    rows = []

    for mos, rc, pts in groups:
        run_slot_guard()
        sec = section(mos, rc)
        lib = get_lib(work, sec, spice_files, reduced)
        trim = codes[f"{mos}:{rc}"]["trim"]
        lines = [
            circuit_body(lib, sec, spice_files, subckt=subckt, trim=trim),
            ".control", "set num_threads=1", "set filetype=binary",
            "set wr_singlescale", "set wr_vecnames",
        ]
        case_meta = []
        for idx, (hv, host, temp, load) in enumerate(pts):
            do_ac = (suite != "pvt") or (
                hv in (3.0, 3.6) and host in (1.65, 1.95) and temp in (-40, 85) and load in (2, 10)
            ) or (hv, host, temp, load) == (3.3, 1.8, 27, 6)
            stem = f"c{idx:04d}"
            case_meta.append(dict(stem=stem, mos=mos, rc=rc, hv_v=hv, host_v=host, temp_c=temp, load_ma=load, trim=trim, ac=do_ac))
            lines += [
                f"option temp={temp}", f"alter Vdd dc={hv}", f"alter Vhost dc={host}", f"alter Venable dc={host}",
                *[f"alter Vb{k} dc={host if (trim >> k) & 1 else 0}" for k in range(6)],
                f"dc Iload {load}m {load + 0.001}m 1u",
                f"write {stem}_dc.raw " + " ".join(dc_vecs),
                "destroy all",
            ]
            if do_ac:
                lines += [
                    f"alter Iload dc={load}m",
                    "alter Vdd acmag=1", "alter Vhost acmag=0", "alter Vtest acmag=0", "alter Itest acmag=0",
                    "ac dec 20 10 200meg",
                ] + ac_write(stem, "hv", ac_nodes)
                lines += [
                    "alter Vdd acmag=0", "alter Vhost acmag=1",
                    "ac dec 20 10 200meg",
                ] + ac_write(stem, "host", ac_nodes)
                lines += [
                    "alter Vhost acmag=0", "alter Vtest acmag=1",
                    "ac dec 20 10 10g",
                    "let tv=-v(fbret)/v(fbin)", "let vr=real(tv)", "let vi=imag(tv)",
                    f"wrdata {stem}_voltage.tsv vr vi", "destroy all",
                    "alter Vtest acmag=0", "alter Itest acmag=1",
                    "ac dec 20 10 10g",
                    "let ti=i(Vtest)/(1-i(Vtest))", "let ir=real(ti)", "let ii=imag(ti)",
                    f"wrdata {stem}_current.tsv ir ii", "destroy all",
                    "alter Itest acmag=0",
                ]
        lines += ["quit", ".endc", ".end", ""]
        rdir = spice.next_run_dir(work, f"dcac_{mos}_{rc}")
        ex = spice.run("\n".join(lines), rdir, files={p.name: p for p in spice_files},
                       timeout_s=300 + len(pts) * (45 if pex_mode else 15))
        if not ex.ok:
            raise RuntimeError(f"DC/AC failed for {mos}:{rc}: {rdir}")
        for m in case_meta:
            stem = m["stem"]
            w = spice.Waves(rdir / f"{stem}_dc.raw")
            row = dict(m, vout_v=float(w["v(quiet)"][0]),
                       vin_excess_ua=float((-w["i(vdd)"][0] - m["load_ma"] * 1e-3) * 1e6),
                       host_ua=float(-w["i(vhost)"][0] * 1e6))
            if not pex_mode:
                row.update(
                    va_v=float(w["v(xdut.xcore.va)"][0]),
                    pre_g_v=float(w["v(xdut.xcore.pre_g)"][0]),
                    casg_v=float(w["v(xdut.xcore.casg)"][0]),
                    mid_v=float(w["v(xdut.xcore.mid)"][0]),
                    gate_v=float(w["v(xdut.xcore.gate)"][0]),
                    vg_clamp_v=float(w["v(xdut.vg_clamp)"][0]),
                    cl_nb_v=float(w["v(xdut.cl_nb)"][0]),
                )
            if m["ac"]:
                hv_a = np.loadtxt(rdir / f"{stem}_hv.tsv", skiprows=1)
                host_a = np.loadtxt(rdir / f"{stem}_host.tsv", skiprows=1)
                va_t = np.loadtxt(rdir / f"{stem}_voltage.tsv", skiprows=1)
                ia_t = np.loadtxt(rdir / f"{stem}_current.tsv", skiprows=1)
                gain = feedback.middlebrook(va_t[:, 1] + 1j * va_t[:, 2], ia_t[:, 1] + 1j * ia_t[:, 2])
                cross = feedback.unity_crossings(va_t[:, 0], gain)
                row.update(
                    psrr20_db=float(-20 * np.log10(interp_ac(hv_a, 20e6))),
                    psrr1_db=float(-20 * np.log10(interp_ac(hv_a, 1e6))),
                    host1_v_v=interp_ac(host_a, 1e6),
                    host20_v_v=interp_ac(host_a, 20e6),
                    crossings=cross,
                    pm_deg=float(cross[0]["pm_deg"]) if len(cross) == 1 and cross[0]["direction"] == "down" else -999.0,
                    ugbw_mhz=float(cross[0]["hz"] / 1e6) if cross else 0.0,
                )
            rows.append(row)
        ac_rows = [r for r in rows if r["mos"] == mos and r["rc"] == rc and r["ac"]]
        dc_rows = [r for r in rows if r["mos"] == mos and r["rc"] == rc]
        print(
            f"DC/AC {mos}:{rc} ({len(dc_rows)} DC, {len(ac_rows)} AC, {ex.elapsed_s:.1f}s) | "
            f"Vout=[{min(r['vout_v'] for r in dc_rows):.4f}, {max(r['vout_v'] for r in dc_rows):.4f}]V | "
            f"PSRR20_min={min(r['psrr20_db'] for r in ac_rows):.2f}dB | "
            f"PM_min={min(r['pm_deg'] for r in ac_rows):.2f}deg | "
            f"Iq_max={max(r['vin_excess_ua'] for r in dc_rows):.1f}uA",
            flush=True,
        )
    return rows


def run_dynamic_suite(work: Path, codes: dict[str, dict], spice_files: list[Path],
                      subckt: str, reduced: bool, modes: tuple[str, ...] = ("step", "noise", "startup", "off"),
                      profiles: list[tuple] | None = None, pex_mode: bool = False) -> dict:
    if profiles is None:
        profiles = [
            ("tt", "tt", 3.3, 1.8, 27),
            ("fs", "ll", 3.0, 1.95, 85),
            ("ss", "hh", 3.0, 1.65, -40),
            ("ff", "ll", 3.6, 1.95, -40),
        ]
    results = {m: [] for m in modes}

    for mos, rc, hv, host, temp in profiles:
        sec = section(mos, rc)
        trim = codes[f"{mos}:{rc}"]["trim"]
        lib = get_lib(work, sec, spice_files, reduced)

        if "step" in modes:
            run_slot_guard()
            body = circuit_body(lib, sec, spice_files, subckt=subckt, trim=trim)
            body = re.sub(r"^Vdd .*$", f"Vdd vin 0 {hv} ac 0", body, flags=re.M)
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
            vecs = ["v(quiet)", "i(vdd)"] if pex_mode else ["v(quiet)", "v(xdut.xcore.gate)", "v(xdut.vg_clamp)", "v(xdut.cl_nb)", "i(vdd)"]
            deck = "\n".join([
                body, f".temp {temp}", ".control", "set num_threads=1", "set filetype=binary",
                "optran 1 1 1 100n 300u 0",
                "save " + " ".join(vecs),
                "tran 0.2n 3u 0 1n",
                "write wave.raw " + " ".join(vecs),
                "quit", ".endc", ".end", "",
            ])
            rdir = spice.next_run_dir(work, f"step_{mos}_{rc}")
            ex = spice.run(deck, rdir, files={p.name: p for p in spice_files}, timeout_s=600)
            if not ex.ok:
                raise RuntimeError(f"Step failed for {mos}:{rc}: {rdir}")
            w = spice.Waves(rdir / "wave.raw")
            v = w["v(quiet)"]
            base = float(np.mean(v[w.t < 0.49e-6]))
            steps = []
            for d, a, b in [(0.1, 0.5e-6, 1.3e-6), (1.0, 1.3e-6, 2.1e-6), (4.0, 2.1e-6, 3.0e-6)]:
                seg = v[(w.t >= a) & (w.t < b)]
                steps.append(dict(delta_ma=d, droop_mv=float((base - seg.min()) * 1e3),
                                  overshoot_mv=float((seg.max() - base) * 1e3),
                                  v_min=float(seg.min()), v_max=float(seg.max())))
            rec = dict(mos=mos, rc=rc, hv_v=hv, host_v=host, temp_c=temp,
                       baseline_v=base, v_min=float(v.min()), v_max=float(v.max()),
                       steps=steps, elapsed_s=round(ex.elapsed_s, 1))
            if not pex_mode:
                rec["vg_clamp_max_v"] = float(w["v(xdut.vg_clamp)"].max())
                rec["vg_clamp_dc_v"] = float(np.mean(w["v(xdut.vg_clamp)"][w.t < 0.49e-6]))
            results["step"].append(rec)
            print(
                f"STEP {mos}:{rc} ({ex.elapsed_s:.1f}s) | base={base:.4f}V | "
                f"1mA: -{steps[1]['droop_mv']:.1f}/+{steps[1]['overshoot_mv']:.1f}mV | "
                f"4mA: Vmin={steps[2]['v_min']:.4f}V (-{steps[2]['droop_mv']:.1f}mV), "
                f"Vmax={steps[2]['v_max']:.4f}V (+{steps[2]['overshoot_mv']:.1f}mV)"
                + (f" | Vg_cl={rec['vg_clamp_dc_v']:.3f}->{rec['vg_clamp_max_v']:.3f}V" if not pex_mode else ""),
                flush=True,
            )

        if "noise" in modes:
            for load in (2, 10):
                run_slot_guard()
                # Noise ALWAYS uses full PDK unless reduced explicitly requested, check reduced flag
                body = circuit_body(lib, sec, spice_files, subckt=subckt, trim=trim)
                body = re.sub(r"^Vdd .*$", f"Vdd vin 0 {hv} ac 0", body, flags=re.M)
                body = re.sub(r"^Vhost .*$", f"Vhost host 0 {host} ac 0", body, flags=re.M)
                body = re.sub(r"^Venable .*$", f"Venable enable 0 {host}", body, flags=re.M)
                for k in range(6):
                    body = re.sub(rf"^Vb{k} .*$", f"Vb{k} b{k} 0 {host if (trim >> k) & 1 else 0}", body, flags=re.M)
                body = re.sub(r"^Iload .*$", f"Iload quiet 0 {load}m", body, flags=re.M)
                deck = "\n".join([
                    body, f".temp {temp}", ".control", "set num_threads=1", "set filetype=binary",
                    "op", "write op.raw v(quiet) i(vdd)", "destroy all",
                    "noise v(quiet) Vdd dec 40 1k 200meg",
                    "setplot noise1", "write noise.raw frequency onoise_spectrum",
                    "quit", ".endc", ".end", "",
                ])
                rdir = spice.next_run_dir(work, f"noise_{mos}_{rc}_{load}")
                ex = spice.run(deck, rdir, files={p.name: p for p in spice_files}, timeout_s=300)
                if not ex.ok:
                    raise RuntimeError(f"Noise failed for {mos}:{rc} {load}mA: {rdir}")
                nw = spice.Waves(rdir / "noise.raw")
                op = spice.Waves(rdir / "op.raw")
                uv = float(np.sqrt(np.trapezoid(nw["onoise_spectrum"] ** 2, nw.t)) * 1e6)
                rec = dict(mos=mos, rc=rc, load_ma=load, vout_v=float(op["v(quiet)"][0]), noise_uv=uv, elapsed_s=round(ex.elapsed_s, 1))
                results["noise"].append(rec)
                print(f"NOISE {mos}:{rc} {load}mA ({ex.elapsed_s:.1f}s) | Vout={rec['vout_v']:.4f}V | {uv:.2f} uVrms", flush=True)

        if "startup" in modes:
            for load in (2, 10):
                run_slot_guard()
                body = circuit_body(lib, sec, spice_files, subckt=subckt, trim=trim)
                body = re.sub(r"^Vdd .*$", f"Vdd vin 0 pwl(0 0 20n 0 120n {hv})", body, flags=re.M)
                body = re.sub(r"^Vhost .*$", f"Vhost host 0 pwl(0 0 20n 0 120n {host})", body, flags=re.M)
                body = re.sub(r"^Venable .*$", f"Venable enable 0 pwl(0 0 250n 0 255n {host})", body, flags=re.M)
                for k in range(6):
                    body = re.sub(rf"^Vb{k} .*$", f"Ebit{k} b{k} 0 host 0 {int(bool((trim >> k) & 1))}", body, flags=re.M)
                body = re.sub(r"^Iload .*$", f"Rload quiet 0 {1800 / load}", body, flags=re.M)
                vecs = ["v(quiet)", "i(vdd)"] if pex_mode else ["v(quiet)", "v(xdut.ref_local)", "v(xdut.xcore.va)", "v(xdut.xcore.casg)", "v(xdut.xcore.gate)"]
                deck = "\n".join([
                    body, f".temp {temp}", ".control", "set num_threads=1", "set filetype=binary",
                    "save " + " ".join(vecs),
                    "tran 20n 180u 0 20n",
                    "write wave.raw " + " ".join(vecs),
                    "quit", ".endc", ".end", "",
                ])
                rdir = spice.next_run_dir(work, f"startup_{mos}_{rc}_{load}")
                ex = spice.run(deck, rdir, files={p.name: p for p in spice_files}, timeout_s=600)
                if not ex.ok:
                    raise RuntimeError(f"Startup failed for {mos}:{rc} {load}mA: {rdir}")
                w = spice.Waves(rdir / "wave.raw")
                v = w["v(quiet)"]
                last = w.t >= w.t[-1] * 0.95
                vfin = float(np.mean(v[last]))
                outside = np.flatnonzero(np.abs(v - vfin) > 0.01)
                settle_us = float(w.t[min(outside[-1] + 1, len(w.t) - 1)] * 1e6) if len(outside) else 0.0
                rec = dict(mos=mos, rc=rc, load_ma=load, v_final=vfin, v_max=float(v.max()),
                           settle_10mv_us=settle_us, last_pp_mv=float(np.ptp(v[last]) * 1e3), elapsed_s=round(ex.elapsed_s, 1))
                results["startup"].append(rec)
                print(f"STARTUP {mos}:{rc} {load}mA ({ex.elapsed_s:.1f}s) | Vfin={vfin:.4f}V | Vmax={rec['v_max']:.4f}V | "
                      f"settle_10mV={settle_us:.1f}us", flush=True)

        if "off" in modes and (mos, rc) in (("tt", "tt"), ("ff", "ll")):
            run_slot_guard()
            # Check BOTH (a) External 1.8V static bypass: vin=quiet=1.8V, enable=0
            # and (b) HV disabled mode: vin=3.6V, enable=0, 100k load
            body = circuit_body(lib, sec, spice_files, subckt=subckt, trim=trim)
            body = re.sub(r"^Venable .*$", "Venable enable 0 0", body, flags=re.M)
            body = re.sub(r"^Iload .*$", "Rload_off quiet 0 100k", body, flags=re.M)
            # Mode A: HV disabled
            deck_a = "\n".join([
                re.sub(r"^Vdd .*$", "Vdd vin 0 3.6", body, flags=re.M),
                f".temp {temp}", ".control", "set num_threads=1", "set filetype=binary",
                "op", "write off_hv.raw v(quiet) i(vdd) i(vhost)", "quit", ".endc", ".end", "",
            ])
            rdir_a = spice.next_run_dir(work, f"off_hv_{mos}_{rc}")
            ex_a = spice.run(deck_a, rdir_a, files={p.name: p for p in spice_files}, timeout_s=180)
            wa = spice.Waves(rdir_a / "off_hv.raw")
            # Mode B: External 1.8V static bypass (vin=quiet=1.8V, enable=0)
            body_b = re.sub(r"^Vdd .*$", "Vdd vin 0 1.8", body, flags=re.M)
            body_b = re.sub(r"^Rload_off .*$", "Vext_bypass quiet vin 0", body_b, flags=re.M)
            deck_b = "\n".join([
                body_b, f".temp {temp}", ".control", "set num_threads=1", "set filetype=binary",
                "op", "write off_byp.raw v(quiet) i(vdd) i(vhost) i(Vext_bypass)", "quit", ".endc", ".end", "",
            ])
            rdir_b = spice.next_run_dir(work, f"off_byp_{mos}_{rc}")
            ex_b = spice.run(deck_b, rdir_b, files={p.name: p for p in spice_files}, timeout_s=180)
            wb = spice.Waves(rdir_b / "off_byp.raw")
            rec = dict(
                mos=mos, rc=rc, temp_c=temp,
                hv_off_vquiet_v=float(wa["v(quiet)"][0]),
                hv_off_ivdd_ua=float(-wa["i(vdd)"][0] * 1e6),
                byp18_ivdd_ua=float(-wb["i(vdd)"][0] * 1e6),
                byp18_ihost_ua=float(-wb["i(vhost)"][0] * 1e6),
            )
            results["off"].append(rec)
            print(f"OFF {mos}:{rc} | HV3.6_off: Vq={rec['hv_off_vquiet_v']:.4f}V, Ivin={rec['hv_off_ivdd_ua']:.2f}uA | "
                  f"Bypass1.8: Ivin={rec['byp18_ivdd_ua']:.2f}uA", flush=True)

    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tag", default="explore")
    ap.add_argument("--suite", choices=("screen", "pvt"), default="screen")
    ap.add_argument("--modes", nargs="+", default=["dcac", "step", "noise", "startup", "off"])
    ap.add_argument("--reduced", action="store_true")
    ap.add_argument("--pex-macro", type=Path, default=None, help="Full extracted probe macro .spice (CPEX or RCX)")
    ap.add_argument("--subckt", default="serdes_pll_supply_hv18_v2_probe")
    ap.add_argument("--profiles", nargs="+", default=["tt", "fs", "ss", "ff"])
    args = ap.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    work = OUT_ROOT / f"{ts}_{args.tag}"
    work.mkdir(parents=True)

    pex_mode = args.pex_macro is not None
    if pex_mode:
        pex_path = args.pex_macro.resolve()
        spice_files = reg.BIAS + [pex_path]
        subckt = args.subckt
    else:
        spice_files = V2_CELLS
        subckt = args.subckt

    if args.suite == "screen":
        corners = [("tt", "tt"), ("fs", "ll"), ("ss", "hh"), ("sf", "hh"), ("ff", "ll")]
    else:
        corners = [(m, r) for m in ("fs", "ss", "sf", "ff", "tt") for r in ("ll", "hh", "tt")]

    codes = calibrate_corners(work, corners, spice_files, subckt, args.reduced, pex_mode=pex_mode)
    out = dict(tag=args.tag, suite=args.suite, reduced=args.reduced, pex_mode=pex_mode,
               subckt=subckt, calibration=codes)

    if "dcac" in args.modes:
        out["dcac"] = run_dc_ac_suite(work, args.suite, codes, spice_files, subckt, args.reduced, pex_mode=pex_mode)

    dyn_modes = tuple(m for m in ("step", "noise", "startup", "off") if m in args.modes)
    if dyn_modes:
        all_profs = [
            ("tt", "tt", 3.3, 1.8, 27),
            ("fs", "ll", 3.0, 1.95, 85),
            ("ss", "hh", 3.0, 1.65, -40),
            ("ff", "ll", 3.6, 1.95, -40),
        ]
        sel_profs = [p for p in all_profs if p[0] in args.profiles]
        out["dynamic"] = run_dynamic_suite(work, codes, spice_files, subckt, args.reduced,
                                           modes=dyn_modes, profiles=sel_profs, pex_mode=pex_mode)

    summary_path = work / "summary.json"
    summary_path.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nSAVED: {summary_path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
