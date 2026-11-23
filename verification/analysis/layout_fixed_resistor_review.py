"""Independent fixed-width SKY130 resistor layout, DRC and reference LVS review."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

from serdes_flow import project

ROOT=project.ROOT
HERE=Path(__file__).resolve()
MAGICDIR=ROOT/'verification/layout'
PDK=Path('/home/host/.volare/sky130A')
SOURCES=[HERE,MAGICDIR/'check.py',MAGICDIR/'magicutil.py',PDK/'libs.tech/magic/sky130A.tcl',
         PDK/'libs.tech/magic/sky130A.magicrc',PDK/'libs.tech/magic/sky130A.tech',PDK/'libs.tech/netgen/sky130A_setup.tcl']


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def main():
    out=ROOT/'results/layout_review/fixed_resistors'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
    tools=out/'tools';tools.mkdir();sources={}
    for p in SOURCES:
        sources[str(p)]=sha(p);name=p.name
        if (tools/name).exists(): raise ValueError('source snapshot name collision')
        shutil.copyfile(p,tools/name)
    spec=importlib.util.spec_from_file_location('layout_review_magicutil',tools/'magicutil.py');mu=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mu;spec.loader.exec_module(mu)
    report=dict(status='incomplete',sources=sources,cells=[],scope='Isolated generated 2p85 and 5p73 devices, nominal l=10um, 3-port guard; no network, PEX electrical qualification, EM or current capacity signoff.')
    try:
        for suffix in ('2p85','5p73'):
            cell='fixed_'+suffix+'_l10';dev='sky130_fd_pr__res_high_po_'+suffix
            work=out/cell;work.mkdir();mu.new_cell(work/(cell+'.mag'))
            script=work/'generate.tcl'
            script.write_text('\n'.join(['drc off',f'cd {work}',f'load {cell}',
                f'set p [dict merge [sky130::{dev}_defaults] {{l 10 guard 1 doports 1}}]',
                'puts "GEN_PARAMETERS $p"',f'sky130::{dev}_draw $p','select top cell',
                'puts "GEN_BBOX [box values]"','save','quit -noprompt'])+'\n')
            run=mu.run_magic(script,work);(work/'generation.log').write_text(run.log);run.need('fixed resistor generation')
            ref=work/(cell+'_ref.spice');ref.write_text(f'.subckt {cell} B R1 R2\nX0 R1 R2 B {dev} l=10\n.ends {cell}\n')
            proc=subprocess.run([sys.executable,str(tools/'check.py'),str(work),cell,'--ref',str(ref)],capture_output=True,text=True,timeout=600)
            (work/'review.log').write_text(proc.stdout+proc.stderr)
            extracted=(work/(cell+'_lvs.spice')).read_text()
            lines=[x.strip() for x in extracted.splitlines() if x.strip() and not x.startswith('*')]
            sub=[x.split() for x in lines if x.lower().startswith('.subckt ')]
            devices=[x.split() for x in lines if x.lower().startswith('x')]
            ports_ok=(len(sub)==1 and sub[0][1].lower()==cell.lower() and [x.lower() for x in sub[0][2:]]==['b','r1','r2'])
            device_ok=(len(devices)==1 and len(devices[0])==6 and [x.lower() for x in devices[0][1:4]]==['r1','r2','b'] and devices[0][4].lower()==dev.lower())
            length=None
            if device_ok:
                match=re.fullmatch(r'l=([0-9.eE+\-]+)',devices[0][5],re.I)
                if match:length=float(match[1])
            body=(work/(cell+'.mag')).read_text()
            guard=bool(re.search(r'^rlabel\s+psubdiffcont\s+.*\s+B$',body,re.M|re.I))
            drc_match=re.search(r'^DRC_TOTAL\s+(\d+)',proc.stdout,re.M)
            clean=(proc.returncode==0 and drc_match and int(drc_match[1])==0 and 'LVS_MATCH True  LVS_PROPERTY_ERRORS False' in proc.stdout and 'LVS_DISCONNECTED none' in proc.stdout and ports_ok and device_ok and length is not None and abs(length-10)<1e-9 and guard)
            record=dict(cell=cell,device=dev,parameters={'l_um':10,'guard':1,'doports':1},generation_ok=run.ok,check_returncode=proc.returncode,
                drc_total=int(drc_match[1]) if drc_match else None,subckt_ports= sub[0][2:] if len(sub)==1 else None,
                extracted_devices=devices,ports_used_by_device=bool(device_ok and ports_ok),extracted_l_um=length,guard_contact_label_on_psub=guard,pass_review=bool(clean),
                evidence={str(p.relative_to(out)):sha(p) for p in work.iterdir() if p.is_file()})
            report['cells'].append(record)
        report['status']='isolated_primitive_review_pass' if all(x['pass_review'] for x in report['cells']) else 'isolated_primitive_review_failed'
    finally:
        (out/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print('RESULT',out,report['status'])
    if report['status']!='isolated_primitive_review_pass':sys.exit(1)


if __name__=='__main__':main()
