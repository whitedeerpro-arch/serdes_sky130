"""Analog / Mixed-Signal Macro Placement, Port Redistribution & Whitespace Optimizer.

Operates directly on signed-off flat SKY130A Magic `.mag` macros and digital PnR
`.def` blocks (no external EDA solver required):
  1. Macro micro-placement & orientation optimization (`optimize_macro_positions`):
     Minimizes weighted HPWL + bounding-box area subject to strict zero-overlap,
     magnetic / guard-ring halo clearances, and grid snapping.
  2. Cardinal perimeter port redistribution (`optimize_port_distribution`):
     Solves globally optimal minimum-detour, zero-crossing 1D port coordinates
     using Pool-Adjacent-Violators (PAV) isotonic projection with minimum pitch
     and differential-pair grouping.
  3. Inter-macro bus alignment & crossing audit (`audit_bus_alignment`):
     Quantifies pin-order inversions (crossings), lateral skew, and Manhattan
     wirelength between two mating macro edges.
  4. Dead-whitespace & pocket discovery (`analyze_whitespace`):
     Extracts maximal empty rectangular pockets inside a macro/chip floorplan
     for decap, bias, or inductor placement.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from itertools import product
from pathlib import Path
import re
from typing import Iterable

from geometry import Cell


ORIENTS = ("R0", "MX", "MY", "R180")


@dataclass(frozen=True)
class MacroSpec:
    """Physical geometry & local ports of a macro normalized to [0..W] x [0..H]."""
    name: str
    width_um: float
    height_um: float
    ports_local: dict[str, tuple[float, float, str]]  # port -> (lx, ly, layer)
    bbox_orig_um: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    halo_um: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # (W, S, E, N)
    m5_area_um2: float = 0.0


@dataclass(frozen=True)
class Placement:
    """Placed origin (x, y) of normalized [0..W]x[0..H] macro box + orientation."""
    name: str
    x: float
    y: float
    orient: str = "R0"
    locked: bool = False
    x_bounds: tuple[float, float] | None = None
    y_bounds: tuple[float, float] | None = None
    allowed_orients: tuple[str, ...] = ("R0",)


@dataclass(frozen=True)
class NetSpec:
    """Inter-macro net connecting `(macro_name, port_name)` terminals.

    Fixed world points can be given as `("@FIXED", f"{x},{y}")`.
    """
    name: str
    pins: tuple[tuple[str, str], ...]
    weight: float = 1.0


def snap(value: float, grid_um: float = 0.005) -> float:
    return round(round(value / grid_um) * grid_um, 6)


def transform_local(lx: float, ly: float, w: float, h: float, orient: str) -> tuple[float, float]:
    if orient == "R0":
        return (lx, ly)
    if orient == "MX":
        return (w - lx, ly)
    if orient == "MY":
        return (lx, h - ly)
    if orient == "R180":
        return (w - lx, h - ly)
    raise ValueError(f"Unsupported orient {orient!r}; expected one of {ORIENTS}")


def macro_from_mag(name: str, mag_path: Path,
                   halo_um: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)) -> MacroSpec:
    cell = Cell.read(mag_path)
    bx0, by0, bx1, by1 = cell.bbox()
    w = round(bx1 - bx0, 4)
    h = round(by1 - by0, 4)
    ports = {
        pname: (round(px - bx0, 4), round(py - by0, 4), layer)
        for layer, px, py, pname in cell.labels
    }
    m5_area = sum((x2 - x1) * (y2 - y1) for x1, y1, x2, y2 in cell.rects.get("metal5", ()))
    return MacroSpec(
        name=name,
        width_um=w,
        height_um=h,
        ports_local=ports,
        bbox_orig_um=(round(bx0, 4), round(by0, 4), round(bx1, 4), round(by1, 4)),
        halo_um=halo_um,
        m5_area_um2=round(m5_area, 3),
    )


def macro_from_def(name: str, def_path: Path,
                   halo_um: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)) -> MacroSpec:
    text = def_path.read_text()
    units = int(re.search(r"UNITS DISTANCE MICRONS (\d+)", text).group(1))
    m_die = re.search(
        r"DIEAREA \(\s*([-\d]+)\s+([-\d]+)\s*\)\s*\(\s*([-\d]+)\s+([-\d]+)\s*\)", text
    )
    dx0, dy0, dx1, dy1 = [int(v) / units for v in m_die.groups()]
    pins_block = re.search(r"PINS \d+ ;(.*?)END PINS", text, re.S).group(1)
    ports: dict[str, tuple[float, float, str]] = {}
    for m in re.finditer(
        r"-\s+(\S+)\s+\+\s+NET\s+\S+.*?\+\s+LAYER\s+(\S+).*?\+\s+PLACED\s+\(\s*([-\d]+)\s+([-\d]+)\s*\)",
        pins_block,
        re.S,
    ):
        pname, layer, px, py = m.group(1), m.group(2), int(m.group(3)) / units, int(m.group(4)) / units
        if pname in ("VPWR", "VGND"):
            continue
        ports[pname] = (round(px - dx0, 4), round(py - dy0, 4), layer)
    return MacroSpec(
        name=name,
        width_um=round(dx1 - dx0, 4),
        height_um=round(dy1 - dy0, 4),
        ports_local=ports,
        bbox_orig_um=(round(dx0, 4), round(dy0, 4), round(dx1, 4), round(dy1, 4)),
        halo_um=halo_um,
    )


def macro_world_box(spec: MacroSpec, pl: Placement, include_halo: bool = False) -> tuple[float, float, float, float]:
    x0, y0 = pl.x, pl.y
    x1, y1 = pl.x + spec.width_um, pl.y + spec.height_um
    if include_halo:
        hw, hs, he, hn = spec.halo_um
        return (x0 - hw, y0 - hs, x1 + he, y1 + hn)
    return (x0, y0, x1, y1)


def world_port_xy(spec: MacroSpec, pl: Placement, port: str) -> tuple[float, float]:
    lx, ly, _ = spec.ports_local[port]
    tx, ty = transform_local(lx, ly, spec.width_um, spec.height_um, pl.orient)
    return (pl.x + tx, pl.y + ty)


def _overlap_area(a: tuple[float, float, float, float], b: tuple[float, float, float, float],
                  tol: float = 1e-6) -> float:
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    if ox <= tol or oy <= tol:
        return 0.0
    return ox * oy


def _box_clearance(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Chebyshev separation between two axis-aligned boxes (negative if overlapping)."""
    gx = max(a[0] - b[2], b[0] - a[2])
    gy = max(a[1] - b[3], b[1] - a[3])
    return max(gx, gy)


