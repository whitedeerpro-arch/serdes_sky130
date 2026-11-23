"""Reject short or misleading native-loop edge histories."""
import importlib.util
from pathlib import Path

import numpy as np
from serdes_flow import clock
from serdes_flow.project import ROOT


def measure(fb, ref=None, stop=1e-6):
    if ref is None:
        ref = np.arange(2e-9, stop, 4e-9)
    return clock.feedback_lock(ref, fb, start=55e-9, stop=stop)


def test_locked_edges_preserve_static_offset_and_full_history():
    ref = np.arange(2e-9, 1e-6, 4e-9)
    r = measure(ref + 50e-12, ref)
    assert r['lock_assessed'] and r['locked_at_end']
    assert abs(r['offset_s'] - 50e-12) < 1e-20
    assert r['final_pairing_errors'] == 0


def test_short_record_cannot_pass_by_shortening_the_sixty_edge_tail():
    ref = np.arange(2e-9, 100e-9, 4e-9)
    r = measure(ref + 50e-12, ref, stop=100e-9)
    assert not r['lock_assessed'] and not r['locked_at_end']


def test_missing_feedback_and_duplicate_or_skipped_pairing_never_pass():
    ref = np.arange(2e-9, 1e-6, 4e-9)
    assert measure([])['lock_status'] == 'missing_feedback'
    for fb in (ref[::2], np.arange(2e-9, 1e-6, 2e-9), ref[:-15]):
        r = measure(fb)
        assert r['lock_assessed'] and not r['locked_at_end']
        assert r['final_pairing_errors'] > 0


def test_frequency_drift_fails_even_with_relaxed_phase_tolerance():
    ref = np.arange(2e-9, 1e-6, 4e-9)
    r = clock.feedback_lock(ref, ref * 1.001, start=55e-9, stop=1e-6, phase_tolerance=1e-9)
    assert not r['locked_at_end'] and r['final_frequency_error'] > 1e-4


def test_stopped_reference_cannot_certify_a_later_endpoint():
    ref = np.arange(2e-9, 600e-9, 4e-9)
    r = measure(ref + 50e-12, ref, stop=1e-6)
    assert not r['locked_at_end']
    assert r['lock_status'] == 'missing_reference_tail'


def test_native_case_path_handles_zero_and_nonzero_offsets():
    spec = importlib.util.spec_from_file_location('native_r6_path_test', ROOT / 'analog/pll/top/tb/native_r6/run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.case_dir(Path('/tmp/c'), 'tt_v1800_t27:tt', 'ext').name == 'tt_v1800_t27_tt_ext'
    assert module.case_dir(Path('/tmp/c'), 'tt_v1800_t27:tt', 'ext', -1).name.endswith('_ext_o-1')
