#!/usr/bin/env python3
"""Physical PDK layout builder for `serdes_tx_sst_driver_pdk` (Full 4:1 Fused
N-over-N SST Driver + 2-Tap FFE + 5-Bit ZQ + On-Chip V_drv LDO).

Floorplan (~253.7 x 90.4 um = ~22,930 um^2, AR ~ 2.81):
  - West (x in [-8.4..97.6], y in [0.6..89.7]):
      `Xldo` (`sst_vdrv_ldo_pdk`: 15.3 pF stacked MIM + under-MIM 1p41 resistors + ABBA OTA + 240u pass FET)
  - East-South (x in [105..221], y in [3.0..29.4]):
      2 Compact High-Speed CMOS Rows (`ROW_DRV`, H=10.20 um) with local M1/M2 intra-row routing
      and over-cell M3 routing:
        * Row 0 (y=3.0..13.2):  `Xpg` (`sst_pulsegen_4ph`, local M1/M2 for `b0..b270`, `c0..c270`)
        * Row 1 (y=19.2..29.4): `Xmux_m` (West, mirror_x=True so `mp/mn` exit at West edge)
                                + `Xmux_f` (East, normal so `fp/fn` exit at East edge),
                                local M1/M2 for `mux_p/mux_n`
      Routed via DRC-guaranteed M3-H / M4-V `ManhattanRouter` using inter-row + over-cell diff-band M3 tracks.
      Inputs `d0..d3, db0..db3, phi0..phi270` exit cleanly on the South perimeter (M4)
      so `serdes_tx_sst_serializer16_pdk` snaps directly underneath in `serdes_tx_sst_top_pdk`!
  - East-North (x in [107..231], y in [35.75..89.20], aligned with `Xldo` height 89.72 um):
      28-Slice Mirrored Face-to-Face Array (`2 rows x 14 cols = 23 Main + 5 Post-FFE`):
        * Top Row (y_orig=66.60, normal): Cols 0..7=m3(8x), 8..11=m2(4x) | gap | Cols 12..13=f2(2x)
        * Bot Row (y_orig=55.40, mirror): Cols 0..7=m4(8x), 8..9=m1(2x), 10=m0(1x) | gap | Cols 11..12=f1(2x), 13=f0(1x)
        * Symmetric M4+M5 `pad_p/pad_n` trunks down the center seam (y=58..64) exiting East!
        * Heavy M4+M5 `vdrv` feed straight from `Xldo.vdrv` into both slice rows!
"""
from __future__ import annotations

from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sst_layout_common as slc  # noqa: E402
from sst_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    ManhattanRouter,
    grid,
    viali_pad,
    via2_clean,
    via3_pad,
    via3_array,
    via4_array,
)
import sst_analog_blocks as sab  # noqa: E402
import sst_cmos_cells as scc  # noqa: E402


def _add_row_transformed(
    dst: Cell,
    row_cell: Cell,
    pins_local: dict[str, list[tuple[float, float, str]]],
    dx: float,
    y_vss_world: float,
    mirror_y: bool = False,
    mirror_x: bool = False,
) -> dict[str, list[tuple[float, float, str]]]:
    """Place a standard row cell into `dst` at `(dx, y_vss_world)` with optional X/Y mirror and return mapped pins."""
    dx = grid(dx)
    dy = grid(y_vss_world)
    dst.include(row_cell, dx=dx, dy=dy, mirror_x=mirror_x, mirror_y=mirror_y)
    out: dict[str, list[tuple[float, float, str]]] = {}
    for net, plist in pins_local.items():
        mapped = []
        for px, py, lyr in plist:
            wx = grid((-px if mirror_x else px) + dx)
            wy = grid((-py if mirror_y else py) + dy)
            mapped.append((wx, wy, lyr))
        out[net] = mapped
    return out


