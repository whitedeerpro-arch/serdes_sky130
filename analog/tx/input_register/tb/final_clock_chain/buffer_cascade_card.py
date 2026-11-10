"""Prepare/check the Xe2/Xe3 and extra5 cascade experiment; resume explicitly runs ngspice.

Prepare/check do not simulate; resume requires a registered reviewed boundary.
The eight-bit window checks the fixed contract, not a full independent bit mapping.
"""
import argparse
import fcntl
import importlib.util
import json
import re
import shutil
import time
import uuid
from pathlib import Path

import numpy as np

from serdes_flow import boundary, clock, serial, spice, watch, waves

ROOT = Path(__file__).resolve().parents[5]
JOINT = Path(__file__).with_name('buffer_joint_card.py')
PARENT = ROOT / 'results/analog/tx/buffer_joint_card/20261110T163621Z_5e8b82b2'
DATA = ROOT / 'docs/data/tx_buffer_joint.json'
spec = importlib.util.spec_from_file_location('frozen_joint', JOINT)
joint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(joint)
old = joint.old
BRANCHES = ('baseline', 'two_stages', 'extra5')


def parent_check():
    joint.check(PARENT, registered=True)
    data = json.loads(DATA.read_text())
    if data['campaign'] != str(PARENT.relative_to(ROOT)):
        raise ValueError('wrong calibration campaign')
    for key, path in (('plan_sha256', PARENT/'plan.json'), ('joint_plan_sha256', PARENT/'joint_plan.json'),
                      ('runner_sha256', JOINT), ('helper_sha256', joint.HELPER),
                      ('summary_sha256', ROOT/data['summary'])):
        if old.digest(path) != data[key]: raise ValueError(f'parent {key} changed')
    summary = json.loads((ROOT/data['summary']).read_text())
    if summary['status'] != 'measured' or {r['condition'] for r in summary['rows']} != set(old.TAGS):
        raise ValueError('parent incomplete')
    for row in summary['rows']:
        tag = row['condition']
        raw = old.completed(PARENT, tag)
        if raw is None or old.digest(raw) != row['raw_sha256'] or not row['result']['baseline_matches']:
            raise ValueError('parent raw or baseline failed')
        for name, digest in data['evidence'][tag].items():
            path = raw if name == tag+'.raw' else raw.parent/name
            if old.digest(path) != digest: raise ValueError(f'parent evidence changed: {path}')
    return {'data_sha256': old.digest(DATA), 'joint_plan_sha256': old.digest(PARENT/'joint_plan.json'),
            'plan_sha256': old.digest(PARENT/'plan.json'), 'summary_sha256': data['summary_sha256'],
            'evidence': data['evidence']}


def check_decks(camp):
    for tag in old.TAGS:
        text = (camp/'prepared'/f'{tag}.cir').read_text()
        for i in range(1, 4):
            match = re.search(rf'(?ms)^\.subckt local_chain_{i} .*?^\.ends local_chain_{i}$', text)
            if not match: raise ValueError('missing branch')
            block = match.group()
            for n in range(5):
                wt, r = ('12.8','320') if (i == 3 or i == 2 and n in (2,3)) else ('16','400')
                lines = re.findall(rf'(?m)^Xe{n} .*$', block)
                if len(lines) != 1 or not lines[0].endswith(f'wn=24 wt={wt} rload={r}'):
                    raise ValueError(f'wrong branch {i} Xe{n}')
            if 'Xiso rp rn ip in vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400' not in block:
                raise ValueError('isolation changed')
            if 'Xout e4p e4n cp cn vbias vdd vss serdes_cml_buffer wn=32 wt=16 rload=240' not in block:
                raise ValueError('output stage changed')
        chains = [re.search(rf'(?ms)^\.subckt local_chain_{i} .*?^\.ends local_chain_{i}$', text).group() for i in (1,2,3)]
        normalize = lambda s: re.sub(r'(?m)^(Xe[0-4] .*? wn=24) wt=\S+ rload=\S+$', r'\1 PARAMS', re.sub(r'local_chain_[123]', 'local_chain', s))
        if len({normalize(s) for s in chains}) != 1: raise ValueError('other branch differences')
        for i in (1,2,3):
            for n in ('ip','in','e0p','e0n','e1p','e1n','e2p','e2n','e3p','e3n','e4p','e4n'):
                probe = f'v(xclock{i}.{n})'
                if text.count(probe) < 2: raise ValueError(f'missing saved probe {probe}')


