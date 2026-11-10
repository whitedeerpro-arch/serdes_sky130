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


@pytest.mark.parametrize('count',[4,5])
def test_extended_clock_confirmation_checks_last_stage_and_metadata(count):
    spec=importlib.util.spec_from_file_location('extended_clock_collector',ROOT/'verification/plotting/tx_parallel_serializer.py')
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    plan={'clock_extra_2g':count,'clock_output_wt':16,'clock_output_r':240}
    entry={'upstream':dict(plan)}
    text=flow.distribution(count,16,240)
    assert collector.clock_extra_2g(plan,entry,text)==count
    bad=text.replace(f'Xout2g e2g_{count-1}p e2g_{count-1}n',f'Xout2g e2g_{count-2}p e2g_{count-2}n')
    with pytest.raises(ValueError,match='output stage connectivity'):
        collector.clock_extra_2g(plan,entry,bad)
    with pytest.raises(ValueError,match='metadata mismatch'):
        collector.clock_extra_2g(plan,{'upstream':{**plan,'clock_extra_2g':3}},text)


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


def test_output_stage_candidate_changes_only_output_instance_and_fixture():
    before=flow.distribution(3)
    after=flow.distribution(3,16,240)
    old=before.splitlines(); new=after.splitlines()
    assert len(old)==len(new)
    # Configuration comment also states the resolved parameters; the only
    # changed circuit statement is the output buffer instance.
    differences=[(a,b) for a,b in zip(old,new) if a!=b]
    changed=[(a,b) for a,b in differences if not a.startswith('*')]
    assert len(changed)==1
    assert changed[0][0].startswith('Xout2g ') and 'wn=32 wt=24 rload=300' in changed[0][0]
    assert 'wn=32 wt=16 rload=240' in changed[0][1]
    assert flow.fixture_signature(before)!=flow.fixture_signature(after)
    assert flow.distribution(1,24.0,300.0)==flow.dist.netlist()


@pytest.mark.parametrize('wt,resistance',[(0,300),(-1,300),(float('nan'),300),(24,float('inf')),(24,0)])
def test_invalid_clock_output_parameters_rejected(wt,resistance):
    with pytest.raises(ValueError,match='positive and finite'):
        flow.distribution(1,wt,resistance)


def test_probe_boundary_output_identity_rejects_parameter_changes():
    original={'upstream':{}}
    assert flow.check_output_identity({},original)==(24,300)
    candidate={'upstream':{'clock_output_wt':16,'clock_output_r':240}}
    assert flow.check_output_identity({'clock_output_wt':16,'clock_output_r':240},candidate)==(16,240)
    with pytest.raises(ValueError,match='registered probe'):
        flow.check_output_identity({'clock_output_wt':24,'clock_output_r':300},candidate)


def test_probe_and_dynamic_stimulus_graph_identity():
    probe=flow.static_probe_sources()
    dynamic='\n'.join([f'Vd{i} d{i} 0 PWL(0 0 20n 1.8)' for i in range(16)]+[
        f'Vguard_{name} guard_{name} 0 PWL(0 0 12n 1.8)' for name in ('a','b','ready','valid')])
    assert flow.stimulus_graph_signature(probe)==flow.stimulus_graph_signature(dynamic)
    assert flow.stimulus_graph_signature(dynamic)!=flow.stimulus_graph_signature(dynamic.replace('Vguard_b guard_b 0 PWL(0 0 12n 1.8)\n',''))
    assert flow.stimulus_graph_signature(dynamic)==flow.stimulus_graph_signature(dynamic.replace('20n 1.8','30n 1.2'))
    assert flow.fixture_signature('title\n'+probe+'\n.control')==flow.fixture_signature('title\n'+dynamic+'\n.control')


def test_mismatched_graph_rejected_before_spice():
    good=flow.static_probe_sources()
    planned={'numerical_source_graph_sha256':flow.stimulus_graph_signature(good)}
    entry={'upstream':{'numerical_source_graph_sha256':planned['numerical_source_graph_sha256']}}
    assert flow.check_stimulus_graph(planned,entry,good)==planned['numerical_source_graph_sha256']
    bad=good.replace('Vguard_b guard_b 0 0\n','')
    with pytest.raises(ValueError,match='source graph'):
        flow.check_stimulus_graph(planned,entry,bad)
    # Historical archives without graph metadata remain readable.
    flow.check_stimulus_graph({}, {'upstream':{}}, bad)


def test_execute_rejects_bad_graph_before_spice(tmp_path, monkeypatch):
    import json
    good='title\n'+flow.static_probe_sources()+'\n.control\n.endc\n'
    bad=good.replace('Vguard_b guard_b 0 0\n','')
    expected=flow.stimulus_graph_signature(good)
    fixture=flow.fixture_signature(bad)
    entry={'upstream':{'fixture_sha256':fixture,'numerical_source_graph_sha256':expected}}
    plan={'snapshot_files':{},'pdk_installation_id':'fake',
          'boundary_sha256':hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest(),
          'fixture_sha256':fixture,'deck_sha256':hashlib.sha256(bad.encode()).hexdigest(),
          'numerical_source_graph_sha256':expected}
    (tmp_path/'execution').mkdir();(tmp_path/'execution/physical_tb.cir').write_text(bad)
    monkeypatch.setattr(flow.project,'pdk_installation_id',lambda:'fake')
    called=[]
    monkeypatch.setattr(flow.spice,'run',lambda *args,**kwargs:called.append(True))
    with pytest.raises(ValueError,match='stimulus source graph'):
        flow.execute(tmp_path,plan,None,entry)
    assert not called


