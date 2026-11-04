"""Supply rejection of the bias distribution: vdd ripple -> module currents, bias lines, CML swing.

    uv run python analog/common/bias/tb/dist_psrr/run.py [--rcorners tt] [--process tt,ss] [--extra "Cdec vcml 0 5p"] [--workers 3]

Deck of tb/dist_pvt with an AC source on vdd and the swing proxy's load tied to vdd (as in a CML
gate: swing = v(vdd) - v(dr)).  Per MOS corner x resistor corner x supply x temperature, ac 1 kHz ..
3 GHz: |d i / d vdd| of the CML / CTLE / CP copies in % of their DC current per volt, |d v / d vdd| of
the bias lines and of vbg, and |d swing / d vdd| in % per volt.  The ideal references of the benches
so far came from a separate ideal supply: zero by construction.  --extra adds a line to the deck (a
decoupling candidate); the bench's nodes are vbg, vcml, vctle, vbn, vbp, vgi.  The vbias line carries one
tail of 20 / 0.5 nf 4 here, far less gate capacitance than a real CML domain, so the high-frequency numbers
are pessimistic.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS, SUPPLY_V, TEMP_C, Condition
from serdes_flow.project import ROOT

TEMPLATE = ROOT / "analog/common/bias/tb/dist_pvt/tb_bias_dist_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/bias/dist_psrr"
DC = {"i_cml": "i(Vmcml)", "i_ctle": "i(Vmctle)", "i_cp": "i(Vmcp)", "swing": "v(vdd)-v(dr)"}
AC = {"i_cml": "mag(i(Vmcml))", "i_ctle": "mag(i(Vmctle))", "i_cp": "mag(i(Vmcp))", "swing": "mag(1-v(dr))",
      "vbias": "mag(v(vcml))", "vbn": "mag(v(vbn))", "vbp": "mag(v(vbp)-1)", "vbg": "mag(v(vbg))"}
FREQS = (1e3, 1e5, 1e6, 1e7, 1e8, 1e9)


def section(proc, rc):
    if rc == "tt":
        return proc
    return rc if proc == "tt" else f"{proc}_{rc}"


def deck(proc, rc, extra=()):
    text = spice.render(TEMPLATE, **spice.corner_values(Condition(proc, 1.8, 27)), SECTION=section(proc, rc))
    text = "\n".join([*text.split("\n", 1)[:1], *extra, *text.split("\n", 1)[1:]])
    for o, n in (("Vdd vdd 0 @SUPPLY@".replace("@SUPPLY@", "1.8"), "Vdd vdd 0 dc 1.8 ac 1"), ("Vtop top 0 1.0", "Vtop top vdd 0")):
        assert text.count(o) == 1, o
        text = text.replace(o, n)
    lines = [".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale"]
    for v in SUPPLY_V:
        for t in TEMP_C:
            n = f"{proc}_{rc}_v{round(v * 1000)}_t{t}"
            lines += [f"option temp={t}", f"alter Vdd dc={v}", "op"] + [f"let dc_{k}={e}" for k, e in DC.items()]
            lines += [f"wrdata {n}_dc.tsv " + " ".join(f"dc_{k}" for k in DC), "destroy all"]
            lines += ["ac dec 10 1k 3g"] + [f"let {k}={e}" for k, e in AC.items()] + [f"wrdata {n}_ac.tsv " + " ".join(AC), "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def read_dc(p):
    l = p.read_text().split("\n")
    return dict(zip(l[0].split(), (float(x) for x in l[1].split())))


def read_ac(p):
    l = [x.split() for x in p.read_text().strip().split("\n")]
    head, rows = l[0], np.array([[float(v) for v in r] for r in l[1:]])
    return rows[:, 0], {k: rows[:, i] for i, k in enumerate(head) if k != "frequency"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rcorners", default="tt")
    ap.add_argument("--process", default=",".join(PROCESS))
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    rcs = a.rcorners.split(",")
    procs = a.process.split(",")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = [(deck(p, rc, a.extra), camp / f"{p}_{rc}", dict(timeout_s=1800, meta=dict(process=p, rcorner=rc, extra=a.extra))) for p in procs for rc in rcs]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    rows = []
    for p in procs:
        for rc in rcs:
            for v in SUPPLY_V:
                for t in TEMP_C:
                    n = f"{p}_{rc}_v{round(v * 1000)}_t{t}"
                    fdc, fac = camp / f"{p}_{rc}" / f"{n}_dc.tsv", camp / f"{p}_{rc}" / f"{n}_ac.tsv"
                    if not (fdc.exists() and fac.exists()):
                        continue
                    dc = read_dc(fdc)
                    f, ac = read_ac(fac)
                    r = dict(process=p, rcorner=rc, supply=v, temp=t, per_freq={})
                    for fq in FREQS:
                        e = {}
                        for k in ("i_cml", "i_ctle", "i_cp"):
                            e[f"{k}_pct_per_v"] = float(np.interp(np.log(fq), np.log(f), ac[k[0:]])) / abs(dc[f"dc_{k}"]) * 100
                        e["swing_pct_per_v"] = float(np.interp(np.log(fq), np.log(f), ac["swing"])) / abs(dc["dc_swing"]) * 100
                        for k in ("vbias", "vbn", "vbp", "vbg"):
                            e[f"{k}_mv_per_v"] = float(np.interp(np.log(fq), np.log(f), ac[k])) * 1e3
                        r["per_freq"][str(fq)] = e
                    r["worst"] = {k: max(r["per_freq"][str(fq)][k] for fq in FREQS) for k in r["per_freq"][str(FREQS[0])]}
                    rows.append(r)
    (camp / "summary.json").write_text(json.dumps(rows, indent=1))
    print(f"extra: {a.extra}")
    print(f"{len(rows)} conditions; max over conditions (min .. max at each frequency):")
    keys = list(rows[0]["per_freq"][str(FREQS[0])])
    print(f"  {'quantity':20s} " + " ".join(f"{fq:>12.0e}" for fq in FREQS))
    for k in keys:
        print(f"  {k:20s} " + " ".join(f"{max(r['per_freq'][str(fq)][k] for r in rows):12.3g}" for fq in FREQS))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
