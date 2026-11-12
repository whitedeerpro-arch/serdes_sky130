"""Offline classification of strict r6 waveform measurement."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('r6_audit_test',ROOT/'verification/analysis/r6_map_wave_audit.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)


def test_cycle_threshold_and_drift_behavior():
    t=np.linspace(0,5e-9,10001)
    slow=a.metrics(t,np.sin(2*np.pi*0.9e9*t),start=0)
    assert slow['rising_edges'] in (4,5) and slow['status']=='4_or_5_edges_reader_skips' and slow['frequency_hz']>0
    settled=a.metrics(t,np.sin(2*np.pi*2e9*t),start=0)
    assert settled['qualified_window'] and settled['reader_returns_number']
    chirp=a.metrics(t,np.sin(2*np.pi*(1.5e9*t+0.5*1e17*t*t)),start=0)
    assert chirp['status']=='unsettled_reader_returns_number' and chirp['frequency_hz']>0
    with pytest.raises(ValueError):a.metrics(t,np.full_like(t,np.nan),start=0)


def test_actual_library_section_aliases(tmp_path):
    from serdes_flow.corners import Condition
    c=Condition.parse('tt_v1650_t-40');name='tt_v1650_t-40_c0_v900.raw'
    lines=['.lib "/models/sky130.lib.spice" hh','option temp=-40','alter Vdd dc=1.65','alter Vref dc=1.65']
    lines += [f'alter Vb{k} dc=0' for k in range(5)]
    lines += ['alter Vctrl dc=0.9','tran 4p 1.4000e-08 8.0000e-09',f'write {name} v(v0p) v(v0n)']
    d=tmp_path/'tb.cir';d.write_text('\n'.join(lines)+'\n')
    assert a.deck_point(d,name,c,'hh',0,.9)
    with pytest.raises(ValueError):a.deck_point(d,name,c,'ll',0,.9)
