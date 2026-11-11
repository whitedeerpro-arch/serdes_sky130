"""Independently verify/publish a completed profile sizing card; never simulate."""
import argparse
import importlib.util
import hashlib
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from serdes_flow import project

ROOT=project.ROOT
RUNNER=ROOT/'analog/tx/input_register/tb/final_clock_chain/buffer_sizing_card.py'
LOADED_SOURCE=Path(__file__).read_bytes()
LOADED_SHA256=hashlib.sha256(LOADED_SOURCE).hexdigest()


def main(campaign,summary,name='tx_buffer_sizing',matrix=False):
    if not re.fullmatch(r'[a-z][a-z0-9_]*',name):raise ValueError('output name must be a simple artifact identifier')
    runner=RUNNER.with_name('buffer_matrix_card.py') if matrix else RUNNER
    spec=importlib.util.spec_from_file_location('sizing_card',runner)
    card=importlib.util.module_from_spec(spec); spec.loader.exec_module(card)
    plan=card.check(campaign,registered=True); old=card.old
    archived=campaign/'publication_sources'/f'{LOADED_SHA256}.py'
    archived.parent.mkdir(exist_ok=True)
    if not archived.exists():
        with archived.open('xb') as stream:stream.write(LOADED_SOURCE)
    if old.digest(archived)!=LOADED_SHA256:raise ValueError('archived publisher changed')
    if summary.parent.parent.parent!=campaign: raise ValueError('summary belongs to another campaign')
    data=json.loads(summary.read_text())
    if data['status'] not in ('measurement_complete','candidate_functional_failure') or len(data['rows'])!=2:
        raise ValueError('incomplete campaign or baseline failure')
    if {r['condition'] for r in data['rows']}!=set(old.TAGS): raise ValueError('wrong conditions')
    profile=card.validate(json.loads((campaign/'profile.json').read_text()))
    predicted=None
    if matrix:
        source=campaign/'gain_plan.py'; prediction=campaign/'gain_plan.json'
        predicted=json.loads(prediction.read_text())
        if old.digest(source)!=predicted['generator_sha256']:raise ValueError('pre-run model source changed')
        for path,expected in predicted['sources'].items():
            if old.digest(ROOT/path)!=expected:raise ValueError('pre-run model input changed')
        mspec=importlib.util.spec_from_file_location('frozen_gain_plan',source)
        model=importlib.util.module_from_spec(mspec);mspec.loader.exec_module(model)
        if model.plan()!=predicted:raise ValueError('pre-run gain model does not reproduce')
    points=json.loads((card.PARENT/'boundary_proposal.json').read_text())['points']
    evidence={}; screens={}
    for row in data['rows']:
        tag=row['condition']; raw=old.completed(campaign,tag)
        if raw is None or str(raw.relative_to(ROOT))!=row['raw'] or old.digest(raw)!=row['raw_sha256']:
            raise ValueError(f'raw/execution/deck mismatch: {tag}')
        result=card.cascade.measure(campaign,tag,raw,points[tag])
        for branch,params in zip(result['branches'],profile['branches']):
            branch['branch']=params['label']; branch['actual_parameters']=params
        result=json.loads(json.dumps(result,default=old.json_default,allow_nan=False))
        if result!=row['result'] or not result['baseline_matches'] or len(result['branches'])!=3:
            raise ValueError(f'measurement or baseline mismatch: {tag}')
        screens[tag]={}
        for branch in result['branches']:
            m=branch.get('metrics',{}); spread=m.get('transition_spread_ui')
            passed=bool(m.get('functional',False) and m.get('minimum_signed_margin_v',float('-inf'))>=.075 and spread is not None and spread<=.15)
            screens[tag][branch['branch']]={'status':'pass' if passed else 'fail', 'scope':'8-bit fixed contract local window',
                'functional':m.get('functional'), 'minimum_signed_margin_v':m.get('minimum_signed_margin_v'),
                'transition_spread_ui':spread, 'branch_status':branch['status']}
        evidence[tag]={p.name:old.digest(p) for p in (raw,raw.parent/'execution.json',raw.parent/'tb.cir',raw.parent/'simulator.log')}
    expected='candidate_functional_failure' if any(b['status']=='functional_failure' for r in data['rows'] for b in r['result']['branches'][1:]) else 'measurement_complete'
    if data['status']!=expected: raise ValueError('inconsistent functional status')
    scope=('TT and FS hot low voltage, ideal recorded PWL local loaded extra5 cut; '
           'eight-bit fixed contract only. Local screen is functional plus 75 mV and 0.15 UI; '
           'isolation amplitude and full TX/PVT/noise remain open; I-17 is not closed.')
    publication={'scope':scope,'status':data['status'],'campaign':str(campaign.relative_to(ROOT)),
        'summary':str(summary.relative_to(ROOT)),'summary_sha256':old.digest(summary),
        'plan_sha256':old.digest(campaign/'plan.json'),'sizing_plan_sha256':old.digest(campaign/('matrix_plan.json' if matrix else 'sizing_plan.json')),
        'profile_sha256':old.digest(campaign/'profile.json'),'profile':profile,'runner_sha256':old.digest(runner),
        'cascade_sha256':old.digest(card.CASCADE),'publisher_sha256':LOADED_SHA256,
        'publisher_snapshot':str(archived.relative_to(ROOT)),
        'parent_identity':plan['parent_identity'],'evidence':evidence,'local_window_screen':screens,
        'results':data['rows'],'ungraded':plan['ungraded']}
    if predicted is not None:
        residuals=[]
        for row in data['rows']:
            pre=next(r for r in predicted['rows'] if r['condition']==row['condition'])
            for branch in row['result']['branches'][1:]:
                params=branch['actual_parameters']['stages']
                matches=[p for p in pre['candidates'] if p['wt_um']==[s[1] for s in params]
                         and all(s[0]==p['wn_um'] and s[2]==p['r_nominal_ohm'] for s in params)]
                if not matches:continue
                forecast=matches[0]['predicted_stage_pp_v']
                observed=[branch['nodes'][f'e{i}']['differential_pp_v'] for i in range(5)]
                residuals.append(dict(condition=row['condition'],branch=branch['branch'],
                    predicted_stage_pp_v=forecast,observed_stage_pp_v=observed,
                    residual_mv=[(a-b)*1e3 for a,b in zip(observed,forecast)],
                    maximum_abs_residual_mv=max(abs(a-b)*1e3 for a,b in zip(observed,forecast))))
        publication.update(pre_run_prediction_sha256=old.digest(campaign/'gain_plan.json'),
                           pre_run_generator_sha256=old.digest(campaign/'gain_plan.py'),
                           prediction_residuals=residuals)
    fig,axes=plt.subplots(2,2,figsize=(12,8.5),layout='constrained')
    stages=('iso','e0','e1','e2','e3','e4','c2g'); colors=('#176c8c','#388c70','#d27732')
    for row,ax in zip(data['rows'],axes[0]):
        for b,color in zip(row['result']['branches'],colors):
            values=[b['nodes'][stage]['differential_pp_v']*1e3 for stage in stages]
            label=b['branch']+(' — FUNCTIONAL FAILURE' if b['status']=='functional_failure' else '')
            ax.plot(stages,values,'o-',color=color,label=label)
        ax.axhline(400,ls='--',color='#b34545',label='400 mV upper')
        ax.axhline(200,ls=':',color='#388c70',label='200 mV target')
        ax.axhline(150,ls='-.',color='#8c5696',label='150 mV hard lower')
        ax.set(title=row['condition'],ylabel='Differential pp (mV)'); ax.grid(alpha=.2); ax.legend(fontsize=7)
    for row,color in zip(data['rows'],('#176c8c','#cf4951')):
        branches=row['result']['branches']
        axes[1,0].plot(range(3),[b.get('clock_fall_shift_s',float('nan'))*1e12 for b in branches],'o-',color=color,label=row['condition'])
        axes[1,1].plot(range(3),[b.get('metrics',{}).get('transition_spread_ui') if b.get('metrics',{}).get('transition_spread_ui') is not None else float('nan') for b in branches],'o-',color=color,label=row['condition'])
        for i,b in enumerate(branches):
            if b['status']=='functional_failure': axes[1,1].annotate('FAIL',(i,0),xytext=(0,5),textcoords='offset points',color=color,ha='center')
    axes[1,0].set(title='Clock propagation',ylabel='c2g shift from old extra5 (ps)')
    axes[1,1].set(title='Eight-bit fixed contract',ylabel='Transition spread (UI)'); axes[1,1].axhline(.15,ls='--',color='#b34545')
    failures=[tag+'/'+label for tag,rows in screens.items() for label,value in rows.items() if value['status']=='fail']
    if failures:
        axes[1,1].text(.02,.98,'LOCAL SPEC FAIL: '+', '.join(failures),transform=axes[1,1].transAxes,
                      va='top',fontsize=7,color='#b34545')
    for ax in axes[1]:
        ax.set_xticks(range(3),[b['label'] for b in profile['branches']]); ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle('TX extra5 sizing — local replay; I-17 remains open',fontsize=12)
    output=ROOT/'docs/data'/f'{name}.json'; figure=ROOT/'docs/figures/tx/ingress'/f'{name}.png'; catalog=ROOT/'results/catalog'/f'{name}.json'
    fig.savefig(figure,dpi=160); plt.close(fig)
    output.write_text(json.dumps(publication,indent=2,allow_nan=False)+'\n')
    catalog.write_text(json.dumps({'data':str(output.relative_to(ROOT)),'data_sha256':old.digest(output),'figure':str(figure.relative_to(ROOT)),
        'figure_sha256':old.digest(figure),'campaign':publication['campaign'],'summary':publication['summary'],
        'summary_sha256':publication['summary_sha256'],'evidence':evidence,'scope':scope,'status':data['status']},indent=2)+'\n')
    print(json.dumps({'status':data['status'],'local_window_screen':screens},indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--campaign',type=Path,required=True); p.add_argument('--summary',type=Path,required=True)
    p.add_argument('--name',default='tx_buffer_sizing',help='artifact name; use a new name to retain an earlier parameter comparison')
    p.add_argument('--matrix',action='store_true',help='use the per-stage matrix card instead of the uniform profile card')
    a=p.parse_args(); main(a.campaign.resolve(),a.summary.resolve(),a.name,a.matrix)
