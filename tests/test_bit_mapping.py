"""bit_mapping separates eye health from bit order on stored TX runs.

Uses results on disk (not in git); skipped when absent.
"""
import json

import pytest

from serdes_flow import serial
from serdes_flow.project import ROOT
from serdes_flow.spice import Waves, has_waves

OPT = ROOT / "results/analog/tx/optimization/20261030T100258Z"
# r2 calibration grid (kept: pinned by clock_replay): start state (3, 1) = 500 MHz three VCO
# cycles and 1 GHz one cycle late against the word clock: clean eye, permuted bits.
GRID = ROOT / "results/analog/tx/serializer/clock_states/grid_20261030T184620Z"
SHIFTED = GRID / "tt_v1800_t27_s31/run"


def _seq(expected, shift_s=0.0):
    return serial.Sequence.from_expected(dict(expected, start_s=expected["start_s"] + shift_s))


@pytest.mark.skipif(not has_waves(OPT / "TX_tt_v1800_t27_s6_sf80_ck96_lowvt32_selected"), reason="campaign results not on disk")
def test_r2_run_is_in_order_and_matches_contract_eye():
    expected = json.loads((OPT / "serializer_expected.json").read_text())
    name = "TX_tt_v1800_t27_s6_sf80_ck96_lowvt32_selected"
    w = Waves(OPT / name / "waveforms.tsv")
    r = serial.bit_mapping(w.t, w["dout"], _seq(expected))
    stored = json.loads((OPT / name / "metrics.json").read_text())["nodes"]["serializer"]
    assert r["in_order"]
    # Same eye, measured without the training phase: within a few mV.
    assert r["eye_min_abs_v"] == pytest.approx(stored["minimum_signed_margin_v"], abs=5e-3)


@pytest.mark.skipif(not has_waves(SHIFTED), reason="calibration grid not on disk")
def test_wrong_divider_state_is_a_permutation():
    expected = json.loads((ROOT / "analog/tx/serializer/tb/clock_states/serializer_expected.json").read_text())
    w = Waves(SHIFTED / "waveforms.tsv")
    r = serial.bit_mapping(w.t, w["dout"], _seq(expected))
    assert r["mapping"] is not None and not r["in_order"]
    assert sorted(r["mapping"]) == list(range(16))
    assert r["eye_min_abs_v"] > 0.1
