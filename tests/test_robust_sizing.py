import numpy as np
import pytest
from serdes_flow.robust_sizing import pareto_mask, power_widths


def test_discrete_unsupported_pareto_point_survives():
    # The middle point cannot minimize a positive weighted sum, but is Pareto.
    assert pareto_mask([[0, 2], [1, 1.5], [2, 0], [2, 2]]).tolist() == [True, True, True, False]


def test_equal_points_do_not_dominate_each_other():
    assert pareto_mask([[1, 1], [1, 1], [1, 2]]).tolist() == [True, True, False]


def test_size_law_and_active_floor():
    assert np.allclose(power_widths(31), [1, 2, 4, 8, 16])
    assert np.allclose(power_widths(31.5, floors_um=[1.5, 0, 0, 0, 0]), [1.5, 2, 4, 8, 16])
    assert np.allclose(power_widths(10, alpha=0), [2]*5)
    assert np.allclose(power_widths(5, floors_um=[1]*5), [1]*5)


def test_smaller_exponent_protects_small_bits_at_same_budget():
    w = power_widths(31, alpha=.8)
    assert np.isclose(sum(w), 31)
    assert w[0] > 1 and w[-1] < 16


def test_invalid_inputs_are_rejected():
    with pytest.raises(ValueError):
        power_widths(1, floors_um=[1]*5)
    with pytest.raises(ValueError):
        pareto_mask([[1, float('nan')]])
