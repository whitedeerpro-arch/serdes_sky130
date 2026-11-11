"""Cross-check fixed-card AC linearization against DC slope and tiny transient.

Uses explicit networks from a checked fixed_load_card campaign; one TT27C
deck, no change to the original passive campaign or any production DUT.
"""
import argparse
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

import numpy as np

from serdes_flow import project,scalar_raw,spice,watch

HERE=Path(__file__).resolve()
spec=importlib.util.spec_from_file_location('fixed_ac_parent',HERE.with_name('fixed_load_card.py'))
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)
ROOT=project.ROOT
IDS=('generic50','r50_n5','r50_n6','r50_n8','generic120','r120_n2','r120_n3','r120_n4','generic400','r400_n1')
FREQ=2e9
DELTA=.001


def deck(parts):
    lines=['fixed resistor AC versus DC and transient audit',f'.lib "{project.model_library()}" tt','Vrail rail 0 1.8',
           '.options reltol=1e-7 abstol=1f vntol=1n']
    for p in parts:
        lines += [f'Vport_{p["id"]} out_{p["id"]} 0 DC 1.55 AC 1 SIN(1.55 1m 2g)',p['instance']]
    vectors=' '.join(f'v(out_{p["id"]}) i(vport_{p["id"]})' for p in parts)
    lines += ['.save '+vectors,'.control','set num_threads=1','set filetype=binary','option temp=27']
    for label,voltage in (('low',1.55-DELTA),('high',1.55+DELTA),('center',1.55)):
        lines += [f'alter Vport_{p["id"]} dc={voltage:.12g}' for p in parts]+['op',f'write {label}.raw '+vectors,'destroy all']
    lines += ['ac lin 1 2g 2g']
    for p in parts:
        n=p['id'];lines += [f'let rd_{n}=-1/real(i(vport_{n}))',f'let cap_{n}=-imag(i(vport_{n}))/(2*pi*2e9)']
    lines += ['write ac.raw '+' '.join(v+p['id'] for p in parts for v in ('rd_','cap_')),'destroy all',
              spice.skip_output_before('tran .5p 3n 0 .5p','1n'),'write transient.raw '+vectors,'quit','.endc','.end','']
    return '\n'.join(lines)


def admittance(w,name):
    use=(w.t>=2e-9)&(w.t<=3e-9);t=w.t[use]
    x=np.column_stack((np.ones_like(t),np.cos(2*np.pi*FREQ*t),np.sin(2*np.pi*FREQ*t)))
    v=np.linalg.lstsq(x,w[f'out_{name}'][use],rcond=None)[0]
    i=np.linalg.lstsq(x,w[f'i(vport_{name})'][use],rcond=None)[0]
    y=-(i[1]-1j*i[2])/(v[1]-1j*v[2])
    return dict(resistance_ohm=float(1/y.real),capacitance_f=float(y.imag/(2*np.pi*FREQ)),
                input_amplitude_v=float(abs(v[1]-1j*v[2])),
                current_fit_rms_a=float(np.sqrt(np.mean((x@i-w[f'i(vport_{name})'][use])**2))))


def analyze(camp):
    """Read-only recovery of a completed physics run; preserve the original plan."""
    plan=base.read(camp/'plan.json');parts=plan['parts'];run=camp/'run'
    for path,expected in plan['sources'].items():
        if base.sha(camp/'execution'/path.lstrip('/'))!=expected:raise ValueError('archived source changed')
    if plan['pdk_identity']!=base.pdk_identity():raise ValueError('PDK changed')
    ex=base.read(run/'execution.json')
    if (ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or
            ex['deck_sha256']!=base.sha(camp/'prepared.cir') or base.sha(run/'tb.cir')!=base.sha(camp/'prepared.cir')):
        raise ValueError('invalid executed diagnostic')
    if spice.case_output(camp,'run','transient.raw',3e-9) is None:raise ValueError('truncated diagnostic')
    # A scalar OP plot may repeat its scale voltage among the requested vectors.
    # Waves resolves the explicit voltage/current column without discarding data.
    low,high,center=[spice.Waves(run/(s+'.raw')) for s in ('low','high','center')]
    if any(len(w.t)!=1 for w in (low,high,center)):raise ValueError('not scalar OP')
    ac=scalar_raw.read(run/'ac.raw',frequency_hz=FREQ);w=spice.Waves(run/'transient.raw')
    rows=[]
    for p in parts:
        n=p['id'];name=f'i(vport_{n})';rd=-2*DELTA/(high[name][0]-low[name][0])
        measured=admittance(w,n)
        rows.append(dict(id=n,DC_resistance_ohm=float(.25/center[name][0]),DC_differential_resistance_ohm=float(rd),
                         AC_resistance_ohm=ac['rd_'+n],AC_capacitance_f=ac['cap_'+n],transient=measured,
                         AC_vs_DC_differential_relative=float(ac['rd_'+n]/rd-1),
                         transient_vs_DC_differential_relative=float(measured['resistance_ohm']/rd-1)))
    outputs=['low.raw','high.raw','center.raw','ac.raw','transient.raw']
    result=dict(status='cross_check_measured',plan_sha256=base.sha(camp/'plan.json'),
                evidence=base.manifest_run(run,outputs),rows=rows,
                analysis_source_sha256=base.sha(HERE),
                scope='TT27C/250mV, +/-1mV DC and 1mV 2GHz transient; not full PVT/noise or layout qualification')
    archive=camp/'analysis'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    archive.mkdir(parents=True,exist_ok=False);shutil.copyfile(HERE,archive/'analyze.py');base.dump(archive/'summary.json',result)
    for r in rows:print(r['id'],r['DC_differential_resistance_ohm'],r['AC_resistance_ohm'],r['transient']['resistance_ohm'],r['transient']['capacitance_f'])
    return archive/'summary.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__);g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--parent',type=Path);g.add_argument('--analyze',type=Path);a=parser.parse_args()
    if a.analyze:
        print(analyze(a.analyze.resolve()));return
    parent=a.parent.resolve();base.check(parent);model=base.read(parent/'networks.json')
    parts=[p for p in model['parts'] if p['id'] in IDS]
    if {p['id'] for p in parts}!=set(IDS):raise ValueError('missing diagnostic parts')
    camp=ROOT/'results/analog/common/devices/fixed_load_ac_check'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);camp.mkdir(parents=True,exist_ok=False)
    text=deck(parts);(camp/'prepared.cir').write_text(text)
    files=list(dict.fromkeys(base.RUNTIME+[HERE]))
    sources={str(p):base.sha(p) for p in files}
    for p in files:
        dst=camp/'execution'/str(p).lstrip('/');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
    plan=dict(parent=str(parent.relative_to(ROOT)),parent_plan_sha256=base.sha(parent/'plan.json'),
              networks_sha256=base.sha(parent/'networks.json'),sources=sources,pdk_identity=base.pdk_identity(),
              delta_v=DELTA,sinusoid_amplitude_v=.001,frequency_hz=FREQ,parts=parts)
    base.dump(camp/'plan.json',plan)
    if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
    run=camp/'run';ex=spice.run(text,run,timeout_s=180,meta=dict(kind='AC_DC_transient_cross_check',condition='tt_v1800_t27'))
    if not ex.ok or spice.case_output(camp,'run','transient.raw',3e-9) is None:raise RuntimeError('diagnostic did not complete')
    print(analyze(camp))


if __name__=='__main__':main()