def _build_pulsegen_row(cache: PdkCache) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build `sst_pulsegen_4ph` on a single `ROW_DRV` row (p0..p3 ONLY; zero pb0..pb3!)."""
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}
    b_pins: dict[str, list[tuple[float, float]]] = {}
    c_pins: dict[str, list[tuple[float, float]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    x = 0.0
    # Stage 1: input sharpening inverters Xi0..Xi27 + cross-coupled alignment Xcc1a/b
    for ph, bnet in (("phi0", "b0"), ("phi90", "b90"), ("phi180", "b180"), ("phi270", "b270")):
        u, x = scc.place_inv(c, cache, row, x, 3.0, 6.0, 1, 2, gap_l=0.760, trk_g=2)
        add_pin(ph, u["a"])
        b_pins.setdefault(bnet, []).append(u["y"])
    for a, b in (("b0", "b180"), ("b90", "b270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.6, 1.2, gap_l=0.760)
        b_pins.setdefault(a, []).append(u["ap"])
        b_pins.setdefault(b, []).append(u["an"])

    # Stage 2: restore polarity Xj0..Xj27 (5.0/12.0 -> crisp c_k falling edges) + Xcc2a/b
    for bnet, cnet in (("b0", "c0"), ("b90", "c90"), ("b180", "c180"), ("b270", "c270")):
        u, x = scc.place_inv(c, cache, row, x, 5.0, 12.0, 2, 4, gap_l=0.760, trk_g=2)
        b_pins.setdefault(bnet, []).append(u["a"])
        c_pins.setdefault(cnet, []).append(u["y"])
    for a, b in (("c0", "c180"), ("c90", "c270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.8, 1.6, gap_l=0.760)
        c_pins.setdefault(a, []).append(u["ap"])
        c_pins.setdefault(b, []).append(u["an"])

    # Stage 3: 25%-duty active-HIGH pulse generators ordered [p2, p3, p0, p1] so c0..c270 wire lengths
    # equalize to 18-23 um; wn=1.90 balances both SS -40C RCX and SS +85C CPEX pulse widths!
    for a, b, pnet in (("c270", "c0", "p2"), ("c0", "c90", "p3"), ("c90", "c180", "p0"), ("c180", "c270", "p1")):
        u, x = scc.place_nor2(c, cache, row, x, 1.90, 18.0, 1, 6, gap_l=0.880, trk_a=0, trk_b=4)
        c_pins.setdefault(a, []).append(u["a"])
        c_pins.setdefault(b, []).append(u["b"])
        add_pin(pnet, u["y"])

    # Local M1+M2 routing for b0..b270 over the NMOS diff band (y = 1.15..2.71)
    y_b_tracks = {"b0": 1.150, "b90": 1.670, "b180": 2.190, "b270": 2.710}
    for bnet, yb in y_b_tracks.items():
        pts = sorted(b_pins[bnet], key=lambda p: p[0])
        for px, py in pts:
            c.wire("metal1", [(px, yb), (px, py)], slc.W_M1)
            c.via1(px, yb)
        c.wire("metal2", [(pts[0][0], yb), (pts[-1][0], yb)], 0.240)

    # Local M1+M2 routing for c0..c270 over PMOS diff band ONLY (45% shorter & lighter without Xpb!)
    for cnet, yp in (("c0", 7.200), ("c90", 7.720), ("c180", 8.240), ("c270", 8.760)):
        pts = sorted(c_pins[cnet], key=lambda p: p[0])
        for px, py in pts:
            c.wire("metal1", [(px, py), (px, yp)], slc.W_M1)
            c.via1(px, yp)
        c.wire("metal2", [(pts[0][0], yp), (pts[-1][0], yp)], 0.240)

    return c, nets, x


def _build_mux4_row(
    cache: PdkCache,
    scale: float,
    tag: str,
    d_names: tuple[str, str, str, str],
    db_names: tuple[str, str, str, str],
    en_net: str | None,
    out_p_net: str,
    out_n_net: str,
    slot_order: tuple[int, int, int, int] = (3, 2, 1, 0),
) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build pure static CMOS `sst_mux4_predrv` (or `_en` when `en_net` set) on a single `ROW_DRV` row.

    Zero pass gates, zero pb0..pb3, zero contention! All internal nets (`g0..g3`, `e`, `o`, `pre1`, `enb`)
    route 100% on planar M2 (tapping M1 strictly inside the 3.0 um channel y=[4.0..6.0], NEVER running
    vertical M1 across diffusion bars or NAND2/NOR2 horizontal M1 straps!).
    """
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    y0, y1, y2, y3, y4 = row.y_tracks  # (4.00, 4.50, 5.00, 5.50, 6.00)
    y_e_trk = 4.460
    y_pre_trk = 5.000
    y_o_trk = 5.540
    y_g_inner_p = 7.300   # g0 -> ue.a (inner arch over PMOS band on M2)
    y_g_outer_p = 7.850   # g2 -> ue.b (outer arch over PMOS band on M2)
    y_g_inner_n = 2.200   # g1 -> uo.a (inner arch over NMOS band on M2)
    y_g_outer_n = 1.650   # g3 -> uo.b (outer arch over NMOS band on M2)
    y_enb_trk = 1.050     # enb -> u2.b (bottom NMOS band on M2, clear of g1/g3 & VSS!)

    is_main = (scale >= 0.8)
    gap = 0.640 if is_main else 0.560
    wn_g, wp_g = grid(2.6 * scale), grid(3.8 * scale)
    nfn_g, nfp_g = (1, 2) if is_main else (1, 1)
    wn_eo, wp_eo = grid(2.8 * scale), grid(5.2 * scale)
    nfn_eo, nfp_eo = (1, 2) if is_main else (1, 1)
    wn_m1, wp_m1 = (grid(1.8 * scale), grid(9.6 * scale)) if is_main else (grid(1.6 * scale), grid(8.4 * scale))
    nfn_m1, nfp_m1 = (1, 4) if is_main else (1, 1)
    wn_mb, wp_mb = grid(3.6 * scale), grid(9.6 * scale)
    nfn_mb, nfp_mb = (2, 4) if is_main else (1, 2)
    wn_2 = grid(10.0 * scale) if en_net is None else grid(7.6 * scale)
    wp_2 = grid(26.1 * scale) if en_net is None else grid(30.0 * scale)
    nfn_2, nfp_2 = (4, 9) if en_net is None else (1, 4)

    x = 0.0
    enb_xs: list[float] = []
    if en_net is not None:
        # Place Xenb on the West side of Xmux_f so fn stays strictly East of f0 (215.6) while keeping width <= 232.5!
        uenb, x = scc.place_inv(c, cache, row, x, 1.0, 2.0, 1, 1, gap_l=gap, trk_g=2)
        add_pin(en_net, uenb["a"])
        enb_xs.append(uenb["y_col_x"])

    # 5-stage polarity: positive leg takes db_names -> 5x invert -> out_p = d_names; negative leg takes d_names -> out_n!
    for in_names, onet in ((db_names, out_p_net), (d_names, out_n_net)):
        # 1. Stage 1: 4x NAND2(p_k, d_k) -> g_k (order 3,2,1,0 makes g0/g2 and g1/g3 strictly nested!)
        g_x: dict[int, float] = {}
        for k in slot_order:
            ug, x = scc.place_nand2(c, cache, row, x, wn_g, wp_g, nfn_g, nfp_g, gap_l=gap, trk_a=0, trk_b=4)
            add_pin(f"p{k}", ug["a"])
            add_pin(in_names[k], ug["b"])
            g_x[k] = ug["y_col_x"]

        # 2. Stage 2: Even/Odd NAND2 — swapped-input parallel (Xepa||Xepb, Xopa||Xopb) for Main (0.0 ps a/b skew!)
        #    and compact single NAND2 for Post-FFE; 100% planar zero-crossing M2 routing!
        if is_main:
            uea, x = scc.place_nand2(c, cache, row, x, grid(1.4 * scale), grid(2.6 * scale), 1, 1, gap_l=gap, trk_a=0, trk_b=4)
            ueb, x = scc.place_nand2(c, cache, row, x, grid(1.4 * scale), grid(2.6 * scale), 1, 1, gap_l=gap, trk_a=0, trk_b=4)
            uoa, x = scc.place_nand2(c, cache, row, x, grid(1.4 * scale), grid(2.6 * scale), 1, 1, gap_l=gap, trk_a=0, trk_b=4)
            uob, x = scc.place_nand2(c, cache, row, x, grid(1.4 * scale), grid(2.6 * scale), 1, 1, gap_l=gap, trk_a=0, trk_b=4)
            # UP (PMOS M2): g0 inner (7.30) -> uea.a, ueb.b; g1 outer (7.85) -> uoa.a, uob.b
            # DOWN (NMOS M2): g2 inner (2.75) -> uea.b, ueb.a; g3 outer (2.15) -> uoa.b, uob.a
            for sx, dst_xs, y_dst, y_bus in (
                (g_x[0], (uea["a"][0], ueb["b"][0]), y4, 7.300),
                (g_x[1], (uoa["a"][0], uob["b"][0]), y4, 7.850),
                (g_x[2], (uea["b"][0], ueb["a"][0]), y0, 2.750),
                (g_x[3], (uoa["b"][0], uob["a"][0]), y0, 2.150),
            ):
                c.via1(sx, y2)
                c.wire("metal2", [(sx, y2), (sx, y_bus)], 0.240)
                for dx in dst_xs:
                    c.via1(dx, y_dst)
                    c.wire("metal2", [(dx, y_dst), (dx, y_bus)], 0.240)
                all_x = [sx, *dst_xs]
                c.wire("metal2", [(min(all_x), y_bus), (max(all_x), y_bus)], 0.240)
            e_drv_xs = [uea["y_col_x"], ueb["y_col_x"]]
            o_drv_xs = [uoa["y_col_x"], uob["y_col_x"]]
        else:
            ue, x = scc.place_nand2(c, cache, row, x, wn_eo, wp_eo, nfn_eo, nfp_eo, gap_l=gap, trk_a=0, trk_b=4)
            uo, x = scc.place_nand2(c, cache, row, x, wn_eo, wp_eo, nfn_eo, nfp_eo, gap_l=gap, trk_a=0, trk_b=4)
            for sx, dx, y_src, y_dst, y_bus in (
                (g_x[0], ue["a"][0], y2, y4, y_g_inner_p),
                (g_x[2], ue["b"][0], y2, y4, y_g_outer_p),
                (g_x[1], uo["a"][0], y2, y0, y_g_inner_n),
                (g_x[3], uo["b"][0], y2, y0, y_g_outer_n),
            ):
                c.via1(sx, y_src)
                c.via1(dx, y_dst)
                c.wire("metal2", [(sx, y_src), (sx, y_bus), (dx, y_bus), (dx, y_dst)], 0.240)
            e_drv_xs = [ue["y_col_x"]]
            o_drv_xs = [uo["y_col_x"]]

        # 3. Stage 3: symmetric swapped-input parallel NOR2(e, o) || NOR2(o, e) -> pre1 (0.0 ps stack skew!)
        um1a, x = scc.place_nor2(c, cache, row, x, wn_m1, wp_m1, nfn_m1, nfp_m1, gap_l=gap, trk_a=0, trk_b=4)
        um1b, x = scc.place_nor2(c, cache, row, x, wn_m1, wp_m1, nfn_m1, nfp_m1, gap_l=gap, trk_a=0, trk_b=4)

        # Route `e` (ue*.y -> um1a.a & um1b.b) as straight horizontal M2 at y_e_trk=4.46 (all have M1 across [4..6]!)
        e_xs = [*e_drv_xs, um1a["a"][0], um1b["b"][0]]
        for px in e_xs:
            c.via1(px, y_e_trk)
        c.wire("metal2", [(min(e_xs), y_e_trk), (max(e_xs), y_e_trk)], 0.220)

        # Route `o` (uo*.y -> um1a.b & um1b.a) as straight horizontal M2 at y_o_trk=5.54
        o_xs = [*o_drv_xs, um1a["b"][0], um1b["a"][0]]
        for px in o_xs:
            c.via1(px, y_o_trk)
        c.wire("metal2", [(min(o_xs), y_o_trk), (max(o_xs), y_o_trk)], 0.220)

        # 4. Stage 4: Tapered intermediate buffer Xmb (slashing Stage-3 NOR2 fanout from 3.5 -> 1.5!)
        umb, x = scc.place_inv(c, cache, row, x, wn_mb, wp_mb, nfn_mb, nfp_mb, gap_l=gap, trk_g=2)

        # Route `pre1` (um1a.y -> um1b.y -> umb.a) as straight horizontal M2 at y_pre_trk=5.00
        p_xs = [um1a["y_col_x"], um1b["y_col_x"], umb["a"][0]]
        for px in p_xs:
            c.via1(px, y_pre_trk)
        c.wire("metal2", [(min(p_xs), y_pre_trk), (max(p_xs), y_pre_trk)], 0.220)

        # 5. Stage 5: output pre-driver (INV for Main, NOR2(mid, enb) for Post-FFE)
        if en_net is None:
            u2, x = scc.place_inv(c, cache, row, x, wn_2, wp_2, nfn_2, nfp_2, gap_l=gap, trk_g=2)
        else:
            u2, x = scc.place_nor2(c, cache, row, x, wn_2, wp_2, nfn_2, nfp_2, gap_l=gap, trk_a=2, trk_b=4)
            enb_xs.append(u2["b"][0])

        # Route `mid` (umb.y -> u2.a) directly on short local M1 at y2=5.00 (0 via, <0.5 ohm!)
        c.wire("metal1", [(umb["y_col_x"], y2), (u2["a"][0], y2)], slc.W_M1)
        add_pin(onet, u2["y"])

    if en_net is not None:
        for px in enb_xs:
            c.via1(px, y0)
            c.wire("metal2", [(px, y_enb_trk), (px, y0)], 0.240)
        c.wire("metal2", [(min(enb_xs), y_enb_trk), (max(enb_xs), y_enb_trk)], 0.240)

    return c, nets, x


