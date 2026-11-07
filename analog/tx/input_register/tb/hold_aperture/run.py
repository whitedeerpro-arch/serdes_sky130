"""Recorded full-bank clock pair -> loaded B-latch aperture characterization.

First --register the fixed source boundary. Run --baseline-only --run-only
ff_v1950_t-40, then --resume CAMPAIGN to fill the planned six-condition map.
Only data arrival is translated; clocks, partner data and select remain fixed.
No full-bank mismatch/noise or 45-PVT qualification is implied by a local map.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np

from serdes_flow import bias, boundary, clock, project, rcorner, spice
from serdes_flow.corners import Condition, STRESS, boundary_first
from serdes_flow.waves import simplify_pwl

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
SOURCE = ROOT / 'results/analog/tx/staggered_ingress/20261106T202607Z'
CELL = ROOT / 'analog/tx/input_register/spice/launch_hold_slice.spice'
BC = 'tx_staggered_b_launch_cut_v3'
PWL_TOL_V = 10e-6
INPUTS = ('data', 'partner', 'clk', 'clk_b', 'sp', 'sn')
PREHISTORY = 4e-9
STOP = PREHISTORY+1.9e-9
OFFSETS_PS = (-100, -50, -25, 0, 10, 20, 30, 40, 60, 80, 120, 160, 200)
VECTORS = 'v(data) v(partner) v(clk) v(clk_b) v(sp) v(sn) v(q) v(cp) v(cn) v(zp) v(zn) v(vdd)'
PHYSICAL = (
    'analog/tx/input_register/spice/word_capture16_staggered.spice',
    'analog/common/devices/spice/sky130_primitives.spice',
    'analog/common/devices/spice/cmos_logic.spice',
    'analog/common/cmos_to_cml/spice/cmos_to_cml_data.spice',
    'analog/common/cml_mux/spice/cml_lowov_cells.spice',
)


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def source_signature(deck, lane, dut_snapshot):
    """Verify the cut's direct gate stages against the saved upstream wiring."""
    words = [next(l for l in dut_snapshot.splitlines() if l.startswith(f'Xl{lane} '))]
    words += [next(l for l in deck.splitlines() if l.startswith(f'Xc{i} ')) for i in (lane, lane-8)]
    words += [next(l for l in deck.splitlines() if l.startswith(f'Xm{lane-8} '))]
    aliases = {f'h{lane}': 'data', f'q{lane-8}': 'partner'}
    body = '\n'.join(' '.join(aliases.get(t, t) for t in l.split()) for l in words)
    return boundary.input_stage_signature('.subckt cut ' + ' '.join(INPUTS) + '\n' + body + '\n.ends', 'cut', INPUTS)