def prepare():
    identity = parent_check()
    camp = ROOT/'results/analog/tx/buffer_cascade_card'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False)
    for name in ('inputs','snap','prepared','runtime'): shutil.copytree(PARENT/name, camp/name)
    for tag in old.TAGS:
        path = camp/'prepared'/f'{tag}.cir'
        text = path.read_text().replace(str(PARENT/'snap'/tag),str(camp/'snap'/tag))
        def alter(match):
            i = int(match.group(1)); block = match.group()
            for n in range(5):
                wt,r = ('12.8','320') if (i == 3 or i == 2 and n in (2,3)) else ('16','400')
                block,count = re.subn(rf'(?m)^(Xe{n} .*? wn=24) wt=\S+ rload=\S+$',rf'\g<1> wt={wt} rload={r}',block)
                if count != 1: raise ValueError('Xe instance missing')
            return block
        text,count = re.subn(r'(?ms)^\.subckt local_chain_([123]) .*?^\.ends local_chain_\1$',alter,text)
        if count != 3: raise ValueError('branch missing')
        # Add only absent vectors, once to .save and once to write.
        probes = ' '.join(f'v(xclock{i}.{n})' for i in (1,2,3) for n in ('ip','in','e0p','e0n','e4p','e4n'))
        text,n1 = re.subn(r'(?m)^(\.save .+)$',lambda m:m.group(1)+' '+probes,text)
        text,n2 = re.subn(r'(?m)^(write '+tag+r'\.raw .+)$',lambda m:m.group(1)+' '+probes,text)
        if n1 != 1 or n2 != 1: raise ValueError('probe insertion failed')
        path.write_text(text)
    parent_bc = json.loads((PARENT/'boundary_proposal.json').read_text())
    proposal = dict(parent_bc,id='tx_i17_extra5_xe2_xe3_cascade_proposal',parent_id=parent_bc['id'],
                    parent_sha256=old.canonical(parent_bc),independent_mathematical_branches=list(BRANCHES),
                    scope='ideal recorded PWL; cascade feasibility only; no upstream impedance or new real-bias validation')
    (camp/'boundary_proposal.json').write_text(json.dumps(proposal,indent=2)+'\n')
    for src,name in ((JOINT,'joint_helper.py'),(joint.HELPER,'local_helper.py'),(Path(__file__),'cascade_helper.py'),(DATA,'calibration.json')):
        shutil.copyfile(src,camp/name)
    plan = json.loads((PARENT/'plan.json').read_text())
    plan['snapshots'] = {str(p.relative_to(camp)):old.digest(p) for p in camp.rglob('*') if p.is_file()}
    plan['status'] = 'prepared_not_simulated'
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    manifest = {'parent':str(PARENT.relative_to(ROOT)),'parent_identity':identity,
                'plan_sha256':old.digest(camp/'plan.json'),'script_sha256':old.digest(Path(__file__)),
                'joint_helper_sha256':old.digest(JOINT),'branches':list(BRANCHES),
                'prediction':'No cascade prediction; parent joint A measured single-stage only.',
                'pending':['registered child boundary','baseline and candidate measurements'],
                'ungraded':['resistance','power','noise','upstream impedance','new bias','full TX','I-17 closure']}
    (camp/'cascade_plan.json').write_text(json.dumps(manifest,indent=2)+'\n')
    check(camp)
    return camp


def check(camp, registered=False):
    manifest=json.loads((camp/'cascade_plan.json').read_text())
    if (manifest['script_sha256'] != old.digest(Path(__file__)) or manifest['joint_helper_sha256'] != old.digest(JOINT)
            or manifest['plan_sha256'] != old.digest(camp/'plan.json') or manifest['parent_identity'] != parent_check()):
        raise ValueError('cascade or parent identity changed')
    old.check(camp, registered=registered)
    proposal=json.loads((camp/'boundary_proposal.json').read_text())
    if old.canonical(boundary.get(proposal['parent_id'])) != proposal['parent_sha256']:
        raise ValueError('parent boundary changed')
    check_decks(camp)
    return manifest


