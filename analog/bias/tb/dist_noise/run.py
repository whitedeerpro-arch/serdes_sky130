"""Noise on the bias lines from the real distribution (bandgap -> V->I -> PMOS copy -> module diode).

    uv run python analog/bias/tb/dist_noise/run.py [--process tt] [--supply 1.8] [--temps 27] [--rcorner tt] [--breakdown] [--extra "..."]

The deck of tb/dist_pvt, ngspice .noise (sparse: KLU has no noise analysis) at the CML bias line vcml, the
reference vbg and the V->I gate line vgi.  Output: one-sided V/sqrt(Hz) per frequency into summary.json, used by
the VCO's phase noise (vco_pn.py --bias).  --breakdown prints the largest device contributions at vcml.
"""
import argparse
import json
import re
import time

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

TEMPLATE = ROOT / "analog/bias/tb/dist_pvt/tb_bias_dist_pvt_ngspice.cir.in"
RESULTS = ROOT / "results/analog/bias/dist_noise"
NODES = ("vcml", "vbg", "vgi")


def is_part(name):
    """A device's total at the output (onoise.<device>), not its per-mechanism entries."""
    return name.startswith("onoise.") and re.search(r"\.(1overf|id|ig[bds]|rb\w*|rd|rs|rg|ic|ib|rc|re|gmin\w*)$", name) is None


def short(name):
    return re.sub(r"^onoise\.[mqr]\.|\.xmos|\.?[mqr]?sky130_fd_pr__\w+$", "", name)


def section(proc, rc):
    return proc if rc == "tt" else rc if proc == "tt" else f"{proc}_{rc}"


def deck(proc, rc, supplies, temps, extra, breakdown):
    text = spice.render(TEMPLATE, **spice.corner_values(Condition(proc, 1.8, 27)), SECTION=section(proc, rc))
    head, rest = text.split("\n", 1)
    text = "\n".join([head, *extra, rest])
    assert text.count("Vdd vdd 0 1.8") == 1
    text = text.replace("Vdd vdd 0 1.8", "Vdd vdd 0 dc 1.8 ac 1").replace("klu", "sparse")
    lines = [".control", "set num_threads=1", "set filetype=binary"]
    for v in supplies:
        for t in temps:
            n = f"v{round(v * 1000)}_t{t}"
            lines += [f"option temp={t}", f"alter Vdd dc={v}"]
            for node in NODES:
                lines += [f"noise v({node}) Vdd dec 10 1k 3g" + (" 1" if breakdown and node == "vcml" else "")]
                lines += ["setplot previous"]
                if breakdown and node == "vcml":
                    lines += [f"write {n}_{node}_parts.raw all"]
                lines += [f"write {n}_{node}.raw onoise_spectrum", "destroy all"]
    return text + "\n".join(lines + ["quit", ".endc", ".end", ""])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--process", default="tt")
    ap.add_argument("--supply", default="1.8")
    ap.add_argument("--temps", default="27")
    ap.add_argument("--rcorner", default="tt")
    ap.add_argument("--breakdown", action="store_true")
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--workers", type=int, default=1)
    a = ap.parse_args()
    procs, supplies = a.process.split(","), [float(x) for x in a.supply.split(",")]
    temps = [int(x) for x in a.temps.split(",")]
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"_{a.rcorner}")
    jobs = [(deck(p, a.rcorner, supplies, temps, a.extra, a.breakdown), camp / p, dict(timeout_s=1800, meta=dict(process=p, rcorner=a.rcorner, extra=a.extra))) for p in procs]
    for ex in spice.run_many(jobs, workers=a.workers, smoke=False):
        if not ex.ok:
            print(f"FAILED {ex.run_dir.relative_to(ROOT)}: {ex.log_failures[:3]}")
    out, pick = dict(rcorner=a.rcorner, extra=a.extra, conditions={}), (1e4, 1e5, 1e6, 1e7, 1e8)
    print(f"{'condition':22s} {'node':5s} nV/sqrtHz at " + " ".join(f"{p:8.0e}" for p in pick))
    for p in procs:
        for v in supplies:
            for t in temps:
                n = f"v{round(v * 1000)}_t{t}"
                e = {}
                for node in NODES:
                    w = spice.Waves(camp / p / f"{n}_{node}.raw")
                    f, s = w.t, w["onoise_spectrum"]
                    e[node] = dict(f=f.tolist(), v=s.tolist())
                    print(f"{p + '_' + n:22s} {node:5s}             " + " ".join(f"{np.interp(q, f, s) * 1e9:8.2f}" for q in pick), flush=True)
                out["conditions"][f"{p}_{n}"] = e
                if a.breakdown:
                    w = spice.Waves(camp / p / f"{n}_vcml_parts.raw")
                    f = w.t
                    for q in (1e5, 1e6, 1e7):
                        i = int(np.argmin(np.abs(f - q)))
                        keep = []
                        for k, nm in enumerate(w.names):
                            if k and is_part(nm):
                                fn = f"{nm}.1overf"
                                tot = float(w.data[i, k])
                                keep.append((tot, short(nm) + (f" ({(float(w[fn][i]) / tot) ** 2 * 100:.0f}% 1/f)" if tot > 0 and fn in w else "")))
                        print(f"  at {q:.0e}: " + ", ".join(f"{nm} {v * 1e9:.2f}" for v, nm in sorted(keep, reverse=True)[:7]))
    (camp / "summary.json").write_text(json.dumps(out))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
