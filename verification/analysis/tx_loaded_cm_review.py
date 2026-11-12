"""Independent offline diagnostic for WP-TX-CM-001; does not fit or simulate."""
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import json
import shutil
import uuid

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, cml_dynamic, project, spice, stage_metrics

ROOT = project.ROOT
HERE = Path(__file__).resolve()
CAMP = ROOT / 'results/analog/tx/loaded_clock_card/20261111T171205.027336Z_8881ed25'
REVIEW = CAMP / 'review/20261111T174430.556183Z_29ee993e/summary.json'
MODEL = CAMP / 'model/20261111T174505.452906Z_84e06f0b/summary.json'
MODEL_CODE = ROOT / 'analog/tx/clock_distribution/theory/loaded_buffer_model.py'
PUBLISHER = ROOT / 'verification/plotting/tx_loaded_clock_model.py'
DOCS = [ROOT / 'docs/data/tx_loaded_clock.json', ROOT / 'docs/data/tx_loaded_clock_model.json',
        ROOT / 'results/catalog/tx_loaded_clock.json', ROOT / 'results/catalog/tx_loaded_clock_model.json',
        ROOT / 'docs/work_packages/WP-TX-CM-001-loaded-clock-review.md']


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    model = load_module('tx_cm_existing_model', MODEL_CODE)
    publisher = load_module('tx_cm_publisher', PUBLISHER)
    card = model.card
    # Publisher independently checks reviewed source identities and replays every stored metric.
    saved = publisher.collect(MODEL)
    review = card.read(REVIEW)
    if saved['review_sha256'] != card.sha(REVIEW):
        raise ValueError('review identity mismatch')
    expected = {(c, p) for c in ('fs_v1650_t85', 'ss_v1650_t-40') for p in model.TRAIN + model.HOLDOUT}
    if {(r['condition'], r['point']) for r in review['rows']} != expected or len(review['rows']) != 8:
        raise ValueError('source condition/point coverage differs')
    for row in review['rows']:
        if card.sha(ROOT / row['raw']) != row['raw_sha256']:
            raise ValueError('raw SHA mismatch: ' + row['raw'])
        if [b['mode'] for b in row['branches']] != list(card.MODES):
            raise ValueError('source branch identity differs')
    t, data = model.wave_data(review['rows'])
    start, stop = saved['evaluation_window_s']
    if not np.allclose((start, stop), (3.5e-9, 6.4e-9), rtol=0, atol=1e-21):
        raise ValueError('unexpected evaluation interval')
    model_items = {(r['condition'], r['mode']): r for r in saved['results']}
    result = dict(status='offline_diagnostic_no_adoption', window_s=[start, stop], sample_step_s=1e-12,
                  sample_bounds_s=[float(t[0]), float(t[-1])], inputs=[], paired_cm=[], predictions=[], failures=[],
                  scope='Prescribed input voltage; two MOS corners, tt resistor corner; no full-TX, pad, startup or size qualification.',
                  interpretation='CM perturbation is applied only to e2g_2; paired differences include resulting correlated differential changes. Repeated periods are not independent samples.')
    figures = {}
    for (condition, mode), item in model_items.items():
        for point in model.TRAIN + model.HOLDOUT:
            row = data[condition, mode, point]
            for j, stage in enumerate(model.STAGES):
                diff, cm = row['signals'][j]
                result['inputs'].append(dict(condition=condition, mode=mode, point=point, stage=stage,
                    common_mode_v=stage_metrics.telemetry(t, cm, start, stop),
                    differential_v=stage_metrics.telemetry(t, diff, start, stop)))
            cascade = row['signals'][0]
            for j, fit in enumerate(item['fits']):
                params = [fit['parameters'][n] for n in cml_dynamic.PARAMETERS]
                def drive(pair):
                    return cml_dynamic.drive(t, *pair, row['vdd'], params,
                        cm_ref=fit['cm_ref_v'], d2_ref=fit['d2_ref_v2'])
                one = drive(row['signals'][j]); cascade = drive(cascade)
                record = dict(condition=condition, mode=mode, point=point, stage=model.STAGES[j], methods={})
                saved_err = next(e for e in item['errors'] if e['point'] == point and e['stage'] == model.STAGES[j])
                for method, pred, source in [('one_step', one, row['signals'][j][0]),
                                              ('cascade', cascade, row['signals'][0][0])]:
                    metrics = model.waveform_metrics(t, pred, row['signals'][j+1], row['vdd'], source, start, stop)
                    if not card.collector.equal(metrics, saved_err[method]):
                        raise ValueError('stored prediction mismatch: ' + str((condition, mode, point, j, method)))
                    signed = {}
                    for polarity, name in ((1, 'rising'), (-1, 'falling')):
                        actual = clock.edges(t, row['signals'][j+1][0], polarity, start, stop)
                        predicted = clock.edges(t, pred[0], polarity, start, stop)
                        if len(actual) != len(predicted) or not len(actual) or np.any(abs(actual-predicted) >= 125e-12):
                            signed[name] = dict(paired=False, actual_count=len(actual), predicted_count=len(predicted))
                            result['failures'].append(dict(condition=condition, mode=mode, point=point, stage=model.STAGES[j], method=method, polarity=name, reason='edge association'))
                        else:
                            delta = (predicted-actual)*1e12
                            signed[name] = dict(paired=True, count=len(delta), mean_ps=float(np.mean(delta)),
                                                minimum_ps=float(np.min(delta)), maximum_ps=float(np.max(delta)),
                                                errors_ps=delta.tolist())
                    if not metrics['complete_causal_clock_check'].get('clock_qualified', False):
                        result['failures'].append(dict(condition=condition, mode=mode, point=point, stage=model.STAGES[j], method=method, reason='causal clock'))
                    record['methods'][method] = dict(metrics=metrics, signed_edges=signed)
                result['predictions'].append(record)
                if mode == 'fixed_long' and point == 'weak080_cm_m25' and j == 2:
                    figures[condition] = (row['signals'][j+1], one, cascade)
        for perturb, reference in [('cm_m25','baseline'), ('weak080_cm_m25','weak080')]:
            for j, stage in enumerate(model.STAGES):
                d, cm = data[condition, mode, perturb]['signals'][j]
                dr, cmr = data[condition, mode, reference]['signals'][j]
                change = stage_metrics.telemetry(t, cm-cmr, start, stop)
                diff_change = stage_metrics.telemetry(t, d-dr, start, stop)
                result['paired_cm'].append(dict(condition=condition, mode=mode, point=perturb, reference=reference,
                    stage=stage, cm_delta_v=change, cm_max_abs_delta_v=max(abs(change['minimum']),abs(change['maximum'])),
                    differential_delta_v=diff_change))
    if len(result['inputs']) != 72 or len(result['paired_cm']) != 36 or len(result['predictions']) != 72 or len(figures) != 2:
        raise ValueError('diagnostic coverage differs')
    paths = [HERE, REVIEW, MODEL, MODEL_CODE, PUBLISHER, CAMP/'plan.json', CAMP/'model_plan.json', *DOCS]
    paths += [ROOT/r['raw'] for r in review['rows']]
    paths += [ROOT/p for p in saved['source_sha256']]
    result['input_sha256'] = {str(p.relative_to(ROOT)): card.sha(p) for p in dict.fromkeys(paths)}
    out = ROOT/'results/analysis/tx_loaded_cm'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(HERE, out/HERE.name)
    use = (t >= start) & (t <= stop)
    for condition, series in figures.items():
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True, layout='constrained')
        for pair, label, style in zip(series, ('measured', 'one-step', 'cascade'), ('-', '--', ':')):
            for ax, y in zip(axes, pair): ax.plot(t[use]*1e9, y[use]*1000, style, label=label)
        axes[0].set_ylabel('Differential (mV)'); axes[1].set_ylabel('Common mode (mV)')
        axes[1].set_xlabel('Replay time (ns)'); axes[0].legend();
        for ax in axes: ax.grid(alpha=.2)
        fig.suptitle(condition+' fixed_long c2g, held-out weak input and −25 mV CM')
        fig.savefig(out/(condition+'.png'), dpi=170); plt.close(fig)
    (out/'summary.json').write_text(json.dumps(result, indent=2, allow_nan=False)+'\n')
    print(out)


if __name__ == '__main__':
    main()
