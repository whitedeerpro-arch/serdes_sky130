"""Passive and bipolar card (sizing flow, device level): resistors, MIM capacitor and PNP over corner and temperature.

    uv run python analog/common/devices/tb/passive_card/card.py [--corners tt,ll,hh,ss,ff]

One deck per library section (ll / hh move the resistor and capacitor models, tt / ss / ff the MOS
and bipolar ones); temperatures -40, -10, 27, 55, 85 C in the control block.  Per point:
  R      high_po w=1 l=2 and w=1 l=4, xhigh_po w=1 l=4, generic_po w=1 l=10 at 0.1 V
  C      cap_mim_m3_1 10 x 10 um from the current at 100 MHz
  PNP    pnp_05v5_W3p40L3p40 diode-connected (collector, base to ground) at 1 uA and 8 uA: VBE and
         dVBE = VBE(8 uA) - VBE(1 uA) (= VT ln 8 ideally)
Summary: TC1 / TC2 of every resistor about 27 C, corner spread at 27 C, the MIM density, VBE(T),
dVBE(T) and a first-order bandgap estimate Vbg = VBE(1 uA) + K dVBE with K for zero slope at 27 C
(its curvature over -40..85 C is the second-order error of a plain PNP core).
"""
import argparse
import json
import time

import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT, model_library

RESULTS = ROOT / "results/analog/common/devices/passive_card"
TEMPS = (-40, -10, 27, 55, 85)
RES = {"hpo_w1l2": "sky130_fd_pr__res_high_po w=1 l=2", "hpo_w1l4": "sky130_fd_pr__res_high_po w=1 l=4",
       "xhpo_w1l4": "sky130_fd_pr__res_xhigh_po w=1 l=4"}


def deck(corner):
    lines = [f"passive card ({corner})", f'.lib "{model_library()}" {corner}', "Vr vr 0 0.1"]
    for tag, inst in RES.items():
        lines += [f"xr_{tag} vr r_{tag} 0 {inst}", f"vm_{tag} r_{tag} 0 0"]
    lines += ["xr_gpo vr r_gpo sky130_fd_pr__res_generic_po w=1 l=10", "vm_gpo r_gpo 0 0",
              "Vc vc 0 dc 0 ac 1", "xc vc c0 sky130_fd_pr__cap_mim_m3_1 w=10 l=10", "vm_c c0 0 0",
              "ie1 0 e1 1u", "xq1 0 0 e1 sky130_fd_pr__pnp_05v5_W3p40L3p40",
              "ie8 0 e8 8u", "xq8 0 0 e8 sky130_fd_pr__pnp_05v5_W3p40L3p40", ".control", "set num_threads=1",
              "set wr_vecnames", "set wr_singlescale"]
    for t in TEMPS:
        n = f"{corner}_t{t}"
        lines += [f"option temp={t}", "op"] + [f"let r_{k}=0.1/i(vm_{k})" for k in list(RES) + ["gpo"]] + [
            "let vbe1=v(e1)", "let vbe8=v(e8)",
            f"wrdata {n}_op.tsv " + " ".join(f"r_{k}" for k in list(RES) + ["gpo"]) + " vbe1 vbe8",
            "ac lin 1 1e8 1e8", "let cmim=imag(i(vm_c))/(2*3.141592653589793*1e8)", f"wrdata {n}_ac.tsv cmim",
            "destroy all"]
    return "\n".join(lines + ["quit", ".endc", ".end", ""])


def read(path):
    lines = path.read_text().split("\n")
    names, vals = lines[0].split(), [float(x) for x in lines[1].split()]
    return dict(zip(names, vals))


def tc(t, y):
    """TC1 (1/C) and TC2 (1/C^2) of y(T) = y27 (1 + tc1 dT + tc2 dT^2)."""
    c = np.polyfit(np.asarray(t) - 27.0, y, 2)
    y27 = np.polyval(c, 0.0)
    return float(c[1] / y27), float(c[0] / y27)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corners", default="tt,ll,hh,ss,ff")
    a = ap.parse_args()
    corners = a.corners.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(c), camp / c, dict(timeout_s=1200, meta=dict(corner=c))) for c in corners]
    for ex in spice.run_many(jobs, workers=4, smoke=False):
        if not ex.ok:
            raise SystemExit(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}")
    data = {}
    for c in corners:
        data[c] = {t: {**read(camp / c / f"{c}_t{t}_op.tsv"), **read(camp / c / f"{c}_t{t}_ac.tsv")} for t in TEMPS}
    out = dict(temps=TEMPS, corners=corners, res={}, mim={}, pnp={})
    print("resistors: R(27 C) per corner, TC1 [ppm/C] / TC2 [ppm/C^2] at tt")
    for k in list(RES) + ["gpo"]:
        r27 = {c: data[c][27][f"r_{k}"] for c in corners}
        t1, t2 = tc(TEMPS, [data["tt"][t][f"r_{k}"] for t in TEMPS])
        out["res"][k] = dict(r27=r27, tc1=t1, tc2=t2)
        print(f"  {k:10s} " + " ".join(f"{c} {r27[c]:8.1f}" for c in corners) + f"   TC1 {t1 * 1e6:7.0f}  TC2 {t2 * 1e6:6.2f}")
    m27 = {c: data[c][27]["cmim"] for c in corners}
    out["mim"] = dict(c27_f=m27, density_f_per_um2={c: v / 100 for c, v in m27.items()})
    print("MIM 10x10 um: " + " ".join(f"{c} {v * 1e15:.1f} fF" for c, v in m27.items()))
    print("PNP: VBE(1 uA) / dVBE(8:1) mV over T, per corner")
    for c in corners:
        vbe = np.array([data[c][t]["vbe1"] for t in TEMPS])
        dv = np.array([data[c][t]["vbe8"] - data[c][t]["vbe1"] for t in TEMPS])
        s_vbe, s_dv = np.polyfit(TEMPS, vbe, 1)[0], np.polyfit(TEMPS, dv, 1)[0]
        k = -s_vbe / s_dv
        vbg = vbe + k * dv
        out["pnp"][c] = dict(vbe=vbe.tolist(), dvbe=dv.tolist(), dvbe_ideal=[8.617e-5 * (t + 273.15) * np.log(8) for t in TEMPS],
                             k=float(k), vbg=vbg.tolist(), vbg_span_mv=float(np.ptp(vbg) * 1e3))
        print(f"  {c}: VBE " + " ".join(f"{v:.4f}" for v in vbe) + "  dVBE " + " ".join(f"{v * 1e3:.2f}" for v in dv)
              + f"  K {k:.2f}  Vbg {np.mean(vbg):.4f} V, span {np.ptp(vbg) * 1e3:.1f} mV")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
