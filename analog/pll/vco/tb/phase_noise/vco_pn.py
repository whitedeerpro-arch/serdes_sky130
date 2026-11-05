"""VCO phase noise from isf.py (impulse responses, gm(t), Id(t)) and device_noise.py (device PSDs).

    uv run python analog/pll/vco/tb/phase_noise/vco_pn.py --isf <campaign> --device <campaign>

Sites per ring: rp 8 (load, thermal), mp 8 (input device: thermal S = 4 k T gamma gm(x), flicker), mt 4 (tail
device: the same).  gamma and the flicker coefficient K(f) are interpolated in Id from the device table, so
the instantaneous current sets both (the input device is off for part of the cycle).  Flicker is fitted per site as
S(f) = K(Id) / f^0.9 around 1 MHz by the table's two points; only the mean response <h alpha> converts it.
Prints L(df) per source.  Noise on the bias line and vctrl is in the PLL synthesis, not here.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from serdes_flow import pnoise, rcorner, spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

OFFS = np.logspace(4, 8, 41)
LVT = "msky130_fd_pr__nfet_01v8_lvt"
REG = "msky130_fd_pr__nfet_01v8"
PROBE = {"mp": (f"@m.xvco.x0.xmp.{LVT}[gm]", f"@m.xvco.x0.xmp.{LVT}[id]"), "mt": (f"@m.xvco.x0.xtail.{REG}[gm]", f"@m.xvco.x0.xtail.{REG}[id]")}


def one_period(w, gm_key, id_key, t_end):
    """gm(x), Id(x) over the cycle (x from a rising crossing), from the settled part before the first pulse."""
    sel = w.t < t_end
    t = w.t[sel]
    y = (w["v(v0p)"] - w["v(v0n)"])[sel]
    e, p = crossings(t, y)
    r = e[p > 0]
    t0, t1 = r[-3], r[-2]
    s = (t >= t0) & (t < t1)
    x = (t[s] - t0) / (t1 - t0)
    return x, np.abs(w[gm_key][sel][s]), np.abs(w[id_key][sel][s])


def source_table(rows):
    i = np.array([r["id"] for r in rows])
    return dict(lid=np.log(i), gamma=np.array([r["gamma"] for r in rows]), lk1=np.log(np.maximum([r["k_1m"] for r in rows], 1e-30)),
                lk100=np.log(np.maximum([r["k_100k"] for r in rows], 1e-30)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--isf", required=True)
    ap.add_argument("--device", required=True)
    a = ap.parse_args()
    camp = ROOT / a.isf
    isf = json.loads((camp / "summary.json").read_text())
    dev = json.loads((ROOT / a.device / "summary.json").read_text())
    T = int(isf["condition"].split("_t")[1]) + 273.15
    per = isf["sites"]["rp"]["period"]
    f0 = 1 / per
    L = {}
    info = {}
    # load resistors
    imp = pnoise.Impulse(np.array(isf["sites"]["rp"]["x"]), np.array(isf["sites"]["rp"]["h"]), per)
    rload = 400 * rcorner.PRESET.get(isf.get("rpdk"), 1.0) * (1 + rcorner.TC1 * (T - 300.15) if isf.get("rpdk") else 1.0)
    L["load R thermal"] = 8 * pnoise.l_white(4 * pnoise.K_B * T / rload, pnoise.white_coefficient(imp), OFFS)
    for site, tab_name, mult, label in (("mp", "in", 8, "input"), ("mt", "tail", 4, "tail")):
        imp = pnoise.Impulse(np.array(isf["sites"][site]["x"]), np.array(isf["sites"][site]["h"]), per)
        w = spice.Waves(camp / site / f"{site}.raw")
        x, gm, idd = one_period(w, *PROBE[site], isf.get("settle", 8e-9) - 0.1e-9)
        o = np.argsort(x)
        x, gm, idd = x[o], gm[o], idd[o]
        tab = source_table(dev["devices"][tab_name])
        lid = np.log(np.maximum(idd, 1e-9))
        gamma = np.interp(lid, tab["lid"], tab["gamma"])
        s_th = 4 * pnoise.K_B * T * gamma * gm                     # one-sided, per device, S(x)
        s0 = float(np.mean(s_th))
        alpha_th = lambda g: np.sqrt(np.interp(g, x, s_th, period=1.0) / s0)
        L[f"{label} thermal"] = mult * pnoise.l_white(s0, pnoise.white_coefficient(imp, alpha_th), OFFS)
        # flicker: K(Id) at 1 MHz, S(f) = K / f with the table's slope between 100 kHz and 1 MHz
        k1 = np.exp(np.interp(lid, tab["lid"], tab["lk1"]))
        k100 = np.exp(np.interp(lid, tab["lid"], tab["lk100"]))
        k0 = float(np.mean(k1))
        alpha_f = lambda g: np.sqrt(np.interp(g, x, k1, period=1.0) / k0)
        mean_h = pnoise.slow_coefficient(imp, alpha_f)
        slope = float(np.log10(np.mean(k100) / k0))                    # K(f) = S f: S ~ K(1M) (f / 1M)^(slope) / f
        s_f = k0 * (OFFS / 1e6) ** (-slope) / OFFS
        L[f"{label} flicker"] = mult * pnoise.l_slow(s_f, mean_h, OFFS)
        info[site] = dict(mean_id_ua=float(np.mean(idd) * 1e6), mean_gm_ms=float(np.mean(gm) * 1e3), s_th=s0, h_eff_rms=float(np.sqrt(pnoise.white_coefficient(imp, alpha_th))),
                          h_rms=float(np.sqrt(pnoise.white_coefficient(imp))), h_mean_f=mean_h, k1m=k0, slope=slope)
    total = sum(L.values())
    pick = [1e5, 1e6, 3e6, 1e7]
    print(f"{isf['condition']}: f0 {f0 / 1e9:.4f} GHz, one-sided L(df) dBc/Hz")
    print(f"  {'source':16s} " + " ".join(f"{p:>9.0e}" for p in pick))
    for k, v in list(L.items()) + [("total", total)]:
        print(f"  {k:16s} " + " ".join(f"{pnoise.dbc(np.interp(p, OFFS, v)):9.1f}" for p in pick))
    for k, v in info.items():
        print(f"  {k}: mean Id {v['mean_id_ua']:.0f} uA, mean gm {v['mean_gm_ms']:.2f} mS, h rms {v['h_rms']:.3e}, with alpha {v['h_eff_rms']:.3e}, flicker <h alpha> {v['h_mean_f']:+.3e}")
    l1m = float(np.interp(1e6, OFFS, total))
    k2 = l1m * 1e12 / f0 ** 2
    print(f"  kappa {np.sqrt(k2):.3e} sqrt(s); one-period jitter {np.sqrt(k2 * per) * 1e12:.3f} ps rms")
    out = dict(isf=a.isf, device=a.device, f0=f0, offsets=OFFS.tolist(), L={k: v.tolist() for k, v in L.items()}, total=total.tolist(), info=info)
    (camp / "phase_noise.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
