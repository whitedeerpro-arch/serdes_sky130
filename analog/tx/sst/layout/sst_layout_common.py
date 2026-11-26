#!/usr/bin/env python3
"""Shared SKY130A PDK layout primitives, cached device builder, SPICE reference
flattener, and verification helpers for TX v4 Zero-CML SST (`analog/tx/sst/layout/`).

Design rules & safety guarantees:
  - Every physical device (LVT/std NMOS, PMOS, res_high_po_2p85/1p41, stacked MIM1+MIM2)
    is drawn by the SKY130A Magic PDK generator (`sky130::*_draw`).
  - All temporary files, Magic/Netgen logs, `.ext`, `.spice`, `.sim` live strictly
    under `results/layout/tx_sst_v4/` (never inside `analog/tx/sst/layout/`).
  - Never uses relative `cd` in Magic Tcl scripts; always uses `-dnull -noconsole`,
    `quit -noprompt`, and bounded `subprocess.run(..., timeout=120)`.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[4]
LAYOUT_VERIF = REPO / "verification/layout"
if str(LAYOUT_VERIF) not in sys.path:
    sys.path.insert(0, str(LAYOUT_VERIF))

from check import exported_ports  # noqa: E402
from geometry import Cell, pdk_device  # noqa: E402
import magicutil as mu  # noqa: E402
from summarize_parasitics import summarize_pex_spice  # noqa: E402

SPICE_DIR = REPO / "analog/tx/sst/spice"
COMMON_SPICE_DIR = REPO / "analog/common/devices/spice"

N_STD = "sky130_fd_pr__nfet_01v8"
N_LVT = "sky130_fd_pr__nfet_01v8_lvt"
P_STD = "sky130_fd_pr__pfet_01v8"
P_LVT = "sky130_fd_pr__pfet_01v8_lvt"
R_2P85 = "sky130_fd_pr__res_high_po_2p85"
R_1P41 = "sky130_fd_pr__res_high_po_1p41"
MIM1 = "sky130_fd_pr__cap_mim_m3_1"
MIM2 = "sky130_fd_pr__cap_mim_m3_2"

W_M1 = 0.180
W_M2 = 0.280
W_M3 = 0.340
W_M4 = 0.400


def grid(x: float) -> float:
    return round(round(x / 0.005) * 0.005, 3)


def clone_cell(src: Cell) -> Cell:
    c = Cell()
    c.rects = {k: list(v) for k, v in src.rects.items()}
    c.labels = list(src.labels)
    return c


class PdkCache:
    """Cache Magic `pdk_device` calls inside a scratch directory under results/."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir.resolve()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, Cell] = {}
        self._mos_mem: dict[str, tuple[Cell, dict]] = {}

    def _key(self, model: str, params: dict[str, Any]) -> str:
        items = "_".join(f"{k}{str(v).replace('.', 'p').replace('-', 'm')}" for k, v in sorted(params.items()))
        short_mdl = model.replace("sky130_fd_pr__", "")
        return f"{short_mdl}__{items}"

    def device(self, model: str, params: dict[str, Any]) -> Cell:
        key = self._key(model, params)
        if key not in self._mem:
            mag_path = self.cache_dir / f"{key}.mag"
            if mag_path.exists():
                c = Cell.read(mag_path)
            else:
                c = pdk_device(self.cache_dir, key, model, params)
            c.rects.pop("checkpaint", None)
            self._mem[key] = c
        return clone_cell(self._mem[key])

    def build_mos(
        self,
        model: str,
        w_f: float,
        l_f: float,
        nf: int,
        dy: float,
        is_pmos: bool,
    ) -> tuple[Cell, dict]:
        """Draw a compact guard=0 MOS centered in X at 0 and in Y at `dy`, with clipped poly."""
        w_f, l_f, dy = grid(w_f), grid(l_f), grid(dy)
        key = f"{model}_{w_f:.3f}_{l_f:.3f}_{nf}_{dy:.3f}_{int(is_pmos)}"
        if key not in self._mos_mem:
            p = self.device(model, dict(w=w_f, l=l_f, nf=nf, conn_gates=0, topc=0, botc=0, guard=0))
            out = Cell()
            cut_layer = "pdiffc" if is_pmos else "ndiffc"
            diff_layer = "pdiff" if is_pmos else "ndiff"
            h_clip = grid(w_f / 2.0 + 0.140)

            for layer, rects in p.rects.items():
                if layer in ("viali", "metal1", "pwell", "nwell", "checkpaint"):
                    continue
                for x1, y1, x2, y2 in rects:
                    if layer == "poly":
                        y1 = max(y1, -h_clip)
                        y2 = min(y2, h_clip)
                        if y2 <= y1:
                            continue
                    out.rect(layer, grid(x1), grid(y1 + dy), grid(x2), grid(y2 + dy))

            sds = sorted({grid((r[0] + r[2]) / 2.0) for r in p.rects[cut_layer]})
            gxs = sorted({grid((r[0] + r[2]) / 2.0) for r in p.rects["poly"]})
            diffs = out.rects[diff_layer]
            diff_x1 = grid(min(r[0] for r in diffs))
            diff_x2 = grid(max(r[2] for r in diffs))
            c_y1 = grid(min(r[1] for r in p.rects[cut_layer]) + dy)
            c_y2 = grid(max(r[3] for r in p.rects[cut_layer]) + dy)
            info = {
                "w_diff": grid(diff_x2 - diff_x1),
                "hw_diff": grid((diff_x2 - diff_x1) / 2.0),
                "s_xs": sds[::2],
                "d_xs": sds[1::2],
                "all_sd_xs": sds,
                "g_xs": gxs,
                "l_f": l_f,
                "w_f": w_f,
                "nf": nf,
                "c_y1": c_y1,
                "c_y2": c_y2,
                "diff_y1": grid(dy - w_f / 2.0),
                "diff_y2": grid(dy + w_f / 2.0),
            }
            self._mos_mem[key] = (out, info)
        cell, info = self._mos_mem[key]
        return clone_cell(cell), dict(info)


