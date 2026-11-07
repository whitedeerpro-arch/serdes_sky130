"""Collect loaded final-clock output sizing events; no simulations are run."""
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
from serdes_flow.waves import crossings, time_average

DATA=ROOT/'docs/data/tx_final_clock_swing.json'
CATALOG=ROOT/'results/catalog/tx_final_clock_swing.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_final_clock_output_sizing'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def equal(a,b):
    if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
    if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool):
        return bool(np.isclose(a,b,rtol=1e-9,atol=1e-12))
    return a==b


def range_stats(t,v):
    return dict(min_v=float(np.min(v)),max_v=float(np.max(v)),mean_v=float(time_average(v,t)),pp_v=float(np.ptp(v)))


def event_crossings(t,y,lo,hi,polarity):
    times,pol=crossings(t,y)
    return times[(pol==polarity)&(times>=lo)&(times<=hi)]


def collect(camp):
    camp=camp.resolve();summary_path=camp/'summary.json'
    if not summary_path.exists():raise ValueError('campaign summary missing; no output written')
    plan=json.loads((camp/'plan.json').read_text());summary=json.loads(summary_path.read_text());entry=json.loads((camp/'boundary.json').read_text())
    if hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256']:raise ValueError('boundary hash mismatch')
    for rel,digest in plan['snapshots'].items():
        if sha(camp/rel)!=digest:raise ValueError(f'snapshot mismatch: {rel}')
    rows=summary['rows'];expected={(r['condition'],r['bit']) for r in plan['cases']}
    if len(rows)!=len(expected) or {(r['condition'],r['bit']) for r in rows}!=expected or any(r['status']!='measured' for r in rows):
        raise ValueError('all planned distinct cases must finish before reading raw')
    runner=camp/'execution/analog/tx/input_register/tb/final_clock_chain/output_swing.py'
    spec=importlib.util.spec_from_file_location('output_swing_snapshot',runner);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    checked_plan,checked_entry=module.verify(camp)
    if checked_plan!=plan or checked_entry!=entry:raise ValueError('campaign identity mismatch')
    base=module.boundary.get(module.BASE_ID);results=[]
    for row in rows:
        tag=row['condition'];bit=row['bit'];raw=ROOT/row['waveform']
        if sha(raw)!=row['waveform_sha256']:raise ValueError(f'waveform changed: {raw}')
        module.parent.helper.validate_execution(raw)
        if module.spice.case_output(camp,row['name'],row['name']+'.raw',plan['stop_s'])!=raw:
            raise ValueError('waveform missing or truncated')
        metrics=module.measure(raw,row,entry)
        if not equal(metrics,row['metrics']):raise ValueError('independent baseline/input measurement differs from summary')
        if not metrics['baseline_matches'] or max(metrics['baseline_max_error_v'].values())>.005:
            raise ValueError(f'{tag} bit {bit}: baseline mismatch; candidate interpretation refused')
        if max(metrics['input_max_error_v'].values())>200e-6:raise ValueError('input replay mismatch')
        point=base['points'][tag];event=point['events'][str(bit)];origin=event['origin_s']
        source=json.loads((ROOT/point['source_campaign']/'summary.json').read_text())
        sign=1 if (event['source_word']>>(bit%16))&1 else -1
        training=source['sequence_start_s']+(bit+.5+source['outputs']['serializer']['check']['training_delay_ui'])*250e-12-origin
        source_rows=json.loads((module.SOURCE/'summary.json').read_text())['rows']
        source_row=next(r for r in source_rows if r['condition']==tag and r['bit']==bit)
        source_wave=spice.Waves(ROOT/source_row['waveform'])
        source_first=event_crossings(source_wave.t,source_wave['sp1']-source_wave['sn1'],4e-9,4.5e-9,-1)
        if len(source_first)!=1:raise ValueError('source count1 falling edge absent or non-unique; phase cannot be interpreted')
        source_fall=float(source_first[0])
        w=spice.Waves(raw);keep=(w.t>=3.5e-9)&(w.t<=5.8e-9);tt=w.t[keep]
        if len(tt)<2:raise ValueError('evaluation window empty')
        ap=w['ap'];an=w['an'];target=event_crossings(w.t,ap-an,4e-9,4.5e-9,sign)
        # Crossing is reported only when uniquely attributable to this target event.
        target_time=float(target[0]) if len(target)==1 else None
        falls=[]
        for i in (1,2,3):
            t=event_crossings(w.t,w[f'sp{i}']-w[f'sn{i}'],4e-9,4.5e-9,-1)
            falls.append(float(t[0]) if len(t)==1 else None)
        branches=[]
        for i,fall in enumerate(falls,1):
            sp=w[f'sp{i}'];sn=w[f'sn{i}'];diff=sp-sn;cm=(sp+sn)/2
            delta=fall-falls[0] if fall is not None and falls[0] is not None else None
            sample=training+(fall-source_fall) if fall is not None else None
            closes=event_crossings(w.t,w[f'xslice{i}.xfinal.sap']-w[f'xslice{i}.xfinal.san'],4e-9,4.5e-9,-1)
            close=float(closes[0]) if len(closes)==1 else None
            if sample is not None and not (3.5e-9<=sample<=5.8e-9):raise ValueError('training sample outside fixed window')
            at=lambda v,t:float(np.interp(t,w.t,v))
            held=w[f'xslice{i}.xfinal.ahp']-w[f'xslice{i}.xfinal.ahn']
            if close is not None and close+200e-12>5.8e-9:raise ValueError('held sample outside fixed window')
            branch=dict(branch=i,parameters=entry['params'][i-1],c2g_p=range_stats(tt,sp[keep]),c2g_n=range_stats(tt,sn[keep]),
                c2g_differential=range_stats(tt,diff[keep]),c2g_common_mode=range_stats(tt,cm[keep]),
                c2g_fall_s=fall,c2g_fall_delta_ps=delta*1e12 if delta is not None else None,
                source_count1_to_candidate_fall_delta_ps=(fall-source_fall)*1e12 if fall is not None else None,
                shifted_training_sample_s=sample,signed_output_at_shifted_training_center_mv=1000*sign*at(w[f'qp{i}']-w[f'qn{i}'],sample) if sample is not None else None,
                timing_status='interpretable' if fall is not None and close is not None else 'uninterpretable: c2g fall or A close absent or non-unique',
                actual_local_a_close_s=close,g3_target_cross_s=target_time,
                g3_target_cross_minus_actual_close_ps=(target_time-close)*1e12 if target_time is not None and close is not None else None,
                signed_g3_at_actual_close_mv=1000*sign*at(ap-an,close) if close is not None else None,
                signed_held_a_200ps_after_actual_close_mv=1000*sign*at(held,close+200e-12) if close is not None else None,
                tail_voltage=range_stats(tt,w[f'xclock{i}.xout.xgain.tail'][keep]),
                bias_voltage=range_stats(tt,w['vbias'][keep]),
                e3p_voltage=range_stats(tt,w[f'xclock{i}.e3p'][keep]),e3n_voltage=range_stats(tt,w[f'xclock{i}.e3n'][keep]),
                tail_status='ungraded; no Vdsat measurement')
            branches.append(branch)
        results.append(dict(condition=tag,bit=bit,slot=event['slot'],source_word=event['source_word'],expected_bit=(sign+1)//2,
            source_trace=point['raw'],source_trace_sha256=point['raw_sha256'],waveform=row['waveform'],waveform_sha256=row['waveform_sha256'],
            source_parent_waveform=source_row['waveform'],source_parent_waveform_sha256=source_row['waveform_sha256'],
            execution_sha256=sha(raw.parent/'execution.json'),deck_sha256=sha(raw.parent/'tb.cir'),
            target_crossing_candidates_s=target.tolist(),training_center_s=training,source_count1_c2g_fall_s=source_fall,baseline=metrics,branches=branches))
    return dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),summary_sha256=sha(summary_path),
        boundary_sha256=plan['boundary_sha256'],collector_sha256=sha(Path(__file__)),events=results,
        scope='Local ungraded TT/FS two-event ideal-voltage replay without upstream source impedance or feedback; not full-bit, full-TX, 45-PVT, mismatch or noise qualification.',
        method='3.5–5.8 ns. c2g falling edge requires exactly one fall in 4–4.5 ns; output sampling is fixed source training center plus measured candidate c2g fall minus source count1 fall, including the original extra1-to-extra3 delay. Actual A close requires exactly one sap-san fall within 4–4.5 ns. Target g3 crossing requires exactly one expected-polarity crossing in that interval. No fitted payload phase or claimed setup margin.')


