"""Local /8 + feedback receiver CPEX/RC screening at 2 GHz.

300 mVpp sine through the schematic upstream buffer; tap 5 fF, feedback 20 fF.
Real schematic bias and fixed PDK resistors; explicit 20 uA/40 ps latch kicks.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import re
import sys

import numpy as np
from serdes_flow import bias, clock, project, rcorner, spice
from serdes_flow.corners import Condition

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from review_sim import execute, save_analysis

POINTS = ["tt_v1800_t27:tt", "fs_v1650_t85:hh", "fs_v1650_t-40:hh",
          "ss_v1650_t-40:hh", "sf_v1650_t-40:ll", "ff_v1950_t-40:ll", "ss_v1650_t85:hh"]
STOP, START = 48e-9, 30e-9
DIV = "pll_cml_prescaler8_pdk"
RX = "serdes_cml_to_cmos_pvt_candidate_pdk"


def deck(point, variant, physical, receiver, out, method="trap"):
    tag, rc = point.split(":")
    c = Condition.parse(tag)
    text = spice.render(ROOT / "analog/pll/divider/tb/pvt/tb_prescaler8_lowov_ngspice.cir.in",
                        **spice.corner_values(c), FREQ_HZ=2e9, STOP=f"{STOP:.12g}")
    # Reference cards from the physical generators have exact finger sizes.
    # CPEX includes the receiver's intended bias dummies and junction geometry.
    if variant != "schematic":
        ext = "rcx" if variant == "rcx" else "pex"
        text = text.replace("0 pll_cml_prescaler8\n", f"0 {DIV}\n")
        text = text.replace("Xfb d08p d08n fb0 fb0n vbias vdd 0 serdes_cml_to_cmos_pvt_candidate",
                            f"Xfb d08p d08n fb0 fb0n vbias vdd 0 {RX}")
        # The receiver RC export failed the independent geometry check, so all
        # variants use its preserved coupled CPEX; only /8 changes to native RC.
        includes = f'.include "{physical / (DIV+"_"+ext+".spice")}"\n.include "{receiver / (RX+"_pex.spice")}"\n'
        text = text.replace(".param supply=", includes + ".param supply=")
    # No obsolete 2 GHz full-rate receiver on the upstream buffer in r6q.
    text = re.sub(r"^Xrx .*\n|^Ccm0[pn] .*\n|^\.nodeset v\(xrx.*\n", "", text, flags=re.M)
    text = re.sub(r"^\.nodeset v\(xfb.*\n", "", text, flags=re.M)
    text=text.replace(".options reltol=1e-4 abstol=1p vntol=1u",f".options reltol=1e-4 abstol=1p vntol=1u method={method}")
    # Flat physical instance names differ from schematic paths. Save ports only.
    text = re.sub(r"^\.save [^\n]*(?:\n\+[^\n]*)*\n", "", text, flags=re.M)
    text = re.sub(r"\.control.*?\.endc", "", text, flags=re.S)
    kicks = "\n".join(f"Ik{k} d0{k}p d0{k}n PWL(0 0 1n 0 1.01n 20u 1.05n 20u 1.06n 0)" for k in (2,4,8))
    probes = " ".join(f"v({n})" for n in ("bp","bn","d02p","d02n","d04p","d04n","d08p","d08n","fb0","fb0n"))
    text = text.replace(".end\n", f"{kicks}\n.save {probes}\n.control\nset num_threads=1\ntran 4p {STOP:.12g} 0 4p\nwrdata waveforms.tsv {probes}\nquit\n.endc\n.end\n")
    return bias.section(rcorner.to_pdk_fixed(bias.real(spice.binary_output(text)), out / "resistors"), c.process, rc)


def measure(path, c):
    w = spice.Waves(path)
    rows = {}
    for label, p, n, expected in [("input","bp","bn",2e9), ("q2","d02p","d02n",1e9),
                                  ("q4","d04p","d04n",.5e9), ("q8","d08p","d08n",.25e9),
                                  ("feedback","fb0","fb0n",.25e9)]:
        y = w[p]-w[n]
        stat = clock.period_stats(w.t, y, start=START, stop=STOP, min_cycles=3)
        amp = clock.cycle_amplitudes(w.t, y, START, STOP)
        ok = stat is not None and abs(stat["frequency_hz"]/expected-1) <= .002
        if stat:
            # Also reject irregular/missing periods that a mean alone hides.
            e = clock.edges(w.t, y, start=START, stop=STOP)
            ok = ok and bool(np.max(np.abs(np.diff(e)*expected-1)) <= .02)
        rows[label] = dict(period=stat, amplitude=amp, frequency_passed=ok)
    rows["functional_passed"] = all(r["frequency_passed"] for r in rows.values())
    rows["local_150mV_screen_passed"] = all(rows[n]["amplitude"] is not None and
        rows[n]["amplitude"]["min_pp_v"] >= .150 for n in ("q2","q4","q8"))
    rows["feedback_rail_passed"] = bool(np.min(w["fb0"][w.t>=START]) <= .2*c.supply and
        np.max(w["fb0"][w.t>=START]) >= .8*c.supply)
    return rows


def main():
    global DIV
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--physical-dir", type=Path, required=True)
    ap.add_argument("--top", default=DIV)
    ap.add_argument("--receiver-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--points", nargs="+", default=POINTS)
    ap.add_argument("--variants", nargs="+", default=["schematic","cpex","rcx"])
    ap.add_argument("--workers", type=int, default=2, choices=(1,2))
    ap.add_argument("--method",choices=("trap","gear"),default="trap")
    a = ap.parse_args()
    DIV=a.top
    cases, ids = {}, {}
    for point in a.points:
        for variant in a.variants:
            key = point.replace(":","_") + "_" + variant
            cases[key] = deck(point, variant, a.physical_dir.resolve(), a.receiver_dir.resolve(), a.output_dir.resolve(),a.method), STOP
            ids[key] = point, variant
    paths = execute(cases, a.output_dir, workers=a.workers)
    rows = {k: measure(p, Condition.parse(ids[k][0].split(":")[0])) for k,p in paths.items()}
    save_analysis(a.output_dir, dict(scope=__doc__, cases=ids, rows=rows))


if __name__ == "__main__":
    main()