def evaluate_floorplan(
    macros: dict[str, MacroSpec],
    placements: dict[str, Placement],
    nets: list[NetSpec],
    *,
    pair_clearances: dict[tuple[str, str], float] | None = None,
) -> dict:
    """Evaluate area, HPWL, overlaps, pairwise clearances, and fill ratio."""
    names = sorted(macros.keys())
    boxes = {n: macro_world_box(macros[n], placements[n], include_halo=False) for n in names}
    hboxes = {n: macro_world_box(macros[n], placements[n], include_halo=True) for n in names}

    bx0 = min(b[0] for b in boxes.values())
    by0 = min(b[1] for b in boxes.values())
    bx1 = max(b[2] for b in boxes.values())
    by1 = max(b[3] for b in boxes.values())
    width = round(bx1 - bx0, 4)
    height = round(by1 - by0, 4)
    bbox_area = round(width * height, 2)
    macro_area = sum(macros[n].width_um * macros[n].height_um for n in names)

    hard_overlap = 0.0
    halo_violations: list[dict] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            ov = _overlap_area(boxes[a], boxes[b])
            if ov > 0.0:
                hard_overlap += ov
            hov = _overlap_area(hboxes[a], boxes[b]) + _overlap_area(boxes[a], hboxes[b])
            if hov > 0.0:
                halo_violations.append({"pair": [a, b], "type": "halo_overlap", "area_um2": round(hov, 3)})
            if pair_clearances:
                req = pair_clearances.get((a, b), pair_clearances.get((b, a)))
                if req is not None:
                    clr = _box_clearance(boxes[a], boxes[b])
                    if clr < req - 1e-6:
                        halo_violations.append({
                            "pair": [a, b], "type": "min_clearance",
                            "actual_um": round(clr, 3), "required_um": req,
                        })

    per_net_hpwl: dict[str, float] = {}
    total_hpwl = 0.0
    weighted_hpwl = 0.0
    for net in nets:
        pts: list[tuple[float, float]] = []
        for mname, pname in net.pins:
            if mname == "@FIXED":
                fx, fy = (float(v) for v in pname.split(","))
                pts.append((fx, fy))
            else:
                pts.append(world_port_xy(macros[mname], placements[mname], pname))
        hpwl = (max(p[0] for p in pts) - min(p[0] for p in pts)) + (max(p[1] for p in pts) - min(p[1] for p in pts))
        per_net_hpwl[net.name] = round(hpwl, 3)
        total_hpwl += hpwl
        weighted_hpwl += net.weight * hpwl

    return {
        "bbox_um": [round(bx0, 3), round(by0, 3), round(bx1, 3), round(by1, 3)],
        "width_um": width,
        "height_um": height,
        "bbox_area_um2": bbox_area,
        "macro_area_um2": round(macro_area, 2),
        "fill_pct": round(100.0 * macro_area / bbox_area, 2) if bbox_area > 0 else 0.0,
        "whitespace_pct": round(100.0 * (1.0 - macro_area / bbox_area), 2) if bbox_area > 0 else 0.0,
        "aspect_ratio": round(width / height, 3) if height > 0 else 0.0,
        "hard_overlap_um2": round(hard_overlap, 4),
        "halo_violations": halo_violations,
        "feasible": hard_overlap <= 1e-6 and not halo_violations,
        "total_hpwl_um": round(total_hpwl, 3),
        "weighted_hpwl_um": round(weighted_hpwl, 3),
        "per_net_hpwl_um": per_net_hpwl,
    }


