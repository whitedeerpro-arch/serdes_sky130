"""RX sampler clock buffer: calibrated coarse model, fit / predict check, and constrained solve.

    uv run python analog/rx/sampler/theory/clock_buffer_model.py --sweep CLOCK_AC_CAMPAIGN --card CARD_CAMPAIGN
        [--fit base,wn20,wn80,r450,cc03] [--guard auto|0.1]

Sizing iteration 2 of the AC-coupled clock interface (docs/verification/sizing.md).  The model is
physical; its unknowns are fitted to a one-factor clock_ac/sweep.py campaign and checked on the
variants left out of the fit.

  PI source (per condition):  a_pi = A0 / |1 + j w R_pi (C0 + Cin)|, R_pi = 600 ohm (PI restore load),
      Cin = W (cgs_w + cgd_w (1 + |Av|)) of the buffer input pair (TT-card per-width values).
  Buffer: nfet_lvt pair, L 0.15, width W, tail I (= 0.85 mA * wt / 20 from the global mirror); gm and
      capacitances from the device card of the condition's corner at Id = I/2, Vsb = tail node
      (fixed point), Vds = VDD - I R / 2 - Vs.  Per-side current I/2 (1 + tanh(gm vid / I)), output
      node R || C_L solved per harmonic (periodic steady state, exact for the linear part),
      C_L = Cc Cg/(Cc + Cg) + 0.1 Cc + k_w W + c0.
  Gate: a_gate = a_buf Cc / (Cc + Cg) (per-condition effective Cg).
  Fitted: k_w, c0 (global); A0, C0, Cg per condition.

Solve (trust region = the sweep ranges): W 20-80 um, R 200-600 ohm, I 0.75-1.5 mA, Cc 0.3-1.2 pF.
Constraints at every stress condition: gate >= 300 mVpp x (1 + guard), guard = the worst relative
prediction error on the held-out variants (auto); gate common mode inside the measured window
(headroom_op/window.py, W32 low-overdrive) with >= 50 mV margin at the predicted amplitude, amplitude
<= 300 mV single-ended (window card range).  Objective: buffer current, then Cc.
"""
import argparse
import itertools
import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from serdes_flow.corners import STRESS, Condition
from serdes_flow.devices import DeviceCard
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/rx/sampler/clock_buffer_model"
WINDOWS = ROOT / "results/analog/rx/sampler/clock_cm_window"
F = 2e9
W_RAD = 2 * np.pi * F
R_PI = 600.0
K_VCK = 0.634
I_REF, W_REF = 0.85e-3, 20.0
GATE_MIN, A_SE_MAX, CM_MARGIN = 0.300, 0.300, 0.050
NH = 15                                   # odd harmonics kept in the periodic solution
# r1 defaults of rx_half_rate_samples_ac, for clock_ac campaigns written before summary.json recorded
# dut_defaults (2026-11-01, e.g. the one-factor sweep 20261101T122952Z)
BASE = dict(ck_wn=40, ck_nfin=8, ck_wt=24, ck_rload=300, cc=0.6e-12)


def _num(k, v):
    return float(v.rstrip("p")) * 1e-12 if k == "cc" else float(v)


def params_of(dut_text, defaults=None):
    """Buffer parameters of a clock_ac variant from its DUT line on top of the campaign's DUT defaults."""
    p = dict(BASE) if defaults is None else {k: _num(k, defaults[k]) for k in BASE}
    for kv in dut_text.split()[1:]:
        k, v = kv.split("=")
        if k in p:
            p[k] = _num(k, v)
    return p


