"""Extract existing r5 workmap evidence; no simulation or configuration writes."""
import hashlib
import importlib.util
import sys

import numpy as np
import json
from pathlib import Path

from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

SOURCE = 'results/analog/pll/vco/workmap/20261106T035710Z'
FILES = [f'{SOURCE}/summary.json', f'{SOURCE}/extend.json',
         'config/pll_code_table.json', 'config/vco_coarse_calibration.toml',
         'analog/pll/vco/tb/tuning/workmap.py', 'analog/pll/vco/tb/tuning/code_table.py',
         'docs/design/pll_vco.md', 'docs/design/pll_loop.md', 'docs/data/vco_cp_edge_fill.json']


def main():
    raw = {p: (ROOT / p).read_bytes() for p in FILES}
    work = json.loads(raw[FILES[0]])
    extended = json.loads(raw[FILES[1]])
    table = json.loads(raw[FILES[2]])
    assert work['vs'] == table['vs'] == [0.85, 1.1, 1.35]
    assert table['source'] == SOURCE and len(work['rows']) == len(table['table']) == 135
    rows, spacings = {}, []
    for key, row in work['rows'].items():
        c = Condition.parse(key.split(':')[0])
        selected = table['table'][key]
        options = []
        for code in row['usable']:
            f = row['f'][str(code)]
            i = 0 if min(f[:2]) <= 2e9 <= max(f[:2]) else 1
            slope = (f[i + 1] - f[i]) / 0.25
            v = work['vs'][i] + (2e9 - f[i]) / slope
            options.append({'code': code, 'vctrl_interpolated_v': v,
                            'slope_secant_hz_per_v': slope,
                            'headroom_to_0_85_v': v - 0.85,
                            'headroom_to_1_35_v': 1.35 - v})
        assert selected['code'] in row['usable']
        measured = {int(k): v[1] for k, v in row['f'].items()}
        pairs = [{'lower_code': k, 'upper_code': k + 1,
                  'spacing_hz': measured[k] - measured[k + 1]}
                 for k in sorted(measured) if k + 1 in measured]
        spacings.extend({'condition': key, **pair} for pair in pairs)
        rows[key] = {'supply_v': c.supply, 'selected': selected,
                     'feasible_codes_0_85_to_1_35_v': options,
                     'measured_frequencies_at_1_1_v_hz': measured,
                     'adjacent_measured_spacing_at_1_1_v': pairs}
    cp = extended['4 bit, simulated: 0.85 V-CP edge']
    failures = set(cp['frozen_bad'])
    chips = {f'{Condition.parse(k.split(":")[0]).process}_{round(Condition.parse(k.split(":")[0]).supply * 1000)}_{k.split(":")[1]}' for k in rows}
    assert len(chips) == 45 and len(failures) == 3 and cp['frozen_ok'] == 42
    assert all(p['spacing_hz'] > 0 for p in spacings)
    out = {'source_sha256': {p: hashlib.sha256(b).hexdigest() for p, b in raw.items()},
           'assumptions': {'target_hz': 2e9, 'voltage_points_v': work['vs'],
             'fixed_window_v': [0.85, 1.35], 'crossing': 'linear interpolation between measured voltage points',
             'frequency_at_1_1': 'measured simulated points only; missing codes not estimated',
             'cp_edge_temperature_result': 'separate extended-point campaign; see extend.json and workmap.py'},
           'conditions': rows,
           'fewer_than_two_feasible_conditions': [k for k, r in rows.items() if len(r['feasible_codes_0_85_to_1_35_v']) < 2],
           'fixed_code_cp_edge_all_temperature': {'count': 42, 'chips': sorted(chips - failures), 'insufficient_data_for_all_temperature_in_source': sorted(failures), 'source_record': cp},
           'adjacent_spacing_measured_1_1_v_hz': {'count': len(spacings), 'min': min(spacings, key=lambda x: x['spacing_hz']), 'max': max(spacings, key=lambda x: x['spacing_hz'])}}
    supplement = json.loads(raw['docs/data/vco_cp_edge_fill.json'])
    assert len(supplement['groups']) == 3
    assert all(len(g['series']) == 3 and all(x['brackets'] for x in g['series']) for g in supplement['groups'])
    out['fixed_code_temperature_supplement'] = {'known_groups_after_fill': 45, 'source': 'docs/data/vco_cp_edge_fill.json', 'groups': supplement['groups'], 'scope': 'Static three-temperature reachability only; original 42-group record retained separately.'}
    evidence = {
        'package_id': 'WP-006',
        'execution_status': 'partial',
        'inputs': [{'path': p, 'sha256': hashlib.sha256(b).hexdigest()} for p, b in raw.items()],
        'observations': out,
        'checks': [
            {'id': 'historical_input_identity_and_grid', 'status': 'pass',
             'detail': '码表指向指定工作图；三个电压点一致；135 条件及码表项存在。'},
            {'id': 'mechanical_extraction', 'status': 'pass',
             'detail': '逐行选码包含于可行码；记录45组、原extend的42/3分类和实测相邻码正间距。'},
            {'id': 'behavior_model', 'status': 'ungraded', 'detail': '行为模型尚未实现或验证。'},
            {'id': 'dynamic_startup_and_switching', 'status': 'ungraded',
             'detail': '切码毛刺、稳定、B2再稳定、实际闭环和上电不在历史静态数据内。'}],
        'unresolved': [
            '原extend的42/3分类保留；11-07共同码补测已补齐三组静态覆盖，但未验证动态接管或启动。',
            '四位粗调行为模型、计数器、接管、动态启动及切码需独立验证。']}
    evidence['checks'].append({'id': 'supplement_three_fixed_codes', 'status': 'pass', 'detail': '独立采集的三个固定码均有三温实测夹区；原42组加补测3组为45组静态覆盖，不是启动通过。'})
    dest = ROOT / 'docs/work_packages/deliveries/WP-006/evidence.json'
    dest.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
    print('conditions', len(rows), 'fewer than two', len(out['fewer_than_two_feasible_conditions']), 'spacing', out['adjacent_spacing_measured_1_1_v_hz'])


