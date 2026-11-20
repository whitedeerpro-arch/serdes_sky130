"""Local-mismatch Monte Carlo for pll_sync_prescaler8_2stack on stress PVT corners.

    uv run python analog/pll/divider/tb/sync2_mc/run.py --samples 100 --chunk 10 --workers 4

Real host bias distribution, fixed-width PDK resistors, *_mm local-mismatch section.
Checks divide functionality, output swings vs 300 mVpp floor and 400 mVpp target,
mux2/buf tail saturation margin, and replica clock-bias sigma.
"""
import argparse
import json
import re
import time

import numpy as np

from serdes_flow import bias, mc, rcorner, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/pll/divider/sync2_mc"
INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice",
    "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/pll/divider/spice/sync_prescaler8_2stack.spice",
]
DEFAULT_POINTS = "tt_v1800_t27:tt,fs_v1650_t85:hh,ss_v1650_t-40:hh,ff_v1950_t85:ll,fs_v1650_t-40:ll"
STOP, T0, T1 = 22e-9, 10e-9, 22e-9
FLOOR, TARGET = 0.300, 0.400
OUTS = [
    ("q2", "dq2", 1.0e-9, 5),
    ("q4", "dq4", 2.0e-9, 3),
    ("q8", "dq8", 4.0e-9, 2),
    ("fb", "dfb", 4.0e-9, 2),
]


def _mm_section(deck_text: str, proc: str, rc: str) -> str:
    base = bias.section(deck_text, proc, rc)
    return re.sub(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: f"{m[1]}{m[2]}_mm", base, count=1, flags=re.M | re.I)


def base_deck(c: Condition, rc: str, freq: float, input_pp: float, snap_dir) -> str:
    lib = spice.corner_values(c)["MODEL_LIBRARY"]
    lines = [
        f"Sync2 prescaler8 MC: {c.tag} ({rc})",
        f'.lib "{lib}" {c.process}',
        *[f'.include "{ROOT / p}"' for p in INCLUDES],
        f".param supply={c.supply} freq={freq} input_pp={input_pp}",
        "Vdd vdd 0 {supply}",
        "Vreference vref 0 {supply}",
        "Iref vref vbias .85m",
        "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
        "Vp sp 0 SIN({supply-.15} {input_pp/4} {freq})",
        "Vn sn 0 SIN({supply-.15} {-input_pp/4} {freq})",
        "Xbuf sp sn bp bn vbias vdd 0 serdes_cml_buffer",
        "Xpre bp bn d02p d02n d04p d04n d08p d08n vbias vdd 0 pll_sync_prescaler8_2stack",
        "C2p d02p 0 5f", "C2n d02n 0 5f",
        "C4p d04p 0 5f", "C4n d04n 0 5f",
        "C8p d08p 0 5f", "C8n d08n 0 5f",
        "Xfb d08p d08n fb0 fb0n vbias vdd 0 serdes_cml_to_cmos_pvt_candidate",
        "Cfb0 fb0 0 20f", "Cfb0n fb0n 0 20f",
        f".temp {c.temp}",
        ".options reltol=1e-4 abstol=1p vntol=1u",
        ".end",
    ]
    text = "\n".join(lines[:-1]) + "\n"
    text = bias.real(text + ".end\n").rsplit(".end", 1)[0]
    text = rcorner.to_pdk_fixed(text + ".end\n", snap_dir).rsplit(".end", 1)[0]
    return _mm_section(text, c.process, rc).rstrip()


def analysis_and_lets():
    ana = [
        f"tran 5p {STOP:.4e} 0 5p",
        "let dq2 = v(d02p) - v(d02n)",
        "let dq4 = v(d04p) - v(d04n)",
        "let dq8 = v(d08p) - v(d08n)",
        "let dfb = v(fb0) - v(fb0n)",
    ]
    lets = {}
    for name, expr, per, nrise in OUTS:
        span = (nrise - 1)
        ana += [
            f"meas tran {name}_hi max {expr} from={T0:.4e} to={T1:.4e}",
            f"meas tran {name}_lo min {expr} from={T0:.4e} to={T1:.4e}",
            f"meas tran {name}_t0 when {expr}=0 rise=1 from={T0:.4e} to={T1:.4e}",
            f"meas tran {name}_t1 when {expr}=0 rise={nrise} from={T0:.4e} to={T1:.4e}",
        ]
        lets[f"{name}_sw"] = f"{name}_hi - {name}_lo"
        lets[f"{name}_per"] = f"({name}_t1 - {name}_t0)/{span}"
    ana += [
        f"meas tran mux_t_min min v(xpre.xx1.tail) from={T0:.4e} to={T1:.4e}",
        f"meas tran vck_avg avg v(xpre.vbias_ck) from={T0:.4e} to={T1:.4e}",
    ]
    lets["mux_t_min"] = "mux_t_min"
    lets["vck_avg"] = "vck_avg"
    return "\n".join(ana), lets


