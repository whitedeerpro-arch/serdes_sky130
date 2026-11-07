"""Identity and waveform-window regressions for the fixed-code coverage audit."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'verification/plotting/vco_cp_edge_fill.py'
spec = importlib.util.spec_from_file_location('vco_fill_collector_test', SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def test_physical_comparison_keeps_load_and_cell_identity(tmp_path):
    cell = tmp_path / 'cell.spice'
    cell.write_text('Rload a b 300\n')
    deck = tmp_path / 'tb.cir'
    text = f'.include "{cell}"\nVdd vdd 0 1.65\nVref ref 0 1.65\n.temp -40\nCload a 0 30f\n.control\nquit\n.endc\n'
    deck.write_text(text)
    original = collector.physical_identity(deck)['core_sha256']
    deck.write_text(text.replace('1.65', '1.95').replace('.temp -40', '.temp 85'))
    assert collector.physical_identity(deck)['core_sha256'] == original
    cell.write_text('Rload a b 200\n')
    assert collector.physical_identity(deck)['core_sha256'] != original
    cell.write_text('Rload a b 300\n')
    deck.write_text(text.replace('30f', '40f'))
    assert collector.physical_identity(deck)['core_sha256'] != original


def test_first_saved_step_tolerance_does_not_allow_missing_window(tmp_path, monkeypatch):
    deck = tmp_path / 'tb.cir'; deck.write_text('test deck\n')
    (tmp_path / 'execution.json').write_text(json.dumps(dict(exit_code=0, timed_out=False, deck_sha256=collector.sha(deck))))
    raw = tmp_path / 'test.raw'; raw.write_bytes(b'placeholder')
    monkeypatch.setattr(collector, 'ROOT', tmp_path)
    monkeypatch.setattr(collector.workmap, 'measure', lambda _: (2e9, .4))
    monkeypatch.setattr(collector.spice, 'Waves', lambda _: SimpleNamespace(t=np.array([19e-9 + .56e-12, 24e-9])))
    assert collector.verify_raw(raw)['frequency_hz'] == 2e9
    monkeypatch.setattr(collector.spice, 'Waves', lambda _: SimpleNamespace(t=np.array([19e-9 + 20e-12, 24e-9])))
    with pytest.raises(ValueError, match='missing measurement window'):
        collector.verify_raw(raw)


def test_no_crossing_inferred_across_missing_voltage_point():
    pts = [dict(vctrl_v=.85,status='measured',frequency_hz=1.9e9),
           dict(vctrl_v=1.1,status='missing'),
           dict(vctrl_v=1.35,status='measured',frequency_hz=2.1e9)]
    assert collector.brackets(pts,1.6) == []
