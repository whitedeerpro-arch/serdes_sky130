"""Recompute loaded extra3/4/5 clock stages from an explicit completed campaign."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import boundary, project, watch
from serdes_flow.project import ROOT

RUNNER='analog/tx/input_register/tb/final_clock_chain/native_reduced_clock.py'
DATA=ROOT/'docs/data/tx_native_reduced_clock.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_native_reduced_clock'
CATALOG=ROOT/'results/catalog/tx_native_reduced_clock.json'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def collect(camp,phase_card=None):
    camp=camp.resolve()
    if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise ValueError('campaign still running')
    spec=importlib.util.spec_from_file_location('native_reduced_clock_snapshot',camp/'execution'/RUNNER)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    # Read-only collection uses the archived runner, including after its
    # worktree copy receives a serialization fix. Execution resume still uses
    # the runner's stricter requirement that current source bytes match.
    plan=json.loads((camp/'plan.json').read_text());entry=boundary.get(plan['boundary_id'])
    if runner.canonical(entry)!=plan['boundary_sha256'] or entry!=json.loads((camp/'boundary.json').read_text()):
        raise ValueError('child boundary changed')
    parent=boundary.get(runner.PARENT)
    if runner.canonical(parent)!=entry['parent_sha256']:raise ValueError('parent boundary changed')
    if plan['counts']!=list(runner.COUNTS) or plan['stop_s']!=runner.STOP or set(plan['conditions'])!=set(entry['points']):
        raise ValueError('experiment parameters differ')
    if sha(project.model_library())!=plan['pdk_library_sha256']:raise ValueError('PDK changed')
    runner.check_source(parent)
    archive_scripts={RUNNER,'verification/plotting/tx_parallel_serializer.py'}
    for rel,h in plan['sources'].items():
        if sha(camp/'execution'/rel)!=h or (rel not in archive_scripts and sha(ROOT/rel)!=h):
            raise ValueError(f'physical/measurement dependency changed: {rel}')
    runner.native.collector=runner.load('archived_full_tx_collector',camp/'execution/verification/plotting/tx_parallel_serializer.py')
    for rel,h in plan['snapshots'].items():
        if sha(camp/rel)!=h:raise ValueError(f'checkpoint changed: {rel}')
    summary_path=camp/'summary.json'
    summary=json.loads(summary_path.read_text()) if summary_path.exists() else None
    if summary is not None:
        rows=summary['rows']
        if len(rows)!=len(plan['conditions']) or {r['condition'] for r in rows}!=set(plan['conditions']) or any(r['status']!='measured' for r in rows):
            raise ValueError('all distinct completed conditions required')
    else:
        rows=[dict(condition=tag) for tag in plan['conditions']]
    model=None
    if phase_card is not None:
        model=json.loads(phase_card.read_text())
        if model['boundary_id']!=runner.PARENT or model['boundary_sha256']!=entry['parent_sha256'] or model['source_points']!=entry['points']:
            raise ValueError('phase model has different source/boundary identity')
    output=[]
    for row in rows:
        tag=row['condition'];raw=runner.out(camp,tag)
        if raw is None:raise ValueError('complete execution/raw missing')
        if summary is not None and (raw!=ROOT/row['raw'] or sha(raw)!=row['raw_sha256']):raise ValueError('raw identity/completeness differs')
        measured=runner.measure(camp,tag,entry['points'][tag],raw)
        # NumPy 2 boolean scalars are not accepted by Python's JSON encoder.
        # Normalize serialization only; no scientific threshold is changed.
        measured=json.loads(json.dumps(measured,default=lambda v:v.item() if isinstance(v,np.generic) else v,allow_nan=False))
        if summary is not None and not runner.native.collector.equal(measured,row['result']):raise ValueError('independent measurements differ')
        if measured['baseline_matches'] is not True:raise ValueError('extra3 baseline fidelity failed')
        for branch in measured['branches']:
            m=branch['metrics'];cycle=branch['c2g_cycles']
            branch['local_eye_screen']=bool(m['functional'] and m['minimum_signed_margin_v']>=.075
                and m['transition_spread_ui'] is not None and m['transition_spread_ui']<=.15)
            branch['observed_c2g_150_to_400mv_screen']=bool(cycle is not None and cycle['min_pp_v']>=.15 and branch['c2g_pp_v']<=.4)
            branch['observed_c2g_at_least_200mv_target']=bool(cycle is not None and cycle['min_pp_v']>=.2)
            if model is not None:
                card=sorted((r for r in model['rows'] if r['condition']==tag),key=lambda r:r['offset_ps'])
                x=[r['offset_ps'] for r in card];shift=branch['clock_fall_shift_s']*1e12
                if not x or not x[0]<=shift<=x[-1]:raise ValueError('clock increment outside measured phase-card range')
                predicted=float(np.interp(shift,x,[r['metrics']['transition_spread_ui'] for r in card]))
                branch['phase_card_prediction']=dict(spread_ui=predicted,
                    measured_minus_prediction_ui=m['transition_spread_ui']-predicted,
                    measured_minus_prediction_s=(m['transition_spread_ui']-predicted)*250e-12)
        output.append(dict(condition=tag,waveform=str(raw.relative_to(ROOT)),waveform_sha256=sha(raw),
            execution_sha256=sha(raw.parent/'execution.json'),deck_sha256=sha(raw.parent/'tb.cir'),**measured))
    return dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),summary_sha256=sha(summary_path) if summary is not None else None,
        original_summary_present=summary is not None,
        phase_card=(dict(path=str(phase_card.resolve().relative_to(ROOT)),sha256=sha(phase_card),
                        method='piecewise-linear interpolation at actual c2g clock increment; no output fitting or extrapolation') if model is not None else None),
        original_analysis_error=(dict(path=str((camp/'analysis_error.json').relative_to(ROOT)),sha256=sha(camp/'analysis_error.json'))
                                 if (camp/'analysis_error.json').is_file() else None),
        analysis_definition='Independent recomputation from complete hashed execution and raw, using the archived runner. NumPy scalar types normalized for JSON; original checkpoints untouched.',
        collector_sha256=sha(Path(__file__)),runner_sha256=sha(camp/'execution'/RUNNER),boundary_id=plan['boundary_id'],
        boundary_sha256=plan['boundary_sha256'],source_points=entry['points'],
        scope='TT/FS word18 B-halfword eight-bit loaded clock-chain cut. Extra3/4/5 are independent ideal-source experiments, not parallel chip paths. No complete TX, 45 PVT, upstream feedback, mismatch or noise qualification.',
        phase_definition='Full-run training phase plus median c2g falling-edge increment measured against recorded c2g. No output-payload phase fitting.',
        cases=output)


def draw(data):
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for case in data['cases']:
        rows=case['branches'];x=[r['extra'] for r in rows];label=case['condition']
        axes[0,0].plot(x,[r['clock_fall_shift_s']*1e12 for r in rows],'-o',label=label)
        axes[0,1].plot(x,[r['c2g_pp_v']*1000 for r in rows],'-o',label=label)
        axes[1,0].plot(x,[r['metrics']['minimum_signed_margin_v']*1000 for r in rows],'-o',label=label)
        axes[1,1].plot(x,[r['metrics']['transition_spread_ui'] for r in rows],'-o',label=label)
        for row in rows:
            if not row['local_eye_screen']:axes[1,1].plot(row['extra'],row['metrics']['transition_spread_ui'],'rx',ms=10)
    for ax in axes.flat:ax.set_xticks([3,4,5]);ax.set_xlabel('Extra physical buffer stages');ax.grid(alpha=.25)
    axes[0,0].set_ylabel('c2g shift from recorded source (ps)');axes[0,0].legend(fontsize=8)
    axes[0,1].set_ylabel('Observed c2g differential swing (mVpp)')
    for value in (150,200,400):axes[0,1].axhline(value,color='gray',ls='--',lw=.6)
    axes[1,0].set_ylabel('Local minimum signed margin (mV)');axes[1,0].axhline(75,color='red',ls='--',lw=.7)
    axes[1,1].set_ylabel('Local edge spread (UI)');axes[1,1].axhline(.15,color='red',ls='--',lw=.7)
    fig.suptitle('WT16/R240: actual loaded clock stages and eight-bit timing; not full TX acceptance')
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=170)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',required=True,type=Path)
    p.add_argument('--phase-card',type=Path,help='explicit measured phase card for prediction/calibration');a=p.parse_args()
    data=collect(a.campaign,a.phase_card);draw(data)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    CATALOG.write_text(json.dumps(dict(data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),campaign=data['campaign'],
        boundary_id=data['boundary_id'],scope=data['scope'],figures=[str(FIG.relative_to(ROOT))+'.'+e for e in ('png','svg')]),indent=2)+'\n')
    print(DATA)


if __name__=='__main__':main()
