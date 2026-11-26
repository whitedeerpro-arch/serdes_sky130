#!/usr/bin/env python3
"""SKY130A Compact 5.0 Gb/s Shunt-Peaked RX CTLE PDK Layout Builder (`serdes_rx_ctle_shunt_5g_compact_pdk`).

Integrates:
  1. Signed-off `serdes_rx_ctle_active_5g_pdk` (41.40 x 26.10 um, 0% M5, DRC=0, LVS=MATCH)
  2. Compact 0%-M5 `M4+M2` 12-turn stacked inductor `rx_ctle_ind_m4m2_5g_pdk`
     (57.60 x 57.60 um = 3,318 um^2, -60.5% coil area, -44.1% C_sub=58.5 fF, L_diff=8.204 nH, DRC=0)

Resulting compact flat top macro (`serdes_rx_ctle_shunt_5g_compact_pdk`):
  - Size: 57.60 x 91.30 um (5,259 um^2 = 0.00526 mm^2, -54.2% vs 91.6 x 125.3 um M5+M3 macro!)
  - 0.0% M5 across the ENTIRE macro (active + coil + routing!)
  - Identical 9-port cardinal interface as `serdes_rx_ctle_shunt_5g_pdk`
  - Verified with Magic `drc(full) = 0`, `FP = 0`, DC-LVS `MATCH` (0 prop err), and Inductor-Open LVS `MATCH`!
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import rx_layout_common as rlc  # noqa: E402
import build_rx_ctle_shunt_5g_pdk as ctle5g  # noqa: E402
from rx_layout_common import Cell, PdkCache, grid, via1_clean  # noqa: E402

REPO = rlc.REPO
IND_COMPACT_MAG = HERE / "variants" / "ctle_shunt_ind_compact_5g_pdk" / "rx_ctle_ind_m4m2_5g_pdk.mag"
VARIANT_DIR = HERE / "variants" / "ctle_shunt_5g_compact_pdk"
RESULTS_DIR = REPO / "results" / "layout" / "rx_ctle_shunt_5g_compact_pdk"
TOP_NAME = "serdes_rx_ctle_shunt_5g_compact_pdk"
TOP_PORTS = ctle5g.TOP_PORTS
ACTIVE_PORTS = ctle5g.ACTIVE_PORTS


def build_compact_ctle_top(
    active_cell: Cell,
    active_meta: dict,
    *,
    include_inductor: bool = True,
    add_ports: bool = True,
) -> tuple[Cell, dict]:
    """Assemble flat compact `serdes_rx_ctle_shunt_5g_compact_pdk` (57.60 x 91.30 um, 0% M5)."""
    c = Cell()

    # 1. Include Active CTLE (North, labels stripped)
    act_unlbl = rlc.clone_cell(active_cell)
    act_unlbl.labels.clear()
    c.include(act_unlbl, dx=0.0, dy=0.0)

    # 2. Include compact 57.6x57.6 um M4+M2 inductor rotated 180 deg on South (6.20 um clearance!)
    ind_cy = -35.000  # North guard ring outer edge: -35.0 + 28.8 = -6.200 (exact 6.20 um gap to y=0!)
    if include_inductor:
        ind = Cell.read(IND_COMPACT_MAG)
        ind.labels.clear()
        c.include(ind, dx=0.0, dy=ind_cy, mirror_x=True, mirror_y=True)

    x_west = -28.800
    x_east = +28.800
    x_act_w = active_meta["x_w_port"]    # -20.700
    x_act_e = active_meta["x_e_port"]    # +20.700
    x_vdd_act = active_meta["x_vdd_act"] # -20.100
    y_vss_top = active_meta["y_vss_n"]   # +25.700
    y_vdd_top = -4.200                   # centered in 6.20 um clearance gap ([-5.10, -3.30])

    # 3. Zero-via, 0%-M5 mirror-symmetric M4 `lp_mid` / `ln_mid` feeds:
    #    Active M4 pads (+-4.60, 0.00) -> jog gently to (+-3.00, -2.00) -> fuse seamlessly into M4 coil leads (+-3.00, -7.80..-11.00)!
    for sgn in (-1.0, +1.0):
        xa = sgn * 4.600
        xi = sgn * 3.000
        c.rect("metal4", grid(xa - 0.600), -2.400, grid(xa + 0.600), +0.400)
        c.rect("metal4", grid(min(xa, xi) - 0.600), -2.400, grid(max(xa, xi) + 0.600), -1.200)
        c.rect("metal4", grid(xi - 0.600), -9.000, grid(xi + 0.600), -1.200)

    # 4. Low-impedance `ct (M2 at 0.0, -7.80)` -> wide 1.80 um M3 `vdd` rail at y=-4.20 (passes cleanly under M4 lp/ln!)
    c.rect("metal2", -0.600, -9.000, +0.600, grid(y_vdd_top + 0.600))
    for dxv in (-0.300, +0.300):
        for dyv in (-0.300, +0.300):
            c.pad("via2", dxv, grid(y_vdd_top + dyv), 0.280)
    c.rect("metal3", x_west, grid(y_vdd_top - 0.900), x_east, grid(y_vdd_top + 0.900))
    # Parallel M4 wing straps outside |x| >= 6.40 for extra-low rail R (clear of lp/ln at +-3.0..4.6!)
    for xa, xb in ((x_west, -6.400), (+6.400, x_east)):
        c.rect("metal4", xa, grid(y_vdd_top - 0.900), xb, grid(y_vdd_top + 0.900))
        xv = grid(xa + 1.200)
        while xv <= xb - 1.200 + 1e-6:
            for dyv in (-0.360, +0.360):
                c.pad("via3", xv, grid(y_vdd_top + dyv), 0.320)
            xv = grid(xv + 4.000)

    # Connect Active CTLE `vdd` (M2 at -20.10, 0.00) -> wide M3 `vdd` rail at y=-4.20
    c.rect("metal2", grid(x_vdd_act - 0.400), grid(y_vdd_top - 0.600), grid(x_vdd_act + 0.400), +0.200)
    for dxv in (-0.220, +0.220):
        for dyv in (-0.300, +0.300):
            c.pad("via2", grid(x_vdd_act + dxv), grid(y_vdd_top + dyv), 0.280)

    # 5. Wide North `vss` rail (`1.80 um` M3 at y=+26.60 + full-width M2 merging seamlessly with Active CTLE M2 vss)
    y_vss_m3 = +26.600
    c.rect("metal2", x_west, grid(y_vss_top - 0.400), x_east, grid(y_vss_m3 + 0.500))
    c.rect("metal3", x_west, grid(y_vss_m3 - 0.900), x_east, grid(y_vss_m3 + 0.900))
    for xv in (-24.0, -16.0, -8.0, 0.0, +8.0, +16.0, +24.0):
        for dyv in (-0.300, +0.300):
            c.pad("via2", xv, grid(y_vss_m3 - 0.150 + dyv), 0.280)

    # Single-sided West `vss` tie to inductor's open-slotted P+ guard ring at (-22.800, -7.000)
    # Passes strictly West of active core (-20.70) on M2 (under M3 vdd & M4 outp/outn, over M1 eq0/eq1 -> 0 crossings!)
    x_vss_gr = -22.800
    y_gr_n = grid(ind_cy + 28.000)  # -7.000 (center of 1.60 um guard ring bar [-7.80, -6.20])
    c.rect("metal2", grid(x_vss_gr - 0.700), grid(y_gr_n - 0.700), grid(x_vss_gr + 0.700), grid(y_vss_m3 + 0.500))
    c.rect("metal1", grid(x_vss_gr - 0.700), grid(y_gr_n - 0.700), grid(x_vss_gr + 0.700), grid(y_gr_n + 0.700))
    for dxv in (-0.360, 0.000, +0.360):
        for dyv in (-0.360, +0.360):
            c.pad("via1", grid(x_vss_gr + dxv), grid(y_gr_n + dyv), 0.260)

    # 6. Straight Zero-Jog Cardinal Perimeter Extensions (identical Y & layer to M5+M3 macro!)
    y_inp = active_meta["y_inp_m3"]      # +6.450 (East, M3)
    y_inn = active_meta["y_inn_m3"]      # +5.550 (East, M3)
    y_outp = active_meta["y_outp_bus"]   # +7.300 (West, M4)
    y_outn = active_meta["y_outn_bus"]   # +4.700 (West, M4)
    y_eq0 = active_meta["y_eq0_out"]     # +11.650 (West, M1)
    y_eq1 = active_meta["y_eq1_out"]     # +23.250 (West, M1)
    y_vbias = active_meta["y_vbias"]     # +23.600 (East, M1 -> M2)

    c.rect("metal3", grid(x_act_e - 0.200), grid(y_inp - 0.200), x_east, grid(y_inp + 0.200))
    c.rect("metal3", grid(x_act_e - 0.200), grid(y_inn - 0.200), x_east, grid(y_inn + 0.200))

    x_vb_v1 = grid(x_act_e + 0.600)
    c.rect("metal1", grid(x_act_e - 0.200), grid(y_vbias - 0.170), grid(x_vb_v1 + 0.160), grid(y_vbias + 0.170))
    via1_clean(c, x_vb_v1, y_vbias)
    c.rect("metal2", grid(x_vb_v1 - 0.200), grid(y_vbias - 0.200), x_east, grid(y_vbias + 0.200))

    c.rect("metal4", x_west, grid(y_outp - 0.200), grid(x_act_w + 0.200), grid(y_outp + 0.200))
    c.rect("metal4", x_west, grid(y_outn - 0.200), grid(x_act_w + 0.200), grid(y_outn + 0.200))

    c.rect("metal1", x_west, grid(y_eq0 - 0.170), grid(x_act_w + 0.200), grid(y_eq0 + 0.170))
    c.rect("metal1", x_west, grid(y_eq1 - 0.170), grid(x_act_w + 0.200), grid(y_eq1 + 0.170))

    top_ports = {
        "inp":   ("metal3", x_east, y_inp),
        "inn":   ("metal3", x_east, y_inn),
        "outp":  ("metal4", x_west, y_outp),
        "outn":  ("metal4", x_west, y_outn),
        "eq0":   ("metal1", x_west, y_eq0),
        "eq1":   ("metal1", x_west, y_eq1),
        "vbias": ("metal2", x_east, y_vbias),
        "vdd":   ("metal3", x_west, y_vdd_top),
        "vss":   ("metal3", x_west, y_vss_m3),
    }
    if add_ports:
        for nm in TOP_PORTS:
            lyr, px, py = top_ports[nm]
            c.port(nm, lyr, px, py)

    return c, {
        "ports": {nm: {"layer": lyr, "x_um": px, "y_um": py} for nm, (lyr, px, py) in top_ports.items()},
        "ind_center_um": [0.0, ind_cy],
        "ind_clearance_um": 6.20,
        "vdd_rail_y_um": y_vdd_top,
        "vss_rail_y_um": y_vss_m3,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = PdkCache(RESULTS_DIR / "_pdk_cache")
    act_cell, act_meta = ctle5g.build_rx_ctle_active_5g_pdk(cache, add_ports=False)

    # 1. Full flat compact top: Magic full DRC + DC-LVS + CPEX
    w_top = RESULTS_DIR / "top_verify"
    w_top.mkdir(parents=True, exist_ok=True)
    top_cell, top_meta = build_compact_ctle_top(act_cell, act_meta, include_inductor=True, add_ports=True)
    top_mag = w_top / f"{TOP_NAME}.mag"
    top_cell.write(top_mag)
    dc_ref = w_top / f"{TOP_NAME}_dc_ref.spice"
    dc_ref.write_text(
        f"* DC-equivalent LVS ref for {TOP_NAME}\n"
        f".subckt {TOP_NAME} " + " ".join(TOP_PORTS) + "\n"
        + "\n".join(ctle5g._active_primitive_lines("vdd", "vdd")) + "\n"
        + f".ends {TOP_NAME}\n"
    )
    rep_top = rlc.verify_flat_cell(w_top, TOP_NAME, top_mag, dc_ref, TOP_PORTS, timeout_s=180)

    # 2. Inductor-Open LVS harness (proves lp_mid / ln_mid stay 100% isolated from vdd / vss outside coil!)
    w_open = RESULTS_DIR / "top_open_verify"
    w_open.mkdir(parents=True, exist_ok=True)
    open_name = f"{TOP_NAME}_open"
    open_cell, _ = build_compact_ctle_top(act_cell, act_meta, include_inductor=False, add_ports=True)
    open_cell.port("lp_mid", "metal4", -3.000, -8.500)
    open_cell.port("ln_mid", "metal4", +3.000, -8.500)
    open_mag = w_open / f"{open_name}.mag"
    open_cell.write(open_mag)
    open_ref = w_open / f"{open_name}_ref.spice"
    open_ref.write_text(
        f".subckt {open_name} " + " ".join(ACTIVE_PORTS) + "\n"
        + "\n".join(ctle5g._active_primitive_lines("lp_mid", "ln_mid")) + "\n"
        + f".ends {open_name}\n"
    )
    rep_open = rlc.verify_flat_cell(w_open, open_name, open_mag, open_ref, ACTIVE_PORTS, timeout_s=180)

    top_png = RESULTS_DIR / f"{TOP_NAME}.png"
    rlc.render_png_plot_mag(top_mag, top_png)

    summary = {
        "variant": "ctle_shunt_5g_compact_pdk",
        "cell": TOP_NAME,
        "pdk": "sky130A",
        "bbox_um": rep_top["bbox_um"],
        "width_um": rep_top["width_um"],
        "height_um": rep_top["height_um"],
        "area_um2": rep_top["area_um2"],
        "area_mm2": round(rep_top["area_um2"] / 1e6, 5),
        "area_vs_m5m3_ctle_pct": round(rep_top["area_um2"] / 11477.48 * 100.0, 1),
        "aspect_ratio": rep_top["aspect_ratio"],
        "ports": top_meta["ports"],
        "drc_total": rep_top["drc_total"],
        "drc_rules": rep_top["drc_rules"],
        "floating_poly": rep_top["floating_poly"],
        "dc_lvs_match": rep_top["lvs_match"],
        "dc_lvs_property_errors": rep_top["lvs_property_errors"],
        "inductor_open_drc_total": rep_open["drc_total"],
        "inductor_open_lvs_match": rep_open["lvs_match"],
        "inductor_open_lvs_property_errors": rep_open["lvs_property_errors"],
        "metal_shares": rep_top["metal_shares"],
        "inductor_open_port_caps_fF": rep_open["parasitics"].get("port_caps_fF", {}),
        "inductor_submacro": "analog/rx/cmos_rx/layout/variants/ctle_shunt_ind_compact_5g_pdk/rx_ctle_ind_m4m2_5g_pdk.mag",
        "mag_sha256": hashlib.sha256(top_mag.read_bytes()).hexdigest(),
    }
    (RESULTS_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({
        k: summary[k] for k in (
            "cell", "width_um", "height_um", "area_um2", "area_vs_m5m3_ctle_pct",
            "drc_total", "drc_rules", "floating_poly",
            "dc_lvs_match", "dc_lvs_property_errors",
            "inductor_open_lvs_match", "inductor_open_lvs_property_errors",
        )
    }, indent=2))
    print("metal_shares:", summary["metal_shares"]["share_pct"])
    op_caps = summary["inductor_open_port_caps_fF"]
    for nm in ("inp", "inn", "outp", "outn", "lp_mid", "ln_mid"):
        if nm in op_caps:
            print(f"  OPEN {nm:8s}: {op_caps[nm]}")

    assert summary["drc_total"] == 0, f"DRC={summary['drc_total']}"
    assert summary["floating_poly"] == 0, f"FP={summary['floating_poly']}"
    assert summary["dc_lvs_match"] and not summary["dc_lvs_property_errors"], "DC-LVS failed"
    assert summary["inductor_open_lvs_match"] and not summary["inductor_open_lvs_property_errors"], "Open-LVS failed"

    if args.install:
        VARIANT_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(top_mag, VARIANT_DIR / f"{TOP_NAME}.mag")
        shutil.copy2(dc_ref, VARIANT_DIR / f"{TOP_NAME}_ref.spice")
        shutil.copy2(top_png, VARIANT_DIR / f"{TOP_NAME}.png")
        shutil.copy2(w_top / f"{TOP_NAME}_lvs.spice", VARIANT_DIR / f"{TOP_NAME}_lvs.spice")
        shutil.copy2(w_open / f"{open_name}_pex.spice", VARIANT_DIR / f"{TOP_NAME}_open_pex.spice")
        (VARIANT_DIR / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(f"SIGNOFF PASS: Installed `{TOP_NAME}` -> {VARIANT_DIR}")


if __name__ == "__main__":
    main()
