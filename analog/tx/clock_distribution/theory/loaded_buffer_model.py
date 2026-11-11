"""Fit the predeclared loaded-clock model; hold out the combined perturbation.

Offline only. Each condition, load implementation and stage has its own fit.
The repeated cycles are not independent statistical samples.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import platform
import shutil
import sys
import uuid

import numpy as np
import scipy
from scipy.optimize import least_squares

from serdes_flow import clock, clock_transfer, cml_dynamic, project, spice, stage_metrics

ROOT = project.ROOT
HERE = Path(__file__).resolve()
REVIEW = ROOT / 'verification/analysis/loaded_clock_review.py'
spec = importlib.util.spec_from_file_location('loaded_model_review', REVIEW)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)
card = review.card
STAGES = ('e3', 'e4', 'c2g')
TRAIN = ('baseline', 'weak080', 'cm_m25')
HOLDOUT = ('weak080_cm_m25',)


def verified(review_path):
    stored = card.read(review_path)
    if stored['status'] != 'strict_review_complete':
        raise ValueError('strict clock review missing')
    summary = ROOT / stored['source_summary']
    if card.read(summary)['status'] != 'loaded_transfer_DOE_measured_no_adoption':
        raise ValueError('model needs the full predeclared DOE')
    actual = review.review(summary)
    if not card.collector.equal(stored, actual):
        raise ValueError('review/raw/source identity changed')
    camp = ROOT / stored['campaign']
    plan = card.read(camp / 'model_plan.json')
    if (plan['training_points'] != list(TRAIN) or plan['holdout_points'] != list(HOLDOUT)
            or plan['parameters'] != list(cml_dynamic.PARAMETERS)
            or plan['bounds_low'] != cml_dynamic.LOWER.tolist()
            or plan['bounds_high'] != cml_dynamic.UPPER.tolist()):
        raise ValueError('model plan differs')
    return stored, camp


def wave_data(rows):
    result = {}
    # All models get the same fixed 1 ps grid and available preceding history.
    # Integer construction and one guard sample avoid a last time just below
    # the exact 6.4 ns measurement boundary after floating-point accumulation.
    t = np.arange(101, 6402, dtype=float) * 1e-12
    for row in rows:
        w = spice.Waves(ROOT / row['raw'])
        if w.t[0] > t[0] or w.t[-1] < t[-1]:
            raise ValueError('incomplete fit/resettling history')
        signal = lambda p, n: (np.interp(t, w.t, w[p] - w[n]),
                                np.interp(t, w.t, (w[p] + w[n]) / 2))
        supply = np.interp(t, w.t, w['vdd'])
        for i, b in enumerate(row['branches'], 1):
            signals = [signal('ip', 'inn')]
            signals += [signal(f'{p}{i}', f'{n}{i}') for p, n in
                        (('e3p', 'e3n'), ('e4p', 'e4n'), ('sp', 'sn'))]
            result[row['condition'], b['mode'], row['point']] = dict(signals=signals, vdd=supply)
    return t, result


def waveform_metrics(t, predicted, actual, supply, source, start, stop):
    use = (t >= start) & (t <= stop)
    pd, pc = predicted; ad, ac = actual
    d_error, cm_error = pd[use] - ad[use], pc[use] - ac[use]
    out = dict(differential_rmse_mv=float(np.sqrt(np.mean(d_error ** 2)) * 1000),
               differential_max_error_mv=float(np.max(abs(d_error)) * 1000),
               common_mode_rmse_mv=float(np.sqrt(np.mean(cm_error ** 2)) * 1000),
               common_mode_max_error_mv=float(np.max(abs(cm_error)) * 1000),
               differential_pp_error_mv=float((np.ptp(pd[use]) - np.ptp(ad[use])) * 1000),
               actual_cycles=clock.cycle_amplitudes(t, ad, start, stop),
               predicted_cycles=clock.cycle_amplitudes(t, pd, start, stop),
               predicted_rail_excursion_v=float(max(0., np.max(pc[use] + abs(pd[use]) / 2 - supply[use]),
                                                     np.max(-pc[use] + abs(pd[use]) / 2))))
    errors, slopes, counts = [], [], []
    association_error = None
    for polarity in (1, -1):
        a = clock.edges(t, ad, polarity, start, stop)
        b = clock.edges(t, pd, polarity, start, stop)
        counts.append([len(a), len(b)])
        if len(a) != len(b) or not len(a):
            association_error = 'actual/predicted output event count differs'; continue
        if np.any(abs(a - b) >= 125e-12):
            association_error = 'output events cannot be associated within 125 ps'; continue
        errors.extend((b - a) * 1e12)
        sa = (np.interp(a + 5e-12, t, ad) - np.interp(a - 5e-12, t, ad)) / .01
        sb = (np.interp(b + 5e-12, t, pd) - np.interp(b - 5e-12, t, pd)) / .01
        slopes.extend(abs(sb) - abs(sa))
    out.update(output_event_counts_actual_predicted=counts,
               output_association_error=association_error,
               crossing_error_max_abs_ps=None if association_error else float(np.max(abs(np.asarray(errors)))),
               slew_error_max_abs_v_per_ns=None if association_error else float(np.max(abs(np.asarray(slopes)))))
    try:
        check = clock_transfer.analyze(t, source, pd, start, stop - 200e-12, 200e-12, minimum_pp_v=.15)
        for events in check['propagation'].values():
            for name in ('input_times_s', 'output_times_s', 'delays_s', 'required_input_times_s'):
                events.pop(name)
        out['complete_causal_clock_check'] = check
    except ValueError as exc:
        out['complete_causal_clock_check'] = dict(edges_complete=False, clock_qualified=False, error=str(exc))
    return out


def fit_stage(t, data, stage, evaluation):
    base = data['baseline']
    cm_ref = float(np.mean(base['signals'][stage][1][evaluation]))
    d2_ref = float(np.mean(base['signals'][stage][0][evaluation] ** 2))
    def drive(inputs, vdd, p):
        return cml_dynamic.drive(t, *inputs, vdd, p, cm_ref=cm_ref, d2_ref=d2_ref)
    def residual(p):
        errors = []
        for name in TRAIN:
            row = data[name]
            predicted = drive(row['signals'][stage], row['vdd'], p)
            actual = row['signals'][stage + 1]
            errors.append((predicted[0][evaluation] - actual[0][evaluation]) / .010)
            errors.append((predicted[1][evaluation] - actual[1][evaluation]) / .005)
        return np.concatenate(errors)
    # The starting point uses baseline only. Fixed training-only multistart
    # avoids selecting an optimizer or initial guess using the held-out point.
    a0 = float(np.clip(2 * np.mean((base['vdd'] - base['signals'][stage + 1][1])[evaluation]), .06, .55))
    fits = [least_squares(residual, [a0, 1.5, tau, delay, 0., 0., 0.],
                          bounds=(cml_dynamic.LOWER, cml_dynamic.UPPER), x_scale='jac', max_nfev=250)
            for tau, delay in ((15., 5.), (35., 1.))]
    fit = min(fits, key=lambda r: r.cost)
    singular = np.linalg.svd(fit.jac * (cml_dynamic.UPPER - cml_dynamic.LOWER), compute_uv=False)
    normalized = (fit.x - cml_dynamic.LOWER) / (cml_dynamic.UPPER - cml_dynamic.LOWER)
    result = dict(parameters=dict(zip(cml_dynamic.PARAMETERS, map(float, fit.x))),
                  cm_ref_v=cm_ref, d2_ref_v2=d2_ref, optimizer_success=bool(fit.success),
                  optimizer_message=fit.message, weighted_rms_residual=float(np.sqrt(np.mean(residual(fit.x) ** 2))),
                  optimizer_nfev=int(fit.nfev),
                  multistart_training_costs=[float(r.cost) for r in fits],
                  scaled_distance_to_parameter_bounds=normalized.tolist(),
                  bound_active_parameters=[n for n, v in zip(cml_dynamic.PARAMETERS, normalized) if min(v, 1 - v) < 1e-4],
                  jacobian_coordinates='Parameters scaled by their declared ranges; residuals scaled by 10mV differential / 5mV CM.',
                  jacobian_singular_values=singular.tolist(),
                  jacobian_condition=None if singular[-1] == 0 else float(singular[0] / singular[-1]))
    return result, drive


def calculate(review_path):
    stored, camp = verified(review_path)
    t, all_data = wave_data(stored['rows'])
    start, stop = card.read(camp / 'plan.json')['evaluation_window_s']
    evaluation = (t >= start) & (t <= stop)
    result = dict(status='exploratory_fit_and_combined_holdout_measured_no_adoption',
                  campaign=str(camp.relative_to(ROOT)), review=str(review_path.relative_to(ROOT)),
                  review_sha256=card.sha(review_path), model_plan_sha256=card.sha(camp / 'model_plan.json'),
                  model_plan=card.read(camp / 'model_plan.json'),
                  training=list(TRAIN), holdout=list(HOLDOUT), evaluation_window_s=[start, stop],
                  sample_step_s=1e-12, sample_start_s=float(t[0]),
                  predicted_observables=['output differential voltage', 'output common-mode voltage', 'absolute crossings and slew'],
                  circuit_only_observables=dict(
                      source_review=str(review_path.relative_to(ROOT)),
                      fields=['tail current', 'tail/input-pair VDS-VDSAT', 'three-clock-stage rail power'],
                      scope='Measured from transistor simulations in the source review; not predicted by this surrogate.'),
                  initial_guesses='baseline-derived A0; g0=1.5, kcm=k2=kg=0; (tau,delay) ps=(15,5),(35,1); least training cost',
                  runtime=dict(python=sys.version, numpy=np.__version__, scipy=scipy.__version__, platform=platform.platform()),
                  results=[])
    for tag in card.read(camp / 'plan.json')['conditions']:
        for mode in card.MODES:
            data = {name: all_data[tag, mode, name] for name in TRAIN + HOLDOUT}
            models = []
            for j, stage in enumerate(STAGES):
                fit, function = fit_stage(t, data, j, evaluation)
                models.append((fit, function))
                print(tag, mode, stage, fit['optimizer_success'], fit['weighted_rms_residual'], flush=True)
            item = dict(condition=tag, mode=mode, fits=[dict(stage=s, **f) for s, (f, _) in zip(STAGES, models)], errors=[])
            result['results'].append(item)
            for name in TRAIN + HOLDOUT:
                row = data[name]; cascade = row['signals'][0]
                for j, (fit, function) in enumerate(models):
                    p = list(fit['parameters'].values())
                    one = function(row['signals'][j], row['vdd'], p)
                    cascade = function(cascade, row['vdd'], p)
                    item['errors'].append(dict(point=name, split='train' if name in TRAIN else 'holdout', stage=STAGES[j],
                        one_step=waveform_metrics(t, one, row['signals'][j + 1], row['vdd'], row['signals'][j][0], start, stop),
                        cascade=waveform_metrics(t, cascade, row['signals'][j + 1], row['vdd'], row['signals'][0][0], start, stop)))
    sources = (HERE, REVIEW, card.HERE, Path(cml_dynamic.__file__), Path(clock_transfer.__file__),
               Path(stage_metrics.__file__), Path(clock.__file__), Path(spice.__file__))
    result['source_sha256'] = {str(p.relative_to(ROOT)): card.sha(p) for p in sources}
    result['limitations'] = [
        'Only FS hot and SS cold; three discrete R implementations, fixed WN/WT and prescribed voltage inputs.',
        'No R or device-size interpolation, original source is a rejected full-TX clock iteration.',
        'Clock loads only use fixed cards; downstream final slice/driver still use frozen generic loads.',
        'No upstream impedance, bias feedback, shared supply response, PEX, mismatch or noise prediction.',
        'Empirical complete-point holdout error is not a prediction interval or guaranteed design margin.',
        'CM formula is approximate; bound-active fits, ill conditioning and rail excursions are reported.',
        'Full serializer/pad eye, full payload mapping and physical size adoption remain separate.'
    ]
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review', type=Path, required=True)
    args = p.parse_args()
    result = calculate(args.review.resolve())
    camp = ROOT / result['campaign']
    dest = camp / 'model' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    dest.mkdir(parents=True, exist_ok=False)
    for source in result['source_sha256']:
        target = dest / 'execution' / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target)
    card.dump(dest / 'summary.json', result)
    print(dest / 'summary.json')


if __name__ == '__main__': main()
