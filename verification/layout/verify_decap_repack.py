#!/usr/bin/env python3
"""Per-rail 4G decap inventory and independent load-side RLC sensitivity sweep."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import numpy as np

from geometry import Cell


# TT biased side-8 values recorded with the full_v8 handoff.
TILE_PF = {"serdes_decap_hybrid_1v8_pdk": 1.265, "serdes_decap_hybrid_hv33_pdk": 0.622}
# Staging points for the next physical A/B. Retain LDO output capacitance at the
# original total pending feedback-loop and VCO supply-pushing validation.
TRIAL_COUNTS = {"vdd_hv33": 16, "vdd_q": 48, "vdd_bias": 8, "vdd_a": 24,
                "vdd_tx": 16, "vdd_rx": 20, "vdd_d": 32}
FREQUENCIES = np.geomspace(1e7, 5e9, 1401)


def impedance(intrinsic_pf: float, tiles_pf: float, package_nh: float,
              access_ph: float, access_ohm: float, damping_ohm: float = 0) -> np.ndarray:
    """Seen by a local small-signal current sink with the package source AC grounded."""
    jw = 2j * np.pi * FREQUENCIES
    admittance = 1 / (0.65 + jw * package_nh * 1e-9) + jw * intrinsic_pf * 1e-12
    if tiles_pf == 0:
        return abs(1 / admittance)
    # A parallel bank with a dedicated series resistor on the damping branch.
    # Access impedance is common to both sections and belongs before the split.
    capacitance = tiles_pf * 1e-12
    if damping_ohm:
        bank_y = jw * capacitance / 2 + 1 / (damping_ohm + 2 / (jw * capacitance))
    else:
        bank_y = jw * capacitance
    admittance += 1 / (access_ohm + jw * access_ph * 1e-12 + 1 / bank_y)
    return abs(1 / admittance)


def measures(values: np.ndarray) -> dict:
    mask = (FREQUENCIES >= 50e6) & (FREQUENCIES <= 2.5e9)
    indices = np.flatnonzero(mask)
    peak_index = indices[values[mask].argmax()]
    return {
        "peak_ohm_50mhz_to_2p5ghz": round(float(values[peak_index]), 3),
        "peak_mhz": round(float(FREQUENCIES[peak_index] / 1e6), 2),
        **{f"z_ohm_{f}_mhz": round(float(np.interp(f*1e6, FREQUENCIES, values)), 3)
           for f in (250, 500, 1000, 2000, 2500)},
    }


def run(source: Path, output: Path) -> None:
    summary = json.loads((source / "summary.json").read_text())
    counts = Counter()
    cells = {}
    footprint = {}
    for bank in summary["decap_placements"]:
        name, cell = bank["domain"], bank["cell"]
        counts[name] += bank["tiles"]
        if name in cells and cells[name] != cell:
            raise ValueError(f"Mixed capacitor types on {name}")
        cells[name] = cell
        if cell not in footprint:
            x0, y0, x1, y1 = Cell.read(source / f"{cell}.mag").bbox()
            footprint[cell] = (x1-x0)*(y1-y0)
    if sum(counts.values()) != summary["decap_tiles_total"] or counts.keys() != TRIAL_COUNTS.keys():
        raise ValueError("Unexpected assembly inventory")

    inventory = {}
    scenarios = {}
    traces = {}
    for name, count in sorted(counts.items()):
        tile_pf = TILE_PF[cells[name]]
        trial = TRIAL_COUNTS[name]
        inventory[name] = {
            "as_built_tiles": count, "as_built_cap_pf": round(count * tile_pf, 3),
            "trial_tiles": trial, "trial_cap_pf": round(trial * tile_pf, 3),
            "tile_footprint_um2": round(footprint[cells[name]], 3),
        }
        if name not in ("vdd_a", "vdd_d", "vdd_rx", "vdd_tx"):
            continue
        intrinsic = summary["floorplan_kpi"]["domains"][name]["internal_cap_pf"]
        estimates = {}
        traces[name] = {}
        options = {
            "no_top_tiles": (0, 0, 0, 0),
            "same_tiles_remote": (count, 250, 0.35, 0),
            "same_tiles_local": (count, 35, 0.08, 0),
            "repack_local": (trial, 35, 0.08, 0),
            "repack_half_damped_1ohm": (trial, 35, 0.08, 1),
            "repack_half_damped_3ohm": (trial, 35, 0.08, 3),
            "repack_half_damped_6ohm": (trial, 35, 0.08, 6),
        }
        if name == "vdd_d":
            options["aggressive_16_half_damped_6ohm"] = (16, 35, 0.08, 6)
        for option, (tiles, access, resistance, damping) in options.items():
            results = []
            for scale in (0.5, 1, 1.5):
                for package in (0.5, 1.5, 4):
                    values = impedance(intrinsic*scale, tiles*tile_pf, package, access, resistance, damping)
                    results.append({"intrinsic_scale": scale, "package_nh": package, **measures(values)})
                    if scale == 1 and package == 1.5:
                        traces[name][option] = values
            estimates[option] = results
        scenarios[name] = {"planning_intrinsic_pf": intrinsic, "cases": estimates}

    output.mkdir(parents=True)
    report = {
        "source": str(source), "tile_pf_from_full_v8_handoff": TILE_PF, "inventory": inventory,
        "total_as_built_tiles": sum(counts.values()), "total_trial_tiles": sum(TRIAL_COUNTS.values()),
        "total_as_built_pf": round(sum(i["as_built_cap_pf"] for i in inventory.values()), 3),
        "total_trial_pf": round(sum(i["trial_cap_pf"] for i in inventory.values()), 3),
        "as_built_tile_footprints_um2": round(sum(count*footprint[cells[n]] for n, count in counts.items()), 2),
        "trial_tile_footprints_um2": round(sum(count*footprint[cells[n]] for n, count in TRIAL_COUNTS.items()), 2),
        "top_bank_reservation_um2": summary["floorplan_kpi"]["packing"]["decap_area_um2"],
        "model": {"source_series_resistance_ohm": 0.65, "local_access_pH": 35, "remote_access_pH": 250,
                  "local_access_ohm": 0.08, "remote_access_ohm": 0.35,
                  "note": "Sensitivity hypotheses for separate external 1.8 V rails. Access and package "
                          "impedances are assumed. Intrinsic caps are planning values, and tile ESR is "
                          "subsumed into the branch assumptions. Regulated VDD_Q needs its LDO loop model."},
        "rails": scenarios,
    }
    (output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(10, 7), layout="constrained", sharex=True)
    names = ("no_top_tiles", "same_tiles_remote", "same_tiles_local", "repack_local", "repack_half_damped_3ohm")
    labels = ("No top tiles", "Original count / remote", "Original count / local",
              "Trial count / local", "Trial / half through 3 ohm")
    for (rail, options), ax in zip(traces.items(), axes.flat):
        for name, label in zip(names, labels):
            ax.loglog(FREQUENCIES / 1e6, options[name], label=label)
        ax.set_title(rail.upper())
        ax.grid(which="both", alpha=0.2)
        ax.set_xlabel("Frequency (MHz)")
        ax.set_ylabel("Load-side |Z| (ohm)")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("4G decap placement sensitivity | 1.5 nH independent package-loop hypothesis")
    fig.savefig(output / "pdn_sweep.png", dpi=145)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("assembly", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    run(args.assembly, args.output_dir)
