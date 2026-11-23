"""VCO frequency vs code and Vctrl with the real bias and PDK resistors.

    uv run python analog/pll/vco/tb/tuning/range_real.py --cases ss_v1650_t85:hh,ff_v1950_t-40:ll [--codes 0,1,2,3,4,5,6,7] [--vctrl 0.7,0.95,1.2,1.45]

The earlier tuning data (docs/design/pll_vco.md) is ideal bias and ideal R: a resistor corner moves R C and, through the
constant-swing bias (I ~ 1 / R), the current too.  One deck per (MOS corner, resistor corner), `alter` over code,
Vctrl, supply and temperature; template of tb/phase_noise (ring + four buffers, 30 fF).  Prints the frequency table and
which (code, Vctrl) reach 2 GHz.  Short transients: settling 8 ns, 12 periods; reltol 1e-4 (frequency to about 0.1 %).
"""
import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

TEMPLATE = ROOT / "analog/pll/vco/tb/phase_noise/tb_vco_isf_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/vco/tuning_real"


def deck(process, rc, conds, codes, vctrls, camp, stop="14n", start="8n", vco_params=""):
    c0 = conds[0]
    text = spice.render(TEMPLATE, **spice.corner_values(c0), VCTRL=1.2, INJECT="", PROBES="", TSTEP="1p", STOP="14n", SAVE_FROM="8n", OUT="x.raw", CFG0=0, CFG1=0, CFG2=0)
    text = re.sub(r"\.control.*?\.endc\n", "", text, flags=re.S)
    text = text.replace("reltol=1e-5", "reltol=1e-4")
    if vco_params:          # what-if: parameter overrides on the VCO instance (sw=5 varw=4.5 varvm=4 ...)
        old = "vbias vdd 0 pll_vco_ring4_pvt_candidate"
        assert text.count(old) == 1
        text = text.replace(old, f"{old} {vco_params}")
    camp.mkdir(parents=True, exist_ok=True)
    text = bias.section(rcorner.to_pdk(bias.real(text), camp), process, rc)
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for c in conds:
        lines += [f"option temp={c.temp}", f"alter Vdd dc={c.supply}"]
        for code in codes:
            for k in range(3):
                lines.append(f"alter Vb{k} dc={c.supply if (code >> k) & 1 else 0}")
            for v in vctrls:
                lines += [f"alter Vctrl dc={v}", f"tran 2p {stop} {start}", f"write {c.tag}_c{code}_v{round(v * 1000)}.raw v(v0p) v(v0n)", "destroy all"]
    text = text.replace(".end\n", "") if text.rstrip().endswith(".end") else text
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def freq(p):
    """Frequency and swing over the last half of the saved window (a weak corner still settles after 8 ns)."""
    w = spice.Waves(p)
    y = w["v(v0p)"] - w["v(v0n)"]
    e, s = crossings(w.t, y)
    r = e[s > 0]
    r = r[len(r) // 2:]
    return (len(r) - 1) / (r[-1] - r[0]), float(np.ptp(y[w.t >= r[0]]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="cond:rcorner,...")
    ap.add_argument("--codes", default="0,1,2,3,4,5,6,7")
    ap.add_argument("--vctrl", default="0.7,0.95,1.2,1.45")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--stop", default="14n")
    ap.add_argument("--start", default="8n")
    ap.add_argument("--vco-params", default="", help="overrides on the VCO instance, e.g. 'sw=5 varw=4.5 varvm=4'")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    groups = {}
    for x in a.cases.split(","):
        tag, rc = x.split(":")
        c = Condition.parse(tag)
        groups.setdefault((c.process, rc), []).append(c)
    codes = [int(x) for x in a.codes.split(",")]
    vs = [float(x) for x in a.vctrl.split(",")]
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + a.tag)
    jobs = [(deck(p, rc, cs, codes, vs, camp, a.stop, a.start, a.vco_params), camp / f"{p}_{rc}", dict(timeout_s=7200, meta=dict(process=p, rcorner=rc, conditions=[c.tag for c in cs], codes=codes, vctrl=vs, stop=a.stop, start=a.start, vco_params=a.vco_params))) for (p, rc), cs in groups.items()]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)
    out = {}
    for (p, rc), cs in groups.items():
        for c in cs:
            rows = {}
            print(f"{c.tag} R {rc}: GHz (mVpp at code {codes[0]}), Vctrl " + " ".join(f"{v:6.2f}" for v in vs))
            for code in codes:
                fs, sw = [], []
                for v in vs:
                    q = camp / f"{p}_{rc}" / f"{c.tag}_c{code}_v{round(v * 1000)}.raw"
                    f, s = freq(q) if q.exists() else (float("nan"), float("nan"))
                    fs.append(f)
                    sw.append(s)
                rows[code] = dict(f=fs, swing=sw)
                print(f"   code {code}: " + " ".join(f"{f / 1e9:6.3f}" for f in fs) + f"    {np.nanmean(sw) * 1e3:4.0f} mVpp", flush=True)
            out[f"{c.tag}:{rc}"] = rows
    (camp / "summary.json").write_text(json.dumps(dict(codes=codes, vctrl=vs, table=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
