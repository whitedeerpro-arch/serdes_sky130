"""Freeze and independently exercise the RX host word path; no physical signoff."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from serdes_flow import project

ROOT=project.ROOT
HERE=Path(__file__).resolve()
SOURCES=[ROOT/f'digital/rx/rtl/{name}.sv' for name in ('rx_word_map','rx_word_align16','rx_async_word_fifo','rx_word_host_path')]+[ROOT/'digital/rx/tb/tb_rx_word_host_path.sv',HERE]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path,data):path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')


def main():
    camp=ROOT/'results/verification/digital/rx_word_host_path'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);camp.mkdir(parents=True)
    execution=camp/'execution';execution.mkdir();source_hash={str(p.relative_to(ROOT)):sha(p) for p in SOURCES}
    for p in SOURCES:shutil.copyfile(p,execution/p.name)
    tools={}
    for name,flag in (('iverilog','-V'),('vvp','-V'),('yosys','-V'),('verilator','--version')):
        binary=Path(shutil.which(name) or name).resolve();version=subprocess.run([str(binary),flag],capture_output=True,text=True,timeout=30)
        tools[name]=dict(path=str(binary),sha256=sha(binary),version=(version.stdout+version.stderr).strip())
    report=dict(status='incomplete',sources=source_hash,tools=tools,scope='Independent clocks, training/epoch and observed payload prefixes in behavioral digital simulation; not physical RX or CDC signoff.',
        uncovered=['complete payload tails were not drained in the per-offset checks','SKY130 mapping and STA','Gray bus timing/skew and synchronizer MTBF','reset recovery/removal','actual recovered-clock jitter and analog sampling','frequency offset compensation and host stall budget'])
    def run(name,cmd):
        p=subprocess.run(cmd,cwd=camp,capture_output=True,text=True,timeout=60);log=camp/(name+'.log');log.write_text(p.stdout+p.stderr)
        dump(camp/(name+'.execution.json'),dict(command=cmd,exit_code=p.returncode,log_sha256=sha(log)))
        if p.returncode:raise RuntimeError(name+' failed: '+str(log))
        return p.stdout+p.stderr
    try:
        rtl=[str(execution/p.name) for p in SOURCES[:4]];bench=str(execution/SOURCES[4].name);binary=camp/'host_path.vvp'
        run('compile',[tools['iverilog']['path'],'-g2012','-s','tb_rx_word_host_path','-o',str(binary),*rtl,bench])
        log=run('simulation',[tools['vvp']['path'],str(binary)])
        counts=[(int(a),int(b)) for a,b in re.findall(r'^OFFSET (\d+) payload_prefix=(\d+)$',log,re.M)]
        total=re.search(r'^OFFSETS_TOTAL (\d+)$',log,re.M)
        if 'FAIL' in log or 'PASS host path:' not in log or [p for p,n in counts]!=list(range(16)) or any(n<20 for p,n in counts) or not total or int(total[1])!=sum(n for p,n in counts):
            raise ValueError('missing per-offset payload-prefix checks')
        run('lint',[tools['verilator']['path'],'--lint-only','--top-module','rx_word_host_path',*rtl])
        syn=run('yosys',[tools['yosys']['path'],'-Q','-T','-p',f'read_verilog -sv {" ".join(rtl)}; hierarchy -check -top rx_word_host_path; proc; memory; opt; check; stat'])
        if 'found and reported 0 problems.' not in syn.lower():raise ValueError('synthesis check incomplete')
        for p in SOURCES:
            if sha(p)!=source_hash[str(p.relative_to(ROOT))] or sha(execution/p.name)!=sha(p):raise ValueError('source changed during review')
        report.update(status='digital_word_host_functional_pass_not_physical_signoff',offset_payload_prefixes=[dict(offset=p,words=n) for p,n in counts],total_payload_prefix_words=int(total[1]),
                      scenarios=['16 window offsets','stall stability and full overflow','unread common reset and new epoch','post-payload retraining fault','first pending payload/retraining edge'])
    finally:
        report['evidence']={str(p.relative_to(camp)):sha(p) for p in camp.rglob('*') if p.is_file()}
        dump(camp/'summary.json',report)
    dump(ROOT/'results/catalog/rx_word_host_path.json',dict(summary=str((camp/'summary.json').relative_to(ROOT)),summary_sha256=sha(camp/'summary.json'),
        status=report['status'],sources=source_hash,offset_payload_prefixes=report['offset_payload_prefixes'],total_payload_prefix_words=report['total_payload_prefix_words'],scope=report['scope'],uncovered=report['uncovered']))
    print(camp/'summary.json')


if __name__=='__main__':main()
