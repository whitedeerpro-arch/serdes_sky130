"""Native closed loop of the r5 / k = 4 PLL core: every circuit at transistor level, capture from the precharge.

    uv run python analog/pll/top/tb/native_k4/run.py [--points tt_v1800_t27:tt,...] [--pre-offset 0.04] [--stop 1.5e-6] [--workers 1]

pll_core_r5k4 (r5 frontend with 4-bit VCO, four extraction branches and dummies, prescaler and feedback receiver,
transistor PFD, current-steering CP at 200 uA, PDK k = 4 loop filter), real bias (CML 0.85 mA, CP 50 uA, follower
10 uA copies), PDK resistors.  Code from config/pll_code_table.json; both loop filter nodes precharged to the table's
Vctrl + --pre-offset, released at 50 ns, PFD out of reset at 52 ns.  Reported: capture time (PFD error within 20 ps of
its final value and the trailing 16-period mean feedback period within 100 ppm), static phase offset, final Vctrl,
2 GHz output frequency over the last 200 ns.  The circuit-level counterpart of analog/pll/top/tb/loop_k4 (behavioural VCO).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

RESULTS = ROOT / "results/analog/pll/top/native_k4"
TREF = 4e-9
INCLUDES = [
    "analog/common/devices/spice/sky130_primitives.spice", "analog/common/devices/spice/sky130_pfet_lvt.spice",
    "analog/common/devices/spice/cmos_logic.spice", "analog/common/devices/spice/cmos_dff_reset.spice",
    "analog/common/cml_buffer/spice/cml_delay_resistive.spice", "analog/common/cml_buffer/spice/cml_buffer.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos.spice", "analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice",
    "analog/common/cml_to_cmos/spice/cml_to_cmos_r4.spice", "analog/pll/vco/spice/cap_bank_3b.spice",
    "analog/pll/vco/spice/cap_bank_4b.spice", "analog/pll/vco/spice/vco_ring4_4b.spice",
    "analog/pll/divider/spice/cml_latch.spice", "analog/pll/divider/spice/cml_div2.spice", "analog/pll/divider/spice/cml_prescaler8.spice",
    "analog/pll/top/spice/clock_frontend_r5.spice", "analog/pll/pfd/spice/cmos_dff_reset.spice", "analog/pll/pfd/spice/pfd_cmos.spice",
    "analog/pll/cp/spice/charge_pump.spice", "analog/pll/cp/spice/charge_pump_steer.spice",
    "analog/pll/loop_filter/spice/passive_rc_precharge.spice", "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice",
    "analog/pll/top/spice/pll_core_r5k4.spice"]


def deck(c, rc, code, vctrl, a, camp):
    lines = ["PLL r5 / k=4 native closed loop", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vdummy vdum 0 {supply}", "Vbias vb 0 {supply}",
              "Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
              "In vb vbn 50u", "Ip vbp 0 50u", "Xbn vbn vbn 0 0 serdes_nfet w=5 l=1", "Xbp vbp vbp vb vb serdes_pfet w=20 l=1 nf=4",
              "Ibuf vdd ibuf 10u",
              f"Vref ref 0 PULSE(0 {{supply}} 2n 30p 30p {TREF / 2 - 30e-12:.4e} {TREF:.4e})",
              "Vreset rst_b 0 PWL(0 0 52n 0 52.02n {supply})",
              f"Vpre pre_ref 0 {vctrl + a.pre_offset:.4f}", "Vpen pre_en 0 PWL(0 {supply} 50n {supply} 50.2n 0)"]
    lines += [f"Vcode{k} cfg{k} 0 {(code >> k & 1) * c.supply}" for k in range(4)]
    lines += ["Xpll ref rst_b vbn vbp ibuf vbias cfg0 cfg1 cfg2 cfg3 pre_ref pre_en ctrl z up dn fb0 c0p c0n c1p c1n c2p c2n c3p c3n vdd vdum 0 pll_core_r5k4",
              "Ikick xpll.xclock.v0p xpll.xclock.v0n PWL(0 1u 20p 1u 21p 0)"]
    # operating-point seeds as analog/pll/top/tb/convergence/probe.py: receiver restore latches, balanced ring outputs,
    # varactor wells at the control voltage
    for k in range(4):
        for cell in ("rx", "fb"):
            lines += [f".nodeset v(xpll.xclock.x{cell}{k}.xrestore.qp)=0 v(xpll.xclock.x{cell}{k}.xrestore.qn)={{supply}}"]
        for sd in ("p", "n"):
            lines += [f".nodeset v(xpll.xclock.v{k}{sd})={c.supply - .12:.3f} v(xpll.xclock.xvco.xv{k}{sd}.p2)={vctrl:.4f}"]
    lines += [f".nodeset v(ctrl)={vctrl:.4f} v(z)={vctrl:.4f}",
              # default SPARSE solver: with KLU the operating point converges (true gmin stepping) but the first
              # transient step fails ("initial timepoint", reported at the bandgap trim source) - 2026-11-09, TT
              f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u",
              ".save v(ref) v(fb0) v(ctrl) v(z) v(c0p)", ".control", "set num_threads=1",
              f"tran 4p {a.stop:.4e} 0 4p", "wrdata loop.tsv v(ref) v(fb0) v(ctrl) v(z) v(c0p)", "quit", ".endc", ".end"]
    text = spice.skip_output_before(spice.binary_output("\n".join(lines) + "\n"), "40n")
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.real(text)
    old = "Ibuf vdd ibuf 10u"
    assert text.count(old) == 1
    text = text.replace(old, "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc)


def rising(t, y):
    e, p = crossings(t, y - y.max() / 2)
    return e[p > 0]


def analyse(path, a):
    w = spice.Waves(path)
    t = w.t
    ref, fb = rising(t, w["v(ref)"]), rising(t, w["v(fb0)"])
    ref, fb = ref[ref > 55e-9], fb[fb > 55e-9]
    idx = np.clip(np.searchsorted(fb, ref), 1, len(fb) - 1)
    near = np.where(np.abs(fb[idx] - ref) < np.abs(fb[idx - 1] - ref), fb[idx], fb[idx - 1])
    e = near - ref
    e_final = float(np.median(e[-40:]))
    per = np.diff(near, prepend=near[0] - TREF)
    cum = np.cumsum(per)
    mean16 = np.array([(cum[i] - (cum[i - 16] if i >= 16 else 0.0)) / min(i + 1, 16) for i in range(len(per))])
    bad = (np.abs(e - e_final) > 20e-12) | (np.abs(mean16 / TREF - 1) > 1e-4)
    capture = float(ref[bad].max() - 52e-9) if bad.any() else 0.0
    locked = not bad[-60:].any()
    c0 = rising(t, w["v(c0p)"])
    c0 = c0[c0 > t[-1] - 200e-9]
    f0 = (len(c0) - 1) / (c0[-1] - c0[0]) if len(c0) > 2 else float("nan")
    return dict(capture_s=capture, locked_at_end=bool(locked), offset_s=e_final, vctrl_final=float(np.mean(w["v(ctrl)"][t > t[-1] - 100e-9])),
                f_out=float(f0), e_pp_last_s=float(np.ptp(e[-40:])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:tt")
    ap.add_argument("--pre-offset", type=float, default=0.04)
    ap.add_argument("--stop", type=float, default=1.5e-6)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--resume")
    a = ap.parse_args()
    table = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = []
    for spec in a.points.split(","):
        cond, rc = spec.split(":")
        c, t = Condition.parse(cond), table[spec]
        d = camp / spec.replace(":", "_")
        if spice.case_output(d, "run", "loop.raw", a.stop) is not None:
            continue
        jobs.append((deck(c, rc, t["code"], t["vctrl"], a, camp / "snap"), spice.next_run_dir(d, "run"),
                     dict(timeout_s=6 * 3600, meta=dict(point=spec, code=t["code"], vctrl=t["vctrl"], pre_offset=a.pre_offset))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec in a.points.split(","):
        p = spice.case_output(camp / spec.replace(":", "_"), "run", "loop.raw", a.stop)
        if p is None:
            print(f"{spec}: missing")
            continue
        r = analyse(p, a)
        rows[spec] = dict(code=table[spec]["code"], vctrl_table=table[spec]["vctrl"], **r)
        print(f"{spec:18s} code {table[spec]['code']:2d}: capture {r['capture_s'] * 1e9:6.0f} ns, locked at end {r['locked_at_end']}, offset {r['offset_s'] * 1e12:6.1f} ps "
              f"(pp {r['e_pp_last_s'] * 1e12:.2f}), Vctrl {r['vctrl_final']:.3f} V (table {table[spec]['vctrl']:.3f}), f_out {r['f_out'] / 1e9:.5f} GHz", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
