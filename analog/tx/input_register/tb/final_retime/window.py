"""Prepare registered final-rank replay; no simulation is launched by default.

Register explicitly, run zero-offset baseline, then resume with explicit offsets.
Baseline fidelity gates every shifted case.
"""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone

import numpy as np
from pathlib import Path

from serdes_flow import bias, boundary, clock, project, rcorner, spice, watch
from serdes_flow.corners import Condition
from serdes_flow.waves import simplify_pwl

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
CELL = ROOT / 'analog/tx/input_register/spice/final_retime_slice.spice'
TEMPLATE = HERE / 'tb_final_ngspice.cir.in'
PRE = 4e-9
POST = 2e-9
OFFSETS_PS = [-80, -40, 0, 40, 80, 120]
NODES = dict(ap='xtx.xtree.g3_0p', an='xtx.xtree.g3_0n',
             bp='xtx.xtree.g3_1p', bn='xtx.xtree.g3_1n', sp='c2gp', sn='c2gn',
             vbias='vbias', vbias_logic='xtx.xtree.vbias_logic', vdd='vdd')
LOAD_NAMES = ('Cqp', 'Cqn', 'Xdriver', 'Clpp', 'Clpn', 'Rlpp', 'Rlpn', 'Llpp',
              'Llpn', 'Clacp', 'Clacn', 'Xchannel', 'Rlc0', 'Rlc1', 'Clc0',
              'Clc1', 'Vlcm', 'Rlterm0', 'Rlterm1')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def lines(text, names):
    by_name = {line.split()[0].lower(): ' '.join(line.split()).lower()
               for line in text.splitlines() if line.strip() and not line.lstrip().startswith(('*', '.'))}
    return [by_name[name.lower()] for name in names]


def joined_lines(text):
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('*'):
            continue
        if line.startswith('+') and out:
            out[-1] += ' ' + line[1:].strip()
        else:
            out.append(line)
    return [' '.join(x.lower().split()) for x in out]


def validate_source_cell(camp, plan):
    tree_rel = 'analog/tx/serializer/spice/serializer16_retimed_lowov.spice'
    library_rel = 'analog/common/cml_mux/spice/cml_lowov_cells.spice'
    identities = {}
    capture_rel = 'analog/tx/input_register/spice/capture_serializer16.spice'
    for rel in (tree_rel, library_rel, capture_rel):
        key = 'execution/source_snapshot/'+rel
        expected = plan['snapshot_files'][key]
        if sha(camp/key) != expected or sha(ROOT/rel) != expected:
            raise ValueError(f'source cell changed: {rel}')
        identities[rel] = expected
    capture = joined_lines((camp/'execution/source_snapshot'/capture_rel).read_text())
    tree_instance = next(x for x in capture if x.startswith('xtree '))
    expected_ports = ' '.join(f'p{i} n{i}' for i in range(16))
    expected_tree = ('xtree '+expected_ports+' c250p c250n c500p c500n c1gp c1gn c2gp c2gn qp qn vbias vdd vdd vss '
                     'serdes16_cml_tree_retimed_lowov wdata=40 wselect=96 wtail=12 rload=500 rout=400 tail_scale=6 wsf=80')
    if tree_instance != expected_tree:
        raise ValueError('source tree instance or parameters changed')
    tree = joined_lines((camp/'execution/source_snapshot'/tree_rel).read_text())
    target = next(x for x in tree if x.startswith('xr4_0 '))
    expected = ('xr4_0 g3_0p g3_0n g3_1p g3_1n c2gp c2gn qp qn vbias vbias_logic vdd vss '
                'serdes_cml_latched_mux2_lowov wdata={wdata} wselect={wselect} wtail={tail_scale*wtail} '
                'nftail={4*tail_scale} wsf={wsf} wsf_sink={wsf_sink} rload={rout}')
    header = next(x for x in tree if x.startswith('.subckt serdes16_cml_tree_retimed_lowov '))
    defaults = 'params: wdata=40 wselect=96 wtail=12 rload=500 rout=400 tail_scale=6 wsf=80 wsf_sink=4'
    wrapper = joined_lines(CELL.read_text())
    wrapped = next(x for x in wrapper if x.startswith('xfinal '))
    canonical = ('xfinal ap an bp bn sp sn qp qn vbias vbias_logic vdd vss serdes_cml_latched_mux2_lowov '
                 'wdata=40 wselect=96 wtail=72 nftail=24 rload=400 whold=40 wsf=80 wsf_sink=4 '
                 'latch_tail_scale=2 latch_load_scale=.75')
    library = joined_lines((camp/'execution/source_snapshot'/library_rel).read_text())
    latch_header = next(x for x in library if x.startswith('.subckt serdes_cml_latched_mux2_lowov '))
    if target != expected or defaults not in header or wrapped != canonical or 'whold=40' not in latch_header or 'latch_tail_scale=2' not in latch_header or 'latch_load_scale=0.75' not in latch_header:
        raise ValueError('source final-rank instance or parameter mapping changed')
    return identities


