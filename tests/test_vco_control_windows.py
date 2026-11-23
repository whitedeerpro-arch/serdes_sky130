import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vco_control_windows', ROOT / 'verification/analysis/vco_control_windows.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def test_crossing_uses_only_brackets_and_secant():
    data = w.curve([.8, 1.0, 1.2], [1.7e9, 1.9e9, 2.3e9], [.4, .4, .4], 'x')
    x = w.crossings(data)
    assert len(x) == 1
    assert x[0]['v'] == pytest.approx(1.05)
    assert x[0]['kvco_hz_per_v'] == pytest.approx(2e9)
    assert x[0]['bracket_v'] == [1.0, 1.2]
    assert not w.crossings(w.curve([.8, 1.0], [1.7e9, 1.9e9], [.4, .4], 'x'))


@pytest.mark.parametrize('vs,f,swing', [([.8, 1.0], [1, 2], [.4]), ([.8, 1.0], [1, float('nan')], [.4, .4]), ([1., .8], [1, 2], [.4, .4])])
def test_invalid_curves_rejected(vs, f, swing):
    with pytest.raises(ValueError): w.curve(vs, f, swing, 'x')


def test_fill_preferred_and_duplicate_not_averaged():
    key = 'tt_v1800_t27:tt'
    source = {'vs': [.85, 1.1, 1.35], 'rows': {key: {'f': {'1': [1.8e9, 2e9, 2.2e9]}, 'swing': {'1': [.4]*3}}}}
    fill = {'source_summary_sha256': 'src', 'partial_rows': [{'example': 'retained'}], 'rows': {key: {'vs': [.8, 1.1, 1.4], 'f': {'1': [1.5e9, 1.9e9, 2.2e9]}, 'swing': {'1': [.4]*3}}}}
    r = w.analyse(source, fill, 'src', 'fill', 'source', 'fill')
    assert r['fill_partial'] and r['partial_rows'] == fill['partial_rows']
    duplicate = r['duplicate_observations'][0]
    assert duplicate['voltage'] == 1.1 and duplicate['fill_minus_source_hz'] == -1e8
    chosen = r['conditions'][key]['curves']['1']
    assert chosen['origin'] == 'fill'
    assert chosen['crossings'][0]['v'] == pytest.approx(1.2)
    assert len(r['conditions']) == 135 and len(r['fixed_three_temperature']) == 45
    assert r['fixed_three_temperature']['tt_v1800:tt']['3']['status'] == 'no_evidenced_code'
    with pytest.raises(ValueError): w.analyse(source, fill, 'wrong', 'fill', 'source', 'fill')


def test_negative_slope_is_retained_but_not_a_pll_candidate():
    key = 'tt_v1800_t27:tt'
    source = {'vs': [.85, 1.1, 1.35], 'rows': {key: {'f': {'1': [2.2e9, 2e9, 1.8e9]}, 'swing': {'1': [.4]*3}}}}
    fill = {'source_summary_sha256': 'src', 'partial_rows': [], 'rows': {}}
    r = w.analyse(source, fill, 'src', 'fill', 'source', 'fill')
    row = r['conditions'][key]
    assert row['curves']['1']['crossings'][0]['kvco_hz_per_v'] < 0
    assert not row['windows']['3']['candidates']