def register():
    plan_path, summary_path = SOURCE/'plan.json', SOURCE/'summary.json'
    plan, summary = json.loads(plan_path.read_text()), json.loads(summary_path.read_text())
    if len(summary['rows']) != 6 or set(r['condition'] for r in summary['rows']) != set(plan['conditions']):
        raise ValueError('source condition identity differs')
    for p in PHYSICAL:
        if sha(ROOT/p) != plan['sources'][p] or sha(SOURCE/'execution'/p) != plan['sources'][p]:
            raise ValueError(f'physical source changed: {p}')
    load = boundary.input_stage_signature(CELL, 'serdes_tx_launch_hold_slice', INPUTS)
    points = {}
    for r in summary['rows']:
        if r['status'] != 'measured' or not r['metrics']['functional']:
            raise ValueError('all six source cases must be complete and functional')
        path = ROOT/r['waveform']
        w = spice.Waves(path)
        if w.t[-1] < plan['stop_s']*(1-1e-7):
            raise ValueError('source truncated')
        ex = json.loads((path.parent/'execution.json').read_text())
        if ex['pdk_installation_id'] != project.pdk_installation_id():
            raise ValueError('PDK changed')
        deck_path = path.parent/'tb.cir'
        if sha(deck_path) != ex['deck_sha256']:
            raise ValueError('source deck changed')
        events = {}
        for name, polarity in (('fall', -1), ('rise', 1)):
            choices = [a for a in r['metrics']['b_close_data_separation']
                       if (1 if (plan['words'][a['word']+1] >> a['lane']) & 1 else -1) == polarity]
            chosen = min(choices, key=lambda a: a['separation_ps'])
            k, lane = chosen['word'], chosen['lane']
            source_load = source_signature(deck_path.read_text(), lane, (SOURCE/'execution'/PHYSICAL[0]).read_text())
            if source_load != load:
                raise ValueError(f'recording/consumer load mismatch: {source_load} != {load}')
            edge = r['metrics']['words'][k]['lanes'][lane]['selected_from_s']
            events[name] = dict(word=k, lane=lane, polarity=polarity, select_edge_s=edge,
                                origin_s=edge-PREHISTORY, close_s=chosen['b_clock_close_s']-(edge-PREHISTORY),
                                original_data_s=chosen['next_data_arrival_s']-(edge-PREHISTORY),
                                original_separation_ps=chosen['separation_ps'])
        points[r['condition']] = boundary.run_record(path.parent, condition=r['condition'],
            raw=str(path.relative_to(ROOT)), raw_sha256=sha(path), events=events,
            pdk_installation_id=ex['pdk_installation_id'])
    entry = dict(id=BC, kind='loaded_internal_port_voltage_replay',
        description='Cut one B latch/converter/MUX branch from the recorded 16-bit bank; select minimum observed data-close separation of each data direction per PVT.',
        upstream=dict(module='tx.capture', revision='staggered_candidate_20261107', campaign=str(SOURCE.relative_to(ROOT)),
                      plan_sha256=sha(plan_path), physical_sources={p: plan['sources'][p] for p in PHYSICAL}),
        nodes=dict(clk='clk', clk_b='xcap.clk_b', data='xcap.h<lane>', partner='q<lane-8>', select=['sp','sn']),
        load=load, consumer_sha256=sha(CELL), points=points,
        processing='Cut one full word (4ns) before to 1.9ns after CML B select; starts with B transparent, then replay one real word of history. Interpolate endpoints and simplify PWL with 10uV bounded error. Baseline unshifted; sweep translates the recorded data trace only. Compare outputs only from 100ps before the target B select. No time scaling or polarity fitting.',
        pwl_tolerance_v=PWL_TOL_V,
        validation=dict(state='pending_baseline_comparison', waveform_error_gate_v=.005),
        proxy_loads=dict(q_wire_f=2e-15, partner_wire_f=2e-15, mux_output_per_leg_f=5e-15),
        valid_while=['same transistor cells and load stages, dimensions, PDK installation and R tt',
                     'source driver impedance and perturbed Miller feedback are omitted by voltage replay',
                     'baseline must match full-bank q/CML/MUX waveforms within 5mV before using shifted cases',
                     'two recorded event shapes per condition, not all patterns, noise, mismatch, startup or 45PVT'])
    old = boundary.registry().get(BC)
    if old is not None:
        if old != entry:
            raise ValueError('registered boundary differs; choose a new BC identity')
    else:
        boundary.register(entry)
    return entry


def event_waves(entry, cond, event):
    p = entry['points'][cond.tag]
    raw = ROOT/p['raw']
    if sha(raw) != p['raw_sha256'] or sha(ROOT/p['run']/'tb.cir') != p['deck_sha256']:
        raise ValueError('recording identity changed')
    w = spice.Waves(raw)
    e = p['events'][event]
    origin, lane = e['origin_s'], e['lane']
    if w.t[0] > origin or w.t[-1] < origin+STOP:
        raise ValueError('source misses cut window')
    t = np.r_[0., w.t[(w.t > origin) & (w.t < origin+STOP)]-origin, STOP]
    mapping = dict(clk='clk', clkb='xcap.clk_b', data=f'xcap.h{lane}', partner=f'q{lane-8}', sp='sp', sn='sn')
    signals = {k: np.interp(t+origin, w.t, w[v]) for k,v in mapping.items()}
    ref = {k: np.interp(t+origin, w.t, w[v]) for k,v in
           dict(q=f'q{lane}', cp=f'c{lane}p', cn=f'c{lane}n', zp=f'z{lane-8}p', zn=f'z{lane-8}n').items()}
    return t, signals, ref


