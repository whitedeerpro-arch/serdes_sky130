#!/usr/bin/env python3
"""Draw parallel LDO MIM arrays with the installed PDK, then run DRC/LVS.

Example: uv run python analog/ldo/layout/build_mim_pdk.py \
    --units 16 50 100 --output-dir results/layout/ldo_mim/<new-run>

The PDK connects each column vertically. This builder adds the two horizontal
rails, explicit external ports, and checks the unmerged extracted device count.
It does not change the design-side SPICE or adopt an entire LDO layout.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "verification/layout"))
import magicutil as mu  # noqa: E402

GRID = {16: (4, 4), 50: (10, 5), 100: (10, 10)}
MODEL = "sky130_fd_pr__cap_mim_m3_1"
REFERENCE = REPO / "analog/ldo/spice/ldo_passives.spice"


def preview(mag: Path) -> None:
    """Render the saved geometry, including Magic's font-label port records."""
    sys.path.insert(0, str(REPO / "analog/layout/scripts"))
    from layout_core import load_mag_as_canvas, plot_canvas
    import matplotlib.pyplot as plt

    canvas = load_mag_as_canvas(mag, mag.stem)
    labels, _ = geometry(mag.read_text())
    canvas.labels.clear()
    for name, x, y in labels:
        canvas.L(name, x, y, "m4" if name == "a" else "m3")
    fig, ax = plt.subplots(figsize=(8, 7), dpi=150)
    plot_canvas(ax, canvas, mag.stem,
                "PDK MIM leaves | a: M4 upper rail | b: M3 lower rail", show_cuts=False)
    ax.legend(loc="upper left", bbox_to_anchor=(1.01, 1), fontsize=7)
    fig.tight_layout()
    fig.savefig(mag.with_suffix(".png"), bbox_inches="tight")
    plt.close(fig)


def geometry(text: str) -> tuple[list[tuple[str, float, float]], list[float]]:
    """Read the physical PDK labels and extent, on Magic's 5 nm file grid."""
    if "magscale 1 2\n" not in text:
        raise ValueError("Expected SKY130 Magic magscale 1 2")
    labels = [
        (name, (int(x1) + int(x2)) / 400, (int(y1) + int(y2)) / 400)
        for x1, y1, x2, y2, name in re.findall(
            r"^[rf]label \S+ (-?\d+) (-?\d+) (-?\d+) (-?\d+) \d+ (?:.* )?(\S+)$",
            text, re.M,
        )
    ]
    rects = [[int(x) / 200 for x in r] for r in re.findall(
        r"^rect (-?\d+) (-?\d+) (-?\d+) (-?\d+)$", text, re.M,
    )]
    if not labels or not rects:
        raise ValueError("PDK did not draw capacitor labels/geometry")
    return labels, [min(r[0] for r in rects), min(r[1] for r in rects),
                    max(r[2] for r in rects), max(r[3] for r in rects)]


