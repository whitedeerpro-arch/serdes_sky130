"""Capture the producer's current flat inverter cells and review isolated copies.

No edits in the producer directory. Re-run full DRC/extraction/LVS on captured
Magic geometry, then audit exported pins, total width and explicit parasitics.
"""
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from serdes_flow import netlist,project

ROOT=project.ROOT
HERE=Path(__file__).resolve()
PRODUCER=ROOT/'analog/common/layout_practice'
AUDITOR=ROOT/'verification/layout_training/inverter_audit.py'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    camp=ROOT/'results/layout_review/inverters'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8])
    camp.mkdir(parents=True,exist_ok=False);tools=camp/'tools';tools.mkdir()
    sources={}
    for source in [HERE,AUDITOR,ROOT/'verification/layout/check.py',ROOT/'verification/layout/magicutil.py',Path(netlist.__file__)]:
        sources[str(source)]=sha(source);shutil.copyfile(source,tools/source.name)
    spec=importlib.util.spec_from_file_location('captured_inverter_audit',tools/AUDITOR.name)
    auditor=importlib.util.module_from_spec(spec);spec.loader.exec_module(auditor)
    report=dict(status='review_incomplete',sources=sources,cells=[],scope='Captured producer inv_std2/inv_std3 only; full DRC/LVS/flat-pin audit, explicit PEX C; no EM, total Cout or electrical timing qualification')
    for cell in ('inv_std2','inv_std3'):
        work=camp/cell;work.mkdir();captured={}
        for suffix in ('.mag','_ref.spice'):
            source=PRODUCER/(cell+suffix);expected=sha(source);shutil.copyfile(source,work/source.name)
            if sha(source)!=expected or sha(work/source.name)!=expected:raise ValueError('producer changed during capture')
            captured[str(source.relative_to(ROOT))]=expected
        source=PRODUCER/f'build_{cell}.py';shutil.copyfile(source,work/'producer_build.py');captured[str(source.relative_to(ROOT))]=sha(source)
        command=[sys.executable,str(tools/'check.py'),str(work),cell,'--ref',str(work/(cell+'_ref.spice'))]
        proc=subprocess.run(command,capture_output=True,text=True,timeout=240)
        (work/'review.log').write_text(proc.stdout+proc.stderr)
        audit=auditor.audit(work/(cell+'_lvs.spice'),cell)
        if proc.returncode!=0 or audit['status']!='pass':raise ValueError(f'captured geometry failed: {cell}')
        capacitances=[]
        for line in (work/(cell+'_pex.spice')).read_text().splitlines():
            fields=line.split()
            if len(fields)==4 and fields[0].lower().startswith('c'):
                capacitances.append(dict(nodes=fields[1:3],fF=netlist.number(fields[3])*1e15))
        totals={n:sum(c['fF'] for c in capacitances if n in c['nodes']) for n in ('d','g')}
        report['cells'].append(dict(cell=cell,captured_sources=captured,DRC_LVS_exit_code=proc.returncode,
                                    audit=audit,explicit_capacitances=capacitances,explicit_incident_fF=totals,
                                    evidence={str(p.relative_to(camp)):sha(p) for p in work.iterdir() if p.is_file()}))
    report['status']='captured_geometry_review_pass'
    report['note']='Explicit C excludes bias-dependent MOS junction/overlap and resistance; producer artifacts remain untouched.'
    (camp/'summary.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    output=ROOT/'docs/data/layout_inverter_producer_review.json'
    output.write_text(json.dumps(dict(campaign=str(camp.relative_to(ROOT)),summary=str((camp/'summary.json').relative_to(ROOT)),summary_sha256=sha(camp/'summary.json'),**report),indent=2)+'\n')
    (ROOT/'results/catalog/layout_inverter_producer_review.json').write_text(json.dumps(dict(data=str(output.relative_to(ROOT)),data_sha256=sha(output),summary=str((camp/'summary.json').relative_to(ROOT)),summary_sha256=sha(camp/'summary.json'),scope=report['scope']),indent=2)+'\n')
    print(camp)
    for cell in report['cells']:print(cell['cell'],cell['audit']['status'],cell['explicit_incident_fF'])


if __name__=='__main__':main()
