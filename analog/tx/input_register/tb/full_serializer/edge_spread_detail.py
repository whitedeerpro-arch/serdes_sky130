"""Compare two native FS word-18 halfword events on their actual c250 edge."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import clock,spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings,time_average

BASE=Path(__file__).resolve().parent/'edge_spread_review.py'
spec=importlib.util.spec_from_file_location('edge_review',BASE);review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)
DATA=ROOT/'docs/data/tx_clock_output_edge_detail.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_clock_output_edge_detail.png'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def build(camp):
    case=review.analyse(camp);camp=camp.resolve()
    if case['condition']!='fs_v1650_t85' or case['clock_extra_2g']!=3:raise ValueError('requires FS extra3 run')
    summary=json.loads((camp/'summary.json').read_text());rows=[r for r in summary['captures'] if r['payload_valid']]
    if len(rows)<=18 or rows[18]['word']!=0xdad9:
        raise ValueError('this diagnostic requires recorded word 18 = 0xdad9')
    row=rows[18];w=spice.Waves(ROOT/summary['waveform'])
    a=clock.edges(w.t,w['c250p']-w['c250n'],-1);b=clock.edges(w.t,w['c250p']-w['c250n'],1)
    af=a[a>=row['capture_s']];bf=b[b>af[0]] if len(af) else []
    if not len(bf):raise ValueError('actual halfword selection absent')
    edge=float(bf[0]);lo=edge-.2e-9;hi=edge+2.2e-9
    if w.t[0]>lo or w.t[-1]<hi:raise ValueError('window not covered')
    select=(w.t>=lo)&(w.t<=hi);t=w.t[select]
    signals=dict(g3=w['xtx.xtree.g3_0p']-w['xtx.xtree.g3_0n'],c2g=w['c2gp']-w['c2gn'],
                 sap=w['xtx.xtree.xr4_0.sap']-w['xtx.xtree.xr4_0.san'],
                 held=w['xtx.xtree.xr4_0.ahp']-w['xtx.xtree.xr4_0.ahn'],output=w['qp']-w['qn'])
    transition={r['bit']:r for r in case['transitions']};events=[]
    g3_cross,g3_pol=crossings(w.t,signals['g3'])
    held_cross,held_pol=crossings(w.t,signals['held'])
    close_times,close_pol=crossings(w.t,signals['sap'])
    falls=close_times[(close_pol==-1)&(close_times>=edge)&(close_times<=edge+2e-9)]
    if len(falls)!=4:raise ValueError('expected four actual A closes in halfword window')
    for bit in (296,302):
        slot=bit%16;previous_even_slot=slot-2 if slot>=2 else slot+14
        expected=(row['word']>>slot)&1;previous_even=(row['word']>>previous_even_slot)&1
        sign=2*expected-1;close_index=(slot-8)//2;c=float(falls[close_index])
        record=dict(bit=bit,slot=slot,expected_bit=expected,previous_even_bit=bit-2,
                    previous_even_slot=previous_even_slot,previous_even_value=previous_even,
                    g3_input_changes=(expected!=previous_even),actual_a_close_ps=float((c-edge)*1e12),
                    output_transition=transition[bit],
                    signed_g3_at_close_mv=float(1000*sign*np.interp(c,w.t,signals['g3'])),
                    signed_held_200ps_after_close_mv=float(1000*sign*np.interp(c+200e-12,w.t,signals['held'])))
        if bit==296:
            hit=g3_cross[(g3_pol==sign)&(g3_cross>=edge)&(g3_cross<=edge+.5e-9)]
            record['target_crossing_search_ps']=[0,500];record['target_crossings_ps']=((hit-edge)*1e12).tolist()
            if len(hit)==1 and previous_even!=expected:
                record['target_crossing_ps']=float((hit[0]-edge)*1e12)
                record['cross_minus_close_ps']=float((hit[0]-c)*1e12)
                held_hit=held_cross[(held_pol==sign)&(held_cross>=hit[0])&(held_cross<=hit[0]+.3e-9)]
                record['held_target_crossing_candidates_ps']=((held_hit-edge)*1e12).tolist()
                if len(held_hit)==1:record['g3_to_held_crossing_ps']=float((held_hit[0]-hit[0])*1e12)
        else:
            previous_close=float(falls[close_index-1])
            hits=g3_cross[(g3_cross>previous_close)&(g3_cross<=c)]
            record['g3_crossings_since_previous_even_close_ps']=((hits-edge)*1e12).tolist()
            record['g3_target_crossing_ps']=None
            record['g3_to_held_crossing_ps']=None
            record['g3_transition_status']='unchanged from slot12; no attributable new slot14 transition' if expected==previous_even else 'ungraded: changed input requires separate event attribution'
            record['held_transition_status']='ungraded for slot14: earlier slot12 response can overlap prior close'
            previous_hits=g3_cross[(g3_pol==sign)&(g3_cross>=edge+1e-9)&(g3_cross<=edge+1.5e-9)]
            record['previous_even_slot12_expected_crossing_candidates_ps']=((previous_hits-edge)*1e12).tolist()
        events.append(record)
    window=(w.t>=edge)&(w.t<=edge+2e-9);cm=(w['c2gp']+w['c2gn'])/2
    envelope=clock.cycle_amplitudes(w.t,signals['c2g'],edge,edge+2e-9)
    return dict(condition=case['condition'],campaign=case['campaign'],clock_output_wt=case['clock_output_wt'],clock_output_r=case['clock_output_r'],
        hashes=case['hashes'],word_index=18,source_word=row['word'],halfword_b_edge_s=edge,
        serializer_training_delay_ui=case['metrics']['training_delay_ui'],events=events,
        c2g_window_s=[edge,edge+2e-9],c2g_complete_cycle_amplitudes=envelope,
        c2g_differential_overall_pp_v=float(np.ptp(signals['c2g'][window])),
        c2g_cm_v=dict(min=float(np.min(cm[window])),max=float(np.max(cm[window])),mean=float(time_average(cm[window],w.t[window])))), \
        (t-edge,{k:v[select] for k,v in signals.items()})


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,action='append',required=True);a=p.parse_args()
    if len(a.campaign)!=2:raise ValueError('need exactly two campaigns')
    values=[build(p) for p in a.campaign];cases=[v[0] for v in values]
    if {(c['clock_output_wt'],c['clock_output_r']) for c in cases}!={(16,240),(24,300)}:raise ValueError('need both output sizes')
    if cases[0]['source_word']!=cases[1]['source_word']:raise ValueError('source words differ')
    out=ROOT/'results/analog/tx/edge_spread_detail'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True,exist_ok=False)
    sources=[Path(__file__).resolve(),BASE,review.COLLECTOR]+[ROOT/'src/serdes_flow'/x for x in ('serial.py','clock.py','spice.py','waves.py','project.py','corners.py')]
    identities={}
    for src in sources:
        dest=out/'execution'/src.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest);identities[str(src.relative_to(ROOT))]=sha(dest)
    data=dict(scope='FS 1.65 V 85 °C two native runs; aligned to their own actual B halfword edge; no causal claim or full PVT qualification.',
              definitions='Bit296 g3 crossing uses 0–500 ps after B edge. A closes are four observed sap-san falls in the B halfword; slot14 uses the fourth, three cycles after slot8. Slot14 and preceding even slot12 both carry 1, so the 1000–1500 ps g3 crossing is associated with prior slot12, not a new slot14 transition. Output residuals use each run’s training phase.',
              analysis_sources=identities,cases=cases)
    text=json.dumps(data,indent=2,allow_nan=False)+'\n';(out/'detail.json').write_text(text)
    fig,axes=plt.subplots(4,1,figsize=(11,9),sharex=True,layout='constrained')
    for case,(dt,signals) in values:
        label=f"wt {case['clock_output_wt']:g} / R {case['clock_output_r']:g}"
        style='-' if case['clock_output_wt']==16 else '--'
        for ax,key in zip(axes,('g3','held','output')):ax.plot(dt*1e12,signals[key]*1000,ls=style,label=label,lw=1)
        axes[3].plot(dt*1e12,signals['c2g']*1000,ls=style,label=label+' c2g',lw=1)
        axes[3].plot(dt*1e12,signals['sap']*1000,ls=style,label=label+' sap−san',lw=.8,alpha=.75)
        for event in case['events']:
            if 'target_crossing_ps' in event:axes[0].axvline(event['target_crossing_ps'],color='green',alpha=.35,ls=style)
            axes[3].axvline(event['actual_a_close_ps'],color='red',alpha=.35,ls=style)
            if event['bit']==302:
                for crossing in event['previous_even_slot12_expected_crossing_candidates_ps']:
                    axes[0].axvline(crossing,color='orange',alpha=.35,ls=style)
    for ax,name in zip(axes,('g3_0','held A','qp−qn','c2g / local A select')):
        ax.axhline(0,color='gray',lw=.5);ax.set_ylabel(name+' (mV)');ax.grid(alpha=.2)
    axes[0].legend(fontsize=8);axes[3].legend(fontsize=7,ncol=2);axes[-1].set_xlabel('ps relative to each run’s actual c250 B edge')
    fig.suptitle('FS word 18: green = slot8 g3 crossing; orange = prior slot12; red = slot8/14 A close')
    fig.savefig(out/'detail.png',dpi=160);plt.close(fig)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(text)
    FIG.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(out/'detail.png',FIG)
    print(out)


if __name__=='__main__':main()
