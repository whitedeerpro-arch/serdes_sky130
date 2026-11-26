#!/usr/bin/env python3
"""Build and check the shared-supply CML→CMOS I/Q host for the 5G LC PLL."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from check import drc, exported_ports, extract
from geometry import Cell
from magicutil import netgen
from optimize_chip_macro_plan import (
    CELL, GRID, ROOT, instances_from_top, magic_port_centres, net_groups, transform_xy,
)

RECEIVER = "serdes_cml_to_cmos_r5_pdk"
BIAS = "serdes_bias_cml_v2_pdk"
TOP = "serdes_5g_cml_clock_host"
REF_RECEIVER = ROOT / f"analog/common/cml_to_cmos/layout/variants/r5_pdk/{RECEIVER}_ref.spice"
REF_BIAS = ROOT / f"analog/bias/layout/variants/v2_pdk/{BIAS}_ref.spice"
BASELINE_BIAS = ("bias_top_v2/icml", "bias_cml_host/iin", *(f"cml2cmos_{i}/vbias" for i in range(4)))


def bias_gate(ext: str, members: tuple[str, ...], supplies: tuple[str, ...]) -> dict:
    groups = net_groups(ext)
    for name in re.findall(r'^node "([^"]+)"', ext, re.M):
        groups.setdefault(name, name)
    roots = {pin: groups.get(pin) for pin in (*members, *supplies)}
    missing = [pin for pin, root in roots.items() if root is None]
    common = roots[members[0]]
    opens = [pin for pin in members if roots[pin] != common]
    shorts = [pin for pin in supplies if roots[pin] is not None and roots[pin] == common]
    return {"pass": not (missing or opens or shorts), "missing": missing, "opens": opens,
            "shorted_supplies": shorts, "extraction_groups": roots}


def via34(cell: Cell, x: float, y: float) -> None:
    for layer, size in (("metal3", 0.52), ("metal4", 0.52), ("via3", 0.32)):
        cell.pad(layer, x, y, size)


def via45(cell: Cell, x: float, y: float, count: int = 1) -> None:
    height = 1.8 * (count - 1)
    cell.pad("metal4", x, y, 1.60, 1.60 + height)
    cell.pad("metal5", x, y, 2.00, 2.00 + height)
    for index in range(count):
        cell.pad("via4", x, y - height / 2 + 1.8 * index, 1.18)


def place(cell: str, bounds: tuple, name: str, x: float, y: float, *,
          rotate: bool = False, flip_x: bool = False) -> tuple[str, tuple[int, ...]]:
    x0, y0, x1, y1 = bounds
    sign = -1 if flip_x else 1
    a, b, c, d = (0, -sign, 1, 0) if rotate else (sign, 0, 0, 1)
    left = min(a*xx+b*yy for xx in (x0, x1) for yy in (y0, y1))
    bottom = min(c*xx+d*yy for xx in (x0, x1) for yy in (y0, y1))
    transform = (a, b, round((x-left)/GRID), c, d, round((y-bottom)/GRID))
    fmt = " ".join(map(str, transform))
    box = " ".join(str(round(v/GRID)) for v in bounds)
    return f"use {cell} {name}\ntimestamp 0\ntransform {fmt}\nbox {box}\n", transform


def run(output: Path, gap: float, bias_side: bool) -> dict:
    output.mkdir(parents=True)
    paths = (REF_RECEIVER.with_name(f"{RECEIVER}.mag"), REF_BIAS.with_name(f"{BIAS}.mag"))
    for path in paths:
        shutil.copyfile(path, output / path.name)
    pins_receiver, pins_diode = (magic_port_centres(p.read_text()) for p in paths)
    receiver, diode = (Cell.read(p).bbox() for p in paths)
    height = round(receiver[3]-receiver[1], 3)
    bias_height = round(diode[2]-diode[0], 3)
    frame = Cell()
    ret = "vss"
    supply = "vdd_clk"
    bias_x = -2.5
    row_envelope = 2*height+gap
    if bias_side:
        diode_x = -37.0
        diode_y = round((row_envelope-bias_height)/2/GRID)*GRID
        ground_x = -4.9
    else:
        diode_x, diode_y = 0, -bias_height-6.0
        ground_x = -6.0
    diode_use, diode_tf = place(BIAS, diode, "bias", diode_x, diode_y, rotate=True, flip_x=bias_side)
    ibx, iby = transform_xy(diode_tf, *pins_diode["iin"][:2])
    gdx, gdy = transform_xy(diode_tf, *pins_diode["vss"][:2])
    ground_y = min(0, diode_y)-4.0
    frame.wire("metal4", [(bias_x, iby), (ibx, iby)], 0.44)
    frame.wire("metal3", [(gdx, gdy), (ground_x, gdy)], 0.52)
    via34(frame, ground_x, gdy)
    via45(frame, ground_x, gdy)
    sources = [diode_use]
    rows = []
    terminal_names = []
    reference_rows = [f"Xbias ibias {ret} {BIAS}"]
    vdd_x = round(pins_receiver["vdd"][0] - receiver[0], 3)
    vss_x = 45.0
    for index, phase in enumerate("iq"):
        record, transform = place(RECEIVER, receiver, f"c2c_{phase}", 0, index * (height + gap))
        sources.append(record)
        pins = {k: (*transform_xy(transform, x, y), layer) for k, (x, y, layer) in pins_receiver.items()}
        names = [f"{phase}{suffix}" for suffix in ("p", "n", "c_p", "c_n")]
        terminal_names.extend(names)
        for name, pin in zip(names, ("inp", "inn", "outp", "outn")):
            px, py, layer = pins[pin]
            # Paint an access stub because parent ports must land on parent metal.
            # Match the r5 landing offsets to clear the nearby bias and return.
            py += {"inp": 0.17, "inn": -0.14}.get(pin, 0)
            end = px - 1.0 if pin.startswith("in") else px + 1.0
            frame.wire(layer, [(px, py), (end, py)], 0.34)
            frame.port(name, layer, end, py)
        bx, by, _ = pins["vbias"]
        via34(frame, bias_x, by)
        frame.wire("metal3", [(bias_x, by), (bx, by)], 0.30)
        vy = pins["vdd"][1]
        gy = pins["vss"][1]
        via45(frame, vdd_x, vy, 2)
        via45(frame, vss_x, gy, 2)
        rows.append((vy, gy, by))
        reference_rows.append(f"Xc2c_{phase} {' '.join(names)} ibias {supply} {ret} {RECEIVER}")
    frame.wire("metal4", [(bias_x, iby), (bias_x, rows[-1][2])], 0.44)
    frame.wire("metal5", [(vdd_x, rows[0][0]), (vdd_x, rows[-1][0])], 2.20)
    frame.wire("metal5", [(ground_x, gdy), (ground_x, ground_y),
                          (vss_x, ground_y), (vss_x, rows[-1][1])], 2.20)
    frame.port("ibias", "metal4", bias_x, iby)
    frame.port(supply, "metal5", vdd_x, rows[-1][0])
    frame.port(ret, "metal5", vss_x, ground_y)

    mag = output / f"{TOP}.mag"
    frame.write(mag)
    mag.write_text(mag.read_text().replace("<< end >>", "".join(sources) + "<< end >>"))
    ref = output / f"{TOP}_ref.spice"
    ref.write_text(REF_RECEIVER.read_text().rstrip() + "\n" + REF_BIAS.read_text().rstrip() + "\n" +
                   f".subckt {TOP} {' '.join(terminal_names)} ibias {supply} {ret}\n" +
                   "\n".join(reference_rows) + f"\n.ends {TOP}\n")
    count, rules = drc(output.resolve(), TOP)
    (output / "drc_rules.txt").write_text(rules + "\n")
    extract(output.resolve(), TOP, TOP)
    gate = bias_gate((output / f"{TOP}.ext").read_text(),
                     ("ibias", "bias/iin", "c2c_i/vbias", "c2c_q/vbias"), (ret, supply))
    lvs = output / f"{TOP}_lvs.spice"
    result = netgen(lvs.resolve(), TOP, ref.resolve(), (output / "netgen.log").resolve(), output.resolve())
    (output / "netgen.stdout").write_text(result.stdout)
    pass_lvs = ("Circuits match uniquely" in result.stdout and
                "Property errors were found" not in result.stdout and
                not re.search("disconnected node:", result.stdout, re.I) and
                exported_ports(lvs, TOP) == [*terminal_names, "ibias", supply, ret])
    inserted = instances_from_top(mag.read_text())
    x0, y0, x1, y1 = frame.bbox()
    width = max(x1, *(m.box[2] for m in inserted.values())) - min(x0, *(m.box[0] for m in inserted.values()))
    total_height = max(y1, *(m.box[3] for m in inserted.values())) - min(y0, *(m.box[1] for m in inserted.values()))
    report = {"row_gap_um": gap, "receiver_row_envelope_um": round(row_envelope, 3),
              "bias_location": "side" if bias_side else "below",
              "macro_bbox_um": [round(width, 3), round(total_height, 3)],
              "macro_bbox_area_um2": round(width*total_height, 2),
              "exported_ports": exported_ports(lvs, TOP),
              "leaf_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              "drc_total": count, "lvs_match": pass_lvs, "bias_gate": gate}
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--gap", type=float, default=1.0)
    parser.add_argument("--bias-below", action="store_true", help="place the reference diode below the I/Q rows")
    parser.add_argument("--audit-4g", type=Path, metavar="ASSEMBLY",
                        help="only apply the bias gate to a stored 4G extraction")
    args = parser.parse_args()
    if args.audit_4g:
        gate = bias_gate((args.audit_4g / f"{CELL}.ext").read_text(), BASELINE_BIAS, ("VSS", "VDD_A", "VDD_BIAS"))
        args.output.write_text(json.dumps(gate, indent=2) + "\n")
        raise SystemExit(0 if gate["pass"] else 1)
    if args.gap < 0 or abs(round(args.gap / GRID)*GRID-args.gap) > 1e-6:
        parser.error("gap must be nonnegative and on the 5 nm grid")
    report = run(args.output, args.gap, not args.bias_below)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if not report["drc_total"] and report["lvs_match"] and report["bias_gate"]["pass"] else 1)


if __name__ == "__main__":
    main()
