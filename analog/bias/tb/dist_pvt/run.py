"""Bias distribution (bandgap -> PMOS copies -> module diodes) over PVT x resistor corner, operating points.

    uv run python analog/bias/tb/dist_pvt/run.py [--rcorners tt,ll,hh]

analog/bias/spice/bias_dist.spice.  One deck per library section (MOS corner x resistor
corner), supply and temperature in the control block (as bandgap_pvt).  Per condition: the copy
currents, the bias voltages next to the ideal-reference ones the benches used so far, the swing
proxy I_tail * R_load of a CML half circuit (real: high_po load, constant swing; ideal: ideal load and
0.85 mA), and each copy's source-drain voltage above vdsat.
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
TEMPLATE = HERE / "tb_bias_dist_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/bias/dist_pvt"
P = "msky130_fd_pr__pfet_01v8_lvt"
VEC = {"vbg": "v(vbg)", "iref": "i(Vi0)", "i_cml": "i(Vmcml)", "i_ctle": "i(Vmctle)", "i_cp": "i(Vmcp)",
       "v_cml": "v(vcml)", "v_cml_i": "v(vbias_i)", "v_ctle": "v(vctle)", "v_ctle_i": "v(vctle_i)",
       "vbn": "v(vbn)", "vbn_i": "v(vbn_i)", "vbp": "v(vbp)", "vbp_i": "v(vbp_i)",
       "swing": "1.0-v(dr)", "swing_i": "1.0-v(dri)", "vgi": "v(vgi)",
       "m_cml": f"(v(vdd)-v(ocml))-@m.xccml.xp.xmos.{P}[vdsat]",
       "m_ctle": f"(v(vdd)-v(octle))-@m.xcctle.xp.xmos.{P}[vdsat]",
       "m_cp": f"(v(vdd)-v(ocp))-@m.xccp.xp.xmos.{P}[vdsat]",
       "m_mv": f"(v(vdd)-v(xref.xbg.s))-@m.xref.xbg.xmv.xmos.{P}[vdsat]"}


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def deck(proc, rc):
    vals = spice.corner_values(Condition(proc, 1.8, 27))
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
    for ex in spice.run_many(jobs, workers=3, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in PROCESS:
        for rc in rcs:
            for v in SUPPLY_V:
                for t in TEMP_C:
                    f = camp / f"{p}_{rc}" / f"{p}_{rc}_v{round(v * 1000)}_t{t}.tsv"
                    if f.exists():
                        rows.append(dict(process=p, rcorner=rc, supply=v, temp=t, **read(f)))
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    col = lambda k, sel=None: np.array([r[k] for r in rows if sel is None or sel(r)])
    print(f"{len(rows)} conditions")
    for k, sc, u in (("iref", 1e6, "uA"), ("i_cml", 1e6, "uA"), ("i_ctle", 1e6, "uA"), ("i_cp", 1e6, "uA"),
                     ("swing", 1e3, "mV"), ("swing_i", 1e3, "mV"), ("m_cml", 1e3, "mV"), ("m_ctle", 1e3, "mV"),
                     ("m_cp", 1e3, "mV"), ("m_mv", 1e3, "mV")):
        x = col(k) * sc
        print(f"  {k:8s} {x.min():9.2f} .. {x.max():9.2f} {u}")
    for k in ("cml", "ctle"):
        d = (col(f"v_{k}") - col(f"v_{k}_i")) * 1e3
        print(f"  v_{k} - ideal  {d.min():+.1f} .. {d.max():+.1f} mV")
    for k in ("vbn", "vbp"):
        d = (col(k) - col(f"{k}_i")) * 1e3
        print(f"  {k} - ideal  {d.min():+.1f} .. {d.max():+.1f} mV")
    r = col("i_cml") / col("iref")
    print(f"  i_cml / iref {r.min():.3f} .. {r.max():.3f} (nominal 21.25)")
    for rc in rcs:
        sel = lambda x, rc=rc: x["rcorner"] == rc
        print(f"    {rc}: swing {col('swing', sel).min() * 1e3:.1f}..{col('swing', sel).max() * 1e3:.1f} mV, ideal {col('swing_i', sel).min() * 1e3:.1f}..{col('swing_i', sel).max() * 1e3:.1f} mV")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
