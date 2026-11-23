import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vco_recode_evidence', ROOT / 'verification/analysis/vco_recode_evidence.py')
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def test_feasible_interval_no_temperature_extrapolation():
    assert r.feasible_interval(.8, 1.4, .9, 1.2, 0, 60) == pytest.approx([10, 40])
    assert r.feasible_interval(.8, .85, .9, 1.2, 0, 60) is None
    with pytest.raises(ValueError): r.interp(1,2,61,0,60)


def test_startup_never_skips_missing_code():
    points = {15:{27:1.4}, 13:{27:1.0}}
    result = r.startup(points,27,.9,1.2)
    assert result['status'] == 'unknown_missing_evidence' and result['code'] == 14
    assert result['examined'][0]['code'] == 15


def test_adjacent_segment_missing_and_margin_shortfall():
    points = {8:{-40:1.0,27:1.3}, 7:{-40:.91}}
    row = next(x for x in r.segments(points,.9,1.2,.02) if x['code']==8 and x['temperature']==[-40,27])
    assert row['crossings'][0]['status']=='unknown_missing_evidence'
    points[7][27] = .91
    row = next(x for x in r.segments(points,.9,1.2,.02) if x['code']==8 and x['temperature']==[-40,27])
    assert row['crossings'][0]['status']=='margin_shortfall'
    assert row['crossings'][0]['opposite_edge_room_v']==pytest.approx(.01)


def test_profile_checks_both_segment_endpoints_and_switch_landing():
    points={15:{-40:1.1,27:1.3},14:{-40:1.0,27:1.1}}
    result=r.run_profile(points,-40,[-40,27],.9,1.2,.02)
    assert result['status']=='evidenced_under_model'
    assert result['events'][0]['old_code']==15 and result['events'][0]['new_code']==14
    del points[14][-40]
    assert r.run_profile(points,-40,[-40,27],.9,1.2,.02)['status']=='unknown_missing_evidence'


def test_negative_kvco_excluded_from_temperature_evidence():
    static = {'conditions': {}, 'fixed_three_temperature': {'tt_v1800:tt': {}},
              'source_path': 'source', 'source_sha256': 'abc', 'fill_path': 'fill', 'fill_sha256': 'def', 'partial_rows': []}
    for temp in (-40, 27, 85):
        static['conditions'][f'tt_v1800_t{temp}:tt'] = {'curves': {'7': {'crossings': [{'v': 1.1, 'kvco_hz_per_v': -1e9}]}}}
    result = r.analyse(static)
    assert len(result['excluded_crossings']) == 3
    assert all(x['reason'] == 'nonpositive_kvco' for x in result['excluded_crossings'])
    segment = next(x for x in result['chips']['tt_v1800:tt']['3']['segments'] if x['code'] == 7)
    assert segment['status'] == 'unknown_missing_evidence'
    assert result['source_path'] == 'source' and result['analyzer_sha256']