def optimize_macro_positions(
    macros: dict[str, MacroSpec],
    placements: dict[str, Placement],
    nets: list[NetSpec],
    *,
    area_weight: float = 0.02,
    pair_clearances: dict[tuple[str, str], float] | None = None,
    steps_um: tuple[float, ...] = (8.0, 4.0, 2.0, 1.0, 0.5, 0.2, 0.1),
    grid_um: float = 0.1,
    max_rounds: int = 8,
) -> tuple[dict[str, Placement], dict]:
    """Optimize unlocked macro orientations and (x, y) positions without overlap.

    Minimizes `weighted_hpwl_um + area_weight * bbox_area_um2` via discrete
    orientation search followed by multi-scale coordinate pattern search.
    """
    before = evaluate_floorplan(macros, placements, nets, pair_clearances=pair_clearances)
    cur = dict(placements)
    movable = [n for n, pl in placements.items() if not pl.locked]

    def score(state: dict[str, Placement]) -> tuple[bool, float, dict]:
        ev = evaluate_floorplan(macros, state, nets, pair_clearances=pair_clearances)
        cost = ev["weighted_hpwl_um"] + area_weight * ev["bbox_area_um2"]
        return ev["feasible"], cost, ev

    # 1. Exact orientation search when combinatorial space is small (<= 64)
    orient_choices = [cur[n].allowed_orients for n in movable]
    n_comb = 1
    for ch in orient_choices:
        n_comb *= len(ch)
    best_ok, best_cost, best_ev = score(cur)
    if 1 < n_comb <= 64:
        for combo in product(*orient_choices):
            cand = dict(cur)
            for n, ori in zip(movable, combo):
                cand[n] = replace(cand[n], orient=ori)
            ok, cost, ev = score(cand)
            if ok and (not best_ok or cost < best_cost - 1e-9):
                cur, best_ok, best_cost, best_ev = cand, ok, cost, ev

    # 2. Multi-scale coordinate descent (pattern search) on unlocked macros
    for step in steps_um:
        for _ in range(max_rounds):
            improved = False
            for n in movable:
                pl = cur[n]
                for dx, dy in ((-step, 0.0), (step, 0.0), (0.0, -step), (0.0, step),
                               (-step, -step), (-step, step), (step, -step), (step, step)):
                    nx = snap(pl.x + dx, grid_um)
                    ny = snap(pl.y + dy, grid_um)
                    if pl.x_bounds is not None and not (pl.x_bounds[0] - 1e-9 <= nx <= pl.x_bounds[1] + 1e-9):
                        continue
                    if pl.y_bounds is not None and not (pl.y_bounds[0] - 1e-9 <= ny <= pl.y_bounds[1] + 1e-9):
                        continue
                    cand = dict(cur)
                    cand[n] = replace(pl, x=nx, y=ny)
                    ok, cost, ev = score(cand)
                    if ok and (not best_ok or cost < best_cost - 1e-9):
                        cur, best_ok, best_cost, best_ev = cand, ok, cost, ev
                        pl = cur[n]
                        improved = True
            if not improved:
                break

    delta_area = round(best_ev["bbox_area_um2"] - before["bbox_area_um2"], 2)
    delta_hpwl = round(best_ev["weighted_hpwl_um"] - before["weighted_hpwl_um"], 3)
    return cur, {
        "before": before,
        "after": best_ev,
        "delta_area_um2": delta_area,
        "delta_area_pct": round(100.0 * delta_area / before["bbox_area_um2"], 2) if before["bbox_area_um2"] else 0.0,
        "delta_weighted_hpwl_um": delta_hpwl,
        "delta_weighted_hpwl_pct": round(100.0 * delta_hpwl / before["weighted_hpwl_um"], 2) if before["weighted_hpwl_um"] else 0.0,
        "moved_macros": {
            n: {
                "before": [placements[n].x, placements[n].y, placements[n].orient],
                "after": [cur[n].x, cur[n].y, cur[n].orient],
                "shift_um": [round(cur[n].x - placements[n].x, 3), round(cur[n].y - placements[n].y, 3)],
            }
            for n in movable
        },
    }


