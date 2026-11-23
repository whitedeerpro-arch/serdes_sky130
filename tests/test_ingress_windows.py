import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wp004", ROOT / "verification/work_packages/wp004_ingress_windows.py")
wp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wp)


def test_windows_and_zero_margin():
    intervals = [(100, 200), (150, 250)]
    assert wp.window(intervals, 100)["feasible"] is False
    result = wp.window(intervals, 200)
    assert (result["minimum_window_ps"], result["phi_lo_ps"], result["phi_hi_ps"]) == (150, -100, -50)
    equal = wp.window(intervals, 150)
    assert equal["feasible"] and equal["phi_lo_ps"] == equal["phi_hi_ps"] == -100
    assert wp.endpoint(0, 150)["margin_ps"] == 0
    assert wp.endpoint(150, 150)["margin_ps"] == 0


def test_card_validation():
    card = json.loads((ROOT / wp.INPUTS[0]).read_text())
    assert len(wp.validate(card)) == 12
    bad = copy.deepcopy(card); bad["units"] = "ns"
    with pytest.raises(ValueError): wp.validate(bad)
    bad = copy.deepcopy(card); bad["envelopes"].pop()
    with pytest.raises(ValueError): wp.validate(bad)
    bad = copy.deepcopy(card); bad["envelopes"][0]["tcq_min_ps"] = 9999
    with pytest.raises(ValueError): wp.validate(bad)


def test_measured_floating_point_boundary():
    card = json.loads((ROOT / wp.INPUTS[0]).read_text())
    intervals = [(r["clock_to_cml_min_ps"], r["clock_to_cml_max_ps"])
                 for r in wp.validate(card) if r["cell"] == "reset"]
    minimum = max(b for a, b in intervals) - min(a for a, b in intervals)
    boundary = wp.window(intervals, minimum)
    assert boundary["feasible"]
    assert boundary["phi_lo_ps"] == boundary["phi_hi_ps"]
    assert not wp.window(intervals, minimum - 1e-6)["feasible"]
