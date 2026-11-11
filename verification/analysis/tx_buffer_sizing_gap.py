"""Audit the local-to-full TX sizing boundary using completed waveforms only.

No parameter selection or simulation. Matched serializer/pad transitions expose
the downstream delay variation which an amplitude-only clock model omits.
"""
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, serial, spice, waves
from serdes_flow.project import ROOT

FULL = ROOT / 'results/analog/tx/full_pvt45/20261110T173418Z'
LOCAL = ROOT / 'docs/data/tx_buffer_taper.json'
COLLECTOR = ROOT / 'verification/plotting/tx_parallel_serializer.py'
MATRIX = ROOT / 'analog/tx/input_register/tb/final_clock_chain/buffer_matrix_card.py'
PROFILE = [[24, 14.4, 320]] + [[24, 15.6, 320]] * 4


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    return json.loads(path.read_text())


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def verify_local(card):
    data = read(LOCAL)
    index = read(ROOT / 'results/catalog/tx_buffer_taper.json')
    if index['data_sha256'] != sha(LOCAL):
        raise ValueError('local publication changed')
    camp, summary = ROOT / data['campaign'], ROOT / data['summary']
    if sha(summary) != data['summary_sha256']:
        raise ValueError('local summary changed')
    card.check(camp, registered=True)
    points = read(card.PARENT / 'boundary_proposal.json')['points']
    profile = card.validate(read(camp / 'profile.json'))
    for row in data['results']:
        tag = row['condition']
        raw = card.old.completed(camp, tag)
        if raw is None or sha(raw) != row['raw_sha256']:
            raise ValueError('local raw/execution/deck failed')
        for name, expected in data['evidence'][tag].items():
            path = raw if name == raw.name else raw.parent / name
            if sha(path) != expected:
                raise ValueError(f'local evidence changed: {name}')
        measured = card.cascade.measure(camp, tag, raw, points[tag])
        for branch, params in zip(measured['branches'], profile['branches']):
            branch['branch'] = params['label']
            branch['actual_parameters'] = params
        measured = json.loads(json.dumps(measured, default=card.old.json_default))
        if measured != row['result'] or not measured['baseline_matches']:
            raise ValueError('local remeasurement disagrees')
    return data, points


