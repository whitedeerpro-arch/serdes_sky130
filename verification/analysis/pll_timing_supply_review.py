"""Read-only cross-check of host timing measurements and explicit jitter units.

No ngspice launch, fitted loop replacement, new acceptance limit or DUT change.
Raw timing is remeasured with the shared clock library. PFD/CP balance and PLL
tolerance are reused published calculations, explicitly distinguished below.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HOST = [ROOT / 'results/analog/pll/top/host_timing' / s
        for s in ('20261111T061902Z', '20261111T091746Z')]
PFD = ROOT / 'results/analog/pll/top/host_timing_pfd_cp/20261111T090715Z/summary.json'
TOL = ROOT / 'results/analog/pll/top/ldo_supply_tolerance/20261111T102959Z/summary.json'
ALT = ROOT / 'results/analog/pll/top/ldo_supply_tolerance/20261111T103001Z/summary.json'
REPLICA = ROOT / 'results/analog/pll/top/host_timing_ref_replica/20261111T105327Z'
BALANCED = ROOT / 'results/analog/pll/top/host_timing_balanced/20261111T114417Z_cl170/summary.json'
BALANCED_TOL = ROOT / 'results/analog/pll/top/ldo_supply_tolerance/20261111T114419Z/summary.json'
UI = 250e-12


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_run(raw, vh, stop):
    w = spice.Waves(raw)
    t = w.t
    start = stop / 2
    vco = w['v(xfe.v0p)'] - w['v(xfe.v0n)']
    rises = clock.edges(t, vco, start=start)
    if len(rises) < 8:
        raise ValueError('too few VCO edges')
    result = dict(T=float(np.median(np.diff(rises))), n_vco=len(rises))
    signals = dict(pre=w['v(fb0)'] - vh / 2, ck=w['v(cm0p)'] - vh / 2)
    if 'v(d08p)' in w.names:
        signals['d08'] = w['v(d08p)'] - w['v(d08n)']
    for name, signal in signals.items():
        delays = clock.relative_phase(t, vco, signal, start=start, stop=stop)
        if len(delays):
            result[name] = dict(median_s=float(np.median(delays)), std_s=float(np.std(delays)),
                                edges=len(delays), event_index_qualified=False)
    return result


def unwrap(x, base, period):
    return float(base + (x - base + period / 2) % period - period / 2)


def replica_review(host):
    published = json.loads((REPLICA / 'summary.json').read_text())
    args = published['args']
    cls = [float(x) for x in args['cl'].split(',')]
    rows = {}
    for tag, old in published['rows'].items():
        measured = {}
        supply = Condition.parse(tag.split(':')[0]).supply
        for name, dh in [('base', 0), ('hp', args['dh']), ('hm', -args['dh']), ('bp', 0), ('bm', 0)]:
            raw = spice.case_output(REPLICA / tag.replace(':', '_'), 'run', name + '.raw', args['stop'])
            if raw is None:
                raise ValueError('replica raw incomplete')
            execution = raw.parent / 'execution.json'
            if json.loads(execution.read_text())['deck_sha256'] != sha(raw.parent / 'tb.cir'):
                raise ValueError('replica execution deck differs')
            w = spice.Waves(raw)
            medians, counts = [], []
            ref = w['v(refp)'] - (supply + dh) / 2
            for k in range(len(cls)):
                d = clock.relative_phase(w.t, ref, w[f'v(o{k})'] - (supply + dh) / 2,
                                         start=args['stop'] / 2, stop=args['stop'])
                d = d[d < 3e-9]
                if len(d) < 2:
                    raise ValueError('too few replica events')
                medians.append(float(np.median(d)))
                counts.append(len(d))
            measured[name] = dict(delay_s=medians, edge_counts=counts, raw=str(raw.relative_to(ROOT)),
                                  raw_sha256=sha(raw), execution_sha256=sha(execution), deck_sha256=sha(raw.parent / 'tb.cir'))
        kh = (np.array(measured['hp']['delay_s']) - measured['hm']['delay_s']) / (2 * args['dh'])
        kb = (np.array(measured['bp']['delay_s']) - measured['bm']['delay_s']) / (2 * args['db'])
        for actual, expected in [(kh, old['kd_ref_h']), (kb, old['kd_ref_b']), (measured['base']['delay_s'], old['delay_s'])]:
            if not np.allclose(actual, expected, rtol=1e-9, atol=1e-18):
                raise ValueError('replica publication differs from raw remeasurement')
        h = host[tag]['derived']
        pf = host[tag]['pfd_balance_summary_k_s_per_v']
        cases = []
        for k, cl in enumerate(cls):
            residual = kh[k] - h['pre_h']['s_per_v']
            cases.append(dict(cl_per_side_f=cl, delay_s=measured['base']['delay_s'][k],
                kd_ref_host_s_per_v=float(kh[k]), kd_ref_bias_s_per_v=float(kb[k]),
                reference_minus_feedback_host_s_per_v=float(residual),
                comparison_host_including_PFD_s_per_v=float(residual + pf) if pf is not None else None,
                reference_minus_feedback_bias_s_per_v=float(kb[k] - h['pre_b']['s_per_v']),
                nominal_delay_added_vs_CL0_s=measured['base']['delay_s'][k] - measured['base']['delay_s'][0]))
        rows[tag] = dict(measurements=measured, cases=cases)
    return dict(campaign=str(REPLICA.relative_to(ROOT)), summary_sha256=sha(REPLICA / 'summary.json'),
                args=args, rows=rows, scope='Independent replica raw crossings, central differences and deck/execution checks; no bias filtering response, full PFD/CP cancellation, loop tolerance or corner qualification inferred.')


def calculate():
    pfd, tol, alt = (json.loads(p.read_text()) for p in (PFD, TOL, ALT))
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in (PFD, TOL, ALT)}
    rows = {}
    for camp in HOST:
        summary = camp / 'summary.json'
        inputs[str(summary.relative_to(ROOT))] = sha(summary)
        published = json.loads(summary.read_text())
        args = published['args']
        for tag, row in published['rows'].items():
            c = Condition.parse(tag.split(':')[0])
            remeasured = {}
            for name, dh in [('base', 0), ('hp', args['dh']), ('hm', -args['dh']), ('bp', 0), ('bm', 0)]:
                raw = spice.case_output(camp / tag.replace(':', '_'), 'run', name + '.raw', args['stop'])
                if raw is None:
                    raise ValueError(f'{tag}/{name}: incomplete or unsuccessful raw')
                ex = json.loads((raw.parent / 'execution.json').read_text())
                deck = raw.parent / 'tb.cir'
                if ex['deck_sha256'] != sha(deck):
                    raise ValueError('execution deck identity differs')
                measured = relative_run(raw, c.supply + dh, args['stop'])
                measured.update(raw=str(raw.relative_to(ROOT)), raw_sha256=sha(raw),
                                deck_sha256=sha(deck), execution_sha256=sha(raw.parent / 'execution.json'))
                for key in ('pre', 'ck', 'd08'):
                    if key not in measured:
                        continue
                    if name != 'base' and key not in remeasured['base']:
                        del measured[key]
                        continue
                    base = measured[key]['median_s'] if name == 'base' else remeasured['base'][key]['median_s']
                    value = unwrap(measured[key]['median_s'], base, measured['T'] if name == 'base' else remeasured['base']['T'])
                    if not np.isclose(value, row['runs'][name][key], rtol=1e-9, atol=1e-18):
                        raise ValueError(f'{tag}/{name}/{key}: published timing differs')
                    measured[key]['median_s'] = value
                remeasured[name] = measured
            derived = {}
            for key, suffix in [('pre', 'd'), ('d08', 'd8'), ('ck', 'ck')]:
                if any(key not in r for r in remeasured.values()):
                    continue
                r = {n: v[key]['median_s'] for n, v in remeasured.items()}
                for drive, plus, minus, delta in [('h', 'hp', 'hm', args['dh']), ('b', 'bp', 'bm', args['db'])]:
                    k = (r[plus] - r[minus]) / (2 * delta)
                    expected = row[f'k{suffix}_{drive}']
                    if not np.isclose(k, expected, rtol=1e-9, atol=1e-18):
                        raise ValueError('published derivative differs')
                    half_span = abs(r[plus] - r[minus]) / 2
                    curvature = (r[plus] + r[minus]) / 2 - r['base']
                    derived[f'{key}_{drive}'] = dict(s_per_v=k, ps_per_mv=k * 1e9,
                        midpoint_curvature_ps=curvature * 1e12,
                        curvature_fraction_of_half_span=abs(curvature) / half_span if half_span else None)
            pf = pfd['rows'].get(tag)
            kdpf = None if pf is None else (pf['zero_s']['hp'] - pf['zero_s']['hm']) / (2 * pfd['args']['dh'])
            if pf is not None and not np.isclose(kdpf, pf['kd_pfd'], rtol=1e-12, atol=1e-20):
                raise ValueError('PFD summary finite difference differs')
            part = derived.get('d08_h')
            total = derived['pre_h']['s_per_v']
            remainder = total - part['s_per_v'] if part else None
            rows[tag] = dict(campaign=str(camp.relative_to(ROOT)), measurements=remeasured, derived=derived,
                pfd_balance_summary_k_s_per_v=kdpf,
                receiver_segment_host_fraction=abs(remainder / total) if part and total else None,
                receiver_segment_includes_input_slew_and_common_mode=True,
                reused_model_voltage_peak_v=tol['points'].get(tag),
                reused_prescaler_only_hypothesis_v=alt['points'].get(tag))
    ss = rows['ss_v1650_t-40:hh']
    kfb = abs(ss['derived']['pre_h']['s_per_v'])
    kpfd = ss['pfd_balance_summary_k_s_per_v']
    effective = kpfd - ss['derived']['pre_h']['s_per_v']
    units = dict(tone_peak_v=.005, assumed_T_magnitude=1., assumed_bias_path=0.,
        comparison_path_s_per_v=effective,
        feedback_path_only_peak_ps=kfb * .005 * 1e12,
        feedback_path_only_pp_ui=2 * kfb * .005 / UI,
        feedback_plus_PFD_peak_ps=abs(effective) * .005 * 1e12,
        feedback_plus_PFD_pp_ui=2 * abs(effective) * .005 / UI,
        two_equal_opposed_PLL_relative_pp_ui=4 * abs(effective) * .005 / UI,
        maximum_residual_ps_per_mv_at_5mV_peak=dict(
            one_PLL_0p05UI_peak=.05 * UI / .005 * 1e9,
            one_PLL_0p05UI_pp=.05 * UI / (.005 * 2) * 1e9,
            two_equal_PLL_0p05UI_relative_pp=.05 * UI / (.005 * 4) * 1e9))
    # N multiplies phase, and cancels when radians are converted to seconds.
    dt = 10e-12
    time_from_feedback_phase = 8 * (2 * np.pi * 250e6 * dt) / (2 * np.pi * 2e9)
    if not np.isclose(dt, time_from_feedback_phase, rtol=1e-14, atol=0):
        raise ValueError('time-domain divider conversion failed')
    replicas = replica_review(rows)
    inputs[str((REPLICA / 'summary.json').relative_to(ROOT))] = replicas['summary_sha256']
    balanced, balanced_tol = (json.loads(p.read_text()) for p in (BALANCED, BALANCED_TOL))
    for tag, row in balanced['rows'].items():
        case = next(c for c in replicas['rows'][tag]['cases'] if np.isclose(c['cl_per_side_f'], 170e-15, rtol=1e-12, atol=0))
        if not (np.isclose(row['kd_h'], -case['reference_minus_feedback_host_s_per_v'], rtol=1e-9, atol=1e-18)
                and np.isclose(row['kd_b'], -case['reference_minus_feedback_bias_s_per_v'], rtol=1e-9, atol=1e-18)):
            raise ValueError('balanced model residual differs from independent raw measurements')
    for p in (BALANCED, BALANCED_TOL):
        inputs[str(p.relative_to(ROOT))] = sha(p)
    return dict(status='raw_timing_and_unit_review; no_circuit_or_specification_change',
        inputs_sha256=inputs, rows=rows, illustrative_units=units, replica=replicas,
        balanced_170_model=dict(residual_arithmetic_matches_raw=True, reused_tolerance=balanced_tol,
                               independent_loop_calculation=False),
        evidence_scope=dict(host_timing='independent raw crossing, central difference, curvature, edge counts and execution/deck checks',
            pfd_cp='published balance-point summary arithmetic only; CP charge raw not independently reintegrated here',
            tolerance='reuse of fixed published loop calculations, not independently rerun or promoted to measured supply tolerance'),
        missing=['Reference replica local card complete; full reference interface and adoption still pending',
            'Direct 1.65/1.95V uses quiet=host, unlike these fixed quiet=1.8V timing cards',
            'DC finite difference is not a measured complex response at the critical ripple frequency',
            'Only 2–4 feedback events per perturbation; modulo phase is not absolute latency or event-index proof',
            'Missing PFD points default to zero in the reused model; unmeasured host points use an envelope',
            'Output receiver and TX/RX distribution delay paths are not included in the reused tolerance',
            'Common-source coherent sum and relative TX/RX/CDR budget require closure'])


def main():
    result = calculate()
    out = ROOT / 'results/verification/pll_timing_supply_review' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'runner.py')
    result.update(analysis_path=str((out / 'summary.json').relative_to(ROOT)),
                  analysis_source_sha256=sha(Path(__file__)),
                  measurement_sources_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                      (ROOT / 'src/serdes_flow/clock.py', ROOT / 'src/serdes_flow/spice.py', ROOT / 'src/serdes_flow/waves.py')})
    body = json.dumps(result, indent=2, allow_nan=False) + '\n'
    (out / 'summary.json').write_text(body)
    data = ROOT / 'docs/data/pll_timing_supply_review.json'
    data.write_text(body)
    rows = result['rows']
    tags = list(rows)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), layout='constrained')
    for offset, key, label, color in [(-.15, 'pre_h', 'VCO to feedback', '#347d8c'),
                                      (.15, 'd08_h', 'VCO to divider output', '#ce9553')]:
        selected = [(i, r['derived'][key]['ps_per_mv']) for i, r in enumerate(rows.values()) if key in r['derived']]
        axes[0].bar([i + offset for i, v in selected], [abs(v) for i, v in selected], .28, label=label, color=color)
    axes[0].set_xticks(range(len(tags)), [s.replace(':', '\n').replace('_v', '\n') for s in tags], fontsize=7)
    for i, r in enumerate(rows.values()):
        if 'd08_h' not in r['derived']:
            axes[0].text(i + .15, .035, 'n/a', ha='center', fontsize=7, color='#777777')
    axes[0].set(ylabel='Absolute DC delay sensitivity (ps/mV)', title='Host rail: feedback path and divider segment')
    axes[0].legend(fontsize=8)
    mv = np.linspace(0, 10, 101)
    for factor, label in [(1, 'One PLL: peak'), (2, 'One PLL: peak-to-peak'), (4, 'Two equal PLLs, opposed: relative pp')]:
        axes[1].plot(mv, factor * abs(result['illustrative_units']['comparison_path_s_per_v']) * mv * 1e-3 / UI, label=label)
    axes[1].axhline(.05, ls='--', color='#955353', label='0.05 UI: three distinct interpretations')
    axes[1].set(xlabel='Host sinusoidal ripple peak (mV)', ylabel='Time error / 250 ps UI',
                title='SS cold illustrative comparison path, |T| = 1')
    axes[1].legend(fontsize=7)
    for ax in axes:
        ax.grid(axis='y', alpha=.2)
    fig.supxlabel('Fixed quiet 1.8 V; DC perturbations. Right panel excludes bias, VCO frequency and endpoint paths; not measured ripple tolerance.', fontsize=8)
    figure = ROOT / 'docs/figures/clocking/pll/core/pll_timing_supply_review.png'
    fig.savefig(figure, dpi=170)
    plt.close(fig)
    fig2, axes2 = plt.subplots(1, 2, figsize=(11.5, 4.8), layout='constrained')
    for tag, r in result['replica']['rows'].items():
        x = [c['cl_per_side_f'] * 1e15 for c in r['cases']]
        axes2[0].plot(x, [c['reference_minus_feedback_host_s_per_v'] * 1e9 for c in r['cases']], 'o-', label=tag, ms=4)
        axes2[1].plot(x, [c['reference_minus_feedback_bias_s_per_v'] * 1e9 for c in r['cases']], 'o-', ms=4)
    axes2[0].set(xlabel='Reference CML load per side (fF)', ylabel='Reference − feedback (ps/mV host)', title='Replica reduces host-rail delay mismatch')
    axes2[1].set(xlabel='Reference CML load per side (fF)', ylabel='Reference − feedback (ps/mV vbias)', title='Bias mismatch remains: separate path')
    for ax in axes2:
        ax.axhline(0, color='#888', lw=.8)
        ax.grid(alpha=.2)
    axes2[0].legend(fontsize=7)
    fig2.supxlabel('Seven local DC cards, ±20 mV host / ±5 mV bias. PFD/CP and actual bias transfer excluded here; no physical adoption or ripple-tolerance qualification.', fontsize=8)
    replica_figure = ROOT / 'docs/figures/clocking/pll/core/pll_reference_replica_review.png'
    fig2.savefig(replica_figure, dpi=170)
    plt.close(fig2)
    index = dict(data=str(data.relative_to(ROOT)), data_sha256=sha(data), figure=str(figure.relative_to(ROOT)),
                 figure_sha256=sha(figure), analysis=result['analysis_path'], analysis_sha256=sha(out / 'summary.json'),
                 replica_figure=str(replica_figure.relative_to(ROOT)), replica_figure_sha256=sha(replica_figure),
                 status=result['status'], script='verification/analysis/pll_timing_supply_review.py')
    (ROOT / 'results/catalog/pll_timing_supply_review.json').write_text(json.dumps(index, indent=2) + '\n')
    print(json.dumps(dict(points=len(rows), illustrative_units=result['illustrative_units'], analysis=result['analysis_path']), indent=2))


if __name__ == '__main__':
    main()
