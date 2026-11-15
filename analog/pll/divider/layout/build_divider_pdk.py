#!/usr/bin/env python3
"""Migrate Gemini's flush-column pll_cml_latch to PDK primitives.

Preserves Gemini's stacked CML latch floorplan (600-ohm high_po loads at top,
symmetric track/data, regen/hold, clock-steer differential pairs, centered tail
current source, and perimeter VSS guard trunks) matching
``analog/pll/divider/spice/cml_latch.spice``.

Usage:
    uv run python analog/pll/divider/layout/build_divider_pdk.py --output-dir results/layout/divider_pdk/run1
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.50)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.50)


def clean(work: Path, name: str, model: str, params: dict) -> Cell:
    prim = pdk_device(work, name, model, params)
    prim.rects.pop("checkpaint", None)
    return prim


def strap_mos_diff(
    c: Cell,
    prim: Cell,
    dx: float,
    dy: float,
    mirror_x: bool,
    finger_w: float,
) -> tuple[list[float], list[float], float, float]:
    """Via1 all diffusion fingers and connect drains (top) & sources (bottom) on M2."""
    sign = -1 if mirror_x else 1
    sd = sorted({grid(sign * (r[0] + r[2]) / 2.0 + dx) for r in prim.rects["ndiffc"]})
    cy = grid(finger_w / 2.0 - 0.5)
    d_y = grid(dy + cy)
    s_y = grid(dy - cy)
    for k, sx in enumerate(sd):
        c.via1(sx, d_y if k % 2 else s_y)
    drains = sd[1::2]
    sources = sd[::2]
    if len(drains) > 1:
        c.wire("metal2", [(drains[0], d_y), (drains[-1], d_y)], 0.36)
    if len(sources) > 1:
        c.wire("metal2", [(sources[0], s_y), (sources[-1], s_y)], 0.36)
    return drains, sources, d_y, s_y


def build_cml_latch(w: Path) -> dict:
    cell = "pll_cml_latch_pdk"
    cw = w / cell
    cw.mkdir(parents=True, exist_ok=True)

    data = clean(cw, "latch_data", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=4, conn_gates=1))
    hold = clean(cw, "latch_hold", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=4, conn_gates=1))
    clk = clean(cw, "latch_clk", "sky130_fd_pr__nfet_01v8_lvt", dict(w=6.0, l=0.15, nf=4, conn_gates=1))
    tail = clean(cw, "latch_tail", "sky130_fd_pr__nfet_01v8", dict(w=3.0, l=0.5, nf=4, conn_gates=1))
    load = clean(cw, "latch_load", "sky130_fd_pr__res_high_po_2p85", dict(l=4.14))

    half_max = max(-clk.bbox()[0], clk.bbox()[2], -data.bbox()[0], data.bbox()[2], -load.bbox()[0], load.bbox()[2])
    x_col = grid(half_max + 2.2)
    cols = (-x_col, +x_col)  # left = Rn / Xdp / Xhp / Xct (qn side), right = Rp / Xdn / Xhn / Xch (qp side)
    side_x = grid(x_col + half_max + 1.8)

    # Vertical stack (bottom -> top): ground -> tail -> clk -> hold -> data -> load -> vdd
    tail_y = 0.0
    ground_y = grid(tail_y + tail.bbox()[1] - 1.6)
    clk_y = grid(tail_y + tail.bbox()[3] + 2.4 - clk.bbox()[1])
    hold_y = grid(clk_y + clk.bbox()[3] + 3.4 - hold.bbox()[1])
    data_y = grid(hold_y + hold.bbox()[3] + 3.6 - data.bbox()[1])
    body_rail_y = grid(data_y + data.bbox()[3] + 1.6)
    load_y = grid(body_rail_y + 0.8 - load.bbox()[1])
    vdd_y = grid(load_y + load.bbox()[3] + 1.4)

    c = Cell()

    # Perimeter VSS M2 trunks (bottom ground + top body rail under resistors)
    c.wire("metal2", [(-side_x, ground_y), (side_x, ground_y)], 0.8)
    c.wire("metal2", [(-side_x, body_rail_y), (side_x, body_rail_y)], 0.6)
    for sx in (-side_x, +side_x):
        c.wire("metal2", [(sx, ground_y), (sx, body_rail_y)], 0.6)
    c.wire("metal2", [(-side_x, vdd_y), (side_x, vdd_y)], 0.8)

    # Tail NMOS (Xtail) at (0, 0)
    c.include(tail, dx=0.0, dy=tail_y)
    t_drains, t_sources, td_y, ts_y = strap_mos_diff(c, tail, 0.0, tail_y, False, 3.0)
    c.wire("metal2", [(t_sources[0], ts_y), (t_sources[0], ground_y)], 0.44)
    tbx, tby = tail.pins("B")[0]
    c.body_contact(grid(tbx), grid(tail_y + tby))
    c.wire("metal2", [(grid(tbx), grid(tail_y + tby)), (grid(tbx), ground_y)], 0.36)
    tgx, tgy = tail.pins("G")[0]
    bias_x = grid(-side_x + 1.6)
    # Stop 0.14um left of tgx so wire stays clear of adjacent S/D M1 pad while landing inside G0 M1
    c.wire("metal1", [(grid(tgx - 0.14), grid(tail_y + tgy)), (bias_x, grid(tail_y + tgy))], 0.22)
    c.via1(bias_x, grid(tail_y + tgy))
    c.wire("metal2", [(bias_x, grid(tail_y + tgy)), (bias_x, ground_y + 1.0)], 0.32)
    tail_bus_y = grid(clk_y + clk.bbox()[1] - 0.9)
    c.via2(0.0, td_y)
    c.via2(0.0, tail_bus_y)
    c.wire("metal3", [(0.0, td_y), (0.0, tail_bus_y)], 0.5)

    # Place body contact laterally offset from col center dx so vertical qp/qn M3 trunks remain clear
    def tie_body_outer(prim: Cell, dx: float, dy: float, mirror_x: bool) -> None:
        sign = -1 if mirror_x else 1
        bx = grid(dx + (-0.9 if dx < 0 else +0.9) + sign * prim.pins("B")[0][0])
        by = grid(dy + prim.pins("B")[0][1])
        c.body_contact(bx, by)
        trunk_x = -side_x if dx < 0 else +side_x
        c.via2(bx, by)
        c.via2(trunk_x, by)
        c.wire("metal3", [(bx, by), (trunk_x, by)], 0.4)

    # Clock steer pair (Xct left, Xch right)
    clk_gate_pts = {}
    clk_drain_pts = {}
    clk_src_pts = []
    for dx, name, mir in [(cols[0], "clk_track", False), (cols[1], "clk_hold", True)]:
        c.include(clk, dx=dx, dy=clk_y, mirror_x=mir)
        sign = -1 if mir else 1
        d_xs, s_xs, d_y, s_y = strap_mos_diff(c, clk, dx, clk_y, mir, 6.0)
        tie_body_outer(clk, dx, clk_y, mir)
        # Source -> tail_bus_y
        sx_esc = s_xs[-1] if dx < 0 else s_xs[0]
        c.wire("metal2", [(sx_esc, s_y), (sx_esc, tail_bus_y)], 0.4)
        clk_src_pts.append(sx_esc)
        clk_drain_pts[name] = (grid(dx), d_y)
        gx = grid(dx + sign * clk.pins("G")[0][0])
        gy = grid(clk_y + clk.pins("G")[0][1])
        gy_esc = grid(gy + 0.65)
        px = grid(dx - 2.4 if dx < 0 else dx + 2.4)
        c.wire("metal1", [(gx, grid(gy + 0.06)), (gx, gy_esc), (px, gy_esc)], 0.20)
        c.via1(px, gy_esc)
        clk_gate_pts[name] = (px, gy_esc)
    c.wire("metal2", [(clk_src_pts[0], tail_bus_y), (clk_src_pts[1], tail_bus_y)], 0.5)

    # Channels between Clk <-> Hold and Hold <-> Data
    hold_bus_y = grid(hold_y + hold.bbox()[1] - 0.9)
    track_bus_y = grid(data_y + data.bbox()[1] - 0.9)
    qp_xc_y = grid(hold_y + hold.bbox()[3] + 1.3)
    qn_xc_y = grid(hold_y + hold.bbox()[3] + 2.3)

    # Hold regen pair (Xhp left -> drain qn, Xhn right -> drain qp)
    hold_src_pts = []
    hold_gate_pts = {}
    for dx, side, mir in [(cols[0], "L", False), (cols[1], "R", True)]:
        c.include(hold, dx=dx, dy=hold_y, mirror_x=mir)
        sign = -1 if mir else 1
        d_xs, s_xs, d_y, s_y = strap_mos_diff(c, hold, dx, hold_y, mir, 5.0)
        tie_body_outer(hold, dx, hold_y, mir)
        sx_esc = s_xs[-1] if dx < 0 else s_xs[0]
        c.wire("metal2", [(sx_esc, s_y), (sx_esc, hold_bus_y)], 0.4)
        hold_src_pts.append(sx_esc)
        # Drain joins main vertical M3 trunk at x=dx (qn on left, qp on right)
        c.via2(dx, d_y)
        # Use inner gate pin and escape +0.65um above diffusion before dropping via1
        g_local = hold.pins("G")[-1] if side == "L" else hold.pins("G")[0]
        gx = grid(dx + sign * g_local[0])
        gy = grid(hold_y + g_local[1])
        gy_esc = grid(gy + 0.65)
        ix = grid(dx + 2.6 if side == "L" else dx - 2.6)
        c.wire("metal1", [(gx, grid(gy + 0.06)), (gx, gy_esc), (ix, gy_esc)], 0.20)
        c.via1(ix, gy_esc)
        hold_gate_pts[side] = (ix, gy_esc)
    c.wire("metal2", [(hold_src_pts[0], hold_bus_y), (hold_src_pts[1], hold_bus_y)], 0.44)

    # Connect hold_bus (Xhp/Xhn sources) down to Xch drain (cols[1], right) via M3 at x = +0.6
    x_hold_drop = grid(0.6)
    c.via2(x_hold_drop, hold_bus_y)
    c.via2(clk_drain_pts["clk_hold"][0], clk_drain_pts["clk_hold"][1])
    c.wire("metal3", [
        (x_hold_drop, hold_bus_y),
        (x_hold_drop, clk_drain_pts["clk_hold"][1]),
        clk_drain_pts["clk_hold"],
    ], 0.4)

    # Track data pair (Xdp left -> drain qn, Xdn right -> drain qp)
    data_src_pts = []
    data_gate_pts = {}
    data_d_y = None
    hold_d_y = grid(hold_y + grid(5.0 / 2.0 - 0.5))
    for dx, nm, mir in [(cols[0], "dp", False), (cols[1], "dn", True)]:
        c.include(data, dx=dx, dy=data_y, mirror_x=mir)
        sign = -1 if mir else 1
        d_xs, s_xs, d_y, s_y = strap_mos_diff(c, data, dx, data_y, mir, 5.0)
        data_d_y = d_y
        tie_body_outer(data, dx, data_y, mir)
        sx_esc = s_xs[-1] if dx < 0 else s_xs[0]
        c.wire("metal2", [(sx_esc, s_y), (sx_esc, track_bus_y)], 0.4)
        data_src_pts.append(sx_esc)
        c.via2(dx, d_y)
        gx = grid(dx + sign * data.pins("G")[0][0])
        gy = grid(data_y + data.pins("G")[0][1])
        gy_esc = grid(gy + 0.65)
        px = grid(dx - 2.4 if dx < 0 else dx + 2.4)
        c.wire("metal1", [(gx, grid(gy + 0.06)), (gx, gy_esc), (px, gy_esc)], 0.20)
        c.via1(px, gy_esc)
        data_gate_pts[nm] = (px, gy_esc)
    c.wire("metal2", [(data_src_pts[0], track_bus_y), (data_src_pts[1], track_bus_y)], 0.44)

    # Connect track_bus (Xdp/Xdn sources) down to Xct drain (cols[0], left) via M3 at x = -0.6
    # (Crosses hold_bus_y on M3 cleanly without touching M2!)
    x_track_drop = grid(-0.6)
    c.via2(x_track_drop, track_bus_y)
    c.via2(clk_drain_pts["clk_track"][0], clk_drain_pts["clk_track"][1])
    c.wire("metal3", [
        (x_track_drop, track_bus_y),
        (x_track_drop, clk_drain_pts["clk_track"][1]),
        clk_drain_pts["clk_track"],
    ], 0.4)

    # Cross-couple hold gates on M4 (clear of M3 vertical drops/trunks):
    # Left hold gate (L) connects to qp (cols[1]); right hold gate (R) connects to qn (cols[0])
    for target_col, gate_pt, yc in [
        (cols[1], hold_gate_pts["L"], qp_xc_y),
        (cols[0], hold_gate_pts["R"], qn_xc_y),
    ]:
        gx, gy = gate_pt
        c.via2(gx, gy)
        c.wire("metal3", [(gx, gy), (gx, yc)], 0.4)
        via3(c, gx, yc)
        via3(c, target_col, yc)
        c.wire("metal4", [(min(gx, target_col), yc), (max(gx, target_col), yc)], 0.44)

    # Load resistors: Rn (left, qn) and Rp (right, qp)
    for dx in cols:
        c.include(load, dx=dx, dy=load_y)
        r2_y = grid(load_y + load.pins("R2")[0][1])
        c.via1(dx, r2_y)
        c.via2(dx, r2_y)
        r1_y = grid(load_y + load.pins("R1")[0][1])
        c.via1(dx, r1_y)
        c.wire("metal2", [(dx, r1_y), (dx, vdd_y)], 0.6)
        rbx = grid(dx + 1.2 * (-1 if dx < 0 else 1) + load.pins("B")[0][0])
        rby = grid(load_y + load.pins("B")[0][1])
        c.body_contact(rbx, rby)
        c.wire("metal2", [(rbx, rby), (rbx, body_rail_y)], 0.4)
        # Main vertical M3 trunk from hold drain -> data drain -> resistor R2
        c.wire("metal3", [(dx, hold_d_y), (dx, r2_y)], 0.48)

    # Export all 9 required ports
    c.port("dp", "metal2", *data_gate_pts["dp"])
    c.port("dn", "metal2", *data_gate_pts["dn"])
    c.port("qp", "metal3", cols[1], data_d_y)
    c.port("qn", "metal3", cols[0], data_d_y)
    c.port("clk_track", "metal2", *clk_gate_pts["clk_track"])
    c.port("clk_hold", "metal2", *clk_gate_pts["clk_hold"])
    c.port("vbias", "metal2", bias_x, ground_y + 1.0)
    c.port("vdd", "metal2", 0.0, vdd_y)
    c.port("vss", "metal2", 0.0, ground_y)
    c.write(cw / f"{cell}.mag")

    ref = (
        "* Physical PDK variant of analog/pll/divider/spice/cml_latch.spice\n"
        + f".subckt {cell} dp dn qp qn clk_track clk_hold vbias vdd vss\n"
        + "Xrp vdd qp vss sky130_fd_pr__res_high_po_2p85 l=4.14\n"
        + "Xrn vdd qn vss sky130_fd_pr__res_high_po_2p85 l=4.14\n"
        + "Xdp qn dp track vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15\n"
        + "Xdn qp dn track vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15\n"
        + "Xhp qn qp hold vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15\n"
        + "Xhn qp qn hold vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15\n"
        + "Xct track clk_track tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15\n"
        + "Xch hold clk_hold tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15\n"
        + "Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5\n"
        + f".ends {cell}\n"
    )
    ref_path = cw / "reference.spice"
    ref_path.write_text(ref)
    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(cw.resolve()), cell, "--ref", str(ref_path.resolve())],
        capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (cw / "check.log").write_text(log)
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (cw / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(cw / f"{cell}.mag").bbox()
    res = {
        "cell": cell,
        "checker_exit": proc.returncode,
        "drc_boxes": int(drc_m[1]) if drc_m else None,
        "lvs_match": "LVS_MATCH True" in log,
        "lvs_property_errors": "LVS_PROPERTY_ERRORS True" in log,
        "exported_ports": ports_m[1].split() if ports_m else [],
        "bbox_um": [bx1, by1, bx2, by2],
        "size_um": [round(bx2 - bx1, 3), round(by2 - by1, 3)],
        "area_um2": round((bx2 - bx1) * (by2 - by1), 2),
        "extracted_models": models,
    }
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    res = build_cml_latch(out)
    (out / "summary.json").write_text(json.dumps([res], indent=2) + "\n")
    print(f"{res['cell']} | DRC={res['drc_boxes']} | LVS={res['lvs_match']} | "
          f"ports={len(res['exported_ports'])} | size={res['size_um']} um")


if __name__ == "__main__":
    main()
