"""Compare four completed reduced-clock full-TX runs; no simulation is performed.

--check validates metadata only and never reads waveform data or writes outputs.
--collect additionally validates archives and writes data and figures.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import spice, watch
from serdes_flow.project import ROOT

PARALLEL=ROOT/'verification/plotting/tx_parallel_serializer.py'
CLOCK=ROOT/'verification/plotting/tx_clock_output_confirmation.py'

def load_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

parallel=load_module('parallel_collector',PARALLEL)
clock_metrics=load_module('clock_confirmation',CLOCK)
DATA=ROOT/'docs/data/tx_reduced_clock_full_confirmation.json'
CATALOG=ROOT/'results/catalog/tx_reduced_clock_full_confirmation.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_reduced_clock_full_confirmation'
EXPECTED={(tag,extra) for tag in ('tt_v1800_t27','fs_v1650_t85') for extra in (3,5)}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def preflight(campaigns):
    paths=[p.resolve() for p in campaigns]
    if len(paths)!=4 or len(set(paths))!=4:raise ValueError('four distinct campaign directories required')
    alive=watch.ngspice_cwds();records=[]
    for camp in paths:
        if not camp.is_relative_to(ROOT):raise ValueError('campaign outside repository')
        if any(p.is_relative_to(camp) for p in alive):raise ValueError(f'active ngspice: {camp}')
        for name in ('plan.json','summary.json','execution/boundary.json','execution/stimulus_manifest.json'):
            if not (camp/name).is_file():raise ValueError(f'pending or incomplete campaign: {camp} missing {name}')
        if (camp/'analysis_error.json').exists():raise ValueError(f'rejected campaign: {camp}')
        plan=json.loads((camp/'plan.json').read_text());summary=json.loads((camp/'summary.json').read_text())
        entry=json.loads((camp/'execution/boundary.json').read_text())
        if plan.get('mode')!='run' or not math.isclose(plan.get('stop_s',0),120e-9,rel_tol=0,abs_tol=1e-15):
            raise ValueError(f'not a full 120 ns dynamic campaign: {camp}')
        if 'outputs' not in summary or 'sequence_start_s' not in summary or not isinstance(summary.get('waveform'),str):
            raise ValueError(f'campaign summary incomplete: {camp}')
        raw=(ROOT/summary['waveform']).resolve()
        if not raw.is_relative_to(camp) or not raw.is_file():raise ValueError(f'summary waveform missing or outside campaign: {camp}')
        execution=raw.parent/'execution.json';deck=raw.parent/'tb.cir'
        if not execution.is_file() or not deck.is_file():raise ValueError(f'run execution metadata missing: {camp}')
        ex=json.loads(execution.read_text())
        if ex.get('exit_code')!=0 or ex.get('timed_out') or ex.get('log_failures'):
            raise ValueError(f'run execution failed: {camp}')
        if sha(deck)!=ex.get('deck_sha256') or ex.get('deck_sha256')!=plan.get('deck_sha256'):
            raise ValueError(f'run deck identity mismatch: {camp}')
        if hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256']:
            raise ValueError(f'boundary hash mismatch: {camp}')
        graph=plan.get('numerical_source_graph_sha256');registered=entry.get('upstream',{}).get('numerical_source_graph_sha256')
        if not isinstance(graph,str) or re.fullmatch(r'[0-9a-fA-F]{64}',graph) is None or graph!=registered:raise ValueError('missing or mismatched source graph hash')
        stage=plan.get('clock_extra_2g',1)
        if type(stage) is not int:raise ValueError('clock extra stage count must be an integer')
        key=(plan['condition'],stage)
        if key not in EXPECTED or (plan.get('clock_output_wt',24),plan.get('clock_output_r',300))!=(16,240):
            raise ValueError(f'unexpected condition, stage count or output parameters: {camp}')
        records.append(dict(path=camp,plan=plan,graph=graph,key=key))
    if {r['key'] for r in records}!=EXPECTED:raise ValueError('condition/stage coverage incomplete or duplicate')
    if len({r['graph'] for r in records})!=1:raise ValueError('source graph identities differ')
    return records


def collect(records):
    cases=[]
    for record in records:
        plan=record['plan'];validated=parallel.collect(record['path'])
        if validated['numerical_source_graph_sha256']!=record['graph']:
            raise ValueError('executed source graph differs from plan')
        w=spice.Waves(ROOT/validated['waveform']);start=validated['sequence_start_s']+64*250e-12;end=validated['sequence_start_s']+320*250e-12
        clock=clock_metrics.signal_metrics(w,start,end)
        outputs={name:dict(check=out['check'],meets_75mv_015ui_screen=out['meets_spec'],
                           grading_scope=out['grading_scope'],mapping=out['mapping'])
                 for name,out in validated['outputs'].items()}
        interface_ok=bool(validated['input_boundary_ok'] and validated['halfword_hold_ok'] and
                          validated['behavioral_tags_align'] and validated['counter']['counting'])
        serializer_payload_screen=bool(interface_ok and outputs['serializer']['meets_75mv_015ui_screen'] and
                                       outputs['serializer']['mapping']['in_order'])
        cases.append(dict(accepted_words=validated['accepted_words'],actual_capture_edges=validated['actual_capture_edges'],
            interface_ok=interface_ok,serializer_payload_screen=serializer_payload_screen,
            campaign=validated['campaign'],condition=validated['condition'],clock_extra_2g=validated['clock_extra_2g'],
            clock_output_wt=validated['clock_output_wt'],clock_output_r=validated['clock_output_r'],
            numerical_source_graph_sha256=validated['numerical_source_graph_sha256'],hashes=validated['hashes'],
            waveform=validated['waveform'],sequence_start_s=validated['sequence_start_s'],payload_window_s=[float(start),float(end)],
            input_boundary_ok=validated['input_boundary_ok'],halfword_hold_ok=validated['halfword_hold_ok'],
            behavioral_tags_align=validated['behavioral_tags_align'],counter=validated['counter'],clock=clock,outputs=outputs))
    sources=[Path(__file__).resolve(),PARALLEL,CLOCK]+[ROOT/'src/serdes_flow'/x for x in ('serial.py','clock.py','spice.py','waves.py','watch.py','project.py','corners.py')]
    return dict(scope='Two extra-stage settings at TT/FS, WT16/R240, native full-TX dynamic cases. Not 45 PVT, mismatch, noise, PLL or startup qualification.',
        payload_window_definition='actual sequence start + 64 UI through + 320 UI; UI = 250 ps; serializer phase fitted to training only',
        source_graph_sha256=records[0]['graph'],analysis_sources=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in sources],cases=cases)


def draw(data):
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for col,tag in enumerate(('tt_v1800_t27','fs_v1650_t85')):
        cases=sorted((c for c in data['cases'] if c['condition']==tag),key=lambda c:c['clock_extra_2g'])
        labels=[f"extra {c['clock_extra_2g']}" for c in cases];x=np.arange(len(cases))
        a=axes[0,col];a.bar(x,[c['clock']['difference_pp_v']*1000 for c in cases],color=['#376f99','#479c84'])
        for level in (150,200,400):a.axhline(level,color='#ad5c42',ls='--',lw=.8)
        a.set(title=tag+' — clock amplitude',ylabel='Differential pp (mV)',xticks=x,xticklabels=labels);a.grid(axis='y',alpha=.2)
        a=axes[1,col];a.bar(x-.18,[c['outputs']['serializer']['check']['minimum_signed_margin_v']*1000 for c in cases],.36,color='#296d98')
        a.axhline(75,color='#296d98',ls='--',lw=.8);a.set_ylabel('Signed margin (mV)',color='#296d98')
        b=a.twinx();spread=[c['outputs']['serializer']['check']['transition_spread_ui'] for c in cases]
        b.bar(x+.18,[v if v is not None else np.nan for v in spread],.36,color='#cc7843');b.axhline(.15,color='#cc7843',ls='--',lw=.8);b.set_ylabel('Spread (UI)',color='#a75320')
        a.set(title='Serializer + interface screen',xticks=x,xticklabels=labels);a.grid(axis='y',alpha=.2)
        for i,c in enumerate(cases):
            valid=c['serializer_payload_screen']
            a.text(i,.97,'PASS' if valid else 'FAIL',transform=a.get_xaxis_transform(),ha='center',va='top',color='#287748' if valid else '#b22222',fontweight='bold',fontsize=9)
    fig.suptitle('Reduced 2 GHz clock swing: complete TX extra3 vs extra5',fontsize=13)
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--check',action='store_true');group.add_argument('--collect',action='store_true')
    p.add_argument('--campaign',action='append',type=Path,required=True);a=p.parse_args()
    records=preflight(a.campaign)
    if a.check:
        print('Four completed dynamic campaign metadata identities verified; no raw read or output written')
        return
    data=collect(records)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    draw(data);CATALOG.parent.mkdir(parents=True,exist_ok=True)
    CATALOG.write_text(json.dumps(dict(data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),scope=data['scope'],
        figures=[str(FIG.relative_to(ROOT))+'.'+ext for ext in ('png','svg')],campaigns=[c['campaign'] for c in data['cases']]),indent=2)+'\n')
    print(DATA)


if __name__=='__main__':main()
