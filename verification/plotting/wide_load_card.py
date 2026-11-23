"""Remeasure wide-poly scalar outputs and publish current/R/C tradeoffs."""
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
RUNNER = ROOT / 'analog/common/devices/tb/passive_card/wide_load_card.py'
spec = importlib.util.spec_from_file_location('wide_card_publish', RUNNER)
card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)
sha, read, dump = card.sha, card.read, card.dump


def layout_review(delivery, repeated):
    a, b = read(delivery), read(repeated)
    fields = ('cell', 'device', 'parameters', 'check_returncode', 'drc_total', 'subckt_ports',
              'extracted_devices', 'ports_used_by_device', 'extracted_l_um', 'guard_contact_label_on_psub', 'pass_review')
    if a['status'] != 'isolated_primitive_review_pass' or b['status'] != a['status'] or len(a['cells']) != 2 or len(b['cells']) != 2:
        raise ValueError('primitive review incomplete')
    if [{k: r[k] for k in fields} for r in a['cells']] != [{k: r[k] for k in fields} for r in b['cells']]:
        raise ValueError('independent primitive review differs')
    for path, report in ((delivery, a), (repeated, b)):
        for source, expected in report['sources'].items():
            if sha(source) != expected: raise ValueError('layout review source changed')
        for cell in report['cells']:
            for rel, expected in cell['evidence'].items():
                if sha(path.parent / rel) != expected: raise ValueError('layout review evidence changed')
    return dict(delivery=str(delivery.relative_to(ROOT)), delivery_sha256=sha(delivery),
                repeated=str(repeated.relative_to(ROOT)), repeated_sha256=sha(repeated),
                cells=[{k: r[k] for k in fields} for r in b['cells']], scope=b['scope'])


