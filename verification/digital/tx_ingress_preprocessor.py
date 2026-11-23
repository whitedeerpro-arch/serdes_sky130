"""Archive the legacy r2 remap and ingress preprocessor RTL checks.

uv run python verification/digital/tx_ingress_preprocessor.py
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from serdes_flow.project import ROOT, git_revision

SCOPE = ('Legacy r2 mapping adapter RTL behavior, lint and generic structure; '
         'current v3 identity path does not adopt this adapter. No cell mapping, STA, CDC or analog integration.')
SOURCES = [
    'digital/tx/rtl/tx_word_remap.sv',
    'digital/tx/rtl/tx_ingress_control.sv',
    'digital/tx/rtl/tx_ingress_preprocessor.sv',
    'digital/tx/tb/tb_tx_word_remap.sv',
    'digital/tx/tb/tb_tx_ingress_preprocessor.sv',
    'digital/tx/tb/data/serializer_state_permutations.hex',
    'verification/digital/tx_ingress_preprocessor.py',
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    camp = ROOT / 'results/digital/tx/ingress_preprocessor' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    camp.mkdir(parents=True, exist_ok=False)
    snapshot = camp / 'execution'
    result = dict(status='failed', git_revision=git_revision(), scope=SCOPE, sources={}, commands=[], checks=[])
    error = None
    try:
        for rel in SOURCES:
            source = ROOT / rel
            target = snapshot / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            result['sources'][rel] = digest(target)

        def run(name, argv):
            record = dict(name=name, argv=argv, cwd=str(snapshot.relative_to(ROOT)), log=name + '.log')
            result['commands'].append(record)
            try:
                completed = subprocess.run(argv, cwd=snapshot, capture_output=True, text=True, timeout=45)
                output = completed.stdout + completed.stderr
                record['exit_code'] = completed.returncode
            except subprocess.TimeoutExpired as exc:
                output = str(exc)
                record['error'] = 'timeout'
                (camp / record['log']).write_text(output + '\n')
                raise RuntimeError(f'{name}: timeout') from exc
            (camp / record['log']).write_text(output)
            if completed.returncode:
                raise RuntimeError(f'{name}: exit {completed.returncode}')
            return output

        remap = 'digital/tx/rtl/tx_word_remap.sv'
        guard = 'digital/tx/rtl/tx_ingress_control.sv'
        rtl = 'digital/tx/rtl/tx_ingress_preprocessor.sv'
        old_tb = 'digital/tx/tb/tb_tx_word_remap.sv'
        tb = 'digital/tx/tb/tb_tx_ingress_preprocessor.sv'
        old_vvp, new_vvp = str(camp / 'remap.vvp'), str(camp / 'preprocessor.vvp')
        run('compile_legacy', ['iverilog', '-g2012', '-s', 'tb_tx_word_remap', '-o', old_vvp, remap, old_tb])
        old = run('legacy', ['vvp', old_vvp])
        if re.findall(r'PASS tx_word_remap: 8 measured states, (\d+) words restored', old) != ['512'] or 'FAIL' in old:
            raise ValueError('legacy result missing or inconsistent')
        result['checks'].append(dict(name='legacy', states=8, words=512))
        run('compile_preprocessor', ['iverilog', '-g2012', '-s', 'tb_tx_ingress_preprocessor', '-o', new_vvp, remap, guard, rtl, tb])
        out = run('preprocessor', ['vvp', new_vvp])
        if (re.findall(r'PASS preprocessor WARMUP_FALLS=(\d+) checks=(\d+)', out) != [('1', '211'), ('2', '227')]
                or 'PASS both warmup configurations' not in out or 'FAIL' in out):
            raise ValueError('preprocessor result missing or inconsistent')
        result['checks'].extend([dict(name='preprocessor', warmup=1, assertions=211), dict(name='preprocessor', warmup=2, assertions=227)])
        run('lint_legacy', ['verilator', '--lint-only', '-Wall', '--top-module', 'tx_word_remap', remap])
        run('lint_preprocessor', ['verilator', '--lint-only', '-Wall', '--top-module', 'tx_ingress_preprocessor', remap, guard, rtl])
        structural = run('structural', ['yosys', '-Q', '-T', '-p', f'read_verilog -sv {remap} {guard} {rtl}; hierarchy -check -top tx_ingress_preprocessor; proc; opt; check -assert'])
        if 'found and reported 0 problems.' not in structural:
            raise ValueError('structural completion missing')
        result.update(status='pass', legacy_words=512, preprocessor_assertions=438)
    except Exception as exc:
        error = exc
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        summary = camp / 'summary.json'
        summary.write_text(json.dumps(result, indent=2) + '\n')
        catalog = ROOT / 'results/catalog/tx_ingress_preprocessor.json'
        index = json.loads(catalog.read_text()) if catalog.exists() else {'campaigns': []}
        index['campaigns'].append(dict(campaign=str(camp.relative_to(ROOT)), summary_sha256=digest(summary), status=result['status']))
        catalog.parent.mkdir(parents=True, exist_ok=True)
        catalog.write_text(json.dumps(index, indent=2) + '\n')
        print(f"{camp}: {result['status']}", flush=True)
    if error is not None:
        raise error


if __name__ == '__main__':
    main()
