"""Verify and publish an explicit cascade campaign; no simulations are launched."""
import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project

ROOT = project.ROOT
RUNNER = ROOT/'analog/tx/input_register/tb/final_clock_chain/buffer_cascade_card.py'


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main(campaign, summary, prediction):
    card=load('cascade_card',RUNNER); old=card.old
    manifest=card.check(campaign,registered=True)
    if summary.parent.parent.parent!=campaign: raise ValueError('summary belongs to another campaign')
    if prediction!=campaign/'sizing_model_before_run.json': raise ValueError('prediction must be campaign pre-run snapshot')
    generator=campaign/'sizing_model_before_run.py'
    predicted=json.loads(prediction.read_text())
    if old.digest(generator)!=predicted['generator_sha256']: raise ValueError('prediction generator hash mismatch')
    for path,expected in predicted['sources'].items():
        if old.digest(ROOT/path)!=expected: raise ValueError(f'prediction source changed: {path}')
    if load('frozen_cascade_model',generator).plan()!=predicted:
        raise ValueError('pre-run prediction does not reproduce')
    data=json.loads(summary.read_text())
    if data['status'] not in ('measurement_complete','candidate_functional_failure'):
        raise ValueError('incomplete run or baseline failure')
    if len(data['rows'])!=2 or {x['condition'] for x in data['rows']}!=set(old.TAGS):
        raise ValueError('wrong condition set')
    point=json.loads((card.PARENT/'boundary_proposal.json').read_text())['points']
    evidence={}; residuals={}; gates={}; model={r['condition']:r for r in predicted['rows']}
    for row in data['rows']:
        tag=row['condition']; raw=old.completed(campaign,tag)
        if raw is None or str(raw.relative_to(ROOT))!=row['raw'] or old.digest(raw)!=row['raw_sha256']:
            raise ValueError(f'raw/execution/deck identity mismatch: {tag}')
        measured=json.loads(json.dumps(card.measure(campaign,tag,raw,point[tag]),default=old.json_default,allow_nan=False))
        if measured!=row['result'] or not measured['baseline_matches']:
            raise ValueError(f'independent measurement or baseline mismatch: {tag}')
        branches=measured['branches']
        if [b['branch'] for b in branches]!=list(card.BRANCHES): raise ValueError('branch order changed')
        expectation=model[tag]['two_stages_predicted_xe3_pp_v']
        actual=branches[1]['nodes']['e3']['differential_pp_v']
        residuals[tag]={'predicted_v':expectation,'measured_v':actual,'residual_mv':(actual-expectation)*1e3,
                        'residual_percent_of_prediction':(actual-expectation)/expectation*100,
                        'branch_status':branches[1]['status']}
        evidence[tag]={p.name:old.digest(p) for p in (raw,raw.parent/'execution.json',raw.parent/'tb.cir',raw.parent/'simulator.log')}
        gates[tag] = []
        for branch in branches:
            metrics = branch.get('metrics', {})
            spread = metrics.get('transition_spread_ui')
            margin = metrics.get('minimum_signed_margin_v')
            functional = bool(metrics.get('functional', False))
            gates[tag].append(dict(branch=branch['branch'], functional=functional,
                margin_75mv_observed=margin is not None and margin >= .075,
                spread_015ui_observed=spread is not None and spread <= .15,
                local_serial_gate_observed=bool(functional and margin is not None and margin >= .075
                                               and spread is not None and spread <= .15),
                observed_over_400mv_nodes=[n for n,v in branch['nodes'].items()
                                         if v['differential_pp_v'] > .4],
                observed_below_200mv_cycle_nodes=[n for n,v in branch['nodes'].items()
                    if v.get('cycles',{}).get('min_pp_v') is not None and v['cycles']['min_pp_v'] < .2],
                observed_below_150mv_cycle_nodes=[n for n,v in branch['nodes'].items()
                    if v.get('cycles',{}).get('min_pp_v') is not None and v['cycles']['min_pp_v'] < .15],
                qualification='local eight-bit observations only; full TX and I-17 remain open'))
    expected_status='candidate_functional_failure' if any(b['status']=='functional_failure' for r in data['rows'] for b in r['result']['branches'][1:]) else 'measurement_complete'
    if data['status']!=expected_status: raise ValueError('summary functional status inconsistent')
    scope=('TT and FS hot low-voltage, archived loaded extra5 replay with ideal recorded PWL inputs, bias and supplies. '
           'Eight-bit fixed contract only; full TX mapping and I-17 remain open. Five-stage model is an unqualified proxy.')
    published={'scope':scope,'status':data['status'],'campaign':str(campaign.relative_to(ROOT)),
               'summary':str(summary.relative_to(ROOT)),'summary_sha256':old.digest(summary),
               'prediction':str(prediction.relative_to(ROOT)),'prediction_sha256':old.digest(prediction),
               'prediction_generator_sha256':old.digest(generator),'prediction_sources':predicted['sources'],
               'runner_sha256':old.digest(RUNNER),'publisher_sha256':old.digest(Path(__file__)),
               'plan_sha256':old.digest(campaign/'plan.json'),'cascade_plan_sha256':old.digest(campaign/'cascade_plan.json'),
               'parent_identity':manifest['parent_identity'],'evidence':evidence,'results':data['rows'],
               'local_gate_observations':gates,
               'two_stage_xe3_prediction_residuals':residuals,'prediction_assumptions':predicted['assumptions'],
               'ungraded':manifest['ungraded']}
    fig,axes=plt.subplots(2,2,figsize=(12,8.5),layout='constrained')
    stages=('iso','e0','e1','e2','e3','e4','c2g'); colors=('#176c8c','#388c70','#d27732')
    for row,ax in zip(data['rows'],axes[0]):
        for branch,color in zip(row['result']['branches'],colors):
            y=[branch['nodes'][s]['differential_pp_v']*1e3 for s in stages]
            label=branch['branch']+(' — FUNCTIONAL FAILURE' if branch['status']=='functional_failure' else '')
            ax.plot(stages,y,'o-',color=color,label=label)
        ax.axhline(400,color='#b34545',ls='--',label='400 mV upper')
        ax.axhline(200,color='#388c70',ls=':',label='200 mV target')
        ax.axhline(150,color='#8c5696',ls='-.',label='150 mV hard lower')
        ax.set(title=row['condition'],ylabel='Differential pp (mV)'); ax.grid(alpha=.2); ax.legend(fontsize=7)
    for row,color in zip(data['rows'],('#176c8c','#cf4951')):
        branches=row['result']['branches']
        shifts=[b.get('clock_fall_shift_s',float('nan'))*1e12 for b in branches]
        spreads=[b.get('metrics',{}).get('transition_spread_ui',float('nan')) for b in branches]
        axes[1,0].plot(range(3),shifts,'o-',color=color,label=row['condition'])
        axes[1,1].plot(range(3),spreads,'o-',color=color,label=row['condition'])
        for i,b in enumerate(branches):
            if b['status']=='functional_failure':
                axes[1,1].annotate('FAIL',(i,0),xytext=(0,5),textcoords='offset points',color=color,ha='center')
    axes[1,0].set(ylabel='c2g shift from old extra5 (ps)',title='Clock propagation')
    axes[1,1].set(ylabel='8-bit transition spread (UI)',title='Fixed-contract local window')
    axes[1,1].axhline(.15,color='#b34545',ls='--')
    failures = [r['condition'] + ' / ' + g['branch'] for r in data['rows']
                for g in gates[r['condition']] if not g['local_serial_gate_observed']]
    if failures:
        axes[1,1].text(.02,.98,'LOCAL SERIAL SPEC FAIL: ' + ', '.join(failures),
                       transform=axes[1,1].transAxes,va='top',fontsize=8,color='#b34545')
    for ax in axes[1]:
        ax.set_xticks(range(3),['baseline','two stages','extra5']); ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle('TX cascade local replay — '+data['status'].replace('_',' ').upper(),fontsize=12)
    figure=ROOT/'docs/figures/tx/ingress/tx_buffer_cascade.png'; output=ROOT/'docs/data/tx_buffer_cascade.json'
    catalog=ROOT/'results/catalog/tx_buffer_cascade.json'
    fig.savefig(figure,dpi=160); plt.close(fig)
    output.write_text(json.dumps(published,indent=2,allow_nan=False)+'\n')
    catalog.write_text(json.dumps({'data':str(output.relative_to(ROOT)),'data_sha256':old.digest(output),
        'figure':str(figure.relative_to(ROOT)),'figure_sha256':old.digest(figure),'campaign':published['campaign'],
        'summary':published['summary'],'summary_sha256':published['summary_sha256'],'evidence':evidence,'scope':scope,
        'status':data['status']},indent=2)+'\n')
    print(json.dumps({'status':data['status'],'two_stage_xe3_prediction_residuals':residuals},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',type=Path,required=True); parser.add_argument('--summary',type=Path,required=True)
    parser.add_argument('--prediction',type=Path,required=True)
    args=parser.parse_args(); main(args.campaign.resolve(),args.summary.resolve(),args.prediction.resolve())
