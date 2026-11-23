"""Bind physical fusion, actual rectangular planning and switch-Q evidence."""
import argparse
from dataclasses import asdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import cap_fusion,project

ROOT=project.ROOT


def identity(path):
    p=Path(path).resolve()
    return dict(path=str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('physical','ac-summary','plan-summary','q-summary'):ap.add_argument('--'+key,type=Path,required=True)
    ap.add_argument('--device-summary',type=Path)
    a=ap.parse_args();inputs=[]
    def read(path):
        inputs.append(identity(path));return json.loads(Path(path).read_text())
    physical=read(a.physical/'summary.json');ac=read(a.ac_summary);plan=read(a.plan_summary);qdata=read(a.q_summary)
    for rel,h in physical['sha256'].items():
        record=identity(a.physical/rel)
        if record['sha256']!=h:raise ValueError('Physical snapshot changed')
    inputs.append(identity(a.physical/'pll_vco_cap_bank5_fused_cap.spice'))
    inputs.append(identity(a.physical/'check.log'))
    negative=a.physical/'lvs_against_unit_reference/comparison.log';inputs.append(identity(negative))
    if 'Property errors were found' not in negative.read_text():raise ValueError('Expected original-reference dimensional mismatch')
    for result in (ac,qdata):
        camp=ROOT/result['campaign'];meta=read(camp/'plan.json')
        if inputs[-1]['sha256']!=result['plan_sha256']:raise ValueError('Campaign plan changed')
        for rel,h in meta['inputs'].items():
            if identity(camp/rel)['sha256']!=h:raise ValueError('Campaign input changed')
        for row in result['rows']:
            run=ROOT/row['run']
            inputs.extend(identity(p) for p in sorted(run.glob('*.tsv')))
            inputs.extend(identity(run/n) for n in ('tb.cir','execution.json'))
    pc=ROOT/plan['campaign'];read(pc/'inputs.json')
    inputs.extend(identity(pc/'ac'/n) for n in ('tb.cir','execution.json','off_0.tsv','off_1.tsv','on_0.tsv','on_1.tsv'))
    inputs.append(identity(pc/'source/cap_bank_plan.json'))
    if inputs[-1]['sha256']!=plan['plan_identity']['sha256']:raise ValueError('Planning snapshot changed')
    m,_=cap_fusion.installed();model_corners={};area_only=[];fixed=[]
    for rc in cap_fusion.RC_FILES:
        model,files=cap_fusion.installed(rc);model_corners[rc]=asdict(model)
        inputs.extend(identity(f) for f in files)
    for n in (1,2,4,8,16):
        side=2*np.sqrt(n);reference=n*m.cap_ff(2,2);actual=m.cap_ff(side,side)
        area_only.append(dict(units=n,equal_area_square_um=float(side),target_ff=reference,actual_ff=actual,
                              relative_cap_error=actual/reference-1,relative_cutoff_error=reference/actual-1))
    for n,s in ((32,22.1965),(16,22.1965),(6,22.2),(5,22.2),(4,22.1965),(2,22.2)):
        target=n*m.cap_ff(s,s);count=int(np.ceil(target/m.cap_ff(30,30)));side=cap_fusion.rounded_square(target/count,grid_um=.01)
        fixed.append(dict(original_units=n,unit_side_um=s,target_pf=target/1000,new_units=count,new_side_um=side,
                          status='model/PCell-guard estimate only; physical fixed-cap array not built'))
    bank=[]
    for row in ac['rows']:
        entry=dict(condition=row['condition'],metrics=row['metrics'],filter_cutoff_hz=row['filter_cutoff_hz'])
        entry['all_three_frequencies_monotone']={}
        for label in ('planning','shared','fused'):
            entry['all_three_frequencies_monotone'][label]=all(
                min(np.diff([r['values'][label]['c_ff'] for r in row['rows'] if r['hz']==f]))>0 for f in (1e6,20e6,2e9))
        r=next(r for r in row['rows'] if r['hz']==2e9 and r['code']==31)
        entry['on_port_q']={k:2*np.pi*2e9*v['c_ff']*1e-15/v['g_s'] for k,v in r['values'].items()}
        bank.append(entry)
    quality=[]
    for row in qdata['rows']:
        vals=[r for r in row['rows'] if r['hz']==2e9]
        quality.append(dict(condition=row['condition'],values=vals))
    baseline_area=51.07*18.61
    result=dict(report='docs/layout/capacitor_fusion.md',inputs=inputs,physical_candidate=physical,
        physical_area_relative_to_shared=physical['area_um2']/baseline_area-1,
        original_reference_lvs_compatible=False,pcell_max_square_um=cap_fusion.maximum_square_um(),
        pcell_limit_is_foundry_rule=False,model_corners=model_corners,area_only_examples=area_only,
        fixed_cap_retiling=fixed,bank_ac=bank,rectangular_plan=plan,switch_q=quality,
        scope='Local geometry, biased AC, same-node cutoff and model estimates; physical candidate only; adopted DUT/layout and full-PVT/oscillator-noise qualifications unchanged')
    if a.device_summary:
        devices=read(a.device_summary);dc=ROOT/devices['campaign'];dp=read(dc/'plan.json')
        if identity(dc/'plan.json')['sha256']!=devices['plan_sha256']:raise ValueError('Device plan changed')
        for rel,h in dp['snapshots'].items():
            if identity(dc/rel)['sha256']!=h:raise ValueError('Device input changed')
        for row in devices['rows']:
            d=ROOT/row['run'];inputs.extend(identity(p) for p in sorted(d.glob('*.tsv')))
            inputs.extend(identity(d/n) for n in ('tb.cir','execution.json'))
        result['switch_devices']=devices
    out=ROOT/'results/layout/capacitor_fusion_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    shutil.copyfile(Path(__file__),out/'analysis.py');shutil.copyfile(Path(cap_fusion.__file__),out/'cap_fusion.py')
    result['analysis_sources']=[identity(out/'analysis.py'),identity(out/'cap_fusion.py')]
    fig,axes=plt.subplots(1,3,figsize=(14,4.1),layout='constrained')
    rec=[r for r in plan['records'] if r['bit']!='b0'];x=np.arange(len(rec))
    axes[0].bar(x-.17,[r['main_c_drawn_relative_error']*100 for r in rec],.34,label='Drawn rectangles')
    axes[0].bar(x+.17,[(m.cap_ff(*r['main_c_matched_um'])/r['main_c_target_ff']-1)*100 for r in rec],.34,label='Length retarget')
    axes[0].set(xticks=x,xticklabels=[r['bit'] for r in rec],ylabel='Main MIM C error (%)',title='Actual nine-block plan widths retained')
    axes[0].legend(fontsize=8)
    names=['1.50','0.75','0.50'];pos=np.arange(3)
    for name,color in [('tt','#136da3'),('fs_hot_hh','#c66b30'),('ss_hot_hh','#963658')]:
        row=next(r for r in quality if r['condition'][0]==name)
        values=[next(v for v in row['values'] if v['state']=='on' and v['variant']==k)['q'] for k in ('w150','w075','w050')]
        axes[1].plot(pos,values,'o-',label=name,color=color)
    axes[1].set(xticks=pos,xticklabels=names,xlabel='Switch width per logical unit (um)',ylabel='Im(Y) / Re(Y)',title='4.6 x 7.56 um block at 2 GHz')
    axes[1].legend(fontsize=8)
    for condition,color in [('tt','#136da3'),('fs_hot_hh','#c66b30')]:
        row=next(r for r in quality if r['condition'][0]==condition)
        for state,ls in [('on','-'),('off','--')]:
            values=[next(v for v in row['values'] if v['state']==state and v['variant']==k)['cap_ff'] for k in ('w150','w075','w050')]
            axes[2].plot(pos,values,'o'+ls,label=condition+' '+state,color=color)
    axes[2].set(xticks=pos,xticklabels=names,xlabel='Switch width per logical unit (um)',ylabel='Effective capacitance (fF)',title='Isolated plan block; full capacitive EXT')
    axes[2].legend(fontsize=8)
    for ax in axes:ax.grid(alpha=.2)
    fig.suptitle('Fusion and switch sizing are separate changes; local cards, not oscillator qualification',fontsize=11)
    folder=ROOT/'docs/figures/layout';folder.mkdir(exist_ok=True)
    fig.savefig(folder/'capacitor_fusion.png',dpi=160);plt.close(fig)
    text=json.dumps(result,indent=2,allow_nan=False)+'\n';(out/'summary.json').write_text(text)
    (ROOT/'docs/data/capacitor_fusion.json').write_text(text)
    (ROOT/'results/catalog/capacitor_fusion.json').write_text(json.dumps(dict(report=result['report'],data='docs/data/capacitor_fusion.json',analysis=str((out/'summary.json').relative_to(ROOT)),inputs=inputs),indent=2)+'\n')
    print(out/'summary.json')


if __name__=='__main__':main()
