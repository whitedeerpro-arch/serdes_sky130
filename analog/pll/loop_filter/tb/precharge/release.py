"""Loop filter state at the release of the dual-node precharge, over a few conditions.

    uv run python analog/pll/loop_filter/tb/precharge/release.py

tb_lf_dual_precharge with the gates opening at 1 us (500 ohm reference source, as the original
comparison).  Per condition: v(ctrl) just before the release, 1 ns and 50 ns after it, and v(z).
"""
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_lf_dual_precharge_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/loop_filter/precharge_release"
CASES = (("tt", 1.8, 1.40), ("tt", 1.8, 1.10), ("ss", 1.65, 1.10), ("ff", 1.95, 1.10), ("sf", 1.65, 1.10), ("fs", 1.95, 1.10))


def deck(proc, sup, vt):
    text = spice.render(TEMPLATE, **spice.corner_values(Condition(proc, sup, 27)))
    for old, new in (("supply=1.8 vtarget=1.40 rsource=500 release=5u", f"supply={sup} vtarget={vt} rsource=500 release=1u"),
                     ("tran 200p 4u 0 200p", "tran 100p 1.06u 0 100p")):
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    return text


def main():
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(*c), camp / f"{c[0]}_v{round(c[1] * 1000)}_t{round(c[2] * 100)}", dict(timeout_s=600)) for c in CASES]
    rows = []
    for c, ex in zip(CASES, spice.run_many(jobs, workers=4, smoke=False)):
        assert ex.ok, (ex.run_dir, ex.log_failures)
        f = ex.run_dir / "waveforms.tsv"
        head = f.read_text().split("\n", 1)[0].split()
        a = np.loadtxt(f, skiprows=1)
        at = lambda name, t: float(np.interp(t, a[:, 0], a[:, head.index(name)]))
        ctrl0, z0 = at("v(ctrl1)", 0.999e-6), at("v(z1)", 0.999e-6)
        rows.append(dict(process=c[0], supply=c[1], target=c[2], ctrl_before=ctrl0, z_before=z0,
                         d_ctrl_1ns_mv=(at("v(ctrl1)", 1.001e-6) - ctrl0) * 1e3, d_ctrl_50ns_mv=(at("v(ctrl1)", 1.05e-6) - ctrl0) * 1e3,
                         d_z_50ns_mv=(at("v(z1)", 1.05e-6) - z0) * 1e3))
        r = rows[-1]
        print(f"{c[0]} {c[1]} V target {c[2]} V: ctrl {ctrl0:.4f} V, +1 ns {r['d_ctrl_1ns_mv']:+.2f} mV, +50 ns {r['d_ctrl_50ns_mv']:+.2f} mV, z +50 ns {r['d_z_50ns_mv']:+.3f} mV", flush=True)
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
