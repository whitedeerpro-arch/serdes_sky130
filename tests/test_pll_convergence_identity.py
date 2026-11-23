"""A changed numerical experiment cannot inherit a complete old waveform."""
import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location("pll_convergence_probe", Path(__file__).resolve().parents[1] / "analog/pll/top/tb/convergence/probe.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


def test_resume_accepts_identical_inputs_but_rejects_changed_seed_source(tmp_path):
    path = tmp_path / "inputs/case.json"
    identity = dict(condition="ff_v1950_t-40", seed="prebiased", stop_s=24e-9, sources={"seed": "original"})
    PROBE.preserve_identity(path, identity)
    original = path.read_bytes()
    PROBE.preserve_identity(path, identity, prior_attempts=True)
    changed = dict(identity, sources={"seed": "changed"})
    with pytest.raises(ValueError, match="inputs changed"):
        PROBE.preserve_identity(path, changed, prior_attempts=True)
    assert path.read_bytes() == original


def test_resume_cannot_certify_a_legacy_run_retroactively(tmp_path):
    path = tmp_path / "inputs/case.json"
    with pytest.raises(ValueError, match="no input identity"):
        PROBE.preserve_identity(path, {"stop_s": 24e-9}, prior_attempts=True)
    assert not path.exists()


def test_changed_endpoint_requires_new_campaign(tmp_path):
    path = tmp_path / "inputs/case.json"
    PROBE.preserve_identity(path, {"stop_s": 24e-9})
    with pytest.raises(ValueError, match="inputs changed"):
        PROBE.preserve_identity(path, {"stop_s": 40e-9}, prior_attempts=True)
    assert json.loads(path.read_text()) == {"stop_s": 24e-9}
