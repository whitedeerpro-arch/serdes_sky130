"""Passive varactor-port noise audit: compare .noise with4kT*Re(Y).

The1ohm CCVS observes short-circuit port-current noise without adding a sense
resistor's noise or voltage drop. An independent physical RC branch validates
the extraction. Pure DC bias; TT27C; not oscillator phase-noise qualification.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import noise_models,pnoise,project,spice,watch

ROOT=project.ROOT


def main():
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--run',action='store_true');g.add_argument('--analyse',type=Path)
    ap.add_argument('--enable-rg-noise',action='store_true');a=ap.parse_args()
    if a.analyse:return analyse(a.analyse.resolve())
    if not a.run:ap.error('use --run after checking the simulation allocation')
    if len(watch.ngspice_cwds())>=4:raise ValueError('Global ngspice slots occupied')
    c=ROOT/'results/analog/pll/vco/varactor_noise'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    c.mkdir(parents=True)
    source=c/'source';source.mkdir();shutil.copyfile(__file__,source/'runner.py')
    model=project.model_library().parents[2]/'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_var_lvt.model.spice'
    shutil.copyfile(model,source/model.name)
    text=f'''Passive port noise audit; TT27C, varactor W5.2 L0.5 vm4
.lib "{project.model_library()}" tt
Vgate g 0 1.55
Vdrive bias 0 1.166 ac1
Vsense bias well 0
Xvar g well 0 sky130_fd_pr__cap_var_lvt w=5.2 l=.5 vm=4
Hobserve out 0 Vsense 1
Vref refbias 0 1.166 ac1
Vrsense refbias rw 0
Rr rw rc 100
Cr rc 0 80f
Hreference rout 0 Vrsense 1
.temp 27
.control
set num_threads=1
set filetype=binary
set wr_vecnames
set wr_singlescale
op
write op.raw v(g) v(well) v(rw)
destroy all
ac dec20 1k 1g
let gy=real(i(Vsense)/v(well))
let by=imag(i(Vsense)/v(well))
let gr=real(i(Vrsense)/v(rw))
let br=imag(i(Vrsense)/v(rw))
wrdata admittance.tsv gy by gr br
destroy all
noise v(out) Vdrive dec20 1k 1g
setplot noise1
write var_noise.raw frequency onoise_spectrum
destroy all
noise v(rout) Vref dec20 1k 1g
setplot noise1
write ref_noise.raw frequency onoise_spectrum
destroy all
quit
.endc
.end
'''
    # Keep ordinary SPICE token separation, independent of parser tolerance.
    text=text.replace('ac1','ac 1').replace('dec20','dec 20')
    if a.enable_rg_noise:
        overlay=c/'models/varactor_noisy.spice';meta=noise_models.varactor_rg(model,overlay)
        (c/'noise_overlay.json').write_text(json.dumps(meta,indent=2)+'\n')
        shutil.copyfile(noise_models.__file__,source/'noise_models.py')
        text=text.replace('Xvar g well 0 sky130_fd_pr__cap_var_lvt ',f'.include "{overlay}"\nXvar g well 0 {noise_models.NOISY_VARACTOR} ')
    (c/'prepared.cir').write_text(text)
    ex=spice.run(text,c/'run',timeout_s=180)
    if not ex.ok:raise ValueError('Noise card failed: '+str(ex.log_failures))
    return analyse(c)


def analyse(c):
    source=c/'source'
    ex=json.loads((c/'run/execution.json').read_text())
    if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:raise ValueError('Noise card execution failed')
    op=spice.Waves(c/'run/op.raw')
    if abs(op['v(well)'][0]-1.166)>1e-6:raise ValueError('Unexpected noise DC bias')
    ac=np.loadtxt(c/'run/admittance.tsv',skiprows=1)
    vf=spice.Waves(c/'run/var_noise.raw');rf=spice.Waves(c/'run/ref_noise.raw')
    if ac.shape!=(121,5) or not np.allclose(ac[:,0],vf.t) or not np.allclose(ac[:,0],rf.t):raise ValueError('Incomplete spectra')
    si=vf['onoise_spectrum']**2;sr=rf['onoise_spectrum']**2
    kt=4*pnoise.K_B*(27+273.15)
    reference_ratio=sr/(kt*ac[:,3])
    # Below1MHz the real part is tiny versus the quadrature current and
    # floating-point cancellation limits Re(Y); validate the resolved band.
    resolved=ac[:,0]>=1e6
    if not np.allclose(reference_ratio[resolved],1,rtol=1e-4,atol=1e-6):raise ValueError('RC reference noise extraction failed')
    rows=[]
    for f in (1e6,20e6,50e6,1e9):
        g=float(np.interp(np.log(f),np.log(ac[:,0]),ac[:,1]))
        observed=float(np.interp(np.log(f),np.log(vf.t),si));expected=kt*g
        rows.append(dict(hz=f,conductance_s=g,observed_a2_hz=observed,
                         passive_equilibrium_expected_a2_hz=expected,
                         observed_to_expected=observed/expected if expected>0 else None))
    result=dict(campaign=str(c.relative_to(ROOT)),pdk_id=project.pdk_installation_id(),
        rows=rows,reference_validated_band_hz=[1e6,1e9],
        reference_ratio_min=float(reference_ratio[resolved].min()),reference_ratio_max=float(reference_ratio[resolved].max()),
        full_band_reference_ratio_min=float(reference_ratio.min()),full_band_reference_ratio_max=float(reference_ratio.max()),
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()},
        scope='TT27C, Vgate1.55V, Vwell1.166V, W5.2 L0.5 vm4; pure-DC passive noise extraction audit only, not cyclostationary/ISF or total PLL phase noise')
    if (c/'noise_overlay.json').exists():result['noise_overlay']=json.loads((c/'noise_overlay.json').read_text())
    out=c/'analysis'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    shutil.copyfile(__file__,out/'analysis.py');result['analysis_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2),flush=True);print(out.relative_to(ROOT),flush=True)


if __name__=='__main__':main()
