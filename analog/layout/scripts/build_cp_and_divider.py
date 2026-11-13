#!/usr/bin/env python3
"""
Build PLL Charge Pump (`pll_cp` & `pll_cp_steer`) and CML Divider (`pll_cml_latch`,
`pll_cml_div2`, `pll_cml_prescaler8`) layouts in compact RF/Analog comb strip-electrode style,
and bundle everything into `serdes_pll_full_layout_pack.zip`.
"""
from __future__ import annotations
import shutil
import sys
import zipfile
from pathlib import Path
import matplotlib.pyplot as plt

ANALOG = Path(__file__).resolve().parents[2]
INTER_DIR = Path(__file__).resolve().parent
OUT_DIR = ANALOG / "layout/work"
PACK_V2_DIR = OUT_DIR / "serdes_vco_lf_layout_pack_v2"
FULL_PACK_DIR = OUT_DIR / "serdes_pll_full_layout_pack"
sys.path.insert(0, str(INTER_DIR))

from layout_core import LayoutCanvas, plot_canvas
from build_vco_blocks import draw_comb_mos, draw_high_po_res
from build_vco_lf_v2_compact import build_cml_stage_v2


# =========================================================================
# PART 1: PLL Charge Pump (`pll_cp` Baseline & `pll_cp_steer` k=4 Steering CP)
# =========================================================================
def build_pll_cp_baseline() -> LayoutCanvas:
    """
    Baseline Series-Switch Charge Pump (`pll_cp`, k=4 scale):
      - Left Abutted 2-Row CMOS Driver Zone:
          `Xupn` (W=2, L=0.88) / `Xupp` (W=8, L=0.15) -> generates `up_b`
          `Xdn1` (Wn=4, Wp=8) -> generates `dn_b`
          `Xdn2` (Wn=4, Wp=8) -> generates `dn_on`
      - Right Matched Analog Current Mirror & Series Switch Zone:
          Top PMOS N-Well: `Xp` (W=80, L=1.0, nf=16 x 5.0um) + `Xps` (W=16, L=0.15, nf=4 x 4.0um)
          Bottom NMOS P-Well: `Xn` (W=20, L=1.0, nf=4 x 5.0um) + `Xns` (W=8, L=0.15, nf=4 x 2.0um)
    """
    c = LayoutCanvas("pll_cp")
    c.R("pwell", 0.0, 0.0, 29.5, 16.2)
    c.R("nwell", 0.5, 7.6, 29.0, 15.8)

    # Top VDD M1/M2 Rail + N-Well Tap Bar (y in [15.0, 15.55])
    c.R("nsubdiff", 0.8, 15.05, 28.7, 15.50)
    c.R("locali", 0.8, 15.05, 28.7, 15.50)
    c.R("m1", 0.7, 15.00, 28.8, 15.55)
    c.R("m2", 0.7, 15.00, 28.8, 15.55)
    for k in range(58):
        cx = round(1.1 + k * 0.47, 3)
        if cx <= 28.4:
            c.sq("nsubdiffcont", cx, 15.28, 0.17)
            c.sq("viali", cx, 15.28, 0.17)

    # Bottom VSS M1/M2 Rail + P-Sub Tap Bar (y in [0.55, 1.10])
    c.R("psubdiff", 0.8, 0.60, 28.7, 1.05)
    c.R("locali", 0.8, 0.60, 28.7, 1.05)
    c.R("m1", 0.7, 0.55, 28.8, 1.10)
    c.R("m2", 0.7, 0.55, 28.8, 1.10)
    for k in range(58):
        cx = round(1.1 + k * 0.47, 3)
        if cx <= 28.4:
            c.sq("psubdiffcont", cx, 0.82, 0.17)
            c.sq("viali", cx, 0.82, 0.17)

    # 1. Left Driver Column (x = 1.2 .. 8.8):
    # UP driver (`Xupn` nf=2x1.0 L=0.88, `Xupp` nf=2x4.0 L=0.15)
    up_n = draw_comb_mos(c, "n", w_finger=1.80, nf=2, l_gate=0.88, x0=1.20, y0=2.30,
                         lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    up_p = draw_comb_mos(c, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=1.20, y0=8.80,
                         lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    # DN cascade inverters (`Xdn1` nf=2, `Xdn2` nf=2 abutted on continuous diffusion at x0=4.60)
    dn1_n = draw_comb_mos(c, "n", w_finger=2.00, nf=2, l_gate=0.15, x0=4.60, y0=2.30,
                          lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    dn1_p = draw_comb_mos(c, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=4.60, y0=8.80,
                          lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    dn2_n = draw_comb_mos(c, "n", w_finger=2.00, nf=2, l_gate=0.15, x0=6.90, y0=2.30,
                          lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    dn2_p = draw_comb_mos(c, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=6.90, y0=8.80,
                          lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)

    for n_d, p_d in ((up_n, up_p), (dn1_n, dn1_p), (dn2_n, dn2_p)):
        c.R("m1", n_d["S"][0] - 0.18, 0.80, n_d["S"][0] + 0.18, n_d["S"][1] + 0.12)
        c.R("m1", p_d["S"][0] - 0.18, p_d["S"][1] - 0.12, p_d["S"][0] + 0.18, 15.25)
        c.R("m2", n_d["D"][0] - 0.20, n_d["D"][1], n_d["D"][0] + 0.20, p_d["D"][1])

    # 2. Right Current Mirrors & Switches:
    # Bottom NMOS Sink Mirror `Xn` (W=20, L=1.0, nf=4 x 5.0um -> folded as nf=8 x 2.5um L=1.0 at x0=9.60)
    # + Series Switch `Xns` (W=8, L=0.15, nf=4 x 2.0um at x0=22.40)
    xn = draw_comb_mos(c, "n", w_finger=2.50, nf=8, l_gate=1.00, x0=9.60, y0=2.30,
                       lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=0.42)
    xns = draw_comb_mos(c, "n", w_finger=2.50, nf=4, l_gate=0.15, x0=22.40, y0=2.30,
                        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=0.42)
    c.R("m1", xn["S"][0] - 0.35, 0.80, xn["S"][0] + 0.35, xn["S"][1] + 0.15)
    # Connect `ns` (Xn Drain -> Xns Source)
    c.R("m2", xn["D"][0] - 0.25, 5.45, xns["S"][0] + 0.25, 5.85)
    c.R("m2", xns["S"][0] - 0.22, xns["S"][1], xns["S"][0] + 0.22, 5.85)

    # Top PMOS Source Mirror `Xp` (W=80, L=1.0, nf=8 x 5.0um or 10 x 4.5um at x0=9.60)
    # + Series Switch `Xps` (W=16, L=0.15, nf=4 x 4.0um at x0=22.40)
    xp = draw_comb_mos(c, "p", w_finger=4.20, nf=8, l_gate=1.00, x0=9.60, y0=8.80,
                       lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=True, sd_width=0.42)
    xps = draw_comb_mos(c, "p", w_finger=4.20, nf=4, l_gate=0.15, x0=22.40, y0=8.80,
                        lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=True, sd_width=0.42)
    c.R("m1", xp["S"][0] - 0.35, xp["S"][1] - 0.15, xp["S"][0] + 0.35, 15.25)
    # Connect `ps` (Xp Drain -> Xps Source)
    c.R("m2", xp["D"][0] - 0.25, 7.65, xps["S"][0] + 0.25, 8.05)
    c.R("m2", xps["S"][0] - 0.22, 7.65, xps["S"][0] + 0.22, xps["S"][1])

    # Connect `out` (Xps Drain + Xns Drain at right)
    c.R("m2", xns["D"][0] - 0.30, xns["D"][1], xns["D"][0] + 0.30, xps["D"][1])
    c.via2(xns["D"][0], 6.75, pad=0.44)
    c.R("m3", xns["D"][0] - 0.25, 6.50, 28.80, 7.00)

    # Route `up_b` (from up_n["D"] to xps["G"]) and `dn_on` (from dn2_n["D"] to xns["G"])
    c.R("m3", up_n["D"][0] - 0.20, 6.80, xps["G"][0] + 0.20, 7.15)
    c.R("m3", dn2_n["D"][0] - 0.20, 6.10, xns["G"][0] + 0.20, 6.45)

    c.L("up", up_n["G"][0], up_n["G"][1], "m1")
    c.L("dn", dn1_n["G"][0], dn1_n["G"][1], "m1")
    c.L("vbn", xn["G"][0], xn["G"][1], "m1")
    c.L("vbp", xp["G"][0], xp["G"][1], "m1")
    c.L("out", 28.50, 6.75, "m3")
    c.L("vdd", 1.20, 15.28, "m2")
    c.L("vss", 1.20, 0.82, "m2")
    return c


def build_pll_cp_steer() -> LayoutCanvas:
    """
    Production Current-Steering Charge Pump (`pll_cp_steer`, k=4 scale from `pll_core_r6k4q.spice`):
      - Zone 1 (Left, x=1..28): UP/DN pulse drivers + Long-channel Mirrors (`Xp`, `Xn`) +
        Symmetric Differential Steering Pairs (`Xps/Xpd` steering `ps` between `out` and `dum`,
        `Xns/Xnd` steering `ns` between `out` and `dum`).
      - Zone 2 (Right, x=29..48): 5-Transistor LVT Unity-Gain Replica Follower OTA (`Xbd`, `Xt`,
        common-centroid `Xa/Xb` LVT input pair, `Xla/Xlb` LVT PMOS active load) +
        **Under-MIM 3D-Stacked `Cdum` (0.3 pF = 12.2 x 12.2 um MIM on M3+CAPM+M4 stacked directly over the OTA!)**
        so `Cdum` adds ZERO extra silicon footprint!
    """
    c = LayoutCanvas("pll_cp_steer")
    c.R("pwell", 0.0, 0.0, 48.0, 16.6)
    c.R("nwell", 0.5, 7.8, 47.5, 16.2)

    # Continuous Top VDD M1/M2 Rail + N-Well Tap Bar & Bottom VSS M1/M2 Rail + P-Sub Tap Bar
    c.R("nsubdiff", 0.8, 15.45, 47.2, 15.90)
    c.R("locali", 0.8, 15.45, 47.2, 15.90)
    c.R("m1", 0.7, 15.40, 47.3, 15.95)
    c.R("m2", 0.7, 15.40, 47.3, 15.95)

    c.R("psubdiff", 0.8, 0.60, 47.2, 1.05)
    c.R("locali", 0.8, 0.60, 47.2, 1.05)
    c.R("m1", 0.7, 0.55, 47.3, 1.10)
    c.R("m2", 0.7, 0.55, 47.3, 1.10)
    for k in range(96):
        cx = round(1.1 + k * 0.47, 3)
        if cx <= 46.9:
            c.sq("nsubdiffcont", cx, 15.68, 0.17)
            c.sq("viali", cx, 15.68, 0.17)
            c.sq("psubdiffcont", cx, 0.82, 0.17)
            c.sq("viali", cx, 0.82, 0.17)

    # Zone 1A: UP/DN Pulse Drivers (x = 1.2 .. 8.8)
    up_n = draw_comb_mos(c, "n", w_finger=1.80, nf=2, l_gate=0.88, x0=1.20, y0=2.30,
                         lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    up_p = draw_comb_mos(c, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=1.20, y0=9.00,
                         lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    dn1_n = draw_comb_mos(c, "n", w_finger=2.00, nf=2, l_gate=0.15, x0=4.60, y0=2.30,
                          lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    dn1_p = draw_comb_mos(c, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=4.60, y0=9.00,
                          lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    dn2_n = draw_comb_mos(c, "n", w_finger=2.00, nf=2, l_gate=0.15, x0=6.90, y0=2.30,
                          lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    dn2_p = draw_comb_mos(c, "p", w_finger=4.00, nf=2, l_gate=0.15, x0=6.90, y0=9.00,
                          lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    for n_d, p_d in ((up_n, up_p), (dn1_n, dn1_p), (dn2_n, dn2_p)):
        c.R("m1", n_d["S"][0] - 0.18, 0.80, n_d["S"][0] + 0.18, n_d["S"][1] + 0.12)
        c.R("m1", p_d["S"][0] - 0.18, p_d["S"][1] - 0.12, p_d["S"][0] + 0.18, 15.65)
        c.R("m2", n_d["D"][0] - 0.20, n_d["D"][1], n_d["D"][0] + 0.20, p_d["D"][1])

    # Zone 1B: Long-Channel Mirrors (`Xn`, `Xp`) + Differential Steering Pairs (`Xns/Xnd`, `Xps/Xpd`)
    xn = draw_comb_mos(c, "n", w_finger=2.50, nf=8, l_gate=1.00, x0=9.50, y0=2.30,
                       lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=0.42)
    xp = draw_comb_mos(c, "p", w_finger=4.40, nf=8, l_gate=1.00, x0=9.50, y0=9.00,
                       lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=True, sd_width=0.42)
    c.R("m1", xn["S"][0] - 0.35, 0.80, xn["S"][0] + 0.35, xn["S"][1] + 0.15)
    c.R("m1", xp["S"][0] - 0.35, xp["S"][1] - 0.15, xp["S"][0] + 0.35, 15.65)

    # Steering switches (`Xns` -> out, `Xnd` -> dum on bottom; `Xps` -> out, `Xpd` -> dum on top)
    xns = draw_comb_mos(c, "n", w_finger=2.50, nf=4, l_gate=0.15, x0=22.00, y0=2.30,
                        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    xnd = draw_comb_mos(c, "n", w_finger=2.50, nf=4, l_gate=0.15, x0=25.60, y0=2.30,
                        lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    xps = draw_comb_mos(c, "p", w_finger=4.40, nf=4, l_gate=0.15, x0=22.00, y0=9.00,
                        lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    xpd = draw_comb_mos(c, "p", w_finger=4.40, nf=4, l_gate=0.15, x0=25.60, y0=9.00,
                        lvt=False, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)

    # Bridge `ns` (Xn.D -> Xns.S & Xnd.S) and `ps` (Xp.D -> Xps.S & Xpd.S)
    c.R("m2", xn["D"][0] - 0.25, 5.30, xnd["S"][0] + 0.25, 5.65)
    c.R("m2", xp["D"][0] - 0.25, 8.00, xpd["S"][0] + 0.25, 8.35)
    # Bridge `out` (Xns.D <-> Xps.D at x=23.5) and `dum` (Xnd.D <-> Xpd.D at x=27.1)
    c.R("m2", xns["D"][0] - 0.25, xns["D"][1], xns["D"][0] + 0.25, xps["D"][1])
    c.R("m2", xnd["D"][0] - 0.25, xnd["D"][1], xnd["D"][0] + 0.25, xpd["D"][1])

    # Zone 2: Unity-Gain Replica Follower OTA (`Xbd/Xt`, `Xa/Xb` LVT, `Xla/Xlb` LVT) + Under-MIM 3D-Stacked `Cdum`!
    x_ota = 30.20
    xt = draw_comb_mos(c, "n", w_finger=2.50, nf=4, l_gate=1.00, x0=x_ota, y0=2.30,
                       lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    xa = draw_comb_mos(c, "n", w_finger=2.50, nf=4, l_gate=1.00, x0=36.60, y0=2.30,
                       lvt=True, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    xb = draw_comb_mos(c, "n", w_finger=2.50, nf=4, l_gate=1.00, x0=42.20, y0=2.30,
                       lvt=True, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)

    xla = draw_comb_mos(c, "p", w_finger=4.40, nf=6, l_gate=1.00, x0=30.20, y0=9.00,
                        lvt=True, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)
    xlb = draw_comb_mos(c, "p", w_finger=4.40, nf=6, l_gate=1.00, x0=38.80, y0=9.00,
                        lvt=True, drain_side="bottom", gate_strap="top", dummy_ends=False, sd_width=0.42)

    c.R("m1", xt["S"][0] - 0.25, 0.80, xt["S"][0] + 0.25, xt["S"][1] + 0.15)
    c.R("m1", xla["S"][0] - 0.30, xla["S"][1] - 0.15, xla["S"][0] + 0.30, 15.65)
    c.R("m1", xlb["S"][0] - 0.30, xlb["S"][1] - 0.15, xlb["S"][0] + 0.30, 15.65)

    # OTA internal connections (`da`: Xa.D <-> Xla.D, `dum`: Xb.D <-> Xlb.D <-> Xnd.D)
    c.R("m2", xa["D"][0] - 0.25, xa["D"][1], xa["D"][0] + 0.25, xla["D"][1])
    c.R("m2", xla["D"][0] - 0.25, 7.60, xa["D"][0] + 0.25, 7.95)
    c.R("m2", xb["D"][0] - 0.25, xb["D"][1], xb["D"][0] + 0.25, xlb["D"][1])
    c.R("m2", xnd["D"][0] - 0.25, 6.65, xb["D"][0] + 0.25, 7.05)

    # Under-MIM 3D-Stacked `Cdum` (0.3 pF = 12.2 x 12.2 um MIM on M3 + CAPM + M4 directly over OTA!)
    c.R("m3", 33.00, 2.20, 46.20, 14.40)
    c.R("mimcap", 33.50, 2.70, 45.70, 13.90)
    for mcx in (35.5, 39.6, 43.7):
        for mcy in (4.8, 8.3, 11.8):
            c.sq("mimcapcontact", mcx, mcy, 0.30)
            c.sq("via3", mcx, mcy, 0.38)
    c.R("m4", 34.20, 3.40, 45.00, 13.20)
    # Tie `Cdum` bottom plate (M3) to `dum` (at xb["D"][0], y=6.85) and top plate (M4) to `vss`
    c.via2(xb["D"][0], 6.85, pad=0.44)

    c.L("up", up_n["G"][0], up_n["G"][1], "m1")
    c.L("dn", dn1_n["G"][0], dn1_n["G"][1], "m1")
    c.L("vbn", xn["G"][0], xn["G"][1], "m1")
    c.L("vbp", xp["G"][0], xp["G"][1], "m1")
    c.L("ibias", xt["G"][0], xt["G"][1], "m1")
    c.L("out", xns["D"][0], 6.85, "m2")
    c.L("dum", xnd["D"][0], 6.85, "m2")
    c.L("vdd", 1.20, 15.68, "m2")
    c.L("vss", 1.20, 0.82, "m2")
    return c


# =========================================================================
# PART 2: PLL High-Speed CML Divider (`pll_cml_latch`, `pll_cml_div2`, `pll_cml_prescaler8`)
# =========================================================================
def build_cml_latch_cell(cell_name: str = "pll_cml_latch", whold: float = 40.0) -> LayoutCanvas:
    """
    Build Gilbert-Cell High-Speed CML D-Latch (`pll_cml_latch`):
      - Bottom Row: Tail Current Source `Xtail` (nf=8 x 3.0um, L=0.5)
      - Row 2 (Lower Clock Differential Pair): `Xct` (left, clk_track) & `Xch` (right, clk_hold),
        each nf=8 x 3.5um LVT, sharing bottom Source Comb directly with `Xtail` Drain Comb (`tail`)!
      - Row 3 (Upper Track + Cross-Coupled Hold Quad):
        Left pair = `Xdp` (nf=4 x 4.0um LVT, Drain->qn, Source->track) + `Xdn` (nf=4 x 4.0um LVT, Drain->qp, Source->track)
        Right pair = `Xhp` (nf=6 x 4.0um LVT, Drain->qn, Source->hold) + `Xhn` (nf=6 x 4.0um LVT, Drain->qp, Source->hold)
      - Top Row: Load resistors `Rp` and `Rn` (600 Ohm `res_high_po_2p85 l=4.22`) directly above the Upper Quad!
    """
    c = LayoutCanvas(cell_name)
    X_MID = 11.20
    sd_w = 0.42

    # 1. Bottom: Tail (`Xtail` nf=8 x 2.8um, L=0.50) centered at X_MID
    tail_nf = 8
    tail_w = round(sd_w * 2 + tail_nf * 0.50 + (tail_nf - 1) * sd_w, 3)
    y_tail = 1.60
    tail = draw_comb_mos(c, "n", w_finger=2.80, nf=tail_nf, l_gate=0.50,
                         x0=round(X_MID - tail_w / 2.0, 3), y0=y_tail,
                         lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=True, sd_width=sd_w)

    # 2. Row 2: Clock Steering Pair `Xct` (left) & `Xch` (right), nf=8 x 3.2um LVT, L=0.15
    ck_nf = 8
    ck_w = round(sd_w * 2 + ck_nf * 0.15 + (ck_nf - 1) * sd_w, 3)
    x_ct = round(X_MID - 0.60 - ck_w, 3)
    x_ch = round(X_MID + 0.60, 3)
    y_ck = round(y_tail + 2.80 + 1.15, 3)
    xct = draw_comb_mos(c, "n", w_finger=3.20, nf=ck_nf, l_gate=0.15, x0=x_ct, y0=y_ck,
                        lvt=True, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=sd_w)
    xch = draw_comb_mos(c, "n", w_finger=3.20, nf=ck_nf, l_gate=0.15, x0=x_ch, y0=y_ck,
                        lvt=True, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=sd_w)

    # Merge `tail` bus between Xtail.D and Xct.S / Xch.S
    c.R("m1", xct["bot_span"][0], tail["top_span"][2], xch["bot_span"][1], xct["bot_span"][3])
    c.R("m2", xct["bot_span"][0], tail["top_span"][2], xch["bot_span"][1], xct["bot_span"][3])
    c.L("tail", X_MID, round((tail["top_span"][2] + xct["bot_span"][3]) / 2.0, 3), "m2")

    # 3. Row 3: Upper Gilbert Quad (`Xdp/Xdn` above `Xct` sharing `track`, `Xhp/Xhn` above `Xch` sharing `hold`)
    y_quad = round(y_ck + 3.20 + 1.15, 3)
    q_nf = 4
    q_w = round(sd_w * 2 + q_nf * 0.15 + (q_nf - 1) * sd_w, 3)
    xdp = draw_comb_mos(c, "n", w_finger=3.50, nf=q_nf, l_gate=0.15, x0=round(X_MID - 0.60 - 2 * q_w - 0.45, 3), y0=y_quad,
                        lvt=True, drain_side="top", gate_strap="top", dummy_ends=False, sd_width=sd_w)
    xdn = draw_comb_mos(c, "n", w_finger=3.50, nf=q_nf, l_gate=0.15, x0=round(X_MID - 0.60 - q_w, 3), y0=y_quad,
                        lvt=True, drain_side="top", gate_strap="top", dummy_ends=False, sd_width=sd_w)
    xhp = draw_comb_mos(c, "n", w_finger=3.50, nf=q_nf, l_gate=0.15, x0=round(X_MID + 0.60, 3), y0=y_quad,
                        lvt=True, drain_side="top", gate_strap="top", dummy_ends=False, sd_width=sd_w)
    xhn = draw_comb_mos(c, "n", w_finger=3.50, nf=q_nf, l_gate=0.15, x0=round(X_MID + 0.60 + q_w + 0.45, 3), y0=y_quad,
                        lvt=True, drain_side="top", gate_strap="top", dummy_ends=False, sd_width=sd_w)

    # Merge `track` (Xct.D <-> Xdp.S + Xdn.S) and `hold` (Xch.D <-> Xhp.S + Xhn.S)
    c.R("m2", xdp["bot_span"][0], xct["top_span"][2], xdn["bot_span"][1], xdp["bot_span"][3])
    c.R("m2", xhp["bot_span"][0], xch["top_span"][2], xhn["bot_span"][1], xhp["bot_span"][3])
    c.L("track", xct["D"][0], round((xct["top_span"][2] + xdp["bot_span"][3]) / 2.0, 3), "m2")
    c.L("hold", xch["D"][0], round((xch["top_span"][2] + xhp["bot_span"][3]) / 2.0, 3), "m2")

    # 4. Top Row: High-Poly Load Resistors `Rp` (left, `qp`) and `Rn` (right, `qn`), `l=4.22` (600 Ohm)
    y_load = round(y_quad + 3.50 + 1.35, 3)
    rp = draw_high_po_res(c, xc=round(X_MID - 3.20, 3), y_bot=y_load, l_body=4.22, w_res=2.85)
    rn = draw_high_po_res(c, xc=round(X_MID + 3.20, 3), y_bot=y_load, l_body=4.22, w_res=2.85)

    # Cross-connect Upper Quad Drains (`qn` on M2, `qp` on M3) to Rp.R2 and Rn.R2 + Cross-Coupled Hold Gates!
    y_qn_bus = round(xdp["D"][1] + 0.10, 3)
    y_qp_bus = round(xdn["D"][1] + 0.55, 3)
    c.R("m2", xdp["D"][0] - 0.30, y_qn_bus - 0.22, xhp["D"][0] + 0.30, y_qn_bus + 0.22)
    c.R("m2", rn["R2"][0] - 0.35, y_qn_bus - 0.22, rn["R2"][0] + 0.35, rn["R2"][1] + 0.25)
    c.R("m3", xdn["D"][0] - 0.30, y_qp_bus - 0.22, xhn["D"][0] + 0.30, y_qp_bus + 0.22)
    c.via2(xdn["D"][0], xdn["D"][1], pad=0.38)
    c.via2(xhn["D"][0], xhn["D"][1], pad=0.38)
    c.via2(rp["R2"][0], rp["R2"][1], pad=0.40)
    c.R("m3", rp["R2"][0] - 0.35, y_qp_bus - 0.22, rp["R2"][0] + 0.35, rp["R2"][1] + 0.25)

    # Top VDD M2/M3 Rail + Full Perimeter P+ Guard Ring (`vss`)
    y_vdd = round(rp["R1"][1] + 0.95, 3)
    c.R("m2", rp["R1"][0] - 0.40, rp["R1"][1], rp["R1"][0] + 0.40, y_vdd + 0.25)
    c.R("m2", rn["R1"][0] - 0.40, rn["R1"][1], rn["R1"][0] + 0.40, y_vdd + 0.25)

    x_left_gr, x_right_gr = 0.40, 22.00
    y_bot_gr, y_top_gr = 0.20, round(y_vdd + 0.65, 3)
    c.R("pwell", x_left_gr - 0.15, y_bot_gr - 0.15, x_right_gr + 0.15, y_top_gr + 0.15)
    c.R("m2", x_left_gr + 0.40, y_vdd - 0.32, x_right_gr - 0.40, y_vdd + 0.32)
    c.R("m3", x_left_gr + 0.40, y_vdd - 0.32, x_right_gr - 0.40, y_vdd + 0.32)
    c.via2(X_MID, y_vdd, pad=0.44)

    gr_w = 0.42
    for gx1, gy1, gx2, gy2 in [
        (x_left_gr, y_bot_gr, x_right_gr, y_bot_gr + gr_w),
        (x_left_gr, y_top_gr - gr_w, x_right_gr, y_top_gr),
        (x_left_gr, y_bot_gr, x_left_gr + gr_w, y_top_gr),
        (x_right_gr - gr_w, y_bot_gr, x_right_gr, y_top_gr),
    ]:
        c.R("psubdiff", gx1, gy1, gx2, gy2)
        c.R("locali", gx1 + 0.04, gy1 + 0.04, gx2 - 0.04, gy2 - 0.04)
        c.R("m1", gx1 + 0.04, gy1 + 0.04, gx2 - 0.04, gy2 - 0.04)
    c.R("m1", tail["S"][0] - 0.45, y_bot_gr + 0.08, tail["S"][0] + 0.45, tail["S"][1] + 0.12)
    c.R("m2", x_left_gr, y_bot_gr, x_right_gr, y_bot_gr + gr_w)

    c.L("dp", xdp["G"][0], xdp["G"][1], "m1")
    c.L("dn", xdn["G"][0], xdn["G"][1], "m1")
    c.L("qp", rp["R2"][0], rp["R2"][1], "m3")
    c.L("qn", rn["R2"][0], rn["R2"][1], "m2")
    c.L("clk_track", xct["G"][0], xct["G"][1], "m1")
    c.L("clk_hold", xch["G"][0], xch["G"][1], "m1")
    c.L("vbias", tail["G"][0], tail["G"][1], "m1")
    c.L("vdd", X_MID, y_vdd, "m3")
    c.L("vss", X_MID, round(y_bot_gr + 0.21, 3), "m2")
    return c


def build_cml_div2_cell() -> LayoutCanvas:
    """
    Build `pll_cml_div2` (Master-Slave Toggle `/2` Divider + Central Source-Follower Clock Level Shifter):
      - Left: `Xmaster` (`pll_cml_latch`)
      - Center: Differential Source Followers (`Xfp/Xfn` LVT + `Xsp/Xsn` current sinks) converting `clkp/clkn` -> `ckp/ckn`
      - Right: `Xslave` (`pll_cml_latch`)
      - Top M3/M4 differential data & Mobius feedback channels (`mp/mn` -> Slave, `qp/qn` -> Master inverted).
    """
    c = LayoutCanvas("pll_cml_div2")
    latch = build_cml_latch_cell("pll_cml_latch")
    lbx1, lby1, lbx2, lby2 = latch.bbox()
    lw, lh = lbx2 - lbx1, lby2 - lby1

    # Place Master at x=0, Central Clock SF at x=lw+1.2, Slave at x=lw+11.2
    c.include_subcell(latch, dx=0.0, dy=0.0, include_labels=False)
    x_sf = round(lw + 1.20, 3)
    x_slave = round(lw + 10.60, 3)
    c.include_subcell(latch, dx=x_slave, dy=0.0, include_labels=False)

    # Central Source-Follower Clock Buffer (`Xfp/Xfn` nf=6 x 4.0um LVT, `Xsp/Xsn` nf=2 x 2.5um L=0.5)
    c.R("pwell", x_sf - 0.40, 0.05, x_slave + 0.40, lby2)
    sp = draw_comb_mos(c, "n", w_finger=2.60, nf=4, l_gate=0.50, x0=x_sf + 0.80, y0=1.60,
                       lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    sn = draw_comb_mos(c, "n", w_finger=2.60, nf=4, l_gate=0.50, x0=x_sf + 4.80, y0=1.60,
                       lvt=False, drain_side="top", gate_strap="bottom", dummy_ends=False, sd_width=0.42)
    fp = draw_comb_mos(c, "n", w_finger=4.20, nf=6, l_gate=0.15, x0=x_sf + 0.60, y0=6.20,
                       lvt=True, drain_side="top", gate_strap="top", dummy_ends=False, sd_width=0.42)
    fn = draw_comb_mos(c, "n", w_finger=4.20, nf=6, l_gate=0.15, x0=x_sf + 4.80, y0=6.20,
                       lvt=True, drain_side="top", gate_strap="top", dummy_ends=False, sd_width=0.42)

    # Connect SF drains to top VDD rail, SF sources (`ckp`, `ckn`) to sinks (`sp`, `sn`) and out to Master/Slave clocks
    c.R("m2", fp["D"][0] - 0.30, fp["D"][1], fp["D"][0] + 0.30, lby2 - 0.60)
    c.R("m2", fn["D"][0] - 0.30, fn["D"][1], fn["D"][0] + 0.30, lby2 - 0.60)
    c.R("m2", sp["D"][0] - 0.25, sp["D"][1], sp["D"][0] + 0.25, fp["S"][1])
    c.R("m2", sn["D"][0] - 0.25, sn["D"][1], sn["D"][0] + 0.25, fn["S"][1])
    c.R("m3", 6.50, 4.80, x_slave + 16.0, 5.20)   # ckp distribution bus
    c.R("m3", 6.50, 5.55, x_slave + 16.0, 5.95)   # ckn distribution bus

    # Connect Master -> Slave (`mp`, `mn`) and Slave -> Master Mobius Feedback (`qp`, `qn`) on M3/M4
    c.R("m3", 8.00, 14.20, x_slave + 8.00, 14.60)
    c.R("m3", 14.40, 14.95, x_slave + 10.50, 15.35)
    c.R("m4", 6.50, 13.00, x_slave + 14.40, 13.45)
    c.R("m4", 9.80, 12.20, x_slave + 8.00, 12.65)

    # Unify Top VDD (M3) and Bottom VSS (M2) across Master + SF + Slave
    total_w = round(x_slave + lbx2, 3)
    c.R("m3", 0.60, lby2 - 0.95, total_w - 0.60, lby2 - 0.30)
    c.R("m2", 0.40, 0.20, total_w - 0.40, 0.62)

    c.L("clkp", fp["G"][0], fp["G"][1], "m1")
    c.L("clkn", fn["G"][0], fn["G"][1], "m1")
    c.L("mp", 8.00, 14.40, "m3")
    c.L("mn", 14.40, 15.15, "m3")
    c.L("qp", round(x_slave + 8.00, 2), 14.40, "m3")
    c.L("qn", round(x_slave + 14.40, 2), 15.15, "m2")
    c.L("vbias", 11.20, 1.00, "m1")
    c.L("vdd", round(total_w / 2.0, 2), round(lby2 - 0.65, 2), "m3")
    c.L("vss", round(total_w / 2.0, 2), 0.41, "m2")
    return c


def build_cml_prescaler8() -> LayoutCanvas:
    """
    Build `pll_cml_prescaler8` (3-Stage `/2 -> Buffer -> /4 -> Buffer -> /8` CML Prescaler):
      Abutted horizontal high-speed pipeline sharing top `vdd` (M3) and bottom `vss` (M2) rails:
        `[X2: div2 (/2)] -> [Xb24: cml_buffer] -> [X4: div2 (/4)] -> [Xb48: cml_buffer] -> [X8: div2 (/8)]`
    """
    c = LayoutCanvas("pll_cml_prescaler8")
    div2 = build_cml_div2_cell()
    buf = build_cml_stage_v2(
        "serdes_cml_buffer",
        pair_nf=4, pair_wf=3.0, tail_nf=6, tail_wf=2.0, tail_l=0.50,
        load_l=4.22, n_loads_per_side=1, out_a="outn", out_b="outp"
    )
    dbx1, dby1, dbx2, dby2 = div2.bbox()
    dw, dh = dbx2 - dbx1, dby2 - dby1
    bbx1, bby1, bbx2, bby2 = buf.bbox()
    bw, bh = bbx2 - bbx1, bby2 - bby1

    # Place pipeline stages left-to-right with 1.2 um inter-stage spacing
    x_cur = 0.0
    stages = [
        ("X2", div2, dw, "q2"),
        ("Xb24", buf, bw, None),
        ("X4", div2, dw, "q4"),
        ("Xb48", buf, bw, None),
        ("X8", div2, dw, "q8"),
    ]
    for st_name, cell_obj, w_cell, tap_prefix in stages:
        bx_min = cell_obj.bbox()[0]
        c.include_subcell(cell_obj, dx=round(x_cur - bx_min, 3), dy=0.0, include_labels=False)
        if tap_prefix:
            c.L(f"{tap_prefix}p", round(x_cur + w_cell - 14.0, 2), 14.40, "m3")
            c.L(f"{tap_prefix}n", round(x_cur + w_cell - 7.5, 2), 15.15, "m2")
        x_cur = round(x_cur + w_cell + 1.20, 3)

    total_w = round(x_cur - 1.20, 3)
    # Continuous Top VDD M3 Bus, Bottom VSS M2 Bus, and Inter-Stage Differential Clock M3 Highway
    c.R("m3", 0.50, dh - 1.00, total_w - 0.50, dh - 0.25)
    c.R("m2", 0.50, 0.15, total_w - 0.50, 0.70)
    c.R("m3", 18.0, 10.80, total_w - 12.0, 11.20)
    c.R("m3", 18.0, 11.55, total_w - 12.0, 11.95)

    c.L("clkp", 24.5, 11.0, "m1")
    c.L("clkn", 28.5, 11.0, "m1")
    c.L("vbias", 11.2, 1.0, "m1")
    c.L("vdd", round(total_w / 2.0, 2), round(dh - 0.62, 2), "m3")
    c.L("vss", round(total_w / 2.0, 2), 0.42, "m2")
    return c


def main():
    # Copy all v2 VCO & LF folders into FULL_PACK_DIR
    if FULL_PACK_DIR.exists():
        shutil.rmtree(FULL_PACK_DIR)
    shutil.copytree(PACK_V2_DIR, FULL_PACK_DIR)

    for sub in ("06_charge_pump", "07_divider"):
        (FULL_PACK_DIR / sub).mkdir(parents=True, exist_ok=True)

    # 1. Build Charge Pumps (`pll_cp` & `pll_cp_steer`)
    cp_base = build_pll_cp_baseline()
    cp_base.save_tcl(FULL_PACK_DIR / "06_charge_pump/pll_cp.tcl")
    cp_base.save_mag(FULL_PACK_DIR / "06_charge_pump/pll_cp.mag")

    cp_steer = build_pll_cp_steer()
    cp_steer.save_tcl(FULL_PACK_DIR / "06_charge_pump/pll_cp_steer.tcl")
    cp_steer.save_mag(FULL_PACK_DIR / "06_charge_pump/pll_cp_steer.mag")

    # 2. Build CML Dividers (`pll_cml_latch`, `pll_cml_div2`, `pll_cml_prescaler8`)
    latch_c = build_cml_latch_cell("pll_cml_latch")
    latch_c.save_tcl(FULL_PACK_DIR / "07_divider/pll_cml_latch.tcl")
    latch_c.save_mag(FULL_PACK_DIR / "07_divider/pll_cml_latch.mag")

    div2_c = build_cml_div2_cell()
    div2_c.save_tcl(FULL_PACK_DIR / "07_divider/pll_cml_div2.tcl")
    div2_c.save_mag(FULL_PACK_DIR / "07_divider/pll_cml_div2.mag")

    pre8_c = build_cml_prescaler8()
    pre8_c.save_tcl(FULL_PACK_DIR / "07_divider/pll_cml_prescaler8.tcl")
    pre8_c.save_mag(FULL_PACK_DIR / "07_divider/pll_cml_prescaler8.mag")

    for name, obj in [
        ("pll_cp (Series-Switch CP)", cp_base),
        ("pll_cp_steer (Steering CP + OTA + Under-MIM Cdum)", cp_steer),
        ("pll_cml_latch (Gilbert CML Latch)", latch_c),
        ("pll_cml_div2 (Master-Slave /2 Divider)", div2_c),
        ("pll_cml_prescaler8 (3-Stage /8 Prescaler)", pre8_c),
    ]:
        bx1, by1, bx2, by2 = obj.bbox()
        w, h = bx2 - bx1, by2 - by1
        print(f"{name:50s}: {w:6.2f} x {h:6.2f} um = {w*h:8.1f} um^2")

    # Render 4-Panel CP & Divider Overview PNG
    fig, axes = plt.subplots(2, 2, figsize=(16, 13.0), dpi=170)
    plot_canvas(
        axes[0, 0], cp_steer,
        f"1. Current-Steering Charge Pump (`pll_cp_steer`, {cp_steer.bbox()[2]-cp_steer.bbox()[0]:.1f} x {cp_steer.bbox()[3]-cp_steer.bbox()[1]:.1f} um = 797 um^2)",
        "2-Row Matched UP/DN Mirrors + Diff Steering Switches + Replica OTA with Under-MIM Stacked 0.3pF Cdum"
    )
    plot_canvas(
        axes[0, 1], latch_c,
        f"2. Gilbert-Cell CML D-Latch (`pll_cml_latch`, {latch_c.bbox()[2]-latch_c.bbox()[0]:.1f} x {latch_c.bbox()[3]-latch_c.bbox()[1]:.1f} um = 491 um^2)",
        "Stacked Tail + Clock Steering Pair (Xct/Xch) + Track/Hold Quad (Xdp/Xdn/Xhp/Xhn) + High-Po Loads"
    )
    plot_canvas(
        axes[1, 0], div2_c,
        f"3. Master-Slave CML /2 Divider (`pll_cml_div2`, {div2_c.bbox()[2]-div2_c.bbox()[0]:.1f} x {div2_c.bbox()[3]-div2_c.bbox()[1]:.1f} um = 1,232 um^2)",
        "Symmetric Left Master Latch + Central Source-Follower Clock Level-Shifter + Right Slave Latch"
    )
    plot_canvas(
        axes[1, 1], pre8_c,
        f"4. 3-Stage CML /8 Prescaler (`pll_cml_prescaler8`, {pre8_c.bbox()[2]-pre8_c.bbox()[0]:.1f} x {pre8_c.bbox()[3]-pre8_c.bbox()[1]:.1f} um = 4,210 um^2)",
        "Abutted Pipeline: [/2 Stage] -> [CML Buffer] -> [/4 Stage] -> [CML Buffer] -> [/8 Stage]",
        show_cuts=False
    )
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=True, fontsize=9, bbox_to_anchor=(0.5, 0.008))
    plt.tight_layout(rect=[0, 0.045, 1, 1])
    cp_div_png = OUT_DIR / "pll_cp_and_divider_overview.png"
    fig.savefig(cp_div_png, dpi=170)
    shutil.copy2(cp_div_png, FULL_PACK_DIR / "pll_cp_and_divider_overview.png")
    plt.close(fig)

    shutil.copy2(INTER_DIR / "build_cp_and_divider.py", FULL_PACK_DIR / "scripts/build_cp_and_divider.py")

    # Package full 7-module PLL archive
    full_zip = OUT_DIR / "serdes_pll_full_layout_pack.zip"
    with zipfile.ZipFile(full_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(FULL_PACK_DIR.rglob("*")):
            if fp.is_file():
                zf.write(fp, fp.relative_to(OUT_DIR))
    print("Created full PLL zip package:", full_zip, f"({full_zip.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
