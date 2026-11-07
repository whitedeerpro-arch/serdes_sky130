"""Archive behavioral/lint/structural checks for the PHY word guard.

uv run python verification/digital/tx_ingress_control.py
This does not map cells, perform STA or connect analog data/valid paths.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from serdes_flow.project import ROOT, git_revision


def main():
    camp=ROOT/'results/digital/tx/ingress_control'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    camp.mkdir(parents=True,exist_ok=False)
    rtl=ROOT/'digital/tx/rtl/tx_ingress_control.sv'
    tb=ROOT/'digital/tx/tb/tb_tx_ingress_control.sv'
    sources=[rtl,tb,Path(__file__).resolve()]
    result=dict(git_revision=git_revision(),sources={},commands=[],checks=[],scope='RTL behavior, lint and generic structural checks only; no library mapping, STA, CDC or analog integration')
    for src in sources:
        result['sources'][str(src.relative_to(ROOT))]=hashlib.sha256(src.read_bytes()).hexdigest()
        dest=camp/'execution'/src.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)

    def run(name,argv):
        done=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=45)
        text=done.stdout+done.stderr
        (camp/(name+'.log')).write_text(text)
        result['commands'].append(dict(name=name,argv=argv,exit_code=done.returncode,log=name+'.log'))
        if done.returncode:
            raise RuntimeError(f'{name} failed; see {camp}')
        return text

    try:
        total=0
        for n,expected in ((1,25),(2,32),(3,39),(5,53)):
            binary=camp/f'n{n}.vvp'
            run(f'compile_n{n}',['iverilog','-g2012','-s','ingress_case',f'-Pingress_case.N={n}','-o',str(binary),str(rtl),str(tb)])
            output=run(f'behavior_n{n}',['vvp',str(binary)])
            found=re.findall(r'PASS WARMUP_FALLS=(\d+) checks=(\d+)',output)
            if found!=[(str(n),str(expected))] or 'FAIL' in output:
                raise ValueError('missing/inconsistent behavioral completion')
            result['checks'].append(dict(parameter=n,passed_assertions=expected));total+=expected
        run('lint',['verilator','--lint-only','-Wall','--top-module','tx_ingress_control',str(rtl)])
        run('structural',['yosys','-p',f'read_verilog -sv {rtl}; hierarchy -check -top tx_ingress_control; proc; opt; check -assert'])
        result.update(status='pass',behavioral_assertions=total)
    finally:
        result.setdefault('status','failed')
        (camp/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
        print(camp,flush=True)
    print('behavioral checks',result['behavioral_assertions'],'lint and generic structure pass')


if __name__=='__main__':main()
