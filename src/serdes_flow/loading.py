"""Static loading / fan-out check of a CML subcircuit (no simulation).

    uv run python -m serdes_flow.loading TOP [--param k=v ...] [--card DIR] [--rows 20] [--node PAT ...]

Flattens TOP from the project's .spice files (serdes_flow.netlist) and, for every node, adds up
  gate     W x Cgg/W of every MOS gate on the node (device card, TT 27 C, gm/Id = 10, |Vds| = 0.6 V,
           nearest card L),
  overlap  W x Cgd/W of every MOS drain / source on the node,
  diff     W x 0.6 fF/um of every drain / source (rough diffusion estimate),
  cap      explicit capacitors (a capacitor between two signal nodes counts fully on both).
Nodes with a resistive load (a resistor to a rail) get R, C and the pole 1 / (2 pi R C); the table
lists them by ascending pole with the largest contributors (instance path, kind, fF).  Rule of
thumb for a CML clock node at f: pole >= 2 f keeps ~90 % of the swing of a fully switched stage.
Values are first-order estimates for spotting overloaded nodes, not a substitute for simulation.
"""
from __future__ import annotations

import argparse
import math
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path

from .devices import DeviceCard
from .netlist import flatten, parse, project_files
from .project import ROOT

RAILS = {"0", "vss", "vdd", "gnd"}
C_DIFF_PER_UM = 0.6e-15
MODEL_DEV = {"sky130_fd_pr__nfet_01v8": "nfet", "sky130_fd_pr__nfet_01v8_lvt": "nfet_lvt",
             "sky130_fd_pr__pfet_01v8": "pfet", "sky130_fd_pr__pfet_01v8_lvt": "pfet_lvt"}


def latest_card():
    runs = sorted((ROOT / "results/analog/common/devices/gmid_card").glob("*/tt/card.npz"))
    return runs[-1].parent if runs else None


class CapTable:
    def __init__(self, card: DeviceCard):
        self.card, self.cache = card, {}

    def per_um(self, model, L):
        dev = MODEL_DEV.get(model)
        if dev is None:
            return 0.0, 0.0
        Ls = self.card.meta["L"][dev] if isinstance(self.card.meta["L"], dict) else self.card.meta["L"]
        Lg = min(Ls, key=lambda x: abs(x - L))
        key = (dev, Lg)
        if key not in self.cache:
            op = self.card.at_gmid(dev, Lg, 10.0, 0.6)
            self.cache[key] = (op["cgg_w"], op["cgd_w"])
        return self.cache[key]


def analyse(top, params=None, card_dir=None):
    subs = parse(project_files(ROOT))
    devs, unknown = flatten(subs, top, params)
    caps = CapTable(DeviceCard.load(card_dir or latest_card()))
    load = defaultdict(list)            # node -> [(path, kind, farad)]
    rload = defaultdict(list)
    for d in devs:
        if d.kind == "mos":
            dn, g, s, _ = d.nodes
            cgg, cgd = caps.per_um(d.model, d.l)
            load[g].append((d.path, "gate", d.w * cgg))
            for n in (dn, s):
                load[n].append((d.path, "overlap", d.w * cgd))
                load[n].append((d.path, "diff", d.w * C_DIFF_PER_UM))
        elif d.kind == "C":
            for n in d.nodes:
                if n not in RAILS:
                    load[n].append((d.path, "cap", d.value))
        elif d.kind == "R":
            a, b = d.nodes
            for n, other in ((a, b), (b, a)):
                if other in RAILS and n not in RAILS:
                    rload[n].append(d.value)
    rows = []
    for n, items in load.items():
        if n in RAILS:
            continue
        c = sum(x[2] for x in items)
        r = 1.0 / sum(1.0 / x for x in rload[n]) if rload.get(n) else None
        pole = 1.0 / (2 * math.pi * r * c) if r and c > 0 else None
        rows.append(dict(node=n, c_f=c, r_ohm=r, pole_hz=pole, gates=sum(1 for x in items if x[1] == "gate"),
                         top=sorted(items, key=lambda x: -x[2])[:4]))
    return rows, unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("top")
    ap.add_argument("--param", action="append", default=[])
    ap.add_argument("--card")
    ap.add_argument("--rows", type=int, default=20)
    ap.add_argument("--node", action="append", default=[], help="glob on node names (default: resistively loaded nodes)")
    a = ap.parse_args()
    params = dict(p.split("=", 1) for p in a.param)
    rows, unknown = analyse(a.top, params, Path(a.card) if a.card else None)
    if a.node:
        sel = [r for r in rows if any(fnmatch(r["node"], p) for p in a.node)]
    else:
        sel = [r for r in rows if r["pole_hz"] is not None]
    sel.sort(key=lambda r: (r["pole_hz"] if r["pole_hz"] is not None else 0.0))
    print(f"{a.top}: {len(rows)} nodes, unknown cells {sorted(unknown) or 'none'}")
    print(f"{'node':28s} {'R ohm':>7s} {'C fF':>7s} {'pole GHz':>8s} {'gates':>5s}  largest loads (fF)")
    for r in sel[:a.rows]:
        pole = f"{r['pole_hz']/1e9:8.2f}" if r["pole_hz"] else "       -"
        rr = f"{r['r_ohm']:7.0f}" if r["r_ohm"] else "      -"
        tops = ", ".join(f"{p.split('.', 1)[-1] if p.count('.') > 2 else p}:{k} {v*1e15:.0f}" for p, k, v in r["top"])
        print(f"{r['node']:28s} {rr} {r['c_f']*1e15:7.1f} {pole} {r['gates']:5d}  {tops}")


if __name__ == "__main__":
    main()
