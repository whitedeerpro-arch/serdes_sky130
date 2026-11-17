"""Frozen native-loop inputs and completed transient boundaries."""
import hashlib
import importlib.util
import json
import numpy as np
import pytest
from serdes_flow.project import ROOT

spec=importlib.util.spec_from_file_location('native_r6_campaign_test',ROOT/'analog/pll/top/tb/native_r6/campaign.py')
campaign=importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


def test_changed_frozen_input_is_rejected_before_execution(tmp_path,monkeypatch):
    path=tmp_path/'prepared.cir';path.write_text('original deck')
    plan=dict(pdk_id='test',external_sha256={},source_sha256={},
              snapshots={'prepared.cir':hashlib.sha256(path.read_bytes()).hexdigest()})
    (tmp_path/'plan.json').write_text(json.dumps(plan))
    monkeypatch.setattr(campaign.project,'pdk_installation_id',lambda:'test')
    assert campaign.check(tmp_path)==plan
    path.write_text('changed clock source')
    with pytest.raises(ValueError,match='Frozen input changed'):
        campaign.check(tmp_path)


def test_exit_zero_cannot_hide_truncated_or_different_deck(tmp_path,monkeypatch):
    (tmp_path/'prepared').mkdir();(tmp_path/'prepared/case.cir').write_text('frozen deck')
    run=tmp_path/'case';run.mkdir();(run/'tb.cir').write_text('frozen deck')
    (run/'execution.json').write_text(json.dumps(dict(exit_code=0,timed_out=False,log_failures=[])))
    class Wave:
        t=np.array([40e-9,99e-9])
        data=np.zeros((2,14))
        def __contains__(self,name):return True
    monkeypatch.setattr(campaign.spice,'Waves',lambda p:Wave())
    e=dict(name='case',t_end_s=100e-9)
    assert campaign.completed(tmp_path,e) is None
    Wave.t=np.array([40e-9,100e-9])
    assert campaign.completed(tmp_path,e)==run
    (run/'tb.cir').write_text('different source')
    assert campaign.completed(tmp_path,e) is None
