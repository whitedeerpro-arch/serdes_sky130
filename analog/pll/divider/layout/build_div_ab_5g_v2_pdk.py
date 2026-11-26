#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder & Signoff Suite for the Dual-Rate 4G/5G
PLL Feedback Divider A (`pll_div_ab_5g_pdk`).

Implements `analog/pll/divider/spice/pll_div_ab_5g_cand.spice` (`pll_div_ab_5g`,
254 MOSFETs, 8 ports: `clkp clkn mode_5g rst_n fb250 fb250_b vdd vss`) 1-to-1:
  - 2.0 GHz /8 (`mode_5g=0`) and 2.5 GHz /10 (`mode_5g=1`) -> 250 MHz, 50% duty,
    fast-clock Nikolic SAFF-TSPC retimed.
  - Pure M1-M4 routing (0.0% M5 usage), mirrored split-half across center VSS
    spine (`y = 0`), with dual top/bottom VDD rails (`y = +-11.000 um`) joined
    by an external-left M4 bridge and 6 vertical substrate/nwell tap walls.
  - Clean West -> East signal flow:
      [Xrst/Xmode] -> [Xin (3-stage diff-to-CMOS + ck_rt)] |W1|
      [Xdiv2 (Nikolic SAFF /2) + Xckhp/n] |W2|
      [Xfb_p/n (AOI21/OAI21) + Xff0 + Xff1 + Xff2 (3x diff MS-DFF /4 /5)] |W3|
      [Xdly + Xsh_n/p (dual-edge 50% shaper)] |W4|
      [Xretime (Nikolic SAFF retimer on ck_rt) + Xout_p/n]
  - `ck_rt` runs on a dedicated low-R M4 spine (`y = -9.860 um`), flanked on
    both sides by DC-static `rst_n` (`-9.060 um`) and `-VDD` (`-11.000 um`),
    >= 2.3 um clear of `q2n`, >= 3.0 um clear of `q1n`, >= 3.8 um clear of
    `q0n`, and >= 4.5 um clear of `ckh_n`.
  - Differential pairs (`clkp/clkn`, `s1p/s1n`, `s2p/s2n`, `ckp/ckn`,
    `h0p/h0n`, `ckh_p/ckh_n`, `fb250/fb250_b`) are mirror-matched across `y=0`.
  - Zero ngspice invocations; all scratch/extract/DRC/LVS/PEX files stay
    strictly under `results/layout/pll_divider/div_ab_5g_pdk/`.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
RX_LAYOUT_DIR = REPO / "analog/rx/cmos_rx/layout"
LAYOUT_VERIF = REPO / "verification/layout"
for _p in (RX_LAYOUT_DIR, LAYOUT_VERIF):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import rx_layout_common as rlc  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_STD,
    N_LVT,
    P_STD,
    P_LVT,
    grid,
    poly_cont_pad,
    viali_pad,
    via3_pad,
    locali_v,
    locali_h,
)

CELL_NAME = "pll_div_ab_5g_v2_pdk"
SRC_SPICE = REPO / "analog/pll/divider/spice/pll_div_ab_5g_v2.spice"
COMMON_SPICE = REPO / "analog/common/devices/spice"
DEFAULT_OUT_DIR = REPO / "results/layout/pll_divider/div_ab_5g_v2_pdk"
DEFAULT_INSTALL_DIR = REPO / "analog/pll/divider/layout/variants/div_ab_5g_v2_pdk"

EXPECTED_PORTS = ["clkp", "clkn", "mode_5g", "rst_n", "fb250", "fb250_b", "vdd", "vss"]

# ---------------------------------------------------------------------------
# Routing & Floorplan Y-Stack (Top = +Y, Bottom = -Y mirrored across y = 0)
# ---------------------------------------------------------------------------
W_M1 = 0.180
W_M2 = 0.300
W_M3 = 0.300
W_M3_CK = 0.360
W_M4 = 0.400
W_PWR_M1 = 0.360
W_PWR_M2 = 0.520
W_PWR_M3 = 0.560
W_PWR_M4 = 0.800

Y_VSS = 0.000
H_TAP_VSS = 0.145
H_TAP_VDD = 0.175
V_TAP_WALL = 0.180
V_TAP_EDGE = 0.220

Y_N_TOP = 3.020        # Max NMOS w_f=2.40 -> [0.620..3.020], 0.475 um clear of psubdiff
NPOLY_TIE = (3.110, 3.260)
Y_T0 = 3.410           # N-gate / cross-couple M1 track
Y_T1 = 4.050           # Main stage node M1 track
Y_T2 = 4.690           # P-gate / secondary M1 track
PPOLY_TIE = (4.840, 4.990)
Y_P_BOT = 5.080        # Max PMOS w_f=3.20 -> [5.080..8.280]

# Internal diffusion M1 strap heights
Y_TAIL = 2.080         # SAFF tail node (NMOS diff)
Y_NSP = 2.640          # SAFF n_sp / n_sn node (NMOS diff)
Y_EQ_S = 5.660         # SAFF Xeq.S tap (PMOS diff)
Y_N_INT = 2.520        # AOI21/OAI21 NMOS series node
Y_P_INT = 5.810        # AOI21/OAI21 PMOS series node
Y_TG_SN = 2.460        # TG NMOS input strap
Y_TG_SP = 5.760        # TG PMOS input strap

# 6 symmetric M3 horizontal tracks (0.750 um pitch -> 0.350 um via2 pad clearance)
Y_M3_CKH = 5.310       # ckh_p (+Y) / ckh_n (-Y); also local s2p/s2n inside Xin
Y_M3_Q0 = 6.060        # left: h0p/h0n; right: q0p/q0n
Y_M3_Q1 = 6.810        # left: ckp (local); mid: q1p/q1n; right: q0dp/q0dn
Y_M3_Q2 = 7.560        # mid: q2p/q2n; right: qsh_n/qsh_p
Y_M3_MODE = 8.310      # DC static mode_5g (+Y) / mode_5g_b (-Y)
Y_M3_RST = 9.060       # DC static rst (+Y) / rst_n (-Y)

# Dedicated shielded M4 retimer clock track (-Y only, flanked by DC rst_n and -VDD)
Y_M4_CKRT = 9.860      # Used at -Y_M4_CKRT = -9.860

# Dual VDD rails
Y_VDD = 11.000         # M4 inner edge 10.500 (0.380 clear of ck_rt via3 pad)

# Differential M4 port pin bars
Y_M4_PAD = 4.650
Y_M4_PORT = 5.700
Y_M4_TOP = 6.300


def _sy(sgn: int, y: float) -> float:
    return grid(sgn * y)


# ---------------------------------------------------------------------------
# Reference SPICE Flattener (100% exact 1:1 from pll_div_ab_5g_cand.spice)
# ---------------------------------------------------------------------------

def generate_div_ab_ref_spice(out_path: Path, cell_name: str = CELL_NAME) -> list[str]:
    """Flatten `pll_div_ab_5g_cand.spice` into exact SKY130 primitives for Netgen."""
    subckts = rlc._parse_spice_subckts([
        COMMON_SPICE / "sky130_primitives.spice",
        COMMON_SPICE / "sky130_pfet_lvt.spice",
        SRC_SPICE,
    ])
    top = subckts["pll_div_ab_5g_v2"]
    ports = list(top["ports"])
    lines = [
        f"* Exact flattened LVS reference netlist for {cell_name}",
        f"* Source: {SRC_SPICE.relative_to(REPO)} (.subckt pll_div_ab_5g_v2)",
        f".subckt {cell_name} " + " ".join(ports),
    ]
    dev_idx = 0

    def expand(sub_name: str, port_map: dict[str, str], env: dict[str, float], prefix: str) -> None:
        nonlocal dev_idx
        sdef = subckts[sub_name]
        local_env = {k: rlc._eval_expr(v, env) for k, v in sdef["defaults"].items()}
        local_env.update(env)
        for inst_name, conns, model, ov in sdef["insts"]:
            mapped = [port_map.get(c, f"{prefix}_{c}") for c in conns]
            cenv = {k: rlc._eval_expr(v, local_env) for k, v in ov.items()}
            if model.startswith("sky130_fd_pr__"):
                dev_idx += 1
                w_str = rlc._fmt_num(cenv["w"])
                l_str = rlc._fmt_num(cenv["l"])
                lines.append(f"X{dev_idx} " + " ".join(mapped) + f" {model} w={w_str} l={l_str}")
            else:
                cdef = subckts[model]
                expand(model, dict(zip(cdef["ports"], mapped)), cenv, f"{prefix}_{inst_name}")

    expand("pll_div_ab_5g_v2", {p: p for p in ports}, {}, "t")
    lines.extend([f".ends {cell_name}", ""])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return ports


# ---------------------------------------------------------------------------
# Low-Level Mirrored-Half Column & Wiring Primitives
# ---------------------------------------------------------------------------

def _draw_tap_h(c: Cell, diff_layer: str, x1: float, x2: float, y: float, half_w: float) -> None:
    x1, x2, y = grid(x1), grid(x2), grid(y)
    c.rect(diff_layer, x1, grid(y - half_w), x2, grid(y + half_w))
    c.rect("locali", x1, grid(y - 0.085), x2, grid(y + 0.085))
    if (x2 - x1) >= 0.48:
        c.rect(diff_layer + "cont", grid(x1 + 0.14), grid(y - 0.085), grid(x2 - 0.14), grid(y + 0.085))


def _draw_tap_v(c: Cell, diff_layer: str, x: float, y1: float, y2: float, half_w: float) -> None:
    x, y1, y2 = grid(x), grid(min(y1, y2)), grid(max(y1, y2))
    c.rect(diff_layer, grid(x - half_w), grid(y1 - 0.085), grid(x + half_w), grid(y2 + 0.085))
    c.rect("locali", grid(x - 0.085), grid(y1 - 0.085), grid(x + 0.085), grid(y2 + 0.085))
    if (y2 - y1) >= 0.90:
        c.rect(diff_layer + "cont", grid(x - 0.085), grid(y1 + 0.360), grid(x + 0.085), grid(y2 - 0.360))


def _draw_np_wall_band(c: Cell, x: float, y_vss: float, y_t1: float, y_vdd: float, half_w: float) -> None:
    if y_vss < y_vdd:
        _draw_tap_v(c, "psubdiff", x, y_vss, grid(y_t1 - 0.360), half_w)
        _draw_tap_v(c, "nsubdiff", x, grid(y_t1 + 0.360), y_vdd, half_w)
    else:
        _draw_tap_v(c, "nsubdiff", x, y_vdd, grid(y_t1 - 0.360), half_w)
        _draw_tap_v(c, "psubdiff", x, grid(y_t1 + 0.360), y_vss, half_w)
    c.pad("viali", x, y_vss, 0.17)
    c.pad("metal1", x, y_vss, 0.32)
    c.pad("viali", x, y_vdd, 0.17)
    c.pad("metal1", x, y_vdd, 0.32)


def _place_col(
    c: Cell,
    cache: PdkCache,
    x_edge: float,
    *,
    n_top: tuple[str, float, float, int] | None = None,
    p_top: tuple[str, float, float, int] | None = None,
    n_bot: tuple[str, float, float, int] | None = None,
    p_bot: tuple[str, float, float, int] | None = None,
    gap_l: float = 0.560,
) -> tuple[dict, float]:
    """Place a column with independently specified Top/Bot NMOS & PMOS: `(model, w_f, l_f, nf)`."""
    built: dict[str, tuple[Cell, dict] | None] = {}
    hws: list[float] = []
    for key, spec, is_p in (
        ("nt", n_top, False),
        ("pt", p_top, True),
        ("nb", n_bot, False),
        ("pb", p_bot, True),
    ):
        if spec is None:
            built[key] = None
            continue
        mdl, wf, lf, nf = spec
        wf, lf = grid(wf), grid(lf)
        dy = grid(Y_P_BOT + wf / 2.0) if is_p else grid(Y_N_TOP - wf / 2.0)
        cm, inf = cache.build_mos(mdl, wf, lf, nf, dy, is_p)
        built[key] = (cm, inf)
        hws.append(inf["hw_diff"])
    hw = max(hws)
    cx = grid(x_edge + gap_l + hw)
    x_next = grid(cx + hw)
    if built["nt"]:
        c.include(built["nt"][0], dx=cx, mirror_y=False)
    if built["pt"]:
        c.include(built["pt"][0], dx=cx, mirror_y=False)
    if built["nb"]:
        c.include(built["nb"][0], dx=cx, mirror_y=True)
    if built["pb"]:
        c.include(built["pb"][0], dx=cx, mirror_y=True)

    col: dict = {
        "cx": cx,
        "hw": hw,
        "inf_nt": built["nt"][1] if built["nt"] else None,
        "inf_pt": built["pt"][1] if built["pt"] else None,
        "inf_nb": built["nb"][1] if built["nb"] else None,
        "inf_pb": built["pb"][1] if built["pb"] else None,
    }
    return col, x_next


