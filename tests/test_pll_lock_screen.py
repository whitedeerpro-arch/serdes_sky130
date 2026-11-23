"""Engineering hold cannot be replaced by a few stationary nearest edges."""
import numpy as np
from serdes_flow import pll_lock


def test_static_phase_offset_passes_a_complete_sustained_record():
    ref=np.arange(2e-9,1e-6,4e-9)
    r=pll_lock.screen(ref,ref+50e-12,start=55e-9,stop=1e-6,period=4e-9)
    assert r['locked'] and r['hold_s']>=320e-9
    assert all(w['pairing_errors']==0 for w in r['windows'])


def test_short_phase_stationarity_cannot_satisfy_hold_time():
    ref=np.arange(2e-9,300e-9,4e-9)
    r=pll_lock.screen(ref,ref+50e-12,start=55e-9,stop=300e-9,period=4e-9)
    assert not r['locked'] and not r['assessed']


def test_missing_tail_and_double_frequency_never_lock():
    ref=np.arange(2e-9,1e-6,4e-9)
    for fb in ([],ref[:-10],np.arange(2e-9,1e-6,2e-9)):
        r=pll_lock.screen(ref,fb,start=55e-9,stop=1e-6,period=4e-9)
        assert r['assessed'] and not r['locked']


def test_late_phase_slip_resets_the_sustained_hold():
    ref=np.arange(2e-9,1e-6,4e-9)
    fb=ref+np.where(ref>850e-9,100e-12,0)
    r=pll_lock.screen(ref,fb,start=55e-9,stop=1e-6,period=4e-9)
    assert not r['locked'] and r['hold_s']<320e-9


def test_missing_reference_tail_cannot_reuse_an_earlier_good_hold():
    ref=np.arange(2e-9,600e-9,4e-9)
    r=pll_lock.screen(ref,ref+50e-12,start=55e-9,stop=1e-6,period=4e-9)
    assert r['assessed'] and not r['locked']
    assert r['status']=='missing_reference_tail'


def test_window_phase_span_catches_large_modulation_with_zero_mean_frequency():
    ref=np.arange(2e-9,1e-6,4e-9)
    fb=ref+30e-12*np.sin(2*np.pi*np.arange(len(ref))/32)
    r=pll_lock.screen(ref,fb,start=55e-9,stop=1e-6,period=4e-9)
    assert not r['locked']
    assert any(w['phase_span_s']>20e-12 for w in r['windows'])
