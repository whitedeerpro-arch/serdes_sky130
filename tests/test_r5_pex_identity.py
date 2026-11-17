"""A legacy PEX run cannot silently inherit new includes or lose half its clock."""
import importlib.util
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from serdes_flow.project import ROOT

spec = importlib.util.spec_from_file_location(
    "r5_pex_identity", ROOT / "analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_legacy_execution_requires_a_new_campaign(tmp_path):
    (tmp_path / "execution.json").write_text("{}")
    with pytest.raises(ValueError, match="Legacy campaign"):
        bench.frozen_deck("old deck", tmp_path, "tt")


def test_changed_include_or_deck_cannot_reuse_a_case(tmp_path, monkeypatch):
    project = bench.freeze_includes.__globals__["project"]
    monkeypatch.setattr(project, "ROOT", tmp_path)
    source = tmp_path / "source.spice"
    source.write_text("R1 a b 100\n")
    campaign = tmp_path / "campaign"
    deck = f'.include "{source}"\ntran 2p 22n\n'
    frozen = bench.frozen_deck(deck, campaign, "tt")
    assert str(campaign / "inputs") in frozen
    assert bench.frozen_deck(deck, campaign, "tt") == frozen
    with pytest.raises(ValueError, match="inputs changed"):
        bench.frozen_deck(deck.replace("22n", "18n"), campaign, "tt")
    source.write_text("R1 a b 200\n")
    with pytest.raises(ValueError, match="Frozen include changed"):
        bench.frozen_deck(deck, campaign, "tt")


def test_logic_check_rejects_stopped_low_amplitude_and_missing_period():
    t = np.arange(0, 200e-9, 1e-12)
    signal = 0.9 + 0.9 * np.sin(2 * np.pi * 2e9 * t)
    assert bench.logic_metrics(t, signal, 1.8, 2e9, 12e-9)["ok"]
    assert not bench.logic_metrics(t, np.zeros_like(t), 1.8, 2e9, 12e-9)["ok"]
    assert not bench.logic_metrics(t, .9 + .05 * (signal - .9), 1.8, 2e9, 12e-9)["ok"]
    signal[(t >= 100e-9) & (t < 100.5e-9)] = 0
    result = bench.logic_metrics(t, signal, 1.8, 2e9, 12e-9)
    assert abs(result["freq_ghz"] / 2 - 1) < .01
    assert not result["ok"] and result["missing_or_extra_periods"] > 0


def test_rc_pair_accepts_capacitor_renumbering_but_rejects_changed_matrix(tmp_path, monkeypatch):
    review, installed = tmp_path / "review", tmp_path / "installed"
    review.mkdir(); installed.mkdir()
    monkeypatch.setattr(bench, "REV_DIR", review)
    monkeypatch.setattr(bench, "PEX_DIR", installed)
    cpex = installed / "candidate_pex.spice"
    rcx = review / "candidate_rcx.spice"
    monkeypatch.setattr(bench, "PEX_SPICE", cpex)
    monkeypatch.setattr(bench, "RCX_SPICE", rcx)
    rcx.write_text("R1 a b 1\n")
    (review / "rc_summary.json").write_text(json.dumps({
        "rcx_sha256": hashlib.sha256(rcx.read_bytes()).hexdigest(),
        "cpex_sha256": hashlib.sha256(b"C0 a b 1f\nC1 b c 2f\n").hexdigest()}))
    (review / "inputs.json").write_text("{}")
    (review / cpex.name).write_text("C0 a b 1f\nC1 b c 2f\n")
    cpex.write_text("C7 c b 2f\nC8 b a 1f\n")
    bench.validate_rc_source()
    cpex.write_text("C7 c b 2f\nC8 b a 10f\n")
    with pytest.raises(ValueError, match="CPEX changed"):
        bench.validate_rc_source()
