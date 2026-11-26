#!/usr/bin/env python3
"""Master SKY130A PDK Physical Layout Builder & Signoff Suite for TX v5 5.0 Gb/s SST.

Builds, verifies (Magic full-rule DRC=0, FP=0, Netgen LVS=MATCH with 0 property errors,
independent `verification/layout/review_cell.py --rc` CPEX + native RCX), renders
white-background `plot_mag.py` PNGs, and writes `summary.json` for all 5 hierarchical
deliverables under `analog/tx/sst/layout/variants/v5_pdk/`:

  1. `sst_slice_unit_pdk.mag`          (`sst_slice_unit_5g`: BBM local driver in 8.80 um pitch)
  2. `sst_vdrv_ldo_pdk.mag`            (reused verbatim from `v4p5_pdk` compact_a1=True)
  3. `serdes_tx_sst_driver_pdk.mag`    (`serdes_tx_sst_driver_5g`: 3-row zero-stacked-PMOS CMOS + 28 slices + LDO)
  4. `serdes_tx_sst_serializer16_pdk.mag` (reused verbatim from `v4p5_pdk`)
  5. `serdes_tx_sst_top_pdk.mag`       (`serdes_tx_sst_top_5g`: exact 38-port interface)

Strictly isolated: never touches v4/v4p4/v4p5 files or existing layout helper modules.
"""
from __future__ import annotations

import argparse
import json
import re
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
    N_LVT,
    P_STD,
    R_2P85,
    W_M1,
    grid,
    poly_cont_pad,
    viali_pad,
    via2_clean,
    via3_pad,
    via3_array,
    via4_array,
    locali_v,
    draw_tap_h,
)
import sst_analog_blocks as sab  # noqa: E402
import sst_cmos_cells as scc  # noqa: E402
import sst_serializer_macro as ssm  # noqa: E402
import build_tx_sst_v4_pdk as v4b  # noqa: E402

VARIANT_DIR = HERE / "variants" / "v5_pdk"
RESULTS_DIR = slc.REPO / "results" / "layout" / "tx_sst_v5_pdk"


# ---------------------------------------------------------------------------
# Isolated v5_5g Flattened SPICE LVS Reference Generator
# ---------------------------------------------------------------------------

