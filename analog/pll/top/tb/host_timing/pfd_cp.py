"""Host sensitivity of the PFD + k = 4 steering CP balance point (HV18 configuration: PFD on host, CP on quiet 1.8 V).

    uv run python analog/pll/top/tb/host_timing/pfd_cp.py [--points tt_v1800_t27:tt,...] [--dh 0.02] [--workers 2] [--resume C]

The locked loop's share of the PFD: the zero-charge phase (static offset) of PFD + CP, as in analog/pll/pfd/tb/pfd_cp_mc
(nominal models, no mismatch), with the PFD and the ref / fb drivers (swing 0..vh, 30 ps edges) on the host source vh,
the CP and its vbp diode on an ideal quiet 1.8 V, CP output held at the code table's 1.8 V Vctrl, real bias on an
unperturbed vdd.  Three transients: vh = supply, +-dh.  Kd_pfd = d(zero-charge phase) / d(vh), s/V (phase = fb edge
minus ref edge at zero net charge).  Locked, t_vco = t_ref + zero phase - (VCO -> fb0 delay), so the VCO edge moves by
Kd_pfd - Kd_h per volt of host (Kd_h from host_timing/run.py).
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_m = importlib.util.spec_from_file_location("pfd_cp_mc", ROOT / "analog/pll/pfd/tb/pfd_cp_mc/run.py")
pm = importlib.util.module_from_spec(_m)
_m.loader.exec_module(pm)
RESULTS = ROOT / "results/analog/pll/top/host_timing_pfd_cp"
INCLUDES = ["analog/common/devices/spice/sky130_primitives.spice", "analog/common/devices/spice/sky130_pfet_lvt.spice",
            "analog/common/devices/spice/cmos_logic.spice", "analog/common/devices/spice/cmos_dff_reset.spice",
            "analog/pll/pfd/spice/cmos_dff_reset.spice", "analog/pll/pfd/spice/pfd_cmos.spice",
            "analog/pll/cp/spice/charge_pump.spice", "analog/pll/cp/spice/charge_pump_steer.spice"]
VQ = 1.8


def deck(c, rc, vout, dh, camp):
    t, ph = pm.edges()
    tend = t[-1] + pm.TREF
    lines = ["PFD on host + steering CP on quiet: balance point versus host", f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in INCLUDES]
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vh vh 0 {supply}", f"Vq vq 0 {VQ}",
              "In vb vbn 50u", "Ip vbp 0 50u", "Xbn vbn vbn 0 0 serdes_nfet w=5 l=1", "Xbp vbp vbp vq vq serdes_pfet w=20 l=1 nf=4",
              f"Vrefi refi 0 PWL({pm.pwl(t, [0.0] * len(t), 1.0)})", f"Vfbi fbi 0 PWL({pm.pwl(t, ph, 1.0)})",
              "Bref ref 0 V=v(refi)*v(vh)", "Bfb fb 0 V=v(fbi)*v(vh)", "Erst rst_b 0 vh 0 1",
              "Xpfd ref fb rst_b up dn vh 0 pll_pfd", "Cup up 0 20f", "Cdn dn 0 20f",
              f"Xcp up dn out vbn vbp ibuf vq 0 pll_cp_steer {pm.CP_PARAMS}", "Ibuf vdd ibuf 10u", f"Vout out 0 {vout:.4f}",
              f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u", ".save i(vout) v(up) v(dn)", ".control", "set num_threads=1"]
    for name, d in (("base", 0.0), ("hp", dh), ("hm", -dh)):
        lines += [f"alter Vh dc={c.supply + d:.4f}", f"tran 1p {tend:.5e} 0 5p", f"wrdata {name}.tsv i(vout) v(up) v(dn)", "destroy all"]
    lines += ["quit", ".endc", ".end"]
    text = bias.real(spice.binary_output("\n".join(lines) + "\n"))
    old = "Ibuf vdd ibuf 10u"
    assert text.count(old) == 1
    text = text.replace(old, "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc), tend


def zero_phase(path):
    """Net charge per period at each phase, and the interpolated zero-charge phase (s)."""
    w = spice.Waves(path)
    t = np.asarray(w.t)
    i = np.asarray(w[[n for n in w.names if n.lower().startswith("i(")][0]])
    te, _ = pm.edges()
    q = []
    for k in range(len(pm.PHASES)):
        e = te[pm.WARM + k]
        s = (t >= e - 0.5e-9) & (t <= e + 3.5e-9)
        q.append(float(np.trapezoid(i[s], t[s])))
    q, ph = np.array(q), np.array(pm.PHASES)
    j = np.where(np.diff(np.sign(q)) != 0)[0]
    if len(j):
        j = j[0]
        z = float(np.interp(0.0, q[j:j + 2] if q[j] < q[j + 1] else q[j:j + 2][::-1], ph[j:j + 2] if q[j] < q[j + 1] else ph[j:j + 2][::-1]))
    else:
        a, b = np.polyfit(ph, q, 1)
        z = float(-b / a)
    return z, q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="tt_v1800_t27:tt,fs_v1650_t85:hh,ss_v1650_t-40:hh,fs_v1950_t-40:hh,ss_v1650_t85:hh,ff_v1950_t-40:ll")
    ap.add_argument("--dh", type=float, default=0.02)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--resume")
    a = ap.parse_args()
    table = json.loads((ROOT / "config/pll_code_table.json").read_text())["table"]
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    specs = a.points.split(",")

    def entry(spec):
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        return c, rc, table[f"{c.process}_v1800_t{c.temp}:{rc}"]

    jobs = []
    for spec in specs:
        c, rc, e = entry(spec)
        d = camp / spec.replace(":", "_")
        text, tend = deck(c, rc, e["vctrl"], a.dh, camp / "snap")
        if spice.case_output(d, "run", "hm.raw", tend) is not None:
            continue
        jobs.append((text, spice.next_run_dir(d, "run"), dict(timeout_s=3600, meta=dict(point=spec, vctrl=e["vctrl"], dh=a.dh))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    rows = {}
    for spec in specs:
        c, rc, e = entry(spec)
        d = camp / spec.replace(":", "_")
        _, tend = deck(c, rc, e["vctrl"], a.dh, camp / "snap")
        z = {}
        for name in ("base", "hp", "hm"):
            p = spice.case_output(d, "run", f"{name}.raw", tend)
            if p is None:
                break
            z[name] = zero_phase(p)
        if len(z) < 3:
            print(f"{spec}: missing")
            continue
        kd = (z["hp"][0] - z["hm"][0]) / (2 * a.dh)
        gain = (z["base"][1][pm.PHASES.index(5e-12)] - z["base"][1][pm.PHASES.index(-5e-12)]) / 10e-12
        rows[spec] = dict(vctrl=e["vctrl"], zero_s={k: v[0] for k, v in z.items()}, kd_pfd=kd, gain_a=float(gain),
                          q_fc={k: [float(x * 1e15) for x in v[1]] for k, v in z.items()})
        print(f"{spec:18s} Vout {e['vctrl']:.3f}: zero phase {z['base'][0] * 1e12:+6.2f} ps (hp {z['hp'][0] * 1e12:+6.2f}, hm {z['hm'][0] * 1e12:+6.2f}), "
              f"Kd_pfd {kd * 1e9:+.4f} ps/mV, gain {gain * 1e6:.0f} uA", flush=True)
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), phases=pm.PHASES, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
