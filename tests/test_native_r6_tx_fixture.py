"""The loaded TX gets real PLL nodes, one shared reference, and known sizes."""
import importlib.util
import re
import shutil
from types import SimpleNamespace
import numpy as np
import pytest
from serdes_flow import boundary,netlist,rcorner
from serdes_flow.project import ROOT

spec=importlib.util.spec_from_file_location('native_r6_tx_fixture_test',ROOT/'analog/tx/input_register/tb/native_r6/loaded_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


def test_joined_fixture_uses_real_bridges_and_one_shared_reference():
    base='PLL fixture\nXbias_ref vbg i0 i1 i2 i3 vgi_bias vdd 0 serdes_bias_ref\n.save v(ref)\n.control\ntran 4p 600n 40n 4p\nwrite loop.raw v(ref)\nquit\n.endc\n.end\n'
    text,signature=probe.fixture(base,[],120e-9)
    assert len(re.findall(r'^Xbias_ref ',text,re.M))==1
    assert 'XIref_tx vbias_tx vgi_bias vdd serdes_bias_pcopy n=85' in text
    assert 'Vtap2gp s2gp b0n 0' in text and 'Vtap2gn s2gn b0p 0' in text
    assert not re.search(r'^V(?:250|500|1g|2g) ',text,re.M)
    expected=boundary.input_stage_signature(probe.tx.distribution(**probe.PARAMS),
        'serdes_cml_clock_distribution_tx_lowov',('s2gp','s2gn'))
    assert signature==expected


def test_current_full_tx_sizes_and_pads_are_preserved_in_joint_fixture():
    text,_=probe.fixture('PLL\n.save v(ref)\n.control\ntran 4p 600n 40n 4p\nwrite loop.raw v(ref)\n.endc\n.end\n',[],120e-9)
    assert 'Xe2g_4 ' in text and 'Xe2g_5 ' not in text
    assert 'Xout2g e2g_4p e2g_4n c2gp c2gn vbias vdd vss serdes_cml_buffer wn=32 wt=16 rload=240' in text
    assert 'rpre=120 wtpre=60 wout=192' in text
    assert 'Clpp lqp 0 200f' in text and 'Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16' in text


def test_private_tx_namespace_does_not_rewrite_the_parent_pll():
    parent='PLL\nXpll a b pll_core_r6k4q\n.save v(ref)\n.control\ntran 4p 600n 40n 4p\nwrite loop.raw v(ref)\n.endc\n.end\n'
    text,_=probe.fixture(parent,[],120e-9,('pll_core_r6k4q','serdes_cml_buffer'))
    assert 'Xpll a b pll_core_r6k4q\n' in text
    assert 'serdes_cml_buffer_tx' in text


def test_tx_small_load_resistors_retain_positive_generic_geometry(tmp_path):
    files=[]
    rels=['analog/common/devices/spice/sky130_primitives.spice',
          'analog/common/cml_buffer/spice/cml_delay_resistive.spice',
          'analog/common/cml_buffer/spice/cml_buffer.spice']
    texts=[(ROOT/p).read_text() for p in rels]
    names={n for t in texts for n in re.findall(r'^\.subckt\s+(\S+)',t,re.M)}
    for k,t in enumerate(texts):
        p=tmp_path/f'{k}.spice';p.write_text(rcorner._pdk_cell(probe.renamed(t,names)));files.append(p)
    subs=netlist.parse(files)
    for resistance in (100,120,133,240):
        ds,unknown=netlist.flatten(subs,'serdes_cml_buffer_tx',dict(rload=resistance))
        assert not unknown
        rs=[d for d in ds if d.model=='sky130_fd_pr__res_high_po']
        assert len(rs)==2 and all(d.l>=2 for d in rs)
        assert all(abs((378+317*d.l)/d.w-resistance)<1e-6 for d in rs)


def test_exploratory_parent_does_not_turn_short_hold_into_contract_pass(tmp_path,monkeypatch):
    contract=tmp_path/'verification/contracts/pll_lock_screen.toml';contract.parent.mkdir(parents=True)
    shutil.copyfile(ROOT/'verification/contracts/pll_lock_screen.toml',contract)
    rawdir=tmp_path/'case';rawdir.mkdir();(rawdir/'loop.raw').write_bytes(b'identity-only fixture')
    class Waves:
        t=np.array([40e-9,600e-9])
        def __getitem__(self,name):return np.array([0.,1.8])
    monkeypatch.setattr(probe,'ROOT',tmp_path)
    monkeypatch.setattr(probe.native,'check',lambda p:dict(entries=[dict(point='tt_v1800_t27:tt',variant='ext')]))
    monkeypatch.setattr(probe.native,'completed',lambda p,e:rawdir)
    monkeypatch.setattr(probe.spice,'Waves',lambda p:Waves())
    screen=dict(locked=False,status='not_locked',hold_s=288e-9,windows=[dict(passed=True)])
    monkeypatch.setattr(probe.pll_lock,'screen',lambda *a,**k:screen)
    with pytest.raises(ValueError,match='engineering lock not established'):probe.engineering(tmp_path)
    result=probe.engineering(tmp_path,exploratory=True)
    assert result['last_window_passed'] and not result['contract_passed']
    assert result['execution_mode']=='exploratory_static_loading_only'
    screen['windows']=[dict(passed=False)]
    with pytest.raises(ValueError):probe.engineering(tmp_path,exploratory=True)


def test_channel_keeps_ideal_rlc_as_in_the_existing_full_tx_bench():
    text='.subckt channel a b\nR1 a b .3\nL1 a b .5n\n.ends channel\n'
    result=probe.tx_cell('verification/models/channel/diff_rlc16.spice',text,('channel',))
    assert 'R1 a b .3' in result and 'L1 a b .5n' in result
    assert 'sky130_fd_pr__res_high_po' not in result
    assert '.subckt channel_tx' in result
