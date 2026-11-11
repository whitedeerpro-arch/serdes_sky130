"""Validate isolated signed-cube PDK overlay against the complete passive card.

Reuse the exact physical networks; compare unchanged DC/C and AC against a
centered DC differential at every RC/T/voltage point, plus tiny transient.
Installed PDK and existing campaigns remain untouched.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import shutil
import uuid

from serdes_flow import pdk_overlays,project,scalar_raw,spice,watch

ROOT=project.ROOT
HERE=Path(__file__).resolve()


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


base=module('overlay_parent',HERE.with_name('fixed_load_card.py'))
diag=module('overlay_transient',HERE.with_name('fixed_load_ac_check.py'))
DELTA=1e-4


def deck(parts,corner,library):
    text=base.deck(parts,corner).replace(str(project.model_library()),str(library))
    # Insert symmetric finite-difference OPs after the original nominal OP write.
    def extra(match):
        name=match[1];drop=int(re.search(r'_d(\d+)$',name)[1])/1000
        lines=[match[0]]
        for label,offset in (('low',-DELTA),('high',DELTA)):
            lines += [f'alter Vport_{p["id"]} dc={1.8-drop-offset:.12g}' for p in parts]+['op']
            lines += [f'let fd_{p["id"]}=i(vport_{p["id"]})' for p in parts]
            lines += [f'write {name}_{label}.raw '+' '.join('fd_'+p['id'] for p in parts)]
        lines += [f'alter Vport_{p["id"]} dc={1.8-drop:.12g}' for p in parts]+['op']
        return '\n'.join(lines)
    text,count=re.subn(r'(?m)^write (t-?\d+_d\d+)_op\.raw .+$',extra,text)
    if count!=9:raise ValueError('unexpected DC/AC grid')
    return text


def prepare(parent,summary):
    base.check(parent);original=base.read(summary)
    if original['status']!='passive_measurements_complete_not_circuit_qualified':raise ValueError('parent not complete')
    if original['networks_sha256']!=base.sha(parent/'networks.json'):raise ValueError('networks changed')
    for path,expected in original['evidence'].items():
        if base.sha(ROOT/path)!=expected:raise ValueError('parent evidence changed')
    camp=ROOT/'results/analog/common/devices/fixed_load_overlay'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False);(camp/'prepared').mkdir();(camp/'execution').mkdir()
    overlay=pdk_overlays.fixed_poly_library(camp/'models')
    model=base.read(parent/'networks.json');shutil.copyfile(parent/'networks.json',camp/'networks.json')
    for rc in base.CORNERS:(camp/'prepared'/f'{rc}.cir').write_text(deck(model['parts'],rc,overlay['library']))
    parts=[p for p in model['parts'] if p['id'] in diag.IDS]
    (camp/'prepared/transient.cir').write_text(diag.deck(parts).replace(str(project.model_library()),overlay['library']))
    paths=list(dict.fromkeys(base.RUNTIME+[HERE,Path(pdk_overlays.__file__),diag.HERE]))
    for p in paths:
        dest=camp/'execution'/str(p).lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    plan=dict(parent=str(parent.relative_to(ROOT)),parent_summary=str(summary.relative_to(ROOT)),parent_summary_sha256=base.sha(summary),
              networks_sha256=base.sha(camp/'networks.json'),overlay_manifest_sha256=base.sha(camp/'models/overlay.json'),
              sources={str(p):base.sha(p) for p in paths},DC_half_step_v=DELTA,
              prepared={str(p.relative_to(camp)):base.sha(p) for p in (camp/'prepared').glob('*.cir')},
              numerical_gates=dict(DC_relative_change=1e-8,C_relative_change=1e-8,AC_to_DC_differential_relative=1e-3),
              ungraded=['full circuit and operating range adoption','noise/mismatch regression','layout parasitics/EM','other simulator modes or PDK revisions'])
    base.dump(camp/'plan.json',plan);return camp


def check(camp):
    plan=base.read(camp/'plan.json');parent=ROOT/plan['parent'];base.check(parent)
    if base.sha(ROOT/plan['parent_summary'])!=plan['parent_summary_sha256'] or base.sha(camp/'networks.json')!=plan['networks_sha256']:
        raise ValueError('parent/network identity changed')
    for path,expected in plan['sources'].items():
        if base.sha(Path(path))!=expected or base.sha(camp/'execution'/path.lstrip('/'))!=expected:raise ValueError('source changed')
    if base.sha(camp/'models/overlay.json')!=plan['overlay_manifest_sha256']:raise ValueError('overlay manifest changed')
    overlay=base.read(camp/'models/overlay.json');changes={c['path']:c['overlay_sha256'] for c in overlay['changes']}
    for path,expected in overlay['source_files'].items():
        if base.sha(camp/'models'/path)!=changes.get(path,expected):raise ValueError('undeclared overlay change')
        if base.sha(Path(overlay['source_pdk'])/path)!=expected:raise ValueError('original PDK changed')
    for rel,expected in plan['prepared'].items():
        if base.sha(camp/rel)!=expected:raise ValueError('prepared deck changed')
    return plan


def run_case(camp,label,outputs):
    text=(camp/'prepared'/f'{label}.cir').read_text()
    run=base.complete(camp,label,text,outputs) if label!='transient' else None
    if label=='transient':
        raw=spice.case_output(camp,label,'transient.raw',3e-9)
        if raw is not None:
            ex=base.read(raw.parent/'execution.json')
            if ex['exit_code']==0 and not ex['log_failures'] and not ex['timed_out'] and ex['deck_sha256']==base.sha(camp/'prepared/transient.cir') and base.sha(raw.parent/'tb.cir')==ex['deck_sha256']:run=raw.parent
    if run is None:
        if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
        destination=spice.next_run_dir(camp,label)
        ex=spice.run(text,destination,timeout_s=240,meta=dict(kind='fixed_poly_cube_overlay_validation',case=label,
                     model_overlay_sha256=base.sha(camp/'models/overlay.json')))
        if not ex.ok:raise RuntimeError(f'case failed: {destination}')
        if label=='transient':
            raw=spice.case_output(camp,destination.name,'transient.raw',3e-9)
            if raw is None:raise ValueError('incomplete transient')
            run=raw.parent
        else:
            run=base.complete(camp,label,text,outputs)
            if run is None:raise ValueError('incomplete scalar grid')
    if base.read(run/'execution.json').get('model_overlay_sha256')!=base.sha(camp/'models/overlay.json'):
        raise ValueError('executed model overlay identity mismatch')
    return run


def resume(camp):
    with (camp/'.runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);plan=check(camp)
        if any(p==camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):raise RuntimeError('campaign active')
        directory=spice.next_run_dir(camp/'analysis','measurement');directory.mkdir(parents=True,exist_ok=False)
        result=dict(status='failed',plan_sha256=base.sha(camp/'plan.json'),rows=[],evidence={})
        try:
            original=base.read(ROOT/plan['parent_summary']);old={(r['id'],r['corner'],r['temp_c'],r['drop_v']):r for r in original['rows']}
            parts=base.read(camp/'networks.json')['parts'];gates=plan['numerical_gates']
            for rc in base.CORNERS:
                outputs=[f't{t}_d{round(d*1000)}_{kind}.raw' for t in base.TEMPS for d in base.DROPS for kind in ('op','ac','low','high')]
                run=run_case(camp,rc,outputs);result['evidence'].update(base.manifest_run(run,outputs))
                for t in base.TEMPS:
                    for d in base.DROPS:
                        prefix=f't{t}_d{round(d*1000)}'
                        op=scalar_raw.read(run/(prefix+'_op.raw'));ac=scalar_raw.read(run/(prefix+'_ac.raw'),frequency_hz=2e9)
                        lo,hi=[scalar_raw.read(run/(prefix+'_'+s+'.raw')) for s in ('low','high')]
                        for p in parts:
                            n=p['id'];before=old[n,rc,t,d];fd=2*DELTA/(hi['fd_'+n]-lo['fd_'+n])
                            row=dict(id=n,corner=rc,temp_c=t,drop_v=d,resistance_ohm=op['r_'+n],node_capacitance_f=ac['c_'+n],
                                     finite_difference_resistance_ohm=fd,AC_resistance_ohm=ac['rd_'+n],
                                     DC_relative_change=op['r_'+n]/before['resistance_ohm']-1,
                                     C_relative_change=ac['c_'+n]/before['node_capacitance_f']-1,
                                     AC_to_DC_differential_relative=ac['rd_'+n]/fd-1,
                                     original_AC_to_DC_differential_relative=before['incremental_resistance_ohm']/fd-1)
                            row['numerical_agreement']=bool(all(abs(row[key])<=value for key,value in gates.items()))
                            result['rows'].append(row)
                if not all(r['numerical_agreement'] for r in result['rows']):raise ValueError(f'overlay numerical gates failed: {rc}')
            outputs=['low.raw','high.raw','center.raw','ac.raw','transient.raw']
            run=run_case(camp,'transient',outputs);result['evidence'].update(base.manifest_run(run,outputs))
            w=spice.Waves(run/'transient.raw');ac=scalar_raw.read(run/'ac.raw',frequency_hz=2e9)
            lo,hi=spice.Waves(run/'low.raw'),spice.Waves(run/'high.raw');transient=[]
            for n in diag.IDS:
                row=dict(id=n,transient=diag.admittance(w,n),AC_resistance_ohm=ac['rd_'+n],AC_capacitance_f=ac['cap_'+n],
                         DC_differential_resistance_ohm=float(-2*diag.DELTA/(hi[f'i(vport_{n})'][0]-lo[f'i(vport_{n})'][0])))
                if abs(row['transient']['resistance_ohm']/row['AC_resistance_ohm']-1)>1e-4:raise ValueError('transient and AC disagree after overlay')
                transient.append(row)
            result.update(status='overlay_DC_AC_transient_verified_not_circuit_adopted',transient=transient,
                          scope='Same 24 passive networks, 5 RC x 3 T x 3 voltage drops; TT tiny transient on ten networks. Original PDK and production DUT unchanged.')
        except Exception as exc:
            result['error']=f'{type(exc).__name__}: {exc}';raise
        finally:base.dump(directory/'summary.json',result)
    return directory/'summary.json'


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',type=Path);g.add_argument('--resume',type=Path);g.add_argument('--check',type=Path)
    p.add_argument('--summary',type=Path);a=p.parse_args()
    if a.prepare:
        if a.summary is None:raise ValueError('explicit parent summary required')
        print(prepare(a.prepare.resolve(),a.summary.resolve()))
    elif a.resume:print(resume(a.resume.resolve()))
    else:check(a.check.resolve());print('identity verified')


if __name__=='__main__':main()
