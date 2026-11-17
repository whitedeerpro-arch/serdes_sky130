"""Native closed loop of the r6 / k = 4 PLL (pll_core_r6k4q): VCO r6, lean frontend, standard-cell PFD.

    uv run python analog/pll/top/tb/native_r6/run.py --map results/analog/pll/vco/r6/map_... [--points tt_v1800_t27:tt,...]
        [--variants ext,hv] [--code-offset 0] [--pre-offset 0.04] [--stop 1.2e-6] [--workers 2] [--resume C]

Bench of analog/pll/top/tb/native_k4_supply (real bias on host, quiet rail from the HV18 r4 LDO or an external
source, tail filter, precharge to the expected Vctrl + pre-offset, release at 50 ns, reset released at 52 ns).
The code and its expected Vctrl come from the r6 map's model (table.json of tuning/r6.py): the centred code of the
point (ext) or of its 1.8 V entry (hv: the VCO sits on about 1.8 V whatever the host supply is); --code-offset moves
to a neighbouring code (in LSB) to exercise the window edges.  Reference: ideal 250 MHz CMOS edge at the PFD (the
reference input path is separate).  Analysis as native_k4 (capture time, static offset, Vctrl, frequency of b0 over
the last 200 ns) plus the quiet rail and the VCO / buffer swings.
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import bias, clock, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

_n = importlib.util.spec_from_file_location("native_k4", ROOT / "analog/pll/top/tb/native_k4/run.py")
nk = importlib.util.module_from_spec(_n)
_n.loader.exec_module(nk)
RESULTS = ROOT / "results/analog/pll/top/native_r6"
LDO_DATA = ROOT / "docs/data/ldo_r4.json"
SC_LIB = "/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
DROP = ("pll_core_r5k4.spice", "clock_frontend_r5.spice", "cap_bank_4b.spice", "vco_ring4_4b.spice", "cml_to_cmos_r4.spice")
INCLUDES = [p for p in nk.INCLUDES if not any(d in p for d in DROP)] + [
    "analog/pll/vco/spice/cap_bank_5b.spice", "analog/pll/vco/spice/vco_delay_r6.spice", "analog/pll/vco/spice/vco_ring4_r6.spice",
    "analog/pll/top/spice/clock_frontend_r6q.spice", "analog/pll/pfd/spice/pfd_sc.spice",
    "analog/common/ldo/spice/ldo_passives.spice", "analog/common/ldo/spice/ldo_hv18_core_r4.spice",
    "analog/common/ldo/spice/pll_supply_hv18_r4.spice", "analog/common/ldo/spice/pll_bias_filter_r4.spice",
    "analog/pll/top/spice/pll_core_r6k4q.spice"]
PROBES = "v(ref) v(fb0) v(ctrl) v(z) v(b0p) v(b0n) v(xpll.xclock.v0p) v(xpll.xclock.v0n) v(vq) v(xpll.vbias_q) v(up) v(dn)"


def entry(table, spec, variant, offset):
    """(table key, code, expected Vctrl) the VCO runs at: the point's own entry, or its 1.8 V entry behind the LDO."""
    cond, rc = spec.split(":")
    c = Condition.parse(cond)
    key = spec if variant == "ext" else f"{c.process}_v1800_t{c.temp}:{rc}"
    r = table[key]
    code = r["best"] + offset
    assert str(code) in r["v"], f"{key}: code {code} has no 2 GHz point inside the window (codes {r['codes']})"
    return key, code, r["v"][str(code)]


