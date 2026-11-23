"""Inspect native extra2g candidate events, without simulation or phase fitting."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import clock, spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

COLLECTOR=ROOT/'verification/plotting/tx_parallel_serializer.py'
spec=importlib.util.spec_from_file_location('parallel_serializer_collector',COLLECTOR)
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def inspect(camp):
    valid=collector.collect(camp)
    camp=camp.resolve();plan=json.loads((camp/'plan.json').read_text());summary=json.loads((camp/'summary.json').read_text())
    path=ROOT/valid['waveform'];w=spice.Waves(path)
    names={'g3p':'xtx.xtree.g3_0p','g3n':'xtx.xtree.g3_0n',
           'sap':'xtx.xtree.xr4_0.sap','san':'xtx.xtree.xr4_0.san',
           'ahp':'xtx.xtree.xr4_0.ahp','ahn':'xtx.xtree.xr4_0.ahn',
           'c250p':'c250p','c250n':'c250n','qp':'qp','qn':'qn'}
    try: signals={name:w[node] for name,node in names.items()}
    except KeyError as e:
        return dict(condition=plan['condition'],campaign=str(camp.relative_to(ROOT)),hashes=valid['hashes'],
                    covered=False,reason=f'required internal node missing: {e}',events=[]),None
    rows=[r for r in summary['captures'] if r['payload_valid']]
    falls=clock.edges(w.t,signals['c250p']-signals['c250n'],-1)
    rises=clock.edges(w.t,signals['c250p']-signals['c250n'],1)
    local=signals['sap']-signals['san']; g3=signals['g3p']-signals['g3n']
    held=signals['ahp']-signals['ahn'];output=signals['qp']-signals['qn']
    lt,lp=crossings(w.t,local);gt,gp=crossings(w.t,g3)
    events=[]
    for bit in (48,104,232):
        word=bit//16; item=dict(bit=bit,slot=bit%16,covered=False)
        if word>=len(rows):item['reason']='capture word absent';events.append(item);continue
        row=rows[word];sign=1 if (row['word']>>(bit%16))&1 else -1
        a=falls[falls>=row['capture_s']]
        if not len(a):item['reason']='A edge absent';events.append(item);continue
        b=rises[rises>a[0]]
        if not len(b):item['reason']='B edge absent';events.append(item);continue
        edge=float(a[0] if bit%16<8 else b[0]);sample=valid['sequence_start_s']+(bit+.5+summary['outputs']['serializer']['check']['training_delay_ui'])*250e-12
        closes=lt[(lp==-1)&(lt>=edge)&(lt<=edge+.5e-9)]
        target=gt[(gp==sign)&(gt>=edge)&(gt<=edge+.5e-9)]
        item.update(source_word=row['word'],expected_bit=(sign+1)//2,halfword_edge_s=edge,
                    halfword_selection='A_fall' if bit%16<8 else 'B_rise',
                    target_crossing_candidates_s=target.tolist(),local_a_fall_candidates_s=closes.tolist(),output_training_sample_s=sample)
        if len(target)!=1 or len(closes)!=1 or sample>w.t[-1] or closes[0]+200e-12>w.t[-1]:
            item['reason']='target crossing non-unique/absent, local close non-unique/absent, or sample outside waveform';events.append(item);continue
        close=float(closes[0]);cross=float(target[0]);interp=lambda y,t:float(np.interp(t,w.t,y))
        item.update(covered=True,g3_target_cross_s=cross,local_a_close_s=close,
                    cross_minus_close_ps=(cross-close)*1e12,
                    signed_g3_at_close_mv=1000*sign*interp(g3,close),
                    signed_held_a_200ps_after_close_mv=1000*sign*interp(held,close+200e-12),
                    signed_output_at_fixed_training_center_mv=1000*sign*interp(output,sample))
        events.append(item)
    return dict(condition=plan['condition'],campaign=str(camp.relative_to(ROOT)),clock_extra_2g=valid['clock_extra_2g'],
                waveform=valid['waveform'],hashes=valid['hashes'],covered=True,events=events), (w,signals)


def draw(case,w,signals,out):
    event=next((e for e in case['events'] if e['bit']==104 and e['covered']),None)
    if event is None:return
    edge=event['halfword_edge_s'];mask=(w.t>=edge-.2e-9)&(w.t<=edge+.8e-9)
    fig,ax=plt.subplots(figsize=(9,4),layout='constrained')
    for label,p,n in [('g3_0','g3p','g3n'),('local A select','sap','san'),('held A','ahp','ahn'),('output','qp','qn')]:
        ax.plot((w.t[mask]-edge)*1e12,(signals[p][mask]-signals[n][mask])*1000,label=label)
    for label,t,color in [('g3 target crossing',event['g3_target_cross_s'],'green'),('actual A close',event['local_a_close_s'],'red'),('training sample',event['output_training_sample_s'],'blue')]:
        ax.axvline((t-edge)*1e12,color=color,ls='--',lw=.8,label=label)
    ax.axhline(0,color='gray',lw=.6);ax.grid(alpha=.2);ax.legend(fontsize=8);ax.set(xlabel='ps relative to actual halfword edge',ylabel='Differential voltage (mV)',title=f"{case['condition']} bit 104, native extra2g={case['clock_extra_2g']}")
    fig.savefig(out/'fs_bit104.png',dpi=150);plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,action='append',required=True);a=p.parse_args()
    results=[];fig=None
    for camp in a.campaign:
        result,waves=inspect(camp);results.append(result)
        if result['condition'].startswith('fs_') and waves:fig=(result,*waves)
    root=ROOT/'results/analog/tx/native_retime';root.mkdir(parents=True,exist_ok=True)
    out=root/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(exist_ok=False)
    sources=[Path(__file__).resolve(),COLLECTOR]+[ROOT/'src/serdes_flow'/x for x in ('serial.py','clock.py','spice.py','waves.py','project.py','corners.py')]
    identities={}
    for path in sources:
        dest=out/'execution'/path.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest);identities[str(path.relative_to(ROOT))]=sha(dest)
    result=dict(scope='Native candidate full TX; actual edges and fixed training-only output sampling; local crossing difference is not setup margin.',analysis_sources=identities,cases=results)
    (out/'analysis.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    if fig:draw(*fig,out)
    print(out)


if __name__=='__main__':main()
