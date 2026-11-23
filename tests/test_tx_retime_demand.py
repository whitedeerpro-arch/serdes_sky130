"""Fault-oriented tests of demand-card case recovery; no simulator needed."""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'tx_retime_demand_runner', ROOT / 'analog/tx/input_register/tb/retime_demand/run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

TAG = 'fs_v1650_t85'
POINT = 'baseline'
DECK = '* fixed test deck\n.end\n'
ENTRY = {'id': 'test-boundary', 'points': {TAG: {'stop_s': 1e-9}}}


def write_raw(path, end=1e-9):
    """Write a real ngspice-compatible binary raw with two finite samples."""
    header = ('Title: synthetic\nPlotname: Transient Analysis\nFlags: real\n'
              'No. Variables: 2\nNo. Points: 2\nVariables:\n'
              '\t0\ttime\ttime\n\t1\tv(out)\tvoltage\nBinary:\n')
    points = np.asarray([[0., 0.], [end, 1.]], dtype='<f8')
    path.write_bytes(header.encode('ascii') + points.tobytes())


def attempt(camp, suffix='', *, end=1e-9, execution=True, **overrides):
    run = camp / (f'{TAG}_{POINT}' + suffix)
    run.mkdir()
    write_raw(run / f'{POINT}.raw', end)
    (run / 'tb.cir').write_text(DECK)
    ex = {'exit_code': 0, 'timed_out': False, 'log_failures': [],
          'condition': TAG, 'point_ids': [POINT], 'boundary_id': ENTRY['id'],
          'deck_sha256': hashlib.sha256(DECK.encode()).hexdigest()}
    ex.update(overrides)
    if execution:
        (run / 'execution.json').write_text(json.dumps(ex))
    return run


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'render', lambda camp, tag, ids: DECK)
    return tmp_path


def test_interrupted_latest_attempt_falls_back_to_completed_older(campaign):
    older = attempt(campaign)
    attempt(campaign, '.r2', execution=False)
    assert runner.completed(campaign, TAG, POINT, ENTRY) == older / f'{POINT}.raw'


@pytest.mark.parametrize('fault', ['failed', 'short', 'corrupt'])
def test_failed_or_incomplete_newest_falls_back(campaign, fault):
    older = attempt(campaign)
    kwargs = {'exit_code': 1, 'log_failures': ['failure']} if fault == 'failed' else {}
    newer = attempt(campaign, '.r2', end=0.5e-9 if fault == 'short' else 1e-9, **kwargs)
    if fault == 'corrupt':
        (newer / f'{POINT}.raw').write_bytes(b'incomplete raw file')
    assert runner.completed(campaign, TAG, POINT, ENTRY) == older / f'{POINT}.raw'


def test_no_valid_attempt_returns_none(campaign):
    assert runner.completed(campaign, TAG, POINT, ENTRY) is None
    attempt(campaign, execution=False)
    attempt(campaign, '.r2', timed_out=True, exit_code=None)
    attempt(campaign, '.r3', end=0.5e-9)
    assert runner.completed(campaign, TAG, POINT, ENTRY) is None


@pytest.mark.parametrize('fault', ['condition', 'point', 'boundary', 'declared_hash', 'actual_deck'])
def test_completed_with_broken_identity_is_rejected(campaign, fault):
    # A valid older run must not hide a corrupt identity on a purportedly
    # successful newer run.
    attempt(campaign)
    changes = {'condition': {'condition': 'tt_v1800_t27'},
               'point': {'point_ids': ['late20']},
               'boundary': {'boundary_id': 'another-boundary'},
               'declared_hash': {'deck_sha256': '0' * 64},
               'actual_deck': {}}[fault]
    newer = attempt(campaign, '.r2', **changes)
    if fault == 'actual_deck':
        (newer / 'tb.cir').write_text('tampered deck\n')
    with pytest.raises(ValueError, match='identity|deck'):
        runner.completed(campaign, TAG, POINT, ENTRY)
