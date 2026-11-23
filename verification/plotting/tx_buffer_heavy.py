"""Verify raw telemetry and publish the explicit Xe4-width sensitivity card."""
import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, project, spice

ROOT=project.ROOT
RUNNER=ROOT/'analog/tx/input_register/tb/final_clock_chain/buffer_heavy_card.py'
spec=importlib.util.spec_from_file_location('heavy_publish',RUNNER)
card=importlib.util.module_from_spec(spec);spec.loader.exec_module(card)
sha=card.old.digest


def close(actual, expected, label, tolerance=1e-12):
    if not np.isclose(actual,expected,rtol=1e-9,atol=tolerance):
        raise ValueError(f'raw recomputation differs: {label}: {actual} != {expected}')


def average(t,y):
    mask=(t>card.START)&(t<card.END)
    tw=np.r_[card.START,t[mask],card.END]
    yw=np.r_[np.interp(card.START,t,y),y[mask],np.interp(card.END,t,y)]
    return float(np.trapezoid(yw,tw)/(card.END-card.START))


def collect(path):
    camp=path.parents[2];card.check(camp,registered=True)
    summary=json.loads(path.read_text())
    if summary['status']!='measurement_complete' or {r['condition'] for r in summary['rows']}!=set(card.old.TAGS):
        raise ValueError('two complete conditions required')
    if summary['plan_sha256']!=sha(camp/'heavy_plan.json'): raise ValueError('plan changed')
    compact=[]
    for row in summary['rows']:
        tag=row['condition'];raw=card.old.completed(camp,tag)
        if raw is None or raw!=ROOT/row['raw']: raise ValueError('missing/wrong raw')
        for name,expected in row['evidence'].items():
            source=raw if name==raw.name else raw.parent/name
            if sha(source)!=expected: raise ValueError('evidence changed')
        result=row['result'];w=spice.Waves(raw)
        if not result['baseline_matches'] or not result['parent_baseline']['matches']:
            raise ValueError('uncalibrated baseline')
        branches=[];mask=(w.t>=card.START)&(w.t<=card.END)
        for i,b in enumerate(result['branches'],1):
            record=dict(wn_um=b['wn_um'],branch=b['branch'],nodes=b['nodes'],
                        clock_fall_shift_s=b['clock_fall_shift_s'],devices=b['devices'],
                        clock_chain_power_w=b['clock_chain_power_w'],metrics=b['metrics'],
                        local_eye_screen=b['local_eye_screen'],propagation={})
            power=average(w.t,w['vdd']*w[f'i(vsense{i})'])
            close(power,b['clock_chain_power_w']['mean'],'power')
            for node in ('e2','e3','e4'):
                y=w[f'xclock{i}.{node}p']-w[f'xclock{i}.{node}n']
                close(float(np.ptp(y[mask])),b['nodes'][node]['differential_pp_v'],'amplitude')
            for cell in ('xe4','xout'):
                itail=w[f'{cell}_xtail_id_{i}']
                close(average(w.t,itail),b['devices'][cell]['tail_current_a']['mean'],'tail Id')
                head=w[f'xclock{i}.{cell}.xgain.tail']-w[f'{cell}_xtail_vdsat_{i}']
                values=np.r_[np.interp(card.START,w.t,head),head[mask],np.interp(card.END,w.t,head)]
                close(float(values.min()),b['devices'][cell]['tail_headroom_v']['minimum'],'headroom')
            for key,p in b['propagation'].items():
                before,after=key.split('_to_');record['propagation'][key]={}
                yin=w[f'xclock{i}.{before}p']-w[f'xclock{i}.{before}n']
                yout=w[f'xclock{i}.{after}p']-w[f'xclock{i}.{after}n']
                for polarity,label in ((1,'rising'),(-1,'falling')):
                    inp=clock.edges(w.t,yin,polarity,card.START-200e-12,card.END)
                    out=clock.edges(w.t,yout,polarity,card.START,card.END)
                    delay=[]
                    for event in out:
                        hits=inp[(inp<=event)&(inp>=event-200e-12)]
                        if len(hits)!=1: raise ValueError('ambiguous raw delay')
                        delay.append(event-hits[0])
                    close(float(np.mean(delay)),p[label]['mean_s'],'delay',1e-18)
                    if len(delay)!=p[label]['events']: raise ValueError('edge count differs')
                    record['propagation'][key][label]={k:v for k,v in p[label].items()
                        if k not in ('input_times_s','output_times_s','delays_s')}
            samples=np.asarray(b['details']['sample_time_s'])
            # Expected signs come from the immutable boundary, independent of the saved score.
            point=json.loads((camp/'boundary_proposal.json').read_text())['points'][tag]
            bits=np.asarray(point['bits'][296:304])
            signed=np.interp(samples,w.t,w[f'qp{i}']-w[f'qn{i}'])*(2*bits-1)
            close(float(signed.min()),b['metrics']['minimum_signed_margin_v'],'signed margin')
            if int(np.count_nonzero(signed<=0))!=b['metrics']['bit_errors']: raise ValueError('bit errors differ')
            branches.append(record)
        compact.append(dict(condition=tag,raw=row['raw'],evidence=row['evidence'],
                            parent_baseline=result['parent_baseline'],branches=branches))
    return dict(scope=card.SCOPE,status='measured_local_width_sensitivity_only',adopted=False,
                campaign=str(camp.relative_to(ROOT)),summary=str(path.relative_to(ROOT)),summary_sha256=sha(path),
                plan_sha256=sha(camp/'heavy_plan.json'),runner_sha256=sha(RUNNER),
                hypothesis_sha256=sha(camp/'hypothesis.json'),publisher_sha256=sha(Path(__file__)),
                results=compact,ungraded=card.UNGRADED,
                remaining_model_gap='No weak-input/amplitude or independent common-mode sweep; this strong-drive card is not a calibrated complete transfer function.')


