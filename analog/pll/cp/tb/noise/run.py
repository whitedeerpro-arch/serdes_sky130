"""Charge pump output current noise with both switches on (the state it spends its reset pulse in, locked).

    uv run python analog/pll/cp/tb/noise/run.py [--cond tt_v1800_t27] [--vout 1.2] [--rcorner tt]

.noise (sparse) across a noiseless 100 ohm sense resistor at the output; S_i(f) = S_v(f) / R^2.  Two decks: ideal
current references (the CP's mirrors only) and the real bias (serdes_flow.bias.real: + bandgap, V->I, copy,
vbn / vbp diodes).  One-sided A^2/Hz into summary.json, for analog/pll/top/theory/pll_noise.py.
"""
import argparse
import json
import time

import numpy as np

from serdes_flow import bias, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

RESULTS = ROOT / "results/analog/pll/cp/noise"
RS = 100.0


def deck(c, vout, real, rc="tt"):
    vals = spice.corner_values(c)
    text = f"""CP output noise, both switches on
.lib "{vals['MODEL_LIBRARY']}" {vals['CORNER']}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/common/devices/spice/cmos_logic.spice"
.include "{ROOT}/analog/pll/cp/spice/charge_pump.spice"
Vdd vdd 0 dc {c.supply} ac 1
In vdd vbn 50u
Xbn vbn vbn 0 0 serdes_nfet w=5 l=1
Ip vbp 0 50u
Xbp vbp vbp vdd vdd serdes_pfet w=20 l=1 nf=4
Xcp vdd vdd out vbn vbp vdd 0 pll_cp
Rs out mid {RS} noisy=0
Vout mid 0 {vout}
.temp {c.temp}
.options sparse
"""
    if real:
        text = bias.section(bias.real(text), c.process, rc)
    return text + "\n".join([".control", "set num_threads=1", "set filetype=binary", "op", "let iout=-i(Vout)", "print iout v(vbn) v(vbp)", "destroy all", "noise v(out) Vdd dec 10 1k 3g", "setplot previous",
                             "write noise.raw onoise_spectrum", "quit", ".endc", ".end", ""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--vout", type=float, default=1.2)
    ap.add_argument("--rcorner", default="tt")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{c.tag}_r{a.rcorner}")
    jobs = [(deck(c, a.vout, r, a.rcorner), camp / n, dict(timeout_s=900)) for n, r in (("ideal", False), ("real", True))]
    for ex in spice.run_many(jobs, workers=1, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    out = dict(condition=c.tag, vout=a.vout, cases={})
    pick = (1e4, 1e5, 1e6, 1e7, 1e8, 1e9)
    print(f"{c.tag}: S_i, A2/Hz at " + " ".join(f"{p:9.0e}" for p in pick))
    for n in ("ideal", "real"):
        w = spice.Waves(camp / n / "noise.raw")
        f, s = w.t, (w["onoise_spectrum"] / RS) ** 2
        out["cases"][n] = dict(f=f.tolist(), s=s.tolist())
        print(f"  {n:6s}          " + " ".join(f"{np.interp(p, f, s):9.2e}" for p in pick), flush=True)
    (camp / "summary.json").write_text(json.dumps(out))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
