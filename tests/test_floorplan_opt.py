from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification/layout"))
from floorplan_opt import (
    MacroSpec,
    NetSpec,
    Placement,
    analyze_whitespace,
    audit_bus_alignment,
    optimize_macro_positions,
    optimize_port_distribution,
)


def test_macro_micro_optimization_compacts_and_respects_clearance():
    macros = {
        "A": MacroSpec("A", 100.0, 80.0, {"out": (100.0, 40.0, "metal3")}),
        "B": MacroSpec("B", 40.0, 50.0, {"in": (0.0, 25.0, "metal3")}),
    }
    init = {
        "A": Placement("A", 0.0, 0.0, locked=True),
        "B": Placement("B", 130.0, 5.0, locked=False, x_bounds=(100.0, 150.0), y_bounds=(0.0, 60.0)),
    }
    nets = [NetSpec("sig", (("A", "out"), ("B", "in")), weight=5.0)]
    best, rep = optimize_macro_positions(
        macros, init, nets,
        area_weight=0.02,
        pair_clearances={("A", "B"): 7.0},
    )
    assert rep["after"]["feasible"] is True
    assert abs(best["B"].x - 107.0) < 0.15
    assert abs(best["B"].y - 15.0) < 0.15
    assert rep["delta_area_um2"] < 0
    assert rep["delta_weighted_hpwl_um"] < 0


def test_port_redistribution_eliminates_crossings_and_keeps_pitch():
    internal = {"b0": 10.0, "b1": 30.0, "b2": 20.0, "b3": 40.0}
    external = {"b0": 12.0, "b1": 14.0, "b2": 16.0, "b3": 18.0}
    res = optimize_port_distribution(
        (0.0, 50.0), internal, external,
        min_pitch_um=2.0, order_by="external",
    )
    assert res["external_crossings_before"] == 1
    assert res["external_crossings_after"] == 0
    coords = [res["ports"][k] for k in ("b0", "b1", "b2", "b3")]
    assert all(b - a >= 2.0 - 1e-6 for a, b in zip(coords, coords[1:]))
    assert coords[0] >= 0.0 and coords[-1] <= 50.0


def test_whitespace_and_bus_audit():
    macros = {
        "SW": MacroSpec("SW", 60.0, 40.0, {}),
        "N": MacroSpec("N", 100.0, 40.0, {}),
    }
    pls = {
        "SW": Placement("SW", 0.0, 0.0, locked=True),
        "N": Placement("N", 0.0, 40.0, locked=True),
    }
    pockets = analyze_whitespace(macros, pls, min_side_um=10.0, min_area_um2=100.0)
    assert len(pockets) == 1
    assert pockets[0]["box_um"] == [60.0, 0.0, 100.0, 40.0]
    assert pockets[0]["area_um2"] == 1600.0

    audit = audit_bus_alignment(
        {"d0": (10.0, 100.0), "d1": (20.0, 100.0), "d2": (30.0, 100.0)},
        {"p0": (25.0, 110.0), "p1": (15.0, 110.0), "p2": (35.0, 110.0)},
        {"d0": "p0", "d1": "p1", "d2": "p2"},
    )
    assert audit["crossings"] == 1
    assert audit["total_lateral_skew_um"] == 25.0
