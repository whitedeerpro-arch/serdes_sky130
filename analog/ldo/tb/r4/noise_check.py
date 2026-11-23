"""Does installed ngspice honor PDK isnoisy=0? Compare with Johnson noise."""
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from serdes_flow import project, spice

ROOT=project.ROOT


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    c=ROOT/'results/analog/ldo/resistor_noise_check'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');c.mkdir(parents=True)
    shutil.copyfile(__file__,c/'runner.py')
    cell=ROOT/'analog/ldo/spice/ldo_passives.spice';shutil.copyfile(cell,c/'passives.spice')
    lines=['* Installed PDK thermal-noise interpretation check',f'.lib "{project.model_library()}" tt',f'.include "{c}/passives.spice"','Vdrive d 0 dc 0 ac 1',
           'Rideal ni d 1k','Xhigh nh d 0 sky130_fd_pr__res_high_po w=1 l=2',
           'Xxhigh nx d 0 sky130_fd_pr__res_xhigh_po w=1 l=471.984','Xactual na d 0 serdes_ldo_ref_res','.temp 27','.options reltol=1e-7 abstol=1f',
           '.control','set num_threads=1','set filetype=binary']
    for key,node in [('ideal','ni'),('high','nh'),('xhigh','nx'),('actual','na')]:
        lines += [f'noise v({node}) Vdrive dec 10 1k 1meg','setplot noise1',f'write {key}.raw frequency onoise_spectrum','destroy all']
    lines += ['quit','.endc','.end',''];deck='\n'.join(lines)
    pdk=project.model_library().parents[2];modelpaths=[pdk/'libs.ref/sky130_fd_pr/spice'/('sky130_fd_pr__res_'+name+'_po.model.spice') for name in ('high','xhigh')]
    ex=spice.run(deck,c/'run',timeout_s=180)
    if not ex.ok:raise ValueError(ex.log_failures)
    rows={}
    for key in ('ideal','high','xhigh','actual'):
        path=c/'run'/(key+'.raw');w=spice.Waves(path)
        if len(w.t)!=31 or not np.isclose(w.t[-1],1e6):raise ValueError('Incomplete noise grid')
        density=float(w['onoise_spectrum'][0]);rows[key]=dict(density_v_rthz=density,equivalent_thermal_resistance_ohm=density*density/(4*1.380649e-23*300.15),raw_sha256=sha(path))
    data=dict(campaign=str(c.relative_to(ROOT)),rows=rows,models={str(p):sha(p) for p in modelpaths},cell_sha256=sha(c/'passives.spice'),execution_sha256=sha(c/'run/execution.json'),
              scope='ngspice47 thermal-noise interpretation, not complete LDO noise/PDK matching validation')
    (c/'summary.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))


if __name__=='__main__':main()
