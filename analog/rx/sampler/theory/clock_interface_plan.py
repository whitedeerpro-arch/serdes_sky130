"""Plan the RX sampler clock interface: low-overdrive tails + AC-coupled clocks (behavioural model).

    uv run python analog/rx/sampler/theory/clock_interface_plan.py [--measure-cg]

Element constraints (measured, not designed here):
  * clock common-mode window of the low-overdrive sample DFF per condition and clock amplitude
    (headroom_op/window.py --bias vbias_logic, campaigns found by their summary metadata);
  * clock-net capacitance at 2 GHz (4 clock gates per net, both DFF states; --measure-cg reruns it);
  * PI output swing over the stress corners (pi/tb/rotation/pvt.py campaign).
Behavioural interface model per clock net:
  PI output (single-ended peak a_pi) -> driver -> coupling capacitor Cc -> clock gates Cg,
  gates biased through Rb from a divider at k * VDD (p and n share the divider node).
  a_gate = A_drv(a_pi) / sqrt(1 + (w Rout C_drv)^2) * Cc / (Cc + Cg),  C_drv = Cc Cg/(Cc+Cg) + 0.1 Cc + 20 fF
  driver "sf": the existing LVT source follower, low-frequency gain 0.9, Rout 204 ohm at 340 uA
    (calibrated: 314/366 mVpp TT ratio with the stock W32 load), Rout ~ 1/sqrt(I);
  driver "cml": one CML buffer per clock pair, gm = I / 0.15 V, output limited to I R / 2 peak.
  Calibration (2026-11-01, sizing iteration 1): built as rx_half_rate_samples_ac, the 300 ohm / 1 mA
  buffer gives ~1.27 at 2 GHz against ~2 here; the TT device card puts its DC gm R at 2.24, so the
  missing pieces are the output pole and large-signal compression, not gm (docs/verification/sizing.md).
  The AC coupling makes the gate common mode k * VDD regardless of the driver's level, and removes
  static upstream offsets from the clock (their duty-cycle error) along with it.
Constraints: gate amplitude 75 mV single-ended peak (300 mVpp diff) at every stress corner,
<= 160 mV (the measured window range); common-mode margin >= 50 mV in all 45 conditions over the
design's amplitude range; high-pass corner of Rb (Cc + Cg) <= 20 MHz (1/100 of the clock: phase shift < 0.6 deg).  Cost: added clock power,
MIM area (2 fF/um^2).  Output: results/analog/rx/sampler/clock_interface_plan/<ts>/.
"""
import argparse
import itertools
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

WINDOWS = ROOT / "results/analog/rx/sampler/clock_cm_window"
PI_SWING = ROOT / "results/analog/rx/pi/rotation_pvt/20261031T183256Z/summary.json"
RESULTS = ROOT / "results/analog/rx/sampler/clock_interface_plan"
W = 2 * np.pi * 2e9
A_MIN, A_MAX, CM_MARGIN = 0.075, 0.16, 0.05
RB = 50e3
MIM_F_PER_UM2 = 2e-15
NETS = 4                                    # data p/n, edge p/n
CG_PROBE = ["tt_v1650_t27", "ss_v1650_t85", "fs_v1650_t-40", "ff_v1950_t-40"]
CG_DECK = """clock-net capacitance of two half-rate DFFs
.lib "{lib}" {corner}
.include "{root}/analog/common/devices/spice/sky130_primitives.spice"
.include "{root}/analog/pll/divider/spice/cml_latch.spice"
.include "{root}/analog/rx/sampler/spice/rx_sample_dff.spice"
.include "{root}/analog/pll/divider/spice/cml_div2.spice"
Vdd vdd 0 {v}
Vref vref 0 {v}
Iref vref vbias .85m
Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4
Xlb vbias vbias_logic vdd 0 pll_cml_tail_bias
Bdp dp 0 V=v(vdd)-0.147+0.05
Bdn dn 0 V=v(vdd)-0.147-0.05
Vcp cp 0 dc {hi} ac 1
Vcn cn 0 dc {lo}
Xd0 dp dn cp cn q0p q0n vbias_logic vdd 0 serdes_rx_sample_dff wtail=72 nftail=24 wclock={wclock}
Xd1 dp dn cn cp q1p q1n vbias_logic vdd 0 serdes_rx_sample_dff wtail=72 nftail=24 wclock={wclock}
.temp {t}
.control
ac lin 1 2g 2g
let c=imag(-i(Vcp))/(2*3.14159265358979*2e9)
print c
quit
.endc
.end
"""


