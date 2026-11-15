#!/usr/bin/env python3
"""Build & verify the complete 8-cell Ultra-Compact SKY130 PDK Divider /8 & Dummy Load Suite
(Plan J2: Center-Symmetric Dual-Wing + Single Central Grounded Dummy Gate + Merged Resistor Bank,
with MOS/Res Dummies, S/D Vertical Split, Single-Sided Gate Contacts, and Guard-Ring Abutment).

Implements unmodified schematics from ``analog/pll/divider/spice/{cml_latch,cml_div2,cml_prescaler8}.spice``
and ``analog/pll/top/spice/clock_frontend_r6q.spice``:
1. ``pll_frontend_dummy_load_pdk``    : 80um LVT SF + 4um sink + 64um LVT MOS cap load (+ MOS dummies)
2. ``pll_cml_tail_bias_pdk``          : Center-Symmetric Dual-Wing Tail Bias (Xpd + Xsink on Left Wing, Xpm + Xref on Right Wing)
3. ``pll_cml_latch_h40_pdk``          : Compact Abutted 2 GHz CML latch (wdata=20, whold=40, wclock=64, wtail=72, R=600 + MOS/Res dummies)
4. ``pll_cml_latch_h80_pdk``          : Compact Abutted CML latch (wdata=20, whold=80, wclock=64, wtail=72, R=600 + MOS/Res dummies)
5. ``pll_cml_div2_biased_h40_pdk``    : /2 divider stage (Center-Symmetric Dual-Wing: Xfp/Xsp Left Wing, Master|Slave with 1 shared grounded tail dummy & 6-resistor bank in Center, Xfn/Xsn Right Wing)
6. ``pll_cml_div2_biased_h80_pdk``    : /4 & /8 divider stage (Center-Symmetric Dual-Wing h80)
7. ``pll_div_buffer_pdk``             : Center-Symmetric Dual-Wing Interstage CML Buffer (Xn+Xt_L+Xr1 on Left Wing, Xp+Xt_R+Xr0 on Right Wing, sharing inner dummy resistors with div2)
8. ``pll_cml_prescaler8_pdk``         : Complete /8 prescaler Center-Symmetric Dual-Wing pipeline (Xbias+X2 in Stage 1, Xb24+X4 in Stage 2, Xb48+X8 in Stage 3)
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

REPO = Path("/home/host/Desktop/workspace/simple_serdes_fork1")
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def run_signoff(w: Path, cell: str, ref_text: str) -> dict:
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text(ref_text)
    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(w / f"{cell}.mag").bbox()
    res = {
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
    print(
        f"{res['cell']:30s} | DRC={res['drc_boxes']} | LVS={res['lvs_match']} | "
        f"PROP_ERR={res['lvs_property_errors']} | ports={len(res['exported_ports'])} | "
        f"size={res['size_um']} um | area={res['area_um2']} um2",
        flush=True,
    )
    return res


def prepare_mos_prim(
    work: Path,
    name: str,
    model: str,
    params: dict,
    *,
    trim_top_gate: bool = True,
    split_sd: bool = True,
    add_dummies: bool = True,
    open_left_gr: bool = False,
    open_right_gr: bool = False,
) -> Cell:
    raw = pdk_device(work, f"{name}_raw", model, params)
    raw.rects.pop("checkpaint", None)

    is_pmos = "pfet" in model
    diff_k = "pdiff" if is_pmos else "ndiff"
    diffc_k = "pdiffc" if is_pmos else "ndiffc"
    well_k = "nwell" if is_pmos else "pwell"
    sub_k = "nsubdiff" if is_pmos else "psubdiff"
    sc_k = sub_k + "cont"

    diff_x = max(r[2] for r in raw.rects[diff_k])
    diff_y = max(r[3] for r in raw.rects[diff_k])
    guard_top = max((r[1] + r[3]) / 2.0 for r in raw.rects[sc_k])
    l_poly = float(params["l"])

    if trim_top_gate:
        raw.rects["polycont"] = [r for r in raw.rects["polycont"] if r[1] < 0]
        raw.rects["locali"] = [
            r
            for r in raw.rects["locali"]
            if not (diff_y + 0.02 < r[1] < guard_top - 0.10 and diff_y + 0.02 < r[3] < guard_top - 0.10)
        ]
        raw.rects["viali"] = [r for r in raw.rects["viali"] if r[3] < diff_y + 0.05]
        raw.rects["metal1"] = [r for r in raw.rects["metal1"] if r[3] < diff_y + 0.05]

        new_poly = []
        for r in raw.rects["poly"]:
            if r[1] >= diff_y + 0.10:
                continue
            elif r[3] > diff_y:
                new_poly.append((r[0], r[1], r[2], grid(diff_y + 0.18)))
            else:
                new_poly.append(r)
        raw.rects["poly"] = new_poly
        raw.labels = [lbl for lbl in raw.labels if not (lbl[3] == "G" and lbl[2] > 0)]

    if split_sd:
        sd = sorted({grid((r[0] + r[2]) / 2.0) for r in raw.rects[diffc_k]})
        sources = sd[::2]
        drains = sd[1::2]
        raw.rects["viali"] = [r for r in raw.rects["viali"] if not (-diff_y - 0.02 <= r[1] and r[3] <= diff_y + 0.02)]
        raw.rects["metal1"] = [r for r in raw.rects["metal1"] if not (-diff_y - 0.02 <= r[1] and r[3] <= diff_y + 0.02)]
        for sx in sources:
            raw.rects["viali"].append((grid(sx - 0.085), grid(-diff_y + 0.06), grid(sx + 0.085), grid(-diff_y + 0.90)))
            raw.rects["metal1"].append((grid(sx - 0.115), grid(-diff_y), grid(sx + 0.115), grid(-diff_y + 0.96)))
        for dx in drains:
            raw.rects["viali"].append((grid(dx - 0.085), grid(-diff_y + 1.20), grid(dx + 0.085), grid(diff_y - 0.06)))
            raw.rects["metal1"].append((grid(dx - 0.115), grid(-diff_y + 1.14), grid(dx + 0.115), grid(diff_y)))

    if add_dummies:
        if l_poly <= 0.155:
            for sign in (-1.0, 1.0):
                if (sign < 0 and open_left_gr) or (sign > 0 and open_right_gr):
                    continue
                x0, x1 = sorted((grid(sign * (diff_x + 0.095)), grid(sign * (diff_x + 0.245))))
                raw.rect("poly", x0, -diff_y, x1, diff_y)
        else:
            dx_exp = grid(l_poly - 0.10)
            x_thresh = diff_x + 0.10
            for lyr in (well_k, sub_k, sc_k, "locali"):
                new_rects = []
                for x0, y0, x1, y1 in raw.rects.get(lyr, []):
                    if x0 > -x_thresh and x1 < x_thresh:
                        new_rects.append((x0, y0, x1, y1))
                        continue
                    nx0 = grid(x0 - dx_exp) if x0 < -x_thresh else (grid(x0 + dx_exp) if x0 > x_thresh else x0)
                    nx1 = grid(x1 - dx_exp) if x1 < -x_thresh else (grid(x1 + dx_exp) if x1 > x_thresh else x1)
                    new_rects.append((nx0, y0, nx1, y1))
                raw.rects[lyr] = new_rects
            new_sc = []
            for x0, y0, x1, y1 in raw.rects[sc_k]:
                if abs(x0 + diff_x) < 0.05 and abs(x1 - diff_x) < 0.05:
                    new_sc.append((grid(x0 - dx_exp), y0, grid(x1 + dx_exp), y1))
                else:
                    new_sc.append((x0, y0, x1, y1))
            raw.rects[sc_k] = new_sc
            for lyr in (sub_k, "locali"):
                adj = []
                for x0, y0, x1, y1 in raw.rects[lyr]:
                    if abs(x1 + diff_x) < 0.05 and x0 < -x_thresh:
                        adj.append((x0, y0, grid(x1 - dx_exp), y1))
                    elif abs(x0 - diff_x) < 0.05 and x1 > x_thresh:
                        adj.append((grid(x0 + dx_exp), y0, x1, y1))
                    else:
                        adj.append((x0, y0, x1, y1))
                raw.rects[lyr] = adj
            gap_inner = 0.115
            for sign in (-1.0, 1.0):
                if (sign < 0 and open_left_gr) or (sign > 0 and open_right_gr):
                    continue
                x0, x1 = sorted((grid(sign * (diff_x + gap_inner)), grid(sign * (diff_x + gap_inner + l_poly))))
                raw.rect("poly", x0, -diff_y, x1, diff_y)

    if open_left_gr or open_right_gr:
        for lyr in (sub_k, sc_k, "locali"):
            kept = []
            for x0, y0, x1, y1 in raw.rects.get(lyr, []):
                is_vert_leg = (y1 - y0) > 1.0
                if is_vert_leg and open_left_gr and x1 < -diff_x:
                    continue
                if is_vert_leg and open_right_gr and x0 > diff_x:
                    continue
                nx0 = max(x0, -diff_x) if (open_left_gr and not is_vert_leg) else x0
                nx1 = min(x1, +diff_x) if (open_right_gr and not is_vert_leg) else x1
                if nx1 > nx0:
                    kept.append((nx0, y0, nx1, y1))
            raw.rects[lyr] = kept

    return raw


def build_res_dummy(res_prim: Cell) -> Cell:
    dum = Cell()
    for lyr in ("pwell", "psubdiff", "psubdiffcont", "locali", "viali", "metal1"):
        dum.rects[lyr] = list(res_prim.rects[lyr])
    y_poly = max(r[3] for r in res_prim.rects["xpolycontact"])
    y_res = max(r[3] for r in res_prim.rects["ppolyres"])
    y_gr = max(r[3] for r in res_prim.rects["psubdiffcont"])
    dum.rect("poly", -1.425, -y_poly, 1.425, y_poly)
    dum.rects["locali"].extend([
        (-1.425, +y_res, +1.425, +y_poly),
        (-1.425, -y_poly, +1.425, -y_res),
        (-0.20, -y_gr, +0.20, -y_poly),
    ])
    dum.rects["polycont"] = list(res_prim.rects["viali"])
    return dum


def add_grounded_dummy_poly(
    c: Cell,
    x_c: float,
    diff_y: float,
    l_poly: float = 0.500,
    ground_y: float = -3.100,
) -> None:
    """Place a single shared L=0.50um dummy poly gate centered at x_c and tie it to M1 VSS at ground_y."""
    yg = grid(-diff_y - 0.275)
    c.rect("poly", grid(x_c - l_poly / 2.0), grid(yg - 0.165), grid(x_c + l_poly / 2.0), grid(diff_y + 0.180))
    c.pad("polycont", x_c, yg, 0.17)
    c.rect("locali", grid(x_c - 0.165), grid(yg - 0.165), grid(x_c + 0.165), grid(yg + 0.165))
    c.pad("viali", x_c, yg, 0.17)
    c.pad("metal1", x_c, yg, 0.34)
    c.wire("metal1", [(x_c, yg), (x_c, ground_y)], 0.34)


def strap_mos_split(
    c: Cell,
    prim: Cell,
    dx: float,
    dy: float,
    mirror_x: bool,
) -> tuple[list[float], list[float], float, float]:
    sign = -1 if mirror_x else 1
    diff_k = "pdiff" if "pdiff" in prim.rects else "ndiff"
    diffc_k = "pdiffc" if "pdiffc" in prim.rects else "ndiffc"
    diff_y = max(r[3] for r in prim.rects[diff_k])
    sd_local = sorted({grid((r[0] + r[2]) / 2.0) for r in prim.rects[diffc_k]})
    cy = grid(diff_y - 0.48)
    d_y = grid(dy + cy)
    s_y = grid(dy - cy)
    drains = sorted([grid(sign * x + dx) for x in sd_local[1::2]])
    sources = sorted([grid(sign * x + dx) for x in sd_local[::2]])
    for sx in sources:
        c.via1(sx, s_y)
    for dxp in drains:
        c.via1(dxp, d_y)
    if len(drains) > 1:
        c.wire("metal2", [(drains[0], d_y), (drains[-1], d_y)], 0.36)
    if len(sources) > 1:
        c.wire("metal2", [(sources[0], s_y), (sources[-1], s_y)], 0.36)
    return drains, sources, d_y, s_y


# ---------------------------------------------------------------------------
# 3 & 4. pll_cml_latch_h40_pdk & pll_cml_latch_h80_pdk (Standalone Latch)
# ---------------------------------------------------------------------------
def build_cml_latch_variant(out: Path, pcache: Path, whold: int) -> tuple[dict, Cell, dict]:
    cell = f"pll_cml_latch_h{whold}_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    nf_hold = whold // 5
    data = prepare_mos_prim(pcache, "latch_data4", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=4, conn_gates=1))
    hold = prepare_mos_prim(pcache, f"latch_hold{nf_hold}", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=nf_hold, conn_gates=1))
    clk = prepare_mos_prim(pcache, "latch_clk16", "sky130_fd_pr__nfet_01v8_lvt", dict(w=4.0, l=0.15, nf=16, conn_gates=1))
    tail = prepare_mos_prim(pcache, "latch_tail24", "sky130_fd_pr__nfet_01v8", dict(w=3.0, l=0.50, nf=24, conn_gates=1))
    load = pdk_device(pcache, "latch_load600", "sky130_fd_pr__res_high_po_2p85", dict(l=4.14))
    load.rects.pop("checkpaint", None)
    load_dum = build_res_dummy(load)

    c = Cell()
    cols = (-4.410, +4.410)
    data_cols = (-3.200, +3.200)
    res_xs = (-6.200, -2.220, +2.220, +6.200)
    side_x = 10.450

    ground_y = -3.100
    tail_y = 0.000
    clk_y = 5.070
    hold_y = 11.140
    data_y = 17.710
    body_rail_y = 20.995
    load_y = 25.710
    vdd_y = 30.900

    for y_gr in (2.285, 7.855, 14.425, 20.995):
        c.rect("psubdiffcont", -2.20, grid(y_gr - 0.085), +2.20, grid(y_gr + 0.085))
        c.rect("locali", -2.20, grid(y_gr - 0.085), +2.20, grid(y_gr + 0.085))

    c.wire("metal1", [(-side_x, ground_y), (side_x, ground_y)], 0.80)
    c.wire("metal1", [(-side_x, 2.285), (-side_x, body_rail_y)], 0.50)
    c.wire("metal1", [(side_x, ground_y), (side_x, body_rail_y)], 0.50)
    c.wire("metal1", [(-side_x, vdd_y), (side_x, vdd_y)], 0.80)

    for sx in (-8.20, +8.20):
        c.pad("viali", sx, -2.285, 0.17)
        c.pad("metal1", sx, -2.285, 0.32)
        c.wire("metal1", [(sx, -2.285), (sx, ground_y)], 0.34)
    for y_gr in (2.285, 7.855, 20.995):
        for bx, tx in ((-7.50, -side_x), (+7.50, +side_x)):
            c.pad("viali", bx, y_gr, 0.17)
            c.pad("metal1", bx, y_gr, 0.32)
            c.wire("metal1", [(bx, y_gr), (tx, y_gr)], 0.34)

    c.include(tail, dx=0.00, dy=tail_y)
    td_xs, ts_xs, td_y, ts_y = strap_mos_split(c, tail, 0.00, tail_y, False)
    for sx in (ts_xs[3], ts_xs[-4]):
        c.wire("metal2", [(sx, ts_y), (sx, ground_y)], 0.42)
        c.via1(sx, ground_y)

    tgy = grid(tail_y - 1.775)
    x_vbl_pin = -9.900
    y_vbl_port = -1.775
    c.wire("metal1", [(x_vbl_pin, tgy), (-9.365, tgy)], 0.24)
    c.via1(x_vbl_pin, y_vbl_port)
    c.pad("metal2", x_vbl_pin, y_vbl_port, 0.40)

    cs_y = None
    cd_y = None
    clk_gate_pts = {}
    for dx, nm, y_ck_port, mir in ((cols[0], "clk_track", 5.200, False), (cols[1], "clk_hold", 4.300, True)):
        c.include(clk, dx=dx, dy=clk_y, mirror_x=mir)
        d_xs, s_xs, cd_y, cs_y = strap_mos_split(c, clk, dx, clk_y, mir)
        cgy = grid(clk_y - 2.275)
        gx_out = grid(dx + (-3.60 if dx < 0 else +3.60))
        px = -9.300 if dx < 0 else +9.300
        c.wire("metal1", [(gx_out, cgy), (px, cgy)], 0.24)
        c.via1(px, cgy)
        c.wire("metal2", [(px, cgy), (px, y_ck_port)], 0.34)
        clk_gate_pts[nm] = (px, y_ck_port)

    c.wire("metal2", [(-1.50, cs_y), (+1.50, cs_y)], 0.44)
    c.wire("metal2", [(0.00, td_y), (0.00, cs_y)], 0.50)

    hs_y = None
    hd_y = None
    hold_gate_pts = {}
    for dx, side, mir in ((cols[0], "L", False), (cols[1], "R", True)):
        c.include(hold, dx=dx, dy=hold_y, mirror_x=mir)
        d_xs, s_xs, hd_y, hs_y = strap_mos_split(c, hold, dx, hold_y, mir)
        x_q = -3.000 if side == "L" else +3.000
        c.wire("metal2", [(min(d_xs[0], x_q), hd_y), (max(d_xs[-1], x_q), hd_y)], 0.36)
        c.via2(x_q, hd_y)
        hgy = grid(hold_y - 2.775)
        gx_in = grid(dx + (+1.68 if whold == 40 else +3.60)) if side == "L" else grid(dx - (+1.68 if whold == 40 else +3.60))
        ix = -2.100 if side == "L" else +2.100
        c.wire("metal1", [(gx_in, hgy), (ix, hgy)], 0.24)
        c.via1(ix, hgy)
        c.via2(ix, hgy)
        hold_gate_pts[side] = (ix, hgy)

    c.wire("metal2", [(-3.00, hs_y), (+3.00, hs_y)], 0.44)
    c.via2(+1.20, cd_y)
    c.via2(+1.20, hs_y)
    c.wire("metal3", [(+1.20, cd_y), (+1.20, hs_y)], 0.42)

    ds_y = None
    dd_y = None
    data_gate_pts = {}
    for dx, nm, y_d_port, mir in ((data_cols[0], "dp", 27.800, False), (data_cols[1], "dn", 26.700, True)):
        c.include(data, dx=dx, dy=data_y, mirror_x=mir)
        d_xs, s_xs, dd_y, ds_y = strap_mos_split(c, data, dx, data_y, mir)
        x_q = -3.000 if dx < 0 else +3.000
        c.wire("metal2", [(min(d_xs[0], x_q), dd_y), (max(d_xs[-1], x_q), dd_y)], 0.36)
        c.via2(x_q, dd_y)
        dgy = grid(data_y - 2.775)
        gx_out = grid(dx + (-0.72 if dx < 0 else +0.72))
        px = -8.600 if dx < 0 else +8.600
        c.wire("metal1", [(gx_out, dgy), (px, dgy)], 0.24)
        c.via1(px, dgy)
        c.wire("metal2", [(px, dgy), (px, y_d_port)], 0.34)
        data_gate_pts[nm] = (px, y_d_port)

    c.wire("metal2", [(-2.50, ds_y), (+2.50, ds_y)], 0.44)
    c.via2(-1.20, cd_y)
    c.via2(-1.20, ds_y)
    c.wire("metal3", [(-1.20, cd_y), (-1.20, ds_y)], 0.42)

    yc_qp, yc_qn = 10.300, 11.400
    for target_x, gate_pt, yc in ((+3.000, hold_gate_pts["L"], yc_qp), (-3.000, hold_gate_pts["R"], yc_qn)):
        gx, gy = gate_pt
        c.wire("metal3", [(gx, gy), (gx, yc)], 0.40)
        via3(c, gx, yc)
        via3(c, target_x, yc)
        c.wire("metal4", [(min(gx, target_x), yc), (max(gx, target_x), yc)], 0.44)

    c.include(load_dum, dx=res_xs[0], dy=load_y)
    c.include(load, dx=res_xs[1], dy=load_y)
    c.include(load, dx=res_xs[2], dy=load_y)
    c.include(load_dum, dx=res_xs[3], dy=load_y)

    r2_y = grid(load_y - 3.065)
    r1_y = grid(load_y + 3.975)
    for rx, x_q in ((res_xs[1], -3.000), (res_xs[2], +3.000)):
        c.via1(x_q, r2_y)
        c.via2(x_q, r2_y)
        c.wire("metal1", [(rx, r1_y), (rx, vdd_y)], 0.56)

    c.wire("metal3", [(-3.000, yc_qn), (-3.000, r2_y)], 0.46)
    c.wire("metal3", [(+3.000, yc_qp), (+3.000, r2_y)], 0.46)

    c.port("dp", "metal2", *data_gate_pts["dp"])
    c.port("dn", "metal2", *data_gate_pts["dn"])
    c.port("qp", "metal3", +3.000, r2_y)
    c.port("qn", "metal3", -3.000, r2_y)
    c.port("clk_track", "metal2", *clk_gate_pts["clk_track"])
    c.port("clk_hold", "metal2", *clk_gate_pts["clk_hold"])
    c.port("vbias", "metal2", x_vbl_pin, y_vbl_port)
    c.port("vdd", "metal1", 0.00, vdd_y)
    c.port("vss", "metal1", 0.00, ground_y)
    c.write(w / f"{cell}.mag")

    ref = "\n".join([
        f".subckt {cell} dp dn qp qn clk_track clk_hold vbias vdd vss",
        "Xrp vdd qp vss sky130_fd_pr__res_high_po_2p85 l=4.14",
        "Xrn vdd qn vss sky130_fd_pr__res_high_po_2p85 l=4.14",
        "Xdp qn dp track vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15",
        "Xdn qp dn track vss sky130_fd_pr__nfet_01v8_lvt w=20 l=0.15",
        f"Xhp qn qp hold vss sky130_fd_pr__nfet_01v8_lvt w={whold} l=0.15",
        f"Xhn qp qn hold vss sky130_fd_pr__nfet_01v8_lvt w={whold} l=0.15",
        "Xct track clk_track tail vss sky130_fd_pr__nfet_01v8_lvt w=64 l=0.15",
        "Xch hold clk_hold tail vss sky130_fd_pr__nfet_01v8_lvt w=64 l=0.15",
        "Xtail tail vbias vss vss sky130_fd_pr__nfet_01v8 w=72 l=0.5",
        f".ends {cell}",
        "",
    ])
    res = run_signoff(w, cell, ref)
    pins = {
        "dp": data_gate_pts["dp"],
        "dn": data_gate_pts["dn"],
        "qp": (+3.000, r2_y),
        "qn": (-3.000, r2_y),
        "clk_track": clk_gate_pts["clk_track"],
        "clk_hold": clk_gate_pts["clk_hold"],
        "vbias": (x_vbl_pin, y_vbl_port),
        "vdd_y": vdd_y,
        "ground_y": ground_y,
        "side_x": side_x,
    }
    return res, c, pins


# ---------------------------------------------------------------------------
# 5 & 6. pll_cml_div2_biased_h40_pdk & pll_cml_div2_biased_h80_pdk
#        Plan J2: Center-Symmetric Dual-Wing + Merged Dummy Architecture!
# ---------------------------------------------------------------------------
def build_div2_variant(out: Path, pcache: Path, whold: int) -> tuple[dict, Cell, dict]:
    cell = f"pll_cml_div2_biased_h{whold}_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    nf_hold = whold // 5
    data = prepare_mos_prim(pcache, "latch_data4", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=4, conn_gates=1))
    hold = prepare_mos_prim(pcache, f"latch_hold{nf_hold}", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=nf_hold, conn_gates=1))
    clk = prepare_mos_prim(pcache, "latch_clk16", "sky130_fd_pr__nfet_01v8_lvt", dict(w=4.0, l=0.15, nf=16, conn_gates=1))

    # Open the inner side (right side of Master, left side after mirror of Slave) of Xtail_M & Xtail_S
    # so they merge at x = 0.000 with ONE shared grounded dummy gate (G = VSS)!
    tail_inner_open = prepare_mos_prim(
        pcache, "latch_tail24_inopen", "sky130_fd_pr__nfet_01v8",
        dict(w=3.0, l=0.50, nf=24, conn_gates=1),
        open_left_gr=False, open_right_gr=True,
    )
    sink = prepare_mos_prim(pcache, "sink4_n", "sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.50, nf=1, conn_gates=1))
    sf8 = prepare_mos_prim(pcache, "sf40_lvt8", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=8, conn_gates=1))
    load = pdk_device(pcache, "latch_load600", "sky130_fd_pr__res_high_po_2p85", dict(l=4.14))
    load.rects.pop("checkpaint", None)
    load_dum = build_res_dummy(load)

    c = Cell()
    side_x = 26.995
    ground_y = -3.100
    tail_y = 0.000
    clk_y = 5.070
    hold_y = 11.140
    data_y = 17.710
    body_rail_y = 20.995
    load_y = 25.710
    vdd_y = 30.900

    dx_m = -9.975
    dx_s = +9.975
    # Outer vertical guard ring of Xtail_M/S is at +-9.975 +- 10.450 = +-20.425 um!
    # Place Xsp/Xsn at dx = +-21.950 so their inner vertical guard ring (+-21.950 -+ 1.525 = +-20.425)
    # merges 100% with Xtail_M/S's outer vertical guard ring at +-20.425!
    dx_sp = -21.950
    dx_sn = +21.950
    # Place Left Wing (Xfp = 2 x nf=8) & Right Wing (Xfn = 2 x nf=8) at dx = +-22.915 so their inner
    # vertical guard ring (+-22.915 -+ 2.490 = +-20.425) ALSO merges 100% along x = +-20.425!
    dx_wing_L = -22.915
    dx_wing_R = +22.915

    # Continuous horizontal power rails & vertical VSS straps
    c.wire("metal1", [(-side_x, ground_y), (side_x, ground_y)], 0.80)
    c.wire("metal1", [(-side_x, vdd_y), (side_x, vdd_y)], 0.80)
    c.wire("metal1", [(-side_x, ground_y), (-side_x, 21.495)], 0.50)
    c.wire("metal1", [(+side_x, ground_y), (+side_x, 21.495)], 0.50)
    c.wire("metal1", [(-20.425, 2.285), (-20.425, 15.925)], 0.50)
    c.wire("metal1", [(+20.425, 2.285), (+20.425, 15.925)], 0.50)

    # -----------------------------------------------------------------------
    # Row 1 (y = 0.000): Center-Merged Xtail_M + Xtail_S (sharing 1 grounded dummy gate at x = 0.000)
    #                    + Symmetric Outer Xsp (-21.950) & Xsn (+21.950)
    # -----------------------------------------------------------------------
    c.include(sink, dx=dx_sp, dy=tail_y, mirror_x=False)
    c.include(tail_inner_open, dx=dx_m, dy=tail_y, mirror_x=False)
    c.include(tail_inner_open, dx=dx_s, dy=tail_y, mirror_x=True)
    c.include(sink, dx=dx_sn, dy=tail_y, mirror_x=True)

    # Bridge pwell + top/bottom guard rings across x = 0.000 between Xtail_M and Xtail_S!
    c.rect("pwell", -20.60, -2.65, +20.60, +2.65)
    for y_gr in (-2.285, +2.285):
        c.rect("psubdiff", -19.80, grid(y_gr - 0.185), +19.80, grid(y_gr + 0.185))
        c.rect("psubdiffcont", -19.60, grid(y_gr - 0.085), +19.60, grid(y_gr + 0.085))
        c.rect("locali", -19.80, grid(y_gr - 0.085), +19.80, grid(y_gr + 0.085))

    # ONE Shared Central Grounded Dummy Poly Gate (G = VSS) at x = 0.000 between Xtail_M & Xtail_S!
    add_grounded_dummy_poly(c, 0.000, diff_y=1.500, l_poly=0.500, ground_y=ground_y)

    for bx in (-18.00, -8.00, +8.00, +18.00):
        c.pad("viali", bx, -2.285, 0.17)
        c.pad("metal1", bx, -2.285, 0.32)
        c.wire("metal1", [(bx, -2.285), (bx, ground_y)], 0.34)
    for bx_sk in (dx_sp, dx_sn):
        c.pad("viali", bx_sk, -2.785, 0.17)
        c.pad("metal1", bx_sk, -2.785, 0.32)
        c.wire("metal1", [(bx_sk, -2.785), (bx_sk, ground_y)], 0.34)

    # Strap Xtail_M & Xtail_S
    td_m, ts_m, td_y, ts_y = strap_mos_split(c, tail_inner_open, dx_m, tail_y, False)
    td_s, ts_s, _, _ = strap_mos_split(c, tail_inner_open, dx_s, tail_y, True)
    for sx in (ts_m[3], ts_m[-4], ts_s[3], ts_s[-4]):
        c.wire("metal2", [(sx, ts_y), (sx, ground_y)], 0.42)
        c.via1(sx, ground_y)

    # Strap Xsp & Xsn
    sp_d, sp_s, sk_dy, sk_sy = strap_mos_split(c, sink, dx_sp, tail_y, False)
    sn_d, sn_s, _, _ = strap_mos_split(c, sink, dx_sn, tail_y, True)
    for sx in (sp_s[0], sn_s[0]):
        c.wire("metal2", [(sx, sk_sy), (sx, ground_y)], 0.36)
        c.via1(sx, ground_y)

    # In-Cell Bottom M3 Bias & Clock Buses
    Y_CKP = +5.200
    Y_CKN = +4.300
    Y_VBLOGIC = -1.775
    Y_VBIAS = -2.550

    # Connect Xtail_M & Xtail_S gates (tgy = -1.775) to Y_VBLOGIC = -1.775
    for x_vbl in (grid(dx_m - 8.500), grid(dx_s + 8.500)):
        c.via1(x_vbl, Y_VBLOGIC)
        c.via2(x_vbl, Y_VBLOGIC)

    # Connect Xsp & Xsn gates (sk_gy = -2.275) to Y_VBIAS = -2.550
    sk_gy = -2.275
    for dx_k, x_vb_tap in ((dx_sp, -23.100), (dx_sn, +23.100)):
        c.wire("metal1", [(min(dx_k, x_vb_tap), sk_gy), (max(dx_k, x_vb_tap), sk_gy)], 0.22)
        c.via1(x_vb_tap, sk_gy)
        c.wire("metal2", [(x_vb_tap, sk_gy), (x_vb_tap, Y_VBIAS)], 0.34)
        c.via2(x_vb_tap, Y_VBIAS)

    c.wire("metal3", [(-side_x, Y_VBLOGIC), (+side_x, Y_VBLOGIC)], 0.42)
    c.wire("metal3", [(-side_x, Y_VBIAS), (+side_x, Y_VBIAS)], 0.42)

    # -----------------------------------------------------------------------
    # Left Wing (dx_wing_L = -22.915: Xfp = 2 x nf=8) & Right Wing (dx_wing_R = +22.915: Xfn = 2 x nf=8)
    # 100% Mirror-Symmetric around x = 0.000!
    # -----------------------------------------------------------------------
    dy_sf1 = 6.070
    dy_sf2 = 12.640
    clk_in_pts = {}
    for dx_w, sgn, clknm, y_ck, sk_dx in (
        (dx_wing_L, -1.0, "clkp", Y_CKP, sp_d[0]),
        (dx_wing_R, +1.0, "clkn", Y_CKN, sn_d[0]),
    ):
        mir_w = (sgn > 0)
        # Note: in sf8 (nf=8), source M2 bar spans dx_w +- 1.920 (-24.835..-20.995),
        # while drain M2 bar spans dx_w +- 1.440 (-24.355..-21.475).
        # Place vertical VDD M2 trunk at x_vdd_w = dx_w - sgn*2.650 (-20.265 / +20.265),
        # which is 0.37 um clear of the source M2 bar!
        x_vdd_w = grid(dx_w - sgn * 2.650)  # -20.265 / +20.265
        x_s_tap = grid(dx_w + sgn * 0.800)  # -23.715 / +23.715
        px_clk = grid(dx_w + sgn * 2.650)   # -25.565 / +25.565 (0.37 um outside source M2 bar!)

        for dy_f in (dy_sf1, dy_sf2):
            c.include(sf8, dx=dx_w, dy=dy_f, mirror_x=mir_w)
            d_xs, s_xs, fd_y, fs_y = strap_mos_split(c, sf8, dx_w, dy_f, mir_w)
            c.wire("metal2", [(min(d_xs[0], x_vdd_w), fd_y), (max(d_xs[-1], x_vdd_w), fd_y)], 0.36)
            c.via2(x_s_tap, fs_y)
            fgy = grid(dy_f - 2.775)
            gx_out = grid(dx_w + sgn * 1.440)
            c.wire("metal1", [(min(gx_out, px_clk), fgy), (max(gx_out, px_clk), fgy)], 0.22)
            c.via1(px_clk, fgy)

        # Tie the two stacked nf=8 gates together on M2 at px_clk and lift to M3 port at fgy2 = 9.865
        fgy1 = grid(dy_sf1 - 2.775)  # +3.295
        fgy2 = grid(dy_sf2 - 2.775)  # +9.865
        c.wire("metal2", [(px_clk, fgy1), (px_clk, fgy2)], 0.34)
        c.via2(px_clk, fgy2)
        c.pad("metal3", px_clk, fgy2, 0.52)
        clk_in_pts[clknm] = (px_clk, fgy2)

        # Tie both SF drain bars up to vdd_y on M2 via x_vdd_top = sgn*16.600 (-16.600 / +16.600, 100% clear of Upper Wings!)
        x_vdd_top = grid(sgn * 16.600)  # -16.600 / +16.600
        c.wire("metal2", [(x_vdd_w, grid(dy_sf1 + 2.02)), (x_vdd_w, grid(dy_sf2 + 2.02)), (x_vdd_top, grid(dy_sf2 + 2.02)), (x_vdd_top, vdd_y)], 0.36)
        c.via1(x_vdd_top, vdd_y)

        # Tie both SF source bars (fs_y1 = 4.050, fs_y2 = 10.620) + sink drain (sk_dx, sk_dy) on M3 to y_ck
        c.via2(sk_dx, sk_dy)
        c.wire("metal3", [(sk_dx, sk_dy), (sk_dx, y_ck)], 0.40)
        c.wire("metal3", [(x_s_tap, grid(dy_sf1 - 2.02)), (x_s_tap, grid(dy_sf2 - 2.02))], 0.42)

        # Tie Wing guard rings (y = 2.785, 9.355, 15.925) to outer M1 VSS vertical (+-side_x)
        for y_gr in (2.785, 9.355, 15.925):
            bx_w = grid(dx_w + sgn * 1.80)
            c.pad("viali", bx_w, y_gr, 0.17)
            c.pad("metal1", bx_w, y_gr, 0.32)
            c.wire("metal1", [(min(bx_w, sgn * side_x), y_gr), (max(bx_w, sgn * side_x), y_gr)], 0.34)

    # -----------------------------------------------------------------------
    # Rows 2, 3, 4 in Center Core: Master (dx_m = -9.975, mir=False) & Slave (dx_s = +9.975, mir=True)
    # -----------------------------------------------------------------------
    # Bridge guard rings inside Master, inside Slave, and across x = 0.000
    for y_gr, x_span, h_psd in ((2.285, 18.00, 0.170), (7.855, 18.00, 0.170), (14.425, 13.50, 0.170), (20.995, 12.50, 0.085)):
        c.rect("psubdiff", -x_span, grid(y_gr - h_psd), +x_span, grid(y_gr + h_psd))
        c.rect("psubdiffcont", grid(-x_span + 0.15), grid(y_gr - 0.085), grid(+x_span - 0.15), grid(y_gr + 0.085))
        c.rect("locali", -x_span, grid(y_gr - 0.085), +x_span, grid(y_gr + 0.085))
        c.pad("viali", 0.000, y_gr, 0.17)
        c.pad("metal1", 0.000, y_gr, 0.32)

    for y_gr, bx_abs in ((2.285, 17.50), (7.855, 17.50)):
        for bx, tx in ((-bx_abs, -20.425), (+bx_abs, +20.425)):
            c.pad("viali", bx, y_gr, 0.17)
            c.pad("metal1", bx, y_gr, 0.32)
            c.wire("metal1", [(min(bx, tx), y_gr), (max(bx, tx), y_gr)], 0.34)
    c.wire("metal1", [(0.000, 2.285), (0.000, body_rail_y)], 0.40)

    clk_pins = {}
    data_pins = {}
    yc_qp, yc_qn = 10.300, 11.400

    for side_ms, dx_c, sgn in (("M", dx_m, 1.0), ("S", dx_s, -1.0)):
        # Keep internal latch drain M3 verticals at dx_c - sgn*3.000 (-12.975/+12.975)
        # and dx_c + sgn*4.500 (-5.475/+5.475, well clear of rx = -6.660/+6.660!)
        x_qn_col = grid(dx_c - sgn * 3.000)  # -12.975 for M, +12.975 for S
        x_qp_col = grid(dx_c + sgn * 4.500)  # -5.475  for M, +5.475  for S

        # Row 2: Clock pair
        for col_off, nm, mir_local in ((-4.410, "ct", False), (+4.410, "ch", True)):
            dx = grid(dx_c + sgn * col_off)
            mir = mir_local if sgn > 0 else (not mir_local)
            c.include(clk, dx=dx, dy=clk_y, mirror_x=mir)
            d_xs, s_xs, cd_y, cs_y = strap_mos_split(c, clk, dx, clk_y, mir)
            cgy = grid(clk_y - 2.275)
            gx_out = grid(dx + sgn * (-3.60 if col_off < 0 else +3.60))
            px = grid(dx_c + sgn * (-9.300 if col_off < 0 else +9.300))
            c.wire("metal1", [(min(gx_out, px), cgy), (max(gx_out, px), cgy)], 0.24)
            c.via1(px, cgy)
            y_target = Y_CKP if ((side_ms == "M" and nm == "ct") or (side_ms == "S" and nm == "ch")) else Y_CKN
            c.wire("metal2", [(px, cgy), (px, y_target)], 0.34)
            c.via2(px, y_target)
            clk_pins[f"{side_ms}_{nm}"] = (px, y_target)

        c.wire("metal2", [(grid(dx_c - 1.50), cs_y), (grid(dx_c + 1.50), cs_y)], 0.44)
        c.wire("metal2", [(dx_c, td_y), (dx_c, cs_y)], 0.50)

        # Row 3: Hold pair
        hold_gate_pts = {}
        for col_off, hside, x_q_this, mir_local in (
            (-4.410, "outer", x_qn_col, False),
            (+4.410, "inner", x_qp_col, True),
        ):
            dx = grid(dx_c + sgn * col_off)
            mir = mir_local if sgn > 0 else (not mir_local)
            c.include(hold, dx=dx, dy=hold_y, mirror_x=mir)
            d_xs, s_xs, hd_y, hs_y = strap_mos_split(c, hold, dx, hold_y, mir)
            c.wire("metal2", [(min(*d_xs, x_q_this), hd_y), (max(*d_xs, x_q_this), hd_y)], 0.36)
            c.via2(x_q_this, hd_y)
            hgy = grid(hold_y - 2.775)
            off_g = +1.68 if whold == 40 else +3.60
            gx_in = grid(dx + sgn * (+off_g if col_off < 0 else -off_g))
            ix = grid(dx_c + sgn * (-2.100 if col_off < 0 else +2.100))
            c.wire("metal1", [(min(gx_in, ix), hgy), (max(gx_in, ix), hgy)], 0.24)
            c.via1(ix, hgy)
            c.via2(ix, hgy)
            hold_gate_pts[hside] = (ix, hgy)

        c.wire("metal2", [(grid(dx_c - 3.00), hs_y), (grid(dx_c + 3.00), hs_y)], 0.44)
        x_ch_up = grid(dx_c + sgn * 1.20)
        c.via2(x_ch_up, cd_y)
        c.via2(x_ch_up, hs_y)
        c.wire("metal3", [(x_ch_up, cd_y), (x_ch_up, hs_y)], 0.42)

        # Row 4: Data pair (keep outer dp M2 riser at dx_c - sgn*5.800 = +-15.775, clear of Xr0/Xr1 at +-14.620 and x_vdd_top at +-16.600!)
        for col_off, dnm, x_q_this, mir_local in (
            (-3.200, "dp", x_qn_col, False),
            (+3.200, "dn", x_qp_col, True),
        ):
            dx = grid(dx_c + sgn * col_off)
            mir = mir_local if sgn > 0 else (not mir_local)
            c.include(data, dx=dx, dy=data_y, mirror_x=mir)
            d_xs, s_xs, dd_y, ds_y = strap_mos_split(c, data, dx, data_y, mir)
            c.wire("metal2", [(min(*d_xs, x_q_this), dd_y), (max(*d_xs, x_q_this), dd_y)], 0.36)
            c.via2(x_q_this, dd_y)
            dgy = grid(data_y - 2.775)
            gx_out = grid(dx + sgn * (-0.72 if col_off < 0 else +0.72))
            px = grid(dx_c + sgn * (-5.800 if col_off < 0 else +8.500))
            c.wire("metal1", [(min(gx_out, px), dgy), (max(gx_out, px), dgy)], 0.24)
            c.via1(px, dgy)
            data_pins[f"{side_ms}_{dnm}"] = (px, dgy)

        c.wire("metal2", [(grid(dx_c - 2.50), ds_y), (grid(dx_c + 2.50), ds_y)], 0.44)
        x_ct_up = grid(dx_c - sgn * 1.20)
        c.via2(x_ct_up, cd_y)
        c.via2(x_ct_up, ds_y)
        c.wire("metal3", [(x_ct_up, cd_y), (x_ct_up, ds_y)], 0.42)

        # Cross-couple Hold pair gates on M4
        for target_x, gate_pt, yc in ((x_qp_col, hold_gate_pts["outer"], yc_qp), (x_qn_col, hold_gate_pts["inner"], yc_qn)):
            gx, gy = gate_pt
            c.wire("metal3", [(gx, gy), (gx, yc)], 0.40)
            via3(c, gx, yc)
            via3(c, target_x, yc)
            c.wire("metal4", [(min(gx, target_x), yc), (max(gx, target_x), yc)], 0.44)

    # Connect horizontal M3 clock buses Y_CKP & Y_CKN across Wing SFs & Center Latches
    c.wire("metal3", [(grid(dx_wing_L - 0.800), Y_CKP), (clk_pins["S_ch"][0], Y_CKP)], 0.42)
    c.wire("metal3", [(clk_pins["M_ch"][0], Y_CKN), (grid(dx_wing_R + 0.800), Y_CKN)], 0.42)

    # -----------------------------------------------------------------------
    # Row 5 (y = 25.710): Merged 6-Resistor Center Bank!
    # [Rdum_L(-10.640) | Rn_M(-6.660) | Rp_M(-2.220) | Rp_S(+2.220) | Rn_S(+6.660) | Rdum_R(+10.640)]
    # 4.440 um active-to-active pitch (0.84 um RPM spacing!) and 3.980 um active-to-dummy pitch!
    # -----------------------------------------------------------------------
    res_xs = (-10.640, -6.660, -2.220, +2.220, +6.660, +10.640)
    c.include(load_dum, dx=res_xs[0], dy=load_y)
    c.include(load, dx=res_xs[1], dy=load_y)
    c.include(load, dx=res_xs[2], dy=load_y)
    c.include(load, dx=res_xs[3], dy=load_y)
    c.include(load, dx=res_xs[4], dy=load_y)
    c.include(load_dum, dx=res_xs[5], dy=load_y)

    # Bridge top guard ring of resistor bank (y = 30.425) across the 0.46 um active-to-active gaps
    c.rect("psubdiff", -12.50, grid(30.425 - 0.085), +12.50, grid(30.425 + 0.085))
    c.rect("psubdiffcont", -12.20, grid(30.425 - 0.085), +12.20, grid(30.425 + 0.085))
    c.rect("locali", -12.50, grid(30.425 - 0.085), +12.50, grid(30.425 + 0.085))

    r2_y = grid(load_y - 3.065)  # +22.645
    r1_y = grid(load_y + 3.975)  # +29.685
    Y_MP = 24.500
    Y_MN = 25.600
    Y_QP = 26.700
    Y_QN = 27.800

    # Connect each latch's internal M3 drain column (x_col) up to its target M3 track (y_tr),
    # and connect each active resistor's bottom terminal (rx, r2_y) on M1->M2->M3->M4 up to y_tr!
    for rx, x_col, yc_start, y_tr in (
        (-6.660, grid(dx_m - 3.000), yc_qn, Y_MN),  # mn (-12.975 col & -6.660 res)
        (-2.220, grid(dx_m + 4.500), yc_qp, Y_MP),  # mp (-5.475  col & -2.220 res)
        (+2.220, grid(dx_s - 4.500), yc_qp, Y_QP),  # qp (+5.475  col & +2.220 res)
        (+6.660, grid(dx_s + 3.000), yc_qn, Y_QN),  # qn (+12.975 col & +6.660 res)
    ):
        c.wire("metal1", [(rx, r1_y), (rx, vdd_y)], 0.56)
        c.via1(rx, r2_y)
        c.via2(rx, r2_y)
        via3(c, rx, r2_y)
        c.wire("metal4", [(rx, r2_y), (rx, y_tr)], 0.44)
        via3(c, rx, y_tr)
        # M3 drain column from yc_start up to r2_y, then M4 from r2_y to y_tr so it never crosses other M3 tracks!
        c.wire("metal3", [(x_col, yc_start), (x_col, r2_y)], 0.46)
        via3(c, x_col, r2_y)
        c.wire("metal4", [(x_col, r2_y), (x_col, y_tr)], 0.44)
        via3(c, x_col, y_tr)

    for d_key, y_tr in (
        ("M_dp", Y_QN),
        ("M_dn", Y_QP),
        ("S_dp", Y_MP),
        ("S_dn", Y_MN),
    ):
        px, dgy = data_pins[d_key]
        c.wire("metal2", [(px, dgy), (px, y_tr)], 0.34)
        c.via2(px, y_tr)

    c.wire("metal3", [(grid(dx_m + 4.500), Y_MP), (data_pins["S_dp"][0], Y_MP)], 0.42)
    c.wire("metal3", [(grid(dx_m - 3.000), Y_MN), (data_pins["S_dn"][0], Y_MN)], 0.42)
    c.wire("metal3", [(data_pins["M_dn"][0], Y_QP), (+side_x, Y_QP)], 0.44)
    c.wire("metal3", [(data_pins["M_dp"][0], Y_QN), (+side_x, Y_QN)], 0.44)

    c.port("clkp", "metal3", *clk_in_pts["clkp"])
    c.port("clkn", "metal3", *clk_in_pts["clkn"])
    c.port("qp", "metal3", +side_x, Y_QP)
    c.port("qn", "metal3", +side_x, Y_QN)
    c.port("mp", "metal3", -2.220, Y_MP)
    c.port("mn", "metal3", -6.660, Y_MN)
    c.port("vbias", "metal3", -side_x, Y_VBIAS)
    c.port("vbias_logic", "metal3", -side_x, Y_VBLOGIC)
    c.port("vdd", "metal1", 0.000, vdd_y)
    c.port("vss", "metal1", 0.000, ground_y)
    c.write(w / f"{cell}.mag")

    latch_sub = (out / f"pll_cml_latch_h{whold}_pdk" / f"pll_cml_latch_h{whold}_pdk_ref.spice").read_text()
    ref = latch_sub + "\n" + "\n".join([
        f".subckt {cell} clkp clkn qp qn mp mn vbias vbias_logic vdd vss",
        "Xfp vdd clkp ckp vss sky130_fd_pr__nfet_01v8_lvt w=80 l=0.15",
        "Xfn vdd clkn ckn vss sky130_fd_pr__nfet_01v8_lvt w=80 l=0.15",
        "Xsp ckp vbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.5",
        "Xsn ckn vbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.5",
        f"Xmaster qn qp mp mn ckp ckn vbias_logic vdd vss pll_cml_latch_h{whold}_pdk",
        f"Xslave mp mn qp qn ckn ckp vbias_logic vdd vss pll_cml_latch_h{whold}_pdk",
        f".ends {cell}",
        "",
    ])
    res = run_signoff(w, cell, ref)
    dpins = {
        "clkp": clk_in_pts["clkp"],
        "clkn": clk_in_pts["clkn"],
        "qp": (+side_x, Y_QP),
        "qn": (+side_x, Y_QN),
        "vbias": (-side_x, Y_VBIAS),
        "vbias_logic": (-side_x, Y_VBLOGIC),
        "vdd_y": vdd_y,
        "ground_y": ground_y,
        "side_x": side_x,
        "dx_wing_L": dx_wing_L,
        "dx_wing_R": dx_wing_R,
    }
    return res, c, dpins


# ---------------------------------------------------------------------------
# 1. pll_frontend_dummy_load_pdk (Center-Symmetric Dual-Wing matching div2!)
# ---------------------------------------------------------------------------
def build_dummy_load(out: Path, pcache: Path) -> tuple[dict, Cell, dict]:
    cell = "pll_frontend_dummy_load_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    sf = prepare_mos_prim(pcache, "sf80_lvt", "sky130_fd_pr__nfet_01v8_lvt", dict(w=5.0, l=0.15, nf=16, conn_gates=1))
    cap = prepare_mos_prim(pcache, "cap64_lvt", "sky130_fd_pr__nfet_01v8_lvt", dict(w=4.0, l=0.15, nf=16, conn_gates=1))
    sink = prepare_mos_prim(pcache, "sink4_n", "sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.50, nf=1, conn_gates=1))

    c = Cell()
    cols = (-4.410, +4.410)
    sink_cols = (-2.600, +2.600)
    side_x = 9.80
    y_vss = -3.600
    dy_sink = 0.000
    dy_cap = 5.570
    dy_sf = 11.640
    y_vdd = 16.000

    for y_gr in (-2.785, 2.785, 8.355, 14.925):
        c.rect("psubdiffcont", -3.00, grid(y_gr - 0.085), +3.00, grid(y_gr + 0.085))
        c.rect("locali", -3.00, grid(y_gr - 0.085), +3.00, grid(y_gr + 0.085))

    c.wire("metal1", [(-side_x, y_vss), (side_x, y_vss)], 0.80)
    c.wire("metal1", [(-side_x, y_vss), (-side_x, 14.925)], 0.60)
    c.wire("metal1", [(side_x, y_vss), (side_x, 14.925)], 0.60)
    c.wire("metal1", [(-side_x, y_vdd), (side_x, y_vdd)], 0.80)

    for y_gr in (2.785, 8.355, 14.925):
        for bx, tx in ((-7.50, -side_x), (+7.50, +side_x)):
            c.pad("viali", bx, y_gr, 0.17)
            c.pad("metal1", bx, y_gr, 0.32)
            c.wire("metal1", [(bx, y_gr), (tx, y_gr)], 0.34)

    y_vbias = -2.275
    ck_drn_pts = {}
    for dx, nm, mir in ((sink_cols[0], "ckp", False), (sink_cols[1], "ckn", True)):
        c.include(sink, dx=dx, dy=dy_sink, mirror_x=mir)
        d_xs, s_xs, d_y, s_y = strap_mos_split(c, sink, dx, dy_sink, mir)
        c.wire("metal2", [(s_xs[0], s_y), (s_xs[0], y_vss)], 0.36)
        c.via1(s_xs[0], y_vss)
        c.via2(d_xs[0], d_y)
        ck_drn_pts[nm] = (d_xs[0], d_y)
    c.wire("metal1", [(-8.90, y_vbias), (+2.60, y_vbias)], 0.22)
    c.via1(-8.90, y_vbias)
    c.via2(-8.90, y_vbias)
    c.pad("metal3", -8.90, y_vbias, 0.54)

    cgy = grid(dy_cap - 2.275)
    for dx, nm, mir in ((cols[0], "ckp", False), (cols[1], "ckn", True)):
        c.include(cap, dx=dx, dy=dy_cap, mirror_x=mir)
        d_xs, s_xs, cd_y, cs_y = strap_mos_split(c, cap, dx, dy_cap, mir)
        x_vss_edge = -side_x if dx < 0 else +side_x
        for y_bar in (cd_y, cs_y):
            c.wire("metal2", [(min(*s_xs, x_vss_edge), y_bar), (max(*s_xs, x_vss_edge), y_bar)], 0.36)
            c.via1(x_vss_edge, y_bar)
        gx_out = grid(dx + (-3.60 if dx < 0 else +3.60))
        px_ck = -8.90 if dx < 0 else +8.90
        c.wire("metal1", [(gx_out, cgy), (px_ck, cgy)], 0.22)
        c.via1(px_ck, cgy)
        c.via2(px_ck, cgy)

    clk_pts = {}
    sf_gy = grid(dy_sf - 2.775)
    for dx, nm, ck_nm, mir in ((cols[0], "clkp", "ckp", False), (cols[1], "clkn", "ckn", True)):
        c.include(sf, dx=dx, dy=dy_sf, mirror_x=mir)
        d_xs, s_xs, d_y, s_y = strap_mos_split(c, sf, dx, dy_sf, mir)
        c.wire("metal2", [(dx, d_y), (dx, y_vdd)], 0.50)
        c.via1(dx, y_vdd)
        x_ck, y_sk_d = ck_drn_pts[ck_nm]
        px_ck = -8.90 if dx < 0 else +8.90
        c.via2(x_ck, s_y)
        c.wire("metal3", [(x_ck, y_sk_d), (x_ck, s_y)], 0.42)
        c.wire("metal3", [(px_ck, cgy), (x_ck, cgy)], 0.40)
        gx_out = grid(dx + (-3.60 if dx < 0 else +3.60))
        c.wire("metal1", [(gx_out, sf_gy), (px_ck, sf_gy)], 0.22)
        c.via1(px_ck, sf_gy)
        c.via2(px_ck, sf_gy)
        c.pad("metal3", px_ck, sf_gy, 0.56)
        clk_pts[nm] = (px_ck, sf_gy)

    c.via1(0.0, y_vdd)
    c.via2(0.0, y_vdd)
    c.pad("metal3", 0.0, y_vdd, 0.60)
    c.via1(0.0, y_vss)
    c.via2(0.0, y_vss)
    c.pad("metal3", 0.0, y_vss, 0.60)

    c.port("clkp", "metal3", *clk_pts["clkp"])
    c.port("clkn", "metal3", *clk_pts["clkn"])
    c.port("vbias", "metal3", -8.90, y_vbias)
    c.port("vdd", "metal3", 0.0, y_vdd)
    c.port("vss", "metal3", 0.0, y_vss)
    c.write(w / f"{cell}.mag")

    ref = "\n".join([
        f".subckt {cell} clkp clkn vbias vdd vss",
        "Xfp vdd clkp ckp vss sky130_fd_pr__nfet_01v8_lvt w=80 l=0.15",
        "Xfn vdd clkn ckn vss sky130_fd_pr__nfet_01v8_lvt w=80 l=0.15",
        "Xsp ckp vbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.5",
        "Xsn ckn vbias vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.5",
        "Xcp vss ckp vss vss sky130_fd_pr__nfet_01v8_lvt w=64 l=0.15",
        "Xcn vss ckn vss vss sky130_fd_pr__nfet_01v8_lvt w=64 l=0.15",
        f".ends {cell}",
        "",
    ])
    res = run_signoff(w, cell, ref)
    return res, c, {"clkp": clk_pts["clkp"], "clkn": clk_pts["clkn"], "vbias": (-8.90, y_vbias), "vdd": (0.0, y_vdd), "vss": (0.0, y_vss)}


# ---------------------------------------------------------------------------
# 2. pll_cml_tail_bias_pdk (Plan J2: Center-Symmetric Dual-Wing Tail Bias!
#    - Left Wing:  Xpd (w=60, l=0.50, nf=10 at dy=26.20) + Xsink (w=3.333, l=0.50 at dy=18.71)
#    - Right Wing: Xpm (w=60, l=0.50, nf=10 at dy=26.20) + Xref  (w=20, l=0.50 at dy=18.71)
#    - Nests 100% into Stage 1 (X2)'s Left & Right Upper Wings!)
# ---------------------------------------------------------------------------
def build_tail_bias(out: Path, pcache: Path) -> tuple[dict, Cell, dict]:
    cell = "pll_cml_tail_bias_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    sink = prepare_mos_prim(pcache, "sink333_n_sym", "sky130_fd_pr__nfet_01v8", dict(w=3.335, l=0.50, nf=1, conn_gates=1))
    # Shift sink's top & bottom guard rings (+-2.455 -> +-2.785) AND extend vertical legs to +-2.785!
    for lyr in ("pwell", "psubdiff", "psubdiffcont", "locali"):
        new_rects = []
        for x0, y0, x1, y1 in sink.rects.get(lyr, []):
            ny0 = grid(y0 - 0.330) if y0 < -2.00 else (grid(y0 + 0.330) if y0 > +2.00 else y0)
            ny1 = grid(y1 - 0.330) if y1 < -2.00 else (grid(y1 + 0.330) if y1 > +2.00 else y1)
            new_rects.append((x0, ny0, x1, ny1))
        if lyr in sink.rects:
            sink.rects[lyr] = new_rects

    nref = prepare_mos_prim(pcache, "nref5_n", "sky130_fd_pr__nfet_01v8", dict(w=4.0, l=0.50, nf=5, conn_gates=1))
    pmir10 = prepare_mos_prim(pcache, "pmir10_p", "sky130_fd_pr__pfet_01v8", dict(w=6.0, l=0.50, nf=10, conn_gates=1))

    c = Cell()
    side_x = 26.995
    ground_y = -3.100
    vdd_y = 30.900
    Y_VBLOGIC = -1.775
    Y_VBIAS = -2.550

    c.wire("metal1", [(-side_x, ground_y), (side_x, ground_y)], 0.80)
    c.wire("metal1", [(-side_x, vdd_y), (side_x, vdd_y)], 0.80)
    c.wire("metal1", [(-side_x, ground_y), (-side_x, 21.495)], 0.50)
    c.wire("metal1", [(+side_x, ground_y), (+side_x, 21.495)], 0.50)

    # Row 4 Wing Slot (dy_n = 18.710): Xsink on Left Wing (dx_sk = -22.915), Xref on Right Wing (dx_rf = +22.185)
    dy_n = 18.710
    dx_sk = -22.915
    dx_rf = +22.185
    c.include(sink, dx=dx_sk, dy=dy_n, mirror_x=False)
    c.include(nref, dx=dx_rf, dy=dy_n, mirror_x=False)

    for y_gr in (15.925, 21.495):
        for bx, tx in ((dx_sk, -side_x), (dx_rf, +side_x)):
            c.pad("viali", bx, y_gr, 0.17)
            c.pad("metal1", bx, y_gr, 0.32)
            c.wire("metal1", [(min(bx, tx), y_gr), (max(bx, tx), y_gr)], 0.34)

    sk_d, sk_s, sk_dy, sk_sy = strap_mos_split(c, sink, dx_sk, dy_n, False)
    c.wire("metal2", [(sk_s[0], sk_sy), (-side_x, sk_sy)], 0.36)
    c.via1(-side_x, sk_sy)

    rf_d, rf_s, rf_dy, rf_sy = strap_mos_split(c, nref, dx_rf, dy_n, False)
    c.wire("metal2", [(rf_s[0], rf_sy), (+side_x, rf_sy)], 0.36)
    c.via1(+side_x, rf_sy)

    # Connect Xsink gate (sk_gy = 16.765) to x_vbsf = -24.500, lift to M4 and drop to Y_VBIAS = -2.550!
    sk_gy = grid(dy_n - 1.945)  # +16.765
    x_vbsf = -24.500
    c.wire("metal1", [(x_vbsf, sk_gy), (dx_sk, sk_gy)], 0.22)
    c.via1(x_vbsf, sk_gy)
    c.via2(x_vbsf, sk_gy)
    via3(c, x_vbsf, sk_gy)
    c.wire("metal4", [(x_vbsf, sk_gy), (x_vbsf, Y_VBIAS)], 0.44)
    via3(c, x_vbsf, Y_VBIAS)
    c.wire("metal3", [(-side_x, Y_VBIAS), (grid(x_vbsf + 0.50), Y_VBIAS)], 0.42)

    # Connect Xref gate (rf_gy = 16.435) to Xref drain (rf_dy = 20.230) at x_rf_g = +19.100 (left of rf_s[0]=+19.845),
    # and drop on M4 at x_vbl = +24.500 to Y_VBLOGIC = -1.775!
    rf_gy = grid(dy_n - 2.275)  # +16.435
    x_rf_g = +19.100
    c.wire("metal1", [(x_rf_g, rf_gy), (grid(dx_rf - 1.580), rf_gy)], 0.22)
    c.via1(x_rf_g, rf_gy)
    c.wire("metal2", [(x_rf_g, rf_gy), (x_rf_g, rf_dy), (rf_d[-1], rf_dy)], 0.36)
    x_vbl = +24.500
    c.wire("metal2", [(rf_d[-1], rf_dy), (x_vbl, rf_dy)], 0.36)
    c.via2(x_vbl, rf_dy)
    via3(c, x_vbl, rf_dy)
    c.wire("metal4", [(x_vbl, rf_dy), (x_vbl, Y_VBLOGIC)], 0.44)
    via3(c, x_vbl, Y_VBLOGIC)
    c.wire("metal3", [(grid(x_vbl - 0.50), Y_VBLOGIC), (+side_x, Y_VBLOGIC)], 0.42)

    # Row 5 Wing Slot (dy_p = 26.200): Symmetric PMOS Current Mirror!
    # Left Wing: Xpd (dx_pd = -21.200), Right Wing: Xpm (dx_pm = +21.200)
    dy_p = 26.200
    dx_pd = -21.200
    dx_pm = +21.200
    pgy = grid(dy_p - 3.320)    # +22.880
    by_p = grid(dy_p + 3.830)   # +30.030

    for dx_p, sgn_p in ((dx_pd, -1.0), (dx_pm, +1.0)):
        mir_p = (sgn_p > 0)
        c.include(pmir10, dx=dx_p, dy=dy_p, mirror_x=mir_p)
        drns, srcs, d_y, s_y = strap_mos_split(c, pmir10, dx_p, dy_p, mir_p)
        # Connect sources (s_y = 23.680) outward to x_vdd_p = dx_p + sgn_p*4.600 (-25.800 / +25.800) and up to vdd_y!
        x_vdd_p = grid(dx_p + sgn_p * 4.600)
        c.wire("metal2", [(min(*srcs, x_vdd_p), s_y), (max(*srcs, x_vdd_p), s_y)], 0.36)
        c.wire("metal2", [(x_vdd_p, s_y), (x_vdd_p, vdd_y)], 0.40)
        c.via1(x_vdd_p, vdd_y)
        # Connect top nwell tap (by_p = 30.030) to vdd_y = 30.900 on M1!
        for bx_off in (-2.50, +2.50):
            bx = grid(dx_p + bx_off)
            c.pad("viali", bx, by_p, 0.17)
            c.pad("metal1", bx, by_p, 0.32)
            c.wire("metal1", [(bx, by_p), (bx, vdd_y)], 0.34)

    # Connect Xpd drain (d_y = 28.720) at x_pd_col = -18.500 (100% clear of div2's M2 VDD at -16.600!)
    # on M3 down to Xpd gate (pgy = 22.880) and Xsink drain (sk_dy = 20.230)!
    x_pd_col = -18.500
    c.via2(x_pd_col, 28.720)
    c.via1(x_pd_col, pgy)
    c.via2(x_pd_col, pgy)
    c.wire("metal2", [(sk_d[0], sk_dy), (x_pd_col, sk_dy)], 0.36)
    c.via2(x_pd_col, sk_dy)
    c.wire("metal3", [(x_pd_col, sk_dy), (x_pd_col, 28.720)], 0.42)

    # Connect Xpm drain (d_y = 28.720) at x_pm_col = +23.500 (right on Xpm drain bar & Xref drain bar!)
    # on M4 down to Xref drain (rf_dy = 20.230), flying over s_y (M2) and Y_QP/Y_QN (M3)!
    x_pm_col = +23.500
    c.via2(x_pm_col, 28.720)
    via3(c, x_pm_col, 28.720)
    c.via2(x_pm_col, rf_dy)
    via3(c, x_pm_col, rf_dy)
    c.wire("metal4", [(x_pm_col, rf_dy), (x_pm_col, 28.720)], 0.44)

    # Bridge pdiode from Left Wing (x_pd_col = -18.500) to Xpm gate on Right Wing (x_pm_g = +18.200) on M4 at y_pd_m4 = 21.600!
    y_pd_m4 = 21.600
    x_pm_g = +18.200
    c.via1(x_pm_g, pgy)
    c.wire("metal2", [(x_pm_g, y_pd_m4), (x_pm_g, pgy)], 0.34)
    via3(c, x_pd_col, y_pd_m4)
    c.via2(x_pm_g, y_pd_m4)
    via3(c, x_pm_g, y_pd_m4)
    c.wire("metal4", [(x_pd_col, y_pd_m4), (x_pm_g, y_pd_m4)], 0.44)

    c.port("vbias_sf", "metal3", -side_x, Y_VBIAS)
    c.port("vbias_logic", "metal3", +side_x, Y_VBLOGIC)
    c.port("vdd", "metal1", 0.000, vdd_y)
    c.port("vss", "metal1", 0.000, ground_y)
    c.write(w / f"{cell}.mag")

    ref = "\n".join([
        f".subckt {cell} vbias_sf vbias_logic vdd vss",
        "Xsink pdiode vbias_sf vss vss sky130_fd_pr__nfet_01v8 w=3.333333333 l=0.5",
        "Xpd pdiode pdiode vdd vdd sky130_fd_pr__pfet_01v8 w=60 l=0.5",
        "Xpm vbias_logic pdiode vdd vdd sky130_fd_pr__pfet_01v8 w=60 l=0.5",
        "Xref vbias_logic vbias_logic vss vss sky130_fd_pr__nfet_01v8 w=20 l=0.5",
        f".ends {cell}",
        "",
    ])
    res = run_signoff(w, cell, ref)
    return res, c, {
        "vbias_sf": (-side_x, Y_VBIAS),
        "vbias_logic": (+side_x, Y_VBLOGIC),
        "vdd": (0.000, vdd_y),
        "vss": (0.000, ground_y),
        "side_x": side_x,
        "vdd_y": vdd_y,
        "ground_y": ground_y,
    }


# ---------------------------------------------------------------------------
# 7. pll_div_buffer_pdk (Plan J2: Center-Symmetric Dual-Wing + Shared Dummy Resistor Bank!
#    - Left Wing:  Xt_L (w=6, l=0.5 at dx=-25.07, y=0) + Xp (w=24, l=0.15 at dx=-22.915, y=18.71) + Xr0 (-14.62)
#    - Right Wing: Xt_R (w=6, l=0.5 at dx=+25.07, y=0) + Xn (w=24, l=0.15 at dx=+22.915, y=18.71) + Xr1 (+14.62)
#    - Inner dummy resistors at -10.640 & +10.640 coincide 100% with div2's outer dummy resistors!)
# ---------------------------------------------------------------------------
def build_div_buffer(out: Path, pcache: Path) -> tuple[dict, Cell, dict]:
    cell = "pll_div_buffer_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    inp8 = prepare_mos_prim(pcache, "buf24_in8", "sky130_fd_pr__nfet_01v8_lvt", dict(w=3.0, l=0.15, nf=8, conn_gates=1))
    tail2 = prepare_mos_prim(pcache, "buf12_tail2", "sky130_fd_pr__nfet_01v8", dict(w=3.0, l=0.50, nf=2, conn_gates=1))
    load = pdk_device(pcache, "latch_load600", "sky130_fd_pr__res_high_po_2p85", dict(l=4.14))
    load.rects.pop("checkpaint", None)
    load_dum = build_res_dummy(load)

    c = Cell()
    side_x = 26.995
    ground_y = -3.100
    vdd_y = 30.900
    tail_y = 0.000
    inp_y = 18.710
    body_rail_y = 20.995
    load_y = 25.710
    Y_VBIAS = -2.550

    c.wire("metal1", [(-side_x, ground_y), (side_x, ground_y)], 0.80)
    c.wire("metal1", [(-side_x, vdd_y), (side_x, vdd_y)], 0.80)
    c.wire("metal1", [(-side_x, ground_y), (-side_x, 21.495)], 0.50)
    c.wire("metal1", [(+side_x, ground_y), (+side_x, 21.495)], 0.50)

    # Bottom row (y = 0.000): Symmetric split tail current source Xt_L (-25.235) & Xt_R (+25.235)
    # Inner vertical guard ring (-25.235 + 1.760 = -23.475) merges 100% with Xsp/Xsn (-21.950 - 1.525 = -23.475)!
    # Outer vertical guard ring (-25.235 - 1.760 = -26.995) merges 100% with side_x = 26.995!
    dx_tl = -25.235
    dx_tr = +25.235
    x_tail_L = -24.100
    x_tail_R = +24.100
    tgy = grid(tail_y - 1.775)  # -1.775
    tby = grid(tail_y - 2.285)  # -2.285
    for dx_t, sgn, x_tm4 in ((dx_tl, -1.0, x_tail_L), (dx_tr, +1.0, x_tail_R)):
        mir = (sgn > 0)
        c.include(tail2, dx=dx_t, dy=tail_y, mirror_x=mir)
        td_xs, ts_xs, td_y, ts_y = strap_mos_split(c, tail2, dx_t, tail_y, mir)
        # Drop inner source finger (dx_t - sgn*0.780 = -24.455 / +24.455) on M2 to ground_y
        x_s_vss = grid(dx_t - sgn * 0.780)
        c.wire("metal2", [(x_s_vss, ts_y), (x_s_vss, ground_y)], 0.36)
        c.via1(x_s_vss, ground_y)
        # Tie bottom guard ring outward at bx_t = dx_t + sgn*0.900 (-26.135 / +26.135) to +-side_x
        bx_t = grid(dx_t + sgn * 0.900)
        c.pad("viali", bx_t, tby, 0.17)
        c.pad("metal1", bx_t, tby, 0.32)
        c.wire("metal1", [(min(bx_t, sgn * side_x), tby), (max(bx_t, sgn * side_x), tby)], 0.34)
        # Gate: bridge the two gate-contact M1 pads across dx_t, via1 at (dx_t, tgy=-1.775), then M2 down to Y_VBIAS (-2.550) + via2!
        c.wire("metal1", [(grid(dx_t - 0.60), tgy), (grid(dx_t + 0.60), tgy)], 0.23)
        c.via1(dx_t, tgy)
        c.wire("metal2", [(dx_t, tgy), (dx_t, Y_VBIAS)], 0.32)
        c.via2(dx_t, Y_VBIAS)
        # Step drain (td_xs[0] = dx_t, td_y = +1.020) inward on M2 to x_tm4 (-24.100 / +24.100) and lift to M4!
        c.wire("metal2", [(min(dx_t, x_tm4), td_y), (max(dx_t, x_tm4), td_y)], 0.36)
        c.via2(x_tm4, td_y)
        via3(c, x_tm4, td_y)

    c.wire("metal3", [(-side_x, Y_VBIAS), (+side_x, Y_VBIAS)], 0.42)

    # Row 4 Wing Slot (inp_y = 18.710): Xn (inn -> outp) on Left Wing (-22.915) & Xp (inp -> outn) on Right Wing (+22.915)
    # This places outp (-14.620) on the Left Wing right next to clkp (-25.565) and outn (+14.620) on the Right Wing right next to clkn (+25.565)!
    dx_wing_L = -22.915
    dx_wing_R = +22.915
    in_gy = grid(inp_y - 1.775)  # +16.935
    in_pts = {}
    id_y = None
    is_y = None
    r2_y = grid(load_y - 3.065)  # +22.645
    r1_y = grid(load_y + 3.975)  # +29.685

    for dx_w, sgn, in_nm, rx_active, x_tm4 in (
        (dx_wing_L, -1.0, "inn", -14.620, x_tail_L),
        (dx_wing_R, +1.0, "inp", +14.620, x_tail_R),
    ):
        mir = (sgn > 0)
        c.include(inp8, dx=dx_w, dy=inp_y, mirror_x=mir)
        d_xs, s_xs, id_y, is_y = strap_mos_split(c, inp8, dx_w, inp_y, mir)

        # Tie top & bottom guard rings of inp8 (16.425, 20.995) to outer vertical M1 VSS (+-side_x)
        for y_gr in (16.425, body_rail_y):
            bx = grid(dx_w + sgn * 1.80)
            c.pad("viali", bx, y_gr, 0.17)
            c.pad("metal1", bx, y_gr, 0.32)
            c.wire("metal1", [(min(bx, sgn * side_x), y_gr), (max(bx, sgn * side_x), y_gr)], 0.34)

        # Drop M4 tail vertical at x_tm4 (-24.100 / +24.100) directly onto Xp/Xn source bar (is_y = 17.690)!
        c.via2(x_tm4, is_y)
        via3(c, x_tm4, is_y)
        c.wire("metal4", [(x_tm4, 1.020), (x_tm4, is_y)], 0.44)

        # Escape gate (in_gy = 16.935) outward to px_in = +-26.100 and lift to M3 port
        gx_out = grid(dx_w + sgn * 1.440)
        px_in = grid(sgn * 26.100)
        c.wire("metal1", [(min(gx_out, px_in), in_gy), (max(gx_out, px_in), in_gy)], 0.22)
        c.via1(px_in, in_gy)
        c.via2(px_in, in_gy)
        c.pad("metal3", px_in, in_gy, 0.54)
        in_pts[in_nm] = (px_in, in_gy)

        # Lift drain bar (id_y = 19.730) at x_out_w = dx_w - sgn*1.440 (-21.475 / +21.475) to M3,
        # go up to r2_y = 22.645, and horizontally on M3 to rx_active (-14.620 / +14.620)!
        x_out_w = grid(dx_w - sgn * 1.440)
        c.via2(x_out_w, id_y)
        c.wire("metal3", [(x_out_w, id_y), (x_out_w, r2_y), (rx_active, r2_y)], 0.44)

    # Connect left & right tail branches together on M4 at is_y = 17.690 (100% clear across the stage!)
    c.wire("metal4", [(x_tail_L, is_y), (x_tail_R, is_y)], 0.44)

    # Top Row (load_y = 25.710): Left & Right Resistor Banks!
    # Left:  [Rdum(-18.600) | Xr0(-14.620) | Rdum_shared(-10.640)]
    # Right: [Rdum_shared(+10.640) | Xr1(+14.620) | Rdum(+18.600)]
    for rx_dum in (-18.600, -10.640, +10.640, +18.600):
        c.include(load_dum, dx=rx_dum, dy=load_y)
    for rx_act in (-14.620, +14.620):
        c.include(load, dx=rx_act, dy=load_y)
        c.via1(rx_act, r2_y)
        c.via2(rx_act, r2_y)
        via3(c, rx_act, r2_y)
        c.wire("metal1", [(rx_act, r1_y), (rx_act, vdd_y)], 0.56)

    c.port("inp", "metal3", *in_pts["inp"])
    c.port("inn", "metal3", *in_pts["inn"])
    c.port("outp", "metal4", -14.620, r2_y)
    c.port("outn", "metal4", +14.620, r2_y)
    c.port("vbias", "metal3", -side_x, Y_VBIAS)
    c.port("vdd", "metal1", 0.000, vdd_y)
    c.port("vss", "metal1", 0.000, ground_y)
    c.write(w / f"{cell}.mag")

    ref = "\n".join([
        f".subckt {cell} inp inn outp outn vbias vdd vss",
        "Xp outn inp tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15",
        "Xn outp inn tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=0.15",
        "Xt tail vbias vss vss sky130_fd_pr__nfet_01v8 w=12 l=0.5",
        "Xr0 vdd outn vss sky130_fd_pr__res_high_po_2p85 l=4.14",
        "Xr1 vdd outp vss sky130_fd_pr__res_high_po_2p85 l=4.14",
        f".ends {cell}",
        "",
    ])
    res = run_signoff(w, cell, ref)
    bpins = {
        "inp": in_pts["inp"],
        "inn": in_pts["inn"],
        "outp": (-14.620, r2_y),
        "outn": (+14.620, r2_y),
        "vbias": (-side_x, Y_VBIAS),
        "vdd": (0.000, vdd_y),
        "vss": (0.000, ground_y),
        "vdd_y": vdd_y,
        "ground_y": ground_y,
        "side_x": side_x,
    }
    return res, c, bpins


# ---------------------------------------------------------------------------
# 8. pll_cml_prescaler8_pdk (Plan J2: Center-Symmetric Dual-Wing Pipeline!
#    - Stage 1 (dx =   0.000): Xbias + X2 (div2_h40) co-centered at dx =   0.000!
#    - Stage 2 (dx = +53.330): Xb24  + X4 (div2_h80) co-centered at dx = +53.330!
#    - Stage 3 (dx =+106.660): Xb48  + X8 (div2_h80) co-centered at dx =+106.660!)
# ---------------------------------------------------------------------------
def build_prescaler8(
    out: Path,
    bias_c: Cell, bias_p: dict,
    div40_c: Cell, d40_p: dict,
    div80_c: Cell, d80_p: dict,
    buf_c: Cell, buf_p: dict,
) -> dict:
    cell = "pll_cml_prescaler8_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    c = Cell()
    pitch = grid(2.0 * d40_p["side_x"])  # 53.330 um!
    dx_x2 = 0.000
    dx_x4 = pitch                        # +53.330
    dx_x8 = grid(2.0 * pitch)            # +106.660

    c.include(bias_c, dx=dx_x2, dy=0.000)
    c.include(div40_c, dx=dx_x2, dy=0.000)
    c.include(buf_c, dx=dx_x4, dy=0.000)
    c.include(div80_c, dx=dx_x4, dy=0.000)
    c.include(buf_c, dx=dx_x8, dy=0.000)
    c.include(div80_c, dx=dx_x8, dy=0.000)

    vdd_y = d40_p["vdd_y"]        # +30.900
    ground_y = d40_p["ground_y"]  # -3.100
    Y_VBLOGIC = -1.775
    Y_VBIAS = -2.550
    x_left = grid(dx_x2 - d40_p["side_x"])   # -26.665
    x_right = grid(dx_x8 + d80_p["side_x"])  # +133.325

    c.wire("metal1", [(x_left, vdd_y), (x_right, vdd_y)], 0.80)
    c.wire("metal1", [(x_left, ground_y), (x_right, ground_y)], 0.80)
    c.wire("metal3", [(x_left, Y_VBIAS), (x_right, Y_VBIAS)], 0.42)
    c.wire("metal3", [(x_left, Y_VBLOGIC), (x_right, Y_VBLOGIC)], 0.42)

    # Interstage wiring between Stage k (dx_src) and Stage k+1 (dx_dst):
    for dx_src, dx_dst in ((dx_x2, dx_x4), (dx_x4, dx_x8)):
        x_q_src = grid(dx_src + d40_p["side_x"])      # right edge of Stage k (= left edge of Stage k+1!)
        y_bin = buf_p["inp"][1]                       # +16.935
        x_bin_n = grid(dx_dst + buf_p["inn"][0])      # dx_dst - 26.100 (Left Wing of Stage k+1, 0.895 um right of x_q_src!)
        x_bin_p = grid(dx_dst + buf_p["inp"][0])      # dx_dst + 26.100 (Right Wing of Stage k+1)

        # 1) qn (Y_QN = 27.800 at x_q_src) -> Buffer inn (Left Wing of Stage k+1 at x_bin_n, y = 16.935)
        c.wire("metal3", [(x_q_src, d40_p["qn"][1]), (x_bin_n, d40_p["qn"][1])], 0.44)
        c.via2(x_bin_n, d40_p["qn"][1])
        c.wire("metal2", [(x_bin_n, d40_p["qn"][1]), (x_bin_n, y_bin)], 0.34)

        # 2) qp (Y_QP = 26.700 at x_q_src on M3) -> Buffer inp (Right Wing of Stage k+1 at x_bin_p, y = 16.935)
        #    Hop qp from M3 to M4 at (x_q_src, 26.700), go up to y_qp_m4 = 28.800, across to x_bin_p, then drop on M2 to y_bin!
        y_qp_m4 = 28.800
        via3(c, x_q_src, d40_p["qp"][1])
        c.wire("metal4", [(x_q_src, d40_p["qp"][1]), (x_q_src, y_qp_m4), (x_bin_p, y_qp_m4)], 0.44)
        via3(c, x_bin_p, y_qp_m4)
        c.via2(x_bin_p, y_qp_m4)
        c.wire("metal2", [(x_bin_p, y_qp_m4), (x_bin_p, y_bin)], 0.34)

        # 3) Buffer outp (Left Wing M4 at dx_dst - 14.620, r2_y = 22.645) -> Stage k+1 clkp (Left Wing M3 at dx_dst - 25.565, y = 9.865)
        # 4) Buffer outn (Right Wing M4 at dx_dst + 14.620, r2_y = 22.645) -> Stage k+1 clkn (Right Wing M3 at dx_dst + 25.565, y = 9.865)
        #    100% mirror-symmetric local Left-Wing and Right-Wing connections at y_clk_m4 = 21.600!
        bx_op, by_op = grid(dx_dst + buf_p["outp"][0]), buf_p["outp"][1]  # dx_dst - 14.620, 22.645
        bx_on, by_on = grid(dx_dst + buf_p["outn"][0]), buf_p["outn"][1]  # dx_dst + 14.620, 22.645
        dx_cp, dy_cp = grid(dx_dst + d80_p["clkp"][0]), d80_p["clkp"][1]  # dx_dst - 25.565, 9.865
        dx_cn, dy_cn = grid(dx_dst + d80_p["clkn"][0]), d80_p["clkn"][1]  # dx_dst + 25.565, 9.865

        y_clk_m4 = 21.600
        c.wire("metal4", [(bx_op, by_op), (bx_op, y_clk_m4), (dx_cp, y_clk_m4), (dx_cp, dy_cp)], 0.44)
        via3(c, dx_cp, dy_cp)

        c.wire("metal4", [(bx_on, by_on), (bx_on, y_clk_m4), (dx_cn, y_clk_m4), (dx_cn, dy_cn)], 0.44)
        via3(c, dx_cn, dy_cn)

    c.port("clkp", "metal3", *d40_p["clkp"])
    c.port("clkn", "metal3", *d40_p["clkn"])
    c.port("q2p", "metal3", grid(dx_x2 + d40_p["qp"][0]), d40_p["qp"][1])
    c.port("q2n", "metal3", grid(dx_x2 + d40_p["qn"][0]), d40_p["qn"][1])
    c.port("q4p", "metal3", grid(dx_x4 + d80_p["qp"][0]), d80_p["qp"][1])
    c.port("q4n", "metal3", grid(dx_x4 + d80_p["qn"][0]), d80_p["qn"][1])
    c.port("q8p", "metal3", grid(dx_x8 + d80_p["qp"][0]), d80_p["qp"][1])
    c.port("q8n", "metal3", grid(dx_x8 + d80_p["qn"][0]), d80_p["qn"][1])
    c.port("vbias", "metal3", x_left, Y_VBIAS)
    c.port("vdd", "metal1", x_left, vdd_y)
    c.port("vss", "metal1", x_left, ground_y)
    c.write(w / f"{cell}.mag")

    subs = []
    for subcell in (
        "pll_cml_tail_bias_pdk",
        "pll_cml_div2_biased_h40_pdk",
        "pll_cml_div2_biased_h80_pdk",
        "pll_div_buffer_pdk",
    ):
        subs.append((out / subcell / f"{subcell}_ref.spice").read_text())
    ref = "\n".join(subs) + "\n" + "\n".join([
        f".subckt {cell} clkp clkn q2p q2n q4p q4n q8p q8n vbias vdd vss",
        "Xbias vbias vbias_logic vdd vss pll_cml_tail_bias_pdk",
        "X2 clkp clkn q2p q2n m2p m2n vbias vbias_logic vdd vss pll_cml_div2_biased_h40_pdk",
        "Xb24 q2p q2n b24p b24n vbias vdd vss pll_div_buffer_pdk",
        "X4 b24p b24n q4p q4n m4p m4n vbias vbias_logic vdd vss pll_cml_div2_biased_h80_pdk",
        "Xb48 q4p q4n b48p b48n vbias vdd vss pll_div_buffer_pdk",
        "X8 b48p b48n q8p q8n m8p m8n vbias vbias_logic vdd vss pll_cml_div2_biased_h80_pdk",
        f".ends {cell}",
        "",
    ])
    return run_signoff(w, cell, ref)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pcache = out / "_prims"
    pcache.mkdir(parents=True, exist_ok=True)

    results = []
    r_dum, _, _ = build_dummy_load(out, pcache)
    results.append(r_dum)

    r_bias, bias_c, bias_p = build_tail_bias(out, pcache)
    results.append(r_bias)

    r_l40, l40_c, l40_p = build_cml_latch_variant(out, pcache, 40)
    results.append(r_l40)

    r_l80, l80_c, l80_p = build_cml_latch_variant(out, pcache, 80)
    results.append(r_l80)

    r_d40, d40_c, d40_p = build_div2_variant(out, pcache, 40)
    results.append(r_d40)

    r_d80, d80_c, d80_p = build_div2_variant(out, pcache, 80)
    results.append(r_d80)

    r_buf, buf_c, buf_p = build_div_buffer(out, pcache)
    results.append(r_buf)

    r_pre = build_prescaler8(out, bias_c, bias_p, d40_c, d40_p, d80_c, d80_p, buf_c, buf_p)
    results.append(r_pre)

    (out / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    if args.install_dir:
        inst = args.install_dir.resolve()
        inst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out / "summary.json", inst / "summary.json")
        for r in results:
            cdir = out / r["cell"]
            for ext in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
                src = cdir / f"{r['cell']}{ext}"
                if src.exists():
                    shutil.copy2(src, inst / src.name)


if __name__ == "__main__":
    main()
