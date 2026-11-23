"""Offline checks for four-bit ISF calibration and resume gates."""
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('isf_4b_pilot', ROOT / 'analog/pll/vco/tb/phase_noise/isf_4b_pilot.py')
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


def test_four_bit_deck_and_isf_site(tmp_path):
    deck, _ = pilot.make_deck(tmp_path)
    assert 'vco_ring4_pvt_candidate' not in deck
    main = next(line for line in deck.splitlines() if line.startswith('Xvco '))
    assert main.endswith('cfg0 cfg1 cfg2 cfg3 vbias vdd 0 pll_vco_ring4_4b capw=2.35 capl=2.5 sw=2.5')
    assert 'Vb3 cfg3 0 0' in deck and 'Vb1 cfg1 0 1.8' in deck and 'Vb2 cfg2 0 1.8' in deck
    includes = [Path(p) for p in re.findall(r'^\.include\s+"([^"]+)"', deck, re.M)]
    all_text = '\n'.join(p.read_text() for p in includes)
    definitions = set(re.findall(r'^\.subckt\s+(\S+)', all_text, re.I | re.M))
    ring = next(p.read_text() for p in includes if p.name == 'vco_ring4_4b.spice')
    bank = next(p.read_text() for p in includes if p.name == 'cap_bank_4b.spice')
    assert {'pll_vco_ring4_4b', 'pll_vco_cap_bank4', 'pll_vco_cap_unit'} <= definitions
    assert 'capw=2.35 capl=2.5 sw=2.5' in main
    units = re.findall(r'^X\S+\s+\S+\s+(b[0-3])\s+\S+\s+(pll_vco_cap_unit)\b', bank, re.M)
    assert [sum(bit == f'b{i}' for bit, _ in units) for i in range(4)] == [1, 2, 4, 8]
    assert all(cell in definitions for _, cell in units)
    assert len(re.findall(r'^Xc\d[ np]?', ring, re.M)) >= 8
    assert deck.count(' 30f') == 8
    site, centres, stop = pilot.site_deck(deck, 'mp', 1.195, .5e-9)
    assert 'write mp.raw' in site and '@m.xvco.x0.xmp.' in site and len(centres) == 33
    assert centres[0] >= 14e-9 and stop > centres[-1]


def test_calibration_requires_measured_bracket():
    with pytest.raises(ValueError, match='do not bracket'):
        pilot.bracket_candidate([(1.17, 1.8e9), (1.22, 1.9e9)])
    assert 1.17 < pilot.bracket_candidate([(1.17, 1.9e9), (1.22, 2.1e9)]) < 1.22
    with pytest.raises(ValueError, match='outside'):
        pilot.voltage_deck('Vctrl ctrl 0 1.195', 1.4)


def test_phase_gap_covers_wraparound_and_bad_data():
    assert pilot.phase_gap(np.arange(32) / 32) < .08
    assert pilot.phase_gap([.2, .21, .22]) > .08
    assert pilot.phase_gap([float('nan'), .5]) is None


def test_completed_rejects_truncated_waveform(tmp_path, monkeypatch):
    run = tmp_path / 'rp'
    run.mkdir()
    deck = 'test deck'
    (run / 'tb.cir').write_text(deck)
    (run / 'execution.json').write_text(json.dumps(dict(exit_code=0, timed_out=False, log_failures=[],
        deck_sha256=pilot.hashlib.sha256(deck.encode()).hexdigest(), pdk_installation_id=pilot.project.pdk_installation_id())))
    class Wave:
        def __init__(self, end, value=1.):
            self.t = np.array([0., end])
            self.values = {'v(v0p)': np.array([0., value])}
        def __contains__(self, key): return key in self.values
        def __getitem__(self, key): return self.values[key]
    monkeypatch.setattr(pilot.spice, 'Waves', lambda path: Wave(9e-9))
    assert pilot.completed(tmp_path, 'rp', deck, 'rp.raw', 10e-9, ['v(v0p)']) is None
    monkeypatch.setattr(pilot.spice, 'Waves', lambda path: Wave(10e-9))
    assert pilot.completed(tmp_path, 'rp', deck, 'rp.raw', 10e-9, ['v(v0p)'])[0] == run
    (run / 'tb.cir').write_text('changed')
    assert pilot.completed(tmp_path, 'rp', deck, 'rp.raw', 10e-9, ['v(v0p)']) is None


def test_missing_or_nonfinite_vectors_fail(tmp_path, monkeypatch):
    run = tmp_path / 'rp'
    run.mkdir()
    deck = 'deck'
    (run / 'tb.cir').write_text(deck)
    (run / 'execution.json').write_text(json.dumps(dict(exit_code=0, timed_out=False, log_failures=[],
        deck_sha256=pilot.hashlib.sha256(deck.encode()).hexdigest(), pdk_installation_id=pilot.project.pdk_installation_id())))
    class Wave:
        t = np.array([0., 10e-9])
        def __contains__(self, key): return key == 'v(v0p)'
        def __getitem__(self, key): return np.array([0., np.nan])
    monkeypatch.setattr(pilot.spice, 'Waves', lambda path: Wave())
    assert pilot.completed(tmp_path, 'rp', deck, 'rp.raw', 10e-9, ['v(v0p)']) is None
    assert pilot.completed(tmp_path, 'rp', deck, 'rp.raw', 10e-9, ['v(v0n)']) is None


def test_same_campaign_live_process_blocks_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(pilot, 'check', lambda camp: {})
    monkeypatch.setattr(pilot.watch, 'ngspice_cwds', lambda: {tmp_path / 'rp'})
    with pytest.raises(RuntimeError, match='already active'):
        pilot.ensure(tmp_path, 'rp', 'deck', 'rp.raw', 1e-9, 10, [])
