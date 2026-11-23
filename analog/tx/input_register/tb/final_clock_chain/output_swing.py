"""Prepare/register/resume three loaded output-swing variants; --check runs no ngspice."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile

import numpy as np
from serdes_flow import boundary, project, spice, watch
from serdes_flow.corners import Condition

ROOT=project.ROOT
HERE=Path(__file__).resolve().parent
PARENT=HERE/'run.py'
SOURCE=ROOT/'results/analog/tx/final_clock_chain/20261107T094939Z'
BASE_ID='tx_final_clock_chain_recorded_v1'
PARAMS=((32,24,300),(32,18,240),(32,16,240))
spec=importlib.util.spec_from_file_location('clock_chain_parent',PARENT)
parent=importlib.util.module_from_spec(spec);spec.loader.exec_module(parent)
sha=parent.sha
STOP=parent.STOP
EXTRA=' '.join(f'v(xslice{i}.xfinal.{node})' for i in (1,2,3)
               for node in ('sap','san','sbp','sbn','xm.slp','xm.sln','xm.tail','xm.ta','xm.tb','xla.tail','xlb.tail')) + ' ' + ' '.join(f'v(xclock{i}.{node})' for i in (1,2,3) for node in ('e3p','e3n','xout.xgain.tail'))


def generate_chain():
    text=parent.CHAIN.read_text()
    match=re.search(r'(?ims)^\.subckt serdes_tx_final_clock_3\b.*?^\.ends serdes_tx_final_clock_3\s*$',text)
    if match is None:raise ValueError('count3 source subckt missing')
    source=match.group(0);old='Xout e3p e3n cp cn vbias vdd vss serdes_cml_buffer wn=32 wt=24 rload=300'
    if source.count(old)!=1:raise ValueError('count3 output topology changed')
    result=[]
    for index,(wn,wt,rload) in enumerate(PARAMS,1):
        new=f'Xout e3p e3n cp cn vbias vdd vss serdes_cml_buffer wn={wn} wt={wt} rload={rload}'
        block=source.replace('serdes_tx_final_clock_3',f'serdes_tx_final_clock_{index}').replace(old,new)
        result.append(block)
    return '\n\n'.join(result)+'\n'


def source_cases(entry):
    parent.verify(entry)
    plan=json.loads((SOURCE/'plan.json').read_text());saved=json.loads((SOURCE/'boundary.json').read_text())
    if plan['boundary_id']!=BASE_ID or hashlib.sha256(json.dumps(saved,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256'] or saved!=entry:
        raise ValueError('fixed source boundary mismatch')
    for rel,digest in plan['sources'].items():
        if sha(SOURCE/'execution'/rel)!=digest:raise ValueError(f'source snapshot changed: {rel}')
    rows=json.loads((SOURCE/'summary.json').read_text())['rows']
    expected={(tag,int(bit)) for tag,p in entry['points'].items() for bit in p['events']}
    if len(rows)!=len(expected) or {(r['condition'],r['bit']) for r in rows}!=expected or any(r['status']!='measured' for r in rows):
        raise ValueError('source campaign incomplete')
    for row in rows:
        raw=ROOT/row['waveform'];parent.helper.validate_execution(raw)
        if sha(raw)!=row['waveform_sha256'] or spice.Waves(raw).t[-1]<STOP*(1-1e-6):raise ValueError('source raw changed or truncated')
        if not parent.measure(raw,row,entry)['baseline_matches']:raise ValueError('source count1 baseline failed')
    return rows


def entry_for(bc_id):
    base=boundary.get(BASE_ID);rows=source_cases(base)
    generated=generate_chain()
    for i in (1,2,3):
        actual=boundary.input_stage_signature(generated,f'serdes_tx_final_clock_{i}',('rp','rn'))
        if actual!=base['load']:raise ValueError('upstream input load differs')
    parent.check_template()
    return dict(id=bc_id,kind='loaded_internal_port_voltage_replay',
        description='Three independent extra3 clock chains differing only in final stage tail width and load resistance.',
        parent_boundary_id=BASE_ID,parent_boundary_sha256=hashlib.sha256(json.dumps(base,sort_keys=True).encode()).hexdigest(),
        source_campaign=str(SOURCE.relative_to(ROOT)),source_plan_sha256=sha(SOURCE/'plan.json'),source_summary_sha256=sha(SOURCE/'summary.json'),
        source_waveforms={r['name']:r['waveform_sha256'] for r in rows},load=base['load'],downstream_load=base['downstream_load'],
        independent_mathematical_replicas=3,params=[dict(wn=wn,wt=wt,rload=r) for wn,wt,r in PARAMS],
        generated_sha256=hashlib.sha256(generated.encode()).hexdigest(),
        valid_while=['ideal voltage sources omit upstream impedance and feedback','same direct downstream load and same source identity',
                     'branch1 c2g, qp/qn and held A/B must match parent extra3 to 5mV before interpreting other branches',
                     'local ungraded study; no full-TX or PVT qualification'])


def register(bc_id):
    entry=entry_for(bc_id);old=boundary.registry().get(bc_id)
    if old is None:boundary.register(entry)
    elif old!=entry:raise ValueError('boundary id identity mismatch')
    return entry


def render(cases,base,camp,name,smoke=False):
    snap=camp/'snap'/name
    text=parent.deck(cases,base,snap,smoke)
    generated=camp/'generated'/f'{name}_chain.spice';generated.parent.mkdir(parents=True,exist_ok=True)
    generated.write_text(generate_chain())
    lines=text.splitlines();matches=[i for i,line in enumerate(lines) if line.lower().startswith('.include ') and line.lower().endswith('/analog/tx/input_register/spice/final_retime_clock_chain.spice"')]
    if len(matches)!=1:raise ValueError('cannot identify transformed clock chain include')
    lines[matches[0]]=f'.include "{generated}"'
    text='\n'.join(lines)+'\n'
    text=text.replace(parent.VECTORS,parent.VECTORS+' '+EXTRA)
    if text.count('v(xslice1.xfinal.sap)')<2:raise ValueError('extra saved vectors missing')
    return text


def prepare(bc_id,camp):
    entry=boundary.get(bc_id)
    if entry!=entry_for(bc_id):raise ValueError('registered boundary changed')
    camp.mkdir(parents=True,exist_ok=False);base=boundary.get(BASE_ID)
    cases=[dict(condition=tag,bit=int(bit),name=f'{tag}_bit{bit}') for tag,p in base['points'].items() for bit in p['events']]
    decks={}
    for case in cases:
        name=case['name'];text=render([case],base,camp,name)
        path=camp/'prepared'/f'{name}.cir';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        decks[name]=str(path.relative_to(camp))
    smoke=render([cases[0]],base,camp,'smoke',True)
    (camp/'prepared/smoke.cir').write_text(smoke)
    files=[Path(__file__).resolve(),PARENT,parent.HELPER,parent.CHAIN,parent.TEMPLATE,parent.helper.CELL,parent.helper.TEMPLATE]+[ROOT/x for x in parent.helper.DEPENDENCIES]
    files += [ROOT/'src/serdes_flow'/x for x in ('spice.py','clock.py','waves.py','bias.py','rcorner.py','boundary.py','project.py','corners.py','watch.py')]
    files += [ROOT/'config/pdk.toml',ROOT/'config/tools.toml']
    sources={str(p.relative_to(ROOT)):sha(p) for p in files}
    for f in files:
        dst=camp/'execution'/f.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dst)
    (camp/'boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
    files=[p for directory in ('prepared','generated','snap','execution') for p in (camp/directory).rglob('*') if p.is_file()]
    plan=dict(boundary_id=bc_id,boundary_sha256=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest(),
              sources=sources,snapshots={str(p.relative_to(camp)):sha(p) for p in files},cases=cases,decks=decks,
              stop_s=STOP,pdk_installation_id=project.pdk_installation_id(),model_library_sha256=sha(project.model_library()))
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return plan


def verify(camp):
    plan=json.loads((camp/'plan.json').read_text());entry=boundary.get(plan['boundary_id'])
    if entry!=entry_for(plan['boundary_id']) or hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256']:
        raise ValueError('boundary identity changed')
    if project.pdk_installation_id()!=plan['pdk_installation_id'] or sha(project.model_library())!=plan['model_library_sha256']:
        raise ValueError('PDK changed')
    for rel,digest in plan['sources'].items():
        if sha(ROOT/rel)!=digest:raise ValueError(f'source changed: {rel}')
    for rel,digest in plan['snapshots'].items():
        if sha(camp/rel)!=digest:raise ValueError(f'snapshot changed: {rel}')
    return plan,entry


def pending(camp,plan):
    result=[]
    for case in plan['cases']:
        raw=spice.case_output(camp,case['name'],case['name']+'.raw',STOP)
        if raw is None:result.append(case)
        else:parent.helper.validate_execution(raw)
    return result


def measure(raw,case,entry):
    parent.helper.validate_execution(raw);w=spice.Waves(raw)
    if w.t[-1]<STOP*(1-1e-6):raise ValueError('truncated waveform')
    base=boundary.get(BASE_ID);t,inputs,_=parent.event_waves(base['points'][case['condition']],case['bit'])
    errs={name:float(np.max(abs(w[name]-np.interp(w.t,t,arr)))) for name,arr in inputs.items()}
    if max(errs.values())>200e-6:raise ValueError('input replay mismatch')
    rows=json.loads((SOURCE/'summary.json').read_text())['rows'];row=next(r for r in rows if r['condition']==case['condition'] and r['bit']==case['bit'])
    reference=spice.Waves(ROOT/row['waveform']);keep=(w.t>=3.5e-9)&(w.t<=5.8e-9)
    nodes={**{n:n+'1' for n in ('sp','sn','qp','qn')},**{n:'xslice1.xfinal.'+n for n in ('ahp','ahn','bhp','bhn')}}
    refs={**{n:n+'3' for n in ('sp','sn','qp','qn')},**{n:'xslice3.xfinal.'+n for n in ('ahp','ahn','bhp','bhn')}}
    errors={n:float(np.max(abs(w[node][keep]-np.interp(w.t[keep],reference.t,reference[refs[n]])))) for n,node in nodes.items()}
    return dict(input_max_error_v=errs,baseline_max_error_v=errors,baseline_matches=max(errors.values())<=.005,
                evaluation_window_s=[3.5e-9,5.8e-9],interpretation='Candidates interpretable only if baseline matches; local ungraded ideal-source replay.')


def resume(camp):
    camp=camp.resolve();plan,entry=verify(camp)
    if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('live ngspice in campaign')
    missing=pending(camp,plan)
    if missing:
        ex=spice.run((camp/'prepared/smoke.cir').read_text(),spice.next_run_dir(camp,'smoke'),timeout_s=180)
        if not ex.ok or spice.case_output(camp,'smoke','smoke.raw',1.001e-9) is None:raise RuntimeError('smoke failed')
        for case in missing:
            ex=spice.run((camp/plan['decks'][case['name']]).read_text(),spice.next_run_dir(camp,case['name']),timeout_s=360,meta=dict(case=case,boundary_id=plan['boundary_id']))
            if not ex.ok:raise RuntimeError(f'case failed: {ex.run_dir}')
    rows=[]
    for case in plan['cases']:
        raw=spice.case_output(camp,case['name'],case['name']+'.raw',STOP);row=dict(case,status='missing')
        if raw:
            try:row.update(status='measured',waveform=str(raw.relative_to(ROOT)),waveform_sha256=sha(raw),metrics=measure(raw,case,entry))
            except (ValueError,KeyError) as e:row.update(status='analysis_error',error=str(e))
        rows.append(row)
    result=dict(analysis_source_sha256=sha(Path(__file__).resolve()),scope='Local ideal-source replay; baseline gate required before interpretation; not full TX qualification.',rows=rows)
    analysis=camp/'analysis';analysis.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    (analysis/(stamp+'.json')).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    tmp=camp/'summary.json.tmp';tmp.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');tmp.replace(camp/'summary.json')
    return result


def check():
    parent.check_template();base=boundary.get(BASE_ID);source_cases(base)
    with tempfile.TemporaryDirectory() as d:
        camp=Path(d);case=dict(condition=next(iter(base['points'])),bit=48,name='check')
        deck=render([case],base,camp,'check');assert 'write check.raw' in deck
        for i,(wn,wt,r) in enumerate(PARAMS,1):
            generated=(camp/'generated/check_chain.spice').read_text()
            assert f'serdes_tx_final_clock_{i}' in generated and f'wn={wn} wt={wt} rload={r}' in generated
        fake=dict(cases=[case]);assert pending(camp,fake)==[case]
        from unittest.mock import patch
        fake_raw=camp/'complete.raw'
        with patch.object(spice,'case_output',return_value=fake_raw), patch.object(parent.helper,'validate_execution') as verify_raw:
            assert pending(camp,fake)==[]
            verify_raw.assert_called_once_with(fake_raw)
    print('source, generated chain, deck, and missing-case resume checks passed; no ngspice')


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--check',action='store_true');g.add_argument('--register',action='store_true');g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path)
    p.add_argument('--boundary-id');a=p.parse_args()
    if a.check:check();return
    if a.resume:resume(a.resume);return
    if not a.boundary_id:p.error('--boundary-id required for register/prepare')
    if a.register:print(register(a.boundary_id)['id']);return
    camp=ROOT/'results/analog/tx/final_clock_swing'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    prepare(a.boundary_id,camp);print(camp)


if __name__=='__main__':main()
