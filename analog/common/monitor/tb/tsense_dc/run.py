"""Monitor temperature sense (serdes_tsense_vbe vs serdes_vref_gnd): trip temperature of every ladder code over
MOS corner x resistor corner x supply, real bandgap bias.

    uv run python analog/common/monitor/tb/tsense_dc/run.py [--rcorners tt,ll,hh] [--ts "rs=23k"] [--lad "r0=85.6k rstep=1.57k"]
        [--ncopy 4] [--workers 2]

One deck per library section; each supply runs `dc temp -40 125 1` and writes the sense voltage vs and the 16 ladder taps.
Code k trips (comparator vs > tap_k flips) at the temperature where vs(T) = tap_k(T); a code above the sense voltage
over the whole range never trips.  Reported: per code the trip temperature spread over the conditions (systematic part;
local mismatch: tsense_mc), and the slope of vs.  The comparator's own offset (cmp_dc / cmp_mc) is converted with the
slope of vs - tap.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS, SUPPLY_V, Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_tsense_dc_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/monitor/tsense_dc"
TAPS = [f"v(xlad.t{k})" for k in range(16)]


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def deck(proc, rc, ts, lad, ncopy):
    vals = spice.corner_values(Condition(proc, 1.8, 27))
    text = spice.render(TEMPLATE, **vals, SECTION=section(proc, rc), TS_PARAMS=ts, LAD_PARAMS=lad, NCOPY=ncopy)
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    for v in SUPPLY_V:
        lines += [f"alter Vdd dc={v}", "dc temp -40 125 1", f"wrdata {proc}_{rc}_v{round(v * 1000)}.tsv v(vs) " + " ".join(TAPS) + " i(Vi0)", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def trips(path):
    d = np.loadtxt(path, skiprows=1)
    t, vs, taps = d[:, 0], d[:, 1], d[:, 2:18]
    out = []
    for k in range(16):
        g = vs - taps[:, k]                     # falls with temperature
        s = np.where(np.diff(np.sign(g)) != 0)[0]
        out.append(float(t[s[0]] + g[s[0]] * (t[s[0] + 1] - t[s[0]]) / (g[s[0]] - g[s[0] + 1])) if len(s) else None)
    i27 = int(np.argmin(abs(t - 27)))
    slope = float(np.polyfit(t[(t >= -40) & (t <= 85)], (vs - taps[:, 8])[(t >= -40) & (t <= 85)], 1)[0])
    return dict(trip_c=out, vs27=float(vs[i27]), tap0_27=float(taps[i27, 0]), tap15_27=float(taps[i27, 15]), slope_v_per_k=slope)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcorners", default="tt,ll,hh")
    ap.add_argument("--ts", default="rs=23k")
    ap.add_argument("--lad", default="r0=85.6k rstep=1.57k")
    ap.add_argument("--ncopy", type=int, default=4)
    ap.add_argument("--workers", type=int, default=2)
    a = ap.parse_args()
    rcs = a.rcorners.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, rc, a.ts, a.lad, a.ncopy), camp / f"{p}_{rc}", dict(timeout_s=1800, meta=dict(process=p, rcorner=rc))) for p in PROCESS for rc in rcs]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in PROCESS:
        for rc in rcs:
            for v in SUPPLY_V:
                f = camp / f"{p}_{rc}" / f"{p}_{rc}_v{round(v * 1000)}.tsv"
                if f.exists():
                    rows.append(dict(process=p, rcorner=rc, supply=v, **trips(f)))
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(f"{len(rows)} conditions (MOS x R x VDD); vs at 27 C {min(r['vs27'] for r in rows):.3f}-{max(r['vs27'] for r in rows):.3f} V, "
          f"slope of vs - tap {min(r['slope_v_per_k'] for r in rows) * 1e3:.2f} .. {max(r['slope_v_per_k'] for r in rows) * 1e3:.2f} mV/K")
    print(" code | trip temperature C: min / median / max  (spread)")
    for k in range(16):
        x = [r["trip_c"][k] for r in rows]
        got = np.array([v for v in x if v is not None])
        if len(got) == 0:
            print(f"  {k:3d} | never trips in -40..125 C")
            continue
        print(f"  {k:3d} | {got.min():7.1f} / {np.median(got):7.1f} / {got.max():7.1f}  ({got.max() - got.min():5.1f} K)" + (f"  [{len(x) - len(got)} no trip]" if len(got) < len(x) else ""))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
