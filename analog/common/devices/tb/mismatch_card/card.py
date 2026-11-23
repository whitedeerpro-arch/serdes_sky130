"""Mismatch card (sizing flow, device level): Pelgrom coefficients from the SKY130 statistical models.

    uv run python analog/common/devices/tb/mismatch_card/card.py [--samples 200] [--corner tt] [--seed 1]

One deck, library section <corner>_mm (local mismatch only), serdes_flow.mc: per sample an operating
point of
  MOS pairs   nfet, nfet_lvt, pfet, pfet_lvt at W x L = 1x1, 2x2, 4x4 um, |Vgs| = |Vds| = 0.9 V,
              source and bulk at the rail: BSIM4 operating-point vth of each device
  resistors   high_po w=1 l=2/4/8, w=2 l=8 and xhigh_po w=1 l=4, 0.1 V across: R
  PNP         pnp_05v5_W3p40L3p40 diode-connected (collector, base to ground) at 1 uA: VBE
Per pair the difference (dVth in mV, dR/R in %, dVBE in mV); sigma of the difference, and for MOS the
Pelgrom A_VT of sigma(dVth) = A_VT / sqrt(W L) (pair-difference convention, mV um).  The resistor
model has a body term (1/sqrt(w l)) and a contact-head term (1/sqrt(contact width)), so resistors are
reported per geometry, not fitted.
"""
import argparse
import json
import time

from serdes_flow import mc, spice, stats
from serdes_flow.project import ROOT, model_library

RESULTS = ROOT / "results/analog/common/devices/mismatch_card"
MOS = {"nfet": ("sky130_fd_pr__nfet_01v8", 1), "nfet_lvt": ("sky130_fd_pr__nfet_01v8_lvt", 1),
       "pfet": ("sky130_fd_pr__pfet_01v8", -1), "pfet_lvt": ("sky130_fd_pr__pfet_01v8_lvt", -1)}
SIZES = [(1, 1), (2, 2), (4, 4)]
RES = {"hpo_w1l2": ("sky130_fd_pr__res_high_po", 1, 2), "hpo_w1l4": ("sky130_fd_pr__res_high_po", 1, 4),
       "hpo_w1l8": ("sky130_fd_pr__res_high_po", 1, 8), "hpo_w2l8": ("sky130_fd_pr__res_high_po", 2, 8),
       "xhpo_w1l4": ("sky130_fd_pr__res_xhigh_po", 1, 4)}


def netlist(corner):
    lines = [f"mismatch card ({corner}_mm)", f'.lib "{model_library()}" {corner}_mm',
             "Vn vn 0 0.9", "Vp vp 0 -0.9", "Vr vr 0 0.1"]
    lets = {}
    for dev, (model, sgn) in MOS.items():
        node = "vn" if sgn > 0 else "vp"
        for w, l in SIZES:
            for k in (1, 2):
                name = f"x{dev}_{w}x{l}_{k}"
                lines.append(f"{name} {node} {node} 0 0 {model} w={w} l={l}")
                lets[f"vth_{dev}_{w}x{l}_{k}"] = f"@m.{name}.m{model}[vth]"
    for tag, (model, w, l) in RES.items():
        for k in (1, 2):
            lines += [f"xr_{tag}_{k} vr r_{tag}_{k} 0 {model} w={w} l={l}", f"vm_{tag}_{k} r_{tag}_{k} 0 0"]
            lets[f"r_{tag}_{k}"] = f"0.1/i(vm_{tag}_{k})"
    for k in (1, 2):
        lines += [f"ie{k} 0 e{k} 1u", f"xq{k} 0 0 e{k} sky130_fd_pr__pnp_05v5_W3p40L3p40"]
        lets[f"vbe_{k}"] = f"v(e{k})"
    return "\n".join(lines), lets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--corner", default="tt")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    run = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    net, lets = netlist(a.corner)
    ex = spice.run(mc.deck(net, a.samples, seed=a.seed, lets=lets), run, timeout_s=3600,
                   meta=dict(corner=f"{a.corner}_mm", samples=a.samples, seed=a.seed))
    if not ex.ok:
        raise SystemExit(f"failed: {ex.log_failures[:3]}")
    rows = mc.read(run)
    col = lambda k: mc.column(rows, k)
    out = dict(corner=f"{a.corner}_mm", samples=len(rows), seed=a.seed, mos={}, res={}, pnp={})
    print(f"{len(rows)} samples, {ex.elapsed_s:.0f} s")
    for dev in MOS:
        sig, area = [], []
        for w, l in SIZES:
            d = (col(f"vth_{dev}_{w}x{l}_1") - col(f"vth_{dev}_{w}x{l}_2")) * 1e3
            s = stats.summary(d)
            out["mos"][f"{dev}_{w}x{l}"] = dict(sigma_dvth_mv=s["std"], mean_dvth_mv=s["mean"], skew=s["skew"],
                                                vth_v=float(abs(col(f"vth_{dev}_{w}x{l}_1").mean())))
            sig.append(s["std"]), area.append(w * l)
        a_vt, rel = stats.pelgrom(sig, area)
        out["mos"][f"{dev}_A_VT_mV_um"] = a_vt
        print(f"{dev:9s} sigma(dVth) mV at 1/4/16 um^2: " + " ".join(f"{x:5.2f}" for x in sig) + f"   A_VT {a_vt:.2f} mV.um (fit rms {rel:.0%})")
    for tag in RES:
        r1, r2 = col(f"r_{tag}_1"), col(f"r_{tag}_2")
        d = (r1 - r2) / ((r1 + r2) / 2) * 100
        s = stats.summary(d)
        out["res"][tag] = dict(r_ohm=float(r1.mean()), sigma_dr_pct=s["std"], skew=s["skew"])
        print(f"{tag:10s} R {r1.mean():7.0f} ohm  sigma(dR/R) {s['std']:.2f} %")
    d = (col("vbe_1") - col("vbe_2")) * 1e3
    s = stats.summary(d)
    out["pnp"] = dict(vbe_v=float(col("vbe_1").mean()), sigma_dvbe_mv=s["std"])
    print(f"pnp W3.4  VBE {col('vbe_1').mean():.4f} V  sigma(dVBE) {s['std']:.3f} mV")
    (run / "summary.json").write_text(json.dumps(out, indent=1))
    print(run.relative_to(ROOT))


if __name__ == "__main__":
    main()