def pwl(t, y, shift=0.):
    moved = t+shift
    ti = np.r_[0., moved[(moved > 0) & (moved < STOP)], STOP]
    yi = np.interp(ti-shift, t, y)
    return simplify_pwl(ti,yi,PWL_TOL_V)


def alter_pwl(name, t, y, shift=0.):
    ti,yi=pwl(t,y,shift)
    values=np.column_stack((ti,yi)).ravel()
    if len(values)<=360:
        return [f'alter @V{name}[pwl] = [ '+' '.join(f'{v:.12e}' for v in values)+' ]']
    # ngspice alter has a finite token limit. A vector expression avoids it.
    return [f'let replay_pwl=vector({len(values)})']+[f'let replay_pwl[{i}]={v:.12e}' for i,v in enumerate(values)]+[f'alter @V{name}[pwl] = replay_pwl','unlet replay_pwl']


def specs(conds, offsets=OFFSETS_PS, events=('fall','rise')):
    return [dict(condition=c.tag, event=e, offset_ps=d, name=c.tag+'_'+e+'_'+('baseline' if d is None else f'd{d:+d}ps'))
            for c in conds for e in events for d in (None,)+tuple(offsets)]


def deck(cases, entry, snap, smoke=False):
    c0 = Condition.parse(cases[0]['condition'])
    blocks = []
    previous = None
    for case in cases:
        c = Condition.parse(case['condition'])
        t, signals, _ = event_waves(entry, c, case['event'])
        if previous != (c.tag, case['event']):
            for name in ('clk', 'clkb', 'partner', 'sp', 'sn'):
                blocks += alter_pwl(name,t,signals[name])
            previous = (c.tag, case['event'])
        ev = entry['points'][c.tag]['events'][case['event']]
        shift = 0 if case['offset_ps'] is None else ev['close_s']+case['offset_ps']*1e-12-ev['original_data_s']
        blocks += alter_pwl('data',t,signals['data'],shift)
        blocks += [f'option temp={c.temp}', f'alter Vdd dc={c.supply}']
        # A recorded PWL knot can fall a floating-point epsilon from exactly
        # 1ns. End just beyond it, so the smoke stop does not force an
        # unresolvable sub-attosecond step between that knot and tstop.
        tran = 'tran .5p 1.001n 0 .5p' if smoke else spice.skip_output_before(f'tran .5p {STOP:.12e} 0 .5p', '.1n')
        blocks += [tran, 'write '+('smoke' if smoke else case['name'])+'.raw '+VECTORS, 'destroy all']
    txt = spice.render(HERE/'tb_hold_ngspice.cir.in', **spice.corner_values(c0), CASES='\n'.join(blocks), VECTORS=VECTORS)
    return bias.section(rcorner.to_pdk(bias.real(txt), snap), c0.process, 'tt')


