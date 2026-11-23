#!/usr/bin/env python3
"""True-scale, signed-off chip-level floorplan, pin-alignment, interconnect-length,
and damped-PDN void-packing planner for the 4 Gb/s Zero-CML SKY130A SerDes.

Extracts ALL macro bounding boxes, M5 usage, and cardinal port coordinates directly
from the signed-off .mag / .def / summary.json files on disk (ZERO ngspice).

Outputs:
  - results/layout/chip_floorplan_20261123/summary.json
  - docs/figures/system/serdes_chip_floorplan_20261123.png
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / "results/layout/chip_floorplan_20261123/summary.json"
OUT_FIG = ROOT / "docs/figures/system/serdes_chip_floorplan_20261123.png"
PDN_SUMMARY = ROOT / "results/verification/stability_pdn_20261123/summary.json"

# ---------------------------------------------------------------------------
# SKY130A Damped PDN Decap Technology Constants (derived from PDK & layouts)
# ---------------------------------------------------------------------------
# Dual-stacked MIM (sky130_fd_pr__cap_mim_m3_1 + cap_mim_m3_2):
#   Active plate density = 2.0 + 2.0 = 4.00 fF/um^2.
#   With <= 29.4 um tiles, 2.0 um alleys, perimeter rings, and series poly R_damp:
#   packing efficiency ~ 0.85 -> macro-level density = 3.40 fF/um^2.
MIM_ACTIVE_FF_PER_UM2 = 4.00
MIM_MACRO_FF_PER_UM2 = 3.40  # Used for 3.3 V HV33 rail (strictly thin-oxide-free SOA!)

# Dense 1.8 V NMOS-cap under stacked MIM1+MIM2 (M1-M2 nfet_01v8 + M3-M5 MIM1+MIM2):
#   nfet_01v8 Cox = 8.34 fF/um^2 (tox=4.14 nm) * ~0.49 active fill = 4.10 fF/um^2
#   (verified against SKY130A hd__decap_12 = 3.68 fF/um^2 with full std-cell overhead).
#   Hybrid MIM1+MIM2 over NMOS-cap = 3.40 + 4.10 = 7.50 fF/um^2 macro-level!
NMOS_MACRO_FF_PER_UM2 = 4.10
HYBRID_MACRO_FF_PER_UM2 = MIM_MACRO_FF_PER_UM2 + NMOS_MACRO_FF_PER_UM2  # 7.50 fF/um^2

# Target damping time constant tau = R_damp * C_dec:
# Calibrated so chip-level 1.8 V parallel R_damp lands squarely in the 1.5-2.0 Ohm
# optimal PDN anti-resonance window from results/verification/stability_pdn_20261123/summary.json.
TARGET_TAU_DAMP_NS = 1.15


# ---------------------------------------------------------------------------
# Exact Disk Parsers (.mag & .def)
# ---------------------------------------------------------------------------
@dataclass
class RawMacro:
    key: str
    cell_name: str
    source_path: str
    width_um: float
    height_um: float
    area_um2: float
    bbox_orig_um: Tuple[float, float, float, float]
    m5_rects: int
    m5_area_um2: float
    m5_usage_pct: float
    ports_local: Dict[str, Tuple[float, float, str]]  # name -> (rx, ry, layer) in [0..W, 0..H]
    drc_total: int = 0
    lvs_match: bool = True
    internal_cap_pf: float = 0.0
    notes: str = ""


def parse_mag(key: str, rel_path: str, cell_name: str, internal_cap_pf: float = 0.0, notes: str = "") -> RawMacro:
    path = ROOT / rel_path
    lines = path.read_text().splitlines()
    scale_um = 0.005  # SKY130A magscale 1 2 -> 0.005 um per internal unit
    for ln in lines[:20]:
        if ln.startswith("magscale "):
            parts = ln.split()
            scale_um = 0.01 * float(parts[1]) / float(parts[2])
            break

    x0 = y0 = 1e18
    x1 = y1 = -1e18
    m5_rects = 0
    m5_area = 0.0
    cur_layer = None
    raw_ports: Dict[str, Tuple[float, float, str]] = {}

    for i, raw in enumerate(lines):
        s = raw.strip()
        if s.startswith("<< ") and s.endswith(" >>"):
            cur_layer = s[3:-3]
        elif s.startswith("rect ") and cur_layer not in ("labels", "properties", "end"):
            _, ax, ay, bx, by = s.split()
            ax_i, ay_i, bx_i, by_i = int(ax), int(ay), int(bx), int(by)
            if ax_i < x0: x0 = ax_i
            if ay_i < y0: y0 = ay_i
            if bx_i > x1: x1 = bx_i
            if by_i > y1: y1 = by_i
            if cur_layer in ("metal5", "met5", "m5"):
                m5_rects += 1
                m5_area += (bx_i - ax_i) * (by_i - ay_i) * (scale_um ** 2)
        elif (s.startswith("flabel ") or s.startswith("rlabel ")) and i + 1 < len(lines) and lines[i + 1].strip().startswith("port "):
            parts = s.split()
            layer = parts[1]
            cx = (int(parts[2]) + int(parts[4])) * 0.5 * scale_um
            cy = (int(parts[3]) + int(parts[5])) * 0.5 * scale_um
            pname = parts[-1]
            raw_ports[pname] = (cx, cy, layer)

    bx0, by0, bx1, by1 = x0 * scale_um, y0 * scale_um, x1 * scale_um, y1 * scale_um
    w = round(bx1 - bx0, 4)
    h = round(by1 - by0, 4)
    area = round(w * h, 2)
    ports_local = {
        k: (round(cx - bx0, 3), round(cy - by0, 3), lay)
        for k, (cx, cy, lay) in raw_ports.items()
    }
    return RawMacro(
        key=key,
        cell_name=cell_name,
        source_path=rel_path,
        width_um=w,
        height_um=h,
        area_um2=area,
        bbox_orig_um=(round(bx0, 3), round(by0, 3), round(bx1, 3), round(by1, 3)),
        m5_rects=m5_rects,
        m5_area_um2=round(m5_area, 2),
        m5_usage_pct=round(100.0 * m5_area / area, 2) if area > 0 else 0.0,
        ports_local=ports_local,
        internal_cap_pf=internal_cap_pf,
        notes=notes,
    )


def parse_digital_def(key: str, def_rel: str, summary_rel: str) -> RawMacro:
    text = (ROOT / def_rel).read_text()
    summ = json.loads((ROOT / summary_rel).read_text())
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    m_die = re.search(
        r"DIEAREA \(\s*([-\d]+)\s+([-\d]+)\s*\)\s*\(\s*([-\d]+)\s+([-\d]+)\s*\)", text
    )
    dx0, dy0, dx1, dy1 = [int(v) / units for v in m_die.groups()]
    w = round(dx1 - dx0, 4)
    h = round(dy1 - dy0, 4)
    area = round(w * h, 2)

    pins_block = re.search(r"PINS \d+ ;(.*?)END PINS", text, re.S).group(1)
    ports_local: Dict[str, Tuple[float, float, str]] = {}
    for m in re.finditer(
        r"-\s+(\S+)\s+\+\s+NET\s+(\S+).*?\+\s+LAYER\s+(\S+).*?\+\s+PLACED\s+\(\s*([-\d]+)\s+([-\d]+)\s*\)",
        pins_block,
        re.S,
    ):
        pname, _, layer, px, py = m.group(1), m.group(2), m.group(3), int(m.group(4)) / units, int(m.group(5)) / units
        if pname in ("VPWR", "VGND"):
            continue
        ports_local[pname] = (round(px - dx0, 3), round(py - dy0, 3), layer)

    wl_m5 = float(summ["pnr"]["wirelength"]["met5"])
    wl_tot = float(summ["pnr"]["wirelength"]["total_um"])
    decap_pf = float(summ["pnr"]["cell_stats"]["decap_cap_pf"])
    return RawMacro(
        key=key,
        cell_name=summ["block"],
        source_path=def_rel,
        width_um=w,
        height_um=h,
        area_um2=area,
        bbox_orig_um=(dx0, dy0, dx1, dy1),
        m5_rects=int(wl_m5),  # M5 wirelength um reported in summary
        m5_area_um2=round(wl_m5 * 1.6, 2),  # approx 1.6 um M5 width
        m5_usage_pct=round(100.0 * wl_m5 / wl_tot, 2),
        ports_local=ports_local,
        drc_total=int(summ["magic_drc_total"]),
        lvs_match=bool(summ["lvs_match"]),
        internal_cap_pf=decap_pf,
        notes="v3.1 unified HD macro; 249 signal pins (South: PLL[22]|TX[21]|RX[63]); 65.94 pF built-in HD decap",
    )


# ---------------------------------------------------------------------------
# Placement & Geometric Transforms
# ---------------------------------------------------------------------------
def transform_point(rx: float, ry: float, w: float, h: float, orient: str) -> Tuple[float, float]:
    """Transform local (rx, ry) in [0..w, 0..h] to rotated/mirrored local coords."""
    if orient == "R0":
        return (rx, ry)
    if orient == "MX":  # mirror horizontally (flip X): x' = w - rx
        return (w - rx, ry)
    if orient == "MY":  # mirror vertically (flip Y): y' = h - ry
        return (rx, h - ry)
    if orient == "R180":
        return (w - rx, h - ry)
    if orient == "R90":  # 90 deg CCW: (rx, ry) -> (h - ry, rx)
        return (h - ry, rx)
    if orient == "R270":  # 90 deg CW: (rx, ry) -> (ry, w - rx)
        return (ry, w - rx)
    if orient == "R270_MX":  # R270 then mirror X: (rx, ry) -> (h - ry, w - rx)
        return (h - ry, w - rx)
    if orient == "R90_MX":  # R90 then mirror X: (rx, ry) -> (ry, rx)
        return (ry, rx)
    raise ValueError(f"Unsupported orient: {orient}")


def transformed_size(w: float, h: float, orient: str) -> Tuple[float, float]:
    if orient in ("R0", "MX", "MY", "R180"):
        return (w, h)
    return (h, w)


@dataclass
class PlacedMacro:
    inst: str
    raw: RawMacro
    x: float
    y: float
    orient: str
    domain: str       # vdd_hv33, vdd_q, vdd_bias, vdd_a, vdd_tx, vdd_rx, vdd_d
    group: str        # Quiet PLL, BIAS/LDO, Clock Dist, TX v4.3, RX v2.2, Digital v3.1
    quiet_island: bool
    label: str
    short_label: str = ""

    @property
    def w(self) -> float:
        return transformed_size(self.raw.width_um, self.raw.height_um, self.orient)[0]

    @property
    def h(self) -> float:
        return transformed_size(self.raw.width_um, self.raw.height_um, self.orient)[1]

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        return (round(self.x, 3), round(self.y, 3), round(self.x + self.w, 3), round(self.y + self.h, 3))

    @property
    def area(self) -> float:
        return round(self.w * self.h, 2)

    @property
    def center(self) -> Tuple[float, float]:
        return (round(self.x + 0.5 * self.w, 3), round(self.y + 0.5 * self.h, 3))

    def port_xy(self, pname: str) -> Tuple[float, float]:
        rx, ry, _ = self.raw.ports_local[pname]
        tx, ty = transform_point(rx, ry, self.raw.width_um, self.raw.height_um, self.orient)
        return (round(self.x + tx, 3), round(self.y + ty, 3))

    def port_group_center(self, names: List[str]) -> Tuple[float, float]:
        pts = [self.port_xy(n) for n in names if n in self.raw.ports_local]
        if not pts:
            return self.center
        return (
            round(sum(p[0] for p in pts) / len(pts), 3),
            round(sum(p[1] for p in pts) / len(pts), 3),
        )


@dataclass
class DecapBank:
    name: str
    x: float
    y: float
    w: float
    h: float
    domain: str
    tech: str  # "hybrid_mim_nmos" (7.50 fF/um^2) or "stacked_mim_hv33" (3.40 fF/um^2)
    notes: str = ""

    @property
    def rect(self) -> Tuple[float, float, float, float]:
        return (round(self.x, 3), round(self.y, 3), round(self.x + self.w, 3), round(self.y + self.h, 3))

    @property
    def area(self) -> float:
        return round(self.w * self.h, 2)

    @property
    def density_ff_um2(self) -> float:
        return MIM_MACRO_FF_PER_UM2 if self.tech == "stacked_mim_hv33" else HYBRID_MACRO_FF_PER_UM2

    @property
    def cap_pf(self) -> float:
        return round(self.area * self.density_ff_um2 / 1000.0, 2)

    @property
    def r_damp_ohm(self) -> float:
        # Target uniform RC damping time constant tau = 0.90 ns -> parallel 500 pF => 1.80 Ohm
        return round(TARGET_TAU_DAMP_NS * 1000.0 / max(self.cap_pf, 1e-6), 2)


# ---------------------------------------------------------------------------
# Geometry Verification Helpers
# ---------------------------------------------------------------------------
def rect_overlap_area(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    ox = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    oy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ox * oy


def rect_gap_um(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float]) -> float:
    dx = max(0.0, max(a[0] - b[2], b[0] - a[2]))
    dy = max(0.0, max(a[1] - b[3], b[1] - a[3]))
    return math.hypot(dx, dy)


def manhattan(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return round(abs(p1[0] - p2[0]) + abs(p1[1] - p2[1]), 2)


# ---------------------------------------------------------------------------
# Build Inventory & Optimized Floorplan
# ---------------------------------------------------------------------------
def load_inventory() -> Dict[str, RawMacro]:
    inv: Dict[str, RawMacro] = {}
    inv["digital_top_v3"] = parse_digital_def(
        "digital_top_v3",
        "digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/serdes_digital_top_v3.def",
        "digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json",
    )
    inv["tx_sst_top"] = parse_mag(
        "tx_sst_top",
        "analog/tx/sst/layout/variants/v4_pdk/serdes_tx_sst_top_pdk.mag",
        "serdes_tx_sst_top_pdk",
        internal_cap_pf=15.3,
        notes="TX v4.3 Zero-CML 16:1 SST + sst_vdrv_ldo (15.3 pF MIM2)",
    )
    inv["rx_cmos_top"] = parse_mag(
        "rx_cmos_top",
        "analog/rx/cmos_rx/layout/variants/v2_pdk/serdes_rx_cmos_top_pdk.mag",
        "serdes_rx_cmos_top_pdk",
        internal_cap_pf=3.4,
        notes="RX v2.2 Zero-CML Term+CTLE+PI+8xDT-Slicer+1:16 Deser",
    )
    inv["ldo_v2_cur"] = parse_mag(
        "ldo_v2_cur",
        "analog/ldo/layout/variants/v2_cur_pdk/serdes_pll_supply_hv18_v2_cur_pdk.mag",
        "serdes_pll_supply_hv18_v2_cur_pdk",
        internal_cap_pf=60.0,
        notes="HV18 LDO v2 current-mode (3.3V->1.8V quiet, 60.0 pF stacked MIM2)",
    )
    inv["bias_top_v2"] = parse_mag(
        "bias_top_v2",
        "analog/bias/layout/variants/v2_pdk/serdes_bias_top_v2_pdk.mag",
        "serdes_bias_top_v2_pdk",
        internal_cap_pf=8.0,
        notes="BIAS v2 unified macro (FC-OTA BG + Vbuf + 16-tap Pbuf + pcopy, 8 pF MIM2)",
    )
    inv["vco_r6_sym9"] = parse_mag(
        "vco_r6_sym9",
        "analog/pll/vco/layout/variants/sym9_clean/pll_vco_core_sym9_s32p5_clean.mag",
        "pll_vco_core_sym9_s32p5_clean",
        internal_cap_pf=0.0,
        notes="VCO r6 sym9 clean 4-stage CML ring + 4 embedded buffers (0% M5)",
    )
    inv["vco_ptat_bias"] = parse_mag(
        "vco_ptat_bias",
        "analog/pll/vco/layout/variants/ptat_bias_pdk/pll_vco_ptat_bias_pdk.mag",
        "pll_vco_ptat_bias_pdk",
        internal_cap_pf=0.0,
        notes="VCO 28/66 PTAT+const blended tail bias (45/45 3-temp single-code, 0% M5)",
    )
    inv["cp_v4"] = parse_mag(
        "cp_v4",
        "analog/pll/cp/layout/variants/v4_pdk/pll_cp_steer_v4_pdk.mag",
        "pll_cp_steer_v4_pdk",
        internal_cap_pf=0.3,
        notes="Wide-swing active-servo steering CP v4 (0.193% mismatch, 0% M5)",
    )
    inv["lf_k4_fused"] = parse_mag(
        "lf_k4_fused",
        "analog/pll/loop_filter/layout/variants/fused_pdk/pll_loop_filter_k4_fused_pdk.mag",
        "pll_loop_filter_k4_fused_pdk",
        internal_cap_pf=18.0,
        notes="Fused stacked-MIM loop filter (4.13 kOhm / 18 pF + dual precharge)",
    )
    inv["pfd_sc_dly"] = parse_mag(
        "pfd_sc_dly",
        "analog/pll/pfd/layout/variants/pdk/pll_pfd_sc_dly_pdk.mag",
        "pll_pfd_sc_dly_pdk",
        internal_cap_pf=0.0,
        notes="Standard-cell dead-zone-free PFD with dlygate4sd1_1 (0% M5)",
    )
    inv["div8_saff"] = parse_mag(
        "div8_saff",
        "analog/pll/divider/layout/variants/saff_reclock_2g_pdk/pll_saff_reclock_prescaler8_2g_pdk.mag",
        "pll_saff_reclock_prescaler8_2g_pdk",
        internal_cap_pf=0.0,
        notes="2 GHz Zero-CML SAFF-TSPC reclocked /8 prescaler (0% M5)",
    )
    inv["cml2cmos_r5"] = parse_mag(
        "cml2cmos_r5",
        "analog/common/cml_to_cmos/layout/variants/r5_pdk/serdes_cml_to_cmos_r5_pdk.mag",
        "serdes_cml_to_cmos_r5_pdk",
        internal_cap_pf=0.0,
        notes="Full-speed 2 GHz CML->CMOS clock receiver (x4 for 8-ph c0..c7, 0% M5)",
    )
    inv["tx_qdiv2"] = parse_mag(
        "tx_qdiv2",
        "analog/rx/cmos_rx/layout/variants/v2_pdk/serdes_rx_qdiv2_8ph_pdk.mag",
        "serdes_rx_qdiv2_8ph_pdk",
        internal_cap_pf=0.0,
        notes="Deterministic 2 GHz -> 1 GHz quadrature /2 for TX phi0..270 (reused signed-off macro, 0% M5)",
    )
    inv["bias_lpf_slow"] = parse_mag(
        "bias_lpf_slow",
        "analog/ldo/layout/variants/bias_filter_r4_pdk/serdes_pll_bias_lowpass_slow_r4_pdk.mag",
        "serdes_pll_bias_lowpass_slow_r4_pdk",
        internal_cap_pf=16.0,
        notes="1 MOhm / 16 pF VCO tail bias lowpass filter (0% M5)",
    )
    inv["bias_cml_v2"] = parse_mag(
        "bias_cml_v2",
        "analog/bias/layout/variants/v2_pdk/serdes_bias_cml_v2_pdk.mag",
        "serdes_bias_cml_v2_pdk",
        internal_cap_pf=5.0,
        notes="Local CML bias diode + 5 pF stacked MIM2 (x2: VCO PTAT + Host Clock)",
    )
    inv["bias_cp_v2"] = parse_mag(
        "bias_cp_v2",
        "analog/bias/layout/variants/v2_pdk/serdes_bias_cp_v2_pdk.mag",
        "serdes_bias_cp_v2_pdk",
        internal_cap_pf=0.0,
        notes="Local CP bias mirror diode (vbn/vbp, 0% M5)",
    )
    inv["bias_ctle_v2"] = parse_mag(
        "bias_ctle_v2",
        "analog/bias/layout/variants/v2_pdk/serdes_bias_ctle_v2_pdk.mag",
        "serdes_bias_ctle_v2_pdk",
        internal_cap_pf=0.0,
        notes="Local RX CTLE bias diode (0% M5)",
    )
    return inv


def build_floorplan(inv: Dict[str, RawMacro]) -> Tuple[List[PlacedMacro], List[DecapBank], List[Dict]]:
    """Construct the true-scale, zero-overlap, pin-aligned SerDes chip floorplan.

    Die core target: ~835 x 602 um (~0.50 mm^2)
    Topology:
      - West Quiet Analog Island (x = 0 .. 346):
          * Top-West:    DECAP_HV33 (3.3V MIM) + LDO v2_cur (vin on North, quiet on East)
          * Mid-West:    BIAS v2 + VCO PTAT Bias (28/66) + Bias LPF Slow + bias_cml_vco
          * Lower-West:  PFD -> CP v4 -> LF k4_fused -> VCO r6 sym9 (strict W->E signal flow)
          * Bottom-West: Quiet vdd_q & vdd_bias Hybrid Damped Decap Banks
      - Central 24 um Full-Height Substrate Isolation Guard Moat (x = 344 .. 368)
      - East Mixed-Signal & High-Speed Side (x = 368 .. 835):
          * North-East:  Digital v3.1 (x = 497 .. 835.1, y = 294 .. 601.4)
                         South edge: PLL[22] (505..563) | TX[21] (582..613) | RX[63] (622..807)
          * North-Mid:   Large Digital + Clock Hybrid Damped Decap Bay (x = 370 .. 486, y = 294 .. 600)
                         Also provides 154 um substrate spacing from Quiet LDO/BIAS to Digital!
          * South-Mid-W: 4x CML->CMOS r5 (vdd_a) + DIV8 SAFF + bias_cml_host + Clock/TX Decaps
          * South-Mid:   TX v4.3 SST (R270_MX, x = 446 .. 596.6, y = 0 .. 232.5, pad_p/n on South!)
                         + tx_qdiv2 directly North of TX phi0..270 (y = 239 .. 255.6)
          * TX-RX Guard: 43.4 um Shielded Isolation & Local Decap Bay (x = 596.6 .. 640.0)
          * South-East:  RX v2.2 CMOS (R270, x = 640 .. 835.4, y = 0 .. 245.3, rxp/n on South!)
                         c0..c7 at NW corner facing PLL clock spine!
    """
    macros: List[PlacedMacro] = [
        # --- Quiet Power & Bias (North-West, Quiet Analog Island) ---
        PlacedMacro(
            "ldo_v2_cur", inv["ldo_v2_cur"], 12.0, 424.0, "R0",
            "vdd_hv33", "BIAS/LDO", True,
            "HV18 LDO v2_cur\n312.5 x 121.5 um\n(3.3V -> 1.8V quiet, 60 pF MIM2)",
            "LDO v2_cur",
        ),
        PlacedMacro(
            "bias_top_v2", inv["bias_top_v2"], 12.0, 256.0, "R0",
            "vdd_bias", "BIAS/LDO", True,
            "BIAS v2 Top\n176.5 x 152.3 um",
            "BIAS v2",
        ),
        PlacedMacro(
            "vco_ptat_bias", inv["vco_ptat_bias"], 194.0, 346.0, "R0",
            "vdd_bias", "BIAS/LDO", True,
            "VCO PTAT Bias\n148.8 x 61.6 um",
            "PTAT Bias",
        ),
        PlacedMacro(
            "bias_lpf_slow", inv["bias_lpf_slow"], 194.0, 236.0, "R0",
            "vdd_q", "BIAS/LDO", True,
            "Bias LPF Slow\n100.2 x 103.2 um\n(1M / 16 pF)",
            "Bias LPF",
        ),
        PlacedMacro(
            "bias_cml_vco", inv["bias_cml_v2"], 303.0, 278.0, "R90",
            "vdd_bias", "BIAS/LDO", True,
            "CML Bias\nVCO\n29x61",
            "Bias CML_V",
        ),

        # --- Quiet PLL Core (Mid-South-West, linear W->E flow) ---
        # PFD runs on vdd_a (host CMOS), placed with 16 um guard clearance West of CP v4
        PlacedMacro(
            "pfd_sc_dly", inv["pfd_sc_dly"], 6.0, 178.0, "R0",
            "vdd_a", "Clock Dist", False,
            "PFD",
            "PFD",
        ),
        PlacedMacro(
            "bias_cp_v2", inv["bias_cp_v2"], 34.0, 150.0, "R0",
            "vdd_q", "Quiet PLL", True,
            "CPb",
            "Bias CP",
        ),
        PlacedMacro(
            "cp_v4", inv["cp_v4"], 48.0, 158.0, "R0",
            "vdd_q", "Quiet PLL", True,
            "CP v4\n59.0x43.7",
            "CP v4",
        ),
        PlacedMacro(
            "lf_k4_fused", inv["lf_k4_fused"], 115.0, 150.0, "R0",
            "vdd_q", "Quiet PLL", True,
            "Loop Filter k4\n98.3 x 64.9 um\n(18 pF MIM)",
            "LF k4",
        ),
        PlacedMacro(
            "vco_r6_sym9", inv["vco_r6_sym9"], 224.0, 144.0, "R0",
            "vdd_q", "Quiet PLL", True,
            "VCO r6 sym9\n108.6 x 79.8 um\n(2 GHz 8-ph)",
            "VCO r6",
        ),

        # --- Host 2 GHz Clock Distribution (vdd_a, East of 24 um Quiet Moat) ---
        PlacedMacro(
            "cml2cmos_0", inv["cml2cmos_r5"], 368.0, 124.0, "R0",
            "vdd_a", "Clock Dist", False,
            "CML->CMOS #0",
            "C2C 0",
        ),
        PlacedMacro(
            "cml2cmos_1", inv["cml2cmos_r5"], 368.0, 156.0, "R0",
            "vdd_a", "Clock Dist", False,
            "CML->CMOS #1",
            "C2C 1",
        ),
        PlacedMacro(
            "cml2cmos_2", inv["cml2cmos_r5"], 368.0, 188.0, "R0",
            "vdd_a", "Clock Dist", False,
            "CML->CMOS #2",
            "C2C 2",
        ),
        PlacedMacro(
            "cml2cmos_3", inv["cml2cmos_r5"], 368.0, 220.0, "R0",
            "vdd_a", "Clock Dist", False,
            "CML->CMOS #3",
            "C2C 3",
        ),
        PlacedMacro(
            "bias_cml_host", inv["bias_cml_v2"], 368.0, 56.0, "R90",
            "vdd_a", "Clock Dist", False,
            "CML Bias\nHost",
            "Bias CML_H",
        ),
        PlacedMacro(
            "div8_saff", inv["div8_saff"], 368.0, 256.0, "R0",
            "vdd_a", "Clock Dist", False,
            "PLL /8 SAFF (97.3x17.5)",
            "DIV8 SAFF",
        ),

        # --- TX v4.3 Zero-CML SST (South-Center, pad_p/pad_n on South outer edge) ---
        PlacedMacro(
            "tx_sst_top", inv["tx_sst_top"], 446.0, 0.0, "R270_MX",
            "vdd_tx", "TX v4.3", False,
            "TX v4.3 SST 16:1\n150.6 x 232.5 um\n(R270_MX, pad_p/n South)",
            "TX v4.3",
        ),
        # R180 puts 2 GHz dp/dn/ep/en on West (facing 4x CML->CMOS) and 1 GHz ckd0..3 on South (above TX phi0..270)!
        PlacedMacro(
            "tx_qdiv2", inv["tx_qdiv2"], 454.0, 239.0, "R180",
            "vdd_tx", "TX v4.3", False,
            "TX 2G->1G Q-Div2 (122.4x16.6)",
            "TX QDiv2",
        ),

        # --- RX v2.2 Zero-CML (South-East, rxp/rxn on South outer edge, c0..c7 NW) ---
        PlacedMacro(
            "rx_cmos_top", inv["rx_cmos_top"], 650.0, 0.0, "R270",
            "vdd_rx", "RX v2.2", False,
            "RX v2.2 Zero-CML 1:16\n195.4 x 245.3 um\n(R270, rxp/rxn South)",
            "RX v2.2",
        ),
        PlacedMacro(
            "bias_ctle_v2", inv["bias_ctle_v2"], 639.0, 49.0, "R0",
            "vdd_rx", "RX v2.2", False,
            "CTLEb",
            "Bias CTLE",
        ),

        # --- Digital Core v3.1 (North-East, South edge directly above PLL | TX | RX) ---
        PlacedMacro(
            "digital_top_v3", inv["digital_top_v3"], 507.0, 294.0, "R0",
            "vdd_d", "Digital v3.1", False,
            "Digital Core v3.1 (serdes_digital_top_v3)\n338.1 x 307.4 um\n(4,932 std cells, 65.94 pF built-in decap)\nSouth: PLL [22] | TX [21] | RX [63]",
            "Digital v3.1",
        ),
    ]

    # --- Damped PDN Decap Banks (C_bank + R_damp, zero overlap, tucked into EVERY natural void pocket) ---
    # Target >= 500 pF external damped decap across all power rails (+ 65.94 pF digital built-in)
    decaps: List[DecapBank] = [
        # 1. North-West HV33 (3.3 V LDO input) — strictly pure stacked MIM1+MIM2 (3.40 fF/um^2, 3.3V SOA-safe!)
        DecapBank(
            "DECAP_HV33_N", 12.0, 554.0, 312.5, 47.0,
            "vdd_hv33", "stacked_mim_hv33",
            "3.3V-safe pure stacked MIM1+MIM2 directly strapping LDO vin North edge",
        ),
        # 2. South-West Quiet Island Bay (below PFD/CP/LF/VCO)
        DecapBank(
            "DECAP_VDDQ_SW", 162.0, 6.0, 174.0, 128.0,
            "vdd_q", "hybrid_mim_nmos",
            "Quiet PLL supply (vdd_q) damped reservoir directly South of LF & VCO r6",
        ),
        DecapBank(
            "DECAP_BIAS_SW", 12.0, 6.0, 140.0, 128.0,
            "vdd_bias", "hybrid_mim_nmos",
            "Analog bias rail (vdd_bias) damped reservoir in SW Quiet Island pocket",
        ),
        # 3. North-Center Bay (East of 24 um Quiet Moat, West of Digital v3.1)
        DecapBank(
            "DECAP_DIG_W", 370.0, 412.0, 124.0, 189.0,
            "vdd_d", "hybrid_mim_nmos",
            "Primary Digital v3.1 (vdd_d) damped decap bank along West power ring",
        ),
        DecapBank(
            "DECAP_CLKA_NW", 370.0, 294.0, 124.0, 110.0,
            "vdd_a", "hybrid_mim_nmos",
            "Host 2 GHz clock domain (vdd_a) damped decap directly North of DIV8/CML->CMOS",
        ),
        # 4. South-Center TX & Clock Pockets
        DecapBank(
            "DECAP_TX_W", 404.0, 6.0, 34.0, 112.0,
            "vdd_tx", "hybrid_mim_nmos",
            "TX v4.3 local damped decap adjacent to West vdd/vdrv rail",
        ),
        DecapBank(
            "DECAP_CLKA_S", 368.0, 6.0, 30.0, 44.0,
            "vdd_a", "hybrid_mim_nmos",
            "Host CML->CMOS local damped decap South of bias_cml_host",
        ),
        # 5. Shielded TX <-> RX Isolation Bay Decaps (53.4 um bay: 9 um guard each side + 34 um local decap!)
        DecapBank(
            "DECAP_TX_E", 605.0, 168.0, 34.0, 64.0,
            "vdd_tx", "hybrid_mim_nmos",
            "TX v4.3 upper-East damped decap inside TX-RX Faraday shield bay",
        ),
        DecapBank(
            "DECAP_RX_W1", 605.0, 60.0, 34.0, 102.0,
            "vdd_rx", "hybrid_mim_nmos",
            "RX v2.2 primary West damped decap inside TX-RX shield bay",
        ),
        DecapBank(
            "DECAP_RX_W2", 605.0, 6.0, 28.0, 46.0,
            "vdd_rx", "hybrid_mim_nmos",
            "RX v2.2 lower-West damped decap near CTLE/Term (clear of bias_ctle_v2)",
        ),
        DecapBank(
            "DECAP_RX_NE", 820.0, 250.0, 25.0, 38.0,
            "vdd_rx", "hybrid_mim_nmos",
            "RX v2.2 upper-East local decap (strictly East of Digital South RX[63] pins)",
        ),
        # 6. Mid-West BIAS-to-LF Quiet Pocket
        DecapBank(
            "DECAP_BIAS_MID", 12.0, 222.0, 174.0, 26.0,
            "vdd_bias", "hybrid_mim_nmos",
            "Compact damped decap tucked in horizontal pocket between LF/CP and BIAS v2",
        ),
    ]

    # Explicit substrate isolation guard bays (for visualization & audit)
    guard_bays = [
        {
            "name": "MOAT_QUIET_MAIN",
            "x": 343.0, "y": 0.0, "w": 24.5, "h": 601.4,
            "desc": "24.5 um full-height P+/DNW substrate moat separating Quiet Analog Island from Digital/Clock/TX",
        },
        {
            "name": "MOAT_TX_RX",
            "x": 596.6, "y": 0.0, "w": 53.4, "h": 245.3,
            "desc": "53.4 um shielded isolation bay between TX SST driver and RX CTLE/slicer (hosts local decap + dual guard rings)",
        },
        {
            "name": "CHANNEL_DIG_ANA",
            "x": 367.5, "y": 246.0, "w": 477.9, "h": 48.0,
            "desc": "48.0 um horizontal bus + isolation channel between Digital South (PLL|TX|RX) and Analog tops",
        },
    ]
    return macros, decaps, guard_bays


# ---------------------------------------------------------------------------
# Audit & KPI Computation
# ---------------------------------------------------------------------------
def audit_and_compute_kpis(
    macros: List[PlacedMacro],
    decaps: List[DecapBank],
    guard_bays: List[Dict],
) -> Dict:
    # 1. Exact overlap check across ALL macros + ALL decap banks
    all_boxes: List[Tuple[str, Tuple[float, float, float, float]]] = (
        [(f"macro:{m.inst}", m.rect) for m in macros]
        + [(f"decap:{d.name}", d.rect) for d in decaps]
    )
    overlaps = []
    total_overlap_um2 = 0.0
    for i in range(len(all_boxes)):
        for j in range(i + 1, len(all_boxes)):
            oa = rect_overlap_area(all_boxes[i][1], all_boxes[j][1])
            if oa > 1e-6:
                overlaps.append({
                    "a": all_boxes[i][0],
                    "b": all_boxes[j][0],
                    "overlap_um2": round(oa, 3),
                })
                total_overlap_um2 += oa
    assert total_overlap_um2 == 0.0, f"OVERLAP DETECTED: {overlaps}"

    # 2. Core bounding box
    min_x = min(b[1][0] for b in all_boxes)
    min_y = min(b[1][1] for b in all_boxes)
    max_x = max(b[1][2] for b in all_boxes)
    max_y = max(b[1][3] for b in all_boxes)
    # Use origin (0,0) to (max_x, max_y) as chip core bbox
    core_w = round(max_x, 2)
    core_h = round(max_y, 2)
    core_area_um2 = round(core_w * core_h, 2)
    core_area_mm2 = round(core_area_um2 / 1e6, 5)

    # 3. Packing density
    macro_area_um2 = round(sum(m.area for m in macros), 2)
    decap_area_um2 = round(sum(d.area for d in decaps), 2)
    density_before_pct = round(100.0 * macro_area_um2 / core_area_um2, 2)
    density_after_pct = round(100.0 * (macro_area_um2 + decap_area_um2) / core_area_um2, 2)

    # 4. Quiet-to-Noisy isolation audit
    quiet_macros = [m for m in macros if m.quiet_island]
    noisy_macros = [m for m in macros if not m.quiet_island]
    noisy_non_pfd = [m for m in noisy_macros if m.inst != "pfd_sc_dly"]

    min_q_to_major_noisy = 1e9
    min_q_to_major_pair = ("", "")
    for q in quiet_macros:
        for n in noisy_non_pfd:
            g = rect_gap_um(q.rect, n.rect)
            if g < min_q_to_major_noisy:
                min_q_to_major_noisy = g
                min_q_to_major_pair = (q.inst, n.inst)

    m_by_name = {m.inst: m for m in macros}
    pfd_to_cp_gap = round(rect_gap_um(m_by_name["pfd_sc_dly"].rect, m_by_name["cp_v4"].rect), 2)
    tx_to_rx_gap = round(rect_gap_um(m_by_name["tx_sst_top"].rect, m_by_name["rx_cmos_top"].rect), 2)
    dig_to_quiet_gap = round(min(rect_gap_um(m_by_name["digital_top_v3"].rect, q.rect) for q in quiet_macros), 2)
    dig_to_tx_gap = round(rect_gap_um(m_by_name["digital_top_v3"].rect, m_by_name["tx_sst_top"].rect), 2)
    dig_to_rx_gap = round(rect_gap_um(m_by_name["digital_top_v3"].rect, m_by_name["rx_cmos_top"].rect), 2)

    assert min_q_to_major_noisy >= 20.0, f"Quiet-to-noisy gap too small: {min_q_to_major_noisy:.2f} um ({min_q_to_major_pair})"
    assert pfd_to_cp_gap >= 15.0, f"PFD-to-CP guard gap too small: {pfd_to_cp_gap:.2f} um"
    assert tx_to_rx_gap >= 20.0, f"TX-to-RX guard gap too small: {tx_to_rx_gap:.2f} um"

    # 5. Digital South Bus Non-Crossing Verification
    dig = m_by_name["digital_top_v3"]
    south_pins = []
    for pn, (rx, ry, _) in dig.raw.ports_local.items():
        if ry < 1.0:
            gx, gy = dig.port_xy(pn)
            south_pins.append((gx, gy, pn))
    pll_pins = [p for p in south_pins if not p[2].startswith("tx") and not p[2].startswith("rx")]
    tx_pins = [p for p in south_pins if p[2].startswith("tx")]
    rx_pins = [p for p in south_pins if p[2].startswith("rx")]
    pll_x_span = (min(p[0] for p in pll_pins), max(p[0] for p in pll_pins))
    tx_x_span = (min(p[0] for p in tx_pins), max(p[0] for p in tx_pins))
    rx_x_span = (min(p[0] for p in rx_pins), max(p[0] for p in rx_pins))
    assert pll_x_span[1] < tx_x_span[0] and tx_x_span[1] < rx_x_span[0], "Digital South pin bands overlap!"

    # Verify analog targets follow the exact same W->E order (zero major bus crossings!)
    vco_x = m_by_name["vco_r6_sym9"].center[0]
    tx_din_x = m_by_name["tx_sst_top"].port_group_center([f"din{i}" for i in range(16)])[0]
    rx_bus_x = m_by_name["rx_cmos_top"].center[0]
    assert vco_x < tx_din_x < rx_bus_x, "Analog W->E bus ordering violated!"

    # 6. Critical Interconnect Manhattan Wirelengths (exact port-to-port)
    vco = m_by_name["vco_r6_sym9"]
    c2c = [m_by_name[f"cml2cmos_{i}"] for i in range(4)]
    tx = m_by_name["tx_sst_top"]
    txq = m_by_name["tx_qdiv2"]
    rx = m_by_name["rx_cmos_top"]
    ldo = m_by_name["ldo_v2_cur"]
    bias = m_by_name["bias_top_v2"]
    ptat = m_by_name["vco_ptat_bias"]
    lpf = m_by_name["bias_lpf_slow"]
    cp = m_by_name["cp_v4"]
    lf = m_by_name["lf_k4_fused"]
    pfd = m_by_name["pfd_sc_dly"]
    div8 = m_by_name["div8_saff"]

    # VCO b0..b3 -> 4x CML->CMOS inp/inn (non-crossing physical order: b0/b1 North -> #3/#2, b2/b3 South -> #1/#0!)
    vco_to_c2c_pairs = [(0, 3), (1, 2), (2, 1), (3, 0)]
    vco_to_c2c_lens = [
        manhattan(vco.port_group_center([f"b{bi}p", f"b{bi}n"]), c2c[ci].port_group_center(["inp", "inn"]))
        for bi, ci in vco_to_c2c_pairs
    ]
    c2c_out_center = (
        round(sum(c.port_group_center(["outp", "outn"])[0] for c in c2c) / 4.0, 2),
        round(sum(c.port_group_center(["outp", "outn"])[1] for c in c2c) / 4.0, 2),
    )
    txq_in = txq.port_group_center(["dp", "dn", "ep", "en"])
    txq_out = txq.port_group_center(["ckd0", "ckd1", "ckd2", "ckd3"])
    tx_phi = tx.port_group_center(["phi0", "phi90", "phi180", "phi270"])
    rx_c8 = rx.port_group_center([f"c{i}" for i in range(8)])

    # Total 2 GHz clock paths (via 4x CML->CMOS trunk)
    c2c_to_txq = manhattan(c2c_out_center, txq_in)
    txq_to_tx_phi = manhattan(txq_out, tx_phi)
    vco_to_tx_2g_total = round(sum(vco_to_c2c_lens) / 4.0 + c2c_to_txq + txq_to_tx_phi, 2)

    c2c_to_rx_pi = manhattan(c2c_out_center, rx_c8)
    vco_to_rx_pi_total = round(sum(vco_to_c2c_lens) / 4.0 + c2c_to_rx_pi, 2)

    # HS pad positions on outer South edge
    tx_pad = tx.port_group_center(["pad_p", "pad_n"])
    rx_pad = rx.port_group_center(["rxp", "rxn"])
    tx_to_rx_hs_pad_pitch = round(math.hypot(rx_pad[0] - tx_pad[0], rx_pad[1] - tx_pad[1]), 2)

    # Digital South -> PLL / TX / RX channel runs
    dig_pll_ctr = (sum(p[0] for p in pll_pins) / len(pll_pins), dig.y)
    dig_tx_ctr = (sum(p[0] for p in tx_pins) / len(tx_pins), dig.y)
    dig_rx_ctr = (sum(p[0] for p in rx_pins) / len(rx_pins), dig.y)

    critical_routes = {
        "vco_to_cml2cmos_4ph_avg_um": round(sum(vco_to_c2c_lens) / 4.0, 2),
        "vco_to_cml2cmos_4ph_each_um": vco_to_c2c_lens,
        "cml2cmos_to_tx_qdiv2_2g_um": c2c_to_txq,
        "tx_qdiv2_to_tx_phi_1g_um": txq_to_tx_phi,
        "vco_to_tx_total_clk_um": vco_to_tx_2g_total,
        "cml2cmos_to_rx_pi_c0_c7_2g_um": c2c_to_rx_pi,
        "vco_to_rx_pi_total_2g_clk_um": vco_to_rx_pi_total,
        "cml2cmos_to_div8_2g_um": manhattan(c2c[3].port_group_center(["outp", "outn"]), div8.port_group_center(["clkp", "clkn"])),
        "pfd_to_cp_up_dn_um": manhattan(pfd.port_group_center(["up", "dn"]), cp.port_group_center(["up", "dn"])),
        "cp_to_lf_ctrl_um": manhattan(cp.port_xy("out"), lf.port_xy("ctrl")),
        "lf_to_vco_ctrl_um": manhattan(lf.port_xy("ctrl"), vco.port_xy("ctrl")),
        "div8_fb_to_pfd_250m_um": manhattan(div8.port_xy("q8p"), pfd.port_xy("fb")),
        "ldo_quiet_to_vco_vddq_um": manhattan(ldo.port_xy("quiet"), vco.port_xy("vdd_q")),
        "bias_to_ldo_vbg_um": manhattan(bias.port_xy("vbg"), ldo.port_xy("bg")),
        "bias_to_ldo_ildo0_um": manhattan(bias.port_xy("i_ldo0"), ldo.port_xy("i_ldo")),
        "bias_to_vco_ptat_vgi_vg_um": manhattan((bias.rect[2], bias.center[1]), ptat.port_group_center(["vgi", "vg"])),
        "ptat_to_lpf_to_vco_vbias_um": round(
            manhattan(ptat.port_xy("out"), lpf.port_xy("original"))
            + manhattan(lpf.port_xy("filtered"), vco.port_xy("vbias_q")), 2
        ),
        "bias_to_cp_icp_um": manhattan(bias.port_xy("icp"), m_by_name["bias_cp_v2"].port_xy("vbn")),
        "bias_to_tx_vbg_um": manhattan(bias.port_xy("vbg"), tx.port_xy("vbg")),
        "bias_to_rx_ctle_vcm_um": manhattan(bias.port_xy("vcm"), rx.port_xy("vcm_ref")),
        "dig_south_to_vco_cfg_um": manhattan(dig_pll_ctr, vco.port_group_center([f"cfg{i}" for i in range(5)])),
        "dig_south_to_tx_din_um": manhattan(dig_tx_ctr, tx.port_group_center([f"din{i}" for i in range(16)])),
        "dig_south_to_rx_pi_ctrl_um": manhattan(dig_rx_ctr, rx.port_group_center([f"a{i}" for i in range(8)] + [f"b{i}" for i in range(8)])),
        "dig_south_to_rx_deser_um": manhattan(dig_rx_ctr, rx.port_group_center([f"wd{i}" for i in range(16)])),
        "tx_pad_to_south_edge_um": round(tx_pad[1], 2),
        "rx_pad_to_south_edge_um": round(rx_pad[1], 2),
        "tx_to_rx_hs_pad_separation_um": tx_to_rx_hs_pad_pitch,
    }

    # 7. PDN Decap Budget & Domain Summary (also comparing pure stacked-MIM vs Hybrid)
    total_damped_decap_pf = round(sum(d.cap_pf for d in decaps), 2)
    assert total_damped_decap_pf >= 500.0, f"Damped decap below 500 pF: {total_damped_decap_pf}"

    # Effective chip-level parallel R_damp across all damped banks (1 / sum(1/R_i))
    eff_r_damp_all = round(1.0 / sum(1.0 / d.r_damp_ohm for d in decaps), 3)
    # Effective R_damp across 1.8 V domains only (excluding 3.3 V HV33 input bank)
    decaps_1v8 = [d for d in decaps if d.domain != "vdd_hv33"]
    total_damped_1v8_pf = round(sum(d.cap_pf for d in decaps_1v8), 2)
    eff_r_damp_1v8 = round(1.0 / sum(1.0 / d.r_damp_ohm for d in decaps_1v8), 3)

    # Pure MIM vs Hybrid area comparison for 500 pF reference
    pdn_area_comparison = {
        "target_damped_decap_pf": 500.0,
        "pure_stacked_mim": {
            "active_density_ff_um2": MIM_ACTIVE_FF_PER_UM2,
            "macro_density_ff_um2": MIM_MACRO_FF_PER_UM2,
            "active_area_500pf_um2": round(500e3 / MIM_ACTIVE_FF_PER_UM2, 1),
            "macro_area_500pf_um2": round(500e3 / MIM_MACRO_FF_PER_UM2, 1),
            "note": "Dual-stacked cap_mim_m3_1 + cap_mim_m3_2 (0.85 tile/alley/R_damp packing); strictly 3.3V SOA-safe",
        },
        "hybrid_mim_over_nmos": {
            "mim_macro_ff_um2": MIM_MACRO_FF_PER_UM2,
            "nmos_macro_ff_um2": NMOS_MACRO_FF_PER_UM2,
            "total_macro_density_ff_um2": HYBRID_MACRO_FF_PER_UM2,
            "macro_area_500pf_um2": round(500e3 / HYBRID_MACRO_FF_PER_UM2, 1),
            "note": "Stacked M3-M5 MIM1+MIM2 over M1-M2 1.8V nfet_01v8 cap + poly R_damp; 2.21x denser on 1.8V rails",
        },
        "adopted_mixed_plan": {
            "hv33_pure_mim_area_um2": round(sum(d.area for d in decaps if d.tech == "stacked_mim_hv33"), 2),
            "hv33_pure_mim_cap_pf": round(sum(d.cap_pf for d in decaps if d.tech == "stacked_mim_hv33"), 2),
            "rails_1v8_hybrid_area_um2": round(sum(d.area for d in decaps_1v8), 2),
            "rails_1v8_hybrid_cap_pf": total_damped_1v8_pf,
            "total_damped_decap_area_um2": decap_area_um2,
            "total_damped_decap_pf": total_damped_decap_pf,
            "parallel_r_damp_all_ohm": eff_r_damp_all,
            "parallel_r_damp_1v8_ohm": eff_r_damp_1v8,
            "digital_builtin_decap_pf": round(m_by_name["digital_top_v3"].raw.internal_cap_pf, 2),
            "analog_internal_mim_pf": round(sum(m.raw.internal_cap_pf for m in macros if m.inst != "digital_top_v3"), 2),
            "grand_total_onchip_cap_pf": round(
                total_damped_decap_pf + sum(m.raw.internal_cap_pf for m in macros), 2
            ),
        },
    }

    # Domain-by-domain power & decap breakdown
    # TT 1.8 V / 27 C power figures from signed-off module docs
    domain_power_tt_mw = {
        "vdd_hv33": {"power_mw": 21.6, "note": "3.3V -> 1.8V LDO input (~12 mA quiet VCO/CP/LF + LDO dropout)"},
        "vdd_q": {"power_mw": 12.6, "note": "Regulated 1.8V quiet rail (VCO r6 PTAT 11.82 mW + CP v4 0.79 mW; sourced from vdd_hv33)"},
        "vdd_bias": {"power_mw": 0.9, "note": "BIAS v2 core + PTAT + Vbuf/Pbuf (1.8V analog)"},
        "vdd_a": {"power_mw": 6.5, "note": "Host 2 GHz clock domain (4x CML->CMOS r5 + SAFF /8 + PFD)"},
        "vdd_tx": {"power_mw": 15.2, "note": "TX v4.3 16:1 SST (FFE=3 TT 15.17 mW; FFE=0 13.97 mW) + Q-Div2"},
        "vdd_rx": {"power_mw": 19.1, "note": "RX v2.2 Zero-CML (CTLE 1.31 + PI 9.06 + 8x Slicer 5.45 + Deser 3.30 mW)"},
        "vdd_d": {"power_mw": 4.2, "note": "Digital Core v3.1 (4,932 HD cells @ 250/125/62.5 MHz)"},
    }
    domains_summary = {}
    for dom in ("vdd_hv33", "vdd_q", "vdd_bias", "vdd_a", "vdd_tx", "vdd_rx", "vdd_d"):
        dm = [m for m in macros if m.domain == dom]
        dd = [d for d in decaps if d.domain == dom]
        dcap_pf = round(sum(d.cap_pf for d in dd), 2)
        req_ohm = round(1.0 / sum(1.0 / d.r_damp_ohm for d in dd), 2) if dd else None
        domains_summary[dom] = {
            "macro_count": len(dm),
            "macros": [m.inst for m in dm],
            "macro_area_um2": round(sum(m.area for m in dm), 2),
            "internal_cap_pf": round(sum(m.raw.internal_cap_pf for m in dm), 2),
            "damped_decap_banks": [d.name for d in dd],
            "damped_decap_area_um2": round(sum(d.area for d in dd), 2),
            "damped_decap_pf": dcap_pf,
            "parallel_r_damp_ohm": req_ohm,
            "tt_power_mw_est": domain_power_tt_mw[dom]["power_mw"],
            "power_note": domain_power_tt_mw[dom]["note"],
        }

    # Extract key PDN audit highlights from stability_pdn_20261123/summary.json
    pdn_ref = {}
    if PDN_SUMMARY.exists():
        raw_pdn = json.loads(PDN_SUMMARY.read_text())
        ac_rows = raw_pdn["investigation_3_chip_pdn"]["ac_rows"]
        tran_rows = raw_pdn["investigation_3_chip_pdn"]["tran_rows"]
        ac_u = [r for r in ac_rows if r["l_pkg_nh"] == 1.5 and r["c_dec_pf"] == 0.0][0]
        ac_d = [r for r in ac_rows if r["l_pkg_nh"] == 1.5 and r["c_dec_pf"] == 500.0 and r["r_damp_ohm"] == 2.0][0]
        tr_u = [r for r in tran_rows if r["case"] == "L1p5_undamped_30mA"][0]
        tr_d = [r for r in tran_rows if r["case"] == "L1p5_C500_R2p0_30mA"][0]
        pdn_ref = {
            "source": "results/verification/stability_pdn_20261123/summary.json",
            "l_pkg_nh": 1.5,
            "undamped_z_peak_ohm": round(ac_u["z_peak_ohm"], 3),
            "damped_500pf_2ohm_z_peak_ohm": round(ac_d["z_peak_ohm"], 3),
            "undamped_30ma_ripple_pp_mv": round(tr_u["ripple_pp_mv"], 2),
            "damped_500pf_2ohm_30ma_ripple_pp_mv": round(tr_d["ripple_pp_mv"], 2),
            "undamped_post_burst_ring_mv": round(tr_u["post_burst_ring_pp_mv"], 2),
            "damped_post_burst_ring_mv": round(tr_d["post_burst_ring_pp_mv"], 2),
        }

    return {
        "generated_by": "verification/layout/plan_chip_floorplan.py",
        "design": "4 Gb/s Zero-CML SKY130A SerDes Chip-Level Floorplan",
        "die_core": {
            "min_x_um": round(min_x, 2),
            "min_y_um": round(min_y, 2),
            "width_um": core_w,
            "height_um": core_h,
            "area_um2": core_area_um2,
            "area_mm2": core_area_mm2,
            "aspect_ratio": round(core_w / core_h, 3),
        },
        "packing": {
            "macro_count": len(macros),
            "macro_area_um2": macro_area_um2,
            "decap_bank_count": len(decaps),
            "decap_area_um2": decap_area_um2,
            "total_filled_area_um2": round(macro_area_um2 + decap_area_um2, 2),
            "macro_density_before_decap_pct": density_before_pct,
            "total_density_after_decap_pct": density_after_pct,
            "overlap_area_um2": total_overlap_um2,
            "overlap_count": len(overlaps),
        },
        "isolation_audit": {
            "min_quiet_to_major_noisy_gap_um": round(min_q_to_major_noisy, 2),
            "min_quiet_to_major_noisy_pair": list(min_q_to_major_pair),
            "pfd_to_cp_guard_gap_um": pfd_to_cp_gap,
            "tx_to_rx_guard_gap_um": tx_to_rx_gap,
            "digital_to_quiet_island_gap_um": dig_to_quiet_gap,
            "digital_to_tx_gap_um": dig_to_tx_gap,
            "digital_to_rx_gap_um": dig_to_rx_gap,
            "digital_south_bus_bands_x_um": {
                "pll_22": [round(pll_x_span[0], 2), round(pll_x_span[1], 2)],
                "tx_21": [round(tx_x_span[0], 2), round(tx_x_span[1], 2)],
                "rx_63": [round(rx_x_span[0], 2), round(rx_x_span[1], 2)],
            },
            "zero_major_bus_crossings": True,
        },
        "critical_routes_manhattan_um": critical_routes,
        "pdn_decap_budget": pdn_area_comparison,
        "pdn_reference_audit": pdn_ref,
        "domains": domains_summary,
        "macros": [
            {
                "inst": m.inst,
                "cell": m.raw.cell_name,
                "source": m.raw.source_path,
                "domain": m.domain,
                "group": m.group,
                "quiet_island": m.quiet_island,
                "orient": m.orient,
                "orig_w_um": m.raw.width_um,
                "orig_h_um": m.raw.height_um,
                "placed_rect_um": list(m.rect),
                "placed_w_um": round(m.w, 3),
                "placed_h_um": round(m.h, 3),
                "area_um2": m.area,
                "m5_usage_pct": m.raw.m5_usage_pct,
                "port_count": len(m.raw.ports_local),
                "internal_cap_pf": m.raw.internal_cap_pf,
                "drc_total": m.raw.drc_total,
                "lvs_match": m.raw.lvs_match,
                "notes": m.raw.notes,
            }
            for m in macros
        ],
        "decap_banks": [
            {
                "name": d.name,
                "domain": d.domain,
                "tech": d.tech,
                "rect_um": list(d.rect),
                "w_um": d.w,
                "h_um": d.h,
                "area_um2": d.area,
                "density_ff_um2": d.density_ff_um2,
                "cap_pf": d.cap_pf,
                "r_damp_ohm": d.r_damp_ohm,
                "tau_ns": TARGET_TAU_DAMP_NS,
                "notes": d.notes,
            }
            for d in decaps
        ],
        "guard_bays": guard_bays,
    }


# ---------------------------------------------------------------------------
# Publication-Grade True-Scale Floorplan Visualization
# ---------------------------------------------------------------------------
def plot_floorplan(macros: List[PlacedMacro], decaps: List[DecapBank], guard_bays: List[Dict], summary: Dict) -> None:
    OUT_FIG.parent.mkdir(parents=True, exist_ok=True)
    W = summary["die_core"]["width_um"]
    H = summary["die_core"]["height_um"]

    fig = plt.figure(figsize=(15.2, 9.6), dpi=240, facecolor="#ffffff")
    # Main true-scale floorplan axis + right-hand legend/KPI panel
    ax = fig.add_axes([0.055, 0.085, 0.675, 0.815], facecolor="#f9fafb")
    ax_leg = fig.add_axes([0.745, 0.085, 0.240, 0.815], facecolor="#ffffff")
    ax_leg.axis("off")

    # Color palette by architectural group (clean, accessible, high-contrast on white)
    GROUP_STYLE = {
        "Quiet PLL":   ("#dbeafe", "#1d4ed8"),  # soft blue / royal blue
        "BIAS/LDO":    ("#fef3c7", "#b45309"),  # warm amber / dark amber
        "Clock Dist":  ("#e0f2fe", "#0369a1"),  # sky cyan / ocean blue
        "TX v4.3":     ("#fee2e2", "#b91c1c"),  # soft rose / crimson
        "RX v2.2":     ("#dcfce7", "#15803d"),  # soft mint / forest green
        "Digital v3.1":("#ede9fe", "#6d28d9"),  # soft lavender / purple
    }
    DECAP_STYLE = {
        "hybrid_mim_nmos":  ("#f1f5f9", "#475569"),
        "stacked_mim_hv33": ("#fff7ed", "#c2410c"),
    }

    # 1. Die boundary
    ax.add_patch(
        Rectangle((0, 0), W, H, facecolor="#ffffff", edgecolor="#0f172a", linewidth=2.0, zorder=1)
    )

    # 2. Isolation Guard Bays (subtle hatched regions)
    for gb in guard_bays:
        fc = "#fef9c3" if "MOAT" in gb["name"] else "#f3f4f6"
        ec = "#ca8a04" if "MOAT" in gb["name"] else "#9ca3af"
        ax.add_patch(
            Rectangle(
                (gb["x"], gb["y"]), gb["w"], gb["h"],
                facecolor=fc, edgecolor=ec, linewidth=0.9,
                linestyle=":", hatch="///", alpha=0.45, zorder=2,
            )
        )

    # Guard bay subtle labels
    ax.text(
        355.25, 315.0, "24.5 µm P+/DNW Quiet Isolation Moat",
        rotation=90, ha="center", va="center", fontsize=7.6, fontweight="bold",
        color="#854d0e", bbox=dict(boxstyle="round,pad=0.18", fc="#fefce8", ec="#eab308", lw=0.6),
        zorder=18,
    )
    ax.text(
        692.0, 275.0, "Digital South ↔ Analog Channel (0 Crossings)",
        ha="center", va="center", fontsize=7.0, fontweight="bold",
        color="#374151", bbox=dict(boxstyle="round,pad=0.15", fc="#f9fafb", ec="#9ca3af", lw=0.6),
        zorder=18,
    )

    # Quiet Island outer dashed boundary
    ax.add_patch(
        FancyBboxPatch(
            (4.0, 2.0), 339.5, 601.0,
            boxstyle="round,pad=0.0,rounding_size=4.0",
            facecolor="none", edgecolor="#1e40af", linewidth=1.3,
            linestyle=(0, (6, 3)), zorder=3,
        )
    )
    ax.text(
        8.0, 607.5, "QUIET ANALOG ISLAND (vdd_hv33 / vdd_q / vdd_bias)",
        fontsize=7.6, fontweight="bold", color="#1e3a8a", ha="left", va="bottom", zorder=20,
    )

    # 3. Damped PDN Decap Banks
    for d in decaps:
        fc, ec = DECAP_STYLE[d.tech]
        ax.add_patch(
            Rectangle(
                (d.x, d.y), d.w, d.h,
                facecolor=fc, edgecolor=ec, linewidth=1.0,
                hatch="..", alpha=0.88, zorder=4,
            )
        )
        cx, cy = d.x + 0.5 * d.w, d.y + 0.5 * d.h
        dom_tag = d.domain.replace("vdd_", "").upper()
        if d.w >= 90 and d.h >= 40:
            txt = f"{d.name}\n{d.cap_pf:.0f} pF | R={d.r_damp_ohm:.1f} Ω\n({d.w:.0f}×{d.h:.0f} µm)"
            fs = 6.9
            rot = 0
        elif d.w >= 140 and d.h >= 22:
            txt = f"{d.name}: {d.cap_pf:.0f} pF | R={d.r_damp_ohm:.1f} Ω"
            fs = 6.2
            rot = 0
        elif d.h >= 58 and d.w <= 36:
            txt = f"{dom_tag} Decap\n{d.cap_pf:.0f} pF ({d.r_damp_ohm:.0f}Ω)"
            fs = 6.0
            rot = 90
        else:
            short_dom = "CLKA" if dom_tag == "A" else dom_tag
            txt = f"{short_dom}\n{d.cap_pf:.0f} pF"
            fs = 5.1
            rot = 0
        ax.text(
            cx, cy, txt, ha="center", va="center", rotation=rot,
            fontsize=fs, fontweight="bold", color="#1e293b",
            bbox=dict(boxstyle="round,pad=0.10", fc="#ffffff", ec="none", alpha=0.76),
            zorder=12,
        )

    # 4. Signed-Off Functional Macros
    m_by_name = {m.inst: m for m in macros}
    for m in macros:
        fc, ec = GROUP_STYLE[m.group]
        ax.add_patch(
            Rectangle(
                (m.x, m.y), m.w, m.h,
                facecolor=fc, edgecolor=ec, linewidth=1.6, zorder=6,
            )
        )
        cx, cy = m.center
        # Smart non-overlapping labels tailored to exact box dimensions
        if m.inst == "digital_top_v3":
            txt = (
                "Digital Core v3.1 (serdes_digital_top_v3)\n"
                f"{m.w:.1f} × {m.h:.1f} µm  |  103,932 µm²\n"
                "4,932 HD cells  •  65.94 pF built-in decap\n"
                "3-Corner STA + VCS GLS + DRC/LVS Signoff"
            )
            ax.text(cx, cy + 16.0, txt, ha="center", va="center", fontsize=8.6, fontweight="bold", color="#3b0764", zorder=14)
        elif m.inst == "ldo_v2_cur":
            txt = (
                "HV18 LDO v2_cur (serdes_pll_supply_hv18_v2_cur_pdk)\n"
                f"{m.w:.1f} × {m.h:.1f} µm  |  3.3V → 1.8V quiet  •  60 pF MIM2"
            )
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=7.6, fontweight="bold", color="#78350f", zorder=14)
        elif m.inst == "bias_top_v2":
            txt = f"BIAS v2 Top\n{m.w:.1f} × {m.h:.1f} µm\n(BG + Vbuf + Pbuf)"
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=7.8, fontweight="bold", color="#78350f", zorder=14)
        elif m.inst == "vco_ptat_bias":
            txt = f"VCO PTAT Bias (28/66)\n{m.w:.1f} × {m.h:.1f} µm"
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=7.2, fontweight="bold", color="#78350f", zorder=14)
        elif m.inst == "bias_lpf_slow":
            txt = f"Bias LPF Slow\n{m.w:.1f} × {m.h:.1f} µm\n(1 MΩ / 16 pF)"
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=7.0, fontweight="bold", color="#78350f", zorder=14)
        elif m.inst == "bias_cml_vco":
            ax.text(cx, cy, "CML Bias\nVCO\n29×61", ha="center", va="center", rotation=90, fontsize=6.0, fontweight="bold", color="#78350f", zorder=14)
        elif m.inst == "bias_cml_host":
            ax.text(cx, cy, "CML Bias\nHost\n29×61", ha="center", va="center", rotation=90, fontsize=6.0, fontweight="bold", color="#0c4a6e", zorder=14)
        elif m.inst == "vco_r6_sym9":
            txt = f"VCO r6 sym9\n{m.w:.1f} × {m.h:.1f} µm\n(2 GHz 8-ph CML)"
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=7.3, fontweight="bold", color="#1e3a8a", zorder=14)
        elif m.inst == "lf_k4_fused":
            txt = f"Loop Filter k4\n{m.w:.1f} × {m.h:.1f} µm\n(18 pF MIM)"
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=7.0, fontweight="bold", color="#1e3a8a", zorder=14)
        elif m.inst == "cp_v4":
            txt = f"CP v4\n{m.w:.1f}×{m.h:.1f}"
            ax.text(cx, cy, txt, ha="center", va="center", fontsize=6.8, fontweight="bold", color="#1e3a8a", zorder=14)
        elif m.inst.startswith("cml2cmos_"):
            idx = m.inst.split("_")[1]
            ax.text(cx, cy, f"CML→CMOS #{idx}\n54.5×27.6", ha="center", va="center", fontsize=5.8, fontweight="bold", color="#0c4a6e", zorder=14)
        elif m.inst == "div8_saff":
            ax.text(cx, cy, "SAFF /8 (97.3×17.5)", ha="center", va="center", fontsize=6.2, fontweight="bold", color="#0c4a6e", zorder=14)
        elif m.inst == "tx_qdiv2":
            ax.text(cx + 4.0, cy, "TX Q-Div2 (122.4×16.6)", ha="center", va="center", fontsize=6.1, fontweight="bold", color="#7f1d1d", zorder=14)
        elif m.inst == "tx_sst_top":
            txt = (
                "TX v4.3 SST 16:1\n"
                f"{m.w:.1f} × {m.h:.1f} µm\n"
                "(Zero-CML, R270_MX)\n"
                "15.3 pF Vdrv MIM2\n"
                "pad_p/n → South"
            )
            ax.text(cx, cy + 8.0, txt, ha="center", va="center", fontsize=7.8, fontweight="bold", color="#7f1d1d", zorder=14)
        elif m.inst == "rx_cmos_top":
            txt = (
                "RX v2.2 Zero-CML 1:16\n"
                f"{m.w:.1f} × {m.h:.1f} µm\n"
                "(CTLE + PI + 8× Slicer + Deser)\n"
                "(R270, c0..c7 NW)\n"
                "rxp/rxn → South"
            )
            ax.text(cx, cy + 8.0, txt, ha="center", va="center", fontsize=7.8, fontweight="bold", color="#14532d", zorder=14)
        elif m.inst == "pfd_sc_dly":
            ax.annotate(
                "PFD (25.3×5.9)", xy=(cx, m.y + m.h), xytext=(cx + 8.0, m.y + 26.0),
                fontsize=6.2, fontweight="bold", color="#0c4a6e", ha="left", va="bottom",
                arrowprops=dict(arrowstyle="-|>", color="#0369a1", lw=0.8),
                bbox=dict(boxstyle="round,pad=0.12", fc="#f0f9ff", ec="#0369a1", lw=0.5),
                zorder=20,
            )
        elif m.inst == "bias_cp_v2":
            ax.annotate(
                "CP Bias", xy=(cx, m.y), xytext=(cx - 10.0, m.y - 11.0),
                fontsize=5.6, fontweight="bold", color="#1e3a8a", ha="center", va="top",
                arrowprops=dict(arrowstyle="-|>", color="#1d4ed8", lw=0.7),
                bbox=dict(boxstyle="round,pad=0.08", fc="#eff6ff", ec="#1d4ed8", lw=0.4),
                zorder=20,
            )
        elif m.inst == "bias_ctle_v2":
            ax.annotate(
                "CTLEb", xy=(cx, m.y), xytext=(641.5, 24.0),
                fontsize=4.8, fontweight="bold", color="#14532d", ha="center", va="center",
                arrowprops=dict(arrowstyle="-|>", color="#15803d", lw=0.65),
                bbox=dict(boxstyle="round,pad=0.06", fc="#f0fdf4", ec="#15803d", lw=0.4),
                zorder=20,
            )

    # 5. Digital South Pin-Band Badges (exact DEF X-spans!)
    bands = summary["isolation_audit"]["digital_south_bus_bands_x_um"]
    dig_y = m_by_name["digital_top_v3"].y
    band_cfg = [
        ("PLL [22]", bands["pll_22"], "#1d4ed8", "#eff6ff"),
        ("TX [21]",  bands["tx_21"],  "#b91c1c", "#fef2f2"),
        ("RX [63]",  bands["rx_63"],  "#15803d", "#f0fdf4"),
    ]
    for lbl, (bx0, bx1), col, bg in band_cfg:
        ax.plot([bx0, bx1], [dig_y + 2.0, dig_y + 2.0], color=col, linewidth=4.0, solid_capstyle="butt", zorder=15)
        ax.text(
            0.5 * (bx0 + bx1), dig_y + 11.5, lbl,
            ha="center", va="bottom", fontsize=7.0, fontweight="bold", color=col,
            bbox=dict(boxstyle="round,pad=0.14", fc=bg, ec=col, lw=0.7), zorder=16,
        )

    # 6. Color-Coded Critical Signal & Supply Routing Trunks / Flylines
    vco = m_by_name["vco_r6_sym9"]
    c2c = [m_by_name[f"cml2cmos_{i}"] for i in range(4)]
    tx = m_by_name["tx_sst_top"]
    txq = m_by_name["tx_qdiv2"]
    rx = m_by_name["rx_cmos_top"]
    ldo = m_by_name["ldo_v2_cur"]
    bias = m_by_name["bias_top_v2"]
    cp = m_by_name["cp_v4"]
    lf = m_by_name["lf_k4_fused"]
    pfd = m_by_name["pfd_sc_dly"]
    div8 = m_by_name["div8_saff"]

    # (a) 2 GHz Clock Distribution (magenta dashed thick trunk, non-crossing!)
    clk_col = "#c026d3"
    # VCO -> 4x CML->CMOS (physical non-crossing order: b0->#3, b1->#2, b2->#1, b3->#0)
    for bi, ci in [(0, 3), (1, 2), (2, 1), (3, 0)]:
        p_src = vco.port_group_center([f"b{bi}p", f"b{bi}n"])
        p_dst = c2c[ci].port_group_center(["inp", "inn"])
        ax.plot([p_src[0], 348.0, p_dst[0]], [p_src[1], p_dst[1], p_dst[1]],
                color=clk_col, lw=1.2, ls="--", alpha=0.85, zorder=15)
    # 4x CML->CMOS -> horizontal 2 GHz clock spine ABOVE tx_qdiv2 (y=260.5) -> TX QDiv2 & RX PI c0..c7
    c_x = c2c[2].rect[2] + 6.0
    spine_y = 260.5
    ax.plot([c_x, c_x], [c2c[0].center[1], spine_y], color=clk_col, lw=2.0, ls="--", zorder=16)
    rx_c_pt = rx.port_group_center([f"c{i}" for i in range(8)])
    ax.plot([c_x, rx_c_pt[0], rx_c_pt[0]], [spine_y, spine_y, rx_c_pt[1]],
            color=clk_col, lw=2.2, ls="--", zorder=16)
    # Tap to TX QDiv2 West input (dp/dn/ep/en) and TX phi0..270
    txq_in = txq.port_group_center(["dp", "dn", "ep", "en"])
    tx_phi = tx.port_group_center(["phi0", "phi90", "phi180", "phi270"])
    ax.plot([c_x, txq_in[0]], [txq_in[1], txq_in[1]], color=clk_col, lw=1.8, ls="--", zorder=16)
    ax.plot([tx_phi[0], tx_phi[0]], [txq.y, tx_phi[1]], color=clk_col, lw=1.8, ls="-", zorder=16)
    # Tap to DIV8 SAFF
    div8_in = div8.port_group_center(["clkp", "clkn"])
    ax.plot([c_x, div8_in[0]], [spine_y, div8_in[1]], color=clk_col, lw=1.5, ls="--", zorder=16)
    ax.scatter([rx_c_pt[0], tx_phi[0], txq_in[0]], [rx_c_pt[1], tx_phi[1], txq_in[1]],
               s=22, color=clk_col, edgecolor="#ffffff", lw=0.6, zorder=19)

    # (b) Quiet LDO Supply (vdd_q) trunk (dark orange dashed)
    ldo_col = "#d97706"
    q_src = ldo.port_xy("quiet")
    vco_vq = vco.port_xy("vdd_q")
    ax.plot([q_src[0], 338.0, 338.0, vco_vq[0]], [q_src[1], q_src[1], 244.0, vco_vq[1]],
            color=ldo_col, lw=2.0, ls="-.", zorder=15)
    # Quiet LDO branch to LF & CP
    ax.plot([338.0, lf.center[0], cp.center[0]], [233.0, 233.0, cp.rect[3]],
            color=ldo_col, lw=1.4, ls="-.", alpha=0.85, zorder=15)

    # (c) Digital <-> Analog Control Buses (color-coded by bus, ZERO crossings!)
    # PLL [22] bus (blue dotted)
    pll_mid_x = 0.5 * sum(bands["pll_22"])
    ax.plot([pll_mid_x, pll_mid_x, vco.center[0]], [dig_y, 286.0, 286.0], color="#1d4ed8", lw=1.8, ls=":", zorder=16)
    ax.plot([vco.center[0], vco.center[0]], [286.0, vco.rect[3]], color="#1d4ed8", lw=1.6, ls=":", zorder=16)
    # TX [21] bus (crimson dotted) -> straight South to TX din0..15
    tx_mid_x = 0.5 * sum(bands["tx_21"])
    tx_din = tx.port_group_center([f"din{i}" for i in range(16)])
    ax.plot([tx_mid_x, tx_mid_x, tx_din[0]], [dig_y, 265.0, tx_din[1]], color="#b91c1c", lw=1.9, ls=":", zorder=16)
    # RX [63] bus (green dotted) -> straight South to RX PI ctrl & Deser
    rx_mid_x = 0.5 * sum(bands["rx_63"])
    ax.plot([rx_mid_x, rx_mid_x], [dig_y, rx.rect[3]], color="#15803d", lw=2.1, ls=":", zorder=16)

    # (d) 4 Gb/s High-Speed Differential I/O Pads on outer South edge!
    tx_pad = tx.port_group_center(["pad_p", "pad_n"])
    rx_pad = rx.port_group_center(["rxp", "rxn"])
    # TX pad marker & outward arrow
    ax.scatter([tx_pad[0]], [tx_pad[1]], s=55, marker="v", color="#dc2626", edgecolor="#ffffff", lw=0.8, zorder=22)
    ax.annotate(
        "TX HS Diff Pads (txp/txn)\n4 Gb/s SST 50 Ω",
        xy=(tx_pad[0], 0.0), xytext=(tx_pad[0], -33.0),
        ha="center", va="top", fontsize=7.6, fontweight="bold", color="#991b1b",
        arrowprops=dict(arrowstyle="<-", color="#dc2626", lw=1.8),
        bbox=dict(boxstyle="round,pad=0.22", fc="#fef2f2", ec="#dc2626", lw=0.9),
        zorder=22,
    )
    # RX pad marker & inward arrow
    ax.scatter([rx_pad[0]], [rx_pad[1]], s=55, marker="^", color="#16a34a", edgecolor="#ffffff", lw=0.8, zorder=22)
    ax.annotate(
        "RX HS Diff Pads (rxp/rxn)\n4 Gb/s CTLE 100 Ω",
        xy=(rx_pad[0], 0.0), xytext=(rx_pad[0] + 45.0, -33.0),
        ha="center", va="top", fontsize=7.6, fontweight="bold", color="#166534",
        arrowprops=dict(arrowstyle="->", color="#16a34a", lw=1.8),
        bbox=dict(boxstyle="round,pad=0.22", fc="#f0fdf4", ec="#16a34a", lw=0.9),
        zorder=22,
    )
    # Pad-to-pad separation callout
    ax.annotate(
        "", xy=(rx_pad[0], -13.0), xytext=(tx_pad[0], -13.0),
        arrowprops=dict(arrowstyle="<->", color="#334155", lw=1.1), zorder=20,
    )
    ax.text(
        0.5 * (tx_pad[0] + rx_pad[0]), -16.0,
        f"HS Pad Pitch = {summary['critical_routes_manhattan_um']['tx_to_rx_hs_pad_separation_um']:.0f} µm",
        ha="center", va="top", fontsize=6.8, fontweight="bold", color="#334155", zorder=20,
    )

    # Outer North edge callout for LDO 3.3 V vin & Digital Host I/O
    vin_pt = ldo.port_xy("vin")
    ax.annotate(
        "vdd_hv33 (3.3 V)", xy=(vin_pt[0], H), xytext=(vin_pt[0] + 22.0, H + 26.0),
        ha="center", va="bottom", fontsize=7.2, fontweight="bold", color="#9a3412",
        arrowprops=dict(arrowstyle="->", color="#c2410c", lw=1.3), zorder=22,
    )
    ax.text(
        m_by_name["digital_top_v3"].center[0], H + 12.0,
        "North: Digital Host I/O (PLL Status [21] | TX Host [19] | RX Host [29])",
        ha="center", va="bottom", fontsize=7.4, fontweight="bold", color="#5b21b6", zorder=20,
    )

    # Axes formatting (TRUE 1:1 ASPECT RATIO!)
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-18.0, W + 22.0)
    ax.set_ylim(-64.0, H + 50.0)
    ax.set_xlabel("Chip Core X (µm)  —  True 1:1 Scale", fontsize=9.5, fontweight="bold", color="#0f172a")
    ax.set_ylabel("Chip Core Y (µm)", fontsize=9.5, fontweight="bold", color="#0f172a")
    ax.grid(True, linestyle=":", linewidth=0.45, color="#cbd5e1", zorder=0)
    ax.tick_params(labelsize=8.2, colors="#334155")

    fig.suptitle(
        "4 Gb/s Zero-CML SKY130A SerDes — True-Scale Signed-Off Chip Floorplan & Damped-PDN Packing Plan",
        fontsize=12.5, fontweight="bold", color="#0f172a", y=0.968,
    )
    fig.text(
        0.50, 0.932,
        "100% Real Measured .mag / .def Bounding Boxes & Port Coordinates  •  Zero Overlap (0.0 µm²)  •  Zero Major Bus Crossings  •  ≥ 24 µm Quiet Substrate Isolation",
        ha="center", va="center", fontsize=8.8, color="#475569",
    )

    # -----------------------------------------------------------------------
    # Right-Hand Legend & Quantitative KPI Panel (clean, non-overlapping)
    # -----------------------------------------------------------------------
    y_cur = 0.985
    ax_leg.text(0.0, y_cur, "Power Domains & Macros", fontsize=9.4, fontweight="bold", color="#0f172a", va="top")
    y_cur -= 0.036

    legend_items = [
        ("Quiet PLL (vdd_q: VCO, LF, CP)", "#dbeafe", "#1d4ed8", None),
        ("BIAS / HV18 LDO (vdd_hv33, bias)", "#fef3c7", "#b45309", None),
        ("Host 2 GHz Clock (vdd_a: C2C, /8)", "#e0f2fe", "#0369a1", None),
        ("TX v4.3 SST 16:1 (vdd_tx)", "#fee2e2", "#b91c1c", None),
        ("RX v2.2 Zero-CML 1:16 (vdd_rx)", "#dcfce7", "#15803d", None),
        ("Digital Core v3.1 (vdd_d)", "#ede9fe", "#6d28d9", None),
        ("Damped Decap (Hybrid MIM+NMOS)", "#f1f5f9", "#475569", ".."),
        ("Damped Decap (3.3V Pure MIM)", "#fff7ed", "#c2410c", ".."),
        ("Substrate Guard / Routing Bay", "#fef9c3", "#ca8a04", "///"),
    ]
    for lbl, fc, ec, ht in legend_items:
        ax_leg.add_patch(
            Rectangle(
                (0.0, y_cur - 0.020), 0.095, 0.022,
                facecolor=fc, edgecolor=ec, lw=1.1, hatch=ht,
                transform=ax_leg.transAxes, clip_on=False,
            )
        )
        ax_leg.text(0.125, y_cur - 0.009, lbl, fontsize=7.6, color="#1e293b", va="center", transform=ax_leg.transAxes)
        y_cur -= 0.033

    y_cur -= 0.015
    ax_leg.text(0.0, y_cur, "Critical Routing Trunks", fontsize=9.2, fontweight="bold", color="#0f172a", va="top", transform=ax_leg.transAxes)
    y_cur -= 0.032
    line_items = [
        ("2 GHz Clock Spine (VCO→TX/RX)", "#c026d3", "--", 2.0),
        ("Quiet LDO Supply (vdd_q)", "#d97706", "-.", 1.8),
        ("Digital South → PLL [22]", "#1d4ed8", ":", 1.8),
        ("Digital South → TX [21]", "#b91c1c", ":", 1.8),
        ("Digital South → RX [63]", "#15803d", ":", 1.8),
        ("4 Gb/s HS Diff Pads (South)", "#dc2626", "-", 2.0),
    ]
    for lbl, col, ls, lw in line_items:
        ax_leg.plot([0.0, 0.095], [y_cur - 0.008, y_cur - 0.008], color=col, ls=ls, lw=lw, transform=ax_leg.transAxes)
        ax_leg.text(0.125, y_cur - 0.008, lbl, fontsize=7.5, color="#1e293b", va="center", transform=ax_leg.transAxes)
        y_cur -= 0.029

    # KPI Box
    dc = summary["die_core"]
    pk = summary["packing"]
    cr = summary["critical_routes_manhattan_um"]
    iso = summary["isolation_audit"]
    pdn = summary["pdn_decap_budget"]["adopted_mixed_plan"]

    kpi_text = (
        f"FLOORPLAN KPIs (SIGNED-OFF BBOXES)\n"
        f"────────────────────────────────────\n"
        f"Core Size:      {dc['width_um']:.1f} × {dc['height_um']:.1f} µm\n"
        f"Core Area:      {dc['area_mm2']:.4f} mm²  (AR {dc['aspect_ratio']:.2f})\n"
        f"Macros ({pk['macro_count']}):    {pk['macro_area_um2']:,.0f} µm² ({pk['macro_density_before_decap_pct']:.1f}%)\n"
        f"Decap ({pk['decap_bank_count']} bnk): {pk['decap_area_um2']:,.0f} µm²\n"
        f"Total Packing:  {pk['total_density_after_decap_pct']:.1f}%  (Overlap: 0.0 µm²)\n"
        f"────────────────────────────────────\n"
        f"DAMPED PDN DECAP (R_damp = 1.5–2.0 Ω)\n"
        f"External Banks: {pdn['total_damped_decap_pf']:.1f} pF  (R_eq={pdn['parallel_r_damp_all_ohm']:.2f} Ω)\n"
        f"  1.8V Hybrid:  {pdn['rails_1v8_hybrid_cap_pf']:.1f} pF  (7.5 fF/µm²)\n"
        f"  3.3V MIM:     {pdn['hv33_pure_mim_cap_pf']:.1f} pF  (3.4 fF/µm²)\n"
        f"Dig Built-in:   {pdn['digital_builtin_decap_pf']:.1f} pF  (+{pdn['analog_internal_mim_pf']:.0f} pF Ana MIM)\n"
        f"Grand Total C:  {pdn['grand_total_onchip_cap_pf']:.1f} pF on-chip\n"
        f"────────────────────────────────────\n"
        f"CRITICAL 2 GHz & ISOLATION METRICS\n"
        f"VCO → C2C avg:  {cr['vco_to_cml2cmos_4ph_avg_um']:.1f} µm (4-ph CML)\n"
        f"C2C → TX QDiv2: {cr['cml2cmos_to_tx_qdiv2_2g_um']:.1f} µm (2 GHz)\n"
        f"C2C → RX PI 8p: {cr['cml2cmos_to_rx_pi_c0_c7_2g_um']:.1f} µm (2 GHz)\n"
        f"Quiet ↔ Noisy:  ≥ {iso['min_quiet_to_major_noisy_gap_um']:.1f} µm moat\n"
        f"TX ↔ RX Guard:  {iso['tx_to_rx_guard_gap_um']:.1f} µm ({cr['tx_to_rx_hs_pad_separation_um']:.0f} µm pads)\n"
        f"Bus Crossings:  0  (PLL | TX | RX aligned)"
    )
    ax_leg.text(
        0.0, y_cur - 0.020, kpi_text,
        fontsize=6.95, family="monospace", color="#0f172a", va="top", ha="left",
        bbox=dict(boxstyle="round,pad=0.45", fc="#f8fafc", ec="#64748b", lw=1.0),
        transform=ax_leg.transAxes,
    )

    fig.savefig(OUT_FIG, dpi=240, facecolor="#ffffff")
    plt.close(fig)


def main() -> None:
    inv = load_inventory()
    macros, decaps, guard_bays = build_floorplan(inv)
    summary = audit_and_compute_kpis(macros, decaps, guard_bays)

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2) + "\n")
    plot_floorplan(macros, decaps, guard_bays, summary)

    dc = summary["die_core"]
    pk = summary["packing"]
    iso = summary["isolation_audit"]
    cr = summary["critical_routes_manhattan_um"]
    pdn = summary["pdn_decap_budget"]["adopted_mixed_plan"]

    print(f"OK: Chip floorplan signed off with 0.0 um^2 overlap!")
    print(f"  Core: {dc['width_um']:.2f} x {dc['height_um']:.2f} um = {dc['area_mm2']:.5f} mm^2 (AR={dc['aspect_ratio']:.2f})")
    print(f"  Packing: {pk['macro_density_before_decap_pct']:.2f}% macros -> {pk['total_density_after_decap_pct']:.2f}% after damped decap")
    print(f"  Damped Decap: {pdn['total_damped_decap_pf']:.2f} pF (1.8V hybrid {pdn['rails_1v8_hybrid_cap_pf']:.1f} pF + HV33 MIM {pdn['hv33_pure_mim_cap_pf']:.1f} pF), R_eq={pdn['parallel_r_damp_all_ohm']:.3f} Ohm (1.8V R_eq={pdn['parallel_r_damp_1v8_ohm']:.3f} Ohm)")
    print(f"  Grand Total On-Chip C: {pdn['grand_total_onchip_cap_pf']:.2f} pF (incl. {pdn['digital_builtin_decap_pf']:.2f} pF Digital + {pdn['analog_internal_mim_pf']:.1f} pF Analog MIM)")
    print(f"  Isolation: Quiet<->MajorNoisy={iso['min_quiet_to_major_noisy_gap_um']:.2f} um ({iso['min_quiet_to_major_noisy_pair']}), PFD<->CP={iso['pfd_to_cp_guard_gap_um']:.2f} um, TX<->RX={iso['tx_to_rx_guard_gap_um']:.2f} um, Dig<->Quiet={iso['digital_to_quiet_island_gap_um']:.2f} um")
    print(f"  2 GHz Clk: VCO->C2C avg={cr['vco_to_cml2cmos_4ph_avg_um']:.1f} um, C2C->TX_QDiv2={cr['cml2cmos_to_tx_qdiv2_2g_um']:.1f} um, C2C->RX_PI={cr['cml2cmos_to_rx_pi_c0_c7_2g_um']:.1f} um")
    print(f"  HS Pads: TX y={cr['tx_pad_to_south_edge_um']:.2f} um, RX y={cr['rx_pad_to_south_edge_um']:.2f} um, separation={cr['tx_to_rx_hs_pad_separation_um']:.1f} um")
    print(f"  Wrote: {OUT_JSON}")
    print(f"  Wrote: {OUT_FIG}")


if __name__ == "__main__":
    main()
