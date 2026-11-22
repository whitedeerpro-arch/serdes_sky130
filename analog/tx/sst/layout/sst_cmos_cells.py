#!/usr/bin/env python3
"""Standard-row SKY130A CMOS cell library for TX v4 Zero-CML SST.

Implements exact schematic subcircuits from `tx_sst_driver.spice` and `tx_sst_serializer16.spice`:
  - `sst_inv`      (LVT NMOS + std PMOS)
  - `sst_nand2`    (2-col LVT NMOS series + std PMOS parallel, any nfn/nfp)
  - `sst_nor2`     (2-col LVT NMOS parallel + std PMOS series, any nfn/nfp)
  - `sst_tgate`    (1-col LVT NMOS + std PMOS pass gate, independent p/pb gates)
  - `sst_cc_align` (2-col cross-coupled inverter pair)
  - `sst_mux2`     (Xta + Xtb + Xi1 + Xi2)
  - `sst_dff_r`    (rising-edge static CMOS MS-DFF with async active-low rst_n)

All cells sit on a uniform `RowSpec` (VSS at y=0, NMOS bottom, 5-track M1 channel,
PMOS top, VDD at y=h_row). Adjacent rows can be mirrored in Y (`mirror_y=True`)
to share continuous VDD/VDD and VSS/VSS rails and continuous N-wells.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sst_layout_common as slc  # noqa: E402
from sst_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_LVT,
    P_STD,
    W_M1,
    W_M2,
    grid,
    poly_cont_pad,
    viali_pad,
    locali_v,
    locali_h,
    draw_tap_h,
)


@dataclass(frozen=True)
class RowSpec:
    """Vertical geometry of a single standard CMOS row (origin at VSS y=0)."""
    y_vss: float
    y_n_top: float
    y_p_bot: float
    y_vdd: float
    nwell_y1: float
    nwell_y2: float

    @property
    def y_npoly(self) -> tuple[float, float]:
        return (grid(self.y_n_top + 0.140), grid(self.y_n_top + 0.290))

    @property
    def y_ppoly(self) -> tuple[float, float]:
        return (grid(self.y_p_bot - 0.290), grid(self.y_p_bot - 0.140))

    @property
    def y_tracks(self) -> tuple[float, float, float, float, float]:
        # 5 M1 tracks spaced 0.500 um apart inside a 3.000 um channel
        return tuple(grid(self.y_n_top + 0.500 + 0.500 * i) for i in range(5))  # type: ignore

    @property
    def height(self) -> float:
        return self.y_vdd


# Serializer row: max w_f_n <= 2.30, max w_f_p <= 3.00 -> H = 9.500 um (all serializer tgates nf=1!)
ROW_SER = RowSpec(
    y_vss=0.000,
    y_n_top=2.750,
    y_p_bot=5.750,
    y_vdd=9.500,
    nwell_y1=5.250,
    nwell_y2=10.100,
)

# Driver high-speed CMOS row: max w_f_n <= 3.00, max w_f_p <= 3.00 -> H = 10.200 um
ROW_DRV = RowSpec(
    y_vss=0.000,
    y_n_top=3.500,
    y_p_bot=6.500,
    y_vdd=10.200,
    nwell_y1=6.000,
    nwell_y2=10.800,
)


def choose_fingers(w_total: float, max_wf: float, min_nf: int = 1) -> tuple[float, int]:
    """Pick finger count nf >= min_nf so w_f = w_total / nf <= max_wf AND exact on 5 nm grid."""
    for nf in range(max(1, min_nf), 17):
        wf = w_total / nf
        if wf <= max_wf + 1e-9 and abs(wf - grid(wf)) < 1e-6:
            return grid(wf), nf
    # Fallback: pick smallest nf with wf <= max_wf
    nf = max(min_nf, int((w_total / max_wf) + 0.9999))
    return grid(w_total / nf), nf


def _place_col(
    c: Cell,
    cache: PdkCache,
    row: RowSpec,
    x_edge: float,
    wn: float,
    wp: float,
    nfn: int,
    nfp: int,
    gap_l: float = 0.560,
) -> tuple[dict, float]:
    """Place one aligned NMOS(LVT)+PMOS(STD) column inside `row` starting right of `x_edge`."""
    wfn = grid(wn / nfn)
    wfp = grid(wp / nfp)
    dy_n = grid(row.y_n_top - wfn / 2.0)
    dy_p = grid(row.y_p_bot + wfp / 2.0)
    mn, inf_n = cache.build_mos(N_LVT, wfn, 0.15, nfn, dy_n, False)
    mp, inf_p = cache.build_mos(P_STD, wfp, 0.15, nfp, dy_p, True)
    hw = max(inf_n["hw_diff"], inf_p["hw_diff"])
    cx = grid(x_edge + gap_l + hw)
    x_next = grid(cx + hw)
    c.include(mn, dx=cx)
    c.include(mp, dx=cx)
    return {"cx": cx, "hw": hw, "inf_n": inf_n, "inf_p": inf_p}, x_next


def _tie_poly(c: Cell, row: RowSpec, cx: float, g_xs: list[float], is_p: bool, tap_x: float | None = None) -> None:
    ya, yb = row.y_ppoly if is_p else row.y_npoly
    # Widen horizontal poly tie strap into channel (0.32 um on ROW_DRV, 0.24 um on ROW_SER) to slash gate series R
    w_bar = 0.320 if row.height >= 10.0 else 0.240
    if is_p:
        ya = grid(yb - w_bar)
    else:
        yb = grid(ya + w_bar)
    y_edge = row.y_p_bot if is_p else row.y_n_top
    for gx in g_xs:
        x = grid(cx + gx)
        y1, y2 = sorted((y_edge, ya if not is_p else yb))
        c.rect("poly", grid(x - 0.075), y1, grid(x + 0.075), y2)
    xs = [grid(cx + g) for g in g_xs]
    if tap_x is not None:
        xs.append(grid(tap_x))
    if len(xs) > 1 or tap_x is not None:
        c.rect("poly", grid(min(xs) - 0.075), ya, grid(max(xs) + 0.075), yb)


def _tap_shared_gate(c: Cell, row: RowSpec, col: dict, y_trk: float, tap_dx: float) -> float:
    """Tie N & P poly gates via dual near-edge polyconts bridged by low-R vertical M1.

    Eliminates the 2.7 um vertical poly run across the 3 um channel (~480 ohm -> ~1.5 ohm!).
    On high-speed ROW_DRV multi-finger devices (nf >= 3), adds a second mid-column polycont + M1
    strap strictly left of the drain vertical M1 bar to slash horizontal poly bar resistance!
    """
    cx = col["cx"]
    xg = grid(cx + tap_dx)
    _tie_poly(c, row, cx, col["inf_n"]["g_xs"], False, tap_x=xg)
    _tie_poly(c, row, cx, col["inf_p"]["g_xs"], True, tap_x=xg)
    y_ntap = row.y_tracks[0]
    y_ptap = row.y_tracks[4]
    # Short vertical poly stubs from n/p tie bars to near-edge polyconts only
    c.rect("poly", grid(xg - 0.135), row.y_npoly[0], grid(xg + 0.135), grid(y_ntap + 0.170))
    c.rect("poly", grid(xg - 0.135), grid(y_ptap - 0.170), grid(xg + 0.135), row.y_ppoly[1])
    poly_cont_pad(c, xg, y_ntap)
    viali_pad(c, xg, y_ntap)
    poly_cont_pad(c, xg, y_ptap)
    viali_pad(c, xg, y_ptap)
    # Low-R M1 vertical gate bridge spanning all 5 tracks (0.125 ohm/sq vs 48.2 ohm/sq poly!)
    c.wire("metal1", [(xg, y_ntap), (xg, y_ptap)], 0.220)
    # Multi-finger M1 gate shunting on ROW_DRV: tap middle finger strictly clear (>=0.56 um) of BOTH N and P right drain bars!
    if row.height >= 10.0:
        x_join_approx = grid(cx + min(max(col["inf_n"]["d_xs"]), max(col["inf_p"]["d_xs"])))
        for is_p, y_t, g_xs in ((False, y_ntap, col["inf_n"]["g_xs"]), (True, y_ptap, col["inf_p"]["g_xs"])):
            if len(g_xs) >= 3:
                # Choose finger closest to center that stays >= 0.56 um left of x_join_approx and >= 0.44 um right of xg
                cands = [grid(cx + g) for g in g_xs if grid(cx + g) <= x_join_approx - 0.560 and grid(cx + g) >= xg + 0.440]
                if cands:
                    xm = cands[-1]
                    if is_p:
                        c.rect("poly", grid(xm - 0.135), grid(y_t - 0.170), grid(xm + 0.135), row.y_ppoly[1])
                    else:
                        c.rect("poly", grid(xm - 0.135), row.y_npoly[0], grid(xm + 0.135), grid(y_t + 0.170))
                    poly_cont_pad(c, xm, y_t)
                    viali_pad(c, xm, y_t)
                    c.wire("metal1", [(xg, y_t), (xm, y_t)], 0.220)
    return xg


def _tap_single_gate(c: Cell, row: RowSpec, col: dict, is_p: bool, y_trk: float, tap_dx: float) -> float:
    """Tie only N or only P poly gates and place polycont+viali at (cx + tap_dx, y_trk).

    For high-speed driver rows (ROW_DRV), uses dual parallel polyconts + dual viali to halve contact R!
    """
    cx = col["cx"]
    xg = grid(cx + tap_dx)
    inf = col["inf_p"] if is_p else col["inf_n"]
    _tie_poly(c, row, cx, inf["g_xs"], is_p, tap_x=xg)
    ya, yb = row.y_ppoly if is_p else row.y_npoly
    if row.height >= 10.0:
        # Dual parallel polyconts spaced 0.360 um apart vertically (clear of y2 = y_trk +- 1.00 um!)
        # Single continuous 0.18 um locali rect eliminates any li.3 notch between the two pads.
        y_2 = grid(y_trk - 0.360 if is_p else y_trk + 0.360)
        ys = sorted((grid(y_trk), y_2, ya, yb))
        c.rect("poly", grid(xg - 0.135), grid(ys[0] - 0.170 if ys[0] in (grid(y_trk), y_2) else ys[0]),
               grid(xg + 0.135), grid(ys[-1] + 0.170 if ys[-1] in (grid(y_trk), y_2) else ys[-1]))
        poly_cont_pad(c, xg, y_trk)
        poly_cont_pad(c, xg, y_2)
        c.rect("locali", grid(xg - 0.090), grid(min(y_trk, y_2) - 0.170),
               grid(xg + 0.090), grid(max(y_trk, y_2) + 0.170))
        viali_pad(c, xg, y_trk)
        viali_pad(c, xg, y_2)
        c.wire("metal1", [(xg, min(y_trk, y_2)), (xg, max(y_trk, y_2))], 0.290)
    else:
        ys = sorted((grid(y_trk), ya, yb))
        c.rect("poly", grid(xg - 0.135), ys[0], grid(xg + 0.135), ys[-1])
        poly_cont_pad(c, xg, y_trk)
        viali_pad(c, xg, y_trk)
    return xg


def _shunt_sd_bar_m1(
    c: Cell, cx: float, xs_local: list[float], y_anchor: float, y_limit: float, toward_pos: bool,
) -> None:
    """Add 0.48 um-pitched viali + 0.24 um vertical M1 along wide ROW_DRV diffusion bars to slash locali/pdc R (6x)."""
    step = 0.480 if toward_pos else -0.480
    ys: list[float] = []
    yy = grid(y_anchor + step)
    while (yy <= y_limit) if toward_pos else (yy >= y_limit):
        ys.append(grid(yy))
        yy = grid(yy + step)
    if not ys:
        return
    y_lo = grid(min(y_anchor, ys[-1]) - 0.145)
    y_hi = grid(max(y_anchor, ys[-1]) + 0.145)
    for lx in xs_local:
        x = grid(cx + lx)
        for yv in ys:
            c.pad("viali", x, yv, 0.17)
        c.rect("metal1", grid(x - 0.120), y_lo, grid(x + 0.120), y_hi)


def _tie_sd_to_rail(
    c: Cell, row: RowSpec, col: dict, is_p: bool, xs_local: list[float], shunt_m1: bool = False
) -> None:
    cx = col["cx"]
    inf = col["inf_p"] if is_p else col["inf_n"]
    y_rail = row.y_vdd if is_p else row.y_vss
    y_end = inf["c_y2"] - 0.060 if is_p else inf["c_y1"] + 0.060
    use_m1 = shunt_m1 and row.height >= 10.0 and inf["w_f"] >= 1.80
    y_shunt = grid(inf["c_y2"] - 0.160) if is_p else grid(inf["c_y1"] + 0.160)
    for sx in xs_local:
        x = grid(cx + sx)
        locali_v(c, x, y_rail, y_end)
        if use_m1:
            viali_pad(c, x, y_shunt)
            c.wire("metal1", [(x, min(y_rail, y_shunt)), (x, max(y_rail, y_shunt))], 0.220)
    if use_m1:
        y_opp = grid(max(inf["c_y1"] + 0.160, row.y_p_bot + 0.240)) if is_p else grid(min(inf["c_y2"] - 0.160, row.y_n_top - 0.240))
        y_lim = grid(y_opp + 0.580) if is_p else grid(y_opp - 0.580)
        _shunt_sd_bar_m1(c, cx, xs_local, y_shunt, y_lim, toward_pos=(not is_p))


def _strap_sd_m1(c: Cell, cx: float, xs_local: list[float], y_bar: float, inf: dict, is_p: bool) -> float:
    """Drop/lift a set of diffusion legs onto an M1 horizontal strap at `y_bar` inside the diff band."""
    y_bar = grid(y_bar)
    xs = [grid(cx + x) for x in xs_local]
    for x in xs:
        if y_bar < inf["c_y1"]:
            locali_v(c, x, y_bar, inf["c_y1"] + 0.060)
        elif y_bar > inf["c_y2"]:
            locali_v(c, x, inf["c_y2"] - 0.060, y_bar)
        viali_pad(c, x, y_bar)
    if len(xs) > 1:
        c.wire("metal1", [(min(xs), y_bar), (max(xs), y_bar)], W_M1)
    return xs[-1]


def _default_gate_dx(col: dict) -> float:
    """Return a clean left-shifted gate tap offset avoiding central/right drain drops."""
    return grid(-col["hw"] - 0.160)


def _connect_col_drains_m1(c: Cell, row: RowSpec, col: dict, y_out: float, n_xs: list[float] | None = None, p_xs: list[float] | None = None) -> float:
    """Join N drains and P drains to an M1 pin at `(x_out, y_out)`."""
    cx = col["cx"]
    in_n, in_p = col["inf_n"], col["inf_p"]
    n_list = n_xs if n_xs is not None else in_n["d_xs"]
    p_list = p_xs if p_xs is not None else in_p["d_xs"]

    # Choose clean M1 drop X on the right side of the column (strictly clear of left-shifted gate tap!)
    y_nb = grid(min(in_n["c_y2"] - 0.160, row.y_n_top - 0.240))
    y_pb = grid(max(in_p["c_y1"] + 0.160, row.y_p_bot + 0.240))

    xn_pts = [grid(cx + x) for x in n_list]
    xp_pts = [grid(cx + x) for x in p_list]
    x_join = grid(max(max(xn_pts), max(xp_pts)))

    for x in xn_pts:
        viali_pad(c, x, y_nb)
    if len(xn_pts) > 1 or xn_pts[0] != x_join:
        c.wire("metal1", [(min(xn_pts + [x_join]), y_nb), (max(xn_pts + [x_join]), y_nb)], 0.290)

    for x in xp_pts:
        viali_pad(c, x, y_pb)
    if len(xp_pts) > 1 or xp_pts[0] != x_join:
        c.wire("metal1", [(min(xp_pts + [x_join]), y_pb), (max(xp_pts + [x_join]), y_pb)], 0.290)

    if row.height >= 10.0:
        if in_n["w_f"] >= 1.80:
            y_n_opp = grid(max(in_n["c_y1"] + 0.160, 0.720))
            _shunt_sd_bar_m1(c, cx, n_list, y_nb, grid(y_n_opp + 0.580), toward_pos=False)
        if in_p["w_f"] >= 1.80:
            y_p_opp = grid(min(in_p["c_y2"] - 0.160, row.y_vdd - 0.850))
            _shunt_sd_bar_m1(c, cx, p_list, y_pb, grid(y_p_opp - 0.580), toward_pos=True)

    c.wire("metal1", [(x_join, y_nb), (x_join, y_pb)], W_M1)
    return x_join


# ---------------------------------------------------------------------------
# Public Standard CMOS Cell Builders
# ---------------------------------------------------------------------------

def place_inv(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float, wp: float, nfn: int = 1, nfp: int = 1,
    gap_l: float = 0.680, trk_g: int = 2,
) -> tuple[dict, float]:
    """Place `sst_inv`: returns pins {'a': (xg, yg), 'y': (xy, y_mid), 'x_end': ...}."""
    wfn, nfn = choose_fingers(wn, row.y_n_top - 0.45, min_nf=nfn)
    wfp, nfp = choose_fingers(wp, row.y_vdd - row.y_p_bot - 0.65, min_nf=nfp)
    col, x_next = _place_col(c, cache, row, x_edge, wfn * nfn, wfp * nfp, nfn, nfp, gap_l=gap_l)

    _tie_sd_to_rail(c, row, col, False, col["inf_n"]["s_xs"], shunt_m1=True)
    _tie_sd_to_rail(c, row, col, True,  col["inf_p"]["s_xs"], shunt_m1=True)

    yg = row.y_tracks[trk_g]
    xg = _tap_shared_gate(c, row, col, yg, tap_dx=_default_gate_dx(col))
    xy = _connect_col_drains_m1(c, row, col, row.y_tracks[2])
    # Place `y` pin at trk_g ^ 2 (or y4 if trk_g==2 -> 1.00 um clear of `a` for M3 via2 pads!)
    y_pin = row.y_tracks[4] if trk_g == 2 else row.y_tracks[2]
    return {"a": (xg, yg), "y": (xy, y_pin), "y_col_x": xy, "col": col, "x_end": x_next}, x_next


def place_nand2(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float, wp: float, nfn: int = 1, nfp: int = 1,
    gap_l: float = 0.680, trk_a: int = 1, trk_b: int = 3,
) -> tuple[dict, float]:
    """Place 2-column `sst_nand2` (`Xna` + `Xpa` left, `Xnb` + `Xpb` right)."""
    wfn, nfn = choose_fingers(wn, row.y_n_top - 0.45, min_nf=nfn)
    wfp, nfp = choose_fingers(wp, row.y_vdd - row.y_p_bot - 0.65, min_nf=nfp)
    ca, x1 = _place_col(c, cache, row, x_edge, wfn * nfn, wfp * nfp, nfn, nfp, gap_l=gap_l)
    cb, x2 = _place_col(c, cache, row, x1,     wfn * nfn, wfp * nfp, nfn, nfp, gap_l=0.680)

    # Power ties: Xnb.s -> VSS, Xpa.s & Xpb.s -> VDD (M1 shunt on parallel PMOS!)
    _tie_sd_to_rail(c, row, cb, False, cb["inf_n"]["s_xs"], shunt_m1=False)
    _tie_sd_to_rail(c, row, ca, True,  ca["inf_p"]["s_xs"], shunt_m1=True)
    _tie_sd_to_rail(c, row, cb, True,  cb["inf_p"]["s_xs"], shunt_m1=True)

    # Series NMOS `mid`: ca.n.s_xs -> cb.n.d_xs on horizontal M1 near bottom of NMOS band
    y_mid = grid(max(ca["inf_n"]["c_y1"] + 0.140, 0.720))
    _strap_sd_m1(c, ca["cx"], ca["inf_n"]["s_xs"], y_mid, ca["inf_n"], False)
    _strap_sd_m1(c, cb["cx"], cb["inf_n"]["d_xs"], y_mid, cb["inf_n"], False)
    xa_mid = grid(ca["cx"] + ca["inf_n"]["s_xs"][0])
    xb_mid = grid(cb["cx"] + cb["inf_n"]["d_xs"][-1])
    c.wire("metal1", [(xa_mid, y_mid), (xb_mid, y_mid)], W_M1)

    # Gates a (left of ca) and b (left of cb)
    ya, yb = row.y_tracks[trk_a], row.y_tracks[trk_b]
    xa = _tap_shared_gate(c, row, ca, ya, tap_dx=_default_gate_dx(ca))
    xb = _tap_shared_gate(c, row, cb, yb, tap_dx=_default_gate_dx(cb))

    # Output `y`: ca.n.d_xs + ca.p.d_xs + cb.p.d_xs joined at top of PMOS band (`y_p_join`)
    xy_a = _connect_col_drains_m1(c, row, ca, row.y_tracks[2])
    y_pb = grid(max(cb["inf_p"]["c_y1"] + 0.160, row.y_p_bot + 0.240))
    xy_b = _strap_sd_m1(c, cb["cx"], cb["inf_p"]["d_xs"], y_pb, cb["inf_p"], True)
    # Connect xy_a -> xy_b at y_pb (inside PMOS band, clear of channel tracks!)
    c.wire("metal1", [(xy_a, y_pb), (xy_b, y_pb)], W_M1)
    # Also drop xy_b down through channel to track 2 so downstream gate can tap directly!
    c.wire("metal1", [(xy_b, row.y_tracks[0]), (xy_b, y_pb)], W_M1)

    return {"a": (xa, ya), "b": (xb, yb), "y": (xy_b, row.y_tracks[2]), "y_col_x": xy_b, "x_end": x2}, x2


def place_nor2(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float, wp: float, nfn: int = 1, nfp: int = 2,
    gap_l: float = 0.680, trk_a: int = 1, trk_b: int = 3,
) -> tuple[dict, float]:
    """Place 2-column `sst_nor2` (`Xna` + `Xpa` left, `Xnb` + `Xpb` right)."""
    wfn, nfn = choose_fingers(wn, row.y_n_top - 0.45, min_nf=nfn)
    wfp, nfp = choose_fingers(wp, row.y_vdd - row.y_p_bot - 0.65, min_nf=nfp)
    ca, x1 = _place_col(c, cache, row, x_edge, wfn * nfn, wfp * nfp, nfn, nfp, gap_l=gap_l)
    cb, x2 = _place_col(c, cache, row, x1,     wfn * nfn, wfp * nfp, nfn, nfp, gap_l=0.680)

    # Power ties: Xna.s & Xnb.s -> VSS (M1 shunt on wide ROW_DRV!), Xpb.s -> VDD
    # (Xpb already has 4 parallel locali legs of 0.7 um to VDD = ~13 ohm; keep y_mid at top clear of Xpg c0..c270!)
    _tie_sd_to_rail(c, row, ca, False, ca["inf_n"]["s_xs"], shunt_m1=True)
    _tie_sd_to_rail(c, row, cb, False, cb["inf_n"]["s_xs"], shunt_m1=True)
    _tie_sd_to_rail(c, row, cb, True,  cb["inf_p"]["s_xs"], shunt_m1=False)

    # Series PMOS `mid`: ca.p.s_xs -> cb.p.d_xs on horizontal M1 near top of PMOS band (clear of M2 c0..c270!)
    y_mid = grid(min(ca["inf_p"]["c_y2"] - 0.140, row.y_vdd - 0.850))
    _strap_sd_m1(c, ca["cx"], ca["inf_p"]["s_xs"], y_mid, ca["inf_p"], True)
    _strap_sd_m1(c, cb["cx"], cb["inf_p"]["d_xs"], y_mid, cb["inf_p"], True)
    xa_mid = grid(ca["cx"] + ca["inf_p"]["s_xs"][0])
    xb_mid = grid(cb["cx"] + cb["inf_p"]["d_xs"][-1])
    c.wire("metal1", [(xa_mid, y_mid), (xb_mid, y_mid)], 0.290)

    # Gates a and b
    ya, yb = row.y_tracks[trk_a], row.y_tracks[trk_b]
    xa = _tap_shared_gate(c, row, ca, ya, tap_dx=_default_gate_dx(ca))
    xb = _tap_shared_gate(c, row, cb, yb, tap_dx=_default_gate_dx(cb))

    # Output `y`: ca.p.d_xs + ca.n.d_xs + cb.n.d_xs joined at top of NMOS band (`y_nb`)
    xy_a = _connect_col_drains_m1(c, row, ca, row.y_tracks[2])
    y_nb = grid(min(cb["inf_n"]["c_y2"] - 0.160, row.y_n_top - 0.240))
    xy_b = _strap_sd_m1(c, cb["cx"], cb["inf_n"]["d_xs"], y_nb, cb["inf_n"], False)
    c.wire("metal1", [(xy_a, y_nb), (xy_b, y_nb)], W_M1)
    c.wire("metal1", [(xy_b, y_nb), (xy_b, row.y_tracks[4])], W_M1)

    return {"a": (xa, ya), "b": (xb, yb), "y": (xy_b, row.y_tracks[2]), "y_col_x": xy_b, "x_end": x2}, x2


def place_tgate(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float, wp: float, nfn: int = 1, nfp: int = 1,
    gap_l: float = 0.840,
) -> tuple[dict, float]:
    """Place 1-column `sst_tgate` (`a` left terminal, `b` right terminal, `p` NMOS gate at trk0, `pb` PMOS gate at trk4)."""
    wfn, nfn = choose_fingers(wn, row.y_n_top - 0.45, min_nf=nfn)
    wfp, nfp = choose_fingers(wp, row.y_vdd - row.y_p_bot - 0.65, min_nf=nfp)
    col, x_next = _place_col(c, cache, row, x_edge, wfn * nfn, wfp * nfp, nfn, nfp, gap_l=gap_l)

    cx = col["cx"]
    in_n, in_p = col["inf_n"], col["inf_p"]
    y_t0, _, y_t2, _, y_t4 = row.y_tracks

    # Shift polycont taps left (-hw - 0.320) so M1 pad stays >= 0.22 um clear of terminal `a` M1 vertical bar!
    tap_dx = grid(-col["hw"] - 0.320)
    xg_p  = _tap_single_gate(c, row, col, False, y_t0, tap_dx=tap_dx)
    xg_pb = _tap_single_gate(c, row, col, True,  y_t4, tap_dx=tap_dx)

    # Terminal `a` = s_xs (strap in lower half of NMOS & upper half of PMOS, bridge vertically at s_xs[0])
    y_na = grid(max(in_n["c_y1"] + 0.160, 0.750))
    y_pa = grid(min(in_p["c_y2"] - 0.160, row.y_vdd - 0.850))
    xa_n = [grid(cx + x) for x in in_n["s_xs"]]
    xa_p = [grid(cx + x) for x in in_p["s_xs"]]
    xa_join = grid(min(min(xa_n), min(xa_p)))
    for x in xa_n:
        viali_pad(c, x, y_na)
    if len(xa_n) > 1 or xa_n[0] != xa_join:
        c.wire("metal1", [(min(xa_n + [xa_join]), y_na), (max(xa_n + [xa_join]), y_na)], 0.290)
    for x in xa_p:
        viali_pad(c, x, y_pa)
    if len(xa_p) > 1 or xa_p[0] != xa_join:
        c.wire("metal1", [(min(xa_p + [xa_join]), y_pa), (max(xa_p + [xa_join]), y_pa)], 0.290)
    c.wire("metal1", [(xa_join, y_na), (xa_join, y_pa)], W_M1)

    # Terminal `b` = d_xs (strap near channel edge of NMOS & PMOS, bridge vertically at max(d_xs))
    xb_join = _connect_col_drains_m1(c, row, col, y_t2)

    # On wide ROW_DRV transmission gates, add 0.48 um multi-viali vertical M1 shunts on `a` (s_xs)
    # (`b` = d_xs is already shunted inside `_connect_col_drains_m1`!) to slash locali/pdc R by ~6x!
    if row.height >= 10.0 and in_n["w_f"] >= 1.80:
        y_nb_top = grid(min(in_n["c_y2"] - 0.160, row.y_n_top - 0.240))
        _shunt_sd_bar_m1(c, cx, in_n["s_xs"], y_na, grid(y_nb_top - 0.580), toward_pos=True)
    if row.height >= 10.0 and in_p["w_f"] >= 1.80:
        y_pb_bot = grid(max(in_p["c_y1"] + 0.160, row.y_p_bot + 0.240))
        _shunt_sd_bar_m1(c, cx, in_p["s_xs"], y_pa, grid(y_pb_bot + 0.580), toward_pos=False)

    return {
        "a": (xa_join, y_t2),
        "b": (xb_join, y_t2),
        "p": (xg_p, y_t0),
        "pb": (xg_pb, y_t4),
        "col": col,
        "x_end": x_next,
    }, x_next


def place_cc_align(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float, wp: float, gap_l: float = 0.680,
) -> tuple[dict, float]:
    """Place `sst_cc_align` (X1: ap->an, X2: an->ap) with clean M1/M2 cross-coupling."""
    u1, x1 = place_inv(c, cache, row, x_edge, wn, wp, 1, 1, gap_l=gap_l, trk_g=1)
    u2, x2 = place_inv(c, cache, row, x1,     wn, wp, 1, 1, gap_l=0.680, trk_g=3)

    y1 = row.y_tracks[1]  # ap track
    y3 = row.y_tracks[3]  # an track
    # u1.y (an) -> u2.a (an) on M1 at y3
    c.wire("metal1", [(u1["y_col_x"], y3), u2["a"]], W_M1)
    # u2.y (ap) -> u1.a (ap) via M2 at y1 (hops cleanly over u1.y vertical M1!)
    c.via1(u2["y_col_x"], y1)
    c.via1(u1["a"][0], y1)
    c.wire("metal2", [(u1["a"][0], y1), (u2["y_col_x"], y1)], W_M2)

    return {"ap": (u1["a"][0], y1), "an": (u2["a"][0], y3), "x_end": x2}, x2


def place_mux2(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float = 1.2, wp: float = 2.4, gap_l: float = 0.720,
) -> tuple[dict, float]:
    """Place `sst_mux2` (a, b, sel, sel_b -> y): Xta + Xtb + Xi1 + Xi2."""
    ta, x1 = place_tgate(c, cache, row, x_edge, wn, wp, 1, 1, gap_l=gap_l)
    tb, x2 = place_tgate(c, cache, row, x1,     wn, wp, 1, 1, gap_l=0.760)
    i1, x3 = place_inv(c, cache, row, x2, wn, wp, 1, 1, gap_l=0.680, trk_g=2)
    i2, x4 = place_inv(c, cache, row, x3, wn, wp, 1, 1, gap_l=0.680, trk_g=2)

    y0, y1, y2, y3, y4 = row.y_tracks
    # mid: ta.b + tb.b -> i1.a on M2 at y2 (hops cleanly over tb.a M1!)
    c.via1(ta["b"][0], y2)
    c.via1(tb["b"][0], y2)
    c.via1(i1["a"][0], y2)
    c.wire("metal2", [(ta["b"][0], y2), (i1["a"][0], y2)], W_M2)

    # yb: i1.y -> i2.a on M1 at y2
    c.wire("metal1", [(i1["y_col_x"], y2), i2["a"]], W_M1)

    # sel: ta.pb (y4) -> tb.p (y0) on M2 (L-route via y4 -> tb.p.x -> y0)
    # Wait: check X of ta.pb vs tb.p -> ta.pb is left of ta, tb.p is left of tb (different X!).
    # sel_b: ta.p (y0) -> tb.pb (y4) on M2!
    # To avoid M2 crossing between sel and sel_b, route sel_b on M2 at y0 -> x_mid_l -> y4,
    # and sel on M2 at y4 -> x_mid_r -> y0? Even simpler: ta.p.x == ta.pb.x, tb.p.x == tb.pb.x!
    # Route sel (ta.pb -> tb.p): M1 right from ta.pb to (ta.b.x, y4) -> via1 -> M2 down to y0 -> wait,
    # ta.b has via1 at y2! So put sel via1 at x_sel = tb.p[0] (at y0) and x_sel_a = ta.pb[0] (at y4),
    # route sel on M2 along (ta.pb.x, y4) -> (tb.p.x, y4)? Wait, tb.pb is at (tb.p.x, y4)!
    # So shift x_drop_sel = grid(tb.p[0] - 0.500) -> NO crossing:
    #   sel_b: (ta.p.x, y0) -> M2 east to (x_drop_sb, y0) -> M2 north to y4 -> M1 east to (tb.pb.x, y4)
    #   Wait: let's just put sel on y3 (M2 horizontal) and sel_b on y1 (M2 horizontal)! ZERO crossings!
    #   Let's check:
    #     ta.p (sel_b) is at (ta.p.x, y0): M1 north to y1 -> via1 -> M2 east to (tb.pb.x, y1) -> wait,
    #     tb.p (sel) is at (tb.p.x, y0)! So tb.pb is at (tb.pb.x, y4)!
    #     In M1: ta.p.x -> y0 to y1 (doesn't touch ta.pb at y4!).
    #     In M1: tb.pb.x -> y4 to y3 (doesn't touch tb.p at y0!).
    #     Wait: we just need sel (ta.pb & tb.p) and sel_b (ta.p & tb.pb) connected cleanly:
    #     Use M1 at ta.pb.x (y4 -> y3), via1 at (ta.pb.x, y3), M2 east to (tb.p.x, y3), wait: M2 vertical at tb.p.x
    #     going down from y3 to y0 crosses y2 (`mid` M2)!
    #     Aha! Put `mid` on M2 at **y1** or **y2**, and put `sel`/`sel_b` vertical hops on M2 at x's OUTSIDE `mid`,
    #     OR put `mid` on **M2 at y2**, `sel` on **M2 at y3** (vertical M1 from y3 to y4 at ta.pb.x, and vertical M1 from
    #     y0 to y1? No, y0 to y3 at tb.p.x crosses y2 on M1? No, `mid` is on M2 at y2, NOT M1!!).
    #     BINGO!! `mid` is on **M2** at y2 — so **M1** is 100% OPEN across y2 at `ta.p.x` and `tb.p.x`!!
    #     Let's double check! At `x = ta.p[0]` (left of ta): NO M1 drain/source wires! Only `ta.p` at y0 and `ta.pb` at y4!
    #     At `x = tb.p[0]` (left of tb): NO M1 drain/source wires! Only `tb.p` at y0 and `tb.pb` at y4!
    #     Therefore:
    #       - `sel_b`: M1 north from ta.p (y0) to y1 -> via1 -> M2 east to (tb.pb.x, y1) -> via1 -> wait: M1 from y1 to y4 at tb.pb.x
    #         would hit tb.p at y0? NO! y1..y4 is strictly ABOVE y0!!
    #       - `sel`:   M1 south from ta.pb (y4) to y3 -> via1 -> M2 east to (tb.p.x, y3) -> via1 -> M1 south from y3 to y0 at tb.p.x!
    #         WAIT: at x = tb.p.x, M1 for sel_b would be y1..y4 and M1 for sel would be y0..y3 -> THOSE TWO WOULD SHORT AT tb.p.x!!
    #     Great catch! Separate their X by 0.45 um (use `x_s = tb.p[0] - 0.460` or route `sel_b` on M2 at y4 and `sel` on M2 at y0!):
    #     CHECK THAT!
    #       - `sel` at `y0` (bottom of channel):
    #           * `ta.pb` at `(ta.pb.x, y4)`: M1 east `0.0`? No, at `x_sel_drop = grid(ta.pb[0] - 0.440)` (empty space left of ta!),
    #             M1 west from `(ta.pb.x, y4)` to `(x_sel_drop, y4)`, M1 south to `(x_sel_drop, y3)` -> via1 -> M2 south to `(x_sel_drop, y0)` -> M2 east to `(tb.p.x, y0)` -> via1!
    #           * Wait: M2 at `y0` only runs from `x_sel_drop` to `tb.p.x` (does NOT touch `ta.p` because `ta.p` has NO via1 at `y0` — `ta.p` goes to `y1` on M1 first!).
    #       - `sel_b` at `y4` (top of channel):
    #           * `ta.p` at `(ta.p.x, y0)`: M1 north to `(ta.p.x, y1)` -> via1 -> M2 north to `(ta.p.x, y4)` ->Wait, `ta.pb` is at `(ta.p.x, y4)` (only on M1, NO via1 on `ta.pb`!).
    #             So M2 at `(ta.p.x, y4)` passes CLEANLY OVER `ta.pb` M1, runs M2 east to `(tb.pb.x, y4)` -> via1!
    #     WAIT A SECOND! VERIFY EVERY SINGLE VIA1 & LAYER IN THAT SOLUTION!
    #     At `ta`:
    #       - `ta.p` (`sel_b`) is on M1 at `(xa_g, y0)`. Put `via1` at `(xa_g, y1)`, M1 `(xa_g, y0)->(xa_g, y1)`.
    #         Then M2 goes north `(xa_g, y1)->(xa_g, y4)` and east `(xa_g, y4)->(xb_g, y4)` -> `via1` at `(xb_g, y4)` (`tb.pb`)!
    #         Does `sel_b` M2 cross `mid` M2 at `y2`? `mid` M2 runs from `ta.b.x` to `i1.a.x`, which is STRICTLY RIGHT of `xa_g`! ZERO CROSSING!!
    #       - `ta.pb` (`sel`) is on M1 at `(xa_g, y4)`. Run M1 west `(xa_g, y4)->(x_l, y4)` (`x_l = xa_g - 0.420`), `via1` at `(x_l, y4)`.
    #         Then M2 goes south `(x_l, y4)->(x_l, y0)` and east `(x_l, y0)->(xb_g, y0)` -> `via1` at `(xb_g, y0)` (`tb.p`)!
    #         Does `sel` M2 touch `sel_b` M2?
    #         `sel` M2 is at `x = x_l` (`y0..y4`) and `y = y0` (`x_l..xb_g`).
    #         `sel_b` M2 is at `x = xa_g` (`y1..y4`) and `y = y4` (`xa_g..xb_g`).
    #         Gap between `x_l` and `xa_g` = `0.420` (M2 width `0.24` -> gap `0.18 > 0.14`!).
    #         Gap between `y0` and `y1` = `0.500` (M2 gap `0.22 > 0.14`!).
    #         ZERO CROSSINGS! ZERO SHORTS! 100% PLANAR IN M1+M2!!
    xa_g, xb_g = ta["p"][0], tb["p"][0]
    x_l = grid(xa_g - 0.440)

    # sel_b: ta.p (xa_g, y0) -> tb.pb (xb_g, y4)
    c.wire("metal1", [(xa_g, y0), (xa_g, y1)], W_M1)
    c.via1(xa_g, y1)
    c.via1(xb_g, y4)
    c.wire("metal2", [(xa_g, y1), (xa_g, y4), (xb_g, y4)], 0.240)

    # sel: ta.pb (xa_g, y4) -> tb.p (xb_g, y0) -> extend M2 south to y_sel (1.20 um clear of b & 2.60 um clear of rst_n!)
    y_sel = grid(row.y_vss + 0.650)
    c.wire("metal1", [(x_l, y4), (xa_g, y4)], 0.320)
    c.via1(x_l, y4)
    c.via1(xb_g, y0)
    c.wire("metal2", [(x_l, y4), (x_l, y0), (xb_g, y0), (xb_g, y_sel)], 0.240)

    return {
        "a": (ta["a"][0], grid(row.y_p_bot + 0.900)),
        "b": (tb["a"][0], grid(row.y_n_top - 0.900)),
        "sel": (xb_g, y_sel),
        "sel_b": (xb_g, y4),
        "y": (i2["y_col_x"], y2),
        "x_end": x4,
    }, x4


def place_dff_r(
    c: Cell, cache: PdkCache, row: RowSpec, x_edge: float,
    wn: float = 1.2, wp: float = 2.4, gap_l: float = 0.720,
) -> tuple[dict, float]:
    """Place `sst_dff_r` (d, clk, rst_n -> q, qb) in 12 compact standard-row columns.

    Exact devices from `tx_sst_serializer16.spice`:
      Xci  clk  clkb  inv(1.2, 2.4)
      Xcb  clkb clki  inv(1.2, 2.4)
      Xtg1 d    m1    tgate(wn, wp, p=clkb, pb=clki)
      Xm2  m1   rst_n m2  nand2(wn*1.5, wp)
      Xm3  m2   m3    inv(0.8, 1.6)
      Xtg2 m3   m1    tgate(0.8, 1.6, p=clki, pb=clkb)
      Xtg3 m2   s1    tgate(wn, wp, p=clki, pb=clkb)
      Xsq  s1   qi    inv(wn*1.2, wp*1.2)
      Xsfb qi   rst_n s2  nand2(1.2, 1.6)
      Xtg4 s2   s1    tgate(0.8, 1.6, p=clkb, pb=clki)
      Xbq1 s1   q     inv(wn*1.5, wp*1.5)
      Xbq2 qi   qb    inv(wn*1.5, wp*1.5)
    """
    y0, y1, y2, y3, y4 = row.y_tracks

    # Place all 12 cells left-to-right (extra gap before tg2/tg3 so xl clock-swap M1 is >=0.35 um clear!)
    ci,  x = place_inv(c, cache, row, x_edge, 1.2, 2.4, 1, 1, gap_l=gap_l, trk_g=2)
    cb,  x = place_inv(c, cache, row, x,      1.2, 2.4, 1, 1, gap_l=0.680, trk_g=2)
    tg1, x = place_tgate(c, cache, row, x,    wn,  wp,  1, 1, gap_l=0.880)
    m2,  x = place_nand2(c, cache, row, x,    grid(wn * 1.5), wp, 1, 1, gap_l=0.680, trk_a=2, trk_b=0)
    m3,  x = place_inv(c, cache, row, x,      0.8, 1.6, 1, 1, gap_l=0.680, trk_g=2)
    tg2, x = place_tgate(c, cache, row, x,    0.8, 1.6, 1, 1, gap_l=1.240)
    tg3, x = place_tgate(c, cache, row, x,    wn,  wp,  1, 1, gap_l=1.240)
    sq,  x = place_inv(c, cache, row, x,      grid(wn * 1.2), grid(wp * 1.2), 1, 1, gap_l=0.680, trk_g=2)
    sfb, x = place_nand2(c, cache, row, x,    1.2, 1.6, 1, 1, gap_l=0.680, trk_a=2, trk_b=0)
    tg4, x = place_tgate(c, cache, row, x,    0.8, 1.6, 1, 1, gap_l=0.880)
    bq1, x = place_inv(c, cache, row, x,      grid(wn * 1.5), grid(wp * 1.5), 1, 1, gap_l=0.680, trk_g=2)
    bq2, x = place_inv(c, cache, row, x,      grid(wn * 1.5), grid(wp * 1.5), 1, 1, gap_l=0.680, trk_g=2)

    y_m1  = grid(row.y_vss + 0.780)
    y_m2  = grid(row.y_p_bot + 0.720)
    y_s1  = grid(row.y_vdd - 0.560)

    # A. Local M1 forward links on y2 (note: m3.y -> tg2.a hops on M2 at y2 over tg2's M1 clock swap!)
    c.wire("metal1", [(ci["y_col_x"], y2), cb["a"]], W_M1)
    c.wire("metal1", [(tg1["b"][0], y2), m2["a"]], W_M1)
    c.wire("metal1", [(m2["y_col_x"], y2), m3["a"]], W_M1)
    c.via1(m3["y_col_x"], y2)
    c.via1(tg2["a"][0], y2)
    c.wire("metal2", [(m3["y_col_x"], y2), (tg2["a"][0], y2)], 0.220)
    c.wire("metal1", [(tg3["b"][0], y2), sq["a"]], W_M1)
    c.wire("metal1", [(sq["y_col_x"], y2), sfb["a"]], W_M1)
    c.wire("metal1", [(sfb["y_col_x"], y2), tg4["a"]], W_M1)

    # B. clkb horizontal M2 bus at y1 (ci.y -> tg1.p, tg2.pb, tg3.pb, tg4.p)
    c.via1(ci["y_col_x"], y1)
    c.wire("metal1", [(tg1["p"][0], y0), (tg1["p"][0], y1)], W_M1)
    c.via1(tg1["p"][0], y1)
    c.wire("metal1", [(tg4["p"][0], y0), (tg4["p"][0], y1)], W_M1)
    c.via1(tg4["p"][0], y1)
    c.wire("metal2", [(ci["y_col_x"], y1), (tg4["p"][0], y1)], 0.220)

    # C. clki horizontal M2 bus at y3 (cb.y -> tg1.pb, tg2.p, tg3.p, tg4.pb)
    c.via1(cb["y_col_x"], y3)
    c.wire("metal1", [(tg1["pb"][0], y3), (tg1["pb"][0], y4)], W_M1)
    c.via1(tg1["pb"][0], y3)
    c.wire("metal1", [(tg4["pb"][0], y3), (tg4["pb"][0], y4)], W_M1)
    c.via1(tg4["pb"][0], y3)
    c.wire("metal2", [(cb["y_col_x"], y3), (tg4["pb"][0], y3)], 0.220)

    # D. Swapped clock taps on tg2 and tg3 — strictly M1 vertically under M2 buses (ZERO M2 crossing!)
    for tg in (tg2, tg3):
        xg = tg["p"][0]
        xl = grid(xg - 0.440)
        # tg.p (y0) -> clki (y3) on M1 at xg (passes under clkb M2 at y1!)
        c.wire("metal1", [(xg, y0), (xg, y3)], W_M1)
        c.via1(xg, y3)
        # tg.pb (y4) -> clkb (y1) on M1 via xl (passes under clki M2 at y3! Width 0.32 at y4 avoids notch!)
        c.wire("metal1", [(xl, y4), (xg, y4)], 0.320)
        c.wire("metal1", [(xl, y1), (xl, y4)], W_M1)
        c.via1(xl, y1)

    # E. m1 feedback on M2 at y_m1: tg1.b -> tg2.b
    c.wire("metal1", [(tg1["b"][0], y_m1), (tg1["b"][0], y2)], W_M1)
    c.wire("metal1", [(tg2["b"][0], y_m1), (tg2["b"][0], y2)], W_M1)
    c.via1(tg1["b"][0], y_m1)
    c.via1(tg2["b"][0], y_m1)
    c.wire("metal2", [(tg1["b"][0], y_m1), (tg2["b"][0], y_m1)], 0.240)

    # F. m2 forward on M2 at y_m2: m2.y -> tg3.a
    c.wire("metal1", [(m2["y_col_x"], y2), (m2["y_col_x"], y_m2)], W_M1)
    c.wire("metal1", [(tg3["a"][0], y2), (tg3["a"][0], y_m2)], W_M1)
    c.via1(m2["y_col_x"], y_m2)
    c.via1(tg3["a"][0], y_m2)
    c.wire("metal2", [(m2["y_col_x"], y_m2), (tg3["a"][0], y_m2)], 0.240)

    # G. s1 feedback + output drive on M2 at y_s1: tg3.b -> tg4.b -> bq1.a
    c.wire("metal1", [(tg3["b"][0], y2), (tg3["b"][0], y_s1)], W_M1)
    c.wire("metal1", [(tg4["b"][0], y2), (tg4["b"][0], y_s1)], W_M1)
    c.wire("metal1", [(bq1["a"][0], y2), (bq1["a"][0], y_s1)], W_M1)
    c.via1(tg3["b"][0], y_s1)
    c.via1(tg4["b"][0], y_s1)
    c.via1(bq1["a"][0], y_s1)
    c.wire("metal2", [(tg3["b"][0], y_s1), (bq1["a"][0], y_s1)], 0.240)

    # G2. qi -> bq2.a on M2 at y_m1 (NMOS side, 100% clear of Y_M1_HOP=6.65 & Y_M2_N2=1.95!)
    c.wire("metal1", [(sq["y_col_x"], y_m1), (sq["y_col_x"], y2)], W_M1)
    c.wire("metal1", [(bq2["a"][0], y_m1), (bq2["a"][0], y2)], W_M1)
    c.via1(sq["y_col_x"], y_m1)
    c.via1(bq2["a"][0], y_m1)
    c.wire("metal2", [(sq["y_col_x"], y_m1), (bq2["a"][0], y_m1)], 0.240)

    # H. rst_n on M3 at y0: m2.b -> sfb.b (zero crossing with clkb/clki/mid!)
    c.via1(m2["b"][0], y0)
    slc.via2_clean(c, m2["b"][0], y0)
    c.via1(sfb["b"][0], y0)
    slc.via2_clean(c, sfb["b"][0], y0)
    c.wire("metal3", [(m2["b"][0], y0), (sfb["b"][0], y0)], 0.340)

    return {
        "d":     (tg1["a"][0], grid(row.y_p_bot + 0.900)),
        "clk":   ci["a"],
        "rst_n": (m2["b"][0], y0),
        "q":     (bq1["y_col_x"], y2),
        "qb":    (bq2["y_col_x"], y2),
        "x_end": x,
    }, x


def finish_cmos_row(c: Cell, row: RowSpec, x1: float, x2: float, tap_pitch: float = 1.6) -> None:
    """Paint continuous pwell/nwell, VSS/VDD tap bars, wide M1 rails, and dense viali stitching."""
    x1, x2 = grid(x1), grid(x2)
    c.rect("pwell", grid(x1 - 0.220), grid(row.y_vss - 0.500), grid(x2 + 0.220), row.nwell_y1)
    c.rect("nwell", grid(x1 - 0.220), row.nwell_y1, grid(x2 + 0.220), row.nwell_y2)
    draw_tap_h(c, "psubdiff", x1, x2, row.y_vss, half_w=0.175)
    draw_tap_h(c, "nsubdiff", x1, x2, row.y_vdd, half_w=0.175)
    w_rail = 0.540 if row.height >= 10.0 else 0.440
    c.wire("metal1", [(x1, row.y_vss), (x2, row.y_vss)], w_rail)
    c.wire("metal1", [(x1, row.y_vdd), (x2, row.y_vdd)], w_rail)
    span = max(1.0, x2 - x1)
    eff_pitch = min(tap_pitch, 1.6)
    n_taps = max(2, int(span // eff_pitch) + 1)
    for i in range(n_taps + 1):
        tx = grid(x1 + 0.350 + (span - 0.700) * i / n_taps)
        viali_pad(c, tx, row.y_vss)
        viali_pad(c, tx, row.y_vdd)


if __name__ == "__main__":
    # Quick standalone unit test of `sst_dff_r` and `sst_mux2`!
    import json
    work_root = slc.REPO / "results/layout/tx_sst_v4/test_cmos"
    cache = PdkCache(work_root / "_cache")
    for name, src_sub, fn in [
        ("test_mux2", "sst_mux2", lambda c: place_mux2(c, cache, ROW_SER, 0.0)),
        ("test_dff_r", "sst_dff_r", lambda c: place_dff_r(c, cache, ROW_SER, 0.0)),
    ]:
        w = work_root / name
        w.mkdir(parents=True, exist_ok=True)
        cell = Cell()
        pins, x_end = fn(cell)
        finish_cmos_row(cell, ROW_SER, -1.0, x_end + 1.0)
        for pnm, pt in pins.items():
            if pnm == "x_end":
                continue
            lyr = "metal3" if pnm == "rst_n" else ("metal2" if pnm in ("sel", "sel_b") else "metal1")
            cell.port(pnm, lyr, pt[0], pt[1])
        cell.port("vdd", "metal1", 0.0, ROW_SER.y_vdd)
        cell.port("vss", "metal1", 0.0, ROW_SER.y_vss)
        mag = w / f"{name}.mag"
        ref = w / f"{name}_ref.spice"
        cell.write(mag)
        ports = slc.generate_ref_spice(src_sub, name, ref)
        rep = slc.verify_flat_cell(w, name, mag, ref, ports)
        print(f"=== {name} ===")
        print(json.dumps({k: v for k, v in rep.items() if k != "parasitics"}, indent=2))