def register(camps, bc_id, bits):
    check_source_map()
    load = lines(TEMPLATE.read_text(), LOAD_NAMES)
    points = {}
    for camp in camps:
        camp = camp.resolve()
        plan = json.loads((camp/'plan.json').read_text())
        summary = json.loads((camp/'summary.json').read_text())
        source = ROOT / plan['source_campaign']
        for path, key in ((source/'plan.json', 'source_plan_sha256'),
                          (source/'summary.json', 'source_summary_sha256'),
                          (ROOT/plan['source_waveform'], 'source_waveform_sha256')):
            if sha(path) != plan[key]:
                raise ValueError(f'source identity changed: {path}')
        for path, expected in plan['snapshot_files'].items():
            if sha(camp/path) != expected:
                raise ValueError(f'checkpoint changed: {path}')
        if not summary['calibration']['passed']:
            raise ValueError('source trace calibration failed')
        raw = spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s'])
        if raw is None or raw.resolve() != (ROOT/summary['waveform']).resolve() or sha(raw) != summary['waveform_sha256']:
            raise ValueError('trace raw missing, truncated, or changed')
        if lines((camp/'execution/physical_tb.cir').read_text(), LOAD_NAMES) != load:
            raise ValueError('direct downstream load differs from source')
        source_cells = validate_source_cell(camp, plan)
        validate_execution(raw)
        w = spice.Waves(raw)
        source_summary = json.loads((source/'summary.json').read_text())
        rows = [r for r in source_summary['captures'] if r['payload_valid']]
        fall = clock.edges(w.t, w['c250p']-w['c250n'], -1)
        rise = clock.edges(w.t, w['c250p']-w['c250n'], 1)
        events = {}
        for bit in bits:
            word = bit // 16
            if word >= len(rows):
                raise ValueError(f'bit {bit} missing from captures')
            a = fall[fall >= rows[word]['capture_s']]
            if not len(a):
                raise ValueError(f'bit {bit}: missing A edge')
            b = rise[rise > a[0]]
            if not len(b):
                raise ValueError(f'bit {bit}: missing B edge')
            edge = float(a[0] if bit % 16 < 8 else b[0])
            if edge-PRE < w.t[0] or edge+POST > w.t[-1]:
                raise ValueError(f'bit {bit}: prehistory or posthistory absent')
            events[str(bit)] = dict(bit=bit, word=word, slot=bit%16, source_word=rows[word]['word'],
                                    selection='A_fall' if bit%16 < 8 else 'B_rise',
                                    selection_edge_s=edge, origin_s=edge-PRE, stop_s=PRE+POST)
        tag = plan['condition']
        if tag in points:
            raise ValueError('duplicate condition')
        points[tag] = dict(condition=tag, raw=str(raw.relative_to(ROOT)), raw_sha256=sha(raw),
                           trace_campaign=str(camp.relative_to(ROOT)), trace_plan_sha256=sha(camp/'plan.json'),
                           trace_summary_sha256=sha(camp/'summary.json'), source_campaign=plan['source_campaign'],
                           source_plan_sha256=plan['source_plan_sha256'], source_summary_sha256=plan['source_summary_sha256'],
                           circuit_sha256=plan['circuit_sha256'], source_cells=source_cells, events=events)
    load_hash = hashlib.sha256(('\n'.join(load)+'\n').encode()).hexdigest()
    entry = dict(id=bc_id, kind='loaded_internal_port_voltage_replay',
        description='Recorded full-TX final rank ports; local replay prototype.',
        upstream=dict(module='tx.serializer', revision='retimed_lowov', campaigns=[str(p.resolve().relative_to(ROOT)) for p in camps]),
        nodes=NODES, load=dict(direct_downstream_lines=load, sha256=load_hash,
                              source_cell='serdes_cml_latched_mux2_lowov',
                              parameters='wdata=40 wselect=96 wtail=72 nftail=24 rload=400 whold=40 wsf=80 wsf_sink=4 latch_tail_scale=2 latch_load_scale=.75'),
        consumer_sha256=sha(CELL), template_sha256=sha(TEMPLATE), points=points,
        processing='4 ns history and 2 ns after actual halfword edge; only c2g pair shifted together; bounded voltage PWL.',
        validation=dict(state='pending_baseline_comparison', waveform_error_gate_v=.005),
        valid_while=['identical cells, downstream load, PDK, source traces and recorded condition',
                     'ideal voltage replay omits upstream source impedance and feedback',
                     'zero-shift qp/qn and both held pairs must match source within 5 mV before shifted conclusions',
                     'local event study only, no mismatch, noise, full PVT or real buffer claim'])
    existing = boundary.registry().get(bc_id)
    if existing is None:
        boundary.register(entry)
    elif existing != entry:
        raise ValueError('boundary id already exists with different identity')
    return entry


