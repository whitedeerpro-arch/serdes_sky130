"""Build and verify the VCO Differential Delay Stage (Core Plan C: Abutted-Guard Twin-8f [P | N])
and the Complete Interlocked Single VCO Stage (Delay Core C + Left/Right Inward-Recess Half-Tanks).
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

from serdes_flow import project

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from geometry import Cell, pdk_device

sys.path.insert(0, str(ROOT / "analog/pll/vco/layout"))
from build_half_tank_sym9_pdk import build_half_tank


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.50)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.50)


def rotate_cell_90(src: Cell, direction: str) -> Cell:
    """Rotate a Cell so its bottom recess (-y) points to +x ('recess_right') or -x ('recess_left').
    - 'recess_right': (x, y) -> (-y, x)
    - 'recess_left':  (x, y) -> (y, x)
    """
    dst = Cell()
    for layer, rects in src.rects.items():
        new_rects = []
        for x0, y0, x1, y1 in rects:
            if direction == "recess_right":
                nx0, nx1 = sorted((-y0, -y1))
                ny0, ny1 = sorted((x0, x1))
            elif direction == "recess_left":
                nx0, nx1 = sorted((y0, y1))
                ny0, ny1 = sorted((x0, x1))
            else:
                raise ValueError(direction)
            new_rects.append((grid(nx0), grid(ny0), grid(nx1), grid(ny1)))
        dst.rects[layer] = new_rects
    for layer, x, y, text in src.labels:
        if direction == "recess_right":
            nx, ny = grid(-y), grid(x)
        else:
            nx, ny = grid(y), grid(x)
        dst.labels.append((layer, nx, ny, text))
    return dst


def build_clean_inp8(work: Path) -> Cell:
    """Build an nf=8, w=5.0 um LVT NMOS with:
    1) Top redundant gate strap/contacts removed (facing top drain exit),
    2) S/D vertical layer separation: source fingers have viali+metal1 only at bottom contact
       [-2.44, -1.60], drain fingers have viali+metal1 only at upper channel [-1.44, +2.44].
    """
    inp = pdk_device(
        work,
        "inp8_pdk",
        "sky130_fd_pr__nfet_01v8_lvt",
        dict(w=5.0, l=0.15, nf=8, conn_gates=1),
    )
    inp.rects.pop("checkpaint", None)

    sd = sorted({grid((r[0] + r[2]) / 2) for r in inp.rects["ndiffc"]})
    sources = sd[::2]   # 5 even columns: -1.92, -0.96, 0.0, 0.96, 1.92
    drains = sd[1::2]   # 4 odd columns:  -1.44, -0.48, 0.48, 1.44

    ndiff_top = max(r[3] for r in inp.rects["ndiff"])  # +2.50
    ndiff_bot = min(r[1] for r in inp.rects["ndiff"])  # -2.50
    guard_top = max((r[1] + r[3]) / 2 for r in inp.rects["psubdiffcont"])  # +3.285

    # 1. Remove redundant top gate contacts (y > 0) and top gate strap
    inp.rects["polycont"] = [r for r in inp.rects["polycont"] if r[1] < 0]
    inp.rects["locali"] = [
        r
        for r in inp.rects["locali"]
        if not (ndiff_top + 0.02 < r[1] < guard_top - 0.10 and ndiff_top + 0.02 < r[3] < guard_top - 0.10)
    ]
    inp.rects["viali"] = [r for r in inp.rects["viali"] if r[3] < ndiff_top + 0.05]
    inp.rects["metal1"] = [r for r in inp.rects["metal1"] if r[3] < ndiff_top + 0.05]

    new_poly = []
    for r in inp.rects["poly"]:
        if r[1] >= ndiff_top + 0.10:
            continue
        elif r[3] > ndiff_top:
            new_poly.append((r[0], r[1], r[2], grid(ndiff_top + 0.18)))
        else:
            new_poly.append(r)
    inp.rects["poly"] = new_poly

    # Add symmetric left/right dummy poly fingers between outer ndiff (+-2.065) and psubdiff (+-2.405):
    for sign in (-1.0, 1.0):
        inp.rect("poly", grid(sign * 2.160), -ndiff_top, grid(sign * 2.310), ndiff_top)

    # 2. Replace S/D finger viali and metal1 inside y in [-2.51, +2.51] with properly-enclosed trimmed bars:
    inp.rects["viali"] = [r for r in inp.rects["viali"] if not (ndiff_bot - 0.02 <= r[1] and r[3] <= ndiff_top + 0.02)]
    inp.rects["metal1"] = [r for r in inp.rects["metal1"] if not (ndiff_bot - 0.02 <= r[1] and r[3] <= ndiff_top + 0.02)]

    for sx in sources:
        inp.rects["viali"].append((grid(sx - 0.085), -2.44, grid(sx + 0.085), -1.60))
        inp.rects["metal1"].append((grid(sx - 0.115), -2.50, grid(sx + 0.115), -1.54))
    for dx in drains:
        inp.rects["viali"].append((grid(dx - 0.085), -1.44, grid(dx + 0.085), 2.44))
        inp.rects["metal1"].append((grid(dx - 0.115), -1.50, grid(dx + 0.115), 2.50))

    return inp


def build_delay_core_c(work: Path) -> tuple[Cell, dict]:
    """Build and verify `pll_vco_delay_sym9_c` (Core Plan C)."""
    cdir = work / "delay_core_c"
    cdir.mkdir(parents=True, exist_ok=True)
    name = "pll_vco_delay_sym9_c"

    inp8 = build_clean_inp8(cdir)
    tail = pdk_device(cdir, "tail_pdk", "sky130_fd_pr__nfet_01v8", dict(w=6.3, l=0.5, nf=4, conn_gates=1))
    load = pdk_device(cdir, "load_pdk", "sky130_fd_pr__res_high_po_2p85", dict(l=4.77))
    for prim in (tail, load):
        prim.rects.pop("checkpaint", None)

    # Expand tail guard ring horizontally by +-0.40 um and add symmetric L=0.50 um dummy poly fingers:
    tail.rects["pwell"] = [(-2.815, -4.20, 2.815, 4.20)]
    tail.rects["psubdiff"] = [
        (-2.635, 3.85, -1.755, 4.02),
        (1.755, 3.85, 2.635, 4.02),
        (-2.635, 3.54, -2.465, 3.85),
        (2.465, 3.54, 2.635, 3.85),
        (-2.635, -3.85, -2.465, -3.54),
        (2.465, -3.85, 2.635, -3.54),
        (-2.635, -4.02, -1.755, -3.85),
        (1.755, -4.02, 2.635, -3.85),
    ]
    tail.rects["psubdiffcont"] = [
        (-1.755, 3.85, 1.755, 4.02),
        (-2.635, -3.54, -2.465, 3.54),
        (2.465, -3.54, 2.635, 3.54),
        (-1.755, -4.02, 1.755, -3.85),
    ]
    new_tail_li = []
    for x0, y0, x1, y1 in tail.rects["locali"]:
        if (x0, x1) == (-2.235, -1.755):
            new_tail_li.append((-2.635, y0, -1.755, y1))
        elif (x0, x1) == (1.755, 2.235):
            new_tail_li.append((1.755, y0, 2.635, y1))
        elif (x0, x1) == (-2.235, -2.065):
            new_tail_li.append((-2.635, y0, -2.465, y1))
        elif (x0, x1) == (2.065, 2.235):
            new_tail_li.append((2.465, y0, 2.635, y1))
        else:
            new_tail_li.append((x0, y0, x1, y1))
    tail.rects["locali"] = new_tail_li
    tail_nd_y = max(r[3] for r in tail.rects["ndiff"])  # 3.15
    for sign in (-1.0, 1.0):
        x0, x1 = sorted((grid(sign * 1.845), grid(sign * 2.345)))
        tail.rect("poly", x0, -tail_nd_y, x1, tail_nd_y)

    # Build a full-size (W=2.85 um, L_total=8.93 um) dummy resistor cell matching `load` in guard ring,
    # poly body, and head contacts (`polycont, locali, viali, metal1`), grounded to its guard ring on LI1:
    load_dummy = Cell()
    for lyr in ("pwell", "psubdiff", "psubdiffcont", "locali", "viali", "metal1"):
        load_dummy.rects[lyr] = list(load.rects[lyr])
    load_dummy.rect("poly", -1.425, -4.465, 1.425, 4.465)
    load_dummy.rects["locali"].extend([
        (-1.425, +2.305, +1.425, +4.465),
        (-1.425, -4.465, +1.425, -2.305),
        (-0.20, -4.945, +0.20, -4.465),
    ])
    load_dummy.rects["polycont"] = [
        (-1.345, +2.39, +1.345, +4.375),
        (-1.345, -4.375, +1.345, -2.39),
    ]

    c = Cell()

    # Place Left (Xmp, dx = -2.49) and Right (Xmn, dx = +2.49, mirror_x=True) so their inner psubdiffcont
    # guard bars (at +-2.49 in local coords) merge cleanly on the symmetry axis x = 0.00!
    inp_dx = 2.49
    c.include(inp8, dx=-inp_dx, mirror_x=False)
    c.include(inp8, dx=inp_dx, mirror_x=True)

    sd_local = sorted({grid((r[0] + r[2]) / 2) for r in inp8.rects["ndiffc"]})
    sources_local = sd_local[::2]
    drains_local = sd_local[1::2]

    drain_y = 2.00
    source_y = -2.00

    for sign in (-1.0, 1.0):
        cx = sign * inp_dx
        drains = sorted([grid(cx + d) for d in drains_local])
        sources = sorted([grid(cx + s) for s in sources_local])
        for dx in drains:
            c.via1(dx, drain_y)
        c.wire("metal2", [(drains[0], drain_y), (drains[-1], drain_y)], 0.36)
        for sx in sources:
            c.via1(sx, source_y)

    # Continuous M2 tail bar across all 10 source columns
    c.wire("metal2", [(grid(-inp_dx + sources_local[0]), source_y), (grid(inp_dx + sources_local[-1]), source_y)], 0.40)

    # Input pair top guard contacts -> body_rail_y
    body_top_y = 3.285
    body_rail_y = 5.15
    for gx in (-inp_dx, inp_dx):
        c.body_contact(gx, body_top_y)
        c.wire("metal2", [(gx, body_top_y), (gx, body_rail_y)], 0.36)

    # Gate connections: inp (left) and inn (right)
    gate_strap_y = -2.775
    inp_y = -4.50
    for sign in (-1.0, 1.0):
        gx = grid(sign * inp_dx)
        c.wire("metal1", [(gx, gate_strap_y), (gx, inp_y)], 0.26)
        c.wire("metal1", [(grid(gx - 1.70), inp_y), (grid(gx + 1.70), inp_y)], 0.28)
        c.via1(gx, inp_y)
        c.wire("metal2", [(grid(gx - 1.20), inp_y), (grid(gx + 1.20), inp_y)], 0.36)

    # Place 4 Load resistors above input pair at pitch = 4.80 um:
    # Left pair (Rp1, Rp2 -> outp): x = -7.20, -2.40
    # Right pair (Rn1, Rn2 -> outn): x = +2.40, +7.20
    res_xs = [-7.20, -2.40, 2.40, 7.20]
    out_bar_y = 4.20
    load_y = grid(body_rail_y + 0.67 - load.pins("B")[0][1])  # 10.85
    vdd_y = grid(load_y + load.pins("R1")[0][1] + 0.85)       # 15.99

    # Disjoint M4 output bars at y = out_bar_y = 4.20:
    c.wire("metal4", [(-7.20, out_bar_y), (-2.40, out_bar_y)], 0.50)
    c.wire("metal4", [(2.40, out_bar_y), (7.20, out_bar_y)], 0.50)

    # Lift input pair drains_p (at x = -2.40) and drains_n (at x = +2.40) via M3 up to out_bar_y
    for sign in (-1.0, 1.0):
        rx = sign * 2.40
        c.via2(rx, drain_y)
        c.wire("metal3", [(rx, drain_y), (rx, out_bar_y)], 0.40)
        via3(c, rx, out_bar_y)

    for rx in res_xs:
        c.include(load, dx=rx, dy=load_y)
        r2_y = grid(load_y + load.pins("R2")[0][1])
        c.via1(rx, r2_y)
        c.via2(rx, r2_y)
        c.wire("metal3", [(rx, r2_y), (rx, out_bar_y)], 0.40)
        via3(c, rx, out_bar_y)

        r1_y = grid(load_y + load.pins("R1")[0][1])
        c.via1(rx, r1_y)
        c.wire("metal2", [(rx, r1_y), (rx, vdd_y)], 0.60)

        bx, by = load.pins("B")[0]
        bx, by = grid(bx + rx), grid(by + load_y)
        c.body_contact(bx, by)
        c.wire("metal2", [(bx, by), (bx, body_rail_y)], 0.40)

    # Full-size (W=2.85 um, L_total=8.93 um) dummy resistor blocks with guard rings at +-12.00 um
    # (exact 4.80 um pitch outside the 4 active load resistors, tucked underneath the b3/b4 MIM caps):
    for dx_dum in (-12.00, 12.00):
        c.include(load_dummy, dx=dx_dum, dy=load_y)
        bx, by = load.pins("B")[0]
        bx, by = grid(bx + dx_dum), grid(by + load_y)
        c.body_contact(bx, by)
        c.wire("metal2", [(bx, by), (bx, body_rail_y)], 0.40)

    # Top VDD bar (kept within [-7.80, +7.80]) and upper body_rail_y (extended to +-12.40 for dummy guard rings)
    vss_strap_x = 5.40
    c.wire("metal2", [(-7.80, vdd_y), (7.80, vdd_y)], 0.90)
    c.wire("metal2", [(-12.40, body_rail_y), (12.40, body_rail_y)], 0.60)

    # Place Tail NMOS below input pair
    tail_y = -9.80
    ground_y = -15.60
    c.include(tail, dy=tail_y)
    tsd = sorted({grid((r[0] + r[2]) / 2) for r in tail.rects["ndiffc"]})
    tdy = grid(6.3 / 2 - 0.50)  # 2.65
    for k, tx in enumerate(tsd):
        c.via1(tx, grid(tail_y + (tdy if k % 2 else -tdy)))
    tdrains, tsources = tsd[1::2], tsd[::2]
    td_y = grid(tail_y + tdy)
    ts_y = grid(tail_y - tdy)
    c.wire("metal2", [(tdrains[0], td_y), (tdrains[-1], td_y)], 0.50)
    c.via2(0.0, td_y)
    c.wire("metal3", [(0.0, td_y), (0.0, source_y)], 0.70)
    c.via2(0.0, source_y)

    c.wire("metal2", [(tsources[0], ts_y), (tsources[-1], ts_y)], 0.60)
    for tx in (tsources[0], tsources[-1]):
        c.wire("metal2", [(tx, ts_y), (tx, ground_y)], 0.50)

    tbx, tby = tail.pins("B")[0]
    tby = grid(tby + tail_y)
    c.body_contact(tbx, tby)
    c.wire("metal2", [(tbx, tby), (tbx, ground_y)], 0.50)

    tgx, tgy = tail.pins("G")[0]
    tgy = grid(tgy + tail_y)
    bias_x = -2.40
    bias_y = grid(ground_y + 1.00)
    c.wire("metal1", [(tgx, tgy), (bias_x, tgy), (bias_x, bias_y)], 0.24)
    c.via1(bias_x, bias_y)

    # Vertical VSS straps at x = +-5.40 (just outside inp8 outer edge +-5.245!)
    c.wire("metal2", [(-vss_strap_x, ground_y), (vss_strap_x, ground_y)], 0.90)
    for sx in (-vss_strap_x, vss_strap_x):
        c.wire("metal2", [(sx, ground_y), (sx, body_rail_y)], 0.50)

    c.labels = []
    c.port("inp", "metal2", -inp_dx, inp_y)
    c.port("inn", "metal2", inp_dx, inp_y)
    c.port("outp", "metal4", -7.20, out_bar_y)
    c.port("outn", "metal4", 7.20, out_bar_y)
    c.port("vbias", "metal2", bias_x, bias_y)
    c.port("vdd", "metal2", 0.0, vdd_y)
    c.port("vss", "metal2", 0.0, ground_y)
    c.write(cdir / f"{name}.mag")

    ref_lines = [
        f".subckt {name} inp inn outp outn vbias vdd vss",
        "Xp outp inp tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15",
        "Xn outn inn tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15",
        "Xt tail vbias vss vss sky130_fd_pr__nfet_01v8 w=25.2 l=0.5",
        "Xrp1 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrp2 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrn1 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        "Xrn2 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77",
        f".ends {name}\n",
    ]
    ref_path = cdir / "reference.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(ROOT / "verification/layout/check.py"), str(cdir), name, "--ref", str(ref_path)],
        capture_output=True,
        text=True,
    )
    (cdir / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr, flush=True)
    if proc.returncode:
        raise RuntimeError(f"Delay core check failed: {cdir / 'check.log'}")

    bx1, by1, bx2, by2 = c.bbox()
    meta = dict(
        cell=name,
        bbox_um=[round(bx1, 3), round(by1, 3), round(bx2, 3), round(by2, 3)],
        width_um=round(bx2 - bx1, 3),
        height_um=round(by2 - by1, 3),
        area_um2=round((bx2 - bx1) * (by2 - by1), 2),
        drc=0,
        lvs=True,
    )
    (cdir / "summary.json").write_text(json.dumps(meta, indent=2) + "\n")
    return c, meta


def build_docked_stage(work: Path, core_cell: Cell, variant: str = "s32p5") -> dict:
    """Build and verify the Complete Interlocked Single VCO Stage:
    `pll_vco_stage_sym9_<variant>` = `pll_vco_delay_sym9_c` + Left `Tank-P` + Right `Tank-N`.
    """
    build_half_tank(work, variant)
    tank_dir = work / variant
    tank_name = f"pll_vco_half_tank_sym9_{variant}"
    tank_cell = Cell.read(tank_dir / f"{tank_name}.mag")
    tank_cell.labels = []

    tank_left = rotate_cell_90(tank_cell, "recess_right")
    tank_right = rotate_cell_90(tank_cell, "recess_left")

    sdir = work / f"stage_{variant}"
    sdir.mkdir(parents=True, exist_ok=True)
    stage_name = f"pll_vco_stage_sym9_{variant}"

    stage = Cell()
    core_clean = Cell.read(work / "delay_core_c/pll_vco_delay_sym9_c.mag")
    core_clean.labels = []
    stage.include(core_clean)

    # Interlock Tank-P (left) and Tank-N (right) at cx = +-20.80 um!
    tank_cx = 20.80
    stage.include(tank_left, dx=-tank_cx, dy=0.0)
    stage.include(tank_right, dx=tank_cx, dy=0.0)

    # 1. Connect Delay Core `outp` (-7.20, 4.20) and `outn` (+7.20, 4.20) on M4 directly into
    #    Tank-P node (-20.80 + 11.02 = -9.78, y in [-2.87, +2.87]) and Tank-N node (+9.78, y in [-2.87, +2.87])!
    node_x = round(tank_cx - 11.02, 2)  # 9.78 um
    for sign in (-1.0, 1.0):
        stage.wire("metal4", [(sign * 7.20, 4.20), (sign * node_x, 4.20), (sign * node_x, 2.60)], 0.50)

    # 2. Connect Tank-P and Tank-N VSS (horizontal M2 bar at y = -5.40 and +5.15)
    #    straight across on M2 to Delay Core vertical VSS strap at x = +-5.40 / +-12.40!
    for sign in (-1.0, 1.0):
        stage.wire("metal2", [(sign * 5.40, -5.40), (sign * (tank_cx - 4.00), -5.40)], 0.40)
        stage.wire("metal2", [(sign * 12.40, +5.15), (sign * (tank_cx + 0.60), +5.15)], 0.40)

    # 3. Connect Tank-P and Tank-N M3 control tracks (b0..b4) down on M3 and across the bottom on M2,
    #    and bridge Varactor vctrl on M4 across (-9.34, -2.00) <-> (+9.34, -2.00):
    ctrl_tracks = [
        ("b0", 1.40, -19.30),
        ("b1", 2.10, -19.90),
        ("b2", 2.80, -20.50),
        ("b3", 3.50, -21.10),
        ("b4", 4.20, -21.70),
    ]
    for cname, ty_orig, y_bridge in ctrl_tracks:
        rx = round(tank_cx + ty_orig, 2)
        stage.wire("metal3", [(-rx, 0.0), (-rx, y_bridge)], 0.36)
        stage.wire("metal3", [(rx, 0.0), (rx, y_bridge)], 0.36)
        stage.via2(-rx, y_bridge)
        stage.via2(rx, y_bridge)
        stage.wire("metal2", [(-rx, y_bridge), (rx, y_bridge)], 0.32)
    vctrl_dx = round(tank_cx - 11.46, 2)  # 9.34 um
    stage.wire("metal4", [(-vctrl_dx, -2.00), (+vctrl_dx, -2.00)], 0.40)

    stage.labels = []
    stage.port("inp", "metal2", -2.49, -4.50)
    stage.port("inn", "metal2", 2.49, -4.50)
    stage.port("outp", "metal4", -7.20, 4.20)
    stage.port("outn", "metal4", 7.20, 4.20)
    stage.port("vbias", "metal2", -2.40, -14.60)
    stage.port("vdd", "metal2", 0.0, 15.99)
    stage.port("vss", "metal2", 0.0, -15.60)
    stage.port("vctrl", "metal4", 0.0, -2.00)
    for cname, _, y_bridge in ctrl_tracks:
        stage.port(cname, "metal2", 0.0, y_bridge)

    stage.write(sdir / f"{stage_name}.mag")

    # Build reference SPICE netlist for the complete stage (`delay_core + 2 x rotated half_tank`)
    # In Magic flat extraction, 90-deg rotation of sky130_fd_pr__cap_mim_m3_1 swaps X-span (w) and Y-span (l).
    tank_ref = re.sub(
        r"(sky130_fd_pr__cap_mim_m3_1\s+)w=(\S+)\s+l=(\S+)",
        r"\1w=\3 l=\2",
        (tank_dir / f"{tank_name}_reference.spice").read_text(),
    )
    stage_ref = (
        tank_ref
        + f"\n.subckt {stage_name} inp inn outp outn vbias vctrl b0 b1 b2 b3 b4 vdd vss\n"
        + "Xp outp inp tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15\n"
        + "Xn outn inn tail vss sky130_fd_pr__nfet_01v8_lvt w=40 l=0.15\n"
        + "Xt tail vbias vss vss sky130_fd_pr__nfet_01v8 w=25.2 l=0.5\n"
        + "Xrp1 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77\n"
        + "Xrp2 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.77\n"
        + "Xrn1 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77\n"
        + "Xrn2 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.77\n"
        + f"Xtankp outp vctrl b0 b1 b2 b3 b4 vss {tank_name}\n"
        + f"Xtankn outn vctrl b0 b1 b2 b3 b4 vss {tank_name}\n"
        + f".ends {stage_name}\n"
    )
    ref_path = sdir / "reference.spice"
    ref_path.write_text(stage_ref)

    proc = subprocess.run(
        [sys.executable, str(ROOT / "verification/layout/check.py"), str(sdir), stage_name, "--ref", str(ref_path)],
        capture_output=True,
        text=True,
    )
    (sdir / "check.log").write_text(proc.stdout + proc.stderr)
    print(proc.stdout + proc.stderr, flush=True)
    if proc.returncode:
        raise RuntimeError(f"Docked stage check failed: {sdir / 'check.log'}")

    bx1, by1, bx2, by2 = stage.bbox()
    smeta = dict(
        cell=stage_name,
        variant=variant,
        bbox_um=[round(bx1, 3), round(by1, 3), round(bx2, 3), round(by2, 3)],
        width_um=round(bx2 - bx1, 3),
        height_um=round(by2 - by1, 3),
        area_um2=round((bx2 - bx1) * (by2 - by1), 2),
        drc=0,
        lvs=True,
    )
    (sdir / "summary.json").write_text(json.dumps(smeta, indent=2) + "\n")
    return smeta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=None)
    ap.add_argument("--variant", default="s32p5")
    args = ap.parse_args()

    out = args.output_dir or (
        ROOT / "results/layout/pll_vco" / ("delay_stage_sym9_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    )
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    core_cell, cmeta = build_delay_core_c(out)
    smeta = build_docked_stage(out, core_cell, args.variant)
    summary = dict(delay_core=cmeta, docked_stage=smeta)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print("COMPLETE SUMMARY:", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