def collect(summary, delivery, repeated):
    camp = summary.parents[2]; plan = card.check(camp); original = read(summary); model = read(camp / 'networks.json')
    if original['status'] != 'wide_networks_measured_not_actual_bias_or_circuit_qualified': raise ValueError('card incomplete')
    if original['plan_sha256'] != sha(camp / 'plan.json') or original['networks_sha256'] != sha(camp / 'networks.json'):
        raise ValueError('plan/network identity changed')
    for path, expected in {**original['evidence'], **original['calibration_evidence']}.items():
        if sha(ROOT / path) != expected: raise ValueError('measurement evidence changed')
    caltext = (camp / 'prepared/calibration.cir').read_text()
    cal = card.complete(camp, 'calibration', caltext, card.output_names(True))
    if cal is None or card.make_networks(plan, cal) != model: raise ValueError('geometry does not reproduce from calibration raw')
    runs = {}
    for rc in card.CORNERS:
        runs[rc] = card.complete(camp, rc, card.deck(model['parts'], rc, plan['overlay']['library']), card.output_names())
        if runs[rc] is None: raise ValueError('missing passive case')
    rows, evidence = card.measure(camp, model, runs)
    if rows != original['rows'] or evidence != original['evidence']: raise ValueError('scalar remeasurement differs')
    expected = {(p['id'], rc, t, d) for p in model['parts'] for rc in card.CORNERS for t in card.TEMPS for d in card.DROPS}
    indexed = {(r['id'], r['corner'], r['temp_c'], r['load_drop_grid_v']): r for r in rows}
    if set(indexed) != expected or len(indexed) != len(rows): raise ValueError('missing or duplicated passive grid points')
    # Every network contains only passive R/C devices and grounded rails/body.
    # Check admittance signs separately from the LF derivative agreement gate.
    quantities = ('resistance_ohm', 'FD_resistance_ohm', 'LF_incremental_resistance_ohm',
                  'RF_real_admittance_inverse_ohm', 'RF_effective_node_capacitance_f')
    physical_minima = {}
    for quantity in quantities:
        row = min(rows, key=lambda r: r[quantity]); value = row[quantity]
        if value < 0 or (quantity != 'RF_effective_node_capacitance_f' and value == 0):
            raise ValueError(f'nonphysical passive result: {quantity}={value}, '
                             f'{row["id"]}/{row["corner"]}/{row["temp_c"]}/{row["load_drop_grid_v"]}')
        physical_minima[quantity] = {k: row[k] for k in
                                    ('id', 'corner', 'temp_c', 'load_drop_grid_v', quantity)}
    parts = []
    for p in model['parts']:
        name = p['id']; nominal = indexed[name, 'tt', 27, .25]
        entry = {k: v for k, v in p.items() if k != 'instance'}
        entry.update(TT27C_load250mV_resistance_ohm=nominal['resistance_ohm'],
                     TT27C_load250mV_node_capacitance_f=nominal['RF_effective_node_capacitance_f'],
                     max_LF_AC_vs_FD_relative_error=max(r['LF_AC_vs_FD_relative_error'] for r in rows if r['id'] == name))
        if p['kind'] != 'reference_string_surrogate':
            entry['tracking_proxies'] = {}
            for reference in ('reference_generic', 'reference_fixed_s1', 'reference_fixed_s8'):
                reference0 = indexed[reference, 'tt', 27, .25]['resistance_ohm']
                values = [(indexed[name, rc, temp, .25]['resistance_ohm'] / indexed[reference, rc, temp, .25]['resistance_ohm']) /
                          (nominal['resistance_ohm'] / reference0) for rc in card.CORNERS for temp in card.TEMPS]
                entry['tracking_proxies'][reference] = dict(normalized_min=min(values), normalized_max=max(values),
                    max_abs_percent=max(abs(np.asarray(values) - 1)) * 100)
            entry['voltage_dependence_TT27C'] = [indexed[name, 'tt', 27, d] for d in card.DROPS]
        parts.append(entry)
    return dict(status='calibrated_wide_poly_planning_no_adoption', adopted=False,
                campaign=str(camp.relative_to(ROOT)), summary=str(summary.relative_to(ROOT)), summary_sha256=sha(summary),
                plan_sha256=original['plan_sha256'], networks_sha256=original['networks_sha256'],
                curves=model['curves'], parts=parts, choices=model['choices'],
                measured_rows=len(rows), current_boundary=plan['current_boundary'], overlay=plan['overlay'],
                max_LF_AC_vs_FD_relative_error=max(r['LF_AC_vs_FD_relative_error'] for r in rows),
                passive_physical_minima=physical_minima,
                reference_scope=plan['reference_scope'], geometry_scope=plan['geometry_scope'], ungraded=plan['ungraded'],
                current_density_scope='Prescribed 6.619mA local two-condition clean-input peak, assumed equal sharing; no fixed-network full-PVT current prediction or EM.',
                capacitance_scope='Port-effective PDK admittance at 2GHz with rail/body AC-grounded, not routed PEX. Reference series networks have distributed RC; RF inverse conductance need not equal DC slope.',
                primitive_layout_review=layout_review(delivery, repeated),
                sources={str(p.relative_to(ROOT)): sha(p) for p in (HERE, RUNNER)})


