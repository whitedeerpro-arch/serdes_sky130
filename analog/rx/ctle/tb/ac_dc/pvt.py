"""RX CTLE operating point / AC / DC transfer over PVT (ideal inputs, no boundary condition).

    uv run python analog/rx/ctle/tb/ac_dc/pvt.py [stress | all | tags...] [--cm 0.8,0.9]

Per condition x EQ code x input common mode: tail and input-pair headroom
(Vds - Vdsat), output common mode, low-frequency gain, gain and peaking at
2 GHz (Nyquist of 4 Gb/s), -3 dB bandwidth, power.  Functional gate: every
transistor of the signal path in saturation with >= 50 mV beyond Vdsat; the
AC numbers are characterization (ungraded).
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import STRESS, Condition, grid45
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_ctle_ac_dc_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/ctle/ac_dc_pvt"
HEADROOM_GATE = 0.05


def read_tsv(path):
    lines = path.read_text().split("\n")
    names = lines[0].split()
    data = np.loadtxt(lines[1:])
    data = np.atleast_2d(data)
    if data.shape[1] == len(names):
        return {n: data[:, i] for i, n in enumerate(names)}
    # complex vectors: scale, then re/im per vector
    out = {names[0]: data[:, 0]}
    for k, n in enumerate(names[1:]):
        out[n] = data[:, 1 + 2 * k] + 1j * data[:, 2 + 2 * k]
    return out


def deck(c, code, cm):
    eq0, eq1 = code & 1, code >> 1
    return spice.render(TEMPLATE, **spice.corner_values(c), EQ_CODE=code, INPUT_CM=cm,
                        EQ0_V=c.supply * eq0, EQ1_V=c.supply * eq1)


def analyse(d):
    op = read_tsv(d / "operating_point.tsv")
    g = {k: float(np.real(v[0])) for k, v in op.items()}
    ac = read_tsv(d / "ac.tsv")
    f = np.real(ac[list(ac)[0]])
    gain = np.abs(ac["gain"])
    db = 20 * np.log10(gain)
    g0 = db[0]
    g2 = float(np.interp(2e9, f, db))
    above = np.where(db < g0 - 3)[0]
    bw = float(f[above[0]]) if len(above) else float("nan")
    head_tail = g["v(xeq.sp)"] - g["vdsat_tail"]
    head_in = g["vds_in"] - g["vdsat_in"]
    return dict(vsrc=g["v(xeq.sp)"], vdsat_tail=g["vdsat_tail"], headroom_tail=head_tail, headroom_in=head_in,
                cm_out=g["cmout"], id_tail=g["id_tail"], power=g["pcore"], gain_lf_db=float(g0), gain_2g_db=g2,
                peaking_db=g2 - float(g0), peak_db=float(db.max() - g0), bw3_hz=bw,
                ok=bool(head_tail >= HEADROOM_GATE and head_in >= HEADROOM_GATE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=["stress"])
    ap.add_argument("--cm", default="0.8,0.9")
    a = ap.parse_args()
    conds = grid45() if a.conds == ["all"] else STRESS if a.conds == ["stress"] else [Condition.parse(x) for x in a.conds]
    cms = [float(x) for x in a.cm.split(",")]
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    keys = [(c, code, cm) for c in conds for cm in cms for code in range(4)]
    jobs = [(deck(c, code, cm), camp / f"{c.tag}_cm{round(cm * 1000)}_eq{code}", dict(meta=dict(condition=c.tag, eq=code, cm=cm)))
            for c, code, cm in keys]
    for ex in spice.run_many(jobs, workers=4, smoke=False):     # no transient: nothing to smoke-test
        assert ex.ok, (ex.run_dir, ex.log_failures)
    rows = []
    for (c, code, cm), (_, d, _) in zip(keys, jobs):
        r = dict(condition=c.tag, eq=code, cm=cm, **analyse(d))
        rows.append(r)
    (camp / "summary.json").write_text(json.dumps(rows, indent=1, default=float))
    print(f"{'condition':15s} cm   eq | Vsrc  head_tail head_in | CMout | LF dB  2G dB  peak | BW GHz | P mW")
    for r in rows:
        print(f"{r['condition']:15s} {r['cm']:.1f}  {r['eq']}  | {r['vsrc']:.3f} {r['headroom_tail']*1e3:6.0f}mV {r['headroom_in']*1e3:6.0f}mV"
              f" | {r['cm_out']:.3f} | {r['gain_lf_db']:5.1f} {r['gain_2g_db']:5.1f} {r['peaking_db']:+5.2f} | {r['bw3_hz']/1e9:5.2f}"
              f" | {r['power']*1e3:4.2f} {'' if r['ok'] else '  HEADROOM'}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
