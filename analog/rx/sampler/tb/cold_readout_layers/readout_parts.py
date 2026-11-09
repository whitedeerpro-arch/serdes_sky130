"""Cold RX readout partial OP; only --resume invokes ngspice.

CMOS loads are removed in partial cases, changing the OP root; these are not
full-RX equivalents and all outcomes are ungraded.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid

import run as base
from serdes_flow import spice, watch

OLD = base.OUT/'20261109T083205.422134Z_5cb6b16b'
OUT = base.ROOT/'results/analog/rx/sampler/cold_readout_parts'
CELL = 'analog/rx/sampler/spice/rx_readout_deser16.spice'
LANES = {'xla0','xlae1','xlb0','xlbe1','xla1','xlae0','xlb1','xlbe0'}
MODES = ('front_only','front_wordclk')


def variant(text, mode):
    blocks = []
    for line in text.splitlines():
        if line.lstrip().startswith('+'):
            if not blocks: raise ValueError('orphan continuation')
            blocks[-1].append(line)
        else: blocks.append([line])
    inside = False
    kept, removed = [], []
    for block in blocks:
        line = block[0].strip()
        if line.lower().startswith('.subckt serdes_rx_readout_deser16 '): inside = True
        name = line.split()[0].lower() if line else ''
        if inside and (name in LANES or (mode == 'front_only' and name == 'xwc')):
            removed.append('\n'.join(block))
        else: kept.extend(block)
        if inside and line.lower() == '.ends serdes_rx_readout_deser16': inside = False
    expected = LANES | ({'xwc'} if mode == 'front_only' else set())
    if {x.split()[0].lower() for x in removed} != expected: raise ValueError('unexpected cell structure')
    xf = [b for b in blocks if b[0].strip().lower().startswith('xf ')]
    if len(xf) != 1 or '\n'.join(xf[0]) not in '\n'.join(kept): raise ValueError('Xf changed')
    return '\n'.join(kept)+'\n', removed


def deck_for(folder, mode, oldplan):
    includes = {src: str(Path('snap/cells')/Path(src).relative_to(base.SOURCE/'pdk_resistors')) for src in oldplan['includes']}
    cell = next(src for src in includes if src.endswith('/'+CELL))
    includes[cell] = f'variants/{mode}.spice'
    deck, _, _ = base.make_deck(folder, base.ORIGINAL.read_text(), 3, 'sparse', includes)
    deck = deck.split('.control',1)[0]
    lines, removed_caps = [], []
    for line in deck.splitlines():
        name = line.split()[0].lower() if line.split() else ''
        if re.fullmatch(r'c(?:a|b|ae|be)[01]_[0-3]', name) or (mode == 'front_only' and name == 'cw'):
            removed_caps.append(line)
        else:
            lines.append(line)
    expected = {f'c{lane}_{i}' for lane in ('a0','b0','ae1','be1','a1','b1','ae0','be0') for i in range(4)}
    if mode == 'front_only': expected.add('cw')
    if {line.split()[0].lower() for line in removed_caps} != expected: raise ValueError('unexpected output capacitors')
    deck = '\n'.join(lines)+'\n'
    nodes = ['bias_vbg','vgi_bias','vbias','vctle','rkp','rkn','xro.ckq','xro.ckqb']
    if mode == 'front_wordclk': nodes += ['xro.xwc.j0','xro.xwc.j1','w']
    vectors = {f'v{i}':f'v({node})' for i,node in enumerate(nodes)}
    vectors.update(base.CURRENTS)
    control = ['.control','set num_threads=1','set wr_vecnames','set wr_singlescale','op']
    control += [f'let {name}={expr}' for name,expr in vectors.items()]
    control += ['wrdata op.tsv '+' '.join(vectors),'quit','.endc','.end']
    return deck+'\n'.join(control)+'\n', nodes, removed_caps


def prepare():
    oldplan = base.verify(OLD)
    archive = OLD/'execution/run.py'
    if base.sha(archive) != oldplan['source_sha256'][str(Path(base.__file__).resolve())]: raise ValueError('runner archive mismatch')
    folder = OUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(OLD/'snap',folder/'snap')
    original = (folder/'snap/cells'/CELL).read_text()
    cases = []
    for mode in MODES:
        cell, removed = variant(original,mode)
        p = folder/'variants'/f'{mode}.spice'; p.parent.mkdir(exist_ok=True); p.write_text(cell)
        deck,nodes,removed_caps = deck_for(folder,mode,oldplan)
        p = folder/'prepared'/f'{mode}.cir'; p.parent.mkdir(exist_ok=True); p.write_text(deck)
        cases.append(dict(name=mode,deck=str(p.relative_to(folder)),variant=f'variants/{mode}.spice',nodes=nodes,
                          removed_instances=removed,removed_output_caps=removed_caps,
                          original_load='Xf + Xwc + 8 CMOS lanes + 32 x 2 fF word outputs + 20 fF word clock',
                          new_load=('Xf only; no lane or word-clock output capacitors' if mode == 'front_only' else
                                    'Xf + Xwc + 20 fF word-clock output; no lanes or lane output capacitors'),
                          load_signature=hashlib.sha256((cell+'\n'+deck).encode()).hexdigest()))
    files = {str(p.relative_to(folder)):base.sha(p) for d in ('snap','variants','prepared') for p in (folder/d).rglob('*') if p.is_file()}
    full = OLD/'readout_sparse'
    plan = dict(scope='FS 1.65 V -40 C hh SPARSE OP; partial CMOS load changes OP root; not full-equivalent; observed/ungraded',
                old_campaign=str(OLD),old_plan_sha256=base.sha(OLD/'plan.json'),old_runner_sha256=base.sha(archive),
                this_runner_sha256=base.sha(__file__),boundary_id=base.BC,
                hint='original six-node nodeset only; no new nodeset, .ic or uic',
                kick='original Ikick xro.xf.dqp to xro.xf.dqn: 1 uA at t=0',
                full_reference={'run':str(full),'execution_sha256':base.sha(full/'execution.json'),
                                'log_sha256':base.sha(full/'simulator.log'),'status':'120 s timeout; no OP table'},
                invalid_fixture='prior cold_readout_parts/20261109T083933.889249Z_dd8e579f: partial cases retained capacitors on disconnected lane outputs; front_only also retained Cw; singular-matrix fixture invalid, not design failure',
                snapshots=files,cases=cases)
    (folder/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return folder


def verify(folder):
    plan = json.loads((folder/'plan.json').read_text()); oldplan = base.verify(OLD)
    if base.sha(OLD/'plan.json') != plan['old_plan_sha256'] or base.sha(OLD/'execution/run.py') != plan['old_runner_sha256'] or base.sha(__file__) != plan['this_runner_sha256']: raise ValueError('source identity changed')
    for path,digest in plan['snapshots'].items():
        if base.sha(folder/path) != digest: raise ValueError(f'snapshot changed: {path}')
    for key,filename in [('execution','execution.json'),('log','simulator.log')]:
        if base.sha(OLD/'readout_sparse'/filename) != plan['full_reference'][key+'_sha256']: raise ValueError('full reference changed')
    for case in plan['cases']:
        cell,removed = variant((folder/'snap/cells'/CELL).read_text(),case['name'])
        deck,nodes,caps = deck_for(folder,case['name'],oldplan)
        if cell != (folder/case['variant']).read_text() or deck != (folder/case['deck']).read_text() or removed != case['removed_instances'] or nodes != case['nodes'] or caps != case['removed_output_caps']: raise ValueError('case changed')
    return plan


def resume(folder):
    with (folder/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan = verify(folder)
        if any(p == folder or p.is_relative_to(folder) for p in watch.ngspice_cwds()): raise ValueError('campaign active')
        rows = []
        for case in plan['cases']:
            name = case['name']; complete = None
            for run in reversed([folder/name]+sorted(folder.glob(name+'.r*'))):
                try:
                    ex = json.loads((run/'execution.json').read_text())
                    if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or base.sha(run/'tb.cir') != base.sha(folder/case['deck']): continue
                    complete = (run,base.read_op(run/'op.tsv',case['nodes'])); break
                except (OSError,ValueError,KeyError): pass
            if complete is None:
                if len(watch.ngspice_cwds()) >= 4: raise RuntimeError('global ngspice quota')
                run = spice.next_run_dir(folder,name)
                ex = spice.run((folder/case['deck']).read_text(),run,timeout_s=120,meta={'case':name,'bc':base.BC,'solver':'sparse'})
                try:
                    if ex.ok: complete = (run,base.read_op(run/'op.tsv',case['nodes']))
                except (OSError,ValueError): pass
            row = dict(case=name,status='missing_or_numerical_failure',spec_status='ungraded')
            if complete:
                run,values = complete
                row.update(status='observed',values=values,run=str(run.relative_to(base.ROOT)),execution_sha256=base.sha(run/'execution.json'),op_sha256=base.sha(run/'op.tsv'))
            rows.append(row)
        dest = folder/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ'); dest.mkdir(parents=True,exist_ok=False)
        (dest/'summary.json').write_text(json.dumps(dict(scope=plan['scope'],rows=rows),indent=2,allow_nan=False)+'\n')
        print(dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__); g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true'); g.add_argument('--check',type=Path); g.add_argument('--resume',type=Path)
    a = ap.parse_args()
    if a.prepare: print(prepare())
    elif a.check: verify(a.check.resolve()); print('checkpoint valid; no ngspice')
    else: resume(a.resume.resolve())


if __name__ == '__main__': main()
