import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('vco_window_publication', ROOT / 'verification/plotting/vco_control_windows.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def test_interpolated_inside_does_not_prove_bracket_inside():
    row = {'curves': {'1': {'crossings': [{'v': 1.0, 'kvco_hz_per_v': 1e9, 'bracket_v': [.85, 1.1]}]}},
           'windows': {h: dict(vlo=.90, vhi=1.21, candidates=[1]) for h in p.model.DROPS}}
    result = p.bracket_containment({'conditions': {'x': row}})
    assert result['4']['conditions_with_whole_bracket'] == 0
    assert result['4']['needs_boundary_confirmation'] == 1
    row['curves']['1']['crossings'][0]['bracket_v'] = [.90, 1.1]
    result = p.bracket_containment({'conditions': {'x': row}})
    assert result['4']['conditions']['x']['whole_bracket_codes'] == [1]
