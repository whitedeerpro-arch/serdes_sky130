"""45-corner PVT verification (with hh / ll PDK resistor corners) for pll_sync_prescaler8_2stack.

    uv run python analog/pll/divider/tb/sync2_pvt/run.py --rpdk hh --workers 4
    uv run python analog/pll/divider/tb/sync2_pvt/run.py --rpdk ll --workers 4

Real host bias distribution, fixed-width PDK resistors, standardized input buffer + 5 fF output taps
and feedback receiver serdes_cml_to_cmos_pvt_candidate (same boundary as rcorner.py).
Measures output swings, divide ratios, synchronous edge skew (q4_rise - q2_fall, q8_rise - q4_fall),
and tail-device saturation margin (Vds - Vdsat) across mux2 / ckdrv / outbuf.
"""
import argparse
import json
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition, boundary_first, grid45
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/pll/divider/sync2_pvt"
INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice",
    "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/pll/divider/spice/sync_prescaler8_2stack.spice",
]
STOP, SAVE_FROM = 24e-9, 12e-9
WANT = {"q2": 1.0e9, "q4": 0.5e9, "q8": 0.25e9, "fb": 0.25e9}
PROBES = (
    "v(bp) v(bn) v(d02p) v(d02n) v(d04p) v(d04n) v(d08p) v(d08n) v(fb0) v(fb0n) "
    "i(Vdd) v(xpre.vbias_ck) "
    "v(xpre.xx1.tail) @m.xpre.xx1.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat] "
    "v(xpre.xckdrv.tail) @m.xpre.xckdrv.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat] "
    "v(xpre.xq2buf.tail) @m.xpre.xq2buf.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat]"
)


def deck(c: Condition, rc: str, freq: float, input_pp: float, snap_dir):
    lib = spice.corner_values(c)["MODEL_LIBRARY"]
    lines = [
        f"Sync2 prescaler8 PVT: {c.tag} ({rc})",
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
        f".save {PROBES}",
        ".control",
        "set num_threads=1",
        f"tran 4p {STOP:.4e} 0 4p",
        f"wrdata pre.tsv {PROBES}",
        "quit",
        ".endc",
        ".end",
    ]
    text = spice.skip_output_before(spice.binary_output("\n".join(lines) + "\n"), f"{SAVE_FROM:.4e}")
    text = bias.real(text)
    return bias.section(rcorner.to_pdk_fixed(text, snap_dir), c.process, rc)


def _edges(t, sig):
    s = sig - np.mean(sig)
    ri = np.where((s[:-1] <= 0) & (s[1:] > 0))[0]
    fa = np.where((s[:-1] >= 0) & (s[1:] < 0))[0]
    tr = t[ri] - s[ri] * (t[ri + 1] - t[ri]) / (s[ri + 1] - s[ri]) if len(ri) >= 2 else np.array([])
    tf = t[fa] - s[fa] * (t[fa + 1] - t[fa]) / (s[fa + 1] - s[fa]) if len(fa) >= 2 else np.array([])
    freq = float(1.0 / np.mean(np.diff(tr))) if len(tr) >= 2 else 0.0
    return float(np.ptp(sig)), float(0.5 * (np.max(sig) + np.min(sig))), freq, tr, tf