def _pav_min_spacing(targets: list[float], spacings: list[float], lo: float, hi: float) -> list[float]:
    """Exact Pool-Adjacent-Violators (PAV) L2 projection onto:
        x_0 >= lo, x_{k+1} - x_k >= spacings[k], x_{n-1} <= hi.
    """
    n = len(targets)
    if n == 0:
        return []
    offsets = [0.0]
    for s in spacings:
        offsets.append(offsets[-1] + s)
    total_span = offsets[-1]
    if total_span > (hi - lo) + 1e-9:
        raise ValueError(f"Requested minimum span {total_span:.3f} um exceeds edge span {hi - lo:.3f} um")
    # Transform y_i = x_i - offsets[i] so constraint becomes lo <= y_0 <= y_1 <= ... <= y_{n-1} <= hi - total_span
    z = [t - o for t, o in zip(targets, offsets)]
    # Standard PAV blocks: [sum_val, count]
    blocks: list[list[float]] = []
    for val in z:
        blocks.append([val, 1.0])
        while len(blocks) >= 2 and (blocks[-2][0] / blocks[-2][1]) > (blocks[-1][0] / blocks[-1][1]):
            b2 = blocks.pop()
            blocks[-1][0] += b2[0]
            blocks[-1][1] += b2[1]
    y_max = hi - total_span
    y: list[float] = []
    for s, cnt in blocks:
        mean = min(max(s / cnt, lo), y_max)
        y.extend([mean] * int(cnt))
    return [yi + oi for yi, oi in zip(y, offsets)]