def _place_sym_col(
    c: Cell,
    cache: PdkCache,
    x_edge: float,
    n_spec: tuple[str, float, float, int] | None,
    p_spec: tuple[str, float, float, int] | None,
    gap_l: float = 0.560,
) -> tuple[dict, float]:
    return _place_col(
        c, cache, x_edge,
        n_top=n_spec, p_top=p_spec, n_bot=n_spec, p_bot=p_spec,
        gap_l=gap_l,
    )


def _inf(col: dict, sgn: int, is_p: bool) -> dict | None:
    if is_p:
        return col["inf_pt"] if sgn > 0 else col["inf_pb"]
    return col["inf_nt"] if sgn > 0 else col["inf_nb"]


def _default_tap_dx(col: dict, sgn: int, use_n: bool, use_p: bool) -> float:
    """Return a gate tap dx strictly clear (>=0.46 um) of all channel drain locali bars."""
    cands: list[float] = []
    if use_n and _inf(col, sgn, False) is not None:
        in_n = _inf(col, sgn, False)
        cands.append(min(in_n["s_xs"]) if in_n["nf"] >= 2 else grid(min(in_n["d_xs"]) - 0.480))
    if use_p and _inf(col, sgn, True) is not None:
        in_p = _inf(col, sgn, True)
        cands.append(min(in_p["s_xs"]) if in_p["nf"] >= 2 else grid(min(in_p["d_xs"]) - 0.480))
    return grid(min(cands))


def _tie_poly_bar(
    c: Cell,
    col: dict,
    sgn: int,
    is_p: bool,
    x_ext_l: float | None = None,
    x_ext_r: float | None = None,
) -> None:
    """Extend all poly fingers of one MOS into NPOLY_TIE / PPOLY_TIE and join horizontally."""
    inf = _inf(col, sgn, is_p)
    if inf is None:
        return
    cx = col["cx"]
    lf = inf["l_f"]
    hw = grid(lf / 2.0)
    g_xs = inf["g_xs"]
    tie = PPOLY_TIE if is_p else NPOLY_TIE
    y_diff = Y_P_BOT if is_p else Y_N_TOP
    ya, yb = sorted((_sy(sgn, tie[0]), _sy(sgn, tie[1])))
    y_edge = _sy(sgn, y_diff)
    y_lo, y_hi = min(ya, y_edge), max(yb, y_edge)
    for gx in g_xs:
        c.rect("poly", grid(cx + gx - hw), y_lo, grid(cx + gx + hw), y_hi)
    xs_l = [cx + g_xs[0] - hw]
    xs_r = [cx + g_xs[-1] + hw]
    if x_ext_l is not None:
        xs_l.append(cx + x_ext_l - max(0.135, hw))
    if x_ext_r is not None:
        xs_r.append(cx + x_ext_r + max(0.135, hw))
    x1, x2 = grid(min(xs_l)), grid(max(xs_r))
    if x2 - x1 > 2 * hw + 0.005:
        c.rect("poly", x1, ya, x2, yb)


def _tap_poly(
    c: Cell,
    col: dict,
    sgn: int,
    is_p: bool,
    y_trk: float,
    tap_dx: float,
    add_viali: bool = True,
) -> float:
    """Drop a DRC-clean polycont (+ optional viali/M1 pad) at `(cx + tap_dx, sgn*y_trk)`."""
    gx = grid(col["cx"] + tap_dx)
    yt = _sy(sgn, y_trk)
    tie = PPOLY_TIE if is_p else NPOLY_TIE
    ys = sorted((yt, _sy(sgn, tie[0]), _sy(sgn, tie[1])))
    c.rect("poly", grid(gx - 0.135), ys[0], grid(gx + 0.135), ys[-1])
    poly_cont_pad(c, gx, yt)
    if add_viali:
        viali_pad(c, gx, yt)
    return gx


def _wire_shared_gate(
    c: Cell,
    col: dict,
    sgn: int,
    y_trk: float,
    tap_dx: float | None = None,
) -> float:
    """Tie N + P poly bars across the channel at `tap_dx`, placing polycont + viali at `sgn*y_trk`."""
    if tap_dx is None:
        tap_dx = _default_tap_dx(col, sgn, True, True)
    _tie_poly_bar(c, col, sgn, False, x_ext_l=tap_dx, x_ext_r=tap_dx)
    _tie_poly_bar(c, col, sgn, True, x_ext_l=tap_dx, x_ext_r=tap_dx)
    xg = grid(col["cx"] + tap_dx)
    ya, yb = sorted((_sy(sgn, NPOLY_TIE[0]), _sy(sgn, PPOLY_TIE[1])))
    c.rect("poly", grid(xg - 0.135), ya, grid(xg + 0.135), yb)
    yt = _sy(sgn, y_trk)
    poly_cont_pad(c, xg, yt)
    viali_pad(c, xg, yt)
    # For wide nf>=3 PMOS, also strap rightmost s_x at Y_T2? No, single poly bar <= 1.8 um is <15 ohm.
    return xg


def _src_to_rail(
    c: Cell,
    col: dict,
    sgn: int,
    is_p: bool,
    n_s_xs: list[float],
    p_s_pts: list[tuple[int, float]],
) -> None:
    inf = _inf(col, sgn, is_p)
    if inf is None:
        return
    cx = col["cx"]
    y_rail = _sy(sgn, Y_VDD if is_p else Y_VSS)
    y_c = _sy(sgn, inf["c_y2"] - 0.06 if is_p else inf["c_y1"] + 0.06)
    for sx in inf["s_xs"]:
        xc = grid(cx + sx)
        locali_v(c, xc, y_rail, y_c)
        if is_p:
            p_s_pts.append((sgn, xc))
        else:
            n_s_xs.append(xc)


def _drains_to_track(
    c: Cell,
    col: dict,
    sgn: int,
    y_trk: float,
    do_n: bool = True,
    do_p: bool = True,
) -> float:
    """Bring NMOS and/or PMOS drain(s) via locali to `sgn*y_trk` with DRC-clean
    locali merging and viali/M1 stitch. Returns rightmost drain X.
    """
    cx = col["cx"]
    yt = _sy(sgn, y_trk)
    pts: list[float] = []
    if do_n and _inf(col, sgn, False) is not None:
        in_n = _inf(col, sgn, False)
        y_n = _sy(sgn, in_n["c_y2"] - 0.06)
        for dx in in_n["d_xs"]:
            xd = grid(cx + dx)
            locali_v(c, xd, y_n, yt)
            pts.append(xd)
    if do_p and _inf(col, sgn, True) is not None:
        in_p = _inf(col, sgn, True)
        y_p = _sy(sgn, in_p["c_y1"] + 0.06)
        for dx in in_p["d_xs"]:
            xd = grid(cx + dx)
            locali_v(c, xd, yt, y_p)
            pts.append(xd)
    pts = sorted(set(pts))
    # Cluster drain stripes closer than 0.380 um (e.g. nf=1 N d=+0.22 & nf=2 P d=0.00):
    # merge their locali with a horizontal bar at yt and drop a single shared viali_pad.
    clusters: list[list[float]] = []
    for xp in pts:
        if clusters and (xp - clusters[-1][-1]) < 0.380:
            clusters[-1].append(xp)
        else:
            clusters.append([xp])
    viali_xs: list[float] = []
    for cl in clusters:
        if len(cl) > 1:
            locali_h(c, cl[0], cl[-1], yt)
        xm = grid((cl[0] + cl[-1]) / 2.0)
        viali_pad(c, xm, yt)
        viali_xs.append(xm)
    if len(viali_xs) > 1:
        c.wire("metal1", [(viali_xs[0], yt), (viali_xs[-1], yt)], W_M1)
    return viali_xs[-1]


def _drains_min_x(col: dict, sgn: int, do_n: bool = True, do_p: bool = True) -> float:
    cx = col["cx"]
    pts: list[float] = []
    if do_n and _inf(col, sgn, False) is not None:
        pts.extend(grid(cx + dx) for dx in _inf(col, sgn, False)["d_xs"])
    if do_p and _inf(col, sgn, True) is not None:
        pts.extend(grid(cx + dx) for dx in _inf(col, sgn, True)["d_xs"])
    return min(pts)


def _wire_cc_xover(c: Cell, col: dict, out_m3_y: float | None = None) -> tuple[float, float]:
    """Cross-couple a 1-finger `cc` / `keep` column whose drains sit at `+-Y_T1` and gates at `+-Y_T0`.
    Returns `(x_qp_m2, x_qn_m2)` where:
      - `x_qn_m2` carries Bottom (`-Y_T1`) -> Top gate (`+Y_T0`) (+ optional `-out_m3_y`)
      - `x_qp_m2` carries Top (`+Y_T1`) -> Bottom gate (`-Y_T0`) (+ optional `+out_m3_y`)
    Pitch between `x_qn_m2` and `x_qp_m2` is `>= 0.580 um` (clean for via2 on both!).
    """
    xg = col["xg"]
    xd = col["xd"]
    x_qn_m2 = xg
    x_qp_m2 = grid(max(xd, xg + 0.580))

    # qn (-Y_T1) -> +Y_T0 (+ optional -out_m3_y)
    c.wire("metal1", [(min(x_qn_m2, xd), -Y_T1), (max(x_qn_m2, xd), -Y_T1)], W_M1)
    c.via1(x_qn_m2, -Y_T1)
    c.via1(x_qn_m2, +Y_T0)
    y_qn_lo = -out_m3_y if out_m3_y is not None else -Y_T1
    if out_m3_y is not None:
        c.via2(x_qn_m2, -out_m3_y)
    c.wire("metal2", [(x_qn_m2, y_qn_lo), (x_qn_m2, +Y_T0)], W_M2)

    # qp (+Y_T1) -> -Y_T0 (+ optional +out_m3_y)
    c.wire("metal1", [(min(xd, x_qp_m2), +Y_T1), (max(xd, x_qp_m2), +Y_T1)], W_M1)
    c.wire("metal1", [(min(xg, x_qp_m2), -Y_T0), (max(xg, x_qp_m2), -Y_T0)], W_M1)
    c.via1(x_qp_m2, +Y_T1)
    c.via1(x_qp_m2, -Y_T0)
    y_qp_hi = +out_m3_y if out_m3_y is not None else +Y_T1
    if out_m3_y is not None:
        c.via2(x_qp_m2, +out_m3_y)
    c.wire("metal2", [(x_qp_m2, -Y_T0), (x_qp_m2, y_qp_hi)], W_M2)
    return x_qp_m2, x_qn_m2


def _place_m4_pin_bar(c: Cell, x: float, sgn: int, y_m1: float) -> None:
    """Bring signal from M1 at `(x, sgn*y_m1)` up to matched M4 pin bar at `sgn*[Y_M4_PAD, Y_M4_TOP]`."""
    ym1 = _sy(sgn, y_m1)
    ypad = _sy(sgn, Y_M4_PAD)
    ytop = _sy(sgn, Y_M4_TOP)
    c.via1(x, ym1)
    c.via2(x, ypad)
    c.wire("metal2", sorted([(x, ym1), (x, ypad)], key=lambda p: p[1]), W_M2)
    via3_pad(c, x, ypad)
    c.wire("metal4", sorted([(x, ypad), (x, ytop)], key=lambda p: p[1]), W_M4)


def _place_filtered_viali(c: Cell, xs: list[float], y: float, min_pitch: float = 0.380) -> list[float]:
    placed: list[float] = []
    for x in sorted({grid(v) for v in xs}):
        if all(abs(x - px) >= min_pitch for px in placed):
            c.pad("viali", x, y, 0.17)
            c.pad("metal1", x, y, 0.32)
            placed.append(x)
    return placed


# ---------------------------------------------------------------------------
# Block Builders
# ---------------------------------------------------------------------------