def measure(path, case, entry):
    w = spice.Waves(path)
    if w.t[-1] < STOP*(1-1e-7):
        raise ValueError('incomplete transient')
    c = Condition.parse(case['condition']);e = entry['points'][c.tag]['events'][case['event']]
    vdd = c.supply;polarity=e['polarity'];oldsign=-polarity
    t,signals,ref=event_waves(entry,c,case['event'])
    shift=0 if case['offset_ps'] is None else e['close_s']+case['offset_ps']*1e-12-e['original_data_s']
    errors={name:float(np.max(np.abs(w['clk_b' if name=='clkb' else name]-np.interp(w.t-(shift if name=='data' else 0),t,y)))) for name,y in signals.items()}
    if max(errors.values())>200e-6:
        raise ValueError(f'input replay mismatch: {errors}')
    closes = clock.edges(w.t,w['clk_b']-vdd/2,-1,PREHISTORY,STOP)
    data = clock.edges(w.t,w['data']-vdd/2,polarity,PREHISTORY-.3e-9,STOP)
    if len(closes)!=1 or len(data)!=1:
        raise ValueError('need unique close and data edges')
    keep=(w.t>=closes[0]-.1e-9)&(w.t<=STOP-.05e-9)
    qm=float(np.min((w['q'][keep]-vdd/2)*oldsign));cm=float(np.min((w['cp'][keep]-w['cn'][keep])*oldsign))
    end=float((np.interp(STOP-.1e-9,w.t,w['q'])-vdd/2)*oldsign)
    initial=float((np.interp(PREHISTORY-.1e-9,w.t,w['q'])-vdd/2)*oldsign)
    result=dict(actual_separation_ps=float((data[0]-closes[0])*1e12),q_old_signed_min_v=qm,cml_old_signed_min_v=cm,
                old_retained=initial>.3*vdd and qm>.3*vdd and cm>0,
                final_state='old' if end>.3*vdd else 'new' if end<-.3*vdd else 'intermediate',input_replay_max_error_v=errors)
    if case['offset_ps'] is None:
        valid=w.t>=PREHISTORY-.1e-9
        err={name:float(np.max(np.abs(w[name][valid]-np.interp(w.t[valid],t,y)))) for name,y in ref.items()}
        result.update(baseline_max_error_v=err,baseline_matches=max(err.values())<=.005)
    return result


