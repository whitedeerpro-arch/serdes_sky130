#!/usr/bin/env python3
"""Collect archived full-TX dynamic runs and render training-aligned eyes.

No simulation is performed. Repeated --collect arguments add conditions.
"""
import argparse
import hashlib
import json
import math
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, serial, spice
from serdes_flow.project import ROOT
from serdes_flow.corners import Condition
from serdes_flow.clock_profiles import normalize_extra

DEFAULT = ROOT / 'results/analog/tx/parallel_serializer/20261107T044921Z'
DATA = ROOT / 'docs/data/tx_parallel_serializer.json'
CATALOG = ROOT / 'results/catalog/tx_parallel_serializer.json'
FIG = ROOT / 'docs/figures/tx/ingress/tx_parallel_serializer_eye'


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def equal(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return bool(np.isclose(a, b, rtol=1e-9, atol=1e-12))
    return a == b


def stimulus_graph_signature(text):
    nodes=[]
    for raw in text.split('.control',1)[0].splitlines():
        words=raw.split()
        if words and re.fullmatch(r'V(?:d\d+|guard_(?:a|b|ready|valid))',words[0],re.I):
            if len(words)<4:raise ValueError('malformed stimulus voltage source')
            nodes.append(' '.join(words[:3]).lower())
    return hashlib.sha256('\n'.join(nodes).encode()).hexdigest()


def check_stimulus_graph(plan, entry, text):
    graph=stimulus_graph_signature(text)
    if plan.get('numerical_source_graph_sha256') is not None and entry.get('upstream',{}).get('numerical_source_graph_sha256') is None:
        raise ValueError('new campaign requires a source-graph-bound probe')
    for expected in (plan.get('numerical_source_graph_sha256'),entry.get('upstream',{}).get('numerical_source_graph_sha256')):
        if expected is not None and graph!=expected:
            raise ValueError('stimulus source graph differs from archive identity')
    return graph


def clock_extra_2g(plan, entry, deck_text):
    """Check metadata against the actual archived v3 2 GHz chain."""
    declared_plan = plan.get('clock_extra_2g', 1)
    declared_boundary = entry.get('upstream', {}).get('clock_extra_2g', 1)
    if (type(declared_plan) is not int or type(declared_boundary) is not int or
            declared_plan not in (1, 2, 3, 4, 5) or declared_plan != declared_boundary):
        raise ValueError('clock extra stage metadata mismatch or unsupported value')
    lines = [' '.join(line.lower().split()) for line in deck_text.splitlines()]
    stages = [line.split() for line in lines if re.match(r'^xe2g_\d+\s', line)]
    by_name = {line[0]: line for line in stages}
    if len(stages) != declared_plan or set(by_name) != {f'xe2g_{i}' for i in range(declared_plan)}:
        raise ValueError('clock extra stage count differs from archived deck')
    expected = lambda name, src, dst, size: [name, src+'p', src+'n', dst+'p', dst+'n',
        'vbias', 'vdd', 'vss', 'serdes_cml_buffer', *size]
    small = ['wn=24', 'wt=16', 'rload=400']
    iso = next((line.split() for line in lines if line.startswith('xiso2g ')), None)
    if iso != expected('xiso2g','r2g','i2g',small):
        raise ValueError('clock input isolation stage differs from v3')
    stage_wt, stage_r = clock_stage_parameters(plan, entry)
    profile=clock_stage_profile(plan,entry)
    for i in range(declared_plan):
        src = 'i2g' if i == 0 else f'e2g_{i-1}'
        actual = by_name[f'xe2g_{i}']
        prefix = expected(f'xe2g_{i}',src,f'e2g_{i}',[])
        if actual[:len(prefix)] != prefix or len(actual) != len(prefix)+3:
            raise ValueError('clock extra stage connectivity differs from v3')
        try:
            params = dict(token.split('=',1) for token in actual[len(prefix):])
            wn,wt,r=profile[i] if profile is not None else (24,stage_wt,stage_r)
            valid = set(params)=={'wn','wt','rload'} and float(params['wn'])==wn and float(params['wt'])==wt and float(params['rload'])==r
        except (ValueError,KeyError):valid=False
        if not valid:raise ValueError('clock extra-stage sizes differ from archived metadata')
    wt, resistance = clock_output_parameters(plan, entry)
    out = next((line.split() for line in lines if line.startswith('xout2g ')), None)
    prefix = expected('xout2g',f'e2g_{declared_plan-1}','c2g',[])
    if out is None or out[:len(prefix)] != prefix or len(out) != len(prefix)+3:
        raise ValueError('clock output stage connectivity differs from v3')
    try:
        parameters = dict(token.split('=',1) for token in out[len(prefix):])
        valid = set(parameters)=={'wn','wt','rload'} and float(parameters['wn'])==32 and float(parameters['wt'])==wt and float(parameters['rload'])==resistance
    except (ValueError,KeyError):
        valid = False
    if not valid:raise ValueError('clock output parameters differ from archived metadata')
    return declared_plan


def clock_output_parameters(plan, entry):
    return clock_pair_parameters(plan, entry, 'clock_output', (24,300))


def clock_stage_parameters(plan, entry):
    return clock_pair_parameters(plan, entry, 'clock_stage', (16,400))


def clock_pair_parameters(plan, entry, stem, defaults):
    def checked(obj):
        values=(obj.get(stem+'_wt',defaults[0]),obj.get(stem+'_r',defaults[1]))
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) or x<=0 for x in values):
            raise ValueError(stem+' parameters must be positive finite numbers')
        return values
    planned=checked(plan); registered=checked(entry.get('upstream',{}))
    if planned!=registered:raise ValueError(stem+' parameters differ from boundary')
    return planned


