import pytest
from serdes_flow.cap_fusion import Mim, require_same_domain


def test_area_only_fusion_loses_small_cap_perimeter():
    m = Mim(2, .19, -.025, .047, 3.41)
    assert m.cap_ff(2, 2) == pytest.approx(9.30225)
    assert m.cap_ff(8, 8) == pytest.approx(133.26225)
    side = m.square_um(16*m.cap_ff(2, 2))
    assert m.cap_ff(side, side) == pytest.approx(16*m.cap_ff(2, 2))


def test_equal_tt_value_does_not_imply_equal_corner_value():
    nominal = Mim(2, .19, -.025, .047, 3.41)
    low_perimeter = Mim(1.778, .03, -.09, .056, 8)
    side = nominal.square_um(16*nominal.cap_ff(2, 2))
    assert low_perimeter.cap_ff(side, side) > 1.15*16*low_perimeter.cap_ff(2, 2)


def test_floorplan_width_can_be_held_while_length_preserves_capacitance():
    m=Mim(2,.19,-.025,.047,3.41)
    target=8*m.cap_ff(2,2)
    length=m.length_um(target,4.6)
    assert length==pytest.approx(7.6513903463)
    assert m.cap_ff(4.6,length)==pytest.approx(target)


def test_terminal_orientation_and_control_are_not_ignored():
    item = dict(model='mim', upper='phase', lower='plate0', control='b0', body='vss')
    require_same_domain([item, item])
    for changed in (dict(lower='plate1'), dict(control='b1'), dict(upper='plate0', lower='phase')):
        with pytest.raises(ValueError, match='domain'):
            require_same_domain([item, item | changed])
