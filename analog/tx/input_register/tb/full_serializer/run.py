"""Actual v3 clock distribution + capture/serializer/driver, ideal CML inputs.

probe: record the loaded PHY word clock with static data.
prepare: register its producer schedule, never fit a serialized output.
run: replay tx_ingress_control output data/tags and check dynamic serialization.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shutil
import uuid

import numpy as np

from serdes_flow import bias,boundary,clock,project,rcorner,serial,spice,watch
from serdes_flow.corners import Condition

ROOT=project.ROOT
HERE=Path(__file__).resolve().parent
LOADED_SOURCE=Path(__file__).read_bytes()
LOADED_SHA256=hashlib.sha256(LOADED_SOURCE).hexdigest()
DUT=ROOT/'analog/tx/input_register/spice/capture_serializer16.spice'
EXPECTED=ROOT/'analog/tx/serializer/tb/clock_states/serializer_expected.json'
DIST=ROOT/'analog/tx/serializer/tb/clock_replay/variants/dist_v3.py'
_spec=importlib.util.spec_from_file_location('full_dist_v3',DIST)
dist=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(dist)
_trace_spec=importlib.util.spec_from_file_location('tx_internal_trace_vectors',HERE/'trace.py')
trace_vectors=importlib.util.module_from_spec(_trace_spec);_trace_spec.loader.exec_module(trace_vectors)
SELECTS=('c250p','c250n','c500p','c500n','c1gp','c1gn','c2gp','c2gn')
PAYLOAD_BITS=256
WORDS=(64+PAYLOAD_BITS+32)//16
DATA_STOP=120e-9
FILES=(
 'analog/common/devices/spice/sky130_primitives.spice','analog/common/devices/spice/cmos_logic.spice',
 'analog/common/devices/spice/cmos_dff.spice','analog/common/devices/spice/sky130_pfet_lvt.spice',
 'analog/common/cmos_to_cml/spice/cmos_to_cml_data.spice','analog/common/cml_to_cmos/spice/cml_to_cmos.spice',
 'analog/common/cml_to_cmos/spice/cml_to_cmos_pvt_candidate.spice',
 'analog/common/cml_mux/spice/cml_lowov_cells.spice','analog/common/cml_buffer/spice/cml_buffer.spice',
 'analog/common/cml_buffer/spice/cml_delay_resistive.spice',
 'analog/tx/input_register/spice/word_capture16_staggered.spice',
 'analog/tx/input_register/spice/word_clock_receiver.spice',
 'analog/tx/input_register/spice/capture_serializer16.spice',
 'analog/tx/serializer/spice/serializer16_retimed_lowov.spice',
 'analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice',
 'verification/models/channel/diff_rlc16.spice',
)+dist.INCLUDES+bias.BIAS_INC
PHYSICAL={str(DIST.relative_to(ROOT)),str((HERE/'tb_full_ngspice.cir.in').relative_to(ROOT))}|set(FILES)


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def new_campaign_dir():
    parent=ROOT/'results/analog/tx/parallel_serializer'
    for _ in range(4):
        name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]
        campaign=parent/name
        try:campaign.mkdir(parents=True,exist_ok=False)
        except FileExistsError:continue
        return campaign
    raise RuntimeError('could not allocate a unique result directory')


def fixture_signature(text):
    """Bind probe/run clock sources, loads, initialization and wiring.

    Exclude prescribed data/metadata sources and output controls. Included
    cell definitions and PDK are checked separately by their archived hashes.
    """
    keep=[]
    for line in text.split('.control',1)[0].splitlines()[1:]:
        line=line.strip()
        if not line or line.startswith('*') or line.lower().startswith(('.include ','.lib ','.save ')):continue
        if re.match(r'^V(?:d\d+|guard_(?:a|b|ready|valid))\s',line,re.I):continue
        keep.append(' '.join(line.lower().split()))
    return hashlib.sha256('\n'.join(keep).encode()).hexdigest()


def check_runtime_includes(text,camp,plan):
    """Old checkpoints may reference a source outside the archived deck tree."""
    for name in re.findall(r'^\.include\s+"([^"]+)"',text,re.M|re.I):
        path=Path(name).resolve()
        if path.is_relative_to(camp.resolve()):
            key=str(path.relative_to(camp.resolve()))
            expected=plan['snapshot_files'].get(key)
        elif path.is_relative_to(ROOT):
            expected=plan['sources'].get(str(path.relative_to(ROOT)))
        else:
            expected=None
        if expected is None or not path.is_file() or sha(path)!=expected:
            raise ValueError(f'unbound or changed runtime include: {path}')


def vectors():
    names=['v(vdd)','i(Vdd)','v(xtx.word_clk)','v(xtx.xcap.clk_b)','v(qp)','v(qn)','v(lqp)','v(lqn)','v(lrp)','v(lrn)']
    names += [f'v({x})' for x in SELECTS]+['v(s2gp)','v(s2gn)']+dist.probe_vectors()
    names += [f'v(d{i})' for i in range(16)]+[f'v(xtx.q{i})' for i in range(16)]
    names += [f'v(xtx.xcap.s{i})' for i in range(16)]
    names += [f'v(xtx.xcap.h{i})' for i in range(8,16)]
    names += [f'v(xtx.xc{i}.din_b)' for i in range(16)]
    return list(dict.fromkeys(names+trace_vectors.internal_vectors()))


def output_parameters(wt=24, resistance=300):
    values=[]
    for name,value in (('clock output wt',wt),('clock output resistance',resistance)):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError(f'{name} must be positive and finite')
        values.append(int(value) if float(value).is_integer() else float(value))
    return tuple(values)


def check_output_identity(plan, entry):
    planned=output_parameters(plan.get('clock_output_wt',24),plan.get('clock_output_r',300))
    upstream=entry['upstream']
    registered=output_parameters(upstream.get('clock_output_wt',24),upstream.get('clock_output_r',300))
    if planned!=registered:raise ValueError('clock output parameters differ from registered probe')
    return planned


def distribution(extra_2g=1,output_wt=24,output_r=300):
    if extra_2g not in (1,2,3):raise ValueError('unsupported 2GHz extra-stage count')
    wt,resistance=output_parameters(output_wt,output_r)
    return dist.netlist({'extra':{**dist.DEFAULT['extra'],'2g':extra_2g},
                         'out':{**dist.DEFAULT['out'],'2g':(32,wt,resistance)}})


def deck(c,data,stop,snap,smoke=False,extra_2g=1,output_wt=24,output_r=300):
    lines=[]
    for name,period in (('250',4e-9),('500',2e-9),('1g',1e-9),('2g',.5e-9)):
        lines += [f'V{name} u{name} 0 PULSE(0 1 1n 30p 30p {period/2-30e-12:.12e} {period:.12e})',
                  f'B{name}p s{name}p 0 V=v(vdd)-.35+.2*v(u{name})',
                  f'B{name}n s{name}n 0 V=v(vdd)-.15-.2*v(u{name})']
    loads=[f'Cq{i} xtx.q{i} 0 2f' for i in range(16)]
    loads += [f'.nodeset v(xtx.q{i})=0 v(xtx.xcap.s{i})=0' for i in range(16)]
    include='\n'.join(f'.include "{ROOT/p}"' for p in dict.fromkeys(FILES))
    vec=vectors()
    if 'Vguard_a ' in data:vec+=['v(guard_a)','v(guard_b)','v(guard_ready)','v(guard_valid)']
    tran='tran 2p 1.001n 0 2p' if smoke else spice.skip_output_before(f'tran 2p {stop:.12e} 0 2p','8n')
    txt=spice.render(HERE/'tb_full_ngspice.cir.in',**spice.corner_values(c),INCLUDES=include,
        DISTRIBUTION='\n'.join(l for l in distribution(extra_2g,output_wt,output_r).splitlines() if not l.startswith('.include ')),CLOCK_SOURCES='\n'.join(lines),DATA=data,WIRE_LOADS='\n'.join(loads),
        VECTORS=' '.join(vec),TRAN=tran)
    return bias.section(rcorner.to_pdk(bias.real(txt),snap),c.process,'tt')


def probe_metrics(path):
    w=spice.Waves(path)
    plan=json.loads((path.parent.parent/'plan.json').read_text())
    start=max(10e-9,plan['stop_s']-14e-9);end=plan['stop_s']-1e-9
    ck=w['xclocks.xcnt.ckp']-w['xclocks.xcnt.ckn']
    e=clock.edges(w.t,ck,-1)
    cnt=clock.binary_counter(w.t,[w[f'xclocks.q{i}p']-w[f'xclocks.q{i}n'] for i in range(3)],e,start,end-1e-9)
    c=Condition.parse(plan['condition'])
    rises=clock.edges(w.t,w['xtx.word_clk']-c.supply/2,1,start,end)
    falls=clock.edges(w.t,w['xtx.word_clk']-c.supply/2,-1,start,end)
    if len(rises)<3 or len(falls)<3 or not cnt['counting']:
        raise ValueError('clock/counter function failed')
    if max(np.max(np.abs(np.diff(a)-4e-9)) for a in (rises,falls))>1e-12:
        raise ValueError('period deviation exceeds 1ps producer-schedule recording gate')
    return dict(counter=cnt,rises_s=rises.tolist(),falls_s=falls.tolist(),period_s=4e-9,window_s=[start,end],period_deviation_gate_s=1e-12)


def prepare(camp):
    plan=json.loads((camp/'plan.json').read_text())
    if plan['mode']!='probe':raise ValueError('requires a probe campaign')
    wave=spice.case_output(camp,'run','waveforms.raw',plan['stop_s'])
    if wave is None:raise ValueError('probe incomplete')
    m=probe_metrics(wave)
    for rel in PHYSICAL:
        if sha(ROOT/rel)!=plan['sources'][rel]:raise ValueError('physical circuit changed after probe')
    c=Condition.parse(plan['condition']);run=wave.parent
    ex=json.loads((run/'execution.json').read_text())
    if sha(run/'tb.cir')!=ex['deck_sha256']:raise ValueError('probe deck changed')
    bc_id='tx_capture_serializer_word_schedule_'+camp.name
    period=4e-9
    # Clock phase comes only from the loaded clock probe. The frequency is the
    # prescribed exact 2GHz/8, never fitted to a data waveform.
    phase={key:float(np.angle(np.mean(np.exp(2j*np.pi*np.asarray(m[key])/period)))*period/(2*np.pi)) for key in ('rises_s','falls_s')}
    edges={}
    for key in phase:
        a=[round((phase[key]+k*period)*1e15)/1000 for k in range(-2,36) if 0<phase[key]+k*period<DATA_STOP]
        edges[key.replace('_s','_ps')]=a
    # Model initial high; first listed transition must therefore be a fall.
    earliest_r=edges['rises_ps'][0];earliest_f=edges['falls_ps'][0]
    if earliest_r<earliest_f:edges['rises_ps']=edges['rises_ps'][1:]
    t0=next(x for x in edges['falls_ps'] if x>=20000)+100
    bits=json.loads(EXPECTED.read_text())['bits'][:WORDS*16]
    words=[sum(bits[16*k+i]<<i for i in range(16)) for k in range(WORDS)]
    updates=[dict(time_ps=round(t0+4000*k,3),word=word) for k,word in enumerate(words)]
    schedule=dict(**edges,updates=updates,reset_release_ps=8000,permit_ps=12000,stop_ps=round(DATA_STOP*1e12),supply_v=c.supply,boundary_id=bc_id)
    folder=camp/'prepared';folder.mkdir(exist_ok=False)
    schedule_path=folder/'schedule.json';schedule_path.write_text(json.dumps(schedule,indent=2)+'\n')
    output_wt,output_r=output_parameters(plan.get('clock_output_wt',24),plan.get('clock_output_r',300))
    entry=dict(id=bc_id,kind='loaded_word_clock_event_schedule',
        description='Producer events on a loaded capture/serializer word clock. Actual v3 distribution/receiver; ideal CML source, exact 2GHz. RTL behavior replay, no output-derived phase fit.',
        upstream=dict(module='tx.capture',revision='capture_serializer16_candidate',clock_extra_2g=plan.get('clock_extra_2g',1),clock_output_wt=output_wt,clock_output_r=output_r,physical_sources={p:plan['sources'][p] for p in PHYSICAL},fixture_sha256=fixture_signature((run/'tb.cir').read_text())),
        nodes=dict(clock='xtx.word_clk',producer_data='d0..d15'),
        load=boundary.input_stage_signature(DUT,'serdes_tx_capture_serializer16',SELECTS),
        points={c.tag:boundary.run_record(run,condition=c.tag,raw=str(wave.relative_to(ROOT)),raw_sha256=sha(wave),pdk_installation_id=ex['pdk_installation_id'])},
        processing=dict(schedule=str(schedule_path.relative_to(ROOT)),schedule_sha256=sha(schedule_path),clock_probe=m,
                        exact_period_s=period,producer_update_after_fall_s=100e-12,reset_release_s=8e-9,permit_s=12e-9),
        validation=dict(requirement='actual capture edges within 100ps of replay; input data setup/hold >=500ps; captured words and halfwords checked independently'),
        valid_while=['same physical modules, clock source, loads, counter initialization and PDK',
                     'data activity may modulate clock phase; actual second run must verify the producer interface',
                     'RTL event model has no library/physical tag delay or output-blank implementation; not startup qualification'])
    boundary.register(entry)
    print(bc_id,schedule_path,flush=True)
    return entry


def analyse_dynamic(path,manifest,entry,payload_bits=PAYLOAD_BITS):
    w=spice.Waves(path);c=Condition.parse(next(iter(entry['points'])))
    captures=clock.edges(w.t,w['xtx.word_clk']-c.supply/2,1,12e-9,w.t[-1]-1.2e-9)
    logical=[x for x in manifest['captures'] if 12e-9<=x['time_ps']*1e-12<=w.t[-1]-1.2e-9]
    rows=[];accepted=[];training_capture=None
    for item in logical:
        target=item['time_ps']*1e-12
        hit=captures[np.abs(captures-target)<100e-12]
        if len(hit)!=1:raise ValueError('behavioral replay clock/capture phase mismatch')
        e=float(hit[0]);word=item['word']
        errors=[]
        for lane in range(16):
            expected=(word>>lane)&1;v=w[f'd{lane}'];sign=2*expected-1
            use=(w.t>=e-.5e-9)&(w.t<=e+.5e-9)
            if np.min((v[use]-c.supply/2)*sign)<=.3*c.supply:errors.append(lane)
            if (np.interp(e+1e-9,w.t,w[f'xtx.xcap.s{lane}'])>c.supply/2)!=bool(expected):errors.append(lane)
        row=dict(capture_s=e,word=word,payload_valid=bool(item['valid']),errors=sorted(set(errors)),halfword_window_checked=False)
        ae=clock.edges(w.t,w['c250p']-w['c250n'],-1,e)
        be=clock.edges(w.t,w['c250p']-w['c250n'],1,float(ae[0])) if len(ae) else []
        if len(ae) and len(be) and be[0]+1.9e-9<=w.t[-1]:
            bad=[];margins=[];tags=[]
            for lane in range(16):
                edge=ae[0] if lane<8 else be[0]
                keep=(w.t>=edge-.1e-9)&(w.t<=edge+1.9e-9)
                margin=float(np.min((w[f'xtx.q{lane}'][keep]-c.supply/2)*(2*((word>>lane)&1)-1)))
                margins.append(margin)
                if margin<=.3*c.supply:bad.append(lane)
            for edge,tag in ((ae[0],'guard_a'),(be[0],'guard_b')):
                keep=(w.t>=edge-.1e-9)&(w.t<=edge+1.9e-9)
                tags.append(float(np.min((w[tag][keep]-c.supply/2)*(1 if item['valid'] else -1)))>.3*c.supply)
            row.update(halfword_window_checked=True,halfword_hold_errors=bad,minimum_q_signed_margin_v=min(margins),behavioral_tags_align=all(tags))
        elif item['valid']:
            raise ValueError('valid word misses complete selected-half window')
        rows.append(row)
        if item['valid']:
            accepted.append(row)
            if training_capture is None:training_capture=e
    words=(64+payload_bits+32)//16
    if len(accepted)!=words or training_capture is None:raise ValueError(f'need all {words} producer words')
    first_a=clock.edges(w.t,w['c250p']-w['c250n'],-1,training_capture)[0]
    bits=np.asarray([((r['word']>>i)&1) for r in accepted for i in range(16)],dtype=int)
    seq=serial.Sequence(bits,float(first_a),250e-12)
    outputs={}
    for label,a,b in (('serializer','qp','qn'),('pad','lqp','lqn'),('remote','lrp','lrn')):
        m,_=serial.check(w.t,w[a]-w[b],seq,payload_bits)
        outputs[label]=dict(check=m,meets_spec=serial.meets_draft(m),mapping=serial.bit_mapping(w.t,w[a]-w[b],seq))
    ck=w['xclocks.xcnt.ckp']-w['xclocks.xcnt.ckn']
    counter=clock.binary_counter(w.t,[w[f'xclocks.q{i}p']-w[f'xclocks.q{i}n'] for i in range(3)],
                                 clock.edges(w.t,ck,-1),float(first_a),float(first_a+len(bits)*250e-12))
    return dict(captures=rows,accepted_words=len(accepted),counter=counter,
                input_boundary_ok=all(not r['errors'] for r in rows),
                halfword_hold_ok=all(not r['halfword_hold_errors'] for r in rows if r['halfword_window_checked']),
                halfword_checked_words=sum(r['halfword_window_checked'] for r in rows),
                halfword_ungraded_words=sum(not r['halfword_window_checked'] for r in rows),
                behavioral_tags_align=all(r['behavioral_tags_align'] for r in rows if r['halfword_window_checked']),
                tags_are_RTL_event_model_not_physical_paths=True,sequence_start_s=float(first_a),outputs=outputs)


def execute(camp,plan,manifest,entry):
    for rel,digest in plan['snapshot_files'].items():
        if sha(camp/rel)!=digest:raise ValueError(f'rendered circuit snapshot changed: {rel}')
    if plan['pdk_installation_id']!=project.pdk_installation_id():raise ValueError('PDK changed')
    if entry and hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()!=plan['boundary_sha256']:
        raise ValueError('registered producer boundary changed')
    if entry:
        check_output_identity(plan,entry)
        if plan.get('clock_extra_2g',1)!=entry['upstream'].get('clock_extra_2g',1):
            raise ValueError('clock stage count differs from registered probe')
    if entry and plan['fixture_sha256']!=entry['upstream']['fixture_sha256']:
        raise ValueError('clock sources, physical loads or wiring differ from schedule probe')
    original=(camp/'execution/physical_tb.cir').read_text()
    if hashlib.sha256(original.encode()).hexdigest()!=plan['deck_sha256']:raise ValueError('physical deck changed')
    wave=spice.case_output(camp,'run','waveforms.raw',plan['stop_s'])
    print(camp,flush=True)
    if wave is None:
        if any(p.is_relative_to(camp.resolve()) for p in watch.ngspice_cwds()):
            raise RuntimeError('campaign still has a live ngspice; observe it instead of restarting')
        check_runtime_includes(original,camp,plan)
        check_runtime_includes((camp/'execution/smoke_tb.cir').read_text(),camp,plan)
        smoke=spice.run((camp/'execution/smoke_tb.cir').read_text(),spice.next_run_dir(camp,'smoke'),timeout_s=180)
        if not smoke.ok or spice.case_output(camp,'smoke','waveforms.raw',1e-9) is None:raise RuntimeError(f'smoke failed: {smoke.run_dir}')
        ex=spice.run(original,spice.next_run_dir(camp,'run'),timeout_s=180+12*plan['stop_s']/1e-9,
                     meta=dict(resumed_from=str(camp/'execution/physical_tb.cir'),boundary_id=plan['boundary_id']))
        wave=spice.case_output(camp,'run','waveforms.raw',plan['stop_s'])
        if not ex.ok or wave is None:raise RuntimeError(f'incomplete run: {ex.run_dir}')
    try:
        metrics=probe_metrics(wave) if plan['mode']=='probe' else analyse_dynamic(wave,manifest,entry,plan['payload_bits'])
    except (ValueError,KeyError,IndexError) as error:
        (camp/'analysis_error.json').write_text(json.dumps(dict(error=str(error),waveform=str(wave.relative_to(ROOT)),analysis_source_sha256=LOADED_SHA256),indent=2)+'\n')
        raise
    metrics['waveform']=str(wave.relative_to(ROOT));metrics['analysis_source_sha256']=LOADED_SHA256
    directory=camp/'analysis';directory.mkdir(exist_ok=True)
    source=directory/('run_'+LOADED_SHA256+'.py')
    if not source.exists():
        with source.open('xb') as out:out.write(LOADED_SOURCE)
    elif sha(source)!=LOADED_SHA256:raise ValueError('archived analyzer changed')
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+metrics['analysis_source_sha256'][:10]+'.json'
    with (directory/name).open('x') as out:json.dump(metrics,out,indent=2,allow_nan=False);out.write('\n')
    (camp/'summary.json').write_text(json.dumps(metrics,indent=2,allow_nan=False)+'\n')
    print('counter',metrics.get('counter',{}).get('counting'),'input_boundary',metrics.get('input_boundary_ok'),
          'outputs',{k:v['meets_spec'] for k,v in metrics.get('outputs',{}).items()},flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=('probe','prepare','run'))
    p.add_argument('--condition',default='tt_v1800_t27');p.add_argument('--probe',type=Path)
    p.add_argument('--bc');p.add_argument('--stimulus',type=Path);p.add_argument('--resume',type=Path)
    p.add_argument('--clock-extra-2g',type=int,choices=(1,2,3),help='extra buffer stages before the final 2GHz output driver; baseline=1')
    p.add_argument('--clock-output-wt',type=float,help='2GHz output tail width; baseline=24')
    p.add_argument('--clock-output-r',type=float,help='2GHz output nominal load resistance; baseline=300')
    a=p.parse_args()
    for value,name in ((a.clock_output_wt,'clock output wt'),(a.clock_output_r,'clock output resistance')):
        if value is not None and (not math.isfinite(value) or value<=0):p.error(f'{name} must be positive and finite')
    if a.mode=='prepare':
        if a.probe is None:p.error('--probe required')
        probe_plan=json.loads((a.probe/'plan.json').read_text())
        wt,resistance=output_parameters(probe_plan.get('clock_output_wt',24),probe_plan.get('clock_output_r',300))
        if a.clock_extra_2g is not None and a.clock_extra_2g!=probe_plan.get('clock_extra_2g',1):raise ValueError('probe clock stage count differs')
        if a.clock_output_wt is not None and a.clock_output_wt!=wt:raise ValueError('probe clock output wt differs')
        if a.clock_output_r is not None and a.clock_output_r!=resistance:raise ValueError('probe clock output resistance differs')
        prepare(a.probe.resolve());return
    if a.resume:
        camp=a.resume.resolve();plan=json.loads((camp/'plan.json').read_text())
        if plan['mode']!=a.mode:raise ValueError('resume mode differs from original')
        if a.clock_extra_2g is not None and a.clock_extra_2g!=plan.get('clock_extra_2g',1):raise ValueError('resume clock stage count differs')
        wt,resistance=output_parameters(plan.get('clock_output_wt',24),plan.get('clock_output_r',300))
        if a.clock_output_wt is not None and a.clock_output_wt!=wt:raise ValueError('resume clock output wt differs')
        if a.clock_output_r is not None and a.clock_output_r!=resistance:raise ValueError('resume clock output resistance differs')
        if 'snapshot_files' not in plan:raise ValueError('legacy campaign has no rendered checkpoint; keep it as evidence')
        manifest=json.loads((camp/'execution/stimulus_manifest.json').read_text()) if a.mode=='run' else None
        entry=boundary.get(plan['boundary_id']) if a.mode=='run' else None
        execute(camp,plan,manifest,entry);return
    c=Condition.parse(a.condition)
    entry=None;manifest=None
    if a.mode=='probe':
        extra_2g=a.clock_extra_2g if a.clock_extra_2g is not None else 1
        wt,resistance=output_parameters(a.clock_output_wt if a.clock_output_wt is not None else 24,a.clock_output_r if a.clock_output_r is not None else 300)
        data='\n'.join(f'Vd{i} d{i} 0 0' for i in range(16));stop=48e-9
    else:
        if not a.bc or a.stimulus is None:p.error('--bc and --stimulus required')
        entry=boundary.get(a.bc);boundary.check_load(a.bc,boundary.input_stage_signature(DUT,'serdes_tx_capture_serializer16',SELECTS))
        extra_2g=entry['upstream'].get('clock_extra_2g',1)
        wt,resistance=output_parameters(entry['upstream'].get('clock_output_wt',24),entry['upstream'].get('clock_output_r',300))
        if a.clock_output_wt is not None and a.clock_output_wt!=wt:raise ValueError('requested clock output wt differs from registered probe')
        if a.clock_output_r is not None and a.clock_output_r!=resistance:raise ValueError('requested clock output resistance differs from registered probe')
        if a.clock_extra_2g is not None and a.clock_extra_2g!=extra_2g:raise ValueError('requested clock count differs from registered probe')
        if c.tag not in entry['points']:raise ValueError('no matching probe condition')
        for rel,digest in entry['upstream']['physical_sources'].items():
            if sha(ROOT/rel)!=digest:raise ValueError('physical probe circuit changed')
        manifest=json.loads((a.stimulus/'manifest.json').read_text())
        if manifest['boundary_id']!=a.bc:raise ValueError('stimulus boundary mismatch')
        processing=entry['processing'];point=entry['points'][c.tag]
        if manifest['schedule_sha256']!=processing['schedule_sha256'] or sha(ROOT/processing['schedule'])!=processing['schedule_sha256']:
            raise ValueError('stimulus schedule differs from registered probe')
        if point['pdk_installation_id']!=project.pdk_installation_id() or sha(ROOT/point['raw'])!=point['raw_sha256']:
            raise ValueError('probe/PDK identity changed')
        for name,details in manifest['outputs'].items():
            if sha(a.stimulus/name)!=details['sha256']:raise ValueError('stimulus output changed')
        if sha(ROOT/'digital/tx/rtl/tx_ingress_control.sv')!=manifest['rtl_sha256']:
            raise ValueError('controller RTL changed')
        if sha(ROOT/'verification/digital/tx_ingress_stimulus.py')!=manifest['script_sha256']:
            raise ValueError('RTL producer changed')
        data=(a.stimulus/'stimuli.inc').read_text();stop=DATA_STOP
    camp=new_campaign_dir()
    sources=[Path(__file__),HERE/'trace.py',HERE/'tb_full_ngspice.cir.in',EXPECTED,DIST]+[ROOT/x for x in set(FILES)]
    sources += [ROOT/'src/serdes_flow'/x for x in ('spice.py','bias.py','rcorner.py','project.py','clock.py','waves.py','serial.py','boundary.py','watch.py')]
    sources += [ROOT/'config'/x for x in ('pdk.toml','tools.toml')]
    if manifest:sources += [ROOT/'digital/tx/rtl/tx_ingress_control.sv',ROOT/'verification/digital/tx_ingress_stimulus.py']
    identity={str(x.relative_to(ROOT)):sha(x) for x in sources}
    identity[str(Path(__file__).resolve().relative_to(ROOT))]=LOADED_SHA256
    for src in sources:
        dst=camp/'execution'/src.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True)
        if src.resolve()==Path(__file__).resolve():dst.write_bytes(LOADED_SOURCE)
        else:shutil.copyfile(src,dst)
    if manifest:
        (camp/'execution/stimulus_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (camp/'execution/stimuli.inc').write_text(data)
        out=camp/'execution/producer';out.mkdir()
        for name in manifest['outputs']:shutil.copyfile(a.stimulus/name,out/name)
        (camp/'execution/boundary.json').write_text(json.dumps(entry,indent=2)+'\n')
    full=deck(c,data,stop,camp/'snap/run',extra_2g=extra_2g,output_wt=wt,output_r=resistance);smoke=deck(c,data,stop,camp/'snap/smoke',True,extra_2g=extra_2g,output_wt=wt,output_r=resistance)
    (camp/'execution/physical_tb.cir').write_text(full);(camp/'execution/smoke_tb.cir').write_text(smoke)
    checkpoints=[x for root in (camp/'snap',camp/'execution') for x in root.rglob('*') if x.is_file()]
    plan=dict(mode=a.mode,condition=c.tag,stop_s=stop,sources=identity,boundary_id=a.bc,payload_bits=PAYLOAD_BITS,clock_extra_2g=extra_2g,clock_output_wt=wt,clock_output_r=resistance,
              fixture_sha256=fixture_signature(full),deck_sha256=hashlib.sha256(full.encode()).hexdigest(),
              boundary_sha256=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest() if entry else None,
              pdk_installation_id=project.pdk_installation_id(),snapshot_files={str(x.relative_to(camp)):sha(x) for x in checkpoints},
              scope='Actual v3/capture/full serializer/driver, real bias and R tt; ideal 2GHz and unused clock source ports; initialized counter, not PLL/startup/45PVT qualification')
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    execute(camp,plan,manifest,entry)


if __name__=='__main__':main()
