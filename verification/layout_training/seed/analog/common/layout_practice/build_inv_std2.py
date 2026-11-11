#!/usr/bin/env python3
"""inv_std2 - T2b practice cell: same circuit as inv_std, but

  * every source/drain has a full row of contacts (0.17 squares on a 0.34 pitch,
    the cookbook's "contact rows" pattern), and
  * both devices are folded into two fingers (PMOS w=8 nf=2, NMOS w=4 nf=2),
    which halves the cell height.

Folding puts the drain in the middle of each diffusion, sources at both ends,
so the output tap is one m1 bar between the two gates.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "verification/layout"))
import magicutil as mu  # noqa: E402

CELL = "inv_std2"

# geometry (um)
XL, XR = 1.20, 4.60          # diffusion extents
G1, G2 = 2.00, 3.00          # gate poly strips (0.15 wide)
GL = 0.15
NY1, NY2 = 1.60, 3.60        # NMOS diffusion (2 fingers x 2.0 = w 4)
PY1, PY2 = 6.00, 10.00       # PMOS diffusion (2 fingers x 4.0 = w 8)
NW = (0.60, 5.20, 5.40, 11.40)
RAIL_W = 0.45

PROCS = "\n".join([
    "proc R {layer x1 y1 x2 y2} { if {$x1 > $x2} {set q $x1; set x1 $x2; set x2 $q};"
    " if {$y1 > $y2} {set q $y1; set y1 $y2; set y2 $q}; box $x1 $y1 $x2 $y2; paint $layer }",
    "proc HW {layer x y w h} { R $layer [expr {$x-$w/2.0}] [expr {$y-$h/2.0}]"
    " [expr {$x+$w/2.0}] [expr {$y+$h/2.0}] }",
    "proc VIA {x y} { HW m1 $x $y 0.32 0.32; HW via1 $x $y 0.26 0.26; HW m2 $x $y 0.32 0.32 }",
    "proc L {name x y} { box $x $y $x $y; label $name; catch {port make} }",
])


def contact_row(x1: float, x2: float, y: float, kind: str) -> list[str]:
    """A row of 0.17 contacts on a 0.34 pitch with li and an m1 strap."""
    t = []
    # keep 0.15 clear of the neighbouring gate (licon.11 wants 0.055)
    x1, x2 = x1 + 0.15, x2 - 0.15
    n = max(1, int((x2 - x1 - 0.17) / 0.34) + 1)
    span = n * 0.34 - 0.17
    x0 = x1 + (x2 - x1 - span) / 2.0
    cut = "ndiffc" if kind == "n" else "pdiffc"
    for i in range(n):
        cx = x0 + i * 0.34 + 0.085
        t.append(f"R {cut} {cx - 0.085} {y - 0.085} {cx + 0.085} {y + 0.085}")
    # li 0.35 tall, the li->m1 via strip 0.17, m1 0.45 tall (met1.4/1.5 need
    # >=0.03 and >=0.06 of enclosure in one direction)
    t.append(f"R locali {x0 - 0.08} {y - 0.175} {x0 + span + 0.08} {y + 0.175}")
    t.append(f"R viali {x0 - 0.08} {y - 0.085} {x0 + span + 0.08} {y + 0.085}")
    t.append(f"R m1 {x0 - 0.12} {y - 0.225} {x0 + span + 0.12} {y + 0.225}")
    return t


def main() -> None:
    for stale in (HERE / f"{CELL}.mag",):
        stale.unlink(missing_ok=True)
    mu.new_cell(HERE / f"{CELL}.mag")
    t = ["drc off", "units microns", f"cd {HERE}", PROCS, f"load {CELL}"]

    def R(*a):
        t.append("R " + " ".join(str(v) for v in a))

    # wells / diffusion
    R("nwell", *NW)
    R("pwell", XL - 0.4, NY1 - 0.4, XR + 0.4, NY2 + 0.4)
    R("ndiff", XL, NY1, XR, NY2)
    R("pdiff", XL, PY1, XR, PY2)
    # recognition markers: channel strips only
    for gx in (G1, G2):
        R("nmos", gx, NY1, gx + GL, NY2)
        R("pmos", gx, PY1, gx + GL, PY2)
    # two vertical gates through both devices
    for gx in (G1, G2):
        R("poly", gx, NY1 - 0.55, gx + GL, PY2 + 0.55)
    # gate bus on the left and the gate contact
    R("poly", 0.30, PY2 + 0.55, G2 + GL, PY2 + 0.85)
    R("polycont", 0.45, PY2 + 0.62, 0.62, PY2 + 0.79)
    R("locali", 0.36, PY2 + 0.55, 0.71, PY2 + 0.86)
    R("mcon", 0.45, PY2 + 0.62, 0.62, PY2 + 0.79)
    R("m1", 0.33, PY2 + 0.54, 0.74, PY2 + 0.87)

    # source/drain contact rows (two rows per region for the tall PMOS)
    for y in (NY1 + 0.5, NY2 - 0.5):
        t += contact_row(XL, G1, y, "n")          # left source
        t += contact_row(G2 + GL, XR, y, "n")     # right source
    for y in (PY1 + 0.7, PY1 + 2.0, PY2 - 2.0, PY2 - 0.7):
        t += contact_row(XL, G1, y, "p")
        t += contact_row(G2 + GL, XR, y, "p")
    # drain (middle) contact rows: one per device height
    t += contact_row(G1 + GL, G2, NY1 + 0.5, "n")
    t += contact_row(G1 + GL, G2, NY2 - 0.5, "n")
    t += contact_row(G1 + GL, G2, PY1 + 1.2, "p")
    t += contact_row(G1 + GL, G2, PY2 - 1.2, "p")

    # rails and straps
    R("m1", XL - 0.3, NY1 - 0.75, XR + 0.3, NY1 - 0.30)      # gnd rail
    R("m1", XL - 0.3, PY2 + 0.30, XR + 0.3, PY2 + 0.75)      # vdd rail
    R("m1", XL + 0.02, NY1 - 0.75, XL + 0.24, NY2 + 0.0)      # left source riser (n)
    R("m1", XR - 0.24, NY1 - 0.75, XR - 0.02, NY2 + 0.0)     # right source riser (n)
    R("m1", XL + 0.02, PY1 - 0.0, XL + 0.24, PY2 + 0.75)      # left source riser (p)
    R("m1", XR - 0.24, PY1 - 0.0, XR - 0.02, PY2 + 0.75)     # right source riser (p)
    # output: drain bars of both devices tied together
    R("m1", G1 + GL + 0.02, NY1 + 0.2, G2 - 0.02, NY2 - 0.2)
    R("m1", G1 + GL + 0.02, PY1 + 0.9, G2 - 0.02, PY2 - 0.9)
    R("m1", (G1 + GL + G2) / 2.0 - 0.20, NY2 - 0.4, (G1 + GL + G2) / 2.0 + 0.20, PY1 + 1.0)
    # well/substrate taps
    R("psubdiff", 1.30, NY1 - 0.75, 1.85, NY1 - 0.30)
    R("psubdiffcont", 1.48, NY1 - 0.62, 1.65, NY1 - 0.45)
    R("locali", 1.40, NY1 - 0.72, 1.73, NY1 - 0.33)
    R("mcon", 1.48, NY1 - 0.62, 1.65, NY1 - 0.45)
    R("m1", 1.40, NY1 - 0.74, 1.73, NY1 - 0.31)
    R("nsubdiff", 4.00, PY2 + 0.60, 4.55, PY2 + 1.05)
    R("nsubdiffcont", 4.18, PY2 + 0.73, 4.35, PY2 + 0.90)
    R("locali", 4.10, PY2 + 0.63, 4.45, PY2 + 1.02)
    R("mcon", 4.18, PY2 + 0.73, 4.35, PY2 + 0.90)
    R("m1", 4.10, PY2 + 0.61, 4.45, PY2 + 1.04)

    # ports
    R("m1", (G1 + GL + G2) / 2.0 - 0.3, PY2 + 0.9, (G1 + GL + G2) / 2.0 + 0.3, PY2 + 1.3)
    for name, x, y in (("d", (G1 + GL + G2) / 2.0, PY2 + 1.1),
                       ("g", 0.53, PY2 + 0.72),
                       ("vdd", (XL + XR) / 2.0, PY2 + 0.52),
                       ("vss", (XL + XR) / 2.0, NY1 - 0.52)):
        t.append(f"L {name} {x} {y}")
    t += ["select top cell", "save"]
    (HERE / "build.tcl").write_text("\n".join(t) + "\n")
    mu.run_magic(HERE / "build.tcl", HERE).need("inv_std2 build")
    print("wrote", HERE / f"{CELL}.mag")


if __name__ == "__main__":
    main()