def count_inversions(order_a: list[str], order_b: list[str]) -> int:
    """Count pairwise crossings between two linear orderings of the same pin set."""
    pos = {name: i for i, name in enumerate(order_b)}
    seq = [pos[name] for name in order_a if name in pos]
    inv = 0
    for i in range(len(seq)):
        for j in range(i + 1, len(seq)):
            if seq[i] > seq[j]:
                inv += 1
    return inv


def audit_bus_alignment(
    src_ports_xy: dict[str, tuple[float, float]],
    dst_ports_xy: dict[str, tuple[float, float]],
    port_map: dict[str, str],
    axis: str = "x",
) -> dict:
    """Measure crossings, lateral skew, and HPWL between two mating macro edges."""
    idx = 0 if axis == "x" else 1
    src_order = sorted(port_map.keys(), key=lambda p: src_ports_xy[p][idx])
    dst_order_mapped = sorted(port_map.keys(), key=lambda p: dst_ports_xy[port_map[p]][idx])
    crossings = count_inversions(src_order, dst_order_mapped)
    lateral_diffs = [
        abs(src_ports_xy[s][idx] - dst_ports_xy[d][idx])
        for s, d in port_map.items()
    ]
    manhattans = [
        abs(src_ports_xy[s][0] - dst_ports_xy[d][0]) + abs(src_ports_xy[s][1] - dst_ports_xy[d][1])
        for s, d in port_map.items()
    ]
    return {
        "bit_count": len(port_map),
        "crossings": crossings,
        "mean_lateral_skew_um": round(sum(lateral_diffs) / len(lateral_diffs), 3) if lateral_diffs else 0.0,
        "max_lateral_skew_um": round(max(lateral_diffs), 3) if lateral_diffs else 0.0,
        "total_lateral_skew_um": round(sum(lateral_diffs), 3),
        "total_manhattan_um": round(sum(manhattans), 3),
        "src_order": src_order,
        "dst_order": dst_order_mapped,
    }


def optimize_port_distribution(
    range_um: tuple[float, float],
    internal_coords: dict[str, float],
    external_coords: dict[str, float] | None = None,
    *,
    min_pitch_um: float = 0.90,
    pair_pitch_um: dict[tuple[str, str], float] | None = None,
    order_by: str = "external",
    grid_um: float = 0.01,
) -> dict:
    """Compute globally optimal zero-crossing 1D perimeter port coordinates.

    `order_by`:
      - `"external"`: match external mating pin order (eliminates 100% of external bus crossings!)
      - `"internal"`: preserve internal pin order
      - `"midpoint"`: order by `(internal + external)/2`
    """
    lo, hi = range_um
    names = list(internal_coords.keys())
    if external_coords is None:
        external_coords = dict(internal_coords)

    if order_by == "external":
        ordered = sorted(names, key=lambda n: (external_coords[n], internal_coords[n]))
    elif order_by == "internal":
        ordered = sorted(names, key=lambda n: internal_coords[n])
    elif order_by == "midpoint":
        ordered = sorted(names, key=lambda n: 0.5 * (internal_coords[n] + external_coords[n]))
    else:
        raise ValueError(f"Unsupported order_by={order_by!r}")

    targets = [0.5 * (internal_coords[n] + external_coords[n]) for n in ordered]
    spacings = []
    for a, b in zip(ordered, ordered[1:]):
        sp = min_pitch_um
        if pair_pitch_um:
            sp = pair_pitch_um.get((a, b), pair_pitch_um.get((b, a), sp))
        spacings.append(sp)

    solved = _pav_min_spacing(targets, spacings, lo, hi)
    # Snap while preserving non-violation of minimum pitch
    snapped: list[float] = []
    for i, val in enumerate(solved):
        v = snap(val, grid_um)
        if i == 0:
            v = max(v, snap(lo, grid_um))
        else:
            v = max(v, snap(snapped[-1] + spacings[i - 1], grid_um))
        snapped.append(v)
    if snapped and snapped[-1] > hi + 1e-6:
        shift = snapped[-1] - snap(hi, grid_um)
        snapped = [snap(v - shift, grid_um) for v in snapped]

    new_coords = {n: round(v, 4) for n, v in zip(ordered, snapped)}
    ext_order = sorted(names, key=lambda n: external_coords[n])
    int_order = sorted(names, key=lambda n: internal_coords[n])
    new_order = sorted(names, key=lambda n: new_coords[n])

    before_ext_detour = sum(abs(internal_coords[n] - external_coords[n]) for n in names)
    after_int_detour = sum(abs(new_coords[n] - internal_coords[n]) for n in names)
    after_ext_detour = sum(abs(new_coords[n] - external_coords[n]) for n in names)

    return {
        "ports": new_coords,
        "order": new_order,
        "external_crossings_before": count_inversions(int_order, ext_order),
        "external_crossings_after": count_inversions(new_order, ext_order),
        "internal_crossings_after": count_inversions(new_order, int_order),
        "before_direct_skew_um": round(before_ext_detour, 3),
        "after_internal_skew_um": round(after_int_detour, 3),
        "after_external_skew_um": round(after_ext_detour, 3),
    }


