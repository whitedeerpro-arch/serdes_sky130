"""Offline tests for complete and partial VCO fill curves."""
import importlib.util
import json
import sys
from pathlib import Path

from serdes_flow.corners import Condition

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('fill_codes_test', ROOT / 'analog/pll/vco/tb/tuning/fill_codes.py')
fill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fill)


def test_partial_codes_are_separate_and_preserve_measurements():
    c = Condition('ss', 1.65, 27)
    vs = fill.grid(c.supply)
    pts = [('tt', c, k, v) for k in (1, 2, 3) for v in vs]
    def lookup(rc, cond, code, v):
        return None if code == 2 and v == vs[-1] else (code, float(v))
    def measure(path):
        return None if path[0] == 3 and path[1] == vs[0] else (2e9 + path[1], .4)
    result = fill.collect(pts, lookup, measure)
    row = result['rows'][f'{c.tag}:tt']
    assert list(row['f']) == ['1']
    assert len(row['vs']) == len(row['f']['1']) == len(row['swing']['1'])
    partial = {r['code']: r for r in result['partial_rows']}
    assert partial[2]['missing_v'] == [vs[-1]]
    assert partial[2]['existing_v'] == vs[:-1]
    assert partial[2]['observations'][0]['f'] is not None
    assert partial[3]['observations'][0]['reason'] == 'measurement_failed'


def test_collect_only_preserves_plans_and_old_summary(tmp_path, monkeypatch):
    camp = tmp_path / 'campaign'
    camp.mkdir()
    old = {'plan.json': b'old plan\n', 'plan_missing.json': b'old missing\n', 'summary.json': b'old summary\n'}
    for name, data in old.items(): (camp / name).write_bytes(data)
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'summary.json').write_text('{}')
    c = Condition('ss', 1.65, 27)
    pts = [('tt', c, 1, v) for v in fill.grid(c.supply)]
    monkeypatch.setattr(fill, 'ROOT', tmp_path)
    monkeypatch.setattr(fill, 'plan', lambda _: pts)
    monkeypatch.setattr(fill, 'plan_missing', lambda _: pts)
    monkeypatch.setattr(fill.spice, 'case_output', lambda *args: None)
    monkeypatch.setattr(fill.spice, 'run_many', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('simulator called')))
    monkeypatch.setattr(sys, 'argv', ['fill_codes.py', '--from', 'source', '--resume', 'campaign', '--missing-only', '--collect-only'])
    fill.main()
    for name, data in old.items(): assert (camp / name).read_bytes() == data
    summaries = list((camp / 'analysis').glob('*/summary.json'))
    assert len(summaries) == 1
    result = json.loads(summaries[0].read_text())
    assert result['partial_rows'][0]['missing_v'] == fill.grid(c.supply)
    assert result['source_summary_sha256']
