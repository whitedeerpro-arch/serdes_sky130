"""Offline checks for the steering CP DC collector; no simulator is invoked."""
import importlib.util
from pathlib import Path
import re

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / 'analog/pll/cp/tb/dc/window_steer.py'
spec = importlib.util.spec_from_file_location('cp_steer_window', RUNNER)
window = importlib.util.module_from_spec(spec)
spec.loader.exec_module(window)


def sweep():
    v = np.arange(166) * .01 + .1  # VDD=1.8, inclusive 0.1..1.75 V
    # Realistic source/sink signs, different mid currents and slopes.
    up = 200e-6 * (1 - .198 * (v - .9))
    dn = -180e-6 * (1 - .10 * (v - .9))
    return v, up, dn


def write_wave(path, v, up, dn):
    np.savetxt(path, np.column_stack((v, up, dn)), header='v(sweep) i(eu) i(ed)', comments='')
    return path


def test_window_and_independent_droops(tmp_path):
    v, up, dn = sweep()
    result = window.measure(write_wave(tmp_path / 'sweep.tsv', v, up, dn), 1.8, .05)
    assert result['up'] == pytest.approx(200e-6)
    assert result['dn'] == pytest.approx(180e-6)
    assert result['mismatch'] == pytest.approx(20 / 190)
    # Both currents individually within 5% of their own midpoint, not matched to each other.
    assert result['lo'] == pytest.approx(.65)
    assert result['hi'] == pytest.approx(1.15)
    for d in window.DROPS:
        point = 1.8 - d
        assert v[0] <= point <= v[-1]  # no interpolation outside the sweep
        assert result['droop_at'][f'{d:.2f}']['up'] == pytest.approx(.198 * (point - .9))
        assert result['droop_at'][f'{d:.2f}']['dn'] == pytest.approx(.10 * (point - .9))


@pytest.mark.parametrize('fault', ['truncated', 'missing_middle', 'nonfinite', 'zero_up', 'zero_dn'])
def test_invalid_sweep_is_rejected(tmp_path, fault):
    v, up, dn = sweep()
    if fault == 'truncated':
        v, up, dn = v[:-1], up[:-1], dn[:-1]
    elif fault == 'missing_middle':
        v, up, dn = np.delete(v, 30), np.delete(up, 30), np.delete(dn, 30)
    elif fault == 'nonfinite':
        up[30] = np.nan
    elif fault == 'zero_up':
        up[80] = 0
    else:
        dn[80] = 0
    with pytest.raises(ValueError):
        window.measure(write_wave(tmp_path / 'bad.tsv', v, up, dn), 1.8, .05)


def test_cp_parameters_match_actual_core():
    text = (ROOT / 'analog/pll/top/spice/pll_core_r5k4.spice').read_text()
    match = re.search(r'^Xcp\s+[^\n]*\bpll_cp_steer\s+([^\n]*)\n\+\s*([^\n]*)', text, re.M | re.I)
    assert match, 'expected steering CP instance and continuation'
    parse = lambda s: dict(re.findall(r'(\w+)\s*=\s*([^\s]+)', s))
    assert parse(window.CP_PARAMS) == parse(' '.join(match.groups()))


@pytest.mark.parametrize('reverse', ['up', 'dn'])
def test_published_collection_rejects_reversed_midpoint(tmp_path, reverse):
    spec = importlib.util.spec_from_file_location('cp_publish', ROOT / 'verification/plotting/pll_cp_steer_window.py')
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    v, up, dn = sweep()
    publish.require_polarity(write_wave(tmp_path / 'good.tsv', v, up, dn), 1.8)
    path = write_wave(tmp_path / 'reversed.tsv', v, -up if reverse == 'up' else up, -dn if reverse == 'dn' else dn)
    with pytest.raises(ValueError):
        publish.require_polarity(path, 1.8)