def plot(data):
    fig,axes=plt.subplots(2,3,figsize=(13.4,8),layout='constrained')
    for row,color in zip(data['results'],('#3566aa','#c06a38')):
        label='TT 1.8V 27C' if row['condition'].startswith('tt') else 'FS 1.65V 85C'
        bs=row['branches'];x=[b['wn_um'] for b in bs]
        for node,style in (('e3','--'),('e4','-')):
            axes[0,0].plot(x,[b['nodes'][node]['differential_pp_v']*1e3 for b in bs],style+'o',color=color,label=label+' '+node)
        for key,style in (('e2_to_e3','--'),('e3_to_e4','-')):
            delay=np.array([np.mean([p['mean_s'] for p in b['propagation'][key].values()])*1e12 for b in bs])
            axes[0,1].plot(x,delay-delay[0],style+'o',color=color,label=label+' '+key.replace('_to_',' -> '))
        axes[0,2].plot(x,[b['clock_chain_power_w']['mean']*1e3 for b in bs],'-o',color=color,label=label)
        for cell,style in (('xe4','-'),('xout','--')):
            axes[1,0].plot(x,[b['devices'][cell]['tail_headroom_v']['minimum']*1e3 for b in bs],style+'o',color=color,label=label+' '+cell)
        shift=np.array([b['clock_fall_shift_s'] for b in bs])*1e12
        axes[1,1].plot(x,shift-shift[0],'-o',color=color,label=label)
        axes[1,2].plot(x,[b['metrics']['transition_spread_ui'] for b in bs],'-o',color=color,label=label)
    titles=['Larger Xe4 also loads Xe3','Causal stage-delay change','Seven-buffer rail power',
            'Minimum NMOS tail VDS - VDSAT','Loaded c2g falling-edge shift','Eight-bit local transition spread']
    units=['Differential pp (mV)','Change from WN24 (ps)','Mean rail power (mW)',
           'Headroom (mV)','Change from WN24 (ps)','Local spread (UI)']
    for ax,title,unit in zip(axes.flat,titles,units):
        ax.set(title=title,xlabel='Xe4 WN per input MOS (um)',ylabel=unit,xticks=[24,32,40])
        ax.grid(alpha=.2);ax.legend(fontsize=7)
    axes[1,2].axhline(.15,color='#777',ls=':',label='0.15 UI')
    fig.suptitle('TX heavy-stage WN sensitivity: gain, preceding-stage burden, headroom and power',fontsize=13)
    fig.supxlabel('Recorded ideal PWL / generic high_po R tt / legacy driver. Local observations only; no dimensions adopted.',fontsize=9)
    return fig


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',required=True,type=Path);a=p.parse_args()
    path=a.summary.resolve();data=collect(path);camp=ROOT/data['campaign']
    snapshot=camp/'publication_sources'/(sha(Path(__file__))+'.py');snapshot.parent.mkdir(exist_ok=True)
    if not snapshot.exists(): shutil.copyfile(Path(__file__),snapshot)
    data['publisher_snapshot']=str(snapshot.relative_to(ROOT))
    figure=ROOT/'docs/figures/tx/ingress/tx_buffer_heavy.png';fig=plot(data);fig.savefig(figure,dpi=170);plt.close(fig)
    output=ROOT/'docs/data/tx_buffer_heavy.json';output.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    index=dict(data=str(output.relative_to(ROOT)),data_sha256=sha(output),
               figure=str(figure.relative_to(ROOT)),figure_sha256=sha(figure),
               campaign=data['campaign'],summary=data['summary'],summary_sha256=data['summary_sha256'],scope=data['scope'])
    (ROOT/'results/catalog/tx_buffer_heavy.json').write_text(json.dumps(index,indent=2)+'\n')
    for row in data['results']:
        print(row['condition'],row['parent_baseline'])
        for b in row['branches']:
            print(b['wn_um'],'e3/e4 mV',*[round(b['nodes'][n]['differential_pp_v']*1e3,4) for n in ('e3','e4')],
                  'c2g ps',b['clock_fall_shift_s']*1e12,'power mW',b['clock_chain_power_w']['mean']*1e3,
                  'tail mV',b['devices']['xe4']['tail_headroom_v']['minimum']*1e3,
                  'margin mV',b['metrics']['minimum_signed_margin_v']*1e3,'spread',b['metrics']['transition_spread_ui'])


if __name__=='__main__': main()