def inspect_case(camp, collector, local, points):
    validated = collector.collect(camp)
    if validated['clock_stage_profile'] != PROFILE:
        raise ValueError('full/profile mismatch')
    for key in ('input_boundary_ok', 'halfword_hold_ok', 'behavioral_tags_align'):
        if validated[key] is not True:
            raise ValueError(f'full boundary failed: {key}')
    if validated['counter']['counting'] is not True:
        raise ValueError('full counter failed')
    plan, summary = read(camp / 'plan.json'), read(camp / 'summary.json')
    bits = np.array([(r['word'] >> bit) & 1 for r in summary['captures']
                     if r['payload_valid'] for bit in range(16)])
    seq = serial.Sequence(bits, validated['sequence_start_s'], 250e-12)
    w = spice.Waves(ROOT / validated['waveform'])
    outputs, detail = {}, {}
    for label, pos, neg in (('serializer', 'qp', 'qn'), ('pad', 'lqp', 'lqn')):
        metrics, d = serial.check(w.t, w[pos] - w[neg], seq, plan['payload_bits'])
        if not collector.equal(metrics, validated['outputs'][label]['check']):
            raise ValueError('full remeasurement disagrees')
        outputs[label] = {'metrics': metrics, 'meets_eye_gate': serial.meets_draft(metrics)}
        detail[label] = d
    # Reconstruct absolute crossing times. Subtracting residuals alone would
    # incorrectly remove the separate training delay of the pad.
    transitions = {}
    for label, d in detail.items():
        delay = outputs[label]['metrics']['training_delay_ui']
        transitions[label] = {int(bit): seq.start_s + (bit + delay + residual) * seq.ui_s
                              for bit, residual in zip(d['payload_transition_bits'], d['edge_residual_ui'])}
    if transitions['serializer'].keys() != transitions['pad'].keys():
        raise ValueError('serializer/pad transitions do not correspond')
    transport = [{'bit': bit, 'slot': bit % 16, 'direction': int(2 * bits[bit] - 1),
                  'delay_ps': (transitions['pad'][bit] - t) * 1e12}
                 for bit, t in transitions['serializer'].items()]
    if not transport:
        raise ValueError('no transport observations')
    delay = [row['delay_ps'] for row in transport]
    lo = seq.start_s + 64 * seq.ui_s
    hi = seq.start_s + (64 + plan['payload_bits']) * seq.ui_s
    mask = (w.t >= lo) & (w.t <= hi)
    nodes = {}
    pairs = ([('iso', 'xclocks.i2gp', 'xclocks.i2gn')]
             + [(f'e{i}', f'xclocks.e2g_{i}p', f'xclocks.e2g_{i}n') for i in range(5)]
             + [('c2g', 'c2gp', 'c2gn')])
    for label, pos, neg in pairs:
        p, n = w[pos], w[neg]
        nodes[label] = {'differential_pp_v': float(np.ptp((p - n)[mask])),
                        'common_mode_mean_v': waves.time_average(((p + n) / 2)[mask], w.t[mask]),
                        'cycles': clock.cycle_amplitudes(w.t, p - n, lo, hi)}
    power = waves.time_average((-w['vdd'] * w['i(vdd)'])[mask], w.t[mask])
    comparison = None
    if plan['condition'] in points:
        tag = plan['condition']
        if bits.tolist() != points[tag]['bits']:
            raise ValueError('full/local bit sequences differ; cannot compare identical window')
        branch = next(b for r in local['results'] if r['condition'] == tag
                      for b in r['result']['branches'] if b['branch'] == 'first14p4')
        if branch['actual_parameters']['stages'] != PROFILE:
            raise ValueError('local profile differs')
        eight, _ = serial.fixed_phase_window(
            w.t, w['qp'] - w['qn'], seq,
            delay_ui=outputs['serializer']['metrics']['training_delay_ui'], first_bit=296, end_bit=304)
        comparison = {'same_bits': bits[296:304].tolist(), 'local': branch['metrics'],
                      'full_same_eight_bits': eight, 'local_nodes': branch['nodes'],
                      'local_scope': 'fixed recorded upstream data/clock/bias, earlier driver and RLC16 load',
                      'full_scope': 'real upstream tree/bias, pre120 WT60 out192 driver; new training delay',
                      'causal_attribution': 'not isolated: source/load/phase differ together'}
    return {'condition': plan['condition'], 'campaign': validated['campaign'], 'hashes': validated['hashes'],
            'clock_stage_profile': PROFILE, 'outputs': outputs, 'clock_nodes': nodes,
            'serializer_to_pad': {'observations': transport, 'minimum_ps': min(delay), 'maximum_ps': max(delay),
                                  'range_ps': max(delay) - min(delay), 'range_ui': (max(delay) - min(delay)) / 250,
                                  'definition': 'Same-bit output zero-crossing delay, no fitted propagation offset; ranges do not add as independent jitter budgets.'},
            'same_window_comparison': comparison, 'vdd_source_mean_power_w': power,
            'power_scope': 'Vdd-source power supplied to clock distribution, capture/tree/driver and bias. Excludes independent ideal clock/data/control/termination sources; not complete TX or isolated buffer power.'}


