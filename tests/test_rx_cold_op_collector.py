"""Collector validates evidence without relying on local simulation results."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rx_cold_op_plot', ROOT / 'verification/plotting/rx_cold_op.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    campaign = tmp_path / 'results/campaign'
    run = campaign / 'run'
    run.mkdir(parents=True)
    (campaign / 'prepared').mkdir()
    (campaign / 'plan.json').write_text('{}')
    deck = campaign / 'prepared/100ns.cir'
    deck.write_text('fixed deck')
    (run / 'tb.cir').write_text('fixed deck')
    (run / 'short.raw').write_bytes(b'waveform')
    (run / 'simulator.log').write_text('Transient op started\nTransient op finished successfully\n')
    ex = dict(deck_sha256=collector.sha(deck), exit_code=0, timed_out=False, log_failures=[], elapsed_s=2)
    (run / 'execution.json').write_text(json.dumps(ex))
    stages = dict(raw_complete=True, endpoints={'v(bias_vbg)': {'start': .669, 'end': .673}})
    row = dict(case='100ns', status='observed', spec_status='ungraded', run='results/campaign/run',
               stages=stages, execution_sha256=collector.sha(run / 'execution.json'), raw_sha256=collector.sha(run / 'short.raw'))
    summary = campaign / 'analysis/a/summary.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps(dict(scope='test', result=row)))
    runner = SimpleNamespace(verify=lambda p: {'snapshots': {}}, assess=lambda p: stages.copy())
    monkeypatch.setattr(collector.importlib, 'import_module', lambda name: runner)
    return campaign, run, summary, stages


def test_full_evidence_checked_and_raw_hash_recorded(evidence):
    _, run, summary, _ = evidence
    rows, inputs = collector.collect_full([('optran', summary)])
    assert rows[0]['result']['stages']['endpoints']['v(bias_vbg)']['end'] == .673
    assert inputs['results/campaign/run/short.raw'] == collector.sha(run / 'short.raw')


def test_full_rejects_stage_and_deck_changes(evidence):
    _, run, summary, stages = evidence
    stages['raw_complete'] = False
    with pytest.raises(ValueError, match='summary differs'):
        collector.collect_full([('optran', summary)])
    stages['raw_complete'] = True
    (run / 'tb.cir').write_text('changed deck')
    with pytest.raises(ValueError, match='identity mismatch'):
        collector.collect_full([('optran', summary)])


def test_full_rejects_changed_raw(evidence):
    _, run, summary, _ = evidence
    (run / 'short.raw').write_bytes(b'changed')
    with pytest.raises(ValueError, match='raw identity mismatch'):
        collector.collect_full([('optran', summary)])


def test_solver_route_retains_optran_and_incomplete_distinction():
    log = 'Starting dynamic gmin stepping\nDynamic gmin stepping failed\nStarting source stepping\nsource stepping failed\nTransient op started\nTransient op finished successfully\n'
    assert collector.solver_route(log, True) == 'optran_endpoint'
    assert collector.solver_route('Starting dynamic gmin stepping', False) == 'dynamic_gmin_incomplete'
    assert collector.solver_route('Starting source stepping\nSource stepping completed', True) == 'source_stepping'
    assert collector.solver_route('No. of Data Rows : 1', True) == 'direct'


def test_lane_measurement_and_route_are_verified(tmp_path, monkeypatch):
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    campaign = tmp_path / 'results/lane'
    run = campaign / 'lane_one'
    run.mkdir(parents=True)
    (campaign / 'prepared').mkdir()
    (campaign / 'plan.json').write_text('{}')
    deck = campaign / 'prepared/one.cir'
    deck.write_text('lane deck')
    (run / 'tb.cir').write_text('lane deck')
    (run / 'op.tsv').write_text('measured OP')
    (run / 'simulator.log').write_text('Starting source stepping\nSource stepping completed\n')
    ex = dict(deck_sha256=collector.sha(deck), exit_code=0, timed_out=False, log_failures=[], elapsed_s=2)
    (run / 'execution.json').write_text(json.dumps(ex))
    measured = {'voltages': {'vgi_bias': .977}, 'currents': {'idd': -.015}}
    row = dict(case='one', status='observed', run='results/lane/lane_one', stages=measured,
               execution_sha256=collector.sha(run / 'execution.json'), op_sha256=collector.sha(run / 'op.tsv'))
    summary = campaign / 'analysis/a/summary.json'
    summary.parent.mkdir(parents=True)
    summary.write_text(json.dumps(dict(scope='test', result=row)))
    lane = SimpleNamespace(verify=lambda p: dict(snapshots={}, source_hashes={}, reference_execution_hashes={}),
                           base=SimpleNamespace(read_op=lambda p, nodes: measured.copy()))
    monkeypatch.setattr(collector.importlib, 'import_module', lambda name: lane)
    rows, inputs = collector.collect_lanes([summary])
    assert rows[0]['solver_route'] == 'source_stepping'
    assert inputs['results/lane/lane_one/op.tsv'] == collector.sha(run / 'op.tsv')
    measured['voltages'] = {'vgi_bias': .8}
    with pytest.raises(ValueError, match='lane evidence mismatch'):
        collector.collect_lanes([summary])


def test_sparse_uses_op_raw_and_checks_hash(evidence):
    campaign, run, summary, _ = evidence
    (campaign / 'prepared/100ns.cir').rename(campaign / 'prepared/full_sparse_op.cir')
    (run / 'short.raw').rename(run / 'op.raw')
    rows, inputs = collector.collect_full([('sparse', summary)])
    assert rows[0]['solver_route'] == 'optran_endpoint'
    assert inputs['results/campaign/run/op.raw'] == collector.sha(run / 'op.raw')
    (run / 'op.raw').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='raw identity mismatch'):
        collector.collect_full([('sparse', summary)])


def test_direct_newton_must_not_use_fallback(evidence, monkeypatch):
    campaign, run, summary, stages = evidence
    (campaign / 'prepared/100ns.cir').rename(campaign / 'prepared/full_dc_newton.cir')
    (run / 'short.raw').rename(run / 'op.raw')
    (campaign / 'seed_nodes.json').write_text('[]')
    stages.update(direct_configured=True, optran_deselected=True, any_fallback=False)
    document = json.loads(summary.read_text())
    document['result'].update(status='observed_direct_newton', stages=stages.copy())
    summary.write_text(json.dumps(document))
    runner = SimpleNamespace(verify=lambda p: {'snapshots': {}}, assess=lambda p, nodes: stages.copy())
    monkeypatch.setattr(collector.importlib, 'import_module', lambda name: runner)
    assert collector.collect_full([('newton', summary)])[0][0]['result']['status'] == 'observed_direct_newton'
    stages['any_fallback'] = True
    document['result']['stages'] = stages.copy()
    summary.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='used a fallback'):
        collector.collect_full([('newton', summary)])
