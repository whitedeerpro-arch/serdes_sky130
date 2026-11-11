"""Screen existing TX PVT records for joint-DC relative timing changes.

Not an AC PSRR measurement, setup/hold qualification or independent-rail Kd.
Only same-bit, unique events are compared. No simulator is launched.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, serial, spice, waves
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

SOURCE = ROOT / 'docs/data/tx_full_pvt45.json'
COLLECTOR = ROOT / 'verification/plotting/tx_parallel_serializer.py'
UI = 250e-12


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def analyse(row, collector):
    camp = ROOT / row['run']
    if sha(camp / 'summary.json') != row['summary_sha256']:
        raise ValueError('full-PVT source summary changed')
    case = collector.collect(camp)
    if (any(case[k] is not True for k in ('input_boundary_ok', 'halfword_hold_ok', 'behavioral_tags_align'))
            or not case['counter']['counting'] or not case['outputs']['serializer']['mapping']['in_order']):
        raise ValueError('word interface, counter or mapping invalid')
    plan = json.loads((camp / 'plan.json').read_text())
    summary = json.loads((camp / 'summary.json').read_text())
    raw = ROOT / case['waveform']
    w = spice.Waves(raw)
    bits = np.array([(r['word'] >> i) & 1 for r in summary['captures']
                     if r['payload_valid'] for i in range(16)], dtype=np.int8)
    seq = serial.Sequence(bits, case['sequence_start_s'], UI)
    metrics, detail = serial.check(w.t, w['qp'] - w['qn'], seq, plan['payload_bits'])
    actual = {int(k): seq.start_s + (k + metrics['training_delay_ui'] + e) * UI
              for k, e in zip(detail['payload_transition_bits'], detail['edge_residual_ui'])}
    c1 = w['c1gp'] - w['c1gn']
    c2 = w['c2gp'] - w['c2gn']
    phase = clock.relative_phase(w.t, c2, c1, ref_polarity=-1, polarity=-1, start=44e-9, stop=90e-9)
    # Exclude the first 1 ns so the preceding reference is inside the window.
    falls = clock.edges(w.t, c1, -1, start=44e-9, stop=90e-9)
    phase = phase[-45:]
    if len(phase) != 45 or len(falls) < 45 or not np.allclose(np.diff(falls[-45:]), 1e-9, atol=5e-12, rtol=0):
        raise ValueError('unexpected clock frequency or observation coverage')
    prefix = 'xtx.xtree.xr4_0.'
    close = {b: clock.edges(w.t, w[prefix + 's' + b + 'p'] - w[prefix + 's' + b + 'n'], sign)
             for b, sign in [('a', -1), ('b', 1)]}
    g3 = {b: waves.crossings(w.t, w[f'xtx.xtree.g3_{i}p'] - w[f'xtx.xtree.g3_{i}n'])
          for i, b in enumerate(('a', 'b'))}
    events = []
    for k, output in actual.items():
        branch = 'a' if k % 2 == 0 else 'b'
        event = dict(bit=k, branch=branch, value=int(bits[k]), new_input=bool(bits[k] != bits[k - 2]),
                     serializer_crossing_s=float(output), status='ungraded')
        if not event['new_input']:
            event['status'] = 'reused_value_no_new_g3_crossing'
            events.append(event)
            continue
        candidates = close[branch][(close[branch] < output) & (close[branch] > output - UI)]
        event['close_candidates'] = len(candidates)
        if len(candidates) == 1:
            ct = float(candidates[0])
            ts, polarity = g3[branch]
            # G3 even/odd update together; the odd slot closes one UI later.
            # Its new data can precede closure by >250 ps (observed ~367 ps).
            # Keep one same-branch 500 ps data interval before closure plus
            # 250 ps after it; never choose a nearest hit when ambiguous.
            hits = ts[(polarity == 2 * bits[k] - 1) & (ts >= ct - 2 * UI) & (ts <= ct + UI)]
            event.update(close_s=ct, g3_candidates=len(hits))
            if len(hits) == 1:
                event.update(status='unique_recorded_event', g3_crossing_s=float(hits[0]),
                             close_minus_g3_s=float(ct - hits[0]))
        events.append(event)
    return dict(condition=row['condition'], campaign=row['run'], raw=case['waveform'], hashes=case['hashes'],
                bits_sha256=hashlib.sha256(bits.tobytes()).hexdigest(),
                clock_phase=dict(definition='c1g falling minus preceding c2g falling',
                    median_s=float(np.median(phase)), pp_s=float(np.ptp(phase)), samples=len(phase),
                    phase_is_modulo_500ps=True, absolute_epoch_qualified=False), events=events)


def calculate():
    spec = importlib.util.spec_from_file_location('tx_relative_collector', COLLECTOR)
    collector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(collector)
    source = json.loads(SOURCE.read_text())
    if (source['campaign'] != 'results/analog/tx/full_pvt45/20261107T200334Z'
            or source['clock'] != [5, 16, 240] or len(source['rows']) != 45):
        raise ValueError('unexpected source revision or grid')
    rows = []
    for row in source['rows']:
        if row['status'] != 'done' or not row['grade']['gates_pass']:
            raise ValueError('source qualification incomplete')
        result = analyse(row, collector)
        rows.append(result)
        print(row['condition'], 'events', len(result['events']), 'qualified',
              sum(e['status'] == 'unique_recorded_event' for e in result['events']), flush=True)
    if len({r['bits_sha256'] for r in rows}) != 1:
        raise ValueError('different bit sequences cannot be compared by event number')
    grouped = {}
    for row in rows:
        c = Condition.parse(row['condition'])
        grouped.setdefault(f'{c.process}_t{c.temp}', []).append((c.supply, row))
    groups = {}
    for tag, trio in grouped.items():
        trio.sort(key=lambda x: x[0])
        voltages = np.array([v for v, r in trio])
        if not np.allclose(voltages, [1.65, 1.8, 1.95]):
            raise ValueError('voltage triplet incomplete')
        maps = [{e['bit']: e for e in r['events'] if e['status'] == 'unique_recorded_event'} for v, r in trio]
        common = set.intersection(*(set(m) for m in maps))
        events = []
        for bit in sorted(common):
            pairs = [m[bit] for m in maps]
            if len({(e['branch'], e['value']) for e in pairs}) != 1:
                raise ValueError('event branch or target differs')
            delay = np.array([e['close_minus_g3_s'] for e in pairs])
            slopes = np.diff(delay) / np.diff(voltages)
            events.append(dict(bit=bit, branch=pairs[0]['branch'], value=pairs[0]['value'],
                close_minus_g3_ps=(delay * 1e12).tolist(), adjacent_ps_per_mv=(slopes * 1e9).tolist(),
                span_ps_per_mv=float((delay[-1] - delay[0]) / (voltages[-1] - voltages[0]) * 1e9)))
        if not events:
            raise ValueError('no common uniquely matched new-input event')
        med = np.array([r['clock_phase']['median_s'] for v, r in trio])
        phase_ok = bool(np.all(np.abs(np.diff(med)) < 250e-12) and np.all((med > 100e-12) & (med < 400e-12)))
        worst = max(events, key=lambda e: max(abs(x) for x in e['adjacent_ps_per_mv']))
        groups[tag] = dict(conditions=[r['condition'] for v, r in trio], voltages_v=voltages.tolist(),
            common_new_events=len(events), matched_events=events, worst_absolute_adjacent_event=worst,
            clock_phase_median_ps=(med * 1e12).tolist(),
            clock_phase_adjacent_ps_per_mv=(np.diff(med) / np.diff(voltages) * 1e9).tolist() if phase_ok else None,
            clock_phase_static_comparison_only=phase_ok, absolute_epoch_qualified=False)
    return dict(status='45_record_joint_DC_timing_screen; not_AC_PSRR_or_setup_hold',
        source=str(SOURCE.relative_to(ROOT)), source_sha256=sha(SOURCE), rows=rows, groups=groups,
        method='Same-bit serializer transition identifies its preceding unique local close within 250 ps. New G3 target-polarity crossing must be unique in [close−500 ps, close+250 ps]; odd data can arrive over 250 ps before close. A/B are even/odd slots; values reused from bit k−2 are not assigned a new G3 edge. Clock phase is modulo 500 ps, screened away from wrap boundaries but without absolute event-index qualification.',
        scope='Ideal 2GHz full TX, extra5 WT16/R400 + out WT16/R240, pre120/WT60/out192, real bias/PDK R tt; initialized counter, replayed RTL controls. Three supplies also change bias, input levels/common mode and load operating points. Same-bit new transitions and two polarities only; reused/ambiguous events retained separately. No setup/hold, noise, native PLL or fixed-quiet independent-rail qualification.')


def main():
    result = calculate()
    out = ROOT / 'results/verification/tx_relative_timing_screen' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True)
    shutil.copyfile(__file__, out / 'runner.py')
    result.update(analysis=str((out / 'summary.json').relative_to(ROOT)), script_sha256=sha(Path(__file__)),
                  measurement_sources_sha256={str(p.relative_to(ROOT)): sha(p) for p in
                      (COLLECTOR, ROOT / 'src/serdes_flow/clock.py', ROOT / 'src/serdes_flow/waves.py',
                       ROOT / 'src/serdes_flow/serial.py', ROOT / 'src/serdes_flow/spice.py')})
    body = json.dumps(result, indent=2, allow_nan=False) + '\n'
    (out / 'summary.json').write_text(body)
    data = ROOT / 'docs/data/tx_relative_timing_screen.json'
    data.write_text(body)
    groups = sorted(result['groups'].items())
    fig, axes = plt.subplots(2, 1, figsize=(11.5, 6.5), layout='constrained')
    for direction, marker in [(0, 'o'), (1, 's')]:
        vals = [max(abs(e['adjacent_ps_per_mv'][direction]) for e in g['matched_events']) for tag, g in groups]
        axes[0].plot(range(len(groups)), vals, marker, label=('1.65 → 1.80 V', '1.80 → 1.95 V')[direction])
        vals = [g['clock_phase_adjacent_ps_per_mv'][direction] if g['clock_phase_adjacent_ps_per_mv'] is not None else np.nan
                for tag, g in groups]
        axes[1].plot(range(len(groups)), vals, marker, label=('1.65 → 1.80 V', '1.80 → 1.95 V')[direction])
    axes[0].set(ylabel='Largest same-bit change (ps/mV)', title='Final latch close minus new g3 crossing: joint-DC screen')
    axes[1].set(ylabel='Clock interval change (ps/mV)', title='c1g falling minus preceding c2g falling, modulo 500 ps')
    for ax in axes:
        ax.set_xticks(range(len(groups)), [t.upper().replace('_T', '\n') + '°C' for t, g in groups], fontsize=8)
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.supxlabel('Existing 45 ideal-clock records. VDD, bias, source levels and load operating points co-vary; not a measured ripple response or setup/hold margin.', fontsize=8)
    figure = ROOT / 'docs/figures/tx/ingress/tx_relative_timing_screen.png'
    fig.savefig(figure, dpi=170)
    plt.close(fig)
    index = dict(data=str(data.relative_to(ROOT)), data_sha256=sha(data), figure=str(figure.relative_to(ROOT)),
                 figure_sha256=sha(figure), analysis=result['analysis'], analysis_sha256=sha(out / 'summary.json'), status=result['status'])
    (ROOT / 'results/catalog/tx_relative_timing_screen.json').write_text(json.dumps(index, indent=2) + '\n')
    print('RESULT', result['analysis'], flush=True)
    for tag, g in groups:
        print(tag, 'common events', g['common_new_events'], 'worst', g['worst_absolute_adjacent_event'], flush=True)


if __name__ == '__main__':
    main()
