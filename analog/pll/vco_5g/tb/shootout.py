#!/usr/bin/env python3
"""5 Gb/s Stretch-Goal VCO Architecture Shootout in SKY130A (2.50 GHz Quadrature).

Apples-to-apples benchmark of 3 next-generation VCO architectures (100% real SKY130A PDK devices)
across 5 PVT x RC corners (TT 1.80V 27C tt, SS 1.65V 85C hh, SF 1.65V 85C hh, FS 1.65V 85C hh,
FF 1.95V -40C ll), isolated cleanly under analog/pll/vco_5g/:

  Arch A: Supply-Regulated Pseudo-Differential CMOS Inverter Ring VCO (4-stage / 8-phase)
  Arch B: Maneatis Self-Biased Symmetric-Load Ring VCO (4-stage / 8-phase, pfet_lvt load + replica OTA)
  Arch C: 5.0 GHz Complementary Cross-Coupled LC-VCO (SKY130A met4||met5 octagonal L) + Quadrature /2

Usage:
    uv run python analog/pll/vco_5g/tb/shootout.py [--stage all] [--workers 2]

Stages (independently resumable under results/analog/pll/vco_5g/shootout_20261123/):
  range   Full tuning range sweep + inductor AC Q check across 5 PVT x RC corners
  lock    Exact 2.500 GHz lock calibration, Kvco, Kb/Kvreg, DC Kvdd, swing, power, quadrature, waveforms
  psrr    20 MHz AC supply-tone pushing Kvdd(20 MHz) via harmonic phasor fit
  isf     Hajimiri-Lee periodic impulse response (ISF) & cyclostationary gm(x)/Id(x) probes
  noise   ngspice .noise (sparse) for all FETs, regulators/bias, inductor pi-tank, noisy=1 varactor, bank, /2
  synth   L(df) breakdown, Leeson LC cross-check, FoM/FoM_T, 5 Gb/s PLL RMS jitter & CDR 14.07 sigma
  plot    4-panel comparison figure at docs/figures/clocking/vco_5g_shootout_20261123.png

Hard constraints:
  - Strictly workers <= 2 for ngspice (num_threads=1, filetype=binary, skip_output_before, t_end check).
  - Zero modifications to signed-off 4 Gb/s mainline files or config/*_working_revision.toml.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, noise_models, pnoise, project, spice
from serdes_flow.corners import Condition
from serdes_flow.waves import crossings

ROOT = project.ROOT
OUT = ROOT / "results/analog/pll/vco_5g/shootout_20261123"
FIG_OUT = ROOT / "docs/figures/clocking/vco_5g_shootout_20261123.png"

PRIMS = ROOT / "analog/common/devices/spice/sky130_primitives.spice"
PLVT = ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice"
NET_A = ROOT / "analog/pll/vco_5g/spice/ring_cmos_reg.spice"
NET_B = ROOT / "analog/pll/vco_5g/spice/ring_maneatis.spice"
NET_C = ROOT / "analog/pll/vco_5g/spice/lc_5g_div2.spice"

R6_SYNTH = ROOT / "results/analog/pll/vco/r6_ptat_perf_20261123/stage6_synth/summary.json"
R6_NOISE = ROOT / "results/analog/pll/vco/r6_ptat_perf_20261123/stage5_noise/summary.json"
R6_CALIB = ROOT / "results/analog/pll/vco/r6_ptat_perf_20261123/stage1_calib/summary.json"
R6_PSRR = ROOT / "results/analog/pll/vco/r6_ptat_perf_20261123/stage3_psrr/summary.json"

TARGET_OUT = 2.5e9       # 2.50 GHz quadrature output for 5 Gb/s half-rate SerDes
TARGET_LC = 5.0e9        # 5.00 GHz LC tank -> /2 -> 2.50 GHz I/Q
UI_5G = 200e-12          # 5 Gb/s unit interval = 200 ps

# Exact 5 PVT x RC corners requested for the 5 Gb/s VCO shootout
CORNERS = [
    dict(key="tt_v1800_t27:tt",  label="TT 1.80V 27°C tt",   short="TT 27°C",
         rm_scale=1.00, c_scale=1.00, cp_ref="tt_v1800_t27:tt",  pfd_duty=0.122),
    dict(key="ss_v1650_t85:hh",  label="SS 1.65V 85°C hh",   short="SS 85°C hh",
         rm_scale=1.22, c_scale=1.12, cp_ref="ss_v1650_t-40:hh", pfd_duty=0.180),
    dict(key="sf_v1650_t85:hh",  label="SF 1.65V 85°C hh",   short="SF 85°C hh",
         rm_scale=1.22, c_scale=1.12, cp_ref="sf_v1650_t85:hh",  pfd_duty=0.145),
    dict(key="fs_v1650_t85:hh",  label="FS 1.65V 85°C hh",   short="FS 85°C hh",
         rm_scale=1.22, c_scale=1.12, cp_ref="fs_v1650_t85:hh",  pfd_duty=0.138),
    dict(key="ff_v1950_t-40:ll", label="FF 1.95V -40°C ll",  short="FF -40°C ll",
         rm_scale=0.75, c_scale=0.88, cp_ref="ff_v1950_t-40:ll", pfd_duty=0.077),
]

NLVT = "msky130_fd_pr__nfet_01v8_lvt"
NSVT = "msky130_fd_pr__nfet_01v8"
PSVT = "msky130_fd_pr__pfet_01v8"
PLVT_M = "msky130_fd_pr__pfet_01v8_lvt"


def cid(key: str) -> str:
    return key.replace(":", "_")


def parse_corner(key: str) -> tuple[Condition, str]:
    tag, rc = key.split(":")
    return Condition.parse(tag), rc


def valid_raw(path: Path, t_end: float, vectors: list[str] | None = None) -> bool:
    if not path.exists() or path.stat().st_size < 128:
        return False
    try:
        w = spice.Waves(path)
        if len(w.t) < 4 or not np.all(np.isfinite(w.t)):
            return False
        if w.t[-1] < t_end * (1.0 - 1e-4):
            return False
        if vectors:
            for v in vectors:
                if v not in w or not np.all(np.isfinite(w[v])):
                    return False
        return True
    except Exception:
        return False


def find_valid_raw(base_dir: Path, name: str, raw_name: str, t_end: float,
                   vectors: list[str] | None = None) -> Path | None:
    dirs = sorted(
        [d for d in base_dir.glob(f"{name}.r*") if d.is_dir() and d.name.rsplit(".r", 1)[-1].isdigit()],
        key=lambda d: int(d.name.rsplit(".r", 1)[-1]),
        reverse=True,
    ) + [base_dir / name]
    for d in dirs:
        p = d / raw_name
        if valid_raw(p, t_end, vectors):
            return p
    return None


def find_valid_noise_raw(base_dir: Path, name: str, raw_name: str, f_min_hi: float = 1e8) -> Path | None:
    dirs = sorted(
        [d for d in base_dir.glob(f"{name}.r*") if d.is_dir() and d.name.rsplit(".r", 1)[-1].isdigit()],
        key=lambda d: int(d.name.rsplit(".r", 1)[-1]),
        reverse=True,
    ) + [base_dir / name]
    for d in dirs:
        p = d / raw_name
        if p.exists() and p.stat().st_size > 128:
            try:
                w = spice.Waves(p)
                if len(w.t) >= 5 and w.t[-1] >= f_min_hi and "onoise_spectrum" in w:
                    return p
            except Exception:
                continue
    return None


def run_batch(jobs: list[tuple[str, Path, dict]], workers: int, label: str):
    if not jobs:
        print(f"[{label}] 0 decks to run (all cached)", flush=True)
        return
    workers = min(int(workers), 2)
    assert 1 <= workers <= 2, f"Strictly workers <= 2 required, got {workers}"
    t0 = time.time()
    print(f"[{label}] launching {len(jobs)} decks (workers={workers})...", flush=True)
    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        status = "OK" if ex.ok else f"WARN({ex.log_failures[:2]})"
        print(f"  done {ex.run_dir.name} ({ex.elapsed_s:.1f}s) {status}", flush=True)
    print(f"[{label}] batch finished in {time.time() - t0:.1f}s", flush=True)


# ---------------------------------------------------------------------------
# Measurement Helpers
# ---------------------------------------------------------------------------

def measure_osc(w: spice.Waves, pos: str, neg: str, start: float, stop: float) -> dict:
    sel = (w.t >= start) & (w.t <= stop)
    t = w.t[sel]
    y = (w[pos] - w[neg])[sel]
    if len(t) < 10:
        return dict(ok=False, f_hz=0.0, swing_v=0.0, n_cycles=0)
    sw = float(np.ptp(y[len(y) // 2:]))
    if sw < 0.08:
        return dict(ok=False, f_hz=0.0, swing_v=sw, n_cycles=0)
    e, pol = crossings(t, y)
    r = e[pol > 0]
    if len(r) < 5:
        return dict(ok=False, f_hz=0.0, swing_v=sw, n_cycles=len(r))
    f = float((len(r) - 1) / (r[-1] - r[0]))
    h = len(r) // 2
    f1 = h / (r[h] - r[0])
    f2 = (len(r) - h - 1) / (r[-1] - r[h])
    drift = float(f2 / f1 - 1.0)
    # Duty cycle distortion
    r_idx = np.where(pol > 0)[0]
    dcs = []
    for k in range(len(r_idx) - 1):
        i0, i1 = r_idx[k], r_idx[k + 1]
        if i1 - i0 == 2 and pol[i0 + 1] < 0:
            per = e[i1] - e[i0]
            hi = e[i0 + 1] - e[i0]
            if per > 0:
                dcs.append(hi / per)
    dcd_pct = (float(np.mean(dcs)) - 0.5) * 100.0 if dcs else float("nan")
    return dict(ok=True, f_hz=f, period_s=1.0 / f, drift=drift, swing_v=sw,
                n_cycles=len(r) - 1, dcd_pct=dcd_pct)


def measure_quad_error(w: spice.Waves, i_pos: str, i_neg: str, q_pos: str, q_neg: str,
                       start: float, stop: float) -> dict:
    """Measure I/Q 90-deg quadrature phase error (ps & deg)."""
    sel = (w.t >= start) & (w.t <= stop)
    t = w.t[sel]
    yi = (w[i_pos] - w[i_neg])[sel]
    yq = (w[q_pos] - w[q_neg])[sel]
    ei, pi = crossings(t, yi)
    eq, pq = crossings(t, yq)
    ri = ei[pi > 0]
    rq = eq[pq > 0]
    if len(ri) < 4 or len(rq) < 4:
        return dict(err_ps=float("nan"), err_deg=float("nan"))
    per = float(np.median(np.diff(ri)))
    # For each I rising edge, find nearest Q rising edge modulo period
    errs = []
    for ti in ri[1:-1]:
        # distance to next Q rising edge
        idx = np.searchsorted(rq, ti)
        if idx < len(rq):
            dt = rq[idx] - ti
            # could be 0.25*T or 0.75*T depending on I/Q polarity; check closeness to 0.25*T vs 0.75*T
            frac = (dt / per) % 1.0
            e1 = frac - 0.25
            e2 = frac - 0.75
            e_best = e1 if abs(e1) < abs(e2) else e2
            errs.append(e_best)
    if not errs:
        return dict(err_ps=float("nan"), err_deg=float("nan"))
    mean_e = float(np.mean(errs))
    return dict(err_ps=mean_e * per * 1e12, err_deg=mean_e * 360.0)


def fit_tone_phasor(w: spice.Waves, pos: str, neg: str, fm: float, td: float, amp: float) -> dict:
    """Exact harmonic least-squares phasor fit (1 dropped period + remaining full periods)."""
    t0 = td + 1.0 / fm
    e, p = crossings(w.t, w[pos] - w[neg])
    r = e[p > 0]
    n = int((r[-1] - t0) * fm)
    if n < 1:
        raise ValueError(f"Insufficient tone periods: n={n}")
    r = r[(r >= t0) & (r <= t0 + n / fm)]
    k = np.arange(len(r), dtype=float)
    w0 = 2.0 * np.pi * fm * (r - td)
    a = np.column_stack((np.ones_like(k), k, k * k, np.sin(w0), np.cos(w0)))
    x, *_ = np.linalg.lstsq(a, r, rcond=None)
    res = r - a @ x
    f0 = float(1.0 / x[1])
    k_c = 2.0 * np.pi * fm * f0 * (x[4] - 1j * x[3]) / amp
    return dict(
        f0=f0, dev_ps=float(np.hypot(x[3], x[4]) * 1e12),
        residual_ps=float(res.std() * 1e12),
        periods=n, edges=len(r),
        k_real=float(k_c.real), k_quad=float(k_c.imag), k_mag=float(abs(k_c)),
    )


def extract_wave_slice(w: spice.Waves, signals: dict[str, tuple[str, str] | str],
                       start: float, n_cycles: float = 2.0, period: float = 400e-12) -> dict:
    """Extract clean 2-cycle waveform slice starting at a rising zero-crossing of the first signal."""
    sel = w.t >= start
    t = w.t[sel]
    first_key = next(iter(signals))
    spec0 = signals[first_key]
    y0 = (w[spec0[0]] - w[spec0[1]])[sel] if isinstance(spec0, tuple) else w[spec0][sel]
    e, p = crossings(t, y0)
    r = e[p > 0]
    t0 = float(r[len(r) // 2])
    t1 = t0 + n_cycles * period
    s = (w.t >= t0) & (w.t <= t1)
    tg = np.linspace(t0, t1, 241)
    out = dict(t_ns=((tg - t0) * 1e9).tolist())
    for k, sp in signals.items():
        arr = (w[sp[0]] - w[sp[1]])[s] if isinstance(sp, tuple) else w[sp][s]
        out[k] = np.interp(tg, w.t[s], arr).tolist()
    return out


# ---------------------------------------------------------------------------
# Circuit Header Builders (100% Real SKY130A PDK Devices)
# ---------------------------------------------------------------------------

def header_arch_a(cfg: dict, *, vctrl: float = 0.85, vdd_src: str | None = None,
                  vctrl_src: str | None = None, vdd_override: float | None = None,
                  reltol: str = "1e-4", inject: str = "", extra_save: str = "",
                  vreg_override: float | None = None) -> str:
    c, rc = parse_corner(cfg["key"])
    lib = spice.corner_values(c)["MODEL_LIBRARY"]
    vdd_v = c.supply if vdd_override is None else vdd_override
    lines = [
        f"* Arch A Supply-Regulated CMOS Ring ({cfg['key']})",
        f'.lib "{lib}" {c.process}',
        f'.include "{PRIMS}"',
        f'.include "{NET_A}"',
        vdd_src if vdd_src else f"Vdd vdd 0 {vdd_v:.6f}",
        vctrl_src if vctrl_src else f"Vctrl vctrl 0 {vctrl:.6f}",
        "Xdut v0p v0n v1p v1n v2p v2n v3p v3n b0p b0n b1p b1n b2p b2n b3p b3n vctrl vreg vdd 0 vco5g_ring_cmos_reg",
        *[f"Cb{i}{s} b{i}{s} 0 30f" for i in range(4) for s in "pn"],
        "Ikick v0p v0n PWL(0 0 1n 0 1.01n 100u 1.06n 100u 1.07n 0)",
    ]
    if vreg_override is not None:
        lines.append(f"Vreg_force vreg 0 {vreg_override:.6f}")
    if inject:
        lines.append(inject)
    lines += [
        f".temp {c.temp}",
        f".options reltol={reltol} abstol=1p vntol=1u klu",
        f".save v(v0p) v(v0n) v(v2p) v(v2n) v(b0p) v(b0n) v(b2p) v(b2n) v(vreg) i(Vdd) i(v.xdut.vreg_sense) i(v.xdut.vbuf_sense) {extra_save}",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def header_arch_b(cfg: dict, *, vbp: float = 1.00, vdd_src: str | None = None,
                  vbp_src: str | None = None, vdd_override: float | None = None,
                  vbx_v: float = 0.0, reltol: str = "1e-4", inject: str = "",
                  extra_save: str = "") -> str:
    c, rc = parse_corner(cfg["key"])
    lib = spice.corner_values(c)["MODEL_LIBRARY"]
    vdd_v = c.supply if vdd_override is None else vdd_override
    lines = [
        f"* Arch B Maneatis Symmetric-Load Ring ({cfg['key']})",
        f'.lib "{lib}" {c.process}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{NET_B}"',
        vdd_src if vdd_src else f"Vdd vdd 0 {vdd_v:.6f}",
        vbp_src if vbp_src else f"Vbp vbp 0 {vbp:.6f}",
    ]
    if abs(vbx_v) > 0:
        # Perturb Vbn directly on the delay cells via a tiny series source by instantiating bias + cells separately
        lines += [
            "Vcore_sense vdd vdd_core 0",
            "Vbias_sense vdd vdd_bias 0",
            "Vbuf_sense  vdd vdd_buf  0",
            "Xbias vbp vbn_raw vdd_bias 0 vco5g_maneatis_bias",
            f"Vbx vbn vbn_raw {vbx_v:.6e}",
            "X0 v3n v3p v0p v0n vbp vbn vdd_core 0 vco5g_maneatis_cell",
            "X1 v0p v0n v1p v1n vbp vbn vdd_core 0 vco5g_maneatis_cell",
            "X2 v1p v1n v2p v2n vbp vbn vdd_core 0 vco5g_maneatis_cell",
            "X3 v2p v2n v3p v3n vbp vbn vdd_core 0 vco5g_maneatis_cell",
            "Xb0 v0p v0n b0p b0n vbn vdd_buf 0 vco5g_man_buf",
            "Xb1 v1p v1n b1p b1n vbn vdd_buf 0 vco5g_man_buf",
            "Xb2 v2p v2n b2p b2n vbn vdd_buf 0 vco5g_man_buf",
            "Xb3 v3p v3n b3p b3n vbn vdd_buf 0 vco5g_man_buf",
            *[f"Cb{i}{s} b{i}{s} 0 30f" for i in range(4) for s in "pn"],
            "Ikick v0p v0n PWL(0 0 1n 0 1.01n 100u 1.06n 100u 1.07n 0)",
        ]
        save_i = "i(Vdd) i(Vcore_sense) i(Vbias_sense) i(Vbuf_sense)"
    else:
        lines += [
            "Xdut v0p v0n v1p v1n v2p v2n v3p v3n b0p b0n b1p b1n b2p b2n b3p b3n vbp vbn vdd 0 vco5g_ring_maneatis",
            *[f"Cb{i}{s} b{i}{s} 0 30f" for i in range(4) for s in "pn"],
            "Ikick v0p v0n PWL(0 0 1n 0 1.01n 100u 1.06n 100u 1.07n 0)",
        ]
        save_i = "i(Vdd) i(v.xdut.vcore_sense) i(v.xdut.vbias_sense) i(v.xdut.vbuf_sense) v(xdut.xbias.vrep)"
    if inject:
        lines.append(inject)
    lines += [
        f".temp {c.temp}",
        f".options reltol={reltol} abstol=1p vntol=1u klu",
        f".save v(v0p) v(v0n) v(v2p) v(v2n) v(b0p) v(b0n) v(b2p) v(b2n) v(vbn) {save_i} {extra_save}",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


def header_arch_c(cfg: dict, *, code: int = 7, vctrl: float = 0.90,
                  vdd_src: str | None = None, vctrl_src: str | None = None,
                  vdd_override: float | None = None, cfg_track_sin: bool = False,
                  reltol: str = "1e-4", inject: str = "", extra_save: str = "",
                  add_ind_ac: bool = False) -> str:
    c, rc = parse_corner(cfg["key"])
    lib = spice.corner_values(c)["MODEL_LIBRARY"]
    vdd_v = c.supply if vdd_override is None else vdd_override
    if cfg_track_sin and vdd_src and "SIN(" in vdd_src:
        m_sin = re.search(r"SIN\(([^)]+)\)", vdd_src)
        sin_args = m_sin.group(1)
        b_lines = [
            f"Vb{b} b{b} 0 DC {vdd_v:.6f} SIN({sin_args})" if (code >> b) & 1 else f"Vb{b} b{b} 0 0"
            for b in range(4)
        ]
    else:
        b_lines = [f"Vb{b} b{b} 0 {vdd_v if (code >> b) & 1 else 0:.6f}" for b in range(4)]
    lines = [
        f"* Arch C 5.0 GHz LC-VCO + Quadrature /2 ({cfg['key']})",
        f'.lib "{lib}" {c.process}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{NET_C}"',
        vdd_src if vdd_src else f"Vdd vdd 0 {vdd_v:.6f}",
        vctrl_src if vctrl_src else f"Vctrl vctrl 0 {vctrl:.6f}",
        *b_lines,
        f"Xdut vp vn ip in qp qn vctrl b0 b1 b2 b3 vdd 0 vco5g_lc_div2 rm_scale={cfg['rm_scale']} c_scale={cfg['c_scale']}",
        "Cip ip 0 30f", "Cin in 0 30f", "Cqp qp 0 30f", "Cqn qn 0 30f",
        "Ikick vp vn PWL(0 0 0.2n 0 0.21n 50u 0.26n 50u 0.27n 0)",
        "Ikick_d ip in PWL(0 0 6n 0 6.01n 50u 6.06n 50u 6.07n 0)",
    ]
    extra_ind_save = ""
    if add_ind_ac:
        lines += [
            f"Xind_q tp tn tct 0 vco5g_ind_oct_2n2 rm_scale={cfg['rm_scale']} c_scale={cfg['c_scale']}",
            "It_diff tn tp ac 1",
            "Rdc_q tct 0 1G",
        ]
        extra_ind_save = "v(tp) v(tn)"
    if inject:
        lines.append(inject)
    cshunt_opt = " cshunt=1e-18" if c.process == "ff" and reltol == "2e-4" else ""
    lines += [
        ".ic v(xdut.xcore.vbias_f)=0.82 v(xdut.xcore.vbias_lc)=0.82 v(xdut.xcore.tail_d)=0.32 v(xdut.xcore.tail)=0.32 v(xdut.xdiv2.vbias_d)=0.78 v(xdut.xdiv2.vck_cm)=1.05 v(vp)=1.05 v(vn)=1.00",
        ".nodeset v(vp)=1.0 v(vn)=1.0 v(xdut.xcore.tail)=0.35 v(xdut.xcore.tail_d)=0.35",
        f".temp {c.temp}",
        f".options reltol={reltol} abstol=10p vntol=10u gmin=1e-11{cshunt_opt} klu method=gear",
        f".save v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd) i(v.xdut.vcore_sense) i(v.xdut.vdiv_sense) {extra_ind_save} {extra_save}",
    ]
    return bias.section("\n".join(lines) + "\n", c.process, rc)


# ---------------------------------------------------------------------------
# Stage 1: Full Tuning Range Sweep & Inductor AC Q across 5 PVT x RC Corners
# ---------------------------------------------------------------------------

def stage_range(workers: int) -> dict:
    sdir = OUT / "stage1_range"
    sdir.mkdir(parents=True, exist_ok=True)
    stop_r = 14e-9
    jobs = []
    plan = {}

    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])
        # Arch A: 7 V_ctrl points from 0.62 V up to (VDD - 0.13)/1.5
        va_hi = round((c.supply - 0.13) / 1.5, 4)
        vs_a = [round(float(x), 4) for x in np.linspace(0.62, va_hi, 7)]
        plan[("A", cfg["key"])] = vs_a
        if find_valid_raw(sdir, f"a_{tag}", f"p{len(vs_a)-1}.raw", stop_r, ["v(v0p)", "v(v0n)"]) is None:
            head = header_arch_a(cfg, vctrl=vs_a[3])
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            for k, v in enumerate(vs_a):
                ctrl += [
                    f"alter Vctrl dc={v:.5f}",
                    f"tran 4p {stop_r:.4e} 6n 4p",
                    f"write p{k}.raw v(v0p) v(v0n) v(vreg) i(Vdd) i(v.xdut.vreg_sense)",
                    "destroy all",
                ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"a_{tag}"),
                         dict(timeout_s=600, meta=dict(stage="range", arch="A", corner=cfg["key"]))))

        # Arch B: 7 V_bp points sweeping VDD-Vbp from 0.50 V to 1.02 V
        dvs_b = np.linspace(0.50, 1.02, 7)
        vs_b = [round(float(c.supply - dv), 4) for dv in dvs_b]
        plan[("B", cfg["key"])] = vs_b
        if find_valid_raw(sdir, f"b_{tag}", f"p{len(vs_b)-1}.raw", stop_r, ["v(v0p)", "v(v0n)"]) is None:
            head = header_arch_b(cfg, vbp=vs_b[3])
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            for k, v in enumerate(vs_b):
                ctrl += [
                    f"alter Vbp dc={v:.5f}",
                    f"tran 4p {stop_r:.4e} 6n 4p",
                    f"write p{k}.raw v(v0p) v(v0n) v(vbn) v(xdut.xbias.vrep) i(Vdd) i(v.xdut.vcore_sense)",
                    "destroy all",
                ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"b_{tag}"),
                         dict(timeout_s=600, meta=dict(stage="range", arch="B", corner=cfg["key"]))))

        # Arch C: Inductor AC Q + 9 (code, Vctrl) points covering full 4-bit bank + single-code varactor span
        v_hi = round(c.supply - 0.15, 4)
        pts_c = [
            (0, v_hi), (0, 0.90), (4, 0.90), (7, 0.25), (7, 0.90), (7, v_hi),
            (10, 0.90), (15, 0.90), (15, 0.20),
        ]
        plan[("C", cfg["key"])] = pts_c
        missing_c = [k for k in range(len(pts_c))
                     if find_valid_raw(sdir, f"c_{tag}", f"p{k}.raw", stop_r, ["v(vp)", "v(vn)"]) is None]
        # Check if any existing c_{tag}* dir has a valid non-empty ind_q.txt
        has_ind_q = False
        for d in sorted(sdir.glob(f"c_{tag}*"), reverse=True):
            iq = d / "ind_q.txt"
            if iq.exists() and "q_ind" in iq.read_text():
                has_ind_q = True
                break
        if missing_c or not has_ind_q:
            head = header_arch_c(cfg, code=7, vctrl=0.90, add_ind_ac=True)
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            if not has_ind_q:
                ctrl += [
                    "ac lin 1 5g 5g",
                    "let zdiff = v(tp) - v(tn)",
                    "let re_z = real(zdiff)",
                    "let im_z = imag(zdiff)",
                    "let q_ind = im_z / re_z",
                    "let l_eff = im_z / (2 * 3.141592653589793 * 5e9)",
                    "let rp_ind = (re_z^2 + im_z^2) / re_z",
                    "print re_z im_z q_ind l_eff rp_ind > ind_q.txt",
                    "destroy all",
                ]
            for k in missing_c:
                code, vc = pts_c[k]
                ctrl += [
                    f"alter Vctrl dc={vc:.5f}",
                    *[f"alter Vb{b} dc={c.supply if (code >> b) & 1 else 0:.5f}" for b in range(4)],
                    f"tran 2p {stop_r:.4e} 6n 2p uic",
                    f"write p{k}.raw v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd) i(v.xdut.vcore_sense) i(v.xdut.vdiv_sense)",
                    "destroy all",
                ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"c_{tag}"),
                         dict(timeout_s=900, meta=dict(stage="range", arch="C", corner=cfg["key"]))))

    run_batch(jobs, workers, "stage1-range")

    out = {"A": {}, "B": {}, "C": {}}
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])

        # Parse Arch A
        vs_a = plan[("A", cfg["key"])]
        pts_a = []
        for k, v in enumerate(vs_a):
            w = spice.Waves(find_valid_raw(sdir, f"a_{tag}", f"p{k}.raw", stop_r))
            m = measure_osc(w, "v(v0p)", "v(v0n)", 8e-9, stop_r)
            vreg = float(np.mean(w["v(vreg)"][w.t >= 8e-9]))
            pts_a.append(dict(vctrl=v, vreg=vreg, f_hz=m["f_hz"], ok=m["ok"], swing_mv=m["swing_v"] * 1e3))
        ok_a = [p for p in pts_a if p["ok"] and p["f_hz"] > 0.2e9]
        f_min_a = min(p["f_hz"] for p in ok_a)
        f_max_a = max(p["f_hz"] for p in ok_a)
        ftr_a = 200.0 * (f_max_a - f_min_a) / (f_max_a + f_min_a)
        # Interpolate Vctrl for 2.50 GHz
        va_arr = np.array([p["vctrl"] for p in ok_a])
        fa_arr = np.array([p["f_hz"] for p in ok_a])
        v_guess_a = float(np.interp(TARGET_OUT, fa_arr, va_arr))
        out["A"][cfg["key"]] = dict(
            f_min_hz=f_min_a, f_max_hz=f_max_a, ftr_pct=ftr_a,
            covers_2p5g=(f_min_a <= TARGET_OUT <= f_max_a),
            v_guess=round(v_guess_a, 4), points=pts_a,
        )

        # Parse Arch B
        vs_b = plan[("B", cfg["key"])]
        pts_b = []
        for k, v in enumerate(vs_b):
            w = spice.Waves(find_valid_raw(sdir, f"b_{tag}", f"p{k}.raw", stop_r))
            m = measure_osc(w, "v(v0p)", "v(v0n)", 8e-9, stop_r)
            vrep = float(np.mean(w["v(xdut.xbias.vrep)"][w.t >= 8e-9]))
            pts_b.append(dict(vbp=v, dv=c.supply - v, vrep=vrep, f_hz=m["f_hz"], ok=m["ok"], swing_mv=m["swing_v"] * 1e3))
        ok_b = [p for p in pts_b if p["ok"] and p["f_hz"] > 0.2e9]
        f_min_b = min(p["f_hz"] for p in ok_b)
        f_max_b = max(p["f_hz"] for p in ok_b)
        ftr_b = 200.0 * (f_max_b - f_min_b) / (f_max_b + f_min_b)
        # f increases as vbp decreases -> sort by f
        ok_b_s = sorted(ok_b, key=lambda p: p["f_hz"])
        v_guess_b = float(np.interp(TARGET_OUT, [p["f_hz"] for p in ok_b_s], [p["vbp"] for p in ok_b_s]))
        out["B"][cfg["key"]] = dict(
            f_min_hz=f_min_b, f_max_hz=f_max_b, ftr_pct=ftr_b,
            covers_2p5g=(f_min_b <= TARGET_OUT <= f_max_b),
            v_guess=round(v_guess_b, 4), points=pts_b,
        )

        # Parse Arch C
        pts_c = plan[("C", cfg["key"])]
        ind_vals = {}
        for d in sorted(sdir.glob(f"c_{tag}*"), reverse=True):
            iq = d / "ind_q.txt"
            if iq.exists() and "q_ind" in iq.read_text():
                for line in iq.read_text().splitlines():
                    mm = re.match(r"\s*(\w+)\s*=\s*([-+0-9.eE]+)", line)
                    if mm:
                        ind_vals[mm.group(1).lower()] = float(mm.group(2))
                break
        rows_c = []
        for k, (code, vc) in enumerate(pts_c):
            w = spice.Waves(find_valid_raw(sdir, f"c_{tag}", f"p{k}.raw", stop_r))
            mt = measure_osc(w, "v(vp)", "v(vn)", 8e-9, stop_r)
            mi = measure_osc(w, "v(ip)", "v(in)", 8e-9, stop_r)
            rows_c.append(dict(code=code, vctrl=vc, f_lc_hz=mt["f_hz"], f_out_hz=mi["f_hz"],
                               ok_lc=mt["ok"], ok_div=mi["ok"] and abs(mi["f_hz"] / max(mt["f_hz"], 1.0) - 0.5) < 0.02,
                               tank_sw_mv=mt["swing_v"] * 1e3, iq_sw_mv=mi["swing_v"] * 1e3))
        ok_c = [r for r in rows_c if r["ok_lc"] and r["ok_div"]]
        f_min_c = min(r["f_out_hz"] for r in ok_c)
        f_max_c = max(r["f_out_hz"] for r in ok_c)
        ftr_c = 200.0 * (f_max_c - f_min_c) / (f_max_c + f_min_c)
        # Single-code continuous varactor span at code=7
        c7 = [r for r in rows_c if r["code"] == 7 and r["ok_div"]]
        f7_min = min(r["f_out_hz"] for r in c7)
        f7_max = max(r["f_out_hz"] for r in c7)
        cont_span_c_pct = 200.0 * (f7_max - f7_min) / (f7_max + f7_min)
        # Fit code vs f_out at Vctrl=0.90 to pick exact code placing 2.50 GHz near Vctrl ~ 0.90 V
        mid_rows = [r for r in rows_c if abs(r["vctrl"] - 0.90) < 1e-3 and r["ok_div"]]
        mid_codes = np.array([r["code"] for r in mid_rows], float)
        mid_fs = np.array([r["f_out_hz"] for r in mid_rows], float)
        # Sort by f ascending
        ord_m = np.argsort(mid_fs)
        code_est = float(np.interp(TARGET_OUT, mid_fs[ord_m], mid_codes[ord_m]))
        code_lock = int(np.clip(round(code_est), 0, 15))
        # Estimate Vctrl at code_lock using varactor slope from code=7
        c7_s = sorted(c7, key=lambda r: r["vctrl"])
        kv_est = (c7_s[-1]["f_out_hz"] - c7_s[0]["f_out_hz"]) / (c7_s[-1]["vctrl"] - c7_s[0]["vctrl"])
        f_at_code_0p9 = float(np.interp(code_lock, mid_codes, mid_fs))
        v_guess_c = float(np.clip(0.90 + (TARGET_OUT - f_at_code_0p9) / kv_est, 0.35, c.supply - 0.30))
        out["C"][cfg["key"]] = dict(
            f_min_hz=f_min_c, f_max_hz=f_max_c, ftr_pct=ftr_c,
            cont_varactor_pct=cont_span_c_pct,
            covers_2p5g=(f_min_c <= TARGET_OUT <= f_max_c),
            code_lock=code_lock, v_guess=round(v_guess_c, 4),
            ind_ac=ind_vals, points=rows_c,
        )
        print(f"  [range] {cfg['key']:18s} | "
              f"A: {f_min_a/1e9:.2f}-{f_max_a/1e9:.2f} GHz ({ftr_a:.0f}%, V={v_guess_a:.3f}V) | "
              f"B: {f_min_b/1e9:.2f}-{f_max_b/1e9:.2f} GHz ({ftr_b:.0f}%, Vbp={v_guess_b:.3f}V) | "
              f"C: {f_min_c/1e9:.2f}-{f_max_c/1e9:.2f} GHz ({ftr_c:.0f}%, cont={cont_span_c_pct:.1f}%, Q={ind_vals.get('q_ind',0):.2f}, c={code_lock}, V={v_guess_c:.3f}V)",
              flush=True)

    (sdir / "summary.json").write_text(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------------------
# Stage 2: Exact 2.500 GHz Lock Calibration, Kvco, Kb/Kvreg, DC Kvdd, Waveforms
# ---------------------------------------------------------------------------

def stage_lock(workers: int, rng_data: dict) -> dict:
    sdir = OUT / "stage2_lock"
    sdir.mkdir(parents=True, exist_ok=True)
    stop1, start1 = 16e-9, 8e-9

    # Pass 1: 3-point bracket around v_guess to nail exact 2.500 GHz (+/- 0.2%)
    jobs_p1 = []
    p1_grid = {}
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])

        # Arch A bracket (+/- 30 mV)
        vg_a = rng_data["A"][cfg["key"]]["v_guess"]
        vs_a = [round(float(np.clip(vg_a + dv, 0.62, (c.supply - 0.13) / 1.5)), 4) for dv in (-0.030, 0.0, 0.030)]
        p1_grid[("A", cfg["key"])] = vs_a
        if find_valid_raw(sdir / "p1", f"a_{tag}", "p2.raw", stop1) is None:
            head = header_arch_a(cfg, vctrl=vs_a[1])
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            for k, v in enumerate(vs_a):
                ctrl += [f"alter Vctrl dc={v:.5f}", f"tran 3p {stop1:.4e} {start1:.4e} 3p",
                         f"write p{k}.raw v(v0p) v(v0n) v(vreg)", "destroy all"]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs_p1.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p1", f"a_{tag}"), dict(timeout_s=450)))

        # Arch B bracket (+/- 35 mV)
        vg_b = rng_data["B"][cfg["key"]]["v_guess"]
        vs_b = [round(float(np.clip(vg_b + dv, c.supply - 1.05, c.supply - 0.48)), 4) for dv in (-0.035, 0.0, 0.035)]
        p1_grid[("B", cfg["key"])] = vs_b
        if find_valid_raw(sdir / "p1", f"b_{tag}", "p2.raw", stop1) is None:
            head = header_arch_b(cfg, vbp=vs_b[1])
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            for k, v in enumerate(vs_b):
                ctrl += [f"alter Vbp dc={v:.5f}", f"tran 3p {stop1:.4e} {start1:.4e} 3p",
                         f"write p{k}.raw v(v0p) v(v0n) v(vbn)", "destroy all"]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs_p1.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p1", f"b_{tag}"), dict(timeout_s=450)))

        # Arch C bracket (+/- 120 mV around v_guess at code_lock)
        rc_d = rng_data["C"][cfg["key"]]
        code_c, vg_c = rc_d["code_lock"], rc_d["v_guess"]
        vs_c = [round(float(np.clip(vg_c + dv, 0.25, c.supply - 0.20)), 4) for dv in (-0.12, 0.0, 0.12)]
        p1_grid[("C", cfg["key"])] = (code_c, vs_c)
        if find_valid_raw(sdir / "p1", f"c_{tag}", "p2.raw", stop1) is None:
            head = header_arch_c(cfg, code=code_c, vctrl=vs_c[1])
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            for k, v in enumerate(vs_c):
                ctrl += [f"alter Vctrl dc={v:.5f}", f"tran 2p {stop1:.4e} {start1:.4e} 2p uic",
                         f"write p{k}.raw v(vp) v(vn) v(ip) v(in)", "destroy all"]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs_p1.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p1", f"c_{tag}"), dict(timeout_s=600)))

    run_batch(jobs_p1, workers, "lock-p1")

    def solve_vlock(vs, fs, target, lo, hi):
        poly = np.polyfit(vs, fs, 2)
        roots = np.roots([poly[0], poly[1], poly[2] - target])
        real_r = [float(r.real) for r in roots if abs(r.imag) < 1e-9 and lo <= r.real <= hi]
        if real_r:
            return round(min(real_r, key=lambda x: abs(x - vs[1])), 5)
        slope = (fs[2] - fs[0]) / (vs[2] - vs[0])
        return round(float(np.clip(vs[1] + (target - fs[1]) / slope, lo, hi)), 5)

    locks = {"A": {}, "B": {}, "C": {}}
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])
        # A
        vs_a = p1_grid[("A", cfg["key"])]
        fs_a = [measure_osc(spice.Waves(find_valid_raw(sdir / "p1", f"a_{tag}", f"p{k}.raw", stop1)), "v(v0p)", "v(v0n)", 10e-9, stop1)["f_hz"] for k in range(3)]
        locks["A"][cfg["key"]] = dict(vctrl=solve_vlock(vs_a, fs_a, TARGET_OUT, 0.60, (c.supply - 0.11) / 1.5))
        # B
        vs_b = p1_grid[("B", cfg["key"])]
        fs_b = [measure_osc(spice.Waves(find_valid_raw(sdir / "p1", f"b_{tag}", f"p{k}.raw", stop1)), "v(v0p)", "v(v0n)", 10e-9, stop1)["f_hz"] for k in range(3)]
        locks["B"][cfg["key"]] = dict(vbp=solve_vlock(vs_b, fs_b, TARGET_OUT, c.supply - 1.08, c.supply - 0.45))
        # C (use f_lc/2 in p1 bracket so slow-buildup FS still solves cleanly; p2 verifies full /2 lock!)
        code_c, vs_c = p1_grid[("C", cfg["key"])]
        fs_c = [measure_osc(spice.Waves(find_valid_raw(sdir / "p1", f"c_{tag}", f"p{k}.raw", stop1)), "v(vp)", "v(vn)", 10e-9, stop1)["f_hz"] / 2.0 for k in range(3)]
        v_lc = solve_vlock(vs_c, fs_c, TARGET_OUT, 0.25, c.supply - 0.20)
        # If Vctrl landed too close to rails, shift 1 code so Vctrl is nicely centered
        if v_lc < 0.45 and code_c > 0:
            code_c -= 1
            v_lc = min(c.supply - 0.35, v_lc + 0.35)
        elif v_lc > c.supply - 0.35 and code_c < 15:
            code_c += 1
            v_lc = max(0.45, v_lc - 0.35)
        locks["C"][cfg["key"]] = dict(code=code_c, vctrl=round(v_lc, 5))
        print(f"  [lock-p1] {cfg['key']:18s} | A: Vctrl={locks['A'][cfg['key']]['vctrl']:.4f}V | "
              f"B: Vbp={locks['B'][cfg['key']]['vbp']:.4f}V | C: code={code_c} Vctrl={locks['C'][cfg['key']]['vctrl']:.4f}V", flush=True)

    # Pass 2: High-precision lock + Kvco (+/-15 mV) + DC Kvdd (+/-5 mV) + Bias sensitivity (Arch B Vbn +/-1 mV)
    stop2, start2 = 20e-9, 10e-9
    jobs_p2 = []
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])

        # Arch A Pass 2
        vc_a = locks["A"][cfg["key"]]["vctrl"]
        if find_valid_raw(sdir / "p2", f"a_{tag}", "vdd_p.raw", stop2) is None:
            head = header_arch_a(cfg, vctrl=vc_a)
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            cases_a = [
                ("nom", vc_a, c.supply),
                ("vm", vc_a - 0.015, c.supply),
                ("vp", vc_a + 0.015, c.supply),
                ("vdd_m", vc_a, c.supply - 0.005),
                ("vdd_p", vc_a, c.supply + 0.005),
            ]
            for nm, vc, vd in cases_a:
                ctrl += [
                    f"alter Vdd dc={vd:.6f}",
                    f"alter Vctrl dc={vc:.6f}",
                    f"tran 2p {stop2:.4e} {start2:.4e} 2p",
                    f"write {nm}.raw v(v0p) v(v0n) v(v2p) v(v2n) v(b0p) v(b0n) v(b2p) v(b2n) v(vreg) i(Vdd) i(v.xdut.vreg_sense) i(v.xdut.vbuf_sense)",
                    "destroy all",
                ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs_p2.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p2", f"a_{tag}"), dict(timeout_s=900)))

        # Arch B Pass 2 (nominal + Kvco + DC Kvdd + Vbn sensitivity Kb)
        vb_b = locks["B"][cfg["key"]]["vbp"]
        if find_valid_raw(sdir / "p2", f"b_{tag}", "vdd_p.raw", stop2) is None:
            head = header_arch_b(cfg, vbp=vb_b)
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            cases_b = [
                ("nom", vb_b, c.supply),
                ("vm", vb_b - 0.015, c.supply),
                ("vp", vb_b + 0.015, c.supply),
                ("vdd_m", vb_b, c.supply - 0.005),
                ("vdd_p", vb_b, c.supply + 0.005),
            ]
            for nm, vb, vd in cases_b:
                ctrl += [
                    f"alter Vdd dc={vd:.6f}",
                    f"alter Vbp dc={vb:.6f}",
                    f"tran 2p {stop2:.4e} {start2:.4e} 2p",
                    f"write {nm}.raw v(v0p) v(v0n) v(v2p) v(v2n) v(b0p) v(b0n) v(b2p) v(b2n) v(vbn) v(xdut.xbias.vrep) i(Vdd) i(v.xdut.vcore_sense) i(v.xdut.vbias_sense) i(v.xdut.vbuf_sense)",
                    "destroy all",
                ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs_p2.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p2", f"b_{tag}"), dict(timeout_s=900)))

        # Arch B Vbn sensitivity deck (small separate deck with Vbx series source on vbn)
        if find_valid_raw(sdir / "p2", f"b_kb_{tag}", "kb_p.raw", stop2) is None:
            head = header_arch_b(cfg, vbp=vb_b, vbx_v=1e-3)
            ctrl = [
                ".control", "set num_threads=1", "set filetype=binary",
                "alter Vbx dc=-1e-3",
                f"tran 2p {stop2:.4e} {start2:.4e} 2p",
                "write kb_m.raw v(v0p) v(v0n)",
                "destroy all",
                "alter Vbx dc=1e-3",
                f"tran 2p {stop2:.4e} {start2:.4e} 2p",
                "write kb_p.raw v(v0p) v(v0n)",
                "destroy all",
                "quit", ".endc", ".end", "",
            ]
            jobs_p2.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p2", f"b_kb_{tag}"), dict(timeout_s=450)))

        # Arch C Pass 2
        code_c, vc_c = locks["C"][cfg["key"]]["code"], locks["C"][cfg["key"]]["vctrl"]
        cases_c = [
            ("nom", vc_c, c.supply),
            ("vm", vc_c - 0.040, c.supply),
            ("vp", vc_c + 0.040, c.supply),
            ("vdd_m", vc_c, c.supply - 0.005),
            ("vdd_p", vc_c, c.supply + 0.005),
        ]
        missing_c2 = [(nm, vc, vd) for nm, vc, vd in cases_c
                      if find_valid_raw(sdir / "p2", f"c_{tag}", f"{nm}.raw", stop2) is None]
        if missing_c2:
            head = header_arch_c(cfg, code=code_c, vctrl=vc_c)
            ctrl = [".control", "set num_threads=1", "set filetype=binary"]
            for nm, vc, vd in missing_c2:
                ctrl += [
                    f"alter Vdd dc={vd:.6f}",
                    *[f"alter Vb{b} dc={vd:.6f}" for b in range(4) if (code_c >> b) & 1],
                    f"alter Vctrl dc={vc:.6f}",
                    f"tran 2p {stop2:.4e} {start2:.4e} 2p uic",
                    f"write {nm}.raw v(vp) v(vn) v(ip) v(in) v(qp) v(qn) i(Vdd) i(v.xdut.vcore_sense) i(v.xdut.vdiv_sense)",
                    "destroy all",
                ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs_p2.append((head + "\n".join(ctrl), spice.next_run_dir(sdir / "p2", f"c_{tag}"), dict(timeout_s=1200)))

    run_batch(jobs_p2, workers, "lock-p2")

    # Analyze Pass 2 for all 3 architectures
    out = {"A": {}, "B": {}, "C": {}}
    win_s = 13e-9
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])

        # --- Arch A ---
        w_a = spice.Waves(find_valid_raw(sdir / "p2", f"a_{tag}", "nom.raw", stop2))
        w_am = spice.Waves(find_valid_raw(sdir / "p2", f"a_{tag}", "vm.raw", stop2))
        w_ap = spice.Waves(find_valid_raw(sdir / "p2", f"a_{tag}", "vp.raw", stop2))
        w_avm = spice.Waves(find_valid_raw(sdir / "p2", f"a_{tag}", "vdd_m.raw", stop2))
        w_avp = spice.Waves(find_valid_raw(sdir / "p2", f"a_{tag}", "vdd_p.raw", stop2))
        m_a = measure_osc(w_a, "v(v0p)", "v(v0n)", win_s, stop2)
        m_ab = measure_osc(w_a, "v(b0p)", "v(b0n)", win_s, stop2)
        qa = measure_quad_error(w_a, "v(b0p)", "v(b0n)", "v(b2p)", "v(b2n)", win_s, stop2)
        sel = w_a.t >= win_s
        vreg_a = float(np.mean(w_a["v(vreg)"][sel]))
        icore_a = float(np.mean(w_a["i(v.xdut.vreg_sense)"][sel]))
        ibuf_a = float(np.mean(w_a["i(v.xdut.vbuf_sense)"][sel]))
        itot_a = float(-np.mean(w_a["i(vdd)"][sel]))
        # Small-signal ring load resistance seen by regulator: dVreg / dIcore
        vreg_m = float(np.mean(w_am["v(vreg)"][w_am.t >= win_s]))
        vreg_p = float(np.mean(w_ap["v(vreg)"][w_ap.t >= win_s]))
        ic_m = float(np.mean(w_am["i(v.xdut.vreg_sense)"][w_am.t >= win_s]))
        ic_p = float(np.mean(w_ap["i(v.xdut.vreg_sense)"][w_ap.t >= win_s]))
        r_ring_ac = (vreg_p - vreg_m) / max(ic_p - ic_m, 1e-6)
        r_ring_dc = vreg_a / max(icore_a, 1e-6)
        f_am = measure_osc(w_am, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"]
        f_ap = measure_osc(w_ap, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"]
        kvco_a = (f_ap - f_am) / 0.030
        kvreg_a = (f_ap - f_am) / (vreg_p - vreg_m)
        kvdd_dc_a = (measure_osc(w_avp, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"] -
                     measure_osc(w_avm, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"]) / 0.010
        out["A"][cfg["key"]] = dict(
            vctrl=locks["A"][cfg["key"]]["vctrl"], vreg=vreg_a,
            f_hz=m_a["f_hz"], period_s=m_a["period_s"],
            core_swing_mv=m_a["swing_v"] * 1e3, buf_swing_mv=m_ab["swing_v"] * 1e3,
            dcd_pct=m_ab["dcd_pct"], quad_err=qa,
            kvco_hz_v=kvco_a, kvreg_hz_v=kvreg_a, kvdd_dc_hz_v=kvdd_dc_a,
            r_ring_dc_ohm=r_ring_dc, r_ring_ac_ohm=r_ring_ac,
            # Power breakdown: ring core power (at Vreg), pass-FET + OTA power (VDD*I_reg_tot - Vreg*I_core), buffers
            p_core_mw=icore_a * vreg_a * 1e3,
            p_core_plus_reg_mw=(itot_a - ibuf_a) * c.supply * 1e3,
            p_reg_overhead_mw=((itot_a - ibuf_a) * c.supply - icore_a * vreg_a) * 1e3,
            p_buf_mw=ibuf_a * c.supply * 1e3,
            p_total_mw=itot_a * c.supply * 1e3,
            icore_ma=icore_a * 1e3,
            wave=extract_wave_slice(w_a, dict(core_diff=("v(v0p)", "v(v0n)"),
                                              buf_i=("v(b0p)", "v(b0n)"),
                                              buf_q=("v(b2p)", "v(b2n)"),
                                              v0p="v(v0p)", vreg="v(vreg)"),
                                    win_s, 2.0, m_a["period_s"]),
        )

        # --- Arch B ---
        w_b = spice.Waves(find_valid_raw(sdir / "p2", f"b_{tag}", "nom.raw", stop2))
        w_bm = spice.Waves(find_valid_raw(sdir / "p2", f"b_{tag}", "vm.raw", stop2))
        w_bp = spice.Waves(find_valid_raw(sdir / "p2", f"b_{tag}", "vp.raw", stop2))
        w_bvm = spice.Waves(find_valid_raw(sdir / "p2", f"b_{tag}", "vdd_m.raw", stop2))
        w_bvp = spice.Waves(find_valid_raw(sdir / "p2", f"b_{tag}", "vdd_p.raw", stop2))
        w_kbm = spice.Waves(find_valid_raw(sdir / "p2", f"b_kb_{tag}", "kb_m.raw", stop2))
        w_kbp = spice.Waves(find_valid_raw(sdir / "p2", f"b_kb_{tag}", "kb_p.raw", stop2))
        m_b = measure_osc(w_b, "v(v0p)", "v(v0n)", win_s, stop2)
        m_bb = measure_osc(w_b, "v(b0p)", "v(b0n)", win_s, stop2)
        qb = measure_quad_error(w_b, "v(b0p)", "v(b0n)", "v(b2p)", "v(b2n)", win_s, stop2)
        sel = w_b.t >= win_s
        vbn_b = float(np.mean(w_b["v(vbn)"][sel]))
        vrep_b = float(np.mean(w_b["v(xdut.xbias.vrep)"][sel]))
        v0min_b = float(np.min(w_b["v(v0p)"][sel]))
        icore_b = float(np.mean(w_b["i(v.xdut.vcore_sense)"][sel]))
        ibias_b = float(np.mean(w_b["i(v.xdut.vbias_sense)"][sel]))
        ibuf_b = float(np.mean(w_b["i(v.xdut.vbuf_sense)"][sel]))
        itot_b = float(-np.mean(w_b["i(vdd)"][sel]))
        kvco_b = (measure_osc(w_bp, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"] -
                  measure_osc(w_bm, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"]) / 0.030
        kvdd_dc_b = (measure_osc(w_bvp, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"] -
                     measure_osc(w_bvm, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"]) / 0.010
        kb_b = (measure_osc(w_kbp, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"] -
                measure_osc(w_kbm, "v(v0p)", "v(v0n)", win_s, stop2)["f_hz"]) / 0.002
        out["B"][cfg["key"]] = dict(
            vbp=locks["B"][cfg["key"]]["vbp"], vbn=vbn_b, vrep=vrep_b, v0min=v0min_b,
            f_hz=m_b["f_hz"], period_s=m_b["period_s"],
            core_swing_mv=m_b["swing_v"] * 1e3, buf_swing_mv=m_bb["swing_v"] * 1e3,
            dcd_pct=m_bb["dcd_pct"], quad_err=qb,
            kvco_hz_v=kvco_b, kb_hz_v=kb_b, kvdd_dc_hz_v=kvdd_dc_b,
            p_core_mw=icore_b * c.supply * 1e3,
            p_bias_mw=ibias_b * c.supply * 1e3,
            p_core_plus_bias_mw=(icore_b + ibias_b) * c.supply * 1e3,
            p_buf_mw=ibuf_b * c.supply * 1e3,
            p_total_mw=itot_b * c.supply * 1e3,
            icore_ma=icore_b * 1e3,
            wave=extract_wave_slice(w_b, dict(core_diff=("v(v0p)", "v(v0n)"),
                                              buf_i=("v(b0p)", "v(b0n)"),
                                              buf_q=("v(b2p)", "v(b2n)"),
                                              v0p="v(v0p)"),
                                    win_s, 2.0, m_b["period_s"]),
        )

        # --- Arch C ---
        w_c = spice.Waves(find_valid_raw(sdir / "p2", f"c_{tag}", "nom.raw", stop2))
        w_cm = spice.Waves(find_valid_raw(sdir / "p2", f"c_{tag}", "vm.raw", stop2))
        w_cp = spice.Waves(find_valid_raw(sdir / "p2", f"c_{tag}", "vp.raw", stop2))
        w_cvm = spice.Waves(find_valid_raw(sdir / "p2", f"c_{tag}", "vdd_m.raw", stop2))
        w_cvp = spice.Waves(find_valid_raw(sdir / "p2", f"c_{tag}", "vdd_p.raw", stop2))
        m_ct = measure_osc(w_c, "v(vp)", "v(vn)", win_s, stop2)
        m_ci = measure_osc(w_c, "v(ip)", "v(in)", win_s, stop2)
        qc = measure_quad_error(w_c, "v(ip)", "v(in)", "v(qp)", "v(qn)", win_s, stop2)
        sel = w_c.t >= win_s
        icore_c = float(np.mean(w_c["i(v.xdut.vcore_sense)"][sel]))
        idiv_c = float(np.mean(w_c["i(v.xdut.vdiv_sense)"][sel]))
        itot_c = float(-np.mean(w_c["i(vdd)"][sel]))
        # Measure I+/I- max slew rate for /2 additive phase-noise floor calculation
        yi_c = (w_c["v(ip)"] - w_c["v(in)"])[sel]
        slew_div2 = float(np.max(np.abs(np.gradient(yi_c, w_c.t[sel]))))
        kvco_c_out = (measure_osc(w_cp, "v(vp)", "v(vn)", win_s, stop2)["f_hz"] -
                      measure_osc(w_cm, "v(vp)", "v(vn)", win_s, stop2)["f_hz"]) / 2.0 / 0.080
        kvdd_dc_c = (measure_osc(w_cvp, "v(vp)", "v(vn)", win_s, stop2)["f_hz"] -
                     measure_osc(w_cvm, "v(vp)", "v(vn)", win_s, stop2)["f_hz"]) / 2.0 / 0.010
        out["C"][cfg["key"]] = dict(
            code=locks["C"][cfg["key"]]["code"], vctrl=locks["C"][cfg["key"]]["vctrl"],
            f_lc_hz=m_ct["f_hz"], f_hz=m_ci["f_hz"],
            period_lc_s=m_ct["period_s"], period_s=m_ci["period_s"],
            tank_swing_mv=m_ct["swing_v"] * 1e3, iq_swing_mv=m_ci["swing_v"] * 1e3,
            dcd_pct=m_ci["dcd_pct"], quad_err=qc, slew_div2_v_s=slew_div2,
            kvco_hz_v=kvco_c_out, kvdd_dc_hz_v=kvdd_dc_c,
            p_core_mw=icore_c * c.supply * 1e3,
            p_div2_mw=idiv_c * c.supply * 1e3,
            p_total_mw=itot_c * c.supply * 1e3,
            icore_ma=icore_c * 1e3,
            wave=extract_wave_slice(w_c, dict(tank_diff=("v(vp)", "v(vn)"),
                                              iq_i=("v(ip)", "v(in)"),
                                              iq_q=("v(qp)", "v(qn)")),
                                    win_s, 2.0, m_ci["period_s"]),
        )
        print(f"  [lock]  {cfg['key']:18s} | "
              f"A: {m_a['f_hz']/1e9:.4f}G Vc={locks['A'][cfg['key']]['vctrl']:.3f}V(Vreg={vreg_a:.2f}V) K={kvco_a/1e6:+.0f} P={out['A'][cfg['key']]['p_core_plus_reg_mw']:.1f}/{out['A'][cfg['key']]['p_total_mw']:.1f}mW | "
              f"B: {m_b['f_hz']/1e9:.4f}G Vbp={locks['B'][cfg['key']]['vbp']:.3f}V K={kvco_b/1e6:+.0f} P={out['B'][cfg['key']]['p_core_plus_bias_mw']:.1f}/{out['B'][cfg['key']]['p_total_mw']:.1f}mW | "
              f"C: {m_ci['f_hz']/1e9:.4f}G(LC {m_ct['f_hz']/1e9:.3f}G) c={locks['C'][cfg['key']]['code']} K={kvco_c_out/1e6:+.0f} P={out['C'][cfg['key']]['p_core_mw']:.1f}+{out['C'][cfg['key']]['p_div2_mw']:.1f}mW",
              flush=True)

    (sdir / "summary.json").write_text(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------------------
# Stage 3: 20 MHz AC Supply-Tone Pushing Kvdd(20 MHz)
# ---------------------------------------------------------------------------

def stage_psrr(workers: int, lock: dict) -> dict:
    sdir = OUT / "stage3_psrr"
    sdir.mkdir(parents=True, exist_ok=True)
    fm, amp, settle, periods = 20e6, 5e-3, 12e-9, 1
    stop = settle + (periods + 1) / fm + 1e-9  # 113 ns (1 dropped period + 1 full period = 125 cycles @ 2.5 GHz)
    jobs = []

    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])
        vdd_sin = f"Vdd vdd 0 DC {c.supply:.6f} SIN({c.supply:.6f} {amp:.5e} {fm:.5e} {settle:.5e})"

        # Arch A (Vctrl referenced to GND, alpha=0)
        la = lock["A"][cfg["key"]]
        if find_valid_raw(sdir, f"a_{tag}", "tone.raw", stop, ["v(v0p)", "v(v0n)"]) is None:
            head = header_arch_a(cfg, vctrl=la["vctrl"], vdd_src=vdd_sin)
            ctrl = [".control", "set num_threads=1", "set filetype=binary",
                    f"tran 2p {stop:.6e} {settle:.6e} 2p",
                    "write tone.raw v(v0p) v(v0n) v(vreg)", "quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"a_{tag}"), dict(timeout_s=1200)))

        # Arch B: BOTH alpha=0 (Vbp referenced to GND) AND alpha=1 (Vbp referenced to VDD, native Maneatis!)
        lb = lock["B"][cfg["key"]]
        for al, aname in ((0.0, "a0"), (1.0, "a1")):
            if find_valid_raw(sdir, f"b_{tag}_{aname}", "tone.raw", stop, ["v(v0p)", "v(v0n)"]) is None:
                vbp_src = (f"Vbp vbp 0 DC {lb['vbp']:.6f} SIN({lb['vbp']:.6f} {al*amp:.5e} {fm:.5e} {settle:.5e})"
                           if al else f"Vbp vbp 0 {lb['vbp']:.6f}")
                head = header_arch_b(cfg, vbp=lb["vbp"], vdd_src=vdd_sin, vbp_src=vbp_src)
                ctrl = [".control", "set num_threads=1", "set filetype=binary",
                        f"tran 2p {stop:.6e} {settle:.6e} 2p",
                        "write tone.raw v(v0p) v(v0n) v(vbn)", "quit", ".endc", ".end", ""]
                jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"b_{tag}_{aname}"), dict(timeout_s=1200)))

        # Arch C (Vctrl referenced to GND, coarse bits tracking VDD)
        lc = lock["C"][cfg["key"]]
        if find_valid_raw(sdir, f"c_{tag}", "tone.raw", stop, ["v(ip)", "v(in)"]) is None:
            head = header_arch_c(cfg, code=lc["code"], vctrl=lc["vctrl"], vdd_src=vdd_sin, cfg_track_sin=True)
            ctrl = [".control", "set num_threads=1", "set filetype=binary",
                    f"tran 2p {stop:.6e} {settle:.6e} 2p uic",
                    "write tone.raw v(vp) v(vn) v(ip) v(in)", "quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"c_{tag}"), dict(timeout_s=1500)))

    run_batch(jobs, workers, "stage3-psrr")

    out = {"A": {}, "B": {}, "C": {}}
    for cfg in CORNERS:
        tag = cid(cfg["key"])
        ra = fit_tone_phasor(spice.Waves(find_valid_raw(sdir, f"a_{tag}", "tone.raw", stop)), "v(v0p)", "v(v0n)", fm, settle, amp)
        rb0 = fit_tone_phasor(spice.Waves(find_valid_raw(sdir, f"b_{tag}_a0", "tone.raw", stop)), "v(v0p)", "v(v0n)", fm, settle, amp)
        rb1 = fit_tone_phasor(spice.Waves(find_valid_raw(sdir, f"b_{tag}_a1", "tone.raw", stop)), "v(v0p)", "v(v0n)", fm, settle, amp)
        rc_ = fit_tone_phasor(spice.Waves(find_valid_raw(sdir, f"c_{tag}", "tone.raw", stop)), "v(vp)", "v(vn)", fm, settle, amp)
        # Convert 5.0 GHz LC tank pushing to 2.5 GHz /2 output pushing (divide by 2!)
        for k_fld in ("f0", "k_real", "k_quad", "k_mag"):
            rc_[k_fld] = rc_[k_fld] / 2.0
        out["A"][cfg["key"]] = ra
        out["B"][cfg["key"]] = dict(a0_gnd=rb0, a1_vdd=rb1, k_mag_gnd=rb0["k_mag"], k_mag_vdd=rb1["k_mag"])
        out["C"][cfg["key"]] = rc_
        print(f"  [psrr]  {cfg['key']:18s} | 20 MHz |Kvdd| (MHz/V) -> "
              f"A={ra['k_mag']/1e6:5.1f} | B(gnd/vdd)={rb0['k_mag']/1e6:6.1f}/{rb1['k_mag']/1e6:5.1f} | C={rc_['k_mag']/1e6:5.1f}",
              flush=True)

    (sdir / "summary.json").write_text(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------------------
# Stage 4: Hajimiri-Lee ISF & Cyclostationary gm(x)/Id(x) Probes
# ---------------------------------------------------------------------------

def one_period_wave(w: spice.Waves, pos: str, neg: str, t_end: float, keys: list[str]):
    sel = w.t < t_end
    t = w.t[sel]
    y = (w[pos] - w[neg])[sel]
    e, p = crossings(t, y)
    r = e[p > 0]
    t0, t1 = r[-3], r[-2]
    s = (t >= t0) & (t < t1)
    x = (t[s] - t0) / (t1 - t0)
    o = np.argsort(x)
    res = {"x": x[o]}
    for k in keys:
        res[k] = w[k][sel][s][o]
    return res


def isf_harm_weights(imp: pnoise.Impulse, n_g: int = 256, n_h: int = 16) -> list[float]:
    g = (np.arange(n_g) + 0.5) / n_g
    hg = imp.at(g)
    fft_h = np.fft.rfft(hg) / n_g
    return [float(abs(fft_h[0]) ** 2)] + [float(2.0 * abs(fft_h[k]) ** 2) for k in range(1, n_h)]


def impulse_response_local(t: np.ndarray, y: np.ndarray, pulses: np.ndarray,
                           charge: float, fit: int = 4) -> pnoise.Impulse:
    """Drift-immune Hajimiri-Lee ISF: uses each pulse's local pre/post period to eliminate slow bias drift."""
    e, pol = crossings(t, y)
    r = e[pol > 0]
    if len(r) < 2 * fit + 2:
        raise ValueError("too few crossings")
    pers, xs, hs = [], [], []
    for j, p in enumerate(pulses[:-1]):
        k, nxt = np.searchsorted(r, p), np.searchsorted(r, pulses[j + 1])
        if k < fit or nxt - k < fit + 3:
            continue
        p_pre = float(np.polyfit(np.arange(fit), r[k - fit:k], 1)[0])
        p_post = float(np.polyfit(np.arange(fit), r[nxt - fit:nxt], 1)[0])
        p_loc = 0.5 * (p_pre + p_post)
        pers.append(p_loc)
        before = r[k - fit:k] - p_loc * np.arange(k - fit, k)
        after = r[nxt - fit:nxt] - p_loc * np.arange(nxt - fit, nxt)
        dt = float(np.mean(after) - np.mean(before))
        xs.append((p - r[k - 1]) / p_loc % 1.0)
        hs.append(-2.0 * np.pi * dt / p_loc / charge)
    o = np.argsort(xs)
    return pnoise.Impulse(np.array(xs)[o], np.array(hs)[o], float(np.median(pers)))