def clock_stage_profile(plan,entry):
    def checked(obj):
        value=obj.get('clock_stage_profile')
        return None if value is None else normalize_extra(value,obj.get('clock_extra_2g',1))
    planned,registered=checked(plan),checked(entry.get('upstream',{}))
    if planned!=registered:raise ValueError('per-stage profile differs from boundary')
    return planned


def case_label(case):
    c = Condition.parse(case['condition'])
    text=f"{c.process.upper()} {c.supply:g}V {c.temp}°C / extra2g={case.get('clock_extra_2g', 1)} / wt={case.get('clock_output_wt',24):g} R={case.get('clock_output_r',300):g}"
    if case.get('clock_stage_profile') is not None:
        text+=' / extra WT='+','.join(f'{s[1]:g}' for s in case['clock_stage_profile'])
    elif (case.get('clock_stage_wt',16),case.get('clock_stage_r',400))!=(16,400):
        text+=f" / extra WT{case['clock_stage_wt']:g} R{case['clock_stage_r']:g}"
    return text


def collect(camp):
    camp = camp.resolve()
    plan = read(camp / 'plan.json')
    if plan['mode'] != 'run':
        raise ValueError('requires dynamic run campaign')
    manifest = read(camp / 'execution/stimulus_manifest.json')
    entry = read(camp / 'execution/boundary.json')
    if hashlib.sha256(json.dumps(entry, sort_keys=True).encode()).hexdigest() != plan['boundary_sha256']:
        raise ValueError('archived boundary hash mismatch')
    if manifest['boundary_id'] != plan['boundary_id'] or entry['id'] != plan['boundary_id']:
        raise ValueError('boundary identity mismatch')
    for rel, expected in plan['snapshot_files'].items():
        if digest(camp / rel) != expected:
            raise ValueError(f'archived snapshot hash mismatch: {rel}')
    for name, info in manifest['outputs'].items():
        if digest(camp / 'execution/producer' / name) != info['sha256']:
            raise ValueError(f'producer output hash mismatch: {name}')
    captures = []
    for line in (camp / 'execution/producer/captures.tsv').read_text().splitlines():
        time, word, valid = line.split()
        captures.append(dict(time_ps=float(time), word=int(word, 16), valid=int(valid)))
    if captures != manifest['captures']:
        raise ValueError('manifest and archived capture events disagree')
    if digest(camp / 'execution/stimuli.inc') != manifest['outputs']['stimuli.inc']['sha256']:
        raise ValueError('replayed stimuli differ from producer output')
    processing = entry['processing']
    schedule = ROOT / processing['schedule']
    if digest(schedule) != processing['schedule_sha256'] or manifest['schedule_sha256'] != processing['schedule_sha256']:
        raise ValueError('producer schedule hash mismatch')
    point = entry['points'][plan['condition']]
    if digest(ROOT / point['raw']) != point['raw_sha256']:
        raise ValueError('probe waveform hash mismatch')
    wave = spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s'])
    if wave is None:
        raise ValueError('missing, unreadable or truncated waveform')
    ex = read(wave.parent / 'execution.json')
    if ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']:
        raise ValueError('simulation execution reports failure')
    if digest(wave.parent / 'tb.cir') != ex['deck_sha256'] or ex['deck_sha256'] != plan['deck_sha256']:
        raise ValueError('executed deck hash mismatch')
    deck_text=(wave.parent / 'tb.cir').read_text()
    graph_sha=check_stimulus_graph(plan,entry,deck_text)
    extra_2g = clock_extra_2g(plan, entry, deck_text)
    output_wt, output_r = clock_output_parameters(plan, entry)
    stage_wt, stage_r = clock_stage_parameters(plan, entry)
    profile=clock_stage_profile(plan,entry)
    w = spice.Waves(wave)
    c = Condition.parse(plan['condition'])
    actual = clock.edges(w.t, w['xtx.word_clk'] - c.supply / 2, 1, 12e-9, w.t[-1] - 1.2e-9)
    logical = [x for x in captures if 12e-9 <= x['time_ps'] * 1e-12 <= w.t[-1] - 1.2e-9]
    accepted = []
    for item in logical:
        hits = actual[np.abs(actual - item['time_ps'] * 1e-12) < 100e-12]
        if len(hits) != 1:
            raise ValueError('actual word clock does not match producer capture')
        if item['valid']:
            accepted.append((item, float(hits[0])))
    if len(accepted) != (64 + plan['payload_bits'] + 32) // 16:
        raise ValueError('incomplete accepted producer words')
    first = clock.edges(w.t, w['c250p'] - w['c250n'], -1, accepted[0][1])
    if not len(first):
        raise ValueError('missing first selected halfword edge')
    bits = np.array([(item['word'] >> i) & 1 for item, _ in accepted for i in range(16)])
    seq = serial.Sequence(bits, float(first[0]), 250e-12)
    summary = read(camp / 'summary.json')
    if not np.isclose(summary['sequence_start_s'], seq.start_s, atol=1e-15, rtol=0):
        raise ValueError('summary sequence start differs from actual clock')
    outputs = {}
    x = np.linspace(-0.5, 1.5, 81)
    for label, p, n in [('serializer', 'qp', 'qn'), ('pad', 'lqp', 'lqn'), ('remote', 'lrp', 'lrn')]:
        y = w[p] - w[n]
        metrics, details = serial.check(w.t, y, seq, plan['payload_bits'])
        mapping = serial.bit_mapping(w.t, y, seq)
        result = dict(check=metrics, meets_spec=serial.meets_draft(metrics), mapping=mapping)
        if not equal(result, summary['outputs'][label]):
            raise ValueError(f'{label} recomputation disagrees with archived summary')
        # Uniformly sample payload UIs, aligned to training-only delay.
        indices = np.linspace(64, 64 + plan['payload_bits'] - 2, min(64, plan['payload_bits'] - 1), dtype=int)
        payload=np.arange(64,64+plan['payload_bits'])
        signed=np.asarray(details['sample_voltage_v'])[payload]*(2*bits[payload]-1)
        # Keep the worst observed bits even when a regular display subsample
        # would skip an isolated narrow eye. This never changes measurement.
        worst=payload[np.argsort(signed)[:16]]
        indices=np.unique(np.r_[indices,worst])
        traces = [np.interp(seq.start_s + (i + metrics['training_delay_ui'] + x) * seq.ui_s, w.t, y).round(6).tolist() for i in indices]
        outputs[label] = dict(**result,grading_scope='serializer_spec' if label=='serializer' else 'comparison_screen_not_link_spec', eye_trace_bit_indices=indices.tolist(),eye_ui=x.round(4).tolist(), eye_v=traces)
    return dict(campaign=str(camp.relative_to(ROOT)), condition=plan['condition'], clock_extra_2g=extra_2g, clock_output_wt=output_wt, clock_output_r=output_r, clock_stage_wt=stage_wt, clock_stage_r=stage_r, clock_stage_profile=profile, numerical_source_graph_sha256=graph_sha, waveform=str(wave.relative_to(ROOT)),
                hashes=dict(waveform_sha256=digest(wave), plan_sha256=digest(camp/'plan.json'),
                            summary_sha256=digest(camp/'summary.json'), manifest_sha256=digest(camp/'execution/stimulus_manifest.json'),
                            boundary_sha256=plan['boundary_sha256'], probe_raw_sha256=point['raw_sha256'],
                            schedule_sha256=processing['schedule_sha256'], deck_sha256=ex['deck_sha256']),
                accepted_words=len(accepted), actual_capture_edges=len(logical), sequence_start_s=seq.start_s,
                input_boundary_ok=summary['input_boundary_ok'], halfword_hold_ok=summary['halfword_hold_ok'],
                behavioral_tags_align=summary['behavioral_tags_align'], counter=summary['counter'], outputs=outputs)


