"""PLL Vctrl window detector (analog/pll/coarse/spice/vctrl_window.spice): thresholds and function over MOS x resistor
corner x supply x temperature, real bandgap bias, codes at their design values.

    uv run python analog/pll/coarse/tb/window_dc/run.py [--rcorners tt,ll,hh] [--code-lo 5] [--code-hi 3] [--workers 1]

One deck per library section; per supply and temperature three operating points: z = 1.1 V (both outputs low; the
ladder voltages vlo, vhi and the detector's supply current), z = vlo_design - 50 mV (lo = 1) and z = vhi_design + 50 mV
(hi = 1).  The trip error against the design values (vlo = 0.900 V at code 5, vhi = VDD - 0.410 V at code 3; ideal 5 uA
ladder current) is the ladder error here plus the comparator's systematic offset from analog/common/monitor/tb/cmp_trip
(-1.0 .. +0.3 mV for inputs 0.6 V .. VDD - 0.40 V); a DC sweep through the comparator's gain stalls in gmin stepping.
The random part is window_mc.
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
TEMPLATE = HERE / "tb_window_dc_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/coarse/window_dc"


def design(code_lo, code_hi, vdd):
    return (160e3 + code_lo * 4e3) * 5e-6, vdd - (64e3 + code_hi * 6e3) * 5e-6


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


VEC = "v(xw.vlo) v(xw.vhi) v(hi) v(lo) i(Vmeas)"


def tag(p, rc, v, t, which):
    return f"{p}_{rc}_v{round(v * 1000)}_t{t}_{which}"


def deck(proc, rc, code_lo, code_hi):
    vals = spice.corner_values(Condition(proc, 1.8, 27))
    text = spice.render(TEMPLATE, **vals, SECTION=section(proc, rc), CODE_LO=code_lo, CODE_HI=code_hi)
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    for v in SUPPLY_V:
        lo, hi = design(code_lo, code_hi, v)
        for t in TEMP_C:
            lines += [f"option temp={t}", f"alter Vdd dc={v}"]
            for which, z in (("mid", 1.1), ("below", lo - 0.05), ("above", hi + 0.05)):
                lines += [f"alter Vz dc={z:.4f}", "op", f"wrdata {tag(proc, rc, v, t, which)}.tsv {VEC}", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def read(path):
    l = path.read_text().split("\n")
    return [float(x) for x in l[1].split()][1:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcorners", default="tt,ll,hh")
    ap.add_argument("--code-lo", type=int, default=5)
    ap.add_argument("--code-hi", type=int, default=3)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    rcs = a.rcorners.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, rc, a.code_lo, a.code_hi), camp / f"{p}_{rc}", dict(timeout_s=3600, meta=dict(process=p, rcorner=rc))) for p in PROCESS for rc in rcs]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in PROCESS:
        for rc in rcs:
            for v in SUPPLY_V:
                lo_d, hi_d = design(a.code_lo, a.code_hi, v)
                for t in TEMP_C:
                    r = dict(process=p, rcorner=rc, supply=v, temp=t, lo_design=lo_d, hi_design=hi_d)
                    try:
                        mid = read(camp / f"{p}_{rc}" / f"{tag(p, rc, v, t, 'mid')}.tsv")
                        below = read(camp / f"{p}_{rc}" / f"{tag(p, rc, v, t, 'below')}.tsv")
                        above = read(camp / f"{p}_{rc}" / f"{tag(p, rc, v, t, 'above')}.tsv")
                    except (OSError, IndexError, ValueError):
                        r["missing"] = True
                        rows.append(r)
                        continue
                    h = v / 2
                    r.update(vlo=mid[0], vhi=mid[1], idd=mid[4],
                             function=bool(mid[2] < h and mid[3] < h and below[3] > h and below[2] < h and above[2] > h and above[3] < h))
                    rows.append(r)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    ok = [r for r in rows if not r.get("missing")]
    print(f"{len(ok)}/{len(rows)} conditions; function (both low inside, lo below, hi above): {sum(r['function'] for r in ok)}/{len(ok)}")
    for key, dk in (("vlo", "lo_design"), ("vhi", "hi_design")):
        e = np.array([r[key] - r[dk] for r in ok]) * 1e3
        print(f"  {key} - design {e.min():+.1f} .. {e.max():+.1f} mV")
        for rc in rcs:
            x = np.array([r[key] - r[dk] for r in ok if r["rcorner"] == rc]) * 1e3
            print(f"      R {rc}: {x.min():+.1f} .. {x.max():+.1f} mV")
    idd = np.array([r["idd"] for r in ok]) * 1e6
    print(f"  detector current through vdd (vhi string + comparators, excluding the copies) {idd.min():.1f} .. {idd.max():.1f} uA")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
