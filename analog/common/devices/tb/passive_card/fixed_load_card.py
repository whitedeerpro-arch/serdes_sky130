"""Calibrate and compare legal fixed-width parallel CML load implementations.

No DUT rewrite. First calibrate actual TT R(L,Vdrop=.25) and legacy targets;
then plan explicit 2p85 parallel networks and compare five RC corners, three
temperatures and three voltage drops. All short analyses share each deck.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import uuid

import numpy as np

from serdes_flow import project,resistor_networks as networks,scalar_raw,spice,watch

ROOT=project.ROOT
HERE=Path(__file__).resolve()
LENGTHS=(.5,.75,1.,1.5,2.,3.,4.,6.,8.)
TARGETS=(50,120,150,240,320,400,600)
COUNTS={50:(3,4,5,6,8),120:(1,2,3,4),150:(1,2,3),240:(1,2),320:(1,2),400:(1,2),600:(1,2)}
CORNERS=('tt','ll','hh','hl','lh')
TEMPS=(-40,27,85)
DROPS=(.1,.25,.5)
FREQUENCY=2e9
PDK=project.model_library().parents[2]
MAGIC=PDK/'libs.tech/magic/sky130A.tcl'
RUNTIME=[HERE,Path(networks.__file__),Path(scalar_raw.__file__),ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/project.py',
         ROOT/'src/serdes_flow/watch.py',ROOT/'config/tools.toml',ROOT/'config/pdk.toml',Path(project.ngspice())]


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def dump(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
def read(path):return json.loads(path.read_text())


def pdk_identity():
    paths=[MAGIC]+[p for folder in ('libs.tech/ngspice','libs.ref/sky130_fd_pr/spice') for p in (PDK/folder).rglob('*') if p.is_file()]
    return {str(p):sha(p) for p in paths}


def legacy(name,value):
    w=max(1,math.ceil(1012/value));length=(value*w-378)/317
    return dict(id=name,kind='legacy_generic',nominal_ohm=value,w_um=w,length_um=length,
                instance=f'X{name} rail out_{name} 0 sky130_fd_pr__res_high_po w={w} l={length:.12g}')


def calibration_parts():
    return [dict(id=f'length{i}',kind='calibration',length_um=length,
                 instance=f'Xlength{i} rail out_length{i} 0 sky130_fd_pr__res_high_po_2p85 l={length}')
            for i,length in enumerate(LENGTHS)]+[legacy(f'generic{r}',r) for r in TARGETS]


def deck(parts,corner,*,calibration=False):
    lines=['fixed-width CML resistor load planning',f'.lib "{project.model_library()}" {corner}',
           'Vrail rail 0 1.8']
    for p in parts:
        lines+=[f'Vport_{p["id"]} out_{p["id"]} 0 DC 1.55 AC 1',p['instance']]
    lines+=['.options reltol=1e-6 abstol=1p vntol=1n','.control','set num_threads=1','set filetype=binary']
    for temp in ((27,) if calibration else TEMPS):
        for drop in ((.25,) if calibration else DROPS):
            prefix=f't{temp}_d{round(drop*1000)}'
            lines += [f'option temp={temp}']+[f'alter Vport_{p["id"]} dc={1.8-drop:.12g}' for p in parts]+['op']
            lines += [f'let r_{p["id"]}={drop}/i(vport_{p["id"]})' for p in parts]
            lines += [f'write {prefix}_op.raw '+' '.join('r_'+p['id'] for p in parts)]
            if not calibration:
                lines += [f'ac lin 1 {FREQUENCY:.12g} {FREQUENCY:.12g}']
                for p in parts:
                    name=p['id']
                    lines += [f'let rd_{name}=-1/real(i(vport_{name}))',
                              f'let c_{name}=-imag(i(vport_{name}))/(2*pi*{FREQUENCY:.12g})']
                lines += [f'write {prefix}_ac.raw '+' '.join(v+p['id'] for p in parts for v in ('rd_','c_'))]
            lines+=['destroy all']
    return '\n'.join(lines+['quit','.endc','.end',''])


def prepare():
    # The primary geometry source is the installed generator, not its rough rho/val display.
    text=MAGIC.read_text()
    marker='proc sky130::sky130_fd_pr__res_high_po_2p85_defaults {} {'
    segment=text.split(marker)[1].split('\n}')[0]
    if 'lmin 0.50' not in segment:raise ValueError('recheck changed PDK minimum length')
    camp=ROOT/'results/analog/common/devices/fixed_load_card'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False)
    (camp/'prepared').mkdir();(camp/'execution').mkdir()
    parts=calibration_parts()
    (camp/'prepared/calibration.cir').write_text(deck(parts,'tt',calibration=True))
    sources={str(p):sha(p) for p in RUNTIME}
    for name in sources:
        dst=camp/'execution'/name.lstrip('/');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(name,dst)
    plan=dict(status='prepared_not_simulated',sources=sources,pdk_identity=pdk_identity(),
              python=sys.version,numpy=np.__version__,calibration_parts=parts,
              calibration_deck_sha256=sha(camp/'prepared/calibration.cir'),
              targets=list(TARGETS),parallel_choices={str(k):list(v) for k,v in COUNTS.items()},
              corners=list(CORNERS),temperatures=list(TEMPS),voltage_drops=list(DROPS),ac_hz=FREQUENCY,
              geometry=dict(card='2p85',minimum_length_um=.5,length_grid_um=.01,source=str(MAGIC)),
              hypothesis='Actual fixed card has contact voltage coefficient proportional to 1/L. '
                         'Calibrate A+B*L+C/L rather than extrapolate a line below its valid lengths. '
                         'Match existing generic R at TT27C/250mV before comparing corners, voltage coefficient and node capacitance.',
              ungraded=['full TX/PLL/bias circuit response','layout routing and DRC/LVS','EM/current density',
                        'noise and mismatch','supply response and temperature self-heating','new dimensions adoption'])
    dump(camp/'plan.json',plan);return camp


def check(camp):
    plan=read(camp/'plan.json')
    if plan['sources']!={str(p):sha(p) for p in RUNTIME} or plan['pdk_identity']!=pdk_identity():
        raise ValueError('runner/runtime/PDK identity changed')
    for path,expected in plan['sources'].items():
        if sha(camp/'execution'/path.lstrip('/'))!=expected:raise ValueError('execution source changed')
    if (plan['python'],plan['numpy'])!=(sys.version,np.__version__):raise ValueError('runtime version changed')
    if sha(camp/'prepared/calibration.cir')!=plan['calibration_deck_sha256']:raise ValueError('calibration deck changed')
    return plan


def complete(camp,label,text,outputs):
    candidates=[camp/label]+[p for p in camp.glob(label+'.r*') if p.name.rsplit('.r',1)[1].isdigit()]
    expected=hashlib.sha256(text.encode()).hexdigest()
    for p in sorted(candidates,key=lambda p:spice._rerun_index(p,label),reverse=True):
        try:
            ex=read(p/'execution.json')
            if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures']:continue
            if ex['deck_sha256']!=expected or sha(p/'tb.cir')!=expected:raise ValueError('executed deck identity mismatch')
            if ex.get('ngspice')!=project.ngspice() or ex.get('pdk_installation_id')!=project.pdk_installation_id():raise ValueError('executed simulator/PDK differs')
            for name in outputs:
                scalar_raw.read(p/name,frequency_hz=FREQUENCY if name.endswith('_ac.raw') else None)
            return p
        except (FileNotFoundError,KeyError):continue
    return None


def run_case(camp,label,text,outputs):
    existing=complete(camp,label,text,outputs)
    if existing is not None:return existing
    if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
    run=spice.next_run_dir(camp,label)
    ex=spice.run(text,run,timeout_s=180,meta=dict(case=label,kind='short_DC_AC_card'))
    if not ex.ok:raise RuntimeError(f'case failed: {run}')
    result=complete(camp,label,text,outputs)
    if result is None:raise RuntimeError(f'missing complete output: {run}')
    return result


def manifest_run(run,outputs):
    return {str(p.relative_to(ROOT)):sha(p) for p in
            [run/'tb.cir',run/'execution.json',run/'simulator.log']+[run/name for name in outputs]}


def make_networks(calibration):
    w=scalar_raw.read(calibration/'t27_d250_op.raw')
    values=[w[f'r_length{i}'] for i in range(len(LENGTHS))]
    coeff,error=networks.fit(LENGTHS,values)
    if error>1e-3:raise ValueError('TT length model is not accurate enough for geometry planning')
    choices=[];parts=[]
    for target in TARGETS:
        baseline=legacy(f'generic{target}',target);parts.append(baseline)
        measured=w[f'r_generic{target}']
        for count in COUNTS[target]:
            plan=networks.parallel(measured,count,coeff)
            choice=dict(nominal_ohm=target,legacy_TT250mV_ohm=measured,parallel_count=count,
                        status='no_legal_geometry' if plan is None else 'planned',geometry=plan)
            choices.append(choice)
            if plan is not None:
                name=f'r{target}_n{count}';choice['id']=name
                parts.append(dict(id=name,kind='fixed_parallel',nominal_ohm=target,**plan,
                                  instance=networks.instances(name,'rail','out_'+name,'0',plan)))
    parts.append(dict(id='reference',kind='reference_tracking',length_um=42.36,
                      instance='Xreference rail out_reference 0 sky130_fd_pr__res_high_po_1p41 l=42.36'))
    return dict(coefficients_ohm=[float(x) for x in coeff],fit_max_error_ohm=error,
                lengths_um=list(LENGTHS),calibration_resistances_ohm=values,choices=choices,parts=parts)


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        check(camp)
        if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign already active')
        output=spice.next_run_dir(camp/'analysis','measurement');output.mkdir(parents=True,exist_ok=False)
        report=dict(status='failed',plan_sha256=sha(camp/'plan.json'),rows=[],evidence={})
        try:
            caltext=(camp/'prepared/calibration.cir').read_text()
            calibration=run_case(camp,'calibration',caltext,['t27_d250_op.raw'])
            model=make_networks(calibration)
            proposed=camp/'networks.json'
            if proposed.exists() and read(proposed)!=model:raise ValueError('planned networks changed; new campaign required')
            if not proposed.exists():dump(proposed,model)
            report.update(networks_sha256=sha(proposed),model=model)
            report['evidence'].update(manifest_run(calibration,['t27_d250_op.raw']))
            for corner in CORNERS:
                text=deck(model['parts'],corner)
                dest=camp/'prepared'/f'{corner}.cir'
                if dest.exists() and dest.read_text()!=text:raise ValueError('prepared case changed')
                if not dest.exists():dest.write_text(text)
                outputs=[f't{t}_d{round(d*1000)}_{kind}.raw' for t in TEMPS for d in DROPS for kind in ('op','ac')]
                run=run_case(camp,corner,text,outputs)
                report['evidence'].update(manifest_run(run,outputs))
                for temp in TEMPS:
                    for drop in DROPS:
                        prefix=f't{temp}_d{round(drop*1000)}'
                        op,ac=scalar_raw.read(run/(prefix+'_op.raw')),scalar_raw.read(run/(prefix+'_ac.raw'),frequency_hz=FREQUENCY)
                        for part in model['parts']:
                            name=part['id'];r=op['r_'+name];rd=ac['rd_'+name];cap=ac['c_'+name]
                            if r<=0 or rd<=0 or cap<=0:raise ValueError('nonpositive passive measurement')
                            report['rows'].append(dict(corner=corner,temp_c=temp,drop_v=drop,id=name,
                                                       resistance_ohm=r,incremental_resistance_ohm=rd,node_capacitance_f=cap))
            report['status']='passive_measurements_complete_not_circuit_qualified'
        except Exception as exc:
            report['error']=f'{type(exc).__name__}: {exc}';raise
        finally:dump(output/'summary.json',report)
    return output/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--check',type=Path);a=p.parse_args()
    if a.prepare:print(prepare())
    elif a.check:print(check(a.check.resolve())['status'])
    else:print(resume(a.resume.resolve()))


if __name__=='__main__':main()
