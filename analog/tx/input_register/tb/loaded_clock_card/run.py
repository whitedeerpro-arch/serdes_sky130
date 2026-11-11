"""Current-load Xe3/Xe4/Xout transfer card from explicit full-TX recordings.

Three independent mathematical branches compare frozen generic, minimum-count
fixed, and longer fixed loads. Original generic baseline must match the full
source at the same absolute edges before input amplitude/common-mode sweeps.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np

from serdes_flow import boundary,clock,corners,pdk_overlays,project,pwl_sources,resistor_networks,spice,stage_metrics,watch,waves

ROOT=project.ROOT
HERE=Path(__file__).resolve()
HELPER=ROOT/'analog/tx/input_register/tb/final_retime/window.py'
COLLECTOR=ROOT/'verification/plotting/tx_parallel_serializer.py'
NETWORK_DATA=ROOT/'docs/data/fixed_load_card.json'
OVERLAY_DATA=ROOT/'docs/data/fixed_load_overlay.json'
SOURCES=[ROOT/'results/analog/tx/parallel_serializer/20261110T174242.179572Z_3bc4c61d',
         ROOT/'results/analog/tx/parallel_serializer/20261110T174428.362201Z_104eee55']
POINTS=[dict(id=n,scale=s,cm_shift_v=c) for n,s,c in (
    ('baseline',1.,0.),('weak080',.8,0.),('cm_m25',1.,-.025),('weak080_cm_m25',.8,-.025))]
MODES=('generic','fixed_short','fixed_long')
NODES=dict(ap='xtx.xtree.g3_0p',an='xtx.xtree.g3_0n',bp='xtx.xtree.g3_1p',bn='xtx.xtree.g3_1n',
           ip='xclocks.e2g_2p',inn='xclocks.e2g_2n',vbias='vbias',vbias_logic='xtx.xtree.vbias_logic',vdd='vdd')
REFERENCES={**{f'e{k}{pn}':f'xclocks.e2g_{k}{pn}' for k in (3,4) for pn in ('p','n')},
            'sp':'c2gp','sn':'c2gn','qp':'qp','qn':'qn','lqp':'lqp','lqn':'lqn',
            **{n:'xtx.xtree.xr4_0.'+n for n in ('ahp','ahn','bhp','bhn','sap','san','sbp','sbn')}}
SEGMENTS={n:(4 if n in ('ip','inn') else 2 if n in ('ap','an','bp','bn') else 1) for n in NODES}
PROFILE=[[24.,14.4,320.]]+[[24.,15.6,320.]]*4


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


helper=module('loaded_clock_helper',HELPER);collector=module('loaded_clock_collector',COLLECTOR)
sha=helper.sha


def read(path):return json.loads(path.read_text())
def dump(path,obj):path.write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')


def overlay_identity():
    data=read(OVERLAY_DATA);index=read(ROOT/'results/catalog/fixed_load_overlay.json')
    if index['data_sha256']!=sha(OVERLAY_DATA) or sha(ROOT/data['summary'])!=data['summary_sha256']:
        raise ValueError('overlay publication changed')
    if data['total_passive_points']!=1080 or len(data['TT_transient'])!=10:raise ValueError('unvalidated overlay')
    manifest=ROOT/data['overlay_manifest']
    if sha(manifest)!=data['overlay_manifest_sha256']:raise ValueError('overlay manifest changed')
    value=read(manifest);dest=manifest.parent;changed={c['path']:c['overlay_sha256'] for c in value['changes']}
    for rel,expected in value['source_files'].items():
        if sha(dest/rel)!=changed.get(rel,expected) or sha(Path(value['source_pdk'])/rel)!=expected:
            raise ValueError('source or overlay model changed')
    return dict(data_sha256=sha(OVERLAY_DATA),manifest=str(manifest.relative_to(ROOT)),manifest_sha256=sha(manifest),
                library=value['library'],id=value['id'])


def source_point(source,pre):
    case=collector.collect(source);plan=read(source/'plan.json');summary=read(source/'summary.json')
    if case['clock_stage_profile']!=PROFILE or plan['driver_params']!='rpre=120 wout=192 wtpre=60':
        raise ValueError('unexpected source clock or current driver')
    if not all(case[k] for k in ('input_boundary_ok','halfword_hold_ok','behavioral_tags_align')) or not case['counter']['counting']:
        raise ValueError('source interface/counter failed')
    helper.validate_source_cell(source,plan,snapshot_root='execution')
    raw=ROOT/case['waveform'];w=spice.Waves(raw)
    captures=[r for r in summary['captures'] if r['payload_valid']]
    if captures[18]['word']!=0xdad9:raise ValueError('wrong source word18')
    a=clock.edges(w.t,w['c250p']-w['c250n'],-1,captures[18]['capture_s'])
    b=clock.edges(w.t,w['c250p']-w['c250n'],1,float(a[0]))
    edge=float(b[0]);origin=edge-pre;stop=pre+2.5e-9
    if origin<w.t[0] or origin+stop>w.t[-1]:raise ValueError('unavailable source history')
    t=np.r_[0.,w.t[(w.t>origin)&(w.t<origin+stop)]-origin,stop]
    arrays={'t':t,**{n:np.interp(t+origin,w.t,w[node]) for n,node in NODES.items()},
            **{'ref_'+n:np.interp(t+origin,w.t,w[node]) for n,node in REFERENCES.items()}}
    point=dict(condition=case['condition'],source=str(source.relative_to(ROOT)),raw=str(raw.relative_to(ROOT)),
               raw_sha256=sha(raw),plan_sha256=sha(source/'plan.json'),summary_sha256=sha(source/'summary.json'),
               source_snapshots=plan['snapshot_files'],origin_s=origin,stop_s=stop,B_edge_s=edge,
               source_profile=PROFILE,driver_params=plan['driver_params'],source_outputs={k:summary['outputs'][k]['check'] for k in ('serializer','pad')},
               input_max_over_VDD_v=float(np.max(np.maximum(arrays['ip'],arrays['inn'])-arrays['vdd'])))
    return point,arrays


def fixed_cells(delay,buffer,data):
    lines=[];choices={p['id']:p for p in data['parts']}
    for mode,count in (('short',1),('long',2)):
        for nominal in (320,240):
            p=dict(choices[f'r{nominal}_n{count}'],geometry_minimum_length_um=.5);suffix=f'{mode}_{nominal}'
            primitive=f'serdes_cml_delay_{suffix}';cell=f'serdes_cml_buffer_{suffix}'
            text=delay.replace('serdes_cml_delay',primitive).replace(' rload=400','')
            for name,node in (('Rp','outp'),('Rn','outn')):
                text,n=re.subn(rf'(?m)^XR{name[1:]}\s+vdd\s+{node}\s+0\s+sky130_fd_pr__res_high_po\s+.*$',
                    lambda _m:resistor_networks.instances(name,'vdd',node,'vss',p),text)
                if n!=1:raise ValueError('unexpected frozen generic load')
            wrap=buffer.replace('serdes_cml_buffer',cell).replace('serdes_cml_delay',primitive)
            wrap=wrap.replace(' rload=600','').replace(' rload={rload}','')
            if 'rload' in '\n'.join(x for x in text.splitlines()+wrap.splitlines() if not x.startswith('*')):
                raise ValueError('unused R parameter survived physical implementation')
            lines += [text,wrap]
    return '\n'.join(lines)


def chain(mode,index):
    text=[f'.subckt clock_cut_{index} ip inn e3p e3n e4p e4n cp cn vbias vdd vss']
    for label,inp,out,wn,resistance in (('e3','ip inn','e3p e3n',24,320),('e4','e3p e3n','e4p e4n',24,320),('out','e4p e4n','cp cn',32,240)):
        wt=15.6 if label!='out' else 16
        kind='serdes_cml_buffer' if mode=='generic' else f'serdes_cml_buffer_{mode.split("_")[1]}_{resistance}'
        params=f'wn={wn} wt={wt}'+(f' rload={resistance}' if mode=='generic' else '')
        text.append(f'X{label} {inp} {out} vbias vdd vss {kind} {params}')
    return '\n'.join(text+[f'.ends clock_cut_{index}'])


def probe_spec():
    voltages=list(NODES)
    for i in (1,2,3):
        voltages += [f'{n}{i}' for n in ('e3p','e3n','e4p','e4n','sp','sn','qp','qn','lqp','lqn')]
        voltages += [f'xslice{i}.xfinal.{n}' for n in ('ahp','ahn','bhp','bhn','sap','san','sbp','sbn')]
        voltages += [f'xclock{i}.x{s}.xgain.tail' for s in ('e3','e4','out')]
    props=[]
    for i in (1,2,3):
        for s in ('e3','e4','out'):
            for mos,parameter in (('xtail','id'),('xtail','vdsat'),('xmp','vdsat'),('xmn','vdsat')):
                model='nfet_01v8' if mos=='xtail' else 'nfet_01v8_lvt'
                props.append((f'{s}_{mos}_{parameter}_{i}',f'@m.xclock{i}.x{s}.xgain.{mos}.msky130_fd_pr__{model}[{parameter}]'))
    return voltages,props


def template(camp,tag,point):
    text=helper.TEMPLATE.read_text();condition=corners.Condition.parse(tag)
    text=re.sub(r'(?m)^\.include "@PROJECT_ROOT@/([^"]+)"',lambda m:f'.include "{camp/"snap"/tag/m[1]}"',text)
    text=spice.render(text,MODEL_LIBRARY=point['library'],CORNER=condition.process,SUPPLY=condition.supply,
                      TEMP_C=condition.temp,VECTORS='@VECTORS@',CASES='@CASES@')
    for name in helper.SOURCE_MAP.values():
        text,n=re.subn(rf'(?m)^{name} .*\n','',text)
        if n!=1:raise ValueError('original stimulus source changed')
    source_lines=[s for node,count in SEGMENTS.items() for s in pwl_sources.declarations(node,'Vsrc_'+node,count)]
    text=text.replace('Vtxen ', '\n'.join(source_lines)+'\nVtxen ',1)
    # Enable and charge the isolated downstream fixture before the observed window.
    text=re.sub(r'(?m)^Vtxen .*$',f'Vtxen tx_en 0 PWL(0 0 .20n 0 .25n {condition.supply})',text)
    block=re.search(r'(?ms)^Xslice [^\n]*\n.*?^Rlterm1 [^\n]*$',text)
    if not block:raise ValueError('missing load block')
    block=block.group();result=[]
    renamed={n for n in ('sp','sn','qp','qn','lqp','lqn','llp','lln','lap','lan','ltp','ltn','lxp','lxn','lrp','lrn','lcm')}
    source_deck=(ROOT/point['source']/'execution/physical_tb.cir').read_text()
    expected=helper.lines(source_deck,helper.LOAD_NAMES)
    adjusted=block.replace('serdes_tx_cml_line_driver_lowvt_enable wgatep=32','serdes_tx_cml_line_driver_lowvt_enable wgatep=32 rpre=120 wout=192 wtpre=60')
    if helper.lines(adjusted,helper.LOAD_NAMES)!=expected:raise ValueError('downstream load does not match full source')
    for i,mode in enumerate(MODES,1):
        result += [f'Vsense{i} vdd vc{i} 0',f'Xclock{i} ip inn e3p{i} e3n{i} e4p{i} e4n{i} sp{i} sn{i} vbias vc{i} 0 clock_cut_{i}']
        for line in adjusted.splitlines():
            words=line.split()
            if not words:continue
            result.append(' '.join([words[0]+str(i)]+[word+str(i) if word in renamed else word for word in words[1:]]))
    text=text.replace(block,'\n'.join(result))
    text=text.replace('Vtxen ',f'.include "{camp/"snap"/tag/"clock_variants.spice"}"\nVtxen ',1)
    return text,expected


def runtime_files():
    return [HERE,HELPER,COLLECTOR,helper.TEMPLATE,helper.CELL,Path(pwl_sources.__file__),Path(stage_metrics.__file__),Path(resistor_networks.__file__)]+[
        ROOT/'src/serdes_flow'/f'{n}.py' for n in ('spice','project','boundary','clock','waves','watch','serial','corners','clock_profiles')]+[
        ROOT/'config/tools.toml',ROOT/'config/pdk.toml',Path(project.ngspice())]


def prepare(pre):
    overlay=overlay_identity();networks=read(NETWORK_DATA)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]
    camp=ROOT/'results/analog/tx/loaded_clock_card'/stamp;camp.mkdir(parents=True,exist_ok=False)
    for name in ('snap','prepared','inputs','execution'):(camp/name).mkdir()
    points={};loads={}
    for source in SOURCES:
        point,arrays=source_point(source,pre);tag=point['condition'];point['library']=overlay['library'];points[tag]=point
        np.savez_compressed(camp/'inputs'/f'{tag}.npz',**arrays)
        for rel in helper.DEPENDENCIES+(str(helper.CELL.relative_to(ROOT)),):
            if rel==str(helper.CELL.relative_to(ROOT)):original=helper.CELL
            elif rel.startswith('analog/'):original=source/'snap/run/pdk_resistors'/rel
            else:original=source/'execution'/rel
            if not original.is_file():raise ValueError('missing frozen physical dependency: '+str(original))
            dest=camp/'snap'/tag/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
        delay=(camp/'snap'/tag/'analog/common/cml_buffer/spice/cml_delay_resistive.spice').read_text()
        buffer=(camp/'snap'/tag/'analog/common/cml_buffer/spice/cml_buffer.spice').read_text()
        variants=fixed_cells(delay,buffer,networks)+'\n'+'\n'.join(chain(m,i) for i,m in enumerate(MODES,1))
        (camp/'snap'/tag/'clock_variants.spice').write_text(variants)
        text,load=template(camp,tag,point);loads[tag]=load;(camp/'prepared'/f'{tag}.cir.in').write_text(text)
    signature=boundary.input_stage_signature(chain('generic',1),'clock_cut_1',['ip','inn'])
    entry=dict(id='tx_loaded_clock_'+stamp.replace('.','_'),kind='loaded_internal_port_voltage_replay',
               nodes=NODES,points=points,load=signature,downstream_lines=loads,
               mathematical_branches=list(MODES),
               variant_input_signatures={m:boundary.input_stage_signature(chain(m,i),'clock_cut_'+str(i),['ip','inn']) for i,m in enumerate(MODES,1)},
               load_mismatch_policy='Fixed variants intentionally change the first stage electrical load under prescribed input voltage; upstream impedance and bias feedback are omitted. Recapture is required for adoption.',
               processing=f'Word18 B edge minus {pre:g}s history; 2.5ns posthistory, 10uV PWL compression and exact additive source decomposition.',
               validation=dict(input_error_v=200e-6,waveform_error_v=.005,absolute_clock_edge_error_s=2e-12),
               scope='FS hot and SS cold; rejected graded-clock source, current driver; local loaded clock transfer only. No pad/full-eye/startup/noise or new dimensions qualification.')
    dump(camp/'boundary_proposal.json',entry);shutil.copyfile(NETWORK_DATA,camp/'network_data.json');shutil.copyfile(OVERLAY_DATA,camp/'overlay_data.json')
    paths=runtime_files();sources={str(p):sha(p) for p in paths}
    for path in paths:
        dest=camp/'execution'/str(path).lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    plan=dict(points=POINTS,conditions=list(points),pre_s=pre,stop_s=pre+2.5e-9,evaluation_window_s=[pre-.5e-9,pre+2.4e-9],
              boundary_sha256=boundary_hash(entry),overlay=overlay,sources=sources,
              snapshots={str(p.relative_to(camp)):sha(p) for p in camp.rglob('*') if p.is_file()},
              hypothesis='Clock-only legal R implementations can alter gain, slew, phase and tail compliance at unchanged prescribed bias. Weak input and lower CM must be measured together; no eye or sizing prediction is made from gm alone.',
              numerical_source_segments=SEGMENTS,pdk_installation_id=project.pdk_installation_id(),
              python=sys.version,numpy=np.__version__,ungraded=['upstream impedance and bias feedback','real reference/load joint retune','remaining MOS/passive corners','noise/mismatch','full payload/pad and source clock adoption'])
    dump(camp/'plan.json',plan);check(camp);return camp


def boundary_hash(entry):
    import hashlib
    return hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()


def check(camp,registered=False):
    plan=read(camp/'plan.json');entry=read(camp/'boundary_proposal.json')
    if boundary_hash(entry)!=plan['boundary_sha256'] or plan['points']!=POINTS or plan['overlay']!=overlay_identity():raise ValueError('plan/boundary/overlay changed')
    if (sys.version,np.__version__)!=(plan['python'],plan['numpy']):raise ValueError('runtime versions changed')
    for path,expected in plan['sources'].items():
        if sha(Path(path))!=expected or sha(camp/'execution'/path.lstrip('/'))!=expected:raise ValueError('source changed: '+path)
    for path,expected in plan['snapshots'].items():
        if sha(camp/path)!=expected:raise ValueError('snapshot changed: '+path)
    for tag,point in entry['points'].items():
        source=ROOT/point['source']
        for rel,expected in point['source_snapshots'].items():
            if sha(source/rel)!=expected:raise ValueError('full source snapshot changed')
        for path,key in ((source/'plan.json','plan_sha256'),(source/'summary.json','summary_sha256'),(ROOT/point['raw'],'raw_sha256')):
            if sha(path)!=point[key]:raise ValueError('full source metadata/raw changed')
    if registered:
        if boundary.get(entry['id'])!=entry:raise ValueError('boundary registration differs')
        for mode,i in zip(MODES,(1,2,3)):
            expected=boundary.input_stage_signature(chain(mode,i),f'clock_cut_{i}',['ip','inn'])
            if expected!=entry['variant_input_signatures'][mode]:raise ValueError('variant load signature changed')
            boundary.check_load(entry['id'],expected,allow_mismatch=mode!='generic')
    return plan,entry


def inputs(data,point):
    result={n:np.array(data[n]) for n in NODES};cm=(result['ip']+result['inn'])/2+point['cm_shift_v']
    half=(result['ip']-result['inn'])/2*point['scale'];result['ip'],result['inn']=cm+half,cm-half
    if point['id']!='baseline' and (np.max(np.maximum(result['ip'],result['inn'])-result['vdd'])>1e-12 or min(result['ip'].min(),result['inn'].min())<0):
        raise ValueError('perturbed source would leave the supply rails')
    return result


def render(camp,tag,name):
    plan=read(camp/'plan.json');point=next(p for p in POINTS if p['id']==name);commands=[]
    with np.load(camp/'inputs'/f'{tag}.npz') as data:
        for n,y in inputs(data,point).items():
            t,v=waves.shift_pwl(data['t'],y,0,tolerance_v=1e-5,time_quantum_s=1e-16)
            segments,_=pwl_sources.parts(t,v,SEGMENTS[n]);commands+=pwl_sources.commands('Vsrc_'+n,segments)
    voltages,properties=probe_spec();saves=' '.join(['v('+n+')' for n in voltages]+[f'i(vsense{i})' for i in (1,2,3)]+[p for _,p in properties])
    output=' '.join(['v('+n+')' for n in voltages]+[f'i(vsense{i})' for i in (1,2,3)]+[n for n,_ in properties])
    commands += [f'tran .5p {plan["stop_s"]:.12e} .1n .5p']+[f'let {n}={p}' for n,p in properties]+[f'write {name}.raw {output}']
    text=(camp/'prepared'/f'{tag}.cir.in').read_text()
    return text.replace('@VECTORS@',saves).replace('@CASES@','\n'.join(commands))


def completed(camp,tag,name,plan):
    label=tag+'_'+name;raw=spice.case_output(camp,label,name+'.raw',plan['stop_s'])
    if raw is None:return None
    ex=read(raw.parent/'execution.json');expected=render(camp,tag,name)
    import hashlib
    digest=hashlib.sha256(expected.encode()).hexdigest()
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures']:return None
    if ex.get('condition')!=tag or ex.get('point')!=name or ex['deck_sha256']!=digest or sha(raw.parent/'tb.cir')!=digest:raise ValueError('executed case identity mismatch')
    return raw


def measure(camp,tag,name,raw,plan):
    w=spice.Waves(raw);start,stop=plan['evaluation_window_s'];use=(w.t>=start)&(w.t<=stop)
    point=next(p for p in POINTS if p['id']==name);result=dict(branches=[],input_error_v={})
    with np.load(camp/'inputs'/f'{tag}.npz') as data:
        expected=inputs(data,point)
        for n,y in expected.items():result['input_error_v'][n]=float(np.max(np.abs(w[n]-np.interp(w.t,data['t'],y))))
        result['baseline_fidelity']=None
        if name=='baseline':
            required=['e3p','e3n','e4p','e4n','sp','sn','qp','qn','ahp','ahn','bhp','bhn','sap','san','sbp','sbn']
            errors={}
            for n in required:
                actual=n+'1' if n in ('e3p','e3n','e4p','e4n','sp','sn','qp','qn') else 'xslice1.xfinal.'+n
                errors[n]=float(np.max(np.abs(w[actual][use]-np.interp(w.t[use],data['t'],data['ref_'+n]))))
            edge_errors=[]
            for polarity in (-1,1):
                a=clock.edges(w.t,w['sp1']-w['sn1'],polarity,start,stop)
                b=clock.edges(data['t'],data['ref_sp']-data['ref_sn'],polarity,start,stop)
                for t in b:
                    hits=a[np.abs(a-t)<125e-12]
                    if len(hits)!=1:raise ValueError('missing/ambiguous baseline absolute clock edge')
                    edge_errors.append(float(hits[0]-t))
                if len(a)!=len(b):raise ValueError('baseline absolute edge count differs')
            result['baseline_fidelity']=dict(voltage_errors_v=errors,max_voltage_error_v=max(errors.values()),max_absolute_clock_edge_error_s=max(map(abs,edge_errors)))
    if max(result['input_error_v'].values())>200e-6:raise ValueError('input replay error exceeds gate')
    if name=='baseline':
        result['baseline_fidelity']['passed']=bool(max(errors.values())<=.005 and max(map(abs,edge_errors))<=2e-12)
    for i,mode in enumerate(MODES,1):
        row=dict(mode=mode,status='measured',nodes={},propagation={});result['branches'].append(row)
        row['clock_rail_power_w']=stage_metrics.telemetry(w.t,w['vdd']*w[f'i(vsense{i})'],start,stop)
        for label,p,n in [('input','ip','inn')]+[(k,k+'p'+str(i),k+'n'+str(i)) for k in ('e3','e4')]+[('c2g','sp'+str(i),'sn'+str(i))]:
            y=w[p]-w[n];cm=(w[p]+w[n])/2
            row['nodes'][label]=dict(differential_pp_v=float(np.ptp(y[use])),common_mode_v=stage_metrics.telemetry(w.t,cm,start,stop),
                                     cycles=clock.cycle_amplitudes(w.t,y,start,stop))
        for label,pos,neg in (('e3','e3p','e3n'),('e4','e4p','e4n'),('out','sp','sn')):
            tail=w[f'xclock{i}.x{label}.xgain.tail']
            row['nodes'][label if label!='out' else 'c2g']['tail_current_a']=stage_metrics.telemetry(w.t,w[f'{label}_xtail_id_{i}'],start,stop)
            row['nodes'][label if label!='out' else 'c2g']['tail_headroom_v']=stage_metrics.headroom(w.t,tail,np.zeros_like(tail),w[f'{label}_xtail_vdsat_{i}'],start,stop)
            for mos,drain in (('xmp',neg),('xmn',pos)):
                row['nodes'][label if label!='out' else 'c2g'][mos+'_headroom_v']=stage_metrics.headroom(w.t,w[drain+str(i)],tail,w[f'{label}_{mos}_vdsat_{i}'],start,stop)
        try:
            pairs=[('input_to_e3','ip','inn','e3p'+str(i),'e3n'+str(i)),('e3_to_e4','e3p'+str(i),'e3n'+str(i),'e4p'+str(i),'e4n'+str(i)),('e4_to_c2g','e4p'+str(i),'e4n'+str(i),'sp'+str(i),'sn'+str(i))]
            for label,ap,an,bp,bn in pairs:row['propagation'][label]=stage_metrics.propagation(w.t,w[ap]-w[an],w[bp]-w[bn],start,stop,200e-12)
        except ValueError as exc:row.update(status='clock_function_not_measurable',error=str(exc))
    return result


def register(camp):
    _,entry=check(camp);before=read(boundary.REGISTRY);boundary.register(entry)
    after=read(boundary.REGISTRY)
    if {e['id']:e for e in after}!={e['id']:e for e in before+[entry]}:raise ValueError('unexpected concurrent registry update')
    dump_registry=json.dumps(before+[entry],indent=1,ensure_ascii=False)+'\n';boundary.REGISTRY.write_text(dump_registry)
    check(camp,registered=True)


def resume(camp,baseline_only):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan,_=check(camp,registered=True)
        if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign active')
        archive=spice.next_run_dir(camp/'analysis','measurement');archive.mkdir(parents=True,exist_ok=False)
        report=dict(status='failed',plan_sha256=sha(camp/'plan.json'),rows=[],scope='Loaded clock transfer; current driver but rejected source clock profile. No eye, pad or full TX qualification.')
        order=[(tag,'baseline') for tag in plan['conditions']]+([] if baseline_only else [(tag,p['id']) for p in POINTS[1:] for tag in plan['conditions']])
        try:
            for tag,name in order:
                raw=completed(camp,tag,name,plan)
                if raw is None:
                    if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
                    text=render(camp,tag,name)
                    smoke=re.sub(r'(?m)^tran .+$','tran .5p 1.001n 0 .5p',text)
                    sd=spice.next_run_dir(camp,'smoke_'+tag+'_'+name);ex=spice.run(smoke,sd,timeout_s=180,meta=dict(condition=tag,point=name,kind='smoke'))
                    if not ex.ok or spice.case_output(camp,sd.name,name+'.raw',1.001e-9) is None:raise RuntimeError('smoke failed: '+str(sd))
                    if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
                    run=spice.next_run_dir(camp,tag+'_'+name);ex=spice.run(text,run,timeout_s=480,meta=dict(condition=tag,point=name,boundary_id=read(camp/'boundary_proposal.json')['id'],model_overlay_manifest_sha256=plan['overlay']['manifest_sha256']))
                    if not ex.ok:raise RuntimeError('full case failed: '+str(run))
                    raw=completed(camp,tag,name,plan)
                    if raw is None:raise RuntimeError('incomplete case')
                row=dict(condition=tag,point=name,raw=str(raw.relative_to(ROOT)),evidence={str(p.relative_to(ROOT)):sha(p) for p in (raw,raw.parent/'execution.json',raw.parent/'tb.cir',raw.parent/'simulator.log')})
                report['rows'].append(row);row['result']=measure(camp,tag,name,raw,plan)
                if name=='baseline' and not row['result']['baseline_fidelity']['passed']:raise RuntimeError('source baseline fidelity failed: '+tag)
            report['status']='baselines_validated_DOE_pending' if baseline_only else 'loaded_transfer_DOE_measured_no_adoption'
        except Exception as exc:
            report['error']=f'{type(exc).__name__}: {exc}';raise
        finally:dump(archive/'summary.json',report)
    return archive/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--register',type=Path);g.add_argument('--resume',type=Path)
    p.add_argument('--pre-ns',type=float,default=4.);p.add_argument('--baseline-only',action='store_true');a=p.parse_args()
    if a.prepare:print(prepare(a.pre_ns*1e-9))
    elif a.check:check(a.check.resolve());print('identity verified')
    elif a.register:register(a.register.resolve());print('registered')
    else:print(resume(a.resume.resolve(),a.baseline_only))


if __name__=='__main__':main()