def tradeoff():
    cp_path = 'results/analog/pll/cp/window/20261106T021356Z/summary.json'
    cp = json.loads((ROOT / cp_path).read_bytes())['rows']
    work = json.loads((ROOT / FILES[0]).read_bytes())
    spec = importlib.util.spec_from_file_location('wp006_workmap', ROOT / FILES[4])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hashes = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in FILES + [cp_path, 'analog/pll/cp/tb/dc/window.py', 'verification/work_packages/wp006_pll_coarse.py']}
    groups = {}
    for process, rc in [('ff', 'tt'), ('ff', 'll'), ('fs', 'll')]:
        rows = []
        for temp in [-40, 27, 85]:
            key = f'{process}_v1950_t{temp}:{rc}'
            c = Condition.parse(key.split(':')[0])
            row = work['rows'][key]
            bounds = []
            for voltage in [0.85, 1.35, 1.5]:
                pts = []
                for code, f in row['f'].items():
                    if voltage in (0.85, 1.35):
                        freq = f[0 if voltage == 0.85 else 2]
                    else:
                        path = module.spice.case_output(ROOT / SOURCE, f'{process}_{rc}', module.name(c, int(code), voltage), module.STOP)
                        if path is None:
                            continue
                        measured = module.measure(path)
                        if measured is None:
                            continue
                        freq = measured[0]
                        rel = str(path.relative_to(ROOT))
                        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
                    pts.append((int(code), freq))
                pts.sort()
                # Bracketing measured frequencies only; interpolate reciprocal frequency.
                crossings = []
                for (a, fa), (b, fb) in zip(pts, pts[1:]):
                    if min(fa, fb) <= 2e9 <= max(fa, fb):
                        crossings.append(a + (1 / 2e9 - 1 / fa) * (b - a) / (1 / fb - 1 / fa))
                fit = np.polyfit([k for k, _ in pts], [1 / f for _, f in pts], 2)
                residual = [abs(1 / np.polyval(fit, k) / f - 1) for k, f in pts]
                roots = [float(x.real) for x in np.roots([fit[0], fit[1], fit[2] - 1 / 2e9]) if abs(x.imag) < 1e-8 and pts[0][0] <= x.real <= pts[-1][0]]
                bounds.append({'voltage_v': voltage, 'measured_points_hz': pts,
                               'interpolated_crossing_codes': crossings,
                               'quadratic_reciprocal_fit_coefficients': fit.tolist(),
                               'fit_roots_within_measured_code_range': roots,
                               'fit_max_relative_frequency_residual': max(residual),
                               'fit_mean_relative_frequency_residual': float(np.mean(residual))})
            rows.append({'condition': key, 'cp_measured_upper_v': cp[key]['hi'], 'bounds': bounds})
        intervals = [(r['bounds'][0]['interpolated_crossing_codes'], r['bounds'][1]['interpolated_crossing_codes']) for r in rows]
        if all(len(a) == len(b) == 1 for a, b in intervals):
            lo = max(a[0] for a, b in intervals)
            hi = min(b[0] for a, b in intervals)
            overlap = {'lower_code': lo, 'upper_code': hi, 'empty': lo > hi,
                       'half_step_codes': [x / 2 for x in range(31) if lo <= x / 2 <= hi]}
        else:
            overlap = None
        groups[f'{process}_1950_{rc}'] = {'temperatures': rows, 'intersection_0_85_to_1_35_v': overlap,
            'actual_cp_edge_intersection': 'inconclusive: VCO data stop at 1.5 V; CP edge exceeds 1.5 V'}
    out = {'method': 'Measured VCO points and CP edge; reciprocal-frequency linear interpolation in code only between measured brackets; quadratic fits are diagnostics. The 1.35 V intersection is a narrower sampled window; 1.5 V data do not bracket the target at these temperatures. Neither is the CP edge. No extrapolation.',
           'source_sha256': hashes, 'groups': groups}
    dest = ROOT / 'docs/work_packages/deliveries/WP-006/resolution_tradeoff.json'
    dest.write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    for k, v in groups.items():
        print(k, v['intersection_0_85_to_1_35_v'])


if __name__ == '__main__':
    if sys.argv[1:] == ['--tradeoff']:
        tradeoff()
    elif not sys.argv[1:]:
        main()
    else:
        raise SystemExit('usage: wp006_pll_coarse.py [--tradeoff]')
