"""Package WP-006's fixed digital/model inputs; never include raw waves or PDK.

    uv run python verification/work_packages/bundle_wp006.py --check
    uv run python verification/work_packages/bundle_wp006.py

--check is read-only. Default creates an append-only bundle and catalog index.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile

from serdes_flow.project import ROOT

EVIDENCE = 'docs/work_packages/deliveries/WP-006/evidence.json'
# Exact input identities, checked against the evidence before packaging.
EVIDENCE_PATHS = (
    'results/analog/pll/vco/workmap/20261106T035710Z/summary.json',
    'results/analog/pll/vco/workmap/20261106T035710Z/extend.json',
    'config/pll_code_table.json', 'config/vco_coarse_calibration.toml',
    'analog/pll/vco/tb/tuning/workmap.py', 'analog/pll/vco/tb/tuning/code_table.py',
    'docs/design/pll_vco.md', 'docs/design/pll_loop.md', 'docs/data/vco_cp_edge_fill.json',
)
FILES = (
    'AGENTS.md', 'README.md', 'pyproject.toml', 'uv.lock', 'docs/overview/spec.md',
    'docs/work_packages/README.md', 'docs/work_packages/WP-006-pll-4bit-coarse-plan.md',
    EVIDENCE, 'docs/work_packages/deliveries/WP-006/summary.md',
    'docs/work_packages/deliveries/WP-006/handoff.md',
    'docs/work_packages/deliveries/WP-006/resolution_tradeoff.json',
    'docs/work_packages/deliveries/WP-006/resolution_tradeoff.md',
    'verification/work_packages/wp006_pll_coarse.py',
    'verification/work_packages/bundle_wp006.py',
    'src/serdes_flow/__init__.py', 'src/serdes_flow/corners.py', 'src/serdes_flow/project.py',
    'docs/figures/clocking/vco/vco_fixed_code_temperature.png',
)

README = '''# WP-006 行为模型资料包

先读 AGENTS.md、docs/work_packages/README.md 和 WP-006 任务说明。现有 evidence、
summary、handoff 为 partial：行为模型尚未实现。实现便携的纯数学/数字行为模型并
按任务测试，不改电路、配置、原数据或中央状态；集成者独立复跑并 review。

输入数字数据足以完成模型任务。包内不含 raw 波形、PDK、模拟器或旧运行目录；
不要读取 raw、运行 ngspice 或运行 wp006_pll_coarse.py --tradeoff。证据中原42组
静态记录与新增3组固定码静态补测分别记录；不能当成启动或动态闭环覆盖。历史
frozen_bad 是原扫描覆盖记录，不可用来断言固定码无解。

BUNDLE_INPUTS.json 包含逐文件 SHA-256；先检查输入身份。仅需提取主证据时，可在
已有 Python、numpy 的离线环境中执行：
    PYTHONPATH=src python verification/work_packages/wp006_pll_coarse.py
不要联网安装依赖；环境缺失请报告。仓库其他链接仅作背景索引，不属于本包输入。
'''


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inputs():
    evidence = json.loads((ROOT / EVIDENCE).read_text())
    identity = {item['path']: item['sha256'] for item in evidence['inputs']}
    if evidence['package_id'] != 'WP-006' or set(identity) != set(EVIDENCE_PATHS) or len(evidence['inputs']) != len(EVIDENCE_PATHS):
        raise ValueError('WP-006 evidence input identity differs from fixed nine files')
    rows = []
    for rel in sorted(set(FILES) | set(EVIDENCE_PATHS)):
        path = ROOT / rel
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f'unsafe or missing input: {path}')
        if path.suffix.lower() in ('.raw', '.gz', '.spice'):
            raise ValueError(f'raw, compressed or circuit input forbidden: {rel}')
        row = {'path': rel, 'sha256': digest(path), 'bytes': path.stat().st_size}
        if rel in identity and row['sha256'] != identity[rel]:
            raise ValueError(f'evidence input changed: {rel}')
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='list inputs and sizes; write nothing')
    args = parser.parse_args()
    rows = inputs()
    if args.check:
        print(json.dumps({'files': rows, 'input_files': len(rows),
                          'input_bytes': sum(r['bytes'] for r in rows)}, indent=2))
        return
    index = ROOT / 'results/catalog/work_package_wp006_bundle.json'
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder = ROOT / 'results/work_packages/bundles' / stamp
    folder.mkdir(parents=True, exist_ok=False)
    archive = folder / 'WP-006-inputs.tar.gz'
    manifest = {'package_id': 'WP-006', 'files': rows,
                'scope': 'Portable digital behavior model; no raw, PDK, simulator or circuit execution.'}
    generated = {'BUNDLE_INPUTS.json': (json.dumps(manifest, indent=2, ensure_ascii=False) + '\n').encode(),
                 'BUNDLE.md': README.encode()}
    expected = {r['path']: r['sha256'] for r in rows}
    expected.update({name: hashlib.sha256(data).hexdigest() for name, data in generated.items()})
    with archive.open('xb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz') as tar:
            for row in rows:
                path = ROOT / row['path']
                if digest(path) != row['sha256']:
                    raise ValueError(f'input changed while packing: {path}')
                tar.add(path, arcname=row['path'], recursive=False)
            for name, data in generated.items():
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(data), 0o644
                tar.addfile(info, io.BytesIO(data))
    # Read every archive member's payload back and verify, including generated metadata.
    wanted = expected.copy()
    with tarfile.open(archive, 'r:gz') as tar:
        for member in tar:
            if not member.isfile() or member.name not in wanted:
                raise ValueError(f'unexpected archive member: {member.name}')
            stream = tar.extractfile(member)
            h = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
            if h.hexdigest() != wanted.pop(member.name):
                raise ValueError(f'archive integrity failed: {member.name}')
    if wanted:
        raise ValueError(f'archive missed inputs: {sorted(wanted)}')
    report = {'package_id': 'WP-006', 'archive': str(archive.relative_to(ROOT)),
              'archive_sha256': digest(archive), 'archive_bytes': archive.stat().st_size,
              'input_files': len(rows), 'input_bytes': sum(r['bytes'] for r in rows),
              'verification': 'all members streamed and SHA-256 verified', 'simulation_quota': 0}
    text = json.dumps(report, indent=2) + '\n'
    (folder / 'bundle.json').write_text(text)
    index.parent.mkdir(parents=True,exist_ok=True)
    pending=index.with_suffix('.json.tmp')
    pending.write_text(text)
    pending.replace(index)
    print(text, end='')


if __name__ == '__main__':
    main()
