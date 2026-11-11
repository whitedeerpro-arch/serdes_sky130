"""Replay all stored loaded-clock model predictions and publish holdout errors."""
import argparse
import importlib.util
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import cml_dynamic, project

ROOT = project.ROOT
HERE = Path(__file__).resolve()
MODEL = ROOT / 'analog/tx/clock_distribution/theory/loaded_buffer_model.py'
spec = importlib.util.spec_from_file_location('loaded_model_publish', MODEL)
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
card = model.card


def collect(summary):
    data = card.read(summary)
    if data['status'] != 'exploratory_fit_and_combined_holdout_measured_no_adoption':
        raise ValueError('incomplete model output')
    for rel, expected in data['source_sha256'].items():
        if card.sha(ROOT / rel) != expected:
            raise ValueError('model source changed: ' + rel)
    review_path = ROOT / data['review']
    if card.sha(review_path) != data['review_sha256']:
        raise ValueError('model review changed')
    reviewed, camp = model.verified(review_path)
    if card.sha(camp / 'model_plan.json') != data['model_plan_sha256']:
        raise ValueError('model plan changed')
    t, raw = model.wave_data(reviewed['rows'])
    start, stop = data['evaluation_window_s']
    expected_keys = {(tag, mode) for tag in card.read(camp / 'plan.json')['conditions'] for mode in card.MODES}
    if {(r['condition'], r['mode']) for r in data['results']} != expected_keys or len(data['results']) != len(expected_keys):
        raise ValueError('model condition/load coverage differs')
    for item in data['results']:
        errors = []
        if [f['stage'] for f in item['fits']] != list(model.STAGES):
            raise ValueError('model stage order differs')
        for point in model.TRAIN + model.HOLDOUT:
            row = raw[item['condition'], item['mode'], point]
            cascade = row['signals'][0]
            for j, fit in enumerate(item['fits']):
                p = [fit['parameters'][name] for name in cml_dynamic.PARAMETERS]
                def drive(pair):
                    return cml_dynamic.drive(t, *pair, row['vdd'], p, cm_ref=fit['cm_ref_v'], d2_ref=fit['d2_ref_v2'])
                one = drive(row['signals'][j]); cascade = drive(cascade)
                errors.append(dict(point=point, split='train' if point in model.TRAIN else 'holdout', stage=model.STAGES[j],
                    one_step=model.waveform_metrics(t, one, row['signals'][j + 1], row['vdd'], row['signals'][j][0], start, stop),
                    cascade=model.waveform_metrics(t, cascade, row['signals'][j + 1], row['vdd'], row['signals'][0][0], start, stop)))
        if not card.collector.equal(errors, item['errors']):
            raise ValueError('stored predictions/metrics do not reproduce from raw')
    return data


