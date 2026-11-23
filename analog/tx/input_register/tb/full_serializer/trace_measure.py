"""Passively inspect calibrated full-TX internal traces; never infer missing bits."""
import argparse
import hashlib
import shutil
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    camp = args.campaign.resolve()
    plan = json.loads((camp / 'plan.json').read_text())
    trace_summary = json.loads((camp / 'summary.json').read_text())
    source = ROOT / plan['source_campaign']
    for file, key in ((source / 'plan.json', 'source_plan_sha256'),
                      (source / 'summary.json', 'source_summary_sha256'),
                      (ROOT / plan['source_waveform'], 'source_waveform_sha256')):
        if digest(file) != plan[key]:
            raise ValueError(f'source hash mismatch: {file}')
    for rel, expected in plan['snapshot_files'].items():
        if digest(camp / rel) != expected:
            raise ValueError(f'checkpoint hash mismatch: {rel}')
    summary = json.loads((source / 'summary.json').read_text())
    rows = [r for r in summary['captures'] if r['payload_valid']]
    bits = [(r['word'] >> lane) & 1 for r in rows for lane in range(16)]
    start = summary['sequence_start_s']
    path = spice.case_output(camp, 'run', 'waveforms.raw', plan['stop_s'])
    if not path:
        raise ValueError('missing or truncated trace')
    if path.resolve() != (ROOT / trace_summary['waveform']).resolve() or digest(path) != trace_summary['waveform_sha256']:
        raise ValueError('trace waveform identity mismatch')
    execution=json.loads((path.parent/'execution.json').read_text())
    if (execution['exit_code'] != 0 or execution['timed_out'] or execution['log_failures']
            or digest(path.parent/'tb.cir') != execution['deck_sha256']
            or execution['deck_sha256'] != digest(camp/'execution/physical_tb.cir')):
        raise ValueError('failed or altered trace execution')
    w = spice.Waves(path)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, output / 'trace_measure.py')
    pairs = [('lane0', 'xtx.p0', 'xtx.n0'), ('lane8', 'xtx.p8', 'xtx.n8'),
             ('g1_0', 'xtx.xtree.g1_0p', 'xtx.xtree.g1_0n'),
             ('g2_0', 'xtx.xtree.g2_0p', 'xtx.xtree.g2_0n'),
             ('g3_0', 'xtx.xtree.g3_0p', 'xtx.xtree.g3_0n'),
             ('held_A', 'xtx.xtree.xr4_0.ahp', 'xtx.xtree.xr4_0.ahn'),
             ('held_B', 'xtx.xtree.xr4_0.bhp', 'xtx.xtree.xr4_0.bhn'),
             ('output', 'qp', 'qn'),
             *[(name, name+'p', name+'n') for name in ('c250', 'c500', 'c1g', 'c2g')],
             ('r1_select', 'xtx.xtree.xr1_0.slp', 'xtx.xtree.xr1_0.sln'),
             ('final_A_select', 'xtx.xtree.xr4_0.sap', 'xtx.xtree.xr4_0.san'),
             ('final_B_select', 'xtx.xtree.xr4_0.sbp', 'xtx.xtree.xr4_0.sbn')]
    falls = clock.edges(w.t, w['c250p'] - w['c250n'], -1)
    rises = clock.edges(w.t, w['c250p'] - w['c250n'], 1)
    delay_ui = summary['outputs']['serializer']['check']['training_delay_ui']
    result = dict(condition=plan['condition'], calibration=trace_summary['calibration'],
                  sequence_start_s=start, training_delay_ui=delay_ui, waveform=str(path), observations={},
                  hashes=dict(trace_plan=digest(camp / 'plan.json'), trace_summary=digest(camp / 'summary.json'),
                              trace_raw=digest(path), source_plan=plan['source_plan_sha256'],
                              source_summary=plan['source_summary_sha256'], source_raw=plan['source_waveform_sha256'],
                              helper=digest(Path(__file__))),
                  interpretation='Passive crossings only; same-time ranks carry different bits. No causal or pass/fail claim.')
    for bit in (48, 104, 232):
        nominal = start + (bit + 0.5) * 250e-12
        center = nominal + delay_ui * 250e-12
        word_index = bit // 16
        if bit >= len(bits) or word_index >= len(rows):
            result['observations'][str(bit)] = {'covered': False, 'actual_output_sample_center_s': center}
            continue
        # First A fall after the capture, then first B rise after that fall.
        a_candidates = falls[falls >= rows[word_index]['capture_s']]
        if not len(a_candidates):
            result['observations'][str(bit)] = {'covered': False, 'reason': 'A edge absent'}
            continue
        a_edge = a_candidates[0]
        b_candidates = rises[rises > a_edge]
        if not len(b_candidates):
            result['observations'][str(bit)] = {'covered': False, 'reason': 'B edge absent'}
            continue
        edge = a_edge if bit % 16 < 8 else b_candidates[0]
        lo, hi = min(edge - .5e-9, center - .1e-9), max(edge + 1.5e-9, center + .1e-9)
        if lo < w.t[0] or hi > w.t[-1]:
            result['observations'][str(bit)] = {'covered': False, 'actual_output_sample_center_s': center}
            continue
        mask = (w.t >= lo) & (w.t <= hi)
        item = dict(covered=True, nominal_input_center_s=nominal, actual_output_sample_center_s=center,
                    reference_c250_s=float(edge), reference_selection='A_fall' if bit % 16 < 8 else 'B_rise',
                    expected_bit=bits[bit], source_word=rows[word_index]['word'],
                    lane0=bits[word_index*16], lane8=bits[word_index*16+8], crossings={}, node_voltages={})
        for node in ('xtx.xtree.xr1_0.slp', 'xtx.xtree.xr1_0.sln', 'xtx.xtree.xr1_0.tail',
                     'xtx.xtree.xr1_0.ta', 'xtx.xtree.xr1_0.tb', 'vbias', 'vgi_bias', 'xtx.xtree.vbias_logic',
                     'xtx.xtree.xr4_0.sap', 'xtx.xtree.xr4_0.san', 'xtx.xtree.xr4_0.sbp', 'xtx.xtree.xr4_0.sbn'):
            v = w[node]
            item['node_voltages'][node] = dict(min_v=float(np.min(v[mask])), max_v=float(np.max(v[mask])),
                                                at_c250_edge_v=float(np.interp(edge, w.t, v)))
        fig, axes = plt.subplots(len(pairs), 1, figsize=(11, 16), sharex=True, constrained_layout=True)
        for ax, (label, p, n) in zip(axes, pairs):
            v = w[p] - w[n]
            times, directions = crossings(w.t[mask], v[mask])
            item['crossings'][label] = [dict(offset_ps=float((t-edge)*1e12), direction=int(d)) for t, d in zip(times, directions)]
            ax.plot((w.t[mask]-edge)*1e12, v[mask], lw=.8)
            ax.axhline(0, color='gray', lw=.4)
            ax.axvline(0, color='black', lw=.5)
            ax.axvline((nominal-edge)*1e12, color='blue', lw=.6)
            ax.axvline((center-edge)*1e12, color='red', lw=.6)
            ax.set_ylabel(label, rotation=0, ha='right', fontsize=7)
            ax.tick_params(labelsize=7)
        axes[-1].set_xlabel('ps relative to selected actual c250 edge; blue = nominal input center; red = fixed-training-delay output sample center')
        fig.suptitle(f"{plan['condition']} bit {bit}, word 0x{rows[word_index]['word']:04x}, lanes 0/8={item['lane0']}/{item['lane8']}\ncalibration passed: {trace_summary['calibration']['passed']}", fontsize=9)
        fig.savefig(output / f'bit_{bit}.png', dpi=140)
        plt.close(fig)
        result['observations'][str(bit)] = item
    (output / 'observations.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(output)


if __name__ == '__main__':
    main()
