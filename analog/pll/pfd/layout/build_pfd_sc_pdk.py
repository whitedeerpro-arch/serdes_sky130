#!/usr/bin/env python3
"""Build symmetric SKY130 HD standard-cell PFD layout (pll_pfd_sc_dly_pdk).

Implements ``pll_pfd_sc_dly`` from ``analog/pll/pfd/spice/pfd_sc.spice`` using
real physical ``sky130_fd_sc_hd`` standard-cell Magic layouts arranged in two
flipped, center-VDD-abutted rows with strict HV (M2 vertical, M3 horizontal)
non-crossing routing and exact UP/DN symmetry across y = 2.72 um.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell  # noqa: E402

PDK_ROOT = Path(os.environ.get("PDK_ROOT", "/home/host/.volare"))
SC_MAG_DIR = PDK_ROOT / "sky130A/libs.ref/sky130_fd_sc_hd/mag"
SC_SPICE = PDK_ROOT / "sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
PFD_SPICE = REPO / "analog/pll/pfd/spice/pfd_sc.spice"

SITE_W = 0.46
ROW_H = 2.72
CELL_SITES = {
    "tapvpwrvgnd_1": 1,
    "nand2_1": 3,
    "inv_1": 3,
    "and2_1": 5,
    "inv_4": 5,
    "dlygate4sd1_1": 7,
    "inv_8": 9,
    "dfrtp_1": 20,
}


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def load_sc(name: str) -> Cell:
    c = Cell.read(SC_MAG_DIR / f"sky130_fd_sc_hd__{name}.mag")
    c.rects.pop("comment", None)
    c.rects.pop("checkpaint", None)
    c.labels.clear()
    return c


def li_to_m1(c: Cell, x: float, y: float) -> tuple[float, float]:
    gx, gy = grid(x), grid(y)
    c.pad("viali", gx, gy, 0.17)
    c.pad("metal1", gx, gy, 0.32)
    return gx, gy


def li_to_m2(c: Cell, x: float, y: float) -> tuple[float, float]:
    gx, gy = li_to_m1(c, x, y)
    c.pad("via1", gx, gy, 0.26)
    c.pad("metal2", gx, gy, 0.40)
    return gx, gy


def extract_sc_subckts(names: list[str]) -> str:
    txt = SC_SPICE.read_text()
    blocks = []
    for nm in names:
        full = f"sky130_fd_sc_hd__{nm}"
        m = re.search(rf"(^\.subckt\s+{re.escape(full)}\b.*?^\.ends\b[^\n]*)", txt, re.M | re.S)
        if not m:
            raise ValueError(f"Missing {full} in {SC_SPICE}")
        blocks.append(m[1])
    return "\n\n".join(blocks)


def build_pfd_sc_dly(out: Path) -> dict:
    cell = "pll_pfd_sc_dly_pdk"
    w = out / cell
    w.mkdir(parents=True, exist_ok=True)

    lib = {nm: load_sc(nm) for nm in CELL_SITES}
    c = Cell()

    # Row 0 (bottom, y = 0 .. 2.72): 50 sites = 23.00 um
    row0 = [
        ("tap0", "tapvpwrvgnd_1"),
        ("Xup", "dfrtp_1"),
        ("Xub1", "inv_4"),
        ("Xub2", "inv_8"),
        ("tap1", "tapvpwrvgnd_1"),
        ("tap1b", "tapvpwrvgnd_1"),
        ("tap1c", "tapvpwrvgnd_1"),
        ("Xdetect", "nand2_1"),
        ("tap2", "tapvpwrvgnd_1"),
        ("Xd1", "inv_1"),
        ("tap3", "tapvpwrvgnd_1"),
        ("Xd2", "inv_1"),
        ("tap4", "tapvpwrvgnd_1"),
    ]
    # Row 1 (top, mirror_y around y=2.72 -> dy=5.44): 50 sites = 23.00 um
    row1 = [
        ("tap6", "tapvpwrvgnd_1"),
        ("Xdn", "dfrtp_1"),
        ("Xdb1", "inv_4"),
        ("Xdb2", "inv_8"),
        ("tap7", "tapvpwrvgnd_1"),
        ("Xd3", "dlygate4sd1_1"),
        ("tap8", "tapvpwrvgnd_1"),
        ("Xclear", "and2_1"),
        ("tap9", "tapvpwrvgnd_1"),
    ]

    x_pos0, cur = {}, 0.0
    for inst, kind in row0:
        x_pos0[inst] = grid(cur)
        c.include(lib[kind], dx=grid(cur), dy=0.0, mirror_y=False)
        cur = grid(cur + CELL_SITES[kind] * SITE_W)
    total_w0 = cur

    x_pos1, cur = {}, 0.0
    for inst, kind in row1:
        x_pos1[inst] = grid(cur)
        c.include(lib[kind], dx=grid(cur), dy=grid(2 * ROW_H), mirror_y=True)
        cur = grid(cur + CELL_SITES[kind] * SITE_W)
    total_w1 = cur
    assert abs(total_w0 - total_w1) < 1e-6, f"Row width mismatch: {total_w0} vs {total_w1}"

    y_top = grid(2 * ROW_H)  # 5.44 um

    # Continuous power rails: VGND at y=0.0 and y=5.44, shared VPWR at y=2.72
    c.wire("metal1", [(0.0, 0.0), (total_w0, 0.0)], 0.48)
    c.wire("metal1", [(0.0, ROW_H), (total_w0, ROW_H)], 0.48)
    c.wire("metal1", [(0.0, y_top), (total_w0, y_top)], 0.48)

    # Tie both VGND rails on left M2 strap outside active signals
    x_vss_rail = -1.20
    c.via1(0.16, 0.0)
    c.via1(0.16, y_top)
    c.wire("metal2", [(x_vss_rail, 0.0), (0.16, 0.0)], 0.48)
    c.wire("metal2", [(x_vss_rail, y_top), (0.16, y_top)], 0.48)
    c.wire("metal2", [(x_vss_rail, 0.0), (x_vss_rail, y_top)], 0.50)

    # 1. Tie D = vdd inside Xup and Xdn via vertical M1 tab (>=0.075 um X overlap on viali!)
    x_d = grid(x_pos0["Xup"] + 1.52)
    c.pad("viali", x_d, 2.25, 0.17)
    c.rect("metal1", grid(x_d - 0.16), 2.13, grid(x_d + 0.16), ROW_H)
    c.pad("viali", x_d, grid(y_top - 2.25), 0.17)
    c.rect("metal1", grid(x_d - 0.16), ROW_H, grid(x_d + 0.16), grid(y_top - 2.13))

    # 2. Clock inputs ref (Row 0 Xup.CLK) and fb (Row 1 Xdn.CLK), symmetric across y=2.72
    W_M23 = 0.40
    W_M1 = 0.32
    ref_pt = li_to_m2(c, x_pos0["Xup"] + 0.235, 1.53)
    fb_pt = li_to_m2(c, x_pos1["Xdn"] + 0.235, y_top - 1.53)
    x_in_port = -0.45
    c.wire("metal2", [(x_in_port, ref_pt[1]), ref_pt], W_M23)
    c.wire("metal2", [(x_in_port, fb_pt[1]), fb_pt], W_M23)

    # 3. Symmetric UP & DN chains: qu -> Xub1 -> ub -> Xub2 -> up; qd -> Xdb1 -> db -> Xdb2 -> dn
    qu_pt = li_to_m2(c, x_pos0["Xup"] + 8.965, 1.53)
    ub1_a = li_to_m2(c, x_pos0["Xub1"] + 0.690, 1.19)
    c.wire("metal2", [qu_pt, (qu_pt[0], ub1_a[1]), ub1_a], W_M23)

    qd_pt = li_to_m2(c, x_pos1["Xdn"] + 8.965, y_top - 1.53)
    db1_a = li_to_m2(c, x_pos1["Xdb1"] + 0.690, y_top - 1.19)
    c.wire("metal2", [qd_pt, (qd_pt[0], db1_a[1]), db1_a], W_M23)

    ub1_y = li_to_m2(c, x_pos0["Xub1"] + 2.070, 1.19)
    ub2_a = li_to_m2(c, x_pos0["Xub2"] + 1.150, 1.19)
    c.wire("metal2", [ub1_y, ub2_a], W_M23)

    db1_y = li_to_m2(c, x_pos1["Xdb1"] + 2.070, y_top - 1.19)
    db2_a = li_to_m2(c, x_pos1["Xdb2"] + 1.150, y_top - 1.19)
    c.wire("metal2", [db1_y, db2_a], W_M23)

    # Strict HV M3 horizontal tracks (all uniform width 0.40 um, 100% inside the 2 rows y in [0, 5.44]!):
    #   y = +0.50 : qu      (Row 0 lower M3 track)
    #   y = +1.19 : up      (Row 0 middle M3 track)
    #   y = +1.96 : rd2     (Row 0 upper M3 track)
    #   y = +2.72 : clear_b (Center M3 track)
    #   y = +3.48 : rst_b   (Row 1 lower M3 track, mirror of +1.96)
    #   y = +4.25 : dn      (Row 1 middle M3 track, mirror of +1.19)
    #   y = +4.94 : qd      (Row 1 upper M3 track, mirror of +0.50)
    ub2_y = li_to_m2(c, x_pos0["Xub2"] + 3.910, 1.19)
    db2_y = li_to_m2(c, x_pos1["Xdb2"] + 3.910, y_top - 1.19)
    x_out_port = grid(total_w0 + 0.60)
    c.via2(*ub2_y)
    c.wire("metal3", [ub2_y, (x_out_port, ub2_y[1])], W_M23)
    c.via2(*db2_y)
    c.wire("metal3", [db2_y, (x_out_port, db2_y[1])], W_M23)

    # 4. qu -> Xdetect.A (via M2 vertical + M3 y=+0.50) & qd -> Xdetect.B (via M2 vertical + M3 y=+4.94)
    det_a = li_to_m2(c, x_pos0["Xdetect"] + 1.145, 1.19)
    det_b = li_to_m2(c, x_pos0["Xdetect"] + 0.225, 1.19)

    y_qu_m3 = 0.45
    c.wire("metal2", [ub1_a, (ub1_a[0], y_qu_m3)], W_M23)
    c.via2(ub1_a[0], y_qu_m3)
    c.via2(det_a[0], y_qu_m3)
    c.wire("metal3", [(ub1_a[0], y_qu_m3), (det_a[0], y_qu_m3)], W_M23)
    c.wire("metal2", [(det_a[0], y_qu_m3), det_a], W_M23)

    y_qd_m3 = grid(y_top - 0.45)  # 4.99
    c.wire("metal2", [db1_a, (db1_a[0], y_qd_m3)], W_M23)
    c.via2(db1_a[0], y_qd_m3)
    c.via2(det_b[0], y_qd_m3)
    c.wire("metal3", [(db1_a[0], y_qd_m3), (det_b[0], y_qd_m3)], W_M23)
    c.wire("metal2", [det_b, (det_b[0], y_qd_m3)], W_M23)

    # 5. Reset delay chain:
    #    - Xdetect.Y -> Xd1.A and Xd1.Y -> Xd2.A routed directly inside Row 0 on M1
    #    - Xd2.Y -> Xd3.A on uniform 0.40 um M2/M3 at y = 1.96
    #    - Xd3.X -> Xclear.B routed directly inside Row 1 on M1
    det_y = li_to_m1(c, x_pos0["Xdetect"] + 0.685, 0.68)
    d1_a = li_to_m1(c, x_pos0["Xd1"] + 0.445, 1.19)
    c.wire("metal1", [det_y, (d1_a[0], det_y[1]), d1_a], W_M1)

    d1_y = li_to_m1(c, x_pos0["Xd1"] + 0.905, 1.19)
    d2_a = li_to_m1(c, x_pos0["Xd2"] + 0.445, 1.19)
    c.wire("metal1", [d1_y, d2_a], W_M1)

    # Xd2.Y (1.53) -> M2 up to 1.96 -> M3 left to d3_a[0] -> M2 up to Xd3.A (3.91)
    d2_y = li_to_m2(c, x_pos0["Xd2"] + 0.905, 1.53)
    d3_a = li_to_m2(c, x_pos1["Xd3"] + 0.225, y_top - 1.53)
    y_rd2_m3 = 1.96
    c.wire("metal2", [d2_y, (d2_y[0], y_rd2_m3)], W_M23)
    c.via2(d2_y[0], y_rd2_m3)
    c.via2(d3_a[0], y_rd2_m3)
    c.wire("metal3", [(d3_a[0], y_rd2_m3), (d2_y[0], y_rd2_m3)], W_M23)
    c.wire("metal2", [(d3_a[0], y_rd2_m3), d3_a], W_M23)

    d3_x = li_to_m1(c, x_pos1["Xd3"] + 2.550, y_top - 0.68)
    clr_b = li_to_m1(c, x_pos1["Xclear"] + 1.150, y_top - 1.19)
    c.wire("metal1", [d3_x, (clr_b[0], d3_x[1]), clr_b], W_M1)

    # rst_b enters from left on M3 at y = 3.48 (mirror of 1.96!), goes up on M2 to Xclear.A (4.25)
    clr_a = li_to_m2(c, x_pos1["Xclear"] + 0.230, y_top - 1.19)
    y_rstb_m3 = grid(y_top - 1.96)  # 3.48
    c.wire("metal2", [(clr_a[0], y_rstb_m3), clr_a], W_M23)
    c.via2(clr_a[0], y_rstb_m3)
    c.wire("metal3", [(x_in_port, y_rstb_m3), (clr_a[0], y_rstb_m3)], W_M23)

    # 6. Zero-skew midpoint-fed clear_b on M3 at y = 2.72 -> vertical M2 to Xup.RESET_B & Xdn.RESET_B
    clr_x = li_to_m2(c, x_pos1["Xclear"] + 2.070, y_top - 1.53)
    x_rst_tap = grid(x_pos0["Xup"] + 5.20)
    y_rst_up = 0.72
    y_rst_dn = grid(y_top - 0.72)
    c.via1(x_rst_tap, y_rst_up)
    c.pad("metal2", x_rst_tap, y_rst_up, W_M23)
    c.via1(x_rst_tap, y_rst_dn)
    c.pad("metal2", x_rst_tap, y_rst_dn, W_M23)
    c.wire("metal2", [(x_rst_tap, y_rst_up), (x_rst_tap, y_rst_dn)], W_M23)
    c.wire("metal2", [(clr_x[0], ROW_H), clr_x], W_M23)
    c.via2(x_rst_tap, ROW_H)
    c.via2(clr_x[0], ROW_H)
    c.wire("metal3", [(x_rst_tap, ROW_H), (clr_x[0], ROW_H)], W_M23)

    # Export exact port order: ref fb rst_b up dn vdd vss
    c.port("ref", "metal2", x_in_port, ref_pt[1])
    c.port("fb", "metal2", x_in_port, fb_pt[1])
    c.port("rst_b", "metal3", x_in_port, y_rstb_m3)
    c.port("up", "metal3", x_out_port, ub2_y[1])
    c.port("dn", "metal3", x_out_port, db2_y[1])
    c.port("vdd", "metal1", 0.20, ROW_H)
    c.port("vss", "metal2", x_vss_rail, ROW_H)
    c.write(w / f"{cell}.mag")

    sc_defs = extract_sc_subckts(["dfrtp_1", "nand2_1", "inv_1", "dlygate4sd1_1", "and2_1", "inv_4", "inv_8"])
    pfd_src = PFD_SPICE.read_text()
    m_pfd = re.search(r"(^\.subckt\s+pll_pfd_sc_dly\b.*?^\.ends\s+pll_pfd_sc_dly\b)", pfd_src, re.M | re.S)
    assert m_pfd is not None
    pfd_sub = re.sub(r"\bpll_pfd_sc_dly\b", cell, m_pfd[1])
    ref_path = w / f"{cell}_ref.spice"
    ref_path.write_text(f"* Standard-cell library + design-side pfd_sc.spice\n{sc_defs}\n\n{pfd_sub}\n")

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
    return {
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--install-dir", type=Path, default=None)
    args = ap.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)

    r = build_pfd_sc_dly(out)
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
