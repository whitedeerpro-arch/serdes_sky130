"""Guard the physical circuit identity of the LDO shrink experiment."""
import importlib.util
from pathlib import Path

import pytest

from serdes_flow.project import ROOT

spec = importlib.util.spec_from_file_location('ldo_cap_sizing_test', ROOT/'analog/ldo/tb/cap_sizing/run.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_baseline_source_is_exact_original():
    v=next(x for x in runner.VARIANTS if x['name']=='r4')
    assert runner.cell_sources(v)=={p.name:p.read_text() for p in runner.r4.CELLS}


def test_shrink_retains_all_mos_and_feedback_reference_controls():
    original=runner.cell_sources(runner.VARIANTS[0])
    small=runner.cell_sources(next(x for x in runner.VARIANTS if x['name']=='s16'))
    core='ldo_hv18_core_r4.spice'
    mos=lambda text:[x for x in text.splitlines() if 'sky130_fd_pr__' in x]
    assert mos(original[core])==mos(small[core])
    macro='pll_supply_hv18_r4.spice'
    assert original[macro].replace('Xcout quiet vss serdes_ldo_mim100','Xcout quiet vss serdes_ldo_mim16')==small[macro]
    assert all(original[n]==small[n] for n in original if n not in (core,macro))
    assert 'mf=' not in small['ldo_passives.spice']


def test_source_anchor_change_prevents_unintended_experiment(monkeypatch):
    original=Path.read_text
    def changed(path,*args,**kwargs):
        data=original(path,*args,**kwargs)
        return data.replace('Xchv va vss serdes_ldo_mim50','Xrenamed va vss serdes_ldo_mim50') if path.name=='ldo_hv18_core_r4.spice' else data
    monkeypatch.setattr(Path,'read_text',changed)
    with pytest.raises(ValueError,match='anchor changed'):
        runner.cell_sources(next(x for x in runner.VARIANTS if x['name']=='s16'))


def test_zero_output_cap_is_removed_not_fake_scaled():
    source=runner.cell_sources(next(x for x in runner.VARIANTS if x['name']=='s0'))['pll_supply_hv18_r4.spice']
    assert 'serdes_ldo_mim0' not in source
    assert not any(x.startswith('Xcout ') for x in source.splitlines())


def test_pex_is_bound_to_external_port_order_and_observed_nodes(tmp_path):
    p=tmp_path/'core.spice'
    p.write_text('''.subckt serdes_ldo_hv18_smallcap_pdk vss out vin off ibias fb ref
X0 mid gate out vss sky130_fd_pr__nfet_05v0_nvt w=10 l=.9
X1 vin casg mid vss sky130_fd_pr__nfet_05v0_nvt w=10 l=.9
X2 drain ctrl va va sky130_fd_pr__pfet_g5v0d10v5 w=1 l=4
.ends
''')
    v=runner.pex_variant(next(x for x in runner.VARIANTS if x['name']=='b32'),p)
    assert v['probe_map']['v(xdut.xcore.mid)']=='v(xdut.xcore.xpex.mid)'
    assert v['probe_map']['v(xdut.xcore.gate)']=='v(xdut.xcore.xpex.gate)'
    source=runner.cell_sources(v)['ldo_hv18_core_r4.spice']
    assert 'Xpex vss out vin off ibias fb ref serdes_ldo_hv18_smallcap_pdk' in source
    p.write_text(p.read_text().replace('vss out vin off ibias fb ref','vin out vss off ibias fb ref'))
    with pytest.raises(ValueError,match='ports'):
        runner.pex_variant(next(x for x in runner.VARIANTS if x['name']=='b32'),p)


def test_published_cells_equal_measured_candidate_after_name_changes():
    v=next(x for x in runner.VARIANTS if x['name']=='b32_h2')
    cells=runner.cell_sources(v)
    def code(text):return [x.strip() for x in text.splitlines() if x.strip() and not x.lstrip().startswith('*')]
    core=(ROOT/'analog/ldo/spice/ldo_hv18_core_smallcap.spice').read_text()
    expected=cells['ldo_hv18_core_r4.spice'].replace('serdes_ldo_hv18_core_r4','serdes_ldo_hv18_core_smallcap')
    assert code(core)==code(expected)
    macro=(ROOT/'analog/ldo/spice/pll_supply_hv18_smallcap.spice').read_text()
    expected=cells['pll_supply_hv18_r4.spice'].split('* Candidate filter AFTER')[0].replace('serdes_pll_supply_hv18_r4','serdes_pll_supply_hv18_smallcap').replace('serdes_ldo_hv18_core_r4','serdes_ldo_hv18_core_smallcap')
    assert code(macro)==code(expected)


@pytest.mark.parametrize('name,total,cas,ref_units', [('ref4_r2',58,16,64),('cas12_ref4',54,12,32)])
def test_peripheral_candidates_flatten_to_physical_arrays_and_resistors(tmp_path,name,total,cas,ref_units):
    from serdes_flow import netlist
    sources=runner.cell_sources(next(v for v in runner.VARIANTS if v['name']==name))
    files=[]
    for filename,data in sources.items():
        p=tmp_path/filename;p.write_text(data);files.append(p)
    devices,unknown=netlist.flatten(netlist.parse(files),'serdes_pll_supply_hv18_r4_probe')
    assert not unknown
    mim=[d for d in devices if d.model=='sky130_fd_pr__cap_mim_m3_1']
    assert len(mim)==total
    assert sum(d.path.startswith('xcore.xccas.') for d in mim)==cas
    reference_res=[d for d in devices if d.path.startswith('xrefres') and d.model=='sky130_fd_pr__res_high_po']
    assert len(reference_res)==ref_units
    assert all(d.w==1 and d.l==pytest.approx((31250-378)/317) for d in reference_res)


def test_inventory_counts_shared_roots_without_summing_historical_definitions():
    spec=importlib.util.spec_from_file_location('ldo_inventory_test',ROOT/'verification/analysis/ldo_cap_inventory.py')
    inventory=importlib.util.module_from_spec(spec);spec.loader.exec_module(inventory)
    rows=inventory.inventory()['rows']
    assert [r['nominal_pf'] for r in rows]==[70,16,18,13,5]
    assert not any(r['unknown_subcircuits'] for r in rows)
    assert sorted(x['nominal_pf'] for x in rows[0]['branches'])==[2,4,16,16,32]


def test_stacked_core_retains_nominal_units_and_reference_output_first_layer(tmp_path):
    from serdes_flow import netlist
    cells=runner.cell_sources(next(v for v in runner.VARIANTS if v['name']=='stack_core70'))
    files=[]
    for name,data in cells.items():
        p=tmp_path/name;p.write_text(data);files.append(p)
    ds,unknown=netlist.flatten(netlist.parse(files),'serdes_pll_supply_hv18_r4_probe')
    assert not unknown
    caps=[d for d in ds if 'cap_mim_m3_' in d.model]
    assert len(caps)==70
    assert sum(d.model.endswith('_2') for d in caps)==24
    assert all(d.path.startswith('xcore.') for d in caps if d.model.endswith('_2'))
    assert sum(d.path.startswith('xrefcap.') for d in caps)==16
    assert sum(d.path.startswith('xcout.') for d in caps)==4


def test_published_stacked_cells_equal_measured_sources_after_names():
    cells=runner.cell_sources(next(v for v in runner.VARIANTS if v['name']=='stack_core70'))
    def code(t):return [s.strip() for s in t.splitlines() if s.strip() and not s.lstrip().startswith('*')]
    src=ROOT/'analog/ldo/spice'
    expected=cells['ldo_hv18_core_r4.spice'].replace('serdes_ldo_hv18_core_r4','serdes_ldo_hv18_core_stacked')
    assert code((src/'ldo_hv18_core_stacked.spice').read_text())==code(expected)
    expected=cells['pll_supply_hv18_r4.spice'].split('* Candidate filter AFTER')[0]
    expected=expected.replace('serdes_pll_supply_hv18_r4','serdes_pll_supply_hv18_stacked').replace('serdes_ldo_hv18_core_r4','serdes_ldo_hv18_core_stacked')
    assert code((src/'pll_supply_hv18_stacked.spice').read_text())==code(expected)
    expected=cells['ldo_passives.spice'].split('.subckt serdes_ldo_stack32',1)[1]
    assert code((src/'ldo_stacked_passives.spice').read_text())==code('.subckt serdes_ldo_stack32'+expected)
