"""Explore constrained 4G macro placement from a physical Magic assembly.

Use the assembled .mag/.ext and its summary as inputs. The output is a macro
plan with fixed orientations, physical pin distances and a placement-only
Magic wrapper for checking geometry. Top-level signal and power routing
belong to the input assembly and must be redrawn for moved instances.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, replace
import hashlib
from itertools import combinations
import json
from pathlib import Path
import re
import shutil

import numpy as np
from scipy import __version__ as scipy_version
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from floorplan_opt import MacroSpec, NetSpec, Placement, evaluate_floorplan, macro_world_box, snap
from magicutil import PDK, run_magic


BOX = tuple[float, float, float, float]
ROOT = Path(__file__).resolve().parents[2]
CELL = "serdes_4g_top_pdk"
FIXED_MACROS = {"ldo_v2_cur", "digital_top_v3", "tx_sst_top", "rx_cmos_top", "bias_ctle_v2"}
# Macro position fences. The guard geometry is also carried as paint in the
# placement check. The TX/RX bay already hosts decap and the fixed CTLE bias.
QUIET_EDGE = 343.0
NOISY_EDGE = 367.5
GUARD_BOXES = (
    (348.0, 6.0, 350.0, 596.0), (360.0, 6.0, 362.0, 596.0),
    (599.2, 6.0, 600.8, 240.0), (645.2, 58.0, 646.8, 240.0),
)
CML_COLUMN = tuple(f"cml2cmos_{n}" for n in range(4))
NOISY_MACROS = {*CML_COLUMN, "bias_cml_host", "div8_saff", "tx_sst_top", "tx_qdiv2", "rx_cmos_top",
                "digital_top_v3"}
PLL_SENSITIVE = {"ldo_v2_cur", "bias_cp_v2", "bias_lpf_slow", "cp_v4", "lf_k4_fused", "vco_r6_sym9"}
RELEASE_MODES = ("release_baseline", "release_zoned", "release_shared", "release_compact")
GRID = 0.005
TO_U = round(1 / GRID)


@dataclass(frozen=True)
class Instance:
    name: str
    cell: str
    record: str
    transform: tuple[int, ...]
    box: BOX
    array: tuple[int, ...] | None


def magic_port_centres(text: str) -> dict[str, tuple[float, float, str]]:
    """Read only Magic ports, including flabels and non-default grid scales."""
    magscale = re.search(r"^magscale (\d+) (\d+)$", text, re.M)
    scale = 0.01 * (int(magscale[1]) / int(magscale[2]) if magscale else 1)
    ports = {}
    for match in re.finditer(r"^[rf]label ([^\n]+)\nport ", text, re.M):
        row = match[1].split()
        start = 2 if row[1] == "s" else 1
        x0, y0, x1, y1 = map(int, row[start:start + 4])
        # GDS import exposes many physical contacts for these two supply names.
        if row[-1] in {"VGND", "VPWR"}:
            continue
        if row[-1] in ports:
            raise ValueError(f"Duplicate physical port {row[-1]}")
        ports[row[-1]] = (scale * (x0+x1) / 2, scale * (y0+y1) / 2, row[0])
    return ports


def transform_xy(transform: tuple[int, ...], x: float, y: float) -> tuple[float, float]:
    a, b, tx, c, d, ty = transform
    return round(a*x + b*y + tx*GRID, 6), round(c*x + d*y + ty*GRID, 6)


def instances_from_top(text: str) -> dict[str, Instance]:
    if "magscale 1 2\n" not in text:
        raise ValueError("This placement adapter uses the 5 nm assembly grid")
    instances = {}
    for hit in re.finditer(
        r"^use (\S+)\s+(\S+)\s*\n(?:(array [^\n]+)\n)?(?:timestamp [^\n]+\n)?"
        r"transform ([^\n]+)\nbox ([^\n]+)\n", text, re.M
    ):
        cell, name = hit[1], hit[2]
        transform = tuple(map(int, hit[4].split()))
        lo_x, lo_y, hi_x, hi_y = map(int, hit[5].split())
        array = tuple(map(int, hit[3].split()[1:])) if hit[3] else None
        if array:
            left, right, dx, low, high, dy = array
            lo_x, hi_x = lo_x + min(right*dx, left*dx), hi_x + max(right*dx, left*dx)
            lo_y, hi_y = lo_y + min(high*dy, low*dy), hi_y + max(high*dy, low*dy)
        xs, ys = zip(*(transform_xy(transform, x*GRID, y*GRID)
                       for x in (lo_x, hi_x) for y in (lo_y, hi_y)))
        instances[name] = Instance(name, cell, hit[0], transform,
                                   (min(xs), min(ys), max(xs), max(ys)), array)
    if len(instances) != len(re.findall(r"^use ", text, re.M)):
        raise ValueError("Some Magic instance records were not parsed")
    return instances


def points_by_macro(assembly: Path, instances: dict[str, Instance]) -> dict:
    all_ports = {}
    points = {}
    for name, inst in instances.items():
        if inst.array:
            continue
        if inst.cell not in all_ports:
            all_ports[inst.cell] = magic_port_centres((assembly / f"{inst.cell}.mag").read_text())
        points[name] = {
            pin: (*transform_xy(inst.transform, x, y), layer)
            for pin, (x, y, layer) in all_ports[inst.cell].items()
        }
    return points


def net_groups(ext: str) -> dict[str, str]:
    parent = {}

    def find(name):
        while name != parent.setdefault(name, name):
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    for a, b in re.findall(r'^(?:equiv|merge) "([^"]+)" "([^"]+)"', ext, re.M):
        parent[find(a)] = find(b)
    return {name: find(name) for name in parent}


def physical_nets(ports: dict, top_ports: dict, aliases: dict) -> tuple[list[NetSpec], dict]:
    groups = defaultdict(list)
    physical_name = {}
    excluded_supply = {
        aliases.get(pin, pin) for pin in top_ports if pin.startswith(("VDD", "VSS"))
    }
    for inst, pins in ports.items():
        for pin in pins:
            node = f"{inst}/{pin}"
            if node in aliases and aliases[node] not in excluded_supply:
                groups[aliases[node]].append((inst, pin))
    for pin, (x, y, _) in top_ports.items():
        if pin in aliases and aliases[pin] not in excluded_supply:
            groups[aliases[pin]].append(("@FIXED", f"{x},{y}"))
            physical_name[aliases[pin]] = pin
    nets = []
    for representative, pins in sorted(groups.items()):
        if len({inst for inst, _ in pins}) >= 2:
            name = physical_name.get(representative, "/".join(min(pins)))
            weight = 0.25 if all(inst in {"tx_sst_top", "rx_cmos_top", "digital_top_v3"} for inst, _ in pins) else 1
            nets.append(NetSpec(name, tuple(sorted(pins)), weight))
    return nets, {"connected_signal_groups": len(nets), "excluded_root_supply_groups": len(excluded_supply)}


def critical_pairs(aliases: dict) -> list[NetSpec]:
    pairs = []

    def add(name, a, b, weight):
        if a not in aliases or b not in aliases or aliases[a] != aliases[b]:
            raise ValueError(f"Input extraction does not connect {a} and {b}")
        pairs.append(NetSpec(name, (tuple(a.split("/")), tuple(b.split("/"))), weight))

    for s, idx in enumerate((2, 3, 0, 1)):
        for a, b in zip("pn", "pn" if s % 2 == 0 else "np"):
            add(f"VCO_B{s}{a}", f"vco_r6_sym9/b{s}{a}", f"cml2cmos_{idx}/in{b}", 5)
        for leg, phase in (("p", s), ("n", s + 4)):
            add(f"RX_C{phase}", f"cml2cmos_{idx}/out{leg}", f"rx_cmos_top/c{phase}", 3)
    for k in range(4):
        add(f"TX_{k}", f"tx_qdiv2/ckd{k}", f"tx_sst_top/phi{k*90}", 4)
    for name, a, b, weight in (
        ("BIAS_PTAT_VGI", "bias_top_v2/vgi", "vco_ptat_bias/vgi", 6),
        ("BIAS_PTAT_VG", "bias_top_v2/vg", "vco_ptat_bias/vg", 6),
        ("TAIL_FILTER", "bias_lpf_slow/filtered", "vco_r6_sym9/vbias_q", 7),
        ("LF_to_VCO", "lf_k4_fused/ctrl", "vco_r6_sym9/ctrl", 7),
        ("CP_to_LF", "cp_v4/out", "lf_k4_fused/ctrl", 5),
        ("PFD_UP", "pfd_sc_dly/up", "cp_v4/up", 5),
        ("PFD_DN", "pfd_sc_dly/dn", "cp_v4/dn", 5),
        ("FEEDBACK", "div8_saff/q8p", "pfd_sc_dly/fb", 1),
        ("BIAS_to_LDO", "bias_top_v2/i_ldo0", "ldo_v2_cur/i_ldo", 2),
        ("LDO_to_VCO", "ldo_v2_cur/quiet", "vco_r6_sym9/vdd_q", 2),
    ):
        add(name, a, b, weight)
    return pairs


def separated_axis(box_a: BOX, box_b: BOX) -> tuple[int, bool, float]:
    options = [(axis, reverse, (box_a if reverse else box_b)[axis] - (box_b if reverse else box_a)[axis+2])
               for axis in (0, 1) for reverse in (False, True)]
    return max(options, key=lambda row: row[2])


class LinearModel:
    def __init__(self):
        self.bounds = []
        self.cost = []
        self.row, self.col, self.val, self.rhs = [], [], [], []
        self.integrality = []

    def variable(self, low=None, high=None, cost=0, integer=0) -> int:
        result = len(self.cost)
        self.cost.append(cost)
        self.bounds.append((low, high))
        self.integrality.append(integer)
        return result

    def limit(self, terms: list[tuple[int, float]], bound: float):
        for col, val in terms:
            self.row.append(len(self.rhs))
            self.col.append(col)
            self.val.append(val)
        self.rhs.append(bound)

    def add_separation(self, options: list[tuple[int, int, float]]) -> None:
        """At least one of the feasible directed separation axes must hold."""
        possible = []
        for left, right, gap in options:
            smallest = self.bounds[left][0] - self.bounds[right][1]
            largest = self.bounds[left][1] - self.bounds[right][0]
            if largest <= gap + 1e-8:
                return
            if smallest <= gap + 1e-8:
                possible.append((left, right, gap, largest-gap))
        if not possible:
            raise ValueError("No axis can separate this pair within its position bounds")
        if len(possible) == 1:
            left, right, gap, _ = possible[0]
            self.limit([(left, 1), (right, -1)], gap)
            return
        active = []
        for left, right, gap, big_m in possible:
            order = self.variable(0, 1, integer=1)
            self.limit([(left, 1), (right, -1), (order, big_m)], gap+big_m)
            active.append((order, -1))
        self.limit(active, -1)

    def solve(self, mixed: bool):
        matrix = coo_matrix((self.val, (self.row, self.col)), shape=(len(self.rhs), len(self.cost))).tocsc()
        result = linprog(self.cost, A_ub=matrix, b_ub=self.rhs, bounds=self.bounds, method="highs",
                         integrality=self.integrality if mixed else None,
                         options={"time_limit": 25.0} if mixed else None)
        if not result.success and (result.status != 1 or result.x is None):
            raise RuntimeError(result.message)
        return result


def solve_plan(macros: dict[str, MacroSpec], baseline: dict[str, Placement], nets: list[NetSpec],
               critical: list[NetSpec], core: BOX, quiet: set[str], step: float, *,
               mixed: bool = False, shared: bool = False, compact: bool = False):
    """Solve with fixed baseline relative ordering, or allow legal axis changes."""
    model = LinearModel()
    origins = {}
    boxes = {n: macro_world_box(macros[n], pl) for n, pl in baseline.items()}
    quiet_fence = quiet & PLL_SENSITIVE if shared else quiet
    noisy_fence = set(CML_COLUMN) if shared else NOISY_MACROS
    for name, block in baseline.items():
        bounds = []
        for axis, origin in enumerate((block.x, block.y)):
            if block.locked:
                bounds.append((origin, origin))
                continue
            size = boxes[name][axis+2] - boxes[name][axis]
            low, high = max(core[axis], origin - step), min(core[axis+2] - size, origin + step)
            if axis == 0 and name in quiet_fence:
                high = min(QUIET_EDGE-size, high)
            if axis == 0 and name in noisy_fence:
                low = max(NOISY_EDGE, low)
            bounds.append((low, high))
        origins[name] = tuple(model.variable(a, b) for a, b in bounds)
        if not block.locked:
            for var, origin in zip(origins[name], (block.x, block.y)):
                delta = model.variable(0, None, cost=0.2)
                model.limit([(var, 1), (delta, -1)], origin)
                model.limit([(var, -1), (delta, -1)], -origin)

    if compact:
        # Minimize the functional envelope with the existing south/east data macros
        # and guard geometry in place. The guard ends are outside this objective.
        north = model.variable(core[1], core[3], cost=120)
        for name, variables in origins.items():
            if not name.startswith("guard_"):
                model.limit([(variables[1], 1), (north, -1)], boxes[name][1]-boxes[name][3])

    clearances = {}
    for a, b in combinations(baseline, 2):
        if baseline[a].locked and baseline[b].locked:
            continue
        axis, reverse, original = separated_axis(boxes[a], boxes[b])
        if original < -1e-6:
            raise ValueError(f"Overlapping input placement of {a} and {b}")
        req = 5.0
        if (a in quiet and b in NOISY_MACROS) or (b in quiet and a in NOISY_MACROS):
            req = 35.4 if not shared or {a, b} & PLL_SENSITIVE else 12.0
        if {a, b} == {"pfd_sc_dly", "cp_v4"}:
            req = 16.75
        if compact and "digital_top_v3" in (a, b) and {a, b} & {"tx_sst_top", "tx_qdiv2", "rx_cmos_top"}:
            req = 12.0
        clearances[a, b] = max(0.0, min(req, original))
        if mixed:
            directions = [(a, b, 1)] if a in CML_COLUMN and b in CML_COLUMN else [
                (aa, bb, coord) for aa, bb in ((a, b), (b, a)) for coord in (0, 1)
            ]
        else:
            aa, bb = (b, a) if reverse else (a, b)
            directions = [(aa, bb, axis)]
        model.add_separation([
            (origins[aa][coord], origins[bb][coord], boxes[aa][coord]-boxes[aa][coord+2]-clearances[a, b])
            for aa, bb, coord in directions
        ])
    for a, b in zip(CML_COLUMN, CML_COLUMN[1:]):
        xa, xb = origins[a][0], origins[b][0]
        model.limit([(xa, 1), (xb, -1)], 0)
        model.limit([(xa, -1), (xb, 1)], 0)

    critical_before = evaluate_floorplan(macros, baseline, critical)["per_net_hpwl_um"]
    for net, bounded in [(net, False) for net in nets] + [(net, True) for net in critical]:
        limits = []
        for axis in (0, 1):
            lo = model.variable(cost=-net.weight)
            hi = model.variable(cost=net.weight)
            limits += [(hi, 1), (lo, -1)]
            for inst, pin in net.pins:
                if inst == "@FIXED":
                    fixed = float(pin.split(",")[axis])
                    model.limit([(lo, 1)], fixed)
                    model.limit([(hi, -1)], -fixed)
                else:
                    offset = macros[inst].ports_local[pin][axis]
                    origin = origins[inst][axis]
                    model.limit([(lo, 1), (origin, -1)], offset)
                    model.limit([(origin, 1), (hi, -1)], -offset)
        if bounded:
            # Rounding guard for port centres on half of the Magic grid.
            model.limit(limits, critical_before[net.name] + 0.004)

    result = model.solve(mixed)
    placement = {
        name: replace(pl, x=snap(result.x[origins[name][0]], GRID), y=snap(result.x[origins[name][1]], GRID))
        for name, pl in baseline.items()
    }
    final = evaluate_floorplan(macros, placement, nets, pair_clearances=clearances)
    if not final["feasible"]:
        raise RuntimeError(f"Snapped placement violates spacing: {final['halo_violations']}")
    final_critical = evaluate_floorplan(macros, placement, critical)["per_net_hpwl_um"]
    if any(value - critical_before[name] > 0.01 for name, value in final_critical.items()):
        raise RuntimeError("Snapping exceeded the critical distance budgets")
    return placement, final, final_critical, {
        "optimized_model": "MILP" if mixed else "LP",
        "optimal_within_solver_tolerance": bool(result.success),
        "mip_gap": getattr(result, "mip_gap", None),
        "binary_separation_variables": sum(model.integrality),
        "critical_tolerance_um": 0.01,
    }


def copy_macro_hierarchy(assembly: Path, work: Path, cells: set[str]) -> set[Path]:
    pending = set(cells)
    files = set()
    while pending:
        cell = pending.pop()
        source = assembly / f"{cell}.mag"
        if not source.is_file():
            library, _, _ = cell.partition("__")
            source = PDK / "libs.ref" / library / "mag" / f"{cell}.mag"
        if source in files:
            continue
        shutil.copyfile(source, work / source.name)
        files.add(source)
        pending.update(re.findall(r"^use (\S+)", source.read_text(), re.M))
    return files


def layout_view(assembly: Path, work: Path, instances: dict, before: dict, after: dict) -> set[Path]:
    """Export a distinct Magic root with only the moved hierarchy and isolation paint."""
    work.mkdir()
    lines = ["magic\ntech sky130A\nmagscale 1 2\ntimestamp 0\n"]
    text = (assembly / f"{CELL}.mag").read_text()
    for layer in ("psubdiff", "psubdiffcont", "locali", "metal1", "viali", "via1", "metal2"):
        block = re.search(rf"^<< {layer} >>\n((?:rect [^\n]+\n)+)", text, re.M)
        if not block:
            continue
        rects = []
        for rect in block[1].splitlines():
            x0, y0, x1, y1 = (int(v)*GRID for v in rect.split()[1:])
            if any(x0 >= a - 0.01 and x1 <= c+0.01 and y0 >= b-0.01 and y1 <= d+0.01
                   for a, b, c, d in GUARD_BOXES):
                rects.append(rect)
        if rects:
            lines.extend([f"<< {layer} >>\n", "\n".join(rects) + "\n"])
    for name, item in instances.items():
        original, shifted = before[name], after[name]
        a, b, tx, c, d, ty = item.transform
        next_x = tx + round((shifted.x-original.x)*TO_U)
        next_y = ty + round((shifted.y-original.y)*TO_U)
        lines.append(re.sub(r"^transform [^\n]*", f"transform {a} {b} {next_x} {c} {d} {next_y}", item.record, flags=re.M))
    lines.append("<< end >>\n")
    (work / "placement_only.mag").write_text("".join(lines))
    return copy_macro_hierarchy(assembly, work, {item.cell for item in instances.values()})


def verify_placement_geometry(work: Path) -> dict:
    """Check the moved macro hierarchy and guard paint with the full Magic deck."""
    script = work / "placement_drc.tcl"
    script.write_text(
        "drc off\nload placement_only\nselect top cell\ndrc on\ndrc euclidean on\n"
        "drc style drc(full)\ndrc check\ndrc catchup\n"
        'puts "DRC_TOTAL [drc list count total]"\n'
        'foreach {why boxes} [drc listall why] {puts "DRC_RULE $why | $boxes"}\n'
        "quit -noprompt\n"
    )
    result = run_magic(script.resolve(), work.resolve())
    (work/"placement_drc.log").write_text(result.log)
    result.need("placement DRC")
    count = re.search(r"^DRC_TOTAL (\d+)$", result.log, re.M)
    if not count:
        raise ValueError(f"Missing DRC count in {work/'placement_drc.log'}")
    return {"drc_total": int(count[1]), "scope": "Hierarchy with guard paint and no top interconnect",
            "log": str(work / "placement_drc.log")}


def access_floors(critical: list[NetSpec], boxes: dict[str, BOX], lengths: dict) -> dict:
    report = {}
    for path in critical:
        a, b = (boxes[inst] for inst, _ in path.pins)
        edge = sum(max(0, a[axis]-b[axis+2], b[axis]-a[axis+2]) for axis in (0, 1))
        report[path.name] = {
            "bbox_to_bbox_lower_bound_um": round(edge, 3),
            "actual_pin_span_um": lengths[path.name],
            "gap_between_pin_and_bbox_estimates_um": round(lengths[path.name] - edge, 3),
        }
    return report


def run(assembly: Path, output: Path, verify: list[str], *, release_decap: bool = False):
    magn = assembly / f"{CELL}.mag"
    ext = assembly / f"{CELL}.ext"
    inventory = assembly / "summary.json"
    content = magn.read_text()
    instances = instances_from_top(content)
    ports = points_by_macro(assembly, instances)
    source = json.loads(inventory.read_text())
    f = source["floorplan_kpi"]
    policy = {d["inst"]: d for d in f["macros"]}
    assert set(policy) == set(ports) and len(instances) == len(ports)+source["decap_banks"]
    assert sum((i.array[1]-i.array[0]+1)*(i.array[4]-i.array[3]+1)
               for i in instances.values() if i.array) == source["decap_tiles_total"]
    quiet = {name for name, p in policy.items() if p["quiet_island"]}
    die = f["die_core"]
    # Upstream planner's width and height are maximum coordinates from (0, 0).
    core = (0.0, 0.0, die["width_um"], die["height_um"])
    # Use the union of each physical array envelope and its PDN reservation.
    rectangles = {n: item.box for n, item in instances.items()}
    for bank in f["decap_banks"]:
        name, reserved = bank["name"], bank["rect_um"]
        actual = rectangles[name]
        rectangles[name] = tuple(fn(a,b) for fn,a,b in zip((min,min,max,max), actual, reserved))
    access_end = rectangles["DECAP_RX_NE"][0]
    if release_decap:
        instances = {n: item for n, item in instances.items() if not item.array}
        rectangles = {n: rectangles[n] for n in instances}
    rectangles.update({f"guard_{i}": box for i, box in enumerate(GUARD_BOXES)})
    # Reserve the east-side strip above TX QDiv2 for the digital south bus.
    # The RX northeast decap reservation covers the remainder of this strip.
    rectangles["digital_bus_access"] = (499.2, 280.0, access_end, 294.0)
    macros = {
        name: MacroSpec(name, x1-x0, y1-y0,
                        {pin: (x-x0,y-y0,layer) for pin,(x,y,layer) in ports.get(name,{}).items()})
        for name,(x0,y0,x1,y1) in rectangles.items()
    }
    baseline = {name: Placement(name, box[0], box[1], locked=name not in policy or name in FIXED_MACROS)
                for name,box in rectangles.items()}
    aliases = net_groups(ext.read_text())
    nets, counts = physical_nets(ports, magic_port_centres(content), aliases)
    critical = critical_pairs(aliases)
    before = evaluate_floorplan(macros, baseline, nets)
    before_critical = evaluate_floorplan(macros, baseline, critical)["per_net_hpwl_um"]
    movable_groups = {net.name for net in nets if any(n != "@FIXED" and not baseline[n].locked for n,_ in net.pins)}
    counts["signal_groups_with_movable_macros"] = len(movable_groups)
    before["movable_net_hpwl_um"] = round(sum(before["per_net_hpwl_um"][n] for n in movable_groups), 3)
    output.mkdir(parents=True, exist_ok=False)
    plans = {}
    sources = {magn, ext, inventory}
    profiles = [("local", 24.0, False), ("island", 72.0, False), ("reorder", 72.0, True)]
    if release_decap:
        profiles = [("release_baseline", 0.0, False), ("release_zoned", 72.0, True),
                    ("release_shared", 72.0, True), ("release_compact", 72.0, True)]
    for mode, travel, mixed in profiles:
        shared = mode in ("release_shared", "release_compact")
        compact = mode == "release_compact"
        active = baseline
        if compact:
            # The independent compact trial moves the digital macro and places a
            # pairwise 12 um channel around the data macros instead of a fixed strip.
            active = {n: pl for n, pl in baseline.items() if n != "digital_bus_access"}
            active["digital_top_v3"] = replace(active["digital_top_v3"], locked=False)
        place, stats, links, solver = solve_plan({n: macros[n] for n in active}, active, nets, critical,
                                                core, quiet, travel, mixed=mixed, shared=shared, compact=compact)
        sources.update(layout_view(assembly, output / mode, instances, baseline, place))
        candidate_boxes = {n: macro_world_box(macros[n], pl) for n,pl in place.items()}
        stats["movable_net_hpwl_um"] = round(sum(stats["per_net_hpwl_um"][n] for n in movable_groups), 3)
        plans[mode] = {
            "travel_um": travel, "signal_geometry": stats, "critical_spans_um": links, "solver": solver,
            "moves_um": {n: [round(place[n].x-baseline[n].x,3), round(place[n].y-baseline[n].y,3)]
                         for n in policy},
            "boxes_um": candidate_boxes,
            "functional_envelope_um": [max(box[2] for n, box in candidate_boxes.items() if n in policy),
                                       max(box[3] for n, box in candidate_boxes.items() if n in policy)],
            "minimum_shared_zone_guard_um": 12.0 if shared else 35.4,
            "critical_access_floor_um": access_floors(critical, candidate_boxes, links),
        }
    (output/"summary.json").write_text(json.dumps({
        "source_sha256": {str(path.resolve().relative_to(ROOT) if path.resolve().is_relative_to(ROOT) else path.resolve()):
                          hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in sorted(sources)},
        "scipy": scipy_version, "solver": "HiGHS LP / MILP",
        "input": {**counts, "functional_macros": len(ports), "movable_macros": len(ports)-len(FIXED_MACROS),
                  "fixed_macros": sorted(FIXED_MACROS), "decap_removed": release_decap,
                  "fixed_decap_tiles": 0 if release_decap else source["decap_tiles_total"],
                  "fixed_decap_banks": 0 if release_decap else source["decap_banks"],
                  "released_reservations_um2": f["packing"]["decap_area_um2"] if release_decap else 0,
                  "planning_core_um": core},
        "baseline": {"signal_geometry": before, "critical_spans_um": before_critical, "boxes_um": rectangles,
                     "critical_access_floor_um": access_floors(critical, rectangles, before_critical)},
        "plans": plans,
    }, indent=2)+"\n")
    for mode in verify:
        work = output/mode
        (work/"placement_drc.json").write_text(json.dumps(verify_placement_geometry(work), indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--release-decap", action="store_true", help="export a separate array-free placement sweep")
    parser.add_argument("--verify", choices=("local", "island", "reorder", *RELEASE_MODES), action="append", default=[],
                        help="run full Magic DRC on the selected placement-only view")
    args = parser.parse_args()
    if any((mode in RELEASE_MODES) != args.release_decap for mode in args.verify):
        parser.error("The verification modes must match --release-decap")
    run(args.assembly, args.output_dir, list(dict.fromkeys(args.verify)), release_decap=args.release_decap)


if __name__ == "__main__":
    main()
