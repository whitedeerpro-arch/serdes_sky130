"""Prepare/check a three-branch per-stage extra5 matrix profile; resume explicitly runs ngspice.

The eight-bit result checks a fixed contract; it is not full TX bit mapping.
"""
import argparse
import fcntl
import importlib.util
import json
import math
import re
import shutil
import time
import uuid
from pathlib import Path

from serdes_flow import boundary, spice, watch
from serdes_flow.clock_profiles import normalize_extra

ROOT=Path(__file__).resolve().parents[5]
CASCADE=Path(__file__).with_name('buffer_cascade_card.py')
DEFAULT=Path(__file__).with_name('size_profiles_taper.json')
GENERIC=Path(__file__).with_name('buffer_sizing_card.py')
SHARED=ROOT/'src/serdes_flow/clock_profiles.py'
PREDICTOR=ROOT/'analog/tx/clock_distribution/theory/buffer_gain_plan.py'
PREDICTION=ROOT/'docs/data/tx_buffer_gain_plan.json'
PARENT=ROOT/'results/analog/tx/buffer_cascade_card/20261110T164906Z_4d3aeb7f'
DATA=ROOT/'docs/data/tx_buffer_cascade.json'
spec=importlib.util.spec_from_file_location('frozen_cascade',CASCADE)
cascade=importlib.util.module_from_spec(spec); spec.loader.exec_module(cascade)
old=cascade.old


def validate(profile):
    if not isinstance(profile,dict) or set(profile)!={'id','branches'} or not isinstance(profile['id'],str) or not re.fullmatch(r'[a-z0-9_]+',profile['id']): raise ValueError('invalid profile')
    branches=profile['branches']
    if not isinstance(branches,list) or len(branches)!=3: raise ValueError('three branches required')
    for branch in branches:
        if not isinstance(branch,dict) or set(branch)!={'label','stages'} or not isinstance(branch['label'],str) or not re.fullmatch(r'[a-z0-9_]+',branch['label']): raise ValueError('invalid branch')
        branch['stages']=normalize_extra(branch['stages'],5)
        if any(x[0]!=24 for x in branch['stages']): raise ValueError('WN must be 24')
    if len({b['label'] for b in branches})!=3 or branches[0]!={'label':'baseline','stages':normalize_extra(None,5)}: raise ValueError('baseline or labels invalid')
    return profile


def parent_check():
    spec=importlib.util.spec_from_file_location('frozen_sizing',GENERIC)
    generic=importlib.util.module_from_spec(spec); spec.loader.exec_module(generic)
    return generic.parent_check()


def check_decks(camp,profile):
    for tag in old.TAGS:
        text=(camp/'prepared'/f'{tag}.cir').read_text(); normalized=[]
        for i,b in enumerate(profile['branches'],1):
            match=re.search(rf'(?ms)^\.subckt local_chain_{i} .*?^\.ends local_chain_{i}$',text)
            if not match: raise ValueError('missing branch')
            chain=match.group()
            for n in range(5):
                lines=re.findall(rf'(?m)^Xe{n} .*$',chain)
                wn,wt,resistance=b['stages'][n]; expected=f'wn={wn} wt={wt} rload={resistance}'
                if len(lines)!=1 or not lines[0].endswith(expected): raise ValueError(f'wrong parameters branch {i} Xe{n}')
            if 'Xiso rp rn ip in vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400' not in chain or 'Xout e4p e4n cp cn vbias vdd vss serdes_cml_buffer wn=32 wt=16 rload=240' not in chain: raise ValueError('iso/out changed')
            normalized.append(re.sub(r'(?m)^(Xe[0-4] .*? wn=24) wt=\S+ rload=\S+$',r'\1 PARAMS',re.sub(r'local_chain_[123]','local_chain',chain)))
        if len(set(normalized))!=1: raise ValueError('branch topology changed')


