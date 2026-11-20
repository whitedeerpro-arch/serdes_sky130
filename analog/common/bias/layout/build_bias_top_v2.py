"""Integrated BIAS v2 Top Macro Layout Builder (serdes_bias_top_v2_pdk).

4-Band unified perimeter-pinned macro (<= 27,000 um^2):
  Band 4 (Top)    : Xm_2x12 (2D CC core PMOS) + 4x3 PNP thermal island
  Band 3 (Hi-Mid) : Folded-cascode core OTA + V->I OTA + Startup + Calibrated Res_all + Xs0..4 + 2x2 Stacked MIM
  Band 2 (Lo-Mid) : Unified pc_2x40 x 2 shared-Nwell mirror bank (153 active + 7 dummies, internal vgi, 0 LU.3!)
  Band 1 (Bottom) : Compact vbuf_v2 (horiz Xr) + Compact pbuf_v2 (horiz Xr0 + 2-row 4->16 CMOS decoder + LVT OTA)

All 20 top-level ports cleanly on the outer macro perimeter:
  Top    : vbg, vdd
  Left   : icml, ictle, icp, i_ldo0, i_ldo1
  Right  : g0, g1, g2, g3, g4
  Bottom : vcm, vss, c0, c1, c2, c3, en_pbuf, pref
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "verification/layout"))
from geometry import Cell


def rot90(src: Cell) -> Cell:
    """Rotate a flat Cell 90 degrees CCW: (x, y) -> (-y, x)."""
    dst = Cell()
    for lay, rects in src.rects.items():
        for x1, y1, x2, y2 in rects:
            dst.rect(lay, -y2, x1, -y1, x2)
    for lay, x, y, nm in src.labels:
        dst.labels.append((lay, -y, x, nm))
    return dst


def build_bias_top_v2(root: Path, bmod) -> dict:
    """Build and verify integrated serdes_bias_top_v2_pdk using helpers from build_bias_v2_pdk."""
    grid = bmod.grid
    clean_primitive = bmod.clean_primitive
    sd_xs_of = bmod.sd_xs_of
    gate_pts_of = bmod.gate_pts_of
    draw_m1_guard_ring = bmod.draw_m1_guard_ring
    via3 = bmod.via3
    via3_array = bmod.via3_array
    via4_array = bmod.via4_array
    _add_outer_ppolyres_dummies = bmod._add_outer_ppolyres_dummies
    _place_mim_stack_site = bmod._place_mim_stack_site
    _cmos_row_rails = bmod._cmos_row_rails
    verify_cell = bmod.verify_cell
    MIM1, MIM2, PNP_MAG = bmod.MIM1, bmod.MIM2, bmod.PNP_MAG

    cell = "serdes_bias_top_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # 0. GENERATE / CACHE CLEAN SKY130 PRIMITIVES
    # =========================================================================
    xm_p = clean_primitive(w, "bg_xm_2x12", "sky130_fd_pr__pfet_01v8_lvt",
                           dict(w=14.0, l=12.0, nf=12, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    fc_fab = clean_primitive(w, "fc_fab", "sky130_fd_pr__pfet_01v8_lvt",
                             dict(w=12.0, l=8.0, nf=6, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    fc_pc = clean_primitive(w, "fc_pc4", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=12.0, l=2.5, nf=4, m=1, guard=1, conn_gates=1, topc=0, botc=1, doports=1))
    fc_pb = clean_primitive(w, "fc_pb", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=12.0, l=8.0, nf=2, m=1, guard=1, conn_gates=1, topc=0, botc=1, doports=1))
    fc_pbc = clean_primitive(w, "fc_pbc", "sky130_fd_pr__pfet_01v8_lvt",
                             dict(w=3.0, l=4.0, nf=1, m=1, guard=1, conn_gates=1, topc=0, botc=1, doports=1))
    fc_ab = clean_primitive(w, "fc_ab", "sky130_fd_pr__nfet_01v8",
                            dict(w=6.0, l=4.0, nf=10, m=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    fc_nc = clean_primitive(w, "fc_nc4", "sky130_fd_pr__nfet_01v8",
                            dict(w=4.0, l=4.0, nf=4, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    fc_nm = clean_primitive(w, "fc_nm", "sky130_fd_pr__nfet_01v8",
                            dict(w=4.0, l=8.0, nf=6, m=2, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    fc_t = clean_primitive(w, "fc_t", "sky130_fd_pr__nfet_01v8",
                           dict(w=3.0, l=4.0, nf=2, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    fc_nbp = clean_primitive(w, "fc_nbp", "sky130_fd_pr__nfet_01v8",
                             dict(w=3.0, l=4.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    fc_nbc = clean_primitive(w, "fc_nbc", "sky130_fd_pr__nfet_01v8",
                             dict(w=1.5, l=10.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    ota_pl = clean_primitive(w, "ota_pl_1x4", "sky130_fd_pr__pfet_01v8_lvt",
                             dict(w=12.0, l=8.0, nf=4, m=1, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    ota_np = clean_primitive(w, "ota_np", "sky130_fd_pr__nfet_01v8",
                             dict(w=6.0, l=4.0, nf=10, m=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    ota_xt = clean_primitive(w, "ota_xt", "sky130_fd_pr__nfet_01v8",
                             dict(w=1.0, l=6.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    st_sp = clean_primitive(w, "st_sp_ng", "sky130_fd_pr__pfet_01v8",
                            dict(w=0.42, l=20.0, nf=1, m=1, guard=0, conn_gates=1, topc=0, botc=1, doports=1))
    st_sn = clean_primitive(w, "st_sn", "sky130_fd_pr__nfet_01v8",
                            dict(w=2.0, l=1.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    st_su = clean_primitive(w, "st_su", "sky130_fd_pr__nfet_01v8",
                            dict(w=1.0, l=1.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    xk_p = clean_primitive(w, "bg_xk", "sky130_fd_pr__nfet_01v8_lvt",
                           dict(w=2.0, l=4.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    xs_sw = clean_primitive(w, "bg_xsw", "sky130_fd_pr__nfet_01v8",
                            dict(w=5.0, l=0.18, nf=4, m=1, guard=0, conn_gates=1, topc=1, botc=1, doports=1))
    r_rs = clean_primitive(w, "bg_rrs10", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=39.200, nx=10, m=1, guard=0))
    r_r2a = clean_primitive(w, "bg_rr2_5", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=37.650, nx=5, m=1, guard=0))
    r_r1 = clean_primitive(w, "bg_rr1", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=39.790, nx=1, m=1, guard=0))
    r_rf = clean_primitive(w, "bg_rrf10", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=33.900, nx=10, m=1, guard=0))
    r_rt = [
        clean_primitive(w, f"bg_rrt{i}", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=lv, nx=1, m=1, guard=0))
        for i, lv in enumerate((1.265, 3.725, 8.645, 18.480, 38.150))
    ]
    mim_side = 22.1965
    m1_21 = clean_primitive(w, "bg_m1_21", MIM1, dict(w=mim_side, l=mim_side, nx=2, ny=1, stack=1, doports=1))
    m2_21 = clean_primitive(w, "bg_m2_21", MIM2, dict(w=mim_side, l=mim_side, nx=2, ny=1, doports=1))
    m1_11 = clean_primitive(w, "bg_m1_11", MIM1, dict(w=mim_side, l=mim_side, nx=1, ny=1, stack=1, doports=1))
    m2_11 = clean_primitive(w, "bg_m2_11", MIM2, dict(w=mim_side, l=mim_side, nx=1, ny=1, doports=1))

    # Band 2: 2x pc_2x40 (each 18.66 um tall -> max N-tap distance 9.33 um < 15 um -> 0 LU.3!)
    pc_p2 = clean_primitive(w, "pc_2x40", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=8.0, l=4.0, nf=40, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))

    # Band 1: vbuf_v2 + pbuf_v2
    vb_xr_v = clean_primitive(w, "vb_xr8", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=40.185, nx=8, m=1, guard=0))
    vb_xr = rot90(vb_xr_v)
    vb_pl = clean_primitive(w, "vb_pl_2x6", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=8.0, l=8.0, nf=6, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    vb_np = clean_primitive(w, "vb_np_2x6", "sky130_fd_pr__nfet_01v8",
                            dict(w=6.0, l=4.0, nf=6, m=2, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    vb_nt = clean_primitive(w, "vb_nt_1x6", "sky130_fd_pr__nfet_01v8",
                            dict(w=2.0, l=4.0, nf=6, m=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))

    pb_xr0_v = clean_primitive(w, "pb_xr0_ng", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=36.550, nx=8, m=1, guard=0))
    pb_xr0 = rot90(pb_xr0_v)
    pb_xr5 = clean_primitive(w, "pb_xr5_ng", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=7.360, nx=5, m=1, guard=0))
    pb_n1 = clean_primitive(w, "pb_n1", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    pb_n2 = clean_primitive(w, "pb_n2", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    pb_p2 = clean_primitive(w, "pb_p2", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=0, botc=1, doports=1))
    pb_p4 = clean_primitive(w, "pb_p4_2f", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.18, nf=2, guard=0, conn_gates=1, topc=0, botc=1, doports=1))
    pb_pl = clean_primitive(w, "pb_pl", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=6.0, l=1.0, nf=18, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    pb_np = clean_primitive(w, "pb_np", "sky130_fd_pr__nfet_01v8_lvt",
                            dict(w=6.0, l=1.0, nf=10, m=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    pb_xt = clean_primitive(w, "pb_xt", "sky130_fd_pr__nfet_01v8",
                            dict(w=5.0, l=1.0, nf=6, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    pb_xst = clean_primitive(w, "pb_xst", "sky130_fd_pr__nfet_01v8",
                             dict(w=5.0, l=0.18, nf=6, m=1, guard=0, conn_gates=1, topc=1, botc=1, doports=1))
    pb_bd = clean_primitive(w, "pb_bd", "sky130_fd_pr__nfet_01v8",
                            dict(w=1.0, l=1.0, nf=1, m=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))

    # Exact nsubdiffcont ring top Y for pc_2x40 & fc_pbc
    pc2_ring_y = max(round((r[1] + r[3]) / 2.0, 3) for r in pc_p2.rects["nsubdiffcont"] if r[2] - r[0] > 3.0)
    pbc_ring_y = max(round((r[1] + r[3]) / 2.0, 3) for r in fc_pbc.rects["nsubdiffcont"] if r[2] - r[0] > 1.0)

    c = Cell()
    # Macro outer boundary: 176.26 x 152.26 = 26,837 um^2 <= 27,000 um^2 (AR=1.16)
    gx1, gy1 = grid(0.6), grid(0.0)
    gx2, gy2 = grid(175.6), grid(151.0)
    draw_m1_guard_ring(c, gx1, gy1, gx2, gy2, w=0.70)

    # =========================================================================
    # GLOBAL VERTICAL M3 HIGHWAYS (ALL >= 0.80 um PITCH & LEFT OF MIM x=120.5!)
    # =========================================================================
    x_vdd_l = grid(3.0)
    x_vg_m3 = grid(51.8)
    x_fcda_m3 = grid(52.6)
    x_fa_m3 = grid(53.4)
    x_fb_m3 = grid(54.2)
    x_vbps_m3 = grid(55.0)
    x_vbpc_m3 = grid(55.8)
    x_fctail_m3 = grid(97.8)
    x_vbnc_m3 = grid(98.6)
    x_st_m3 = grid(99.4)
    x_b3_vss = grid(106.8)
    x_nb_m3 = grid(108.4)
    x_nb2_m3 = grid(109.2)
    x_ta_m3 = grid(110.0)
    x_tb_m3 = grid(110.8)
    x_vbg_m3 = grid(112.0)
    x_s_m3 = grid(113.4)
    x_otada_m3 = grid(114.6)
    x_vgi_m3 = grid(115.8)
    x_vdd_m = grid(117.2)
    x_a_m3 = grid(118.6)

    vdd_l_ys: list[float] = []
    vdd_m_ys: list[float] = []
    xm_net_ys: dict[str, list[float]] = {k: [] for k in ("nb", "ta", "vbg", "tb", "nb2", "vg")}
    fa_ys: list[float] = []
    fb_ys: list[float] = []
    vbps_ys: list[float] = []
    vbpc_ys: list[float] = []
    fcda_ys: list[float] = []
    s_ys: list[float] = []
    vgi_ys: list[float] = []

    # =========================================================================
    # BAND 4 (TOP, y = 119.7 .. 150.3): Xm_2x12 + 4x3 PNP Thermal Island
    # =========================================================================
    dx_xm, dy_xm = grid(76.2), grid(135.0)
    c.include(xm_p, dx=dx_xm, dy=dy_xm)
    xm_xs = sd_xs_of(xm_p, "pdiffc", dx_xm)
    xm_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_xm) for r in xm_p.rects["pdiffc"]})
    xm_gxs = sorted({grid(x + dx_xm) for _, x, _, nm in xm_p.labels if nm.startswith("G")})
    xm_gys = sorted({grid(y + dy_xm) for _, _, y, nm in xm_p.labels if nm.startswith("G")})

    row_net_cols = [
        {"nb": 2, "ta": 4, "vbg": 6, "tb": 8, "nb2": 10},
        {"nb2": 2, "tb": 4, "vbg": 6, "ta": 8, "nb": 10},
    ]
    net_m3_x = {"nb": x_nb_m3, "ta": x_ta_m3, "vbg": x_vbg_m3, "tb": x_tb_m3, "nb2": x_nb2_m3}
    net_y_off = {"nb": -4.2, "ta": -2.6, "vbg": -1.0, "tb": 0.6, "nb2": 2.2}
    for r_i, yr in enumerate(xm_ys):
        yv = grid(yr + 4.4)
        for idx in (1, 3, 5, 7, 9, 11):
            c.via1(xm_xs[idx], yv)
        c.wire("metal2", [(x_vdd_l, yv), (xm_xs[11], yv)], 0.56)
        c.via2(x_vdd_l, yv); vdd_l_ys.append(yv)
        c.via2(x_vdd_m, yv); vdd_m_ys.append(yv)
        for nm, col_i in row_net_cols[r_i].items():
            yn = grid(yr + net_y_off[nm])
            cx = xm_xs[col_i]; tx = net_m3_x[nm]
            c.via1(cx, yn)
            if nm == "vbg":
                c.via1(xm_xs[0], yn); c.via1(xm_xs[12], yn)
                c.wire("metal2", [(xm_xs[0], yn), (xm_xs[12], yn)], 0.36)
            else:
                c.wire("metal2", [(min(cx, tx), yn), (max(cx, tx), yn)], 0.36)
            c.via2(tx, yn); xm_net_ys[nm].append(yn)
        gy = xm_gys[r_i]
        for gx in xm_gxs[1:11]:
            c.via1(gx, gy)
        c.wire("metal2", [(min(x_vg_m3, xm_gxs[1]), gy), (max(x_vg_m3, xm_gxs[10]), gy)], 0.36)
        c.via2(x_vg_m3, gy); xm_net_ys["vg"].append(gy)
        c.wire("metal1", [(xm_gxs[0], gy), (grid(xm_xs[1] - 0.65), gy), (grid(xm_xs[1] - 0.65), grid(gy + 0.65)), (xm_xs[1], grid(gy + 0.65))], 0.24)
        c.wire("metal1", [(xm_gxs[11], gy), (grid(xm_xs[11] + 0.65), gy), (grid(xm_xs[11] + 0.65), grid(gy + 0.65)), (xm_xs[11], grid(gy + 0.65))], 0.24)
    y_xm_top_ring = grid(dy_xm + 15.065)
    c.wire("metal1", [(xm_xs[11], xm_ys[-1]), (xm_xs[11], y_xm_top_ring)], 0.34); c.pad("viali", xm_xs[11], y_xm_top_ring, 0.17)

    # 4x3 PNP thermal island (x=152.3..174.1, y=121.2..149.0)
    pnp = Cell.read(PNP_MAG)
    pnp.rects.pop("checkpaint", None)
    pnp_em = pnp.pins("Emitter")[0]; pnp_ba = pnp.pins("Base")[0]; pnp_co = pnp.pins("Collector")[0]
    pnp.labels.clear()
    pnp_xs = [grid(152.3 + i * 7.2) for i in range(3)]
    pnp_ys = [grid(121.2 + j * 6.95) for j in range(4)]
    q1_em = q3_em = (0.0, 0.0)
    for r_i, py in enumerate(pnp_ys):
        y_bc = grid(py + 5.95)
        for c_i, px in enumerate(pnp_xs):
            if r_i == 3 and c_i in (0, 2):
                c.rect("pwell", px, py, grid(px + 6.7), grid(py + 6.7))
                c.rect("psubdiff", grid(px + 0.4), grid(py + 0.4), grid(px + 6.3), grid(py + 6.4))
                c.rect("psubdiffcont", grid(px + 1.2), grid(py + 1.2), grid(px + 5.5), grid(py + 5.5))
                c.rect("locali", grid(px + 0.8), grid(py + 0.8), grid(px + 5.9), grid(py + 6.25))
                c.pad("viali", grid(px + 3.35), y_bc, 0.17); c.pad("metal1", grid(px + 3.35), y_bc, 0.40)
                continue
            c.include(pnp, dx=px, dy=py)
            ex, ey = grid(px + pnp_em[0]), grid(py + pnp_em[1])
            bx_p, by_p = grid(px + pnp_ba[0]), grid(py + pnp_ba[1])
            cx_p, cy_p = grid(px + pnp_co[0]), grid(py + pnp_co[1])
            c.wire("locali", [(cx_p, by_p), (cx_p, cy_p)], 0.36)
            c.pad("viali", cx_p, cy_p, 0.17); c.pad("metal1", cx_p, cy_p, 0.36)
            c.wire("metal1", [(cx_p, cy_p), (cx_p, y_bc)], 0.36)
            c.via1(ex, ey)
            if r_i == 1 and c_i == 1:
                q1_em = (ex, ey)
            elif r_i == 3 and c_i == 1:
                q3_em = (ex, ey)
        c.wire("metal1", [(grid(pnp_xs[0] + 1.0), y_bc), (gx2, y_bc)], 0.40)
    x_q2_l, x_q2_m, x_q2_r = [grid(x + pnp_em[0]) for x in pnp_xs]
    y_q2_0, y_q2_1, y_q2_2 = [grid(y + pnp_em[1]) for y in pnp_ys[:3]]
    c.wire("metal2", [(x_q2_l, y_q2_0), (x_q2_r, y_q2_0), (x_q2_r, y_q2_2), (x_q2_l, y_q2_2), (x_q2_l, y_q2_0)], 0.40)

    # =========================================================================
    # BAND 3 (y = 73.8 .. 118.8): FC-OTA + V->I OTA + Res_all + Xs0..4 + 2x2 MIM
    # =========================================================================
    # --- 3A. Left (x=1.8..53.3): fc_fab + fc_pca/pcb/pb/pbc + Xsp ---
    dx_fab, dy_fab = grid(27.5), grid(104.0)  # x=1.8..53.2, y=90.7..117.3
    c.include(fc_fab, dx=dx_fab, dy=dy_fab)
    fab_xs = sd_xs_of(fc_fab, "pdiffc", dx_fab)
    fab_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_fab) for r in fc_fab.rects["pdiffc"]})
    fab_gxs = sorted({grid(x + dx_fab) for _, x, _, nm in fc_fab.labels if nm.startswith("G")})
    fab_gys = sorted({grid(y + dy_fab) for _, _, y, nm in fc_fab.labels if nm.startswith("G")})
    fabbx, fabby = fc_fab.pins("B")[0]; fabbx, fabby = grid(fabbx + dx_fab), grid(fabby + dy_fab)
    for r_i, yr in enumerate(fab_ys):
        yv = grid(yr + 3.2); yfa = grid(yr + 0.4); yfb = grid(yr - 2.2)
        for idx in (0, 1, 3, 5, 6):
            c.via1(fab_xs[idx], yv)
        c.wire("metal2", [(x_vdd_l, yv), (fab_xs[6], yv)], 0.44); c.via2(x_vdd_l, yv); vdd_l_ys.append(yv)
        fa_col, fb_col = (2, 4) if r_i == 0 else (4, 2)
        c.via1(fab_xs[fa_col], yfa); c.wire("metal2", [(fab_xs[fa_col], yfa), (x_fa_m3, yfa)], 0.34); c.via2(x_fa_m3, yfa); fa_ys.append(yfa)
        c.via1(fab_xs[fb_col], yfb); c.wire("metal2", [(fab_xs[fb_col], yfb), (x_fb_m3, yfb)], 0.34); c.via2(x_fb_m3, yfb); fb_ys.append(yfb)
        gy = fab_gys[r_i]
        for gx in fab_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(fab_gxs[1], gy), (x_vbps_m3, gy)], 0.32); c.via2(x_vbps_m3, gy); vbps_ys.append(gy)
        for gx, sx in ((fab_gxs[0], fab_xs[0]), (fab_gxs[5], fab_xs[6])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.28)
    y_fab_top_ring = grid(dy_fab + 13.065)
    c.wire("metal1", [(fab_xs[0], fab_ys[-1]), (fab_xs[0], y_fab_top_ring)], 0.34); c.pad("viali", fab_xs[0], y_fab_top_ring, 0.17)

    # Xpca + Xpcb + Xpb + Xpbc right below fc_fab (N-well merged with fc_fab & pc_2x40 top!)
    dx_pca, dy_pc = grid(8.3), grid(82.4)
    dx_pcb = grid(21.9)
    dx_pb = grid(37.9)
    dx_pbc, dy_pbc = grid(49.5), grid(84.4)
    c.rect("nwell", grid(1.8), grid(71.5), grid(52.2), grid(92.0))
    for prim_pc, dx_p, s_x, d_x, s_ys, d_ys, ys_s, ys_d in (
        (fc_pc, dx_pca, x_fb_m3, x_fcda_m3, fb_ys, fcda_ys, grid(dy_pc + 2.95), grid(dy_pc - 1.2)),
        (fc_pc, dx_pcb, x_fa_m3, x_vg_m3, fa_ys, xm_net_ys["vg"], grid(dy_pc + 4.0), grid(dy_pc - 4.0)),
    ):
        c.include(prim_pc, dx=dx_p, dy=dy_pc)
        pxs = sd_xs_of(prim_pc, "pdiffc", dx_p)
        pgx = grid(dx_p + prim_pc.pins("G")[0][0]); pgy = grid(dy_pc + prim_pc.pins("G")[0][1])
        for idx in (0, 2, 4):
            c.via1(pxs[idx], ys_s)
        c.wire("metal2", [(pxs[0], ys_s), (s_x, ys_s)], 0.34); c.via2(s_x, ys_s); s_ys.append(ys_s)
        for idx in (1, 3):
            c.via1(pxs[idx], ys_d)
        c.wire("metal2", [(pxs[1], ys_d), (d_x, ys_d)], 0.34); c.via2(d_x, ys_d); d_ys.append(ys_d)
        c.via1(pgx, pgy)
        c.wire("metal2", [(pgx, pgy), (x_vbpc_m3, pgy)], 0.30); c.via2(x_vbpc_m3, pgy); vbpc_ys.append(pgy)
        x_pc_gr = grid(dx_p + prim_pc.bbox()[0] + 0.35)
        y_pc_ring = grid(dy_pc + 6.655)
        c.wire("metal1", [(x_pc_gr, y_pc_ring), (x_pc_gr, fabby)], 0.34)
        c.pad("viali", x_pc_gr, y_pc_ring, 0.17); c.pad("viali", x_pc_gr, fabby, 0.17)

    c.include(fc_pb, dx=dx_pb, dy=dy_pc)
    pb_xs = sd_xs_of(fc_pb, "pdiffc", dx_pb)
    pb_gx = grid(dx_pb + fc_pb.pins("G")[0][0]); pb_gy = grid(dy_pc + fc_pb.pins("G")[0][1])
    y_pb_vdd = grid(dy_pc + 5.2); y_pb_d = grid(dy_pc - 2.6)
    for idx in (0, 2):
        c.via1(pb_xs[idx], y_pb_vdd)
    c.wire("metal2", [(x_vdd_l, y_pb_vdd), (pb_xs[2], y_pb_vdd)], 0.34); c.via2(x_vdd_l, y_pb_vdd); vdd_l_ys.append(y_pb_vdd)
    c.via1(pb_xs[1], y_pb_d); c.wire("metal2", [(pb_xs[1], y_pb_d), (x_vbps_m3, y_pb_d)], 0.32)
    c.via2(x_vbps_m3, y_pb_d); vbps_ys.append(y_pb_d)
    # Drop pb_gx DOWN 0.65 um on M1 FIRST so M2 NEVER touches fc_pc gate wire at y=76.26 (vbp_c)!
    y_pbg = grid(pb_gy - 0.65)
    c.wire("metal1", [(pb_gx, pb_gy), (pb_gx, y_pbg)], 0.24)
    c.via1(pb_gx, y_pbg); c.wire("metal2", [(pb_gx, y_pbg), (x_vbps_m3, y_pbg)], 0.30)
    c.via2(x_vbps_m3, y_pbg); vbps_ys.append(y_pbg)
    y_pb_ring = grid(dy_pc + 6.655)
    c.wire("metal1", [(pb_xs[2], y_pb_vdd), (pb_xs[2], y_pb_ring)], 0.30); c.pad("viali", pb_xs[2], y_pb_ring, 0.17)

    c.include(fc_pbc, dx=dx_pbc, dy=dy_pbc)
    pbc_xs = sd_xs_of(fc_pbc, "pdiffc", dx_pbc)
    pbc_gx, pbc_gy = grid(dx_pbc + fc_pbc.pins("G")[0][0]), grid(dy_pbc + fc_pbc.pins("G")[0][1])
    # Extend pbc_xs[0] M1 from dy_pbc (84.4) UP to y_pb_vdd (87.6) & y_pbc_ring so fc_pbc source ties cleanly to vdd!
    y_pbc_ring = grid(dy_pbc + pbc_ring_y)
    c.wire("metal1", [(pbc_xs[0], dy_pbc), (pbc_xs[0], max(y_pb_vdd, y_pbc_ring))], 0.32)
    c.via1(pbc_xs[0], y_pb_vdd); c.wire("metal2", [(pb_xs[2], y_pb_vdd), (pbc_xs[0], y_pb_vdd)], 0.32)
    c.pad("metal1", pbc_xs[0], y_pbc_ring, 0.34); c.pad("viali", pbc_xs[0], y_pbc_ring, 0.17)
    c.via1(pbc_xs[1], grid(dy_pbc - 0.8)); c.via1(pbc_gx, pbc_gy)
    c.wire("metal2", [(pbc_xs[1], grid(dy_pbc - 0.8)), (pbc_xs[1], pbc_gy), (pbc_gx, pbc_gy), (x_vbpc_m3, pbc_gy)], 0.28)
    c.via2(x_vbpc_m3, pbc_gy); vbpc_ys.append(pbc_gy)

    # Xsp (0.42/20) tucked at (13.0, 118.45), N-well merged UP into Xm_2x12 AND DOWN into fc_fab (0 nwell.2a!)
    dx_sp, dy_sp = grid(13.0), grid(118.45)
    c.include(st_sp, dx=dx_sp, dy=dy_sp)
    sp_nw = st_sp.rects["nwell"][0]
    c.rect("nwell", grid(sp_nw[0] + dx_sp), grid(116.5), grid(sp_nw[2] + dx_sp), grid(121.5))
    sp_xs = sd_xs_of(st_sp, "pdiffc", dx_sp)
    sp_gx, sp_gy = grid(dx_sp + st_sp.pins("G")[0][0]), grid(dy_sp + st_sp.pins("G")[0][1])
    y_sp_sd0 = grid(dy_sp + 0.18); y_sp_sd = grid(dy_sp + 0.42)
    c.wire("metal1", [(sp_xs[0], y_sp_sd0), (sp_xs[0], y_sp_sd)], 0.24); c.via1(sp_xs[0], y_sp_sd)
    c.wire("metal2", [(x_vdd_l, y_sp_sd), (sp_xs[0], y_sp_sd)], 0.28); c.via2(x_vdd_l, y_sp_sd); vdd_l_ys.append(y_sp_sd)
    c.wire("metal1", [(sp_xs[1], y_sp_sd0), (sp_xs[1], y_sp_sd)], 0.24); c.via1(sp_xs[1], y_sp_sd)
    c.wire("metal2", [(sp_xs[1], y_sp_sd), (x_st_m3, y_sp_sd)], 0.28); c.via2(x_st_m3, y_sp_sd)
    y_sp_g = grid(sp_gy - 0.55)
    c.wire("metal1", [(sp_gx, sp_gy), (sp_gx, y_sp_g)], 0.22); c.via1(sp_gx, y_sp_g)
    c.wire("metal2", [(gx1, y_sp_g), (sp_gx, y_sp_g)], 0.26); c.via1(gx1, y_sp_g)

    # --- 3B. Middle (x=56.5..109.9 -> >= 2.5 um clear of r_rs rpm at 112.4!) ---
    dx_opl, dy_opl = grid(74.0), grid(111.3)  # x=56.6..91.4, y=104.4..118.2 (0.7 um above fc_ab!)
    c.include(ota_pl, dx=dx_opl, dy=dy_opl)
    opl_xs = sd_xs_of(ota_pl, "pdiffc", dx_opl)
    opl_gpts = gate_pts_of(ota_pl, dx_opl, dy_opl)
    opl_gy = opl_gpts[0][1]
    otada_ys: list[float] = []
    y_op_vdd = grid(dy_opl + 4.4); y_op_da = grid(dy_opl + 0.6); y_op_vgi = grid(dy_opl - 2.4)
    for idx in (0, 2, 4):
        c.via1(opl_xs[idx], y_op_vdd)
    c.wire("metal2", [(opl_xs[0], y_op_vdd), (x_vdd_m, y_op_vdd)], 0.36); c.via2(x_vdd_m, y_op_vdd); vdd_m_ys.append(y_op_vdd)
    c.via1(opl_xs[1], y_op_da); c.wire("metal2", [(opl_xs[1], y_op_da), (x_otada_m3, y_op_da)], 0.32)
    c.via2(x_otada_m3, y_op_da); otada_ys.append(y_op_da)
    c.via1(opl_xs[3], y_op_vgi); c.wire("metal2", [(opl_xs[3], y_op_vgi), (x_vgi_m3, y_op_vgi)], 0.32)
    c.via2(x_vgi_m3, y_op_vgi); vgi_ys.append(y_op_vgi)
    for gx, _ in opl_gpts:
        c.via1(gx, opl_gy)
    c.wire("metal2", [(opl_gpts[0][0], opl_gy), (x_otada_m3, opl_gy)], 0.30); c.via2(x_otada_m3, opl_gy); otada_ys.append(opl_gy)
    y_opl_ring = grid(dy_opl + 6.655)
    c.wire("metal1", [(opl_xs[0], y_op_vdd), (opl_xs[0], y_opl_ring)], 0.32); c.pad("viali", opl_xs[0], y_opl_ring, 0.17)

    # Xpbnc_2f (18.25 x 13.84) at dx=100.8 -> x=91.7..109.9 (2.5 um clear of r_rs! Full Nwell merge with ota_pl!)
    dx_pbnc, dy_pbnc = grid(100.8), grid(111.3)
    c.include(fc_pb, dx=dx_pbnc, dy=dy_pbnc)
    c.rect("nwell", grid(90.5), grid(104.35), grid(92.8), grid(118.25))
    pnc_xs = sd_xs_of(fc_pb, "pdiffc", dx_pbnc)
    pnc_gx, pnc_gy = grid(dx_pbnc + fc_pb.pins("G")[0][0]), grid(dy_pbnc + fc_pb.pins("G")[0][1])
    y_pnc_vdd = grid(dy_pbnc + 4.4); y_pnc_d = grid(dy_pbnc - 4.0)
    for idx in (0, 2):
        c.via1(pnc_xs[idx], y_pnc_vdd)
    c.wire("metal2", [(pnc_xs[0], y_pnc_vdd), (x_vdd_m, y_pnc_vdd)], 0.34); c.via2(x_vdd_m, y_pnc_vdd); vdd_m_ys.append(y_pnc_vdd)
    c.wire("metal1", [(pnc_xs[0], y_pnc_vdd), (pnc_xs[0], grid(dy_pbnc + 6.655))], 0.30); c.pad("viali", pnc_xs[0], grid(dy_pbnc + 6.655), 0.17)
    c.via1(pnc_xs[1], y_pnc_d); c.wire("metal2", [(x_vbnc_m3, y_pnc_d), (pnc_xs[1], y_pnc_d)], 0.30); c.via2(x_vbnc_m3, y_pnc_d)
    # Drop pnc_gx DOWN on M1 FIRST to fab_gys[1] so M2 NEVER touches ota_pl gate M2 at opl_gy=105.16 (ota_da)!
    y_pnc_g = grid(fab_gys[1])
    c.wire("metal1", [(pnc_gx, pnc_gy), (pnc_gx, y_pnc_g)], 0.24)
    c.via1(pnc_gx, y_pnc_g); c.wire("metal2", [(pnc_gx, y_pnc_g), (x_vbps_m3, y_pnc_g)], 0.30)
    c.via2(x_vbps_m3, y_pnc_g); vbps_ys.append(y_pnc_g)

    # fc_ab (w=6, l=4, nf=10) at (78.2, 100.4): x=56.4..100.0, y=97.1..103.7
    dx_ab, dy_ab = grid(78.2), grid(100.4)
    c.include(fc_ab, dx=dx_ab, dy=dy_ab)
    ab_xs = sd_xs_of(fc_ab, "ndiffc", dx_ab)
    ab_gpts = gate_pts_of(fc_ab, dx_ab, dy_ab)
    ab_gy = ab_gpts[0][1]
    y_ab_t = grid(dy_ab - 1.5); y_ab_fa = grid(dy_ab - 0.5); y_ab_fb = grid(dy_ab + 0.5)
    for idx in (1, 3, 5, 7, 9):
        c.via1(ab_xs[idx], y_ab_t)
    c.wire("metal2", [(ab_xs[1], y_ab_t), (x_fctail_m3, y_ab_t)], 0.34); c.via2(x_fctail_m3, y_ab_t)
    for idx in (2, 8):
        c.via1(ab_xs[idx], y_ab_fa)
    c.wire("metal2", [(x_fa_m3, y_ab_fa), (ab_xs[8], y_ab_fa)], 0.32); c.via2(x_fa_m3, y_ab_fa); fa_ys.append(y_ab_fa)
    for idx in (4, 6):
        c.via1(ab_xs[idx], y_ab_fb)
    c.wire("metal2", [(x_fb_m3, y_ab_fb), (ab_xs[6], y_ab_fb)], 0.32); c.via2(x_fb_m3, y_ab_fb); fb_ys.append(y_ab_fb)
    y_g_ta = grid(ab_gy - 0.55); y_g_tb = grid(ab_gy - 1.15)
    for idx in (1, 2, 7, 8):
        gx = ab_gpts[idx][0]; c.via1(gx, ab_gy); c.wire("metal2", [(gx, ab_gy), (gx, y_g_ta)], 0.32)
    c.wire("metal2", [(ab_gpts[1][0], y_g_ta), (x_ta_m3, y_g_ta)], 0.30); c.via2(x_ta_m3, y_g_ta); xm_net_ys["ta"].append(y_g_ta)
    for idx in (3, 4, 5, 6):
        gx = ab_gpts[idx][0]; c.via1(gx, ab_gy); c.via2(gx, ab_gy)
        c.wire("metal3", [(gx, ab_gy), (gx, y_g_tb)], 0.40); c.via2(gx, y_g_tb)
    c.wire("metal2", [(ab_gpts[3][0], y_g_tb), (x_tb_m3, y_g_tb)], 0.30); c.via2(x_tb_m3, y_g_tb); xm_net_ys["tb"].append(y_g_tb)
    for gx, sx in ((ab_gpts[0][0], ab_xs[0]), (ab_gpts[9][0], ab_xs[10])):
        c.wire("metal1", [(gx, ab_gy), (sx, ab_gy), (sx, dy_ab)], 0.24)

    # fc_t (dy=100.1) + Xbd (dy=96.2 -> bot 94.42, clear of fc_nbpc 94.18 & fc_t bot 98.32!)
    dx_fct, dy_fct = grid(104.8), grid(100.1)
    c.include(fc_t, dx=dx_fct, dy=dy_fct)
    ft_xs = sd_xs_of(fc_t, "ndiffc", dx_fct)
    ft_gx, ft_gy = grid(dx_fct + fc_t.pins("G")[0][0]), grid(dy_fct + fc_t.pins("G")[0][1])
    y_fct_d = grid(dy_fct - 0.80); y_fct_s = grid(dy_fct + 0.60)
    c.via1(ft_xs[1], y_fct_d); c.wire("metal2", [(x_fctail_m3, y_fct_d), (ft_xs[1], y_fct_d)], 0.30); c.via2(x_fctail_m3, y_fct_d)
    c.wire("metal3", [(x_fctail_m3, min(y_ab_t, y_fct_d)), (x_fctail_m3, max(y_ab_t, y_fct_d))], 0.40)
    c.via1(ft_gx, ft_gy); c.wire("metal2", [(ft_gx, ft_gy), (x_nb_m3, ft_gy)], 0.28); c.via2(x_nb_m3, ft_gy); xm_net_ys["nb"].append(ft_gy)

    dx_bd, dy_bd = grid(104.8), grid(96.2)
    c.include(fc_t, dx=dx_bd, dy=dy_bd)
    bd_xs = sd_xs_of(fc_t, "ndiffc", dx_bd)
    bd_gx, bd_gy = grid(dx_bd + fc_t.pins("G")[0][0]), grid(dy_bd + fc_t.pins("G")[0][1])
    c.rect("metal1", grid(bd_xs[1] - 0.30), grid(dy_bd + 0.8), grid(bd_xs[1] + 0.30), grid(bd_gy + 0.16))
    c.via1(bd_gx, bd_gy); c.wire("metal2", [(bd_gx, bd_gy), (x_nb_m3, bd_gy)], 0.28); c.via2(x_nb_m3, bd_gy); xm_net_ys["nb"].append(bd_gy)

    # fc_nca (56.4..74.0) + fc_ncb (75.2..92.8) + fc_nbp (94.0..98.4) + fc_nbpc (99.4..103.8) + Xsn (105.6) + Xsu (108.4)
    dx_nca, dy_nc = grid(65.2), grid(93.1)
    dx_ncb = grid(84.0)  # 1.2 um gap from fc_nca -> ZERO overlap!
    x_na_m3 = grid(65.2); x_nbn_m3 = grid(84.0)
    vbnc_ys = [y_pnc_d]
    for dx_n, d_x, s_x, d_ys, yd_n in (
        (dx_nca, x_fcda_m3, x_na_m3, fcda_ys, grid(dy_nc + 0.6)),
        (dx_ncb, x_vg_m3, x_nbn_m3, xm_net_ys["vg"], grid(dy_nc + 1.4)),
    ):
        c.include(fc_nc, dx=dx_n, dy=dy_nc)
        nxs = sd_xs_of(fc_nc, "ndiffc", dx_n)
        ngx = grid(dx_n + fc_nc.pins("G")[0][0]); ngy = grid(dy_nc + fc_nc.pins("G")[0][1])
        ys_n = grid(dy_nc - 1.15)  # 91.95 -> 0.51 above fab_gys[0]=91.44 & 0.65 below y_d_b=92.60!
        for idx in (1, 3):
            c.via1(nxs[idx], yd_n)
        c.wire("metal2", [(min(nxs[1], d_x), yd_n), (max(nxs[3], d_x), yd_n)], 0.30); c.via2(d_x, yd_n); d_ys.append(yd_n)
        for idx in (0, 2, 4):
            c.via1(nxs[idx], ys_n)
        c.wire("metal2", [(min(nxs[0], s_x), ys_n), (max(nxs[4], s_x), ys_n)], 0.30); c.via2(s_x, ys_n)
        c.via1(ngx, ngy); c.wire("metal2", [(ngx, ngy), (x_vbnc_m3, ngy)], 0.28); c.via2(x_vbnc_m3, ngy); vbnc_ys.append(ngy)

    dx_nbp, dy_nbp = grid(96.2), grid(92.4)
    dx_nbpc = grid(101.6)
    c.include(fc_nbp, dx=dx_nbp, dy=dy_nbp)
    c.include(fc_nbp, dx=dx_nbpc, dy=dy_nbp)
    for dx_b, d_m3, d_list, y_d_b in (
        (dx_nbp, x_vbps_m3, vbps_ys, grid(92.60)),
        (dx_nbpc, x_vbpc_m3, vbpc_ys, grid(93.15)),
    ):
        bxs = sd_xs_of(fc_nbp, "ndiffc", dx_b)
        bgx, bgy = grid(dx_b + fc_nbp.pins("G")[0][0]), grid(dy_nbp + fc_nbp.pins("G")[0][1])
        c.via1(bxs[1], y_d_b); c.wire("metal2", [(d_m3, y_d_b), (bxs[1], y_d_b)], 0.26); c.via2(d_m3, y_d_b); d_list.append(y_d_b)
        c.via1(bgx, bgy)
    y_nbp_g = grid(dy_nbp + fc_nbp.pins("G")[0][1])
    c.wire("metal2", [(grid(dx_nbp + fc_nbp.pins("G")[0][0]), y_nbp_g), (x_nb_m3, y_nbp_g)], 0.28)
    c.via2(x_nb_m3, y_nbp_g); xm_net_ys["nb"].append(y_nbp_g)

    dx_sn, dy_snsu = grid(105.6), grid(91.9)
    dx_su = grid(108.6)  # ends 109.4 -> 3.0 um clear of r_rs!
    c.include(st_sn, dx=dx_sn, dy=dy_snsu)
    c.include(st_su, dx=dx_su, dy=dy_snsu)
    sn_xs = sd_xs_of(st_sn, "ndiffc", dx_sn); sn_gx, sn_gy = grid(dx_sn + st_sn.pins("G")[0][0]), grid(dy_snsu + st_sn.pins("G")[0][1])
    su_xs = sd_xs_of(st_su, "ndiffc", dx_su); su_gx, su_gy = grid(dx_su + st_su.pins("G")[0][0]), grid(dy_snsu + st_su.pins("G")[0][1])
    c.via1(sn_gx, sn_gy); c.wire("metal2", [(sn_gx, sn_gy), (x_nb_m3, sn_gy)], 0.28); c.via2(x_nb_m3, sn_gy); xm_net_ys["nb"].append(sn_gy)
    y_st_lo = grid(dy_snsu + 0.15)
    c.via1(sn_xs[1], y_st_lo); c.via1(su_gx, su_gy)
    c.wire("metal2", [(x_st_m3, y_st_lo), (su_gx, y_st_lo)], 0.26); c.wire("metal2", [(su_gx, y_st_lo), (su_gx, su_gy)], 0.32)
    c.via2(x_st_m3, y_st_lo); c.wire("metal3", [(x_st_m3, y_st_lo), (x_st_m3, y_sp_sd)], 0.34)
    y_su_vg = grid(90.80)  # 0.64 below fab_gys[0]=91.44 (0 met2.2!) & 1.15 below ys_n=91.95!
    c.via1(su_xs[1], dy_snsu); c.wire("metal2", [(su_xs[1], dy_snsu), (su_xs[1], y_su_vg), (x_vg_m3, y_su_vg)], 0.26)
    c.via2(x_vg_m3, y_su_vg); xm_net_ys["vg"].append(y_su_vg)

    # Mid-band P+ substrate tap bar at y_b3_ptap = 90.2 (x=56.4..109.6 -> 2.8 um clear of r_rs!)
    y_b3_ptap = grid(90.2)
    c.rect("pwell", grid(56.0), grid(y_b3_ptap - 0.40), grid(110.0), grid(y_b3_ptap + 0.40))
    c.rect("psubdiff", grid(56.4), grid(y_b3_ptap - 0.20), grid(109.6), grid(y_b3_ptap + 0.20))
    c.rect("psubdiffcont", grid(56.7), grid(y_b3_ptap - 0.085), grid(109.3), grid(y_b3_ptap + 0.085))
    c.rect("locali", grid(56.4), grid(y_b3_ptap - 0.20), grid(109.6), grid(y_b3_ptap + 0.20))
    c.rect("metal1", grid(56.4), grid(y_b3_ptap - 0.22), grid(109.6), grid(y_b3_ptap + 0.22))
    for i in range(6):
        c.pad("viali", grid(58.0 + i * 9.8), y_b3_ptap, 0.17)
    c.via1(x_b3_vss, y_b3_ptap); c.via2(x_b3_vss, y_b3_ptap)
    c.wire("metal3", [(x_b3_vss, y_b3_ptap), (x_b3_vss, gy2)], 0.36); c.via2(x_b3_vss, gy2); c.via1(x_b3_vss, gy2)
    # Tie fc_ab outer dummies via M2 to x_b3_vss (ZERO M1 crossing fc_nca/fc_ncb!)
    y_abdum = grid(dy_ab - 2.05)  # 98.35 -> 0.37 above bd_gy=97.82 & 0.55 below y_ab_t=98.90!
    for sx in (ab_xs[0], ab_xs[10]):
        c.via1(sx, y_abdum)
    c.wire("metal2", [(ab_xs[0], y_abdum), (x_b3_vss, y_abdum)], 0.26); c.via2(x_b3_vss, y_abdum)
    for sx in (ft_xs[0], ft_xs[2]):
        c.via1(sx, y_fct_s)
    c.wire("metal2", [(ft_xs[0], y_fct_s), (ft_xs[2], y_fct_s)], 0.26); c.via2(x_b3_vss, y_fct_s)
    y_bd_s = grid(dy_bd - 0.65)
    for sx in (bd_xs[0], bd_xs[2]):
        c.via1(sx, y_bd_s)
    c.wire("metal2", [(bd_xs[0], y_bd_s), (bd_xs[2], y_bd_s)], 0.26); c.via2(x_b3_vss, y_bd_s)
    for dx_b in (dx_nbp, dx_nbpc):
        bxs = sd_xs_of(fc_nbp, "ndiffc", dx_b)
        c.wire("metal1", [(bxs[0], dy_nbp), (bxs[0], y_b3_ptap)], 0.24)
    c.wire("metal1", [(sn_xs[0], dy_snsu), (sn_xs[0], y_b3_ptap)], 0.24)
    c.wire("metal1", [(su_xs[0], dy_snsu), (su_xs[0], y_b3_ptap)], 0.24)

    # fc_nm (2x6 w=4, l=8) at (82.0, 84.8): x=56.4..107.6, y=79.8..89.8
    dx_nm, dy_nm = grid(82.0), grid(84.8)
    c.include(fc_nm, dx=dx_nm, dy=dy_nm)
    nm_xs = sd_xs_of(fc_nm, "ndiffc", dx_nm)
    nm_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_nm) for r in fc_nm.rects["ndiffc"]})
    nm_gxs = sorted({grid(x + dx_nm) for _, x, _, nm in fc_nm.labels if nm.startswith("G")})
    nm_gys = sorted({grid(y + dy_nm) for _, _, y, nm in fc_nm.labels if nm.startswith("G")})
    na_ys = [grid(dy_nc - 1.15)]; nbn_ys = [grid(dy_nc - 1.15)]
    for r_i, yr in enumerate(nm_ys):
        ys_v = grid(yr - 1.1); yna = grid(yr + 0.1); ynbn = grid(yr + 1.1)
        for idx in (0, 1, 3, 5, 6):
            c.via1(nm_xs[idx], ys_v)
        c.wire("metal2", [(nm_xs[0], ys_v), (nm_xs[6], ys_v)], 0.34); c.via2(x_b3_vss, ys_v)
        na_col, nbn_col = (2, 4) if r_i == 0 else (4, 2)
        c.via1(nm_xs[na_col], yna); c.wire("metal2", [(min(nm_xs[na_col], x_na_m3), yna), (max(nm_xs[na_col], x_na_m3), yna)], 0.30)
        c.via2(x_na_m3, yna); na_ys.append(yna)
        c.via1(nm_xs[nbn_col], ynbn); c.wire("metal2", [(min(nm_xs[nbn_col], x_nbn_m3), ynbn), (max(nm_xs[nbn_col], x_nbn_m3), ynbn)], 0.30)
        c.via2(x_nbn_m3, ynbn); nbn_ys.append(ynbn)
        gy = nm_gys[r_i]
        for gx in nm_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(x_fcda_m3, gy), (nm_gxs[4], gy)], 0.30); c.via2(x_fcda_m3, gy); fcda_ys.append(gy)
        for gx, sx in ((nm_gxs[0], nm_xs[0]), (nm_gxs[5], nm_xs[6])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.24)

    # Local P+ tap at y_on_ptap = 72.30 (x up to 108.6 so ot_xs[1]=108.09 lands cleanly on vss!)
    dx_onp, dy_onp = grid(78.2), grid(76.2)
    y_on_ptap = grid(72.30)
    c.rect("pwell", grid(56.0), grid(y_on_ptap - 0.30), grid(109.0), grid(y_on_ptap + 0.35))
    c.rect("psubdiff", grid(56.4), grid(y_on_ptap - 0.18), grid(108.6), grid(y_on_ptap + 0.18))
    c.rect("psubdiffcont", grid(56.7), grid(y_on_ptap - 0.085), grid(108.3), grid(y_on_ptap + 0.085))
    c.rect("locali", grid(56.4), grid(y_on_ptap - 0.18), grid(108.6), grid(y_on_ptap + 0.18))
    c.rect("metal1", grid(56.4), grid(y_on_ptap - 0.20), grid(108.6), grid(y_on_ptap + 0.20))
    for i in range(6):
        c.pad("viali", grid(58.0 + i * 9.4), y_on_ptap, 0.17)
    c.via1(x_b3_vss, y_on_ptap); c.via2(x_b3_vss, y_on_ptap)
    c.wire("metal3", [(x_b3_vss, y_on_ptap), (x_b3_vss, y_b3_ptap)], 0.36)

    c.include(ota_np, dx=dx_onp, dy=dy_onp)
    onp_xs = sd_xs_of(ota_np, "ndiffc", dx_onp)
    onp_gpts = gate_pts_of(ota_np, dx_onp, dy_onp)
    onp_gy = onp_gpts[0][1]  # ~79.32
    y_on_t = grid(dy_onp - 1.5); y_on_da = grid(dy_onp + 0.30); y_on_vgi = grid(dy_onp + 1.30)  # y_on_da=76.50 >= 0.55 above Xrs M2 jumper 75.77!
    for idx in (1, 3, 5, 7, 9):
        c.via1(onp_xs[idx], y_on_t)
    c.wire("metal2", [(onp_xs[1], y_on_t), (onp_xs[9], y_on_t)], 0.34)
    for idx in (2, 8):
        c.via1(onp_xs[idx], y_on_da)
    c.wire("metal2", [(onp_xs[2], y_on_da), (x_otada_m3, y_on_da)], 0.32); c.via2(x_otada_m3, y_on_da); otada_ys.append(y_on_da)
    for idx in (4, 6):
        c.via1(onp_xs[idx], y_on_vgi)
    c.wire("metal2", [(onp_xs[4], y_on_vgi), (x_vgi_m3, y_on_vgi)], 0.32); c.via2(x_vgi_m3, y_on_vgi); vgi_ys.append(y_on_vgi)
    y_og_s = grid(onp_gy - 0.65); y_og_vbg = grid(onp_gy + 0.65)
    for idx in (1, 2, 7, 8):
        gx = onp_gpts[idx][0]; c.via1(gx, onp_gy); c.wire("metal2", [(gx, onp_gy), (gx, y_og_s)], 0.32)
    c.wire("metal2", [(onp_gpts[1][0], y_og_s), (x_s_m3, y_og_s)], 0.28); c.via2(x_s_m3, y_og_s); s_ys.append(y_og_s)
    for idx in (3, 4, 5, 6):
        gx = onp_gpts[idx][0]; c.via1(gx, onp_gy); c.via2(gx, onp_gy)
        c.wire("metal3", [(gx, onp_gy), (gx, y_og_vbg)], 0.40); c.via2(gx, y_og_vbg)
    c.wire("metal2", [(onp_gpts[3][0], y_og_vbg), (x_vbg_m3, y_og_vbg)], 0.30); c.via2(x_vbg_m3, y_og_vbg); xm_net_ys["vbg"].append(y_og_vbg)
    for gx, sx in ((onp_gpts[0][0], onp_xs[0]), (onp_gpts[9][0], onp_xs[10])):
        c.wire("metal1", [(gx, onp_gy), (sx, onp_gy), (sx, y_on_ptap)], 0.24)

    # ota_xt (dy=73.55 -> top 74.34): swap S/D so ot_xs[0]=ota_tail (101.6, LEFT of ot_gx=104.8!) & ot_xs[1]=vss -> ZERO M2 short to nb2!
    dx_ot, dy_ot = grid(104.8), grid(73.55)
    c.include(ota_xt, dx=dx_ot, dy=dy_ot)
    ot_xs = sd_xs_of(ota_xt, "ndiffc", dx_ot)
    ot_gx, ot_gy = grid(dx_ot + ota_xt.pins("G")[0][0]), grid(dy_ot + ota_xt.pins("G")[0][1])
    c.wire("metal1", [(ot_xs[1], dy_ot), (ot_xs[1], y_on_ptap)], 0.24)
    c.via1(ot_xs[0], dy_ot); c.wire("metal2", [(onp_xs[9], y_on_t), (ot_xs[0], y_on_t), (ot_xs[0], dy_ot)], 0.28)
    c.via1(ot_gx, ot_gy); c.wire("metal2", [(ot_gx, ot_gy), (x_nb2_m3, ot_gy)], 0.28); c.via2(x_nb2_m3, ot_gy); xm_net_ys["nb2"].append(ot_gy)

    dx_bd2, dy_bd2 = grid(104.8), grid(77.60)  # bd2_gy = 79.22 (cleanly between y_og_s=78.67 & y_og_vbg=79.97!)
    c.include(fc_t, dx=dx_bd2, dy=dy_bd2)
    bd2_xs = sd_xs_of(fc_t, "ndiffc", dx_bd2)
    bd2_gx, bd2_gy = grid(dx_bd2 + fc_t.pins("G")[0][0]), grid(dy_bd2 + fc_t.pins("G")[0][1])
    y_bd2_s = grid(76.85)  # cleanly between y_on_da=76.50? No: y_on_da=76.50, y_on_vgi=77.50 -> put y_bd2_s=75.85 (0.65 below y_on_da!)
    y_bd2_s = grid(75.85)
    for sx in (bd2_xs[0], bd2_xs[2]):
        c.via1(sx, y_bd2_s)
    c.wire("metal2", [(bd2_xs[0], y_bd2_s), (bd2_xs[2], y_bd2_s)], 0.26); c.via2(x_b3_vss, y_bd2_s)
    c.rect("metal1", grid(bd2_xs[1] - 0.30), grid(dy_bd2 + 0.8), grid(bd2_xs[1] + 0.30), grid(bd2_gy + 0.16))
    c.via1(bd2_gx, bd2_gy); c.wire("metal2", [(bd2_gx, bd2_gy), (x_nb2_m3, bd2_gy)], 0.28); c.via2(x_nb2_m3, bd2_gy); xm_net_ys["nb2"].append(bd2_gy)

    # --- 3C. Right (x=119.9..174.5): Res_all + Xs0..4 + Xk + Xnbc + 2x2 Stacked MIM Roof ---
    dx_c3 = grid(22.9); dy_c3 = grid(50.2)  # drops Col 3 by 1.2 um -> 0 poly.9/rpm.3 against Xm!
    dx_rs, dy_rs = grid(97.0 + dx_c3), grid(46.0 + dy_c3)
    c.include(r_rs, dx=dx_rs, dy=dy_rs)
    _add_outer_ppolyres_dummies(c, r_rs, dx_rs, dy_rs)
    rs_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_rs) for r in r_rs.rects["viali"]})
    rs_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_rs) for r in r_rs.rects["viali"]})
    rs_yb, rs_yt = rs_ys[0], rs_ys[-1]
    for k, (idx_a, idx_b) in enumerate(((0, 2), (2, 4), (4, 6), (6, 8))):
        y_base = rs_yb if k % 2 == 0 else rs_yt
        y_j = grid(y_base - 1.35 if k % 2 == 0 else y_base + 1.35)
        c.wire("metal1", [(rs_xs[idx_a], y_base), (rs_xs[idx_a], y_j), (rs_xs[idx_b], y_j), (rs_xs[idx_b], y_base)], 0.30)
    for k, (idx_a, idx_b) in enumerate(((1, 3), (3, 5), (5, 7), (7, 9))):
        y_base = rs_yb if k % 2 == 0 else rs_yt
        y_j = grid(y_base - 0.65 if k % 2 == 0 else y_base + 0.60)
        c.via1(rs_xs[idx_a], y_base); c.via1(rs_xs[idx_b], y_base)
        c.wire("metal2", [(rs_xs[idx_a], y_base), (rs_xs[idx_a], y_j), (rs_xs[idx_b], y_j), (rs_xs[idx_b], y_base)], 0.30)
    pt_ta_res = (rs_xs[0], rs_yt); pt_a_res = (rs_xs[8], rs_yb)
    pt_tb_res = (rs_xs[1], rs_yt); pt_b_res = (rs_xs[9], rs_yb)

    dx_r2l = grid(111.4 + dx_c3); dx_r1 = grid(115.9 + dx_c3); dx_r2r = grid(120.4 + dx_c3)
    dy_r12 = grid(46.0 + dy_c3)
    c.include(r_r2a, dx=dx_r2l, dy=dy_r12); c.include(r_r1, dx=dx_r1, dy=dy_r12); c.include(r_r2a, dx=dx_r2r, dy=dy_r12)
    r2l_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_r2l) for r in r_r2a.rects["viali"]})
    r2r_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_r2r) for r in r_r2a.rects["viali"]})
    r2_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_r12) for r in r_r2a.rects["viali"]})
    r1_x = sorted({grid((r[0] + r[2]) / 2.0 + dx_r1) for r in r_r1.rects["viali"]})[0]
    r1_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_r12) for r in r_r1.rects["viali"]})
    r2_body = r_r2a.rects["ppolyres"][0]; r2_bw = grid(r2_body[2] - r2_body[0])
    for xd_c in (grid(r2l_xs[0] - 1.48), grid(r2r_xs[-1] + 1.48)):
        c.rect("ppolyres", grid(xd_c - r2_bw / 2), grid(r2_body[1] + dy_r12), grid(xd_c + r2_bw / 2), grid(r2_body[3] + dy_r12))
    for i in range(4):
        yj_l = r2_ys[0] if i % 2 == 0 else r2_ys[-1]
        yj_r = r2_ys[-1] if i % 2 == 0 else r2_ys[0]
        c.wire("metal1", [(r2l_xs[i], yj_l), (r2l_xs[i + 1], yj_l)], 0.40)
        c.wire("metal1", [(r2r_xs[i], yj_r), (r2r_xs[i + 1], yj_r)], 0.40)
    y_r2_hop = grid(r1_ys[0] - 0.85)
    c.via1(r2l_xs[4], r2_ys[0]); c.via1(r2r_xs[0], r2_ys[0])
    c.wire("metal2", [(r2l_xs[4], r2_ys[0]), (r2l_xs[4], y_r2_hop), (r2r_xs[0], y_r2_hop), (r2r_xs[0], r2_ys[0])], 0.34)
    pt_vbg_res = (r2l_xs[0], r2_ys[-1]); pt_d_res = (r2r_xs[4], r2_ys[-1])
    pt_b_r1 = (r1_x, r1_ys[0]); pt_c_r1 = (r1_x, r1_ys[-1])

    dx_rf, dy_rf = grid(134.8 + dx_c3), grid(48.7 + dy_c3)
    c.include(r_rf, dx=dx_rf, dy=dy_rf)
    rf_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_rf) for r in r_rf.rects["viali"]})
    rf_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_rf) for r in r_rf.rects["viali"]})
    for i in range(9):
        yj = rf_ys[0] if i % 2 == 0 else rf_ys[-1]
        c.wire("metal1", [(rf_xs[i], yj), (rf_xs[i + 1], yj)], 0.40)
    pt_s_res = (rf_xs[-1], rf_ys[-1]); pt_rt5_res = (rf_xs[0], rf_ys[-1])

    rt_pts: dict[str, tuple[float, float]] = {}
    rt_top_target = rf_ys[-1]
    rt_xs_bar = [grid(rf_xs[0] - 1.48)] + [grid(rf_xs[-1] + (k + 1) * 1.48) for k in range(4)]
    rt_terms: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for k, bit_idx in enumerate((4, 3, 2, 1, 0)):
        rp = r_rt[bit_idx]
        rys = sorted({grid((r[1] + r[3]) / 2.0) for r in rp.rects["viali"]})
        dy_t = grid(rt_top_target - rys[-1]); dx_t = rt_xs_bar[k]
        c.include(rp, dx=dx_t, dy=dy_t)
        rt_terms.append(((dx_t, grid(rys[-1] + dy_t)), (dx_t, grid(rys[0] + dy_t))))
    c.wire("metal1", [pt_rt5_res, rt_terms[0][0]], 0.36)
    rt_pts["rt5"] = rt_terms[0][0]
    y_rt4_link = grid(29.35 + dy_c3)
    c.wire("metal1", [rt_terms[0][1], (rt_terms[0][1][0], y_rt4_link)], 0.28)
    c.via1(rt_terms[0][1][0], y_rt4_link)
    c.wire("metal2", [(rt_terms[0][1][0], y_rt4_link), (grid(144.6 + dx_c3), y_rt4_link)], 0.28)
    c.via1(grid(144.6 + dx_c3), y_rt4_link)
    c.wire("metal1", [(grid(144.6 + dx_c3), y_rt4_link), (grid(146.0 + dx_c3), y_rt4_link)], 0.28)
    c.via1(grid(146.0 + dx_c3), y_rt4_link)
    rt_pts["rt4"] = rt_terms[1][1]
    c.wire("metal1", [rt_terms[1][0], rt_terms[2][0]], 0.34); rt_pts["rt3"] = rt_terms[2][0]
    c.wire("metal1", [rt_terms[2][1], (rt_terms[3][1][0], rt_terms[2][1][1]), rt_terms[3][1]], 0.32); rt_pts["rt2"] = rt_terms[3][1]
    c.wire("metal1", [rt_terms[3][0], rt_terms[4][0]], 0.34); rt_pts["rt1"] = rt_terms[4][0]
    c.wire("metal1", [rt_terms[4][1], (gx2, rt_terms[4][1][1])], 0.36)

    sw_specs = [
        ("g0", "vss", "rt1", grid(150.2 + dx_c3), grid(55.0 + dy_c3)),
        ("g1", "rt1", "rt2", grid(150.2 + dx_c3), grid(48.8 + dy_c3)),
        ("g2", "rt2", "rt3", grid(150.2 + dx_c3), grid(42.6 + dy_c3)),
        ("g3", "rt3", "rt4", grid(150.2 + dx_c3), grid(36.4 + dy_c3)),
        ("g4", "rt4", "rt5", grid(150.2 + dx_c3), grid(30.2 + dy_c3)),
    ]
    rt_track_x = {nm: grid(x + dx_c3) for nm, x in (("rt5", 145.4), ("rt4", 146.0), ("rt3", 146.6), ("rt2", 147.2), ("rt1", 147.85))}
    rt_entry_y = {"rt4": rt_pts["rt4"][1], "rt2": rt_pts["rt2"][1],
                  "rt5": grid(67.10 + dy_c3), "rt3": grid(67.65 + dy_c3), "rt1": grid(68.20 + dy_c3)}
    rt_track_ys: dict[str, list[float]] = {k: [rt_entry_y[k]] for k in rt_track_x}
    rt_track_ys["rt4"].append(y_rt4_link)
    for nm, (rx, ry) in rt_pts.items():
        if nm not in rt_track_x: continue
        ey = rt_entry_y[nm]; tx = rt_track_x[nm]
        if nm in ("rt4", "rt2"):
            c.wire("metal1", [(rx, ry), (tx, ry)], 0.28); c.via1(tx, ry)
        else:
            c.wire("metal1", [(rx, ry), (rx, ey)], 0.26); c.via1(rx, ey)
            c.wire("metal2", [(rx, ey), (tx, ey)], 0.32)
    g_port_pts: dict[str, tuple[float, float]] = {}
    for gnm, na, nb, sx_c, sy_c in sw_specs:
        c.include(xs_sw, dx=sx_c, dy=sy_c)
        sxs = sd_xs_of(xs_sw, "ndiffc", sx_c)
        sgx = grid(sx_c + xs_sw.pins("G")[0][0]); sgy = grid(sy_c + xs_sw.pins("G")[0][1])
        ya_s = grid(sy_c + 1.5); yb_s = grid(sy_c - 1.5)
        for idx in (0, 2, 4):
            c.via1(sxs[idx], ya_s)
        if na == "vss":
            c.wire("metal2", [(sxs[0], ya_s), (gx2, ya_s)], 0.28); c.via1(gx2, ya_s)
        else:
            c.wire("metal2", [(rt_track_x[na], ya_s), (sxs[4], ya_s)], 0.28); rt_track_ys[na].append(ya_s)
        for idx in (1, 3):
            c.via1(sxs[idx], yb_s)
        c.wire("metal2", [(rt_track_x[nb], yb_s), (sxs[3], yb_s)], 0.28); rt_track_ys[nb].append(yb_s)
        x_g_out = grid(sx_c + xs_sw.bbox()[2] + 0.55)
        c.wire("metal1", [(sgx, sgy), (x_g_out, sgy)], 0.22); c.via1(x_g_out, sgy)
        c.wire("metal2", [(x_g_out, sgy), (gx2, sgy)], 0.26)
        g_port_pts[gnm] = (gx2, sgy)
    for nm, x_tr in rt_track_x.items():
        ys = rt_track_ys[nm]
        c.wire("metal2", [(x_tr, min(ys)), (x_tr, max(ys))], 0.26)

    # Xk & Xnbc under Xrref (0.7+ um above pc_2x40 top Nwell 71.95!)
    dx_xk, dy_xk = grid(130.2 + dx_c3), grid(24.75 + dy_c3)  # y=74.95
    c.include(xk_p, dx=dx_xk, dy=dy_xk)
    xk_xs = sd_xs_of(xk_p, "ndiffc", dx_xk)
    xk_gx, xk_gy = grid(dx_xk + xk_p.pins("G")[0][0]), grid(dy_xk + xk_p.pins("G")[0][1])
    y_xk_s = grid(72.80); y_xk_vbg = grid(72.25); y_xk_vgi = grid(71.70)
    c.via1(xk_xs[0], dy_xk); c.wire("metal2", [(xk_xs[0], dy_xk), (xk_xs[0], y_xk_s), (x_s_m3, y_xk_s)], 0.28)
    c.via2(x_s_m3, y_xk_s); s_ys.append(y_xk_s)
    c.via1(xk_gx, xk_gy); c.wire("metal2", [(xk_gx, xk_gy), (xk_gx, y_xk_vbg), (x_vbg_m3, y_xk_vbg)], 0.28)
    c.via2(x_vbg_m3, y_xk_vbg); xm_net_ys["vbg"].append(y_xk_vbg)
    c.via1(xk_xs[1], dy_xk); c.wire("metal2", [(xk_xs[1], dy_xk), (xk_xs[1], y_xk_vgi), (x_vgi_m3, y_xk_vgi)], 0.28)
    c.via2(x_vgi_m3, y_xk_vgi); vgi_ys.append(y_xk_vgi)

    dx_nbc, dy_nbc = grid(136.2 + dx_c3), grid(27.8 + dy_c3)  # y=78.00 (0.55 below y_og_s=78.55!)
    c.include(fc_nbc, dx=dx_nbc, dy=dy_nbc)
    nbc_xs = sd_xs_of(fc_nbc, "ndiffc", dx_nbc)
    nbc_gx, nbc_gy = grid(dx_nbc + fc_nbc.pins("G")[0][0]), grid(dy_nbc + fc_nbc.pins("G")[0][1])
    y_c3_ptap = grid(24.4 + dy_c3)
    c.rect("pwell", grid(133.6 + dx_c3), grid(y_c3_ptap - 0.45), gx2, grid(y_c3_ptap + 0.45))
    c.rect("psubdiff", grid(134.0 + dx_c3), grid(y_c3_ptap - 0.22), gx2, grid(y_c3_ptap + 0.22))
    c.rect("psubdiffcont", grid(134.3 + dx_c3), grid(y_c3_ptap - 0.085), grid(gx2 - 0.3), grid(y_c3_ptap + 0.085))
    c.rect("locali", grid(134.0 + dx_c3), grid(y_c3_ptap - 0.22), gx2, grid(y_c3_ptap + 0.22))
    c.rect("metal1", grid(134.0 + dx_c3), grid(y_c3_ptap - 0.24), gx2, grid(y_c3_ptap + 0.24))
    c.pad("viali", grid(137.0 + dx_c3), y_c3_ptap, 0.17)
    c.wire("metal1", [(nbc_xs[0], dy_nbc), (nbc_xs[0], grid(26.55 + dy_c3)), (grid(134.8 + dx_c3), grid(26.55 + dy_c3)), (grid(134.8 + dx_c3), y_c3_ptap)], 0.24)
    c.via1(nbc_xs[1], dy_nbc); c.via1(nbc_gx, nbc_gy)
    c.wire("metal2", [(x_vbnc_m3, dy_nbc), (nbc_xs[1], dy_nbc)], 0.28)
    c.wire("metal2", [(nbc_gx, nbc_gy), (nbc_gx, dy_nbc)], 0.26)
    c.via2(x_vbnc_m3, dy_nbc); vbnc_ys.append(dy_nbc)

    # Resistor <-> Core/PNP/OTA connections (zero crossings at y=118..120!)
    y_ta_res = rs_yt; y_tb_res = grid(rs_yt + 0.50); y_vbg_res = grid(68.25 + dy_c3)  # ~118.45
    c.via1(*pt_ta_res); c.wire("metal2", [pt_ta_res, (x_ta_m3, y_ta_res)], 0.30); c.via2(x_ta_m3, y_ta_res); xm_net_ys["ta"].append(y_ta_res)
    c.via1(*pt_tb_res); c.wire("metal2", [pt_tb_res, (pt_tb_res[0], y_tb_res), (x_tb_m3, y_tb_res)], 0.30); c.via2(x_tb_m3, y_tb_res); xm_net_ys["tb"].append(y_tb_res)
    c.via1(*pt_vbg_res); c.wire("metal2", [pt_vbg_res, (pt_vbg_res[0], y_vbg_res), (x_vbg_m3, y_vbg_res)], 0.34); c.via2(x_vbg_m3, y_vbg_res); xm_net_ys["vbg"].append(y_vbg_res)
    y_s_top = grid(68.85 + dy_c3)  # 119.05
    c.wire("metal1", [pt_s_res, (pt_s_res[0], y_s_top)], 0.28); c.via1(pt_s_res[0], y_s_top)
    c.wire("metal2", [(pt_s_res[0], y_s_top), (x_s_m3, y_s_top)], 0.30); c.via2(x_s_m3, y_s_top); s_ys.append(y_s_top)

    y_b_link = grid(min(pt_b_res[1], pt_b_r1[1]) - 1.75)
    c.via1(*pt_b_res); c.wire("metal1", [pt_b_r1, (pt_b_r1[0], y_b_link)], 0.30); c.via1(pt_b_r1[0], y_b_link)
    c.wire("metal2", [pt_b_res, (pt_b_res[0], y_b_link), (pt_b_r1[0], y_b_link)], 0.30)

    # a (pt_a_res -> x_a_m3 -> up to q1_em[1] -> M4 right to q1_em)
    y_a_r = grid(73.40)
    c.via1(*pt_a_res); c.wire("metal2", [pt_a_res, (pt_a_res[0], y_a_r), (x_a_m3, y_a_r)], 0.28)
    c.via2(x_a_m3, y_a_r); c.wire("metal3", [(x_a_m3, y_a_r), (x_a_m3, q1_em[1])], 0.34)
    via3(c, x_a_m3, q1_em[1]); c.via2(*q1_em); via3(c, *q1_em)
    c.wire("metal4", [(x_a_m3, q1_em[1]), q1_em], 0.50)

    # c (pt_c_r1 -> M1 up to 118.45 -> M2 right to x_q2_l -> M3 UP over y_s_top=119.05 to y_q2_0 -> M2!)
    y_c_top = grid(118.45)
    c.wire("metal1", [pt_c_r1, (pt_c_r1[0], y_c_top)], 0.28); c.via1(pt_c_r1[0], y_c_top)
    c.wire("metal2", [(pt_c_r1[0], y_c_top), (x_q2_l, y_c_top)], 0.32)
    c.via2(x_q2_l, y_c_top); c.wire("metal3", [(x_q2_l, y_c_top), (x_q2_l, y_q2_0)], 0.36); c.via2(x_q2_l, y_q2_0)

    # d (pt_d_res -> M1 up to 119.65 [0.60 above y_s_top=119.05 & 0.79 below Xm xm_gys[0]=120.44!] -> M2 right to 151.4 -> M3 up to q3_em!)
    y_d_top = grid(119.65)
    c.wire("metal1", [pt_d_res, (pt_d_res[0], y_d_top)], 0.28); c.via1(pt_d_res[0], y_d_top)
    c.wire("metal2", [(pt_d_res[0], y_d_top), (grid(151.4), y_d_top)], 0.30)
    c.via2(grid(151.4), y_d_top)
    c.wire("metal3", [(grid(151.4), y_d_top), (grid(151.4), q3_em[1])], 0.34)
    c.via2(grid(151.4), q3_em[1]); c.wire("metal2", [(grid(151.4), q3_em[1]), q3_em], 0.30)

    # 2x2 Stacked MIM1+MIM2 roof over Col 3 (Cvbg = 6 pF [3 sites] + Cvgi = 2 pF [1 site])
    dx_mim_top = grid(125.0 + dx_c3); dy_mim_top = grid(51.0 + dy_c3)
    mim_top = _place_mim_stack_site(c, m1_21, m2_21, dx_mim_top, dy_mim_top)
    c1_single_x = sorted(grid(x) for _, x, _, nm in m1_11.labels if nm.startswith("C1"))[0]
    dx_mim_vbg3 = grid(mim_top["a_pts"][1][0] - c1_single_x)
    dx_mim_vgi = grid(mim_top["a_pts"][0][0] - c1_single_x)
    mim_vgi = _place_mim_stack_site(c, m1_11, m2_11, dx_mim_vgi, grid(24.8 + dy_c3))
    mim_vbg3 = _place_mim_stack_site(c, m1_11, m2_11, dx_mim_vbg3, grid(24.8 + dy_c3))
    for lay, key, ww in (("metal4", "a_pts", 1.20), ("metal3", "b3_pts", 1.20), ("metal5", "b5_pts", 1.80)):
        p0 = mim_vbg3[key][0]; p1 = mim_top[key][1]
        xm = grid((p0[0] + p1[0]) / 2.0)
        c.wire(lay, [(xm, p0[1]), (xm, p1[1])], ww)
    y_cbg_m4 = grid(64.25 + dy_c3); y_cbg_vss = grid(66.20 + dy_c3)
    for x, y in mim_top["a_pts"]:
        c.wire("metal4", [(x, y), (x, y_cbg_m4)], 1.20)
    c.wire("metal4", [(x_vbg_m3, y_cbg_m4), (mim_top["a_pts"][-1][0], y_cbg_m4)], 1.00)
    via3_array(c, x_vbg_m3, y_cbg_m4, 1, 8, pitch=0.72)
    for x, y in mim_top["b3_pts"]:
        c.wire("metal3", [(x, y), (x, y_cbg_vss)], 1.20)
    for x, y in mim_top["b5_pts"]:
        c.wire("metal5", [(x, y), (x, y_cbg_vss)], 1.80)
    xb_l = min(mim_top["b3_pts"][0][0], mim_top["b5_pts"][0][0])
    c.wire("metal3", [(xb_l, y_cbg_vss), (gx2, y_cbg_vss)], 1.10)
    c.wire("metal5", [(xb_l, y_cbg_vss), (gx2, y_cbg_vss)], 1.80)
    x_vss_tie = grid(126.0 + dx_c3)
    c.rect("metal4", grid(x_vss_tie - 4.2), grid(y_cbg_vss - 0.70), grid(x_vss_tie + 4.2), grid(y_cbg_vss + 0.70))
    via3_array(c, grid(x_vss_tie - 2.6), y_cbg_vss, 4, 2, pitch=0.72)
    via4_array(c, grid(x_vss_tie + 1.2), y_cbg_vss, 4, 1, pitch=2.00)
    c.via2(gx2, y_cbg_vss); c.via1(gx2, y_cbg_vss)

    y_cvgi_m4 = grid(11.50 + dy_c3); y_cvgi_vdd = grid(10.05 + dy_c3)
    ax_gi, ay_gi = mim_vgi["a_pts"][0]; b3x_gi, b3y_gi = mim_vgi["b3_pts"][0]; b5x_gi, b5y_gi = mim_vgi["b5_pts"][0]
    c.wire("metal4", [(ax_gi, ay_gi), (ax_gi, y_cvgi_m4), (x_vgi_m3, y_cvgi_m4)], 0.66)
    via3_array(c, x_vgi_m3, y_cvgi_m4, 1, 8, pitch=0.72); vgi_ys.append(y_cvgi_m4)
    c.wire("metal3", [(b3x_gi, b3y_gi), (b3x_gi, y_cvgi_vdd), (x_vdd_m, y_cvgi_vdd)], 0.60)
    c.wire("metal5", [(b5x_gi, b5y_gi), (b5x_gi, y_cvgi_vdd), (x_vdd_m, y_cvgi_vdd)], 1.60)
    x_vdd_tie = grid(106.0 + dx_c3)
    c.rect("metal4", grid(x_vdd_tie - 7.5), grid(y_cvgi_vdd - 0.45), grid(x_vdd_tie + 4.2), grid(y_cvgi_vdd + 0.45))
    via3_array(c, grid(x_vdd_tie - 2.8), y_cvgi_vdd, 4, 1, pitch=0.72)
    via3_array(c, grid(x_vdd_tie - 6.0), y_cvgi_vdd, 4, 1, pitch=0.72)
    via4_array(c, grid(x_vdd_tie + 1.2), y_cvgi_vdd, 4, 1, pitch=2.00)
    vdd_m_ys.append(y_cvgi_vdd)

    # =========================================================================
    # BAND 2 (y = 34.6 .. 72.0): Unified 2x pc_2x40 Shared-Nwell Bank (0 LU.3, 153 act + 7 dum!)
    # =========================================================================
    dx_pc = grid(88.1)
    dy_pc_bot = grid(43.90); dy_pc_top = grid(62.65)  # bot: 34.57..53.23, top: 53.32..71.98 (0.32 clear of y_on_ptap=72.30!)
    c.include(pc_p2, dx=dx_pc, dy=dy_pc_bot)
    c.include(pc_p2, dx=dx_pc, dy=dy_pc_top)
    c.rect("nwell", grid(1.45), grid(52.7), grid(174.75), grid(53.9))
    c.rect("nwell", grid(1.45), grid(34.0), grid(53.4), grid(35.3))
    c.rect("nwell", grid(149.9), grid(33.8), grid(174.75), grid(35.3))
    pc_xs = sd_xs_of(pc_p2, "pdiffc", dx_pc)
    pc_ys_b = sorted({grid((r[1] + r[3]) / 2.0 + dy_pc_bot) for r in pc_p2.rects["pdiffc"]})
    pc_ys_t = sorted({grid((r[1] + r[3]) / 2.0 + dy_pc_top) for r in pc_p2.rects["pdiffc"]})
    pc_ys = pc_ys_b + pc_ys_t
    pc_gxs = sorted({grid(x + dx_pc) for _, x, _, nm in pc_p2.labels if nm.startswith("G")})
    pc_gys = (sorted({grid(y + dy_pc_bot) for _, _, y, nm in pc_p2.labels if nm.startswith("G")})
              + sorted({grid(y + dy_pc_top) for _, _, y, nm in pc_p2.labels if nm.startswith("G")}))

    row_alloc = [
        {"icp": list(range(2, 20, 2)), "i_ldo1": [20, 22], "iv_in": [24, 26], "iv_b": [28, 30], "ip_in": [32, 34], "ip_b": [36, 38]},
        {"icp": [2], "i_ldo0": [4, 6], "ictle": list(range(8, 28, 2)), "icml": list(range(28, 40, 2))},
        {"icml": list(range(2, 40, 2))},
        {"icml": list(range(2, 36, 2)) + [40], "s": [36, 38]},
    ]
    x_icml_m3 = grid(4.2); x_ictle_m3 = grid(5.4); x_icp_m3 = grid(6.4); x_ldo0_m3 = grid(7.4); x_ldo1_m3 = grid(8.4)
    x_ivin_m3 = grid(47.2); x_ivb_m3 = grid(54.8)
    # pbuf Band1-2 M3 columns ALL 1.00 um pitch (zero met3.2!):
    x_ipin_m3 = grid(148.0); x_ipb_m3 = grid(149.0); x_tap_bus = grid(150.0); x_po_vdd = grid(151.0); x_po_da = grid(152.0); x_po_out = grid(174.2)
    pc_m3_map = {
        "icml": x_icml_m3, "ictle": x_ictle_m3, "icp": x_icp_m3, "i_ldo0": x_ldo0_m3, "i_ldo1": x_ldo1_m3,
        "iv_in": x_ivin_m3, "iv_b": x_ivb_m3, "ip_in": x_ipin_m3, "ip_b": x_ipb_m3, "s": x_s_m3,
    }
    pc_m3_ys: dict[str, list[float]] = {k: [] for k in pc_m3_map}
    left_port_ys: dict[str, float] = {}
    for r_i, yr in enumerate(pc_ys):
        yv = grid(yr + 2.4)
        for idx in range(1, 40, 2):
            c.via1(pc_xs[idx], yv)
        c.wire("metal2", [(x_vdd_l, yv), (pc_xs[39], yv)], 0.50)
        c.via2(x_vdd_l, yv); vdd_l_ys.append(yv)
        c.via2(x_vdd_m, yv); vdd_m_ys.append(yv)

        groups = list(row_alloc[r_i].items())
        n_g = len(groups)
        for g_i, (nm, cols) in enumerate(groups):
            yd = grid(yr - 3.0 + g_i * (3.6 / max(1, n_g - 1)) if n_g > 1 else yr - 1.2)
            tx = pc_m3_map[nm]
            for ci in cols:
                c.via1(pc_xs[ci], yd)
            x_min = min(pc_xs[min(cols)], tx); x_max = max(pc_xs[max(cols)], tx)
            c.wire("metal2", [(x_min, yd), (x_max, yd)], 0.34)
            c.via2(tx, yd)
            if nm == "s":
                s_ys.append(yd)
            else:
                pc_m3_ys[nm].append(yd)
            # Assign left perimeter exit Y directly on an allocated drain track (ZERO collision with y_dl or other tracks!)
            if nm in ("icml", "ictle", "icp", "i_ldo0", "i_ldo1") and nm not in left_port_ys:
                if (nm == "icml" and r_i == 2) or (nm != "icml"):
                    left_port_ys[nm] = yd

        gy = pc_gys[r_i]
        act_g_end = 40 if r_i == 3 else 39
        for gx in pc_gxs[1:act_g_end]:
            c.via1(gx, gy)
        c.wire("metal2", [(pc_gxs[1], gy), (pc_gxs[act_g_end - 1], gy)], 0.32)
        c.via2(x_vgi_m3, gy); vgi_ys.append(gy)
        # Left outer dummy (finger 0): G=vdd (L-hook), D=vss (pc_xs[0] -> gx1 at yr+1.55, clear of all drains <= yr+0.6!)
        c.wire("metal1", [(pc_gxs[0], gy), (grid(pc_xs[1] - 0.65), gy), (grid(pc_xs[1] - 0.65), grid(gy + 0.65)), (pc_xs[1], grid(gy + 0.65))], 0.24)
        y_dl = grid(yr + 1.55)
        c.via1(pc_xs[0], y_dl); c.wire("metal2", [(gx1, y_dl), (pc_xs[0], y_dl)], 0.28); c.via1(gx1, y_dl)
        if r_i < 3:
            c.wire("metal1", [(pc_gxs[39], gy), (grid(pc_xs[39] + 0.65), gy), (grid(pc_xs[39] + 0.65), grid(gy + 0.65)), (pc_xs[39], grid(gy + 0.65))], 0.24)
            c.via1(pc_xs[40], y_dl); c.wire("metal2", [(pc_xs[40], y_dl), (gx2, y_dl)], 0.28); c.via1(gx2, y_dl)

    # Tie BOTH pc_2x40 top N-tap rings cleanly to vdd S/D columns!
    for dy_b, y_top_row in ((dy_pc_bot, pc_ys_b[-1]), (dy_pc_top, pc_ys_t[-1])):
        y_ring = grid(dy_b + pc2_ring_y)
        for idx in (1, 19, 39):
            c.wire("metal1", [(pc_xs[idx], y_top_row), (pc_xs[idx], y_ring)], 0.34)
            c.pad("viali", pc_xs[idx], y_ring, 0.17)

    for nm, y_ex in left_port_ys.items():
        tx = pc_m3_map[nm]
        ys = pc_m3_ys[nm] + [y_ex]
        y_lo, y_hi = min(ys), max(ys)
        if y_hi - y_lo < 0.70:
            c.rect("metal3", grid(tx - 0.25), grid(y_ex - 0.25), grid(tx + 0.25), grid(y_ex + 0.25))
        else:
            c.wire("metal3", [(tx, y_lo), (tx, y_hi)], 0.44 if nm == "icml" else 0.40)
        c.via2(tx, y_ex)
        c.wire("metal2", [(gx1, y_ex), (tx, y_ex)], 0.44 if nm == "icml" else 0.34)

    # =========================================================================
    # BAND 1 (BOTTOM, y = 0.6 .. 34.8): Compact vbuf_v2 (Left) + Compact pbuf_v2 (Right)
    # =========================================================================
    # --- 1A. vbuf_v2 (x=1.8..80.0, y=0.6..34.8) ---
    dx_vxr, dy_vxr = grid(24.4), grid(8.0)
    c.include(vb_xr, dx=dx_vxr, dy=dy_vxr)
    vxr_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_vxr) for r in vb_xr.rects["viali"]})
    vxr_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_vxr) for r in vb_xr.rects["viali"]})
    vxr_body = vb_xr.rects["ppolyres"][0]; vxr_bh = grid(vxr_body[3] - vxr_body[1])
    for yd_c in (grid(vxr_ys[0] - 1.48), grid(vxr_ys[-1] + 1.48)):
        c.rect("ppolyres", grid(vxr_body[0] + dx_vxr), grid(yd_c - vxr_bh / 2), grid(vxr_body[2] + dx_vxr), grid(yd_c + vxr_bh / 2))
    for i in range(7):
        xj = vxr_xs[0] if i % 2 == 0 else vxr_xs[-1]
        c.wire("metal1", [(xj, vxr_ys[i]), (xj, vxr_ys[i + 1])], 0.40)
    pt_vxr_in = (vxr_xs[-1], vxr_ys[0])
    pt_vxr_gnd = (vxr_xs[-1], vxr_ys[-1])
    c.via1(*pt_vxr_in); c.wire("metal2", [pt_vxr_in, (x_ivin_m3, pt_vxr_in[1])], 0.32); c.via2(x_ivin_m3, pt_vxr_in[1])
    # Drop pt_vxr_gnd on M3 at x=46.2 (1.0 um left of x_ivin_m3=47.2) so it NEVER crosses iv_in M2 at y_gin=13.18!
    x_vgnd_m3 = grid(46.2)
    c.via1(*pt_vxr_gnd); c.wire("metal2", [pt_vxr_gnd, (x_vgnd_m3, pt_vxr_gnd[1])], 0.32)
    c.via2(x_vgnd_m3, pt_vxr_gnd[1]); c.wire("metal3", [(x_vgnd_m3, gy1), (x_vgnd_m3, pt_vxr_gnd[1])], 0.36)
    c.via2(x_vgnd_m3, gy1); c.via1(x_vgnd_m3, gy1)

    # vb_pl_2x6 (51.41 x 18.66) at (27.6, 25.1) -> y=15.8..34.4 (0.40 clear of pc_2x40_bot nsubdiff!)
    dx_vpl, dy_vpl = grid(27.6), grid(25.1)
    c.include(vb_pl, dx=dx_vpl, dy=dy_vpl)
    c.rect("nwell", grid(1.9), grid(33.7), grid(53.4), grid(35.3))
    vpl_xs = sd_xs_of(vb_pl, "pdiffc", dx_vpl)
    vpl_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_vpl) for r in vb_pl.rects["pdiffc"]})
    vpl_gxs = sorted({grid(x + dx_vpl) for _, x, _, nm in vb_pl.labels if nm.startswith("G")})
    vpl_gys = sorted({grid(y + dy_vpl) for _, _, y, nm in vb_pl.labels if nm.startswith("G")})
    x_vda_m3 = grid(51.6); x_vcm_m3 = grid(52.6)
    vda_ys: list[float] = []; vcm_ys: list[float] = []
    for r_i, yr in enumerate(vpl_ys):
        yv = grid(yr + 2.4); yda = grid(yr + 0.0); you = grid(yr - 2.2)
        for idx in (1, 3, 5):
            c.via1(vpl_xs[idx], yv)
        c.wire("metal2", [(x_vdd_l, yv), (vpl_xs[5], yv)], 0.40); c.via2(x_vdd_l, yv); vdd_l_ys.append(yv)
        da_c, ou_c = (2, 4) if r_i == 0 else (4, 2)
        c.via1(vpl_xs[da_c], yda); c.wire("metal2", [(vpl_xs[da_c], yda), (x_vda_m3, yda)], 0.32); c.via2(x_vda_m3, yda); vda_ys.append(yda)
        # Tie outer dummy drains (0, 6) to vcm (G=S=B=vdd HARD OFF -> keeps w=8 l=8 separate from fc_fab w=12 l=8!)
        for idx in (0, ou_c, 6):
            c.via1(vpl_xs[idx], you)
        c.wire("metal2", [(vpl_xs[0], you), (x_vcm_m3, you)], 0.32); c.via2(x_vcm_m3, you); vcm_ys.append(you)
        gy = vpl_gys[r_i]
        for gx in vpl_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(vpl_gxs[1], gy), (x_vda_m3, gy)], 0.30); c.via2(x_vda_m3, gy); vda_ys.append(gy)
        c.wire("metal1", [(vpl_gxs[0], gy), (grid(vpl_xs[1] - 0.65), gy), (grid(vpl_xs[1] - 0.65), grid(gy + 0.65)), (vpl_xs[1], grid(gy + 0.65))], 0.24)
        c.wire("metal1", [(vpl_gxs[5], gy), (grid(vpl_xs[5] + 0.65), gy), (grid(vpl_xs[5] + 0.65), grid(gy + 0.65)), (vpl_xs[5], grid(gy + 0.65))], 0.24)
    y_vpl_ring = grid(dy_vpl + 9.065)
    c.wire("metal1", [(vpl_xs[1], vpl_ys[-1]), (vpl_xs[1], y_vpl_ring)], 0.34); c.pad("viali", vpl_xs[1], y_vpl_ring, 0.17)

    # vb_np_2x6 at dx=66.85 (x=53.66..80.04 -> 0.36 > 0.34 clear of BOTH vb_pl 53.30 & dec Nwell 80.40!)
    dx_vnp, dy_vnp = grid(66.85), grid(14.0)
    c.include(vb_np, dx=dx_vnp, dy=dy_vnp)
    vnp_xs = sd_xs_of(vb_np, "ndiffc", dx_vnp)
    vnp_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_vnp) for r in vb_np.rects["ndiffc"]})
    vnp_gxs = sorted({grid(x + dx_vnp) for _, x, _, nm in vb_np.labels if nm.startswith("G")})
    vnp_gys = sorted({grid(y + dy_vnp) for _, _, y, nm in vb_np.labels if nm.startswith("G")})
    x_vtail_m3 = grid(66.85)
    vtail_ys: list[float] = []
    for r_i, yr in enumerate(vnp_ys):
        yt = grid(yr - 1.75); yda = grid(yr - 0.50); you = grid(yr + 1.60)  # yda=16.34 -> 0.60 clear of vpl_gys[0]=16.94!
        for idx in (1, 3, 5):
            c.via1(vnp_xs[idx], yt)
        c.wire("metal2", [(vnp_xs[1], yt), (vnp_xs[5], yt)], 0.34); c.via2(x_vtail_m3, yt); vtail_ys.append(yt)
        da_c, ou_c = (2, 4) if r_i == 0 else (4, 2)
        c.via1(vnp_xs[da_c], yda); c.wire("metal2", [(x_vda_m3, yda), (vnp_xs[da_c], yda)], 0.32); c.via2(x_vda_m3, yda); vda_ys.append(yda)
        c.via1(vnp_xs[ou_c], you); c.wire("metal2", [(x_vcm_m3, you), (vnp_xs[ou_c], you)], 0.32); c.via2(x_vcm_m3, you); vcm_ys.append(you)
        gy = vnp_gys[r_i]
        in_cols = (1, 2) if r_i == 0 else (3, 4)
        cm_cols = (3, 4) if r_i == 0 else (1, 2)
        y_gin = grid(gy - 0.55); y_gcm = grid(gy + 0.55)
        for idx in in_cols:
            gx = vnp_gxs[idx]; c.via1(gx, gy); c.wire("metal2", [(gx, gy), (gx, y_gin)], 0.32)
        c.wire("metal2", [(x_ivin_m3, y_gin), (vnp_gxs[max(in_cols)], y_gin)], 0.28); c.via2(x_ivin_m3, y_gin)
        pc_m3_ys["iv_in"].extend([pt_vxr_in[1], y_gin])
        for idx in cm_cols:
            gx = vnp_gxs[idx]; c.via1(gx, gy); c.via2(gx, gy)
            c.wire("metal3", [(gx, gy), (gx, y_gcm)], 0.40); c.via2(gx, y_gcm)
        c.wire("metal2", [(x_vcm_m3, y_gcm), (vnp_gxs[max(cm_cols)], y_gcm)], 0.28); c.via2(x_vcm_m3, y_gcm); vcm_ys.append(y_gcm)
        for gx, sx in ((vnp_gxs[0], vnp_xs[0]), (vnp_gxs[5], vnp_xs[6])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.24)
    y_vb_ptap = grid(5.8)
    c.rect("pwell", grid(53.4), grid(y_vb_ptap - 0.45), grid(80.3), grid(y_vb_ptap + 0.45))
    c.rect("psubdiff", grid(53.8), grid(y_vb_ptap - 0.22), grid(79.9), grid(y_vb_ptap + 0.22))
    c.rect("psubdiffcont", grid(54.1), grid(y_vb_ptap - 0.085), grid(79.6), grid(y_vb_ptap + 0.085))
    c.rect("locali", grid(53.8), grid(y_vb_ptap - 0.22), grid(79.9), grid(y_vb_ptap + 0.22))
    c.rect("metal1", grid(53.8), grid(y_vb_ptap - 0.24), grid(79.9), grid(y_vb_ptap + 0.24))
    for i in range(4):
        c.pad("viali", grid(55.8 + i * 7.5), y_vb_ptap, 0.17)
    for sx in (vnp_xs[0], vnp_xs[6]):
        c.wire("metal1", [(sx, vnp_ys[-1]), (sx, y_vb_ptap)], 0.24)
    c.wire("metal1", [(vnp_xs[0], y_vb_ptap), (vnp_xs[0], gy1)], 0.30)

    dx_vnt, dy_vnt = grid(66.85), grid(2.6)
    c.include(vb_nt, dx=dx_vnt, dy=dy_vnt)
    vnt_xs = sd_xs_of(vb_nt, "ndiffc", dx_vnt)
    vnt_gpts = gate_pts_of(vb_nt, dx_vnt, dy_vnt)
    vnt_gy = vnt_gpts[0][1]
    for idx in (0, 2, 4, 6):
        c.wire("metal1", [(vnt_xs[idx], dy_vnt), (vnt_xs[idx], gy1)], 0.24)
    y_vnt_ib = grid(dy_vnt - 0.40); y_vnt_tl = grid(dy_vnt + 0.55)
    for idx in (1, 5):
        c.via1(vnt_xs[idx], y_vnt_ib)
    c.wire("metal2", [(x_ivb_m3, y_vnt_ib), (vnt_xs[5], y_vnt_ib)], 0.28); c.via2(x_ivb_m3, y_vnt_ib)
    pc_m3_ys["iv_b"].append(y_vnt_ib)
    c.via1(vnt_xs[3], y_vnt_tl); c.wire("metal2", [(x_vtail_m3, y_vnt_tl), (vnt_xs[3], y_vnt_tl)], 0.30)
    c.via2(x_vtail_m3, y_vnt_tl); vtail_ys.append(y_vnt_tl)
    c.wire("metal3", [(x_vtail_m3, min(vtail_ys)), (x_vtail_m3, max(vtail_ys))], 0.36)
    for gx, _ in vnt_gpts[1:5]:
        c.via1(gx, vnt_gy)
    c.wire("metal2", [(x_ivb_m3, vnt_gy), (vnt_gpts[4][0], vnt_gy)], 0.28); c.via2(x_ivb_m3, vnt_gy); pc_m3_ys["iv_b"].append(vnt_gy)
    for gx, sx in ((vnt_gpts[0][0], vnt_xs[0]), (vnt_gpts[5][0], vnt_xs[6])):
        c.wire("metal1", [(gx, vnt_gy), (sx, vnt_gy), (sx, dy_vnt)], 0.24)

    c.wire("metal3", [(x_vda_m3, min(vda_ys)), (x_vda_m3, max(vda_ys))], 0.36)
    c.wire("metal3", [(x_vcm_m3, gy1), (x_vcm_m3, max(vcm_ys))], 0.44)
    c.wire("metal3", [(x_ivin_m3, min(pc_m3_ys["iv_in"])), (x_ivin_m3, max(pc_m3_ys["iv_in"]))], 0.36)
    c.wire("metal3", [(x_ivb_m3, min(pc_m3_ys["iv_b"])), (x_ivb_m3, max(pc_m3_ys["iv_b"]))], 0.36)

    # --- 1B. pbuf_v2 (x=80.7..174.8, y=0.6..34.8): horiz Xr0 + 3x Xr5 + 2-row 4->16 CMOS decoder + LVT OTA ---
    dx_pr0, dy_pr0 = grid(100.8), grid(8.05)  # left 80.44 (0.40 clear of vb_np), right 121.16 (0.50 clear of pb_xr5!)
    c.include(pb_xr0, dx=dx_pr0, dy=dy_pr0)
    pr0_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_pr0) for r in pb_xr0.rects["viali"]})
    pr0_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_pr0) for r in pb_xr0.rects["viali"]})
    pr0_body = pb_xr0.rects["ppolyres"][0]; pr0_bh = grid(pr0_body[3] - pr0_body[1])
    for yd_c in (grid(pr0_ys[0] - 1.48), grid(pr0_ys[-1] + 1.48)):
        c.rect("ppolyres", grid(pr0_body[0] + dx_pr0), grid(yd_c - pr0_bh / 2), grid(pr0_body[2] + dx_pr0), grid(yd_c + pr0_bh / 2))
    for i in range(7):
        xj = pr0_xs[0] if i % 2 == 0 else pr0_xs[-1]
        c.wire("metal1", [(xj, pr0_ys[i]), (xj, pr0_ys[i + 1])], 0.40)
    pt_pr0_t0 = (pr0_xs[-1], pr0_ys[0])
    pt_pr0_vss = (pr0_xs[-1], pr0_ys[-1])
    # Route pt_pr0_vss straight UP to dec_y0s[0] vss rail (NEVER cross pb_xr0 contacts or pt_pr0_t0!)
    c.wire("metal1", [pt_pr0_vss, (pt_pr0_vss[0], grid(15.92))], 0.34)

    # 3x pb_xr5 placed as ONE uniform 15-bar 1.48-um-pitch array (outer dummies ONLY at far left & far right!)
    # Alternating serpentine parity -> ZERO vertical inter-group jumpers & ZERO overlapping internal dummies!
    pr5_dxs = [grid(127.0), grid(134.4), grid(141.8)]  # 5 * 1.48 = 7.40 um pitch!
    dy_pr5 = grid(7.6)
    tap_pts: dict[int, tuple[float, float]] = {}
    all_xs5: list[float] = []
    yb5 = yt5 = 0.0
    for g_i, dx_5 in enumerate(pr5_dxs):
        c.include(pb_xr5, dx=dx_5, dy=dy_pr5)
        xs5 = sorted({grid((r[0] + r[2]) / 2.0 + dx_5) for r in pb_xr5.rects["viali"]})
        ys5 = sorted({grid((r[1] + r[3]) / 2.0 + dy_pr5) for r in pb_xr5.rects["viali"]})
        yb5, yt5 = ys5[0], ys5[-1]
        all_xs5.extend(xs5)
    # Add outer physical dummy ppolyres bars ONLY at far left (all_xs5[0]-1.48) and far right (all_xs5[-1]+1.48)
    r5_body = pb_xr5.rects["ppolyres"][0]; r5_bw = grid(r5_body[2] - r5_body[0])
    for xd_c in (grid(all_xs5[0] - 1.48), grid(all_xs5[-1] + 1.48)):
        c.rect("ppolyres", grid(xd_c - r5_bw / 2), grid(r5_body[1] + dy_pr5), grid(xd_c + r5_bw / 2), grid(r5_body[3] + dy_pr5))
    tap_pts[0] = (all_xs5[0], yb5)
    c.wire("metal1", [pt_pr0_t0, (all_xs5[0], pt_pr0_t0[1]), (all_xs5[0], yb5)], 0.34)
    for k in range(15):
        ye = yt5 if k % 2 == 0 else yb5
        if k < 14:
            c.wire("metal1", [(all_xs5[k], ye), (all_xs5[k + 1], ye)], 0.38)
            tap_pts[k + 1] = (grid((all_xs5[k] + all_xs5[k + 1]) / 2.0), ye)
        else:
            tap_pts[15] = (all_xs5[14], ye)
    c.via1(*tap_pts[15]); c.wire("metal2", [tap_pts[15], (x_ipin_m3, tap_pts[15][1])], 0.32)
    c.via2(x_ipin_m3, tap_pts[15][1]); pc_m3_ys["ip_in"].append(tap_pts[15][1])

    # Compact 2-row 4->16 static CMOS decoder + 16 tgates (x=80.7..148.2 -> 0 diff/tap.9, 0 diff/tap.11, 0 nwell.2a!)
    x_dec_l = grid(80.7); x_dec_r = grid(148.2)
    dec_y0s = [grid(15.92), grid(25.35)]
    dec_rails = []
    for y0 in dec_y0s:
        dec_rails.append(_cmos_row_rails(c, x_dec_l, x_dec_r, y0, grid(y0 + 4.85), grid(y0 + 8.90)))
    c.rect("nwell", grid(x_dec_l - 0.3), grid(33.9), grid(x_dec_r + 0.3), grid(35.3))
    c.wire("metal1", [(x_dec_l, dec_rails[0][0]), (x_dec_l, dec_rails[1][0])], 0.40)
    c.via1(x_dec_l, dec_rails[0][0])
    c.wire("metal2", [(x_dec_l, dec_rails[0][0]), (grid(79.8), dec_rails[0][0]), (grid(79.8), gy1)], 0.36)
    c.via1(grid(79.8), gy1)
    c.wire("metal1", [(x_dec_r, dec_rails[0][1]), (x_dec_r, dec_rails[1][1])], 0.40)

    def place_inv2(xc: float, y0: float, yvss: float, yvdd: float) -> dict:
        yn, yp = grid(y0 + 1.50), grid(y0 + 6.65)
        c.include(pb_n1, dx=xc, dy=yn); c.include(pb_p2, dx=xc, dy=yp)
        nxs = sd_xs_of(pb_n1, "ndiffc", xc); pxs = sd_xs_of(pb_p2, "pdiffc", xc)
        gx, ngy = grid(xc + pb_n1.pins("G")[0][0]), grid(yn + pb_n1.pins("G")[0][1])
        pgy = grid(yp + pb_p2.pins("G")[0][1])
        c.wire("metal1", [(nxs[0], yn), (nxs[0], yvss)], 0.22)
        c.wire("metal1", [(pxs[0], yp), (pxs[0], yvdd)], 0.22)
        x_o = grid(xc + 0.60)  # via1 is ONLY in open channel (0.60-0.10-0.35 = 0.15 > 0.14 wire clearance to S/D!)
        c.wire("metal1", [(nxs[1], yn), (x_o, yn), (x_o, yp), (pxs[1], yp)], 0.20)
        c.wire("metal1", [(gx, ngy), (gx, pgy)], 0.20)
        return dict(inp=(gx, grid(y0 + 3.60)), out=(x_o, grid(y0 + 3.60)))

    def place_nand2_2(xc: float, y0: float, yvss: float, yvdd: float) -> dict:
        yn, yp = grid(y0 + 1.65), grid(y0 + 6.65)
        x1, x2 = grid(xc - 0.62), grid(xc + 0.62)
        c.include(pb_n2, dx=x1, dy=yn); c.include(pb_n2, dx=x2, dy=yn)
        c.include(pb_p2, dx=x1, dy=yp); c.include(pb_p2, dx=x2, dy=yp)
        n1s = sd_xs_of(pb_n2, "ndiffc", x1); n2s = sd_xs_of(pb_n2, "ndiffc", x2)
        p1s = sd_xs_of(pb_p2, "pdiffc", x1); p2s = sd_xs_of(pb_p2, "pdiffc", x2)
        g1x, ng1y = grid(x1 + pb_n2.pins("G")[0][0]), grid(yn + pb_n2.pins("G")[0][1])
        g2x, ng2y = grid(x2 + pb_n2.pins("G")[0][0]), grid(yn + pb_n2.pins("G")[0][1])
        pg1y = grid(yp + pb_p2.pins("G")[0][1]); pg2y = grid(yp + pb_p2.pins("G")[0][1])
        c.wire("metal1", [(n2s[1], yn), (n2s[1], yvss)], 0.22)
        c.wire("metal1", [(n1s[1], yn), (n2s[0], yn)], 0.22)
        c.wire("metal1", [(p1s[1], yp), (p1s[1], yvdd)], 0.22)
        c.wire("metal1", [(p2s[0], yp), (p2s[0], yvdd)], 0.22)
        x_ol = grid(x1 - 0.66)
        c.wire("metal1", [(n1s[0], yn), (x_ol, yn), (x_ol, grid(y0 + 7.55))], 0.20)
        # Put p1s[0] bridge at yp+0.20 so y_ao[2]=6.85 via1 overlaps solidly (ZERO 0.01 um slit!)
        c.wire("metal1", [(x_ol, grid(yp + 0.20)), (p1s[0], grid(yp + 0.20))], 0.20)
        y_pm2 = grid(y0 + 7.86)
        c.wire("metal1", [(p1s[0], yp), (p1s[0], y_pm2)], 0.23)
        c.wire("metal1", [(p2s[1], yp), (p2s[1], y_pm2)], 0.23)
        c.via1(p1s[0], y_pm2); c.via1(p2s[1], y_pm2)
        c.wire("metal2", [(p1s[0], y_pm2), (p2s[1], y_pm2)], 0.24)
        c.wire("metal1", [(g1x, ng1y), (g1x, pg1y)], 0.20)
        c.wire("metal1", [(g2x, ng2y), (g2x, pg2y)], 0.20)
        return dict(a=(g1x, grid(y0 + 3.60)), b=(g2x, grid(y0 + 3.60)), out=(x_ol, grid(y0 + 6.40)))

    def place_nor_inv_tg2(xc: float, y0: float, yvss: float, yvdd: float) -> dict:
        yn, yp = grid(y0 + 1.50), grid(y0 + 6.65)
        xa, xb = grid(xc - 2.25), grid(xc - 0.30)
        xi, xt = grid(xc + 0.98), grid(xc + 2.68)  # x_io=+1.58, x_tin=+2.02 (gap 0.18!), x_tout=+3.34 (via1 gap 0.15, next_xa gap 0.165!)
        c.include(pb_n1, dx=xa, dy=yn); c.include(pb_n1, dx=xb, dy=yn)
        c.include(pb_p4, dx=xa, dy=yp); c.include(pb_p4, dx=xb, dy=yp)
        nas = sd_xs_of(pb_n1, "ndiffc", xa); nbs = sd_xs_of(pb_n1, "ndiffc", xb)
        pas = sd_xs_of(pb_p4, "pdiffc", xa); pbs = sd_xs_of(pb_p4, "pdiffc", xb)
        gax, ngay = grid(xa + pb_n1.pins("G")[0][0]), grid(yn + pb_n1.pins("G")[0][1])
        gbx, ngby = grid(xb + pb_n1.pins("G")[0][0]), grid(yn + pb_n1.pins("G")[0][1])
        pgax, pgay = grid(xa + pb_p4.pins("G")[0][0]), grid(yp + pb_p4.pins("G")[0][1])
        pgbx, pgby = grid(xb + pb_p4.pins("G")[0][0]), grid(yp + pb_p4.pins("G")[0][1])
        c.wire("metal1", [(nas[0], yn), (nas[0], yvss)], 0.22)
        c.wire("metal1", [(nbs[1], yn), (nbs[1], yvss)], 0.22)
        x_ps = grid((xa + xb) / 2.0)
        y_ps_top = grid(y0 + 6.22)
        c.wire("metal1", [(nas[1], yn), (nbs[0], yn)], 0.20)
        c.wire("metal1", [(x_ps, yn), (x_ps, y_ps_top)], 0.20)
        for sx in (pbs[0], pbs[2]):
            c.wire("metal1", [(sx, yp), (sx, yvdd)], 0.22)
        y_p4m = grid(y0 + 7.86)  # 0.51 above y_ao[3]=7.35 (0.15 > 0.14!) & 0.16 below y_vdd M1!
        for sx in (pbs[1], pas[0], pas[2]):
            c.wire("metal1", [(sx, yp), (sx, y_p4m)], 0.23)
            c.via1(sx, y_p4m)
        c.wire("metal2", [(pas[0], y_p4m), (pbs[1], y_p4m)], 0.24)
        c.wire("metal1", [(pas[1], yp), (pas[1], y_ps_top)], 0.23)
        c.via1(pas[1], y_ps_top); c.via1(x_ps, y_ps_top)
        c.wire("metal2", [(pas[1], y_ps_top), (x_ps, y_ps_top)], 0.24)
        c.wire("metal1", [(gax, ngay), (gax, pgay), (pgax, pgay)], 0.20)
        c.wire("metal1", [(gbx, ngby), (gbx, pgby), (pgbx, pgby)], 0.20)
        inv = place_inv2(xi, y0, yvss, yvdd)
        c.include(pb_n1, dx=xt, dy=yn); c.include(pb_p2, dx=xt, dy=yp)
        tns = sd_xs_of(pb_n1, "ndiffc", xt); tps = sd_xs_of(pb_p2, "pdiffc", xt)
        tgnx, tgny = grid(xt + pb_n1.pins("G")[0][0]), grid(yn + pb_n1.pins("G")[0][1])
        tgpx, tgpy = grid(xt + pb_p2.pins("G")[0][0]), grid(yp + pb_p2.pins("G")[0][1])
        x_tin = grid(xt - 0.66); x_tout = grid(xt + 0.66)  # 0.15 > 0.14 clear of tns/tps AND 0.165 clear of next_xa!
        c.wire("metal1", [(tns[0], yn), (x_tin, yn), (x_tin, grid(y0 + 6.95))], 0.18)
        c.wire("metal1", [(x_tin, yp), (tps[0], yp)], 0.18)
        c.wire("metal1", [(tns[1], yn), (x_tout, yn), (x_tout, yp), (tps[1], yp)], 0.20)
        y_ps_tg = grid(y0 + 2.28)
        c.via1(x_ps, y_ps_tg); c.via1(inv["inp"][0], y_ps_tg); c.via1(tgnx, y_ps_tg)
        c.wire("metal1", [(tgnx, tgny), (tgnx, y_ps_tg)], 0.22)
        c.wire("metal1", [(inv["inp"][0], ngay), (inv["inp"][0], y_ps_tg)], 0.22)
        c.wire("metal2", [(x_ps, y_ps_tg), (tgnx, y_ps_tg)], 0.24)
        y_sb_tg = grid(y0 + 4.57)
        c.via1(inv["out"][0], y_sb_tg); c.via1(tgpx, y_sb_tg)
        c.wire("metal1", [(tgpx, tgpy), (tgpx, y_sb_tg)], 0.20)
        c.wire("metal2", [(inv["out"][0], y_sb_tg), (tgpx, y_sb_tg)], 0.24)
        return dict(in_b=(gax, grid(y0 + 3.60)), in_a=(gbx, grid(y0 + 3.60)),
                    tap_in=(x_tin, grid(y0 + 6.80)), tap_out=(x_tout, yn))

    # 2 INV on Row 0 (c0, c1) + 2 INV on Row 1 (c2, c3): inv_c[0]=81.65 -> pxs[0]=81.41 > x_vdd_l=81.40!
    inv_c = [
        place_inv2(grid(81.65), dec_y0s[0], *dec_rails[0]),
        place_inv2(grid(83.10), dec_y0s[0], *dec_rails[0]),
        place_inv2(grid(81.65), dec_y0s[1], *dec_rails[1]),
        place_inv2(grid(83.10), dec_y0s[1], *dec_rails[1]),
    ]
    nand_a = [place_nand2_2(grid(85.40 + i * 2.60), dec_y0s[0], *dec_rails[0]) for i in range(4)]
    nand_b = [place_nand2_2(grid(85.40 + i * 2.60), dec_y0s[1], *dec_rails[1]) for i in range(4)]

    # 16 NOR2+INV+TGATE cells: 8 on Row 0, 8 on Row 1 at xc=99.15..144.30 (pitch 6.45, right x_tout=147.62 < 148.2!)
    tgate_in_pts: dict[int, tuple[float, float]] = {}
    tgate_out_pts: list[tuple[float, float]] = []
    nor_a_pts: dict[int, list[tuple[float, float]]] = {i: [] for i in range(4)}
    nor_b_pts: dict[int, list[tuple[float, float]]] = {j: [] for j in range(4)}
    for k in range(16):
        row_i = k // 8; col_i = k % 8
        xc = grid(99.15 + col_i * 6.45)
        cell_d = place_nor_inv_tg2(xc, dec_y0s[row_i], *dec_rails[row_i])
        tgate_in_pts[k] = cell_d["tap_in"]
        tgate_out_pts.append(cell_d["tap_out"])
        nor_b_pts[k // 4].append(cell_d["in_b"])
        nor_a_pts[k % 4].append(cell_d["in_a"])

    # Wire c0..c3 bottom perimeter ports (c2=80.85, c0=81.65, c1=83.10, c3=84.30 -> >= 0.80 pitch & clear of ox via1!)
    c_m3_in: list[float] = [grid(81.65), grid(83.10), grid(80.85), grid(84.30)]
    for grp, nands, y0, base_c in ((0, nand_a, dec_y0s[0], 0), (1, nand_b, dec_y0s[1], 2)):
        y_tr = [grid(y0 + 2.95 + m * 0.48) for m in range(4)]
        sigs_x = []
        for off in range(2):
            ci = base_c + off
            ix, iy = inv_c[ci]["inp"]; ox, oy = inv_c[ci]["out"]
            tx_c = c_m3_in[ci]
            yt_i = y_tr[2 * off]; yt_o = y_tr[2 * off + 1]
            c.via1(ix, yt_i); c.via2(tx_c, yt_i)
            if tx_c != ix:
                c.wire("metal2", [(min(ix, tx_c), yt_i), (max(ix, tx_c), yt_i)], 0.24)
            c.wire("metal3", [(tx_c, gy1), (tx_c, yt_i)], 0.34)
            c.via1(ox, yt_o)
            sigs_x.extend([ix, ox])
        for ni, (ia, ib) in enumerate(((3, 1), (3, 0), (2, 1), (2, 0))):
            ax, ay = nands[ni]["a"]; bx, by = nands[ni]["b"]
            c.via1(ax, y_tr[ia]); c.wire("metal2", [(sigs_x[ia], y_tr[ia]), (ax, y_tr[ia])], 0.24)
            c.via1(bx, y_tr[ib]); c.wire("metal2", [(sigs_x[ib], y_tr[ib]), (bx, y_tr[ib])], 0.24)

    # Wire a0n..a3n (M3 at 94.45..96.70 -> STRICTLY RIGHT of nand[3]["b"]=93.82 -> ZERO short & 0 met2.2!)
    for i in range(4):
        ox, oy = nand_a[i]["out"]
        x_a_m3 = grid(94.45 + i * 0.75)
        y_ao = grid(dec_y0s[0] + 5.94 + i * 0.47)
        ya0 = grid(dec_y0s[0] + 2.73 + i * 0.47); ya1 = grid(dec_y0s[1] + 2.73 + i * 0.47)
        c.via1(ox, y_ao); c.wire("metal2", [(ox, y_ao), (x_a_m3, y_ao)], 0.24)
        c.via2(x_a_m3, y_ao); c.via2(x_a_m3, ya0); c.via2(x_a_m3, ya1)
        c.wire("metal3", [(x_a_m3, ya0), (x_a_m3, ya1)], 0.34)
        for row_i, y_bus in ((0, ya0), (1, ya1)):
            pts = [p for p in nor_a_pts[i] if abs(p[1] - (dec_y0s[row_i] + 3.60)) < 2.0]
            c.wire("metal2", [(x_a_m3, y_bus), (max(p[0] for p in pts), y_bus)], 0.24)
            for px, _ in pts:
                c.via1(px, y_bus)

    b_m3_cols = [grid(85.30), grid(86.05), grid(87.90), grid(88.65)]
    for j in range(4):
        ox, oy = nand_b[j]["out"]
        row_i = j // 2
        yb = grid(dec_y0s[row_i] + 5.00 + (j % 2) * 0.47)
        y_bo = grid(dec_y0s[1] + 5.94 + j * 0.47)
        x_b_m3 = b_m3_cols[j]
        c.via1(ox, y_bo); c.wire("metal2", [(min(ox, x_b_m3), y_bo), (max(ox, x_b_m3), y_bo)], 0.24)
        c.via2(x_b_m3, y_bo); c.via2(x_b_m3, yb)
        c.wire("metal3", [(x_b_m3, min(y_bo, yb)), (x_b_m3, max(y_bo, yb))], 0.34)
        pts = nor_b_pts[j]
        c.wire("metal2", [(x_b_m3, yb), (max(p[0] for p in pts), yb)], 0.24)
        for px, _ in pts:
            c.via1(px, yb)

    # 100% PLANAR 16-TAP ROUTER (y_bus strictly in [3.55..10.83]; >= 0.73 um M3 pitch -> 0.33 > 0.30 met3.2!)
    tap_m3_segs: list[tuple[int, float, float, float]] = [
        (-1, x_ipin_m3, 0.0, 40.0), (-1, x_ipb_m3, 0.0, 40.0), (-1, x_tap_bus, 0.0, 40.0),
    ]
    for k in range(15):
        sx, sy = tap_pts[k]
        y_bus = grid(3.55 + k * 0.52)
        tap_m3_segs.append((k, sx, min(sy, y_bus) - 0.35, max(sy, y_bus) + 0.35))
    for k in range(15):
        sx, sy = tap_pts[k]; dx_t, dy_t = tgate_in_pts[k]
        y_bus = grid(3.55 + k * 0.52)
        cands = []
        if abs(sx - dx_t) <= 2.90:
            cands.append(sx)
        base_c = dx_t if k < 8 else grid(dx_t - 0.78)
        for st in sorted(range(-58, 59), key=abs):
            cx = grid(base_c + st * 0.05)
            if abs(cx - dx_t) <= 2.90 and 98.4 <= cx <= 147.1:
                cands.append(cx)
        found = None
        for cx in cands:
            y_lo = (min(sy, dy_t) if cx == sx else y_bus) - 0.35
            y_hi = dy_t + 0.35
            if all(uk == k or abs(cx - ux) >= 0.73 or y_hi < u_lo or y_lo > u_hi for uk, ux, u_lo, u_hi in tap_m3_segs):
                found = cx
                break
        assert found is not None, f"No local free M3 column for tap {k} near dx_t={dx_t}"
        x_drop = found
        if x_drop == sx:
            # Same-net straight vertical M3 from (sx, sy) UP to (sx, dy_t) -> ZERO y_bus needed!
            tap_m3_segs.append((k, sx, min(sy, dy_t) - 0.35, dy_t + 0.35))
            c.via1(sx, sy); c.via2(sx, sy)
            c.wire("metal3", [(sx, sy), (sx, dy_t)], 0.40)
            c.via2(sx, dy_t)
            if sx != dx_t:
                c.wire("metal2", [(min(sx, dx_t), dy_t), (max(sx, dx_t), dy_t)], 0.32)
            c.via1(dx_t, dy_t)
        else:
            tap_m3_segs.append((k, x_drop, y_bus - 0.35, dy_t + 0.35))
            c.via1(sx, sy); c.via2(sx, sy)
            c.wire("metal3", [(sx, min(sy, y_bus)), (sx, max(sy, y_bus))], 0.40)
            c.via2(sx, y_bus)
            c.wire("metal2", [(min(sx, x_drop), y_bus), (max(sx, x_drop), y_bus)], 0.24)
            c.via2(x_drop, y_bus)
            c.wire("metal3", [(x_drop, y_bus), (x_drop, dy_t)], 0.40)
            c.via2(x_drop, dy_t)
            if x_drop != dx_t:
                c.wire("metal2", [(min(x_drop, dx_t), dy_t), (max(x_drop, dx_t), dy_t)], 0.32)
            c.via1(dx_t, dy_t)
    # Tap 15 IS ip_in -> tap directly off x_ipin_m3=148.0 at dy_t (ZERO extra M3 column!)
    dx15, dy15 = tgate_in_pts[15]
    c.via1(dx15, dy15); c.via2(x_ipin_m3, dy15)
    c.wire("metal2", [(dx15, dy15), (x_ipin_m3, dy15)], 0.24)

    # Common tap output bus (tgate_out_pts -> x_tap_bus=150.0 -> pbuf OTA)
    y_tap_r0 = grid(dec_y0s[0] + 0.80); y_tap_r1 = grid(dec_y0s[1] + 0.80)
    for k, (ox, oy) in enumerate(tgate_out_pts):
        yb = y_tap_r0 if k < 8 else y_tap_r1
        c.wire("metal1", [(ox, oy), (ox, yb)], 0.20); c.via1(ox, yb)
    c.wire("metal2", [(tgate_out_pts[0][0], y_tap_r0), (x_tap_bus, y_tap_r0)], 0.28)
    c.wire("metal2", [(tgate_out_pts[8][0], y_tap_r1), (x_tap_bus, y_tap_r1)], 0.28)
    c.via2(x_tap_bus, y_tap_r0); c.via2(x_tap_bus, y_tap_r1)
    c.wire("metal3", [(x_tap_bus, y_tap_r0), (x_tap_bus, y_tap_r1)], 0.40)

    # --- 1C. pbuf LVT OTA (x=150.0..174.9, y=0.6..34.8) ---
    x_po_c = grid(162.4)
    dy_ppl = grid(27.2); dy_pnp = grid(14.5); dy_pxt = grid(4.5)
    c.include(pb_pl, dx=x_po_c, dy=dy_ppl)
    c.include(pb_np, dx=x_po_c, dy=dy_pnp)
    c.include(pb_xt, dx=grid(156.2), dy=dy_pxt)
    c.include(pb_xst, dx=grid(163.2), dy=dy_pxt)
    c.include(pb_bd, dx=grid(167.8), dy=dy_pxt)

    ppl_xs = sd_xs_of(pb_pl, "pdiffc", x_po_c)
    ppl_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_ppl) for r in pb_pl.rects["pdiffc"]})
    ppl_gxs = sorted({grid(x + x_po_c) for _, x, _, nm in pb_pl.labels if nm.startswith("G")})
    ppl_gys = sorted({grid(y + dy_ppl) for _, _, y, nm in pb_pl.labels if nm.startswith("G")})
    po_da_ys: list[float] = []; po_out_ys: list[float] = []; po_vdd_ys: list[float] = []
    for r_i, yr in enumerate(ppl_ys):
        yv = grid(yr + 1.6); yda = grid(yr + 0.1); you = grid(yr - 1.4)
        for idx in (1, 3, 5, 7, 9, 11, 13, 15, 17):
            c.via1(ppl_xs[idx], yv)
        c.wire("metal2", [(x_po_vdd, yv), (ppl_xs[17], yv)], 0.36); c.via2(x_po_vdd, yv); po_vdd_ys.append(yv)
        a_cols = (2, 4, 14, 16) if r_i == 0 else (6, 8, 10, 12)
        b_cols = (6, 8, 10, 12) if r_i == 0 else (2, 4, 14, 16)
        for idx in a_cols:
            c.via1(ppl_xs[idx], yda)
        c.wire("metal2", [(x_po_da, yda), (ppl_xs[max(a_cols)], yda)], 0.30); c.via2(x_po_da, yda); po_da_ys.append(yda)
        for idx in (0,) + b_cols + (18,):
            c.via1(ppl_xs[idx], you)
        c.wire("metal2", [(ppl_xs[0], you), (x_po_out, you)], 0.30); c.via2(x_po_out, you); po_out_ys.append(you)
        gy = ppl_gys[r_i]
        for gx in ppl_gxs[1:17]:
            c.via1(gx, gy)
        c.wire("metal2", [(x_po_da, gy), (ppl_gxs[16], gy)], 0.28); c.via2(x_po_da, gy); po_da_ys.append(gy)
        c.wire("metal1", [(ppl_gxs[0], gy), (grid(ppl_xs[1] - 0.50), gy), (grid(ppl_xs[1] - 0.50), grid(gy + 0.55)), (ppl_xs[1], grid(gy + 0.55))], 0.22)
        c.wire("metal1", [(ppl_gxs[17], gy), (grid(ppl_xs[17] + 0.50), gy), (grid(ppl_xs[17] + 0.50), grid(gy + 0.55)), (ppl_xs[17], grid(gy + 0.55))], 0.22)
    y_ppl_ring = grid(dy_ppl + 7.065)
    c.wire("metal1", [(ppl_xs[1], ppl_ys[-1]), (ppl_xs[1], y_ppl_ring)], 0.30); c.pad("viali", ppl_xs[1], y_ppl_ring, 0.17)
    c.via1(x_dec_r, dec_rails[1][1]); c.wire("metal2", [(x_dec_r, dec_rails[1][1]), (x_po_vdd, dec_rails[1][1])], 0.44); c.via2(x_po_vdd, dec_rails[1][1])
    c.wire("metal3", [(x_po_vdd, min(po_vdd_ys + [dec_rails[1][1]])), (x_po_vdd, grid(pc_ys[0] + 2.4))], 0.50)
    c.via2(x_po_vdd, grid(pc_ys[0] + 2.4))

    pnp_xs_n = sd_xs_of(pb_np, "ndiffc", x_po_c)
    pnp_gpts = gate_pts_of(pb_np, x_po_c, dy_pnp)
    pnp_gy = pnp_gpts[0][1]
    y_pn_t = grid(dy_pnp - 1.6); y_pn_da = grid(dy_pnp + 0.0); y_pn_out = grid(dy_pnp + 1.6)
    y_pn_tap = grid(pnp_gy + 0.65); y_pn_outg = grid(pnp_gy + 1.35)
    for tx in (pnp_xs_n[1], pnp_xs_n[3], pnp_xs_n[5], pnp_xs_n[7], pnp_xs_n[9]):
        c.via1(tx, y_pn_t)
    c.wire("metal2", [(pnp_xs_n[1], y_pn_t), (pnp_xs_n[9], y_pn_t)], 0.36)
    for ax in (pnp_xs_n[2], pnp_xs_n[8]):
        c.via1(ax, y_pn_da)
    c.wire("metal2", [(x_po_da, y_pn_da), (pnp_xs_n[8], y_pn_da)], 0.30); c.via2(x_po_da, y_pn_da); po_da_ys.append(y_pn_da)
    for bx in (pnp_xs_n[4], pnp_xs_n[6]):
        c.via1(bx, y_pn_out)
    c.wire("metal2", [(pnp_xs_n[4], y_pn_out), (x_po_out, y_pn_out)], 0.30); c.via2(x_po_out, y_pn_out); po_out_ys.append(y_pn_out)
    for idx in (1, 2, 7, 8):
        gx = pnp_gpts[idx][0]; c.via1(gx, pnp_gy); c.wire("metal2", [(gx, pnp_gy), (gx, y_pn_tap)], 0.32)
    c.wire("metal2", [(x_tap_bus, y_pn_tap), (pnp_gpts[8][0], y_pn_tap)], 0.30); c.via2(x_tap_bus, y_pn_tap)
    c.wire("metal3", [(x_tap_bus, min(y_tap_r0, y_pn_tap)), (x_tap_bus, max(y_tap_r1, y_pn_tap))], 0.40)
    for idx in (3, 4, 5, 6):
        gx = pnp_gpts[idx][0]; c.via1(gx, pnp_gy); c.via2(gx, pnp_gy)
        c.wire("metal3", [(gx, pnp_gy), (gx, y_pn_outg)], 0.40); c.via2(gx, y_pn_outg)
    c.wire("metal2", [(pnp_gpts[3][0], y_pn_outg), (x_po_out, y_pn_outg)], 0.30); c.via2(x_po_out, y_pn_outg); po_out_ys.append(y_pn_outg)
    y_po_ptap = grid(dy_pnp - 4.8)
    c.rect("pwell", grid(152.0), grid(y_po_ptap - 0.45), gx2, grid(y_po_ptap + 0.45))
    c.rect("psubdiff", grid(152.4), grid(y_po_ptap - 0.22), gx2, grid(y_po_ptap + 0.22))
    c.rect("psubdiffcont", grid(152.7), grid(y_po_ptap - 0.085), grid(gx2 - 0.3), grid(y_po_ptap + 0.085))
    c.rect("locali", grid(152.4), grid(y_po_ptap - 0.22), gx2, grid(y_po_ptap + 0.22))
    c.rect("metal1", grid(152.4), grid(y_po_ptap - 0.24), gx2, grid(y_po_ptap + 0.24))
    for i in range(4):
        c.pad("viali", grid(154.0 + i * 5.5), y_po_ptap, 0.17)
    for gx, sx in ((pnp_gpts[0][0], pnp_xs_n[0]), (pnp_gpts[9][0], pnp_xs_n[10])):
        c.wire("metal1", [(gx, pnp_gy), (sx, pnp_gy), (sx, y_po_ptap)], 0.24)

    pxt_xs = sd_xs_of(pb_xt, "ndiffc", grid(156.2))
    pxt_g = grid(156.2 + pb_xt.pins("G")[0][0]); pxt_gy = grid(dy_pxt + pb_xt.pins("G")[0][1])
    pxst_xs = sd_xs_of(pb_xst, "ndiffc", grid(163.2))
    pxst_g = grid(163.2 + pb_xst.pins("G")[0][0]); pxst_gy = grid(dy_pxt + pb_xst.pins("G")[0][1])
    pbd_xs = sd_xs_of(pb_bd, "ndiffc", grid(167.8))
    pbd_g = grid(167.8 + pb_bd.pins("G")[0][0]); pbd_gy = grid(dy_pxt + pb_bd.pins("G")[0][1])
    y_pxt_d = grid(dy_pxt + 1.2); y_pxt_s = grid(dy_pxt - 1.2)
    for dx in pxt_xs[1::2]:
        c.via1(dx, y_pxt_d)
    c.wire("metal2", [(pxt_xs[1], y_pxt_d), (pxt_xs[-2], y_pxt_d)], 0.36)
    c.via2(pxt_xs[3], y_pxt_d); c.via2(pxt_xs[3], y_pn_t)
    c.wire("metal3", [(pxt_xs[3], y_pxt_d), (pxt_xs[3], y_pn_t)], 0.44)
    # Connect pxt_xs[3]=156.2 horizontally on M2 to pb_np tail pnp_xs_n[1]=157.2!
    c.wire("metal2", [(min(pxt_xs[3], pnp_xs_n[1]), y_pn_t), (pnp_xs_n[1], y_pn_t)], 0.36)
    for sx in pxt_xs[::2]:
        c.via1(sx, y_pxt_s)
    for dx in pxst_xs[1::2]:
        c.via1(dx, y_pxt_s)
    c.wire("metal2", [(pxt_xs[0], y_pxt_s), (pxst_xs[-2], y_pxt_s)], 0.36)
    y_pxst_s = grid(dy_pxt - 2.0)
    for sx in pxst_xs[::2]:
        c.via1(sx, y_pxst_s)
    c.wire("metal2", [(pxst_xs[0], y_pxst_s), (pxst_xs[-1], y_pxst_s)], 0.36)
    c.wire("metal2", [(pxst_xs[0], y_pxst_s), (pxst_xs[0], gy1)], 0.36); c.via1(pxst_xs[0], gy1)
    c.wire("metal1", [(pbd_xs[0], dy_pxt), (pbd_xs[0], gy1)], 0.24)
    c.via1(pbd_xs[1], dy_pxt); c.via1(pbd_g, pbd_gy); c.via1(pxt_g, pxt_gy)
    c.wire("metal2", [(x_ipb_m3, pxt_gy), (pbd_xs[1], pxt_gy)], 0.30); c.via2(x_ipb_m3, pxt_gy); pc_m3_ys["ip_b"].append(pxt_gy)
    c.wire("metal2", [(pbd_g, pbd_gy), (pbd_g, pxt_gy)], 0.28)
    c.wire("metal2", [(pbd_xs[1], dy_pxt), (pbd_xs[1], pxt_gy)], 0.28)
    x_en_port = grid(163.2 + pb_xst.bbox()[2] + 0.60)
    # Lift en_pbuf on M1 UP to y_en=7.85 (0.73 above pxt_gy=7.12) BEFORE via1/via2 -> ZERO short to ip_b!
    y_en = grid(pxst_gy + 0.60)
    c.wire("metal1", [(pxst_g, pxst_gy), (x_en_port, pxst_gy), (x_en_port, y_en)], 0.22)
    c.via1(x_en_port, y_en); c.via2(x_en_port, y_en)
    c.wire("metal3", [(x_en_port, gy1), (x_en_port, y_en)], 0.34)
    c.wire("metal3", [(x_po_da, min(po_da_ys)), (x_po_da, max(po_da_ys))], 0.36)
    c.wire("metal3", [(x_po_out, gy1), (x_po_out, max(po_out_ys))], 0.50)

    # =========================================================================
    # COMPLETE ALL GLOBAL VERTICAL M3 TRUNKS
    # =========================================================================
    c.wire("metal3", [(x_vdd_l, min(vdd_l_ys)), (x_vdd_l, gy2)], 0.60)
    c.wire("metal3", [(x_vdd_m, min(vdd_m_ys)), (x_vdd_m, gy2)], 0.60)
    c.wire("metal3", [(x_fa_m3, min(fa_ys)), (x_fa_m3, max(fa_ys))], 0.34)
    c.wire("metal3", [(x_fb_m3, min(fb_ys)), (x_fb_m3, max(fb_ys))], 0.34)
    c.wire("metal3", [(x_vbps_m3, min(vbps_ys)), (x_vbps_m3, max(vbps_ys))], 0.34)
    c.wire("metal3", [(x_vbpc_m3, min(vbpc_ys)), (x_vbpc_m3, max(vbpc_ys))], 0.34)
    c.wire("metal3", [(x_fcda_m3, min(fcda_ys)), (x_fcda_m3, max(fcda_ys))], 0.34)
    c.wire("metal3", [(x_vbnc_m3, min(vbnc_ys)), (x_vbnc_m3, max(vbnc_ys))], 0.34)
    c.wire("metal3", [(x_na_m3, min(na_ys)), (x_na_m3, max(na_ys))], 0.34)
    c.wire("metal3", [(x_nbn_m3, min(nbn_ys)), (x_nbn_m3, max(nbn_ys))], 0.34)
    c.wire("metal3", [(x_otada_m3, min(otada_ys)), (x_otada_m3, max(otada_ys))], 0.36)
    c.wire("metal3", [(x_vgi_m3, min(vgi_ys)), (x_vgi_m3, max(vgi_ys))], 0.44)
    c.wire("metal3", [(x_s_m3, min(s_ys)), (x_s_m3, max(s_ys))], 0.36)
    c.wire("metal3", [(x_ipin_m3, min(pc_m3_ys["ip_in"])), (x_ipin_m3, max(pc_m3_ys["ip_in"]))], 0.36)
    c.wire("metal3", [(x_ipb_m3, min(pc_m3_ys["ip_b"])), (x_ipb_m3, max(pc_m3_ys["ip_b"]))], 0.36)
    for nm, x_tr in (("nb", x_nb_m3), ("ta", x_ta_m3), ("tb", x_tb_m3), ("nb2", x_nb2_m3), ("vg", x_vg_m3)):
        ys = xm_net_ys[nm]
        c.wire("metal3", [(x_tr, min(ys)), (x_tr, max(ys))], 0.34)
    c.wire("metal3", [(x_vbg_m3, min(xm_net_ys["vbg"])), (x_vbg_m3, gy2)], 0.44)

    # =========================================================================
    # ALL 20 TOP-LEVEL PERIMETER PORTS
    # =========================================================================
    c.port("vbg", "metal3", x_vbg_m3, gy2)
    c.port("vcm", "metal3", x_vcm_m3, gy1)
    c.port("pref", "metal3", x_po_out, gy1)
    for nm, y_ex in left_port_ys.items():
        c.port(nm, "metal2", gx1, y_ex)
    for gnm in ("g4", "g3", "g2", "g1", "g0"):
        c.port(gnm, "metal2", *g_port_pts[gnm])
    for i in range(4):
        c.port(f"c{i}", "metal3", c_m3_in[i], gy1)
    c.port("en_pbuf", "metal3", x_en_port, gy1)
    c.port("vdd", "metal3", x_vdd_m, gy2)
    c.port("vss", "metal1", grid((gx1 + gx2) / 2.0), gy1)
    c.write(w / f"{cell}.mag")

    ref_lines = [
        "* BIAS v2 serdes_bias_top_v2_pdk (Integrated 4-band macro, internal vgi, 100% real transistors)",
        f".subckt {cell} vbg vcm pref icml ictle icp i_ldo0 i_ldo1 g4 g3 g2 g1 g0 c3 c2 c1 c0 en_pbuf vdd vss",
        "Xm1 ta vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm2 tb vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm3 vbg vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm4 nb vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm5 nb2 vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xxm_dum vbg vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xq1 vss vss a sky130_fd_pr__pnp_05v5_W3p40L3p40",
        *[f"Xq2_{i} vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40" for i in range(8)],
        "Xq3 vss vss d sky130_fd_pr__pnp_05v5_W3p40L3p40",
        *[f"Xrsa{i} {'ta' if i==0 else f'rsa{i}'} {'a' if i==4 else f'rsa{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=39.200" for i in range(5)],
        *[f"Xrsb{i} {'tb' if i==0 else f'rsb{i}'} {'b' if i==4 else f'rsb{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=39.200" for i in range(5)],
        "Xr1 b c vss sky130_fd_pr__res_high_po w=1 l=39.790",
        *[f"Xr2_{i} {'vbg' if i==0 else f'r2_{i}'} {'d' if i==9 else f'r2_{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=37.650" for i in range(10)],
        "Xbd nb nb vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xfc_t fc_tail nb vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xfc_a fc_fa ta fc_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xfc_b fc_fb tb fc_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xfc_ab_dl fc_tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xfc_ab_dr fc_tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xfc_nbp vbp_src nb vss vss sky130_fd_pr__nfet_01v8 w=3 l=4",
        "Xfc_pb vbp_src vbp_src vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8",
        "Xfc_nbpc vbp_c nb vss vss sky130_fd_pr__nfet_01v8 w=3 l=4",
        "Xfc_pbc vbp_c vbp_c vdd vdd sky130_fd_pr__pfet_01v8_lvt w=3 l=4",
        "Xfc_pbnc vbn_c vbp_src vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8",
        "Xfc_nbc vbn_c vbn_c vss vss sky130_fd_pr__nfet_01v8 w=1.5 l=10",
        "Xfc_fa fc_fa vbp_src vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=8",
        "Xfc_fb fc_fb vbp_src vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=8",
        "Xfc_pca fc_da vbp_c fc_fb vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=2.5",
        "Xfc_pcb vg vbp_c fc_fa vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=2.5",
        "Xfc_nca fc_da vbn_c fc_na vss sky130_fd_pr__nfet_01v8 w=16 l=4",
        "Xfc_ncb vg vbn_c fc_nbn vss sky130_fd_pr__nfet_01v8 w=16 l=4",
        "Xfc_na fc_na fc_da vss vss sky130_fd_pr__nfet_01v8 w=16 l=8",
        "Xfc_nb fc_nbn fc_da vss vss sky130_fd_pr__nfet_01v8 w=16 l=8",
        "Xfc_nm_d vss vss vss vss sky130_fd_pr__nfet_01v8 w=16 l=8",
        "Xsp st vss vdd vdd sky130_fd_pr__pfet_01v8 w=0.42 l=20",
        "Xsn st nb vss vss sky130_fd_pr__nfet_01v8 w=2 l=1",
        "Xsu vg st vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        "Xbd2 nb2 nb2 vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xota_t ota_tail nb2 vss vss sky130_fd_pr__nfet_01v8 w=1 l=6",
        "Xota_a ota_da s ota_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xota_b vgi vbg ota_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xota_ab_dl ota_tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xota_ab_dr ota_tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xota_la ota_da ota_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8",
        "Xota_lb vgi ota_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8",
        "Xk vgi vbg s vss sky130_fd_pr__nfet_01v8_lvt w=2 l=4",
        *[f"Xrref{i} {'s' if i==0 else f'rr{i}'} {'rt5' if i==9 else f'rr{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=33.900" for i in range(10)],
        "Xrt4 rt5 rt4 vss sky130_fd_pr__res_high_po w=1 l=38.150",
        "Xrt3 rt4 rt3 vss sky130_fd_pr__res_high_po w=1 l=18.480",
        "Xrt2 rt3 rt2 vss sky130_fd_pr__res_high_po w=1 l=8.645",
        "Xrt1 rt2 rt1 vss sky130_fd_pr__res_high_po w=1 l=3.725",
        "Xrt0 rt1 vss vss sky130_fd_pr__res_high_po w=1 l=1.265",
        "Xs4 rt5 g4 rt4 vss sky130_fd_pr__nfet_01v8 w=20 l=0.18",
        "Xs3 rt4 g3 rt3 vss sky130_fd_pr__nfet_01v8 w=20 l=0.18",
        "Xs2 rt3 g2 rt2 vss sky130_fd_pr__nfet_01v8 w=20 l=0.18",
        "Xs1 rt2 g1 rt1 vss sky130_fd_pr__nfet_01v8 w=20 l=0.18",
        "Xs0 rt1 g0 vss vss sky130_fd_pr__nfet_01v8 w=20 l=0.18",
        *[f"Xcbg1_{i} vbg vss sky130_fd_pr__cap_mim_m3_1 w={mim_side} l={mim_side}" for i in range(3)],
        *[f"Xcbg2_{i} vss vbg sky130_fd_pr__cap_mim_m3_2 w={mim_side} l={mim_side}" for i in range(3)],
        f"Xcgi1 vgi vdd sky130_fd_pr__cap_mim_m3_1 w={mim_side} l={mim_side}",
        f"Xcgi2 vdd vgi sky130_fd_pr__cap_mim_m3_2 w={mim_side} l={mim_side}",
        "Xmv s vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo0 iv_in vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo1 iv_b vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo2 ip_in vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo3 ip_b vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xpc_cml icml vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=680 l=4",
        "Xpc_ctle ictle vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=160 l=4",
        "Xpc_cp icp vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=160 l=4",
        "Xpc_ldo0 i_ldo0 vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xpc_ldo1 i_ldo1 vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        *[f"Xpc_dum{i} vss vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=8 l=4" for i in range(7)],
        "Xfc_fab_dum vdd vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=48 l=8",
        "Xvb_pl_dum vcm vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=8",
        *[f"Xvr{i} {'iv_in' if i==0 else f'vr{i}'} {'vss' if i==7 else f'vr{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=40.185" for i in range(8)],
        "Xvbd iv_b iv_b vss vss sky130_fd_pr__nfet_01v8 w=4 l=4",
        "Xvt vb_tail iv_b vss vss sky130_fd_pr__nfet_01v8 w=4 l=4",
        "Xvdum_tl iv_b vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=4",
        "Xvdum_tr iv_b vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=4",
        "Xva vb_da iv_in vb_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xvb vcm vcm vb_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xvdum_nl vb_tail vss vss vss sky130_fd_pr__nfet_01v8 w=12 l=4",
        "Xvdum_nr vb_tail vss vss vss sky130_fd_pr__nfet_01v8 w=12 l=4",
        "Xvla vb_da vb_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=8",
        "Xvlb vcm vb_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=8",
        *[f"Xpr0_{i} {'pt0' if i==0 else f'pp0_{i}'} {'vss' if i==7 else f'pp0_{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=36.550" for i in range(8)],
        *[f"Xpr{k} {'ip_in' if k==15 else f'pt{k}'} pt{k-1} vss sky130_fd_pr__res_high_po w=1 l=7.360" for k in range(1, 16)],
        *[f"Xpic{i}_n pc{i}b c{i} vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXpic{i}_p pc{i}b c{i} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18" for i in range(4)],
        *[f"Xpna{i}_na pa{i}n {a} pma{i} vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\nXpna{i}_nb pma{i} {b} vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\n"
          f"Xpna{i}_pa pa{i}n {a} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18\nXpna{i}_pb pa{i}n {b} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18"
          for i, (a, b) in enumerate([("pc1b", "pc0b"), ("pc1b", "c0"), ("c1", "pc0b"), ("c1", "c0")])],
        *[f"Xpnb{i}_na pb{i}n {a} pmb{i} vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\nXpnb{i}_nb pmb{i} {b} vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\n"
          f"Xpnb{i}_pa pb{i}n {a} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18\nXpnb{i}_pb pb{i}n {b} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18"
          for i, (a, b) in enumerate([("pc3b", "pc2b"), ("pc3b", "c2"), ("c3", "pc2b"), ("c3", "c2")])],
        *[f"Xpno{k}_na ps{k} pb{k//4}n vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXpno{k}_nb ps{k} pa{k%4}n vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\n"
          f"Xpno{k}_pa ps{k} pb{k//4}n pmno{k} vdd sky130_fd_pr__pfet_01v8 w=4 l=0.18\nXpno{k}_pb pmno{k} pa{k%4}n vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=0.18\n"
          f"Xpi{k}_n psb{k} ps{k} vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXpi{k}_p psb{k} ps{k} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18\n"
          f"Xpg{k}_n {'ip_in' if k==15 else f'pt{k}'} ps{k} ptap vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXpg{k}_p {'ip_in' if k==15 else f'pt{k}'} psb{k} ptap vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18"
          for k in range(16)],
        "Xpbd ip_b ip_b vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        "Xpt pb_tail ip_b pb_ts vss sky130_fd_pr__nfet_01v8 w=30 l=1",
        "Xpst pb_ts en_pbuf vss vss sky130_fd_pr__nfet_01v8 w=30 l=0.18",
        "Xpa pb_da ptap pb_tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xpb pref pref pb_tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xpdum_nl pb_tail vss vss vss sky130_fd_pr__nfet_01v8_lvt w=6 l=1",
        "Xpdum_nr pb_tail vss vss vss sky130_fd_pr__nfet_01v8_lvt w=6 l=1",
        "Xpla pb_da pb_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        "Xplb pref pb_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        "Xpdum_p pref vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=1",
        f".ends {cell}\n",
    ]
    return verify_cell(w, cell, "\n".join(ref_lines), do_rcx=False)
