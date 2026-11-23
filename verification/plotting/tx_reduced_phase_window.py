"""Independently collect a complete reduced-swing final-rank phase study."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from serdes_flow import boundary, watch
from serdes_flow.project import ROOT

RUNNER='analog/tx/input_register/tb/final_retime/native_window.py'
DATA=ROOT/'docs/data/tx_reduced_phase_window.json'
CATALOG=ROOT/'results/catalog/tx_reduced_phase_window.json'
FIG=ROOT/'docs/figures/tx/ingress/tx_reduced_phase_window'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def collect(camp):
    camp=camp.resolve()
    if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise ValueError('campaign still has live ngspice')
    spec=importlib.util.spec_from_file_location('reduced_phase_snapshot',camp/'execution'/RUNNER)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    plan=json.loads((camp/'plan.json').read_text());entry=boundary.get(plan['boundary_id'])
    if entry!=json.loads((camp/'boundary.json').read_text()) or runner.digest(entry)!=plan['boundary_sha256']:
        raise ValueError('boundary changed')
    runner.verify_boundary(entry)
    archive_scripts={RUNNER,'verification/plotting/tx_parallel_serializer.py'}
    for rel,h in plan['sources'].items():
        if sha(camp/'execution'/rel)!=h or (rel not in archive_scripts and sha(ROOT/rel)!=h):
            raise ValueError(f'physical/measurement dependency changed: {rel}')
    for rel,h in plan['snapshots'].items():
        if sha(camp/rel)!=h:raise ValueError(f'prepared checkpoint changed: {rel}')
    if plan['offsets_ps']!=list(runner.OFFSETS) or plan['stop_s']!=runner.STOP or plan['first_bit']!=runner.FIRST or plan['end_bit']!=runner.END:
        raise ValueError('experiment parameters changed')
    runner.collector=runner.module('archived_full_tx_collector',camp/'execution/verification/plotting/tx_parallel_serializer.py')
    summary=json.loads((camp/'summary.json').read_text())
    expected={(c['condition'],c['offset_ps']) for c in plan['cases']}
    rows=summary['rows']
    if len(rows)!=len(expected) or {(r['condition'],r['offset_ps']) for r in rows}!=expected or any(r['status']!='measured' for r in rows):
        raise ValueError('complete distinct phase cases required')
    out=[]
    for row in rows:
        tag=row['condition'];offset=row['offset_ps'];raw=runner.output(camp,tag,offset)
        if raw is None or raw!=ROOT/row['waveform'] or sha(raw)!=row['waveform_sha256']:
            raise ValueError('waveform identity/completeness differs')
        measured=runner.measure(raw,entry['points'][tag],offset,camp/'inputs'/f'{tag}.npz')
        if not runner.collector.equal(measured,row['result']):raise ValueError('independent local measurements differ')
        if offset==0 and measured['baseline_matches'] is not True:raise ValueError('original loaded baseline failed')
        out.append(dict(condition=tag,offset_ps=offset,waveform=row['waveform'],waveform_sha256=row['waveform_sha256'],
                        execution_sha256=sha(raw.parent/'execution.json'),deck_sha256=sha(raw.parent/'tb.cir'),**measured))
    return dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),summary_sha256=sha(camp/'summary.json'),
                collector_sha256=sha(Path(__file__)),runner_sha256=sha(camp/'execution'/RUNNER),
                boundary_id=plan['boundary_id'],boundary_sha256=plan['boundary_sha256'],source_points=entry['points'],
                scope='TT/FS, eight bits of word18 B halfword, ideal recorded port voltages and actual final rank/driver/RLC16. Not complete TX, 45 PVT, mismatch, noise, or physical delay-cell qualification.',
                phase_definition='Original full-run training phase plus commanded c2g shift; local bit phase/UI never fitted.',
                waveform_error_gate_v=.005,edge_error_gate_s=2e-12,first_bit=plan['first_bit'],end_bit=plan['end_bit'],rows=out)


def draw(data):
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    tags=sorted({r['condition'] for r in data['rows']},reverse=True)
    if len(tags)!=2:raise ValueError('comparison figure requires exactly two recorded conditions')
    for col,tag in enumerate(tags):
        rows=sorted((r for r in data['rows'] if r['condition']==tag),key=lambda r:r['offset_ps'])
        x=[r['offset_ps'] for r in rows]
        axes[0,col].plot(x,[r['metrics']['minimum_signed_margin_v']*1000 for r in rows],'-o',color='#28769c')
        axes[0,col].axhline(75,color='#b74838',ls='--',lw=.8)
        axes[0,col].set(title=tag,ylabel='Local minimum signed margin (mV)')
        axes[1,col].plot(x,[r['metrics']['transition_spread_ui'] for r in rows],'-o',color='#b66d38')
        axes[1,col].axhline(.15,color='#b74838',ls='--',lw=.8)
        axes[1,col].set(ylabel='Local edge spread (UI)',xlabel='Commanded c2g shift (ps)')
        for i,r in enumerate(rows):
            if not r['local_eye_screen']:
                axes[1,col].plot(x[i],r['metrics']['transition_spread_ui'],'rx',ms=10)
        for ax in axes[:,col]:ax.axvline(0,color='gray',ls=':',lw=.7);ax.grid(alpha=.25)
    fig.suptitle('Reduced-swing final rank: calibrated eight-bit voltage replay; not full TX acceptance')
    FIG.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'):fig.savefig(FIG.with_suffix('.'+ext),dpi=170)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,required=True);a=p.parse_args()
    data=collect(a.campaign);draw(data)
    DATA.parent.mkdir(parents=True,exist_ok=True);DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    CATALOG.write_text(json.dumps(dict(data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),campaign=data['campaign'],
        boundary_id=data['boundary_id'],scope=data['scope'],figures=[str(FIG.relative_to(ROOT))+'.'+s for s in ('png','svg')]),indent=2)+'\n')
    print(DATA)


if __name__=='__main__':main()
