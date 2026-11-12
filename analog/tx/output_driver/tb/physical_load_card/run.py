"""Frozen paired clean-input driver with explicit fixed-poly load variants.

Prepare and resume are separate. Generic calibration gates precede every
candidate. Each case recomputes its own DC solution; no startup claim.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import uuid

import numpy as np
from serdes_flow import boundary, clock, project, spice, stage_metrics, watch

ROOT=project.ROOT
HERE=Path(__file__).resolve()
PARENT=ROOT/'results/analog/tx/output_driver/coupling_state/20261112T043742.580713Z_66e65343'
PAIR=ROOT/'analog/tx/output_driver/tb/coupling_state/run.py'
WIDE=ROOT/'docs/data/wide_load_card.json'
WIDE_INDEX=ROOT/'results/catalog/wide_load_card.json'
COUPLING=ROOT/'docs/data/tx_coupling_state.json'
BC_ID='tx_driver_clean_pair_20261112_v1'
MODES=('generic','fixed_2p85','fixed_5p73')
TAGS=('fs_v1650_t85','ff_v1950_t-40')
NAMES={'fixed_2p85':('r120_2p85_n6','r50_2p85_n24'), 'fixed_5p73':('r120_5p73_n3','r50_5p73_n12')}
REL_DRIVER='analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice'
REL_DELAY='analog/common/cml_buffer/spice/cml_delay_resistive.spice'
REL_BUFFER='analog/common/cml_buffer/spice/cml_buffer.spice'


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
pair=module('physical_load_pair',PAIR)
wide=module('physical_load_wide',ROOT/'analog/common/devices/tb/passive_card/wide_load_card.py')
sha=pair.sha
read=pair.read
dump=pair.dump


def load_identity():
    data=read(WIDE);idx=read(WIDE_INDEX)
    if idx['data_sha256']!=sha(WIDE) or sha(ROOT/data['summary'])!=data['summary_sha256'] or data['overlay']!=wide.overlay():raise ValueError('wide source/overlay identity changed')
    parts={p['id']:p for p in data['parts']};chosen={}
    for mode,ids in NAMES.items():
        selected=[parts[n] for n in ids]
        if [(p['nominal_ohm'],p['parallel_count'],p['card']) for p in selected] != ([(120,6,'2p85'),(50,24,'2p85')] if mode=='fixed_2p85' else [(120,3,'5p73'),(50,12,'5p73')]):raise ValueError('candidate network differs')
        chosen[mode]=[dict(id=p['id'],length_um=p['length_um'],parallel_count=p['parallel_count'],card=p['card']) for p in selected]
    return dict(wide_sha256=sha(WIDE),wide_index_sha256=sha(WIDE_INDEX),overlay=data['overlay'],networks=chosen)


def source_refs():
    p=pair.check(PARENT);entry=boundary.get(BC_ID)
    if entry['source_data']['path']!=str(COUPLING.relative_to(ROOT)) or entry['source_data']['sha256']!=sha(COUPLING):raise ValueError('boundary source data mismatch')
    if entry['validation']!={'baseline_max_abs_node_error_v':.001,'baseline_max_abs_edge_error_s':.2e-12,'baseline_current_peak_rms_relative_error':.01}:raise ValueError('boundary validation gate differs')
    if p['conditions']!=list(TAGS) or abs(p['stop_s']-92e-9)>1e-18:raise ValueError('parent stimulus identity differs')
    refs={}
    for tag in TAGS:
        raw=pair.completed(PARENT,tag,p);point=entry['points'][tag];run=boundary.point_run(BC_ID,tag)
        if raw is None or raw.parent!=run or sha(raw)!=point['waveform_sha256'] or sha(run/'tb.cir')!=point['deck_sha256']:raise ValueError('boundary parent case mismatch')
        for key in ('prepared_deck','stimulus','input_cell'):
            if sha(ROOT/point[key])!=point[key+'_sha256']:raise ValueError('boundary source mismatch: '+key)
        refs[tag]=dict(raw=str(raw.relative_to(ROOT)),raw_sha256=sha(raw),deck_sha256=sha(PARENT/'prepared'/tag/'tb.cir'),stim_sha256=sha(PARENT/'prepared'/tag/'stimuli.inc'),
            execution_sha256=sha(raw.parent/'execution.json'),log_sha256=sha(raw.parent/'simulator.log'))
    return dict(boundary=entry,parent_plan_sha256=sha(PARENT/'plan.json'),coupling_sha256=sha(COUPLING),parent_plan=p,points=refs)


def variant_cells(driver,delay,buffer,mode,networks):
    if mode=='generic':return ''
    pre,term=networks[mode]; width=pre['card']; suffix=mode
    def replace_load(text,group,network):
        for side,node in (('p','outp'),('n','outn')) if group=='pre' else (('p','qp'),('n','qn')):
            pattern=rf'(?m)^XR{side}\s+\S+\s+{node}\s+0\s+sky130_fd_pr__res_high_po\s+.*$'
            rail='vdd' if group=='pre' else 'vdd_out'
            lines='\n'.join(f'XR{side}_{i} {rail} {node} vss sky130_fd_pr__res_high_po_{width} l={network["length_um"]:.8f}' for i in range(network['parallel_count']))
            text,n=re.subn(pattern,lambda _:lines,text)
            if n!=1:raise ValueError('unexpected '+group+' resistor')
        return text
    delay=replace_load(delay,'pre',pre).replace('serdes_cml_delay','pre_delay_'+suffix)
    buffer=buffer.replace('serdes_cml_buffer','pre_buffer_'+suffix).replace('serdes_cml_delay','pre_delay_'+suffix)
    driver=replace_load(driver,'term',term).replace('serdes_tx_cml_line_driver_lowvt_enable','driver_'+suffix)
    driver,n=re.subn(r'(?m)^(Xpre .*?)serdes_cml_buffer\b',r'\1pre_buffer_'+suffix,driver)
    if n!=1:raise ValueError('Xpre changed')
    return '\n'.join((delay,buffer,driver))+'\n'


def probes(mode,networks):
    nodes=['vdd','vbias','vgi_bias','bias_vbg','qp','qn'];props=[];groups={}
    for i in (1,2):
        nodes += [n+str(i) for n in ('lqp','lqn','lrp','lrn','lap','lan','ltp','ltn')]
        nodes += [f'xdriver{i}.'+n for n in ('ip','in','gp','gn','tail','vbtail')]
        nodes += [f'xdriver{i}.xpre.xgain.tail']
        for group in ('term','pre'):
            for side in ('p','n'):
                count=1 if mode=='generic' else networks[mode][1 if group=='term' else 0]['parallel_count']
                card=None if mode=='generic' else networks[mode][0]['card'];base=f'xdriver{i}.'+('' if group=='term' else 'xpre.xgain.')
                keys=[]
                for j in range(count):
                    name=f'{group}_{side}{i}_{j}';instance=f'xr{side}' if mode=='generic' else f'xr{side}_{j}'
                    element='rbody' if mode=='generic' else 'rhrpoly_'+card
                    props.append((name,f'@r.{base}{instance}.{element}[i]'));keys.append(name)
                groups[f'{group}_{side}{i}']=keys
        for kind,path in (('itail',f'xdriver{i}.xt.xmos'),('pre_itail',f'xdriver{i}.xpre.xgain.xtail')):
            for parameter in ('id','vdsat'):
                props.append((f'{kind}_{parameter}{i}',f'@m.{path}.msky130_fd_pr__nfet_01v8[{parameter}]'))
    return nodes,props,groups


def deck(text,mode,networks,library,variant_path):
    text,n=re.subn(r'(?m)^\.lib "[^"]+" (\S+)$',lambda m:f'.lib "{library}" {m[1]}',text)
    if n!=1:raise ValueError('model library line changed')
    if mode!='generic':
        text=text.replace('.include "stimuli.inc"',f'.include "{variant_path}"\n.include "stimuli.inc"')
        text,n=re.subn(r'(?m)^(Xdriver[12] .*?)\bserdes_tx_cml_line_driver_lowvt_enable\b',r'\1driver_'+mode,text)
        if n!=2:raise ValueError('driver pair not replaced')
    nodes,props,groups=probes(mode,networks)
    saves=['v('+n+')' for n in nodes]+[f'i(vsense{i})' for i in (1,2)]+[p for _,p in props]
    text,n=re.subn(r'(?m)^\.save .+$','.save '+' '.join(saves),text)
    if n!=1:raise ValueError('save line changed')
    cmd=['.control','set num_threads=1','set filetype=binary','tran 2p 9.200000000000002e-08 0 2p']
    cmd += [f'let {n}={p}' for n,p in props]
    # Stable legacy names permit the existing paired measurement to be reused.
    for i in (1,2):
        for alias,group in ((f'irp{i}',f'term_p{i}'),(f'irn{i}',f'term_n{i}')):
            cmd.append('let '+alias+'='+'+'.join(groups[group]))
        cmd += [f'let itail{i}=itail_id{i}',f'let vdsat{i}=itail_vdsat{i}']
    outputs=['v('+n+')' for n in nodes]+[f'i(vsense{i})' for i in (1,2)]+[n for n,_ in props]+[f'{p}{i}' for i in (1,2) for p in ('irp','irn','itail','vdsat')]
    cmd += ['write waveforms.raw '+' '.join(outputs),'quit','.endc']
    text,n=re.subn(r'(?ms)^\.control\n.*?^\.endc$',lambda _:'\n'.join(cmd),text)
    if n!=1:raise ValueError('control changed')
    return text


def prepare():
    ident=load_identity();source=source_refs();camp=ROOT/'results/analog/tx/output_driver/physical_load_card'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);camp.mkdir(parents=True)
    for tag in TAGS:
        dest=camp/'prepared'/tag;dest.mkdir(parents=True)
        parenttext=(PARENT/'prepared'/tag/'tb.cir').read_text()
        for raw in re.findall(r'(?m)^\.include "([^"]+)"',parenttext):
            if raw=='stimuli.inc':continue
            original=Path(raw)
            if not original.is_file():raise ValueError('missing included source '+raw)
            if re.search(r'(?im)^\s*\.(?:include|lib)\b',original.read_text()):
                raise ValueError('nested include needs an explicit frozen dependency: '+raw)
            rel=original.relative_to(ROOT);target=camp/'snap'/tag/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
            parenttext=parenttext.replace('"'+raw+'"','"'+str(target)+'"')
        shutil.copyfile(PARENT/'prepared'/tag/'stimuli.inc',dest/'stimuli.inc')
        snap=PARENT/'snap'/tag/'pdk_resistors';cells=[(snap/p).read_text() for p in (REL_DRIVER,REL_DELAY,REL_BUFFER)]
        for mode in MODES:
            variant=dest/(mode+'.spice');variant.write_text(variant_cells(*cells,mode,ident['networks']))
            driver_text=cells[0] if mode=='generic' else variant.read_text()
            signature=boundary.input_stage_signature(driver_text,'serdes_tx_cml_line_driver_lowvt_enable' if mode=='generic' else 'driver_'+mode,('inp','inn'))
            boundary.check_load(BC_ID,signature)
            (dest/(mode+'.cir')).write_text(deck(parenttext,mode,ident['networks'],ident['overlay']['library'],variant))
    paths=[HERE,PAIR,pair.DDJ,pair.ddj.TEMPLATE,pair.ddj.DRIVER,pair.ddj.BUFFER,Path(wide.__file__),Path(wide.base.__file__),Path(spice.__file__),Path(stage_metrics.__file__),Path(clock.__file__),Path(boundary.__file__),Path(watch.__file__),Path(pair.serial.__file__),Path(pair.bias.__file__),ROOT/'src/serdes_flow/rcorner.py',Path(project.__file__),Path(project.ngspice()),ROOT/'config/ngspice/spiceinit',ROOT/'config/pdk.toml',ROOT/'config/tools.toml',WIDE,WIDE_INDEX,COUPLING]
    for p in paths:
        target=camp/'execution'/str(p).lstrip('/');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
    plan=dict(identity=ident,source=source,conditions=list(TAGS),modes=list(MODES),stop_s=source['parent_plan']['stop_s'],
              baseline_gate=dict(single_ended_v=.001,absolute_edge_s=.2e-12,current_peak_rms_relative=.01),python=sys.version,numpy=np.__version__,
              sources={str(p):sha(p) for p in paths},snapshots={str(p.relative_to(camp)):sha(p) for d in ('snap','prepared') for p in (camp/d).rglob('*') if p.is_file()},
              scope='Clean prescribed input, two coupled histories sharing one real generic bias per case; independent OP per mode; no startup/full TX/PVT/noise/EM qualification.')
    dump(camp/'plan.json',plan);check(camp);return camp


def check(camp):
    p=read(camp/'plan.json')
    if p['identity']!=load_identity() or p['source']!=source_refs() or (p['python'],p['numpy'])!=(sys.version,np.__version__):raise ValueError('source or runtime changed')
    for path,h in p['sources'].items():
        if sha(path)!=h or sha(camp/'execution'/path.lstrip('/'))!=h:raise ValueError('source changed')
    for path,h in p['snapshots'].items():
        if sha(camp/path)!=h:raise ValueError('snapshot changed')
    return p


def completed(camp,tag,mode,plan):
    raw=spice.case_output(camp,tag+'_'+mode,'waveforms.raw',plan['stop_s'])
    if raw is None:return None
    ex=read(raw.parent/'execution.json'); deckpath=camp/'prepared'/tag/(mode+'.cir')
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures']:return None
    if ex['deck_sha256']!=sha(deckpath) or sha(raw.parent/'tb.cir')!=ex['deck_sha256'] or sha(raw.parent/'stimuli.inc')!=sha(camp/'prepared'/tag/'stimuli.inc') or ex.get('condition')!=tag or ex.get('mode')!=mode:raise ValueError('execution identity differs')
    return raw


def rms(t,y):return float(np.sqrt(np.trapezoid(y*y,t)/(t[-1]-t[0])))


def measure(raw,plan,mode):
    w=spice.Waves(raw);nodes,props,groups=probes(mode,plan['identity']['networks']);t=w.t
    # Explicit completeness check before inheriting existing eye and mapping analysis.
    for n in nodes+[p[0] for p in props]:
        if not np.all(np.isfinite(w[n])):raise ValueError('nonfinite probe '+n)
    result=pair.measure(raw,plan['source']['parent_plan']);result['resistors']={}
    for group,names in groups.items():
        currents=[w[n] for n in names];total=np.sum(currents,axis=0)
        metrics=lambda y:dict(peak_abs_a=float(np.max(abs(y))),rms_a=rms(t,y))
        result['resistors'][group]=dict(total=metrics(total),individual=[metrics(y) for y in currents])
    result['initial']={f'{n}{i}':float(w[f'{n}{i}'][0]) for i in (1,2) for n in ('lqp','lqn','lrp','lrn','lap','lan','ltp','ltn')}
    for i in (1,2):
        for leg in ('p','n'):result['initial'][f'coupling_{leg}{i}']=float(w[f'la{leg}{i}'][0]-w[f'lt{leg}{i}'][0])
    result['predriver']=[]
    for i in (1,2):
        tail=w[f'xdriver{i}.xpre.xgain.tail'];vd=w[f'pre_itail_vdsat{i}']
        result['predriver'].append(dict(branch=i,
            current_a=stage_metrics.telemetry(t,w[f'pre_itail_id{i}'],10e-9,90e-9),
            headroom_v=stage_metrics.headroom(t,tail,np.zeros_like(t),vd,10e-9,90e-9),
            output_common_mode_v=stage_metrics.telemetry(t,(w[f'xdriver{i}.gp']+w[f'xdriver{i}.gn'])/2,10e-9,90e-9)))
        result['initial'][f'output_DC_current_balance_a{i}']=float(w[f'irp{i}'][0]+w[f'irn{i}'][0]-w[f'itail{i}'][0])
        result['initial'][f'pre_DC_current_balance_a{i}']=float(sum(w[n][0] for n in groups[f'pre_p{i}']+groups[f'pre_n{i}'])-w[f'pre_itail_id{i}'][0])
    return result


def baseline(raw,reference,plan):
    w=spice.Waves(raw);old=spice.Waves(reference);start=old.t[0];stop=min(old.t[-1],w.t[-1]);use=(w.t>=start)&(w.t<=stop)
    names=['vdd','vbias','bias_vbg','qp','qn']+[n+str(i) for i in (1,2) for n in ('lqp','lqn','lrp','lrn')]+[f'xdriver{i}.{n}' for i in (1,2) for n in ('tail','vbtail')]
    err={n:float(np.max(abs(w[n][use]-np.interp(w.t[use],old.t,old[n])))) for n in names};edges={}
    for i in (1,2):
        for label in ('lq','lr'):
            diffs=[]
            for pol in (-1,1):
                a=clock.edges(old.t,old[f'{label}p{i}']-old[f'{label}n{i}'],pol,8e-9,stop)
                b=clock.edges(w.t,w[f'{label}p{i}']-w[f'{label}n{i}'],pol,8e-9,stop)
                if len(a)!=len(b) or not len(a) or np.any(abs(a-b)>=125e-12):raise ValueError('baseline missing/ambiguous edges')
                diffs.extend(abs(a-b))
            edges[f'{label}{i}']=float(max(diffs))
    currents={}
    for i in (1,2):
        for prefix in ('irp','irn','itail'):
            name=f'{prefix}{i}';a=old[name];b=np.interp(old.t,w.t,w[name]);
            for typ,ma,mb in (('peak',np.max(abs(a)),np.max(abs(b))),('rms',rms(old.t,a),rms(old.t,b))):
                if ma<=0:raise ValueError('invalid current baseline')
                currents[name+'_'+typ]=float(abs(mb/ma-1))
    gate=plan['baseline_gate'];return dict(voltage_errors_v=err,edge_errors_s=edges,current_relative_errors=currents,
       passed=max(err.values())<=gate['single_ended_v'] and max(edges.values())<=gate['absolute_edge_s'] and max(currents.values())<=gate['current_peak_rms_relative'])


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan=check(camp)
        if any(p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign active')
        dest=spice.next_run_dir(camp/'analysis','measurement');dest.mkdir(parents=True);report=dict(status='failed',plan_sha256=sha(camp/'plan.json'),rows=[])
        try:
            for mode in MODES:
                for tag in TAGS:
                    raw=completed(camp,tag,mode,plan);text=(camp/'prepared'/tag/(mode+'.cir')).read_text();stim=camp/'prepared'/tag/'stimuli.inc'
                    if raw is None:
                        if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
                        smoke=re.sub(r'(?m)^tran .+$','tran 2p 1.001n 0 2p',text);sd=spice.next_run_dir(camp,'smoke_'+tag+'_'+mode)
                        ex=spice.run(smoke,sd,files={'stimuli.inc':stim},timeout_s=180)
                        if not ex.ok or spice.case_output(camp,sd.name,'waveforms.raw',1.001e-9) is None:raise RuntimeError('smoke failed')
                        if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
                        ex=spice.run(text,spice.next_run_dir(camp,tag+'_'+mode),files={'stimuli.inc':stim},timeout_s=480,meta=dict(condition=tag,mode=mode))
                        if not ex.ok:raise RuntimeError('simulation failed')
                        raw=completed(camp,tag,mode,plan)
                        if raw is None:raise RuntimeError('incomplete waveform')
                    row=dict(condition=tag,mode=mode,raw=str(raw.relative_to(ROOT)),evidence={str(p.relative_to(ROOT)):sha(p) for p in (raw,raw.parent/'tb.cir',raw.parent/'stimuli.inc',raw.parent/'execution.json',raw.parent/'simulator.log')})
                    report['rows'].append(row);row['result']=measure(raw,plan,mode)
                    if mode=='generic':
                        row['baseline']=baseline(raw,ROOT/plan['source']['points'][tag]['raw'],plan)
                        if not row['baseline']['passed']:raise RuntimeError('generic baseline gate failed: '+tag)
            report['status']='local_physical_loads_measured_no_adoption'
        except Exception as exc:report['error']=f'{type(exc).__name__}: {exc}';raise
        finally:dump(dest/'summary.json',report)
    return dest/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True);g.add_argument('--prepare',action='store_true');g.add_argument('--check',type=Path);g.add_argument('--resume',type=Path);a=p.parse_args()
    print(prepare() if a.prepare else check(a.check.resolve()) if a.check else resume(a.resume.resolve()))


if __name__=='__main__':main()
