"""Full FS RX 1 ns diagnostic with same-deck logged transient-OP soft hints.

--prepare/--check are read-only with respect to simulations. --resume requires
the exact numerical-initial-guess BC proposal to be registered first. Hints are
not hard initial conditions and do not demonstrate startup or logical function.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import uuid

import run as base
import full_short as short
from serdes_flow import boundary, spice, watch

OUT=base.ROOT/'results/analog/rx/sampler/cold_readout_full_seeded'
LOG=base.ORIGINAL.parent/'simulator.log'
BC='rx_fs_w40_full_transient_op_xro_seed_v1'


def hints():
    lines=LOG.read_text(errors='strict').splitlines()
    markers=[i for i,s in enumerate(lines) if s.strip()=='Initial Transient Solution']
    if len(markers)!=1 or 'Transient op finished successfully' not in '\n'.join(lines[max(0,markers[0]-5):markers[0]]): raise ValueError('initial solution marker missing or ambiguous')
    start=markers[0]+1
    finish=next((i for i in range(start,len(lines)) if '#branch' in lines[i]),None)
    if finish is None: raise ValueError('solution table lacks branch boundary')
    found=[]; names=set()
    for i in range(start,finish):
        parts=lines[i].split()
        if len(parts)!=2 or not parts[0].lower().startswith('xro.'): continue
        name,value=parts
        if not re.fullmatch(r'xro(?:\.[a-z0-9_]+)+',name,re.I): raise ValueError(f'unsafe node {name}')
        try: number=float(value)
        except ValueError: continue
        if not math.isfinite(number): continue
        if name.lower() in names: raise ValueError('duplicate node')
        names.add(name.lower()); found.append(dict(node=name.lower(),value=value,line=i+1))
    if not found or not {'xro.ckq','xro.ckqb','xro.xwc.j0','xro.xwc.j1'}.issubset(names): raise ValueError('incomplete readout table')
    return found


def proposal(entries,oldplan):
    encoded=json.dumps(entries,sort_keys=True,separators=(',',':')).encode()
    return dict(id=BC,kind='numerical_initial_guess',description='Soft nodeset hints from the same FS full W40 deck transient-OP initial solution; not DC qualification or power-up evidence.',
                upstream=dict(module='rx sampler readout',deck=str(base.ORIGINAL.relative_to(base.ROOT)),deck_sha256=base.sha(base.ORIGINAL),
                              execution=str(base.EXECUTION.relative_to(base.ROOT)),execution_sha256=base.sha(base.EXECUTION),
                              log=str(LOG.relative_to(base.ROOT)),log_sha256=base.sha(LOG),
                              frozen_cell_manifest_sha256=hashlib.sha256(json.dumps(oldplan['snapshots'],sort_keys=True).encode()).hexdigest(),
                              limitation='source execution records deck/stimulus hashes and PDK identity, but no per-cell execution-time hashes; frozen historical cell paths are verified against the prepared source snapshot'),
                nodes=entries,load=None,points={'fs_v1650_t-40':dict(condition='FS_hh 1.65 V -40 C PI20 trim32 rb2k W40',count=len(entries),content_sha256=hashlib.sha256(encoded).hexdigest())},
                processing='finite xro.* voltage lines in original Initial Transient Solution, excluding branch currents; decimal text copied verbatim into soft .nodeset only',
                validation=dict(state='ungraded',limitation='transient-OP solution is not full DC proof, functional proof, nor physical power-up'),
                valid_while=['same source log/deck, frozen cell snapshot and PDK identity','same t=0 controls and load','no hard .ic/uic'])


def make_deck(folder,oldplan,entries):
    deck=short.deck_for(folder,oldplan)
    marker='.control\n'
    hint='* additional soft numerical guesses from recorded same-deck transient OP\n'+''.join(f'.nodeset v({x["node"]})={x["value"]}\n' for x in entries)
    if deck.count(marker)!=1: raise ValueError('control marker ambiguity')
    return deck.replace(marker,hint+marker,1)


def prepare():
    oldplan=base.verify(short.OLD)
    original_ex=json.loads(base.EXECUTION.read_text())
    if original_ex['deck_sha256']!=base.sha(base.ORIGINAL) or original_ex['inputs_sha256']['stimuli.inc']!=base.sha(base.STIMULUS) or original_ex['pdk_installation_id']!=base.project.pdk_installation_id(): raise ValueError('source deck, stimulus, or PDK mismatch')
    # Names come from the actual flattened xro nodes printed by the exact source deck;
    # paths of every include and every copied historical cell are checked by base.verify.
    entries=hints(); bc=proposal(entries,oldplan)
    folder=OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]); folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(short.OLD/'snap',folder/'snap')
    (folder/'prepared').mkdir(); (folder/'prepared/full_seeded.cir').write_text(make_deck(folder,oldplan,entries))
    (folder/'seed_boundary_proposal.json').write_text(json.dumps(bc,indent=2)+'\n')
    snapshots={str(p.relative_to(folder)):base.sha(p) for d in ('snap','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    plan=dict(scope='same full FS W40 KLU 1 ns transient with soft logged xro hints; observed/ungraded only',
              source_plan_sha256=base.sha(short.OLD/'plan.json'),source_runner_sha256=base.sha(base.__file__),
              short_runner_sha256=base.sha(short.__file__),this_runner_sha256=base.sha(__file__),
              seed_bc=BC,proposal_sha256=base.sha(folder/'seed_boundary_proposal.json'),
              source_log_sha256=base.sha(LOG),hint_count=len(entries),snapshots=snapshots,
              source_node_validation='xro voltage names were emitted by the exact source full deck initial transient solution; source execution deck/stimulus hashes and historical include snapshot verified. No independent execution-time per-cell hashes were recorded.',
              warning='Transient-OP values are rounded log output and initial solver guesses only; no DC, startup or Q logic pass asserted.')
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n'); return folder


def verify(folder,registered=False):
    plan=json.loads((folder/'plan.json').read_text()); oldplan=base.verify(short.OLD)
    if base.sha(short.OLD/'plan.json')!=plan['source_plan_sha256'] or base.sha(base.__file__)!=plan['source_runner_sha256'] or base.sha(short.__file__)!=plan['short_runner_sha256'] or base.sha(__file__)!=plan['this_runner_sha256'] or base.sha(LOG)!=plan['source_log_sha256']: raise ValueError('source identity changed')
    for p,digest in plan['snapshots'].items():
        if base.sha(folder/p)!=digest: raise ValueError(f'snapshot changed: {p}')
    bc=json.loads((folder/'seed_boundary_proposal.json').read_text()); entries=hints()
    if base.sha(folder/'seed_boundary_proposal.json')!=plan['proposal_sha256'] or bc!=proposal(entries,oldplan) or len(entries)!=plan['hint_count']: raise ValueError('hint identity changed')
    deck=make_deck(folder,oldplan,entries)
    if deck!=(folder/'prepared/full_seeded.cir').read_text() or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M): raise ValueError('deck changed or hard initial condition')
    if registered and boundary.get(BC)!=bc: raise ValueError('registered BC differs')
    return plan


def resume(folder):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB); plan=verify(folder,registered=True)
        if any(p==folder or p.is_relative_to(folder) for p in watch.ngspice_cwds()): raise ValueError('campaign active')
        complete=None
        for run in reversed([folder/'full_seeded']+sorted(folder.glob('full_seeded.r*'))):
            try:
                ex=json.loads((run/'execution.json').read_text()); details=short.assess(run)
                if ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and base.sha(run/'tb.cir')==base.sha(folder/'prepared/full_seeded.cir') and details['tran_returned'] and details['raw_written'] and details['raw_complete']:
                    complete=(run,details); break
            except (OSError,ValueError,KeyError): pass
        if complete is None:
            if len(watch.ngspice_cwds())>=4: raise RuntimeError('global ngspice quota')
            run=spice.next_run_dir(folder,'full_seeded')
            ex=spice.run((folder/'prepared/full_seeded.cir').read_text(),run,timeout_s=600,meta={'bc':base.BC,'seed_bc':BC,'solver':'klu','scope':plan['scope']})
            details=short.assess(run)
            if ex.ok and details['tran_returned'] and details['raw_written'] and details['raw_complete']: complete=(run,details)
        row=dict(status='observed' if complete else 'incomplete_or_numerical_failure',spec_status='ungraded',run=str(run.relative_to(base.ROOT)),stages=details,execution_sha256=base.sha(run/'execution.json'))
        if (run/'short.raw').exists(): row['raw_sha256']=base.sha(run/'short.raw')
        dest=folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],result=row),indent=2,allow_nan=False)+'\n'); print(dest)


def main():
    ap=argparse.ArgumentParser(description=__doc__); g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path)
    a=ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; BC proposal not registered; no ngspice')
    else: resume(a.resume.resolve())


if __name__=='__main__': main()
