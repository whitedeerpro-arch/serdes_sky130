"""Plan nonuniform extra5 tail widths using published local data; no SPICE.

Empirical 2 GHz fit, not a DDJ, functionality or full-TX pass prediction.
"""
import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares
from serdes_flow import project

ROOT=project.ROOT
SOURCES=[ROOT/'docs/data/tx_buffer_cascade.json',ROOT/'docs/data/tx_buffer_sizing.json']


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def transfer(w,v,limit,gain):
    scale=np.asarray(w)/14.4
    return limit*scale*np.tanh(gain*np.sqrt(scale)*np.asarray(v)/(limit*scale))


def plan():
    cascade,sizing=(json.loads(p.read_text()) for p in SOURCES)
    records=[]
    for data,label,width in ((cascade,'extra5',12.8),(sizing,'tail14',14),(sizing,'tail14p4',14.4)):
        for row in data['results']:
            if not row['result']['baseline_matches']: raise ValueError('source baseline failed')
            branch=next(b for b in row['result']['branches'] if b['branch']==label)
            nodes=branch['nodes']; names=('iso','e0','e1','e2','e3')
            for src,dst in zip(names,names[1:]):
                records.append({'condition':row['condition'],'branch':label,'wn_um':24,'wt_um':width,'r_nominal_ohm':320,
                    'source_node':src,'target_node':dst,'input_v':nodes[src]['differential_pp_v'],
                    'output_v':nodes[dst]['differential_pp_v']})
    rows=[]
    for tag in ('tt_v1800_t27','fs_v1650_t85'):
        obs=[r for r in records if r['condition']==tag]
        if len(obs)!=12: raise ValueError('expected twelve observations per condition')
        w=np.array([r['wt_um'] for r in obs]); x=np.array([r['input_v'] for r in obs]); y=np.array([r['output_v'] for r in obs])
        fit=least_squares(lambda p:transfer(w,x,*p)-y,[.36,1.2],bounds=([.05,.05],[2.,10.]))
        if not fit.success or not np.all(np.isfinite(fit.x)): raise ValueError(f'fit failed: {tag}')
        residual=transfer(w,x,*fit.x)-y
        source=next(r for r in sizing['results'] if r['condition']==tag)
        ref=next(b for b in source['result']['branches'] if b['branch']=='tail14p4')['nodes']
        iso=ref['iso']['differential_pp_v']; e3=ref['e3']['differential_pp_v']; e4=ref['e4']['differential_pp_v']
        denom=float(transfer(14.4,e3,*fit.x))
        if denom<=0: raise ValueError('invalid e4 reference')
        load_factor=e4/denom
        candidates=[]
        choices=[('uniform15',[15.]*5)]+[(f'first{first:g}_then{later:g}',[first]+[later]*4) for first,later in itertools.product((14.,14.4),(15.2,15.6,16.))]
        for name,widths in choices:
            values=[]; v=iso
            for i,width in enumerate(widths):
                v=float(transfer(width,v,*fit.x))
                if i==4: v*=load_factor
                values.append(v)
            candidates.append({'candidate':name,'wt_um':widths,'r_nominal_ohm':320,'wn_um':24,
                               'predicted_stage_pp_v':values,'predicted_e4_v_unvalidated_proxy':values[-1],
                               'maximum_predicted_stage_pp_v':max(values)})
        rows.append({'condition':tag,'observations':obs,'fit':{'limit_v_at_wt14p4':float(fit.x[0]),'gain_at_wt14p4':float(fit.x[1]),
                     'max_abs_in_sample_residual_v':float(np.max(np.abs(residual))),'rms_in_sample_residual_v':float(np.sqrt(np.mean(residual**2))),
                     'residual_v':residual.tolist()},'measured_iso_input_v':iso,
                     'e4_load_factor':float(load_factor),'e4_calibration':{'input_e3_v':e3,'observed_e4_v':e4,'predicted_unloaded_e4_v':denom},
                     'candidates':candidates})
    tt,fs=rows
    selections=[]
    for t,f in zip(tt['candidates'],fs['candidates']):
        selections.append({'candidate':t['candidate'],'tt_maximum_predicted_stage_v':t['maximum_predicted_stage_pp_v'],
            'tt_predicted_within_400mv':bool(t['maximum_predicted_stage_pp_v']<=.4),
            'fs_e4_v_unvalidated_proxy':f['predicted_e4_v_unvalidated_proxy']})
    return {'status':'prediction_only_ungraded','generator_sha256':sha(Path(__file__)),
            'sources':{str(p.relative_to(ROOT)):sha(p) for p in SOURCES},'rows':rows,'candidate_comparison':selections,
            'assumptions':['R320 and WN24; fit iso→e0→e1→e2→e3 only',
                'gm proportional to sqrt(I), amplitude saturation proportional to I, with I proportional to tail width',
                '2 GHz waveforms approximated by differential peak-to-peak amplitudes; observations are correlated',
                'e4 WN32 output load modeled by one factor calibrated at WT14.4; extrapolation is unvalidated',
                'does not predict DDJ, function, pass, PVT, source impedance, noise or full TX'],
            'selection_rule':'TT predicted max across e0..e4 <= 400 mV; compare FS e4 proxy, then verify by SPICE'}


if __name__=='__main__':
    output=ROOT/'docs/data/tx_buffer_gain_plan.json'
    result=plan(); output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result['candidate_comparison'],indent=2))
