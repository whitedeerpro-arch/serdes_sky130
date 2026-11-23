"""Bandgap and constant-swing reference over PVT x resistor corner (operating points).

    uv run python analog/bias/tb/bandgap_pvt/run.py [--rcorners tt,ll,hh]

analog/bias/spice/bandgap.spice.  One deck per library section (MOS corner x resistor corner:
tt, ss, ff, sf, fs and their _ll / _hh combinations), supply and temperature in the control block.
Per condition: vbg, the reference current into 0.7 V, I * R into a high_po load (swing proxy), the
core and V->I amplifier input errors, the error-amplifier input common mode, and the source-drain
margin of the vbg-branch PMOS (Xm3) and of the V->I PMOS (Xmv) above their vdsat.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_bandgap_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/bias/bandgap_pvt"
VEC = {"vcm": "v(vcm)", "vbg": "v(vbg)", "iref": "i(Vi0)", "ir": "v(i1)", "err_core": "v(xbg.ta)-v(xbg.tb)", "err_vi": "v(xbg.s)-v(vbg)",
       "cm": "v(xbg.ta)", "vg": "v(vg)", "vgi": "v(vgi)",
       "m3_margin": "(v(vdd)-v(vbg))-@m.xbg.xm3.xmos.msky130_fd_pr__pfet_01v8_lvt[vdsat]",
       "mv_margin": "(v(vdd)-v(xbg.s))-@m.xbg.xmv.xmos.msky130_fd_pr__pfet_01v8_lvt[vdsat]"}


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"          # tt + resistor corner is the plain ll / hh section


def deck(proc, rc):
    c0 = Condition(proc, 1.8, 27)
    vals = spice.corner_values(c0)
    text = spice.render(TEMPLATE, **vals, SECTION=section(proc, rc))
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    for v in SUPPLY_V:
        for t in TEMP_C:
            n = f"{proc}_{rc}_v{round(v * 1000)}_t{t}"
            lines += [f"option temp={t}", f"alter Vdd dc={v}", "op"] + [f"let {k}={e}" for k, e in VEC.items()] + [
                f"wrdata {n}.tsv " + " ".join(VEC), "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def read(path):
    l = path.read_text().split("\n")
    return dict(zip(l[0].split(), (float(x) for x in l[1].split())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcorners", default="tt,ll,hh")
    a = ap.parse_args()
    rcs = a.rcorners.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, rc), camp / f"{p}_{rc}", dict(timeout_s=1200, meta=dict(process=p, rcorner=rc))) for p in PROCESS for rc in rcs]
    for ex in spice.run_many(jobs, workers=4, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in PROCESS:
        for rc in rcs:
            for v in SUPPLY_V:
                for t in TEMP_C:
                    n = f"{p}_{rc}_v{round(v * 1000)}_t{t}"
                    f = camp / f"{p}_{rc}" / f"{n}.tsv"
                    if f.exists():
                        rows.append(dict(process=p, rcorner=rc, supply=v, temp=t, **read(f)))
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    col = lambda k, sel=None: np.array([r[k] for r in rows if sel is None or sel(r)])
    print(f"{len(rows)} conditions")
    for k, scale, unit in (("vcm", 1, "V"), ("vbg", 1, "V"), ("iref", 1e6, "uA"), ("ir", 1e3, "mV"), ("err_core", 1e3, "mV"), ("err_vi", 1e3, "mV"),
                           ("cm", 1, "V"), ("vg", 1, "V"), ("vgi", 1, "V"), ("m3_margin", 1e3, "mV"), ("mv_margin", 1e3, "mV")):
        x = col(k) * scale
        print(f"  {k:10s} {x.min():9.4f} .. {x.max():9.4f} {unit}")
    print("  per resistor corner (all MOS corners, supplies, temperatures):")
    for rc in rcs:
        sel = lambda r, rc=rc: r["rcorner"] == rc
        print(f"    {rc}: vbg {col('vbg', sel).min():.4f}..{col('vbg', sel).max():.4f} V  iref {col('iref', sel).min() * 1e6:.2f}..{col('iref', sel).max() * 1e6:.2f} uA"
              f"  I*R {col('ir', sel).min() * 1e3:.2f}..{col('ir', sel).max() * 1e3:.2f} mV")
    for t in TEMP_C:
        sel = lambda r, t=t: r["temp"] == t and r["rcorner"] == "tt"
        print(f"    tt-R, {t:4d} C: vbg {col('vbg', sel).min():.4f}..{col('vbg', sel).max():.4f} V")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
