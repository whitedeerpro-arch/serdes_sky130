"""Noiseless r6 transient equivalence after enabling varactor rg noise locally."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from serdes_flow import noise_models,project,spice,watch

ROOT=project.ROOT


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args()
    if len(watch.ngspice_cwds())>=4:raise ValueError('Global ngspice slots occupied')
    parent=a.parent.resolve();p=json.loads((parent/'plan.json').read_text())
    for n,h in p['snapshots'].items():
        if sha(parent/n)!=h:raise ValueError('Parent input changed: '+n)
    case=parent/'f50_a0';ex=json.loads((case/'execution.json').read_text())
    if ex['exit_code'] or ex['timed_out'] or ex['log_failures']:raise ValueError('Parent execution not complete')
    reference=spice.Waves(case/'ctrl.raw')
    if reference.t[-1]<80e-9*(1-1e-9):raise ValueError('Parent waveform truncated')
    c=ROOT/'results/analog/pll/vco/varactor_equivalence'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');c.mkdir(parents=True)
    shutil.copytree(parent/'snap',c/'snap')
    model=project.model_library().parents[2]/'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__cap_var_lvt.model.spice'
    overlay=c/'models/varactor_noisy.spice';meta=noise_models.varactor_rg(model,overlay)
    ring=c/'snap/pdk_fixed_resistors/analog/pll/vco/spice/vco_ring4_r6.spice'
    text=ring.read_text();modified,n=re.subn(r'(?im)^(Xv\S+\s+\S+\s+\S+\s+\S+\s+)sky130_fd_pr__cap_var_lvt(\s)',r'\g<1>'+noise_models.NOISY_VARACTOR+r'\2',text)
    if n!=8:raise ValueError('Expected8 varactor instances')
    ring.write_text(modified)
    deck=(parent/'prepared/f50_a0.cir').read_text().replace(str(parent/'snap'),str(c/'snap'))
    deck=deck.replace('Vdd vdd 0 1.8',f'.include "{overlay}"\nVdd vdd 0 1.8')
    deck=re.sub(r'^tran .*$', 'tran 2p 20n 10n 2p',deck,flags=re.M)
    (c/'prepared.cir').write_text(deck)
    smoke=re.sub(r'^tran .*$', 'tran 2p 1n 0 2p',deck,flags=re.M)
    files={'runner.py':Path(__file__),'noise_models.py':Path(noise_models.__file__)}
    source=c/'source';source.mkdir()
    for n,s in files.items():shutil.copyfile(s,source/n)
    (c/'input.json').write_text(json.dumps(dict(parent=str(parent.relative_to(ROOT)),parent_plan_sha256=sha(parent/'plan.json'),
        parent_raw_sha256=sha(case/'ctrl.raw'),overlay=meta,source_sha256={p.name:sha(p) for p in source.iterdir()},
        snapshot_sha256={str(p.relative_to(c)):sha(p) for p in c.rglob('*') if p.is_file()}),indent=2)+'\n')
    for name,text,end in [('smoke',smoke,1e-9),('run',deck,20e-9)]:
        out=spice.run(text,c/name,timeout_s=600)
        print(name,out.ok,round(out.elapsed_s,1),flush=True)
        w=spice.Waves(c/name/'ctrl.raw')
        if not out.ok or w.t[-1]<end*(1-1e-9) or not np.all(np.isfinite(w.data)):raise ValueError('Equivalence run incomplete')
    new=spice.Waves(c/'run/ctrl.raw');use=(reference.t>=10e-9)&(reference.t<=19e-9)
    errors={n:float(np.max(np.abs(reference[n][use]-np.interp(reference.t[use],new.t,new[n])))) for n in ('v(v0p)','v(v0n)','v(ctrl)','v(ctrl_dc)','i(vsin)','v(vbias_q)')}
    passed=all(v<1e-4 for n,v in errors.items() if n.startswith('v(')) and errors['i(vsin)']<1e-6
    result=dict(campaign=str(c.relative_to(ROOT)),parent=str(parent.relative_to(ROOT)),max_abs_errors=errors,
                passed=passed,overlay=meta,scope='TT/code9/map voltage, same ring/4buffers30fF/real bias/slow tail;1ns smoke+20ns noiseless transient; only rg noisy flag plus alias; no full PVT, MC or oscillator noise budget')
    (c/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps(result,indent=2),flush=True)
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
