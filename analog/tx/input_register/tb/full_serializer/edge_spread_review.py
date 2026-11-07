"""Recompute payload edge extrema for explicit archived full-TX campaigns; no simulation."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import serial, spice
from serdes_flow.project import ROOT

COLLECTOR=ROOT/'verification/plotting/tx_parallel_serializer.py'
spec=importlib.util.spec_from_file_location('parallel_serializer_collector',COLLECTOR)
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def analyse(camp):
    validated=collector.collect(camp)
    if (any(validated.get(key) is not True for key in ('input_boundary_ok','halfword_hold_ok','behavioral_tags_align'))
            or validated.get('counter',{}).get('counting') is not True):
        raise ValueError('edge attribution requires verified word capture, hold, tags and counting')
    camp=camp.resolve();summary=json.loads((camp/'summary.json').read_text());plan=json.loads((camp/'plan.json').read_text())
    rows=[r for r in summary['captures'] if r['payload_valid']]
    bits=np.array([(r['word']>>i)&1 for r in rows for i in range(16)])
    seq=serial.Sequence(bits,validated['sequence_start_s'],250e-12)
    w=spice.Waves(ROOT/validated['waveform']);metrics,details=serial.check(w.t,w['qp']-w['qn'],seq,plan['payload_bits'])
    if not collector.equal(metrics,summary['outputs']['serializer']['check']):raise ValueError('serializer recomputation mismatch')
    transitions=[]
    for bit,residual in zip(details['payload_transition_bits'],details['edge_residual_ui']):
        transitions.append(dict(bit=bit,payload_bit=bit-64,word=bit//16,slot=bit%16,
            halfword='A' if bit%16<8 else 'B',previous_bit=int(bits[bit-1]),expected_bit=int(bits[bit]),
            source_word=rows[bit//16]['word'],residual_ui=residual,
            crossing_s=seq.start_s+(bit+metrics['training_delay_ui']+residual)*seq.ui_s))
    slots=[]
    for slot in range(16):
        values=[r['residual_ui'] for r in transitions if r['slot']==slot]
        slots.append(dict(slot=slot,halfword='A' if slot<8 else 'B',count=len(values),
            minimum_ui=min(values) if values else None,maximum_ui=max(values) if values else None))
    return dict(condition=plan['condition'],clock_extra_2g=validated['clock_extra_2g'],clock_output_wt=validated['clock_output_wt'],
        clock_output_r=validated['clock_output_r'],campaign=validated['campaign'],hashes=validated['hashes'],
        graph_sha256=validated.get('numerical_source_graph_sha256'),sequence_start_s=seq.start_s,metrics=metrics,
        mapping=validated['outputs']['serializer']['mapping'],input_boundary_ok=validated['input_boundary_ok'],
        halfword_hold_ok=validated['halfword_hold_ok'],behavioral_tags_align=validated['behavioral_tags_align'],
        earliest=min(transitions,key=lambda r:r['residual_ui']) if transitions else None,
        latest=max(transitions,key=lambda r:r['residual_ui']) if transitions else None,
        slots=slots,transitions=transitions)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--campaign',type=Path,action='append',required=True);a=p.parse_args()
    cases=[analyse(x) for x in a.campaign]
    out=ROOT/'results/analog/tx/edge_spread_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True,exist_ok=False)
    sources=[Path(__file__).resolve(),COLLECTOR]+[ROOT/'src/serdes_flow'/x for x in ('serial.py','clock.py','spice.py','waves.py','project.py','corners.py')]
    hashes={}
    for source in sources:
        target=out/'execution'/source.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        hashes[str(source.relative_to(ROOT))]=sha(target)
    result=dict(scope='Explicit native full-TX runs; training-only phase; per-bit edge residual extrema, not a full PVT/noise qualification.',
        definition='Residual is matched output zero crossing minus training-only expected transition, in UI; bit indices start at the first training bit, payload starts at bit 64.',
        analysis_sources=hashes,cases=cases)
    (out/'diagnostic.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(out)


if __name__=='__main__':main()
