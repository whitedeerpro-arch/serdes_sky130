"""Offline verification of exact series PWL construction and template topology."""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('series_pwl',ROOT/'analog/tx/input_register/tb/retime_demand/series_pwl.py')
series = importlib.util.module_from_spec(spec)
spec.loader.exec_module(series)


@pytest.mark.parametrize('count', [1,4,16,25])
def test_series_sum_at_all_breakpoints_and_between(count):
    rng = np.random.default_rng(37)
    t = np.r_[0.,np.cumsum(rng.uniform(.01,1.,31))]
    y = rng.normal(size=len(t))
    parts, err = series.series_parts(t,y,count)
    probe = np.sort(np.r_[t,(t[:-1]+t[1:])/2])
    reconstructed = sum((np.interp(probe,x,z) for x,z in parts),np.zeros_like(probe))
    np.testing.assert_allclose(reconstructed,np.interp(probe,t,y),atol=1e-12,rtol=0)
    assert err <= 1e-12
    assert len(parts) == count


def test_short_input_pads_unused_sources_and_preserves_initial_voltage():
    parts, _ = series.series_parts(np.array([0.,1.,2.]),np.array([1.8,1.2,1.4]),16)
    assert parts[0][1][0] == 1.8
    assert all(np.all(y == 0) for _,y in parts[2:])


def test_template_preserves_downstream_load_and_serial_connections():
    original = series.BASE_TEMPLATE()
    rendered = series.series_template()
    assert series.base.helper.lines(original,series.base.helper.LOAD_NAMES) == series.base.helper.lines(rendered,series.base.helper.LOAD_NAMES)
    for node, count in series.COUNTS.items():
        source = series.base.helper.SOURCE_MAP[node]
        orig = next(x for x in original.splitlines() if x.split() and x.split()[0] == source).split()
        for i in range(count):
            line = next(x for x in rendered.splitlines() if x.split() and x.split()[0] == series.source_name(node,i)).split()
            assert line[1] == (orig[1] if i == 0 else f'series_{node}_{i}')
            assert line[2] == ('0' if i == count-1 else f'series_{node}_{i+1}')
