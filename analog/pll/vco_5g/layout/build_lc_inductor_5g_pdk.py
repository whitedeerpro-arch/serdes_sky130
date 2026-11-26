#!/usr/bin/env python3
"""SKY130A 5.0 GHz Symmetric Differential 3-Turn `met4 || met5` Spiral Inductor Layout Builder.

Builds `vco5g_ind_sym_2n2_pdk` for Arch C (5.0 GHz Complementary LC-VCO + /2 -> 2.50 GHz I/Q):
  - Outer dimension : D_out = 210.0 um (x, y in [-105 .. +105] um), inner hole = 122.0 x 122.0 um
  - Conductor       : W = 12.0 um, S = 4.0 um (P = 16.0 um), parallel `met4 || met5` stitched with
                      dense `via4` arrays (R_sh,dc = 17.9 mOhm/sq vs 29 mOhm/sq met5-only)
  - Differential symmetry:
      * Port `p` (SW, x=-14) & Port `n` (SE, x=+14) on `met5`, 100% mirror-symmetric around x=0
      * Half-P: North M5 overpass (T0->T1) + South M3 underpass (T1->T2) -> Center-Tap `ct`
      * Half-N: North M3 underpass (T0->T1) + South M5 overpass (T1->T2) -> Center-Tap `ct`
      * Exact 1:1 matching of total length, M3 underpasses (1 each), and via transitions -> L_p == L_n, R_p == R_n
      * All 6 half-turns carry differential current clockwise -> 100% positive mutual inductance
  - Center-Tap `ct` (North, x=0): exits cleanly North on `met4` between M3 underpass & M5 overpass
  - Substrate isolation: Open-slotted P+ substrate guard ring at R = 122 um (broken at South to prevent eddy-current loop!)

All scratch/extraction files live strictly under `results/layout/vco_5g_ind_pdk/`;
only clean signed-off artifacts (`.mag`, `.png`, `summary.json`) are installed into
`analog/pll/vco_5g/layout/variants/ind_sym_2n2_pdk/`.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))

from geometry import Cell  # noqa: E402
import magicutil as mu  # noqa: E402

VARIANT_DIR = Path(__file__).resolve().parent / "variants" / "ind_sym_2n2_pdk"
RESULTS_DIR = REPO / "results" / "layout" / "vco_5g_ind_pdk"
PLOT_MAG = REPO / "verification" / "layout" / "plot_mag.py"


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def add_via4_strip(c: Cell, x1: float, y1: float, x2: float, y2: float, pitch: float = 2.40) -> int:
    """Fill rectangular overlap [x1..x2] x [y1..y2] with DRC-safe 1.18x1.18 via4 cuts (spacing >= 1.22 um)."""
    x1, x2 = sorted((grid(x1), grid(x2)))
    y1, y2 = sorted((grid(y1), grid(y2)))
    # Keep 1.2 um margin from metal edge to via4 center (cut half=0.59, enclosure=0.61 > 0.31 um rule)
    xs = []
    x = grid(x1 + 1.40)
    while x <= x2 - 1.40 + 1e-6:
        xs.append(x)
        x = grid(x + pitch)
    ys = []
    y = grid(y1 + 1.40)
    while y <= y2 - 1.40 + 1e-6:
        ys.append(y)
        y = grid(y + pitch)
    if not xs and (x2 - x1) >= 2.0:
        xs = [grid(0.5 * (x1 + x2))]
    if not ys and (y2 - y1) >= 2.0:
        ys = [grid(0.5 * (y1 + y2))]
    # Center the grid cleanly
    if len(xs) > 1:
        ox = grid(0.5 * ((x1 + x2) - (xs[0] + xs[-1])))
        xs = [grid(v + ox) for v in xs]
    if len(ys) > 1:
        oy = grid(0.5 * ((y1 + y2) - (ys[0] + ys[-1])))
        ys = [grid(v + oy) for v in ys]
    cnt = 0
    for xv in xs:
        for yv in ys:
            c.pad("via4", xv, yv, 1.18)
            cnt += 1
    return cnt


def add_via3_array(c: Cell, x1: float, y1: float, x2: float, y2: float, pitch: float = 0.80) -> int:
    """Fill [x1..x2] x [y1..y2] with DRC-safe 0.32x0.32 via3 cuts (M3<->M4)."""
    x1, x2 = sorted((grid(x1), grid(x2)))
    y1, y2 = sorted((grid(y1), grid(y2)))
    xs, ys = [], []
    x = grid(x1 + 0.60)
    while x <= x2 - 0.60 + 1e-6:
        xs.append(x)
        x = grid(x + pitch)
    y = grid(y1 + 0.60)
    while y <= y2 - 0.60 + 1e-6:
        ys.append(y)
        y = grid(y + pitch)
    if len(xs) > 1:
        ox = grid(0.5 * ((x1 + x2) - (xs[0] + xs[-1])))
        xs = [grid(v + ox) for v in xs]
    if len(ys) > 1:
        oy = grid(0.5 * ((y1 + y2) - (ys[0] + ys[-1])))
        ys = [grid(v + oy) for v in ys]
    cnt = 0
    for xv in xs:
        for yv in ys:
            c.pad("via3", xv, yv, 0.32)
            cnt += 1
    return cnt


def build_inductor_cell() -> tuple[Cell, dict]:
    c = Cell()

    W = 12.0       # trace width (um)
    S = 4.0        # turn-to-turn spacing (um)
    P = W + S      # 16.0 um pitch
    R0 = 99.0      # Turn 0 centerline (outer edge = 105.0 -> D_out = 210.0 um)
    R1 = R0 - P    # 83.0 um
    R2 = R1 - P    # 67.0 um
    hw = W / 2.0   # 6.0 um
    X_BR = 16.0    # bridge pad centerline (+/-16.0 um -> metal edges at +/-10.0 .. +/-22.0, 20 um center gap!)

    via4_total = 0
    via3_total = 0

    def draw_parallel_seg(x1: float, y1: float, x2: float, y2: float, stitch_via4: bool = True) -> None:
        nonlocal via4_total
        c.rect("metal4", x1, y1, x2, y2)
        c.rect("metal5", x1, y1, x2, y2)
        if stitch_via4:
            via4_total += add_via4_strip(c, x1, y1, x2, y2, pitch=2.60)

    # -------------------------------------------------------------------------
    # 1. Parallel `met4 || met5` Main Winding Arms (100% mirror-symmetric!)
    # -------------------------------------------------------------------------
    # Turn 0 (R0 = 99.0): West & East vertical arms + SW/SE/NW/NE horizontal arms stopping at |x| = X_BR - hw = 10.0
    for sign in (-1.0, 1.0):
        # Vertical outer arm: x in [93..105], y in [-105..+105]
        vx1, vx2 = sorted((sign * (R0 - hw), sign * (R0 + hw)))
        draw_parallel_seg(vx1, -(R0 + hw), vx2, +(R0 + hw))
        # South horizontal arm: |x| in [X_BR - hw .. R0 - hw] = [10..93], y in [-105..-93]
        hx1, hx2 = sorted((sign * (X_BR - hw), sign * (R0 - hw)))
        draw_parallel_seg(hx1, -(R0 + hw), hx2, -(R0 - hw))
        # North horizontal arm: |x| in [X_BR - hw .. R0 - hw] = [10..93], y in [+93..+105]
        draw_parallel_seg(hx1, +(R0 - hw), hx2, +(R0 + hw))

        # Turn 1 (R1 = 83.0): Vertical arm + North/South horizontal arms stopping at |x| = X_BR - hw = 10.0
        vx1, vx2 = sorted((sign * (R1 - hw), sign * (R1 + hw)))
        draw_parallel_seg(vx1, -(R1 + hw), vx2, +(R1 + hw))
        hx1, hx2 = sorted((sign * (X_BR - hw), sign * (R1 - hw)))
        draw_parallel_seg(hx1, -(R1 + hw), hx2, -(R1 - hw))
        draw_parallel_seg(hx1, +(R1 - hw), hx2, +(R1 + hw))

        # Turn 2 (R2 = 67.0): Vertical arm + South horizontal arm stopping at |x| = 10.0 + continuous North bar to x=0 (CT!)
        vx1, vx2 = sorted((sign * (R2 - hw), sign * (R2 + hw)))
        draw_parallel_seg(vx1, -(R2 + hw), vx2, +(R2 + hw))
        hx1, hx2 = sorted((sign * (X_BR - hw), sign * (R2 - hw)))
        draw_parallel_seg(hx1, -(R2 + hw), hx2, -(R2 - hw))
        # North Turn 2 joins cleanly at x = 0 (center tap!)
        nx1, nx2 = sorted((0.0, sign * (R2 - hw)))
        draw_parallel_seg(nx1, +(R2 - hw), nx2, +(R2 + hw))

    # -------------------------------------------------------------------------
    # 2. Symmetric Differential Port Leads (`p` at x=-16, `n` at x=+16, South)
    # -------------------------------------------------------------------------
    y_port_s = -118.0
    for x_p, pnm in ((-X_BR, "p"), (+X_BR, "n")):
        draw_parallel_seg(x_p - hw, y_port_s, x_p + hw, -(R0 + hw))
        c.port(pnm, "metal5", x_p, y_port_s + 2.0)

    # -------------------------------------------------------------------------
    # 3. Symmetric North Cross-Over (Turn 0 <-> Turn 1)
    #    - Half-P (NW T0 -> NE T1): M5 overpass (-10, +99) -> (0, +99) -> (0, +83) -> (+10, +83)
    #    - Half-N (NE T0 -> NW T1): M3 underpass (+16, +99) -> (-16, +99) -> (-16, +83)
    #      Note: M4 at x in [-3..+3] is reserved for Center-Tap `ct` -> M3 passes below & M5 above!
    # -------------------------------------------------------------------------
    # P-side M5 overpass (width 12.0 um, clean solid Manhattan Z-bridge!)
    c.rect("metal5", -X_BR + hw, R0 - hw, +hw, R0 + hw)          # [-10..+6] x [93..105]
    c.rect("metal5", -hw, R1 - hw, +hw, R0 + hw)                 # [-6..+6]  x [77..105]
    c.rect("metal5", -hw, R1 - hw, +X_BR - hw, R1 + hw)          # [-6..+10] x [77..89]

    # N-side M3 underpass: via3 drop at NE T0 (+16, +99) -> M3 West at y=+99 -> South at x=-16 -> via3 rise at NW T1 (-16, +83)!
    # Wait: keep M3 South leg at x=-16 completely clear of Turn 0 NW M3 (none there) and pad cleanly into M4 at (-16, +83)!
    # Drop pad at (+16, +99): [10..22] x [93..105]
    c.rect("metal3", X_BR - hw, R0 - hw, X_BR + hw, R0 + hw)
    via3_total += add_via3_array(c, X_BR - hw + 0.5, R0 - hw + 0.5, X_BR + hw - 0.5, R0 + hw - 0.5)
    # Horizontal M3 bridge across x=0 at y=+99: [-22..+22] x [93..105]
    c.rect("metal3", -(X_BR + hw), R0 - hw, +(X_BR + hw), R0 + hw)
    # Vertical M3 drop from y=+99 to y=+83 at x=-16: [-22..-10] x [77..105]
    c.rect("metal3", -(X_BR + hw), R1 - hw, -(X_BR - hw), R0 + hw)
    # Rise via3 at NW T1 (-16, +83): [-22..-10] x [77..89]
    via3_total += add_via3_array(c, -(X_BR + hw) + 0.5, R1 - hw + 0.5, -(X_BR - hw) - 0.5, R1 + hw - 0.5)

    # -------------------------------------------------------------------------
    # 4. Symmetric South Cross-Over (Turn 1 <-> Turn 2, exact opposite layer assignment!)
    #    - Half-N (SW T1 -> SE T2): M5 overpass (-10, -83) -> (0, -83) -> (0, -67) -> (+10, -67)
    #    - Half-P (SE T1 -> SW T2): M3 underpass (+16, -83) -> (-16, -83) -> (-16, -67)
    # -------------------------------------------------------------------------
    # N-side M5 overpass (width 12.0 um)
    c.rect("metal5", -X_BR + hw, -(R1 + hw), +hw, -(R1 - hw))    # [-10..+6] x [-89..-77]
    c.rect("metal5", -hw, -(R1 + hw), +hw, -(R2 - hw))           # [-6..+6]  x [-89..-61]
    c.rect("metal5", -hw, -(R2 + hw), +X_BR - hw, -(R2 - hw))    # [-6..+10] x [-73..-61]

    # P-side M3 underpass: drop at SE T1 (+16, -83) -> West at y=-83 -> North at x=-16 -> rise at SW T2 (-16, -67)
    c.rect("metal3", X_BR - hw, -(R1 + hw), X_BR + hw, -(R1 - hw))
    via3_total += add_via3_array(c, X_BR - hw + 0.5, -(R1 + hw) + 0.5, X_BR + hw - 0.5, -(R1 - hw) - 0.5)
    c.rect("metal3", -(X_BR + hw), -(R1 + hw), +(X_BR + hw), -(R1 - hw))
    c.rect("metal3", -(X_BR + hw), -(R1 + hw), -(X_BR - hw), -(R2 - hw))
    via3_total += add_via3_array(c, -(X_BR + hw) + 0.5, -(R2 + hw) + 0.5, -(X_BR - hw) - 0.5, -(R2 - hw) - 0.5)

    # -------------------------------------------------------------------------
    # 5. Center-Tap `ct` Exit North on `met4` (x in [-4.0..+4.0], 6.0 um clear of |x|>=10.0 M4 arms!)
    #    Passes strictly BETWEEN North M3 underpass and North M5 overpass!
    # -------------------------------------------------------------------------
    y_port_n = +118.0
    c.rect("metal4", -4.0, +(R2 - hw), +4.0, y_port_n)
    # Transition to M5 pad outside North edge (y in [109.5..118.0], 4.5 um clear of Turn 0 M5 <= 105.0!)
    c.rect("metal5", -4.0, +109.5, +4.0, y_port_n)
    via4_total += add_via4_strip(c, -4.0, +109.5, +4.0, y_port_n, pitch=2.40)
    c.port("ct", "metal5", 0.0, y_port_n - 2.0)

    # -------------------------------------------------------------------------
    # 6. Open-Slotted P+ Substrate Guard Ring at R_g = 123.0 um (broken at South to prevent eddy loop!)
    # -------------------------------------------------------------------------
    rg = 123.0
    gw = 2.0
    # 3 sides + slotted South arms stopping at |x| = 28.0 (clear of p/n leads at |x| <= 22.0 & breaks DC loop!)
    segs = [
        (-rg, -rg, -rg, +rg),      # West
        (+rg, -rg, +rg, +rg),      # East
        (-rg, +rg, +rg, +rg),      # North (note: M1/psubdiff strictly below ct M4/M5!)
        (-rg, -rg, -28.0, -rg),    # South-West
        (+28.0, -rg, +rg, -rg),    # South-East
    ]
    for sx1, sy1, sx2, sy2 in segs:
        xlo, xhi = min(sx1, sx2) - gw / 2.0, max(sx1, sx2) + gw / 2.0
        ylo, yhi = min(sy1, sy2) - gw / 2.0, max(sy1, sy2) + gw / 2.0
        for lyr in ("psubdiff", "locali", "metal1"):
            c.rect(lyr, xlo, ylo, xhi, yhi)
        if abs(sx1 - sx2) < 1e-6:
            yc = grid(min(sy1, sy2) + 1.5)
            while yc <= max(sy1, sy2) - 1.5 + 1e-6:
                c.pad("psubdiffcont", sx1, yc, 0.17)
                c.pad("viali", sx1, yc, 0.17)
                yc = grid(yc + 2.5)
        else:
            xc = grid(min(sx1, sx2) + 1.5)
            while xc <= max(sx1, sx2) - 1.5 + 1e-6:
                c.pad("psubdiffcont", xc, sy1, 0.17)
                c.pad("viali", xc, sy1, 0.17)
                xc = grid(xc + 2.5)
    c.port("sub", "metal1", -rg, 0.0)

    # Analytical modified Wheeler estimate (square 3-turn spiral, K1=2.34, K2=2.75)
    d_out = 210.0e-6
    d_in = 122.0e-6
    d_avg = 0.5 * (d_out + d_in)
    rho = (d_out - d_in) / (d_out + d_in)
    mu0 = 4.0 * math.pi * 1e-7
    n_turns = 3
    l_wheeler_nh = 2.34 * mu0 * (n_turns ** 2) * d_avg / (1.0 + 2.75 * rho) * 1e9

    # Exact total trace length per half-coil & DC resistance estimate
    # Each turn perimeter = 4 * (2*R_k) = 8*R_k -> total 3-turn length = 8*(99+83+67) = 1992 um (~166 sq @ W=12 um)
    total_len_um = 8.0 * (R0 + R1 + R2) + 2.0 * (118.0 - 105.0)
    n_sq_m45 = (total_len_um - 2.0 * 48.0) / W
    n_sq_m3 = (2.0 * 48.0) / W
    r_sh_m45_tt = (0.029 * 0.047) / (0.029 + 0.047)   # 17.93 mOhm/sq (met5 || met4)
    r_sh_m3_tt = 0.047
    r_dc_ohm = n_sq_m45 * r_sh_m45_tt + n_sq_m3 * r_sh_m3_tt

    meta = {
        "d_out_um": 210.0,
        "d_in_um": 122.0,
        "width_um": W,
        "spacing_um": S,
        "turns": n_turns,
        "total_trace_len_um": round(total_len_um, 1),
        "via4_cuts": via4_total,
        "via3_cuts": via3_total,
        "l_wheeler_square_nh": round(l_wheeler_nh, 3),
        "r_dc_tt_ohm": round(r_dc_ohm, 3),
    }
    return c, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install", action="store_true", help="Install clean DRC=0 artifacts into variants/ind_sym_2n2_pdk/")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cell_name = "vco5g_ind_sym_2n2_pdk"
    mag = RESULTS_DIR / f"{cell_name}.mag"
    png = RESULTS_DIR / f"{cell_name}.png"

    cell, meta = build_inductor_cell()
    cell.write(mag)

    # Run Magic full-rule DRC + CPEX extraction
    tcl = RESULTS_DIR / "_check.tcl"
    tcl.write_text("\n".join([
        "drc off",
        f"load {cell_name}",
        "select top cell",
        "drc on",
        "drc euclidean on",
        "drc style drc(full)",
        "drc check",
        "drc catchup",
        'puts "DRC_TOTAL [drc list count total]"',
        'foreach {why boxes} [drc listall why] { puts "DRC_RULE [llength $boxes] | $why" }',
        "drc off",
        "extract all",
        "ext2spice lvs",
        "ext2spice cthresh 0",
        "ext2spice extresist off",
        f"ext2spice -o {cell_name}_pex.spice",
        "quit -noprompt",
    ]) + "\n")
    res = mu.run_magic(tcl, cwd=RESULTS_DIR)
    (RESULTS_DIR / "magic_check.log").write_text(res.log)
    m_drc = re.search(r"DRC_TOTAL (\d+)", res.log)
    drc_total = int(m_drc.group(1)) if m_drc else -1
    drc_rules = [f"{m.group(1)} | {m.group(2).strip()}" for m in re.finditer(r"DRC_RULE (\d+) \| (.+)", res.log)]

    # Parse extracted total capacitance on ports (p, n, ct) from PEX
    pex_txt = (RESULTS_DIR / f"{cell_name}_pex.spice").read_text() if (RESULTS_DIR / f"{cell_name}_pex.spice").exists() else ""
    caps_ff: dict[str, float] = {}
    for ln in pex_txt.splitlines():
        if ln.startswith("C"):
            toks = ln.split()
            if len(toks) >= 4:
                val_s = toks[3].lower()
                mult = 1e15
                if val_s.endswith("f"):
                    val = float(val_s[:-1])
                elif val_s.endswith("p"):
                    val = float(val_s[:-1]) * 1e3
                else:
                    val = float(val_s) * mult
                key = f"{toks[1]}--{toks[2]}"
                caps_ff[key] = round(caps_ff.get(key, 0.0) + val, 3)

    # Render PNG (plot_mag.py takes positional <mag> <png>)
    subprocess.run([sys.executable, str(PLOT_MAG), str(mag), str(png)], check=True)

    bb = cell.bbox()
    w_um = round(bb[2] - bb[0], 3)
    h_um = round(bb[3] - bb[1], 3)
    summary = {
        "cell": cell_name,
        "pdk": "sky130A",
        "bbox_um": [round(v, 3) for v in bb],
        "width_um": w_um,
        "height_um": h_um,
        "area_um2": round(w_um * h_um, 2),
        "drc_total": drc_total,
        "drc_rules": drc_rules,
        "geometry_and_analytical": meta,
        "pex_caps_fF": caps_ff,
    }
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))

    assert drc_total == 0, f"DRC failed: {drc_total} {drc_rules}"
    if args.install:
        VARIANT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(mag, VARIANT_DIR / mag.name)
        shutil.copy2(png, VARIANT_DIR / png.name)
        (VARIANT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Installed clean DRC=0 inductor -> {VARIANT_DIR}")


if __name__ == "__main__":
    main()