def plot(data):
    tags = list(dict.fromkeys(r['condition'] for r in data['results']))
    fig, axes = plt.subplots(2, 3, figsize=(12.5, 7.1), layout='constrained')
    fields = (('differential_max_error_mv', 'Maximum differential error (mV)'),
              ('common_mode_max_error_mv', 'Maximum common-mode error (mV)'),
              ('crossing_error_max_abs_ps', 'Maximum absolute crossing error (ps)'))
    for row, tag in enumerate(tags):
        crossing_failures, clock_failures = 0, 0
        for mode, color in zip(card.MODES, ('#657788', '#c27236', '#20877b')):
            item = next(i for i in data['results'] if (i['condition'], i['mode']) == (tag, mode))
            hold = [e for e in item['errors'] if e['split'] == 'holdout']
            if [e['stage'] for e in hold] != list(model.STAGES):
                raise ValueError('held-out stage coverage differs')
            for method, marker, style in (('one_step', 'o', ':'), ('cascade', 'D', '-')):
                crossing_failures += sum(e[method]['crossing_error_max_abs_ps'] is None for e in hold)
                clock_failures += sum(not e[method]['complete_causal_clock_check']['clock_qualified'] for e in hold)
                for ax, (field, ylabel) in zip(axes[row], fields):
                    y = [e[method][field] if e[method][field] is not None else np.nan for e in hold]
                    ax.plot(range(3), y, color=color, marker=marker, ls=style, ms=5,
                            label=mode + ': ' + method)
                    ax.set_ylabel(ylabel)
                    if field == 'crossing_error_max_abs_ps':
                        for i, value in enumerate(y):
                            if not np.isfinite(value):
                                ax.annotate('ASSOCIATION FAIL', (i, 0), color='#af2525', fontsize=7, rotation=90)
        axes[row, 0].set_title(tag)
        axes[row, 2].set_title(f'Association failures: {crossing_failures}; clock gate failures: {clock_failures}', fontsize=9)
        for ax in axes[row]:
            ax.set_xticks(range(3), model.STAGES)
            ax.set_ylim(bottom=0)
            ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=7)
    fig.suptitle('Loaded CML model: complete held-out 0.8x differential / -25 mV CM point')
    fig.supxlabel('Training: original, 0.8x differential, -25 mV CM. Cascades start only at replay input. Empirical discrepancy; no size adoption.', fontsize=9)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--summary', type=Path, required=True)
    args = p.parse_args()
    summary = args.summary.resolve()
    data = collect(summary)
    dest = summary.parent / 'publication_sources' / card.sha(HERE)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / HERE.name
    if target.exists() and card.sha(target) != card.sha(HERE):
        raise ValueError('publisher snapshot differs')
    if not target.exists(): shutil.copyfile(HERE, target)
    output = ROOT / 'docs/data/tx_loaded_clock_model.json'
    figure = ROOT / 'docs/figures/tx/ingress/tx_loaded_clock_model.png'
    plot(data).savefig(figure, dpi=170, bbox_inches='tight', pad_inches=.15)
    plt.close('all')
    data['publication'] = dict(summary=str(summary.relative_to(ROOT)), summary_sha256=card.sha(summary),
                               publisher=str(HERE.relative_to(ROOT)), publisher_sha256=card.sha(HERE),
                               publisher_snapshot=str(target.relative_to(ROOT)))
    card.dump(output, data)
    fields = ('differential_max_error_mv', 'common_mode_max_error_mv', 'crossing_error_max_abs_ps')
    maxima = {}
    for tag in dict.fromkeys(r['condition'] for r in data['results']):
        held = [e for r in data['results'] if r['condition'] == tag for e in r['errors'] if e['split'] == 'holdout']
        maxima[tag] = {}
        for method in ('one_step', 'cascade'):
            missing = sum(e[method]['crossing_error_max_abs_ps'] is None for e in held)
            maxima[tag][method] = {field: max((e[method][field] for e in held if e[method][field] is not None), default=None)
                                   for field in fields}
            # A maximum over only the surviving associations is not an error
            # bound covering the full holdout. Keep failures visible in JSON.
            if missing:
                maxima[tag][method]['associated_only_max_crossing_error_ps'] = maxima[tag][method]['crossing_error_max_abs_ps']
                maxima[tag][method]['crossing_error_max_abs_ps'] = None
            maxima[tag][method]['missing_crossing_associations'] = missing
            maxima[tag][method]['clock_floor_or_complete_event_failures'] = sum(
                not e[method]['complete_causal_clock_check']['clock_qualified'] for e in held)
            maxima[tag][method]['rail_excursion_cases'] = sum(e[method]['predicted_rail_excursion_v'] > 1e-9 for e in held)
        fits = [f for r in data['results'] if r['condition'] == tag for f in r['fits']]
        maxima[tag]['optimizer_failed_fits'] = sum(not f['optimizer_success'] for f in fits)
        maxima[tag]['parameter_bound_active_fits'] = sum(bool(f['bound_active_parameters']) for f in fits)
    card.dump(ROOT / 'results/catalog/tx_loaded_clock_model.json',
              dict(data=str(output.relative_to(ROOT)), data_sha256=card.sha(output),
                   figure=str(figure.relative_to(ROOT)), figure_sha256=card.sha(figure),
                   summary=data['publication']['summary'], summary_sha256=card.sha(summary),
                   holdout_maximum_errors=maxima, status=data['status'], scope=data['model_plan']['scope']))
    print(output)
    print(figure)
    print(maxima)


if __name__ == '__main__': main()
