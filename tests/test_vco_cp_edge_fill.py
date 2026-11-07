"""Offline tests of CP-edge campaign resume; ngspice is never invoked."""
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


TUNING = Path(__file__).resolve().parents[1] / 'analog/pll/vco/tb/tuning'
sys.path.insert(0, str(TUNING))
spec = importlib.util.spec_from_file_location('cp_edge_fill_test', TUNING / 'cp_edge_fill.py')
fill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fill)


def output(campaign, name, raw, stop):
    for directory in [campaign / f'{name}.r2', campaign / name]:
        path = directory / raw
        if path.exists() and path.read_text() != 'truncated':
            return path
    return None


def smoke_run(deck, directory, **kwargs):
    assert 'tran 2p 1.001e-9 0' in deck
    directory.mkdir()
    raw = re.search(r'write (\S+\.raw)', deck).group(1)
    (directory / raw).write_text('complete')
    return SimpleNamespace(ok=True, run_dir=directory)


def batch_run(jobs, workers, smoke):
    assert workers == 1 and not smoke
    result = []
    for deck, directory, options in jobs:
        assert options['timeout_s'] == 600 + 60 * len(options['meta']['cases'])
        directory.mkdir()
        (directory / 'tb.cir').write_text(deck)
        (directory / 'execution.json').write_text('{}')
        for case in options['meta']['cases']:
            (directory / case['raw']).write_text('complete')
        result.append(SimpleNamespace(ok=True, run_dir=directory, log_failures=[]))
    return result


def test_resume_only_missing_and_invalid_measurements(tmp_path):
    camp = tmp_path / 'campaign'
    manifest = fill.prepare(camp)
    name = 'ff_tt'
    cases = manifest['cases'][name]
    existing = camp / name
    existing.mkdir()
    (existing / cases[0]['raw']).write_text('complete')
    (existing / cases[1]['raw']).write_text('truncated')
    (existing / 'tb.cir').write_text('original deck')
    (existing / 'execution.json').write_text('{}')
    captured = []

    def batch(jobs, workers, smoke):
        captured.extend(jobs)
        return batch_run(jobs, workers, smoke)

    def measure(path):
        if '_v850.' in path.name:
            return None
        if '_v1500.' in path.name:
            return float('nan'), 0.4
        return 2e9, 0.4

    with patch.object(fill.spice, 'case_output', side_effect=output), \
         patch.object(fill.spice, 'run', side_effect=smoke_run), \
         patch.object(fill.spice, 'run_many', side_effect=batch), \
         patch.object(fill.workmap, 'measure', side_effect=measure):
        fill.resume(camp)
        ff_job = next(job for job in captured if job[1].name == 'ff_tt.r2')
        assert [x['raw'] for x in ff_job[2]['meta']['cases']] == [x['raw'] for x in cases[1:]]
        assert cases[0]['raw'] not in ff_job[0]
        report = json.loads(next(camp.glob('report_*.json')).read_text())
        assert report['analysis_source_sha256']
        for row in report['rows'].values():
            assert not row['complete']
            assert all(s['raw_sha256'] and s['execution_sha256'] and s['deck_sha256'] for s in row['samples'])
        assert report['rows'][name]['samples'][0]['frequency_hz'] is None
        assert report['rows'][name]['samples'][1]['frequency_hz'] is None


def test_truncated_smoke_aborts_before_batch(tmp_path):
    camp = tmp_path / 'campaign'
    fill.prepare(camp)

    def truncated_smoke(deck, directory, **kwargs):
        directory.mkdir()
        raw = re.search(r'write (\S+\.raw)', deck).group(1)
        (directory / raw).write_text('truncated')
        return SimpleNamespace(ok=True, run_dir=directory)

    with patch.object(fill.spice, 'case_output', side_effect=output) as case_output, \
         patch.object(fill.spice, 'run', side_effect=truncated_smoke), \
         patch.object(fill.spice, 'run_many') as batch:
        with pytest.raises(RuntimeError, match='smoke failed'):
            fill.resume(camp)
        batch.assert_not_called()
        assert case_output.call_args.args[3] == 1.001e-9
