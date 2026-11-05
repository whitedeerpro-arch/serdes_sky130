"""RX PI 64-code rotation over PVT (ideal anchors, no boundary condition).

    uv run python analog/rx/pi/tb/rotation/pvt.py [stress | all | tags...] [--codes 0..63] [--pi cmix=120f ...]
        [--bias ideal|real] [--rpdk tt|ll|hh] [--workers 4] [--resume C] [--analyse-only]

Anchors: four ideal 2 GHz differential clocks, 0/45/90/135 deg, 400 mVpp diff, common mode
VDD - 0.15 V (follows the supply).  Code c = 8q + f (README): even sector A = q, B = q+1,
nB = f; odd sector A = q+1, B = q, nB = 8 - f; f0..f7 thermometer, first nB high.
One ngspice run per process corner: supply, temperature and the 24 control bits change in
the control block; 4 ns per code, phase measured over the last 2 ns.

Per condition: data-clock phase vs code (unwrapped, in UI of 4 Gb/s; one 2 GHz period = 2 UI,
LSB = 2/64 UI), monotonicity, DNL / INL (INL against the straight line through the 64 codes
with the mean step), output swing, edge-clock offset from data + 0.5 UI (quadrature).
Gate (agreed 2026-11-01): monotonic over 64 codes, |INL| <= 0.02 UI.
--pi: rotator parameters; --bias real / --rpdk: real reference and PDK resistors, as sampler/tb/link_pvt.
"""
import argparse
import json
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_pi_rotation_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/pi/rotation_pvt"
PERIOD = 0.5e-9
UI = 250e-12
STOP, SAVE_FROM, MEAS_FROM = 4e-9, 1.9e-9, 2e-9
GATE_INL = 0.02


def bits(code, supply):
    q, f = divmod(code, 8)
    a, b, nb = (q, (q + 1) % 8, f) if q % 2 == 0 else ((q + 1) % 8, q, 8 - f)
    v = {}
    for i in range(8):
        v[f"Va{i}"] = supply if i == a else 0.0
        v[f"Vb{i}"] = supply if i == b else 0.0
        v[f"Vf{i}"] = supply if i < nb else 0.0
    return v


def case_name(c, code):
    return f"{c.tag}_c{code:02d}"


def deck(cases, pi_params="", real_bias=False, rpdk=None, camp=None):
    c0, code0 = cases[0]
    b0 = bits(code0, c0.supply)
    text = spice.render(TEMPLATE, **spice.corner_values(c0), CASES="@CASES@", PI_PARAMS=pi_params,
                        **{f"{k[1].upper()}{k[2]}_V": v for k, v in b0.items()})
    blocks = []
    for c, code in cases:
        n = case_name(c, code)
        blocks.append("\n".join([f"* case {n}", f"option temp={c.temp}", f"alter Vdd dc={c.supply}", f"alter Vref dc={c.supply}"]
                                + [f"alter {k} dc={v}" for k, v in bits(code, c.supply).items()]
                                + [f"tran 2p {STOP:.3e} {SAVE_FROM:.3e} 4p",
                                   "let data_clock=v(dp)-v(dn)", "let edge_clock=v(ep)-v(en)", "let anchor=v(c0p)-v(c0n)",
                                   "let power=-v(vdd)*i(Vdd)",
                                   f"write {n}.raw data_clock edge_clock anchor power", "destroy all"]))
    text = text.replace("@CASES@", "\n".join(blocks))
    if real_bias:
        text = bias.real(text)
    if rpdk:
        text = bias.section(rcorner.to_pdk(text, camp), c0.process, rpdk)
    return text


def phase(t, y, ref):
    """Mean rising-crossing time of y after those of ref, in seconds modulo one period."""
    sel = t >= MEAS_FROM
    e, p = crossings(t[sel], y[sel])
    r, pr = crossings(t[sel], ref[sel])
    e, r = e[p > 0], r[pr > 0]
    d = np.array([x - r[np.searchsorted(r, x) - 1] for x in e if np.searchsorted(r, x) > 0]) % PERIOD
    ang = np.angle(np.mean(np.exp(2j * np.pi * d / PERIOD)))
    return float(ang / (2 * np.pi) * PERIOD % PERIOD)


