"""Recompute direct-stage CM raws and publish the measured local responses."""
import argparse
import copy
import importlib.util
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, project, spice

ROOT = project.ROOT
HERE = Path(__file__).resolve()
RUNNER = ROOT / 'analog/tx/input_register/tb/loaded_stage_cm/run.py'
spec = importlib.util.spec_from_file_location('direct_cm_publish_card', RUNNER)
card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)
helpers = card.parent.module('direct_cm_core_helpers', ROOT / 'verification/plotting/tx_loaded_clock.py')


def compact_check(check):
    result = {k: v for k, v in check.items() if k != 'propagation'}
    if check['edges_complete']: result['core_propagation'] = helpers.core_delays(check)
    return result


def collect(summary):
    camp = summary.parents[2]; plan = card.check(camp); stored = card.read(summary)
    if stored['status'] != 'direct_CM_measured_no_adoption' or stored['plan_sha256'] != card.sha(camp / 'plan.json'):
        raise ValueError('incomplete or changed direct-CM campaign')
    expected = {(tag, p['id']) for tag in plan['conditions'] for p in card.POINTS}
    if {(r['condition'], r['point']) for r in stored['rows']} != expected or len(stored['rows']) != len(expected):
        raise ValueError('missing/duplicate direct CM cases')
    result = dict(status='raw_recomputed_direct_CM_no_adoption', adopted=False, rows=[], failures=[],
                  campaign=str(camp.relative_to(ROOT)), summary=str(summary.relative_to(ROOT)), summary_sha256=card.sha(summary),
                  plan_sha256=stored['plan_sha256'], boundary_id=card.read(camp / 'boundary_proposal.json')['id'],
                  scope='FS hot / SS cold, three R implementations, ideal series DC CM experiment, actual three clock stages and downstream driver load; RC tt and prescribed external inputs.',
                  power_scope='VDD rail of three clock stages only; ideal CM injection sources and other supplied blocks excluded.',
                  model_scope='Development/training data only; no new model fit or independent model holdout.',
                  sources={str(p.relative_to(ROOT)): card.sha(p) for p in (HERE, RUNNER, Path(helpers.__file__))})
    raws = {}
    for row in stored['rows']:
        tag, name = row['condition'], row['point']; raw = card.completed(camp, tag, name, plan)
        if raw is None or str(raw.relative_to(ROOT)) != row['raw']: raise ValueError('missing/wrong completed waveform')
        for path, expected_sha in row['evidence'].items():
            if card.sha(ROOT / path) != expected_sha: raise ValueError('execution evidence changed')
        actual = card.measure(camp, tag, name, raw, plan)
        if not card.parent.collector.equal(actual, row['result']): raise ValueError('metrics differ from raw')
        if name == 'baseline' and not actual['baseline_fidelity']['passed']: raise ValueError('baseline uncalibrated')
        entry = dict(condition=tag, point=name, raw=row['raw'], evidence=row['evidence'], result=copy.deepcopy(actual))
        for b in entry['result']['branches']:
            b['input_to_c2g'] = compact_check(b['input_to_c2g'])
            for s in b['stages']: s['clock_check'] = compact_check(s['clock_check'])
            if not b['clock_floor_and_events_pass']:
                result['failures'].append(dict(condition=tag, point=name, mode=b['mode'], reason='clock floor or complete causal events'))
        result['rows'].append(entry); raws[tag, name] = raw
    start, stop = plan['evaluation_window_s']
    for tag in plan['conditions']:
        base_row = next(r for r in result['rows'] if r['condition'] == tag and r['point'] == 'baseline')
        base = spice.Waves(raws[tag, 'baseline'])
        for row in (r for r in result['rows'] if r['condition'] == tag):
            w = spice.Waves(raws[tag, row['point']])
            for i, (b, ref) in enumerate(zip(row['result']['branches'], base_row['result']['branches']), 1):
                b['input_CM_mean_delta_v'] = {s['stage']: s['input_common_mode_v']['mean'] - r['input_common_mode_v']['mean']
                                            for s, r in zip(b['stages'], ref['stages'])}
                b['c2g_min_cycle_pp_delta_v'] = (b['input_to_c2g'].get('output_cycles', {}).get('min_pp_v', np.nan)
                                               - ref['input_to_c2g']['output_cycles']['min_pp_v'])
                changes = {}
                for polarity, label in ((1, 'rising'), (-1, 'falling')):
                    a = clock.edges(base.t, base[f'sp{i}'] - base[f'sn{i}'], polarity, start, stop)
                    z = clock.edges(w.t, w[f'sp{i}'] - w[f'sn{i}'], polarity, start, stop)
                    if len(a) != len(z) or not len(a) or np.any(abs(a - z) >= 125e-12):
                        changes[label] = dict(paired=False, actual_count=len(z), baseline_count=len(a))
                        result['failures'].append(dict(condition=tag, point=row['point'], mode=b['mode'], reason='absolute output association', polarity=label))
                    else:
                        changes[label] = dict(paired=True, count=len(a), mean_s=float(np.mean(z - a)),
                                              min_s=float(min(z - a)), max_s=float(max(z - a)))
                b['absolute_c2g_edge_change_s'] = changes
                if not np.isfinite(b['c2g_min_cycle_pp_delta_v']): b['c2g_min_cycle_pp_delta_v'] = None
    result['measured_branches'] = sum(len(r['result']['branches']) for r in result['rows'])
    result['clock_pass_branches'] = sum(b['clock_floor_and_events_pass'] for r in result['rows'] for b in r['result']['branches'])
    return result


