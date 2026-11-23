"""The DC bias clamp must stop when the physical tail gate load changes."""
import importlib.util

import pytest

from serdes_flow import boundary, project


def test_physical_and_reference_load_match_but_changed_tail_is_rejected(tmp_path):
    spec=importlib.util.spec_from_file_location("vco_layout_boundary",project.ROOT/"analog/pll/vco/tb/layout_pex/run.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    directory=project.ROOT/"analog/pll/vco/layout/variants/sym9_clean"
    top="pll_vco_core_sym9_s32p5_clean"
    reference=module.bias_load_signature(directory/(top+"_ref.spice"),top)
    physical=module.bias_load_signature(directory/(top+"_pex.spice"),top)
    assert physical==reference
    assert boundary.check_load("pll_sym9_dc_bias@layout_review_20261115",physical)
    text=(directory/(top+"_pex.spice")).read_text()
    assert "w=6.3 l=0.5" in text
    changed=tmp_path/"changed.spice"
    changed.write_text(text.replace("w=6.3 l=0.5","w=6.4 l=0.5",1))
    with pytest.raises(boundary.BoundaryMismatch):
        boundary.check_load("pll_sym9_dc_bias@layout_review_20261115",module.bias_load_signature(changed,top))