def generate_ref_spice_5g(
    top_src_subckt: str,
    top_out_subckt: str,
    out_path: Path,
    param_overrides: dict[str, float] | None = None,
) -> list[str]:
    """Flatten `tx_sst_driver_5g.spice` + `tx_sst_serializer16_5g.spice` + `tx_sst_top_5g.spice`."""
    subckts = slc._parse_spice_subckts([
        slc.COMMON_SPICE_DIR / "sky130_primitives.spice",
        slc.SPICE_DIR / "tx_sst_driver_5g.spice",
        slc.SPICE_DIR / "tx_sst_serializer16_5g.spice",
        slc.SPICE_DIR / "tx_sst_top_5g.spice",
    ])
    if top_src_subckt not in subckts:
        raise KeyError(f"Unknown subckt {top_src_subckt}")

    top_def = subckts[top_src_subckt]
    top_ports = list(top_def["ports"])
    lines: list[str] = [
        f"* Exact flattened LVS reference netlist for {top_out_subckt}",
        f"* Source subckt: {top_src_subckt} (v5_5g hardened analog/tx/sst/spice/*_5g.spice)",
        f".subckt {top_out_subckt} " + " ".join(top_ports),
    ]
    dev_idx = 0

    def expand(sub_name: str, port_map: dict[str, str], env: dict[str, float], prefix: str) -> None:
        nonlocal dev_idx
        sdef = subckts[sub_name]
        local_env = {k: slc._eval_expr(v, env) for k, v in sdef["defaults"].items()}
        local_env.update(env)

        for inst_name, conns, model, ov in sdef["insts"]:
            mapped_conns = [port_map.get(c, f"{prefix}_{c}") for c in conns]
            child_env = {k: slc._eval_expr(v, local_env) for k, v in ov.items()}
            if model.startswith("sky130_fd_pr__"):
                dev_idx += 1
                p_strs = []
                if "nfet" in model or "pfet" in model:
                    p_strs.append(f"w={slc._fmt_num(child_env['w'])}")
                    p_strs.append(f"l={slc._fmt_num(child_env['l'])}")
                elif "res_high_po_" in model:
                    p_strs.append(f"l={slc._fmt_num(child_env['l'])}")
                elif "cap_mim_" in model:
                    p_strs.append(f"w={slc._fmt_num(child_env['w'])}")
                    p_strs.append(f"l={slc._fmt_num(child_env['l'])}")
                else:
                    for k, v in sorted(child_env.items()):
                        p_strs.append(f"{k}={slc._fmt_num(v)}")
                lines.append(f"X{dev_idx} " + " ".join(mapped_conns) + f" {model} " + " ".join(p_strs))
            elif model in subckts:
                cdef = subckts[model]
                if len(mapped_conns) != len(cdef["ports"]):
                    raise ValueError(f"Port count mismatch calling {model}: {len(mapped_conns)} != {len(cdef['ports'])}")
                cmap = dict(zip(cdef["ports"], mapped_conns))
                expand(model, cmap, child_env, f"{prefix}_{inst_name}")
            else:
                raise KeyError(f"Unknown model {model} inside {sub_name}")

    init_env = {k: slc._eval_expr(v, {}) for k, v in top_def["defaults"].items()}
    if param_overrides:
        init_env.update(param_overrides)
    expand(top_src_subckt, {p: p for p in top_ports}, init_env, "t")
    lines.append(f".ends {top_out_subckt}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return top_ports


# ---------------------------------------------------------------------------
# 1. Hardened Break-Before-Make Unit Slice (`sst_slice_unit_5g`)
# ---------------------------------------------------------------------------

def build_sst_slice_unit_5g(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build tileable 8.80 x 25.17 um BBM N-over-N SST Unit Slice (`sst_slice_unit_5g`).

    Exact schematic devices (`tx_sst_driver_5g.spice`):
      - Xgpb/Xgnb: sst_nand2 wn=0.80 wp=2.20 nfn=1 nfp=1 (drawn as shared nf=2 N/P)
      - Xgp/Xgn:   sst_inv   wn=1.80 wp=3.00 nfn=2 nfp=2 (w_f_n=0.90, w_f_p=1.50)
      - Xpup/Xpun: nfet_01v8_lvt w=3.8 l=0.15 nf=2; Xpdp/Xpdn: w=2.6 l=0.15 nf=1
      - Xrp/Xrn:   res_high_po_2p85 l=3.75 (shared guard ring)
    """
    c = Cell()
    hx = sab.SLICE_HALF_X

    # Band 0: Matched high-poly 2.85 um resistors (identical to v4.5)
    res2 = cache.device(R_2P85, dict(l=3.75, nx=2, m=1, guard=1))
    r1_0 = res2.pins("R1_0")[0]
    r2_0 = res2.pins("R2_0")[0]
    r1_1 = res2.pins("R1_1")[0]
    r2_1 = res2.pins("R2_1")[0]
    res2.labels.clear()
    c.include(res2, dx=0.0, dy=0.0)

    c.rect("pwell", -hx, -4.785, +hx, 15.400)
    c.rect("metal4", -hx, grid(sab.SLICE_Y_PAD_P - 0.400), +hx, grid(sab.SLICE_Y_PAD_P + 0.400))
    c.rect("metal4", -hx, grid(sab.SLICE_Y_PAD_N - 0.400), +hx, grid(sab.SLICE_Y_PAD_N + 0.400))

    xp0, yp0 = grid(r2_0[0]), grid(r2_0[1])
    c.via1(xp0, yp0)
    c.wire("metal2", [(xp0, yp0), (xp0, sab.SLICE_Y_PAD_P)], 0.440)
    via2_clean(c, xp0, sab.SLICE_Y_PAD_P)
    via3_pad(c, xp0, sab.SLICE_Y_PAD_P)

    xp1, yp1 = grid(r2_1[0]), grid(r2_1[1])
    c.via1(xp1, yp1)
    c.wire("metal2", [(xp1, yp1), (xp1, sab.SLICE_Y_PAD_N)], 0.440)
    via2_clean(c, xp1, sab.SLICE_Y_PAD_N)
    via3_pad(c, xp1, sab.SLICE_Y_PAD_N)

    # Band 1: Power LVT NMOS switches + vss / vdrv horizontal rails (identical to v4.5)
    draw_tap_h(c, "psubdiff", -hx, +hx, sab.SLICE_Y_VSS_PWR, half_w=0.220)
    c.rect("metal1", -hx, grid(sab.SLICE_Y_VSS_PWR - 0.250), +hx, grid(sab.SLICE_Y_VSS_PWR + 0.250))
    c.rect("metal3", -hx, grid(sab.SLICE_Y_VSS_PWR - 0.500), +hx, grid(sab.SLICE_Y_VSS_PWR + 0.500))
    for tx in (-3.400, 0.000, +3.400):
        viali_pad(c, tx, sab.SLICE_Y_VSS_PWR)
        c.via1(tx, sab.SLICE_Y_VSS_PWR)
        via2_clean(c, tx, sab.SLICE_Y_VSS_PWR)
        c.rect("psubdiff", grid(tx - 0.180), 4.500, grid(tx + 0.180), sab.SLICE_Y_VSS_PWR)
        locali_v(c, tx, 4.500, sab.SLICE_Y_VSS_PWR)
        viali_pad(c, tx, 4.520)
        c.wire("metal1", [(tx, 4.520), (tx, sab.SLICE_Y_VSS_PWR)], 0.340)
    for tx in (-0.630, +0.630):
        viali_pad(c, tx, sab.SLICE_Y_VSS_PWR)
        c.via1(tx, sab.SLICE_Y_VSS_PWR)
        via2_clean(c, tx, sab.SLICE_Y_VSS_PWR)

    y_pwr = 7.750
    m_pu, inf_pu = cache.build_mos(N_LVT, 1.90, 0.15, 2, y_pwr, False)
    m_pd, inf_pd = cache.build_mos(N_LVT, 2.60, 0.15, 1, y_pwr, False)

    cx_pup, cx_pdp = -2.600, -0.850
    cx_pdn, cx_pun = +0.850, +2.600
    c.include(m_pu, dx=cx_pup)
    c.include(m_pd, dx=cx_pdp)
    c.include(m_pd, dx=cx_pdn)
    c.include(m_pu, dx=cx_pun)

    c.rect("metal4", -hx, grid(sab.SLICE_Y_VDRV - 0.600), +hx, grid(sab.SLICE_Y_VDRV + 0.600))
    for cx_u in (cx_pup, cx_pun):
        xs_vdrv = [grid(cx_u + x) for x in inf_pu["s_xs"]]
        for xv in xs_vdrv:
            for vy in (7.450, 8.150):
                viali_pad(c, xv, vy)
            c.wire("metal1", [(xv, 7.450), (xv, 8.150)], 0.280)
            c.via1(xv, sab.SLICE_Y_VDRV)
        c.wire("metal2", [(xs_vdrv[0], sab.SLICE_Y_VDRV), (xs_vdrv[-1], sab.SLICE_Y_VDRV)], 0.560)
        via2_clean(c, cx_u, sab.SLICE_Y_VDRV)
        via3_pad(c, cx_u, sab.SLICE_Y_VDRV)

    y_sw = 6.180
    for sgn, cx_u, cx_d, r1_pt in ((-1, cx_pup, cx_pdp, r1_0), (+1, cx_pun, cx_pdn, r1_1)):
        x_ud = grid(cx_u + inf_pu["d_xs"][0])
        x_dd = grid(cx_d + (inf_pd["s_xs"][0] if sgn < 0 else inf_pd["d_xs"][0]))
        x_ds = grid(cx_d + (inf_pd["d_xs"][0] if sgn < 0 else inf_pd["s_xs"][0]))

        locali_v(c, x_ud, y_sw, inf_pu["c_y1"] + 0.060)
        locali_v(c, x_dd, y_sw, inf_pd["c_y1"] + 0.060)
        viali_pad(c, x_ud, y_sw)
        viali_pad(c, x_dd, y_sw)
        viali_pad(c, x_ud, 6.950)
        viali_pad(c, x_dd, 6.950)
        c.wire("metal1", [(x_ud, y_sw), (x_ud, 6.950)], 0.260)
        c.wire("metal1", [(x_dd, y_sw), (x_dd, 6.950)], 0.260)
        c.wire("metal1", sorted([(x_ud, y_sw), (x_dd, y_sw)], key=lambda p: p[0]), 0.320)

        rx, ry = grid(r1_pt[0]), grid(r1_pt[1])
        c.via1(rx, y_sw)
        c.via1(rx, ry)
        c.wire("metal2", [(rx, ry), (rx, y_sw)], 0.500)

        locali_v(c, x_ds, sab.SLICE_Y_VSS_PWR, inf_pd["c_y1"] + 0.060)
        for vy in (6.950, 7.750, 8.550):
            viali_pad(c, x_ds, vy)
        c.wire("metal1", [(x_ds, sab.SLICE_Y_VSS_PWR), (x_ds, 8.550)], 0.280)

    y_gp, y_gn = 9.750, 10.350
    for gx in inf_pu["g_xs"]:
        c.rect("poly", grid(cx_pup + gx - 0.075), 8.700, grid(cx_pup + gx + 0.075), 9.450)
    c.rect("poly", grid(cx_pup + inf_pu["g_xs"][0] - 0.075), 9.300,
           grid(cx_pup + inf_pu["g_xs"][-1] + 0.075), 9.450)
    c.rect("poly", grid(cx_pup - 0.135), 9.300, grid(cx_pup + 0.135), y_gp)
    poly_cont_pad(c, cx_pup, y_gp)
    viali_pad(c, cx_pup, y_gp)
    c.via1(cx_pup, y_gp)

    c.rect("poly", grid(cx_pdn - 0.075), 9.050, grid(cx_pdn + 0.075), y_gp)
    poly_cont_pad(c, cx_pdn, y_gp)
    viali_pad(c, cx_pdn, y_gp)
    c.via1(cx_pdn, y_gp)
    c.wire("metal2", [(cx_pup, y_gp), (cx_pdn, y_gp)], 0.280)

    c.rect("poly", grid(cx_pdp - 0.075), 9.050, grid(cx_pdp + 0.075), y_gn)
    poly_cont_pad(c, cx_pdp, y_gn)
    viali_pad(c, cx_pdp, y_gn)
    c.via1(cx_pdp, y_gn)

    for gx in inf_pu["g_xs"]:
        c.rect("poly", grid(cx_pun + gx - 0.075), 8.700, grid(cx_pun + gx + 0.075), 9.450)
    c.rect("poly", grid(cx_pun + inf_pu["g_xs"][0] - 0.075), 9.300,
           grid(cx_pun + inf_pu["g_xs"][-1] + 0.075), 9.450)
    c.rect("poly", grid(cx_pun - 0.135), 9.300, grid(cx_pun + 0.135), y_gn)
    poly_cont_pad(c, cx_pun, y_gn)
    viali_pad(c, cx_pun, y_gn)
    c.via1(cx_pun, y_gn)
    c.wire("metal2", [(cx_pdp, y_gn), (cx_pun, y_gn)], 0.280)

    # Band 2: Hardened Break-Before-Make Local CMOS Drivers (Xgpb/Xgnb + Xgp/Xgn)
    draw_tap_h(c, "psubdiff", -hx, +hx, sab.SLICE_Y_VSS_DRV, half_w=0.175)
    c.rect("metal1", -hx, grid(sab.SLICE_Y_VSS_DRV - 0.220), +hx, grid(sab.SLICE_Y_VSS_DRV + 0.220))
    c.rect("metal3", -hx, grid(sab.SLICE_Y_VSS_DRV - 0.300), +hx, grid(sab.SLICE_Y_VSS_DRV + 0.300))
    for tx in (-3.400, 0.000, +3.400):
        viali_pad(c, tx, sab.SLICE_Y_VSS_DRV)
        c.via1(tx, sab.SLICE_Y_VSS_DRV)
        via2_clean(c, tx, sab.SLICE_Y_VSS_DRV)
    c.wire("metal3", [(0.000, sab.SLICE_Y_VSS_PWR), (0.000, sab.SLICE_Y_VSS_DRV)], 0.560)

    c.rect("nwell", -hx, 15.500, +hx, 19.450)
    draw_tap_h(c, "nsubdiff", grid(-hx + 0.200), grid(+hx - 0.200), sab.SLICE_Y_VDD_DRV, half_w=0.175)
    c.rect("metal1", -hx, grid(sab.SLICE_Y_VDD_DRV - 0.220), +hx, grid(sab.SLICE_Y_VDD_DRV + 0.220))
    c.rect("metal3", -hx, grid(sab.SLICE_Y_VDD_DRV - 0.360), +hx, grid(sab.SLICE_Y_VDD_DRV + 0.360))
    for tx in (-3.750, +3.750):
        viali_pad(c, tx, sab.SLICE_Y_VDD_DRV)
        c.via1(tx, sab.SLICE_Y_VDD_DRV)
        via2_clean(c, tx, sab.SLICE_Y_VDD_DRV)
    viali_pad(c, 0.000, sab.SLICE_Y_VDD_DRV)

    # Hardened v5_5g local driver FETs (v5.5: orthogonal Slow-N/+85C & Slow-P/-40C centering):
    #   NAND2: N nf=2 w_f=0.85 (series), P nf=2 w_f=2.20 (parallel: mid=vdd, outer=out)
    #   INV:   N nf=2 w_f=0.90 (total 1.80), P nf=2 w_f=1.65 (total 3.30)
    y_dn_top = 13.000
    y_dp_bot = 16.000
    mn_nd, in_nd = cache.build_mos(N_LVT, 0.85, 0.15, 2, grid(y_dn_top - 0.425), False)
    mp_nd, ip_nd = cache.build_mos(P_STD, 2.20, 0.15, 2, grid(y_dp_bot + 1.100), True)
    mn_iv, in_iv = cache.build_mos(N_LVT, 0.90, 0.15, 2, grid(y_dn_top - 0.450), False)
    mp_iv, ip_iv = cache.build_mos(P_STD, 1.65, 0.15, 2, grid(y_dp_bot + 0.825), True)

    cx_nd_l, cx_iv_l = -3.150, -1.050
    cx_iv_r, cx_nd_r = +1.050, +3.150
    for cx_nd in (cx_nd_l, cx_nd_r):
        c.include(mn_nd, dx=cx_nd)
        c.include(mp_nd, dx=cx_nd)
    for cx_iv in (cx_iv_l, cx_iv_r):
        c.include(mn_iv, dx=cx_iv)
        c.include(mp_iv, dx=cx_iv)

    w_din_m3 = 0.440
    c.rect("metal3", -hx, grid(sab.SLICE_Y_DIN_P - w_din_m3 / 2.0), +hx, grid(sab.SLICE_Y_DIN_P + w_din_m3 / 2.0))
    c.rect("metal3", -hx, grid(sab.SLICE_Y_DIN_N - w_din_m3 / 2.0), +hx, grid(sab.SLICE_Y_DIN_N + w_din_m3 / 2.0))

    y_g_en = 14.500
    y_g_out = 13.500
    y_n_out_m1 = 12.600
    y_nd_pjoin = 16.400  # Inside PMOS diff band (clear of din_n=15.55 & vdd=18.80, zero conflict w/ center vdd locali!)
    en_tap_xs = []

    for sgn, cx_nd, cx_iv, y_din, y_gate_pwr in (
        (-1, cx_nd_l, cx_iv_l, sab.SLICE_Y_DIN_P, y_gp),
        (+1, cx_nd_r, cx_iv_r, sab.SLICE_Y_DIN_N, y_gn),
    ):
        gx_en = grid(cx_nd + (in_nd["g_xs"][0] if sgn < 0 else in_nd["g_xs"][-1]))
        gx_din = grid(cx_nd + (in_nd["g_xs"][-1] if sgn < 0 else in_nd["g_xs"][0]))
        en_tap_xs.append(gx_en)

        # Dual near-edge poly contacts on gx_din bridged by low-R M1
        c.rect("poly", grid(gx_din - 0.075), y_dn_top, grid(gx_din + 0.075), grid(sab.SLICE_Y_DIN_P + 0.170))
        c.rect("poly", grid(gx_din - 0.075), grid(sab.SLICE_Y_DIN_N - 0.170), grid(gx_din + 0.075), y_dp_bot)
        poly_cont_pad(c, gx_din, sab.SLICE_Y_DIN_P)
        viali_pad(c, gx_din, sab.SLICE_Y_DIN_P)
        poly_cont_pad(c, gx_din, sab.SLICE_Y_DIN_N)
        viali_pad(c, gx_din, sab.SLICE_Y_DIN_N)
        c.wire("metal1", [(gx_din, sab.SLICE_Y_DIN_P), (gx_din, sab.SLICE_Y_DIN_N)], 0.220)
        c.via1(gx_din, y_din)
        via2_clean(c, gx_din, y_din)

        # Static `en` gate poly + contact at y_g_en = 14.500
        c.rect("poly", grid(gx_en - 0.075), y_dn_top, grid(gx_en + 0.075), y_dp_bot)
        poly_cont_pad(c, gx_en, y_g_en)
        viali_pad(c, gx_en, y_g_en)
        c.via1(gx_en, y_g_en)

        # NAND2 diffusions: N series (outer=vss, inner=out), P parallel (center=vdd, outer=out)
        x_n_vss = grid(cx_nd + (in_nd["s_xs"][0] if sgn < 0 else in_nd["s_xs"][-1]))
        x_n_out = grid(cx_nd + (in_nd["s_xs"][-1] if sgn < 0 else in_nd["s_xs"][0]))
        x_p_vdd = grid(cx_nd + ip_nd["d_xs"][0])
        x_p_out0 = grid(cx_nd + ip_nd["s_xs"][0])
        x_p_out1 = grid(cx_nd + ip_nd["s_xs"][-1])

        locali_v(c, x_n_vss, sab.SLICE_Y_VSS_DRV, in_nd["c_y1"] + 0.060)
        viali_pad(c, x_n_vss, 12.550)
        c.wire("metal1", [(x_n_vss, sab.SLICE_Y_VSS_DRV), (x_n_vss, 12.550)], 0.220)
        locali_v(c, x_p_vdd, ip_nd["c_y2"] - 0.060, sab.SLICE_Y_VDD_DRV)
        viali_pad(c, x_p_vdd, sab.SLICE_Y_VDD_DRV)
        viali_pad(c, x_p_vdd, 17.850)
        c.wire("metal1", [(x_p_vdd, 17.850), (x_p_vdd, sab.SLICE_Y_VDD_DRV)], 0.220)

        # Join NAND2 PMOS outer drains on M1 at y_nd_pjoin = 16.400 -> drop through x_nd_drop = +-2.220
        for xp_o in (x_p_out0, x_p_out1):
            viali_pad(c, xp_o, y_nd_pjoin)
        x_nd_drop = grid(sgn * 2.220)
        c.wire("metal1", sorted([(x_p_out0, y_nd_pjoin), (x_p_out1, y_nd_pjoin)], key=lambda p: p[0]), W_M1)
        c.wire("metal1", sorted([(x_p_out1 if sgn < 0 else x_p_out0, y_nd_pjoin), (x_nd_drop, y_nd_pjoin)], key=lambda p: p[0]), W_M1)
        viali_pad(c, x_n_out, y_n_out_m1)
        c.wire("metal1", sorted([(x_n_out, y_n_out_m1), (x_nd_drop, y_n_out_m1)], key=lambda p: p[0]), W_M1)
        c.wire("metal1", [(x_nd_drop, y_n_out_m1), (x_nd_drop, y_nd_pjoin)], W_M1)

        # INV (nf=2): join both poly fingers in channel at y_g_out = 13.500 and tap outward at gx_iv_tap = +-1.750
        iv_gxs = [grid(cx_iv + g) for g in in_iv["g_xs"]]
        gx_iv_tap = grid(sgn * 1.750)
        for gx_i in iv_gxs:
            c.rect("poly", grid(gx_i - 0.075), y_dn_top, grid(gx_i + 0.075), y_dp_bot)
        all_iv_gx = iv_gxs + [gx_iv_tap]
        c.rect("poly", grid(min(all_iv_gx) - 0.075), grid(y_g_out - 0.170),
               grid(max(all_iv_gx) + 0.075), grid(y_g_out + 0.170))
        poly_cont_pad(c, gx_iv_tap, y_g_out)
        viali_pad(c, gx_iv_tap, y_g_out)
        c.wire("metal1", sorted([(x_nd_drop, y_g_out), (gx_iv_tap, y_g_out)], key=lambda p: p[0]), W_M1)

        # INV nf=2 outer sources -> VSS / VDD (short locali to rail + M1 shunt on PMOS at 17.30..18.80)
        for sx_l in in_iv["s_xs"]:
            xs = grid(cx_iv + sx_l)
            locali_v(c, xs, sab.SLICE_Y_VSS_DRV, in_iv["c_y1"] + 0.060)
            viali_pad(c, xs, sab.SLICE_Y_VSS_DRV)
            locali_v(c, xs, ip_iv["c_y2"] - 0.060, sab.SLICE_Y_VDD_DRV)
            viali_pad(c, xs, 17.200)
            viali_pad(c, xs, sab.SLICE_Y_VDD_DRV)
            c.wire("metal1", [(xs, 17.200), (xs, sab.SLICE_Y_VDD_DRV)], 0.220)

        # INV nf=2 center drain (x = cx_iv = +-1.050): join N & P on locali -> viali + via1 at y=12.600 -> M2 drop!
        x_iv_d = grid(cx_iv + in_iv["d_xs"][0])
        locali_v(c, x_iv_d, in_iv["c_y2"] - 0.060, ip_iv["c_y1"] + 0.060)
        y_iv_tap = 12.600
        viali_pad(c, x_iv_d, y_iv_tap)
        c.via1(x_iv_d, y_iv_tap)
        x_m2_drop = grid(sgn * 1.650)
        c.wire("metal2", sorted([(x_iv_d, y_iv_tap), (x_m2_drop, y_iv_tap)], key=lambda p: p[0]), 0.280)
        c.wire("metal2", [(x_m2_drop, y_gate_pwr), (x_m2_drop, y_iv_tap)], 0.280)

    c.wire("metal2", [(en_tap_xs[0], y_g_en), (en_tap_xs[1], y_g_en)], 0.280)
    c.wire("metal2", [(0.000, y_g_en), (0.000, sab.SLICE_Y_EN_PIN)], 0.320)

    if add_ports:
        c.port("din_p", "metal3", -hx, sab.SLICE_Y_DIN_P)
        c.port("din_n", "metal3", -hx, sab.SLICE_Y_DIN_N)
        c.port("en",    "metal2", 0.000, sab.SLICE_Y_EN_PIN)
        c.port("pad_p", "metal4", +hx, sab.SLICE_Y_PAD_P)
        c.port("pad_n", "metal4", +hx, sab.SLICE_Y_PAD_N)
        c.port("vdrv",  "metal4", -hx, sab.SLICE_Y_VDRV)
        c.port("vdd",   "metal3", -hx, sab.SLICE_Y_VDD_DRV)
        c.port("vss",   "metal3", -hx, sab.SLICE_Y_VSS_PWR)

    return c, {
        "pitch_x": sab.SLICE_PITCH_X,
        "half_x": hx,
        "y_pad_p": sab.SLICE_Y_PAD_P,
        "y_pad_n": sab.SLICE_Y_PAD_N,
        "y_vss_pwr": sab.SLICE_Y_VSS_PWR,
        "y_vdrv": sab.SLICE_Y_VDRV,
        "y_vss_drv": sab.SLICE_Y_VSS_DRV,
        "y_din_p": sab.SLICE_Y_DIN_P,
        "y_din_n": sab.SLICE_Y_DIN_N,
        "y_vdd_drv": sab.SLICE_Y_VDD_DRV,
        "y_en_pin": sab.SLICE_Y_EN_PIN,
    }


# ---------------------------------------------------------------------------
# 2. Hardened Zero-Stacked-PMOS CMOS Rows (`Xpg_5g`, `Xmux_m_5g`, `Xmux_f_5g`)
# ---------------------------------------------------------------------------

def _add_row_transformed(
    dst: Cell,
    row_cell: Cell,
    pins_local: dict[str, list[tuple[float, float, str]]],
    dx: float,
    y_vss_world: float,
    mirror_y: bool = False,
    mirror_x: bool = False,
) -> dict[str, list[tuple[float, float, str]]]:
    dx, dy = grid(dx), grid(y_vss_world)
    dst.include(row_cell, dx=dx, dy=dy, mirror_x=mirror_x, mirror_y=mirror_y)
    out: dict[str, list[tuple[float, float, str]]] = {}
    for net, plist in pins_local.items():
        out[net] = [
            (grid((-px if mirror_x else px) + dx), grid((-py if mirror_y else py) + dy), lyr)
            for px, py, lyr in plist
        ]
    return out


def _build_pulsegen_5g_row(cache: PdkCache) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build `sst_pulsegen_4ph_5g` (INV -> INV -> NAND2 -> INV, zero stacked PMOS!) on `ROW_DRV`."""
    row = scc.ROW_DRV
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}
    b_pins: dict[str, list[tuple[float, float]]] = {}
    c_pins: dict[str, list[tuple[float, float]]] = {}

    def add_pin(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    y2 = row.y_tracks[2]
    x = 0.0

    # Stage 1: Xi0..Xi27 (3.0/8.4) + Xcc1a/b (0.6/1.6)
    for ph, bnet in (("phi0", "b0"), ("phi90", "b90"), ("phi180", "b180"), ("phi270", "b270")):
        u, x = scc.place_inv(c, cache, row, x, 3.0, 8.4, 1, 3, gap_l=0.720, trk_g=2)
        add_pin(ph, u["a"])
        b_pins.setdefault(bnet, []).append(u["y"])
    for a, b in (("b0", "b180"), ("b90", "b270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.6, 1.6, gap_l=0.720)
        b_pins.setdefault(a, []).append(u["ap"])
        b_pins.setdefault(b, []).append(u["an"])

    # Stage 2: Xj0..Xj27 (5.0/14.0) + Xcc2a/b (0.8/2.2) (gap_l=0.96 gives >=1.0 um M4 pitch between Xj.y and next Xj.a!)
    for bnet, cnet in (("b0", "c0"), ("b90", "c90"), ("b180", "c180"), ("b270", "c270")):
        u, x = scc.place_inv(c, cache, row, x, 5.0, 14.0, 2, 5, gap_l=0.960, trk_g=2)
        b_pins.setdefault(bnet, []).append(u["a"])
        c_pins.setdefault(cnet, []).append(u["y"])
    for a, b in (("c0", "c180"), ("c90", "c270")):
        u, x = scc.place_cc_align(c, cache, row, x, 0.8, 2.2, gap_l=0.960)
        c_pins.setdefault(a, []).append(u["ap"])
        c_pins.setdefault(b, []).append(u["an"])

    # Stage 3a + 3b: Paired Xpb (NAND2 5.6/10.4) -> direct M1 -> Xp (INV 6.6/15.9)
    # Ordered [p2, p3, p0, p1] so c0..c270 wire lengths stay balanced!
    for a_lead, b_trail, pnet in (
        ("c180", "c90",  "p2"),
        ("c270", "c180", "p3"),
        ("c0",   "c270", "p0"),
        ("c90",  "c0",   "p1"),
    ):
        upb, x = scc.place_nand2(c, cache, row, x, 5.6, 10.4, 2, 4, gap_l=0.760, trk_a=0, trk_b=4)
        up,  x = scc.place_inv(c, cache, row, x, 6.6, 15.9, 3, 6, gap_l=0.680, trk_g=2)
        c_pins.setdefault(a_lead, []).append(upb["a"])
        c_pins.setdefault(b_trail, []).append(upb["b"])
        # Direct 0-via M1 link pb_k -> Xp.a at y2 = 5.00
        c.wire("metal1", [(upb["y_col_x"], y2), up["a"]], W_M1)
        add_pin(pnet, up["y"])

    # Export b0..b270 and c0..c270 to ManhattanRouter (zero diff-band M1/M2 conflicts!)
    for bnet, pts in b_pins.items():
        for pt in pts:
            add_pin(bnet, pt)
    for cnet, pts in c_pins.items():
        for pt in pts:
            add_pin(cnet, pt)

    return c, nets, x


def _build_mux4_5g_row(
    cache: PdkCache,
    is_main: bool,
    d_names: tuple[str, str, str, str],
    db_names: tuple[str, str, str, str],
    en_net: str | None,
    out_p_net: str,
    out_n_net: str,
    slot_order: tuple[int, int, int, int] = (3, 2, 1, 0),
) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build 6-stage all-NAND2+INV `sst_mux4_predrv_5g` (or `_en_5g`) on a single `ROW_DRV` row.

    Zero stacked PMOS anywhere! 100% planar zero-crossing M1/M2 internal routing:
      - Stage 1: 4x NAND2(p_k, in_k) -> g_k
      - Stage 2: 4x swapped NAND2(g0/g2, g1/g3) -> e, o  (nested M2 arches at y=7.30/7.85 & 2.75/2.15)
      - Stage 3: 2x INV(e -> e_b, o -> o_b)              (e at y=4.46, o at y=5.54)
      - Stage 4: 2x swapped NAND2(e_b, o_b) -> pre       (e_b at y=7.30, o_b at y=2.75)
      - Stage 5: INV(pre -> mid) [Main] or NAND2(pre, en -> mid) [Post-FFE] (pre at y=5.00)
      - Stage 6: INV(mid -> out)                         (direct 0-via M1 at y=5.00)
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
    y_en_trk = 1.050

    gap = 0.600 if is_main else 0.580
    if is_main:
        s1 = (2.4, 5.4, 1, 2)
        s2 = (1.8, 3.6, 1, 2)
        s3 = (2.4, 7.2, 1, 3)
        s4 = (2.8, 5.2, 1, 2)
        s5 = (6.0, 13.5, 2, 5)
        s6 = (12.5, 39.0, 5, 13)
    else:
        s1 = (1.8, 4.2, 1, 2)
        s2 = (1.4, 2.8, 1, 1)
        s3 = (1.8, 5.4, 1, 2)
        s4 = (2.1, 3.9, 1, 2)
        s5 = (8.4, 9.6, 3, 4)
        s6 = (5.6, 19.6, 2, 7)

    x = 0.0
    en_xs: list[float] = []

    # 6-stage non-inverting polarity: positive leg takes d_names -> out_p; negative leg takes db_names -> out_n!
    for in_names, onet in ((d_names, out_p_net), (db_names, out_n_net)):
        # Stage 1: 4x NAND2(p_k, in_k) -> g_k
        g_x: dict[int, float] = {}
        for k in slot_order:
            ug, x = scc.place_nand2(c, cache, row, x, *s1, gap_l=gap, trk_a=0, trk_b=4)
            add_pin(f"p{k}", ug["a"])
            add_pin(in_names[k], ug["b"])
            g_x[k] = ug["y_col_x"]

        # Stage 2: 4x swapped-input parallel NAND2 -> e, o
        uea, x = scc.place_nand2(c, cache, row, x, *s2, gap_l=gap, trk_a=0, trk_b=4)
        ueb, x = scc.place_nand2(c, cache, row, x, *s2, gap_l=gap, trk_a=0, trk_b=4)
        uoa, x = scc.place_nand2(c, cache, row, x, *s2, gap_l=gap, trk_a=0, trk_b=4)
        uob, x = scc.place_nand2(c, cache, row, x, *s2, gap_l=gap, trk_a=0, trk_b=4)

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

        # Stage 3: 2x INV (e -> e_b, o -> o_b)
        ue_inv, x = scc.place_inv(c, cache, row, x, *s3, gap_l=gap, trk_g=1)
        uo_inv, x = scc.place_inv(c, cache, row, x, *s3, gap_l=gap, trk_g=3)

        e_xs = [uea["y_col_x"], ueb["y_col_x"], ue_inv["a"][0]]
        for px in e_xs:
            c.via1(px, y_e_trk)
        c.wire("metal2", [(min(e_xs), y_e_trk), (max(e_xs), y_e_trk)], 0.220)

        o_xs = [uoa["y_col_x"], uob["y_col_x"], uo_inv["a"][0]]
        for px in o_xs:
            c.via1(px, y_o_trk)
        c.wire("metal2", [(min(o_xs), y_o_trk), (max(o_xs), y_o_trk)], 0.220)

        # Stage 4: 2x swapped-input parallel NAND2(e_b, o_b) -> pre (ZERO stacked PMOS!)
        um1a, x = scc.place_nand2(c, cache, row, x, *s4, gap_l=gap, trk_a=0, trk_b=4)
        um1b, x = scc.place_nand2(c, cache, row, x, *s4, gap_l=gap, trk_a=0, trk_b=4)

        # Route e_b (from y4 UP to PMOS M2 y=7.30, clearing o_xs at y=5.54!) and o_b (from y0 DOWN to NMOS M2 y=2.75!)
        for sx, y_src, dst_xs, y_dst, y_bus in (
            (ue_inv["y_col_x"], y4, (um1a["a"][0], um1b["b"][0]), y4, 7.300),
            (uo_inv["y_col_x"], y0, (um1a["b"][0], um1b["a"][0]), y0, 2.750),
        ):
            c.via1(sx, y_src)
            c.wire("metal2", [(sx, y_src), (sx, y_bus)], 0.240)
            for dx in dst_xs:
                c.via1(dx, y_dst)
                c.wire("metal2", [(dx, y_dst), (dx, y_bus)], 0.240)
            all_x = [sx, *dst_xs]
            c.wire("metal2", [(min(all_x), y_bus), (max(all_x), y_bus)], 0.240)

        # Stage 5: INV (Main) or NAND2(pre, en) (Post-FFE)
        if en_net is None:
            umb, x = scc.place_inv(c, cache, row, x, *s5, gap_l=gap, trk_g=2)
        else:
            umb, x = scc.place_nand2(c, cache, row, x, *s5, gap_l=gap, trk_a=2, trk_b=0)
            en_xs.append(umb["b"][0])

        p_xs = [um1a["y_col_x"], um1b["y_col_x"], umb["a"][0]]
        for px in p_xs:
            c.via1(px, y_pre_trk)
        c.wire("metal2", [(min(p_xs), y_pre_trk), (max(p_xs), y_pre_trk)], 0.220)

        # Stage 6: Pure INV output pre-driver for BOTH Main and Post-FFE
        u2, x = scc.place_inv(c, cache, row, x, *s6, gap_l=gap, trk_g=2)
        c.wire("metal1", [(umb["y_col_x"], y2), u2["a"]], W_M1)
        add_pin(onet, u2["y"])

    if en_net is not None:
        for px in en_xs:
            c.via1(px, y0)
            c.wire("metal2", [(px, y_en_trk), (px, y0)], 0.240)
        c.wire("metal2", [(min(en_xs), y_en_trk), (max(en_xs), y_en_trk)], 0.240)
        add_pin(en_net, (en_xs[-1], y_en_trk), "metal2")

    return c, nets, x


# ---------------------------------------------------------------------------
# 3. Complete Hardened 5.0 Gb/s SST Driver Macro (`serdes_tx_sst_driver_5g`)
# ---------------------------------------------------------------------------

def build_sst_driver_5g(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Build complete `serdes_tx_sst_driver_pdk` for v5_5g (3 clean CMOS rows + 28 slices + v4.5 LDO)."""
    c = Cell()
    row = scc.ROW_DRV

    # 1. West Block: Reused v4.5 compact_a1 V_drv LDO (`Xldo`, x in [-25.2..86.5], y in [0.2..90.2])
    ldo_cell, ldo_meta = sab.build_sst_vdrv_ldo(cache, add_ports=False, compact_a1=True)
    c.include(ldo_cell, dx=0.0, dy=0.0)

    # 2. East-South Block: 3 Dedicated High-Speed CMOS Rows (`ROW_DRV`, H=10.20 um)
    #    * Row 0 (y=3.0..13.2):  Xpg_5g   (West-aligned above phi0..phi270 South pins)
    #    * Row 1 (y=23.4..33.6): Xmux_f_5g (East-aligned; Ch0-1 widened +3.6 um for 1.80 um double-spaced p0..p3!)
    #    * Row 2 (y=40.2..50.4): Xmux_m_5g (West-aligned mirrored -> mp/mn exit straight West!)
    x_cmos0 = 94.400
    x_cmos_l = grid(x_cmos0 - 0.800)  # 93.600
    y_r0_vss, y_r0_vdd = 3.000, grid(3.000 + row.height)    # 3.00..13.20
    y_r1_vss, y_r1_vdd = 23.400, grid(23.400 + row.height)  # 23.40..33.60
    y_r2_vss, y_r2_vdd = 40.200, grid(40.200 + row.height)  # 40.20..50.40

    pg_cell, pg_nets, pg_w = _build_pulsegen_5g_row(cache)
    mf_cell, mf_nets, mf_w = _build_mux4_5g_row(
        cache, is_main=False,
        d_names=("db3", "db0", "db1", "db2"), db_names=("d3", "d0", "d1", "d2"),
        en_net="ffe_en", out_p_net="fp", out_n_net="fn", slot_order=(3, 2, 1, 0),
    )
    mm_cell, mm_nets, mm_w = _build_mux4_5g_row(
        cache, is_main=True,
        d_names=("d0", "d1", "d2", "d3"), db_names=("db0", "db1", "db2", "db3"),
        en_net=None, out_p_net="mp", out_n_net="mn", slot_order=(3, 2, 1, 0),
    )

    x_r0_r = grid(max(x_cmos0 + pg_w + 1.500, 185.000))
    x_mf_l = grid(max(x_cmos0 + 1.000, 215.500 - mf_w))
    x_r1_r = grid(max(x_mf_l + mf_w + 1.500, 217.000))
    x_mm_r = grid(x_cmos0 + mm_w + 1.500)
    x_cmos_r = grid(max(x_r0_r, x_r1_r, x_mm_r + 1.500, 217.500))

    all_nets: dict[str, list[tuple[float, float, str]]] = {}

    def merge_pins(pmap: dict[str, list[tuple[float, float, str]]]) -> None:
        for net, pts in pmap.items():
            all_nets.setdefault(net, []).extend(pts)

    # Row 0: Xpg_5g
    scc.finish_cmos_row(pg_cell, row, grid(x_cmos_l - x_cmos0), grid(x_cmos_r - x_cmos0), tap_pitch=1.6)
    merge_pins(_add_row_transformed(c, pg_cell, pg_nets, x_cmos0, y_r0_vss, mirror_y=False, mirror_x=False))

    # Row 1: Xmux_f_5g (placed East so fp/fn sit directly near x=216!)
    r1_cell = Cell()
    r1_mf_pins = _add_row_transformed(r1_cell, mf_cell, mf_nets, grid(x_mf_l - x_cmos0), 0.0, mirror_y=False, mirror_x=False)
    scc.finish_cmos_row(r1_cell, row, grid(x_cmos_l - x_cmos0), grid(x_cmos_r - x_cmos0), tap_pitch=1.6)
    merge_pins(_add_row_transformed(c, r1_cell, r1_mf_pins, x_cmos0, y_r1_vss, mirror_y=False, mirror_x=False))

    # Row 2: Xmux_m_5g (mirrored West so mp/mn sit directly at x~95 near mp/mn slice trunks!)
    r2_cell = Cell()
    r2_mm_pins = _add_row_transformed(r2_cell, mm_cell, mm_nets, grid(x_mm_r - x_cmos0), 0.0, mirror_y=False, mirror_x=True)
    scc.finish_cmos_row(r2_cell, row, grid(x_cmos_l - x_cmos0), grid(x_cmos_r - x_cmos0), tap_pitch=1.6)
    merge_pins(_add_row_transformed(c, r2_cell, r2_mm_pins, x_cmos0, y_r2_vss, mirror_y=False, mirror_x=False))

    # Low-R M2 over-straps directly atop ALL 6 CMOS M1 power rails
    x_pwr_l = 93.100
    x_pwr_r = grid(max(x_cmos_r + 0.800, 218.500))
    for y_rail, is_vss in (
        (y_r0_vss, True), (y_r0_vdd, False),
        (y_r1_vss, True), (y_r1_vdd, False),
        (y_r2_vss, True), (y_r2_vdd, False),
    ):
        x_l_start = x_pwr_l if is_vss else x_cmos_l
        c.wire("metal1", [(x_l_start, y_rail), (x_cmos_r, y_rail)], 0.540)
        c.wire("metal2", [(x_l_start, y_rail), (x_cmos_r, y_rail)], 0.960)
        v1_pitch = 1.6 if is_vss else 2.4
        n_v1 = max(2, int((x_cmos_r - x_cmos_l) // v1_pitch) + 1)
        for i in range(n_v1 + 1):
            vx = grid(x_cmos_l + 0.400 + (x_cmos_r - x_cmos_l - 0.800) * i / n_v1)
            c.via1(vx, y_rail)
    for y_vss_r in (y_r0_vss, y_r1_vss, y_r2_vss):
        c.via1(x_pwr_l, y_vss_r)
        via2_clean(c, x_pwr_l, y_vss_r)

    c.wire("metal3", [(x_pwr_l, y_r0_vss), (x_pwr_l, y_r2_vss)], 1.000)
    c.wire("metal2", [(ldo_meta["vss"][0], ldo_meta["vss"][1]), (x_pwr_l, ldo_meta["vss"][1]), (x_pwr_l, y_r0_vss)], 1.000)

    # 3. East-North Block: 28-Slice Face-to-Face Mirrored Array (2 x 14, BBM v5_5g slices!)
    slice_cell, smeta = build_sst_slice_unit_5g(cache, add_ports=False)
    pitch = smeta["pitch_x"]     # 8.800
    hx = smeta["half_x"]         # 4.400
    gap_mf = 0.800

    x_arr_l = 96.000
    # Shift slice array +19.00 um north (v5.1: +3.60 um extra Ch0-1 for 1.80 um double-spaced p0..p3!)
    y_seam = 83.600
    y_row_t = grid(y_seam + 5.600)   # 89.200
    y_row_b = grid(y_seam - 5.600)   # 78.000 (bot en = 58.35, y_en_b_bus = 57.20, 6.80 um above Row 2 VDD 50.40!)

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

    c.rect("pwell", x_arr_l, grid(y_row_b - 15.400), x_arr_r, grid(y_row_t + 15.400))
    for y_orig, mir, split_cxs in (
        (y_row_t, False, (top_cxs[11], top_cxs[12])),
        (y_row_b, True,  (bot_cxs[10], bot_cxs[11])),
    ):
        xb1, xb2 = grid(split_cxs[0] + hx - 0.10), grid(split_cxs[1] - hx + 0.10)
        def ym(yl: float) -> float:
            return grid(y_orig + (-yl if mir else yl))
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

    # 4. Symmetric Pad_p / Pad_n East Trunks + Low-R M5 Power Grid
    y_padp_t = grid(y_row_t + smeta["y_pad_p"])   # 83.000
    y_padn_t = grid(y_row_t + smeta["y_pad_n"])   # 80.640
    y_padn_b = grid(y_row_b - smeta["y_pad_n"])   # 79.360
    y_padp_b = grid(y_row_b - smeta["y_pad_p"])   # 77.000

    x_e_base = grid(max(x_arr_r, x_pwr_r))
    x_padn_j = grid(x_e_base + 1.200)
    x_vdd_e  = grid(x_e_base + 2.800)
    x_padp_j = grid(x_e_base + 5.200)
    x_fn_v   = grid(x_e_base + 7.200)
    x_fp_v   = grid(x_e_base + 8.400)
    x_pad_out = grid(x_e_base + 11.000)

    c.wire("metal4", [(x_arr_r, y_padn_t), (x_padn_j, y_padn_t), (x_padn_j, y_padn_b), (x_arr_r, y_padn_b)], 0.800)
    c.wire("metal4", [(x_padn_j, y_seam), (x_pad_out, y_seam)], 1.000)

    c.wire("metal4", [(x_arr_r, y_padp_t), (x_padp_j, y_padp_t)], 0.800)
    c.wire("metal4", [(x_arr_r, y_padp_b), (x_padp_j, y_padp_b)], 0.800)
    via4_array(c, x_padp_j, y_padp_t, nx=1, ny=1)
    via4_array(c, x_padp_j, y_padp_b, nx=1, ny=1)
    c.wire("metal5", [(x_padp_j, y_padp_b), (x_padp_j, y_padp_t)], 1.800)
    c.wire("metal4", [(x_padp_j, y_padp_t), (x_pad_out, y_padp_t)], 1.000)

    # Heavy VDRV feed from Xldo.vdrv (74.75) -> vertical M4+M5 spine x=91.0 -> y_vdrv_b (66.25) & y_vdrv_t (93.75)
    y_vdrv_t = grid(y_row_t + smeta["y_vdrv"])    # 93.750
    y_vdrv_b = grid(y_row_b - smeta["y_vdrv"])    # 66.250
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

    # Heavy VDD distribution (M3+M4+M5)
    y_vdd_t = grid(y_row_t + smeta["y_vdd_drv"])  # 104.400
    y_vdd_b = grid(y_row_b - smeta["y_vdd_drv"])  # 55.600
    x_vdd_sp = 86.800                             # 1.80 um M5 gap to x_vdrv_sp=91.000 (above y_vss_m5_w=70.6!)
    x_vdd_m5_e = grid(x_pad_out - 1.600)
    c.wire("metal4", [ldo_meta["vdd"], (x_vdd_sp, ldo_meta["vdd"][1]), (x_vdd_sp, y_vdd_t)], 1.600)
    via3_array(c, x_vdd_sp, y_vdd_t, nx=2, ny=2)
    c.wire("metal3", [(x_vdd_sp, y_vdd_t), (x_arr_l, y_vdd_t)], 1.200)
    c.rect("metal5", 85.000, grid(ldo_meta["vdd"][1] - 1.100), grid(x_vdd_sp + 1.200), grid(y_vdd_t + 1.200))
    via4_array(c, x_vdd_sp, y_vdd_t, nx=1, ny=1)
    c.wire("metal5", [(x_vdd_sp, y_vdd_t), (x_vdd_m5_e, y_vdd_t)], 2.400)
    for sidx in (0, 4, 8, 11, 13):
        cx = top_cxs[sidx]
        via3_array(c, cx, y_vdd_t, nx=2, ny=2)
        via4_array(c, cx, y_vdd_t, nx=1, ny=1)
    c.wire("metal5", [(x_vdd_m5_e, -0.500), (x_vdd_m5_e, y_vdd_t)], 2.400)

    x_vdd_cmos_w = 91.400
    x_vdd_b_m5_r = 215.800
    c.wire("metal5", [(x_vdd_cmos_w, y_vdd_b), (x_vdd_b_m5_r, y_vdd_b)], 2.400)
    for sidx in (0, 4, 8, 11, 13):
        cx = bot_cxs[sidx]
        via3_array(c, cx, y_vdd_b, nx=2, ny=2)
        via4_array(c, cx, y_vdd_b, nx=1, ny=1)
    c.wire("metal3", [(x_arr_r, y_vdd_t), (x_vdd_e, y_vdd_t), (x_vdd_e, y_vdd_b)], 1.200)
    c.wire("metal3", [(x_arr_r, y_vdd_b), (x_vdd_e, y_vdd_b)], 1.200)
    via3_array(c, x_vdd_e, y_vdd_b, nx=2, ny=2)
    c.wire("metal4", [(x_vdd_e, y_vdd_b), (x_vdd_m5_e, y_vdd_b)], 1.600)
    via4_array(c, x_vdd_m5_e, y_vdd_b, nx=1, ny=1)
    for vx_off in (-0.300, +0.300):
        via2_clean(c, grid(x_vdd_e + vx_off), y_vdd_b)
    c.wire("metal2", [(x_vdd_e, y_r0_vdd), (x_vdd_e, y_vdd_b)], 1.400)
    for y_rv in (y_r0_vdd, y_r1_vdd, y_r2_vdd):
        c.wire("metal2", [(x_cmos_r, y_rv), (x_vdd_e, y_rv)], 1.000)

    # West-CMOS VDD M5 spine (x=91.4, y=13.2..55.6) + M5 over-straps over all 3 CMOS VDD rails!
    c.wire("metal5", [(x_vdd_cmos_w, y_r0_vdd), (x_vdd_cmos_w, y_vdd_b)], 2.200)
    cmos_vdd_pillars: list[tuple[float, float]] = []
    for y_rv, xs_st in (
        (y_r0_vdd, (176.0, 198.6)),
        (y_r1_vdd, (113.8, 158.9, 198.6)),
        (y_r2_vdd, (113.8, 158.9, 198.6)),
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

    # Heavy VSS distribution (M3+M4+M5)
    y_vss_pt = grid(y_row_t + smeta["y_vss_pwr"])  # 91.000
    y_vss_dt = grid(y_row_t + smeta["y_vss_drv"])  # 97.000
    y_vss_pb = grid(y_row_b - smeta["y_vss_pwr"])  # 69.000
    y_vss_db = grid(y_row_b - smeta["y_vss_drv"])  # 63.000
    y_vss_m5_bot = ldo_meta["y_vss_m5"]            # 1.500
    y_vss_m5_t = grid(y_vss_pt - 1.400)            # 89.600
    y_vss_m5_b = grid(y_vss_pb + 1.400)            # 70.400
    x_vss_sp = 88.200
    x_vss_m5_w = 86.800
    x_vss_m5_e = 220.600

    c.wire("metal3", [(x_vss_sp, y_vss_m5_bot), (x_vss_sp, y_vss_dt)], 2.000)
    c.wire("metal3", [(x_vss_sp, y_r0_vss), (x_pwr_l, y_r0_vss)], 1.200)
    for yv, wv in ((y_vss_db, 1.200), (y_vss_pb, 1.300), (y_vss_pt, 1.300), (y_vss_dt, 1.200)):
        c.wire("metal3", [(x_vss_sp, yv), (x_arr_l, yv)], wv)

    c.rect("metal5", grid(ldo_meta["x_east_edge"] - 0.800), grid(y_vss_m5_bot - 1.200), grid(x_vss_m5_e + 1.800), grid(y_r0_vss + 1.200))
    # Stop West M5 VSS spine at y=68.0 (strictly below ldo_meta.vdrv M5 at y=74.75 -> >5 um clear!)
    c.wire("metal5", [(x_vss_m5_w, y_vss_m5_bot), (x_vss_m5_w, 68.000)], 2.400)
    c.wire("metal5", [(x_vss_m5_e, y_vss_m5_bot), (x_vss_m5_e, y_vss_m5_t)], 3.600)
    for y_rv in (y_r1_vss, y_r2_vss):
        c.wire("metal5", [(95.600, y_rv), (x_vss_m5_e, y_rv)], 2.200)

    cmos_vss_pillars: list[tuple[float, float]] = []
    r0_vss_pillars = (126.0, 134.0, 146.0, 158.9, 170.0, 185.0, 198.6, 209.0, 215.5)
    r12_vss_pillars = (100.0, 113.8, 158.9, 185.0, 198.6, 214.0)
    c.wire("metal3", [(r0_vss_pillars[0], y_r0_vss), (x_vss_m5_e, y_r0_vss)], 0.960)
    c.wire("metal3", [(95.600, y_r1_vss), (x_vss_m5_e, y_r1_vss)], 0.760)
    c.wire("metal3", [(95.600, y_r2_vss), (x_vss_m5_e, y_r2_vss)], 0.760)
    for y_rv_v2, x_start_v2 in ((y_r0_vss, r0_vss_pillars[0]), (y_r1_vss, 95.600), (y_r2_vss, 95.600)):
        n_v2 = int((x_vss_m5_e - x_start_v2) // 0.80)
        for iv2 in range(n_v2 + 1):
            via2_clean(c, grid(x_start_v2 + iv2 * 0.800), y_rv_v2)
    for y_rv, xs_st in ((y_r0_vss, r0_vss_pillars), (y_r1_vss, r12_vss_pillars), (y_r2_vss, r12_vss_pillars)):
        for xs in xs_st:
            is_open_m4 = (y_rv == y_r0_vss and (xs <= 125.0 or xs >= 177.0))
            via4_array(c, xs, y_rv, nx=2 if is_open_m4 else 1, ny=1)
            via3_array(c, xs, y_rv, nx=3 if (is_open_m4 or y_rv != y_r0_vss) else 2, ny=2 if y_rv == y_r0_vss else 1)
            cmos_vss_pillars.append((xs, y_rv))

    # Stitch West M5 VSS spine to West M3 VSS spine (stop at y_vss_db=66.6, >5 um clear of vdrv at 74.75!)
    for y_st in (y_vss_m5_bot, y_r1_vss, y_r2_vss, y_vss_db):
        via4_array(c, x_vss_m5_w, y_st, nx=1, ny=2 if y_st == y_vss_db else 1)
        c.wire("metal4", [(x_vss_m5_w, y_st), (x_vss_sp, y_st)], 2.200 if y_st == y_vss_db else 1.600)
        via3_array(c, x_vss_sp, y_st, nx=2, ny=3 if y_st == y_vss_db else 2)

    for y_rv in (y_r0_vss, y_r1_vss, y_r2_vss):
        c.wire("metal2", [(x_cmos_r, y_rv), (x_vss_m5_e, y_rv)], 0.960)
        for dxv in (-0.420, 0.000, +0.420):
            via2_clean(c, grid(x_vss_m5_e + dxv), y_rv)
        via3_array(c, x_vss_m5_e, y_rv, nx=2, ny=2)
        via4_array(c, x_vss_m5_e, y_rv, nx=2, ny=1)

    for y_m5_s, y_m3_s, row_cxs in ((y_vss_m5_t, y_vss_pt, top_cxs), (y_vss_m5_b, y_vss_pb, bot_cxs)):
        c.wire("metal5", [(row_cxs[0], y_m5_s), (x_vss_m5_e, y_m5_s)], 2.400)
        for cx in row_cxs:
            via4_array(c, cx, y_m5_s, nx=2, ny=1)
            c.wire("metal4", [(cx, min(y_m5_s, y_m3_s)), (cx, max(y_m5_s, y_m3_s))], 1.600)
            via3_array(c, cx, y_m3_s, nx=2, ny=2)

    # 5. Connect Bank Enables (m0..m4, f0..f2) & mp/mn/fp/fn Data Buses
    y_en_t = grid(y_row_t + smeta["y_en_pin"])       # 105.250
    y_en_t_bus = grid(y_en_t + 1.150)                # 106.400
    y_north_port = grid(y_en_t_bus + 1.800)          # 108.200
    top_banks = [("m3", top_cxs[0:8]), ("m2", top_cxs[8:12]), ("f2", top_cxs[12:14])]
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

    y_en_b = grid(y_row_b - smeta["y_en_pin"])       # 54.750
    y_en_b_bus = grid(y_en_b - 1.150)                # 53.600
    bot_banks = [
        ("m4", bot_cxs[0:8]), ("m1", bot_cxs[8:10]), ("m0", bot_cxs[10:11]),
        ("f1", bot_cxs[11:13]), ("f0", bot_cxs[13:14]),
    ]
    bot_en_pins: dict[str, tuple[float, float]] = {}
    for bnm, cxs in bot_banks:
        for cx in cxs:
            c.wire("metal2", [(cx, y_en_b_bus), (cx, y_en_b)], 0.320)
            via2_clean(c, cx, y_en_b_bus)
        if len(cxs) > 1:
            c.wire("metal3", [(cxs[0], y_en_b_bus), (cxs[-1], y_en_b_bus)], 0.400)
        bot_en_pins[bnm] = (cxs[-1], y_en_b_bus)

    y_dinp_b = grid(y_row_b - smeta["y_din_p"])      # 60.950
    y_dinn_b = grid(y_row_b - smeta["y_din_n"])      # 58.850
    y_dinp_t = grid(y_row_t + smeta["y_din_p"])      # 99.050
    y_dinn_t = grid(y_row_t + smeta["y_din_n"])      # 101.150

    x_mp_v, x_mn_v = 93.400, 94.700
    for xv, yb, yt, nm in ((x_mp_v, y_dinp_b, y_dinp_t, "mp"), (x_mn_v, y_dinn_b, y_dinn_t, "mn")):
        c.wire("metal3", [(xv, yb), (x_arr_l, yb)], 0.360)
        c.wire("metal3", [(xv, yt), (x_arr_l, yt)], 0.360)
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

    for xv, yb, yt, nm in ((x_fp_v, y_dinp_b, y_dinp_t, "fp"), (x_fn_v, y_dinn_b, y_dinn_t, "fn")):
        for y_row_din in (yb, yt):
            via3_pad(c, grid(x_arr_r + 0.500), y_row_din)
            c.wire("metal3", [(x_arr_r, y_row_din), (grid(x_arr_r + 0.500), y_row_din)], 0.520)
            c.wire("metal4", [(grid(x_arr_r + 0.500), y_row_din), (xv, y_row_din)], 0.440)
            via3_pad(c, xv, y_row_din)
        # M3 from y=57.20 up to yt (passes cleanly UNDER y_vdd_b M4 at 59.20 and pad_p/n M4 at 80.6..86.6!)
        # M4 from y_f_tap up to y=57.20 (passes cleanly OVER East enable M3 tracks f0/f1/m0/m4/m1 at 43.7..55.4!)
        y_f_tap = 37.400 if nm == "fp" else 35.600
        y_f_hop = 57.200
        c.wire("metal3", [(xv, y_f_hop), (xv, yt)], 0.400)
        via3_pad(c, xv, y_f_hop)
        c.wire("metal4", [(xv, y_f_tap), (xv, y_f_hop)], 0.440)
        all_nets.setdefault(nm, []).append((xv, y_f_tap, "metal4"))

    # 6. Route ALL Remaining CMOS Interconnects via ManhattanRouter (3-Row Wide M3 Bands, v5.1 double-spaced!)
    #   * Band S   (South + Row 0 NMOS):      y in [0.5..5.9]
    #   * Band 0-1 (Row 0 PMOS + Ch0-1 + R1): y in [10.4..25.7]  (1.80 um double-spaced p0..p3!)
    #   * Band 1-2 (Row 1 PMOS + Ch1-2 + R2): y in [31.1..42.8]  (1.80 um double-spaced fp/fn!)
    #   * Band 2-A (Row 2 PMOS + Ch2-Arr):    y in [48.2..56.3]  (y_en_b_bus = 57.20, double-spaced mp/mn!)
    m3_tracks = [grid(0.500 + 0.900 * k) for k in range(63)]  # 0.50 .. 56.30
    pref_tracks = {
        yt for yt in m3_tracks
        if (0.5 <= yt <= 5.95) or (10.3 <= yt <= 25.8) or (31.0 <= yt <= 42.9) or (48.1 <= yt <= 56.4)
    }
    router = ManhattanRouter(m3_tracks, m4_min_pitch=0.960, preferred_tracks=pref_tracks)

    # Exact same South perimeter port X coordinates as v4.5 so serializer16 snaps 1:1 with ZERO jog!
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

    east_en_order = ["ffe_en", "m4", "m1", "m0", "f1", "f0"]
    east_en_ports: dict[str, tuple[float, float]] = {}
    x_fan_m4 = grid(x_fp_v + 1.000)
    x_fan_m1 = grid(x_fp_v + 2.000)
    east_route_spec = {
        "ffe_en": (x_pad_out, 34.700, 34.700),
        "m4":     (x_fan_m4,  53.600, 43.700),
        "m1":     (x_fan_m1,  54.500, 45.900),
        "m0":     (x_pad_out, 55.400, 55.400),
        "f1":     (x_pad_out, 51.800, 51.800),
        "f0":     (x_pad_out, 50.900, 50.900),
    }
    # Double-space p0..p3 (1.80 um pitch in Ch0-1), fp/fn (1.80 um pitch in Ch1-2), mp/mn (1.80 um pitch in Ch2-A)!
    pref_y_map: dict[str, float] = {
        "fp": 37.400,
        "fn": 35.600,
        "mp": 56.300,
        "mn": 54.500,
        "p0": 15.800,
        "p1": 17.600,
        "p2": 19.400,
        "p3": 21.200,
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
        pref_y_map[nm] = 0.500
    for idx_b, nm in enumerate(("b0", "b90", "b180", "b270")):
        pref_y_map[nm] = (2.300, 3.200, 5.000, 5.900)[idx_b]
    for idx_c, nm in enumerate(("c0", "c90", "c180", "c270")):
        pref_y_map[nm] = (10.400, 11.300, 12.200, 14.000)[idx_c]
    for idx_d, nm in enumerate(("d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3")):
        pref_y_map[nm] = grid(32.000 + idx_d * 0.900)

    # Reserve M3 power rails, CMOS pillars (generous +-1.30 um clearance!), and East/West vertical M3/M4 trunks
    router.reserve_m3_span(y_en_b_bus, x_arr_l, x_arr_r, "__en_b_bus__")
    for yt in m3_tracks:
        if abs(yt - y_r0_vss) <= 1.350:
            router.reserve_m3_span(yt, grid(r0_vss_pillars[0] - 1.500), grid(x_vss_m5_e + 1.500), "__r0_vss_m3__")
        if abs(yt - y_r1_vss) <= 1.350:
            router.reserve_m3_span(yt, 94.500, grid(x_vss_m5_e + 1.500), "__r1_vss_m3__")
        if abs(yt - y_r2_vss) <= 1.350:
            router.reserve_m3_span(yt, 94.500, grid(x_vss_m5_e + 1.500), "__r2_vss_m3__")
    for xp, yp in cmos_vdd_pillars + cmos_vss_pillars:
        for yt in m3_tracks:
            if abs(yt - yp) <= 1.350:
                router.reserve_m3_span(yt, grid(xp - 1.500), grid(xp + 1.500), "__cmos_pwr__")
        for dx_r in (-1.000, -0.500, 0.000, +0.500, +1.000):
            router.reserve_m4_seg(grid(xp + dx_r), grid(yp - 1.350), grid(yp + 1.350), "__cmos_pwr__")
    for y_rv in (y_r0_vss, y_r1_vss, y_r2_vss):
        for dy_r in (-0.60, 0.0, +0.60):
            router.reserve_m3_span(grid(y_rv + dy_r), grid(x_vss_m5_e - 1.20), grid(x_vss_m5_e + 1.20), "__vss_e__")
        for dx_r in (-0.80, 0.0, +0.80):
            router.reserve_m4_seg(grid(x_vss_m5_e + dx_r), grid(y_rv - 1.20), grid(y_rv + 1.20), "__vss_e__")
    for yt in m3_tracks:
        if y_r0_vss - 0.8 <= yt <= y_r2_vss + 0.8:
            router.reserve_m3_pad(x_pwr_l, yt, "__vss_l__")
        if yt >= y_vdd_b - 0.8:
            router.reserve_m3_pad(x_vdd_e, yt, "__vdd_e__")
    router.reserve_m4_seg(x_fp_v, 37.400, 57.200, "fp")
    router.reserve_m4_seg(x_fn_v, 35.600, 57.200, "fn")
    router.reserve_m4_seg(x_mp_v, y_dinp_b, y_dinp_t, "mp")
    router.reserve_m4_seg(x_mn_v, y_dinn_b, y_dinn_t, "mn")
    router.reserve_m4_seg(x_fan_m4, 43.700, 53.600, "m4")
    router.reserve_m4_seg(x_fan_m1, 45.900, 54.500, "m1")
    router.reserve_m3_span(43.700, x_fan_m4, x_pad_out, "m4")
    router.reserve_m3_span(45.900, x_fan_m1, x_pad_out, "m1")
    router.pre_register_nets(all_nets)

    east_set = set(east_en_order) | {"mp", "mn", "fp", "fn"}
    net_order = sorted(
        all_nets.items(),
        key=lambda kv: (
            0 if kv[0] in east_set else (1 if any(p[2] == "metal4" for p in kv[1]) else 2),
            max(p[0] for p in kv[1]) - min(p[0] for p in kv[1]),
        ),
    )
    for net_name, plist in net_order:
        router.route_net(c, net_name, plist, pref_y=pref_y_map.get(net_name))

    for enm in ("m4", "m1"):
        x_fan, y_trk, y_port = east_route_spec[enm]
        via3_pad(c, x_fan, y_trk)
        c.wire("metal4", [(x_fan, y_port), (x_fan, y_trk)], 0.440)
        via3_pad(c, x_fan, y_port)
        c.wire("metal3", [(x_fan, y_port), (x_pad_out, y_port)], 0.400)

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
        "y_r1_vdd": y_r0_vdd,
        "y_r2_vdd": y_r2_vdd,
        "x_vdd_sp": x_vdd_sp,
        "x_vdrv_sp": x_vdrv_sp,
        "y_vss_m5_bot": y_vss_m5_bot,
        "y_north_port": y_north_port,
        "y_vdd_t": y_vdd_t,
        "y_vdrv_t": y_vdrv_t,
    }


# ---------------------------------------------------------------------------
# 3b. Hardened 5.0 Gb/s 16:4 Serializer (`serdes_tx_sst_serializer16_5g`)
# ---------------------------------------------------------------------------

def _place_dff_r_5g(
    c: Cell, cache: PdkCache, row: scc.RowSpec, x_edge: float, gap_l: float = 0.900,
) -> tuple[dict, float]:
    """Place `sst_dff_r_5g` (nfp=1 tgates -> 0 short, strong Xci/Xcb 1.4/3.4 + Xsq 2.1/5.0 + Xbq1/2 2.7/7.5!)."""
    y0, y1, y2, y3, y4 = row.y_tracks
    ci,  x = scc.place_inv(c, cache, row, x_edge, 1.4, 3.4, 1, 2, gap_l=gap_l, trk_g=2)
    cb,  x = scc.place_inv(c, cache, row, x,      1.4, 3.4, 1, 2, gap_l=0.680, trk_g=2)
    tg1, x = scc.place_tgate(c, cache, row, x,    1.5, 2.8, 1, 1, gap_l=0.880)
    m2,  x = scc.place_nand2(c, cache, row, x,    2.25, 2.8, 1, 1, gap_l=0.680, trk_a=2, trk_b=0)
    m3,  x = scc.place_inv(c, cache, row, x,      0.8, 1.6, 1, 1, gap_l=0.680, trk_g=2)
    tg2, x = scc.place_tgate(c, cache, row, x,    0.8, 1.6, 1, 1, gap_l=1.240)
    tg3, x = scc.place_tgate(c, cache, row, x,    1.5, 2.8, 1, 1, gap_l=1.240)
    sq,  x = scc.place_inv(c, cache, row, x,      2.1, 5.0, 1, 2, gap_l=0.680, trk_g=2)
    sfb, x = scc.place_nand2(c, cache, row, x,    1.2, 1.6, 1, 1, gap_l=0.680, trk_a=2, trk_b=0)
    tg4, x = scc.place_tgate(c, cache, row, x,    0.8, 1.6, 1, 1, gap_l=0.880)
    bq1, x = scc.place_inv(c, cache, row, x,      2.7, 7.5, 2, 3, gap_l=0.680, trk_g=2)
    bq2, x = scc.place_inv(c, cache, row, x,      2.7, 7.5, 2, 3, gap_l=0.680, trk_g=2)

    y_m1 = grid(row.y_vss + 0.780)
    y_m2 = grid(row.y_p_bot + 0.720)
    y_s1 = grid(row.y_vdd - 0.560)

    c.wire("metal1", [(ci["y_col_x"], y2), cb["a"]], W_M1)
    c.wire("metal1", [(tg1["b"][0], y2), m2["a"]], W_M1)
    c.wire("metal1", [(m2["y_col_x"], y2), m3["a"]], W_M1)
    c.via1(m3["y_col_x"], y2)
    c.via1(tg2["a"][0], y2)
    c.wire("metal2", [(m3["y_col_x"], y2), (tg2["a"][0], y2)], 0.220)
    c.wire("metal1", [(tg3["b"][0], y2), sq["a"]], W_M1)
    c.wire("metal1", [(sq["y_col_x"], y2), sfb["a"]], W_M1)
    c.wire("metal1", [(sfb["y_col_x"], y2), tg4["a"]], W_M1)

    c.via1(ci["y_col_x"], y1)
    c.wire("metal1", [(tg1["p"][0], y0), (tg1["p"][0], y1)], W_M1)
    c.via1(tg1["p"][0], y1)
    c.wire("metal1", [(tg4["p"][0], y0), (tg4["p"][0], y1)], W_M1)
    c.via1(tg4["p"][0], y1)
    c.wire("metal2", [(ci["y_col_x"], y1), (tg4["p"][0], y1)], 0.220)

    c.via1(cb["y_col_x"], y3)
    c.wire("metal1", [(tg1["pb"][0], y3), (tg1["pb"][0], y4)], W_M1)
    c.via1(tg1["pb"][0], y3)
    c.wire("metal1", [(tg4["pb"][0], y3), (tg4["pb"][0], y4)], W_M1)
    c.via1(tg4["pb"][0], y3)
    c.wire("metal2", [(cb["y_col_x"], y3), (tg4["pb"][0], y3)], 0.220)

    for tg in (tg2, tg3):
        xg = tg["p"][0]
        xl = grid(xg - 0.440)
        c.wire("metal1", [(xg, y0), (xg, y3)], W_M1)
        c.via1(xg, y3)
        c.wire("metal1", [(xl, y4), (xg, y4)], 0.320)
        c.wire("metal1", [(xl, y1), (xl, y4)], W_M1)
        c.via1(xl, y1)

    c.wire("metal1", [(tg1["b"][0], y_m1), (tg1["b"][0], y2)], W_M1)
    c.wire("metal1", [(tg2["b"][0], y_m1), (tg2["b"][0], y2)], W_M1)
    c.via1(tg1["b"][0], y_m1)
    c.via1(tg2["b"][0], y_m1)
    c.wire("metal2", [(tg1["b"][0], y_m1), (tg2["b"][0], y_m1)], 0.240)

    c.wire("metal1", [(m2["y_col_x"], y2), (m2["y_col_x"], y_m2)], W_M1)
    c.wire("metal1", [(tg3["a"][0], y2), (tg3["a"][0], y_m2)], W_M1)
    c.via1(m2["y_col_x"], y_m2)
    c.via1(tg3["a"][0], y_m2)
    c.wire("metal2", [(m2["y_col_x"], y_m2), (tg3["a"][0], y_m2)], 0.240)

    c.wire("metal1", [(tg3["b"][0], y2), (tg3["b"][0], y_s1)], W_M1)
    c.wire("metal1", [(tg4["b"][0], y2), (tg4["b"][0], y_s1)], W_M1)
    c.wire("metal1", [(bq1["a"][0], y2), (bq1["a"][0], y_s1)], W_M1)
    c.via1(tg3["b"][0], y_s1)
    c.via1(tg4["b"][0], y_s1)
    c.via1(bq1["a"][0], y_s1)
    c.wire("metal2", [(tg3["b"][0], y_s1), (bq1["a"][0], y_s1)], 0.240)

    c.wire("metal1", [(sq["y_col_x"], y_m1), (sq["y_col_x"], y2)], W_M1)
    c.wire("metal1", [(bq2["a"][0], y_m1), (bq2["a"][0], y2)], W_M1)
    c.via1(sq["y_col_x"], y_m1)
    c.via1(bq2["a"][0], y_m1)
    c.wire("metal2", [(sq["y_col_x"], y_m1), (bq2["a"][0], y_m1)], 0.240)

    c.via1(m2["b"][0], y0)
    via2_clean(c, m2["b"][0], y0)
    c.via1(sfb["b"][0], y0)
    via2_clean(c, sfb["b"][0], y0)
    c.wire("metal3", [(m2["b"][0], y0), (sfb["b"][0], y0)], 0.340)

    return {
        "d":     (tg1["a"][0], grid(row.y_p_bot + 0.900)),
        "clk":   ci["a"],
        "rst_n": (m2["b"][0], y0),
        "q":     (bq1["y_col_x"], y2),
        "qb":    (bq2["y_col_x"], y2),
        "x_end": x,
    }, x


def _build_lane_row_5g(
    cache: PdkCache,
    lane_idx: int,
    dins: tuple[str, str, str, str],
    stagger_spec: list[tuple[str, str, bool, str, str | None]],
) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Build 5.0 Gb/s lane row (`is_5g=True` places `_place_dff_r_5g` for output stagger DFF)."""
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
    r_dffs: list[dict] = []
    for k in range(3):
        u, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
        wire_dff_ctrl(u, "clk250b", d_in_global=dins[k])
        r_dffs.append(u)
    u_r3m, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
    wire_dff_ctrl(u_r3m, "clk250b", d_in_global=dins[3])
    u_r3, x = scc.place_dff_r(c, cache, row, x, wn=0.8, wp=1.6, gap_l=0.900)
    ssm._local_m1_abut_to_dff_d(c, u_r3m["q"][0], u_r3["d"][0])
    wire_dff_ctrl(u_r3, "clk250")
    r_dffs.append(u_r3)

    u_ma, x = scc.place_mux2(c, cache, row, x, wn=0.9, wp=1.8, gap_l=1.360)
    add("clk250b", u_ma["sel"], "metal2"); add("clk250", u_ma["sel_b"], "metal2")
    u_da, x = scc.place_dff_r(c, cache, row, x, wn=1.2, wp=2.4, gap_l=0.900)
    wire_dff_ctrl(u_da, "clk500")
    u_mb, x = scc.place_mux2(c, cache, row, x, wn=0.9, wp=1.8, gap_l=1.360)
    add("clk250b", u_mb["sel"], "metal2"); add("clk250", u_mb["sel_b"], "metal2")
    u_db, x = scc.place_dff_r(c, cache, row, x, wn=1.2, wp=2.4, gap_l=0.900)
    wire_dff_ctrl(u_db, "clk500b")
    u_mc, x = scc.place_mux2(c, cache, row, x, wn=1.5, wp=3.0, gap_l=1.360)
    add("clk500", u_mc["sel"], "metal2"); add("clk500b", u_mc["sel_b"], "metal2")
    u_d1g, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=0.900)
    wire_dff_ctrl(u_d1g, "c0")

    prev_q_x = u_d1g["q"][0]
    for ck_n, _d_in, is_5g, q_n, qb_n in stagger_spec:
        if is_5g:
            u_st, x = _place_dff_r_5g(c, cache, row, x, gap_l=0.900)
        else:
            u_st, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=0.900)
        ssm._local_m1_abut_to_dff_d(c, prev_q_x, u_st["d"][0])
        is_final = (qb_n is not None)
        wire_dff_ctrl(u_st, ck_n, q_n=(q_n if is_final else None), qb_n=(qb_n if is_final else None))
        prev_q_x = u_st["q"][0]

    ssm._local_m1_abut_to_dff_d(c, u_ma["y"][0], u_da["d"][0])
    ssm._local_m1_abut_to_dff_d(c, u_mb["y"][0], u_db["d"][0])
    ssm._local_m1_abut_to_dff_d(c, u_mc["y"][0], u_d1g["d"][0])
    ssm._local_m2_nmos_strap(c, r_dffs[2]["q"][0], u_ma["a"][0], ssm.Y_M2_N2, src_y1=2.510, dst_y1=2.050)
    ssm._local_m2_pmos_strap(c, r_dffs[0]["q"][0], u_ma["b"][0], ssm.Y_M2_P1, src_y0=5.990, dst_y0=None)
    ssm._local_m2_pmos_strap(c, r_dffs[1]["q"][0], u_mb["a"][0], ssm.Y_M2_P2, src_y0=5.990, dst_y0=7.330, dst_w=0.300)
    ssm._local_m2_pmos_strap(c, r_dffs[3]["q"][0], u_mb["b"][0], ssm.Y_M2_P3, src_y0=5.990, dst_y0=7.330)
    ssm._local_m2_pmos_strap(c, u_da["q"][0], u_mc["a"][0], ssm.Y_M2_P1, src_y0=5.990, dst_y0=None)
    ssm._local_m2_pmos_strap(c, u_db["q"][0], u_mc["b"][0], ssm.Y_M2_P2, src_y0=5.990, dst_y0=None)
    return c, nets, x


def _build_clk_div_row_5g(cache: PdkCache) -> tuple[Cell, dict[str, list[tuple[float, float, str]]], float]:
    """Row 2 of `serdes_tx_sst_serializer16_5g`: strengthened 4-phase clock buffers for 5.0 Gb/s."""
    row = scc.ROW_SER
    c = Cell()
    nets: dict[str, list[tuple[float, float, str]]] = {}

    def add(net: str, pt: tuple[float, float], lyr: str = "metal1") -> None:
        nets.setdefault(net, []).append((pt[0], pt[1], lyr))

    y2 = row.y_tracks[2]

    # 1. Left Group: /4 divider Xdiv250 + parallel Xb250a/b + Xo250
    x = 48.000
    u250, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=0.900)
    add("rst_n", u250["rst_n"], "metal3")
    ua250, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 3, gap_l=1.000, trk_g=2)
    ub250, x = scc.place_inv(c, cache, row, x, 3.0, 6.0, 2, 2, gap_l=0.900, trk_g=2)
    uo250, x = scc.place_inv(c, cache, row, x, 1.5, 3.0, 1, 2, gap_l=1.000, trk_g=2)
    ssm._local_m2_nmos_strap(c, u250["qb"][0], u250["d"][0], ssm.Y_M2_N2, src_y1=2.510, dst_y1=None)
    c.wire("metal1", [(ub250["a"][0], ssm.Y_M2_N2), (ub250["a"][0], y2)], W_M1)
    c.via1(ub250["a"][0], ssm.Y_M2_N2)
    c.wire("metal2", [(u250["qb"][0], ssm.Y_M2_N2), (ub250["a"][0], ssm.Y_M2_N2)], 0.240)
    c.wire("metal1", [(u250["q"][0], 5.990), (u250["q"][0], ssm.Y_M1_HOP), (ua250["a"][0], ssm.Y_M1_HOP), ua250["a"]], W_M1)
    ssm._local_m2_pmos_strap(c, ub250["y_col_x"], uo250["a"][0], ssm.Y_M2_P2, src_y0=5.990, dst_y0=y2)
    add("clk250b",    ua250["y"])
    add("clk250",     ub250["y"])
    add("clk250_out", uo250["y"])

    # 2. Center Group: hardened 5.0 Gb/s clock buffers Xc0..Xc27b
    x = 88.500
    clk_specs = [
        ("phi0",   "c0",   2.6, 6.0, 5.0, 12.5, 2, 3, 2, 5),
        ("phi90",  "c90",  2.0, 4.8, 3.6,  9.0, 1, 2, 2, 4),
        ("phi180", "c180", 2.2, 5.4, 4.2, 10.5, 1, 3, 2, 4),
        ("phi270", "c270", 2.0, 4.8, 3.6,  9.0, 1, 2, 2, 4),
    ]
    for pin_in, pin_out, wn1, wp1, wn2, wp2, nfn1, nfp1, nfn2, nfp2 in clk_specs:
        u1, x = scc.place_inv(c, cache, row, x, wn1, wp1, nfn1, nfp1, gap_l=1.100, trk_g=2)
        u2, x = scc.place_inv(c, cache, row, x, wn2, wp2, nfn2, nfp2, gap_l=0.800, trk_g=2)
        c.wire("metal1", [(u1["y_col_x"], y2), u2["a"]], W_M1)
        add(pin_in,  u1["a"])
        add(pin_out, u2["y"])

    # 3. Right-Center Group: parallel Xb500a/b + Xo500 + /2 divider Xdiv500
    x = grid(max(x + 2.000, 123.000))
    ua500, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 3, gap_l=1.000, trk_g=2)
    ub500, x = scc.place_inv(c, cache, row, x, 4.0, 8.0, 2, 3, gap_l=0.900, trk_g=2)
    uo500, x = scc.place_inv(c, cache, row, x, 1.5, 3.0, 1, 2, gap_l=1.000, trk_g=2)
    ssm._local_m2_pmos_strap(c, ua500["y_col_x"], uo500["a"][0], ssm.Y_M2_P2, src_y0=5.990, dst_y0=y2)
    add("clk500b",    ua500["y"])
    add("clk500",     ub500["y"])
    add("clk500_out", uo500["y"])

    u500, x = scc.place_dff_r(c, cache, row, x, wn=1.5, wp=3.0, gap_l=1.100)
    add("c0",    u500["clk"])
    add("rst_n", u500["rst_n"], "metal3")
    ssm._local_m2_nmos_strap(c, u500["qb"][0], u500["d"][0], ssm.Y_M2_N2, src_y1=2.510, dst_y1=None)
    c.wire("metal1", [(ub500["a"][0], ssm.Y_M2_N2), (ub500["a"][0], y2)], W_M1)
    c.via1(ub500["a"][0], ssm.Y_M2_N2)
    c.wire("metal2", [(ub500["a"][0], ssm.Y_M2_N2), (u500["d"][0], ssm.Y_M2_N2)], 0.240)

    x_q500, x_a500, x_c250 = u500["q"][0], ua500["a"][0], u250["clk"][0]
    c.wire("metal1", [(x_q500, 5.990), (x_q500, ssm.Y_M2_P1)], W_M1)
    c.via1(x_q500, ssm.Y_M2_P1)
    c.wire("metal1", [(x_a500, y2), (x_a500, ssm.Y_M2_P1)], W_M1)
    c.via1(x_a500, ssm.Y_M2_P1)
    c.wire("metal1", [(x_c250, y2), (x_c250, ssm.Y_M2_P1)], W_M1)
    c.via1(x_c250, ssm.Y_M2_P1)
    c.wire("metal2", [(x_c250, ssm.Y_M2_P1), (x_q500, ssm.Y_M2_P1)], 0.240)
    return c, nets, x


