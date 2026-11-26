"""Synthetic tests for serdes_flow.serial.bit_mapping.

Verifies order-agnostic eye opening, edge-spread measurement, in-order latency,
intra-word and cross-word divider permutations, and corrupted bit streams
without relying on external simulation outputs.
"""
import numpy as np
import pytest

from serdes_flow import serial

UI_S = 250e-12
START_S = 1e-9


def _sequence(words=20, seed=7):
    rng = np.random.default_rng(seed)
    alternating = np.tile([0, 1], serial.ALTERNATING_BITS // 2)
    marker = rng.integers(0, 2, size=serial.TRAINING_BITS - serial.ALTERNATING_BITS)
    payload = rng.integers(0, 2, size=16 * words - serial.TRAINING_BITS)
    bits = np.concatenate([alternating, marker, payload])
    return serial.Sequence(bits, start_s=START_S, ui_s=UI_S)


def _waveform(
    out_bits,
    *,
    start_s=START_S,
    ui_s=UI_S,
    phase_ui=0.18,
    amp_v=0.25,
    jitter_ui=None,
    ramp_s=60e-12,
    end_pad_s=3e-9,
):
    levels = amp_v * (2 * np.asarray(out_bits, dtype=float) - 1)
    ts = [0.0]
    ys = [levels[0]]
    for n in range(1, len(levels)):
        if levels[n] != levels[n - 1]:
            dt_j = 0.0 if jitter_ui is None else float(jitter_ui[n])
            tc = start_s + (n + phase_ui + dt_j) * ui_s
            ts.extend((tc - 0.5 * ramp_s, tc + 0.5 * ramp_s))
            ys.extend((levels[n - 1], levels[n]))
    ts.append(start_s + len(levels) * ui_s + end_pad_s)
    ys.append(levels[-1])
    return np.asarray(ts, dtype=float), np.asarray(ys, dtype=float)


def test_in_order_waveform_matches_contract_eye_and_phase():
    seq = _sequence()
    t, y = _waveform(seq.bits, phase_ui=0.18, amp_v=0.25)

    r = serial.bit_mapping(t, y, seq)
    contract, _ = serial.check(t, y, seq, payload_bits=16 * 12)

    assert r["in_order"]
    assert r["mapping"] == list(range(16))
    assert r["frame_offset_ui"] == 0
    assert r["words_used"] >= 10
    assert r["sampling_phase_ui"] == pytest.approx(0.18, abs=1e-6)
    assert r["edge_spread_ui"] == pytest.approx(0.0, abs=1e-6)
    assert contract["functional"]
    assert r["eye_min_abs_v"] == pytest.approx(contract["minimum_signed_margin_v"], abs=1e-6)


def test_pure_integer_latency_stays_in_order():
    seq = _sequence()
    latency = 3
    out_bits = np.concatenate([np.zeros(latency, dtype=int), seq.bits])
    t, y = _waveform(out_bits, phase_ui=-0.22, amp_v=0.25)

    r = serial.bit_mapping(t, y, seq)

    assert r["in_order"]
    assert r["mapping"] == list(range(16))
    assert r["frame_offset_ui"] == latency
    assert r["sampling_phase_ui"] == pytest.approx(-0.22, abs=1e-6)
    assert r["eye_min_abs_v"] == pytest.approx(0.25, abs=1e-6)


def test_wrong_divider_state_is_detected_as_permutation_with_healthy_eye():
    seq = _sequence()
    perm = [4, 5, 6, 7, 0, 1, 2, 3, 12, 13, 14, 15, 8, 9, 10, 11]
    words = seq.bits.reshape(-1, 16)
    permuted = words[:, perm].ravel()
    out_bits = np.concatenate([np.zeros(2, dtype=int), permuted])
    t, y = _waveform(out_bits, phase_ui=0.12, amp_v=0.25)

    r = serial.bit_mapping(t, y, seq)
    contract, _ = serial.check(t, y, seq, payload_bits=16 * 12)

    assert not contract["functional"]
    assert r["mapping"] == perm
    assert r["frame_offset_ui"] == 2
    assert not r["in_order"]
    assert sorted(r["mapping"]) == list(range(16))
    assert r["eye_min_abs_v"] == pytest.approx(0.25, abs=1e-6)


def test_cross_word_permutation_resolves_neighbor_word_slots():
    seq = _sequence()
    cross_map = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, -4, -3, -2, -1]
    out_bits = np.zeros_like(seq.bits)
    for k in range(1, len(seq.bits) // 16):
        for j, src in enumerate(cross_map):
            out_bits[16 * k + j] = seq.bits[16 * k + src]
    t, y = _waveform(out_bits, phase_ui=0.05, amp_v=0.22)

    r = serial.bit_mapping(t, y, seq)

    assert r["mapping"] == cross_map
    assert r["frame_offset_ui"] == 0
    assert not r["in_order"]
    assert any(s < 0 for s in r["mapping"])
    assert r["eye_min_abs_v"] == pytest.approx(0.22, abs=1e-6)


def test_bit_errors_clear_mapping_without_hiding_eye_or_edge_spread():
    seq = _sequence()
    corrupted = seq.bits.copy()
    corrupted[16 * 6 + 3] ^= 1
    corrupted[16 * 9 + 11] ^= 1
    jitter = np.where(np.arange(len(corrupted)) % 2 == 0, -0.05, 0.05)
    t, y = _waveform(corrupted, phase_ui=0.10, amp_v=0.25, jitter_ui=jitter)

    r = serial.bit_mapping(t, y, seq)

    assert r["mapping"] is None
    assert not r["in_order"]
    assert r["frame_offset_ui"] is None
    assert r["words_used"] == 0
    assert r["eye_min_abs_v"] == pytest.approx(0.25, abs=1e-6)
    assert r["edge_spread_ui"] == pytest.approx(0.10, abs=1e-6)
