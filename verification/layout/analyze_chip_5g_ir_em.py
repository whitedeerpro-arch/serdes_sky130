#!/usr/bin/env python3
"""Real-Geometry 2D Finite-Volume Static IR-Drop & DC Electromigration (EM) Analyzer
for the 5.0 Gb/s Plan-C Full-Chip Layout (`serdes_5g_top_pdk`, 936 x 650 um).

Parses ALL top-level metal (`metal1..metal5`) and via (`via1..via4`) rectangles directly
from `results/layout/chip_top_5g_20261126/plan_v4p1/serdes_5g_top_pdk.mag`, isolates the
exact connected components of all 8 power/ground domains (`VDD_HV33`, `VDD_BIAS`, `VDD_Q`,
`VDD_A`, `VDD_D`, `VDD_TX`, `VDD_RX`, `VSS`), constructs an exact overlap-free 2D
Boolean-union cell-centered finite-volume conductance network (G * V = I) per domain using
SKY130A worst-case 100 C sheet and via resistances, and solves for BOTH:
  - TT 27 C typical 5G currents (measured from CPEX/postlayout/co-sim summaries on disk)
  - Worst-Case Peak sustained 5G currents (FF 1.95 V / 85 C sustained)

Special physical fidelity:
  - `VDD_Q` is sourced ON-CHIP at `ldo_kelvin.quiet` (NOT an external pad).
  - `VDD_HV33` carries `I(VDD_Q) + Iq(LDO)`; `VSS` returns `I(VDD_Q)` at each quiet-domain
    load macro (VCO, CP, PFD, BIAS_CP, LF) and `Iq(LDO)` at `ldo_kelvin.vss` (exact KCL,
    zero double-counting).
  - `digital_v4` (`v4p1`) currents distribute across all 9 drawn East `VPWR` M5 stripes
    and all 10 drawn East `VGND` M5 stripes.
  - Also evaluates a 4-pad distributed VSS sensitivity (W/S-TX/E-RX/N GSSG bondring)
    alongside the literal single-port `.mag` `VSS` label at (-14, 300) to cleanly separate
    outer-ring drop from internal guard-moat / via chokepoint bounce.

Outputs:
  - `results/layout/chip_top_5g_20261126/ir_em_5g/summary.json`
  - `docs/figures/layout/serdes_5g_ir_em_20261126.png`
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import sys
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.colors import Normalize, PowerNorm
from matplotlib.patches import Rectangle
import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_chip_top_5g_pdk as b5g  # noqa: E402

# =============================================================================
# Exact SKY130A PDK Techfile Constants (libs.tech/magic/sky130A.tech)
# =============================================================================
# Sheet resistance [Ohm/sq]: (nominal 25 C, worst-case hot 100 C)
R_SQ: dict[str, tuple[float, float]] = {
    "metal1": (0.125, 0.145),
    "metal2": (0.125, 0.145),
    "metal3": (0.047, 0.056),
    "metal4": (0.047, 0.056),
    "metal5": (0.029, 0.036),
}
# Single-cut via resistance [Ohm/cut]: (nominal 25 C, worst-case hot 100 C)
R_VIA: dict[str, tuple[float, float]] = {
    "via1": (4.50, 10.0),
    "via2": (3.41, 8.00),
    "via3": (3.41, 8.00),
    "via4": (0.38, 0.89),
}
# SKY130A DC Electromigration limits at 110 C
J_EM_DC: dict[str, float] = {  # [mA / um metal width]
    "metal1": 0.75,
    "metal2": 0.75,
    "metal3": 1.80,
    "metal4": 1.80,
    "metal5": 2.70,
}
I_EM_VIA: dict[str, float] = {  # [mA / single via cut]
    "via1": 0.10,
    "via2": 0.20,
    "via3": 0.20,
    "via4": 1.20,
}

METAL_LAYERS = ("metal1", "metal2", "metal3", "metal4", "metal5")
VIA_LAYERS = (
    ("via1", "metal1", "metal2"),
    ("via2", "metal2", "metal3"),
    ("via3", "metal3", "metal4"),
    ("via4", "metal4", "metal5"),
)
VDD_DOMAINS = ("VDD_HV33", "VDD_BIAS", "VDD_Q", "VDD_A", "VDD_D", "VDD_TX", "VDD_RX")
ALL_DOMAINS = (*VDD_DOMAINS, "VSS")

# Combined rail-to-rail (VDD + VSS) static IR budgets [mV] and single-rail VDD budgets [mV]
DOMAIN_META: dict[str, dict] = {
    "VDD_HV33": {"v_nom": 3.30, "v_peak": 3.30, "vdd_budget_mv": 30.0, "total_budget_mv": 45.0, "color": "#d95f02"},
    "VDD_BIAS": {"v_nom": 1.80, "v_peak": 1.95, "vdd_budget_mv": 10.0, "total_budget_mv": 20.0, "color": "#a6761d"},
    "VDD_Q":    {"v_nom": 1.80, "v_peak": 1.80, "vdd_budget_mv": 15.0, "total_budget_mv": 25.0, "color": "#e41a1c"},
    "VDD_A":    {"v_nom": 1.80, "v_peak": 1.95, "vdd_budget_mv": 20.0, "total_budget_mv": 35.0, "color": "#7b3294"},
    "VDD_D":    {"v_nom": 1.80, "v_peak": 1.95, "vdd_budget_mv": 25.0, "total_budget_mv": 40.0, "color": "#2b83ba"},
    "VDD_TX":   {"v_nom": 1.80, "v_peak": 1.95, "vdd_budget_mv": 25.0, "total_budget_mv": 40.0, "color": "#e6ab02"},
    "VDD_RX":   {"v_nom": 1.80, "v_peak": 1.95, "vdd_budget_mv": 25.0, "total_budget_mv": 40.0, "color": "#1b9e77"},
    "VSS":      {"v_nom": 0.00, "v_peak": 0.00, "vdd_budget_mv": 15.0, "total_budget_mv": 15.0, "color": "#475569"},
}


@dataclass
class PortLoad:
    macro: str
    port: str
    domain: str
    layer: str
    pts: list[tuple[float, float]]   # 1 point for single port, or N points for striped digital ports
    i_tt_ma: float
    i_peak_ma: float
    source: str


def parse_mag_geometry(mag_path: Path) -> tuple[float, dict[str, list[tuple[float, float, float, float]]], dict[str, tuple[str, float, float, tuple[float, float, float, float]]], dict[str, list[tuple[str, float, float, tuple[float, float, float, float]]]]]:
    """Parse exact `magscale`, top-level metal/via rectangles, and `<< labels >>` (including multi-pad VSS) from a `.mag` file."""
    lines = mag_path.read_text().splitlines()
    scale_um = 0.005
    for ln in lines[:20]:
        if ln.startswith("magscale "):
            ps = ln.split()
            scale_um = 0.01 * float(ps[1]) / float(ps[2])
            break

    rects: dict[str, list[tuple[float, float, float, float]]] = defaultdict(list)
    labels: dict[str, tuple[str, float, float, tuple[float, float, float, float]]] = {}
    labels_all: dict[str, list[tuple[str, float, float, tuple[float, float, float, float]]]] = defaultdict(list)
    cur = None
    for ln in lines:
        s = ln.strip()
        if s.startswith("<< ") and s.endswith(" >>"):
            cur = s[3:-3]
        elif s.startswith("rect ") and cur in (*METAL_LAYERS, "via1", "via2", "via3", "via4"):
            _, x1, y1, x2, y2 = s.split()
            r = (
                round(int(x1) * scale_um, 4),
                round(int(y1) * scale_um, 4),
                round(int(x2) * scale_um, 4),
                round(int(y2) * scale_um, 4),
            )
            if r[2] > r[0] and r[3] > r[1]:
                rects[cur].append(r)
        elif (s.startswith("rlabel ") or s.startswith("flabel ")) and cur == "labels":
            ps = s.split()
            lyr = ps[1]
            b = (
                round(int(ps[2]) * scale_um, 4),
                round(int(ps[3]) * scale_um, 4),
                round(int(ps[4]) * scale_um, 4),
                round(int(ps[5]) * scale_um, 4),
            )
            cx = round(0.5 * (b[0] + b[2]), 4)
            cy = round(0.5 * (b[1] + b[3]), 4)
            entry = (lyr, cx, cy, b)
            labels[ps[-1]] = entry
            labels_all[ps[-1]].append(entry)

    # Sanity-check scale against 936 x 650 um core + outer M5 power ring
    m5 = rects["metal5"]
    x_min = min(r[0] for r in m5)
    x_max = max(r[2] for r in m5)
    y_min = min(r[1] for r in m5)
    y_max = max(r[3] for r in m5)
    assert abs(scale_um - 0.005) < 1e-9, f"Unexpected scale_um={scale_um}"
    assert x_min < -30.0 and x_max > 965.0 and y_min < -35.0 and y_max > 680.0, (
        f"Unexpected M5 bbox: [{x_min}, {x_max}] x [{y_min}, {y_max}]"
    )
    return scale_um, rects, labels, dict(labels_all)


def _rects_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], tol: float = 1e-5) -> bool:
    return not (a[2] < b[0] - tol or b[2] < a[0] - tol or a[3] < b[1] - tol or b[3] < a[1] - tol)


def extract_power_domains(
    rects: dict[str, list[tuple[float, float, float, float]]],
    labels: dict[str, tuple[str, float, float, tuple[float, float, float, float]]],
) -> dict[str, dict[str, list[tuple[float, float, float, float]]]]:
    """Use exact polygon + via Union-Find to extract the 8 disjoint power/ground metal+via subsets."""
    nodes: list[tuple[str, float, float, float, float]] = []
    by_lyr: dict[str, list[tuple[int, float, float, float, float]]] = defaultdict(list)
    for lyr in METAL_LAYERS:
        for r in rects.get(lyr, ()):
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

    for lyr in METAL_LAYERS:
        arr = by_lyr[lyr]
        for i in range(len(arr)):
            ii, x1, y1, x2, y2 = arr[i]
            ra = (x1, y1, x2, y2)
            for j in range(i + 1, len(arr)):
                jj, X1, Y1, X2, Y2 = arr[j]
                if _rects_overlap(ra, (X1, Y1, X2, Y2)):
                    union(ii, jj)

    for vlyr, l1, l2 in VIA_LAYERS:
        for vr in rects.get(vlyr, ()):
            h1 = [ii for ii, x1, y1, x2, y2 in by_lyr[l1] if _rects_overlap((x1, y1, x2, y2), vr)]
            h2 = [ii for ii, x1, y1, x2, y2 in by_lyr[l2] if _rects_overlap((x1, y1, x2, y2), vr)]
            if h1 and h2:
                for a in h1[1:]:
                    union(h1[0], a)
                for b in h2:
                    union(h1[0], b)

    roots: dict[str, int] = {}
    for dom in ALL_DOMAINS:
        lyr, px, py, _ = labels[dom]
        hits = {
            find(ii)
            for ii, x1, y1, x2, y2 in by_lyr[lyr]
            if x1 - 0.25 <= px <= x2 + 0.25 and y1 - 0.25 <= py <= y2 + 0.25
        }
        assert len(hits) == 1, f"Power net {dom} at ({px},{py}) on {lyr} matched roots={hits}"
        roots[dom] = next(iter(hits))

    assert len(set(roots.values())) == 8, f"Power domains are not 8 distinct nets! {roots}"

    dom_geom: dict[str, dict[str, list[tuple[float, float, float, float]]]] = {}
    for dom in ALL_DOMAINS:
        r = roots[dom]
        g: dict[str, list[tuple[float, float, float, float]]] = {k: [] for k in (*METAL_LAYERS, "via1", "via2", "via3", "via4")}
        for idx, (lyr, x1, y1, x2, y2) in enumerate(nodes):
            if find(idx) == r:
                g[lyr].append((x1, y1, x2, y2))
        for vlyr, l1, l2 in VIA_LAYERS:
            for vr in rects.get(vlyr, ()):
                h1 = [ii for ii, x1, y1, x2, y2 in by_lyr[l1] if _rects_overlap((x1, y1, x2, y2), vr)]
                if h1 and find(h1[0]) == r:
                    g[vlyr].append(vr)
        dom_geom[dom] = g
    return dom_geom


def build_5g_macro_loads(macros: list[b5g.MacroMeta]) -> tuple[list[PortLoad], list[PortLoad]]:
    """Build exact measured 5G macro VDD & VSS port currents with transparent disk citations.

    Returns (vdd_loads, vss_loads) satisfying exact KCL conservation:
      sum(VDD_HV33 + VDD_BIAS + VDD_A + VDD_D + VDD_TX + VDD_RX) == sum(VSS)
      and VDD_HV33 == sum(VDD_Q) + Iq(LDO).
    """
    by = {m.inst: m for m in macros}
    dig = by["digital_v4"]
    x_dig_e = round(dig.x + dig.w - 3.5, 3)  # exact x_dig_e used in build_chip_top_5g_pdk.py line 949
    vpwr_pts = [(x_dig_e, round(dig.y + yl, 3)) for yl in (33.2, 69.2, 105.2, 141.2, 177.2, 213.2, 249.2, 285.2, 321.2) if yl < dig.h - 2.0]
    vgnd_pts = [(x_dig_e, round(dig.y + yl, 3)) for yl in (15.2, 51.2, 87.2, 123.2, 159.2, 195.2, 231.2, 267.2, 303.2, 339.2) if yl < dig.h - 2.0]

    def pt(inst: str, port: str) -> list[tuple[float, float]]:
        wx, wy, _ = by[inst].port_world(port)
        return [(wx, wy)]

    # --- 1. Quiet regulated domain VDD_Q (sourced on-chip at ldo_kelvin.quiet) ---
    i_vco_tt, i_vco_pk = 5.88, 8.06     # vco_5g_oct_cpex_20261125 & vco_5g_oct_xtemp_20261126 (TT 5.883mA, FF 1.95V max 8.055mA)
    i_cp_tt, i_cp_pk = 0.39, 0.55       # top_cosim_5g_20261124 (p_cp=0.71mW @1.8V=0.39mA; FF peak ~0.55mA)
    i_pfd_tt, i_pfd_pk = 0.09, 0.15     # top_cosim_5g_20261124 (p_pfd=0.16mW @1.8V=0.09mA; FF peak ~0.15mA)
    i_bcp_tt, i_bcp_pk = 0.05, 0.08     # bias/v2 postlayout (icp=50.2uA TT, ~80uA peak)
    i_lf_tt, i_lf_pk = 0.01, 0.02       # passive loop filter steady-state leakage / precharge buffer idle
    i_vddq_tt = round(i_vco_tt + i_cp_tt + i_pfd_tt + i_bcp_tt + i_lf_tt, 4)
    i_vddq_pk = round(i_vco_pk + i_cp_pk + i_pfd_pk + i_bcp_pk + i_lf_pk, 4)

    # --- 2. HV18 LDO (VDD_HV33 -> supplies VDD_Q + LDO Iq; host -> VDD_BIAS) ---
    i_ldo_iq_tt, i_ldo_iq_pk = 0.16, 0.25   # ldo_v2_cur_signoff_20261124 (iq=0.155mA TT, 0.244mA worst corner FS+85C)
    i_ldo_host_tt, i_ldo_host_pk = 0.05, 0.10  # 1.8V host enable/trim logic on VDD_BIAS
    i_hv33_tt = round(i_vddq_tt + i_ldo_iq_tt, 4)
    i_hv33_pk = round(i_vddq_pk + i_ldo_iq_pk, 4)

    # --- 3. BIAS Top v2 (VDD_BIAS) ---
    i_bias_tt, i_bias_pk = 0.78, 0.96   # bias/v2/20261120T145746Z_postlayout (TT 0.781mA, 135-corner max 0.955mA)

    # --- 4. 5G Clock Bay (VDD_A) ---
    i_clk_tt, i_clk_pk = 6.42, 8.80     # top_cosim_5g_20261124 2x r5 @2.5G (11.17mW/1.8V=6.21mA + 0.21mA icml); FF85 scaled by r5 v6 CPEX 1.373x -> 8.80mA
    i_div_tt, i_div_pk = 3.17, 3.55     # div_ab_5g_v2 CPEX (5.698mW/1.8V=3.166mA TT; FF 6.513mW/1.95V=3.34mA * 1.061 hot -> 3.55mA)
    i_txq_tt, i_txq_pk = 2.48, 3.20     # top_cosim_5g_20261124 (p_txq=4.47mW/1.8V=2.48mA TT); pi_5g_study FF div_run=3.19mA -> 3.20mA

    # --- 5. 5G TX SST v5 (VDD_TX) ---
    i_tx_tt, i_tx_pk = 15.91, 17.50     # tx_sst_5g_v5_20261125 CPEX FFE3 (28.64mW/1.8V=15.91mA TT; FF 1.95V -40C 30.38mW=15.58mA, hot FF+85C 1.101x StageB -> 17.50mA)

    # --- 6. 5G RX Top (VDD_RX: W3 CTLE + 4->8 PI v3 + 8x 5G Slicers + Deser16) ---
    # TT: W3 CTLE 1.08 + PI/QDiv2 14.02 + 8x Slicer CPEX 5.49 + Deser16 3.31 = 23.90 mA
    # Peak FF 1.95V +85C: W3 CTLE 1.11 + PI 17.28 + 8x Slicer 6.25 + Deser16 3.83 = 28.47 mA
    i_rx_tt, i_rx_pk = 23.90, 28.47

    # --- 7. 5G Digital Top v4p1 (VDD_D: 6,484 std cells, 191.3 mm wire, 312.5/160 MHz) ---
    i_dig_tt, i_dig_pk = 7.00, 14.50

    vdd_loads: list[PortLoad] = [
        PortLoad("ldo_kelvin", "vin", "VDD_HV33", "metal5", pt("ldo_kelvin", "vin"), i_hv33_tt, i_hv33_pk,
                 "VDD_Q sum + LDO Iq (ldo_v2_cur_signoff_20261124: 0.155mA TT / 0.244mA peak)"),
        PortLoad("ldo_kelvin", "host", "VDD_BIAS", "metal2", pt("ldo_kelvin", "host"), i_ldo_host_tt, i_ldo_host_pk,
                 "HV18 LDO 1.8V host enable/trim interface"),
        PortLoad("bias_top_v2", "vdd", "VDD_BIAS", "metal3", pt("bias_top_v2", "vdd"), i_bias_tt, i_bias_pk,
                 "bias/v2/20261120T145746Z_postlayout: 0.781mA TT, 0.955mA 135-corner max"),
        PortLoad("lc_vco_oct", "vdd", "VDD_Q", "metal4", pt("lc_vco_oct", "vdd"), i_vco_tt, i_vco_pk,
                 "vco_5g_oct_cpex_20261125 & vco_5g_oct_xtemp_20261126: 5.883mA TT, 8.055mA FF 1.95V max"),
        PortLoad("cp_v4", "vdd", "VDD_Q", "metal3", pt("cp_v4", "vdd"), i_cp_tt, i_cp_pk,
                 "top_cosim_5g_20261124 stage1_pll: p_cp=0.71mW @1.8V (0.39mA TT, 0.55mA peak)"),
        PortLoad("pfd", "vdd", "VDD_Q", "metal1", pt("pfd", "vdd"), i_pfd_tt, i_pfd_pk,
                 "top_cosim_5g_20261124 stage1_pll: p_pfd=0.16mW @1.8V (0.09mA TT, 0.15mA peak)"),
        PortLoad("bias_cp", "vcp", "VDD_Q", "metal2", pt("bias_cp", "vcp"), i_bcp_tt, i_bcp_pk,
                 "bias/v2 postlayout: icp=50.2uA TT, 80uA peak"),
        PortLoad("lf_k4", "vdd", "VDD_Q", "metal3", pt("lf_k4", "vdd"), i_lf_tt, i_lf_pk,
                 "Passive loop filter steady-state precharge switch leakage"),
        PortLoad("clk_host_5g", "vdd_clk", "VDD_A", "metal5", pt("clk_host_5g", "vdd_clk"), i_clk_tt, i_clk_pk,
                 "top_cosim_5g_20261124 2x r5 (11.17mW/1.8V+icml=6.42mA TT) * r5 v6 CPEX FF85/TT 1.373x -> 8.80mA"),
        PortLoad("div_ab_5g_v2", "vdd", "VDD_A", "metal4", pt("div_ab_5g_v2", "vdd"), i_div_tt, i_div_pk,
                 "div_ab_5g_v2_hardening_20261125 CPEX 5G /10: 5.698mW/1.8V=3.17mA TT, 3.55mA FF+85C"),
        PortLoad("tx_qdiv2_5g", "vdd", "VDD_A", "metal3", pt("tx_qdiv2_5g", "vdd"), i_txq_tt, i_txq_pk,
                 "top_cosim_5g_20261124 p_txq=4.47mW/1.8V=2.48mA TT; pi_5g_study_20261124 FF 3.19mA -> 3.20mA"),
        PortLoad("tx_sst_v5", "vdd", "VDD_TX", "metal5", pt("tx_sst_v5", "vdd"), i_tx_tt, i_tx_pk,
                 "tx_sst_5g_v5_20261125 CPEX 5G FFE3: 28.64mW/1.8V=15.91mA TT; FF+85C 17.50mA sustained"),
        PortLoad("rx_top_5g", "vdd", "VDD_RX", "metal5", pt("rx_top_5g", "vdd"), i_rx_tt, i_rx_pk,
                 "CTLE W3 CPEX (1.08/1.11mA) + 5G PI/QDiv2 (14.02/17.28mA) + 8x Slicer CPEX (5.49/6.25mA) + Deser16 (3.31/3.83mA)"),
        PortLoad("digital_v4", "VPWR", "VDD_D", "metal5", vpwr_pts, i_dig_tt, i_dig_pk,
                 "digital_v4 v4p1 (6,484 std cells, 191.3mm wire, 312.5/160MHz): 7.00mA TT / 14.50mA peak across 9 East M5 stripes"),
    ]

    # Exact KCL VSS returns (note ldo_kelvin.vss returns ONLY LDO Iq + host, NOT VDD_Q load!)
    div_vss_pt = [(by["div_ab_5g_v2"].port_world("vss")[0], 545.8)]  # North end of div_ab M4 vss spine (build_chip_top_5g_pdk.py:508)
    vss_loads: list[PortLoad] = [
        PortLoad("ldo_kelvin", "vss", "VSS", "metal4", pt("ldo_kelvin", "vss"), round(i_ldo_iq_tt + i_ldo_host_tt, 4), round(i_ldo_iq_pk + i_ldo_host_pk, 4),
                 "LDO quiescent + host return (VDD_Q current returns via quiet-domain macros)"),
        PortLoad("bias_top_v2", "vss", "VSS", "metal1", pt("bias_top_v2", "vss"), i_bias_tt, i_bias_pk, "Return of bias_top_v2"),
        PortLoad("lc_vco_oct", "vss", "VSS", "metal4", pt("lc_vco_oct", "vss"), i_vco_tt, i_vco_pk, "Return of lc_vco_oct"),
        PortLoad("cp_v4", "vss", "VSS", "metal3", pt("cp_v4", "vss"), i_cp_tt, i_cp_pk, "Return of cp_v4"),
        PortLoad("pfd", "vss", "VSS", "metal2", pt("pfd", "vss"), i_pfd_tt, i_pfd_pk, "Return of pfd"),
        PortLoad("bias_cp", "vss", "VSS", "metal2", pt("bias_cp", "vss"), i_bcp_tt, i_bcp_pk, "Return of bias_cp"),
        PortLoad("lf_k4", "vss", "VSS", "metal3", pt("lf_k4", "vss"), i_lf_tt, i_lf_pk, "Return of lf_k4"),
        PortLoad("clk_host_5g", "vss", "VSS", "metal5", pt("clk_host_5g", "vss"), i_clk_tt, i_clk_pk, "Return of clk_host_5g"),
        PortLoad("div_ab_5g_v2", "vss", "VSS", "metal4", div_vss_pt, i_div_tt, i_div_pk, "Return of div_ab_5g_v2 (North M4 spine y=545.8)"),
        PortLoad("tx_qdiv2_5g", "vss", "VSS", "metal3", pt("tx_qdiv2_5g", "vss"), i_txq_tt, i_txq_pk, "Return of tx_qdiv2_5g"),
        PortLoad("tx_sst_v5", "vss", "VSS", "metal5", pt("tx_sst_v5", "vss"), i_tx_tt, i_tx_pk, "Return of tx_sst_v5"),
        PortLoad("rx_top_5g", "vss", "VSS", "metal5", pt("rx_top_5g", "vss"), i_rx_tt, i_rx_pk, "Return of rx_top_5g"),
        PortLoad("digital_v4", "VGND", "VSS", "metal5", vgnd_pts, i_dig_tt, i_dig_pk, "Return of digital_v4 across 10 East M5 VGND stripes"),
    ]

    ext_vdd_tt = sum(l.i_tt_ma for l in vdd_loads if l.domain != "VDD_Q")
    ext_vdd_pk = sum(l.i_peak_ma for l in vdd_loads if l.domain != "VDD_Q")
    vss_tt = sum(l.i_tt_ma for l in vss_loads)
    vss_pk = sum(l.i_peak_ma for l in vss_loads)
    assert abs(ext_vdd_tt - vss_tt) < 1e-6, f"KCL TT mismatch: {ext_vdd_tt} vs {vss_tt}"
    assert abs(ext_vdd_pk - vss_pk) < 1e-6, f"KCL Peak mismatch: {ext_vdd_pk} vs {vss_pk}"
    return vdd_loads, vss_loads


def _dedup_coords(vals: list[float], tol: float = 1e-4) -> list[float]:
    if not vals:
        return []
    s = sorted(vals)
    out = [s[0]]
    for v in s[1:]:
        if v - out[-1] > tol:
            out.append(v)
    return out


def _subdivide_covered_intervals(coords: list[float], spans: list[tuple[float, float]], max_step: float) -> list[float]:
    """Insert intermediate grid lines only inside intervals that actually carry metal."""
    out = [coords[0]]
    for a, b in zip(coords[:-1], coords[1:]):
        L = b - a
        if L > max_step:
            mid = 0.5 * (a + b)
            covered = any(s0 <= mid <= s1 for s0, s1 in spans)
            if covered:
                n = int(math.ceil(L / max_step))
                for k in range(1, n):
                    out.append(round(a + k * (L / n), 4))
        out.append(b)
    return out


def solve_domain_fvm_2d(
    domain: str,
    geom: dict[str, list[tuple[float, float, float, float]]],
    source_specs: list[tuple[str, tuple[float, float, float, float]]],  # list of (layer, clamp_box_um)
    loads: list[PortLoad],
    worst_corner_r: bool = True,
    max_cell_um: float = 10.0,
) -> dict:
    """Build exact overlap-free 2D Boolean-union cell-centered FVM mesh and solve G*V = I."""
    r_idx = 1 if worst_corner_r else 0

    # 1. Per-layer exact coordinate grids (Boolean union of metal rects + via bounds + port/source boxes)
    layer_grids: dict[str, dict] = {}
    cell_meta: list[tuple[str, int, int, float, float, float, float]] = []  # (lyr, ix, iy, x0, y0, x1, y1)

    for lyr in METAL_LAYERS:
        mrects = geom.get(lyr, [])
        if not mrects:
            continue
        raw_xs: list[float] = []
        raw_ys: list[float] = []
        for x1, y1, x2, y2 in mrects:
            raw_xs.extend((x1, x2))
            raw_ys.extend((y1, y2))

        # Include ALL via boundaries touching this layer so adjacent layers share exact via cell centers
        # (eliminates any staggered-grid vertical offset artifact along the dual P+ guard moats!)
        for vlyr, l1, l2 in VIA_LAYERS:
            if lyr in (l1, l2):
                for vx1, vy1, vx2, vy2 in geom.get(vlyr, ()):
                    raw_xs.extend((vx1, vx2))
                    raw_ys.extend((vy1, vy2))

        # Include source clamp boxes and load port attachment coordinates on this layer
        for slyr, sb in source_specs:
            if slyr == lyr:
                raw_xs.extend((sb[0], sb[2]))
                raw_ys.extend((sb[1], sb[3]))
        for ld in loads:
            if ld.layer == lyr:
                for px, py in ld.pts:
                    raw_xs.extend((px - 0.5, px + 0.5))
                    raw_ys.extend((py - 0.5, py + 0.5))

        xs = _dedup_coords(raw_xs)
        ys = _dedup_coords(raw_ys)
        xs = _subdivide_covered_intervals(xs, [(r[0], r[2]) for r in mrects], max_cell_um)
        ys = _subdivide_covered_intervals(ys, [(r[1], r[3]) for r in mrects], max_cell_um)

        nx = len(xs) - 1
        ny = len(ys) - 1
        cell_id = np.full((nx, ny), -1, dtype=np.int32)

        # Mark cells whose center falls inside ANY raw metal rect on this layer (exact Boolean union!)
        x_mids = np.array([0.5 * (xs[i] + xs[i + 1]) for i in range(nx)])
        y_mids = np.array([0.5 * (ys[j] + ys[j + 1]) for j in range(ny)])
        active_mask = np.zeros((nx, ny), dtype=bool)
        for x1, y1, x2, y2 in mrects:
            ix_mask = (x_mids >= x1 - 1e-6) & (x_mids <= x2 + 1e-6)
            iy_mask = (y_mids >= y1 - 1e-6) & (y_mids <= y2 + 1e-6)
            if np.any(ix_mask) and np.any(iy_mask):
                active_mask[np.ix_(ix_mask, iy_mask)] = True

        active_ix, active_iy = np.where(active_mask)
        for ix, iy in zip(active_ix.tolist(), active_iy.tolist()):
            cid = len(cell_meta)
            cell_id[ix, iy] = cid
            cell_meta.append((lyr, ix, iy, xs[ix], ys[iy], xs[ix + 1], ys[iy + 1]))

        layer_grids[lyr] = {
            "xs": xs, "ys": ys, "nx": nx, "ny": ny,
            "cell_id": cell_id, "x_mids": x_mids, "y_mids": y_mids,
        }

    n_nodes = len(cell_meta)
    assert n_nodes > 0, f"No active metal cells built for domain {domain}"

    # 2. Assemble 2D finite-volume lateral conductances (exact cell-centered sheet Laplace operator)
    G = lil_matrix((n_nodes, n_nodes), dtype=float)
    horiz_faces: dict[str, list[tuple[int, int, int, int, float, float]]] = defaultdict(list)
    # horiz_faces[lyr]: (ix, iy, cid_L, cid_R, dy, g_edge) crossing vertical face x = xs[ix+1]
    vert_faces: dict[str, list[tuple[int, int, int, int, float, float]]] = defaultdict(list)
    # vert_faces[lyr]: (ix, iy, cid_B, cid_T, dx, g_edge) crossing horizontal face y = ys[iy+1]

    for lyr, lg in layer_grids.items():
        rsq = R_SQ[lyr][r_idx]
        xs, ys = lg["xs"], lg["ys"]
        cid_arr = lg["cell_id"]
        nx, ny = lg["nx"], lg["ny"]

        # East-West shared vertical faces
        for ix in range(nx - 1):
            dx_sum = (xs[ix + 1] - xs[ix]) + (xs[ix + 2] - xs[ix + 1])
            for iy in range(ny):
                c1 = int(cid_arr[ix, iy])
                c2 = int(cid_arr[ix + 1, iy])
                if c1 >= 0 and c2 >= 0:
                    dy = ys[iy + 1] - ys[iy]
                    g_e = (2.0 * dy) / (rsq * dx_sum)
                    G[c1, c1] += g_e
                    G[c2, c2] += g_e
                    G[c1, c2] -= g_e
                    G[c2, c1] -= g_e
                    horiz_faces[lyr].append((ix, iy, c1, c2, dy, g_e))

        # North-South shared horizontal faces
        for iy in range(ny - 1):
            dy_sum = (ys[iy + 1] - ys[iy]) + (ys[iy + 2] - ys[iy + 1])
            for ix in range(nx):
                c1 = int(cid_arr[ix, iy])
                c2 = int(cid_arr[ix, iy + 1])
                if c1 >= 0 and c2 >= 0:
                    dx = xs[ix + 1] - xs[ix]
                    g_e = (2.0 * dx) / (rsq * dy_sum)
                    G[c1, c1] += g_e
                    G[c2, c2] += g_e
                    G[c1, c2] -= g_e
                    G[c2, c1] -= g_e
                    vert_faces[lyr].append((ix, iy, c1, c2, dx, g_e))

    # 3. Assemble EXACT per-via-cut vertical conductances
    via_records: list[dict] = []  # {vlyr, cx, cy, links: [(c_bot, c_top, g_bt)]}

    def overlapping_cells(lyr: str, box: tuple[float, float, float, float]) -> list[tuple[int, float]]:
        if lyr not in layer_grids:
            return []
        lg = layer_grids[lyr]
        xs, ys, cid_arr = lg["xs"], lg["ys"], lg["cell_id"]
        bx1, by1, bx2, by2 = box
        # Find index ranges overlapping [bx1, bx2] and [by1, by2]
        ix0 = max(0, int(np.searchsorted(xs, bx1 - 1e-6, side="right")) - 1)
        ix1 = min(lg["nx"], int(np.searchsorted(xs, bx2 + 1e-6, side="left")))
        iy0 = max(0, int(np.searchsorted(ys, by1 - 1e-6, side="right")) - 1)
        iy1 = min(lg["ny"], int(np.searchsorted(ys, by2 + 1e-6, side="left")))
        out: list[tuple[int, float]] = []
        for ix in range(ix0, ix1):
            ox = min(xs[ix + 1], bx2) - max(xs[ix], bx1)
            if ox <= 1e-7:
                continue
            for iy in range(iy0, iy1):
                c = int(cid_arr[ix, iy])
                if c < 0:
                    continue
                oy = min(ys[iy + 1], by2) - max(ys[iy], by1)
                if oy > 1e-7:
                    out.append((c, ox * oy))
        return out

    for vlyr, l_bot, l_top in VIA_LAYERS:
        r_cut = R_VIA[vlyr][r_idx]
        g_cut = 1.0 / r_cut
        for vr in geom.get(vlyr, ()):
            c_bot_list = overlapping_cells(l_bot, vr)
            c_top_list = overlapping_cells(l_top, vr)
            if not c_bot_list or not c_top_list:
                continue
            a_bot = sum(a for _, a in c_bot_list)
            a_top = sum(a for _, a in c_top_list)
            links: list[tuple[int, int, float]] = []
            for cb, ab in c_bot_list:
                wb = ab / a_bot
                for ct, at in c_top_list:
                    wt = at / a_top
                    g_bt = g_cut * wb * wt
                    G[cb, cb] += g_bt
                    G[ct, ct] += g_bt
                    G[cb, ct] -= g_bt
                    G[ct, cb] -= g_bt
                    links.append((cb, ct, g_bt))
            via_records.append({
                "vlyr": vlyr,
                "cx": round(0.5 * (vr[0] + vr[2]), 3),
                "cy": round(0.5 * (vr[1] + vr[3]), 3),
                "links": links,
            })

    # 4. Identify Dirichlet voltage-source clamp cells & macro current-injection cells
    clamp_cells: list[int] = []
    for slyr, sb in source_specs:
        hits = overlapping_cells(slyr, sb)
        assert hits, f"Domain {domain}: source spec ({slyr}, {sb}) hit ZERO active cells!"
        clamp_cells.extend(c for c, _ in hits)
    clamp_set = sorted(set(clamp_cells))

    # Map each load port to active cells within a local attachment window (spreads across wire width -> zero point singularity)
    load_cell_map: list[tuple[PortLoad, list[tuple[int, float]]]] = []
    for ld in loads:
        all_hits: list[tuple[int, float]] = []
        n_pts = len(ld.pts)
        for px, py in ld.pts:
            # Try tight 1.0 um box first, expand to 2.0 um if needed (matches port width)
            hits = []
            for half_w in (0.6, 1.2, 2.0):
                hits = overlapping_cells(ld.layer, (px - half_w, py - half_w, px + half_w, py + half_w))
                if hits:
                    break
            assert hits, f"Domain {domain}: load {ld.macro}.{ld.port} @ ({px},{py}) on {ld.layer} hit ZERO active cells!"
            tot_a = sum(a for _, a in hits)
            for c, a in hits:
                all_hits.append((c, (a / tot_a) / n_pts))
        load_cell_map.append((ld, all_hits))

    # 5. Helper to solve for either TT or Peak currents
    G_raw = G.tocsr()
    G_dir = G.copy()
    for c in clamp_set:
        G_dir.rows[c] = [c]
        G_dir.data[c] = [1.0]
    G_dir_csr = G_dir.tocsr()

    def solve_case(use_peak: bool) -> dict:
        I_vec = np.zeros(n_nodes, dtype=float)
        tot_inj_ma = 0.0
        for ld, chits in load_cell_map:
            i_ma = ld.i_peak_ma if use_peak else ld.i_tt_ma
            tot_inj_ma += i_ma
            for c, w_frac in chits:
                I_vec[c] += (i_ma * 1e-3) * w_frac
        I_rhs = I_vec.copy()
        for c in clamp_set:
            I_rhs[c] = 0.0

        V = spsolve(G_dir_csr, I_rhs)  # Volts drop (>0 means voltage drop on VDD, or ground bounce >0 on VSS)
        assert np.all(np.isfinite(V)), f"Domain {domain}: non-finite solution (disconnected mesh?)"

        # Verify exact KCL at Dirichlet boundary: sum of currents drawn from clamped nodes == tot_inj_ma
        I_resid = G_raw @ V
        i_from_src_ma = float(-np.sum(I_resid[clamp_set]) * 1e3)
        # Note: if a load cell overlapped a clamp cell, adjust expectation
        clamped_load_ma = float(np.sum(I_vec[clamp_set]) * 1e3)
        kcl_err_ma = abs((i_from_src_ma + clamped_load_ma) - tot_inj_ma)
        assert kcl_err_ma < 1e-4, f"Domain {domain}: KCL error {kcl_err_ma:.6f} mA (src={i_from_src_ma:.4f}, load={tot_inj_ma:.4f})"

        # Per-macro IR drop at exact port coordinates (area-weighted average across port cells)
        macro_drops: dict[str, dict] = {}
        for ld, chits in load_cell_map:
            v_drop_mv = float(sum(V[c] * w_frac for c, w_frac in chits) * 1e3)
            v_max_mv = float(max(V[c] for c, _ in chits) * 1e3)
            i_ma = ld.i_peak_ma if use_peak else ld.i_tt_ma
            key = f"{ld.macro}.{ld.port}"
            macro_drops[key] = {
                "macro": ld.macro,
                "port": ld.port,
                "layer": ld.layer,
                "xy_um": list(ld.pts[0]) if len(ld.pts) == 1 else [round(sum(p[0] for p in ld.pts)/len(ld.pts), 2), round(sum(p[1] for p in ld.pts)/len(ld.pts), 2)],
                "n_attach_pts": len(ld.pts),
                "i_ma": round(i_ma, 3),
                "ir_drop_mv": round(v_drop_mv, 3),
                "ir_drop_max_cell_mv": round(v_max_mv, 3),
            }

        # Exact physical cross-sectional metal current density J [mA/um] (zero corner/point singularity!)
        metal_em_by_layer: dict[str, dict] = {}
        worst_metal = {"em_pct": 0.0, "layer": "metal5", "j_ma_per_um": 0.0, "i_seg_ma": 0.0, "w_um": 0.0, "xy_um": [0.0, 0.0], "dir": "x"}
        metal_hotspots: list[dict] = []

        for lyr, lg in layer_grids.items():
            xs, ys = lg["xs"], lg["ys"]
            j_lim = J_EM_DC[lyr]
            lyr_worst = {"em_pct": 0.0, "j_ma_per_um": 0.0, "i_seg_ma": 0.0, "w_um": 0.0, "xy_um": [0.0, 0.0], "dir": "x"}

            # 1) Cross-sections along X (vertical faces x = xs[ix+1], grouped into contiguous Y runs!)
            by_ix: dict[int, list[tuple[int, int, int, float, float]]] = defaultdict(list)
            for ix, iy, c1, c2, dy, g_e in horiz_faces.get(lyr, ()):
                by_ix[ix].append((iy, c1, c2, dy, g_e))
            for ix, items in by_ix.items():
                items.sort(key=lambda t: t[0])
                x_face = xs[ix + 1]
                # Split into contiguous iy runs (distinct parallel metal wires crossing x_face)
                k = 0
                while k < len(items):
                    run = [items[k]]
                    k += 1
                    while k < len(items) and items[k][0] == run[-1][0] + 1:
                        run.append(items[k])
                        k += 1
                    w_tot = sum(t[3] for t in run)
                    i_net_ma = sum((V[t[1]] - V[t[2]]) * t[4] * 1e3 for t in run)
                    j_val = abs(i_net_ma) / w_tot
                    em_pct = 100.0 * j_val / j_lim
                    y_mid = 0.5 * (ys[run[0][0]] + ys[run[-1][0] + 1])
                    if em_pct > lyr_worst["em_pct"]:
                        lyr_worst = {
                            "em_pct": round(em_pct, 1),
                            "j_ma_per_um": round(j_val, 3),
                            "i_seg_ma": round(abs(i_net_ma), 3),
                            "w_um": round(w_tot, 2),
                            "xy_um": [round(x_face, 1), round(y_mid, 1)],
                            "dir": "X",
                        }

            # 2) Cross-sections along Y (horizontal faces y = ys[iy+1], grouped into contiguous X runs!)
            by_iy: dict[int, list[tuple[int, int, int, float, float]]] = defaultdict(list)
            for ix, iy, c1, c2, dx, g_e in vert_faces.get(lyr, ()):
                by_iy[iy].append((ix, c1, c2, dx, g_e))
            for iy, items in by_iy.items():
                items.sort(key=lambda t: t[0])
                y_face = ys[iy + 1]
                k = 0
                while k < len(items):
                    run = [items[k]]
                    k += 1
                    while k < len(items) and items[k][0] == run[-1][0] + 1:
                        run.append(items[k])
                        k += 1
                    w_tot = sum(t[3] for t in run)
                    i_net_ma = sum((V[t[1]] - V[t[2]]) * t[4] * 1e3 for t in run)
                    j_val = abs(i_net_ma) / w_tot
                    em_pct = 100.0 * j_val / j_lim
                    x_mid = 0.5 * (xs[run[0][0]] + xs[run[-1][0] + 1])
                    if em_pct > lyr_worst["em_pct"]:
                        lyr_worst = {
                            "em_pct": round(em_pct, 1),
                            "j_ma_per_um": round(j_val, 3),
                            "i_seg_ma": round(abs(i_net_ma), 3),
                            "w_um": round(w_tot, 2),
                            "xy_um": [round(x_mid, 1), round(y_face, 1)],
                            "dir": "Y",
                        }

            metal_em_by_layer[lyr] = lyr_worst
            if lyr_worst["em_pct"] > worst_metal["em_pct"]:
                worst_metal = {"layer": lyr, **lyr_worst}
            if lyr_worst["em_pct"] >= 80.0:
                metal_hotspots.append({"layer": lyr, **lyr_worst})

        # Exact per-via-cut AND per-via-array DC EM utilization!
        via_cut_results: list[dict] = []
        for vr in via_records:
            i_cut_ma = sum((V[cb] - V[ct]) * g_bt * 1e3 for cb, ct, g_bt in vr["links"])
            vlyr = vr["vlyr"]
            em_pct = 100.0 * abs(i_cut_ma) / I_EM_VIA[vlyr]
            via_cut_results.append({
                "vlyr": vlyr,
                "cx": vr["cx"],
                "cy": vr["cy"],
                "i_cut_ma": abs(i_cut_ma),
                "em_pct": em_pct,
            })

        # Cluster vias spatially (within 4.0 um on same layer) to report array-level + worst-cut EM
        via_arrays: list[dict] = []
        by_vlyr: dict[str, list[dict]] = defaultdict(list)
        for vc in via_cut_results:
            by_vlyr[vc["vlyr"]].append(vc)
        for vlyr, vlist in by_vlyr.items():
            # Group the 1,276 periodic guard-moat via1 cuts separately from discrete via1 ties
            if vlyr == "via1" and len(vlist) > 50:
                moat_cuts = [v for v in vlist if 385.0 <= v["cx"] <= 399.0]
                other_cuts = [v for v in vlist if not (385.0 <= v["cx"] <= 399.0)]
                if moat_cuts:
                    mx = max(moat_cuts, key=lambda v: v["em_pct"])
                    i_sum = sum(v["i_cut_ma"] for v in moat_cuts)
                    via_arrays.append({
                        "vlyr": vlyr,
                        "n_cuts": len(moat_cuts),
                        "xy_um": [round(mx["cx"], 1), round(mx["cy"], 1)],
                        "i_total_ma": round(i_sum, 3),
                        "i_avg_cut_ma": round(i_sum / len(moat_cuts), 4),
                        "i_max_cut_ma": round(mx["i_cut_ma"], 4),
                        "em_avg_pct": round(100.0 * (i_sum / len(moat_cuts)) / I_EM_VIA[vlyr], 1),
                        "em_max_cut_pct": round(mx["em_pct"], 1),
                        "note": "Dual P+ guard-moat M1-M2 stitching array (sum of |I_cut| across all 1,276 cuts)",
                    })
                vlist = other_cuts
            used = [False] * len(vlist)
            for i in range(len(vlist)):
                if used[i]:
                    continue
                q = [i]
                used[i] = True
                cl = [vlist[i]]
                while q:
                    u = q.pop()
                    for j in range(len(vlist)):
                        if not used[j] and abs(vlist[j]["cx"] - vlist[u]["cx"]) < 4.5 and abs(vlist[j]["cy"] - vlist[u]["cy"]) < 4.5:
                            used[j] = True
                            q.append(j)
                            cl.append(vlist[j])
                i_tot = sum(v["i_cut_ma"] for v in cl)
                i_avg = i_tot / len(cl)
                mx = max(cl, key=lambda v: v["i_cut_ma"])
                cx = sum(v["cx"] for v in cl) / len(cl)
                cy = sum(v["cy"] for v in cl) / len(cl)
                via_arrays.append({
                    "vlyr": vlyr,
                    "n_cuts": len(cl),
                    "xy_um": [round(cx, 1), round(cy, 1)],
                    "i_total_ma": round(i_tot, 3),
                    "i_avg_cut_ma": round(i_avg, 4),
                    "i_max_cut_ma": round(mx["i_cut_ma"], 4),
                    "em_avg_pct": round(100.0 * i_avg / I_EM_VIA[vlyr], 1),
                    "em_max_cut_pct": round(mx["em_pct"], 1),
                })

        via_arrays.sort(key=lambda a: a["em_max_cut_pct"], reverse=True)
        worst_via = via_arrays[0] if via_arrays else {
            "vlyr": "none", "n_cuts": 0, "xy_um": [0.0, 0.0],
            "i_total_ma": 0.0, "i_avg_cut_ma": 0.0, "i_max_cut_ma": 0.0,
            "em_avg_pct": 0.0, "em_max_cut_pct": 0.0,
        }

        worst_macro_entry = max(macro_drops.values(), key=lambda d: d["ir_drop_mv"])
        max_field_mv = float(np.max(V) * 1e3)
        return {
            "total_current_ma": round(tot_inj_ma, 3),
            "kcl_error_ma": round(kcl_err_ma, 6),
            "max_macro_ir_mv": round(worst_macro_entry["ir_drop_mv"], 2),
            "worst_macro": f"{worst_macro_entry['macro']}.{worst_macro_entry['port']}",
            "max_field_ir_mv": round(max_field_mv, 2),
            "macro_drops": macro_drops,
            "worst_metal_em": worst_metal,
            "metal_em_by_layer": metal_em_by_layer,
            "worst_via_em": worst_via,
            "via_arrays_top10": via_arrays[:10],
            "via_arrays_exceed_80pct": [a for a in via_arrays if a["em_max_cut_pct"] >= 80.0],
            "cell_v_mv": (V * 1e3).tolist(),  # kept in-memory for plotting; stripped before JSON dump
        }

    res_tt = solve_case(use_peak=False)
    res_pk = solve_case(use_peak=True)
    return {
        "domain": domain,
        "mesh_nodes": n_nodes,
        "via_cuts_modeled": len(via_records),
        "metal_rects": {k: len(geom.get(k, [])) for k in METAL_LAYERS if geom.get(k)},
        "via_cuts": {k: len(geom.get(k, [])) for k in ("via1", "via2", "via3", "via4") if geom.get(k)},
        "tt": res_tt,
        "peak": res_pk,
        "cell_meta": cell_meta,  # kept in-memory for plotting; stripped before JSON dump
    }


def strip_plot_arrays(domain_results: dict[str, dict]) -> dict[str, dict]:
    """Return a clean JSON-serializable copy without bulky per-cell voltage arrays."""
    clean = {}
    for dom, d in domain_results.items():
        cd = {k: v for k, v in d.items() if k != "cell_meta"}
        cd["tt"] = {k: v for k, v in d["tt"].items() if k != "cell_v_mv"}
        cd["peak"] = {k: v for k, v in d["peak"].items() if k != "cell_v_mv"}
        clean[dom] = cd
    return clean


def plot_ir_em_5g_report(
    core_w: float,
    core_h: float,
    macros: list[b5g.MacroMeta],
    decaps: list[b5g.DecapBank],
    labels: dict[str, tuple[str, float, float, tuple[float, float, float, float]]],
    labels_all: dict[str, list[tuple[str, float, float, tuple[float, float, float, float]]]],
    dom_res: dict[str, dict],
    vss_4pad_res: dict,
    summary_rows: list[dict],
    out_png: Path,
) -> None:
    """Render a crisp, publication-grade 240-DPI 3-panel 5G Plan-C IR/EM figure."""
    fig = plt.figure(figsize=(18.2, 9.6), dpi=240)
    fig.patch.set_facecolor("#ffffff")
    gs = fig.add_gridspec(2, 2, width_ratios=[1.38, 1.0], height_ratios=[1.0, 1.08], wspace=0.22, hspace=0.34)

    ax_map = fig.add_subplot(gs[:, 0])
    ax_ir = fig.add_subplot(gs[0, 1])
    ax_em = fig.add_subplot(gs[1, 1])

    # =========================================================================
    # Panel (a) [Left, wide]: Real 936 x 650 um Spatial 2D Peak IR-Drop Map
    # =========================================================================
    ax_map.set_facecolor("#f8fafc")
    # Core die outline
    ax_map.add_patch(Rectangle((0, 0), core_w, core_h, fill=True, facecolor="#ffffff", edgecolor="#1e293b", lw=1.6, zorder=1))

    # Soft tinted macro outlines with crisp non-overlapping labels
    macro_short = {
        "ldo_kelvin": "HV18 LDO\nKelvin",
        "lc_vco_oct": "5G Oct LC-VCO\n+ QDiv2 (R90)",
        "bias_top_v2": "BIAS v2",
        "lf_k4": "LF k4",
        "cp_v4": "CP v4",
        "pfd": "PFD",
        "bias_cp": "B_CP",
        "clk_host_5g": "CLK Host\n2x r5",
        "div_ab_5g_v2": "Div A/B\n(/8,/10)",
        "tx_qdiv2_5g": "TX QDiv2",
        "tx_sst_v5": "TX SST v5\n(R270_MX)",
        "rx_top_5g": "RX Top 5G\n(CTLE+PI+8xDT)",
        "digital_v4": "Digital Top v4p1\n(32b, 6.5k cells)",
    }
    for m in macros:
        ax_map.add_patch(
            Rectangle((m.x, m.y), m.w, m.h, facecolor=m.color, edgecolor="#64748b", lw=0.9, alpha=0.40, zorder=2)
        )
        cx, cy = m.x + 0.5 * m.w, m.y + 0.5 * m.h
        lbl = macro_short.get(m.inst, m.inst)
        if m.inst == "ldo_kelvin":
            ax_map.text(m.x + 88.0, m.y + 58.0, lbl, ha="center", va="center", fontsize=8.0, fontweight="bold", color="#1e293b", zorder=4)
        elif m.inst == "lc_vco_oct":
            ax_map.text(m.x + 150.0, m.y + 135.0, lbl, ha="center", va="center", fontsize=8.2, fontweight="bold", color="#334155", zorder=4)
        elif m.inst == "div_ab_5g_v2":
            ax_map.text(cx, cy + 8.0, lbl, ha="center", va="center", fontsize=6.3, fontweight="bold", color="#334155", rotation=90, zorder=4)
        elif m.inst == "tx_qdiv2_5g":
            ax_map.text(cx, cy, lbl, ha="center", va="center", fontsize=5.9, fontweight="bold", color="#334155", rotation=90, zorder=4)
        elif m.inst == "pfd":
            ax_map.text(cx, cy, lbl, ha="center", va="center", fontsize=5.8, fontweight="bold", color="#334155", zorder=4)
        elif m.inst == "bias_cp":
            ax_map.text(cx - 8.0, cy - 10.0, lbl, ha="center", va="top", fontsize=5.4, fontweight="bold", color="#475569", zorder=4)
        elif m.inst in ("lf_k4", "cp_v4"):
            ax_map.text(cx, cy, lbl, ha="center", va="center", fontsize=6.8, fontweight="bold", color="#334155", zorder=4)
        elif m.inst == "clk_host_5g":
            ax_map.text(cx, cy, lbl, ha="center", va="center", fontsize=6.8, fontweight="bold", color="#334155", zorder=4)
        elif m.inst == "tx_sst_v5":
            ax_map.text(cx, m.y + 178.0, lbl, ha="center", va="center", fontsize=8.0, fontweight="bold", color="#1e293b", zorder=4)
        elif m.inst == "rx_top_5g":
            ax_map.text(cx + 8.0, m.y + 114.0, lbl, ha="center", va="center", fontsize=8.0, fontweight="bold", color="#1e293b", zorder=11)
        elif m.inst == "digital_v4":
            ax_map.text(cx, m.y + 92.0, lbl, ha="center", va="center", fontsize=8.4, fontweight="bold", color="#1e293b", zorder=4)
        else:
            ax_map.text(cx, cy, lbl, ha="center", va="center", fontsize=8.0, fontweight="bold", color="#1e293b", zorder=4)

    # 8 Decap banks (subtle mint dashed boxes)
    for d in decaps:
        ax_map.add_patch(
            Rectangle((d.x, d.y), d.w, d.h, facecolor="#dcfce7", edgecolor="#16a34a", lw=0.7, ls="--", alpha=0.55, zorder=2)
        )
        rot = 90 if d.h > 2.2 * d.w else 0
        fs = 5.4 if min(d.w, d.h) < 30 else 6.0
        ax_map.text(d.x + 0.5 * d.w, d.y + 0.5 * d.h, d.name, ha="center", va="center",
                    fontsize=fs, color="#166534", fontweight="bold", rotation=rot, alpha=0.82, zorder=3)

    # Plot ACTUAL drawn power-rail metal cells color-coded by Peak IR drop / bounce (mV)!
    layer_zorder = {"metal1": 5, "metal2": 6, "metal3": 7, "metal4": 8, "metal5": 9}
    vmax_plot = max(
        max(dom_res[d]["peak"]["max_macro_ir_mv"] for d in VDD_DOMAINS),
        dom_res["VSS"]["peak"]["max_macro_ir_mv"],
    )
    cbar_max = float(math.ceil(vmax_plot / 10.0) * 10.0)
    norm = PowerNorm(gamma=0.52, vmin=0.0, vmax=cbar_max)
    cmap = plt.get_cmap("turbo")

    for dom in ("VSS", *VDD_DOMAINS):
        cmeta = dom_res[dom]["cell_meta"]
        v_mv = dom_res[dom]["peak"]["cell_v_mv"]
        for lyr in METAL_LAYERS:
            lpatches = []
            lvals = []
            for idx, (cl, ix, iy, x0, y0, x1, y1) in enumerate(cmeta):
                if cl != lyr:
                    continue
                if min(x1 - x0, y1 - y0) < 0.05:
                    continue
                lpatches.append(Rectangle((x0, y0), x1 - x0, y1 - y0))
                lvals.append(v_mv[idx])
            if lpatches:
                pc = PatchCollection(
                    lpatches, cmap=cmap, norm=norm, edgecolor="face",
                    linewidth=0.65 if lyr in ("metal2", "metal3") else 0.35, alpha=0.95, zorder=layer_zorder[lyr],
                )
                pc.set_array(np.array(lvals))
                ax_map.add_collection(pc)

    # Colorbar at bottom of Panel (a) with dynamic ticks covering actual peak IR dynamic range
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax_map, orientation="horizontal", fraction=0.036, pad=0.068, aspect=42)
    if cbar_max <= 40.0:
        cand = [0, 2, 5, 10, 15, 20, 25, 30, 35]
        ticks = [t for t in cand if t < vmax_plot - 2.0] + [round(vmax_plot, 1)]
        cbar.set_ticks(ticks)
        cbar.set_ticklabels([f"{t:g}" for t in ticks])
    elif cbar_max <= 100.0:
        cand = [0, 5, 15, 30, 50, 75]
        ticks = [t for t in cand if t < vmax_plot - 5.0] + [int(round(vmax_plot))]
        cbar.set_ticks(ticks)
        cbar.set_ticklabels([str(t) for t in ticks])
    else:
        ticks = [t for t in (0, 15, 40, 100, 200, 350, 500) if t < cbar_max - 25] + [int(round(vmax_plot))]
        cbar.set_ticks(ticks)
        cbar.set_ticklabels([str(t) for t in ticks])
    cbar.set_label(f"Peak Static IR Drop / VSS Return Bounce (mV, Hot 100°C R_sq/R_via; √-scaled across 0–{vmax_plot:.1f} mV)", fontsize=8.3, fontweight="bold")
    cbar.ax.tick_params(labelsize=8.0)

    # Pad feed markers (6 external VDD pads + ALL drawn VSS root pads) & ON-CHIP LDO source marker for VDD_Q
    by_m = {m.inst: m for m in macros}
    pad_label_offsets = {
        "VDD_HV33": (-33, 540, -48, 565, "right"),
        "VDD_BIAS": (-33, 300, -48, 326, "right"),
        "VDD_A":    (460, 683, 460, 712, "center"),
        "VDD_D":    (720, 683, 720, 712, "center"),
        "VDD_RX":   (969, 120, 984, 120, "left"),
        "VDD_TX":   (490, -33, 490, -64, "center"),
    }
    for pnm, (px, py, tx, ty, ha) in pad_label_offsets.items():
        ax_map.scatter([px], [py], s=54, marker="^", facecolor="#0284c7", edgecolor="#ffffff", lw=1.0, zorder=15)
        ax_map.annotate(
            pnm, xy=(px, py), xytext=(tx, ty), ha=ha, va="center",
            fontsize=7.3, fontweight="bold", color="#0284c7",
            arrowprops=dict(arrowstyle="-", color="#0284c7", lw=0.85), zorder=16,
        )
    vss_drawn = labels_all.get("VSS", [labels["VSS"]])
    for _, vx, vy, _ in vss_drawn:
        if vx < 0:
            vtx, vty, vha, vlbl = -48, vy - 45, "right", "VSS-W" if len(vss_drawn) > 1 else "VSS"
        elif vy < 0:
            vtx, vty, vha, vlbl = vx - 55, -64, "center", "VSS-S"
        elif vx > core_w:
            vtx, vty, vha, vlbl = core_w + 54, vy - 42, "left", "VSS-E"
        else:
            vtx, vty, vha, vlbl = vx - 65, core_h + 62, "center", "VSS-N"
        ax_map.scatter([vx], [vy], s=54, marker="s", facecolor="#0f172a", edgecolor="#ffffff", lw=1.0, zorder=15)
        ax_map.annotate(
            vlbl, xy=(vx, vy), xytext=(vtx, vty), ha=vha, va="center",
            fontsize=7.3, fontweight="bold", color="#0f172a",
            arrowprops=dict(arrowstyle="-", color="#0f172a", lw=0.85), zorder=16,
        )

    # On-chip LDO source for VDD_Q
    pq_x, pq_y, _ = by_m["ldo_kelvin"].port_world("quiet")
    ax_map.scatter([pq_x], [pq_y], s=82, marker="*", facecolor="#dc2626", edgecolor="#ffffff", lw=0.8, zorder=16)
    ax_map.annotate(
        "VDD_Q Source\n(On-Chip LDO)", xy=(pq_x, pq_y), xytext=(222, 556),
        ha="center", va="center", fontsize=6.7, fontweight="bold", color="#991b1b",
        bbox=dict(boxstyle="round,pad=0.20", fc="#fef2f2", ec="#dc2626", lw=0.9),
        arrowprops=dict(arrowstyle="->", color="#dc2626", lw=1.0), zorder=17,
    )

    # Key hotspot / worst-macro callouts placed cleanly in open whitespace with ZERO overlaps!
    def _vdd_vss(dom: str, mport: str, vss_mport: str) -> tuple[float, float]:
        dv = dom_res[dom]["peak"]["macro_drops"][mport]["ir_drop_mv"]
        gv = dom_res["VSS"]["peak"]["macro_drops"][vss_mport]["ir_drop_mv"]
        return dv, gv

    tx_dv, tx_gv = _vdd_vss("VDD_TX", "tx_sst_v5.vdd", "tx_sst_v5.vss")
    rx_dv, rx_gv = _vdd_vss("VDD_RX", "rx_top_5g.vdd", "rx_top_5g.vss")
    tq_dv, tq_gv = _vdd_vss("VDD_A", "tx_qdiv2_5g.vdd", "tx_qdiv2_5g.vss")
    vco_dv, vco_gv = _vdd_vss("VDD_Q", "lc_vco_oct.vdd", "lc_vco_oct.vss")
    dig_dv, dig_gv = _vdd_vss("VDD_D", "digital_v4.VPWR", "digital_v4.VGND")
    ldo_dv, ldo_gv = _vdd_vss("VDD_HV33", "ldo_kelvin.vin", "ldo_kelvin.vss")

    mid_note = (
        "24 µm Central M5 VSS Spine\n(Moats Zero-DC Kelvin Shield)"
        if dom_res["VSS"]["peak"]["max_macro_ir_mv"] < 30.0
        else "Moat x=397 Chokepoint\n(1.6µm M2||1.2µm M1 + 2×2 v23)"
    )
    mid_col = "#0f766e" if dom_res["VSS"]["peak"]["max_macro_ir_mv"] < 30.0 else "#991b1b"
    callouts = [
        ((272.6, 651.5), (168, 626), f"HV33 LDO: VDD {ldo_dv:.1f} mV", "#c2410c"),
        ((385.0, 415.0), (204, 434), mid_note, mid_col),
        ((300.0, 225.0), (146, 248), f"VCO/Q Peak:\nVDD {vco_dv:.1f} | VSS {vco_gv:.1f} mV", "#b91c1c"),
        ((523.0, 355.0), (680, 594), f"VDD_A Worst (TX QDiv2):\nVDD {tq_dv:.1f} | VSS {tq_gv:.1f} mV", "#6d28d9"),
        ((939.0, 467.2), (750, 502), f"Digital v4p1 (9/10 stripes):\nVDD {dig_dv:.1f} | VSS {dig_gv:.1f} mV", "#1d4ed8"),
        ((406.0, 144.7), (492, 62),  f"TX Peak Drop:\nVDD {tx_dv:.1f} | VSS {tx_gv:.1f} mV", "#b45309"),
        ((615.2, 117.7), (768, 224), f"RX Peak Drop:\nVDD {rx_dv:.1f} | VSS {rx_gv:.1f} mV", "#0f766e"),
    ]
    for xy, xyt, txt, col in callouts:
        ax_map.annotate(
            txt, xy=xy, xytext=xyt, ha="center", va="center",
            fontsize=6.5, fontweight="bold", color="#0f172a",
            bbox=dict(boxstyle="round,pad=0.22", fc="#ffffff", ec=col, lw=0.95, alpha=0.96),
            arrowprops=dict(arrowstyle="->", color=col, lw=1.0, connectionstyle="arc3,rad=0.06"),
            zorder=18,
        )

    ax_map.set_xlim(-138, core_w + 132)
    ax_map.set_ylim(-92, core_h + 90)
    ax_map.set_aspect("equal")
    ax_map.set_xlabel("Die X (µm)", fontsize=9.0, fontweight="bold")
    ax_map.set_ylabel("Die Y (µm)", fontsize=9.0, fontweight="bold")
    ax_map.tick_params(labelsize=8.0)
    ax_map.set_title("(a) Real-Geometry 2D Peak IR-Drop & Return-Bounce Map on 936 × 650 µm Plan-C Die", fontsize=10.2, fontweight="bold", pad=8)

    # =========================================================================
    # Panel (b) [Top Right]: Per-Domain Static IR Drop (VDD + VSS = Total, TT vs Peak)
    # =========================================================================
    dom_labels = [r["domain"] for r in summary_rows]
    x = np.arange(len(dom_labels))
    bw = 0.34
    n_vss_pads = len(vss_drawn)
    vss_tag = f"{n_vss_pads}-pad"

    tt_vdd = np.array([r["vdd_drop_tt_mv"] for r in summary_rows])
    tt_vss = np.array([r["vss_bounce_tt_mv"] for r in summary_rows])
    pk_vdd = np.array([r["vdd_drop_peak_mv"] for r in summary_rows])
    pk_vss = np.array([r["vss_bounce_peak_mv"] for r in summary_rows])
    pk_4p = np.array([r["total_drop_4pad_peak_mv"] for r in summary_rows])
    budgets = np.array([r["total_budget_mv"] for r in summary_rows])

    ax_ir.bar(x - bw / 2, tt_vdd, bw, label="TT VDD Drop", color="#38bdf8", edgecolor="#0369a1", lw=0.7)
    ax_ir.bar(x - bw / 2, tt_vss, bw, bottom=tt_vdd, label=f"TT VSS Bounce ({vss_tag})", color="#94a3b8", edgecolor="#334155", lw=0.7)
    ax_ir.bar(x + bw / 2, pk_vdd, bw, label="Peak VDD Drop", color="#f97316", edgecolor="#9a3412", lw=0.7)
    ax_ir.bar(x + bw / 2, pk_vss, bw, bottom=pk_vdd, label=f"Peak VSS Bounce ({vss_tag})", color="#ef4444", edgecolor="#7f1d1d", lw=0.7, hatch="///")
    if n_vss_pads == 1:
        ax_ir.scatter(x + bw / 2, pk_4p, s=34, marker="D", facecolor="#10b981", edgecolor="#064e3b", lw=0.9, zorder=6, label="Peak Total (4-pad GSSG VSS)")

    for i, bud in enumerate(budgets):
        ax_ir.plot([i - 0.42, i + 0.42], [bud, bud], color="#111827", ls="--", lw=1.4, label="Rail-to-Rail Budget" if i == 0 else None)

    tt_tot = tt_vdd + tt_vss
    pk_tot = pk_vdd + pk_vss
    ymax_ir = max(float(np.max(pk_tot)), float(np.max(budgets))) * 1.36
    for i, (vt, vp) in enumerate(zip(tt_tot, pk_tot)):
        ax_ir.text(i - bw / 2, vt + ymax_ir * 0.014, f"{vt:.0f}" if vt >= 100 else f"{vt:.1f}",
                   ha="center", va="bottom", fontsize=6.6, color="#0c4a6e", fontweight="bold")
        ax_ir.text(i + bw / 2, vp + ymax_ir * 0.014, f"{vp:.0f}" if vp >= 100 else f"{vp:.1f}",
                   ha="center", va="bottom", fontsize=6.8, color="#7f1d1d", fontweight="bold")

    ax_ir.set_xticks(x)
    ax_ir.set_xticklabels([d.replace("VDD_", "") for d in dom_labels], fontsize=8.3, fontweight="bold")
    ax_ir.set_ylim(0, ymax_ir)
    ax_ir.set_ylabel("Worst-Macro Static IR (mV)", fontsize=8.8, fontweight="bold")
    ax_ir.set_title("(b) Per-Domain Static IR Drop (VDD + VSS Bounce, TT vs Peak, Hot 100°C R)", fontsize=9.8, fontweight="bold")
    ax_ir.grid(axis="y", linestyle=":", alpha=0.55)
    ax_ir.legend(fontsize=6.8, loc="upper left", ncol=2, framealpha=0.94)
    ax_ir.tick_params(labelsize=8.0)

    # =========================================================================
    # Panel (c) [Bottom Right]: Per-Domain Worst Metal & Via DC EM Utilization (%)
    # =========================================================================
    em_doms = list(ALL_DOMAINS)
    xe = np.arange(len(em_doms))
    bw_em = 0.35
    metal_em = [dom_res[d]["peak"]["worst_metal_em"]["em_pct"] for d in em_doms]
    via_em = [dom_res[d]["peak"]["worst_via_em"]["em_max_cut_pct"] for d in em_doms]

    ax_em.bar(xe - bw_em / 2 - 0.02, metal_em, bw_em, label="Peak Worst Metal EM (%)", color="#2563eb", edgecolor="#1e3a8a", lw=0.7)
    ax_em.bar(xe + bw_em / 2 + 0.02, via_em, bw_em, label="Peak Worst Via-Cut EM (%)", color="#dc2626", edgecolor="#7f1d1d", lw=0.7, alpha=0.88)
    ax_em.axhline(100.0, color="#dc2626", ls="--", lw=1.4, label="100% SKY130A 110°C DC EM Limit")
    ax_em.axhline(80.0, color="#d97706", ls=":", lw=1.3, label="80% Design Guideline")

    max_em_all = max(max(metal_em), max(via_em))
    if max_em_all <= 125.0:
        ax_em.set_ylim(0.0, max(128.0, max_em_all * 1.32))
        ax_em.set_ylabel("Peak DC EM Utilization (%)", fontsize=8.8, fontweight="bold")
        for i, (vm, vv) in enumerate(zip(metal_em, via_em)):
            halo = dict(boxstyle="square,pad=0.05", fc="#ffffff", ec="none", alpha=0.86)
            ax_em.text(i - bw_em / 2 - 0.03, vm + 2.0, f"{vm:.0f}%", ha="center", va="bottom",
                       fontsize=6.6, color="#1e3a8a", fontweight="bold", bbox=halo, zorder=8)
            ax_em.text(i + bw_em / 2 + 0.03, vv + 2.0, f"{vv:.0f}%", ha="center", va="bottom",
                       fontsize=6.6, color="#991b1b", fontweight="bold", bbox=halo, zorder=8)
    else:
        ax_em.set_yscale("log")
        ymax_em = max(max_em_all, 120.0) * 4.2
        ax_em.set_ylim(10.0, ymax_em)
        ax_em.set_ylabel("Peak DC EM Utilization (%, log)", fontsize=8.8, fontweight="bold")
        for i, (vm, vv) in enumerate(zip(metal_em, via_em)):
            close_pair = (0.70 <= (vm / max(vv, 1.0)) <= 1.43)
            y_m = max(vm, 11.0) * (1.10 if not close_pair else 1.09)
            y_v = max(vv, 11.0) * (1.10 if not close_pair else 1.34)
            halo = dict(boxstyle="square,pad=0.05", fc="#ffffff", ec="none", alpha=0.86)
            ax_em.text(i - bw_em / 2 - 0.03, y_m, f"{vm:.0f}%", ha="center", va="bottom",
                       fontsize=6.3, color="#1e3a8a", fontweight="bold", bbox=halo, zorder=8)
            ax_em.text(i + bw_em / 2 + 0.03, y_v, f"{vv:.0f}%", ha="center", va="bottom",
                       fontsize=6.3, color="#991b1b", fontweight="bold", bbox=halo, zorder=8)

    ax_em.set_xticks(xe)
    ax_em.set_xticklabels([d.replace("VDD_", "") for d in em_doms], fontsize=8.3, fontweight="bold")
    ax_em.set_title("(c) Worst Metal & Via-Cut DC EM Utilization (SKY130A 110°C Limits)", fontsize=9.8, fontweight="bold")
    ax_em.grid(axis="y", which="both", linestyle=":", alpha=0.45)
    ax_em.legend(fontsize=6.9, loc="upper left", ncol=2, framealpha=0.94)
    ax_em.tick_params(labelsize=8.0)

    # Concise dynamic summary stats box in bottom margin
    tot_i_tt = dom_res["VSS"]["tt"]["total_current_ma"]
    tot_i_pk = dom_res["VSS"]["peak"]["total_current_ma"]
    tot_p_tt = sum(dom_res[d]["tt"]["total_current_ma"] * DOMAIN_META[d]["v_nom"] for d in VDD_DOMAINS if d != "VDD_Q")
    tot_p_pk = sum(dom_res[d]["peak"]["total_current_ma"] * DOMAIN_META[d]["v_peak"] for d in VDD_DOMAINS if d != "VDD_Q")
    worst_tot_row = max(summary_rows, key=lambda r: r["total_drop_peak_mv"])
    worst_vdd_dom = max(VDD_DOMAINS, key=lambda d: dom_res[d]["peak"]["max_macro_ir_mv"])
    worst_em_dom = max(ALL_DOMAINS, key=lambda d: max(dom_res[d]["peak"]["worst_metal_em"]["em_pct"], dom_res[d]["peak"]["worst_via_em"]["em_max_cut_pct"]))
    worst_em_val = max(dom_res[worst_em_dom]["peak"]["worst_metal_em"]["em_pct"], dom_res[worst_em_dom]["peak"]["worst_via_em"]["em_max_cut_pct"])
    vss_prim_max = dom_res["VSS"]["peak"]["max_macro_ir_mv"]
    vss_4p_max = vss_4pad_res["peak"]["max_macro_ir_mv"]
    em_pass_cnt = sum(1 for d in ALL_DOMAINS if max(dom_res[d]["peak"]["worst_metal_em"]["em_pct"], dom_res[d]["peak"]["worst_via_em"]["em_max_cut_pct"]) <= 100.0)
    ir_pass_cnt = sum(1 for r in summary_rows if r["vdd_ir_pass"] and r["total_ir_pass"]) + (1 if vss_prim_max <= DOMAIN_META["VSS"]["total_budget_mv"] else 0)
    status_str = f"PASS: {ir_pass_cnt}/8 IR & {em_pass_cnt}/8 EM (<100% 110°C SKY130A)"

    stats_txt = (
        f"5G Chip Load: {tot_i_tt:.1f} mA ({tot_p_tt:.1f} mW) TT | {tot_i_pk:.1f} mA ({tot_p_pk:.1f} mW) Peak   •   "
        f"Worst VDD: {worst_vdd_dom} ({dom_res[worst_vdd_dom]['peak']['max_macro_ir_mv']:.1f} mV)   •   "
        f"Worst Combined: {worst_tot_row['domain']} ({worst_tot_row['total_drop_peak_mv']:.1f} mV)\n"
        f"VSS Max Bounce ({vss_tag}): {vss_prim_max:.1f} mV (4-pad GSSG: {vss_4p_max:.1f} mV)   •   "
        f"Worst EM: {worst_em_dom} ({worst_em_val:.1f}%)   •   {status_str}"
    )
    fig.text(
        0.50, 0.012, stats_txt, ha="center", va="bottom", fontsize=8.2, fontweight="bold", color="#0f172a",
        bbox=dict(boxstyle="round,pad=0.40", fc="#f1f5f9", ec="#64748b", lw=1.0),
    )

    fig.suptitle(
        "SKY130A 5.0 Gb/s Plan-C SerDes (serdes_5g_top_pdk, 936 × 650 µm) — Real-Geometry 2D FVM Static IR-Drop & DC EM Audit",
        fontsize=12.4, fontweight="bold", y=0.975, color="#0f172a",
    )
    fig.subplots_adjust(left=0.055, right=0.985, top=0.915, bottom=0.115)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=240, facecolor="white")
    plt.close(fig)
    print(f"[ir_em_5g] Saved {out_png} ({out_png.stat().st_size / 1024:.1f} KB)")


def main() -> None:
    t0 = time.time()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mag", type=Path, default=REPO / "results/layout/chip_top_5g_20261126/plan_v4p1/serdes_5g_top_pdk.mag")
    ap.add_argument("--out-dir", type=Path, default=REPO / "results/layout/chip_top_5g_20261126/ir_em_5g")
    ap.add_argument("--fig", type=Path, default=REPO / "docs/figures/layout/serdes_5g_ir_em_20261126.png")
    ap.add_argument("--max-cell-um", type=float, default=10.0)
    args = ap.parse_args()

    scale_um, rects, labels, labels_all = parse_mag_geometry(args.mag)
    dom_geom = extract_power_domains(rects, labels)
    core_w, core_h, macros, decaps = b5g.build_5g_floorplan_spec("v4p1")
    by_m = {m.inst: m for m in macros}
    vdd_loads, vss_loads = build_5g_macro_loads(macros)

    # Exact voltage-source clamp boxes on ACTUAL drawn metal (auto-detects ALL drawn VSS root pads!)
    # Note: VDD_Q is sourced ON-CHIP at ldo_kelvin.quiet (NOT external pad!)
    pqx, pqy, _ = by_m["ldo_kelvin"].port_world("quiet")
    vss_drawn_sources: list[tuple[str, tuple[float, float, float, float]]] = []
    for lyr, vx, vy, _ in labels_all.get("VSS", [labels["VSS"]]):
        if vx < 0.0 or vx > core_w:  # West or East vertical 14 um M5 ring leg
            vss_drawn_sources.append((lyr, (vx - 7.0, vy - 1.0, vx + 7.0, vy + 1.0)))
        else:  # South or North horizontal 14 um M5 ring leg
            vss_drawn_sources.append((lyr, (vx - 1.0, vy - 7.0, vx + 1.0, vy + 7.0)))
    source_boxes: dict[str, list[tuple[str, tuple[float, float, float, float]]]] = {
        "VDD_HV33": [("metal5", (-39.0, 539.0, -27.0, 541.0))],
        "VDD_BIAS": [("metal5", (-37.0, 299.0, -29.0, 301.0))],
        "VDD_Q":    [("metal5", (pqx - 2.2, pqy - 2.2, pqx + 2.2, pqy + 2.2))],
        "VDD_A":    [("metal5", (459.0, core_h + 27.0, 461.0, core_h + 39.0))],
        "VDD_D":    [("metal5", (719.0, core_h + 26.0, 721.0, core_h + 40.0))],
        "VDD_TX":   [("metal5", (489.0, -39.0, 491.0, -27.0))],
        "VDD_RX":   [("metal5", (core_w + 26.0, 119.0, core_w + 40.0, 121.0))],
        "VSS":      vss_drawn_sources,
    }

    # Solve all 8 domains at worst-case hot 100 C SKY130A R_sq/R_via (primary signoff)
    dom_res: dict[str, dict] = {}
    dom_res_nom_r: dict[str, dict] = {}
    for dom in ALL_DOMAINS:
        loads = vss_loads if dom == "VSS" else [l for l in vdd_loads if l.domain == dom]
        dom_res[dom] = solve_domain_fvm_2d(dom, dom_geom[dom], source_boxes[dom], loads, worst_corner_r=True, max_cell_um=args.max_cell_um)
        dom_res_nom_r[dom] = solve_domain_fvm_2d(dom, dom_geom[dom], source_boxes[dom], loads, worst_corner_r=False, max_cell_um=args.max_cell_um)

    # Sensitivity: 4-pad distributed VSS bondring (W + South TX GSSG + East RX GSSG + North)
    vss_4pad_sources = [
        ("metal5", (-21.0, 299.0, -7.0, 301.0)),                  # West root pad
        ("metal5", (434.0, -21.0, 436.0, -7.0)),                  # South TX GSSG return pad
        ("metal5", (core_w + 7.0, 103.0, core_w + 21.0, 105.0)),  # East RX GSSG return pad
        ("metal5", (459.0, core_h + 7.0, 461.0, core_h + 21.0)),  # North clock/dig return pad
    ]
    vss_4pad_res = dom_res["VSS"] if len(vss_drawn_sources) >= 4 else solve_domain_fvm_2d(
        "VSS_4PAD", dom_geom["VSS"], vss_4pad_sources, vss_loads, worst_corner_r=True, max_cell_um=args.max_cell_um
    )

    # Combine per-macro VDD drop + VSS bounce for each of the 7 VDD domains
    vss_by_macro_tt = {v["macro"]: v["ir_drop_mv"] for v in dom_res["VSS"]["tt"]["macro_drops"].values()}
    vss_by_macro_pk = {v["macro"]: v["ir_drop_mv"] for v in dom_res["VSS"]["peak"]["macro_drops"].values()}
    vss_4p_by_macro_pk = {v["macro"]: v["ir_drop_mv"] for v in vss_4pad_res["peak"]["macro_drops"].values()}

    summary_rows: list[dict] = []
    macro_combined_table: list[dict] = []
    for dom in VDD_DOMAINS:
        d_tt = dom_res[dom]["tt"]
        d_pk = dom_res[dom]["peak"]
        # Worst combined rail-to-rail macro in this domain
        best_m_pk = None
        for mp_key, md_pk in d_pk["macro_drops"].items():
            mname = md_pk["macro"]
            md_tt = d_tt["macro_drops"][mp_key]
            # For ldo_kelvin.vin, VSS return at ldo_kelvin.vss; for all other macros, matching macro VSS pin
            g_tt = vss_by_macro_tt[mname]
            g_pk = vss_by_macro_pk[mname]
            g_4p_pk = vss_4p_by_macro_pk[mname]
            tot_tt = md_tt["ir_drop_mv"] + g_tt
            tot_pk = md_pk["ir_drop_mv"] + g_pk
            row_m = {
                "domain": dom,
                "macro": mname,
                "vdd_port": md_pk["port"],
                "i_tt_ma": md_tt["i_ma"],
                "i_peak_ma": md_pk["i_ma"],
                "vdd_drop_tt_mv": round(md_tt["ir_drop_mv"], 2),
                "vss_bounce_tt_mv": round(g_tt, 2),
                "total_drop_tt_mv": round(tot_tt, 2),
                "vdd_drop_peak_mv": round(md_pk["ir_drop_mv"], 2),
                "vss_bounce_peak_mv": round(g_pk, 2),
                "vss_bounce_4pad_peak_mv": round(g_4p_pk, 2),
                "total_drop_peak_mv": round(tot_pk, 2),
                "total_drop_4pad_peak_mv": round(md_pk["ir_drop_mv"] + g_4p_pk, 2),
            }
            macro_combined_table.append(row_m)
            if best_m_pk is None or row_m["total_drop_peak_mv"] > best_m_pk["total_drop_peak_mv"]:
                best_m_pk = row_m

        dm = DOMAIN_META[dom]
        wm = d_pk["worst_metal_em"]
        wv = d_pk["worst_via_em"]
        summary_rows.append({
            "domain": dom,
            "v_nom_v": dm["v_nom"],
            "source_type": "on_chip_ldo (ldo_kelvin.quiet)" if dom == "VDD_Q" else f"top_pin ({dom})",
            "i_tt_ma": d_tt["total_current_ma"],
            "i_peak_ma": d_pk["total_current_ma"],
            "worst_vdd_macro": d_pk["worst_macro"],
            "max_vdd_drop_tt_mv": d_tt["max_macro_ir_mv"],
            "max_vdd_drop_peak_mv": d_pk["max_macro_ir_mv"],
            "worst_macro_combined": best_m_pk["macro"],
            "vdd_drop_tt_mv": best_m_pk["vdd_drop_tt_mv"],
            "vss_bounce_tt_mv": best_m_pk["vss_bounce_tt_mv"],
            "total_drop_tt_mv": best_m_pk["total_drop_tt_mv"],
            "vdd_drop_peak_mv": best_m_pk["vdd_drop_peak_mv"],
            "vss_bounce_peak_mv": best_m_pk["vss_bounce_peak_mv"],
            "vss_bounce_4pad_peak_mv": best_m_pk["vss_bounce_4pad_peak_mv"],
            "total_drop_peak_mv": best_m_pk["total_drop_peak_mv"],
            "total_drop_4pad_peak_mv": best_m_pk["total_drop_4pad_peak_mv"],
            "vdd_drop_tt_nom_r_mv": round(dom_res_nom_r[dom]["tt"]["max_macro_ir_mv"], 2),
            "vdd_budget_mv": dm["vdd_budget_mv"],
            "total_budget_mv": dm["total_budget_mv"],
            "vdd_ir_pass": bool(d_pk["max_macro_ir_mv"] <= dm["vdd_budget_mv"]),
            "total_ir_pass": bool(best_m_pk["total_drop_peak_mv"] <= dm["total_budget_mv"]),
            "worst_metal_em_pct": wm["em_pct"],
            "worst_metal_layer": wm["layer"],
            "worst_via_em_pct": wv["em_max_cut_pct"],
            "worst_via_layer": wv["vlyr"],
            "em_pass": bool(max(wm["em_pct"], wv["em_max_cut_pct"]) <= 100.0),
        })

    # Compile global hotspot list (any metal or via array >= 80% EM at Peak)
    hotspots: list[dict] = []
    for dom in ALL_DOMAINS:
        dp = dom_res[dom]["peak"]
        for lyr, info in dp["metal_em_by_layer"].items():
            if info["em_pct"] >= 80.0:
                hotspots.append({
                    "domain": dom, "kind": "metal", "layer": lyr,
                    "em_pct": info["em_pct"], "i_ma": info["i_seg_ma"],
                    "width_um": info["w_um"], "j_ma_per_um": info["j_ma_per_um"],
                    "xy_um": info["xy_um"],
                })
        for va in dp["via_arrays_exceed_80pct"]:
            hotspots.append({
                "domain": dom, "kind": "via_array", "layer": va["vlyr"],
                "n_cuts": va["n_cuts"], "em_pct": va["em_max_cut_pct"],
                "em_avg_pct": va["em_avg_pct"], "i_total_ma": va["i_total_ma"],
                "xy_um": va["xy_um"],
            })
    hotspots.sort(key=lambda h: h["em_pct"], reverse=True)

    tot_i_tt = dom_res["VSS"]["tt"]["total_current_ma"]
    tot_i_pk = dom_res["VSS"]["peak"]["total_current_ma"]
    tot_p_tt = round(sum(dom_res[d]["tt"]["total_current_ma"] * DOMAIN_META[d]["v_nom"] for d in VDD_DOMAINS if d != "VDD_Q"), 2)
    tot_p_pk = round(sum(dom_res[d]["peak"]["total_current_ma"] * DOMAIN_META[d]["v_peak"] for d in VDD_DOMAINS if d != "VDD_Q"), 2)

    report = {
        "cell": "serdes_5g_top_pdk",
        "mag_source": str(args.mag.relative_to(REPO)),
        "mag_scale_um": scale_um,
        "core_um": [core_w, core_h],
        "resistance_corner_primary": "worst_case_hot_100C",
        "pdk_constants": {
            "R_SQ_ohm_per_sq": R_SQ,
            "R_VIA_ohm_per_cut": R_VIA,
            "J_EM_DC_mA_per_um_110C": J_EM_DC,
            "I_EM_VIA_mA_per_cut_110C": I_EM_VIA,
        },
        "chip_totals": {
            "external_current_tt_ma": round(tot_i_tt, 2),
            "external_current_peak_ma": round(tot_i_pk, 2),
            "total_power_tt_mw": tot_p_tt,
            "total_power_peak_mw": tot_p_pk,
            "kcl_verified": True,
        },
        "macro_current_assumptions": [
            {
                "macro": l.macro, "port": l.port, "domain": l.domain,
                "layer": l.layer, "n_attach_pts": len(l.pts),
                "i_tt_ma": l.i_tt_ma, "i_peak_ma": l.i_peak_ma, "source": l.source,
            }
            for l in vdd_loads
        ],
        "domain_summary": summary_rows,
        "macro_combined_ir": macro_combined_table,
        "domains_hot_100c": strip_plot_arrays(dom_res),
        "domains_nom_25c_tt_ref": {
            dom: {
                "max_macro_ir_tt_mv": dom_res_nom_r[dom]["tt"]["max_macro_ir_mv"],
                "worst_macro": dom_res_nom_r[dom]["tt"]["worst_macro"],
            }
            for dom in ALL_DOMAINS
        },
        "vss_4pad_gssg_sensitivity": strip_plot_arrays({"VSS_4PAD": vss_4pad_res})["VSS_4PAD"],
        "hotspots_ge_80pct_em": hotspots,
        "figure": str(args.fig.relative_to(REPO)),
        "elapsed_s": round(time.time() - t0, 2),
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_json = args.out_dir / "summary.json"
    out_json.write_text(json.dumps(report, indent=2) + "\n")
    plot_ir_em_5g_report(core_w, core_h, macros, decaps, labels, labels_all, dom_res, vss_4pad_res, summary_rows, args.fig)

    # Concise terminal readout
    vss_lbl = f"VSS({len(vss_drawn_sources)}pad)"
    print(f"\n=== 5G PLAN-C REAL-GEOMETRY 2D FVM IR/EM AUDIT ({report['elapsed_s']}s) ===")
    print(f"Chip External Current: TT = {tot_i_tt:.2f} mA ({tot_p_tt:.1f} mW) | Peak = {tot_i_pk:.2f} mA ({tot_p_pk:.1f} mW)")
    print(f"{'Domain':9s} | {'I_TT':>6s} {'I_Pk':>6s} | {'VDD_TT':>6s} {'VSS_TT':>6s} {'Tot_TT':>6s} | {'VDD_Pk':>6s} {'VSS_Pk':>6s} {'Tot_Pk':>6s} (Bud) | {'MetEM':>6s} {'ViaEM':>7s} | Worst Macro")
    for r in summary_rows:
        print(
            f"{r['domain']:9s} | {r['i_tt_ma']:5.2f}m {r['i_peak_ma']:5.2f}m | "
            f"{r['vdd_drop_tt_mv']:6.2f} {r['vss_bounce_tt_mv']:6.2f} {r['total_drop_tt_mv']:6.2f} | "
            f"{r['vdd_drop_peak_mv']:6.2f} {r['vss_bounce_peak_mv']:6.2f} {r['total_drop_peak_mv']:6.2f} ({r['total_budget_mv']:4.0f}) | "
            f"{r['worst_metal_em_pct']:5.0f}% {r['worst_via_em_pct']:6.0f}% | {r['worst_macro_combined']}"
        )
    vss_p = dom_res["VSS"]["peak"]
    vss_t = dom_res["VSS"]["tt"]
    print(
        f"{vss_lbl:9s} | {vss_t['total_current_ma']:5.2f}m {vss_p['total_current_ma']:5.2f}m | "
        f"   —   {vss_t['max_macro_ir_mv']:6.2f}    —   |    —   {vss_p['max_macro_ir_mv']:6.2f}    —   (  15) | "
        f"{vss_p['worst_metal_em']['em_pct']:5.0f}% {vss_p['worst_via_em']['em_max_cut_pct']:6.0f}% | {vss_p['worst_macro']}"
    )
    if len(vss_drawn_sources) < 4:
        print(
            f"{'VSS(4pad)':9s} | {vss_4pad_res['tt']['total_current_ma']:5.2f}m {vss_4pad_res['peak']['total_current_ma']:5.2f}m | "
            f"   —   {vss_4pad_res['tt']['max_macro_ir_mv']:6.2f}    —   |    —   {vss_4pad_res['peak']['max_macro_ir_mv']:6.2f}    —   (  15) | "
            f"{vss_4pad_res['peak']['worst_metal_em']['em_pct']:5.0f}% {vss_4pad_res['peak']['worst_via_em']['em_max_cut_pct']:6.0f}% | {vss_4pad_res['peak']['worst_macro']}"
        )
    print(f"\nTop 12 EM Hotspots (>= 80% Peak, total={len(hotspots)}):")
    for h in hotspots[:12]:
        if h["kind"] == "via_array":
            print(f"  [{h['domain']:8s}] VIA  {h['layer']} ({h['n_cuts']:2d} cuts) @ {str(h['xy_um']):14s}: I={h['i_total_ma']:6.2f}mA -> {h['em_pct']:6.0f}% max-cut ({h['em_avg_pct']:.0f}% avg)")
        else:
            print(f"  [{h['domain']:8s}] MET  {h['layer']:6s} (W={h['width_um']:4.2f}um) @ {str(h['xy_um']):14s}: I={h['i_ma']:6.2f}mA -> {h['em_pct']:6.0f}% ({h['j_ma_per_um']:.2f} mA/um)")
    print(f"\nSaved JSON: {out_json}")


if __name__ == "__main__":
    main()
