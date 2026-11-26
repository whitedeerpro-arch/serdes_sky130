#!/usr/bin/env python3
"""Physical PDK layout builder for `serdes_tx_sst_serializer16_pdk` (Pure 1 GHz Static CMOS
16:4 Quarter-Rate Serializer + /2 & /4 Dividers + 4-Phase Stagger Retimer).

Floorplan (~227.7 x 53.1 um = ~12,090 um^2, 5 abutted mirrored standard CMOS rows `ROW_SER` H=9.50 um):
  - Row 0 (y=0.0..9.5,   normal): Lane 0 (Xr0..Xr3, Xma, Xda, Xmb, Xdb, Xmc, Xd1g, Xst0)
  - Row 1 (y=9.5..19.0,  mirror): Lane 1 (Xr0..Xr3, Xma, Xda, Xmb, Xdb, Xmc, Xd1g, Xst1)
  - Row 2 (y=19.0..28.5, normal): Dataflow-aligned Clock/Div row:
      Left [x~48..82]:   Xdiv250 + Xb250a/b + Xo250
      Center [x~107..130]: Xc0..Xc27b (aligned directly beneath phi0..phi270 North ports)
      Right [x~132..165]:  Xb500a/b + Xo500 + Xdiv500
  - Row 3 (y=28.5..38.0, mirror): Lane 2 (Xr0..Xr3, Xma, Xda, Xmb, Xdb, Xmc, Xd1g, Xst2a, Xst2b)
  - Row 4 (y=38.0..47.5, normal): Lane 3 (Xr0..Xr3, Xma, Xda, Xmb, Xdb, Xmc, Xd1g, Xst3a, Xst3b)

All 42 intra-lane nets and 6 internal Row-2 divider/buffer nets are routed locally on M1/M2
inside each row's open NMOS/PMOS diff bands, leaving only 22 global nets on over-cell M3/M4
(plus 16 straight vertical M4 `din0..din15` drops and collinear `rst_n` M3 buses).
North perimeter pins (`phi0..phi270, d0..d3, db0..db3`) align 1-to-1 with the South perimeter
of `serdes_tx_sst_driver_pdk` for zero-jog vertical abutment in `serdes_tx_sst_top_pdk`.
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
    via2_clean,
    via3_pad,
    via3_array,
    via4_array,
)
import sst_cmos_cells as scc  # noqa: E402


# Exact `serdes_tx_sst_driver_pdk` South perimeter port X coordinates (metal4),
# shifted by -4.200 um so `Xser` placed at dx=+4.200 shares a flush West edge (x=0.000) with `Xldo`!
DEFAULT_NORTH_PIN_XS: dict[str, float] = {
    "phi0":    92.800,
    "phi90":   96.800,
    "phi180": 100.800,
    "phi270": 104.800,
    "d0":     126.800,
    "d1":     132.800,
    "d2":     138.800,
    "d3":     144.800,
    "db0":    150.800,
    "db1":    156.800,
    "db2":    162.800,
    "db3":    168.800,
}

# Local intra-row M1/M2 routing tracks inside `ROW_SER` (H=9.500 um):
#   - Strictly clear of `dff_r` internal M2 (`0.62..0.94`, `3.05..4.91`, `6.31..6.63`, `8.78..9.10`)
#   - Strictly clear of `din` via2 M2 pads at `y=6.65` (`6.45..6.85`) -> P1 starts at `7.18` (`0.21 um` gap!)
#   - Strictly clear of `dff_r` `tg1.a` `viali_pad` at `1.325..1.615` -> N2 at `1.95` (`0.175 um` gap!)
Y_M1_HOP = 6.650
Y_M2_N2  = 1.950
Y_M2_P1  = 7.180
Y_M2_P2  = 7.680
Y_M2_P3  = 8.180


def _local_m1_abut_to_dff_d(c: Cell, x_src: float, x_dst: float) -> None:
    """Direct pure-M1 link from an adjacent cell's `y`/`q` column (y<=5.99) to next `dff_r.d` (y=6.65)."""
    c.wire("metal1", [(x_src, 5.990), (x_src, Y_M1_HOP), (x_dst, Y_M1_HOP)], slc.W_M1)


def _local_m2_pmos_strap(
    c: Cell,
    x_src: float,
    x_dst: float,
    y_trk: float,
    src_y0: float = 5.990,
    dst_y0: float | None = None,
    dst_w: float = slc.W_M1,
) -> None:
    """Route an intra-row net on an open PMOS-band horizontal M2 track (`7.18 / 7.68 / 8.18`)."""
    c.wire("metal1", [(x_src, src_y0), (x_src, y_trk)], slc.W_M1)
    c.via1(x_src, y_trk)
    if dst_y0 is not None:
        c.wire("metal1", [(x_dst, min(dst_y0, y_trk)), (x_dst, max(dst_y0, y_trk))], dst_w)
    c.via1(x_dst, y_trk)
    c.wire("metal2", [(min(x_src, x_dst), y_trk), (max(x_src, x_dst), y_trk)], 0.240)


