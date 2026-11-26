from pathlib import Path
import sys

import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "verification/layout"))
from geometry import Cell
from route_manhattan import (
    RouteUnavailable,
    candidate_net_orders,
    route,
    write_metal_delta,
)


def test_crossing_uses_upper_layer_and_keeps_blockers():
    base = Cell()
    base.pad("metal4", 1.0, 5.0, 0.8)
    base.pad("metal4", 19.0, 5.0, 0.8)
    for layer in ("metal3", "metal4"):
        base.rect(layer, 8, -1, 12, 11)
    box = [0, 0, 20, 10]
    job = [{"name": "bridge", "terminals": [["metal4", 1, 5], ["metal4", 19, 5]]}]

    with pytest.raises(RouteUnavailable):
        route(base, box, job, ("metal3", "metal4"))

    result, report = route(base, box, job)
    assert report["bridge"] == {"length_um": {"metal5": 18.0}, "vias": {"via4": 2}}
    assert result.rects["metal3"] == base.rects["metal3"]
    assert len(result.rects["via4"]) == 2
    assert "via4" not in base.rects


def test_magic_delta_keeps_nonport_labels_and_pin_indices(tmp_path):
    source = tmp_path / "base.mag"
    trailer = """<< labels >>
rlabel metal4 200 200 400 240 0 test_pin
port 7 nsew
rlabel metal4 300 200 300 200 0 diagnostic_label
<< properties >>
string TEST_KEEP yes
<< end >>
"""
    source.write_text(
        "magic\ntech sky130A\nmagscale 1 2\ntimestamp 1234\n"
        "<< metal4 >>\nrect 160 160 440 280\n" + trailer
    )
    before = Cell.read(source)
    after = Cell.read(source)
    after.rect("metal4", 1.2, 1.2, 2.0, 1.4)
    after.rect("metal5", 0.0, 0.0, 2.0, 2.0)
    target = tmp_path / "after.mag"

    write_metal_delta(source, target, before, after)

    assert target.read_text().endswith(trailer)
    assert "timestamp 1234\n" in target.read_text()
    assert Cell.read(target).rects == after.rects


def test_metal2_via2_underpass_and_custom_width():
    base = Cell()
    base.pad("metal3", 1.0, 5.0, 0.8)
    base.pad("metal3", 11.0, 5.0, 0.8)
    # Block M3 and M4 across x=[5..7]; M2 is open underneath
    for layer in ("metal3", "metal4"):
        base.rect(layer, 5.0, 0.0, 7.0, 10.0)
    box = [0, 0, 12, 10]
    nets = [{"name": "bias", "width_um": {"metal2": 0.40}, "terminals": [["metal3", 1, 5], ["metal3", 11, 5]]}]

    with pytest.raises(RouteUnavailable):
        route(base, box, nets, ("metal3", "metal4"))

    res, rep = route(base, box, nets, ("metal2", "metal3", "metal4"))
    assert rep["bias"]["vias"].get("via2", 0) == 2
    assert rep["bias"]["length_um"].get("metal2", 0.0) > 2.0
    # Verify custom M2 width (0.40 um) was emitted
    m2_heights = [round(y2 - y1, 3) for x1, y1, x2, y2 in res.rects["metal2"] if (x2 - x1) > 1.0]
    assert any(abs(h - 0.40) < 1e-6 for h in m2_heights)


def test_keepout_and_diff_pair_coupling_separation():
    base = Cell()
    for y in (4.6, 5.4):
        base.pad("metal3", 1.0, y, 0.4)
        base.pad("metal3", 13.0, y, 0.4)
    box = [0, 0, 14, 12]
    nets = [
        {"name": "sig_p", "terminals": [["metal3", 1.0, 4.6], ["metal3", 13.0, 4.6]]},
        {"name": "sig_n", "terminals": [["metal3", 1.0, 5.4], ["metal3", 13.0, 5.4]]},
    ]

    # Without coupling avoidance, sig_n hugs close to sig_p (parallel ~12 um)
    pdiag_base = {}
    _, rep_base = route(base, box, nets, ("metal3", "metal4"),
                        diff_pairs=[("sig_p", "sig_n")], pair_diagnostics=pdiag_base)

    # With coupling avoidance + keepout above y=9, sig_n spreads away from sig_p while respecting keepout
    pdiag_sep = {}
    keepouts = [{"box_um": [4.0, 9.0, 10.0, 12.0], "layers": ["metal3", "metal4"]}]
    res_sep, rep_sep = route(
        base, box, nets, ("metal3", "metal4"),
        keepouts=keepouts,
        diff_pairs=[("sig_p", "sig_n")],
        coupling_weight=8.0,
        coupling_radius_um=3.0,
        pair_diagnostics=pdiag_sep,
    )
    assert pdiag_sep["sig_p:sig_n"]["same_layer_parallel_um"] < pdiag_base["sig_p:sig_n"]["same_layer_parallel_um"]
    # Verify no routed M3/M4 segment intrudes into keepout [4..10] x [9..12]
    for lyr in ("metal3", "metal4"):
        for x1, y1, x2, y2 in res_sep.rects.get(lyr, ()):
            assert not (min(x2, 10.0) > max(x1, 4.0) and min(y2, 12.0) > max(y1, 9.0))


def test_candidate_net_orders_deduplicates():
    nets = [
        {"name": "short", "terminals": [["metal3", 0, 0], ["metal3", 2, 0]]},
        {"name": "long", "terminals": [["metal3", 0, 1], ["metal3", 10, 1]]},
        {"name": "mid", "terminals": [["metal3", 0, 2], ["metal3", 5, 2]]},
    ]
    orders = candidate_net_orders(nets)
    keys = [tuple(n["name"] for n in o) for o in orders]
    assert len(keys) == len(set(keys))
    assert keys[0] == ("short", "long", "mid")
    assert ("short", "mid", "long") in keys
