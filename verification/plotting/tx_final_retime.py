"""Collect and redraw the two-condition final-rank replay study without simulation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

DEFAULT = ROOT/'docs/data/tx_final_retime_window.json'
FIGURE = ROOT/'docs/figures/tx/ingress/tx_final_retime_window'
CATALOG = ROOT/'results/catalog/tx_final_retime_window.json'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024*1024), b''):
            h.update(part)
    return h.hexdigest()


def collect(camp):
    camp = camp.resolve()
    plan = json.loads((camp/'plan.json').read_text())
    summary = json.loads((camp/'summary.json').read_text())
    entry = json.loads((camp/'boundary.json').read_text())
    if hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest() != plan['boundary_sha256']:
        raise ValueError('boundary hash mismatch')
    for rel, digest in plan['sources'].items():
        if sha(camp/'execution'/rel) != digest:
            raise ValueError(f'checkpoint mismatch: {rel}')
    runner = camp/'execution/analog/tx/input_register/tb/final_retime/window.py'
    spec = importlib.util.spec_from_file_location('final_retime_runner_snapshot', runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.verify_entry(entry)
    expected={(tag,int(bit),offset) for tag in plan['conditions'] for bit in plan['events'][tag] for offset in plan['offsets_ps']}
    rows=summary['rows']
    if len(rows)!=len(expected) or {(r['condition'],r['bit'],r['offset_ps']) for r in rows} != expected or any(r['status']!='measured' for r in rows):
        raise ValueError('all 24 distinct measured cases required; live/incomplete results are not read')
    out=[]
    for tag in plan['conditions']:
        point=entry['points'][tag]
        source=json.loads((ROOT/point['source_campaign']/'summary.json').read_text())
        trace=spice.Waves(ROOT/point['raw'])
        for bitstr in plan['events'][tag]:
            bit=int(bitstr); event=point['events'][bitstr]
            edge=event['selection_edge_s']; origin=event['origin_s']
            sign=1 if (event['source_word'] >> (bit%16)) & 1 else -1
            local=trace['xtx.xtree.xr4_0.sap']-trace['xtx.xtree.xr4_0.san']
            close_times, close_pol=crossings(trace.t,local)
            chosen=close_times[(close_pol==-1)&(close_times>=edge)&(close_times<=edge+.5e-9)]
            if not len(chosen): raise ValueError(f'{tag} bit {bit}: local A close absent')
            close=float(chosen[0]); close_rel=close-origin
            g3=trace['xtx.xtree.g3_0p']-trace['xtx.xtree.g3_0n']
            times,pol=crossings(trace.t,g3)
            suitable=times[(pol==sign)&(times>=edge)&(times<=edge+.5e-9)]
            crossing=float(suitable[0]) if len(suitable)==1 else None
            sample=(source['sequence_start_s']+(bit+.5+source['outputs']['serializer']['check']['training_delay_ui'])*250e-12)-origin
            event_result=dict(condition=tag,bit=bit,slot=event['slot'],source_word=event['source_word'],expected_bit=(sign+1)//2,
                trace_raw=point['raw'],trace_raw_sha256=point['raw_sha256'], origin_s=origin,halfword_edge_s=edge,
                actual_local_a_close_s=close, g3_expected_polarity_crossing_s=crossing,
                g3_crossing_minus_close_ps=(crossing-close)*1e12 if crossing is not None else None,
                g3_crossing_definition='unique crossing toward target sign during first 500ps after selected halfword edge; null if absent or ambiguous, never an older-word crossing',
                source_output_sample_relative_s=sample, cases=[])
            for row in sorted((r for r in rows if r['condition']==tag and r['bit']==bit),key=lambda r:r['offset_ps']):
                raw=ROOT/row['waveform']
                if sha(raw)!=row['waveform_sha256']: raise ValueError(f'raw hash mismatch: {raw}')
                module.validate_execution(raw)
                checked=module.measure(raw,row,entry)
                if max(checked['input_max_error_v'].values())>200e-6: raise ValueError('input replay mismatch')
                if row['offset_ps']==0 and (not checked['baseline_matches'] or max(checked['original_trace_error_v'].values())>.005):
                    raise ValueError('baseline fidelity failed')
                wave=spice.Waves(raw)
                delta=row['offset_ps']*1e-12
                reference=close_rel+delta
                locations=[reference,reference+200e-12,sample+delta]
                if any(t<plan['evaluation_window_s'][0] or t>plan['evaluation_window_s'][1] for t in locations):
                    raise ValueError(f'sample outside fixed evaluation window: {tag} {bit} {row["offset_ps"]}')
                at=lambda node,t: float(np.interp(t,wave.t,wave[node]))
                event_result['cases'].append(dict(offset_ps=row['offset_ps'], waveform=row['waveform'],waveform_sha256=row['waveform_sha256'],
                    reference_close_relative_s=reference,
                    signed_g3_at_reference_close_mv=1000*sign*(at('ap',reference)-at('an',reference)),
                    signed_held_a_200ps_after_reference_close_mv=1000*sign*(at('xslice.xfinal.ahp',reference+200e-12)-at('xslice.xfinal.ahn',reference+200e-12)),
                    signed_output_at_shifted_training_center_mv=1000*sign*(at('qp',sample+delta)-at('qn',sample+delta)),
                    input_max_error_v=max(checked['input_max_error_v'].values()),
                    baseline_max_error_v=max(checked['original_trace_error_v'].values()) if row['offset_ps']==0 else None))
            out.append(event_result)
    return dict(campaign=str(camp.relative_to(ROOT)),plan_sha256=sha(camp/'plan.json'),summary_sha256=sha(camp/'summary.json'),
        boundary_sha256=plan['boundary_sha256'],collector_sha256=sha(Path(__file__)),
        scope='Two events per TT/FS condition, ideal voltage replay without upstream impedance; not a full-bit, 45-PVT, physical-buffer, noise, or serializer-spec pass.',
        definition='Local A close is original sap-san falling crossing. Offset close is estimated as original close + commanded shift; fixed original training delay plus shift supplies output sampling phase, without payload fitting. Final 200 ps excluded.',
        evaluation_window_s=plan['evaluation_window_s'], events=out)


def draw(data):
    fig,axes=plt.subplots(2,2,figsize=(11,7),sharex=True,constrained_layout=True)
    for ax,event in zip(axes.flat,data['events']):
        cases=event['cases']; x=[c['offset_ps'] for c in cases]
        for key,label in [('signed_g3_at_reference_close_mv','g3 input at reference close'),
                          ('signed_held_a_200ps_after_reference_close_mv','held A, 200 ps later'),
                          ('signed_output_at_shifted_training_center_mv','output at shifted training center')]:
            ax.plot(x,[c[key] for c in cases],marker='o',ms=3,label=label)
        ax.axhline(0,color='black',lw=.7);ax.grid(alpha=.25)
        ax.set_title(f"{event['condition']} / bit {event['bit']} (slot {event['slot']}, word 0x{event['source_word']:04x})")
        ax.set_xlabel('Commanded c2g shift (ps)');ax.set_ylabel('Expected-polarity differential (mV)')
    axes.flat[0].legend(fontsize=8)
    fig.suptitle('Final-rank voltage replay: reference close estimated from original close + shift',fontsize=11)
    FIGURE.parent.mkdir(parents=True,exist_ok=True)
    for ext in ('png','svg'): fig.savefig(FIGURE.with_suffix('.'+ext),dpi=160)
    plt.close(fig)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collect', '--campaign', dest='campaign', type=Path, help='explicit completed campaign to collect')
    p.add_argument('--data',type=Path,default=DEFAULT)
    a=p.parse_args()
    if a.campaign:
        data=collect(a.campaign)
        a.data.parent.mkdir(parents=True,exist_ok=True)
        a.data.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    else:
        data=json.loads(a.data.read_text())
    draw(data)
    CATALOG.parent.mkdir(parents=True,exist_ok=True)
    CATALOG.write_text(json.dumps(dict(data=str(a.data.relative_to(ROOT)),data_sha256=sha(a.data),
        source_campaign=data['campaign'],figures=[str(FIGURE.relative_to(ROOT))+'.'+x for x in ('png','svg')],
        collector_sha256=sha(Path(__file__)),scope=data['scope']),indent=2)+'\n')


if __name__=='__main__': main()
