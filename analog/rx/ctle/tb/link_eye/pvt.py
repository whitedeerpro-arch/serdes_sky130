"""RX CTLE eye over PVT: ideal TX + C2 PCB + real termination/CTLE (no boundary condition).

    uv run python analog/rx/ctle/tb/link_eye/pvt.py [stress | all | tags...] [--vcm 1.05]
        [--tx nominal|weak] [--resume CAMPAIGN] [--analyse-only]

Stimulus: 40 warm-up bits + one full PRBS7 period (167 bits, ~42 ns) from an ideal
Thevenin TX (per leg 50 ohm, open-circuit swing below), pad 200 fF and 0.5 nH package,
C2_loss6 Foster model, 2 x 50 ohm termination to vcm, CTLE with 20 fF per leg.
One ngspice run per process corner (supply, temperature, EQ code changed in the
control block).  Signed eye (serdes_flow.eye) over the PRBS period at the RX input
and at the CTLE output; per condition the best EQ code is reported.

Gate (sampler input = CTLE output, agreed 2026-11-01): eye height >= 75 mV and
width >= 0.6 UI at the decision threshold.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import eye, spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_ctle_link_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/ctle/link_eye_pvt"
UI = 250e-12
T0 = 1e-9                      # start of bit 0
WARM, NBITS = 40, 167          # analysed bits 40..166 = one PRBS7 period
STOP, SAVE_FROM = T0 + (NBITS + 8) * UI, 8e-9
TX = {"nominal": dict(oc_pp=0.8, ramp=40e-12), "weak": dict(oc_pp=0.6, ramp=60e-12)}
GATE_H, GATE_W = 0.075, 0.6


def case_name(c, code):
    return f"{c.tag}_eq{code}"


def stimuli(vcm, tx):
    bits = eye.prbs7(NBITS)
    a = TX[tx]["oc_pp"] / 4                    # per leg: +-oc_pp/4 around vcm (differential oc_pp pp)
    lines = []
    for leg, sign in (("p", 1), ("n", -1)):
        pts = eye.nrz_pwl(bits, UI, T0, TX[tx]["ramp"], vcm - sign * a, vcm + sign * a)
        lines.append(f"Vtx{leg} txs_{leg} 0 PWL(" + " ".join(f"{t:.6e} {v:.5f}" for t, v in pts) + ")")
    return "\n".join(lines) + "\n", bits


def deck(cases, vcm):
    c0, code0 = cases[0]
    assert all(c.process == c0.process for c, _ in cases)
    text = spice.render(TEMPLATE, **spice.corner_values(c0), VCM=vcm, EQ0_V=c0.supply * (code0 & 1),
                        EQ1_V=c0.supply * (code0 >> 1), CASES="@CASES@")
    blocks = []
    for c, code in cases:
        n = case_name(c, code)
        blocks.append("\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}",
                                 f"alter Veq0 dc={c.supply * (code & 1)}", f"alter Veq1 dc={c.supply * (code >> 1)}",
                                 f"tran 2p {STOP:.4e} {SAVE_FROM:.4e} 4p",
                                 "let rx_diff=v(rxp)-v(rxn)", "let ctle_diff=v(op)-v(on)",
                                 "let ctle_cm=(v(op)+v(on))/2", "let pcore=-v(vdd)*i(Vdd)",
                                 f"write {n}.raw rx_diff ctle_diff ctle_cm pcore", "destroy all"]))
    return text.replace("@CASES@", "\n".join(blocks))


def analyse(d, name, bits):
    w = spice.Waves(Path(d) / f"{name}.raw")
    rx = eye.signed_eye(w.t, w["rx_diff"], bits, UI, T0, first_bit=WARM, max_latency=4e-9)
    ct = eye.signed_eye(w.t, w["ctle_diff"], bits, UI, T0, first_bit=WARM, max_latency=4e-9)
    sel = w.t > T0 + WARM * UI
    return dict(rx_height=rx["height_v"], rx_width=rx["width_ui"], height=ct["height_v"], width=ct["width_ui"],
                latency_ns=ct["latency_s"] * 1e9, ctle_pp=float(np.ptp(w["ctle_diff"][sel])),
                ctle_cm=float(np.mean(w["ctle_cm"][sel])), power_mw=float(np.mean(w["pcore"][sel]) * 1e3),
                ok=bool(ct["height_v"] >= GATE_H and ct["width_ui"] >= GATE_W))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--vcm", type=float, default=1.05)
    ap.add_argument("--tx", default="nominal", choices=tuple(TX))
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    camp = (ROOT / a.resume) if a.resume else RESULTS / f"{a.tx}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    camp.mkdir(parents=True, exist_ok=True)
    stim, bits = stimuli(a.vcm, a.tx)
    (camp / "stimuli.inc").write_text(stim)
    keys = [(c, code) for c in conds for code in range(4)]
    by_proc = {}
    for k in keys:
        by_proc.setdefault(k[0].process, []).append(k)
    jobs = [(deck(cases, a.vcm), camp / proc,
             dict(files={"stimuli.inc": camp / "stimuli.inc"},
                  meta=dict(process=proc, vcm=a.vcm, tx=a.tx, cases=[case_name(*k) for k in cases])))
            for proc, cases in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(keys)} cases in {len(jobs)} decks: {len(jobs) - len(todo)} kept, {len(todo)} to run", flush=True)
    # several tran lines per deck: smoke_deck needs exactly one, so the deck runs unsmoked
    # (the template is checked by a single-case TT run first, see --help of this script)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=4, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = [dict(condition=c.tag, eq=code, **analyse(camp / c.process, case_name(c, code), bits)) for c, code in keys]
    best = {}
    for r in rows:
        if r["condition"] not in best or r["height"] > best[r["condition"]]["height"]:
            best[r["condition"]] = r
    (camp / "summary.json").write_text(json.dumps(dict(vcm=a.vcm, tx=a.tx, tx_model=TX[a.tx], rows=rows,
                                                       best={k: v["eq"] for k, v in best.items()}), indent=1, default=float))
    print(f"{'condition':15s} | RX in mV/UI | CTLE eye per EQ code 0..3 (mV / UI) | best")
    for c in conds:
        rs = [r for r in rows if r["condition"] == c.tag]
        b = best[c.tag]
        print(f"{c.tag:15s} | {rs[0]['rx_height']*1e3:5.0f}/{rs[0]['rx_width']:.2f} | "
              + "  ".join(f"{r['height']*1e3:5.0f}/{r['width']:.2f}" for r in rs)
              + f" | eq{b['eq']} {'ok' if b['ok'] else 'FAIL'}  CM {b['ctle_cm']:.2f} V  pp {b['ctle_pp']*1e3:.0f} mV")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
