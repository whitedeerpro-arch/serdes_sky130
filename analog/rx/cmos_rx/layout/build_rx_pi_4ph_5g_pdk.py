#!/usr/bin/env python3
"""SKY130A PDK Physical Layout Builder & Signoff Suite for 5G (2.5 GHz) 4-Phase I/Q Pure CMOS PI:

  1. `serdes_rx_octature_4to8_2p5g_pdk` : 2.5 GHz 4->8 slew-shaped resistor-linearized octature stage
  2. `serdes_rx_pi_4ph_5g_pdk`          : Integrated 2.5 GHz 4-Phase I/Q 64-code CMOS PI + 1.25 GHz /2

Source circuit: `analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice` (1-to-1 SKY130A device match).

Design & Floorplan Guarantees:
  - Strict 0.0% M5 usage (M1-M4 + MIM1 only) for clean top-level M5 PDN stitching.
  - 100% matched 4-pair mirrored octature floorplan + full-height VSS-shielded equal-span M4 slew bus
    (`ips, qps, ins, qns`) + equal-span M3 taps for minimal post-layout 8-phase octature skew.
  - Cardinal perimeter orientation for clean integration into `serdes_rx_cmos_top_5g_pdk`:
      * West  : ip, qp, in, qn (4 quadrature 2.5 GHz inputs), rst_n, vdd, vss
      * South : a0..a7, b0..b7, f0..f7 (24 static 64-code PI controls)
      * North : ckd0..ckd3, cke0..cke3 (8 quarter-rate 1.25 GHz clocks on uniform 16.0 um pitch)
      * East  : dp, dn, ep, en (2.5 GHz PI quadrature-interleaved stitch / probe outputs)
  - All scratch, extraction, and review files live strictly under `results/layout/rx_cmos_5g/pi_4ph/`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rx_layout_common as rlc  # noqa: E402
import build_rx_cmos_pi_5g_pdk as pi5  # noqa: E402
from rx_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    N_STD,
    N_LVT,
    P_STD,
    P_LVT,
    R_0P35,
    R_0P69,
    MIM1,
    W_M1,
    W_M2,
    W_M3,
    W_M4,
    grid,
    viali_pad,
    via1_clean,
    via2_clean,
    via3_pad,
    draw_tap_h,
)

VARIANT_DIR = HERE / "variants" / "v5g_4ph_v3_pdk"
RESULTS_DIR = rlc.REPO / "results" / "layout" / "rx_cmos_5g" / "pi_4ph_v3"

VARIANT_CONFIGS: dict[str, dict[str, object]] = {
    "v5g_4ph_v3_pdk": {
        "variant_dir": HERE / "variants" / "v5g_4ph_v3_pdk",
        "results_dir": rlc.REPO / "results" / "layout" / "rx_cmos_5g" / "pi_4ph_v3",
        "source_spice": "analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice",
    },
}


# ---------------------------------------------------------------------------
# Reference SPICE flattener for `rx_pi_4ph_iq_5g_v3.spice`
# ---------------------------------------------------------------------------

def generate_rx_4ph_ref_spice(
    top_src_subckt: str,
    top_out_subckt: str,
    out_path: Path,
    param_overrides: dict[str, float] | None = None,
    spice_filename: str = "rx_pi_4ph_iq_5g_v3.spice",
) -> list[str]:
    """Flatten `rx_pi_4ph_iq_5g_v3.spice` into an exact SKY130 primitive reference netlist for Netgen."""
    subckts = rlc._parse_spice_subckts([
        rlc.COMMON_SPICE_DIR / "sky130_primitives.spice",
        rlc.COMMON_SPICE_DIR / "sky130_pfet_lvt.spice",
        rlc.RX_SPICE_DIR / spice_filename,
    ])
    if top_src_subckt not in subckts:
        raise KeyError(f"Unknown subckt {top_src_subckt}")

    top_def = subckts[top_src_subckt]
    top_ports = list(top_def["ports"])
    lines: list[str] = [
        f"* Exact flattened LVS reference netlist for {top_out_subckt}",
        f"* Source subckt: {top_src_subckt} (analog/rx/cmos_rx/spice/{spice_filename})",
        f".subckt {top_out_subckt} " + " ".join(top_ports),
    ]
    dev_idx = 0

    def expand(sub_name: str, port_map: dict[str, str], env: dict[str, float], prefix: str) -> None:
        nonlocal dev_idx
        sdef = subckts[sub_name]
        local_env: dict[str, float] = {}
        for k, v in sdef["defaults"].items():
            local_env[k] = rlc._eval_expr(v, env)
        local_env.update(env)

        for inst_name, conns, model, ov in sdef["insts"]:
            mapped_conns = [port_map.get(c, f"{prefix}_{c}") for c in conns]
            child_env = {k: rlc._eval_expr(v, local_env) for k, v in ov.items()}
            if model.startswith("sky130_fd_pr__"):
                dev_idx += 1
                p_strs: list[str] = []
                if "nfet" in model or "pfet" in model:
                    p_strs.append(f"w={rlc._fmt_num(child_env['w'])}")
                    p_strs.append(f"l={rlc._fmt_num(child_env['l'])}")
                elif "res_high_po_" in model:
                    p_strs.append(f"l={rlc._fmt_num(child_env['l'])}")
                elif "cap_mim_" in model:
                    p_strs.append(f"w={rlc._fmt_num(child_env['w'])}")
                    p_strs.append(f"l={rlc._fmt_num(child_env['l'])}")
                else:
                    for k, v in sorted(child_env.items()):
                        p_strs.append(f"{k}={rlc._fmt_num(v)}")
                lines.append(f"X{dev_idx} " + " ".join(mapped_conns) + f" {model} " + " ".join(p_strs))
            elif model in subckts:
                cdef = subckts[model]
                if len(mapped_conns) != len(cdef["ports"]):
                    raise ValueError(f"Port count mismatch calling {model}: {len(mapped_conns)} != {len(cdef['ports'])}")
                cmap = dict(zip(cdef["ports"], mapped_conns))
                expand(model, cmap, child_env, f"{prefix}_{inst_name}")
            else:
                raise KeyError(f"Unknown model {model} inside {sub_name}")

    init_env = {k: rlc._eval_expr(v, {}) for k, v in top_def["defaults"].items()}
    if param_overrides:
        init_env.update(param_overrides)
    expand(top_src_subckt, {p: p for p in top_ports}, init_env, "t")
    lines.append(f".ends {top_out_subckt}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return top_ports


# ---------------------------------------------------------------------------
# Compact DRC-Safe CMOS Inverter Helper (handles narrow multi-finger devices cleanly)
# ---------------------------------------------------------------------------

def draw_oct_inv(
    c: Cell,
    cache: PdkCache,
    cx: float,
    wn: float,
    wp: float,
    n_mdl: str,
    p_mdl: str,
    ln: float,
    lp: float,
    nfn: int,
    nfp: int,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
    x_out_off: float = 0.560,
) -> dict:
    """Draw compact vertical CMOS inverter enforcing >= 0.48 um M1 source-to-drain separation even for small w_f."""
    cx = grid(cx)
    hp = grid((wp / nfp) / 2.0)
    hn = grid((wn / nfn) / 2.0)
    sgn_p = 1.0 if y_vdd > y_p else -1.0
    sgn_n = 1.0 if y_vss > y_n else -1.0
    off_p = grid(max(0.240, min(0.450, hp - 0.160)))
    off_n = grid(max(0.240, min(0.350, hn - 0.140)))
    sp_y = grid(y_p + sgn_p * off_p)
    dp_y = grid(y_p - sgn_p * off_p)
    sn_y = grid(y_n + sgn_n * off_n)
    dn_y = grid(y_n - sgn_n * off_n)

    pm = pi5.place_mos_col(c, cache, cx, p_mdl, wp, lp, nfp, y_p, True, y_g, sp_y, dp_y)
    nm = pi5.place_mos_col(c, cache, cx, n_mdl, wn, ln, nfn, y_n, False, y_g, sn_y, dn_y)

    for sx in pm["s_xs"]:
        c.wire("metal1", [(sx, sp_y), (sx, y_vdd)], 0.220)
    for sx in nm["s_xs"]:
        c.wire("metal1", [(sx, sn_y), (sx, y_vss)], 0.220)

    max_d_off = max(abs(x - cx) for x in (pm["d_xs"] + nm["d_xs"]))
    x_drn = grid(cx + max(x_out_off, max_d_off))
    c.rect("metal1", grid(min(pm["d_xs"][0], x_drn) - 0.09), grid(dp_y - 0.145),
           grid(max(pm["d_xs"][-1], x_drn) + 0.09), grid(dp_y + 0.145))
    c.rect("metal1", grid(min(nm["d_xs"][0], x_drn) - 0.09), grid(dn_y - 0.145),
           grid(max(nm["d_xs"][-1], x_drn) + 0.09), grid(dn_y + 0.145))
    c.wire("metal1", [(x_drn, dp_y), (x_drn, dn_y)], W_M1)

    return {
        "in": (cx, grid(y_g)),
        "out": (x_drn, grid(y_g)),
        "dp": (pm["d"][0], dp_y),
        "dn": (nm["d"][0], dn_y),
        "pm": pm,
        "nm": nm,
    }


# ---------------------------------------------------------------------------
# 1. serdes_rx_octature_4to8_2p5g_pdk — 2.5 GHz 4->8 Slew-Shaped Octature Stage
# ---------------------------------------------------------------------------

def build_rx_octature_4to8_2p5g_pdk(
    cache: PdkCache,
    add_ports: bool = True,
    variant: str = "v5g_4ph_v3_pdk",
) -> tuple[Cell, dict]:
    """Build `serdes_rx_octature_4to8_2p5g_pdk` (14 ports: ip qp in qn cb0..cb7 vdd vss).

    4 identical 11.80 um mirrored differential pair rows (`y = 0.00 .. 47.20`, top power bus at `48.20/49.20`):
      - Pair 0 (y_ctr= 5.90): Xsl0/Xcsl0 (ip->ips) | cb0 (+y), cb4 (-y)
      - Pair 1 (y_ctr=17.70): Xsl1/Xcsl1 (qp->qps) | cb1 (+y), cb5 (-y)
      - Pair 2 (y_ctr=29.50): Xsl2/Xcsl2 (in->ins) | cb2 (+y), cb6 (-y)
      - Pair 3 (y_ctr=41.30): Xsl3/Xcsl3 (qn->qns) | cb3 (+y), cb7 (-y)
    Strict 0.0% M5 usage (M1-M4 + MIM1 only).
    """
    is_v2 = variant in ("v5g_4ph_v2_pdk", "v5g_4ph_v3_pdk")
    c = Cell()

    H_PAIR = 11.800
    pair_ctrs = [grid(5.900 + p * H_PAIR) for p in range(4)]   # 5.90, 17.70, 29.50, 41.30
    vss_ys = [grid(p * H_PAIR) for p in range(5)]              # 0.00, 11.80, 23.60, 35.40, 47.20
    y_vss_top_bus = 48.200
    y_vdd_top = 49.200

    # Column X coordinates
    x_west = 0.000
    x_sl = 2.400
    x_slew_bus = [grid(5.100 + k * 0.880) for k in range(9)]   # [vss, ips, vss, qps, vss, ins, vss, qns, vss]
    x_vss_sh = [x_slew_bus[i] for i in (0, 2, 4, 6, 8)]        # 5.10, 6.86, 8.62, 10.38, 12.14
    slew_x = {
        "ips": x_slew_bus[1],  # 5.980
        "qps": x_slew_bus[3],  # 7.740
        "ins": x_slew_bus[5],  # 9.500
        "qns": x_slew_bus[7],  # 11.260
    }
    x_vdd_m4_w = 13.060
    x_xoa = 15.300
    x_xob = 19.100
    x_roct = 25.400
    x_cac = 24.600
    x_ac_drop = 29.350
    x_rec = 31.100
    x_vdd_m4_m = 32.850
    x_rfb = 35.900
    x_vss_m4_e = 38.600
    x_vdd_m4_e = 39.480
    x_xb = 41.100 if is_v2 else 41.300
    x_xcc = 44.700 if is_v2 else 44.500
    x_oct_east = 47.600

    # Pre-build cached passive subcells
    csl_dev = cache.device(MIM1, dict(w=1.75, l=1.75, nx=1, ny=1, stack=0, doports=1))
    csl_c2_dx = csl_dev.pins("C2")[0][0]  # +1.545
    csl_c1_dx = csl_dev.pins("C1")[0][0]  # -0.730
    csl_dev.labels.clear()

    roct_dev = pi5.rot90_cell(cache.device(R_0P69, dict(l=1.5, nx=4, m=1, guard=1)))
    roct_dev.labels.clear()
    roct_w_x = grid(x_roct - 2.655)       # 22.745
    roct_e_x = grid(x_roct + 2.655)       # 28.055
    roct_gw_x = grid(x_roct - 3.395)      # 22.005
    roct_ge_x = grid(x_roct + 3.395)      # 28.795

    cac_raw = cache.device(MIM1, dict(w=4.2, l=4.2, nx=1, ny=1, stack=0, doports=1))
    cac_raw.labels.clear()
    cac_fx = pi5.flip_x_cell(cac_raw)     # M3 bottom plate [-3.03..+3.03], M4 C1 [-1.37..+2.635]

    rfb_dev = cache.device(R_0P35, dict(l=9.5, nx=4, m=1, guard=1))
    rfb_dev.labels.clear()

    # --- 1. Horizontal VSS rails (y = 0, 11.8, 23.6, 35.4, 47.2) + top full-width VSS M3 bus at 48.20 ---
    # Break psubdiff around rfb_oct on vss_ys[1] & vss_ys[3], and break M3 around Xcac [21.00..29.20] for capm.11/met3.3d!
    for idx_v, yv in enumerate(vss_ys):
        if idx_v in (1, 3):
            draw_tap_h(c, "psubdiff", 0.400, 33.000, yv, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.200)
            draw_tap_h(c, "psubdiff", 38.800, 46.200, yv, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.200)
            c.wire("metal1", [(33.000, yv), (grid(x_rfb - 1.985), yv)], 0.440)
            c.wire("metal1", [(grid(x_rfb + 1.985), yv), (38.800, yv)], 0.440)
        else:
            draw_tap_h(c, "psubdiff", 0.400, 46.200, yv, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.200)
        # M3 segments strictly >= 1.55 um clear of Xcac mimcap [23.23..27.43] and >= 0.57 um clear of Xcac M3 [21.57..27.63]
        c.wire("metal3", [(x_west, yv), (21.000, yv)], 0.400)
        c.wire("metal3", [(29.200, yv), (x_oct_east, yv)], 0.400)
        for vx in (grid(x_sl + csl_c2_dx), 13.500, 20.500, 29.600, 32.850, 38.600, 42.900, 45.800):
            via1_clean(c, vx, yv)
            via2_clean(c, vx, yv)

    # Full-width top VSS M3 bus at y_vss_top_bus = 48.200 (>= 1.57 um above Pair 3 Xcac mimcap 46.35!)
    c.wire("metal3", [(x_west, y_vss_top_bus), (x_oct_east, y_vss_top_bus)], 0.560)

    # Full-width vertical M4 VSS shields & East VSS M4 spine (extending up to y_vss_top_bus = 48.20!)
    for xsh in (*x_vss_sh, x_vss_m4_e):
        c.wire("metal4", [(xsh, vss_ys[0]), (xsh, y_vss_top_bus)], 0.360)
        for yv in (*vss_ys, y_vss_top_bus):
            via3_pad(c, xsh, yv)

    # Equal-span full-height vertical M4 slew trunks (`ips, qps, ins, qns`)
    y_slew_lo = grid(pair_ctrs[0] - 3.450)   # 2.450
    y_slew_hi = grid(pair_ctrs[-1] + 3.450)  # 44.750
    for sx in slew_x.values():
        c.wire("metal4", [(sx, y_slew_lo), (sx, y_slew_hi)], 0.360)

    # Top horizontal VDD M3 bus at y = 49.200 (w=0.600 matching top-level rail) + vertical M4 VDD spines
    c.wire("metal3", [(x_west, y_vdd_top), (x_oct_east, y_vdd_top)], 0.600)
    for xvdd in (x_vdd_m4_w, x_vdd_m4_m, x_vdd_m4_e):
        c.wire("metal4", [(xvdd, pair_ctrs[0]), (xvdd, y_vdd_top)], 0.400)
        via3_pad(c, xvdd, y_vdd_top)

    # Exact Stage 2 input mapping per pair: (top_a, top_b, bot_a, bot_b, stage1_in_port, stage1_slew_net)
    pair_specs = [
        ("ips", "ips", "ins", "ins", "ip", "ips", "cb0", "cb4"),
        ("ips", "qps", "ins", "qns", "qp", "qps", "cb1", "cb5"),
        ("qps", "qps", "qns", "qns", "in", "ins", "cb2", "cb6"),
        ("qps", "ins", "qns", "ips", "qn", "qns", "cb3", "cb7"),
    ]

    in_ports: dict[str, tuple[float, float]] = {}
    cb_ports: dict[str, tuple[float, float]] = {}
    rec_in_pts: dict[str, tuple[float, float]] = {}
    rec_out_pts: dict[str, tuple[float, float]] = {}

    # --- 2. Build all 4 IDENTICAL Mirrored Differential Pairs ---
    for p_idx, (top_a, top_b, bot_a, bot_b, in_nm, sl_net, cb_top_nm, cb_bot_nm) in enumerate(pair_specs):
        yc = pair_ctrs[p_idx]
        y_vdd = yc
        y_vss_t = grid(yc + H_PAIR / 2.0)
        y_vss_b = grid(yc - H_PAIR / 2.0)

        # NWELL blocks (strictly around transistor columns, clear of roct & rfb!)
        c.rect("nwell", 0.500, grid(yc - 0.550), 4.300, grid(yc + 2.600))
        c.rect("nwell", 13.450, grid(yc - 2.600), 20.950, grid(yc + 2.600))
        nw_c4_h = 2.850 if is_v2 else 2.600
        c.rect("nwell", 29.250, grid(yc - nw_c4_h), 33.150, grid(yc + nw_c4_h))
        nw_c5_h = 2.850 if is_v2 else 2.600
        c.rect("nwell", 38.800 if is_v2 else 39.250, grid(yc - nw_c5_h), 45.950 if is_v2 else 45.750, grid(yc + nw_c5_h))

        # Horizontal VDD taps + M1/M3 bridges (clear of roct/Xcac M3 and rfb M3 pads!)
        draw_tap_h(c, "nsubdiff", 0.700, 4.100, y_vdd, half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.000)
        draw_tap_h(c, "nsubdiff", 13.650, 20.750, y_vdd, half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.100)
        draw_tap_h(c, "nsubdiff", 29.450, 32.950, y_vdd, half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.000)
        draw_tap_h(c, "nsubdiff", 39.000 if is_v2 else 39.450, 45.750 if is_v2 else 45.550, y_vdd, half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.100)

        # Stitch Col 0 (Xsl) VDD across slew bus to Col 2 (Xo) VDD on M3 at y_vdd (M3 free here!)
        c.wire("metal3", [(1.100, y_vdd), (14.100, y_vdd)], 0.400)
        for vx in (1.100, 14.100):
            via1_clean(c, vx, y_vdd)
            via2_clean(c, vx, y_vdd)
        via3_pad(c, x_vdd_m4_w, y_vdd)

        # Tie Col 4A (Xrec) and Col 5 (Xb/Xcc) VDD taps directly to their vertical M4 VDD spines (clear of rfb!)
        for vx in (32.850, 39.480):
            via1_clean(c, vx, y_vdd)
            via2_clean(c, vx, y_vdd)
            via3_pad(c, vx, y_vdd)

        # --- Stage 1: Xsl_p (Top +y) + Xcsl_p (Bot -y) ---
        xsl = draw_oct_inv(
            c, cache, x_sl, 1.40, 5.60, N_LVT, P_LVT, 0.15, 0.35, 2, 4,
            grid(yc + 1.500), grid(yc + 4.200), grid(yc + 2.900), y_vdd, y_vss_t,
            x_out_off=0.640,
        )
        # West input port (ip / qp / in / qn) on M3 at y = yc + 2.900
        y_in = grid(yc + 2.900)
        x_in_via = 0.850
        c.wire("metal3", [(x_west, y_in), (x_in_via, y_in)], 0.360)
        via2_clean(c, x_in_via, y_in)
        via1_clean(c, x_in_via, y_in)
        c.wire("metal1", [(x_in_via, y_in), xsl["in"]], 0.240)
        in_ports[in_nm] = (x_west, y_in)

        # Xcsl_p (1.75 x 1.75 MIM1) in Bottom half at (x_sl, yc - 3.400): >= 1.365 um capm.11 to BOTH y_sl_feed & y_vss_b!
        y_csl = grid(yc - 3.400)
        c.include(csl_dev, dx=x_sl, dy=y_csl)
        # Tie Xcsl.C2 (vss bottom plate M3 at x_sl + 1.545 = 3.945) straight down to y_vss_b M3 (w=0.520 flush with via2!)
        x_csl_c2 = grid(x_sl + csl_c2_dx)  # 3.945
        c.wire("metal3", [(x_csl_c2, grid(y_csl - 0.900)), (x_csl_c2, y_vss_b)], 0.520)
        # Connect Xcsl.C1 (M4 top plate at x_sl - 0.730 = 1.670) -> (3.040, yc - 0.900) -> equal-span M3 feed -> slew_x[sl_net]
        y_sl_feed = grid(yc - 0.900)
        x_sl_out = xsl["out"][0]           # 3.040
        x_csl_c1 = grid(x_sl + csl_c1_dx)  # 1.670
        c.wire("metal4", [(x_csl_c1, y_csl), (x_csl_c1, y_sl_feed), (x_sl_out, y_sl_feed)], 0.380)
        via3_pad(c, x_sl_out, y_sl_feed)
        # Xsl.out -> M2 straight down to y_sl_feed -> via2 -> equal-span M3 [x_sl_out .. slew_x['qns']]
        via1_clean(c, x_sl_out, y_in)
        c.wire("metal2", [(x_sl_out, y_in), (x_sl_out, y_sl_feed)], 0.300)
        via2_clean(c, x_sl_out, y_sl_feed)
        c.wire("metal3", [(x_sl_out, y_sl_feed), (slew_x["qns"], y_sl_feed)], 0.340)
        via3_pad(c, slew_x[sl_net], y_sl_feed)

        # --- Stage 2 resistors: rot90(roct_1p5_nx4) centered at (x_roct, yc) ---
        c.include(roct_dev, dx=x_roct, dy=yc)
        # Tie roct guard ring cleanly to y_vss_b & y_vss_t
        for xg in (roct_gw_x, roct_ge_x):
            for yt in (grid(yc - 2.500), grid(yc + 2.500)):
                viali_pad(c, xg, yt)
            c.wire("metal1", [(xg, y_vss_b), (xg, y_vss_t)], 0.300)

        # --- Both Halves (+1 = phase p, -1 = phase p+4): Xo, Xcac, Xrec, Xb, Xcc ---
        xcc_refs: dict[int, dict] = {}
        xb_refs: dict[int, dict] = {}
        for sgn, src_a, src_b, cb_nm in ((+1, top_a, top_b, cb_top_nm), (-1, bot_a, bot_b, cb_bot_nm)):
            y_vss_h = y_vss_t if sgn > 0 else y_vss_b
            y_p = grid(yc + sgn * 1.500)
            y_gc = grid(yc + sgn * 2.900)
            y_n = grid(yc + sgn * 4.200)

            # Stage 2: Xo.Xa & Xo.Xb (pi4_inv_lvt 1.10/4.40 nfn=1 nfp=4)
            xoa = draw_oct_inv(
                c, cache, x_xoa, 1.10, 4.40, N_LVT, P_LVT, 0.15, 0.35, 1, 4,
                y_p, y_n, y_gc, y_vdd, y_vss_h, x_out_off=0.640,
            )
            xob = draw_oct_inv(
                c, cache, x_xob, 1.10, 4.40, N_LVT, P_LVT, 0.15, 0.35, 1, 4,
                y_p, y_n, y_gc, y_vdd, y_vss_h, x_out_off=0.640,
            )

            # Equal-span M3 taps from slew bus [slew_x['ips'] .. gate_x]
            y_tap_a = grid(yc + sgn * 2.350)
            y_tap_b = grid(yc + sgn * 3.450)
            c.wire("metal3", [(slew_x["ips"], y_tap_a), (x_xoa, y_tap_a)], 0.340)
            via3_pad(c, slew_x[src_a], y_tap_a)
            via2_clean(c, x_xoa, y_tap_a)
            c.wire("metal2", [(x_xoa, y_tap_a), (x_xoa, y_gc)], 0.280)
            via1_clean(c, x_xoa, y_gc)

            c.wire("metal3", [(slew_x["ips"], y_tap_b), (x_xob, y_tap_b)], 0.340)
            via3_pad(c, slew_x[src_b], y_tap_b)
            via2_clean(c, x_xob, y_tap_b)
            c.wire("metal2", [(x_xob, y_tap_b), (x_xob, y_gc)], 0.280)
            via1_clean(c, x_xob, y_gc)

            # Zero-crossing M2 stitches: Xa.out -> inner bar (±0.585), Xb.out -> outer bar (±1.755)
            y_bar_in = grid(yc + sgn * 0.585)
            y_bar_out = grid(yc + sgn * 1.755)
            via1_clean(c, xoa["out"][0], y_gc)
            c.wire("metal2", [(xoa["out"][0], y_gc), (xoa["out"][0], y_bar_in), (roct_w_x, y_bar_in)], 0.300)
            via1_clean(c, roct_w_x, y_bar_in)

            via1_clean(c, xob["out"][0], y_gc)
            c.wire("metal2", [(xob["out"][0], y_gc), (xob["out"][0], y_bar_out), (roct_w_x, y_bar_out)], 0.300)
            via1_clean(c, roct_w_x, y_bar_out)

            # East summing node `m_k`: unite inner & outer East heads on M1+M2 -> via2 -> Xcac M3 bottom plate!
            # Place via2 at yc + sgn*1.650 (>= 0.74 um inside Xcac M3 edge yc+0.65) with flush 0.520 M3 bridge!
            y_m_mid = grid(yc + sgn * 1.650)
            c.wire("metal1", [(roct_e_x, y_bar_in), (roct_e_x, y_bar_out)], 0.380)
            c.wire("metal2", [(roct_e_x, y_bar_in), (roct_e_x, y_bar_out)], 0.380)
            via1_clean(c, roct_e_x, y_bar_in)
            via1_clean(c, roct_e_x, y_bar_out)
            via2_clean(c, roct_e_x, y_m_mid)

            # 3D-stacked Stage 3A MIM cap `Xcac` (4.2 x 4.2, flip_x) centered at (x_cac=24.60, yc + sgn*2.950)
            y_cac = grid(yc + sgn * 2.950)
            c.include(cac_fx, dx=x_cac, dy=y_cac)
            # Connect roct_e_x (28.055) M3 flush (w=0.520 == via2 pad!) into Xcac M3 right edge (27.630)
            c.wire("metal3", [(grid(x_cac + 2.600), y_m_mid), (roct_e_x, y_m_mid)], 0.520)
            # Escape `ac_k` from Xcac.C1 M4 top plate (x in [23.23..27.235]) straight EAST at y_gc
            c.wire("metal4", [(grid(x_cac + 2.100), y_gc), (x_ac_drop, y_gc)], 0.400)
            via3_pad(c, x_ac_drop, y_gc)
            via2_clean(c, x_ac_drop, y_gc)

            # Stage 3A Recovery Inverter `Xrec` (v1: 1.65/6.60, v2: 2.20/8.40, both LVT nfn=2 nfp=4)
            y_p_rec = grid(yc + sgn * 1.500) if is_v2 else y_p
            y_gc_v2 = grid(yc + sgn * 2.960) if is_v2 else y_gc
            xrec = draw_oct_inv(
                c, cache, x_rec,
                2.20 if is_v2 else 1.65,
                8.40 if is_v2 else 6.60,
                N_LVT, P_LVT, 0.15, 0.35, 2, 4,
                y_p_rec, y_n, y_gc_v2, y_vdd, y_vss_h, x_out_off=0.640,
            )
            # `ac_k` M2 into Xrec.in
            c.wire("metal2", [(x_ac_drop, y_gc), (x_rec, y_gc), (x_rec, y_gc_v2)], 0.300)
            via1_clean(c, x_rec, y_gc_v2)
            rec_in_pts[cb_nm] = (x_rec, y_gc)

            # `o_k` from Xrec.out at y_o = yc + sgn*3.700 -> M3 straight EAST across rfb into Xb.in!
            y_o = grid(yc + sgn * 3.700)
            via1_clean(c, xrec["out"][0], y_o)
            via2_clean(c, xrec["out"][0], y_o)
            c.wire("metal3", [(xrec["out"][0], y_o), (x_xb, y_o)], 0.360)
            rec_out_pts[cb_nm] = (xrec["out"][0], y_o)

            # Stage 3B Output Buffer `Xb` + half of `Xcc`
            if is_v2:
                y_p_xb = grid(yc + sgn * 1.500)
                xb = draw_oct_inv(
                    c, cache, x_xb, 3.40, 12.60, N_LVT, P_LVT, 0.15, 0.35, 2, 6,
                    y_p_xb, y_n, y_gc_v2, y_vdd, y_vss_h, x_out_off=1.920,
                )
            else:
                xb = draw_oct_inv(
                    c, cache, x_xb, 2.40, 10.80, N_LVT, P_STD, 0.15, 0.15, 2, 6,
                    y_p, y_n, y_gc, y_vdd, y_vss_h, x_out_off=0.960,
                )
            via2_clean(c, x_xb, y_o)
            c.wire("metal2", [(x_xb, y_o), (x_xb, y_gc_v2)], 0.300)
            via1_clean(c, x_xb, y_gc_v2)

            if is_v2:
                xcc = draw_oct_inv(
                    c, cache, x_xcc, 0.45, 2.10, N_LVT, P_LVT, 0.15, 0.35, 1, 1,
                    y_p_xb, y_n, y_gc, y_vdd, y_vss_h, x_out_off=0.720,
                )
            else:
                xcc = draw_oct_inv(
                    c, cache, x_xcc, 0.45, 2.025, N_LVT, P_STD, 0.15, 0.15, 1, 3,
                    y_p, y_n, y_gc, y_vdd, y_vss_h, x_out_off=0.720,
                )
            # M1 stitch Xb.out -> Xcc.in (same phase cb_nm)
            c.wire("metal1", [(xb["out"][0], y_gc), xcc["in"]], 0.240)
            xb_refs[sgn] = xb
            xcc_refs[sgn] = xcc

            # Export `cb_nm` straight EAST on lean 0.30 um M3 from x_cb_via to x_oct_east = 47.60
            x_cb_via = 43.850 if is_v2 else 43.000
            via1_clean(c, x_cb_via, y_gc)
            via2_clean(c, x_cb_via, y_gc)
            c.wire("metal3", [(x_cb_via, y_gc), (x_oct_east, y_gc)], 0.300)
            cb_ports[cb_nm] = (x_oct_east, y_gc)

        # Cross-couple `Xcc` within pair (WIDE 1.25 um M2 separation -> cuts 180-deg Miller C in half!)
        y_top_gc = grid(yc + 2.900)
        y_bot_gc = grid(yc - 2.900)
        y_top_cc = grid(yc + 2.200)
        y_bot_cc = grid(yc - 2.200)
        x_cc_out = xcc_refs[+1]["out"][0]  # 45.420 (v2) / 45.220 (v1)
        x_cc_t = 45.950 if is_v2 else 45.850
        x_cc_b = 47.100

        via2_clean(c, x_cc_t, y_top_gc)
        c.wire("metal2", [(x_cc_t, y_top_gc), (x_cc_t, y_bot_cc)], 0.280)
        via1_clean(c, x_cc_t, y_bot_cc)
        c.wire("metal1", [(x_cc_out, y_bot_cc), (x_cc_t, y_bot_cc)], 0.220)

        via2_clean(c, x_cc_b, y_bot_gc)
        c.wire("metal2", [(x_cc_b, y_bot_gc), (x_cc_b, y_top_cc)], 0.280)
        via1_clean(c, x_cc_b, y_top_cc)
        c.wire("metal1", [(x_cc_out, y_top_cc), (x_cc_b, y_top_cc)], 0.220)

    # --- 3. Two identical vertical `rfb_oct_9p5_nx4` banks (Bank 01 at y=11.80, Bank 23 at y=35.40) ---
    # Quadrature/45-deg interleaved bar order (cb4, cb5, cb0, cb1) -> ZERO adjacent 180-deg Miller coupling on o_k M4!
    bar_dxs = [-1.245, -0.415, +0.415, +1.245]
    m4_dxs = [-1.380, -0.460, +0.460, +1.380]
    for b_idx, (y_mid, phases_4) in enumerate((
        (vss_ys[1], ("cb4", "cb5", "cb0", "cb1")),  # Bank 01 at y=11.80
        (vss_ys[3], ("cb6", "cb7", "cb2", "cb3")),  # Bank 23 at y=35.40
    )):
        c.include(rfb_dev, dx=x_rfb, dy=y_mid)
        # Tie rfb guard ring cleanly to adjacent vss rails
        y_g_bot = grid(y_mid - 7.395)
        y_g_top = grid(y_mid + 7.395)
        viali_pad(c, x_rfb, y_g_bot)
        viali_pad(c, x_rfb, y_g_top)
        c.wire("metal1", [(x_rfb, y_g_bot), (x_rfb, grid(y_mid - H_PAIR))], 0.340)
        c.wire("metal1", [(x_rfb, y_g_top), (x_rfb, grid(y_mid + H_PAIR))], 0.340)
        for xgr in (grid(x_rfb - 1.985), grid(x_rfb + 1.985)):
            viali_pad(c, xgr, y_mid)

        y_h_bot = grid(y_mid - 6.655)
        y_h_top = grid(y_mid + 6.655)

        for k, cb_nm in enumerate(phases_4):
            xb_bar = grid(x_rfb + bar_dxs[k])
            xm4 = grid(x_rfb + m4_dxs[k])
            ac_x, ac_y = rec_in_pts[cb_nm]
            _, o_y = rec_out_pts[cb_nm]

            # Pair-lower phases (cb4, cb0 / cb6, cb2 -> k in (0, 2)): ac->bot head, o->top head
            # Pair-upper phases (cb5, cb1 / cb7, cb3 -> k in (1, 3)): ac->top head, o->bot head
            is_lower = (k in (0, 2))
            y_ac_head = y_h_bot if is_lower else y_h_top
            y_o_head = y_h_top if is_lower else y_h_bot

            # `ac_k` M2 (zero crossings across all 4 bars!)
            c.wire("metal2", [(ac_x, ac_y), (xb_bar, ac_y), (xb_bar, y_ac_head)], 0.280)
            via1_clean(c, xb_bar, y_ac_head)

            # `o_k` M3 -> lean 0.30 um M4 vertical -> via3+via2+via1 onto FAR head
            via3_pad(c, xm4, o_y)
            c.wire("metal4", [(xm4, o_y), (xm4, y_o_head)], 0.300)
            via3_pad(c, xm4, y_o_head)
            via2_clean(c, xm4, y_o_head)
            via1_clean(c, xm4, y_o_head)
            if abs(xm4 - xb_bar) > 0.005:
                c.wire("metal1", [(min(xm4, xb_bar), y_o_head), (max(xm4, xb_bar), y_o_head)], 0.240)

    meta = {
        **in_ports,
        **cb_ports,
        "vdd": (x_west, y_vdd_top),
        "vss": (x_west, y_vss_top_bus),
        "vss_ys": vss_ys,
        "y_vss_top_bus": y_vss_top_bus,
        "y_vdd_top": y_vdd_top,
        "x_east": x_oct_east,
    }

    if add_ports:
        for nm in ("ip", "qp", "in", "qn"):
            c.port(nm, "metal3", *in_ports[nm])
        for k in range(8):
            nm = f"cb{k}"
            c.port(nm, "metal3", *cb_ports[nm])
        c.port("vdd", "metal3", x_west, y_vdd_top)
        c.port("vss", "metal3", x_west, y_vss_top_bus)

    return c, meta


# ---------------------------------------------------------------------------
# 2. Updated 5G 4-Phase `pi4_diff_chan` (lres=6.4, cmix=2.8, cac=3.7, lrfb=8.0, rec=1.65, r2=2.60)
# ---------------------------------------------------------------------------

def _build_pi4_diff_chan_cell(cache: PdkCache) -> tuple[Cell, dict]:
    """Build ONE mathematically Y-mirror symmetric 5G 4-phase `pi4_diff_chan` centered at y = 0.0."""
    ch = Cell()
    half = Cell()

    # Shared symmetric resistor banks (centered at y = 0.0)
    # res_high_po_0p69 l=6.4 nx=16 guard=1 -> rot90 bbox (-6.11, -9.95, +6.11, +9.95), R1=-5.105, R2=+5.105, B=+-5.845
    r16 = pi5.rot90_cell(cache.device(R_0P69, dict(l=6.4, nx=16, m=1, guard=1)))
    x_r16_c = 99.400
    r16_r1_x = grid(x_r16_c - 5.105)   # 94.295 (exact same West head X as v5g_pdk!)
    r16_r2_x = grid(x_r16_c + 5.105)   # 104.505
    r16_top_ys = [grid(0.585 + k * 1.170) for k in range(8)]
    r16.labels.clear()
    ch.include(r16, dx=x_r16_c, dy=0.0)

    # Vertical r2: res_high_po_0p35 l=8.0 nx=2 guard=1 -> bbox (-1.42, -6.91, +1.42, +6.91), R1=+5.905, R2=-5.905, B=+-6.645
    r2 = cache.device(R_0P35, dict(l=8.0, nx=2, m=1, guard=1))
    x_r2_c = 107.800
    x_r2_w = grid(x_r2_c - 0.415)      # 107.385
    x_r2_e = grid(x_r2_c + 0.415)      # 108.215
    y_r2_hi = +5.905
    y_r2_lo = -5.905
    r2.labels.clear()
    ch.include(r2, dx=x_r2_c, dy=0.0)

    # Tie r16 & r2 guard rings to vss rails at y = +-10.500
    y_vss_ch = 10.500
    for xg_tie in (grid(x_r16_c - 5.845), grid(x_r16_c + 5.845)):
        for yt in (-9.500, 0.000, +9.500):
            viali_pad(ch, xg_tie, yt)
        ch.wire("metal1", [(xg_tie, -y_vss_ch), (xg_tie, +y_vss_ch)], 0.340)
    for yt_r2 in (-6.645, +6.645):
        viali_pad(ch, x_r2_c, yt_r2)
    ch.wire("metal1", [(x_r2_c, +6.645), (x_r2_c, +y_vss_ch)], 0.340)
    ch.wire("metal1", [(x_r2_c, -6.645), (x_r2_c, -y_vss_ch)], 0.340)

    # 1. Stage 1 TOP: Xmap & Xmbp (identical to 5G v5g_pdk!)
    x_mux_a = 15.600
    x_mux_b = 31.400
    x_s1_nw_r = 41.900
    half.rect("nwell", grid(x_mux_a - 1.20), +5.800, x_s1_nw_r, +9.300)
    draw_tap_h(half, "nsubdiff", grid(x_mux_a - 0.80), 41.700, +8.800, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)
    draw_tap_h(half, "psubdiff", grid(x_mux_a - 0.80), 41.800, +2.400, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)
    mux_a = pi5._draw_pi_mux4_half(half, cache, x_mux_a)
    mux_b = pi5._draw_pi_mux4_half(half, cache, x_mux_b)

    # 2. Stage 2 TOP: 8x pi4_slice_r (identical FETs to 5G v5g_pdk!)
    slice_xs = [grid(44.600 + c_idx * 11.400) for c_idx in range(4)]
    x_mix_l = grid(slice_xs[0] - 0.850)   # 43.750
    x_mix_r = grid(slice_xs[-1] + 10.900) # 89.700
    half.rect("nwell", 43.400, +2.200, grid(x_mix_r + 0.50), +8.300)
    draw_tap_h(half, "nsubdiff", x_mix_l, x_mix_r, +5.250, half_w=0.175, with_m1=True, m1_w=0.300, viali_pitch=1.20)
    draw_tap_h(half, "psubdiff", x_mix_l, x_mix_r, +y_vss_ch, half_w=0.175, with_m1=True, m1_w=0.360, viali_pitch=1.20)
    draw_tap_h(ch,   "psubdiff", x_mix_l, x_mix_r, 0.000, half_w=0.175, with_m1=True, m1_w=0.360, viali_pitch=1.20)

    slices_top: dict[int, dict] = {}
    for col_i, sx in enumerate(slice_xs):
        slices_top[2 * col_i]     = pi5._draw_pi_slice_r_fets_clean(half, cache, sx, y_vss=0.000,    y_vdd=+5.250)
        slices_top[2 * col_i + 1] = pi5._draw_pi_slice_r_fets_clean(half, cache, sx, y_vss=+y_vss_ch, y_vdd=+5.250)

    y_ca = +4.450
    y_cb = +6.050
    for mx_pt, yt_clk in ((mux_a["out"], y_ca), (mux_b["out"], y_cb)):
        via1_clean(half, mx_pt[0], mx_pt[1])
        half.wire("metal2", [mx_pt, (mx_pt[0], yt_clk)], 0.320)
        via2_clean(half, mx_pt[0], yt_clk)

    ca_max_x = mux_a["out"][0]
    cb_max_x = mux_b["out"][0]
    for col_i in range(4):
        s_ev = slices_top[2 * col_i]
        for xca in s_ev["ca_xs"]:
            via1_clean(half, xca, y_ca)
            via1_clean(half, xca, y_cb)
            half.wire("metal2", [(xca, y_ca), (xca, y_cb)], 0.300)
            via2_clean(half, xca, y_ca)
            ca_max_x = max(ca_max_x, xca)
        for xcb in s_ev["cb_xs"]:
            via1_clean(half, xcb, y_ca)
            via1_clean(half, xcb, y_cb)
            half.wire("metal2", [(xcb, y_ca), (xcb, y_cb)], 0.300)
            via2_clean(half, xcb, y_cb)
            cb_max_x = max(cb_max_x, xcb)
    half.wire("metal3", [(mux_a["out"][0], y_ca), (ca_max_x, y_ca)], 0.300)
    half.wire("metal3", [(mux_b["out"][0], y_cb), (cb_max_x, y_cb)], 0.300)

    x_vdd_w_ch = 42.650
    via1_clean(half, x_vdd_w_ch, +5.250)
    via2_clean(half, x_vdd_w_ch, +5.250)
    half.wire("metal3", [(x_vdd_w_ch, +5.250), (x_mix_r, +5.250)], 0.300)

    drv_plan = [
        (6, +0.550, 0, 91.950),
        (4, +1.410, 1, 91.300),
        (2, +2.270, 2, 90.650),
        (0, +3.130, 3, 90.000),
        (1, +7.370, 4, 90.000),
        (3, +8.230, 5, 90.650),
        (5, +9.090, 6, 91.300),
        (7, +9.950, 7, 91.950),
    ]
    for s_idx, yt, bar_i, xj in drv_plan:
        sl = slices_top[s_idx]
        dx = sl["drv_x"]
        y_lo = min(sl["drv_y_lo"], yt)
        y_hi = max(sl["drv_y_hi"], yt)
        half.wire("metal1", [(dx, y_lo), (dx, y_hi)], 0.320)
        via1_clean(half, dx, yt)
        via2_clean(half, dx, yt)
        half.wire("metal3", [(dx, yt), (xj, yt)], 0.340)
        via2_clean(half, xj, yt)
        yb = r16_top_ys[bar_i]
        half.wire("metal2", [(xj, yt), (xj, yb), (r16_r1_x, yb)], 0.400)
        via1_clean(half, r16_r1_x, yb)

    f_m4_xs: dict[int, float] = {}
    fb_m4_xs: dict[int, float] = {}
    for col_i, sx in enumerate(slice_xs):
        ev = 2 * col_i
        od = 2 * col_i + 1
        xf_ev, yf_ev = slices_top[ev]["f_tap"]
        xfb_ev, yfb_ev = slices_top[ev]["fb_tap"]
        xf_od, yf_od = slices_top[od]["f_tap"]
        xfb_od, yfb_od = slices_top[od]["fb_tap"]

        xm_f_ev  = xf_ev
        xm_fb_ev = xfb_ev
        xm_f_od  = grid(xf_od + 1.050)
        xm_fb_od = grid(xfb_od + 1.050)
        f_m4_xs[ev], fb_m4_xs[ev] = xm_f_ev, xm_fb_ev
        f_m4_xs[od], fb_m4_xs[od] = xm_f_od, xm_fb_od

        via2_clean(half, xm_f_ev, yf_ev)
        via3_pad(half, xm_f_ev, yf_ev)
        via2_clean(half, xm_fb_ev, yfb_ev)
        via3_pad(half, xm_fb_ev, yfb_ev)

        via2_clean(half, xf_od, yf_od)
        half.wire("metal3", [(xf_od, yf_od), (xm_f_od, yf_od)], 0.520)
        via3_pad(half, xm_f_od, yf_od)

        via2_clean(half, xfb_od, yfb_od)
        half.wire("metal3", [(xfb_od, yfb_od), (xm_fb_od, yfb_od)], 0.520)
        via3_pad(half, xm_fb_od, yfb_od)

    # 3. Stage 3 East summing bar (`mixp`) on r16 East heads (x = 104.505)
    half.wire("metal1", [(r16_r2_x, r16_top_ys[0]), (r16_r2_x, r16_top_ys[-1])], 0.440)
    half.wire("metal2", [(r16_r2_x, r16_top_ys[0]), (r16_r2_x, r16_top_ys[-1])], 0.440)
    for yb in r16_top_ys:
        via1_clean(half, r16_r2_x, yb)

    # 4. Stage 3+4 MERGED: 3D-Stack `Xcmix` (2.8x2.8) & `Xcac` (3.7x3.7) directly over `r16_6p4`!
    mim_mix = cache.device(MIM1, dict(w=2.8, l=2.8, nx=1, ny=1, stack=0, doports=1))
    c2_mix_rel = mim_mix.pins("C2")[0]  # (+2.070, 0.0)
    mim_mix.labels.clear()

    mim_ac = cache.device(MIM1, dict(w=3.7, l=3.7, nx=1, ny=1, stack=0, doports=1))
    c2_ac_rel = mim_ac.pins("C2")[0]    # (+2.520, 0.0)
    mim_ac.labels.clear()
    mim_ac_fx = pi5.flip_x_cell(mim_ac)

    x_cmix = 95.600   # M3 [93.27..97.93], C2(vss) at 97.670
    x_cac  = 101.400  # M3 [98.62..104.18], C2(mixp) at 98.880
    y_mim  = +5.250
    half.include(mim_mix,   dx=x_cmix, dy=y_mim)
    half.include(mim_ac_fx, dx=x_cac,  dy=y_mim)

    x_cmix_vss = grid(x_cmix + c2_mix_rel[0])  # 97.670
    half.wire("metal3", [(x_cmix_vss, grid(y_mim + 1.350)), (x_cmix_vss, +y_vss_ch)], 0.520)
    via2_clean(half, x_cmix_vss, +y_vss_ch)
    via1_clean(half, x_cmix_vss, +y_vss_ch)

    # Stitch `mixp`
    x_cac_c2 = grid(x_cac - c2_ac_rel[0])  # 98.880
    via2_clean(half, r16_r2_x, y_mim)
    half.wire("metal3", [(grid(x_cac + 2.600), y_mim), (r16_r2_x, y_mim)], 0.520)
    y_mix_m4 = +8.500
    half.wire("metal4", [
        (grid(x_cmix - 0.500), grid(y_mim + 1.250)),
        (grid(x_cmix - 0.500), y_mix_m4),
        (x_cac_c2, y_mix_m4),
        (x_cac_c2, grid(y_mim + 1.700)),
    ], 0.440)

    # Escape `acp` EAST from Xcac.C1 M4 top plate to x_ac_drop = 106.600
    y_ac_bus = +8.500
    x_ac_drop = 106.600
    half.wire("metal4", [
        (grid(x_cac + 1.300), grid(y_mim + 1.700)),
        (grid(x_cac + 1.300), y_ac_bus),
        (x_ac_drop, y_ac_bus),
    ], 0.440)
    via3_pad(half, x_ac_drop, y_ac_bus)
    via2_clean(half, x_ac_drop, y_ac_bus)

    # 5. Stage 5 TOP: Xip (1.65/6.60 nfn=1 nfp=4) and Xr2 (2.60/10.40 nfn=2 nfp=4)
    y_vdd_r = +2.400
    y_p_r   = +4.400
    y_gc_r  = +6.400
    y_n_r   = +8.100
    y_vss_r = +y_vss_ch  # +10.500

    x_xip   = 111.600
    x_xr2   = 115.400
    x_vdd_e = 117.600
    x_out_e = 119.000
    half.rect("nwell", 109.900, +1.850, 117.400, +6.150)
    draw_tap_h(half, "nsubdiff", 110.200, 117.200, y_vdd_r, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)
    half.wire("metal1", [(x_mix_r, y_vss_r), (109.900, y_vss_r)], 0.460)
    draw_tap_h(half, "psubdiff", 109.900, 118.400, y_vss_r, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)

    xip = pi5.draw_cmos_inv(
        half, cache, x_xip, 1.65, 6.60, N_LVT, P_LVT, 0.15, 0.35, 1, 4,
        y_p_r, y_n_r, y_gc_r, y_vdd_r, y_vss_r,
    )
    xr2 = pi5.draw_cmos_inv(
        half, cache, x_xr2, 2.60, 10.40, N_LVT, P_LVT, 0.15, 0.35, 2, 4,
        y_p_r, y_n_r, y_gc_r, y_vdd_r, y_vss_r,
    )

    via1_clean(half, xip["out"][0], y_gc_r)
    via1_clean(half, xr2["in"][0], y_gc_r)
    half.wire("metal2", [(xip["out"][0], y_gc_r), (xr2["in"][0], y_gc_r)], 0.320)

    via1_clean(half, xr2["out"][0], y_gc_r)
    via2_clean(half, xr2["out"][0], y_gc_r)
    half.wire("metal3", [(xr2["out"][0], y_gc_r), (x_out_e, y_gc_r)], 0.400)

    draw_tap_h(half, "psubdiff", 14.500, x_mix_l, +y_vss_ch, half_w=0.175, with_m1=True, m1_w=0.360, viali_pitch=1.20)
    half.wire("metal1", [(41.800, +2.400), (43.250, +2.400), (43.250, 0.000), (x_mix_l, 0.000)], 0.440)
    half.wire("metal1", [(41.700, +8.800), (x_vdd_w_ch, +8.800), (x_vdd_w_ch, +5.250), (x_mix_l, +5.250)], 0.360)

    # Include `half` BOTH normal (+y) AND mirror_y (-y)!
    ch.include(half, dx=0.0, dy=0.0, mirror_y=False)
    ch.include(half, dx=0.0, dy=0.0, mirror_y=True)

    # 180-deg point-symmetric vertical r2 connections (`acp/acn` & `r1p/r1n`)
    ch.wire("metal2", [(x_ac_drop, +y_ac_bus), (109.600, +y_ac_bus), (109.600, +y_gc_r), (x_xip, +y_gc_r)], 0.300)
    ch.wire("metal2", [(x_r2_w, +y_ac_bus), (x_r2_w, y_r2_hi)], 0.300)
    via1_clean(ch, x_r2_w, y_r2_hi)
    via1_clean(ch, x_xip, +y_gc_r)

    ch.wire("metal2", [(x_ac_drop, -y_ac_bus), (109.600, -y_ac_bus), (109.600, -y_gc_r), (x_xip, -y_gc_r)], 0.300)
    ch.wire("metal2", [(x_r2_e, -y_ac_bus), (x_r2_e, y_r2_lo)], 0.300)
    via1_clean(ch, x_r2_e, y_r2_lo)
    via1_clean(ch, x_xip, -y_gc_r)

    x_r1_tap = grid(xip["out"][0] + 0.800)  # 113.040
    ch.wire("metal2", [(x_r1_tap, +y_gc_r), (x_r1_tap, +1.200)], 0.300)
    via2_clean(ch, x_r1_tap, +1.200)
    ch.wire("metal3", [(x_r2_w, +1.200), (x_r1_tap, +1.200)], 0.360)
    via2_clean(ch, x_r2_w, +1.200)
    ch.wire("metal2", [(x_r2_w, +1.200), (x_r2_w, y_r2_lo)], 0.300)
    via1_clean(ch, x_r2_w, y_r2_lo)

    ch.wire("metal2", [(x_r1_tap, -y_gc_r), (x_r1_tap, -1.200)], 0.300)
    via2_clean(ch, x_r1_tap, -1.200)
    ch.wire("metal3", [(x_r2_e, -1.200), (x_r1_tap, -1.200)], 0.360)
    via2_clean(ch, x_r2_e, -1.200)
    ch.wire("metal2", [(x_r2_e, -1.200), (x_r2_e, y_r2_hi)], 0.300)
    via1_clean(ch, x_r2_e, y_r2_hi)

    for yv in (-y_vdd_r, +y_vdd_r):
        ch.wire("metal1", [(117.200, yv), (x_vdd_e, yv)], 0.440)
        via1_clean(ch, x_vdd_e, yv)
        via2_clean(ch, x_vdd_e, yv)
        via3_pad(ch, x_vdd_e, yv)
    ch.wire("metal4", [(x_vdd_e, -y_vdd_r), (x_vdd_e, +y_vdd_r)], 0.560)

    for yv in (-8.800, +8.800):
        via1_clean(ch, x_vdd_w_ch, yv)
        via2_clean(ch, x_vdd_w_ch, yv)
        via3_pad(ch, x_vdd_w_ch, yv)
    ch.wire("metal4", [(x_vdd_w_ch, -8.800), (x_vdd_w_ch, +8.800)], 0.560)

    # Central 2.5 GHz Clock Channels for Xmap/Xman (`e0..e3`) and Xmbp/Xmbn (`o0..o3`)
    # Low-C wide-pitch lean 0.30 um M3 tracks (1.06 um pitch -> 0.76 um space!)
    clk_ys = [+1.590, +0.530, -0.530, -1.590]
    for mx_base, x_l_bus, x_r_bus, w_clk_m3 in (
        (mux_a, 14.000, 25.400, 0.300),
        (mux_b, 29.800, 41.200, 0.300),
    ):
        for yt in clk_ys:
            ch.wire("metal3", [(x_l_bus, yt), (x_r_bus, yt)], w_clk_m3)
        for k in range(4):
            xl = mx_base["tgs"][k]["x_l"]
            yt_top = clk_ys[k]
            via1_clean(ch, xl, +3.450)
            ch.wire("metal2", [(xl, +3.450), (xl, yt_top)], 0.280)
            via2_clean(ch, xl, yt_top)
            yt_bot = clk_ys[(k + 2) % 4]
            xl_b = grid(xl - 0.520)
            ch.wire("metal1", [(xl, -3.450), (xl_b, -3.450)], 0.290)
            via1_clean(ch, xl_b, -3.450)
            ch.wire("metal2", [(xl_b, -3.450), (xl_b, yt_bot)], 0.280)
            via2_clean(ch, xl_b, yt_bot)

    # Fly `o0..o3` strictly OUTSIDE `mux_m` (y_m=+-6.73) AND clear of y_vss_ch=+-10.50 via3 pads: [+-8.45, +-9.45]!
    # Eliminates 100% of M2-M3 parallel-plate overlap between `o_fly_ys` and `Xmap/Xman`'s high-Z `m` node!
    o_fly_ys = [+9.450, +8.450, -8.450, -9.450]
    o_jmp_xs = [26.800, 27.680, 28.560, 29.440]
    for k in range(4):
        yf = o_fly_ys[k]
        xj = o_jmp_xs[k]
        yc = clk_ys[k]
        ch.wire("metal3", [(14.000, yf), (xj, yf)], 0.300)
        via3_pad(ch, xj, yf)
        ch.wire("metal4", [(xj, yf), (xj, yc)], 0.300)
        via3_pad(ch, xj, yc)
        ch.wire("metal3", [(xj, yc), (29.800, yc)], 0.300)

    sel_a_m4: list[tuple[float, float]] = []
    sel_b_m4: list[tuple[float, float]] = []
    for mx_base, out_list in ((mux_a, sel_a_m4), (mux_b, sel_b_m4)):
        for k in range(4):
            cx = mx_base["tgs"][k]["gp"][0]
            xm_s  = grid(cx)
            xm_sb = grid(cx + 0.960)
            out_list.append((xm_s, xm_sb))
            for sgn_y in (+1.0, -1.0):
                y_gn_c = grid(sgn_y * 4.700)
                y_s_v  = grid(sgn_y * 3.300)
                via1_clean(ch, cx, y_gn_c)
                ch.wire("metal2", [(cx, y_gn_c), (xm_s, y_s_v)], W_M2)
                via2_clean(ch, xm_s, y_s_v)
                via3_pad(ch, xm_s, y_s_v)
                y_gp_c = grid(sgn_y * 5.600)
                via1_clean(ch, cx, y_gp_c)
                ch.wire("metal2", [(cx, y_gp_c), (xm_sb, y_gp_c)], W_M2)
                via2_clean(ch, xm_sb, y_gp_c)
                via3_pad(ch, xm_sb, y_gp_c)
            ch.wire("metal4", [(xm_s, -3.300), (xm_s, +3.300)], 0.360)
            ch.wire("metal4", [(xm_sb, -5.600), (xm_sb, +5.600)], 0.360)

    for k in range(8):
        yk = 0.550 if (k % 2 == 0) else 9.950
        ch.wire("metal4", [(f_m4_xs[k], -yk), (f_m4_xs[k], +yk)], 0.360)
        ch.wire("metal4", [(fb_m4_xs[k], -yk), (fb_m4_xs[k], +yk)], 0.360)

    meta = {
        "e_ys": clk_ys,
        "o_ys": o_fly_ys,
        "clk_in_x": 14.000,
        "sel_a_m4": sel_a_m4,
        "sel_b_m4": sel_b_m4,
        "f_m4_xs": f_m4_xs,
        "fb_m4_xs": fb_m4_xs,
        "on_pt": (x_out_e, +y_gc_r),
        "op_pt": (x_out_e, -y_gc_r),
        "xr2_out_x": xr2["out"][0],
        "vdd_m4_w": x_vdd_w_ch,
        "vdd_m4_e": x_vdd_e,
        "vss_e_x": 118.600,
        "vss_ys": [-y_vss_ch, 0.000, +y_vss_ch],
        "y_vss_ch": y_vss_ch,
    }
    return ch, meta


# ---------------------------------------------------------------------------
# 2B. Hardened v2 5G 4-Phase `pi4_diff_chan` (AC-coupled Hybrid-PMOS Mux +
#     High-f_T SVT-P Slice + 2-Stage Triode+CC Diff Rec + Direct Hybrid-PMOS Xr2)
# ---------------------------------------------------------------------------

def draw_hyb_inv(
    c: Cell,
    cache: PdkCache,
    cx: float,
    wn: float,
    wps: float,
    wpl: float,
    nfn: int,
    nfps: int,
    nfpl: int,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
    x_ps: float | None = None,
    x_pl: float | None = None,
    x_n: float | None = None,
    x_out_off: float = 0.640,
) -> dict:
    """Draw 100% M1-only Composite Hybrid-PMOS inverter (`pi4_inv_hyb`: SVT-P l=0.15 || LVT-P l=0.35 + LVT-N l=0.15).

    Enforces >= 0.39 um pdiff-to-pdiff spacing (~1.00 um gate-to-gate >> 0.415 um SKY130 lvtn.3b).
    """
    cx = grid(cx)
    x_ps = grid(cx if x_ps is None else x_ps)
    x_n  = grid(cx if x_n is None else x_n)
    if x_pl is None:
        m_ps, _ = cache.build_mos(P_STD, grid(wps / nfps), 0.15, nfps, 0.0, True)
        m_pl, _ = cache.build_mos(P_LVT, grid(wpl / nfpl), 0.35, nfpl, 0.0, True)
        x_pl = grid(x_ps + m_ps.bbox()[2] - m_pl.bbox()[0] + 0.400)
    else:
        x_pl = grid(x_pl)

    hps = grid((wps / nfps) / 2.0)
    hpl = grid((wpl / nfpl) / 2.0)
    hn  = grid((wn  / nfn)  / 2.0)
    sgn_p = 1.0 if y_vdd > y_p else -1.0
    sgn_n = 1.0 if y_vss > y_n else -1.0
    off_p = grid(max(0.240, min(0.450, min(hps, hpl) - 0.160)))
    off_n = grid(max(0.240, min(0.350, hn - 0.140)))
    sp_y = grid(y_p + sgn_p * off_p)
    dp_y = grid(y_p - sgn_p * off_p)
    sn_y = grid(y_n + sgn_n * off_n)
    dn_y = grid(y_n - sgn_n * off_n)

    pms = pi5.place_mos_col(c, cache, x_ps, P_STD, wps, 0.15, nfps, y_p, True,  y_g, sp_y, dp_y)
    pml = pi5.place_mos_col(c, cache, x_pl, P_LVT, wpl, 0.35, nfpl, y_p, True,  y_g, sp_y, dp_y)
    nm  = pi5.place_mos_col(c, cache, x_n,  N_LVT, wn,  0.15, nfn,  y_n, False, y_g, sn_y, dn_y)

    # Tie all PMOS sources straight to y_vdd and NMOS sources straight to y_vss on M1
    for sx in pms["s_xs"] + pml["s_xs"]:
        c.wire("metal1", [(sx, sp_y), (sx, y_vdd)], 0.220)
    for sx in nm["s_xs"]:
        c.wire("metal1", [(sx, sn_y), (sx, y_vss)], 0.220)

    # Tie all 3 gates together along y_g on M1
    gx_lo = min(x_ps, x_pl, x_n)
    gx_hi = max(x_ps, x_pl, x_n)
    if gx_hi - gx_lo > 0.005:
        c.wire("metal1", [(gx_lo, grid(y_g)), (gx_hi, grid(y_g))], W_M1)

    # Tie all drains together on M1 with vertical drop strictly East of pml gate pad
    x_drn = grid(max(
        x_pl + x_out_off,
        max(pml["d_xs"]) + 0.320,
        max(nm["d_xs"]) + 0.320,
    ))
    all_pd_xs = pms["d_xs"] + pml["d_xs"]
    c.rect("metal1", grid(min(all_pd_xs) - 0.09), grid(dp_y - 0.145),
           grid(max(max(all_pd_xs), x_drn) + 0.09), grid(dp_y + 0.145))
    c.rect("metal1", grid(min(nm["d_xs"]) - 0.09), grid(dn_y - 0.145),
           grid(max(max(nm["d_xs"]), x_drn) + 0.09), grid(dn_y + 0.145))
    c.wire("metal1", [(x_drn, dp_y), (x_drn, dn_y)], W_M1)

    return {
        "in": (x_n, grid(y_g)),
        "out": (x_drn, grid(y_g)),
        "dp": (pml["d"][-1] if isinstance(pml["d"], list) else pml["d"][0], dp_y),
        "dn": (nm["d"][0], dn_y),
        "pms": pms,
        "pml": pml,
        "nm": nm,
    }


def _draw_tgate_v2_col(
    c: Cell,
    cache: PdkCache,
    cx: float,
    wn: float,
    wp: float,
    y_p: float,
    y_n: float,
    y_gp: float,
    y_gn: float,
    s_on_left: bool = True,
    nfn: int = 1,
    nfp: int = 1,
) -> dict:
    """DRC-clean LVT transmission gate supporting `wn=1.50 nfn=2` (enforces >= 0.18 um M1 s-d gap)."""
    cx = grid(cx)
    hp = grid((wp / nfp) / 2.0)
    hn = grid((wn / nfn) / 2.0)
    sp_y = grid(y_p + min(0.45 if nfp > 1 else 0.28, max(0.0, hp - 0.16)))
    dp_y = grid(y_p - min(0.45 if nfp > 1 else 0.28, max(0.0, hp - 0.16)))
    off_n = 0.240 if nfn > 1 else 0.000
    sn_y = grid(y_n - off_n)
    dn_y = grid(y_n + off_n)

    pm = pi5.place_mos_col(c, cache, cx, P_LVT, wp, 0.35, nfp, y_p, True, y_gp, sp_y, dp_y)
    nm = pi5.place_mos_col(c, cache, cx, N_LVT, wn, 0.15, nfn, y_n, False, y_gn, sn_y, dn_y)

    if nfp == 1 and nfn == 1:
        x_l = grid(cx - 0.560)
        x_r = grid(cx + 0.560)
        c.rect("metal1", grid(x_l - 0.09), grid(sp_y - 0.145), grid(pm["s"][0] + 0.145), grid(sp_y + 0.145))
        c.rect("metal1", grid(x_l - 0.09), grid(sn_y - 0.145), grid(nm["s"][0] + 0.145), grid(sn_y + 0.145))
        c.wire("metal1", [(x_l, sn_y), (x_l, sp_y)], W_M1)
        c.rect("metal1", grid(pm["d"][0] - 0.145), grid(dp_y - 0.145), grid(x_r + 0.09), grid(dp_y + 0.145))
        c.rect("metal1", grid(nm["d"][0] - 0.145), grid(dn_y - 0.145), grid(x_r + 0.09), grid(dn_y + 0.145))
        c.wire("metal1", [(x_r, dn_y), (x_r, dp_y)], W_M1)
    else:
        x_l = grid(min(pm["s_xs"][0], nm["s_xs"][0]))
        x_r = grid(cx + 0.500)
        c.rect("metal1", grid(x_l - 0.09), grid(sp_y - 0.145), grid(pm["s_xs"][0] + 0.145), grid(sp_y + 0.145))
        c.rect("metal1", grid(x_l - 0.09), grid(sn_y - 0.145), grid(nm["s_xs"][0] + 0.145), grid(sn_y + 0.145))
        c.wire("metal1", [(x_l, sn_y), (x_l, sp_y)], W_M1)
        c.rect("metal1", grid(pm["d"][0] - 0.145), grid(dp_y - 0.145), grid(x_r + 0.09), grid(dp_y + 0.145))
        c.rect("metal1", grid(nm["d"][0] - 0.145), grid(dn_y - 0.145), grid(x_r + 0.09), grid(dn_y + 0.145))
        c.wire("metal1", [(x_r, dn_y), (x_r, dp_y)], W_M1)

    return {
        "a": (x_l, grid((sn_y + sp_y) / 2.0)) if s_on_left else (x_r, grid((dn_y + dp_y) / 2.0)),
        "b": (x_r, grid((dn_y + dp_y) / 2.0)) if s_on_left else (x_l, grid((sn_y + sp_y) / 2.0)),
        "x_l": x_l,
        "x_r": x_r,
        "gp": pm["g"],
        "gn": nm["g"],
        "sp_y": sp_y,
        "dp_y": dp_y,
        "sn_y": sn_y,
        "dn_y": dn_y,
    }


def _draw_pi4_mux4_v2_half(c: Cell, cache: PdkCache, x0: float, x_out: float) -> dict:
    """Draw 1 v2 `pi4_mux4_tg` FET group in top half (+y):
      4x pi4_tgate_lvt(wn=1.50 nfn=2, wp=4.60 nfp=2) at x0 + k*1.94
      1x pi4_inv_hyb(wn=3.40 nfn=2, wps=11.20 nfps=4, wpl=5.60 nfpl=2) centered around x_out
    """
    x0, x_out = grid(x0), grid(x_out)
    y_vss = +2.400
    y_n   = +3.550
    y_gn  = +4.650
    y_gc  = +5.100
    y_gp  = +5.550
    y_p   = +7.250
    y_vdd = +8.950

    tgs = []
    for k in range(4):
        cx = grid(x0 + k * 1.940)
        tg = _draw_tgate_v2_col(c, cache, cx, 1.50, 4.60, y_p, y_n, y_gp, y_gn, s_on_left=True, nfn=2, nfp=2)
        tgs.append(tg)

    # Composite Hybrid-PMOS Xout at y_p_inv=+7.000, y_n_inv=+3.750; align Xn under Xps (ZERO poly.2!)
    inv = draw_hyb_inv(
        c, cache, x_out, 3.40, 11.20, 5.60, 2, 4, 2,
        y_p=+7.000, y_n=+3.750, y_g=y_gc, y_vdd=y_vdd, y_vss=y_vss,
        x_ps=grid(x_out - 0.900), x_pl=grid(x_out + 1.380), x_n=grid(x_out - 0.900), x_out_off=0.640,
    )
    inv["in"] = (x_out, y_gc)

    # Common mux node `m`: horizontal M2 bar at y_m = +7.900 (NORTH of ma +7.350 -> ZERO m/ma crossing!)
    y_m = +7.900
    for tg in tgs:
        via1_clean(c, tg["x_r"], tg["dp_y"])
        c.wire("metal2", [(tg["x_r"], tg["dp_y"]), (tg["x_r"], y_m)], 0.280)
    c.wire("metal2", [(tgs[0]["x_r"], y_m), (tgs[-1]["x_r"], y_m)], 0.300)

    return {
        "tgs": tgs,
        "m_end": (tgs[-1]["x_r"], y_m),
        "in": inv["in"],
        "out": (inv["out"][0], y_gc),
        "y_gn": y_gn,
        "y_gp": y_gp,
        "y_gc": y_gc,
    }


def _draw_pi4_slice_r_v2_fets(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_vss: float,
    y_vdd: float,
) -> dict:
    """DRC-clean v2 `pi4_slice_r` FET cell (TGs 0.65/2.10 LVT, Xinv & Xdum 0.70 LVT-N / 3.40 SVT-P l=0.15 nf=2)."""
    x0 = grid(x0)
    sgn = +1.0 if y_vdd > y_vss else -1.0
    y_n  = grid(y_vss + sgn * 0.830)
    y_gn = grid(y_vss + sgn * 1.540)
    y_gc = grid(y_vss + sgn * 1.950)
    y_gp = grid(y_vss + sgn * 2.350)
    y_p  = grid(y_vss + sgn * 3.750)

    xs = [grid(x0 + dx) for dx in (0.000, 2.020, 3.880, 5.820, 7.720, 9.650)]

    xsa = _draw_tgate_v2_col(c, cache, xs[0], 0.65, 2.10, y_p, y_n, y_gp, y_gn, s_on_left=True, nfn=1, nfp=1)
    xdb = _draw_tgate_v2_col(c, cache, xs[1], 0.65, 2.10, y_p, y_n, y_gp, y_gn, s_on_left=True, nfn=1, nfp=1)
    xsb = _draw_tgate_v2_col(c, cache, xs[3], 0.65, 2.10, y_p, y_n, y_gp, y_gn, s_on_left=True, nfn=1, nfp=1)
    xda = _draw_tgate_v2_col(c, cache, xs[4], 0.65, 2.10, y_p, y_n, y_gp, y_gn, s_on_left=True, nfn=1, nfp=1)

    # Col 2: Xdum (gate = dum, d = s = vdd / vss, N_LVT 0.70/0.15 nf=1 + P_STD 3.40/0.15 nf=2)
    dp_m = pi5.place_mos_col(c, cache, xs[2], P_STD, 3.40, 0.15, 2, y_p, True, y_gc,
                             grid(y_p + sgn * 0.45), grid(y_p - sgn * 0.45))
    dn_m = pi5.place_mos_col(c, cache, xs[2], N_LVT, 0.70, 0.15, 1, y_n, False, y_gc,
                             grid(y_n - sgn * 0.16), grid(y_n + sgn * 0.16))
    for sx in dp_m["s_xs"]:
        c.wire("metal1", [(sx, dp_m["s"][1]), (sx, y_vdd)], 0.220)
    for dx in dp_m["d_xs"]:
        c.wire("metal1", [(dx, dp_m["d"][1]), (dx, y_vdd)], 0.220)
    for pt in (dn_m["s"], dn_m["d"]):
        c.wire("metal1", [(pt[0], pt[1]), (pt[0], y_vss)], 0.220)

    # Col 5: Xinv (sel -> drv, N_LVT 0.70/0.15 nf=1 + P_STD 3.40/0.15 nf=2)
    xinv = draw_oct_inv(
        c, cache, xs[5], 0.70, 3.40, N_LVT, P_STD, 0.15, 0.15, 1, 2,
        y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=0.480,
    )

    ym_dum = grid(y_vss + sgn * 1.080)
    ym_gn  = y_gn
    ym_gp  = y_gp
    ym_fbb = grid(y_vss + sgn * 2.950)
    ym_sel = grid(y_vss + sgn * 3.950)

    # 1. `sel` on M2 at ym_sel: xsa.x_r, xsb.x_r, xinv.in
    x_sel_in = grid(xs[5] - 0.980)
    c.wire("metal1", [(xinv["in"][0], xinv["in"][1]), (x_sel_in, xinv["in"][1]), (x_sel_in, ym_sel)], W_M1)
    c.wire("metal1", [(xsa["x_r"], xsa["dp_y"]), (xsa["x_r"], ym_sel)], 0.320)
    c.wire("metal1", [(xsb["x_r"], xsb["dp_y"]), (xsb["x_r"], ym_sel)], 0.320)
    for px in (xsa["x_r"], xsb["x_r"], x_sel_in):
        via1_clean(c, px, ym_sel)
    c.wire("metal2", [(xsa["x_r"], ym_sel), (x_sel_in, ym_sel)], W_M2)

    # 2. `dum` on M2 at ym_dum: xdb.x_r, xdum.g, xda.x_r
    x_dum_in = grid(xs[2] - 0.720)
    c.wire("metal1", [(xs[2], y_gc), (x_dum_in, y_gc), (x_dum_in, ym_dum)], W_M1)
    c.wire("metal1", [(xdb["x_r"], xdb["dn_y"]), (xdb["x_r"], ym_dum)], 0.300)
    c.wire("metal1", [(xda["x_r"], xda["dn_y"]), (xda["x_r"], ym_dum)], 0.300)
    for px in (xdb["x_r"], x_dum_in, xda["x_r"]):
        via1_clean(c, px, ym_dum)
    c.wire("metal2", [(xdb["x_r"], ym_dum), (xda["x_r"], ym_dum)], 0.300)

    # 3. `f`
    x_f_x = grid(xs[2] + 0.860)
    y_tap_m1 = grid(y_vss + sgn * 0.550)
    via1_clean(c, xsa["gp"][0], ym_gp)
    via1_clean(c, xdb["gp"][0], ym_gp)
    via1_clean(c, x_f_x, ym_gp)
    c.wire("metal2", [(xsa["gp"][0], ym_gp), (x_f_x, ym_gp)], W_M2)
    c.wire("metal1", [(x_f_x, ym_gp), (x_f_x, y_tap_m1)], W_M1)
    via1_clean(c, x_f_x, ym_gn)
    via1_clean(c, xsb["gn"][0], ym_gn)
    via1_clean(c, xda["gn"][0], ym_gn)
    c.wire("metal2", [(x_f_x, ym_gn), (xda["gn"][0], ym_gn)], W_M2)
    via1_clean(c, x_f_x, y_tap_m1)

    # 4. `fb`
    x_fb_l = grid(xs[0] + 1.010)
    x_fb_r = grid(xs[3] + 0.950)
    via1_clean(c, xsa["gn"][0], ym_gn)
    via1_clean(c, x_fb_l, ym_gn)
    via1_clean(c, xdb["gn"][0], ym_gn)
    c.wire("metal2", [(xsa["gn"][0], ym_gn), (xdb["gn"][0], ym_gn)], W_M2)
    c.wire("metal1", [(x_fb_l, y_tap_m1), (x_fb_l, ym_fbb)], W_M1)
    via1_clean(c, x_fb_l, y_tap_m1)
    via1_clean(c, x_fb_l, ym_fbb)
    via1_clean(c, x_fb_r, ym_fbb)
    c.wire("metal2", [(x_fb_l, ym_fbb), (x_fb_r, ym_fbb)], W_M2)
    c.wire("metal1", [(x_fb_r, ym_fbb), (x_fb_r, ym_gp)], W_M1)
    via1_clean(c, xsb["gp"][0], ym_gp)
    via1_clean(c, x_fb_r, ym_gp)
    via1_clean(c, xda["gp"][0], ym_gp)
    c.wire("metal2", [(xsb["gp"][0], ym_gp), (xda["gp"][0], ym_gp)], W_M2)

    # Extend ca/cb M1 pins toward y_vdd (+4.45 / +6.05) with solid M1 bar
    y_bridge = grid(y_vdd - sgn * 0.800)
    for xl in (xsa["x_l"], xdb["x_l"], xsb["x_l"], xda["x_l"]):
        ya, yb = sorted((grid(xsa["sp_y"]), y_bridge))
        c.rect("metal1", grid(xl - 0.145), grid(ya - 0.145), grid(xl + 0.385), grid(yb + 0.145))

    return {
        "ca_xs": [xsa["x_l"], xda["x_l"]],
        "cb_xs": [xdb["x_l"], xsb["x_l"]],
        "f_tap": (x_f_x, y_tap_m1),
        "fb_tap": (x_fb_l, y_tap_m1),
        "drv_x": xinv["out"][0],
        "drv_y_lo": min(xinv["dp"][1], xinv["dn"][1]),
        "drv_y_hi": max(xinv["dp"][1], xinv["dn"][1]),
        "x_end": grid(xs[5] + 0.850),
    }


def _build_pi4_diff_chan_v2_cell(cache: PdkCache) -> tuple[Cell, dict]:
    """Build ONE mathematically Y-mirror symmetric v2 `pi4_diff_chan` centered at y = 0.0 (exact same East x=119.00)."""
    ch = Cell()
    half = Cell()
    y_vss_ch = 10.500

    # --- Shared symmetric resistor banks (centered at y = 0.0) ---
    # All three self-bias resistor pairs use l = 6.5 um (pins at y = +-5.155, guard at y = +-5.895)
    r2_l6p5 = cache.device(R_0P35, dict(l=6.5, nx=2, m=1, guard=1))
    r2_l6p5.labels.clear()
    y_r2_pin = 5.155
    y_r2_g   = 5.895
    r16 = pi5.rot90_cell(cache.device(R_0P69, dict(l=2.2, nx=16, m=1, guard=1)))
    r16.labels.clear()

    x_rm_a = 19.700
    x_rm_b = 37.200
    x_r16_c = 95.150
    r16_r1_x = grid(x_r16_c - 3.005)   # 92.145 (exact same West head X!)
    r16_r2_x = grid(x_r16_c + 3.005)   # 98.155
    r16_top_ys = [grid(0.585 + k * 1.170) for k in range(8)]
    x_r2_1 = 102.700

    ch.include(r2_l6p5, dx=x_rm_a, dy=0.0)
    ch.include(r2_l6p5, dx=x_rm_b, dy=0.0)
    ch.include(r16,     dx=x_r16_c, dy=0.0)
    ch.include(r2_l6p5, dx=x_r2_1, dy=0.0)

    # Tie all resistor guard rings cleanly to vss rails
    for xg_tie in (grid(x_r16_c - 3.745), grid(x_r16_c + 3.745)):
        for yt in (-9.500, 0.000, +9.500):
            viali_pad(ch, xg_tie, yt)
        ch.wire("metal1", [(xg_tie, -y_vss_ch), (xg_tie, +y_vss_ch)], 0.340)
    for yt_r2 in (-y_r2_g, +y_r2_g):
        viali_pad(ch, x_r2_1, yt_r2)
    ch.wire("metal1", [(x_r2_1, +y_r2_g), (x_r2_1, +y_vss_ch)], 0.340)
    ch.wire("metal1", [(x_r2_1, -y_r2_g), (x_r2_1, -y_vss_ch)], 0.340)

    # Pre-build MIM caps (Xcmix 1.6x1.6, Xcm 4.3x4.2, Xcp1 4.8x4.8; Stage-3 MIM removed!)
    mim_1p6 = cache.device(MIM1, dict(w=1.6, l=1.6, nx=1, ny=1, stack=0, doports=1))
    c2_mix_dx = mim_1p6.pins("C2")[0][0]   # +1.470
    mim_1p6.labels.clear()

    mim_4p3 = cache.device(MIM1, dict(w=4.3, l=4.2, nx=1, ny=1, stack=0, doports=1))
    mim_4p3.labels.clear()

    mim_4p8 = cache.device(MIM1, dict(w=4.8, l=4.8, nx=1, ny=1, stack=0, doports=1))
    c2_4p8_dx = mim_4p8.pins("C2")[0][0]   # +3.070
    mim_4p8.labels.clear()
    mim_4p8_fx = pi5.flip_x_cell(mim_4p8)

    # =========================================================================
    # 1. Stage 1 TOP: AC-Coupled Self-Biased Hybrid-PMOS `Xmap` & `Xmbp`
    # =========================================================================
    x_mux_a = 11.400
    x_out_a = 23.550
    x_cm_a  = 21.750
    x_mux_b = 28.900
    x_out_b = 41.050
    x_cm_b  = 39.250
    y_cm_s1 = +5.250
    x_vdd_w_ch = 45.250

    for nw_l, nw_r in ((10.400, 18.200), (21.250, 26.350), (27.900, 35.700)):
        half.rect("nwell", nw_l, +5.300, nw_r, +9.450)
        draw_tap_h(half, "nsubdiff", grid(nw_l + 0.20), grid(nw_r - 0.20), +8.950,
                   half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.20)
        draw_tap_h(half, "psubdiff", grid(nw_l + 0.20), grid(nw_r - 0.20), +2.400,
                   half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.20)
    # Xout_b nwell merges flush into Stage-2 nwell at +8.700; upper +8.70..+9.45 stops at 42.70 (>=1.35 um nwell.2a!)
    half.rect("nwell", 38.750, +5.300, 44.250, +8.700)
    half.rect("nwell", 38.750, +8.700, 42.700, +9.450)
    draw_tap_h(half, "nsubdiff", 38.950, 42.500, +8.950, half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.20)
    draw_tap_h(half, "psubdiff", 38.950, 43.150, +2.400, half_w=0.175, with_m1=True, m1_w=0.440, viali_pitch=1.20)
    half.wire("metal1", [(10.600, +8.950), (43.850, +8.950)], 0.440)
    half.wire("metal1", [(10.600, +2.400), (43.800, +2.400)], 0.440)
    for xr2_g in (grid(x_rm_a - 1.155), grid(x_rm_a + 1.155), grid(x_rm_b - 1.155), grid(x_rm_b + 1.155)):
        viali_pad(half, xr2_g, +2.400)

    mux_a = _draw_pi4_mux4_v2_half(half, cache, x_mux_a, x_out_a)
    mux_b = _draw_pi4_mux4_v2_half(half, cache, x_mux_b, x_out_b)

    half.include(mim_4p3, dx=x_cm_a, dy=y_cm_s1)
    half.include(mim_4p3, dx=x_cm_b, dy=y_cm_s1)

    for mx, x_cm, x_out in ((mux_a, x_cm_a, x_out_a), (mux_b, x_cm_b, x_out_b)):
        x_m_v2 = grid(x_cm + 2.800)
        y_m = mx["m_end"][1]
        half.wire("metal2", [mx["m_end"], (x_m_v2, y_m), (x_m_v2, +7.000)], 0.280)
        via2_clean(half, x_m_v2, +7.000)

        x_ma_m4 = grid(x_cm + 0.300)
        y_ma_drop = +1.350
        half.wire("metal4", [(x_ma_m4, y_cm_s1), (x_ma_m4, y_ma_drop)], 0.400)
        via3_pad(half, x_ma_m4, y_ma_drop)
        via2_clean(half, x_ma_m4, y_ma_drop)
        half.wire("metal2", [
            (x_ma_m4, y_ma_drop),
            (x_ma_m4, mx["in"][1]),
            (x_out, mx["in"][1]),
            (x_out, +7.350),
        ], 0.280)
        via1_clean(half, x_out, mx["in"][1])

    # =========================================================================
    # 2. Stage 2 TOP: 8x v2 `pi4_slice_r` (DRC-clean 11.20 um pitch)
    # =========================================================================
    slice_xs = [grid(45.100 + c_idx * 11.200) for c_idx in range(4)]
    x_mix_l = grid(slice_xs[0] - 0.800)    # 44.300
    x_mix_r = grid(slice_xs[-1] + 10.450)  # 89.150
    half.rect("nwell", 44.050, +2.150, grid(x_mix_r + 0.50), +8.700)
    draw_tap_h(half, "nsubdiff", x_mix_l, x_mix_r, +5.250, half_w=0.175, with_m1=True, m1_w=0.300, viali_pitch=1.20)
    draw_tap_h(half, "psubdiff", 10.800, x_mix_r, +y_vss_ch, half_w=0.175, with_m1=True, m1_w=0.360, viali_pitch=1.20)
    draw_tap_h(ch,   "psubdiff", x_mix_l, x_mix_r, 0.000, half_w=0.175, with_m1=True, m1_w=0.360, viali_pitch=1.20)
    half.wire("metal1", [(43.800, +2.400), (43.800, 0.000), (x_mix_l, 0.000)], 0.440)
    half.wire("metal1", [(43.850, +8.950), (43.850, +5.250), (x_mix_l, +5.250)], 0.280)

    slices_top: dict[int, dict] = {}
    for col_i, sx in enumerate(slice_xs):
        slices_top[2 * col_i]     = _draw_pi4_slice_r_v2_fets(half, cache, sx, y_vss=0.000,    y_vdd=+5.250)
        slices_top[2 * col_i + 1] = _draw_pi4_slice_r_v2_fets(half, cache, sx, y_vss=+y_vss_ch, y_vdd=+5.250)

    y_ca = +4.450
    y_cb = +6.050
    x_ca_fly_l = 29.000
    x_ca_drop  = 43.820
    y_ca_fly   = +8.850
    x_cb_via2  = 43.250

    via1_clean(half, mux_a["out"][0], mux_a["out"][1])
    half.wire("metal2", [
        mux_a["out"],
        (mux_a["out"][0], +8.350),
        (x_ca_fly_l, +8.350),
        (x_ca_fly_l, y_ca_fly),
    ], 0.300)
    via2_clean(half, x_ca_fly_l, y_ca_fly)
    half.wire("metal3", [(x_ca_fly_l, y_ca_fly), (x_ca_drop, y_ca_fly)], 0.300)
    via2_clean(half, x_ca_drop, y_ca_fly)
    half.wire("metal2", [(x_ca_drop, y_ca_fly), (x_ca_drop, y_ca)], 0.300)
    via2_clean(half, x_ca_drop, y_ca)

    via1_clean(half, mux_b["out"][0], mux_b["out"][1])
    half.wire("metal2", [mux_b["out"], (mux_b["out"][0], y_cb)], 0.300)
    half.wire("metal2", [(mux_b["out"][0], y_cb), (x_cb_via2, y_cb)], 0.400)
    via2_clean(half, x_cb_via2, y_cb)

    ca_max_x = x_ca_drop
    cb_max_x = x_cb_via2
    for col_i in range(4):
        s_ev = slices_top[2 * col_i]
        for xca in s_ev["ca_xs"]:
            via1_clean(half, xca, y_ca)
            via1_clean(half, xca, y_cb)
            half.wire("metal2", [(xca, y_ca), (xca, y_cb)], 0.300)
            via2_clean(half, xca, y_ca)
            ca_max_x = max(ca_max_x, xca)
        for xcb in s_ev["cb_xs"]:
            via1_clean(half, xcb, y_ca)
            via1_clean(half, xcb, y_cb)
            half.wire("metal2", [(xcb, y_ca), (xcb, y_cb)], 0.300)
            via2_clean(half, xcb, y_cb)
            cb_max_x = max(cb_max_x, xcb)
    half.wire("metal3", [(x_ca_drop, y_ca), (slices_top[0]["ca_xs"][0], y_ca)], 0.520)
    half.wire("metal3", [(x_ca_drop, y_ca), (ca_max_x, y_ca)], 0.300)
    half.wire("metal3", [(x_cb_via2, y_cb), (cb_max_x, y_cb)], 0.300)

    via1_clean(half, x_vdd_w_ch, +5.250)
    via2_clean(half, x_vdd_w_ch, +5.250)
    via3_pad(half, x_vdd_w_ch, +5.250)
    half.wire("metal3", [(x_vdd_w_ch, +5.250), (ca_max_x, +5.250)], 0.300)

    drv_plan = [
        (6, +0.550, 0, 91.350),
        (4, +1.500, 1, 90.750),
        (2, +2.270, 2, 90.000),
        (0, +3.130, 3, 89.400),
        (1, +7.370, 4, 89.400),
        (3, +8.230, 5, 90.000),
        (5, +9.000, 6, 90.750),
        (7, +9.950, 7, 91.350),
    ]
    for s_idx, yt, bar_i, xj in drv_plan:
        sl = slices_top[s_idx]
        dx = sl["drv_x"]
        y_lo = min(sl["drv_y_lo"], yt)
        y_hi = max(sl["drv_y_hi"], yt)
        half.wire("metal1", [(dx, y_lo), (dx, y_hi)], 0.320)
        via1_clean(half, dx, yt)
        via2_clean(half, dx, yt)
        half.wire("metal3", [(dx, yt), (xj, yt)], 0.340)
        via2_clean(half, xj, yt)
        yb = r16_top_ys[bar_i]
        half.wire("metal2", [(xj, yt), (xj, yb), (r16_r1_x, yb)], 0.340)
        via1_clean(half, r16_r1_x, yb)

    f_m4_xs: dict[int, float] = {}
    fb_m4_xs: dict[int, float] = {}
    for col_i in range(4):
        ev = 2 * col_i
        od = 2 * col_i + 1
        xf_ev, yf_ev = slices_top[ev]["f_tap"]
        xfb_ev, yfb_ev = slices_top[ev]["fb_tap"]
        xf_od, yf_od = slices_top[od]["f_tap"]
        xfb_od, yfb_od = slices_top[od]["fb_tap"]

        xm_f_ev  = xf_ev
        xm_fb_ev = xfb_ev
        xm_f_od  = grid(xf_od + 1.000)
        xm_fb_od = grid(xfb_od + 1.000)
        f_m4_xs[ev], fb_m4_xs[ev] = xm_f_ev, xm_fb_ev
        f_m4_xs[od], fb_m4_xs[od] = xm_f_od, xm_fb_od

        via2_clean(half, xm_f_ev, yf_ev)
        via3_pad(half, xm_f_ev, yf_ev)
        via2_clean(half, xm_fb_ev, yfb_ev)
        via3_pad(half, xm_fb_ev, yfb_ev)

        via2_clean(half, xf_od, yf_od)
        half.wire("metal3", [(xf_od, yf_od), (xm_f_od, yf_od)], 0.520)
        via3_pad(half, xm_f_od, yf_od)

        via2_clean(half, xfb_od, yfb_od)
        half.wire("metal3", [(xfb_od, yfb_od), (xm_fb_od, yfb_od)], 0.520)
        via3_pad(half, xm_fb_od, yfb_od)

    # =========================================================================
    # 3. Stage 3 TOP: `mixp` Summing Bar + 3D-Stacked `Xcmix (1.6)` & `Xcp1 (4.8)`
    # =========================================================================
    half.wire("metal1", [(r16_r2_x, r16_top_ys[0]), (r16_r2_x, r16_top_ys[-1])], 0.440)
    half.wire("metal2", [(r16_r2_x, r16_top_ys[0]), (r16_r2_x, r16_top_ys[-1])], 0.440)
    for yb in r16_top_ys:
        via1_clean(half, r16_r2_x, yb)

    x_cmix = 92.150
    x_cp1  = 97.650
    y_mim  = +5.250
    half.include(mim_1p6,    dx=x_cmix, dy=y_mim)
    half.include(mim_4p8_fx, dx=x_cp1,  dy=y_mim)

    x_cmix_vss = grid(x_cmix + c2_mix_dx)
    half.wire("metal3", [(x_cmix_vss, grid(y_mim + 0.850)), (x_cmix_vss, +y_vss_ch)], 0.520)
    via2_clean(half, x_cmix_vss, +y_vss_ch)
    via1_clean(half, x_cmix_vss, +y_vss_ch)

    x_cp1_c2 = grid(x_cp1 - c2_4p8_dx)
    x_mix_v2 = 101.200
    half.wire("metal2", [(r16_r2_x, y_mim), (x_mix_v2, y_mim)], 0.400)
    via2_clean(half, x_mix_v2, y_mim)
    half.wire("metal3", [(grid(x_cp1 + 3.150), y_mim), (x_mix_v2, y_mim)], 0.520)

    y_mix_m4 = +8.500
    half.wire("metal4", [
        (grid(x_cmix - 0.500), grid(y_mim + 0.700)),
        (grid(x_cmix - 0.500), y_mix_m4),
        (x_cp1_c2, y_mix_m4),
        (x_cp1_c2, grid(y_mim + 2.300)),
    ], 0.440)

    y_ac1_bus = +9.350
    x_ac1_drop = 101.350
    half.wire("metal4", [
        (grid(x_cp1 + 1.500), grid(y_mim + 2.300)),
        (grid(x_cp1 + 1.500), y_ac1_bus),
        (x_ac1_drop, y_ac1_bus),
    ], 0.440)
    via3_pad(half, x_ac1_drop, y_ac1_bus)
    via2_clean(half, x_ac1_drop, y_ac1_bus)

    # =========================================================================
    # 4. Stage 4 TOP: Hardened 2-Stage Triode+Cross-Coupled Diff Amp (`half`)
    #    Zero Stage-3 MIM loss -> drives Stage 5 Hybrid-PMOS Xr2 directly!
    # =========================================================================
    x_d1 = 105.550
    x_d2 = 109.300
    y_mn_d   = +2.725
    y_gn_d   = +4.285
    y_gmc_d  = +4.845
    y_mc_d   = +5.930
    y_vdd_d  = +7.115
    y_mp_d   = +8.570
    y_gmp_d  = +9.920

    half.rect("nwell", 104.350, +4.950, 110.850, +9.750)
    draw_tap_h(half, "nsubdiff", 104.550, 110.600, y_vdd_d, half_w=0.175, with_m1=True, m1_w=0.400, viali_pitch=1.20)

    # Stage 1 (+y): Xmn1p (7.20/0.15 nf=3), Xmc1p (2.88/0.15 nf=2), Xmp1p (3.80/0.15 nf=2)
    mn1 = pi5.place_mos_col(half, cache, x_d1, N_LVT, 7.20, 0.15, 3, y_mn_d, False, y_gn_d,
                            grid(y_mn_d - 0.35), grid(y_mn_d + 0.35))
    mc1 = pi5.place_mos_col(half, cache, x_d1, P_STD, 2.88, 0.15, 2, y_mc_d, True, y_gmc_d,
                            grid(y_mc_d + 0.35), grid(y_mc_d - 0.35))
    mp1 = pi5.place_mos_col(half, cache, x_d1, P_STD, 3.80, 0.15, 2, y_mp_d, True, y_gmp_d,
                            grid(y_mp_d - 0.35), grid(y_mp_d + 0.35))

    # Stage 2 (+y): Xmn2n (12.00/0.15 nf=5), Xmc2n (5.04/0.15 nf=4), Xmp2n (6.30/0.15 nf=4)
    mn2 = pi5.place_mos_col(half, cache, x_d2, N_LVT, 12.00, 0.15, 5, y_mn_d, False, y_gn_d,
                            grid(y_mn_d - 0.35), grid(y_mn_d + 0.35))
    mc2 = pi5.place_mos_col(half, cache, x_d2, P_STD, 5.04, 0.15, 4, y_mc_d, True, y_gmc_d,
                            grid(y_mc_d + 0.35), grid(y_mc_d - 0.35))
    mp2 = pi5.place_mos_col(half, cache, x_d2, P_STD, 6.30, 0.15, 4, y_mp_d, True, y_gmp_d,
                            grid(y_mp_d - 0.35), grid(y_mp_d + 0.35))

    for dev in (mc1, mp1, mc2, mp2):
        for sx in dev["s_xs"]:
            half.wire("metal1", [(sx, dev["s"][1]), (sx, y_vdd_d)], 0.220)
    for mp in (mp1, mp2):
        half.wire("metal1", [mp["g"], (mp["g"][0], +y_vss_ch)], 0.240)

    # Vertical drain net `r1n` (+y) at x_r1_bar = 106.550
    x_r1_bar = grid(x_d1 + 1.000)  # 106.550
    for dev in (mn1, mc1, mp1):
        half.rect("metal1", grid(min(dev["d_xs"][0], x_r1_bar) - 0.09), grid(dev["d"][1] - 0.145),
                  grid(max(dev["d_xs"][-1], x_r1_bar) + 0.09), grid(dev["d"][1] + 0.145))
    half.wire("metal1", [(x_r1_bar, mn1["d"][1]), (x_r1_bar, mc1["d"][1])], W_M1)
    half.wire("metal1", [(x_r1_bar, y_gn_d), (x_d2, y_gn_d)], W_M1)
    via1_clean(half, x_r1_bar, mc1["d"][1])
    via1_clean(half, x_r1_bar, mp1["d"][1])
    half.wire("metal2", [(x_r1_bar, mc1["d"][1]), (x_r1_bar, mp1["d"][1])], 0.280)

    # Vertical M1 drain bar `r2p` (+y) at x_r2_bar = x_d2 + 1.650 = 110.950
    x_r2_bar = grid(x_d2 + 1.650)  # 110.950
    for dev in (mn2, mc2, mp2):
        half.rect("metal1", grid(min(dev["d_xs"][0], x_r2_bar) - 0.09), grid(dev["d"][1] - 0.145),
                  grid(max(dev["d_xs"][-1], x_r2_bar) + 0.09), grid(dev["d"][1] + 0.145))
    half.wire("metal1", [(x_r2_bar, mn2["d"][1]), (x_r2_bar, mp2["d"][1])], W_M1)

    # =========================================================================
    # 5. Stage 5 TOP: Direct Composite Hybrid-PMOS Driver `Xr2` (4.20/18.00/5.60) + Output Aligner `Xcco` (0.90/3.80)
    #    Exact same East output port `(119.000, +-6.400)`!
    # =========================================================================
    y_vdd_r = +2.300
    y_p_r   = +4.400
    y_gc_r  = +6.400
    y_n_r   = +8.100
    y_vss_r = +y_vss_ch  # +10.500

    x_xr2_ps = 114.050
    x_xr2_pl = 116.820
    x_cco    = 118.600
    x_vdd_e  = 114.050
    x_out_e  = 119.000
    half.rect("nwell", 112.220, +1.750, 119.500, +6.300)
    draw_tap_h(half, "nsubdiff", 112.420, 119.300, y_vdd_r, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)
    half.wire("metal1", [(x_mix_r, y_vss_r), (112.600, y_vss_r)], 0.460)
    draw_tap_h(half, "psubdiff", 112.600, 119.350, y_vss_r, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)

    xr2 = draw_hyb_inv(
        half, cache, x_xr2_ps, 4.20, 18.00, 5.60, 2, 6, 2,
        y_p_r, y_n_r, y_gc_r, y_vdd_r, y_vss_r,
        x_ps=x_xr2_ps, x_pl=x_xr2_pl, x_n=x_xr2_ps, x_out_off=0.750,
    )
    xcco = draw_oct_inv(
        half, cache, x_cco, 0.90, 3.80, N_LVT, P_STD, 0.15, 0.15, 1, 2,
        y_p_r, y_n_r, y_gc_r, y_vdd_r, y_vss_r, x_out_off=0.670,
    )
    # Tie Xr2.out straight to Xcco.in on M1 (same output net: `on` in +y, `op` in -y!)
    half.wire("metal1", [xr2["out"], xcco["in"]], W_M1)

    # Direct low-C horizontal M2 stitch: `r2p` (+y) -> Xr2n.in (+y) -> `on`, `r2n` (-y) -> Xr2p.in (-y) -> `op`!
    via1_clean(half, x_r2_bar, y_gc_r)
    via1_clean(half, xr2["in"][0], y_gc_r)
    half.wire("metal2", [(x_r2_bar, y_gc_r), (xr2["in"][0], y_gc_r)], 0.340)

    # Export `on` (+y) / `op` (-y) straight EAST on M3 from Xr2.out (117.570) past Xcco.out (119.450)
    x_out_v = xr2["out"][0]  # 117.570
    via1_clean(half, x_out_v, y_gc_r)
    via2_clean(half, x_out_v, y_gc_r)
    half.wire("metal3", [(x_out_v, y_gc_r), (119.450, y_gc_r)], 0.400)

    # Stitch Diff Stage 1+2 VDD (y_vdd_d = +7.115) UP to M3 bridge at y = +9.600 -> EAST to x_vdd_e!
    y_vdd_br = +9.600
    x_vdd_d_tap = 107.100
    via1_clean(half, x_vdd_d_tap, y_vdd_d)
    half.wire("metal2", [(x_vdd_d_tap, y_vdd_d), (x_vdd_d_tap, y_vdd_br)], 0.340)
    via2_clean(half, x_vdd_d_tap, y_vdd_br)
    half.wire("metal3", [(x_vdd_d_tap, y_vdd_br), (x_vdd_e, y_vdd_br)], 0.400)
    via3_pad(half, x_vdd_e, y_vdd_br)

    # =========================================================================
    # INCLUDE `half` BOTH NORMAL (+y) AND MIRROR_Y (-y)!
    # =========================================================================
    ch.include(half, dx=0.0, dy=0.0, mirror_y=False)
    ch.include(half, dx=0.0, dy=0.0, mirror_y=True)

    # Cross-couple `Xcco` (op <-> on) on M2 (0.82 um separation!)
    x_cco_out = xcco["out"][0]  # 119.270
    x_cco_a   = 118.450
    # xcco_bot.out (-5.50) -> M2 straight UP at x_cco_out (119.27) -> via2 onto `on` M3 (+6.40)
    via1_clean(ch, x_cco_out, -5.500)
    ch.wire("metal2", [(x_cco_out, -5.500), (x_cco_out, +y_gc_r)], 0.280)
    via2_clean(ch, x_cco_out, +y_gc_r)
    # xcco_top.out (+7.30) -> M2 West to x_cco_a (118.45) -> M2 straight DOWN -> via2 onto `op` M3 (-6.40)
    via1_clean(ch, x_cco_out, +7.300)
    ch.wire("metal2", [(x_cco_out, +7.300), (x_cco_a, +7.300), (x_cco_a, -y_gc_r)], 0.280)
    via2_clean(ch, x_cco_a, -y_gc_r)

    # --- Shared Tail FETs `Xmt1` (4.60/0.20 nf=4) & `Xmt2` (9.80/0.20 nf=8) centered on y = 0.0 ---
    mt1 = pi5.place_mos_col(ch, cache, x_d1, N_STD, 4.60, 0.20, 4, 0.000, False, -0.985, -0.260, +0.260)
    mt2 = pi5.place_mos_col(ch, cache, x_d2, N_STD, 9.80, 0.20, 8, 0.000, False, -0.985, -0.260, +0.260)

    # Tie Xmt1.s & Xmt2.s (-0.260) cleanly to BOTH r2_1 East VSS guard ring AND dedicated VSS strip at x = 111.900!
    x_g_r21_e = grid(x_r2_1 + 1.155)
    x_vss_mid = 111.900
    viali_pad(ch, x_g_r21_e, -0.260)
    for yt in (-y_r2_g, +y_r2_g):
        viali_pad(ch, x_g_r21_e, yt)
    ch.wire("metal1", [(x_g_r21_e, -y_vss_ch), (x_g_r21_e, +y_vss_ch)], 0.280)
    # Dedicated compact local VSS anchor between Stage 4 and Stage 5 (clear of Stage-5 nwell 112.40!)
    ch.wire("metal1", [(x_g_r21_e, -0.260), (x_vss_mid, -0.260)], 0.260)
    ch.wire("metal1", [(x_vss_mid, -y_vss_ch), (x_vss_mid, +y_vss_ch)], 0.340)

    # Stitch `tail1` & `tail2` cleanly (M1 up to +mn.s, M2 down OVER mt.s/mt.g to -mn.s!)
    for mt, mn, x_t in ((mt1, mn1, x_d1), (mt2, mn2, x_d2)):
        x_tail_l = min(mt["d_xs"][0], mn["s_xs"][0])
        x_tail_r = max(mt["d_xs"][-1], mn["s_xs"][-1])
        ch.wire("metal1", [(x_tail_l, +0.260), (x_tail_r, +0.260)], 0.290)
        for sx in mn["s_xs"]:
            ch.wire("metal1", [(sx, +0.260), (sx, +mn["s"][1])], 0.220)
        via1_clean(ch, x_t, +0.260)
        via1_clean(ch, x_t, -mn["s"][1])
        ch.wire("metal2", [(x_t, +0.260), (x_t, -mn["s"][1])], 0.360)
        ch.wire("metal1", [(mn["s_xs"][0], -mn["s"][1]), (mn["s_xs"][-1], -mn["s"][1])], 0.240)

    # Tie Xmt1.g & Xmt2.g (-0.985) -> vdd DOWN to -y_vdd_d (-7.100)
    ch.wire("metal1", [mt1["g"], mt2["g"]], 0.240)
    via1_clean(ch, x_vdd_d_tap, -0.985)
    ch.wire("metal2", [(x_vdd_d_tap, -0.985), (x_vdd_d_tap, -y_vdd_d)], 0.300)

    # --- 180-deg Point-Symmetric Vertical `r2` Feedback Connections (l=6.5, pin y=+-5.155) ---
    # 1. Xrm_a (Mux A) and Xrm_b (Mux B):
    for mx, x_rm_c, x_out in ((mux_a, x_rm_a, x_out_a), (mux_b, x_rm_b, x_out_b)):
        xr_w = grid(x_rm_c - 0.415)
        xr_e = grid(x_rm_c + 0.415)
        ch.wire("metal2", [(x_out, +7.350), (xr_w, +7.350), (xr_w, +y_r2_pin)], 0.280)
        via1_clean(ch, xr_w, +y_r2_pin)
        ch.wire("metal2", [(x_out, -7.350), (xr_e, -7.350), (xr_e, -y_r2_pin)], 0.280)
        via1_clean(ch, xr_e, -y_r2_pin)

        x_ot = mx["out"][0]
        x_fb_v2 = grid(x_out + 0.150)
        ch.wire("metal2", [(x_ot, +mx["y_gc"]), (x_ot, +0.550), (x_fb_v2, +0.550)], 0.280)
        via2_clean(ch, x_fb_v2, +0.550)
        ch.wire("metal3", [(xr_w, +0.550), (x_fb_v2, +0.550)], 0.340)
        via2_clean(ch, xr_w, +0.550)
        ch.wire("metal2", [(xr_w, +0.550), (xr_w, -y_r2_pin)], 0.280)
        via1_clean(ch, xr_w, -y_r2_pin)

        ch.wire("metal2", [(x_ot, -mx["y_gc"]), (x_ot, -0.550), (x_fb_v2, -0.550)], 0.280)
        via2_clean(ch, x_fb_v2, -0.550)
        ch.wire("metal3", [(xr_e, -0.550), (x_fb_v2, -0.550)], 0.340)
        via2_clean(ch, xr_e, -0.550)
        ch.wire("metal2", [(xr_e, -0.550), (xr_e, +y_r2_pin)], 0.280)
        via1_clean(ch, xr_e, +y_r2_pin)

    # 2. `r2_1` (`Xrp1`: ac1p <-> r1n; `Xrn1`: ac1n <-> r1p) + Stage 1 cross-coupling
    x_r21_w = grid(x_r2_1 - 0.415)  # 102.285
    x_r21_e = grid(x_r2_1 + 0.415)  # 103.115
    x_ac1_col = 104.250
    ch.wire("metal2", [(x_ac1_drop, +y_ac1_bus), (x_ac1_col, +y_ac1_bus), (x_ac1_col, +y_gn_d), (x_d1, +y_gn_d)], 0.280)
    ch.wire("metal2", [(x_r21_w, +y_ac1_bus), (x_r21_w, +y_r2_pin)], 0.280)
    via1_clean(ch, x_r21_w, +y_r2_pin)
    via1_clean(ch, x_d1, +y_gn_d)
    ch.wire("metal2", [(x_ac1_drop, -y_ac1_bus), (x_ac1_col, -y_ac1_bus), (x_ac1_col, -y_gn_d), (x_d1, -y_gn_d)], 0.280)
    ch.wire("metal2", [(x_r21_e, -y_ac1_bus), (x_r21_e, -y_r2_pin)], 0.280)
    via1_clean(ch, x_r21_e, -y_r2_pin)
    via1_clean(ch, x_d1, -y_gn_d)

    # Cross-couple Stage 1 (x_cc1_n=106.50, x_vdd_d_tap=107.10, x_cc1_p=107.65 -> >=0.55 um M2 spacing!)
    x_cc1_n = 106.500
    x_cc1_p = 107.650
    via1_clean(ch, x_r1_bar, +3.100)
    ch.wire("metal2", [(x_r1_bar, +3.100), (x_cc1_n, +3.100), (x_cc1_n, -y_gmc_d), (x_d1, -y_gmc_d)], 0.260)
    via1_clean(ch, x_d1, -y_gmc_d)
    via2_clean(ch, x_cc1_n, +1.200)
    ch.wire("metal3", [(x_r21_w, +1.200), (x_cc1_n, +1.200)], 0.340)
    via2_clean(ch, x_r21_w, +1.200)
    ch.wire("metal2", [(x_r21_w, +1.200), (x_r21_w, -y_r2_pin)], 0.280)
    via1_clean(ch, x_r21_w, -y_r2_pin)

    via1_clean(ch, x_cc1_p, -y_gn_d)
    ch.wire("metal2", [(x_cc1_p, -y_gn_d), (x_cc1_p, +y_gmc_d), (x_d1, +y_gmc_d)], 0.260)
    via1_clean(ch, x_d1, +y_gmc_d)
    via2_clean(ch, x_cc1_p, -1.200)
    ch.wire("metal3", [(x_r21_e, -1.200), (x_cc1_p, -1.200)], 0.340)
    via2_clean(ch, x_r21_e, -1.200)
    ch.wire("metal2", [(x_r21_e, -1.200), (x_r21_e, +y_r2_pin)], 0.280)
    via1_clean(ch, x_r21_e, +y_r2_pin)

    # Stage 2 cross-coupling (`r2p` (+y) -> mc2p.g (-4.650), `r2n` (-y) -> mc2n.g (+4.650))
    # Both stay strictly inside y in [-7.80 .. +4.65], completely clear of direct M2 feed at y = +-6.40!
    x_cc2_p = x_r2_bar                # 110.750
    x_cc2_n = grid(x_r2_bar + 0.550)  # 111.300
    via1_clean(ch, x_r2_bar, +3.100)
    ch.wire("metal2", [(x_cc2_p, +3.100), (x_cc2_p, -y_gmc_d), (x_d2, -y_gmc_d)], 0.260)
    via1_clean(ch, x_d2, -y_gmc_d)
    via1_clean(ch, x_r2_bar, -7.800)
    ch.wire("metal2", [(x_r2_bar, -7.800), (x_cc2_n, -7.800), (x_cc2_n, +y_gmc_d), (x_d2, +y_gmc_d)], 0.260)
    via1_clean(ch, x_d2, +y_gmc_d)

    # Vertical M4 VDD spines (West: x_vdd_w_ch = 45.250 at +-5.250; East: x_vdd_e = 114.600)
    for yv in (-y_vdd_r, +y_vdd_r):
        via1_clean(ch, x_vdd_e, yv)
        via2_clean(ch, x_vdd_e, yv)
        via3_pad(ch, x_vdd_e, yv)
    ch.wire("metal4", [(x_vdd_e, -y_vdd_br), (x_vdd_e, +y_vdd_br)], 0.560)
    ch.wire("metal4", [(x_vdd_w_ch, -5.250), (x_vdd_w_ch, +5.250)], 0.560)

    # Central 2.5 GHz Clock Channels for Xmap/Xman (`e0..e3`) and Xmbp/Xmbn (`o0..o3`)
    clk_ys = [+1.590, +0.530, -0.530, -1.590]
    clk_in_x = 10.600
    for mx_base, x_l_bus, x_r_bus in (
        (mux_a, clk_in_x, 17.000),
        (mux_b, 25.400,   34.500),
    ):
        for yt in clk_ys:
            ch.wire("metal3", [(x_l_bus, yt), (x_r_bus, yt)], 0.300)
        for k in range(4):
            xl = mx_base["tgs"][k]["x_l"]
            yt_top = clk_ys[k]
            via1_clean(ch, xl, +3.450)
            ch.wire("metal2", [(xl, +3.450), (xl, yt_top)], 0.280)
            via2_clean(ch, xl, yt_top)
            yt_bot = clk_ys[(k + 2) % 4]
            xl_b = grid(xl - 0.480)
            via1_clean(ch, xl, -3.450)
            ch.wire("metal2", [(xl, -3.450), (xl, -2.550), (xl_b, -2.550), (xl_b, yt_bot)], 0.280)
            via2_clean(ch, xl_b, yt_bot)

    o_fly_ys = [+9.650, +8.850, -8.850, -9.650]
    o_jmp_xs = [27.120, 25.400, 26.260, 27.980]
    for k in range(4):
        yf = o_fly_ys[k]
        xj = o_jmp_xs[k]
        yc = clk_ys[k]
        ch.wire("metal3", [(clk_in_x, yf), (xj, yf)], 0.300)
        via3_pad(ch, xj, yf)
        ch.wire("metal4", [(xj, yf), (xj, yc)], 0.300)
        via3_pad(ch, xj, yc)
        ch.wire("metal3", [(xj, yc), (28.500, yc)], 0.300)

    sel_a_m4: list[tuple[float, float]] = []
    sel_b_m4: list[tuple[float, float]] = []
    for mx_base, out_list in ((mux_a, sel_a_m4), (mux_b, sel_b_m4)):
        for k in range(4):
            cx = mx_base["tgs"][k]["gp"][0]
            xm_s  = grid(cx)
            xm_sb = grid(cx + 0.960)
            out_list.append((xm_s, xm_sb))
            y_sb_abs = 1.350 if k == 3 else mx_base["y_gp"]
            for sgn_y in (+1.0, -1.0):
                y_gn_c = grid(sgn_y * mx_base["y_gn"])
                y_s_v  = grid(sgn_y * 3.300)
                via1_clean(ch, cx, y_gn_c)
                ch.wire("metal2", [(cx, y_gn_c), (xm_s, y_s_v)], W_M2)
                via2_clean(ch, xm_s, y_s_v)
                via3_pad(ch, xm_s, y_s_v)
                y_gp_c = grid(sgn_y * mx_base["y_gp"])
                y_sb_v = grid(sgn_y * y_sb_abs)
                via1_clean(ch, cx, y_gp_c)
                ch.wire("metal2", [(cx, y_gp_c), (xm_sb, y_gp_c), (xm_sb, y_sb_v)], W_M2)
                via2_clean(ch, xm_sb, y_sb_v)
                via3_pad(ch, xm_sb, y_sb_v)
            ch.wire("metal4", [(xm_s, -3.300), (xm_s, +3.300)], 0.340)
            ch.wire("metal4", [(xm_sb, -y_sb_abs), (xm_sb, +y_sb_abs)], 0.340)

    for k in range(8):
        yk = 0.550 if (k % 2 == 0) else 9.950
        ch.wire("metal4", [(f_m4_xs[k], -yk), (f_m4_xs[k], +yk)], 0.340)
        ch.wire("metal4", [(fb_m4_xs[k], -yk), (fb_m4_xs[k], +yk)], 0.340)

    meta = {
        "e_ys": clk_ys,
        "o_ys": o_fly_ys,
        "clk_in_x": clk_in_x,
        "sel_a_m4": sel_a_m4,
        "sel_b_m4": sel_b_m4,
        "f_m4_xs": f_m4_xs,
        "fb_m4_xs": fb_m4_xs,
        "on_pt": (x_out_e, +y_gc_r),
        "op_pt": (x_out_e, -y_gc_r),
        "xr2_out_x": xr2["out"][0],
        "vdd_m4_w": x_vdd_w_ch,
        "vdd_m4_e": x_vdd_e,
        "vss_e_x": 118.600,
        "vss_ys": [-y_vss_ch, 0.000, +y_vss_ch],
        "y_vss_ch": y_vss_ch,
        "vss_w_x": 10.200,
        "vss_w_tie_x": 10.800,
        "vdd_e_lo_y": -y_vdd_br,
    }
    return ch, meta


# ---------------------------------------------------------------------------
# 3. Updated 5G 4-Phase `serdes_rx_qdiv2_8ph_4iq` (single static Xrst 0.6/1.2)
# ---------------------------------------------------------------------------

def build_rx_qdiv2_8ph_4iq_pdk(cache: PdkCache, add_ports: bool = False) -> tuple[Cell, dict]:
    """Build exact 1:1 `serdes_rx_qdiv2_8ph_4iq` (single `pi4_inv_static` Xrst 0.6/1.2 driving latches + clock gates)."""
    c = Cell()

    y_vdd = 0.000
    y_p_s   = -2.400
    y_gp_s  = -4.600
    y_gc_s  = -5.100
    y_gn_s  = -5.600
    y_n_s   = -7.050
    y_vss_s = -8.650

    y_p_n   = +1.800
    y_gc_n  = +3.500
    y_n_n   = +4.900
    y_vss_n = +6.750

    x_left  = 0.000
    x_right = 136.400

    c.rect("nwell", grid(x_left - 0.60), -4.450, grid(x_right + 0.60), +3.350)
    draw_tap_h(c, "nsubdiff", x_left, x_right, y_vdd,   half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)
    draw_tap_h(c, "psubdiff", x_left, x_right, y_vss_s, half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)
    draw_tap_h(c, "psubdiff", x_left, x_right, y_vss_n, half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)

    pair_x_ctrs = {"d02": 19.600, "d13": 51.000, "e02": 91.200, "e13": 121.200}
    north_m2_xs = []
    for xc in pair_x_ctrs.values():
        north_m2_xs.extend([grid(xc - 4.300 + 0.580), grid(xc + 4.450 + 0.580)])
    for y_rail, m3_pw in ((y_vdd, 0.500), (y_vss_s, 0.600), (y_vss_n, 0.500)):
        c.wire("metal3", [(x_left, y_rail), (x_right, y_rail)], m3_pw)
        xv = grid(x_left + 1.5)
        while xv <= x_right - 1.5 + 1e-6:
            if y_rail == y_vss_n and any(abs(xv - nx) < 1.20 for nx in north_m2_xs):
                xv = grid(xv + 12.0)
                continue
            via1_clean(c, xv, y_rail)
            via2_clean(c, xv, y_rail)
            xv = grid(xv + 12.0)

    for x_strap in (grid(x_left + 0.50), grid(x_right - 0.50)):
        via3_pad(c, x_strap, y_vss_s)
        via3_pad(c, x_strap, y_vss_n)
        c.wire("metal4", [(x_strap, y_vss_s), (x_strap, y_vss_n)], 0.600)

    # Single Xrst inverter matching `rx_pi_4ph_iq_5g_cand.spice` line 253: `pi4_inv_static wn=0.6 wp=1.2`
    xrst = pi5.draw_cmos_inv(
        c, cache, 5.200, 0.60, 1.20, N_STD, P_STD, 0.18, 0.18, 1, 1,
        y_p_s, y_n_s, y_gc_s, y_vdd, y_vss_s, x_out_off=0.600,
    )

    col_x0 = [10.400, 41.800, 73.200, 104.600]
    clk_specs = [
        ("dp", False, 3.40, 14.28, 2, 4),
        ("dn", True,  3.40, 14.28, 2, 4),
        ("ep", False, 1.45,  6.09, 1, 3),
        ("en", True,  1.45,  6.09, 1, 3),
    ]
    gates: dict[str, dict] = {}
    latches: dict[str, dict] = {}
    for (cname, clamp_hi, wn_o, wp_o, nfn_o, nfp_o), x0 in zip(clk_specs, col_x0):
        cg = pi5._draw_qdiv2_clkgate(c, cache, x0, y_p_s, y_n_s, y_gp_s, y_gn_s, y_vdd, y_vss_s, clamp_hi=clamp_hi)
        lt = pi5._draw_pi_diff_latch(
            c, cache, grid(x0 + 10.600), y_p_s, y_n_s, y_gp_s, y_gn_s, y_vdd, y_vss_s,
            wn_out=wn_o, wp_out=wp_o, nfn_out=nfn_o, nfp_out=nfp_o,
        )
        gates[cname] = cg
        latches[cname] = lt
        via1_clean(c, cg["ck"][0], cg["ck"][1])
        c.wire("metal2", [(cg["ck"][0], cg["ck"][1]), (cg["ck"][0], lt["ck"][1]), lt["ck"]], W_M2)

    outpairs: dict[str, dict] = {}
    for pname, xctr in pair_x_ctrs.items():
        outpairs[pname] = pi5._draw_qdiv2_outpair(c, cache, xctr, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    cc_dckb = pi5._draw_qdiv2_cc_align(c, cache, 30.200, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=0.45, wp=1.89)
    cc_dck  = pi5._draw_qdiv2_cc_align(c, cache, 35.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=0.45, wp=1.89)
    cc_eckb = pi5._draw_qdiv2_cc_align(c, cache, 101.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=0.45, wp=1.89)
    cc_eck  = pi5._draw_qdiv2_cc_align(c, cache, 107.000, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=0.45, wp=1.89)

    y_trk_rstn_lat = -6.800
    y_trk_rstn     = -5.950
    y_trk_rst_lat  = -5.100
    y_trk_rst      = -4.250
    y_trk_dp       = -3.400
    y_trk_ep       = -2.550
    y_trk_dn       = -1.700
    y_trk_en       = -0.850

    y_trk_d0  = +0.840
    y_trk_ckp = +1.680
    y_trk_d2  = +2.520
    y_trk_d1  = +3.360
    y_trk_ckn = +4.200
    y_trk_d3  = +5.040
    y_trk_ckb = +5.880

    y_trk_ck02  = +7.600
    y_trk_ck13  = +8.450
    y_north_pin = +8.800

    clk_names = ["dp", "dn", "ep", "en"]

    # `rst_n` feeds Xrst.in, all 4 ClkGates, AND directly bridges to y_trk_rstn_lat -> all 4 Latches!
    x_rstn_hi = grid(max(
        max(gates[cn]["rst_n"][0] for cn in clk_names),
        max(gates[cn]["clmp_rst_pt"][0] for cn in clk_names if gates[cn]["clmp_rst_net"] == "rst_n"),
    ) + 0.500)
    x_rstn_lat_hi = grid(latches["en"]["rst_n_lat"][0] + 0.500)
    c.wire("metal3", [(x_left, y_trk_rstn), (x_rstn_hi, y_trk_rstn)], 0.340)
    c.wire("metal3", [(xrst["in"][0], y_trk_rstn_lat), (x_rstn_lat_hi, y_trk_rstn_lat)], 0.340)
    via1_clean(c, xrst["in"][0], xrst["in"][1])
    c.wire("metal2", [(xrst["in"][0], y_trk_rstn_lat), (xrst["in"][0], xrst["in"][1])], W_M2)
    via2_clean(c, xrst["in"][0], y_trk_rstn)
    via2_clean(c, xrst["in"][0], y_trk_rstn_lat)
    for cn in clk_names:
        gx, gy = gates[cn]["rst_n"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, y_trk_rstn)], W_M2)
        via2_clean(c, gx, y_trk_rstn)
        if gates[cn]["clmp_rst_net"] == "rst_n":
            cx, cy = gates[cn]["clmp_rst_pt"]
            via1_clean(c, cx, cy)
            c.wire("metal2", [(cx, cy), (cx, y_trk_rstn)], W_M2)
            via2_clean(c, cx, y_trk_rstn)
        lx, ly = latches[cn]["rst_n_lat"]
        via1_clean(c, lx, ly)
        via2_clean(c, lx, ly)

    # `rst` (Xrst.out) feeds all 4 ClkGates AND directly bridges to y_trk_rst_lat -> all 4 Latches!
    x_rst_hi = grid(max(
        max(gates[cn]["rst"][0] for cn in clk_names),
        max(gates[cn]["clmp_rst_pt"][0] for cn in clk_names if gates[cn]["clmp_rst_net"] == "rst"),
    ) + 0.500)
    x_rst_lat_hi = grid(latches["en"]["rst_lat"][0] + 0.500)
    c.wire("metal3", [(xrst["out"][0], y_trk_rst), (x_rst_hi, y_trk_rst)], 0.340)
    c.wire("metal3", [(xrst["out"][0], y_trk_rst_lat), (x_rst_lat_hi, y_trk_rst_lat)], 0.340)
    via1_clean(c, xrst["out"][0], xrst["out"][1])
    c.wire("metal2", [(xrst["out"][0], xrst["out"][1]), (xrst["out"][0], y_trk_rst)], W_M2)
    via2_clean(c, xrst["out"][0], y_trk_rst_lat)
    via2_clean(c, xrst["out"][0], y_trk_rst)
    for cn in clk_names:
        gx, gy = gates[cn]["rst"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, y_trk_rst)], W_M2)
        via2_clean(c, gx, y_trk_rst)
        if gates[cn]["clmp_rst_net"] == "rst":
            cx, cy = gates[cn]["clmp_rst_pt"]
            via1_clean(c, cx, cy)
            c.wire("metal2", [(cx, cy), (cx, y_trk_rst)], W_M2)
            via2_clean(c, cx, y_trk_rst)
        rx, ry = latches[cn]["rst_lat"]
        via1_clean(c, rx, ry)
        via2_clean(c, rx, y_trk_rst_lat)

    # `dp, dn, ep, en` EQUAL-SPAN horizontal M3 trunks [8.5 .. x_right]
    for cn, yt in (("dp", y_trk_dp), ("dn", y_trk_dn), ("ep", y_trk_ep), ("en", y_trk_en)):
        c.wire("metal3", [(8.500, yt), (x_right, yt)], 0.300)
        gx, gy = gates[cn]["ck_in"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, yt)], W_M2)
        via2_clean(c, gx, yt)

    # Conflict-free M4-vertical / M3-horizontal router for North-band nets
    m4_used: list[tuple[float, float, float, str]] = [
        (grid(x_left + 0.50), y_vss_s, y_vss_n, "vss"),
        (grid(x_right - 0.50), y_vss_s, y_vss_n, "vss"),
    ]
    m3_pads: list[tuple[float, float, str]] = []
    m3_tracks_occ: dict[float, list[tuple[float, float, str]]] = {
        y_vdd: [(x_left, x_right, "vdd")],
        y_vss_s: [(x_left, x_right, "vss")],
        y_vss_n: [(x_left, x_right, "vss")],
        y_trk_rstn_lat: [(xrst["in"][0], x_rstn_lat_hi, "rst_n")],
        y_trk_rstn: [(x_left, x_rstn_hi, "rst_n")],
        y_trk_rst_lat: [(xrst["out"][0], x_rst_lat_hi, "rst")],
        y_trk_rst: [(xrst["out"][0], x_rst_hi, "rst")],
        y_trk_dp: [(8.500, x_right, "dp")],
        y_trk_dn: [(8.500, x_right, "dn")],
        y_trk_ep: [(8.500, x_right, "ep")],
        y_trk_en: [(8.500, x_right, "en")],
    }

    def m4_free(x: float, y1: float, y2: float, net: str) -> bool:
        ya, yb = min(y1, y2) - 0.88, max(y1, y2) + 0.88
        for ux, uy1, uy2, unet in m4_used:
            if unet != net and abs(ux - x) < 0.96 and not (yb < uy1 or ya > uy2):
                return False
        return True

    def m3_pt_ok(x_c: float, y_c: float, net: str) -> bool:
        for ty, occs in m3_tracks_occ.items():
            if abs(ty - y_c) < 0.78:
                for ox1, ox2, onet in occs:
                    if onet != net and (ox1 - 0.80) <= x_c <= (ox2 + 0.80):
                        return False
        for mx, my, mnet in m3_pads:
            if mnet != net and abs(mx - x_c) < 0.80 and abs(my - y_c) < 0.78:
                return False
        return True

    def route_bus_m3_m4(net: str, y_trk: float, pins: list[tuple[float, float, str]]) -> None:
        y_trk = grid(y_trk)
        xs_trk: list[float] = []
        for px, py, lyr in pins:
            px, py = grid(px), grid(py)
            chosen = None
            if py > 0.0 and m3_pt_ok(px, y_trk, net):
                chosen = (px, y_trk)
            elif m3_pt_ok(px, py, net) and m4_free(px, py, y_trk, net):
                chosen = (px, py)
            else:
                for dx_n in (0.48, -0.48, 0.96, -0.96, 1.44, -1.44, 1.92, -1.92):
                    xc = grid(px + dx_n)
                    if m3_pt_ok(xc, py, net) and m4_free(xc, py, y_trk, net):
                        chosen = (xc, py)
                        break
            if chosen is None:
                raise RuntimeError(f"No clean M3/M4 escape for net {net} pin {(px, py)} -> y_trk={y_trk}")
            xc, yc = chosen
            if lyr == "metal1":
                via1_clean(c, px, py)
            if abs(xc - px) > 0.01 or abs(yc - py) > 0.01:
                c.wire("metal2", [(px, py), (xc, py), (xc, yc)], W_M2)
            via2_clean(c, xc, yc)
            m3_pads.append((xc, yc, net))
            if abs(yc - y_trk) > 0.01:
                via3_pad(c, xc, yc)
                c.wire("metal4", [(xc, yc), (xc, y_trk)], 0.400)
                via3_pad(c, xc, y_trk)
                m4_used.append((xc, min(yc, y_trk), max(yc, y_trk), net))
            xs_trk.append(xc)
        x_lo, x_hi = min(xs_trk), max(xs_trk)
        if x_hi - x_lo > 0.01:
            c.wire("metal3", [(x_lo, y_trk), (x_hi, y_trk)], 0.300)
        m3_tracks_occ.setdefault(y_trk, []).append((x_lo, x_hi, net))

    route_bus_m3_m4("d0", y_trk_d0, [
        (latches["dp"]["qp"][0], latches["dp"]["qp"][1], "metal1"),
        (latches["dn"]["dp_in"][0], latches["dn"]["dp_in"][1], "metal1"),
        (latches["ep"]["dp_in"][0], latches["ep"]["dp_in"][1], "metal1"),
        (outpairs["d02"]["in_b"][0], outpairs["d02"]["in_b"][1], "metal1"),
    ])
    route_bus_m3_m4("d2", y_trk_d2, [
        (latches["dp"]["qn"][0], latches["dp"]["qn"][1], "metal1"),
        (latches["dn"]["dn_in"][0], latches["dn"]["dn_in"][1], "metal1"),
        (latches["ep"]["dn_in"][0], latches["ep"]["dn_in"][1], "metal1"),
        (outpairs["d02"]["in_a"][0], outpairs["d02"]["in_a"][1], "metal1"),
    ])
    route_bus_m3_m4("d1", y_trk_d1, [
        (latches["dn"]["qp"][0], latches["dn"]["qp"][1], "metal1"),
        (latches["dp"]["dn_in"][0], latches["dp"]["dn_in"][1], "metal1"),
        (latches["en"]["dp_in"][0], latches["en"]["dp_in"][1], "metal1"),
        (outpairs["d13"]["in_b"][0], outpairs["d13"]["in_b"][1], "metal1"),
    ])
    route_bus_m3_m4("d3", y_trk_d3, [
        (latches["dn"]["qn"][0], latches["dn"]["qn"][1], "metal1"),
        (latches["dp"]["dp_in"][0], latches["dp"]["dp_in"][1], "metal1"),
        (latches["en"]["dn_in"][0], latches["en"]["dn_in"][1], "metal1"),
        (outpairs["d13"]["in_a"][0], outpairs["d13"]["in_a"][1], "metal1"),
    ])
    route_bus_m3_m4("e0", y_trk_d2, [
        (latches["ep"]["qp"][0], latches["ep"]["qp"][1], "metal1"),
        (outpairs["e02"]["in_b"][0], outpairs["e02"]["in_b"][1], "metal1"),
    ])
    route_bus_m3_m4("e2", y_trk_d0, [
        (latches["ep"]["qn"][0], latches["ep"]["qn"][1], "metal1"),
        (outpairs["e02"]["in_a"][0], outpairs["e02"]["in_a"][1], "metal1"),
    ])
    route_bus_m3_m4("e1", y_trk_d2, [
        (latches["en"]["qp"][0], latches["en"]["qp"][1], "metal1"),
        (outpairs["e13"]["in_b"][0], outpairs["e13"]["in_b"][1], "metal1"),
    ])
    route_bus_m3_m4("e3", y_trk_d0, [
        (latches["en"]["qn"][0], latches["en"]["qn"][1], "metal1"),
        (outpairs["e13"]["in_a"][0], outpairs["e13"]["in_a"][1], "metal1"),
    ])
    route_bus_m3_m4("dp_ck", y_trk_ckp, [
        (gates["dp"]["ck_esc"][0], gates["dp"]["ck_esc"][1], "metal1"),
        (latches["dn"]["ckb_esc"][0], latches["dn"]["ckb_esc"][1], "metal1"),
        (cc_dck["a"][0], cc_dck["a"][1], "metal2"),
    ])
    route_bus_m3_m4("dn_ck", y_trk_ckn, [
        (gates["dn"]["ck_esc"][0], gates["dn"]["ck_esc"][1], "metal1"),
        (latches["dp"]["ckb_esc"][0], latches["dp"]["ckb_esc"][1], "metal1"),
        (cc_dck["b"][0], cc_dck["b"][1], "metal2"),
    ])
    route_bus_m3_m4("ep_ck", y_trk_ckp, [
        (gates["ep"]["ck_esc"][0], gates["ep"]["ck_esc"][1], "metal1"),
        (latches["en"]["ckb_esc"][0], latches["en"]["ckb_esc"][1], "metal1"),
        (cc_eck["a"][0], cc_eck["a"][1], "metal2"),
    ])
    route_bus_m3_m4("en_ck", y_trk_ckn, [
        (gates["en"]["ck_esc"][0], gates["en"]["ck_esc"][1], "metal1"),
        (latches["ep"]["ckb_esc"][0], latches["ep"]["ckb_esc"][1], "metal1"),
        (cc_eck["b"][0], cc_eck["b"][1], "metal2"),
    ])
    route_bus_m3_m4("dp_ckb", y_trk_ckb, [
        (gates["dp"]["ckb_esc"][0], gates["dp"]["ckb_esc"][1], "metal1"),
        (cc_dckb["a"][0], cc_dckb["a"][1], "metal2"),
    ])
    route_bus_m3_m4("dn_ckb", y_trk_ckb, [
        (gates["dn"]["ckb_esc"][0], gates["dn"]["ckb_esc"][1], "metal1"),
        (cc_dckb["b"][0], cc_dckb["b"][1], "metal2"),
    ])
    route_bus_m3_m4("ep_ckb", y_trk_ckb, [
        (gates["ep"]["ckb_esc"][0], gates["ep"]["ckb_esc"][1], "metal1"),
        (cc_eckb["a"][0], cc_eckb["a"][1], "metal2"),
    ])
    route_bus_m3_m4("en_ckb", y_trk_ckb, [
        (gates["en"]["ckb_esc"][0], gates["en"]["ckb_esc"][1], "metal1"),
        (cc_eckb["b"][0], cc_eckb["b"][1], "metal2"),
    ])

    north_specs = [
        ("ckd0", outpairs["d02"]["out_a_m2"],  11.000, y_trk_ck02),
        ("ckd2", outpairs["d02"]["out_b_m2"],  43.000, y_trk_ck02),
        ("ckd1", outpairs["d13"]["out_a_m2"],  27.000, y_trk_ck13),
        ("ckd3", outpairs["d13"]["out_b_m2"],  59.000, y_trk_ck13),
        ("cke0", outpairs["e02"]["out_a_m2"],  75.000, y_trk_ck02),
        ("cke2", outpairs["e02"]["out_b_m2"], 107.000, y_trk_ck02),
        ("cke1", outpairs["e13"]["out_a_m2"],  91.000, y_trk_ck13),
        ("cke3", outpairs["e13"]["out_b_m2"], 123.000, y_trk_ck13),
    ]
    north_pins: dict[str, tuple[float, float]] = {}
    for nm, (ox, oy), x_pin, y_sort in north_specs:
        c.wire("metal2", [(ox, oy), (ox, y_sort)], 0.360)
        via2_clean(c, ox, y_sort)
        c.wire("metal3", [(min(ox, x_pin), y_sort), (max(ox, x_pin), y_sort)], 0.360)
        via3_pad(c, x_pin, y_sort)
        c.wire("metal4", [(x_pin, y_sort), (x_pin, y_north_pin)], 0.440)
        north_pins[nm] = (x_pin, y_north_pin)

    meta = {
        "dp": (x_right, y_trk_dp),
        "dn": (x_right, y_trk_dn),
        "ep": (x_right, y_trk_ep),
        "en": (x_right, y_trk_en),
        "rst_n": (x_left, y_trk_rstn),
        "vdd": (x_left, y_vdd),
        "vss": (x_left, y_vss_s),
        "vdd_e": (x_right, y_vdd),
        "vss_e": (x_right, y_vss_s),
        **north_pins,
    }
    return c, meta


# ---------------------------------------------------------------------------
# 3B. Hardened v2 `serdes_rx_qdiv2_8ph_4iq` (Matched Dual-Johnson +
#     Hybrid-PMOS ClkGate + Compact Synchronous `(d1 & dp_ck)` `Xesync`)
# ---------------------------------------------------------------------------

def _draw_qdiv2_clkgate_v2(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_gp: float,
    y_gn: float,
    y_vdd: float,
    y_vss: float,
    clamp_hi: bool = False,
) -> dict:
    """Draw 1 v2 5G symmetric TG-isolated reset-gated 2.5 GHz clock slice:
      Col 0 (x0 + 0.00): Xtg    (pi4_tgate_lvt wn=2.60 nfn=2, wp=6.80 l=0.35 nfp=3)
      Col 1 (x0 + 2.60): Xclmp  (nfet 0.80/0.18 if lo; pfet 1.60/0.18 if hi)
      Col 2 (x0 + 4.35 / 5.85): Xinv   (pi4_inv_hyb wn=1.60 nf1, wps=5.40 nf2, wpl=2.20 nf1)
      Col 3 (x0 + 8.35): Xg_inv (pi4_inv_q wn=2.40 nf2, wp=12.00 nf4)
    """
    x0   = grid(x0)
    x_tg = grid(x0)
    x_cl = grid(x0 + 2.600)
    x_i1_ps = grid(x0 + 4.350)
    x_i1_pl = grid(x0 + 5.850)
    x_i2 = grid(x0 + 8.150)
    y_gc = grid((y_gp + y_gn) / 2.0)

    tgp = pi5.place_mos_col(c, cache, x_tg, P_LVT, 6.80, 0.35, 3, y_p, True,  y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
    tgn = pi5.place_mos_col(c, cache, x_tg, N_LVT, 2.60, 0.15, 2, y_n, False, y_gn, grid(y_n - 0.35), grid(y_n + 0.35))

    x_ckin = grid(x_tg - 1.300)
    c.rect("metal1", grid(x_ckin - 0.09), grid(tgp["s"][1] - 0.145), grid(tgp["s_xs"][0] + 0.145), grid(tgp["s"][1] + 0.145))
    c.rect("metal1", grid(x_ckin - 0.09), grid(tgn["s"][1] - 0.145), grid(tgn["s_xs"][0] + 0.145), grid(tgn["s"][1] + 0.145))
    c.wire("metal1", [(x_ckin, tgp["s"][1]), (x_ckin, tgn["s"][1])], W_M1)

    x_ckg = grid(x_tg + 1.350)
    c.rect("metal1", grid(tgp["d_xs"][-1] - 0.145), grid(tgp["d"][1] - 0.145), grid(x_ckg + 0.09), grid(tgp["d"][1] + 0.145))
    c.rect("metal1", grid(tgn["d_xs"][-1] - 0.145), grid(tgn["d"][1] - 0.145), grid(x_ckg + 0.09), grid(tgn["d"][1] + 0.145))
    c.wire("metal1", [(x_ckg, tgp["d"][1]), (x_ckg, tgn["d"][1])], W_M1)

    if not clamp_hi:
        clmp = pi5.place_mos_col(c, cache, x_cl, N_STD, 0.80, 0.18, 1, y_n, False, y_gn, grid(y_n - 0.25), grid(y_n + 0.25))
        c.wire("metal1", [(clmp["s"][0], clmp["s"][1]), (clmp["s"][0], y_vss)], 0.220)
        c.wire("metal1", [(x_ckg, clmp["d"][1]), (clmp["d"][0], clmp["d"][1])], W_M1)
        clmp_gate_net = "rst"
        clmp_gate_pt = (clmp["g"][0], y_gc)
        c.wire("metal1", [(clmp["g"][0], clmp["g"][1]), clmp_gate_pt], W_M1)
    else:
        clmp = pi5.place_mos_col(c, cache, x_cl, P_STD, 1.60, 0.18, 1, y_p, True, y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
        c.wire("metal1", [(clmp["s"][0], clmp["s"][1]), (clmp["s"][0], y_vdd)], 0.220)
        c.wire("metal1", [(x_ckg, clmp["d"][1]), (clmp["d"][0], clmp["d"][1])], W_M1)
        clmp_gate_net = "rst_n"
        clmp_gate_pt = (clmp["g"][0], y_gp)

    # Col 2: Xinv (Composite Hybrid-PMOS: wn=1.60 nf1, wps=5.40 nf2, wpl=2.20 nf1 -> out at x0+6.45)
    inv1 = draw_hyb_inv(
        c, cache, x_i1_ps, 1.60, 5.40, 2.20, 1, 2, 1,
        y_p, y_n, y_gc, y_vdd, y_vss,
        x_ps=x_i1_ps, x_pl=x_i1_pl, x_n=x_i1_ps, x_out_off=0.600,
    )
    y_ckg_br = grid(y_p - 0.45) if not clamp_hi else grid(y_n + 0.35)
    x_i1_in_l = grid(x_i1_ps - 0.900)
    c.wire("metal1", [(x_ckg, y_ckg_br), (x_i1_in_l, y_ckg_br), (x_i1_in_l, y_gc), (x_i1_ps, y_gc)], W_M1)

    # Col 3: Xg_inv (pi4_inv_q wn=2.40 nf2, wp=10.56 nf4 -> out at x0+9.45)
    inv2 = pi5.draw_cmos_inv(
        c, cache, x_i2, 2.40, 10.56, N_LVT, P_STD, 0.15, 0.15, 2, 4,
        y_p, y_n, y_gc, y_vdd, y_vss, y_out_m1=y_gc, x_out_off=1.100,
    )
    y_ckb_m1 = grid(y_gp)
    c.wire("metal1", [(inv1["out"][0], y_ckb_m1), (x_i2, y_ckb_m1), (x_i2, y_gc)], W_M1)

    y_esc = grid(y_vss + 1.000)
    c.wire("metal1", [(inv2["out"][0], inv2["dn"][1]), (inv2["out"][0], y_esc)], W_M1)

    x_tgn_g = grid(tgn["g"][0] + 0.700)
    c.wire("metal1", [(tgp["g"][0], tgp["g"][1]), (tgp["g"][0], y_gc)], W_M1)
    c.wire("metal1", [(tgn["g"][0], tgn["g"][1]), (x_tgn_g, y_gn)], W_M1)

    return {
        "ck_in": (x_ckin, y_gc),
        "rst_n": (x_tgn_g, y_gn),
        "rst":   (tgp["g"][0], y_gc),
        "clmp_rst_net": clmp_gate_net,
        "clmp_rst_pt": clmp_gate_pt,
        "ck": (inv2["out"][0], grid(y_gn)),
        "ck_esc": (inv2["out"][0], y_esc),
        "x_end": grid(x_i2 + 1.650),
    }


def _draw_pi_diff_latch_v2(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_gp: float,
    y_gn: float,
    y_vdd: float,
    y_vss: float,
    wn_out: float = 3.40,
    wp_out: float = 13.20,
    nfn_out: int = 2,
    nfp_out: int = 4,
    wn_tg: float = 3.00,
    wp_tg: float = 7.80,
    expose_int: bool = False,
) -> dict:
    """Draw 1 v2 `pi4_diff_latch` (Xtgp/n parametrized, Xk 0.60/0.60, Xrp/rn 1.0/1.8, Xop/n 3.40/13.20, Xcc 0.65/2.75)."""
    x0 = grid(x0)
    xs = [
        grid(x0 + 0.000),   # 0: Xtgp (nfp=3)
        grid(x0 + 2.200),   # 1: Xk1 (int_n -> int_p)
        grid(x0 + 3.900),   # 2: Xrp/Xrn (rst_lat / rst_n_lat)
        grid(x0 + 5.600),   # 3: Xk2 (int_p -> int_n)
        grid(x0 + 7.800),   # 4: Xtgn (nfp=3)
        grid(x0 + 10.900),  # 5: Xon (int_p -> qn, nfp=4)
        grid(x0 + 13.300),  # 6: Xcc1 (qp -> qn)
        grid(x0 + 14.950),  # 7: Xcc2 (qn -> qp)
        grid(x0 + 17.350),  # 8: Xop (int_n -> qp, nfp=4)
    ]
    y_gc = grid((y_gp + y_gn) / 2.0)

    tgp_p = pi5.place_mos_col(c, cache, xs[0], P_STD, wp_tg, 0.15, 3, y_p, True,  y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
    tgp_n = pi5.place_mos_col(c, cache, xs[0], N_LVT, wn_tg, 0.15, 2, y_n, False, y_gn, grid(y_n - 0.35), grid(y_n + 0.35))
    x_dpin = grid(xs[0] - 1.050)
    c.rect("metal1", grid(x_dpin - 0.09), grid(tgp_p["s"][1] - 0.145), grid(tgp_p["s_xs"][0] + 0.145), grid(tgp_p["s"][1] + 0.145))
    c.rect("metal1", grid(x_dpin - 0.09), grid(tgp_n["s"][1] - 0.145), grid(tgp_n["s_xs"][0] + 0.145), grid(tgp_n["s"][1] + 0.145))
    c.wire("metal1", [(x_dpin, tgp_p["s"][1]), (x_dpin, tgp_n["s"][1])], W_M1)
    x_tgp_d = grid(xs[0] + 1.050)
    c.rect("metal1", grid(tgp_p["d_xs"][-1] - 0.145), grid(tgp_p["d"][1] - 0.145), grid(x_tgp_d + 0.09), grid(tgp_p["d"][1] + 0.145))
    c.rect("metal1", grid(tgp_n["d_xs"][-1] - 0.145), grid(tgp_n["d"][1] - 0.145), grid(x_tgp_d + 0.09), grid(tgp_n["d"][1] + 0.145))
    c.wire("metal1", [(x_tgp_d, tgp_p["d"][1]), (x_tgp_d, tgp_n["d"][1])], W_M1)

    k1 = pi5.draw_cmos_inv(c, cache, xs[1], 0.60, 0.60, N_STD, P_STD, 0.28, 0.28, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss)

    rn = pi5.place_mos_col(c, cache, xs[2], P_STD, 1.80, 0.18, 1, y_p, True,  y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
    rp = pi5.place_mos_col(c, cache, xs[2], N_STD, 1.00, 0.18, 1, y_n, False, y_gn, grid(y_n - 0.25), grid(y_n + 0.25))
    c.wire("metal1", [(rn["s"][0], rn["s"][1]), (rn["s"][0], y_vdd)], 0.220)
    c.wire("metal1", [(rp["s"][0], rp["s"][1]), (rp["s"][0], y_vss)], 0.220)

    k2 = pi5.draw_cmos_inv(c, cache, xs[3], 0.60, 0.60, N_STD, P_STD, 0.28, 0.28, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss)

    tgn_p = pi5.place_mos_col(c, cache, xs[4], P_STD, wp_tg, 0.15, 3, y_p, True,  y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
    tgn_n = pi5.place_mos_col(c, cache, xs[4], N_LVT, wn_tg, 0.15, 2, y_n, False, y_gn, grid(y_n - 0.35), grid(y_n + 0.35))
    x_tgn_int = grid(xs[4] - 1.050)
    c.rect("metal1", grid(x_tgn_int - 0.09), grid(tgn_p["s"][1] - 0.145), grid(tgn_p["s_xs"][0] + 0.145), grid(tgn_p["s"][1] + 0.145))
    c.rect("metal1", grid(x_tgn_int - 0.09), grid(tgn_n["s"][1] - 0.145), grid(tgn_n["s_xs"][0] + 0.145), grid(tgn_n["s"][1] + 0.145))
    c.wire("metal1", [(x_tgn_int, tgn_p["s"][1]), (x_tgn_int, tgn_n["s"][1])], W_M1)
    x_dnin = grid(xs[4] + 1.050)
    c.rect("metal1", grid(tgn_p["d_xs"][-1] - 0.145), grid(tgn_p["d"][1] - 0.145), grid(x_dnin + 0.09), grid(tgn_p["d"][1] + 0.145))
    c.rect("metal1", grid(tgn_n["d_xs"][-1] - 0.145), grid(tgn_n["d"][1] - 0.145), grid(x_dnin + 0.09), grid(tgn_n["d"][1] + 0.145))
    c.wire("metal1", [(x_dnin, tgn_p["d"][1]), (x_dnin, tgn_n["d"][1])], W_M1)

    xon = pi5.draw_cmos_inv(
        c, cache, xs[5], wn_out, wp_out, N_LVT, P_STD, 0.15, 0.15, nfn_out, nfp_out,
        y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=1.100,
    )
    cc1 = pi5.draw_cmos_inv(c, cache, xs[6], 0.65, 2.75, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss)
    cc2 = pi5.draw_cmos_inv(c, cache, xs[7], 0.65, 2.75, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss)
    xop = pi5.draw_cmos_inv(
        c, cache, xs[8], wn_out, wp_out, N_LVT, P_STD, 0.15, 0.15, nfn_out, nfp_out,
        y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=1.100,
    )

    ym_intp = grid(y_p - 0.950)
    ym_intn = grid(y_p - 1.600)
    ym_ckb  = grid(y_gp)
    ym_ck   = grid(y_gn)
    ym_qp   = ym_ckb
    ym_qn   = ym_ck

    via1_clean(c, tgp_p["g"][0], ym_ckb)
    via1_clean(c, tgn_p["g"][0], ym_ckb)
    c.wire("metal2", [(tgp_p["g"][0], ym_ckb), (tgn_p["g"][0], ym_ckb)], W_M2)

    via1_clean(c, tgp_n["g"][0], ym_ck)
    via1_clean(c, tgn_n["g"][0], ym_ck)
    c.wire("metal2", [(tgp_n["g"][0], ym_ck), (tgn_n["g"][0], ym_ck)], W_M2)

    x_rpd_m1 = grid(xs[2] + 0.680)
    c.wire("metal1", [(rp["d"][0], rp["d"][1]), (x_rpd_m1, rp["d"][1]), (x_rpd_m1, ym_intp)], W_M1)
    c.wire("metal1", [(k2["in"][0], k2["in"][1]), (k2["in"][0], ym_intp)], W_M1)
    x_xon_in = grid(xs[5] - 1.250)
    c.wire("metal1", [(xon["in"][0], xon["in"][1]), (x_xon_in, xon["in"][1]), (x_xon_in, ym_intp)], W_M1)
    for px in (x_tgp_d, k1["out"][0], x_rpd_m1, k2["in"][0], x_xon_in):
        via1_clean(c, px, ym_intp)
    c.wire("metal2", [(x_tgp_d, ym_intp), (x_xon_in, ym_intp)], W_M2)

    c.wire("metal1", [(k1["in"][0], k1["in"][1]), (k1["in"][0], ym_intn)], W_M1)
    c.wire("metal1", [(rn["d"][0], rn["d"][1]), (rn["d"][0], ym_intn)], W_M1)
    x_xop_in = grid(xs[8] - 1.250)
    c.wire("metal1", [(xop["in"][0], xop["in"][1]), (x_xop_in, xop["in"][1]), (x_xop_in, ym_intn)], W_M1)
    for px in (k1["in"][0], rn["d"][0], k2["out"][0], x_tgn_int, x_xop_in):
        via1_clean(c, px, ym_intn)
    c.wire("metal2", [(k1["in"][0], ym_intn), (x_xop_in, ym_intn)], W_M2)

    c.wire("metal1", [(cc2["in"][0], cc2["in"][1]), (cc2["in"][0], ym_qn)], W_M1)
    for px in (xon["out"][0], cc1["out"][0], cc2["in"][0]):
        via1_clean(c, px, ym_qn)
    c.wire("metal2", [(xon["out"][0], ym_qn), (cc2["in"][0], ym_qn)], W_M2)

    c.wire("metal1", [(cc1["in"][0], cc1["in"][1]), (cc1["in"][0], ym_qp)], W_M1)
    for px in (cc1["in"][0], cc2["out"][0], xop["out"][0]):
        via1_clean(c, px, ym_qp)
    c.wire("metal2", [(cc1["in"][0], ym_qp), (xop["out"][0], ym_qp)], W_M2)

    y_esc = grid(y_vss + 1.000)
    c.wire("metal1", [(x_dpin, tgp_n["s"][1]), (x_dpin, y_esc)], W_M1)
    c.wire("metal1", [(x_dnin, tgn_n["d"][1]), (x_dnin, y_esc)], W_M1)
    c.wire("metal1", [(xon["out"][0], xon["dn"][1]), (xon["out"][0], y_esc)], W_M1)
    c.wire("metal1", [(xop["out"][0], xop["dn"][1]), (xop["out"][0], y_esc)], W_M1)

    x_rstn_esc = grid(xs[2] - 0.680)
    y_rstn_lat_tap = grid(y_vss + 1.850)  # -6.800
    c.wire("metal1", [(rn["g"][0], rn["g"][1]), (x_rstn_esc, rn["g"][1]), (x_rstn_esc, y_rstn_lat_tap)], W_M1)
    y_rst_lat_tap = grid(y_gc)            # -5.100
    c.wire("metal1", [(rp["g"][0], rp["g"][1]), (rp["g"][0], y_rst_lat_tap)], W_M1)

    x_ckb_tap = grid(xs[0] + 1.450)
    via1_clean(c, x_ckb_tap, ym_ckb)
    c.wire("metal1", [(x_ckb_tap, ym_ckb), (x_ckb_tap, y_esc)], W_M1)

    extra_int: dict[str, tuple[float, float]] = {}
    if expose_int:
        c.wire("metal1", [(x_rpd_m1, rp["d"][1]), (x_rpd_m1, y_esc)], W_M1)
        c.wire("metal1", [(k2["out"][0], k2["dn"][1]), (k2["out"][0], y_esc)], W_M1)
        extra_int["intp_esc"] = (x_rpd_m1, y_esc)
        extra_int["intn_esc"] = (k2["out"][0], y_esc)

    return {
        "dp_in": (x_dpin, y_esc),
        "dn_in": (x_dnin, y_esc),
        "ckb": (tgp_p["g"][0], ym_ckb),
        "ckb_esc": (x_ckb_tap, y_esc),
        "ck": (tgp_n["g"][0], ym_ck),
        "rst_n_lat": (x_rstn_esc, y_rstn_lat_tap),
        "rst_lat": (rp["g"][0], y_rst_lat_tap),
        "qn": (xon["out"][0], y_esc),
        "qp": (xop["out"][0], y_esc),
        "x_end": grid(xs[8] + 1.650),
        **extra_int,
    }


def _draw_qdiv2_outpair_v2(
    c: Cell,
    cache: PdkCache,
    x_ctr: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
) -> dict:
    """Draw 1 v2 symmetric differential 1.25 GHz output pair (`2.40/12.00` + `cc 0.45/2.16`)."""
    x_ctr = grid(x_ctr)
    y_n = grid(y_n + 0.160)  # +5.360 -> y_ob=+5.010 (>=0.180 um met2.2 above y_trk_e2=+4.480 via2 pad!)
    x_ba = grid(x_ctr - 4.300)
    x_c1 = grid(x_ctr - 1.150)
    x_c2 = grid(x_ctr + 0.900)
    x_bb = grid(x_ctr + 4.450)

    def draw_big_inv(cx: float) -> dict:
        cx = grid(cx)
        pm = pi5.place_mos_col(c, cache, cx, P_STD, 12.00, 0.15, 4, y_p, True,  y_g, grid(y_p - 0.55), grid(y_p + 0.55))
        nm = pi5.place_mos_col(c, cache, cx, N_LVT,  2.40, 0.15, 2, y_n, False, y_g, grid(y_n + 0.35), grid(y_n - 0.35))
        for sx in pm["s_xs"]:
            c.wire("metal1", [(sx, pm["s"][1]), (sx, y_vdd)], 0.240)
        for sx in nm["s_xs"]:
            c.wire("metal1", [(sx, nm["s"][1]), (sx, y_vss)], 0.240)
        x_in = grid(cx - 1.250)
        c.wire("metal1", [(cx, y_g), (x_in, y_g)], W_M1)
        x_m2 = grid(cx + 0.580)
        via1_clean(c, pm["d_xs"][-1], pm["d"][1])
        via1_clean(c, pm["d_xs"][0], pm["d"][1])
        via1_clean(c, nm["d"][0], nm["d"][1])
        c.wire("metal2", [(pm["d_xs"][0], pm["d"][1]), (x_m2, pm["d"][1]), (x_m2, nm["d"][1]), (nm["d"][0], nm["d"][1])], 0.320)
        return {"in": (x_in, y_g), "out": (x_m2, grid(y_n - 0.35))}

    ba = draw_big_inv(x_ba)
    bb = draw_big_inv(x_bb)
    c1 = pi5.draw_cmos_inv(c, cache, x_c1, 0.45, 2.16, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p, y_n, y_g, y_vdd, y_vss)
    c2 = pi5.draw_cmos_inv(c, cache, x_c2, 0.45, 2.16, N_LVT, P_STD, 0.15, 0.15, 1, 1, y_p, y_n, y_g, y_vdd, y_vss)

    y_oa = grid(y_p + 0.55)
    y_ob = grid(y_n - 0.35)

    c.wire("metal1", [(c2["out"][0], y_oa), (c2["out"][0], c2["dp"][1])], W_M1)
    c.wire("metal1", [(c1["out"][0], c1["dn"][1]), (c1["out"][0], y_ob)], W_M1)
    c.rect("metal1", grid(c1["dn"][0] - 0.10), grid(y_ob - 0.16), grid(c1["out"][0] + 0.16), grid(c1["dn"][1] + 0.145))
    c.rect("metal1", grid(c2["dp"][0] - 0.10), grid(c2["dp"][1] - 0.145), grid(c2["out"][0] + 0.16), grid(y_oa + 0.16))

    via1_clean(c, c1["in"][0], c1["in"][1])
    via1_clean(c, c2["out"][0], y_oa)
    c.wire("metal2", [(ba["out"][0], y_oa), (c2["out"][0], y_oa)], 0.300)
    c.wire("metal2", [(c1["in"][0], y_oa), (c1["in"][0], c1["in"][1])], W_M2)

    via1_clean(c, c1["out"][0], y_ob)
    via1_clean(c, c2["in"][0], c2["in"][1])
    c.wire("metal2", [(c1["out"][0], y_ob), (bb["out"][0], y_ob)], 0.300)
    c.wire("metal2", [(c2["in"][0], y_ob), (c2["in"][0], c2["in"][1])], W_M2)

    return {
        "in_a": ba["in"],
        "in_b": bb["in"],
        "out_a_m2": (ba["out"][0], y_ob),
        "out_b_m2": (bb["out"][0], y_ob),
    }


def _draw_qdiv2_cc_align_v2(
    c: Cell,
    cache: PdkCache,
    x_ctr: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
    wn: float = 1.00,
    wp: float = 4.20,
    nfn: int = 1,
    nfp: int = 2,
) -> dict:
    """Draw multi-finger cross-coupled differential aligner (`pi4_cc_align_q`) in North row."""
    x_ctr = grid(x_ctr)
    x_c1 = grid(x_ctr - 1.350)
    x_c2 = grid(x_ctr + 1.350)
    c1 = draw_oct_inv(c, cache, x_c1, wn, wp, N_LVT, P_STD, 0.15, 0.15, nfn, nfp, y_p, y_n, y_g, y_vdd, y_vss, x_out_off=0.720)
    c2 = draw_oct_inv(c, cache, x_c2, wn, wp, N_LVT, P_STD, 0.15, 0.15, nfn, nfp, y_p, y_n, y_g, y_vdd, y_vss, x_out_off=0.720)
    y_oa = grid(y_p + 0.55)
    y_ob = grid(y_n - 0.35)
    c.wire("metal1", [(c2["out"][0], y_oa), (c2["out"][0], c2["dp"][1])], W_M1)
    c.wire("metal1", [(c1["out"][0], c1["dn"][1]), (c1["out"][0], y_ob)], W_M1)
    via1_clean(c, c1["in"][0], c1["in"][1])
    via1_clean(c, c2["out"][0], y_oa)
    c.wire("metal2", [(c1["in"][0], c1["in"][1]), (c1["in"][0], y_oa), (c2["out"][0], y_oa)], 0.300)
    via1_clean(c, c1["out"][0], y_ob)
    via1_clean(c, c2["in"][0], c2["in"][1])
    c.wire("metal2", [(c1["out"][0], y_ob), (c2["in"][0], y_ob), (c2["in"][0], c2["in"][1])], 0.300)
    return {"a": (c1["in"][0], y_oa), "b": (c2["in"][0], y_ob)}


def _draw_qdiv2_gated_inj_v2(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
    in_above: bool = False,
) -> dict:
    """Draw 1 static-gated D->E phase injection cell (`pi4_gated_inj`: N_LVT 1.40/0.15 nf=1, P_STD 4.40/0.15 nf=2).

    `inj_off` M2 runs horizontally at y_gp (+3.450) and `inj_en` M2 at y_gn (+4.000) — both >= 0.16 um clear of each
    other AND >= 0.16 um clear of y_trk_d3 (+4.485) via2 pads!
    """
    x_in  = grid(x0)
    x_en  = grid(x0 + 1.900)
    x_out = grid(x_en + 0.960)
    x_in_tap = grid(x_in - 0.800)
    y_n_inj = grid(y_n + 0.150)  # +5.350 (ndiff [4.65..6.05])
    y_gp = +3.490                # 0.28 um li.3 clear of pdiff top +3.050, 0.16 um met2.2 above y_trk_d2 (+3.000) via2!
    y_gn = +4.050                # 0.22 um poly.2 & 0.24 um met2.2 above y_gp (+3.490)!
    y_in_tap  = +5.850 if in_above else +2.700
    y_out_tap = +5.850

    # Col 0: input FETs (P_STD 4.00/0.15 nf=2, N_LVT 1.30/0.15 nf=1), shared gate at y_g (+3.850)
    pi_m = pi5.place_mos_col(c, cache, x_in, P_STD, 4.00, 0.15, 2, y_p,     True,  y_g, grid(y_p - 0.55),     grid(y_p + 0.55))
    ni_m = pi5.place_mos_col(c, cache, x_in, N_LVT, 1.30, 0.15, 1, y_n_inj, False, y_g, grid(y_n_inj + 0.35), grid(y_n_inj - 0.35))
    for sx in pi_m["s_xs"]:
        c.wire("metal1", [(sx, pi_m["s"][1]), (sx, y_vdd)], 0.220)
    c.wire("metal1", [(ni_m["s"][0], ni_m["s"][1]), (ni_m["s"][0], y_vss)], 0.220)
    c.wire("metal1", [(x_in, y_g), (x_in_tap, y_g), (x_in_tap, y_in_tap)], W_M1)

    # Col 1: enable FETs (P_STD 4.00/0.15 nf=2 gate=inj_off@y_gp, N_LVT 1.30/0.15 nf=1 gate=inj_en@y_gn)
    pe_m = pi5.place_mos_col(c, cache, x_en, P_STD, 4.00, 0.15, 2, y_p,     True,  y_gp, grid(y_p + 0.55),     grid(y_p - 0.55))
    ne_m = pi5.place_mos_col(c, cache, x_en, N_LVT, 1.30, 0.15, 1, y_n_inj, False, y_gn, grid(y_n_inj - 0.35), grid(y_n_inj + 0.35))

    # Internal series nodes sp (M1 at y_p+0.55) and sn (M1 at y_n_inj-0.35)
    c.wire("metal1", [(pi_m["d"][0], grid(y_p + 0.55)), (pe_m["s_xs"][-1], grid(y_p + 0.55))], W_M1)
    c.wire("metal1", [(ni_m["d"][0], grid(y_n_inj - 0.35)), (ne_m["s"][0], grid(y_n_inj - 0.35))], W_M1)

    # Output M1 bar at x_out (y_p-0.55 .. y_out_tap)
    c.wire("metal1", [(pe_m["d"][0], grid(y_p - 0.55)), (x_out, grid(y_p - 0.55))], W_M1)
    c.wire("metal1", [(ne_m["d"][0], grid(y_n_inj + 0.35)), (x_out, grid(y_n_inj + 0.35))], W_M1)
    c.wire("metal1", [(x_out, grid(y_p - 0.55)), (x_out, y_out_tap)], W_M1)

    return {
        "in": (x_in_tap, y_in_tap),
        "out": (x_out, y_out_tap),
        "inj_off": (x_en, y_gp),
        "inj_en": (x_en, y_gn),
    }


def _draw_qdiv2_lock_ctrl_v2(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
) -> dict:
    """Draw self-healing `pi4_e_lock_ctrl` in North row (`x0-1.6 .. x0+16.6`, XNOR West -> Xdet1/Xdet2 East):
      x0 + 0.00, 1.60, 3.20, 4.80 : 8-FET CMOS XNOR(d2, e0) [cols d2, e0, d0, e2] (short d0/d2 wiring!)
      x0 + 7.20                   : Xlpf_rst (N_STD 1.00/0.18 nf=1, gate=rst_lat, s->vss, d=v_lpf)
      x0 + 10.90                  : Xlpf_cap (N_STD 2.40/1.20 nf=2 MOSCAP, gate=v_lpf, s=d->vss)
      x0 + 14.00                  : Xdet1 (0.45/1.10 l=0.18, v_lpf -> inj_en)
      x0 + 15.85                  : Xdet2 (0.60/1.80 l=0.18, inj_en -> inj_off)
    """
    x0 = grid(x0)
    xs_x  = [grid(x0 + k * 1.600) for k in range(4)]  # 0=d2, 1=e0, 2=d0, 3=e2
    x_rst = grid(x0 + 7.200)
    x_cap = grid(x0 + 10.900)
    x_d1  = grid(x0 + 14.000)
    x_d2  = grid(x0 + 15.850)

    y_gp_en  = +3.490   # inj_off M2 bus!
    y_gn_en  = +4.050   # inj_en M2 bus!
    y_n_x    = grid(y_n + 0.150)   # +5.350
    y_vlpf_n = +6.050              # Top M2 bus for v_lpf (0.35 um above NMOS drain M1!)
    y_vlpf_p = +1.500              # Local M2 stitch c0.p.d <-> c2.p.d (strictly inside [c0.p.d .. c2.p.d]!)

    # 1. 8-FET CMOS XNOR(d2, e0): cols 0=d2, 1=e0, 2=d0, 3=e2
    pms = []
    nms = []
    for k, xk in enumerate(xs_x):
        if k in (0, 2):
            pm = pi5.place_mos_col(c, cache, xk, P_LVT, 1.60, 0.35, 1, y_p,   True,  y_g, grid(y_p + 0.45),   grid(y_p - 0.45))
            nm = pi5.place_mos_col(c, cache, xk, N_STD, 0.42, 0.50, 1, y_n_x, False, y_g, grid(y_n_x - 0.24), grid(y_n_x + 0.24))
        else:
            pm = pi5.place_mos_col(c, cache, xk, P_LVT, 1.60, 0.35, 1, y_p,   True,  y_g, grid(y_p - 0.45),   grid(y_p + 0.45))
            c.wire("metal1", [(pm["s"][0], pm["s"][1]), (pm["s"][0], y_vdd)], 0.220)
            nm = pi5.place_mos_col(c, cache, xk, N_STD, 0.42, 0.50, 1, y_n_x, False, y_g, grid(y_n_x + 0.24), grid(y_n_x - 0.24))
            c.wire("metal1", [(nm["s"][0], nm["s"][1]), (nm["s"][0], y_vss)], 0.220)
        pms.append(pm)
        nms.append(nm)

    # All 4 internal series nodes 100% on M1 (ZERO crossings!)
    c.wire("metal1", [pms[0]["s"], pms[1]["d"]], W_M1)  # sp1: c0.p.s -> c1.p.d
    c.wire("metal1", [pms[2]["s"], pms[3]["d"]], W_M1)  # sp2: c2.p.s -> c3.p.d
    c.wire("metal1", [nms[1]["d"], nms[2]["s"]], W_M1)  # sn2: c1.n.d -> c2.n.s
    c.wire("metal1", [nms[0]["s"], (nms[0]["s"][0], +4.650), (nms[3]["d"][0], +4.650), nms[3]["d"]], W_M1)  # sn1

    # Tie v_lpf across c0.p.d <-> c2.p.d on M2 at y_vlpf_p (+1.500), rise cleanly WEST of c0 on M2 at x_vl0 -> y_vlpf_n (+6.050)!
    x_vl0 = grid(xs_x[0] - 0.850)
    via1_clean(c, pms[0]["d"][0], y_vlpf_p)
    via1_clean(c, pms[2]["d"][0], y_vlpf_p)
    c.wire("metal2", [(x_vl0, y_vlpf_p), (pms[2]["d"][0], y_vlpf_p)], 0.380)
    c.wire("metal2", [(x_vl0, y_vlpf_p), (x_vl0, y_vlpf_n)], 0.300)
    for idx_v in (0, 2):
        nx_d = nms[idx_v]["d"][0]
        c.wire("metal1", [nms[idx_v]["d"], (nx_d, y_vlpf_n)], W_M1)
        via1_clean(c, nx_d, y_vlpf_n)

    # Clean M1 gate taps: d0 West of x_vl0 (0.60 um M2 clearance!); e0 East of e2 (xs_x[3])!
    x_d0_tap = grid(xs_x[0] - 1.450)
    x_e0_tap = grid(xs_x[3] + 0.900)
    c.wire("metal1", [(xs_x[2], y_g), (xs_x[2], +3.300), (x_d0_tap, +3.300)], W_M1)
    c.wire("metal1", [(xs_x[1], y_g), (xs_x[1], +4.250), (x_e0_tap, +4.250)], W_M1)

    # 2. Xlpf_rst (N_STD 1.00/0.18 nf=1 at x_rst, y_n_x, gate=rst_lat at y_g)
    rst_m = pi5.place_mos_col(c, cache, x_rst, N_STD, 1.00, 0.18, 1, y_n_x, False, y_g, grid(y_n_x + 0.35), grid(y_n_x - 0.35))
    c.wire("metal1", [(rst_m["s"][0], rst_m["s"][1]), (rst_m["s"][0], y_vss)], 0.220)
    x_rstd = grid(x_rst + 0.720)
    c.wire("metal1", [(rst_m["d"][0], rst_m["d"][1]), (x_rstd, rst_m["d"][1]), (x_rstd, y_vlpf_n)], W_M1)
    via1_clean(c, x_rstd, y_vlpf_n)

    # 3. Xlpf_cap (N_STD 1.20/1.20 nf=1 MOSCAP at x_cap, y_n_x -> 2x faster lock settle!)
    cap_m = pi5.place_mos_col(c, cache, x_cap, N_STD, 1.20, 1.20, 1, y_n_x, False, y_g, grid(y_n_x + 0.35), grid(y_n_x - 0.35))
    for sx in cap_m["s_xs"]:
        c.wire("metal1", [(sx, cap_m["s"][1]), (sx, y_vss)], 0.220)
    for dx in cap_m["d_xs"]:
        c.wire("metal1", [(dx, cap_m["d"][1]), (dx, y_vss)], 0.220)
    x_cap_g = grid(cap_m["s_xs"][0] - 0.650)
    c.wire("metal1", [(x_cap, y_g), (x_cap_g, y_g), (x_cap_g, y_vlpf_n)], W_M1)
    via1_clean(c, x_cap_g, y_vlpf_n)

    # 4. Xdet1 (0.85/1.10, v_lpf -> inj_en) & Xdet2 (0.60/1.80, inj_en -> inj_off) directly facing East local injectors!
    det1 = draw_oct_inv(c, cache, x_d1, 0.85, 1.10, N_STD, P_STD, 0.18, 0.18, 1, 1, y_p, y_n_x, y_g, y_vdd, y_vss, x_out_off=0.600)
    det2 = draw_oct_inv(c, cache, x_d2, 0.60, 1.80, N_STD, P_STD, 0.18, 0.18, 1, 1, y_p, y_n_x, y_g, y_vdd, y_vss, x_out_off=0.600)
    c.wire("metal1", [det1["out"], det2["in"]], W_M1)
    x_d1_in = grid(x_d1 - 0.850)
    c.wire("metal1", [det1["in"], (x_d1_in, y_g), (x_d1_in, y_vlpf_n)], W_M1)
    via1_clean(c, x_d1_in, y_vlpf_n)
    via1_clean(c, det1["out"][0], y_gn_en)
    via1_clean(c, det2["out"][0], y_gp_en)

    # Continuous horizontal v_lpf M2 bus across XNOR -> Xlpf_rst -> Xlpf_cap -> Xdet1.in!
    c.wire("metal2", [(x_vl0, y_vlpf_n), (x_d1_in, y_vlpf_n)], 0.380)

    return {
        "d2": (xs_x[0], y_g),
        "d0": (x_d0_tap, +3.300),
        "e0": (x_e0_tap, +4.250),
        "e2": (xs_x[3], y_g),
        "rst_lat": (x_rst, y_g),
        "inj_en": (det1["out"][0], y_gn_en),
        "inj_off": (det2["out"][0], y_gp_en),
    }


def _draw_qdiv2_dum_col_v2(
    c: Cell,
    cache: PdkCache,
    x0: float,
    p_model: str,
    wp: float,
    lp: float,
    n_model: str,
    wn: float,
    ln: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
) -> tuple[float, float]:
    """Draw 1 single-column capacitive load-matching dummy (s=d->vdd/vss, gate=(x0, y_g))."""
    x0 = grid(x0)
    pm = pi5.place_mos_col(c, cache, x0, p_model, wp, lp, 1, y_p, True,  y_g, grid(y_p - 0.35), grid(y_p + 0.35))
    nm = pi5.place_mos_col(c, cache, x0, n_model, wn, ln, 1, y_n, False, y_g, grid(y_n + 0.16), grid(y_n - 0.16))
    for pt in (pm["s"], pm["d"]):
        c.wire("metal1", [(pt[0], pt[1]), (pt[0], y_vdd)], 0.220)
    for pt in (nm["s"], nm["d"]):
        c.wire("metal1", [(pt[0], pt[1]), (pt[0], y_vss)], 0.220)
    return (x0, y_g)


def build_rx_qdiv2_8ph_v2_pdk(cache: PdkCache, add_ports: bool = False) -> tuple[Cell, dict]:
    """Build exact 1:1 hardened v2 `serdes_rx_qdiv2_8ph_4iq` (exact same 136.4 x 17.45 um bbox & 15 pins as pi5!)."""
    c = Cell()

    y_vdd   = 0.000
    y_p_s   = -2.400
    y_gp_s  = -4.600
    y_gc_s  = -5.100
    y_gn_s  = -5.600
    y_n_s   = -7.050
    y_vss_s = -8.650

    y_p_n   = +1.950
    y_gc_n  = +3.850
    y_n_n   = +5.200
    y_vss_n = +6.750

    x_left  = 0.000
    x_right = 136.400

    c.rect("nwell", grid(x_left - 0.60), -4.450, grid(x_right + 0.60), +3.650)
    draw_tap_h(c, "nsubdiff", x_left, x_right, y_vdd,   half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)
    draw_tap_h(c, "psubdiff", x_left, x_right, y_vss_s, half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)
    draw_tap_h(c, "psubdiff", x_left, x_right, y_vss_n, half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)

    pair_x_ctrs = {"d02": 19.600, "d13": 47.400, "e02": 94.600, "e13": 125.400}
    north_m2_xs = []
    for xc in pair_x_ctrs.values():
        north_m2_xs.extend([grid(xc - 4.300 + 0.580), grid(xc + 4.450 + 0.580)])

    # Split y_vss_n M3 over [71.80 .. 111.20] (solid 0.560 um M1 + psubdiff stays 100% continuous!)
    # so static DC `inj_en` [73.80 .. 109.20] runs cleanly at y=+6.750 M3 to Xdet2_e1 (0.0% M5!).
    x_vss_n_gap_l = 71.800
    x_vss_n_gap_r = 111.200
    for y_rail, m3_pw in ((y_vdd, 0.400), (y_vss_s, 0.600)):
        c.wire("metal3", [(x_left, y_rail), (x_right, y_rail)], m3_pw)
        xv = grid(x_left + 1.5)
        while xv <= x_right - 1.5 + 1e-6:
            via1_clean(c, xv, y_rail)
            via2_clean(c, xv, y_rail)
            xv = grid(xv + 12.0)

    c.wire("metal3", [(x_left, y_vss_n), (x_vss_n_gap_l, y_vss_n)], 0.400)
    c.wire("metal3", [(x_vss_n_gap_r, y_vss_n), (x_right, y_vss_n)], 0.400)
    vss_n_via_xs: list[float] = []
    xv = grid(x_left + 1.5)
    while xv <= x_right - 1.5 + 1e-6:
        if (xv <= x_vss_n_gap_l - 0.80 or xv >= x_vss_n_gap_r + 0.80) and not any(abs(xv - nx) < 1.20 for nx in north_m2_xs):
            vss_n_via_xs.append(xv)
        xv = grid(xv + 12.0)
    for xv_extra in (71.000, 112.000):
        if not any(abs(xv_extra - nx) < 1.20 for nx in north_m2_xs) and not any(abs(xv_extra - vx) < 1.0 for vx in vss_n_via_xs):
            vss_n_via_xs.append(xv_extra)
    for xv in vss_n_via_xs:
        via1_clean(c, xv, y_vss_n)
        via2_clean(c, xv, y_vss_n)

    for x_strap in (grid(x_left + 0.50), grid(x_right - 0.50)):
        via3_pad(c, x_strap, y_vss_s)
        via3_pad(c, x_strap, y_vss_n)
        c.wire("metal4", [(x_strap, y_vss_s), (x_strap, y_vss_n)], 0.600)

    # 1. Shared 3-stage staged reset chain (Xrst -> Xrst_d1 -> Xrst_d2) driving ALL 4 latches cleanly
    xrst = pi5.draw_cmos_inv(
        c, cache, 2.700, 2.00, 8.00, N_LVT, P_STD, 0.15, 0.15, 2, 4,
        y_p_s, y_n_s, y_gc_s, y_vdd, y_vss_s, x_out_off=1.050,
    )
    xrst_d1 = pi5.draw_cmos_inv(
        c, cache, 5.200, 0.60, 1.50, N_STD, P_STD, 0.18, 0.18, 1, 1,
        y_p_s, y_n_s, y_gc_s, y_vdd, y_vss_s, x_out_off=0.520,
    )
    xrst_d2 = pi5.draw_cmos_inv(
        c, cache, 7.000, 1.20, 3.00, N_STD, P_STD, 0.18, 0.18, 1, 1,
        y_p_s, y_n_s, y_gc_s, y_vdd, y_vss_s, x_out_off=0.520,
    )
    c.wire("metal1", [xrst["out"], xrst_d1["in"]], W_M1)
    c.wire("metal1", [xrst_d1["out"], xrst_d2["in"]], W_M1)

    # 2. 4 Matched Dual-Johnson Columns (PVT-balanced TG: D=2.90/7.50, E=4.00/10.80; Xop/Xon=3.40/13.20!)
    col_x0 = [10.400, 41.800, 73.200, 104.600]
    clk_specs = [
        ("dp", False, False, 2.90,  7.50),
        ("dn", True,  False, 2.90,  7.50),
        ("ep", False, True,  4.00, 10.80),
        ("en", True,  True,  4.00, 10.80),
    ]
    gates: dict[str, dict] = {}
    latches: dict[str, dict] = {}
    for (cname, clamp_hi, exp_int, wn_tg, wp_tg), x0 in zip(clk_specs, col_x0):
        cg = _draw_qdiv2_clkgate_v2(c, cache, x0, y_p_s, y_n_s, y_gp_s, y_gn_s, y_vdd, y_vss_s, clamp_hi=clamp_hi)
        lt = _draw_pi_diff_latch_v2(
            c, cache, grid(x0 + 11.150), y_p_s, y_n_s, y_gp_s, y_gn_s, y_vdd, y_vss_s,
            wn_out=3.40, wp_out=13.20, nfn_out=2, nfp_out=4, wn_tg=wn_tg, wp_tg=wp_tg, expose_int=exp_int,
        )
        gates[cname] = cg
        latches[cname] = lt
        via1_clean(c, cg["ck"][0], cg["ck"][1])
        c.wire("metal2", [(cg["ck"][0], cg["ck"][1]), (cg["ck"][0], lt["ck"][1]), lt["ck"]], W_M2)

    # 3. North Row: Local-Injector Placement (Xinj_e0 directly over Xle0, Xinj_e1 + Xdet2_e1 directly over Xle1 -> <=10 um int_p/n, 0 fF Miller C!)
    outpairs: dict[str, dict] = {}
    for pname, xctr in pair_x_ctrs.items():
        outpairs[pname] = _draw_qdiv2_outpair_v2(c, cache, xctr, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    cc_dck = _draw_qdiv2_cc_align_v2(c, cache, 35.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=1.00, wp=4.20, nfn=1, nfp=2)
    cc_eck = _draw_qdiv2_cc_align_v2(c, cache, 102.900, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=1.00, wp=4.20, nfn=1, nfp=2)

    # Self-healing XNOR lock controller in GAP 1 (x = 57.75 .. 75.70, XNOR West -> Xdet1/Xdet2 East)
    lctrl = _draw_qdiv2_lock_ctrl_v2(c, cache, 59.200, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    # Local Xle0 injectors directly above Xle0 (e0_intp = 8.5 um on y_trk_ck13, e0_intn = 5.9 um on Track 3 -> 0 fF Miller!)
    inj_e0p = _draw_qdiv2_gated_inj_v2(c, cache, 77.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, in_above=False)
    inj_e0n = _draw_qdiv2_gated_inj_v2(c, cache, 81.800, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, in_above=False)

    # Stitch local M2 `inj_en` (+4.000) & `inj_off` (+3.450) from lctrl straight East into inj_e0p & inj_e0n
    for inj_c in (inj_e0p, inj_e0n):
        via1_clean(c, inj_c["inj_en"][0], inj_c["inj_en"][1])
        via1_clean(c, inj_c["inj_off"][0], inj_c["inj_off"][1])
    c.wire("metal2", [lctrl["inj_en"],  inj_e0n["inj_en"]],  0.260)
    c.wire("metal2", [lctrl["inj_off"], inj_e0n["inj_off"]], 0.260)

    # Local Xdet2_e1 (inj_en -> inj_off_e1) + local Xle1 injectors directly above Xle1 (e1_intp = 5.9 um on y_trk_ck02, e1_intn = 3.2 um on Track 2 -> 0 fF Miller!)
    x_d2e1 = 109.200
    y_n_x = grid(y_n_n + 0.150)  # +5.350
    det2_e1 = draw_oct_inv(c, cache, x_d2e1, 0.60, 1.80, N_STD, P_STD, 0.18, 0.18, 1, 1, y_p_n, y_n_x, y_gc_n, y_vdd, y_vss_n, x_out_off=0.600)
    inj_e1p = _draw_qdiv2_gated_inj_v2(c, cache, 111.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, in_above=False)
    inj_e1n = _draw_qdiv2_gated_inj_v2(c, cache, 115.900, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, in_above=True)

    # Static DC `inj_en` bridge on y_vss_n (+6.750) M3 [73.80 .. 109.20] -> Xdet2_e1.in & inj_e1p/inj_e1n
    x_ien_w = grid(lctrl["inj_en"][0])  # 73.800
    c.wire("metal2", [(x_ien_w, +4.050), (x_ien_w, y_vss_n)], 0.300)
    via2_clean(c, x_ien_w, y_vss_n)
    c.wire("metal3", [(x_ien_w, y_vss_n), (x_d2e1, y_vss_n)], 0.300)
    via2_clean(c, x_d2e1, y_vss_n)
    c.wire("metal1", [det2_e1["in"], (x_d2e1, +4.050)], W_M1)
    via1_clean(c, x_d2e1, +4.050)
    c.wire("metal2", [(x_d2e1, y_vss_n), (x_d2e1, +4.050)], 0.300)
    via1_clean(c, det2_e1["out"][0], +3.490)
    for inj_c in (inj_e1p, inj_e1n):
        via1_clean(c, inj_c["inj_en"][0], inj_c["inj_en"][1])
        via1_clean(c, inj_c["inj_off"][0], inj_c["inj_off"][1])
    c.wire("metal2", [(x_d2e1, +4.050), inj_e1n["inj_en"]], 0.260)
    c.wire("metal2", [(det2_e1["out"][0], +3.490), inj_e1n["inj_off"]], 0.260)

    # 6 single-column 8-phase load-matching dummies (Xxd_d1/d3, Xxd_e1/e3 matching XNOR; Xdum_e1/e3 matching Xle0/Xle1!)
    xd_d1  = _draw_qdiv2_dum_col_v2(c, cache,  27.600, P_LVT, 1.60, 0.35, N_STD, 0.42, 0.50, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    xd_d3  = _draw_qdiv2_dum_col_v2(c, cache,  29.400, P_LVT, 1.60, 0.35, N_STD, 0.42, 0.50, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    dum_e1 = _draw_qdiv2_dum_col_v2(c, cache, 106.200, P_STD, 2.50, 0.15, N_LVT, 0.85, 0.15, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    dum_e3 = _draw_qdiv2_dum_col_v2(c, cache, 107.600, P_STD, 2.50, 0.15, N_LVT, 0.85, 0.15, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    xd_e1  = _draw_qdiv2_dum_col_v2(c, cache, 132.400, P_LVT, 1.60, 0.35, N_STD, 0.42, 0.50, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    xd_e3  = _draw_qdiv2_dum_col_v2(c, cache, 134.100, P_LVT, 1.60, 0.35, N_STD, 0.42, 0.50, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    # 4. Track definitions: 1-for-1 static-DC interleaved South clocks + 8 clean 0.740 um North tracks (d0 away from y_vdd!)
    y_trk_rstn_lat = -6.800
    y_trk_dp       = -5.950
    y_trk_rst_lat  = -5.100
    y_trk_dn       = -4.250
    y_trk_rstn     = -3.400
    y_trk_ep       = -2.550
    y_trk_rst      = -1.700
    y_trk_en       = -0.850
    y_rstn_west    = -5.950  # Exact drop-in West port Y (-5.950 -> 57.250 in top-level!)

    y_trk_d1   = +0.780  # T1: d1 [30.4 .. 110.8]
    y_trk_ckp  = +1.520  # T2: dp_ck | ep_ck | e1_intn [118.7 .. 122.0]
    y_trk_d0   = +2.260  # T3: d0 [22.8 .. 76.8] | e0_intn [84.6 .. 90.6] | e1 [93.2 .. 134.2]
    y_trk_d2   = +3.000  # T4: d2 [14.0 .. 81.0] | e3 [83.3 .. 134.1]
    y_trk_ckn  = +3.740  # T5: dn_ck | en_ck (and lctrl.rst_lat M4 drop at x=66.4!)
    y_trk_e2   = +4.480  # T6: e2 [64.0 .. 124.6] (below lctrl v_lpf M2 at +6.050!)
    y_trk_e0   = +5.220  # T7: e0 [64.9 .. 114.7] (below lctrl v_lpf M2 at +6.050!)
    y_trk_d3   = +5.960  # T8: d3 [20.5 .. 115.1] (M4 riser at 64.95 jumps over v_lpf M2!)

    y_trk_ck02  = +7.600
    y_trk_ck13  = +8.450
    y_north_pin = +8.800

    clk_names = ["dp", "dn", "ep", "en"]

    # `rst_n`: West port enters at y_rstn_west (-5.950) [0.00..2.70], jogs UP on M2 at xrst.in (2.70) to y_trk_rstn (-3.400)!
    x_rstn_hi = grid(max(
        max(gates[cn]["rst_n"][0] for cn in clk_names),
        max(gates[cn]["clmp_rst_pt"][0] for cn in clk_names if gates[cn]["clmp_rst_net"] == "rst_n"),
    ) + 0.500)
    c.wire("metal3", [(x_left, y_rstn_west), (xrst["in"][0], y_rstn_west)], 0.340)
    c.wire("metal3", [(xrst["in"][0], y_trk_rstn), (x_rstn_hi, y_trk_rstn)], 0.340)
    via1_clean(c, xrst["in"][0], xrst["in"][1])
    c.wire("metal2", [(xrst["in"][0], y_rstn_west), (xrst["in"][0], y_trk_rstn)], W_M2)
    via2_clean(c, xrst["in"][0], y_rstn_west)
    via2_clean(c, xrst["in"][0], y_trk_rstn)
    for cn in clk_names:
        gx, gy = gates[cn]["rst_n"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, y_trk_rstn)], W_M2)
        via2_clean(c, gx, y_trk_rstn)
        if gates[cn]["clmp_rst_net"] == "rst_n":
            cx, cy = gates[cn]["clmp_rst_pt"]
            via1_clean(c, cx, cy)
            c.wire("metal2", [(cx, cy), (cx, y_trk_rstn)], W_M2)
            via2_clean(c, cx, y_trk_rstn)

    # `rst`: Xrst.out -> all 4 ClkGates
    x_rst_hi = grid(max(
        max(gates[cn]["rst"][0] for cn in clk_names),
        max(gates[cn]["clmp_rst_pt"][0] for cn in clk_names if gates[cn]["clmp_rst_net"] == "rst"),
    ) + 0.500)
    c.wire("metal3", [(xrst["out"][0], y_trk_rst), (x_rst_hi, y_trk_rst)], 0.340)
    via1_clean(c, xrst["out"][0], xrst["out"][1])
    c.wire("metal2", [(xrst["out"][0], xrst["out"][1]), (xrst["out"][0], y_trk_rst)], W_M2)
    via2_clean(c, xrst["out"][0], y_trk_rst)
    for cn in clk_names:
        gx, gy = gates[cn]["rst"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, y_trk_rst)], W_M2)
        via2_clean(c, gx, y_trk_rst)
        if gates[cn]["clmp_rst_net"] == "rst":
            cx, cy = gates[cn]["clmp_rst_pt"]
            via1_clean(c, cx, cy)
            c.wire("metal2", [(cx, cy), (cx, y_trk_rst)], W_M2)
            via2_clean(c, cx, y_trk_rst)

    # Shared continuous `rst_n_lat` (Xrst_d1 -> ALL 4 latches Xld0, Xld1, Xle0, Xle1!)
    x_rstn_lat_hi = grid(latches["en"]["rst_n_lat"][0] + 0.500)
    c.wire("metal3", [(xrst_d1["out"][0], y_trk_rstn_lat), (x_rstn_lat_hi, y_trk_rstn_lat)], 0.340)
    via1_clean(c, xrst_d1["out"][0], xrst_d1["out"][1])
    c.wire("metal2", [(xrst_d1["out"][0], xrst_d1["out"][1]), (xrst_d1["out"][0], y_trk_rstn_lat)], W_M2)
    via2_clean(c, xrst_d1["out"][0], y_trk_rstn_lat)
    for cn in clk_names:
        lx, ly = latches[cn]["rst_n_lat"]
        via1_clean(c, lx, ly)
        via2_clean(c, lx, ly)

    # Shared continuous `rst_lat` (Xrst_d2 -> ALL 4 latches + vertical M4 drop to lctrl.rst_lat!)
    x_rst_lat_hi = grid(latches["en"]["rst_lat"][0] + 0.500)
    c.wire("metal3", [(xrst_d2["out"][0], y_trk_rst_lat), (x_rst_lat_hi, y_trk_rst_lat)], 0.340)
    via1_clean(c, xrst_d2["out"][0], xrst_d2["out"][1])
    via2_clean(c, xrst_d2["out"][0], y_trk_rst_lat)
    for cn in clk_names:
        rx, ry = latches[cn]["rst_lat"]
        via1_clean(c, rx, ry)
        via2_clean(c, rx, y_trk_rst_lat)

    # Drop lctrl.rst_lat straight DOWN on M4 to y_trk_rst_lat (-5.100) via y_trk_ckn (+3.740 -> clear of dn_ck/en_ck!)
    x_lrst = grid(lctrl["rst_lat"][0])  # 78.200
    y_lrst_top = y_trk_ckn              # +3.740 (between dn_ck<=51.2 and en_ck>=85.8 -> 100% FREE!)
    via1_clean(c, x_lrst, lctrl["rst_lat"][1])
    c.wire("metal2", [lctrl["rst_lat"], (x_lrst, y_lrst_top)], 0.400)
    via2_clean(c, x_lrst, y_lrst_top)
    via3_pad(c, x_lrst, y_lrst_top)
    c.wire("metal4", [(x_lrst, y_trk_rst_lat), (x_lrst, y_lrst_top)], 0.400)
    via3_pad(c, x_lrst, y_trk_rst_lat)

    # `dp, dn, ep, en` EQUAL-SPAN low-C horizontal M3 trunks [8.5 .. x_right]
    for cn, yt in (("dp", y_trk_dp), ("dn", y_trk_dn), ("ep", y_trk_ep), ("en", y_trk_en)):
        c.wire("metal3", [(8.500, yt), (x_right, yt)], 0.300)
        gx, gy = gates[cn]["ck_in"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, yt)], W_M2)
        via2_clean(c, gx, yt)

    # Conflict-free M4-vertical / M3-horizontal router for North-band nets
    north_specs = [
        ("ckd0", outpairs["d02"]["out_a_m2"],  11.000, y_trk_ck02),
        ("ckd2", outpairs["d02"]["out_b_m2"],  43.000, y_trk_ck02),
        ("ckd1", outpairs["d13"]["out_a_m2"],  27.000, y_trk_ck13),
        ("ckd3", outpairs["d13"]["out_b_m2"],  59.000, y_trk_ck13),
        ("cke0", outpairs["e02"]["out_a_m2"],  75.000, y_trk_ck02),
        ("cke2", outpairs["e02"]["out_b_m2"], 107.000, y_trk_ck02),
        ("cke1", outpairs["e13"]["out_a_m2"],  91.000, y_trk_ck13),
        ("cke3", outpairs["e13"]["out_b_m2"], 123.000, y_trk_ck13),
    ]
    m4_used: list[tuple[float, float, float, str]] = [
        (grid(x_left + 0.50), y_vss_s, y_vss_n, "vss"),
        (grid(x_right - 0.50), y_vss_s, y_vss_n, "vss"),
        (x_lrst, y_trk_rst_lat, y_lrst_top, "rst_lat"),
    ]
    m3_pads: list[tuple[float, float, str]] = [
        (x_lrst, y_lrst_top, "rst_lat"),
        (x_ien_w, y_vss_n, "inj_en"),
        (x_d2e1, y_vss_n, "inj_en"),
    ]
    m3_tracks_occ: dict[float, list[tuple[float, float, str]]] = {
        y_vdd: [(x_left, x_right, "vdd")],
        y_vss_s: [(x_left, x_right, "vss")],
        y_vss_n: [
            (x_left, x_vss_n_gap_l, "vss"),
            (x_ien_w, x_d2e1, "inj_en"),
            (x_vss_n_gap_r, x_right, "vss"),
        ],
        y_trk_rstn_lat: [(xrst_d1["out"][0], x_rstn_lat_hi, "rst_n_lat")],
        y_trk_rstn: [(xrst["in"][0], x_rstn_hi, "rst_n")],
        y_trk_rst_lat: [(xrst_d2["out"][0], x_rst_lat_hi, "rst_lat")],
        y_trk_rst: [(xrst["out"][0], x_rst_hi, "rst")],
        y_trk_dp: [(x_left, xrst["in"][0], "rst_n"), (8.500, x_right, "dp")],
        y_trk_dn: [(8.500, x_right, "dn")],
        y_trk_ep: [(8.500, x_right, "ep")],
        y_trk_en: [(8.500, x_right, "en")],
    }
    # Pre-register ALL power-rail via2 pads (y_vdd, y_vss_n) so Track 1 & Track 8 pads stay >= 0.86 um clear!
    xv_p = grid(x_left + 1.5)
    while xv_p <= x_right - 1.5 + 1e-6:
        m3_pads.append((xv_p, y_vdd, "vdd"))
        xv_p = grid(xv_p + 12.0)
    for xv in vss_n_via_xs:
        m3_pads.append((xv, y_vss_n, "vss"))

    # Pre-register North output sort M3 tracks & M4 pins so e0_intp on y_trk_ck13 avoids them cleanly!
    for nm, (ox, _oy), x_pin, y_sort in north_specs:
        m3_tracks_occ.setdefault(y_sort, []).append((min(ox, x_pin), max(ox, x_pin), nm))
        m4_used.append((x_pin, y_sort, y_north_pin, nm))

    def m4_free(x: float, y1: float, y2: float, net: str) -> bool:
        ya, yb = min(y1, y2) - 0.88, max(y1, y2) + 0.88
        for ux, uy1, uy2, unet in m4_used:
            if unet != net and abs(ux - x) < 0.96 and not (yb < uy1 or ya > uy2):
                return False
        return True

    def m3_pt_ok(x_c: float, y_c: float, net: str) -> bool:
        for ty, occs in m3_tracks_occ.items():
            # 0.745 um North track pitch: 0.745 - 0.260(pad) - 0.150(wire) = 0.335 >= 0.300 um met3.2!
            if abs(ty - y_c) < 0.72:
                for ox1, ox2, onet in occs:
                    if onet != net and (ox1 - 0.80) <= x_c <= (ox2 + 0.80):
                        return False
        for mx, my, mnet in m3_pads:
            # Never place two 0.52 um M3 pads directly opposite on adjacent tracks (0.82 um pad-to-pad!)
            if mnet != net and abs(mx - x_c) < 0.86 and abs(my - y_c) < 0.86:
                return False
        return True

    def route_bus_m3_m4(net: str, y_trk: float, pins: list[tuple[float, float, str]]) -> None:
        y_trk = grid(y_trk)
        xs_trk: list[float] = []
        for px, py, lyr in pins:
            px, py = grid(px), grid(py)
            chosen = None
            if py > 0.0:
                if m3_pt_ok(px, y_trk, net):
                    chosen = (px, y_trk)
                else:
                    for dx_n in (0.48, -0.48, 0.96, -0.96, 1.44, -1.44, 1.92, -1.92):
                        xc = grid(px + dx_n)
                        if m3_pt_ok(xc, y_trk, net):
                            chosen = (xc, y_trk)
                            break
            if chosen is None and m3_pt_ok(px, py, net) and m3_pt_ok(px, y_trk, net) and m4_free(px, py, y_trk, net):
                chosen = (px, py)
            if chosen is None:
                for dx_n in (0.24, -0.24, 0.48, -0.48, 0.72, -0.72, 0.96, -0.96, 1.20, -1.20, 1.44, -1.44, 1.92, -1.92, 2.40, -2.40):
                    xc = grid(px + dx_n)
                    if m3_pt_ok(xc, py, net) and m3_pt_ok(xc, y_trk, net) and m4_free(xc, py, y_trk, net):
                        chosen = (xc, py)
                        break
            if chosen is None:
                raise RuntimeError(f"No clean M3/M4 escape for net {net} pin {(px, py)} -> y_trk={y_trk}")
            xc, yc = chosen
            if lyr == "metal1":
                via1_clean(c, px, py)
            if abs(xc - px) > 0.01 or abs(yc - py) > 0.01:
                w_seg = 0.400 if (abs(xc - px) < 0.65 and abs(yc - py) < 0.65) else W_M2
                c.wire("metal2", [(px, py), (xc, py), (xc, yc)], w_seg)
            via2_clean(c, xc, yc)
            m3_pads.append((xc, yc, net))
            if abs(yc - y_trk) > 0.01:
                via3_pad(c, xc, yc)
                c.wire("metal4", [(xc, yc), (xc, y_trk)], 0.400)
                via3_pad(c, xc, y_trk)
                m4_used.append((xc, min(yc, y_trk), max(yc, y_trk), net))
                m3_pads.append((xc, y_trk, net))
            xs_trk.append(xc)
        x_lo, x_hi = min(xs_trk), max(xs_trk)
        if x_hi - x_lo > 0.01:
            c.wire("metal3", [(x_lo, y_trk), (x_hi, y_trk)], 0.300)
        m3_tracks_occ.setdefault(y_trk, []).append((x_lo, x_hi, net))

    # Matched Dual-Johnson D-channel buses (d0..d3) feeding latches, outpairs, local injectors, and XNOR
    route_bus_m3_m4("d0", y_trk_d0, [
        (latches["dp"]["qp"][0], latches["dp"]["qp"][1], "metal1"),
        (latches["dn"]["dp_in"][0], latches["dn"]["dp_in"][1], "metal1"),
        (outpairs["d02"]["in_b"][0], outpairs["d02"]["in_b"][1], "metal1"),
        (inj_e0p["in"][0], inj_e0p["in"][1], "metal1"),
        (lctrl["d0"][0], lctrl["d0"][1], "metal1"),
    ])
    route_bus_m3_m4("d2", y_trk_d2, [
        (latches["dp"]["qn"][0], latches["dp"]["qn"][1], "metal1"),
        (latches["dn"]["dn_in"][0], latches["dn"]["dn_in"][1], "metal1"),
        (outpairs["d02"]["in_a"][0], outpairs["d02"]["in_a"][1], "metal1"),
        (inj_e0n["in"][0], y_trk_d2, "metal1"),
        (lctrl["d2"][0], lctrl["d2"][1], "metal1"),
    ])
    route_bus_m3_m4("d1", y_trk_d1, [
        (latches["dn"]["qp"][0], latches["dn"]["qp"][1], "metal1"),
        (latches["dp"]["dn_in"][0], latches["dp"]["dn_in"][1], "metal1"),
        (outpairs["d13"]["in_b"][0], outpairs["d13"]["in_b"][1], "metal1"),
        (inj_e1p["in"][0], inj_e1p["in"][1], "metal1"),
        (xd_d1[0], xd_d1[1], "metal1"),
    ])
    # Route `e0` before `d3` so South pin Xle1.dp_in (114.70) stays unshifted (>=0.53 um clear of en_ck=113.85!)
    route_bus_m3_m4("e0", y_trk_e0, [
        (latches["ep"]["qp"][0], latches["ep"]["qp"][1], "metal1"),
        (latches["en"]["dp_in"][0], latches["en"]["dp_in"][1], "metal1"),
        (outpairs["e02"]["in_a"][0], outpairs["e02"]["in_a"][1], "metal1"),
        (lctrl["e0"][0], lctrl["e0"][1], "metal1"),
    ])
    route_bus_m3_m4("d3", y_trk_d3, [
        (latches["dn"]["qn"][0], latches["dn"]["qn"][1], "metal1"),
        (latches["dp"]["dp_in"][0], latches["dp"]["dp_in"][1], "metal1"),
        (outpairs["d13"]["in_a"][0], outpairs["d13"]["in_a"][1], "metal1"),
        (inj_e1n["in"][0], inj_e1n["in"][1], "metal1"),
        (xd_d3[0], xd_d3[1], "metal1"),
    ])

    # Remaining Matched Dual-Johnson E-channel buses (e2, e1, e3)
    route_bus_m3_m4("e2", y_trk_e2, [
        (latches["ep"]["qn"][0], latches["ep"]["qn"][1], "metal1"),
        (latches["en"]["dn_in"][0], latches["en"]["dn_in"][1], "metal1"),
        (outpairs["e02"]["in_b"][0], outpairs["e02"]["in_b"][1], "metal1"),
        (lctrl["e2"][0], lctrl["e2"][1], "metal1"),
    ])
    route_bus_m3_m4("e1", y_trk_d0, [
        (latches["en"]["qp"][0], latches["en"]["qp"][1], "metal1"),
        (latches["ep"]["dn_in"][0], latches["ep"]["dn_in"][1], "metal1"),
        (outpairs["e13"]["in_a"][0], outpairs["e13"]["in_a"][1], "metal1"),
        (dum_e1[0], dum_e1[1], "metal1"),
        (xd_e1[0], xd_e1[1], "metal1"),
    ])
    route_bus_m3_m4("e3", y_trk_d2, [
        (latches["en"]["qn"][0], latches["en"]["qn"][1], "metal1"),
        (latches["ep"]["dp_in"][0], latches["ep"]["dp_in"][1], "metal1"),
        (outpairs["e13"]["in_b"][0], outpairs["e13"]["in_b"][1], "metal1"),
        (dum_e3[0], dum_e3[1], "metal1"),
        (xd_e3[0], xd_e3[1], "metal1"),
    ])

    # 2.5 GHz Stage-2 latch clocks + Xcc_dck/Xcc_eck (0.00 fF extra load!)
    route_bus_m3_m4("dp_ck", y_trk_ckp, [
        (gates["dp"]["ck_esc"][0], gates["dp"]["ck_esc"][1], "metal1"),
        (latches["dn"]["ckb_esc"][0], latches["dn"]["ckb_esc"][1], "metal1"),
        (cc_dck["a"][0], cc_dck["a"][1], "metal2"),
    ])
    route_bus_m3_m4("dn_ck", y_trk_ckn, [
        (gates["dn"]["ck_esc"][0], gates["dn"]["ck_esc"][1], "metal1"),
        (latches["dp"]["ckb_esc"][0], latches["dp"]["ckb_esc"][1], "metal1"),
        (cc_dck["b"][0], cc_dck["b"][1], "metal2"),
    ])
    route_bus_m3_m4("ep_ck", y_trk_ckp, [
        (gates["ep"]["ck_esc"][0], gates["ep"]["ck_esc"][1], "metal1"),
        (latches["en"]["ckb_esc"][0], latches["en"]["ckb_esc"][1], "metal1"),
        (cc_eck["a"][0], cc_eck["a"][1], "metal2"),
    ])
    route_bus_m3_m4("en_ck", y_trk_ckn, [
        (gates["en"]["ck_esc"][0], gates["en"]["ck_esc"][1], "metal1"),
        (latches["ep"]["ckb_esc"][0], latches["ep"]["ckb_esc"][1], "metal1"),
        (cc_eck["b"][0], cc_eck["b"][1], "metal2"),
    ])

    # 4 Local Short-Hop D->E Phase-Injection outputs (3.2 - 8.5 um each, ZERO differential Miller C!)
    # `e0_intn` [84.6..90.6] on T3 (+2.260) & `e1_intn` [118.7..122.0] on T2 (+1.520) tap straight off x_out M1 bar!
    route_bus_m3_m4("e0_intn", y_trk_d0, [
        (inj_e0n["out"][0], y_trk_d0, "metal1"),
        (latches["ep"]["intn_esc"][0], latches["ep"]["intn_esc"][1], "metal1"),
    ])
    route_bus_m3_m4("e0_intp", y_trk_ck13, [
        (inj_e0p["out"][0], inj_e0p["out"][1], "metal1"),
        (latches["ep"]["intp_esc"][0], latches["ep"]["intp_esc"][1], "metal1"),
    ])
    route_bus_m3_m4("e1_intp", y_trk_ck02, [
        (inj_e1p["out"][0], inj_e1p["out"][1], "metal1"),
        (latches["en"]["intp_esc"][0], latches["en"]["intp_esc"][1], "metal1"),
    ])
    route_bus_m3_m4("e1_intn", y_trk_ckp, [
        (inj_e1n["out"][0], y_trk_ckp, "metal1"),
        (latches["en"]["intn_esc"][0], latches["en"]["intn_esc"][1], "metal1"),
    ])

    north_pins: dict[str, tuple[float, float]] = {}
    for nm, (ox, oy), x_pin, y_sort in north_specs:
        c.wire("metal2", [(ox, oy), (ox, y_sort)], 0.360)
        via2_clean(c, ox, y_sort)
        c.wire("metal3", [(min(ox, x_pin), y_sort), (max(ox, x_pin), y_sort)], 0.360)
        via3_pad(c, x_pin, y_sort)
        c.wire("metal4", [(x_pin, y_sort), (x_pin, y_north_pin)], 0.440)
        north_pins[nm] = (x_pin, y_north_pin)

    meta = {
        "dp": (x_right, y_trk_dp),
        "dn": (x_right, y_trk_dn),
        "ep": (x_right, y_trk_ep),
        "en": (x_right, y_trk_en),
        "rst_n": (x_left, y_rstn_west),
        "vdd": (x_left, y_vdd),
        "vss": (x_left, y_vss_s),
        "vdd_e": (x_right, y_vdd),
        "vss_e": (x_right, y_vss_s),
        **north_pins,
    }
    return c, meta


# ---------------------------------------------------------------------------
# 3C. Cold-MC-Hardened v3 `serdes_rx_qdiv2_8ph_4iq` (Full-Strength Hybrid-PMOS
#     Clock Buffers / Latches / Output Buffers + Zero-Stack 2-FET TG Injectors
#     + Balanced Fast XNOR & Centered LVT-P Xdet1; Exact 1:1 Drop-In!)
# ---------------------------------------------------------------------------

def _draw_qdiv2_clkgate_v3(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_gp: float,
    y_gn: float,
    y_vdd: float,
    y_vss: float,
    clamp_hi: bool = False,
) -> dict:
    """Draw 1 v3 symmetric TG-isolated reset-gated 2.5 GHz Hybrid-PMOS clock slice:
      Col 0 (x0 + 0.00): Xtg    (pi4_tgate_lvt wn=2.60 nfn=2, wp=6.80 l=0.35 nfp=3)
      Col 1 (x0 + 2.20): Xclmp  (nfet 0.80/0.18 if lo; pfet 1.60/0.18 if hi)
      Col 2 (x0 + 3.60 / 5.09): Xinv   (pi4_inv_hyb wn=2.20 nf2, wps=7.00 nf2, wpl=2.80 nf1)
      Col 3 (x0 + 7.12 / 9.09): Xg_inv (pi4_inv_hyb wn=3.00 nf2, wps=12.60 nf4, wpl=3.50 nf1)
    """
    x0 = grid(x0)
    x_tg    = grid(x0)
    x_cl    = grid(x0 + 2.150)
    x_i1_ps = grid(x0 + 3.550)
    x_i1_pl = grid(x0 + 5.040)
    x_i2_ps = grid(x0 + 7.020)
    x_i2_pl = grid(x0 + 8.990)
    y_gc = grid((y_gp + y_gn) / 2.0)

    tgp = pi5.place_mos_col(c, cache, x_tg, P_LVT, 6.80, 0.35, 3, y_p, True,  y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
    tgn = pi5.place_mos_col(c, cache, x_tg, N_LVT, 2.60, 0.15, 2, y_n, False, y_gn, grid(y_n - 0.35), grid(y_n + 0.35))

    x_ckin = grid(x_tg - 1.150)
    c.rect("metal1", grid(x_ckin - 0.09), grid(tgp["s"][1] - 0.145), grid(tgp["s_xs"][0] + 0.145), grid(tgp["s"][1] + 0.145))
    c.rect("metal1", grid(x_ckin - 0.09), grid(tgn["s"][1] - 0.145), grid(tgn["s_xs"][0] + 0.145), grid(tgn["s"][1] + 0.145))
    c.wire("metal1", [(x_ckin, tgp["s"][1]), (x_ckin, tgn["s"][1])], W_M1)

    x_ckg = grid(x_tg + 1.300)
    c.rect("metal1", grid(tgp["d_xs"][-1] - 0.145), grid(tgp["d"][1] - 0.145), grid(x_ckg + 0.09), grid(tgp["d"][1] + 0.145))
    c.rect("metal1", grid(tgn["d_xs"][-1] - 0.145), grid(tgn["d"][1] - 0.145), grid(x_ckg + 0.09), grid(tgn["d"][1] + 0.145))
    c.wire("metal1", [(x_ckg, tgp["d"][1]), (x_ckg, tgn["d"][1])], W_M1)

    if not clamp_hi:
        clmp = pi5.place_mos_col(c, cache, x_cl, N_STD, 0.80, 0.18, 1, y_n, False, y_gn, grid(y_n - 0.25), grid(y_n + 0.25))
        c.wire("metal1", [(clmp["s"][0], clmp["s"][1]), (clmp["s"][0], y_vss)], 0.220)
        c.wire("metal1", [(x_ckg, clmp["d"][1]), (clmp["d"][0], clmp["d"][1])], W_M1)
        clmp_gate_net = "rst"
        clmp_gate_pt = (clmp["g"][0], y_gc)
        c.wire("metal1", [(clmp["g"][0], clmp["g"][1]), clmp_gate_pt], W_M1)
    else:
        clmp = pi5.place_mos_col(c, cache, x_cl, P_STD, 1.60, 0.18, 1, y_p, True, y_gp, grid(y_p + 0.45), grid(y_p - 0.45))
        c.wire("metal1", [(clmp["s"][0], clmp["s"][1]), (clmp["s"][0], y_vdd)], 0.220)
        c.wire("metal1", [(x_ckg, clmp["d"][1]), (clmp["d"][0], clmp["d"][1])], W_M1)
        clmp_gate_net = "rst_n"
        clmp_gate_pt = (clmp["g"][0], y_gp)

    inv1 = draw_hyb_inv(
        c, cache, x_i1_ps, 2.50, 7.00, 3.50, 2, 2, 1,
        y_p, y_n, y_gc, y_vdd, y_vss,
        x_ps=x_i1_ps, x_pl=x_i1_pl, x_n=x_i1_ps, x_out_off=0.560,
    )
    y_ckg_br = grid(y_p - 0.45) if not clamp_hi else grid(y_n + 0.35)
    x_i1_in_l = grid(x_i1_ps - 0.800)
    c.wire("metal1", [(x_ckg, y_ckg_br), (x_i1_in_l, y_ckg_br), (x_i1_in_l, y_gc), (x_i1_ps, y_gc)], W_M1)

    inv2 = draw_hyb_inv(
        c, cache, x_i2_ps, 3.50, 14.00, 3.50, 2, 4, 1,
        y_p, y_n, y_gc, y_vdd, y_vss,
        x_ps=x_i2_ps, x_pl=x_i2_pl, x_n=x_i2_ps, x_out_off=0.600,
    )
    y_ckb_m1 = grid(y_gp)
    c.wire("metal1", [(inv1["out"][0], y_ckb_m1), (x_i2_ps, y_ckb_m1), (x_i2_ps, y_gc)], W_M1)

    y_esc = grid(y_vss + 1.000)
    c.wire("metal1", [(inv2["out"][0], inv2["dn"][1]), (inv2["out"][0], y_esc)], W_M1)

    x_tgn_g = grid(tgn["g"][0] + 0.700)
    c.wire("metal1", [(tgp["g"][0], tgp["g"][1]), (tgp["g"][0], y_gc)], W_M1)
    c.wire("metal1", [(tgn["g"][0], tgn["g"][1]), (x_tgn_g, y_gn)], W_M1)

    return {
        "ck_in": (x_ckin, y_gc),
        "rst_n": (x_tgn_g, y_gn),
        "rst":   (tgp["g"][0], y_gc),
        "clmp_rst_net": clmp_gate_net,
        "clmp_rst_pt": clmp_gate_pt,
        "ck": (inv2["out"][0], grid(y_gn)),
        "ck_esc": (inv2["out"][0], y_esc),
        "x_end": grid(inv2["out"][0] + 0.250),
    }


def _draw_pi_diff_latch_v3(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_gp: float,
    y_gn: float,
    y_vdd: float,
    y_vss: float,
    wn_tg: float = 2.40,
    wps_tg: float = 4.80,
    wpl_tg: float = 1.80,
    wn_out: float = 3.80,
    wps_out: float = 10.50,
    wpl_out: float = 3.50,
    expose_int: bool = False,
) -> dict:
    """Draw 1 v3 Hybrid-PMOS `pi4_diff_latch` / `pi4_diff_latch_e` (Hybrid TG, LVT-P keepers & aligners, Hybrid Xop/Xon)."""
    x0 = grid(x0)
    xs = [
        grid(x0 + 0.000),   # 0: Xtgp (ps/n at +0.00, pl at +1.50)
        grid(x0 + 2.950),   # 1: Xk1 (LVT-P 0.60/0.35, N_STD 0.60/0.28)
        grid(x0 + 4.700),   # 2: Xrp/Xrn (rst_lat / rst_n_lat)
        grid(x0 + 6.250),   # 3: Xk2 (LVT-P 0.60/0.35, N_STD 0.60/0.28)
        grid(x0 + 9.450),   # 4: Xtgn (pl at +7.95, ps/n at +9.45)
        grid(x0 + 11.650),  # 5: Xon (ps/n at +11.65, pl at +13.40)
        grid(x0 + 15.000),  # 6: Xcc1 (N_LVT 0.65, P_LVT 2.10)
        grid(x0 + 16.350),  # 7: Xcc2 (N_LVT 0.65, P_LVT 2.10)
        grid(x0 + 18.200),  # 8: Xop (ps/n at +18.20, pl at +19.95)
    ]
    y_gc = grid((y_gp + y_gn) / 2.0)
    sp_y, dp_y = grid(y_p + 0.45), grid(y_p - 0.45)
    sn_y, dn_y = grid(y_n - 0.35), grid(y_n + 0.35)

    # Col 0: Hybrid-PMOS Xtgp (tgp_ps nf=2 + tgp_pl nf=1 + tgp_n nf=2)
    # Gate ckb tied on M2 via ym_ckb (leaves y_gp M1 clear so x_tgp_d drops at xs[0]+0.85, leaving x_tgp_pl empty in NMOS row for ckb_esc!)
    x_tgp_pl = grid(xs[0] + 1.500)
    tgp_ps = pi5.place_mos_col(c, cache, xs[0],    P_STD, wps_tg, 0.15, 2, y_p, True,  y_gp, sp_y, dp_y)
    tgp_pl = pi5.place_mos_col(c, cache, x_tgp_pl, P_LVT, wpl_tg, 0.35, 1, y_p, True,  y_gp, sp_y, dp_y)
    tgp_n  = pi5.place_mos_col(c, cache, xs[0],    N_LVT, wn_tg,  0.15, 2, y_n, False, y_gn, sn_y, dn_y)
    x_dpin = grid(xs[0] - 0.900)
    c.rect("metal1", grid(x_dpin - 0.09), grid(sp_y - 0.145), grid(tgp_pl["s_xs"][-1] + 0.145), grid(sp_y + 0.145))
    c.rect("metal1", grid(x_dpin - 0.09), grid(sn_y - 0.145), grid(tgp_n["s_xs"][-1] + 0.145), grid(sn_y + 0.145))
    c.wire("metal1", [(x_dpin, sp_y), (x_dpin, sn_y)], W_M1)
    x_tgp_d = grid(xs[0] + 0.850)
    c.rect("metal1", grid(tgp_ps["d_xs"][0] - 0.145), grid(dp_y - 0.145), grid(tgp_pl["d_xs"][-1] + 0.145), grid(dp_y + 0.145))
    c.rect("metal1", grid(tgp_n["d_xs"][0] - 0.145),  grid(dn_y - 0.145), grid(x_tgp_d + 0.09), grid(dn_y + 0.145))
    c.wire("metal1", [(x_tgp_d, dp_y), (x_tgp_d, dn_y)], W_M1)

    # Col 1-3: LVT-P keepers (Xk1, Xk2) & reset FETs (Xrp, Xrn)
    k1 = draw_oct_inv(c, cache, xs[1], 0.60, 0.60, N_STD, P_LVT, 0.28, 0.35, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=0.530)
    rn = pi5.place_mos_col(c, cache, xs[2], P_STD, 1.80, 0.18, 1, y_p, True,  y_gp, sp_y, dp_y)
    rp = pi5.place_mos_col(c, cache, xs[2], N_STD, 1.00, 0.18, 1, y_n, False, y_gn, grid(y_n - 0.25), grid(y_n + 0.25))
    c.wire("metal1", [(rn["s"][0], rn["s"][1]), (rn["s"][0], y_vdd)], 0.220)
    c.wire("metal1", [(rp["s"][0], rp["s"][1]), (rp["s"][0], y_vss)], 0.220)
    k2 = draw_oct_inv(c, cache, xs[3], 0.60, 0.60, N_STD, P_LVT, 0.28, 0.35, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=0.530)

    # Col 4: Hybrid-PMOS Xtgn (tgn_pl nf=1 at xs[4]-1.50 + tgn_ps nf=2 + tgn_n nf=2 at xs[4])
    x_tgn_pl = grid(xs[4] - 1.500)
    tgn_pl = pi5.place_mos_col(c, cache, x_tgn_pl, P_LVT, wpl_tg, 0.35, 1, y_p, True,  y_gp, sp_y, dp_y)
    tgn_ps = pi5.place_mos_col(c, cache, xs[4],    P_STD, wps_tg, 0.15, 2, y_p, True,  y_gp, sp_y, dp_y)
    tgn_n  = pi5.place_mos_col(c, cache, xs[4],    N_LVT, wn_tg,  0.15, 2, y_n, False, y_gn, sn_y, dn_y)
    x_tgn_int = grid(xs[4] - 2.200)
    c.rect("metal1", grid(x_tgn_int - 0.09), grid(sp_y - 0.145), grid(tgn_ps["s_xs"][-1] + 0.145), grid(sp_y + 0.145))
    c.rect("metal1", grid(x_tgn_int - 0.09), grid(sn_y - 0.145), grid(tgn_n["s_xs"][-1] + 0.145), grid(sn_y + 0.145))
    c.wire("metal1", [(x_tgn_int, sp_y), (x_tgn_int, sn_y)], W_M1)
    x_dnin = grid(xs[4] + 0.950)
    c.rect("metal1", grid(tgn_pl["d_xs"][0] - 0.145), grid(dp_y - 0.145), grid(x_dnin + 0.09), grid(dp_y + 0.145))
    c.rect("metal1", grid(tgn_n["d_xs"][0] - 0.145),  grid(dn_y - 0.145), grid(x_dnin + 0.09), grid(dn_y + 0.145))
    c.wire("metal1", [(x_dnin, dp_y), (x_dnin, dn_y)], W_M1)

    # Col 5-8: Hybrid-PMOS Xon/Xop (3.80 / 10.50+3.50) + LVT-P Xcc1/Xcc2 (0.65 / 2.10)
    xon = draw_hyb_inv(
        c, cache, xs[5], wn_out, wps_out, wpl_out, 2, 3, 1,
        y_p, y_n, y_gc, y_vdd, y_vss,
        x_ps=xs[5], x_pl=grid(xs[5] + 1.750), x_n=xs[5], x_out_off=0.620,
    )
    cc1 = draw_oct_inv(c, cache, xs[6], 0.65, 2.10, N_LVT, P_LVT, 0.15, 0.35, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=0.540)
    cc2 = draw_oct_inv(c, cache, xs[7], 0.65, 2.10, N_LVT, P_LVT, 0.15, 0.35, 1, 1, y_p, y_n, y_gc, y_vdd, y_vss, x_out_off=0.540)
    xop = draw_hyb_inv(
        c, cache, xs[8], wn_out, wps_out, wpl_out, 2, 3, 1,
        y_p, y_n, y_gc, y_vdd, y_vss,
        x_ps=xs[8], x_pl=grid(xs[8] + 1.750), x_n=xs[8], x_out_off=0.620,
    )

    ym_intp = grid(y_p - 0.950)
    ym_intn = grid(y_p - 1.600)
    ym_ckb  = grid(y_gp)
    ym_ck   = grid(y_gn)
    ym_qp   = ym_ckb
    ym_qn   = ym_ck

    for gx_ckb in (tgp_ps["g"][0], tgp_pl["g"][0], tgn_pl["g"][0], tgn_ps["g"][0]):
        via1_clean(c, gx_ckb, ym_ckb)
    c.wire("metal2", [(tgp_ps["g"][0], ym_ckb), (tgn_ps["g"][0], ym_ckb)], W_M2)

    via1_clean(c, tgp_n["g"][0], ym_ck)
    via1_clean(c, tgn_n["g"][0], ym_ck)
    c.wire("metal2", [(tgp_n["g"][0], ym_ck), (tgn_n["g"][0], ym_ck)], W_M2)

    x_rpd_m1 = grid(xs[2] + 0.650)
    c.wire("metal1", [(rp["d"][0], rp["d"][1]), (x_rpd_m1, rp["d"][1]), (x_rpd_m1, ym_intp)], W_M1)
    c.wire("metal1", [(k2["in"][0], k2["in"][1]), (k2["in"][0], ym_intp)], W_M1)
    # Straight vertical M1 from xon.in (xs[5], y_gc) up to ym_intp (-3.350, 0.21 um clear of dp_y=-2.85!)
    x_xon_in = xs[5]
    c.wire("metal1", [(x_xon_in, y_gc), (x_xon_in, ym_intp)], W_M1)
    for px in (x_tgp_d, k1["out"][0], x_rpd_m1, k2["in"][0], x_xon_in):
        via1_clean(c, px, ym_intp)
    c.wire("metal2", [(x_tgp_d, ym_intp), (x_xon_in, ym_intp)], W_M2)

    c.wire("metal1", [(k1["in"][0], k1["in"][1]), (k1["in"][0], ym_intn)], W_M1)
    c.wire("metal1", [(rn["d"][0], rn["d"][1]), (rn["d"][0], ym_intn)], W_M1)
    x_xop_in = xs[8]
    c.wire("metal1", [(x_xop_in, y_gc), (x_xop_in, ym_intn)], W_M1)
    for px in (k1["in"][0], rn["d"][0], k2["out"][0], x_tgn_int, x_xop_in):
        via1_clean(c, px, ym_intn)
    c.wire("metal2", [(k1["in"][0], ym_intn), (x_xop_in, ym_intn)], W_M2)

    c.wire("metal1", [(cc2["in"][0], cc2["in"][1]), (cc2["in"][0], ym_qn)], W_M1)
    for px in (xon["out"][0], cc1["out"][0], cc2["in"][0]):
        via1_clean(c, px, ym_qn)
    c.wire("metal2", [(xon["out"][0], ym_qn), (cc2["in"][0], ym_qn)], W_M2)

    c.wire("metal1", [(cc1["in"][0], cc1["in"][1]), (cc1["in"][0], ym_qp)], W_M1)
    for px in (cc1["in"][0], cc2["out"][0], xop["out"][0]):
        via1_clean(c, px, ym_qp)
    c.wire("metal2", [(cc1["in"][0], ym_qp), (xop["out"][0], ym_qp)], W_M2)

    y_esc = grid(y_vss + 1.000)
    c.wire("metal1", [(x_dpin, sn_y), (x_dpin, y_esc)], W_M1)
    c.wire("metal1", [(x_dnin, dn_y), (x_dnin, y_esc)], W_M1)
    c.wire("metal1", [(xon["out"][0], xon["dn"][1]), (xon["out"][0], y_esc)], W_M1)
    c.wire("metal1", [(xop["out"][0], xop["dn"][1]), (xop["out"][0], y_esc)], W_M1)

    x_rstn_esc = grid(xs[2] - 0.750)
    y_rstn_lat_tap = grid(y_vss + 1.850)  # -6.800
    c.wire("metal1", [(rn["g"][0], rn["g"][1]), (x_rstn_esc, rn["g"][1]), (x_rstn_esc, y_rstn_lat_tap)], W_M1)
    y_rst_lat_tap = grid(y_gc)            # -5.100
    c.wire("metal1", [(rp["g"][0], rp["g"][1]), (rp["g"][0], y_rst_lat_tap)], W_M1)

    # Drop ckb_esc cleanly under tgp_pl (xs[0]+1.500: empty in NMOS row!)
    x_ckb_tap = x_tgp_pl
    via1_clean(c, x_ckb_tap, ym_ckb)
    c.wire("metal1", [(x_ckb_tap, ym_ckb), (x_ckb_tap, y_esc)], W_M1)

    extra_int: dict[str, tuple[float, float]] = {}
    if expose_int:
        c.wire("metal1", [(x_rpd_m1, rp["d"][1]), (x_rpd_m1, y_esc)], W_M1)
        c.wire("metal1", [(k2["out"][0], k2["dn"][1]), (k2["out"][0], y_esc)], W_M1)
        extra_int["intp_esc"] = (x_rpd_m1, y_esc)
        extra_int["intn_esc"] = (k2["out"][0], y_esc)

    return {
        "dp_in": (x_dpin, y_esc),
        "dn_in": (x_dnin, y_esc),
        "ckb": (tgp_ps["g"][0], ym_ckb),
        "ckb_esc": (x_ckb_tap, y_esc),
        "ck": (tgp_n["g"][0], ym_ck),
        "rst_n_lat": (x_rstn_esc, y_rstn_lat_tap),
        "rst_lat": (rp["g"][0], y_rst_lat_tap),
        "qn": (xon["out"][0], y_esc),
        "qp": (xop["out"][0], y_esc),
        "x_end": grid(xop["out"][0] + 0.250),
        **extra_int,
    }


def _draw_qdiv2_outpair_v3(
    c: Cell,
    cache: PdkCache,
    x_ctr: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
) -> dict:
    """Draw 1 v3 Hybrid-PMOS 1.25 GHz output pair (`2.60 / 9.00+3.00` + LVT-P `cc 0.45/1.40`)."""
    x_ctr = grid(x_ctr)
    y_n = grid(y_n + 0.160)  # +5.360 -> y_ob=+5.010 (>=0.180 um met2.2 above y_trk_e2=+4.480 via2 pad!)
    x_ba_ps = grid(x_ctr - 4.750)
    x_ba_pl = grid(x_ctr - 3.000)
    x_c1    = grid(x_ctr - 0.900)
    x_c2    = grid(x_ctr + 0.900)
    x_bb_ps = grid(x_ctr + 3.200)
    x_bb_pl = grid(x_ctr + 4.950)

    def draw_big_hyb(x_ps: float, x_pl: float) -> dict:
        pms = pi5.place_mos_col(c, cache, x_ps, P_STD, 9.00, 0.15, 3, y_p, True,  y_g, grid(y_p - 0.55), grid(y_p + 0.55))
        pml = pi5.place_mos_col(c, cache, x_pl, P_LVT, 3.00, 0.35, 1, y_p, True,  y_g, grid(y_p - 0.55), grid(y_p + 0.55))
        nm  = pi5.place_mos_col(c, cache, x_ps, N_LVT, 2.60, 0.15, 2, y_n, False, y_g, grid(y_n + 0.35), grid(y_n - 0.35))
        for sx in pms["s_xs"] + pml["s_xs"]:
            c.wire("metal1", [(sx, pms["s"][1]), (sx, y_vdd)], 0.240)
        for sx in nm["s_xs"]:
            c.wire("metal1", [(sx, nm["s"][1]), (sx, y_vss)], 0.240)
        x_in = grid(x_ps - 1.050)
        c.wire("metal1", [(x_in, y_g), (x_pl, y_g)], W_M1)
        x_m2 = grid(x_pl + 0.650)
        dp_y = grid(y_p + 0.55)
        dn_y = grid(y_n - 0.35)
        all_pd = pms["d_xs"] + pml["d_xs"]
        c.rect("metal1", grid(min(all_pd) - 0.09), grid(dp_y - 0.145), grid(max(all_pd) + 0.09), grid(dp_y + 0.145))
        via1_clean(c, pml["d"][0], dp_y)
        via1_clean(c, pms["d_xs"][0], dp_y)
        via1_clean(c, nm["d"][0], dn_y)
        c.wire("metal2", [(pms["d_xs"][0], dp_y), (x_m2, dp_y), (x_m2, dn_y), (nm["d"][0], dn_y)], 0.320)
        return {"in": (x_in, y_g), "out": (x_m2, dn_y)}

    ba = draw_big_hyb(x_ba_ps, x_ba_pl)
    bb = draw_big_hyb(x_bb_ps, x_bb_pl)
    c1 = draw_oct_inv(c, cache, x_c1, 0.45, 1.40, N_LVT, P_LVT, 0.15, 0.35, 1, 1, y_p, y_n, y_g, y_vdd, y_vss, x_out_off=0.580)
    c2 = draw_oct_inv(c, cache, x_c2, 0.45, 1.40, N_LVT, P_LVT, 0.15, 0.35, 1, 1, y_p, y_n, y_g, y_vdd, y_vss, x_out_off=0.580)

    y_oa = grid(y_p + 0.55)
    y_ob = grid(y_n - 0.35)

    c.wire("metal1", [(c2["out"][0], y_oa), (c2["out"][0], c2["dp"][1])], W_M1)
    c.wire("metal1", [(c1["out"][0], c1["dn"][1]), (c1["out"][0], y_ob)], W_M1)
    c.rect("metal1", grid(c1["dn"][0] - 0.10), grid(y_ob - 0.16), grid(c1["out"][0] + 0.16), grid(c1["dn"][1] + 0.145))
    c.rect("metal1", grid(c2["dp"][0] - 0.10), grid(c2["dp"][1] - 0.145), grid(c2["out"][0] + 0.16), grid(y_oa + 0.16))

    via1_clean(c, c1["in"][0], c1["in"][1])
    via1_clean(c, c2["out"][0], y_oa)
    c.wire("metal2", [(ba["out"][0], y_oa), (c2["out"][0], y_oa)], 0.300)
    c.wire("metal2", [(c1["in"][0], y_oa), (c1["in"][0], c1["in"][1])], W_M2)

    via1_clean(c, c1["out"][0], y_ob)
    via1_clean(c, c2["in"][0], c2["in"][1])
    c.wire("metal2", [(c1["out"][0], y_ob), (bb["out"][0], y_ob)], 0.300)
    c.wire("metal2", [(c2["in"][0], y_ob), (c2["in"][0], c2["in"][1])], W_M2)

    return {
        "in_a": ba["in"],
        "in_b": bb["in"],
        "out_a_m2": (ba["out"][0], y_ob),
        "out_b_m2": (bb["out"][0], y_ob),
    }


def _draw_qdiv2_cc_align_v3(
    c: Cell,
    cache: PdkCache,
    x_ctr: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
    wn: float = 1.00,
    wp: float = 3.20,
    nfn: int = 1,
    nfp: int = 2,
) -> dict:
    """Draw LVT-PMOS cross-coupled differential clock aligner (`pi4_cc_align`) in North row."""
    x_ctr = grid(x_ctr)
    x_c1 = grid(x_ctr - 1.550)
    x_c2 = grid(x_ctr + 1.550)
    c1 = draw_oct_inv(c, cache, x_c1, wn, wp, N_LVT, P_LVT, 0.15, 0.35, nfn, nfp, y_p, y_n, y_g, y_vdd, y_vss, x_out_off=0.920)
    c2 = draw_oct_inv(c, cache, x_c2, wn, wp, N_LVT, P_LVT, 0.15, 0.35, nfn, nfp, y_p, y_n, y_g, y_vdd, y_vss, x_out_off=0.920)
    y_oa = grid(y_p + 0.55)
    y_ob = grid(y_n - 0.35)
    c.wire("metal1", [(c2["out"][0], y_oa), (c2["out"][0], c2["dp"][1])], W_M1)
    c.wire("metal1", [(c1["out"][0], c1["dn"][1]), (c1["out"][0], y_ob)], W_M1)
    via1_clean(c, c1["in"][0], c1["in"][1])
    via1_clean(c, c2["out"][0], y_oa)
    c.wire("metal2", [(c1["in"][0], c1["in"][1]), (c1["in"][0], y_oa), (c2["out"][0], y_oa)], 0.300)
    via1_clean(c, c1["out"][0], y_ob)
    via1_clean(c, c2["in"][0], c2["in"][1])
    c.wire("metal2", [(c1["out"][0], y_ob), (c2["in"][0], y_ob), (c2["in"][0], c2["in"][1])], 0.300)
    return {"a": (c1["in"][0], y_oa), "b": (c2["in"][0], y_ob)}


def _draw_qdiv2_uni_inj_v3(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_in_tap: float = +2.700,
    y_vss: float = +6.750,
) -> dict:
    """Draw 1 unidirectional 2-FET N_LVT pull-down phase injector (`pi4_gated_inj`: 2x N_LVT 3.00/0.15 nf=2)."""
    x0 = grid(x0)
    x_ni = grid(x0 - 0.850)
    x_ne = grid(x0 + 0.850)
    y_n_inj = +5.350  # nf=2 w_f=1.50 -> ndiff [+4.60..+6.10]: >=0.475 um below psubdiff & >=0.95 um above nwell!
    y_g_in  = +3.850  # Xni gate (a)
    y_g_en  = +4.050  # Xne gate (inj_en M2 bus)
    sn_y, dn_y = grid(y_n_inj + 0.350), grid(y_n_inj - 0.350)  # +5.700, +5.000
    y_out_tap = +5.850

    # Xni: s->vss (+5.70->+6.75), g=a (+3.85), d=sn (+5.00)
    ni_m = pi5.place_mos_col(c, cache, x_ni, N_LVT, 3.00, 0.15, 2, y_n_inj, False, y_g_in, sn_y, dn_y)
    # Xne: s=sn (+5.00), g=inj_en (+4.05), d=y (+5.70)
    ne_m = pi5.place_mos_col(c, cache, x_ne, N_LVT, 3.00, 0.15, 2, y_n_inj, False, y_g_en, dn_y, sn_y)

    # Tie Xni.s straight UP to y_vss_n on M1
    for sx in ni_m["s_xs"]:
        c.wire("metal1", [(sx, sn_y), (sx, y_vss)], 0.220)

    # Internal node `sn`: horizontal M1 bar at dn_y (+5.00) connecting Xni.d -> Xne.s (0.41 um clear of +5.70 M1!)
    c.rect("metal1", grid(ni_m["d_xs"][0] - 0.145), grid(dn_y - 0.145),
           grid(ne_m["s_xs"][-1] + 0.145), grid(dn_y + 0.145))

    # Input `a`: West M1 bar at x_in = x_ni - 1.050 from Xni.g (+3.85) to y_in_tap (>=0.28 um clear of Xni.s M1!)
    x_in = grid(x_ni - 1.050)
    c.wire("metal1", [(x_ni, y_g_in), (x_in, y_g_in), (x_in, grid(y_in_tap))], W_M1)

    # Output `y`: East M1 bar at x_out = x_ne + 0.900 from Xne.d (+5.70) across [+1.52..+5.85]
    x_out = grid(x_ne + 0.900)
    c.rect("metal1", grid(ne_m["d_xs"][0] - 0.145), grid(sn_y - 0.145),
           grid(x_out + 0.09), grid(sn_y + 0.145))
    c.wire("metal1", [(x_out, +1.520), (x_out, y_out_tap)], W_M1)

    return {
        "in": (x_in, grid(y_in_tap)),
        "out": (x_out, y_out_tap),
        "inj_en": (x_ne, y_g_en),
    }


def _draw_qdiv2_lock_ctrl_v3(
    c: Cell,
    cache: PdkCache,
    x0: float,
    y_p: float,
    y_n: float,
    y_g: float,
    y_vdd: float,
    y_vss: float,
) -> dict:
    """Draw cold-hardened `pi4_e_lock_ctrl` in North row (XNOR 2.20/0.85 + Xlpf_cap 0.95/0.95 + LVT-P Xdet1 1.40/1.60)."""
    x0 = grid(x0)
    xs_x  = [grid(x0 + k * 1.600) for k in range(4)]  # 0=d2, 1=e0, 2=d0, 3=e2
    x_rst = grid(x0 + 7.200)
    x_cap = grid(x0 + 10.900)
    x_d1  = grid(x0 + 14.000)

    y_gn_en  = +4.050
    y_n_x    = grid(y_n + 0.150)  # +5.350
    y_vlpf_n = +6.050
    y_vlpf_p = +1.500

    pms = []
    nms = []
    for k, xk in enumerate(xs_x):
        if k in (0, 2):
            pm = pi5.place_mos_col(c, cache, xk, P_LVT, 2.20, 0.35, 1, y_p,   True,  y_g, grid(y_p + 0.45),   grid(y_p - 0.45))
            nm = pi5.place_mos_col(c, cache, xk, N_STD, 0.85, 0.35, 1, y_n_x, False, y_g, grid(y_n_x - 0.24), grid(y_n_x + 0.24))
        else:
            pm = pi5.place_mos_col(c, cache, xk, P_LVT, 2.20, 0.35, 1, y_p,   True,  y_g, grid(y_p - 0.45),   grid(y_p + 0.45))
            c.wire("metal1", [(pm["s"][0], pm["s"][1]), (pm["s"][0], y_vdd)], 0.220)
            nm = pi5.place_mos_col(c, cache, xk, N_STD, 0.85, 0.35, 1, y_n_x, False, y_g, grid(y_n_x + 0.24), grid(y_n_x - 0.24))
            c.wire("metal1", [(nm["s"][0], nm["s"][1]), (nm["s"][0], y_vss)], 0.220)
        pms.append(pm)
        nms.append(nm)

    c.wire("metal1", [pms[0]["s"], pms[1]["d"]], W_M1)
    c.wire("metal1", [pms[2]["s"], pms[3]["d"]], W_M1)
    c.wire("metal1", [nms[1]["d"], nms[2]["s"]], W_M1)
    c.wire("metal1", [nms[0]["s"], (nms[0]["s"][0], +4.650), (nms[3]["d"][0], +4.650), nms[3]["d"]], W_M1)

    x_vl0 = grid(xs_x[0] - 0.850)
    via1_clean(c, pms[0]["d"][0], y_vlpf_p)
    via1_clean(c, pms[2]["d"][0], y_vlpf_p)
    c.wire("metal2", [(x_vl0, y_vlpf_p), (pms[2]["d"][0], y_vlpf_p)], 0.380)
    c.wire("metal2", [(x_vl0, y_vlpf_p), (x_vl0, y_vlpf_n)], 0.300)
    for idx_v in (0, 2):
        nx_d = nms[idx_v]["d"][0]
        c.wire("metal1", [nms[idx_v]["d"], (nx_d, y_vlpf_n)], W_M1)
        via1_clean(c, nx_d, y_vlpf_n)

    x_d0_tap = grid(xs_x[0] - 1.450)
    x_e0_tap = grid(xs_x[3] + 0.900)
    c.wire("metal1", [(xs_x[2], y_g), (xs_x[2], +3.300), (x_d0_tap, +3.300)], W_M1)
    c.wire("metal1", [(xs_x[1], y_g), (xs_x[1], +4.250), (x_e0_tap, +4.250)], W_M1)

    rst_m = pi5.place_mos_col(c, cache, x_rst, N_STD, 1.00, 0.18, 1, y_n_x, False, y_g, grid(y_n_x + 0.35), grid(y_n_x - 0.35))
    c.wire("metal1", [(rst_m["s"][0], rst_m["s"][1]), (rst_m["s"][0], y_vss)], 0.220)
    x_rstd = grid(x_rst + 0.720)
    c.wire("metal1", [(rst_m["d"][0], rst_m["d"][1]), (x_rstd, rst_m["d"][1]), (x_rstd, y_vlpf_n)], W_M1)
    via1_clean(c, x_rstd, y_vlpf_n)

    cap_m = pi5.place_mos_col(c, cache, x_cap, N_STD, 0.95, 0.95, 1, y_n_x, False, y_g, grid(y_n_x + 0.30), grid(y_n_x - 0.30))
    for sx in cap_m["s_xs"]:
        c.wire("metal1", [(sx, cap_m["s"][1]), (sx, y_vss)], 0.220)
    for dx in cap_m["d_xs"]:
        c.wire("metal1", [(dx, cap_m["d"][1]), (dx, y_vss)], 0.220)
    x_cap_g = grid(cap_m["s_xs"][0] - 0.650)
    c.wire("metal1", [(x_cap, y_g), (x_cap_g, y_g), (x_cap_g, y_vlpf_n)], W_M1)
    via1_clean(c, x_cap_g, y_vlpf_n)

    det1 = draw_oct_inv(c, cache, x_d1, 2.80, 2.00, N_STD, P_LVT, 0.18, 0.35, 2, 1, y_p, y_n_x, y_g, y_vdd, y_vss, x_out_off=0.820)
    x_d1_in = grid(x_d1 - 0.950)
    c.wire("metal1", [det1["in"], (x_d1_in, y_g), (x_d1_in, y_vlpf_n)], W_M1)
    via1_clean(c, x_d1_in, y_vlpf_n)
    via1_clean(c, det1["out"][0], y_gn_en)

    c.wire("metal2", [(x_vl0, y_vlpf_n), (x_d1_in, y_vlpf_n)], 0.380)

    return {
        "d2": (xs_x[0], y_g),
        "d0": (x_d0_tap, +3.300),
        "e0": (x_e0_tap, +4.250),
        "e2": (xs_x[3], y_g),
        "rst_lat": (x_rst, y_g),
        "inj_en": (det1["out"][0], y_gn_en),
    }


def build_rx_qdiv2_8ph_v3_pdk(cache: PdkCache, add_ports: bool = False) -> tuple[Cell, dict]:
    """Build exact 1:1 cold-MC-hardened v3 `serdes_rx_qdiv2_8ph_4iq` (exact same 136.4 x 17.45 um bbox & 15 pins)."""
    c = Cell()

    y_vdd   = 0.000
    y_p_s   = -2.400
    y_gp_s  = -4.600
    y_gc_s  = -5.100
    y_gn_s  = -5.600
    y_n_s   = -7.050
    y_vss_s = -8.650

    y_p_n   = +1.950
    y_gc_n  = +3.850
    y_n_n   = +5.200
    y_vss_n = +6.750

    x_left  = 0.000
    x_right = 136.400

    c.rect("nwell", grid(x_left - 0.60), -4.450, grid(x_right + 0.60), +3.650)
    draw_tap_h(c, "nsubdiff", x_left, x_right, y_vdd,   half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)
    draw_tap_h(c, "psubdiff", x_left, x_right, y_vss_s, half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)
    draw_tap_h(c, "psubdiff", x_left, x_right, y_vss_n, half_w=0.175, with_m1=True, m1_w=0.560, viali_pitch=1.200)

    pair_x_ctrs = {"d02": 20.400, "d13": 48.600, "e02": 93.600, "e13": 124.200}
    north_m2_xs = []
    for xc in pair_x_ctrs.values():
        north_m2_xs.extend([grid(xc - 3.000 + 0.650), grid(xc + 4.950 + 0.650)])

    # Split y_vss_n M3 over [72.00 .. 114.00] for static DC `inj_en` bridge [74.70 .. 112.35] (0.0% M5!)
    x_vss_n_gap_l = 72.000
    x_vss_n_gap_r = 114.000
    for y_rail, m3_pw in ((y_vdd, 0.400), (y_vss_s, 0.600)):
        c.wire("metal3", [(x_left, y_rail), (x_right, y_rail)], m3_pw)
        xv = grid(x_left + 1.5)
        while xv <= x_right - 1.5 + 1e-6:
            via1_clean(c, xv, y_rail)
            via2_clean(c, xv, y_rail)
            xv = grid(xv + 12.0)

    c.wire("metal3", [(x_left, y_vss_n), (x_vss_n_gap_l, y_vss_n)], 0.400)
    c.wire("metal3", [(x_vss_n_gap_r, y_vss_n), (x_right, y_vss_n)], 0.400)
    vss_n_via_xs: list[float] = []
    xv = grid(x_left + 2.0)
    while xv <= x_right - 1.5 + 1e-6:
        if (xv <= x_vss_n_gap_l - 0.80 or xv >= x_vss_n_gap_r + 0.80) and not any(abs(xv - nx) < 1.20 for nx in north_m2_xs):
            vss_n_via_xs.append(xv)
        xv = grid(xv + 12.0)
    for xv_extra in (70.400, 114.800):
        if not any(abs(xv_extra - nx) < 1.20 for nx in north_m2_xs) and not any(abs(xv_extra - vx) < 1.0 for vx in vss_n_via_xs):
            vss_n_via_xs.append(xv_extra)
    for xv in vss_n_via_xs:
        via1_clean(c, xv, y_vss_n)
        via2_clean(c, xv, y_vss_n)

    for x_strap in (grid(x_left + 0.50), grid(x_right - 0.50)):
        via3_pad(c, x_strap, y_vss_s)
        via3_pad(c, x_strap, y_vss_n)
        c.wire("metal4", [(x_strap, y_vss_s), (x_strap, y_vss_n)], 0.600)

    # 1. Shared 3-stage staged reset chain in West North-row space (full LVT-PMOS for crisp balanced -40..+85 C slew!)
    xrst = draw_oct_inv(
        c, cache, 3.100, 2.00, 6.00, N_LVT, P_LVT, 0.15, 0.35, 2, 3,
        y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, x_out_off=1.250,
    )
    xrst_d1 = draw_oct_inv(
        c, cache, 6.000, 0.65, 1.60, N_STD, P_LVT, 0.35, 0.35, 1, 1,
        y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, x_out_off=0.950,
    )
    xrst_d2 = draw_oct_inv(
        c, cache, 9.400, 2.20, 5.40, N_LVT, P_LVT, 0.15, 0.35, 2, 3,
        y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, x_out_off=1.250,
    )
    c.wire("metal1", [xrst["out"], xrst_d1["in"]], W_M1)
    c.wire("metal1", [xrst_d1["out"], xrst_d2["in"]], W_M1)

    # 2. 4 Full-Strength Hybrid-PMOS Dual-Johnson Columns (33.60 um pitch: col_x0 = [2.6, 36.2, 69.8, 103.4])
    col_x0 = [2.600, 36.200, 69.800, 103.400]
    clk_specs = [
        ("dp", False, False, 2.90, 5.60, 2.25),
        ("dn", True,  False, 2.90, 5.60, 2.25),
        ("ep", False, True,  4.00, 7.00, 3.20),
        ("en", True,  True,  4.00, 7.00, 3.20),
    ]
    gates: dict[str, dict] = {}
    latches: dict[str, dict] = {}
    for (cname, clamp_hi, exp_int, wn_tg, wps_tg, wpl_tg), x0 in zip(clk_specs, col_x0):
        cg = _draw_qdiv2_clkgate_v3(c, cache, x0, y_p_s, y_n_s, y_gp_s, y_gn_s, y_vdd, y_vss_s, clamp_hi=clamp_hi)
        lt = _draw_pi_diff_latch_v3(
            c, cache, grid(x0 + 11.150), y_p_s, y_n_s, y_gp_s, y_gn_s, y_vdd, y_vss_s,
            wn_tg=wn_tg, wps_tg=wps_tg, wpl_tg=wpl_tg, wn_out=3.80, wps_out=10.50, wpl_out=3.50, expose_int=exp_int,
        )
        gates[cname] = cg
        latches[cname] = lt
        via1_clean(c, cg["ck"][0], cg["ck"][1])
        c.wire("metal2", [(cg["ck"][0], cg["ck"][1]), (cg["ck"][0], lt["ck"][1]), lt["ck"]], W_M2)

    # 3. North Row: Hybrid-PMOS Output Pairs + LVT-P Aligners + Hardened Lock Ctrl + Unidirectional N_LVT Injectors
    outpairs: dict[str, dict] = {}
    for pname, xctr in pair_x_ctrs.items():
        outpairs[pname] = _draw_qdiv2_outpair_v3(c, cache, xctr, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    cc_dck = _draw_qdiv2_cc_align_v3(c, cache,  35.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=0.45, wp=2.30, nfn=1, nfp=2)
    cc_eck = _draw_qdiv2_cc_align_v3(c, cache, 102.600, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n, wn=0.45, wp=2.30, nfn=1, nfp=2)

    lctrl = _draw_qdiv2_lock_ctrl_v3(c, cache, 60.100, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    # Local unidirectional 2-FET N_LVT pull-down injectors directly above Xle0 & Xle1 (NO inj_off / Xdet2 needed!)
    # inj_e0n (d2) West at 77.70 (x_in=75.80 clear of e3=80.05); inj_e0p (d0) East at 83.10 (x_in=81.20 clear of e3=80.05!)
    inj_e0n = _draw_qdiv2_uni_inj_v3(c, cache,  77.700, y_in_tap=+3.000, y_vss=y_vss_n)
    inj_e0p = _draw_qdiv2_uni_inj_v3(c, cache,  83.100, y_in_tap=+2.260, y_vss=y_vss_n)
    for inj_c in (inj_e0n, inj_e0p):
        via1_clean(c, inj_c["inj_en"][0], inj_c["inj_en"][1])
    c.wire("metal2", [lctrl["inj_en"], inj_e0p["inj_en"]], 0.260)

    # inj_e1n (d3 at +5.96) taps ABOVE inj_en (+4.05) -> ZERO M2 crossing with inj_en!
    inj_e1p = _draw_qdiv2_uni_inj_v3(c, cache, 111.300, y_in_tap=+2.260, y_vss=y_vss_n)
    inj_e1n = _draw_qdiv2_uni_inj_v3(c, cache, 115.800, y_in_tap=+5.960, y_vss=y_vss_n)

    x_ien_w = grid(lctrl["inj_en"][0])    # 74.700
    x_ien_e = grid(inj_e1p["inj_en"][0])  # 112.350
    c.wire("metal2", [(x_ien_w, +4.050), (x_ien_w, y_vss_n)], 0.300)
    via2_clean(c, x_ien_w, y_vss_n)
    c.wire("metal3", [(x_ien_w, y_vss_n), (x_ien_e, y_vss_n)], 0.300)
    via2_clean(c, x_ien_e, y_vss_n)
    c.wire("metal2", [(x_ien_e, y_vss_n), (x_ien_e, +4.050)], 0.300)
    for inj_c in (inj_e1p, inj_e1n):
        via1_clean(c, inj_c["inj_en"][0], inj_c["inj_en"][1])
    c.wire("metal2", [(x_ien_e, +4.050), inj_e1n["inj_en"]], 0.260)

    # 6 single-column 8-phase load-matching dummies (matching v3 XNOR 2.20/0.85 & lean pi4_e_dum P_STD 1.40/0.15)
    xd_d1  = _draw_qdiv2_dum_col_v2(c, cache,  27.800, P_LVT, 2.20, 0.35, N_STD, 0.85, 0.35, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    xd_d3  = _draw_qdiv2_dum_col_v2(c, cache,  29.800, P_LVT, 2.20, 0.35, N_STD, 0.85, 0.35, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    dum_e1 = _draw_qdiv2_dum_col_v2(c, cache, 107.000, P_STD, 1.40, 0.15, N_LVT, 0.42, 0.15, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    dum_e3 = _draw_qdiv2_dum_col_v2(c, cache, 108.400, P_STD, 1.40, 0.15, N_LVT, 0.42, 0.15, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    xd_e1  = _draw_qdiv2_dum_col_v2(c, cache, 132.400, P_LVT, 2.20, 0.35, N_STD, 0.85, 0.35, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)
    xd_e3  = _draw_qdiv2_dum_col_v2(c, cache, 134.100, P_LVT, 2.20, 0.35, N_STD, 0.85, 0.35, y_p_n, y_n_n, y_gc_n, y_vdd, y_vss_n)

    # 4. South Track definitions: 4 static DC reset rails below 4 quadrature-ordered non-Miller clocks (exact v1/v2 port Ys!)
    y_trk_rstn_lat = -6.800
    y_trk_rstn     = -5.950  # Exact drop-in West port Y (-5.950 -> 57.250 in top-level!)
    y_trk_rst_lat  = -5.100
    y_trk_rst      = -4.250
    y_trk_dp       = -3.400  # 0 deg   (exact v1/v2 East port Y!)
    y_trk_ep       = -2.550  # 90 deg  (quadrature to dp -> 0 Miller!)
    y_trk_dn       = -1.700  # 180 deg (quadrature to ep -> 0 Miller!)
    y_trk_en       = -0.850  # 270 deg (quadrature to dn -> 0 Miller!)

    y_trk_d1   = +0.780
    y_trk_ckp  = +1.520
    y_trk_d0   = +2.260
    y_trk_d2   = +3.000
    y_trk_ckn  = +3.740
    y_trk_e2   = +4.480
    y_trk_e0   = +5.220
    y_trk_d3   = +5.960

    y_trk_ck02  = +7.600
    y_trk_ck13  = +8.450
    y_north_pin = +8.800

    clk_names = ["dp", "dn", "ep", "en"]

    # Drop North-row reset chain (`rst_n`, `rst`, `rst_n_lat`, `rst_lat`) cleanly on M4 at x = 2.15, 3.85, 6.95, 10.65
    x_rstn_m4    = 2.150
    x_rst_m4     = 3.850
    x_rstnlat_m4 = 6.950
    x_rstlat_m4  = 10.650

    def _drop_rst_m4(pin_xy: tuple[float, float], xm4: float, y_top: float, y_bot: float) -> None:
        px, py = pin_xy
        via1_clean(c, px, py)
        c.wire("metal2", [(px, py), (xm4, py), (xm4, y_top)], 0.340)
        via2_clean(c, xm4, y_top)
        via3_pad(c, xm4, y_top)
        c.wire("metal4", [(xm4, y_bot), (xm4, y_top)], 0.400)
        via3_pad(c, xm4, y_bot)

    _drop_rst_m4(xrst["in"],     x_rstn_m4,    y_trk_ckn, y_trk_rstn)
    _drop_rst_m4(xrst["out"],    x_rst_m4,     y_trk_ckn, y_trk_rst)
    _drop_rst_m4(xrst_d1["out"], x_rstnlat_m4, y_trk_ckn, y_trk_rstn_lat)
    _drop_rst_m4(xrst_d2["out"], x_rstlat_m4,  y_trk_ckn, y_trk_rst_lat)

    # `rst_n`: West port (0.00, -5.950) straight East to all 4 ClkGates
    x_rstn_hi = grid(max(
        max(gates[cn]["rst_n"][0] for cn in clk_names),
        max(gates[cn]["clmp_rst_pt"][0] for cn in clk_names if gates[cn]["clmp_rst_net"] == "rst_n"),
    ) + 0.500)
    c.wire("metal3", [(x_left, y_trk_rstn), (x_rstn_hi, y_trk_rstn)], 0.340)
    for cn in clk_names:
        gx, gy = gates[cn]["rst_n"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, y_trk_rstn)], W_M2)
        via2_clean(c, gx, y_trk_rstn)
        if gates[cn]["clmp_rst_net"] == "rst_n":
            cx, cy = gates[cn]["clmp_rst_pt"]
            via1_clean(c, cx, cy)
            c.wire("metal2", [(cx, cy), (cx, y_trk_rstn)], W_M2)
            via2_clean(c, cx, y_trk_rstn)

    # `rst`: x_rst_m4 -> all 4 ClkGates
    x_rst_hi = grid(max(
        max(gates[cn]["rst"][0] for cn in clk_names),
        max(gates[cn]["clmp_rst_pt"][0] for cn in clk_names if gates[cn]["clmp_rst_net"] == "rst"),
    ) + 0.500)
    c.wire("metal3", [(min(x_rst_m4, gates["dp"]["rst"][0]), y_trk_rst), (x_rst_hi, y_trk_rst)], 0.340)
    for cn in clk_names:
        gx, gy = gates[cn]["rst"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, y_trk_rst)], W_M2)
        via2_clean(c, gx, y_trk_rst)
        if gates[cn]["clmp_rst_net"] == "rst":
            cx, cy = gates[cn]["clmp_rst_pt"]
            via1_clean(c, cx, cy)
            c.wire("metal2", [(cx, cy), (cx, y_trk_rst)], W_M2)
            via2_clean(c, cx, y_trk_rst)

    # `rst_n_lat`: x_rstnlat_m4 -> ALL 4 latches
    x_rstn_lat_hi = grid(latches["en"]["rst_n_lat"][0] + 0.500)
    c.wire("metal3", [(x_rstnlat_m4, y_trk_rstn_lat), (x_rstn_lat_hi, y_trk_rstn_lat)], 0.340)
    for cn in clk_names:
        lx, ly = latches[cn]["rst_n_lat"]
        via1_clean(c, lx, ly)
        via2_clean(c, lx, ly)

    # `rst_lat`: x_rstlat_m4 -> ALL 4 latches + vertical M4 drop to lctrl.rst_lat!
    x_rst_lat_hi = grid(latches["en"]["rst_lat"][0] + 0.500)
    c.wire("metal3", [(x_rstlat_m4, y_trk_rst_lat), (x_rst_lat_hi, y_trk_rst_lat)], 0.340)
    for cn in clk_names:
        rx, ry = latches[cn]["rst_lat"]
        via1_clean(c, rx, ry)
        via2_clean(c, rx, y_trk_rst_lat)

    x_lrst = grid(lctrl["rst_lat"][0])
    y_lrst_top = y_trk_ckn
    via1_clean(c, x_lrst, lctrl["rst_lat"][1])
    c.wire("metal2", [lctrl["rst_lat"], (x_lrst, y_lrst_top)], 0.400)
    via2_clean(c, x_lrst, y_lrst_top)
    via3_pad(c, x_lrst, y_lrst_top)
    c.wire("metal4", [(x_lrst, y_trk_rst_lat), (x_lrst, y_lrst_top)], 0.400)
    via3_pad(c, x_lrst, y_trk_rst_lat)

    # `dp, dn, ep, en` EQUAL-SPAN low-C horizontal M3 trunks [1.10 .. x_right]
    for cn, yt in (("dp", y_trk_dp), ("dn", y_trk_dn), ("ep", y_trk_ep), ("en", y_trk_en)):
        c.wire("metal3", [(1.100, yt), (x_right, yt)], 0.300)
        gx, gy = gates[cn]["ck_in"]
        via1_clean(c, gx, gy)
        c.wire("metal2", [(gx, gy), (gx, yt)], W_M2)
        via2_clean(c, gx, yt)

    north_specs = [
        ("ckd0", outpairs["d02"]["out_a_m2"],  11.000, y_trk_ck02),
        ("ckd2", outpairs["d02"]["out_b_m2"],  43.000, y_trk_ck02),
        ("ckd1", outpairs["d13"]["out_a_m2"],  27.000, y_trk_ck13),
        ("ckd3", outpairs["d13"]["out_b_m2"],  59.000, y_trk_ck13),
        ("cke0", outpairs["e02"]["out_a_m2"],  75.000, y_trk_ck02),
        ("cke2", outpairs["e02"]["out_b_m2"], 107.000, y_trk_ck02),
        ("cke1", outpairs["e13"]["out_a_m2"],  91.000, y_trk_ck13),
        ("cke3", outpairs["e13"]["out_b_m2"], 123.000, y_trk_ck13),
    ]
    m4_used: list[tuple[float, float, float, str]] = [
        (grid(x_left + 0.50), y_vss_s, y_vss_n, "vss"),
        (grid(x_right - 0.50), y_vss_s, y_vss_n, "vss"),
        (x_rstn_m4, y_trk_rstn, y_trk_ckn, "rst_n"),
        (x_rst_m4, y_trk_rst, y_trk_ckn, "rst"),
        (x_rstnlat_m4, y_trk_rstn_lat, y_trk_ckn, "rst_n_lat"),
        (x_rstlat_m4, y_trk_rst_lat, y_trk_ckn, "rst_lat"),
        (x_lrst, y_trk_rst_lat, y_lrst_top, "rst_lat"),
    ]
    m3_pads: list[tuple[float, float, str]] = [
        (x_rstn_m4, y_trk_ckn, "rst_n"),
        (x_rst_m4, y_trk_ckn, "rst"),
        (x_rstnlat_m4, y_trk_ckn, "rst_n_lat"),
        (x_rstlat_m4, y_trk_ckn, "rst_lat"),
        (x_lrst, y_lrst_top, "rst_lat"),
        (x_ien_w, y_vss_n, "inj_en"),
        (x_ien_e, y_vss_n, "inj_en"),
    ]
    m3_tracks_occ: dict[float, list[tuple[float, float, str]]] = {
        y_vdd: [(x_left, x_right, "vdd")],
        y_vss_s: [(x_left, x_right, "vss")],
        y_vss_n: [
            (x_left, x_vss_n_gap_l, "vss"),
            (x_ien_w, x_ien_e, "inj_en"),
            (x_vss_n_gap_r, x_right, "vss"),
        ],
        y_trk_rstn_lat: [(x_rstnlat_m4, x_rstn_lat_hi, "rst_n_lat")],
        y_trk_rstn: [(x_left, x_rstn_hi, "rst_n")],
        y_trk_rst_lat: [(x_rstlat_m4, x_rst_lat_hi, "rst_lat")],
        y_trk_rst: [(min(x_rst_m4, gates["dp"]["rst"][0]), x_rst_hi, "rst")],
        y_trk_dp: [(1.100, x_right, "dp")],
        y_trk_ep: [(1.100, x_right, "ep")],
        y_trk_dn: [(1.100, x_right, "dn")],
        y_trk_en: [(1.100, x_right, "en")],
    }
    xv_p = grid(x_left + 1.5)
    while xv_p <= x_right - 1.5 + 1e-6:
        m3_pads.append((xv_p, y_vdd, "vdd"))
        xv_p = grid(xv_p + 12.0)
    for xv in vss_n_via_xs:
        m3_pads.append((xv, y_vss_n, "vss"))

    for nm, (ox, _oy), x_pin, y_sort in north_specs:
        m3_tracks_occ.setdefault(y_sort, []).append((min(ox, x_pin), max(ox, x_pin), nm))
        m4_used.append((x_pin, y_sort, y_north_pin, nm))

    def m4_free(x: float, y1: float, y2: float, net: str) -> bool:
        ya, yb = min(y1, y2) - 0.88, max(y1, y2) + 0.88
        for ux, uy1, uy2, unet in m4_used:
            if unet != net and abs(ux - x) < 0.96 and not (yb < uy1 or ya > uy2):
                return False
        return True

    def m3_pt_ok(x_c: float, y_c: float, net: str) -> bool:
        for ty, occs in m3_tracks_occ.items():
            if abs(ty - y_c) < 0.72:
                for ox1, ox2, onet in occs:
                    if onet != net and (ox1 - 0.80) <= x_c <= (ox2 + 0.80):
                        return False
        for mx, my, mnet in m3_pads:
            if mnet != net and abs(mx - x_c) < 0.86 and abs(my - y_c) < 0.86:
                return False
            # Also prevent same-net via2 pad notches (< 0.30 um met3.2 between two 0.52 um pads!)
            if mnet == net and 0.10 < abs(mx - x_c) < 0.84 and abs(my - y_c) < 0.84:
                return False
        return True

    def route_bus_m3_m4(net: str, y_trk: float, pins: list[tuple[float, float, str]]) -> None:
        y_trk = grid(y_trk)
        xs_trk: list[float] = []
        for px, py, lyr in pins:
            px, py = grid(px), grid(py)
            chosen = None
            if py > 0.0:
                if m3_pt_ok(px, y_trk, net):
                    chosen = (px, y_trk)
                else:
                    for dx_n in (-0.48, 0.48, -0.96, 0.96, -1.44, 1.44, -1.92, 1.92):
                        xc = grid(px + dx_n)
                        if m3_pt_ok(xc, y_trk, net):
                            chosen = (xc, y_trk)
                            break
            if chosen is None and m3_pt_ok(px, py, net) and m3_pt_ok(px, y_trk, net) and m4_free(px, py, y_trk, net):
                chosen = (px, py)
            if chosen is None:
                for dx_n in (0.24, -0.24, 0.48, -0.48, 0.72, -0.72, 0.96, -0.96, 1.20, -1.20, 1.44, -1.44, 1.92, -1.92, 2.40, -2.40):
                    xc = grid(px + dx_n)
                    if m3_pt_ok(xc, py, net) and m3_pt_ok(xc, y_trk, net) and m4_free(xc, py, y_trk, net):
                        chosen = (xc, py)
                        break
            if chosen is None:
                raise RuntimeError(f"No clean M3/M4 escape for net {net} pin {(px, py)} -> y_trk={y_trk}")
            xc, yc = chosen
            if lyr == "metal1":
                via1_clean(c, px, py)
            if abs(xc - px) > 0.01 or abs(yc - py) > 0.01:
                w_seg = 0.400 if (abs(xc - px) < 0.65 and abs(yc - py) < 0.65) else W_M2
                c.wire("metal2", [(px, py), (xc, py), (xc, yc)], w_seg)
            via2_clean(c, xc, yc)
            m3_pads.append((xc, yc, net))
            if abs(yc - y_trk) > 0.01:
                via3_pad(c, xc, yc)
                c.wire("metal4", [(xc, yc), (xc, y_trk)], 0.400)
                via3_pad(c, xc, y_trk)
                m4_used.append((xc, min(yc, y_trk), max(yc, y_trk), net))
                m3_pads.append((xc, y_trk, net))
            xs_trk.append(xc)
        x_lo, x_hi = min(xs_trk), max(xs_trk)
        if x_hi - x_lo > 0.01:
            c.wire("metal3", [(x_lo, y_trk), (x_hi, y_trk)], 0.300)
        m3_tracks_occ.setdefault(y_trk, []).append((x_lo, x_hi, net))

    # Matched Dual-Johnson D-channel buses (unidirectional N_LVT pull-down: d2->e0_intn, d0->e0_intp, d3->e1_intn, d1->e1_intp!)
    route_bus_m3_m4("d0", y_trk_d0, [
        (latches["dp"]["qp"][0], latches["dp"]["qp"][1], "metal1"),
        (latches["dn"]["dp_in"][0], latches["dn"]["dp_in"][1], "metal1"),
        (outpairs["d02"]["in_b"][0], outpairs["d02"]["in_b"][1], "metal1"),
        (inj_e0p["in"][0], inj_e0p["in"][1], "metal1"),
        (lctrl["d0"][0], lctrl["d0"][1], "metal1"),
    ])
    route_bus_m3_m4("d2", y_trk_d2, [
        (latches["dp"]["qn"][0], latches["dp"]["qn"][1], "metal1"),
        (latches["dn"]["dn_in"][0], latches["dn"]["dn_in"][1], "metal1"),
        (outpairs["d02"]["in_a"][0], outpairs["d02"]["in_a"][1], "metal1"),
        (inj_e0n["in"][0], inj_e0n["in"][1], "metal1"),
        (lctrl["d2"][0], lctrl["d2"][1], "metal1"),
    ])
    route_bus_m3_m4("d1", y_trk_d1, [
        (latches["dn"]["qp"][0], latches["dn"]["qp"][1], "metal1"),
        (latches["dp"]["dn_in"][0], latches["dp"]["dn_in"][1], "metal1"),
        (outpairs["d13"]["in_b"][0], outpairs["d13"]["in_b"][1], "metal1"),
        (inj_e1p["in"][0], inj_e1p["in"][1], "metal1"),
        (xd_d1[0], xd_d1[1], "metal1"),
    ])
    route_bus_m3_m4("e0", y_trk_e0, [
        (latches["ep"]["qp"][0], latches["ep"]["qp"][1], "metal1"),
        (latches["en"]["dp_in"][0], latches["en"]["dp_in"][1], "metal1"),
        (outpairs["e02"]["in_a"][0], outpairs["e02"]["in_a"][1], "metal1"),
        (lctrl["e0"][0], lctrl["e0"][1], "metal1"),
    ])
    route_bus_m3_m4("d3", y_trk_d3, [
        (latches["dn"]["qn"][0], latches["dn"]["qn"][1], "metal1"),
        (latches["dp"]["dp_in"][0], latches["dp"]["dp_in"][1], "metal1"),
        (outpairs["d13"]["in_a"][0], outpairs["d13"]["in_a"][1], "metal1"),
        (inj_e1n["in"][0], inj_e1n["in"][1], "metal1"),
        (xd_d3[0], xd_d3[1], "metal1"),
    ])
    route_bus_m3_m4("e2", y_trk_e2, [
        (latches["ep"]["qn"][0], latches["ep"]["qn"][1], "metal1"),
        (latches["en"]["dn_in"][0], latches["en"]["dn_in"][1], "metal1"),
        (outpairs["e02"]["in_b"][0], outpairs["e02"]["in_b"][1], "metal1"),
        (lctrl["e2"][0], lctrl["e2"][1], "metal1"),
    ])
    route_bus_m3_m4("e1", y_trk_d0, [
        (latches["en"]["qp"][0], latches["en"]["qp"][1], "metal1"),
        (latches["ep"]["dn_in"][0], latches["ep"]["dn_in"][1], "metal1"),
        (outpairs["e13"]["in_a"][0], outpairs["e13"]["in_a"][1], "metal1"),
        (dum_e1[0], dum_e1[1], "metal1"),
        (xd_e1[0], xd_e1[1], "metal1"),
    ])
    route_bus_m3_m4("e3", y_trk_d2, [
        (latches["en"]["qn"][0], latches["en"]["qn"][1], "metal1"),
        (latches["ep"]["dp_in"][0], latches["ep"]["dp_in"][1], "metal1"),
        (outpairs["e13"]["in_b"][0], outpairs["e13"]["in_b"][1], "metal1"),
        (dum_e3[0], dum_e3[1], "metal1"),
        (xd_e3[0], xd_e3[1], "metal1"),
    ])

    route_bus_m3_m4("dp_ck", y_trk_ckp, [
        (gates["dp"]["ck_esc"][0], gates["dp"]["ck_esc"][1], "metal1"),
        (latches["dn"]["ckb_esc"][0], latches["dn"]["ckb_esc"][1], "metal1"),
        (cc_dck["a"][0], cc_dck["a"][1], "metal2"),
    ])
    route_bus_m3_m4("dn_ck", y_trk_ckn, [
        (gates["dn"]["ck_esc"][0], gates["dn"]["ck_esc"][1], "metal1"),
        (latches["dp"]["ckb_esc"][0], latches["dp"]["ckb_esc"][1], "metal1"),
        (cc_dck["b"][0], cc_dck["b"][1], "metal2"),
    ])
    route_bus_m3_m4("ep_ck", y_trk_ckp, [
        (gates["ep"]["ck_esc"][0], gates["ep"]["ck_esc"][1], "metal1"),
        (latches["en"]["ckb_esc"][0], latches["en"]["ckb_esc"][1], "metal1"),
        (cc_eck["a"][0], cc_eck["a"][1], "metal2"),
    ])
    route_bus_m3_m4("en_ck", y_trk_ckn, [
        (gates["en"]["ck_esc"][0], gates["en"]["ck_esc"][1], "metal1"),
        (latches["ep"]["ckb_esc"][0], latches["ep"]["ckb_esc"][1], "metal1"),
        (cc_eck["b"][0], cc_eck["b"][1], "metal2"),
    ])

    # 4 Local Short-Hop Unidirectional N_LVT Phase-Injection outputs (e0_intn, e0_intp, e1_intp, e1_intn)
    route_bus_m3_m4("e0_intn", y_trk_ck13, [
        (inj_e0n["out"][0], inj_e0n["out"][1], "metal1"),
        (latches["ep"]["intn_esc"][0], latches["ep"]["intn_esc"][1], "metal1"),
    ])
    route_bus_m3_m4("e0_intp", y_trk_d0, [
        (inj_e0p["out"][0], y_trk_d0, "metal1"),
        (latches["ep"]["intp_esc"][0], latches["ep"]["intp_esc"][1], "metal1"),
    ])
    route_bus_m3_m4("e1_intp", y_trk_ck02, [
        (inj_e1p["out"][0], inj_e1p["out"][1], "metal1"),
        (latches["en"]["intp_esc"][0], latches["en"]["intp_esc"][1], "metal1"),
    ])
    route_bus_m3_m4("e1_intn", y_trk_ckp, [
        (inj_e1n["out"][0], y_trk_ckp, "metal1"),
        (latches["en"]["intn_esc"][0], latches["en"]["intn_esc"][1], "metal1"),
    ])

    north_pins: dict[str, tuple[float, float]] = {}
    for nm, (ox, oy), x_pin, y_sort in north_specs:
        c.wire("metal2", [(ox, oy), (ox, y_sort)], 0.360)
        via2_clean(c, ox, y_sort)
        c.wire("metal3", [(min(ox, x_pin), y_sort), (max(ox, x_pin), y_sort)], 0.360)
        via3_pad(c, x_pin, y_sort)
        c.wire("metal4", [(x_pin, y_sort), (x_pin, y_north_pin)], 0.440)
        north_pins[nm] = (x_pin, y_north_pin)

    meta = {
        "dp": (x_right, y_trk_dp),
        "dn": (x_right, y_trk_dn),
        "ep": (x_right, y_trk_ep),
        "en": (x_right, y_trk_en),
        "rst_n": (x_left, y_trk_rstn),
        "vdd": (x_left, y_vdd),
        "vss": (x_left, y_vss_s),
        "vdd_e": (x_right, y_vdd),
        "vss_e": (x_right, y_vss_s),
        **north_pins,
    }
    return c, meta


# ---------------------------------------------------------------------------
# 4. serdes_rx_pi_4ph_5g_pdk — Full Integrated 5G 4-Phase I/Q CMOS PI + /2
# ---------------------------------------------------------------------------

def build_rx_pi_4ph_5g_pdk(
    cache: PdkCache,
    add_ports: bool = True,
    variant: str = "v5g_4ph_v3_pdk",
) -> tuple[Cell, dict]:
    """Build full integrated `serdes_rx_pi_4ph_5g_pdk` (43 ports matching `serdes_rx_pi_4ph_iq_8ph`, 0.0% M5)."""
    is_v2 = variant in ("v5g_4ph_v2_pdk", "v5g_4ph_v3_pdk")
    is_v3 = (variant == "v5g_4ph_v3_pdk")
    c = Cell()

    # 1. Place Octature 4->8 stage on West at (dx=0.0, dy=4.100)
    #    -> y_vss_top_bus = 4.10 + 48.20 = 52.300 == y_top_vss_bus; y_vdd_top = 4.10 + 49.20 = 53.300 == y_top_vdd_bus!
    oct_cell, oct_m = build_rx_octature_4to8_2p5g_pdk(cache, add_ports=False, variant=variant)
    dy_oct = 4.100
    c.include(oct_cell, dx=0.0, dy=dy_oct)

    # 2. Place TWO identical `pi4_diff_chan` cells shifted East by dx_ch = +46.400
    ch_cell, ch_m = _build_pi4_diff_chan_v2_cell(cache) if is_v2 else _build_pi4_diff_chan_cell(cache)
    dx_ch = 46.400
    y_vss_ch = ch_m["y_vss_ch"]  # 10.500
    y_ch_e = 18.200
    y_ch_d = 40.800
    c.include(ch_cell, dx=dx_ch, dy=y_ch_e)
    c.include(ch_cell, dx=dx_ch, dy=y_ch_d)

    # 3. Low-C 8-wire M4 octature clock spine (`cb0..cb7`)
    if is_v2:
        spine_xs = [grid(49.000 + k * 0.940) for k in range(8)]  # 49.00 .. 55.58 (0.64 um air gap!)
    else:
        spine_xs = [grid(49.200 + k * 1.240) for k in range(8)]  # 49.20 .. 57.88
    y_spine_lo = 7.000
    y_spine_hi = 50.600 if is_v2 else 50.300
    for k in range(8):
        c.wire("metal4", [(spine_xs[k], y_spine_lo), (spine_xs[k], y_spine_hi)], 0.300)

    # Stitch octature `cb0..cb7` outputs (at x = 47.600) into M4 spine at conflict-free Ys
    # (strictly >= 1.65 um clear of ALL 16 Xch_e/Xch_d tap Ys!)
    cb_spine_ys = {
        0: 12.900,  # oct at 12.90 (straight!)
        1: 24.700,  # oct at 24.70 (straight!)
        2: 36.500,  # oct at 36.50 (straight!)
        3: 47.300,  # oct at 48.30 (jog -1.00, >= 0.48 um via2 M3 spacing!)
        4:  7.100,  # oct at  7.10 (straight!)
        5: 21.600,  # oct at 18.90 (jog +2.70)
        6: 29.400,  # oct at 30.70 (jog -1.30)
        7: 45.000,  # oct at 42.50 (jog +2.50)
    }
    x_jog = 48.100
    for k in range(8):
        ox, oy_rel = oct_m[f"cb{k}"]
        oy = grid(dy_oct + oy_rel)
        ys = cb_spine_ys[k]
        if abs(ys - oy) > 0.01:
            c.wire("metal3", [(ox, oy), (x_jog, oy)], 0.300)
            via2_clean(c, x_jog, oy)
            c.wire("metal2", [(x_jog, oy), (x_jog, ys)], 0.300)
            via2_clean(c, x_jog, ys)
            c.wire("metal3", [(x_jog, ys), (spine_xs[k], ys)], 0.300)
        else:
            c.wire("metal3", [(ox, ys), (spine_xs[k], ys)], 0.300)
        via3_pad(c, spine_xs[k], ys)

    # Tap clock spine (`cb0..cb7`) into `Xch_d` and `Xch_e` on lean 0.30 um M3
    clk_in_x = grid(dx_ch + ch_m["clk_in_x"])  # 60.400
    for y_ch, e_cbs, o_cbs in (
        (y_ch_d, [0, 2, 4, 6], [1, 3, 5, 7]),
        (y_ch_e, [2, 4, 6, 0], [3, 5, 7, 1]),
    ):
        for idx, cb_k in enumerate(e_cbs):
            yt = grid(y_ch + ch_m["e_ys"][idx])
            xs_tap = spine_xs[cb_k]
            via3_pad(c, xs_tap, yt)
            c.wire("metal3", [(xs_tap, yt), (clk_in_x, yt)], 0.300)
        for idx, cb_k in enumerate(o_cbs):
            yt = grid(y_ch + ch_m["o_ys"][idx])
            xs_tap = spine_xs[cb_k]
            via3_pad(c, xs_tap, yt)
            c.wire("metal3", [(xs_tap, yt), (clk_in_x, yt)], 0.300)

    # 4. South Band (y in [0.00, 5.40]): 24x `pi4_inv_static` (a0..7, b0..7, f0..7) shifted by dx_ch
    y_st_vss = 0.400
    y_st_n   = 1.250
    y_st_gc  = 2.150
    y_st_p   = 3.150
    y_st_vdd = 4.250

    a_xs = [grid(dx_ch + 14.600 + k * 1.650) for k in range(8)]
    b_xs = [grid(dx_ch + 28.600 + k * 1.650) for k in range(8)]
    f_xs = [grid(dx_ch + x) for x in (46.000, 50.800, 57.150, 61.950, 68.300, 73.100, 79.450, 84.250)]

    x_st_l = grid(dx_ch + (10.000 if is_v2 else 13.000))
    x_st_r = grid(dx_ch + 86.800)
    c.rect("nwell", grid(dx_ch + 12.500), +2.350, grid(x_st_r + 0.50), +4.850)
    draw_tap_h(c, "psubdiff", x_st_l, x_st_r, y_st_vss, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)
    draw_tap_h(c, "nsubdiff", grid(dx_ch + 13.000), x_st_r, y_st_vdd, half_w=0.175, with_m1=True, m1_w=0.460, viali_pitch=1.20)

    stat_invs: dict[str, dict] = {}
    south_pins: dict[str, tuple[float, float]] = {}
    y_south_pin = -0.350
    for grp, gxs in (("a", a_xs), ("b", b_xs), ("f", f_xs)):
        for k, gx in enumerate(gxs):
            nm = f"{grp}{k}"
            inv = pi5.draw_cmos_inv(
                c, cache, gx, 0.45, 0.90, N_STD, P_STD, 0.18, 0.18, 1, 1,
                y_st_p, y_st_n, y_st_gc, y_st_vdd, y_st_vss,
            )
            stat_invs[nm] = inv
            via1_clean(c, inv["in"][0], inv["in"][1])
            c.wire("metal2", [(inv["in"][0], y_south_pin), (inv["in"][0], inv["in"][1])], 0.300)
            south_pins[nm] = (inv["in"][0], y_south_pin)

    # 5. Connect vertical M4 control lines between South bank, Xch_e, and Xch_d
    jog_ys_8 = [0.600, 1.500, 2.400, 3.300, 4.200, 5.100, 6.000, 6.900]

    def stitch_ctrl_m4(pin_m1: tuple[float, float], is_m2: bool, x_m4: float, y_jog: float, y_m4_top: float) -> None:
        px, py = pin_m1
        if not is_m2:
            via1_clean(c, px, py)
        if abs(y_jog - py) > 0.01:
            c.wire("metal2", [(px, py), (px, y_jog)], 0.300)
        via2_clean(c, px, y_jog)
        if abs(x_m4 - px) > 0.01:
            c.wire("metal3", [(min(px, x_m4), y_jog), (max(px, x_m4), y_jog)], 0.520)
        via3_pad(c, x_m4, y_jog)
        c.wire("metal4", [(x_m4, y_jog), (x_m4, y_m4_top)], 0.360)

    for idx, k in enumerate((0, 2, 4, 6)):
        xm_s, xm_sb = grid(dx_ch + ch_m["sel_a_m4"][idx][0]), grid(dx_ch + ch_m["sel_a_m4"][idx][1])
        inv = stat_invs[f"a{k}"]
        stitch_ctrl_m4(inv["in"],  True,  xm_s,  jog_ys_8[2 * idx],     grid(y_ch_d + 3.300))
        stitch_ctrl_m4(inv["out"], False, xm_sb, jog_ys_8[2 * idx + 1], grid(y_ch_d + 5.600))

    for idx, k in enumerate((1, 3, 5, 7)):
        xm_s, xm_sb = grid(dx_ch + ch_m["sel_b_m4"][idx][0]), grid(dx_ch + ch_m["sel_b_m4"][idx][1])
        inv = stat_invs[f"b{k}"]
        stitch_ctrl_m4(inv["in"],  True,  xm_s,  jog_ys_8[2 * idx],     grid(y_ch_d + 3.300))
        stitch_ctrl_m4(inv["out"], False, xm_sb, jog_ys_8[2 * idx + 1], grid(y_ch_d + 5.600))

    for col_i in range(4):
        for sub_i in range(2):
            k = 2 * col_i + sub_i
            inv = stat_invs[f"f{k}"]
            y_top_k = grid(y_ch_d + (0.550 if sub_i == 0 else 9.950))
            stitch_ctrl_m4(inv["in"],  True,  grid(dx_ch + ch_m["f_m4_xs"][k]),  jog_ys_8[2 * sub_i],     y_top_k)
            stitch_ctrl_m4(inv["out"], False, grid(dx_ch + ch_m["fb_m4_xs"][k]), jog_ys_8[2 * sub_i + 1], y_top_k)

    # 6. Place QDiv2 aligned with East side of rotator!
    #    v3 uses Cold-MC-Hardened Hybrid-PMOS QDiv2 (`build_rx_qdiv2_8ph_v3_pdk`, 1:1 drop-in!)
    #    v2 uses matched Dual-Johnson + Hybrid-PMOS ClkGate (`build_rx_qdiv2_8ph_v2_pdk`)
    if is_v3:
        div_cell, div_m = build_rx_qdiv2_8ph_v3_pdk(cache, add_ports=False)
    elif is_v2:
        div_cell, div_m = build_rx_qdiv2_8ph_v2_pdk(cache, add_ports=False)
    else:
        div_cell, div_m = build_rx_qdiv2_8ph_4iq_pdk(cache, add_ports=False)
    dx_div = 29.000   # qdiv2 spans x = [29.00 .. 165.40], matching rotator East = 165.40!
    dy_div = 63.200
    c.include(div_cell, dx=dx_div, dy=dy_div)

    y_top_vss_bus = 52.300
    y_top_vdd_bus = 53.300
    y_div_vss = grid(dy_div + div_m["vss"][1])  # 54.550
    y_div_vdd = grid(dy_div + div_m["vdd"][1])  # 63.200

    # 7. Unified Power Grid (Octature + Rotator + QDiv2, 0.0% M5!)
    x_vss_cw   = grid(dx_ch + ch_m.get("vss_w_x", 13.300))
    x_vss_tie  = grid(dx_ch + ch_m.get("vss_w_tie_x", 14.500))
    x_vdd_w_ch = grid(dx_ch + ch_m["vdd_m4_w"])
    x_vdd_e    = grid(dx_ch + ch_m["vdd_m4_e"])
    x_vss_e    = grid(dx_ch + ch_m["vss_e_x"])

    for yv in (grid(y_ch_e - y_vss_ch), grid(y_ch_e + y_vss_ch), grid(y_ch_d - y_vss_ch), grid(y_ch_d + y_vss_ch)):
        c.wire("metal1", [(x_vss_cw, yv), (x_vss_tie, yv)], 0.460)
        c.wire("metal1", [(grid(dx_ch + 118.000), yv), (x_vss_e, yv)], 0.460)
        for xv in (x_vss_cw, x_vss_e):
            via1_clean(c, xv, yv)
            via2_clean(c, xv, yv)
            via3_pad(c, xv, yv)

    # South bank vss -> x_vss_cw vertical M4 spine -> y_top_vss_bus
    via1_clean(c, x_vss_cw, y_st_vss)
    via2_clean(c, x_vss_cw, y_st_vss)
    via3_pad(c, x_vss_cw, y_st_vss)
    for xv, y0_s in ((x_vss_cw, y_st_vss), (x_vss_e, grid(y_ch_e - y_vss_ch))):
        via3_pad(c, xv, y_top_vss_bus)
        c.wire("metal4", [(xv, y0_s), (xv, y_top_vss_bus)], 0.600)

    # Continuous full-width horizontal VSS M3 rail at y = 52.300 (joins octature vss_top + x_vss_cw + x_vss_e)
    c.wire("metal3", [(0.000, y_top_vss_bus), (x_vss_e, y_top_vss_bus)], 0.560)
    # Stitch y_top_vss_bus UP into qdiv2 vss at West (dx_div + 0.50 = 29.50) and East (dx_div + 135.90 = 164.90)
    x_div_vss_w = grid(dx_div + 0.500)
    x_div_vss_e = grid(dx_div + div_m["vss_e"][0] - 0.500)
    for xv in (x_div_vss_w, x_div_vss_e):
        via3_pad(c, xv, y_top_vss_bus)
        c.wire("metal4", [(xv, y_top_vss_bus), (xv, y_div_vss)], 0.600)

    # Continuous full-width horizontal VDD M3 rail at y = 53.300 (joins octature vdd_top + x_vdd_w_ch + x_vdd_e)
    c.wire("metal3", [(0.000, y_top_vdd_bus), (x_vdd_e, y_top_vdd_bus)], 0.600)
    via1_clean(c, x_vdd_w_ch, y_st_vdd)
    via2_clean(c, x_vdd_w_ch, y_st_vdd)
    via3_pad(c, x_vdd_w_ch, y_st_vdd)
    via3_pad(c, x_vdd_w_ch, y_top_vdd_bus)
    c.wire("metal4", [(x_vdd_w_ch, y_st_vdd), (x_vdd_w_ch, y_top_vdd_bus)], 0.560)
    via3_pad(c, x_vdd_e, y_top_vdd_bus)
    c.wire("metal4", [(x_vdd_e, grid(y_ch_e + ch_m.get("vdd_e_lo_y", -2.400))), (x_vdd_e, y_top_vdd_bus)], 0.560)

    # Stitch VDD UP into qdiv2 at West (dx_div - 0.90 = 24.10) and East (dx_div + 136.90 = 161.90)
    x_vdd_div_w = grid(dx_div - 0.900)                      # 24.100
    x_vdd_div_e = grid(dx_div + div_m["vdd_e"][0] + 0.500)  # 161.900
    c.wire("metal3", [(x_vdd_div_w, y_div_vdd), (dx_div, y_div_vdd)], 0.600)
    via3_pad(c, x_vdd_div_w, y_top_vdd_bus)
    via3_pad(c, x_vdd_div_w, y_div_vdd)
    c.wire("metal4", [(x_vdd_div_w, y_top_vdd_bus), (x_vdd_div_w, y_div_vdd)], 0.600)

    c.wire("metal3", [(x_vdd_e, y_top_vdd_bus), (x_vdd_div_e, y_top_vdd_bus)], 0.600)
    c.wire("metal3", [(grid(dx_div + div_m["vdd_e"][0]), y_div_vdd), (x_vdd_div_e, y_div_vdd)], 0.600)
    via3_pad(c, x_vdd_div_e, y_top_vdd_bus)
    via3_pad(c, x_vdd_div_e, y_div_vdd)
    c.wire("metal4", [(x_vdd_div_e, y_top_vdd_bus), (x_vdd_div_e, y_div_vdd)], 0.600)

    # 8. West Perimeter Extensions (`ip, qp, in, qn`, `rst_n`, `vdd`, `vss` at x_west = -1.600)
    x_west = -1.600
    y_rstn = grid(dy_div + div_m["rst_n"][1])  # 57.250
    c.wire("metal3", [(x_west, y_rstn), (dx_div, y_rstn)], 0.400)
    c.wire("metal3", [(x_west, y_top_vss_bus), (0.000, y_top_vss_bus)], 0.560)
    c.wire("metal3", [(x_west, y_top_vdd_bus), (0.000, y_top_vdd_bus)], 0.600)
    west_iq: dict[str, tuple[float, float]] = {}
    for nm in ("ip", "qp", "in", "qn"):
        yiq = grid(dy_oct + oct_m[nm][1])
        c.wire("metal3", [(x_west, yiq), (0.000, yiq)], 0.400)
        west_iq[nm] = (x_west, yiq)

    # 9. East Equal-Span M4 Stitch -> QDiv2 (v2 shields (ep,en) from (dp,dn) with grounded VSS M4 spine while preserving EXACT 4 East port coordinates!)
    x_rot_east = grid(dx_ch + ch_m["op_pt"][0])  # 165.400
    x_div_east = grid(dx_div + div_m["dp"][0])   # 165.400
    rot_out_ys = {
        "dp": grid(y_ch_d + ch_m["op_pt"][1]),
        "dn": grid(y_ch_d + ch_m["on_pt"][1]),
        "ep": grid(y_ch_e + ch_m["op_pt"][1]),
        "en": grid(y_ch_e + ch_m["on_pt"][1]),
    }
    x_east = grid(x_div_east + 5.900)    # 171.300
    if is_v2:
        # Quadrature-interleaved non-Miller M4 order [dp, ep, dn, en] (ZERO 180-deg Miller!) + exact drop-in East ports!
        stitch_xs = {
            "dp": grid(x_div_east + 1.500),  # 166.900
            "ep": grid(x_div_east + 2.700),  # 168.100
            "dn": grid(x_div_east + 3.900),  # 169.300
            "en": grid(x_div_east + 5.100),  # 170.500
        }
        port_ys = {
            "dp": grid(dy_div - 3.400),  # 59.800 (exact v1 drop-in!)
            "ep": grid(dy_div - 2.550),  # 60.650 (exact v1 drop-in!)
            "dn": grid(dy_div - 1.700),  # 61.500 (exact v1 drop-in!)
            "en": grid(dy_div - 0.850),  # 62.350 (exact v1 drop-in!)
        }
        y_st_lo = min(rot_out_ys.values())
        y_st_hi = max(max(grid(dy_div + div_m[nm][1]), port_ys[nm]) for nm in ("dp", "dn", "ep", "en"))
        east_ports: dict[str, tuple[float, float]] = {}
        for nm in ("dp", "dn", "ep", "en"):
            xr = stitch_xs[nm]
            y_from = rot_out_ys[nm]
            y_div = grid(dy_div + div_m[nm][1])
            y_port = port_ys[nm]
            c.wire("metal3", [(x_rot_east, y_from), (xr, y_from)], 0.360)
            via3_pad(c, xr, y_from)
            c.wire("metal4", [(xr, y_st_lo), (xr, y_st_hi)], 0.340)
            via3_pad(c, xr, y_div)
            c.wire("metal3", [(x_div_east, y_div), (xr, y_div)], 0.360)
            if abs(y_port - y_div) > 0.01:
                via3_pad(c, xr, y_port)
            c.wire("metal3", [(xr, y_port), (x_east, y_port)], 0.360)
            east_ports[nm] = (x_east, y_port)
    else:
        stitch_xs = {
            "dp": grid(x_div_east + 1.500),  # 166.900
            "ep": grid(x_div_east + 2.700),  # 168.100
            "dn": grid(x_div_east + 3.900),  # 169.300
            "en": grid(x_div_east + 5.100),  # 170.500
        }
        y_st_lo = min(rot_out_ys.values())
        y_st_hi = max(grid(dy_div + div_m[nm][1]) for nm in ("dp", "dn", "ep", "en"))
        east_ports = {}
        for nm in ("dp", "dn", "ep", "en"):
            xr = stitch_xs[nm]
            y_from = rot_out_ys[nm]
            y_to = grid(dy_div + div_m[nm][1])
            c.wire("metal3", [(x_rot_east, y_from), (xr, y_from)], 0.360)
            via3_pad(c, xr, y_from)
            c.wire("metal4", [(xr, y_st_lo), (xr, y_st_hi)], 0.340)
            via3_pad(c, xr, y_to)
            c.wire("metal3", [(x_div_east, y_to), (x_east, y_to)], 0.360)
            east_ports[nm] = (x_east, y_to)

    # 10. North 1.25 GHz Output Clocks (`ckd0..3, cke0..3`, uniform 16.0 um pitch)
    north_ports = {
        nm: (grid(dx_div + div_m[nm][0]), grid(dy_div + div_m[nm][1]))
        for nm in ("ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3")
    }

    port_coords: dict[str, dict] = {}
    if add_ports:
        for nm in ("ip", "qp", "in", "qn"):
            c.port(nm, "metal3", *west_iq[nm])
            port_coords[nm] = {"edge": "west", "layer": "metal3", "xy_um": list(west_iq[nm])}
        for grp in ("a", "b", "f"):
            for k in range(8):
                nm = f"{grp}{k}"
                c.port(nm, "metal2", *south_pins[nm])
                port_coords[nm] = {"edge": "south", "layer": "metal2", "xy_um": list(south_pins[nm])}
        c.port("rst_n", "metal3", x_west, y_rstn)
        port_coords["rst_n"] = {"edge": "west", "layer": "metal3", "xy_um": [x_west, y_rstn]}
        for nm in ("dp", "dn", "ep", "en"):
            c.port(nm, "metal3", *east_ports[nm])
            port_coords[nm] = {"edge": "east", "layer": "metal3", "xy_um": list(east_ports[nm])}
        for nm in ("ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3"):
            c.port(nm, "metal4", *north_ports[nm])
            port_coords[nm] = {"edge": "north", "layer": "metal4", "xy_um": list(north_ports[nm])}
        c.port("vdd", "metal3", x_west, y_top_vdd_bus)
        c.port("vss", "metal3", x_west, y_top_vss_bus)
        port_coords["vdd"] = {"edge": "west", "layer": "metal3", "xy_um": [x_west, y_top_vdd_bus]}
        port_coords["vss"] = {"edge": "west", "layer": "metal3", "xy_um": [x_west, y_top_vss_bus]}

    return c, {
        "port_coords": port_coords,
        "west_iq": west_iq,
        "north_ports": north_ports,
        "east_ports": east_ports,
        "south_ports": south_pins,
        "dy_oct": dy_oct,
        "dx_ch": dx_ch,
        "dx_div": dx_div,
        "dy_div": dy_div,
    }


# ---------------------------------------------------------------------------
# Internal Octature + PI Mix CPEX Extractor & Independent Signoff Driver
# ---------------------------------------------------------------------------

def extract_octature_internal_cpex(pex_path: Path) -> dict[str, dict]:
    """Identify the 4 slew nodes (`ips/qps/ins/qns`) and 8 octature mix nodes (`m0..m7`) by topology."""
    from collections import Counter

    if not pex_path.exists():
        return {}
    mim_cnt: Counter[str] = Counter()
    res69_cnt: Counter[str] = Counter()
    for ln in pex_path.read_text().splitlines():
        if not ln.startswith("X"):
            continue
        toks = ln.split()
        if "cap_mim_m3_1" in ln:
            mim_cnt[toks[1]] += 1
            mim_cnt[toks[2]] += 1
        if "res_high_po_0p69" in ln:
            res69_cnt[toks[1]] += 1
            res69_cnt[toks[2]] += 1

    all_caps = rlc.parse_all_pex_node_caps(pex_path)

    def _y_coord(net: str) -> float:
        m = re.match(r"a_n?\d+_(n?)(\d+)#", net)
        if not m:
            return 0.0
        val = int(m.group(2)) / 200.0
        return -val if m.group(1) == "n" else val

    # Octature mix nodes `m0..m7` connect to 1 MIM cap (cac_oct) and 2 res_high_po_0p69 (Xra, Xrb)
    oct_m_nodes = sorted([n for n in mim_cnt if mim_cnt[n] == 1 and res69_cnt[n] == 2], key=_y_coord)
    out: dict[str, dict] = {}
    if len(oct_m_nodes) == 8:
        # Bottom-to-top Y order: m4, m0, m5, m1, m6, m2, m7, m3
        m_names = ["m4", "m0", "m5", "m1", "m6", "m2", "m7", "m3"]
        for logical, raw in zip(m_names, oct_m_nodes):
            if raw in all_caps:
                out[logical] = {"extracted_net": raw, **all_caps[raw]}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=sorted(VARIANT_CONFIGS.keys()), default="v5g_4ph_v3_pdk",
                    help="Layout variant to build/signoff (default: v5g_4ph_v3_pdk)")
    ap.add_argument("--only", nargs="*", default=["octature", "pi4ph"],
                    help="Cells to build: octature, pi4ph")
    ap.add_argument("--signoff", action="store_true",
                    help="Run independent `review_cell.py --rc`, install into variants/<variant>/, write summary.json")
    args = ap.parse_args()

    cfg = VARIANT_CONFIGS[args.variant]
    variant_dir = Path(cfg["variant_dir"])
    results_dir = Path(cfg["results_dir"])
    source_spice = str(cfg["source_spice"])
    spice_filename = Path(source_spice).name

    variant_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(results_dir / "_pdk_cache")

    targets = [
        ("octature", "serdes_rx_octature_4to8_2p5g_pdk", "serdes_rx_octature_4to8_2p5g",
         lambda: build_rx_octature_4to8_2p5g_pdk(cache, add_ports=True, variant=args.variant),
         ["ip", "qp", "in", "qn", "cb0", "cb1", "cb2", "cb3", "cb4", "cb5", "cb6", "cb7", "vdd", "vss"]),
        ("pi4ph", "serdes_rx_pi_4ph_5g_pdk", "serdes_rx_pi_4ph_iq_8ph",
         lambda: build_rx_pi_4ph_5g_pdk(cache, add_ports=True, variant=args.variant),
         ["ip", "qp", "in", "qn", "rst_n", "dp", "dn", "ep", "en",
          "ckd0", "ckd1", "ckd2", "ckd3", "cke0", "cke1", "cke2", "cke3", "vdd", "vss"]),
    ]

    summary_path = variant_dir / "summary.json"
    summary_doc = json.loads(summary_path.read_text()) if summary_path.exists() else {
        "variant": args.variant,
        "source_spice": source_spice,
        "pdk": "sky130A",
        "cells": {},
    }

    for key, cell_name, src_subckt, builder, watch_nets in targets:
        if key not in args.only:
            continue
        if args.signoff:
            print(f"\n=== Independent Signoff (`review_cell.py --rc`) for {cell_name} [{args.variant}] ({src_subckt}) ===", flush=True)
            mag = variant_dir / f"{cell_name}.mag"
            ref = variant_dir / f"{cell_name}_ref.spice"
            lvs_out = variant_dir / f"{cell_name}_lvs.spice"
            pex_out = variant_dir / f"{cell_name}_pex.spice"
            png = variant_dir / f"{cell_name}.png"
            review_dir = results_dir / "review" / cell_name

            cell, meta = builder()
            cell.write(mag)
            expected_ports = generate_rx_4ph_ref_spice(src_subckt, cell_name, ref, spice_filename=spice_filename)
            rev = pi5._run_review_with_rc_audit(mag, ref, review_dir, timeout_s=240)

            shutil.copy2(review_dir / f"{cell_name}_lvs.spice", lvs_out)
            shutil.copy2(review_dir / f"{cell_name}_pex.spice", pex_out)

            chk = pi5._parse_check_log(review_dir / "check.log")
            fp = rlc.count_floating_poly(mag)
            mshares = rlc.compute_metal_shares(mag)
            lvs_log = review_dir / f"{cell_name}_lvs.log"
            lvs_txt = lvs_log.read_text() if lvs_log.exists() else ""
            lvs_match = "Circuits match uniquely" in lvs_txt
            lvs_prop_err = "Property errors were found" in lvs_txt
            raw_dev_count = sum(1 for ln in ref.read_text().splitlines() if ln.startswith("X"))

            w_um = round(rev["size_um"][0], 3)
            h_um = round(rev["size_um"][1], 3)
            area_um2 = round(w_um * h_um, 2)
            ar = round(w_um / max(h_um, 1e-6), 2)

            pcaps = rev.get("parasitics", {}).get("port_caps_fF", {})
            key_caps = {k: pcaps[k] for k in watch_nets if k in pcaps}
            rc_nets = pi5._parse_rcx_net_resistors(review_dir / f"{cell_name}_rcx.spice", watch_nets)
            internal_cpex = {}
            internal_cpex.update(extract_octature_internal_cpex(review_dir / f"{cell_name}_pex.spice"))
            if key == "pi4ph":
                internal_cpex.update(pi5.extract_pi_mix_internal_cpex(review_dir / f"{cell_name}_pex.spice"))

            rlc.render_png_plot_mag(mag, png)

            # Collect exact port coordinates directly from written .mag labels
            mag_labels = {nm: {"layer": lyr, "xy_um": [round(x, 3), round(y, 3)]}
                          for lyr, x, y, nm in Cell.read(mag).labels}

            rc_info = rev.get("rc", {})
            entry = {
                "cell": cell_name,
                "source_subckt": src_subckt,
                "mag": str(mag.relative_to(rlc.REPO)),
                "ref_spice": str(ref.relative_to(rlc.REPO)),
                "lvs_spice": str(lvs_out.relative_to(rlc.REPO)),
                "pex_spice": str(pex_out.relative_to(rlc.REPO)),
                "png": str(png.relative_to(rlc.REPO)),
                "review_dir": str(review_dir.relative_to(rlc.REPO)),
                "rcx_spice": str((review_dir / f"{cell_name}_rcx.spice").relative_to(rlc.REPO)),
                "bbox_um": [round(v, 3) for v in rev["bbox_um"]],
                "width_um": w_um,
                "height_um": h_um,
                "area_um2": area_um2,
                "aspect_ratio": ar,
                "expected_port_count": len(expected_ports),
                "exported_port_count": len(rev["ports"]),
                "exported_ports": rev["ports"],
                "port_coords": meta.get("port_coords", mag_labels),
                "port_count_match": (len(rev["ports"]) == len(expected_ports) and set(rev["ports"]) == set(expected_ports)),
                "physical_passed": rev["physical_passed"],
                "drc_total": chk["drc_total"],
                "floating_poly": fp,
                "lvs_match": lvs_match,
                "lvs_property_errors": lvs_prop_err,
                "rc_devices_preserved": rc_info.get("devices_preserved", False),
                "rc_review_strict_passed": rc_info.get("review_cell_rc_strict_passed", False),
                "rc_connectivity_and_wl_preserved": rc_info.get("connectivity_and_wl_preserved", False),
                "rc_shorted_supply_moscap_as_ps_diffs": rc_info.get("shorted_supply_moscap_as_ps_diffs", 0),
                "rc_note": rc_info.get("note", ""),
                "rc_resistor_count": rc_info.get("resistor_count", 0),
                "raw_device_count": raw_dev_count,
                "merged_device_count": chk["merged_device_count"],
                "net_count": chk["net_count"],
                "metal_shares": mshares,
                "key_port_caps_fF": key_caps,
                "internal_cpex_fF": internal_cpex,
                "key_net_rcx_ohm": rc_nets,
            }
            summary_doc["cells"][cell_name] = entry

            assert entry["drc_total"] == 0, f"{cell_name}: DRC={entry['drc_total']}"
            assert entry["floating_poly"] == 0, f"{cell_name}: FP={entry['floating_poly']}"
            assert entry["lvs_match"] is True, f"{cell_name}: LVS mismatch"
            assert entry["lvs_property_errors"] is False, f"{cell_name}: LVS property errors"
            assert entry["port_count_match"] is True, f"{cell_name}: port count mismatch"
            assert entry["physical_passed"] is True, f"{cell_name}: physical_passed=False"
            assert entry["rc_connectivity_and_wl_preserved"] is True, f"{cell_name}: RC connectivity/W/L failed"
            if key == "octature":
                assert entry["rc_devices_preserved"] is True, f"{cell_name}: strict rc_devices_preserved=False"
            assert entry["metal_shares"]["share_pct"]["M5"] == 0.0, f"{cell_name}: non-zero M5!"
            if args.variant == "v5g_4ph_v3_pdk" and key == "pi4ph":
                v1_sum_path = HERE / "variants" / "v5g_4ph_pdk" / "summary.json"
                if v1_sum_path.exists():
                    v1_sum = json.loads(v1_sum_path.read_text())
                    v1_pi = v1_sum["cells"]["serdes_rx_pi_4ph_5g_pdk"]
                    assert entry["bbox_um"] == v1_pi["bbox_um"], f"BBox drift: {entry['bbox_um']} != {v1_pi['bbox_um']}"
                    assert entry["port_coords"] == v1_pi["port_coords"], "43-port coordinate mismatch vs v5g_4ph_pdk!"
                else:
                    assert entry["bbox_um"] == [-1.9, -0.5, 171.48, 72.22], (
                        f"BBox drift vs canonical v5g_4ph_v3_pdk: {entry['bbox_um']}"
                    )
                    assert len(entry["port_coords"]) == 43, (
                        f"Expected 43 canonical perimeter ports, got {len(entry['port_coords'])}"
                    )

            print(
                f"  PASS {cell_name}: {w_um:.2f} x {h_um:.2f} um ({area_um2:,.2f} um^2, AR={ar:.2f}) | "
                f"DRC=0 | LVS=MATCH (prop_err=False) | FP=0 | ports={len(rev['ports'])}/{len(expected_ports)} | "
                f"devs={raw_dev_count} | RC_strict={entry['rc_devices_preserved']} "
                f"(WL+conn=True, moscap_asps_diffs={entry['rc_shorted_supply_moscap_as_ps_diffs']}) | "
                f"M1-5={mshares['share_pct']}",
                flush=True,
            )
            if internal_cpex:
                print(f"  internal CPEX: {json.dumps(internal_cpex)}", flush=True)
        else:
            print(f"\n=== Building & Verifying {cell_name} [{args.variant}] ({src_subckt}) ===", flush=True)
            work = results_dir / f"work_{key}"
            work.mkdir(parents=True, exist_ok=True)
            mag = work / f"{cell_name}.mag"
            ref = work / f"{cell_name}_ref.spice"
            png = work / f"{cell_name}.png"
            cell, _meta = builder()
            cell.write(mag)
            expected_ports = generate_rx_4ph_ref_spice(src_subckt, cell_name, ref, spice_filename=spice_filename)
            rep = rlc.verify_flat_cell(work, cell_name, mag, ref, expected_ports, timeout_s=180)
            rlc.render_png_plot_mag(mag, png)
            print(json.dumps({
                k: rep[k] for k in (
                    "cell", "bbox_um", "width_um", "height_um", "area_um2", "aspect_ratio",
                    "drc_total", "drc_rules", "lvs_match", "lvs_property_errors",
                    "lvs_disconnected", "port_count_match", "floating_poly", "metal_shares",
                )
            }, indent=2))
            pcaps = rep["parasitics"].get("port_caps_fF", {})
            for k in watch_nets:
                if k in pcaps:
                    print(f"  C({k:5s}) = {pcaps[k]['total_node_fF']:.3f} fF "
                          f"(sub={pcaps[k]['to_substrate_fF']:.3f}, cpl={pcaps[k]['coupling_sum_fF']:.3f})")
            icp = extract_octature_internal_cpex(work / f"{cell_name}_pex.spice")
            if icp:
                print("  Octature m0..m7 CPEX:")
                for k, v in icp.items():
                    print(f"    C({k:3s}) = {v['total_node_fF']:.3f} fF (sub={v['to_substrate_fF']:.3f}, cpl={v['coupling_sum_fF']:.3f})")

    if args.signoff:
        summary_path.write_text(json.dumps(summary_doc, indent=2) + "\n")
        print(f"\nUpdated signoff summary: {summary_path}")


if __name__ == "__main__":
    main()
