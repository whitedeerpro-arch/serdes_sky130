"""Electrical check of Rz series-segment contact resistance (not LVS merging)."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from serdes_flow import project,spice,watch

ROOT=project.ROOT


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output-dir',type=Path);a=ap.parse_args()
    if len(watch.ngspice_cwds())>=4:raise ValueError('Global ngspice slots occupied')
    out=(a.output_dir or ROOT/'results/analog/bias/rz_segments'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')).resolve()
    out.mkdir(parents=True,exist_ok=False)
    snap=out/'source';snap.mkdir();shutil.copyfile(__file__,snap/'runner.py')
    for suffix in ('lvs','ref'):
        src=ROOT/f'analog/bias/layout/variants/pdk/serdes_bg_amp_pdk_{suffix}.spice'
        shutil.copyfile(src,snap/src.name)
    groups={'merged_length':(1,61.90),'extracted_four':(4,15.48),
            'nom20_four':(4,(5000-378)/317),'nom30_four':(4,(7500-378)/317)}
    lines=['* Rz unmerged electrical calibration; each pair biased at0.9V',f'.lib "{project.model_library()}" tt']
    for tag,(n,length) in groups.items():
        lines += [f'Vl_{tag} lo_{tag} 0 .9',f'Vt_{tag} hi_{tag} lo_{tag} 0 ac 1']
        nodes=[f'hi_{tag}',*[f'n{k}_{tag}' for k in range(1,n)],f'lo_{tag}']
        lines += [f'X{k}_{tag} {nodes[k]} {nodes[k+1]} 0 sky130_fd_pr__res_high_po w=1 l={length:.12g}' for k in range(n)]
    lines += ['.control','set num_threads=1','set wr_vecnames','set wr_singlescale']
    for t in (-40,27,85):
        lines += [f'option temp={t}','ac lin 1 10 10']
        lines += [f'let r{k}=1/real(-i(Vt_{tag}))' for k,tag in enumerate(groups)]
        lines += [f'wrdata t{t}.tsv '+' '.join(f'r{k}' for k in range(len(groups))),'destroy all']
    lines += ['quit','.endc','.end','']
    ex=spice.run('\n'.join(lines),out/'run',timeout_s=180)
    if not ex.ok:raise ValueError('Rz electrical card execution failed')
    rows=[]
    for t in (-40,27,85):
        a=np.atleast_2d(np.loadtxt(out/'run'/f't{t}.tsv',skiprows=1))
        if a.shape!=(1,5) or not np.allclose(a[:,0],[10]) or not np.all(np.isfinite(a)):raise ValueError('Incomplete Rz card')
        values={tag:float(a[0,k+1]) for k,tag in enumerate(groups)}
        rows.append(dict(temp_c=t,resistance_ohm=values,extracted_vs_merged_pct=(values['extracted_four']/values['merged_length']-1)*100))
    result=dict(campaign=str(out.relative_to(ROOT)),pdk=project.pdk_installation_id(),groups=groups,rows=rows,
                source_sha256={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in snap.iterdir()},
                scope='TT model x three temperatures; DC0.9V common mode and10Hz small-signal conductance; not full-RC/PVT or an automatic layout change')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))


if __name__=='__main__':main()