def plots(data):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), layout='constrained')
    for width, color in (('2p85', '#c27236'), ('5p73', '#20877b')):
        parts = [p for p in data['parts'] if p['kind'] == 'fixed_load' and p['nominal_ohm'] == 50 and p['card'] == width]
        for p in parts:
            cap = p['TT27C_load250mV_node_capacitance_f'] * 1e15
            j = p['hypothetical_peak_uA_per_um']; area = p['poly_body_area_um2']
            error = p['tracking_proxies']['reference_fixed_s8']['max_abs_percent']
            for ax, x, y in ((axes[0], cap, j), (axes[1], area, cap), (axes[2], cap, error)):
                ax.scatter(x, y, color=color, s=35)
                ax.annotate(str(p['parallel_count']), (x, y), xytext=(4, 5 if width == '2p85' else -12),
                            textcoords='offset points', fontsize=8)
        axes[0].plot([], [], 'o', color=color, label='Width ' + str(card.geometry.WIDTHS[width]) + 'um')
    axes[0].axhline(100, color='#555', ls='--', lw=.8); axes[0].axhline(500, color='#888', ls=':', lw=.8)
    axes[0].set(xlabel='Port C at 2GHz (fF)', ylabel='Hypothetical peak current / width (uA/um)'); axes[0].legend(fontsize=8)
    axes[1].set(xlabel='Resistive film area only (um²)', ylabel='Port C at 2GHz (fF)')
    axes[2].set(xlabel='Port C at 2GHz (fF)', ylabel='Maximum reference-ratio deviation (%)')
    for ax in axes: ax.grid(alpha=.2); ax.margins(x=.12, y=.12)
    fig.suptitle('Local 50-ohm termination planning: separately calibrated widths / explicit counts')
    fig.supxlabel('TT geometry matched to legacy electrical R. 100/500 are preferred/model current guidance; same prescribed peak for all points. Ratio uses controlled code15 R-only string, not the bias loop.', fontsize=8)
    other, axs = plt.subplots(2, 3, figsize=(13.5, 7), layout='constrained')
    for ax, target in zip(axs.ravel(), card.TARGETS):
        for width, color in (('2p85', '#c27236'), ('5p73', '#20877b')):
            parts = [p for p in data['parts'] if p['kind'] == 'fixed_load' and p['nominal_ohm'] == target and p['card'] == width]
            for p in parts:
                cap = p['TT27C_load250mV_node_capacitance_f'] * 1e15
                error = p['tracking_proxies']['reference_fixed_s8']['max_abs_percent']
                ax.scatter(cap, error, color=color, s=30)
                ax.annotate(str(p['parallel_count']), (cap, error), xytext=(3, 5 if width == '2p85' else -10),
                            textcoords='offset points', fontsize=7)
            ax.plot([], [], 'o', color=color, label=width)
        ax.set(title=str(target) + ' ohm nominal', xlabel='Port C at 2GHz (fF)', ylabel='Reference-ratio max deviation (%)')
        ax.grid(alpha=.2); ax.margins(x=.12, y=.15)
    axs[0, 0].legend(fontsize=7)
    other.suptitle('Load / controlled-reference tracking: 5 RC corners x 3 temperatures')
    other.supxlabel('Counts label explicit parallel devices; matching is at TT27C/250mV, reference-string drop is 1.23V. No adopted network, full circuit or routed layout qualification.', fontsize=8)
    return fig, other


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--summary', type=Path, required=True)
    p.add_argument('--layout-delivery', type=Path, required=True); p.add_argument('--layout-repeat', type=Path, required=True); a = p.parse_args()
    summary = a.summary.resolve(); data = collect(summary, a.layout_delivery.resolve(), a.layout_repeat.resolve())
    dest = summary.parent / 'publication_sources' / sha(HERE); dest.mkdir(parents=True, exist_ok=True)
    if not (dest / HERE.name).exists(): shutil.copyfile(HERE, dest / HERE.name)
    figs = plots(data); paths = [ROOT / 'docs/figures/common/wide_termination_card.png', ROOT / 'docs/figures/common/wide_load_tracking.png']
    for fig, path in zip(figs, paths): fig.savefig(path, dpi=170, bbox_inches='tight', pad_inches=.15)
    plt.close('all'); data['figures'] = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    output = ROOT / 'docs/data/wide_load_card.json'; dump(output, data)
    dump(ROOT / 'results/catalog/wide_load_card.json', dict(data=str(output.relative_to(ROOT)), data_sha256=sha(output),
         figures=data['figures'], summary=data['summary'], summary_sha256=data['summary_sha256'], measured_rows=data['measured_rows'], status=data['status']))
    print(output)


if __name__ == '__main__': main()
