import pytest
from serdes_flow import noise_models


def test_overlay_keeps_parameter_names_and_electrical_expression(tmp_path):
    source=tmp_path/'original.spice'
    text=".subckt sky130_fd_pr__cap_var_lvt c0 c1 b\n.param sky130_fd_pr__cap_var_lvt__cmin=1p\nrg p2 c1 r='100+v(c0,p2)'\n.ends sky130_fd_pr__cap_var_lvt\n"
    source.write_text(text);output=tmp_path/'local.spice';noise_models.varactor_rg(source,output)
    actual=output.read_text()
    assert "rg p2 c1 r='100+v(c0,p2)' noisy=1" in actual
    assert '.param sky130_fd_pr__cap_var_lvt__cmin=1p' in actual
    assert actual.startswith('.subckt sky130_fd_pr__cap_var_lvt_noisy ')
    assert source.read_text()==text


def test_overlay_rejects_unknown_model_instead_of_patching_an_arbitrary_resistor(tmp_path):
    p=tmp_path/'new.spice';p.write_text('.subckt different a b\nRother a b 100\n.ends\n')
    with pytest.raises(ValueError,match='rg anchor changed'):noise_models.varactor_rg(p,tmp_path/'bad.spice')
