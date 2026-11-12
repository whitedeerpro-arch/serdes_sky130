"""Offline checks for physical reference topology and frozen input identity."""
import importlib.util
from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('physical_reference_test', ROOT/'analog/common/bias/tb/physical_reference_card/run.py')
card = importlib.util.module_from_spec(spec)
spec.loader.exec_module(card)


def fake_geometry():
    return {f'{name}_{count}': dict(length_um=2.0, parallel_count=1,
             calibrated_domain_um=[.5, 512.], minimum_length_um=.5)
            for name in card.NOMINAL for count in ((1,8) if name=='rref' else (1,))}


def test_calibration_uses_six_actual_w1_devices():
    text=card.calibration_deck('/models/sky130.lib.spice')
    for name,r in card.NOMINAL.items():
        assert f'X{name} rail out_{name} 0 sky130_fd_pr__res_high_po w=1 l={(r-378)/317:.15g}' in text
    assert 'Xrt0 rail out_rt0 0 sky130_fd_pr__res_high_po w=1 ' in text
    assert text.count(' 0 sky130_fd_pr__res_high_po w=1 l=') == 6


def test_frozen_reference_topology_and_trim_switches():
    source=card.BG.read_text(); dims=fake_geometry()
    for mode in card.MODES:
        text=card.variant(source,mode,dims)
        assert f'.subckt serdes_bandgap_{mode} ' in text
        assert f'.ends serdes_bandgap_{mode}' in text
        for i in range(5):
            assert source.count(f'Xs{i} rt{i+1} g{i} '+(f'rt{i}' if i else 'vss')+' vss serdes_nfet')==1
            assert text.count(f'Xs{i} rt{i+1} g{i} '+(f'rt{i}' if i else 'vss')+' vss serdes_nfet')==1
            assert len(re.findall(rf'^Bg{i} g{i} vss ',text,re.M))==1
        for label in ('rsa','rsb','r1','r2'):
            line=next(x for x in source.splitlines() if x.startswith('X'+label+' '))
            assert text.count(line)==1
        if mode!='generic':
            rlines=[x.split() for x in text.splitlines() if x.startswith(('Xrref_','Xrt4_','Xrt3_','Xrt2_','Xrt1_','Xrt0_'))]
            assert len(rlines)==(13 if mode=='fixed_s8' else 6)
            assert all(x[3]=='vss' and x[4]=='sky130_fd_pr__res_high_po_1p41' for x in rlines)
            main=[x for x in rlines if x[0].startswith('Xrref_')]
            pairs=[(x[1],x[2]) for x in main]
            assert pairs[0][0]=='s' and pairs[-1][1]=='rt5'
            assert all(a[1]==b[0] for a,b in zip(pairs,pairs[1:]))
            assert len({x[0] for x in rlines})==len(rlines)


def test_case_matrix_nodes_and_real_copy(tmp_path):
    deck=card.physical_deck(tmp_path,'/models/lib.spice')
    lines=deck.splitlines()
    case_names=set()
    all_case_nodes=[]
    component_names=[]
    for line in lines:
        if line and not line.startswith(('.', '*')) and line[0].upper() in 'XVCRI':
            component_names.append(line.split()[0].lower())
    assert len(component_names)==len(set(component_names))
    for mode in card.MODES:
        for trim in card.TRIMS:
            case=card.case_name(mode,trim);case_names.add(case)
            bg_line=next(line for line in lines if line.startswith('Xbg_'+case+' '))
            pins=bg_line.split()[1:10]
            assert pins[-2:]==['vdd','0'] and all(pin.startswith(case+'_') for pin in pins[:-2])
            all_case_nodes.extend(pins[:-2]+[case+'_vbias',case+'_vcopy'])
            assert f'serdes_bandgap_{mode} trim={trim} cvgi=2p' in deck
            assert f'Xcopy_{case} {case}_vbias {case}_vgi {case}_vcopy serdes_bias_pcopy n=85' in deck
            assert f'Xdiode_{case} {case}_vbias 0 serdes_bias_cml' in deck
            assert all(f'Vi{k}_{case} {case}_i{k} 0 0.7' in deck for k in range(4))
            assert all(f'v(xbg_{case}.rt{k})' in deck for k in range(1,6))
            assert f'v(Xbg_{case}.s)=1.23' in deck
            for temp in card.TEMPS:
                assert sum(line.startswith(f'write {case}_t{temp}.raw ') for line in lines)==1
    assert len(all_case_nodes)==len(set(all_case_nodes))
    assert len(case_names)==15 and len(card.output_names())==45 and len(set(card.output_names()))==45
    assert [int(x) for x in re.findall(r'^option temp=(-?\d+)$',deck,re.M)]==list(card.TEMPS)
    assert lines.count('op')==3
    assert len(re.findall(r'^write .*\.raw ',deck,re.M))==45


def test_subcircuits_namespaced_without_collisions():
    source=card.BG.read_text(); dims=fake_geometry()
    all_names=[]
    for mode in card.MODES:
        text=card.variant(source,mode,dims)
        names=re.findall(r'^\.subckt\s+(\S+)',text,re.M|re.I)
        assert set(names)=={f'{name}_{mode}' for name in ('serdes_bandgap','serdes_bg_amp','serdes_bg_ota','serdes_ref_vbuf')}
        all_names.extend(names)
        assert f'serdes_bg_amp_{mode}' in text and f'serdes_bg_ota_{mode}' in text
    assert len(all_names)==len(set(all_names))


def test_geometry_rejects_unmeasured_or_bad_calibration():
    curve={'coefficients_ohm':[254.77,230.046333578,39.24926493], 'domain_um':[.5,512.]}
    samples={'r_'+name:float(r)*1.02 for name,r in card.NOMINAL.items()}
    got=card.geometries(curve,samples)
    assert len(got)==7 and got['rref_8']['target_resistance_ohm']==samples['r_rref']/8
    samples['r_rt0']=float('nan')
    with pytest.raises(ValueError):card.geometries(curve,samples)