# ---------------------------------------------------------------------------
# DRC-clean low-level drawing primitives
# ---------------------------------------------------------------------------

def poly_cont_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("poly", x, y, 0.27, 0.34)
    c.pad("polycont", x, y, 0.17, 0.17)
    c.pad("locali", x, y, 0.18, 0.34)


def viali_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("viali", x, y, 0.17)
    # 0.29 x 0.29 = 0.0841 um^2 > 0.083 um^2 Metal1 minimum area rule (met1.6)
    c.pad("metal1", x, y, 0.29, 0.29)


def via1_clean(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.via1(x, y)


def via2_clean(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.via2(x, y)
    c.pad("metal3", x, y, 0.52)


def via3_pad(c: Cell, x: float, y: float) -> None:
    x, y = grid(x), grid(y)
    c.pad("metal3", x, y, 0.52)
    c.pad("via3", x, y, 0.32)
    c.pad("metal4", x, y, 0.52)


def via3_array(c: Cell, x: float, y: float, nx: int = 2, ny: int = 2, pitch: float = 0.70) -> None:
    x, y = grid(x), grid(y)
    x0 = x - (nx - 1) * pitch / 2.0
    y0 = y - (ny - 1) * pitch / 2.0
    hw = (nx - 1) * pitch / 2.0 + 0.35
    hh = (ny - 1) * pitch / 2.0 + 0.35
    c.rect("metal3", grid(x - hw), grid(y - hh), grid(x + hw), grid(y + hh))
    c.rect("metal4", grid(x - hw), grid(y - hh), grid(x + hw), grid(y + hh))
    for ix in range(nx):
        for iy in range(ny):
            c.pad("via3", grid(x0 + ix * pitch), grid(y0 + iy * pitch), 0.32)


def via4_array(c: Cell, x: float, y: float, nx: int = 2, ny: int = 2, pitch: float = 2.10) -> None:
    x, y = grid(x), grid(y)
    x0 = x - (nx - 1) * pitch / 2.0
    y0 = y - (ny - 1) * pitch / 2.0
    hw = (nx - 1) * pitch / 2.0 + 1.05
    hh = (ny - 1) * pitch / 2.0 + 1.05
    c.rect("metal4", grid(x - hw), grid(y - hh), grid(x + hw), grid(y + hh))
    c.rect("metal5", grid(x - hw - 0.15), grid(y - hh - 0.15), grid(x + hw + 0.15), grid(y + hh + 0.15))
    for ix in range(nx):
        for iy in range(ny):
            c.pad("via4", grid(x0 + ix * pitch), grid(y0 + iy * pitch), 1.18)


def via34_pillar(c: Cell, x: float, y: float, big: bool = False) -> None:
    x, y = grid(x), grid(y)
    if big:
        c.rect("metal3", grid(x - 2.1), grid(y - 2.1), grid(x + 2.1), grid(y + 2.1))
        c.rect("metal4", grid(x - 2.2), grid(y - 2.2), grid(x + 2.2), grid(y + 2.2))
        c.rect("metal5", grid(x - 2.4), grid(y - 2.4), grid(x + 2.4), grid(y + 2.4))
        for vx in (-1.35, -0.45, 0.45, 1.35):
            for vy in (-0.90, 0.0, 0.90):
                c.pad("via3", grid(x + vx), grid(y + vy), 0.32)
        for vx in (-1.05, 1.05):
            for vy in (-1.05, 1.05):
                c.pad("via4", grid(x + vx), grid(y + vy), 1.18)
    else:
        c.rect("metal3", grid(x - 2.1), grid(y - 1.1), grid(x + 2.1), grid(y + 1.1))
        c.rect("metal4", grid(x - 2.2), grid(y - 1.2), grid(x + 2.2), grid(y + 1.2))
        c.rect("metal5", grid(x - 2.4), grid(y - 1.3), grid(x + 2.4), grid(y + 1.3))
        for vx in (-1.35, -0.45, 0.45, 1.35):
            for vy in (-0.45, 0.45):
                c.pad("via3", grid(x + vx), grid(y + vy), 0.32)
        for vx in (-1.05, 1.05):
            c.pad("via4", grid(x + vx), y, 1.18)


def locali_v(c: Cell, x: float, y1: float, y2: float) -> None:
    ya, yb = sorted((grid(y1), grid(y2)))
    c.rect("locali", grid(x - 0.085), ya, grid(x + 0.085), yb)


def locali_h(c: Cell, x1: float, x2: float, y: float) -> None:
    xa, xb = sorted((grid(x1), grid(x2)))
    c.rect("locali", grid(xa - 0.085), grid(y - 0.085), grid(xb + 0.085), grid(y + 0.085))


def draw_tap_h(c: Cell, diff_layer: str, x1: float, x2: float, y: float, half_w: float = 0.175) -> None:
    x1, x2, y = grid(x1), grid(x2), grid(y)
    c.rect(diff_layer, x1, grid(y - half_w), x2, grid(y + half_w))
    c.rect("locali", x1, grid(y - 0.085), x2, grid(y + 0.085))
    if (x2 - x1) >= 0.48:
        c.rect(diff_layer + "cont", grid(x1 + 0.14), grid(y - 0.085), grid(x2 - 0.14), grid(y + 0.085))


def draw_tap_v(c: Cell, diff_layer: str, x: float, y1: float, y2: float, half_w: float = 0.180) -> None:
    x, y1, y2 = grid(x), grid(y1), grid(y2)
    c.rect(diff_layer, grid(x - half_w), grid(y1 - 0.085), grid(x + half_w), grid(y2 + 0.085))
    c.rect("locali", grid(x - 0.085), grid(y1 - 0.085), grid(x + 0.085), grid(y2 + 0.085))
    if (y2 - y1) >= 0.90:
        c.rect(diff_layer + "cont", grid(x - 0.085), grid(y1 + 0.360), grid(x + 0.085), grid(y2 - 0.360))


def place_stacked_mim(
    c: Cell, cache: PdkCache, side: float, cols: int, rows: int,
    dx_c: float, dy_c: float,
    a_off: float = 1.90, b3_off: float = 1.90, b5_off: float = 2.60,
    pillar_side: str = "east", pillar_dx: float = 3.60,
) -> dict:
    """Place an aligned stacked MIM1+MIM2 (M3-M4-M5) block centered at (dx_c, dy_c).

    Polarity:
      - Middle plate `a` (M4) = C1 of MIM1 + C2 of MIM2  (vdrv / vgate)
      - Outer plates `b` (M3+M5) = C2 of MIM1 + C1 of MIM2 (vss)
    """
    lower = cache.device(MIM1, dict(w=side, l=side, nx=cols, ny=rows, stack=1, doports=1))
    upper = cache.device(MIM2, dict(w=side, l=side, nx=cols, ny=rows, doports=1))
    lp = sorted(lower.rects["mimcapcontact"], key=lambda r: (r[0], r[1]))
    up = sorted([(-r[2], r[1], -r[0], r[3]) for r in upper.rects["mimcap2contact"]], key=lambda r: (r[0], r[1]))
    if len(lp) != cols * rows or len(up) != cols * rows:
        raise RuntimeError(f"MIM plate count mismatch: {len(lp)} vs {len(up)}")
    adx = grid((lp[0][0] + lp[0][2] - up[0][0] - up[0][2]) / 2.0)
    ady = grid((lp[0][1] + lp[0][3] - up[0][1] - up[0][3]) / 2.0)
    for a, b in zip(lp, up):
        if max(abs(a[k] - b[k] - (adx if k % 2 == 0 else ady)) for k in range(4)) > 0.02:
            raise RuntimeError("MIM1/MIM2 plate alignment mismatch")

    dx_c, dy_c = grid(dx_c), grid(dy_c)
    a_pts = sorted([(grid(x + dx_c), grid(y + dy_c)) for _, x, y, nm in lower.labels if nm.startswith("C1")])
    b3_pts = sorted([(grid(x + dx_c), grid(y + dy_c)) for _, x, y, nm in lower.labels if nm.startswith("C2")])
    b5_pts = sorted([(grid(-x + adx + dx_c), grid(y + ady + dy_c)) for _, x, y, nm in upper.labels if nm.startswith("C1")])
    lower.labels.clear()
    upper.labels.clear()

    c.include(lower, dx=dx_c, dy=dy_c)
    c.include(upper, dx=grid(dx_c + adx), dy=grid(dy_c + ady), mirror_x=True)

    lx1, ly1, lx2, ly2 = lower.bbox()
    ux1, uy1, ux2, uy2 = upper.bbox()
    bx1 = grid(min(lx1 + dx_c, -ux2 + adx + dx_c))
    bx2 = grid(max(lx2 + dx_c, -ux1 + adx + dx_c))
    by1 = grid(min(ly1 + dy_c, uy1 + ady + dy_c))
    by2 = grid(max(ly2 + dy_c, uy2 + ady + dy_c))

    ya = grid(by2 + a_off)
    for x, y in a_pts:
        c.wire("metal4", [(x, y), (x, ya)], 0.90)
    if len(a_pts) > 1:
        c.wire("metal4", [(a_pts[0][0], ya), (a_pts[-1][0], ya)], 1.00)

    yb3 = grid(by1 - b3_off)
    for x, y in b3_pts:
        c.wire("metal3", [(x, y), (x, yb3)], 0.90)
    if len(b3_pts) > 1:
        c.wire("metal3", [(b3_pts[0][0], yb3), (b3_pts[-1][0], yb3)], 1.00)

    yb5 = grid(by2 + b5_off)
    for x, y in b5_pts:
        c.wire("metal5", [(x, y), (x, yb5)], 1.60)
    if len(b5_pts) > 1:
        c.wire("metal5", [(b5_pts[0][0], yb5), (b5_pts[-1][0], yb5)], 1.60)

    if pillar_side == "east":
        xg = grid(bx2 + pillar_dx)
        yp = grid(dy_c)
        c.wire("metal3", [(b3_pts[-1][0], yb3), (xg, yb3), (xg, yp)], 1.00)
        c.wire("metal5", [(b5_pts[-1][0], yb5), (xg, yb5), (xg, yp)], 1.60)
        via34_pillar(c, xg, yp, big=False)
        b_pin = (xg, yp)
    elif pillar_side == "west":
        xg = grid(bx1 - pillar_dx)
        yp = grid(dy_c)
        c.wire("metal3", [(b3_pts[0][0], yb3), (xg, yb3), (xg, yp)], 1.00)
        c.wire("metal5", [(b5_pts[0][0], yb5), (xg, yb5), (xg, yp)], 1.60)
        via34_pillar(c, xg, yp, big=False)
        b_pin = (xg, yp)
    else:
        b_pin = (b3_pts[0][0], yb3)

    return {
        "a": (a_pts[-1][0], ya),
        "a_left": (a_pts[0][0], ya),
        "a_pts": a_pts,
        "ya": ya,
        "b": b_pin,
        "b3_pts": b3_pts,
        "yb3": yb3,
        "b5_pts": b5_pts,
        "yb5": yb5,
        "bbox": (bx1, by1, bx2, by2),
    }


# ---------------------------------------------------------------------------
# DRC-Guaranteed M3-Horizontal / M4-Vertical Manhattan Router
# ---------------------------------------------------------------------------

class ManhattanRouter:
    """Interval-packing M3-H / M4-V router for multi-row CMOS macros.

    Guarantees >= 0.90 um pitch on both M3 horizontal tracks and M4 vertical drops
    (pad 0.52 um -> >= 0.38 um edge-to-edge gap >> 0.30 um SKY130 met3.2/met4.2).
    """

    def __init__(
        self,
        m3_tracks: list[float],
        m4_min_pitch: float = 0.960,
        preferred_tracks: set[float] | None = None,
    ) -> None:
        self.m3_tracks = [grid(y) for y in m3_tracks]
        self.preferred_tracks = {grid(y) for y in preferred_tracks} if preferred_tracks else set()
        self.m4_min_pitch = m4_min_pitch
        # Per-track occupied X intervals: list of (x1, x2, net_name)
        self.track_occ: dict[float, list[tuple[float, float, str]]] = {y: [] for y in self.m3_tracks}
        # Global M4 vertical segments: list of (x, y1, y2, net_name)
        self.m4_segs: list[tuple[float, float, float, str]] = []
        # Local M3 jogs from pin -> assigned M4 X: list of (y, x1, x2, net_name)
        self.m3_jogs: list[tuple[float, float, float, str]] = []
        # Track M3 pin pad positions so no horizontal M3 bus hits an unrelated pin's M3 via2 pad!
        self.m3_pin_pads: list[tuple[float, float, str]] = []

    def _m4_clear(self, x: float, y1: float, y2: float, net: str) -> bool:
        ya, yb = min(y1, y2) - 0.855, max(y1, y2) + 0.855
        for sx, sy1, sy2, snet in self.m4_segs:
            if snet == net:
                continue
            if abs(x - sx) < self.m4_min_pitch and not (yb < sy1 or ya > sy2):
                return False
        return True

    def _alloc_m4_x(self, pref_x: float, y1: float, y2: float, net: str) -> float:
        pref_x = grid(pref_x)
        if self._m4_clear(pref_x, y1, y2, net):
            return pref_x
        for k in range(1, 80):
            for sgn in (+1, -1):
                cand = grid(pref_x + sgn * k * 0.480)
                if self._m4_clear(cand, y1, y2, net):
                    return cand
        raise RuntimeError(f"ManhattanRouter: no free M4 X near {pref_x} for net {net}")

    def _track_free(self, yt: float, x1: float, x2: float, net: str) -> bool:
        xa, xb = min(x1, x2) - 0.855, max(x1, x2) + 0.855
        for ox1, ox2, onet in self.track_occ[yt]:
            if onet != net and not (xb < ox1 or xa > ox2):
                return False
        for px, py, pnet in self.m3_pin_pads:
            if pnet != net and abs(py - yt) < 0.855 and xa <= px <= xb:
                return False
        for jy, jx1, jx2, jnet in self.m3_jogs:
            if jnet != net and abs(jy - yt) < 0.855 and not (xb < jx1 - 0.855 or xa > jx2 + 0.855):
                return False
        return True

    def reserve_m3_pad(self, x: float, y: float, net: str) -> None:
        self.m3_pin_pads.append((grid(x), grid(y), net))

    def reserve_m3_span(self, y: float, x1: float, x2: float, net: str) -> None:
        self.m3_jogs.append((grid(y), grid(min(x1, x2)), grid(max(x1, x2)), net))

    def reserve_m4_seg(self, x: float, y1: float, y2: float, net: str) -> None:
        self.m4_segs.append((grid(x), grid(min(y1, y2)), grid(max(y1, y2)), net))

    def pre_register_nets(self, all_nets: dict[str, list[tuple[float, float, str]]]) -> None:
        """Register all pin pads upfront so no trunk collides with a future pin."""
        for net, pts in all_nets.items():
            for px, py, lyr in pts:
                px, py = grid(px), grid(py)
                if lyr in ("metal1", "metal2", "metal3"):
                    self.m3_pin_pads.append((px, py, net))
                elif lyr == "metal4":
                    self.m4_segs.append((px, grid(py - 0.20), grid(py + 0.20), net))

    def _m3_jog_clear(self, y: float, x1: float, x2: float, net: str) -> bool:
        xa, xb = min(x1, x2) - 0.855, max(x1, x2) + 0.855
        for px, py, pnet in self.m3_pin_pads:
            if pnet != net and abs(py - y) < 0.855 and xa <= px <= xb:
                return False
        for jy, jx1, jx2, jnet in self.m3_jogs:
            if jnet != net and abs(jy - y) < 0.855 and not (xb < jx1 - 0.855 or xa > jx2 + 0.855):
                return False
        for ty, occs in self.track_occ.items():
            if abs(ty - y) < 0.855:
                for ox1, ox2, onet in occs:
                    if onet != net and not (xb < ox1 - 0.855 or xa > ox2 + 0.855):
                        return False
        return True

    def _m3_vseg_clear(self, x: float, y1: float, y2: float, net: str) -> bool:
        ya, yb = min(y1, y2) - 0.855, max(y1, y2) + 0.855
        for px, py, pnet in self.m3_pin_pads:
            if pnet != net and abs(px - x) < 0.855 and ya <= py <= yb:
                return False
        for jy, jx1, jx2, jnet in self.m3_jogs:
            if jnet != net and ya <= jy <= yb and (jx1 - 0.855) <= x <= (jx2 + 0.855):
                return False
        for ty, occs in self.track_occ.items():
            if ya <= ty <= yb:
                for ox1, ox2, onet in occs:
                    if onet != net and (ox1 - 0.855) <= x <= (ox2 + 0.855):
                        return False
        return True

    def _plan_pin_escape(
        self, px: float, py: float, y_trunk: float, net: str, lyr: str,
        tentative_m4: list[tuple[float, float, float]],
    ) -> tuple[float, float] | None:
        """Plan a guaranteed DRC-clean escape `(mx, y_via3)` from pin `(px, py, lyr)` to `y_trunk`.

        Returns `(mx, y_via3)` where M4 runs vertically at `x=mx` from `y_via3` to `y_trunk`.
        For `metal4` ports, allows a perimeter horizontal M4 jog at `y=py` if straight-up is blocked.
        For `metal1/2/3` pins, tries straight-up -> horizontal M3 jog -> short L-escape on M3.
        """
        def clear_m4(x: float, y_a: float, y_b: float) -> bool:
            if not self._m4_clear(x, y_a, y_b, net):
                return False
            ya, yb = min(y_a, y_b) - 0.855, max(y_a, y_b) + 0.855
            for tx, ty1, ty2 in tentative_m4:
                dx = abs(x - tx)
                if 0.40 < dx < 0.88 and not (yb < ty1 or ya > ty2):
                    return False
            return True

        px, py = grid(px), grid(py)
        if lyr == "metal4":
            if clear_m4(px, py, y_trunk):
                return (px, py)
            # Allow a clean horizontal M4 jog right at the perimeter `y=py`
            for k in range(2, 24):
                for sgn in (+1, -1):
                    cand = grid(px + sgn * k * 0.480)
                    # Ensure horizontal M4 jog at `py` is clear of other M4 segments crossing `py`
                    jog_ok = True
                    xa, xb = min(px, cand) - 0.855, max(px, cand) + 0.855
                    for sx, sy1, sy2, snet in self.m4_segs:
                        if snet != net and xa <= sx <= xb and (sy1 - 0.855) <= py <= (sy2 + 0.855):
                            jog_ok = False
                            break
                    if jog_ok and clear_m4(cand, py, y_trunk):
                        return (cand, py)
            return None

        # 1. Try snapping onto an existing same-net M4 drop within 0.88 um!
        for tx, _, _ in tentative_m4:
            if abs(px - tx) <= 0.88 and clear_m4(tx, py, y_trunk) and self._m3_jog_clear(py, px, tx, net):
                return (tx, py)

        # 2. Straight up on M4 at (px, py)
        if clear_m4(px, py, y_trunk):
            return (px, py)

        # 3. Horizontal M3 jog at y=py
        for k in range(2, 28):
            for sgn in (+1, -1):
                cand = grid(px + sgn * k * 0.480)
                if clear_m4(cand, py, y_trunk) and self._m3_jog_clear(py, px, cand, net):
                    return (cand, py)

        # 4. Short vertical M3 escape to py_esc = py +- (0.9..4.5 um), then M4 (or horizontal M3 jog)
        for dy_e in (+0.900, -0.900, +1.350, -1.350, +1.800, -1.800, +2.250, -2.250, +2.700, -2.700, +3.600, -3.600, +4.500, -4.500):
            ye = grid(py + dy_e)
            if 0.01 < abs(ye - y_trunk) < 0.88:
                continue
            if not self._m3_vseg_clear(px, py, ye, net):
                continue
            if clear_m4(px, ye, y_trunk):
                return (px, ye)
            for k in range(2, 48):
                for sgn in (+1, -1):
                    cand = grid(px + sgn * k * 0.480)
                    if clear_m4(cand, ye, y_trunk) and self._m3_jog_clear(ye, px, cand, net):
                        return (cand, ye)
        return None

    def route_net(
        self,
        c: Cell,
        net: str,
        pins: list[tuple[float, float, str]],
        pref_y: float | None = None,
        m3_width: float = 0.400,
        m4_width: float = 0.520,
    ) -> float:
        """Route a net connecting `pins = [(x, y, layer), ...]` using 1 M3 trunk + M4 drops.

        Atomically verifies every pin's M4 drop and M3 escape before committing geometry,
        guaranteeing zero M3/M4 shorts and zero met3.2/met4.2 violations.
        """
        if len(pins) < 2:
            return pref_y if pref_y is not None else self.m3_tracks[0]

        pts = sorted([(grid(x), grid(y), lyr) for x, y, lyr in pins], key=lambda p: 0 if p[2] == "metal4" else 1)
        ys_raw = [p[1] for p in pts]
        y_target = grid(pref_y) if pref_y is not None else grid(sum(ys_raw) / len(ys_raw))

        cand_tracks = sorted(
            self.m3_tracks,
            key=lambda yt: (0 if (not self.preferred_tracks or yt in self.preferred_tracks) else 1, abs(yt - y_target)),
        )
        chosen_y: float | None = None
        chosen_plan: list[tuple[float, float, str, float, float]] | None = None
        fail_reasons: dict[str, int] = {"near_pin": 0, "m4_block": 0, "m3_full": 0}
        last_block_pin = None

        for yt in cand_tracks:
            if any(0.01 < abs(py - yt) < 0.88 for _, py, _ in pts):
                fail_reasons["near_pin"] += 1
                continue
            tent_m4: list[tuple[float, float, float]] = []
            plan: list[tuple[float, float, str, float, float]] = []
            ok = True
            for px, py, lyr in pts:
                if lyr != "metal4" and abs(py - yt) < 0.01:
                    plan.append((px, py, lyr, px, py))
                    continue
                esc = self._plan_pin_escape(px, py, yt, net, lyr, tent_m4)
                if esc is None:
                    ok = False
                    last_block_pin = (px, py, lyr, yt)
                    fail_reasons["m4_block"] += 1
                    break
                mx, ye = esc
                tent_m4.append((mx, min(ye, yt), max(ye, yt)))
                plan.append((px, py, lyr, mx, ye))
            if not ok:
                continue
            trunk_xs = [p[3] for p in plan]
            if not self._track_free(yt, min(trunk_xs), max(trunk_xs), net):
                fail_reasons["m3_full"] += 1
                continue
            chosen_y = yt
            chosen_plan = plan
            break

        if chosen_y is None or chosen_plan is None:
            xs_raw = [p[0] for p in pts]
            raise RuntimeError(
                f"ManhattanRouter: no conflict-free M3/M4 route for net {net} in x=[{min(xs_raw)}, {max(xs_raw)}] "
                f"reasons={fail_reasons} last_block={last_block_pin}"
            )

        trunk_xs = []
        for px, py, lyr, mx, ye in chosen_plan:
            if lyr == "metal1":
                c.via1(px, py)
                via2_clean(c, px, py)
            elif lyr == "metal2":
                via2_clean(c, px, py)

            if lyr == "metal4":
                if abs(mx - px) > 0.01:
                    c.wire("metal4", [(min(px, mx), py), (max(px, mx), py)], m4_width)
                    # Record perimeter horizontal jog span
                    for xx in (px, mx):
                        self.m4_segs.append((xx, grid(py - 0.1), grid(py + 0.1), net))
                if abs(py - chosen_y) > 0.01:
                    c.wire("metal4", [(mx, min(py, chosen_y)), (mx, max(py, chosen_y))], m4_width)
                via3_pad(c, mx, chosen_y)
                self.m4_segs.append((mx, min(py, chosen_y), max(py, chosen_y), net))
                trunk_xs.append(mx)
            elif abs(py - chosen_y) < 0.01:
                trunk_xs.append(px)
            else:
                if abs(ye - py) > 0.01:
                    c.wire("metal3", [(px, min(py, ye)), (px, max(py, ye))], m3_width)
                    self.m3_pin_pads.append((px, ye, net))
                    self.m3_jogs.append((grid((py + ye) / 2.0), px, px, net))
                if abs(mx - px) > 0.01:
                    jog_w = 0.520 if abs(mx - px) < 0.90 else m3_width
                    c.wire("metal3", [(min(px, mx), ye), (max(px, mx), ye)], jog_w)
                    self.m3_jogs.append((ye, min(px, mx), max(px, mx), net))
                via3_pad(c, mx, ye)
                self.m3_pin_pads.append((mx, ye, net))
                if abs(ye - chosen_y) > 0.01:
                    c.wire("metal4", [(mx, min(ye, chosen_y)), (mx, max(ye, chosen_y))], m4_width)
                via3_pad(c, mx, chosen_y)
                self.m4_segs.append((mx, min(ye, chosen_y), max(ye, chosen_y), net))
                trunk_xs.append(mx)

        x_lo, x_hi = min(trunk_xs), max(trunk_xs)
        if x_hi - x_lo > 0.01:
            c.wire("metal3", [(x_lo, chosen_y), (x_hi, chosen_y)], m3_width)
        self.track_occ[chosen_y].append((x_lo, x_hi, net))
        return chosen_y


# ---------------------------------------------------------------------------
# Frozen SPICE Reference Netlist Evaluator (exact 1:1 from analog/tx/sst/spice/)
# ---------------------------------------------------------------------------

def _eval_expr(expr: str, env: dict[str, float]) -> float:
    s = expr.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
    safe_globals = {"__builtins__": {}, "max": max, "min": min, "floor": math.floor, "ceil": math.ceil, "abs": abs}
    return float(eval(s, safe_globals, env))


def _fmt_num(v: float) -> str:
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6g}"


def _parse_spice_subckts(paths: list[Path]) -> dict[str, dict]:
    """Parse `.subckt` definitions (handling `+` continuations) from frozen SPICE files."""
    subckts: dict[str, dict] = {}
    for p in paths:
        raw_lines = p.read_text().splitlines()
        logical: list[str] = []
        for ln in raw_lines:
            s = ln.strip()
            if not s or s.startswith("*"):
                continue
            if s.startswith("+") and logical:
                logical[-1] += " " + s[1:].strip()
            else:
                logical.append(s)

        cur: dict | None = None
        for ln in logical:
            low = ln.lower()
            if low.startswith(".subckt "):
                toks = ln.split()
                name = toks[1]
                ports: list[str] = []
                defaults: dict[str, str] = {}
                in_params = False
                for tok in toks[2:]:
                    if tok.lower() == "params:":
                        in_params = True
                        continue
                    if in_params or "=" in tok:
                        in_params = True
                        k, v = tok.split("=", 1)
                        defaults[k.lower()] = v
                    else:
                        ports.append(tok)
                cur = {"name": name, "ports": ports, "defaults": defaults, "insts": []}
                subckts[name] = cur
            elif low.startswith(".ends"):
                cur = None
            elif cur is not None and ln[0].upper() == "X":
                toks = ln.split()
                inst_name = toks[0]
                param_idx = len(toks)
                for i in range(2, len(toks)):
                    if "=" in toks[i]:
                        param_idx = i
                        break
                model = toks[param_idx - 1]
                conns = toks[1 : param_idx - 1]
                ov: dict[str, str] = {}
                for tok in toks[param_idx:]:
                    k, v = tok.split("=", 1)
                    ov[k.lower()] = v
                cur["insts"].append((inst_name, conns, model, ov))
    return subckts


def generate_ref_spice(
    top_src_subckt: str,
    top_out_subckt: str,
    out_path: Path,
    param_overrides: dict[str, float] | None = None,
) -> list[str]:
    """Flatten frozen TX v4 SST SPICE into a literal SKY130 primitive reference netlist for Netgen.

    Reads the frozen files in `analog/tx/sst/spice/` + `sky130_primitives.spice` verbatim,
    evaluates all `{expr}` subcircuit parameters, and emits exact SKY130 primitive devices
    so Netgen performs full property checking (W, L, res L, MIM W/L) with 0 approximations.
    """
    subckts = _parse_spice_subckts([
        COMMON_SPICE_DIR / "sky130_primitives.spice",
        SPICE_DIR / "tx_sst_driver.spice",
        SPICE_DIR / "tx_sst_serializer16.spice",
        SPICE_DIR / "tx_sst_top.spice",
    ])
    if top_src_subckt not in subckts:
        raise KeyError(f"Unknown subckt {top_src_subckt}")

    top_def = subckts[top_src_subckt]
    top_ports = list(top_def["ports"])
    lines: list[str] = [
        f"* Exact flattened LVS reference netlist for {top_out_subckt}",
        f"* Source subckt: {top_src_subckt} (frozen analog/tx/sst/spice/*.spice)",
        f".subckt {top_out_subckt} " + " ".join(top_ports),
    ]
    dev_idx = 0

    def expand(sub_name: str, port_map: dict[str, str], env: dict[str, float], prefix: str) -> None:
        nonlocal dev_idx
        sdef = subckts[sub_name]
        local_env = {}
        for k, v in sdef["defaults"].items():
            local_env[k] = _eval_expr(v, env)
        local_env.update(env)

        for inst_name, conns, model, ov in sdef["insts"]:
            mapped_conns = [port_map.get(c, f"{prefix}_{c}") for c in conns]
            child_env = {k: _eval_expr(v, local_env) for k, v in ov.items()}
            if model.startswith("sky130_fd_pr__"):
                dev_idx += 1
                # Emit exact SKY130 primitive parameters checked by Netgen
                p_strs = []
                if "nfet" in model or "pfet" in model:
                    p_strs.append(f"w={_fmt_num(child_env['w'])}")
                    p_strs.append(f"l={_fmt_num(child_env['l'])}")
                elif "res_high_po_" in model:
                    p_strs.append(f"l={_fmt_num(child_env['l'])}")
                elif "cap_mim_" in model:
                    p_strs.append(f"w={_fmt_num(child_env['w'])}")
                    p_strs.append(f"l={_fmt_num(child_env['l'])}")
                else:
                    for k, v in sorted(child_env.items()):
                        p_strs.append(f"{k}={_fmt_num(v)}")
                lines.append(f"X{dev_idx} " + " ".join(mapped_conns) + f" {model} " + " ".join(p_strs))
            elif model in subckts:
                cdef = subckts[model]
                if len(mapped_conns) != len(cdef["ports"]):
                    raise ValueError(f"Port count mismatch calling {model}: {len(mapped_conns)} != {len(cdef['ports'])}")
                cmap = dict(zip(cdef["ports"], mapped_conns))
                expand(model, cmap, child_env, f"{prefix}_{inst_name}")
            else:
                raise KeyError(f"Unknown model {model} inside {sub_name}")

    init_env = {k: _eval_expr(v, {}) for k, v in top_def["defaults"].items()}
    if param_overrides:
        init_env.update(param_overrides)
    expand(top_src_subckt, {p: p for p in top_ports}, init_env, "t")
    lines.append(f".ends {top_out_subckt}")
    lines.append("")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines))
    return top_ports


