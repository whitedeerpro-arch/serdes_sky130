"""Sampler offset trim: input-referred offset per injected current at the master latch nodes, 45 conditions.

    uv run python analog/rx/sampler/tb/offset_dac/run.py inject [--corners tt,ss,ff,sf,fs] [--ua 10]

Bench of tb/offset_mc (ideal PI-like clocks, slow differential ramp -25 -> +25 mV over 40 ns) without
mismatch.  Ideal DC current sinks on the master latch outputs mp / mn of each sample DFF stand in for
a current-steering trim DAC (common current I0 on both nodes, differential d moved between them).
Cases per condition, the same on all four lanes: nom (no sinks); plus (mp I0 + d, mn I0 - d); minus
(mp I0 - d, mn I0 + d); cm (I0 on both: common mode only, node CM drops I0 R).  All lanes move
together because the lanes interact through the shared input buffer: a lane that decides at a
different ramp point than its neighbours changes their input through its kickback (seen: an
uninjected lane moved 1.9 mV while its neighbours were shifted by +-7.5 mV).
Offset shift = ramp slope x (crossing time with sinks - without); gain = (plus - minus) / (4 d).  The trim gain (mV per uA of
differential current) sets the DAC full scale and LSB per condition (docs/design/rx_pi_sampler.md).
One ngspice per MOS corner; supply and temperature loop in the control block (option temp, alter).

    uv run python analog/rx/sampler/tb/offset_dac/run.py dc [--corners ...] [--node 0.2]

The DAC alone (rx_offset_dac.spice, with its unit-current reference) on the bench tail-bias chain (850 uA reference -> pll_cml_tail_bias,
as in the sampler benches), outputs held at VDD - node V: sink currents of op / on for all 64 codes;
unit current, differential step, DNL, monotonicity.  Input-referred offset = gain x (I_op - I_on).

    uv run python analog/rx/sampler/tb/offset_dac/run.py codes --dut ac_trim|ac_cal [--codes 0,16,31,32,47,63]

The trimmed sampler block itself (variant ac_cal: current DAC; ac_trim: auxiliary pair, voltage mode)
in the offset bench with a wider ramp (-60 -> +60 mV over 96 ns, same 1.25 mV/ns), all four lanes at
the same code per case: threshold per code relative to the mean of codes 31 and 32 (+-0.5 LSB around
zero trim for a mismatch-free block), full-scale step (code 0 -> 63) / 63 per condition.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = ROOT / "analog/rx/sampler/tb/offset_mc/tb_rx_sampler_offset_mc_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/offset_dac"
SLOPE = 0.05 / 40e-9
LANES = ("d0", "d1", "e0", "e1")
SINKS = [f"I{l}{s}" for l in LANES for s in "pn"]
SENT = -1e30


def netlist(process, extra=""):
    c = Condition(process, 1.8, 27)
    text = spice.render(TEMPLATE, **(spice.corner_values(c) | {"SECTION": process}))
    sinks = "\n".join(f"I{l}{s} xdut.x{l}.m{s} 0 dc 0" for l in LANES for s in "pn")
    return text + "\n" + sinks + "\n" + extra


CASES = ("nom", "plus", "minus", "cm")


def inject_cases(i0, d):
    """(label, {sink: amps}) per case of CASES."""
    side = {"plus": (i0 + d, i0 - d), "minus": (i0 - d, i0 + d), "cm": (i0, i0)}
    return [("nom", {})] + [(k, {f"I{l}{s}": side[k][j] for l in LANES for j, s in enumerate("pn")}) for k in CASES[1:]]


def deck(process, cases, extra=""):
    """cases: (supply, temp, label, {sink: amps}); one row of crossing times per case in xing.tsv."""
    meas = [f"let s_{l} = v({l}p) - v({l}n)" for l in LANES] + [f"meas tran t_{l} when s_{l}=0 rise=1 from=6n" for l in LANES]
    ctl = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale", "set appendwrite",
           "setplot const"] + [f"let t_{l} = {SENT}" for l in LANES]
    for k, (v, t, label, cur) in enumerate(cases):
        ctl += [f"* case {k} {v} V {t} C {label}", f"option temp={t}", f"alter vdd dc={v}", f"alter vref dc={v}"]
        ctl += [f"alter {s.lower()} dc={cur.get(s, 0.0):.6e}" for s in SINKS]
        ctl += ["tran 2p 46n 0 4p"] + meas + WRITE
    ctl += ["quit", ".endc", ".end", ""]
    return netlist(process, extra) + "\n" + "\n".join(ctl)


# One row per case, as serdes_flow.mc writes: `let t_x = t_x` over sentinels of the same names in the
# const plot.  (New names such as `let w = t_x` or `let k = 3` take the transient's time scale, and
# wrdata then writes one row per time point; campaigns before 2026-11-03 13:00 have that format, with
# the case index c_k as a column, and read_rows keeps the last row of each case.)
WRITE = [f"let t_{l} = t_{l}" for l in LANES] + ["wrdata xing.tsv " + " ".join(f"t_{l}" for l in LANES),
                                                  "destroy all", "setplot const"]


def read_rows(path):
    """{case index: row}; rows carry w_<lane> (= t_<lane>) either way."""
    rows, names, k = {}, None, 0
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if not p:
            continue
        try:
            vals = [float(x) for x in p]
        except ValueError:
            names = p
            continue
        r = {n: (np.nan if v <= SENT / 10 else v) for n, v in zip(names, vals)}
        for l in LANES:
            if f"t_{l}" in r:
                r[f"w_{l}"] = r[f"t_{l}"]
        if "c_k" in r:
            rows[int(r["c_k"])] = r
        else:
            rows[k] = r
            k += 1
    return rows


def run_inject(a, camp):
    d = a.ua * 1e-6
    cases = [(v, t, label, cur) for v in SUPPLY_V for t in TEMP_C for label, cur in inject_cases(a.i0_ua * 1e-6, d)]
    jobs = [(deck(p, cases), camp / p, dict(timeout_s=60 * len(cases), meta=dict(process=p, ua=a.ua, i0_ua=a.i0_ua)))
            for p in a.corners.split(",")]
    t0 = time.time()
    spice.run_many(jobs, workers=a.workers, smoke=False)
    out = dict(differential_ua=2 * a.ua, i0_ua=a.i0_ua, slope_v_per_s=SLOPE, conditions={})
    for p in a.corners.split(","):
        f = camp / p / "xing.tsv"
        rows = read_rows(f) if f.exists() else {}
        n = len(CASES)
        for i in range(0, len(cases), n):
            v, t = cases[i][0], cases[i][1]
            got = [rows.get(i + j) for j in range(n)]
            tag = Condition(p, v, t).tag
            if any(r is None for r in got):
                print(f"  {tag}: missing")
                continue
            nom = got[0]
            sh = {k: {l: (r[f"w_{l}"] - nom[f"w_{l}"]) * SLOPE * 1e3 for l in LANES} for k, r in zip(CASES[1:], got[1:])}
            gain = {l: (sh["plus"][l] - sh["minus"][l]) / (4 * a.ua) for l in LANES}   # mV per uA differential
            asym = {l: sh["plus"][l] + sh["minus"][l] for l in LANES}
            out["conditions"][tag] = dict(shift_mv=sh, gain_mv_per_ua=gain, asym_mv=asym)
            g = np.array(list(gain.values()))
            print(f"  {tag:16s} gain {g.min():.3f}..{g.max():.3f} mV/uA  asym {min(asym.values()):+5.2f}..{max(asym.values()):+5.2f}"
                  f"  cm-only {min(sh['cm'].values()):+5.2f}..{max(sh['cm'].values()):+5.2f} mV")
    g = [x for c in out["conditions"].values() for x in c["gain_mv_per_ua"].values() if np.isfinite(x)]
    if g:
        print(f"gain {min(g):.3f}..{max(g):.3f} mV/uA over {len(g)} conditions ({time.time() - t0:.0f} s)")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


DC_DECK = """RX offset DAC DC transfer
.lib "@MODEL_LIBRARY@" @SECTION@
.include "@PROJECT_ROOT@/analog/common/devices/spice/sky130_primitives.spice"
.include "@PROJECT_ROOT@/analog/common/devices/spice/cmos_logic.spice"
.include "@PROJECT_ROOT@/analog/pll/divider/spice/cml_div2.spice"
.include "@PROJECT_ROOT@/analog/rx/sampler/spice/rx_offset_dac.spice"
Vdd vdd 0 1.8
Vref vref 0 1.8
Iref vref vbias .85m
Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4
Xlb vbias vbias_logic vdd 0 pll_cml_tail_bias
Vop op 0 1.6
Von on 0 1.6
@BITS@
Xdb vbias_logic vbd vdd 0 serdes_rx_offset_dac_bias
Xdac op on b0 b1 b2 b3 b4 b5 vbd vdd 0 serdes_rx_offset_dac
.temp 27
"""


def dc_deck(process, conds, node):
    """conds: (supply, temp); every code 0..63 per condition; rows (case, code, i_op, i_on) in dc.tsv."""
    c = Condition(process, 1.8, 27)
    text = spice.render(DC_DECK.replace("@BITS@", "\n".join(f"Vb{k} b{k} 0 0" for k in range(6))),
                        **(spice.corner_values(c) | {"SECTION": process}))
    ctl = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale", "set appendwrite"]
    k = 0
    for v, temp in conds:
        ctl += [f"option temp={temp}", f"alter vdd dc={v}", f"alter vref dc={v}", f"alter vop dc={v - node}", f"alter von dc={v - node}"]
        for code in range(64):
            ctl += [f"alter vb{b} dc={v * ((code >> b) & 1)}" for b in range(6)]
            ctl += ["op", f"let c_k = {k}", f"let c_code = {code}", "let w_p = -i(vop)", "let w_n = -i(von)",
                    "wrdata dc.tsv c_k c_code w_p w_n", "destroy all"]
            k += 1
    ctl += ["quit", ".endc", ".end", ""]
    return text + "\n".join(ctl)


def run_dc(a, camp):
    conds = [(v, t) for v in SUPPLY_V for t in TEMP_C]
    jobs = [(dc_deck(p, conds, a.node), camp / p, dict(timeout_s=1800, meta=dict(process=p, node=a.node)))
            for p in a.corners.split(",")]
    spice.run_many(jobs, workers=a.workers, smoke=False)
    out = dict(node_below_vdd_v=a.node, conditions={})
    for p in a.corners.split(","):
        f = camp / p / "dc.tsv"
        rows = read_rows(f) if f.exists() else {}
        for j, (v, t) in enumerate(conds):
            r = [rows.get(j * 64 + code) for code in range(64)]
            tag = Condition(p, v, t).tag
            if any(x is None for x in r):
                print(f"  {tag}: missing")
                continue
            ip = np.array([x["w_p"] for x in r]); im = np.array([x["w_n"] for x in r])
            diff = (ip - im) * 1e6                          # uA, ideally (2c - 63) Iu
            step = np.diff(diff)
            lsb = (diff[-1] - diff[0]) / 63                 # end-point differential step (= 2 Iu)
            dnl = step / lsb - 1
            inl = (diff - (diff[0] + lsb * np.arange(64))) / lsb
            out["conditions"][tag] = dict(total_ua=float((ip + im).mean() * 1e6), total_spread_ua=float(np.ptp(ip + im) * 1e6),
                                          step_ua=float(lsb), dnl_min=float(dnl.min()), dnl_max=float(dnl.max()),
                                          inl_max=float(np.abs(inl).max()), monotonic=bool((step > 0).all()),
                                          diff_ua=diff.tolist())
            o = out["conditions"][tag]
            print(f"  {tag:16s} total {o['total_ua']:6.1f} uA (spread {o['total_spread_ua']:.2f})  step {lsb:5.3f} uA"
                  f"  DNL {o['dnl_min']:+.3f}..{o['dnl_max']:+.3f}  INL {o['inl_max']:.3f} LSB  {'monotonic' if o['monotonic'] else 'NOT MONOTONIC'}")
    st = [c["step_ua"] for c in out["conditions"].values()]
    if st:
        print(f"step {min(st):.3f}..{max(st):.3f} uA over {len(st)} conditions")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


VARIANTS = {"ac_cal": ("serdes_rx_half_rate_samples_ac_cal", "rx_offset_dac.spice"),
            "ac_trim": ("serdes_rx_half_rate_samples_ac_trim", "rx_offset_trim.spice")}
CAL_NODES = [f"{l}b{k}" for l in LANES for k in range(6)]
RAMP_A, RAMP_T0 = 0.06, 5e-9
RAMP_T = 2 * RAMP_A / SLOPE


def codes_deck(process, variant, cases):
    """cases: (supply, temp, code); crossing times per case in xing.tsv (as deck())."""
    sub, inc = VARIANTS[variant]
    c = Condition(process, 1.8, 27)
    text = spice.render(TEMPLATE, **(spice.corner_values(c) | {"SECTION": process}))
    old_ramp = "Vramp ramp 0 PWL(0 -0.025 5n -0.025 45n 0.025)"
    old_dut = "Xdut ip in dp dn ep en d0p d0n d1p d1n e0p e0n e1p e1n vbias vdd 0 serdes_rx_half_rate_samples_ac rb=2k"
    assert text.count(old_ramp) == 1 and text.count(old_dut) == 1
    text = text.replace(old_ramp, f"Vramp ramp 0 PWL(0 {-RAMP_A} {RAMP_T0:.4e} {-RAMP_A} {RAMP_T0 + RAMP_T:.4e} {RAMP_A})")
    text = text.replace(old_dut, old_dut.replace("serdes_rx_half_rate_samples_ac rb=2k", " ".join(CAL_NODES) + f" {sub} rb=2k"))
    inc_line = f'.include "{ROOT}/analog/rx/sampler/spice/rx_half_rate_samples_ac.spice"'
    assert text.count(inc_line) == 1
    text = text.replace(inc_line, inc_line + f'\n.include "{ROOT}/analog/rx/sampler/spice/rx_offset_dac.spice"'
                        + (f'\n.include "{ROOT}/analog/rx/sampler/spice/rx_offset_trim.spice"' if variant == "ac_trim" else ""))
    text += "\n" + "\n".join(f"Vc{n} {n} 0 dc 0" for n in CAL_NODES) + "\n"
    stop = RAMP_T0 + RAMP_T + 1e-9
    meas = [f"let s_{l} = v({l}p) - v({l}n)" for l in LANES] + [f"meas tran t_{l} when s_{l}=0 rise=1 from=6n" for l in LANES]
    ctl = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale", "set appendwrite",
           "setplot const"] + [f"let t_{l} = {SENT}" for l in LANES]
    for k, (v, temp, code) in enumerate(cases):
        ctl += [f"* case {k} {v} V {temp} C code {code}", f"option temp={temp}", f"alter vdd dc={v}", f"alter vref dc={v}"]
        ctl += [f"alter vc{n} dc={v * ((code >> int(n[-1])) & 1)}" for n in CAL_NODES]
        ctl += [f"tran 2p {stop:.4e} 0 4p"] + meas + WRITE
    ctl += ["quit", ".endc", ".end", ""]
    return text + "\n".join(ctl)


def run_codes(a, camp):
    codes = [int(x) for x in a.codes.split(",")]
    assert 31 in codes and 32 in codes and 0 in codes and 63 in codes
    cases = [(v, t, code) for v in SUPPLY_V for t in TEMP_C for code in codes]
    jobs = [(codes_deck(p, a.dut, cases), camp / p, dict(timeout_s=90 * len(cases), meta=dict(process=p, dut=a.dut, codes=codes)))
            for p in a.corners.split(",")]
    t0 = time.time()
    spice.run_many(jobs, workers=a.workers, smoke=False)
    out = dict(dut=a.dut, codes=codes, slope_v_per_s=SLOPE, conditions={})
    n = len(codes)
    for p in a.corners.split(","):
        f = camp / p / "xing.tsv"
        rows = read_rows(f) if f.exists() else {}
        for i in range(0, len(cases), n):
            v, temp = cases[i][0], cases[i][1]
            tag = Condition(p, v, temp).tag
            got = {code: rows.get(i + j) for j, code in enumerate(codes)}
            if any(r is None for r in got.values()):
                print(f"  {tag}: missing")
                continue
            thr = {}
            for l in LANES:
                ref = (got[31][f"w_{l}"] + got[32][f"w_{l}"]) / 2
                thr[l] = {code: (got[code][f"w_{l}"] - ref) * SLOPE * 1e3 for code in codes}
            fs = {l: (thr[l][63] - thr[l][0]) / 63 for l in LANES}
            mid = {l: thr[l][32] - thr[l][31] for l in LANES}
            out["conditions"][tag] = dict(threshold_mv=thr, step_fullscale_mv=fs, step_mid_mv=mid,
                                          range_mv=[min(thr[l][0] for l in LANES), max(thr[l][63] for l in LANES)])
            f_ = np.array(list(fs.values()))
            print(f"  {tag:16s} step {f_.min():.2f}..{f_.max():.2f} mV  code0 {min(thr[l][0] for l in LANES):+6.1f}"
                  f"  code63 {max(thr[l][63] for l in LANES):+6.1f} mV  mid step {min(mid.values()):.2f}..{max(mid.values()):.2f}")
    st = [x for c in out["conditions"].values() for x in c["step_fullscale_mv"].values()]
    if st:
        print(f"full-scale step {min(st):.2f}..{max(st):.2f} mV over {len(out['conditions'])} conditions ({time.time() - t0:.0f} s)")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    i = sub.add_parser("inject", help="ideal current sinks: trim gain per condition")
    i.add_argument("--corners", default=",".join(PROCESS))
    i.add_argument("--ua", type=float, default=10.0, help="d: differential current is 2 d")
    i.add_argument("--i0-ua", type=float, default=20.0, help="common current per node")
    i.add_argument("--workers", type=int, default=4)
    d = sub.add_parser("dc", help="the DAC alone: sink currents for all codes")
    d.add_argument("--corners", default=",".join(PROCESS))
    d.add_argument("--node", type=float, default=0.2, help="outputs held at VDD - node (V)")
    d.add_argument("--workers", type=int, default=4)
    k = sub.add_parser("codes", help="trimmed sampler block: threshold per code")
    k.add_argument("--dut", choices=sorted(VARIANTS), default="ac_trim")
    k.add_argument("--corners", default=",".join(PROCESS))
    k.add_argument("--codes", default="0,16,31,32,47,63")
    k.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{a.mode}" + (f"_{a.dut}" if a.mode == "codes" else ""))
    {"inject": run_inject, "dc": run_dc, "codes": run_codes}[a.mode](a, camp)


if __name__ == "__main__":
    main()
