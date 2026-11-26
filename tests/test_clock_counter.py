import numpy as np
import pytest

from serdes_flow.clock import binary_counter


@pytest.mark.parametrize("delay", [60e-12, 101e-12, 180e-12])
def test_counter_samples_after_clk_to_q(delay):
    t = np.arange(0, 12e-9, 1e-12)
    edges = np.arange(0, 12e-9, 500e-12)
    state = np.floor((t - delay) / 500e-12).astype(int) % 8
    bits = [2.0 * ((state >> i) & 1) - 1 for i in range(3)]
    got = binary_counter(t, bits, edges, edges[2], edges[22])
    assert got["counting"]
    assert got["samples"] == 20


def test_counter_does_not_hide_a_missed_step():
    t = np.arange(0, 24e-9, 1e-12)
    edges = np.arange(0, 24e-9, 500e-12)
    state = np.floor((t - 150e-12) / 500e-12).astype(int)
    state -= state >= 10  # one missed increment, followed by correct increments
    bits = [2.0 * ((state >> i) & 1) - 1 for i in range(3)]
    got = binary_counter(t, bits, edges, 1e-9, 23e-9)
    assert not got["counting"]
    assert len(got["invalid_steps"]) == 1


def test_missing_clock_is_not_counting():
    got = binary_counter([0, 1], [[1, 1]] * 3, [], 0, 1)
    assert not got["counting"]
    assert got["samples"] == 0