def build_sst_serializer16_5g(
    cache: PdkCache,
    add_ports: bool = True,
    north_pin_xs: dict[str, float] | None = None,
) -> tuple[Cell, dict]:
    """Build hardened 5.0 Gb/s `serdes_tx_sst_serializer16_pdk` (strong Xc0..Xc27b + Xst0/1/2b/3b)."""
    c = Cell()
    row = scc.ROW_SER
    H = row.height  # 9.500

    # Strengthened final stagger DFFs (`_place_dff_r_5g`: Xsq 2.1/5.0, Xbq1/2 2.7/7.5!)
    r0_c, r0_n, r0_w = _build_lane_row_5g(
        cache, 0, ("din0", "din4", "din8", "din12"),
        [("c180", "l0", True, "d0", "db0")],
    )
    r1_c, r1_n, r1_w = _build_lane_row_5g(
        cache, 1, ("din1", "din5", "din9", "din13"),
        [("c270", "l1", True, "d1", "db1")],
    )
    r2_c, r2_n, r2_w = _build_clk_div_row_5g(cache)
    r3_c, r3_n, r3_w = _build_lane_row_5g(
        cache, 2, ("din2", "din6", "din10", "din14"),
        [("c180", "l2", False, "l2h", None), ("c0", "l2h", True, "d2", "db2")],
    )
    r4_c, r4_n, r4_w = _build_lane_row_5g(
        cache, 3, ("din3", "din7", "din11", "din15"),
        [("c180", "l3", False, "l3h", None), ("c90", "l3h", True, "d3", "db3")],
    )

    row_dxs = [0.000, 1.200, 0.000, 2.400, 3.600]
    x_max_w = grid(max(r0_w, r1_w + 1.2, r2_w, r3_w + 2.4, r4_w + 3.6) + 1.500)
    x_row_l = -1.000
    x_row_r = x_max_w
    for rc, rdx in zip((r0_c, r1_c, r2_c, r3_c, r4_c), row_dxs):
        scc.finish_cmos_row(rc, row, grid(x_row_l - rdx), grid(x_row_r - rdx), tap_pitch=1.6)

    y_r0 = 0.000
    y_r1 = grid(2.0 * H)
    y_r2 = y_r1
    y_r3_vss = grid(4.0 * H)
    y_r4_vss = y_r3_vss
    y_top = grid(5.0 * H)

    row_cfgs = [
        (r0_c, r0_n, row_dxs[0], y_r0,     False),
        (r1_c, r1_n, row_dxs[1], y_r1,     True),
        (r2_c, r2_n, row_dxs[2], y_r2,     False),
        (r3_c, r3_n, row_dxs[3], y_r3_vss, True),
        (r4_c, r4_n, row_dxs[4], y_r4_vss, False),
    ]
    all_nets: dict[str, list[tuple[float, float, str]]] = {}
    for rc, rn, rdx, y_vss_w, mir in row_cfgs:
        mapped = ssm._add_row_transformed(c, rc, rn, rdx, y_vss_w, mir)
        for net, pts in mapped.items():
            all_nets.setdefault(net, []).extend(pts)

    x_vss_w = grid(x_row_l - 2.600)
    x_vss_m5_w = -3.300
    x_rst_w = grid(x_row_l - 0.500)
    x_vdd_e = grid(x_row_r + 1.400)
    x_vdd_m5_e = grid(max(225.200, x_vdd_e + 1.400))
    vss_ys = [y_r0, y_r1, y_r3_vss]
    vdd_ys = [grid(y_r0 + H), grid(y_r2 + H), y_top]

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

    rst_pts = all_nets.pop("rst_n", [])
    rst_by_y: dict[float, list[float]] = {}
    for px, py, _ in rst_pts:
        rst_by_y.setdefault(grid(py), []).append(px)
    y_south_port = -1.600
    y_north_port = grid(y_top + 2.000)
    rst_ys = sorted(rst_by_y.keys())
    for ry in rst_ys:
        xs_r = rst_by_y[ry]
        c.wire("metal3", [(x_rst_w, ry), (max(xs_r), ry)], 0.360)
        via3_pad(c, x_rst_w, ry)
    c.wire("metal4", [(x_rst_w, y_south_port), (x_rst_w, max(rst_ys))], 0.440)

    raw_tracks = [grid(0.600 + 0.900 * k) for k in range(int((y_north_port - 0.80) / 0.900) + 1)]
    m3_tracks = [yt for yt in raw_tracks if all(abs(yt - ry) >= 0.880 for ry in rst_ys)]
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

    for pnm in ("clk250_out", "clk500_out"):
        px_src = all_nets[pnm][0][0]
        px = grid(px_src)
        south_ports[pnm] = (px, y_south_port)
        all_nets[pnm].append((px, y_south_port, "metal4"))

    north_order = [
        "phi0", "phi90", "phi180", "phi270",
        "d0", "d1", "d2", "d3", "db0", "db1", "db2", "db3",
    ]
    north_ports: dict[str, tuple[float, float]] = {}
    for pnm in north_order:
        px = grid(north_pin_xs[pnm]) if (north_pin_xs and pnm in north_pin_xs) else ssm.DEFAULT_NORTH_PIN_XS[pnm]
        north_ports[pnm] = (px, y_north_port)
        all_nets.setdefault(pnm, []).append((px, y_north_port, "metal4"))

    pref_y_map: dict[str, float] = {
        "clk250":     20.400, "clk250b": 19.500, "clk500": 25.800, "clk500b": 21.300,
        "c0":         26.700, "c90":     27.600, "c180":   28.500, "c270":    20.400,
        "phi0":       29.400, "phi90":   30.300, "phi180": 29.400, "phi270":  30.300,
        "clk250_out": 19.500, "clk500_out": 20.400,
        "d0":          8.700, "db0":     10.500, "d1":      9.600, "db1":     11.400,
        "d2":         29.400, "db2":     30.300, "d3":     46.500, "db3":     48.300,
    }

    router.pre_register_nets(all_nets)
    net_order = sorted(
        all_nets.items(),
        key=lambda kv: (0 if any(p[2] == "metal4" for p in kv[1]) else 1, max(p[0] for p in kv[1]) - min(p[0] for p in kv[1])),
    )
    for net_name, plist in net_order:
        router.route_net(c, net_name, plist, pref_y=pref_y_map.get(net_name))

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


