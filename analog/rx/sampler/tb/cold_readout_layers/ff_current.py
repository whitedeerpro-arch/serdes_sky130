"""Prepare/check/resume FF cold W40 readout ordinary-OP diagnostic.

The historical FF deck timed out and used an older cell snapshot. This prepares
only the first, ordinary-OP stage with the separately frozen FS W40 cell closure.
Only --resume-op runs ngspice, one worker with a 600 s timeout. The subsequent
independent-Newton and transient stages require a separate same-FF seed and review.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import fcntl
import difflib
import numpy as np
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from serdes_flow import boundary, project, rcorner, spice, watch

ROOT = project.ROOT
SELF = Path(__file__).resolve()
FF = ROOT/'results/analog/rx/sampler/readout_deser/20261105T065521Z_ac_trim32_realbias_rhh'
FF_DECK = FF/'ff_v1950_t-40/tb.cir'
FF_STIM = FF/'ff_v1950_t-40/stimuli.inc'
FF_EX = FF/'ff_v1950_t-40/execution.json'
W40 = ROOT/'results/analog/rx/sampler/readout_deser/20261105T195801Z_ac_trim32_realbias_rhh'
W40_PLAN = ROOT/'results/analog/rx/sampler/cold_readout_full_sparse_op/20261109T133404.020641Z_42c4ada0/plan.json'
W40_SNAPSHOT = W40_PLAN.parent/'snap/cells'
OUT = ROOT/'results/analog/rx/sampler/cold_readout_ff_current'
BC = 'rx_c2_far_nominal@ctle_rc'
REGISTRY = ROOT/'config/boundary_conditions.json'
INC = re.compile(r'^\.include\s+"([^"]+)"', re.I | re.M)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare():
    original = FF_DECK.read_text()
    ex = json.loads(FF_EX.read_text())
    wp = json.loads(W40_PLAN.read_text())
    if ex['deck_sha256'] != sha(FF_DECK) or ex['inputs_sha256']['stimuli.inc'] != sha(FF_STIM):
        raise ValueError('FF deck or stimulus identity mismatch')
    if (ex['condition'],ex['bias'],ex['rpdk'],ex['code'],ex['cal_code']) != ('ff_v1950_t-40','real','hh',20,32):
        raise ValueError('unexpected FF execution boundary')
    for rel,h in wp['snapshots'].items():
        if sha(W40_PLAN.parent/rel) != h:
            raise ValueError(f'W40 frozen snapshot mismatch: {rel}')
    demux=W40_SNAPSHOT/'analog/rx/sampler/spice/rx_readout_demux2.spice'
    if not re.search(r'div_whold\s*=\s*40\b',demux.read_text()):
        raise ValueError('W40 not verified in frozen closure')
    for required in ('.lib "'+str(project.model_library())+'" ff_hh', '.temp -40', 'Vdd vdd 0 1.95',
                     'serdes_rx_half_rate_samples_ac_trim_rk rb=2k', 'serdes_rx_readout_deser16',
                     'Xbias_ref ', 'Xpi ', '.nodeset v(bias_vbg)=1.23'):
        if required not in original:
            raise ValueError(f'FF deck missing boundary: {required}')
    ctle = W40_SNAPSHOT/'analog/rx/ctle/spice/rx_ctle_rc.spice'
    signature = boundary.input_stage_signature(ctle.read_text(), 'serdes_rx_ctle_rc', ('inp','inn'))
    boundary.check_load(BC, signature)
    if signature['sha'] != '624029c653372f50' or ex['bc'] != BC:
        raise ValueError('registered C2 replay boundary or load mismatch')
    for family, expected in (('a', [0,0,1,0,0,0,0,0]), ('b', [0,0,0,1,0,0,0,0]), ('f', [1,1,1,1,0,0,0,0])):
        for index, bit in enumerate(expected):
            if f'V{family}{index} {family}{index} 0 {1.95 if bit else 0.0}' not in original:
                raise ValueError('PI20 code source mismatch')
    for lane in ('d0','d1','e0','e1'):
        for bit in range(6):
            if f'Vcal{lane}b{bit} {lane}b{bit} '+('vdd 0' if bit==5 else '0 0') not in original:
                raise ValueError('trim32 source mismatch')
    deser=W40_SNAPSHOT/'analog/rx/sampler/spice/rx_readout_deser16.spice'
    if not re.search(r'div_whold\s*=\s*40\b',deser.read_text()) or 'div_whold={div_whold}' not in deser.read_text():
        raise ValueError('deserializer W40 default/propagation mismatch')
    source_paths = re.findall(INC, original)
    relative = []
    for item in source_paths:
        if item == 'stimuli.inc':
            continue
        relative.append(Path(item).relative_to(FF/'pdk_resistors'))
    for rel in relative:
        if not (W40_SNAPSHOT/rel).is_file():
            raise ValueError(f'W40 closure missing: {rel}')
    target = OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid4().hex[:8])
    (target/'snap/cells').mkdir(parents=True)
    for rel in relative:
        dest=target/'snap/cells'/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(W40_SNAPSHOT/rel,dest)
    shutil.copyfile(FF_STIM,target/'snap/stimuli.inc')
    def replace(m):
        name=m.group(1)
        rel=Path('stimuli.inc') if name=='stimuli.inc' else Path('cells')/Path(name).relative_to(FF/'pdk_resistors')
        return f'.include "{target/"snap"/rel}"'
    body=INC.sub(replace,original.split('.control',1)[0])
    body=re.sub(r'^\.save .*\n','',body,flags=re.M|re.I)
    body=re.sub(r'(^\.options .*?)\s+klu\b',r'\1',body,flags=re.M|re.I)
    if re.search(r'^\s*\.ic\b|\buic\b',body,re.I|re.M) or body.lower().count('.nodeset ')!=1:
        raise ValueError('unexpected hard IC or nodeset count')
    control='''\n.save all
.control
set num_threads=1
set filetype=binary
echo STAGE_BEFORE_OP
op
echo STAGE_OP_RETURNED
write op.raw all
echo STAGE_RAW_WRITTEN
quit
.endc
.end
'''
    (target/'prepared').mkdir()
    deck=target/'prepared/ff_op.cir';deck.write_text(body+control)
    w40_comparison={}
    for rel in relative:
        old=W40_SNAPSHOT/rel;live=ROOT/rel
        if not live.exists(): raise ValueError(f'current source missing: {rel}')
        frozen=old.read_text(); current=live.read_text(); converted=rcorner._pdk_cell(current)
        diff=list(difflib.unified_diff(frozen.splitlines(),converted.splitlines(),fromfile='frozen',tofile='current_pdk',lineterm=''))
        w40_comparison[str(rel)]={'frozen_sha256':sha(old),'current_sha256':sha(live),
                                  'same_as_current':frozen==current,'same_after_pdk':frozen==converted,
                                  'pdk_mapped_diff':diff}
    if any(not v['same_after_pdk'] for v in w40_comparison.values()):
        raise ValueError('frozen DUT differs from PDK-mapped current source')
    # PDK R transformed cells differ from current source by construction; a hash
    # comparison alone cannot distinguish expected R mapping from DUT changes.
    pdk=project.model_library().parents[2]
    pdk_hashes={str(p):sha(p) for folder in ('libs.tech/ngspice','libs.ref/sky130_fd_pr/spice')
                for p in sorted((pdk/folder).rglob('*')) if p.is_file()}
    snapshots={str(p.relative_to(target)):sha(p) for d in ('snap','prepared') for p in (target/d).rglob('*') if p.is_file()}
    proposal={'id':'rx_ff_w40_c2_nominal_cold_diagnostic_v1','kind':'diagnostic_boundary_proposal',
              'condition':'FF 1.95 V -40 C hh, W40, PI20 trim32 rb2k, real bias, ideal 2 GHz phase anchors',
              'stimulus':'rx_c2_far_nominal@ctle_rc; same fixed nominal waveform as historical FS test; not FF-native link',
              'source_ff_deck':str(FF_DECK.relative_to(ROOT)),'source_ff_execution':str(FF_EX.relative_to(ROOT)),
              'source_ff_execution_timed_out':ex['timed_out'],'source_stimulus_sha256':sha(FF_STIM),
              'w40_source':str(W40_PLAN.relative_to(ROOT)), 'qualification':'same fixed C2 replay functional boundary; no native PLL/system qualification; ordinary OP alone is ungraded',
              'registered_replay_boundary':BC,'registered_load_signature':signature,
              'numerical_seed':'six original generic soft nodeset values only; no FS all-node seed; no IC/UIC',
              'next':'ordinary OP can be pseudo-transient; independent same-FF Newton with fallback disabled before any transient',
              'registered':False, 'not_a_new_registered_replay':True}
    (target/'boundary_proposal.json').write_text(json.dumps(proposal,indent=2)+'\n')
    plan={'scope':proposal['qualification'],'proposal_sha256':sha(target/'boundary_proposal.json'),
          'source_sha256':{str(p):sha(p) for p in (SELF,FF_DECK,FF_EX,FF_STIM,W40_PLAN,REGISTRY,Path(spice.__file__),Path(boundary.__file__),Path(rcorner.__file__),Path(watch.__file__),Path(project.__file__))},
          'pdk_sha256':pdk_hashes,'snapshots':snapshots,'w40_vs_current':w40_comparison,
          'runnable_stages':['ordinary OP'], 'prepared_stage':'ordinary OP only',
          'remaining':'independent same-FF Newton and subsequent transient require separately reviewed seed and stages'}
    (target/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    print(target.relative_to(ROOT))
    return target


def check(target):
    p=json.loads((target/'plan.json').read_text())
    for path,h in p['source_sha256'].items():
        if sha(path)!=h:raise ValueError(f'source changed: {path}')
    for path,h in p['pdk_sha256'].items():
        if sha(path)!=h:raise ValueError(f'PDK changed: {path}')
    for path,h in p['snapshots'].items():
        if sha(target/path)!=h:raise ValueError(f'snapshot changed: {path}')
    if sha(target/'boundary_proposal.json')!=p['proposal_sha256']:
        raise ValueError('proposal changed')
    print(json.dumps({'result':'verified','stage':p['prepared_stage'],'simulation_started':False,
                      'frozen_cell_mismatches_vs_current':sum(not x['same_as_current'] for x in p['w40_vs_current'].values()),
                      'frozen_cell_mismatches_after_pdk':sum(not x['same_after_pdk'] for x in p['w40_vs_current'].values()),
                      'missing':p['remaining']},indent=2))
    boundary.check_load(BC, json.loads((target/'boundary_proposal.json').read_text())['registered_load_signature'])
    return p


def assess(run, target):
    ex=json.loads((run/'execution.json').read_text())
    expected=sha(target/'prepared/ff_op.cir')
    if (ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or
        ex['deck_sha256']!=expected or sha(run/'tb.cir')!=expected or
        ex['pdk_installation_id']!=project.pdk_installation_id() or
        ex['ngspice']!=project.ngspice() or ex['model_library']!=str(project.model_library())):
        raise ValueError('execution identity or status mismatch')
    log=(run/'simulator.log').read_text(errors='replace')
    if not all(k in log for k in ('STAGE_BEFORE_OP','STAGE_OP_RETURNED','STAGE_RAW_WRITTEN')):
        raise ValueError('OP output markers missing')
    names,values=spice.read_raw(run/'op.raw')
    names=[x.lower() for x in names]
    required={'v(bias_vbg)','v(vgi_bias)','v(vbias)','v(vctle)','v(xro.ckq)','v(xro.xwc.j0)','i(vdd)'}
    if values.shape != (1,len(names)) or not np.isfinite(values).all() or not required.issubset(names):
        raise ValueError('all-node OP raw incomplete/nonfinite')
    return {'status':'observed','spec_status':'ungraded','dc_root_certified':False,
            'fallback':{'optran':bool(re.search(r'Transient op started',log,re.I)),
                        'dynamic_gmin':bool(re.search(r'Starting dynamic gmin',log,re.I)),
                        'true_gmin':bool(re.search(r'Starting true gmin',log,re.I)),
                        'source_stepping':bool(re.search(r'Starting source stepping',log,re.I))},
            'node_count':sum(x.startswith('v(') and x.endswith(')') for x in names),
            'vector_count':len(names),'raw_sha256':sha(run/'op.raw'),
            'execution_sha256':sha(run/'execution.json'),'log_sha256':sha(run/'simulator.log'),
            'run':str(run.relative_to(ROOT))}


def resume_op(target):
    with (target/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=check(target)
        runs=[target/'ff_op']+sorted(target.glob('ff_op.r[0-9]*'))
        for run in reversed(runs):
            try:
                result=assess(run,target);print(json.dumps(result,indent=2));return
            except (OSError,ValueError,KeyError,IndexError):
                pass
        active=watch.ngspice_cwds()
        if len(active)>=4 or any(x.is_relative_to(target) for x in active):
            raise RuntimeError('global ngspice quota or campaign already active')
        run=spice.next_run_dir(target,'ff_op')
        execution=spice.run((target/'prepared/ff_op.cir').read_text(),run,timeout_s=600,
                  meta={'bc':BC,'scope':plan['scope'],'solver':'ordinary SPARSE OP, one worker'})
        try:
            result=assess(run,target)
        except (OSError,ValueError,KeyError,IndexError) as exc:
            result=dict(status='incomplete_or_numerical_failure',spec_status='ungraded',dc_root_certified=False,
                        reason=str(exc),timed_out=execution.timed_out,run=str(run.relative_to(ROOT)),
                        execution_sha256=sha(run/'execution.json'),log_sha256=sha(run/'simulator.log'))
        dest=target/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        dest.mkdir(parents=True)
        (dest/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume-op',type=Path);args=ap.parse_args()
    if args.prepare: check(prepare())
    elif args.check: check(args.check.resolve())
    else: resume_op(args.resume_op.resolve())
