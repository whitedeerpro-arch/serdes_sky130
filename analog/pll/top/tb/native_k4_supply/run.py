"""Native closed loop of the r5 / k = 4 PLL on its own supply domain: HV18 r4 or an external quiet supply (LDO integration).

    uv run python analog/pll/top/tb/native_k4_supply/run.py [--points tt_v1800_t27:tt,...] [--variants hv,ext] [--vin 3.3]
        [--pre-offset 0.04] [--stop 1.5e-6] [--workers 2] [--resume C]

pll_core_r5k4q (analog/pll/top/spice/pll_core_r5k4q.spice): VCO, extraction buffers, steering CP and k = 4 LF on the
quiet rail vq, VCO / buffer tails behind the 1 MOhm / 16 pF tail filter; PFD, prescaler and receivers on the host rail
(the point's supply).  Real bias on host (one serdes_bias_ref; CML, CP vbn and follower copies from host; the CP vbp
diode on vq).  Variants (docs/design/ldo_r4.md, static configuration):
  hv   serdes_pll_supply_hv18_r4 with vin = --vin, enable high, bg / vgi from the host bias reference, trim code of the
       point's MOS / R corner (docs/data/ldo_r4.json calibration); the VCO then runs at about 1.8 V whatever the host
       is, so its code and Vctrl come from the code table's 1.8 V entry of the same process, temperature and R corner
  ext  vin and vq tied to one ideal source at the point's supply, LDO cell present with enable low (the 1.8 V
       configuration); code from the point's own entry
The LDO and the tail filter start from the operating point (settled; their power-up is analog/common/ldo r4_startup).
Precharge, release and analysis as analog/pll/top/tb/native_k4: capture time, offset, Vctrl, 2 GHz frequency, plus the
quiet rail's mean and peak-to-peak and the filtered tail line over the last 200 ns.
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_n = importlib.util.spec_from_file_location("native_k4", ROOT / "analog/pll/top/tb/native_k4/run.py")
nk = importlib.util.module_from_spec(_n)
_n.loader.exec_module(nk)
RESULTS = ROOT / "results/analog/pll/top/native_k4_supply"
LDO_DATA = ROOT / "docs/data/ldo_r4.json"
INCLUDES = [p for p in nk.INCLUDES if p != "analog/pll/top/spice/pll_core_r5k4.spice"] + [
    "analog/pll/top/spice/clock_frontend_r5q.spice", "analog/common/ldo/spice/ldo_passives.spice",
    "analog/common/ldo/spice/ldo_hv18_core_r4.spice", "analog/common/ldo/spice/pll_supply_hv18_r4.spice",
    "analog/common/ldo/spice/pll_bias_filter_r4.spice", "analog/pll/top/spice/pll_core_r5k4q.spice"]
PROBES = "v(ref) v(fb0) v(ctrl) v(z) v(c0p) v(vq) v(xpll.vbias_q)"


def vco_entry(table, spec, variant):
    """Code-table entry the VCO runs at: the point's own, or its 1.8 V entry behind the LDO."""
    if variant == "ext":
        return spec, table[spec]
    cond, rc = spec.split(":")
    c = Condition.parse(cond)
    key = f"{c.process}_v1800_t{c.temp}:{rc}"
    return key, table[key]


def deck(c, rc, code, vctrl, variant, trim, a, camp):
    vq0 = 1.8 if variant == "hv" else c.supply
    lines = ["PLL r5 / k=4 native closed loop on a quiet supply", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vdummy vdum 0 {supply}"]
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
    lines += [f"Ecode{k} cfg{k} 0 vq 0 {code >> k & 1}" for k in range(4)]
    lines += ["Xpll ref rst_b vbn vbp ibuf vbias cfg0 cfg1 cfg2 cfg3 pre_ref pre_en ctrl z up dn fb0 c0p c0n c1p c1n c2p c2n c3p c3n "
              "vdd vq vdum 0 pll_core_r5k4q",
              "Ikick xpll.xclock.v0p xpll.xclock.v0n PWL(0 1u 20p 1u 21p 0)"]
    for k in range(4):
        for cell in ("rx", "fb"):
            lines += [f".nodeset v(xpll.xclock.x{cell}{k}.xrestore.qp)=0 v(xpll.xclock.x{cell}{k}.xrestore.qn)={{supply}}"]
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
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc)


def rails(path):
    w = spice.Waves(path)
    t = w.t
    late = t > t[-1] - 200e-9
    q, b = w["v(vq)"][late], w["v(xpll.vbias_q)"][late]
    return dict(vq_mean=float(np.mean(q)), vq_pp=float(np.ptp(q)), vq_min=float(q.min()), vbias_q_mean=float(np.mean(b)), vbias_q_pp=float(np.ptp(b)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:tt")
    ap.add_argument("--variants", default="hv,ext")
    ap.add_argument("--vin", type=float, default=3.3)
    ap.add_argument("--pre-offset", type=float, default=0.04)
    ap.add_argument("--stop", type=float, default=1.5e-6)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    table = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
    trims = json.loads(LDO_DATA.read_text())["calibration_codes"]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    plan = [(spec, v) for spec in a.points.split(",") for v in a.variants.split(",")]
    jobs = []
    for spec, var in plan:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        key, t = vco_entry(table, spec, var)
        trim = trims[f"{c.process}:{rc}"]["trim"]
        d = camp / f"{spec.replace(':', '_')}_{var}"
        if spice.case_output(d, "run", "loop.raw", a.stop) is not None:
            continue
        jobs.append((deck(c, rc, t["code"], t["vctrl"], var, trim, a, camp / "snap"), spice.next_run_dir(d, "run"),
                     dict(timeout_s=6 * 3600, meta=dict(point=spec, variant=var, vco_entry=key, code=t["code"], vctrl=t["vctrl"],
                                                        trim=trim if var == "hv" else None, vin=a.vin if var == "hv" else None,
                                                        pre_offset=a.pre_offset))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec, var in plan:
        p = spice.case_output(camp / f"{spec.replace(':', '_')}_{var}", "run", "loop.raw", a.stop)
        if p is None:
            print(f"{spec} {var}: missing")
            continue
        key, t = vco_entry(table, spec, var)
        r = dict(nk.analyse(p, a), **rails(p))
        rows[f"{spec}:{var}"] = dict(vco_entry=key, code=t["code"], vctrl_table=t["vctrl"], **r)
        print(f"{spec:18s} {var:3s} code {t['code']:2d}: capture {r['capture_s'] * 1e9:6.0f} ns, locked {r['locked_at_end']}, offset {r['offset_s'] * 1e12:6.1f} ps "
              f"(pp {r['e_pp_last_s'] * 1e12:.2f}), Vctrl {r['vctrl_final']:.3f} V (table {t['vctrl']:.3f}), f_out {r['f_out'] / 1e9:.5f} GHz; "
              f"vq {r['vq_mean']:.4f} V pp {r['vq_pp'] * 1e3:.2f} mV, vbias_q {r['vbias_q_mean']:.4f} V pp {r['vbias_q_pp'] * 1e3:.3f} mV", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
