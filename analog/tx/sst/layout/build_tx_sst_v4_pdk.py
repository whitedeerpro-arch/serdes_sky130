#!/usr/bin/env python3
"""Master SKY130A PDK Physical Layout Builder & Signoff Suite for TX v4 Zero-CML SST.

Builds, verifies (Magic full-rule DRC=0, Netgen LVS=MATCH with 0 property errors,
independent `verification/layout/review_cell.py --rc` CPEX + native RCX), renders
white-background `plot_mag.py` PNGs, and writes `summary.json` + `README.md` for
all 5 hierarchical deliverables under `analog/tx/sst/layout/variants/v4_pdk/`:

  1. `sst_slice_unit_pdk.mag`
  2. `sst_vdrv_ldo_pdk.mag`
  3. `serdes_tx_sst_driver_pdk.mag`
  4. `serdes_tx_sst_serializer16_pdk.mag`
  5. `serdes_tx_sst_top_pdk.mag`
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import sst_layout_common as slc  # noqa: E402
from sst_layout_common import (  # noqa: E402
    Cell,
    PdkCache,
    grid,
    via2_clean,
    via3_pad,
)
import sst_analog_blocks as sab  # noqa: E402
import sst_driver_macro as sdm  # noqa: E402
import sst_serializer_macro as ssm  # noqa: E402


VARIANT_DIR = HERE / "variants" / "v4_pdk"
RESULTS_DIR = slc.REPO / "results" / "layout" / "tx_sst_v4"


def build_sst_top(cache: PdkCache, add_ports: bool = True) -> tuple[Cell, dict]:
    """Assemble integrated 16:1 Zero-CML TX v4 SST Top (`serdes_tx_sst_top_pdk`).

    Floorplan (~251.5 x 147.8 um = ~37,160 um^2, AR ~ 1.70):
      - North: `Xdrv` (`serdes_tx_sst_driver_pdk`, 251.10 x 90.38 um) at (0.0, 0.0)
      - South: `Xser` (`serdes_tx_sst_serializer16_pdk`, 227.98 x 51.62 um) directly below
               with 1:1 exact 0.000 um X-aligned M4 vertical joins for `phi0..phi270, d0..db3`
      - 5.8 um inter-macro corridor (`y in [-6.20, -0.40]`):
               `phi0..phi270` tap cleanly West on M3 at widened 1.30 um pitch
               (`y=-5.25, -3.95, -2.65, -1.35`, 0.86 um gap) to outer West perimeter
               (`x=-8.40`), while `vss` bridges vertically on M2 (`x=-3.60`) and `vdd`
               bridges vertically on M2 (`x=x_vdd_e=233.80`) with zero crossings!
    """
    c = Cell()

    drv_cell, drv_meta = sdm.build_sst_driver(cache, add_ports=False)
    north_pin_xs = {k: x for k, (x, _) in drv_meta["south_ports"].items()}
    ser_cell, ser_meta = ssm.build_sst_serializer16(cache, add_ports=False, north_pin_xs=north_pin_xs)

    y_ser_north = -6.200
    dy_ser = grid(y_ser_north - ser_meta["y_north_port"])

    c.include(drv_cell, dx=0.0, dy=0.0)
    c.include(ser_cell, dx=0.0, dy=dy_ser)

    # 1. Straight vertical M4 joins for all 12 interface nets (`phi0..phi270, d0..db3`)
    for nm, (px, py_drv) in drv_meta["south_ports"].items():
        c.wire("metal4", [(px, y_ser_north), (px, py_drv)], 0.520)

    # 2. Export `phi0..phi270` West on M3 inside the 5.8 um corridor to outer West perimeter (x=-8.40)
    #    1.30 um track pitch (0.86 um edge-to-edge gap) minimizes lateral inter-phase coupling!
    x_west_port = -8.400
    phi_ports: dict[str, tuple[float, float]] = {}
    for idx, nm in enumerate(("phi0", "phi90", "phi180", "phi270")):
        yp = grid(-5.250 + idx * 1.300)
        xp = drv_meta["south_ports"][nm][0]
        via3_pad(c, xp, yp)
        c.wire("metal3", [(x_west_port, yp), (xp, yp)], 0.440)
        phi_ports[nm] = (x_west_port, yp)

    # 3. Join `vss` (`Xser` West M3 spine -> vertical M2 at x=-3.60 -> `Xldo` y_vss_bot=1.20 M2)
    #    Crosses underneath `phi0..phi270` M3 cleanly; export `vss` at West perimeter (-8.40, 1.20).
    x_vss_w = ser_meta["x_vss_w"]
    y_ser_vss_hi = grid(dy_ser + ser_meta["vss_ys"][-1])
    y_ldo_vss = drv_meta["ports"]["vss"][2]  # 1.200 on M2
    c.wire("metal2", [(x_vss_w, y_ser_vss_hi), (x_vss_w, y_ldo_vss)], 1.400)
    c.wire("metal2", [(x_west_port, y_ldo_vss), (-7.600, y_ldo_vss)], 0.800)

    # 4. Join `vdd` (`Xser` East M3 spine -> M3 east to x_vdd_e -> vertical M2 north into `Xdrv` East M2 spine at y_r1_vdd)
    #    Strictly clear of all CMOS rows (west of x_vdd_e) and all East enable M3 routes (M2 under M3, no M3 pad at y_r1_vdd)!
    x_ser_vdd = ser_meta["x_vdd_e"]
    y_ser_vdd_hi = grid(dy_ser + ser_meta["vdd_ys"][-1])
    x_drv_vdd_e = drv_meta["x_vdd_e"]
    y_drv_r1_vdd = drv_meta.get("y_r1_vdd", drv_meta["y_r2_vdd"])
    c.wire("metal3", [(x_ser_vdd, y_ser_vdd_hi), (x_drv_vdd_e, y_ser_vdd_hi)], 1.200)
    for vx_off in (-0.300, +0.300):
        via2_clean(c, grid(x_drv_vdd_e + vx_off), y_ser_vdd_hi)
    c.wire("metal2", [(x_drv_vdd_e, y_ser_vdd_hi), (x_drv_vdd_e, y_drv_r1_vdd)], 1.400)

    # 5. Extend `vbg` West to outer West perimeter (-8.40, 89.50) and `vdd`/`vdrv` North to y_north_port!
    _, x_vbg, y_vbg = drv_meta["ports"]["vbg"]
    c.wire("metal2", [(x_west_port, y_vbg), (x_vbg, y_vbg)], 0.440)

    y_north = drv_meta["y_north_port"]
    x_vdd_sp = drv_meta["x_vdd_sp"]
    x_vdrv_sp = drv_meta["x_vdrv_sp"]
    c.wire("metal4", [(x_vdd_sp, drv_meta["y_vdd_t"]), (x_vdd_sp, y_north)], 1.600)
    c.wire("metal4", [(x_vdrv_sp, drv_meta["y_vdrv_t"]), (x_vdrv_sp, y_north)], 2.000)

    # 6. Export exact 38 perimeter ports in exact `serdes_tx_sst_top` schematic order!
    port_locs: dict[str, tuple[str, float, float]] = {}
    for i in range(16):
        px, py = ser_meta["south_ports"][f"din{i}"]
        port_locs[f"din{i}"] = ("metal4", px, grid(py + dy_ser))
    for nm in ("phi0", "phi90", "phi180", "phi270"):
        port_locs[nm] = ("metal3", *phi_ports[nm])
    for nm in ("rst_n", "clk500_out", "clk250_out"):
        px, py = ser_meta["south_ports"][nm]
        port_locs[nm] = ("metal4", px, grid(py + dy_ser))
    for nm in ("m0", "m1", "m2", "m3", "m4", "f0", "f1", "f2", "ffe_en", "pad_p", "pad_n"):
        port_locs[nm] = drv_meta["ports"][nm]
    port_locs["vbg"] = ("metal2", x_west_port, y_vbg)
    port_locs["vdrv"] = ("metal4", x_vdrv_sp, y_north)
    port_locs["vdd"] = ("metal4", x_vdd_sp, y_north)
    port_locs["vss"] = ("metal2", x_west_port, y_ldo_vss)

    if add_ports:
        order = (
            [f"din{i}" for i in range(16)]
            + ["phi0", "phi90", "phi180", "phi270", "rst_n"]
            + ["m0", "m1", "m2", "m3", "m4", "f0", "f1", "f2", "ffe_en"]
            + ["vbg", "pad_p", "pad_n", "vdrv", "clk500_out", "clk250_out", "vdd", "vss"]
        )
        for pnm in order:
            lyr, px, py = port_locs[pnm]
            c.port(pnm, lyr, px, py)

    return c, {"ports": port_locs, "dy_ser": dy_ser}


def _parse_rcx_net_resistors(rcx_path: Path, net_names: list[str]) -> dict[str, dict]:
    """Summarize Magic native reduced-RC wire resistors on selected nets from `*_rcx.spice`."""
    if not rcx_path.exists():
        return {}
    per_net: dict[str, list[float]] = {n: [] for n in net_names}
    for ln in rcx_path.read_text().splitlines():
        if not ln.startswith("R"):
            continue
        toks = ln.split()
        if len(toks) < 4:
            continue
        n1, n2, val_s = toks[1], toks[2], toks[3]
        base1 = re.sub(r"\.[nt]\d+$", "", n1)
        base2 = re.sub(r"\.[nt]\d+$", "", n2)
        if base1 in per_net and base1 == base2:
            try:
                per_net[base1].append(float(val_s))
            except ValueError:
                pass
    out: dict[str, dict] = {}
    for n, vals in per_net.items():
        if vals:
            out[n] = {
                "r_elem_count": len(vals),
                "r_sum_ohm": round(sum(vals), 3),
                "r_max_elem_ohm": round(max(vals), 3),
                "r_min_elem_ohm": round(min(vals), 3),
            }
        else:
            out[n] = {
                "r_elem_count": 0,
                "r_sum_ohm": 0.0,
                "r_max_elem_ohm": 0.0,
                "note": "below Magic extresist 1 ohm threshold",
            }
    return out


def _parse_check_log(log_path: Path) -> dict:
    txt = log_path.read_text() if log_path.exists() else ""
    drc_m = re.search(r"DRC_TOTAL[\s=]+(\d+)", txt)
    dev_m = re.search(r"Circuit 1 contains (\d+) devices", txt)
    net_m = re.search(r"Circuit 1 contains (\d+) nets", txt)
    lvs_match = ("Circuits match uniquely" in txt) or ("LVS_MATCH True" in txt)
    prop_err = ("Property errors were found" in txt) or ("LVS_PROPERTY_ERRORS True" in txt)
    return {
        "drc_total": int(drc_m.group(1)) if drc_m else None,
        "merged_device_count": int(dev_m.group(1)) if dev_m else None,
        "net_count": int(net_m.group(1)) if net_m else None,
        "lvs_match": lvs_match,
        "lvs_property_errors": prop_err,
    }


def _count_floating_poly(mag_path: Path) -> int:
    """Count connected components of poly/gate shapes lacking any polycont/xpolycontact."""
    cell = Cell.read(mag_path)
    poly_layers = ("polysilicon", "ntransistor", "ptransistor", "nfetlvt", "pfetlvt", "polyresistor", "ppolyres")
    cont_layers = ("polycontact", "xpolycontact")
    polys = [r for lyr in poly_layers for r in cell.rects.get(lyr, [])]
    conts = [r for lyr in cont_layers for r in cell.rects.get(lyr, [])]
    if not polys:
        return 0
    # Connected components via touching/overlapping bboxes (with 1 nm tolerance)
    eps = 0.002
    def touch(a, b):
        return not (a[2] + eps < b[0] or b[2] + eps < a[0] or a[3] + eps < b[1] or b[3] + eps < a[1])

    # Spatial grid acceleration (5 um bins)
    bins: dict[tuple[int, int], list[int]] = {}
    for idx, r in enumerate(polys):
        for bx in range(int(r[0] // 5), int(r[2] // 5) + 1):
            for by in range(int(r[1] // 5), int(r[3] // 5) + 1):
                bins.setdefault((bx, by), []).append(idx)

    parent = list(range(len(polys)))
    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for idxs in bins.values():
        n = len(idxs)
        for i in range(n):
            a = idxs[i]
            ra = polys[a]
            for j in range(i + 1, n):
                b = idxs[j]
                if touch(ra, polys[b]):
                    union(a, b)

    contacted_roots: set[int] = set()
    for cr in conts:
        for bx in range(int(cr[0] // 5), int(cr[2] // 5) + 1):
            for by in range(int(cr[1] // 5), int(cr[3] // 5) + 1):
                for idx in bins.get((bx, by), []):
                    if touch(cr, polys[idx]):
                        contacted_roots.add(find(idx))

    all_roots = {find(i) for i in range(len(polys))}
    return len(all_roots - contacted_roots)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="Optional subset of cells to build/verify")
    ap.add_argument("--skip-png", action="store_true", help="Skip PNG rendering")
    ap.add_argument(
        "--refresh-artifacts",
        action="store_true",
        help="Re-parse existing review directories, check floating poly, refresh summary.json, and re-render PNGs without rebuilding .mag",
    )
    args = ap.parse_args()

    VARIANT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(RESULTS_DIR / "_pdk_cache")

    specs = [
        ("sst_slice_unit_pdk", "sst_slice_unit", lambda: sab.build_sst_slice_unit(cache, add_ports=True),
         ["pad_p", "pad_n", "vdrv", "din_p", "din_n", "vdd", "vss"], 120),
        ("sst_vdrv_ldo_pdk", "sst_vdrv_ldo", lambda: sab.build_sst_vdrv_ldo(cache, add_ports=True),
         ["vdrv", "vbg", "vdd", "vss"], 150),
        ("serdes_tx_sst_driver_pdk", "serdes_tx_sst_driver", lambda: sdm.build_sst_driver(cache, add_ports=True),
         ["pad_p", "pad_n", "vdrv", "vdd", "vss", "phi0"], 240),
        ("serdes_tx_sst_serializer16_pdk", "serdes_tx_sst_serializer16", lambda: ssm.build_sst_serializer16(cache, add_ports=True),
         ["phi0", "d0", "db0", "clk500_out", "clk250_out", "vdd", "vss"], 240),
        ("serdes_tx_sst_top_pdk", "serdes_tx_sst_top", lambda: build_sst_top(cache, add_ports=True),
         ["pad_p", "pad_n", "vdrv", "vdd", "vss", "phi0", "phi90", "phi180", "phi270", "clk500_out", "clk250_out"], 360),
    ]

    if args.only:
        only_set = set(args.only)
        specs = [s for s in specs if s[0] in only_set]

    summary: dict[str, dict] = {}

    for cell_name, src_subckt, builder, rc_watch_nets, timeout_s in specs:
        mag_path = VARIANT_DIR / f"{cell_name}.mag"
        ref_path = VARIANT_DIR / f"{cell_name}_ref.spice"
        review_dir = RESULTS_DIR / "review" / cell_name
        if args.refresh_artifacts:
            print(f"\n=== Refreshing {cell_name} from {review_dir} ===", flush=True)
            expected_ports = slc.exported_ports(ref_path, cell_name)
            rev = json.loads((review_dir / "summary.json").read_text())
            rc_path = review_dir / "rc_summary.json"
            if rc_path.exists():
                rev["rc"] = json.loads(rc_path.read_text())
        else:
            print(f"\n=== Building & Signing Off {cell_name} (from {src_subckt}) ===", flush=True)
            cell, _meta = builder()
            cell.write(mag_path)
            expected_ports = slc.generate_ref_spice(src_subckt, cell_name, ref_path)
            rev = slc.run_independent_review(mag_path, ref_path, review_dir, timeout_s=timeout_s)

        chk = _parse_check_log(review_dir / "check.log")
        floating_poly = _count_floating_poly(mag_path)
        lvs_log = review_dir / f"{cell_name}_lvs.log"
        lvs_txt = lvs_log.read_text() if lvs_log.exists() else ""
        lvs_match = "Circuits match uniquely" in lvs_txt
        lvs_prop_err = "Property errors were found" in lvs_txt
        raw_dev_count = sum(1 for ln in ref_path.read_text().splitlines() if ln.startswith("X"))

        w_um = round(rev["size_um"][0], 3)
        h_um = round(rev["size_um"][1], 3)
        area_um2 = round(w_um * h_um, 2)
        ar = round(w_um / max(h_um, 1e-6), 2)

        pcaps = rev.get("parasitics", {}).get("port_caps_fF", {})
        key_caps = {k: pcaps[k] for k in rc_watch_nets if k in pcaps}
        rc_nets = _parse_rcx_net_resistors(review_dir / f"{cell_name}_rcx.spice", rc_watch_nets)

        png_path = VARIANT_DIR / f"{cell_name}.png"
        if not args.skip_png:
            slc.render_png_plot_mag(mag_path, png_path)

        entry = {
            "cell": cell_name,
            "source_subckt": src_subckt,
            "mag": str(mag_path.relative_to(slc.REPO)),
            "ref_spice": str(ref_path.relative_to(slc.REPO)),
            "png": str(png_path.relative_to(slc.REPO)) if not args.skip_png else None,
            "review_dir": str(review_dir.relative_to(slc.REPO)),
            "pex_spice": str((review_dir / f"{cell_name}_pex.spice").relative_to(slc.REPO)),
            "rcx_spice": str((review_dir / f"{cell_name}_rcx.spice").relative_to(slc.REPO)),
            "bbox_um": [round(v, 3) for v in rev["bbox_um"]],
            "width_um": w_um,
            "height_um": h_um,
            "area_um2": area_um2,
            "aspect_ratio": ar,
            "expected_port_count": len(expected_ports),
            "exported_port_count": len(rev["ports"]),
            "port_count_match": (len(rev["ports"]) == len(expected_ports) and set(rev["ports"]) == set(expected_ports)),
            "physical_passed": rev["physical_passed"],
            "drc_total": chk["drc_total"],
            "floating_poly": floating_poly,
            "lvs_match": lvs_match,
            "lvs_property_errors": lvs_prop_err,
            "rc_devices_preserved": rev.get("rc", {}).get("devices_preserved", False),
            "rc_resistor_count": rev.get("rc", {}).get("resistor_count", 0),
            "rc_resistor_nets": rev.get("rc", {}).get("resistor_nets", []),
            "key_port_caps_fF": key_caps,
            "key_net_rcx_ohm": rc_nets,
            "raw_device_count": raw_dev_count,
            "merged_device_count": chk["merged_device_count"],
            "net_count": chk["net_count"],
        }
        summary[cell_name] = entry
        print(
            f"  {cell_name}: {w_um:.2f} x {h_um:.2f} um ({area_um2:,.1f} um^2, AR={ar:.2f}) | "
            f"DRC={chk['drc_total']} FP={floating_poly} LVS={lvs_match} prop_err={lvs_prop_err} "
            f"ports={len(rev['ports'])}/{len(expected_ports)} phys={rev['physical_passed']} "
            f"rc_dev_ok={entry['rc_devices_preserved']} devs={raw_dev_count}({chk['merged_device_count']})",
            flush=True,
        )
        if "pad_p" in key_caps and "pad_n" in key_caps:
            print(
                f"    pad_p={key_caps['pad_p']['total_node_fF']:.3f} fF "
                f"(sub={key_caps['pad_p']['to_substrate_fF']:.3f}), "
                f"pad_n={key_caps['pad_n']['total_node_fF']:.3f} fF "
                f"(sub={key_caps['pad_n']['to_substrate_fF']:.3f})",
                flush=True,
            )
        if "vdrv" in key_caps:
            print(
                f"    vdrv cap={key_caps['vdrv']['total_node_fF']:.3f} fF | "
                f"rcx={rc_nets.get('vdrv', {})}",
                flush=True,
            )

    if not args.only:
        out_json = VARIANT_DIR / "summary.json"
        out_json.write_text(json.dumps({"variant": "v4_pdk", "pdk": "sky130A", "cells": summary}, indent=2) + "\n")
        print(f"\nWrote {out_json}", flush=True)


if __name__ == "__main__":
    main()