def _local_m2_nmos_strap(c: Cell, x_src: float, x_dst: float, y_trk: float, src_y1: float = 2.510, dst_y1: float | None = 2.050) -> None:
    """Route an intra-row net on an open NMOS-band horizontal M2 track (`1.85`)."""
    c.wire("metal1", [(x_src, y_trk), (x_src, src_y1)], slc.W_M1)
    c.via1(x_src, y_trk)
    if dst_y1 is not None:
        c.wire("metal1", [(x_dst, min(y_trk, dst_y1)), (x_dst, max(y_trk, dst_y1))], slc.W_M1)
    c.via1(x_dst, y_trk)
    c.wire("metal2", [(min(x_src, x_dst), y_trk), (max(x_src, x_dst), y_trk)], 0.240)


def _add_row_transformed(
    dst: Cell,
    row_cell: Cell,
    pins_local: dict[str, list[tuple[float, float, str]]],
    dx: float,
    y_vss_world: float,
    mirror_y: bool,
) -> dict[str, list[tuple[float, float, str]]]:
    dx, dy = grid(dx), grid(y_vss_world)
    dst.include(row_cell, dx=dx, dy=dy, mirror_y=mirror_y)
    out: dict[str, list[tuple[float, float, str]]] = {}
    for net, plist in pins_local.items():
        out[net] = [
            (grid(px + dx), grid((-py if mirror_y else py) + dy), lyr)
            for px, py, lyr in plist
        ]
    return out


