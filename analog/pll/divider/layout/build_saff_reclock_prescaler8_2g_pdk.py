#!/usr/bin/env python3
"""Build pure-CMOS Equalized Nikolic SAFF-TSPC Reclocked 2 GHz /8 Prescaler SKY130 PDK layout (v2).

Implements `analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice` (`pll_saff_reclock_prescaler8_2g` v7) 1-to-1:
  - Interleaved adjacent floorplan (left -> right):
      [Xck] -> [Xff0] -> [Xr0+Xo0] |wall1| [Xff1] -> [Xr1+Xo1] |wall2| [Xtg2] -> [Xff2] -> [Xr2+Xo2]
    Cuts b0->Xr0, b1->Xr1, b2->Xr2 local wires down to ~2.5 um and slashes b1/b2 total wirelength 2.6-4x vs v1.
  - Mirrored split-half architecture across y = 0 (Top = +Y p-side, Bottom = -Y n-side):
      * Center VSS rail (psubdiff + locali + M1 + M4) along y = 0
      * Top & bottom VDD rails (nsubdiff + locali + M1 + M2 + M3 + M4) at y = +-8.260 um, joined by external-left M4 bridge
      * `saff_tspc_dff`: 7 compact mirrored columns (`tail_pm`, `dp_pre`, `ln_lp`, `eq`, `inv`, `drv`, `keep`)
        - `Xtail` (wt, nf=2) split symmetrically Top (wt/2, nf=2) + Bot (wt/2, nf=2) in parallel -> exact width `wt`
        - `Xeq` (weq, nf=1) split symmetrically Top (weq/2, nf=1) + Bot (weq/2, nf=1) in parallel -> exact width `weq`
        - Exact startup asymmetry `seed_k` on `Xff0` (0.30), `Xff1/Xff2` (0.25); 100% symmetric (`seed_k=0.0`) on `Xr0/Xr1/Xr2`
      * `Xck` (`tspc_ckbuf`, v7 wn1=2.4/wp1=6.0, wn2=10.8/wp2=24.0) drives dual symmetric M3 `ck_2g` rails (+-4.900 um, W=0.40 um)
      * Four non-overlapping M3 horizontal buses (W=0.30 um for data/b0n, W=0.40 um for ck_2g):
          +-4.900 (ck_2g), +-5.650 (b2p/b2n), +-6.400 (b1p/b1n + local d2p/d2n), +-7.150 (b0p/b0n, 1.90 um clear of ck_2g)
      * All 10 exported ports on M4: clkp/clkn, q2p/q2n, q4p/q4n, q8p/q8n, vdd, vss
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
sys.path.insert(0, str(REPO / "verification/layout"))
sys.path.insert(0, str(REPO / "analog/pll/divider/layout"))

from geometry import Cell  # noqa: E402
import build_cmos_prescaler8_2g_pdk as base  # noqa: E402
import build_cmos_sync_prescaler8_2g_pdk as sync_base  # noqa: E402

grid = base.grid
build_mos = base.build_mos
tie_poly_v = base.tie_poly_v
poly_cont_pad = base.poly_cont_pad
viali_pad = base.viali_pad
via3_pad = base.via3_pad
draw_tap_h = base.draw_tap_h
draw_np_wall_band = base.draw_np_wall_band

_sgn_y = sync_base._sgn_y
_locali_v = sync_base._locali_v
_locali_h = sync_base._locali_h
_tie_poly_bars = sync_base._tie_poly_bars
_tap_polycont = sync_base._tap_polycont
_strap_finger_poly_m1 = sync_base._strap_finger_poly_m1
_wire_shared_inv_gate = sync_base._wire_shared_inv_gate
_src_to_rail = sync_base._src_to_rail
_drains_to_track = sync_base._drains_to_track
_wire_diff_xover = sync_base._wire_diff_xover

Y_VSS = sync_base.Y_VSS
Y_N_TOP = sync_base.Y_N_TOP
NPOLY_TIE = sync_base.NPOLY_TIE
Y_T0 = sync_base.Y_T0
Y_T1 = sync_base.Y_T1
Y_T2 = sync_base.Y_T2
PPOLY_TIE = sync_base.PPOLY_TIE
Y_P_BOT = sync_base.Y_P_BOT
Y_VDD = sync_base.Y_VDD

# Internal NMOS diffusion M1 strap heights inside SAFF Stage 1
Y_TAIL = 1.600
Y_NSP = 2.150
Y_EQ_S = 4.760

# Four symmetric M3 horizontal buses (ordered to keep b0n 1.90 um clear of ck_2g and 0.68 um clear of VDD M3)
Y_M3_CK = 4.900   # Dual-rail wide ck_2g (Xck -> Xff0 -> Xr0 -> Xr1 -> Xr2)
Y_M3_B2 = 5.650   # +: b2p, -: b2n (short local Xtg2 <- Xff2 -> Xr2)
Y_M3_B1 = 6.400   # +: b1p, -: b1n (Xff1 -> Xr1 -> Xtg2) & short local d2p/d2n (Xtg2 -> Xff2)
Y_M3_B0 = 7.150   # +: b0p (Xff0 -> Xr0), -: b0n (Xff0 -> Xr0 -> Xff1.ck -> Xff2.ck)

H_TAP_VSS = base.H_TAP_VSS
H_TAP_VDD = base.H_TAP_VDD
V_TAP_EDGE = base.V_TAP_EDGE
V_TAP_WALL = base.V_TAP_WALL

W_M1 = base.W_M1
W_M2 = base.W_M2
W_M3 = 0.300
W_M3_CK = 0.400
W_M4 = 0.360
W_PWR_M1 = base.W_PWR_M1
W_PWR_M2 = base.W_PWR_M2
W_PWR_M3 = base.W_PWR_M3
W_PWR_M4 = base.W_PWR_M4

Y_M4_PAD = 4.050
Y_M4_TOP = 6.200
Y_M4_PORT = 5.500


def _place_asym_col(
    c: Cell,
    w: Path,
    pfx: str,
    x_edge: float,
    cname: str,
    *,
    n_top: tuple[str, float, float, int] | None = None,
    p_top: tuple[str, float, float, int] | None = None,
    n_bot: tuple[str, float, float, int] | None = None,
    p_bot: tuple[str, float, float, int] | None = None,
    gap_l: float = 0.440,
) -> tuple[dict, float]:
    """Place a column with independently specified Top/Bot NMOS & PMOS devices: (model, w_f, l_f, nf)."""
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
        dy = grid(Y_P_BOT + wf / 2.0) if is_p else grid(Y_N_TOP - wf / 2.0)
        cm, inf = build_mos(w, f"{pfx}_{cname}_{key}", mdl, wf, lf, nf, dy, is_p)
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

    col: dict = {"cx": cx, "hw": hw}
    col["inf_nt"] = built["nt"][1] if built["nt"] else None
    col["inf_pt"] = built["pt"][1] if built["pt"] else None
    col["inf_nb"] = built["nb"][1] if built["nb"] else None
    col["inf_pb"] = built["pb"][1] if built["pb"] else None
    # Convenience aliases when Top and Bot have identical finger footprints
    col["inf_n"] = col["inf_nt"] or col["inf_nb"]
    col["inf_p"] = col["inf_pt"] or col["inf_pb"]
    return col, x_next


def _place_sym_col(
    c: Cell,
    w: Path,
    pfx: str,
    x_edge: float,
    cname: str,
    n_spec: tuple[str, float, float, int] | None,
    p_spec: tuple[str, float, float, int] | None,
    gap_l: float,
) -> tuple[dict, float]:
    """Place a Top/Bot mirror-symmetric column (reusing single MOS cell per type)."""
    cn, inf_n = (None, None)
    cp, inf_p = (None, None)
    hws: list[float] = []
    if n_spec is not None:
        mdl, wf, lf, nf = n_spec
        dy_n = grid(Y_N_TOP - wf / 2.0)
        cn, inf_n = build_mos(w, f"{pfx}_{cname}_n", mdl, wf, lf, nf, dy_n, False)
        hws.append(inf_n["hw_diff"])
    if p_spec is not None:
        mdl, wf, lf, nf = p_spec
        dy_p = grid(Y_P_BOT + wf / 2.0)
        cp, inf_p = build_mos(w, f"{pfx}_{cname}_p", mdl, wf, lf, nf, dy_p, True)
        hws.append(inf_p["hw_diff"])
    hw = max(hws)
    cx = grid(x_edge + gap_l + hw)
    x_next = grid(cx + hw)
    if cn is not None:
        c.include(cn, dx=cx, mirror_y=False)
        c.include(cn, dx=cx, mirror_y=True)
    if cp is not None:
        c.include(cp, dx=cx, mirror_y=False)
        c.include(cp, dx=cx, mirror_y=True)
    return {
        "cx": cx,
        "hw": hw,
        "inf_n": inf_n,
        "inf_p": inf_p,
        "inf_nt": inf_n,
        "inf_pt": inf_p,
        "inf_nb": inf_n,
        "inf_pb": inf_p,
    }, x_next


def _col_for_sgn(col: dict, sgn: int) -> dict:
    return {
        "cx": col["cx"],
        "hw": col["hw"],
        "inf_n": col["inf_nt"] if sgn > 0 else col["inf_nb"],
        "inf_p": col["inf_pt"] if sgn > 0 else col["inf_pb"],
    }


def _place_m4_pin_bar(c: Cell, x: float, sgn: int, y_m1: float) -> None:
    """Bring signal from M1 at (x, sgn*y_m1) up to M4 vertical pin bar on sgn*[Y_M4_PAD, Y_M4_TOP]."""
    ym1 = _sgn_y(sgn, y_m1)
    ypad = _sgn_y(sgn, Y_M4_PAD)
    ytop = _sgn_y(sgn, Y_M4_TOP)
    c.via1(x, ym1)
    c.via2(x, ypad)
    c.wire("metal2", sorted([(x, ym1), (x, ypad)], key=lambda p: p[1]), W_M2)
    via3_pad(c, x, ypad)
    c.wire("metal4", sorted([(x, ypad), (x, ytop)], key=lambda p: p[1]), W_M4)


def build_saff_dff(
    c: Cell,
    w: Path,
    st_name: str,
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
    wkp: float,
    wkn: float,
    winv_n: float = 0.80,
    winv_p: float = 1.75,
    seed_k: float = 0.0,
    # Clock connection: "ck_2g" -> dual +-Y_M3_CK; "b0n" -> single -Y_M3_B0
    ck_mode: str = "ck_2g",
    # Input dp/dn M3 source track (positive Y magnitude) and whether polarity is swapped (self-toggle)
    in_m3_y: float = Y_M3_B0,
    in_swapped: bool = False,
    # Output qp/qn M3 export track (positive Y magnitude, or None for retimers driving outbuf directly)
    out_m3_y: float | None = None,
    # Optional attached deskewed output buffer (for Xr0/Xr1/Xr2)
    outbuf_cfg: dict | None = None,
    gap_first: float = 0.560,
) -> dict:
    """Build 7-column Nikolic-Symmetric Equalized SAFF-TSPC DFF (+ optional deskewed output buffer)."""
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x_edge = grid(x_l_edge)
    cols: dict[str, dict] = {}

    N_STD = "sky130_fd_pr__nfet_01v8"
    N_LVT = "sky130_fd_pr__nfet_01v8_lvt"
    P_STD = "sky130_fd_pr__pfet_01v8"

    # Col 0: Xtail (Top wt/2 nf=2 + Bot wt/2 nf=2 -> total wt) & Xpm (wmid nf=1)
    cols["tail_pm"], x_edge = _place_sym_col(
        c, w, st_name, x_edge, "tail_pm",
        (N_LVT, grid(wt / 4.0), 0.15, 2),
        (P_STD, grid(wmid), 0.15, 1),
        gap_l=gap_first,
    )
    # Col 1: Xdp/Xdn (wd nf=2 LVT) & Xpre (wpre nf=2)
    cols["dp_pre"], x_edge = _place_sym_col(
        c, w, st_name, x_edge, "dp_pre",
        (N_LVT, grid(wd / 2.0), 0.15, 2),
        (P_STD, grid(wpre / 2.0), 0.15, 2),
        gap_l=0.480,
    )
    # Col 2: Xln (wl nf=2 LVT) & Xlp (wlp nf=1)
    cols["ln_lp"], x_edge = _place_sym_col(
        c, w, st_name, x_edge, "ln_lp",
        (N_LVT, grid(wl / 2.0), 0.15, 2),
        (P_STD, grid(wlp), 0.15, 1),
        gap_l=0.440,
    )
    # Col 3: Xeq (Top weq/2 nf=1 + Bot weq/2 nf=1 -> total weq), empty NMOS slot gives extra LVT clearance
    cols["eq"], x_edge = _place_sym_col(
        c, w, st_name, x_edge, "eq",
        None,
        (P_STD, grid(weq / 2.0), 0.15, 1),
        gap_l=0.440,
    )
    # Col 4: Xinvs/Xinvr (std N winv_n nf=1, P winv_p nf=1)
    cols["inv"], x_edge = _place_sym_col(
        c, w, st_name, x_edge, "inv",
        (N_STD, grid(winv_n), 0.15, 1),
        (P_STD, grid(winv_p), 0.15, 1),
        gap_l=0.560,
    )
    # Col 5: Xdp_d/Xdn_d (wdn nf=2 LVT) & Xpp_s/Xpn_s (wop nf=2)
    cols["drv"], x_edge = _place_sym_col(
        c, w, st_name, x_edge, "drv",
        (N_LVT, grid(wdn / 2.0), 0.15, 2),
        (P_STD, grid(wop / 2.0), 0.15, 2),
        gap_l=0.640,
    )
    # Col 6: Static cross-coupled keeper (exact seed_k asymmetry on Top P & Bot N when seed_k > 0)
    if seed_k > 0.0:
        cols["keep"], x_edge = _place_asym_col(
            c, w, st_name, x_edge, "keep",
            n_top=(N_STD, grid(wkn), 0.15, 1),
            p_top=(P_STD, grid(wkp + seed_k), 0.15, 1),
            n_bot=(N_STD, grid(wkn + seed_k), 0.15, 1),
            p_bot=(P_STD, grid(wkp), 0.15, 1),
            gap_l=0.520,
        )
    else:
        cols["keep"], x_edge = _place_sym_col(
            c, w, st_name, x_edge, "keep",
            (N_STD, grid(wkn), 0.15, 1),
            (P_STD, grid(wkp), 0.15, 1),
            gap_l=0.520,
        )

    if outbuf_cfg is not None:
        cols["ob"], x_edge = _place_sym_col(
            c, w, st_name, x_edge, "ob",
            (N_STD, grid(outbuf_cfg["wn"] / 2.0), 0.15, 2),
            (P_STD, grid(outbuf_cfg["wp"] / 2.0), 0.15, 2),
            gap_l=0.640,
        )
        cols["k_out"], x_edge = _place_sym_col(
            c, w, st_name, x_edge, "k_out",
            (N_STD, grid(outbuf_cfg["wkn"]), 0.15, 1),
            (P_STD, grid(outbuf_cfg["wkp"]), 0.15, 1),
            gap_l=0.440,
        )

    c0, c1, c2, c3, c4, c5, c6 = (
        cols["tail_pm"], cols["dp_pre"], cols["ln_lp"], cols["eq"], cols["inv"], cols["drv"], cols["keep"]
    )

    for sgn in (+1, -1):
        y0, y1, y2 = _sgn_y(sgn, Y_T0), _sgn_y(sgn, Y_T1), _sgn_y(sgn, Y_T2)
        y_tail = _sgn_y(sgn, Y_TAIL)
        y_nsp = _sgn_y(sgn, Y_NSP)
        y_eqs = _sgn_y(sgn, Y_EQ_S)

        c0s = _col_for_sgn(c0, sgn)
        c1s = _col_for_sgn(c1, sgn)
        c2s = _col_for_sgn(c2, sgn)
        c3s = _col_for_sgn(c3, sgn)
        c4s = _col_for_sgn(c4, sgn)
        c5s = _col_for_sgn(c5, sgn)
        c6s = _col_for_sgn(c6, sgn)

        # 1. Power-rail source connections
        _src_to_rail(c, c0s, sgn, False, n_s_xs, p_s_pts)  # Xtail.S -> VSS
        _src_to_rail(c, c0s, sgn, True,  n_s_xs, p_s_pts)  # Xpm.S -> VDD
        _src_to_rail(c, c1s, sgn, True,  n_s_xs, p_s_pts)  # Xpre.S -> VDD
        _src_to_rail(c, c2s, sgn, True,  n_s_xs, p_s_pts)  # Xlp.S -> VDD
        for cs in (c4s, c5s, c6s):
            _src_to_rail(c, cs, sgn, False, n_s_xs, p_s_pts)
            _src_to_rail(c, cs, sgn, True,  n_s_xs, p_s_pts)
        if outbuf_cfg is not None:
            for nm in ("ob", "k_out"):
                cs = _col_for_sgn(cols[nm], sgn)
                _src_to_rail(c, cs, sgn, False, n_s_xs, p_s_pts)
                _src_to_rail(c, cs, sgn, True,  n_s_xs, p_s_pts)

        # 2. Internal tail node: c0(Xtail).D -> c1(Xdp).S on M1 at +-Y_TAIL
        tail_pts = [grid(c0["cx"] + x) for x in c0s["inf_n"]["d_xs"]] + [
            grid(c1["cx"] + x) for x in c1s["inf_n"]["s_xs"]
        ]
        for x in tail_pts:
            viali_pad(c, x, y_tail)
        c.wire("metal1", [(min(tail_pts), y_tail), (max(tail_pts), y_tail)], W_M1)

        # 3. Internal n_sp / n_sn node: c0(Xpm).D -> Y_T1 -> vertical M1 down to +-Y_NSP -> c1(Xdp).D & c2(Xln).S
        x_pm_d = grid(c0["cx"] + c0s["inf_p"]["d_xs"][0])
        _locali_v(c, x_pm_d, y1, _sgn_y(sgn, c0s["inf_p"]["c_y1"] + 0.06))
        viali_pad(c, x_pm_d, y1)
        c.wire("metal1", sorted([(x_pm_d, y_nsp), (x_pm_d, y1)], key=lambda p: p[1]), W_M1)
        nsp_pts = [x_pm_d] + [grid(c1["cx"] + x) for x in c1s["inf_n"]["d_xs"]] + [
            grid(c2["cx"] + x) for x in c2s["inf_n"]["s_xs"]
        ]
        for x in nsp_pts[1:]:
            viali_pad(c, x, y_nsp)
        c.wire("metal1", [(min(nsp_pts), y_nsp), (max(nsp_pts), y_nsp)], W_M1)

        # 4. Clock gates (ck) along +-Y_T2: c0 (Xtail+Xpm shared poly), c1 (Xpre nf=2 strapped), c3 (Xeq nf=1)
        xg_ck = _wire_shared_inv_gate(c, c0s, sgn, Y_T2, tap_dx=-0.560)
        c0["xg_ck"] = xg_ck
        _tie_poly_bars(c, c1s, sgn, tie_n=False, tie_p=True)
        _strap_finger_poly_m1(c, c1s, sgn, True, Y_T2, m1_reach_x=xg_ck)
        _tie_poly_bars(c, c3s, sgn, tie_n=False, tie_p=True, x_ext_l=-0.220)
        xg_eq = _tap_polycont(c, c3s, sgn, True, Y_T2, -0.220)
        viali_pad(c, xg_eq, y2)
        c.wire("metal1", [(xg_ck, y2), (xg_eq, y2)], W_M1)

        # 5. dp / dn input gate on c1 (Xdp/Xdn) at +-Y_T0
        _tie_poly_bars(c, c1s, sgn, tie_n=True, tie_p=False, x_ext_l=-0.460)
        xg_dp = _tap_polycont(c, c1s, sgn, False, Y_T0, -0.460)
        viali_pad(c, xg_dp, y0)
        c1["xg_d"] = xg_dp

        # 6. Sense-amp latch nodes sp / sn along +-Y_T1: c1(Xpre).D, c2(Xln+Xlp).D, c3(Xeq).D -> c4(Xinv).G -> c5(Xpp_s).G
        _drains_to_track(c, c1s, sgn, Y_T1, do_n=False, do_p=True)
        _drains_to_track(c, c2s, sgn, Y_T1, do_n=True, do_p=True)
        _drains_to_track(c, c3s, sgn, Y_T1, do_n=False, do_p=True)
        xg_inv = _wire_shared_inv_gate(c, c4s, sgn, Y_T1, tap_dx=-0.300)
        c4["xg"] = xg_inv
        c.wire("metal1", [(c1["cx"], y1), (xg_inv, y1)], W_M1)

        # Drive c5 PMOS (Xpp_s/Xpn_s) gate on +-Y_T2 from xg_inv
        c.wire("metal1", sorted([(xg_inv, y1), (xg_inv, y2)], key=lambda p: p[1]), W_M1)
        _tie_poly_bars(c, c5s, sgn, tie_n=True, tie_p=True)
        _strap_finger_poly_m1(c, c5s, sgn, True, Y_T2, m1_reach_x=xg_inv)

        # Cross-coupled latch gate on c2 (Xln+Xlp) at +-Y_T0 (vertical poly passes cleanly under Y_T2 M1!)
        xg_ln = _wire_shared_inv_gate(c, c2s, sgn, Y_T0, tap_dx=-0.460)
        c2["xg"] = xg_ln

        # Xeq.S tap at (c3.cx - 0.220, +-Y_EQ_S)
        x_eq_s = grid(c3["cx"] + c3s["inf_p"]["s_xs"][0])
        viali_pad(c, x_eq_s, y_eqs)
        c3["x_eq_s"] = x_eq_s

        # 7. Fast inverter drain sb / rb at c4.D (c4.cx + 0.220, +-Y_T1)
        xd_inv = _drains_to_track(c, c4s, sgn, Y_T1, do_n=True, do_p=True)
        c4["xd"] = xd_inv

        # 8. Slave pulldown gate (rb Top / sb Bot) on c5 NMOS strapped at +-Y_T0
        x_drv_ng_l, _ = _strap_finger_poly_m1(c, c5s, sgn, False, Y_T0)
        c5["x_ng_l"] = x_drv_ng_l

        # 9. Slave output qp / qn along +-Y_T1: c5.D -> c6.D
        xd_drv = _drains_to_track(c, c5s, sgn, Y_T1, do_n=True, do_p=True)
        xd_keep = _drains_to_track(c, c6s, sgn, Y_T1, do_n=True, do_p=True)
        c5["xd"] = xd_drv
        c6["xd"] = xd_keep
        c.wire("metal1", [(xd_drv, y1), (xd_keep, y1)], W_M1)

        # Static keeper gate (qn Top / qp Bot) at c6 on +-Y_T0
        xg_keep = _wire_shared_inv_gate(c, c6s, sgn, Y_T0, tap_dx=-0.220)
        c6["xg"] = xg_keep

        # 10. Optional attached deskewed output buffer (Xo0/Xo1/Xo2: r_n Top -> q_p, r_p Bot -> q_n)
        if outbuf_cfg is not None:
            c_ob = _col_for_sgn(cols["ob"], sgn)
            c_ko = _col_for_sgn(cols["k_out"], sgn)
            xg_ob = _wire_shared_inv_gate(c, c_ob, sgn, Y_T0, tap_dx=-0.460)
            _strap_finger_poly_m1(c, c_ob, sgn, True, Y_T2, m1_reach_x=xg_ob)
            c.wire("metal1", sorted([(xg_ob, y0), (xg_ob, y2)], key=lambda p: p[1]), W_M1)
            cols["ob"]["xg"] = xg_ob
            cols["ob"]["xd"] = _drains_to_track(c, c_ob, sgn, Y_T1, do_n=True, do_p=True)
            cols["k_out"]["xd"] = _drains_to_track(c, c_ko, sgn, Y_T1, do_n=True, do_p=True)
            cols["k_out"]["xg"] = _wire_shared_inv_gate(c, c_ko, sgn, Y_T0, tap_dx=-0.300)
            c.wire("metal1", [(cols["ob"]["xd"], y1), (cols["k_out"]["xd"], y1)], W_M1)

    # -------------------------------------------------------------------------
    # Inter-half M2 vertical straps & crossovers
    # -------------------------------------------------------------------------
    # A. Clock M2 vertical strap at c0["xg_ck"]
    x_ck = c0["xg_ck"]
    c.via1(x_ck, +Y_T2)
    c.via1(x_ck, -Y_T2)
    if ck_mode == "ck_2g":
        c.via2(x_ck, +Y_M3_CK)
        c.via2(x_ck, -Y_M3_CK)
        c.wire("metal2", [(x_ck, -Y_M3_CK), (x_ck, +Y_M3_CK)], W_M2)
    elif ck_mode == "b0n":
        c.via2(x_ck, -Y_M3_B0)
        c.wire("metal2", [(x_ck, -Y_M3_B0), (x_ck, +Y_T2)], W_M2)
    else:
        raise ValueError(f"Unknown ck_mode: {ck_mode}")

    # B. Symmetric tail M2 vertical bridge at c0["cx"] (joins Top & Bot Xtail drains)
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
        x_in_p = xg_d
        x_in_n = xg_d
    else:
        # Self-toggle: Top dp <- -in_m3_y (at xg_d), Bot dn <- +in_m3_y (at xg_d + 0.520)
        x_fb_top = xg_d
        x_fb_bot = grid(xg_d + 0.520)
        c.via1(x_fb_top, +Y_T0)
        c.via2(x_fb_top, -in_m3_y)
        c.wire("metal2", [(x_fb_top, -in_m3_y), (x_fb_top, +Y_T0)], W_M2)

        c.wire("metal1", [(xg_d, -Y_T0), (x_fb_bot, -Y_T0)], W_M1)
        c.via1(x_fb_bot, -Y_T0)
        c.via2(x_fb_bot, +in_m3_y)
        c.wire("metal2", [(x_fb_bot, -Y_T0), (x_fb_bot, +in_m3_y)], W_M2)
        x_in_p = x_fb_bot  # taps +in_m3_y
        x_in_n = x_fb_top  # taps -in_m3_y

    # D. Cross-coupled sp / sn + Xeq.S M2 pair at c3
    x_sn_m2 = c3["x_eq_s"]             # c3.cx - 0.220
    x_sp_m2 = grid(c3["cx"] + 0.300)   # pitch 0.520 um
    # sn: -Y_T1 -> +Y_T0 (c2 Top gate) -> +Y_EQ_S (c3 Top Xeq.S)
    c.via1(x_sn_m2, -Y_T1)
    c.via1(x_sn_m2, +Y_T0)
    c.via1(x_sn_m2, +Y_EQ_S)
    c.wire("metal1", [(c2["xg"], +Y_T0), (x_sn_m2, +Y_T0)], W_M1)
    c.wire("metal2", [(x_sn_m2, -Y_T1), (x_sn_m2, +Y_EQ_S)], W_M2)
    # sp: +Y_T1 -> -Y_T0 (c2 Bot gate) -> -Y_EQ_S (c3 Bot Xeq.S via M1 stub)
    c.via1(x_sp_m2, +Y_T1)
    c.via1(x_sp_m2, -Y_T0)
    c.via1(x_sp_m2, -Y_EQ_S)
    c.wire("metal1", [(c2["xg"], -Y_T0), (x_sp_m2, -Y_T0)], W_M1)
    c.wire("metal1", [(x_sn_m2, -Y_EQ_S), (x_sp_m2, -Y_EQ_S)], W_M1)
    c.wire("metal2", [(x_sp_m2, -Y_EQ_S), (x_sp_m2, +Y_T1)], W_M2)

    # E. Cross-coupled sb / rb M2 pair between c4 (inv.D) and c5 (drv NMOS gate)
    x_sb_m2 = c4["xd"]                 # c4.cx + 0.220
    x_rb_m2 = grid(c4["xd"] + 0.520)   # pitch 0.520 um
    # sb: +Y_T1 -> -Y_T0 -> c5 Bot gate
    c.via1(x_sb_m2, +Y_T1)
    c.via1(x_sb_m2, -Y_T0)
    c.wire("metal1", [(x_sb_m2, -Y_T0), (c5["x_ng_l"], -Y_T0)], W_M1)
    c.wire("metal2", [(x_sb_m2, -Y_T0), (x_sb_m2, +Y_T1)], W_M2)
    # rb: -Y_T1 (M1 stub from c4.xd) -> +Y_T0 -> c5 Top gate
    c.wire("metal1", [(x_sb_m2, -Y_T1), (x_rb_m2, -Y_T1)], W_M1)
    c.via1(x_rb_m2, -Y_T1)
    c.via1(x_rb_m2, +Y_T0)
    c.wire("metal1", [(x_rb_m2, +Y_T0), (c5["x_ng_l"], +Y_T0)], W_M1)
    c.wire("metal2", [(x_rb_m2, -Y_T1), (x_rb_m2, +Y_T0)], W_M2)

    # F. Cross-coupled qp / qn M2 pair at c6 (keep)
    x_qn_m2 = c6["xg"]                 # c6.cx - 0.220
    x_qp_m2 = grid(c6["cx"] + 0.300)   # pitch 0.520 um
    # qn: -Y_T1 -> +Y_T0 (+ optional -out_m3_y)
    c.via1(x_qn_m2, -Y_T1)
    c.via1(x_qn_m2, +Y_T0)
    y_qn_lo = -out_m3_y if out_m3_y is not None else -Y_T1
    if out_m3_y is not None:
        c.via2(x_qn_m2, -out_m3_y)
    c.wire("metal2", [(x_qn_m2, y_qn_lo), (x_qn_m2, +Y_T0)], W_M2)
    # qp: +Y_T1 (M1 stub from c6.xd) -> -Y_T0 (+ optional +out_m3_y)
    c.wire("metal1", [(c6["xd"], +Y_T1), (x_qp_m2, +Y_T1)], W_M1)
    c.wire("metal1", [(x_qn_m2, -Y_T0), (x_qp_m2, -Y_T0)], W_M1)
    c.via1(x_qp_m2, +Y_T1)
    c.via1(x_qp_m2, -Y_T0)
    y_qp_hi = +out_m3_y if out_m3_y is not None else +Y_T1
    if out_m3_y is not None:
        c.via2(x_qp_m2, +out_m3_y)
    c.wire("metal2", [(x_qp_m2, -Y_T0), (x_qp_m2, y_qp_hi)], W_M2)

    # G. Attached deskewed output buffer wiring + M4 output pins
    x_out_pin = None
    if outbuf_cfg is not None:
        # Connect rn (+Y_T0 at x_qn_m2) -> ob.xg (+Y_T0), rp (-Y_T0 at x_qp_m2) -> ob.xg (-Y_T0)
        xg_ob = cols["ob"]["xg"]
        c.wire("metal1", [(x_qn_m2, +Y_T0), (xg_ob, +Y_T0)], W_M1)
        c.wire("metal1", [(x_qp_m2, -Y_T0), (xg_ob, -Y_T0)], W_M1)
        # Cross-couple k_out gates
        x_kout_g = cols["k_out"]["xg"]
        x_kout_d = cols["k_out"]["xd"]
        _wire_diff_xover(c, x_kout_d, x_kout_g)
        c.wire("metal1", [(min(x_kout_g, x_kout_d), -Y_T0), (max(x_kout_g, x_kout_d), -Y_T0)], W_M1)
        x_out_pin = cols["ob"]["xd"]
        for sgn in (+1, -1):
            _place_m4_pin_bar(c, x_out_pin, sgn, Y_T1)

    return {
        "x_end": x_edge,
        "x_ck": x_ck,
        "x_in_p": x_in_p,
        "x_in_n": x_in_n,
        "x_qp": x_qp_m2,
        "x_qn": x_qn_m2,
        "x_out_pin": x_out_pin,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_tg2(c: Cell, w: Path, x_l_edge: float) -> dict:
    """Build differential TG 2:1 MUX (`Xtg2p` Top, `Xtg2n` Bot): v7 wn=1.3 nf=1, wp=2.8 (1.4x2)."""
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x_edge = grid(x_l_edge)
    N_STD = "sky130_fd_pr__nfet_01v8"
    P_STD = "sky130_fd_pr__pfet_01v8"

    cols: dict[str, dict] = {}
    for nm, gap_l in (("tg_a", 0.760), ("tg_b", 1.150)):
        cols[nm], x_edge = _place_sym_col(
            c, w, "tg2", x_edge, nm,
            (N_STD, 1.300, 0.15, 1),
            (P_STD, 1.400, 0.15, 2),
            gap_l=gap_l,
        )

    for nm in ("tg_a", "tg_b"):
        col = cols[nm]
        in_n, in_p = col["inf_n"], col["inf_p"]
        for sgn in (+1, -1):
            y0, y2 = _sgn_y(sgn, Y_T0), _sgn_y(sgn, Y_T2)
            _drains_to_track(c, col, sgn, Y_T1)
            y_sn = _sgn_y(sgn, (in_n["c_y1"] + in_n["c_y2"]) / 2.0)
            y_sp = _sgn_y(sgn, (in_p["c_y1"] + in_p["c_y2"]) / 2.0)
            xn_s = grid(col["cx"] + in_n["s_xs"][0])
            xp_s0 = grid(col["cx"] + in_p["s_xs"][0])
            xp_s1 = grid(col["cx"] + in_p["s_xs"][1])
            viali_pad(c, xn_s, y_sn)
            c.pad("metal1", xn_s, y_sn, 0.30)
            for xsp in (xp_s0, xp_s1):
                viali_pad(c, xsp, y_sp)
            c.wire("metal1", [(xp_s0, y_sp), (xp_s1, y_sp)], W_M1)
            col[f"y_sn_{sgn}"] = y_sn
            col[f"y_sp_{sgn}"] = y_sp

            _tie_poly_bars(c, col, sgn, tie_n=True, tie_p=True, x_ext_l=-0.380, x_ext_r=+0.380)
            xg_n = grid(col["cx"] - 0.820)
            xg_p = grid(col["cx"] + 0.840)
            x_tap_n = grid(col["cx"] - 0.220)
            _tap_polycont(c, col, sgn, False, Y_T0, -0.220)
            viali_pad(c, x_tap_n, y0)
            c.wire("metal1", [(xg_n, y0), (x_tap_n, y0)], W_M1)
            for dx_p in (-0.380, +0.380):
                xp_t = grid(col["cx"] + dx_p)
                _tap_polycont(c, col, sgn, True, Y_T2, dx_p)
                viali_pad(c, xp_t, y2)
            c.wire("metal1", [(grid(col["cx"] - 0.380), y2), (xg_p, y2)], W_M1)
            col[f"xn_{sgn}"] = xg_n
            col[f"xp_{sgn}"] = xg_p

        y_sn_p, y_sp_p = col["y_sn_1"], col["y_sp_1"]
        y_sn_n, y_sp_n = col["y_sn_-1"], col["y_sp_-1"]
        if nm == "tg_a":
            # Passes a = b2p (+Y_M3_B2) on Top, b2n (-Y_M3_B2) on Bot
            xs_a = grid(col["cx"] - 0.220)
            for yy in (y_sn_p, y_sp_p, y_sn_n, y_sp_n):
                c.via1(xs_a, yy)
            c.via2(xs_a, +Y_M3_B2)
            c.via2(xs_a, -Y_M3_B2)
            c.wire("metal2", [(xs_a, y_sn_p), (xs_a, +Y_M3_B2)], W_M2)
            c.wire("metal2", [(xs_a, -Y_M3_B2), (xs_a, y_sn_n)], W_M2)
            col["x_fb_top"] = xs_a
            col["x_fb_bot"] = xs_a
        else:
            # Passes b = b2n (-Y_M3_B2) on Top, b2p (+Y_M3_B2) on Bot
            xn_s = grid(col["cx"] - 0.220)
            x_bt = grid(col["cx"] - 0.260)
            x_bb = grid(col["cx"] + 0.280)
            c.wire("metal1", [(xn_s, y_sn_p), (x_bt, y_sn_p)], W_M1)
            c.via1(x_bt, y_sn_p)
            c.via1(x_bt, y_sp_p)
            c.via2(x_bt, -Y_M3_B2)
            c.wire("metal2", [(x_bt, -Y_M3_B2), (x_bt, y_sp_p)], W_M2)

            c.wire("metal1", [(xn_s, y_sn_n), (x_bb, y_sn_n)], W_M1)
            c.via1(x_bb, y_sn_n)
            c.via1(x_bb, y_sp_n)
            c.via2(x_bb, +Y_M3_B2)
            c.wire("metal2", [(x_bb, y_sp_n), (x_bb, +Y_M3_B2)], W_M2)
            col["x_fb_top"] = x_bt
            col["x_fb_bot"] = x_bb

    # Select gates: s = b1p (+Y_M3_B1), sb = b1n (-Y_M3_B1)
    # tg_a: NMOS = sb (-Y_M3_B1), PMOS = s (+Y_M3_B1)
    # tg_b: NMOS = s (+Y_M3_B1), PMOS = sb (-Y_M3_B1)
    for nm, n_trk, p_trk in (("tg_a", -Y_M3_B1, +Y_M3_B1), ("tg_b", +Y_M3_B1, -Y_M3_B1)):
        xn = cols[nm]["xn_1"]
        xp = cols[nm]["xp_1"]
        c.via1(xn, +Y_T0)
        c.via1(xn, -Y_T0)
        c.via2(xn, n_trk)
        c.wire("metal2", [(xn, min(-Y_T0, n_trk)), (xn, max(+Y_T0, n_trk))], W_M2)

        c.via1(xp, +Y_T2)
        c.via1(xp, -Y_T2)
        c.via2(xp, p_trk)
        c.wire("metal2", [(xp, min(-Y_T2, p_trk)), (xp, max(+Y_T2, p_trk))], W_M2)

    # Lift d2p/d2n (+-Y_T1) onto local M3 track +-Y_M3_B1 at x_d2_m2 = tg_b.cx + 1.660
    # (0.820 um right of tg_b.xp at +0.840 -> 0.420 um clean M3 pad-to-pad gap to b1n!)
    x_d2_m2 = grid(cols["tg_b"]["cx"] + 1.660)
    for sgn in (+1, -1):
        yt1 = _sgn_y(sgn, Y_T1)
        ym3 = _sgn_y(sgn, Y_M3_B1)
        c.wire("metal1", [(cols["tg_a"]["cx"], yt1), (x_d2_m2, yt1)], W_M1)
        c.via1(x_d2_m2, yt1)
        c.via2(x_d2_m2, ym3)
        c.wire("metal2", sorted([(x_d2_m2, yt1), (x_d2_m2, ym3)], key=lambda p: p[1]), W_M2)

    return {
        "x_end": grid(max(x_edge, x_d2_m2 + 0.300)),
        "x_d2_m2": x_d2_m2,
        "x_b1p_r": cols["tg_b"]["xn_1"],
        "x_b1n_r": cols["tg_b"]["xp_1"],
        "x_b2_l": cols["tg_a"]["x_fb_top"],
        "cols": cols,
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def build_tspc_ckbuf(c: Cell, w: Path, x_l_edge: float) -> dict:
    """Build matched differential-to-single-phase 2 GHz clock receiver (`tspc_ckbuf`, v7).

    Columns:
      0 (`ck1`): X1p (Top: clkp -> ck1n) / X1n (Bot: clkn -> ck1p) [wn=2.4 nf=2, wp=6.0 nf=2]
      1 (`k1`):  Xk1p (Top: ck1p -> ck1n) / Xk1n (Bot: ck1n -> ck1p) [wn=0.45 nf=1, wp=1.00 nf=1]
      2 (`dum`): X2n_dum (Bot only: ck1p -> ck_dum) [wn=2.7 nf=2, wp=6.0 nf=2]
      3 (`cdum`): Xcdum (Bot N-only: vss, ck_dum, vss, vss) [w=4.0 l=0.5 nf=4 -> 1.00x4]
      4 (`ck2`): X2p (Top + Bot parallel: ck1n -> ck_2g) [each wn=5.4 nf=4, wp=12.0 nf=4 -> total 10.8 / 24.0]
    """
    n_s_xs: list[float] = []
    p_s_pts: list[tuple[int, float]] = []
    x_edge = grid(x_l_edge)
    N_STD = "sky130_fd_pr__nfet_01v8"
    P_STD = "sky130_fd_pr__pfet_01v8"

    cols: dict[str, dict] = {}
    cols["ck1"], x_edge = _place_sym_col(
        c, w, "ck", x_edge, "ck1",
        (N_STD, 1.200, 0.15, 2),
        (P_STD, 3.000, 0.15, 2),
        gap_l=0.620,
    )
    cols["k1"], x_edge = _place_sym_col(
        c, w, "ck", x_edge, "k1",
        (N_STD, 0.450, 0.15, 1),
        (P_STD, 1.000, 0.15, 1),
        gap_l=0.440,
    )
    cols["dum"], x_edge = _place_asym_col(
        c, w, "ck", x_edge, "dum",
        n_bot=(N_STD, 1.350, 0.15, 2),
        p_bot=(P_STD, 3.000, 0.15, 2),
        gap_l=0.600,
    )
    cols["cdum"], x_edge = _place_asym_col(
        c, w, "ck", x_edge, "cdum",
        n_bot=(N_STD, 1.000, 0.50, 4),
        gap_l=0.480,
    )
    cols["ck2"], x_edge = _place_sym_col(
        c, w, "ck", x_edge, "ck2",
        (N_STD, 1.350, 0.15, 4),
        (P_STD, 3.000, 0.15, 4),
        gap_l=0.960,
    )

    c_ck1, c_k1, c_dum, c_cdum, c_ck2 = cols["ck1"], cols["k1"], cols["dum"], cols["cdum"], cols["ck2"]

    # Col 0 (`ck1`) and Col 1 (`k1`): symmetric Top/Bot
    for sgn in (+1, -1):
        y1 = _sgn_y(sgn, Y_T1)
        y2 = _sgn_y(sgn, Y_T2)
        for col in (c_ck1, c_k1):
            _src_to_rail(c, col, sgn, False, n_s_xs, p_s_pts)
            _src_to_rail(c, col, sgn, True,  n_s_xs, p_s_pts)
            col["xd"] = _drains_to_track(c, col, sgn, Y_T1)
        xg_ck1 = _wire_shared_inv_gate(c, c_ck1, sgn, Y_T1, tap_dx=-0.460)
        _strap_finger_poly_m1(c, c_ck1, sgn, True, Y_T2, m1_reach_x=xg_ck1)
        c.wire("metal1", sorted([(xg_ck1, y1), (xg_ck1, y2)], key=lambda p: p[1]), W_M1)
        c_ck1["xg"] = xg_ck1

        xg_k1 = _wire_shared_inv_gate(c, c_k1, sgn, Y_T0, tap_dx=-0.220)
        c_k1["xg"] = xg_k1
        c.wire("metal1", [(c_ck1["xd"], y1), (c_k1["xd"], y1)], W_M1)

    # Export clkp (+M4) and clkn (-M4) vertical pin bars at c_ck1["xg"]
    xg_ck1 = c_ck1["xg"]
    for sgn in (+1, -1):
        _place_m4_pin_bar(c, xg_ck1, sgn, Y_T1)

    # Cross-couple ck1n (+Y_T1) <-> ck1p (-Y_T1) onto k1 gates
    x_ck1p_m2 = c_k1["xg"]                 # c_k1.cx - 0.220
    x_ck1n_m2 = grid(c_k1["cx"] + 0.300)   # pitch 0.520 um
    c.via1(x_ck1p_m2, -Y_T1)
    c.via1(x_ck1p_m2, +Y_T0)
    c.wire("metal2", [(x_ck1p_m2, -Y_T1), (x_ck1p_m2, +Y_T0)], W_M2)
    c.wire("metal1", [(c_k1["xd"], +Y_T1), (x_ck1n_m2, +Y_T1)], W_M1)
    c.wire("metal1", [(x_ck1p_m2, -Y_T0), (x_ck1n_m2, -Y_T0)], W_M1)
    c.via1(x_ck1n_m2, +Y_T1)
    c.via1(x_ck1n_m2, -Y_T0)
    c.wire("metal2", [(x_ck1n_m2, -Y_T0), (x_ck1n_m2, +Y_T1)], W_M2)

    # Col 2 (`dum`, Bot only): input ck1p (-Y_T1) -> output ck_dum (-Y_T1)
    c_dum_b = _col_for_sgn(c_dum, -1)
    _src_to_rail(c, c_dum_b, -1, False, n_s_xs, p_s_pts)
    _src_to_rail(c, c_dum_b, -1, True,  n_s_xs, p_s_pts)
    xd_dum = _drains_to_track(c, c_dum_b, -1, Y_T1)
    xg_dum = _wire_shared_inv_gate(c, c_dum_b, -1, Y_T1, tap_dx=-0.460)
    _strap_finger_poly_m1(c, c_dum_b, -1, True, Y_T2, m1_reach_x=xg_dum)
    c.wire("metal1", [(xg_dum, -Y_T2), (xg_dum, -Y_T1)], W_M1)
    c.wire("metal1", [(c_k1["xd"], -Y_T1), (xg_dum, -Y_T1)], W_M1)

    # Col 3 (`cdum`, Bot N-only, l=0.50 nf=4): ALL s_xs & d_xs -> VSS; gates -> ck_dum (-Y_T0)
    inf_cd = c_cdum["inf_nb"]
    for sd_x in sorted(inf_cd["s_xs"] + inf_cd["d_xs"]):
        xc = grid(c_cdum["cx"] + sd_x)
        _locali_v(c, xc, Y_VSS, _sgn_y(-1, inf_cd["c_y1"] + 0.06))
        n_s_xs.append(xc)
    g_xs_cd = inf_cd["g_xs"]
    ya_cd, yb_cd = sorted((_sgn_y(-1, NPOLY_TIE[0]), _sgn_y(-1, NPOLY_TIE[1])))
    tie_poly_v(c, c_cdum["cx"], g_xs_cd, 0.50, _sgn_y(-1, Y_N_TOP), yb_cd)
    c.rect("poly", grid(c_cdum["cx"] + g_xs_cd[0] - 0.250), ya_cd, grid(c_cdum["cx"] + g_xs_cd[-1] + 0.250), yb_cd)
    cd_taps = [grid(c_cdum["cx"] + dx) for dx in (-1.185, 0.000, +1.185)]
    for gx in cd_taps:
        poly_cont_pad(c, gx, -Y_T0)
        viali_pad(c, gx, -Y_T0)
        c.rect("poly", grid(gx - 0.135), -Y_T0, grid(gx + 0.135), yb_cd)
    c.wire("metal1", [(cd_taps[0], -Y_T0), (cd_taps[-1], -Y_T0)], W_M1)
    # Connect X2n_dum.D (xd_dum, -Y_T1) -> Xcdum.G (cd_taps[0], -Y_T0)
    c.wire("metal1", [(xd_dum, -Y_T1), (cd_taps[0], -Y_T1)], W_M1)
    c.wire("metal1", [(cd_taps[0], -Y_T1), (cd_taps[0], -Y_T0)], W_M1)

    # Col 4 (`ck2`, Top + Bot parallel nf=4 each): input ck1n -> output ck_2g
    xg_ck2 = grid(c_ck2["cx"] - 1.400)
    for sgn in (+1, -1):
        y0, y1, y2 = _sgn_y(sgn, Y_T0), _sgn_y(sgn, Y_T1), _sgn_y(sgn, Y_T2)
        _src_to_rail(c, c_ck2, sgn, False, n_s_xs, p_s_pts)
        _src_to_rail(c, c_ck2, sgn, True,  n_s_xs, p_s_pts)
        _drains_to_track(c, c_ck2, sgn, Y_T1)
        _wire_shared_inv_gate(c, c_ck2, sgn, Y_T1, tap_dx=-1.400)
        _strap_finger_poly_m1(c, c_ck2, sgn, False, Y_T0, m1_reach_x=xg_ck2)
        _strap_finger_poly_m1(c, c_ck2, sgn, True,  Y_T2, m1_reach_x=xg_ck2)
        c.wire("metal1", sorted([(xg_ck2, y0), (xg_ck2, y2)], key=lambda p: p[1]), W_M1)

    # Feed ck1n from Top (+Y_T1) right into xg_ck2, and drop via M2 to Bot xg_ck2 (-Y_T1)
    c.wire("metal1", [(x_ck1n_m2, +Y_T1), (xg_ck2, +Y_T1)], W_M1)
    c.via1(xg_ck2, +Y_T1)
    c.via1(xg_ck2, -Y_T1)
    c.wire("metal2", [(xg_ck2, -Y_T1), (xg_ck2, +Y_T1)], W_M2)

    # Launch ck_2g onto BOTH +Y_M3_CK and -Y_M3_CK via dual parallel vertical M2 bars at d_xs=[-0.48, +0.48]
    ck2_d_xs = [grid(c_ck2["cx"] + dx) for dx in c_ck2["inf_n"]["d_xs"]]
    for xd in ck2_d_xs:
        c.via1(xd, +Y_T1)
        c.via1(xd, -Y_T1)
        c.via2(xd, +Y_M3_CK)
        c.via2(xd, -Y_M3_CK)
        c.wire("metal2", [(xd, -Y_M3_CK), (xd, +Y_M3_CK)], W_M2)

    return {
        "x_end": x_edge,
        "x_clkin": xg_ck1,
        "x_ck2g_l": min(ck2_d_xs),
        "x_ck2g_r": max(ck2_d_xs),
        "n_s_xs": n_s_xs,
        "p_s_pts": p_s_pts,
    }


def _place_filtered_viali(c: Cell, xs: list[float], y: float, min_pitch: float = 0.380) -> list[float]:
    """Place viali + M1 pads along a continuous locali power rail while enforcing mcon.2 spacing."""
    placed: list[float] = []
    for x in sorted({grid(v) for v in xs}):
        if all(abs(x - px) >= min_pitch for px in placed):
            c.pad("viali", x, y, 0.17)
            c.pad("metal1", x, y, 0.32)
            placed.append(x)
    return placed


def _build_ref_netlist(cell: str) -> str:
    """Flat SKY130 PDK LVS reference netlist matching `pll_saff_reclock_prescaler8_2g` 1-to-1."""
    lines = [
        f"* PDK LVS reference netlist for {cell} (1-to-1 with pll_saff_reclock_prescaler8_2g)",
        f".subckt {cell} clkp clkn q2p q2n q4p q4n q8p q8n vdd vss",
    ]

    def inv(nm: str, a: str, y: str, wn: float, wp: float) -> None:
        lines.append(f"X{nm}_n {y} {a} vss vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15")
        lines.append(f"X{nm}_p {y} {a} vdd vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15")

    def tgmux(nm: str, a: str, b: str, s: str, sb: str, y: str, wn: float, wp: float) -> None:
        lines.extend([
            f"X{nm}_na {y} {sb} {a} vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{nm}_pa {y} {s}  {a} vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
            f"X{nm}_nb {y} {s}  {b} vss sky130_fd_pr__nfet_01v8 w={wn} l=0.15",
            f"X{nm}_pb {y} {sb} {b} vdd sky130_fd_pr__pfet_01v8 w={wp} l=0.15",
        ])

    def outbuf(nm: str, qpi: str, qni: str, qp: str, qn: str, wn: float, wp: float, wkn: float, wkp: float) -> None:
        inv(f"{nm}_obp", qpi, qp, wn, wp)
        inv(f"{nm}_obn", qni, qn, wn, wp)
        inv(f"{nm}_kp",  qp,  qn, wkn, wkp)
        inv(f"{nm}_kn",  qn,  qp, wkn, wkp)

    def saff(
        nm: str, dp: str, dn: str, ck: str, qp: str, qn: str, *,
        wt: float, wd: float, wl: float, wlp: float, wpre: float, wmid: float, weq: float,
        wop: float, wdn: float, wkp: float, wkn: float, seed_k: float = 0.0,
        winv_n: float = 0.80, winv_p: float = 1.75,
    ) -> None:
        tail, n_sp, n_sn = f"{nm}_tail", f"{nm}_nsp", f"{nm}_nsn"
        sp, sn, sb, rb = f"{nm}_sp", f"{nm}_sn", f"{nm}_sb", f"{nm}_rb"
        wkp_p = round(wkp + seed_k, 4)
        wkn_n = round(wkn + seed_k, 4)
        lines.extend([
            f"X{nm}_tail {tail} {ck} vss vss sky130_fd_pr__nfet_01v8_lvt w={wt} l=0.15",
            f"X{nm}_dp {n_sp} {dp} {tail} vss sky130_fd_pr__nfet_01v8_lvt w={wd} l=0.15",
            f"X{nm}_dn {n_sn} {dn} {tail} vss sky130_fd_pr__nfet_01v8_lvt w={wd} l=0.15",
            f"X{nm}_lnp {sp} {sn} {n_sp} vss sky130_fd_pr__nfet_01v8_lvt w={wl} l=0.15",
            f"X{nm}_lnn {sn} {sp} {n_sn} vss sky130_fd_pr__nfet_01v8_lvt w={wl} l=0.15",
            f"X{nm}_lpp {sp} {sn} vdd vdd sky130_fd_pr__pfet_01v8 w={wlp} l=0.15",
            f"X{nm}_lpn {sn} {sp} vdd vdd sky130_fd_pr__pfet_01v8 w={wlp} l=0.15",
            f"X{nm}_prep {sp} {ck} vdd vdd sky130_fd_pr__pfet_01v8 w={wpre} l=0.15",
            f"X{nm}_pren {sn} {ck} vdd vdd sky130_fd_pr__pfet_01v8 w={wpre} l=0.15",
            f"X{nm}_eq {sp} {ck} {sn} vdd sky130_fd_pr__pfet_01v8 w={weq} l=0.15",
            f"X{nm}_pmp {n_sp} {ck} vdd vdd sky130_fd_pr__pfet_01v8 w={wmid} l=0.15",
            f"X{nm}_pmn {n_sn} {ck} vdd vdd sky130_fd_pr__pfet_01v8 w={wmid} l=0.15",
        ])
        inv(f"{nm}_invs", sp, sb, winv_n, winv_p)
        inv(f"{nm}_invr", sn, rb, winv_n, winv_p)
        lines.extend([
            f"X{nm}_pp_s {qp} {sp} vdd vdd sky130_fd_pr__pfet_01v8 w={wop} l=0.15",
            f"X{nm}_dp_d {qp} {rb} vss vss sky130_fd_pr__nfet_01v8_lvt w={wdn} l=0.15",
            f"X{nm}_pn_s {qn} {sn} vdd vdd sky130_fd_pr__pfet_01v8 w={wop} l=0.15",
            f"X{nm}_dn_d {qn} {sb} vss vss sky130_fd_pr__nfet_01v8_lvt w={wdn} l=0.15",
            f"X{nm}_kp_p {qp} {qn} vdd vdd sky130_fd_pr__pfet_01v8 w={wkp_p} l=0.15",
            f"X{nm}_kp_n {qp} {qn} vss vss sky130_fd_pr__nfet_01v8 w={wkn} l=0.15",
            f"X{nm}_kn_p {qn} {qp} vdd vdd sky130_fd_pr__pfet_01v8 w={wkp} l=0.15",
            f"X{nm}_kn_n {qn} {qp} vss vss sky130_fd_pr__nfet_01v8 w={wkn_n} l=0.15",
        ])

    # Xck (tspc_ckbuf v7: wn1=2.4 wp1=6.0 wn2=10.8 wp2=24.0)
    inv("ck_1p", "clkp", "ck1n", 2.4, 6.0)
    inv("ck_1n", "clkn", "ck1p", 2.4, 6.0)
    inv("ck_k1p", "ck1p", "ck1n", 0.45, 1.00)
    inv("ck_k1n", "ck1n", "ck1p", 0.45, 1.00)
    inv("ck_2p", "ck1n", "ck_2g", 10.8, 24.0)
    inv("ck_2n_dum", "ck1p", "ck_dum", 2.7, 6.0)
    lines.append("Xck_cdum vss ck_dum vss vss sky130_fd_pr__nfet_01v8 w=4.0 l=0.5")

    # Stage A: Xff0 (v7 boosted output drive)
    saff("ff0", "b0n", "b0p", "ck_2g", "b0p", "b0n",
         wt=5.4, wd=3.4, wl=2.8, wlp=1.6, wpre=2.8, wmid=1.3, weq=2.2,
         wop=3.8, wdn=3.4, wkp=0.65, wkn=0.55, seed_k=0.30)

    # Stage B: Xff1, Xtg2p/Xtg2n, Xff2 (v7 post-layout-aware sizing)
    saff("ff1", "b1n", "b1p", "b0n", "b1p", "b1n",
         wt=4.4, wd=2.8, wl=2.4, wlp=1.4, wpre=2.2, wmid=1.1, weq=1.8,
         wop=3.0, wdn=2.8, wkp=0.60, wkn=0.50, seed_k=0.25)
    tgmux("tg2p", "b2p", "b2n", "b1p", "b1n", "d2p", 1.3, 2.8)
    tgmux("tg2n", "b2n", "b2p", "b1p", "b1n", "d2n", 1.3, 2.8)
    saff("ff2", "d2p", "d2n", "b0n", "b2p", "b2n",
         wt=4.4, wd=2.8, wl=2.4, wlp=1.4, wpre=2.2, wmid=1.1, weq=1.8,
         wop=3.0, wdn=2.8, wkp=0.60, wkn=0.50, seed_k=0.25)

    # Stage C: Xr0, Xr1, Xr2 (v7 100% symmetric, seed_k=0.0)
    for idx, (bp, bn, rp, rn) in enumerate((("b0p", "b0n", "r0p", "r0n"),
                                            ("b1p", "b1n", "r1p", "r1n"),
                                            ("b2p", "b2n", "r2p", "r2n"))):
        saff(f"r{idx}", bp, bn, "ck_2g", rp, rn,
             wt=4.4, wd=2.8, wl=2.3, wlp=1.5, wpre=2.8, wmid=1.3, weq=2.0,
             wop=2.8, wdn=2.6, wkp=0.65, wkn=0.55, seed_k=0.0)

    # Stage D: Xo0, Xo1, Xo2
    outbuf("o0", "r0n", "r0p", "q2p", "q2n", 2.6, 5.4, 0.60, 1.25)
    outbuf("o1", "r1n", "r1p", "q4p", "q4n", 2.6, 5.4, 0.60, 1.25)
    outbuf("o2", "r2n", "r2p", "q8p", "q8n", 3.0, 6.2, 0.65, 1.35)

    lines.extend([f".ends {cell}", ""])
    return "\n".join(lines)


def build_saff_prescaler8_2g(out: Path) -> dict:
    cell = "pll_saff_reclock_prescaler8_2g_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)
    c = Cell()

    x_left_wall = 0.500
    all_n_s: list[float] = []
    all_p_pts: list[tuple[int, float]] = []
    walls: list[tuple[float, float]] = [(x_left_wall, V_TAP_EDGE)]

    # Block 1: Xck (2 GHz diff-to-single-phase clock receiver, left anchor driving dual ck_2g rails rightward)
    ck = build_tspc_ckbuf(c, w, grid(x_left_wall + V_TAP_EDGE))
    all_n_s.extend(ck["n_s_xs"])
    all_p_pts.extend(ck["p_s_pts"])

    # Block 2: Xff0 (2 GHz /2 toggle, clocked by ck_2g, self-toggle on b0 -> adjacent to Xr0)
    ff0 = build_saff_dff(
        c, w, "ff0", ck["x_end"],
        wt=5.4, wd=3.4, wl=2.8, wlp=1.6, wpre=2.8, wmid=1.3, weq=2.2,
        wop=3.8, wdn=3.4, wkp=0.65, wkn=0.55, seed_k=0.30,
        ck_mode="ck_2g", in_m3_y=Y_M3_B0, in_swapped=True, out_m3_y=Y_M3_B0,
        gap_first=0.640,
    )
    all_n_s.extend(ff0["n_s_xs"])
    all_p_pts.extend(ff0["p_s_pts"])

    # Block 3: Xr0 + Xo0 (2 GHz retimer 0 + q2 buffer, ~2.5 um from Xff0!)
    r0 = build_saff_dff(
        c, w, "r0", ff0["x_end"],
        wt=4.4, wd=2.8, wl=2.3, wlp=1.5, wpre=2.8, wmid=1.3, weq=2.0,
        wop=2.8, wdn=2.6, wkp=0.65, wkn=0.55, seed_k=0.0,
        ck_mode="ck_2g", in_m3_y=Y_M3_B0, in_swapped=False, out_m3_y=None,
        outbuf_cfg=dict(wn=2.6, wp=5.4, wkn=0.60, wkp=1.25),
        gap_first=0.640,
    )
    all_n_s.extend(r0["n_s_xs"])
    all_p_pts.extend(r0["p_s_pts"])

    # Tap wall 1 separating /2 group from /4 group
    x_wall1 = grid(r0["x_end"] + 0.500 + V_TAP_WALL)
    walls.append((x_wall1, V_TAP_WALL))

    # Block 4: Xff1 (1 GHz /4, clocked by b0n, self-toggle on b1 -> adjacent to Xr1!)
    ff1 = build_saff_dff(
        c, w, "ff1", grid(x_wall1 + V_TAP_WALL),
        wt=4.4, wd=2.8, wl=2.4, wlp=1.4, wpre=2.2, wmid=1.1, weq=1.8,
        wop=3.0, wdn=2.8, wkp=0.60, wkn=0.50, seed_k=0.25,
        ck_mode="b0n", in_m3_y=Y_M3_B1, in_swapped=True, out_m3_y=Y_M3_B1,
        gap_first=0.560,
    )
    all_n_s.extend(ff1["n_s_xs"])
    all_p_pts.extend(ff1["p_s_pts"])

    # Block 5: Xr1 + Xo1 (2 GHz retimer 1 + q4 buffer, ~2.5 um from Xff1!)
    r1 = build_saff_dff(
        c, w, "r1", ff1["x_end"],
        wt=4.4, wd=2.8, wl=2.3, wlp=1.5, wpre=2.8, wmid=1.3, weq=2.0,
        wop=2.8, wdn=2.6, wkp=0.65, wkn=0.55, seed_k=0.0,
        ck_mode="ck_2g", in_m3_y=Y_M3_B1, in_swapped=False, out_m3_y=None,
        outbuf_cfg=dict(wn=2.6, wp=5.4, wkn=0.60, wkp=1.25),
        gap_first=0.640,
    )
    all_n_s.extend(r1["n_s_xs"])
    all_p_pts.extend(r1["p_s_pts"])

    # Tap wall 2 separating /4 group from /8 group
    x_wall2 = grid(r1["x_end"] + 0.500 + V_TAP_WALL)
    walls.append((x_wall2, V_TAP_WALL))

    # Block 6: Xtg2 (select=b1, inputs=b2, output=d2 on local +-Y_M3_B1 -> adjacent to Xff2!)
    tg2 = build_tg2(c, w, grid(x_wall2 + V_TAP_WALL))
    all_n_s.extend(tg2["n_s_xs"])
    all_p_pts.extend(tg2["p_s_pts"])

    # Block 7: Xff2 (1 GHz /8, clocked by b0n, input=d2 on local +-Y_M3_B1, output=b2 -> adjacent to Xr2!)
    ff2 = build_saff_dff(
        c, w, "ff2", tg2["x_end"],
        wt=4.4, wd=2.8, wl=2.4, wlp=1.4, wpre=2.2, wmid=1.1, weq=1.8,
        wop=3.0, wdn=2.8, wkp=0.60, wkn=0.50, seed_k=0.25,
        ck_mode="b0n", in_m3_y=Y_M3_B1, in_swapped=False, out_m3_y=Y_M3_B2,
        gap_first=0.560,
    )
    all_n_s.extend(ff2["n_s_xs"])
    all_p_pts.extend(ff2["p_s_pts"])

    # Block 8: Xr2 + Xo2 (2 GHz retimer 2 + q8 buffer scaled 1.15x, ~2.5 um from Xff2!)
    r2 = build_saff_dff(
        c, w, "r2", ff2["x_end"],
        wt=4.4, wd=2.8, wl=2.3, wlp=1.5, wpre=2.8, wmid=1.3, weq=2.0,
        wop=2.8, wdn=2.6, wkp=0.65, wkn=0.55, seed_k=0.0,
        ck_mode="ck_2g", in_m3_y=Y_M3_B2, in_swapped=False, out_m3_y=None,
        outbuf_cfg=dict(wn=3.0, wp=6.2, wkn=0.65, wkp=1.35),
        gap_first=0.640,
    )
    all_n_s.extend(r2["n_s_xs"])
    all_p_pts.extend(r2["p_s_pts"])

    x_right_wall = grid(r2["x_end"] + 0.500 + V_TAP_EDGE)
    walls.append((x_right_wall, V_TAP_EDGE))

    # -------------------------------------------------------------------------
    # Global M3 signal buses (zero overlaps across all 4 tracks; b0n 1.90 um clear of ck_2g!)
    # -------------------------------------------------------------------------
    # Track A (+-Y_M3_CK = +-4.900, W=0.400): dual-rail wide ck_2g spine: Xck -> Xff0 -> Xr0 -> Xr1 -> Xr2
    c.wire("metal3", [(ck["x_ck2g_l"], +Y_M3_CK), (r2["x_ck"], +Y_M3_CK)], W_M3_CK)
    c.wire("metal3", [(ck["x_ck2g_l"], -Y_M3_CK), (r2["x_ck"], -Y_M3_CK)], W_M3_CK)

    # Track B (+-Y_M3_B2 = +-5.650, W=0.300): short local b2p/b2n: Xtg2 <- Xff2 -> Xr2
    c.wire("metal3", [(tg2["x_b2_l"], +Y_M3_B2), (r2["x_in_p"], +Y_M3_B2)], W_M3)
    c.wire("metal3", [(tg2["x_b2_l"], -Y_M3_B2), (r2["x_in_n"], -Y_M3_B2)], W_M3)

    # Track C (+-Y_M3_B1 = +-6.400, W=0.300):
    #   Left segment: b1p/b1n: Xff1 -> Xr1 -> Xtg2 select
    c.wire("metal3", [(min(ff1["x_in_p"], ff1["x_qp"]), +Y_M3_B1), (tg2["x_b1p_r"], +Y_M3_B1)], W_M3)
    c.wire("metal3", [(min(ff1["x_in_n"], ff1["x_qn"]), -Y_M3_B1), (tg2["x_b1n_r"], -Y_M3_B1)], W_M3)
    #   Right local segment: d2p/d2n: Xtg2 -> Xff2 (0.42 um M3 pad-to-pad clear of b1n!)
    c.wire("metal3", [(tg2["x_d2_m2"], +Y_M3_B1), (ff2["x_in_p"], +Y_M3_B1)], W_M3)
    c.wire("metal3", [(tg2["x_d2_m2"], -Y_M3_B1), (ff2["x_in_n"], -Y_M3_B1)], W_M3)

    # Track D (+-Y_M3_B0 = +-7.150, W=0.300):
    #   +Y_M3_B0 (b0p): short local Xff0 -> Xr0
    c.wire("metal3", [(min(ff0["x_in_p"], ff0["x_qp"]), +Y_M3_B0), (r0["x_in_p"], +Y_M3_B0)], W_M3)
    #   -Y_M3_B0 (b0n): Xff0 -> Xr0 -> Xff1.ck -> Xff2.ck
    c.wire("metal3", [(min(ff0["x_in_n"], ff0["x_qn"]), -Y_M3_B0), (ff2["x_ck"], -Y_M3_B0)], W_M3)

    # -------------------------------------------------------------------------
    # Wells, tap walls, and dense M1..M4 power grid
    # -------------------------------------------------------------------------
    x_rail_l = grid(x_left_wall - V_TAP_EDGE - 0.140)
    x_rail_r = grid(x_right_wall + V_TAP_EDGE + 0.140)
    x_wl = grid(x_rail_l - 0.220)
    x_wr = grid(x_rail_r + 0.250)
    c.rect("pwell", x_wl, -Y_T1, x_wr, +Y_T1)
    c.rect("nwell", x_wl, +Y_T1, x_wr, grid(Y_VDD + 0.450))
    c.rect("nwell", x_wl, grid(-Y_VDD - 0.450), x_wr, -Y_T1)

    for xw, hw in walls:
        draw_np_wall_band(c, xw, Y_VSS, +Y_T1, +Y_VDD, hw)
        draw_np_wall_band(c, xw, Y_VSS, -Y_T1, -Y_VDD, hw)

    # Center VSS rail (psubdiff + locali + M1 + M4 spine)
    draw_tap_h(c, "psubdiff", x_rail_l, x_rail_r, Y_VSS, H_TAP_VSS)
    c.wire("metal1", [(x_rail_l, Y_VSS), (x_rail_r, Y_VSS)], W_PWR_M1)
    c.wire("metal4", [(x_left_wall, Y_VSS), (x_rail_r, Y_VSS)], W_PWR_M4)
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
    x_cur = grid(x_left_wall + 1.200)
    while x_cur <= x_rail_r - 0.800:
        m2_free = all(x_cur + 0.550 <= a or x_cur - 0.550 >= b for a, b in m2_y0_spans)
        if m2_free and all(abs(x_cur - vx) >= 1.200 for vx in vss_via_xs):
            c.via1(x_cur, Y_VSS)
            c.via2(x_cur, Y_VSS)
            via3_pad(c, x_cur, Y_VSS)
            vss_via_xs.append(x_cur)
        x_cur = grid(x_cur + 0.250)

    # Top and bottom VDD rails + external-left M4 bridge
    x_vdd_bridge = grid(x_left_wall - 1.100)
    for sgn in (+1, -1):
        yv = grid(sgn * Y_VDD)
        draw_tap_h(c, "nsubdiff", x_rail_l, x_rail_r, yv, H_TAP_VDD)
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
        x_cur = grid(x_left_wall + 0.900)
        while x_cur <= x_rail_r - 0.600:
            if all(abs(x_cur - vx) >= 0.900 for vx in vdd_via_xs):
                c.via1(x_cur, yv)
                c.via2(x_cur, yv)
                via3_pad(c, x_cur, yv)
                vdd_via_xs.append(x_cur)
            x_cur = grid(x_cur + 0.450)

    c.wire("metal4", [(x_vdd_bridge, -Y_VDD), (x_vdd_bridge, +Y_VDD)], W_PWR_M4)

    # Export all 10 exact ports on M4
    c.port("clkp", "metal4", ck["x_clkin"],   +Y_M4_PORT)
    c.port("clkn", "metal4", ck["x_clkin"],   -Y_M4_PORT)
    c.port("q2p",  "metal4", r0["x_out_pin"], +Y_M4_PORT)
    c.port("q2n",  "metal4", r0["x_out_pin"], -Y_M4_PORT)
    c.port("q4p",  "metal4", r1["x_out_pin"], +Y_M4_PORT)
    c.port("q4n",  "metal4", r1["x_out_pin"], -Y_M4_PORT)
    c.port("q8p",  "metal4", r2["x_out_pin"], +Y_M4_PORT)
    c.port("q8n",  "metal4", r2["x_out_pin"], -Y_M4_PORT)
    c.port("vdd",  "metal4", x_left_wall,     +Y_VDD)
    c.port("vss",  "metal4", x_left_wall,     Y_VSS)

    mag_path = w / f"{cell}.mag"
    c.write(mag_path)

    ref_text = _build_ref_netlist(cell)
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text(ref_text)

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"), str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"), str(mag_path), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(mag_path).bbox()
    return {
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)

    r = build_saff_prescaler8_2g(out)
    print(
        f"{r['cell']:38s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | "
        f"size={r['size_um']} um | area={r['area_um2']} um2",
        flush=True,
    )
    (out / "summary.json").write_text(json.dumps([r], indent=2) + "\n")
    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        cdir = out / r["cell"]
        for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
            src = cdir / f"{r['cell']}{ext}"
            if src.exists():
                shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
