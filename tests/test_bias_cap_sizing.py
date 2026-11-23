"""Guard the bandgap study's topology and physical-cap counting boundaries."""
import importlib.util

from serdes_flow import netlist
from serdes_flow.project import ROOT

sp=importlib.util.spec_from_file_location('bias_caps_test',ROOT/'analog/bias/tb/cap_sizing/run.py')
runner=importlib.util.module_from_spec(sp);sp.loader.exec_module(runner)


def test_legacy_without_measurement_ports_is_exact_original():
    v=next(v for v in runner.VARIANTS if v['name']=='legacy')
    assert runner.cell_sources(v,probe=False)=={p.name:p.read_text() for p in runner.SOURCES}


def test_core_probe_cuts_gate_drive_after_the_differential_error_amplifier(tmp_path):
    cells=runner.cell_sources(next(v for v in runner.VARIANTS if v['name']=='phys6'))
    files=[]
    for name,text in cells.items():
        p=tmp_path/name;p.write_text(text);files.append(p)
    subs=netlist.parse(files);bg=subs['serdes_bandgap_probe']
    elements={e.name:e for e in bg.elements}
    assert elements['xamp'].nodes[:3]==['tb','ta','core_return']
    assert all(elements[f'xm{k}'].nodes[1]=='core_input' for k in range(1,6))
    assert elements['xamp2'].nodes[:3]==['vi_input','vbg','vgi']
    assert elements['xrref'].nodes[0]=='vi_return'
    assert elements['xmv'].nodes[0]=='vi_return'


def test_physical_reference_uses_explicit_units_with_independent_sum(tmp_path):
    for name,total in [('phys6',13),('cc4',11),('gi0',11)]:
        files=[]
        folder=tmp_path/name;folder.mkdir()
        for filename,text in runner.cell_sources(next(v for v in runner.VARIANTS if v['name']==name),probe=False).items():
            p=folder/filename;p.write_text(text);files.append(p)
        ds,unknown=netlist.flatten(netlist.parse(files),'serdes_bias_ref')
        assert not unknown
        caps=[d for d in ds if 'cap_mim_m3_' in d.model]
        assert len(caps)==total
        assert not any(d.kind=='C' for d in ds)
        assert all(d.w==22.1965 and d.l==22.1965 for d in caps)


def test_compensation_rz_keeps_four_real_contacted_segments(tmp_path):
    cells=runner.cell_sources(next(v for v in runner.VARIANTS if v['name']=='cc4_r30p'),probe=False)
    files=[]
    for name,text in cells.items():
        p=tmp_path/name;p.write_text(text);files.append(p)
    ds,unknown=netlist.flatten(netlist.parse(files),'serdes_bias_ref')
    assert not unknown
    rs=[d for d in ds if d.path.startswith('xbg.xamp.xrz')]
    assert len(rs)==4
    assert abs(sum(378+317*d.l for d in rs)-30000)<1e-6


def test_natural_startup_ramps_all_clamps_and_noise_has_only_dc_sources():
    spec=importlib.util.spec_from_file_location('bias_caps_dynamic_test',ROOT/'analog/bias/tb/cap_sizing/dynamic.py')
    dynamic=importlib.util.module_from_spec(spec);spec.loader.exec_module(dynamic)
    e=dict(section='tt',supply_v=1.8,temp_c=27,load='dist',files=['bandgap.spice'],mode='startup',step_v=.05)
    startup=dynamic.deck(e)
    assert '.nodeset' not in startup and '.ic ' not in startup and ' uic' not in startup
    assert 'Vi0 i0 clamp0 0' in startup
    assert 'Bi1 i1 0 V=0.7*min(time/1u,1)' in startup
    assert 'Btop top 0 V=min(time/1u,1)' in startup
    noise=dynamic.deck(dict(e,mode='noise'))
    assert 'time/' not in noise and 'pwl(' not in noise
    assert all(f'Vi{k} i{k} 0 0.7' in noise for k in range(4))
