"""Freeze and exercise the RX word FIFO without claiming physical CDC signoff."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from serdes_flow import project

ROOT = project.ROOT
HERE = Path(__file__).resolve()
RTL = ROOT / 'digital/rx/rtl/rx_async_word_fifo.sv'
BENCH = ROOT / 'digital/rx/tb/tb_rx_async_word_fifo.sv'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def dump(path, data): path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def main():
    camp = ROOT / 'results/verification/digital/rx_async_word_fifo' / (
        datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid.uuid4().hex[:8])
    camp.mkdir(parents=True); execution = camp / 'execution'; execution.mkdir()
    sources = {str(p.relative_to(ROOT)): sha(p) for p in (HERE, RTL, BENCH)}
    for p in (HERE, RTL, BENCH): shutil.copyfile(p, execution / p.name)
    tools = {}
    for name, flag in (('iverilog', '-V'), ('vvp', '-V'), ('yosys', '-V'), ('verilator', '--version')):
        binary = Path(shutil.which(name) or name).resolve()
        version = subprocess.run([str(binary), flag], text=True, capture_output=True, timeout=30)
        tools[name] = dict(path=str(binary), sha256=sha(binary), version=(version.stdout + version.stderr).strip())
    result = dict(status='incomplete', sources=sources, tools=tools, cases=[],
                  scope='Abstract independent clocks and reset epochs. Functional RTL and generic synthesis only; not connected to the physical RX.',
                  uncovered=['SKY130 mapping/STA', 'physical Gray bus delay/skew and synchronizer MTBF',
                             'reset recovery/removal', 'actual recovered-clock jitter/PI steps',
                             'FIFO depth/host stall budget and protocol clock compensation',
                             'system fault handling after overflow'])

    def run(name, command):
        out = subprocess.run(command, cwd=camp, capture_output=True, text=True, timeout=60)
        log = camp / (name + '.log'); log.write_text(out.stdout + out.stderr)
        dump(camp / (name + '.execution.json'), dict(command=command, exit_code=out.returncode,
                                                    log_sha256=sha(log)))
        if out.returncode: raise RuntimeError(name + ' failed: ' + str(log))
        return out.stdout + out.stderr

    try:
        for bits in (1, 2, 4):
            tag = 'depth' + str(2**bits); binary = camp / (tag + '.vvp')
            run(tag + '_compile', [tools['iverilog']['path'], '-g2012', '-s', 'tb_rx_async_word_fifo',
                '-P', f'tb_rx_async_word_fifo.ADDR_BITS={bits}', '-o', str(binary),
                str(execution / RTL.name), str(execution / BENCH.name)])
            log = run(tag + '_simulation', [tools['vvp']['path'], str(binary)])
            match = re.search(r'^PASS depth=(\d+) accepted reads=(\d+) rejected=(\d+) arrivals=(\d+) reset_discarded=(\d+)$', log, re.M)
            if 'FAIL' in log or not match or int(match[1]) != 2**bits: raise ValueError('incomplete functional result')
            synthesis = run(tag + '_yosys', [tools['yosys']['path'], '-Q', '-T', '-p',
                f'read_verilog -sv {execution / RTL.name}; hierarchy -check -top rx_async_word_fifo -chparam ADDR_BITS {bits}; '
                'proc; memory; opt; check; stat'])
            if 'found and reported 0 problems.' not in synthesis.lower(): raise ValueError('generic synthesis check incomplete')
            run(tag + '_lint', [tools['verilator']['path'], '--lint-only', '--top-module', 'rx_async_word_fifo',
                                f'-GADDR_BITS={bits}', str(execution / RTL.name)])
            result['cases'].append(dict(address_bits=bits, depth=int(match[1]), accepted_reads=int(match[2]),
                rejected_arrivals=int(match[3]), word_arrivals=int(match[4]), reset_discarded=int(match[5]),
                simulation='pass', generic_synthesis='pass', lint='pass'))
        for p in (HERE, RTL, BENCH):
            if sha(p) != sources[str(p.relative_to(ROOT))] or sha(execution / p.name) != sha(p):
                raise ValueError('review sources changed')
        result['status'] = 'rtl_cdc_primitive_functional_pass_not_physical_signoff'
    finally:
        result['evidence'] = {str(p.relative_to(camp)): sha(p) for p in camp.rglob('*') if p.is_file()}
        dump(camp / 'summary.json', result)
    dump(ROOT / 'results/catalog/rx_async_word_fifo.json', dict(summary=str((camp / 'summary.json').relative_to(ROOT)),
        summary_sha256=sha(camp / 'summary.json'), status=result['status'], sources=sources, cases=result['cases'],
        scope=result['scope'], uncovered=result['uncovered']))
    print(camp / 'summary.json')


if __name__ == '__main__': main()