def prepare(path):
    profile=validate(json.loads(path.read_text())); parent=parent_check()
    prediction=json.loads(PREDICTION.read_text())
    if prediction['generator_sha256']!=old.digest(PREDICTOR) or any(old.digest(ROOT/p)!=h for p,h in prediction['sources'].items()): raise ValueError('prediction source identity changed')
    camp=ROOT/'results/analog/tx/buffer_matrix_card'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False)
    for name in ('inputs','snap','prepared','runtime'): shutil.copytree(PARENT/name,camp/name)
    for tag in old.TAGS:
        deck=camp/'prepared'/f'{tag}.cir'; text=deck.read_text().replace(str(PARENT/'snap'/tag),str(camp/'snap'/tag))
        def alter(match):
            branch=profile['branches'][int(match.group(1))-1]; block=match.group()
            for n in range(5):
                wn,wt,resistance=branch['stages'][n]
                block,count=re.subn(rf'(?m)^(Xe{n} .*?) wn=\S+ wt=\S+ rload=\S+$',lambda m:f'{m.group(1)} wn={wn} wt={wt} rload={resistance}',block)
                if count!=1: raise ValueError('Xe instance missing')
            return block
        text,count=re.subn(r'(?ms)^\.subckt local_chain_([123]) .*?^\.ends local_chain_\1$',alter,text)
        if count!=3: raise ValueError('branches missing')
        deck.write_text(text)
    bc=json.loads((PARENT/'boundary_proposal.json').read_text())
    proposal=dict(bc,id=profile['id'],parent_id=bc['id'],parent_sha256=old.canonical(bc),
                  independent_mathematical_branches=[b['label'] for b in profile['branches']],
                  scope='ideal recorded PWL local loaded sizing; no upstream impedance or new real-bias validation')
    (camp/'boundary_proposal.json').write_text(json.dumps(proposal,indent=2)+'\n')
    for source,name in ((path,'profile.json'),(Path(__file__),'matrix_helper.py'),(CASCADE,'cascade_helper.py'),
                        (cascade.JOINT,'joint_helper.py'),(cascade.joint.HELPER,'local_helper.py'),(DATA,'parent_data.json'),(GENERIC,'sizing_helper.py'),
                        (SHARED,'clock_profiles.py'),(PREDICTOR,'gain_plan.py'),(PREDICTION,'gain_plan.json')):
        shutil.copyfile(source,camp/name)
    plan=json.loads((PARENT/'plan.json').read_text())
    plan['snapshots']={str(p.relative_to(camp)):old.digest(p) for p in camp.rglob('*') if p.is_file()}
    plan['status']='prepared_not_simulated'; (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    sizing={'parent':str(PARENT.relative_to(ROOT)),'parent_identity':parent,'plan_sha256':old.digest(camp/'plan.json'),
            'script_sha256':old.digest(Path(__file__)),'cascade_sha256':old.digest(CASCADE),
            'profile_sha256':old.digest(camp/'profile.json'),'shared_sha256':old.digest(SHARED),
            'predictor_sha256':old.digest(PREDICTOR),'prediction_sha256':old.digest(PREDICTION),'generic_sha256':old.digest(GENERIC),'ungraded':['physical resistance','power','noise','upstream impedance','new bias','full TX','I-17 closure']}
    (camp/'matrix_plan.json').write_text(json.dumps(sizing,indent=2)+'\n')
    check(camp); return camp


def check(camp,registered=False):
    plan=json.loads((camp/'matrix_plan.json').read_text())
    if plan['shared_sha256']!=old.digest(SHARED) or plan['generic_sha256']!=old.digest(GENERIC): raise ValueError('shared or generic helper changed')
    if plan['script_sha256']!=old.digest(Path(__file__)) or plan['cascade_sha256']!=old.digest(CASCADE) or plan['plan_sha256']!=old.digest(camp/'plan.json') or plan['profile_sha256']!=old.digest(camp/'profile.json') or plan['parent_identity']!=parent_check(): raise ValueError('sizing/parent identity changed')
    old.check(camp,registered=registered)
    profile=validate(json.loads((camp/'profile.json').read_text()))
    proposal=json.loads((camp/'boundary_proposal.json').read_text())
    if proposal['id']!=profile['id'] or proposal['independent_mathematical_branches']!=[b['label'] for b in profile['branches']] or old.canonical(boundary.get(proposal['parent_id']))!=proposal['parent_sha256']: raise ValueError('boundary identity changed')
    check_decks(camp,profile); return plan


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        archive=camp/'analysis'/(time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'_'+uuid.uuid4().hex[:8]); archive.mkdir(parents=True,exist_ok=False)
        report={'status':'failed','scope':'ideal recorded PWL; local extra5 sizing only','rows':[]}
        try:
            check(camp,registered=True)
            if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()): raise RuntimeError('campaign active')
            points=json.loads((PARENT/'boundary_proposal.json').read_text())['points']; profile=validate(json.loads((camp/'profile.json').read_text()))
            for tag in old.TAGS:
                raw=old.completed(camp,tag)
                if raw is None:
                    if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit before smoke')
                    deck=(camp/'prepared'/f'{tag}.cir').read_text(); smoke=deck.replace('tran .5p 6.500000000000e-09 .1n .5p','tran .5p 1.001n 0 .5p')
                    if smoke==deck: raise ValueError('smoke tran missing')
                    sd=spice.next_run_dir(camp,'smoke_'+tag); ex=spice.run(smoke,sd,timeout_s=180,meta={'condition':tag,'kind':'smoke'})
                    if not ex.ok or spice.case_output(camp,sd.name,tag+'.raw',1.001e-9) is None: raise RuntimeError(f'smoke failed: {sd}')
                    if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice limit before full')
                    run=spice.next_run_dir(camp,tag); ex=spice.run(deck,run,timeout_s=360,meta={'condition':tag,'kind':'full'})
                    if not ex.ok: raise RuntimeError(f'full failed: {run}')
                    raw=old.completed(camp,tag)
                    if raw is None: raise RuntimeError(f'incomplete output: {tag}')
                row={'condition':tag,'raw':str(raw.relative_to(ROOT)),'raw_sha256':old.digest(raw)}; report['rows'].append(row)
                measurement=cascade.measure(camp,tag,raw,points[tag])
                for branch,params in zip(measurement['branches'],profile['branches']):
                    branch['branch']=params['label']; branch['actual_parameters']=params
                row['result']=measurement
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
    p.add_argument('--profile',type=Path,default=DEFAULT); a=p.parse_args()
    if a.prepare: print(prepare(a.profile.resolve()))
    elif a.check: print(json.dumps(check(a.check.resolve()),indent=2))
    else: print(json.dumps(resume(a.resume.resolve()),indent=2,default=old.json_default,allow_nan=False))


if __name__=='__main__': main()