def summarize(camp, cases, entry):
    rows=[]
    for case in cases:
        row=dict(case,status='missing')
        c=Condition.parse(case['condition'])
        path=spice.case_output(camp,c.process,case['name']+'.raw',STOP)
        if path:
            try: row.update(status='measured',waveform=str(path.relative_to(ROOT)),metrics=measure(path,case,entry))
            except (ValueError,KeyError) as error: row.update(status='analysis_error',error=str(error))
        rows.append(row)
    result=dict(boundary_id=BC,scope='Local loaded B latch, recorded clock pair and partner/select; shifted prescribed data source; two event shapes/condition. No mismatch/noise or full-bank/45PVT acceptance.',rows=rows)
    tmp=camp/'summary.json.tmp';tmp.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');tmp.replace(camp/'summary.json')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--register',action='store_true');p.add_argument('--resume',type=Path)
    p.add_argument('--run-only');p.add_argument('--baseline-only',action='store_true')
    p.add_argument('--conditions',help='planned subset of registered conditions')
    p.add_argument('--events',choices=('fall','rise','both'))
    p.add_argument('--offsets-ps',help='comma-separated signed integer offsets; use = before negative values')
    p.add_argument('--workers',type=int,choices=(1,2),default=2)
    a=p.parse_args()
    if a.register:
        print(register()['id']);return
    entry=boundary.get(BC)
    boundary.check_load(BC,boundary.input_stage_signature(CELL,'serdes_tx_launch_hold_slice',INPUTS))
    if sha(CELL)!=entry['consumer_sha256']:
        raise ValueError('consumer changed')
    for rel,digest in entry['upstream']['physical_sources'].items():
        if sha(ROOT/rel)!=digest:raise ValueError('physical cell changed')
    if any(v['pdk_installation_id']!=project.pdk_installation_id() for v in entry['points'].values()):
        raise ValueError('PDK changed')
    old_plan=json.loads((a.resume/'plan.json').read_text()) if a.resume and (a.resume/'plan.json').exists() else None
    old_exp=old_plan.get('experiment',{}) if old_plan else {}
    tags=a.conditions.split(',') if a.conditions else old_exp.get('conditions',[c.tag for c in boundary_first(STRESS)])
    if len(tags)!=len(set(tags)) or set(tags)-set(entry['points']):raise ValueError('invalid planned condition subset')
    conds=boundary_first([Condition.parse(t) for t in tags])
    events=('fall','rise') if a.events=='both' else (a.events,) if a.events else tuple(old_exp.get('events',('fall','rise')))
    offsets=tuple(int(x) for x in a.offsets_ps.split(',')) if a.offsets_ps else tuple(old_exp.get('offsets_ps',OFFSETS_PS))
    if not offsets or len(offsets)!=len(set(offsets)) or max(map(abs,offsets))>1000:raise ValueError('unique offsets within +/-1000ps required')
    cases=specs(conds,offsets,events)
    sources=[Path(__file__),HERE/'tb_hold_ngspice.cir.in',CELL]+[ROOT/x for x in set(PHYSICAL+bias.BIAS_INC)]
    sources += [ROOT/'analog/common/devices/spice/cmos_dff.spice']
    sources += [ROOT/'src/serdes_flow'/x for x in ('spice.py','clock.py','waves.py','bias.py','rcorner.py','boundary.py','project.py','corners.py')]
    sources += [ROOT/'config'/x for x in ('pdk.toml','tools.toml')]
    identity={str(x.relative_to(ROOT)):sha(x) for x in sources}
    plan=dict(sources=identity,boundary_sha256=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest(),cases=cases,stop_s=STOP,
              experiment=dict(conditions=[c.tag for c in conds],events=list(events),offsets_ps=list(offsets)))
    camp=a.resume.resolve() if a.resume else ROOT/'results/analog/tx/hold_aperture'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    camp.mkdir(parents=True,exist_ok=True)
    if (camp/'plan.json').exists():
        if json.loads((camp/'plan.json').read_text())!=plan:raise ValueError('input identity changed; new campaign required')
    else:
        if a.resume:raise ValueError('no original plan')
        (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    for src in sources:
        dst=camp/'execution'/src.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists() and sha(dst)!=sha(src):raise ValueError('snapshot changed')
        if not dst.exists():shutil.copyfile(src,dst)
    (camp/'execution/boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
    selected=a.run_only.split(',') if a.run_only else [c.tag for c in conds]
    if set(selected)-{c.tag for c in conds}:raise ValueError('unknown condition')
    groups={}
    for case in cases:
        if case['condition'] not in selected or (a.baseline_only and case['offset_ps'] is not None):continue
        c=Condition.parse(case['condition'])
        if spice.case_output(camp,c.process,case['name']+'.raw',STOP) is None:groups.setdefault(c.process,[]).append(case)
    if groups and not a.baseline_only:
        for tag in {case['condition'] for group in groups.values() for case in group}:
            c=Condition.parse(tag)
            for event in events:
                baseline=next(x for x in cases if x['condition']==tag and x['event']==event and x['offset_ps'] is None)
                path=spice.case_output(camp,c.process,baseline['name']+'.raw',STOP)
                if path is None:
                    raise ValueError(f'{tag}/{event}: run --baseline-only before sweep')
                metrics=measure(path,baseline,entry)
                if not metrics['old_retained'] or not metrics['baseline_matches']:
                    raise ValueError(f'{tag}/{event}: baseline fidelity failed; no shifted runs')
    print(camp,flush=True)
    if groups:
        first=next(iter(groups.values()))[0]
        smoke=spice.run(deck([first],entry,camp/'snap/smoke',True),spice.next_run_dir(camp,'smoke'),timeout_s=150)
        if not smoke.ok or spice.case_output(camp,'smoke','smoke.raw',1e-9) is None:raise RuntimeError(f'smoke failed: {smoke.run_dir}')
        jobs=[(deck(cs,entry,camp/'snap'/proc),spice.next_run_dir(camp,proc),dict(timeout_s=180+15*len(cs),meta=dict(cases=cs,boundary_id=BC))) for proc,cs in groups.items()]
        try:
            for ex in spice.run_many(jobs,workers=a.workers,smoke=False):print(ex.run_dir.name,ex.ok,round(ex.elapsed_s,1),flush=True)
        finally:summarize(camp,cases,entry)
    result=summarize(camp,cases,entry)
    for row in result['rows']:
        if row['status']!='missing':print(row['name'],row['status'],row.get('metrics',{}).get('old_retained'),row.get('metrics',{}).get('baseline_matches'),flush=True)


if __name__=='__main__':main()
