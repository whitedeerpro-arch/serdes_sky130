"""Bounded first-order differential buffer model; offline archived-waveform spike.

No ngspice. e0-e3 only, WN24 driving WN24, TT and FS. Training and
holdout identities are fixed below; this is not a TX acceptance model.
"""
import hashlib
import importlib.util
import json
import platform
import sys
from pathlib import Path

import numpy as np
import scipy
from scipy.optimize import least_squares
from scipy.signal import lfilter
from serdes_flow import clock, spice
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve()
NAMES = ('cascade', 'sizing', 'gain_search', 'taper')
TRAIN = {'cascade': ('baseline', 'extra5'), 'sizing': ('tail14', 'tail14p4')}
HOLD = {'gain_search': ('tail15', 'tail15p6_r300'), 'taper': ('first14', 'first14p4')}
TAGS = ('tt_v1800_t27', 'fs_v1650_t85')
DT = 1e-12
T = np.arange(1.5e-9, 6.401e-9, DT)
EVAL = (T >= 4e-9) & (T <= 6.4e-9)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text())


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def verify(name):
    data_path = ROOT / f'docs/data/tx_buffer_{name}.json'
    catalog_path = ROOT / f'results/catalog/tx_buffer_{name}.json'
    data, index = read(data_path), read(catalog_path)
    if index['data_sha256'] != digest(data_path) or index['data'] != str(data_path.relative_to(ROOT)):
        raise ValueError(f'{name}: publication identity')
    camp, summary = ROOT / data['campaign'], ROOT / data['summary']
    if index['campaign'] != data['campaign'] or index['summary'] != data['summary'] or index['summary_sha256'] != data['summary_sha256'] or digest(summary) != data['summary_sha256']:
        raise ValueError(f'{name}: summary identity')
    kind = 'buffer_cascade_card.py' if name == 'cascade' else ('buffer_matrix_card.py' if name == 'taper' else 'buffer_sizing_card.py')
    runner = ROOT / 'analog/tx/input_register/tb/final_clock_chain' / kind
    card = module(runner, f'card_{name}')
    card.check(camp, registered=True)
    if digest(runner) != data['runner_sha256'] or digest(camp / 'plan.json') != data['plan_sha256']:
        raise ValueError(f'{name}: runner/plan mismatch')
    rows = read(summary)['rows']
    if rows != data['results'] or {r['condition'] for r in rows} != set(TAGS):
        raise ValueError(f'{name}: summary rows differ')
    loaded = {}
    for row in rows:
        tag = row['condition']
        raw = card.old.completed(camp, tag)
        if raw is None or str(raw.relative_to(ROOT)) != row['raw'] or digest(raw) != row['raw_sha256']:
            raise ValueError(f'{name}/{tag}: incomplete or changed raw')
        if index['evidence'][tag] != data['evidence'][tag]:
            raise ValueError('catalog evidence differs')
        for filename, expected in data['evidence'][tag].items():
            path = raw if filename == raw.name else raw.parent / filename
            if digest(path) != expected:
                raise ValueError(f'changed evidence: {path}')
        if not row['result']['baseline_matches']:
            raise ValueError('baseline not calibrated')
        w = spice.Waves(raw)
        branches = {}
        for i, b in enumerate(row['result']['branches'], 1):
            label = b['branch']
            if name == 'cascade':
                if label not in ('baseline', 'extra5'): continue
                widths = [(16.,400.)]*4 if label == 'baseline' else [(12.8,320.)]*4
            else:
                p = b['actual_parameters']
                widths = [(s[1],s[2]) for s in p['stages'][:4]] if 'stages' in p else [(p['wt_um'],p['r_nominal_ohm'])]*4
            node = lambda n: np.interp(T, w.t, w[f'xclock{i}.{n}p'] - w[f'xclock{i}.{n}n'])
            branches[label] = {'signals': [node('i')] + [node(f'e{k}') for k in range(4)], 'widths': widths}
        loaded[tag] = branches
    return loaded, {'publication': str(data_path.relative_to(ROOT)), 'publication_sha256': digest(data_path),
                    'catalog_sha256': digest(catalog_path), 'summary_sha256': digest(summary),
                    'campaign': data['campaign'], 'evidence': data['evidence'],
                    'plan_sha256': data['plan_sha256'], 'runner_sha256': data['runner_sha256']}


def drive(x, width, resistance, p):
    # x,y are differential voltages; p = [half-amplitude, small-signal gain,
    # tau(ps), explicit input delay(ps)], referenced to 14.4 um / 320 ohm.
    a0, g0, tau0, delay = p
    scale = width / 14.4
    r = resistance / 320.
    a = a0 * scale * r
    gain = g0 * np.sqrt(scale) * r
    xd = np.interp(T - delay * 1e-12, T, x, left=x[0], right=x[-1])
    target = a * np.tanh(gain * xd / a)
    alpha = np.exp(-DT / (tau0 * r * 1e-12))
    # The first 2.5 ns is settling history; no observed output initializes a stage.
    return lfilter([1-alpha], [1, -alpha], target, zi=[target[0]*alpha])[0]


def crossing(t, y):
    return clock.edges(t, y, 1, 4e-9, 6.4e-9), clock.edges(t, y, -1, 4e-9, 6.4e-9)


