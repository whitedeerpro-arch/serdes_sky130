#!/usr/bin/env python3
"""Hierarchical SKY130A PDK Chip-Level Top Assembly (`serdes_4g_top_pdk`).

Assembles the real full-chip Magic layout (`.mag`) and GDSII (`.gds`) for the
SKY130A 1.8 V 4 Gb/s NRZ SerDes (`845.4 x 601.4 um` core + perimeter power/pad ring):

  1. All 20 signed-off full-custom analog/PLL/TX/RX/LDO/BIAS `.mag` macros
     placed at exact verified coordinates & orientations from `plan_chip_floorplan.py`.
  2. Real signed-off digital macro `serdes_digital_top_v3` imported read-only from
     `digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.gds`.
  3. Real DRC-clean SKY130A damped MIM1+MIM2 decap tile (`serdes_decap_damped_unit_pdk.mag`)
     arrayed across all 12 PDN decap pockets (`10x10 um` stacked MIM1+MIM2 + under-MIM
     `res_high_po_2p85` series damping resistor).
  4. Full-height P+ substrate isolation guard moat (`MOAT_QUIET_MAIN`) and
     TX-RX shield moat (`MOAT_TX_RX`).
  5. Domain-separated M5/M4 power rings & straps (`vdd_hv33`, `vdd_q`, `vdd_bias`,
     `vdd_a`, `vdd_tx`, `vdd_rx`, `vdd_d`, unified `vss` perimeter shield ring).
  6. Top-level inter-macro signal routing (Stage 2: PLL core W->E chain, matched
     2 GHz 8-phase clock spine across the moat, TX 1 GHz clock, PLL 250 MHz feedback,
     Digital South-Edge <-> Analog buses, South GSSG high-speed TX/RX pad exits).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "analog/tx/sst/layout"))

import magicutil as mu  # noqa: E402
import plan_chip_floorplan as pcf  # noqa: E402
import sst_layout_common as slc  # noqa: E402
from sst_layout_common import Cell, PdkCache, grid, place_stacked_mim, via2_clean, via34_pillar, via3_pad  # noqa: E402

SCALE = 200  # 1 um = 200 Magic units (magscale 1 2 -> 5 nm grid)


def u(um: float) -> int:
    return int(round(um * SCALE))


def magic_transform(
    bbox_orig: tuple[float, float, float, float],
    mx: float,
    my: float,
    orient: str,
) -> tuple[int, int, int, int, int, int]:
    """Exact integer Magic transform (a b c d e f) matching plan_chip_floorplan.transform_point."""
    x0, y0, x1, y1 = bbox_orig
    if orient == "R0":
        return (1, 0, u(mx - x0), 0, 1, u(my - y0))
    if orient == "MX":
        return (-1, 0, u(mx + x1), 0, 1, u(my - y0))
    if orient == "MY":
        return (1, 0, u(mx - x0), 0, -1, u(my + y1))
    if orient == "R180":
        return (-1, 0, u(mx + x1), 0, -1, u(my + y1))
    if orient == "R90":
        return (0, -1, u(mx + y1), 1, 0, u(my - x0))
    if orient == "R270":
        return (0, 1, u(mx - y0), -1, 0, u(my + x1))
    if orient == "R270_MX":
        return (0, -1, u(mx + y1), -1, 0, u(my + x1))
    if orient == "R90_MX":
        return (0, 1, u(mx - y0), 1, 0, u(my - x0))
    raise ValueError(f"Unsupported orient: {orient}")


def build_damped_decap_unit(work: Path, cache: PdkCache) -> dict:
    """Build a standalone & arrayable DRC=0 damped MIM1+MIM2 decap unit tile (20.0 x 19.5 um pitch).

    Real electrical topology:
      VDD (North M4 bus) ──[Stacked 8x8 um MIM1+MIM2 (~0.27 pF)]──[Under-MIM res_high_po_2p85 (~600 Ohm)]── VSS (South M2 bus)
    """
    cell_name = "serdes_decap_damped_unit_pdk"
    c = Cell()

    mim = place_stacked_mim(
        c, cache, side=8.0, cols=1, rows=1,
        dx_c=7.000, dy_c=7.500,
        a_off=1.50, b3_off=1.50, b5_off=2.60,
        pillar_side="east",
    )

    # Under-MIM series damping resistor sky130_fd_pr__res_high_po_2p85 (l=3.0 -> ~600 Ohm) at (6.0, 7.5)
    r_dev = cache.device("sky130_fd_pr__res_high_po_2p85", dict(l=3.0, m=1, guard=0))
    c.include(r_dev, dx=6.000, dy=7.500)

    # South VSS bus on M2 at y = -1.20 + P+ substrate tap strip
    y_vss = -1.200
    c.rect("metal2", -1.000, grid(y_vss - 0.450), 17.000, grid(y_vss + 0.450))
    c.rect("psubdiff", 0.500, grid(y_vss - 0.250), 15.000, grid(y_vss + 0.250))
    c.rect("locali", 0.550, grid(y_vss - 0.200), 14.950, grid(y_vss + 0.200))
    for xt in (2.0, 6.0, 10.0, 14.0):
        c.pad("psubdiffcont", xt, y_vss, 0.17)
        c.pad("viali", xt, y_vss, 0.17)
        c.pad("metal1", xt, y_vss, 0.36)
        c.via1(xt, y_vss)

    # R2 (6.0, 5.0) -> VSS bus
    c.via1(6.000, 5.000)
    c.wire("metal2", [(6.000, 5.000), (6.000, y_vss)], 0.500)

    # R1 (6.0, 10.0) -> mim["b"] (M3/M5 outer-plate pillar point!)
    bx, by = mim["b"]
    c.via1(6.000, 10.000)
    c.wire("metal2", [(6.000, 10.000), (bx, 10.000), (bx, by)], 0.500)
    via2_clean(c, bx, by)

    # North VDD bus on M4 at y = 15.40
    y_vdd = 15.400
    c.rect("metal4", -1.000, grid(y_vdd - 0.450), 17.000, grid(y_vdd + 0.450))
    ax, ay = mim["a"]
    c.wire("metal4", [(ax, ay), (ax, y_vdd)], 0.800)

    c.port("vdd", "metal4", 7.000, y_vdd)
    c.port("vss", "metal2", 7.000, y_vss)

    mag_path = work / f"{cell_name}.mag"
    c.write(mag_path)

    # Clean arrayable pitch (21.0 x 19.5 um >= 1.9 um inter-tile gap for M5/MIM with pillar_side="east", b5_off=2.60)
    pitch_x, pitch_y = 21.0, 19.5
    drc_tcl = work / "_drc_decap.tcl"
    drc_tcl.write_text("\n".join([
        "drc off",
        f"cd {work}",
        f"load {cell_name}",
        "select top cell",
        'puts "UNIT_BOX [box values]"',
        "drc on",
        "drc style drc(full)",
        "drc check",
        "drc catchup",
        'puts "UNIT_DRC [drc list count total]"',
        'foreach {why boxes} [drc listall why] { puts "UNIT_RULE [llength $boxes] | $why" }',
        "quit -noprompt",
    ]) + "\n")
    res = mu.run_magic(drc_tcl, cwd=work)
    m_drc = re.search(r"UNIT_DRC (\d+)", res.log)
    m_box = re.search(r"UNIT_BOX (-?\d+) (-?\d+) (-?\d+) (-?\d+)", res.log)
    drc_cnt = int(m_drc.group(1)) if m_drc else -1
    box = [int(m_box.group(i)) / SCALE for i in range(1, 5)] if m_box else [-1, -1.65, 15.5, 15.65]
    print(f"[decap_unit] {cell_name}: box={box}, DRC={drc_cnt}")
    if drc_cnt != 0:
        for line in res.log.splitlines():
            if "UNIT_RULE" in line or "Error" in line:
                print("  ", line)
    return {"cell": cell_name, "mag": mag_path, "drc": drc_cnt, "box_um": box, "pitch_x": pitch_x, "pitch_y": pitch_y}


def build_hybrid_decap_unit(
    work: Path,
    cache: PdkCache,
    cell_name: str,
    mos_model: str,
    w_f: float,
    l_f: float,
    nf: int,
    mim_side: float = 9.5,
) -> dict:
    """Build a drop-in DRC=0 hybrid MIM1+MIM2 + under-MIM MOS-cap decap tile (21.0 x 19.5 um pitch).

    Verified by Magic DRC(full)=0 (unit & 2x2 array) and ngspice AC PEX:
      - serdes_decap_hybrid_1v8_pdk  (nfet_01v8,     w=10.5 l=4.0 nf=3 + 9.5x9.5 MIM1+MIM2): 1.407 pF @ 1.8V
      - serdes_decap_hybrid_hv33_pdk (nfet_g5v0d10v5,w=10.0 l=4.0 nf=3 + 9.5x9.5 MIM1+MIM2): 0.763 pF @ 3.3V
    """
    c = Cell()
    y_vss = -1.200
    y_vdd = 15.400
    is_hv = "g5v0" in mos_model

    mim = place_stacked_mim(
        c, cache, side=mim_side, cols=1, rows=1,
        dx_c=6.500, dy_c=6.800,
        a_off=1.50, b3_off=1.50, b5_off=2.60,
        pillar_side="east",
    )

    p = cache.device(mos_model, dict(w=w_f, l=l_f, nf=nf, conn_gates=0, topc=0, botc=0, guard=0))
    pb = p.bbox()
    dx_m = grid(6.800 - 0.5 * (pb[0] + pb[2]))
    dy_m = grid(5.500 - 0.5 * (pb[1] + pb[3]))
    cut_layer = "mvndiffc" if is_hv else "ndiffc"
    diff_layer = "mvndiff" if is_hv else "ndiff"
    h_clip = grid(w_f / 2.0 + 0.140)
    for layer, rects_l in p.rects.items():
        if layer in ("viali", "metal1", "pwell", "nwell", "checkpaint"):
            continue
        for x1, y1, x2, y2 in rects_l:
            if layer == "poly":
                y1 = max(y1, -h_clip)
                y2 = min(y2, h_clip)
                if y2 <= y1:
                    continue
            c.rect(layer, grid(dx_m + x1), grid(dy_m + y1), grid(dx_m + x2), grid(dy_m + y2))

    sd_xs = sorted({grid(dx_m + 0.5 * (r[0] + r[2])) for r in p.rects[cut_layer]})
    g_xs = sorted({grid(dx_m + 0.5 * (r[0] + r[2])) for r in p.rects["poly"]})
    sd_y1 = grid(dy_m + min(r[1] for r in p.rects[cut_layer]))
    sd_y2 = grid(dy_m + max(r[3] for r in p.rects[cut_layer]))
    diff_y2 = grid(dy_m + max(r[3] for r in p.rects[diff_layer]))

    for sx in sd_xs:
        c.rect("locali", grid(sx - 0.085), sd_y1, grid(sx + 0.085), sd_y2)
        c.wire("metal1", [(sx, sd_y2), (sx, y_vss)], 0.300)
        for vy in (grid(sd_y1 + 0.30), grid(0.5 * (sd_y1 + sd_y2)), grid(sd_y2 - 0.30)):
            c.pad("viali", sx, vy, 0.17)
        c.via1(sx, y_vss)

    y_g = grid(diff_y2 + 0.700)
    hw_poly = grid(l_f / 2.0)
    for gx in g_xs:
        c.rect("poly", grid(gx - hw_poly), grid(diff_y2 - 0.050), grid(gx + hw_poly), grid(y_g + 0.220))
        c.pad("polycont", gx, y_g, 0.17)
        c.rect("locali", grid(gx - 0.200), grid(y_g - 0.120), grid(gx + 0.200), grid(y_g + 0.120))
        c.pad("viali", gx, y_g, 0.17)
    c.rect("poly", grid(g_xs[0] - hw_poly), grid(y_g - 0.220), grid(g_xs[-1] + hw_poly), grid(y_g + 0.220))
    c.wire("metal1", [(g_xs[0], y_g), (g_xs[-1], y_g)], 0.360)

    x_gt = grid(g_xs[0])
    c.wire("metal1", [(x_gt, y_g), (x_gt, y_vdd)], 0.440)
    c.via1(x_gt, y_vdd)
    via2_clean(c, x_gt, y_vdd)
    via3_pad(c, x_gt, y_vdd)

    c.rect("metal2", -1.000, grid(y_vss - 0.450), 17.000, grid(y_vss + 0.450))
    c.rect("psubdiff", 0.000, grid(y_vss - 0.250), 15.500, grid(y_vss + 0.250))
    c.rect("locali", 0.050, grid(y_vss - 0.200), 15.450, grid(y_vss + 0.200))
    for xt in sd_xs:
        c.pad("psubdiffcont", xt, y_vss, 0.17)
        c.pad("viali", xt, y_vss, 0.17)
        c.pad("metal1", xt, y_vss, 0.36)

    bx, by = mim["b"]
    via2_clean(c, bx, by)
    c.wire("metal2", [(bx, by), (bx, y_vss)], 0.500)

    c.rect("metal4", -1.000, grid(y_vdd - 0.450), 16.200, grid(y_vdd + 0.450))
    ax, ay = mim["a"]
    c.wire("metal4", [(ax, ay), (ax, y_vdd)], 0.800)

    c.port("vdd", "metal4", 7.000, y_vdd)
    c.port("vss", "metal2", 7.000, y_vss)

    mag_path = work / f"{cell_name}.mag"
    c.write(mag_path)
    pitch_x, pitch_y = 21.0, 19.5
    drc_tcl = work / f"_drc_{cell_name}.tcl"
    drc_tcl.write_text("\n".join([
        "drc off", f"cd {work}", f"load {cell_name}", "select top cell",
        'puts "UNIT_BOX [box values]"', "drc on", "drc style drc(full)",
        "drc check", "drc catchup", 'puts "UNIT_DRC [drc list count total]"',
        'foreach {why boxes} [drc listall why] { puts "UNIT_RULE [llength $boxes] | $why" }',
        "quit -noprompt",
    ]) + "\n")
    res = mu.run_magic(drc_tcl, cwd=work)
    m_drc = re.search(r"UNIT_DRC (\d+)", res.log)
    m_box = re.search(r"UNIT_BOX (-?\d+) (-?\d+) (-?\d+) (-?\d+)", res.log)
    drc_cnt = int(m_drc.group(1)) if m_drc else -1
    box = [int(m_box.group(i)) / SCALE for i in range(1, 5)] if m_box else [-2.03, -1.65, 18.63, 15.85]
    print(f"[decap_unit] {cell_name}: box={box}, DRC={drc_cnt}")
    return {"cell": cell_name, "mag": mag_path, "drc": drc_cnt, "box_um": box, "pitch_x": pitch_x, "pitch_y": pitch_y}


def prepare_digital_proxy(work: Path, gds_rel: str = "digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.gds") -> Path:
    """Import signed-off serdes_digital_top_v3.gds into work/ via fast read-only Magic proxy."""
    out_mag = work / "serdes_digital_top_v3.mag"
    gds = REPO / gds_rel
    assert gds.exists(), f"Missing digital GDS: {gds}"
    tcl = work / "_import_digital.tcl"
    tcl.write_text("\n".join([
        "drc off",
        f"cd {work}",
        "gds readonly true",
        "gds rescale false",
        f"gds read {gds}",
        "load serdes_digital_top_v3",
        "save serdes_digital_top_v3",
        "quit -noprompt",
    ]) + "\n")
    t0 = time.time()
    res = mu.run_magic(tcl, cwd=work)
    res.need("import serdes_digital_top_v3.gds")
    print(f"[digital_proxy] Imported {gds.relative_to(REPO)} -> {out_mag.name} in {time.time()-t0:.2f}s")
    return out_mag


def copy_subcell_mags(work: Path, inv: dict) -> dict[str, Path]:
    """Copy all 20 unique analog macro .mag files into work/ so Magic resolves every `use` cleanly."""
    copied: dict[str, Path] = {}
    for key, raw in inv.items():
        if key == "digital_top_v3":
            continue
        src = REPO / raw.source_path
        assert src.exists(), f"Missing macro .mag: {src}"
        dst = work / f"{raw.cell_name}.mag"
        if not dst.exists():
            shutil.copy2(src, dst)
        copied[raw.cell_name] = dst
    print(f"[macros] Staged {len(copied)} unique analog .mag macros into {work.relative_to(REPO)}")
    return copied


def paint_guard_moat_rects(rects: dict[str, list[tuple[int, int, int, int]]], x1: float, y1: float, x2: float, y2: float) -> None:
    """Add a clean DRC=0 P+ substrate guard bar (psubdiff + locali + psubdiffcont + M1 + M2 VSS shield)."""
    cx = grid(0.5 * (x1 + x2))
    # Continuous P+ tap column (width 1.6 um) + M1/M2 shield bar
    rects.setdefault("psubdiff", []).append((u(cx - 0.80), u(y1), u(cx + 0.80), u(y2)))
    rects.setdefault("locali", []).append((u(cx - 0.60), u(y1 + 0.10), u(cx + 0.60), u(y2 - 0.10)))
    rects.setdefault("metal1", []).append((u(cx - 0.60), u(y1 + 0.10), u(cx + 0.60), u(y2 - 0.10)))
    rects.setdefault("metal2", []).append((u(cx - 0.80), u(y1 + 0.10), u(cx + 0.80), u(y2 - 0.10)))
    yc = grid(y1 + 1.0)
    while yc <= y2 - 1.0 + 1e-6:
        for xo in (-0.30, 0.30):
            rects.setdefault("psubdiffcont", []).append((u(cx + xo - 0.085), u(yc - 0.085), u(cx + xo + 0.085), u(yc + 0.085)))
            rects.setdefault("viali", []).append((u(cx + xo - 0.085), u(yc - 0.085), u(cx + xo + 0.085), u(yc + 0.085)))
            # Magic via1 layer is full cut+surround box = 0.26 x 0.26 um (+-0.13)
            rects.setdefault("via1", []).append((u(cx + xo - 0.130), u(yc - 0.130), u(cx + xo + 0.130), u(yc + 0.130)))
        yc = grid(yc + 2.0)


def add_wire_rect(rects: dict[str, list[tuple[int, int, int, int]]], layer: str, pts: list[tuple[float, float]], width: float) -> None:
    hw = 0.5 * width
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        if abs(x1 - x2) < 1e-6:
            rects.setdefault(layer, []).append((u(x1 - hw), u(min(y1, y2) - hw), u(x1 + hw), u(max(y1, y2) + hw)))
        elif abs(y1 - y2) < 1e-6:
            rects.setdefault(layer, []).append((u(min(x1, x2) - hw), u(y1 - hw), u(max(x1, x2) + hw), u(y1 + hw)))
        else:
            # Manhattan L-jog (horizontal then vertical)
            xm, ym = x2, y1
            rects.setdefault(layer, []).append((u(min(x1, xm) - hw), u(y1 - hw), u(max(x1, xm) + hw), u(y1 + hw)))
            rects.setdefault(layer, []).append((u(xm - hw), u(min(ym, y2) - hw), u(xm + hw), u(max(ym, y2) + hw)))


def add_via_12(rects: dict[str, list[tuple[int, int, int, int]]], x: float, y: float) -> None:
    """DRC-safe M1<->M2 via1 pad (Magic via1 box = 0.26x0.26, M1/M2 pad = 0.36x0.36)."""
    rects.setdefault("metal1", []).append((u(x - 0.18), u(y - 0.18), u(x + 0.18), u(y + 0.18)))
    rects.setdefault("via1", []).append((u(x - 0.13), u(y - 0.13), u(x + 0.13), u(y + 0.13)))
    rects.setdefault("metal2", []).append((u(x - 0.18), u(y - 0.18), u(x + 0.18), u(y + 0.18)))


def add_via_23(rects: dict[str, list[tuple[int, int, int, int]]], x: float, y: float) -> None:
    """DRC-safe M2<->M3 via2 pad (Magic via2 box = 0.28x0.28, M2 pad = 0.42x0.42, M3 pad = 0.52x0.52)."""
    rects.setdefault("metal2", []).append((u(x - 0.21), u(y - 0.21), u(x + 0.21), u(y + 0.21)))
    rects.setdefault("via2", []).append((u(x - 0.14), u(y - 0.14), u(x + 0.14), u(y + 0.14)))
    rects.setdefault("metal3", []).append((u(x - 0.26), u(y - 0.26), u(x + 0.26), u(y + 0.26)))


def add_via_34(rects: dict[str, list[tuple[int, int, int, int]]], x: float, y: float) -> None:
    """DRC-safe M3<->M4 via3 pad (Magic via3 box = 0.32x0.32, M3/M4 pad = 0.52x0.52)."""
    rects.setdefault("metal3", []).append((u(x - 0.26), u(y - 0.26), u(x + 0.26), u(y + 0.26)))
    rects.setdefault("via3", []).append((u(x - 0.16), u(y - 0.16), u(x + 0.16), u(y + 0.16)))
    rects.setdefault("metal4", []).append((u(x - 0.26), u(y - 0.26), u(x + 0.26), u(y + 0.26)))


def add_via_45(rects: dict[str, list[tuple[int, int, int, int]]], x: float, y: float) -> None:
    """DRC-safe M4<->M5 via4 pad (Magic via4 box = 1.18x1.18, M4 pad = 1.60, M5 pad = 2.00)."""
    rects.setdefault("metal4", []).append((u(x - 0.80), u(y - 0.80), u(x + 0.80), u(y + 0.80)))
    rects.setdefault("via4", []).append((u(x - 0.59), u(y - 0.59), u(x + 0.59), u(y + 0.59)))
    rects.setdefault("metal5", []).append((u(x - 1.00), u(y - 1.00), u(x + 1.00), u(y + 1.00)))


def add_via_45_array(
    rects: dict[str, list[tuple[int, int, int, int]]],
    cx: float,
    cy: float,
    nx: int,
    ny: int,
    pitch: float = 1.80,
) -> None:
    """DRC-safe nx x ny via4 array (1.18 um cut, 1.80 um pitch -> 0.62 um spacing >= 0.42 um min)."""
    x0 = cx - 0.5 * (nx - 1) * pitch
    y0 = cy - 0.5 * (ny - 1) * pitch
    w_m4 = (nx - 1) * pitch + 1.60
    h_m4 = (ny - 1) * pitch + 1.60
    w_m5 = (nx - 1) * pitch + 2.00
    h_m5 = (ny - 1) * pitch + 2.00
    rects.setdefault("metal4", []).append((u(cx - 0.5 * w_m4), u(cy - 0.5 * h_m4), u(cx + 0.5 * w_m4), u(cy + 0.5 * h_m4)))
    rects.setdefault("metal5", []).append((u(cx - 0.5 * w_m5), u(cy - 0.5 * h_m5), u(cx + 0.5 * w_m5), u(cy + 0.5 * h_m5)))
    for ix in range(nx):
        for iy in range(ny):
            vx = grid(x0 + ix * pitch)
            vy = grid(y0 + iy * pitch)
            rects.setdefault("via4", []).append((u(vx - 0.59), u(vy - 0.59), u(vx + 0.59), u(vy + 0.59)))


def add_via_234_array(
    rects: dict[str, list[tuple[int, int, int, int]]],
    cx: float,
    cy: float,
    nx: int,
    ny: int,
    pitch: float = 0.80,
) -> None:
    """DRC-safe stacked M2->M3->M4 multi-via array (reduces decap-tie ESR by 4-6x)."""
    x0 = cx - 0.5 * (nx - 1) * pitch
    y0 = cy - 0.5 * (ny - 1) * pitch
    w_m2 = (nx - 1) * pitch + 0.52
    h_m2 = (ny - 1) * pitch + 0.52
    w_m34 = (nx - 1) * pitch + 0.60
    h_m34 = (ny - 1) * pitch + 0.60
    rects.setdefault("metal2", []).append((u(cx - 0.5 * w_m2), u(cy - 0.5 * h_m2), u(cx + 0.5 * w_m2), u(cy + 0.5 * h_m2)))
    rects.setdefault("metal3", []).append((u(cx - 0.5 * w_m34), u(cy - 0.5 * h_m34), u(cx + 0.5 * w_m34), u(cy + 0.5 * h_m34)))
    rects.setdefault("metal4", []).append((u(cx - 0.5 * w_m34), u(cy - 0.5 * h_m34), u(cx + 0.5 * w_m34), u(cy + 0.5 * h_m34)))
    for ix in range(nx):
        for iy in range(ny):
            vx = grid(x0 + ix * pitch)
            vy = grid(y0 + iy * pitch)
            rects.setdefault("via2", []).append((u(vx - 0.14), u(vy - 0.14), u(vx + 0.14), u(vy + 0.14)))
            rects.setdefault("via3", []).append((u(vx - 0.16), u(vy - 0.16), u(vx + 0.16), u(vy + 0.16)))


def audit_top_connectivity(
    rects: dict[str, list[tuple[int, int, int, int]]],
    macros: list,
    decap_placements: list[dict],
) -> dict:
    """Union-find connectivity & short audit across all top-level metal2..metal5 + via2..via4 rects."""
    from collections import defaultdict

    layers = ("metal1", "metal2", "metal3", "metal4", "metal5")
    nodes: list[tuple[str, float, float, float, float]] = []
    by_lyr: dict[str, list[tuple[int, float, float, float, float]]] = defaultdict(list)
    for lyr in layers:
        for x1i, y1i, x2i, y2i in rects.get(lyr, ()):
            if x2i <= x1i or y2i <= y1i:
                continue
            r = (x1i / SCALE, y1i / SCALE, x2i / SCALE, y2i / SCALE)
            idx = len(nodes)
            nodes.append((lyr, *r))
            by_lyr[lyr].append((idx, *r))

    parent = list(range(len(nodes)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    def overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float], tol: float = 1e-6) -> bool:
        return not (a[2] < b[0] - tol or b[2] < a[0] - tol or a[3] < b[1] - tol or b[3] < a[1] - tol)

    for lyr in layers:
        arr = by_lyr[lyr]
        for i in range(len(arr)):
            ii, x1, y1, x2, y2 = arr[i]
            for j in range(i + 1, len(arr)):
                jj, X1, Y1, X2, Y2 = arr[j]
                if not (x2 < X1 - 1e-6 or X2 < x1 - 1e-6 or y2 < Y1 - 1e-6 or Y2 < y1 - 1e-6):
                    union(ii, jj)

    for vlyr, l1, l2 in (("via1", "metal1", "metal2"), ("via2", "metal2", "metal3"), ("via3", "metal3", "metal4"), ("via4", "metal4", "metal5")):
        for x1i, y1i, x2i, y2i in rects.get(vlyr, ()):
            vr = (x1i / SCALE, y1i / SCALE, x2i / SCALE, y2i / SCALE)
            h1 = [ii for ii, x1, y1, x2, y2 in by_lyr[l1] if overlaps((x1, y1, x2, y2), vr)]
            h2 = [ii for ii, x1, y1, x2, y2 in by_lyr[l2] if overlaps((x1, y1, x2, y2), vr)]
            if h1 and h2:
                for a in h1[1:]:
                    union(h1[0], a)
                for b in h2:
                    union(h1[0], b)

    by = {m.inst: m for m in macros}
    expected = [
        ("pfd_up", [("pfd_sc_dly", "up", "metal3"), ("cp_v4", "up", "metal3")]),
        ("pfd_dn", [("pfd_sc_dly", "dn", "metal3"), ("cp_v4", "dn", "metal3")]),
        ("vctrl", [("cp_v4", "out", "metal3"), ("lf_k4_fused", "ctrl", "metal3"), ("vco_r6_sym9", "ctrl", "metal4")]),
        ("fb250", [("div8_saff", "q8p", "metal4"), ("pfd_sc_dly", "fb", "metal2")]),
        ("vbg", [("bias_top_v2", "vbg", "metal3"), ("ldo_v2_cur", "bg", "metal2")]
                + ([("tx_sst_top", "vbg", "metal2")] if by["bias_top_v2"].raw.cell_name == "serdes_bias_top_v2_ptat_pdk" else [])),
        ("i_ldo0", [("bias_top_v2", "i_ldo0", "metal2"), ("ldo_v2_cur", "i_ldo", "metal2")]),
        ("i_ldo1", [("bias_top_v2", "i_ldo1", "metal2"), ("cp_v4", "ibias", "metal3")]),
        ("tx_clk", [("digital_top_v3", "tx_word_clk", "metal2"), ("tx_sst_top", "clk250_out", "metal4")]),
        ("rx_wclk", [("digital_top_v3", "rx_word_clk", "metal2"), ("rx_cmos_top", "wclk", "metal4")]),
    ]
    if by["bias_top_v2"].raw.cell_name == "serdes_bias_top_v2_ptat_pdk":
        expected.extend([
            ("ptat_vgi", [("bias_top_v2", "vgi", "metal3"), ("vco_ptat_bias", "vgi", "metal2")]),
            ("ptat_vg", [("bias_top_v2", "vg", "metal3"), ("vco_ptat_bias", "vg", "metal2")]),
            ("vco_ptat_out", [("vco_ptat_bias", "out", "metal4"), ("bias_cml_vco", "iin", "metal4"), ("bias_lpf_slow", "original", "metal1")]),
            ("vco_vbias_q", [("bias_lpf_slow", "filtered", "metal4"), ("vco_r6_sym9", "vbias_q", "metal4")]),
            ("lf_pref", [("bias_top_v2", "pref", "metal3"), ("lf_k4_fused", "pre_ref", "metal3")]),
            ("cp_vbn", [("bias_top_v2", "icp", "metal2"), ("bias_cp_v2", "vbn", "metal2"), ("cp_v4", "vbn", "metal3")]),
            ("cp_vbp", [("bias_cp_v2", "vbp", "metal3"), ("cp_v4", "vbp", "metal3")]),
            ("host_cml_bias", [("bias_top_v2", "icml", "metal2"), ("bias_cml_host", "iin", "metal4")]
                              + [(f"cml2cmos_{k}", "vbias", "metal3") for k in range(4)]),
            ("rx_ictle", [("bias_top_v2", "ictle", "metal2"), ("rx_cmos_top", "ibias_ctle", "metal4")]),
            ("rx_vcm", [("bias_top_v2", "vcm", "metal3"), ("rx_cmos_top", "vcm_ref", "metal4")]),
        ])
    for vp, c_inst, cp in (
        ("b0n", "cml2cmos_2", "inn"), ("b0p", "cml2cmos_2", "inp"),
        ("b1p", "cml2cmos_3", "inn"), ("b1n", "cml2cmos_3", "inp"),
        ("b2n", "cml2cmos_0", "inn"), ("b2p", "cml2cmos_0", "inp"),
        ("b3p", "cml2cmos_1", "inn"), ("b3n", "cml2cmos_1", "inp"),
    ):
        expected.append((f"vco_{vp}", [("vco_r6_sym9", vp, "metal2"), (c_inst, cp, "metal3")]))
    for name, ci, cp, dsts in (
        ("c0", "cml2cmos_2", "outp", [("rx_cmos_top", "c0", "metal3"), ("tx_qdiv2", "dp", "metal3")]),
        ("c1", "cml2cmos_3", "outp", [("rx_cmos_top", "c1", "metal3"), ("div8_saff", "clkp", "metal4")]),
        ("c2", "cml2cmos_0", "outp", [("rx_cmos_top", "c2", "metal3"), ("tx_qdiv2", "ep", "metal3")]),
        ("c3", "cml2cmos_1", "outp", [("rx_cmos_top", "c3", "metal3")]),
        ("c4", "cml2cmos_2", "outn", [("rx_cmos_top", "c4", "metal3"), ("tx_qdiv2", "dn", "metal3")]),
        ("c5", "cml2cmos_3", "outn", [("rx_cmos_top", "c5", "metal3"), ("div8_saff", "clkn", "metal4")]),
        ("c6", "cml2cmos_0", "outn", [("rx_cmos_top", "c6", "metal3"), ("tx_qdiv2", "en", "metal3")]),
        ("c7", "cml2cmos_1", "outn", [("rx_cmos_top", "c7", "metal3")]),
    ):
        expected.append((f"clk_{name}", [(ci, cp, "metal3")] + dsts))
    for qp, tp in (("ckd0", "phi0"), ("ckd1", "phi90"), ("ckd2", "phi180"), ("ckd3", "phi270")):
        expected.append((f"txq_{qp}", [("tx_qdiv2", qp, "metal4"), ("tx_sst_top", tp, "metal3")]))
    for i in range(16):
        expected.append((f"tx_d{i}", [("digital_top_v3", f"tx_capture_data[{i}]", "metal2"), ("tx_sst_top", f"din{i}", "metal4")]))
        expected.append((f"rx_wd{i}", [("digital_top_v3", f"rx_phys[{i}]", "metal2"), ("rx_cmos_top", f"wd{i}", "metal4")]))
        expected.append((f"rx_we{i}", [("digital_top_v3", f"rx_phys[{16 + i}]", "metal2"), ("rx_cmos_top", f"we{i}", "metal4")]))
    for pref, rp in (("rx_select_a", "a"), ("rx_select_b", "b"), ("rx_fine_b", "f")):
        for i in range(8):
            expected.append((f"pi_{rp}{i}", [("digital_top_v3", f"{pref}[{i}]", "metal2"), ("rx_cmos_top", f"{rp}{i}", "metal2")]))

    def hit_pt(px: float, py: float, lyr: str, tol: float = 0.25) -> set[int]:
        return {find(ii) for ii, x1, y1, x2, y2 in by_lyr[lyr] if x1 - tol <= px <= x2 + tol and y1 - tol <= py <= y2 + tol}

    pwr_pts = {
        "VSS": ("metal5", -14.0, 300.0),
        "vdd_hv33": ("metal5", -33.0, 520.0),
        "vdd_bias": ("metal5", -33.0, 315.0),
        "vdd_q": ("metal5", -33.0, 105.0),
        "vdd_a": ("metal5", 420.0, 634.0),
        "vdd_d": ("metal5", 680.0, 634.0),
        "vdd_rx": ("metal5", 906.0, 140.0),
        "vdd_tx": ("metal5", 431.0, -34.0),
    }
    comp_to_nets: dict[int, list[str]] = defaultdict(list)
    pwr_roots: dict[str, int] = {}
    for pname, (lyr, px, py) in pwr_pts.items():
        hr = hit_pt(px, py, lyr, tol=0.1)
        if len(hr) == 1:
            r = next(iter(hr))
            pwr_roots[pname] = r
            comp_to_nets[r].append(f"PWR:{pname}")

    opens = []
    for net, pins in expected:
        roots = [(f"{inst}.{port}", hit_pt(*by[inst].port_xy(port), lyr)) for inst, port, lyr in pins]
        all_r = set().union(*(hr for _, hr in roots))
        if len(all_r) != 1 or any(not hr for _, hr in roots):
            opens.append(net)
        for r in all_r:
            comp_to_nets[r].append(net)

    for pname, (px, py) in (("TX_PAD_P", (468.5, -49.0)), ("TX_PAD_N", (477.3, -49.0)), ("RX_IN_N", (663.5, -49.0)), ("RX_IN_P", (672.3, -49.0))):
        for r in hit_pt(px, py, "metal5", tol=0.1):
            comp_to_nets[r].append(pname)

    decap_ok = 0
    for b in decap_placements:
        rvdd = hit_pt(b["x_vdd"], b["y_vdd_0"], "metal4", tol=0.1)
        rvss = hit_pt(b["x_vss"], b["y_vss_0"], "metal2", tol=0.1)
        if rvdd == {pwr_roots.get(b["domain"], -1)} and rvss == {pwr_roots.get("VSS", -2)}:
            decap_ok += 1

    shorts = [ns for ns in comp_to_nets.values() if len(ns) > 1]
    res = {
        "signal_nets_checked": len(expected),
        "opens": opens,
        "shorts": shorts,
        "power_domains_distinct": len(set(pwr_roots.values())),
        "decap_banks_connected": decap_ok,
        "decap_banks_total": len(decap_placements),
    }
    print(
        f"[top_audit] signal_nets={res['signal_nets_checked']} | opens={len(opens)} | "
        f"shorts={len(shorts)} | pwr_domains={res['power_domains_distinct']}/8 | "
        f"decap_banks_tied={decap_ok}/{res['decap_banks_total']}"
    )
    return res


def build_chip_top(
    work: Path,
    stage: str = "full",
    export_gds: bool = True,
    run_drc: bool = True,
    use_v32_digital: bool = True,
    use_stacked_lpf: bool = True,
    use_saff_v2: bool = True,
    drop_dup_bias_ctle: bool = True,
    use_v5_review_macros: bool = True,
    v8_power_decap: bool = False,
) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    inv = pcf.load_inventory()

    # Optional v3.2 / full_v5 review upgrades (all read from isolated variant dirs; v1.0 frozen dirs untouched!):
    #  1) Stacked MIM1+MIM2 bias_lpf_slow (-39.8% area: 10,340 -> 6,227 um^2, R90 at y=280 clears y=251.5 M5!)
    #  2) Digital top v3.2 (direct chronological {we[15:0], wd[15:0]} + review fixes C1/C3/C4/C5/M1/M3/M4/M5!)
    #  3) Hardened SAFF-TSPC /8 v2_cand (A4: 100.79x17.52 um, DRC=0, LVS=MATCH, 15.65 ps CPEX, 199/200 MC!)
    #  4) Drop duplicate external bias_ctle_v2 (A6: rx_cmos_top_pdk already embeds Xbias_ctle internally!)
    #  5) Full_v5 isolated review-closure macros: TX SST v4p4_pdk (A1+C2), RX CMOS v2p3_pdk (A2+A5),
    #     TX QDiv2 v2p3_pdk (A2), BIAS v2_ptat_pdk (A3 North vgi/vg + A5 exact 22-port order)!
    dig_gds_rel = "digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.gds"
    if use_stacked_lpf:
        lpf_rel = "analog/ldo/layout/variants/bias_filter_stacked_pdk/serdes_pll_bias_lowpass_stacked_pdk.mag"
        if (REPO / lpf_rel).exists():
            inv["bias_lpf_slow"] = pcf.parse_mag(
                "bias_lpf_slow", lpf_rel, "serdes_pll_bias_lowpass_stacked_pdk", internal_cap_pf=16.0
            )
    if use_saff_v2:
        saff_rel = "analog/pll/divider/layout/variants/saff_reclock_2g_v2_pdk/pll_saff_reclock_prescaler8_2g_v2_cand_pdk.mag"
        if (REPO / saff_rel).exists():
            inv["div8_saff"] = pcf.parse_mag(
                "div8_saff", saff_rel, "pll_saff_reclock_prescaler8_2g_v2_cand_pdk"
            )
    if use_v5_review_macros:
        for key, rel, cname, cap_pf in (
            ("tx_sst_top", "analog/tx/sst/layout/variants/v4p4_pdk/serdes_tx_sst_top_pdk.mag", "serdes_tx_sst_top_pdk", 15.3),
            ("rx_cmos_top", "analog/rx/cmos_rx/layout/variants/v2p3_pdk/serdes_rx_cmos_top_pdk.mag", "serdes_rx_cmos_top_pdk", 3.4),
            ("tx_qdiv2", "analog/rx/cmos_rx/layout/variants/v2p3_pdk/serdes_rx_qdiv2_8ph_pdk.mag", "serdes_rx_qdiv2_8ph_pdk", 0.0),
            ("bias_top_v2", "analog/bias/layout/variants/v2_ptat_pdk/serdes_bias_top_v2_ptat_pdk.mag", "serdes_bias_top_v2_ptat_pdk", 8.0),
        ):
            if (REPO / rel).exists():
                inv[key] = pcf.parse_mag(key, rel, cname, internal_cap_pf=cap_pf)
    if use_v32_digital:
        v32_def = "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/serdes_digital_top_v3.def"
        v32_sum = "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/summary.json"
        v32_gds = "digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/serdes_digital_top_v3.gds"
        if (REPO / v32_def).exists() and (REPO / v32_gds).exists() and (REPO / v32_sum).exists():
            inv["digital_top_v3"] = pcf.parse_digital_def("digital_top_v3", v32_def, v32_sum)
            dig_gds_rel = v32_gds

    macros, decaps, guard_bays = pcf.build_floorplan(inv)
    if drop_dup_bias_ctle:
        macros = [m for m in macros if m.inst != "bias_ctle_v2"]
        inv.pop("bias_ctle_v2", None)
    # Adjust placement for upgraded macros:
    #  - Stacked bias_lpf_slow rotated R90 (105.81 x 58.85 um) placed at (194.0, 280.0) -> opens 44 um M5-free gap below!
    #  - Compacted v3.2 digital top aligned to NE corner (x=845.1-w, y=601.4-h -> opens +8.2 um taller S-edge channel!)
    #  - Full_v5 TX v4p4 (+25 um North -> y=0..257.5): shift tx_qdiv2 to y=263.0, div8_saff to y=288.5,
    #    and DECAP_CLKA_NW to y=307.5..408.5 (still 5 rows -> 208/208 decap tiles preserved, 0 M5 bridges on c0..c7!)
    for m in macros:
        if m.inst == "bias_lpf_slow" and use_stacked_lpf and m.raw.cell_name == "serdes_pll_bias_lowpass_stacked_pdk":
            m.orient = "R90"
            m.x, m.y = 194.0, 280.0
        elif m.inst == "digital_top_v3" and use_v32_digital:
            m.x = round(845.1 - m.w, 2)
            m.y = round(601.4 - m.h, 2)
        elif m.inst == "tx_qdiv2" and use_v5_review_macros:
            m.y = 263.0
        elif m.inst == "div8_saff" and use_v5_review_macros:
            m.y = 288.5
    if use_v5_review_macros:
        for d in decaps:
            if d.name == "DECAP_CLKA_NW":
                d.y = 307.5
                d.h = 101.0

    kpi = pcf.audit_and_compute_kpis(macros, decaps, guard_bays)

    # 1. Stage all 20 analog .mag macros + read-only digital proxy + damped decap unit cell
    copy_subcell_mags(work, inv)
    prepare_digital_proxy(work, gds_rel=dig_gds_rel)
    cache = PdkCache(work / "_pdk_cache")
    if v8_power_decap:
        decap_1v8 = build_hybrid_decap_unit(
            work, cache, "serdes_decap_hybrid_1v8_pdk", "sky130_fd_pr__nfet_01v8",
            w_f=10.5, l_f=4.0, nf=3, mim_side=8.0,
        )
        decap_hv33 = build_hybrid_decap_unit(
            work, cache, "serdes_decap_hybrid_hv33_pdk", "sky130_fd_pr__nfet_g5v0d10v5",
            w_f=10.0, l_f=4.0, nf=3, mim_side=8.0,
        )
        decap_info = decap_1v8
        decap_unit_drc_val = max(decap_1v8["drc"], decap_hv33["drc"])
    else:
        decap_info = build_damped_decap_unit(work, cache)
        decap_1v8 = decap_hv33 = decap_info
        decap_unit_drc_val = decap_info["drc"]

    # 2. Compose hierarchical serdes_4g_top_pdk.mag
    top_name = "serdes_4g_top_pdk"
    rects: dict[str, list[tuple[int, int, int, int]]] = {}
    uses: list[str] = []
    labels: list[tuple[str, int, int, int, int, str, int | None]] = []

    # 2a. Instantiate all 20 real signed-off macros
    for m in macros:
        tf = magic_transform(m.raw.bbox_orig_um, m.x, m.y, m.orient)
        bx0, by0, bx1, by1 = [u(v) for v in m.raw.bbox_orig_um]
        uses.append("\n".join([
            f"use {m.raw.cell_name}  {m.inst}",
            "timestamp 0",
            f"transform {tf[0]} {tf[1]} {tf[2]} {tf[3]} {tf[4]} {tf[5]}",
            f"box {bx0} {by0} {bx1} {by1}",
        ]))

    # 2b. Array real decap unit tiles inside all 12 decap pockets!
    pitch_x = decap_info["pitch_x"]
    pitch_y = decap_info["pitch_y"]
    bx0_u, by0_u, bx1_u, by1_u = decap_info["box_um"]
    uw, uh = bx1_u - bx0_u, by1_u - by0_u
    total_decap_tiles = 0
    decap_placements = []
    ux0, uy0, ux1, uy1 = [u(v) for v in decap_info["box_um"]]
    for d in decaps:
        # Leave 2.5 um margin inside each decap bay so zero interaction with adjacent macros or routing channels
        avail_w = max(0.0, d.w - 5.0)
        avail_h = max(0.0, d.h - 5.0)
        if avail_w < uw or avail_h < uh:
            continue
        nx = max(1, int((avail_w - uw) // pitch_x) + 1)
        ny = max(1, int((avail_h - uh) // pitch_y) + 1)
        arr_w = (nx - 1) * pitch_x + uw
        arr_h = (ny - 1) * pitch_y + uh
        ox = grid(d.x + 0.5 * (d.w - arr_w) - bx0_u)
        oy = grid(d.y + 0.5 * (d.h - arr_h) - by0_u)
        total_decap_tiles += nx * ny
        d_info = decap_hv33 if (v8_power_decap and d.domain == "vdd_hv33") else decap_1v8
        decap_placements.append(dict(
            name=d.name, domain=d.domain, cell=d_info["cell"], nx=nx, ny=ny, tiles=nx * ny, ox=ox, oy=oy,
            x_vdd=grid(ox - 0.55), x_vss=grid(ox + (nx - 1) * pitch_x + 16.55),
            y_vdd_0=grid(oy + 15.40), y_vdd_top=grid(oy + 15.40 + (ny - 1) * pitch_y),
            y_vss_0=grid(oy - 1.20), y_vss_top=grid(oy - 1.20 + (ny - 1) * pitch_y),
        ))
        lines = [
            f"use {d_info['cell']}  {d.name}",
            f"array 0 {nx - 1} {u(pitch_x)} 0 {ny - 1} {u(pitch_y)}",
            "timestamp 0",
            f"transform 1 0 {u(ox)} 0 1 {u(oy)}",
            f"box {ux0} {uy0} {ux1} {uy1}",
        ]
        uses.append("\n".join(lines))
        # Strap all nx x ny tiles inside this decap bank into one solid bank-wide M4 VDD bus + M2 VSS bus!
        x_lo = grid(ox - 1.00)
        x_hi = grid(ox + (nx - 1) * pitch_x + (16.20 if v8_power_decap else 17.00))
        for r in range(ny):
            yvdd = grid(oy + 15.40 + r * pitch_y)
            yvss = grid(oy - 1.20 + r * pitch_y)
            add_wire_rect(rects, "metal4", [(x_lo, yvdd), (x_hi, yvdd)], 0.90)
            add_wire_rect(rects, "metal2", [(x_lo, yvss), (x_hi, yvss)], 0.90)
        if ny > 1:
            add_wire_rect(rects, "metal4", [(grid(ox - 0.55), grid(oy + 15.40)), (grid(ox - 0.55), grid(oy + 15.40 + (ny - 1) * pitch_y))], 0.90)
            add_wire_rect(rects, "metal2", [(grid(ox + (nx - 1) * pitch_x + 16.55), grid(oy - 1.20)), (grid(ox + (nx - 1) * pitch_x + 16.55), grid(oy - 1.20 + (ny - 1) * pitch_y))], 0.90)

    # 2c. Full-height P+ substrate isolation guard moats (MOAT_QUIET_MAIN + MOAT_TX_RX rails)
    # MOAT_QUIET_MAIN: x in [343.0..367.5], y in [4.0..598.0] — dual parallel P+ guard bars at x=349.0 and x=361.0
    paint_guard_moat_rects(rects, 348.0, 6.0, 350.0, 596.0)
    paint_guard_moat_rects(rects, 360.0, 6.0, 362.0, 596.0)
    # MOAT_TX_RX: dual guard bars framing the TX-RX isolation bay at x=600.0 and x=644.0 (clear of bias_ctle_v2 at x=639, y=49!)
    paint_guard_moat_rects(rects, 599.2, 6.0, 600.8, 240.0)
    paint_guard_moat_rects(rects, 645.2, 58.0, 646.8, 240.0)

    # 2d. Outer Chip Perimeter Power Rings (full_v4 IR/EM-Hardened PDN: 16 um VSS + 6-14 um Domain VDD Rings + Multi-Via Arrays!)
    # VSS closed M5 ring (w=16.0 um): W x=-14 [-22..-6], S y=-15 [-23..-7], E x=887 [879..895], N y=615 [607..623]
    # Outer VDD M5 rings (>=4.0 um outside VSS): W x=-33, N y=634, E x=906, S y=-34
    vss_w = 16.0
    add_wire_rect(rects, "metal5", [(-14.0, -15.0), (887.0, -15.0), (887.0, 615.0), (-14.0, 615.0), (-14.0, -15.0)], vss_w)
    # Tie moat M2 ground bars cleanly to South/North VSS ring via multi-via arrays
    for xm in (349.0, 361.0):
        add_wire_rect(rects, "metal2", [(xm, 4.0), (xm, 7.0)], 1.60)
        add_via_234_array(rects, xm, 4.5, 2, 2)
        add_wire_rect(rects, "metal4", [(xm, -15.0), (xm, 4.5)], 2.40)
        add_via_45_array(rects, xm, -15.0, 2, 3)
        add_wire_rect(rects, "metal2", [(xm, 595.0), (xm, 598.0)], 1.60)
        add_via_234_array(rects, xm, 597.5, 2, 2)
        add_wire_rect(rects, "metal4", [(xm, 597.5), (xm, 615.0)], 2.40)
        add_via_45_array(rects, xm, 615.0, 2, 3)
    # Tie MOAT_TX_RX West bar (x=600.0) AND East bar (x=646.0) cleanly to South VSS ring!
    add_wire_rect(rects, "metal2", [(600.0, 4.0), (600.0, 7.0)], 1.60)
    add_via_234_array(rects, 600.0, 4.5, 2, 2)
    add_wire_rect(rects, "metal4", [(600.0, -15.0), (600.0, 4.5)], 2.40)
    add_via_45_array(rects, 600.0, -15.0, 2, 3)
    add_wire_rect(rects, "metal2", [(646.0, 2.0), (646.0, 61.0)], 1.60)
    add_via_234_array(rects, 646.0, 2.0, 2, 2)
    add_wire_rect(rects, "metal4", [(646.0, -15.0), (646.0, 2.0)], 2.00)
    add_via_45_array(rects, 646.0, -15.0, 2, 3)

    # Domain-scaled segmented outer VDD rings (M5, >= 4.0 um gap from VSS ring & >= 7.0 um between domains incl. endcaps!)
    # 1) vdd_hv33 (NW, 14.0 um M5): x=-33, y=422..634 and y=634, x=-33..338 (ends x=345)
    add_wire_rect(rects, "metal5", [(-33.0, 422.0), (-33.0, 634.0), (338.0, 634.0)], 14.0)
    # 2) vdd_bias (Mid-W, 6.0 um M5): x=-33, y=214..404 (y=[211..407], >=8 um gap to hv33>=415 & q<=204!)
    add_wire_rect(rects, "metal5", [(-33.0, 214.0), (-33.0, 404.0)], 6.0)
    # 3) vdd_q (SW, 12.0 um M5): x=-33, y=-34..198 and y=-34, x=-33..346 (plus direct internal LDO->VCO 14 um trunk!)
    add_wire_rect(rects, "metal5", [(-33.0, 198.0), (-33.0, -34.0), (346.0, -34.0)], 12.0)
    # 4) vdd_a (North-Center, 12.0 um M5): y=634, x=358..488 (x=[352..494], >=7 um gap to hv33<=345 & d>=503!)
    add_wire_rect(rects, "metal5", [(358.0, 634.0), (488.0, 634.0)], 12.0)
    # 5) vdd_d (NE, 10.0 um M5): y=634, x=508..906 and x=906, y=296..634 (y_bot=291, >=7 um to rx<=284!)
    add_wire_rect(rects, "metal5", [(508.0, 634.0), (906.0, 634.0), (906.0, 296.0)], 10.0)
    # 6) vdd_rx (SE, 12.0 um M5): x=906, y=-34..278 and y=-34, x=622..906 (x_left=616, >=8 um to tx<=608!)
    add_wire_rect(rects, "metal5", [(622.0, -34.0), (906.0, -34.0), (906.0, 278.0)], 12.0)
    # 7) vdd_tx (South-Center, 12.0 um M5): y=-34, x=400..602 (x_right=608, >=8 um to rx>=616!)
    add_wire_rect(rects, "metal5", [(400.0, -34.0), (602.0, -34.0)], 12.0)

    # 2d-bis. Tie ALL 12 Decap Banks' M4 VDD & M2 VSS Buses with Widened Low-ESR M4 Trunks & Multi-Via Arrays!
    dp_by = {d["name"]: d for d in decap_placements}

    # 1) DECAP_HV33_N -> VDD_HV33 (y=634) & VSS (y=615)
    # Keep North M2 VSS vertical trunk shifted +0.20 um East (x_vss_n = x_vss + 0.20) for zero met2.2 DRC!
    if "DECAP_HV33_N" in dp_by:
        b = dp_by["DECAP_HV33_N"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_top"]), (b["x_vdd"], 634.0)], 3.20)
        add_via_45_array(rects, b["x_vdd"], 634.0, 2, 3)
        x_vss_n = grid(b["x_vss"] + 0.20)
        add_wire_rect(rects, "metal2", [(b["x_vss"], b["y_vss_top"]), (x_vss_n, b["y_vss_top"])], 1.00)
        add_wire_rect(rects, "metal2", [(x_vss_n, b["y_vss_top"]), (x_vss_n, 603.0)], 1.00)
        add_via_234_array(rects, x_vss_n, 603.0, 2, 2)
        add_wire_rect(rects, "metal4", [(x_vss_n, 603.0), (x_vss_n, 615.0)], 3.20)
        add_via_45_array(rects, x_vss_n, 615.0, 2, 3)

    # 2) DECAP_BIAS_MID -> VDD_BIAS (x=-33) & VSS (x=-14)
    if "DECAP_BIAS_MID" in dp_by:
        b = dp_by["DECAP_BIAS_MID"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_0"]), (-33.0, b["y_vdd_0"])], 2.40)
        add_via_45_array(rects, -33.0, b["y_vdd_0"], 2, 2)
        add_wire_rect(rects, "metal2", [(b["ox"] - 0.55, b["y_vss_0"]), (6.0, b["y_vss_0"])], 1.20)
        add_via_234_array(rects, 6.0, b["y_vss_0"], 2, 2)
        add_wire_rect(rects, "metal4", [(6.0, b["y_vss_0"]), (-14.0, b["y_vss_0"])], 2.40)
        add_via_45_array(rects, -14.0, b["y_vss_0"], 2, 2)

    # 3) DECAP_BIAS_SW -> VDD_BIAS (x=-33 via x=-3.0 corridor turning West at y=215.0 strictly South of DECAP_BIAS_MID!) & VSS (y=-15)
    if "DECAP_BIAS_SW" in dp_by:
        b = dp_by["DECAP_BIAS_SW"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_top"]), (-3.0, b["y_vdd_top"]), (-3.0, 215.0), (-33.0, 215.0)], 3.00)
        add_via_45_array(rects, -33.0, 215.0, 2, 2)
        add_wire_rect(rects, "metal2", [(b["x_vss"], b["y_vss_0"]), (b["x_vss"], 2.0)], 1.20)
        add_via_234_array(rects, b["x_vss"], 2.0, 2, 2)
        add_wire_rect(rects, "metal4", [(b["x_vss"], 2.0), (b["x_vss"], -15.0)], 3.20)
        add_via_45_array(rects, b["x_vss"], -15.0, 2, 3)

    # 4) DECAP_VDDQ_SW -> VDD_Q (y=-34) & VSS (y=-15)
    if "DECAP_VDDQ_SW" in dp_by:
        b = dp_by["DECAP_VDDQ_SW"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_0"]), (b["x_vdd"], -34.0)], 4.00)
        add_via_45_array(rects, b["x_vdd"], -34.0, 2, 3)
        add_wire_rect(rects, "metal2", [(b["x_vss"], b["y_vss_0"]), (b["x_vss"], 2.0)], 1.40)
        add_via_234_array(rects, b["x_vss"], 2.0, 2, 3)
        add_wire_rect(rects, "metal4", [(b["x_vss"], 2.0), (b["x_vss"], -15.0)], 4.00)
        add_via_45_array(rects, b["x_vss"], -15.0, 2, 3)

    # 5) DECAP_DIG_W -> VDD_D (y=634, x>=505) & VSS via MOAT_QUIET_MAIN (x=361.0 -> 0 M4 crossing!)
    if "DECAP_DIG_W" in dp_by:
        b = dp_by["DECAP_DIG_W"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_top"]), (b["x_vdd"], 605.0), (508.0, 605.0), (508.0, 634.0)], 4.00)
        add_via_45_array(rects, 508.0, 634.0, 2, 3)
        add_wire_rect(rects, "metal2", [(b["ox"] - 0.55, b["y_vss_0"]), (361.0, b["y_vss_0"])], 1.60)

    # 6 & 7) DECAP_CLKA_NW & DECAP_CLKA_S -> widened 3.0 um VDD_A M4 spine:
    #     South section runs at x=349.0 (clears vco_north<=346.25 & vco_south>=351.75), then jogs at y=406 to x=355.0
    #     (centered between MOAT_QUIET_MAIN M4 ties at x=349 and x=361!) all the way North to VDD_A (y=634)!
    if "DECAP_CLKA_NW" in dp_by:
        b = dp_by["DECAP_CLKA_NW"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_top"]), (355.0, b["y_vdd_top"]), (355.0, 634.0)], 3.00)
        add_via_45_array(rects, 355.0, 634.0, 2, 3)
        add_wire_rect(rects, "metal2", [(b["ox"] - 0.55, b["y_vss_0"]), (361.0, b["y_vss_0"])], 1.60)
    if "DECAP_CLKA_S" in dp_by:
        b = dp_by["DECAP_CLKA_S"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_0"]), (349.0, b["y_vdd_0"]), (349.0, 405.0), (355.0, 405.0)], 3.00)
        add_wire_rect(rects, "metal2", [(b["x_vss"], b["y_vss_0"]), (b["x_vss"], 2.0)], 1.40)
        add_via_234_array(rects, b["x_vss"], 2.0, 2, 3)
        add_wire_rect(rects, "metal4", [(b["x_vss"], 2.0), (b["x_vss"], -15.0)], 3.20)
        add_via_45_array(rects, b["x_vss"], -15.0, 2, 3)

    # 8) DECAP_TX_W -> VDD_TX (y=-34) & VSS (y=-15)
    if "DECAP_TX_W" in dp_by:
        b = dp_by["DECAP_TX_W"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_0"]), (b["x_vdd"], -34.0)], 3.20)
        add_via_45_array(rects, b["x_vdd"], -34.0, 2, 3)
        add_wire_rect(rects, "metal2", [(b["x_vss"], b["y_vss_0"]), (b["x_vss"], 2.0)], 1.40)
        add_via_234_array(rects, b["x_vss"], 2.0, 2, 2)
        add_wire_rect(rects, "metal4", [(b["x_vss"], 2.0), (b["x_vss"], -15.0)], 3.20)
        add_via_45_array(rects, b["x_vss"], -15.0, 2, 3)

    # 9) DECAP_TX_E -> VDD_TX via unobstructed M5 corridor at x=604.0 down to y=-34 & VSS via MOAT_TX_RX (x=600.0)!
    if "DECAP_TX_E" in dp_by:
        b = dp_by["DECAP_TX_E"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_0"]), (604.0, b["y_vdd_0"])], 2.40)
        add_via_45_array(rects, 604.0, b["y_vdd_0"], 1, 2)
        add_wire_rect(rects, "metal5", [(604.0, b["y_vdd_0"]), (604.0, -2.5)], 3.20)
        add_via_45_array(rects, 604.0, -2.5, 2, 2)
        add_wire_rect(rects, "metal4", [(604.0, -2.5), (604.0, -34.0)], 3.20)
        add_via_45_array(rects, 604.0, -34.0, 2, 3)
        add_wire_rect(rects, "metal2", [(b["ox"] - 0.55, b["y_vss_0"]), (600.0, b["y_vss_0"])], 1.40)

    # 10 & 11) DECAP_RX_W1 & DECAP_RX_W2 -> VDD_RX (y=-34, x>=616) & VSS via MOAT_TX_RX (x=600.0)!
    if "DECAP_RX_W1" in dp_by and "DECAP_RX_W2" in dp_by:
        b1, b2 = dp_by["DECAP_RX_W1"], dp_by["DECAP_RX_W2"]
        add_wire_rect(rects, "metal4", [(b1["x_vdd"], b1["y_vdd_0"]), (b1["x_vdd"], b2["y_vdd_top"])], 1.60)
        add_wire_rect(rects, "metal4", [(b2["x_vdd"], b2["y_vdd_0"]), (b2["x_vdd"], -34.0), (624.0, -34.0)], 3.20)
        add_via_45_array(rects, 624.0, -34.0, 2, 3)
        add_wire_rect(rects, "metal2", [(b1["ox"] - 0.55, b1["y_vss_0"]), (600.0, b1["y_vss_0"])], 1.40)
        add_wire_rect(rects, "metal2", [(b2["ox"] - 0.55, b2["y_vss_0"]), (600.0, b2["y_vss_0"])], 1.40)

    # 12) DECAP_RX_NE -> VDD_RX (x=906) & VSS (x=887) cleanly across open M4 band y=[258..278]!
    if "DECAP_RX_NE" in dp_by:
        b = dp_by["DECAP_RX_NE"]
        add_wire_rect(rects, "metal4", [(b["x_vdd"], b["y_vdd_0"]), (906.0, b["y_vdd_0"])], 3.20)
        add_via_45_array(rects, 906.0, b["y_vdd_0"], 3, 2)
        add_wire_rect(rects, "metal2", [(b["x_vss"], b["y_vss_0"]), (845.5, b["y_vss_0"])], 1.20)
        add_via_234_array(rects, 845.5, b["y_vss_0"], 2, 2)
        add_wire_rect(rects, "metal4", [(845.5, b["y_vss_0"]), (887.0, b["y_vss_0"])], 3.20)
        add_via_45_array(rects, 887.0, b["y_vss_0"], 3, 2)

    # 2e. Stage 2: Clean DRC=0 Top-Level Inter-Macro Signal Routing
    #     Every route matches exact macro port metal layers and runs strictly in verified open channels
    #     or on M5 over 0%-M5 blocks (zero collisions with macro internals or decap bays!).
    routed_nets = 0
    if stage == "full":
        by_inst = {m.inst: m for m in macros}

        # --- Route 1: Quiet PLL Core W->E Signal Chain ---
        # 1a) PFD (up/dn, M3) -> CP v4 (up/dn, M3) in open gap x=[33..46];
        #     dn crosses over up vertically on M4 (since pfd.dn > pfd.up while cp.dn < cp.up -> ZERO M3 short!)
        p1_up, p2_up = by_inst["pfd_sc_dly"].port_xy("up"), by_inst["cp_v4"].port_xy("up")
        add_wire_rect(rects, "metal3", [p1_up, (36.0, p1_up[1]), (36.0, p2_up[1]), p2_up], 0.50)
        routed_nets += 1
        p1_dn, p2_dn = by_inst["pfd_sc_dly"].port_xy("dn"), by_inst["cp_v4"].port_xy("dn")
        add_wire_rect(rects, "metal3", [p1_dn, (39.0, p1_dn[1])], 0.50)
        add_via_34(rects, 39.0, p1_dn[1])
        add_wire_rect(rects, "metal4", [(39.0, p1_dn[1]), (39.0, p2_dn[1])], 0.50)
        add_via_34(rects, 39.0, p2_dn[1])
        add_wire_rect(rects, "metal3", [(39.0, p2_dn[1]), p2_dn], 0.50)
        routed_nets += 1

        # 1b) CP v4 (out, M3) -> LF k4_fused (ctrl, M3 at South edge y=150.4) cleanly around South in y=144.0!
        p_cp_out = by_inst["cp_v4"].port_xy("out")
        p_lf_ctrl = by_inst["lf_k4_fused"].port_xy("ctrl")
        add_wire_rect(rects, "metal3", [p_cp_out, (111.0, p_cp_out[1]), (111.0, 144.0), (p_lf_ctrl[0], 144.0), p_lf_ctrl], 0.60)
        routed_nets += 1

        # 1c) LF k4_fused (ctrl, M3) -> VCO r6 sym9 (ctrl, M4 at (304.4, 177.8))
        #     M5 width = 2.00 um matches via4 M5 pad width (zero same-net M5 notches!).
        p_vco_vc = by_inst["vco_r6_sym9"].port_xy("ctrl")
        add_wire_rect(rects, "metal3", [p_lf_ctrl, (p_lf_ctrl[0], 140.0), (219.0, 140.0)], 0.60)
        add_via_34(rects, 219.0, 140.0)
        add_via_45(rects, 219.0, 140.0)
        add_wire_rect(rects, "metal5", [(219.0, 140.0), (219.0, 173.0), (p_vco_vc[0], 173.0)], 2.00)
        add_via_45(rects, p_vco_vc[0], 173.0)
        add_wire_rect(rects, "metal4", [(p_vco_vc[0], 173.0), p_vco_vc], 0.36)
        routed_nets += 1

        # --- Route 2: Matched 2 GHz 8-Phase VCO -> 4x CML->CMOS Crossing across 24.5 um Moat ---
        # Exact 4-stage differential ring oscillator 45-deg monotonic phase mapping (matches verify_4g_full_chain.py):
        #   cml2cmos_2 (inp=b0p, inn=b0n) -> (outp=c0 [0 deg],   outn=c4 [180 deg])
        #   cml2cmos_3 (inp=b1n, inn=b1p) -> (outp=c1 [45 deg],  outn=c5 [225 deg])
        #   cml2cmos_0 (inp=b2p, inn=b2n) -> (outp=c2 [90 deg],  outn=c6 [270 deg])
        #   cml2cmos_1 (inp=b3n, inn=b3p) -> (outp=c3 [135 deg], outn=c7 [315 deg])
        vco = by_inst["vco_r6_sym9"]
        vco_north = [
            ("b0n", "cml2cmos_2", "inn", 226.0, 340.0),
            ("b0p", "cml2cmos_2", "inp", 228.0, 342.0),
            ("b1p", "cml2cmos_3", "inn", 230.0, 344.0),
            ("b1n", "cml2cmos_3", "inp", 232.0, 346.0),
        ]
        vco_south = [
            ("b2n", "cml2cmos_0", "inn", 136.0, 352.0),
            ("b2p", "cml2cmos_0", "inp", 138.0, 354.0),
            ("b3p", "cml2cmos_1", "inn", 140.0, 356.0),
            ("b3n", "cml2cmos_1", "inp", 142.0, 358.0),
        ]
        for vp, c_inst, cp, y_ch, x_moat in vco_north + vco_south:
            p1 = vco.port_xy(vp)
            p2 = by_inst[c_inst].port_xy(cp)
            y_in = p2[1] - 0.14 if cp == "inn" else p2[1] + 0.17
            add_wire_rect(rects, "metal2", [p1, (p1[0], y_ch)], 0.40)
            add_via_23(rects, p1[0], y_ch)
            add_wire_rect(rects, "metal3", [(p1[0], y_ch), (x_moat, y_ch)], 0.50)
            add_via_34(rects, x_moat, y_ch)
            add_wire_rect(rects, "metal4", [(x_moat, y_ch), (x_moat, y_in)], 0.50)
            add_via_34(rects, x_moat, y_in)
            add_wire_rect(rects, "metal3", [(x_moat, y_in), (p2[0], y_in)], 0.34)
            routed_nets += 1

        # --- Route 3: 2 GHz CMOS Clock Distribution (4x CML->CMOS -> DIV8, TX QDiv2, RX PI c0..c7) ---
        c2c_outs = []
        for k in range(4):
            c2c = by_inst[f"cml2cmos_{k}"]
            c2c_outs.append((c2c.port_xy("outp"), c2c.port_xy("outn")))

        # 3a) cml2cmos_3 (outp=c1/outn=c5) -> div8_saff (clkp/clkn, M4 at x=370.605)
        #     Enter div8_saff on metal3 cleanly UNDER its West M4 VDD bar (x=368.1..368.9) -> via34 onto clkp/clkn M4!
        d8 = by_inst["div8_saff"]
        for src_x_br, dp, y_ch, x_w in (
            (424.0 + 1 * 2.85, "clkp", 253.0, 363.5),  # c1 = cml2cmos_3.outp (outer West -> clears clkn M4!)
            (424.0 + 5 * 2.85, "clkn", 252.2, 365.5),  # c5 = cml2cmos_3.outn (inner East -> 0 M4 crossing!)
        ):
            dst_pt = d8.port_xy(dp)
            add_via_34(rects, src_x_br, y_ch)
            add_wire_rect(rects, "metal3", [(src_x_br, y_ch), (x_w, y_ch)], 0.40)
            add_via_34(rects, x_w, y_ch)
            add_wire_rect(rects, "metal4", [(x_w, y_ch), (x_w, dst_pt[1])], 0.44)
            add_via_34(rects, x_w, dst_pt[1])
            add_wire_rect(rects, "metal3", [(x_w, dst_pt[1]), dst_pt], 0.40)
            add_via_34(rects, dst_pt[0], dst_pt[1])
            routed_nets += 1

        # 3b) 250 MHz Feedback: div8_saff (q8p, M4) -> pfd_sc_dly (fb, M2) on shielded 2.0 um M5 trunk,
        #     dipping cleanly onto M3 across x=[332.5..354.5] under BOTH VDD_Q (14 um M5 @ x=342) and VDD_A (3 um M4 @ x=349)!
        p_q8 = d8.port_xy("q8p")
        p_fb = by_inst["pfd_sc_dly"].port_xy("fb")
        add_wire_rect(rects, "metal4", [p_q8, (468.5, p_q8[1])], 0.60)
        add_via_45(rects, 468.5, p_q8[1])
        if use_v5_review_macros:
            # div8_saff is at y=288.5..306.0 (0% M5!): fly cleanly West over div8_saff on M5 -> x=355.0 -> y=251.5!
            add_wire_rect(rects, "metal5", [
                (468.5, p_q8[1]), (355.0, p_q8[1]), (355.0, 251.5),
            ], 2.00)
        else:
            add_wire_rect(rects, "metal5", [
                (468.5, p_q8[1]), (468.5, 287.0), (355.0, 287.0), (355.0, 251.5),
            ], 2.00)
        add_via_45(rects, 355.0, 251.5)
        add_via_34(rects, 355.0, 251.5)
        add_wire_rect(rects, "metal3", [(355.0, 251.5), (331.0, 251.5)], 0.80)
        add_via_34(rects, 331.0, 251.5)
        add_via_45(rects, 331.0, 251.5)
        # Fly over pfd_sc_dly's West M2 VSS rail (x=6.00..6.50) on M4 at y=182.65 (clear of internal M3<=181.93 & top M2>=183.45),
        # then drop via34+via23 at (7.35, 182.65) -> short M2 stub straight onto pfd_sc_dly.fb (x=6.80..8.35, y=182.16)!
        y_fb_drop = 182.65
        add_wire_rect(rects, "metal5", [(331.0, 251.5), (1.5, 251.5), (1.5, y_fb_drop)], 2.00)
        add_via_45(rects, 1.5, y_fb_drop)
        add_wire_rect(rects, "metal4", [(1.5, y_fb_drop), (7.35, y_fb_drop)], 0.44)
        add_via_34(rects, 7.35, y_fb_drop)
        add_via_23(rects, 7.35, y_fb_drop)
        add_wire_rect(rects, "metal2", [(7.35, y_fb_drop), (7.35, p_fb[1])], 0.42)
        routed_nets += 1

        # 3c) Exact Monotonic 8-Phase 2 GHz CMOS Clock Spine (c0..c7 = 0,45,90,135,180,225,270,315 deg)
        #     + Exact 90-deg Quadrature Tap into tx_qdiv2 (dp=c0, dn=c4, ep=c2, en=c6)!
        rx = by_inst["rx_cmos_top"]
        txq = by_inst["tx_qdiv2"]
        ordered_8ph = [
            (c2c_outs[2][0], "c0"),  # b0p ->   0 deg
            (c2c_outs[3][0], "c1"),  # b1n ->  45 deg
            (c2c_outs[0][0], "c2"),  # b2p ->  90 deg
            (c2c_outs[1][0], "c3"),  # b3n -> 135 deg
            (c2c_outs[2][1], "c4"),  # b0n -> 180 deg
            (c2c_outs[3][1], "c5"),  # b1p -> 225 deg
            (c2c_outs[0][1], "c6"),  # b2n -> 270 deg
            (c2c_outs[1][1], "c7"),  # b3p -> 315 deg
        ]
        txq_taps = {"c0": "dp", "c4": "dn", "c2": "ep", "c6": "en"}
        for idx, (src_pt, rname) in enumerate(ordered_8ph):
            dst_pt = rx.port_xy(rname)
            x_br = 424.0 + idx * 2.85         # 424.0 .. 443.95 (ALL 8 spines strictly West of tx_sst_top>=446.0!)
            if use_v5_review_macros:
                # Full_v5: div8_saff moved North to y=288.5 -> 0 M5 bridges needed on c0..c7!
                # Straight M4 vertical spine -> M3 horizontal in open gap y=[281.00..286.18] (above tx_qdiv2<=279.57)!
                y_bus = 281.0 + idx * 0.74
                add_wire_rect(rects, "metal3", [src_pt, (x_br, src_pt[1])], 0.40)
                add_via_34(rects, x_br, src_pt[1])
                add_wire_rect(rects, "metal4", [(x_br, src_pt[1]), (x_br, y_bus)], 0.44)
                add_via_34(rects, x_br, y_bus)
                add_wire_rect(rects, "metal3", [(x_br, y_bus), (dst_pt[0], y_bus), dst_pt], 0.34)
                if rname in txq_taps:
                    tp = txq.port_xy(txq_taps[rname])
                    add_via_34(rects, x_br, tp[1])
                    add_wire_rect(rects, "metal3", [(x_br, tp[1]), tp], 0.36)
            else:
                y_s = 254.6
                y_n = 274.75
                y_bus = 275.4 + idx * 0.74
                add_wire_rect(rects, "metal3", [src_pt, (x_br, src_pt[1])], 0.40)
                add_via_34(rects, x_br, src_pt[1])
                add_wire_rect(rects, "metal4", [(x_br, src_pt[1]), (x_br, y_s)], 0.44)
                add_via_45(rects, x_br, y_s)
                add_wire_rect(rects, "metal5", [(x_br, y_s), (x_br, y_n)], 2.00)
                add_via_45(rects, x_br, y_n)
                add_wire_rect(rects, "metal4", [(x_br, y_n), (x_br, y_bus)], 0.44)
                add_via_34(rects, x_br, y_bus)
                add_wire_rect(rects, "metal3", [(x_br, y_bus), (dst_pt[0], y_bus), dst_pt], 0.34)
                if rname in txq_taps:
                    tp = txq.port_xy(txq_taps[rname])
                    add_wire_rect(rects, "metal4", [(x_br, src_pt[1]), (x_br, tp[1])], 0.44)
                    add_via_34(rects, x_br, tp[1])
                    add_wire_rect(rects, "metal3", [(x_br, tp[1]), tp], 0.36)
            routed_nets += 1

        # 3d) TX QDiv2 (ckd0..3, M4) -> TX SST Top (phi0..phi270, M3) in open gap!
        tx = by_inst["tx_sst_top"]
        y_q_off = 24.60 if use_v5_review_macros else 0.0
        for qp, tp, y_mid in (
            ("ckd0", "phi0",   234.00 + y_q_off),
            ("ckd1", "phi90",  235.20 + y_q_off),
            ("ckd2", "phi180", 237.60 + y_q_off),
            ("ckd3", "phi270", 236.40 + y_q_off),
        ):
            p1 = txq.port_xy(qp)
            p2 = tx.port_xy(tp)
            add_wire_rect(rects, "metal4", [p1, (p1[0], y_mid), (p2[0], y_mid)], 0.40)
            add_via_34(rects, p2[0], y_mid)
            add_wire_rect(rects, "metal3", [(p2[0], y_mid), p2], 0.40)
            routed_nets += 1

        # --- Route 4: Digital South-Edge (met2) <-> TX & RX Full Buses (100% Orthogonal M2/M3/M4!) ---
        dig = by_inst["digital_top_v3"]

        # 4a) TX clock & 16-bit data bundle (17 nets): sorted West->East so M2 drops never cross;
        #     safe via2+via3 X strictly outside vertical M3 trunk [596.8..611.8] AND never crosses any earlier M2 drop!
        tx_dig_pairs = [("tx_word_clk", "clk250_out")] + [(f"tx_capture_data[{i}]", f"din{i}") for i in range(16)]
        tx_dig_pairs.sort(key=lambda pair: dig.port_xy(pair[0])[0])
        all_tx_p1_xs = [dig.port_xy(dp)[0] for dp, _ in tx_dig_pairs]
        tx_xvs = [597.5 + i * 0.84 for i in range(len(tx_dig_pairs))]
        placed_tx_vias: list[tuple[float, float]] = []

        def _safe_tx_via_x(x_pref: float, y_cur: float, idx_cur: int) -> float:
            # Earlier pins j < idx_cur have y_ch[j] < y_cur, so their M2 vertical drops pass through y_cur!
            # Later pins k > idx_cur have y_ch[k] > y_cur, so their M2 vertical drops stop ABOVE y_cur!
            # Therefore searching EAST (xc >= x_pref) or forbidding crossing any earlier pin's X guarantees 0 M2 shorts!
            earlier_xs = all_tx_p1_xs[:idx_cur]
            candidates = [x_pref]
            for step in range(1, 60):
                candidates.append(x_pref + step * 0.60)
                candidates.append(x_pref - step * 0.60)
            for xc in candidates:
                if 596.6 <= xc <= 612.0:
                    continue
                if xc < 582.0 or xc > 630.0:
                    continue
                if 0.05 <= abs(xc - x_pref) < 0.55:
                    continue
                lo_x, hi_x = min(x_pref, xc) - 0.45, max(x_pref, xc) + 0.45
                if any(lo_x <= ex <= hi_x for ex in earlier_xs):
                    continue
                if any(
                    math.hypot(max(0.0, abs(xc - vx) - 0.52), max(0.0, abs(y_cur - vy) - 0.52)) < 0.36
                    for vx, vy in placed_tx_vias
                ):
                    continue
                return round(xc, 2)
            return round(max(612.4, x_pref), 2)

        for idx, (dp, tp) in enumerate(tx_dig_pairs):
            p1 = dig.port_xy(dp)
            p2 = tx.port_xy(tp)
            y_ch = 259.2 + idx * 0.84             # 259.20 .. 272.64 (strictly North of tx_sst_top<=257.52 -> 0 vss short!)
            xv = tx_xvs[idx]                      # 597.50 .. 610.94 (West of DECAP_TX_E>=612.96!)
            x_via = _safe_tx_via_x(p1[0], y_ch, idx)
            placed_tx_vias.append((x_via, y_ch))
            if abs(x_via - p1[0]) < 0.05:
                add_wire_rect(rects, "metal2", [p1, (p1[0], y_ch)], 0.24)
            else:
                add_wire_rect(rects, "metal2", [p1, (p1[0], y_ch), (x_via, y_ch)], 0.24)
            add_via_23(rects, x_via, y_ch)
            add_via_34(rects, x_via, y_ch)
            add_wire_rect(rects, "metal4", [(x_via, y_ch), (xv, y_ch)], 0.32)
            add_via_34(rects, xv, y_ch)
            add_wire_rect(rects, "metal3", [(xv, y_ch), (xv, p2[1])], 0.32)
            add_via_34(rects, xv, p2[1])
            add_wire_rect(rects, "metal4", [(xv, p2[1]), p2], 0.32)
            routed_nets += 1

        # 4b) RX 24-bit PI Control Bus (a0..7, b0..7, f0..7):
        #     100% orthogonal zero-crossing stack: M2 vertical drop from digital -> M2 safe-X jog outside vertical trunk
        #     & c0..c7 drops -> via2+via3 -> M4 horizontal in y=[256.8..273.36] (interleaved odd/even to avoid diagonal via3!)
        #     -> via3 -> 24 M3 vertical tracks in x=[631.8..648.36] -> via3 -> M4 horizontal East to x=649.4
        #     -> via3+via2 -> M2 into rx_cmos_top West edge (x=650.3, 1.6 um pitch)!
        rx_pi_pairs = (
            [(f"rx_select_a[{i}]", f"a{i}") for i in range(8)]
            + [(f"rx_select_b[{i}]", f"b{i}") for i in range(8)]
            + [(f"rx_fine_b[{i}]", f"f{i}") for i in range(8)]
        )
        # Sort West->East by digital pin X so M2 drops never cross each other
        rx_pi_pairs.sort(key=lambda pair: dig.port_xy(pair[0])[0])
        c_drop_xs = [rx.port_xy(f"c{k}")[0] for k in range(8)]
        xv_list = [631.8 + i * 0.72 for i in range(len(rx_pi_pairs))]
        all_pi_p1_xs = [dig.port_xy(dp)[0] for dp, _ in rx_pi_pairs]
        placed_pi_vias: list[tuple[float, float]] = []

        def _safe_pi_via_x(x_pref: float, y_cur: float, idx_cur: int) -> float:
            # Must avoid: (1) vertical M3 trunk [630.8..649.8], (2) c0..c7 M3 drops,
            # (3) exact square-to-square gap >= 0.35 um from placed vias, (4) earlier pins' M2 drops passing y_cur!
            earlier_xs = all_pi_p1_xs[:idx_cur]
            candidates = [x_pref]
            for step in range(1, 60):
                candidates.append(x_pref + step * 0.60)
                candidates.append(x_pref - step * 0.60)
            for xc in candidates:
                if xc < 650.8 or xc > 720.0:
                    continue
                if 0.05 <= abs(xc - x_pref) < 0.55:
                    continue
                if any(abs(xc - cx) < 0.90 for cx in c_drop_xs):
                    continue
                lo_x, hi_x = min(x_pref, xc) - 0.45, max(x_pref, xc) + 0.45
                if any(lo_x <= ex <= hi_x for ex in earlier_xs):
                    continue
                if any(
                    math.hypot(max(0.0, abs(xc - vx) - 0.52), max(0.0, abs(y_cur - vy) - 0.52)) < 0.36
                    for vx, vy in placed_pi_vias
                ):
                    continue
                return round(xc, 2)
            return round(max(651.0, x_pref), 2)

        for idx, (dp, rp) in enumerate(rx_pi_pairs):
            p1 = dig.port_xy(dp)
            p2 = rx.port_xy(rp)
            # Strictly increasing y_ch West->East => ZERO M2 crossings! Interleave xv by +12 => ZERO diagonal via3!
            y_ch = 256.8 + idx * 0.72             # 256.80 .. 273.36 (below c0..c7>=275.4)
            x_idx = (idx // 2) + (12 if (idx % 2) else 0)
            xv = xv_list[x_idx]                   # 631.80 .. 648.36 (East of DECAP<=631.04, West of via3/2 x=649.4!)
            x_via = _safe_pi_via_x(p1[0], y_ch, idx)
            placed_pi_vias.append((x_via, y_ch))
            if abs(x_via - p1[0]) < 0.05:
                add_wire_rect(rects, "metal2", [p1, (p1[0], y_ch)], 0.24)
            else:
                # Short clean M2 jog at y_ch (no M2 conflict since rx_pi_pairs sorted West->East & unique y_ch!)
                add_wire_rect(rects, "metal2", [p1, (p1[0], y_ch), (x_via, y_ch)], 0.24)
            add_via_23(rects, x_via, y_ch)
            add_via_34(rects, x_via, y_ch)
            add_wire_rect(rects, "metal4", [(x_via, y_ch), (xv, y_ch)], 0.30)
            add_via_34(rects, xv, y_ch)
            add_wire_rect(rects, "metal3", [(xv, y_ch), (xv, p2[1])], 0.30)
            add_via_34(rects, xv, p2[1])
            add_wire_rect(rects, "metal4", [(xv, p2[1]), (649.4, p2[1])], 0.30)
            add_via_34(rects, 649.4, p2[1])
            add_via_23(rects, 649.4, p2[1])
            add_wire_rect(rects, "metal2", [(649.4, p2[1]), p2], 0.30)
            routed_nets += 1

        # 4c) FULL 33-Net RX Data + Edge + Word Clock Bus (wclk + wd[0..15] + we[0..15] -> rx_phys[0..31]):
        #     Direct chronological mapping matching v3.2 rx_word_map.sv & rx_cmos_deser16.spice!
        #     Upper 24 tracks run North of DECAP_RX_NE (y=[281.4..298.4]) and lower 9 tracks run South of DECAP_RX_NE
        #     (y=[247.5..253.8]), all cleanly entering the 33-track East channel x=[847.2..874.7]!
        rx_dig_pairs = (
            [("rx_word_clk", "wclk")]
            + [(f"rx_phys[{i}]", f"wd{i}") for i in range(16)]
            + [(f"rx_phys[{16 + i}]", f"we{i}") for i in range(16)]
        )
        # Split tracks cleanly around DECAP_RX_NE ([260.25..277.75]) based on available vertical channel height
        n_upper = min(len(rx_dig_pairs), max(17, int((dig.y - 1.0 - 281.4) // 0.74) + 1))
        for idx, (dp, rp) in enumerate(rx_dig_pairs):
            p1 = dig.port_xy(dp)
            p2 = rx.port_xy(rp)
            if idx < n_upper:
                y_ch = 281.4 + idx * 0.74         # strictly North of DECAP_RX_NE<=277.75 & c0..c7<=280.58!
            else:
                y_ch = 247.2 + (idx - n_upper) * 0.74  # strictly South of DECAP_RX_NE>=260.25 & rx_pi>=256.8!
            xv = 847.2 + idx * 0.86               # 847.20 .. 874.72 (all 33 tracks strictly West of VSS ring 879.5!)
            add_wire_rect(rects, "metal2", [p1, (p1[0], y_ch)], 0.28)
            add_via_23(rects, p1[0], y_ch)
            add_via_34(rects, p1[0], y_ch)
            add_wire_rect(rects, "metal4", [(p1[0], y_ch), (xv, y_ch)], 0.30)
            add_via_34(rects, xv, y_ch)
            add_wire_rect(rects, "metal3", [(xv, y_ch), (xv, p2[1])], 0.32)
            add_via_34(rects, xv, p2[1])
            add_wire_rect(rects, "metal4", [(xv, p2[1]), p2], 0.32)
            routed_nets += 1

        # --- Route 5: Key Analog Bias / LDO / Quiet-Supply High-Current Trunks ---
        # Enter ldo_v2_cur.bg on metal2 (w=0.30 um for >=0.23 um met2.2 margin!) cleanly UNDER its West M3 VSS trunk
        p_vbg = by_inst["bias_top_v2"].port_xy("vbg")
        p_bg = by_inst["ldo_v2_cur"].port_xy("bg")
        add_wire_rect(rects, "metal3", [p_vbg, (p_vbg[0], 416.0), (8.0, 416.0), (8.0, p_bg[1])], 0.60)
        add_via_23(rects, 8.0, p_bg[1])
        add_wire_rect(rects, "metal2", [(8.0, p_bg[1]), p_bg], 0.30)
        routed_nets += 1

        # 5-bis) Missing LDO & CP Bias Current Feeds (bias_top_v2.i_ldo0 -> ldo_v2_cur.i_ldo, i_ldo1 -> cp_v4.ibias)
        p_ildo0 = by_inst["bias_top_v2"].port_xy("i_ldo0")
        p_ldo_i = by_inst["ldo_v2_cur"].port_xy("i_ldo")
        add_wire_rect(rects, "metal2", [p_ildo0, (6.2, p_ildo0[1])], 0.34)
        add_via_23(rects, 6.2, p_ildo0[1])
        add_wire_rect(rects, "metal3", [(6.2, p_ildo0[1]), (6.2, p_ldo_i[1])], 0.44)
        add_via_23(rects, 6.2, p_ldo_i[1])
        add_wire_rect(rects, "metal2", [(6.2, p_ldo_i[1]), p_ldo_i], 0.30)
        routed_nets += 1

        # i_ldo1 runs West at x=4.2 on M3 (clears fb250 M5<=2.5 & M4@y=182.65, clears DECAP_BIAS_MID via234@6.0!),
        # South to y=144.5 (strictly North of DECAP_BIAS_SW<=134 & bias trunks<=133.5, South of cp_vbn@146.5),
        # hops on M4 over x=8.4..12.0 M3 trunks -> M3 East to x=46.5 (1.5 um East of cp_vbn@45.0!) -> cp_v4.ibias!
        p_ildo1 = by_inst["bias_top_v2"].port_xy("i_ldo1")
        p_cp_ib = by_inst["cp_v4"].port_xy("ibias")
        add_wire_rect(rects, "metal2", [p_ildo1, (4.2, p_ildo1[1])], 0.34)
        add_via_23(rects, 4.2, p_ildo1[1])
        add_wire_rect(rects, "metal3", [(4.2, p_ildo1[1]), (4.2, 144.5)], 0.44)
        add_via_34(rects, 4.2, 144.5)
        add_wire_rect(rects, "metal4", [(4.2, 144.5), (14.0, 144.5)], 0.44)
        add_via_34(rects, 14.0, 144.5)
        add_wire_rect(rects, "metal3", [(14.0, 144.5), (46.5, 144.5), (46.5, p_cp_ib[1]), p_cp_ib], 0.44)
        routed_nets += 1

        # A3 + Full Analog Bias & Reference Closure (full_v6: all 9 analog bias/ref chains wired!)
        if by_inst["bias_top_v2"].raw.cell_name == "serdes_bias_top_v2_ptat_pdk":
            # 5c) A1 Chip-Level Closure: bias_top_v2.vbg -> tx_sst_top.vbg (unity-gain buffered!)
            p_tx_vbg = by_inst["tx_sst_top"].port_xy("vbg")
            add_wire_rect(rects, "metal3", [(p_vbg[0], 416.0), (345.0, 416.0), (345.0, 410.0), (496.5, 410.0)], 0.50)
            add_via_34(rects, 496.5, 410.0)
            add_wire_rect(rects, "metal4", [(496.5, 410.0), (496.5, 290.0)], 0.50)
            add_via_45(rects, 496.5, 290.0)
            add_wire_rect(rects, "metal5", [(496.5, 290.0), (p_tx_vbg[0], 290.0), (p_tx_vbg[0], 260.0)], 2.00)
            add_via_45(rects, p_tx_vbg[0], 260.0)
            add_via_34(rects, p_tx_vbg[0], 260.0)
            add_via_23(rects, p_tx_vbg[0], 260.0)
            add_wire_rect(rects, "metal2", [(p_tx_vbg[0], 260.0), p_tx_vbg], 0.44)

            # 5d) A3 PTAT vgi/vg: bias_top_v2_ptat (North M3) -> vco_ptat_bias (West M2)
            p_b_vgi = by_inst["bias_top_v2"].port_xy("vgi")
            p_p_vgi = by_inst["vco_ptat_bias"].port_xy("vgi")
            add_wire_rect(rects, "metal3", [p_b_vgi, (p_b_vgi[0], 412.0), (190.5, 412.0), (190.5, p_p_vgi[1])], 0.50)
            add_via_23(rects, 190.5, p_p_vgi[1])
            add_wire_rect(rects, "metal2", [(190.5, p_p_vgi[1]), p_p_vgi], 0.50)
            routed_nets += 1

            p_b_vg = by_inst["bias_top_v2"].port_xy("vg")
            p_p_vg = by_inst["vco_ptat_bias"].port_xy("vg")
            add_wire_rect(rects, "metal3", [p_b_vg, (p_b_vg[0], 414.0)], 0.50)
            add_via_34(rects, p_b_vg[0], 414.0)
            add_wire_rect(rects, "metal4", [(p_b_vg[0], 414.0), (192.2, 414.0)], 0.50)
            add_via_34(rects, 192.2, 414.0)
            add_wire_rect(rects, "metal3", [(192.2, 414.0), (192.2, p_p_vg[1])], 0.50)
            add_via_23(rects, 192.2, p_p_vg[1])
            add_wire_rect(rects, "metal2", [(192.2, p_p_vg[1]), p_p_vg], 0.50)
            routed_nets += 1

            # 5e) VCO PTAT Bias Chain: vco_ptat_bias.out (M4) -> bias_cml_vco.iin (M4) -> bias_lpf_slow.original (M1)
            p_ptat_out = by_inst["vco_ptat_bias"].port_xy("out")
            p_bcml_vco = by_inst["bias_cml_vco"].port_xy("iin")
            p_lpf_in = by_inst["bias_lpf_slow"].port_xy("original")
            add_wire_rect(rects, "metal4", [
                p_ptat_out, (343.6, p_ptat_out[1]), (343.6, 342.0), (301.2, 342.0),
                (301.2, p_bcml_vco[1]), p_bcml_vco,
            ], 0.60)
            add_wire_rect(rects, "metal4", [
                (301.2, p_bcml_vco[1]), (301.2, 277.0), (p_lpf_in[0], 277.0), p_lpf_in,
            ], 0.50)
            add_via_34(rects, p_lpf_in[0], p_lpf_in[1])
            add_via_23(rects, p_lpf_in[0], p_lpf_in[1])
            add_via_12(rects, p_lpf_in[0], p_lpf_in[1])
            routed_nets += 1

            # 5f) Filtered VCO Tail Bias: bias_lpf_slow.filtered (M4) -> vco_r6_sym9.vbias_q (M4 via M5 over 0%-M5 VCO)
            p_lpf_out = by_inst["bias_lpf_slow"].port_xy("filtered")
            p_vco_vb = by_inst["vco_r6_sym9"].port_xy("vbias_q")
            add_wire_rect(rects, "metal4", [
                p_lpf_out, (191.5, p_lpf_out[1]), (191.5, 240.0), (219.0, 240.0), (219.0, p_vco_vb[1]),
            ], 0.50)
            add_via_45(rects, 219.0, p_vco_vb[1])
            add_wire_rect(rects, "metal5", [(219.0, p_vco_vb[1]), p_vco_vb], 2.00)
            add_via_45(rects, p_vco_vb[0], p_vco_vb[1])
            routed_nets += 1

            # 5g) PLL LF Precharge Reference: bias_top_v2.pref (M3) -> lf_k4_fused.pre_ref (M3)
            p_pref = by_inst["bias_top_v2"].port_xy("pref")
            p_lf_pref = by_inst["lf_k4_fused"].port_xy("pre_ref")
            add_wire_rect(rects, "metal3", [
                p_pref, (188.2, p_pref[1]), (188.2, 218.0), (113.2, 218.0), (113.2, p_lf_pref[1]), p_lf_pref,
            ], 0.44)
            routed_nets += 1

            # 5h) Charge Pump Bias Mirror Chain: bias_top_v2.icp -> bias_cp_v2.vbn -> cp_v4.vbn & vbp -> cp_v4.vbp
            #     Ordered West->East in x=[8.4, 9.6, 10.8, 12.0] = [rx_vcm, rx_ictle, host_cml_bias, cp_vbn] -> 0 M3 crossings!
            p_icp = by_inst["bias_top_v2"].port_xy("icp")
            p_bcp_n = by_inst["bias_cp_v2"].port_xy("vbn")
            p_bcp_p = by_inst["bias_cp_v2"].port_xy("vbp")
            p_cp_n = by_inst["cp_v4"].port_xy("vbn")
            p_cp_p = by_inst["cp_v4"].port_xy("vbp")
            add_wire_rect(rects, "metal2", [p_icp, (12.0, p_icp[1])], 0.40)
            add_via_23(rects, 12.0, p_icp[1])
            add_wire_rect(rects, "metal3", [(12.0, p_icp[1]), (12.0, 187.0)], 0.44)
            add_via_34(rects, 12.0, 187.0)
            add_wire_rect(rects, "metal4", [(12.0, 187.0), (12.0, 175.0)], 0.44)  # hops cleanly over 0%-M4 pfd_sc_dly
            add_via_34(rects, 12.0, 175.0)
            add_wire_rect(rects, "metal3", [(12.0, 175.0), (12.0, 146.5), (45.0, 146.5), (45.0, p_cp_n[1]), p_cp_n], 0.44)
            # Stay on M3 over bias_cp_v2's South M2 VSS rail (y=150.45), then drop via23 straight onto bias_cp_v2.vbn!
            add_wire_rect(rects, "metal3", [(p_bcp_n[0], 146.5), p_bcp_n], 0.44)
            add_via_23(rects, p_bcp_n[0], p_bcp_n[1])
            routed_nets += 1

            add_wire_rect(rects, "metal3", [p_bcp_p, (43.6, p_bcp_p[1])], 0.44)
            add_via_34(rects, 43.6, p_bcp_p[1])
            add_wire_rect(rects, "metal4", [(43.6, p_bcp_p[1]), (43.6, p_cp_p[1]), (46.6, p_cp_p[1])], 0.44)
            add_via_34(rects, 46.6, p_cp_p[1])
            add_wire_rect(rects, "metal3", [(46.6, p_cp_p[1]), p_cp_p], 0.44)
            routed_nets += 1

            # 5i) Host Clock CML Bias Chain: bias_top_v2.icml -> bias_cml_host.iin (M4) -> 4x cml2cmos.vbias (M3)
            p_icml = by_inst["bias_top_v2"].port_xy("icml")
            p_bcml_h = by_inst["bias_cml_host"].port_xy("iin")
            add_wire_rect(rects, "metal2", [p_icml, (10.8, p_icml[1])], 0.40)
            add_via_23(rects, 10.8, p_icml[1])
            add_wire_rect(rects, "metal3", [(10.8, p_icml[1]), (10.8, 187.0)], 0.44)
            add_via_34(rects, 10.8, 187.0)
            add_wire_rect(rects, "metal4", [(10.8, 187.0), (10.8, 175.0)], 0.44)
            add_via_34(rects, 10.8, 175.0)
            add_wire_rect(rects, "metal3", [(10.8, 175.0), (10.8, 133.5), (365.5, 133.5)], 0.44)
            add_via_34(rects, 365.5, 133.5)
            c2c_vbs = [by_inst[f"cml2cmos_{k}"].port_xy("vbias") for k in range(4)]
            add_wire_rect(rects, "metal4", [(365.5, p_bcml_h[1]), (365.5, c2c_vbs[-1][1])], 0.44)
            add_wire_rect(rects, "metal4", [(365.5, p_bcml_h[1]), p_bcml_h], 0.44)
            for p_vb in c2c_vbs:
                add_via_34(rects, 365.5, p_vb[1])
                add_wire_rect(rects, "metal3", [(365.5, p_vb[1]), p_vb], 0.30)
            routed_nets += 1

            # 5j) RX CTLE Bias & Termination VCM: drop South at x=345.0/343.5 (West of vco_south x_moat>=352!) to y=120.5/119.0!
            p_ictle = by_inst["bias_top_v2"].port_xy("ictle")
            p_rx_ic = by_inst["rx_cmos_top"].port_xy("ibias_ctle")
            add_wire_rect(rects, "metal2", [p_ictle, (9.6, p_ictle[1])], 0.40)
            add_via_23(rects, 9.6, p_ictle[1])
            add_wire_rect(rects, "metal3", [(9.6, p_ictle[1]), (9.6, 187.0)], 0.44)
            add_via_34(rects, 9.6, 187.0)
            add_wire_rect(rects, "metal4", [(9.6, 187.0), (9.6, 175.0)], 0.44)
            add_via_34(rects, 9.6, 175.0)
            add_wire_rect(rects, "metal3", [
                (9.6, 175.0), (9.6, 131.5), (345.0, 131.5), (345.0, 120.5),
                (401.6, 120.5), (401.6, -2.5), (642.5, -2.5), (642.5, p_rx_ic[1]),
            ], 0.44)
            add_via_34(rects, 642.5, p_rx_ic[1])
            add_wire_rect(rects, "metal4", [(642.5, p_rx_ic[1]), p_rx_ic], 0.44)
            routed_nets += 1

            p_vcm = by_inst["bias_top_v2"].port_xy("vcm")
            p_rx_vcm = by_inst["rx_cmos_top"].port_xy("vcm_ref")
            add_wire_rect(rects, "metal3", [p_vcm, (p_vcm[0], 253.6), (13.6, 253.6)], 0.44)
            add_via_34(rects, 13.6, 253.6)
            add_wire_rect(rects, "metal4", [(13.6, 253.6), (8.4, 253.6)], 0.44)  # hops cleanly over x=9.6..12.0 M3!
            add_via_34(rects, 8.4, 253.6)
            add_wire_rect(rects, "metal3", [(8.4, 253.6), (8.4, 187.0)], 0.44)
            add_via_34(rects, 8.4, 187.0)
            add_wire_rect(rects, "metal4", [(8.4, 187.0), (8.4, 175.0)], 0.44)
            add_via_34(rects, 8.4, 175.0)
            add_wire_rect(rects, "metal3", [
                (8.4, 175.0), (8.4, 129.5), (343.5, 129.5), (343.5, 119.0),
                (400.2, 119.0), (400.2, -4.0), (643.8, -4.0), (643.8, p_rx_vcm[1]),
            ], 0.44)
            add_via_34(rects, 643.8, p_rx_vcm[1])
            add_wire_rect(rects, "metal4", [(643.8, p_rx_vcm[1]), p_rx_vcm], 0.44)
            routed_nets += 1

        # 5a) VDD_HV33 high-current feed into ldo_v2_cur.vin (28 mA FF peak):
        #     6 um M5 || 8 um M4 horizontal bridge in open gap y=550.5 -> 12 um M5 vertical at x=333.5 -> 5x5 via4 -> 12 um M4 under VSS -> 5x5 via4 onto VDD_HV33 North ring!
        p_vin = by_inst["ldo_v2_cur"].port_xy("vin")
        add_wire_rect(rects, "metal5", [p_vin, (p_vin[0], 550.5), (333.5, 550.5)], 6.00)
        add_via_45_array(rects, p_vin[0] + 6.0, 550.5, 4, 2)
        add_wire_rect(rects, "metal4", [(p_vin[0] + 3.0, 550.5), (333.5, 550.5)], 6.00)
        add_via_45_array(rects, 333.5, 550.5, 4, 2)
        add_wire_rect(rects, "metal5", [(333.5, 550.5), (333.5, 598.0)], 12.00)
        add_via_45_array(rects, 333.5, 598.0, 5, 5)
        add_wire_rect(rects, "metal4", [(333.5, 598.0), (333.5, 634.0)], 12.00)
        add_via_45_array(rects, 333.5, 634.0, 5, 5)
        routed_nets += 1

        # 5b) NEW Direct Internal VDD_Q Super-Highway (ldo_v2_cur.quiet -> vco_r6_sym9.vdd_q -> VDD_Q South Ring!):
        #     Cuts VDD_Q static IR drop 18x (190.2 mV -> 10.5 mV) and brings via4 EM down from 862% -> 72%!
        #     14.0 um M5 vertical spine at x=342.0 (x=[335..349], >=3.0 um clear of bias_cml_vco/vco/DECAP_VDDQ_SW!),
        #     12.0 um M5 West branch at y=232.0 -> 6x4 (24-cut) via4 array onto vco_r6_sym9.vdd_q (278.3, 223.4),
        #     and 10.0 um M4 underpass at x=341.0 across South VSS ring into VDD_Q South ring (y=-34.0)!
        p_quiet = by_inst["ldo_v2_cur"].port_xy("quiet")
        p_vco_vdd = by_inst["vco_r6_sym9"].port_xy("vdd_q")
        add_wire_rect(rects, "metal5", [p_quiet, (342.0, p_quiet[1])], 12.00)
        add_wire_rect(rects, "metal5", [(342.0, p_quiet[1]), (342.0, 3.0)], 14.00)
        add_wire_rect(rects, "metal5", [(342.0, 232.0), (p_vco_vdd[0], 232.0)], 12.00)
        add_via_45_array(rects, p_vco_vdd[0], 232.0, 6, 4)
        # Drop M4 cleanly onto vco_r6_sym9.vdd_q (y=223.4) staying >=0.8 um North of vco.vss (y=221.9)
        rects.setdefault("metal4", []).append((u(p_vco_vdd[0] - 5.5), u(223.0), u(p_vco_vdd[0] + 5.5), u(235.5)))
        # Underpass South VSS ring on 10 um M4 at x=341.0 into VDD_Q South ring (y=-34.0)
        add_via_45_array(rects, 341.0, 3.0, 5, 4)
        add_wire_rect(rects, "metal4", [(341.0, 3.0), (341.0, -34.0)], 10.00)
        add_via_45_array(rects, 341.0, -34.0, 5, 4)
        routed_nets += 1

        # --- Stage 2-v8: Full-Chip 20-Macro VDD/VSS Power & Ground Strapping (A-C2 Closure!) ---
        if v8_power_decap:
            # 1) ldo_v2_cur.vss (M4 @ y=424.94 > 405.0, clear of VDD_A M4!) -> MOAT_QUIET_MAIN (x=349.0 M2)
            p_ldo_vss = by_inst["ldo_v2_cur"].port_xy("vss")
            add_wire_rect(rects, "metal4", [p_ldo_vss, (349.0, p_ldo_vss[1])], 2.40)
            add_via_234_array(rects, 349.0, p_ldo_vss[1], 2, 2)

            # 2) ldo_v2_cur.host (M2 straight West @ y=429.34 clear of i_ldo0!) + bias_top_v2.vdd (M5 hop over ptat_vg M4!)
            #    + vco_ptat_bias.vdd (M4) -> VDD_BIAS West ring (x=-33, y=404)!
            p_ldo_h = by_inst["ldo_v2_cur"].port_xy("host")
            p_b_vdd = by_inst["bias_top_v2"].port_xy("vdd")
            p_p_vdd = by_inst["vco_ptat_bias"].port_xy("vdd")
            add_wire_rect(rects, "metal2", [p_ldo_h, (-1.0, p_ldo_h[1])], 1.00)
            add_via_234_array(rects, -1.0, p_ldo_h[1], 2, 2)
            add_wire_rect(rects, "metal4", [(-1.0, p_ldo_h[1]), (-1.0, 419.5)], 2.00)
            # Hop bias_top_v2.vdd over ptat_vg M4 (y=414.0) & vbg/vgi M3 on M5 -> drop onto y=420.5 M4!
            add_wire_rect(rects, "metal3", [p_b_vdd, (p_b_vdd[0], 409.5)], 1.00)
            add_via_34(rects, p_b_vdd[0], 409.5)
            add_via_45(rects, p_b_vdd[0], 409.5)
            add_wire_rect(rects, "metal5", [(p_b_vdd[0], 409.5), (p_b_vdd[0], 420.5)], 2.00)
            add_via_45(rects, p_b_vdd[0], 420.5)
            add_wire_rect(rects, "metal4", [
                p_p_vdd, (p_p_vdd[0], 420.5), (p_b_vdd[0], 420.5), (-1.0, 420.5), (-1.0, 404.0), (-33.0, 404.0),
            ], 2.00)
            add_via_45_array(rects, -33.0, 404.0, 2, 2)

            # 3) bias_top_v2.vss (M1) -> DECAP_BIAS_MID VSS M2 bus (y_vss_top, zero crossings!)
            p_b_vss = by_inst["bias_top_v2"].port_xy("vss")
            add_via_12(rects, p_b_vss[0], p_b_vss[1])
            b_mid = dp_by["DECAP_BIAS_MID"]
            add_wire_rect(rects, "metal2", [p_b_vss, (p_b_vss[0], b_mid["y_vss_top"])], 1.20)

            # 4) bias_lpf_slow.vss (M3) + bias_cml_vco.vss (M3) -> x=301.5 M3 -> y=268 M3 -> via23 onto MOAT_QUIET_MAIN (349.0 M2)
            #    (Uses M3->via23 ONLY so it passes cleanly UNDER VDD_A M4 @ x=349.0!)
            p_lpf_vss = by_inst["bias_lpf_slow"].port_xy("vss")
            p_bcv_vss = by_inst["bias_cml_vco"].port_xy("vss")
            add_wire_rect(rects, "metal3", [
                p_lpf_vss, (301.5, p_lpf_vss[1]), (301.5, p_bcv_vss[1]), p_bcv_vss,
            ], 0.80)
            add_wire_rect(rects, "metal3", [(301.5, p_bcv_vss[1]), (301.5, 268.0), (349.0, 268.0)], 1.00)
            add_via_23(rects, 349.0, 268.0)

            # 5) Quiet PLL Row VSS:
            #    - vco_r6_sym9.vss (M4) -> via34 right at (278.3, 221.4) -> M3 East to MOAT_QUIET_MAIN (349.0 M2, via23 ONLY!)
            #      (Cleanly UNDER vco_b0n/b0p M4 @ 340..346, VDD_Q M5 @ 342, AND VDD_A M4 @ 349!)
            #    - lf_k4_fused.vss (M3) -> M4 hop over lf_pref M3 (@218.0) -> M3 East @ y=221.4 (UNDER vco_vbias_q M4 @ 219!)
            p_vco_vss = by_inst["vco_r6_sym9"].port_xy("vss")
            p_lf_vss = by_inst["lf_k4_fused"].port_xy("vss")
            # Hop lf_k4_fused.vss OVER lf_pref M3 (x=188.2, y=218..256) on M4 to x=194.0, then M3 East UNDER vco_vbias_q M4 (x=219)!
            add_via_34(rects, p_lf_vss[0], p_lf_vss[1])
            add_wire_rect(rects, "metal4", [p_lf_vss, (p_lf_vss[0], 221.4), (194.0, 221.4)], 1.00)
            add_via_34(rects, 194.0, 221.4)
            add_wire_rect(rects, "metal4", [p_vco_vss, (p_vco_vss[0], 221.4)], 1.00)
            add_via_34(rects, p_vco_vss[0], 221.4)
            add_wire_rect(rects, "metal3", [(194.0, 221.4), (349.0, 221.4)], 1.00)
            add_via_23(rects, 349.0, 221.4)

            #    - cp_v4.vss (M3) + bias_cp_v2.vss (M2) -> M4 West to x=15.0 -> M2 UNDER bias M3 trunks & DECAP_BIAS_SW VDD_BIAS M4 (@-3.0!) -> West VSS ring (-14.0)
            p_cp_vss = by_inst["cp_v4"].port_xy("vss")
            p_bcp_vss = by_inst["bias_cp_v2"].port_xy("vss")
            add_via_34(rects, p_cp_vss[0], p_cp_vss[1])
            add_wire_rect(rects, "metal4", [p_cp_vss, (p_cp_vss[0], 138.0), (15.0, 138.0)], 1.40)
            add_via_234_array(rects, 15.0, 138.0, 1, 1)
            add_wire_rect(rects, "metal2", [(15.0, 138.0), (-7.0, 138.0)], 1.20)
            add_via_234_array(rects, -7.0, 138.0, 1, 2)
            add_wire_rect(rects, "metal4", [(-7.0, 138.0), (-14.0, 138.0)], 1.60)
            add_via_45_array(rects, -14.0, 138.0, 2, 2)
            add_wire_rect(rects, "metal4", [(p_bcp_vss[0], 138.0), p_bcp_vss], 1.00)
            add_via_34(rects, p_bcp_vss[0], p_bcp_vss[1])
            add_via_23(rects, p_bcp_vss[0], p_bcp_vss[1])

            #    - pfd_sc_dly.vss (M2) -> M2 cleanly UNDER DECAP_BIAS_SW VDD_BIAS M4 (@x=-3.0) to x=-7.0 -> West VSS ring (-14.0)
            p_pfd_vss = by_inst["pfd_sc_dly"].port_xy("vss")
            add_wire_rect(rects, "metal2", [p_pfd_vss, (-7.0, p_pfd_vss[1])], 0.80)
            add_via_234_array(rects, -7.0, p_pfd_vss[1], 1, 2)
            add_wire_rect(rects, "metal4", [(-7.0, p_pfd_vss[1]), (-14.0, p_pfd_vss[1])], 1.40)
            add_via_45_array(rects, -14.0, p_pfd_vss[1], 2, 2)

            # 6) Quiet PLL Row VDD_Q: 3.0 um M5 horizontal bus @ y=218.5 into VDD_Q M5 spine (x=342)!
            #    lf_k4_fused.vdd (M3) hops immediately to M4 (OVER vctrl M3 @ 140/144!) -> y=134.8 M4 -> VDD_Q spine (342)!
            add_wire_rect(rects, "metal5", [(33.0, 218.5), (342.0, 218.5)], 3.00)
            p_cp_vdd = by_inst["cp_v4"].port_xy("vdd")
            add_wire_rect(rects, "metal3", [p_cp_vdd, (p_cp_vdd[0], 205.5)], 1.00)
            add_via_34(rects, p_cp_vdd[0], 205.5)
            add_wire_rect(rects, "metal4", [(p_cp_vdd[0], 205.5), (p_cp_vdd[0], 218.5)], 1.20)
            add_via_45_array(rects, p_cp_vdd[0], 218.5, 2, 2)

            p_bcp_vcp = by_inst["bias_cp_v2"].port_xy("vcp")
            add_wire_rect(rects, "metal2", [p_bcp_vcp, (p_bcp_vcp[0], 165.0), (33.0, 165.0)], 0.80)
            add_via_23(rects, 33.0, 165.0)
            add_via_34(rects, 33.0, 165.0)
            add_wire_rect(rects, "metal4", [(33.0, 165.0), (33.0, 218.5)], 1.20)
            add_via_45_array(rects, 33.0, 218.5, 2, 2)
            # pfd_sc_dly.vdd horizontal M1 rail exits cleanly East at (30.50, 180.97) -> x=33.0 -> M4!
            add_wire_rect(rects, "metal1", [(30.50, 180.97), (33.0, 180.97)], 0.44)
            add_via_12(rects, 33.0, 180.97)
            add_via_23(rects, 33.0, 180.97)
            add_via_34(rects, 33.0, 180.97)

            p_lf_vdd = by_inst["lf_k4_fused"].port_xy("vdd")
            add_via_34(rects, p_lf_vdd[0], p_lf_vdd[1])
            add_wire_rect(rects, "metal4", [p_lf_vdd, (p_lf_vdd[0], 134.8), (342.0, 134.8)], 1.40)
            add_via_45_array(rects, 342.0, 134.8, 2, 2)

            # 7) Host Clock Column (cml2cmos_0..3, div8_saff, bias_cml_host) -> VDD_A & VSS!
            c2c_vdds = [by_inst[f"cml2cmos_{k}"].port_xy("vdd") for k in range(4)]
            c2c_vsss = [by_inst[f"cml2cmos_{k}"].port_xy("vss") for k in range(4)]
            x_c2c_vdd = c2c_vdds[0][0]
            x_c2c_vss = 413.0  # centered on cml2cmos clean M4 vss bar [406.31..415.98], 10 um clear of internal MIMs!
            # VDD_A: M5 over cml2cmos_0..3 -> y=285.0 -> via45+via34 -> M3 West UNDER c1/c5 M4 (@363.5/365.5!) -> VDD_A M4 @ x=355.0!
            add_wire_rect(rects, "metal5", [(x_c2c_vdd, c2c_vdds[0][1]), (x_c2c_vdd, 285.0)], 2.20)
            for pt in c2c_vdds:
                add_via_45_array(rects, pt[0], pt[1], 1, 2)
            add_via_45_array(rects, x_c2c_vdd, 285.0, 2, 2)
            add_via_34(rects, x_c2c_vdd, 285.0)
            add_wire_rect(rects, "metal3", [(x_c2c_vdd, 285.0), (355.0, 285.0)], 1.60)
            add_via_34(rects, 355.0, 285.0)
            p_d8_vdd = by_inst["div8_saff"].port_xy("vdd")
            add_wire_rect(rects, "metal4", [(355.0, 285.0), (355.0, 410.0)], 2.40)
            add_wire_rect(rects, "metal4", [(355.0, p_d8_vdd[1]), p_d8_vdd], 1.40)

            # VSS: M5 vertical at x=413.0 down to y=120.5 (South of cml2cmos_0>=124, North of DECAP_TX_W<=110!) -> jog West to x=403.5 -> South to y=52.5
            #      -> M4 West OVER rx_ictle/rx_vcm M3 (@400.2/401.6!) to x=368.8 -> M3 North to bias_cml_host.vss & MOAT_QUIET_MAIN (361.0)!
            add_wire_rect(rects, "metal5", [
                (x_c2c_vss, c2c_vsss[-1][1]), (x_c2c_vss, 120.5), (403.5, 120.5), (403.5, 52.5),
            ], 2.20)
            for pt in c2c_vsss:
                add_via_45_array(rects, x_c2c_vss, pt[1], 1, 2)
            p_bch_vss = by_inst["bias_cml_host"].port_xy("vss")
            add_via_45_array(rects, 403.5, 52.5, 2, 2)
            add_wire_rect(rects, "metal4", [(403.5, 52.5), (p_bch_vss[0], 52.5)], 1.60)
            add_via_34(rects, p_bch_vss[0], 52.5)
            add_wire_rect(rects, "metal3", [(p_bch_vss[0], 52.5), p_bch_vss, (361.0, p_bch_vss[1])], 1.20)
            add_via_23(rects, 361.0, p_bch_vss[1])
            # div8_saff.vss (M4 @ (369.6, 297.26)): drop via34 RIGHT AT (369.6, 297.26) (strictly East of div8_saff West M4 vdd bar 368.1..368.9!)
            # then run M3 straight West under div8_saff.vdd & c1/c5 M4 -> MOAT_QUIET_MAIN (361.0 M2)!
            p_d8_vss = by_inst["div8_saff"].port_xy("vss")
            add_via_34(rects, p_d8_vss[0], p_d8_vss[1])
            add_wire_rect(rects, "metal3", [p_d8_vss, (361.0, p_d8_vss[1])], 1.00)
            add_via_23(rects, 361.0, p_d8_vss[1])

            # 8) TX (tx_sst_top & tx_qdiv2) -> VDD_TX & VSS (strictly clear of tx_dig M3 trunk x=[597.5..611.0]!)
            p_tx_vdd = by_inst["tx_sst_top"].port_xy("vdd")
            p_tx_vss = by_inst["tx_sst_top"].port_xy("vss")
            # Merge cleanly into tx_sst_top internal M5 vdd rail [448.82..451.22] x [142.82..145.22] (zero met5.2 notch!)
            add_wire_rect(rects, "metal5", [(449.5, p_tx_vdd[1]), (443.0, p_tx_vdd[1])], 2.40)
            add_wire_rect(rects, "metal5", [(443.0, p_tx_vdd[1]), (443.0, -2.5)], 3.20)
            add_via_45_array(rects, 443.0, -2.5, 2, 2)
            add_wire_rect(rects, "metal4", [(443.0, -2.5), (443.0, -34.0)], 5.00)
            add_via_45_array(rects, 443.0, -34.0, 3, 3)

            # Fly tx_sst_top.vss (over 0%-M5 tx_qdiv2!), tx_qdiv2.vss, AND rx_cmos_top.vss straight East on M5 @ y=280.6 into East VSS ring (x=887)!
            # Strictly NORTH of DECAP_RX_NE M5 (<=276.47 -> 2.9 um gap!), tx_qdiv2.vdd (y<=271.82) & rx_cmos_top.vdd (y=251.5)!
            p_txq_vdd = by_inst["tx_qdiv2"].port_xy("vdd")
            p_txq_vss = by_inst["tx_qdiv2"].port_xy("vss")
            y_txrx_vss = 280.60
            add_wire_rect(rects, "metal5", [p_tx_vss, (p_tx_vss[0], y_txrx_vss), (887.0, y_txrx_vss)], 2.40)
            # Drop via34+via45 at y=279.27 (strictly South of clk_c0 M3 @280.58!) and jog North ONLY on metal5!
            add_wire_rect(rects, "metal3", [p_txq_vss, (588.0, p_txq_vss[1])], 1.00)
            add_via_34(rects, 588.0, p_txq_vss[1])
            add_via_45(rects, 588.0, p_txq_vss[1])
            add_wire_rect(rects, "metal5", [(588.0, p_txq_vss[1]), (588.0, y_txrx_vss)], 2.00)

            # tx_qdiv2.vdd: hop to M5 at x=583.0 (West of tx_dig!) -> fly straight East & South on M5 into DECAP_TX_E M5 trunk (x=604.0)!
            add_wire_rect(rects, "metal3", [p_txq_vdd, (583.0, p_txq_vdd[1])], 1.00)
            add_via_34(rects, 583.0, p_txq_vdd[1])
            add_via_45(rects, 583.0, p_txq_vdd[1])
            b_txe = dp_by["DECAP_TX_E"]
            add_wire_rect(rects, "metal5", [(583.0, p_txq_vdd[1]), (604.0, p_txq_vdd[1]), (604.0, b_txe["y_vdd_0"])], 2.40)

            # 9) RX (rx_cmos_top) -> VDD_RX East ring (M5 @ y=251.5 stops at x=876.0 -> 2.2 um clear of East VSS>=879.0!) & VSS -> M5 North to y=279.27!
            p_rx_vdd = by_inst["rx_cmos_top"].port_xy("vdd")
            p_rx_vss = by_inst["rx_cmos_top"].port_xy("vss")
            add_wire_rect(rects, "metal5", [p_rx_vdd, (p_rx_vdd[0], 251.5), (876.0, 251.5)], 2.00)
            add_via_45_array(rects, 876.0, 251.5, 1, 2)
            add_wire_rect(rects, "metal4", [(876.0, 251.5), (906.0, 251.5)], 3.20)
            add_via_45_array(rects, 906.0, 251.5, 3, 2)

            add_wire_rect(rects, "metal5", [p_rx_vss, (p_rx_vss[0], y_txrx_vss)], 2.40)

            # 10) Digital Top v3 (8x East VGND M5 -> East VSS ring + 8x East VPWR M5->M4->M5 -> East VDD_D ring!)
            dig_m = by_inst["digital_top_v3"]
            x_dig_tap = grid(dig_m.x + dig_m.w - 4.5)
            for y_loc in (267.2, 231.2, 195.2, 159.2, 123.2, 87.2, 51.2, 15.2):
                yc = grid(dig_m.y + y_loc)
                add_wire_rect(rects, "metal5", [(x_dig_tap, yc), (887.0, yc)], 2.00)
            for y_loc in (285.2, 249.2, 213.2, 177.2, 141.2, 105.2, 69.2, 33.2):
                yc = grid(dig_m.y + y_loc)
                add_wire_rect(rects, "metal5", [(x_dig_tap, yc), (860.0, yc)], 2.00)
                add_via_45_array(rects, 860.0, yc, 2, 2)
                add_wire_rect(rects, "metal4", [(860.0, yc), (906.0, yc)], 2.40)
                add_via_45_array(rects, 906.0, yc, 2, 2)
            routed_nets += 34

        # --- Route 6: South-Edge High-Speed Differential Pad Exits (TX_PAD_P/N 3.0 um EM-Hardened & RX_IN_N/P) ---
        # 6a) TX SST Top (pad_p/pad_n, M4 at (471.4, 1.2) and (474.4, 1.2)): flare at y=-4.0 then 3.0 um M4 -> 2x2 via4 -> M5 pads!
        for sp, x_pad, ext_lbl in (("pad_p", 468.5, "TX_PAD_P"), ("pad_n", 477.3, "TX_PAD_N")):
            px, py = tx.port_xy(sp)
            add_wire_rect(rects, "metal4", [(px, py), (px, -4.0), (x_pad, -4.0)], 1.80)
            add_wire_rect(rects, "metal4", [(x_pad, -4.0), (x_pad, -46.5)], 3.00)
            add_via_45_array(rects, x_pad, -46.5, 2, 2)
            rects.setdefault("metal5", []).append((u(x_pad - 2.6), u(-54.0), u(x_pad + 2.6), u(-44.0)))
            labels.append(("metal5", u(x_pad - 1.2), u(-52.0), u(x_pad + 1.2), u(-47.0), ext_lbl, len(labels) + 1))
            routed_nets += 1

        # 6b) RX CMOS Top (rxn/rxp, M5 at (665.5, 0.9) and (670.3, 0.9)):
        #     Exit South on 1.80 um M5 -> via4 at y=-3.6 (clear of VSS y=-7.0!) -> M4 under VSS & VDD_RX -> 2x2 via4 -> M5 bondpads!
        for sp, x_pad, ext_lbl in (("rxn", 663.5, "RX_IN_N"), ("rxp", 672.3, "RX_IN_P")):
            px, py = rx.port_xy(sp)
            add_wire_rect(rects, "metal5", [(px, py), (px, -3.6)], 1.80)
            add_via_45(rects, px, -3.6)
            add_wire_rect(rects, "metal4", [(px, -3.6), (px, -40.5), (x_pad, -40.5), (x_pad, -46.5)], 1.80)
            add_via_45_array(rects, x_pad, -46.5, 2, 2)
            rects.setdefault("metal5", []).append((u(x_pad - 2.6), u(-54.0), u(x_pad + 2.6), u(-44.0)))
            labels.append(("metal5", u(x_pad - 1.2), u(-52.0), u(x_pad + 1.2), u(-47.0), ext_lbl, len(labels) + 1))
            routed_nets += 1

    # Add top-level power & reference clock perimeter ports (full_v4 widened ring centers)
    top_ports = [
        ("metal5", -14.0, 300.0, "VSS"),
        ("metal5", -33.0, 520.0, "VDD_HV33"),
        ("metal5", -33.0, 315.0, "VDD_BIAS"),
        ("metal5", -33.0, 105.0, "VDD_Q"),
        ("metal5", 420.0, 634.0, "VDD_A"),
        ("metal5", 680.0, 634.0, "VDD_D"),
        ("metal5", 906.0, 140.0, "VDD_RX"),
        ("metal5", 431.0, -34.0, "VDD_TX"),
    ]
    for lyr, px, py, name in top_ports:
        labels.append((lyr, u(px - 1.0), u(py - 1.0), u(px + 1.0), u(py + 1.0), name, len(labels) + 1))

    # Write hierarchical .mag file
    mag_lines = [
        "magic",
        "tech sky130A",
        "magscale 1 2",
        "timestamp 0",
    ]
    for lyr in sorted(rects):
        mag_lines.append(f"<< {lyr} >>")
        for x1, y1, x2, y2 in rects[lyr]:
            if x2 > x1 and y2 > y1:
                mag_lines.append(f"rect {x1} {y1} {x2} {y2}")
    mag_lines.extend(uses)
    mag_lines.append("<< labels >>")
    for lyr, x1, y1, x2, y2, name, pnum in labels:
        mag_lines.append(f"rlabel {lyr} {x1} {y1} {x2} {y2} 0 {name}")
        if pnum is not None:
            mag_lines.append(f"port {pnum} nsew")
    mag_lines.append("<< end >>")
    top_mag = work / f"{top_name}.mag"
    top_mag.write_text("\n".join(mag_lines) + "\n")
    print(f"[chip_top] Wrote {top_mag.relative_to(REPO)} ({len(macros)} macros, {total_decap_tiles} damped decap tiles, {routed_nets} top routed nets)")

    # 3. Magic Top-Level Full-Rule DRC & Merged GDSII Export
    drc_total = None
    drc_rules = []
    gds_bytes = 0
    if run_drc or export_gds:
        tcl = work / "_verify_and_gds.tcl"
        cmds = [
            "drc off",
            f"cd {work}",
            f"load {top_name}",
            "select top cell",
            'puts "TOP_BOX [box values]"',
        ]
        if run_drc:
            cmds += [
                "drc on",
                "drc style drc(full)",
                "drc check",
                "drc catchup",
                'puts "TOP_DRC_TOTAL [drc list count total]"',
                'foreach {why boxes} [drc listall why] { puts "TOP_DRC_RULE [llength $boxes] | $why" }',
            ]
        if export_gds:
            cmds += [
                "drc off",
                "gds noduplicates true",
                f"gds write {top_name}.gds",
                'puts "GDS_WRITTEN OK"',
            ]
        # Real hierarchical Magic extraction (catches top-to-macro internal metal shorts invisible to DRC & rect-only checks!)
        cmds += [
            "drc off",
            "extract all",
            "ext2spice lvs",
            f"ext2spice -o {top_name}_lvs.spice",
            'puts "TOP_EXT2SPICE_OK"',
            "quit -noprompt",
        ]
        tcl.write_text("\n".join(cmds) + "\n")
        t0 = time.time()
        res = mu.run_magic(tcl, cwd=work)
        (work / "magic_top.log").write_text(res.log)
        m_drc = re.search(r"TOP_DRC_TOTAL (\d+)", res.log)
        if m_drc:
            drc_total = int(m_drc.group(1))
        for m_r in re.finditer(r"TOP_DRC_RULE (\d+) \| (.+)", res.log):
            drc_rules.append({"count": int(m_r.group(1)), "rule": m_r.group(2).strip()})
        gds_path = work / f"{top_name}.gds"
        if gds_path.exists():
            gds_bytes = gds_path.stat().st_size
        print(f"[magic_top] elapsed={time.time()-t0:.1f}s | DRC_TOTAL={drc_total} ({len(drc_rules)} rules) | GDS={gds_bytes/1048576:.2f} MB")
        for r in drc_rules[:12]:
            print(f"    DRC {r['count']:4d} | {r['rule']}")

    # Parse real Magic hierarchical extracted subckt connections to prove ZERO top-to-macro internal shorts!
    hier_audit = None
    lvs_spice = work / f"{top_name}_lvs.spice"
    if stage == "full" and lvs_spice.exists():
        # Join SPICE continuation lines (+)
        joined: list[str] = []
        for raw_ln in lvs_spice.read_text().splitlines():
            s_ln = raw_ln.strip()
            if not s_ln or s_ln.startswith("*"):
                continue
            if s_ln.startswith("+") and joined:
                joined[-1] += " " + s_ln[1:].strip()
            else:
                joined.append(s_ln)
        sub_ports: dict[str, list[str]] = {}
        inst_nets: dict[str, dict[str, str]] = {}
        in_top = False
        for ln in joined:
            low = ln.lower()
            if low.startswith(".subckt "):
                toks = ln.split()
                sub_ports[toks[1]] = toks[2:]
                in_top = (toks[1] == top_name)
            elif low.startswith(".ends"):
                in_top = False
            elif in_top and ln.startswith("X"):
                toks = ln.split()
                inst = toks[0][1:]
                cell = toks[-1]
                nets = toks[1:-1]
                pnames = sub_ports.get(cell, [])
                if len(pnames) == len(nets):
                    inst_nets[inst] = dict(zip(pnames, nets))

        def get_net(inst: str, port: str) -> str | None:
            return inst_nets.get(inst, {}).get(port)

        # Verify ALL 4 previously-hidden C1 hard shorts + critical bias/clock links are cleanly connected & unshorted!
        must_connect = [
            ("vbg_ldo", ("bias_top_v2", "vbg"), ("ldo_v2_cur", "bg")),
            ("vbg_tx", ("bias_top_v2", "vbg"), ("tx_sst_top", "vbg")),
            ("i_ldo0", ("bias_top_v2", "i_ldo0"), ("ldo_v2_cur", "i_ldo")),
            ("i_ldo1", ("bias_top_v2", "i_ldo1"), ("cp_v4", "ibias")),
            ("c1_div8", ("cml2cmos_3", "outp"), ("div8_saff", "clkp")),
            ("c5_div8", ("cml2cmos_3", "outn"), ("div8_saff", "clkn")),
            ("c6_rx", ("cml2cmos_0", "outn"), ("rx_cmos_top", "c6")),
            ("c7_rx", ("cml2cmos_1", "outn"), ("rx_cmos_top", "c7")),
            ("tx_d0", ("digital_top_v3", "tx_capture_data[0]"), ("tx_sst_top", "din0")),
            ("fb250", ("div8_saff", "q8p"), ("pfd_sc_dly", "fb")),
            ("vctrl", ("cp_v4", "out"), ("vco_r6_sym9", "ctrl")),
        ]
        must_differ = [
            ("vbg_vs_ldo_vss", ("bias_top_v2", "vbg"), ("ldo_v2_cur", "vss")),
            ("c1_vs_div8_vdd", ("div8_saff", "clkp"), ("div8_saff", "vdd")),
            ("c5_vs_div8_vdd", ("div8_saff", "clkn"), ("div8_saff", "vdd")),
            ("c1_vs_c5", ("div8_saff", "clkp"), ("div8_saff", "clkn")),
            ("c6_vs_tx_vdd", ("cml2cmos_0", "outn"), ("tx_sst_top", "vdd")),
            ("c7_vs_tx_vdd", ("cml2cmos_1", "outn"), ("tx_sst_top", "vdd")),
            ("c6_vs_tx_vdrv", ("cml2cmos_0", "outn"), ("tx_sst_top", "vdrv")),
            ("c7_vs_tx_vdrv", ("cml2cmos_1", "outn"), ("tx_sst_top", "vdrv")),
            ("tx_vdd_vs_vdrv", ("tx_sst_top", "vdd"), ("tx_sst_top", "vdrv")),
            ("tx_d0_vs_tx_vss", ("tx_sst_top", "din0"), ("tx_sst_top", "vss")),
            ("i_ldo0_vs_ldo_vss", ("ldo_v2_cur", "i_ldo"), ("ldo_v2_cur", "vss")),
            ("i_ldo1_vs_cp_vss", ("cp_v4", "ibias"), ("cp_v4", "vss")),
            ("i_ldo1_vs_cp_vbn", ("cp_v4", "ibias"), ("cp_v4", "vbn")),
            ("cp_vbn_vs_cp_vss", ("cp_v4", "vbn"), ("cp_v4", "vss")),
            ("fb250_vs_pfd_vss", ("pfd_sc_dly", "fb"), ("pfd_sc_dly", "vss")),
            ("rx_ictle_vs_vss", ("rx_cmos_top", "ibias_ctle"), ("rx_cmos_top", "vss")),
            ("rx_vcm_vs_vss", ("rx_cmos_top", "vcm_ref"), ("rx_cmos_top", "vss")),
        ]
        if v8_power_decap:
            # Verify ALL 20 macros' VSS/VGND tied to common VSS AND ALL 18 macros' VDD/VPWR tied to exact domain rails!
            for inst_vss, port_vss in [
                ("ldo_v2_cur", "vss"), ("bias_top_v2", "vss"), ("bias_lpf_slow", "vss"),
                ("bias_cml_vco", "vss"), ("pfd_sc_dly", "vss"), ("bias_cp_v2", "vss"),
                ("cp_v4", "vss"), ("lf_k4_fused", "vss"), ("vco_r6_sym9", "vss"),
                ("cml2cmos_0", "vss"), ("cml2cmos_1", "vss"), ("cml2cmos_2", "vss"),
                ("cml2cmos_3", "vss"), ("bias_cml_host", "vss"), ("div8_saff", "vss"),
                ("tx_sst_top", "vss"), ("tx_qdiv2", "vss"), ("rx_cmos_top", "vss"),
                ("digital_top_v3", "VGND"),
            ]:
                must_connect.append((f"vss_{inst_vss}", (inst_vss, port_vss), ("ldo_v2_cur", "vss")))
            must_connect.extend([
                ("vdd_bias_ldo_host", ("ldo_v2_cur", "host"), ("bias_top_v2", "vdd")),
                ("vdd_bias_ptat", ("vco_ptat_bias", "vdd"), ("bias_top_v2", "vdd")),
                ("vdd_q_vco", ("vco_r6_sym9", "vdd_q"), ("ldo_v2_cur", "quiet")),
                ("vdd_q_cp", ("cp_v4", "vdd"), ("ldo_v2_cur", "quiet")),
                ("vdd_q_bcp", ("bias_cp_v2", "vcp"), ("ldo_v2_cur", "quiet")),
                ("vdd_q_lf", ("lf_k4_fused", "vdd"), ("ldo_v2_cur", "quiet")),
                ("vdd_q_pfd", ("pfd_sc_dly", "vdd"), ("ldo_v2_cur", "quiet")),
                ("vdd_a_c0", ("cml2cmos_0", "vdd"), ("div8_saff", "vdd")),
                ("vdd_a_c1", ("cml2cmos_1", "vdd"), ("div8_saff", "vdd")),
                ("vdd_a_c2", ("cml2cmos_2", "vdd"), ("div8_saff", "vdd")),
                ("vdd_a_c3", ("cml2cmos_3", "vdd"), ("div8_saff", "vdd")),
                ("vdd_tx_qdiv", ("tx_qdiv2", "vdd"), ("tx_sst_top", "vdd")),
            ])
            dom_reps = [
                ("HV33", ("ldo_v2_cur", "vin")),
                ("BIAS", ("bias_top_v2", "vdd")),
                ("VDDQ", ("ldo_v2_cur", "quiet")),
                ("VDDA", ("div8_saff", "vdd")),
                ("VDDTX", ("tx_sst_top", "vdd")),
                ("VDDRX", ("rx_cmos_top", "vdd")),
                ("VDDD", ("digital_top_v3", "VPWR")),
                ("VSS", ("ldo_v2_cur", "vss")),
            ]
            for idx_a in range(len(dom_reps)):
                for idx_b in range(idx_a + 1, len(dom_reps)):
                    na, pa = dom_reps[idx_a]
                    nb, pb = dom_reps[idx_b]
                    must_differ.append((f"dom_{na}_vs_{nb}", pa, pb))
        hier_opens = []
        for tag, (i1, p1), (i2, p2) in must_connect:
            n1, n2 = get_net(i1, p1), get_net(i2, p2)
            if not n1 or not n2 or n1 != n2:
                hier_opens.append(f"{tag}: {i1}.{p1}={n1} != {i2}.{p2}={n2}")
        hier_shorts = []
        for tag, (i1, p1), (i2, p2) in must_differ:
            n1, n2 = get_net(i1, p1), get_net(i2, p2)
            if n1 and n2 and n1 == n2:
                hier_shorts.append(f"{tag}: {i1}.{p1} == {i2}.{p2} == {n1}")
        hier_audit = {
            "extracted_instances": len(inst_nets),
            "must_connect_checked": len(must_connect),
            "must_differ_checked": len(must_differ),
            "hier_opens": hier_opens,
            "hier_shorts": hier_shorts,
        }
        print(
            f"[magic_hier_lvs_audit] instances={len(inst_nets)} | "
            f"hier_opens={len(hier_opens)}/{len(must_connect)} | "
            f"hier_shorts={len(hier_shorts)}/{len(must_differ)}"
        )
        for msg in hier_opens + hier_shorts:
            print(f"    HIER_FAIL: {msg}")

    summary = {
        "cell": top_name,
        "stage": stage,
        "macro_count": len(macros),
        "decap_banks": len(decap_placements),
        "decap_tiles_total": total_decap_tiles,
        "decap_unit_drc": decap_unit_drc_val,
        "v8_power_decap": v8_power_decap,
        "routed_top_nets": routed_nets,
        "top_connectivity": audit_top_connectivity(rects, macros, decap_placements) if stage == "full" else None,
        "magic_hier_audit": hier_audit,
        "top_drc_total": drc_total,
        "top_drc_rules": drc_rules,
        "gds_bytes": gds_bytes,
        "floorplan_kpi": kpi,
        "decap_placements": decap_placements,
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=REPO / "results/layout/chip_top_20261123")
    ap.add_argument("--stage", choices=("floorplan", "full"), default="full")
    ap.add_argument("--no-gds", action="store_true")
    ap.add_argument("--no-drc", action="store_true")
    ap.add_argument("--legacy-macros", action="store_true", help="Use v1.0 digital_top_v3 and single-layer bias_lpf_slow")
    ap.add_argument("--v8-power-decap", action="store_true", help="Enable full_v8 hybrid MIM+MOS decap (275 pF) + all 20-macro VDD/VSS strapping")
    args = ap.parse_args()
    build_chip_top(
        args.output_dir.resolve(),
        stage=args.stage,
        export_gds=not args.no_gds,
        run_drc=not args.no_drc,
        use_v32_digital=not args.legacy_macros,
        use_stacked_lpf=not args.legacy_macros,
        use_v5_review_macros=not args.legacy_macros,
        v8_power_decap=args.v8_power_decap,
    )


if __name__ == "__main__":
    main()
