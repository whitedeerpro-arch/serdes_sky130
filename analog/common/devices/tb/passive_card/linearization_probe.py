"""Minimal expression audit for the fixed-poly resistor AC discrepancy.

Compare DC finite differences, AC derivatives and 1mV transient functions.
No PDK or production DUT is changed. Uses the project's ngspice/HSA setup.
"""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import uuid

import numpy as np

from serdes_flow import project,scalar_raw,spice,watch

ROOT=project.ROOT
HERE=Path(__file__).resolve()
U='min((abs(v(x))-1.6),0.4)'
EXPRESSIONS={
    'linear':U,
    'pow2':f'pow({U},2)',
    'mul2':f'({U})*({U})',
    'pow3':f'pow({U},3)',
    'mul3':f'({U})*({U})*({U})',
    'power2':f'({U})**2',
    'power3':f'({U})**3',
    'contact_pow':f'1+({U})*.0147+pow({U},2)*.136+pow({U},3)*.0529',
    'contact_mul':f'1+({U})*.0147+({U})*({U})*.136+({U})*({U})*({U})*.0529',
    'contact_horner':f'1+({U})*(.0147+({U})*(.136+({U})*.0529))',
}
CENTERS=(.25,1.2,1.8,2.2,-.25)
DELTA=1e-5
FREQ=2e9


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def deck():
    lines=['behavioral expression derivative audit','Vx x 0 DC .25 AC 1 SIN(.25 1m 2g)']
    for name,expr in EXPRESSIONS.items():lines.append(f'B_{name} o_{name} 0 v={{{expr}}}')
    vectors=' '.join(['v(x)']+[f'v(o_{n})' for n in EXPRESSIONS])
    lines+=['.options reltol=1e-8 abstol=1f vntol=1p','.save '+vectors,'.control','set num_threads=1','set filetype=binary']
    for i,center in enumerate(CENTERS):
        for label,offset in (('low',-DELTA),('high',DELTA),('center',0)):
            lines += [f'alter Vx dc={center+offset:.12g}','op',f'write p{i}_{label}.raw '+vectors,'destroy all']
        lines += ['ac lin 1 2g 2g']+[f'let g_{n}=real(v(o_{n}))' for n in EXPRESSIONS]
        lines += [f'write p{i}_ac.raw '+' '.join('g_'+n for n in EXPRESSIONS),'destroy all']
    lines += ['alter Vx dc=.25','tran .5p 3n 1n .5p','write transient.raw '+vectors,'quit','.endc','.end','']
    return '\n'.join(lines)


def transient_gain(w,name):
    use=(w.t>=2e-9)&(w.t<=3e-9);t=w.t[use]
    design=np.column_stack((np.ones_like(t),np.cos(2*np.pi*FREQ*t),np.sin(2*np.pi*FREQ*t)))
    x=np.linalg.lstsq(design,w['x'][use],rcond=None)[0]
    y=np.linalg.lstsq(design,w['o_'+name][use],rcond=None)[0]
    gain=(y[1]-1j*y[2])/(x[1]-1j*x[2])
    return dict(real=float(gain.real),imag=float(gain.imag),input_amplitude_v=float(abs(x[1]-1j*x[2])))


def main():
    camp=ROOT/'results/analog/common/devices/linearization_probe'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False);(camp/'execution').mkdir()
    files=[HERE,Path(project.__file__),Path(spice.__file__),Path(scalar_raw.__file__),Path(project.ngspice())]
    sources={str(p):sha(p) for p in files}
    for p in files:
        dest=camp/'execution'/str(p).lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    plan=dict(expressions=EXPRESSIONS,centers_v=list(CENTERS),DC_half_step_v=DELTA,transient_center_v=.25,
              transient_amplitude_v=.001,frequency_hz=FREQ,sources=sources,
              reference_links=['https://ngspice.sourceforge.io/docs/ngspice-manual.pdf','https://sourceforge.net/p/ngspice/bugs/336/'])
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    if len(watch.ngspice_cwds())>=4:raise RuntimeError('global ngspice limit')
    text=deck();run=camp/'run';ex=spice.run(text,run,timeout_s=120,meta=dict(kind='expression_derivative_probe',condition='no_PDK'))
    if not ex.ok or spice.case_output(camp,'run','transient.raw',3e-9) is None:raise RuntimeError('expression probe incomplete')
    w=spice.Waves(run/'transient.raw');rows=[]
    for i,center in enumerate(CENTERS):
        low,high,nom=[spice.Waves(run/f'p{i}_{label}.raw') for label in ('low','high','center')]
        ac=scalar_raw.read(run/f'p{i}_ac.raw',frequency_hz=FREQ)
        for name,expr in EXPRESSIONS.items():
            numerical=float((high['o_'+name][0]-low['o_'+name][0])/(2*DELTA))
            row=dict(center_v=center,name=name,expression=expr,DC_value=float(nom['o_'+name][0]),
                     DC_derivative=numerical,AC_derivative=ac['g_'+name],AC_minus_DC=ac['g_'+name]-numerical)
            if i==0:row['transient_gain']=transient_gain(w,name)
            rows.append(row)
    result=dict(status='expression_derivative_measured',plan_sha256=sha(camp/'plan.json'),rows=rows,
                evidence={str(p.relative_to(ROOT)):sha(p) for p in run.iterdir() if p.is_file()},
                scope='ngspice47 with project HSA initialization, no PDK; expression DC/AC derivatives and TT-independent tiny transient')
    (camp/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(camp)
    for row in rows:
        if row['center_v']==.25:print(row['name'],row['DC_value'],row['DC_derivative'],row['AC_derivative'],row.get('transient_gain'))


if __name__=='__main__':main()
