import numpy as np
import pytest
from serdes_flow import spectral


def test_adaptive_grid_and_linear_drift_do_not_bias_a_tone():
    rng=np.random.default_rng(7)
    t=np.r_[0.,np.sort(rng.uniform(0,100e-9,4000)),100e-9]
    expected=.003-.007j
    y=2+.3*t/100e-9+np.real(expected*np.exp(2j*np.pi*50e6*(t-11e-9)))
    got=spectral.tone(t,y,50e6,11e-9,91e-9)
    # Exact-window endpoints are linearly interpolated on the adaptive grid.
    assert abs(got['phasor']-expected)<1e-8


def test_tone_rejects_uncovered_and_nonfinite_waveforms():
    t=np.linspace(0,1e-7,100)
    with pytest.raises(ValueError):spectral.tone(t,t,50e6,0,2e-7)
    y=t.copy();y[50]=np.nan
    with pytest.raises(ValueError):spectral.tone(t,y,50e6,0,1e-7)
