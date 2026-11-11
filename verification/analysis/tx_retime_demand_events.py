"""Passive final-rank event diagnosis from two archived full-TX waveforms.

The latch branches A/B refer to even/odd serializer slots, not input halfwords.
All times are measured observations, not setup/hold or pass qualification.
"""
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
from serdes_flow import serial, spice, waves
from serdes_flow.project import ROOT

COLLECTOR = ROOT / 'verification/plotting/tx_parallel_serializer.py'
CAMPAIGNS = (
    ROOT / 'results/analog/tx/parallel_serializer/20261110T174242.179572Z_3bc4c61d',
    ROOT / 'results/analog/tx/parallel_serializer/20261110T174428.362201Z_104eee55',
)
OUTPUT = ROOT / 'docs/data/tx_retime_demand_events.json'
WINDOW = 250e-12


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def load_collector():
    spec = importlib.util.spec_from_file_location('event_full_collector', COLLECTOR)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def crossing_map(details, metrics, seq):
    return {int(k): float(seq.start_s + (k + metrics['training_delay_ui'] + residual) * seq.ui_s)
            for k, residual in zip(details['payload_transition_bits'], details['edge_residual_ui'])}


def analyse(camp, collector):
    case = collector.collect(camp)
    if (any(case[k] is not True for k in ('input_boundary_ok', 'halfword_hold_ok', 'behavioral_tags_align'))
            or case['counter']['counting'] is not True):
        raise ValueError('source word interface or counter failed')
    plan = json.loads((camp / 'plan.json').read_text())
    summary = json.loads((camp / 'summary.json').read_text())
    bits = np.array([(r['word'] >> i) & 1 for r in summary['captures']
                     if r['payload_valid'] for i in range(16)], dtype=int)
    seq = serial.Sequence(bits, case['sequence_start_s'], 250e-12)
    w = spice.Waves(ROOT / case['waveform'])
    diagnostics = {}
    selected = {}
    for label, p, n in (('serializer','qp','qn'), ('pad','lqp','lqn')):
        metrics, detail = serial.check(w.t, w[p] - w[n], seq, plan['payload_bits'])
        if not collector.equal(metrics, case['outputs'][label]['check']):
            raise ValueError(f'{label}: metrics differ from validated full source')
        offsets = np.asarray(detail['edge_residual_ui'])
        if not len(offsets): raise ValueError('no matched payload transitions')
        first, end = serial.TRAINING_BITS, serial.TRAINING_BITS + plan['payload_bits']
        samples = np.asarray(detail['sample_voltage_v'])
        signed = samples[first:end] * (2 * bits[first:end] - 1)
        ks = np.asarray(detail['payload_transition_bits'])
        chosen = {'minimum_center': int(first + np.argmin(signed)),
                  'earliest_edge': int(ks[np.argmin(offsets)]),
                  'latest_edge': int(ks[np.argmax(offsets)])}
        diagnostics[label] = {'metrics': metrics, 'selected_bits': chosen}
        selected[label] = (metrics, detail, crossing_map(detail, metrics, seq))
    pfx = 'xtx.xtree.xr4_0.'
    diff = {
        'g3_a': w['xtx.xtree.g3_0p'] - w['xtx.xtree.g3_0n'],
        'g3_b': w['xtx.xtree.g3_1p'] - w['xtx.xtree.g3_1n'],
        'held_a': w[pfx+'ahp'] - w[pfx+'ahn'], 'held_b': w[pfx+'bhp'] - w[pfx+'bhn'],
        'clock_a': w[pfx+'sap'] - w[pfx+'san'], 'clock_b': w[pfx+'sbp'] - w[pfx+'sbn'],
    }
    edges = {name: waves.crossings(w.t, v) for name, v in diff.items()}
    serializer_cross = selected['serializer'][2]
    pad_cross = selected['pad'][2]
    events = []
    for out, d in diagnostics.items():
        for extreme, k in d['selected_bits'].items():
            branch = 'a' if k % 2 == 0 else 'b'
            wanted = int(2 * bits[k] - 1)
            event = {'output':out, 'extreme':extreme, 'bit':k, 'payload_bit':k-serial.TRAINING_BITS,
                     'slot':k%16, 'value':int(bits[k]), 'previous_same_branch_value':int(bits[k-2]),
                     'branch':branch.upper(), 'new_branch_input':bool(bits[k] != bits[k-2]),
                     'serializer_crossing_s':serializer_cross.get(k), 'pad_crossing_s':pad_cross.get(k),
                     'center_sample_time_s':selected[out][1]['sample_time_s'][k],
                     'signed_center_mv':float(selected[out][1]['sample_voltage_v'][k] * wanted * 1000),
                     'status':'ungraded', 'reason':None}
            output_t = serializer_cross.get(k)
            if output_t is None:
                event['reason'] = 'no serializer transition for this center bit'
                events.append(event); continue
            close_t, close_pol = edges['clock_'+branch]
            needed = -1 if branch == 'a' else 1
            nearby = close_t[(close_pol == needed) & (close_t <= output_t) & (close_t >= output_t-WINDOW)]
            if len(nearby) != 1:
                event.update(reason='expected one branch closing edge in preceding 250 ps', close_candidates=int(len(nearby)))
                events.append(event); continue
            close = float(nearby[0])
            clk = diff['clock_'+branch]
            slope = float((np.interp(close+5e-12,w.t,clk)-np.interp(close-5e-12,w.t,clk))/.01)
            # Record selection sign at the crossing preceding this output; an
            # unexpected state is not silently treated as an applicable latch.
            sp = w['c2gp'] - w['c2gn']
            output_state = float(np.interp(output_t, w.t, sp))
            if (branch == 'a' and output_state >= 0) or (branch == 'b' and output_state <= 0):
                event.update(reason='selected clock polarity at output disagrees with slot branch', close_s=close,
                             c2g_at_serializer_crossing_mv=output_state*1000)
                events.append(event);continue
            event.update(close_s=close, serializer_minus_close_ps=(output_t-close)*1e12,
                         c2g_at_serializer_crossing_mv=output_state*1000,
                         local_clock_slope_v_per_ns=slope, reason=None, status='observed')
            g3 = diff['g3_'+branch]
            event['g3_signed_at_close_mv'] = float(np.interp(close,w.t,g3)*wanted*1000)
            for kind in ('g3','held'):
                if kind == 'g3' and not event['new_branch_input']:
                    event.update(g3_target_crossing_s=None, close_minus_g3_ps=None,
                                 g3_status='held_from_previous_same_branch_bit')
                    continue
                times, pol = edges[kind+'_'+branch]
                hits = times[(pol == wanted) & (times >= close-WINDOW) & (times <= close+WINDOW)]
                event[kind+'_crossing_candidates'] = int(len(hits))
                event[kind+'_target_crossing_s'] = float(hits[0]) if len(hits)==1 else None
                event[kind+'_status'] = 'unique' if len(hits)==1 else 'ungraded_not_unique'
                if kind == 'g3':
                    event['close_minus_g3_ps'] = float((close-hits[0])*1e12) if len(hits)==1 else None
            g = event.get('g3_target_crossing_s'); h = event.get('held_target_crossing_s')
            event['g3_to_held_ps'] = float((h-g)*1e12) if g is not None and h is not None else None
            events.append(event)
    return {'condition':case['condition'], 'campaign':case['campaign'], 'hashes':case['hashes'],
            'sequence_start_s':seq.start_s, 'payload_bits':plan['payload_bits'],
            'source_metrics_and_extremes':diagnostics, 'events':events}


def calculate():
    collector = load_collector()
    result = {'scope':'Passive recorded ideal-clock full-TX event measurements, not setup/hold, PVT, startup or qualification.',
              'method':'Branch A/B corresponds to even/odd bits. Find unique A falling or B rising local clock crossing in preceding 250 ps of same-bit serializer transition; input and held target crossings within close ±250 ps must be unique. G3 is a new event only when bit[k] differs from bit[k-2]. Local clock slope uses 10 ps centered aperture.',
              'analysis_sources':{str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__).resolve(),COLLECTOR,ROOT/'src/serdes_flow/serial.py',ROOT/'src/serdes_flow/waves.py')},
              'cases':[analyse(c,collector) for c in CAMPAIGNS]}
    return result


def main():
    result = calculate()
    OUTPUT.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    for c in result['cases']:
        for e in c['events']:
            print(c['condition'],e['output'],e['extreme'],'bit',e['bit'],'branch',e['branch'],
                  'new',e['new_branch_input'],'status',e['status'],'reason',e['reason'],
                  'close-g3 ps',e.get('close_minus_g3_ps'), 'g3-held ps',e.get('g3_to_held_ps'))


if __name__ == '__main__':
    main()
