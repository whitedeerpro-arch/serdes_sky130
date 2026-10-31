import numpy as np
import pytest

from serdes_flow import balance as bl
from serdes_flow.balance import Budget, ElementModel, Fixed, Inst, Knob, KnobSpec, Params, Sample, Skew, Structure

FLAT = {p: 1.0 for p in ("tt", "ss", "ff", "sf", "fs")}
E = {
    "A": ElementModel("A", 40.0, {"tt": 1, "ss": 1.1, "ff": 0.9, "sf": 0.85, "fs": 1.15}, alpha=-0.02, beta=0.03),
    "Bq": ElementModel("Bq", 40.0, {"tt": 1, "ss": 1.1, "ff": 0.9, "sf": 0.85, "fs": 1.15}, alpha=-0.02, beta=-0.05),
    "R": ElementModel("R", 40.0, FLAT, track="A"),
}
P0 = Params(mismatch={"*": 0.0}, tap_error=0.0)


def test_same_composition_has_no_spread():
    S = Structure("x", "x", {"a": [Inst("A", "1"), Inst("A", "2")], "b": [Inst("A", "3"), Inst("A", "4"), Fixed(10.0)]}, {},
                  [Skew("a", "b", 10.0, 250.0, 100.0, owner="b")], ["a", "b"])
    res, _ = bl.evaluate(S, E, P0, {})
    assert np.ptp(res[0].values) < 1e-9
    assert res[0].margin == pytest.approx(100.0)


def test_opposite_temperature_slopes_spread():
    S = Structure("x", "x", {"a": [Inst("A", "1")], "b": [Inst("Bq", "2")]}, {},
                  [Skew("a", "b", 0.0, 1000.0, 400.0, owner="b")], ["a", "b"])
    res, _ = bl.evaluate(S, E, P0, {})
    i_hot = [k for k, c in enumerate(bl.GRID) if c.tag == "tt_v1800_t85"][0]
    i_cold = [k for k, c in enumerate(bl.GRID) if c.tag == "tt_v1800_t-40"][0]
    # d(b - a) / dt = 40 * (-0.05 - 0.03) per unit t; t spans 2 units between -40 and 85 C
    assert res[0].values[i_hot] - res[0].values[i_cold] == pytest.approx(40 * (-0.08) * 2, rel=1e-6)


def test_replica_tracks_and_residual():
    S = Structure("x", "x", {"a": [Inst("A", "1")], "b": [Inst("R", "2")]}, {},
                  [Skew("a", "b", 0.0, 1000.0, 400.0, owner="b")], ["a", "b"])
    res, _ = bl.evaluate(S, E, P0, {})
    assert np.ptp(res[0].values) < 1e-9
    res, _ = bl.evaluate(S, E, Params(mismatch={"*": 0.0}, tap_error=0.0, tracking={"R": 0.1}), {})
    da = E["A"].delays()
    assert np.ptp(res[0].values) == pytest.approx(0.1 * np.ptp(da), rel=1e-6)


def test_sample_window_margin():
    S = Structure("x", "x", {"d": [Fixed(200.0)], "k": [Fixed(0.0)]}, {},
                  [Sample("d", "k", 500.0, setup=100.0, hold=50.0, owner="k")], ["k"])
    res, _ = bl.evaluate(S, E, P0, {})
    assert res[0].margin == pytest.approx(min(200 - 50, 500 - 100 - 200))


def test_centre_picks_fixed_knob():
    S = Structure("x", "x", {"a": [Fixed(0.0)], "b": [Knob("j")]}, {"j": KnobSpec("fixed", tuple(range(8)), unit=62.5)},
                  [Skew("a", "b", 187.5, 1000.0, 100.0, owner="b")], ["a", "b"])
    kv = bl.centre(S, E, P0)
    assert kv["j"] == 3


def test_budget_delay_limit_is_shrink_budget():
    S = Structure("x", "x", {"loop": [Inst("A", "1"), Inst("A", "2")]}, {}, [Budget("loop", 200.0, owner="loop")], ["loop"])
    lim = bl.limits(S, E, P0, {})
    worst = E["A"].delays().max() * 2
    assert lim["delay"]["A"] == pytest.approx(200.0 / worst, rel=0.01)


def test_fit_element_recovers_model():
    m = E["A"]
    d = m.delays()
    samples = {c.tag: float(d[i]) for i, c in enumerate(bl.GRID)}
    f = bl.fit_element(samples, "A")
    assert f.tt == pytest.approx(m.tt, rel=0.02)
    assert f.beta == pytest.approx(m.beta, abs=0.005)
    assert bl.fit_residual(f, samples) < 2.0
