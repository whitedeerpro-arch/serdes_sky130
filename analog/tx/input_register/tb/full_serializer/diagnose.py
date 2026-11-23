"""Compare archived full serializer waveforms; no simulations or phase fitting."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import clock, serial, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

COLLECTOR = ROOT / 'verification/plotting/tx_parallel_serializer.py'
spec = importlib.util.spec_from_file_location('tx_parallel_collector', COLLECTOR)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def lead(t, v, edge, threshold):
    times, _ = crossings(t, v - threshold)
    before = times[(times < edge) & (times > edge - 4e-9)]
    return float((edge - before[-1]) * 1e12) if len(before) else None


def diagnose(camp):
    validated = collector.collect(camp)
    camp = Path(camp).resolve()
    plan = json.loads((camp / 'plan.json').read_text())
    summary = json.loads((camp / 'summary.json').read_text())
    w = spice.Waves(ROOT / validated['waveform'])
    rows = [r for r in summary['captures'] if r['payload_valid']]
    bits = np.array([(r['word'] >> i) & 1 for r in rows for i in range(16)])
    seq = serial.Sequence(bits, validated['sequence_start_s'], 250e-12)
    outputs = {}
    for label, p, n in [('serializer','qp','qn'), ('pad','lqp','lqn'), ('remote','lrp','lrn')]:
        metrics, d = serial.check(w.t, w[p]-w[n], seq, plan['payload_bits'])
        signed = np.array(d['sample_voltage_v']) * (2 * bits[:len(d['sample_voltage_v'])] - 1)
        edge_bits = np.array(d['payload_transition_bits'])
        residual = np.array(d['edge_residual_ui'])
        slots = []
        for slot in range(16):
            indices = np.arange(64, 64 + plan['payload_bits'])
            sample = signed[indices[indices % 16 == slot]]
            edges = residual[edge_bits % 16 == slot]
            slots.append(dict(slot=slot, minimum_signed_margin_v=float(min(sample)), samples=len(sample),
                              edge_count=len(edges), edge_residual_min_ui=float(min(edges)) if len(edges) else None,
                              edge_residual_max_ui=float(max(edges)) if len(edges) else None))
        payload_indices = np.arange(64,64 + plan['payload_bits'])
        worst = sorted(payload_indices, key=lambda i: signed[i])[:16]
        outputs[label] = dict(check=metrics, slots=slots,
            worst_payload_bits=[dict(index=int(i), slot=int(i%16), word=int(i//16), expected=int(bits[i]), signed_margin_v=float(signed[i])) for i in worst],
            training_error_positions=[int(i) for i in range(32) if signed[i] <= 0],
            marker_error_positions=[int(i) for i in range(32,64) if signed[i] <= 0])
    c = Condition.parse(plan['condition'])
    sel = w['c250p']-w['c250n']
    a_edges = clock.edges(w.t, sel, -1)
    b_edges = clock.edges(w.t, sel, 1)
    changed = []
    for prev, row in zip(rows, rows[1:]):
        a = a_edges[a_edges >= row['capture_s']][0]
        b = b_edges[b_edges > a][0]
        for lane in range(16):
            if (row['word'] ^ prev['word']) & (1 << lane):
                edge = a if lane < 8 else b
                changed.append(dict(capture_s=row['capture_s'], lane=lane, selection='A_fall' if lane<8 else 'B_rise',
                    selected_edge_s=float(edge), q_lead_ps=lead(w.t,w[f'xtx.q{lane}'],edge,c.supply/2),
                    primary_s_lead_ps=lead(w.t,w[f'xtx.xcap.s{lane}'],edge,c.supply/2),
                    converter_din_b_lead_ps=lead(w.t,w[f'xtx.xc{lane}.din_b'],edge,c.supply/2)))
    ref = clock.edges(w.t,w['c2gp']-w['c2gn'],1)
    phases = {}
    for name in ('c250','c500','c1g','c2g'):
        for polarity in (-1,1):
            es = clock.edges(w.t,w[name+'p']-w[name+'n'],polarity)
            for window, start, end in [('training',seq.start_s,seq.start_s+64*seq.ui_s),('payload',seq.start_s+64*seq.ui_s,seq.start_s+(64+plan['payload_bits'])*seq.ui_s)]:
                esel = es[(es>=start)&(es<end)]
                idx = np.searchsorted(ref,esel,side='right')-1
                good=idx>=0; esel=esel[good]; idx=idx[good]
                delays=(esel-ref[idx])*1e12
                states=[]
                for edge in esel:
                    states.append(''.join('1' if np.interp(edge+30e-12,w.t,w[f'xclocks.q{i}p']-w[f'xclocks.q{i}n'])>0 else '0' for i in range(3)))
                phases[f'{window}_{name}_{"rise" if polarity==1 else "fall"}'] = dict(reference='preceding actual c2g rising zero crossing', sample_count=len(delays), delay_ps_min=float(min(delays)) if len(delays) else None, delay_ps_max=float(max(delays)) if len(delays) else None, counter_q0_q1_q2_counts={state:states.count(state) for state in sorted(set(states))}, counter_sample_offset_ps=30)
    return dict(condition=plan['condition'], campaign=str(camp.relative_to(ROOT)), hashes=validated['hashes'],
                outputs=outputs, changed_lanes=changed, clock_phases=phases,
                lead_definition='Time since most recent 50%-supply crossing before actual selected halfword edge, within 4 ns; null means no crossing found, not a measured margin.',
                phase_definition='Preceding rising c2g zero crossing; no fitted phase. Counter sign sampled 30 ps after each reported edge.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign',action='append',type=Path,required=True)
    args=parser.parse_args()
    cases=[diagnose(p) for p in args.campaign]
    out=ROOT/'results/analog/tx/parallel_diagnostic'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out.mkdir(parents=True,exist_ok=False)
    sources=[Path(__file__).resolve(),COLLECTOR]+[ROOT/'src/serdes_flow'/name for name in ('serial.py','clock.py','spice.py','waves.py','project.py','corners.py')]
    identity={}
    for source in sources:
        rel=source.relative_to(ROOT);dest=out/'execution'/rel
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        identity[str(rel)]=digest(dest)
    result=dict(scope='Existing raw only. Event-model tags, ideal 2 GHz, real bias and PDK tt resistors, initialized counter; no simulation or optimization. CML converter output and tree internal nodes not saved.',
                source_sha256=digest(Path(__file__)), collector_sha256=digest(COLLECTOR), analysis_sources=identity,cases=cases)
    (out/'diagnostic.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(out)


if __name__ == '__main__': main()