STOP = PRE + POST
TOL = 10e-6
TIME_GRID = 1e-16  # 100 as: merge numerically coincident breakpoints across sources.
INPUT_GATE = 200e-6
SOURCE_MAP = dict(ap='Vap', an='Van', bp='Vbp', bn='Vbn', sp='Vsp', sn='Vsn',
                  vbias='Vbias', vbias_logic='Vlogic', vdd='Vdd')
REFS = dict(qp='qp', qn='qn', ahp='xtx.xtree.xr4_0.ahp', ahn='xtx.xtree.xr4_0.ahn',
            bhp='xtx.xtree.xr4_0.bhp', bhn='xtx.xtree.xr4_0.bhn')
VECTORS = ' '.join('v('+x+')' for x in ('ap','an','bp','bn','sp','sn','vbias','vbias_logic','vdd',
                     'qp','qn','xslice.xfinal.ahp','xslice.xfinal.ahn','xslice.xfinal.bhp','xslice.xfinal.bhn'))
DEPENDENCIES = ('analog/common/devices/spice/sky130_primitives.spice',
                'analog/common/devices/spice/cmos_logic.spice',
                'analog/common/devices/spice/sky130_pfet_lvt.spice',
                'analog/common/cml_buffer/spice/cml_buffer.spice',
                'analog/common/cml_buffer/spice/cml_delay_resistive.spice',
                'analog/common/cml_mux/spice/cml_lowov_cells.spice',
                'analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice',
                'verification/models/channel/diff_rlc16.spice')


def validate_execution(raw):
    run = Path(raw).parent
    ex = json.loads((run/'execution.json').read_text())
    if ex.get('exit_code') != 0 or ex.get('timed_out') or ex.get('log_failures'):
        raise ValueError(f'failed source execution: {run}')
    if sha(run/'tb.cir') != ex['deck_sha256']:
        raise ValueError(f'execution deck hash mismatch: {run}')


def check_source_map():
    defined = {line.split()[0].lower() for line in TEMPLATE.read_text().splitlines()
               if line.strip() and line.strip()[0].lower() == 'v'}
    if len({x.lower() for x in SOURCE_MAP.values()}) != len(SOURCE_MAP) or set(SOURCE_MAP) != set(NODES):
        raise ValueError('invalid replay source map')
    missing = {x for x in SOURCE_MAP.values() if x.lower() not in defined}
    if missing:
        raise ValueError(f'replay voltage sources missing from template: {missing}')


