"""Route short SKY130A M2–M5 interconnects on a flat Magic layout.

The job file gives a flat, 5 nm grid search window in µm and a list of nets
with at least two terminals, each specified as [metal layer, x, y]. All
terminal paint must exist. Optional analog extensions support:
  - metal2 + via2 alongside the default metal3..metal5 stack
  - per-net `width_um` (scalar or per-layer dict)
  - per-net `extra_spacing_um` (with automatic pin-escape collar)
  - global `keepouts` (`[{"box_um": [x0, y0, x1, y1], "layers": [...]}]`)
  - differential / sensitive-pair soft proximity avoidance (`diff_pairs`,
    `coupling_weight`, `coupling_radius_um`) to reduce P/N mutual capacitance
  - multi-order net routing fallback and pair coupling/mismatch metrics

The CLI checks each completed candidate with the repository's standard Magic
DRC and Netgen LVS flow.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from heapq import heappop, heappush
import json
from pathlib import Path

import numpy as np

from geometry import Cell


ALL_LAYER_NAMES = ("metal2", "metal3", "metal4", "metal5")
LAYER_NAMES = ("metal3", "metal4", "metal5")
GRID_PER_UM = 200


@dataclass(frozen=True)
class Layer:
    half_width: int
    spacing: int
    preferred_axis: int


# Integer units are the Magic file's 5 nm grid. Spacing includes DRC margin
# over SKY130A nominal rules and increases near wide metal (> 3.0 um).
LAYERS = (
    Layer(28, 56, 1),    # 0: metal2 (0.28 um wide, 0.28 um spacing, vertical pref)
    Layer(36, 66, 0),    # 1: metal3 (0.36 um wide, 0.33 um spacing, horizontal pref)
    Layer(44, 66, 1),    # 2: metal4 (0.44 um wide, 0.33 um spacing, vertical pref)
    Layer(160, 324, 0),  # 3: metal5 (1.60 um wide, 1.62 um spacing, horizontal pref)
)
# (via_layer, half_cut, lower_half_pad, upper_half_pad, cut_edge_spacing, via_cost)
VIA_RULES = (
    ("via2", 28, 40, 52, 42, 420),   # 0: metal2 <-> metal3 (0.28 cut, 0.40 M2, 0.52 M3, 0.21 gap)
    ("via3", 32, 52, 52, 20, 440),   # 1: metal3 <-> metal4
    ("via4", 118, 156, 200, 88, 800),  # 2: metal4 <-> metal5
)
CONDUCTORS = {
    "metal2": (0,), "metal3": (1,), "metal4": (2,), "metal5": (3,),
    "via1": (0,), "via2": (0, 1), "via3": (1, 2), "via4": (2, 3),
    "mimcapcontact": (2,), "mimcap2contact": (3,),
}
STEP = 40
BEND_COST = 44
Node = tuple[int, int, int]
Box = tuple[int, int, int, int]


class RouteUnavailable(ValueError):
    """No path is available for the given net order and search bounds."""


def grid(value: float) -> int:
    result = round(value * GRID_PER_UM)
    if abs(result - value * GRID_PER_UM) > 1e-6:
        raise ValueError(f"Off-grid coordinate {value}")
    return result


def intersects(a: Box, b: Box) -> bool:
    x = min(a[2], b[2]) - max(a[0], b[0])
    y = min(a[3], b[3]) - max(a[1], b[1])
    return min(x, y) >= 0 and max(x, y) > 0


def axis_grid(lo: int, hi: int, coordinates: list[int]) -> np.ndarray:
    return np.array(sorted({lo, hi, *range(lo, hi, STEP), *coordinates}))


def _resolve_half_widths(net: dict) -> list[int]:
    """Return per-layer half-width in 5 nm ticks for `net`."""
    hw = [rule.half_width for rule in LAYERS]
    wspec = net.get("width_um")
    if wspec is None:
        return hw
    if isinstance(wspec, (int, float)):
        val = grid(float(wspec) / 2.0)
        if val <= 0:
            raise ValueError(f"Positive width_um required for net {net.get('name')}")
        return [max(val, rule.half_width) for rule in LAYERS]
    if isinstance(wspec, dict):
        for lname, wval in wspec.items():
            idx = ALL_LAYER_NAMES.index(lname)
            val = grid(float(wval) / 2.0)
            if val <= 0:
                raise ValueError(f"Positive width_um required for {net.get('name')}:{lname}")
            hw[idx] = val
        return hw
    raise ValueError(f"Unsupported width_um specification for net {net.get('name')}: {wspec!r}")


def _parse_keepouts(keepouts: list[dict] | None) -> list[tuple[Box, set[int]]]:
    parsed: list[tuple[Box, set[int]]] = []
    if not keepouts:
        return parsed
    for ko in keepouts:
        raw = ko["box_um"]
        if len(raw) != 4:
            raise ValueError(f"Keepout box_um must have 4 coordinates: {raw}")
        x0, y0, x1, y1 = (grid(float(v)) for v in raw)
        if x0 >= x1 or y0 >= y1:
            raise ValueError(f"Keepout box_um must be nonempty: {raw}")
        lay_names = ko.get("layers", ALL_LAYER_NAMES)
        lay_ids = {ALL_LAYER_NAMES.index(name) for name in lay_names}
        parsed.append(((x0, y0, x1, y1), lay_ids))
    return parsed


class Window:
    def __init__(self, base: Cell, box: Box, pins: list[Node],
                 keepouts: list[tuple[Box, set[int]]] | None = None):
        self.x = axis_grid(box[0], box[2], [x for x, _, _ in pins])
        self.y = axis_grid(box[1], box[3], [y for _, y, _ in pins])
        self.shape = (len(self.x), len(self.y))
        self.keepouts = keepouts or []
        self.paint: list[tuple[str, Box]] = []
        self.routed_segments: dict[str, list[tuple[int, Box]]] = {}
        padded_box = (box[0] - 550, box[1] - 550, box[2] + 550, box[3] + 550)
        for name, rects in base.rects.items():
            if name not in CONDUCTORS and name not in {"mimcap", "mimcap2"}:
                continue
            for rect in rects:
                b = tuple(grid(v) for v in rect)
                if intersects(b, padded_box):
                    self.paint.append((name, b))

    def point(self, node: Node) -> Node:
        x, y, layer = node
        return int(self.x.searchsorted(x)), int(self.y.searchsorted(y)), layer

    def owned_paint(self, pins: list[Node]) -> set[int]:
        """Trace conducting paint inside the window from the supplied access points."""
        pending = [
            i for i, (kind, (x0, y0, x1, y1)) in enumerate(self.paint)
            if any(layer in CONDUCTORS.get(kind, ()) and x0 <= x <= x1 and y0 <= y <= y1
                   for x, y, layer in pins)
        ]
        for x, y, layer in pins:
            if not any(layer in CONDUCTORS[self.paint[i][0]]
                       and self.paint[i][1][0] <= x <= self.paint[i][1][2]
                       and self.paint[i][1][1] <= y <= self.paint[i][1][3] for i in pending):
                raise ValueError(f"No conducting paint at {ALL_LAYER_NAMES[layer]} ({x/200}, {y/200})")
        owned = set(pending)
        while pending:
            name, rect = self.paint[pending.pop()]
            layers = CONDUCTORS[name]
            for i, (other, candidate) in enumerate(self.paint):
                if i in owned or not any(layer in CONDUCTORS.get(other, ()) for layer in layers):
                    continue
                if intersects(rect, candidate):
                    pending.append(i)
                    owned.add(i)
        return owned

    def mask_rect(self, mask: np.ndarray, b: Box, amount: int) -> None:
        x0, x1 = self.x.searchsorted([b[0] - amount, b[2] + amount], side="left")
        y0, y1 = self.y.searchsorted([b[1] - amount, b[3] + amount], side="left")
        mask[x0:x1, y0:y1] = True

    def metal_mask(self, layer: int, half_width: int, owned: set[int],
                   extra_spacing: int = 0,
                   escape_pins: list[Node] | None = None,
                   escape_radius: int = 0) -> np.ndarray:
        base_mask = np.zeros(self.shape, dtype=bool)
        extra_mask = np.zeros(self.shape, dtype=bool) if extra_spacing > 0 else None
        for i, (kind, b) in enumerate(self.paint):
            if i in owned:
                continue
            if layer in CONDUCTORS.get(kind, ()):
                wide = min(b[2] - b[0], b[3] - b[1]) > 600
                spacing = max(LAYERS[layer].spacing, 86 if wide else 0)
                self.mask_rect(base_mask, b, half_width + spacing)
                if extra_mask is not None:
                    self.mask_rect(extra_mask, b, half_width + spacing + extra_spacing)
            elif (kind, layer) in {("mimcap", 1), ("mimcap2", 2)}:
                self.mask_rect(base_mask, b, half_width + 272)
        for kbox, klayers in self.keepouts:
            if layer in klayers:
                self.mask_rect(base_mask, kbox, half_width)
        if extra_mask is not None:
            if escape_pins and escape_radius > 0:
                for px, py, _ in escape_pins:
                    x0, x1 = self.x.searchsorted([px - escape_radius, px + escape_radius], side="left")
                    y0, y1 = self.y.searchsorted([py - escape_radius, py + escape_radius], side="left")
                    extra_mask[x0:x1, y0:y1] = False
            base_mask |= extra_mask
        return base_mask

    def via_mask(self, lower: int, owned: set[int],
                 half_widths: list[int] | None = None) -> np.ndarray:
        name, half_cut, bottom, top, spacing, _ = VIA_RULES[lower]
        if half_widths is not None:
            bottom = max(bottom, half_widths[lower])
            top = max(top, half_widths[lower + 1])
        mask = self.metal_mask(lower, bottom, owned) | self.metal_mask(lower + 1, top, owned)
        for kind, b in self.paint:
            # Avoid stacking new same-level cuts with existing cuts, even on the same net.
            if kind == name or (name, kind) in {("via3", "mimcapcontact"), ("via4", "mimcap2contact")}:
                self.mask_rect(mask, b, half_cut + spacing)
        return mask

    def coupling_penalties(self, partner_names: set[str], radius: int,
                           weight: float) -> list[np.ndarray] | None:
        """Build smooth per-layer proximity & overlap penalties against `partner_names`."""
        if not partner_names or weight <= 0.0 or radius <= 0:
            return None
        segs: list[tuple[int, Box]] = []
        for pname in partner_names:
            segs.extend(self.routed_segments.get(pname, ()))
        if not segs:
            return None
        penalties = [np.zeros(self.shape, dtype=np.int32) for _ in LAYERS]
        xv = self.x[:, None]
        yv = self.y[None, :]
        scale_same = weight * STEP
        scale_adj = 0.5 * weight * STEP
        for slay, (bx0, by0, bx1, by1) in segs:
            # Distance from grid nodes to segment box
            dx = np.maximum(0, np.maximum(bx0 - xv, xv - bx1))
            dy = np.maximum(0, np.maximum(by0 - yv, yv - by1))
            dist = dx + dy
            near = dist < radius
            if np.any(near):
                add = np.where(near, np.rint(scale_same * (1.0 - dist / radius)), 0).astype(np.int32)
                penalties[slay] += add
            # Adjacent-layer broadside overlap penalty
            overlap = (dx == 0) & (dy == 0)
            if np.any(overlap):
                ov_add = int(round(scale_adj))
                for adj in (slay - 1, slay + 1):
                    if 0 <= adj < len(LAYERS):
                        penalties[adj][overlap] += ov_add
        return penalties

    def search(self, starts: set[Node], goal: Node, metals: list[np.ndarray],
               vias: list[np.ndarray], allowed: set[int],
               penalties: list[np.ndarray] | None = None) -> list[Node]:
        def heuristic(x: int, y: int) -> int:
            return abs(int(self.x[x] - self.x[goal[0]])) + abs(int(self.y[y] - self.y[goal[1]]))

        queue = []
        dist = {}
        parent = {}
        for x, y, layer in sorted(starts):
            if not metals[layer][x, y]:
                initial = (x, y, layer, -1)
                dist[initial] = 0
                heappush(queue, (heuristic(x, y), 0, initial))
        while queue:
            _, prev_cost, state = heappop(queue)
            x, y, layer, prev_axis = state
            if prev_cost != dist[state]:
                continue
            if (x, y, layer) == goal:
                path = [state[:3]]
                while state in parent:
                    state = parent[state]
                    path.append(state[:3])
                return path[::-1]
            edges = []
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                xx, yy = x + dx, y + dy
                if not (0 <= xx < len(self.x) and 0 <= yy < len(self.y)) or metals[layer][xx, yy]:
                    continue
                # Consecutive coordinates are at most 0.20 µm apart. Even the
                # narrowest blocked rectangle spans over twice that after inflation.
                axis = int(dx == 0)
                distance = abs(int(self.x[xx] - self.x[x])) + abs(int(self.y[yy] - self.y[y]))
                cost = distance if axis == LAYERS[layer].preferred_axis else distance * 3 // 2
                if penalties is not None:
                    p = int(penalties[layer][xx, yy])
                    if p > 0:
                        cost += (p * max(distance, 1)) // STEP
                edges.append(((xx, yy, layer, axis), cost + (BEND_COST if prev_axis not in (-1, axis) else 0)))
            for neighbor in (layer - 1, layer + 1):
                if neighbor in allowed and not vias[min(layer, neighbor)][x, y]:
                    edges.append(((x, y, neighbor, -1), VIA_RULES[min(layer, neighbor)][-1]))
            for new, cost in edges:
                total = prev_cost + cost
                if total < dist.get(new, float("inf")):
                    parent[new] = state
                    dist[new] = total
                    heappush(queue, (total + heuristic(*new[:2]), total, new))
        raise RouteUnavailable("No route within the supplied window and layer set")

    def add_rect(self, dst: Cell, layer: str, box: Box) -> None:
        self.paint.append((layer, box))
        dst.rect(layer, *(n / GRID_PER_UM for n in box))

    def emit(self, dst: Cell, path: list[Node], length: Counter, cuts: Counter,
             half_widths: list[int] | None = None,
             net_name: str | None = None) -> None:
        coords = [(int(self.x[x]), int(self.y[y]), z) for x, y, z in path]
        corners = [coords[0]]
        for a, b, c in zip(coords, coords[1:], coords[2:]):
            if a[2] == b[2] == c[2] and not (a[0] == b[0] == c[0] or a[1] == b[1] == c[1]):
                corners.append(b)
            elif a[2] != b[2] or b[2] != c[2]:
                corners.append(b)
        corners.append(coords[-1])
        seg_list = self.routed_segments.setdefault(net_name, []) if net_name else None
        for (x, y, z), (xx, yy, zz) in zip(corners, corners[1:]):
            if z == zz:
                d = half_widths[z] if half_widths is not None else LAYERS[z].half_width
                name = ALL_LAYER_NAMES[z]
                box = (min(x, xx) - d, min(y, yy) - d, max(x, xx) + d, max(y, yy) + d)
                self.add_rect(dst, name, box)
                if seg_list is not None:
                    seg_list.append((z, box))
                length[name] += abs(x - xx) + abs(y - yy)
                continue
            lower = min(z, zz)
            name, cut, bottom, top, _, _ = VIA_RULES[lower]
            if half_widths is not None:
                bottom = max(bottom, half_widths[lower])
                top = max(top, half_widths[lower + 1])
            for layer_i, layer, radius in (
                (-1, name, cut),
                (lower, ALL_LAYER_NAMES[lower], bottom),
                (lower + 1, ALL_LAYER_NAMES[lower + 1], top),
            ):
                box = (x - radius, y - radius, x + radius, y + radius)
                self.add_rect(dst, layer, box)
                if seg_list is not None and layer_i >= 0:
                    seg_list.append((layer_i, box))
            cuts[name] += 1


def _pair_metrics(work: Window, reports: dict, diff_pairs: list[tuple[str, str]],
                  near_um: float = 3.0) -> dict[str, dict]:
    """Compute length mismatch & proximity coupling geometry metrics for diff pairs."""
    near_ticks = grid(near_um)
    out: dict[str, dict] = {}
    for a, b in diff_pairs:
        if a not in reports or b not in reports:
            continue
        la = sum(reports[a]["length_um"].values())
        lb = sum(reports[b]["length_um"].values())
        segs_a = work.routed_segments.get(a, [])
        segs_b = work.routed_segments.get(b, [])
        parallel_ticks = 0
        overlap_area_ticks2 = 0
        min_same_gap = None
        for za, ba in segs_a:
            for zb, bb in segs_b:
                ox = min(ba[2], bb[2]) - max(ba[0], bb[0])
                oy = min(ba[3], bb[3]) - max(ba[1], bb[1])
                if za == zb:
                    gx = max(0, -ox)
                    gy = max(0, -oy)
                    gap = max(gx, gy)
                    if min_same_gap is None or gap < min_same_gap:
                        min_same_gap = gap
                    if gx <= near_ticks and oy > 0:
                        parallel_ticks += oy
                    elif gy <= near_ticks and ox > 0:
                        parallel_ticks += ox
                elif abs(za - zb) == 1 and ox > 0 and oy > 0:
                    overlap_area_ticks2 += ox * oy
        out[f"{a}:{b}"] = {
            "length_a_um": round(la, 3),
            "length_b_um": round(lb, 3),
            "length_mismatch_um": round(abs(la - lb), 3),
            "same_layer_parallel_um": round(parallel_ticks / GRID_PER_UM, 3),
            "min_same_layer_gap_um": None if min_same_gap is None else round(min_same_gap / GRID_PER_UM, 3),
            "adjacent_layer_overlap_um2": round(overlap_area_ticks2 / (GRID_PER_UM ** 2), 4),
        }
    return out


def route(base: Cell, box_um: list[float], nets: list[dict],
          layers: tuple[str, ...] = LAYER_NAMES, *,
          keepouts: list[dict] | None = None,
          diff_pairs: list[tuple[str, str]] | None = None,
          coupling_weight: float = 0.0,
          coupling_radius_um: float = 2.5,
          pair_diagnostics: dict | None = None) -> tuple[Cell, dict]:
    box = tuple(grid(v) for v in box_um)
    allowed = {ALL_LAYER_NAMES.index(layer) for layer in layers}
    terminals = [
        [(grid(x), grid(y), ALL_LAYER_NAMES.index(layer)) for layer, x, y in net["terminals"]]
        for net in nets
    ]
    all_pins = [point for pins in terminals for point in pins]
    if len(box) != 4 or box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError("Expected a nonempty window [x0, y0, x1, y1]")
    if any(len(p) < 2 or len(p) != len(set(p)) for p in terminals):
        raise ValueError("Expected at least two distinct terminals per net")
    if len({net["name"] for net in nets}) != len(nets) or not nets:
        raise ValueError("Expected unique, nonempty nets")
    if len(all_pins) != len(set(all_pins)):
        raise ValueError("Terminals on different nets must use distinct ports")
    if any(not (box[0] <= x <= box[2] and box[1] <= y <= box[3] and layer in allowed)
           for x, y, layer in all_pins):
        raise ValueError("Terminal is outside the routing window or on a disabled layer")

    parsed_keepouts = _parse_keepouts(keepouts)
    pair_map: dict[str, set[str]] = {}
    if diff_pairs:
        for a, b in diff_pairs:
            pair_map.setdefault(a, set()).add(b)
            pair_map.setdefault(b, set()).add(a)

    work = Window(base, box, all_pins, keepouts=parsed_keepouts)
    dst = Cell(rects={k: list(v) for k, v in base.rects.items()}, labels=list(base.labels))
    reports = {}
    for net, pins in zip(nets, terminals):
        net_name = net["name"]
        half_widths = _resolve_half_widths(net)
        extra_spacing = grid(float(net.get("extra_spacing_um", 0.0)))
        escape_radius = grid(float(net.get(
            "escape_radius_um",
            max(float(net.get("extra_spacing_um", 0.0)) + 0.8, 1.5) if extra_spacing > 0 else 0.0,
        )))
        partners = set(pair_map.get(net_name, ())) | set(net.get("avoid_nets", ()))
        net_cw = float(net.get("coupling_weight", coupling_weight))
        net_cr = grid(float(net.get("coupling_radius_um", coupling_radius_um)))
        penalties = work.coupling_penalties(partners, net_cr, net_cw)

        length: Counter = Counter()
        cuts: Counter = Counter()
        port_nodes = [work.point(pin) for pin in pins]
        tree = {port_nodes[0]}
        for goal in port_nodes[1:]:
            if goal in tree:
                continue
            owned = work.owned_paint(pins)
            metals = [
                work.metal_mask(
                    i, half_widths[i], owned,
                    extra_spacing=extra_spacing,
                    escape_pins=pins,
                    escape_radius=escape_radius,
                )
                for i in range(len(LAYERS))
            ]
            vias = [work.via_mask(i, owned, half_widths=half_widths) for i in range(len(VIA_RULES))]
            try:
                path = work.search(tree, goal, metals, vias, allowed, penalties=penalties)
            except RouteUnavailable as error:
                raise RouteUnavailable(f"{net_name} terminal {goal}: {error}") from error
            work.emit(dst, path, length, cuts, half_widths=half_widths, net_name=net_name)
            tree.update(path)
        reports[net_name] = {
            "length_um": {name: ticks / GRID_PER_UM for name, ticks in length.items()},
            "vias": dict(cuts),
        }
    if pair_diagnostics is not None and diff_pairs:
        pair_diagnostics.update(_pair_metrics(work, reports, diff_pairs))
    return dst, reports


def _net_hpwl(net: dict) -> float:
    xs = [float(t[1]) for t in net["terminals"]]
    ys = [float(t[2]) for t in net["terminals"]]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def candidate_net_orders(nets: list[dict]) -> list[list[dict]]:
    """Return deduplicated net orders: given, reversed, shortest-first, longest-first."""
    raw = [nets]
    if len(nets) > 1:
        raw.append(nets[::-1])
        raw.append(sorted(nets, key=_net_hpwl))
        raw.append(sorted(nets, key=_net_hpwl, reverse=True))
    seen = set()
    unique = []
    for order in raw:
        key = tuple(n["name"] for n in order)
        if key not in seen:
            seen.add(key)
            unique.append(order)
    return unique


def write_metal_delta(source: Path, target: Path, before: Cell, after: Cell) -> None:
    """Keep Magic labels, port indices, properties and untouched paint verbatim."""
    remaining = {}
    for layer, rects in after.rects.items():
        original = before.rects.get(layer, [])
        if rects[:len(original)] != original:
            raise ValueError(f"Non-additive edit on layer {layer}")
        if len(rects) > len(original):
            remaining[f"<< {layer} >>\n"] = [
                "rect " + " ".join(str(grid(x)) for x in box) + "\n"
                for box in rects[len(original):]
            ]
    section = None
    with target.open("x") as out:
        for line in source.read_text().splitlines(keepends=True):
            if line.startswith("<< "):
                out.writelines(remaining.pop(section, ()))
                section = line
            if line in ("<< labels >>\n", "<< properties >>\n", "<< end >>\n"):
                for header, added in remaining.items():
                    out.write(header)
                    out.writelines(added)
                remaining.clear()
            out.write(line)


def main() -> None:
    from check import exported_ports
    from review_cell import review

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path)
    parser.add_argument("job", type=Path)
    parser.add_argument("output_dir", type=Path, help="new run directory inside the repository")
    parser.add_argument("--reference", required=True, type=Path, help="SPICE reference for the whole cell")
    args = parser.parse_args()
    job = json.loads(args.job.read_text())
    base = Cell.read(args.base)
    reference_ports = exported_ports(args.reference, args.base.stem)
    if not reference_ports:
        parser.error("the reference must export the top-level ports in the target cell's subcircuit")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    ref = args.output_dir / "reference.spice"
    ref.write_bytes(args.reference.read_bytes())
    orders = candidate_net_orders(job["nets"])
    keepouts = job.get("keepouts")
    diff_pairs = [tuple(p) for p in job.get("diff_pairs", ())]
    coupling_weight = float(job.get("coupling_weight", 0.0))
    coupling_radius_um = float(job.get("coupling_radius_um", 2.5))

    records = []
    accepted = None
    for number, nets in enumerate(orders, 1):
        attempt = args.output_dir / f"attempt_{number}"
        attempt.mkdir()
        row = {"attempt": attempt.name, "net_order": [n["name"] for n in nets]}
        records.append(row)
        pdiag: dict = {}
        try:
            candidate, row["nets"] = route(
                base, job["window_um"], nets, tuple(job.get("layers", LAYER_NAMES)),
                keepouts=keepouts,
                diff_pairs=diff_pairs or None,
                coupling_weight=coupling_weight,
                coupling_radius_um=coupling_radius_um,
                pair_diagnostics=pdiag if diff_pairs else None,
            )
        except RouteUnavailable as error:
            row["error"] = str(error)
            continue
        if pdiag:
            row["diff_pairs"] = pdiag
        mag = attempt / args.base.name
        write_metal_delta(args.base, mag, base, candidate)
        checked = review(mag, ref, attempt / "verify")
        row["physical_passed"] = checked["physical_passed"]
        row["exact_port_order"] = checked["ports"] == reference_ports
        if row["physical_passed"] and row["exact_port_order"]:
            accepted = str(mag.relative_to(args.output_dir))
            break
    (args.output_dir / "summary.json").write_text(
        json.dumps({"verified_layout": accepted, "attempts": records}, indent=2) + "\n"
    )
    if accepted is None:
        parser.exit(1, "No route passed DRC, LVS and the exact port-order check. See the attempt logs.\n")
    print(args.output_dir / accepted)


if __name__ == "__main__":
    main()