def offsets(target, reference):
    shifts=[]
    for edge in reference:
        hits=target[np.abs(target-edge)<125e-12]
        if len(hits)!=1: raise ValueError('ambiguous or missing clock edge association')
        shifts.append(float(hits[0]-edge))
    if not shifts or len(target)!=len(shifts): raise ValueError('clock edge count differs')
    return shifts


def measure(camp, tag, raw, point):
    w=spice.Waves(raw); ref=spice.Waves(old.SOURCE/tag/(tag+'.raw'))
    with np.load(camp/'inputs'/f'{tag}.npz') as d:
        inputs={k:float(np.max(np.abs(w[k]-np.interp(w.t,d['t'],d[k])))) for k in
                ('ap','an','bp','bn','vbias','vbias_logic','vdd','rp','rn')}
        source_fall=clock.edges(d['t'],d['ref_sp']-d['ref_sn'],-1,4e-9,old.STOP-.1e-9)
    mask=(w.t>=3.5e-9)&(w.t<=6.45e-9)
    pairs=[(n+'1',n+'3') for n in ('sp','sn','qp','qn')]
    pairs += [(f'xslice1.xfinal.{n}',f'xslice3.xfinal.{n}') for n in ('ahp','ahn','bhp','bhn','sap','san')]
    errors={a:float(np.max(np.abs(w[a][mask]-np.interp(w.t[mask],ref.t,ref[b])))) for a,b in pairs}
    result={'input_max_error_v':inputs,'baseline_max_error_v':errors,'baseline_matches':False,
            'branches':[], 'ungraded':['physical resistance','tail Vdsat and Id','current and power','noise']}
    if max(inputs.values())>200e-6 or max(errors.values())>.005:
        result['status']='ungraded_baseline_failed'; return result
    try:
        seq=serial.Sequence(np.asarray(point['bits'],dtype=int),point['sequence_start_s']-point['origin_s'],250e-12)
        ref_fall=clock.edges(ref.t,ref['sp3']-ref['sn3'],-1,4e-9,old.STOP-.1e-9)
        previous=float(np.median(offsets(ref_fall,source_fall)))
        old_metrics,old_details=serial.fixed_phase_window(ref.t,ref['qp3']-ref['qn3'],seq,
            delay_ui=point['training_delay_ui']+previous/seq.ui_s,first_bit=296,end_bit=304)
        fall=clock.edges(w.t,w['sp1']-w['sn1'],-1,4e-9,old.STOP-.1e-9)
        delta=float(np.median(offsets(fall,ref_fall)))
        total=float(np.median(offsets(fall,source_fall)))
        bm,bd=serial.fixed_phase_window(w.t,w['qp1']-w['qn1'],seq,
            delay_ui=point['training_delay_ui']+total/seq.ui_s,first_bit=296,end_bit=304)
        a=dict(zip(old_details['payload_transition_bits'],old_details['edge_residual_ui']))
        b=dict(zip(bd['payload_transition_bits'],bd['edge_residual_ui']))
        error=max((abs((b[k]-v)*seq.ui_s+delta) for k,v in a.items()),default=None) if a.keys()==b.keys() else None
        result.update(baseline_serial_edge_error_s=error,old_extra5_metrics=old_metrics,
                      source_to_old_extra5_clock_shift_s=previous)
        if error is None or error>2e-12 or bm['bit_errors']!=old_metrics['bit_errors']:
            result['status']='ungraded_baseline_failed'; return result
    except (ValueError,KeyError,IndexError) as exc:
        result.update(status='ungraded_baseline_failed',baseline_error=f'{type(exc).__name__}: {exc}'); return result
    result['baseline_matches']=True
    wm=(w.t>=4e-9)&(w.t<=old.STOP-.1e-9)
    for i,label in enumerate(BRANCHES,1):
        row={'branch':label,'status':'measurement_complete','nodes':{}}
        result['branches'].append(row)
        try:
            for stage,pos,neg in [('iso','ip','in')]+[(f'e{k}',f'e{k}p',f'e{k}n') for k in range(5)]+[('c2g',f'sp{i}',f'sn{i}')]:
                prefix='' if stage=='c2g' else f'xclock{i}.'
                p,n=w[prefix+pos],w[prefix+neg]; diff=p-n; cm=(p+n)/2
                item={'differential_pp_v':float(np.ptp(diff[wm])),
                      'common_mode_mean_v':float(waves.time_average(cm[wm],w.t[wm]))}
                row['nodes'][stage]=item
                try: item['cycles']=clock.cycle_amplitudes(w.t,diff,4e-9,old.STOP-.1e-9)
                except (ValueError,IndexError) as exc: item['cycles_error']=f'{type(exc).__name__}: {exc}'
            fall=clock.edges(w.t,w[f'sp{i}']-w[f'sn{i}'],-1,4e-9,old.STOP-.1e-9)
            shifts=offsets(fall,ref_fall); total_shifts=offsets(fall,source_fall)
            total=float(np.median(total_shifts))
            metrics,details=serial.fixed_phase_window(w.t,w[f'qp{i}']-w[f'qn{i}'],seq,
                delay_ui=point['training_delay_ui']+total/seq.ui_s,first_bit=296,end_bit=304)
            row.update(clock_fall_shift_s=float(np.median(shifts)),clock_shift_min_s=min(shifts),
                       clock_shift_max_s=max(shifts),clock_total_shift_from_source_s=total,
                       metrics=metrics,details=details)
            if not metrics['functional']:
                row.update(status='functional_failure',error='8-bit fixed-contract functional check failed',
                           functional_detail={k:metrics.get(k) for k in ('bit_errors','missing_transitions','extra_crossings')})
        except (ValueError,KeyError,IndexError) as exc:
            row.update(status='functional_failure',error=f'{type(exc).__name__}: {exc}')
    result['status']='candidate_functional_failure' if any(x['status']=='functional_failure' for x in result['branches'][1:]) else 'measurement_complete'
    if result['branches'][0]['status']!='measurement_complete':
        result.update(status='ungraded_baseline_failed',baseline_matches=False)
        result['branches']=[]
    return result


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive=camp/'analysis'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8])
        archive.mkdir(parents=True,exist_ok=False)
        report={'status':'failed','scope':'ideal recorded PWL; local cascade feasibility only','rows':[]}
        try:
            check(camp,registered=True)
            if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign active')
            points=json.loads((PARENT/'boundary_proposal.json').read_text())['points']
            for tag in old.TAGS:
                raw=old.completed(camp,tag)
                if raw is None:
                    if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit before smoke')
                    deck=(camp/'prepared'/f'{tag}.cir').read_text()
                    smoke=deck.replace('tran .5p 6.500000000000e-09 .1n .5p','tran .5p 1.001n 0 .5p')
                    if smoke==deck: raise ValueError('smoke tran missing')
                    sd=spice.next_run_dir(camp,'smoke_'+tag)
                    ex=spice.run(smoke,sd,timeout_s=180,meta={'condition':tag,'kind':'smoke'})
                    if not ex.ok or spice.case_output(camp,sd.name,tag+'.raw',1.001e-9) is None: raise RuntimeError(f'smoke failed: {sd}')
                    if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit before full')
                    run=spice.next_run_dir(camp,tag)
                    ex=spice.run(deck,run,timeout_s=360,meta={'condition':tag,'kind':'full'})
                    if not ex.ok: raise RuntimeError(f'full failed: {run}')
                    raw=old.completed(camp,tag)
                    if raw is None: raise RuntimeError(f'incomplete output: {tag}')
                row={'condition':tag,'raw':str(raw.relative_to(ROOT)),'raw_sha256':old.digest(raw)}
                report['rows'].append(row); row['result']=measure(camp,tag,raw,points[tag])
            statuses=[r['result']['status'] for r in report['rows']]
            report['status']='ungraded_baseline_failed' if 'ungraded_baseline_failed' in statuses else ('candidate_functional_failure' if 'candidate_functional_failure' in statuses else 'measurement_complete')
        except Exception as exc:
            report['error']=f'{type(exc).__name__}: {exc}'; raise
        finally:
            (archive/'summary.json').write_text(json.dumps(report,indent=2,default=old.json_default,allow_nan=False)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__); g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path)
    a=p.parse_args()
    if a.prepare: print(prepare())
    elif a.check: print(json.dumps(check(a.check.resolve()),indent=2))
    else: print(json.dumps(resume(a.resume.resolve()),indent=2,default=old.json_default,allow_nan=False))


if __name__ == '__main__': main()
