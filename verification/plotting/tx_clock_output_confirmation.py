"""Collect four completed full-TX runs and compare 2 GHz output sizing, without simulation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import clock, spice, watch
from serdes_flow.project import ROOT
from serdes_flow.waves import time_average

COLLECTOR=ROOT/'verification/plotting/tx_parallel_serializer.py'
spec=importlib.util.spec_from_file_location('parallel_serializer_collector',COLLECTOR)
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)
DATA=ROOT/'docs/data/tx_clock_output_confirmation.json'
CATALOG=ROOT/'results/catalog/tx_clock_output_confirmation.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_clock_output_full_confirmation'
UI=250e-12
EXPECTED={('tt_v1800_t27',24,300),('tt_v1800_t27',16,240),('fs_v1650_t85',24,300),('fs_v1650_t85',16,240)}


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def signal_metrics(w,start,end):
    if w.t[0]>start or w.t[-1]<end:raise ValueError('payload window not fully covered')
    inside=(w.t>start)&(w.t<end)
    t=np.r_[start,w.t[inside],end]
    p=np.interp(t,w.t,w['c2gp']);n=np.interp(t,w.t,w['c2gn']);diff=p-n;cm=(p+n)/2
    rise=clock.edges(t,diff,1,start,end);fall=clock.edges(t,diff,-1,start,end)
    stats=clock.period_stats(t,diff,start,end)
    cycles=clock.cycle_amplitudes(t,diff,start,end)
    periods={}
    for name,es in (('rising',rise),('falling',fall)):
        if len(es)>=2:
            delta=np.diff(es)
            periods[name]=dict(count=len(delta),min_s=float(np.min(delta)),max_s=float(np.max(delta)),
                               max_abs_error_fraction=float(np.max(np.abs(delta/.5e-9-1))))
        else:periods[name]=None
    return dict(window_s=[float(start),float(end)],difference_pp_v=float(np.ptp(diff)),
                positive_single_ended_pp_v=float(np.ptp(p)),negative_single_ended_pp_v=float(np.ptp(n)),
                common_mode_v=dict(min=float(np.min(cm)),max=float(np.max(cm)),mean=float(time_average(cm,t))),
                rising_edges=len(rise),falling_edges=len(fall),period_stats=stats,periods_by_polarity=periods,cycle_amplitudes=cycles,
                expected_cycles=(end-start)/.5e-9,
                edge_count_screen=bool(abs(len(rise)-(end-start)/.5e-9)<=1 and abs(len(fall)-(end-start)/.5e-9)<=1),
                period_error_lt_one_percent=bool(all(value is not None and value['max_abs_error_fraction']<.01 for value in periods.values())),
                clock_amplitude_screen_150_to_400mv=(bool(cycles['min_pp_v']>=.15 and np.ptp(diff)<=.4) if cycles is not None else None),
                clock_design_target_at_least_200mv=(bool(cycles['min_pp_v']>=.2) if cycles is not None else None),
                screen_scope='observed payload window only; edge counts and period errors reported, not full-PVT qualification')


def collect(camps):
    if len(camps)!=4 or len({p.resolve() for p in camps})!=4:raise ValueError('require four distinct campaigns')
    paths=[p.resolve() for p in camps]
    alive=watch.ngspice_cwds()
    # Check every case before opening any raw, so a live/incomplete set never creates partial data.
    for camp in paths:
        if not (camp/'summary.json').is_file():raise ValueError(f'campaign pending: {camp}')
        if any(p.is_relative_to(camp) for p in alive):raise ValueError(f'campaign still has active ngspice: {camp}')
    cases=[]
    for camp in paths:
        validated=collector.collect(camp)
        if validated['clock_extra_2g']!=3:raise ValueError('all cases must have extra2g=3')
        key=(validated['condition'],validated['clock_output_wt'],validated['clock_output_r'])
        if key not in EXPECTED:raise ValueError(f'unexpected condition or output sizing: {key}')
        w=spice.Waves(ROOT/validated['waveform'])
        start=validated['sequence_start_s']+64*UI;end=validated['sequence_start_s']+320*UI
        metrics=signal_metrics(w,start,end)
        output=validated['outputs']['serializer']
        check=output['check']
        cases.append(dict(campaign=validated['campaign'],condition=validated['condition'],clock_extra_2g=3,
            clock_output_wt=validated['clock_output_wt'],clock_output_r=validated['clock_output_r'],
            waveform=validated['waveform'],hashes=validated['hashes'],sequence_start_s=validated['sequence_start_s'],
            payload_window_s=[float(start),float(end)],clock=metrics,
            serializer=dict(check=check,meets_spec=output['meets_spec'],mapping=output['mapping']),
            input_boundary_ok=validated['input_boundary_ok'],halfword_hold_ok=validated['halfword_hold_ok'],
            behavioral_tags_align=validated['behavioral_tags_align'],counter=validated['counter']))
    if {(c['condition'],c['clock_output_wt'],c['clock_output_r']) for c in cases}!=EXPECTED:
        raise ValueError('missing or duplicate configuration')
    sources=[Path(__file__).resolve(),COLLECTOR]+[ROOT/'src/serdes_flow'/x for x in ('serial.py','clock.py','spice.py','waves.py','project.py','corners.py','watch.py')]
    return dict(scope='TT and FS, extra2g=3, two full-TX output sizes, ideal 2 GHz input and real bias; no 45-PVT, mismatch, noise, PLL or startup qualification. Clock amplitude screen alone does not close I-17.',
        payload_window_definition='Actual selected sequence start + 64 UI through + 320 UI, UI=250 ps; fixed training-only serializer phase.',
        analysis_sources=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in sources],cases=cases)


def draw(data):
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for col,tag in enumerate(('tt_v1800_t27','fs_v1650_t85')):
        cases=sorted((c for c in data['cases'] if c['condition']==tag),key=lambda c:-c['clock_output_wt'])
        labels=[f"wt {c['clock_output_wt']:g} / R {c['clock_output_r']:g}" for c in cases];x=np.arange(2)
        a=axes[0,col];a.bar(x,[c['clock']['difference_pp_v']*1000 for c in cases],color=['#436f94','#499d86'])
        for val in (150,200,400):a.axhline(val,color='#b45a3c',ls='--',lw=.7);a.text(1.55,val,str(val),fontsize=7,va='bottom')
        a.set(title=tag+' — c2g payload-window amplitude',ylabel='Differential peak-to-peak (mV)',xticks=x,xticklabels=labels);a.grid(axis='y',alpha=.2)
        a=axes[1,col];a.bar(x-.18,[c['serializer']['check']['minimum_signed_margin_v']*1000 for c in cases],.36,color='#296d98',label='Signed margin (mV)')
        a.axhline(75,color='#296d98',ls='--',lw=.8);a.set_ylabel('Signed margin (mV)',color='#296d98')
        b=a.twinx();b.bar(x+.18,[c['serializer']['check']['transition_spread_ui'] or 0 for c in cases],.36,color='#cc7843',label='Spread (UI)')
        b.axhline(.15,color='#cc7843',ls='--',lw=.8);b.set_ylabel('Edge spread (UI)',color='#a75320')
        a.set(title='Serializer eye gates',xticks=x,xticklabels=labels);a.grid(axis='y',alpha=.2)
    fig.suptitle('Full TX: loaded 2 GHz output sizing at TT and FS',fontsize=13)
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--collect',action='store_true',help='write collected data and figures');p.add_argument('--campaign',type=Path,action='append',required=True);a=p.parse_args()
    if not a.collect:p.error('explicit --collect required to write outputs')
    data=collect(a.campaign)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    draw(data);CATALOG.parent.mkdir(parents=True,exist_ok=True)
    CATALOG.write_text(json.dumps(dict(data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),scope=data['scope'],
        figures=[str(FIG.relative_to(ROOT))+'.'+x for x in ('png','svg')],campaigns=[c['campaign'] for c in data['cases']]),indent=2)+'\n')
    print(DATA)


if __name__=='__main__':main()
