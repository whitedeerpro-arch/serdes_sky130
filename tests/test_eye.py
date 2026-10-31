import numpy as np
import pytest

from serdes_flow import eye

UI = 250e-12


def test_prbs7_period_and_balance():
    b = eye.prbs7(254)
    assert b[:127] == b[127:]
    assert sum(b[:127]) == 64


def _rc_response(bits, tau, delay, amp=0.2):
    t = np.arange(0, (len(bits) + 20) * UI, 1e-12)
    pts = eye.nrz_pwl(bits, UI, 0.0, 20e-12, -amp, amp)
    x = np.interp(t, [p[0] for p in pts], [p[1] for p in pts])
    y = np.zeros_like(x)
    a = 1e-12 / tau
    for i in range(1, len(t)):
        y[i] = y[i - 1] + a * (x[i - 1] - y[i - 1])
    shift = int(round(delay / 1e-12))
    return t, np.r_[np.full(shift, y[0]), y[:-shift]]


def test_signed_eye_finds_latency_and_opening():
    bits = eye.prbs7(167)
    t, y = _rc_response(bits, tau=40e-12, delay=600e-12)
    e = eye.signed_eye(t, y, bits, UI, 0.0, first_bit=40)
    assert e["height_v"] > 0.12
    assert 0.6 < e["width_ui"] <= 1.0
    assert 600e-12 <= e["latency_s"] <= 600e-12 + UI / 2       # best sampling point lags the delay (RC settling)


def test_slow_channel_closes_and_inverted_is_negative():
    bits = eye.prbs7(167)
    t, y = _rc_response(bits, tau=400e-12, delay=100e-12)
    assert eye.signed_eye(t, y, bits, UI, 0.0, first_bit=40)["height_v"] < 0.05
    t, y = _rc_response(bits, tau=40e-12, delay=100e-12)
    assert eye.signed_eye(t, -y, bits, UI, 0.0, first_bit=40, max_latency=2e-9)["height_v"] < 0