def draw(data):
    fig,axes=plt.subplots(4,2,figsize=(11,12),layout='constrained')
    for idx,event in enumerate(data['events']):
        branches=event['branches'];x=np.arange(3);labels=[f"{b['parameters']['wt']}/{b['parameters']['rload']}" for b in branches]
        a,b=axes[idx];a.bar(x,[1000*s['c2g_differential']['pp_v'] for s in branches],color='#28789d')
        for level in (150,200,400):a.axhline(level,color='#a55b44',lw=.7,ls='--');a.text(2.55,level,str(level),fontsize=7,va='bottom')
        a.set_ylabel('c2g differential pp (mV)');a.set_title(f"{event['condition']} bit {event['bit']}")
        b.bar(x,[s['signed_output_at_shifted_training_center_mv'] if s['signed_output_at_shifted_training_center_mv'] is not None else np.nan for s in branches],color='#6a9c72');b.axhline(0,color='black',lw=.7)
        b.set_ylabel('Signed output (mV)');b.set_title('Fixed training sample + measured phase')
        for ax in (a,b):ax.set_xticks(x,labels);ax.set_xlabel('Output wt / R');ax.grid(axis='y',alpha=.2)
    fig.suptitle('Loaded final clock output: local ungraded event comparison (wn = 32)',fontsize=12)
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,required=True);a=p.parse_args()
    data=collect(a.campaign)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    draw(data);CATALOG.parent.mkdir(parents=True,exist_ok=True)
    CATALOG.write_text(json.dumps(dict(campaign=data['campaign'],data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),
        figures=[str(FIG.relative_to(ROOT))+'.'+x for x in ('png','svg')],scope=data['scope']),indent=2)+'\n')
    print(DATA)


if __name__=='__main__':main()
