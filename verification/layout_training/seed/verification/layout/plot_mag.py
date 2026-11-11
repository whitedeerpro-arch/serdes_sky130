#!/usr/bin/env python3
"""Plot a Magic .mag file to PNG (headless check of the generated layout)."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

U = 200.0  # magic internal units per micrometre
COLORS = {
    "nwell": "#f5e6a8",
    "pwell": "#efe0c8",
    "psubdiff": "#8ecf8e",
    "ndiff": "#7fb3e8",
    "psubdiffcont": "#2e7d32",
    "ndiffcont": "#1e5fa8",
    "poly": "#d95f02",
    "polycont": "#a04000",
    "locali": "#b39ddb",
    "m1": "#5c6bc0",
    "m2": "#26a69a",
    "m3": "#ef5350",
    "m4": "#42a5f5",
    "m5": "#8d6e63",
    "mimcap": "#ffd54f",
    "mimcapcontact": "#ffb300",
    "via1": "#212121",
    "via2": "#212121",
    "via3": "#212121",
    "via4": "#212121",
    "viali": "#212121",
    "npc": "#cccccc",
    "licon": "#212121",
}
Z = {k: i for i, k in enumerate(COLORS)}


def parse(path: Path):
    layer = None
    rects = []
    labels = []
    for line in path.read_text().splitlines():
        m = re.match(r"^<< (\S+) >>$", line)
        if m:
            layer = m.group(1).replace("metal", "m")
            continue
        m = re.match(r"^rect (-?\d+) (-?\d+) (-?\d+) (-?\d+)$", line)
        if m and layer:
            x1, y1, x2, y2 = (int(v) / U for v in m.groups())
            rects.append((layer, x1, y1, x2, y2))
        m = re.match(r"^rlabel \S+ (-?\d+) (-?\d+) .* 0 (\S+)$", line)
        if m:
            labels.append((m.group(3), int(m.group(1)) / U, int(m.group(2)) / U))
    return rects, labels


def main() -> None:
    path = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else path.with_suffix(".png")
    rects, labels = parse(path)
    fig, ax = plt.subplots(figsize=(18, 13))
    for layer, x1, y1, x2, y2 in rects:
        if layer not in COLORS:
            continue
        ax.add_patch(
            Rectangle((x1, y1), x2 - x1, y2 - y1, facecolor=COLORS[layer],
                      edgecolor="none", alpha=0.85 if layer not in ("m1", "m2", "m3", "m4") else 0.75,
                      zorder=Z[layer])
        )
    for name, x, y in labels:
        ax.text(x, y, name, fontsize=7, color="black", zorder=100)
        ax.plot([x], [y], marker="o", ms=2, color="black", zorder=99)
    xs = [r[1] for r in rects] + [r[3] for r in rects]
    ys = [r[2] for r in rects] + [r[4] for r in rects]
    if len(sys.argv) > 3:
        x0, y0, x1, y1 = (float(v) for v in sys.argv[3].split(","))
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
    else:
        ax.set_xlim(min(xs) - 3, max(xs) + 3)
        ax.set_ylim(min(ys) - 3, max(ys) + 3)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    ax.set_title(path.name)
    ax.grid(True, lw=0.2, alpha=0.4)
    handles = [Rectangle((0, 0), 1, 1, facecolor=c) for k, c in COLORS.items() if any(r[0] == k for r in rects)]
    ax.legend(handles, [k for k in COLORS if any(r[0] == k for r in rects)], fontsize=6, loc="upper right")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    print("wrote", out)


if __name__ == "__main__":
    main()