def measure_cg(camp):
    jobs = []
    for tag, wclock, (hi, lo) in itertools.product(CG_PROBE, (32, 64), ((1.12, 0.92), (0.92, 1.12))):
        c = Condition.parse(tag)
        cv = spice.corner_values(c)
        d = CG_DECK.format(lib=cv["MODEL_LIBRARY"], corner=c.process, root=ROOT, v=c.supply, t=c.temp, hi=hi, lo=lo, wclock=wclock)
        jobs.append((d, camp / "cg" / f"{tag}_w{wclock}_{'high' if hi > lo else 'low'}", dict(meta=dict(condition=tag, wclock=wclock))))
    out = {32: [], 64: []}
    for ex in spice.run_many(jobs, workers=4, smoke=False):
        line = [l for l in (ex.run_dir / "simulator.log").read_text().splitlines() if l.strip().startswith("c =")][0]
        out[json.loads((ex.run_dir / "execution.json").read_text())["wclock"]].append(spice.spice_number(line.split("=")[1]))
    return {w: dict(min=min(v), max=max(v)) for w, v in out.items()}


CG_DEFAULT = {32: dict(min=63.4e-15, max=141.3e-15), 64: dict(min=136.2e-15, max=259.3e-15)}   # --measure-cg, 2026-11-01


def load_windows():
    """{wclock: {ck_half: {condition: (lo, hi, supply)}}} from the low-overdrive window campaigns."""
    out = {}
    for s in sorted(WINDOWS.glob("*/summary.json")):
        d = json.loads(s.read_text())
        if d.get("bias") != "vbias_logic":
            continue
        wclock = int(d["dff"].get("wclock", 32))
        out.setdefault(wclock, {})[round(d["ck_half_v"], 3)] = {r["condition"]: (r["lo_v"], r["hi_v"], r["supply"]) for r in d["rows"]}
    return out


def window_at(win, cond, a):
    hs = sorted(win)
    lo = np.interp(a, hs, [win[h][cond][0] for h in hs])
    hi = np.interp(a, hs, [win[h][cond][1] for h in hs])
    return lo, hi, win[hs[0]][cond][2]


def best_k(win, a_lo, a_hi):
    conds = list(next(iter(win.values())))
    ks = np.linspace(0.4, 0.85, 901)
    margin = np.full_like(ks, np.inf)
    for c in conds:
        for a in (a_lo, a_hi):
            lo, hi, v = window_at(win, c, a)
            margin = np.minimum(margin, np.minimum(ks * v - lo, hi - ks * v))
    i = int(np.argmax(margin))
    return float(ks[i]), float(margin[i])


def gate_amplitude(a_pi, drv, cc, cg):
    c_drv = cc * cg / (cc + cg) + 0.1 * cc + 20e-15
    if drv["kind"] == "sf":
        a, rout = 0.9 * a_pi, 204.0 * np.sqrt(340e-6 / drv["i"])
    else:
        a, rout = min(drv["i"] / 0.15 * drv["r"] * a_pi, drv["i"] * drv["r"] / 2), drv["r"]
    return a / np.sqrt(1 + (W * rout * c_drv) ** 2) * cc / (cc + cg)


DRIVERS = [dict(kind="sf", i=340e-6, label="SF 340 uA (existing)"), dict(kind="sf", i=680e-6, label="SF 680 uA"),
           dict(kind="cml", r=400, i=0.75e-3, label="CML 400 ohm 0.75 mA"), dict(kind="cml", r=300, i=1.0e-3, label="CML 300 ohm 1 mA"),
           dict(kind="cml", r=300, i=1.5e-3, label="CML 300 ohm 1.5 mA"), dict(kind="cml", r=200, i=1.5e-3, label="CML 200 ohm 1.5 mA")]
CC = [0.2e-12, 0.3e-12, 0.4e-12, 0.6e-12, 0.8e-12, 1.0e-12, 1.5e-12]


