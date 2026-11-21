#!/usr/bin/env python3
"""Physical PDK layout builder for `serdes_tx_sst_serializer16_pdk` (Pure 1 GHz Static CMOS
16:4 Quarter-Rate Serializer + /2 & /4 Dividers + 4-Phase Stagger Retimer).

Floorplan (~240 x 51 um = ~12,200 um^2, 5 mirrored standard CMOS rows `ROW_SER` H=9.50 um):
  - Row 0 (y=0.0..9.5,   normal): Lane 0 (Xr0..Xr3, Xma, Xmb, Xda, Xdb, Xmc, Xd1g, Xst0)
  - Row 1 (y=9.5..19.0,  mirror): Lane 1 (Xr0..Xr3, Xma, Xmb, Xda, Xdb, Xmc, Xd1g, Xst1)
  - Row 2 (y=19.0..28.5, normal): Clock buffers (Xc0..Xc27b) + Dividers (Xdiv500, Xdiv250) + Export bufs
  - Row 3 (y=28.5..38.0, mirror): Lane 2 (Xr0..Xr3, Xma, Xmb, Xda, Xdb, Xmc, Xd1g, Xst2a, Xst2b)
  - Row 4 (y=38.0..47.5, normal): Lane 3 (Xr0..Xr3, Xma, Xmb, Xda, Xdb, Xmc, Xd1g, Xst3a, Xst3b)

North perimeter pins (`d0..d3, db0..db3, phi0..phi270`) align 1-to-1 with the South perimeter
of `serdes_tx_sst_driver_pdk` for abutment in `serdes_tx_sst_top_pdk`.
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
)
import sst_cmos_cells as scc  # noqa: E402


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

    `stagger_spec`: list of `(clk_net, d_in_net, wn, wp, q_net, qb_net)`.
    """
    row = scc.ROW_SER
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}
    p = f"L{lane_idx}"

    def add(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    def wire_dff(u: dict, d_n: str, ck_n: str, q_n: str | None, qb_n: str | None) -> None:
        add(d_n, u["d"])
        add(ck_n, u["clk"])
        add("rst_n", u["rst_n"], "metal3")
        if q_n is not None:
            add(q_n, u["q"])
        if qb_n is not None:
            add(qb_n, u["qb"])

    x = 0.0
    # Stage 0: 4x 250 MHz input capture DFFs (wn=0.8, wp=1.6)
    for k in range(4):
        u, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
        wire_dff(u, dins[k], "clk250", f"{p}_r{k}", None)

    # Stage 1: 4:2 MUX (Xma, Xmb, wn=0.9, wp=1.8) + 2x 500 MHz DFFs (Xda, Xdb, wn=1.0, wp=2.0)
    # Extra gap_l=1.360 before mux2 keeps mux2's left x_l M1 strap >= 0.25 um clear of previous cell's drain!
    for m_nm, a_n, b_n, y_n in (
        ("ma", f"{p}_r2", f"{p}_r0", f"{p}_ma"),
        ("mb", f"{p}_r3", f"{p}_r1", f"{p}_mb"),
    ):
        u, x = scc.place_mux2(c, cache, row, x, wn=0.9, wp=1.8, gap_l=1.360)
        add(a_n, u["a"])
        add(b_n, u["b"])
        add("clk250", u["sel"], "metal2")
        add("clk250b", u["sel_b"], "metal2")
        add(y_n, u["y"])

    for d_in, q_out in ((f"{p}_ma", f"{p}_da"), (f"{p}_mb", f"{p}_db")):
        u, x = scc.place_dff_r(c, cache, row, x, wn=1.0, wp=2.0, gap_l=0.900)
        wire_dff(u, d_in, "clk500b", q_out, None)

    # Stage 2: 2:1 MUX (Xmc, wn=1.2, wp=2.4) + 1 GHz DFF (Xd1g, wn=1.4, wp=2.8)
    u, x = scc.place_mux2(c, cache, row, x, wn=1.2, wp=2.4, gap_l=1.360)
    add(f"{p}_da", u["a"])
    add(f"{p}_db", u["b"])
    add("clk500", u["sel"], "metal2")
    add("clk500b", u["sel_b"], "metal2")
    add(f"{p}_mc", u["y"])

    u, x = scc.place_dff_r(c, cache, row, x, wn=1.4, wp=2.8, gap_l=0.900)
    wire_dff(u, f"{p}_mc", "c0", f"l{lane_idx}", None)

    # Stage 3: 4-Phase Stagger Retimer DFF(s)
    for ck_n, d_in, wn, wp, q_n, qb_n in stagger_spec:
        u, x = scc.place_dff_r(c, cache, row, x, wn=wn, wp=wp, gap_l=0.900)
        wire_dff(u, d_in, ck_n, q_n, qb_n)

    return c, nets, x


def _build_clk_div_row(cache: PdkCache) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build center clock-buffer + /2 & /4 divider row (`Row 2`) on `ROW_SER`."""
    row = scc.ROW_SER
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    x = 0.0
    y2 = row.y_tracks[2]
    # 1. Local 4-phase clock buffers Xc0..Xc27b (direct M1 link between stage 1 & stage 2 -> zero M3 tracks!)
    clk_specs = [
        ("phi0",   "c0",   2.0, 4.0, 3.5, 7.0),
        ("phi90",  "c90",  1.5, 3.0, 2.5, 5.0),
        ("phi180", "c180", 1.5, 3.0, 2.5, 5.0),
        ("phi270", "c270", 1.5, 3.0, 2.5, 5.0),
    ]
    for pin_in, pin_out, wn1, wp1, wn2, wp2 in clk_specs:
        u1, x = scc.place_inv(c, cache, row, x, wn1, wp1, 1, 2, gap_l=1.100, trk_g=2)
        u2, x = scc.place_inv(c, cache, row, x, wn2, wp2, 2, 3, gap_l=0.800, trk_g=2)
        c.wire("metal1", [(u1["y_col_x"], y2), u2["a"]], slc.W_M1)
        add(pin_in, u1["a"])
        add(pin_out, u2["y"])

    # 2. Static CMOS /2 and /4 dividers Xdiv500, Xdiv250
    u500, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=1.100)
    add("clk500b_i", u500["d"])
    add("c0",        u500["clk"])
    add("rst_n",     u500["rst_n"], "metal3")
    add("clk500_i",  u500["q"])
    add("clk500b_i", u500["qb"])

    u250, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=1.100)
    add("clk250b_i", u250["d"])
    add("clk500_i",  u250["clk"])
    add("rst_n",     u250["rst_n"], "metal3")
    add("clk250_i",  u250["q"])
    add("clk250b_i", u250["qb"])

    # 3. Buffered internal distribution clocks Xb500a/b, Xb250a/b & export buffers Xo500, Xo250
    #    Direct M1 link ua.y -> ub.a & uo.a (strictly adjacent -> zero M3 pinch!)
    for src_n, inv_n, buf_n, exp_n in (
        ("clk500_i", "clk500b", "clk500", "clk500_out"),
        ("clk250_i", "clk250b", "clk250", "clk250_out"),
    ):
        ua, x = scc.place_inv(c, cache, row, x, 2.5, 5.0, 2, 2, gap_l=1.200, trk_g=2)
        ub, x = scc.place_inv(c, cache, row, x, 2.5, 5.0, 2, 2, gap_l=1.000, trk_g=2)
        uo, x = scc.place_inv(c, cache, row, x, 1.5, 3.0, 1, 2, gap_l=1.200, trk_g=2)
        c.wire("metal1", [(ua["y_col_x"], y2), ub["a"]], slc.W_M1)
        add(src_n, ua["a"])
        add(inv_n, ua["y"])
        add(buf_n, ub["y"])
        add(inv_n, uo["a"])
        add(exp_n, uo["y"])

    return c, nets, x


def build_sst_serializer16(
    cache: PdkCache,
    add_ports: bool = True,
    north_pin_xs: dict[str, float] | None = None,
) -> tuple[Cell, dict]:
    """Build complete `serdes_tx_sst_serializer16_pdk` macro (~242 x 51 um).

    Optional `north_pin_xs` lets `serdes_tx_sst_top_pdk` specify exact X coordinates for
    `d0..d3, db0..db3, phi0..phi270` so serializer North pins abut driver South pins 1:1.
    """
    c = Cell()
    row = scc.ROW_SER
    H = row.height  # 9.500

    # Build 5 rows
    r0_c, r0_n, r0_w = _build_lane_row(
        cache, 0, ("din0", "din4", "din8", "din12"),
        [("c270", "l0", 1.5, 3.0, "d0", "db0")],
    )
    r1_c, r1_n, r1_w = _build_lane_row(
        cache, 1, ("din1", "din5", "din9", "din13"),
        [("c0", "l1", 1.5, 3.0, "d1", "db1")],
    )
    r2_c, r2_n, r2_w = _build_clk_div_row(cache)
    r3_c, r3_n, r3_w = _build_lane_row(
        cache, 2, ("din2", "din6", "din10", "din14"),
        [("c180", "l2", 1.2, 2.4, "l2h", None), ("c90", "l2h", 1.5, 3.0, "d2", "db2")],
    )
    r4_c, r4_n, r4_w = _build_lane_row(
        cache, 3, ("din3", "din7", "din11", "din15"),
        [("c180", "l3", 1.2, 2.4, "l3h", None), ("c180", "l3h", 1.5, 3.0, "d3", "db3")],
    )

    # Stagger the 5 rows in X by 1.20 um so identical-column pins across Lanes 0..3 NEVER share an M4 X!
    row_dxs = [0.000, 1.200, 0.000, 2.400, 3.600]
    x_max_w = grid(max(r0_w, r1_w + 1.2, r2_w, r3_w + 2.4, r4_w + 3.6) + 1.500)
    x_row_l = -1.000
    x_row_r = x_max_w
    for rc, rdx in zip((r0_c, r1_c, r2_c, r3_c, r4_c), row_dxs):
        scc.finish_cmos_row(rc, row, grid(x_row_l - rdx), grid(x_row_r - rdx), tap_pitch=12.0)

    # Row vertical placement with clean 7.2 um pin-free M3 routing channels around center clock/div row!
    #   Pair 0 (Row 0 + Row 1 mirrored at VDD=9.50):   y in [0.00 .. 19.00]
    #   Channel A (pin-free M3 routing bay):           y in [19.00 .. 26.20]
    #   Row 2 (Clock buffers + /2, /4 dividers):       y in [26.20 .. 35.70]
    #   Channel B (pin-free M3 routing bay):           y in [35.70 .. 42.90]
    #   Pair 1 (Row 3 + Row 4 mirrored at VDD=52.40):  y in [42.90 .. 61.90]
    #   Channel C (North interface bay):               y in [61.90 .. 67.50]
    y_r0 = 0.000
    y_r1 = grid(2.0 * H)          # 19.000 (mirror_y -> VDD=9.50, VSS=19.00)
    y_r2 = 26.200                 # normal   -> VSS=26.20, VDD=35.70
    y_r3 = grid(42.900 + H)       # 52.400? wait: mirror_y around y_vss!
    # Wait: if Row 3 is mirror_y with y_vss=52.40 -> VDD is at 52.40-9.50=42.90, VSS is at 52.40!
    # And Row 4 is normal with y_vss=52.40 -> VSS is at 52.40 (SHARED with Row 3!), VDD is at 61.90!
    y_r3_vss = grid(42.900 + H)   # 52.400
    y_r4_vss = y_r3_vss           # 52.400
    y_top = grid(y_r4_vss + H)    # 61.900

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

    # Power rail vertical straps: VSS OUTSIDE at x=-3.60 (so rst_n M3 at x=-2.00 NEVER crosses VSS M3!), VDD East!
    x_vss_w = grid(x_row_l - 2.600)
    x_rst_w = grid(x_row_l - 0.900)
    x_vdd_e = grid(x_row_r + 1.400)
    vss_ys = [y_r0, y_r1, y_r2, y_r3_vss]
    vdd_ys = [grid(y_r0 + H), grid(y_r2 + H), 42.900, y_top]
    for yv in vss_ys:
        c.wire("metal1", [(x_vss_w, yv), (x_row_l, yv)], 0.560)
        c.via1(x_vss_w, yv)
        via2_clean(c, x_vss_w, yv)
    c.wire("metal3", [(x_vss_w, vss_ys[0]), (x_vss_w, vss_ys[-1])], 1.200)

    for yv in vdd_ys:
        c.wire("metal1", [(x_row_r, yv), (x_vdd_e, yv)], 0.560)
        c.via1(x_vdd_e, yv)
        via2_clean(c, x_vdd_e, yv)
    c.wire("metal3", [(x_vdd_e, vdd_ys[0]), (x_vdd_e, vdd_ys[-1])], 1.200)

    # Collinear horizontal M3 `rst_n` buses across each row, joined on M4 at x_rst_w (strictly EAST of x_vss_w!)
    rst_pts = all_nets.pop("rst_n", [])
    rst_by_y: dict[float, list[float]] = {}
    for px, py, _ in rst_pts:
        rst_by_y.setdefault(grid(py), []).append(px)
    y_south_port = -2.200
    y_north_port = grid(y_top + 6.400)
    rst_ys = sorted(rst_by_y.keys())
    for ry in rst_ys:
        xs_r = rst_by_y[ry]
        c.wire("metal3", [(x_rst_w, ry), (max(xs_r), ry)], 0.360)
        via3_pad(c, x_rst_w, ry)
    c.wire("metal4", [(x_rst_w, y_south_port), (x_rst_w, max(rst_ys))], 0.440)

    # Build M3 horizontal tracks strictly clear of the 5 `rst_n` M3 lines, preferring pin-free channels first!
    raw_tracks = [grid(0.600 + 0.900 * k) for k in range(int((y_north_port - 1.2) / 0.900) + 1)]
    m3_tracks = [yt for yt in raw_tracks if all(abs(yt - ry) >= 0.880 for ry in rst_ys)]
    pref_tracks = {
        yt for yt in m3_tracks
        if (19.4 <= yt <= 25.8) or (36.1 <= yt <= 42.5) or (62.3 <= yt <= 67.5)
    }
    router = ManhattanRouter(m3_tracks, m4_min_pitch=0.960, preferred_tracks=pref_tracks)
    for ry in rst_ys:
        router.reserve_m3_span(ry, x_rst_w - 0.5, x_row_r + 0.5, "rst_n")
    router.reserve_m4_seg(x_rst_w, y_south_port, max(rst_ys), "rst_n")

    # South perimeter ports (din0..din15 aligned under Xr0..Xr3 in [2..80], clk500/250_out clear in [104..116])
    south_order = [f"din{i}" for i in range(16)] + ["clk500_out", "clk250_out"]
    south_ports: dict[str, tuple[float, float]] = {"rst_n": (x_rst_w, y_south_port)}
    for idx, pnm in enumerate(south_order):
        px = grid(2.000 + idx * 5.200) if idx < 16 else grid(106.0 + (idx - 16) * 8.000)
        south_ports[pnm] = (px, y_south_port)
        all_nets.setdefault(pnm, []).append((px, y_south_port, "metal4"))

    # North perimeter ports (phi0..phi270, d0..d3, db0..db3) aligned 1:1 with Driver South ports!
    north_order = [
        "phi0", "phi90", "phi180", "phi270",
        "d0", "db0", "d1", "db1", "d2", "db2", "d3", "db3",
    ]
    north_ports: dict[str, tuple[float, float]] = {}
    for idx, pnm in enumerate(north_order):
        px = grid(north_pin_xs[pnm]) if (north_pin_xs and pnm in north_pin_xs) else grid(109.0 + idx * 7.200)
        north_ports[pnm] = (px, y_north_port)
        all_nets.setdefault(pnm, []).append((px, y_north_port, "metal4"))

    # Route M4-port nets first (claim clean straight vertical drops), then shortest spans first!
    router.pre_register_nets(all_nets)
    net_order = sorted(
        all_nets.items(),
        key=lambda kv: (0 if any(p[2] == "metal4" for p in kv[1]) else 1, max(p[0] for p in kv[1]) - min(p[0] for p in kv[1])),
    )
    for net_name, plist in net_order:
        router.route_net(c, net_name, plist)

    # Export exact 33 schematic ports
    port_locs: dict[str, tuple[str, float, float]] = {}
    for pnm, (px, py) in south_ports.items():
        port_locs[pnm] = ("metal4", px, py)
    for pnm, (px, py) in north_ports.items():
        port_locs[pnm] = ("metal4", px, py)
    port_locs["vdd"] = ("metal3", x_vdd_e, vdd_ys[-1])
    port_locs["vss"] = ("metal3", x_vss_w, vss_ys[0])

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
        "x_vdd_e": x_vdd_e,
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
