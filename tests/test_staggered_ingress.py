"""Fault injection for ingress timing analysis, without running SPICE."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

spec = importlib.util.spec_from_file_location(
    "staggered", Path(__file__).resolve().parents[1] / "analog/tx/input_register/tb/staggered/run.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class Wave:
    def __init__(self):
        self.t = np.arange(2e-9, bench.STOP+1e-12, 5e-12)
        t = self.t
        delay = .35e-9
        high = lambda shift: ((t - 1.015e-9 - shift) % 4e-9) < 2e-9
        self.y = {"vdd": np.full_like(t, 1.8), "sp": high(0).astype(float),
                  "sn": (~high(0)).astype(float), "clk": 1.8*high(delay),
                  "xcap.clk_b": 1.8*(~high(delay+.02e-9))}
        for lane in range(16):
            bits = np.array([(word >> lane) & 1 for word in bench.WORDS])
            arrival = bench.WARMUP + 1.015e-9 + delay + (.2e-9 if lane < 8 else 2.2e-9)
            index = np.clip(np.floor((t-arrival)/4e-9).astype(int)+1, 0, len(bits)-1)
            # index zero is the first word; updates to word one occur one period later.
            index = np.maximum(index-1, 0)
            self.y[f"q{lane}"] = 1.8*bits[index]
            self.y[f"c{lane}p"] = .2*(2*bits[index]-1)
            self.y[f"c{lane}n"] = np.zeros_like(t)
            if lane >= 8:
                idx = np.clip(np.floor((t-(bench.WARMUP+1.015e-9+delay+.1e-9))/4e-9).astype(int), 0, len(bits)-1)
                self.y[f"xcap.h{lane}"] = 1.8*bits[idx]
        for i in range(8):
            self.y[f"z{i}p"] = np.where(high(0), self.y[f"c{i+8}p"], self.y[f"c{i}p"])
            self.y[f"z{i}n"] = np.zeros_like(t)

    def __getitem__(self, name):
        return self.y[name]


def test_delayed_clock_uses_actual_mux_select(monkeypatch):
    wave = Wave()
    monkeypatch.setattr(bench.spice, "Waves", lambda _: wave)
    assert bench.measure(None, "receiver")["functional"]
    # Fault at the start of B selection, before delayed CMOS clk rises. A
    # measurement centered on CMOS clk would miss this hold-window violation.
    bad = (wave.t > bench.WARMUP+5.08e-9) & (wave.t < bench.WARMUP+5.16e-9)
    wave.y["q8"][bad] = 1.8-wave.y["q8"][bad]
    assert not bench.measure(None, "receiver")["functional"]


def test_expected_next_word_transition_cannot_disappear(monkeypatch):
    wave = Wave()
    wave.y["xcap.h8"][:] = 0
    monkeypatch.setattr(bench.spice, "Waves", lambda _: wave)
    with pytest.raises(ValueError, match="expected one next-data transition"):
        bench.measure(None, "receiver")


def test_receiver_requires_select_wave_and_complete_time(monkeypatch):
    wave = Wave()
    monkeypatch.setattr(bench.spice, "Waves", lambda _: wave)
    del wave.y["sp"]
    with pytest.raises(KeyError):
        bench.measure(None, "receiver")
    wave.t = wave.t[:-10]
    with pytest.raises(ValueError, match="incomplete transient"):
        bench.measure(None, "receiver")