def analyse(path):
    w = spice.Waves(path)
    t = w.t
    m = t >= 14e-9
    tm = t[m]
    inp_sw, _, inp_f, _, _ = _edges(tm, w["v(bp)"][m] - w["v(bn)"][m])
    q2_sw, q2_cm, q2_f, tr2, tf2 = _edges(tm, w["v(d02p)"][m] - w["v(d02n)"][m])
    q4_sw, q4_cm, q4_f, tr4, tf4 = _edges(tm, w["v(d04p)"][m] - w["v(d04n)"][m])
    q8_sw, q8_cm, q8_f, tr8, _ = _edges(tm, w["v(d08p)"][m] - w["v(d08n)"][m])
    fb_sw, _, fb_f, _, _ = _edges(tm, w["v(fb0)"][m] - w["v(fb0n)"][m])
    sk4 = float(np.mean([x - tf2[np.argmin(np.abs(tf2 - x))] for x in tr4[1:-1]])) if len(tr4) > 2 and len(tf2) > 0 else float("nan")
    sk8 = float(np.mean([x - tf4[np.argmin(np.abs(tf4 - x))] for x in tr8[1:]]) if len(tr8) >= 2 and len(tf4) > 0 else float("nan"))
    # Include interior q8 edges matching q4 fall edges cleanly: skip last q8 edge only if near boundary
    if len(tr8) >= 2 and len(tf4) > 0:
        inner = [x for x in tr8 if tf4[0] < x < tf4[-1]]
        if inner:
            sk8 = float(np.mean([x - tf4[np.argmin(np.abs(tf4 - x))] for x in inner]))
    mux_ov = float(np.min(w["v(xpre.xx1.tail)"][m] - w["@m.xpre.xx1.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat]"][m]))
    ck_ov = float(np.min(w["v(xpre.xckdrv.tail)"][m] - w["@m.xpre.xckdrv.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat]"][m]))
    buf_ov = float(np.min(w["v(xpre.xq2buf.tail)"][m] - w["@m.xpre.xq2buf.xtail.xmos.msky130_fd_pr__nfet_01v8[vdsat]"][m]))
    return {
        "in": {"swing": inp_sw, "freq": inp_f},
        "q2": {"swing": q2_sw, "freq": q2_f, "want": WANT["q2"]},
        "q4": {"swing": q4_sw, "freq": q4_f, "want": WANT["q4"]},
        "q8": {"swing": q8_sw, "freq": q8_f, "want": WANT["q8"]},
        "fb": {"swing": fb_sw, "freq": fb_f, "want": WANT["fb"]},
        "sk4_ps": sk4 * 1e12,
        "sk8_ps": sk8 * 1e12,
        "ov_min": min(mux_ov, ck_ov, buf_ov),
        "ov": {"mux": mux_ov, "ckdrv": ck_ov, "buf": buf_ov},
        "idd_ma": float(-np.mean(w["i(vdd)"][m]) * 1e3),
        "vck": float(np.mean(w["v(xpre.vbias_ck)"][m])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpdk", default="hh", choices=["tt", "hh", "ll"])
    ap.add_argument("--freq", type=float, default=2.0e9)
    ap.add_argument("--input-pp", type=float, default=0.30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    a = ap.parse_args()
    camp = ROOT / a.resume if a.resume else RESULTS / f"{a.rpdk}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True, exist_ok=True)
    conds = boundary_first(grid45())
    jobs = []
    for c in conds:
        d = camp / c.tag
        if spice.case_output(d, "run", "pre.raw", STOP) is None:
            txt = deck(c, a.rpdk, a.freq, a.input_pp, camp / "snap")
            jobs.append((txt, spice.next_run_dir(d, "run"), dict(timeout_s=1800, meta=dict(tag=c.tag, rpdk=a.rpdk))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for c in conds:
        p = spice.case_output(camp / c.tag, "run", "pre.raw", STOP)
        if p is None:
            print(f"{c.tag:15s} MISSING")
            continue
        r = analyse(p)
        rows[c.tag] = r
        print(
            f"{c.tag:15s} Id={r['idd_ma']:5.2f}mA in={r['in']['swing']*1e3:4.0f} | "
            f"q2={r['q2']['swing']*1e3:4.0f}({r['q2']['freq']/1e9:.3f}) "
            f"q4={r['q4']['swing']*1e3:4.0f}({r['q4']['freq']/1e9:.3f}) "
            f"q8={r['q8']['swing']*1e3:4.0f}({r['q8']['freq']/1e9:.3f}) "
            f"fb={r['fb']['freq']/1e9:.4f} | sk4={r['sk4_ps']:+5.2f} sk8={r['sk8_ps']:+5.2f} ps | ov_min={r['ov_min']:+.3f}V",
            flush=True,
        )
    bad = [
        t for t, r in rows.items()
        if any(abs(r[k]["freq"] / r[k]["want"] - 1) > 0.002 for k in ("q2", "q4", "q8", "fb"))
    ]
    if rows:
        min_q2 = min(rows, key=lambda t: rows[t]["q2"]["swing"])
        min_q4 = min(rows, key=lambda t: rows[t]["q4"]["swing"])
        min_q8 = min(rows, key=lambda t: rows[t]["q8"]["swing"])
        min_ov = min(rows, key=lambda t: rows[t]["ov_min"])
        sk4s = [r["sk4_ps"] for r in rows.values() if np.isfinite(r["sk4_ps"])]
        sk8s = [r["sk8_ps"] for r in rows.values() if np.isfinite(r["sk8_ps"])]
        print(
            f"\nSUMMARY ({a.rpdk}): {len(rows)}/45 complete, divide_errors={len(bad)} {bad[:8]}\n"
            f"  min swing mVpp: q2={rows[min_q2]['q2']['swing']*1e3:.1f}@{min_q2}, "
            f"q4={rows[min_q4]['q4']['swing']*1e3:.1f}@{min_q4}, "
            f"q8={rows[min_q8]['q8']['swing']*1e3:.1f}@{min_q8}\n"
            f"  skew ps: sk4=[{min(sk4s):+.2f}, {max(sk4s):+.2f}] (span {max(sk4s)-min(sk4s):.2f} ps), "
            f"sk8=[{min(sk8s):+.2f}, {max(sk8s):+.2f}] (span {max(sk8s)-min(sk8s):.2f} ps)\n"
            f"  min tail Vds-Vdsat: {rows[min_ov]['ov_min']:+.3f}V@{min_ov}",
            flush=True,
        )
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), divide_errors=bad, rows=rows), indent=1))
    print(camp.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