def deck(c, rc, code, vctrl, variant, trim, a, camp):
    vq0 = 1.8 if variant == "hv" else c.supply
    lines = ["PLL r6 / k=4 native closed loop on a quiet supply", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES] + [f'.include "{SC_LIB}"']
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}"]
    if variant == "hv":
        lines += [f"Vin vin 0 {a.vin}", "Ven en 0 {supply}"] + [f"Et{k} t{k} 0 vdd 0 {trim >> k & 1}" for k in range(6)]
        lines += ["Xldo vin vdd vq bias_vbg vgi_bias en t0 t1 t2 t3 t4 t5 0 serdes_pll_supply_hv18_r4"]
    else:
        lines += ["Vq vq 0 {supply}", "Xldo vq vdd vq bias_vbg vgi_bias 0 0 0 0 0 0 0 0 serdes_pll_supply_hv18_r4"]
    lines += ["Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4",
              "In vb vbn 50u", "Ip vbp 0 50u", "Xbn vbn vbn 0 0 serdes_nfet w=5 l=1", "Xbp vbp vbp vq vq serdes_pfet w=20 l=1 nf=4",
              "Ibuf vdd ibuf 10u",
              f"Vref ref 0 PULSE(0 {{supply}} 2n 30p 30p {nk.TREF / 2 - 30e-12:.4e} {nk.TREF:.4e})",
              "Vreset rst_b 0 PWL(0 0 52n 0 52.02n {supply})",
              f"Vpre pre_ref 0 {vctrl + a.pre_offset:.4f}", "Vpen pre_en 0 PWL(0 {supply} 50n {supply} 50.2n 0)"]
    lines += [f"Ecode{k} cfg{k} 0 vq 0 {code >> k & 1}" for k in range(5)]
    lines += ["Xpll ref rst_b vbn vbp ibuf vbias cfg0 cfg1 cfg2 cfg3 cfg4 pre_ref pre_en ctrl z up dn fb0 "
              "b0p b0n b1p b1n b2p b2n b3p b3n d02p d02n d04p d04n d08p d08n vdd vq 0 pll_core_r6k4q",
              "Ikick xpll.xclock.v0p xpll.xclock.v0n PWL(0 1u 20p 1u 21p 0)",
              # the simulator has no noise: a CML divider latch can sit at its symmetric operating point for 10-20 ns
              # (FS 1.65 V 85 C hh, frontend_r6/divider_fs_hot*); 20 uA for 40 ps breaks it, as noise does on chip
              *[f"Ikick{n} {n}p {n}n PWL(0 0 1n 0 1.01n 20u 1.05n 20u 1.06n 0)" for n in ("d02", "d04", "d08")],
              ".nodeset v(xpll.xclock.xfb0.xrestore.qp)=0 v(xpll.xclock.xfb0.xrestore.qn)={supply}"]
    for k in range(4):
        for sd in ("p", "n"):
            lines += [f".nodeset v(xpll.xclock.v{k}{sd})={vq0 - .12:.3f} v(xpll.xclock.xvco.xv{k}{sd}.p2)={vctrl:.4f}"]
    lines += [f".nodeset v(ctrl)={vctrl:.4f} v(z)={vctrl:.4f} v(vq)={vq0:.3f}",
              f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u",
              f".save {PROBES}", ".control", "set num_threads=1",
              f"tran 4p {a.stop:.4e} 0 4p", f"wrdata loop.tsv {PROBES}", "quit", ".endc", ".end"]
    text = spice.skip_output_before(spice.binary_output("\n".join(lines) + "\n"), "40n")
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.real(text)
    old = "Ibuf vdd ibuf 10u"
    assert text.count(old) == 1
    text = text.replace(old, "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    return bias.section(rcorner.to_pdk_fixed(text, camp), c.process, rc)


def analyse(path, a):
    w = spice.Waves(path)
    t = w.t
    ref, fb = nk.rising(t, w["v(ref)"]), nk.rising(t, w["v(fb0)"])
    lock = clock.feedback_lock(ref, fb, start=55e-9, stop=float(t[-1]), period=nk.TREF)
    late = t > t[-1] - 200e-9
    b0 = w["v(b0p)"][late] - w["v(b0n)"][late]
    v0 = w["v(xpll.xclock.v0p)"][late] - w["v(xpll.xclock.v0n)"][late]
    ed, sg = crossings(t[late], b0)
    r = ed[sg > 0]
    q, vb = w["v(vq)"][late], w["v(xpll.vbias_q)"][late]
    ctrl = w["v(ctrl)"][t > t[-1] - 100e-9]
    return dict(**lock,
                vctrl_final=float(np.mean(ctrl)), vctrl_ripple=float(np.ptp(ctrl)), f_out=float((len(r) - 1) / (r[-1] - r[0])) if len(r) > 2 else None,
                vco_swing=float(np.ptp(v0)), buf_swing=float(np.ptp(b0)), vq_mean=float(np.mean(q)), vq_pp=float(np.ptp(q)), vbias_q_pp=float(np.ptp(vb)))


def case_dir(camp, spec, variant, offset=0):
    suffix = f"_o{offset:+d}" if offset else ""
    return camp / f"{spec.replace(':', '_')}_{variant}{suffix}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True, help="r6 map campaign with table.json")
    ap.add_argument("--points", default="tt_v1800_t27:tt,fs_v1650_t85:hh,ss_v1650_t-40:hh,sf_v1650_t-40:ll")
    ap.add_argument("--variants", default="ext")
    ap.add_argument("--code-offset", type=int, default=0)
    ap.add_argument("--vin", type=float, default=3.3)
    ap.add_argument("--pre-offset", type=float, default=0.04)
    ap.add_argument("--stop", type=float, default=1.2e-6)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    table = json.loads((ROOT / a.map / "table.json").read_text())["rows"]
    trims = json.loads(LDO_DATA.read_text())["calibration_codes"]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    plan = [(spec, v) for spec in a.points.split(",") for v in a.variants.split(",")]
    jobs, ent = [], {}
    for spec, var in plan:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        key, code, vctrl = ent[(spec, var)] = entry(table, spec, var, a.code_offset)
        trim = trims[f"{c.process}:{rc}"]["trim"]
        d = case_dir(camp, spec, var, a.code_offset)
        if spice.case_output(d, "run", "loop.raw", a.stop) is not None:
            continue
        jobs.append((deck(c, rc, code, vctrl, var, trim, a, camp / "snap"), spice.next_run_dir(d, "run"),
                     dict(timeout_s=6 * 3600, meta=dict(point=spec, variant=var, vco_entry=key, code=code, vctrl=vctrl, pre_offset=a.pre_offset))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec, var in plan:
        d = case_dir(camp, spec, var, a.code_offset)
        p = spice.case_output(d, "run", "loop.raw", a.stop)
        if p is None:
            print(f"{spec} {var}: missing")
            continue
        key, code, vctrl = ent[(spec, var)]
        r = analyse(p, a)
        rows[f"{spec}:{var}"] = dict(vco_entry=key, code=code, vctrl_model=vctrl, **r)
        print(spec, var, code, json.dumps(r, allow_nan=False), flush=True)
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
