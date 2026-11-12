"""Reread the selected reference-loop DC solutions and compare trim/temperature."""
import argparse
import importlib.util
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project, scalar_raw

ROOT = project.ROOT
HERE = Path(__file__).resolve()
RUNNER = ROOT / 'analog/common/bias/tb/physical_reference_card/run.py'
spec = importlib.util.spec_from_file_location('physical_reference_publish', RUNNER)
card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)
read, sha, dump = card.read, card.sha, card.dump


def collect(summary):
    camp = summary.parents[2]; plan = card.check(camp); report = read(summary)
    if report['status'] != 'selected_DC_operating_points_complete_not_startup_or_adoption':
        raise ValueError('physical reference run incomplete')
    if report['plan_sha256'] != sha(camp / 'plan.json'): raise ValueError('reference plan changed')
    for path, expected in report['evidence'].items():
        if sha(ROOT / path) != expected: raise ValueError('reference evidence changed: ' + path)
    cal = card.complete(camp, 'calibration', card.calibration_deck(plan['identity']['overlay']['library']), ['calibration.raw'])
    physical = card.complete(camp, 'physical', card.physical_deck(camp, plan['identity']['overlay']['library']), card.output_names())
    if cal is None or physical is None: raise ValueError('missing reference outputs')
    dimensions = read(camp / 'dimensions.json')
    if (sha(camp / 'dimensions.json') != report['dimensions_sha256'] or
            card.geometries(plan['identity']['curve'], scalar_raw.read(cal / 'calibration.raw')) != dimensions['geometry']):
        raise ValueError('reference calibration does not reproduce')
    for mode in card.MODES:
        variant = camp / 'variants' / (mode + '.spice')
        if (sha(variant) != report['variant_sha256'][mode] or variant.read_text() !=
                card.variant((camp / 'snap' / card.BG.relative_to(ROOT)).read_text(), mode, dimensions['geometry'])):
            raise ValueError('reference variant changed')
    expected = {(m, c, t) for m in card.MODES for c in card.TRIMS for t in card.TEMPS}
    indexed = {(r['mode'], r['trim'], r['temp_c']): r for r in report['rows']}
    if set(indexed) != expected or len(indexed) != len(report['rows']): raise ValueError('reference coverage differs')
    rows = []
    # These deliberately broad diagnostic bounds identify zero-current / wrong
    # DC branches. They do not replace a bias accuracy or startup specification.
    bounds = dict(vbg_v=[1.1, 1.4], max_abs_s_minus_vbg_v=.02, output_current_a=[1e-6, 50e-6])
    for mode, trim, temp in sorted(expected):
        original = indexed[mode, trim, temp]; raw = physical / f'{card.case_name(mode, trim)}_t{temp}.raw'
        observed = scalar_raw.read(raw)
        values = {k: observed['obs_' + k] for k in original['observables']}
        if values != original['observables'] or str(raw.relative_to(ROOT)) != original['raw']:
            raise ValueError('reference scalar remeasurement differs')
        currents = np.asarray([values[f'iout{k}'] for k in range(4)])
        error = values['s'] - values['vbg']
        branch = (bounds['vbg_v'][0] <= values['vbg'] <= bounds['vbg_v'][1] and abs(error) <= .02 and
                  np.all((currents >= 1e-6) & (currents <= 50e-6)) and values['icopy'] > 0 and
                  0 < values['vbias'] < plan['supply_v'])
        drops = {'rref': values['s'] - values['rt5'], **{
            'rt' + str(k): values['rt' + str(k+1)] - (values['rt' + str(k)] if k else 0.) for k in range(5)}}
        rows.append(dict(mode=mode, trim=trim, temp_c=temp, **values,
            output_current_mean_a=float(np.mean(currents)), output_current_spread_a=float(np.ptp(currents)),
            copy_to_output_ratio=float(values['icopy'] / currents[0]) if currents[0] != 0 else None,
            s_minus_vbg_v=error, reference_segment_drops_v=drops,
            enabled_trim_bits=[k for k in range(5) if trim & (1 << k)], diagnostic_expected_DC_branch=bool(branch)))
    by = {(r['mode'], r['trim'], r['temp_c']): r for r in rows}
    trim_checks = []
    for mode in card.MODES:
        for temp in card.TEMPS:
            points = [by[mode, trim, temp] for trim in card.TRIMS]
            differences = np.diff([r['output_current_mean_a'] for r in points])
            trim_checks.append(dict(mode=mode, temp_c=temp, trims=list(card.TRIMS),
                output_current_steps_a=differences.tolist(), sampled_codes_strictly_increasing=bool(np.all(differences > 0))))
    for row in rows:
        generic = by['generic', row['trim'], row['temp_c']]
        row['output_current_change_vs_generic_percent'] = 100 * (row['output_current_mean_a'] / generic['output_current_mean_a'] - 1) if generic['output_current_mean_a'] else None
        row['copy_current_change_vs_generic_percent'] = 100 * (row['icopy'] / generic['icopy'] - 1) if generic['icopy'] else None
    wide = read(card.WIDE_DATA); wide_summary = ROOT / wide['summary']; load_report = read(wide_summary)
    if sha(wide_summary) != wide['summary_sha256']: raise ValueError('wide scalar summary changed')
    load_rows = {(r['id'], r['corner'], r['temp_c'], r['load_drop_grid_v']): r for r in load_report['rows']}
    products = []
    for name in ('r50_2p85_n24', 'r50_5p73_n12', 'r120_2p85_n6', 'r120_5p73_n3',
                 'r240_2p85_n2', 'r240_5p73_n1'):
        for mode in card.MODES:
            nominal = by[mode, 15, 27]['icopy'] * load_rows[name, 'tt', 27, .25]['resistance_ohm']
            values = [by[mode, 15, t]['icopy'] * load_rows[name, 'tt', t, .25]['resistance_ohm'] / nominal for t in card.TEMPS] if nominal else [None] * len(card.TEMPS)
            products.append(dict(load=name, reference_mode=mode, trim=15, temperatures=list(card.TEMPS), normalized_copy_current_times_R=values))
    return dict(status='selected_DC_reference_comparison_no_adoption', adopted=False, rows=rows,
        sampled_trim_checks=trim_checks, expected_DC_branch_bounds=bounds,
        unexpected_DC_branch_count=sum(not r['diagnostic_expected_DC_branch'] for r in rows),
        copy_load_products=products, campaign=str(camp.relative_to(ROOT)), summary=str(summary.relative_to(ROOT)),
        summary_sha256=sha(summary), plan_sha256=report['plan_sha256'], dimensions=dimensions,
        scope=plan['scope'], temperatures=list(card.TEMPS), trims=list(card.TRIMS),
        product_scope='Independent measured n85 diode-copy current times isolated R at 250mV. TT process/1.8V/RC tt, normalized at 27C. Not the actual TX tail current, swing, startup, mismatch or loaded-interface qualification.',
        sources={str(p.relative_to(ROOT)): sha(p) for p in (HERE, RUNNER, card.WIDE_DATA, wide_summary)})