def plot(data):
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), layout='constrained')
    points = ('baseline', 'e4_m25', 'out_m25')
    for j, tag in enumerate(('fs_v1650_t85', 'ss_v1650_t-40')):
        for mode, color in zip(card.parent.MODES, ('#657788', '#c27236', '#20877b')):
            branches = [next(b for r in data['rows'] if (r['condition'], r['point']) == (tag, point)
                             for b in r['result']['branches'] if b['mode'] == mode) for point in points]
            for stage, marker, style in (('e4', 'o', '-'), ('out', 'D', ':')):
                axes[j, 0].plot(range(3), [b['input_CM_mean_delta_v'][stage] * 1000 for b in branches],
                                marker=marker, ls=style, color=color, label=mode + ': ' + stage)
            axes[j, 1].plot(range(3), [np.nan if b['c2g_min_cycle_pp_delta_v'] is None else b['c2g_min_cycle_pp_delta_v'] * 1000 for b in branches], 'o-', color=color)
            y = [np.mean([e['mean_s'] for e in b['absolute_c2g_edge_change_s'].values()]) * 1e12
                 if all(e['paired'] for e in b['absolute_c2g_edge_change_s'].values()) else np.nan for b in branches]
            axes[j, 2].plot(range(3), y, 'o-', color=color)
        for ax in axes[j]:
            ax.set_xticks(range(3), ('original', 'Xe4 -25mV', 'Xout -25mV'), rotation=10)
            ax.grid(alpha=.2); ax.ticklabel_format(axis='y', style='plain', useOffset=False)
        axes[j, 0].set_ylabel(tag + '\nActual input CM change (mV)')
        axes[j, 1].set_ylabel('c2g minimum cycle pp change (mV)')
        axes[j, 2].set_ylabel('Mean absolute c2g edge change (ps)')
    axes[0, 0].legend(fontsize=7)
    fig.suptitle(f'Direct internal CM perturbations: {data["clock_pass_branches"]}/{data["measured_branches"]} local clock checks; {len(data["failures"])} recorded failures')
    fig.supxlabel('Ideal equal series sources retain the preceding gate loading. Experimental DC shifts; no physical shifter, full TX or PPA qualification.', fontsize=9)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--summary', type=Path, required=True); a = p.parse_args()
    summary = a.summary.resolve(); data = collect(summary)
    dest = summary.parent / 'publication_sources' / card.sha(HERE); dest.mkdir(parents=True, exist_ok=True)
    if not (dest / HERE.name).exists(): shutil.copyfile(HERE, dest / HERE.name)
    output = ROOT / 'docs/data/tx_direct_stage_cm.json'; figure = ROOT / 'docs/figures/tx/ingress/tx_direct_stage_cm.png'
    plot(data).savefig(figure, dpi=170, bbox_inches='tight', pad_inches=.15); plt.close('all')
    card.dump(output, data)
    card.dump(ROOT / 'results/catalog/tx_direct_stage_cm.json',
              dict(data=str(output.relative_to(ROOT)), data_sha256=card.sha(output), figure=str(figure.relative_to(ROOT)), figure_sha256=card.sha(figure),
                   summary=data['summary'], summary_sha256=data['summary_sha256'], failures=data['failures'], scope=data['scope']))
    print(output)
    print(data['measured_branches'], data['clock_pass_branches'], 'failures', data['failures'])


if __name__ == '__main__': main()