def plot(cases):
    fig, axes = plt.subplots(2, 3, figsize=(16, 8), layout='constrained', gridspec_kw={'height_ratios': [2.1, 1]})
    labels = ('serializer', 'pad', 'remote')
    colors = plt.cm.tab10.colors
    spread_limit=max(.18,1.2*max(c['outputs'][label]['check']['transition_spread_ui'] or 0 for c in cases for label in labels))
    for col, label in enumerate(labels):
        ax = axes[0, col]
        # All conditions shown with translucent traces and a condition legend.
        for j, case in enumerate(cases):
            out = case['outputs'][label]
            for trace in out['eye_v']:
                ax.plot(out['eye_ui'], np.array(trace) * 1000, color=colors[j % len(colors)], alpha=.09, lw=.7)
            ax.plot([], [], color=colors[j % len(colors)], label=case_label(case))
        ax.axhline(75, color='#bc3434', lw=.8, ls='--'); ax.axhline(-75, color='#bc3434', lw=.8, ls='--')
        ax.axvline(.5, color='#777777', lw=.7, ls=':')
        ax.set(title=label.capitalize(), xlabel='Time within eye (UI)', ylabel='Differential voltage (mV)')
        ax.set_ylim(-270,270)
        ax.grid(alpha=.15)
        if col == 0: ax.legend(fontsize=8, loc='upper right')
        ax = axes[1, col]
        pos = np.arange(len(cases)); width=.36
        margins = [c['outputs'][label]['check']['minimum_signed_margin_v'] * 1000 for c in cases]
        spreads = [c['outputs'][label]['check']['transition_spread_ui'] for c in cases]
        ax.bar(pos-width/2, margins, width, color='#296d98', label='Signed margin (mV)')
        ax.axhline(75, color='#296d98', ls='--', lw=1)
        ax.set_ylabel('Signed margin (mV)', color='#296d98')
        ax.set_ylim(0,260)
        other = ax.twinx()
        other.bar(pos+width/2, [v if v is not None else 0 for v in spreads], width, color='#cc7843', label='Spread (UI)')
        other.axhline(.15, color='#cc7843', ls='--', lw=1)
        other.set_ylabel('Edge spread (UI)', color='#a75320')
        other.set_ylim(0,spread_limit)
        ax.set_xticks(pos, [case_label(c).replace(' / ', '\n') for c in cases], rotation=0, ha='center', fontsize=7)
        for j, case in enumerate(cases):
            out=case['outputs'][label]
            # the pad is a gate from 2026-11-08 (docs/overview/spec.md); the remote stays a comparison screen
            kind='EYE' if label=='serializer' else 'GATE' if label=='pad' else 'SCREEN'
            status=f"{kind}\n{'PASS' if out['meets_spec'] else 'FAIL'}"
            ax.text(j, .97, status, transform=ax.get_xaxis_transform(), ha='center', va='top', fontsize=7,
                    color='#287748' if out['meets_spec'] else '#b22222', fontweight='bold')
    fig.suptitle('Full TX dynamic serialization: training-aligned payload eyes', fontsize=15)
    fig.supxlabel('Serializer and pad gates: ±75 mV, 0.15 UI (pad gate from 2026-11-08). Remote: same comparison screen; link acceptance remains separate.\nTraining-only phase; 250 ps/UI; weakest payload bits retained in displayed traces.', fontsize=9)
    FIG.parent.mkdir(parents=True, exist_ok=True)
    for ext in ('png', 'svg'): fig.savefig(FIG.with_suffix('.' + ext), dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='append', type=Path, help='dynamic campaign directory; repeat for multiple conditions')
    args = parser.parse_args()
    paths = args.collect or [DEFAULT]
    cases, failures = [], []
    for path in paths:
        try:
            cases.append(collect(path))
        except (ValueError, KeyError, IndexError, OSError) as error:
            failures.append(dict(campaign=str(path), error=str(error)))
    analysis=[Path(__file__).resolve()]+[ROOT/'src/serdes_flow'/name for name in ('serial.py','clock.py','spice.py','waves.py')]
    result = dict(analysis_sources=[dict(path=str(p.relative_to(ROOT)),sha256=digest(p)) for p in analysis],
                  scope='Ideal 2 GHz source; real bias and PDK R tt; initialized counter; RTL event-model tags. Not 45 PVT, MC, noise, PLL or startup qualification.',
                  phase='Eye and serial.check phase from training only; serial.bit_mapping independently uses payload crossings for order-agnostic diagnosis.',
                  cases=cases, collection_failures=failures)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    CATALOG.write_text(json.dumps(dict(scope=result['scope'], cases=[{k:v for k,v in c.items() if k != 'outputs'} for c in cases], collection_failures=failures), indent=2, allow_nan=False) + '\n')
    if cases: plot(cases)
    if failures:
        raise SystemExit('Collection failed: ' + json.dumps(failures, ensure_ascii=False))
    print(f'Collected {len(cases)} campaign(s); wrote {DATA.relative_to(ROOT)} and {FIG.relative_to(ROOT)}.png/svg')


if __name__ == '__main__': main()