def metrics(pred, actual):
    amplitude_error = (np.ptp(pred[EVAL]) - np.ptp(actual[EVAL])) * 1000
    differences, slopes, counts = [], [], []
    for a, b in zip(crossing(T, actual), crossing(T, pred)):
        counts.append([len(a),len(b)])
        if len(a) != len(b) or not len(a):
            return {'amplitude_error_mv': float(amplitude_error), 'crossing_counts_actual_predicted': counts,
                    'crossing_error_ps_median': None, 'crossing_error_ps_max_abs': None,
                    'slew_error_v_per_ns_median': None, 'slew_error_v_per_ns_max_abs': None}
        differences.extend((b-a)*1e12)
        for ta, tb in zip(a,b):
            # Same 10 ps aperture around each actual/predicted zero crossing.
            s1 = (np.interp(ta+5e-12,T,actual)-np.interp(ta-5e-12,T,actual)) / .01
            s2 = (np.interp(tb+5e-12,T,pred)-np.interp(tb-5e-12,T,pred)) / .01
            slopes.append(abs(s2)-abs(s1))
    return {'amplitude_error_mv': float(amplitude_error), 'crossing_counts_actual_predicted': counts,
            'crossing_error_ps_median': float(np.median(differences)), 'crossing_error_ps_max_abs': float(np.max(np.abs(differences))),
            'slew_error_v_per_ns_median': float(np.median(slopes)), 'slew_error_v_per_ns_max_abs': float(np.max(np.abs(slopes)))}


def calculate():
    all_data, identities = {}, {}
    for name in NAMES:
        all_data[name], identities[name] = verify(name)
    result = {}
    for tag in TAGS:
        train = [(name,label,all_data[name][tag][label]) for name, labels in TRAIN.items() for label in labels]
        def residual(p):
            return np.concatenate([(drive(d['signals'][i], *d['widths'][i], p)-d['signals'][i+1])[EVAL][::4]
                                   for _,_,d in train for i in range(4)])
        fit = least_squares(residual, [.22, 1.5, 20., 5.], bounds=([.05,.1,1.,0.],[1.,8.,120.,80.]), max_nfev=300)
        if not fit.success: raise ValueError(f'fit failed {tag}: {fit.message}')
        p = fit.x
        errors = []
        for split, groups in [('train', TRAIN), ('holdout', HOLD)]:
            for name, labels in groups.items():
                for label in labels:
                    d = all_data[name][tag][label]
                    cascade = d['signals'][0].copy()
                    for i in range(4):
                        one = drive(d['signals'][i], *d['widths'][i], p)
                        cascade = drive(cascade, *d['widths'][i], p)
                        errors.append({'split': split, 'source': name, 'branch': label, 'stage': f'e{i}',
                                       'wt_um': d['widths'][i][0], 'r_nominal_ohm': d['widths'][i][1],
                                       'one_step_measured_input': metrics(one,d['signals'][i+1]),
                                       'cascade_from_measured_iso_only': metrics(cascade,d['signals'][i+1])})
        result[tag] = {'parameters': {'half_saturation_v':float(p[0]),'small_signal_gain':float(p[1]),
                                      'tau_ps':float(p[2]),'explicit_delay_ps':float(p[3])},
                       'fit_rms_mv':float(np.sqrt(np.mean(residual(p)**2))*1000),
                       'fit_status':fit.message, 'stage_errors':errors}
    files = [HERE, ROOT/'src/serdes_flow/clock.py', ROOT/'src/serdes_flow/spice.py',
             ROOT/'analog/tx/input_register/tb/final_clock_chain/buffer_cascade_card.py',
             ROOT/'analog/tx/input_register/tb/final_clock_chain/buffer_sizing_card.py',
             ROOT/'analog/tx/input_register/tb/final_clock_chain/buffer_matrix_card.py']
    output = {'status':'exploratory_unqualified', 'scope':'TT 1.8 V 27 C and FS 1.65 V 85 C; recorded ideal-source PWL local chain, e0-e3 WN24 driving WN24 only.',
              'formula':'tau(R) dy/dt + y = A(WT,R) tanh(g(WT,R) vin(t-delay)/A); A~WT*R, g~sqrt(WT)*R, tau~R',
              'training':TRAIN,'holdout':HOLD,'inputs':identities,
              'source_sha256':{str(x.relative_to(ROOT)):digest(x) for x in files},
              'runtime':{'python':sys.version,'numpy':np.__version__,'scipy':scipy.__version__,'platform':platform.platform()},
              'method':'1 ps sampled differential waveforms, 1.5–4 ns settling history; 4–6.4 ns fit/evaluation; separate independent fit per condition. Holdout never used in fit. Each cascade starts only from measured iso waveform; no internal measured stage reset. Crossing and 10 ps aperture slew errors are predicted minus measured.',
              'limitations':['Only two conditions; no PVT interpolation or qualification.', 'Correlated stages and repeated cycles are not independent samples; holdout extrapolates in width and R.', 'Output scaling uses nominal R, not extracted physical PDK resistance.', 'No e4 WN32 heavy load, Xout, common mode, upstream impedance, bias feedback, mismatch, noise, power, serializer or pad.', 'Holdout error is empirical model discrepancy, not a statistical confidence interval or a guaranteed error bound.', 'No candidate dimensions selected; waveform model does not establish timing or eye compliance.'],
              'results':result}
    return output


def main():
    output = calculate()
    result = output['results']
    target=ROOT/'docs/data/tx_buffer_dynamic_model.json'
    target.write_text(json.dumps(output,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:{'parameters':v['parameters'],'fit_rms_mv':v['fit_rms_mv'],
                       'holdout_max': {field:max(abs(e[mode][field]) for e in v['stage_errors'] if e['split']=='holdout' for mode in ('one_step_measured_input','cascade_from_measured_iso_only') if e[mode][field] is not None) for field in ('amplitude_error_mv','crossing_error_ps_max_abs','slew_error_v_per_ns_max_abs')}} for k,v in result.items()},indent=2))


if __name__ == '__main__':
    main()
