"""VCO tuning curves of the PLL r4 frontend from one Vctrl ramp per coarse code.

    uv run python analog/pll/top/tb/pvt_r4/tuning.py <condition tag> <code> [code...]

Same frontend bench as run.py (all four branches loaded as in the PLL), open
loop.  Vctrl is held at V0 for 8 ns, then ramped linearly to V1 over 60 ns
(15 mV/ns; at ~500 MHz/V the frequency moves ~0.2 % per period, so the curve
is quasi-static).  Each VCO period gives one (Vctrl at mid-period, frequency)
point (VCO node v0).  Prints the frequency range per code and the Vctrl for 2 GHz.
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
RESULTS = ROOT / "results/analog/pll/top/tuning_r4"
V0, V1, T0, T1 = 0.8, 1.7, 8e-9, 68e-9
TARGET_HZ = 2e9


def deck(c, code):
    d = spice.render(HERE / "tb_frontend_ngspice.cir.in", **spice.corner_values(c), CODE=code,
                     CONTROL_SOURCE=f"PWL(0 {V0} {T0 * 1e9:g}n {V0} {T1 * 1e9:g}n {V1})", STOP=f"{T1 * 1e9 + 1:g}n")
    # Only Vctrl and the VCO node; the template's b0 let refers to a node that r4 made a port.
    d = "\n".join("wrdata waveforms.tsv v(ctrl) d0" if l.startswith("wrdata ") else l
                  for l in d.splitlines() if not l.startswith("let b0="))
    return spice.skip_output_before(spice.binary_output(d), "6n")


def curve(run_dir):
    w = spice.Waves(run_dir / "waveforms.raw")
    e, pol = crossings(w.t, w["d0"])
    r = e[pol > 0]
    r = r[r > T0 - 1e-9]
    mid = (r[1:] + r[:-1]) / 2
    return np.interp(mid, w.t, w["ctrl"]), 1 / np.diff(r)


def main(tag, codes):
    c = Condition.parse(tag)
    camp = RESULTS / f"{tag}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    jobs = [(deck(c, k), camp / f"code{k}", dict(meta=dict(condition=tag, code=k, ramp=[V0, V1, T0, T1])))
            for k in codes]
    for ex in spice.run_many(jobs, workers=4):
        assert ex.ok, (ex.run_dir, ex.log_failures)
    analyse(camp, tag, codes)


def analyse(camp, tag, codes):
    rows = []
    for k in codes:
        v, f = curve(camp / f"code{k}")
        ramp = v > V0 + 1e-3
        v, f = v[ramp], f[ramp]
        cross = None
        if len(f) and f.min() <= TARGET_HZ <= f.max():
            i = int(np.argmin(abs(f - TARGET_HZ)))
            cross = float(v[i])
        kvco = float(np.polyfit(v[abs(f - TARGET_HZ) < 0.1e9], f[abs(f - TARGET_HZ) < 0.1e9], 1)[0]) \
            if cross is not None and np.sum(abs(f - TARGET_HZ) < 0.1e9) > 5 else None
        rows.append(dict(code=k, vctrl_v=v.tolist(), frequency_hz=f.tolist(), vctrl_at_2ghz=cross,
                         kvco_hz_per_v=kvco))
        print(f"{tag} code {k}: {f.min() / 1e9:.3f}-{f.max() / 1e9:.3f} GHz over Vctrl {v.min():.2f}-{v.max():.2f} V; "
              + (f"2 GHz at Vctrl {cross:.3f} V, Kvco {kvco / 1e6:.0f} MHz/V" if cross else "2 GHz not covered"),
              flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(condition=tag, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    if sys.argv[1] == "analyse":                      # analyse <campaign dir>
        camp = Path(sys.argv[2]).resolve()
        tag = json.loads((sorted(camp.glob("code*"))[0] / "execution.json").read_text())["condition"]
        analyse(camp, tag, sorted(int(p.name[4:]) for p in camp.glob("code*")))
    else:
        main(sys.argv[1], [int(x) for x in sys.argv[2:]])