# ---------------------------------------------------------------------------
# 4. Integrated 16:1 5.0 Gb/s SST Top (`serdes_tx_sst_top_5g`)
# ---------------------------------------------------------------------------

def build_sst_top_5g(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Assemble integrated 16:1 5.0 Gb/s TX SST Top (`serdes_tx_sst_top_pdk`, exact 38 ports)."""
    c = Cell()
    drv_cell, drv_meta = build_sst_driver_5g(cache, add_ports=False)
    x_west_port = grid(drv_meta["ports"]["vbg"][1])
    dx_ser = grid(x_west_port - (-4.200))
    north_pin_xs = {k: grid(x - dx_ser) for k, (x, _) in drv_meta["south_ports"].items()}
    ser_cell, ser_meta = build_sst_serializer16_5g(cache, add_ports=False, north_pin_xs=north_pin_xs)

    y_ser_north = -6.200
    dy_ser = grid(y_ser_north - ser_meta["y_north_port"])
    c.include(drv_cell, dx=0.0, dy=0.0)
    c.include(ser_cell, dx=dx_ser, dy=dy_ser)

    for nm, (px, py_drv) in drv_meta["south_ports"].items():
        c.wire("metal4", [(px, y_ser_north), (px, py_drv)], 0.520)

    phi_ports: dict[str, tuple[float, float]] = {}
    for idx, nm in enumerate(("phi0", "phi90", "phi180", "phi270")):
        yp = grid(-5.250 + idx * 1.300)
        xp = drv_meta["south_ports"][nm][0]
        via3_pad(c, xp, yp)
        c.rect("metal3", x_west_port, grid(yp - 0.220), grid(xp + 0.220), grid(yp + 0.220))
        phi_ports[nm] = (x_west_port, yp)

    x_vss_w = grid(dx_ser + ser_meta["x_vss_w"])
    x_vss_m5_w = grid(dx_ser + ser_meta["x_vss_m5_w"])
    y_ser_vss_hi = grid(dy_ser + ser_meta["vss_ys"][-1])
    y_ldo_vss_m5 = drv_meta["y_vss_m5_bot"]
    c.wire("metal2", [(x_vss_w, y_ser_vss_hi), (x_vss_w, 1.200)], 1.200)
    c.wire("metal5", [(x_vss_m5_w, y_ser_vss_hi), (x_vss_m5_w, y_ldo_vss_m5)], 1.800)
    c.rect("metal5", x_west_port, -4.800, 222.400, 2.700)

    x_ser_vdd = grid(dx_ser + ser_meta["x_vdd_e"])
    x_ser_vdd_m5 = grid(dx_ser + ser_meta["x_vdd_m5_e"])
    y_ser_vdd_hi = grid(dy_ser + ser_meta["vdd_ys"][-1])
    x_drv_vdd_e = drv_meta["x_vdd_e"]
    x_drv_vdd_m5_e = drv_meta["x_vdd_m5_e"]
    y_drv_r1_vdd = drv_meta["y_r1_vdd"]
    y_vdd_jog = -4.000
    for vy_off in (-0.600, -1.200):
        via2_clean(c, x_ser_vdd, grid(y_ser_vdd_hi + vy_off))
    c.wire("metal2", [
        (x_ser_vdd, grid(y_ser_vdd_hi - 1.200)),
        (x_ser_vdd, y_vdd_jog),
        (x_drv_vdd_e, y_vdd_jog),
        (x_drv_vdd_e, y_drv_r1_vdd),
    ], 1.400)
    c.rect(
        "metal5",
        grid(min(x_ser_vdd_m5, x_drv_vdd_m5_e) - 1.000),
        grid(y_ser_vdd_hi - 0.900),
        grid(max(x_ser_vdd_m5, x_drv_vdd_m5_e) + 1.000),
        grid(0.500),
    )

    _, x_vbg, y_vbg = drv_meta["ports"]["vbg"]
    if x_vbg > x_west_port + 0.01:
        c.rect("metal2", x_west_port, grid(y_vbg - 0.220), grid(x_vbg + 0.220), grid(y_vbg + 0.220))

    y_north = drv_meta["y_north_port"]
    y_north_edge = grid(y_north + 0.220)
    x_vdd_sp = drv_meta["x_vdd_sp"]
    x_vdrv_sp = drv_meta["x_vdrv_sp"]
    c.rect("metal4", grid(x_vdd_sp - 0.800), drv_meta["y_vdd_t"], grid(x_vdd_sp + 0.800), y_north_edge)
    c.rect("metal5", grid(x_vdd_sp - 1.000), drv_meta["y_vdd_t"], grid(x_vdd_sp + 1.000), y_north_edge)
    c.rect("metal4", grid(x_vdrv_sp - 1.000), drv_meta["y_vdrv_t"], grid(x_vdrv_sp + 1.000), y_north_edge)

    port_locs: dict[str, tuple[str, float, float]] = {}
    for i in range(16):
        px, py = ser_meta["south_ports"][f"din{i}"]
        port_locs[f"din{i}"] = ("metal4", grid(px + dx_ser), grid(py + dy_ser))
    for nm in ("phi0", "phi90", "phi180", "phi270"):
        port_locs[nm] = ("metal3", *phi_ports[nm])
    for nm in ("rst_n", "clk500_out", "clk250_out"):
        px, py = ser_meta["south_ports"][nm]
        port_locs[nm] = ("metal4", grid(px + dx_ser), grid(py + dy_ser))
    for nm in ("m0", "m1", "m2", "m3", "m4", "f0", "f1", "f2", "ffe_en", "pad_p", "pad_n"):
        port_locs[nm] = drv_meta["ports"][nm]
    port_locs["vbg"] = ("metal2", x_west_port, y_vbg)
    port_locs["vdrv"] = ("metal4", x_vdrv_sp, y_north)
    port_locs["vdd"] = ("metal5", x_vdd_sp, y_north)
    port_locs["vss"] = ("metal5", x_west_port, y_ldo_vss_m5)

    if add_ports:
        order = (
            [f"din{i}" for i in range(16)]
            + ["phi0", "phi90", "phi180", "phi270", "rst_n"]
            + ["m0", "m1", "m2", "m3", "m4", "f0", "f1", "f2", "ffe_en"]
            + ["vbg", "pad_p", "pad_n", "vdrv", "clk500_out", "clk250_out", "vdd", "vss"]
        )
        for pnm in order:
            lyr, px, py = port_locs[pnm]
            c.port(pnm, lyr, px, py)

    return c, {"ports": port_locs, "dy_ser": dy_ser, "dx_ser": dx_ser}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="Optional subset of cells to build/verify")
    ap.add_argument("--skip-png", action="store_true", help="Skip PNG rendering")
    args = ap.parse_args()

    VARIANT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(RESULTS_DIR / "_pdk_cache")

    specs = [
        ("sst_slice_unit_pdk", "sst_slice_unit_5g", lambda: build_sst_slice_unit_5g(cache, add_ports=True),
         ["pad_p", "pad_n", "vdrv", "din_p", "din_n", "vdd", "vss"], 120),
        ("sst_vdrv_ldo_pdk", "sst_vdrv_ldo", lambda: sab.build_sst_vdrv_ldo(cache, add_ports=True, compact_a1=True),
         ["vdrv", "vbg", "vdd", "vss"], 150),
        ("serdes_tx_sst_driver_pdk", "serdes_tx_sst_driver_5g", lambda: build_sst_driver_5g(cache, add_ports=True),
         ["pad_p", "pad_n", "vdrv", "vdd", "vss", "phi0"], 300),
        ("serdes_tx_sst_serializer16_pdk", "serdes_tx_sst_serializer16_5g", lambda: build_sst_serializer16_5g(cache, add_ports=True),
         ["phi0", "d0", "db0", "clk500_out", "clk250_out", "vdd", "vss"], 240),
        ("serdes_tx_sst_top_pdk", "serdes_tx_sst_top_5g", lambda: build_sst_top_5g(cache, add_ports=True),
         ["pad_p", "pad_n", "vdrv", "vdd", "vss", "phi0", "phi90", "phi180", "phi270", "clk500_out", "clk250_out"], 420),
    ]

    if args.only:
        only_set = set(args.only)
        specs = [s for s in specs if s[0] in only_set]

    summary: dict[str, dict] = {}
    for cell_name, src_subckt, builder, rc_watch_nets, timeout_s in specs:
        mag_path = VARIANT_DIR / f"{cell_name}.mag"
        ref_path = VARIANT_DIR / f"{cell_name}_ref.spice"
        review_dir = RESULTS_DIR / "review" / cell_name
        print(f"\n=== Building & Signing Off {cell_name} (from {src_subckt}) ===", flush=True)
        cell, _meta = builder()
        cell.write(mag_path)
        expected_ports = generate_ref_spice_5g(src_subckt, cell_name, ref_path)
        rev = slc.run_independent_review(mag_path, ref_path, review_dir, timeout_s=timeout_s)

        chk = v4b._parse_check_log(review_dir / "check.log")
        floating_poly = v4b._count_floating_poly(mag_path)
        lvs_log = review_dir / f"{cell_name}_lvs.log"
        lvs_txt = lvs_log.read_text() if lvs_log.exists() else ""
        lvs_match = "Circuits match uniquely" in lvs_txt
        lvs_prop_err = "Property errors were found" in lvs_txt
        raw_dev_count = sum(1 for ln in ref_path.read_text().splitlines() if ln.startswith("X"))

        w_um = round(rev["size_um"][0], 3)
        h_um = round(rev["size_um"][1], 3)
        area_um2 = round(w_um * h_um, 2)
        ar = round(w_um / max(h_um, 1e-6), 2)

        pcaps = rev.get("parasitics", {}).get("port_caps_fF", {})
        key_caps = {k: pcaps[k] for k in rc_watch_nets if k in pcaps}
        rc_nets = v4b._parse_rcx_net_resistors(review_dir / f"{cell_name}_rcx.spice", rc_watch_nets)

        png_path = VARIANT_DIR / f"{cell_name}.png"
        if not args.skip_png:
            slc.render_png_plot_mag(mag_path, png_path)

        entry = {
            "cell": cell_name,
            "source_subckt": src_subckt,
            "mag": str(mag_path.relative_to(slc.REPO)),
            "ref_spice": str(ref_path.relative_to(slc.REPO)),
            "png": str(png_path.relative_to(slc.REPO)) if not args.skip_png else None,
            "review_dir": str(review_dir.relative_to(slc.REPO)),
            "pex_spice": str((review_dir / f"{cell_name}_pex.spice").relative_to(slc.REPO)),
            "rcx_spice": str((review_dir / f"{cell_name}_rcx.spice").relative_to(slc.REPO)),
            "bbox_um": [round(v, 3) for v in rev["bbox_um"]],
            "width_um": w_um,
            "height_um": h_um,
            "area_um2": area_um2,
            "aspect_ratio": ar,
            "expected_port_count": len(expected_ports),
            "exported_port_count": len(rev["ports"]),
            "port_count_match": (len(rev["ports"]) == len(expected_ports) and set(rev["ports"]) == set(expected_ports)),
            "physical_passed": rev["physical_passed"],
            "drc_total": chk["drc_total"],
            "floating_poly": floating_poly,
            "lvs_match": lvs_match,
            "lvs_property_errors": lvs_prop_err,
            "rc_devices_preserved": rev.get("rc", {}).get("devices_preserved", False),
            "rc_resistor_count": rev.get("rc", {}).get("resistor_count", 0),
            "key_port_caps_fF": key_caps,
            "key_net_rcx_ohm": rc_nets,
            "raw_device_count": raw_dev_count,
            "merged_device_count": chk["merged_device_count"],
            "net_count": chk["net_count"],
        }
        summary[cell_name] = entry
        print(
            f"  {cell_name}: {w_um:.2f} x {h_um:.2f} um ({area_um2:,.1f} um^2, AR={ar:.2f}) | "
            f"DRC={chk['drc_total']} FP={floating_poly} LVS={lvs_match} prop_err={lvs_prop_err} "
            f"ports={len(rev['ports'])}/{len(expected_ports)} phys={rev['physical_passed']} "
            f"rc_dev_ok={entry['rc_devices_preserved']} devs={raw_dev_count}({chk['merged_device_count']})",
            flush=True,
        )

    if not args.only:
        out_json = VARIANT_DIR / "summary.json"
        out_json.write_text(json.dumps({"variant": "v5_pdk", "pdk": "sky130A", "cells": summary}, indent=2) + "\n")
        print(f"\nWrote {out_json}", flush=True)


if __name__ == "__main__":
    main()
