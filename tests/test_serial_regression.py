"""serdes_flow.serial must reproduce the TX campaign metrics exactly.

Uses existing TX r2 runs on disk (results/ is not in git); skips if absent.
"""
import json
from pathlib import Path

import pytest

from serdes_flow import serial
from serdes_flow.project import ROOT
from serdes_flow.spice import Waves

CAMPAIGN = ROOT / "results/analog/tx/optimization/20261030T100258Z"
NODES = {"serializer": "dout", "pad": "line_tx", "far": "line_rx"}
RUNS = [
    ("TX_fs_v1650_t85_s6_sf80_ck96_lowvt32_selected", 128),
    ("TX_ss_v1650_t-40_s6_sf80_ck96_lowvt32_selected", 128),
    ("TX_fs_v1650_t85_s6_sf80_ck96_lowvt32_selected_long1024", 1024),
]


@pytest.mark.skipif(not CAMPAIGN.exists(), reason="campaign results not on disk")
@pytest.mark.parametrize("name,payload", RUNS)
def test_matches_campaign_metrics(name, payload):
    seq = serial.Sequence.from_expected(json.loads((CAMPAIGN / "serializer_expected.json").read_text()))
    stored = json.loads((CAMPAIGN / name / "metrics.json").read_text())["nodes"]
    w = Waves(CAMPAIGN / name / "waveforms.tsv")
    for node, vec in NODES.items():
        got, _ = serial.check(w.t, w[vec], seq, payload)
        for key, want in stored[node].items():
            assert got[key] == pytest.approx(want, rel=1e-12, abs=1e-15), (node, key)