def power(drv, vdd=1.8):
    n = NETS if drv["kind"] == "sf" else NETS // 2
    return n * drv["i"] * vdd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--measure-cg", action="store_true")
    a = ap.parse_args()
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    cg = measure_cg(camp) if a.measure_cg else CG_DEFAULT
    wins = load_windows()
    a_pi = {r["condition"]: r["swing_min_v"] / 4 for r in json.loads(PI_SWING.read_text())}
    rows = []
    for wclock, drv, cc in itertools.product(sorted(wins), DRIVERS, CC):
        amps = [gate_amplitude(x, drv, cc, cg[wclock]["max"]) for x in a_pi.values()]
        amps += [gate_amplitude(x, drv, cc, cg[wclock]["min"]) for x in a_pi.values()]
        a_lo, a_hi = min(amps), max(amps)
        k, m = best_k(wins[wclock], max(a_lo, 0.05), min(a_hi, 0.16))
        f_hp = 1 / (2 * np.pi * RB * (cc + cg[wclock]["max"]))
        ok = a_lo >= A_MIN and a_hi <= A_MAX and m >= CM_MARGIN and f_hp <= 20e6
        rows.append(dict(wclock=wclock, driver=drv["label"], cc_pf=cc * 1e12, a_gate_min_mv=a_lo * 1e3, a_gate_max_mv=a_hi * 1e3,
                         k=k, cm_margin_mv=m * 1e3, f_hp_mhz=f_hp / 1e6, p_drv_mw=power(drv) * 1e3,
                         mim_um2=NETS * cc / MIM_F_PER_UM2, ok=bool(ok)))
    feas = sorted((r for r in rows if r["ok"]), key=lambda r: (r["p_drv_mw"], r["mim_um2"]))
    (camp / "plan.json").write_text(json.dumps(dict(cg_f=cg, a_pi_v=a_pi, rb_ohm=RB, gates=dict(a_min_v=A_MIN, a_max_v=A_MAX, cm_margin_v=CM_MARGIN),
                                                    rows=rows, feasible=feas), indent=1))
    print("clock-net capacitance (fF): " + ", ".join(f"W{w} {v['min']*1e15:.0f}..{v['max']*1e15:.0f}" for w, v in cg.items()))
    print("45-condition CM window, low-overdrive tails (V): " + "; ".join(
        f"W{w} A={h*1e3:.0f}mV {max(x[0] for x in d.values()):.3f}..{min(x[1] for x in d.values()):.3f}"
        for w in sorted(wins) for h, d in sorted(wins[w].items())))
    print(f"\n{'wclk':4s} {'driver':22s} {'Cc pF':>5s} | gate amp mV min..max | k     CM margin mV | f_hp MHz | P_drv mW | MIM um2 | ok")
    for r in rows:
        if r["cc_pf"] in (0.3, 0.6, 1.0):
            print(f"W{r['wclock']:<3d} {r['driver']:22s} {r['cc_pf']:5.1f} | {r['a_gate_min_mv']:5.0f}..{r['a_gate_max_mv']:5.0f}        | "
                  f"{r['k']:.3f} {r['cm_margin_mv']:6.0f}     | {r['f_hp_mhz']:6.2f}   | {r['p_drv_mw']:6.2f}   | {r['mim_um2']:5.0f}   | {'yes' if r['ok'] else ''}")
    print("\nfeasible, cheapest first:")
    for r in feas[:8]:
        print(f"  W{r['wclock']} {r['driver']:22s} Cc {r['cc_pf']:.1f} pF: gate {r['a_gate_min_mv']:.0f}..{r['a_gate_max_mv']:.0f} mV, "
              f"k {r['k']:.3f} (margin {r['cm_margin_mv']:.0f} mV), P {r['p_drv_mw']:.2f} mW, MIM {r['mim_um2']:.0f} um2")
    # figure: per-condition window at the chosen design's amplitude range and the k*VDD law
    if feas:
        ch = feas[0]
        win = wins[ch["wclock"]]
        conds = list(next(iter(win.values())))
        fig, axs = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)
        ax = axs[0]
        for i, c in enumerate(conds):
            lo = max(window_at(win, c, a)[0] for a in (max(ch["a_gate_min_mv"] / 1e3, .05), ch["a_gate_max_mv"] / 1e3))
            hi = min(window_at(win, c, a)[1] for a in (max(ch["a_gate_min_mv"] / 1e3, .05), ch["a_gate_max_mv"] / 1e3))
            v = win[min(win)][c][2]
            ax.plot([i, i], [lo, hi], color="#2a78d6", lw=4, solid_capstyle="butt")
            ax.plot(i, ch["k"] * v, "o", color="#eb6834", ms=4)
        ax.set_xticks(range(len(conds)))
        ax.set_xticklabels(conds, rotation=90, fontsize=6)
        ax.set_ylabel("clock common mode at the latch (V)")
        ax.set_title(f"W{ch['wclock']} low-overdrive DFF: feasible clock CM (bars) vs {ch['k']:.3f} x VDD (dots)", fontsize=9)
        ax = axs[1]
        for drv, col in zip(DRIVERS, ["#2a78d6", "#1baf7a", "#eda100", "#eb6834", "#e87ba4", "#6250d6"]):
            ccs = np.linspace(0.1e-12, 1.5e-12, 60)
            ax.plot(ccs * 1e12, [gate_amplitude(min(a_pi.values()), drv, x, cg[ch["wclock"]]["max"]) * 1e3 for x in ccs], color=col, label=drv["label"])
        ax.axhline(A_MIN * 1e3, color="#6b6a64", ls="--", lw=1)
        ax.set_xlabel("coupling capacitor Cc per net (pF)")
        ax.set_ylabel("gate clock amplitude, single-ended peak (mV)")
        ax.set_title(f"worst corner (PI {min(a_pi.values())*4e3:.0f} mVpp), W{ch['wclock']} gates {cg[ch['wclock']]['max']*1e15:.0f} fF; dashed = 300 mVpp target", fontsize=9)
        ax.legend(frameon=False, fontsize=8)
        fig.savefig(camp / "clock_interface_plan.png", dpi=130)
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
