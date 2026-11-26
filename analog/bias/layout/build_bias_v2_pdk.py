#!/usr/bin/env python3
"""Build and verify the BIAS v2 SKY130 PDK layout suite (7 clean cells + integrated macro).

Cells generated into ``analog/bias/layout/variants/v2_pdk/``:
  1. ``serdes_bias_ctle_v2_pdk``  : 4-finger LVT NMOS diode + 2 outer dummies in P+ guard ring
  2. ``serdes_bias_cp_v2_pdk``    : Shared-diffusion [D,DN,MN,MN,DN,D] NMOS + [D,4xDP,D] PMOS (<=110 um^2)
  3. ``serdes_bias_cml_v2_pdk``   : 5/0.5 NMOS diode tucked directly under 2x1 stacked MIM1+MIM2 5 pF (<=1800 um^2)
  4. ``serdes_ref_vbuf_v2_pdk``   : Compact guarded OTA + 8-bar calibrated high_po Xr + outer dummies
  5. ``serdes_ref_pbuf_v2_pdk``   : 100% real transistors (4->16 CMOS decoder + 16-tap string + 16 tgates + LVT OTA)
  6. ``serdes_bias_ref_v2_pdk``   : Folded-cascode bandgap + V->I ref + stacked MIM1+MIM2 (<=15,500 um^2)
  7. ``serdes_bias_top_v2_pdk``   : Unified perimeter-pinned integrated macro with internal vgi & pcopy bank (<=27,000 um^2)

Rules enforced:
  - ZERO ``cd`` commands inside Magic Tcl scripts (uses subprocess cwd).
  - Always ``-dnull -noconsole`` + ``quit -noprompt`` + Python timeout.
  - Full-rule DRC == 0, Netgen LVS == MATCH (0 property errors, 0 disconnected nodes, exact ports).
  - Clean install directory: ONLY .mag, .png, _ref.spice, _lvs.spice, _pex.spice, _rcx.spice (if clean),
    summary.json, README.md (ZERO .log, .ext, .tcl files inside analog/**/layout/).
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
import time

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "verification/layout"))
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402

PNP_MAG = Path("/home/host/.volare/sky130A/libs.ref/sky130_fd_pr/mag/sky130_fd_pr__rf_pnp_05v5_W3p40L3p40.mag")
PLOT_MAG = REPO / "verification/layout/plot_mag.py"
MIM1 = "sky130_fd_pr__cap_mim_m3_1"
MIM2 = "sky130_fd_pr__cap_mim_m3_2"


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def via3(c: Cell, x: float, y: float) -> None:
    c.pad("metal3", x, y, 0.50)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.50)


def via4(c: Cell, x: float, y: float) -> None:
    c.pad("metal4", x, y, 1.50)
    c.pad("via4", x, y, 1.18)
    c.pad("metal5", x, y, 1.50)


def via3_array(c: Cell, x0: float, y0: float, nx: int, ny: int, pitch: float = 0.72) -> None:
    """Place an nx x ny array of via3 (M3-M4) centered at (x0, y0) with solid M3/M4 backing plates."""
    hx = grid(((nx - 1) * pitch + 0.50) / 2.0)
    hy = grid(((ny - 1) * pitch + 0.50) / 2.0)
    c.rect("metal3", grid(x0 - hx), grid(y0 - hy), grid(x0 + hx), grid(y0 + hy))
    c.rect("metal4", grid(x0 - hx), grid(y0 - hy), grid(x0 + hx), grid(y0 + hy))
    for ix in range(nx):
        for iy in range(ny):
            px = grid(x0 + (ix - (nx - 1) / 2.0) * pitch)
            py = grid(y0 + (iy - (ny - 1) / 2.0) * pitch)
            via3(c, px, py)


def via4_array(c: Cell, x0: float, y0: float, nx: int, ny: int, pitch: float = 2.00) -> None:
    """Place an nx x ny array of via4 (M4-M5) centered at (x0, y0)."""
    for ix in range(nx):
        for iy in range(ny):
            px = grid(x0 + (ix - (nx - 1) / 2.0) * pitch)
            py = grid(y0 + (iy - (ny - 1) / 2.0) * pitch)
            via4(c, px, py)


def clean_primitive(work: Path, name: str, model: str, params: dict) -> Cell:
    pmag = work / f"{name}.mag"
    prim = Cell.read(pmag) if pmag.exists() else pdk_device(work, name, model, params)
    prim.rects.pop("checkpaint", None)
    return prim


def sd_xs_of(prim: Cell, cut_layer: str, dx: float = 0.0) -> list[float]:
    return sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects[cut_layer]})


def gate_pts_of(prim: Cell, dx: float = 0.0, dy: float = 0.0) -> list[tuple[float, float]]:
    pts = [(grid(x + dx), grid(y + dy)) for _, x, y, nm in prim.labels if nm.startswith("G")]
    return sorted(pts, key=lambda p: (p[0], p[1]))


def draw_m1_guard_ring(c: Cell, x1: float, y1: float, x2: float, y2: float, w: float = 0.70) -> None:
    """Closed 1.8V P+ substrate guard ring (pwell + psubdiff + locali + M1, M2-transparent)."""
    pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    c.wire("pwell", pts, w + 0.56)
    for lay in ("psubdiff", "locali", "metal1"):
        c.wire(lay, pts, w)
    cw = 0.18
    c.rect("psubdiffcont", x1 + 0.25, y1 - cw / 2, x2 - 0.25, y1 + cw / 2)
    c.rect("psubdiffcont", x1 + 0.25, y2 - cw / 2, x2 - 0.25, y2 + cw / 2)
    c.rect("psubdiffcont", x1 - cw / 2, y1 + 0.25, x1 + cw / 2, y2 - 0.25)
    c.rect("psubdiffcont", x2 - cw / 2, y1 + 0.25, x2 + cw / 2, y2 - 0.25)
    for y in (y1, y2):
        nx = max(2, int((x2 - x1) // 4.0))
        for i in range(nx + 1):
            c.pad("viali", grid(x1 + (x2 - x1) * i / nx), y, 0.17)
    for x in (x1, x2):
        ny = max(2, int((y2 - y1) // 4.0))
        for i in range(1, ny):
            c.pad("viali", x, grid(y1 + (y2 - y1) * i / ny), 0.17)


def run_magic_safe(tcl_text: str, work: Path, tag: str, timeout: int = 120) -> mu.MagicResult:
    """Run Magic batch safely: NEVER uses cd inside Tcl, always -dnull -noconsole + quit -noprompt."""
    assert "\ncd " not in ("\n" + tcl_text), "Forbidden cd inside Magic Tcl script"
    script = work / f"_{tag}.tcl"
    script.write_text(tcl_text)
    proc = subprocess.run(
        [mu.MAGIC, "-dnull", "-noconsole", "-rcfile", str(mu.RCFILE), str(script)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    log = proc.stdout + proc.stderr
    clean = "\n".join(l for l in log.splitlines() if "tk_version" not in l and "version_check.tcl" not in l)
    bad = re.search(r"Error parsing|no such|No such cell", clean)
    return mu.MagicResult(log=log, ok=(proc.returncode == 0 and bad is None))


def exported_ports(path: Path, cell: str) -> list[str]:
    logical = re.sub(r"\n[ \t]*\+", " ", path.read_text())
    header = re.search(rf"^\.subckt[ \t]+{re.escape(cell)}(?:[ \t]+([^\n]*))?$", logical, re.M | re.I)
    if header is None:
        return []
    ports = []
    for tok in (header[1] or "").split():
        if tok.lower() == "params:" or "=" in tok:
            break
        ports.append(tok)
    return ports


def verify_cell(work: Path, cell: str, ref_text: str, do_rcx: bool = True) -> dict:
    """Run full-rule DRC, LVS extraction + Netgen, CPEX, optional RCX, and PNG render."""
    ref_path = work / f"{cell}_ref.spice"
    ref_path.write_text(ref_text)

    # 1. Full-rule DRC (NO cd in Tcl!)
    drc_res = run_magic_safe(
        "\n".join([
            "drc off",
            f"load {cell}",
            "select top cell",
            "drc on",
            "drc style drc(full)",
            "drc check",
            "drc catchup",
            'puts "DRC_TOTAL [drc list count total]"',
            'foreach {why boxes} [drc listall why] { puts "DRC_RULE [llength $boxes] | $why" }',
            "quit -noprompt",
        ]) + "\n",
        work,
        "drc",
    )
    m = re.search(r"^DRC_TOTAL\s+(\d+)", drc_res.log, re.M)
    if m is None:
        raise RuntimeError(f"DRC failed to report total for {cell}:\n{drc_res.log[-2000:]}")
    drc_total = int(m[1])
    drc_rules = [l[len("DRC_RULE "):] for l in drc_res.log.splitlines() if l.startswith("DRC_RULE ")]

    # 2. LVS + CPEX extraction (magic-capfix, NO cd in Tcl!)
    ext_res = run_magic_safe(
        "\n".join([
            "drc off",
            f"load {cell}",
            "select top cell",
            "extract all",
            "ext2spice lvs",
            f"ext2spice -o {cell}_lvs.spice",
            "ext2spice cthresh 0",
            "ext2spice extresist off",
            f"ext2spice -o {cell}_pex.spice",
            "quit -noprompt",
        ]) + "\n",
        work,
        "ext",
    )
    ext_res.need(f"extract {cell}")

    # 3. Optional RCX extraction (extresist)
    rcx_ok = False
    if do_rcx:
        rcx_tcl = "\n".join([
            "drc off",
            f"load {cell}",
            "select top cell",
            "extract do all",
            "extract all",
            "ext2sim labels on",
            "ext2sim",
            "extresist tolerance 10",
            "extresist",
            "ext2spice lvs",
            "ext2spice cthresh 0",
            "ext2spice extresist on",
            f"ext2spice -o {cell}_rcx.spice",
            "quit -noprompt",
        ]) + "\n"
        try:
            rcx_res = run_magic_safe(rcx_tcl, work, "rcx", timeout=120)
            rcx_p = work / f"{cell}_rcx.spice"
            if rcx_res.ok and rcx_p.exists() and ".subckt" in rcx_p.read_text():
                rcx_ok = True
        except Exception:
            rcx_ok = False

    # 4. Netgen LVS (uses mu.NETGENEXEC + fixed shim with strict timeout=120 so it can never hang)
    lvs_log = work / f"{cell}_lvs.log"
    shim = work / "_netgen_local.tcl"
    shim.write_text(
        mu.NETGEN_TCL.read_text().replace(
            "load /usr/lib/netgen/tcl/tclnetgen.so",
            f"load {mu.NGC}/tcl/tclnetgen.so",
        )
    )
    ng_script = work / "_netgen_run.tcl"
    ng_script.write_text(
        f"set argv [list lvs {{{work / f'{cell}_lvs.spice'} {cell}}} {{{ref_path} {cell}}} {mu.NETGEN_SETUP} {lvs_log}]\n"
        f"source {shim}\n"
        "quit\n"
    )
    ng = subprocess.run(
        [str(mu.NETGENEXEC), str(ng_script)],
        cwd=work,
        capture_output=True,
        text=True,
        timeout=120,
    )
    lvs_txt = ng.stdout + (lvs_log.read_text() if lvs_log.exists() else "")
    lvs_match = "Circuits match uniquely" in ng.stdout
    prop_err = "Property errors were found" in ng.stdout
    disc = sorted(set(re.findall(r"disconnected node:\s*(\S+)", lvs_txt, re.I)))
    ports = exported_ports(work / f"{cell}_lvs.spice", cell)
    lvs_ok = lvs_match and not prop_err and not disc and bool(ports)

    # 5. Render PNG
    subprocess.run([sys.executable, str(PLOT_MAG), str(work / f"{cell}.mag"), str(work / f"{cell}.png")],
                   check=True, capture_output=True, text=True)

    # 6. Bbox & extracted model counts
    c_loaded = Cell.read(work / f"{cell}.mag")
    bx1, by1, bx2, by2 = c_loaded.bbox()
    w_um, h_um = round(bx2 - bx1, 3), round(by2 - by1, 3)
    area = round(w_um * h_um, 2)
    lvs_spice = (work / f"{cell}_lvs.spice").read_text()
    models = Counter(re.findall(r"\b(sky130_fd_pr__\w+)\b", lvs_spice))

    rep = dict(
        cell=cell,
        drc_boxes=drc_total,
        drc_rules=drc_rules[:8],
        lvs_match=lvs_ok,
        lvs_property_errors=prop_err,
        lvs_disconnected=disc,
        exported_ports=ports,
        bbox_um=[bx1, by1, bx2, by2],
        size_um=[w_um, h_um],
        area_um2=area,
        aspect_ratio=round(max(w_um, h_um) / min(w_um, h_um), 2),
        rcx_generated=rcx_ok,
        extracted_models=dict(models),
    )
    print(f"[{cell}] {w_um:.2f} x {h_um:.2f} um = {area:.1f} um^2 (AR={rep['aspect_ratio']}) | "
          f"DRC={drc_total} | LVS={'MATCH' if lvs_ok else 'FAIL'} | RCX={rcx_ok} | ports={ports}", flush=True)
    if drc_total:
        for r in drc_rules[:8]:
            print("  DRC:", r, flush=True)
    if not lvs_ok:
        tail = [l for l in lvs_txt.splitlines() if re.search(r"match|mismatch|Property|Error|disconnected", l, re.I)]
        print("  LVS FAIL:", "\n    ".join(tail[-12:]), flush=True)
    return rep


# =============================================================================
# 1. serdes_bias_ctle_v2_pdk (4 active fingers + 2 outer dummies in guard ring)
# =============================================================================
def build_bias_ctle_v2(root: Path) -> dict:
    cell = "serdes_bias_ctle_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)
    prim = clean_primitive(w, "ctle_nf6", "sky130_fd_pr__nfet_01v8_lvt",
                           dict(w=2.0, l=0.5, nf=6, guard=1, conn_gates=0, topc=1, botc=0, doports=1))
    c = Cell()
    c.include(prim)
    xs = sd_xs_of(prim, "ndiffc")
    gpts = gate_pts_of(prim)
    bx, by = prim.pins("B")[0]
    bx, by = grid(bx), grid(by)

    # Fingers: [0=D, 1=A, 2=A, 3=A, 4=A, 5=D]
    # sd[0,1,3,5,6] = vss; sd[2,4] = iin; g[0,5] = vss; g[1,2,3,4] = iin
    y_d = grid(0.45)
    y_s = grid(-0.55)
    y_g = gpts[0][1]
    for sx in (xs[0], xs[1], xs[3], xs[5], xs[6]):
        c.via1(sx, y_s)
    c.wire("metal2", [(xs[0], y_s), (xs[6], y_s)], 0.32)
    c.body_contact(bx, by)
    c.wire("metal2", [(bx, by), (bx, y_s)], 0.32)

    for dx in (xs[2], xs[4]):
        c.via1(dx, y_d)
    c.wire("metal2", [(xs[2], y_d), (xs[4], y_d)], 0.32)
    for gx, gy in gpts[1:5]:
        c.via1(gx, gy)
    c.wire("metal2", [(gpts[1][0], y_g), (gpts[4][0], y_g)], 0.30)
    # Connect drain bus to gate bus at gpts[2][0] (aligned with gate contact, zero met2.2!)
    c.wire("metal2", [(gpts[2][0], y_d), (gpts[2][0], y_g)], 0.30)

    # Outer dummy gates g[0], g[5] -> vss guard ring directly on M1 + viali tap (zero M2 congestion!)
    gx_l = grid(prim.bbox()[0] + 0.35)
    gx_r = grid(prim.bbox()[2] - 0.35)
    c.wire("metal1", [(gpts[0][0], y_g), (gx_l, y_g), (gx_l, 0.0)], 0.24)
    c.wire("metal1", [(gpts[5][0], y_g), (gx_r, y_g), (gx_r, 0.0)], 0.24)
    c.pad("viali", gx_l, 0.0, 0.17); c.pad("metal1", gx_l, 0.0, 0.32)
    c.pad("viali", gx_r, 0.0, 0.17); c.pad("metal1", gx_r, 0.0, 0.32)

    c.port("iin", "metal2", gpts[2][0], y_g)
    c.port("vss", "metal2", bx, by)
    c.write(w / f"{cell}.mag")

    ref = (
        "* BIAS v2 serdes_bias_ctle_v2_pdk (4 active + 2 outer shorted dummy fingers)\n"
        f".subckt {cell} iin vss\n"
        "Xd iin iin vss vss sky130_fd_pr__nfet_01v8_lvt w=8 l=0.5\n"
        "Xdum_l vss vss vss vss sky130_fd_pr__nfet_01v8_lvt w=2 l=0.5\n"
        "Xdum_r vss vss vss vss sky130_fd_pr__nfet_01v8_lvt w=2 l=0.5\n"
        f".ends {cell}\n"
    )
    return verify_cell(w, cell, ref)


# =============================================================================
# 2. serdes_bias_cp_v2_pdk (Shared-diffusion [D,DN,MN,MN,DN,D] + [D,4xDP,D], <=110 um^2)
# =============================================================================
def build_bias_cp_v2(root: Path) -> dict:
    cell = "serdes_bias_cp_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)

    # topc=1,botc=0 on NMOS & topc=0,botc=1 on PMOS puts all poly contacts in the center channel,
    # keeping bottom/top outer edges bare diff for ultra-compact P+/N+ taps (<=110 um^2)!
    nm = clean_primitive(w, "cp_n6", "sky130_fd_pr__nfet_01v8",
                         dict(w=2.5, l=1.0, nf=6, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    pm = clean_primitive(w, "cp_p6", "sky130_fd_pr__pfet_01v8",
                         dict(w=5.0, l=1.0, nf=6, guard=0, conn_gates=0, topc=0, botc=1, doports=1))
    nb = nm.bbox()
    pb = pm.bbox()

    c = Cell()
    dy_n = 0.0
    dy_p = grid(nb[3] + 0.85 - pb[1])
    c.include(nm, dx=0.0, dy=dy_n)
    c.include(pm, dx=0.0, dy=dy_p)

    nxs = sd_xs_of(nm, "ndiffc")
    ngpts = gate_pts_of(nm, 0.0, dy_n)
    pxs = sd_xs_of(pm, "pdiffc")
    pgpts = gate_pts_of(pm, 0.0, dy_p)

    # Top N+ tap bar inside PMOS Nwell (vcp)
    p_nw_y1 = min(r[1] for r in pm.rects["nwell"]) + dy_p
    p_nw_y2 = max(r[3] for r in pm.rects["nwell"]) + dy_p
    p_nw_x1 = min(r[0] for r in pm.rects["nwell"])
    p_nw_x2 = max(r[2] for r in pm.rects["nwell"])
    y_ntap = grid(p_nw_y2 + 0.35)
    c.rect("nwell", p_nw_x1, p_nw_y1, p_nw_x2, grid(y_ntap + 0.45))
    c.rect("nsubdiff", grid(p_nw_x1 + 0.30), grid(y_ntap - 0.18), grid(p_nw_x2 - 0.30), grid(y_ntap + 0.18))
    c.rect("nsubdiffcont", grid(p_nw_x1 + 0.48), grid(y_ntap - 0.085), grid(p_nw_x2 - 0.48), grid(y_ntap + 0.085))
    c.rect("locali", grid(p_nw_x1 + 0.30), grid(y_ntap - 0.18), grid(p_nw_x2 - 0.30), grid(y_ntap + 0.18))
    c.rect("metal1", grid(p_nw_x1 + 0.30), grid(y_ntap - 0.18), grid(p_nw_x2 - 0.30), grid(y_ntap + 0.18))
    for tx in (pxs[1], pxs[3], pxs[5]):
        c.pad("viali", tx, y_ntap, 0.17)
        c.via1(tx, y_ntap)

    # Bottom P+ tap bar below NMOS (vss)
    y_gbot = grid(nb[1] - 0.60)
    gx1 = grid(min(nb[0], pb[0]))
    gx2 = grid(max(nb[2], pb[2]))
    c.rect("pwell", grid(gx1 - 0.25), grid(y_gbot - 0.45), grid(gx2 + 0.25), grid(nb[3] + 0.20))
    c.rect("psubdiff", grid(gx1 + 0.10), grid(y_gbot - 0.18), grid(gx2 - 0.10), grid(y_gbot + 0.18))
    c.rect("psubdiffcont", grid(gx1 + 0.28), grid(y_gbot - 0.085), grid(gx2 - 0.28), grid(y_gbot + 0.085))
    c.rect("locali", grid(gx1 + 0.10), grid(y_gbot - 0.18), grid(gx2 - 0.10), grid(y_gbot + 0.18))
    c.rect("metal1", grid(gx1 + 0.10), grid(y_gbot - 0.18), grid(gx2 - 0.10), grid(y_gbot + 0.18))
    for tx in (nxs[0], nxs[2], nxs[4], nxs[6]):
        c.pad("viali", tx, y_gbot, 0.17)
        c.via1(tx, y_gbot)

    # NMOS [D, DN_L, MN_L, MN_R, DN_R, D]:
    # sd[0,2,4,6]=vss, sd[1,5]=vbn, sd[3]=vbp; g[0,5]=vss, g[1..4]=vbn
    y_nvss = grid(dy_n - 0.80)
    y_nvbn = grid(dy_n + 0.00)
    y_nvbp = grid(dy_n + 0.80)
    y_ng = ngpts[0][1]

    for sx in (nxs[0], nxs[2], nxs[4], nxs[6]):
        c.via1(sx, y_nvss)
        c.wire("metal2", [(sx, y_gbot), (sx, y_nvss)], 0.32)
    c.wire("metal2", [(nxs[0], y_gbot), (nxs[6], y_gbot)], 0.36)

    for gx, sx in ((ngpts[0][0], nxs[0]), (ngpts[5][0], nxs[6])):
        c.via1(gx, y_ng)
        c.wire("metal2", [(gx, y_ng), (sx, y_ng), (sx, y_nvss)], 0.30)

    c.via1(nxs[1], y_nvbn)
    c.via1(nxs[5], y_nvbn)
    c.wire("metal2", [(nxs[1], y_nvbn), (nxs[5], y_nvbn)], 0.32)
    for gx, gy in ngpts[1:5]:
        c.via1(gx, gy)
    c.wire("metal2", [(min(nxs[1], ngpts[1][0]), y_ng), (ngpts[4][0], y_ng)], 0.32)
    c.wire("metal2", [(nxs[1], y_nvbn), (nxs[1], y_ng)], 0.32)

    # vbp from NMOS sd[3] up to PMOS on M3
    c.via1(nxs[3], y_nvbp)
    c.via2(nxs[3], y_nvbp)

    # PMOS [D, DP, DP, DP, DP, D]:
    # sd[0,1,3,5,6]=vcp, sd[2,4]=vbp; g[0,5]=vcp, g[1..4]=vbp
    y_pvcp = grid(dy_p + 1.45)
    y_pvbp = grid(dy_p - 1.25)
    y_pg = pgpts[0][1]

    for sx in (pxs[0], pxs[1], pxs[3], pxs[5], pxs[6]):
        c.via1(sx, y_pvcp)
    c.wire("metal2", [(pxs[0], y_pvcp), (pxs[6], y_pvcp)], 0.36)
    for tx in (pxs[1], pxs[3], pxs[5]):
        c.wire("metal2", [(tx, y_pvcp), (tx, y_ntap)], 0.34)
    c.wire("metal2", [(pxs[1], y_ntap), (pxs[5], y_ntap)], 0.36)

    for gx, sx in ((pgpts[0][0], pxs[0]), (pgpts[5][0], pxs[6])):
        c.via1(gx, y_pg)
        c.wire("metal2", [(gx, y_pg), (sx, y_pg), (sx, y_pvcp)], 0.30)

    for dx in (pxs[2], pxs[4]):
        c.via1(dx, y_pvbp)
    c.wire("metal2", [(pxs[2], y_pvbp), (pxs[4], y_pvbp)], 0.34)
    for gx, gy in pgpts[1:5]:
        c.via1(gx, gy)
    c.wire("metal2", [(pgpts[1][0], y_pg), (pgpts[4][0], y_pg)], 0.32)
    c.via2(nxs[3], y_pvbp)
    c.via2(nxs[3], y_pg)
    c.wire("metal3", [(nxs[3], y_nvbp), (nxs[3], y_pvbp)], 0.40)
    c.wire("metal2", [(min(pxs[2], nxs[3]), y_pvbp), (max(pxs[4], nxs[3]), y_pvbp)], 0.34)
    c.wire("metal2", [(min(pgpts[1][0], nxs[3]), y_pg), (max(pgpts[4][0], nxs[3]), y_pg)], 0.32)

    c.port("vbn", "metal2", nxs[1], y_nvbn)
    c.port("vbp", "metal3", nxs[3], y_pvbp)
    c.port("vcp", "metal2", pxs[3], y_ntap)
    c.port("vss", "metal2", nxs[2], y_gbot)
    c.write(w / f"{cell}.mag")

    ref = (
        "* BIAS v2 serdes_bias_cp_v2_pdk (shared-diff [D,DN,MN,MN,DN,D] + [D,4xDP,D])\n"
        f".subckt {cell} vbn vbp vcp vss\n"
        "Xdn vbn vbn vss vss sky130_fd_pr__nfet_01v8 w=5 l=1\n"
        "Xmn vbp vbn vss vss sky130_fd_pr__nfet_01v8 w=5 l=1\n"
        "Xdum_nl vbn vss vss vss sky130_fd_pr__nfet_01v8 w=2.5 l=1\n"
        "Xdum_nr vbn vss vss vss sky130_fd_pr__nfet_01v8 w=2.5 l=1\n"
        "Xdp vbp vbp vcp vcp sky130_fd_pr__pfet_01v8 w=20 l=1\n"
        "Xdum_pl vcp vcp vcp vcp sky130_fd_pr__pfet_01v8 w=5 l=1\n"
        "Xdum_pr vcp vcp vcp vcp sky130_fd_pr__pfet_01v8 w=5 l=1\n"
        f".ends {cell}\n"
    )
    return verify_cell(w, cell, ref)


# =============================================================================
# 3. serdes_bias_cml_v2_pdk (5/0.5 diode under 2x1 stacked MIM1+MIM2 5 pF, <=1800 um^2)
# =============================================================================
def build_bias_cml_v2(root: Path) -> dict:
    cell = "serdes_bias_cml_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)

    side = 24.8
    lower = clean_primitive(w, "cml_mim1", MIM1, dict(w=side, l=side, nx=2, ny=1, stack=1, doports=1))
    upper = clean_primitive(w, "cml_mim2", MIM2, dict(w=side, l=side, nx=2, ny=1, doports=1))
    xd = clean_primitive(w, "cml_diode", "sky130_fd_pr__nfet_01v8", dict(w=5.0, l=0.5, nf=1, guard=1, conn_gates=1, doports=1))

    lp = sorted(lower.rects["mimcapcontact"], key=lambda r: (r[0], r[1]))
    up = sorted([(-r[2], r[1], -r[0], r[3]) for r in upper.rects["mimcap2contact"]], key=lambda r: (r[0], r[1]))
    dx_u = grid((lp[0][0] + lp[0][2] - up[0][0] - up[0][2]) / 2.0)
    dy_u = grid((lp[0][1] + lp[0][3] - up[0][1] - up[0][3]) / 2.0)

    c = Cell()
    c.include(lower)
    c.include(upper, dx=dx_u, dy=dy_u, mirror_x=True)

    # Tuck 5/0.5 NMOS diode directly underneath the MIM1+MIM2 array (M1/M2 only under M3 plates!)
    c.include(xd, dx=0.0, dy=0.0)
    xs = sd_xs_of(xd, "ndiffc")
    gx, gy = xd.pins("G")[0]
    bx, by = xd.pins("B")[0]
    gx, gy, bx, by = grid(gx), grid(gy), grid(bx), grid(by)
    y_d, y_s = grid(1.1), grid(-1.1)
    c.via1(xs[0], y_s); c.via1(xs[1], y_d)
    c.via1(gx, gy)
    c.wire("metal2", [(xs[1], y_d), (gx, y_d), (gx, gy)], 0.44)
    c.body_contact(bx, by)
    c.wire("metal2", [(bx, by), (bx, y_s), (xs[0], y_s)], 0.44)

    a_pts = sorted((grid(x), grid(y)) for _, x, y, nm in lower.labels if nm.startswith("C1"))
    b3_pts = sorted((grid(x), grid(y)) for _, x, y, nm in lower.labels if nm.startswith("C2"))
    b5_pts = sorted((grid(-x + dx_u), grid(y + dy_u)) for _, x, y, nm in upper.labels if nm.startswith("C1"))

    bx1, by1, bx2, by2 = c.bbox()
    # Single top routing band ONLY (no bottom rail -> saves 3 um height -> ~1,750 um^2 at exact 5.00 pF!)
    # All rails sit >= 1.75 um above MIM1/MIM2 plates (capm.11, cap2m.11, met5.2 all 0!).
    ya_m4 = grid(by2 + 1.95)   # M4 iin rail (left: x = -22 .. +14.3)
    yb_top = grid(by2 + 2.55)  # M3 + M5 vss rail (right: x = -1.9 .. +28.4) + 8 via3 + 4 via4 tie!

    # a (iin): M4 from lower C1 up to ya_m4
    for x, y in a_pts:
        c.wire("metal4", [(x, y), (x, ya_m4)], 1.20)
    c.wire("metal4", [(a_pts[0][0], ya_m4), (a_pts[-1][0], ya_m4)], 1.20)

    # b (vss): M3 from lower C2 straight UP to yb_top (clear of MIM1 plates by >= 1.75 um!)
    x_b_right = b3_pts[-1][0]
    for x, y in b3_pts:
        c.wire("metal3", [(x, y), (x, yb_top)], 1.20)
    c.wire("metal3", [(b3_pts[0][0], yb_top), (x_b_right, yb_top)], 1.40)

    # M5 from upper C1 up to yb_top (clear of C2 via4 AND met5.2 >= 1.60 um!)
    for x, y in b5_pts:
        c.wire("metal5", [(x, y), (x, yb_top)], 1.60)
    c.wire("metal5", [(b5_pts[0][0], yb_top), (x_b_right, yb_top)], 1.60)

    # 8 via3 + 4 via4 tie M3 <-> M4 <-> M5 for vss along the top-right empty strip at yb_top
    c.wire("metal4", [(grid(x_b_right - 7.5), yb_top), (x_b_right, yb_top)], 1.60)
    via4_array(c, grid(x_b_right - 3.8), yb_top, 4, 1, pitch=2.00)
    via3_array(c, grid(x_b_right - 3.8), yb_top, 8, 1, pitch=0.80)

    # Connect buried NMOS diode out on M2 to top rails (route vss RIGHT of diode -> UP -> LEFT at yb_top: zero M2 crossing!)
    x_vss_up = grid(xs[1] + 2.5)
    c.wire("metal2", [(xs[0], y_s), (x_vss_up, y_s), (x_vss_up, yb_top), (b3_pts[0][0], yb_top)], 0.50)
    for ix in range(2):
        c.via2(grid(b3_pts[0][0] + ix * 0.80), yb_top)
    c.wire("metal2", [(b3_pts[0][0], yb_top), (grid(b3_pts[0][0] + 0.80), yb_top)], 0.44)

    # iin M2 -> M3 -> M4 (8 via3!) at top-left (x = -21 .. -17, y = yb_top, >= 15 um left of b3_pts[0]!)
    x_iin_tie = grid(a_pts[0][0] - 5.2)
    c.wire("metal2", [(gx, y_d), (x_iin_tie, y_d), (x_iin_tie, yb_top)], 0.50)
    for ix in range(2):
        c.via2(grid(x_iin_tie + ix * 0.80), yb_top)
    c.wire("metal2", [(x_iin_tie, yb_top), (grid(x_iin_tie + 0.80), yb_top)], 0.44)
    c.wire("metal3", [(grid(x_iin_tie - 0.4), yb_top), (grid(x_iin_tie + 3.2), yb_top)], 1.40)
    via3_array(c, grid(x_iin_tie + 1.4), yb_top, 4, 2, pitch=0.72)
    c.wire("metal4", [(grid(x_iin_tie - 0.4), yb_top), (a_pts[0][0], yb_top)], 1.40)
    c.wire("metal4", [(a_pts[0][0], ya_m4), (a_pts[0][0], yb_top)], 1.40)

    c.port("iin", "metal4", a_pts[0][0], yb_top)
    c.port("vss", "metal3", b3_pts[0][0], yb_top)
    c.write(w / f"{cell}.mag")

    ref = (
        "* BIAS v2 serdes_bias_cml_v2_pdk (5/0.5 diode under 2x1 stacked MIM1+MIM2 5.0 pF)\n"
        f".subckt {cell} iin vss\n"
        "Xd iin iin vss vss sky130_fd_pr__nfet_01v8 w=5 l=0.5\n"
        f"Xm1_0 iin vss {MIM1} w={side} l={side}\n"
        f"Xm1_1 iin vss {MIM1} w={side} l={side}\n"
        f"Xm2_0 vss iin {MIM2} w={side} l={side}\n"
        f"Xm2_1 vss iin {MIM2} w={side} l={side}\n"
        f".ends {cell}\n"
    )
    return verify_cell(w, cell, ref)


# =============================================================================
# Reusable resistor + analog array helpers (with outer dummies!)
# =============================================================================
def strap_res_serpentine_dummies(
    c: Cell, prim: Cell, dx: float, dy: float, n_active: int
) -> dict:
    """Place guarded res_high_po_0p35 with nx = n_active + 2 (outer 2 bars = vss dummies).
    Serpentine-straps active bars 1..n_active in series; ties outer dummy bars 0 and n_active+1
    both top and bottom to the guard ring (vss).
    Returns dict with plus=(x,y), minus=(x,y), guard_left_x, guard_bot_y, bar_xs, yb, yt.
    """
    c.include(prim, dx=dx, dy=dy)
    xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects["viali"]})
    ys = sorted({grid((r[1] + r[3]) / 2.0 + dy) for r in prim.rects["viali"]})
    yb, yt = ys[0], ys[-1]
    assert len(xs) == n_active + 2, f"Expected {n_active+2} bars, got {len(xs)}"

    # Tie left/right outer dummy bars (0 and -1) top & bottom to guard ring on M1
    gl = min(prim.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    gr = max(prim.rects["psubdiffcont"], key=lambda r: r[0] + r[2])
    gb = min(prim.rects["psubdiffcont"], key=lambda r: r[1] + r[3])
    gt = max(prim.rects["psubdiffcont"], key=lambda r: r[1] + r[3])
    x_gl = grid((gl[0] + gl[2]) / 2.0 + dx)
    x_gr = grid((gr[0] + gr[2]) / 2.0 + dx)
    y_gb = grid((gb[1] + gb[3]) / 2.0 + dy)
    y_gt = grid((gt[1] + gt[3]) / 2.0 + dy)
    for x_bar, x_ring in ((xs[0], x_gl), (xs[-1], x_gr)):
        for y_end in (yb, yt):
            c.wire("metal1", [(x_bar, y_end), (x_ring, y_end)], 0.36)
            c.pad("viali", x_ring, y_end, 0.17)
            c.pad("metal1", x_ring, y_end, 0.36)

    # Serpentine-strap active bars 1..n_active
    act = xs[1:-1]
    for i in range(n_active - 1):
        yj = yb if i % 2 == 0 else yt
        c.wire("metal1", [(act[i], yj), (act[i + 1], yj)], 0.44)
    plus = (act[0], yt)
    minus = (act[-1], yt if n_active % 2 == 0 else yb)
    return dict(plus=plus, minus=minus, x_gl=x_gl, x_gr=x_gr, y_gb=y_gb, y_gt=y_gt,
                act_xs=act, yb=yb, yt=yt)


# =============================================================================
# 4. serdes_ref_vbuf_v2_pdk (Compact guarded 2D-CC OTA + 8-bar calibrated Xr + dummies)
# =============================================================================
def build_ref_vbuf_v2(root: Path) -> dict:
    cell = "serdes_ref_vbuf_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)

    # Left bay: 2D CC PMOS load [D,A,A,B,B,D]/[D,B,B,A,A,D] (w=8,l=8,nf=6,m=2),
    #           CC NMOS diff pair [D,A,A,B,B,B,B,A,A,D] (w=6,l=4,nf=10),
    #           CC NMOS tail/diode [D,BD,T,T,BD,D] (w=2,l=4,nf=6).
    pl = clean_primitive(w, "vb_pl", "sky130_fd_pr__pfet_01v8_lvt",
                         dict(w=8.0, l=8.0, nf=6, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    np_ = clean_primitive(w, "vb_np", "sky130_fd_pr__nfet_01v8",
                          dict(w=6.0, l=4.0, nf=10, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    nt = clean_primitive(w, "vb_nt", "sky130_fd_pr__nfet_01v8",
                         dict(w=2.0, l=4.0, nf=6, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    xr = clean_primitive(w, "vb_xr", "sky130_fd_pr__res_high_po_0p35",
                         dict(w=1.0, l=40.185, nx=10, m=1, guard=1))

    c = Cell()
    # Place left bay centered at x=0: nt at y=4.0, np at y=12.6, pl at y=30.0
    dy_nt = 4.2
    dy_np = 12.8
    dy_pl = 31.2
    c.include(nt, dx=0.0, dy=dy_nt)
    c.include(np_, dx=0.0, dy=dy_np)
    c.include(pl, dx=0.0, dy=dy_pl)

    # Outer guard ring around left OTA + right Xr integrated cleanly
    pl_b = pl.bbox()
    np_b = np_.bbox()
    xr_b = xr.bbox()
    x_ota_l = grid(min(pl_b[0], np_b[0]) - 2.6)
    x_ota_r = grid(max(pl_b[2], np_b[2]) + 2.6)
    dx_xr = grid(x_ota_r + 1.4 - xr_b[0])
    dy_xr = grid(23.5)

    xr_info = strap_res_serpentine_dummies(c, xr, dx_xr, dy_xr, n_active=8)

    # Single outer M1 guard ring enclosing the entire cell (merged with Xr's bottom/top!)
    gx1 = grid(x_ota_l - 0.8)
    gx2 = grid(dx_xr + xr_b[2] + 0.6)
    gy1 = grid(min(dy_nt + nt.bbox()[1] - 1.6, dy_xr + xr_b[1] - 0.8))
    gy2 = grid(max(dy_pl + pl_b[3] + 1.2, dy_xr + xr_b[3] + 0.8))
    draw_m1_guard_ring(c, gx1, gy1, gx2, gy2, w=0.80)
    # Internal horizontal P+ tap strip between nt and np_ (fixes LU.2 < 15um & catches np_ outer dummies cleanly!)
    y_ptap_mid = grid(dy_nt + nt.bbox()[3] + 1.15)
    c.rect("pwell", gx1, grid(y_ptap_mid - 0.55), x_ota_r, grid(y_ptap_mid + 0.55))
    c.rect("psubdiff", gx1, grid(y_ptap_mid - 0.28), x_ota_r, grid(y_ptap_mid + 0.28))
    c.rect("psubdiffcont", grid(gx1 + 0.3), grid(y_ptap_mid - 0.09), grid(x_ota_r - 0.3), grid(y_ptap_mid + 0.09))
    c.rect("locali", gx1, grid(y_ptap_mid - 0.25), x_ota_r, grid(y_ptap_mid + 0.25))
    c.rect("metal1", gx1, grid(y_ptap_mid - 0.30), x_ota_r, grid(y_ptap_mid + 0.30))
    for i in range(5):
        px = grid(gx1 + 4.5 + (x_ota_r - gx1 - 9.0) * i / 4.0)
        c.pad("viali", px, y_ptap_mid, 0.17)
    # Tie Xr guard ring to outer guard ring on M1
    c.wire("metal1", [(xr_info["x_gr"], dy_xr), (gx2, dy_xr)], 0.50)
    c.pad("viali", xr_info["x_gr"], dy_xr, 0.17)

    # Vertical M3 trunks in left/right channels of OTA
    x_vdd = grid(pl_b[0] - 1.2)
    x_da = grid(pl_b[0] - 2.2)
    x_out = grid(pl_b[2] + 1.2)
    x_iin = grid(pl_b[2] + 2.2)

    # 1) Strap Xla/Xlb (2x6 pfet_lvt: Row 0=[D,A,A,B,B,D], Row 1=[D,B,B,A,A,D])
    pl_xs = sd_xs_of(pl, "pdiffc")
    pl_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_pl) for r in pl.rects["pdiffc"]})
    pl_gxs = sorted({grid(x) for _, x, _, nm in pl.labels if nm.startswith("G")})
    pl_gys = sorted({grid(y + dy_pl) for _, _, y, nm in pl.labels if nm.startswith("G")})
    pbx, pby = pl.pins("B")[0]
    pbx, pby = grid(pbx), grid(pby + dy_pl)

    vdd_ys, da_ys, out_ys = [], [], []
    for r_idx, yr in enumerate(pl_ys):
        y_vdd = grid(yr + 2.0)
        y_da = grid(yr + 0.2)
        y_out = grid(yr - 1.6)
        for sx in (pl_xs[0], pl_xs[1], pl_xs[3], pl_xs[5], pl_xs[6]):
            c.via1(sx, y_vdd)
        c.wire("metal2", [(x_vdd, y_vdd), (pl_xs[6], y_vdd)], 0.44)
        c.via2(x_vdd, y_vdd)
        vdd_ys.append(y_vdd)

        da_col, out_col = (pl_xs[2], pl_xs[4]) if r_idx == 0 else (pl_xs[4], pl_xs[2])
        c.via1(da_col, y_da)
        c.wire("metal2", [(x_da, y_da), (da_col, y_da)], 0.36)
        c.via2(x_da, y_da)
        da_ys.append(y_da)

        c.via1(out_col, y_out)
        c.wire("metal2", [(out_col, y_out), (x_out, y_out)], 0.36)
        c.via2(x_out, y_out)
        out_ys.append(y_out)

        # Gates: active g[1..4] -> da on M2 at gy; dummy g[0], g[5] -> outer M1 S/D bars directly on M1 (zero M2 crossing!)
        gy = pl_gys[r_idx]
        for gx in pl_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(x_da, gy), (pl_gxs[4], gy)], 0.34)
        c.via2(x_da, gy)
        da_ys.append(gy)
        for gx, sx in ((pl_gxs[0], pl_xs[0]), (pl_gxs[5], pl_xs[6])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.30)

    c.body_contact(pbx, pby)
    y_pby_m2 = grid(pby - 0.55)  # clear of pl Row 0 gate M2 bus (met2.2=0!)
    c.wire("metal2", [(x_vdd, y_pby_m2), (pbx, y_pby_m2), (pbx, pby)], 0.36)
    c.via2(x_vdd, y_pby_m2)
    vdd_ys.append(y_pby_m2)
    c.wire("metal3", [(x_vdd, min(vdd_ys)), (x_vdd, gy2)], 0.60)

    # 2) Strap Xa/Xb (10-finger nfet: [D, A, A, B, B, B, B, A, A, D])
    np_xs = sd_xs_of(np_, "ndiffc")
    np_gpts = gate_pts_of(np_, 0.0, dy_np)
    np_gy = np_gpts[0][1]
    y_np_tail = grid(dy_np - 1.8)
    y_np_da = grid(dy_np + 0.0)
    y_np_out = grid(dy_np + 1.8)
    y_np_iin = grid(np_gy + 0.80)
    y_np_outg = grid(np_gy + 1.60)

    for tx in (np_xs[1], np_xs[3], np_xs[5], np_xs[7], np_xs[9]):
        c.via1(tx, y_np_tail)
    c.wire("metal2", [(np_xs[1], y_np_tail), (np_xs[9], y_np_tail)], 0.44)

    for ax in (np_xs[2], np_xs[8]):
        c.via1(ax, y_np_da)
    c.wire("metal2", [(x_da, y_np_da), (np_xs[8], y_np_da)], 0.36)
    c.via2(x_da, y_np_da)
    da_ys.append(y_np_da)

    for bx in (np_xs[4], np_xs[6]):
        c.via1(bx, y_np_out)
    c.wire("metal2", [(np_xs[4], y_np_out), (x_out, y_np_out)], 0.36)
    c.via2(x_out, y_np_out)
    out_ys.append(y_np_out)

    # Active gates: g[1,2,7,8] -> iin (y_np_iin); g[3,4,5,6] -> out (y_np_outg)
    for idx in (1, 2, 7, 8):
        gx = np_gpts[idx][0]
        c.via1(gx, np_gy)
        c.wire("metal2", [(gx, np_gy), (gx, y_np_iin)], 0.32)
    c.wire("metal2", [(np_gpts[1][0], y_np_iin), (x_iin, y_np_iin)], 0.36)
    c.via2(x_iin, y_np_iin)

    for idx in (3, 4, 5, 6):
        gx = np_gpts[idx][0]
        c.via1(gx, np_gy)
        c.via2(gx, np_gy)
        c.wire("metal3", [(gx, np_gy), (gx, y_np_outg)], 0.36)
        c.via2(gx, y_np_outg)
    c.wire("metal2", [(np_gpts[3][0], y_np_outg), (x_out, y_np_outg)], 0.36)
    c.via2(x_out, y_np_outg)
    out_ys.append(y_np_outg)

    # Outer dummy fingers g[0], g[9] and sd[0], sd[10] -> vss on M1 straight to P+ tap bar (zero M2 crossing!)
    for gx, sx in ((np_gpts[0][0], np_xs[0]), (np_gpts[9][0], np_xs[10])):
        c.wire("metal1", [(gx, np_gy), (sx, np_gy), (sx, y_ptap_mid)], 0.30)
        c.pad("viali", sx, y_ptap_mid, 0.17)

    # 3) Strap Xbd/Xt (6-finger nfet: [D, BD, T, T, BD, D])
    nt_xs = sd_xs_of(nt, "ndiffc")
    nt_gpts = gate_pts_of(nt, 0.0, dy_nt)
    nt_gy = nt_gpts[0][1]
    y_nt_vss = grid(dy_nt - 0.55)
    y_nt_ib = grid(dy_nt + 0.55)

    for sx in (nt_xs[0], nt_xs[2], nt_xs[4], nt_xs[6]):
        c.wire("metal1", [(sx, dy_nt), (sx, gy1)], 0.30)

    # Dummy gates g[0], g[5] -> vss on M1 directly to outer M1 S/D bars (zero M2 crossing!)
    for gx, sx in ((nt_gpts[0][0], nt_xs[0]), (nt_gpts[5][0], nt_xs[6])):
        c.wire("metal1", [(gx, nt_gy), (sx, nt_gy), (sx, gy1)], 0.30)

    # ibias: sd[1], sd[5] + active gates g[1..4] -> brought to bottom perimeter port
    c.via1(nt_xs[1], y_nt_ib); c.via1(nt_xs[5], y_nt_ib)
    c.wire("metal2", [(nt_xs[1], y_nt_ib), (nt_xs[5], y_nt_ib)], 0.34)
    for gx, gy in nt_gpts[1:5]:
        c.via1(gx, gy)
    c.wire("metal2", [(min(nt_xs[1], nt_gpts[1][0]), nt_gy), (nt_gpts[4][0], nt_gy)], 0.34)
    c.wire("metal2", [(nt_xs[1], y_nt_ib), (nt_xs[1], nt_gy)], 0.34)
    # Export ibias to left perimeter on M2 at y_nt_ib? Use M3 drop to gy1? No, bring out to x = gx1 on M2!
    c.wire("metal2", [(gx1, y_nt_ib), (nt_xs[1], y_nt_ib)], 0.40)

    # tail: nt sd[3] at y_nt_tail = dy_nt - 0.55 (clear of ibias M2 bus at y_nt_ib = dy_nt + 0.55!) -> np tail bus on M3
    y_nt_tail = grid(dy_nt - 0.55)
    c.via1(nt_xs[3], y_nt_tail); c.via2(nt_xs[3], y_nt_tail)
    c.via2(nt_xs[3], y_np_tail)
    c.wire("metal3", [(nt_xs[3], y_nt_tail), (nt_xs[3], y_np_tail)], 0.44)

    # Finish M3 vertical trunks for da, out, and iin -> Xr plus; Xr minus -> vss guard ring
    c.wire("metal3", [(x_da, min(da_ys)), (x_da, max(da_ys))], 0.44)
    c.wire("metal3", [(x_out, min(out_ys)), (x_out, gy2)], 0.50)

    # Connect Xr plus -> x_iin trunk, Xr minus -> top guard ring (vss)
    xp_p, yp_p = xr_info["plus"]
    xp_m, yp_m = xr_info["minus"]
    c.via1(xp_p, yp_p)
    c.wire("metal2", [(x_iin, yp_p), (xp_p, yp_p)], 0.40)
    c.via2(x_iin, yp_p)
    c.wire("metal3", [(x_iin, y_np_iin), (x_iin, gy2)], 0.50)

    # Xr minus (bar 8 top, since n_active=8 is even!) -> top guard ring M1 (vss)
    c.wire("metal1", [(xp_m, yp_m), (xp_m, gy2)], 0.40)

    # All 5 ports cleanly on perimeter!
    c.port("iin", "metal3", x_iin, gy2)
    c.port("ibias", "metal2", gx1, y_nt_ib)
    c.port("out", "metal3", x_out, gy2)
    c.port("vdd", "metal3", x_vdd, gy2)
    c.port("vss", "metal1", grid((gx1 + gx2) / 2.0), gy1)
    c.write(w / f"{cell}.mag")

    ref = (
        "* BIAS v2 serdes_ref_vbuf_v2_pdk (calibrated 8-bar Xr + 2D CC OTA + outer dummies)\n"
        f".subckt {cell} iin ibias out vdd vss\n"
        + "\n".join(f"Xr{i} {'iin' if i==0 else f'rv{i}'} {'vss' if i==7 else f'rv{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=40.185" for i in range(8)) + "\n"
        "Xrdum_l vss vss vss sky130_fd_pr__res_high_po w=1 l=40.185\n"
        "Xrdum_r vss vss vss sky130_fd_pr__res_high_po w=1 l=40.185\n"
        "Xbd ibias ibias vss vss sky130_fd_pr__nfet_01v8 w=4 l=4\n"
        "Xt tail ibias vss vss sky130_fd_pr__nfet_01v8 w=4 l=4\n"
        "Xdum_tl ibias vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=4\n"
        "Xdum_tr ibias vss vss vss sky130_fd_pr__nfet_01v8 w=2 l=4\n"
        "Xa da iin tail vss sky130_fd_pr__nfet_01v8 w=24 l=4\n"
        "Xb out out tail vss sky130_fd_pr__nfet_01v8 w=24 l=4\n"
        "Xdum_nl tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4\n"
        "Xdum_nr tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4\n"
        "Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=8\n"
        "Xlb out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=8\n"
        "Xdum_p0 vdd vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=8\n"
        f".ends {cell}\n"
    )
    return verify_cell(w, cell, ref)


# =============================================================================
# 5. serdes_ref_pbuf_v2_pdk (100% REAL TRANSISTORS: 4->16 CMOS decoder + 16-tap string + LVT OTA)
# =============================================================================
def _cmos_row_rails(c: Cell, x1: float, x2: float, y_base: float, y_nwell_bot: float, y_nwell_top: float) -> tuple[float, float]:
    """Draw continuous P+ tap (vss at y_base, stops short of x2) and N+ tap (vdd, starts right of x1) + Nwell."""
    y_vss = grid(y_base)
    y_vdd = grid(y_nwell_top - 0.50)
    x_vss_r = grid(x2 - 0.70)   # clear of right vertical vdd trunk at x2!
    x_vdd_l = grid(x1 + 0.70)   # clear of left vertical vss trunk at x1!
    c.rect("pwell", grid(x1 - 0.3), grid(y_vss - 0.45), grid(x2 + 0.3), grid(y_nwell_bot - 0.15))
    c.rect("psubdiff", x1, grid(y_vss - 0.22), x_vss_r, grid(y_vss + 0.22))
    c.rect("psubdiffcont", grid(x1 + 0.25), grid(y_vss - 0.085), grid(x_vss_r - 0.25), grid(y_vss + 0.085))
    c.rect("locali", x1, grid(y_vss - 0.20), x_vss_r, grid(y_vss + 0.20))
    c.rect("metal1", x1, grid(y_vss - 0.22), x_vss_r, grid(y_vss + 0.22))
    c.rect("nwell", grid(x1 - 0.3), y_nwell_bot, grid(x2 + 0.3), grid(y_nwell_top + 0.15))
    c.rect("nsubdiff", x_vdd_l, grid(y_vdd - 0.22), x2, grid(y_vdd + 0.22))
    c.rect("nsubdiffcont", grid(x_vdd_l + 0.25), grid(y_vdd - 0.085), grid(x2 - 0.25), grid(y_vdd + 0.085))
    c.rect("locali", x_vdd_l, grid(y_vdd - 0.20), x2, grid(y_vdd + 0.20))
    c.rect("metal1", x_vdd_l, grid(y_vdd - 0.22), x2, grid(y_vdd + 0.22))
    n_taps = max(2, int((x2 - x1) // 6.0))
    for i in range(n_taps + 1):
        px_s = grid(x1 + 0.8 + (x_vss_r - x1 - 1.6) * i / n_taps)
        px_d = grid(x_vdd_l + 0.8 + (x2 - x_vdd_l - 1.6) * i / n_taps)
        c.pad("viali", px_s, y_vss, 0.17)
        c.pad("viali", px_d, y_vdd, 0.17)
    return y_vss, y_vdd


def build_ref_pbuf_v2(root: Path) -> dict:
    cell = "serdes_ref_pbuf_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)

    xr0 = clean_primitive(w, "pb_xr0", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=36.550, nx=10, m=1, guard=1))
    xr5 = clean_primitive(w, "pb_xr5_act", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=7.360, nx=5, m=1, guard=0))

    n1 = clean_primitive(w, "pb_n1", "sky130_fd_pr__nfet_01v8", dict(w=1.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    n2 = clean_primitive(w, "pb_n2", "sky130_fd_pr__nfet_01v8", dict(w=2.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    p2 = clean_primitive(w, "pb_p2", "sky130_fd_pr__pfet_01v8", dict(w=2.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=0, botc=1, doports=1))
    p4 = clean_primitive(w, "pb_p4", "sky130_fd_pr__pfet_01v8", dict(w=4.0, l=0.18, nf=1, guard=0, conn_gates=0, topc=0, botc=1, doports=1))

    ota_pl = clean_primitive(w, "pb_pl", "sky130_fd_pr__pfet_01v8_lvt",
                             dict(w=6.0, l=1.0, nf=18, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    ota_np = clean_primitive(w, "pb_np", "sky130_fd_pr__nfet_01v8_lvt",
                             dict(w=6.0, l=1.0, nf=10, guard=0, conn_gates=0, topc=1, botc=0, doports=1))
    ota_xt = clean_primitive(w, "pb_xt", "sky130_fd_pr__nfet_01v8",
                             dict(w=5.0, l=1.0, nf=6, guard=0, conn_gates=1, topc=1, botc=0, doports=1))
    ota_xst = clean_primitive(w, "pb_xst_v2", "sky130_fd_pr__nfet_01v8",
                              dict(w=5.0, l=0.18, nf=6, guard=0, conn_gates=1, topc=1, botc=1, doports=1))
    ota_bd = clean_primitive(w, "pb_bd", "sky130_fd_pr__nfet_01v8",
                             dict(w=1.0, l=1.0, nf=1, guard=0, conn_gates=1, topc=1, botc=0, doports=1))

    c = Cell()

    # ZONE A (Left): Xr0 + 3 rows x 5 active Xr1..Xr15 (with outer dummies)
    xr0_b = xr0.bbox()
    dx_r0, dy_r0 = grid(-xr0_b[0] + 1.6), grid(26.0)
    r0_info = strap_res_serpentine_dummies(c, xr0, dx_r0, dy_r0, n_active=8)

    xr5_b = xr5.bbox()
    dx_r5 = grid(dx_r0 + xr0_b[2] + 2.2 - xr5_b[0])
    r5_ys = [grid(8.8), grid(22.6), grid(36.4)]
    tap_pts: dict[int, tuple[float, float]] = {}
    r5_row_ends = []
    for row_i, ry in enumerate(r5_ys):
        c.include(xr5, dx=dx_r5, dy=ry)
        xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_r5) for r in xr5.rects["viali"]})
        ys = sorted({grid((r[1] + r[3]) / 2.0 + ry) for r in xr5.rects["viali"]})
        yb, yt = ys[0], ys[-1]
        # Add physical outer dummy ppolyres bars at exact 1.48 um pitch (no xpolycontact -> 100% etch match, 0 LVS dummy merge ambiguity)
        r_body = xr5.rects["ppolyres"][0]
        bw = grid(r_body[2] - r_body[0])
        for xd_c in (grid(xs[0] - 1.48), grid(xs[-1] + 1.48)):
            c.rect("ppolyres", grid(xd_c - bw / 2), grid(r_body[1] + ry), grid(xd_c + bw / 2), grid(r_body[3] + ry))
        r5_row_ends.append((grid(xs[0] - 1.48), grid(xs[-1] + 1.48), yb, yt))
        act = xs  # all 5 active bars
        base_k = row_i * 5
        if row_i == 0:
            tap_pts[0] = (act[0], yb)
        for j in range(5):
            y_end = yt if j % 2 == 0 else yb
            tap_k = base_k + j + 1
            if j < 4:
                c.wire("metal1", [(act[j], y_end), (act[j + 1], y_end)], 0.40)
                tap_pts[tap_k] = (grid((act[j] + act[j + 1]) / 2.0), y_end)
            else:
                tap_pts[tap_k] = (act[j], y_end)
        if row_i == 0:
            # r0_info["plus"][1] (~46.2) is well above r5 row2 exits (max 43.2) -> clean M2 hop to x_t0, M3 down to t0!
            x_t0 = grid(dx_r0 + xr0_b[2] + 0.9)
            c.via1(*r0_info["plus"])
            c.wire("metal2", [r0_info["plus"], (x_t0, r0_info["plus"][1])], 0.32)
            c.via2(x_t0, r0_info["plus"][1])
            c.wire("metal3", [(x_t0, r0_info["plus"][1]), (x_t0, tap_pts[0][1])], 0.34)
            c.via2(x_t0, tap_pts[0][1]); c.via1(*tap_pts[0])
            c.wire("metal2", [(x_t0, tap_pts[0][1]), tap_pts[0]], 0.32)
        if row_i < 2:
            # Inter-row jumper on M3 over r5 (r5 has ZERO other M3 -> zero M2 crossing with tap_exit_ys!)
            ny_b = sorted({grid((r[1] + r[3]) / 2.0 + r5_ys[row_i + 1]) for r in xr5.rects["viali"]})[0]
            y_mid = grid((yt + ny_b) / 2.0)
            c.via1(act[4], yt); c.via2(act[4], yt)
            c.via1(act[0], ny_b); c.via2(act[0], ny_b)
            c.wire("metal3", [(act[4], yt), (act[4], y_mid), (act[0], y_mid), (act[0], ny_b)], 0.36)

    # ZONE B (Center): 100% Real 4-to-16 CMOS Decoder + 16 CMOS Tgates (5 clean rows, pitch 12.2 um)
    # Place all 16 M3 tap tracks directly over xr0 (zero M3 on xr0 -> saves 13 um width!)
    x_r5_right = grid(dx_r5 + xr5_b[2] + 1.0)
    x_tap_m3_0 = grid(dx_r0 + xr0_b[0] + 0.80)
    x_tap_m3_pitch = 0.72
    x_tap_m3_last = grid(x_tap_m3_0 + 15 * x_tap_m3_pitch)
    b_m3_xs = [grid(x_r5_right + 1.2 + j * 0.80) for j in range(4)]
    x_dec_start = grid(b_m3_xs[-1] + 1.4)

    row_pitch = 12.2
    row_y0s = [grid(2.4 + r * row_pitch) for r in range(5)]

    # Clean DRC=0 CMOS gate builders (wide channel between yn+1.3 and yp-2.4 -> zero met1.2!)
    def place_inv(xc: float, y0: float, y_vss: float, y_vdd: float) -> dict:
        yn, yp = grid(y0 + 1.85), grid(y0 + 8.10)
        c.include(n1, dx=xc, dy=yn); c.include(p2, dx=xc, dy=yp)
        n_d = grid(xc + n1.pins("D")[0][0]); n_s = grid(xc + n1.pins("S")[0][0])
        p_d = grid(xc + p2.pins("D")[0][0]); p_s = grid(xc + p2.pins("S")[0][0])
        n_gy = grid(yn + n1.pins("G")[0][1]); p_gy = grid(yp + p2.pins("G")[0][1])
        c.wire("metal1", [(n_s, yn), (n_s, y_vss)], 0.22)
        c.wire("metal1", [(p_s, yp), (p_s, y_vdd)], 0.22)
        c.wire("metal1", [(xc, n_gy), (xc, p_gy)], 0.22)
        x_out = grid(xc - 0.80)
        c.wire("metal1", [(n_d, yn), (x_out, yn), (x_out, yp), (p_d, yp)], 0.22)
        y_mid = grid((n_gy + p_gy) / 2.0)
        return dict(inp=(xc, y_mid), out=(x_out, y_mid))

    def place_nand2(xc_l: float, y0: float, y_vss: float, y_vdd: float) -> dict:
        xc_r = grid(xc_l + 1.95)
        yn, yp = grid(y0 + 1.85), grid(y0 + 8.10)
        c.include(n2, dx=xc_l, dy=yn); c.include(n2, dx=xc_r, dy=yn)
        c.include(p2, dx=xc_l, dy=yp); c.include(p2, dx=xc_r, dy=yp)
        nl_d = grid(xc_l + n2.pins("D")[0][0]); nl_s = grid(xc_l + n2.pins("S")[0][0])
        nr_d = grid(xc_r + n2.pins("D")[0][0]); nr_s = grid(xc_r + n2.pins("S")[0][0])
        pl_d = grid(xc_l + p2.pins("D")[0][0]); pl_s = grid(xc_l + p2.pins("S")[0][0])
        pr_d = grid(xc_r + p2.pins("D")[0][0]); pr_s = grid(xc_r + p2.pins("S")[0][0])
        n_gy = grid(yn + n2.pins("G")[0][1]); p_gy = grid(yp + p2.pins("G")[0][1])
        c.wire("metal1", [(nl_s, yn), (nr_d, yn)], 0.22)
        c.wire("metal1", [(nr_s, yn), (nr_s, y_vss)], 0.22)
        c.wire("metal1", [(pl_s, yp), (pl_s, y_vdd)], 0.22)
        c.wire("metal1", [(pr_s, yp), (pr_s, y_vdd)], 0.22)
        c.wire("metal1", [(xc_l, n_gy), (xc_l, p_gy)], 0.22)
        c.wire("metal1", [(xc_r, n_gy), (xc_r, p_gy)], 0.22)
        x_out = grid(xc_l - 0.80)
        c.wire("metal1", [(nl_d, yn), (x_out, yn), (x_out, yp), (pl_d, yp)], 0.22)
        y_pm2 = grid(yp - 0.55)  # strictly below y_b_hop (y0 + 8.90..10.34) -> zero short to b0n!
        c.via1(pl_d, y_pm2); c.via1(pr_d, y_pm2)
        c.wire("metal2", [(pl_d, y_pm2), (pr_d, y_pm2)], 0.28)
        y_mid = grid((n_gy + p_gy) / 2.0)
        return dict(a=(xc_l, y_mid), b=(xc_r, y_mid), out=(x_out, y_mid))

    def place_nor2(xc_l: float, y0: float, y_vss: float, y_vdd: float) -> dict:
        xc_r = grid(xc_l + 1.95)
        yn, yp = grid(y0 + 1.85), grid(y0 + 8.10)
        c.include(n1, dx=xc_l, dy=yn); c.include(n1, dx=xc_r, dy=yn)
        c.include(p4, dx=xc_l, dy=yp); c.include(p4, dx=xc_r, dy=yp)
        nl_d = grid(xc_l + n1.pins("D")[0][0]); nl_s = grid(xc_l + n1.pins("S")[0][0])
        nr_d = grid(xc_r + n1.pins("D")[0][0]); nr_s = grid(xc_r + n1.pins("S")[0][0])
        pl_d = grid(xc_l + p4.pins("D")[0][0]); pl_s = grid(xc_l + p4.pins("S")[0][0])
        pr_d = grid(xc_r + p4.pins("D")[0][0]); pr_s = grid(xc_r + p4.pins("S")[0][0])
        n_gy = grid(yn + n1.pins("G")[0][1]); p_gy = grid(yp + p4.pins("G")[0][1])
        c.wire("metal1", [(nl_s, yn), (nl_s, y_vss)], 0.22)
        c.wire("metal1", [(nr_s, yn), (nr_s, y_vss)], 0.22)
        c.wire("metal1", [(pl_s, yp), (pr_d, yp)], 0.22)
        c.wire("metal1", [(pr_s, yp), (pr_s, y_vdd)], 0.22)
        c.wire("metal1", [(xc_l, n_gy), (xc_l, p_gy)], 0.22)
        c.wire("metal1", [(xc_r, n_gy), (xc_r, p_gy)], 0.22)
        x_out = grid(xc_l - 0.80)
        c.wire("metal1", [(nl_d, yn), (x_out, yn), (x_out, yp), (pl_d, yp)], 0.22)
        c.via1(nl_d, yn); c.via1(nr_d, yn)
        c.wire("metal2", [(nl_d, yn), (nr_d, yn)], 0.28)
        y_mid = grid((n_gy + p_gy) / 2.0)
        return dict(a=(xc_l, y_mid), b=(xc_r, y_mid), out=(x_out, y_mid))

    def place_tgate(xc: float, y0: float) -> dict:
        yn, yp = grid(y0 + 1.85), grid(y0 + 8.10)
        c.include(n1, dx=xc, dy=yn); c.include(p2, dx=xc, dy=yp)
        n_d = grid(xc + n1.pins("D")[0][0]); n_s = grid(xc + n1.pins("S")[0][0])
        p_d = grid(xc + p2.pins("D")[0][0]); p_s = grid(xc + p2.pins("S")[0][0])
        n_gy = grid(yn + n1.pins("G")[0][1]); p_gy = grid(yp + p2.pins("G")[0][1])
        x_in = grid(xc - 0.80); x_out = grid(xc + 0.80)
        c.wire("metal1", [(n_d, yn), (x_in, yn), (x_in, yp), (p_d, yp)], 0.22)
        c.wire("metal1", [(n_s, yn), (x_out, yn), (x_out, yp), (p_s, yp)], 0.22)
        return dict(inp=(x_in, yp), out=(x_out, grid(yn + 0.15)), en=(xc, n_gy), enb=(xc, p_gy))

    dec_w = 48.2
    x_dec_end = grid(x_dec_start + dec_w)
    row_rails = []
    for y0 in row_y0s:
        row_rails.append(_cmos_row_rails(c, x_dec_start, x_dec_end, y0, grid(y0 + 5.25), grid(y0 + 11.55)))
    c.wire("metal1", [(x_dec_start, row_rails[0][0]), (x_dec_start, row_rails[-1][0])], 0.44)
    c.wire("metal1", [(x_dec_end, row_rails[0][1]), (x_dec_end, row_rails[-1][1])], 0.44)

    # Row 0: 4 INV + 4 NAND2(a) + 4 NAND2(b)
    y0_pre = row_y0s[0]
    yvss0, yvdd0 = row_rails[0]
    inv_c = [place_inv(grid(x_dec_start + 1.8 + i * 2.4), y0_pre, yvss0, yvdd0) for i in range(4)]
    nand_a = [place_nand2(grid(x_dec_start + 13.8 + i * 4.1), y0_pre, yvss0, yvdd0) for i in range(4)]
    nand_b = [place_nand2(grid(x_dec_start + 30.4 + i * 4.1), y0_pre, yvss0, yvdd0) for i in range(4)]

    # Row 0 routing: 8 horizontal M2 tracks in center channel y0_pre + 3.55 .. y0_pre + 6.91 (clear of n2 M1 top!)
    r0_tracks = [grid(y0_pre + 3.55 + k * 0.48) for k in range(8)]
    c_pins_in = []
    for i in range(4):
        y_ti, y_to = r0_tracks[2 * i], r0_tracks[2 * i + 1]
        ix, iy = inv_c[i]["inp"]; ox, oy = inv_c[i]["out"]
        c.wire("metal1", [(ix, min(iy, y_ti)), (ix, max(iy, y_ti))], 0.22); c.via1(ix, y_ti)
        c.wire("metal1", [(ox, min(oy, y_to)), (ox, max(oy, y_to))], 0.22); c.via1(ox, y_to)
        c_pins_in.append((ix, y_ti))

    for idx, (tr_a, tr_b) in enumerate([(3, 1), (3, 0), (2, 1), (2, 0)]):
        for pt, tr in ((nand_a[idx]["a"], tr_a), (nand_a[idx]["b"], tr_b)):
            yt = r0_tracks[tr]
            c.wire("metal1", [(pt[0], min(pt[1], yt)), (pt[0], max(pt[1], yt))], 0.22); c.via1(pt[0], yt)
    for tr in range(4):
        x_src = inv_c[tr // 2]["inp"][0] if tr % 2 == 0 else inv_c[tr // 2]["out"][0]
        c.wire("metal2", [(x_src, r0_tracks[tr]), (nand_a[3]["b"][0], r0_tracks[tr])], 0.28)

    for idx, (tr_a, tr_b) in enumerate([(7, 5), (7, 4), (6, 5), (6, 4)]):
        for pt, tr in ((nand_b[idx]["a"], tr_a), (nand_b[idx]["b"], tr_b)):
            yt = r0_tracks[tr]
            c.wire("metal1", [(pt[0], min(pt[1], yt)), (pt[0], max(pt[1], yt))], 0.22); c.via1(pt[0], yt)
    for tr in range(4, 8):
        x_src = inv_c[tr // 2]["inp"][0] if tr % 2 == 0 else inv_c[tr // 2]["out"][0]
        c.wire("metal2", [(x_src, r0_tracks[tr]), (nand_b[3]["b"][0], r0_tracks[tr])], 0.28)

    # Rows 1..4 (j = 0..3): a_m3_xs[0] at +5.15 sits cleanly between inv_c[1] (+4.2) and inv_c[2] (+6.6)!
    slice_xs = [grid(x_dec_start + 3.2 + i * 11.4) for i in range(4)]
    a_m3_xs = [grid(sx + 1.95) for sx in slice_xs]
    tap_m3_xs = [grid(sx + 9.80) for sx in slice_xs]

    tgate_in_pts: dict[int, tuple[float, float]] = {}
    for j in range(4):
        y0 = row_y0s[j + 1]
        yvss_j, yvdd_j = row_rails[j + 1]
        y_bj_bus = grid(y0 + 3.60)
        y_sk_bus = grid(y0 + 4.30)
        y_sbk_bus = grid(y0 + 5.00)

        # Route b[j]n on M2 over Row 0 PMOS (y0_pre + 8.90 + j*0.48 -> max 10.34, well clear of y_vdd = 11.05!)
        bx_o, by_o = nand_b[j]["out"]
        y_b_hop = grid(y0_pre + 8.90 + j * 0.48)
        c.wire("metal1", [(bx_o, by_o), (bx_o, y_b_hop)], 0.22); c.via1(bx_o, y_b_hop)
        c.wire("metal2", [(b_m3_xs[j], y_b_hop), (bx_o, y_b_hop)], 0.28); c.via2(b_m3_xs[j], y_b_hop)
        c.wire("metal3", [(b_m3_xs[j], y_b_hop), (b_m3_xs[j], y_bj_bus)], 0.34); c.via2(b_m3_xs[j], y_bj_bus)
        c.wire("metal2", [(b_m3_xs[j], y_bj_bus), (slice_xs[3], y_bj_bus)], 0.28)

        for i in range(4):
            k = 4 * j + i
            sx = slice_xs[i]
            no = place_nor2(sx, y0, yvss_j, yvdd_j)
            iv = place_inv(grid(sx + 5.2), y0, yvss_j, yvdd_j)
            tg = place_tgate(grid(sx + 8.3), y0)

            ax, ay = no["a"]
            c.wire("metal1", [(ax, min(ay, y_bj_bus)), (ax, max(ay, y_bj_bus))], 0.22); c.via1(ax, y_bj_bus)

            bx, by = no["b"]
            y_ai_tap = grid(y0 + 3.00)
            c.wire("metal1", [(bx, min(by, y_ai_tap)), (bx, max(by, y_ai_tap))], 0.22)
            c.via1(bx, y_ai_tap); c.via2(bx, y_ai_tap)

            nox, noy = no["out"]; ivx, ivy = iv["inp"]; enx, eny = tg["en"]
            c.wire("metal1", [(nox, min(noy, y_sk_bus)), (nox, max(noy, y_sk_bus))], 0.22); c.via1(nox, y_sk_bus)
            c.wire("metal1", [(ivx, min(ivy, y_sk_bus)), (ivx, max(ivy, y_sk_bus))], 0.22); c.via1(ivx, y_sk_bus)
            c.wire("metal1", [(enx, min(eny, y_sk_bus)), (enx, max(eny, y_sk_bus))], 0.22); c.via1(enx, y_sk_bus)
            c.wire("metal2", [(nox, y_sk_bus), (enx, y_sk_bus)], 0.28)

            iox, ioy = iv["out"]; eb_x, eb_y = tg["enb"]
            c.wire("metal1", [(iox, min(ioy, y_sbk_bus)), (iox, max(ioy, y_sbk_bus))], 0.22); c.via1(iox, y_sbk_bus)
            c.wire("metal1", [(eb_x, min(eb_y, y_sbk_bus)), (eb_x, max(eb_y, y_sbk_bus))], 0.22); c.via1(eb_x, y_sbk_bus)
            c.wire("metal2", [(iox, y_sbk_bus), (eb_x, y_sbk_bus)], 0.28)

            tx_o, ty_o = tg["out"]
            c.via1(tx_o, ty_o); c.wire("metal2", [(tx_o, ty_o), (tap_m3_xs[i], ty_o)], 0.28)
            c.via2(tap_m3_xs[i], ty_o)
            tgate_in_pts[k] = tg["inp"]

    # Route a[0..3]n cleanly on M2 at y0_pre + 0.55..2.05 (wait: y0_pre + 1.85 is yn! Put a_hop at y_row1 - 1.2..no:
    # put a_hop at y0_pre + 0.35..1.85? No, put a_hop at y0_pre + 7.25? No, put a_hop BELOW y0_pre at y = 0.65..2.15? No, gy1!
    # Best: put a_hop right at y0_pre + 9.25..10.81 on M2 OVER Row 0 PMOS (since nand_a is left of nand_b, ZERO X overlap?
    # Wait: b_hop goes LEFT across nand_a to b_m3_xs! So put a_hop at y0_pre + 7.20 + i*0.50 -> 7.20, 7.70, 8.20 (clear of r0_tracks max 6.89 AND clear of b_hop min 9.25! And move nand2 y_pm2 to yp + 0.85 = 8.95 -> wait: 7.20..8.70 has 4 tracks? 7.25, 7.75, 8.25, 8.75? Put y_pm2 at yp + 1.35 = 9.45? No, put y_pm2 inside place_nand2 at yp - 0.55 = 7.55? No, p2 top is yp+1.49! Wait: place_nand2's y_pm2 is ONLY over nand_a/nand_b PMOS, and y_a_hop goes right to a_m3_xs!
    # Actually: y0_pre + 11.20 is y_vdd; y_row1 = y0_pre + 12.20! Simply put a_hop on M2 at y0_pre + 0.45 + i*0.52? No, yn=1.85 so n2 bot = 0.49 (M1 only on S/D, NOT M2!). On M2, y0_pre + 0.35..1.91 is 100% EMPTY!!
    # Why did a_hop have met1.2 earlier? Because ax_o M1 dropped down to y_a_hop and via1 M1 pad (0.32) touched nl_d M1!
    # Fix: keep ax_o M1 -> via1 -> M2 at y = y0_pre + 7.15 (ABOVE r0_tracks!) or drop on M2 from y_mid down to y_a_hop!
    for i in range(4):
        ax_o, ay_o = nand_a[i]["out"]
        # Stay >= 0.40 um clear of yn = y0_pre + 1.85 M1 strap AND r0_tracks[0] = y0_pre + 3.55!
        y_a_hop = grid(y0_pre + (0.65, 1.15, 2.55, 3.05)[i])
        c.wire("metal1", [(ax_o, min(y_a_hop, ay_o)), (ax_o, max(y_a_hop, ay_o))], 0.22); c.via1(ax_o, y_a_hop)
        c.wire("metal2", [(ax_o, y_a_hop), (a_m3_xs[i], y_a_hop)], 0.28); c.via2(a_m3_xs[i], y_a_hop)
        c.wire("metal3", [(a_m3_xs[i], y_a_hop), (a_m3_xs[i], grid(row_y0s[4] + 3.2))], 0.34)

    y_tap_top = grid(row_y0s[4] + 12.0)
    for tx in tap_m3_xs:
        c.wire("metal3", [(tx, grid(row_y0s[1] + 2.0)), (tx, y_tap_top)], 0.34)
        c.via2(tx, y_tap_top)
    c.wire("metal2", [(tap_m3_xs[0], y_tap_top), (tap_m3_xs[-1], y_tap_top)], 0.40)

    # Planar non-crossing M2 fanout GOING LEFT from r5 taps to x_tap_m3 (over xr0):
    # r5_ys = [8.8, 22.6, 36.4] -> row0: 4.3..13.3, row1: 18.1..27.1, row2: 31.9..40.9
    # Rightmost tap gets outermost y_ex so horizontal M2 flies cleanly LEFT over inner taps!
    # All tap_exit_ys >= 1.0 um clear of ALL y_row_tap (row1=23.35..25.03, row2=35.55..37.23, row3=47.75..49.43, row4=59.95..61.63)!
    tap_exit_ys = [
        # Row 0 (bot=4.3, top=13.3): t0,t2,t4 bot (3.4, 2.8, 2.2); t1,t3,t5 top (14.4, 15.0, 15.6)
        grid(3.40), grid(14.40), grid(2.80), grid(15.00), grid(2.20), grid(15.60),
        # Row 1 (bot=18.1, top=27.1): t6,t8,t10 top (28.2, 28.8, 29.4); t7,t9 bot (17.0, 16.4)
        grid(28.20), grid(17.00), grid(28.80), grid(16.40), grid(29.40),
        # Row 2 (bot=31.9, top=40.9): t11,t13,t15 top (42.0, 42.6, 43.2); t12,t14 bot (30.8, 30.2)
        grid(42.00), grid(30.80), grid(42.60), grid(30.20), grid(43.20),
    ]
    for k in range(16):
        j, i = k // 4, k % 4
        y0 = row_y0s[j + 1]
        y_row_tap = grid(y0 + 8.75 + i * 0.56)
        x_m3 = grid(x_tap_m3_0 + k * x_tap_m3_pitch)
        tx_s, ty_s = tap_pts[k]
        tx_d, ty_d = tgate_in_pts[k]
        y_ex = tap_exit_ys[k]
        c.via1(tx_s, ty_s)
        c.wire("metal2", [(tx_s, ty_s), (tx_s, y_ex), (x_m3, y_ex)], 0.28)
        c.via2(x_m3, y_ex)
        c.wire("metal3", [(x_m3, y_ex), (x_m3, y_row_tap)], 0.34)
        c.via2(x_m3, y_row_tap)
        c.wire("metal2", [(x_m3, y_row_tap), (tx_d, y_row_tap)], 0.28)
        c.wire("metal1", [(tx_d, min(ty_d, y_row_tap)), (tx_d, max(ty_d, y_row_tap))], 0.22)
        c.via1(tx_d, y_row_tap)

    # ZONE C (Right): Switched 300 uA LVT OTA
    x_ota_c = grid(x_dec_end + 17.5)
    dy_pl = grid(45.5)
    dy_np = grid(24.0)
    dy_xt = grid(11.5)
    dy_xst = grid(4.5)
    c.include(ota_pl, dx=x_ota_c, dy=dy_pl)
    c.include(ota_np, dx=x_ota_c, dy=dy_np)
    c.include(ota_xt, dx=x_ota_c, dy=dy_xt)
    c.include(ota_xst, dx=x_ota_c, dy=dy_xst)
    dx_bd = grid(x_ota_c + ota_xt.bbox()[2] + 2.6)
    c.include(ota_bd, dx=dx_bd, dy=dy_xt)

    gx1 = grid(0.6)
    gx2 = grid(max(dx_bd + ota_bd.bbox()[2], x_ota_c + ota_pl.bbox()[2]) + 2.6)
    gy1 = grid(0.6)
    gy2 = grid(max(row_y0s[4] + 13.0, dy_pl + ota_pl.bbox()[3] + 2.0))
    draw_m1_guard_ring(c, gx1, gy1, gx2, gy2, w=0.80)

    c.wire("metal1", [(gx1, dy_r0), (r0_info["x_gl"], dy_r0)], 0.50)
    c.wire("metal1", [(r0_info["minus"][0], r0_info["minus"][1]), (r0_info["minus"][0], gy2)], 0.40)

    c.wire("metal1", [(x_dec_start, gy1), (x_dec_start, row_rails[0][0])], 0.44)

    # c0..c3 down to bottom perimeter on M3 (all >= 2.7 um apart!)
    c_port_xs = []
    for i in range(4):
        ix, y_tr = c_pins_in[i]
        c.via2(ix, y_tr)
        c.wire("metal3", [(ix, gy1), (ix, y_tr)], 0.34)
        c_port_xs.append(ix)

    x_o_vdd = grid(x_ota_c + ota_pl.bbox()[0] - 1.2)
    x_o_da = grid(x_ota_c + ota_pl.bbox()[0] - 2.3)
    x_o_out = grid(x_ota_c + ota_pl.bbox()[2] + 1.2)

    c.via1(x_dec_end, row_rails[-1][1])
    c.wire("metal2", [(x_dec_end, row_rails[-1][1]), (x_o_vdd, row_rails[-1][1])], 0.50)
    c.via2(x_o_vdd, row_rails[-1][1])

    # Xla/Xlb (2x18 pfet_lvt)
    pl_xs = sd_xs_of(ota_pl, "pdiffc", x_ota_c)
    pl_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_pl) for r in ota_pl.rects["pdiffc"]})
    pl_gxs = sorted({grid(x + x_ota_c) for _, x, _, nm in ota_pl.labels if nm.startswith("G")})
    pl_gys = sorted({grid(y + dy_pl) for _, _, y, nm in ota_pl.labels if nm.startswith("G")})
    pbx, pby = ota_pl.pins("B")[0]
    pbx, pby = grid(pbx + x_ota_c), grid(pby + dy_pl)

    vdd_ys, da_ys, out_ys = [row_rails[-1][1]], [], []
    for r_idx, yr in enumerate(pl_ys):
        yv = grid(yr + 1.6); yda = grid(yr + 0.1); you = grid(yr - 1.4)
        for idx in (0, 1, 3, 5, 7, 9, 11, 13, 15, 17, 18):
            c.via1(pl_xs[idx], yv)
        c.wire("metal2", [(x_o_vdd, yv), (pl_xs[18], yv)], 0.40)
        c.via2(x_o_vdd, yv); vdd_ys.append(yv)
        a_cols = (2, 4, 14, 16) if r_idx == 0 else (6, 8, 10, 12)
        b_cols = (6, 8, 10, 12) if r_idx == 0 else (2, 4, 14, 16)
        for idx in a_cols:
            c.via1(pl_xs[idx], yda)
        c.wire("metal2", [(x_o_da, yda), (pl_xs[max(a_cols)], yda)], 0.34)
        c.via2(x_o_da, yda); da_ys.append(yda)
        for idx in b_cols:
            c.via1(pl_xs[idx], you)
        c.wire("metal2", [(pl_xs[min(b_cols)], you), (x_o_out, you)], 0.34)
        c.via2(x_o_out, you); out_ys.append(you)
        gy = pl_gys[r_idx]
        for gx in pl_gxs[1:17]:
            c.via1(gx, gy)
        c.wire("metal2", [(x_o_da, gy), (pl_gxs[16], gy)], 0.32)
        c.via2(x_o_da, gy); da_ys.append(gy)
        for gx, sx in ((pl_gxs[0], pl_xs[0]), (pl_gxs[17], pl_xs[18])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.28)

    c.body_contact(pbx, pby)
    y_pby_m2 = grid(pby - 0.65)
    c.wire("metal2", [(x_o_vdd, y_pby_m2), (pbx, y_pby_m2), (pbx, pby)], 0.36)
    c.via2(x_o_vdd, y_pby_m2); vdd_ys.append(y_pby_m2)
    c.wire("metal3", [(x_o_vdd, min(vdd_ys)), (x_o_vdd, gy2)], 0.60)

    # Xa/Xb (10-finger nfet_lvt)
    np_xs = sd_xs_of(ota_np, "ndiffc", x_ota_c)
    np_gpts = gate_pts_of(ota_np, x_ota_c, dy_np)
    np_gy = np_gpts[0][1]
    y_np_tail = grid(dy_np - 1.6); y_np_da = grid(dy_np + 0.0); y_np_out = grid(dy_np + 1.6)
    y_np_tap = grid(np_gy + 0.80); y_np_outg = grid(np_gy + 1.60)
    for tx in (np_xs[1], np_xs[3], np_xs[5], np_xs[7], np_xs[9]):
        c.via1(tx, y_np_tail)
    c.wire("metal2", [(np_xs[1], y_np_tail), (np_xs[9], y_np_tail)], 0.44)
    for ax in (np_xs[2], np_xs[8]):
        c.via1(ax, y_np_da)
    c.wire("metal2", [(x_o_da, y_np_da), (np_xs[8], y_np_da)], 0.34); c.via2(x_o_da, y_np_da); da_ys.append(y_np_da)
    for bx in (np_xs[4], np_xs[6]):
        c.via1(bx, y_np_out)
    c.wire("metal2", [(np_xs[4], y_np_out), (x_o_out, y_np_out)], 0.34); c.via2(x_o_out, y_np_out); out_ys.append(y_np_out)
    for idx in (1, 2, 7, 8):
        gx = np_gpts[idx][0]; c.via1(gx, np_gy); c.wire("metal2", [(gx, np_gy), (gx, y_np_tap)], 0.28)
    c.wire("metal2", [(np_gpts[1][0], y_np_tap), (np_gpts[8][0], y_np_tap)], 0.32)
    x_tap_drop = grid(x_o_da - 1.1)
    c.wire("metal2", [(tap_m3_xs[-1], y_tap_top), (x_tap_drop, y_tap_top)], 0.36); c.via2(x_tap_drop, y_tap_top)
    c.wire("metal3", [(x_tap_drop, y_np_tap), (x_tap_drop, y_tap_top)], 0.36); c.via2(x_tap_drop, y_np_tap)
    c.wire("metal2", [(x_tap_drop, y_np_tap), (np_gpts[1][0], y_np_tap)], 0.32)

    for idx in (3, 4, 5, 6):
        gx = np_gpts[idx][0]; c.via1(gx, np_gy); c.via2(gx, np_gy)
        c.wire("metal3", [(gx, np_gy), (gx, y_np_outg)], 0.34); c.via2(gx, y_np_outg)
    c.wire("metal2", [(np_gpts[3][0], y_np_outg), (x_o_out, y_np_outg)], 0.34); c.via2(x_o_out, y_np_outg); out_ys.append(y_np_outg)

    # P+ tap bar well clear of LVTN (>= 1.0 um below ota_np!)
    y_ota_ptap = grid(dy_np - 5.2)
    c.rect("pwell", grid(x_o_vdd - 0.5), grid(y_ota_ptap - 0.5), gx2, grid(y_ota_ptap + 0.5))
    c.rect("psubdiff", grid(x_o_vdd), grid(y_ota_ptap - 0.24), gx2, grid(y_ota_ptap + 0.24))
    c.rect("psubdiffcont", grid(x_o_vdd + 0.35), grid(y_ota_ptap - 0.085), grid(gx2 - 0.35), grid(y_ota_ptap + 0.085))
    c.rect("locali", grid(x_o_vdd), grid(y_ota_ptap - 0.22), gx2, grid(y_ota_ptap + 0.22))
    c.rect("metal1", grid(x_o_vdd), grid(y_ota_ptap - 0.24), gx2, grid(y_ota_ptap + 0.24))
    for i in range(4):
        c.pad("viali", grid(x_o_vdd + 2.0 + i * 6.0), y_ota_ptap, 0.17)
    for gx, sx in ((np_gpts[0][0], np_xs[0]), (np_gpts[9][0], np_xs[10])):
        c.wire("metal1", [(gx, np_gy), (sx, np_gy), (sx, y_ota_ptap)], 0.28)

    # Xt, Xst, Xbd
    xt_xs = sd_xs_of(ota_xt, "ndiffc", x_ota_c)
    xt_g = grid(x_ota_c + ota_xt.pins("G")[0][0]); xt_gy = grid(dy_xt + ota_xt.pins("G")[0][1])
    xst_xs = sd_xs_of(ota_xst, "ndiffc", x_ota_c)
    xst_g = grid(x_ota_c + ota_xst.pins("G")[0][0]); xst_gy = grid(dy_xst + ota_xst.pins("G")[0][1])
    bd_xs = sd_xs_of(ota_bd, "ndiffc", dx_bd)
    bd_g = grid(dx_bd + ota_bd.pins("G")[0][0]); bd_gy = grid(dy_xt + ota_bd.pins("G")[0][1])

    y_xt_d = grid(dy_xt + 1.2); y_xt_s = grid(dy_xt - 1.2)
    y_xst_d = grid(dy_xst + 1.2)
    for dx in xt_xs[1::2]:
        c.via1(dx, y_xt_d)
    c.wire("metal2", [(xt_xs[1], y_xt_d), (xt_xs[-2], y_xt_d)], 0.44)
    c.via2(xt_xs[3], y_xt_d); c.via2(xt_xs[3], y_np_tail)
    c.wire("metal3", [(xt_xs[3], y_xt_d), (xt_xs[3], y_np_tail)], 0.54)

    for sx in xt_xs[::2]:
        c.via1(sx, y_xt_s)
    c.wire("metal2", [(xt_xs[0], y_xt_s), (xt_xs[-1], y_xt_s)], 0.44)
    for dx in xst_xs[1::2]:
        c.via1(dx, y_xst_d)
    c.wire("metal2", [(xst_xs[1], y_xst_d), (xst_xs[-2], y_xst_d)], 0.44)
    c.wire("metal2", [(xst_xs[3], y_xst_d), (xst_xs[3], y_xt_s)], 0.44)
    y_xst_s = grid(dy_xst - 1.2)
    for sx in xst_xs[::2]:
        c.via1(sx, y_xst_s)
    c.wire("metal2", [(xst_xs[0], y_xst_s), (xst_xs[-1], y_xst_s)], 0.44)
    c.wire("metal2", [(xst_xs[0], y_xst_s), (xst_xs[0], gy1)], 0.44)
    c.via1(xst_xs[0], gy1)

    c.wire("metal1", [(bd_xs[0], dy_xt), (bd_xs[0], gy1)], 0.28)
    c.via1(bd_xs[1], dy_xt); c.via1(bd_g, bd_gy); c.via1(xt_g, xt_gy)
    c.wire("metal2", [(xt_g, xt_gy), (gx2, xt_gy)], 0.34)
    c.wire("metal2", [(bd_g, bd_gy), (bd_g, xt_gy)], 0.32)
    c.wire("metal2", [(bd_xs[1], dy_xt), (bd_xs[1], xt_gy)], 0.32)

    # Pull xst gate out LEFT on M1 past xst bbox before via1/via2 -> zero met1.2 on l=0.18!
    x_xst_en = grid(x_ota_c + ota_xst.bbox()[0] - 0.85)
    c.wire("metal1", [(x_xst_en, xst_gy), (xst_g, xst_gy)], 0.24)
    c.via1(x_xst_en, xst_gy); c.via2(x_xst_en, xst_gy)
    c.wire("metal3", [(x_xst_en, gy1), (x_xst_en, xst_gy)], 0.36)

    c.wire("metal3", [(x_o_da, min(da_ys)), (x_o_da, max(da_ys))], 0.44)
    c.wire("metal3", [(x_o_out, min(out_ys)), (x_o_out, gy2)], 0.60)

    # Export iin (= tap 15) straight up to top perimeter on M3 at x_tap_m3_last!
    c.wire("metal3", [(x_tap_m3_last, grid(row_y0s[4] + 8.88)), (x_tap_m3_last, gy2)], 0.40)

    c.port("iin", "metal3", x_tap_m3_last, gy2)
    c.port("ibias", "metal2", gx2, xt_gy)
    c.port("out", "metal3", x_o_out, gy2)
    c.port("en", "metal3", x_xst_en, gy1)
    for i in range(4):
        c.port(f"c{i}", "metal3", c_port_xs[i], gy1)
    c.port("vdd", "metal3", x_o_vdd, gy2)
    c.port("vss", "metal1", grid((gx1 + gx2) / 2.0), gy1)
    c.write(w / f"{cell}.mag")

    # Reference netlist (100% real transistors matching bias_v2.spice + outer dummies)
    ref_lines = [
        "* BIAS v2 serdes_ref_pbuf_v2_pdk (100% real transistors, 4->16 CMOS decoder + 16-tap string + LVT OTA)",
        f".subckt {cell} iin ibias out en c0 c1 c2 c3 vdd vss",
        *[f"Xr0_{i} {'t0' if i==0 else f'p0_{i}'} {'vss' if i==7 else f'p0_{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=36.550" for i in range(8)],
        "Xr0_dl vss vss vss sky130_fd_pr__res_high_po w=1 l=36.550",
        "Xr0_dr vss vss vss sky130_fd_pr__res_high_po w=1 l=36.550",
        *[f"Xr{k} {'iin' if k==15 else f't{k}'} t{k-1} vss sky130_fd_pr__res_high_po w=1 l=7.360" for k in range(1, 16)],
        # 4 input inverters
        *[f"Xic{i}_n c{i}b c{i} vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXic{i}_p c{i}b c{i} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18" for i in range(4)],
        # 4 NAND2 a0n..a3n
        *[f"Xna{i}_na a{i}n {a} ma{i} vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\nXna{i}_nb ma{i} {b} vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\n"
          f"Xna{i}_pa a{i}n {a} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18\nXna{i}_pb a{i}n {b} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18"
          for i, (a, b) in enumerate([("c1b", "c0b"), ("c1b", "c0"), ("c1", "c0b"), ("c1", "c0")])],
        # 4 NAND2 b0n..b3n
        *[f"Xnb{i}_na b{i}n {a} mb{i} vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\nXnb{i}_nb mb{i} {b} vss vss sky130_fd_pr__nfet_01v8 w=2 l=0.18\n"
          f"Xnb{i}_pa b{i}n {a} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18\nXnb{i}_pb b{i}n {b} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18"
          for i, (a, b) in enumerate([("c3b", "c2b"), ("c3b", "c2"), ("c3", "c2b"), ("c3", "c2")])],
        # 16 NOR2 + 16 INV + 16 TGATE
        *[f"Xno{k}_na s{k} b{k//4}n vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXno{k}_nb s{k} a{k%4}n vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\n"
          f"Xno{k}_pa s{k} b{k//4}n mno{k} vdd sky130_fd_pr__pfet_01v8 w=4 l=0.18\nXno{k}_pb mno{k} a{k%4}n vdd vdd sky130_fd_pr__pfet_01v8 w=4 l=0.18\n"
          f"Xi{k}_n sb{k} s{k} vss vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXi{k}_p sb{k} s{k} vdd vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18\n"
          f"Xg{k}_n {'iin' if k==15 else f't{k}'} s{k} tap vss sky130_fd_pr__nfet_01v8 w=1 l=0.18\nXg{k}_p {'iin' if k==15 else f't{k}'} sb{k} tap vdd sky130_fd_pr__pfet_01v8 w=2 l=0.18"
          for k in range(16)],
        # Switched 300 uA LVT OTA + outer dummies
        "Xbd ibias ibias vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        "Xt tail ibias ts vss sky130_fd_pr__nfet_01v8 w=30 l=1",
        "Xst ts en vss vss sky130_fd_pr__nfet_01v8 w=30 l=0.18",
        "Xa da tap tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xb out out tail vss sky130_fd_pr__nfet_01v8_lvt w=24 l=1",
        "Xdum_nl tail vss vss vss sky130_fd_pr__nfet_01v8_lvt w=6 l=1",
        "Xdum_nr tail vss vss vss sky130_fd_pr__nfet_01v8_lvt w=6 l=1",
        "Xla da da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        "Xlb out da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=96 l=1",
        "Xdum_p vdd vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=1",
        f".ends {cell}\n",
    ]
    return verify_cell(w, cell, "\n".join(ref_lines))


# =============================================================================
# 6. serdes_bias_ref_v2_pdk (Folded-cascode BG + V->I + stacked MIM1+MIM2, <=15,500 um^2)
# =============================================================================
def _add_outer_ppolyres_dummies(c: Cell, prim: Cell, dx: float, dy: float) -> None:
    """Add physical un-contacted outer ppolyres dummy bars at exact 1.48 um pitch (100% etch match, 0 LVS ambiguity)."""
    xs = sorted({grid((r[0] + r[2]) / 2.0 + dx) for r in prim.rects["viali"]})
    r_body = prim.rects["ppolyres"][0]
    bw = grid(r_body[2] - r_body[0])
    for xd_c in (grid(xs[0] - 1.48), grid(xs[-1] + 1.48)):
        c.rect("ppolyres", grid(xd_c - bw / 2), grid(r_body[1] + dy), grid(xd_c + bw / 2), grid(r_body[3] + dy))


def _place_mim_stack_site(
    c: Cell, lower: Cell, upper: Cell, dx: float, dy: float
) -> dict:
    """Place X-mirrored stacked MIM1+MIM2 (nx x 1) at (dx, dy) and return exact terminal coords."""
    lp = sorted(lower.rects["mimcapcontact"], key=lambda r: (r[0], r[1]))
    up = sorted([(-r[2], r[1], -r[0], r[3]) for r in upper.rects["mimcap2contact"]], key=lambda r: (r[0], r[1]))
    dx_u = grid(dx + (lp[0][0] + lp[0][2] - up[0][0] - up[0][2]) / 2.0)
    dy_u = grid(dy + (lp[0][1] + lp[0][3] - up[0][1] - up[0][3]) / 2.0)
    c.include(lower, dx=dx, dy=dy)
    c.include(upper, dx=dx_u, dy=dy_u, mirror_x=True)
    a_pts = sorted((grid(x + dx), grid(y + dy)) for _, x, y, nm in lower.labels if nm.startswith("C1"))
    b3_pts = sorted((grid(x + dx), grid(y + dy)) for _, x, y, nm in lower.labels if nm.startswith("C2"))
    b5_pts = sorted((grid(-x + dx_u), grid(y + dy_u)) for _, x, y, nm in upper.labels if nm.startswith("C1"))
    lb = lower.bbox()
    ub = upper.bbox()
    bx1 = grid(min(lb[0] + dx, -ub[2] + dx_u))
    bx2 = grid(max(lb[2] + dx, -ub[0] + dx_u))
    by1 = grid(min(lb[1] + dy, ub[1] + dy_u))
    by2 = grid(max(lb[3] + dy, ub[3] + dy_u))
    return dict(a_pts=a_pts, b3_pts=b3_pts, b5_pts=b5_pts, bbox=(bx1, by1, bx2, by2))


def build_bias_ref_v2(root: Path) -> dict:
    cell = "serdes_bias_ref_v2_pdk"
    w = root / cell
    w.mkdir(parents=True, exist_ok=True)

    # --- Generate/cache clean SKY130 primitives ---
    # 1. Core PMOS Xm1..Xm5: 2x12 pfet_lvt (20 active + 4 outer dummies, 2D common-centroid)
    xm_p = clean_primitive(w, "bg_xm_2x12", "sky130_fd_pr__pfet_01v8_lvt",
                           dict(w=14.0, l=12.0, nf=12, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    # 2. Xmv + Xo0..3: 5x6 pfet_lvt (20 active + 10 outer dummies, 5 rows = [o0, o1, mv, o2, o3])
    xmv_p = clean_primitive(w, "bg_xmv_5x6", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=8.0, l=4.0, nf=6, m=5, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    # 3. Folded-cascode OTA (serdes_bg_fcota_v2) primitives
    fc_fab = clean_primitive(w, "fc_fab", "sky130_fd_pr__pfet_01v8_lvt",
                             dict(w=12.0, l=8.0, nf=6, m=2, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
    fc_pc = clean_primitive(w, "fc_pc4", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=12.0, l=2.5, nf=4, m=1, guard=1, conn_gates=1, topc=0, botc=1, doports=1))
    fc_pb = clean_primitive(w, "fc_pb", "sky130_fd_pr__pfet_01v8_lvt",
                            dict(w=12.0, l=8.0, nf=2, m=1, guard=1, conn_gates=1, topc=0, botc=1, doports=1))
    fc_pbnc = clean_primitive(w, "fc_pbnc", "sky130_fd_pr__pfet_01v8_lvt",
                              dict(w=24.0, l=8.0, nf=1, m=1, guard=1, conn_gates=1, topc=0, botc=1, doports=1))
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
    # 4. V->I OTA (serdes_bg_ota_v2) + startup + diodes + slew helper + trim switches
    ota_pl = clean_primitive(w, "ota_pl", "sky130_fd_pr__pfet_01v8_lvt",
                             dict(w=12.0, l=8.0, nf=6, m=1, guard=1, conn_gates=0, topc=0, botc=1, doports=1))
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
    # 5. Calibrated high_po resistor banks (guard=0 + physical outer ppolyres dummies at 1.48 um pitch)
    r_rs = clean_primitive(w, "bg_rrs10", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=39.200, nx=10, m=1, guard=0))
    r_r2a = clean_primitive(w, "bg_rr2_5", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=37.650, nx=5, m=1, guard=0))
    r_r1 = clean_primitive(w, "bg_rr1", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=39.790, nx=1, m=1, guard=0))
    r_rf = clean_primitive(w, "bg_rrf10", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=33.900, nx=10, m=1, guard=0))
    r_rt = [
        clean_primitive(w, f"bg_rrt{i}", "sky130_fd_pr__res_high_po_0p35", dict(w=1.0, l=lv, nx=1, m=1, guard=0))
        for i, lv in enumerate((1.265, 3.725, 8.645, 18.480, 38.150))
    ]
    # 6. Stacked MIM1+MIM2 primitives (side=22.1965 -> 2.00 pF/site: 3x Cvbg + 1x Cvgi)
    mim_side = 22.1965
    m1_21 = clean_primitive(w, "bg_m1_21", MIM1, dict(w=mim_side, l=mim_side, nx=2, ny=1, stack=1, doports=1))
    m2_21 = clean_primitive(w, "bg_m2_21", MIM2, dict(w=mim_side, l=mim_side, nx=2, ny=1, doports=1))
    m1_11 = clean_primitive(w, "bg_m1_11", MIM1, dict(w=mim_side, l=mim_side, nx=1, ny=1, stack=1, doports=1))
    m2_11 = clean_primitive(w, "bg_m2_11", MIM2, dict(w=mim_side, l=mim_side, nx=1, ny=1, doports=1))

    c = Cell()
    # Macro outer boundary: guard ring centers 0.6..152.8 x 0.6..100.2 (w=0.70 -> ~153.5 x 100.9 = 15,480 um^2 <= 15,500!)
    gx1, gy1 = grid(1.1), grid(0.0)
    gx2, gy2 = grid(152.7), grid(99.85)
    draw_m1_guard_ring(c, gx1, gy1, gx2, gy2, w=0.70)

    # =========================================================================
    # A. TOP CROWN: Xm1..Xm5 (2x12 pfet_lvt, 2D Common-Centroid + 4 outer dummies)
    # =========================================================================
    dx_xm, dy_xm = grid(76.9), grid(84.0)  # y=68.67..99.33 (0.17+ clear of gy2=99.85 & 1.27+ above PNP!)
    c.include(xm_p, dx=dx_xm, dy=dy_xm)
    xm_xs = sd_xs_of(xm_p, "pdiffc", dx_xm)
    xm_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_xm) for r in xm_p.rects["pdiffc"]})
    xm_gxs = sorted({grid(x + dx_xm) for _, x, _, nm in xm_p.labels if nm.startswith("G")})
    xm_gys = sorted({grid(y + dy_xm) for _, _, y, nm in xm_p.labels if nm.startswith("G")})
    xmbx, xmby = xm_p.pins("B")[0]
    xmbx, xmby = grid(xmbx + dx_xm), grid(xmby + dy_xm)

    # Vertical M3 highways (ALL >= 0.80 um apart & strictly LEFT of MIM roof x=98.2!)
    # Note: x_vbg_m3 (87.8) is LEFT of x_vdd_m (95.6) so Cvgi vdd rail (95.6..123) NEVER crosses vbg!
    x_vgi_l = grid(30.2)
    x_s_m3 = grid(31.0)
    x_d_m3 = grid(31.8)
    x_a_m3 = grid(32.6)
    x_vdd_l = grid(33.6)
    x_nb_m3 = grid(34.6)
    x_vg_m3 = grid(35.4)
    x_fcda_m3 = grid(36.2)
    x_nb2_m3 = grid(85.2)
    x_ta_m3 = grid(86.0)
    x_tb_m3 = grid(86.8)
    x_vbg_m3 = grid(87.8)
    x_s_r = grid(92.4)
    x_otada_m3 = grid(93.4)
    x_vgi_r = grid(94.4)
    x_vdd_m = grid(95.6)

    xm_vdd_ys: list[float] = []
    xm_net_ys: dict[str, list[float]] = {k: [] for k in ("nb", "ta", "vbg", "tb", "nb2", "vg")}
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
        c.wire("metal2", [(xm_xs[1], yv), (xm_xs[11], yv)], 0.56)
        for xv in (x_vdd_l, x_vdd_m):
            c.via2(xv, yv)
        xm_vdd_ys.append(yv)

        for nm, col_i in row_net_cols[r_i].items():
            yn = grid(yr + net_y_off[nm])
            cx = xm_xs[col_i]
            tx = net_m3_x[nm]
            c.via1(cx, yn)
            if nm == "vbg":
                # Tie outer dummy drains (xm_xs[0], xm_xs[12]) to vbg (G=S=B=vdd -> HARD OFF, unique L=12 LVS sig!)
                c.via1(xm_xs[0], yn); c.via1(xm_xs[12], yn)
                c.wire("metal2", [(xm_xs[0], yn), (xm_xs[12], yn)], 0.36)
            else:
                c.wire("metal2", [(min(cx, tx), yn), (max(cx, tx), yn)], 0.36)
            c.via2(tx, yn)
            xm_net_ys[nm].append(yn)

        gy = xm_gys[r_i]
        for gx in xm_gxs[1:11]:
            c.via1(gx, gy)
        c.wire("metal2", [(min(x_vg_m3, xm_gxs[1]), gy), (max(x_vg_m3, xm_gxs[10]), gy)], 0.36)
        c.via2(x_vg_m3, gy)
        xm_net_ys["vg"].append(gy)
        # Outer dummy gates -> inner vdd S/D via L-hook +0.65 above gy (0.50+ clear of adjacent active gate M1!)
        c.wire("metal1", [(xm_gxs[0], gy), (grid(xm_xs[1] - 0.65), gy), (grid(xm_xs[1] - 0.65), grid(gy + 0.65)), (xm_xs[1], grid(gy + 0.65))], 0.24)
        c.wire("metal1", [(xm_gxs[11], gy), (grid(xm_xs[11] + 0.65), gy), (grid(xm_xs[11] + 0.65), grid(gy + 0.65)), (xm_xs[11], grid(gy + 0.65))], 0.24)

    # Tie Xm TOP nsubdiffcont guard ring (+15.065, ZERO gate row at top!) directly to xm_xs[11] (vdd)!
    y_xm_top_ring = grid(dy_xm + 15.065)
    c.wire("metal1", [(xm_xs[11], xm_ys[-1]), (xm_xs[11], y_xm_top_ring)], 0.34); c.pad("viali", xm_xs[11], y_xm_top_ring, 0.17)

    # =========================================================================
    # B. COL 1 (x = 1.6 .. 32.8): 3x4 PNP Thermal Island (Top) + Xmv/Xo0..3 (Bot)
    # =========================================================================
    pnp = Cell.read(PNP_MAG)
    pnp.rects.pop("checkpaint", None)
    pnp_em = pnp.pins("Emitter")[0]
    pnp_ba = pnp.pins("Base")[0]
    pnp_co = pnp.pins("Collector")[0]
    pnp.labels.clear()

    # 3 rows x 4 cols: y_pnp0=47.7 -> >= 1.50 um above Xmv N-well (46.1) -> zero nwell.2a!
    pnp_xs = [grid(2.4 + i * 7.2) for i in range(4)]
    pnp_ys = [grid(46.90 + j * 6.85) for j in range(3)]  # 46.90..67.30 (1.37 below Xm 68.67, 1.28 above Xmv 45.62!)
    q1_em = q3_em = (0.0, 0.0)
    for r_i, py in enumerate(pnp_ys):
        y_bc = grid(py + 5.95)
        for c_i, px in enumerate(pnp_xs):
            if c_i == 3 and r_i in (0, 2):
                c.rect("pwell", px, py, grid(px + 6.7), grid(py + 6.7))
                c.rect("psubdiff", grid(px + 0.4), grid(py + 0.4), grid(px + 6.3), grid(py + 6.4))
                c.rect("psubdiffcont", grid(px + 1.2), grid(py + 1.2), grid(px + 5.5), grid(py + 5.5))
                c.rect("locali", grid(px + 0.8), grid(py + 0.8), grid(px + 5.9), grid(py + 6.25))
                c.pad("viali", grid(px + 3.35), y_bc, 0.17)
                c.pad("metal1", grid(px + 3.35), y_bc, 0.40)
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
            elif r_i == 1 and c_i == 3:
                q3_em = (ex, ey)
        c.wire("metal1", [(gx1, y_bc), (grid(pnp_xs[-1] + 5.0), y_bc)], 0.40)

    x_q2_l, x_q2_m, x_q2_r = [grid(x + pnp_em[0]) for x in pnp_xs[:3]]
    y_q2_0, y_q2_1, y_q2_2 = [grid(y + pnp_em[1]) for y in pnp_ys]
    c.wire("metal2", [(x_q2_l, y_q2_0), (x_q2_r, y_q2_0), (x_q2_r, y_q2_2), (x_q2_l, y_q2_2), (x_q2_l, y_q2_0)], 0.40)

    # Xmv + Xo0..3 (5x6 pfet_lvt: dy_xmv=23.7 -> y=1.13..46.27, >= 1.43 um below PNP!)
    dx_xmv, dy_xmv = grid(15.6), grid(23.1)  # bot 0.53 (0.18 clear of gy1=0.0? Wait: gy1 top=0.35 -> 0.53 is 0.18! Use 23.05? No: 0.53-0.35=0.18 > 0.13!)
    c.include(xmv_p, dx=dx_xmv, dy=dy_xmv)
    mv_xs = sd_xs_of(xmv_p, "pdiffc", dx_xmv)
    mv_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_xmv) for r in xmv_p.rects["pdiffc"]})
    mv_gxs = sorted({grid(x + dx_xmv) for _, x, _, nm in xmv_p.labels if nm.startswith("G")})
    mv_gys = sorted({grid(y + dy_xmv) for _, _, y, nm in xmv_p.labels if nm.startswith("G")})
    mvbx, mvby = xmv_p.pins("B")[0]
    mvbx, mvby = grid(mvbx + dx_xmv), grid(mvby + dy_xmv)

    i_port_xs = [grid(mv_xs[2] + k * 2.2) for k in range(4)]
    mv_row_names = ["i0", "i1", "s", "i2", "i3"]
    mv_row_m3_x = {"i0": i_port_xs[0], "i1": i_port_xs[1], "s": x_s_m3, "i2": i_port_xs[2], "i3": i_port_xs[3]}
    s_ys: list[float] = []
    for r_i, yr in enumerate(mv_ys):
        yv = grid(yr + 2.2); yd = grid(yr - 1.4)
        for idx in (1, 3, 5):
            c.via1(mv_xs[idx], yv)
        c.wire("metal2", [(mv_xs[1], yv), (x_vdd_l, yv)], 0.44)
        c.via2(x_vdd_l, yv); xm_vdd_ys.append(yv)
        for idx in (2, 4):
            c.via1(mv_xs[idx], yd)
        rnm = mv_row_names[r_i]
        tx = mv_row_m3_x[rnm]
        c.wire("metal2", [(min(mv_xs[2], tx), yd), (max(mv_xs[4], tx), yd)], 0.36)
        c.via2(tx, yd)
        if rnm.startswith("i"):
            c.wire("metal3", [(tx, gy1), (tx, yd)], 0.36)
        else:
            s_ys.append(yd)
        gy = mv_gys[r_i]
        for gx in mv_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(mv_gxs[1], gy), (x_vgi_l, gy)], 0.32)
        c.via2(x_vgi_l, gy)
        # Outer dummies: G=vdd (L-hook +0.65 above gy -> 0 met1.2!), S=vdd, D=vss (M2/M3 -> 0 met1.2!)
        c.wire("metal1", [(mv_gxs[0], gy), (grid(mv_xs[1] - 0.65), gy), (grid(mv_xs[1] - 0.65), grid(gy + 0.65)), (mv_xs[1], grid(gy + 0.65))], 0.24)
        c.wire("metal1", [(mv_gxs[5], gy), (grid(mv_xs[5] + 0.65), gy), (grid(mv_xs[5] + 0.65), grid(gy + 0.65)), (mv_xs[5], grid(gy + 0.65))], 0.24)
        y_mvd = grid(yr + 0.4)
        c.via1(mv_xs[0], y_mvd); c.wire("metal2", [(gx1, y_mvd), (mv_xs[0], y_mvd)], 0.30); c.via1(gx1, y_mvd)
        c.via1(mv_xs[6], y_mvd); c.via2(mv_xs[6], y_mvd)
    c.wire("metal3", [(mv_xs[6], gy1), (mv_xs[6], grid(mv_ys[-1] + 0.4))], 0.36)
    c.via2(mv_xs[6], gy1); c.via1(mv_xs[6], gy1)
    # Tie Xmv TOP nsubdiffcont guard ring (+22.305, ZERO gate row at top!) directly to mv_xs[1] (vdd)!
    y_mv_top_ring = grid(dy_xmv + 22.305)
    c.wire("metal1", [(mv_xs[1], mv_ys[-1]), (mv_xs[1], y_mv_top_ring)], 0.30); c.pad("viali", mv_xs[1], y_mv_top_ring, 0.17)
    c.wire("metal3", [(x_vgi_l, gy1), (x_vgi_l, mv_gys[-1])], 0.36)

    # =========================================================================
    # C. COL 2 (x = 34.5 .. 88.0): Single-Stage Folded-Cascode OTA (serdes_bg_fcota_v2)
    # =========================================================================
    dx_fab, dy_fab = grid(60.5), grid(51.0)  # x=34.8..86.2, y=37.67..64.33 (opens y=64.4..68.8 for Xsp+Xbd!)
    c.include(fc_fab, dx=dx_fab, dy=dy_fab)
    fab_xs = sd_xs_of(fc_fab, "pdiffc", dx_fab)
    fab_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_fab) for r in fc_fab.rects["pdiffc"]})
    fab_gxs = sorted({grid(x + dx_fab) for _, x, _, nm in fc_fab.labels if nm.startswith("G")})
    fab_gys = sorted({grid(y + dy_fab) for _, _, y, nm in fc_fab.labels if nm.startswith("G")})
    fabbx, fabby = fc_fab.pins("B")[0]
    fabbx, fabby = grid(fabbx + dx_fab), grid(fabby + dy_fab)

    x_fa_m3 = grid(56.0)
    x_fb_m3 = grid(57.0)
    x_vbps_m3 = grid(64.8)
    x_vbpc_m3 = grid(63.8)
    x_vbnc_m3 = grid(84.2)
    x_fctail_m3 = grid(79.0)
    x_st_m3 = grid(82.4)

    fa_ys: list[float] = []
    fb_ys: list[float] = []
    vbps_ys: list[float] = []
    vbpc_ys: list[float] = []
    for r_i, yr in enumerate(fab_ys):
        yv = grid(yr + 3.2); yfa = grid(yr + 0.4); yfb = grid(yr - 2.2)
        for idx in (0, 1, 3, 5, 6):
            c.via1(fab_xs[idx], yv)
        c.wire("metal2", [(x_vdd_l, yv), (fab_xs[6], yv)], 0.44)
        c.via2(x_vdd_l, yv); xm_vdd_ys.append(yv)
        fa_col, fb_col = (2, 4) if r_i == 0 else (4, 2)
        c.via1(fab_xs[fa_col], yfa)
        c.wire("metal2", [(min(fab_xs[fa_col], x_fa_m3), yfa), (max(fab_xs[fa_col], x_fa_m3), yfa)], 0.34)
        c.via2(x_fa_m3, yfa); fa_ys.append(yfa)
        c.via1(fab_xs[fb_col], yfb)
        c.wire("metal2", [(min(fab_xs[fb_col], x_fb_m3), yfb), (max(fab_xs[fb_col], x_fb_m3), yfb)], 0.34)
        c.via2(x_fb_m3, yfb); fb_ys.append(yfb)
        gy = fab_gys[r_i]
        for gx in fab_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(min(fab_gxs[1], x_vbps_m3), gy), (max(fab_gxs[4], x_vbps_m3), gy)], 0.32)
        c.via2(x_vbps_m3, gy); vbps_ys.append(gy)
        for gx, sx in ((fab_gxs[0], fab_xs[0]), (fab_gxs[5], fab_xs[6])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.28)
    c.body_contact(fabbx, fabby)
    y_fabby = grid(fabby - 0.65)
    c.wire("metal2", [(x_vdd_l, y_fabby), (fabbx, y_fabby), (fabbx, fabby)], 0.36)
    c.via2(x_vdd_l, y_fabby); xm_vdd_ys.append(y_fabby)

    # C2. Xpca + Xpcb + Xpb (merge same-net vdd N-wells cleanly with fc_fab -> zero nwell.2a!)
    dx_pca, dy_pc = grid(41.2), grid(30.8)   # x=34.7..47.7, y=23.9..37.7
    dx_pcb = grid(55.4)                      # x=48.9..61.9
    dx_pb = grid(72.0)                       # x=63.3..81.5
    c.rect("nwell", grid(34.7), grid(23.85), grid(81.5), grid(39.5))
    for prim_pc, dx_p, s_x, d_x, s_ys, d_ys, ys_s, ys_d in (
        (fc_pc, dx_pca, x_fb_m3, x_fcda_m3, fb_ys, None, grid(dy_pc + 2.4), grid(dy_pc - 1.2)),
        (fc_pc, dx_pcb, x_fa_m3, x_vg_m3, fa_ys, xm_net_ys["vg"], grid(dy_pc + 4.0), grid(dy_pc - 4.0)),
    ):
        c.include(prim_pc, dx=dx_p, dy=dy_pc)
        pxs = sd_xs_of(prim_pc, "pdiffc", dx_p)
        pgx = grid(dx_p + prim_pc.pins("G")[0][0]); pgy = grid(dy_pc + prim_pc.pins("G")[0][1])
        pbx, pby = prim_pc.pins("B")[0]; pbx, pby = grid(pbx + dx_p), grid(pby + dy_pc)
        for idx in (0, 2, 4):
            c.via1(pxs[idx], ys_s)
        c.wire("metal2", [(min(pxs[0], s_x), ys_s), (max(pxs[4], s_x), ys_s)], 0.34)
        c.via2(s_x, ys_s); s_ys.append(ys_s)
        for idx in (1, 3):
            c.via1(pxs[idx], ys_d)
        c.wire("metal2", [(min(pxs[1], d_x), ys_d), (max(pxs[3], d_x), ys_d)], 0.34)
        c.via2(d_x, ys_d)
        if d_ys is not None:
            d_ys.append(ys_d)
        c.via1(pgx, pgy)
        c.wire("metal2", [(min(pgx, x_vbpc_m3), pgy), (max(pgx, x_vbpc_m3), pgy)], 0.30)
        c.via2(x_vbpc_m3, pgy); vbpc_ys.append(pgy)
        # Connect fc_pc exact top nsubdiffcont ring (+6.655) up to fc_fab exact bottom ring (fabby)
        x_pc_gr = grid(dx_p + prim_pc.bbox()[0] + 0.35)
        y_pc_ring = grid(dy_pc + 6.655)
        c.wire("metal1", [(x_pc_gr, y_pc_ring), (x_pc_gr, fabby)], 0.34)
        c.pad("viali", x_pc_gr, y_pc_ring, 0.17); c.pad("viali", x_pc_gr, fabby, 0.17)

    c.include(fc_pb, dx=dx_pb, dy=dy_pc)
    pb_xs = sd_xs_of(fc_pb, "pdiffc", dx_pb)
    pb_gx = grid(dx_pb + fc_pb.pins("G")[0][0]); pb_gy = grid(dy_pc + fc_pb.pins("G")[0][1])
    pb_bx, pb_by = fc_pb.pins("B")[0]; pb_bx, pb_by = grid(pb_bx + dx_pb), grid(pb_by + dy_pc)
    y_pb_vdd = grid(dy_pc + 4.8)  # 35.60: aligned with Xpbc vdd & well above pbc_gy (33.16)!
    y_pb_d = grid(dy_pc + 0.4)    # 31.20: well above sn_gy (30.32) & below pbc_gy (33.16)!
    for idx in (0, 2):
        c.via1(pb_xs[idx], y_pb_vdd)
    c.wire("metal2", [(pb_xs[0], y_pb_vdd), (x_vdd_m, y_pb_vdd)], 0.34)
    c.via2(x_vdd_m, y_pb_vdd); xm_vdd_ys.append(y_pb_vdd)
    c.via1(pb_xs[1], y_pb_d)
    c.wire("metal2", [(x_vbps_m3, y_pb_d), (pb_xs[1], y_pb_d)], 0.32)
    c.via2(x_vbps_m3, y_pb_d); vbps_ys.append(y_pb_d)
    c.via1(pb_gx, pb_gy)
    c.wire("metal2", [(x_vbps_m3, pb_gy), (pb_gx, pb_gy)], 0.30)
    c.via2(x_vbps_m3, pb_gy); vbps_ys.append(pb_gy)
    y_pb_ring = grid(dy_pc + 6.655)
    c.wire("metal1", [(pb_xs[2], y_pb_ring), (pb_xs[2], y_pb_vdd)], 0.30); c.pad("viali", pb_xs[2], y_pb_ring, 0.17)

    # C3. Xa/Xb input pair (w=6, l=4, nf=10)
    dx_ab, dy_ab = grid(56.4), grid(20.25)  # clears fc_pc N-well (23.85) with 0 diff/tap.9, li.3, licon.14!
    c.include(fc_ab, dx=dx_ab, dy=dy_ab)
    ab_xs = sd_xs_of(fc_ab, "ndiffc", dx_ab)
    ab_gpts = gate_pts_of(fc_ab, dx_ab, dy_ab)
    ab_gy = ab_gpts[0][1]
    # Planar non-crossing M2 tracks between y_nbp_g (~18.12) and ab_gy (~23.48):
    y_ab_t = grid(19.00); y_ab_fa = grid(19.75); y_ab_fb = grid(20.50)
    for idx in (1, 3, 5, 7, 9):
        c.via1(ab_xs[idx], y_ab_t)
    c.wire("metal2", [(ab_xs[1], y_ab_t), (x_fctail_m3, y_ab_t)], 0.34)
    c.via2(x_fctail_m3, y_ab_t)
    for idx in (2, 8):
        c.via1(ab_xs[idx], y_ab_fa)
    c.wire("metal2", [(ab_xs[2], y_ab_fa), (ab_xs[8], y_ab_fa)], 0.32)
    c.via2(x_fa_m3, y_ab_fa); fa_ys.append(y_ab_fa)
    for idx in (4, 6):
        c.via1(ab_xs[idx], y_ab_fb)
    c.wire("metal2", [(ab_xs[4], y_ab_fb), (ab_xs[6], y_ab_fb)], 0.32)
    c.via2(x_fb_m3, y_ab_fb); fb_ys.append(y_ab_fb)
    y_g_ta = grid(ab_gy - 0.54); y_g_tb = grid(ab_gy - 1.07)
    for idx in (1, 2, 7, 8):
        gx = ab_gpts[idx][0]; c.via1(gx, ab_gy); c.wire("metal2", [(gx, ab_gy), (gx, y_g_ta)], 0.32)
    c.wire("metal2", [(ab_gpts[1][0], y_g_ta), (x_ta_m3, y_g_ta)], 0.30)
    c.via2(x_ta_m3, y_g_ta); xm_net_ys["ta"].append(y_g_ta)
    for idx in (3, 4, 5, 6):
        gx = ab_gpts[idx][0]; c.via1(gx, ab_gy); c.via2(gx, ab_gy)
        c.wire("metal3", [(gx, ab_gy), (gx, y_g_tb)], 0.34); c.via2(gx, y_g_tb)
    c.wire("metal2", [(ab_gpts[3][0], y_g_tb), (x_tb_m3, y_g_tb)], 0.30)
    c.via2(x_tb_m3, y_g_tb); xm_net_ys["tb"].append(y_g_tb)
    for gx, sx in ((ab_gpts[0][0], ab_xs[0]), (ab_gpts[9][0], ab_xs[10])):
        c.wire("metal1", [(gx, ab_gy), (sx, ab_gy), (sx, dy_ab)], 0.24)

    # C4. Xnca + Xncb (separate yd_n so fc_da & vg NEVER overlap!)
    dx_nca, dy_nc = grid(44.8), grid(14.2)
    dx_ncb = grid(66.8)
    x_na_m3 = grid(44.8); x_nbn_m3 = grid(66.8)
    for dx_n, d_x, s_x, d_ys, yd_n in (
        (dx_nca, x_fcda_m3, x_na_m3, None, grid(dy_nc + 0.6)),
        (dx_ncb, x_vg_m3, x_nbn_m3, xm_net_ys["vg"], grid(dy_nc + 1.4)),
    ):
        c.include(fc_nc, dx=dx_n, dy=dy_nc)
        nxs = sd_xs_of(fc_nc, "ndiffc", dx_n)
        ngx = grid(dx_n + fc_nc.pins("G")[0][0]); ngy = grid(dy_nc + fc_nc.pins("G")[0][1])
        ys_n = grid(dy_nc - 1.0)
        for idx in (1, 3):
            c.via1(nxs[idx], yd_n)
        c.wire("metal2", [(min(nxs[1], d_x), yd_n), (max(nxs[3], d_x), yd_n)], 0.30)
        c.via2(d_x, yd_n)
        if d_ys is not None:
            d_ys.append(yd_n)
        for idx in (0, 2, 4):
            c.via1(nxs[idx], ys_n)
        c.wire("metal2", [(min(nxs[0], s_x), ys_n), (max(nxs[4], s_x), ys_n)], 0.32)
        c.via2(s_x, ys_n)
        c.via1(ngx, ngy)
        c.wire("metal2", [(min(ngx, x_vbnc_m3), ngy), (max(ngx, x_vbnc_m3), ngy)], 0.28)
        c.via2(x_vbnc_m3, ngy)

    # C5. Xna/Xnb (2x6 nfet w=4, l=8): sources tied straight to gy1 / y_col2_ptap on M1 (zero vertical M2!)
    dx_nm, dy_nm = grid(59.8), grid(6.4)
    c.include(fc_nm, dx=dx_nm, dy=dy_nm)
    nm_xs = sd_xs_of(fc_nm, "ndiffc", dx_nm)
    nm_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_nm) for r in fc_nm.rects["ndiffc"]})
    nm_gxs = sorted({grid(x + dx_nm) for _, x, _, nm in fc_nm.labels if nm.startswith("G")})
    nm_gys = sorted({grid(y + dy_nm) for _, _, y, nm in fc_nm.labels if nm.startswith("G")})
    na_ys = [grid(dy_nc - 1.0)]
    nbn_ys = [grid(dy_nc - 1.0)]
    fcda_ys = [grid(dy_pc - 1.2), grid(dy_nc + 0.6)]
    y_col2_ptap = grid(11.45)
    for r_i, yr in enumerate(nm_ys):
        ys_v = grid(yr - 1.1); yna = grid(yr + 0.1); ynbn = grid(yr + 1.1)
        for idx in (0, 1, 3, 5, 6):
            c.via1(nm_xs[idx], ys_v)
        c.wire("metal2", [(nm_xs[0], ys_v), (nm_xs[6], ys_v)], 0.34)
        if r_i == 0:
            c.wire("metal1", [(nm_xs[0], yr), (nm_xs[0], gy1)], 0.32)
            c.wire("metal1", [(nm_xs[6], yr), (nm_xs[6], gy1)], 0.32)
        else:
            c.wire("metal1", [(nm_xs[0], yr), (nm_xs[0], y_col2_ptap)], 0.32)
            c.wire("metal1", [(nm_xs[6], yr), (nm_xs[6], y_col2_ptap)], 0.32)
        na_col, nbn_col = (2, 4) if r_i == 0 else (4, 2)
        c.via1(nm_xs[na_col], yna)
        c.wire("metal2", [(min(nm_xs[na_col], x_na_m3), yna), (max(nm_xs[na_col], x_na_m3), yna)], 0.30)
        c.via2(x_na_m3, yna); na_ys.append(yna)
        c.via1(nm_xs[nbn_col], ynbn)
        c.wire("metal2", [(min(nm_xs[nbn_col], x_nbn_m3), ynbn), (max(nm_xs[nbn_col], x_nbn_m3), ynbn)], 0.30)
        c.via2(x_nbn_m3, ynbn); nbn_ys.append(ynbn)
        gy = nm_gys[r_i]
        for gx in nm_gxs[1:5]:
            c.via1(gx, gy)
        c.wire("metal2", [(x_fcda_m3, gy), (nm_gxs[4], gy)], 0.30)
        c.via2(x_fcda_m3, gy); fcda_ys.append(gy)
        for gx, sx in ((nm_gxs[0], nm_xs[0]), (nm_gxs[5], nm_xs[6])):
            c.wire("metal1", [(gx, gy), (sx, gy), (sx, yr)], 0.24)

    c.rect("pwell", grid(34.0), grid(y_col2_ptap - 0.5), grid(88.0), grid(y_col2_ptap + 0.5))
    c.rect("psubdiff", grid(34.5), grid(y_col2_ptap - 0.22), grid(87.5), grid(y_col2_ptap + 0.22))
    c.rect("psubdiffcont", grid(34.8), grid(y_col2_ptap - 0.085), grid(87.2), grid(y_col2_ptap + 0.085))
    c.rect("locali", grid(34.5), grid(y_col2_ptap - 0.22), grid(87.5), grid(y_col2_ptap + 0.22))
    c.rect("metal1", grid(34.5), grid(y_col2_ptap - 0.24), grid(87.5), grid(y_col2_ptap + 0.24))
    for i in range(6):
        c.pad("viali", grid(36.0 + i * 10.0), y_col2_ptap, 0.17)
    c.wire("metal1", [(ab_xs[0], dy_ab), (ab_xs[0], y_col2_ptap)], 0.24)
    c.wire("metal1", [(ab_xs[10], dy_ab), (ab_xs[10], y_col2_ptap)], 0.24)

    # C6. Xt (fc_tail, nb, vss), Xnbp (vbp_src, nb, vss), Xnbpc (vbp_c, nb, vss)
    dx_fct, dy_fct = grid(82.8), grid(19.80)  # bot diff 18.30 (1.05 above fc_nbp poly 17.25!), ft_gy ~ 21.42 (0.73 below y_g_tb!)
    c.include(fc_t, dx=dx_fct, dy=dy_fct)
    ft_xs = sd_xs_of(fc_t, "ndiffc", dx_fct)
    ft_gx, ft_gy = grid(dx_fct + fc_t.pins("G")[0][0]), grid(dy_fct + fc_t.pins("G")[0][1])
    # Tie fc_t sources (ft_xs[0], ft_xs[2]) via M2 at y_fct_s=20.65 directly onto x=83.3 vss M3 strap
    y_fct_s = grid(20.65)
    for sx in (ft_xs[0], ft_xs[2]):
        c.via1(sx, y_fct_s)
    c.wire("metal2", [(ft_xs[0], y_fct_s), (ft_xs[2], y_fct_s)], 0.28)
    c.via2(grid(83.3), y_fct_s)
    y_fct_d = grid(19.75)
    c.via1(ft_xs[1], y_fct_d)
    c.wire("metal2", [(x_fctail_m3, y_fct_d), (ft_xs[1], y_fct_d)], 0.30); c.via2(x_fctail_m3, y_fct_d)
    c.wire("metal3", [(x_fctail_m3, min(y_ab_t, y_fct_d)), (x_fctail_m3, max(y_ab_t, y_fct_d))], 0.36)
    c.via1(ft_gx, ft_gy); c.wire("metal2", [(x_nb_m3, ft_gy), (ft_gx, ft_gy)], 0.30)
    c.via2(x_nb_m3, ft_gy); xm_net_ys["nb"].append(ft_gy)

    dx_nbp, dy_nbp = grid(80.6), grid(15.3)  # poly top 17.25 (1.05 below fc_t!), y_nbp_g ~ 16.92 (0.60 above ngy=16.32!)
    dx_nbpc = grid(85.8)
    c.include(fc_nbp, dx=dx_nbp, dy=dy_nbp)
    c.include(fc_nbp, dx=dx_nbpc, dy=dy_nbp)
    for dx_b, d_m3, d_list, y_d_b in (
        (dx_nbp, x_vbps_m3, vbps_ys, grid(14.15)),
        (dx_nbpc, x_vbpc_m3, vbpc_ys, grid(14.75)),
    ):
        bxs = sd_xs_of(fc_nbp, "ndiffc", dx_b)
        bgx, bgy = grid(dx_b + fc_nbp.pins("G")[0][0]), grid(dy_nbp + fc_nbp.pins("G")[0][1])
        c.wire("metal1", [(bxs[0], dy_nbp), (bxs[0], y_col2_ptap)], 0.24)
        c.via1(bxs[1], y_d_b)
        c.wire("metal2", [(min(bxs[1], d_m3), y_d_b), (max(bxs[1], d_m3), y_d_b)], 0.28)
        c.via2(d_m3, y_d_b); d_list.append(y_d_b)
        c.via1(bgx, bgy)
    y_nbp_g = grid(dy_nbp + fc_nbp.pins("G")[0][1])
    c.wire("metal2", [(x_nb_m3, y_nbp_g), (grid(dx_nbpc + fc_nbp.pins("G")[0][0]), y_nbp_g)], 0.28)
    c.via2(x_nb_m3, y_nbp_g); xm_net_ys["nb"].append(y_nbp_g)

    # C7. Xpbc (vbp_c, vbp_c, vdd, vdd) at (85.2, 34.0), merged N-well with Xpb -> zero nwell.2a!
    dx_pbc, dy_pbc = grid(84.6), grid(34.8)  # top 37.22 (0.45 below fc_fab) & drain/gate >=34.0 (0.80 above Xpb vdd 33.2!)
    c.include(fc_pbc, dx=dx_pbc, dy=dy_pbc)
    c.rect("nwell", grid(79.5), grid(30.8), grid(87.4), grid(39.5))
    pbc_xs = sd_xs_of(fc_pbc, "pdiffc", dx_pbc)
    pbc_gx, pbc_gy = grid(dx_pbc + fc_pbc.pins("G")[0][0]), grid(dy_pbc + fc_pbc.pins("G")[0][1])
    pbc_bx, pbc_by = fc_pbc.pins("B")[0]; pbc_bx, pbc_by = grid(pbc_bx + dx_pbc), grid(pbc_by + dy_pbc)
    c.via1(pbc_xs[0], grid(dy_pbc + 0.8))
    c.wire("metal2", [(pbc_xs[0], grid(dy_pbc + 0.8)), (x_vdd_m, grid(dy_pbc + 0.8))], 0.32)
    c.via2(x_vdd_m, grid(dy_pbc + 0.8)); xm_vdd_ys.append(grid(dy_pbc + 0.8))
    c.body_contact(pbc_bx, pbc_by)
    c.wire("metal2", [(pbc_bx, pbc_by), (x_vdd_m, pbc_by)], 0.30); c.via2(x_vdd_m, pbc_by); xm_vdd_ys.append(pbc_by)
    c.via1(pbc_xs[1], grid(dy_pbc - 0.8)); c.via1(pbc_gx, pbc_gy)
    c.wire("metal2", [(x_vbpc_m3, pbc_gy), (pbc_gx, pbc_gy), (pbc_xs[1], pbc_gy), (pbc_xs[1], grid(dy_pbc - 0.8))], 0.28)
    c.via2(x_vbpc_m3, pbc_gy); vbpc_ys.append(pbc_gy)

    # C8. Xsn (st, nb, vss) & Xsu (vg, st, vss) at (83.2, 27.8) & (86.6, 27.8) + local P+ tap (zero LU.2!)
    dx_sn, dy_snsu = grid(83.2), grid(29.2)
    dx_su = grid(86.6)
    c.include(st_sn, dx=dx_sn, dy=dy_snsu)
    c.include(st_su, dx=dx_su, dy=dy_snsu)
    sn_xs = sd_xs_of(st_sn, "ndiffc", dx_sn)
    sn_gx, sn_gy = grid(dx_sn + st_sn.pins("G")[0][0]), grid(dy_snsu + st_sn.pins("G")[0][1])
    su_xs = sd_xs_of(st_su, "ndiffc", dx_su)
    su_gx, su_gy = grid(dx_su + st_su.pins("G")[0][0]), grid(dy_snsu + st_su.pins("G")[0][1])
    y_st_ptap = grid(26.6)
    c.rect("pwell", grid(81.5), grid(y_st_ptap - 0.5), grid(88.2), grid(y_st_ptap + 0.5))
    c.rect("psubdiff", grid(82.0), grid(y_st_ptap - 0.22), grid(87.8), grid(y_st_ptap + 0.22))
    c.rect("psubdiffcont", grid(82.3), grid(y_st_ptap - 0.085), grid(87.5), grid(y_st_ptap + 0.085))
    c.rect("locali", grid(82.0), grid(y_st_ptap - 0.22), grid(87.8), grid(y_st_ptap + 0.22))
    c.rect("metal1", grid(82.0), grid(y_st_ptap - 0.24), grid(87.8), grid(y_st_ptap + 0.24))
    c.pad("viali", grid(84.8), y_st_ptap, 0.17)
    c.wire("metal1", [(sn_xs[0], dy_snsu), (sn_xs[0], y_st_ptap)], 0.24)
    c.wire("metal1", [(su_xs[0], dy_snsu), (su_xs[0], y_st_ptap)], 0.24)
    c.via1(grid(83.3), y_st_ptap); c.via2(grid(83.3), y_st_ptap)
    c.wire("metal3", [(grid(83.3), y_col2_ptap), (grid(83.3), y_st_ptap)], 0.34)
    c.via2(grid(83.3), y_col2_ptap); c.via1(grid(83.3), y_col2_ptap)
    c.via1(sn_gx, sn_gy); c.wire("metal2", [(x_nb_m3, sn_gy), (sn_gx, sn_gy)], 0.28)
    c.via2(x_nb_m3, sn_gy); xm_net_ys["nb"].append(sn_gy)
    # Xsn drain (st) -> Xsu gate (st) at y_st_lo=29.35 (0.97 below sn_gy=30.32 & 0.85 above y_su_vg=28.50!)
    # Xsu drain (vg) drops to y_su_vg=28.50 (0.70 ABOVE dy_nbc=27.80 -> NEVER crosses vbn_c! & 1.70 above Xpcb 26.80!)
    y_st_lo = grid(29.35)
    y_su_vg = grid(28.50)
    c.via1(sn_xs[1], y_st_lo); c.via1(su_gx, su_gy)
    c.wire("metal2", [(x_st_m3, y_st_lo), (su_gx, y_st_lo)], 0.26)
    c.wire("metal2", [(su_gx, y_st_lo), (su_gx, su_gy)], 0.32)
    c.via2(x_st_m3, y_st_lo)
    c.via1(su_xs[1], dy_snsu)
    c.wire("metal2", [(su_xs[1], dy_snsu), (su_xs[1], y_su_vg), (x_vg_m3, y_su_vg)], 0.26)
    c.via2(x_vg_m3, y_su_vg); xm_net_ys["vg"].append(y_su_vg)

    # C9. Xsp (0.42/20) + Xbd (6/4) + local P+ tap in top strip y = 64.6..68.4 (clear of fc_fab 64.33 & Xm 68.47!)
    dx_sp, dy_sp = grid(46.5), grid(66.85)
    c.include(st_sp, dx=dx_sp, dy=dy_sp)
    sp_nw = st_sp.rects["nwell"][0]
    c.rect("nwell", grid(sp_nw[0] + dx_sp), grid(sp_nw[1] + dy_sp), grid(sp_nw[2] + dx_sp), grid(70.5))
    sp_xs = sd_xs_of(st_sp, "pdiffc", dx_sp)
    sp_gx, sp_gy = grid(dx_sp + st_sp.pins("G")[0][0]), grid(dy_sp + st_sp.pins("G")[0][1])
    # Start M1 extension at dy_sp + 0.18 -> y_sp_sd = 67.20 (0.42 clear of G M1 & 0.48 below Xbd y_bd_d0=67.68!)
    y_sp_sd0 = grid(dy_sp + 0.18)
    y_sp_sd = grid(dy_sp + 0.35)
    c.wire("metal1", [(sp_xs[0], y_sp_sd0), (sp_xs[0], y_sp_sd)], 0.24); c.via1(sp_xs[0], y_sp_sd)
    c.wire("metal2", [(x_vdd_l, y_sp_sd), (sp_xs[0], y_sp_sd)], 0.28); c.via2(x_vdd_l, y_sp_sd); xm_vdd_ys.append(y_sp_sd)
    c.wire("metal1", [(sp_xs[1], y_sp_sd0), (sp_xs[1], y_sp_sd)], 0.24); c.via1(sp_xs[1], y_sp_sd)
    c.wire("metal2", [(sp_xs[1], y_sp_sd), (x_st_m3, y_sp_sd)], 0.28)
    c.via2(x_st_m3, y_sp_sd)
    c.wire("metal3", [(x_st_m3, y_st_lo), (x_st_m3, y_sp_sd)], 0.34)

    # Local P+ substrate tap between Xsp (57.5) & Xbd (67.6) -> feeds Xsp gate + Xbd sources + clears LU.2!
    x_top_ptap = grid(62.5); y_top_ptap = grid(65.85)
    c.rect("pwell", grid(59.2), grid(y_top_ptap - 0.45), grid(65.8), grid(y_top_ptap + 0.45))
    c.rect("psubdiff", grid(59.6), grid(y_top_ptap - 0.20), grid(65.4), grid(y_top_ptap + 0.20))
    c.rect("psubdiffcont", grid(59.9), grid(y_top_ptap - 0.085), grid(65.1), grid(y_top_ptap + 0.085))
    c.rect("locali", grid(59.6), grid(y_top_ptap - 0.20), grid(65.4), grid(y_top_ptap + 0.20))
    c.rect("metal1", grid(59.6), grid(y_top_ptap - 0.22), grid(65.4), grid(y_top_ptap + 0.22))
    c.pad("viali", x_top_ptap, y_top_ptap, 0.17)
    c.via1(x_top_ptap, y_top_ptap); c.via2(x_top_ptap, y_top_ptap)
    c.wire("metal3", [(x_top_ptap, y_top_ptap), (x_top_ptap, gy2)], 0.36)
    c.via2(x_top_ptap, gy2); c.via1(x_top_ptap, gy2)
    y_sp_lo = grid(sp_gy - 0.60)
    c.wire("metal1", [(sp_gx, sp_gy), (sp_gx, y_sp_lo)], 0.22); c.via1(sp_gx, y_sp_lo)
    c.wire("metal2", [(sp_gx, y_sp_lo), (x_top_ptap, y_sp_lo)], 0.26)
    c.via1(x_top_ptap, y_sp_lo); c.wire("metal1", [(x_top_ptap, y_sp_lo), (x_top_ptap, y_top_ptap)], 0.26)

    # Xbd (nb, nb, vss, vss): 8.87 x 3.57 at (72.0, 66.35)
    dx_bd, dy_bd = grid(72.0), grid(66.35)
    c.include(fc_t, dx=dx_bd, dy=dy_bd)
    bd_xs = sd_xs_of(fc_t, "ndiffc", dx_bd)
    bd_gx, bd_gy = grid(dx_bd + fc_t.pins("G")[0][0]), grid(dy_bd + fc_t.pins("G")[0][1])
    # Tie Xbd sources (bd_xs[0], bd_xs[2]) to x_top_ptap on M2 at y=65.85
    y_bd_s = grid(dy_bd - 0.50)
    for sx in (bd_xs[0], bd_xs[2]):
        c.via1(sx, y_bd_s)
    c.wire("metal2", [(x_top_ptap, y_bd_s), (bd_xs[2], y_bd_s)], 0.26)
    c.via1(x_top_ptap, y_bd_s); c.wire("metal1", [(x_top_ptap, y_bd_s), (x_top_ptap, y_top_ptap)], 0.26)
    # Bridge Xbd drain M1 solidly up to gate M1 (same net nb, full width -> 0 met1.2!), and route nb on M2 at bd_gy!
    c.rect("metal1", grid(bd_xs[1] - 0.30), grid(67.40), grid(bd_xs[1] + 0.30), grid(68.15))
    c.via1(bd_gx, bd_gy)
    c.wire("metal2", [(bd_gx, bd_gy), (x_nb_m3, bd_gy)], 0.28)
    c.via2(x_nb_m3, bd_gy); xm_net_ys["nb"].append(bd_gy)

    # =========================================================================
    # D. COL 3 (x = 89.0 .. 152.2): Precision Resistor Bank + ota_v2 + Xs4..0 + 2x2 Stacked MIM Roof
    # =========================================================================
    dx_rs, dy_rs = grid(97.0), grid(46.0)
    c.include(r_rs, dx=dx_rs, dy=dy_rs)
    _add_outer_ppolyres_dummies(c, r_rs, dx_rs, dy_rs)
    rs_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_rs) for r in r_rs.rects["viali"]})
    rs_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_rs) for r in r_rs.rects["viali"]})
    rs_yb, rs_yt = rs_ys[0], rs_ys[-1]
    # Interdigitated ABABABABAB jumpers: Xrsa (0,2,4,6,8) on METAL1 (±1.35 clear of r_rs M1 pads ±1.05!), Xrsb (1,3,5,7,9) on METAL2!
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

    dx_r2l = grid(111.4); dx_r1 = grid(115.9); dx_r2r = grid(120.4)
    dy_r12 = grid(46.0)
    c.include(r_r2a, dx=dx_r2l, dy=dy_r12)
    c.include(r_r1, dx=dx_r1, dy=dy_r12)
    c.include(r_r2a, dx=dx_r2r, dy=dy_r12)
    r2l_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_r2l) for r in r_r2a.rects["viali"]})
    r2r_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_r2r) for r in r_r2a.rects["viali"]})
    r2_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_r12) for r in r_r2a.rects["viali"]})
    r1_x = sorted({grid((r[0] + r[2]) / 2.0 + dx_r1) for r in r_r1.rects["viali"]})[0]
    r1_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_r12) for r in r_r1.rects["viali"]})
    r2_body = r_r2a.rects["ppolyres"][0]; r2_bw = grid(r2_body[2] - r2_body[0])
    for xd_c in (grid(r2l_xs[0] - 1.48), grid(r2r_xs[-1] + 1.48)):
        c.rect("ppolyres", grid(xd_c - r2_bw / 2), grid(r2_body[1] + dy_r12),
               grid(xd_c + r2_bw / 2), grid(r2_body[3] + dy_r12))
    # r2l enters at top (0) -> exits at bot (4); r2r enters at bot (0) -> exits at top (4) (10-bar series chain!)
    for i in range(4):
        yj_l = r2_ys[0] if i % 2 == 0 else r2_ys[-1]
        yj_r = r2_ys[-1] if i % 2 == 0 else r2_ys[0]
        c.wire("metal1", [(r2l_xs[i], yj_l), (r2l_xs[i + 1], yj_l)], 0.40)
        c.wire("metal1", [(r2r_xs[i], yj_r), (r2r_xs[i + 1], yj_r)], 0.40)
    y_r2_hop = grid(r1_ys[0] - 0.85)
    c.via1(r2l_xs[4], r2_ys[0]); c.via1(r2r_xs[0], r2_ys[0])
    c.wire("metal2", [(r2l_xs[4], r2_ys[0]), (r2l_xs[4], y_r2_hop), (r2r_xs[0], y_r2_hop), (r2r_xs[0], r2_ys[0])], 0.34)
    pt_vbg_res = (r2l_xs[0], r2_ys[-1])
    pt_d_res = (r2r_xs[4], r2_ys[-1])
    pt_b_r1 = (r1_x, r1_ys[0])
    pt_c_r1 = (r1_x, r1_ys[-1])

    # Xrt4 sits cleanly at x=126.4 (left of Xrref, well clear of Xk/Xnbc/Xpbnc!), Xrref at 128.0..141.3, Xrt3..0 at 142.8..147.2!
    dx_rf, dy_rf = grid(134.8), grid(48.7)  # bot=29.7 (1.1+ above Xnbc 27.6!), top=67.8 (1.17 below Xm 68.97!)
    c.include(r_rf, dx=dx_rf, dy=dy_rf)
    rf_xs = sorted({grid((r[0] + r[2]) / 2.0 + dx_rf) for r in r_rf.rects["viali"]})
    rf_ys = sorted({grid((r[1] + r[3]) / 2.0 + dy_rf) for r in r_rf.rects["viali"]})
    for i in range(9):
        yj = rf_ys[0] if i % 2 == 0 else rf_ys[-1]
        c.wire("metal1", [(rf_xs[i], yj), (rf_xs[i + 1], yj)], 0.40)
    # Reverse Xrref order: s = rf_xs[-1] top? Keep s = rf_xs[0] top, rt5 = rf_xs[-1] top -> hop on M2 to rt4 top!
    # Even simpler: s = rf_xs[-1] top (right), rt5 = rf_xs[0] top (left) -> straight M1 into Xrt4 at rf_xs[0]-1.48!
    pt_s_res = (rf_xs[-1], rf_ys[-1])
    pt_rt5_res = (rf_xs[0], rf_ys[-1])

    rt_pts: dict[str, tuple[float, float]] = {}
    rt_top_target = rf_ys[-1]
    # Xrt4 at rf_xs[0] - 1.48 (~126.6, right over ota_pl -> bot 25.0 clear of ota_pl 23.1 AND left of Xk 129.0!),
    # Xrt3..0 at rf_xs[-1] + 1.48*(1..4) (~143.0..147.4, ALL short: bot >= 47.0 -> ZERO conflict with Xpbnc or Xnbc!)
    rt_xs_bar = [grid(rf_xs[0] - 1.48)] + [grid(rf_xs[-1] + (k + 1) * 1.48) for k in range(4)]
    rt_terms: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for k, bit_idx in enumerate((4, 3, 2, 1, 0)):
        rp = r_rt[bit_idx]
        rys = sorted({grid((r[1] + r[3]) / 2.0) for r in rp.rects["viali"]})
        dy_t = grid(rt_top_target - rys[-1])
        dx_t = rt_xs_bar[k]
        c.include(rp, dx=dx_t, dy=dy_t)
        yb_t = grid(rys[0] + dy_t); yt_t = grid(rys[-1] + dy_t)
        rt_terms.append(((dx_t, yt_t), (dx_t, yb_t)))
    # rt5: rf_xs[0] top -> Xrt4 top on M1; rt4: Xrt4 bot -> M1 up to y_rt4_link (29.35, ABOVE Xnbc 26.8!) -> M2 -> M1 hop under rt5!
    c.wire("metal1", [pt_rt5_res, rt_terms[0][0]], 0.36)
    rt_pts["rt5"] = rt_terms[0][0]
    y_rt4_link = grid(29.35)
    c.wire("metal1", [rt_terms[0][1], (rt_terms[0][1][0], y_rt4_link)], 0.28)
    c.via1(rt_terms[0][1][0], y_rt4_link)
    c.wire("metal2", [(rt_terms[0][1][0], y_rt4_link), (grid(144.6), y_rt4_link)], 0.28)
    c.via1(grid(144.6), y_rt4_link)
    c.wire("metal1", [(grid(144.6), y_rt4_link), (grid(146.0), y_rt4_link)], 0.28)
    c.via1(grid(146.0), y_rt4_link)
    rt_pts["rt4"] = rt_terms[1][1]
    c.wire("metal1", [rt_terms[1][0], rt_terms[2][0]], 0.34)
    rt_pts["rt3"] = rt_terms[2][0]
    c.wire("metal1", [rt_terms[2][1], (rt_terms[3][1][0], rt_terms[2][1][1]), rt_terms[3][1]], 0.32)
    rt_pts["rt2"] = rt_terms[3][1]
    c.wire("metal1", [rt_terms[3][0], rt_terms[4][0]], 0.34)
    rt_pts["rt1"] = rt_terms[4][0]
    c.wire("metal1", [rt_terms[4][1], (gx2, rt_terms[4][1][1])], 0.36)

    # D5. 5 Trim switches Xs0..4 at x=150.2 in strictly planar top-to-bottom series order (ZERO M2 crossings!)
    sw_specs = [
        ("g0", "vss", "rt1", grid(150.2), grid(55.0)),
        ("g1", "rt1", "rt2", grid(150.2), grid(48.8)),
        ("g2", "rt2", "rt3", grid(150.2), grid(42.6)),
        ("g3", "rt3", "rt4", grid(150.2), grid(36.4)),
        ("g4", "rt4", "rt5", grid(150.2), grid(30.2)),
    ]
    # Left-to-right = deepest-to-shallowest -> every vertical M2 track stops strictly ABOVE tracks to its left!
    rt_track_x = {"rt5": grid(145.4), "rt4": grid(146.0), "rt3": grid(146.6), "rt2": grid(147.2), "rt1": grid(147.85)}
    rt_entry_y = {"rt4": rt_pts["rt4"][1], "rt2": rt_pts["rt2"][1], "rt5": grid(67.10), "rt3": grid(67.65), "rt1": grid(68.20)}
    rt_track_ys: dict[str, list[float]] = {k: [rt_entry_y[k]] for k in rt_track_x}
    rt_track_ys["rt4"].append(y_rt4_link)
    for nm, (rx, ry) in rt_pts.items():
        if nm not in rt_track_x: continue
        ey = rt_entry_y[nm]
        tx = rt_track_x[nm]
        if nm in ("rt4", "rt2"):
            # Enter on M1 directly underneath intervening vertical M2 tracks -> ZERO M2 crossing!
            c.wire("metal1", [(rx, ry), (tx, ry)], 0.28)
            c.via1(tx, ry)
        else:
            c.wire("metal1", [(rx, ry), (rx, ey)], 0.26)
            c.via1(rx, ey)
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
            c.wire("metal2", [(rt_track_x[na], ya_s), (sxs[4], ya_s)], 0.28)
            rt_track_ys[na].append(ya_s)
        for idx in (1, 3):
            c.via1(sxs[idx], yb_s)
        c.wire("metal2", [(rt_track_x[nb], yb_s), (sxs[3], yb_s)], 0.28)
        rt_track_ys[nb].append(yb_s)
        x_g_out = grid(sx_c + xs_sw.bbox()[2] + 0.55)
        c.wire("metal1", [(sgx, sgy), (x_g_out, sgy)], 0.22)
        c.via1(x_g_out, sgy)
        c.wire("metal2", [(x_g_out, sgy), (gx2, sgy)], 0.26)
        g_port_pts[gnm] = (gx2, sgy)
    for nm, x_tr in rt_track_x.items():
        ys = rt_track_ys[nm]
        c.wire("metal2", [(x_tr, min(ys)), (x_tr, max(ys))], 0.26)

    # D6. V->I OTA (ota_pl + ota_np) below Resistors
    dx_opl, dy_opl = grid(115.0), grid(16.2)
    c.include(ota_pl, dx=dx_opl, dy=dy_opl)
    opl_xs = sd_xs_of(ota_pl, "pdiffc", dx_opl)
    opl_gpts = gate_pts_of(ota_pl, dx_opl, dy_opl)
    opl_gy = opl_gpts[0][1]
    opl_bx, opl_by = ota_pl.pins("B")[0]; opl_bx, opl_by = grid(opl_bx + dx_opl), grid(opl_by + dy_opl)
    y_op_vdd = grid(dy_opl + 3.2); y_op_da = grid(dy_opl + 0.2); y_op_vgi = grid(dy_opl - 2.6)
    for idx in (0, 1, 3, 5, 6):
        c.via1(opl_xs[idx], y_op_vdd)
    c.wire("metal2", [(opl_xs[0], y_op_vdd), (opl_xs[6], y_op_vdd)], 0.40)
    c.via2(x_vdd_m, y_op_vdd); xm_vdd_ys.append(y_op_vdd)
    c.via1(opl_xs[2], y_op_da); c.via1(opl_xs[4], y_op_vgi)
    for gx in [p[0] for p in opl_gpts[1:5]]:
        c.via1(gx, opl_gy)
    c.wire("metal2", [(opl_gpts[1][0], opl_gy), (opl_gpts[4][0], opl_gy)], 0.30)
    # Route ota_da cleanly LEFT on M2 to x_otada_m3 (93.6) -> M3 down to ota_np (ZERO vertical M2 crossing y=7..14!)
    c.wire("metal2", [(x_otada_m3, y_op_da), (opl_xs[2], y_op_da)], 0.32); c.via2(x_otada_m3, y_op_da)
    c.wire("metal2", [(x_otada_m3, opl_gy), (opl_gpts[1][0], opl_gy)], 0.30); c.via2(x_otada_m3, opl_gy)
    for gx, sx in ((opl_gpts[0][0], opl_xs[0]), (opl_gpts[5][0], opl_xs[6])):
        c.wire("metal1", [(gx, opl_gy), (sx, opl_gy), (sx, dy_opl)], 0.28)
    y_opl_ring = grid(dy_opl + 6.655)
    c.wire("metal1", [(opl_xs[6], y_op_vdd), (opl_xs[6], y_opl_ring)], 0.32); c.pad("viali", opl_xs[6], y_opl_ring, 0.17)

    dx_onp, dy_onp = grid(110.4), grid(5.3)
    c.include(ota_np, dx=dx_onp, dy=dy_onp)
    onp_xs = sd_xs_of(ota_np, "ndiffc", dx_onp)
    onp_gpts = gate_pts_of(ota_np, dx_onp, dy_onp)
    onp_gy = onp_gpts[0][1]
    y_on_t = grid(dy_onp - 1.5); y_on_da = grid(dy_onp + 0.0); y_on_vgi = grid(dy_onp + 1.5)
    for idx in (1, 3, 5, 7, 9):
        c.via1(onp_xs[idx], y_on_t)
    c.wire("metal2", [(onp_xs[1], y_on_t), (onp_xs[9], y_on_t)], 0.34)
    for idx in (2, 8):
        c.via1(onp_xs[idx], y_on_da)
    c.wire("metal2", [(x_otada_m3, y_on_da), (onp_xs[8], y_on_da)], 0.32); c.via2(x_otada_m3, y_on_da)
    c.wire("metal3", [(x_otada_m3, y_on_da), (x_otada_m3, y_op_da)], 0.36)
    for idx in (4, 6):
        c.via1(onp_xs[idx], y_on_vgi)
    c.wire("metal2", [(x_vgi_r, y_on_vgi), (onp_xs[6], y_on_vgi)], 0.32); c.via2(x_vgi_r, y_on_vgi)
    # y_og_s BELOW onp_gy (7.77, only x=92.4..125.5 -> never touches Xmv!), bridged to x_s_m3 at empty M2 track y=12.60!
    y_og_s = grid(onp_gy - 0.65); y_og_vbg = grid(onp_gy + 0.72)
    for idx in (1, 2, 7, 8):
        gx = onp_gpts[idx][0]; c.via1(gx, onp_gy); c.wire("metal2", [(gx, onp_gy), (gx, y_og_s)], 0.26)
    c.wire("metal2", [(x_s_r, y_og_s), (onp_gpts[8][0], y_og_s)], 0.28); c.via2(x_s_r, y_og_s)
    y_s_mid = grid(12.60)
    c.via2(x_s_r, y_s_mid); c.via2(x_s_m3, y_s_mid); s_ys.append(y_s_mid)
    c.wire("metal2", [(x_s_m3, y_s_mid), (x_s_r, y_s_mid)], 0.30)
    for idx in (3, 4, 5, 6):
        gx = onp_gpts[idx][0]; c.via1(gx, onp_gy); c.via2(gx, onp_gy)
        c.wire("metal3", [(gx, onp_gy), (gx, y_og_vbg)], 0.34); c.via2(gx, y_og_vbg)
    c.wire("metal2", [(x_vbg_m3, y_og_vbg), (onp_gpts[6][0], y_og_vbg)], 0.30)
    c.via2(x_vbg_m3, y_og_vbg); xm_net_ys["vbg"].append(y_og_vbg)
    for gx, sx in ((onp_gpts[0][0], onp_xs[0]), (onp_gpts[9][0], onp_xs[10])):
        c.wire("metal1", [(gx, onp_gy), (sx, onp_gy), (sx, gy1)], 0.24)

    # D7. Xpbnc, Xt_ota, Xbd2, Xk, Xnbc
    dx_pbnc, dy_pbnc = grid(147.0), grid(14.0)  # x=142.0..152.0 (0.35+ clear of gx2=152.7 & Xbd2=141.5!)
    c.include(fc_pbnc, dx=dx_pbnc, dy=dy_pbnc)
    pnc_xs = sd_xs_of(fc_pbnc, "pdiffc", dx_pbnc)
    pnc_gx, pnc_gy = grid(dx_pbnc + fc_pbnc.pins("G")[0][0]), grid(dy_pbnc + fc_pbnc.pins("G")[0][1])
    pnc_bx, pnc_by = fc_pbnc.pins("B")[0]; pnc_bx, pnc_by = grid(pnc_bx + dx_pbnc), grid(pnc_by + dy_pbnc)
    c.via1(pnc_xs[0], y_op_vdd); c.wire("metal2", [(opl_xs[6], y_op_vdd), (pnc_xs[0], y_op_vdd)], 0.36)
    y_pnc_ring = grid(dy_pbnc + 12.655)
    c.wire("metal1", [(pnc_xs[0], y_op_vdd), (pnc_xs[0], y_pnc_ring)], 0.30); c.pad("viali", pnc_xs[0], y_pnc_ring, 0.17)
    c.via1(pnc_xs[1], grid(dy_pbnc + 6.0))
    c.via1(pnc_gx, pnc_gy)

    dx_ot, dy_ot = grid(136.5), grid(2.4)  # ot_gy ~ 3.02 (0.78 below y_on_t=3.80 -> ZERO met2.2!)
    c.include(ota_xt, dx=dx_ot, dy=dy_ot)
    ot_xs = sd_xs_of(ota_xt, "ndiffc", dx_ot)
    ot_gx, ot_gy = grid(dx_ot + ota_xt.pins("G")[0][0]), grid(dy_ot + ota_xt.pins("G")[0][1])
    c.wire("metal1", [(ot_xs[0], dy_ot), (ot_xs[0], gy1)], 0.24)
    c.via1(ot_xs[1], dy_ot); c.wire("metal2", [(onp_xs[9], y_on_t), (ot_xs[1], y_on_t), (ot_xs[1], dy_ot)], 0.28)
    c.via1(ot_gx, ot_gy); c.wire("metal2", [(x_nb2_m3, ot_gy), (ot_gx, ot_gy)], 0.28)
    c.via2(x_nb2_m3, ot_gy); xm_net_ys["nb2"].append(ot_gy)

    dx_bd2, dy_bd2 = grid(137.0), grid(7.4)  # ends 141.4 (0.60 clear of Xpbnc 142.0!)
    c.include(fc_t, dx=dx_bd2, dy=dy_bd2)
    bd2_xs = sd_xs_of(fc_t, "ndiffc", dx_bd2)
    bd2_gx, bd2_gy = grid(dx_bd2 + fc_t.pins("G")[0][0]), grid(dy_bd2 + fc_t.pins("G")[0][1])
    for sx in (bd2_xs[0], bd2_xs[2]):
        c.wire("metal1", [(sx, dy_bd2), (sx, gy1)], 0.24)
    # Route nb2 horizontally at y_bd2_m2=6.05 (between y_on_da=5.30 & y_on_vgi=6.80, 1.72 below y_og_s=7.77!)
    y_bd2_m2 = grid(6.05)
    c.via1(bd2_xs[1], y_bd2_m2); c.via1(bd2_gx, bd2_gy)
    c.wire("metal2", [(x_nb2_m3, y_bd2_m2), (bd2_xs[1], y_bd2_m2), (bd2_gx, y_bd2_m2), (bd2_gx, bd2_gy)], 0.28)
    c.via2(x_nb2_m3, y_bd2_m2); xm_net_ys["nb2"].append(y_bd2_m2)

    dx_xk, dy_xk = grid(130.2), grid(24.75)  # 0.63 above ota_pl N-well (23.12), clear of Xrt4 (126.6) & Xnbc (27.05)!
    c.include(xk_p, dx=dx_xk, dy=dy_xk)
    xk_xs = sd_xs_of(xk_p, "ndiffc", dx_xk)
    xk_gx, xk_gy = grid(dx_xk + xk_p.pins("G")[0][0]), grid(dy_xk + xk_p.pins("G")[0][1])
    # Strictly planar non-crossing M2 tracks below ALL resistor bottoms (23.36+) and above y_op_vdd (19.40):
    # leftmost (s=128.0) highest (21.85), middle (vbg=130.2) next (21.25), rightmost (vgi=132.4) lowest (20.65)!
    y_xk_s = grid(21.85); y_xk_vbg = grid(21.25); y_xk_vgi = grid(20.65); y_c3vss = grid(20.05)
    c.via1(xk_xs[0], dy_xk)
    c.wire("metal2", [(xk_xs[0], dy_xk), (xk_xs[0], y_xk_s), (x_s_r, y_xk_s)], 0.28)
    c.via2(x_s_r, y_xk_s); c.via2(x_s_r, y_og_s)
    c.wire("metal3", [(x_s_r, y_og_s), (x_s_r, y_xk_s)], 0.34)
    c.via1(xk_gx, xk_gy)
    c.wire("metal2", [(xk_gx, xk_gy), (xk_gx, y_xk_vbg), (x_vbg_m3, y_xk_vbg)], 0.28)
    c.via2(x_vbg_m3, y_xk_vbg); xm_net_ys["vbg"].append(y_xk_vbg)
    c.via1(xk_xs[1], dy_xk)
    c.wire("metal2", [(xk_xs[1], dy_xk), (xk_xs[1], y_xk_vgi), (x_vgi_r, y_xk_vgi)], 0.28); c.via2(x_vgi_r, y_xk_vgi)

    dx_nbc, dy_nbc = grid(136.2), grid(27.8)  # 1.40 above r2_ys[0]=26.4 & 0.90 below rt5=28.70!
    c.include(fc_nbc, dx=dx_nbc, dy=dy_nbc)
    nbc_xs = sd_xs_of(fc_nbc, "ndiffc", dx_nbc)
    nbc_gx, nbc_gy = grid(dx_nbc + fc_nbc.pins("G")[0][0]), grid(dy_nbc + fc_nbc.pins("G")[0][1])
    y_col3_ptap = grid(24.4)
    c.rect("pwell", grid(133.6), grid(y_col3_ptap - 0.45), grid(141.6), grid(y_col3_ptap + 0.45))
    c.rect("psubdiff", grid(134.0), grid(y_col3_ptap - 0.22), grid(141.2), grid(y_col3_ptap + 0.22))
    c.rect("psubdiffcont", grid(134.3), grid(y_col3_ptap - 0.085), grid(140.9), grid(y_col3_ptap + 0.085))
    c.rect("locali", grid(134.0), grid(y_col3_ptap - 0.22), grid(141.2), grid(y_col3_ptap + 0.22))
    c.rect("metal1", grid(134.0), grid(y_col3_ptap - 0.24), grid(141.2), grid(y_col3_ptap + 0.24))
    c.pad("viali", grid(137.0), y_col3_ptap, 0.17)
    # Jog nbc_xs[0] (130.7) RIGHT at y=26.55 (strictly ABOVE Xk top 25.85!) before dropping to y_col3_ptap!
    c.wire("metal1", [(nbc_xs[0], dy_nbc), (nbc_xs[0], grid(26.55)), (grid(134.8), grid(26.55)), (grid(134.8), y_col3_ptap)], 0.24)
    # Tie y_col3_ptap down to y_c3vss=20.05 -> LEFT to x_vss_r=91.4 -> M3 straight to gy1!
    x_vss_r = grid(91.4)
    c.via1(grid(137.0), y_col3_ptap)
    c.wire("metal2", [(grid(137.0), y_col3_ptap), (grid(137.0), y_c3vss), (x_vss_r, y_c3vss)], 0.28)
    c.via2(x_vss_r, y_c3vss)
    c.wire("metal3", [(x_vss_r, gy1), (x_vss_r, y_c3vss)], 0.34)
    c.via2(x_vss_r, gy1); c.via1(x_vss_r, gy1)
    c.via1(nbc_xs[1], dy_nbc); c.via1(nbc_gx, nbc_gy)
    c.wire("metal2", [(x_vbnc_m3, dy_nbc), (pnc_xs[1], dy_nbc)], 0.28)
    c.wire("metal2", [(pnc_xs[1], grid(dy_pbnc + 6.0)), (pnc_xs[1], dy_nbc)], 0.28)
    c.wire("metal2", [(nbc_gx, nbc_gy), (nbc_gx, dy_nbc)], 0.26)
    c.via2(x_vbnc_m3, dy_nbc)

    y_vbps_bot = grid(pnc_gy)
    c.wire("metal2", [(x_vbps_m3, y_vbps_bot), (pnc_gx, y_vbps_bot)], 0.28)
    c.via2(x_vbps_m3, y_vbps_bot); vbps_ys.append(y_vbps_bot)

    # =========================================================================
    # E. COMPLETE VERTICAL M3 BUSES + RESISTOR <-> CORE/PNP/OTA CONNECTIONS
    # =========================================================================
    y_ta_res = rs_yt; y_tb_res = grid(rs_yt + 0.50); y_vbg_res = grid(68.25)
    c.via1(*pt_ta_res); c.wire("metal2", [pt_ta_res, (pt_ta_res[0], y_ta_res), (x_ta_m3, y_ta_res)], 0.30)
    c.via2(x_ta_m3, y_ta_res); xm_net_ys["ta"].append(y_ta_res)
    c.via1(*pt_tb_res); c.wire("metal2", [pt_tb_res, (pt_tb_res[0], y_tb_res), (x_tb_m3, y_tb_res)], 0.30)
    c.via2(x_tb_m3, y_tb_res); xm_net_ys["tb"].append(y_tb_res)
    c.via1(*pt_vbg_res); c.wire("metal2", [pt_vbg_res, (pt_vbg_res[0], y_vbg_res), (x_vbg_m3, y_vbg_res)], 0.34)
    c.via2(x_vbg_m3, y_vbg_res); xm_net_ys["vbg"].append(y_vbg_res)

    y_s_top = grid(68.75)
    c.wire("metal1", [pt_s_res, (pt_s_res[0], y_s_top)], 0.28); c.via1(pt_s_res[0], y_s_top); c.wire("metal2", [(pt_s_res[0], y_s_top), (x_s_m3, y_s_top)], 0.30)
    c.via2(x_s_m3, y_s_top); s_ys.append(y_s_top)
    c.wire("metal3", [(x_s_m3, min(s_ys)), (x_s_m3, max(s_ys))], 0.36)

    # Route pt_b_r1 down to y_b_link on M1 so it passes cleanly UNDER y_r2_hop (M2)!
    y_b_link = grid(min(pt_b_res[1], pt_b_r1[1]) - 1.75)
    c.via1(*pt_b_res)
    c.wire("metal1", [pt_b_r1, (pt_b_r1[0], y_b_link)], 0.30)
    c.via1(pt_b_r1[0], y_b_link)
    c.wire("metal2", [pt_b_res, (pt_b_res[0], y_b_link), (pt_b_r1[0], y_b_link)], 0.30)

    # Route a from pt_a_res LEFT at y=22.65 to x_a_r=90.4 -> M3 DOWN to y=11.90 -> M2 LEFT across empty Col 2 to x_a_m3!
    y_a_r = grid(22.65); x_a_r = grid(90.4); y_a_bot = grid(12.02)
    c.via1(*pt_a_res)
    c.wire("metal2", [pt_a_res, (pt_a_res[0], y_a_r), (x_a_r, y_a_r)], 0.28)
    c.via2(x_a_r, y_a_r)
    c.wire("metal3", [(x_a_r, y_a_bot), (x_a_r, y_a_r)], 0.34)
    c.via2(x_a_r, y_a_bot)
    c.wire("metal2", [(x_a_m3, y_a_bot), (x_a_r, y_a_bot)], 0.28)
    c.via2(x_a_m3, y_a_bot)
    c.wire("metal3", [(x_a_m3, y_a_bot), (x_a_m3, q1_em[1])], 0.34)
    via3(c, x_a_m3, q1_em[1]); c.via2(*q1_em); via3(c, *q1_em)
    c.wire("metal4", [(x_a_m3, q1_em[1]), q1_em], 0.50)

    y_c_top = grid(65.25)
    c.via1(*pt_c_r1)
    c.wire("metal2", [pt_c_r1, (pt_c_r1[0], y_c_top), (x_q2_r, y_c_top), (x_q2_r, y_q2_2)], 0.32)

    y_d_top = grid(64.70)
    c.via1(*pt_d_res)
    c.wire("metal2", [pt_d_res, (pt_d_res[0], y_d_top), (x_d_m3, y_d_top)], 0.30)
    c.via2(x_d_m3, y_d_top)
    c.wire("metal3", [(x_d_m3, q3_em[1]), (x_d_m3, y_d_top)], 0.34)
    c.via2(x_d_m3, q3_em[1]); c.wire("metal2", [(x_d_m3, q3_em[1]), q3_em], 0.30)

    c.wire("metal2", [(x_vgi_r, y_op_vgi), (opl_xs[4], y_op_vgi)], 0.34)
    c.via2(x_vgi_r, y_op_vgi)

    c.wire("metal3", [(x_vdd_l, min(xm_vdd_ys)), (x_vdd_l, gy2)], 0.50)
    c.wire("metal3", [(x_vdd_m, min(xm_vdd_ys)), (x_vdd_m, gy2)], 0.50)
    c.wire("metal3", [(x_fa_m3, min(fa_ys)), (x_fa_m3, max(fa_ys))], 0.34)
    c.wire("metal3", [(x_fb_m3, min(fb_ys)), (x_fb_m3, max(fb_ys))], 0.34)
    c.wire("metal3", [(x_vbps_m3, min(vbps_ys)), (x_vbps_m3, max(vbps_ys))], 0.34)
    c.wire("metal3", [(x_vbpc_m3, min(vbpc_ys)), (x_vbpc_m3, max(vbpc_ys))], 0.34)
    c.wire("metal3", [(x_fcda_m3, min(fcda_ys)), (x_fcda_m3, max(fcda_ys))], 0.34)
    c.wire("metal3", [(x_vbnc_m3, grid(dy_nc + fc_nc.pins("G")[0][1])), (x_vbnc_m3, dy_nbc)], 0.34)
    c.wire("metal3", [(x_na_m3, min(na_ys)), (x_na_m3, max(na_ys))], 0.34)
    c.wire("metal3", [(x_nbn_m3, min(nbn_ys)), (x_nbn_m3, max(nbn_ys))], 0.34)
    for nm, x_tr in (("nb", x_nb_m3), ("ta", x_ta_m3), ("tb", x_tb_m3), ("nb2", x_nb2_m3), ("vg", x_vg_m3)):
        ys = xm_net_ys[nm]
        c.wire("metal3", [(x_tr, min(ys)), (x_tr, max(ys))], 0.34)
    c.wire("metal3", [(x_vbg_m3, min(xm_net_ys["vbg"])), (x_vbg_m3, gy2)], 0.44)

    # =========================================================================
    # F. 2x2 STACKED MIM1+MIM2 ROOF OVER COL 3 (Cvbg = 6 pF [3 sites] + Cvgi = 2 pF [1 site])
    # =========================================================================
    dx_mim_top = grid(125.0); dy_mim_top = grid(51.0)
    mim_top = _place_mim_stack_site(c, m1_21, m2_21, dx_mim_top, dy_mim_top)
    c1_single_x = sorted(grid(x) for _, x, _, nm in m1_11.labels if nm.startswith("C1"))[0]
    dx_mim_vbg3 = grid(mim_top["a_pts"][1][0] - c1_single_x)
    dx_mim_vgi = grid(mim_top["a_pts"][0][0] - c1_single_x)
    mim_vgi = _place_mim_stack_site(c, m1_11, m2_11, dx_mim_vgi, grid(24.8))
    mim_vbg3 = _place_mim_stack_site(c, m1_11, m2_11, dx_mim_vbg3, grid(24.8))

    for lay, key, ww in (("metal4", "a_pts", 1.20), ("metal3", "b3_pts", 1.20), ("metal5", "b5_pts", 1.80)):
        p0 = mim_vbg3[key][0]; p1 = mim_top[key][1]
        xm = grid((p0[0] + p1[0]) / 2.0)
        c.wire(lay, [(xm, p0[1]), (xm, p1[1])], ww)

    y_cbg_m4 = grid(64.25)
    y_cbg_vss = grid(66.20)
    for x, y in mim_top["a_pts"]:
        c.wire("metal4", [(x, y), (x, y_cbg_m4)], 1.20)
    c.wire("metal4", [(x_vbg_m3, y_cbg_m4), (mim_top["a_pts"][-1][0], y_cbg_m4)], 1.00)
    # 1x8 vertical via3 array directly on x_vbg_m3 (narrow 0.50 um width -> ZERO short to x_tb_m3!)
    via3_array(c, x_vbg_m3, y_cbg_m4, 1, 8, pitch=0.72)
    for x, y in mim_top["b3_pts"]:
        c.wire("metal3", [(x, y), (x, y_cbg_vss)], 1.20)
    for x, y in mim_top["b5_pts"]:
        c.wire("metal5", [(x, y), (x, y_cbg_vss)], 1.80)
    xb_l = min(mim_top["b3_pts"][0][0], mim_top["b5_pts"][0][0])
    c.wire("metal3", [(xb_l, y_cbg_vss), (gx2, y_cbg_vss)], 1.10)
    c.wire("metal5", [(xb_l, y_cbg_vss), (gx2, y_cbg_vss)], 1.80)
    x_vss_tie = grid(126.0)
    c.rect("metal4", grid(x_vss_tie - 4.2), grid(y_cbg_vss - 0.70), grid(x_vss_tie + 4.2), grid(y_cbg_vss + 0.70))
    via3_array(c, grid(x_vss_tie - 2.6), y_cbg_vss, 4, 2, pitch=0.72)
    via4_array(c, grid(x_vss_tie + 1.2), y_cbg_vss, 4, 1, pitch=2.00)
    c.via2(gx2, y_cbg_vss); c.via1(gx2, y_cbg_vss)

    y_cvgi_m4 = grid(11.50)
    y_cvgi_vdd = grid(10.05)
    ax_gi, ay_gi = mim_vgi["a_pts"][0]
    b3x_gi, b3y_gi = mim_vgi["b3_pts"][0]
    b5x_gi, b5y_gi = mim_vgi["b5_pts"][0]
    c.wire("metal4", [(ax_gi, ay_gi), (ax_gi, y_cvgi_m4), (x_vgi_l, y_cvgi_m4)], 0.66)
    # 1x8 vertical via3 array on x_vgi_l & 1x4 on x_vgi_r (0.50 um wide -> ZERO short to x_s_m3 or x_vdd_m!)
    via3_array(c, x_vgi_l, y_cvgi_m4, 1, 8, pitch=0.72)
    c.wire("metal3", [(x_vgi_r, y_on_vgi), (x_vgi_r, y_xk_vgi)], 0.50)
    via3_array(c, x_vgi_r, y_cvgi_m4, 1, 4, pitch=0.72)
    c.wire("metal3", [(b3x_gi, b3y_gi), (b3x_gi, y_cvgi_vdd), (x_vdd_m, y_cvgi_vdd)], 0.60)
    c.wire("metal5", [(b5x_gi, b5y_gi), (b5x_gi, y_cvgi_vdd), (x_vdd_m, y_cvgi_vdd)], 1.60)
    x_vdd_tie = grid(106.0)
    c.rect("metal4", grid(x_vdd_tie - 7.5), grid(y_cvgi_vdd - 0.45), grid(x_vdd_tie + 4.2), grid(y_cvgi_vdd + 0.45))
    via3_array(c, grid(x_vdd_tie - 2.8), y_cvgi_vdd, 4, 1, pitch=0.72)
    via3_array(c, grid(x_vdd_tie - 6.0), y_cvgi_vdd, 4, 1, pitch=0.72)
    via4_array(c, grid(x_vdd_tie + 1.2), y_cvgi_vdd, 4, 1, pitch=2.00)
    c.wire("metal3", [(x_vdd_m, y_cvgi_vdd), (x_vdd_m, min(xm_vdd_ys))], 0.50)

    # =========================================================================
    # G. PERIMETER PORTS (ALL 13 ports cleanly on outer macro boundary!)
    # =========================================================================
    c.port("vbg", "metal3", x_vbg_m3, gy2)
    for k in range(4):
        c.port(f"i{k}", "metal3", i_port_xs[k], gy1)
    c.port("vgi", "metal3", x_vgi_l, gy1)
    for gnm, (px, py) in g_port_pts.items():
        c.port(gnm, "metal2", px, py)
    c.port("vdd", "metal3", x_vdd_m, gy2)
    c.port("vss", "metal1", grid((gx1 + gx2) / 2.0), gy1)
    c.write(w / f"{cell}.mag")

    # Exact reference netlist matching bias_v2.spice + physical outer dummies!
    ref_lines = [
        "* BIAS v2 serdes_bias_ref_v2_pdk (Folded-cascode BG + V->I + stacked MIM1+MIM2)",
        f".subckt {cell} vbg i0 i1 i2 i3 vgi g4 g3 g2 g1 g0 vdd vss",
        # Core PMOS Xm1..Xm5 + 4 outer dummies (w=14 l=12 x 4 = w=56 l=12)
        "Xm1 ta vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm2 tb vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm3 vbg vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm4 nb vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        "Xm5 nb2 vg vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        # Xrsa, Xrsb (5+5 bars l=39.200)
        *[f"Xrsa{i} {'ta' if i==0 else f'rsa{i}'} {'a' if i==4 else f'rsa{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=39.200" for i in range(5)],
        *[f"Xrsb{i} {'tb' if i==0 else f'rsb{i}'} {'b' if i==4 else f'rsb{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=39.200" for i in range(5)],
        # PNPs Q1 (1), Q2 (8), Q3 (1)
        "Xq1 vss vss a sky130_fd_pr__pnp_05v5_W3p40L3p40",
        *[f"Xq2_{i} vss vss c sky130_fd_pr__pnp_05v5_W3p40L3p40" for i in range(8)],
        "Xq3 vss vss d sky130_fd_pr__pnp_05v5_W3p40L3p40",
        # Xr1 (l=39.790) + Xr2 (10 bars l=37.650)
        "Xr1 b c vss sky130_fd_pr__res_high_po w=1 l=39.790",
        *[f"Xr2_{i} {'vbg' if i==0 else f'r2_{i}'} {'d' if i==9 else f'r2_{i+1}'} vss sky130_fd_pr__res_high_po w=1 l=37.650" for i in range(10)],
        # Core bias diode + Folded-cascode OTA + outer dummies
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
        # Startup
        "Xsp st vss vdd vdd sky130_fd_pr__pfet_01v8 w=0.42 l=20",
        "Xsn st nb vss vss sky130_fd_pr__nfet_01v8 w=2 l=1",
        "Xsu vg st vss vss sky130_fd_pr__nfet_01v8 w=1 l=1",
        # V->I loop + Xmv/Xo0..3 + dummies
        "Xbd2 nb2 nb2 vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xota_t ota_tail nb2 vss vss sky130_fd_pr__nfet_01v8 w=1 l=6",
        "Xota_a ota_da s ota_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xota_b vgi vbg ota_tail vss sky130_fd_pr__nfet_01v8 w=24 l=4",
        "Xota_ab_dl ota_tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xota_ab_dr ota_tail vss vss vss sky130_fd_pr__nfet_01v8 w=6 l=4",
        "Xota_la ota_da ota_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8",
        "Xota_lb vgi ota_da vdd vdd sky130_fd_pr__pfet_01v8_lvt w=24 l=8",
        "Xk vgi vbg s vss sky130_fd_pr__nfet_01v8_lvt w=2 l=4",
        "Xmv s vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo0 i0 vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo1 i1 vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo2 i2 vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        "Xo3 i3 vgi vdd vdd sky130_fd_pr__pfet_01v8_lvt w=32 l=4",
        *[f"Xmv_dum{i} vss vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=8 l=4" for i in range(10)],
        "Xpl_dum vdd vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=72 l=8",
        "Xxm_dum vbg vdd vdd vdd sky130_fd_pr__pfet_01v8_lvt w=56 l=12",
        # Xrref (10 bars l=33.900) + Xrt4..0 + Xs4..0
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
        # Stacked MIM1+MIM2: Cvbg (3 sites = 6 pF) + Cvgi (1 site = 2 pF)
        *[f"Xcbg1_{i} vbg vss {MIM1} w={mim_side} l={mim_side}\nXcbg2_{i} vss vbg {MIM2} w={mim_side} l={mim_side}" for i in range(3)],
        f"Xcgi1 vgi vdd {MIM1} w={mim_side} l={mim_side}",
        f"Xcgi2 vdd vgi {MIM2} w={mim_side} l={mim_side}",
        f".ends {cell}\n",
    ]
    return verify_cell(w, cell, "\n".join(ref_lines))


def build_bias_top_v2(root: Path, export_ptat: bool = False) -> dict:
    import sys as _sys
    _dir = str(Path(__file__).resolve().parent)
    if _dir not in _sys.path:
        _sys.path.insert(0, _dir)
    import build_bias_top_v2 as _top
    return _top.build_bias_top_v2(root, _sys.modules[__name__], export_ptat=export_ptat)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", type=Path, default=None)
    ap.add_argument("--cells", default="ctle,cp,cml,vbuf,pbuf,bias_ref,bias_top")
    ap.add_argument("--install-variant", default=None,
                    help="Optional isolated variant name under analog/bias/layout/variants/ (e.g. v2_ptat_pdk); never overwrites v2_pdk")
    args = ap.parse_args()
    work = (args.work_dir or (REPO / "results/layout/bias_v2_pdk" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))).resolve()
    work.mkdir(parents=True, exist_ok=True)
    builders = {
        "ctle": build_bias_ctle_v2,
        "cp": build_bias_cp_v2,
        "cml": build_bias_cml_v2,
        "vbuf": build_ref_vbuf_v2,
        "pbuf": build_ref_pbuf_v2,
        "bias_ref": build_bias_ref_v2,
        "bias_top": lambda r: build_bias_top_v2(r, export_ptat=False),
        "bias_top_ptat": lambda r: build_bias_top_v2(r, export_ptat=True),
    }
    reports = []
    for k in args.cells.split(","):
        if k in builders:
            reports.append(builders[k](work))
    (work / "summary.json").write_text(json.dumps(reports, indent=2) + "\n")
    if args.install_variant:
        assert args.install_variant != "v2_pdk", "Refusing to overwrite v1.0-hashed v2_pdk/"
        vdir = Path(__file__).resolve().parent / "variants" / args.install_variant
        vdir.mkdir(parents=True, exist_ok=True)
        for rep in reports:
            cn = rep["cell"]
            cdir = work / cn
            for suf in (".mag", ".png", "_ref.spice", "_lvs.spice", "_pex.spice"):
                src = cdir / f"{cn}{suf}"
                if src.exists():
                    shutil.copy2(src, vdir / src.name)
        (vdir / "summary.json").write_text(json.dumps({"variant": args.install_variant, "pdk": "sky130A", "cells": reports}, indent=2) + "\n")
        print(f"Installed clean artifacts -> {vdir}")
    print(f"Done -> {work}")


if __name__ == "__main__":
    main()
