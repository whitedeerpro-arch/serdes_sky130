"""bit_mapping separates eye health from bit order on stored TX runs.

Uses results on disk (not in git); skipped when absent.
"""
import json

import pytest

from serdes_flow import serial
from serdes_flow.project import ROOT
from serdes_flow.spice import Waves

OPT = ROOT / "results/analog/tx/optimization/20261030T100258Z"
# Single-chain exploration, 500 MHz one VCO cycle off: clean eye, permuted bits.
SHIFTED = sorted((ROOT / "results/analog/tx/clock_distribution/single_chain").glob("tx_f_*"))


def _seq(expected, shift_s=0.0):
    return serial.Sequence.from_expected(dict(expected, start_s=expected["start_s"] + shift_s))


@pytest.mark.skipif(not OPT.exists(), reason="campaign results not on disk")
def test_r2_run_is_in_order_and_matches_contract_eye():
    expected = json.loads((OPT / "serializer_expected.json").read_text())
    name = "TX_tt_v1800_t27_s6_sf80_ck96_lowvt32_selected"
    w = Waves(OPT / name / "waveforms.tsv")
    r = serial.bit_mapping(w.t, w["dout"], _seq(expected))
    stored = json.loads((OPT / name / "metrics.json").read_text())["nodes"]["serializer"]
    assert r["in_order"]
    # Same eye, measured without the training phase: within a few mV.
    assert r["eye_min_abs_v"] == pytest.approx(stored["minimum_signed_margin_v"], abs=5e-3)


@pytest.mark.skipif(not SHIFTED, reason="exploration results not on disk")
def test_wrong_divider_state_is_a_permutation():
    camp = SHIFTED[-1]
    rows = {r["name"]: r for r in json.loads((camp / "summary.json").read_text())}
    expected = json.loads((ROOT / "analog/tx/clock_distribution/tb/single_chain/serializer_expected.json").read_text())
    w = Waves(camp / "tt_00/run/waveforms.tsv")
    r = serial.bit_mapping(w.t, w["dout"], _seq(expected, rows["tt_00"]["data_shift_ps"] * 1e-12))
    assert r["mapping"] is not None and not r["in_order"]
    assert r["eye_min_abs_v"] > 0.1