class Model:
    def __init__(self, cards):
        self.cards = cards                  # corner -> DeviceCard

    def pair_op(self, c, w, i_tail, r):
        card = self.cards[c.process]
        vin_cm = c.supply - 0.15
        vs = 0.8
        for _ in range(30):
            vds = min(max(c.supply - i_tail * r / 2 - vs, 0.1), 1.8)
            op = card.at_id_w("nfet_lvt", 0.15, i_tail / 2 / w, vds, temp=c.temp, vsb=min(max(vs, 0.0), 0.9))
            vs_new = vin_cm - op["vgs"]
            if abs(vs_new - vs) < 1e-4:
                break
            vs = 0.5 * (vs + vs_new)
        return dict(gm=op["gm_w"] * w, cgs=op["cgs_w"] * w, cgd=op["cgd_w"] * w, vs=vs, vds=vds)

    @staticmethod
    def buffer_out(a_pi_pp, gm, i_tail, r, c_l, n=256):
        """Differential pp at the buffer output for a sinusoidal input of a_pi_pp (diff pp)."""
        t = np.arange(n) / n / F
        vid = a_pi_pp / 2 * np.sin(W_RAD * t)
        ip = i_tail / 2 * (1 + np.tanh(gm * vid / i_tail))
        spec = np.fft.rfft(ip)
        k = np.arange(len(spec))
        z = r / (1 + 1j * 2 * np.pi * k * F * r * c_l)
        z[NH + 1:] = 0
        vp = -np.fft.irfft(spec * z, n)
        vd = vp - np.roll(vp, n // 2)
        return float(np.ptp(vd))

    def predict(self, c, p, th):
        """th: dict(k_w, c0, A0, C0, Cg) with the per-condition entries already selected."""
        w, r, cc = p["ck_wn"], p["ck_rload"], p["cc"]
        i_tail = I_REF * p["ck_wt"] / W_REF
        op = self.pair_op(c, w, i_tail, r)
        cg = th["Cg"]
        c_l = cc * cg / (cc + cg) + 0.1 * cc + th["k_w"] * w + th["c0"]
        av = op["gm"] * r / abs(1 + 1j * W_RAD * r * c_l)
        cin = op["cgs"] + op["cgd"] * (1 + av)
        a_pi = th["A0"] / abs(1 + 1j * W_RAD * R_PI * (th["C0"] + cin))
        a_buf = self.buffer_out(a_pi, op["gm"], i_tail, r, c_l)
        return dict(pi=a_pi, buf=a_buf, gate=a_buf * cc / (cc + cg), i_tail=i_tail, gm=op["gm"], c_l=c_l, cin=cin)


def unpack(x, conds):
    th = dict(k_w=x[0] * 1e-15, c0=x[1] * 1e-15)
    per = {c.tag: dict(A0=x[2 + 3 * i], C0=x[3 + 3 * i] * 1e-15, Cg=x[4 + 3 * i] * 1e-15) for i, c in enumerate(conds)}
    return th, per


def fit(model, rows, conds, names):
    x0 = [1.0, 20.0] + [0.45, 100.0, 100.0] * len(conds)
    lo = [0.0, 0.0] + [0.1, 0.0, 20.0] * len(conds)
    hi = [10.0, 300.0] + [2.0, 1000.0, 400.0] * len(conds)
    data = [r for r in rows if r["variant"] in names]

    def resid(x):
        th, per = unpack(x, conds)
        out = []
        for r in data:
            c = Condition.parse(r["condition"])
            pr = model.predict(c, r["p"], {**th, **per[c.tag]})
            out += [np.log(pr["pi"] / r["pi_pp"]), np.log(pr["buf"] / r["buf_pp"]), np.log(pr["gate"] / r["gate_pp"])]
        return np.array(out)

    sol = least_squares(resid, x0, bounds=(lo, hi), x_scale="jac")
    return sol.x, float(np.sqrt(np.mean(sol.fun ** 2)))


def load_window():
    """{ck_half: {condition: (lo, hi, supply)}} for the W32 low-overdrive DFF."""
    out = {}
    for s in sorted(WINDOWS.glob("*/summary.json")):
        d = json.loads(s.read_text())
        if d.get("bias") == "vbias_logic" and int(d["dff"].get("wclock", 32)) == 32:
            out[round(d["ck_half_v"], 3)] = {r["condition"]: (r["lo_v"], r["hi_v"], r["supply"]) for r in d["rows"]}
    return out


def cm_margin(win, tag, a_se):
    hs = sorted(win)
    lo = np.interp(a_se, hs, [win[h][tag][0] for h in hs])
    hi = np.interp(a_se, hs, [win[h][tag][1] for h in hs])
    v = K_VCK * win[hs[0]][tag][2]
    return float(min(v - lo, hi - v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", required=True, help="clock_ac campaign with the one-factor variants")
    ap.add_argument("--card", required=True, help="device-card campaign (one sub-directory per corner)")
    ap.add_argument("--fit", default="base,wn20,wn80,r450,cc03")
    ap.add_argument("--guard", default="auto")
    a = ap.parse_args()
    summ = json.loads((ROOT / a.sweep / "summary.json").read_text())
    duts = {v["name"]: v["dut"] for v in summ["variants"]}
    rows = [dict(r, p=params_of(duts[r["variant"]], summ.get("dut_defaults"))) for r in summ["rows"] if r["buf_pp"] is not None]
    conds = [c for c in STRESS if any(r["condition"] == c.tag for r in rows)]
    cards = {p: DeviceCard.load(ROOT / a.card / p) for p in sorted({c.process for c in conds})}
    model = Model(cards)
    fit_names = a.fit.split(",")
    x, rms = fit(model, rows, conds, fit_names)
    th, per = unpack(x, conds)
    print(f"fit on {fit_names}: rms log error {rms:.3f}; k_w {th['k_w']*1e15:.2f} fF/um, c0 {th['c0']*1e15:.1f} fF")
    for c in conds:
        q = per[c.tag]
        print(f"  {c.tag:15s} A0 {q['A0']*1e3:5.0f} mVpp  C0 {q['C0']*1e15:5.0f} fF  Cg {q['Cg']*1e15:5.0f} fF")
    print("\nprediction vs measurement (gate mVpp; * = held out):")
    errs, held = [], []
    for r in rows:
        c = Condition.parse(r["condition"])
        pr = model.predict(c, r["p"], {**th, **per[c.tag]})
        e = pr["gate"] / r["gate_pp"] - 1
        errs.append(dict(variant=r["variant"], condition=c.tag, gate_meas=r["gate_pp"], gate_pred=pr["gate"],
                         pi_meas=r["pi_pp"], pi_pred=pr["pi"], buf_meas=r["buf_pp"], buf_pred=pr["buf"], err=e,
                         held_out=r["variant"] not in fit_names))
        if r["variant"] not in fit_names:
            held.append(abs(e))
    for v in dict.fromkeys(r["variant"] for r in rows):
        es = [x for x in errs if x["variant"] == v]
        print(f"  {v:9s}{'*' if es[0]['held_out'] else ' '} " + "  ".join(
            f"{x['condition'].split('_')[0]}{x['condition'].split('_t')[1]:>4}: {x['gate_meas']*1e3:3.0f}/{x['gate_pred']*1e3:3.0f}" for x in es))
    guard = max(held) if a.guard == "auto" else float(a.guard)
    print(f"held-out |error| max {max(held)*100:.1f} %, mean {np.mean(held)*100:.1f} %; guard band {guard*100:.1f} %")

    win = load_window()
    cands = []
    for w, r, wt, cc in itertools.product((20, 30, 40, 60, 80), range(200, 601, 50), (18, 21, 24, 30, 36),
                                          (0.3e-12, 0.45e-12, 0.6e-12, 0.8e-12, 1.0e-12, 1.2e-12)):
        p = dict(ck_wn=w, ck_nfin=max(2, w // 5), ck_wt=wt, ck_rload=r, cc=cc)
        gates, margins = {}, {}
        for c in conds:
            pr = model.predict(c, p, {**th, **per[c.tag]})
            gates[c.tag] = pr["gate"]
            a_se = pr["gate"] / 4
            margins[c.tag] = cm_margin(win, c.tag, min(a_se, A_SE_MAX)) if a_se <= A_SE_MAX else -1.0
        ok = min(gates.values()) >= GATE_MIN * (1 + guard) and min(margins.values()) >= CM_MARGIN
        cands.append(dict(p=p, i_ma=I_REF * wt / W_REF * 1e3, gate_min=min(gates.values()), gate_max=max(gates.values()),
                          cm_margin=min(margins.values()), ok=ok, gates=gates))
    feas = sorted([c for c in cands if c["ok"]], key=lambda c: (c["i_ma"], c["p"]["cc"], -c["gate_min"]))
    print(f"\n{len(feas)}/{len(cands)} grid points feasible; cheapest:")
    for c in feas[:8]:
        p = c["p"]
        print(f"  W {p['ck_wn']:2d}  R {p['ck_rload']:3d}  I {c['i_ma']:.2f} mA  Cc {p['cc']*1e12:.2f} pF | gate "
              f"{c['gate_min']*1e3:.0f}-{c['gate_max']*1e3:.0f} mVpp, CM margin {c['cm_margin']*1e3:.0f} mV")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    (camp / "model.json").write_text(json.dumps(dict(sweep=a.sweep, card=a.card, fit=fit_names, rms_log=rms,
        theta=dict(k_w=th["k_w"], c0=th["c0"]), per_condition=per, predictions=errs, guard=guard,
        feasible=[dict(p=c["p"], i_ma=c["i_ma"], gate_min=c["gate_min"], gate_max=c["gate_max"], cm_margin=c["cm_margin"])
                  for c in feas[:50]]), indent=1, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
