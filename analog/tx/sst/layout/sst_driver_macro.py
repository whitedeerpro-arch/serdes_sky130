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
    """Build `sst_pulsegen_4ph` on a single `ROW_DRV` row with local M1/M2 routing for `b0..b270` and `c0..c270`."""
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}
    b_pins: dict[str, list[tuple[float, float]]] = {}
    c_left_pins: dict[str, list[tuple[float, float]]] = {}
    c_right_pins: dict[str, list[tuple[float, float]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    x = 0.0
    # Stage 1: input sharpening inverters Xi0..Xi27 + cross-coupled alignment Xcc1a/b
    for ph, bnet in (("phi0", "b0"), ("phi90", "b90"), ("phi180", "b180"), ("phi270", "b270")):
        u, x = scc.place_inv(c, cache, row, x, 2.5, 5.0, 1, 2, gap_l=1.200, trk_g=2)
        add_pin(ph, u["a"])
        b_pins.setdefault(bnet, []).append(u["y"])
    for a, b in (("b0", "b180"), ("b90", "b270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.6, 1.2, gap_l=1.200)
        b_pins.setdefault(a, []).append(u["ap"])
        b_pins.setdefault(b, []).append(u["an"])

    # Stage 2: restore polarity Xj0..Xj27 + Xcc2a/b
    for bnet, cnet in (("b0", "c0"), ("b90", "c90"), ("b180", "c180"), ("b270", "c270")):
        u, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 4, gap_l=1.200, trk_g=2)
        b_pins.setdefault(bnet, []).append(u["a"])
        c_left_pins.setdefault(cnet, []).append(u["y"])
    for a, b in (("c0", "c180"), ("c90", "c270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.8, 1.6, gap_l=1.200)
        c_left_pins.setdefault(a, []).append(u["ap"])
        c_left_pins.setdefault(b, []).append(u["an"])

    # Stage 3A: 25%-duty pulse generators Xp0..Xp3 (NOR2)
    for a, b, pnet in (("c90", "c180", "p0"), ("c180", "c270", "p1"), ("c270", "c0", "p2"), ("c0", "c90", "p3")):
        u, x = scc.place_nor2(c, cache, row, x, 2.8, 12.0, 2, 4, gap_l=0.920, trk_a=0, trk_b=4)
        c_left_pins.setdefault(a, []).append(u["a"])
        c_left_pins.setdefault(b, []).append(u["b"])
        add_pin(pnet, u["y"])

    # Open 2.90 um M1/M2 bridge corridor between Xp3 (NOR2) and Xpb0 (NAND2) to transition c0..c270
    # from the PMOS diff band (M1-free over NOR2) to the NMOS diff band (M1-free over NAND2)!
    x_bridge_base = x
    for idx, (a, b, pbnet) in enumerate((("c0", "c270", "pb0"), ("c90", "c0", "pb1"), ("c180", "c90", "pb2"), ("c270", "c180", "pb3"))):
        u, x = scc.place_nand2(c, cache, row, x, 6.0, 5.0, 2, 2, gap_l=(2.900 if idx == 0 else 0.920), trk_a=0, trk_b=4)
        c_right_pins.setdefault(a, []).append(u["a"])
        c_right_pins.setdefault(b, []).append(u["b"])
        add_pin(pbnet, u["y"])

    for pnet, pbnet in (("p0", "pb0"), ("p1", "pb1"), ("p2", "pb2"), ("p3", "pb3")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.7, 1.4, gap_l=0.920)
        add_pin(pnet, u["ap"], "metal2")
        add_pin(pbnet, u["an"])

    # Local M1+M2 routing for b0..b270 over the unused NMOS diff band (y = 0.85, 1.45, 2.05, 2.65)
    y_b_tracks = {"b0": 0.850, "b90": 1.450, "b180": 2.050, "b270": 2.650}
    for bnet, yb in y_b_tracks.items():
        pts = sorted(b_pins[bnet], key=lambda p: p[0])
        for px, py in pts:
            c.wire("metal1", [(px, yb), (px, py)], slc.W_M1)
            c.via1(px, yb)
        c.wire("metal2", [(pts[0][0], yb), (pts[-1][0], yb)], 0.240)

    # Local M1+M2 routing for c0..c270:
    #   * Left half (Xj, Xcc2, Xp0..3 NOR2): PMOS diff band M2 (y = 7.20, 7.72, 8.24, 8.76)
    #   * Bridge corridor (x_bridge_base + 0.50 + k*0.52): vertical M1 hop PMOS band -> NMOS band
    #   * Right half (Xpb0..3 NAND2): NMOS diff band M2 (y = 1.20, 1.72, 2.24, 2.76)
    c_spec = [
        ("c0",   7.200, 1.200),
        ("c90",  7.720, 1.720),
        ("c180", 8.240, 2.240),
        ("c270", 8.760, 2.760),
    ]
    for k, (cnet, yp, yn) in enumerate(c_spec):
        xbr = grid(x_bridge_base + 0.500 + k * 0.520)
        lpts = sorted(c_left_pins[cnet], key=lambda p: p[0])
        for px, py in lpts:
            c.wire("metal1", [(px, py), (px, yp)], slc.W_M1)
            c.via1(px, yp)
        c.via1(xbr, yp)
        c.wire("metal2", [(lpts[0][0], yp), (xbr, yp)], 0.220)

        # Vertical M1 bridge in open corridor
        c.wire("metal1", [(xbr, yn), (xbr, yp)], slc.W_M1)
        c.via1(xbr, yn)

        rpts = sorted(c_right_pins[cnet], key=lambda p: p[0])
        for px, py in rpts:
            c.wire("metal1", [(px, yn), (px, py)], slc.W_M1)
            c.via1(px, yn)
        c.wire("metal2", [(xbr, yn), (rpts[-1][0], yn)], 0.220)

    return c, nets, x


def _build_mux4_row(
    cache: PdkCache,
    scale: float,
    tag: str,
    d_names: tuple[str, str, str, str],
    db_names: tuple[str, str, str, str],
    en_net: str,
    out_p_net: str,
    out_n_net: str,
) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build `sst_mux4_predrv(scale=...)` on a single `ROW_DRV` row with local M1/M2 `mux_p`/`mux_n` buses."""
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    x = 0.0
    y2 = row.y_tracks[2]
    # 1+2. Interleaved stiff 1 GHz data drivers + 4:1 transmission gates
    # Route mux_p completely locally on NMOS-edge M2 (y_mux_p = y_nb = 3.260, zero vertical M1 over tgate PMOS!)
    # and mux_n on lower NMOS-band M2 (y_mux_n = 1.980):
    #   * Clear of tgate y_na and NAND2 y_mid in BOTH scale=1.0 and scale=0.45!
    #   * Eliminates all M3/M4 router tracks for mux_p/mux_n!
    wn_b, wp_b = grid(2.4 * scale), grid(4.8 * scale)
    wn_t, wp_t = grid(2.4 * scale), grid(4.0 * scale)
    y_mux_p = grid(row.y_n_top - 0.240)  # 3.260
    y_mux_n = 1.980
    mux_p_xs: list[float] = []
    mux_n_xs: list[float] = []
    for k in range(4):
        ub, x = scc.place_inv(c, cache, row, x, wn_b, wp_b, 1, 2, gap_l=0.920, trk_g=2)
        ut, x = scc.place_tgate(c, cache, row, x, wn_t, wp_t, 1, 2, gap_l=0.960)
        c.wire("metal1", [(ub["y_col_x"], y2), (ut["a"][0], y2)], slc.W_M1)
        c.via1(ut["b"][0], y_mux_p)
        mux_p_xs.append(ut["b"][0])
        add_pin(db_names[k], ub["a"])
        add_pin(f"p{k}", ut["p"])
        add_pin(f"pb{k}", ut["pb"])

    for k in range(4):
        ub, x = scc.place_inv(c, cache, row, x, wn_b, wp_b, 1, 2, gap_l=0.920, trk_g=2)
        ut, x = scc.place_tgate(c, cache, row, x, wn_t, wp_t, 1, 2, gap_l=0.960)
        c.wire("metal1", [(ub["y_col_x"], y2), (ut["a"][0], y2)], slc.W_M1)
        c.wire("metal1", [(ut["b"][0], y_mux_n), (ut["b"][0], y_mux_p)], slc.W_M1)
        c.via1(ut["b"][0], y_mux_n)
        mux_n_xs.append(ut["b"][0])
        add_pin(d_names[k], ub["a"])
        add_pin(f"p{k}", ut["p"])
        add_pin(f"pb{k}", ut["pb"])

    # 3. Cross-coupled keeper Xccm -> tap straight into local mux_p (y=3.26) and mux_n (y=1.98) M2 buses!
    wn_k = max(0.45, grid(0.45 * scale))
    wp_k = max(0.90, grid(0.90 * scale))
    ucc, x = scc.place_cc_align(c, cache, row, x, wn_k, wp_k, gap_l=0.720)
    c.wire("metal1", [(ucc["ap"][0], y_mux_p), (ucc["ap"][0], ucc["ap"][1])], slc.W_M1)
    c.via1(ucc["ap"][0], y_mux_p)
    c.wire("metal1", [(ucc["an"][0], y_mux_n), (ucc["an"][0], ucc["an"][1])], slc.W_M1)
    c.via1(ucc["an"][0], y_mux_n)

    # 4+5. Stage 1 NAND2 + Stage 2 INV interleaved per leg (trk_a=0, trk_b=4 -> >= 1.00 um M3 clearance!)
    wn_1, wp_1 = grid(5.2 * scale), grid(4.6 * scale)
    wn_2, wp_2 = grid(5.5 * scale), grid(11.0 * scale)
    for leg, onet in (("p", out_p_net), ("n", out_n_net)):
        u1, x = scc.place_nand2(c, cache, row, x, wn_1, wp_1, 2, 2, gap_l=0.920, trk_a=0, trk_b=4)
        u2, x = scc.place_inv(c, cache, row, x, wn_2, wp_2, 2, 3, gap_l=0.920, trk_g=2)
        c.wire("metal1", [(u1["y_col_x"], y2), u2["a"]], slc.W_M1)
        if leg == "p":
            c.wire("metal1", [(u1["a"][0], y_mux_p), (u1["a"][0], u1["a"][1])], slc.W_M1)
            c.via1(u1["a"][0], y_mux_p)
            mux_p_xs.append(u1["a"][0])
        else:
            # Drop on M2 from (u1.a, y=4.0) to y_mux_n=1.98 (strictly East of mux_p end, zero M1 near NAND2 y_mid!)
            c.via1(u1["a"][0], u1["a"][1])
            c.wire("metal2", [(u1["a"][0], y_mux_n), (u1["a"][0], u1["a"][1])], 0.280)
            mux_n_xs.append(u1["a"][0])
        add_pin(en_net, u1["b"])
        add_pin(onet, u2["y"])

    c.wire("metal2", [(min(mux_p_xs), y_mux_p), (max(mux_p_xs), y_mux_p)], 0.280)
    c.wire("metal2", [(min(mux_n_xs), y_mux_n), (max(mux_n_xs), y_mux_n)], 0.280)

    return c, nets, x


def build_sst_driver(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build complete `serdes_tx_sst_driver_pdk` macro (~231.5 x 90.1 um)."""
    c = Cell()
    row = scc.ROW_DRV

    # ------------------------------------------------------------------
    # 1. West Block: Compacted On-Chip V_drv LDO (`Xldo`, x in [0.0..86.5])
    # ------------------------------------------------------------------
    ldo_cell, ldo_meta = sab.build_sst_vdrv_ldo(cache, add_ports=False)
    c.include(ldo_cell, dx=0.0, dy=0.0)

    # ------------------------------------------------------------------
    # 2. East-South Block: 2 Compact High-Speed CMOS Rows (Row 0 = Xpg; Row 1 = Xmux_m || Xmux_f)
    #    Shifted West by 11.00 um to abut tightly against compacted Xldo (xmax = 86.50)!
    # ------------------------------------------------------------------
    x_cmos0 = 95.000
    x_pg0 = 95.500
    y_r0_vss = 3.000                                # Row 0 (Xpg):             VSS=3.00,  VDD=13.20
    y_r0_vdd = grid(y_r0_vss + row.height)          # 13.20
    # Channel 0-1 (6.0 um) + over-cell diff bands = 12.2 um pin-free M3 corridor [10.0..22.2]!
    y_r1_vss = 19.200                               # Row 1 (Xmux_m | Xmux_f): VSS=19.20, VDD=29.40
    y_r1_vdd = grid(y_r1_vss + row.height)          # 29.40

    pg_cell, pg_nets, pg_w = _build_pulsegen_row(cache)
    mm_cell, mm_nets, mm_w = _build_mux4_row(
        cache, 1.0, "mm",
        ("d0", "d1", "d2", "d3"), ("db0", "db1", "db2", "db3"),
        en_net="vdd_en", out_p_net="mp", out_n_net="mn",
    )
    mf_cell, mf_nets, mf_w = _build_mux4_row(
        cache, 0.45, "mf",
        ("db3", "db0", "db1", "db2"), ("d3", "d0", "d1", "d2"),
        en_net="ffe_en", out_p_net="fp", out_n_net="fn",
    )

    # Row 1 horizontal layout under the 124 um slice array [96..220]:
    #   * Xmux_m (mirrored in X) spans [96.64..149.00] -> mp/mn exit right at West edge (97.3, 104.5)!
    #   * Xmux_f (normal)        spans [157.00..208.40] -> fp/fn exit right at East edge (201.5, 208.3)!
    x_mm_r = 149.000
    x_mf_l = 157.000
    x_cmos_l = grid(x_cmos0 - 1.000)                # 94.000
    x_r0_r = grid(x_pg0 + pg_w + 1.500)             # ~188.2
    x_cmos_r = grid(x_mf_l + mf_w + 1.600)          # ~210.0

    scc.finish_cmos_row(pg_cell, row, grid(x_cmos_l - x_pg0), grid(x_r0_r - x_pg0), tap_pitch=10.0)

    # Build Row 1 as one unified continuous-well / continuous-rail cell containing Xmux_m (mirrored) + Xmux_f
    r1_cell = Cell()
    all_nets: dict[str, list[tuple[float, float, str]]] = {}

    def merge_pins(pmap: dict[str, list[tuple[float, float, str]]]) -> None:
        for net, pts in pmap.items():
            all_nets.setdefault(net, []).extend(pts)

    merge_pins(_add_row_transformed(c, pg_cell, pg_nets, x_pg0, y_r0_vss, mirror_y=False, mirror_x=False))
    r1_mm_pins = _add_row_transformed(r1_cell, mm_cell, mm_nets, grid(x_mm_r - x_cmos0), 0.0, mirror_y=False, mirror_x=True)
    r1_mf_pins = _add_row_transformed(r1_cell, mf_cell, mf_nets, grid(x_mf_l - x_cmos0), 0.0, mirror_y=False, mirror_x=False)
    scc.finish_cmos_row(r1_cell, row, grid(x_cmos_l - x_cmos0), grid(x_cmos_r - x_cmos0), tap_pitch=10.0)
    merge_pins(_add_row_transformed(c, r1_cell, r1_mm_pins, x_cmos0, y_r1_vss, mirror_y=False, mirror_x=False))
    merge_pins(_add_row_transformed(c, Cell(), r1_mf_pins, x_cmos0, y_r1_vss, mirror_y=False, mirror_x=False))

    # Tie `vdd_en` (Xmux_m's permanent VDD enable) directly to Row 1's VDD rail (y_r1_vdd = 29.40) on M1/M2!
    for px, py, _ in all_nets.pop("vdd_en", []):
        c.via1(px, py)
        c.via1(px, y_r1_vdd)
        c.wire("metal2", [(px, min(py, y_r1_vdd)), (px, max(py, y_r1_vdd))], 0.280)

    # Strap CMOS power rails (VSS at 3.00, 19.20; VDD at 13.20, 29.40) at West & East edges
    x_pwr_l = grid(x_cmos_l - 0.800)                # 104.200
    x_pwr_r = grid(x_cmos_r + 1.200)                # ~222.200
    for y_vss_r in (y_r0_vss, y_r1_vss):
        c.wire("metal1", [(x_pwr_l, y_vss_r), (x_cmos_l, y_vss_r)], 0.500)
        c.via1(x_pwr_l, y_vss_r)
        via2_clean(c, x_pwr_l, y_vss_r)
    # Row 0 VDD M1 extends east from x_r0_r -> x_pwr_r (no dead wells east of Xpg!); Row 1 VDD extends from x_cmos_r -> x_pwr_r
    c.wire("metal1", [(x_r0_r, y_r0_vdd), (x_pwr_r, y_r0_vdd)], 0.500)
    c.wire("metal1", [(x_cmos_r, y_r1_vdd), (x_pwr_r, y_r1_vdd)], 0.500)
    for y_vdd_r in (y_r0_vdd, y_r1_vdd):
        c.via1(x_pwr_r, y_vdd_r)
    # Strap Row 0 -> Row 1 VDD on M2 at x_pwr_r (keeps M3 100% open for East control pins & fp/fn!)
    c.wire("metal2", [(x_pwr_r, y_r0_vdd), (x_pwr_r, y_r1_vdd)], 0.800)

    # Connect West CMOS VSS spine (x_pwr_l) straight to Xldo VSS (96.0, 1.20) on M2/M3!
    c.wire("metal3", [(x_pwr_l, y_r0_vss), (x_pwr_l, y_r1_vss)], 0.800)
    c.wire("metal2", [(ldo_meta["vss"][0], ldo_meta["vss"][1]), (x_pwr_l, ldo_meta["vss"][1]), (x_pwr_l, y_r0_vss)], 0.800)

    # ------------------------------------------------------------------
    # 3. East-North Block: 28-Slice Face-to-Face Mirrored Array (2 x 14)
    # ------------------------------------------------------------------
    slice_cell, smeta = sab.build_sst_slice_unit(cache, add_ports=False)
    pitch = smeta["pitch_x"]     # 8.800
    hx = smeta["half_x"]         # 4.400
    gap_mf = 0.800               # clean M3 break between Main (mp/mn) and Post-FFE (fp/fn) slices

    x_arr_l = 96.000
    y_seam = 61.000              # Slid South 27.80 um so East top (89.42) aligns with Xldo top (89.42)!
    y_row_t = grid(y_seam + 5.600)   # 66.600
    y_row_b = grid(y_seam - 5.600)   # 55.400 (bot en = 35.75, y_en_b_bus = 34.60, 5.20 um above Row 1 VDD 29.40!)

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
        c.rect("metal3", xb1, grid(ym(smeta["y_vss_pwr"]) - 0.40), xb2, grid(ym(smeta["y_vss_pwr"]) + 0.40))
        c.rect("metal3", xb1, grid(ym(smeta["y_vss_drv"]) - 0.30), xb2, grid(ym(smeta["y_vss_drv"]) + 0.30))
        c.rect("metal3", xb1, grid(ym(smeta["y_vdd_drv"]) - 0.36), xb2, grid(ym(smeta["y_vdd_drv"]) + 0.36))
        c.rect("metal1", xb1, grid(ym(smeta["y_vss_pwr"]) - 0.25), xb2, grid(ym(smeta["y_vss_pwr"]) + 0.25))
        c.rect("metal1", xb1, grid(ym(smeta["y_vss_drv"]) - 0.22), xb2, grid(ym(smeta["y_vss_drv"]) + 0.22))
        c.rect("metal1", xb1, grid(ym(smeta["y_vdd_drv"]) - 0.22), xb2, grid(ym(smeta["y_vdd_drv"]) + 0.22))
        nwy1, nwy2 = sorted((ym(15.500), ym(19.450)))
        c.rect("nwell", xb1, nwy1, xb2, nwy2)

    # ------------------------------------------------------------------
    # 4. Symmetric Pad_p / Pad_n East Trunks + Low-R Power Distribution
    # ------------------------------------------------------------------
    y_padp_t = grid(y_row_t + smeta["y_pad_p"])   # 64.000
    y_padn_t = grid(y_row_t + smeta["y_pad_n"])   # 61.640
    y_padn_b = grid(y_row_b - smeta["y_pad_n"])   # 60.360
    y_padp_b = grid(y_row_b - smeta["y_pad_p"])   # 58.000

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

    # Heavy VDRV feed from collinear Xldo.vdrv (74.750) -> vertical M4+M5 spine at x=91.0 -> both slice rows
    # + 2.0 um M5 over-straps directly over y_vdrv_t and y_vdrv_b across the M5-free 2x14 slice array!
    y_vdrv_t = grid(y_row_t + smeta["y_vdrv"])    # 74.750 (collinear with Xldo.vdrv!)
    y_vdrv_b = grid(y_row_b - smeta["y_vdrv"])    # 47.250
    y_vdrv_lo = min(y_vdrv_b, ldo_meta["vdrv"][1])
    y_vdrv_hi = max(y_vdrv_t, ldo_meta["vdrv"][1])
    x_vdrv_sp = 91.000
    c.wire("metal4", [ldo_meta["vdrv"], (x_vdrv_sp, ldo_meta["vdrv"][1])], 2.000)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_lo), (x_vdrv_sp, y_vdrv_hi)], 2.200)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_t), (x_arr_l, y_vdrv_t)], 1.400)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_b), (x_arr_l, y_vdrv_b)], 1.400)
    # Parallel M5 spine + full-width M5 over-straps stitched via4 every 3-4 slices (cuts array R ~5.5x: 8.16 -> ~1.5 ohm!)
    via4_array(c, x_vdrv_sp, y_vdrv_b, nx=1, ny=1)
    via4_array(c, x_vdrv_sp, y_vdrv_t, nx=1, ny=1)
    if abs(ldo_meta["vdrv"][1] - y_vdrv_t) > 0.5 and abs(ldo_meta["vdrv"][1] - y_vdrv_b) > 0.5:
        via4_array(c, x_vdrv_sp, ldo_meta["vdrv"][1], nx=1, ny=1)
    c.wire("metal5", [(ldo_meta["vdrv"][0], ldo_meta["vdrv"][1]), (x_vdrv_sp, ldo_meta["vdrv"][1])], 2.200)
    c.wire("metal5", [(x_vdrv_sp, y_vdrv_lo), (x_vdrv_sp, y_vdrv_hi)], 2.200)
    for y_vs, row_cxs in ((y_vdrv_t, top_cxs), (y_vdrv_b, bot_cxs)):
        c.wire("metal5", [(x_vdrv_sp, y_vs), (row_cxs[-1], y_vs)], 2.000)
        for sidx in (0, 4, 8, 11, 13):
            via4_array(c, row_cxs[sidx], y_vs, nx=1, ny=1)

    # Heavy VDD distribution: join collinear Xldo.vdd (85.400), Row T vdd, Row B vdd, and CMOS VDD!
    y_vdd_t = grid(y_row_t + smeta["y_vdd_drv"])  # 85.400 (collinear with Xldo.vdd!)
    y_vdd_b = grid(y_row_b - smeta["y_vdd_drv"])  # 36.600
    x_vdd_sp = 88.200
    c.wire("metal4", [ldo_meta["vdd"], (x_vdd_sp, ldo_meta["vdd"][1]), (x_vdd_sp, y_vdd_t)], 1.600)
    via3_array(c, x_vdd_sp, y_vdd_t, nx=2, ny=2)
    c.wire("metal3", [(x_vdd_sp, y_vdd_t), (x_arr_l, y_vdd_t)], 1.200)
    # East vertical VDD spine: M3 between y_vdd_b (36.60) and y_vdd_t (85.40), then M2 below y_vdd_b down to y_r1_vdd (29.40)!
    # Keeps M3 100% open across x_vdd_e below y=35.5 for East enable pins + fp/fn!
    c.wire("metal3", [(x_arr_r, y_vdd_t), (x_vdd_e, y_vdd_t), (x_vdd_e, y_vdd_b)], 1.200)
    c.wire("metal3", [(x_arr_r, y_vdd_b), (x_vdd_e, y_vdd_b)], 1.200)
    for vx_off in (-0.300, +0.300):
        via2_clean(c, grid(x_vdd_e + vx_off), y_vdd_b)
    c.wire("metal2", [(x_vdd_e, y_r1_vdd), (x_vdd_e, y_vdd_b)], 1.400)
    c.wire("metal2", [(x_pwr_r, y_r1_vdd), (x_vdd_e, y_r1_vdd)], 1.000)

    # Heavy VSS distribution: vertical M3 spine at x_vss_sp = 88.200 (between Xldo 86.5 and vdrv M4 91.0!)
    y_vss_pt = grid(y_row_t + smeta["y_vss_pwr"])  # 72.000
    y_vss_dt = grid(y_row_t + smeta["y_vss_drv"])  # 78.000
    y_vss_pb = grid(y_row_b - smeta["y_vss_pwr"])  # 50.000
    y_vss_db = grid(y_row_b - smeta["y_vss_drv"])  # 44.000
    x_vss_sp = 88.200
    c.wire("metal3", [(x_vss_sp, y_r0_vss), (x_vss_sp, y_vss_dt)], 1.200)
    c.wire("metal3", [(x_vss_sp, y_r0_vss), (x_pwr_l, y_r0_vss)], 1.000)
    for yv in (y_vss_db, y_vss_pb, y_vss_pt, y_vss_dt):
        c.wire("metal3", [(x_vss_sp, yv), (x_arr_l, yv)], 1.000)

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
    for xv, yb, yt, nm in ((x_fp_v, y_dinp_b, y_dinp_t, "fp"), (x_fn_v, y_dinn_b, y_dinn_t, "fn")):
        for y_row_din in (yb, yt):
            via3_pad(c, grid(x_arr_r + 0.500), y_row_din)
            c.wire("metal3", [(x_arr_r, y_row_din), (grid(x_arr_r + 0.500), y_row_din)], 0.360)
            c.wire("metal4", [(grid(x_arr_r + 0.500), y_row_din), (xv, y_row_din)], 0.440)
            via3_pad(c, xv, y_row_din)
        c.wire("metal3", [(xv, yb), (xv, yt)], 0.400)
        all_nets.setdefault(nm, []).append((xv, yb, "metal3"))

    # ------------------------------------------------------------------
    # 6. Route ALL Remaining CMOS Interconnects via ManhattanRouter (Inter-row + Over-Cell M3)
    # ------------------------------------------------------------------
    # Pin-free M3 bands (0.90 um pitch):
    #   * Band S   (South + Row 0 NMOS diff):       y in [0.5..5.9]   (7 tracks; Row 0 pins at y in [7.0..9.0])
    #   * Band 0-1 (Row 0 PMOS + Ch0-1 + Row 1 NMOS): y in [10.4..22.1] (14 tracks; Row 1 pins at y in [23.2..25.2])
    #   * Band 1-A (Row 1 PMOS + Ch1-Arr):          y in [26.6..33.0] (x_vdd_e is M2-only below 36.6 -> 29.3 is open!)
    m3_tracks = [grid(0.500 + 0.900 * k) for k in range(37)]
    pref_tracks = {
        yt for yt in m3_tracks
        if (0.5 <= yt <= 5.95) or (10.3 <= yt <= 22.15) or (26.5 <= yt <= 33.4)
    }
    router = ManhattanRouter(m3_tracks, m4_min_pitch=0.960, preferred_tracks=pref_tracks)

    # South perimeter ports aligned directly below their receiver spans (shifted West 11.00 um!):
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
    #   Spread cleanly across y in [22.10, 32.90] (min spacing 1.80 um, zero label crowding!)
    #   m4 and m1 jog cleanly down on M4 East of x_fp_v (228.4) to 24.30 / 26.50!
    east_en_order = ["ffe_en", "m4", "m1", "m0", "f1", "f0"]
    east_en_ports: dict[str, tuple[float, float]] = {}
    x_fan_m4 = grid(x_fp_v + 1.000)   # 229.400
    x_fan_m1 = grid(x_fp_v + 2.000)   # 230.400
    east_route_spec = {
        "ffe_en": (x_pad_out, 22.100, 22.100),
        "m4":     (x_fan_m4,  28.400, 24.300),
        "m1":     (x_fan_m1,  30.200, 26.500),
        "m0":     (x_pad_out, 29.300, 29.300),
        "f1":     (x_pad_out, 31.100, 31.100),
        "f0":     (x_pad_out, 32.900, 32.900),
    }
    pref_y_map: dict[str, float] = {
        "fp": 27.500,
        "fn": 26.600,
        "mp": 32.900,
        "mn": 32.000,
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
    for nm in ("p0", "p1", "p2", "p3", "pb0", "pb1", "pb2", "pb3"):
        pref_y_map[nm] = 16.700
    for nm in ("d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3"):
        pref_y_map[nm] = 13.100

    # Reserve M3 power spines & bridges so router stays clear of VSS/VDD M3 + East fanout!
    router.reserve_m3_span(y_en_b_bus, x_arr_l, x_arr_r, "__en_b_bus__")
    for yt in m3_tracks:
        if y_r0_vss - 0.8 <= yt <= y_r1_vss + 0.8:
            router.reserve_m3_pad(x_pwr_l, yt, "__vss_l__")
        if yt >= y_vdd_b - 0.8:
            router.reserve_m3_pad(x_vdd_e, yt, "__vdd_e__")
    router.reserve_m4_seg(x_mp_v, y_dinp_b, y_dinp_t, "mp")
    router.reserve_m4_seg(x_mn_v, y_dinn_b, y_dinn_t, "mn")
    router.reserve_m4_seg(x_fan_m4, 24.300, 28.400, "m4")
    router.reserve_m4_seg(x_fan_m1, 26.500, 30.200, "m1")
    router.reserve_m3_span(24.300, x_fan_m4, x_pad_out, "m4")
    router.reserve_m3_span(26.500, x_fan_m1, x_pad_out, "m1")
    router.pre_register_nets(all_nets)

    # Route Band 1-Arr & East enables first (lock exact clean straight tracks), then M4 South-port nets, then p0..pb3!
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

    # Draw clean East fanout drops for m4 (28.4 -> 24.3) and m1 (30.2 -> 26.5) East of x_fp_v!
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
        "vdrv": ("metal4", x_vdrv_sp, y_vdrv_t),
        "vdd":  ("metal4", x_vdd_sp, y_vdd_t),
        "vss":  ("metal2", ldo_meta["vss"][0], ldo_meta["vss"][1]),
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
        "y_r2_vdd": y_r1_vdd,
        "y_r1_vdd": y_r1_vdd,
        "x_vdd_sp": x_vdd_sp,
        "x_vdrv_sp": x_vdrv_sp,
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
