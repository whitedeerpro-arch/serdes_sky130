#!/usr/bin/env python3
"""Core geometry canvas, .mag parser/writer, .tcl exporter, and matplotlib renderer."""
from __future__ import annotations
import re
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle


class LayoutCanvas:
    def __init__(self, cell_name: str):
        self.cell_name = cell_name
        self.rects: dict[str, list[tuple[float, float, float, float]]] = {}
        self.labels: list[tuple[str, float, float, str]] = []
        self.tcl_lines: list[str] = [
            "drc off",
            "units microns",
            "proc R {layer x1 y1 x2 y2} { if {$x1 > $x2} {set q $x1; set x1 $x2; set x2 $q};"
            " if {$y1 > $y2} {set q $y1; set y1 $y2; set y2 $q}; box $x1 $y1 $x2 $y2; paint $layer }",
            "proc L {name x y} { box $x $y $x $y; label $name; catch {port make} }",
            f"load {cell_name}",
        ]

    def R(self, layer: str, x1: float, y1: float, x2: float, y2: float):
        xa, xb = round(min(x1, x2), 3), round(max(x1, x2), 3)
        ya, yb = round(min(y1, y2), 3), round(max(y1, y2), 3)
        if xb <= xa or yb <= ya:
            return
        self.rects.setdefault(layer, []).append((xa, ya, xb, yb))
        self.tcl_lines.append(f"R {layer} {xa:.3f} {ya:.3f} {xb:.3f} {yb:.3f}")

    def sq(self, layer: str, cx: float, cy: float, s: float):
        self.R(layer, cx - s / 2.0, cy - s / 2.0, cx + s / 2.0, cy + s / 2.0)

    def sq_wh(self, layer: str, cx: float, cy: float, w: float, h: float):
        self.R(layer, cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)

    def via1(self, cx: float, cy: float, pad: float = 0.36):
        self.sq("m1", cx, cy, pad)
        self.sq("via1", cx, cy, 0.26)
        self.sq("m2", cx, cy, pad)

    def via2(self, cx: float, cy: float, pad: float = 0.42):
        self.sq("m2", cx, cy, pad)
        self.sq("via2", cx, cy, 0.28)
        self.sq("m3", cx, cy, pad)

    def via3(self, cx: float, cy: float, pad: float = 0.46):
        self.sq("m3", cx, cy, pad)
        self.sq("via3", cx, cy, 0.32)
        self.sq("m4", cx, cy, pad)

    def L(self, name: str, x: float, y: float, layer: str = "m1"):
        rx, ry = round(x, 3), round(y, 3)
        self.labels.append((layer, rx, ry, name))
        self.tcl_lines.append(f"L {name} {rx:.3f} {ry:.3f}")

    def include_subcell(self, sub: "LayoutCanvas", dx: float = 0.0, dy: float = 0.0,
                        flip_x: bool = False, flip_y: bool = False, cx0: float = 0.0, cy0: float = 0.0,
                        include_labels: bool = False, prefix: str = ""):
        for lyr, rlist in sub.rects.items():
            for (x1, y1, x2, y2) in rlist:
                nx1, nx2 = (-x2 + 2 * cx0, -x1 + 2 * cx0) if flip_x else (x1, x2)
                ny1, ny2 = (-y2 + 2 * cy0, -y1 + 2 * cy0) if flip_y else (y1, y2)
                self.R(lyr, nx1 + dx, ny1 + dy, nx2 + dx, ny2 + dy)
        if include_labels:
            for lyr, lx, ly, nm in sub.labels:
                nlx = (-lx + 2 * cx0) if flip_x else lx
                nly = (-ly + 2 * cy0) if flip_y else ly
                self.L(f"{prefix}{nm}" if prefix else nm, nlx + dx, nly + dy, lyr)

    def bbox(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for rlist in self.rects.values():
            for x1, y1, x2, y2 in rlist:
                xs.extend([x1, x2])
                ys.extend([y1, y2])
        if not xs:
            return (0.0, 0.0, 1.0, 1.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def save_tcl(self, path: Path):
        out = self.tcl_lines + ["select top cell", "save"]
        path.write_text("\n".join(out) + "\n")

    def save_mag(self, path: Path):
        mag_map = {"m1": "metal1", "m2": "metal2", "m3": "metal3", "m4": "metal4"}
        lines = ["magic", "tech sky130A", "magscale 1 2", "timestamp 1794500000"]
        merged: dict[str, list[tuple[float, float, float, float]]] = {}
        for lyr, rlist in self.rects.items():
            mlyr = mag_map.get(lyr, lyr)
            merged.setdefault(mlyr, []).extend(rlist)
        for lyr, rlist in merged.items():
            lines.append(f"<< {lyr} >>")
            for x1, y1, x2, y2 in rlist:
                lines.append(f"rect {int(round(x1*200))} {int(round(y1*200))} {int(round(x2*200))} {int(round(y2*200))}")
        lines.append("<< labels >>")
        for lyr, lx, ly, nm in self.labels:
            mlyr = mag_map.get(lyr, lyr)
            ix, iy = int(round(lx * 200)), int(round(ly * 200))
            lines.append(f"rlabel {mlyr} {ix} {iy} {ix} {iy} 1 {nm}")
        lines.append("<< end >>")
        path.write_text("\n".join(lines) + "\n")


def load_mag_as_canvas(path: Path, cell_name: str = "sub") -> LayoutCanvas:
    c = LayoutCanvas(cell_name)
    rev_map = {"metal1": "m1", "metal2": "m2", "metal3": "m3", "metal4": "m4"}
    cur_layer = None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        m_sec = re.match(r"^<<\s*(\S+)\s*>>$", line)
        if m_sec:
            cur_layer = rev_map.get(m_sec.group(1), m_sec.group(1))
            continue
        if cur_layer and cur_layer not in ("labels", "end"):
            m_rect = re.match(r"^rect\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)$", line)
            if m_rect:
                x1, y1, x2, y2 = [int(v) / 200.0 for v in m_rect.groups()]
                c.R(cur_layer, x1, y1, x2, y2)
        elif cur_layer == "labels":
            m_lab = re.match(r"^rlabel\s+(\S+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+(-?\d+)\s+\d+\s+(\S+)$", line)
            if m_lab:
                lyr = rev_map.get(m_lab.group(1), m_lab.group(1))
                lx = (int(m_lab.group(2)) + int(m_lab.group(4))) / 400.0
                ly = (int(m_lab.group(3)) + int(m_lab.group(5))) / 400.0
                c.L(m_lab.group(6), lx, ly, lyr)
    return c


LAYER_STYLE = {
    "pwell":         dict(fc="#f5ebd6", ec="none", alpha=0.45, z=1, label="pwell"),
    "nwell":         dict(fc="#fde68a", ec="#d97706", alpha=0.55, z=2, label="nwell"),
    "psubdiff":      dict(fc="#86efac", ec="#16a34a", alpha=0.80, z=3, label="psubdiff (P+ tap)"),
    "nsubdiff":      dict(fc="#93c5fd", ec="#2563eb", alpha=0.80, z=3, label="nsubdiff (N+ tap)"),
    "ndiff":         dict(fc="#60a5fa", ec="#1d4ed8", alpha=0.82, z=3, label="ndiff (N+ active)"),
    "pdiff":         dict(fc="#f472b6", ec="#be185d", alpha=0.82, z=3, label="pdiff (P+ active)"),
    "poly":          dict(fc="#ea580c", ec="#9a3412", alpha=0.86, z=4, label="poly"),
    "nmos":          dict(fc="#fb923c", ec="#c2410c", alpha=0.35, z=5, label="nmos/lvt"),
    "nmoslvt":       dict(fc="#fb923c", ec="#c2410c", alpha=0.35, z=5, label="nmos/lvt"),
    "pmos":          dict(fc="#f43f5e", ec="#9f1239", alpha=0.35, z=5, label="pmos/lvt"),
    "pmoslvt":       dict(fc="#f43f5e", ec="#9f1239", alpha=0.35, z=5, label="pmos/lvt"),
    "varactor":      dict(fc="#f97316", ec="#c2410c", alpha=0.45, z=5, label="varactor"),
    "xhrpoly":       dict(fc="#d946ef", ec="#86198f", alpha=0.72, z=4, label="high_po resistor"),
    "xpolycontact":  dict(fc="#a21caf", ec="#4a044e", alpha=0.85, z=6, label="res contact"),
    "locali":        dict(fc="#a78bfa", ec="#6d28d9", alpha=0.55, z=6, label="li1 (locali)"),
    "polycont":      dict(fc="#78350f", ec="#451a03", alpha=0.92, z=7, label="licon (contact)"),
    "ndiffc":        dict(fc="#065f46", ec="#022c22", alpha=0.92, z=7, label="licon (contact)"),
    "pdiffc":        dict(fc="#065f46", ec="#022c22", alpha=0.92, z=7, label="licon (contact)"),
    "nsubdiffcont":  dict(fc="#065f46", ec="#022c22", alpha=0.92, z=7, label="licon (contact)"),
    "psubdiffcont":  dict(fc="#065f46", ec="#022c22", alpha=0.92, z=7, label="licon (contact)"),
    "viali":         dict(fc="#c084fc", ec="#581c87", alpha=0.88, z=8, label="viali (mcon)"),
    "mcon":          dict(fc="#c084fc", ec="#581c87", alpha=0.88, z=8, label="viali (mcon)"),
    "m1":            dict(fc="#3b82f6", ec="#1d4ed8", alpha=0.68, z=9, label="met1 (M1)"),
    "metal1":        dict(fc="#3b82f6", ec="#1d4ed8", alpha=0.68, z=9, label="met1 (M1)"),
    "via1":          dict(fc="#16a34a", ec="#052e16", alpha=0.95, z=10, lw=1.0, label="via1 (M1->M2)"),
    "m2":            dict(fc="#0d9488", ec="#115e59", alpha=0.66, z=11, label="met2 (M2)"),
    "metal2":        dict(fc="#0d9488", ec="#115e59", alpha=0.66, z=11, label="met2 (M2)"),
    "via2":          dict(fc="#1e293b", ec="#0f172a", alpha=0.95, z=12, lw=1.0, label="via2 (M2->M3)"),
    "m3":            dict(fc="#ef4444", ec="#991b1b", alpha=0.62, z=13, label="met3 (M3)"),
    "metal3":        dict(fc="#ef4444", ec="#991b1b", alpha=0.62, z=13, label="met3 (M3)"),
    "mimcap":        dict(fc="#f59e0b", ec="#b45309", alpha=0.75, z=14, label="capm (MIM top)"),
    "mimcapcontact": dict(fc="#d97706", ec="#78350f", alpha=0.90, z=15, label="mimcc"),
    "via3":          dict(fc="#eab308", ec="#713f12", alpha=0.95, z=16, lw=1.0, label="via3 (M3->M4)"),
    "m4":            dict(fc="#0ea5e9", ec="#0369a1", alpha=0.65, z=17, label="met4 (M4)"),
    "metal4":        dict(fc="#0ea5e9", ec="#0369a1", alpha=0.65, z=17, label="met4 (M4)"),
}


def plot_canvas(ax, canvas: LayoutCanvas, title: str, subtitle: str = "", show_cuts: bool = True):
    ax.set_facecolor("#ffffff")
    ordered = sorted(canvas.rects.keys(), key=lambda k: LAYER_STYLE.get(k, {}).get("z", 5))
    seen_labels = set()
    cut_layers = {"polycont", "ndiffc", "pdiffc", "nsubdiffcont", "psubdiffcont", "viali", "mcon"}
    for lyr in ordered:
        if not show_cuts and lyr in cut_layers:
            continue
        st = LAYER_STYLE.get(lyr, dict(fc="#cbd5e1", ec="#64748b", alpha=0.5, z=5, label=lyr))
        lbl_name = st["label"]
        for (x1, y1, x2, y2) in canvas.rects[lyr]:
            lbl = lbl_name if lbl_name not in seen_labels else "_nolegend_"
            seen_labels.add(lbl_name)
            ax.add_patch(Rectangle(
                (x1, y1), x2 - x1, y2 - y1,
                facecolor=st["fc"], edgecolor=st.get("ec", "none"),
                linewidth=st.get("lw", 0.45), alpha=st["alpha"], zorder=st["z"], label=lbl
            ))
    for lyr, lx, ly, nm in canvas.labels:
        ax.plot(lx, ly, "ko", markersize=3.5, zorder=25)
        ax.text(
            lx + 0.15, ly + 0.10, nm, fontsize=8.5, fontweight="bold", color="#0f172a",
            bbox=dict(boxstyle="round,pad=0.18", fc="#ffffff", ec="#94a3b8", alpha=0.90),
            zorder=26
        )
    bx1, by1, bx2, by2 = canvas.bbox()
    pad_x = max(1.0, (bx2 - bx1) * 0.06)
    pad_y = max(1.0, (by2 - by1) * 0.06)
    ax.set_xlim(bx1 - pad_x, bx2 + pad_x)
    ax.set_ylim(by1 - pad_y, by2 + pad_y)
    ax.set_aspect("equal")
    ax.grid(True, linestyle=":", linewidth=0.45, color="#cbd5e1", alpha=0.7)
    ax.set_xlabel("x (um)", fontsize=9.5)
    ax.set_ylabel("y (um)", fontsize=9.5)
    full_title = f"{title}\n{subtitle}" if subtitle else title
    ax.set_title(full_title, fontsize=9.2, fontweight="bold", pad=8)