def verify_entry(entry):
    if sha(CELL) != entry['consumer_sha256'] or sha(TEMPLATE) != entry['template_sha256']:
        raise ValueError('consumer or template changed')
    if lines(TEMPLATE.read_text(), LOAD_NAMES) != entry['load']['direct_downstream_lines']:
        raise ValueError('consumer load changed')
    for point in entry['points'].values():
        camp = ROOT / point['trace_campaign']
        plan = json.loads((camp/'plan.json').read_text())
        if sha(camp/'plan.json') != point['trace_plan_sha256'] or sha(camp/'summary.json') != point['trace_summary_sha256']:
            raise ValueError('trace metadata changed')
        if sha(ROOT/point['raw']) != point['raw_sha256']:
            raise ValueError('trace raw changed')
        if spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s']) != ROOT/point['raw']:
            raise ValueError('trace waveform missing or truncated')
        validate_execution(ROOT/point['raw'])
        for name, expected in plan['snapshot_files'].items():
            if sha(camp/name) != expected:
                raise ValueError(f'trace checkpoint changed: {name}')
        if validate_source_cell(camp, plan) != point['source_cells']:
            raise ValueError('source cell identity changed')
        for rel in DEPENDENCIES:
            expected = plan['snapshot_files']['execution/source_snapshot/'+rel]
            if sha(ROOT/rel) != expected:
                raise ValueError(f'physical dependency differs from source: {rel}')
        source = ROOT / point['source_campaign']
        if sha(source/'plan.json') != point['source_plan_sha256'] or sha(source/'summary.json') != point['source_summary_sha256']:
            raise ValueError('source metadata changed')
        if sha(ROOT/plan['source_waveform']) != plan['source_waveform_sha256']:
            raise ValueError('source raw changed')
        if project.pdk_installation_id() != plan['pdk_installation_id'] or sha(project.model_library()) != plan['model_library_sha256']:
            raise ValueError('PDK identity changed')


def event_waves(point, bit):
    event = point['events'][str(bit)]
    w = spice.Waves(ROOT/point['raw'])
    origin = event['origin_s']
    if w.t[0] > origin or w.t[-1] < origin + STOP:
        raise ValueError('recording no longer covers window')
    t = np.r_[0., w.t[(w.t > origin) & (w.t < origin+STOP)]-origin, STOP]
    signals = {name: np.interp(t+origin, w.t, w[node]) for name, node in NODES.items()}
    refs = {name: np.interp(t+origin, w.t, w[node]) for name, node in REFS.items()}
    return t, signals, refs


def shifted_pwl(t, y, shift):
    moved = t + shift
    ti = np.r_[0., moved[(moved > 0) & (moved < STOP)], STOP]
    yi = np.interp(ti-shift, t, y)
    quantized=np.unique(np.rint(ti/TIME_GRID).astype(np.int64))*TIME_GRID
    quantized[0],quantized[-1]=0.,STOP
    voltages=np.interp(quantized-shift,t,y)
    # Reserve half the bound for time quantization. The explicit comparison
    # below still enforces the original full 10 uV waveform contract.
    ts, ys = simplify_pwl(quantized, voltages, TOL/2)
    if np.max(np.abs(np.interp(ti, ts, ys)-yi)) > TOL*(1+1e-9):
        raise ValueError('PWL error gate failed')
    return ts, ys


def alter_pwl(name, t, y, shift):
    ts, ys = shifted_pwl(t, y, shift)
    vals = np.column_stack((ts, ys)).ravel()
    if len(vals) <= 360:
        return [f'alter {name} dc={ys[0]:.12e}', 'alter @'+name+'[pwl] = [ '+' '.join(f'{v:.12e}' for v in vals)+' ]']
    return ([f'alter {name} dc={ys[0]:.12e}', f'let replay_pwl=vector({len(vals)})'] +
            [f'let replay_pwl[{i}]={v:.12e}' for i, v in enumerate(vals)] +
            ['alter @'+name+'[pwl] = replay_pwl', 'unlet replay_pwl'])


def case_name(tag, bit, offset):
    return f'{tag}_bit{bit}_d{offset:+d}ps'


