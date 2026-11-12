"""Publish reproduced finite-window audits and measured paired load states."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project, spice, waves
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve()
RUNNER = ROOT / 'analog/tx/output_driver/tb/coupling_state/run.py'
spec = importlib.util.spec_from_file_location('publish_coupling_card', RUNNER)
card = importlib.util.module_from_spec(spec); spec.loader.exec_module(card)
CURRENT = ROOT / 'results/analysis/tx_termination_current/20261111T181313.220139Z_6f967973/summary.json'
CURRENT_REPEAT = ROOT / 'results/analysis/tx_termination_current/20261112T043136.535700Z_7ce979c2/summary.json'
COUPLING = ROOT / 'results/analysis/tx_coupling_state/20261111T181734.249315Z_7dac0565/summary.json'
COUPLING_REPEAT = ROOT / 'results/analysis/tx_coupling_state/20261112T043200.509894Z_003c988a/summary.json'
read, dump, sha = card.read, card.dump, card.sha


def audits():
    current, coupling = read(CURRENT), read(COUPLING)
    if current != read(CURRENT_REPEAT) or coupling != read(COUPLING_REPEAT):
        raise ValueError('offline audits did not reproduce exactly')
    if len(current['rows']) != 45 or len(coupling['rows']) != 45: raise ValueError('audit grid incomplete')
    if coupling['prior_summary_sha256'] != sha(CURRENT): raise ValueError('audit dependency differs')
    if current['source_sha256'] != sha(ROOT / current['source']): raise ValueError('TX source index changed')
    for report, field in ((current, 'analysis_sources_sha256'), (coupling, 'sources_sha256')):
        for path, expected in report[field].items():
            if sha(ROOT / path) != expected: raise ValueError('audit source changed: ' + path)
    for r in current['rows']:
        camp = ROOT / r['campaign']
        for path, expected in ((ROOT / r['raw'], r['raw_sha256']), (camp / 'plan.json', r['plan_sha256']),
                               (camp / 'summary.json', r['summary_sha256']),
                               (camp / 'execution/physical_tb.cir', r['deck_sha256'])):
            if sha(path) != expected: raise ValueError('audit source evidence changed')
    return current, coupling


def collect(summary):
    current, coupling = audits(); camp = summary.parents[2]; plan = card.check(camp); original = read(summary)
    if original['status'] != 'paired_local_state_measured_no_full_TX_qualification' or original['plan_sha256'] != sha(camp / 'plan.json'):
        raise ValueError('paired campaign incomplete or changed')
    if {r['condition'] for r in original['rows']} != set(card.TAGS) or len(original['rows']) != len(card.TAGS):
        raise ValueError('paired cases missing or duplicated')
    result = dict(status='reproduced_finite_record_audits_and_local_paired_state_no_full_TX_qualification',
                  summary=str(summary.relative_to(ROOT)), summary_sha256=sha(summary), plan_sha256=original['plan_sha256'],
                  audited_current=current, audited_coupling=coupling, paired_rows=[], failures=[],
                  evidence={str(p.relative_to(ROOT)): sha(p) for p in (CURRENT, CURRENT_REPEAT, COUPLING, COUPLING_REPEAT, HERE, RUNNER)},
                  scope=plan['scope'], limits=current['rules'],
                  interpretation='Old 45 records cover a finite turn-on/charge history. Native resistor conduction and tail currents are measured only in the new two-condition clean-input paired experiment. Peak-current equal-sharing counts are planning values, not AC EM or physical fixed-resistor qualification.')
    waveforms = {}
    for row in original['rows']:
        tag = row['condition']; raw = card.completed(camp, tag, plan)
        if raw is None or str(raw.relative_to(ROOT)) != row['raw']: raise ValueError('missing or wrong completed paired raw')
        for path, expected in row['evidence'].items():
            if sha(ROOT / path) != expected: raise ValueError('paired evidence changed')
        actual = card.measure(raw, plan)
        # Float-valued deterministic telemetry should reproduce exactly here.
        if actual != row['result']: raise ValueError('paired metrics do not reproduce from raw')
        entry = dict(row); entry['full_record_current'] = []; result['paired_rows'].append(entry)
        w = spice.Waves(raw); waveforms[tag] = w
        old_r = current['passive_checks'][str(Condition.parse(tag).temp)]['samples'][0]['resistance_ohm']
        for i, branch in enumerate(actual['branches'], 1):
            currents = []
            for name, node in ((f'irp{i}', f'lqp{i}'), (f'irn{i}', f'lqn{i}')):
                y = w[name]; peak = float(np.max(abs(y))); drop = w['vdd'] - w[node]
                currents.append(dict(node=node, measured_peak_abs_a=peak,
                    measured_mean_a=float(waves.time_average(y, w.t)),
                    measured_rms_a=float(np.sqrt(waves.time_average(y * y, w.t))),
                    measured_R_total_mean_power_w=float(waves.time_average(y * drop, w.t)),
                    generic_DC_R_conduction_crosscheck_max_error_a=float(np.max(abs(y - drop / old_r))),
                    hypothetical_fixed_2p85_equal_share_peak_uA_per_um={str(n): peak * 1e6 / (2.85 * n) for n in (5, 6, 8, 17, 24)},
                    hypothetical_count_at_model_500=math.ceil(peak * 1e6 / (2.85 * 500)),
                    hypothetical_count_at_preferred_100=math.ceil(peak * 1e6 / (2.85 * 100))))
            entry['full_record_current'].append(dict(mode=branch['mode'], window_s=[float(w.t[0]), float(w.t[-1])], branches=currents))
            for output in ('pad', 'remote'):
                r = branch['outputs'][output]
                if not r['check']['functional'] or not r['mapping']['in_order'] or not r['local_draft_meets']:
                    result['failures'].append(dict(condition=tag, mode=branch['mode'], output=output,
                        functional=r['check']['functional'], in_order=r['mapping']['in_order'], clean_input_local_draft=r['local_draft_meets']))
    return result, waveforms


def paired_plot(data, waveforms):
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), layout='constrained')
    for row, tag in enumerate(card.TAGS):
        w = waveforms[tag]; x = w.t * 1e9
        for i, color, mode in ((1, '#c27236', 'enable at 4ns'), (2, '#20877b', 'enabled DC initial state')):
            local = ((w[f'lqp{i}'] + w[f'lqn{i}']) / 2 - w['vdd']) * 1000
            remote = ((w[f'lrp{i}'] + w[f'lrn{i}']) / 2 - .9) * 1000
            axes[row, 0].plot(x, local, color=color, lw=.8, label=mode + ': local - VDD')
            axes[row, 0].plot(x, remote, color=color, ls=':', lw=.8, label=mode + ': remote - 0.9V')
            axes[row, 1].plot(x, (w[f'irp{i}'] + w[f'irn{i}']) * 1000, color=color, lw=.8, label=mode + ': local R sum')
        axes[row, 1].plot(x, w['itail2'] * 1000, color='#48566a', ls='--', lw=.8, label='Measured warm-copy tail')
        axes[row, 0].set_ylabel(tag + '\nCM relative to local / remote rail (mV)')
        axes[row, 1].set_ylabel('Measured conduction current (mA)')
        for ax in axes[row]:
            ax.axvline(4.1, color='#888', lw=.6); ax.set_xlabel('Time (ns)'); ax.grid(alpha=.2)
    axes[0, 0].legend(fontsize=7); axes[0, 1].legend(fontsize=7)
    fig.suptitle('Output coupling initial state changes where DC tail current comes from')
    fig.supxlabel('Same clean input / shared real bias, current driver; 10 nF per leg. DC initialization is an analysis boundary, not a demonstrated physical startup.', fontsize=9)
    return fig


def audit_plot(data):
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8), layout='constrained')
    processes = ('tt', 'ss', 'ff', 'sf', 'fs'); columns = [(v, t) for v in (1.65, 1.8, 1.95) for t in (-40, 27, 85)]
    grid = np.full((5, 9), np.nan)
    for r in data['audited_current']['rows']:
        c = Condition.parse(r['condition'])
        grid[processes.index(c.process), columns.index((c.supply, c.temp))] = max(b['current_peak_abs_a'] for b in r['branches']) * 1000
    if not np.all(np.isfinite(grid)): raise ValueError('audit heatmap grid incomplete')
    for ax, values, title, fmt in ((axes[0], grid, 'Peak local R conduction estimate (mA)', '.2f'),
                                    (axes[1], np.ceil(grid * 1000 / 285), 'Equal-sharing count at preferred 100 uA/um', '.0f')):
        im = ax.imshow(values, cmap='Blues', aspect='auto')
        for (i, j), value in np.ndenumerate(values): ax.text(j, i, format(value, fmt), ha='center', va='center', fontsize=8)
        ax.set_yticks(range(5), [p.upper() for p in processes]); ax.set_xticks(range(9), [f'{v:g}V\n{t}C' for v, t in columns], rotation=25)
        ax.set_title(title, fontsize=11); fig.colorbar(im, ax=ax, shrink=.8)
    fig.suptitle('Historical full TX 45: finite 8-120 ns charge-state records')
    fig.supxlabel('Generic-R voltage conversion, including low-drop extrapolation. These counts do not cover the measured warm-state current or qualify a fixed-R implementation.', fontsize=9)
    return fig


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--summary', type=Path, required=True); a = p.parse_args()
    summary = a.summary.resolve(); data, waveforms = collect(summary)
    dest = summary.parent / 'publication_sources' / sha(HERE); dest.mkdir(parents=True, exist_ok=True)
    if not (dest / HERE.name).exists(): shutil.copyfile(HERE, dest / HERE.name)
    figure = ROOT / 'docs/figures/tx/output_driver/tx_coupling_state.png'
    audit_figure = figure.with_name('tx_termination_current_finite.png')
    paired_plot(data, waveforms).savefig(figure, dpi=170, bbox_inches='tight', pad_inches=.15)
    audit_plot(data).savefig(audit_figure, dpi=170, bbox_inches='tight', pad_inches=.15); plt.close('all')
    data['figures'] = {str(p.relative_to(ROOT)): sha(p) for p in (figure, audit_figure)}
    output = ROOT / 'docs/data/tx_coupling_state.json'; dump(output, data)
    dump(ROOT / 'results/catalog/tx_coupling_state.json', dict(data=str(output.relative_to(ROOT)), data_sha256=sha(output),
         summary=data['summary'], summary_sha256=data['summary_sha256'], figures=data['figures'], failures=data['failures'], scope=data['scope']))
    print(output)
    print('local clean-input failures', data['failures'])


if __name__ == '__main__': main()