# ---------------------------------------------------------------------------
# Fast bounded Magic/Netgen verification + review_cell.py + plot_mag.py
# ---------------------------------------------------------------------------

def run_magic_bounded(script: Path, cwd: Path, timeout_s: int = 120) -> mu.MagicResult:
    proc = subprocess.run(
        [mu.MAGIC, "-dnull", "-noconsole", "-rcfile", str(mu.RCFILE), str(script)],
        cwd=cwd.resolve(),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    log = proc.stdout + proc.stderr
    clean = "\n".join(
        l for l in log.splitlines()
        if "tk_version" not in l and "version_check.tcl" not in l
    )
    bad = re.search(r"Error parsing|no such|No such cell", clean)
    return mu.MagicResult(log=log, ok=(proc.returncode == 0 and bad is None))


def run_netgen_bounded(layout: Path, top: str, ref: Path, out_log: Path, cwd: Path, timeout_s: int = 120) -> subprocess.CompletedProcess:
    cwd = cwd.resolve()
    shim = cwd / "_netgen_local.tcl"
    text = mu.NETGEN_TCL.read_text().replace(
        "load /usr/lib/netgen/tcl/tclnetgen.so",
        f"load {mu.NGC}/tcl/tclnetgen.so",
    )
    shim.write_text(text)
    script = cwd / "_netgen_run.tcl"
    script.write_text(
        "set argv [list lvs {%s %s} {%s %s} %s %s]\n"
        "source %s\n" % (layout.resolve(), top, ref.resolve(), top, mu.NETGEN_SETUP, out_log.resolve(), shim.resolve())
    )
    return subprocess.run(
        [str(mu.NETGENEXEC), str(script)], cwd=cwd, capture_output=True, text=True, timeout=timeout_s
    )


def verify_flat_cell(
    work: Path,
    cell: str,
    mag_src: Path,
    ref_src: Path,
    expected_ports: list[str],
    timeout_s: int = 120,
) -> dict:
    """Run full-rule Magic DRC, LVS extraction, Netgen LVS, and CPEX inside `work`."""
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    mag = work / f"{cell}.mag"
    ref = work / f"{cell}_ref.spice"
    if mag_src.resolve() != mag:
        shutil.copy2(mag_src, mag)
    if ref_src.resolve() != ref:
        shutil.copy2(ref_src, ref)

    lvs_sp = work / f"{cell}_lvs.spice"
    pex_sp = work / f"{cell}_pex.spice"
    lvs_log = work / f"{cell}_lvs.log"

    tcl = work / "_drc_ext.tcl"
    tcl.write_text("\n".join([
        "drc off",
        f"load {cell}",
        "select top cell",
        "drc on",
        "drc euclidean on",
        "drc style drc(full)",
        "drc check",
        "drc catchup",
        'puts "DRC_TOTAL=[drc list count total]"',
        'foreach {why boxes} [drc listall why] { puts "DRC_RULE [llength $boxes] | $why" }',
        "drc off",
        "extract all",
        "ext2spice lvs",
        f"ext2spice -o {lvs_sp.name}",
        "ext2spice cthresh 0",
        "ext2spice rthresh infinite",
        f"ext2spice -o {pex_sp.name}",
        "quit -noprompt",
        "",
    ]))
    res = run_magic_bounded(tcl, work, timeout_s=timeout_s)
    (work / "_drc_ext.log").write_text(res.log)
    res.need(f"DRC+EXT {cell}")

    m_drc = re.search(r"DRC_TOTAL=(\d+)", res.log)
    drc_total = int(m_drc.group(1)) if m_drc else -1
    drc_rules = sorted(
        (l[len("DRC_RULE "):] for l in res.log.splitlines() if l.startswith("DRC_RULE ")),
        key=lambda l: -int(l.split("|")[0]),
    )

    ng = run_netgen_bounded(lvs_sp, cell, ref, lvs_log, work, timeout_s=timeout_s)
    lvs_txt = lvs_log.read_text() if lvs_log.exists() else (ng.stdout + ng.stderr)
    full_txt = ng.stdout + "\n" + lvs_txt
    lvs_match = "Circuits match uniquely" in full_txt
    lvs_prop_err = "Property errors were found" in full_txt
    lvs_disc = sorted(set(re.findall(r"disconnected node:\s*(\S+)", full_txt, re.I)))

    ports = exported_ports(lvs_sp, cell) if lvs_sp.exists() else []
    port_set_ok = set(ports) == set(expected_ports) and len(ports) == len(expected_ports)
    parasitics = summarize_pex_spice(pex_sp, ports) if pex_sp.exists() else {}

    box = Cell.read(mag).bbox()
    w_um = round(box[2] - box[0], 3)
    h_um = round(box[3] - box[1], 3)
    return {
        "cell": cell,
        "bbox_um": [round(x, 3) for x in box],
        "width_um": w_um,
        "height_um": h_um,
        "area_um2": round(w_um * h_um, 2),
        "aspect_ratio": round(w_um / max(h_um, 1e-6), 2),
        "drc_total": drc_total,
        "drc_rules": drc_rules,
        "lvs_match": lvs_match,
        "lvs_property_errors": lvs_prop_err,
        "lvs_disconnected": lvs_disc,
        "exported_ports": ports,
        "expected_port_count": len(expected_ports),
        "port_count_match": port_set_ok,
        "parasitics": parasitics,
        "work_dir": str(work),
    }


def run_independent_review(mag: Path, ref: Path, review_dir: Path, timeout_s: int = 180) -> dict:
    """Invoke `verification/layout/review_cell.py --rc` into a fresh append-only review directory."""
    review_dir = review_dir.resolve()
    if review_dir.exists():
        shutil.rmtree(review_dir)
    proc = subprocess.run(
        [sys.executable, str(LAYOUT_VERIF / "review_cell.py"), str(mag.resolve()), str(ref.resolve()),
         "--output-dir", str(review_dir), "--rc"],
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"review_cell.py failed for {mag.name}:\n{proc.stdout}\n{proc.stderr}")
    rep = json.loads((review_dir / "summary.json").read_text())
    rc_path = review_dir / "rc_summary.json"
    if rc_path.exists():
        rep["rc"] = json.loads(rc_path.read_text())
    return rep


def render_png_plot_mag(mag: Path, out_png: Path) -> None:
    """Render white-background PNG using `verification/layout/plot_mag.py` with outside legend."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    import plot_mag as pm  # noqa: E402

    rects, labels = pm.parse(mag)
    xs = [r[1] for r in rects] + [r[3] for r in rects]
    ys = [r[2] for r in rects] + [r[4] for r in rects]
    x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
    w, h = x2 - x1, y2 - y1

    fig_w = 18.0
    fig_h = max(7.0, min(15.0, fig_w * (h + 10.0) / max(w + 10.0, 1.0)))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    present: set[str] = set()
    for layer, rx1, ry1, rx2, ry2 in rects:
        if layer not in pm.COLORS:
            continue
        present.add(layer)
        is_mim = layer in ("mimcap", "mimcap2")
        alpha = 0.28 if is_mim else (0.65 if layer in ("m1", "m2", "m3", "m4", "m5") else 0.88)
        ec = "#d97706" if layer == "mimcap" else ("#059669" if layer == "mimcap2" else "none")
        ax.add_patch(
            Rectangle(
                (rx1, ry1), rx2 - rx1, ry2 - ry1,
                facecolor=pm.COLORS[layer],
                edgecolor=ec,
                linewidth=0.7 if is_mim else 0.0,
                hatch="//" if is_mim else None,
                alpha=alpha,
                zorder=pm.Z[layer],
            )
        )

    # Spread clustered perimeter labels cleanly so every port name is legible with zero box overlap
    pad_x = max(3.0, 0.05 * w)
    pad_y = max(3.0, 0.06 * h)
    placed: list[tuple[str, float, float, float, float]] = []
    min_dy = max(2.2, 0.024 * h)
    min_dx = max(5.0, 0.040 * w)
    # Sort by X-bucket then Y so vertical stacks on West/East edges fan out cleanly
    for nm, px, py in sorted(labels, key=lambda t: (round(t[1] / max(min_dx, 1.0)), t[2])):
        tx, ty = px, py
        # Push slightly outward if on outer left/right/bottom/top perimeter
        if abs(px - x1) < 1.5:
            tx = px - 0.015 * w
        elif abs(px - x2) < 4.0:
            tx = px + 0.015 * w
        if abs(py - y1) < 1.5:
            ty = py - 0.018 * h
        elif abs(py - y2) < 1.5:
            ty = py + 0.015 * h
        # De-overlap against previously placed label boxes
        for _ in range(12):
            conflict = False
            for _, _, _, otx, oty in placed:
                if abs(tx - otx) < min_dx and abs(ty - oty) < min_dy:
                    conflict = True
                    if abs(px - x1) < 1.5 or abs(px - x2) < 4.0:
                        ty = oty + min_dy
                    else:
                        ty = oty + (min_dy if py >= y2 - 2.0 else -min_dy)
                    break
            if not conflict:
                break
        placed.append((nm, px, py, tx, ty))

    for nm, px, py, tx, ty in placed:
        ax.plot([px], [py], marker="o", ms=2.8, color="#111827", zorder=99)
        if abs(tx - px) > 0.3 or abs(ty - py) > 0.3:
            ax.plot([px, tx], [py, ty], color="#2563eb", lw=0.55, alpha=0.75, zorder=98)
        ha = "right" if abs(px - x1) < 1.5 else ("left" if abs(px - x2) < 4.0 else "center")
        ax.text(
            tx, ty, nm, fontsize=6.2, fontweight="bold", color="#111827", ha=ha, va="center", zorder=100,
            bbox=dict(boxstyle="round,pad=0.12", facecolor="white", edgecolor="#2563eb", alpha=0.92, lw=0.6),
        )

    ax.set_xlim(x1 - pad_x * 1.4, x2 + pad_x * 1.6)
    ax.set_ylim(y1 - pad_y * 1.5, y2 + pad_y * 1.3)
    ax.set_aspect("equal")
    ax.set_xlabel("x (um)")
    ax.set_ylabel("y (um)")
    ax.set_title(f"{mag.name}  ({w:.2f} x {h:.2f} um = {w*h:,.1f} um^2)")
    ax.grid(True, lw=0.25, alpha=0.35)

    legend_keys = [k for k in pm.COLORS if k in present]
    handles = [
        Rectangle((0, 0), 1, 1, facecolor=pm.COLORS[k],
                  edgecolor="#d97706" if k == "mimcap" else ("#059669" if k == "mimcap2" else "none"),
                  hatch="//" if k in ("mimcap", "mimcap2") else None)
        for k in legend_keys
    ]
    ax.legend(handles, legend_keys, fontsize=6.5, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=160, facecolor="white")
    plt.close(fig)
