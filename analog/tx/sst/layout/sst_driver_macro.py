#!/usr/bin/env python3
"""Physical PDK layout builder for `serdes_tx_sst_driver_pdk` (Full 4:1 Fused
N-over-N SST Driver + 2-Tap FFE + 5-Bit ZQ + On-Chip V_drv LDO).

Floorplan (~234 x 94 um = ~22,000 um^2):
  - West (x in [-8.4..97.6], y in [0.6..89.7]):
      `Xldo` (`sst_vdrv_ldo_pdk`: 15.3 pF stacked MIM + under-MIM 1p41 resistors + ABBA OTA + 240u pass FET)
  - East-South (x in [106..230], y in [1.0..34.0]):
      3 Mirrored Standard High-Speed CMOS Rows (`ROW_DRV`, H=10.20 um):
        * Row 0 (y=1.0..11.2, normal):  `Xpg` (`sst_pulsegen_4ph`)
        * Row 1 (y=11.2..21.4, mirror): `Xmux_m` (`sst_mux4_predrv scale=1.0`)
        * Row 2 (y=21.4..31.6, normal): `Xmux_f` (`sst_mux4_predrv scale=0.45`)
      Routed via DRC-guaranteed M3-H / M4-V `ManhattanRouter`.
      Inputs `d0..d3, db0..db3, phi0..phi270` exit cleanly on the South perimeter (M4)
      so `serdes_tx_sst_serializer16_pdk` snaps directly underneath in `serdes_tx_sst_top_pdk`!
  - East-North (x in [106..230], y in [38.0..90.0]):
      28-Slice Mirrored Face-to-Face Array (`2 rows x 14 cols = 23 Main + 5 Post-FFE`):
        * Top Row (y_orig=69.60, normal): Cols 0..7=m3(8x), 8..11=m2(4x) | gap | Cols 12..13=f2(2x)
        * Bot Row (y_orig=58.40, mirror): Cols 0..7=m4(8x), 8..9=m1(2x), 10=m0(1x) | gap | Cols 11..12=f1(2x), 13=f0(1x)
        * Symmetric M4+M5 `pad_p/pad_n` trunks down the center seam (y=61..67) exiting East!
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
    mirror_y: bool,
) -> dict[str, list[tuple[float, float, str]]]:
    """Place a standard row cell into `dst` at `(dx, y_vss_world)` with optional Y-mirror and return mapped pins."""
    dx = grid(dx)
    dy = grid(y_vss_world)
    dst.include(row_cell, dx=dx, dy=dy, mirror_y=mirror_y)
    out: dict[str, list[tuple[float, float, str]]] = {}
    for net, plist in pins_local.items():
        mapped = []
        for px, py, lyr in plist:
            wx = grid(px + dx)
            wy = grid((-py if mirror_y else py) + dy)
            mapped.append((wx, wy, lyr))
        out[net] = mapped
    return out


def _build_pulsegen_row(cache: PdkCache) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build `sst_pulsegen_4ph` on a single `ROW_DRV` row (returns cell, net->pins, x_end)."""
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    x = 0.0
    # Stage 1: input sharpening inverters Xi0..Xi27 + cross-coupled alignment Xcc1a/b
    for ph, bnet in (("phi0", "b0"), ("phi90", "b90"), ("phi180", "b180"), ("phi270", "b270")):
        u, x = scc.place_inv(c, cache, row, x, 2.5, 5.0, 1, 2, gap_l=1.200, trk_g=2)
        add_pin(ph, u["a"])
        add_pin(bnet, u["y"])
    for a, b in (("b0", "b180"), ("b90", "b270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.6, 1.2, gap_l=1.200)
        add_pin(a, u["ap"], "metal2")
        add_pin(b, u["an"])

    # Stage 2: restore polarity Xj0..Xj27 + Xcc2a/b
    for bnet, cnet in (("b0", "c0"), ("b90", "c90"), ("b180", "c180"), ("b270", "c270")):
        u, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 4, gap_l=1.200, trk_g=2)
        add_pin(bnet, u["a"])
        add_pin(cnet, u["y"])
    for a, b in (("c0", "c180"), ("c90", "c270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.8, 1.6, gap_l=1.200)
        add_pin(a, u["ap"], "metal2")
        add_pin(b, u["an"])

    # Stage 3: 25%-duty pulse generators Xp0..Xp3 (NOR2), Xpb0..Xpb3 (NAND2), Xccp0..Xccp3
    # Use trk_a=0, trk_b=4 so a, b, and y (trk2) are spaced >= 1.00 um apart for M3 via2 pads!
    for a, b, pnet in (("c90", "c180", "p0"), ("c180", "c270", "p1"), ("c270", "c0", "p2"), ("c0", "c90", "p3")):
        u, x = scc.place_nor2(c, cache, row, x, 2.8, 12.0, 2, 4, gap_l=0.920, trk_a=0, trk_b=4)
        add_pin(a, u["a"])
        add_pin(b, u["b"])
        add_pin(pnet, u["y"])
    for a, b, pbnet in (("c0", "c270", "pb0"), ("c90", "c0", "pb1"), ("c180", "c90", "pb2"), ("c270", "c180", "pb3")):
        u, x = scc.place_nand2(c, cache, row, x, 6.0, 5.0, 2, 2, gap_l=0.920, trk_a=0, trk_b=4)
        add_pin(a, u["a"])
        add_pin(b, u["b"])
        add_pin(pbnet, u["y"])
    for pnet, pbnet in (("p0", "pb0"), ("p1", "pb1"), ("p2", "pb2"), ("p3", "pb3")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.7, 1.4, gap_l=0.920)
        add_pin(pnet, u["ap"], "metal2")
        add_pin(pbnet, u["an"])

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
    """Build `sst_mux4_predrv(scale=...)` on a single `ROW_DRV` row."""
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    x = 0.0
    y2 = row.y_tracks[2]
    # 1+2. Interleaved stiff 1 GHz data drivers + 4:1 transmission gates
    # Join the 4 Xtp.b outputs directly on a local horizontal M2 bus (mux_p) and 4 Xtn.b on M2 (mux_n)
    # -> ultra-low 4 Gb/s mux_p/mux_n cap and eliminates 12 redundant M4 drops!
    wn_b, wp_b = grid(2.4 * scale), grid(4.8 * scale)
    wn_t, wp_t = grid(2.4 * scale), grid(4.0 * scale)
    mux_p_xs: list[float] = []
    mux_n_xs: list[float] = []
    # Put local mux_p / mux_n M2 bus at y_nb = row.y_n_top - 0.240 (1.74 um below y2 -> zero short with d0..db3 via1!)
    y_mux_m2 = grid(row.y_n_top - 0.240)
    for k in range(4):
        ub, x = scc.place_inv(c, cache, row, x, wn_b, wp_b, 1, 2, gap_l=0.920, trk_g=2)
        ut, x = scc.place_tgate(c, cache, row, x, wn_t, wp_t, 1, 2, gap_l=0.960)
        c.wire("metal1", [(ub["y_col_x"], y2), (ut["a"][0], y2)], slc.W_M1)
        c.via1(ut["b"][0], y_mux_m2)
        mux_p_xs.append(ut["b"][0])
        add_pin(db_names[k], ub["a"])
        add_pin(f"p{k}", ut["p"])
        add_pin(f"pb{k}", ut["pb"])
    c.wire("metal2", [(mux_p_xs[0], y_mux_m2), (mux_p_xs[-1], y_mux_m2)], 0.300)
    add_pin(f"{tag}_mux_p", (mux_p_xs[-1], y_mux_m2), "metal2")

    for k in range(4):
        ub, x = scc.place_inv(c, cache, row, x, wn_b, wp_b, 1, 2, gap_l=0.920, trk_g=2)
        ut, x = scc.place_tgate(c, cache, row, x, wn_t, wp_t, 1, 2, gap_l=0.960)
        c.wire("metal1", [(ub["y_col_x"], y2), (ut["a"][0], y2)], slc.W_M1)
        c.via1(ut["b"][0], y_mux_m2)
        mux_n_xs.append(ut["b"][0])
        add_pin(d_names[k], ub["a"])
        add_pin(f"p{k}", ut["p"])
        add_pin(f"pb{k}", ut["pb"])
    c.wire("metal2", [(mux_n_xs[0], y_mux_m2), (mux_n_xs[-1], y_mux_m2)], 0.300)
    add_pin(f"{tag}_mux_n", (mux_n_xs[-1], y_mux_m2), "metal2")

    # 3. Cross-coupled keeper Xccm
    wn_k = max(0.45, grid(0.45 * scale))
    wp_k = max(0.90, grid(0.90 * scale))
    u, x = scc.place_cc_align(c, cache, row, x, wn_k, wp_k, gap_l=0.720)
    add_pin(f"{tag}_mux_p", u["ap"], "metal2")
    add_pin(f"{tag}_mux_n", u["an"])

    # 4+5. Stage 1 NAND2 + Stage 2 INV interleaved per leg (trk_a=0, trk_b=4 -> >= 1.00 um M3 clearance!)
    wn_1, wp_1 = grid(5.2 * scale), grid(4.6 * scale)
    wn_2, wp_2 = grid(5.5 * scale), grid(11.0 * scale)
    for leg, onet in (("p", out_p_net), ("n", out_n_net)):
        u1, x = scc.place_nand2(c, cache, row, x, wn_1, wp_1, 2, 2, gap_l=0.920, trk_a=0, trk_b=4)
        u2, x = scc.place_inv(c, cache, row, x, wn_2, wp_2, 2, 3, gap_l=0.920, trk_g=2)
        c.wire("metal1", [(u1["y_col_x"], y2), u2["a"]], slc.W_M1)
        add_pin(f"{tag}_mux_{leg}", u1["a"])
        add_pin(en_net, u1["b"])
        add_pin(onet, u2["y"])

    return c, nets, x


def build_sst_driver(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build complete `serdes_tx_sst_driver_pdk` macro."""
    c = Cell()
    row = scc.ROW_DRV

    # ------------------------------------------------------------------
    # 1. West Block: On-Chip V_drv LDO (`Xldo`)
    # ------------------------------------------------------------------
    ldo_cell, ldo_meta = sab.build_sst_vdrv_ldo(cache, add_ports=False)
    c.include(ldo_cell, dx=0.0, dy=0.0)

    # ------------------------------------------------------------------
    # 2. East-South Block: 3 High-Speed CMOS Rows (Xpg, Xmux_m, Xmux_f) + 3 Pin-Free M3 Channels
    # ------------------------------------------------------------------
    x_cmos0 = 106.000
    y_r0_vss = 5.200                                # Row 0 (Xpg):    VSS=5.20,  VDD=15.40
    y_r0_vdd = grid(y_r0_vss + row.height)          # 15.40
    # Channel 0-1 (8.4 um): 8 pin-free M3 tracks directly between Xpg and Xmux_m!
    y_r1_vss = 23.800                               # Row 1 (Xmux_m): VSS=23.80, VDD=34.00
    y_r1_vdd = grid(y_r1_vss + row.height)          # 34.00
    # Channel 1-2 (12.0 um): 12 pin-free M3 tracks between Xmux_m and Xmux_f!
    y_r2_vss = 46.000                               # Row 2 (Xmux_f): VSS=46.00, VDD=56.20
    y_r2_vdd = grid(y_r2_vss + row.height)          # 56.20

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

    x_cmos_w = grid(max(pg_w, mm_w + 1.2, mf_w + 2.4) + 1.500)
    scc.finish_cmos_row(pg_cell, row, -1.000, x_cmos_w, tap_pitch=10.0)
    scc.finish_cmos_row(mm_cell, row, -2.200, grid(x_cmos_w - 1.200), tap_pitch=10.0)
    scc.finish_cmos_row(mf_cell, row, -3.400, grid(x_cmos_w - 2.400), tap_pitch=10.0)

    all_nets: dict[str, list[tuple[float, float, str]]] = {}

    def merge_pins(pmap: dict[str, list[tuple[float, float, str]]]) -> None:
        for net, pts in pmap.items():
            all_nets.setdefault(net, []).extend(pts)

    # Stagger Row 0/1/2 by 1.20 um in X so vertical M4 drops between rows never share an exact X!
    merge_pins(_add_row_transformed(c, pg_cell, pg_nets, x_cmos0,         y_r0_vss, mirror_y=False))
    merge_pins(_add_row_transformed(c, mm_cell, mm_nets, x_cmos0 + 1.200, y_r1_vss, mirror_y=False))
    merge_pins(_add_row_transformed(c, mf_cell, mf_nets, x_cmos0 + 2.400, y_r2_vss, mirror_y=False))

    x_cmos_l = grid(x_cmos0 - 1.000)
    x_cmos_r = grid(x_cmos0 + x_cmos_w)

    # Tie `vdd_en` (Xmux_m's permanent VDD enable) directly to Row 1's VDD rail (y_r1_vdd = 34.00) on M1/M2!
    for px, py, _ in all_nets.pop("vdd_en", []):
        c.via1(px, py)
        c.via1(px, y_r1_vdd)
        c.wire("metal2", [(px, min(py, y_r1_vdd)), (px, max(py, y_r1_vdd))], 0.280)

    # Strap CMOS power rails (VSS at 5.20, 23.80, 46.00; VDD at 15.40, 34.00, 56.20) at West & East edges
    x_pwr_l = grid(x_cmos_l - 0.800)
    x_pwr_r = grid(x_cmos_r + 1.200)
    for y_vss_r in (y_r0_vss, y_r1_vss, y_r2_vss):
        c.wire("metal1", [(x_pwr_l, y_vss_r), (x_cmos_l, y_vss_r)], 0.500)
        c.via1(x_pwr_l, y_vss_r)
        via2_clean(c, x_pwr_l, y_vss_r)
    for y_vdd_r in (y_r0_vdd, y_r1_vdd, y_r2_vdd):
        c.wire("metal1", [(x_cmos_r, y_vdd_r), (x_pwr_r, y_vdd_r)], 0.500)
        c.via1(x_pwr_r, y_vdd_r)
    # Strap Row 0 -> Row 1 -> Row 2 VDD on M2 at x_pwr_r (keeps M3 100% open for East control pins!)
    c.wire("metal2", [(x_pwr_r, y_r0_vdd), (x_pwr_r, y_r2_vdd)], 0.800)
    via2_clean(c, x_pwr_r, y_r2_vdd)

    # Connect West CMOS VSS spine (x_pwr_l) straight to Xldo VSS (96.0, 1.20) on M2/M3!
    c.wire("metal3", [(x_pwr_l, y_r0_vss), (x_pwr_l, y_r2_vss)], 0.800)
    c.wire("metal2", [(ldo_meta["vss"][0], ldo_meta["vss"][1]), (x_pwr_l, ldo_meta["vss"][1]), (x_pwr_l, y_r0_vss)], 0.800)

    # ------------------------------------------------------------------
    # 3. East-North Block: 28-Slice Face-to-Face Mirrored Array (2 x 14)
    # ------------------------------------------------------------------
    slice_cell, smeta = sab.build_sst_slice_unit(cache, add_ports=False)
    pitch = smeta["pitch_x"]     # 8.800
    hx = smeta["half_x"]         # 4.400
    gap_mf = 0.800               # clean M3 break between Main (mp/mn) and Post-FFE (fp/fn) slices

    x_arr_l = 107.000
    y_seam = 88.800
    y_row_t = grid(y_seam + 5.600)   # 94.400
    y_row_b = grid(y_seam - 5.600)   # 83.200 (bot en = 63.55, 7.35 um clear above Row 2 VDD 56.20!)

    # Column center X helper: cols 0..10 contiguous, 11..13 shift for Row B; cols 0..11 contiguous, 12..13 shift for Row T!
    # Keep a single uniform 0.80 um gap after Col 10 in Row B and after Col 11 in Row T?
    # Better: keep ALL 14 columns aligned vertically by making Row T = 11 Main + 3 Post?
    # Wait: Main=23 (8+4+8+2+1), Post=5 (2+2+1). 12+11=23 and 2+3=5!
    # If we align Cols 0..10 (11 cols), put `gap_mf=0.80` after Col 10 ONLY in Row B and after Col 11 ONLY in Row T,
    # total width of BOTH rows is identical: 14 * 8.80 + 0.80 = 124.00 um!
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
    y_padp_t = grid(y_row_t + smeta["y_pad_p"])   # 67.000
    y_padn_t = grid(y_row_t + smeta["y_pad_n"])   # 64.640
    y_padn_b = grid(y_row_b - smeta["y_pad_n"])   # 63.360
    y_padp_b = grid(y_row_b - smeta["y_pad_p"])   # 61.000

    # Join Top & Bot pad_n at East (x = x_padn_j) on M4; join Top & Bot pad_p at East (x = x_padp_j) on M4+M5!
    x_e_base = grid(max(x_arr_r, x_pwr_r))
    x_padn_j = grid(x_e_base + 1.200)
    x_vdd_e  = grid(x_e_base + 2.800)
    x_padp_j = grid(x_e_base + 5.200)
    x_fn_v   = grid(x_e_base + 7.200)
    x_fp_v   = grid(x_e_base + 8.400)
    x_pad_out = grid(x_e_base + 11.200)

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

    # Heavy VDRV feed from Xldo.vdrv -> vertical M4+M5 spine at x=102.0 -> both slice rows!
    y_vdrv_t = grid(y_row_t + smeta["y_vdrv"])
    y_vdrv_b = grid(y_row_b - smeta["y_vdrv"])
    y_vdrv_lo = min(y_vdrv_b, ldo_meta["vdrv"][1])
    y_vdrv_hi = max(y_vdrv_t, ldo_meta["vdrv"][1])
    x_vdrv_sp = 102.000
    c.wire("metal4", [ldo_meta["vdrv"], (x_vdrv_sp, ldo_meta["vdrv"][1])], 2.000)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_lo), (x_vdrv_sp, y_vdrv_hi)], 2.200)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_t), (x_arr_l, y_vdrv_t)], 1.400)
    c.wire("metal4", [(x_vdrv_sp, y_vdrv_b), (x_arr_l, y_vdrv_b)], 1.400)
    # Parallel M5 reinforcement on vdrv spine!
    via4_array(c, x_vdrv_sp, y_vdrv_lo, nx=1, ny=1)
    via4_array(c, x_vdrv_sp, y_vdrv_b, nx=1, ny=1)
    via4_array(c, x_vdrv_sp, y_vdrv_t, nx=1, ny=1)
    c.wire("metal5", [(ldo_meta["vdrv"][0], ldo_meta["vdrv"][1]), (x_vdrv_sp, ldo_meta["vdrv"][1])], 2.200)
    c.wire("metal5", [(x_vdrv_sp, y_vdrv_lo), (x_vdrv_sp, y_vdrv_hi)], 2.200)

    # Heavy VDD distribution: join Xldo.vdd, Row T vdd, Row B vdd, and CMOS VDD!
    y_vdd_t = grid(y_row_t + smeta["y_vdd_drv"])
    y_vdd_b = grid(y_row_b - smeta["y_vdd_drv"])
    # Top VDD: route on M4 at x_vdd_sp = 99.20 (2.80 um west of x_vdrv_sp=102.0 -> zero crossing with vdrv!)
    x_vdd_sp = 99.200
    c.wire("metal4", [ldo_meta["vdd"], (x_vdd_sp, ldo_meta["vdd"][1]), (x_vdd_sp, y_vdd_t)], 1.600)
    via3_array(c, x_vdd_sp, y_vdd_t, nx=2, ny=2)
    c.wire("metal3", [(x_vdd_sp, y_vdd_t), (x_arr_l, y_vdd_t)], 1.200)
    # East vertical VDD M3 spine (strictly east of x_arr_r & x_pwr_r, strictly west of x_fp_v/x_fn_v!)
    c.wire("metal3", [(x_arr_r, y_vdd_t), (x_vdd_e, y_vdd_t), (x_vdd_e, y_r2_vdd)], 1.200)
    c.wire("metal3", [(x_arr_r, y_vdd_b), (x_vdd_e, y_vdd_b)], 1.200)
    c.wire("metal3", [(x_pwr_r, y_r2_vdd), (x_vdd_e, y_r2_vdd)], 1.000)

    # Heavy VSS distribution: vertical M3 spine at x_vss_sp = 99.200 (strictly between Xldo 97.6 and vdrv M4 102.0!)
    y_vss_pt = grid(y_row_t + smeta["y_vss_pwr"])  # 75.000
    y_vss_dt = grid(y_row_t + smeta["y_vss_drv"])  # 81.000
    y_vss_pb = grid(y_row_b - smeta["y_vss_pwr"])  # 53.000
    y_vss_db = grid(y_row_b - smeta["y_vss_drv"])  # 47.000
    x_vss_sp = 99.200
    c.wire("metal3", [(x_vss_sp, y_r0_vss), (x_vss_sp, y_vss_dt)], 1.200)
    c.wire("metal3", [(x_vss_sp, y_r0_vss), (x_pwr_l, y_r0_vss)], 1.000)
    for yv in (y_vss_db, y_vss_pb, y_vss_pt, y_vss_dt):
        c.wire("metal3", [(x_vss_sp, yv), (x_arr_l, yv)], 1.000)

    # ------------------------------------------------------------------
    # 5. Connect Bank Enables (m0..m4, f0..f2) & mp/mn/fp/fn Data Buses
    # ------------------------------------------------------------------
    # Top Row enables (y_en_t = 81.60 + 19.65 = 101.25) -> clean M3 buses at y = 102.40 -> North perimeter M4 pins!
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

    # Bottom Row enables (y_en_b = 70.40 - 19.65 = 50.75) -> clean M3 buses at y = 49.60 -> route to East perimeter!
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

    # Connect mp/mn (Main slices) and fp/fn (Post slices) between Row T and Row B on vertical M4 straps!
    # Main slices: Row B din_p=44.40, din_n=43.40; Row T din_p=83.60, din_n=84.60.
    # Place vertical M4 straps at x = 104.2 (mp) and x = 105.6 (mn) — strictly between vdrv_sp (102.0) and x_arr_l (107.0)!
    y_dinp_b = grid(y_row_b - smeta["y_din_p"])   # 44.400
    y_dinn_b = grid(y_row_b - smeta["y_din_n"])   # 43.400
    y_dinp_t = grid(y_row_t + smeta["y_din_p"])   # 83.600
    y_dinn_t = grid(y_row_t + smeta["y_din_n"])   # 84.600

    x_mp_v, x_mn_v = 104.400, 105.700
    for xv, yb, yt, nm in ((x_mp_v, y_dinp_b, y_dinp_t, "mp"), (x_mn_v, y_dinn_b, y_dinn_t, "mn")):
        c.wire("metal3", [(xv, yb), (x_arr_l, yb)], 0.360)
        c.wire("metal3", [(xv, yt), (x_arr_l, yt)], 0.360)
        # Run vertically on M4, with clean 3.0 um M3 underpasses underneath the two vdrv M4 arms (y_vdrv_b, y_vdrv_t)!
        # (At y_vdrv_b and y_vdrv_t, M3 is 100% open — >= 2.7 um clear of vss_drv and vss_pwr M3 rails!)
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
    # 6. Route ALL CMOS Interconnects (`Xpg`, `Xmux_m`, `Xmux_f`, ports) via ManhattanRouter
    # ------------------------------------------------------------------
    # Allocate M3 tracks across South + Ch0-1 + Ch1-2 + Ch2-Arr (0.90 um pitch, 31 pin-free channel tracks!)
    m3_tracks = [grid(0.500 + 0.900 * k) for k in range(69)]
    pref_tracks = {
        yt for yt in m3_tracks
        if (0.5 <= yt <= 4.6) or (16.0 <= yt <= 23.2) or (34.6 <= yt <= 45.4) or (56.8 <= yt <= 61.6)
    }
    router = ManhattanRouter(m3_tracks, m4_min_pitch=0.960, preferred_tracks=pref_tracks)

    # South perimeter ports aligned directly below their receiver stages (phi0..270 on West, d0..db3 across middle)
    south_order = [
        "phi0", "phi90", "phi180", "phi270",
        "d0", "db0", "d1", "db1", "d2", "db2", "d3", "db3",
    ]
    y_south_port = -0.400
    south_ports: dict[str, tuple[float, float]] = {}
    for idx, pnm in enumerate(south_order):
        px = grid(x_cmos0 + 3.000 + idx * 7.200)
        south_ports[pnm] = (px, y_south_port)
        all_nets.setdefault(pnm, []).append((px, y_south_port, "metal4"))

    # East perimeter ports for bottom-row enables (m4, m1, m0, f1, f0) + ffe_en on M3 in Ch1-2 (y=35.6..44.6)!
    east_en_order = ["ffe_en", "m0", "m1", "m4", "f0", "f1"]
    east_en_ports: dict[str, tuple[float, float]] = {}
    east_track_ys = [m3_tracks[39 + i] for i in range(len(east_en_order))]
    for enm, y_ep in zip(east_en_order, east_track_ys):
        if enm != "ffe_en":
            bx, by = bot_en_pins[enm]
            all_nets.setdefault(enm, []).append((bx, by, "metal3"))
        all_nets.setdefault(enm, []).append((x_pad_out, y_ep, "metal3"))
        east_en_ports[enm] = (x_pad_out, y_ep)

    # Reserve M3 power spines & bridges so router stays clear of VSS/VDD M3!
    router.reserve_m3_span(y_en_b_bus, x_arr_l, x_arr_r, "__en_b_bus__")
    router.reserve_m3_span(y_r2_vdd, x_pwr_r - 0.5, x_vdd_e + 0.5, "__vdd_r2__")
    for yt in m3_tracks:
        if y_r0_vss - 0.8 <= yt <= y_r2_vss + 0.8:
            router.reserve_m3_pad(x_pwr_l, yt, "__vss_l__")
        if yt >= y_r2_vdd - 0.8:
            router.reserve_m3_pad(x_vdd_e, yt, "__vdd_e__")
    router.reserve_m4_seg(x_mp_v, y_dinp_b, y_dinp_t, "mp")
    router.reserve_m4_seg(x_mn_v, y_dinn_b, y_dinn_t, "mn")
    router.pre_register_nets(all_nets)

    # Route M4-port nets first (claim clean straight vertical drops), then shortest spans first!
    net_order = sorted(
        all_nets.items(),
        key=lambda kv: (0 if any(p[2] == "metal4" for p in kv[1]) else 1, max(p[0] for p in kv[1]) - min(p[0] for p in kv[1])),
    )
    for net_name, plist in net_order:
        router.route_net(c, net_name, plist)

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
        "y_r2_vdd": y_r2_vdd,
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
