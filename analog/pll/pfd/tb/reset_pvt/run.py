"""PFD reset width (UP and DN pulse width at zero phase) over 45 conditions, with the k = 4 steering CP's switch
inputs as the load (PLL closure step 5: the lock detector's tau must exceed it).

    uv run python analog/pll/pfd/tb/reset_pvt/run.py [--workers 1]

Deck of analog/pll/pfd/tb/pfd_cp_mc (real bias, PFD + CP, CP output held at 1.15 V), nominal models; ref and fb
coincide (zero phase) for 4 periods, then fb 40 ps late for 2 periods.  Per condition: UP and DN widths in the last
zero-phase period (the reset width) and the UP width with fb 40 ps late (reset width + 40 ps if the PFD is linear
there).  One deck per MOS corner and supply (the clocks swing to that supply), temperature in the control block.
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

from serdes_flow import bias, spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

_s = importlib.util.spec_from_file_location("pfd_cp_mc", ROOT / "analog/pll/pfd/tb/pfd_cp_mc/run.py")
pm = importlib.util.module_from_spec(_s)
_s.loader.exec_module(pm)
RESULTS = ROOT / "results/analog/pll/pfd/reset_pvt"
TREF, T0, TR = 4e-9, 1e-9, 30e-12
SHIFT = [0.0] * 4 + [40e-12] * 2


def deck(proc, v):
    times = [T0 + k * TREF for k in range(len(SHIFT))]
    c = Condition(proc, v, 27)
    text = spice.render(pm.TEMPLATE, **spice.corner_values(c), REF_PWL=pm.pwl(times, [0.0] * len(times), v),
                        FB_PWL=pm.pwl(times, SHIFT, v), CP_PARAMS=pm.CP_PARAMS, VOUT="1.15")
    text = bias.real(text)
    text = text.replace("Ibuf vdd ibuf 10u", "XIbuf ibuf vgi_bias vdd serdes_bias_pcopy n=4")
    tend = times[-1] + TREF
    z, late = times[3], times[4]
    h = v / 2
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    for t in TEMP_C:
        lines += [f"option temp={t}", f"tran 1p {tend:.5e} 0 5p",
                  f"meas tran upw trig v(up) val={h} rise=1 td={z - 0.5e-9:.4e} targ v(up) val={h} fall=1 td={z - 0.5e-9:.4e}",
                  f"meas tran dnw trig v(dn) val={h} rise=1 td={z - 0.5e-9:.4e} targ v(dn) val={h} fall=1 td={z - 0.5e-9:.4e}",
                  f"meas tran uplate trig v(up) val={h} rise=1 td={late - 0.5e-9:.4e} targ v(up) val={h} fall=1 td={late - 0.5e-9:.4e}",
                  f"wrdata {proc}_v{round(v * 1000)}_t{t}.tsv upw dnw uplate", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, v), camp / f"{p}_v{round(v * 1000)}", dict(timeout_s=3600, meta=dict(process=p, supply=v))) for p in PROCESS for v in SUPPLY_V]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}", flush=True)
    rows = []
    for p in PROCESS:
        for v in SUPPLY_V:
            for t in TEMP_C:
                f = camp / f"{p}_v{round(v * 1000)}" / f"{p}_v{round(v * 1000)}_t{t}.tsv"
                if f.exists():
                    l = f.read_text().split("\n")
                    d = dict(zip(l[0].split(), (float(x) for x in l[1].split())))
                    rows.append(dict(process=p, supply=v, temp=t, **{k: d[k] for k in ("upw", "dnw", "uplate")}))
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    print(f"{len(rows)} conditions; reset width (UP / DN at zero phase) and UP with fb 40 ps late, ps")
    for k in ("upw", "dnw", "uplate"):
        x = sorted((r[k], f"{r['process']} {r['supply']} {r['temp']}") for r in rows)
        print(f"  {k:6s} {x[0][0] * 1e12:6.0f} ({x[0][1]}) .. {x[-1][0] * 1e12:6.0f} ({x[-1][1]})")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
