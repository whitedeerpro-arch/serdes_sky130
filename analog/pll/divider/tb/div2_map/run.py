"""Feasible region of one CML divide-by-2: output swing against the clock's common mode and swing at its gates.

    uv run python analog/pll/divider/tb/div2_map/run.py [cond:passive ...] [--cm 0.85,0.95,1.05,1.16,1.27] [--pp 150,215,270,350]
        [--load rx|pll] [--latch wtail=72 ...] [--fin 2e9] [--workers 4] [--tag x]
    uv run python analog/pll/divider/tb/div2_map/run.py --from-prescaler <tb/pvt/rcorner.py summary.json> [--load rx] [--latch whold=40]

--from-prescaler: every condition of that campaign at the clock common mode and swing its first stage saw there, one point each.

cond:passive, e.g. fs_v1650_t85:hh; hh / ll are joint resistor and capacitor library corners.  Real bias, PDK resistors, 2 GHz
sine at the clock gates by default (no follower, no capacitor: any clock interface is a point on this map).  One deck per condition, the
map in its control block.  Load: rx = both outputs into a W24 nf4 buffer (the read divider); pll = q only, m open.

Per point, over the last 10 of 20 ns: output swing, crossings (20 wanted), and for the first latch the tail current, tail
VDS - VDSAT, the clock steering (max - min of I_track) / mean(I_track + I_hold), and the mean gm of a hold device, whose gm R is
the regeneration gain.  A clock interface is judged by where it lands on the map, without a chain simulation.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_div2_map_ngspice.cir.in"
RESULTS = ROOT / "results/analog/pll/divider/div2_map"
NF = "msky130_fd_pr__nfet_01v8"
LVT = "msky130_fd_pr__nfet_01v8_lvt"
DEFAULT = ["fs_v1650_t85:hh", "ss_v1650_t85:hh", "fs_v1650_t85:ll", "tt_v1800_t27:tt"]
STOP, SAVE_FROM, WINDOW = 20e-9, 8e-9, 10e-9
LOADS = {
    "rx": "Xbq qp qn oqp oqn vbias vdd 0 serdes_cml_buffer wn=24 nfin=4 wt=12 rload=600\nXbm mp mn omp omn vbias vdd 0 serdes_cml_buffer wn=24 nfin=4 wt=12 rload=600\nCo1 oqp 0 30f\nCo2 oqn 0 30f\nCo3 omp 0 30f\nCo4 omn 0 30f",
    "pll": "Xbq qp qn oqp oqn vbias vdd 0 serdes_cml_buffer wn=24 wt=12 rload=600\nCl1 qp 0 5f\nCl2 qn 0 5f\nCo1 oqp 0 30f\nCo2 oqn 0 30f",
}


def case(cm, pp):
    return f"c{round(cm * 1000)}_p{round(pp)}"


def deck(c, rc, cms, pps, load, latch, camp, fin=2e9):
    blocks = []
    for cm in cms:
        for pp in pps:
            blocks.append("\n".join([f"alter Vcm dc={cm}", f"alter Va dc={pp * 1e-3 / 4:.6f}", f"tran 4p {STOP:.4e} {SAVE_FROM:.4e} 4p",
                                     f"let itail=@m.xmaster.xtail.xmos.{NF}[id]", f"let vdsat=@m.xmaster.xtail.xmos.{NF}[vdsat]",
                                     f"let itrack=@m.xmaster.xct.xmos.{LVT}[id]", f"let ihold=@m.xmaster.xch.xmos.{LVT}[id]",
                                     f"let gmh=@m.xmaster.xhp.xmos.{LVT}[gm]",
                                     f"write {case(cm, pp)}.raw v(qp) v(qn) v(mp) v(mn) v(xmaster.tail) itail vdsat itrack ihold gmh", "destroy all"]))
    text = spice.render(TEMPLATE, **spice.corner_values(c), LATCH=" ".join(latch), LOAD=LOADS[load], CASES="\n".join(blocks), W=f"{2 * np.pi * fin:.8e}")
    camp.mkdir(parents=True, exist_ok=True)
    return bias.section(rcorner.to_pdk(bias.real(text), camp), c.process, rc)


def analyse(path):
    w = spice.Waves(path)
    sel = w.t > w.t[-1] - WINDOW
    t = w.t[sel]
    q = (w["v(qp)"] - w["v(qn)"])[sel]
    it, ih = w["itrack"][sel], w["ihold"][sel]
    tail = w["v(xmaster.tail)"][sel]
    return dict(swing=float(np.ptp(q)), crossings=len(crossings(t, q)[0]), itail=float(np.mean(w["itail"][sel])),
                headroom=float(np.mean(tail - w["vdsat"][sel])), tail=float(np.mean(tail)), steering=float(np.ptp(it) / np.mean(it + ih)), gm_hold=float(np.mean(w["gmh"][sel])),
                cm_out=float(np.mean((w["v(qp)"] + w["v(qn)"])[sel] / 2)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("conds", nargs="*", default=DEFAULT)
    ap.add_argument("--cm", default="0.85,0.95,1.05,1.16,1.27")
    ap.add_argument("--pp", default="150,215,270,350")
    ap.add_argument("--load", default="rx", choices=sorted(LOADS))
    ap.add_argument("--latch", action="append", default=[])
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="")
    ap.add_argument("--fin", type=float, default=2e9)
    ap.add_argument("--from-prescaler")
    a = ap.parse_args()
    cms = [float(x) for x in a.cm.split(",")]
    pps = [float(x) for x in a.pp.split(",")]
    latch = a.latch or ["wdata=20", "whold=80", "wclock=64", "wtail=72", "nftail=24", "rload=600"]
    if a.latch:
        given = dict(x.split("=") for x in a.latch)
        latch = [f"{k}={given.get(k, v)}" for k, v in (("wdata", 20), ("whold", 80), ("wclock", 64), ("wtail", 72), ("nftail", 24), ("rload", 600))]
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + a.tag)
    conds = [x.split(":") for x in a.conds]
    points = {}
    if a.from_prescaler:
        src = json.loads((ROOT / a.from_prescaler).read_text())
        conds = [[t, src["rpdk"]] for t in src["rows"]]
        points = {t: (round(r["q2 clock"]["cm"], 3), round(r["q2 clock"]["swing"] * 1e3)) for t, r in src["rows"].items()}
    jobs = []
    for tag, rc in conds:
        c = Condition.parse(tag)
        one = ([points[tag][0]], [points[tag][1]]) if tag in points else (cms, pps)
        jobs.append((deck(c, rc, one[0], one[1], a.load, latch, camp / f"{tag}_{rc}_snap", a.fin), camp / f"{tag}_{rc}", dict(timeout_s=3600, meta=dict(condition=tag, passive=rc, load=a.load, latch=latch))))
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    out = {}
    if points:
        print(f"passive {conds[0][1]}, load {a.load}, {' '.join(latch)}: output mVpp (crossings) at the first stage's clock of {a.from_prescaler}")
        worst = []
        for tag, rc in conds:
            cm, pp = points[tag]
            p = camp / f"{tag}_{rc}" / f"{case(cm, pp)}.raw"
            if not p.exists():
                print(f"{tag:15s} missing", flush=True)
                continue
            r = analyse(p)
            out[f"{tag}:{rc}"] = dict(cm=cm, pp=pp, **r)
            worst.append((r["swing"], tag))
            print(f"{tag:15s} CM {cm:.3f} pp {pp:4d} | {r['swing'] * 1e3:5.0f} ({r['crossings']}) | Itail {r['itail'] * 1e6:4.0f} uA, VDS-VDSAT {r['headroom'] * 1e3:5.0f} mV", flush=True)
        worst.sort()
        bad = [t for t, v in out.items() if v["crossings"] not in (19, 20, 21)]
        print(f"{len(out)} conditions; wrong crossings {bad}; lowest {worst[0][0] * 1e3:.0f} mVpp at {worst[0][1]}; below 200 mVpp: {[t for v, t in worst if v < 0.2]}")
        (camp / "summary.json").write_text(json.dumps(dict(load=a.load, latch=latch, source=a.from_prescaler, rows=out), indent=1))
        print(camp.relative_to(ROOT))
        return
    for tag, rc in conds:
        rows = {}
        print(f"\n== {tag} {rc}, load {a.load}, {' '.join(latch)}, input {a.fin / 1e9:g} GHz")
        print(f"output swing mVpp (crossings, {round(a.fin * WINDOW)} wanted), clock pp across, common mode down")
        print("  CM V | " + " ".join(f"{p:>10.0f}" for p in pps) + " |  Itail uA  VDS-VDSAT mV  steering  gm_hold mS (at the largest pp)")
        for cm in cms:
            cells, last = [], None
            for pp in pps:
                p = camp / f"{tag}_{rc}" / f"{case(cm, pp)}.raw"
                if not p.exists():
                    cells.append(f"{'-':>10s}")
                    continue
                r = analyse(p)
                rows[case(cm, pp)] = r
                last = r
                cells.append(f"{r['swing'] * 1e3:6.0f}({r['crossings']:2d})")
            extra = f"{last['itail'] * 1e6:9.0f} {last['headroom'] * 1e3:12.0f} {last['steering']:9.2f} {last['gm_hold'] * 1e3:11.2f}" if last else ""
            print(f" {cm:5.2f} | " + " ".join(cells) + " | " + extra, flush=True)
        out[f"{tag}:{rc}"] = rows
    (camp / "summary.json").write_text(json.dumps(dict(cm=cms, pp=pps, load=a.load, latch=latch, fin=a.fin, rows=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
