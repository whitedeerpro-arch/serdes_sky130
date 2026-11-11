#!/usr/bin/env python3
"""Hand-painted stacked inverter (T2 of docs/layout/tasks.md).

No device generator: the transistors are poly crossings of diffusion, painted
with plain rectangles, so the cell is the template for later logic cells.

    vdd ------------------------------------   m1 rail
      [nwell]  n-tap            p+ source
      +--------------------------------+
      |   PMOS  W8  (pdiff 8.0 tall)   |      VDD on top
      |        | gate (vertical poly)  |
      |        |                       |
      +--------|---------+-------------+
               |         |
      +--------|---------+-------------+
      |   NMOS  W4  (ndiff 4.0 tall)   |      GND on the bottom
      +--------------------------------+
      p-tap                    n+ source
    gnd ------------------------------------   m1 rail

Drains are joined by one vertical m1 bar on the right, sources go straight up /
down to their rails, the gate exits to the left at the bottom.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "verification/layout"))
import magicutil as mu  # noqa: E402

CELL = "inv_std"

# geometry (micrometres)
XG = 2.60            # gate poly left edge
GL = 0.15            # gate length
XL, XR = 1.20, 4.60  # diffusion extents
NY1, NY2 = 1.60, 5.60   # NMOS diffusion (W = 4.0)
PY1, PY2 = 7.20, 15.20  # PMOS diffusion (W = 8.0)
NW = (0.60, 6.40, 6.70, 16.30)   # nwell x1 x2 y1 y2
GND = (0.90, 4.90, 0.35, 0.80)   # gnd rail x1 x2 y1 y2
VDD = (0.90, 4.90, 16.00, 16.45)  # vdd rail

PROCS = r"""
proc R {layer x1 y1 x2 y2} {
    if {$x1 > $x2} { set t $x1; set x1 $x2; set x2 $t }
    if {$y1 > $y2} { set t $y1; set y1 $y2; set y2 $t }
    box $x1 $y1 $x2 $y2
    paint $layer
}
proc C {x y} { R ndiffc [expr {$x-0.085}] [expr {$y-0.085}] [expr {$x+0.085}] [expr {$y+0.085}] }
proc CF {layer x y} { R $layer [expr {$x-0.085}] [expr {$y-0.085}] [expr {$x+0.085}] [expr {$y+0.085}] }
proc LI {x y} { R locali [expr {$x-0.145}] [expr {$y-0.145}] [expr {$x+0.145}] [expr {$y+0.145}] }
proc VIA {x y} {
    R locali [expr {$x-0.175}] [expr {$y-0.175}] [expr {$x+0.175}] [expr {$y+0.175}]
    R viali  [expr {$x-0.085}] [expr {$y-0.085}] [expr {$x+0.085}] [expr {$y+0.085}]
    R m1     [expr {$x-0.175}] [expr {$y-0.175}] [expr {$x+0.175}] [expr {$y+0.175}]
}
proc L {name x y} { box $x $y $x $y; label $name }
"""


def build(work: Path) -> None:
    for stale in (work / f"{CELL}.mag",):
        stale.unlink(missing_ok=True)
    mu.new_cell(work / f"{CELL}.mag")
    t = ["drc off", "units microns", f"cd {work}", PROCS, f"load {CELL}"]

    def R(layer, x1, y1, x2, y2):
        t.append(f"R {layer} {x1} {y1} {x2} {y2}")
        return f"R {layer} {x1} {y1} {x2} {y2}"

    # ---- wells -------------------------------------------------------------
    t.append(f"R nwell {NW[0]} {NW[2]} {NW[1]} {NW[3]}")
    t.append(f"R pwell {XL - 0.4} {NY1 - 0.4} {XR + 0.4} {NY2 + 0.4}")

    # ---- diffusion ---------------------------------------------------------
    t.append(f"R ndiff {XL} {NY1} {XG} {NY2}")
    t.append(f"R ndiff {XG + GL} {NY1} {XR} {NY2}")
    t.append(f"R pdiff {XL} {PY1} {XG} {PY2}")
    t.append(f"R pdiff {XG + GL} {PY1} {XR} {PY2}")
    # recognition markers over the channels
    t.append(f"R nmos {XG} {NY1} {XG + GL} {NY2}")
    t.append(f"R pmos {XG} {PY1} {XG + GL} {PY2}")

    # ---- poly gate (one vertical strip through both devices) --------------
    t.append(f"R poly {XG} 0.95 {XG + GL} {PY2 + 0.75}")
    # gate contact pad at the bottom, widened so a 0.17 contact fits
    t.append(f"R poly {XG - 0.20} 0.95 {XG + GL + 0.20} 1.45")

    # ---- well / substrate taps --------------------------------------------
    NTAP = (1.00, 15.50, 1.45, 15.95)   # x1 y1 x2 y2, n+ inside the nwell
    PTAP = (1.00, 0.85, 1.45, 1.30)     # p+ below the NMOS, on the p substrate
    t.append(f"R nsubdiff {NTAP[0]} {NTAP[1]} {NTAP[2]} {NTAP[3]}")
    t.append(f"R nsubdiffcont 1.14 15.64 1.31 15.81")
    t.append(f"R psubdiff {PTAP[0]} {PTAP[1]} {PTAP[2]} {PTAP[3]}")
    t.append(f"R psubdiffcont 1.14 0.99 1.31 1.16")

    # ---- contacts ----------------------------------------------------------
    # source / drain diff contacts
    for x, y, kind in ((1.80, 3.00, "n"), (4.15, 3.00, "n"),
                       (1.80, 9.50, "p"), (4.15, 13.50, "p")):
        t.append(f"CF {'ndiffc' if kind == 'n' else 'pdiffc'} {x} {y}")
        t.append(f"VIA {x} {y}")
    # gate contact
    t.append(f"CF pc 2.675 1.20")
    t.append(f"VIA 2.675 1.20")
    # well taps
    t.append(f"VIA 1.225 15.725")
    t.append(f"VIA 1.225 1.075")

    # ---- m1 routing --------------------------------------------------------
    t.append(f"R m1 {GND[0]} {GND[2]} {GND[1]} {GND[3]}")
    t.append(f"R m1 {VDD[0]} {VDD[2]} {VDD[1]} {VDD[3]}")
    # nfet source down to gnd, pfet source up to vdd
    t.append(f"R m1 1.66 0.80 1.94 3.20")
    t.append(f"R m1 1.66 9.30 1.94 16.00")
    # drains joined
    t.append(f"R m1 4.01 2.80 4.29 13.70")
    # nwell tap to vdd, psub tap to gnd
    t.append(f"R m1 0.55 15.60 1.50 16.20")   # n-tap to vdd
    t.append(f"R m1 0.55 0.30 1.50 1.20")     # p-tap to gnd
    # gate port
    t.append(f"R m1 2.55 1.05 3.60 1.35")

    # ---- ports -------------------------------------------------------------
    t.append("L d 4.15 5.90")
    t.append("L g 3.40 1.20")
    t.append("L vdd 2.90 16.22")
    t.append("L vss 2.90 0.58")
    for i, p in enumerate(("d", "g", "vdd", "vss"), start=1):
        xe, ye = {"d": (4.15, 5.90), "g": (3.40, 1.20), "vdd": (2.90, 16.22),
                  "vss": (2.90, 0.58)}[p]
        t.append(f"box {xe} {ye} {xe} {ye}")
        t.append(f"label {p}")
        t.append(f"port make {i}")

    t += ["select top cell", "save"]
    (work / "build.tcl").write_text("\n".join(t) + "\n")
    mu.run_magic(work / "build.tcl", work).need("inv_std build")


def main() -> None:
    build(HERE)
    print("wrote", HERE / f"{CELL}.mag")


if __name__ == "__main__":
    main()