def _build_lane_row(
    cache: PdkCache,
    lane_idx: int,
    dins: tuple[str, str, str, str],
    stagger_spec: list[tuple[str, str, float, float, str, str]],
) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build one complete 4:1 lane serializer + its stagger retimer DFF(s) on `ROW_SER`.

    All intra-lane data hops (`r0..r3, ma, mb, da, db, mc, l*, l2h/l3h`) are routed
    100% locally on M1 abutment and open-band M2 straps (ZERO M3/M4 usage!).
    `stagger_spec`: list of `(clk_net, d_in_net, wn, wp, q_net, qb_net)`.
    """
    row = scc.ROW_SER
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    def wire_dff_ctrl(u: dict, ck_n: str, d_in_global: str | None = None, q_n: str | None = None, qb_n: str | None = None) -> None:
        if d_in_global is not None:
            add(d_in_global, u["d"])
        add(ck_n, u["clk"])
        add("rst_n", u["rst_n"], "metal3")
        if q_n is not None:
            add(q_n, u["q"])
        if qb_n is not None:
            add(qb_n, u["qb"])

    x = 0.0
    # Stage 0: Full-cycle 250 MHz input word capture (C2 fix: Xr0..Xr2 + Xr3_m on clk250b -> full 4.00 ns setup;
    # Xr3 retimes r3_m -> r3 on clk250 via direct M1 abutment, preserving natural r0,r1,r2,r3 order!)
    r_dffs: list[dict] = []
    for k in range(3):
        u, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
        wire_dff_ctrl(u, "clk250b", d_in_global=dins[k])
        r_dffs.append(u)
    u_r3m, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
    wire_dff_ctrl(u_r3m, "clk250b", d_in_global=dins[3])
    u_r3, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
    _local_m1_abut_to_dff_d(c, u_r3m["q"][0], u_r3["d"][0])
    wire_dff_ctrl(u_r3, "clk250")
    r_dffs.append(u_r3)

    # Stage 1 interleaved as (Xma, Xda, Xmb, Xdb) with staggered 500 MHz clocks (Xda=clk500, Xdb=clk500b)!
    u_ma, x = scc.place_mux2(c, cache, row, x, wn=0.9, wp=1.8, gap_l=1.360)
    add("clk250b", u_ma["sel"], "metal2")
    add("clk250", u_ma["sel_b"], "metal2")

    u_da, x = scc.place_dff_r(c, cache, row, x, wn=1.2, wp=2.4, gap_l=0.900)
    wire_dff_ctrl(u_da, "clk500")

    u_mb, x = scc.place_mux2(c, cache, row, x, wn=0.9, wp=1.8, gap_l=1.360)
    add("clk250b", u_mb["sel"], "metal2")
    add("clk250", u_mb["sel_b"], "metal2")

    u_db, x = scc.place_dff_r(c, cache, row, x, wn=1.2, wp=2.4, gap_l=0.900)
    wire_dff_ctrl(u_db, "clk500b")

    # Stage 2: 2:1 MUX (Xmc, wn=1.5, wp=3.0) + 1 GHz DFF (Xd1g, wn=1.5, wp=3.0)
    u_mc, x = scc.place_mux2(c, cache, row, x, wn=1.5, wp=3.0, gap_l=1.360)
    add("clk500", u_mc["sel"], "metal2")
    add("clk500b", u_mc["sel_b"], "metal2")

    u_d1g, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=0.900)
    wire_dff_ctrl(u_d1g, "c0")

    # Stage 3: 4-Phase Stagger Retimer DFF(s) with direct M1 abutment from Xd1g -> Xst*
    prev_q_x = u_d1g["q"][0]
    for ck_n, _d_in, wn, wp, q_n, qb_n in stagger_spec:
        u_st, x = scc.place_dff_r(c, cache, row, x, wn=wn, wp=wp, gap_l=0.900)
        _local_m1_abut_to_dff_d(c, prev_q_x, u_st["d"][0])
        # Only export final output ports (d0..d3, db0..db3); internal l2h/l3h connect via M1 abutment!
        is_final = (qb_n is not None)
        wire_dff_ctrl(u_st, ck_n, q_n=(q_n if is_final else None), qb_n=(qb_n if is_final else None))
        prev_q_x = u_st["q"][0]

    # --- Local M1 direct abutment links (ZERO vias, ZERO M2/M3/M4!) ---
    _local_m1_abut_to_dff_d(c, u_ma["y"][0], u_da["d"][0])    # ma: Xma.y -> Xda.d
    _local_m1_abut_to_dff_d(c, u_mb["y"][0], u_db["d"][0])    # mb: Xmb.y -> Xdb.d
    _local_m1_abut_to_dff_d(c, u_mc["y"][0], u_d1g["d"][0])   # mc: Xmc.y -> Xd1g.d

    # --- Local over-cell M2 horizontal straps (ZERO M3/M4!) ---
    # r2: Xr2.q -> Xma.a on NMOS M2 (stops at Xma.ta.a, 1.025 um left of Xma.sel vertical M2!)
    _local_m2_nmos_strap(c, r_dffs[2]["q"][0], u_ma["a"][0], Y_M2_N2, src_y1=2.510, dst_y1=2.050)
    # r0: Xr0.q -> Xma.b on PMOS M2 P1 (Xma.tb.a already spans y=1.98..7.42)
    _local_m2_pmos_strap(c, r_dffs[0]["q"][0], u_ma["b"][0], Y_M2_P1, src_y0=5.990, dst_y0=None)
    # r1: Xr1.q -> Xmb.a on PMOS M2 P2 (wide 0.300 M1 stub bridges cleanly to Xmb.ta.a viali_pad at 7.33 -> 0 notch!)
    _local_m2_pmos_strap(c, r_dffs[1]["q"][0], u_mb["a"][0], Y_M2_P2, src_y0=5.990, dst_y0=7.330, dst_w=0.300)
    # r3: Xr3.q -> Xmb.b on PMOS M2 P3 (extend Xmb.tb.a M1 from 7.33 to 8.18)
    _local_m2_pmos_strap(c, r_dffs[3]["q"][0], u_mb["b"][0], Y_M2_P3, src_y0=5.990, dst_y0=7.330)
    # da: Xda.q -> Xmc.a on PMOS M2 P1 (strictly east of r0 end; Xmc.ta.a spans 1.68..8.02)
    _local_m2_pmos_strap(c, u_da["q"][0], u_mc["a"][0], Y_M2_P1, src_y0=5.990, dst_y0=None)
    # db: Xdb.q -> Xmc.b on PMOS M2 P2 (P2=7.68 pad top=7.84 overlaps Xmc.tb.a viali_pad 7.785..8.075 -> 0 notch!)
    _local_m2_pmos_strap(c, u_db["q"][0], u_mc["b"][0], Y_M2_P2, src_y0=5.990, dst_y0=None)

    return c, nets, x


def _build_clk_div_row(cache: PdkCache) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build dataflow-aligned center clock-buffer + /2 & /4 divider row (`Row 2`) on `ROW_SER`.

    Placement left-to-right matches lane loads & North/South ports:
      - Left   [x~48..82]:  Xdiv250 + Xb250a/b + Xo250 (center of Xr0..Xr3 & Xma/Xmb)
      - Center [x~107..130]: Xc0..Xc27b (aligned directly beneath phi0..phi270 North ports!)
      - Right  [x~132..165]: Xb500a/b + Xo500 + Xdiv500 (aligned with Xda/Xdb/Xmc & c0 loads!)

    All internal Row-2 divider/buffer nets (`clk250b_i, clk250_i, clk500b_i, clk500_i`,
    plus `Xb250a->Xo250` and `Xb500a->Xo500`) route locally on M1/M2 (ZERO M3/M4!).
    """
    row = scc.ROW_SER
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    y2 = row.y_tracks[2]

    # ------------------------------------------------------------------
    # 1. Left Group (x ~ 48..86): /4 divider Xdiv250 + parallel Xb250a/b + Xo250
    # ------------------------------------------------------------------
    x = 48.000
    u250, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=0.900)
    add("rst_n", u250["rst_n"], "metal3")
    ua250, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 3, gap_l=1.000, trk_g=2)
    ub250, x = scc.place_inv(c, cache, row, x, 3.0, 6.0, 2, 2, gap_l=0.900, trk_g=2)
    uo250, x = scc.place_inv(c, cache, row, x, 1.5, 3.0, 1, 2, gap_l=1.000, trk_g=2)
    # Self-feedback + parallel Xb250b input: clk250b_i (u250.qb -> u250.d AND -> ub250.a) on NMOS M2 Y_M2_N2!
    _local_m2_nmos_strap(c, u250["qb"][0], u250["d"][0], Y_M2_N2, src_y1=2.510, dst_y1=None)
    c.wire("metal1", [(ub250["a"][0], Y_M2_N2), (ub250["a"][0], y2)], slc.W_M1)
    c.via1(ub250["a"][0], Y_M2_N2)
    c.wire("metal2", [(u250["qb"][0], Y_M2_N2), (ub250["a"][0], Y_M2_N2)], 0.240)
    # clk250_i: u250.q -> ua250.a on direct pure M1 at y=6.65!
    c.wire("metal1", [(u250["q"][0], 5.990), (u250["q"][0], Y_M1_HOP), (ua250["a"][0], Y_M1_HOP), ua250["a"]], slc.W_M1)
    # clk250_out = ~clk250 = clk250b (C2 fix: ub250.y -> uo250.a on local PMOS M2 P2!)
    _local_m2_pmos_strap(c, ub250["y_col_x"], uo250["a"][0], Y_M2_P2, src_y0=5.990, dst_y0=y2)
    add("clk250b",    ua250["y"])
    add("clk250",     ub250["y"])
    add("clk250_out", uo250["y"])

    # ------------------------------------------------------------------
    # 2. Center Group (x ~ 89.5..118.5): 4-phase clock buffers Xc0..Xc27b (v4.3 strengthened!)
    # ------------------------------------------------------------------
    x = 89.500
    clk_specs = [
        ("phi0",   "c0",   2.4, 4.8, 4.4, 8.8, 2, 2, 2, 3),
        ("phi90",  "c90",  2.0, 4.0, 3.6, 7.2, 1, 2, 2, 3),
        ("phi180", "c180", 2.0, 4.0, 3.6, 7.2, 1, 2, 2, 3),
        ("phi270", "c270", 2.0, 4.0, 3.6, 7.2, 1, 2, 2, 3),
    ]
    for pin_in, pin_out, wn1, wp1, wn2, wp2, nfn1, nfp1, nfn2, nfp2 in clk_specs:
        u1, x = scc.place_inv(c, cache, row, x, wn1, wp1, nfn1, nfp1, gap_l=1.100, trk_g=2)
        u2, x = scc.place_inv(c, cache, row, x, wn2, wp2, nfn2, nfp2, gap_l=0.800, trk_g=2)
        c.wire("metal1", [(u1["y_col_x"], y2), u2["a"]], slc.W_M1)
        add(pin_in,  u1["a"])
        add(pin_out, u2["y"])

    # ------------------------------------------------------------------
    # 3. Right-Center Group (x ~ 121.0..158.0): parallel Xb500a/b + Xo500 + /2 divider Xdiv500
    # ------------------------------------------------------------------
    x = grid(max(x + 2.000, 121.000))
    ua500, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 3, gap_l=1.000, trk_g=2)
    ub500, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 3, gap_l=0.900, trk_g=2)
    uo500, x = scc.place_inv(c, cache, row, x, 1.5, 3.0, 1, 2, gap_l=1.000, trk_g=2)
    _local_m2_pmos_strap(c, ua500["y_col_x"], uo500["a"][0], Y_M2_P2, src_y0=5.990, dst_y0=y2)
    add("clk500b",    ua500["y"])
    add("clk500",     ub500["y"])
    add("clk500_out", uo500["y"])

    u500, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=1.100)
    add("c0",    u500["clk"])
    add("rst_n", u500["rst_n"], "metal3")
    # Self-feedback + parallel Xb500b input: clk500b_i (u500.qb -> u500.d AND -> ub500.a) on NMOS M2 Y_M2_N2!
    _local_m2_nmos_strap(c, u500["qb"][0], u500["d"][0], Y_M2_N2, src_y1=2.510, dst_y1=None)
    c.wire("metal1", [(ub500["a"][0], Y_M2_N2), (ub500["a"][0], y2)], slc.W_M1)
    c.via1(ub500["a"][0], Y_M2_N2)
    c.wire("metal2", [(ub500["a"][0], Y_M2_N2), (u500["d"][0], Y_M2_N2)], 0.240)

    # clk500_i: u500.q -> ua500.a -> u250.clk on single continuous local PMOS M2 P1 strap!
    x_q500 = u500["q"][0]
    x_a500 = ua500["a"][0]
    x_c250 = u250["clk"][0]
    c.wire("metal1", [(x_q500, 5.990), (x_q500, Y_M2_P1)], slc.W_M1)
    c.via1(x_q500, Y_M2_P1)
    c.wire("metal1", [(x_a500, y2), (x_a500, Y_M2_P1)], slc.W_M1)
    c.via1(x_a500, Y_M2_P1)
    c.wire("metal1", [(x_c250, y2), (x_c250, Y_M2_P1)], slc.W_M1)
    c.via1(x_c250, Y_M2_P1)
    c.wire("metal2", [(x_c250, Y_M2_P1), (x_q500, Y_M2_P1)], 0.240)

    return c, nets, x


