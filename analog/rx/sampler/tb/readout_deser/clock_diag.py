"""Why the read divider fails at a condition: reruns a readout_deser deck with probes on its clock path.

    uv run python analog/rx/sampler/tb/readout_deser/clock_diag.py <case dir> [<case dir> ...] [--stop 24e-9] [--from 6e-9] [--workers 3]

<case dir>: a readout_deser/<campaign>/<condition> with tb.cir and stimuli.inc.  Same deck, shorter, more nodes saved.  Over the
last 8 ns, per node pair: differential swing, common mode; the follower output against the tail node's headroom; output toggles.
"""
import argparse
import re
import shutil
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

RESULTS = ROOT / "results/analog/rx/sampler/readout_clock_diag"
D = "xro.xf.xdiv"
PAIRS = [("rk (divider input)", "rkp", "rkn"), ("tap (buffer input)", "xdut.tbp", "xdut.tbn"), ("follower", f"{D}.ckp", f"{D}.ckn"),
         ("divider q", "xro.xf.dqp", "xro.xf.dqn"), ("divider m", "xro.xf.dmp", "xro.xf.dmn")]
SINGLE = ["vbias", f"{D}.vbias_logic", f"{D}.xmaster.tail", f"{D}.xslave.tail"]


def probes():
    return [f"v({n})" for _, a, b in PAIRS for n in (a, b)] + [f"v({n})" for n in SINGLE]


def edit(deck, stop, start):
    lines = deck.splitlines()
    out = []
    for l in lines:
        if l.startswith(".save "):
            l += " " + " ".join(probes())
        elif l.startswith("tran "):
            t = l.split()
            l = f"tran {t[1]} {stop:.4e} {start:.4e} {t[4]}"
        elif l.startswith("write "):
            l = "write diag.raw v(vdd) " + " ".join(probes())
        out.append(l)
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+")
    ap.add_argument("--stop", type=float, default=24e-9)
    ap.add_argument("--from", dest="start", type=float, default=6e-9)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    jobs = []
    names = []
    for k, c in enumerate(a.cases):
        c = Path(c)
        name = f"{k}_{c.name}_{re.sub(r'.*_r', 'r', c.parent.name)}"
        names.append(name)
        camp.mkdir(parents=True, exist_ok=True)
        shutil.copy(c / "stimuli.inc", camp / f"{name}.inc")
        jobs.append((edit((c / "tb.cir").read_text(), a.stop, a.start), camp / name, dict(files={"stimuli.inc": camp / f"{name}.inc"}, timeout_s=3600, meta=dict(source=str(c)))))
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:3]}", flush=True)
    for name in names:
        w = spice.Waves(camp / name / "diag.raw")
        sel = w.t > w.t[-1] - 8e-9
        print(f"== {name}: VDD {np.mean(w['v(vdd)'][sel]):.3f} V, vbias {np.mean(w['v(vbias)'][sel]):.3f} V, vbias_logic {np.mean(w[f'v({D}.vbias_logic)'][sel]):.3f} V")
        print(f"{'node':22s} {'swing mVpp':>10s} {'CM V':>7s} {'toggles':>8s}")
        for lab, p, n in PAIRS:
            y = w[f"v({p})"] - w[f"v({n})"]
            cm = (w[f"v({p})"] + w[f"v({n})"]) / 2
            print(f"{lab:22s} {np.ptp(y[sel]) * 1e3:10.0f} {np.mean(cm[sel]):7.3f} {len(crossings(w.t[sel], y[sel])[0]):8d}")
        for s in ("xmaster", "xslave"):
            v = w[f"v({D}.{s}.tail)"][sel]
            print(f"{s} tail node: {v.min():.3f} .. {v.max():.3f} V, mean {v.mean():.3f}")
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
