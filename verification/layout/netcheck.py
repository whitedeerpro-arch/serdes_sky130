#!/usr/bin/env python3
"""Geometric connectivity check for a Magic .mag file.

Runs the same graph the extractor would build for the *metal* stack (plus the
local-interconnect and diffusion contacts), but reports it as connected
components with the labels that land on each one.  It is a debugging aid, not a
replacement for extract + netgen.

Usage: python verification/layout/netcheck.py <file.mag> [--net <label>]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

U = 200.0  # magic internal units per micrometre

# layer -> set of layers it connects to (symmetric closure is computed below)
VIA_LINKS = {
    "viali": ("locali", "metal1"),
    "via1": ("metal1", "metal2"),
    "via2": ("metal2", "metal3"),
    "via3": ("metal3", "metal4"),
    "via4": ("metal4", "metal5"),
    "ndiffc": ("ndiff", "locali"),
    "pdiffc": ("pdiff", "locali"),
    "psubdiffcont": ("psubdiff", "locali"),
    "nsubdiffcont": ("nsubdiff", "locali"),
    "polycont": ("poly", "locali"),
    "xpolycontact": ("xpolycontact", "locali"),
}
CONDUCTORS = {
    "locali", "metal1", "metal2", "metal3", "metal4", "metal5",
    "ndiff", "pdiff", "psubdiff", "nsubdiff", "poly",
}


def parse(path: Path):
    layer = None
    rects = []  # (layer, x1, y1, x2, y2)
    labels = []
    for line in path.read_text().splitlines():
        m = re.match(r"^<< (\S+) >>$", line)
        if m:
            layer = m.group(1)
            continue
        m = re.match(r"^rect (-?\d+) (-?\d+) (-?\d+) (-?\d+)$", line)
        if m and layer:
            x1, y1, x2, y2 = (int(v) / U for v in m.groups())
            rects.append((layer, x1, y1, x2, y2))
        m = re.match(r"^rlabel \S+ (-?\d+) (-?\d+) (-?\d+) (-?\d+) \d+ (\S+)$", line)
        if m:
            labels.append((m.group(5), int(m.group(1)) / U, int(m.group(2)) / U))
    return rects, labels


def overlap(a, b) -> bool:
    """True when the two boxes share area or an edge (a corner alone does not connect)."""
    ox = min(a[3], b[3]) - max(a[1], b[1])
    oy = min(a[4], b[4]) - max(a[2], b[2])
    tol = 1e-9
    if ox < -tol or oy < -tol:
        return False
    return not (abs(ox) <= tol and abs(oy) <= tol)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mag", type=Path)
    ap.add_argument("--net", default=None, help="label to report the component of")
    ap.add_argument("--max-report", type=int, default=8)
    ap.add_argument("--metal-only", action="store_true")
    args = ap.parse_args()

    rects, labels = parse(args.mag)
    if args.metal_only:
        global CONDUCTORS
        CONDUCTORS = {"locali", "metal1", "metal2", "metal3", "metal4", "metal5"}
    idx = {id(r): i for i, r in enumerate(rects)}
    parent = list(range(len(rects)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    by_layer = defaultdict(list)
    for i, r in enumerate(rects):
        by_layer[r[0]].append(i)

    # same-layer connectivity (rectangles only; magic merges diagonals only at corners)
    for layer, ids in by_layer.items():
        if layer not in CONDUCTORS and layer not in VIA_LINKS:
            continue
        for ii in range(len(ids)):
            a = rects[ids[ii]]
            for jj in range(ii + 1, len(ids)):
                b = rects[ids[jj]]
                if overlap(a, b):
                    union(ids[ii], ids[jj])

    # via connectivity
    for via, links in VIA_LINKS.items():
        for i in by_layer.get(via, []):
            v = rects[i]
            for layer in links:
                for j in by_layer.get(layer, []):
                    if overlap(v, rects[j]):
                        union(i, j)

    comps = defaultdict(list)
    for i in range(len(rects)):
        comps[find(i)].append(i)
    comp_labels = defaultdict(list)
    for name, x, y in labels:
        hit = None
        for i, r in enumerate(rects):
            if r[1] <= x <= r[3] and r[2] <= y <= r[4] and r[0] in CONDUCTORS | set(VIA_LINKS):
                hit = i
                break
        if hit is not None:
            comp_labels[find(hit)].append(name)

    ranked = sorted(comps.items(), key=lambda kv: -len(kv[1]))
    print(f"{args.mag.name}: {len(rects)} rects, {len(ranked)} components")
    for root, members in ranked[: args.max_report]:
        names = sorted(set(comp_labels.get(root, [])))
        area = sum((rects[i][3] - rects[i][1]) * (rects[i][4] - rects[i][2]) for i in members)
        print(f"  comp {root:5d}: {len(members):4d} rects, area {area:9.1f} um2, labels {names}")

    if args.net:
        for root, members in comps.items():
            if args.net in comp_labels.get(root, []):
                names = sorted(set(comp_labels.get(root, [])))
                print(f"\nlabels on the {args.net} component: {names}")
                layers = defaultdict(int)
                for i in members:
                    layers[rects[i][0]] += 1
                print("  layers:", dict(layers))
                xs = [rects[i][1] for i in members] + [rects[i][3] for i in members]
                ys = [rects[i][2] for i in members] + [rects[i][4] for i in members]
                print(f"  bbox x {min(xs):.2f}..{max(xs):.2f}  y {min(ys):.2f}..{max(ys):.2f}")
                return


if __name__ == "__main__":
    main()