def plots(data):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), layout='constrained')
    colors = dict(generic='#777777', fixed_s1='#c27236', fixed_s8='#20877b')
    for mode, color in colors.items():
        for temp, style in ((-40, ':'), (27, '-'), (85, '--')):
            rows = sorted([r for r in data['rows'] if r['mode'] == mode and r['temp_c'] == temp], key=lambda r: r['trim'])
            axes[0].plot([r['trim'] for r in rows], [r['output_current_mean_a'] * 1e6 for r in rows],
                         style, marker='.', color=color, label=f'{mode} / {temp}C')
        rows = sorted([r for r in data['rows'] if r['mode'] == mode and r['trim'] == 15], key=lambda r: r['temp_c'])
        axes[1].plot([r['temp_c'] for r in rows], [r['copy_to_output_ratio'] for r in rows], 'o-', color=color, label=mode)
        for name, style in (('r50_2p85_n24', '--'), ('r50_5p73_n12', '-')):
            p = next(p for p in data['copy_load_products'] if p['reference_mode'] == mode and p['load'] == name)
            axes[2].plot(p['temperatures'], [100 * (v - 1) if v is not None else np.nan for v in p['normalized_copy_current_times_R']],
                         style, marker='o', color=color, label=f'{mode} / {name}')
    axes[0].set(xlabel='Trim code (sampled)', ylabel='Mean spare output current (uA)')
    axes[0].legend(fontsize=7)
    axes[1].set(xlabel='Temperature (C)', ylabel='n85 diode-copy / spare output current')
    axes[1].axhline(85/4, ls=':', color='#aaaaaa'); axes[1].legend(fontsize=8)
    axes[2].set(xlabel='Temperature (C)', ylabel='Normalized copy-current x R change (%)'); axes[2].legend(fontsize=6)
    for ax in axes: ax.grid(alpha=.2)
    fig.suptitle('Reference-string replacement in the actual bias loop: selected TT / 1.8V DC solutions')
    fig.supxlabel('Core resistors stay generic; six reference segments change. Five sampled trim codes, three temperatures. Products are independent DC proxies, not loaded TX or startup qualification.', fontsize=8)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--summary', type=Path, required=True); a = p.parse_args()
    summary = a.summary.resolve(); data = collect(summary)
    snap = summary.parent / 'publication_sources' / sha(HERE); snap.mkdir(parents=True, exist_ok=True)
    if not (snap / HERE.name).exists(): shutil.copyfile(HERE, snap / HERE.name)
    figure = ROOT / 'docs/figures/common/physical_reference_card.png'
    fig = plots(data); fig.savefig(figure, dpi=170, bbox_inches='tight', pad_inches=.15); plt.close(fig)
    data['figures'] = {str(figure.relative_to(ROOT)): sha(figure)}
    output = ROOT / 'docs/data/physical_reference_card.json'; dump(output, data)
    dump(ROOT / 'results/catalog/physical_reference_card.json', dict(data=str(output.relative_to(ROOT)), data_sha256=sha(output),
        summary=data['summary'], summary_sha256=data['summary_sha256'], figures=data['figures'], status=data['status'],
        unexpected_DC_branch_count=data['unexpected_DC_branch_count']))
    print(output)


if __name__ == '__main__': main()
