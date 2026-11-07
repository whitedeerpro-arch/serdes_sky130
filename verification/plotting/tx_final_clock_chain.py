"""Collect and redraw the final clock-chain comparison; no simulation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

DATA=ROOT/'docs/data/tx_final_clock_chain.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_final_clock_stage_comparison'
CATALOG=ROOT/'results/catalog/tx_final_clock_chain.json'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def collect(camp):
    camp=camp.resolve();plan=json.loads((camp/'plan.json').read_text());summary=json.loads((camp/'summary.json').read_text())
    entry=json.loads((camp/'boundary.json').read_text())
    if hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256']:
        raise ValueError('boundary hash mismatch')
    for rel,digest in plan['sources'].items():
        if sha(camp/'execution'/rel)!=digest:raise ValueError(f'checkpoint mismatch: {rel}')
    rows=summary['rows']
    expected={(tag,int(bit)) for tag,p in entry['points'].items() for bit in p['events']}
    if len(rows)!=len(expected) or {(r['condition'],r['bit']) for r in rows}!=expected or any(r['status']!='measured' for r in rows):
        raise ValueError('all four distinct cases must be measured before raw collection')
    runner=camp/'execution/analog/tx/input_register/tb/final_clock_chain/run.py'
    spec=importlib.util.spec_from_file_location('clock_chain_snapshot',runner);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.verify(entry)
    results=[]
    for row in rows:
        raw=ROOT/row['waveform'];tag=row['condition'];bit=row['bit']
        if sha(raw)!=row['waveform_sha256']:raise ValueError(f'raw changed: {raw}')
        module.helper.validate_execution(raw)
        checked=module.measure(raw,row,entry)
        point=entry['points'][tag];event=point['events'][str(bit)];origin=event['origin_s'];edge=event['selection_edge_s']
        source=json.loads((ROOT/point['source_campaign']/'summary.json').read_text())
        trace=spice.Waves(ROOT/point['raw']);w=spice.Waves(raw)
        if w.t[-1]<plan['stop_s']*(1-1e-6):raise ValueError('truncated raw')
        clock=trace['xtx.xtree.xr4_0.sap']-trace['xtx.xtree.xr4_0.san']
        times,pol=crossings(trace.t,clock);choices=times[(pol==-1)&(times>=edge)&(times<=edge+.5e-9)]
        if not len(choices):raise ValueError('source local A close missing')
        close=float(choices[0])-origin
        sign=1 if (event['source_word']>>(bit%16))&1 else -1
        training=source['sequence_start_s']+(bit+.5+source['outputs']['serializer']['check']['training_delay_ui'])*250e-12-origin
        falls=[]
        for i in (1,2,3):
            times,pol=crossings(w.t,w[f'sp{i}']-w[f'sn{i}'])
            candidates=times[(pol==-1)&(times>=4e-9)&(times<=4.5e-9)]
            if not len(candidates):raise ValueError(f'first falling c2g missing: {tag} bit {bit} count{i}')
            falls.append(float(candidates[0]))
        stages=[]
        for i,fall in enumerate(falls,1):
            delta=fall-falls[0];sample=training+delta;held=close+delta+200e-12
            if any(t<3.5e-9 or t>5.8e-9 for t in (sample,held)):
                raise ValueError('sample outside fixed 3.5–5.8 ns evaluation window')
            at=lambda n,t:float(np.interp(t,w.t,w[n]))
            keep=(w.t>=3.5e-9)&(w.t<=5.8e-9);diff=w[f'sp{i}'][keep]-w[f'sn{i}'][keep]
            stages.append(dict(extra_stage_count=i,total_buffers=i+2,c2g_fall_s=fall,
                c2g_fall_shift_ps=delta*1e12,c2g_differential_pp_mv=float(np.ptp(diff)*1000),
                shifted_training_sample_s=sample,
                signed_output_at_shifted_training_center_mv=1000*sign*(at(f'qp{i}',sample)-at(f'qn{i}',sample)),
                estimated_a_close_plus_200ps_s=held,
                signed_held_a_at_estimated_close_plus_200ps_mv=1000*sign*(at(f'xslice{i}.xfinal.ahp',held)-at(f'xslice{i}.xfinal.ahn',held))))
        results.append(dict(condition=tag,bit=bit,slot=event['slot'],source_word=event['source_word'],expected_bit=(sign+1)//2,
            source_trace=point['raw'],source_trace_sha256=point['raw_sha256'],waveform=row['waveform'],waveform_sha256=row['waveform_sha256'],
            count1_baseline_matches=checked['baseline_matches'],count1_baseline_error_v=checked['baseline_max_error_v'],
            input_max_error_v=checked['input_max_error_v'],original_local_a_close_relative_s=close,
            source_training_sample_relative_s=training, stages=stages,
            interpretation='ungraded local comparison' if checked['baseline_matches'] else 'baseline failed; candidate branches are not interpretable'))
    return dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),summary_sha256=sha(camp/'summary.json'),
                boundary_sha256=plan['boundary_sha256'],collector_sha256=sha(Path(__file__)),events=results,
                scope='Two events each at TT and FS; ideal voltage sources omit upstream impedance and feedback. Ungraded local study; no full-bit, 45-PVT, mismatch or noise qualification.',
                method='Count1/2/3 means 1/2/3 extra buffers before output buffer. Phase is measured first falling c2g within 4–4.5ns minus count1. Output sample is original fixed training center plus measured phase; held-A time uses original actual close plus phase plus 200ps and is estimated, not measured candidate close. Last 200ps excluded.')


def draw(data):
    fig,axes=plt.subplots(2,2,figsize=(11,7),sharex=True,constrained_layout=True)
    for ax,event in zip(axes.flat,data['events']):
        stages=event['stages'];x=[s['extra_stage_count'] for s in stages]
        ax.plot(x,[s['signed_output_at_shifted_training_center_mv'] for s in stages],marker='o',label='output at shifted training center')
        ax.plot(x,[s['signed_held_a_at_estimated_close_plus_200ps_mv'] for s in stages],marker='s',label='held A at estimated close + 200 ps')
        ax.axhline(0,color='black',lw=.7);ax.grid(alpha=.25);ax.set_xticks([1,2,3]);ax.set_xlabel('Extra clock buffer stages')
        ax.set_ylabel('Expected-polarity differential (mV)')
        status='' if event['count1_baseline_matches'] else ' — BASELINE FAILED'
        ax.set_title(f"{event['condition']} bit {event['bit']}{status}")
        for s in stages:ax.annotate(f"Δ {s['c2g_fall_shift_ps']:+.0f} ps",(s['extra_stage_count'],s['signed_output_at_shifted_training_center_mv']),xytext=(0,7),textcoords='offset points',ha='center',fontsize=8)
    axes.flat[0].legend(fontsize=8)
    fig.suptitle('Final clock chain: actual c2g phase and conditional fixed-training output sample',fontsize=10)
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--collect',type=Path);p.add_argument('--data',type=Path,default=DATA);a=p.parse_args()
    if a.collect:
        data=collect(a.collect);a.data.parent.mkdir(parents=True,exist_ok=True);a.data.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    else:data=json.loads(a.data.read_text())
    draw(data)
    CATALOG.parent.mkdir(parents=True,exist_ok=True)
    CATALOG.write_text(json.dumps(dict(data=str(a.data.relative_to(ROOT)),data_sha256=sha(a.data),source_campaign=data['campaign'],
        figures=[str(FIG.relative_to(ROOT))+'.'+x for x in ('png','svg')],collector_sha256=sha(Path(__file__)),scope=data['scope']),indent=2)+'\n')


if __name__=='__main__':main()
