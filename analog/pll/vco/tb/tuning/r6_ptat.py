"""PLL VCO r6 with BIAS v2 PTAT + Constant-Swing Tail-Current Blending.

    uv run python analog/pll/vco/tb/tuning/r6_ptat.py bench [--workers 2]
    uv run python analog/pll/vco/tb/tuning/r6_ptat.py sweep [--cands "p45=47,44;p60=34,58;p75=21,73"] [--workers 2] [--resume C]
    uv run python analog/pll/vco/tb/tuning/r6_ptat.py map --nf-const 34 --nf-ptat 58 [--passive tt,hh,ll] [--workers 2] [--resume C]
    uv run python analog/pll/vco/tb/tuning/r6_ptat.py table --resume C
    uv run python analog/pll/vco/tb/tuning/r6_ptat.py check --resume C --nf-const 34 --nf-ptat 58 [--workers 2]
    uv run python analog/pll/vco/tb/tuning/r6_ptat.py headroom --nf-const 34 --nf-ptat 58 [--workers 2]

Uses 100% real SKY130A devices (`serdes_bias_vco_ptat_core` / `serdes_bias_top_v2_ptat` +
`pll_vco_ring4_r6` + 4 `serdes_cml_buffer` + `rcorner.to_pdk_fixed`), binary raw output,
`skip_output_before`, `t_end` completion checks, and resumable per-corner decks.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import numpy as np
from scipy.interpolate import PchipInterpolator

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition, boundary_first, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

RESULTS = ROOT / "results/analog/pll/vco/r6_ptat"

PRIMS = ROOT / "analog/common/devices/spice/sky130_primitives.spice"
PLVT = ROOT / "analog/common/devices/spice/sky130_pfet_lvt.spice"
BIAS_V2 = ROOT / "analog/bias/spice/bias_v2.spice"
VCO_PTAT = ROOT / "analog/pll/vco/spice/vco_ptat_bias.spice"
CML_DEL = ROOT / "analog/common/cml_buffer/spice/cml_delay_resistive.spice"
CML_BUF = ROOT / "analog/common/cml_buffer/spice/cml_buffer.spice"
CAP5 = ROOT / "analog/pll/vco/spice/cap_bank_5b.spice"
DEL6 = ROOT / "analog/pll/vco/spice/vco_delay_r6.spice"
RING6 = ROOT / "analog/pll/vco/spice/vco_ring4_r6.spice"

NCODE, COARSE, FLOOR, HEAD, TARGET = 32, (0, 15, 31), 0.90, 0.44, 2e9
STOP, START, TSTEP = 14e-9, 8e-9, "4p"
DRIFT = 5e-4

# The 9 chip groups that missed 3-temp common code in baseline r6, with their midpoint test code
FAIL9 = [
    ("ff", 1.65, "ll", 19),
    ("ff", 1.80, "ll", 19),
    ("fs", 1.65, "ll", 12),
    ("fs", 1.80, "ll", 11),
    ("fs", 1.95, "ll", 11),
    ("sf", 1.65, "ll", 26),
    ("tt", 1.65, "ll", 18),
    ("tt", 1.65, "tt", 9),
    ("ff", 1.65, "tt", 10),
]

STRESS = [
    # (label, rc, cond_tag, code, vctrl_mode)
    ("slow_end", "hh", "fs_v1650_t85", 0, "top"),
    ("fast_end", "ll", "sf_v1650_t-40", 31, "floor"),
    ("hot_sf_hh", "hh", "sf_v1650_t85", 16, "mid"),
    ("hot_ss_hh", "hh", "ss_v1650_t85", 4, "mid"),
    ("hot_fs_hh", "hh", "fs_v1650_t85", 4, "mid"),
    ("hot_ff_hh", "hh", "ff_v1650_t85", 10, "mid"),
    ("cold_sf_hh", "hh", "sf_v1650_t-40", 16, "mid"),
    ("cold_ss_hh", "hh", "ss_v1650_t-40", 4, "mid"),
]

UNSETTLED: list[tuple[str, float]] = []


def top(c: Condition) -> float:
    return round(c.supply - HEAD, 3)


def vgrid(c: Condition) -> list[float]:
    return [round(float(v), 3) for v in np.linspace(FLOOR, top(c), 4)]


def case_name(c: Condition, code: int, v: float) -> str:
    return f"{c.tag}_c{code}_v{round(v * 1000)}.raw"


def base_circuit(
    process: str,
    rc: str,
    nf_const: int,
    nf_ptat: int,
    snap_dir: Path,
    ring_params: str = "",
    use_full_top: bool = False,
    for_op: bool = False,
) -> str:
    lib = spice.corner_values(Condition(process, 1.8, 27))["MODEL_LIBRARY"]
    rp = (" " + ring_params) if ring_params else ""
    if use_full_top:
        bias_inst = [
            "Vg4 g4 0 0", "Eg3 g3 0 vdd 0 1", "Eg2 g2 0 vdd 0 1", "Eg1 g1 0 vdd 0 1", "Eg0 g0 0 vdd 0 1",
            "Vc3 c3 0 0", "Ec2 c2 0 vdd 0 1", "Ec1 c1 0 vdd 0 1", "Ec0 c0 0 vdd 0 1",
            "Ven en_pbuf 0 0",
            f"Xbias vbg vcm pref icml icml_vco ictle icp ild0 ild1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd 0 serdes_bias_top_v2_ptat nf_const={nf_const} nf_ptat={nf_ptat}",
            "Cvcm vcm 0 5p",
            "Xdcml_tx icml 0 serdes_bias_cml_v2",
            "Vmvco icml_vco vbias 0",
            "Xdcml_vco vbias 0 serdes_bias_cml_v2",
            "Xdctle ictle 0 serdes_bias_ctle_v2",
            "Xdcp icp vbp vdd 0 serdes_bias_cp_v2",
            "Vld0 ild0 0 0.7", "Vld1 ild1 0 0.7",
            ".nodeset v(vbg)=1.234 v(vcm)=1.05 v(xbias.xref.s)=1.234 v(xbias.xref.vg)=1.1 v(xbias.vgi)=1.1 v(xbias.xref.ta)=1.05 v(xbias.xref.tb)=1.05",
        ]
    elif nf_ptat == 0:
        bias_inst = [
            "Vg4 g4 0 0", "Eg3 g3 0 vdd 0 1", "Eg2 g2 0 vdd 0 1", "Eg1 g1 0 vdd 0 1", "Eg0 g0 0 vdd 0 1",
            "Xref vbg i0 i1 i2 i3 vgi g4 g3 g2 g1 g0 vdd 0 serdes_bias_ref_v2",
            "Xd0 i0 i0 0 0 serdes_nfet w=4 l=4 nf=2",
            "Xd1 i1 i1 0 0 serdes_nfet w=4 l=4 nf=2",
            "Xd2 i2 i2 0 0 serdes_nfet w=4 l=4 nf=2",
            "Xd3 i3 i3 0 0 serdes_nfet w=4 l=4 nf=2",
            f"Xpc icml_vco vgi vdd serdes_bias_pcopy_v2 n={nf_const}",
            "Vmvco icml_vco vbias 0",
            "Xdcml_vco vbias 0 serdes_bias_cml_v2",
            ".nodeset v(vbg)=1.234 v(xref.s)=1.234 v(xref.vg)=1.1 v(vgi)=1.1 v(xref.ta)=1.05 v(xref.tb)=1.05",
        ]
    else:
        bias_inst = [
            "Vg4 g4 0 0", "Eg3 g3 0 vdd 0 1", "Eg2 g2 0 vdd 0 1", "Eg1 g1 0 vdd 0 1", "Eg0 g0 0 vdd 0 1",
            f"Xbias vbias vbg g4 g3 g2 g1 g0 vdd 0 serdes_bias_vco_ptat_core nf_const={nf_const} nf_ptat={nf_ptat}",
            ".nodeset v(vbg)=1.234 v(xbias.xref.s)=1.234 v(xbias.xref.vg)=1.1 v(xbias.vgi)=1.1 v(xbias.xref.ta)=1.05 v(xbias.xref.tb)=1.05",
        ]

    lines = [
        f"* PLL VCO r6 + BIAS v2 PTAT blend ({process}/{rc}, nf_const={nf_const}, nf_ptat={nf_ptat})",
        f'.lib "{lib}" {process}',
        f'.include "{PRIMS}"',
        f'.include "{PLVT}"',
        f'.include "{BIAS_V2}"',
        f'.include "{VCO_PTAT}"',
        f'.include "{CML_DEL}"',
        f'.include "{CML_BUF}"',
        f'.include "{CAP5}"',
        f'.include "{DEL6}"',
        f'.include "{RING6}"',
        "Vdd vdd 0 1.8",
        *bias_inst,
        "Vctrl ctrl 0 1.15",
        "Vb0 cfg0 0 0", "Vb1 cfg1 0 0", "Vb2 cfg2 0 0", "Vb3 cfg3 0 0", "Vb4 cfg4 0 0",
        f"Xvco v0p v0n v1p v1n v2p v2n v3p v3n ctrl cfg0 cfg1 cfg2 cfg3 cfg4 vbias vdd 0 pll_vco_ring4_r6{rp}",
        "Xbuf0 v0p v0n b0p b0n vbias vdd 0 serdes_cml_buffer",
        "Xbuf1 v1p v1n b1p b1n vbias vdd 0 serdes_cml_buffer",
        "Xbuf2 v2p v2n b2p b2n vbias vdd 0 serdes_cml_buffer",
        "Xbuf3 v3p v3n b3p b3n vbias vdd 0 serdes_cml_buffer",
        "Cb0p b0p 0 30f", "Cb0n b0n 0 30f", "Cb1p b1p 0 30f", "Cb1n b1n 0 30f",
        "Cb2p b2p 0 30f", "Cb2n b2n 0 30f", "Cb3p b3p 0 30f", "Cb3n b3n 0 30f",
        "Ikick v0p v0n PWL(0 1u 20p 1u 21p 0)",
        ".options reltol=1e-4 abstol=1p vntol=1u klu",
    ]
    if not for_op:
        lines.append(".save v(v0p) v(v0n) v(xvco.x0.tail) v(vbias) i(Vdd)")
    snap_dir.mkdir(parents=True, exist_ok=True)
    text = rcorner.to_pdk_fixed("\n".join(lines) + "\n", snap_dir)
    return bias.section(text, process, rc)


def tran_deck(
    process: str,
    rc: str,
    points: list[tuple[Condition, int, float]],
    nf_const: int,
    nf_ptat: int,
    snap_dir: Path,
    *,
    tstep: str = TSTEP,
    stop: float = STOP,
    start: float = START,
    ring_params: str = "",
    use_full_top: bool = False,
) -> str:
    head = base_circuit(process, rc, nf_const, nf_ptat, snap_dir, ring_params=ring_params, use_full_top=use_full_top)
    ctrl = [".control", "set num_threads=1", "set filetype=binary"]
    for c, code, v in points:
        ctrl += [f"option temp={c.temp}", f"alter Vdd dc={c.supply}"]
        ctrl += [f"alter Vb{k} dc={c.supply if (code >> k) & 1 else 0}" for k in range(5)]
        ctrl += [
            f"alter Vctrl dc={v}",
            f"tran {tstep} {stop:.4e} {start:.4e}",
            f"write {case_name(c, code, v)} v(v0p) v(v0n) v(xvco.x0.tail) v(vbias) i(Vdd)",
            "destroy all",
        ]
    ctrl += ["quit", ".endc", ".end", ""]
    return head + "\n".join(ctrl)


def jobs_for(
    vc: Path,
    todo: list[tuple[str, Condition, int, float]],
    nf_const: int,
    nf_ptat: int,
    *,
    tstep: str = TSTEP,
    stop: float = STOP,
    start: float = START,
    ring_params: str = "",
):
    groups: dict[tuple[str, str], list[tuple[Condition, int, float]]] = {}
    for rc, c, code, v in todo:
        if spice.case_output(vc, f"{c.process}_{rc}", case_name(c, code, v), stop) is None:
            groups.setdefault((c.process, rc), []).append((c, code, v))
    out = []
    for (p, rc), pts in groups.items():
        text = tran_deck(
            p, rc, pts, nf_const, nf_ptat, vc / "snap" / f"{p}_{rc}",
            tstep=tstep, stop=stop, start=start, ring_params=ring_params,
        )
        out.append((
            text,
            spice.next_run_dir(vc, f"{p}_{rc}"),
            dict(
                timeout_s=90 * len(pts) + 900,
                meta=dict(process=p, passive=rc, points=len(pts), nf_const=nf_const, nf_ptat=nf_ptat, tstep=tstep, stop=stop),
            ),
        ))
    return out


def run_jobs(jobs, workers: int) -> None:
    if not jobs:
        print("0 decks to run (all cached)", flush=True)
        return
    print(f"{len(jobs)} decks, {sum(j[2]['meta']['points'] for j in jobs)} points (workers={workers})", flush=True)
    for ex in spice.run_many(jobs, workers=workers, smoke=False):
        if not ex.ok:
            print(f"deck {ex.run_dir}: {ex.log_failures[:3]}", flush=True)


def read_wave(camp: Path, rc: str, c: Condition, code: int, v: float, stop: float = STOP, start: float = START):
    p = spice.case_output(camp, f"{c.process}_{rc}", case_name(c, code, v), stop)
    if p is None:
        return None
    w = spice.Waves(p)
    y = w["v(v0p)"] - w["v(v0n)"]
    sel = w.t >= max(start, stop - 5e-9)
    e, s = crossings(w.t[sel], y[sel])
    r = e[s > 0]
    if len(r) < 6:
        sel = w.t >= start
        e, s = crossings(w.t[sel], y[sel])
        r = e[s > 0]
        if len(r) < 4:
            return None
    h = len(r) // 2
    f1, f2 = h / (r[h] - r[0]), (len(r) - 1 - h) / (r[-1] - r[h])
    if abs(f2 / f1 - 1) > DRIFT:
        UNSETTLED.append((f"{c.tag}:{rc} code {code} {v} V", f2 / f1 - 1))
    freq = float((len(r) - 1) / (r[-1] - r[0]))
    swing = float(np.ptp(y[sel]))
    idd = -float(np.mean(w["i(vdd)"][sel])) if "i(vdd)" in w.names else float("nan")
    vtail = float(np.mean(w["v(xvco.x0.tail)"][sel])) if "v(xvco.x0.tail)" in w.names else float("nan")
    vbias = float(np.mean(w["v(vbias)"][sel])) if "v(vbias)" in w.names else float("nan")
    return dict(f=freq, swing=swing, idd=idd, vtail=vtail, vbias=vbias)


def cmd_bench(args, camp: Path) -> None:
    """Fast accuracy & speed benchmark: core vs full top + 4p/14n vs 5p/12n vs 6p/11n."""
    c_tt = Condition("tt", 1.8, 27)
    c_hot = Condition("fs", 1.65, 85)
    pts_tt = [(c_tt, 9, 1.15)]
    pts_hot = [(c_hot, 0, 1.21)]
    jobs = [
        (tran_deck("tt", "tt", pts_tt, 34, 58, camp / "s1", tstep="4p", stop=14e-9, start=8e-9, use_full_top=False),
         camp / "core_4p_14n_tt", dict(timeout_s=300, meta=dict(points=1, label="core_4p_14n_tt"))),
        (tran_deck("tt", "tt", pts_tt, 34, 58, camp / "s2", tstep="4p", stop=14e-9, start=8e-9, use_full_top=True),
         camp / "top_4p_14n_tt", dict(timeout_s=300, meta=dict(points=1, label="top_4p_14n_tt"))),
        (tran_deck("tt", "tt", pts_tt, 34, 58, camp / "s3", tstep="5p", stop=12e-9, start=7e-9, use_full_top=False),
         camp / "core_5p_12n_tt", dict(timeout_s=300, meta=dict(points=1, label="core_5p_12n_tt"))),
        (tran_deck("tt", "tt", pts_tt, 34, 58, camp / "s4", tstep="6p", stop=11e-9, start=6e-9, use_full_top=False),
         camp / "core_6p_11n_tt", dict(timeout_s=300, meta=dict(points=1, label="core_6p_11n_tt"))),
        (tran_deck("fs", "hh", pts_hot, 34, 58, camp / "s5", tstep="4p", stop=14e-9, start=8e-9, use_full_top=False),
         camp / "core_4p_14n_fs", dict(timeout_s=300, meta=dict(points=1, label="core_4p_14n_fs"))),
        (tran_deck("fs", "hh", pts_hot, 34, 58, camp / "s6", tstep="6p", stop=11e-9, start=6e-9, use_full_top=False),
         camp / "core_6p_11n_fs", dict(timeout_s=300, meta=dict(points=1, label="core_6p_11n_fs"))),
    ]
    res = list(spice.run_many(jobs, workers=args.workers, smoke=False))
    print("\n=== BENCHMARK: core vs full top & timestep/stop ===", flush=True)
    for ex, (c, code, v, stop, start, lab) in zip(
        res,
        [
            (c_tt, 9, 1.15, 14e-9, 8e-9, "core 4p/14n TT"),
            (c_tt, 9, 1.15, 14e-9, 8e-9, "top  4p/14n TT"),
            (c_tt, 9, 1.15, 12e-9, 7e-9, "core 5p/12n TT"),
            (c_tt, 9, 1.15, 11e-9, 6e-9, "core 6p/11n TT"),
            (c_hot, 0, 1.21, 14e-9, 8e-9, "core 4p/14n FS"),
            (c_hot, 0, 1.21, 11e-9, 6e-9, "core 6p/11n FS"),
        ],
    ):
        raw = ex.run_dir / case_name(c, code, v)
        if not raw.exists():
            print(f"  {lab:16s}: FAILED ({ex.log_failures[:2]})")
            continue
        w = spice.Waves(raw)
        y = w["v(v0p)"] - w["v(v0n)"]
        sel = w.t >= stop - 5e-9
        e, s = crossings(w.t[sel], y[sel])
        r = e[s > 0]
        f = (len(r) - 1) / (r[-1] - r[0])
        sw = float(np.ptp(y[sel])) * 1e3
        vb = float(np.mean(w["v(vbias)"][sel]))
        vt = float(np.mean(w["v(xvco.x0.tail)"][sel]))
        idd = -float(np.mean(w["i(vdd)"][sel])) * 1e3
        print(f"  {lab:16s}: {ex.elapsed_s:5.1f}s | f={f/1e9:.5f} GHz | sw={sw:5.1f} mVpp | Vb={vb:.4f}V | Vt={vt:.4f}V | Idd={idd:.3f} mA")


def cmd_headroom(args, camp: Path) -> None:
    """Fast 135-condition DC OP sweep checking Vbg, I_cml_vco, Vtail, Vds, Vdsat, headroom, and core-vs-top match."""
    jobs = []
    for rc in args.passive.split(","):
        for proc in ("tt", "ss", "ff", "sf", "fs"):
            head = base_circuit(proc, rc, args.nf_const, args.nf_ptat, camp / "snap" / f"{proc}_{rc}", use_full_top=args.full_top, for_op=True)
            # Measure bias current via Vmvco if full_top or nf_ptat==0, else sum Xbias.Xdcml
            ctrl = [".control", "set num_threads=1"]
            for vdd in (1.65, 1.8, 1.95):
                for temp in (-40, 27, 85):
                    c = Condition(proc, vdd, temp)
                    vctrl = round((FLOOR + top(c)) / 2, 3)
                    ctrl += [
                        f"option temp={temp}",
                        f"alter Vdd dc={vdd}",
                        f"alter Vctrl dc={vctrl}",
                        "op",
                        "let vd = @m.xvco.x0.xtail.msky130_fd_pr__nfet_01v8[vds]",
                        "let vdsat = @m.xvco.x0.xtail.msky130_fd_pr__nfet_01v8[vdsat]",
                        "let id_t = @m.xvco.x0.xtail.msky130_fd_pr__nfet_01v8[id]",
                        "let vth_t = @m.xvco.x0.xtail.msky130_fd_pr__nfet_01v8[vth]",
                        "let id_d = @m.xbias.xdcml.xd.xmos.msky130_fd_pr__nfet_01v8[id]" if (not args.full_top and args.nf_ptat > 0)
                        else "let id_d = @m.xdcml_vco.xd.xmos.msky130_fd_pr__nfet_01v8[id]",
                        f'echo "OPROW {proc} {rc} {vdd} {temp} " $&v(vbg) $&v(vbias) $&id_d $&id_t $&vd $&vdsat $&vth_t $&i(Vdd)',
                        "destroy all",
                    ]
            ctrl += ["quit", ".endc", ".end", ""]
            jobs.append((head + "\n".join(ctrl), spice.next_run_dir(camp, f"op_{proc}_{rc}"), dict(timeout_s=300, meta=dict(points=9))))

    res = list(spice.run_many(jobs, workers=args.workers, smoke=False))
    rows = {}
    for ex in res:
        if ex.exit_code != 0:
            print(f"OP deck {ex.run_dir} exited {ex.exit_code}: {ex.log_failures[:2]}", flush=True)
            continue
        for line in (ex.run_dir / "simulator.log").read_text().splitlines():
            if line.startswith("OPROW "):
                parts = line.split()
                proc, rc, vdd, temp = parts[1], parts[2], float(parts[3]), int(float(parts[4]))
                vbg, vbias, id_d, id_t, vd, vdsat, vth, ivdd = [float(x) for x in parts[5:]]
                key = f"{proc}_v{round(vdd*1000)}_t{temp}:{rc}"
                rows[key] = dict(
                    vbg=vbg, vbias=vbias, icml_uA=id_d * 1e6, itail_mA=id_t * 1e3,
                    vds=vd, vdsat=vdsat, headroom_mV=(vd - vdsat) * 1e3, vth=vth,
                    idd_mA=-ivdd * 1e3, power_mW=-ivdd * vdd * 1e3,
                )
    print(f"\n=== DC OP HEADROOM & BIAS ({len(rows)}/135 corners, nf_const={args.nf_const}, nf_ptat={args.nf_ptat}, full_top={args.full_top}) ===")
    if rows:
        w_hr = sorted(rows.items(), key=lambda kv: kv[1]["headroom_mV"])[:6]
        print("Worst tail headroom (Vds - Vdsat):")
        for k, r in w_hr:
            print(f"  {k:20s}: Vds={r['vds']:.3f}V Vdsat={r['vdsat']:.3f}V headroom={r['headroom_mV']:+.1f}mV | Icml={r['icml_uA']:.1f}uA Itail={r['itail_mA']:.3f}mA P={r['power_mW']:.2f}mW")
        tt27 = rows.get("tt_v1800_t27:tt")
        ttm40 = rows.get("tt_v1800_t-40:tt")
        tt85 = rows.get("tt_v1800_t85:tt")
        if tt27 and ttm40 and tt85:
            print(f"TT 1.8V: -40C={ttm40['icml_uA']:.2f}uA ({ttm40['itail_mA']:.3f}mA/stg), 27C={tt27['icml_uA']:.2f}uA ({tt27['itail_mA']:.3f}mA/stg), 85C={tt85['icml_uA']:.2f}uA ({tt85['itail_mA']:.3f}mA/stg) | 85/-40={tt85['icml_uA']/ttm40['icml_uA']:.3f}")
            print(f"TT 1.8V VCO+4buf+bias power: -40C={ttm40['power_mW']:.2f}mW, 27C={tt27['power_mW']:.2f}mW, 85C={tt85['power_mW']:.2f}mW")
    (camp / "headroom.json").write_text(json.dumps(dict(nf_const=args.nf_const, nf_ptat=args.nf_ptat, full_top=args.full_top, rows=rows), indent=1))


def cmd_sweep(args, camp: Path) -> None:
    """Stage 1 fast blend-ratio sweep on 9 failing groups + slow/fast ends + hot/cold swing stress."""
    cands = {}
    for item in args.cands.split(";"):
        name, pair = item.split("=", 1)
        nc, np_ = [int(x) for x in pair.split(",")]
        cands[name.strip()] = (nc, np_)

    todo = []
    for p, vdd, rc, code in FAIL9:
        for temp in (-40, 85):
            c = Condition(p, vdd, temp)
            todo.append((rc, c, code, FLOOR))
            todo.append((rc, c, code, top(c)))
    for lab, rc, ctag, code, vmode in STRESS:
        c = Condition.parse(ctag)
        v = top(c) if vmode == "top" else FLOOR if vmode == "floor" else round((FLOOR + top(c)) / 2, 3)
        todo.append((rc, c, code, v))
    # Deduplicate
    todo = list(dict.fromkeys(todo))

    jobs = []
    for name, (nc, np_) in cands.items():
        jobs += jobs_for(camp / name, todo, nc, np_, tstep=args.tstep, stop=args.stop, start=args.start)
    run_jobs(jobs, args.workers)

    summary = {}
    print("\n=== STAGE 1 BLEND-RATIO SWEEP SUMMARY ===")
    for name, (nc, np_) in cands.items():
        vc = camp / name
        print(f"\n--- Candidate {name} (nf_const={nc}, nf_ptat={np_}) ---")
        fail_pass = 0
        min_edge_mv = 999.0
        g_rows = {}
        for p, vdd, rc, code in FAIL9:
            c_lo = Condition(p, vdd, -40)
            c_hi = Condition(p, vdd, 85)
            m_lo0 = read_wave(vc, rc, c_lo, code, FLOOR, args.stop, args.start)
            m_lo1 = read_wave(vc, rc, c_lo, code, top(c_lo), args.stop, args.start)
            m_hi0 = read_wave(vc, rc, c_hi, code, FLOOR, args.stop, args.start)
            m_hi1 = read_wave(vc, rc, c_hi, code, top(c_hi), args.stop, args.start)
            if not all((m_lo0, m_lo1, m_hi0, m_hi1)):
                print(f"  {p}_v{round(vdd*1000)}:{rc} c={code:2d}: MISSING")
                continue
            ok_lo = m_lo0["f"] <= TARGET <= m_lo1["f"]
            ok_hi = m_hi0["f"] <= TARGET <= m_hi1["f"]
            v_lo = float(np.interp(TARGET, [m_lo0["f"], m_lo1["f"]], [FLOOR, top(c_lo)])) if ok_lo else float("nan")
            v_hi = float(np.interp(TARGET, [m_hi0["f"], m_hi1["f"]], [FLOOR, top(c_hi)])) if ok_hi else float("nan")
            ok = ok_lo and ok_hi
            edge = min(v_lo - FLOOR, top(c_lo) - v_lo, v_hi - FLOOR, top(c_hi) - v_hi) * 1e3 if ok else -999.0
            if ok:
                fail_pass += 1
                min_edge_mv = min(min_edge_mv, edge)
            # Estimate shift in % at mid-Vctrl
            df_pct = ((m_hi0["f"] + m_hi1["f"]) / (m_lo0["f"] + m_lo1["f"]) - 1) * 100
            g_rows[f"{p}_v{round(vdd*1000)}:{rc}"] = dict(
                code=code, ok=ok, v_m40=v_lo, v_85=v_hi, edge_mV=edge, df_pct=df_pct,
                f_m40=[m_lo0["f"]/1e9, m_lo1["f"]/1e9], f_85=[m_hi0["f"]/1e9, m_hi1["f"]/1e9],
                sw_m40=min(m_lo0["swing"], m_lo1["swing"])*1e3, sw_85=min(m_hi0["swing"], m_hi1["swing"])*1e3,
            )
            st = "PASS" if ok else "MISS"
            print(f"  {p}_v{round(vdd*1000)}:{rc:2s} c={code:2d} [{st}] | -40C:[{m_lo0['f']/1e9:.3f},{m_lo1['f']/1e9:.3f}] V={v_lo:.3f} | 85C:[{m_hi0['f']/1e9:.3f},{m_hi1['f']/1e9:.3f}] V={v_hi:.3f} | edge={edge:5.1f}mV df={df_pct:+.1f}% sw(-40/85)={min(m_lo0['swing'],m_lo1['swing'])*1e3:.0f}/{min(m_hi0['swing'],m_hi1['swing'])*1e3:.0f}mV")

        s_rows = {}
        for lab, rc, ctag, code, vmode in STRESS:
            c = Condition.parse(ctag)
            v = top(c) if vmode == "top" else FLOOR if vmode == "floor" else round((FLOOR + top(c)) / 2, 3)
            m = read_wave(vc, rc, c, code, v, args.stop, args.start)
            if not m:
                print(f"  STRESS {lab:12s}: MISSING")
                continue
            extra = ""
            if lab == "slow_end":
                extra = f" margin={(m['f']/TARGET - 1)*100:+.1f}%"
            elif lab == "fast_end":
                extra = f" margin={(1 - m['f']/TARGET)*100:+.1f}%"
            s_rows[lab] = dict(cond=f"{ctag}:{rc}", code=code, v=v, f_ghz=m["f"]/1e9, swing_mV=m["swing"]*1e3, idd_mA=m["idd"]*1e3, vtail=m["vtail"])
            print(f"  STRESS {lab:12s} ({ctag}:{rc} c={code:2d} V={v:.2f}): f={m['f']/1e9:.4f}GHz{extra} sw={m['swing']*1e3:.0f}mVpp Idd={m['idd']*1e3:.2f}mA Vt={m['vtail']:.3f}V")

        print(f"  >>> {name}: {fail_pass}/9 FAIL9 groups locked at single code (min edge={min_edge_mv:.1f} mV)")
        summary[name] = dict(nf_const=nc, nf_ptat=np_, fail9_pass=fail_pass, min_edge_mV=min_edge_mv, fail9=g_rows, stress=s_rows)
    (camp / "sweep.json").write_text(json.dumps(summary, indent=1))


def build_model(camp: Path, rc: str, c: Condition, stop: float = STOP, start: float = START):
    vs = vgrid(c)
    pts = [[read_wave(camp, rc, c, k, v, stop, start) for v in vs] for k in COARSE]
    if any(x is None for row in pts for x in row):
        return None
    inv = np.array([[1 / x["f"] for x in row] for row in pts])
    fit = [np.polyfit(COARSE, inv[:, j], 2) for j in range(len(vs))]
    curves = [PchipInterpolator(vs, [1 / np.polyval(fit[j], n) for j in range(len(vs))]) for n in range(NCODE)]
    return dict(
        vs=vs,
        curves=curves,
        swing=[[x["swing"] for x in row] for row in pts],
        idd=[[x["idd"] for x in row] for row in pts],
        vtail=[[x["vtail"] for x in row] for row in pts],
    )


def find_lock(m, c: Condition) -> dict[int, float]:
    out = {}
    grid = np.linspace(FLOOR, top(c), 400)
    for n, cv in enumerate(m["curves"]):
        f = cv(grid)
        if f.min() <= TARGET <= f.max():
            out[n] = float(np.interp(TARGET, f, grid))
    return out


def cmd_table(args, camp: Path) -> None:
    conds = grid45()
    rows, chips, miss = {}, {}, 0
    for rc in args.passive.split(","):
        for c in conds:
            m = build_model(camp, rc, c, args.stop, args.start)
            if m is None:
                miss += 1
                continue
            lk = find_lock(m, c)
            f0, f31 = float(m["curves"][0](top(c))), float(m["curves"][NCODE - 1](FLOOR))
            ks = sorted(lk)
            step = float(np.median(np.abs(np.diff([lk[k] for k in ks])))) if len(ks) > 1 else float("nan")
            mid = (FLOOR + top(c)) / 2
            best = min(ks, key=lambda k: abs(lk[k] - mid)) if ks else None
            kv = float(m["curves"][best].derivative()(lk[best])) if ks else float("nan")
            rows[f"{c.tag}:{rc}"] = dict(
                codes=ks,
                v={str(k): lk[k] for k in ks},
                slow_margin=f0 / TARGET - 1,
                fast_margin=1 - f31 / TARGET,
                lsb_v=step,
                window_lsb=(top(c) - FLOOR) / step if step == step else float("nan"),
                best=best,
                kvco=kv,
                swing_min=float(np.min(m["swing"])),
                swing_max=float(np.max(m["swing"])),
                idd_mean_mA=float(np.nanmean(m["idd"])) * 1e3,
                power_mW=float(np.nanmean(m["idd"])) * c.supply * 1e3,
                vtail_min=float(np.nanmin(m["vtail"])),
            )
            chips.setdefault((c.process, c.supply, rc), {})[c.temp] = lk
    if not rows:
        print("no complete condition")
        return
    print(f"{len(rows)} conditions with a model, {miss} missing")
    for key, lab in (("slow_margin", "slow end (code 0 at window top above 2 GHz)"),
                     ("fast_margin", "fast end (code 31 at window floor below 2 GHz)")):
        w = sorted(rows.items(), key=lambda kv: kv[1][key])[:5]
        print(f"  {lab}: " + ", ".join(f"{k} {r[key] * 100:+.1f}%" for k, r in w))
    n = np.array([len(r["codes"]) for r in rows.values()])
    wl = np.array([r["window_lsb"] for r in rows.values()])
    kv = np.array([r["kvco"] for r in rows.values()])
    print(f"  codes with 2 GHz inside the window: min {n.min()}, median {int(np.median(n))}, max {n.max()}; conditions with < 2: {int((n < 2).sum())}, < 3: {int((n < 3).sum())}")
    print(f"  window / LSB step: min {np.nanmin(wl):.2f}, median {np.nanmedian(wl):.2f};  Kvco at centred code {np.nanmin(kv) / 1e6:.0f} .. {np.nanmax(kv) / 1e6:.0f} MHz/V")
    print(f"  swing over simulated points {min(r['swing_min'] for r in rows.values()) * 1e3:.0f} .. {max(r['swing_max'] for r in rows.values()) * 1e3:.0f} mVpp")
    w_sw = sorted(rows.items(), key=lambda kv: kv[1]["swing_min"])[:5]
    print("  lowest swing: " + ", ".join(f"{k} {r['swing_min'] * 1e3:.0f}mV" for k, r in w_sw))

    frozen, bad, drifts = {}, [], []
    for (p, v, rc), t in sorted(chips.items()):
        if len(t) < 3:
            continue
        common = set.intersection(*(set(x) for x in t.values()))
        tp = v - HEAD
        mar = {k: min(min(x[k] - FLOOR, tp - x[k]) for x in t.values()) for k in common}
        best_c = max(mar, key=mar.get) if mar else None
        b_m40 = rows[f"{p}_v{round(v*1000)}_t-40:{rc}"]["best"]
        b_85 = rows[f"{p}_v{round(v*1000)}_t85:{rc}"]["best"]
        dr = (b_m40 - b_85) if (b_m40 is not None and b_85 is not None) else None
        if dr is not None:
            drifts.append(dr)
        frozen[f"{p}_v{round(v * 1000)}:{rc}"] = dict(
            codes=sorted(common),
            best_common=best_c,
            best_margin_v=mar[best_c] if best_c is not None else None,
            drift_m40_to_85=dr,
        )
        if not common:
            bad.append(f"{p}_v{round(v * 1000)}:{rc}")
    if frozen:
        bm = [x["best_margin_v"] for x in frozen.values() if x["best_margin_v"] is not None]
        print(f"  chips (MOS, supply, passive) with one code for -40 .. 85 C: {len(frozen) - len(bad)} of {len(frozen)}; best frozen edge margin min {min(bm) * 1e3:.0f} mV (median {np.median(bm)*1e3:.0f} mV)" + (f"; none: {bad}" if bad else ""))
        if drifts:
            print(f"  code drift (best_-40 - best_85): min {min(drifts):+d}, median {np.median(drifts):+.1f}, max {max(drifts):+d}, max|drift| {max(abs(x) for x in drifts)}")
    (camp / "table.json").write_text(json.dumps(dict(nf_const=args.nf_const, nf_ptat=args.nf_ptat, rows=rows, frozen=frozen), indent=1))


def cmd_check(args, camp: Path) -> None:
    """Verify model accuracy AND directly simulate closed-code lock across -40/27/85C for all 9 previously failing groups + edge corners."""
    tbl = json.loads((camp / "table.json").read_text())
    rows, frozen = tbl["rows"], tbl["frozen"]
    todo = []
    want_fail9 = []
    for p, vdd, rc, _ in FAIL9:
        gk = f"{p}_v{round(vdd*1000)}:{rc}"
        finfo = frozen.get(gk, {})
        bc = finfo.get("best_common")
        if bc is None:
            continue
        for temp in (-40, 27, 85):
            rk = f"{p}_v{round(vdd*1000)}_t{temp}:{rc}"
            v = round(rows[rk]["v"][str(bc)], 3)
            c = Condition(p, vdd, temp)
            todo.append((rc, c, bc, v))
            want_fail9.append((gk, rk, c, rc, bc, v))

    # Plus 6 worst slow/fast/win_lsb corners
    pick = sorted(rows, key=lambda k: min(rows[k]["slow_margin"], rows[k]["fast_margin"]))[:6]
    want_extra = []
    for key in pick:
        if rows[key]["best"] is None:
            continue
        cond, rc = key.split(":")
        c = Condition.parse(cond)
        k = rows[key]["best"]
        v = round(rows[key]["v"][str(k)], 3)
        todo.append((rc, c, k, v))
        want_extra.append((key, c, rc, k, v))

    todo = list(dict.fromkeys(todo))
    run_jobs(jobs_for(camp / "check", todo, args.nf_const, args.nf_ptat, tstep=args.tstep, stop=args.stop, start=args.start), args.workers)

    errs = []
    out_check = dict(fail9=[], extra=[])
    print("\n=== DIRECT CLOSED-CODE VERIFICATION: 9 PREVIOUSLY FAILING GROUPS (-40 / 27 / 85 C) ===")
    for gk, rk, c, rc, bc, v in want_fail9:
        m = read_wave(camp / "check", rc, c, bc, v, args.stop, args.start)
        if m:
            e = m["f"] / TARGET - 1
            errs.append(e)
            out_check["fail9"].append(dict(group=gk, cond=rk, code=bc, vctrl=v, f_ghz=m["f"]/1e9, err_pct=e*100, swing_mV=m["swing"]*1e3, idd_mA=m["idd"]*1e3))
            print(f"  {rk:20s} common_code={bc:2d} V={v:.3f}V -> f={m['f']/1e9:.4f} GHz ({e*100:+.2f}%) sw={m['swing']*1e3:.0f}mVpp Idd={m['idd']*1e3:.2f}mA")

    print("\n=== DIRECT VERIFICATION: WORST RANGE-END CORNERS ===")
    for key, c, rc, k, v in want_extra:
        m = read_wave(camp / "check", rc, c, k, v, args.stop, args.start)
        if m:
            e = m["f"] / TARGET - 1
            errs.append(e)
            out_check["extra"].append(dict(cond=key, code=k, vctrl=v, f_ghz=m["f"]/1e9, err_pct=e*100, swing_mV=m["swing"]*1e3, idd_mA=m["idd"]*1e3))
            print(f"  {key:20s} best_code={k:2d}   V={v:.3f}V -> f={m['f']/1e9:.4f} GHz ({e*100:+.2f}%) sw={m['swing']*1e3:.0f}mVpp Idd={m['idd']*1e3:.2f}mA")

    if errs:
        print(f"\nModel error across {len(errs)} verified lock points: {min(errs)*100:+.2f}% .. {max(errs)*100:+.2f}% (max |err| = {max(abs(x) for x in errs)*100:.2f}%)")
    (camp / "check.json").write_text(json.dumps(out_check, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("bench", "sweep", "map", "table", "check", "headroom"))
    ap.add_argument("--cands", default="p45=47,44;p60=34,58;p75=21,73")
    ap.add_argument("--nf-const", type=int, default=28)
    ap.add_argument("--nf-ptat", type=int, default=66)
    ap.add_argument("--passive", default="tt,hh,ll")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--tstep", default=TSTEP)
    ap.add_argument("--stop", type=float, default=STOP)
    ap.add_argument("--start", type=float, default=START)
    ap.add_argument("--full-top", action="store_true")
    ap.add_argument("--resume")
    args = ap.parse_args()
    if args.workers > 2:
        raise ValueError("Host concurrency budget: max --workers 2 for this subagent")

    camp = ROOT / args.resume if args.resume else RESULTS / (args.mode + "_" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    camp.mkdir(parents=True, exist_ok=True)
    print(f"Campaign: {camp.relative_to(ROOT)}", flush=True)

    if args.mode == "bench":
        cmd_bench(args, camp)
    elif args.mode == "headroom":
        cmd_headroom(args, camp)
    elif args.mode == "sweep":
        cmd_sweep(args, camp)
    elif args.mode == "map":
        todo = [(rc, c, k, v) for rc in args.passive.split(",") for c in boundary_first(grid45()) for k in COARSE for v in vgrid(c)]
        run_jobs(jobs_for(camp, todo, args.nf_const, args.nf_ptat, tstep=args.tstep, stop=args.stop, start=args.start), args.workers)
        cmd_table(args, camp)
    elif args.mode == "table":
        cmd_table(args, camp)
    elif args.mode == "check":
        cmd_check(args, camp)

    if UNSETTLED:
        print(f"NOT SETTLED ({len(UNSETTLED)} reads): " + ", ".join(f"{k} {d * 100:+.3f}%" for k, d in UNSETTLED[:12]))


if __name__ == "__main__":
    main()