def build_sst_serializer16(
    cache: PdkCache,
    add_ports: bool = True,
    north_pin_xs: dict[str, float] | None = None,
) -> tuple[Cell, dict]:
    """Build complete `serdes_tx_sst_serializer16_pdk` macro (~227.7 x 53.1 um).

    Optional `north_pin_xs` lets `serdes_tx_sst_top_pdk` specify exact X coordinates for
    `phi0..phi270, d0..d3, db0..db3` so serializer North pins abut driver South pins 1:1.
    """
    c = Cell()
    row = scc.ROW_SER
    H = row.height  # 9.500

    # Build 5 rows (v4.3: 500 ps stagger lead c180/c270/c0/c90 -> >=200 ps setup at SS -40C RCX!)
    r0_c, r0_n, r0_w = _build_lane_row(
        cache, 0, ("din0", "din4", "din8", "din12"),
        [("c180", "l0", 1.5, 3.0, "d0", "db0")],
    )
    r1_c, r1_n, r1_w = _build_lane_row(
        cache, 1, ("din1", "din5", "din9", "din13"),
        [("c270", "l1", 1.5, 3.0, "d1", "db1")],
    )
    r2_c, r2_n, r2_w = _build_clk_div_row(cache)
    r3_c, r3_n, r3_w = _build_lane_row(
        cache, 2, ("din2", "din6", "din10", "din14"),
        [("c180", "l2", 1.5, 3.0, "l2h", None), ("c0", "l2h", 1.5, 3.0, "d2", "db2")],
    )
    r4_c, r4_n, r4_w = _build_lane_row(
        cache, 3, ("din3", "din7", "din11", "din15"),
        [("c180", "l3", 1.5, 3.0, "l3h", None), ("c90", "l3h", 1.5, 3.0, "d3", "db3")],
    )

    # Stagger the 4 lane rows by 1.20 um (> 0.96 um M4 pitch) so identical-column pins never collide on M4!
    row_dxs = [0.000, 1.200, 0.000, 2.400, 3.600]
    x_max_w = grid(max(r0_w, r1_w + 1.2, r2_w, r3_w + 2.4, r4_w + 3.6) + 1.500)
    x_row_l = -1.000
    x_row_r = x_max_w
    for rc, rdx in zip((r0_c, r1_c, r2_c, r3_c, r4_c), row_dxs):
        scc.finish_cmos_row(rc, row, grid(x_row_l - rdx), grid(x_row_r - rdx), tap_pitch=1.6)

    # Compact 5-row abutted mirrored placement (shared VDD/VSS rails, ChA = ChB = 0.0 um!):
    #   Row 0 (normal):  VSS=0.00,  VDD=9.50
    #   Row 1 (mirror):  VDD=9.50,  VSS=19.00
    #   Row 2 (normal):  VSS=19.00, VDD=28.50
    #   Row 3 (mirror):  VDD=28.50, VSS=38.00
    #   Row 4 (normal):  VSS=38.00, VDD=47.50
    #   Channel C (North interface bay): y in [47.50 .. 51.00] (3.50 um)
    y_r0 = 0.000
    y_r1 = grid(2.0 * H)          # 19.000 (mirror_y -> VDD=9.50, VSS=19.00)
    y_r2 = y_r1                   # 19.000 (normal   -> VSS=19.00 shared with Row 1, VDD=28.50)
    y_r3_vss = grid(4.0 * H)      # 38.000 (mirror_y -> VDD=28.50 shared with Row 2, VSS=38.00)
    y_r4_vss = y_r3_vss           # 38.000 (normal   -> VSS=38.00 shared with Row 3, VDD=47.50)
    y_top = grid(5.0 * H)         # 47.500

    row_cfgs = [
        (r0_c, r0_n, row_dxs[0], y_r0,     False),
        (r1_c, r1_n, row_dxs[1], y_r1,     True),
        (r2_c, r2_n, row_dxs[2], y_r2,     False),
        (r3_c, r3_n, row_dxs[3], y_r3_vss, True),
        (r4_c, r4_n, row_dxs[4], y_r4_vss, False),
    ]
    all_nets: dict[str, list[tuple[float, float, str]]] = {}
    for rc, rn, rdx, y_vss_w, mir in row_cfgs:
        mapped = _add_row_transformed(c, rc, rn, rdx, y_vss_w, mir)
        for net, pts in mapped.items():
            all_nets.setdefault(net, []).extend(pts)

    # Power rail straps: parallel 0.48 um M2 atop ALL 6 M1 rails + West VSS & East VDD M3/M4/M5 spines!
    x_vss_w = grid(x_row_l - 2.600)
    x_vss_m5_w = -3.300            # width 1.80 -> [-4.20..-2.40] (flush x=0.000 in top at dx=+4.20!)
    x_rst_w = grid(x_row_l - 0.500) # -1.500 -> 0.53 um M4 gap to x_vss_m5_w via4 M4 (-2.25)!
    x_vdd_e = grid(x_row_r + 1.400)
    x_vdd_m5_e = grid(max(225.200, x_vdd_e + 1.400))  # aligns with driver x_vdd_m5_e in top!
    vss_ys = [y_r0, y_r1, y_r3_vss]
    vdd_ys = [grid(y_r0 + H), grid(y_r2 + H), y_top]
    # Parallel M2 over-straps on every M1 power rail (0.48 um wide -> >=0.19 um clear of y_s1 M2!)
    for yv in vss_ys + vdd_ys:
        c.wire("metal2", [(x_row_l, yv), (x_row_r, yv)], 0.480)
        n_v1 = max(2, int((x_row_r - x_row_l) // 4.0) + 1)
        for i in range(n_v1 + 1):
            c.via1(grid(x_row_l + 0.400 + (x_row_r - x_row_l - 0.800) * i / n_v1), yv)

    for yv in vss_ys:
        c.wire("metal1", [(x_vss_w, yv), (x_row_l, yv)], 0.560)
        c.wire("metal2", [(x_vss_w, yv), (x_row_l, yv)], 0.560)
        c.via1(x_vss_w, yv)
        via2_clean(c, x_vss_w, yv)
        via3_array(c, x_vss_w, yv, nx=2, ny=2)
        c.wire("metal4", [(x_vss_w, yv), (x_vss_m5_w, yv)], 1.400)
        via4_array(c, x_vss_m5_w, yv, nx=1, ny=1)
        c.wire("metal5", [(x_vss_m5_w, yv), (220.000, yv)], 1.800)
    c.wire("metal3", [(x_vss_w, vss_ys[0]), (x_vss_w, vss_ys[-1])], 1.200)
    c.wire("metal5", [(x_vss_m5_w, vss_ys[0]), (x_vss_m5_w, vss_ys[-1])], 1.800)

    for yv in vdd_ys:
        c.wire("metal1", [(x_row_r, yv), (x_vdd_e, yv)], 0.560)
        c.wire("metal2", [(x_row_r, yv), (x_vdd_e, yv)], 0.560)
        c.via1(x_vdd_e, yv)
        via2_clean(c, x_vdd_e, yv)
        via3_array(c, x_vdd_e, yv, nx=2, ny=2)
        c.wire("metal4", [(x_vdd_e, yv), (x_vdd_m5_e, yv)], 1.400)
        via4_array(c, x_vdd_m5_e, yv, nx=1, ny=1)
        c.wire("metal5", [(1.000, yv), (x_vdd_m5_e, yv)], 1.800)
    c.wire("metal3", [(x_vdd_e, vdd_ys[0]), (x_vdd_e, vdd_ys[-1])], 1.200)
    c.wire("metal5", [(x_vdd_m5_e, vdd_ys[0]), (x_vdd_m5_e, vdd_ys[-1])], 2.000)

    # Distributed mid-rail M5-to-M2 stitch pillars across all 6 power rails (auto-nudge clear of pin X!)
    all_pin_xs = [px for net, pts in all_nets.items() if net != "rst_n" for px, _, _ in pts]
    ser_pwr_pillars: list[tuple[float, float]] = []
    base_pillar_xs = (37.700, 83.300, 141.500, 186.600, 210.800)
    ser_pillar_xs = []
    for x0 in base_pillar_xs:
        xp = x0
        for off in (0.0, 2.0, -2.0, 4.0, -4.0, 6.0, -6.0, 8.0, -8.0):
            cand = grid(x0 + off)
            if 5.0 <= cand <= x_row_r - 2.0 and all(abs(cand - px) >= 2.200 for px in all_pin_xs):
                xp = cand
                break
        ser_pillar_xs.append(xp)
    for yv in vss_ys + vdd_ys:
        for xp in ser_pillar_xs:
            if xp <= x_row_r - 1.500:
                via4_array(c, xp, yv, nx=1, ny=1)
                via3_array(c, xp, yv, nx=2, ny=1)
                for dxv in (-0.300, +0.300):
                    via2_clean(c, grid(xp + dxv), yv)
                ser_pwr_pillars.append((xp, yv))

    # Collinear horizontal M3 `rst_n` buses across each row, joined on M4 at x_rst_w
    rst_pts = all_nets.pop("rst_n", [])
    rst_by_y: dict[float, list[float]] = {}
    for px, py, _ in rst_pts:
        rst_by_y.setdefault(grid(py), []).append(px)
    y_south_port = -1.600
    y_north_port = grid(y_top + 2.000)  # 49.500 (2.0 um North bay; Row 4 VDD sits 2.0 um below y_north_port)
    rst_ys = sorted(rst_by_y.keys())
    for ry in rst_ys:
        xs_r = rst_by_y[ry]
        c.wire("metal3", [(x_rst_w, ry), (max(xs_r), ry)], 0.360)
        via3_pad(c, x_rst_w, ry)
    c.wire("metal4", [(x_rst_w, y_south_port), (x_rst_w, max(rst_ys))], 0.440)

    # Over-cell + Channel C M3 tracks (0.90 um pitch, strictly clear of the 5 `rst_n` M3 lines)
    raw_tracks = [grid(0.600 + 0.900 * k) for k in range(int((y_north_port - 0.80) / 0.900) + 1)]
    m3_tracks = [yt for yt in raw_tracks if all(abs(yt - ry) >= 0.880 for ry in rst_ys)]
    # Prefer pin-free diff-band seams (Row0-1 VDD, Row1-2 VSS, Row2-3 VDD, Row4 PMOS + ChC)
    pref_tracks = {
        yt for yt in m3_tracks
        if (7.5 <= yt <= 11.4) or (19.2 <= yt <= 21.4) or (25.1 <= yt <= 30.8) or (45.5 <= yt <= 48.6)
    }
    router = ManhattanRouter(m3_tracks, m4_min_pitch=0.960, preferred_tracks=pref_tracks)
    for xp, yp in ser_pwr_pillars:
        for yt in m3_tracks:
            if abs(yt - yp) <= 0.900:
                router.reserve_m3_span(yt, grid(xp - 1.100), grid(xp + 1.100), "__ser_pwr__")
        for dx_r in (-0.800, 0.000, +0.800):
            router.reserve_m4_seg(grid(xp + dx_r), grid(yp - 1.100), grid(yp + 1.100), "__ser_pwr__")
    for ry in rst_ys:
        router.reserve_m3_span(ry, x_rst_w - 0.5, x_row_r + 0.5, "rst_n")
    router.reserve_m4_seg(x_rst_w, y_south_port, max(rst_ys), "rst_n")

    # Direct zero-M3 vertical M4 drops for all 16 parallel data inputs `din0..din15`!
    south_ports: dict[str, tuple[float, float]] = {"rst_n": (x_rst_w, y_south_port)}
    for i in range(16):
        pnm = f"din{i}"
        px, py, _lyr = all_nets.pop(pnm)[0]
        c.via1(px, py)
        via2_clean(c, px, py)
        via3_pad(c, px, py)
        c.wire("metal4", [(px, y_south_port), (px, py)], 0.520)
        router.reserve_m3_pad(px, py, pnm)
        router.reserve_m4_seg(px, y_south_port, py, pnm)
        south_ports[pnm] = (px, y_south_port)

    # South perimeter ports for `clk250_out` and `clk500_out` directly beneath Xo250 / Xo500!
    for pnm in ("clk250_out", "clk500_out"):
        px_src = all_nets[pnm][0][0]
        px = grid(px_src)
        south_ports[pnm] = (px, y_south_port)
        all_nets[pnm].append((px, y_south_port, "metal4"))

    # North perimeter ports aligned 1:1 with Step 1 `serdes_tx_sst_driver_pdk` South ports!
    north_order = [
        "phi0", "phi90", "phi180", "phi270",
        "d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3",
    ]
    north_ports: dict[str, tuple[float, float]] = {}
    for pnm in north_order:
        px = grid(north_pin_xs[pnm]) if (north_pin_xs and pnm in north_pin_xs) else DEFAULT_NORTH_PIN_XS[pnm]
        north_ports[pnm] = (px, y_north_port)
        all_nets.setdefault(pnm, []).append((px, y_north_port, "metal4"))

    # Preferred trunk Y hints: separate d0..db3 across Row0-1, Row2-3, and Row4-ChC seams to cut lateral coupling!
    pref_y_map: dict[str, float] = {
        "clk250":     20.400,
        "clk250b":    19.500,
        "clk500":     25.800,
        "clk500b":    21.300,
        "c0":         26.700,
        "c90":        27.600,
        "c180":       28.500,
        "c270":       20.400,
        "phi0":       29.400,
        "phi90":      30.300,
        "phi180":     29.400,
        "phi270":     30.300,
        "clk250_out": 19.500,
        "clk500_out": 20.400,
        "d0":          8.700,
        "db0":        10.500,
        "d1":          9.600,
        "db1":        11.400,
        "d2":         29.400,
        "db2":        30.300,
        "d3":         46.500,
        "db3":        48.300,
    }

    # Route M4-port nets first (claim clean straight vertical drops), then shortest spans first!
    router.pre_register_nets(all_nets)
    net_order = sorted(
        all_nets.items(),
        key=lambda kv: (0 if any(p[2] == "metal4" for p in kv[1]) else 1, max(p[0] for p in kv[1]) - min(p[0] for p in kv[1])),
    )
    for net_name, plist in net_order:
        router.route_net(c, net_name, plist, pref_y=pref_y_map.get(net_name))

    # Export exact 33 schematic ports
    port_locs: dict[str, tuple[str, float, float]] = {}
    for pnm, (px, py) in south_ports.items():
        port_locs[pnm] = ("metal4", px, py)
    for pnm, (px, py) in north_ports.items():
        port_locs[pnm] = ("metal4", px, py)
    port_locs["vdd"] = ("metal5", x_vdd_m5_e, vdd_ys[-1])
    port_locs["vss"] = ("metal5", x_vss_m5_w, vss_ys[0])

    if add_ports:
        order = (
            [f"din{i}" for i in range(16)]
            + ["phi0", "phi90", "phi180", "phi270", "rst_n"]
            + ["d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3"]
            + ["clk500_out", "clk250_out", "vdd", "vss"]
        )
        for pnm in order:
            lyr, px, py = port_locs[pnm]
            c.port(pnm, lyr, px, py)

    return c, {
        "ports": port_locs,
        "north_ports": north_ports,
        "south_ports": south_ports,
        "x_vss_w": x_vss_w,
        "x_vss_m5_w": x_vss_m5_w,
        "x_vdd_e": x_vdd_e,
        "x_vdd_m5_e": x_vdd_m5_e,
        "y_north_port": y_north_port,
        "y_south_port": y_south_port,
        "vss_ys": vss_ys,
        "vdd_ys": vdd_ys,
    }


if __name__ == "__main__":
    import json
    work = slc.REPO / "results/layout/tx_sst_v4/test_serializer"
    cache = PdkCache(work / "_cache")
    cell, meta = build_sst_serializer16(cache, add_ports=True)
    name = "serdes_tx_sst_serializer16_pdk"
    mag = work / f"{name}.mag"
    ref = work / f"{name}_ref.spice"
    cell.write(mag)
    ports = slc.generate_ref_spice("serdes_tx_sst_serializer16", name, ref)
    rep = slc.verify_flat_cell(work, name, mag, ref, ports, timeout_s=180)
    print(json.dumps({k: v for k, v in rep.items() if k != "parasitics"}, indent=2))
    if rep["parasitics"]:
        pc = rep["parasitics"].get("port_caps_fF", {})
        print("Sample port caps (fF):", json.dumps({k: pc[k] for k in ("phi0", "d0", "db0", "clk500_out", "clk250_out", "vdd") if k in pc}, indent=2))
