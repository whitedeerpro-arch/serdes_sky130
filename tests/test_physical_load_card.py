"""Offline physical-load topology and probe coverage checks."""
import importlib.util
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('tx_physical_load_test',ROOT/'analog/tx/output_driver/tb/physical_load_card/run.py')
card=importlib.util.module_from_spec(spec);spec.loader.exec_module(card)


def samples():
    return {'fixed_2p85':[dict(card='2p85',parallel_count=6,length_um=5.4),dict(card='2p85',parallel_count=24,length_um=9.84)],
            'fixed_5p73':[dict(card='5p73',parallel_count=3,length_um=5.41),dict(card='5p73',parallel_count=12,length_um=9.87)]}


def inputs():
    root=card.PARENT/'snap/fs_v1650_t85/pdk_resistors'
    return [(root/p).read_text() for p in (card.REL_DRIVER,card.REL_DELAY,card.REL_BUFFER)]


def test_fixed_replacement_scoped_to_pre_and_termination():
    driver,delay,buffer=inputs();net=samples()
    for mode in card.MODES[1:]:
        text=card.variant_cells(driver,delay,buffer,mode,net)
        pre,term=net[mode]
        assert f'Xpre ip in gp gn vbias vdd_pre vss pre_buffer_{mode}' in text
        assert 'Xiso inp inn ip in vbias vdd_pre vss serdes_cml_buffer' in text
        for side in ('p','n'):
            assert len(re.findall(rf'^XR{side}_\d+ vdd out{side} vss sky130_fd_pr__res_high_po_{pre["card"]} ',text,re.M))==pre['parallel_count']
            assert len(re.findall(rf'^XR{side}_\d+ vdd_out q{side} vss sky130_fd_pr__res_high_po_{term["card"]} ',text,re.M))==term['parallel_count']
        for line in driver.splitlines():
            if line.startswith(('XbgN ','XbgP ','Xt ','Xp ','Xn ')):assert line in text


def test_complete_per_branch_probe_coverage():
    net=samples()
    for mode in card.MODES:
        nodes,props,groups=card.probes(mode,net)
        assert len(nodes)==len(set(nodes)) and len(props)==len(set(n for n,p in props))
        for branch in (1,2):
            for kind in ('term','pre'):
                count=1 if mode=='generic' else net[mode][1 if kind=='term' else 0]['parallel_count']
                for side in ('p','n'):
                    names=groups[f'{kind}_{side}{branch}'];assert len(names)==count
                    for name in names:
                        paths=[p for n,p in props if n==name];assert len(paths)==1
                        assert ('rbody[i]' if mode=='generic' else 'rhrpoly_'+net[mode][0]['card']+'[i]') in paths[0]
            assert f'itail_id{branch}' in dict(props) and f'pre_itail_id{branch}' in dict(props)


def test_pair_deck_modes_and_probes():
    parent=(card.PARENT/'prepared/fs_v1650_t85/tb.cir').read_text();net=samples()
    for mode in card.MODES:
        text=card.deck(parent,mode,net,'/overlay/sky130.lib.spice','/tmp/variant.spice')
        assert text.count('Xdriver1 ')==1 and text.count('Xdriver2 ')==1
        assert 'Ven1 tx_en1 0 PWL(0 0 4n 0 4.1n 1.65)' in text and 'Ven2 tx_en2 0 1.65' in text
        assert text.count('Xbias_ref ')==1 and 'Xchannel1 ' in text and 'Xchannel2 ' in text
        assert text.count('.save ')==1 and text.count('write waveforms.raw ')==1
        assert ('driver_'+mode in text)==(mode!='generic')
        nodes,props,groups=card.probes(mode,net)
        for name,probe in props:assert probe in text and f'let {name}={probe}' in text
        for leg in ('lap1','ltp1','lap2','ltp2'):assert f'v({leg})' in text


def test_registered_input_signature_matches_all_variants():
    driver,delay,buffer=inputs();net=samples()
    for mode in card.MODES:
        text=driver if mode=='generic' else card.variant_cells(driver,delay,buffer,mode,net)
        name='serdes_tx_cml_line_driver_lowvt_enable' if mode=='generic' else 'driver_'+mode
        signature=card.boundary.input_stage_signature(text,name,('inp','inn'))
        assert signature['sha']=='89de63369106e2a2'
        assert card.boundary.check_load(card.BC_ID,signature)
