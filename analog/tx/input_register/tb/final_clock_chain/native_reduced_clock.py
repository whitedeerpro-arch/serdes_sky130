"""Loaded final-rank replay: extra3/4/5 stages, WT16/R240, no DUT edits.

--prepare registers a child boundary and snapshots TT/FS inputs and decks;
--check validates the snapshot only; --resume runs and collects after smoke.
All three branches are independent ideal-source mathematical experiments.
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
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from serdes_flow import bias, boundary, clock, project, rcorner, serial, spice, watch, waves
from serdes_flow.corners import Condition

ROOT=project.ROOT
HERE=Path(__file__).resolve().parent
NATIVE=ROOT/'analog/tx/input_register/tb/final_retime/native_window.py'
OLD=HERE/'run.py'
TEMPLATE=HERE/'tb_clock_ngspice.cir.in'
PARENT='tx_reduced_final_word18_phase_v1'
STOP=6.5e-9
PRE=4e-9
COUNTS=(3,4,5)


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


native=load('native_phase_parent',NATIVE)
old=load('old_clock_chain',OLD)
helper=native.helper
sha=helper.sha
SOURCES={k:v for k,v in helper.SOURCE_MAP.items() if k not in ('sp','sn')}
SOURCES.update(rp='Vrp',rn='Vrn')
NODEMAP={k:v for k,v in helper.NODES.items() if k not in ('sp','sn')}
NODEMAP.update(rp='xclocks.r2gp',rn='xclocks.r2gn')
REFS={**native.LOCAL_REFS,'sp':'c2gp','sn':'c2gn'}
VECTORS=' '.join('v('+x+')' for x in list(NODEMAP)+[x+str(i) for i in (1,2,3) for x in ('sp','sn','qp','qn')]+[f'xslice{i}.xfinal.{x}' for i in (1,2,3) for x in ('ahp','ahn','bhp','bhn','sap','san')])


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def check_source(entry):
    old.check_template()
    native.verify_boundary(entry)
    if set(entry['points']) != {'tt_v1800_t27','fs_v1650_t85'}:
        raise ValueError('parent must contain explicit TT and FS source')
    for pt in entry['points'].values():
        camp=ROOT/pt['campaign']
        if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):
            raise ValueError('source has active ngspice')
        text=(camp/'execution/physical_tb.cir').read_text()
        expected=['xiso2g r2gp r2gn i2gp i2gn vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400',
                  'xe2g_0 i2gp i2gn e2g_0p e2g_0n vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400',
                  'xe2g_1 e2g_0p e2g_0n e2g_1p e2g_1n vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400',
                  'xe2g_2 e2g_1p e2g_1n e2g_2p e2g_2n vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400',
                  'xout2g e2g_2p e2g_2n c2gp c2gn vbias vdd vss serdes_cml_buffer wn=32 wt=16 rload=240']
        if helper.lines(text,('Xiso2g','Xe2g_0','Xe2g_1','Xe2g_2','Xout2g'))!=expected:
            raise ValueError('source chain differs')
        if helper.lines(text,helper.LOAD_NAMES)!=helper.lines(helper.TEMPLATE.read_text(),helper.LOAD_NAMES):
            raise ValueError('source output load differs')
        source=boundary.input_stage_signature('.subckt cut rp rn\n'+expected[0].replace('r2gp','rp').replace('r2gn','rn')+'\n.ends','cut',('rp','rn'))
        for n in COUNTS:
            if boundary.input_stage_signature(chain_subckt(n),f'native_chain_{n}',('rp','rn'))!=source:
                raise ValueError('first iso input load differs')
    return source


def chain_subckt(count):
    lines=[f'.subckt native_chain_{count} rp rn cp cn vbias vdd vss',
           'Xiso rp rn ip in vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400']
    for i in range(count):
        src='i' if i==0 else f'e{i-1}'
        lines.append(f'Xe{i} {src}p {src}n e{i}p e{i}n vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400')
    lines.append(f'Xout e{count-1}p e{count-1}n cp cn vbias vdd vss serdes_cml_buffer wn=32 wt=16 rload=240')
    return '\n'.join(lines+[f'.ends native_chain_{count}'])+'\n'


def template():
    text=TEMPLATE.read_text()
    text=text.replace('.include "@PROJECT_ROOT@/analog/tx/input_register/spice/final_retime_clock_chain.spice"', '\n'.join(chain_subckt(n) for n in COUNTS))
    for i,n in enumerate(COUNTS,1):
        text=text.replace(f'serdes_tx_final_clock_{i}',f'native_chain_{n}')
    return text


def data(point):
    w=spice.Waves(ROOT/point['raw']);origin=point['origin_s']
    if w.t[0]>origin or w.t[-1]<origin+STOP:raise ValueError('missing prehistory/posthistory')
    t=np.r_[0.,w.t[(w.t>origin)&(w.t<origin+STOP)]-origin,STOP]
    return {'t':t,**{k:np.interp(t+origin,w.t,w[v]) for k,v in NODEMAP.items()},
            **{'ref_'+k:np.interp(t+origin,w.t,w[v]) for k,v in REFS.items()}}


def deck(camp,tag):
    c=Condition.parse(tag); cmds=[]
    with np.load(camp/'inputs'/f'{tag}.npz') as d:
        for key,source in SOURCES.items():cmds.extend(native.commands(source,d['t'],d[key],0.))
    cmds += [f'option temp={c.temp}',f'alter Vtxen dc={c.supply:.12e}',
             spice.skip_output_before(f'tran .5p {STOP:.12e} 0 .5p','.1n'),
             f'write {tag}.raw {VECTORS}','destroy all']
    txt=spice.render(template(),**spice.corner_values(c),CASES='\n'.join(cmds),VECTORS=VECTORS)
    return bias.section(rcorner.to_pdk(txt,camp/'snap'/tag),c.process,'tt')


def prepare(bc_id,campaigns):
    parent=boundary.get(PARENT)
    expected={str((ROOT/p['campaign']).resolve()) for p in parent['points'].values()}
    if len(campaigns)!=2 or {str(p.resolve()) for p in campaigns}!=expected:raise ValueError('explicit sources differ from parent')
    load_signature=check_source(parent)
    entry=dict(id=bc_id,kind='loaded_internal_port_voltage_replay',parent_id=PARENT,parent_sha256=canonical(parent),
               points=parent['points'],nodes=NODEMAP,load=load_signature,output_load=parent['load'],
               independent_mathematical_branches=list(COUNTS),scope='ideal sources; no upstream impedance/feedback; local only')
    prior=boundary.registry().get(bc_id)
    if prior is None:boundary.register(entry)
    elif prior!=entry:raise ValueError('child boundary identity changed')
    camp=ROOT/'results/analog/tx/native_reduced_clock'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False);(camp/'inputs').mkdir();(camp/'prepared').mkdir()
    for tag,pt in entry['points'].items():
        np.savez_compressed(camp/'inputs'/f'{tag}.npz',**data(pt))
        (camp/'prepared'/f'{tag}.cir').write_text(deck(camp,tag))
    files=[Path(__file__).resolve(),NATIVE,native.HELPER,OLD,TEMPLATE,helper.CELL,helper.TEMPLATE,native.COLLECTOR]+[ROOT/x for x in helper.DEPENDENCIES]
    files += [ROOT/'src/serdes_flow'/x for x in ('spice.py','clock.py','waves.py','serial.py','bias.py','rcorner.py','boundary.py','project.py','corners.py','watch.py')]
    files += [ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
    sources={str(p.relative_to(ROOT)):sha(p) for p in files}
    for p in files:
        dest=camp/'execution'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    (camp/'boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
    snapshots={str(p.relative_to(camp)):sha(p) for d in ('inputs','prepared','snap','execution') for p in (camp/d).rglob('*') if p.is_file()}
    plan={'boundary_id':bc_id,'boundary_sha256':canonical(entry),'sources':sources,'snapshots':snapshots,
          'stop_s':STOP,'conditions':list(entry['points']),'counts':list(COUNTS),'pdk_library_sha256':sha(project.model_library()),
          'scope':'three independent branches on prescribed ideal source; no physical parallel topology'}
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return camp


def verify(camp):
    plan=json.loads((camp/'plan.json').read_text()); entry=boundary.get(plan['boundary_id'])
    if canonical(entry)!=plan['boundary_sha256'] or entry!=json.loads((camp/'boundary.json').read_text()):raise ValueError('child boundary changed')
    parent=boundary.get(PARENT)
    if canonical(parent)!=entry['parent_sha256']:raise ValueError('parent boundary changed')
    if (plan['counts']!=list(COUNTS) or plan['stop_s']!=STOP or
            set(plan['conditions'])!=set(entry['points']) or len(plan['conditions'])!=len(entry['points'])):
        raise ValueError('campaign parameters changed')
    if sha(project.model_library())!=plan['pdk_library_sha256']:raise ValueError('PDK changed')
    check_source(parent)
    for rel,h in plan['sources'].items():
        if sha(ROOT/rel)!=h or sha(camp/'execution'/rel)!=h:raise ValueError(f'source changed: {rel}')
    for rel,h in plan['snapshots'].items():
        if sha(camp/rel)!=h:raise ValueError(f'checkpoint changed: {rel}')
    return plan,entry


def out(camp,tag):
    raw=spice.case_output(camp,tag,tag+'.raw',STOP)
    if raw is None or not (raw.parent/'execution.json').is_file():return None
    ex=json.loads((raw.parent/'execution.json').read_text()); expected=sha(camp/'prepared'/f'{tag}.cir')
    if ex.get('exit_code')!=0 or ex.get('timed_out') or ex.get('log_failures'):return None
    if ex.get('condition')!=tag or ex.get('deck_sha256')!=expected or sha(raw.parent/'tb.cir')!=expected:raise ValueError('deck identity mismatch')
    return raw


def measure(camp,tag,pt,raw):
    w=spice.Waves(raw)
    with np.load(camp/'inputs'/f'{tag}.npz') as d:
        inputs={k:float(np.max(abs(w[k]-np.interp(w.t,d['t'],d[k])))) for k in NODEMAP}
        if max(inputs.values())>200e-6:raise ValueError('input mismatch')
        mask=(w.t>=3.5e-9)&(w.t<=6.45e-9)
        base={k:(k+'1' if k in ('sp','sn','qp','qn') else 'xslice1.xfinal.'+k) for k in REFS}
        errors={k:float(np.max(abs(w[v][mask]-np.interp(w.t[mask],d['t'],d['ref_'+k])))) for k,v in base.items()}
        seq=serial.Sequence(np.asarray(pt['bits'],dtype=int),pt['sequence_start_s']-pt['origin_s'],250e-12)
        _,refdetails=serial.fixed_phase_window(d['t'],d['ref_qp']-d['ref_qn'],seq,delay_ui=pt['training_delay_ui'],first_bit=296,end_bit=304)
        ref_fall=clock.edges(d['t'],d['ref_sp']-d['ref_sn'],-1,PRE,STOP-.1e-9)
        rows=[]
        for i,count in enumerate(COUNTS,1):
            fall=clock.edges(w.t,w[f'sp{i}']-w[f'sn{i}'],-1,PRE,STOP-.1e-9)
            shifts=[]
            for e in ref_fall:
                hits=fall[abs(fall-e)<125e-12]
                if len(hits)!=1:raise ValueError('ambiguous c2g clock association')
                shifts.append(float(hits[0]-e))
            if not shifts or len(shifts)!=len(fall):raise ValueError('missing c2g edges')
            delta=float(np.median(shifts))
            metrics,details=serial.fixed_phase_window(w.t,w[f'qp{i}']-w[f'qn{i}'],seq,
                delay_ui=pt['training_delay_ui']+delta/seq.ui_s,first_bit=296,end_bit=304)
            y=w[f'sp{i}']-w[f'sn{i}']; cm=(w[f'sp{i}']+w[f'sn{i}'])/2
            wm=(w.t>=PRE)&(w.t<=STOP-.1e-9)
            rows.append(dict(extra=count,clock_fall_shift_s=delta,clock_shift_min_s=min(shifts),clock_shift_max_s=max(shifts),
                metrics=metrics,details=details,c2g_pp_v=float(np.ptp(y[wm])),c2g_cycles=clock.cycle_amplitudes(w.t,y,PRE,STOP-.1e-9),
                c2g_common_mode_mean_v=waves.time_average(cm[wm],w.t[wm])))
        a={b:r for b,r in zip(refdetails['payload_transition_bits'],refdetails['edge_residual_ui'])}
        b={k:v for k,v in zip(rows[0]['details']['payload_transition_bits'],rows[0]['details']['edge_residual_ui'])}
        edge_error=max((abs((b[k]-v)*seq.ui_s+rows[0]['clock_fall_shift_s']) for k,v in a.items()),default=0.) if a.keys()==b.keys() and a else None
        passed=bool(max(errors.values())<=.005 and edge_error is not None and edge_error<=2e-12)
        return dict(inputs=inputs,baseline_errors_v=errors,baseline_edge_error_s=edge_error,baseline_matches=passed,
                    branches=rows if passed else None,branch_status='measured' if passed else 'ungraded_baseline_failed')


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan,entry=verify(camp)
        if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise ValueError('campaign active')
        missing=[tag for tag in plan['conditions'] if out(camp,tag) is None]
        if missing:
            if len(watch.ngspice_cwds()) + 1 > 4:raise RuntimeError('global quota before smoke')
            tag=missing[0]; text=(camp/'prepared'/f'{tag}.cir').read_text()
            smoke=text.replace(f'tran .5p {STOP:.12e} .1n .5p','tran .5p 1.001n 0 .5p')
            if smoke==text or smoke.count('tran .5p')!=1:raise ValueError('smoke must have one short tran')
            smoke_dir=spice.next_run_dir(camp,'smoke')
            ex=spice.run(smoke,smoke_dir,timeout_s=180)
            if not ex.ok or spice.case_output(camp,smoke_dir.name,tag+'.raw',1.001e-9) is None:raise RuntimeError('smoke failed')
            if len(watch.ngspice_cwds())+min(2,len(missing))>4:raise RuntimeError('global quota')
            jobs=[((camp/'prepared'/f'{tag}.cir').read_text(),spice.next_run_dir(camp,tag),
                   dict(timeout_s=360,meta=dict(condition=tag,boundary_id=plan['boundary_id']))) for tag in missing]
            if any(not ex.ok for ex in spice.run_many(jobs,workers=2,smoke=False)):raise RuntimeError('deck failure; resume missing')
        rows=[]
        for tag in plan['conditions']:
            raw=out(camp,tag); row=dict(condition=tag,status='missing')
            if raw:
                try:row.update(status='measured',raw=str(raw.relative_to(ROOT)),raw_sha256=sha(raw),result=measure(camp,tag,entry['points'][tag],raw))
                except (ValueError,KeyError) as e:row.update(status='analysis_error',error=str(e))
            rows.append(row)
        result=dict(scope=plan['scope'],boundary_id=plan['boundary_id'],boundary_sha256=plan['boundary_sha256'],rows=rows)
        archive=camp/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');archive.mkdir(parents=True,exist_ok=False)
        text=json.dumps(result,indent=2,allow_nan=False)+'\n';(archive/'summary.json').write_text(text)
        tmp=camp/'summary.json.tmp';tmp.write_text(text);tmp.replace(camp/'summary.json')
        if all(r['status']=='measured' and r['result']['baseline_matches'] for r in rows):
            fig,ax=plt.subplots(1,2,figsize=(9,4),layout='constrained')
            for r in rows:
                b=r['result']['branches'];ax[0].plot(COUNTS,[x['clock_fall_shift_s']*1e12 for x in b],marker='o',label=r['condition'])
                ax[1].plot(COUNTS,[x['metrics']['transition_spread_ui'] for x in b],marker='o',label=r['condition'])
            ax[0].set(xlabel='Extra stages',ylabel='c2g shift from source (ps)');ax[1].set(xlabel='Extra stages',ylabel='8-bit transition spread (UI)')
            ax[1].axhline(.15,color='red',ls='--');ax[0].legend();fig.savefig(archive/'clock_stages.png',dpi=160);plt.close(fig)
        return camp


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path)
    p.add_argument('--boundary-id');p.add_argument('--campaign',type=Path,action='append',default=[])
    a=p.parse_args()
    if a.prepare:
        if not a.boundary_id:p.error('--prepare requires --boundary-id and two --campaign')
        print(prepare(a.boundary_id,a.campaign))
    elif a.check:verify(a.check.resolve());print('checkpoint valid; no ngspice')
    else:print(resume(a.resume.resolve()))


if __name__=='__main__':main()