def test_new_run_cannot_reuse_an_unbound_legacy_probe():
    data=flow.static_probe_sources()
    plan={'numerical_source_graph_sha256':flow.stimulus_graph_signature(data)}
    with pytest.raises(ValueError,match='record a new probe'):
        flow.check_stimulus_graph(plan,{'upstream':{}},data)


@pytest.mark.parametrize('count',[1,3,5])
def test_extra_sizing_changes_only_the_declared_2g_buffers(count):
    before=flow.distribution(count,16,240)
    after=flow.distribution(count,16,240,14.4,320)
    statements=lambda text:[line for line in text.splitlines() if not line.startswith('*')]
    pairs=list(zip(statements(before),statements(after)))
    assert len(statements(before))==len(statements(after))
    changed=[(a,b) for a,b in pairs if a!=b]
    assert len(changed)==count
    assert all(a.startswith('Xe2g_') and b.endswith('wn=24 wt=14.4 rload=320') for a,b in changed)
    assert flow.fixture_signature(before)!=flow.fixture_signature(after)
    assert flow.distribution(count,16,240,16.0,400.0)==before
    spec=importlib.util.spec_from_file_location('stage_collector',ROOT/'verification/plotting/tx_parallel_serializer.py')
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    plan=dict(clock_extra_2g=count,clock_output_wt=16,clock_output_r=240,clock_stage_wt=14.4,clock_stage_r=320)
    assert collector.clock_extra_2g(plan,{'upstream':dict(plan)},after)==count
    # Correctly signed metadata cannot hide one stale instance in a new chain.
    stale=after.replace('wt=14.4 rload=320','wt=16 rload=400',1)
    with pytest.raises(ValueError,match='sizes differ'):
        collector.clock_extra_2g(plan,{'upstream':dict(plan)},stale)
    flow.check_distribution_identity(plan,after)
    with pytest.raises(ValueError,match='plan parameters'):
        flow.check_distribution_identity({**plan,'clock_stage_wt':14},after)


def test_extra_sizing_boundary_cannot_be_reused_for_different_stage_parameters(tmp_path,monkeypatch):
    import json
    assert flow.check_stage_identity({}, {'upstream':{}})==(16,400)
    entry={'upstream':{'clock_stage_wt':14,'clock_stage_r':320}}
    assert flow.check_stage_identity({'clock_stage_wt':14,'clock_stage_r':320},entry)==(14,320)
    plan={'snapshot_files':{},'pdk_installation_id':'fake',
          'boundary_sha256':hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest(),
          'clock_stage_wt':14.4,'clock_stage_r':320}
    monkeypatch.setattr(flow.project,'pdk_installation_id',lambda:'fake')
    called=[];monkeypatch.setattr(flow.spice,'run',lambda *a,**k:called.append(True))
    with pytest.raises(ValueError,match='extra-stage parameters differ'):
        flow.execute(tmp_path,plan,None,entry)
    assert not called
    with pytest.raises(ValueError,match='registered probe'):
        flow.check_stage_identity({'clock_stage_wt':14,'clock_stage_r':320},{'upstream':{}})


@pytest.mark.parametrize('wt,resistance',[(True,320),(14,False),(0,320),(14,float('inf')),(float('nan'),320)])
def test_invalid_extra_sizing_is_rejected_before_rendering(wt,resistance):
    with pytest.raises(ValueError,match='positive and finite'):
        flow.distribution(5,16,240,wt,resistance)


def test_tapered_profile_binds_each_position_and_rejects_a_stale_stage():
    profile=[[24,14,320]]+[[24,15.6,320] for _ in range(4)]
    text=flow.distribution(5,16,240,stage_profile=profile)
    plan=dict(clock_extra_2g=5,clock_output_wt=16,clock_output_r=240,clock_stage_profile=profile)
    entry={'upstream':dict(plan)}
    assert flow.check_stage_profile_identity(plan,entry)==profile
    flow.check_distribution_identity(plan,text)
    assert 'wn=24 wt=14 rload=320' in next(l for l in text.splitlines() if l.startswith('Xe2g_0 '))
    assert all('wn=24 wt=15.6 rload=320' in l for l in text.splitlines() if l.startswith(tuple(f'Xe2g_{i} ' for i in range(1,5))))
    spec=importlib.util.spec_from_file_location('matrix_collector',ROOT/'verification/plotting/tx_parallel_serializer.py')
    collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
    assert collector.clock_extra_2g(plan,entry,text)==5
    wrong=[[24,14.4,320]]+profile[1:]
    with pytest.raises(ValueError,match='profile differs'):
        flow.check_stage_profile_identity(plan,{'upstream':{**plan,'clock_stage_profile':wrong}})
    with pytest.raises(ValueError,match='profile differs'):
        collector.clock_extra_2g(plan,{'upstream':{**plan,'clock_stage_profile':wrong}},text)
    with pytest.raises(ValueError,match='sizes differ'):
        collector.clock_extra_2g(plan,entry,text.replace('wt=14 rload=320','wt=15.6 rload=320',1))
    with pytest.raises(ValueError,match='plan parameters'):
        flow.check_distribution_identity({**plan,'clock_stage_profile':wrong},text)


@pytest.mark.parametrize('profile',[
    [[24,14,320]], [[True,14,320]]*5, [[24,float('nan'),320]]*5,
    [[24,14,-1]]*5, 'not JSON', {'stages':[]},
])
def test_malformed_per_stage_profiles_cannot_render_a_full_chain(profile):
    with pytest.raises(ValueError):flow.distribution(5,16,240,stage_profile=profile)