def deck(cases, entry, snap, smoke=False):
    first = Condition.parse(cases[0]['condition'])
    commands = []
    for case in cases:
        c = Condition.parse(case['condition'])
        t, signals, _ = event_waves(entry['points'][c.tag], case['bit'])
        for name, data in signals.items():
            source_name = SOURCE_MAP[name]
            shift = case['offset_ps']*1e-12 if name in ('sp','sn') else 0.
            commands.extend(alter_pwl(source_name, t, data, shift))
        commands += [f'option temp={c.temp}', f'alter Vtxen dc={c.supply:.12e}']
        tran = 'tran .5p 1.001n 0 .5p' if smoke else spice.skip_output_before(f'tran .5p {STOP:.12e} 0 .5p', '.1n')
        commands += [tran, 'write '+('smoke' if smoke else case['name'])+'.raw '+VECTORS, 'destroy all']
    text = spice.render(TEMPLATE, **spice.corner_values(first), CASES='\n'.join(commands), VECTORS=VECTORS)
    return bias.section(rcorner.to_pdk(text, snap), first.process, 'tt')


def measure(path, case, entry):
    w = spice.Waves(path)
    if w.t[-1] < STOP*(1-1e-6):
        raise ValueError('truncated case')
    t, signals, refs = event_waves(entry['points'][case['condition']], case['bit'])
    input_errors = {}
    for name, data in signals.items():
        shift = case['offset_ps']*1e-12 if name in ('sp','sn') else 0.
        input_errors[name] = float(np.max(np.abs(w[name]-np.interp(w.t-shift, t, data))))
    if max(input_errors.values()) > INPUT_GATE:
        raise ValueError(f'input replay error: {input_errors}')
    keep = (w.t >= PRE-.5e-9) & (w.t <= STOP-.2e-9)
    names = dict(qp='qp', qn='qn', ahp='xslice.xfinal.ahp', ahn='xslice.xfinal.ahn',
                 bhp='xslice.xfinal.bhp', bhn='xslice.xfinal.bhn')
    errors = {name: float(np.max(np.abs(w[node][keep]-np.interp(w.t[keep],t,refs[name]))))
              for name,node in names.items()}
    return dict(input_max_error_v=input_errors, reference_window_s=[PRE-.5e-9,STOP-.2e-9],
                original_trace_error_v=errors,
                baseline_matches=(max(errors.values()) <= .005) if case['offset_ps']==0 else None,
                comparison_status='baseline fidelity' if case['offset_ps']==0 else 'observation relative to unshifted trace, not pass/fail')


