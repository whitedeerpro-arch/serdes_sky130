import importlib.util
import hashlib
import pytest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone

from serdes_flow.project import ROOT

spec=importlib.util.spec_from_file_location('parallel_serializer',ROOT/'analog/tx/input_register/tb/full_serializer/run.py')
flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)


def test_data_replay_preserves_fixture_but_load_and_clock_changes_do_not():
    a='title\n.include "one.spice"\nVd0 d0 0 0\nB2gp s2gp 0 V=1.45+.2*v(u)\nCq0 xtx.q0 0 2f\n.save v(qp)\n.control\ntran 2p 48n\n.endc'
    b=a.replace('one.spice','snapshot.spice').replace('Vd0 d0 0 0','Vd0 d0 0 PWL(0 0 1n 1.8)\nVguard_a guard_a 0 0').replace('tran 2p 48n','tran 2p 120n')
    assert flow.fixture_signature(a)==flow.fixture_signature(b)
    assert flow.fixture_signature(a)!=flow.fixture_signature(b.replace('0 2f','0 5f'))
    assert flow.fixture_signature(a)!=flow.fixture_signature(b.replace('+.2*v(u)','+.25*v(u)'))


def test_resume_rejects_changed_runtime_include(tmp_path):
    cell=tmp_path/'snap/cell.spice'
    cell.parent.mkdir()
    cell.write_text('original cell')
    deck=f'.include "{cell}"'
    plan={'snapshot_files':{'snap/cell.spice':hashlib.sha256(cell.read_bytes()).hexdigest()},'sources':{}}
    flow.check_runtime_includes(deck,tmp_path,plan)
    cell.write_text('modified cell')
    with pytest.raises(ValueError,match='changed runtime include'):
        flow.check_runtime_includes(deck,tmp_path,plan)


def test_baseline_clock_distribution_is_preserved_and_added_stage_changes_fixture():
    original=flow.dist.netlist()
    assert flow.distribution(1)==original
    changed=flow.distribution(2)
    assert flow.fixture_signature(original)!=flow.fixture_signature(changed)
    # The historical s2g input stage remains the same upstream load.
    first=lambda text:next(line for line in text.splitlines() if line.startswith('Xch_a2g '))
    assert first(original)==first(changed)


def test_concurrent_campaigns_keep_both_runs_when_timestamp_is_identical(tmp_path,monkeypatch):
    class FixedTime:
        @staticmethod
        def now(_):return datetime(2026,11,7,tzinfo=timezone.utc)
    monkeypatch.setattr(flow,'datetime',FixedTime)
    monkeypatch.setattr(flow,'ROOT',tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        directories=list(pool.map(lambda _:flow.new_campaign_dir(),range(2)))
    assert len(set(directories))==2
    for i,directory in enumerate(directories):
        (directory/'input.txt').write_text(str(i))
    assert [(d/'input.txt').read_text() for d in directories]==['0','1']
