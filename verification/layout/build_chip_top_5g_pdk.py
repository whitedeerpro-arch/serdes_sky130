#!/usr/bin/env python3
"""Real Physical 5G SerDes Chip-Top Assembler, Multi-Layer Router & Verifier (`serdes_5g_top_pdk`, Plan B / Plan C).

Assembles ALL 13 real verified SKY130A 5G PDK macros + 8 compacted 5G Direct/Damped/HV33 hybrid
decap banks (`decap_5g_tiles.py`, 20.8 x 17.2 um, DRC=0) into a hierarchical Magic `.mag` chip top
(`936 x 642 um = 0.6009 mm^2` for Plan C `v4p1`, `-22.7%` vs Plan A), wires:
  - Closed 14 um M5 VSS perimeter ring + Dual P+ Substrate Guard Moat (`x=387, 397`)
  - 7 separated outer M5 supply rails (`VDD_HV33`, `VDD_BIAS`, `VDD_Q`, `VDD_A`, `VDD_D`, `VDD_RX`, `VDD_TX`)
  - 13/13 macros' VDD & VSS power straps + 8/8 decap banks tied to exact domains
  - Pragmatic multi-layer signal routing:
      * 2L M4 straight-needle (`0` crossings, `0` vias) for RX 33-bit data/edge/clock bus
      * 3L M2/M3/M4 stacked routing for TX 17-bit data bus & 24-bit RX PI control (`a/b/f`)
      * Mirror-symmetric 2.5 GHz CML I/Q (`lc_vco_oct -> clk_host_5g`), 2.5 GHz CMOS I/Q
        (`clk_host_5g -> rx_top_5g / tx_qdiv2_5g / div_ab_5g_v2`), and 1.25 GHz 4-phase TX clocks
      * Full PLL loop (`pfd -> cp_v4 -> lf_k4 -> lc_vco_oct`, `div_ab_5g_v2.fb250 -> pfd.fb`)
      * Complete BIAS distribution (`vbg`, `i_ldo0`, `i_ldo1`, `icp/vbn/vbp`, `icml`, `ictle`, `vcm`, `pref`)
      * 90-degree orthogonal South `TX_PAD_P/N` & East `RX_IN_P/N` differential pad exits
  - Fast Python Union-Find + spacing/overlap pre-audit (`<1s`) + real Magic `drc(full)` (`--drc`)
    + real Magic hierarchical `extract all; ext2spice lvs` connectivity/short proof (`--extract`).

ZERO ngspice required. Preserves all frozen 4G and baseline files untouched.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for p in (HERE, REPO / "analog/tx/sst/layout"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_chip_top_pdk as b4g  # noqa: E402
import decap_5g_tiles as d5g  # noqa: E402
import magicutil as mu  # noqa: E402
from sst_layout_common import grid  # noqa: E402

SCALE = 200  # 5 nm grid


def u(um: float) -> int:
    return int(round(um * SCALE))


@dataclass
class MacroMeta:
    inst: str
    cell_name: str
    mag_rel: str
    extra_mags: list[str]
    bbox_orig: tuple[float, float, float, float]
    ports_raw: dict[str, tuple[float, float, str]]  # name -> (raw_x, raw_y, layer)
    x: float
    y: float
    orient: str
    domain: str
    group: str
    color: str
    is_digital: bool = False
    gds_rel: str = ""
    def_rel: str = ""

    @property
    def w(self) -> float:
        w0 = self.bbox_orig[2] - self.bbox_orig[0]
        h0 = self.bbox_orig[3] - self.bbox_orig[1]
        return h0 if self.orient in ("R90", "R270", "R90_MX", "R270_MX") else w0

    @property
    def h(self) -> float:
        w0 = self.bbox_orig[2] - self.bbox_orig[0]
        h0 = self.bbox_orig[3] - self.bbox_orig[1]
        return w0 if self.orient in ("R90", "R270", "R90_MX", "R270_MX") else h0

    @property
    def tf(self) -> tuple[int, int, int, int, int, int]:
        return b4g.magic_transform(self.bbox_orig, self.x, self.y, self.orient)

    def world_pt(self, raw_x: float, raw_y: float) -> tuple[float, float]:
        a, b, c, d, e, f = self.tf
        wx = (a * raw_x * SCALE + b * raw_y * SCALE + c) / SCALE
        wy = (d * raw_x * SCALE + e * raw_y * SCALE + f) / SCALE
        return (round(wx, 3), round(wy, 3))

    def port_world(self, pname: str) -> tuple[float, float, str]:
        rx, ry, lyr = self.ports_raw[pname]
        wx, wy = self.world_pt(rx, ry)
        return (wx, wy, lyr)


@dataclass
class DecapBank:
    name: str
    domain: str
    x: float
    y: float
    w: float
    h: float
    damp_mode: str = "50pct"


def parse_mag_bbox_and_ports(
    mag_path: Path,
) -> tuple[tuple[float, float, float, float], dict[str, tuple[float, float, str]]]:
    """Parse exact bounding box (including hierarchical child `use` bboxes!) and labeled ports."""
    lines = mag_path.read_text().splitlines()
    scale_um = 0.005
    for ln in lines[:20]:
        if ln.startswith("magscale "):
            ps = ln.split()
            scale_um = 0.01 * float(ps[1]) / float(ps[2])
            break

    x0 = y0 = 1e18
    x1 = y1 = -1e18
    cur = None
    ports: dict[str, tuple[float, float, str]] = {}

    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("<< ") and s.endswith(" >>"):
            cur = s[3:-3]
        elif s.startswith("rect ") and cur not in ("labels", "properties", "end"):
            _, ax, ay, bx, by = s.split()
            x0 = min(x0, int(ax) * scale_um)
            y0 = min(y0, int(ay) * scale_um)
            x1 = max(x1, int(bx) * scale_um)
            y1 = max(y1, int(by) * scale_um)
        elif s.startswith("use "):
            tf = (1, 0, 0, 0, 1, 0)
            cbox = None
            j = i + 1
            while j < len(lines) and j < i + 6:
                sj = lines[j].strip()
                if sj.startswith("transform "):
                    tf = tuple(int(v) for v in sj.split()[1:7])
                elif sj.startswith("box "):
                    cbox = tuple(int(v) for v in sj.split()[1:5])
                    break
                j += 1
            if cbox is not None:
                a, b, c, d, e, f = tf
                for cx in (cbox[0], cbox[2]):
                    for cy in (cbox[1], cbox[3]):
                        wx = (a * cx + b * cy + c) * scale_um
                        wy = (d * cx + e * cy + f) * scale_um
                        x0, x1 = min(x0, wx), max(x1, wx)
                        y0, y1 = min(y0, wy), max(y1, wy)
        elif (s.startswith("flabel ") or s.startswith("rlabel ")) and i + 1 < len(lines) and lines[i + 1].strip().startswith("port "):
            ps = s.split()
            lyr = ps[1]
            cx = (int(ps[2]) + int(ps[4])) * 0.5 * scale_um
            cy = (int(ps[3]) + int(ps[5])) * 0.5 * scale_um
            ports[ps[-1]] = (round(cx, 3), round(cy, 3), lyr)
        i += 1

    return (round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3)), ports


def parse_def_bbox_and_ports(def_path: Path) -> tuple[tuple[float, float, float, float], dict[str, tuple[float, float, str]]]:
    txt = def_path.read_text()
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", txt).group(1))
    m_die = re.search(r"DIEAREA \(\s*([-\d]+)\s+([-\d]+)\s*\)\s*\(\s*([-\d]+)\s+([-\d]+)\s*\)", txt)
    bx0, by0, bx1, by1 = (int(v) / units for v in m_die.groups())
    pins_blk = re.search(r"PINS \d+ ;(.*?)END PINS", txt, re.S).group(1)
    lmap = {"met1": "metal1", "met2": "metal2", "met3": "metal3", "met4": "metal4", "met5": "metal5"}
    ports: dict[str, tuple[float, float, str]] = {}
    for m in re.finditer(
        r"-\s+(\S+)\s+\+\s+NET\s+\S+.*?\+\s+LAYER\s+(\S+).*?\+\s+(?:PLACED|FIXED)\s+\(\s*([-\d]+)\s+([-\d]+)\s*\)",
        pins_blk, re.S,
    ):
        pname, lay, px, py = m.group(1), m.group(2), int(m.group(3)) / units, int(m.group(4)) / units
        ports[pname] = (round(px, 3), round(py, 3), lmap.get(lay, lay))
    return (round(bx0, 3), round(by0, 3), round(bx1, 3), round(by1, 3)), ports


def prepare_digital_proxy_v4(work: Path, gds_rel: str, cell_name: str = "serdes_digital_top_v4") -> Path:
    out_mag = work / f"{cell_name}.mag"
    gds = REPO / gds_rel
    assert gds.exists(), f"Missing digital GDS: {gds}"
    tcl = work / "_import_digital_v4.tcl"
    tcl.write_text("\n".join([
        "drc off",
        f"cd {work}",
        "gds readonly true",
        "gds rescale false",
        f"gds read {gds}",
        f"load {cell_name}",
        f"save {cell_name}",
        "quit -noprompt",
    ]) + "\n")
    t0 = time.time()
    res = mu.run_magic(tcl, cwd=work)
    res.need(f"import {cell_name}.gds")
    print(f"[digital_proxy] Imported {gds.relative_to(REPO)} -> {out_mag.name} in {time.time()-t0:.2f}s", flush=True)
    return out_mag


def count_1d_crossings(pairs: list[tuple[float, float]]) -> int:
    s = sorted(pairs, key=lambda p: p[0])
    cnt = 0
    for i in range(len(s)):
        for j in range(i + 1, len(s)):
            if s[i][1] > s[j][1] + 1e-4:
                cnt += 1
    return cnt


def build_5g_floorplan_spec(digital_variant: str = "v4p1") -> tuple[float, float, list[MacroMeta], list[DecapBank]]:
    """Construct exact Plan-C (v4p1) zero-overlap, zero-alley-conflict 5G chip-top spec."""
    if digital_variant != "v4p1":
        raise ValueError(
            f"Unsupported digital_variant={digital_variant!r}; only 'v4p1' (hd_pnr_v4p1_5g_coopt) is supported."
        )
    dig_dir = "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4"
    dig_def = REPO / dig_dir / "serdes_digital_top_v4.def"
    dig_gds_rel = f"{dig_dir}/serdes_digital_top_v4.gds"
    dig_def_rel = f"{dig_dir}/serdes_digital_top_v4.def"
    dig_bb, dig_ports = parse_def_bbox_and_ports(dig_def)
    dig_w, dig_h = dig_bb[2] - dig_bb[0], dig_bb[3] - dig_bb[1]

    def mk(inst, cell_name, mag_rel, x, y, orient, domain, group, color, extra_mags=None):
        bb, pts = parse_mag_bbox_and_ports(REPO / mag_rel)
        return MacroMeta(
            inst=inst, cell_name=cell_name, mag_rel=mag_rel, extra_mags=extra_mags or [],
            bbox_orig=bb, ports_raw=pts, x=x, y=y, orient=orient,
            domain=domain, group=group, color=color,
        )

    # Plan C (`936 x 642 um = 0.6009 mm^2`, -22.7% vs Plan A):
    # Preserves EXACT rx_x - dig_x = 70.0 um alignment so all 33 RX data/edge/clk pins have 0 crossings!
    # Widens:
    #   - West-of-moat VDD_Q Kelvin spine: x=[372.5..385.5] (13 um)
    #   - East-of-moat fb250/VDD_TX alley: x=[398.5..408.0] (9.5 um)
    #   - clk_host <-> tx_qdiv2 alley:     x=[500.0..514.0] (14.0 um)
    #   - tx_qdiv2 <-> digital alley:      x=[532.0..544.0] (12.0 um)
    #   - TX<->RX mid-channel (y=257..282): 24.6 um tall
    #   - South-of-RX PI-ctrl channel (y=38..58): 20.0 um tall
    x_dig = 544.0
    x_rx = 614.0
    y_dig = 290.0
    core_h = round(max(650.0, y_dig + dig_h + 6.0), 1)
    core_w = round(max(936.0, x_dig + dig_w + 6.0), 1)

    macros: list[MacroMeta] = [
        # --- WEST QUIET ANALOG ISLAND (x = 0 .. 372.5) ---
        mk("ldo_kelvin", "serdes_pll_supply_hv18_v2_cur_pdk",
           "analog/ldo/layout/variants/v2_cur_kelvin_pdk/serdes_pll_supply_hv18_v2_cur_pdk.mag",
           0.0, core_h - 124.0, "R0", "vdd_hv33", "LDO", "#fed9a6"),
        mk("lc_vco_oct", "vco5g_lc_div2_oct_pdk",
           "analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/vco5g_lc_div2_oct_pdk.mag",
           0.0, 210.0, "R90", "vdd_q", "LC-VCO (R90)", "#fbb4ae",
           extra_mags=[
               "analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/vco5g_lc_active_div2_oct_pdk.mag",
               "analog/pll/vco_5g/layout/variants/ind_oct_2n5_pdk/vco5g_ind_oct_2n5_pdk.mag",
           ]),
        mk("bias_top_v2", "serdes_bias_top_v2_pdk",
           "analog/bias/layout/variants/v2_pdk/serdes_bias_top_v2_pdk.mag",
           0.0, 0.0, "MX", "vdd_bias", "BIAS", "#e5d8bd"),
        mk("lf_k4", "pll_loop_filter_k4_fused_pdk",
           "analog/pll/loop_filter/layout/variants/fused_pdk/pll_loop_filter_k4_fused_pdk.mag",
           248.0, 132.0, "R180", "vdd_q", "PLL", "#ccebc5"),
        mk("cp_v4", "pll_cp_steer_v4_pdk",
           "analog/pll/cp/layout/variants/v4_pdk/pll_cp_steer_v4_pdk.mag",
           182.0, 142.0, "R0", "vdd_q", "PLL", "#ccebc5"),
        mk("pfd", "pll_pfd_sc_dly_pdk",
           "analog/pll/pfd/layout/variants/pdk/pll_pfd_sc_dly_pdk.mag",
           152.0, 172.0, "R0", "vdd_q", "PLL", "#ccebc5"),
        mk("bias_cp", "serdes_bias_cp_v2_pdk",
           "analog/bias/layout/variants/v2_pdk/serdes_bias_cp_v2_pdk.mag",
           180.0, 128.0, "R0", "vdd_q", "PLL", "#ccebc5"),

        # --- EAST HIGH-SPEED CLOCK, TX, RX & DIGITAL BAY (x = 408 .. core_w) ---
        mk("clk_host_5g", "serdes_5g_cml_clock_host",
           "results/layout/decap_release_20261125_fvy2da/clock_host_5g/serdes_5g_cml_clock_host.mag",
           408.0, 310.0, "R0", "vdd_a", "CLK 5G", "#decbe4",
           extra_mags=[
               "results/layout/decap_release_20261125_fvy2da/clock_host_5g/serdes_bias_cml_v2_pdk.mag",
               "results/layout/decap_release_20261125_fvy2da/clock_host_5g/serdes_cml_to_cmos_r5_pdk.mag",
           ]),
        mk("div_ab_5g_v2", "pll_div_ab_5g_v2_pdk",
           "analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/pll_div_ab_5g_v2_pdk.mag",
           408.0, 386.0, "R90", "vdd_a", "CLK 5G", "#decbe4"),
        mk("tx_qdiv2_5g", "serdes_rx_qdiv2_8ph_5g_pdk",
           "analog/rx/cmos_rx/layout/variants/v5g_pdk/serdes_rx_qdiv2_8ph_5g_pdk.mag",
           514.0, 276.0, "R90", "vdd_a", "CLK 5G", "#decbe4"),
        mk("tx_sst_v5", "serdes_tx_sst_top_pdk",
           "analog/tx/sst/layout/variants/v5_pdk/serdes_tx_sst_top_pdk.mag",
           408.0, 0.0, "R270_MX", "vdd_tx", "TX 5G", "#ffffcc"),
        mk("rx_top_5g", "serdes_rx_cmos_top_5g_pdk",
           "analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/serdes_rx_cmos_top_5g_pdk.mag",
           x_rx, 62.0, "R0", "vdd_rx", "RX 5G", "#ccece6"),
        MacroMeta(
            inst="digital_v4", cell_name="serdes_digital_top_v4", mag_rel="", extra_mags=[],
            bbox_orig=dig_bb, ports_raw=dig_ports, x=x_dig, y=y_dig, orient="R0",
            domain="vdd_d", group=f"DIG {digital_variant}", color="#b3cde3",
            is_digital=True, gds_rel=dig_gds_rel, def_rel=dig_def_rel,
        ),
    ]

    # Targeted ~11.5% core-area hybrid decap banks (compacted 20.8 x 17.2 um 5G Direct + 121-Ohm Damped + HV33 tiles)
    decaps: list[DecapBank] = [
        DecapBank("DEC_HV33", "vdd_hv33", 322.0, core_h - 124.0,  48.0, 120.0, "hv33"),
        DecapBank("DEC_BIAS", "vdd_bias",   0.0, 160.0,           142.0,  24.0, "direct"),
        DecapBank("DEC_Q",    "vdd_q",    192.0,   4.0,           178.0, 118.0, "direct"),
        DecapBank("DEC_A",    "vdd_a",    408.0, 558.0,           126.0,  78.0, "50pct"),
        DecapBank("DEC_D",    "vdd_d",    440.0, 424.0,            92.0, 124.0, "75pct"),
        DecapBank("DEC_TX_N", "vdd_tx",   408.0, 266.0,            92.0,  36.0, "50pct"),
        DecapBank("DEC_TX_W", "vdd_tx",   579.0,   4.0,            22.0, 134.0, "50pct"),
        DecapBank("DEC_RX_S", "vdd_rx",   614.0,   1.0,           238.0,  37.0, "50pct"),
    ]

    # Strict zero-overlap assertion
    all_boxes = [(m.inst, (m.x, m.y, m.x + m.w, m.y + m.h)) for m in macros] + [
        (d.name, (d.x, d.y, d.x + d.w, d.y + d.h)) for d in decaps
    ]
    for i in range(len(all_boxes)):
        for j in range(i + 1, len(all_boxes)):
            a, b = all_boxes[i][1], all_boxes[j][1]
            ox = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
            oy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
            if ox * oy > 1e-4:
                raise AssertionError(
                    f"OVERLAP between {all_boxes[i][0]} {a} and {all_boxes[j][0]} {b}: {ox*oy:.1f} um^2"
                )
    return core_w, core_h, macros, decaps


def add_box(
    rects: dict[str, list[tuple[int, int, int, int]]],
    layer: str,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
) -> None:
    """Paint an exact bounding box (no +/-hw endcap bloat) snapped to the 5 nm Magic grid."""
    ax, bx = min(x1, x2), max(x1, x2)
    ay, by = min(y1, y2), max(y1, y2)
    rects.setdefault(layer, []).append((u(grid(ax)), u(grid(ay)), u(grid(bx)), u(grid(by))))


def add_via_12_array(
    rects: dict[str, list[tuple[int, int, int, int]]],
    cx: float,
    cy: float,
    nx: int,
    ny: int,
    pitch: float = 0.60,
) -> None:
    """DRC-safe nx x ny M1<->M2 via1 array (0.26 um cut, 0.60 um pitch -> 0.34 um gap >= 0.17 um)."""
    x0 = cx - 0.5 * (nx - 1) * pitch
    y0 = cy - 0.5 * (ny - 1) * pitch
    wm = (nx - 1) * pitch + 0.44
    hm = (ny - 1) * pitch + 0.44
    add_box(rects, "metal1", cx - 0.5 * wm, cy - 0.5 * hm, cx + 0.5 * wm, cy + 0.5 * hm)
    add_box(rects, "metal2", cx - 0.5 * wm, cy - 0.5 * hm, cx + 0.5 * wm, cy + 0.5 * hm)
    for ix in range(nx):
        for iy in range(ny):
            vx = grid(x0 + ix * pitch)
            vy = grid(y0 + iy * pitch)
            rects.setdefault("via1", []).append((u(vx - 0.13), u(vy - 0.13), u(vx + 0.13), u(vy + 0.13)))


def add_via_23_array(
    rects: dict[str, list[tuple[int, int, int, int]]],
    cx: float,
    cy: float,
    nx: int,
    ny: int,
    pitch: float = 0.80,
) -> None:
    """DRC-safe nx x ny M2<->M3 via2 array (0.28 um cut, 0.80 um pitch -> 0.52 um gap >= 0.20 um)."""
    x0 = cx - 0.5 * (nx - 1) * pitch
    y0 = cy - 0.5 * (ny - 1) * pitch
    w2 = (nx - 1) * pitch + 0.52
    h2 = (ny - 1) * pitch + 0.52
    w3 = (nx - 1) * pitch + 0.60
    h3 = (ny - 1) * pitch + 0.60
    add_box(rects, "metal2", cx - 0.5 * w2, cy - 0.5 * h2, cx + 0.5 * w2, cy + 0.5 * h2)
    add_box(rects, "metal3", cx - 0.5 * w3, cy - 0.5 * h3, cx + 0.5 * w3, cy + 0.5 * h3)
    for ix in range(nx):
        for iy in range(ny):
            vx = grid(x0 + ix * pitch)
            vy = grid(y0 + iy * pitch)
            rects.setdefault("via2", []).append((u(vx - 0.14), u(vy - 0.14), u(vx + 0.14), u(vy + 0.14)))


def add_via_34_array(
    rects: dict[str, list[tuple[int, int, int, int]]],
    cx: float,
    cy: float,
    nx: int,
    ny: int,
    pitch: float = 0.80,
) -> None:
    """DRC-safe nx x ny M3<->M4 via3 array (0.32 um cut, 0.80 um pitch -> 0.48 um gap >= 0.20 um)."""
    x0 = cx - 0.5 * (nx - 1) * pitch
    y0 = cy - 0.5 * (ny - 1) * pitch
    wm = (nx - 1) * pitch + 0.60
    hm = (ny - 1) * pitch + 0.60
    add_box(rects, "metal3", cx - 0.5 * wm, cy - 0.5 * hm, cx + 0.5 * wm, cy + 0.5 * hm)
    add_box(rects, "metal4", cx - 0.5 * wm, cy - 0.5 * hm, cx + 0.5 * wm, cy + 0.5 * hm)
    for ix in range(nx):
        for iy in range(ny):
            vx = grid(x0 + ix * pitch)
            vy = grid(y0 + iy * pitch)
            rects.setdefault("via3", []).append((u(vx - 0.16), u(vy - 0.16), u(vx + 0.16), u(vy + 0.16)))


def add_layer_hop(rects: dict, x: float, y: float, l_from: str, l_to: str) -> None:
    order = ["metal1", "metal2", "metal3", "metal4", "metal5"]
    i0, i1 = order.index(l_from), order.index(l_to)
    if i0 == i1:
        return
    lo, hi = min(i0, i1), max(i0, i1)
    for k in range(lo, hi):
        if k == 0: b4g.add_via_12(rects, x, y)
        elif k == 1: b4g.add_via_23(rects, x, y)
        elif k == 2: b4g.add_via_34(rects, x, y)
        elif k == 3: b4g.add_via_45(rects, x, y)


def route_poly(
    rects: dict,
    p0: tuple[float, float, str],
    p1: tuple[float, float, str],
    segments: list[tuple[tuple[float, float], tuple[float, float], str]],
    width: float = 0.40,
) -> float:
    """Paint an explicit sequence of orthogonal (pt_a, pt_b, layer) segments with exact via transitions."""
    cur_lyr = p0[2]
    wl = 0.0
    for idx, (a, b, lyr) in enumerate(segments):
        ax, ay = grid(a[0]), grid(a[1])
        bx, by = grid(b[0]), grid(b[1])
        if idx == 0 and (abs(ax - p0[0]) > 0.01 or abs(ay - p0[1]) > 0.01):
            b4g.add_wire_rect(rects, cur_lyr, [(p0[0], p0[1]), (ax, ay)], width)
        add_layer_hop(rects, ax, ay, cur_lyr, lyr)
        b4g.add_wire_rect(rects, lyr, [(ax, ay), (bx, by)], width)
        wl += abs(bx - ax) + abs(by - ay)
        cur_lyr = lyr
    end_pt = segments[-1][1]
    ex, ey = grid(end_pt[0]), grid(end_pt[1])
    add_layer_hop(rects, ex, ey, cur_lyr, p1[2])
    if abs(ex - p1[0]) > 0.01 or abs(ey - p1[1]) > 0.01:
        b4g.add_wire_rect(rects, p1[2], [(ex, ey), (p1[0], p1[1])], width)
    return wl


def audit_top_connectivity_5g(
    rects: dict[str, list[tuple[int, int, int, int]]],
    macros: list[MacroMeta],
    decap_placements: list[dict],
    core_w: float,
    core_h: float,
    expected_nets: list[tuple[str, list[tuple[str, str, str]]]],
) -> dict:
    """Fast (<1s) Union-Find connectivity, 8-domain power isolation, decap tie, and same-layer DRC spacing audit."""
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

    def hit_pt(px: float, py: float, lyr: str, tol: float = 0.25) -> set[int]:
        return {find(ii) for ii, x1, y1, x2, y2 in by_lyr[lyr] if x1 - tol <= px <= x2 + tol and y1 - tol <= py <= y2 + tol}

    pwr_pts = {
        "VSS":      ("metal5", -14.0, 300.0),
        "vdd_hv33": ("metal5", -33.0, 540.0),
        "vdd_bias": ("metal5", -33.0, 300.0),
        "vdd_q":    ("metal5", -33.0, 60.0),
        "vdd_a":    ("metal5", 460.0, core_h + 33.0),
        "vdd_d":    ("metal5", 720.0, core_h + 33.0),
        "vdd_rx":   ("metal5", core_w + 33.0, 120.0),
        "vdd_tx":   ("metal5", 490.0, -33.0),
    }
    comp_to_nets: dict[int, list[str]] = defaultdict(list)
    pwr_roots: dict[str, int] = {}
    for pname, (lyr, px, py) in pwr_pts.items():
        hr = hit_pt(px, py, lyr, tol=0.2)
        if len(hr) == 1:
            r = next(iter(hr))
            pwr_roots[pname] = r
            comp_to_nets[r].append(f"PWR:{pname}")

    by = {m.inst: m for m in macros}
    opens: list[str] = []
    for net, pins in expected_nets:
        roots = []
        for inst, port, lyr in pins:
            px, py, _ = by[inst].port_world(port)
            roots.append((f"{inst}.{port}", hit_pt(px, py, lyr)))
        all_r = set().union(*(hr for _, hr in roots))
        if len(all_r) != 1 or any(not hr for _, hr in roots):
            opens.append(f"{net}: {[(lbl, len(hr)) for lbl, hr in roots]}")
        for r in all_r:
            comp_to_nets[r].append(net)

    # Check all 13 macros' VDD & VSS pins hit exact expected power roots
    macro_pwr_fails: list[str] = []
    macro_pwr_map = [
        ("ldo_kelvin", "vin", "metal5", "vdd_hv33"),
        ("ldo_kelvin", "quiet", "metal5", "vdd_q"),
        ("ldo_kelvin", "host", "metal2", "vdd_bias"),
        ("ldo_kelvin", "vss", "metal4", "VSS"),
        ("lc_vco_oct", "vdd", "metal4", "vdd_q"),
        ("lc_vco_oct", "vss", "metal4", "VSS"),
        ("bias_top_v2", "vdd", "metal3", "vdd_bias"),
        ("bias_top_v2", "vss", "metal1", "VSS"),
        ("lf_k4", "vdd", "metal3", "vdd_q"),
        ("lf_k4", "vss", "metal3", "VSS"),
        ("cp_v4", "vdd", "metal3", "vdd_q"),
        ("cp_v4", "vss", "metal3", "VSS"),
        ("pfd", "vdd", "metal1", "vdd_q"),
        ("pfd", "vss", "metal2", "VSS"),
        ("bias_cp", "vcp", "metal2", "vdd_q"),
        ("bias_cp", "vss", "metal2", "VSS"),
        ("clk_host_5g", "vdd_clk", "metal5", "vdd_a"),
        ("clk_host_5g", "vss", "metal5", "VSS"),
        ("div_ab_5g_v2", "vdd", "metal4", "vdd_a"),
        ("div_ab_5g_v2", "vss", "metal4", "VSS"),
        ("tx_qdiv2_5g", "vdd", "metal3", "vdd_a"),
        ("tx_qdiv2_5g", "vss", "metal3", "VSS"),
        ("tx_sst_v5", "vdd", "metal5", "vdd_tx"),
        ("tx_sst_v5", "vss", "metal5", "VSS"),
        ("rx_top_5g", "vdd", "metal5", "vdd_rx"),
        ("rx_top_5g", "vss", "metal5", "VSS"),
    ]
    for inst, port, lyr, dom in macro_pwr_map:
        px, py, _ = by[inst].port_world(port)
        if inst == "div_ab_5g_v2" and port == "vss":
            py = 545.8  # North end of div_ab_5g_v2's full-height M4 vss spine (avoids South vdd bar!)
        hr = hit_pt(px, py, lyr)
        exp_r = pwr_roots.get(dom, -999)
        if hr != {exp_r}:
            macro_pwr_fails.append(f"{inst}.{port}->{dom} got={hr} exp={exp_r}")
    # Also check digital_v4 East M5 stripes hit vdd_d & VSS
    dig = by["digital_v4"]
    if hit_pt(dig.x + dig.w - 2.0, dig.y + 33.2, "metal5") != {pwr_roots.get("vdd_d", -999)}:
        macro_pwr_fails.append("digital_v4.VPWR->vdd_d")
    if hit_pt(dig.x + dig.w - 2.0, dig.y + 15.2, "metal5") != {pwr_roots.get("VSS", -999)}:
        macro_pwr_fails.append("digital_v4.VGND->VSS")

    decap_ok = 0
    decap_fails: list[str] = []
    for b in decap_placements:
        rvdd = hit_pt(*b["vdd_pt"], "metal4", tol=0.2)
        rvss = hit_pt(*b["vss_pt"], "metal2", tol=0.2)
        if rvdd == {pwr_roots.get(b["domain"], -1)} and rvss == {pwr_roots.get("VSS", -2)}:
            decap_ok += 1
        else:
            decap_fails.append(f"{b['name']}({b['domain']}): vdd={rvdd} vs {pwr_roots.get(b['domain'])}, vss={rvss} vs {pwr_roots.get('VSS')}")

    # Check top-level different-net same-layer metal spacing (catches M2/M3/M4/M5 top routing DRCs in <0.5s!)
    min_sp = {"metal2": 0.145, "metal3": 0.305, "metal4": 0.305, "metal5": 1.605}
    spacing_viols: list[str] = []
    for lyr, sp in min_sp.items():
        arr = by_lyr[lyr]
        for i in range(len(arr)):
            ii, x1, y1, x2, y2 = arr[i]
            ri = find(ii)
            for j in range(i + 1, len(arr)):
                jj, X1, Y1, X2, Y2 = arr[j]
                if find(jj) == ri:
                    continue
                dx = max(0.0, max(X1 - x2, x1 - X2))
                dy = max(0.0, max(Y1 - y2, y1 - Y2))
                if dx < sp and dy < sp and (dx * dx + dy * dy) < sp * sp - 1e-6:
                    if len(spacing_viols) < 25:
                        spacing_viols.append(f"{lyr} d=({dx:.3f},{dy:.3f})<{sp} @ ({x1:.1f},{y1:.1f})..({X1:.1f},{Y1:.1f})")

    shorts = [ns for ns in comp_to_nets.values() if len(ns) > 1]
    res = {
        "signal_nets_checked": len(expected_nets),
        "opens": opens,
        "shorts": shorts,
        "power_domains_distinct": len(set(pwr_roots.values())),
        "macro_pwr_ties_ok": len(macro_pwr_map) + 2 - len(macro_pwr_fails),
        "macro_pwr_ties_total": len(macro_pwr_map) + 2,
        "macro_pwr_fails": macro_pwr_fails,
        "decap_banks_connected": decap_ok,
        "decap_banks_total": len(decap_placements),
        "decap_fails": decap_fails,
        "top_spacing_viols_count": len(spacing_viols),
        "top_spacing_viols_sample": spacing_viols[:10],
    }
    print(
        f"[top_audit_5g] signals={len(expected_nets)} opens={len(opens)} shorts={len(shorts)} | "
        f"pwr_domains={res['power_domains_distinct']}/8 | macro_pwr={res['macro_pwr_ties_ok']}/{res['macro_pwr_ties_total']} | "
        f"decap_tied={decap_ok}/{len(decap_placements)} | top_spacing_viols={len(spacing_viols)}",
        flush=True,
    )
    for msg in opens[:6] + [f"SHORT:{s}" for s in shorts[:6]] + macro_pwr_fails[:6] + decap_fails[:6] + spacing_viols[:6]:
        print(f"    AUDIT_ISSUE: {msg}", flush=True)
    return res


def build_chip_top_5g(
    work: Path,
    digital_variant: str = "v4p1",
    run_drc: bool = False,
    run_extract: bool = False,
    export_gds: bool = False,
) -> dict:
    t0 = time.time()
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    core_w, core_h, macros, decaps = build_5g_floorplan_spec(digital_variant=digital_variant)
    m_map = {m.inst: m for m in macros}

    # 1. Stage all real 5G .mag subcells + read-only digital proxy + compacted 5G decap tiles
    staged = 0
    for m in macros:
        if m.is_digital:
            prepare_digital_proxy_v4(work, m.gds_rel, m.cell_name)
        else:
            for rel in [m.mag_rel, *m.extra_mags]:
                src = REPO / rel
                assert src.exists(), f"Missing 5G macro mag: {src}"
                shutil.copy2(src, work / src.name)
                staged += 1
    print(f"[chip_top_5g] Staged {staged} real 5G analog .mag files + digital proxy ({digital_variant})", flush=True)

    decap_dir = work / "decap_tiles"
    decap_sum = d5g.build_all_5g_decap_tiles(decap_dir)
    assert decap_sum["all_drc_clean"], f"5G decap tile DRC failed: {decap_sum}"
    for key in ("direct_1v8", "damped_1v8", "hv33"):
        src_mag = Path(decap_sum["tiles"][key]["mag"])
        shutil.copy2(src_mag, work / src_mag.name)

    # 2. Compose hierarchical `serdes_5g_top_pdk.mag`
    top_name = "serdes_5g_top_pdk"
    rects: dict[str, list[tuple[int, int, int, int]]] = {}
    uses: list[str] = []
    labels: list[tuple[str, int, int, int, int, str, int | None]] = []

    for m in macros:
        tf = m.tf
        bx0, by0, bx1, by1 = [u(v) for v in m.bbox_orig]
        uses.append("\n".join([
            f"use {m.cell_name}  {m.inst}",
            "timestamp 0",
            f"transform {tf[0]} {tf[1]} {tf[2]} {tf[3]} {tf[4]} {tf[5]}",
            f"box {bx0} {by0} {bx1} {by1}",
        ]))

    # 2b. Array compacted 5G Direct + 121-Ohm Damped + HV33 tiles inside every decap bank
    px, py = d5g.PITCH_X, d5g.PITCH_Y
    box_u = decap_sum["tiles"]["direct_1v8"]["box_um"]
    uw, uh = box_u[2] - box_u[0], box_u[3] - box_u[1]
    ux0, uy0, ux1, uy1 = [u(v) for v in box_u]
    tile_counts = defaultdict(lambda: {"direct": 0, "damped": 0, "hv33": 0, "cap_pf": 0.0})
    decap_placements: list[dict] = []

    for d in decaps:
        avail_w = max(0.0, d.w - 2.0)
        avail_h = max(0.0, d.h - 2.0)
        if avail_w < uw or avail_h < uh:
            continue
        nx = max(1, int((avail_w - uw) // px) + 1)
        ny = max(1, int((avail_h - uh) // py) + 1)
        if d.name == "DEC_Q":
            nx, ny = min(nx, 6), min(ny, 4)
        arr_w = (nx - 1) * px + uw
        arr_h = (ny - 1) * py + uh
        ox = grid(d.x + 0.5 * (d.w - arr_w) - box_u[0])
        oy = grid(d.y + 0.5 * (d.h - arr_h) - box_u[1])

        n_dir = n_dmp = n_hv = 0
        for ix in range(nx):
            for iy in range(ny):
                if d.damp_mode == "hv33":
                    tkey = "hv33"; n_hv += 1
                elif d.damp_mode == "direct":
                    tkey = "direct_1v8"; n_dir += 1
                elif d.damp_mode == "75pct":
                    tkey = "direct_1v8" if (ix + iy) % 4 == 0 else "damped_1v8"
                    if tkey == "direct_1v8": n_dir += 1
                    else: n_dmp += 1
                else:
                    tkey = "direct_1v8" if (ix + iy) % 2 == 0 else "damped_1v8"
                    if tkey == "direct_1v8": n_dir += 1
                    else: n_dmp += 1
                tcell = decap_sum["tiles"][tkey]["cell"]
                tx = grid(ox + ix * px)
                ty = grid(oy + iy * py)
                uses.append("\n".join([
                    f"use {tcell}  {d.name}_{ix}_{iy}",
                    "timestamp 0",
                    f"transform 1 0 {u(tx)} 0 1 {u(ty)}",
                    f"box {ux0} {uy0} {ux1} {uy1}",
                ]))
        cap_pf = n_dir * 1.265 + n_dmp * 1.05 + n_hv * 0.622
        tile_counts[d.domain]["direct"] += n_dir
        tile_counts[d.domain]["damped"] += n_dmp
        tile_counts[d.domain]["hv33"] += n_hv
        tile_counts[d.domain]["cap_pf"] = round(tile_counts[d.domain]["cap_pf"] + cap_pf, 2)

        x_lo = grid(ox - 1.00)
        x_hi = grid(ox + (nx - 1) * px + 16.40)
        xvdd = grid(ox - 0.55)
        xvss = grid(ox + (nx - 1) * px + 15.95)
        yvdd0 = grid(oy + d5g.Y_VDD)
        yvdd1 = grid(oy + d5g.Y_VDD + (ny - 1) * py)
        yvss0 = grid(oy + d5g.Y_VSS)
        yvss1 = grid(oy + d5g.Y_VSS + (ny - 1) * py)
        for r in range(ny):
            b4g.add_wire_rect(rects, "metal4", [(x_lo, grid(oy + d5g.Y_VDD + r * py)), (x_hi, grid(oy + d5g.Y_VDD + r * py))], 0.90)
            b4g.add_wire_rect(rects, "metal2", [(x_lo, grid(oy + d5g.Y_VSS + r * py)), (x_hi, grid(oy + d5g.Y_VSS + r * py))], 0.90)
        if ny > 1:
            b4g.add_wire_rect(rects, "metal4", [(xvdd, yvdd0), (xvdd, yvdd1)], 0.90)
            b4g.add_wire_rect(rects, "metal2", [(xvss, yvss0), (xvss, yvss1)], 0.90)
        decap_placements.append(dict(
            name=d.name, domain=d.domain, nx=nx, ny=ny,
            direct=n_dir, damped=n_dmp, hv33=n_hv, cap_pf=round(cap_pf, 2),
            x=d.x, y=d.y, w=d.w, h=d.h, ox=ox, oy=oy, x_lo=x_lo, x_hi=x_hi,
            vdd_pt=(xvdd, yvdd0), vdd_top=(xvdd, yvdd1),
            vss_pt=(xvss, yvss0), vss_top=(xvss, yvss1),
        ))
    dp_by = {b["name"]: b for b in decap_placements}

    # 2c. Full-Height Dual P+ Substrate Guard Moat at x = 387.0 & 397.0
    b4g.paint_guard_moat_rects(rects, 386.2, 6.0, 387.8, core_h - 6.0)
    b4g.paint_guard_moat_rects(rects, 396.2, 6.0, 397.8, core_h - 6.0)

    # 2d. Outer M5 Power Ring: Closed 14 um VSS ring + 7 separated domain outer M5 VDD rails!
    b4g.add_wire_rect(rects, "metal5", [(-14.0, -14.0), (core_w + 14.0, -14.0), (core_w + 14.0, core_h + 14.0), (-14.0, core_h + 14.0), (-14.0, -14.0)], 14.0)
    for xm in (387.0, 397.0):
        b4g.add_wire_rect(rects, "metal2", [(xm, 4.0), (xm, 7.0)], 1.60)
        b4g.add_via_234_array(rects, xm, 4.5, 2, 2)
        b4g.add_wire_rect(rects, "metal4", [(xm, -14.0), (xm, 4.5)], 2.40)
        b4g.add_via_45_array(rects, xm, -14.0, 2, 3)
        b4g.add_wire_rect(rects, "metal2", [(xm, core_h - 7.0), (xm, core_h - 4.0)], 1.60)
        b4g.add_via_234_array(rects, xm, core_h - 4.5, 2, 2)
        b4g.add_wire_rect(rects, "metal4", [(xm, core_h - 4.5), (xm, core_h + 14.0)], 2.40)
        b4g.add_via_45_array(rects, xm, core_h + 14.0, 2, 3)

    # 7 separated outer M5 supply rails (>= 5 um outside VSS ring & >= 12 um between domains!)
    b4g.add_wire_rect(rects, "metal5", [(-33.0, 440.0), (-33.0, core_h + 33.0), (376.0, core_h + 33.0)], 12.0)           # 1. VDD_HV33
    b4g.add_wire_rect(rects, "metal5", [(-33.0, 172.0), (-33.0, 420.0)], 8.0)                                              # 2. VDD_BIAS
    b4g.add_wire_rect(rects, "metal5", [(-33.0, 152.0), (-33.0, -33.0), (382.0, -33.0)], 12.0)                             # 3. VDD_Q
    b4g.add_wire_rect(rects, "metal5", [(400.0, core_h + 33.0), (530.0, core_h + 33.0)], 12.0)                             # 4. VDD_A
    b4g.add_wire_rect(rects, "metal5", [(548.0, core_h + 33.0), (core_w + 33.0, core_h + 33.0), (core_w + 33.0, 278.0)], 14.0)  # 5. VDD_D (widened 10->14 um)
    b4g.add_wire_rect(rects, "metal5", [(602.0, -33.0), (core_w + 33.0, -33.0), (core_w + 33.0, 258.0)], 14.0)             # 6. VDD_RX (widened 12->14 um; >=3 um clear of VDD_TX)
    b4g.add_wire_rect(rects, "metal5", [(400.0, -33.0), (586.0, -33.0)], 12.0)                                             # 7. VDD_TX

    # 2d-bis. IR/EM-Hardened Full-Height 24 um Central M5 VSS Spine (x=373..397, y=-14..core_h+14)
    # Bridges South <-> North 14 um M5 VSS perimeter rings directly over the dual P+ guard moats so
    # ZERO macro DC return current ever enters the thin M1/M2 P+ substrate guard moats!
    add_box(rects, "metal5", 373.0, -14.0, 397.0, core_h + 14.0)

    # 2e. Tie ALL 8 Decap Banks cleanly to their exact VDD domain & VSS!
    # 1) DEC_HV33 -> VDD_HV33 (N) & VSS (moat x=387, flush 0.90 um M2; 0 mA DC!)
    b = dp_by["DEC_HV33"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_top"], (b["vdd_top"][0], core_h + 33.0)], 3.00)
    b4g.add_via_45_array(rects, b["vdd_top"][0], core_h + 33.0, 2, 3)
    b4g.add_wire_rect(rects, "metal2", [b["vss_pt"], (387.0, b["vss_pt"][1])], 0.90)

    # 2) DEC_BIAS -> VDD_BIAS (W x=-33) & VSS (W x=-14)
    b = dp_by["DEC_BIAS"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_pt"], (-33.0, b["vdd_pt"][1])], 2.40)
    b4g.add_via_45_array(rects, -33.0, b["vdd_pt"][1], 2, 2)
    b4g.add_wire_rect(rects, "metal2", [(b["x_lo"], b["vss_pt"][1]), (-4.0, b["vss_pt"][1])], 0.90)
    b4g.add_via_234_array(rects, -4.0, b["vss_pt"][1], 2, 2)
    b4g.add_wire_rect(rects, "metal4", [(-4.0, b["vss_pt"][1]), (-14.0, b["vss_pt"][1])], 2.40)
    b4g.add_via_45_array(rects, -14.0, b["vss_pt"][1], 2, 2)

    # 3) DEC_Q -> VDD_Q (S y=-33) & VSS (S y=-14, flush 0.90 um M2!)
    b = dp_by["DEC_Q"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_pt"], (b["vdd_pt"][0], -33.0)], 3.60)
    b4g.add_via_45_array(rects, b["vdd_pt"][0], -33.0, 2, 3)
    b4g.add_wire_rect(rects, "metal2", [b["vss_pt"], (b["vss_pt"][0], 2.0)], 0.90)
    b4g.add_via_234_array(rects, b["vss_pt"][0], 2.0, 2, 2)
    b4g.add_wire_rect(rects, "metal4", [(b["vss_pt"][0], 2.0), (b["vss_pt"][0], -14.0)], 3.60)
    b4g.add_via_45_array(rects, b["vss_pt"][0], -14.0, 2, 3)

    # 4) DEC_A -> VDD_A (N y=core_h+33) & VSS (moat x=397; 0 mA DC!)
    b = dp_by["DEC_A"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_top"], (b["vdd_top"][0], core_h + 33.0)], 3.20)
    b4g.add_via_45_array(rects, b["vdd_top"][0], core_h + 33.0, 2, 3)
    b4g.add_wire_rect(rects, "metal2", [(b["x_lo"], b["vss_pt"][1]), (397.0, b["vss_pt"][1])], 0.90)

    # 5) DEC_D -> VDD_D (N via open x=538 -> y=653 -> x=556 -> y=core_h+33) & VSS (W at y=552 -> moat x=397; 0 mA DC!)
    b = dp_by["DEC_D"]
    b4g.add_wire_rect(rects, "metal4", [(b["x_hi"], b["vdd_top"][1]), (538.0, b["vdd_top"][1]), (538.0, core_h + 3.0), (556.0, core_h + 3.0), (556.0, core_h + 33.0)], 3.20)
    b4g.add_via_45_array(rects, 556.0, core_h + 33.0, 2, 3)
    b4g.add_wire_rect(rects, "metal2", [(b["x_lo"], b["vss_top"][1]), (436.0, b["vss_top"][1]), (436.0, 552.0), (397.0, 552.0)], 0.90)

    # 6) DEC_TX_N -> VDD_TX (M4 bridge under y=258..269 M5 VSS highway at x=405.0; 0 mA DC!) & VSS (W to moat x=397)
    b = dp_by["DEC_TX_N"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_pt"], (405.0, b["vdd_pt"][1]), (405.0, 252.0)], 2.40)
    b4g.add_via_45_array(rects, 405.0, 252.0, 1, 2)
    b4g.add_wire_rect(rects, "metal2", [(b["x_lo"], b["vss_pt"][1]), (397.0, b["vss_pt"][1])], 0.90)

    # 7) DEC_TX_W -> VDD_TX (S y=-33) & VSS (S y=-14, flush 0.90 um M2!)
    b = dp_by["DEC_TX_W"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_pt"], (b["vdd_pt"][0], -33.0)], 2.80)
    b4g.add_via_45_array(rects, b["vdd_pt"][0], -33.0, 2, 3)
    b4g.add_wire_rect(rects, "metal2", [b["vss_pt"], (b["vss_pt"][0], 2.0)], 0.90)
    b4g.add_via_234_array(rects, b["vss_pt"][0], 2.0, 2, 2)
    b4g.add_wire_rect(rects, "metal4", [(b["vss_pt"][0], 2.0), (b["vss_pt"][0], -14.0)], 2.80)
    b4g.add_via_45_array(rects, b["vss_pt"][0], -14.0, 2, 3)

    # 8) DEC_RX_S -> VDD_RX (merges directly into 30 um VDD_RX M4 bridge + 16x4=64 via4 array @ y=-33!) & VSS (S y=-14)
    b = dp_by["DEC_RX_S"]
    b4g.add_wire_rect(rects, "metal4", [b["vdd_pt"], (b["vdd_pt"][0], -33.0)], 3.60)
    b4g.add_wire_rect(rects, "metal2", [b["vss_pt"], (b["vss_pt"][0], -2.0)], 0.90)
    b4g.add_via_234_array(rects, b["vss_pt"][0], -2.0, 2, 2)
    b4g.add_wire_rect(rects, "metal4", [(b["vss_pt"][0], -2.0), (b["vss_pt"][0], -14.0)], 3.60)
    b4g.add_via_45_array(rects, b["vss_pt"][0], -14.0, 2, 3)

    # 2f. Tie ALL 13 Macros' VDD & VSS Power Rails with Full IR/EM-Hardened Multi-Via M5/M4 Trunks!
    ldo = m_map["ldo_kelvin"]
    vco = m_map["lc_vco_oct"]
    bias = m_map["bias_top_v2"]
    lf, cp, pfd, bcp = m_map["lf_k4"], m_map["cp_v4"], m_map["pfd"], m_map["bias_cp"]
    clk, div, tq = m_map["clk_host_5g"], m_map["div_ab_5g_v2"], m_map["tx_qdiv2_5g"]
    tx, rx, dig = m_map["tx_sst_v5"], m_map["rx_top_5g"], m_map["digital_v4"]

    # -------------------------------------------------------------------------
    # 1) LDO Kelvin:
    #    - vin (9.11 mA): 12 um M5/M4 + 6x3=18 via4 (y=651.2) + 6x4=24 via4 (y=683.0) -> <50% EM!
    #    - quiet (8.86 mA): Direct 24 um M5 VDD_Q highway straight South over M5-free VCO active bay!
    #    - host (0.10 mA): VDD_BIAS with 2x2 via2/via3 arrays
    #    - vss (0.35 mA): Direct 4 um M4 under VDD_Q into 24 um Central M5 VSS Spine (ZERO moat!)
    # -------------------------------------------------------------------------
    p = ldo.port_world("vin")
    add_box(rects, "metal5", p[0] - 6.0, p[1] - 2.4, p[0] + 6.0, core_h + 4.6)
    b4g.add_via_45_array(rects, p[0], core_h + 1.2, 6, 3)
    add_box(rects, "metal4", p[0] - 6.0, core_h - 1.4, p[0] + 6.0, core_h + 37.0)
    b4g.add_via_45_array(rects, p[0], core_h + 33.0, 6, 4)

    # Main 24 um M5 VDD_Q Kelvin Highway: ldo.quiet (311.6, 590.7) -> 9.6 um slot (x=314.2..323.8 clear of LDO vss & DEC_HV33)
    # -> 24 um M5 vertical superhighway (x=314.0..338.0, y=212.0..524.0) straight to lc_vco_oct.vdd!
    pq = ldo.port_world("quiet")
    add_box(rects, "metal5", pq[0] - 2.6, pq[1] - 7.0, 323.8, pq[1] + 7.0)
    add_box(rects, "metal5", 314.2, 522.0, 323.8, pq[1] + 7.0)
    add_box(rects, "metal5", 314.0, 212.0, 338.0, 524.0)
    # Branch to outer South VDD_Q rail & DEC_Q (0 mA DC, at x=360.0 strictly clear of DEC_Q M5<=342.6 & Central VSS>=373!)
    add_box(rects, "metal5", 336.0, 212.0, 362.0, 218.0)
    add_box(rects, "metal5", 358.0, -4.0, 362.0, 218.0)
    b4g.add_via_45_array(rects, 360.0, -2.5, 2, 2)
    add_box(rects, "metal4", 358.0, -35.0, 362.0, -0.5)
    b4g.add_via_45_array(rects, 360.0, -33.0, 2, 3)

    ph = ldo.port_world("host")
    b4g.add_wire_rect(rects, "metal2", [(ph[0], ph[1]), (-4.5, ph[1])], 1.20)
    add_via_23_array(rects, -4.5, ph[1], 2, 2)
    b4g.add_wire_rect(rects, "metal3", [(-4.5, ph[1]), (-4.5, 390.0)], 1.20)
    add_via_34_array(rects, -4.5, 390.0, 2, 2)
    b4g.add_wire_rect(rects, "metal4", [(-4.5, 390.0), (-33.0, 390.0)], 2.00)
    b4g.add_via_45_array(rects, -33.0, 390.0, 2, 2)

    pv = ldo.port_world("vss")
    add_box(rects, "metal4", pv[0] - 2.0, 511.0, pv[0] + 2.0, pv[1] + 1.0)
    add_box(rects, "metal4", pv[0] - 2.0, 511.0, 382.0, 515.0)
    b4g.add_via_45_array(rects, 378.0, 513.0, 3, 2)

    # -------------------------------------------------------------------------
    # 2) LC-VCO (8.06 mA peak):
    #    Keep top-level VDD_Q M4 strictly inside x=298.1..301.9 (3.8 um neck) over internal vdd bar
    #    (y=223.9..226.1) with >=1.4 um wide-M4 step-back (y<=222.5) so Magic hierarchical extraction
    #    NEVER promotes internal act0/vdd (keeps DRC=0 & 41/41 diff PASS!), and parallel-shunt the
    #    3.8 um M4 neck with 2x1 via4 (@ y=224.7 -> M5) + 4x2 via3 (@ y=224.8 -> 3.6 um M3 shunt)
    #    so M4, M3, via3, and via4 ALL stay well below SKY130A 110 C DC EM limits!
    #    - vss: 8 um neck + 4x1 via4 (@ y=228.5) + 12x1 via4 (@ y=231.0, M4 y=230.2..231.8) = 16 via4 ->
    #      25.5 um M5 North over M5-free VCO active bay -> 22 um M5 West straight to West 14 um M5 VSS ring!
    # -------------------------------------------------------------------------
    pvd = vco.port_world("vdd")
    add_box(rects, "metal4", 297.0, 211.5, 323.0, 219.5)
    add_box(rects, "metal4", 298.05, 219.0, 301.95, 226.0)
    add_box(rects, "metal5", 297.0, 211.5, 338.0, 220.0)
    b4g.add_via_45_array(rects, 310.0, 215.5, 10, 4)
    # Parallel M5 (2x1 via4 @ y=224.7, 1.8 um clear of vss M5 @ 227.5) & M3 (4x2 via3) shunts into (300.0, 225.0)!
    b4g.add_via_45_array(rects, 300.0, 224.7, 2, 1)
    add_box(rects, "metal5", 298.1, 218.0, 301.9, 225.7)
    add_via_34_array(rects, 300.0, 225.0, 4, 2, pitch=0.80)
    add_box(rects, "metal3", 298.2, 214.0, 301.8, 225.8)
    add_via_34_array(rects, 300.0, 215.5, 4, 3, pitch=0.80)

    pvs = vco.port_world("vss")
    add_box(rects, "metal4", 296.0, 227.4, 304.0, 231.8)
    b4g.add_via_45_array(rects, 300.0, 228.5, 4, 1)
    add_box(rects, "metal4", 289.0, 230.2, 311.0, 231.8)
    b4g.add_via_45_array(rects, 300.0, 231.0, 12, 1)
    add_box(rects, "metal5", 286.0, 227.5, 311.5, 506.0)
    add_box(rects, "metal5", -14.0, 484.0, 311.5, 506.0)

    # -------------------------------------------------------------------------
    # 3) BIAS Top v2 (0.96 mA peak):
    #    - vdd (M3 @ 59.3, 151.63): 1.4 um M3 entry + 4x3=12 via3 @ (59.3, 155.0) -> 3.6 um M4 West to x=-33 -> 2x3=6 via4!
    #    - vss (M1 @ 88.4, 0.63): 6x3=18 via1 + 4x2=8 via234 @ (88.4, -1.8) -> 4.0 um M4 South -> 2x3=6 via4 on VSS!
    # -------------------------------------------------------------------------
    pbv = bias.port_world("vdd")
    add_box(rects, "metal3", pbv[0] - 0.70, pbv[1] - 0.30, pbv[0] + 0.70, 154.0)
    add_box(rects, "metal3", pbv[0] - 1.60, 153.4, pbv[0] + 1.60, 156.2)
    add_via_34_array(rects, pbv[0], 155.0, 4, 3)
    add_box(rects, "metal4", -35.0, 153.7, pbv[0] + 1.60, 157.3)
    add_box(rects, "metal4", -35.0, 153.7, -31.0, 176.5)
    b4g.add_via_45_array(rects, -33.0, 173.5, 2, 3)

    pbs = bias.port_world("vss")
    add_box(rects, "metal1", pbs[0] - 2.0, -2.7, pbs[0] + 2.0, pbs[1] + 0.35)
    add_via_12_array(rects, pbs[0], -1.8, 6, 3, pitch=0.60)
    b4g.add_via_234_array(rects, pbs[0], -1.8, 4, 2, pitch=0.80)
    add_box(rects, "metal4", pbs[0] - 2.0, -16.8, pbs[0] + 2.0, -1.0)
    b4g.add_via_45_array(rects, pbs[0], -14.0, 2, 3)

    # -------------------------------------------------------------------------
    # 4) Quiet PLL Core (`lf_k4`, `cp_v4`, `pfd`, `bias_cp`, 0.80 mA total):
    #    - VDD_Q: 4 um M5 branch from 24 um VDD_Q highway @ y=201.0 West to x=186.0 + 2x2 via4 + 3x3=9 via3 -> M3 bus!
    #      pfd.vdd (0.15 mA): 3x1 via1 + 2x1 via2/via3 along M1 bar y=174.97 -> ~60% max-cut EM (down from 150%!)
    #    - VSS: Dedicated 6 um M5 riser from South VSS ring @ x=198.0 to y=125.0 + 2x2 via4 + 3x3=9 via3 -> M3 bus
    #      (ZERO moat connection; cp_v4.vss runs pure M3 via x=191.5 East of bias_cp -> ZERO via2/via3 bottleneck!)
    # -------------------------------------------------------------------------
    add_box(rects, "metal5", 318.0, 199.0, 324.0, 214.0)
    add_box(rects, "metal5", 184.0, 199.0, 324.0, 203.0)
    b4g.add_via_45_array(rects, 186.0, 200.5, 2, 2)
    add_via_34_array(rects, 186.0, 200.5, 3, 3)
    b4g.add_wire_rect(rects, "metal3", [(153.65, 200.5), (315.0, 200.5)], 1.60)
    for m_q, pn_q in ((lf, "vdd"), (cp, "vdd")):
        pqm = m_q.port_world(pn_q)
        b4g.add_wire_rect(rects, "metal3", [(pqm[0], pqm[1]), (pqm[0], 200.5)], 1.00)
    # pfd.vdd (0.15 mA): 3 via1 cuts straddling (153.65, 174.97) at x=153.45, 154.05, 154.65 + 2 via2/via3 -> M4 North!
    ppfd_v = pfd.port_world("vdd")
    for vx_1 in (grid(ppfd_v[0] - 0.20), grid(ppfd_v[0] + 0.40), grid(ppfd_v[0] + 1.00)):
        b4g.add_via_12(rects, vx_1, ppfd_v[1])
    for vx_23 in (grid(ppfd_v[0] - 0.15), grid(ppfd_v[0] + 0.65)):
        b4g.add_via_23(rects, vx_23, ppfd_v[1])
        b4g.add_via_34(rects, vx_23, ppfd_v[1])
        b4g.add_via_34(rects, vx_23, 200.5)
    add_box(rects, "metal1", ppfd_v[0] - 0.38, ppfd_v[1] - 0.18, ppfd_v[0] + 1.18, ppfd_v[1] + 0.18)
    add_box(rects, "metal2", ppfd_v[0] - 0.38, ppfd_v[1] - 0.18, ppfd_v[0] + 1.18, ppfd_v[1] + 0.18)
    add_box(rects, "metal3", ppfd_v[0] - 0.41, ppfd_v[1] - 0.26, ppfd_v[0] + 0.91, ppfd_v[1] + 0.26)
    add_box(rects, "metal4", ppfd_v[0] - 0.41, ppfd_v[1] - 0.26, ppfd_v[0] + 0.91, 200.76)
    pbcp_v = bcp.port_world("vcp")
    route_poly(rects, pbcp_v, (244.0, 200.5, "metal3"), [
        ((pbcp_v[0], pbcp_v[1]), (pbcp_v[0], 140.5), "metal2"),
        ((pbcp_v[0], 140.5), (244.0, 140.5), "metal2"),
        ((244.0, 140.5), (244.0, 200.5), "metal3"),
    ], width=0.80)

    # Quiet PLL Core VSS: dedicated 6 um M5 riser @ x=198.0 from South VSS ring (-14..127) — ZERO moat DC!
    add_box(rects, "metal5", 195.0, -14.0, 201.0, 127.0)
    b4g.add_via_45_array(rects, 198.0, 125.0, 2, 2)
    add_via_34_array(rects, 198.0, 125.0, 3, 3)
    b4g.add_wire_rect(rects, "metal3", [(182.0, 125.0), (282.5, 125.0)], 2.00)
    plf_s = lf.port_world("vss")
    b4g.add_wire_rect(rects, "metal3", [(plf_s[0], plf_s[1]), (plf_s[0], 125.0)], 1.00)
    # cp_v4.vss (0.55 mA): pure M3 East to x=191.5 (East of bias_cp @ 188.9) -> South M3 to y=125.0 (ZERO via2!)
    pcp_s = cp.port_world("vss")
    b4g.add_wire_rect(rects, "metal3", [(pcp_s[0], pcp_s[1]), (191.5, pcp_s[1]), (191.5, 125.0)], 1.20)
    pbcp_s = bcp.port_world("vss")
    b4g.add_wire_rect(rects, "metal2", [(pbcp_s[0], pbcp_s[1]), (pbcp_s[0], 125.0)], 0.80)
    add_via_23_array(rects, pbcp_s[0], 125.0, 2, 1)
    ppfd_s = pfd.port_world("vss")
    b4g.add_wire_rect(rects, "metal2", [(ppfd_s[0], ppfd_s[1]), (147.0, ppfd_s[1]), (147.0, 151.5), (-4.0, 151.5)], 1.00)
    b4g.add_via_234_array(rects, -4.0, 151.5, 2, 2)
    b4g.add_wire_rect(rects, "metal4", [(-4.0, 151.5), (-14.0, 151.5)], 1.60)
    b4g.add_via_45_array(rects, -14.0, 151.5, 2, 2)

    # -------------------------------------------------------------------------
    # 5) 5G Clock Bay (`clk_host_5g` 8.80mA, `div_ab_5g_v2` 3.55mA, `tx_qdiv2_5g` 3.20mA = 15.55mA):
    #    - VDD_A: 20 um M4 bridge under North VSS ring (40+40 via4!) -> 20 um M5 header (y=634..654) ->
    #      DUAL M5 vertical trunks flanking DEC_A/DEC_D (West x=400.0..407.4 + East x=534.6..542.0) +
    #      12 um M5 center drop (x=429..441) -> 14 um M5 bridge directly across clk_host_5g.vdd_clk!
    #      tx_qdiv2_5g.vdd: 3.6 um M3 + 8x4=32 via3 + 3x3=9 via4 -> 6 um M5 North over M5-free tx_qdiv2_5g!
    #    - VSS (ZERO moat DC!):
    #      * div_ab_5g_v2.vss (3.55 mA): 6 um M4 West @ y=550.5..556.5 -> 4x3=12 via4 into 24 um Central M5 VSS Spine!
    #      * clk_host_5g.vss (8.80 mA): 10 um M5 straight West (y=302.4..312.4) into 24 um Central M5 VSS Spine
    #        PLUS 14 um M5 South (x=498..512) into tx_sst_v5.vss & East VSS Highway!
    #      * tx_qdiv2_5g.vss (3.20 mA): 2.6->4.4 um M3 + 5x8=40 via3 + 2x4=8 via4 -> 22 um M5 East-West VSS Highway!
    # -------------------------------------------------------------------------
    # North VDD_A entry right under VDD_A pad (460, 683): 20 um M4 bridge + 10x4=40 via4 on BOTH ends!
    add_box(rects, "metal4", 450.0, 644.0, 470.0, core_h + 37.5)
    b4g.add_via_45_array(rects, 460.0, core_h + 33.0, 10, 4)
    b4g.add_via_45_array(rects, 460.0, 648.0, 10, 4)
    # 20 um M5 North VDD_A Header (y=634..654, x=400.0..542.0)
    add_box(rects, "metal5", 400.0, 634.0, 542.0, 654.0)
    # West M5 VDD_A Trunk (x=400.0..407.4, y=386.0..654.0; clear of Central VSS<=397 & DEC_A>=409.42 & clkp>=412.8!)
    add_box(rects, "metal5", 400.0, 386.0, 407.4, 654.0)
    # Mid-North M5 tie below DEC_A (y=548.0..564.0, x=400.0..441.0) -> 12 um Center M5 Trunk (x=429..441, y=378..564)
    add_box(rects, "metal5", 400.0, 548.0, 441.0, 564.0)
    add_box(rects, "metal5", 429.0, 378.0, 441.0, 564.0)
    # East M5 VDD_A Trunk (x=534.6..542.0, y=365.5..654.0; clear of DEC_A<=532.58, DEC_D<=526.78, dig M5>=547.68!)
    add_box(rects, "metal5", 534.6, 365.5, 542.0, 654.0)
    # 14 um M5 horizontal clk_host_5g.vdd_clk bus connecting Center Trunk + clk_host_5g.vdd_clk + East Trunk!
    pck_v = clk.port_world("vdd_clk")
    add_box(rects, "metal5", 429.0, 378.0, 490.0, 390.0)
    add_box(rects, "metal5", 482.5, 365.5, 542.0, 379.5)
    add_box(rects, "metal5", 482.5, 365.5, 490.0, 390.0)

    # div_ab_5g_v2.vdd (3.55 mA): 4 um M4 West from (408.5, 387.6) -> 5 um M4 North (x=401.3..406.3) -> 3x6=18 via4!
    pdiv_v = div.port_world("vdd")
    add_box(rects, "metal4", 401.3, 386.2, 409.0, 390.2)
    add_box(rects, "metal4", 401.3, 386.2, 406.3, 420.0)
    b4g.add_via_45_array(rects, 403.7, 409.0, 3, 6)

    # div_ab_5g_v2.vss (3.55 mA): 4->6 um M4 North from (419.5, 545.8) -> West @ y=550.5..556.5 -> 4x3=12 via4 on Central VSS!
    pdiv_s = div.port_world("vss")
    add_box(rects, "metal4", pdiv_s[0] - 2.0, 545.0, pdiv_s[0] + 2.0, 556.5)
    add_box(rects, "metal4", 384.0, 550.5, pdiv_s[0] + 2.0, 556.5)
    b4g.add_via_45_array(rects, 389.0, 553.5, 4, 3)

    # tx_qdiv2_5g.vdd (3.20 mA): 3.6 um M3 entry + 8x4=32 via3 + 3x3=9 via4 @ (522.5, 271.9) -> 6 um M5 North to y=379.5!
    # (M5 starts at y=269.1 -> 2.6 um clear of tx_sst_v5.vss M5 <= 266.5!)
    ptq_v = tq.port_world("vdd")
    add_box(rects, "metal3", 521.2, 269.5, 524.8, 277.0)
    add_via_34_array(rects, 522.5, 271.9, 8, 4, pitch=0.80)
    add_box(rects, "metal4", 519.4, 269.0, 525.6, 274.8)
    b4g.add_via_45_array(rects, 522.5, 271.9, 3, 3)
    add_box(rects, "metal5", 519.5, 269.1, 525.5, 379.5)

    # clk_host_5g.vss (8.80 mA): 10 um M5 straight West (y=302.4..312.4) into 24 um Central M5 VSS Spine
    # PLUS 14 um M5 East/South (x=498..512, y=258.2..324) tying cleanly to tx_sst_v5.vss!
    pck_s = clk.port_world("vss")
    add_box(rects, "metal5", 395.0, 302.4, 491.1, 312.4)
    add_box(rects, "metal5", 488.9, 310.0, 512.0, 324.0)
    add_box(rects, "metal5", 498.0, 258.2, 512.0, 324.0)

    # -------------------------------------------------------------------------
    # 6) TX SST v5 (17.50 mA peak):
    #    - vdd (M5 @ 408.22, 144.7): 14 um M5 highway (x=399.5..413.5, y=-4.9..148.0) ->
    #      24 um M4 bridge (x=400.5..424.5) under South VSS ring with 13x2+3x3=35 via4 (N) & 13x4=52 via4 (S)!
    #    - vss (M5 @ 518.52, 256.5): 3-way ZERO-VIA M5 return:
    #      (a) 8.3 um M5 straight West (y=258.2..266.5) -> 24 um Central M5 VSS Spine (2.6 um clear of tx_qdiv2_5g.vdd M5>=269.1!)
    #      (b) 14 um M5 North (x=498..512) -> clk_host_5g.vss -> Central M5 VSS Spine!
    #      (c) 22 um M5 straight East (y=264.0..286.0, x=534..950) -> East 14 um M5 VSS ring!
    #    - tx_qdiv2_5g.vss (3.20 mA): 2.6->4.4 um M3 + 5x8=40 via3 + 2x4=8 via4 @ (530.2, 271.5) -> East VSS Highway!
    # -------------------------------------------------------------------------
    ptx_v = tx.port_world("vdd")
    add_box(rects, "metal5", 399.5, -4.9, 413.5, 148.0)
    add_box(rects, "metal5", 400.5, -4.9, 425.0, -1.1)
    b4g.add_via_45_array(rects, 413.0, -3.0, 13, 2)
    b4g.add_via_45_array(rects, 403.5, 2.5, 3, 3)
    add_box(rects, "metal4", 400.5, -37.0, 424.8, -1.2)
    add_box(rects, "metal4", 400.5, -3.0, 406.5, 5.5)
    b4g.add_via_45_array(rects, 413.0, -33.0, 13, 4)
    # 0 mA DC spur North to DEC_TX_N M4 bridge @ (405.0, 252.0)
    add_box(rects, "metal5", 402.5, 146.0, 406.5, 254.0)

    ptx_s = tx.port_world("vss")
    ptq_s = tq.port_world("vss")
    # West M5 VSS bridge from tx_sst_v5.vss (518.52, 256.5) to Central M5 VSS Spine (x=373..397)
    add_box(rects, "metal5", 517.3, 254.7, 524.8, 266.5)
    add_box(rects, "metal5", 395.0, 258.2, 524.8, 266.5)
    # East 22 um M5 VSS Highway (y=264.0..286.0, x=534.0..core_w+14.0) + tie from tx_sst_v5.vss (y=254.7..266.5)!
    add_box(rects, "metal5", 517.3, 254.7, 576.6, 266.5)
    add_box(rects, "metal5", 534.0, 264.0, core_w + 14.0, 286.0)
    # tx_qdiv2_5g.vss (3.20 mA): 2.6 um M3 entry (clear of 529.14!) + 5x8=40 via3 + 2x4=8 via4 @ (530.2, 271.5)!
    add_box(rects, "metal3", 529.8, 274.2, 532.4, 277.0)
    add_via_34_array(rects, 530.2, 271.5, 5, 8, pitch=0.80)
    add_box(rects, "metal4", 528.3, 267.8, 532.1, 275.2)
    b4g.add_via_45_array(rects, 530.2, 271.5, 2, 4)
    add_box(rects, "metal5", 528.3, 264.0, 536.0, 275.2)

    # -------------------------------------------------------------------------
    # 7) RX Top 5G (28.47 mA peak — highest-current macro!):
    #    - vdd (M5 @ 615.2, 117.68): DUAL-FEED (East Direct + South-West):
    #      (a) EAST DIRECT: 21.4 um M5 (y=116.6..138.0, x=614.2..839.2) -> 4x9=36 via4 -> 16 um M4 jump
    #          (x=831.8..856.0, 1.24 um clear of ctle_p M4 @ 857.24) under widened 6.0 um rx.vss spine (842.2..848.2)
    #          -> 3x9=27 via4 -> 24 um M5 (y=114..138) -> 4x12=48 via4 -> 24 um M4 under East VSS ring -> 4x12=48 via4
    #          straight into East VDD_RX pad (969, 120)!
    #      (b) SOUTH-WEST: 10.4 um M5 (x=601.6..612.0) South -> 16x2+5x3=47 via4 -> 30 um M4 bridge under South VSS ring
    #          -> 16x4=64 via4 onto South VDD_RX M5 rail!
    #    - vss (M5 @ 615.2, 93.88): DUAL-ENDED (South + North) ZERO-VIA M5 return:
    #      (a) SOUTH: 48 um M5 East (y=47.0..94.9, 11.1 um clear of DEC_RX_S M5<=35.9!) -> East VSS ring
    #          + 30 um M5 South branch (x=856..886) -> South VSS ring!
    #      (b) NORTH: 6.0 um M5 tie (x=842.2..848.2, y=259.0..266.0) bridging rx_top_5g's East VSS spine directly
    #          into the 22 um North VSS Highway (y=264..286), halving internal RX VSS spine current!
    # -------------------------------------------------------------------------
    prx_v = rx.port_world("vdd")
    # (a) East Direct Feed -> East VDD_RX pad (969, 120)
    add_box(rects, "metal5", 614.2, 116.6, 839.2, 138.0)
    b4g.add_via_45_array(rects, 835.3, 129.8, 4, 9)
    add_box(rects, "metal4", 831.8, 121.8, 856.0, 137.8)
    b4g.add_via_45_array(rects, 853.4, 129.8, 3, 9)
    add_box(rects, "metal5", 850.6, 114.0, core_w + 5.0, 138.0)
    b4g.add_via_45_array(rects, core_w + 1.0, 126.0, 4, 12)
    add_box(rects, "metal4", core_w - 3.0, 114.0, core_w + 38.0, 138.0)
    b4g.add_via_45_array(rects, core_w + 33.0, 126.0, 4, 12)
    # (b) South-West Parallel Feed -> South VDD_RX rail
    add_box(rects, "metal5", 601.6, 116.6, 616.4, 136.6)
    add_box(rects, "metal5", 601.6, -4.9, 612.0, 136.6)
    add_box(rects, "metal5", 601.6, -4.9, 633.5, -1.1)
    add_box(rects, "metal5", 601.6, -4.9, 612.0, 7.0)
    b4g.add_via_45_array(rects, 618.0, -3.0, 16, 2)
    b4g.add_via_45_array(rects, 606.8, 3.0, 5, 3)
    add_box(rects, "metal4", 602.0, -37.0, 632.5, -1.2)
    add_box(rects, "metal4", 602.0, -3.0, 611.6, 6.0)
    b4g.add_via_45_array(rects, 618.0, -33.0, 16, 4)

    # RX VSS: 48 um M5 South-East + 30 um M5 South leg + 6 um M5 North dual-return bridge to y=264..286 VSS Highway!
    prx_s = rx.port_world("vss")
    add_box(rects, "metal5", 614.1, 47.0, core_w + 14.0, 94.9)
    add_box(rects, "metal5", 856.0, -14.0, 886.0, 50.0)
    add_box(rects, "metal5", 842.2, 259.0, 848.2, 266.0)

    # 8) Digital Top v4/v4p1 (ALL 10 East VGND M5 stripes -> East VSS ring + ALL 9 East VPWR M5 stripes -> East VDD_D ring!)
    x_dig_e = grid(dig.x + dig.w - 3.5)
    vgnd_ys = (15.2, 51.2, 87.2, 123.2, 159.2, 195.2, 231.2, 267.2, 303.2, 339.2)
    vpwr_ys = (33.2, 69.2, 105.2, 141.2, 177.2, 213.2, 249.2, 285.2, 321.2)
    for yl in vgnd_ys:
        if yl < dig.h - 2.0:
            yc = grid(dig.y + yl)
            b4g.add_wire_rect(rects, "metal5", [(x_dig_e, yc), (core_w + 14.0, yc)], 2.00)
    for yl in vpwr_ys:
        if yl < dig.h - 2.0:
            yc = grid(dig.y + yl)
            b4g.add_wire_rect(rects, "metal5", [(x_dig_e, yc), (core_w + 3.0, yc)], 2.40)
            b4g.add_via_45_array(rects, core_w + 2.5, yc, 2, 2)
            b4g.add_wire_rect(rects, "metal4", [(core_w + 2.5, yc), (core_w + 33.0, yc)], 3.20)
            b4g.add_via_45_array(rects, core_w + 33.0, yc, 2, 2)

    # 3. Route ALL 5G Inter-Macro High-Speed Clock, PLL, BIAS, Data & Control Buses!
    routed_metrics: dict[str, dict] = {}
    routed_lines_plot: list[tuple[str, str, list[tuple[float, float]]]] = []
    expected_nets: list[tuple[str, list[tuple[str, str, str]]]] = []

    # 3a. 33-bit RX Data / Edge / Word Clock (`rx_top_5g` North <-> `digital_v4` South)
    # Drop M4->M2 vias cleanly OUTSIDE digital_v4 South boundary (y=dig.y-0.55), then 0.16 um M2 pin stub -> ZERO met2.2 inside dig!
    rx_pairs = [("wclk", "rx_word_clk")] + [(f"wd{i}", f"rx_phys[{i}]") for i in range(16)] + [(f"we{i}", f"rx_phys[{16+i}]") for i in range(16)]
    rx_coords = []
    rx_wl = 0.0
    rx_max_dx = 0.0
    y_ch_lo = rx.y + rx.h + 2.0
    y_ch_hi = dig.y - 2.0
    y_dig_via = grid(dig.y - 0.55)
    for idx, (rp, dp) in enumerate(rx_pairs):
        p0 = rx.port_world(rp)
        p1 = dig.port_world(dp)
        rx_coords.append((p0[0], p1[0]))
        dx = abs(p0[0] - p1[0])
        rx_max_dx = max(rx_max_dx, dx)
        if dx < 0.35:
            xm = grid(p1[0])
            wl = route_poly(rects, p0, (xm, y_dig_via, "metal2"), [
                ((p0[0], p0[1]), (xm, p0[1]), "metal4"),
                ((xm, p0[1]), (xm, y_dig_via), "metal4"),
            ], width=0.38)
            b4g.add_wire_rect(rects, "metal2", [(xm, y_dig_via), (p1[0], p1[1] + 0.18)], 0.16)
            routed_lines_plot.append(("rx_data", "#1f77b4", [(p0[0], p0[1]), (p1[0], p1[1])]))
        else:
            yt = grid(y_ch_lo + (idx % 20) * ((y_ch_hi - y_ch_lo) / 20.0))
            v_l = "metal4" if idx % 2 == 0 else "metal2"
            wl = route_poly(rects, p0, (p1[0], y_dig_via, "metal2"), [
                ((p0[0], p0[1]), (p0[0], yt), v_l),
                ((p0[0], yt), (p1[0], yt), "metal3"),
                ((p1[0], yt), (p1[0], y_dig_via), v_l),
            ], width=0.34)
            b4g.add_wire_rect(rects, "metal2", [(p1[0], y_dig_via), (p1[0], p1[1] + 0.18)], 0.16)
            routed_lines_plot.append(("rx_data", "#1f77b4", [(p0[0], p0[1]), (p0[0], yt), (p1[0], yt), (p1[0], p1[1])]))
        rx_wl += wl
        expected_nets.append((f"rx_{rp}", [("rx_top_5g", rp, p0[2]), ("digital_v4", dp, p1[2])]))
    rx_crossings = count_1d_crossings(rx_coords)
    routed_metrics["rx_data_33b"] = {
        "nets": len(rx_pairs), "crossings": rx_crossings,
        "max_dx_um": round(rx_max_dx, 2), "total_wl_um": round(rx_wl, 1),
        "layer_mode": "2L_M4_straight_0via" if rx_crossings == 0 and rx_max_dx < 0.35 else "3L_M2M3M4_channel",
    }

    # 3b. 17-bit TX Data / Word Clock (`tx_sst_v5` East <-> `digital_v4` South-West)
    # Dynamically choose 17 M4 vertical tracks clear of digital South pins; drop M4->M2 outside digital at y=dig.y-0.55!
    tx_pairs = [("clk250_out", "tx_word_clk")] + [(f"din{i}", f"tx_capture_data[{i}]") for i in range(16)]
    tx_dig_xs = [dig.port_world(dp)[0] for _, dp in tx_pairs]
    tx_xts: list[float] = []
    xc = 578.20
    while len(tx_xts) < len(tx_pairs):
        if all(abs(xc - dx) >= 0.90 for dx in tx_dig_xs) and all(abs(xc - prev) >= 0.86 for prev in tx_xts):
            tx_xts.append(grid(xc))
            xc += 0.86
        else:
            xc += 0.10
    tx_wl = 0.0
    for idx, (tp, dp) in enumerate(tx_pairs):
        p0 = tx.port_world(tp)
        p1 = dig.port_world(dp)
        xt = tx_xts[idx]
        yt = grid(274.2 + idx * 0.84)  # y=274.2..287.64: >1.5um above pi_ctrl M3 (<=272.6) & >1.8um below y_dig_via (289.45)!
        wl = route_poly(rects, p0, (p1[0], y_dig_via, "metal2"), [
            ((p0[0], p0[1]), (xt, p0[1]), "metal3"),
            ((xt, p0[1]), (xt, yt), "metal4"),
            ((xt, yt), (p1[0], yt), "metal3"),
            ((p1[0], yt), (p1[0], y_dig_via), "metal4"),
        ], width=0.32)
        b4g.add_wire_rect(rects, "metal2", [(p1[0], y_dig_via), (p1[0], p1[1] + 0.18)], 0.16)
        tx_wl += wl
        routed_lines_plot.append(("tx_data", "#2ca02c", [(p0[0], p0[1]), (xt, p0[1]), (xt, yt), (p1[0], yt), (p1[0], p1[1])]))
        expected_nets.append((f"tx_{tp}", [("tx_sst_v5", tp, p0[2]), ("digital_v4", dp, p1[2])]))
    routed_metrics["tx_data_17b"] = {
        "nets": len(tx_pairs), "total_wl_um": round(tx_wl, 1), "avg_wl_um": round(tx_wl / len(tx_pairs), 1),
    }

    # 3c. Mirror-Symmetric 2.5 GHz CML I/Q (`lc_vco_oct R90` East -> `clk_host_5g` internal c2c_i/q)
    # Keep via34 strictly West of c2c_i/q (x_in=443.8/444.8 < 445.0) & narrow 0.32 um final M3 stub -> >0.36 um clear of ibias M3!
    iq_cml_wl = 0.0
    cml_cfg = [
        ("ip", 373.8, 307.0, 443.8),
        ("in", 375.2, 308.4, 444.8),
        ("qp", 375.2, 377.2, 444.8),
        ("qn", 373.8, 378.6, 443.8),
    ]
    for nm, x_v, y_h, x_in in cml_cfg:
        p0 = vco.port_world(nm)
        p1 = clk.port_world(nm)
        wl = route_poly(rects, p0, (x_in, p1[1], "metal3"), [
            ((p0[0], p0[1]), (x_v, p0[1]), "metal4"),
            ((x_v, p0[1]), (x_v, y_h), "metal4"),
            ((x_v, y_h), (x_in, y_h), "metal3"),
            ((x_in, y_h), (x_in, p1[1]), "metal4"),
        ], width=0.40)
        b4g.add_wire_rect(rects, "metal3", [(x_in, p1[1]), (p1[0], p1[1])], 0.32)
        iq_cml_wl += wl + abs(p1[0] - x_in)
        routed_lines_plot.append(("clk_2p5g_cml", "#d62728", [(p0[0], p0[1]), (x_v, p0[1]), (x_v, y_h), (x_in, y_h), (x_in, p1[1]), (p1[0], p1[1])]))
        expected_nets.append((f"vco_{nm}", [("lc_vco_oct", nm, p0[2]), ("clk_host_5g", nm, p1[2])]))
    routed_metrics["clk_2p5g_vco_to_host"] = {
        "nets": 4, "total_wl_um": round(iq_cml_wl, 1), "avg_hop_um": round(iq_cml_wl / 4.0, 1),
    }

    # 3d. 2.5 GHz CMOS I/Q Hub (`clk_host_5g` East -> `rx_top_5g` West + `tx_qdiv2_5g` North + `div_ab_5g_v2` South!)
    iq_rx_wl = 0.0
    iq_hub = [
        ("ic_p", "ip", "dp", "clkp"),
        ("ic_n", "in", "dn", "clkn"),
        ("qc_p", "qp", "ep", None),
        ("qc_n", "qn", "en", None),
    ]
    for idx, (src_nm, rx_nm, tq_nm, div_nm) in enumerate(iq_hub):
        p0 = clk.port_world(src_nm)
        p_rx = rx.port_world(rx_nm)
        p_tq = tq.port_world(tq_nm)
        x_w = grid(501.4 + idx * 1.40)
        y_m = grid(261.8 + idx * 1.20)  # y=261.8..265.4 strictly ABOVE clk_1p25g_tx (<=261.0) & BELOW rx_pi_ctrl M3 (266.6..272.6)!
        x_e = grid(609.0 + idx * 1.30)
        wl = route_poly(rects, p0, p_rx, [
            ((p0[0], p0[1]), (x_w, p0[1]), "metal3"),
            ((x_w, p0[1]), (x_w, y_m), "metal4"),
            ((x_w, y_m), (x_e, y_m), "metal3"),
            ((x_e, y_m), (x_e, p_rx[1]), "metal4"),
            ((x_e, p_rx[1]), (p_rx[0], p_rx[1]), "metal3"),
        ], width=0.44)
        iq_rx_wl += wl
        routed_lines_plot.append(("clk_2p5g_rx", "#9467bd", [(p0[0], p0[1]), (x_w, p0[1]), (x_w, y_m), (x_e, y_m), (x_e, p_rx[1]), (p_rx[0], p_rx[1])]))
        # Branch North -> drop via34 cleanly OUTSIDE tx_qdiv2_5g North edge (y=414.2 > 413.6) -> M3 stub into dp/dn/ep/en!
        y_n = grid(415.2 + idx * 1.20)
        route_poly(rects, (x_w, p0[1], "metal4"), (p_tq[0], 414.2, "metal3"), [
            ((x_w, p0[1]), (x_w, y_n), "metal4"),
            ((x_w, y_n), (p_tq[0], y_n), "metal3"),
            ((p_tq[0], y_n), (p_tq[0], 414.2), "metal4"),
        ], width=0.38)
        b4g.add_wire_rect(rects, "metal3", [(p_tq[0], 414.2), (p_tq[0], p_tq[1])], 0.34)
        pins_net = [("clk_host_5g", src_nm, p0[2]), ("rx_top_5g", rx_nm, p_rx[2]), ("tx_qdiv2_5g", tq_nm, p_tq[2])]
        if div_nm:
            # Fly over div_ab_5g_v2's South M4 vdd/vss rail (y=386.5) on M5 (div_ab is M5=0%!) -> via45 outside at y_dv!
            p_dv = div.port_world(div_nm)
            y_dv = grid(381.4 + idx * 1.60)
            route_poly(rects, (x_w, y_dv, "metal4"), (p_dv[0], y_dv, "metal4"), [
                ((x_w, y_dv), (p_dv[0], y_dv), "metal3"),
            ], width=0.40)
            b4g.add_via_45(rects, p_dv[0], y_dv)
            b4g.add_wire_rect(rects, "metal5", [(p_dv[0], y_dv), (p_dv[0], p_dv[1])], 2.00)
            b4g.add_via_45(rects, p_dv[0], p_dv[1])
            pins_net.append(("div_ab_5g_v2", div_nm, p_dv[2]))
        expected_nets.append((f"clk2p5_{src_nm}", pins_net))
    routed_metrics["clk_2p5g_host_to_rx"] = {
        "nets": 4, "total_wl_um": round(iq_rx_wl, 1), "avg_hop_um": round(iq_rx_wl / 4.0, 1),
    }

    # 3e. 1.25 GHz 4-Phase TX Clocks (`tx_qdiv2_5g` West -> `tx_sst_v5` North `phi0..270`)
    # Monotonic M4 staircase exiting ckd0..3 West (ckd0 lowest -> rightmost xt=512.1; ckd3 highest -> leftmost xt=508.2 -> ZERO via3 at ckd pins!)
    tx_clk_wl = 0.0
    for idx, (qp, tp) in enumerate([("ckd0", "phi0"), ("ckd1", "phi90"), ("ckd2", "phi180"), ("ckd3", "phi270")]):
        p0 = tq.port_world(qp)
        p1 = tx.port_world(tp)
        xt = grid(512.1 - idx * 1.30)
        yt = grid(258.0 + idx * 1.00)
        wl = route_poly(rects, p0, p1, [
            ((p0[0], p0[1]), (xt, p0[1]), "metal4"),
            ((xt, p0[1]), (xt, yt), "metal4"),
            ((xt, yt), (p1[0], yt), "metal3"),
            ((p1[0], yt), (p1[0], p1[1]), "metal4"),
        ], width=0.38)
        tx_clk_wl += wl
        routed_lines_plot.append(("clk_1p25g_tx", "#ff7f0e", [(p0[0], p0[1]), (xt, p0[1]), (xt, yt), (p1[0], yt), (p1[0], p1[1])]))
        expected_nets.append((f"txclk_{tp}", [("tx_qdiv2_5g", qp, p0[2]), ("tx_sst_v5", tp, p1[2])]))
    routed_metrics["clk_1p25g_qdiv_to_tx"] = {
        "nets": 4, "total_wl_um": round(tx_clk_wl, 1), "avg_hop_um": round(tx_clk_wl / 4.0, 1),
    }

    # 3f. Quiet PLL Loop (`pfd -> cp_v4 -> lf_k4 -> lc_vco_oct`, `div_ab_5g_v2.fb250 -> pfd.fb`)
    # Route lc_vco_oct.vctrl leg on M2 so it passes cleanly UNDER lc_vco_oct's horizontal M4 vdd/vss rails (y=225/228.5)!
    p_lf, p_vc, p_cpo = lf.port_world("ctrl"), vco.port_world("vctrl"), cp.port_world("out")
    vctrl_wl = route_poly(rects, p_lf, p_vc, [
        ((p_lf[0], p_lf[1]), (p_lf[0], 204.5), "metal4"),
        ((p_lf[0], 204.5), (p_vc[0], 204.5), "metal3"),
        ((p_vc[0], 204.5), (p_vc[0], p_vc[1]), "metal2"),
    ], width=0.50)
    routed_lines_plot.append(("pll_vctrl", "#e377c2", [(p_lf[0], p_lf[1]), (p_lf[0], 204.5), (p_vc[0], 204.5), (p_vc[0], p_vc[1])]))
    # CP out turns North at x=242.4 (strictly West of bcp.vcp x=244.0!) -> ZERO short with VDD_Q!
    route_poly(rects, p_cpo, (p_lf[0], 204.5, "metal4"), [
        ((p_cpo[0], p_cpo[1]), (242.4, p_cpo[1]), "metal3"),
        ((242.4, p_cpo[1]), (242.4, 204.5), "metal4"),
        ((242.4, 204.5), (p_lf[0], 204.5), "metal3"),
    ], width=0.44)
    expected_nets.append(("pll_vctrl", [("cp_v4", "out", p_cpo[2]), ("lf_k4", "ctrl", p_lf[2]), ("lc_vco_oct", "vctrl", p_vc[2])]))

    for idx_u, nm_u in enumerate(("up", "dn")):
        pu0, pu1 = pfd.port_world(nm_u), cp.port_world(nm_u)
        xu = grid(179.0 + idx_u * 1.40)
        route_poly(rects, pu0, pu1, [
            ((pu0[0], pu0[1]), (xu, pu0[1]), "metal3"),
            ((xu, pu0[1]), (xu, pu1[1]), "metal4"),
            ((xu, pu1[1]), (pu1[0], pu1[1]), "metal3"),
        ], width=0.38)
        expected_nets.append((f"pll_{nm_u}", [("pfd", nm_u, pu0[2]), ("cp_v4", nm_u, pu1[2])]))

    # fb250: div_ab -> North y=549 -> West x=400.0 -> South y=207.0 -> West x=155.4 -> South M4 to y=179.0 -> M2 into pfd.fb @ (154.2, 176.16) (clear of pfd West M2 vss bar!)
    p_div, p_fb = div.port_world("fb250"), pfd.port_world("fb")
    fb_wl = route_poly(rects, p_div, (154.2, p_fb[1], "metal2"), [
        ((p_div[0], p_div[1]), (p_div[0], 549.0), "metal4"),
        ((p_div[0], 549.0), (400.0, 549.0), "metal3"),
        ((400.0, 549.0), (400.0, 207.0), "metal4"),
        ((400.0, 207.0), (155.4, 207.0), "metal3"),
        ((155.4, 207.0), (155.4, 179.0), "metal4"),
        ((155.4, 179.0), (154.2, 179.0), "metal2"),
    ], width=0.36)
    b4g.add_wire_rect(rects, "metal2", [(154.2, 179.0), (154.2, p_fb[1])], 0.20)
    b4g.add_wire_rect(rects, "metal2", [(154.2, p_fb[1]), (p_fb[0], p_fb[1])], 0.20)
    routed_lines_plot.append(("pll_fb250", "#8c564b", [(p_div[0], p_div[1]), (p_div[0], 549.0), (400.0, 549.0), (400.0, 207.0), (155.4, 207.0), (155.4, 179.0), (154.2, 179.0), (154.2, p_fb[1])]))
    expected_nets.append(("pll_fb250", [("div_ab_5g_v2", "fb250", p_div[2]), ("pfd", "fb", p_fb[2])]))
    routed_metrics["pll_loop"] = {"lf_to_vco_vctrl_um": round(vctrl_wl, 1), "div_to_pfd_fb250_um": round(fb_wl, 1)}

    # 3g. Complete BIAS Distribution (0 crossings w/ power rails, moat, or via234 arrays!)
    p_vbg, p_lbg, p_txbg = bias.port_world("vbg"), ldo.port_world("bg"), tx.port_world("vbg")
    route_poly(rects, p_vbg, p_lbg, [
        ((p_vbg[0], p_vbg[1]), (p_vbg[0], 157.5), "metal3"),
        ((p_vbg[0], 157.5), (-7.5, 157.5), "metal2"),
        ((-7.5, 157.5), (-7.5, p_lbg[1]), "metal3"),
        ((-7.5, p_lbg[1]), (p_lbg[0], p_lbg[1]), "metal2"),
    ], width=0.44)
    route_poly(rects, (p_vbg[0], 157.5, "metal3"), p_txbg, [
        ((p_vbg[0], 157.5), (144.0, 157.5), "metal3"),
        ((144.0, 157.5), (144.0, 208.5), "metal4"),
        ((144.0, 208.5), (398.6, 208.5), "metal3"),
        ((398.6, 208.5), (398.6, 259.2), "metal4"),
        ((398.6, 259.2), (p_txbg[0], 259.2), "metal3"),
        ((p_txbg[0], 259.2), (p_txbg[0], p_txbg[1]), "metal2"),
    ], width=0.40)
    expected_nets.append(("bias_vbg", [("bias_top_v2", "vbg", p_vbg[2]), ("ldo_kelvin", "bg", p_lbg[2]), ("tx_sst_v5", "vbg", p_txbg[2])]))

    p_il0, p_lild = bias.port_world("i_ldo0"), ldo.port_world("i_ldo")
    route_poly(rects, p_il0, p_lild, [
        ((p_il0[0], p_il0[1]), (178.0, p_il0[1]), "metal2"),
        ((178.0, p_il0[1]), (178.0, -8.4), "metal4"),
        ((178.0, -8.4), (-9.5, -8.4), "metal3"),
        ((-9.5, -8.4), (-9.5, p_lild[1]), "metal3"),
        ((-9.5, p_lild[1]), (p_lild[0], p_lild[1]), "metal2"),
    ], width=0.40)
    expected_nets.append(("bias_i_ldo0", [("bias_top_v2", "i_ldo0", p_il0[2]), ("ldo_kelvin", "i_ldo", p_lild[2])]))

    p_il1, p_cpib = bias.port_world("i_ldo1"), cp.port_world("ibias")
    route_poly(rects, p_il1, p_cpib, [
        ((p_il1[0], p_il1[1]), (179.4, p_il1[1]), "metal2"),
        ((179.4, p_il1[1]), (179.4, p_cpib[1]), "metal4"),
        ((179.4, p_cpib[1]), (p_cpib[0], p_cpib[1]), "metal3"),
    ], width=0.38)
    expected_nets.append(("bias_i_ldo1", [("bias_top_v2", "i_ldo1", p_il1[2]), ("cp_v4", "ibias", p_cpib[2])]))

    p_icp, p_bvn, p_cvn = bias.port_world("icp"), bcp.port_world("vbn"), cp.port_world("vbn")
    route_poly(rects, p_icp, p_bvn, [
        ((p_icp[0], p_icp[1]), (177.2, p_icp[1]), "metal2"),
        ((177.2, p_icp[1]), (177.2, p_bvn[1]), "metal4"),
        ((177.2, p_bvn[1]), (p_bvn[0], p_bvn[1]), "metal3"),
    ], width=0.36)
    route_poly(rects, (177.2, p_bvn[1], "metal4"), p_cvn, [
        ((177.2, p_bvn[1]), (177.2, p_cvn[1]), "metal4"),
        ((177.2, p_cvn[1]), (p_cvn[0], p_cvn[1]), "metal3"),
    ], width=0.36)
    expected_nets.append(("bias_cp_vbn", [("bias_top_v2", "icp", p_icp[2]), ("bias_cp", "vbn", p_bvn[2]), ("cp_v4", "vbn", p_cvn[2])]))

    p_bvp, p_cvp = bcp.port_world("vbp"), cp.port_world("vbp")
    route_poly(rects, p_bvp, p_cvp, [
        ((p_bvp[0], p_bvp[1]), (190.2, p_bvp[1]), "metal3"),
        ((190.2, p_bvp[1]), (190.2, 141.0), "metal4"),
        ((190.2, 141.0), (178.0, 141.0), "metal3"),
        ((178.0, 141.0), (178.0, p_cvp[1]), "metal4"),
        ((178.0, p_cvp[1]), (p_cvp[0], p_cvp[1]), "metal3"),
    ], width=0.36)
    expected_nets.append(("bias_cp_vbp", [("bias_cp", "vbp", p_bvp[2]), ("cp_v4", "vbp", p_cvp[2])]))

    # 4) icml -> clk_host_5g.ibias (M3 horizontal at y=123.2 strictly South of y=125 VSS & over M2 moat -> ZERO shorts!)
    p_icml, p_ckib = bias.port_world("icml"), clk.port_world("ibias")
    route_poly(rects, p_icml, p_ckib, [
        ((p_icml[0], p_icml[1]), (189.8, p_icml[1]), "metal2"),
        ((189.8, p_icml[1]), (189.8, 123.2), "metal4"),
        ((189.8, 123.2), (401.6, 123.2), "metal3"),
        ((401.6, 123.2), (401.6, 304.0), "metal4"),
        ((401.6, 304.0), (p_ckib[0], 304.0), "metal3"),
        ((p_ckib[0], 304.0), (p_ckib[0], p_ckib[1]), "metal4"),
    ], width=0.40)
    expected_nets.append(("bias_icml", [("bias_top_v2", "icml", p_icml[2]), ("clk_host_5g", "ibias", p_ckib[2])]))

    # 5) pref (y=-4.2), ictle (y=-5.6), vcm (y=-7.0) — ALL clear of y=-2.0 via234 arrays!
    p_pref, p_lfpr = bias.port_world("pref"), lf.port_world("pre_ref")
    route_poly(rects, p_pref, p_lfpr, [
        ((p_pref[0], p_pref[1]), (p_pref[0], -4.2), "metal3"),
        ((p_pref[0], -4.2), (373.5, -4.2), "metal3"),
        ((373.5, -4.2), (373.5, p_lfpr[1]), "metal4"),
        ((373.5, p_lfpr[1]), (p_lfpr[0], p_lfpr[1]), "metal3"),
    ], width=0.38)
    expected_nets.append(("bias_pref", [("bias_top_v2", "pref", p_pref[2]), ("lf_k4", "pre_ref", p_lfpr[2])]))

    p_ict, p_rxct = bias.port_world("ictle"), rx.port_world("ibias_ctle")
    route_poly(rects, p_ict, p_rxct, [
        ((p_ict[0], p_ict[1]), (181.2, p_ict[1]), "metal2"),
        ((181.2, p_ict[1]), (181.2, -5.6), "metal4"),
        ((181.2, -5.6), (p_rxct[0], -5.6), "metal3"),
        ((p_rxct[0], -5.6), (p_rxct[0], p_rxct[1]), "metal4"),
    ], width=0.40)
    expected_nets.append(("bias_ictle", [("bias_top_v2", "ictle", p_ict[2]), ("rx_top_5g", "ibias_ctle", p_rxct[2])]))

    p_vcm, p_rxcm = bias.port_world("vcm"), rx.port_world("vcm_ref")
    route_poly(rects, p_vcm, p_rxcm, [
        ((p_vcm[0], p_vcm[1]), (p_vcm[0], -7.0), "metal4"),
        ((p_vcm[0], -7.0), (p_rxcm[0], -7.0), "metal3"),
        ((p_rxcm[0], -7.0), (p_rxcm[0], p_rxcm[1]), "metal4"),
    ], width=0.40)
    expected_nets.append(("bias_vcm", [("bias_top_v2", "vcm", p_vcm[2]), ("rx_top_5g", "vcm_ref", p_rxcm[2])]))

    # 3h. 24-bit RX PI Control (`digital_v4` West-Bottom -> `rx_top_5g` South `a0..7, b0..7, f0..7`, 3L M2/M3/M4!)
    pi_ctrl_wl = 0.0
    pi_pairs = (
        [(f"rx_select_a[{i}]", f"a{i}") for i in range(8)]
        + [(f"rx_select_b[{i}]", f"b{i}") for i in range(8)]
        + [(f"rx_fine_b[{i}]", f"f{i}") for i in range(8)]
    )
    for idx, (dp, rp) in enumerate(pi_pairs):
        p0 = dig.port_world(dp)
        p1 = rx.port_world(rp)
        y_s = grid(39.4 + idx * 0.88)  # 24 M3 tracks @ 0.88 um pitch in y=[39.4..59.64] (strictly between DEC_RX_S 38 & RX 62!)
        # Planar decoupled 3L routing:
        #   - idx 0..7:  pure M4 -> M3 -> M4 (y_m=266.6..272.6, strictly between clk_2p5g_rx<=265.4 & tx_data>=275.4; 0 M2!)
        #   - idx 8..23: pure monotonic double-staircase M2 (x_w & x_e both increase with y_m -> 0 crossings & 0 M3/M4!)
        if idx < 8:
            x_w = grid(533.2 + idx * 0.88)
            x_e = grid(601.8 + idx * 0.86)
            y_m = grid(266.6 + idx * 0.86)
            v_w, h_m, v_e = "metal4", "metal3", "metal4"
        else:
            k = idx - 8  # 0..15
            x_w = grid(533.2 + k * 0.56)
            x_e = grid(601.8 + k * 0.56)
            y_m = grid(273.6 + k * 0.86)
            v_w, h_m, v_e = "metal2", "metal2", "metal2"
        pts = [(p0[0], p0[1]), (x_w, p0[1]), (x_w, y_m), (x_e, y_m), (x_e, y_s), (p1[0], y_s), (p1[0], p1[1])]
        wl = route_poly(rects, p0, p1, [
            ((p0[0], p0[1]), (x_w, p0[1]), "metal3"),
            ((x_w, p0[1]), (x_w, y_m), v_w),
            ((x_w, y_m), (x_e, y_m), h_m),
            ((x_e, y_m), (x_e, y_s), v_e),
            ((x_e, y_s), (p1[0], y_s), "metal3"),
            ((p1[0], y_s), (p1[0], p1[1]), "metal2"),
        ], width=0.32)
        pi_ctrl_wl += wl
        if idx in (0, 8, 16, 23):
            routed_lines_plot.append(("rx_pi_ctrl", "#17becf", pts))
        expected_nets.append((f"pi_{rp}", [("digital_v4", dp, p0[2]), ("rx_top_5g", rp, p1[2])]))
    routed_metrics["rx_pi_ctrl_24b"] = {
        "nets": 24, "total_wl_um": round(pi_ctrl_wl, 1), "avg_wl_um": round(pi_ctrl_wl / 24.0, 1),
    }

    # Fix tx_data vertical layer to pure M4 (eliminates any M2 crossing with PI-ctrl M2 horizontal bridge!)
    # Wait: tx_data was already painted above with alternating M4/M2 — let's make tx_data 100% M4 right where it's painted!
    # (Done cleanly via clean post-check: we'll edit line 3b immediately below if audit flags any crossing.)

    # 3i. 90-Degree Orthogonal High-Speed GSSG Pad Exits (South `TX_PAD_P/N` & East `RX_IN_P/N`)!
    for sp, x_pad, ext_lbl in (("pad_p", 430.0, "TX_PAD_P"), ("pad_n", 439.0, "TX_PAD_N")):
        px0, py0, _ = tx.port_world(sp)
        b4g.add_wire_rect(rects, "metal4", [(px0, py0), (px0, -4.0), (x_pad, -4.0), (x_pad, -48.0)], 2.40)
        b4g.add_via_45_array(rects, x_pad, -48.0, 2, 2)
        rects.setdefault("metal5", []).append((u(x_pad - 2.6), u(-55.0), u(x_pad + 2.6), u(-45.0)))
        labels.append(("metal5", u(x_pad - 1.2), u(-53.0), u(x_pad + 1.2), u(-48.0), ext_lbl, len(labels) + 1))

    for sp, x_turn, y_pad, ext_lbl in (("rxn", core_w + 40.0, 98.0, "RX_IN_N"), ("rxp", core_w + 44.0, 110.0, "RX_IN_P")):
        px0, py0, _ = rx.port_world(sp)
        b4g.add_wire_rect(rects, "metal5", [(px0, py0), (core_w + 3.0, py0)], 1.80)
        b4g.add_via_45(rects, core_w + 3.0, py0)
        b4g.add_wire_rect(rects, "metal4", [(core_w + 3.0, py0), (x_turn, py0), (x_turn, y_pad), (core_w + 50.0, y_pad)], 1.80)
        b4g.add_via_45_array(rects, core_w + 50.0, y_pad, 2, 2)
        rects.setdefault("metal5", []).append((u(core_w + 47.0), u(y_pad - 2.6), u(core_w + 57.0), u(y_pad + 2.6)))
        labels.append(("metal5", u(core_w + 50.0), u(y_pad - 1.2), u(core_w + 55.0), u(y_pad + 1.2), ext_lbl, len(labels) + 1))

    # Top-level power perimeter labels (4 distributed root VSS GSSG/perimeter landing ports + 7 VDD domains!)
    for lyr, px_l, py_l, nm in [
        ("metal5", -14.0, 300.0, "VSS"),
        ("metal5", 435.0, -14.0, "VSS"),
        ("metal5", core_w + 14.0, 104.0, "VSS"),
        ("metal5", 460.0, core_h + 14.0, "VSS"),
        ("metal5", -33.0, 540.0, "VDD_HV33"),
        ("metal5", -33.0, 300.0, "VDD_BIAS"),
        ("metal5", -33.0, 60.0, "VDD_Q"),
        ("metal5", 460.0, core_h + 33.0, "VDD_A"),
        ("metal5", 720.0, core_h + 33.0, "VDD_D"),
        ("metal5", core_w + 33.0, 120.0, "VDD_RX"),
        ("metal5", 490.0, -33.0, "VDD_TX"),
    ]:
        labels.append((lyr, u(px_l - 1.0), u(py_l - 1.0), u(px_l + 1.0), u(py_l + 1.0), nm, len(labels) + 1))

    # 4. Write hierarchical Magic `.mag` file (strict Magic section order!)
    mag_lines = ["magic", "tech sky130A", "magscale 1 2", "timestamp 0"]
    for lyr in sorted(rects.keys()):
        mag_lines.append(f"<< {lyr} >>")
        for x1i, y1i, x2i, y2i in rects[lyr]:
            if x2i > x1i and y2i > y1i:
                mag_lines.append(f"rect {x1i} {y1i} {x2i} {y2i}")
    mag_lines.extend(uses)
    mag_lines.append("<< labels >>")
    for lyr, x1i, y1i, x2i, y2i, nm, pnum in labels:
        mag_lines.append(f"rlabel {lyr} {x1i} {y1i} {x2i} {y2i} 0 {nm}")
        if pnum is not None:
            mag_lines.append(f"port {pnum} nsew")
    mag_lines.append("<< end >>")
    top_mag = work / f"{top_name}.mag"
    top_mag.write_text("\n".join(mag_lines) + "\n")

    # 4b. Instant (<1s) Python Union-Find connectivity, 8-domain power isolation & top spacing audit!
    top_audit = audit_top_connectivity_5g(rects, macros, decap_placements, core_w, core_h, expected_nets)

    # 5. Compute exact Chip-Top KPIs & Render True-Scale Inspection PNG (crisp unclipped legend!)
    core_area = core_w * core_h
    active_area = sum(m.w * m.h for m in macros)
    decap_area = sum(d.w * d.h for d in decaps)
    tot_tiles_dir = sum(v["direct"] for v in tile_counts.values())
    tot_tiles_dmp = sum(v["damped"] for v in tile_counts.values())
    tot_tiles_hv = sum(v["hv33"] for v in tile_counts.values())
    tot_tiles = tot_tiles_dir + tot_tiles_dmp + tot_tiles_hv
    tot_top_cap_pf = round(sum(v["cap_pf"] for v in tile_counts.values()), 2)

    fig, ax = plt.subplots(figsize=(14.0, 9.8), dpi=160)
    ax.set_facecolor("#fafafa")
    ax.add_patch(Rectangle((0, 0), core_w, core_h, fill=False, edgecolor="#111", lw=2.2, zorder=10))
    # Outer M5 VSS ring & 7 domain rails
    ax.add_patch(Rectangle((-21, -21), core_w + 42, core_h + 42, fill=False, edgecolor="#7f5539", lw=4.0, alpha=0.55, zorder=1))
    dom_rails = [
        ("VDD_HV33", "#e66101", [(-33, 440), (-33, core_h + 33), (376, core_h + 33)]),
        ("VDD_BIAS", "#b35806", [(-33, 172), (-33, 420)]),
        ("VDD_Q",    "#d7191c", [(-33, 152), (-33, -33), (382, -33)]),
        ("VDD_A",    "#7b3294", [(400, core_h + 33), (530, core_h + 33)]),
        ("VDD_D",    "#2b83ba", [(548, core_h + 33), (core_w + 33, core_h + 33), (core_w + 33, 278)]),
        ("VDD_RX",   "#1b7837", [(606, -33), (core_w + 33, -33), (core_w + 33, 258)]),
        ("VDD_TX",   "#d95f02", [(400, -33), (592, -33)]),
    ]
    for dnm, dcol, dpts in dom_rails:
        ax.plot([p[0] for p in dpts], [p[1] for p in dpts], color=dcol, lw=4.2, alpha=0.75, zorder=2)

    # Guard moat
    ax.add_patch(Rectangle((384, 4), 16, core_h - 8, facecolor="#e0e0e0", edgecolor="#555", hatch="///", alpha=0.65, zorder=2))
    ax.text(392, core_h * 0.5, "Dual P+ Guard Moat", rotation=90, ha="center", va="center", fontsize=8.0, fontweight="bold", color="#333", zorder=3)

    # Decap banks
    for dp in decap_placements:
        ax.add_patch(Rectangle((dp["x"], dp["y"]), dp["w"], dp["h"], facecolor="#e5f5e0", edgecolor="#31a354", lw=1.1, hatch="...", alpha=0.85, zorder=2))
        rot = 90 if dp["h"] > 2.2 * dp["w"] else 0
        lbl = f"{dp['name']}\n{dp['direct']}D+{dp['damped']}R+{dp['hv33']}H ({dp['cap_pf']:.0f}pF)" if dp["hv33"] else f"{dp['name']}\n{dp['direct']}D+{dp['damped']}R ({dp['cap_pf']:.0f}pF)"
        fs_d = 5.5 if dp["w"] < 30 else 6.3
        ax.text(dp["x"] + 0.5 * dp["w"], dp["y"] + 0.5 * dp["h"], lbl, ha="center", va="center",
                fontsize=fs_d, color="#005a32", fontweight="bold", rotation=rot, zorder=4,
                bbox=dict(boxstyle="round,pad=0.10", fc="#f4fbf2", ec="none", alpha=0.85))

    # Real 5G macros
    for m in macros:
        ax.add_patch(Rectangle((m.x, m.y), m.w, m.h, facecolor=m.color, edgecolor="#222", lw=1.3, alpha=0.92, zorder=3))
        rot = 90 if m.h > 2.4 * m.w else 0
        if m.inst == "lc_vco_oct":
            ax.plot([m.x + 255, m.x + 255], [m.y, m.y + m.h], ls="--", color="#8b0000", lw=1.2, zorder=4)
            ax.text(m.x + 125, m.y + 0.5 * m.h, "Octagonal 2.5 nH LC Coil\n(26µm N / 58µm S Halo)", ha="center", va="center",
                    fontsize=8.2, color="#8b0000", fontweight="bold", zorder=5,
                    bbox=dict(boxstyle="round,pad=0.25", fc="#fff4f4", ec="#b2182b", ls="--"))
            ax.text(m.x + 313, m.y + 0.5 * m.h, "VCO Core\n& /2 I/Q\n(R90 -> E)", ha="center", va="center",
                    fontsize=7.6, color="#111", fontweight="bold", zorder=5)
        else:
            lbl = f"{m.inst}\n({m.w:.0f}×{m.h:.0f}, {m.orient})" if m.w * m.h > 9000 else m.inst
            fs = 8.2 if m.w * m.h > 25000 else (6.5 if m.w * m.h > 1800 else 5.2)
            ax.text(m.x + 0.5 * m.w, m.y + 0.5 * m.h, lbl, ha="center", va="center",
                    fontsize=fs, fontweight="bold", rotation=rot, zorder=5)

    # Routed interconnects + crisp bottom legend
    legend_map = {
        "rx_data":      ("#1f77b4", "RX Data/Edge 33b (312.5M)"),
        "tx_data":      ("#2ca02c", "TX Data/Clk 17b (312.5M)"),
        "clk_2p5g_cml": ("#d62728", "2.5G CML I/Q (VCO->Host)"),
        "clk_2p5g_rx":  ("#9467bd", "2.5G CMOS I/Q (Host->RX)"),
        "clk_1p25g_tx": ("#ff7f0e", "1.25G 4-Ph (QDiv2->TX)"),
        "pll_vctrl":    ("#e377c2", "PLL Vctrl (LF->VCO)"),
        "pll_fb250":    ("#8c564b", "PLL FB250 (DivAB->PFD)"),
        "rx_pi_ctrl":   ("#17becf", "RX PI Ctrl 24b (3L M2/M3/M4)"),
    }
    seen_leg: set[str] = set()
    for grp, col, pts in routed_lines_plot:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        lw = 1.6 if "clk" in grp or "pll" in grp else 0.75
        lbl = legend_map[grp][1] if (grp in legend_map and grp not in seen_leg) else None
        if lbl:
            seen_leg.add(grp)
        ax.plot(xs, ys, color=col, lw=lw, alpha=0.88, label=lbl, zorder=8)
    ax.legend(loc="upper center", bbox_to_anchor=(0.48, -0.075), fontsize=8.0, framealpha=0.95, ncol=4)

    # High-speed orthogonal pad annotations
    ax.annotate("TX pad_p/n (SOUTH GSSG)", xy=(435, -48), xytext=(490, -70), ha="center", fontsize=8.4, fontweight="bold", color="#b2182b",
                arrowprops=dict(arrowstyle="->", color="#b2182b", lw=1.8))
    ax.annotate("RX rxp/rxn\n(EAST GSSG\n90° Ortho!)", xy=(core_w + 48, 99), xytext=(core_w + 88, 125), va="center", fontsize=8.3, fontweight="bold", color="#1b7837",
                arrowprops=dict(arrowstyle="->", color="#1b7837", lw=1.8))

    ax.set_xlim(-55, core_w + 175)
    ax.set_ylim(-85, core_h + 55)
    ax.set_aspect("equal")
    ax.set_xlabel("X (µm)")
    ax.set_ylabel("Y (µm)")
    ax.set_title(
        f"5G SerDes Chip-Top (`serdes_5g_top_pdk`, {digital_variant.upper()}): "
        f"{core_w:.0f}×{core_h:.0f} µm = {core_area/1e6:.4f} mm² | "
        f"Macro {100*active_area/core_area:.1f}% | Decap {100*decap_area/core_area:.1f}% ({tot_tiles} tiles: {tot_tiles_dir}D+{tot_tiles_dmp}R+{tot_tiles_hv}H = {tot_top_cap_pf:.0f} pF) | "
        f"RX Crossings = {rx_crossings}",
        fontsize=9.3, fontweight="bold",
    )
    ax.grid(True, alpha=0.2)
    out_png = work / f"serdes_5g_chip_top_{digital_variant}.png"
    fig.savefig(out_png, dpi=160, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)

    # 6. Optional real Magic top-level DRC (`--drc`), GDSII export (`--gds`) & hierarchical ext2spice check (`--extract`)
    magic_verify: dict | None = None
    if run_drc or run_extract or export_gds:
        tcl = work / "_verify_top_5g.tcl"
        cmds = [
            "drc off",
            f"cd {work}",
            f"addpath {work}",
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
                'puts "TOP_GDS_OK"',
            ]
        if run_extract:
            cmds += [
                "drc off",
                "extract all",
                "ext2spice lvs",
                f"ext2spice -o {top_name}_lvs.spice",
                'puts "TOP_EXT2SPICE_OK"',
            ]
        cmds.append("quit -noprompt")
        tcl.write_text("\n".join(cmds) + "\n")
        tm0 = time.time()
        res = mu.run_magic(tcl, cwd=work)
        (work / "magic_top_5g.log").write_text(res.log)
        assert "contained format error" not in res.log, f"Magic format error! See {work / 'magic_top_5g.log'}"
        m_drc = re.search(r"TOP_DRC_TOTAL (\d+)", res.log)
        drc_total = int(m_drc.group(1)) if m_drc else None
        drc_rules = [{"count": int(m.group(1)), "rule": m.group(2).strip()}
                     for m in re.finditer(r"TOP_DRC_RULE (\d+) \| (.+)", res.log)]
        ext_ok = "TOP_EXT2SPICE_OK" in res.log and (work / f"{top_name}_lvs.spice").exists()
        hier_ok = None
        must_conn_res = {}
        must_diff_res = {}
        if ext_ok:
            joined: list[str] = []
            for raw_ln in (work / f"{top_name}_lvs.spice").read_text().splitlines():
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
                    inst, cell, nets = toks[0][1:], toks[-1], toks[1:-1]
                    pnames = sub_ports.get(cell, [])
                    if len(pnames) == len(nets):
                        inst_nets[inst] = dict(zip(pnames, nets))
            def gnet(inst: str, port: str) -> str | None:
                return inst_nets.get(inst, {}).get(port)
            # Signal + Bias + Power connectivity checks!
            conn_checks = [
                ("rx_wclk", ("rx_top_5g", "wclk"), ("digital_v4", "rx_word_clk")),
                ("rx_wd0",  ("rx_top_5g", "wd0"),  ("digital_v4", "rx_phys[0]")),
                ("rx_we15", ("rx_top_5g", "we15"), ("digital_v4", "rx_phys[31]")),
                ("tx_clk",  ("tx_sst_v5", "clk250_out"), ("digital_v4", "tx_word_clk")),
                ("tx_d0",   ("tx_sst_v5", "din0"), ("digital_v4", "tx_capture_data[0]")),
                ("vco_ip",  ("lc_vco_oct", "ip"),  ("clk_host_5g", "ip")),
                ("vco_qp",  ("lc_vco_oct", "qp"),  ("clk_host_5g", "qp")),
                ("rx_ip",   ("clk_host_5g", "ic_p"), ("rx_top_5g", "ip")),
                ("div_cp",  ("clk_host_5g", "ic_p"), ("div_ab_5g_v2", "clkp")),
                ("tq_dp",   ("clk_host_5g", "ic_p"), ("tx_qdiv2_5g", "dp")),
                ("tx_phi0", ("tx_qdiv2_5g", "ckd0"), ("tx_sst_v5", "phi0")),
                ("vctrl",   ("lf_k4", "ctrl"), ("lc_vco_oct", "vctrl")),
                ("cp_lf",   ("cp_v4", "out"), ("lf_k4", "ctrl")),
                ("fb250",   ("div_ab_5g_v2", "fb250"), ("pfd", "fb")),
                ("vbg_ldo", ("bias_top_v2", "vbg"), ("ldo_kelvin", "bg")),
                ("vbg_tx",  ("bias_top_v2", "vbg"), ("tx_sst_v5", "vbg")),
                ("icml",    ("bias_top_v2", "icml"), ("clk_host_5g", "ibias")),
                ("ictle",   ("bias_top_v2", "ictle"), ("rx_top_5g", "ibias_ctle")),
                ("vcm",     ("bias_top_v2", "vcm"), ("rx_top_5g", "vcm_ref")),
                ("pi_a0",   ("digital_v4", "rx_select_a[0]"), ("rx_top_5g", "a0")),
                ("pi_f7",   ("digital_v4", "rx_fine_b[7]"), ("rx_top_5g", "f7")),
                ("vddq_vco", ("ldo_kelvin", "quiet"), ("lc_vco_oct", "vdd")),
                ("vddq_cp",  ("ldo_kelvin", "quiet"), ("cp_v4", "vdd")),
                ("vdda_clk", ("clk_host_5g", "vdd_clk"), ("div_ab_5g_v2", "vdd")),
                ("vdda_tq",  ("clk_host_5g", "vdd_clk"), ("tx_qdiv2_5g", "vdd")),
                ("vss_all",  ("ldo_kelvin", "vss"), ("rx_top_5g", "vss")),
                ("vss_tx",   ("ldo_kelvin", "vss"), ("tx_sst_v5", "vss")),
                ("vss_dig",  ("ldo_kelvin", "vss"), ("digital_v4", "VGND")),
            ]
            for tag, (ia, pa), (ib, pb) in conn_checks:
                na, nb = gnet(ia, pa), gnet(ib, pb)
                must_conn_res[tag] = {"ok": bool(na and nb and na == nb), "a": na, "b": nb}
            # Critical isolation & 8-domain pairwise separation checks!
            dom_reps = [
                ("HV33", ("ldo_kelvin", "vin")),
                ("BIAS", ("bias_top_v2", "vdd")),
                ("VDDQ", ("ldo_kelvin", "quiet")),
                ("VDDA", ("div_ab_5g_v2", "vdd")),
                ("VDDTX", ("tx_sst_v5", "vdd")),
                ("VDDRX", ("rx_top_5g", "vdd")),
                ("VDDD", ("digital_v4", "VPWR")),
                ("VSS", ("ldo_kelvin", "vss")),
            ]
            diff_checks = [
                ("vco_ip_vs_in", ("lc_vco_oct", "ip"), ("lc_vco_oct", "in")),
                ("vco_qp_vs_qn", ("lc_vco_oct", "qp"), ("lc_vco_oct", "qn")),
                ("vco_ip_vs_qp", ("lc_vco_oct", "ip"), ("lc_vco_oct", "qp")),
                ("vctrl_vs_vdd", ("lc_vco_oct", "vctrl"), ("lc_vco_oct", "vdd")),
                ("vctrl_vs_vss", ("lc_vco_oct", "vctrl"), ("lc_vco_oct", "vss")),
                ("fb250_vs_vss", ("pfd", "fb"), ("ldo_kelvin", "vss")),
                ("icml_vs_vss",  ("bias_top_v2", "icml"), ("ldo_kelvin", "vss")),
                ("rx_in_p_vs_n", ("rx_top_5g", "rxp"), ("rx_top_5g", "rxn")),
                ("tx_pad_p_vs_n", ("tx_sst_v5", "pad_p"), ("tx_sst_v5", "pad_n")),
                ("rx_wd0_vs_wclk", ("rx_top_5g", "wd0"), ("rx_top_5g", "wclk")),
                ("tx_d0_vs_vss", ("tx_sst_v5", "din0"), ("tx_sst_v5", "vss")),
                ("tx_phi0_vs_phi90", ("tx_sst_v5", "phi0"), ("tx_sst_v5", "phi90")),
                ("pi_a0_vs_f7", ("rx_top_5g", "a0"), ("rx_top_5g", "f7")),
            ]
            for i_a in range(len(dom_reps)):
                for i_b in range(i_a + 1, len(dom_reps)):
                    diff_checks.append((f"dom_{dom_reps[i_a][0]}_vs_{dom_reps[i_b][0]}", dom_reps[i_a][1], dom_reps[i_b][1]))
            for tag, (ia, pa), (ib, pb) in diff_checks:
                na, nb = gnet(ia, pa), gnet(ib, pb)
                must_diff_res[tag] = {"ok": bool(na != nb), "a": na, "b": nb}
            hier_ok = all(v["ok"] for v in must_conn_res.values()) and all(v["ok"] for v in must_diff_res.values())
        gds_path = work / f"{top_name}.gds"
        gds_bytes = gds_path.stat().st_size if ("TOP_GDS_OK" in res.log and gds_path.exists()) else 0
        magic_verify = {
            "elapsed_s": round(time.time() - tm0, 1),
            "drc_total": drc_total,
            "drc_rules": drc_rules[:20],
            "gds_bytes": gds_bytes,
            "ext2spice_ok": ext_ok,
            "hier_audit_ok": hier_ok,
            "must_connect_pass": sum(1 for v in must_conn_res.values() if v["ok"]),
            "must_connect_total": len(must_conn_res),
            "must_differ_pass": sum(1 for v in must_diff_res.values() if v["ok"]),
            "must_differ_total": len(must_diff_res),
            "must_connect_fails": {k: v for k, v in must_conn_res.items() if not v["ok"]},
            "must_differ_fails": {k: v for k, v in must_diff_res.items() if not v["ok"]},
        }
        print(
            f"[magic_top_5g] elapsed={magic_verify['elapsed_s']}s | DRC_TOTAL={drc_total} ({len(drc_rules)} rules) | "
            f"GDS={gds_bytes/1048576:.2f}MB | ext2spice={ext_ok} | hier_audit_ok={hier_ok} "
            f"(conn={magic_verify['must_connect_pass']}/{magic_verify['must_connect_total']}, "
            f"diff={magic_verify['must_differ_pass']}/{magic_verify['must_differ_total']})",
            flush=True,
        )
        for r in drc_rules[:10]:
            print(f"    DRC {r['count']:4d} | {r['rule']}", flush=True)

    summary = {
        "cell": top_name,
        "digital_variant": digital_variant,
        "mag": str(top_mag.relative_to(REPO)),
        "png": str(out_png.relative_to(REPO)),
        "core_w_um": core_w,
        "core_h_um": core_h,
        "core_area_mm2": round(core_area / 1e6, 4),
        "aspect_ratio": round(core_w / core_h, 2),
        "active_macro_area_mm2": round(active_area / 1e6, 4),
        "active_macro_density_pct": round(100.0 * active_area / core_area, 1),
        "decap_bank_area_um2": round(decap_area, 1),
        "decap_area_pct": round(100.0 * decap_area / core_area, 1),
        "decap_tile_pitch_um": [px, py],
        "decap_tiles_total": tot_tiles,
        "decap_tiles_breakdown": {"direct_1v8": tot_tiles_dir, "damped_1v8": tot_tiles_dmp, "hv33": tot_tiles_hv},
        "decap_top_cap_pf": tot_top_cap_pf,
        "decap_by_domain": dict(tile_counts),
        "decap_unit_drc_clean": decap_sum["all_drc_clean"],
        "routed_metrics": routed_metrics,
        "top_audit_5g": top_audit,
        "magic_verify": magic_verify,
        "elapsed_s": round(time.time() - t0, 2),
    }
    (work / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"[chip_top_5g] DONE ({summary['elapsed_s']}s): {core_w:.0f}x{core_h:.0f} um = {summary['core_area_mm2']} mm^2 | "
        f"Macro={summary['active_macro_density_pct']}% | Decap={summary['decap_area_pct']}% ({tot_tiles} tiles, {tot_top_cap_pf} pF) | "
        f"RX_crossings={rx_crossings} (max_dx={rx_max_dx:.2f} um) | VCO->CLK={routed_metrics['clk_2p5g_vco_to_host']['avg_hop_um']} um | "
        f"LF->VCO={routed_metrics['pll_loop']['lf_to_vco_vctrl_um']} um",
        flush=True,
    )
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--digital-variant", choices=["v4p1"], default="v4p1")
    ap.add_argument("--drc", action="store_true", help="Run real Magic full-rule top-level DRC check")
    ap.add_argument("--gds", action="store_true", help="Export merged full-chip GDSII")
    ap.add_argument("--extract", action="store_true", help="Run real Magic hierarchical ext2spice connectivity/short audit")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or (REPO / f"results/layout/chip_top_5g_20261126/plan_{args.digital_variant}")
    build_chip_top_5g(out, digital_variant=args.digital_variant, run_drc=args.drc, run_extract=args.extract, export_gds=args.gds)


if __name__ == "__main__":
    main()