def build_sst_driver(
    cache: PdkCache,
    add_ports: bool = True,
    compact_a1: bool = False,
) -> tuple[Cell, dict]:
    """Build complete `serdes_tx_sst_driver_pdk` macro (~231.5 x 90.1 um)."""
    c = Cell()
    row = scc.ROW_DRV

    # ------------------------------------------------------------------
    # 1. West Block: Compacted On-Chip V_drv LDO (`Xldo`, x in [0.0..86.5])
    # ------------------------------------------------------------------
    ldo_cell, ldo_meta = sab.build_sst_vdrv_ldo(cache, add_ports=False, compact_a1=compact_a1)
    c.include(ldo_cell, dx=0.0, dy=0.0)

    # ------------------------------------------------------------------
    # 2. East-South Block: 2 Compact High-Speed CMOS Rows (Row 0 = Xpg; Row 1 = Xmux_m || Xmux_f)
    #    Widened Ch0-1 (+1.8 um) and Ch1-Arr (+1.8 um) give p0..p3 & pb0..pb3 1.80 um double-spaced
    #    separated M3 tracks (zero p_k<->pb_k Miller coupling!) while keeping top height ~150.6 um!
    # ------------------------------------------------------------------
    x_cmos0 = 94.400
    x_pg0 = 94.400
    y_r0_vss = 3.000                                # Row 0 (Xpg | Xmux_f):    VSS=3.00,  VDD=13.20
    y_r0_vdd = grid(y_r0_vss + row.height)          # 13.20
    y_r1_vss = 21.000                               # Row 1 (Xmux_m):          VSS=21.00, VDD=31.20
    y_r1_vdd = grid(y_r1_vss + row.height)          # 31.20

    pg_cell, pg_nets, pg_w = _build_pulsegen_row(cache)
    mm_cell, mm_nets, mm_w = _build_mux4_row(
        cache, 1.0, "mm",
        ("d0", "d1", "d2", "d3"), ("db0", "db1", "db2", "db3"),
        en_net=None, out_p_net="mp", out_n_net="mn",
        slot_order=(3, 2, 1, 0),
    )
    mf_cell, mf_nets, mf_w = _build_mux4_row(
        cache, 0.35, "mf",
        ("db3", "db0", "db1", "db2"), ("d3", "d0", "d1", "d2"),
        en_net="ffe_en", out_p_net="fp", out_n_net="fn",
        slot_order=(3, 2, 1, 0),
    )

    # Row 0 (Xpg West, ~64 um) + Xmux_f East (~52 um) = ~118 um -> fits cleanly inside x <= 218 um!
    # Row 1 (Xmux_m mirrored West, ~74 um) -> fits cleanly inside x <= 172 um!
    x_cmos_l = grid(x_cmos0 - 0.800)                # 94.000
    r1_fit = (x_cmos0 + mm_w + 4.0 + mf_w + 1.6) <= 218.500
    all_nets: dict[str, list[tuple[float, float, str]]] = {}

    def merge_pins(pmap: dict[str, list[tuple[float, float, str]]]) -> None:
        for net, pts in pmap.items():
            all_nets.setdefault(net, []).extend(pts)

    if r1_fit:
        x_mm_r = grid(x_cmos0 + mm_w + 1.500)
        x_mf_l = grid(max(x_mm_r + 3.000, 162.000))
        x_r0_r = grid(x_pg0 + pg_w + 1.500)
        x_cmos_r = grid(max(x_r0_r, x_mf_l + mf_w + 1.600))
        scc.finish_cmos_row(pg_cell, row, grid(x_cmos_l - x_pg0), grid(x_r0_r - x_pg0), tap_pitch=1.6)
        r1_cell = Cell()
        merge_pins(_add_row_transformed(c, pg_cell, pg_nets, x_pg0, y_r0_vss, mirror_y=False, mirror_x=False))
        r1_mm_pins = _add_row_transformed(r1_cell, mm_cell, mm_nets, grid(x_mm_r - x_cmos0), 0.0, mirror_y=False, mirror_x=True)
        r1_mf_pins = _add_row_transformed(r1_cell, mf_cell, mf_nets, grid(x_mf_l - x_cmos0), 0.0, mirror_y=False, mirror_x=False)
        scc.finish_cmos_row(r1_cell, row, grid(x_cmos_l - x_cmos0), grid(x_cmos_r - x_cmos0), tap_pitch=1.6)
        merge_pins(_add_row_transformed(c, r1_cell, r1_mm_pins, x_cmos0, y_r1_vss, mirror_y=False, mirror_x=False))
        merge_pins(_add_row_transformed(c, Cell(), r1_mf_pins, x_cmos0, y_r1_vss, mirror_y=False, mirror_x=False))
    else:
        # Row 0 = Xpg (West) + Xmux_f (East, normal -> fp/fn exit East); Row 1 = Xmux_m (mirrored -> mp/mn exit West)
        x_mf_l = grid(x_pg0 + pg_w + 0.800)
        x_r0_r = grid(x_mf_l + mf_w + 0.800)
        x_mm_r = grid(x_cmos0 + mm_w + 1.500)
        x_cmos_r = grid(max(x_r0_r, x_mm_r + 1.600))
        r0_cell = Cell()
        r0_pg_pins = _add_row_transformed(r0_cell, pg_cell, pg_nets, grid(x_pg0 - x_cmos0), 0.0, mirror_y=False, mirror_x=False)
        r0_mf_pins = _add_row_transformed(r0_cell, mf_cell, mf_nets, grid(x_mf_l - x_cmos0), 0.0, mirror_y=False, mirror_x=False)
        scc.finish_cmos_row(r0_cell, row, grid(x_cmos_l - x_cmos0), grid(x_r0_r - x_cmos0), tap_pitch=1.6)
        merge_pins(_add_row_transformed(c, r0_cell, r0_pg_pins, x_cmos0, y_r0_vss, mirror_y=False, mirror_x=False))
        merge_pins(_add_row_transformed(c, Cell(), r0_mf_pins, x_cmos0, y_r0_vss, mirror_y=False, mirror_x=False))
        r1_cell = Cell()
        r1_mm_pins = _add_row_transformed(r1_cell, mm_cell, mm_nets, grid(x_mm_r - x_cmos0), 0.0, mirror_y=False, mirror_x=True)
        scc.finish_cmos_row(r1_cell, row, grid(x_cmos_l - x_cmos0), grid(x_cmos_r - x_cmos0), tap_pitch=1.6)
        merge_pins(_add_row_transformed(c, r1_cell, r1_mm_pins, x_cmos0, y_r1_vss, mirror_y=False, mirror_x=False))

    # Tie `vdd_en` (Xmux_m's permanent VDD enable) directly to Row 1's VDD rail (y_r1_vdd = 31.20) on M1/M2!
    for px, py, _ in all_nets.pop("vdd_en", []):
        c.via1(px, py)
        c.via1(px, y_r1_vdd)
        c.wire("metal2", [(px, min(py, y_r1_vdd)), (px, max(py, y_r1_vdd))], 0.280)

    # Low-R M2 over-straps directly atop ALL 4 CMOS M1 power rails (y_r0_vss/vdd, y_r1_vss/vdd)
    # stitched with via1 every 3.5 um! Cuts CMOS rail R from ~190 ohm to < 5 ohm!
    x_pwr_l = 93.100                                # 0.50 um clear of x_vdd_cmos_w=91.4 via3_array!
    x_pwr_r = grid(max(x_cmos_r + 1.200, 215.000))
    for y_rail, x_r_end in (
        (y_r0_vss, x_r0_r),
        (y_r0_vdd, x_r0_r),
        (y_r1_vss, x_cmos_r),
        (y_r1_vdd, x_cmos_r),
    ):
        x_l_start = x_pwr_l if y_rail in (y_r0_vss, y_r1_vss) else x_cmos_l
        c.wire("metal1", [(x_l_start, y_rail), (x_r_end, y_rail)], 0.540)
        c.wire("metal2", [(x_l_start, y_rail), (x_r_end, y_rail)], 0.960)
        v1_pitch = 1.6 if y_rail in (y_r0_vss, y_r1_vss) else 2.5
        n_v1 = max(2, int((x_r_end - x_cmos_l) // v1_pitch) + 1)
        for i in range(n_v1 + 1):
            vx = grid(x_cmos_l + 0.400 + (x_r_end - x_cmos_l - 0.800) * i / n_v1)
            c.via1(vx, y_rail)
    for y_vss_r in (y_r0_vss, y_r1_vss):
        c.via1(x_pwr_l, y_vss_r)
        via2_clean(c, x_pwr_l, y_vss_r)

    # Connect West CMOS VSS spine (x_pwr_l) straight to Xldo VSS (y_vss_bot=1.20) on M2/M3!
    c.wire("metal3", [(x_pwr_l, y_r0_vss), (x_pwr_l, y_r1_vss)], 1.000)
    c.wire("metal2", [(ldo_meta["vss"][0], ldo_meta["vss"][1]), (x_pwr_l, ldo_meta["vss"][1]), (x_pwr_l, y_r0_vss)], 1.000)

    # ------------------------------------------------------------------
    # 3. East-North Block: 28-Slice Face-to-Face Mirrored Array (2 x 14)
    # ------------------------------------------------------------------
    slice_cell, smeta = sab.build_sst_slice_unit(cache, add_ports=False)
    pitch = smeta["pitch_x"]     # 8.800
    hx = smeta["half_x"]         # 4.400
    gap_mf = 0.800               # clean M3 break between Main (mp/mn) and Post-FFE (fp/fn) slices

    x_arr_l = 96.000
    y_seam = 64.600              # +3.60 um vs v4.2 -> 1.80 um double-spaced p0..p3 & pb0..pb3, top H ~150.6 um!
    y_row_t = grid(y_seam + 5.600)   # 70.200
    y_row_b = grid(y_seam - 5.600)   # 59.000 (bot en = 39.35, y_en_b_bus = 38.20, 7.00 um above Row 1 VDD 31.20!)

    def col_cx(col_idx: int, split_after: int) -> float:
        extra = gap_mf if col_idx > split_after else 0.0
        return grid(x_arr_l + hx + col_idx * pitch + extra)

    top_cxs = [col_cx(i, 11) for i in range(14)]
    bot_cxs = [col_cx(i, 10) for i in range(14)]
    x_arr_r = grid(top_cxs[-1] + hx)

    for cx in top_cxs:
        c.include(slice_cell, dx=cx, dy=y_row_t, mirror_y=False)
    for cx in bot_cxs:
        c.include(slice_cell, dx=cx, dy=y_row_b, mirror_y=True)

    # Continuous pwell across the seam and gap_mf break
    c.rect("pwell", x_arr_l, grid(y_row_b - 15.400), x_arr_r, grid(y_row_t + 15.400))
    # Bridge power & pad rails across the 0.80 um Main/Post break in BOTH rows (NOT din_p/din_n!)
    for y_orig, mir, split_cxs in (
        (y_row_t, False, (top_cxs[11], top_cxs[12])),
        (y_row_b, True,  (bot_cxs[10], bot_cxs[11])),
    ):
        xb1, xb2 = grid(split_cxs[0] + hx - 0.10), grid(split_cxs[1] - hx + 0.10)
        def ym(yl: float) -> float:
            return grid(y_orig + (-yl if mir else yl))
        # Bridge pad_p, pad_n, vdrv (M4), vss_pwr, vss_drv, vdd_drv (M3+M1), nwell
        c.rect("metal4", xb1, grid(ym(smeta["y_pad_p"]) - 0.40), xb2, grid(ym(smeta["y_pad_p"]) + 0.40))
        c.rect("metal4", xb1, grid(ym(smeta["y_pad_n"]) - 0.40), xb2, grid(ym(smeta["y_pad_n"]) + 0.40))
        c.rect("metal4", xb1, grid(ym(smeta["y_vdrv"]) - 0.60),  xb2, grid(ym(smeta["y_vdrv"]) + 0.60))
        c.rect("metal3", xb1, grid(ym(smeta["y_vss_pwr"]) - 0.50), xb2, grid(ym(smeta["y_vss_pwr"]) + 0.50))
        c.rect("metal3", xb1, grid(ym(smeta["y_vss_drv"]) - 0.30), xb2, grid(ym(smeta["y_vss_drv"]) + 0.30))
        c.rect("metal3", xb1, grid(ym(smeta["y_vdd_drv"]) - 0.36), xb2, grid(ym(smeta["y_vdd_drv"]) + 0.36))
        c.rect("metal1", xb1, grid(ym(smeta["y_vss_pwr"]) - 0.25), xb2, grid(ym(smeta["y_vss_pwr"]) + 0.25))
        c.rect("metal1", xb1, grid(ym(smeta["y_vss_drv"]) - 0.22), xb2, grid(ym(smeta["y_vss_drv"]) + 0.22))
        c.rect("metal1", xb1, grid(ym(smeta["y_vdd_drv"]) - 0.22), xb2, grid(ym(smeta["y_vdd_drv"]) + 0.22))
        nwy1, nwy2 = sorted((ym(15.500), ym(19.450)))
        c.rect("nwell", xb1, nwy1, xb2, nwy2)

    # ------------------------------------------------------------------
    # 4. Symmetric Pad_p / Pad_n East Trunks + Low-R M5 Power Distribution (vdrv + vss + vdd!)
    # ------------------------------------------------------------------
    y_padp_t = grid(y_row_t + smeta["y_pad_p"])   # 67.600
    y_padn_t = grid(y_row_t + smeta["y_pad_n"])   # 65.240
    y_padn_b = grid(y_row_b - smeta["y_pad_n"])   # 63.960
    y_padp_b = grid(y_row_b - smeta["y_pad_p"])   # 61.600

    # Join Top & Bot pad_n at East (x = x_padn_j) on M4; join Top & Bot pad_p at East (x = x_padp_j) on M4+M5!
    x_e_base = grid(max(x_arr_r, x_pwr_r))
    x_padn_j = grid(x_e_base + 1.200)
    x_vdd_e  = grid(x_e_base + 2.800)
    x_padp_j = grid(x_e_base + 5.200)
    x_fn_v   = grid(x_e_base + 7.200)
    x_fp_v   = grid(x_e_base + 8.400)
    x_pad_out = grid(x_e_base + 11.000)           # 231.000 -> flush East edge at 231.500!

    # pad_n: M4 bridge at x_padn_j + M4 exit at y=y_seam -> clear of pad_p M5 bridge!
    c.wire("metal4", [(x_arr_r, y_padn_t), (x_padn_j, y_padn_t), (x_padn_j, y_padn_b), (x_arr_r, y_padn_b)], 0.800)
    c.wire("metal4", [(x_padn_j, y_seam), (x_pad_out, y_seam)], 1.000)

    # pad_p: extend M4 past x_padn_j to x_padp_j, bridge on M5 over y_seam (pad_n M4) so zero short!
    c.wire("metal4", [(x_arr_r, y_padp_t), (x_padp_j, y_padp_t)], 0.800)
    c.wire("metal4", [(x_arr_r, y_padp_b), (x_padp_j, y_padp_b)], 0.800)
    via4_array(c, x_padp_j, y_padp_t, nx=1, ny=1)
    via4_array(c, x_padp_j, y_padp_b, nx=1, ny=1)
    c.wire("metal5", [(x_padp_j, y_padp_b), (x_padp_j, y_padp_t)], 1.800)
    c.wire("metal4", [(x_padp_j, y_padp_t), (x_pad_out, y_padp_t)], 1.000)

    # Heavy VDRV feed from Xldo.vdrv (74.750) -> vertical M4+M5 spine at x=91.0 -> both slice rows
    # + 2.0 um M5 over-straps directly over y_vdrv_t and y_vdrv_b across the 2x14 slice array!
    y_vdrv_t = grid(y_row_t + smeta["y_vdrv"])    # 78.350
    y_vdrv_b = grid(y_row_b - smeta["y_vdrv"])    # 50.850
    y_vdrv_lo = min(y_vdrv_b, ldo_meta["vdrv"][1])
    y_vdrv_hi = max(y_vdrv_t, ldo_meta["vdrv"][1])
    x_vdrv_sp = 91.000
    c.wire("metal4", [ldo_meta["vdrv"], (x_vdrv_sp, ldo_meta["vdrv"][1])], 2.000)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_lo), (x_vdrv_sp, y_vdrv_hi)], 2.200)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_t), (x_arr_l, y_vdrv_t)], 1.400)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_b), (x_arr_l, y_vdrv_b)], 1.400)
    via4_array(c, x_vdrv_sp, y_vdrv_b, nx=1, ny=1)
    via4_array(c, x_vdrv_sp, y_vdrv_t, nx=1, ny=1)
    if abs(ldo_meta["vdrv"][1] - y_vdrv_t) > 0.5 and abs(ldo_meta["vdrv"][1] - y_vdrv_b) > 0.5:
        via4_array(c, x_vdrv_sp, ldo_meta["vdrv"][1], nx=1, ny=1)
    c.wire("metal5", [(ldo_meta["vdrv"][0], ldo_meta["vdrv"][1]), (x_vdrv_sp, ldo_meta["vdrv"][1])], 2.400)
    c.wire("metal5", [(x_vdrv_sp, y_vdrv_lo), (x_vdrv_sp, y_vdrv_hi)], 2.400)
    for y_vs, row_cxs in ((y_vdrv_t, top_cxs), (y_vdrv_b, bot_cxs)):
        c.wire("metal5", [(x_vdrv_sp, y_vs), (row_cxs[-1], y_vs)], 2.400)
        for sidx in (0, 4, 8, 11, 13):
            via4_array(c, row_cxs[sidx], y_vs, nx=1, ny=1)

    # Heavy VDD distribution (M3+M4+M5): Xldo.vdd (85.40) -> Top M5 (89.00) -> East M5 spine (229.4)
    # + Bot-slice M5 (40.20) + West-CMOS M5 (91.4) + East M2/M3 CMOS feed!
    y_vdd_t = grid(y_row_t + smeta["y_vdd_drv"])  # 89.000
    y_vdd_b = grid(y_row_b - smeta["y_vdd_drv"])  # 40.200
    x_vdd_sp = 88.200
    x_vdd_m5_e = grid(x_pad_out - 1.600)          # 229.400 (width 2.0 -> [228.4..230.4], 2.0 um clear of pad_p M5!)
    # West M4+M5 join Xldo.vdd (85.40) -> y_vdd_t (89.00) with clean notch-free solid M5 corner rect
    c.wire("metal4", [ldo_meta["vdd"], (x_vdd_sp, ldo_meta["vdd"][1]), (x_vdd_sp, y_vdd_t)], 1.600)
    via3_array(c, x_vdd_sp, y_vdd_t, nx=2, ny=2)
    c.wire("metal3", [(x_vdd_sp, y_vdd_t), (x_arr_l, y_vdd_t)], 1.200)
    c.rect("metal5", 85.500, grid(ldo_meta["vdd"][1] - 1.100), grid(x_vdd_sp + 1.200), grid(y_vdd_t + 1.200))
    via4_array(c, x_vdd_sp, y_vdd_t, nx=1, ny=1)
    # Full-width Top-slice VDD M5 over-strap (88.2 -> 229.4, width 2.40 flush with via4_array -> 0 notches!)
    c.wire("metal5", [(x_vdd_sp, y_vdd_t), (x_vdd_m5_e, y_vdd_t)], 2.400)
    for sidx in (0, 4, 8, 11, 13):
        cx = top_cxs[sidx]
        via3_array(c, cx, y_vdd_t, nx=2, ny=2)
        via4_array(c, cx, y_vdd_t, nx=1, ny=1)
    # East outer vertical VDD M5 spine (x = 229.4, y = -0.50 .. y_vdd_t)
    c.wire("metal5", [(x_vdd_m5_e, -0.500), (x_vdd_m5_e, y_vdd_t)], 2.400)
    # Bot-slice VDD M5 over-strap (91.4 -> 216.8, right edge 218.0 -> 2.0 um clear of x_vss_m5_e=221.0!),
    # stitched every 3-4 slices and bridged cleanly on M3+M4 under x_vss_m5_e into x_vdd_m5_e=229.4!
    x_vdd_cmos_w = 91.400          # Strictly West of CMOS cells & router (x>=94) AND 2.2 um clear of x_vss_m5_w=86.8!
    x_vdd_b_m5_r = 215.800         # right edge 217.0 -> 1.80 um clear of widened 3.6 um East M5 VSS spine [218.8..222.4]!
    c.wire("metal5", [(x_vdd_cmos_w, y_vdd_b), (x_vdd_b_m5_r, y_vdd_b)], 2.400)
    for sidx in (0, 4, 8, 11, 13):
        cx = bot_cxs[sidx]
        via3_array(c, cx, y_vdd_b, nx=2, ny=2)
        via4_array(c, cx, y_vdd_b, nx=1, ny=1)
    # East M3/M4 bridge under x_vss_m5_e (221.0) -> x_vdd_m5_e (229.4), plus East M2 spine at x_vdd_e (222.8, strictly East of 221.0!)
    c.wire("metal3", [(x_arr_r, y_vdd_t), (x_vdd_e, y_vdd_t), (x_vdd_e, y_vdd_b)], 1.200)
    c.wire("metal3", [(x_arr_r, y_vdd_b), (x_vdd_e, y_vdd_b)], 1.200)
    via3_array(c, x_vdd_e, y_vdd_b, nx=2, ny=2)
    c.wire("metal4", [(x_vdd_e, y_vdd_b), (x_vdd_m5_e, y_vdd_b)], 1.600)
    via4_array(c, x_vdd_m5_e, y_vdd_b, nx=1, ny=1)
    for vx_off in (-0.300, +0.300):
        via2_clean(c, grid(x_vdd_e + vx_off), y_vdd_b)
    c.wire("metal2", [(x_vdd_e, y_r0_vdd), (x_vdd_e, y_vdd_b)], 1.400)
    c.wire("metal2", [(x_r0_r, y_r0_vdd), (x_vdd_e, y_r0_vdd)], 1.000)
    c.wire("metal2", [(x_cmos_r, y_r1_vdd), (x_vdd_e, y_r1_vdd)], 1.000)
    # West-CMOS VDD M5 spine (x=91.4, y=13.2..40.2) + full-width CMOS VDD M5 over-straps (y=13.2, 31.2)!
    c.wire("metal5", [(x_vdd_cmos_w, y_r0_vdd), (x_vdd_cmos_w, y_vdd_b)], 2.200)
    cmos_vdd_pillars: list[tuple[float, float]] = []
    for y_rv, xs_st in (
        (y_r0_vdd, (113.8, 197.0)),
        (y_r1_vdd, (113.8, 158.9, 198.6)),
    ):
        c.wire("metal5", [(x_vdd_cmos_w, y_rv), (x_vdd_b_m5_r, y_rv)], 2.200)
        via4_array(c, x_vdd_cmos_w, y_rv, nx=1, ny=1)
        via3_array(c, x_vdd_cmos_w, y_rv, nx=2, ny=1)
        via2_clean(c, x_vdd_cmos_w, y_rv)
        c.wire("metal2", [(x_vdd_cmos_w, y_rv), (x_cmos_l, y_rv)], 0.960)
        for xs in xs_st:
            via4_array(c, xs, y_rv, nx=1, ny=1)
            via3_array(c, xs, y_rv, nx=2, ny=1)
            for dxv in (-0.300, +0.300):
                via2_clean(c, grid(xs + dxv), y_rv)
            cmos_vdd_pillars.append((xs, y_rv))

    # Heavy VSS distribution (M3+M4+M5):
    #   * Bottom M5 trunk (y=1.50, collinear with Xldo y_vss_m5=1.50) across x=[86.5..221.0]!
    #   * West M5 spine (x=87.0, 1.80 um wide -> 1.80 um clear of vdrv M5 89.9!) y=[1.50..70.60]
    #   * East M5 spine (x=221.0, 2.00 um wide -> 2.00 um clear of pad_p M5 224.0!) y=[1.50..74.20]
    #   * Two full-width slice-array Power-VSS M5 over-straps at y=74.20 (Top) and y=55.00 (Bot),
    #     stitched down to y_vss_pt (75.60) / y_vss_pb (53.60) M3 at 6 slices!
    y_vss_pt = grid(y_row_t + smeta["y_vss_pwr"])  # 75.600
    y_vss_dt = grid(y_row_t + smeta["y_vss_drv"])  # 81.600
    y_vss_pb = grid(y_row_b - smeta["y_vss_pwr"])  # 53.600
    y_vss_db = grid(y_row_b - smeta["y_vss_drv"])  # 47.600
    y_vss_m5_bot = ldo_meta["y_vss_m5"]            # 1.500
    y_vss_m5_t = grid(y_vss_pt - 1.400)            # 74.200 (2.25 um clear of vdrv_t M5 77.35!)
    y_vss_m5_b = grid(y_vss_pb + 1.400)            # 55.000 (2.25 um clear of vdrv_b M5 51.85!)
    x_vss_sp = 88.200
    x_vss_m5_w = 86.800
    x_vss_m5_e = 220.600           # width 3.60 -> [218.8..222.4], 1.80 um clear of vdd_b (217.0) & 1.90 um clear of pad_p (224.3)!

    # West M3 spine + M3 bridges under vdrv into all 4 slice VSS rows (width 1.30 keeps >=0.37 um from mp/mn M3 underpass!)
    c.wire("metal3", [(x_vss_sp, y_vss_m5_bot), (x_vss_sp, y_vss_dt)], 2.000)
    c.wire("metal3", [(x_vss_sp, y_r0_vss), (x_pwr_l, y_r0_vss)], 1.200)
    for yv, wv in ((y_vss_db, 1.200), (y_vss_pb, 1.300), (y_vss_pt, 1.300), (y_vss_dt, 1.200)):
        c.wire("metal3", [(x_vss_sp, yv), (x_arr_l, yv)], wv)

    # Bottom + West + East M5 VSS frame + full-width CMOS VSS M5 over-straps (y_r0_vss=3.0, y_r1_vss=21.0)!
    c.rect("metal5", grid(ldo_meta["x_east_edge"] - 0.800), grid(y_vss_m5_bot - 1.200), grid(x_vss_m5_e + 1.800), grid(y_r0_vss + 1.200))
    c.wire("metal5", [(x_vss_m5_w, y_vss_m5_bot), (x_vss_m5_w, 70.600)], 2.400)
    c.wire("metal5", [(x_vss_m5_e, y_vss_m5_bot), (x_vss_m5_e, y_vss_m5_t)], 3.600)
    c.wire("metal5", [(95.600, y_r1_vss), (x_vss_m5_e, y_r1_vss)], 2.200)
    cmos_vss_pillars: list[tuple[float, float]] = []
    # Continuous low-R M3 strap + continuous 0.80 um-pitched via2 along y_r0_vss (x=113.8..220.6) + 15 M5->M3 pillars!
    # Slashes M2<->M5 vertical resistance from 3.3 ohm to <0.25 ohm so R_pd RCX delta <= 0.8 ohm across all 6 corners!
    r0_vss_pillars = (
        113.8, 124.0, 134.0, 140.0, 146.0, 152.0, 158.9,
        164.0, 170.0, 178.0, 185.0, 193.0, 201.0, 209.0, 215.5,
    )
    r1_vss_pillars = (100.0, 113.8, 158.9, 185.0, 192.0, 198.6, 206.5, 214.0)
    c.wire("metal3", [(r0_vss_pillars[0], y_r0_vss), (x_vss_m5_e, y_r0_vss)], 0.960)
    c.wire("metal3", [(95.600, y_r1_vss), (x_vss_m5_e, y_r1_vss)], 0.760)
    # Continuous 0.80 um-pitched via2 stitching along BOTH y_r0_vss AND y_r1_vss M2 <-> M3!
    for y_rv_v2, x_start_v2 in ((y_r0_vss, r0_vss_pillars[0]), (y_r1_vss, 95.600)):
        n_v2 = int((x_vss_m5_e - x_start_v2) // 0.80)
        for iv2 in range(n_v2 + 1):
            via2_clean(c, grid(x_start_v2 + iv2 * 0.800), y_rv_v2)
    for y_rv, xs_st in (
        (y_r0_vss, r0_vss_pillars),
        (y_r1_vss, r1_vss_pillars),
    ):
        for xs in xs_st:
            is_open_m4 = (y_rv == y_r0_vss and (xs <= 125.0 or xs >= 177.0))
            via4_array(c, xs, y_rv, nx=2 if is_open_m4 else 1, ny=1)
            via3_array(c, xs, y_rv, nx=3 if (is_open_m4 or y_rv == y_r1_vss) else 2, ny=2 if y_rv == y_r0_vss else 1)
            cmos_vss_pillars.append((xs, y_rv))

    # Stitch West M5 spine (x=86.8) to West M3 spine (x=88.2) at y=1.50, 21.00, 47.60, 53.60, 68.80 with dual via4 + 2x3 via3!
    for y_st in (y_vss_m5_bot, y_r1_vss, y_vss_db, y_vss_pb, 68.800):
        via4_array(c, x_vss_m5_w, y_st, nx=1, ny=2 if y_st in (y_vss_pb, 68.800) else 1)
        c.wire("metal4", [(x_vss_m5_w, y_st), (x_vss_sp, y_st)], 2.200 if y_st in (y_vss_pb, 68.800) else 1.600)
        via3_array(c, x_vss_sp, y_st, nx=2, ny=3 if y_st in (y_vss_pb, 68.800) else 2)
    # Tie East ends of Row 0 & Row 1 CMOS VSS M2 directly into East M5 VSS spine (x=220.6, strictly West of x_vdd_e=222.8!)
    for y_rv, x_end_r in ((y_r0_vss, x_r0_r), (y_r1_vss, x_cmos_r)):
        c.wire("metal2", [(x_end_r, y_rv), (x_vss_m5_e, y_rv)], 0.960)
        for dxv in (-0.420, 0.000, +0.420):
            via2_clean(c, grid(x_vss_m5_e + dxv), y_rv)
        via3_array(c, x_vss_m5_e, y_rv, nx=2, ny=2)
        via4_array(c, x_vss_m5_e, y_rv, nx=2, ny=1)

    # Slice-array Power-VSS M5 over-straps (x=100.4 .. 221.0, strictly clear of x_mn_v=94.7!) stitched at ALL 14 slices!
    for y_m5_s, y_m3_s, row_cxs in (
        (y_vss_m5_t, y_vss_pt, top_cxs),
        (y_vss_m5_b, y_vss_pb, bot_cxs),
    ):
        c.wire("metal5", [(row_cxs[0], y_m5_s), (x_vss_m5_e, y_m5_s)], 2.400)
        for cx in row_cxs:
            via4_array(c, cx, y_m5_s, nx=2, ny=1)
            c.wire("metal4", [(cx, min(y_m5_s, y_m3_s)), (cx, max(y_m5_s, y_m3_s))], 1.600)
            via3_array(c, cx, y_m3_s, nx=2, ny=2)

    # ------------------------------------------------------------------
    # 5. Connect Bank Enables (m0..m4, f0..f2) & mp/mn/fp/fn Data Buses
    # ------------------------------------------------------------------
    # Top Row enables (y_en_t = 86.25) -> clean M3 buses at y = 87.40 -> North perimeter M4 pins (y = 89.20)!
    y_en_t = grid(y_row_t + smeta["y_en_pin"])
    y_en_t_bus = grid(y_en_t + 1.150)
    y_north_port = grid(y_en_t_bus + 1.800)
    top_banks = [
        ("m3", top_cxs[0:8]),
        ("m2", top_cxs[8:12]),
        ("f2", top_cxs[12:14]),
    ]
    top_en_ports: dict[str, tuple[float, float]] = {}
    for bnm, cxs in top_banks:
        for cx in cxs:
            c.wire("metal2", [(cx, y_en_t), (cx, y_en_t_bus)], 0.320)
            via2_clean(c, cx, y_en_t_bus)
        if len(cxs) > 1:
            c.wire("metal3", [(cxs[0], y_en_t_bus), (cxs[-1], y_en_t_bus)], 0.400)
        px = cxs[len(cxs) // 2]
        via3_pad(c, px, y_en_t_bus)
        c.wire("metal4", [(px, y_en_t_bus), (px, y_north_port)], 0.440)
        top_en_ports[bnm] = (px, y_north_port)

    # Bottom Row enables (y_en_b = 35.75) -> clean M3 buses at y = 34.60 -> route to East perimeter!
    y_en_b = grid(y_row_b - smeta["y_en_pin"])
    y_en_b_bus = grid(y_en_b - 1.150)
    bot_banks = [
        ("m4", bot_cxs[0:8]),
        ("m1", bot_cxs[8:10]),
        ("m0", bot_cxs[10:11]),
        ("f1", bot_cxs[11:13]),
        ("f0", bot_cxs[13:14]),
    ]
    bot_en_pins: dict[str, tuple[float, float]] = {}
    for bnm, cxs in bot_banks:
        for cx in cxs:
            c.wire("metal2", [(cx, y_en_b_bus), (cx, y_en_b)], 0.320)
            via2_clean(c, cx, y_en_b_bus)
        if len(cxs) > 1:
            c.wire("metal3", [(cxs[0], y_en_b_bus), (cxs[-1], y_en_b_bus)], 0.400)
        bot_en_pins[bnm] = (cxs[-1], y_en_b_bus)

    # Connect mp/mn (Main slices) and fp/fn (Post slices) between Row T and Row B on vertical M4/M3 straps!
    y_dinp_b = grid(y_row_b - smeta["y_din_p"])   # 41.400
    y_dinn_b = grid(y_row_b - smeta["y_din_n"])   # 40.400
    y_dinp_t = grid(y_row_t + smeta["y_din_p"])   # 80.600
    y_dinn_t = grid(y_row_t + smeta["y_din_n"])   # 81.600

    x_mp_v, x_mn_v = 93.400, 94.700
    for xv, yb, yt, nm in ((x_mp_v, y_dinp_b, y_dinp_t, "mp"), (x_mn_v, y_dinn_b, y_dinn_t, "mn")):
        c.wire("metal3", [(xv, yb), (x_arr_l, yb)], 0.360)
        c.wire("metal3", [(xv, yt), (x_arr_l, yt)], 0.360)
        # Run vertically on M4, with clean 3.0 um M3 underpasses underneath the two vdrv M4 arms (y_vdrv_b, y_vdrv_t)!
        y_b_lo, y_b_hi = grid(y_vdrv_b - 1.500), grid(y_vdrv_b + 1.500)
        y_t_lo, y_t_hi = grid(y_vdrv_t - 1.500), grid(y_vdrv_t + 1.500)
        via3_pad(c, xv, yb)
        c.wire("metal4", [(xv, yb), (xv, y_b_lo)], 0.440)
        via3_pad(c, xv, y_b_lo)
        c.wire("metal3", [(xv, y_b_lo), (xv, y_b_hi)], 0.400)
        via3_pad(c, xv, y_b_hi)
        c.wire("metal4", [(xv, y_b_hi), (xv, y_t_lo)], 0.440)
        via3_pad(c, xv, y_t_lo)
        c.wire("metal3", [(xv, y_t_lo), (xv, y_t_hi)], 0.400)
        via3_pad(c, xv, y_t_hi)
        c.wire("metal4", [(xv, y_t_hi), (xv, yt)], 0.440)
        via3_pad(c, xv, yt)
        all_nets.setdefault(nm, []).append((xv, yb, "metal4"))

    # Post slices: connect East edge of Row B & Row T (x_arr_r) via M4 bridge over x_vdd_e -> vertical M3 at x_fp_v/x_fn_v!
    # Run vertical M3 down underneath y_vdd_b M4 (40.20) to y=38.30 (above Band 1-A enables <=37.40 & clear of vdd M4 >=39.40)!
    for xv, yb, yt, nm in (
        (x_fp_v, y_dinp_b, y_dinp_t, "fp"),
        (x_fn_v, y_dinn_b, y_dinn_t, "fn"),
    ):
        for y_row_din in (yb, yt):
            via3_pad(c, grid(x_arr_r + 0.500), y_row_din)
            c.wire("metal3", [(x_arr_r, y_row_din), (grid(x_arr_r + 0.500), y_row_din)], 0.520)
            c.wire("metal4", [(grid(x_arr_r + 0.500), y_row_din), (xv, y_row_din)], 0.440)
            via3_pad(c, xv, y_row_din)
        c.wire("metal3", [(xv, 38.300), (xv, yt)], 0.400)
        all_nets.setdefault(nm, []).append((xv, 38.300, "metal3"))

    # ------------------------------------------------------------------
    # 6. Route ALL Remaining CMOS Interconnects via ManhattanRouter (Inter-row + Over-Cell M3)
    # ------------------------------------------------------------------
    # Pin-free M3 bands (0.90 um pitch, widened for separated 1.80 um double-spaced p0..p3 & pb0..pb3!):
    #   * Band S   (South + Row 0 NMOS diff):       y in [0.5..5.9]   (Row 0 pins at y in [7.0..9.0])
    #   * Band 0-1 (Row 0 PMOS + Ch0-1 + Row 1 NMOS): y in [10.4..23.9] (16 tracks; Row 1 pins at [25.0..27.0])
    #   * Band 1-A (Row 1 PMOS + Ch1-Arr):          y in [28.4..37.4] (11 tracks; y_en_b_bus = 38.20!)
    m3_tracks = [grid(0.500 + 0.900 * k) for k in range(42)]
    pref_tracks = {
        yt for yt in m3_tracks
        if (0.5 <= yt <= 5.95) or (10.3 <= yt <= 24.0) or (28.3 <= yt <= 37.5)
    }
    router = ManhattanRouter(m3_tracks, m4_min_pitch=0.960, preferred_tracks=pref_tracks)

    # South perimeter ports aligned directly below their receiver spans:
    #   * phi0..phi270 at 97..109 (4.0 um pitch, directly under Xpg West)
    #   * d0..d3 at 131..149 and db0..db3 at 155..173 (6.0 um pitch, strictly inside [Xmux_m..Xmux_f] span!)
    y_south_port = -0.400
    south_port_xs = {
        "phi0":    97.000,
        "phi90":  101.000,
        "phi180": 105.000,
        "phi270": 109.000,
        "d0":     131.000,
        "d1":     137.000,
        "d2":     143.000,
        "d3":     149.000,
        "db0":    155.000,
        "db1":    161.000,
        "db2":    167.000,
        "db3":    173.000,
    }
    south_ports: dict[str, tuple[float, float]] = {}
    for pnm, px in south_port_xs.items():
        px = grid(px)
        south_ports[pnm] = (px, y_south_port)
        all_nets.setdefault(pnm, []).append((px, y_south_port, "metal4"))

    # East perimeter ports for bottom-row enables (ffe_en, m4, m1, m0, f1, f0):
    east_en_order = ["ffe_en", "m4", "m1", "m0", "f1", "f0"]
    east_en_ports: dict[str, tuple[float, float]] = {}
    x_fan_m4 = grid(x_fp_v + 1.000)   # 229.400
    x_fan_m1 = grid(x_fp_v + 2.000)   # 230.400
    east_route_spec = {
        "ffe_en": (x_pad_out, 37.400, 37.400),
        "m4":     (x_fan_m4,  34.700, 24.300),
        "m1":     (x_fan_m1,  35.600, 26.500),
        "m0":     (x_pad_out, 36.500, 36.500),
        "f1":     (x_pad_out, 32.000, 32.000),
        "f0":     (x_pad_out, 31.100, 31.100),
    }
    # Separate p0..p3 (Band 0-1, 1.80 um double-spaced; zero pb0..pb3 in v4.3 pure static CMOS MUX!)
    pref_y_map: dict[str, float] = {
        "fp": 30.200,
        "fn": 29.300,
        "mp": 36.500,
        "mn": 35.600,
        "p0": 17.600,
        "p1": 19.400,
        "p2": 22.100,
        "p3": 23.900,
    }
    for enm in east_en_order:
        x_end, y_trk, y_port = east_route_spec[enm]
        if enm != "ffe_en":
            bx, by = bot_en_pins[enm]
            all_nets.setdefault(enm, []).append((bx, by, "metal3"))
        all_nets.setdefault(enm, []).append((x_end, y_trk, "metal3"))
        east_en_ports[enm] = (x_pad_out, y_port)
        pref_y_map[enm] = y_trk
    for nm in ("phi0", "phi90", "phi180", "phi270"):
        pref_y_map[nm] = 2.300
    for idx_d, nm in enumerate(("d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3")):
        pref_y_map[nm] = grid(10.400 + idx_d * 0.900)

    # Reserve M3 power spines, CMOS M5-to-M2 pillars & bridges so router stays clear of VSS/VDD M3/M4!
    router.reserve_m3_span(y_en_b_bus, x_arr_l, x_arr_r, "__en_b_bus__")
    for yt in m3_tracks:
        if abs(yt - y_r0_vss) <= 0.900:
            router.reserve_m3_span(yt, grid(r0_vss_pillars[0] - 1.000), grid(x_vss_m5_e + 1.000), "__r0_vss_m3__")
        if abs(yt - y_r1_vss) <= 0.900:
            router.reserve_m3_span(yt, 94.800, grid(x_vss_m5_e + 1.000), "__r1_vss_m3__")
    for xp, yp in cmos_vdd_pillars + cmos_vss_pillars:
        for yt in m3_tracks:
            if abs(yt - yp) <= 0.900:
                router.reserve_m3_span(yt, grid(xp - 1.100), grid(xp + 1.100), "__cmos_pwr__")
        for dx_r in (-0.800, 0.000, +0.800):
            router.reserve_m4_seg(grid(xp + dx_r), grid(yp - 1.100), grid(yp + 1.100), "__cmos_pwr__")
    for y_rv in (y_r0_vss, y_r1_vss):
        for dy_r in (-0.60, 0.0, +0.60):
            router.reserve_m3_span(grid(y_rv + dy_r), grid(x_vss_m5_e - 1.20), grid(x_vss_m5_e + 1.20), "__vss_e__")
        for dx_r in (-0.80, 0.0, +0.80):
            router.reserve_m4_seg(grid(x_vss_m5_e + dx_r), grid(y_rv - 1.20), grid(y_rv + 1.20), "__vss_e__")
    for yt in m3_tracks:
        if y_r0_vss - 0.8 <= yt <= y_r1_vss + 0.8:
            router.reserve_m3_pad(x_pwr_l, yt, "__vss_l__")
        if yt >= y_vdd_b - 0.8:
            router.reserve_m3_pad(x_vdd_e, yt, "__vdd_e__")
    router.reserve_m4_seg(x_mp_v, y_dinp_b, y_dinp_t, "mp")
    router.reserve_m4_seg(x_mn_v, y_dinn_b, y_dinn_t, "mn")
    router.reserve_m4_seg(x_fan_m4, 24.300, 34.700, "m4")
    router.reserve_m4_seg(x_fan_m1, 26.500, 35.600, "m1")
    router.reserve_m3_span(24.300, x_fan_m4, x_pad_out, "m4")
    router.reserve_m3_span(26.500, x_fan_m1, x_pad_out, "m1")
    router.pre_register_nets(all_nets)

    # Route East/Band 1-A nets first, then South-port M4 nets (d0..db3 in 10.4..16.7), then p0..p3 (18.5..23.9) & pb0..pb3 (28.4..33.8)!
    east_set = set(east_en_order) | {"mp", "mn", "fp", "fn"}
    net_order = sorted(
        all_nets.items(),
        key=lambda kv: (
            0 if kv[0] in east_set else (1 if any(p[2] == "metal4" for p in kv[1]) else 2),
            max(p[0] for p in kv[1]) - min(p[0] for p in kv[1]),
        ),
    )
    routed_ys: dict[str, float] = {}
    for net_name, plist in net_order:
        routed_ys[net_name] = router.route_net(c, net_name, plist, pref_y=pref_y_map.get(net_name))

    # Draw clean East fanout drops for m4 and m1 East of x_fp_v!
    for enm in ("m4", "m1"):
        x_fan, y_trk, y_port = east_route_spec[enm]
        via3_pad(c, x_fan, y_trk)
        c.wire("metal4", [(x_fan, y_port), (x_fan, y_trk)], 0.440)
        via3_pad(c, x_fan, y_port)
        c.wire("metal3", [(x_fan, y_port), (x_pad_out, y_port)], 0.400)

    # ------------------------------------------------------------------
    # 7. Export Exact 27 Perimeter Ports (Exact Schematic Subckt Order!)
    # ------------------------------------------------------------------
    port_locs = {
        **{k: ("metal4", *south_ports[k]) for k in ("d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3", "phi0", "phi90", "phi180", "phi270")},
        "m0": ("metal3", *east_en_ports["m0"]),
        "m1": ("metal3", *east_en_ports["m1"]),
        "m2": ("metal4", *top_en_ports["m2"]),
        "m3": ("metal4", *top_en_ports["m3"]),
        "m4": ("metal3", *east_en_ports["m4"]),
        "f0": ("metal3", *east_en_ports["f0"]),
        "f1": ("metal3", *east_en_ports["f1"]),
        "f2": ("metal4", *top_en_ports["f2"]),
        "ffe_en": ("metal3", *east_en_ports["ffe_en"]),
        "vbg":  ("metal2", *ldo_meta["vbg"]),
        "pad_p": ("metal4", x_pad_out, y_padp_t),
        "pad_n": ("metal4", x_pad_out, y_seam),
        "vdrv": ("metal5", x_vdrv_sp, y_vdrv_t),
        "vdd":  ("metal5", x_vdd_sp, y_vdd_t),
        "vss":  ("metal5", ldo_meta["vss"][0], y_vss_m5_bot),
    }

    if add_ports:
        order = [
            "d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3",
            "phi0", "phi90", "phi180", "phi270",
            "m0", "m1", "m2", "m3", "m4", "f0", "f1", "f2", "ffe_en",
            "vbg", "pad_p", "pad_n", "vdrv", "vdd", "vss",
        ]
        for pnm in order:
            lyr, px, py = port_locs[pnm]
            c.port(pnm, lyr, px, py)

    return c, {
        "ports": port_locs,
        "south_ports": south_ports,
        "x_cmos0": x_cmos0,
        "x_pad_out": x_pad_out,
        "x_vdd_e": x_vdd_e,
        "x_vdd_m5_e": x_vdd_m5_e,
        "y_r2_vdd": y_r1_vdd,
        "y_r1_vdd": y_r1_vdd,
        "x_vdd_sp": x_vdd_sp,
        "x_vdrv_sp": x_vdrv_sp,
        "y_vss_m5_bot": y_vss_m5_bot,
        "y_north_port": y_north_port,
        "y_vdd_t": y_vdd_t,
        "y_vdrv_t": y_vdrv_t,
    }


if __name__ == "__main__":
    import json
    work = slc.REPO / "results/layout/tx_sst_v4/test_driver"
    cache = PdkCache(work / "_cache")
    cell, meta = build_sst_driver(cache, add_ports=True)
    name = "serdes_tx_sst_driver_pdk"
    mag = work / f"{name}.mag"
    ref = work / f"{name}_ref.spice"
    cell.write(mag)
    ports = slc.generate_ref_spice("serdes_tx_sst_driver", name, ref)
    rep = slc.verify_flat_cell(work, name, mag, ref, ports, timeout_s=180)
    print(json.dumps({k: v for k, v in rep.items() if k != "parasitics"}, indent=2))
    if rep["parasitics"]:
        pc = rep["parasitics"].get("port_caps_fF", {})
        print("Key port caps (fF):", json.dumps({k: pc[k] for k in ("pad_p", "pad_n", "vdrv", "vdd", "phi0") if k in pc}, indent=2))
