"""Independently remeasure a declared demand campaign, including bit mapping."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import serial, spice
from serdes_flow.project import ROOT


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def publish(camp, summary, name):
    if not re.fullmatch(r'[a-z][a-z0-9_]*', name):
        raise ValueError('simple artifact name required')
    if summary.parent.parent.parent != camp:
        raise ValueError('summary belongs to another campaign')
    plan = read(camp / 'plan.json')
    folder = ROOT / 'analog/tx/input_register/tb/retime_demand'
    runner = folder / ('series_pwl.py' if str((folder / 'series_pwl.py').relative_to(ROOT)) in plan['sources'] else 'run.py')
    spec = importlib.util.spec_from_file_location('published_demand', runner)
    card = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(card)
    _, entry = card.check(camp, registered=True)
    report = read(summary)
    ids = {(r['condition'], r['point']['id']) for r in report['rows']}
    if len(ids) != len(report['rows']):
        raise ValueError('duplicate measured point')
    if any((tag, 'baseline') not in ids for tag in plan['conditions']):
        raise ValueError('baseline coverage missing')
    rows = []
    for row in report['rows']:
        tag, point = row['condition'], row['point']
        if tag not in plan['conditions'] or point not in card.POINTS:
            raise ValueError('undeclared condition/point')
        raw = card.completed(camp, tag, point['id'], entry)
        if raw is None or str(raw.relative_to(ROOT)) != row['raw'] or sha(raw) != row['raw_sha256']:
            raise ValueError('raw identity or execution failed')
        result = card.measure(camp, tag, point['id'], raw, entry)
        if json.loads(json.dumps(result, allow_nan=False)) != row['result']:
            raise ValueError('demand metrics do not reproduce')
        if point['id'] == 'baseline' and not result['baseline_matches']:
            raise ValueError('baseline calibration failed')
        w = spice.Waves(raw)
        pt = entry['points'][tag]
        seq = serial.Sequence(np.array(pt['bits'], dtype=int), pt['sequence_start_s'], 250e-12)
        outputs = {}
        for label, pos, neg in (('serializer', 'qp', 'qn'), ('pad', 'lqp', 'lqn')):
            try:
                mapping = serial.bit_mapping(w.t, w[pos] - w[neg], seq)
                mapping_ok = mapping['in_order'] is True
            except (ValueError, IndexError, KeyError) as error:
                mapping, mapping_ok = {'status': 'ungraded', 'error': str(error)}, False
            if point['id'] == 'baseline' and not mapping_ok:
                raise ValueError('baseline bit mapping failed')
            outputs[label] = dict(metrics=result['outputs'][label]['metrics'], mapping=mapping,
                                  meets_eye_and_mapping=bool(result['outputs'][label]['meets_eye_gate'] and mapping_ok))
        cycles = result['c2g_cycles']
        clock_target = bool(cycles and cycles['min_pp_v'] >= .2 and result['actual_c2g_pp_v'] <= .4)
        rows.append(dict(condition=tag, point=point, outputs=outputs,
                         c2g_pp_v=result['actual_c2g_pp_v'], c2g_cycles=cycles,
                         c2g_common_mode_mean_v=result['c2g_common_mode_mean_v'], clock_200to400_observation=clock_target,
                         local_demand_screen=bool(clock_target and all(o['meets_eye_and_mapping'] for o in outputs.values())),
                         baseline_matches=result['baseline_matches'], baseline_max_error_v=result['baseline_max_error_v'],
                         baseline_absolute_edge_error_s={k: v['baseline_absolute_edge_error_s'] for k, v in result['outputs'].items()},
                         raw=row['raw'], raw_sha256=row['raw_sha256'],
                         evidence={p.name: sha(p) for p in (raw.parent / 'tb.cir', raw.parent / 'execution.json', raw.parent / 'simulator.log')}))
    expected = {(tag, p['id']) for tag in plan['conditions'] for p in card.POINTS}
    status = 'demand_surface_measured' if ids == expected else 'baselines_calibrated_surface_incomplete'
    archive = camp / 'publication' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    archive.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, archive / 'publisher.py')
    publication = dict(status=status, campaign=str(camp.relative_to(ROOT)), summary=str(summary.relative_to(ROOT)),
                       summary_sha256=sha(summary), plan_sha256=sha(camp / 'plan.json'), boundary_sha256=plan['boundary_sha256'],
                       publisher_sha256=sha(Path(__file__).resolve()), publisher_snapshot=str((archive / 'publisher.py').relative_to(ROOT)),
                       analysis_source_sha256={str(p.relative_to(ROOT)): sha(p) for p in (runner, ROOT / 'src/serdes_flow/serial.py', ROOT / 'src/serdes_flow/spice.py')},
                       scope='Recorded full-TX final-rank ports, current driver and direct load, 256 payload bits, training-only phase and independent bit mapping. Prescribed voltage sources omit upstream impedance/feedback; no physical sizing, full-system or 45-PVT/noise/startup qualification.',
                       amplitude_policy=dict(status='internal_400mV_ceiling_under_review; no_replacement_limit_adopted',
                                             historical_screen='clock_200to400_observation and local_demand_screen retain the original 200–400 mV band; exceeding 400 alone does not establish physical failure',
                                             current_interpretation='Read outputs.meets_eye_and_mapping separately; headroom, noise and device stress require additional evidence'),
                       rows=rows)
    data = ROOT / 'docs/data' / (name + '.json')
    data.write_text(json.dumps(publication, indent=2, allow_nan=False) + '\n')
    fig, axes = plt.subplots(3, len(plan['conditions']), figsize=(max(8, 6.1 * len(plan['conditions'])), 9),
                             squeeze=False, layout='constrained')
    colors = {.9: '#965dab', 1.: '#207b85', 1.1: '#c46c32'}
    for col, tag in enumerate(plan['conditions']):
        for scale, color in colors.items():
            selected = sorted([r for r in rows if r['condition'] == tag and r['point']['differential_scale'] == scale],
                              key=lambda r: r['point']['delay_ps'])
            if not selected:
                continue
            x = [r['point']['delay_ps'] for r in selected]
            for row_index, label in enumerate(('serializer', 'pad')):
                axes[row_index, col].plot(x, [r['outputs'][label]['metrics']['transition_spread_ui'] for r in selected],
                                          'o-', color=color, label=f'differential scale {scale:g}')
            for label, marker, style in [('serializer', 'o', '-'), ('pad', 's', '--')]:
                axes[2, col].plot(x, [r['outputs'][label]['metrics']['minimum_signed_margin_v'] * 1000 for r in selected],
                                  marker=marker, ls=style, color=color, label=f'{label}, scale {scale:g}')
        for row_index, label in enumerate(('Serializer spread (UI)', 'Pad spread (UI)', 'Signed margin (mV)')):
            ax = axes[row_index, col]
            ax.set(title=tag if row_index == 0 else '', xlabel='Prescribed clock delay (ps)', ylabel=label)
            ax.axhline(.15 if row_index < 2 else 75, ls='--', color='#a84242', lw=.9)
            ax.grid(alpha=.2)
            ax.legend(fontsize=7)
        outside_clock = [r for r in rows if r['condition'] == tag and not r['clock_200to400_observation']]
        for row_index, label in enumerate(('serializer', 'pad')):
            if outside_clock:
                axes[row_index, col].scatter([r['point']['delay_ps'] for r in outside_clock],
                                             [r['outputs'][label]['metrics']['transition_spread_ui'] for r in outside_clock],
                                             marker='x', color='#bc2424', s=65, zorder=6)
        if outside_clock:
            axes[0, col].text(.02, .02, 'Red ×: outside historical 200–400 mV screen; ceiling under review',
                              transform=axes[0, col].transAxes, fontsize=8, color='#a22929')
    fig.suptitle('Final-rank demand: phase and differential scale', fontsize=13)
    fig.supxlabel('Prescribed voltage ports; eye/mapping and historical amplitude screen are separate.\nScaling also changes slew. No new amplitude limit or physical dimensions adopted.', fontsize=9)
    figure = ROOT / 'docs/figures/tx/ingress' / (name + '.png')
    fig.savefig(figure, dpi=160)
    plt.close(fig)
    index = dict(data=str(data.relative_to(ROOT)), data_sha256=sha(data), figure=str(figure.relative_to(ROOT)),
                 figure_sha256=sha(figure), campaign=publication['campaign'], summary=publication['summary'],
                 summary_sha256=publication['summary_sha256'], status=status, scope=publication['scope'])
    (ROOT / 'results/catalog' / (name + '.json')).write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps({'status': status, 'rows': len(rows), 'data': str(data.relative_to(ROOT))}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign', type=Path, required=True)
    p.add_argument('--summary', type=Path, required=True)
    p.add_argument('--name', default='tx_retime_demand_surface')
    args = p.parse_args()
    publish(args.campaign.resolve(), args.summary.resolve(), args.name)
