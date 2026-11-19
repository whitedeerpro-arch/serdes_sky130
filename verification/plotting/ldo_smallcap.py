"""Publish explicitly selected LDO shrink results and geometry comparison.

Only generates data/plots; the engineering conclusion is written by hand.
"""
import argparse
from pathlib import Path
import json
import hashlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project

ROOT=project.ROOT

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    p=p.resolve();d=json.loads(p.read_text())
    if d.get('missing'):raise ValueError('Incomplete evidence: '+str(p))
    return d

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('screen','refined','rejected','pvt','dynamic','baseline','pex','layout'):
        ap.add_argument('--'+key,type=Path)
    ap.add_argument('--original-mag',type=Path,default=ROOT/'analog/common/ldo/layout/variants/r4_pdk/serdes_ldo_hv18_core_r4_pdk.mag')
    ap.add_argument('--pex-worst',type=Path)
    ap.add_argument('--manifest',type=Path,help='explicit evidence manifest; no latest-run discovery')
    ap.add_argument('--selected')
    args=ap.parse_args()
    if args.manifest:
        manifest=json.loads(args.manifest.read_text())
        for key,value in manifest.items():
            if getattr(args,key,None) is None:setattr(args,key,value if key=='selected' else ROOT/value)
    if not args.selected:args.selected='b32_h2'
    for key in ('screen','refined','rejected','pvt','dynamic','baseline','pex','layout'):
        if getattr(args,key) is None:ap.error('Missing evidence input: '+key)
    inputs={key:getattr(args,key).resolve() for key in ('screen','refined','rejected','pvt','dynamic','baseline','pex','layout')}
    if args.pex_worst:inputs['pex_worst']=args.pex_worst.resolve()
    data={key:read(path) for key,path in inputs.items()};summary={x['name']:x for x in data['pvt']['summary']}
    selected=args.selected
    dynrows=[x for x in data['baseline']['rows'] if x['variant']=='r4']+data['dynamic']['rows']
    if selected not in summary:raise ValueError('Missing selected variant')
    if not all(x['complete'] for x in summary.values()):raise ValueError('PVT incomplete')
    dest=ROOT/'docs/figures/layout/ldo/smallcap';dest.mkdir(parents=True,exist_ok=True)
    result=dict(revision='smallcap_'+selected+'_candidate',date='2026-11-14',inputs={key:dict(path=str(path.relative_to(ROOT)),sha256=sha(path)) for key,path in inputs.items()},
                pvt=summary,dynamic=dynrows,pressure=[x for x in data['dynamic']['rows'] if x['mos']!='tt'],pex=data['pex']['summary']+data.get('pex_worst',{}).get('summary',[]),
                original_total_pf=218,candidate_total_pf=70,original_core_pf=102,candidate_core_pf=50,
                geometry={k:v for k,v in data['layout'].items() if k not in ('check_stdout','cap_arrays')},
                scope='Local schematic PVT and fixed core cap-PEX pressure points; actual PLL load, whole-macro PEX, mismatch and system jitter remain separate')
    (ROOT/'docs/data/ldo_smallcap.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    (ROOT/'results/catalog/ldo_smallcap.json').write_text(json.dumps(dict(report='docs/design/ldo_smallcap.md',data='docs/data/ldo_smallcap.json',**result),indent=2)+'\n')
    plt.rcParams.update({'font.size':10})
    fig,axes=plt.subplots(2,2,figsize=(11,8),dpi=160)
    labels=['r4','Rejected54pF','Candidate70pF'];stacks=np.array([[50,50,100,16,2],[16,16,4,16,2],[32,16,4,16,2]])
    bottom=np.zeros(3)
    for j,(name,color) in enumerate(zip(['Amplifier filter','Isolation gate filter','Output','Reference','Compensation'],['#587cbd','#7bb5a0','#d7a45b','#b68fc3','#afafaf'])):
        axes[0,0].bar(labels,stacks[:,j],bottom=bottom,label=name,color=color);bottom+=stacks[:,j]
    axes[0,0].set_ylabel('Physical MIM capacitance (pF)');axes[0,0].legend(fontsize=8)
    for n,v in enumerate(bottom):axes[0,0].text(n,v+3,str(int(v)),ha='center')
    base=next(x for x in data['screen']['summary'] if x['name']=='r4')
    ps=[base['psrr20_min_db'],next(x for x in data['rejected']['summary'] if x['name']=='b16r2')['psrr20_min_db'],summary[selected]['psrr20_min_db']]
    axes[0,1].bar(labels,ps,color=['#587cbd','#bd6860','#7bb5a0']);axes[0,1].axhline(34,c='k',ls='--',label='Existing planning gate34dB')
    axes[0,1].set_ylabel('Minimum20MHz rejection (dB)');axes[0,1].legend(fontsize=8)
    axes[0,1].set_title('r4: paired5-point screen; candidates:255AC points',fontsize=9)
    noises={v:[next(x['noise_uv'] for x in dynrows if x['variant']==v and x['mode']=='noise' and x['load_ma']==i and x['mos']=='tt') for i in (2,10)] for v in ('r4',selected)}
    xx=np.arange(2)
    for k,(v,label) in enumerate([('r4','r4'),(selected,'70pF candidate')]):axes[1,0].bar(xx+(k-.5)*.32,noises[v],.32,label=label)
    axes[1,0].set_xticks(xx,['2mA','10mA']);axes[1,0].set_ylabel('Noise (uVrms),1kHz..199.5MHz');axes[1,0].legend()
    for v,label in [('r4','r4'),(selected,'70pF candidate')]:
        row=next(x for x in dynrows if x['variant']==v and x['mode']=='step' and x['mos']=='tt')
        axes[1,1].plot([x['delta_ma'] for x in row['steps']],[x['droop_mv'] for x in row['steps']],'-o',label=label)
    axes[1,1].set_xlabel('Declared load step (mA),1ns edge');axes[1,1].set_ylabel('Output droop (mV),TT');axes[1,1].legend()
    for ax in axes.flat:ax.grid(axis='y',alpha=.2)
    fig.tight_layout();fig.savefig(dest/'comparison.png');plt.close(fig)
    sys.path.insert(0,str(ROOT/'analog/layout/scripts'))
    from layout_core import load_mag_as_canvas,plot_canvas
    mag=inputs['layout'].parent/'serdes_ldo_hv18_smallcap_pdk/serdes_ldo_hv18_smallcap_pdk.mag'
    fig,axs=plt.subplots(1,2,figsize=(14,6),dpi=170)
    for ax,path,label in [(axs[0],args.original_mag,'r4 core reference:102pF'),(axs[1],mag,'Small-cap core:50pF; DRC0,LVS match')]:
        cv=load_mag_as_canvas(path,path.stem);plot_canvas(ax,cv,label,'Core only; output/reference are separate',show_cuts=False)
        if ax.get_legend():ax.get_legend().remove()
        ax.set_xlim(-52,312);ax.set_ylim(-133,133)
    fig.tight_layout();fig.savefig(dest/'layout_comparison.png');plt.close(fig)
    print('Published docs/data/ldo_smallcap.json and two figures.')

if __name__=='__main__':main()