def build(out: Path, units: int) -> dict:
    cols, rows = GRID[units]
    cell = f"serdes_ldo_mim{units}_pdk"
    work = out / cell
    work.mkdir(parents=True, exist_ok=False)
    ref_text = REFERENCE.read_text()
    dims = re.search(rf"Xc a b {MODEL} w=([\d.]+) l=([\d.]+)", ref_text)
    if dims is None:
        raise ValueError("Cannot find current physical MIM leaf dimensions")
    w, length = map(float, dims.groups())
    mag = work / f"{cell}.mag"
    mu.new_cell(mag)
    draw = work / "draw.tcl"
    draw.write_text(
        f"drc off\nload {cell}\nbox values 0 0 0 0\n"
        f"set p [dict merge [sky130::{MODEL}_defaults] "
        f"[dict create w {w} l {length} nx {cols} ny {rows} stack 0]]\n"
        f"sky130::{MODEL}_draw $p\nsave {cell}\nquit -noprompt\n"
    )
    res = mu.run_magic(draw, work)
    (work / "draw.log").write_text(res.log)
    res.need("PDK MIM array")
    text = mag.read_text()
    labels, bbox = geometry(text)
    top = sorted((x, y) for name, x, y in labels if name.startswith("C1"))
    bottom = sorted((x, y) for name, x, y in labels if name.startswith("C2"))
    if len(top) != cols or len(bottom) != cols:
        raise ValueError("Expected one physical port pair per connected column")
    # Retain all PDK geometry; replace column ports with the two array ports.
    text = re.sub(r"<< labels >>.*?(?=<< properties >>)", "<< labels >>\n", text, flags=re.S)
    text = re.sub(r"string FIXED_BBOX .*\n", "", text)
    mag.write_text(text)
    upper, lower = round(bbox[3] + 2, 3), round(bbox[1] - 2, 3)
    lines = [
        "drc off", f"load {cell}", "snap internal", "units microns",
        "proc R {ly x1 y1 x2 y2} {box values ${x1}um ${y1}um ${x2}um ${y2}um; paint $ly}",
    ]

    def rect(layer: str, x1: float, y1: float, x2: float, y2: float) -> None:
        lines.append(f"R {layer} {x1:.3f} {y1:.3f} {x2:.3f} {y2:.3f}")

    for x, y in top:
        rect("metal4", x - .5, y, x + .5, upper + .5)
    rect("metal4", top[0][0] - .6, upper - .5, top[-1][0] + .6, upper + .5)
    for x, y in bottom:
        rect("metal4", x - .26, lower - .26, x + .26, y)
        rect("metal3", x - .26, lower - .26, x + .26, lower + .26)
        rect("via3", x - .16, lower - .16, x + .16, lower + .16)
    rect("metal3", bottom[0][0] - .6, lower - .5, bottom[-1][0] + .6, lower + .5)
    lines += [
        f"box values {top[0][0]}um {upper}um {top[0][0]}um {upper}um",
        "label a 0 metal4", "port make 1",
        f"box values {bottom[0][0]}um {lower}um {bottom[0][0]}um {lower}um",
        "label b 0 metal3", "port make 2", "save", "quit -noprompt",
    ]
    route = work / "route.tcl"
    route.write_text("\n".join(lines) + "\n")
    res = mu.run_magic(route, work)
    (work / "route.log").write_text(res.log)
    res.need("array rails")
    ref = work / "reference.spice"
    ref.write_text(re.sub(rf"\bserdes_ldo_mim{units}\b", cell, ref_text))
    check = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"), str(work), cell, "--ref", str(ref)],
        capture_output=True, text=True, check=False,
    )
    (work / "check.log").write_text(check.stdout + check.stderr)
    print(cell, check.stdout, flush=True)
    if check.returncode:
        raise RuntimeError(f"Physical checks failed: {work / 'check.log'}")
    extracted = (work / f"{cell}_lvs.spice").read_text()
    devices = re.findall(rf"^X\S+ (\S+) (\S+) {MODEL} l=([\d.]+) w=([\d.]+)$", extracted, re.M)
    if len(devices) != units or any(set(d[:2]) != {"a", "b"} for d in devices):
        raise ValueError("Wrong number of parallel physical capacitors or a short/disconnected leaf")
    if not re.search(rf"^\.subckt {cell} a b$", extracted, re.M):
        raise ValueError("External ports/order do not match the design")
    if any(abs(float(d[2]) / length - 1) > .001 or abs(float(d[3]) / w - 1) > .001 for d in devices):
        raise ValueError("Extracted dimensions deviate from reference by more than 0.1%")
    _, physical_bbox = geometry(mag.read_text())
    preview(mag)
    return {
        "cell": cell, "units": units, "grid": [cols, rows], "full_rule_drc": 0,
        "lvs": "unique_match_no_property_errors_or_disconnected_ports",
        "ports": ["a", "b"], "reference_leaf_um": [w, length],
        "extracted_leaf_um": sorted({(float(d[3]), float(d[2])) for d in devices}),
        "bbox_um": physical_bbox,
        "reference": str(REFERENCE.relative_to(REPO)),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--units", type=int, nargs="+", choices=GRID, default=[16])
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = []
    for units in args.units:
        results.append(build(out, units))
        (out / "summary.json").write_text(json.dumps(results, indent=2) + "\n")


if __name__ == "__main__":
    main()
