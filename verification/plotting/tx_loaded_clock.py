"""Independently remeasure and publish a named loaded-clock review."""
import argparse
import importlib.util
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project

ROOT = project.ROOT
HERE = Path(__file__).resolve()
REVIEW = ROOT / 'verification/analysis/loaded_clock_review.py'
spec = importlib.util.spec_from_file_location('loaded_publish_review', REVIEW)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
card = review.card
COLORS = ('#657788', '#c27236', '#20877b')


def core_delays(check):
    result = {}
    for label, events in check['propagation'].items():
        inputs = np.asarray(events['input_times_s'])
        delays = np.asarray(events['delays_s'])
        required = np.asarray(events['required_input_times_s'])
        selected = [delays[np.flatnonzero(abs(inputs - event) < 1e-18)[0]] for event in required]
        result[label] = dict(events=len(selected), mean_s=float(np.mean(selected)),
                             min_s=float(min(selected)), max_s=float(max(selected)),
                             median_abs_slew_v_per_s=events['median_abs_slew_v_per_s'])
    return result


def collect(path):
    stored = card.read(path)
    recomputed = review.review(ROOT / stored['source_summary'])
    if not card.collector.equal(stored, recomputed):
        raise ValueError('review no longer matches raw/source identity')
    camp = ROOT / stored['campaign']
    result = dict(status='measured_local_transfer_no_adoption', adopted=False,
                  campaign=stored['campaign'], review=str(path.relative_to(ROOT)), review_sha256=card.sha(path),
                  source_summary=stored['source_summary'], source_summary_sha256=stored['source_summary_sha256'],
                  plan_sha256=stored['plan_sha256'], boundary_id=card.read(camp / 'boundary_proposal.json')['id'],
                  scope=stored['scope'], rows=[],
                  source_sha256={str(p.relative_to(ROOT)): card.sha(p) for p in (HERE, REVIEW)},
                  power_scope='Only the three clock stages; excludes bias/input sources, upstream clock, serializer, driver and PLL.')
    for row in stored['rows']:
        compact = {k: row[k] for k in ('condition', 'point', 'raw', 'raw_sha256', 'baseline_fidelity')}
        compact['baseline_absolute_edge_errors_s'] = row.get('baseline_absolute_edge_errors_s')
        compact['branches'] = []
        result['rows'].append(compact)
        for b in row['branches']:
            branch = {k: b[k] for k in ('mode', 'nodes', 'clock_rail_power_w', 'clock_floor_and_events_pass')}
            branch['complete_clock_checks'] = {}
            compact['branches'].append(branch)
            for name, check in b['complete_clock_check'].items():
                branch['complete_clock_checks'][name] = {k: v for k, v in check.items() if k != 'propagation'}
                if check['edges_complete']:
                    branch['complete_clock_checks'][name]['core_propagation'] = core_delays(check)
    return result


def plot(data):
    tags = list(dict.fromkeys(r['condition'] for r in data['rows']))
    points = list(dict.fromkeys(r['point'] for r in data['rows']))
    labels = dict(baseline='original', weak080='0.8x D', cm_m25='CM -25mV', weak080_cm_m25='both')
    fig, axes = plt.subplots(2, 4, figsize=(15, 7), layout='constrained')
    for j, tag in enumerate(tags):
        rows = {r['point']: r for r in data['rows'] if r['condition'] == tag}
        for mode, color in zip(card.MODES, COLORS):
            branches = [next(b for b in rows[p]['branches'] if b['mode'] == mode) for p in points]
            amplitudes = [b['nodes']['c2g']['cycles']['min_pp_v'] * 1000 for b in branches]
            delay = []
            for b in branches:
                check = b['complete_clock_checks']['input_to_c2g']
                delay.append(np.mean([c['mean_s'] for c in check['core_propagation'].values()]) * 1e12
                             if check['edges_complete'] else np.nan)
            cm = [b['nodes']['c2g']['common_mode_v']['mean'] * 1000 for b in branches]
            power = [b['clock_rail_power_w']['mean'] * 1000 for b in branches]
            for ax, values in zip(axes[j], (amplitudes, delay, cm, power)):
                ax.plot(range(len(points)), values, 'o-', ms=5, color=color, label=mode)
        for ax in axes[j]:
            ax.set_xticks(range(len(points)), [labels[p] for p in points], rotation=15)
            ax.grid(alpha=.2)
            ax.ticklabel_format(axis='y', style='plain', useOffset=False)
        axes[j, 3].yaxis.set_major_formatter(matplotlib.ticker.FormatStrFormatter('%.6f'))
        axes[j, 0].set_ylabel(tag + '\nc2g minimum cycle pp (mV)')
        axes[j, 1].set_ylabel('input to c2g causal delay (ps)')
        axes[j, 2].set_ylabel('c2g mean common mode (mV)')
        axes[j, 3].set_ylabel('Three-clock-stage rail power (mW)')
    axes[0, 0].legend(fontsize=8)
    fig.suptitle('Actual loaded clock: ' + ('calibrated original-input baselines' if len(points) == 1
                                         else 'independent differential / CM perturbations'))
    fig.supxlabel('Xe3 / Xe4 / Xout only; fixed bias and prescribed inputs; current driver retained as load. No full TX or pad qualification.', fontsize=9)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review', type=Path, required=True)
    args = p.parse_args()
    data = collect(args.review.resolve())
    baseline = all(r['point'] == 'baseline' for r in data['rows'])
    name = 'tx_loaded_clock_baseline' if baseline else 'tx_loaded_clock'
    dest = ROOT / data['campaign'] / 'publication_sources' / card.sha(HERE)
    dest.mkdir(parents=True, exist_ok=True)
    for path in (HERE, REVIEW):
        target = dest / path.name
        if target.exists() and card.sha(target) != card.sha(path):
            raise ValueError('publication snapshot already exists with different contents')
        if not target.exists(): shutil.copyfile(path, target)
    data['publisher_snapshot'] = str((dest / HERE.name).relative_to(ROOT))
    output = ROOT / 'docs/data' / (name + '.json')
    figure = ROOT / 'docs/figures/tx/ingress' / (name + '.png')
    plot(data).savefig(figure, dpi=170, bbox_inches='tight', pad_inches=.15)
    plt.close('all')
    card.dump(output, data)
    card.dump(ROOT / 'results/catalog' / (name + '.json'),
              dict(data=str(output.relative_to(ROOT)), data_sha256=card.sha(output),
                   figure=str(figure.relative_to(ROOT)), figure_sha256=card.sha(figure),
                   review=data['review'], review_sha256=data['review_sha256'],
                   status=data['status'], scope=data['scope']))
    print(output)
    print(figure)


if __name__ == '__main__': main()