def build_ctrl_invs(c: Cell, cache: PdkCache, x_l_edge: float) -> dict:
    """Block 0: Static control inverters `Xrst` (+Y: rst_n->rst) & `Xmode` (-Y: mode_5g->mode_5g_b)."""
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    col, x_end = _place_sym_col(
        c, cache, x_l_edge,
        (N_STD, 0.600, 0.18, 1),
        (P_STD, 1.200, 0.18, 1),
        gap_l=1.100,  # space for mode_5g vertical M2 to the left of ctrl.xg
    )
    for sgn in (+1, -1):
        _src_to_rail(c, col, sgn, False, n_s_xs, p_s_pts)
        _src_to_rail(c, col, sgn, True, n_s_xs, p_s_pts)
        col[f"xd_{sgn}"] = _drains_to_track(c, col, sgn, Y_T1)
        col[f"xg_{sgn}"] = _wire_shared_gate(c, col, sgn, Y_T1)

    x_rstn_m2 = col["xg_1"]               # rst_n: -Y_M3_RST -> +Y_T1 (Xrst gate)
    x_mode_m2 = grid(x_rstn_m2 - 0.620)   # mode_5g: +Y_M3_MODE -> -Y_T1 (Xmode gate)
    x_out_m2 = grid(max(col["xd_1"], x_rstn_m2 + 0.600))  # rst (+Y) & mode_5g_b (-Y)

    # mode_5g: M4 port at (x_mode_m2, +Y_M3_MODE) -> M3 +Y_M3_MODE & M2 down to Xmode gate (-Y_T1)
    c.wire("metal1", [(x_mode_m2, -Y_T1), (col["xg_-1"], -Y_T1)], W_M1)
    c.via1(x_mode_m2, -Y_T1)
    c.via2(x_mode_m2, +Y_M3_MODE)
    via3_pad(c, x_mode_m2, +Y_M3_MODE)
    c.wire("metal2", [(x_mode_m2, -Y_T1), (x_mode_m2, +Y_M3_MODE)], W_M2)

    # rst_n: M4 port at (x_rstn_m2, -Y_M3_RST) -> M3 -Y_M3_RST & M2 up to Xrst gate (+Y_T1)
    c.via1(x_rstn_m2, +Y_T1)
    c.via2(x_rstn_m2, -Y_M3_RST)
    via3_pad(c, x_rstn_m2, -Y_M3_RST)
    c.wire("metal2", [(x_rstn_m2, -Y_M3_RST), (x_rstn_m2, +Y_T1)], W_M2)

    # rst (+Y drain -> +Y_M3_RST) & mode_5g_b (-Y drain -> -Y_M3_MODE)
    c.wire("metal1", [(col["xd_1"], +Y_T1), (x_out_m2, +Y_T1)], W_M1)
    c.via1(x_out_m2, +Y_T1)
    c.via2(x_out_m2, +Y_M3_RST)
    c.wire("metal2", [(x_out_m2, +Y_T1), (x_out_m2, +Y_M3_RST)], W_M2)

    c.wire("metal1", [(col["xd_-1"], -Y_T1), (x_out_m2, -Y_T1)], W_M1)
    c.via1(x_out_m2, -Y_T1)
    c.via2(x_out_m2, -Y_M3_MODE)
    c.wire("metal2", [(x_out_m2, -Y_M3_MODE), (x_out_m2, -Y_T1)], W_M2)

    return {
        "x_end": grid(max(x_end, x_out_m2 + 0.300)),
        "x_mode_port": x_mode_m2,
        "x_rstn_port": x_rstn_m2,
        "x_rst_start": x_out_m2,
        "x_rstn_start": x_rstn_m2,
        "x_mode_start": x_mode_m2,
        "x_modeb_start": x_out_m2,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_inbuf(c: Cell, cache: PdkCache, x_l_edge: float) -> dict:
    """Block 1: `divab_inbuf` (3-stage diff-to-CMOS + matched `ck_rt` delay branch)."""
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x = grid(x_l_edge)
    cols: dict[str, dict] = {}

    # Stage 1: low-C_in LVT-N + LVT-P receiver (`X1p/n`) + gentle l=0.28 STD aligner (`Xcc1`)
    cols["s1"], x = _place_sym_col(
        c, cache, x, (N_LVT, 1.200, 0.15, 1), (P_LVT, 2.200, 0.35, 2), gap_l=0.800
    )
    cols["cc1"], x = _place_sym_col(
        c, cache, x, (N_STD, 0.420, 0.28, 1), (P_STD, 0.840, 0.28, 1), gap_l=0.860
    )
    # Stage 2: crisp gain stage (`X2p/n`) + soft l=0.20 STD aligner (`Xcc2`)
    cols["s2"], x = _place_sym_col(
        c, cache, x, (N_LVT, 1.800, 0.15, 1), (P_STD, 2.300, 0.15, 3), gap_l=0.860
    )
    cols["cc2"], x = _place_sym_col(
        c, cache, x, (N_STD, 0.420, 0.20, 1), (P_STD, 1.400, 0.20, 1), gap_l=0.820
    )
    # Stage 3B: 7-stage PVT-tracking ck_rt chain (`Xrt1/dum`, `Xrt2..Xrt7` on -Y)
    cols["rt1"], x = _place_sym_col(
        c, cache, x, (N_LVT, 1.000, 0.15, 1), (P_STD, 1.900, 0.15, 2), gap_l=0.820
    )
    cols["rt2"], x = _place_col(
        c, cache, x, n_bot=(N_LVT, 1.000, 0.15, 1), p_bot=(P_STD, 1.900, 0.15, 2), gap_l=0.620
    )
    cols["rt3"], x = _place_col(
        c, cache, x, n_bot=(N_LVT, 1.200, 0.15, 1), p_bot=(P_STD, 2.300, 0.15, 2), gap_l=0.620
    )
    cols["rt4"], x = _place_col(
        c, cache, x, n_bot=(N_LVT, 1.400, 0.15, 1), p_bot=(P_STD, 2.700, 0.15, 2), gap_l=0.620
    )
    cols["rt5"], x = _place_col(
        c, cache, x, n_bot=(N_LVT, 1.600, 0.15, 1), p_bot=(P_STD, 2.050, 0.15, 3), gap_l=0.620
    )
    cols["rt6"], x = _place_col(
        c, cache, x, n_bot=(N_LVT, 1.000, 0.15, 2), p_bot=(P_STD, 2.600, 0.15, 3), gap_l=0.620
    )
    cols["rt7"], x = _place_col(
        c, cache, x, n_bot=(N_LVT, 1.400, 0.15, 2), p_bot=(P_STD, 2.700, 0.15, 4), gap_l=0.620
    )
    # Stage 3A: balanced driver (`X3p/n`) + soft aligner (`Xcc3`) + matched gate-cap dummy on `ckn` (+Y)
    cols["s3"], x = _place_sym_col(
        c, cache, x, (N_LVT, 1.400, 0.15, 2), (P_STD, 2.700, 0.15, 4), gap_l=0.760
    )
    cols["cc3"], x = _place_sym_col(
        c, cache, x, (N_STD, 0.450, 0.20, 1), (P_STD, 1.600, 0.20, 1), gap_l=0.820
    )
    cols["ckn_dum"], x = _place_col(
        c, cache, x, n_top=(N_LVT, 1.600, 0.15, 2), p_top=(P_STD, 2.000, 0.15, 4), gap_l=0.820
    )

    # Wire symmetric columns (s1, cc1, s2, cc2, rt1, s3, cc3)
    for sgn in (+1, -1):
        y1 = _sy(sgn, Y_T1)
        for nm in ("s1", "cc1", "s2", "cc2", "rt1", "s3", "cc3"):
            col = cols[nm]
            _src_to_rail(c, col, sgn, False, n_s_xs, p_s_pts)
            _src_to_rail(c, col, sgn, True, n_s_xs, p_s_pts)
            col["xd"] = _drains_to_track(c, col, sgn, Y_T1)
            y_g = Y_T0 if nm in ("cc1", "cc2", "cc3") else Y_T1
            col["xg"] = _wire_shared_gate(c, col, sgn, y_g)

        # s1.D -> cc1.D -> s2.G
        c.wire("metal1", [(_drains_min_x(cols["s1"], sgn), y1), (cols["s2"]["xg"], y1)], W_M1)
        # s2.D -> cc2.D -> rt1.G (on +-Y_T1)
        c.wire("metal1", [(_drains_min_x(cols["s2"], sgn), y1), (cols["rt1"]["xg"], y1)], W_M1)
        # s3.D -> cc3.D (ckn on +Y_T1, ckp on -Y_T1)
        c.wire("metal1", [(_drains_min_x(cols["s3"], sgn), y1), (cols["cc3"]["xd"], y1)], W_M1)

    # Differential crossovers at cc1, cc2, cc3
    _wire_cc_xover(c, cols["cc1"])
    x_s2p_m2, x_s2n_m2 = _wire_cc_xover(c, cols["cc2"], out_m3_y=Y_M3_CKH)
    _, x_ckp_m2 = _wire_cc_xover(c, cols["cc3"], out_m3_y=None)

    # Matched West M4 ports clkp (+Y) / clkn (-Y) at s1.xg
    x_clkin = cols["s1"]["xg"]
    for sgn in (+1, -1):
        _place_m4_pin_bar(c, x_clkin, sgn, Y_T1)

    # Route s2p (+Y_M3_CKH) & s2n (-Y_M3_CKH) symmetrically over rt1..rt3 into s3.xg
    xg_s3 = cols["s3"]["xg"]
    c.wire("metal3", [(x_s2p_m2, +Y_M3_CKH), (xg_s3, +Y_M3_CKH)], W_M3_CK)
    c.wire("metal3", [(x_s2n_m2, -Y_M3_CKH), (xg_s3, -Y_M3_CKH)], W_M3_CK)
    for sgn in (+1, -1):
        y1 = _sy(sgn, Y_T1)
        ym3 = _sy(sgn, Y_M3_CKH)
        c.via1(xg_s3, y1)
        c.via2(xg_s3, ym3)
        c.wire("metal2", sorted([(xg_s3, y1), (xg_s3, ym3)], key=lambda p: p[1]), W_M2)

    # Wire rt2..rt7 (-Y only): rt1->rt2->rt3->rt4->rt5->rt6->rt7 -> ck_rt on M4 (-Y_M4_CKRT)
    for nm in ("rt2", "rt3", "rt4", "rt5", "rt6", "rt7"):
        col = cols[nm]
        _src_to_rail(c, col, -1, False, n_s_xs, p_s_pts)
        _src_to_rail(c, col, -1, True, n_s_xs, p_s_pts)
        col["xd"] = _drains_to_track(c, col, -1, Y_T1)
        col["xg"] = _wire_shared_gate(c, col, -1, Y_T1)
    for a_nm, b_nm in (("rt1", "rt2"), ("rt2", "rt3"), ("rt3", "rt4"), ("rt4", "rt5"), ("rt5", "rt6"), ("rt6", "rt7")):
        c.wire("metal1", [(cols[a_nm]["xd"], -Y_T1), (cols[b_nm]["xg"], -Y_T1)], W_M1)

    # Launch ck_rt onto shielded M4 spine at -Y_M4_CKRT
    x_ckrt_launch = cols["rt7"]["xd"]
    c.via1(x_ckrt_launch, -Y_T1)
    c.via2(x_ckrt_launch, -Y_M4_CKRT)
    via3_pad(c, x_ckrt_launch, -Y_M4_CKRT)
    c.wire("metal2", [(x_ckrt_launch, -Y_M4_CKRT), (x_ckrt_launch, -Y_T1)], W_M2)

    # Launch ckp (-Y at cc3) onto local -Y_M3_Q1 to drive adjacent Xdiv2
    c.via2(x_ckp_m2, -Y_M3_Q1)
    c.wire("metal2", [(x_ckp_m2, -Y_M3_Q1), (x_ckp_m2, -Y_T1)], W_M2)

    # Wire matched dummy inverter `ckn_dum` (+Y only): S -> rails, D -> local ckn_dum_out (+Y_T2), G -> ckn (+Y_T1)
    cd = cols["ckn_dum"]
    _src_to_rail(c, cd, +1, False, n_s_xs, p_s_pts)
    _src_to_rail(c, cd, +1, True, n_s_xs, p_s_pts)
    _drains_to_track(c, cd, +1, Y_T2)
    xg_dum = _wire_shared_gate(c, cd, +1, Y_T1)
    c.wire("metal1", [(cols["cc3"]["xd"], +Y_T1), (xg_dum, +Y_T1)], W_M1)

    return {
        "x_end": grid(max(x, cd["cx"] + cd["hw"] + 0.300)),
        "x_clkin": x_clkin,
        "x_ckrt_launch": x_ckrt_launch,
        "x_ckp_launch": x_ckp_m2,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_saff_dff(
    c: Cell,
    cache: PdkCache,
    x_l_edge: float,
    *,
    wt: float,
    wd: float,
    wl: float,
    wlp: float,
    wpre: float,
    wmid: float,
    weq: float,
    wop: float,
    wdn: float,
    winv_n: float,
    winv_p: float,
    wkp: float,
    wkn: float,
    seed_k: float,
    ck_source: str,  # "ckp_m3_q1" (Xdiv2) or "ck_rt_m4" (Xretime)
    in_m3_y: float,
    nfop: int = 2,
    in_swapped: bool = True,
    out_m3_y: float | None = None,
    attach_outbuf: bool = False,
    gap_first: float = 0.680,
) -> dict:
    """Build 8-column Nikolic-Symmetric Equalized SAFF-TSPC DFF with reset clamps
    (`divab_saff_dff`) and optional attached matched output buffer (`Xout_p/n` + `Xcc_out`).
    """
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x = grid(x_l_edge)
    cols: dict[str, dict] = {}

    # Col 0: Xtail (split Top/Bot wt/4 nf=2 -> total wt) & Xpmp/n (wmid nf=1)
    cols["tail_pm"], x = _place_sym_col(
        c, cache, x, (N_LVT, grid(wt / 4.0), 0.15, 2), (P_STD, grid(wmid), 0.15, 1), gap_l=gap_first
    )
    # Col 1: Xdp/n (wd/2 nf=2 LVT) & Xpre (wpre/2 nf=2)
    cols["dp_pre"], x = _place_sym_col(
        c, cache, x, (N_LVT, grid(wd / 2.0), 0.15, 2), (P_STD, grid(wpre / 2.0), 0.15, 2), gap_l=0.580
    )
    # Col 2: Xln (wl/2 nf=2 LVT) & Xlp (wlp nf=1)
    cols["ln_lp"], x = _place_sym_col(
        c, cache, x, (N_LVT, grid(wl / 2.0), 0.15, 2), (P_STD, grid(wlp), 0.15, 1), gap_l=0.520
    )
    # Col 3: Xeq (split Top/Bot weq/2 nf=1 -> total weq), empty NMOS
    cols["eq"], x = _place_sym_col(
        c, cache, x, None, (P_STD, grid(weq / 2.0), 0.15, 1), gap_l=0.520
    )
    # Col 4: Xinvs/Xinvr (`divab_inv`: N_LVT + P_STD!)
    cols["inv"], x = _place_sym_col(
        c, cache, x, (N_LVT, grid(winv_n), 0.15, 1), (P_STD, grid(winv_p), 0.15, 1), gap_l=0.580
    )
    # Col 5: Xdp_d/dn_d (wdn/2 nf=2 LVT) & Xpp_s/pn_s (wop/nfop nf=nfop)
    cols["drv"], x = _place_sym_col(
        c, cache, x, (N_LVT, grid(wdn / 2.0), 0.15, 2), (P_STD, grid(wop / nfop), 0.15, nfop),
        gap_l=(0.820 if nfop >= 4 else 0.720),
    )
    # Col 6: Static cross-coupled keeper (N_STD + P_STD -> gap_l=0.76 for LVT->STD clearance!)
    cols["keep"], x = _place_col(
        c, cache, x,
        n_top=(N_STD, grid(wkn), 0.15, 1),
        p_top=(P_STD, grid(wkp + seed_k), 0.15, 1),
        n_bot=(N_STD, grid(wkn + seed_k), 0.15, 1),
        p_bot=(P_STD, grid(wkp), 0.15, 1),
        gap_l=0.760,
    )
    # Col 7: Reset clamps (`Xrstp` +Y N_STD l=0.18, `Xrstn` -Y P_STD l=0.18)
    cols["rst"], x = _place_col(
        c, cache, x,
        n_top=(N_STD, 1.200, 0.18, 1),
        p_bot=(P_STD, 2.400, 0.18, 1),
        gap_l=0.720,
    )

    if attach_outbuf:
        cols["ob"], x = _place_sym_col(
            c, cache, x, (N_LVT, 1.200, 0.15, 2), (P_STD, 2.100, 0.15, 3), gap_l=0.800
        )
        cols["cc_ob"], x = _place_sym_col(
            c, cache, x, (N_LVT, 0.450, 0.15, 1), (P_STD, 1.200, 0.15, 1), gap_l=0.720
        )

    c0, c1, c2, c3, c4, c5, c6, c7 = (
        cols["tail_pm"], cols["dp_pre"], cols["ln_lp"], cols["eq"],
        cols["inv"], cols["drv"], cols["keep"], cols["rst"],
    )

    for sgn in (+1, -1):
        y0, y1, y2 = _sy(sgn, Y_T0), _sy(sgn, Y_T1), _sy(sgn, Y_T2)
        y_tail = _sy(sgn, Y_TAIL)
        y_nsp = _sy(sgn, Y_NSP)
        y_eqs = _sy(sgn, Y_EQ_S)

        # 1. Sources to power rails
        _src_to_rail(c, c0, sgn, False, n_s_xs, p_s_pts)
        _src_to_rail(c, c0, sgn, True, n_s_xs, p_s_pts)
        _src_to_rail(c, c1, sgn, True, n_s_xs, p_s_pts)
        _src_to_rail(c, c2, sgn, True, n_s_xs, p_s_pts)
        for col in (c4, c5, c6, c7):
            _src_to_rail(c, col, sgn, False, n_s_xs, p_s_pts)
            _src_to_rail(c, col, sgn, True, n_s_xs, p_s_pts)

        # 2. Internal tail node: c0(Xtail).D -> c1(Xdp).S on M1 at +-Y_TAIL
        in_c0n, in_c1n = _inf(c0, sgn, False), _inf(c1, sgn, False)
        tail_pts = [grid(c0["cx"] + dx) for dx in in_c0n["d_xs"]] + [
            grid(c1["cx"] + sx) for sx in in_c1n["s_xs"]
        ]
        for xp in tail_pts:
            viali_pad(c, xp, y_tail)
        c.wire("metal1", [(min(tail_pts), y_tail), (max(tail_pts), y_tail)], W_M1)

        # 3. Internal n_sp / n_sn: c0(Xpm).D -> Y_T1 -> vertical M1 to +-Y_NSP -> c1.D & c2.S
        in_c0p, in_c2n = _inf(c0, sgn, True), _inf(c2, sgn, False)
        x_pm_d = grid(c0["cx"] + in_c0p["d_xs"][0])
        locali_v(c, x_pm_d, y1, _sy(sgn, in_c0p["c_y1"] + 0.06))
        viali_pad(c, x_pm_d, y1)
        c.wire("metal1", sorted([(x_pm_d, y_nsp), (x_pm_d, y1)], key=lambda p: p[1]), W_M1)
        nsp_pts = [x_pm_d] + [grid(c1["cx"] + dx) for dx in in_c1n["d_xs"]] + [
            grid(c2["cx"] + sx) for sx in in_c2n["s_xs"]
        ]
        for xp in nsp_pts[1:]:
            viali_pad(c, xp, y_nsp)
        c.wire("metal1", [(min(nsp_pts), y_nsp), (max(nsp_pts), y_nsp)], W_M1)

        # 4. Clock gates along +-Y_T2: c0 (Xtail+Xpm), c1 (Xpre), c3 (Xeq)
        xg_ck = _wire_shared_gate(c, c0, sgn, Y_T2, tap_dx=-0.520)
        c0["xg_ck"] = xg_ck
        _tie_poly_bar(c, c1, sgn, True, x_ext_l=-0.480)
        xg_pre = _tap_poly(c, c1, sgn, True, Y_T2, -0.480)
        _tie_poly_bar(c, c3, sgn, True, x_ext_l=-0.260)
        xg_eq = _tap_poly(c, c3, sgn, True, Y_T2, -0.260)
        c.wire("metal1", [(xg_ck, y2), (xg_eq, y2)], W_M1)

        # 5. Input dp/dn gate on c1 NMOS at +-Y_T0
        _tie_poly_bar(c, c1, sgn, False, x_ext_l=-0.480)
        xg_dp = _tap_poly(c, c1, sgn, False, Y_T0, -0.480)
        c1["xg_d"] = xg_dp

        # 6. Sense-amp nodes sp/sn along +-Y_T1: c1(Xpre).D, c2(Xln+Xlp).D, c3(Xeq).D -> c4.G -> c5(Xpp_s).G
        _drains_to_track(c, c1, sgn, Y_T1, do_n=False, do_p=True)
        _drains_to_track(c, c2, sgn, Y_T1, do_n=True, do_p=True)
        _drains_to_track(c, c3, sgn, Y_T1, do_n=False, do_p=True)
        xg_inv = _wire_shared_gate(c, c4, sgn, Y_T1, tap_dx=-0.260)
        c4["xg"] = xg_inv
        c.wire("metal1", [(c1["cx"], y1), (xg_inv, y1)], W_M1)

        # Drive c5 PMOS gate on +-Y_T2 from xg_inv
        c.wire("metal1", sorted([(xg_inv, y1), (xg_inv, y2)], key=lambda p: p[1]), W_M1)
        c5p_dx = -0.920 if nfop == 4 else -0.480
        _tie_poly_bar(c, c5, sgn, True, x_ext_l=c5p_dx)
        xg_c5p = _tap_poly(c, c5, sgn, True, Y_T2, c5p_dx)
        c.wire("metal1", [(xg_inv, y2), (xg_c5p, y2)], W_M1)

        # Cross-coupled latch gate on c2 at +-Y_T0
        xg_ln = _wire_shared_gate(c, c2, sgn, Y_T0, tap_dx=-0.480)
        c2["xg"] = xg_ln

        # Xeq.S tap at c3
        x_eq_s = grid(c3["cx"] + _inf(c3, sgn, True)["s_xs"][0])
        viali_pad(c, x_eq_s, y_eqs)
        c3["x_eq_s"] = x_eq_s

        # 7. Fast inverter drain sb/rb at c4.D (+-Y_T1)
        c4["xd"] = _drains_to_track(c, c4, sgn, Y_T1)

        # 8. Slave pulldown gate (rb Top / sb Bot) on c5 NMOS at +-Y_T0
        _tie_poly_bar(c, c5, sgn, False, x_ext_l=-0.480)
        c5["x_ng"] = _tap_poly(c, c5, sgn, False, Y_T0, -0.480)

        # 9. Slave output qp/qn along +-Y_T1: c5.D -> c6.D -> c7(rst).D
        xd_drv = _drains_to_track(c, c5, sgn, Y_T1)
        xd_keep = _drains_to_track(c, c6, sgn, Y_T1)
        xd_rst = _drains_to_track(c, c7, sgn, Y_T1, do_n=(sgn > 0), do_p=(sgn < 0))
        c5["xd"] = xd_drv
        c6["xd"] = xd_keep
        c7["xd"] = xd_rst
        c.wire("metal1", [(xd_drv, y1), (xd_rst, y1)], W_M1)

        # Keeper gate at c6 (+-Y_T0)
        c6["xg"] = _wire_shared_gate(c, c6, sgn, Y_T0, tap_dx=-0.260)

        # Reset gate at c7 on +-Y_T2 (keeps +-Y_T0 100% clear for attached outbuf!)
        is_p_rst = sgn < 0
        _tie_poly_bar(c, c7, sgn, is_p_rst, x_ext_l=-0.260)
        c7["xg"] = _tap_poly(c, c7, sgn, is_p_rst, Y_T2, -0.260)

        # 10. Optional attached matched output buffer (`Xout_p/n` + `Xcc_out`)
        if attach_outbuf:
            for nm in ("ob", "cc_ob"):
                _src_to_rail(c, cols[nm], sgn, False, n_s_xs, p_s_pts)
                _src_to_rail(c, cols[nm], sgn, True, n_s_xs, p_s_pts)
                cols[nm]["xd"] = _drains_to_track(c, cols[nm], sgn, Y_T1)
            cols["ob"]["xg"] = _wire_shared_gate(c, cols["ob"], sgn, Y_T0)
            cols["cc_ob"]["xg"] = _wire_shared_gate(c, cols["cc_ob"], sgn, Y_T0)
            c.wire("metal1", [(_drains_min_x(cols["ob"], sgn), y1), (cols["cc_ob"]["xd"], y1)], W_M1)

    # -------------------------------------------------------------------------
    # Inter-half M2 vertical straps & crossovers
    # -------------------------------------------------------------------------
    # A. Clock M2 vertical strap at c0["xg_ck"]
    x_ck = c0["xg_ck"]
    c.via1(x_ck, +Y_T2)
    c.via1(x_ck, -Y_T2)
    if ck_source == "ckp_m3_q1":
        c.via2(x_ck, -Y_M3_Q1)
        c.wire("metal2", [(x_ck, -Y_M3_Q1), (x_ck, +Y_T2)], W_M2)
    elif ck_source == "ck_rt_m4":
        c.via2(x_ck, -Y_M4_CKRT)
        via3_pad(c, x_ck, -Y_M4_CKRT)
        c.wire("metal2", [(x_ck, -Y_M4_CKRT), (x_ck, +Y_T2)], W_M2)
    else:
        raise ValueError(f"Unknown ck_source: {ck_source}")

    # B. Symmetric tail M2 vertical bridge at c0["cx"]
    x_tail_m2 = c0["cx"]
    c.via1(x_tail_m2, +Y_TAIL)
    c.via1(x_tail_m2, -Y_TAIL)
    c.wire("metal2", [(x_tail_m2, -Y_TAIL), (x_tail_m2, +Y_TAIL)], W_M2)

    # C. Input dp/dn M2 drop from +-in_m3_y into c1["xg_d"] (+-Y_T0)
    xg_d = c1["xg_d"]
    if not in_swapped:
        c.via1(xg_d, +Y_T0)
        c.via2(xg_d, +in_m3_y)
        c.wire("metal2", [(xg_d, +Y_T0), (xg_d, +in_m3_y)], W_M2)
        c.via1(xg_d, -Y_T0)
        c.via2(xg_d, -in_m3_y)
        c.wire("metal2", [(xg_d, -in_m3_y), (xg_d, -Y_T0)], W_M2)
        x_in_p, x_in_n = xg_d, xg_d
    else:
        # Top dp <- -in_m3_y (at xg_d), Bot dn <- +in_m3_y (at xg_d + 0.580)
        x_fb_top = xg_d
        x_fb_bot = grid(xg_d + 0.580)
        c.via1(x_fb_top, +Y_T0)
        c.via2(x_fb_top, -in_m3_y)
        c.wire("metal2", [(x_fb_top, -in_m3_y), (x_fb_top, +Y_T0)], W_M2)
        c.wire("metal1", [(xg_d, -Y_T0), (x_fb_bot, -Y_T0)], W_M1)
        c.via1(x_fb_bot, -Y_T0)
        c.via2(x_fb_bot, +in_m3_y)
        c.wire("metal2", [(x_fb_bot, -Y_T0), (x_fb_bot, +in_m3_y)], W_M2)
        x_in_p, x_in_n = x_fb_bot, x_fb_top

    # D. Cross-coupled sp/sn + Xeq.S M2 pair at c3
    x_sn_m2 = c3["x_eq_s"]
    x_sp_m2 = grid(x_sn_m2 + 0.560)
    c.via1(x_sn_m2, -Y_T1)
    # Bridge M1 notch between x_sn_m2 via1 pad and c3.Xeq drain viali pad (both on -Y_T1 sn net)
    c.wire("metal1", [(x_sn_m2, -Y_T1), (grid(c3["cx"] + _inf(c3, -1, True)["d_xs"][0]), -Y_T1)], 0.320)
    c.via1(x_sn_m2, +Y_T0)
    c.via1(x_sn_m2, +Y_EQ_S)
    c.wire("metal1", [(c2["xg"], +Y_T0), (x_sn_m2, +Y_T0)], W_M1)
    c.wire("metal2", [(x_sn_m2, -Y_T1), (x_sn_m2, +Y_EQ_S)], W_M2)
    c.via1(x_sp_m2, +Y_T1)
    c.via1(x_sp_m2, -Y_T0)
    c.via1(x_sp_m2, -Y_EQ_S)
    c.wire("metal1", [(c2["xg"], -Y_T0), (x_sp_m2, -Y_T0)], W_M1)
    c.wire("metal1", [(x_sn_m2, -Y_EQ_S), (x_sp_m2, -Y_EQ_S)], W_M1)
    c.wire("metal2", [(x_sp_m2, -Y_EQ_S), (x_sp_m2, +Y_T1)], W_M2)

    # E. Cross-coupled sb/rb M2 pair between c4 and c5
    x_sb_m2 = c4["xd"]
    x_rb_m2 = grid(x_sb_m2 + 0.560)
    c.via1(x_sb_m2, +Y_T1)
    c.via1(x_sb_m2, -Y_T0)
    c.wire("metal1", [(x_sb_m2, -Y_T0), (c5["x_ng"], -Y_T0)], W_M1)
    c.wire("metal2", [(x_sb_m2, -Y_T0), (x_sb_m2, +Y_T1)], W_M2)
    c.wire("metal1", [(x_sb_m2, -Y_T1), (x_rb_m2, -Y_T1)], W_M1)
    c.via1(x_rb_m2, -Y_T1)
    c.via1(x_rb_m2, +Y_T0)
    c.wire("metal1", [(x_rb_m2, +Y_T0), (c5["x_ng"], +Y_T0)], W_M1)
    c.wire("metal2", [(x_rb_m2, -Y_T1), (x_rb_m2, +Y_T0)], W_M2)

    # F. Cross-coupled qp/qn M2 pair at c6 (keep)
    x_qp_m2, x_qn_m2 = _wire_cc_xover(c, c6, out_m3_y=out_m3_y)

    # G. Reset clamps M2 vertical drops to +-Y_M3_RST at c7["xg"]
    x_rst_m2 = c7["xg"]
    c.via1(x_rst_m2, +Y_T2)
    c.via2(x_rst_m2, +Y_M3_RST)
    c.wire("metal2", [(x_rst_m2, +Y_T2), (x_rst_m2, +Y_M3_RST)], W_M2)
    c.via1(x_rst_m2, -Y_T2)
    c.via2(x_rst_m2, -Y_M3_RST)
    c.wire("metal2", [(x_rst_m2, -Y_M3_RST), (x_rst_m2, -Y_T2)], W_M2)

    # H. Optional attached output buffer wiring + matched East M4 pins
    x_out_pin = None
    if attach_outbuf:
        xg_ob = cols["ob"]["xg"]
        # rn (+Y_T0 at x_qn_m2) -> Xout_p.G (+Y_T0), rp (-Y_T0 at x_qp_m2) -> Xout_n.G (-Y_T0)
        c.wire("metal1", [(x_qn_m2, +Y_T0), (xg_ob, +Y_T0)], W_M1)
        c.wire("metal1", [(x_qp_m2, -Y_T0), (xg_ob, -Y_T0)], W_M1)
        _wire_cc_xover(c, cols["cc_ob"])
        x_out_pin = cols["ob"]["xd"]
        for sgn in (+1, -1):
            _place_m4_pin_bar(c, x_out_pin, sgn, Y_T1)

    return {
        "x_end": grid(max(x, c7["cx"] + c7["hw"] + 0.300)),
        "x_ck": x_ck,
        "x_in_p": x_in_p,
        "x_in_n": x_in_n,
        "x_qp": x_qp_m2,
        "x_qn": x_qn_m2,
        "x_rst": x_rst_m2,
        "x_out_pin": x_out_pin,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_ckh_buf(c: Cell, cache: PdkCache, x_l_edge: float) -> dict:
    """Block 3: Half-rate clock buffers `Xckhp` (+Y: h0n->ckh_p), `Xckhn` (-Y: h0p->ckh_n), `Xcc_ckh`."""
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x = grid(x_l_edge)
    c_buf, x = _place_sym_col(
        c, cache, x, (N_LVT, 1.200, 0.15, 2), (P_STD, 2.400, 0.15, 4), gap_l=1.250
    )
    c_cc, x = _place_sym_col(
        c, cache, x, (N_STD, 0.450, 0.20, 1), (P_STD, 1.600, 0.20, 1), gap_l=0.820
    )

    for sgn in (+1, -1):
        y1 = _sy(sgn, Y_T1)
        for col in (c_buf, c_cc):
            _src_to_rail(c, col, sgn, False, n_s_xs, p_s_pts)
            _src_to_rail(c, col, sgn, True, n_s_xs, p_s_pts)
            col["xd"] = _drains_to_track(c, col, sgn, Y_T1)
        c_buf["xg"] = _wire_shared_gate(c, c_buf, sgn, Y_T0)
        c_cc["xg"] = _wire_shared_gate(c, c_cc, sgn, Y_T0)
        c.wire("metal1", [(_drains_min_x(c_buf, sgn), y1), (c_cc["xd"], y1)], W_M1)

    # Swap h0n (-Y_M3_Q0) -> Xckhp (+Y_T0), h0p (+Y_M3_Q0) -> Xckhn (-Y_T0) cleanly left of c_buf.xg
    xg = c_buf["xg"]
    x_h0n = grid(xg - 0.580)
    x_h0p = xg
    c.wire("metal1", [(x_h0n, +Y_T0), (xg, +Y_T0)], W_M1)
    c.via1(x_h0n, +Y_T0)
    c.via2(x_h0n, -Y_M3_Q0)
    c.wire("metal2", [(x_h0n, -Y_M3_Q0), (x_h0n, +Y_T0)], W_M2)

    c.via1(x_h0p, -Y_T0)
    c.via2(x_h0p, +Y_M3_Q0)
    c.wire("metal2", [(x_h0p, -Y_T0), (x_h0p, +Y_M3_Q0)], W_M2)

    # Launch ckh_p (+Y_M3_CKH) & ckh_n (-Y_M3_CKH) via cross-coupled Xcc_ckh
    x_ckhp, x_ckhn = _wire_cc_xover(c, c_cc, out_m3_y=Y_M3_CKH)
    return {
        "x_end": grid(max(x, x_ckhp + 0.300)),
        "x_h0p_in": x_h0p,
        "x_h0n_in": x_h0n,
        "x_ckhp_out": x_ckhp,
        "x_ckhn_out": x_ckhn,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_aoi_oai_pair(
    c: Cell,
    cache: PdkCache,
    x_l_edge: float,
    *,
    wn: float,
    wp: float,
    nfn: int,
    nfp: int,
    m3_a: float,
    m3_b: float,
    m3_c: float,
    out_m3_y: float | None = None,
    gap_first: float = 0.680,
) -> dict:
    """Build 3-column differential AOI21 (+Y) / OAI21 (-Y) pair (`Xfb_p/n` or `Xsh_n/p`)."""
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x = grid(x_l_edge)

    wn_1 = grid(wn / nfn)
    wn_15 = grid(1.5 * wn / nfn)
    wp_1 = grid(wp / nfp)
    wp_075 = grid(0.75 * wp / nfp)
    wp_125 = grid(1.25 * wp / nfp)

    # Col A (gate=a), Col B (gate=b), Col C (gate=c)
    ca, x = _place_col(
        c, cache, x,
        n_top=(N_LVT, wn_1, 0.15, nfn),  p_top=(P_STD, wp_1, 0.15, nfp),
        n_bot=(N_LVT, wn_15, 0.15, nfn), p_bot=(P_STD, wp_075, 0.15, nfp),
        gap_l=gap_first,
    )
    cb, x = _place_col(
        c, cache, x,
        n_top=(N_LVT, wn_15, 0.15, nfn), p_top=(P_STD, wp_1, 0.15, nfp),
        n_bot=(N_LVT, wn_15, 0.15, nfn), p_bot=(P_STD, wp_125, 0.15, nfp),
        gap_l=0.620,
    )
    cc, x = _place_col(
        c, cache, x,
        n_top=(N_LVT, wn_15, 0.15, nfn), p_top=(P_STD, wp_1, 0.15, nfp),
        n_bot=(N_LVT, wn_15, 0.15, nfn), p_bot=(P_STD, wp_125, 0.15, nfp),
        gap_l=0.620,
    )

    # Shared gates on +-Y_T0 -> M2 up/down to m3_a, m3_b, m3_c
    gate_xs: dict[str, float] = {}
    for nm, col, m3_y in (("a", ca, m3_a), ("b", cb, m3_b), ("c", cc, m3_c)):
        for sgn in (+1, -1):
            xg = _wire_shared_gate(c, col, sgn, Y_T0)
            y0, ym3 = _sy(sgn, Y_T0), _sy(sgn, m3_y)
            c.via1(xg, y0)
            c.via2(xg, ym3)
            c.wire("metal2", sorted([(xg, y0), (xg, ym3)], key=lambda p: p[1]), W_M2)
            gate_xs[f"{nm}_{sgn}"] = xg

    # --- Top (+Y): AOI21 ---
    # Sources to rails: Xna (ca.N), Xnc (cc.N) -> VSS; Xpa (ca.P) -> VDD
    _src_to_rail(c, ca, +1, False, n_s_xs, p_s_pts)
    _src_to_rail(c, cc, +1, False, n_s_xs, p_s_pts)
    _src_to_rail(c, ca, +1, True, n_s_xs, p_s_pts)
    # NMOS internal mid: cb.N.S <-> cc.N.D on M1 at +Y_N_INT
    n_mid_pts = [grid(cb["cx"] + sx) for sx in _inf(cb, +1, False)["s_xs"]] + [
        grid(cc["cx"] + dx) for dx in _inf(cc, +1, False)["d_xs"]
    ]
    for xp in n_mid_pts:
        viali_pad(c, xp, +Y_N_INT)
    c.wire("metal1", [(min(n_mid_pts), +Y_N_INT), (max(n_mid_pts), +Y_N_INT)], W_M1)
    # PMOS internal p1: ca.P.D <-> cb.P.S <-> cc.P.S on M1 at +Y_P_INT
    p1_pts = (
        [grid(ca["cx"] + dx) for dx in _inf(ca, +1, True)["d_xs"]]
        + [grid(cb["cx"] + sx) for sx in _inf(cb, +1, True)["s_xs"]]
        + [grid(cc["cx"] + sx) for sx in _inf(cc, +1, True)["s_xs"]]
    )
    for xp in p1_pts:
        viali_pad(c, xp, +Y_P_INT)
    c.wire("metal1", [(min(p1_pts), +Y_P_INT), (max(p1_pts), +Y_P_INT)], W_M1)
    # Output y (+Y_T1): ca.N.D, cb.N.D, cb.P.D, cc.P.D
    _drains_to_track(c, ca, +1, Y_T1, do_n=True, do_p=False)
    _drains_to_track(c, cb, +1, Y_T1, do_n=True, do_p=True)
    x_yp_r = _drains_to_track(c, cc, +1, Y_T1, do_n=False, do_p=True)
    x_yp_l = _drains_min_x(ca, +1, do_n=True, do_p=False)
    c.wire("metal1", [(x_yp_l, +Y_T1), (x_yp_r, +Y_T1)], W_M1)

    # --- Bottom (-Y): OAI21 ---
    # Sources to rails: Xna (ca.N) -> VSS; Xpa (ca.P), Xpb (cb.P) -> VDD
    _src_to_rail(c, ca, -1, False, n_s_xs, p_s_pts)
    _src_to_rail(c, ca, -1, True, n_s_xs, p_s_pts)
    _src_to_rail(c, cb, -1, True, n_s_xs, p_s_pts)
    # NMOS internal n1: ca.N.D <-> cb.N.S <-> cc.N.S on M1 at -Y_N_INT
    n1_pts = (
        [grid(ca["cx"] + dx) for dx in _inf(ca, -1, False)["d_xs"]]
        + [grid(cb["cx"] + sx) for sx in _inf(cb, -1, False)["s_xs"]]
        + [grid(cc["cx"] + sx) for sx in _inf(cc, -1, False)["s_xs"]]
    )
    for xp in n1_pts:
        viali_pad(c, xp, -Y_N_INT)
    c.wire("metal1", [(min(n1_pts), -Y_N_INT), (max(n1_pts), -Y_N_INT)], W_M1)
    # PMOS internal p1: cb.P.D <-> cc.P.S on M1 at -Y_P_INT
    p1b_pts = [grid(cb["cx"] + dx) for dx in _inf(cb, -1, True)["d_xs"]] + [
        grid(cc["cx"] + sx) for sx in _inf(cc, -1, True)["s_xs"]
    ]
    for xp in p1b_pts:
        viali_pad(c, xp, -Y_P_INT)
    c.wire("metal1", [(min(p1b_pts), -Y_P_INT), (max(p1b_pts), -Y_P_INT)], W_M1)
    # Output y (-Y_T1): ca.P.D, cb.N.D, cc.N.D, cc.P.D
    _drains_to_track(c, ca, -1, Y_T1, do_n=False, do_p=True)
    _drains_to_track(c, cb, -1, Y_T1, do_n=True, do_p=False)
    x_yn_r = _drains_to_track(c, cc, -1, Y_T1, do_n=True, do_p=True)
    x_yn_l = _drains_min_x(ca, -1, do_n=False, do_p=True)
    c.wire("metal1", [(x_yn_l, -Y_T1), (x_yn_r, -Y_T1)], W_M1)

    x_out_m2 = grid(max(x_yp_r, x_yn_r) + 0.450)
    if out_m3_y is not None:
        c.wire("metal1", [(x_yp_r, +Y_T1), (x_out_m2, +Y_T1)], W_M1)
        c.via1(x_out_m2, +Y_T1)
        c.via2(x_out_m2, +out_m3_y)
        c.wire("metal2", [(x_out_m2, +Y_T1), (x_out_m2, +out_m3_y)], W_M2)
        c.wire("metal1", [(x_yn_r, -Y_T1), (x_out_m2, -Y_T1)], W_M1)
        c.via1(x_out_m2, -Y_T1)
        c.via2(x_out_m2, -out_m3_y)
        c.wire("metal2", [(x_out_m2, -out_m3_y), (x_out_m2, -Y_T1)], W_M2)

    return {
        "x_end": grid(max(x, x_out_m2 + 0.300 if out_m3_y is not None else x)),
        "x_out_p": x_yp_r,
        "x_out_n": x_yn_r,
        "x_out_m2": x_out_m2,
        "gate_xs": gate_xs,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_diff_latch(
    c: Cell,
    cache: PdkCache,
    x_l_edge: float,
    *,
    wn_tg: float,
    wp_tg: float,
    nfn_tg: int,
    nfp_tg: int,
    wn_out: float,
    wp_out: float,
    nfn_out: int,
    nfp_out: int,
    ck_sgn: int,       # +1 => NMOS=ckh_p (+Y_M3_CKH), PMOS=ckh_n (-Y_M3_CKH); -1 => swapped
    in_m3_y: float | None = None,
    out_m3_y: float | None = None,
    gap_first: float = 1.250,
) -> dict:
    """Build 5-column resettable differential TG latch (`divab_diff_latch`):
    `tg -> keep -> rst -> out -> cc`.
    """
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x = grid(x_l_edge)

    c_tg, x = _place_sym_col(
        c, cache, x,
        (N_LVT, grid(wn_tg / nfn_tg), 0.15, nfn_tg),
        (P_STD, grid(wp_tg / nfp_tg), 0.15, nfp_tg),
        gap_l=gap_first,
    )
    c_kp, x = _place_sym_col(
        c, cache, x,
        (N_STD, 0.420, 0.28, 1),
        (P_STD, 0.420, 0.28, 1),
        gap_l=0.920,  # space for x_ckb_m2 + LVT->STD clearance!
    )
    c_rst, x = _place_col(
        c, cache, x,
        n_top=(N_STD, 0.900, 0.18, 1),
        p_bot=(P_STD, 1.600, 0.18, 1),
        gap_l=0.720,
    )
    c_out, x = _place_sym_col(
        c, cache, x,
        (N_LVT, grid(wn_out / nfn_out), 0.15, nfn_out),
        (P_STD, grid(wp_out / nfp_out), 0.15, nfp_out),
        gap_l=0.800,  # STD->LVT clearance!
    )
    c_cc, x = _place_sym_col(
        c, cache, x,
        (N_LVT, 0.420, 0.15, 1),
        (P_STD, 1.760, 0.15, 1),
        gap_l=0.580,
    )

    # 1. TG input/output/clock wiring
    x_in_m2 = grid(c_tg["cx"] - 0.480)
    x_ck_m2 = grid(c_tg["cx"] - 1.080)
    x_ckb_m2 = grid(c_tg["cx"] + 0.560)

    for sgn in (+1, -1):
        y0, y1, y2 = _sy(sgn, Y_T0), _sy(sgn, Y_T1), _sy(sgn, Y_T2)
        y_sn = _sy(sgn, Y_TG_SN)
        y_sp = _sy(sgn, Y_TG_SP)

        # TG sources (dp_in / dn_in) -> joined onto vertical M2 at x_in_m2
        in_tgn, in_tgp = _inf(c_tg, sgn, False), _inf(c_tg, sgn, True)
        n_sx = grid(c_tg["cx"] + in_tgn["s_xs"][0])
        viali_pad(c, n_sx, y_sn)
        c.wire("metal1", [(min(x_in_m2, n_sx), y_sn), (max(x_in_m2, n_sx), y_sn)], W_M1)
        c.via1(x_in_m2, y_sn)

        p_sxs = [grid(c_tg["cx"] + sx) for sx in in_tgp["s_xs"]]
        for xp in p_sxs:
            viali_pad(c, xp, y_sp)
        c.wire("metal1", [(min(p_sxs + [x_in_m2]), y_sp), (max(p_sxs + [x_in_m2]), y_sp)], W_M1)
        c.via1(x_in_m2, y_sp)

        if in_m3_y is None:
            c.via1(x_in_m2, y1)
            c.wire("metal2", sorted([(x_in_m2, y_sn), (x_in_m2, y_sp)], key=lambda p: p[1]), W_M2)
        else:
            ym3 = _sy(sgn, in_m3_y)
            c.via2(x_in_m2, ym3)
            ys_m2 = sorted([y_sn, y_sp, ym3])
            c.wire("metal2", [(x_in_m2, ys_m2[0]), (x_in_m2, ys_m2[-1])], W_M2)

        # TG gates: NMOS -> x_ck_m2 at +-Y_T0, PMOS -> x_ckb_m2 at +-Y_T2
        _tie_poly_bar(c, c_tg, sgn, False, x_ext_l=-0.260)
        xg_tgn = _tap_poly(c, c_tg, sgn, False, Y_T0, -0.260)
        c.wire("metal1", [(x_ck_m2, y0), (xg_tgn, y0)], W_M1)

        _tie_poly_bar(c, c_tg, sgn, True, x_ext_r=+0.480)
        xg_tgp = _tap_poly(c, c_tg, sgn, True, Y_T2, +0.480)
        c.wire("metal1", [(xg_tgp, y2), (x_ckb_m2, y2)], W_M1)

        # TG drains -> int_p (+Y_T1) / int_n (-Y_T1) -> keep.D -> rst.D
        _src_to_rail(c, c_kp, sgn, False, n_s_xs, p_s_pts)
        _src_to_rail(c, c_kp, sgn, True, n_s_xs, p_s_pts)
        _src_to_rail(c, c_rst, sgn, False, n_s_xs, p_s_pts)
        _src_to_rail(c, c_rst, sgn, True, n_s_xs, p_s_pts)
        _drains_to_track(c, c_tg, sgn, Y_T1)
        c_kp["xd"] = _drains_to_track(c, c_kp, sgn, Y_T1)
        xd_rst = _drains_to_track(c, c_rst, sgn, Y_T1, do_n=(sgn > 0), do_p=(sgn < 0))
        c.wire("metal1", [(_drains_min_x(c_tg, sgn), y1), (xd_rst, y1)], W_M1)

        # Keep gate (+-Y_T0) and reset gate (+-Y_T2, keeps +-Y_T0 free!)
        c_kp["xg"] = _wire_shared_gate(c, c_kp, sgn, Y_T0)
        is_p_rst = sgn < 0
        _tie_poly_bar(c, c_rst, sgn, is_p_rst, x_ext_l=-0.260)
        c_rst["xg"] = _tap_poly(c, c_rst, sgn, is_p_rst, Y_T2, -0.260)

        # Output restoring inverter (`Xop` +Y takes int_n at +Y_T0; `Xon` -Y takes int_p at -Y_T0)
        for col in (c_out, c_cc):
            _src_to_rail(c, col, sgn, False, n_s_xs, p_s_pts)
            _src_to_rail(c, col, sgn, True, n_s_xs, p_s_pts)
            col["xd"] = _drains_to_track(c, col, sgn, Y_T1)
        c_out["xg"] = _wire_shared_gate(c, c_out, sgn, Y_T0)
        c_cc["xg"] = _wire_shared_gate(c, c_cc, sgn, Y_T0)
        c.wire("metal1", [(_drains_min_x(c_out, sgn), y1), (c_cc["xd"], y1)], W_M1)

    # 2. Clock vertical M2 straps on TG
    y_ck_m3 = _sy(ck_sgn, Y_M3_CKH)
    y_ckb_m3 = _sy(-ck_sgn, Y_M3_CKH)
    c.via1(x_ck_m2, +Y_T0)
    c.via1(x_ck_m2, -Y_T0)
    c.via2(x_ck_m2, y_ck_m3)
    c.wire("metal2", [(x_ck_m2, min(-Y_T0, y_ck_m3)), (x_ck_m2, max(+Y_T0, y_ck_m3))], W_M2)

    c.via1(x_ckb_m2, +Y_T2)
    c.via1(x_ckb_m2, -Y_T2)
    c.via2(x_ckb_m2, y_ckb_m3)
    c.wire("metal2", [(x_ckb_m2, min(-Y_T2, y_ckb_m3)), (x_ckb_m2, max(+Y_T2, y_ckb_m3))], W_M2)

    # 3. Keeper cross-couple (`int_n` -> +Y_T0 -> Xop.G; `int_p` -> -Y_T0 -> Xon.G)
    x_intp_m2, x_intn_m2 = _wire_cc_xover(c, c_kp)
    c.wire("metal1", [(x_intn_m2, +Y_T0), (c_out["xg"], +Y_T0)], W_M1)
    c.wire("metal1", [(x_intp_m2, -Y_T0), (c_out["xg"], -Y_T0)], W_M1)

    # 4. Reset clamp vertical M2 drops to +-Y_M3_RST
    x_rst_m2 = c_rst["xg"]
    c.via1(x_rst_m2, +Y_T2)
    c.via2(x_rst_m2, +Y_M3_RST)
    c.wire("metal2", [(x_rst_m2, +Y_T2), (x_rst_m2, +Y_M3_RST)], W_M2)
    c.via1(x_rst_m2, -Y_T2)
    c.via2(x_rst_m2, -Y_M3_RST)
    c.wire("metal2", [(x_rst_m2, -Y_M3_RST), (x_rst_m2, -Y_T2)], W_M2)

    # 5. Output `cc` cross-couple (+ optional M3 export)
    x_qp_m2, x_qn_m2 = _wire_cc_xover(c, c_cc, out_m3_y=out_m3_y)

    return {
        "x_end": grid(max(x, x_qp_m2 + 0.300)),
        "x_in": x_in_m2,
        "x_ck": x_ck_m2,
        "x_ckb": x_ckb_m2,
        "x_rst": x_rst_m2,
        "x_out_m1": c_cc["xd"],
        "x_qp": x_qp_m2,
        "x_qn": x_qn_m2,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_ms_dff(
    c: Cell,
    cache: PdkCache,
    x_l_edge: float,
    *,
    wn_tg: float,
    wp_tg: float,
    wn_m: float,
    wp_m: float,
    wn_s: float,
    wp_s: float,
    out_m3_y: float,
    gap_first: float = 1.250,
) -> dict:
    """Build rising-edge differential MS-DFF (`divab_ms_dff` = Master + Slave `divab_diff_latch`)."""
    # Master: ck=ckh_n, ckb=ckh_p (ck_sgn = -1)
    xm = build_diff_latch(
        c, cache, x_l_edge,
        wn_tg=wn_tg, wp_tg=wp_tg, nfn_tg=1, nfp_tg=2,
        wn_out=wn_m, wp_out=wp_m, nfn_out=1, nfp_out=2,
        ck_sgn=-1, in_m3_y=None, out_m3_y=None, gap_first=gap_first,
    )
    # Slave: ck=ckh_p, ckb=ckh_n (ck_sgn = +1)
    xs = build_diff_latch(
        c, cache, xm["x_end"],
        wn_tg=wn_tg, wp_tg=wp_tg, nfn_tg=1, nfp_tg=2,
        wn_out=wn_s, wp_out=wp_s, nfn_out=1, nfp_out=3,
        ck_sgn=+1, in_m3_y=None, out_m3_y=out_m3_y, gap_first=1.350,
    )
    # Connect Master outputs (mp, mn) directly into Slave inputs on +-Y_T1
    c.wire("metal1", [(xm["x_out_m1"], +Y_T1), (xs["x_in"], +Y_T1)], W_M1)
    c.wire("metal1", [(xm["x_out_m1"], -Y_T1), (xs["x_in"], -Y_T1)], W_M1)
    return {
        "x_end": xs["x_end"],
        "x_in": xm["x_in"],
        "x_out_m1": xs["x_out_m1"],
        "x_qp": xs["x_qp"],
        "x_qn": xs["x_qn"],
        "x_ck_r": max(xm["x_ck"], xm["x_ckb"], xs["x_ck"], xs["x_ckb"]),
        "n_s_xs": xm["n_s_xs"] + xs["n_s_xs"],
        "p_s_pts": xm["p_s_pts"] + xs["p_s_pts"],
    }


# ---------------------------------------------------------------------------
# Top-Level Assembly
# ---------------------------------------------------------------------------

def build_div_ab_5g_cell(cache: PdkCache) -> tuple[Cell, dict]:
    c = Cell()
    all_n_s: list[float] = []
    all_p_pts: list[tuple[int, float]] = []
    walls: list[tuple[float, float]] = []

    def _acc(blk: dict) -> dict:
        all_n_s.extend(blk["n_s_xs"])
        all_p_pts.extend(blk["p_s_pts"])
        return blk

    x_w0 = 0.500
    walls.append((x_w0, V_TAP_EDGE))

    # Block 0 & 1: Static control inverters + 3-stage diff-to-CMOS input buffer & ck_rt branch
    ctrl = _acc(build_ctrl_invs(c, cache, grid(x_w0 + V_TAP_EDGE)))
    inbuf = _acc(build_inbuf(c, cache, ctrl["x_end"]))

    # Wall 1: isolates input receiver from high-speed SAFF /2
    x_w1 = grid(inbuf["x_end"] + 0.550 + V_TAP_WALL)
    walls.append((x_w1, V_TAP_WALL))

    # Block 2 & 3: SAFF-TSPC Toggle /2 (`Xdiv2`, hardened wop=9.6 nfop=4) + half-rate clock buffers (`Xckhp/n`)
    div2 = _acc(build_saff_dff(
        c, cache, grid(x_w1 + V_TAP_WALL),
        wt=5.6, wd=3.4, wl=2.8, wlp=1.6, wpre=3.8, wmid=1.6, weq=2.4,
        wop=9.6, nfop=4, wdn=2.4, winv_n=0.55, winv_p=2.60, wkp=1.60, wkn=0.50, seed_k=0.25,
        ck_source="ckp_m3_q1", in_m3_y=Y_M3_Q0, in_swapped=True, out_m3_y=Y_M3_Q0,
        attach_outbuf=False, gap_first=0.680,
    ))
    ckh = _acc(build_ckh_buf(c, cache, div2["x_end"]))

    # Wall 2: isolates 2.0/2.5 GHz /2 domain from 1.0/1.25 GHz /4-/5 counter
    x_w2 = grid(ckh["x_end"] + 0.550 + V_TAP_WALL)
    walls.append((x_w2, V_TAP_WALL))

    # Block 4: Feedback logic (`Xfb_p` AOI21 on +Y, `Xfb_n` OAI21 on -Y)
    fb = _acc(build_aoi_oai_pair(
        c, cache, grid(x_w2 + V_TAP_WALL),
        wn=1.20, wp=4.80, nfn=1, nfp=2,
        m3_a=Y_M3_Q1, m3_b=Y_M3_Q2, m3_c=Y_M3_MODE,
        out_m3_y=None, gap_first=0.680,
    ))

    # Blocks 5, 6, 7: 3-FF synchronous /4 or /5 counter (`Xff0`, `Xff1`, `Xff2`)
    ff0 = _acc(build_ms_dff(
        c, cache, fb["x_end"],
        wn_tg=1.60, wp_tg=4.00, wn_m=1.40, wp_m=5.60, wn_s=2.40, wp_s=9.60,
        out_m3_y=Y_M3_Q0, gap_first=1.350,
    ))
    c.wire("metal1", [(fb["x_out_p"], +Y_T1), (ff0["x_in"], +Y_T1)], W_M1)
    c.wire("metal1", [(fb["x_out_n"], -Y_T1), (ff0["x_in"], -Y_T1)], W_M1)

    ff1 = _acc(build_ms_dff(
        c, cache, ff0["x_end"],
        wn_tg=1.20, wp_tg=3.00, wn_m=1.20, wp_m=5.04, wn_s=1.60, wp_s=6.72,
        out_m3_y=Y_M3_Q1, gap_first=1.350,
    ))
    c.wire("metal1", [(ff0["x_out_m1"], +Y_T1), (ff1["x_in"], +Y_T1)], W_M1)
    c.wire("metal1", [(ff0["x_out_m1"], -Y_T1), (ff1["x_in"], -Y_T1)], W_M1)

    ff2 = _acc(build_ms_dff(
        c, cache, ff1["x_end"],
        wn_tg=1.20, wp_tg=3.00, wn_m=1.20, wp_m=5.04, wn_s=1.60, wp_s=6.72,
        out_m3_y=Y_M3_Q2, gap_first=1.350,
    ))
    c.wire("metal1", [(ff1["x_out_m1"], +Y_T1), (ff2["x_in"], +Y_T1)], W_M1)
    c.wire("metal1", [(ff1["x_out_m1"], -Y_T1), (ff2["x_in"], -Y_T1)], W_M1)

    # Wall 3: isolates counter from dual-edge 50% duty shaper
    x_w3 = grid(ff2["x_end"] + 0.550 + V_TAP_WALL)
    walls.append((x_w3, V_TAP_WALL))

    # Block 8 & 9: Half-cycle delay latch (`Xdly`, ck=ckh_n, ckb=ckh_p -> ck_sgn=-1) + shaper (`Xsh_n/p`)
    dly = _acc(build_diff_latch(
        c, cache, grid(x_w3 + V_TAP_WALL),
        wn_tg=1.80, wp_tg=4.40, nfn_tg=1, nfp_tg=2,
        wn_out=2.40, wp_out=9.60, nfn_out=2, nfp_out=4,
        ck_sgn=-1, in_m3_y=Y_M3_Q0, out_m3_y=Y_M3_Q1, gap_first=1.250,
    ))
    sh = _acc(build_aoi_oai_pair(
        c, cache, dly["x_end"],
        wn=2.00, wp=8.00, nfn=2, nfp=4,
        m3_a=Y_M3_Q0, m3_b=Y_M3_Q1, m3_c=Y_M3_MODE,
        out_m3_y=Y_M3_Q2, gap_first=0.800,
    ))

    # Wall 4: isolates shaper from ultra-clean full-rate SAFF retimer + output buffer
    x_w4 = grid(sh["x_end"] + 0.550 + V_TAP_WALL)
    walls.append((x_w4, V_TAP_WALL))

    # Block 10: Full-rate SAFF retimer (`Xretime`) + matched output buffer (`Xout_p/n` + `Xcc_out`)
    retime = _acc(build_saff_dff(
        c, cache, grid(x_w4 + V_TAP_WALL),
        wt=5.2, wd=3.2, wl=2.8, wlp=1.6, wpre=3.4, wmid=1.5, weq=2.2,
        wop=4.4, wdn=2.6, winv_n=0.70, winv_p=2.80, wkp=0.65, wkn=0.55, seed_k=0.0,
        ck_source="ck_rt_m4", in_m3_y=Y_M3_Q2, in_swapped=True, out_m3_y=None,
        attach_outbuf=True, gap_first=0.680,
    ))

    x_w5 = grid(retime["x_end"] + 0.550 + V_TAP_EDGE)
    walls.append((x_w5, V_TAP_EDGE))

    # -------------------------------------------------------------------------
    # Global M3 Signal Buses & Shielded M4 `ck_rt` Spine
    # -------------------------------------------------------------------------
    # 1. Local ckp (-Y_M3_Q1): Xin.Xcc3 -> Xdiv2.ck
    c.wire("metal3", [(inbuf["x_ckp_launch"], -Y_M3_Q1), (div2["x_ck"], -Y_M3_Q1)], W_M3_CK)

    # 2. Local h0p / h0n (+-Y_M3_Q0): Xdiv2 self-toggle -> Xckhp/n
    c.wire("metal3", [(min(div2["x_in_p"], div2["x_qp"]), +Y_M3_Q0), (ckh["x_h0p_in"], +Y_M3_Q0)], W_M3)
    c.wire("metal3", [(min(div2["x_in_n"], div2["x_qn"]), -Y_M3_Q0), (ckh["x_h0n_in"], -Y_M3_Q0)], W_M3)

    # 3. Matched half-rate clocks ckh_p / ckh_n (+-Y_M3_CKH): Xckh -> Xff0, Xff1, Xff2, Xdly
    x_ckh_end = max(dly["x_ck"], dly["x_ckb"])
    c.wire("metal3", [(ckh["x_ckhp_out"], +Y_M3_CKH), (x_ckh_end, +Y_M3_CKH)], W_M3_CK)
    c.wire("metal3", [(ckh["x_ckhn_out"], -Y_M3_CKH), (x_ckh_end, -Y_M3_CKH)], W_M3_CK)

    # 4. Counter & shaper buses:
    #    q0p/q0n (+-Y_M3_Q0): Xff0 -> Xdly -> Xsh
    c.wire("metal3", [(ff0["x_qp"], +Y_M3_Q0), (sh["gate_xs"]["a_1"], +Y_M3_Q0)], W_M3)
    c.wire("metal3", [(ff0["x_qn"], -Y_M3_Q0), (sh["gate_xs"]["a_-1"], -Y_M3_Q0)], W_M3)

    #    q1p/q1n (+-Y_M3_Q1): Xfb <- Xff1
    c.wire("metal3", [(fb["gate_xs"]["a_1"], +Y_M3_Q1), (ff1["x_qp"], +Y_M3_Q1)], W_M3)
    c.wire("metal3", [(fb["gate_xs"]["a_-1"], -Y_M3_Q1), (ff1["x_qn"], -Y_M3_Q1)], W_M3)

    #    q0dp/q0dn (right segment of +-Y_M3_Q1): Xdly -> Xsh (clear of q1p/q1n by >14 um!)
    c.wire("metal3", [(dly["x_qp"], +Y_M3_Q1), (sh["gate_xs"]["b_1"], +Y_M3_Q1)], W_M3)
    c.wire("metal3", [(dly["x_qn"], -Y_M3_Q1), (sh["gate_xs"]["b_-1"], -Y_M3_Q1)], W_M3)

    #    q2p/q2n (+-Y_M3_Q2): Xfb <- Xff2
    c.wire("metal3", [(fb["gate_xs"]["b_1"], +Y_M3_Q2), (ff2["x_qp"], +Y_M3_Q2)], W_M3)
    c.wire("metal3", [(fb["gate_xs"]["b_-1"], -Y_M3_Q2), (ff2["x_qn"], -Y_M3_Q2)], W_M3)

    #    qsh_n/qsh_p (right segment of +-Y_M3_Q2): Xsh -> Xretime (clear of q2p/q2n by >12 um!)
    c.wire("metal3", [(sh["x_out_m2"], +Y_M3_Q2), (retime["x_in_p"], +Y_M3_Q2)], W_M3)
    c.wire("metal3", [(sh["x_out_m2"], -Y_M3_Q2), (retime["x_in_n"], -Y_M3_Q2)], W_M3)

    # 5. Static DC shield rails: mode_5g / mode_5g_b (+-Y_M3_MODE) & rst / rst_n (+-Y_M3_RST)
    c.wire("metal3", [(ctrl["x_mode_start"], +Y_M3_MODE), (sh["gate_xs"]["c_1"], +Y_M3_MODE)], W_M3)
    c.wire("metal3", [(ctrl["x_modeb_start"], -Y_M3_MODE), (sh["gate_xs"]["c_-1"], -Y_M3_MODE)], W_M3)
    c.wire("metal3", [(ctrl["x_rst_start"], +Y_M3_RST), (retime["x_rst"], +Y_M3_RST)], W_M3)
    c.wire("metal3", [(ctrl["x_rstn_start"], -Y_M3_RST), (retime["x_rst"], -Y_M3_RST)], W_M3)

    # 6. Shielded low-R M4 retimer clock spine `ck_rt` (-Y_M4_CKRT = -9.860 um)
    c.wire("metal4", [(inbuf["x_ckrt_launch"], -Y_M4_CKRT), (retime["x_ck"], -Y_M4_CKRT)], W_M4)

    # -------------------------------------------------------------------------
    # Wells, Tap Walls, and M1-M4 Power Grid (0.0% M5)
    # -------------------------------------------------------------------------
    x_rail_l = grid(x_w0 - V_TAP_EDGE - 0.140)
    x_rail_r = grid(x_w5 + V_TAP_EDGE + 0.140)
    x_wl = grid(x_rail_l - 0.220)
    x_wr = grid(x_rail_r + 0.250)
    c.rect("pwell", x_wl, -Y_T1, x_wr, +Y_T1)
    c.rect("nwell", x_wl, +Y_T1, x_wr, grid(Y_VDD + 0.450))
    c.rect("nwell", x_wl, grid(-Y_VDD - 0.450), x_wr, -Y_T1)

    for xw, hw in walls:
        _draw_np_wall_band(c, xw, Y_VSS, +Y_T1, +Y_VDD, hw)
        _draw_np_wall_band(c, xw, Y_VSS, -Y_T1, -Y_VDD, hw)

    # Center VSS rail (psubdiff + locali + M1 + M4 spine)
    _draw_tap_h(c, "psubdiff", x_rail_l, x_rail_r, Y_VSS, H_TAP_VSS)
    c.wire("metal1", [(x_rail_l, Y_VSS), (x_rail_r, Y_VSS)], W_PWR_M1)
    c.wire("metal4", [(x_w0, Y_VSS), (x_rail_r, Y_VSS)], W_PWR_M4)
    vss_viali_xs = _place_filtered_viali(c, [*all_n_s, *(xw for xw, _ in walls)], Y_VSS, min_pitch=0.380)
    x_cur = grid(x_rail_l + 0.450)
    while x_cur <= x_rail_r - 0.450:
        if all(abs(x_cur - ex) >= 0.420 for ex in vss_viali_xs):
            c.pad("viali", x_cur, Y_VSS, 0.17)
            c.pad("metal1", x_cur, Y_VSS, 0.32)
            vss_viali_xs.append(x_cur)
        x_cur = grid(x_cur + 0.450)
    for xw, _ in walls:
        c.via1(xw, Y_VSS)
        c.via2(xw, Y_VSS)
        via3_pad(c, xw, Y_VSS)
    m2_y0_spans = [(x1, x2) for x1, y1, x2, y2 in c.rects.get("metal2", []) if y1 < 0.450 and y2 > -0.450]
    vss_via_xs = [xw for xw, _ in walls]
    x_cur = grid(x_w0 + 1.200)
    while x_cur <= x_rail_r - 0.800:
        m2_free = all(x_cur + 0.550 <= a or x_cur - 0.550 >= b for a, b in m2_y0_spans)
        if m2_free and all(abs(x_cur - vx) >= 1.400 for vx in vss_via_xs):
            c.via1(x_cur, Y_VSS)
            c.via2(x_cur, Y_VSS)
            via3_pad(c, x_cur, Y_VSS)
            vss_via_xs.append(x_cur)
        x_cur = grid(x_cur + 0.250)

    # Top and bottom VDD rails + external-left M4 bridge (clear of M4 VSS starting at x_w0!)
    x_vdd_bridge = grid(x_w0 - 1.100)
    for sgn in (+1, -1):
        yv = grid(sgn * Y_VDD)
        _draw_tap_h(c, "nsubdiff", x_rail_l, x_rail_r, yv, H_TAP_VDD)
        c.rect("locali", x_rail_l, grid(yv - 0.145), x_rail_r, grid(yv + 0.145))
        c.wire("metal1", [(x_rail_l, yv), (x_rail_r, yv)], W_PWR_M1)
        c.wire("metal2", [(x_rail_l, yv), (x_rail_r, yv)], W_PWR_M2)
        c.wire("metal3", [(x_rail_l, yv), (x_rail_r, yv)], W_PWR_M3)
        c.wire("metal4", [(x_vdd_bridge, yv), (x_rail_r, yv)], 1.000)
        vdd_viali_xs = _place_filtered_viali(
            c, [*(x for s, x in all_p_pts if s == sgn), *(xw for xw, _ in walls)], yv, min_pitch=0.380
        )
        x_cur = grid(x_rail_l + 0.420)
        while x_cur <= x_rail_r - 0.420:
            if all(abs(x_cur - ex) >= 0.400 for ex in vdd_viali_xs):
                c.pad("viali", x_cur, yv, 0.17)
                c.pad("metal1", x_cur, yv, 0.32)
                vdd_viali_xs.append(x_cur)
            x_cur = grid(x_cur + 0.420)
        vdd_via_xs = [xw for xw, _ in walls]
        for xw, _ in walls:
            c.via1(xw, yv)
            c.via2(xw, yv)
            via3_pad(c, xw, yv)
        x_cur = grid(x_w0 + 1.000)
        while x_cur <= x_rail_r - 0.600:
            if all(abs(x_cur - vx) >= 1.200 for vx in vdd_via_xs):
                c.via1(x_cur, yv)
                c.via2(x_cur, yv)
                via3_pad(c, x_cur, yv)
                vdd_via_xs.append(x_cur)
            x_cur = grid(x_cur + 0.450)

    c.wire("metal4", [(x_vdd_bridge, -Y_VDD), (x_vdd_bridge, +Y_VDD)], W_PWR_M4)

    # -------------------------------------------------------------------------
    # Export All 8 Exact Ports on M4
    # -------------------------------------------------------------------------
    c.port("clkp",    "metal4", inbuf["x_clkin"],      +Y_M4_PORT)
    c.port("clkn",    "metal4", inbuf["x_clkin"],      -Y_M4_PORT)
    c.port("mode_5g", "metal4", ctrl["x_mode_port"],   +Y_M3_MODE)
    c.port("rst_n",   "metal4", ctrl["x_rstn_port"],   -Y_M3_RST)
    c.port("fb250",   "metal4", retime["x_out_pin"],   +Y_M4_PORT)
    c.port("fb250_b", "metal4", retime["x_out_pin"],   -Y_M4_PORT)
    c.port("vdd",     "metal4", x_w0,                  +Y_VDD)
    c.port("vss",     "metal4", x_w0,                  Y_VSS)

    meta = {
        "walls_x": [xw for xw, _ in walls],
        "ports_xy": {
            "clkp": [inbuf["x_clkin"], +Y_M4_PORT],
            "clkn": [inbuf["x_clkin"], -Y_M4_PORT],
            "mode_5g": [ctrl["x_mode_port"], +Y_M3_MODE],
            "rst_n": [ctrl["x_rstn_port"], -Y_M3_RST],
            "fb250": [retime["x_out_pin"], +Y_M4_PORT],
            "fb250_b": [retime["x_out_pin"], -Y_M4_PORT],
            "vdd": [x_w0, +Y_VDD],
            "vss": [x_w0, Y_VSS],
        },
    }
    return c, meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    ap.add_argument("--install-dir", type=Path, default=None)
    ap.add_argument("--review", action="store_true", help="Run independent verification/layout/review_cell.py --rc")
    args = ap.parse_args()

    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(out / "_pdk_cache")

    build_dir = out / "build"
    build_dir.mkdir(parents=True, exist_ok=True)

    c, meta = build_div_ab_5g_cell(cache)
    mag_path = build_dir / f"{CELL_NAME}.mag"
    ref_path = build_dir / f"{CELL_NAME}_ref.spice"
    c.write(mag_path)
    ports = generate_div_ab_ref_spice(ref_path, CELL_NAME)
    assert ports == EXPECTED_PORTS, f"Port mismatch: {ports} != {EXPECTED_PORTS}"

    rep = rlc.verify_flat_cell(build_dir, CELL_NAME, mag_path, ref_path, EXPECTED_PORTS, timeout_s=180)
    rep["floorplan"] = meta

    lvs_spice = (build_dir / f"{CELL_NAME}_lvs.spice").read_text()
    ref_spice = ref_path.read_text()
    rep["extracted_models"] = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    rep["reference_models"] = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", ref_spice, re.M)))

    png_path = build_dir / f"{CELL_NAME}.png"
    rlc.render_png_plot_mag(mag_path, png_path)

    print(
        f"{CELL_NAME} | DRC={rep['drc_total']} | LVS={rep['lvs_match']} | "
        f"PROP_ERR={rep['lvs_property_errors']} | DISC={rep['lvs_disconnected']} | "
        f"PORTS={len(rep['exported_ports'])}/{rep['expected_port_count']} | "
        f"FLOAT_POLY={rep['floating_poly']} | M5={rep['metal_shares']['share_pct']['M5']}% | "
        f"SIZE={rep['width_um']}x{rep['height_um']} um ({rep['area_um2']} um2)",
        flush=True,
    )
    if rep["drc_rules"]:
        print("DRC_RULES:", flush=True)
        for r in rep["drc_rules"]:
            print(" ", r, flush=True)

    passed = (
        rep["drc_total"] == 0
        and rep["lvs_match"]
        and not rep["lvs_property_errors"]
        and not rep["lvs_disconnected"]
        and rep["port_count_match"]
        and rep["floating_poly"] == 0
        and rep["metal_shares"]["share_pct"]["M5"] == 0.0
    )

    if args.review and passed:
        review_dir = out / "review"
        rev = rlc.run_independent_review(mag_path, ref_path, review_dir, timeout_s=180)
        rep["independent_review"] = rev
        print(
            f"REVIEW_CELL: physical_passed={rev['physical_passed']} | "
            f"ports={len(rev['ports'])} | rc_resistors={rev.get('rc', {}).get('resistor_count')}",
            flush=True,
        )

    (build_dir / "summary.json").write_text(json.dumps(rep, indent=2) + "\n")

    if args.install_dir and passed:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        src_dir = (out / "review") if (args.review and (out / "review").exists()) else build_dir
        shutil.copy2(mag_path, inst / f"{CELL_NAME}.mag")
        shutil.copy2(png_path, inst / f"{CELL_NAME}.png")
        shutil.copy2(ref_path, inst / f"{CELL_NAME}_ref.spice")
        shutil.copy2(src_dir / f"{CELL_NAME}_lvs.spice", inst / f"{CELL_NAME}_lvs.spice")
        shutil.copy2(src_dir / f"{CELL_NAME}_pex.spice", inst / f"{CELL_NAME}_pex.spice")
        (inst / "summary.json").write_text(json.dumps(rep, indent=2) + "\n")
        print(f"INSTALLED clean signed-off artifacts to {inst}", flush=True)

    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
