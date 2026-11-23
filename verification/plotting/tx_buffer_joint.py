"""Independently verify and publish a completed joint Xe2 card; never simulate."""
import argparse
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from serdes_flow import project

ROOT = project.ROOT
RUNNER = ROOT / 'analog/tx/input_register/tb/final_clock_chain/buffer_joint_card.py'


def main(campaign, summary):
    spec = importlib.util.spec_from_file_location('joint_card', RUNNER)
    joint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(joint)
    plan = joint.check(campaign, registered=True)
    old = joint.old
    if summary.parent.parent.parent != campaign:
        raise ValueError('summary belongs to a different campaign')
    data = json.loads(summary.read_text())
    if data['status'] != 'measured' or len(data['rows']) != len(old.TAGS):
        raise ValueError('campaign incomplete or baseline failed')
    if {r['condition'] for r in data['rows']} != set(old.TAGS):
        raise ValueError('unexpected conditions')
    if data['predictions'] != plan['predictions']:
        raise ValueError('campaign prediction identity changed')
    calibration = json.loads((campaign / 'calibration.json').read_text())
    if old.digest(campaign / 'calibration.json') != plan['parent_identity']['cal_sha256']:
        raise ValueError('calibration identity changed')
    points = json.loads((joint.PARENT / 'boundary_proposal.json').read_text())['points']
    evidence, residuals = {}, {}
    for row in data['rows']:
        tag = row['condition']
        raw = old.completed(campaign, tag)
        if raw is None or str(raw.relative_to(ROOT)) != row['raw'] or old.digest(raw) != row['raw_sha256']:
            raise ValueError(f'raw or execution identity changed: {tag}')
        actual = old.measure(campaign, tag, raw, points[tag])
        for branch, (label, wt, resistance) in zip(actual.get('branches', []), plan['parameters']):
            branch.update(branch=label, wn_um=24, wt_um=float(wt), r_nominal_ohm=int(resistance))
        actual = json.loads(json.dumps(actual, default=old.json_default, allow_nan=False))
        if actual != row['result'] or not actual['baseline_matches'] or len(actual.get('branches', [])) != 3:
            raise ValueError(f'independent measurement or baseline mismatch: {tag}')
        predicted = calibration['next_joint_prediction'][tag]
        if predicted['wt_um'] != float(plan['parameters'][1][1]) or predicted['r_nominal_ohm'] != int(plan['parameters'][1][2]):
            raise ValueError('calibration prediction parameter mismatch')
        v_pred, d_pred = predicted['predicted_xe2_pp_v'], predicted['predicted_c2g_shift_s']
        observed = actual['branches'][1]
        v_obs = observed['nodes']['xe2_output']['differential_pp_v']
        d_obs = observed['clock_fall_shift_s']
        residuals[tag] = {'predicted_xe2_pp_v': v_pred, 'measured_xe2_pp_v': v_obs,
                          'xe2_residual_mv': (v_obs-v_pred)*1e3,
                          'xe2_residual_percent_of_prediction': (v_obs-v_pred)/v_pred*100,
                          'predicted_c2g_shift_s': d_pred, 'measured_c2g_shift_s': d_obs,
                          'c2g_residual_ps': (d_obs-d_pred)*1e12}
        evidence[tag] = {p.name: old.digest(p) for p in (raw, raw.parent/'execution.json', raw.parent/'tb.cir', raw.parent/'simulator.log')}
    scope = ('TT and FS hot low-voltage archived extra5 loaded slice and driver, fixed ideal recorded input, bias and supply; '
             '8-bit local window. I-17 and full TX/PVT/noise remain open; physical resistance, power and upstream impedance ungraded.')
    publication = {'scope': scope, 'campaign': str(campaign.relative_to(ROOT)), 'summary': str(summary.relative_to(ROOT)),
                   'summary_sha256': old.digest(summary), 'joint_plan_sha256': old.digest(campaign/'joint_plan.json'),
                   'plan_sha256': old.digest(campaign/'plan.json'), 'runner_sha256': old.digest(RUNNER),
                   'helper_sha256': old.digest(joint.HELPER), 'publisher_sha256': old.digest(Path(__file__)),
                   'calibration_sha256': plan['parent_identity']['cal_sha256'], 'parameters': plan['parameters'],
                   'rounded_plan_predictions': plan['predictions'], 'joint_a_prediction_residuals': residuals,
                   'evidence': evidence, 'results': data['rows'], 'ungraded': plan['ungraded']}
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), layout='constrained')
    colors = ['#176c8c', '#388c70', '#d27732']
    labels = ['baseline 16/400', 'joint A 12.8/320', 'joint B 12/320']
    for row, ax in zip(data['rows'], axes[0]):
        for i, branch in enumerate(row['result']['branches']):
            ax.bar(np.arange(3)+(i-1)*.23, [branch['nodes'][k]['differential_pp_v']*1e3 for k in ('xe2_output', 'xe3_output', 'c2g')],
                   width=.22, label=labels[i], color=colors[i])
        ax.axhspan(200, 400, color='#388c70', alpha=.08)
        ax.axhline(400, ls='--', color='#b34545'); ax.axhline(200, ls=':', color='#777')
        ax.set(xticks=range(3), xticklabels=['Xe2', 'Xe3 next stage', 'c2g'], ylabel='Differential pp (mV)', title=row['condition'])
        ax.legend(fontsize=7)
    for row, color in zip(data['rows'], ('#176c8c', '#cf4951')):
        branches = row['result']['branches']
        axes[1, 0].plot(range(3), [b['clock_fall_shift_s']*1e12 for b in branches], 'o-', color=color, label=row['condition'])
        axes[1, 1].plot(range(3), [b['metrics']['transition_spread_ui'] for b in branches], 'o-', color=color, label=row['condition'])
    axes[1, 0].set(ylabel='c2g shift from old extra5 (ps)', title='Clock propagation')
    axes[1, 1].set(ylabel='8-bit transition spread (UI)', title='Recorded phase plus measured clock shift')
    axes[1, 1].axhline(.15, ls='--', color='#b34545')
    for ax in axes[1]:
        ax.set_xticks(range(3), ['baseline', 'joint A', 'joint B']); ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle('TX I-17: loaded Xe2 joint perturbations, local replay only', fontsize=12)
    figure = ROOT/'docs/figures/tx/ingress/tx_buffer_joint.png'
    output = ROOT/'docs/data/tx_buffer_joint.json'
    catalog = ROOT/'results/catalog/tx_buffer_joint.json'
    fig.savefig(figure, dpi=160); plt.close(fig)
    output.write_text(json.dumps(publication, indent=2, allow_nan=False)+'\n')
    catalog.write_text(json.dumps({'data': str(output.relative_to(ROOT)), 'data_sha256': old.digest(output),
                                   'figure': str(figure.relative_to(ROOT)), 'figure_sha256': old.digest(figure),
                                   'campaign': publication['campaign'], 'summary': publication['summary'],
                                   'summary_sha256': publication['summary_sha256'], 'evidence': evidence, 'scope': scope}, indent=2)+'\n')
    print(json.dumps({'evidence_verified': True, 'joint_a_prediction_residuals': residuals}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--summary', type=Path, required=True)
    args = parser.parse_args()
    main(args.campaign.resolve(), args.summary.resolve())
