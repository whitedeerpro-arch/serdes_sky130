"""Monitor comparator (serdes_cmp) trip points over PVT x input common mode, real bandgap bias, from a slow triangle.

    uv run python analog/common/monitor/tb/cmp_trip/run.py [--cms 0.6,0.7,...] [--ramp-mv 30] [--ramp-us 60]
        [--cmp-params "win=16 lin=2"] [--ncopy 1] [--workers 1]

inn = Vcm, inp = Vcm + a triangle -A .. +A .. -A (A = --ramp-mv, --ramp-us per edge).  The rising and falling output
crossings of VDD / 2 give the input difference at each trip; their mean is the static offset (systematic only: local
mismatch is cmp_mc) and half their difference the dynamic lag (delay x ramp rate).  A DC sweep through the
comparator's ~1e6 gain stalls in gmin stepping, the transient does not.  One deck per MOS corner (resistor tt), supply
and temperature in the control block; also the supply current of the comparator before the first crossing.
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
TEMPLATE = HERE / "tb_cmp_trip_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/monitor/cmp_trip"
CMS = "0.6,0.7,0.8,0.9,1.0,1.1,1.2,1.3,1.4,1.5,1.6,1.7"
T0 = 1e-6


def tag(proc, v, t, cm):
    return f"{proc}_v{round(v * 1000)}_t{t}_cm{round(cm * 1000)}"


def pwl(a, tr):
    return f"0 {-a:.6g} {T0:.6g} {-a:.6g} {T0 + tr:.6g} {a:.6g} {T0 + 2 * tr:.6g} {-a:.6g}"


def deck(proc, cms, a_v, tr, params, ncopy, headroom):
    vals = spice.corner_values(Condition(proc, 1.8, 27))
    text = spice.render(TEMPLATE, **vals, SECTION=proc, CMP_PARAMS=params, NCOPY=ncopy, PWL=pwl(a_v, tr))
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    tend = T0 + 2 * tr
    for v in SUPPLY_V:
        for t in TEMP_C:
            lines += [f"option temp={t}", f"alter Vdd dc={v}"]
            for cm in cms:
                if cm > v - headroom:
                    continue
                lines += [f"alter Vn dc={cm}", f"tran {tr / 3000:.4g} {tend:.6g} 0 {tr / 3000:.4g}",
                          f"meas tran tup when v(out)={v / 2:.4f} rise=1", f"meas tran tdn when v(out)={v / 2:.4f} fall=1",
                          f"meas tran idd avg i(Vmeas) from={T0 * 0.2:.4g} to={T0 * 0.9:.4g}",
                          f"meas tran omin min v(out) from={T0 * 0.5:.4g} to={T0 + 0.1 * tr:.4g}",
                          f"meas tran omax max v(out) from={T0 + 0.9 * tr:.4g} to={T0 + 1.1 * tr:.4g}",
                          f"wrdata {tag(proc, v, t, cm)}.tsv tup tdn idd omin omax", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def read(path, a_v, tr, v):
    l = path.read_text().split("\n")
    names, vals = l[0].split(), [float(x) for x in l[1].split()]
    d = dict(zip(names, vals))
    up = -a_v + 2 * a_v * (d["tup"] - T0) / tr
    dn = a_v - 2 * a_v * (d["tdn"] - T0 - tr) / tr
    return dict(trip_up=up, trip_dn=dn, offset=(up + dn) / 2, lag=(up - dn) / 2, idd=d["idd"],
                rails=bool(d["omin"] < 0.1 * v and d["omax"] > 0.9 * v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cms", default=CMS)
    ap.add_argument("--ramp-mv", type=float, default=30)
    ap.add_argument("--ramp-us", type=float, default=60)
    ap.add_argument("--headroom", type=float, default=0.15, help="skip common modes above VDD - headroom")
    ap.add_argument("--cmp-params", default="")
    ap.add_argument("--ncopy", type=int, default=1)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--processes", default=",".join(PROCESS))
    a = ap.parse_args()
    cms = [float(x) for x in a.cms.split(",")]
    a_v, tr = a.ramp_mv * 1e-3, a.ramp_us * 1e-6
    procs = a.processes.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, cms, a_v, tr, a.cmp_params, a.ncopy, a.headroom), camp / p, dict(timeout_s=7200, meta=dict(process=p))) for p in procs]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in procs:
        for v in SUPPLY_V:
            for t in TEMP_C:
                for cm in cms:
                    f = camp / p / f"{tag(p, v, t, cm)}.tsv"
                    if f.exists():
                        try:
                            rows.append(dict(process=p, supply=v, temp=t, cm=cm, **read(f, a_v, tr, v)))
                        except (ValueError, KeyError, IndexError):
                            rows.append(dict(process=p, supply=v, temp=t, cm=cm, failed=True))
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), rows=rows), indent=1))
    print(f"{len(rows)} points; static offset / lag (mV) and supply current by common mode (ramp {a.ramp_mv:.0f} mV per {a.ramp_us:.0f} us):")
    for cm in cms:
        r = [x for x in rows if x["cm"] == cm]
        if not r:
            continue
        ok = [x for x in r if not x.get("failed") and x["rails"] and np.isfinite(x["offset"])]
        bad = [f"{x['process']} {x['supply']} {x['temp']}" for x in r if x not in ok]
        if not ok:
            print(f"  cm {cm:.2f} V: none clean ({bad[:4]})")
            continue
        off = np.array([x["offset"] for x in ok]) * 1e3
        lag = np.array([x["lag"] for x in ok]) * 1e3
        idd = np.array([x["idd"] for x in ok]) * 1e6
        print(f"  cm {cm:.2f} V: {len(ok)}/{len(r)} clean | offset {off.min():+.2f} .. {off.max():+.2f} | lag {lag.min():.2f} .. {lag.max():.2f} | "
              f"I {idd.min():.2f}-{idd.max():.2f} uA" + (f" | not clean: {bad[:4]}" if bad else ""))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