def execute(entry, bc_id, resume, offsets):
    check_source_map()
    verify_entry(entry)
    sources = [Path(__file__).resolve(), CELL, TEMPLATE] + [ROOT/x for x in DEPENDENCIES]
    sources += [ROOT/'src/serdes_flow'/x for x in ('spice.py','clock.py','waves.py','bias.py','rcorner.py','boundary.py','project.py','corners.py','watch.py')]
    identity = {str(p.relative_to(ROOT)):sha(p) for p in sources}
    bc_hash = hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
    if resume:
        camp = resume.resolve()
        plan = json.loads((camp/'plan.json').read_text())
        if plan['sources'] != identity or plan['boundary_sha256'] != bc_hash:
            raise ValueError('campaign identity changed')
    else:
        camp = ROOT/'results/analog/tx/final_retime'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        camp.mkdir(parents=True, exist_ok=False)
        plan = dict(boundary_id=bc_id, boundary_sha256=bc_hash, sources=identity, stop_s=STOP,numerical_time_grid_s=TIME_GRID,pwl_error_bound_v=TOL,
                    evaluation_window_s=[PRE-.5e-9,STOP-.2e-9], offsets_ps=OFFSETS_PS,
                    conditions=list(entry['points']), events={k:list(v['events']) for k,v in entry['points'].items()})
        (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
        (camp/'boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
        for src in sources:
            dest=camp/'execution'/src.relative_to(ROOT)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(src,dest)
    for rel, expected in identity.items():
        if sha(camp/'execution'/rel) != expected:
            raise ValueError(f'campaign snapshot changed: {rel}')
    all_cases = [dict(condition=tag, bit=int(bit), offset_ps=offset, name=case_name(tag,int(bit),offset))
                 for tag, point in entry['points'].items() for bit in point['events'] for offset in OFFSETS_PS]
    selected = [c for c in all_cases if c['offset_ps'] in offsets]
    if any(path.is_relative_to(camp) for path in watch.ngspice_cwds()):
        raise RuntimeError('campaign has a live ngspice process; refuse duplicate execution')
    if any(c['offset_ps'] != 0 for c in selected):
        for c in selected:
            baseline = dict(c, offset_ps=0, name=case_name(c['condition'],c['bit'],0))
            proc = Condition.parse(c['condition']).process
            raw = spice.case_output(camp,proc,baseline['name']+'.raw',STOP)
            if raw is not None:
                validate_execution(raw)
            if raw is None or not measure(raw, baseline, entry)['baseline_matches']:
                raise ValueError(f"{c['condition']} bit {c['bit']}: zero-offset baseline missing or failed")
    groups = {}
    for case in selected:
        proc = Condition.parse(case['condition']).process
        raw = spice.case_output(camp,proc,case['name']+'.raw',STOP)
        if raw is None:
            groups.setdefault(proc,[]).append(case)
        else:
            validate_execution(raw)
    print(camp, flush=True)
    if groups:
        first = next(iter(groups.values()))[0]
        smoke = spice.run(deck([first],entry,camp/'snap/smoke',True),spice.next_run_dir(camp,'smoke'),timeout_s=180)
        if not smoke.ok or spice.case_output(camp,'smoke','smoke.raw',1e-9) is None:
            raise RuntimeError('smoke failed')
        for proc, cases in groups.items():
            ex = spice.run(deck(cases,entry,camp/'snap'/proc),spice.next_run_dir(camp,proc),
                           timeout_s=180+120*len(cases),meta=dict(cases=cases,boundary_id=bc_id))
            if not ex.ok:
                raise RuntimeError(f'incomplete deck: {ex.run_dir}')
    rows = []
    for case in all_cases:
        proc=Condition.parse(case['condition']).process
        raw=spice.case_output(camp,proc,case['name']+'.raw',STOP)
        row=dict(case, status='missing')
        if raw:
            try:
                validate_execution(raw)
                row.update(status='measured', waveform=str(raw.relative_to(ROOT)), waveform_sha256=sha(raw), metrics=measure(raw,case,entry))
            except (ValueError, KeyError) as e:
                row.update(status='analysis_error', error=str(e))
        rows.append(row)
    output=dict(boundary_id=bc_id, scope='Local ideal-voltage replay; baseline gate required; no PVT, mismatch or noise qualification.',rows=rows)
    tmp=camp/'summary.json.tmp'
    tmp.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    tmp.replace(camp/'summary.json')
    return camp

def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--register', action='store_true')
    group.add_argument('--run', action='store_true')
    group.add_argument('--resume', type=Path)
    p.add_argument('--campaign', type=Path, action='append', default=[])
    p.add_argument('--boundary-id', required=True)
    p.add_argument('--bits', default='104')
    p.add_argument('--offsets-ps', help='explicit comma-separated offsets for resume; use = for negatives')
    args = p.parse_args()
    if args.register:
        if not args.campaign:
            p.error('--register requires at least one --campaign')
        bits = [int(x) for x in args.bits.split(',')]
        if len(bits) != len(set(bits)) or any(x < 0 for x in bits):
            p.error('bits must be unique nonnegative integers')
        print(register(args.campaign, args.boundary_id, bits)['id'])
        return
    if args.run and args.offsets_ps:
        p.error('--run is baseline-only; use --resume for explicit offsets')
    if args.resume and not args.offsets_ps:
        p.error('--resume requires --offsets-ps')
    offsets = [0] if args.run else [int(x) for x in args.offsets_ps.split(',')]
    if not offsets or len(offsets)!=len(set(offsets)) or set(offsets)-set(OFFSETS_PS):
        p.error(f'offsets must be unique and drawn from {OFFSETS_PS}')
    entry = boundary.get(args.boundary_id)
    print(execute(entry, args.boundary_id, args.resume, offsets))


if __name__ == '__main__':
    main()
