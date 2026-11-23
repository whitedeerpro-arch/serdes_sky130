import numpy as np
import pytest

from serdes_flow.loading import rising_edge_load


def test_linear_ramp_capacitance_and_slew_with_nonzero_low():
    t = np.linspace(0, 2e-9, 2001)
    v = .2+1.8*np.clip((t-.9e-9)/.1e-9, 0, 1)
    current = 175e-15*np.gradient(v, t)
    row, = rising_edge_load(t, v, current, .2, 2, .5e-9, 1.5e-9)
    assert row['slew_10_90_s'] == pytest.approx(80e-12)
    assert row['charge_equivalent_cap_f'] == pytest.approx(175e-15)
    # Sign is not silently hidden when the current probe is reversed.
    reverse, = rising_edge_load(t, v, -current, .2, 2, .5e-9, 1.5e-9)
    assert reverse['charge_equivalent_cap_f'] == pytest.approx(-175e-15)


def test_truncated_charge_window_is_rejected():
    t = np.linspace(0, 1e-9, 1001)
    v = np.clip((t-.7e-9)/.1e-9, 0, 1)
    with pytest.raises(ValueError, match='incomplete clock charge window'):
        rising_edge_load(t, v, np.zeros_like(t), 0, 1, .5e-9, 1e-9)
