"""Explicitly register and run a calibrated r2g final-clock chain cut.

Three branches share ideal prescribed voltages as independent mathematical
experiments; no upstream source impedance or clock feedback is represented.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import bias, boundary, project, rcorner, spice, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
HELPER = ROOT/'analog/tx/input_register/tb/final_retime/window.py'
CHAIN = ROOT/'analog/tx/input_register/spice/final_retime_clock_chain.spice'
TEMPLATE = HERE/'tb_clock_ngspice.cir.in'
BASE_ID = 'tx_final_retime_recorded_v1'
spec = importlib.util.spec_from_file_location('final_retime_helper', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
MAP = {**{k:v for k,v in helper.NODES.items() if k not in ('sp','sn')},
       'rp':'xclocks.r2gp', 'rn':'xclocks.r2gn'}
SOURCES = dict(ap='Vap',an='Van',bp='Vbp',bn='Vbn',rp='Vrp',rn='Vrn',
               vbias='Vbias',vbias_logic='Vlogic',vdd='Vdd')
STOP = helper.STOP
VECTORS = ' '.join('v('+x+')' for x in list(MAP) +
    [x+str(i) for i in (1,2,3) for x in ('sp','sn','qp','qn')] +
    [f'xslice{i}.xfinal.{x}' for i in (1,2,3) for x in ('ahp','ahn','bhp','bhn')])


def sha(p):
    return helper.sha(p)


def check_template():
    defined={line.split()[0].lower() for line in TEMPLATE.read_text().splitlines()
             if line.strip() and line.strip()[0].lower()=='v'}
    if set(MAP)!=set(SOURCES) or any(v.lower() not in defined for v in SOURCES.values()):
        raise ValueError('source mapping mismatch')
    # Every branch carries the identical direct load topology as the calibrated cut.
    original=helper.lines(helper.TEMPLATE.read_text(),helper.LOAD_NAMES)
    text=TEMPLATE.read_text()
    renamed=set('sp sn qp qn lqp lqn llp lln lap lan ltp ltn lxp lxn lrp lrn lcm'.split())
    for i in (1,2,3):
        actual=helper.lines(text,[name+str(i) for name in helper.LOAD_NAMES])
        expected=[]
        for line in original:
            words=line.split()
            expected.append(' '.join([words[0]+str(i)]+[word+str(i) if word in renamed else word for word in words[1:]]))
        if actual != expected:
            raise ValueError(f'branch {i} load mismatch')



def register(bc_id, camps):
    check_template()
    base=boundary.get(BASE_ID)
    helper.verify_entry(base)
    expected={str((ROOT/p['trace_campaign']).resolve()) for p in base['points'].values()}
    if {str(p.resolve()) for p in camps}!=expected:
        raise ValueError('explicit traces differ from calibrated base boundary')
    for point in base['points'].values():
        trace_deck = (ROOT/point['trace_campaign']/'execution/physical_tb.cir').read_text()
        expected_chain = [
            'xiso2g r2gp r2gn i2gp i2gn vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400',
            'xe2g_0 i2gp i2gn e2g_0p e2g_0n vbias vdd vss serdes_cml_buffer wn=24 wt=16 rload=400',
            'xout2g e2g_0p e2g_0n c2gp c2gn vbias vdd vss serdes_cml_buffer wn=32 wt=24 rload=300']
        if helper.lines(trace_deck, ('Xiso2g','Xe2g_0','Xout2g')) != expected_chain:
            raise ValueError('source clock-chain instance differs')
        first_iso=expected_chain[0].replace('r2gp','rp').replace('r2gn','rn')
        source_load=boundary.input_stage_signature('.subckt cut rp rn\n'+first_iso+'\n.ends','cut',('rp','rn'))
        for count in (1,2,3):
            consumer_load=boundary.input_stage_signature(CHAIN,f'serdes_tx_final_clock_{count}',('rp','rn'))
            if consumer_load != source_load:
                raise ValueError(f'clock count{count} presents a different upstream load')
        w=spice.Waves(ROOT/point['raw'])
        for node in MAP.values():
            _=w[node]
    entry=dict(id=bc_id,kind='loaded_internal_port_voltage_replay',
        description='r2g recorded input into iso/extra/out clock chain and final retimed mux.',
        base_boundary_id=BASE_ID,base_boundary_sha256=hashlib.sha256(json.dumps(base,sort_keys=True).encode()).hexdigest(),
        nodes=MAP,load=source_load,downstream_load=base['load'],independent_mathematical_replicas=3,points=base['points'],chain_sha256=sha(CHAIN),template_sha256=sha(TEMPLATE),
        helper_sha256=sha(HELPER), processing='4 ns history plus 2 ns after selected halfword edge; fixed 3.5–5.8 ns evaluation.',
        validation=dict(state='pending_count1_baseline',waveform_error_gate_v=.005),
        valid_while=['source and actual first iso load unchanged','ideal source has no upstream impedance or feedback',
                     'count1 must match c2g, output and held nodes before interpreting count2/3',
                     'local TT/FS events only; no full-PVT, noise or mismatch qualification'])
    old=boundary.registry().get(bc_id)
    if old is None: boundary.register(entry)
    elif old!=entry: raise ValueError('boundary identity already exists with different content')
    return entry


def verify(entry):
    check_template()
    base=boundary.get(entry['base_boundary_id'])
    if hashlib.sha256(json.dumps(base,sort_keys=True).encode()).hexdigest()!=entry['base_boundary_sha256']:
        raise ValueError('base boundary changed')
    helper.verify_entry(base)
    for count in (1,2,3):
        boundary.check_load(entry['id'],boundary.input_stage_signature(CHAIN,f'serdes_tx_final_clock_{count}',('rp','rn')))
    if sha(CHAIN)!=entry['chain_sha256'] or sha(TEMPLATE)!=entry['template_sha256'] or sha(HELPER)!=entry['helper_sha256']:
        raise ValueError('consumer, template or helper changed')
    return base


def event_waves(point,bit):
    w=spice.Waves(ROOT/point['raw']);origin=point['events'][str(bit)]['origin_s']
    if w.t[0]>origin or w.t[-1]<origin+STOP: raise ValueError('source window missing')
    t=np.r_[0.,w.t[(w.t>origin)&(w.t<origin+STOP)]-origin,STOP]
    signals={name:np.interp(t+origin,w.t,w[node]) for name,node in MAP.items()}
    refs={name:np.interp(t+origin,w.t,w[node]) for name,node in
          dict(sp='c2gp',sn='c2gn',**helper.REFS).items()}
    return t,signals,refs


def deck(cases,entry,snap,smoke=False):
    first=Condition.parse(cases[0]['condition']);commands=[]
    for case in cases:
        c=Condition.parse(case['condition']);t,signals,_=event_waves(entry['points'][c.tag],case['bit'])
        for name,y in signals.items(): commands.extend(helper.alter_pwl(SOURCES[name],t,y,0.))
        commands += [f'option temp={c.temp}',f'alter Vtxen dc={c.supply:.12e}']
        tran='tran .5p 1.001n 0 .5p' if smoke else spice.skip_output_before(f'tran .5p {STOP:.12e} 0 .5p','.1n')
        commands += [tran,'write '+('smoke' if smoke else case['name'])+'.raw '+VECTORS,'destroy all']
    txt=spice.render(TEMPLATE,**spice.corner_values(first),CASES='\n'.join(commands),VECTORS=VECTORS)
    return bias.section(rcorner.to_pdk(txt,snap),first.process,'tt')


def measure(raw,case,entry):
    helper.validate_execution(raw);w=spice.Waves(raw)
    if w.t[-1]<STOP*(1-1e-6):raise ValueError('truncated case')
    t,signals,refs=event_waves(entry['points'][case['condition']],case['bit'])
    inp={n:float(np.max(abs(w[n]-np.interp(w.t,t,y)))) for n,y in signals.items()}
    if max(inp.values())>200e-6:raise ValueError('input replay error')
    keep=(w.t>=3.5e-9)&(w.t<=5.8e-9)
    nodes=dict(sp='sp1',sn='sn1',qp='qp1',qn='qn1',**{n:'xslice1.xfinal.'+n for n in ('ahp','ahn','bhp','bhn')})
    errors={n:float(np.max(abs(w[node][keep]-np.interp(w.t[keep],t,refs[n])))) for n,node in nodes.items()}
    return dict(input_max_error_v=inp,baseline_max_error_v=errors,baseline_matches=max(errors.values())<=.005,
                evaluation_window_s=[3.5e-9,5.8e-9],
                interpretation='Branches 2/3 are only interpretable when count1 matches; no upstream impedance or feedback.')


def run(entry,bc_id,resume):
    verify(entry)
    files=[Path(__file__).resolve(),HELPER,CHAIN,TEMPLATE,helper.CELL,helper.TEMPLATE]+[ROOT/x for x in helper.DEPENDENCIES]
    files += [ROOT/'src/serdes_flow'/x for x in ('spice.py','clock.py','waves.py','bias.py','rcorner.py','boundary.py','project.py','corners.py','watch.py')]
    identity={str(p.relative_to(ROOT)):sha(p) for p in files};bh=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
    if resume:
        camp=resume.resolve();plan=json.loads((camp/'plan.json').read_text())
        if plan['sources']!=identity or plan['boundary_sha256']!=bh:raise ValueError('campaign identity changed')
    else:
        camp=ROOT/'results/analog/tx/final_clock_chain'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        camp.mkdir(parents=True,exist_ok=False)
        plan=dict(boundary_id=bc_id,boundary_sha256=bh,sources=identity,stop_s=STOP)
        (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
        (camp/'boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
        for f in files:
            dest=camp/'execution'/f.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
    for rel,digest in identity.items():
        if sha(camp/'execution'/rel)!=digest:raise ValueError('campaign snapshot changed')
    if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign has live ngspice')
    cases=[dict(condition=tag,bit=int(bit),name=f'{tag}_bit{bit}') for tag,point in entry['points'].items() for bit in point['events']]
    groups={}
    for case in cases:
        proc=Condition.parse(case['condition']).process
        raw=spice.case_output(camp,proc,case['name']+'.raw',STOP)
        if raw: helper.validate_execution(raw)
        else: groups.setdefault(proc,[]).append(case)
    print(camp,flush=True)
    if groups:
        first=next(iter(groups.values()))[0]
        smoke=spice.run(deck([first],entry,camp/'snap/smoke',True),spice.next_run_dir(camp,'smoke'),timeout_s=180)
        if not smoke.ok or spice.case_output(camp,'smoke','smoke.raw',1e-9) is None:raise RuntimeError('smoke failed')
        for proc,cs in groups.items():
            ex=spice.run(deck(cs,entry,camp/'snap'/proc),spice.next_run_dir(camp,proc),timeout_s=180+180*len(cs),meta=dict(cases=cs,boundary_id=bc_id))
            if not ex.ok:raise RuntimeError(f'deck failed: {ex.run_dir}')
    rows=[]
    for case in cases:
        proc=Condition.parse(case['condition']).process;raw=spice.case_output(camp,proc,case['name']+'.raw',STOP)
        row=dict(case,status='missing')
        if raw:
            try:row.update(status='measured',waveform=str(raw.relative_to(ROOT)),waveform_sha256=sha(raw),metrics=measure(raw,case,entry))
            except (ValueError,KeyError) as e:row.update(status='analysis_error',error=str(e))
        rows.append(row)
    result=dict(boundary_id=bc_id,scope='Independent ideal-source branches; no upstream impedance or feedback. Count1 baseline gates interpretation of added stages.',rows=rows)
    tmp=camp/'summary.json.tmp';tmp.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');tmp.replace(camp/'summary.json')
    return camp


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--register',action='store_true');g.add_argument('--run',action='store_true');g.add_argument('--resume',type=Path)
    p.add_argument('--boundary-id',required=True);p.add_argument('--campaign',type=Path,action='append',default=[])
    a=p.parse_args()
    if a.register:
        if not a.campaign:p.error('--register requires explicit --campaign for every trace')
        print(register(a.boundary_id,a.campaign)['id'])
    else: print(run(boundary.get(a.boundary_id),a.boundary_id,a.resume))


if __name__=='__main__':main()