def analyse_condition(d, c, codes):
    ph, edge, swing, power = [], [], [], []
    for code in codes:
        w = spice.Waves(Path(d) / f"{case_name(c, code)}.raw")
        ph.append(phase(w.t, w["data_clock"], w["anchor"]))
        edge.append(phase(w.t, w["edge_clock"], w["data_clock"]))
        sel = w.t >= MEAS_FROM
        swing.append(float(min(np.ptp(w["data_clock"][sel]), np.ptp(w["edge_clock"][sel]))))
        power.append(float(np.mean(w["power"][sel])))
    ph = np.unwrap(np.array(ph) / PERIOD * 2 * np.pi) / (2 * np.pi) * PERIOD / UI      # UI
    step = np.diff(ph)
    direction = np.sign(np.median(step))
    step = step * direction
    lsb = (2.0 * (len(codes) - 1) / 64) / (len(codes) - 1) if len(codes) > 1 else 0
    span = (ph[-1] - ph[0]) * direction
    fit = ph[0] + direction * np.mean(step) * np.arange(len(codes))
    inl = (ph - fit) * direction
    quad = (np.array(edge) / UI - 0.5)                          # edge clock = data + 90 deg of 2 GHz = 0.5 UI
    quad = (quad + 0.5) % 1.0 - 0.5                             # 90 or 270 deg: either polarity is a quadrature phase
    return dict(condition=c.tag, codes=list(codes), phase_ui=ph.tolist(), monotonic=bool(np.all(step > 0)),
                step_min_lsb=float(step.min() / lsb), step_max_lsb=float(step.max() / lsb),
                dnl_lsb=float(np.max(np.abs(step / lsb - np.mean(step) / lsb))), inl_ui=float(np.max(np.abs(inl))),
                span_ui=float(span), quadrature_err_ui=float(np.max(np.abs(quad))), swing_min_v=float(min(swing)),
                power_mw=float(np.mean(power) * 1e3),
                ok=bool(np.all(step > 0) and np.max(np.abs(inl)) <= GATE_INL))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--codes", default="0..63")
    ap.add_argument("--pi", action="append", default=[])
    ap.add_argument("--bias", choices=("ideal", "real"), default="ideal")
    ap.add_argument("--rpdk", choices=("tt", "ll", "hh"))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--resume")
    ap.add_argument("--analyse-only", action="store_true")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.codes.split(".."))
    codes = list(range(lo, hi + 1))
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    keys = [(c, code) for c in conds for code in codes]
    by_proc = {}
    for k in keys:
        by_proc.setdefault(k[0].process, []).append(k)
    pi_params = " ".join(a.pi)
    jobs = [(deck(cases, pi_params, a.bias == "real", a.rpdk, camp), camp / proc,
             dict(meta=dict(process=proc, conditions=sorted({c.tag for c, _ in cases}), codes=codes, pi=a.pi, bias=a.bias, rpdk=a.rpdk)))
            for proc, cases in by_proc.items()]
    todo = []
    for j in jobs:
        if (j[1] / "execution.json").exists():
            continue
        if j[1].exists() and not a.analyse_only:
            shutil.rmtree(j[1])
        todo.append(j)
    print(f"{len(keys)} cases in {len(jobs)} decks: {len(jobs) - len(todo)} kept, {len(todo)} to run", flush=True)
    for ex in ([] if a.analyse_only else spice.run_many(todo, workers=a.workers, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = [analyse_condition(camp / c.process, c, codes) for c in conds]
    (camp / "summary.json").write_text(json.dumps(rows, indent=1, default=float))
    print(f"{'condition':15s} | mono | step lsb min/max | DNL lsb | INL UI | span UI | quad err UI | swing mV | P mW")
    for r in rows:
        print(f"{r['condition']:15s} | {'yes' if r['monotonic'] else 'NO '}  | {r['step_min_lsb']:5.2f}/{r['step_max_lsb']:5.2f} | "
              f"{r['dnl_lsb']:5.2f} | {r['inl_ui']:.4f} | {r['span_ui']:6.3f} | {r['quadrature_err_ui']:.3f} | "
              f"{r['swing_min_v']*1e3:5.0f} | {r['power_mw']:5.2f} {'' if r['ok'] else ' FAIL'}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
