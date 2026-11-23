import pytest

from serdes_flow.timing import sampled_hold_boundary


def test_bracket_requires_both_states_and_monotonic_retention():
    r=sampled_hold_boundary([(0,False),(10e-12,True),(-10e-12,False),(20e-12,True)])
    assert r==dict(status='bracketed',last_failed_s=0,first_passed_s=10e-12)
    assert sampled_hold_boundary([(0,True),(1,False),(2,True)])['status']=='nonmonotonic'
    assert sampled_hold_boundary([(0,True),(1,True)])['status']=='unbracketed'


def test_incomplete_or_ambiguous_samples_are_not_filled():
    for points in ([],[(0,True),(0,False)],[(float('nan'),False)],[(0,None)],[(0,None),(0,True)]):
        with pytest.raises(ValueError):sampled_hold_boundary(points)
