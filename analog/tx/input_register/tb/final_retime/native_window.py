"""Registered final-rank phase study from verified native full-TX waveforms.

Register explicit sources, prepare immutable inputs, run baselines, then scan.
Every deck has one PVT condition; phase cases share model loading. No DUT edit.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

import numpy as np
from serdes_flow import bias, boundary, clock, project, rcorner, serial, spice, watch, waves
from serdes_flow.corners import Condition

ROOT=project.ROOT
HERE=Path(__file__).resolve().parent
HELPER=HERE/'window.py'
COLLECTOR=ROOT/'verification/plotting/tx_parallel_serializer.py'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result)
    return result


helper=module('original_final_window',HELPER)
collector=module('native_full_collector',COLLECTOR)
sha=helper.sha
STOP=6.5e-9
PRE=4e-9
OFFSETS=(-20,0,10,20,40,60)
FIRST,END=296,304
EVAL=(3.5e-9,6.45e-9)
LOCAL_REFS={**helper.REFS,'sap':'xtx.xtree.xr4_0.sap','san':'xtx.xtree.xr4_0.san'}
VECTORS=helper.VECTORS+' v(xslice.xfinal.sap) v(xslice.xfinal.san)'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def fixture_identity():
    return dict(consumer_sha256=sha(helper.CELL),template_sha256=sha(helper.TEMPLATE),
                direct_load=helper.lines(helper.TEMPLATE.read_text(),helper.LOAD_NAMES),
                pdk_installation_id=project.pdk_installation_id(),model_library_sha256=sha(project.model_library()))


def register(camps,bc_id):
    helper.check_source_map()
    points={}
    for camp in camps:
        camp=camp.resolve();case=collector.collect(camp)
        if (case['clock_extra_2g'],case['clock_output_wt'],case['clock_output_r'])!=(3,16,240):
            raise ValueError('requires extra3 WT16/R240 full-TX sources')
        if any(case[k] is not True for k in ('input_boundary_ok','halfword_hold_ok','behavioral_tags_align')) or not case['counter']['counting']:
            raise ValueError('source word interface or counter failed')
        plan=json.loads((camp/'plan.json').read_text());summary=json.loads((camp/'summary.json').read_text())
        if plan['pdk_installation_id']!=project.pdk_installation_id():raise ValueError('source PDK differs')
        cells=helper.validate_source_cell(camp,plan,snapshot_root='execution')
        for rel in helper.DEPENDENCIES:
            if sha(ROOT/rel)!=plan['snapshot_files']['execution/'+rel]:
                raise ValueError(f'consumer physical dependency differs: {rel}')
        if helper.lines((camp/'execution/physical_tb.cir').read_text(),helper.LOAD_NAMES)!=fixture_identity()['direct_load']:
            raise ValueError('direct output load differs')
        rows=[r for r in summary['captures'] if r['payload_valid']]
        if len(rows)<=18 or rows[18]['word']!=0xdad9:raise ValueError('requires source word18=0xdad9')
        raw=ROOT/case['waveform'];helper.validate_execution(raw);w=spice.Waves(raw)
        af=clock.edges(w.t,w['c250p']-w['c250n'],-1)
        af=af[af>=rows[18]['capture_s']]
        bf=clock.edges(w.t,w['c250p']-w['c250n'],1)
        bf=bf[bf>af[0]] if len(af) else []
        if not len(bf):raise ValueError('B halfword edge missing')
        edge=float(bf[0]);origin=edge-PRE
        if origin<w.t[0] or origin+STOP>w.t[-1]:raise ValueError('source window incomplete')
        tag=case['condition']
        if tag in points:raise ValueError('duplicate source condition')
        points[tag]=dict(condition=tag,campaign=str(camp.relative_to(ROOT)),
            raw=str(raw.relative_to(ROOT)),raw_sha256=sha(raw),source_plan_sha256=sha(camp/'plan.json'),
            source_summary_sha256=sha(camp/'summary.json'),source_hashes=case['hashes'],source_cells=cells,
            halfword_b_edge_s=edge,origin_s=origin,sequence_start_s=case['sequence_start_s'],
            training_delay_ui=summary['outputs']['serializer']['check']['training_delay_ui'],
            bits=[(r['word']>>i)&1 for r in rows for i in range(16)])
    entry=dict(id=bc_id,kind='loaded_internal_port_voltage_replay',
        description='Reduced-swing full-TX final rank, word18 B halfword including slot8 and unchanged-even slot14.',
        upstream=dict(module='tx.serializer',revision='capture_v3_extra3_WT16_R240',campaigns=[p['campaign'] for p in points.values()]),
        nodes=helper.NODES,load=fixture_identity(),points=points,
        processing='4ns history plus 2.5ns after B edge; shift only recorded c2g pair; 10uV bounded PWL with 100as time grid.',
        validation=dict(state='requires_zero_shift_fidelity',voltage_error_v=.005,input_error_v=200e-6,edge_error_s=2e-12),
        valid_while=['identical final rank and direct driver/pad/RLC16 load; PDK R tt',
                     'ideal recorded voltage sources omit upstream impedance and feedback',
                     'phase from full-run training plus commanded shift; no local payload fitting',
                     'local eight-bit observation only, not full serializer, PVT, mismatch or noise qualification'])
    old=boundary.registry().get(bc_id)
    if old is None:boundary.register(entry)
    elif old!=entry:raise ValueError('boundary id already has different identity')
    return entry


def verify_boundary(entry):
    if entry['load']!=fixture_identity():raise ValueError('consumer load or PDK changed')
    for point in entry['points'].values():
        camp=ROOT/point['campaign'];plan=json.loads((camp/'plan.json').read_text())
        if sha(camp/'plan.json')!=point['source_plan_sha256'] or sha(camp/'summary.json')!=point['source_summary_sha256']:
            raise ValueError('source metadata changed')
        if sha(ROOT/point['raw'])!=point['raw_sha256']:raise ValueError('source raw changed')
        helper.validate_execution(ROOT/point['raw'])
        for rel,h in plan['snapshot_files'].items():
            if sha(camp/rel)!=h:raise ValueError(f'source checkpoint changed: {rel}')
        if helper.validate_source_cell(camp,plan,snapshot_root='execution')!=point['source_cells']:raise ValueError('source cells changed')
        for rel in helper.DEPENDENCIES:
            if sha(ROOT/rel)!=plan['snapshot_files']['execution/'+rel]:raise ValueError('physical cell changed')


def event_data(point):
    w=spice.Waves(ROOT/point['raw']);origin=point['origin_s']
    t=np.r_[0.,w.t[(w.t>origin)&(w.t<origin+STOP)]-origin,STOP]
    data={'t':t}
    data.update({n:np.interp(t+origin,w.t,w[node]) for n,node in helper.NODES.items()})
    data.update({'ref_'+n:np.interp(t+origin,w.t,w[node]) for n,node in LOCAL_REFS.items()})
    return data


def name(offset):
    return f'phase_{offset:+d}ps'


def commands(source,t,y,offset):
    ts,ys=waves.shift_pwl(t,y,offset,tolerance_v=1e-5,time_quantum_s=1e-16)
    vals=np.column_stack((ts,ys)).ravel()
    out=[f'alter {source} dc={ys[0]:.12e}']
    if len(vals)<=360:
        return out+['alter @'+source+'[pwl] = [ '+' '.join(f'{v:.12e}' for v in vals)+' ]']
    return out+[f'let replay_pwl=vector({len(vals)})']+[f'let replay_pwl[{i}]={v:.12e}' for i,v in enumerate(vals)]+[
        'alter @'+source+'[pwl] = replay_pwl','unlet replay_pwl']


def deck(camp,tag,offsets):
    c=Condition.parse(tag);cmd=[]
    with np.load(camp/'inputs'/f'{tag}.npz') as data:
        for offset in offsets:
            for n,source in helper.SOURCE_MAP.items():
                cmd+=commands(source,data['t'],data[n],offset*1e-12 if n in ('sp','sn') else 0.)
            cmd += [f'option temp={c.temp}',f'alter Vtxen dc={c.supply:.12e}',
                    spice.skip_output_before(f'tran .5p {STOP:.12e} 0 .5p','.1n'),
                    f'write {name(offset)}.raw {VECTORS}','destroy all']
    text=spice.render(helper.TEMPLATE,**spice.corner_values(c),CASES='\n'.join(cmd),VECTORS=VECTORS)
    return bias.section(rcorner.to_pdk(text,camp/'snap'/tag),c.process,'tt')


def prepare(bc_id):
    entry=boundary.get(bc_id);verify_boundary(entry)
    camp=ROOT/'results/analog/tx/reduced_phase_window'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False);(camp/'inputs').mkdir();(camp/'prepared').mkdir()
    for tag,point in entry['points'].items():
        np.savez_compressed(camp/'inputs'/f'{tag}.npz',**event_data(point))
        for stage,offsets in [('baseline',[0]),('scan',[x for x in OFFSETS if x])]:
            (camp/'prepared'/f'{tag}_{stage}.cir').write_text(deck(camp,tag,offsets))
    files=[Path(__file__).resolve(),HELPER,COLLECTOR,helper.CELL,helper.TEMPLATE]+[ROOT/x for x in helper.DEPENDENCIES]
    files += [ROOT/'src/serdes_flow'/x for x in ('spice.py','clock.py','waves.py','serial.py','bias.py','rcorner.py','boundary.py','project.py','corners.py','watch.py')]
    files += [ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
    sources={str(p.relative_to(ROOT)):sha(p) for p in files}
    for p in files:
        dest=camp/'execution'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    (camp/'boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
    snapshots={str(p.relative_to(camp)):sha(p) for d in ('inputs','prepared','snap','execution') for p in (camp/d).rglob('*') if p.is_file()}
    plan=dict(boundary_id=bc_id,boundary_sha256=digest(entry),sources=sources,snapshots=snapshots,
              stop_s=STOP,evaluation_window_s=EVAL,offsets_ps=OFFSETS,conditions=list(entry['points']),
              first_bit=FIRST,end_bit=END,workers=2,cases=[dict(condition=t,offset_ps=o,name=name(o)) for t in entry['points'] for o in OFFSETS])
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return camp


def verify(camp):
    plan=json.loads((camp/'plan.json').read_text());entry=boundary.get(plan['boundary_id'])
    if entry!=json.loads((camp/'boundary.json').read_text()) or digest(entry)!=plan['boundary_sha256']:raise ValueError('boundary changed')
    verify_boundary(entry)
    for rel,h in plan['sources'].items():
        if sha(ROOT/rel)!=h or sha(camp/'execution'/rel)!=h:raise ValueError(f'analysis or source changed: {rel}')
    for rel,h in plan['snapshots'].items():
        if sha(camp/rel)!=h:raise ValueError(f'prepared checkpoint changed: {rel}')
    if plan['offsets_ps']!=list(OFFSETS) or plan['stop_s']!=STOP or plan['first_bit']!=FIRST or plan['end_bit']!=END:
        raise ValueError('experiment parameters changed')
    return plan,entry


def output(camp,tag,offset):
    raw=spice.case_output(camp,tag,name(offset)+'.raw',STOP)
    if raw is None or not (raw.parent/'execution.json').exists():return None
    ex=json.loads((raw.parent/'execution.json').read_text())
    if ex.get('exit_code')!=0 or ex.get('timed_out') or ex.get('log_failures'):return None
    offsets=ex.get('offsets_ps')
    if not isinstance(offsets,list) or not offsets or len(offsets)!=len(set(offsets)) or set(offsets)-set(OFFSETS):
        raise ValueError('execution contains an undeclared phase case')
    expected=hashlib.sha256(deck(camp,tag,ex['offsets_ps']).encode()).hexdigest()
    if ex['condition']!=tag or offset not in ex['offsets_ps'] or sha(raw.parent/'tb.cir')!=expected or ex['deck_sha256']!=expected:
        raise ValueError('execution deck or case identity differs')
    return raw


def measure(raw,point,offset,data_path):
    helper.validate_execution(raw);w=spice.Waves(raw)
    if w.t[-1]<STOP*(1-1e-6):raise ValueError('truncated local waveform')
    with np.load(data_path) as d:
        inputs={n:float(np.max(abs(w[n]-np.interp(w.t-(offset*1e-12 if n in ('sp','sn') else 0),d['t'],d[n])))) for n in helper.NODES}
        if max(inputs.values())>200e-6:raise ValueError('input PWL reproduction failed')
        keep=(w.t>=EVAL[0])&(w.t<=EVAL[1])
        local={**{n:n for n in ('qp','qn')},**{n:'xslice.xfinal.'+n for n in ('ahp','ahn','bhp','bhn','sap','san')}}
        errors={n:float(np.max(abs(w[node][keep]-np.interp(w.t[keep],d['t'],d['ref_'+n])))) for n,node in local.items()}
        seq=serial.Sequence(np.asarray(point['bits'],dtype=int),point['sequence_start_s']-point['origin_s'],250e-12)
        reference,ref_details=serial.fixed_phase_window(d['t'],d['ref_qp']-d['ref_qn'],seq,
                delay_ui=point['training_delay_ui'],first_bit=FIRST,end_bit=END)
        metrics,details=serial.fixed_phase_window(w.t,w['qp']-w['qn'],seq,
                delay_ui=point['training_delay_ui']+offset*1e-12/seq.ui_s,first_bit=FIRST,end_bit=END)
    residuals={b:r for b,r in zip(details['payload_transition_bits'],details['edge_residual_ui'])}
    ref_residuals={b:r for b,r in zip(ref_details['payload_transition_bits'],ref_details['edge_residual_ui'])}
    edge_error=max((abs(residuals[b]-r)*seq.ui_s for b,r in ref_residuals.items()),default=0.) if residuals.keys()==ref_residuals.keys() else None
    calibrated=bool(offset==0 and max(errors.values())<=.005 and edge_error is not None and edge_error<=2e-12
                    and metrics['functional']==reference['functional'])
    c2g=w['sp']-w['sn'];clock_mask=(w.t>=PRE)&(w.t<=STOP-.1e-9)
    cm=(w['sp']+w['sn'])/2
    local_closes=clock.edges(w.t,w['xslice.xfinal.sap']-w['xslice.xfinal.san'],-1,PRE,PRE+2e-9)
    return dict(input_max_error_v=inputs,baseline_voltage_error_v=errors if offset==0 else None,
        baseline_edge_error_s=edge_error if offset==0 else None,baseline_matches=calibrated if offset==0 else None,
        source_window_metrics=reference,metrics=metrics,details=details,
        local_eye_screen=bool(metrics['functional'] and metrics['minimum_signed_margin_v']>=.075
                              and metrics['transition_spread_ui'] is not None and metrics['transition_spread_ui']<=.15),
        actual_local_a_closes_s=local_closes.tolist(),
        c2g_pp_v=float(np.ptp(c2g[clock_mask])),c2g_cycles=clock.cycle_amplitudes(w.t,c2g,PRE,STOP-.1e-9),
        c2g_common_mode_mean_v=waves.time_average(cm[clock_mask],w.t[clock_mask]),
        scope='eight local bits, phase from original full-run training plus commanded shift; no complete serializer acceptance')


def resume(camp,stage):
    camp=camp.resolve()
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan,entry=verify(camp)
        if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign still running')
        if stage=='scan':
            for tag,point in entry['points'].items():
                raw=output(camp,tag,0)
                if raw is None or not measure(raw,point,0,camp/'inputs'/f'{tag}.npz')['baseline_matches']:
                    raise ValueError(f'{tag}: original loaded baseline missing or failed')
        chosen=[0] if stage=='baseline' else [x for x in OFFSETS if x]
        jobs=[]
        for tag in plan['conditions']:
            missing=[x for x in chosen if output(camp,tag,x) is None]
            if missing:
                jobs.append((deck(camp,tag,missing),spice.next_run_dir(camp,tag),dict(timeout_s=180+120*len(missing),
                    meta=dict(condition=tag,offsets_ps=missing,boundary_id=plan['boundary_id']))))
        if jobs:
            if len(watch.ngspice_cwds())+min(2,len(jobs))>4:raise RuntimeError('global ngspice quota would exceed 4')
            # A multi-tran deck cannot use the generic smoke_deck directly:
            # only its first tran would be shortened. Render one case first.
            first=jobs[0][2]['meta'];tag=first['condition'];offset=first['offsets_ps'][0]
            smoke_dir=spice.next_run_dir(camp,'smoke')
            smoke=spice.run(spice.smoke_deck(deck(camp,tag,[offset])),smoke_dir,timeout_s=180)
            if not smoke.ok or spice.case_output(smoke_dir.parent,smoke_dir.name,name(offset)+'.raw',1.1e-9) is None:
                raise RuntimeError('single-case smoke failed')
            executions=spice.run_many(jobs,workers=2,smoke=False)
            if any(not ex.ok for ex in executions):raise RuntimeError('incomplete deck; preserve logs and resume missing cases')
        rows=[]
        for case in plan['cases']:
            tag=case['condition'];offset=case['offset_ps'];raw=output(camp,tag,offset)
            row=dict(case,status='missing')
            if raw is not None:
                try:
                    row.update(status='measured',waveform=str(raw.relative_to(ROOT)),waveform_sha256=sha(raw),
                        result=measure(raw,entry['points'][tag],offset,camp/'inputs'/f'{tag}.npz'))
                except (ValueError,KeyError) as exc:row.update(status='analysis_error',error=str(exc))
            rows.append(row)
        result=dict(scope='Calibrated local voltage-replay phase scan; no full-TX or PVT/noise/mismatch qualification',
                    boundary_id=plan['boundary_id'],boundary_sha256=plan['boundary_sha256'],rows=rows)
        archive=camp/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');archive.mkdir(parents=True,exist_ok=False)
        text=json.dumps(result,indent=2,allow_nan=False)+'\n';(archive/'summary.json').write_text(text)
        tmp=camp/'summary.json.tmp';tmp.write_text(text);tmp.replace(camp/'summary.json')
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--register',action='store_true');g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--check',action='store_true')
    p.add_argument('--boundary-id');p.add_argument('--campaign',type=Path,action='append');p.add_argument('--stage',choices=('baseline','scan'))
    a=p.parse_args()
    if a.resume:
        if not a.stage:p.error('--resume requires --stage')
        result=resume(a.resume,a.stage)
        print(json.dumps([dict(condition=r['condition'],offset_ps=r['offset_ps'],status=r['status'],
                              baseline=r.get('result',{}).get('baseline_matches'),screen=r.get('result',{}).get('local_eye_screen')) for r in result['rows']]))
    elif not a.boundary_id:p.error('--boundary-id required')
    elif a.register:
        if not a.campaign:p.error('--register requires explicit --campaign')
        print(register(a.campaign,a.boundary_id)['id'])
    elif a.prepare:print(prepare(a.boundary_id))
    else:verify_boundary(boundary.get(a.boundary_id));print('registered native source and load identities valid; no ngspice run')


if __name__=='__main__':main()