def analyze_whitespace(
    macros: dict[str, MacroSpec],
    placements: dict[str, Placement],
    *,
    bbox_override: tuple[float, float, float, float] | None = None,
    min_side_um: float = 10.0,
    min_area_um2: float = 200.0,
) -> list[dict]:
    """Find maximal empty axis-aligned rectangular pockets inside the floorplan."""
    boxes = [macro_world_box(macros[n], placements[n], include_halo=False) for n in macros]
    if bbox_override is not None:
        bx0, by0, bx1, by1 = bbox_override
    else:
        bx0 = min(b[0] for b in boxes)
        by0 = min(b[1] for b in boxes)
        bx1 = max(b[2] for b in boxes)
        by1 = max(b[3] for b in boxes)

    xs = sorted({bx0, bx1, *(b[0] for b in boxes), *(b[2] for b in boxes)})
    ys = sorted({by0, by1, *(b[1] for b in boxes), *(b[3] for b in boxes)})
    nx, ny = len(xs) - 1, len(ys) - 1
    occ = [[False] * ny for _ in range(nx)]
    for ix in range(nx):
        cx = 0.5 * (xs[ix] + xs[ix + 1])
        for iy in range(ny):
            cy = 0.5 * (ys[iy] + ys[iy + 1])
            for b in boxes:
                if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]:
                    occ[ix][iy] = True
                    break

    # Enumerate maximal empty grid rectangles
    cands: list[tuple[int, int, int, int]] = []
    for x0 in range(nx):
        for x1 in range(x0 + 1, nx + 1):
            col_free = [all(not occ[ix][iy] for ix in range(x0, x1)) for iy in range(ny)]
            y0 = 0
            while y0 < ny:
                if not col_free[y0]:
                    y0 += 1
                    continue
                y1 = y0
                while y1 < ny and col_free[y1]:
                    y1 += 1
                # Maximality in X: cannot expand left or right across [y0..y1)
                can_left = x0 > 0 and all(not occ[x0 - 1][iy] for iy in range(y0, y1))
                can_right = x1 < nx and all(not occ[x1][iy] for iy in range(y0, y1))
                if not can_left and not can_right:
                    cands.append((x0, y0, x1, y1))
                y0 = y1

    pockets = []
    for x0, y0, x1, y1 in cands:
        w = xs[x1] - xs[x0]
        h = ys[y1] - ys[y0]
        area = w * h
        if min(w, h) >= min_side_um and area >= min_area_um2:
            pockets.append({
                "box_um": [round(xs[x0], 2), round(ys[y0], 2), round(xs[x1], 2), round(ys[y1], 2)],
                "width_um": round(w, 2),
                "height_um": round(h, 2),
                "area_um2": round(area, 1),
            })
    pockets.sort(key=lambda p: p["area_um2"], reverse=True)
    return pockets