def main():
    collector = load_module('tx_gap_collector', COLLECTOR)
    card = load_module('tx_gap_matrix', MATRIX)
    local, points = verify_local(card)
    plan = read(FULL / 'plan.json')
    full_summary = read(FULL / 'summary.json')
    if plan['conditions'] != ['fs_v1650_t85', 'ss_v1650_t-40'] or plan['clock_stage_profile'] != PROFILE:
        raise ValueError('unexpected full campaign')
    if full_summary['plan'] != plan or set(full_summary['rows']) != set(plan['conditions']):
        raise ValueError('full summary/plan identity differs')
    cases = []
    for tag in plan['conditions']:
        path = FULL / 'state' / f'{tag}.json'
        state = read(path)
        if state['status'] != 'done' or state['condition'] != tag or state != full_summary['rows'][tag]:
            raise ValueError('full campaign incomplete or state identity differs')
        case = inspect_case(ROOT / state['run'], collector, local, points)
        if case['condition'] != tag:
            raise ValueError('state points to another condition')
        case['state_sha256'] = sha(path)
        cases.append(case)
    sources = [Path(__file__).resolve(), COLLECTOR, MATRIX,
               ROOT / 'src/serdes_flow/serial.py', ROOT / 'src/serdes_flow/clock.py',
               ROOT / 'src/serdes_flow/spice.py', ROOT / 'src/serdes_flow/waves.py',
               ROOT / 'src/serdes_flow/clock_profiles.py']
    report = {'status': 'full_FS_eye_failure_not_adopted',
              'scope': 'Completed ideal-2GHz TX stress points and recorded-PWL local cut only; no 45-point, native PLL, startup, mismatch or noise qualification.',
              'analysis_sources': {str(p.relative_to(ROOT)): sha(p) for p in sources},
              'inputs': {str(p.relative_to(ROOT)): sha(p) for p in (LOCAL, FULL / 'plan.json', FULL / 'summary.json')},
              'cases': cases,
              'next_selection_gate': 'No new sizing candidate until the model includes measured clock slew/phase and data setup/hold, and a separately validated serializer-to-pad response. Missing model outputs cannot be treated as zero penalty.'}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out = ROOT / 'results/analog/tx/sizing_gap' / stamp
    out.mkdir(parents=True, exist_ok=False)
    for source in sources:
        dest = out / 'execution' / source.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
    (out / 'analysis.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    report['analysis_archive'] = str(out.relative_to(ROOT))
    data = ROOT / 'docs/data/tx_buffer_sizing_gap.json'
    data.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7), layout='constrained')
    fs = cases[0]
    stages = ('iso', 'e0', 'e1', 'e2', 'e3', 'e4', 'c2g')
    for label, nodes in [('Recorded-PWL local cut', fs['same_window_comparison']['local_nodes']),
                         ('Full FS payload', fs['clock_nodes']),
                         ('Full SS cold payload', cases[1]['clock_nodes'])]:
        axes[0].plot(stages, [nodes[s]['differential_pp_v'] * 1000 for s in stages], 'o-', label=label)
    axes[0].axhline(400, ls='--', color='#9c3d3d')
    axes[0].axhline(200, ls=':', color='#668666')
    axes[0].set(title='Clock amplitude: local FS vs full FS / SS', ylabel='Differential pp (mV)')
    axes[0].legend(fontsize=8)
    for case in cases:
        rows = case['serializer_to_pad']['observations']
        axes[1].scatter([r['bit'] - 64 for r in rows], [r['delay_ps'] for r in rows], s=9,
                        alpha=.7, label=case['condition'])
    axes[1].set(title='Serializer to pad: matched-bit propagation', xlabel='Payload transition bit', ylabel='Propagation delay (ps)')
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    fig.suptitle('Amplitude-only planning leaves timing constraints unresolved', fontsize=13)
    figure = ROOT / 'docs/figures/tx/ingress/tx_buffer_sizing_gap.png'
    fig.savefig(figure, dpi=170)
    plt.close(fig)
    catalog = {'data': str(data.relative_to(ROOT)), 'data_sha256': sha(data),
               'figure': str(figure.relative_to(ROOT)), 'figure_sha256': sha(figure),
               'analysis_archive': report['analysis_archive'], 'scope': report['scope'], 'status': report['status']}
    (ROOT / 'results/catalog/tx_buffer_sizing_gap.json').write_text(json.dumps(catalog, indent=2) + '\n')
    print(json.dumps({'archive': report['analysis_archive'],
                      'cases': [{'condition': c['condition'], 'outputs': c['outputs'],
                                 'same_window_comparison': c['same_window_comparison'],
                                 'transport_range_ps': c['serializer_to_pad']['range_ps'],
                                 'vdd_source_power_mw': c['vdd_source_mean_power_w'] * 1000}
                                for c in cases]}, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
