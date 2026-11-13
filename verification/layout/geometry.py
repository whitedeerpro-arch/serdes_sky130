"""Small flat Magic geometry helpers for PDK-based analog block builders.

Dimensions are micrometres. Device recognition layers come from the PDK,
never from an electrical symbol or a hand-drawn approximation of a device.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import magicutil as mu


@dataclass
class Cell:
    rects: dict[str, list[tuple[float, float, float, float]]] = field(default_factory=dict)
    labels: list[tuple[str, float, float, str]] = field(default_factory=list)

    @classmethod
    def read(cls, path: Path) -> Cell:
        text = path.read_text()
        if "magscale 1 2\n" not in text:
            raise ValueError(f"Expected 5 nm Magic file grid: {path}")
        cell = cls()
        layer = None
        for line in text.splitlines():
            if m := re.fullmatch(r"<< (\S+) >>", line):
                layer = m[1]
            elif line.startswith("rect "):
                cell.rects.setdefault(layer, []).append(tuple(int(x) / 200 for x in line.split()[1:]))
            elif m := re.fullmatch(r"[rf]label (\S+) (?:s )?(-?\d+) (-?\d+) (-?\d+) (-?\d+) \d+ (?:.* )?(\S+)", line):
                cell.labels.append((m[1], (int(m[2]) + int(m[4])) / 400,
                                    (int(m[3]) + int(m[5])) / 400, m[6]))
            elif line.startswith(("tri ", "use ")):
                raise ValueError(f"Flat rectangular geometry required: {path}")
        if not cell.rects:
            raise ValueError(f"No device geometry: {path}")
        return cell

    def bbox(self) -> tuple[float, float, float, float]:
        rs = [r for rects in self.rects.values() for r in rects]
        return min(r[0] for r in rs), min(r[1] for r in rs), max(r[2] for r in rs), max(r[3] for r in rs)

    def pins(self, name: str) -> list[tuple[float, float]]:
        pts = [(x, y) for _, x, y, label in self.labels if label == name]
        if not pts:
            raise ValueError(f"Missing physical PDK pin {name}")
        return pts

    def include(self, source: Cell, dx: float = 0, dy: float = 0,
                mirror_x: bool = False, mirror_y: bool = False) -> None:
        for layer, rects in source.rects.items():
            for x1, y1, x2, y2 in rects:
                if mirror_x:
                    x1, x2 = -x2, -x1
                if mirror_y:
                    y1, y2 = -y2, -y1
                self.rect(layer, x1 + dx, y1 + dy, x2 + dx, y2 + dy)

    def rect(self, layer: str, x1: float, y1: float, x2: float, y2: float) -> None:
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"Empty rectangle: {layer} {(x1, y1, x2, y2)}")
        self.rects.setdefault(layer, []).append((x1, y1, x2, y2))

    def pad(self, layer: str, x: float, y: float, w: float, h: float | None = None) -> None:
        h = w if h is None else h
        self.rect(layer, x - w / 2, y - h / 2, x + w / 2, y + h / 2)

    def via1(self, x: float, y: float) -> None:
        self.pad("metal1", x, y, .32)
        self.pad("via1", x, y, .26)
        self.pad("metal2", x, y, .32)

    def via2(self, x: float, y: float) -> None:
        self.pad("metal2", x, y, .4)
        self.pad("via2", x, y, .28)
        self.pad("metal3", x, y, .4)

    def body_contact(self, x: float, y: float) -> None:
        self.pad("viali", x, y, .17)
        self.pad("metal1", x, y, .32)
        self.via1(x, y)

    def wire(self, layer: str, points: list[tuple[float, float]], width: float) -> None:
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            if x1 != x2 and y1 != y2:
                raise ValueError("Manhattan path required")
            self.rect(layer, min(x1, x2) - width / 2, min(y1, y2) - width / 2,
                      max(x1, x2) + width / 2, max(y1, y2) + width / 2)

    def port(self, name: str, layer: str, x: float, y: float) -> None:
        self.labels.append((layer, x, y, name))

    def write(self, path: Path) -> None:
        lines = ["magic", "tech sky130A", "magscale 1 2", "timestamp 0"]
        for layer, rects in self.rects.items():
            lines.append(f"<< {layer} >>")
            for rect in rects:
                lines.append("rect " + " ".join(str(round(x * 200)) for x in rect))
        lines.append("<< labels >>")
        for i, (layer, x, y, name) in enumerate(self.labels, 1):
            x, y = round(x * 200), round(y * 200)
            lines += [f"rlabel {layer} {x} {y} {x} {y} 0 {name}", f"port {i} nsew"]
        lines += ["<< end >>", ""]
        path.write_text("\n".join(lines))


def pdk_device(work: Path, name: str, model: str, parameters: dict) -> Cell:
    """Draw a PDK primitive into a fresh cell, without changing Magic units first."""
    mu.new_cell(work / f"{name}.mag")
    params = " ".join(f"{k} {v}" for k, v in parameters.items())
    script = work / f"{name}.tcl"
    script.write_text(
        f"drc off\nload {name}\nbox values 0 0 0 0\n"
        f"set p [dict merge [sky130::{model}_defaults] [dict create {params}]]\n"
        f"sky130::{model}_draw $p\nsave {name}\nquit -noprompt\n"
    )
    result = mu.run_magic(script, work)
    (work / f"{name}.log").write_text(result.log)
    result.need(name)
    return Cell.read(work / f"{name}.mag")