def report(a, camp, groups):
    out = {}
    print(f"swing floor {FLOOR * 1e3:.0f} / target {TARGET * 1e3:.0f} mVpp")
    for spec, rows in groups.items():
        if len(rows) < 3:
            print(f"{spec:18s} {len(rows)} samples")
            continue
        kf = stats.k_factor(len(rows))
        col = lambda k: np.array([r[k] for r in rows], float)
        fail = np.zeros(len(rows), bool)
        for n, _, per, _ in OUTS:
            p = col(f"{n}_per")
            fail |= ~np.isfinite(p) | (np.abs(p / per - 1) > 0.02)
        sw = {n: col(f"{n}_sw") for n, *_ in OUTS}
        worst = min(float(np.nanmean(v) - kf * np.nanstd(v, ddof=1)) for v in sw.values())
        mt = col("mux_t_min")
        vck = col("vck_avg")
        ci = stats.yield_ci(int((~fail).sum()), len(rows))
        out[spec] = {
            "samples": len(rows),
            "k": kf,
            "divide_fail": int(fail.sum()),
            "divide_pass_ci": list(ci),
            "swing": {
                n: [float(np.nanmean(v)), float(np.nanstd(v, ddof=1)), float(np.nanmin(v))]
                for n, v in sw.items()
            },
            "swing_mean_minus_k_sd": worst,
            "mux_tail_min": [float(np.nanmean(mt)), float(np.nanmin(mt))],
            "vck": [float(np.nanmean(vck)), float(np.nanstd(vck, ddof=1))],
        }
        sw_str = " ".join(f"{n}:{np.nanmean(v)*1e3:4.0f}/{np.nanstd(v,ddof=1)*1e3:4.1f}(min {np.nanmin(v)*1e3:3.0f})" for n, v in sw.items())
        print(
            f"{spec:18s} n={len(rows):3d} k={kf:.2f} div_fail={int(fail.sum()):2d} CI=[{ci[0]:.3f},{ci[1]:.3f}] | "
            f"{sw_str} | mean-ksd={worst*1e3:4.0f}mV ({'PASS>=400' if worst >= TARGET else 'OK>=300' if worst >= FLOOR else 'BELOW'}) | "
            f"mux_t>={np.nanmin(mt):.3f}V vck={np.nanmean(vck):.3f}+-{np.nanstd(vck,ddof=1)*1e3:.1f}mV",
            flush=True,
        )
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), floor=FLOOR, target=TARGET, points=out), indent=1))
    print(camp.relative_to(ROOT), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default=DEFAULT_POINTS)
    ap.add_argument("--samples", type=int, default=80)
    ap.add_argument("--chunk", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--freq", type=float, default=2.0e9)
    ap.add_argument("--input-pp", type=float, default=0.30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    ana, lets = analysis_and_lets()
    jobs, owners = [], []
    for spec in a.points.split(","):
        cond_s, rc = spec.split(":")
        c = Condition.parse(cond_s)
        net = base_deck(c, rc, a.freq, a.input_pp, camp / "snap")
        for idx, cseed, n in mc.chunks(a.samples, a.seed, a.chunk):
            txt = mc.deck(net, samples=n, seed=cseed, analysis=ana, lets=lets, t_end=STOP)
            jobs.append((txt, camp / spec.replace(":", "_") / f"chunk_{idx:03d}", dict(timeout_s=1800, meta=dict(point=spec, chunk=idx))))
            owners.append(spec)
    dirs = mc.run_many(jobs, workers=a.workers)
    groups = {spec: mc.read_all([d for d, o in zip(dirs, owners) if o == spec]) for spec in a.points.split(",")}
    report(a, camp, groups)


if __name__ == "__main__":
    main()
