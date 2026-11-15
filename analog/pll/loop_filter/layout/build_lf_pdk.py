#!/usr/bin/env python3
"""Build 3D Under-MIM SKY130 PDK Loop Filter (pll_loop_filter_k4_pdk).

Implements ``pll_loop_filter_k4`` from ``analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice``:
- 6x3 18-unit ``sky130_fd_pr__cap_mim_m3_1`` (w=22.1965, l=22.1965) array with
  1D common-centroid [VDD, VSS, VDD, VDD, VSS, VDD] bottom-plate split (12 to VDD,
  6 to VSS) and unified top-plate M4 integrator node ``z``.
- ``Xrz`` (res_high_po_0p69, l=7.59 um) and ``Xfast`` LVT transmission gate placed
  strictly beneath Column 1's VSS-grounded M3 bottom plate so ``ctrl`` picks up
  zero parasitic coupling to VDD.
- ``Xinv`` and ``Xint`` LVT transmission gate placed 3D-stacked beneath the MIM
  array using strict HV M1/M2 routing (zero M3/M4 inside the MIM footprint).
- Explicit zero-volt sense probe ``Vlink cp_in ctrl 0`` merged into ``ctrl`` per
  ``docs/layout/pll_r6.md``.
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
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402

MIM_MODEL = "sky130_fd_pr__cap_mim_m3_1"


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def clean_prim(work: Path, name: str, model: str, params: dict) -> Cell:
    p = pdk_device(work, name, model, params)
    p.rects.pop("checkpaint", None)
    return p


def draw_mim_6x3(work: Path) -> tuple[Cell, list[tuple[float, float]], list[tuple[float, float]], tuple[float, float, float, float]]:
    name = "mim_6x3_raw"
    mag = work / f"{name}.mag"
    mu.new_cell(mag)
    tcl = work / f"{name}.tcl"
    tcl.write_text(
        f"drc off\nload {name}\nbox values 0 0 0 0\n"
        f"set p [dict merge [sky130::{MIM_MODEL}_defaults] "
        f"[dict create w 22.1965 l 22.1965 nx 6 ny 3 stack 0]]\n"
        f"sky130::{MIM_MODEL}_draw $p\nsave {name}\nquit -noprompt\n"
    )
    res = mu.run_magic(tcl, work)
    (work / f"{name}.log").write_text(res.log)
    res.need(name)
    mc = Cell.read(mag)
    mc.rects.pop("checkpaint", None)
    top = sorted((x, y) for _, x, y, lbl in mc.labels if lbl.startswith("C1"))
    bot = sorted((x, y) for _, x, y, lbl in mc.labels if lbl.startswith("C2"))
    mc.labels.clear()
    assert len(top) == 6 and len(bot) == 6
    return mc, top, bot, mc.bbox()


def place_w2_mos(
    c: Cell,
    prim: Cell,
    cut_layer: str,
    dx: float,
    dy: float,
    is_pmos: bool,
    body_rail_y: float,
) -> dict:
    """Place w=2.0 um MOSFET, strap S/D onto local M2 combs, escape G left on M1, tie B on M1."""
    c.include(prim, dx=dx, dy=dy)
    sds = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})
    s_xs = sds[::2]
    d_xs = sds[1::2]
    if is_pmos:
        # Put source comb ABOVE (facing vdd rail) and drain comb BELOW (facing channel)
        s_y_pin, d_y_pin = grid(dy + 0.46), grid(dy - 0.46)
        s_bus_y, d_bus_y = grid(dy + 2.40), grid(dy - 2.40)
        by = grid(dy + abs(prim.pins("B")[0][1]))
    else:
        s_y_pin, d_y_pin = grid(dy - 0.46), grid(dy + 0.46)
        s_bus_y, d_bus_y = grid(dy - 2.40), grid(dy + 2.40)
        by = grid(dy - abs(prim.pins("B")[0][1]))

    for sx in s_xs:
        c.via1(sx, s_y_pin)
        c.wire("metal2", [(sx, s_y_pin), (sx, s_bus_y)], 0.26)
    for sx in d_xs:
        c.via1(sx, d_y_pin)
        c.wire("metal2", [(sx, d_y_pin), (sx, d_bus_y)], 0.26)
    if len(s_xs) > 1:
        c.wire("metal2", [(s_xs[0], s_bus_y), (s_xs[-1], s_bus_y)], 0.32)
    if len(d_xs) > 1:
        c.wire("metal2", [(d_xs[0], d_bus_y), (d_xs[-1], d_bus_y)], 0.32)

    gy = grid(dy + prim.pins("G")[0][1])
    gx0 = grid(dx + min(p[0] for p in prim.pins("G")))
    gx_esc = grid(sds[0] - 0.90)
    c.wire("metal1", [(gx_esc, gy), (gx0, gy)], 0.20)
    c.via1(gx_esc, gy)

    c.pad("viali", dx, by, 0.17)
    c.pad("metal1", dx, by, 0.32)
    c.wire("metal1", [(dx, by), (dx, body_rail_y)], 0.30)

    return {
        "s_xs": s_xs,
        "d_xs": d_xs,
        "s_bus_y": s_bus_y,
        "d_bus_y": d_bus_y,
        "g_pt": (gx_esc, gy),
    }


def build_lf_k4(out: Path) -> dict:
    cell = "pll_loop_filter_k4_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    mim_c, top_tabs, bot_tabs, mbbox = draw_mim_6x3(w)
    rz = clean_prim(w, "rz_pdk", "sky130_fd_pr__res_high_po_0p69", dict(l=7.59))
    n2 = clean_prim(w, "n2_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=2, conn_gates=1))
    n4 = clean_prim(w, "n4_pdk", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1))
    p4 = clean_prim(w, "p4_pdk", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.15, nf=4, conn_gates=1))
    pl4 = clean_prim(w, "pl4_pdk", "sky130_fd_pr__pfet_01v8_lvt", dict(w=2.0, l=0.35, nf=4, conn_gates=1))
    pl8 = clean_prim(w, "pl8_pdk", "sky130_fd_pr__pfet_01v8_lvt", dict(w=2.0, l=0.35, nf=8, conn_gates=1))

    c = Cell()
    c.include(mim_c)

    # 1. MIM array top plate (z on M4) and [V, G, V, V, G, V] bottom plates (vdd & vss on M3)
    upper_z = grid(mbbox[3] + 2.00)     # +37.70
    lower_vdd = grid(mbbox[1] - 2.00)   # -37.70
    lower_vss = grid(mbbox[1] - 4.00)   # -39.70

    for x, y in top_tabs:
        c.rect("metal4", grid(x - 0.50), y, grid(x + 0.50), grid(upper_z + 0.50))
    c.rect("metal4", grid(top_tabs[0][0] - 0.60), grid(upper_z - 0.50),
           grid(top_tabs[-1][0] + 0.60), grid(upper_z + 0.50))

    vdd_cols = (0, 2, 3, 5)
    vss_cols = (1, 4)
    for idx in vdd_cols:
        x, y = bot_tabs[idx]
        c.rect("metal4", grid(x - 0.26), grid(lower_vdd - 0.26), grid(x + 0.26), y)
        c.rect("metal3", grid(x - 0.26), grid(lower_vdd - 0.26), grid(x + 0.26), grid(lower_vdd + 0.26))
        c.rect("via3", grid(x - 0.16), grid(lower_vdd - 0.16), grid(x + 0.16), grid(lower_vdd + 0.16))
    x_vdd_m2 = -76.50
    c.rect("metal3", grid(x_vdd_m2 - 0.40), grid(lower_vdd - 0.50),
           grid(bot_tabs[5][0] + 0.60), grid(lower_vdd + 0.50))

    for idx in vss_cols:
        x, y = bot_tabs[idx]
        c.rect("metal4", grid(x - 0.26), grid(lower_vss - 0.26), grid(x + 0.26), y)
        c.rect("metal3", grid(x - 0.26), grid(lower_vss - 0.26), grid(x + 0.26), grid(lower_vss + 0.26))
        c.rect("via3", grid(x - 0.16), grid(lower_vss - 0.16), grid(x + 0.16), grid(lower_vss + 0.16))
    x_vss_m2 = -78.50
    c.rect("metal3", grid(x_vss_m2 - 0.40), grid(lower_vss - 0.50),
           grid(bot_tabs[4][0] + 0.60), grid(lower_vss + 0.50))

    # 2. Under-MIM active placement (strict HV: M1 horizontal, M2 vertical)
    y_rz_vss_m1 = -28.00
    y_nmos_vss_m1 = -3.00
    y_preen_m1 = 6.50
    y_preb_m1 = 7.50
    y_preref_m1 = 8.50
    y_ctrl_m1 = 9.50
    y_z_m1 = 10.50
    y_pmos_vdd_m1 = 21.00

    # Xrz under Column 1 VSS bottom plate (x = -38.62)
    dx_rz, dy_rz = -38.62, -18.00
    c.include(rz, dx=dx_rz, dy=dy_rz)
    rz_by = grid(dy_rz + rz.pins("B")[0][1])
    c.pad("viali", dx_rz, rz_by, 0.17)
    c.pad("metal1", dx_rz, rz_by, 0.34)
    c.wire("metal1", [(dx_rz, rz_by), (dx_rz, y_rz_vss_m1)], 0.34)
    c.wire("metal1", [(x_vss_m2, y_rz_vss_m1), (dx_rz, y_rz_vss_m1)], 0.48)
    c.via1(x_vss_m2, y_rz_vss_m1)

    y_rz_r2 = grid(dy_rz - 4.80)   # ctrl end (-22.80)
    y_rz_r1 = grid(dy_rz + 4.80)   # z end (-13.20)
    c.via1(dx_rz, y_rz_r2)
    c.via1(dx_rz, y_rz_r1)

    # NMOS row at dy = +2.00, PMOS row at dy = +16.00
    dy_n, dy_p = 2.00, 16.00
    dx_fast, dx_inv, dx_int = -43.00, -28.00, -12.00

    fn = place_w2_mos(c, n2, "ndiffc", dx_fast, dy_n, False, y_nmos_vss_m1)
    fp = place_w2_mos(c, pl4, "pdiffc", dx_fast, dy_p, True, y_pmos_vdd_m1)
    in_n = place_w2_mos(c, n2, "ndiffc", dx_inv, dy_n, False, y_nmos_vss_m1)
    in_p = place_w2_mos(c, p4, "pdiffc", dx_inv, dy_p, True, y_pmos_vdd_m1)
    it_n = place_w2_mos(c, n4, "ndiffc", dx_int, dy_n, False, y_nmos_vss_m1)
    it_p = place_w2_mos(c, pl8, "pdiffc", dx_int, dy_p, True, y_pmos_vdd_m1)

    # VSS & VDD M1 rails -> left M2 trunks -> lower_vss / lower_vdd M3 rails
    c.wire("metal1", [(x_vss_m2, y_nmos_vss_m1), (dx_int, y_nmos_vss_m1)], 0.48)
    c.via1(x_vss_m2, y_nmos_vss_m1)
    c.wire("metal2", [(x_vss_m2, lower_vss), (x_vss_m2, y_nmos_vss_m1)], 0.60)
    c.via2(x_vss_m2, lower_vss)

    c.wire("metal1", [(x_vdd_m2, y_pmos_vdd_m1), (dx_int, y_pmos_vdd_m1)], 0.48)
    c.via1(x_vdd_m2, y_pmos_vdd_m1)
    c.wire("metal2", [(x_vdd_m2, lower_vdd), (x_vdd_m2, y_pmos_vdd_m1)], 0.60)
    c.via2(x_vdd_m2, lower_vdd)

    # Xinv wiring: Xn.S -> vss, Xp.S -> vdd, Xn.G & Xp.G -> pre_en, Xn.D & Xp.D -> pre_b
    c.wire("metal2", [(in_n["s_xs"][0], in_n["s_bus_y"]), (in_n["s_xs"][0], y_nmos_vss_m1)], 0.30)
    c.via1(in_n["s_xs"][0], y_nmos_vss_m1)

    c.wire("metal2", [(in_p["s_xs"][0], in_p["s_bus_y"]), (in_p["s_xs"][0], y_pmos_vdd_m1)], 0.30)
    c.via1(in_p["s_xs"][0], y_pmos_vdd_m1)

    c.wire("metal2", [(dx_inv, in_n["d_bus_y"]), (dx_inv, in_p["d_bus_y"])], 0.32)
    c.via1(dx_inv, y_preb_m1)

    # Gate connections to pre_en (y=6.50) and pre_b (y=7.50)
    for gpt in (fn["g_pt"], in_n["g_pt"], in_p["g_pt"], it_n["g_pt"]):
        c.wire("metal2", [gpt, (gpt[0], y_preen_m1)], 0.28)
        c.via1(gpt[0], y_preen_m1)
    for gpt in (fp["g_pt"], it_p["g_pt"]):
        c.wire("metal2", [gpt, (gpt[0], y_preb_m1)], 0.28)
        c.via1(gpt[0], y_preb_m1)

    x_sig_port = -77.50
    c.wire("metal1", [(x_sig_port, y_preen_m1), (it_n["g_pt"][0], y_preen_m1)], 0.36)
    c.via1(x_sig_port, y_preen_m1)
    c.via2(x_sig_port, y_preen_m1)
    c.pad("metal3", x_sig_port, y_preen_m1, 0.52)

    c.wire("metal1", [(fp["g_pt"][0], y_preb_m1), (it_p["g_pt"][0], y_preb_m1)], 0.34)

    # Xfast t-gate: node b = ctrl (at dx_fast), node a = pre_ref (at x_fast_ref = -39.20)
    c.wire("metal2", [(dx_fast, fn["d_bus_y"]), (dx_fast, fp["d_bus_y"])], 0.34)
    c.via1(dx_fast, y_ctrl_m1)
    x_ctrl_riser = -46.50
    c.wire("metal1", [(x_ctrl_riser, y_ctrl_m1), (dx_fast, y_ctrl_m1)], 0.36)
    c.via1(x_ctrl_riser, y_ctrl_m1)
    y_ctrl_port = -42.00
    c.wire("metal2", [(x_ctrl_riser, y_ctrl_m1), (x_ctrl_riser, y_rz_r2), (dx_rz, y_rz_r2), (dx_rz, y_ctrl_port)], 0.40)
    c.via2(dx_rz, y_ctrl_port)
    c.pad("metal3", dx_rz, y_ctrl_port, 0.52)

    x_fast_ref = -39.20
    c.wire("metal2", [(fn["s_xs"][-1], fn["s_bus_y"]), (x_fast_ref, fn["s_bus_y"]),
                      (x_fast_ref, fp["s_bus_y"]), (fp["s_xs"][-1], fp["s_bus_y"])], 0.32)
    c.via1(x_fast_ref, y_preref_m1)

    # Xint t-gate: node b = z (at dx_int), node a = pre_ref (at x_int_ref = -7.60)
    c.wire("metal2", [(dx_int, it_n["d_bus_y"]), (dx_int, it_p["d_bus_y"])], 0.36)
    c.via1(dx_int, y_z_m1)
    x_rz_z_riser = -34.50
    x_z_top_riser = -5.00
    c.wire("metal1", [(x_rz_z_riser, y_z_m1), (x_z_top_riser, y_z_m1)], 0.40)
    c.via1(x_rz_z_riser, y_z_m1)
    c.wire("metal2", [(dx_rz, y_rz_r1), (x_rz_z_riser, y_rz_r1), (x_rz_z_riser, y_z_m1)], 0.38)
    c.via1(x_z_top_riser, y_z_m1)
    c.wire("metal2", [(x_z_top_riser, y_z_m1), (x_z_top_riser, upper_z)], 0.50)
    c.via2(x_z_top_riser, upper_z)
    via3(c, x_z_top_riser, upper_z)

    x_int_ref = -7.60
    c.wire("metal2", [(it_n["s_xs"][-1], it_n["s_bus_y"]), (x_int_ref, it_n["s_bus_y"]),
                      (x_int_ref, it_p["s_bus_y"]), (it_p["s_xs"][-1], it_p["s_bus_y"])], 0.34)
    c.via1(x_int_ref, y_preref_m1)
    c.wire("metal1", [(x_sig_port, y_preref_m1), (x_int_ref, y_preref_m1)], 0.40)
    c.via1(x_sig_port, y_preref_m1)
    c.via2(x_sig_port, y_preref_m1)
    c.pad("metal3", x_sig_port, y_preref_m1, 0.52)

    # Export exact port order: ctrl z pre_ref pre_en vdd vss
    c.port("ctrl", "metal3", dx_rz, y_ctrl_port)
    c.port("z", "metal4", top_tabs[0][0], upper_z)
    c.port("pre_ref", "metal3", x_sig_port, y_preref_m1)
    c.port("pre_en", "metal3", x_sig_port, y_preen_m1)
    c.port("vdd", "metal3", bot_tabs[0][0], lower_vdd)
    c.port("vss", "metal3", bot_tabs[1][0], lower_vss)
    c.write(w / f"{cell}.mag")
    # Add MASKHINTS_RPM (1.28 um wide >= 1.27 um rpm.1) around the 0.69 um Xrz body
    rx1, ry1 = round((dx_rz - 0.64) * 200), round((dy_rz - 6.08) * 200)
    rx2, ry2 = round((dx_rz + 0.64) * 200), round((dy_rz + 6.08) * 200)
    mag_txt = (w / f"{cell}.mag").read_text()
    mag_txt = mag_txt.replace("<< end >>", f"<< properties >>\nstring MASKHINTS_RPM {rx1} {ry1} {rx2} {ry2}\n<< end >>")
    (w / f"{cell}.mag").write_text(mag_txt)

    # Reference SPICE from design parameters (Vlink cp_in ctrl 0 merged into ctrl;
    # explicit numeric W/L so Netgen checks exact transistor widths without ignoring ngspice params:)
    ref_lines = [
        "* Physical LVS reference for pll_loop_filter_k4 (Vlink cp_in ctrl 0 merged into ctrl)",
        f".subckt {cell} ctrl z pre_ref pre_en vdd vss",
        "Xrz ctrl z vss sky130_fd_pr__res_high_po_0p69 l=7.594",
    ]
    for i in range(6):
        ref_lines.append(f"Xcg{i:02d} z vss sky130_fd_pr__cap_mim_m3_1 w=22.1965 l=22.1965")
    for i in range(12):
        ref_lines.append(f"Xcv{i:02d} z vdd sky130_fd_pr__cap_mim_m3_1 w=22.1965 l=22.1965")
    ref_lines += [
        "Xinv_n pre_b pre_en vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xinv_p pre_b pre_en vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15",
        "Xfast_n pre_ref pre_en ctrl vss sky130_fd_pr__nfet_01v8 w=4 l=0.15",
        "Xfast_p pre_ref pre_b ctrl vdd sky130_fd_pr__pfet_01v8_lvt w=8 l=0.35",
        "Xint_n pre_ref pre_en z vss sky130_fd_pr__nfet_01v8 w=8 l=0.15",
        "Xint_p pre_ref pre_b z vdd sky130_fd_pr__pfet_01v8_lvt w=16 l=0.35",
        f".ends {cell}",
        "",
    ]
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text("\n".join(ref_lines))

    proc = subprocess.run(
        [sys.executable, str(REPO / "verification/layout/check.py"),
         str(w), cell, "--ref", str(ref_path)],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    log = proc.stdout + proc.stderr
    (w / "check.log").write_text(log)
    if proc.returncode != 0:
        raise RuntimeError(f"{cell} failed checks:\n{log}")

    lvs_spice = (w / f"{cell}_lvs.spice").read_text()
    mims = re.findall(rf"^X\S+ (\S+) (\S+) {MIM_MODEL} l=([\d.]+) w=([\d.]+)$", lvs_spice, re.M)
    cnt_vss = sum(1 for a, b, _, _ in mims if {a, b} == {"z", "vss"})
    cnt_vdd = sum(1 for a, b, _, _ in mims if {a, b} == {"z", "vdd"})
    if len(mims) != 18 or cnt_vss != 6 or cnt_vdd != 12:
        raise ValueError(f"Expected 18 MIM units (6 VSS + 12 VDD), got total={len(mims)} vss={cnt_vss} vdd={cnt_vdd}")

    subprocess.run(
        [sys.executable, str(REPO / "verification/layout/plot_mag.py"),
         str(w / f"{cell}.mag"), str(w / f"{cell}.png")],
        cwd=REPO, check=True, capture_output=True,
    )
    drc_m = re.search(r"^DRC_TOTAL (\d+)", log, re.M)
    ports_m = re.search(r"^LVS_EXPORTED_PORTS (.+)$", log, re.M)
    models = dict(Counter(re.findall(r"^X[^\n]*?\b(sky130_fd_pr__\w+)\b", lvs_spice, re.M)))
    bx1, by1, bx2, by2 = Cell.read(w / f"{cell}.mag").bbox()
    return {
        "cell": cell,
        "checker_exit": proc.returncode,
        "drc_boxes": int(drc_m[1]) if drc_m else None,
        "lvs_match": "LVS_MATCH True" in log,
        "lvs_property_errors": "LVS_PROPERTY_ERRORS True" in log,
        "exported_ports": ports_m[1].split() if ports_m else [],
        "mim_units": {"total": len(mims), "z_vss": cnt_vss, "z_vdd": cnt_vdd},
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

    r = build_lf_k4(out)
    print(
        f"{r['cell']:28s} | DRC={r['drc_boxes']} | LVS={r['lvs_match']} | "
        f"PROP_ERR={r['lvs_property_errors']} | ports={len(r['exported_ports'])} | size={r['size_um']} um",
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
