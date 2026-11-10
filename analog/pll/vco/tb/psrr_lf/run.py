"""Supply tone to the 4-bit VCO's frequency through the real k = 4 loop filter (PLL closure step 7).

    uv run python analog/pll/vco/tb/psrr_lf/run.py [--points tt_v1800_t27:tt,...] [--variants lf,gnd,vdd] [--freqs 20e6]
        [--lf50] [--amp 5e-3] [--lf-cell pll_loop_filter_k4] [--cp "<pll_cp_steer params>"] [--iamp 1e-6] [--workers 2]
        [--analyse C]

4-bit ring (vco_ring4_4b + cap_bank_4b) with its four buffers, real bias and PDK resistors (the workmap / ISF bench), at
the code-table code and Vctrl of each point (config/pll_code_table.json).  VDD carries a sine of --amp from 12 ns on;
the set code bits follow VDD.  Variants:
  lf   the control node is the real pll_loop_filter_k4 (Rz 4.13 k, 12 MIM units to VDD and 6 to ground, precharge
       gates off) with the k = 4 steering CP attached and both switches off (its output capacitance and leakage, real
       bias); a 100 MOhm resistor to a DC source sets the operating point (1.8 ms against 18 pF: open at the tone).
       Above the loop bandwidth this is what the VCO sees; the loop's own high-pass is applied separately
       (analog/pll/top/theory/supply_tolerance.py).
  gnd  ideal Vctrl source (alpha 0: control fixed to ground),  vdd  ideal Vctrl carrying the tone (alpha 1).
  zin  as lf but VDD clean and a sine current of --iamp at fm injected into the control node: the impedance the CP
       drives, Z = V(ctrl) / I by lock-in over the kept periods (the loop's own Z(f), incl. everything on the node).
Fit as psrr_tone.py: K = w f0 (B - j A) / amp from the rising crossings after one dropped period.  gnd and vdd at the
same point give the control line's gain and the alpha that nulls K; lf gives the actual K and, through
K_lf = K_gnd + alpha_eff (K_vdd - K_gnd), the effective alpha of the real network.
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
_w = importlib.util.spec_from_file_location("vco_workmap", ROOT / "analog/pll/vco/tb/tuning/workmap.py")
wm = importlib.util.module_from_spec(_w)
_w.loader.exec_module(wm)
_p = importlib.util.spec_from_file_location("psrr_tone", ROOT / "analog/pll/vco/tb/phase_noise/psrr_tone.py")
pt = importlib.util.module_from_spec(_p)
_p.loader.exec_module(pt)
RESULTS = ROOT / "results/analog/pll/vco/psrr_lf"
TABLE = ROOT / "config/pll_code_table.json"
POINTS = "tt_v1800_t27:tt,sf_v1650_t85:hh,ff_v1950_t-40:ll,fs_v1950_t85:hh,ss_v1650_t85:hh,fs_v1650_t85:hh,ss_v1650_t-40:hh"
CP_PARAMS = "wn=20 wp=80 wsn=8 wsp=16 up_wn=2 up_wp=8 dn_wn=4 dn_wp=8 pnf=16 nnf=4 ntail=2 cdum=0.3p"
SETTLE = 12e-9
INCLUDES = ["analog/common/devices/spice/sky130_pfet_lvt.spice", "analog/common/devices/spice/cmos_logic.spice",
            "analog/pll/cp/spice/charge_pump.spice", "analog/pll/cp/spice/charge_pump_steer.spice",
            "analog/pll/loop_filter/spice/passive_rc_precharge.spice", "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice"]
LF_BLOCK = """* real loop filter + steering CP (switches off) on the control node; DC through 100 MOhm
Vup up 0 0
Vdn dn 0 0
Vbcp vbcp 0 {supply}
Incp vbcp vbn 50u
Ipcp vbp 0 50u
Xbncp vbn vbn 0 0 serdes_nfet w=5 l=1
Xbpcp vbp vbp vdd vdd serdes_pfet w=20 l=1 nf=4
Xcp up dn cpo vbn vbp ibcp vdd 0 pll_cp_steer {cp}
Xlf cpo ctrl z pre_ref pre_en vdd 0 {lf}
Vpre pre_ref 0 {v}
Ven pre_en 0 0
"""


def done(d):
    """A run that ended normally (execution.json written with exit 0 and its waveform present)."""
    e = d / "execution.json"
    if not (e.exists() and (d / "tone.raw").exists()):
        return False
    return json.loads(e.read_text()).get("exit_code") == 0


def latest(camp, cond, rc, var, fm):
    """The completed run directory of a plan point (the original or a re-run)."""
    base = camp / f"{cond}_{rc}"
    cands = sorted(base.glob(name(var, fm) + "*")) if base.exists() else []
    good = [d for d in cands if d.is_dir() and done(d)]
    return good[-1] if good else None


def zin(d, fm, periods, iamp):
    """Z = V(ctrl) / I_inj at fm: lock-in over the kept periods (the first after SETTLE dropped)."""
    w = spice.Waves(d / "tone.raw")
    t, v = np.asarray(w.t), np.asarray(w["v(ctrl)"])
    sel = (t >= SETTLE + 1 / fm) & (t <= SETTLE + (periods + 1) / fm)
    t, v = t[sel], v[sel]
    ph = 2 * np.pi * fm * (t - SETTLE)
    span = t[-1] - t[0]
    x = 2 / span * np.trapezoid(v * np.cos(ph), t)
    y = 2 / span * np.trapezoid(v * np.sin(ph), t)
    return (y + 1j * x) / iamp                                  # i = iamp sin(ph): V phasor (x - j y) over (-j iamp)


def name(variant, fm):
    return f"{variant}_{fm / 1e6:g}M"


def deck(c, rc, code, vctrl, variant, fm, amp, stop, camp, lf_cell="pll_loop_filter_k4", cp=CP_PARAMS, iamp=1e-6):
    loaded = variant in ("lf", "zin")
    text = spice.render(wm.TEMPLATE, **spice.corner_values(c), VCTRL=vctrl, INJECT="", PROBES="v(ctrl)" + (" v(z)" if loaded else ""),
                        TSTEP="1p", STOP=f"{stop:.5e}", SAVE_FROM=f"{SETTLE:.5e}", OUT="tone.raw", CFG0=0, CFG1=0, CFG2=0)
    old = "ctrl cfg0 cfg1 cfg2 vbias vdd 0 pll_vco_ring4_pvt_candidate"
    assert text.count(old) == 1
    text = text.replace(old, "ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd 0 pll_vco_ring4_4b").replace("Vb2 cfg2 0 0\n", "Vb2 cfg2 0 0\nVb3 cfg3 0 0\n")
    inc = '.include "' + str(ROOT / "analog/pll/vco/spice/vco_ring4_pvt_candidate.spice") + '"'
    assert text.count(inc) == 1
    extra = [inc.replace("analog/pll/vco/spice/vco_ring4_pvt_candidate.spice", f) for f in INCLUDES]
    text = text.replace(inc, "\n".join([inc.replace("vco_ring4_pvt_candidate", "cap_bank_4b"), inc.replace("vco_ring4_pvt_candidate", "vco_ring4_4b")] + extra))
    rep = {} if variant == "zin" else {f"Vdd vdd 0 {c.supply}": f"Vdd vdd 0 DC {c.supply} SIN({c.supply} {amp:.5e} {fm:.5e} {SETTLE:.5e})"}
    for k in range(4):                                         # a set bit is tied to VDD, a clear bit to ground
        rep[f"Vb{k} cfg{k} 0 0"] = f"Vb{k} cfg{k} vdd 0" if (code >> k) & 1 else f"Vb{k} cfg{k} 0 0"
    if loaded:
        rep[f"Vctrl ctrl 0 {vctrl}"] = LF_BLOCK.format(supply=c.supply, cp=cp, v=vctrl, lf=lf_cell)
        if variant == "zin":
            rep[f"Vctrl ctrl 0 {vctrl}"] += f"Iinj 0 ctrl DC 0 SIN(0 {iamp:.5e} {fm:.5e} {SETTLE:.5e})\n"
    elif variant == "vdd":
        rep[f"Vctrl ctrl 0 {vctrl}"] = f"Vctrl ctrl 0 DC {vctrl} SIN({vctrl} {amp:.5e} {fm:.5e} {SETTLE:.5e})"
    for o, n in rep.items():
        assert text.count(o) == 1, o
        text = text.replace(o, n)
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, rc)
    if loaded:
        hold = f"XIbcp ibcp vgi_bias vdd serdes_bias_pcopy n=4\nRhold ctrl hold 100Meg\nVhold hold 0 {vctrl}\n"
        text = text.replace(".control", hold + ".control", 1)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default=POINTS)
    ap.add_argument("--variants", default="lf,gnd,vdd")
    ap.add_argument("--freqs", default="20e6")
    ap.add_argument("--lf50", action="store_true", help="also the lf variant at 50 MHz")
    ap.add_argument("--amp", type=float, default=5e-3)
    ap.add_argument("--lf-cell", default="pll_loop_filter_k4", help="loop-filter subcircuit for the lf variant (pll_loop_filter_k4_s7: 7 / 11 split)")
    ap.add_argument("--cp", default=CP_PARAMS, help="pll_cp_steer parameters on the control node (lf / zin)")
    ap.add_argument("--iamp", type=float, default=1e-6, help="zin: injected current amplitude, A")
    ap.add_argument("--periods", type=int, default=2)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--analyse")
    ap.add_argument("--resume", help="campaign to continue: runs without a clean execution.json are redone")
    a = ap.parse_args()
    table = json.loads(TABLE.read_text())["table"]
    camp = ROOT / (a.analyse or a.resume) if (a.analyse or a.resume) else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    plan = []
    for spec in a.points.split(","):
        cond, rc = spec.split(":")
        row = table[spec]
        for fm in (float(x) for x in a.freqs.split(",")):
            plan += [(cond, rc, row["code"], row["vctrl"], v, fm) for v in a.variants.split(",")]
        if a.lf50:
            plan.append((cond, rc, row["code"], row["vctrl"], "lf", 50e6))
    if not a.analyse:
        jobs = []
        for cond, rc, code, v, var, fm in plan:
            c = Condition.parse(cond)
            stop = SETTLE + (a.periods + 1) / fm + 1e-9
            d = camp / f"{cond}_{rc}" / name(var, fm)
            if done(d):
                continue
            if d.exists():                                      # interrupted: keep it, run again beside it
                d = spice.next_run_dir(camp / f"{cond}_{rc}", name(var, fm))
            jobs.append((deck(c, rc, code, v, var, fm, a.amp, stop, camp / "snap" / f"{cond}_{rc}_{name(var, fm)}", a.lf_cell, a.cp, a.iamp), d,
                         dict(timeout_s=3600, meta=dict(point=f"{cond}:{rc}", code=code, vctrl=v, variant=var, fm=fm, amp=a.amp, lf_cell=a.lf_cell,
                                                        cp=a.cp, iamp=a.iamp))))
        for ex in spice.run_many(jobs, workers=a.workers, smoke=True):
            if not ex.ok:
                print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)
    rows = {}
    print(f"tone {a.amp * 1e3:.1f} mV on VDD; K in MHz/V (real = in phase with VDD, quad = 90 deg)")
    print(f"{'point':24s} {'code':>4s} {'Vctrl':>6s} {'var':>4s} {'f MHz':>6s} {'f0 GHz':>8s} {'K real':>8s} {'K quad':>8s} {'|K|':>7s}")
    for cond, rc, code, v, var, fm in plan:
        d = latest(camp, cond, rc, var, fm)
        if d is None:
            continue
        if var == "zin":
            z = zin(d, fm, a.periods, a.iamp)
            rows[f"{cond}:{rc}:{name(var, fm)}"] = dict(z_real=float(z.real), z_imag=float(z.imag), code=code, vctrl=v)
            print(f"{cond + ':' + rc:24s} {code:4d} {v:6.3f} {var:>4s} {fm / 1e6:6.1f}   Z {abs(z) / 1e3:7.3f} kOhm at {np.degrees(np.angle(z)):6.1f} deg", flush=True)
            continue
        q = pt.fit(d, fm, SETTLE)
        k = 2 * np.pi * fm * q["f0"] * (q["cos"] - 1j * q["sin"]) / a.amp
        rows[f"{cond}:{rc}:{name(var, fm)}"] = dict(q, k_real=float(k.real), k_quad=float(k.imag), k_abs=float(abs(k)), code=code, vctrl=v)
        print(f"{cond + ':' + rc:24s} {code:4d} {v:6.3f} {var:>4s} {fm / 1e6:6.1f} {q['f0'] / 1e9:8.4f} {k.real / 1e6:8.1f} {k.imag / 1e6:8.1f} {abs(k) / 1e6:7.1f}", flush=True)
    for spec in a.points.split(","):
        for fm in (float(x) for x in a.freqs.split(",")):
            g, h, l = (rows.get(f"{spec}:{name(x, fm)}") for x in ("gnd", "vdd", "lf"))
            if g and h:
                kg, kh = complex(g["k_real"], g["k_quad"]), complex(h["k_real"], h["k_quad"])
                line = f"  {spec} {fm / 1e6:g} MHz: control line |K| {abs(kh - kg) / 1e6:.0f} MHz/V, null alpha {(-(kg * (kh - kg).conjugate()).real / abs(kh - kg) ** 2):.3f}"
                if l:
                    kl = complex(l["k_real"], l["k_quad"])
                    line += f"; real LF |K| {abs(kl) / 1e6:.0f} MHz/V, effective alpha {((kl - kg) / (kh - kg)).real:.3f}"
                print(line)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), cp=CP_PARAMS, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
