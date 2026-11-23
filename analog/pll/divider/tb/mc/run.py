"""Local mismatch Monte Carlo of the PLL CML prescaler (/2 /2 /2) at its stress conditions.

    uv run python analog/pll/divider/tb/mc/run.py [--points fs_v1650_t-40:hh,...] [--samples 200] [--chunk 25] [--seed 1] [--workers 4]
        [--resume <campaign>]

Deck of analog/pll/divider/tb/pvt/rcorner.py (2 GHz sine 0.3 Vpp through the real upstream buffer, real bias, PDK R,
5 fF taps), library section <process>_<rc>_mm: local mismatch only, the global corner stays the process / RC section
(docs/verification/statistics.md).  Per sample over 32-48 ns: period of each output from rising crossings (pass / fail:
1 / 2 / 4 ns within 2 %), differential swing of each output (normal metric: hard floor 150 mVpp, target 200 mVpp,
k = 3.28 for 200 samples), and the lowest first-stage tail node voltage (the FS 1.65 V -40 C headroom question).
Chunks keep their seeds (mc.run_many resumes by chunk).
"""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_spec = importlib.util.spec_from_file_location("div_rcorner", ROOT / "analog/pll/divider/tb/pvt/rcorner.py")
rc_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc_mod)
RESULTS = ROOT / "results/analog/pll/divider/mc"
T0, T1 = 32e-9, 48e-9
OUTS = (("q2", "d02p", "d02n", 1e-9), ("q4", "d04p", "d04n", 2e-9), ("q8", "d08p", "d08n", 4e-9))
FLOOR, TARGET = 0.150, 0.200


def netlist(c, rc, camp):
    text = rc_mod.deck(c, rc, 0.3, [], camp)
    text = re.sub(r"\.control.*?\.endc\s*", "", text, flags=re.S)
    text = re.sub(r"^\.end\s*$", "", text, flags=re.M)
    sec = f"{c.process}_{rc}_mm" if rc != "tt" else f"{c.process}_mm"
    text, n = re.subn(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: m[1] + sec, text, count=1, flags=re.M | re.I)
    assert n == 1
    return text


def analysis():
    lines = [f"tran 4p {T1:.4e} {T0 - 2e-9:.4e} 4p"]
    for name, p, n, per in OUTS:
        # control-mode meas takes no v(a,b): a differential vector first; four rising crossings after T0
        lines += [f"let {name}d = v({p})-v({n})",
                  f"meas tran {name}_ta when {name}d=0 rise=1 from={T0:.4e}", f"meas tran {name}_tb when {name}d=0 rise=4 from={T0:.4e}",
                  f"meas tran {name}_hi max {name}d from={T0:.4e} to={T1:.4e}", f"meas tran {name}_lo min {name}d from={T0:.4e} to={T1:.4e}"]
    lines.append(f"meas tran tail_min min v(xpre.x2.xmaster.tail) from={T0:.4e} to={T1:.4e}")
    return "\n".join(lines)


LETS = {**{f"{n}_per": f"({n}_tb-{n}_ta)/3" for n, *_ in OUTS}, **{f"{n}_sw": f"{n}_hi-{n}_lo" for n, *_ in OUTS}, "tail_min": "tail_min"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="fs_v1650_t-40:hh,fs_v1650_t-40:ll,fs_v1650_t85:hh,fs_v1650_t85:ll,ss_v1650_t-40:hh,ff_v1950_t-40:ll,tt_v1800_t27:tt")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--chunk", type=int, default=8, help="samples per ngspice; this bench grows ~165-200 MB per sample (3 GB cap)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--resume")
    ap.add_argument("--analyse", help="campaign: read every chunk's rows as far as they go (a chunk cut by the memory cap keeps "
                                      "its first samples: sample k of a seed is fixed, the cut depends on memory, not on values)")
    a = ap.parse_args()
    if a.analyse:
        camp = ROOT / a.analyse
        groups = {}
        for spec in a.points.split(","):
            pt = camp / spec.replace(":", "_")
            if not pt.is_dir():
                continue
            rows = []
            for base in sorted(x for x in pt.glob("chunk??") if x.is_dir()):
                best = []
                for d in [base] + sorted(pt.glob(base.name + ".r*")):
                    if (d / "mc.tsv").exists():
                        try:
                            r = mc.read(d)
                        except Exception:
                            continue
                        best = r if len(r) > len(best) else best
                rows += best
            groups[spec] = rows
        return report(a, camp, groups)
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs, owners = [], []
    for spec in a.points.split(","):
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        net = netlist(c, rc, camp / "snap" / spec.replace(":", "_"))
        for k, s, n in mc.chunks(a.samples, a.seed, a.chunk):
            jobs.append((mc.deck(net, n, seed=s, analysis=analysis(), lets=LETS, t_end=T1), camp / spec.replace(":", "_") / f"chunk{k:02d}",
                         dict(timeout_s=600 + 120 * n, meta=dict(point=spec, samples=n, seed=s))))
            owners.append(spec)
    dirs = mc.run_many(jobs, workers=a.workers)
    report(a, camp, {spec: mc.read_all([d for d, o in zip(dirs, owners) if o == spec]) for spec in a.points.split(",")})


def report(a, camp, groups):
    out = {}
    print(f"swing floor {FLOOR * 1e3:.0f} / target {TARGET * 1e3:.0f} mVpp; k from each point's sample count (99.73 %, 95 %)")
    print(f"{'point':18s} {'div fail':>8s} | " + " ".join(f"{n + ' sw mean/sd':>18s}" for n, *_ in OUTS) + f" | {'min - k sd vs floor':>19s} | {'tail min V':>10s}")
    for spec, rows in groups.items():
        if len(rows) < 3:
            print(f"{spec:18s} {len(rows)} samples")
            continue
        kf = stats.k_factor(len(rows))
        col = lambda k: np.array([r[k] for r in rows], float)
        fail = np.zeros(len(rows), bool)
        for n, _, _, per in OUTS:
            p = col(f"{n}_per")
            fail |= ~np.isfinite(p) | (np.abs(p / per - 1) > 0.02)
        sw = {n: col(f"{n}_sw") for n, *_ in OUTS}
        worst = min(float(np.nanmean(v) - kf * np.nanstd(v, ddof=1)) for v in sw.values())
        tail = col("tail_min")
        ci = stats.yield_ci(int((~fail).sum()), len(rows))
        out[spec] = dict(samples=len(rows), k=kf, divide_fail=int(fail.sum()), divide_pass_ci=list(ci), swing={n: [float(np.nanmean(v)), float(np.nanstd(v, ddof=1)), float(np.nanmin(v))] for n, v in sw.items()},
                         swing_mean_minus_k_sd=worst, tail_min=[float(np.nanmean(tail)), float(np.nanstd(tail, ddof=1)), float(np.nanmin(tail))])
        print(f"{spec:18s} k {kf:.2f} {int(fail.sum()):4d}/{len(rows):3d} | " + " ".join(f"{np.nanmean(v) * 1e3:8.0f}/{np.nanstd(v, ddof=1) * 1e3:5.1f} mV" for v in sw.values())
              + f" | {worst * 1e3:8.0f} mV ({'ok' if worst >= FLOOR else 'BELOW'}) | {np.nanmean(tail):.3f}/{np.nanmin(tail):.3f}", flush=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), floor=FLOOR, target=TARGET, points=out), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