def stage_isf(workers: int, lock: dict) -> dict:
    sdir = OUT / "stage4_isf"
    sdir.mkdir(parents=True, exist_ok=True)
    jobs = []
    meta_map = {}

    # Exact ngspice internal MOSFET device probe paths
    probes_a = [
        f"@m.xdut.x0.xmn_p.xmos.{NLVT}[gm]",  f"@m.xdut.x0.xmn_p.xmos.{NLVT}[id]",
        f"@m.xdut.x0.xmp_p.xmos.{PSVT}[gm]",  f"@m.xdut.x0.xmp_p.xmos.{PSVT}[id]",
        f"@m.xdut.x0.xmln_p.xmos.{NLVT}[gm]", f"@m.xdut.x0.xmln_p.xmos.{NLVT}[id]",
        f"@m.xdut.x0.xmlp_p.xmos.{PSVT}[gm]", f"@m.xdut.x0.xmlp_p.xmos.{PSVT}[id]",
    ]
    probes_b = {
        "pl": [
            f"@m.xdut.x0.xp1p.xmos.{PLVT_M}[gm]", f"@m.xdut.x0.xp1p.xmos.{PLVT_M}[id]",
            f"@m.xdut.x0.xp2p.xmos.{PLVT_M}[gm]", f"@m.xdut.x0.xp2p.xmos.{PLVT_M}[id]",
        ],
        "mp": [f"@m.xdut.x0.xmp.xmos.{NLVT}[gm]", f"@m.xdut.x0.xmp.xmos.{NLVT}[id]"],
        "mt": [f"@m.xdut.x0.xtail.xmos.{NSVT}[gm]", f"@m.xdut.x0.xtail.xmos.{NSVT}[id]"],
    }
    sites_b = {"pl": ("vdd", "v0p"), "mp": ("v0p", "xdut.x0.tail"), "mt": ("xdut.x0.tail", "0")}
    probes_c = {
        "se": [f"@m.xdut.xcore.xmp1.xmos.{PLVT_M}[gm]", f"@m.xdut.xcore.xmp1.xmos.{PLVT_M}[id]"],
        "mn": [f"@m.xdut.xcore.xmn1.xmos.{NLVT}[gm]", f"@m.xdut.xcore.xmn1.xmos.{NLVT}[id]"],
        "mt": [f"@m.xdut.xcore.xtail.xmos.{NSVT}[gm]", f"@m.xdut.xcore.xtail.xmos.{NSVT}[id]"],
    }
    sites_c = {"se": ("vp", "0"), "mn": ("vp", "xdut.xcore.tail"), "mt": ("xdut.xcore.tail_d", "0")}

    for cfg in CORNERS:
        tag = cid(cfg["key"])

        # --- Arch A (1 site: v0p -> 0, settle=36 ns so Xreg settles < 1 fs, q=2 fC, 20 phases x 7 periods) ---
        la = lock["A"][cfg["key"]]
        per_a = la["period_s"]
        ph_a, ev_a, cov_a, q_a, set_a = 20, 7, 1.25, 2.0e-15, 36e-9
        sp_a = ev_a * per_a + cov_a * per_a / ph_a
        stop_a = set_a + (ph_a + 2) * sp_a
        pwl_a, cen_a = pnoise.pulse_train(set_a, sp_a, ph_a + 1, q_a)
        meta_map[("A", cfg["key"])] = dict(period=per_a, stop=stop_a, settle=set_a, charge=q_a, centres=cen_a.tolist())
        if find_valid_raw(sdir, f"a_{tag}_out2", "out.raw", stop_a, ["v(v0p)", "v(v0n)", *probes_a]) is None:
            head = header_arch_a(cfg, vctrl=la["vctrl"], reltol="1e-5",
                                 inject=f"Iinj v0p 0 {pwl_a}", extra_save=" ".join(probes_a))
            ctrl = [".control", "set num_threads=1", "set filetype=binary",
                    f"tran 1.5p {stop_a:.6e} {set_a - 2.0e-9:.6e} 1.5p",
                    f"write out.raw v(v0p) v(v0n) {' '.join(probes_a)}", "quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"a_{tag}_out2"), dict(timeout_s=1500)))

        # --- Arch B (3 sites: pl, mp, mt, 20 phases x 7 periods) ---
        lb = lock["B"][cfg["key"]]
        per_b = lb["period_s"]
        ph_b, ev_b, cov_b, q_b, set_b = 20, 7, 1.25, 0.5e-15, 8e-9
        sp_b = ev_b * per_b + cov_b * per_b / ph_b
        stop_b = set_b + (ph_b + 2) * sp_b
        pwl_b, cen_b = pnoise.pulse_train(set_b, sp_b, ph_b + 1, q_b)
        meta_map[("B", cfg["key"])] = dict(period=per_b, stop=stop_b, settle=set_b, charge=q_b, centres=cen_b.tolist())
        for site in ("pl", "mp", "mt"):
            pr = probes_b[site]
            if find_valid_raw(sdir, f"b_{tag}_{site}", f"{site}.raw", stop_b, ["v(v0p)", "v(v0n)", *pr]) is None:
                a_n, b_n = sites_b[site]
                head = header_arch_b(cfg, vbp=lb["vbp"], reltol="1e-5",
                                     inject=f"Iinj {a_n} {b_n} {pwl_b}", extra_save=" ".join(pr))
                ctrl = [".control", "set num_threads=1", "set filetype=binary",
                        f"tran 1.5p {stop_b:.6e} {set_b - 2.0e-9:.6e} 1.5p",
                        f"write {site}.raw v(v0p) v(v0n) {' '.join(pr)}", "quit", ".endc", ".end", ""]
                jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"b_{tag}_{site}"), dict(timeout_s=1500)))

        # --- Arch C (3 sites at 5.0 GHz: se, mn, mt; settle=40 ns, q=20 fC -> 0.5 ps SNR, 16 phases x 16 cycles) ---
        lc = lock["C"][cfg["key"]]
        per_c = lc["period_lc_s"]
        ph_c, ev_c, cov_c, q_c, set_c = 16, 16, 1.25, 20.0e-15, 40e-9
        sp_c = ev_c * per_c + cov_c * per_c / ph_c
        stop_c = set_c + (ph_c + 2) * sp_c
        pwl_c, cen_c = pnoise.pulse_train(set_c, sp_c, ph_c + 1, q_c, width=2.0e-12, edge=1.0e-12)
        meta_map[("C", cfg["key"])] = dict(period=per_c, stop=stop_c, settle=set_c, charge=q_c, centres=cen_c.tolist())
        for site in ("se", "mn", "mt"):
            pr = probes_c[site]
            if find_valid_raw(sdir, f"c_{tag}_{site}2", f"{site}.raw", stop_c, ["v(vp)", "v(vn)", *pr]) is None:
                a_n, b_n = sites_c[site]
                head = header_arch_c(cfg, code=lc["code"], vctrl=lc["vctrl"], reltol="2e-4",
                                     inject=f"Iinj {a_n} {b_n} {pwl_c}", extra_save=" ".join(pr))
                ctrl = [".control", "set num_threads=1", "set filetype=binary",
                        f"tran 1.5p {stop_c:.6e} {set_c - 2.0e-9:.6e} 1.5p uic",
                        f"write {site}.raw v(vp) v(vn) {' '.join(pr)}", "quit", ".endc", ".end", ""]
                jobs.append((head + "\n".join(ctrl), spice.next_run_dir(sdir, f"c_{tag}_{site}2"), dict(timeout_s=1800)))

    run_batch(jobs, workers, "stage4-isf")

    out = {"A": {}, "B": {}, "C": {}}
    for cfg in CORNERS:
        tag = cid(cfg["key"])
        # Arch A
        ma = meta_map[("A", cfg["key"])]
        p_a = find_valid_raw(sdir, f"a_{tag}_out2", "out.raw", ma["stop"])
        w_a = spice.Waves(p_a)
        imp_a = impulse_response_local(w_a.t, w_a["v(v0p)"] - w_a["v(v0n)"], np.array(ma["centres"]), ma["charge"], fit=3)
        gap_a = float(np.max(np.diff(np.r_[imp_a.x, imp_a.x[0] + 1.0])))
        out["A"][cfg["key"]] = dict(
            raw=str(p_a.relative_to(ROOT)), settle=ma["settle"], charge=ma["charge"],
            x=imp_a.x.tolist(), h=imp_a.h.tolist(), period=imp_a.period, gap=gap_a,
            h_rms=float(np.sqrt(pnoise.white_coefficient(imp_a))),
            h_mean=float(pnoise.slow_coefficient(imp_a)),
            harm_w=isf_harm_weights(imp_a),
        )

        # Arch B
        mb = meta_map[("B", cfg["key"])]
        sb = {}
        for site in ("pl", "mp", "mt"):
            p_b = find_valid_raw(sdir, f"b_{tag}_{site}", f"{site}.raw", mb["stop"])
            w_b = spice.Waves(p_b)
            imp_b = pnoise.impulse_response(w_b.t, w_b["v(v0p)"] - w_b["v(v0n)"], np.array(mb["centres"]), mb["charge"], fit=3)
            gap_b = float(np.max(np.diff(np.r_[imp_b.x, imp_b.x[0] + 1.0])))
            sb[site] = dict(
                raw=str(p_b.relative_to(ROOT)), x=imp_b.x.tolist(), h=imp_b.h.tolist(),
                period=imp_b.period, gap=gap_b,
                h_rms=float(np.sqrt(pnoise.white_coefficient(imp_b))),
                h_mean=float(pnoise.slow_coefficient(imp_b)),
                harm_w=isf_harm_weights(imp_b),
            )
        out["B"][cfg["key"]] = dict(settle=mb["settle"], charge=mb["charge"], sites=sb)

        # Arch C
        mc = meta_map[("C", cfg["key"])]
        sc = {}
        for site in ("se", "mn", "mt"):
            p_c = find_valid_raw(sdir, f"c_{tag}_{site}2", f"{site}.raw", mc["stop"])
            w_c = spice.Waves(p_c)
            imp_c = impulse_response_local(w_c.t, w_c["v(vp)"] - w_c["v(vn)"], np.array(mc["centres"]), mc["charge"], fit=4)
            gap_c = float(np.max(np.diff(np.r_[imp_c.x, imp_c.x[0] + 1.0])))
            sc[site] = dict(
                raw=str(p_c.relative_to(ROOT)), x=imp_c.x.tolist(), h=imp_c.h.tolist(),
                period=imp_c.period, gap=gap_c,
                h_rms=float(np.sqrt(pnoise.white_coefficient(imp_c))),
                h_mean=float(pnoise.slow_coefficient(imp_c)),
                harm_w=isf_harm_weights(imp_c),
            )
            if site == "se":
                # Also build differential ISF h_diff(x) = h_se(x) - h_se(x + 0.5) & save vp(x) wave for varactor averaging
                g = (np.arange(256) + 0.5) / 256.0
                hd = imp_c.at(g) - imp_c.at(g + 0.5)
                imp_d = pnoise.Impulse(g, hd, imp_c.period)
                sc["diff"] = dict(
                    x=g.tolist(), h=hd.tolist(), period=imp_c.period,
                    h_rms=float(np.sqrt(pnoise.white_coefficient(imp_d))),
                    h_mean=float(pnoise.slow_coefficient(imp_d)),
                    harm_w=isf_harm_weights(imp_d),
                )
                wv = one_period_wave(w_c, "v(vp)", "v(vn)", mc["settle"] - 0.1e-9, ["v(vp)"])
                g64 = np.linspace(0, 1, 65)[:-1]
                vp_g = np.interp(g64, wv["x"], wv["v(vp)"], period=1.0)
                sc["vp_wave"] = dict(x=g64.tolist(), v=vp_g.tolist(),
                                     v_min=float(np.min(vp_g)), v_max=float(np.max(vp_g)), v_mean=float(np.mean(vp_g)))
        out["C"][cfg["key"]] = dict(settle=mc["settle"], charge=mc["charge"], sites=sc)
        print(f"  [isf]   {cfg['key']:18s} | "
              f"A h_rms={out['A'][cfg['key']]['h_rms']:.2e} (gap={gap_a:.3f}) | "
              f"B h_rms(pl/mp/mt)={sb['pl']['h_rms']:.2e}/{sb['mp']['h_rms']:.2e}/{sb['mt']['h_rms']:.2e} | "
              f"C h_rms(se/diff/mn/mt)={sc['se']['h_rms']:.2e}/{sc['diff']['h_rms']:.2e}/{sc['mn']['h_rms']:.2e}/{sc['mt']['h_rms']:.2e}",
              flush=True)

    (sdir / "summary.json").write_text(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------------------
# Stage 5: ngspice .noise (sparse) for ALL Devices, Regulators, Bias, Tank, Varactor, /2
# ---------------------------------------------------------------------------

def ensure_noisy_varactor(out_dir: Path) -> Path:
    dest = out_dir / "sky130_fd_pr__cap_var_lvt_noisy.model.spice"
    if not dest.exists():
        src = project.model_library().parents[2] / "libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_var_lvt.model.spice"
        info = noise_models.varactor_rg(src, dest)
        (out_dir / "varactor_noise_overlay.json").write_text(json.dumps(info, indent=2))
    return dest


def stage_noise(workers: int, lock: dict, isf: dict) -> dict:
    sdir = OUT / "stage5_noise"
    sdir.mkdir(parents=True, exist_ok=True)
    noisy_var = ensure_noisy_varactor(sdir)

    # Device families to characterize gamma(Id) and K_1/f(Id) per corner:
    # (name, subckt_type, w, l, nf, is_pmos, vgs_list)
    dev_specs = [
        ("nlvt_015", "serdes_nfet_lvt", 24.0, 0.15, 8,  False, [0.35, 0.50, 0.65, 0.85, 1.10]),
        ("psvt_015", "serdes_pfet",     48.0, 0.15, 16, True,  [0.50, 0.65, 0.80, 1.00, 1.25]),
        ("plvt_035", "serdes_pfet_lvt", 32.0, 0.35, 8,  True,  [0.35, 0.50, 0.65, 0.85, 1.10]),
        ("nsvt_025", "serdes_nfet",     64.0, 0.25, 16, False, [0.55, 0.70, 0.85, 1.00, 1.15]),
        ("nsvt_050", "serdes_nfet",     80.0, 0.50, 16, False, [0.60, 0.75, 0.90, 1.05, 1.20]),
    ]

    jobs = []
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])
        lib = spice.corner_values(c)["MODEL_LIBRARY"]
        la, lb, lc = lock["A"][cfg["key"]], lock["B"][cfg["key"]], lock["C"][cfg["key"]]
        vp_w = isf["C"][cfg["key"]]["sites"]["vp_wave"]
        v_gates = np.linspace(vp_w["v_min"], vp_w["v_max"], 5).tolist()

        # Deck 1: Active FET noise tables (all 5 device families)
        if find_valid_noise_raw(sdir / "devs", tag, "nsvt_050_4.raw", 1e9) is None:
            lines = [
                f"* Active FET noise tables ({cfg['key']})",
                f'.lib "{lib}" {c.process}',
                f'.include "{PRIMS}"',
                f'.include "{PLVT}"',
            ]
            for nm, sub, w, l, nf, is_p, _ in dev_specs:
                if not is_p:
                    lines += [
                        f"Vd_{nm} vdr_{nm} 0 0.7",
                        f"Rs_{nm} vdr_{nm} d_{nm} 100 noisy=0",
                        f"Vg_{nm} g_{nm} 0 0.7 ac 1",
                        f"Xm_{nm} d_{nm} g_{nm} 0 0 {sub} w={w} l={l} nf={nf}",
                    ]
                else:
                    lines += [
                        f"Vs_{nm} s_{nm} 0 1.8",
                        f"Vd_{nm} vdr_{nm} 0 1.0",
                        f"Rs_{nm} vdr_{nm} d_{nm} 100 noisy=0",
                        f"Vg_{nm} g_{nm} 0 1.1 ac 1",
                        f"Xm_{nm} d_{nm} g_{nm} s_{nm} s_{nm} {sub} w={w} l={l} nf={nf}",
                    ]
            lines += [f".temp {c.temp}", ".options sparse", ".control", "set num_threads=1", "set filetype=binary"]
            for nm, _, _, _, _, is_p, vgs_list in dev_specs:
                for k, vgs in enumerate(vgs_list):
                    vg0 = (1.8 - vgs) if is_p else vgs
                    vg1 = (1.8 - vgs - 0.01) if is_p else (vgs + 0.01)
                    lines += [
                        f"alter Vg_{nm} dc={vg0:.5f}", "op",
                        f"print i(Vd_{nm}) > {nm}_op0_{k}.txt", "destroy all",
                        f"alter Vg_{nm} dc={vg1:.5f}", "op",
                        f"print i(Vd_{nm}) > {nm}_op1_{k}.txt", "destroy all",
                        f"alter Vg_{nm} dc={vg0:.5f}",
                        f"noise v(d_{nm}) Vg_{nm} dec 6 1k 2g",
                        "setplot previous",
                        f"write {nm}_{k}.raw onoise_spectrum", "destroy all",
                    ]
            lines += ["quit", ".endc", ".end", ""]
            jobs.append((bias.section("\n".join(lines), c.process, rc),
                         spice.next_run_dir(sdir / "devs", tag), dict(timeout_s=900)))

        # Deck 2: Subsystem & Passive noise (Arch A reg, Arch B replica servo, Arch C ind + varactor + bank + /2 latch)
        if find_valid_noise_raw(sdir / "subsys", tag, "div2_n.raw", 1e9) is None:
            lines = [
                f"* Subsystem & Passive noise ({cfg['key']})",
                f'.lib "{lib}" {c.process}',
                f'.include "{PRIMS}"',
                f'.include "{PLVT}"',
                f'.include "{NET_A}"',
                f'.include "{NET_B}"',
                f'.include "{NET_C}"',
                f'.include "{noisy_var}"',
                f"Vdd vdd 0 dc {c.supply:.6f} ac 1",
                # 1) Arch A supply regulator loaded with ring small-signal R_ring_ac (in series with DC current sink)
                f"Vctrl_a vctrl_a 0 {la['vctrl']:.6f}",
                "Xreg_a vctrl_a vreg_a vdd 0 vco5g_cmos_reg_ldo",
                f"Iring_a vreg_a 0 {la['icore_ma']*1e-3:.6e}",
                # AC-coupled small-signal ring resistance R_ring_ac (noiseless!) so regulator sees exact AC load Z
                "Cac_ra vreg_a vreg_ac 1u",
                f"Rring_ac vreg_ac 0 {max(la['r_ring_ac_ohm'], 30.0):.4f} noisy=0",
                # 2) Arch B replica-bias servo OTA output V_bn noise
                f"Vbp_b vbp_b 0 {lb['vbp']:.6f}",
                "Xbias_b vbp_b vbn_b vdd 0 vco5g_maneatis_bias",
                # 3) Arch C inductor pi-model exact differential short-circuit current noise across 1 Ohm sense R!
                f"Xind_c ind_p ind_n ind_ct 0 vco5g_ind_oct_2n2 rm_scale={cfg['rm_scale']} c_scale={cfg['c_scale']}",
                "Rdc_ind ind_ct 0 1G noisy=0",
                "Rs_ind ind_p ind_n 1.0 noisy=0",
                # 4) Arch C noisy=1 varactor rg noise (5 gate voltages spanning vp(x)) + AC C_var at 20 MHz
                f"Vvg_c vg_c_src 0 {vp_w['v_mean']:.5f} ac 1",
                "Rs_var vg_c_src vg_c 1.0 noisy=0",
                f"Vvw_c vw_c 0 {lc['vctrl']:.6f}",
                f"Xvar_c vg_c vw_c 0 {noise_models.NOISY_VARACTOR} w=5.2 l=0.5 vm=6",
                f"Vvg_c2 vg_c2 0 {vp_w['v_mean']:.5f}",
                f"Vvw_c2 vw_c2 0 dc {lc['vctrl']:.6f} ac 1",
                f"Xvar_c2 vg_c2 vw_c2 0 {noise_models.NOISY_VARACTOR} w=5.2 l=0.5 vm=6",
                # 5) Arch C differential MIM bank unit ON & OFF noise (1 Ohm differential sense R across vp<->vn)
                f"Vbk_cm bk_cm 0 {vp_w['v_mean']:.5f}",
                "Rs_bk bk_p bk_n 1.0 noisy=0",
                "Ldc_bkp bk_p bk_cm 1m",
                "Ldc_bkn bk_n bk_cm 1m",
                f"Vbk_en bk_en 0 {c.supply:.6f}",
                "Xbk_u bk_p bk_n bk_en vdd 0 vco5g_lc_bank_unit capw=4.2 capl=4.2 sw=16",
                # 6) Arch C CML /2 latch noise at balanced zero-crossing (estimates additive /2 phase noise floor!)
                "Xrb_d vdd vbd_n 0 sky130_fd_pr__res_high_po_1p41 l=14.0",
                "Xnb_d vbd_n vbd_n 0 0 serdes_nfet w=6 l=0.35 nf=2",
                f"Vd_cm d_cm 0 {c.supply - 0.30:.5f}",
                f"Vck_hi ck_hi 0 {min(c.supply - 0.25, 1.35):.5f}",
                f"Vck_lo ck_lo 0 {0.70:.5f}",
                "Xlatch d_cm d_cm lqp lqn ck_hi ck_lo vbd_n vdd 0 vco5g_cml_latch_5g",
                "Clqp lqp 0 30f", "Clqn lqn 0 30f",
                f".temp {c.temp}",
                ".options sparse",
                ".control",
                "set num_threads=1",
                "set filetype=binary",
                # Arch A regulator noise
                "noise v(vreg_a) Vdd dec 10 1k 2g",
                "setplot previous", "write reg_a.raw onoise_spectrum", "destroy all",
                # Arch B replica-servo Vbn noise
                "noise v(vbn_b) Vdd dec 10 1k 2g",
                "setplot previous", "write bias_b.raw onoise_spectrum", "destroy all",
                # Arch C inductor differential current noise (across 1 Ohm sense R -> S_I = S_v / 1^2!)
                "noise v(ind_p,ind_n) Vdd dec 15 100meg 30g",
                "setplot previous", "write ind_c.raw onoise_spectrum", "destroy all",
            ]
            # Arch C varactor across 5 gate voltages
            for k, vg in enumerate(v_gates):
                lines += [
                    f"alter Vvg_c dc={vg:.5f}",
                    "noise v(vg_c) Vvg_c dec 12 100meg 40g",
                    "setplot previous", f"write var_c_{k}.raw onoise_spectrum", "destroy all",
                    f"alter Vvg_c2 dc={vg:.5f}",
                    "ac lin 1 20meg 20meg",
                    "let c_well = real(imag(-i(Vvw_c2)) / (2 * 3.141592653589793 * 20e6))",
                    f"print c_well > var_c_{k}.txt", "destroy all",
                ]
            lines += [
                # Bank unit ON & OFF
                f"alter Vbk_en dc={c.supply:.6f}",
                "noise v(bk_p,bk_n) Vdd dec 12 100meg 40g",
                "setplot previous", "write bk_on.raw onoise_spectrum", "destroy all",
                "alter Vbk_en dc=0",
                "noise v(bk_p,bk_n) Vdd dec 12 100meg 40g",
                "setplot previous", "write bk_off.raw onoise_spectrum", "destroy all",
                # /2 latch noise
                "noise v(lqp,lqn) Vdd dec 8 10k 5g",
                "setplot previous", "write div2_n.raw onoise_spectrum", "destroy all",
                "quit", ".endc", ".end", "",
            ]
            jobs.append((bias.section("\n".join(lines), c.process, rc),
                         spice.next_run_dir(sdir / "subsys", tag), dict(timeout_s=900)))

    run_batch(jobs, workers, "stage5-noise")

    def parse_first_abs(path: Path) -> float:
        for line in path.read_text().splitlines():
            if "=" in line:
                return abs(float(line.split("=", 1)[1].strip().split()[0]))
        raise ValueError(f"No value in {path}")

    out = {}
    for cfg in CORNERS:
        c, rc = parse_corner(cfg["key"])
        tag = cid(cfg["key"])
        T = c.temp + 273.15
        vp_w = isf["C"][cfg["key"]]["sites"]["vp_wave"]
        v_gates = np.linspace(vp_w["v_min"], vp_w["v_max"], 5).tolist()

        d_dev = find_valid_noise_raw(sdir / "devs", tag, "nsvt_050_4.raw", 1e9).parent
        d_sub = find_valid_noise_raw(sdir / "subsys", tag, "div2_n.raw", 1e9).parent

        devices = {}
        for nm, _, _, _, _, _, vgs_list in dev_specs:
            rows = []
            for k, vgs in enumerate(vgs_list):
                i0 = parse_first_abs(d_dev / f"{nm}_op0_{k}.txt")
                i1 = parse_first_abs(d_dev / f"{nm}_op1_{k}.txt")
                gm = max(abs(i1 - i0) / 0.01, 1e-9)
                w = spice.Waves(d_dev / f"{nm}_{k}.raw")
                sid = (w["onoise_spectrum"] / 100.0) ** 2
                s_th = float(np.interp(1e9, w.t, sid))
                k_100k = float(max(np.interp(1e5, w.t, sid) - s_th, 1e-35) * 1e5)
                k_1m = float(max(np.interp(1e6, w.t, sid) - s_th, 1e-35) * 1e6)
                rows.append(dict(vgs=vgs, id=i0, gm=gm, s_1g=s_th,
                                 gamma=s_th / (4.0 * pnoise.K_B * T * gm), k_100k=k_100k, k_1m=k_1m))
            devices[nm] = rows

        w_ra = spice.Waves(d_sub / "reg_a.raw")
        w_bb = spice.Waves(d_sub / "bias_b.raw")
        w_ic = spice.Waves(d_sub / "ind_c.raw")
        w_on = spice.Waves(d_sub / "bk_on.raw")
        w_off = spice.Waves(d_sub / "bk_off.raw")
        w_d2 = spice.Waves(d_sub / "div2_n.raw")

        # Inductor differential short-circuit current noise at 5 GHz (across 1 Ohm sense R)
        # Note: Z_ind(5 GHz) ~ 74 Ohm >> 1 Ohm -> current divider error < 0.02%!
        s_i_ind = w_ic["onoise_spectrum"] ** 2
        s_i_ind_5g = float(np.interp(5e9, w_ic.t, s_i_ind))

        # Varactor rg noise averaged over vp(x)
        var_f = None
        var_s_list, var_c_list = [], []
        for k in range(len(v_gates)):
            wv = spice.Waves(d_sub / f"var_c_{k}.raw")
            var_f = wv.t
            var_s_list.append(wv["onoise_spectrum"] ** 2)
            mc_ = re.search(r"c_well\s*=\s*([-+0-9.eE]+)", (d_sub / f"var_c_{k}.txt").read_text())
            var_c_list.append(abs(float(mc_.group(1))) if mc_ else 90e-15)
        var_s_arr = np.array(var_s_list)
        v_wave = np.array(vp_w["v"])
        var_s_mean = np.array([float(np.mean(np.interp(v_wave, v_gates, var_s_arr[:, fi]))) for fi in range(len(var_f))])
        c_var_mean = float(np.mean(np.interp(v_wave, v_gates, var_c_list)))

        out[cfg["key"]] = dict(
            devices=devices,
            reg_a=dict(f=w_ra.t.tolist(), v=w_ra["onoise_spectrum"].tolist(),
                       v_1m_nv=float(np.interp(1e6, w_ra.t, w_ra["onoise_spectrum"]) * 1e9)),
            bias_b=dict(f=w_bb.t.tolist(), v=w_bb["onoise_spectrum"].tolist(),
                        v_1m_nv=float(np.interp(1e6, w_bb.t, w_bb["onoise_spectrum"]) * 1e9)),
            ind_c=dict(f=w_ic.t.tolist(), s_i=s_i_ind.tolist(), s_i_5g=s_i_ind_5g),
            var_c=dict(f=var_f.tolist(), s_mean=var_s_mean.tolist(),
                       s_5g=float(np.interp(5e9, var_f, var_s_mean)), c_per_var_f=c_var_mean),
            bank_c=dict(f=w_on.t.tolist(), s_on=(w_on["onoise_spectrum"] ** 2).tolist(),
                        s_off=(w_off["onoise_spectrum"] ** 2).tolist(),
                        s_on_5g=float(np.interp(5e9, w_on.t, w_on["onoise_spectrum"] ** 2)),
                        s_off_5g=float(np.interp(5e9, w_off.t, w_off["onoise_spectrum"] ** 2))),
            div2_c=dict(f=w_d2.t.tolist(), v=w_d2["onoise_spectrum"].tolist(),
                        v_10m_nv=float(np.interp(1e7, w_d2.t, w_d2["onoise_spectrum"]) * 1e9)),
        )
        print(f"  [noise] {cfg['key']:18s} | regA@1M={out[cfg['key']]['reg_a']['v_1m_nv']:.1f} nV/rtHz | "
              f"biasB@1M={out[cfg['key']]['bias_b']['v_1m_nv']:.1f} nV/rtHz | "
              f"indC(5G)={s_i_ind_5g:.2e} A2/Hz | div2@10M={out[cfg['key']]['div2_c']['v_10m_nv']:.2f} nV/rtHz",
              flush=True)

    (sdir / "summary.json").write_text(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------------------
# Stage 6: Phase Noise L(df), Leeson Cross-Check, FoM, 5 Gb/s PLL Jitter & CDR
# ---------------------------------------------------------------------------

def source_table(rows):
    i = np.array([max(r["id"], 1e-12) for r in rows])
    return dict(
        lid=np.log(i),
        gamma=np.array([r["gamma"] for r in rows]),
        lk1=np.log(np.maximum([r["k_1m"] for r in rows], 1e-35)),
        lk100=np.log(np.maximum([r["k_100k"] for r in rows], 1e-35)),
    )


def device_cyclostationary_l(imp: pnoise.Impulse, x: np.ndarray, gm: np.ndarray, idd: np.ndarray,
                             tab: dict, mult: float, T: float, offs: np.ndarray, w_scale: float = 1.0):
    """Cyclostationary thermal + 1/f phase noise for `mult` uncorrelated transistors.
    w_scale = W_actual / W_table (used when same L/model is scaled in width, e.g. latch inverter vs main inverter!).
    Note: for scaled width W = w_scale * W_tab, current density Id/W is preserved by evaluating table at Id / w_scale,
    while thermal S_th = 4 k T gamma gm uses actual gm, and flicker K_1/f scales as w_scale * K_tab(Id/w_scale)!
    """
    id_eq = np.maximum(np.abs(idd) / w_scale, 1e-9)
    lid = np.log(id_eq)
    gamma = np.interp(lid, tab["lid"], tab["gamma"])
    s_th = 4.0 * pnoise.K_B * T * gamma * np.abs(gm)
    s0 = max(float(np.mean(s_th)), 1e-35)
    alpha_th = lambda g: np.sqrt(np.maximum(np.interp(g, x, s_th, period=1.0), 0.0) / s0)
    l_th = mult * pnoise.l_white(s0, pnoise.white_coefficient(imp, alpha_th), offs)

    k1 = w_scale * np.exp(np.interp(lid, tab["lid"], tab["lk1"]))
    k100 = w_scale * np.exp(np.interp(lid, tab["lid"], tab["lk100"]))
    k0 = max(float(np.mean(k1)), 1e-35)
    alpha_f = lambda g: np.sqrt(np.maximum(np.interp(g, x, k1, period=1.0), 0.0) / k0)
    mean_h = pnoise.slow_coefficient(imp, alpha_f)
    slope = float(np.log10(max(np.mean(k100), 1e-35) / k0))
    s_f = k0 * (offs / 1e6) ** (-slope) / offs
    l_fl = mult * pnoise.l_slow(s_f, mean_h, offs)
    return l_th, l_fl


def cdr_14sigma_5g_ui(f_all: np.ndarray, l_tot: np.ndarray, f0: float, *,
                      ticks: int = 1 << 18, edge: float = 7.2e-12, latency: int = 4, seed: int = 1) -> dict:
    """5 Gb/s bang-bang CDR simulation (UI = 200 ps, 16-bit word TICK = 3.2 ns, Nyq = 156.25 MHz)."""
    TICK = 16.0 * UI_5G  # 3.2 ns
    STEP = UI_5G / 32.0  # 6.25 ps
    KP = 8192.0 / 65536.0
    KI = 32.0 / 65536.0
    FLIM = 32768.0 / 65536.0

    def phase_series(rng):
        df = 1.0 / (ticks * TICK)
        f = np.arange(1, ticks // 2 + 1) * df
        lo = f < f_all[0]
        slope = np.log10(l_tot[1] / l_tot[0]) / np.log10(f_all[1] / f_all[0])
        l = np.exp(np.interp(np.log(f), np.log(f_all), np.log(l_tot)))
        l[lo] = l_tot[0] * (f[lo] / f_all[0]) ** slope
        s = 2.0 * l / (2.0 * np.pi * f0) ** 2
        x = np.zeros(ticks // 2 + 1, complex)
        x[1:] = ticks * np.sqrt(s * df / 4.0) * (rng.standard_normal(ticks // 2) + 1j * rng.standard_normal(ticks // 2))
        return np.fft.irfft(x, ticks)

    rng = np.random.default_rng(seed)
    t_in = phase_series(rng) - phase_series(rng)
    trans = rng.binomial(16, 0.5, ticks)
    noise = rng.standard_normal((ticks, 16)) * edge
    err = np.zeros(ticks)
    phase, debt, freq = 0.0, 0.0, 0.0
    pending = [0]
    votes = [0] * (latency - 1)
    for k in range(ticks):
        e = t_in[k] - phase
        err[k] = e
        m = trans[k]
        s = 0
        if m:
            total = int(np.sign(e + noise[k, :m]).sum())
            s = (total > 0) - (total < 0)
        votes.append(s)
        s = votes.pop(0)
        freq = min(FLIM, max(-FLIM, freq + KI * s))
        debt += freq + KP * s
        d = 0
        if debt >= 1.0:
            d, debt = 1, debt - 1.0
        elif debt <= -1.0:
            d, debt = -1, debt + 1.0
        pending.append(d)
        phase += pending.pop(0) * STEP

    err = err[ticks // 16:]
    err = err - err.mean()
    nyq = 0.5 / TICK  # 156.25 MHz
    hi = f_all > nyq
    s_hi = 2.0 * np.trapezoid(2.0 * l_tot[hi], f_all[hi]) / (2.0 * np.pi * f0) ** 2
    tot = float(np.sqrt(err.var() + s_hi))
    return dict(
        total_rms_ps=tot * 1e12,
        total_rms_ui=tot / UI_5G,
        pp_14p07sigma_ui=14.07 * tot / UI_5G,
        peak_err_ui=float(np.abs(err).max() / UI_5G),
    )


def optimize_pll_loop(f_pll: np.ndarray, l_vco_pll: np.ndarray, f0: float, kvco_abs: float,
                      cp_psd: np.ndarray, T: float, *, bw_targets_mhz: list[float],
                      n_div: int = 10, icp: float = 200e-6, inband_dbc: float = -123.1,
                      cf_f: float = 0.7e-12, delay: float = 2e-9) -> dict:
    """Design damped 2nd-order CP-PLL (zeta ~= 1.0 -> PM ~ 60 deg) at each target UGB and pick optimal BW."""
    best = None
    all_pts = []
    for bw_mhz in bw_targets_mhz:
        ugb_t = bw_mhz * 1e6
        # UGB ~= (Icp / (2 pi N)) * Kvco * Rz -> Rz = 2 pi N * UGB / (Icp * Kvco)
        # Zero at UGB / 4 -> Ci = 4 / (2 pi UGB Rz)
        rz = (2.0 * np.pi * n_div * ugb_t) / (icp * max(kvco_abs, 20e6))
        rz = float(np.clip(rz, 150.0, 250e3))
        ci = 4.0 / (2.0 * np.pi * ugb_t * rz)
        cf = min(cf_f, ci / 15.0)
        lp = pnoise.Loop(icp=icp, rz=rz, ci=ci, cf=cf, kvco=kvco_abs, n=n_div, delay=delay)
        ugb_act, pm_act = lp.unity_gain()
        if pm_act < 45.0:
            continue
        syn = pnoise.synthesize(f_pll, lp, l_vco_pll, inband_dbc, cp_psd, t=T)
        j_10k_100m = pnoise.rms_jitter(f_pll, syn["total"], f0, 1e4, 1e8) * 1e12
        j_10k_1g = pnoise.rms_jitter(f_pll, syn["total"], f0, 1e4, 1e9) * 1e12
        row = dict(
            target_bw_mhz=bw_mhz, ugb_mhz=ugb_act / 1e6, pm_deg=pm_act,
            rz_ohm=rz, ci_pf=ci * 1e12, cf_pf=cf * 1e12,
            j_10k_100m_ps=j_10k_100m, j_10k_1g_ps=j_10k_1g,
            j_vco_ps=pnoise.rms_jitter(f_pll, syn["VCO"], f0, 1e4, 1e8) * 1e12,
            j_cp_ps=pnoise.rms_jitter(f_pll, syn["CP"], f0, 1e4, 1e8) * 1e12,
            j_inband_ps=pnoise.rms_jitter(f_pll, syn["reference, PFD, divider"], f0, 1e4, 1e8) * 1e12,
            j_rz_ps=pnoise.rms_jitter(f_pll, syn["loop filter Rz"], f0, 1e4, 1e8) * 1e12,
            syn_total=syn["total"],
        )
        all_pts.append(row)
        if best is None or j_10k_100m < best["j_10k_100m_ps"]:
            best = row
    return dict(best=best, sweep=[{k: v for k, v in r.items() if k != "syn_total"} for r in all_pts])


def stage_synth(rng_data: dict, lock: dict, psrr: dict, isf: dict, noise: dict) -> dict:
    sdir = OUT / "stage6_synth"
    sdir.mkdir(parents=True, exist_ok=True)
    offs = np.logspace(4, 8, 81)      # 10 kHz .. 100 MHz
    f_pll = np.logspace(4, 9, 1001)   # 10 kHz .. 1 GHz

    # Load real measured CP v4 noise PSD from r6_ptat_perf_20261123 (identical CP for apples-to-apples!)
    r6_nz = json.loads(R6_NOISE.read_text())
    r6_s6 = json.loads(R6_SYNTH.read_text())

    out = {"A": {}, "B": {}, "C": {}, "r6_ref": {}}
    for k, v in r6_s6.items():
        out["r6_ref"][k] = dict(
            L_100k_dbc=v["L_100k_dbc"], L_1m_dbc=v["L_1m_dbc"], L_10m_dbc=v["L_10m_dbc"],
            fom_1m_core=v["fom"]["fom_1m_core"], p_core_mw=v["power"]["vco_core_mw"],
            p_total_mw=v["power"]["vco_total_with_bias_mw"],
            j_10k_100m_ps=v["jitter_v4"]["j_10k_100m_ps"]["total"],
            cdr_4g_14s_ui=v["cdr_v4"]["pp_14p07sigma_ui"],
            offsets=v["offsets"], L_core=v["L_core"],
        )

    for cfg in CORNERS:
        key = cfg["key"]
        c, rc = parse_corner(key)
        T = c.temp + 273.15
        nz = noise[key]
        tabs = {k: source_table(v) for k, v in nz["devices"].items()}

        # CP v4 sampled PSD on f_pll (common across all 3 architectures!)
        cp_d = r6_nz[cfg["cp_ref"]]["cp_v4"]
        s_cp_pll = np.exp(np.interp(np.log(f_pll), np.log(cp_d["f"]), np.log(np.maximum(cp_d["s_i"], 1e-35))))
        cp_seen = pnoise.cp_sampled_psd(f_pll, s_cp_pll, cfg["pfd_duty"])

        # ===================== ARCH A =====================
        la, ra, ia = lock["A"][key], rng_data["A"][key], isf["A"][key]
        f0_a = 1.0 / ia["period"]
        imp_a = pnoise.Impulse(np.array(ia["x"]), np.array(ia["h"]), ia["period"])
        wa = spice.Waves(ROOT / ia["raw"])
        pr_a = [
            f"@m.xdut.x0.xmn_p.xmos.{NLVT}[gm]",  f"@m.xdut.x0.xmn_p.xmos.{NLVT}[id]",
            f"@m.xdut.x0.xmp_p.xmos.{PSVT}[gm]",  f"@m.xdut.x0.xmp_p.xmos.{PSVT}[id]",
            f"@m.xdut.x0.xmln_p.xmos.{NLVT}[gm]", f"@m.xdut.x0.xmln_p.xmos.{NLVT}[id]",
            f"@m.xdut.x0.xmlp_p.xmos.{PSVT}[gm]", f"@m.xdut.x0.xmlp_p.xmos.{PSVT}[id]",
        ]
        op_a = one_period_wave(wa, "v(v0p)", "v(v0n)", ia["settle"] - 0.1e-9, pr_a)
        La = {}
        La["main_n_th"], La["main_n_fl"] = device_cyclostationary_l(
            imp_a, op_a["x"], op_a[pr_a[0]], op_a[pr_a[1]], tabs["nlvt_015"], 8.0, T, offs, w_scale=1.0)
        La["main_p_th"], La["main_p_fl"] = device_cyclostationary_l(
            imp_a, op_a["x"], op_a[pr_a[2]], op_a[pr_a[3]], tabs["psvt_015"], 8.0, T, offs, w_scale=1.0)
        La["lat_n_th"], La["lat_n_fl"] = device_cyclostationary_l(
            imp_a, op_a["x"], op_a[pr_a[4]], op_a[pr_a[5]], tabs["nlvt_015"], 8.0, T, offs, w_scale=4.2 / 24.0)
        La["lat_p_th"], La["lat_p_fl"] = device_cyclostationary_l(
            imp_a, op_a["x"], op_a[pr_a[6]], op_a[pr_a[7]], tabs["psvt_015"], 8.0, T, offs, w_scale=8.4 / 48.0)
        # Regulator V_reg noise pushed through Kvreg
        s_vreg = np.exp(np.interp(np.log(offs), np.log(nz["reg_a"]["f"]), np.log(np.maximum(np.array(nz["reg_a"]["v"]) ** 2, 1e-35))))
        La["reg_ldo"] = pnoise.bias_line_l(offs, s_vreg, abs(la["kvreg_hz_v"]))
        La_core = sum(v for k, v in La.items() if k != "reg_ldo")
        La_tot = La_core + La["reg_ldo"]

        l100k_a = float(pnoise.dbc(np.interp(1e5, offs, La_tot)))
        l1m_a = float(pnoise.dbc(np.interp(1e6, offs, La_tot)))
        l10m_a = float(pnoise.dbc(np.interp(1e7, offs, La_tot)))
        l1m_a_core = float(pnoise.dbc(np.interp(1e6, offs, La_core)))
        fom_a_core = -l1m_a_core + 20.0 * math.log10(f0_a / 1e6) - 10.0 * math.log10(la["p_core_mw"])
        fom_a_tot = -l1m_a + 20.0 * math.log10(f0_a / 1e6) - 10.0 * math.log10(la["p_core_plus_reg_mw"])
        # Extrapolate to f_pll and optimize 5 Gb/s PLL (10-25 MHz BW range)
        l_a_pll = 10.0 ** np.interp(np.log10(f_pll), np.log10(offs), np.log10(La_tot))
        l_a_pll[f_pll > offs[-1]] = La_tot[-1] * (offs[-1] / f_pll[f_pll > offs[-1]]) ** 2
        pll_a = optimize_pll_loop(f_pll, l_a_pll, f0_a, abs(la["kvco_hz_v"]), cp_seen, T,
                                  bw_targets_mhz=[10.0, 12.0, 15.0, 18.0, 22.0, 25.0], cf_f=0.5e-12)
        cdr_a = cdr_14sigma_5g_ui(f_pll, pll_a["best"]["syn_total"], f0_a)
        best_a = {k: v for k, v in pll_a["best"].items() if k != "syn_total"}
        out["A"][key] = dict(
            f0_hz=f0_a, offsets=offs.tolist(), L_core=La_core.tolist(), L_total=La_tot.tolist(),
            L_100k_dbc=l100k_a, L_1m_dbc=l1m_a, L_10m_dbc=l10m_a, L_1m_core_only_dbc=l1m_a_core,
            fom_1m_core=fom_a_core, fom_1m_core_reg=fom_a_tot,
            fom_t_1m=fom_a_tot + 20.0 * math.log10(ra["ftr_pct"] / 10.0),
            breakdown_1m={k: float(np.interp(1e6, offs, v) / np.interp(1e6, offs, La_tot) * 100.0) for k, v in La.items()},
            pll=best_a, pll_sweep=pll_a["sweep"], cdr_5g=cdr_a,
        )

        # ===================== ARCH B =====================
        lb, rb, ib = lock["B"][key], rng_data["B"][key], isf["B"][key]
        f0_b = 1.0 / ib["sites"]["pl"]["period"]
        Lb = {}
        # Symmetric loads P1 (diode) & P2 (Vbp)
        imp_pl = pnoise.Impulse(np.array(ib["sites"]["pl"]["x"]), np.array(ib["sites"]["pl"]["h"]), ib["sites"]["pl"]["period"])
        w_pl = spice.Waves(ROOT / ib["sites"]["pl"]["raw"])
        pr_pl = [
            f"@m.xdut.x0.xp1p.xmos.{PLVT_M}[gm]", f"@m.xdut.x0.xp1p.xmos.{PLVT_M}[id]",
            f"@m.xdut.x0.xp2p.xmos.{PLVT_M}[gm]", f"@m.xdut.x0.xp2p.xmos.{PLVT_M}[id]",
        ]
        op_pl = one_period_wave(w_pl, "v(v0p)", "v(v0n)", ib["settle"] - 0.1e-9, pr_pl)
        Lb["p1_th"], Lb["p1_fl"] = device_cyclostationary_l(
            imp_pl, op_pl["x"], op_pl[pr_pl[0]], op_pl[pr_pl[1]], tabs["plvt_035"], 8.0, T, offs, w_scale=1.0)
        Lb["p2_th"], Lb["p2_fl"] = device_cyclostationary_l(
            imp_pl, op_pl["x"], op_pl[pr_pl[2]], op_pl[pr_pl[3]], tabs["plvt_035"], 8.0, T, offs, w_scale=1.0)
        # Input NMOS pair
        imp_mp = pnoise.Impulse(np.array(ib["sites"]["mp"]["x"]), np.array(ib["sites"]["mp"]["h"]), ib["sites"]["mp"]["period"])
        w_mp = spice.Waves(ROOT / ib["sites"]["mp"]["raw"])
        pr_mp = [f"@m.xdut.x0.xmp.xmos.{NLVT}[gm]", f"@m.xdut.x0.xmp.xmos.{NLVT}[id]"]
        op_mp = one_period_wave(w_mp, "v(v0p)", "v(v0n)", ib["settle"] - 0.1e-9, pr_mp)
        Lb["in_th"], Lb["in_fl"] = device_cyclostationary_l(
            imp_mp, op_mp["x"], op_mp[pr_mp[0]], op_mp[pr_mp[1]], tabs["nlvt_015"], 8.0, T, offs, w_scale=22.0 / 24.0)
        # Tail NMOS
        imp_mt = pnoise.Impulse(np.array(ib["sites"]["mt"]["x"]), np.array(ib["sites"]["mt"]["h"]), ib["sites"]["mt"]["period"])
        w_mt = spice.Waves(ROOT / ib["sites"]["mt"]["raw"])
        pr_mt = [f"@m.xdut.x0.xtail.xmos.{NSVT}[gm]", f"@m.xdut.x0.xtail.xmos.{NSVT}[id]"]
        op_mt = one_period_wave(w_mt, "v(v0p)", "v(v0n)", ib["settle"] - 0.1e-9, pr_mt)
        Lb["tail_th"], Lb["tail_fl"] = device_cyclostationary_l(
            imp_mt, op_mt["x"], op_mt[pr_mt[0]], op_mt[pr_mt[1]], tabs["nsvt_025"], 4.0, T, offs, w_scale=1.0)
        # Replica-bias servo OTA noise on V_bn
        s_vbn = np.exp(np.interp(np.log(offs), np.log(nz["bias_b"]["f"]), np.log(np.maximum(np.array(nz["bias_b"]["v"]) ** 2, 1e-35))))
        Lb["replica_ota"] = pnoise.bias_line_l(offs, s_vbn, abs(lb["kb_hz_v"]))
        Lb_core = sum(v for k, v in Lb.items() if k != "replica_ota")
        Lb_tot = Lb_core + Lb["replica_ota"]

        l100k_b = float(pnoise.dbc(np.interp(1e5, offs, Lb_tot)))
        l1m_b = float(pnoise.dbc(np.interp(1e6, offs, Lb_tot)))
        l10m_b = float(pnoise.dbc(np.interp(1e7, offs, Lb_tot)))
        l1m_b_core = float(pnoise.dbc(np.interp(1e6, offs, Lb_core)))
        fom_b_core = -l1m_b_core + 20.0 * math.log10(f0_b / 1e6) - 10.0 * math.log10(lb["p_core_mw"])
        fom_b_tot = -l1m_b + 20.0 * math.log10(f0_b / 1e6) - 10.0 * math.log10(lb["p_core_plus_bias_mw"])
        l_b_pll = 10.0 ** np.interp(np.log10(f_pll), np.log10(offs), np.log10(Lb_tot))
        l_b_pll[f_pll > offs[-1]] = Lb_tot[-1] * (offs[-1] / f_pll[f_pll > offs[-1]]) ** 2
        pll_b = optimize_pll_loop(f_pll, l_b_pll, f0_b, abs(lb["kvco_hz_v"]), cp_seen, T,
                                  bw_targets_mhz=[10.0, 12.0, 15.0, 18.0, 22.0, 25.0], cf_f=0.5e-12)
        cdr_b = cdr_14sigma_5g_ui(f_pll, pll_b["best"]["syn_total"], f0_b)
        best_b = {k: v for k, v in pll_b["best"].items() if k != "syn_total"}
        out["B"][key] = dict(
            f0_hz=f0_b, offsets=offs.tolist(), L_core=Lb_core.tolist(), L_total=Lb_tot.tolist(),
            L_100k_dbc=l100k_b, L_1m_dbc=l1m_b, L_10m_dbc=l10m_b, L_1m_core_only_dbc=l1m_b_core,
            fom_1m_core=fom_b_core, fom_1m_core_bias=fom_b_tot,
            fom_t_1m=fom_b_tot + 20.0 * math.log10(rb["ftr_pct"] / 10.0),
            breakdown_1m={k: float(np.interp(1e6, offs, v) / np.interp(1e6, offs, Lb_tot) * 100.0) for k, v in Lb.items()},
            pll=best_b, pll_sweep=pll_b["sweep"], cdr_5g=cdr_b,
        )

        # ===================== ARCH C (5.0 GHz LC-VCO -> /2 -> 2.5 GHz) =====================
        lc, rc_d, ic = lock["C"][key], rng_data["C"][key], isf["C"][key]
        f_lc = 1.0 / ic["sites"]["se"]["period"]
        f0_c = f_lc / 2.0
        Lc5 = {}
        imp_se = pnoise.Impulse(np.array(ic["sites"]["se"]["x"]), np.array(ic["sites"]["se"]["h"]), ic["sites"]["se"]["period"])
        imp_df = pnoise.Impulse(np.array(ic["sites"]["diff"]["x"]), np.array(ic["sites"]["diff"]["h"]), ic["sites"]["diff"]["period"])
        imp_mn = pnoise.Impulse(np.array(ic["sites"]["mn"]["x"]), np.array(ic["sites"]["mn"]["h"]), ic["sites"]["mn"]["period"])
        imp_mtc = pnoise.Impulse(np.array(ic["sites"]["mt"]["x"]), np.array(ic["sites"]["mt"]["h"]), ic["sites"]["mt"]["period"])

        # 1) Inductor pi-model thermal noise (exact harmonic PPV sum of ngspice .noise + Nyquist 4kT/Rp cross-check!)
        hw_df = np.array(ic["sites"]["diff"]["harm_w"])
        hw_se = np.array(ic["sites"]["se"]["harm_w"])
        ind_f, ind_s = np.array(nz["ind_c"]["f"]), np.array(nz["ind_c"]["s_i"])
        ks_c = np.arange(1, min(len(hw_df), 7))
        ind_coeff = float(np.sum([hw_df[k] * float(np.interp(k * f_lc, ind_f, ind_s)) for k in ks_c]))
        Lc5["ind_thermal"] = (ind_coeff / 2.0) / (2.0 * np.pi * offs) ** 2
        # Exact Nyquist-Johnson 4 k T / Rp_ind check at fundamental k=1
        rp_ind = rc_d["ind_ac"]["rp_ind"]
        q_ind = rc_d["ind_ac"]["q_ind"]
        s_i_rp_4kt = 4.0 * pnoise.K_B * T / rp_ind
        l_ind_4kt_1m = float(pnoise.dbc(pnoise.l_white(s_i_rp_4kt, pnoise.white_coefficient(imp_df), 1e6)))

        # 2) Cross-coupled PMOS (2x, pfet_lvt 64/0.35) & NMOS (2x, nfet_lvt 40/0.15)
        w_cse = spice.Waves(ROOT / ic["sites"]["se"]["raw"])
        pr_cp = [f"@m.xdut.xcore.xmp1.xmos.{PLVT_M}[gm]", f"@m.xdut.xcore.xmp1.xmos.{PLVT_M}[id]"]
        op_cp = one_period_wave(w_cse, "v(vp)", "v(vn)", ic["settle"] - 0.1e-9, pr_cp)
        Lc5["pmos_th"], Lc5["pmos_fl"] = device_cyclostationary_l(
            imp_se, op_cp["x"], op_cp[pr_cp[0]], op_cp[pr_cp[1]], tabs["plvt_035"], 2.0, T, offs, w_scale=64.0 / 32.0)

        w_cmn = spice.Waves(ROOT / ic["sites"]["mn"]["raw"])
        pr_cn = [f"@m.xdut.xcore.xmn1.xmos.{NLVT}[gm]", f"@m.xdut.xcore.xmn1.xmos.{NLVT}[id]"]
        op_cn = one_period_wave(w_cmn, "v(vp)", "v(vn)", ic["settle"] - 0.1e-9, pr_cn)
        Lc5["nmos_th"], Lc5["nmos_fl"] = device_cyclostationary_l(
            imp_mn, op_cn["x"], op_cn[pr_cn[0]], op_cn[pr_cn[1]], tabs["nlvt_015"], 2.0, T, offs, w_scale=40.0 / 24.0)

        # 3) Tail NMOS (1x, nfet_01v8 80/0.5)
        w_cmt = spice.Waves(ROOT / ic["sites"]["mt"]["raw"])
        pr_ct = [f"@m.xdut.xcore.xtail.xmos.{NSVT}[gm]", f"@m.xdut.xcore.xtail.xmos.{NSVT}[id]"]
        op_ct = one_period_wave(w_cmt, "v(vp)", "v(vn)", ic["settle"] - 0.1e-9, pr_ct)
        Lc5["tail_th"], Lc5["tail_fl"] = device_cyclostationary_l(
            imp_mtc, op_ct["x"], op_ct[pr_ct[0]], op_ct[pr_ct[1]], tabs["nsvt_050"], 1.0, T, offs, w_scale=1.0)

        # 4) Varactor rg (2x noisy=1)
        vf_c, vs_c = np.array(nz["var_c"]["f"]), np.array(nz["var_c"]["s_mean"])
        var_coeff_c = float(np.sum([hw_se[k] * float(np.interp(k * f_lc, vf_c, vs_c)) for k in ks_c]))
        Lc5["varactor_rg"] = 2.0 * (var_coeff_c / 2.0) / (2.0 * np.pi * offs) ** 2

        # 5) 4-bit differential MIM bank switches (code ON + (15 - code) OFF)
        bf_c = np.array(nz["bank_c"]["f"])
        bs_tot = lc["code"] * np.array(nz["bank_c"]["s_on"]) + (15 - lc["code"]) * np.array(nz["bank_c"]["s_off"])
        bk_coeff_c = float(np.sum([hw_df[k] * float(np.interp(k * f_lc, bf_c, bs_tot)) for k in ks_c]))
        Lc5["bank_switches"] = (bk_coeff_c / 2.0) / (2.0 * np.pi * offs) ** 2

        Lc5_tot = sum(Lc5.values())
        # Divide-by-2 phase noise scaling (-6.02 dB) + additive CML /2 latch noise floor
        d2_f, d2_v = np.array(nz["div2_c"]["f"]), np.array(nz["div2_c"]["v"])
        s_v_d2 = np.exp(np.interp(np.log(offs), np.log(d2_f), np.log(np.maximum(d2_v ** 2, 1e-35))))
        # Each edge has variance dt^2 = S_v_out / slew^2; 2 transitions/cycle & 2 latches -> L_div2 = 2 * S_v * (pi*f0/slew)^2
        # (more accurately: for sampled edge noise at 2*f0, one-sided SSB phase noise floor = (2*pi*f0)^2 * S_v_white / (2 * slew^2))
        s_v_d2_white = float(np.interp(1e8, d2_f, d2_v ** 2))
        # Integrated broadband voltage noise at latch crossing BW ~ 3 GHz folded by 2*f0 sampling rate = 5 GHz (aliasing ~ 1.2x)
        # Standard Egan/Razavi divider SSB phase noise floor: L_div2(df) = (2*pi*f0)^2 * (S_v_d2(df) * 1.2) / (2 * slew^2)
        L_div2_floor = (2.0 * np.pi * f0_c) ** 2 * (s_v_d2 * 1.2 + s_v_d2_white * 0.5) / (2.0 * max(lc["slew_div2_v_s"], 1e9) ** 2)
        Lc2p5_tot = Lc5_tot / 4.0 + L_div2_floor

        # Analytical Leeson cross-check at 5.0 GHz (and /2 -> 2.5 GHz):
        # P_sig = V_pk_diff^2 / (2 * R_p,ind); typical complementary LC excess noise factor F = 1 + gamma_eff (~2.5)
        v_pk_diff = (lc["tank_swing_mv"] * 1e-3) / 2.0
        p_sig_w = (v_pk_diff ** 2) / (2.0 * rp_ind)
        l5g_leeson_f1 = 10.0 * math.log10((2.0 * pnoise.K_B * T / p_sig_w) * (f_lc / (2.0 * q_ind * 1e6)) ** 2)
        l5g_leeson_f2p5 = l5g_leeson_f1 + 10.0 * math.log10(2.5)
        l2p5g_leeson_f2p5 = l5g_leeson_f2p5 - 6.0206

        l100k_c = float(pnoise.dbc(np.interp(1e5, offs, Lc2p5_tot)))
        l1m_c = float(pnoise.dbc(np.interp(1e6, offs, Lc2p5_tot)))
        l10m_c = float(pnoise.dbc(np.interp(1e7, offs, Lc2p5_tot)))
        l1m_c5g = float(pnoise.dbc(np.interp(1e6, offs, Lc5_tot)))
        fom_c_core = -l1m_c5g + 20.0 * math.log10(f_lc / 1e6) - 10.0 * math.log10(lc["p_core_mw"])
        fom_c_tot = -l1m_c + 20.0 * math.log10(f0_c / 1e6) - 10.0 * math.log10(lc["p_total_mw"])

        l_c_pll = 10.0 ** np.interp(np.log10(f_pll), np.log10(offs), np.log10(Lc2p5_tot))
        l_c_pll[f_pll > offs[-1]] = Lc2p5_tot[-1] * (offs[-1] / f_pll[f_pll > offs[-1]]) ** 2
        # Optimize Arch C PLL across BOTH narrow optimal LC BW (1..6 MHz) AND 10-25 MHz ring-style BW!
        pll_c_opt = optimize_pll_loop(f_pll, l_c_pll, f0_c, abs(lc["kvco_hz_v"]), cp_seen, T,
                                      bw_targets_mhz=[0.8, 1.2, 1.8, 2.5, 3.5, 5.0, 8.0, 10.0], cf_f=0.4e-12)
        pll_c_10m = optimize_pll_loop(f_pll, l_c_pll, f0_c, abs(lc["kvco_hz_v"]), cp_seen, T,
                                      bw_targets_mhz=[10.0, 12.0, 15.0], cf_f=0.4e-12)
        cdr_c_opt = cdr_14sigma_5g_ui(f_pll, pll_c_opt["best"]["syn_total"], f0_c)
        cdr_c_10m = cdr_14sigma_5g_ui(f_pll, pll_c_10m["best"]["syn_total"], f0_c)
        best_c_opt = {k: v for k, v in pll_c_opt["best"].items() if k != "syn_total"}
        best_c_10m = {k: v for k, v in pll_c_10m["best"].items() if k != "syn_total"}
        out["C"][key] = dict(
            f_lc_hz=f_lc, f0_hz=f0_c, offsets=offs.tolist(),
            L_5g=Lc5_tot.tolist(), L_total=Lc2p5_tot.tolist(), L_div2_floor_10m_dbc=float(pnoise.dbc(np.interp(1e7, offs, L_div2_floor))),
            L_5g_1m_dbc=l1m_c5g,
            L_100k_dbc=l100k_c, L_1m_dbc=l1m_c, L_10m_dbc=l10m_c,
            fom_1m_core=fom_c_core, fom_1m_total=fom_c_tot,
            fom_t_1m=fom_c_tot + 20.0 * math.log10(rc_d["ftr_pct"] / 10.0),
            leeson_check=dict(
                q_ind=q_ind, rp_ind_ohm=rp_ind, p_sig_mw=p_sig_w * 1e3,
                l_ind_isf_5g_1m=float(pnoise.dbc(np.interp(1e6, offs, Lc5["ind_thermal"]))),
                l_ind_4kt_5g_1m=l_ind_4kt_1m,
                leeson_5g_f1_1m=l5g_leeson_f1,
                leeson_5g_f2p5_1m=l5g_leeson_f2p5,
                leeson_2p5g_f2p5_1m=l2p5g_leeson_f2p5,
                implied_F_db=l1m_c5g - l5g_leeson_f1,
            ),
            breakdown_1m={k: float(np.interp(1e6, offs, v) / np.interp(1e6, offs, Lc5_tot) * 100.0) for k, v in Lc5.items()},
            pll=best_c_opt, pll_10m=best_c_10m, pll_sweep=pll_c_opt["sweep"],
            cdr_5g=cdr_c_opt, cdr_5g_10m=cdr_c_10m,
        )

        print(f"  [synth] {key:18s} | "
              f"A: L1M={l1m_a:6.1f} FoM={fom_a_tot:5.1f} J={best_a['j_10k_100m_ps']:.2f}ps ({cdr_a['pp_14p07sigma_ui']:.3f}UI) | "
              f"B: L1M={l1m_b:6.1f} FoM={fom_b_tot:5.1f} J={best_b['j_10k_100m_ps']:.2f}ps ({cdr_b['pp_14p07sigma_ui']:.3f}UI) | "
              f"C: L1M={l1m_c:6.1f}(5G:{l1m_c5g:.1f},Leeson:{l2p5g_leeson_f2p5:.1f}) FoM={fom_c_core:5.1f}/{fom_c_tot:5.1f} J={best_c_opt['j_10k_100m_ps']:.2f}ps(@{best_c_opt['ugb_mhz']:.1f}M) [{best_c_10m['j_10k_100m_ps']:.2f}ps@10M] ({cdr_c_opt['pp_14p07sigma_ui']:.3f}UI)",
              flush=True)

    (sdir / "summary.json").write_text(json.dumps(out, indent=2))
    return out


# ---------------------------------------------------------------------------
# Stage 7: 4-Panel Publication Comparison Figure
# ---------------------------------------------------------------------------

def stage_plot(rng_data: dict, lock: dict, psrr: dict, synth: dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.size": 9.2,
        "axes.titlesize": 10.2,
        "axes.titleweight": "bold",
        "axes.labelsize": 9.2,
        "legend.fontsize": 7.6,
        "xtick.labelsize": 8.2,
        "ytick.labelsize": 8.2,
        "axes.grid": True,
        "grid.alpha": 0.28,
        "grid.linestyle": "--",
    })

    fig, axes = plt.subplots(2, 2, figsize=(14.4, 10.0), dpi=180)
    fig.subplots_adjust(left=0.065, right=0.975, top=0.915, bottom=0.075, wspace=0.25, hspace=0.31)
    fig.suptitle(
        "5 Gb/s Stretch-Goal VCO Shootout in SKY130A (2.50 GHz Quadrature, 1.65–1.95 V, 5 PVT×RC Corners)",
        fontsize=12.4, fontweight="bold", y=0.972,
    )

    c_keys = [cfg["key"] for cfg in CORNERS]
    c_lbls = [cfg["short"] for cfg in CORNERS]
    col_a, col_b, col_c, col_r6 = "#1f77b4", "#ff7f0e", "#2ca02c", "#7f7f7f"

    # --- Panel (a): Tuning Range & 2.50 GHz PVT Coverage ---
    ax = axes[0, 0]
    y_base = np.arange(len(c_keys))
    h_off = {"A": 0.25, "B": 0.0, "C": -0.25}
    cols = {"A": col_a, "B": col_b, "C": col_c}
    names = {
        "A": "Arch A: Reg. CMOS Ring (0-bank cont.)",
        "B": "Arch B: Maneatis Sym.-Load Ring (0-bank cont.)",
        "C": "Arch C: 5 GHz LC-VCO + ÷2 (4-bit bank + var.)",
    }
    for arch in ("A", "B", "C"):
        for i, k in enumerate(c_keys):
            d = rng_data[arch][k]
            f0, f1 = d["f_min_hz"] / 1e9, d["f_max_hz"] / 1e9
            y = y_base[i] + h_off[arch]
            ax.barh(y, f1 - f0, left=f0, height=0.22, color=cols[arch], alpha=0.84,
                    edgecolor="white", lw=0.6, label=names[arch] if i == 0 else None)
            ax.text(f1 + 0.06, y, f"{f0:.2f}–{f1:.2f}", va="center", ha="left", fontsize=6.8, color="#222222")
    ax.axvline(2.50, color="#d62728", lw=2.0, ls="--", label="5 Gb/s Target (2.50 GHz)")
    ax.axvline(2.00, color=col_r6, lw=1.3, ls=":", label="Signed-off r6 Baseline (2.00 GHz)")
    ax.set_yticks(y_base)
    ax.set_yticklabels(c_lbls)
    ax.invert_yaxis()
    ax.set_xlim(0.4, 8.4)
    ax.set_xlabel("Output Quadrature Frequency (GHz)")
    ax.set_title("(a) Tuning Range & 2.50 GHz PVT Coverage (All 5/5 Corners)")
    ax.legend(loc="center right", bbox_to_anchor=(0.99, 0.56), fontsize=6.8, framealpha=0.95)

    # --- Panel (b): Free-Running Phase Noise L(df) at TT & Worst Corner vs r6+PTAT ---
    ax = axes[0, 1]
    tt = "tt_v1800_t27:tt"
    worst_k = {}
    for arch in ("A", "B", "C"):
        worst_k[arch] = max(c_keys, key=lambda k: synth[arch][k]["L_1m_dbc"])
    for arch, col, short_nm in (("A", col_a, "Arch A (CMOS Reg)"),
                                ("B", col_b, "Arch B (Maneatis)"),
                                ("C", col_c, "Arch C (5G LC+÷2)")):
        s_tt = synth[arch][tt]
        s_wk = synth[arch][worst_k[arch]]
        fm = np.array(s_tt["offsets"]) / 1e6
        ax.semilogx(fm, 10 * np.log10(np.array(s_tt["L_total"])), color=col, lw=2.1,
                    label=f"{short_nm} TT ({s_tt['L_1m_dbc']:.1f} dBc/Hz @1M)")
        if worst_k[arch] != tt:
            w_sh = next(c["short"] for c in CORNERS if c["key"] == worst_k[arch])
            ax.semilogx(fm, 10 * np.log10(np.array(s_wk["L_total"])), color=col, lw=1.3, ls="--", alpha=0.8,
                        label=f"{short_nm} worst {w_sh} ({s_wk['L_1m_dbc']:.1f})")
    # Signed-off r6+PTAT TT baseline (2.0 GHz -> +1.94 dB scaled to 2.5 GHz noted, plotted native 2.0 GHz)
    r6_tt = synth["r6_ref"][tt]
    ax.semilogx(np.array(r6_tt["offsets"]) / 1e6, 10 * np.log10(np.array(r6_tt["L_core"])),
                color=col_r6, lw=1.7, ls=":", label=f"r6+PTAT 2.0 GHz TT ({r6_tt['L_1m_dbc']:.1f} dBc/Hz)")
    ax.axvline(1.0, color="gray", lw=0.8, ls=":")
    ax.axhline(-110.0, color=col_c, lw=0.9, ls="-.", alpha=0.65)
    ax.text(0.013, -108.5, "LC Target: −110 dBc/Hz @ 1 MHz", color=col_c, fontsize=7.2, fontweight="bold")
    ax.set_xlim(0.01, 100.0)
    ax.set_ylim(-155, -55)
    ax.set_xlabel("Offset Frequency Δf (MHz)")
    ax.set_ylabel("2.5 GHz Output Phase Noise L(Δf) (dBc/Hz)")
    ax.set_title("(b) Free-Running L(Δf) at TT & Worst PVT Corner vs r6+PTAT")
    ax.legend(loc="lower left", fontsize=6.9, framealpha=0.93)

    # --- Panel (c): Projected 5 Gb/s PLL RMS Jitter (ps) & FoM across All 5 Corners ---
    ax = axes[1, 0]
    x_pos = np.arange(len(c_keys))
    w_b = 0.25
    j_a = [synth["A"][k]["pll"]["j_10k_100m_ps"] for k in c_keys]
    j_b = [synth["B"][k]["pll"]["j_10k_100m_ps"] for k in c_keys]
    j_c = [synth["C"][k]["pll"]["j_10k_100m_ps"] for k in c_keys]
    b1 = ax.bar(x_pos - w_b, j_a, width=w_b, color=col_a, label="Arch A: Reg. CMOS Ring (opt. BW)")
    b2 = ax.bar(x_pos,       j_b, width=w_b, color=col_b, label="Arch B: Maneatis Ring (opt. BW)")
    b3 = ax.bar(x_pos + w_b, j_c, width=w_b, color=col_c, label="Arch C: 5G LC+÷2 (opt. BW)")
    for bars in (b1, b2, b3):
        for bar in bars:
            h = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, h + 0.04, f"{h:.2f}",
                    ha="center", va="bottom", fontsize=6.7, fontweight="bold")
    ax.axhline(1.00, color="#d62728", lw=1.6, ls="--", label="Sub-1 ps Stretch Target (1.00 ps)")
    ax.axhline(0.50, color=col_c, lw=1.2, ls=":", label="LC Stretch Target (0.50 ps)")
    ax.axhline(1.91, color=col_r6, lw=1.3, ls="-.", label="Signed-off r6+PTAT TT (1.91 ps @ 2 GHz)")
    ax.set_xticks(x_pos)
    ax.set_xticklabels(c_lbls)
    ymax_j = max(max(j_a), max(j_b), 2.3) * 1.48
    ax.set_ylim(0, ymax_j)
    ax.set_ylabel("Closed-Loop PLL RMS Jitter, 10k–100M (ps)")
    ax.set_title("(c) Projected 5 Gb/s PLL RMS Jitter vs 1.0 ps / 0.5 ps Targets")
    ax.legend(loc="upper left", ncol=1, fontsize=6.5, framealpha=0.94)
    # Compact TT FoM & Power callout box (neatly separated on upper right)
    fom_txt = (
        f"TT 27°C Core / Total FoM(1M) & Power:\n"
        f"• r6+PTAT (2G): {synth['r6_ref'][tt]['fom_1m_core']:.1f} dBc/Hz | {synth['r6_ref'][tt]['p_core_mw']:.1f} mW\n"
        f"• Arch A (2.5G): {synth['A'][tt]['fom_1m_core']:.1f}/{synth['A'][tt]['fom_1m_core_reg']:.1f} | {lock['A'][tt]['p_core_mw']:.1f}/{lock['A'][tt]['p_core_plus_reg_mw']:.1f} mW\n"
        f"• Arch B (2.5G): {synth['B'][tt]['fom_1m_core']:.1f}/{synth['B'][tt]['fom_1m_core_bias']:.1f} | {lock['B'][tt]['p_core_mw']:.1f}/{lock['B'][tt]['p_core_plus_bias_mw']:.1f} mW\n"
        f"• Arch C (2.5G): {synth['C'][tt]['fom_1m_core']:.1f}/{synth['C'][tt]['fom_1m_total']:.1f} | {lock['C'][tt]['p_core_mw']:.1f}+{lock['C'][tt]['p_div2_mw']:.1f} mW"
    )
    ax.text(0.985, 0.975, fom_txt, transform=ax.transAxes, ha="right", va="top", fontsize=6.4,
            bbox=dict(boxstyle="round,pad=0.30", facecolor="#fffdf5", edgecolor="#999999", alpha=0.94))

    # --- Panel (d): Steady-State 2.50 GHz Quadrature Output Waveforms (TT 27°C) ---
    ax = axes[1, 1]
    wa = lock["A"][tt]["wave"]
    wb = lock["B"][tt]["wave"]
    wc = lock["C"][tt]["wave"]
    # Plot vertically stacked (offset cleanly) differential I & Q waveforms (2 cycles = 0.8 ns)
    ax.plot(wa["t_ns"], np.array(wa["core_diff"]) + 3.6, color=col_a, lw=1.8,
            label=f"Arch A Core I ({lock['A'][tt]['core_swing_mv']:.0f} mVpp, Vreg={lock['A'][tt]['vreg']:.2f}V)")
    ax.plot(wa["t_ns"], np.array(wa["buf_q"]) * 0.65 + 3.6, color=col_a, lw=1.2, ls="--", alpha=0.75,
            label="Arch A Buf Q (scaled)")
    ax.plot(wb["t_ns"], np.array(wb["core_diff"]) + 0.0, color=col_b, lw=1.8,
            label=f"Arch B Core I ({lock['B'][tt]['core_swing_mv']:.0f} mVpp, Vbp={lock['B'][tt]['vbp']:.2f}V)")
    ax.plot(wb["t_ns"], np.array(wb["buf_q"]) + 0.0, color=col_b, lw=1.2, ls="--", alpha=0.75,
            label=f"Arch B Buf Q ({lock['B'][tt]['buf_swing_mv']:.0f} mVpp)")
    ax.plot(wc["t_ns"], np.array(wc["iq_i"]) - 3.2, color=col_c, lw=1.9,
            label=f"Arch C ÷2 I ({lock['C'][tt]['iq_swing_mv']:.0f} mVpp)")
    ax.plot(wc["t_ns"], np.array(wc["iq_q"]) - 3.2, color=col_c, lw=1.5, ls="--", alpha=0.85,
            label=f"Arch C ÷2 Q (90° err={lock['C'][tt]['quad_err']['err_deg']:+.2f}°)")
    ax.plot(wc["t_ns"], np.array(wc["tank_diff"]) * 0.45 - 5.5, color="#17becf", lw=1.4,
            label=f"Arch C 5 GHz LC Tank ({lock['C'][tt]['tank_swing_mv']:.0f} mVpp, ×0.45)")
    for y0 in (3.6, 0.0, -3.2, -5.5):
        ax.axhline(y0, color="gray", lw=0.6, alpha=0.45)
    ax.set_xlim(0, 0.80)
    ax.set_ylim(-6.7, 5.8)
    ax.set_xlabel("Time (ns)  [2 Cycles @ 2.50 GHz, T = 400 ps]")
    ax.set_ylabel("Differential Voltage (V, vertically offset)")
    ax.set_title("(d) Steady-State 2.50 GHz I/Q & 5.0 GHz LC Tank Waveforms (TT)")
    ax.legend(loc="upper right", ncol=1, fontsize=6.7, framealpha=0.92)

    FIG_OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_OUT, dpi=180)
    plt.close(fig)
    print(f"[plot] saved {FIG_OUT.relative_to(ROOT)}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default="all",
                    help="comma-separated stages or 'all': range,lock,psrr,isf,noise,synth,plot")
    ap.add_argument("--workers", type=int, default=2, choices=(1, 2))
    a = ap.parse_args()
    assert 1 <= a.workers <= 2, "Strictly max 2 ngspice workers allowed!"
    OUT.mkdir(parents=True, exist_ok=True)

    def load(name):
        p = OUT / name / "summary.json"
        if not p.exists():
            raise FileNotFoundError(f"Missing {p}; run earlier stages first")
        return json.loads(p.read_text())

    valid = ("range", "lock", "psrr", "isf", "noise", "synth", "plot")
    stages = valid if a.stage == "all" else tuple(s.strip() for s in a.stage.split(",") if s.strip())
    for s in stages:
        if s not in valid:
            raise ValueError(f"Unknown stage {s!r}")

    rng_data = lock = psrr = isf = noise = synth = None
    if "range" in stages:
        rng_data = stage_range(a.workers)
    if "lock" in stages:
        rng_data = rng_data or load("stage1_range")
        lock = stage_lock(a.workers, rng_data)
    if "psrr" in stages:
        lock = lock or load("stage2_lock")
        psrr = stage_psrr(a.workers, lock)
    if "isf" in stages:
        lock = lock or load("stage2_lock")
        isf = stage_isf(a.workers, lock)
    if "noise" in stages:
        lock = lock or load("stage2_lock")
        isf = isf or load("stage4_isf")
        noise = stage_noise(a.workers, lock, isf)
    if "synth" in stages:
        rng_data = rng_data or load("stage1_range")
        lock = lock or load("stage2_lock")
        psrr = psrr or load("stage3_psrr")
        isf = isf or load("stage4_isf")
        noise = noise or load("stage5_noise")
        synth = stage_synth(rng_data, lock, psrr, isf, noise)
    if "plot" in stages:
        rng_data = rng_data or load("stage1_range")
        lock = lock or load("stage2_lock")
        psrr = psrr or load("stage3_psrr")
        synth = synth or load("stage6_synth")
        stage_plot(rng_data, lock, psrr, synth)


if __name__ == "__main__":
    main()
