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
    "nbase": "#fcd34d",
    "psubdiff": "#8ecf8e",
    "mvpsubdiff": "#8ecf8e",
    "pdiff": "#f4a582",
    "mvpdiff": "#f4a582",
    "nsubdiff": "#a6cee3",
    "mvnsubdiff": "#a6cee3",
    "ndiff": "#7fb3e8",
    "mvndiff": "#7fb3e8",
    "varactor": "#38bdf8",
    "psubdiffcont": "#2e7d32",
    "mvpsubdiffcont": "#2e7d32",
    "nsubdiffcont": "#2e7d32",
    "mvnsubdiffcont": "#2e7d32",
    "ndiffcont": "#1e5fa8",
    "ndiffc": "#212121",
    "mvndiffc": "#212121",
    "pdiffc": "#212121",
    "mvpdiffc": "#212121",
    "ppolyres": "#e879f9",
    "xpolyres": "#e879f9",
    "xpolycontact": "#9333ea",
    "poly": "#d95f02",
    "nmos": "#d95f02",
    "nmoslvt": "#ea580c",
    "mvnmos": "#c2410c",
    "mvnnmos": "#b45309",
    "pmos": "#d95f02",
    "pmoslvt": "#e11d48",
    "mvpmos": "#be123c",
    "polycont": "#a04000",
    "npc": "#cccccc",
    "licon": "#212121",
    "locali": "#b39ddb",
    "viali": "#7e57c2",
    "mcon": "#8d8d8d",
    "m1": "#5c6bc0",
    "via1": "#00a000",
    "m2": "#26a69a",
    "via2": "#212121",
    "m3": "#ef5350",
    "mimcap": "#ffd54f",
    "mimcapcontact": "#ffb300",
    "via3": "#212121",
    "m4": "#42a5f5",
    "mimcap2": "#6ee7b7",
    "mimcap2contact": "#10b981",
    "via4": "#212121",
    "m5": "#8d6e63",
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
        is_mim = layer in ("mimcap", "mimcap2")
        alpha = 0.30 if is_mim else (0.68 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.88)
        ec = "#d97706" if layer == "mimcap" else ("#059669" if layer == "mimcap2" else "none")
        ax.add_patch(
            Rectangle((x1, y1), x2 - x1, y2 - y1, facecolor=COLORS[layer],
                      edgecolor=ec, linewidth=0.8 if is_mim else 0.0,
                      hatch="//" if is_mim else None,
                      alpha=alpha, zorder=Z[layer])
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
