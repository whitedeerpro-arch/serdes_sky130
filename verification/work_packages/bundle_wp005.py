"""Build the fixed, read-only external WP-005 input bundle (no simulations).

uv run python verification/work_packages/bundle_wp005.py
Paths and content hashes are verified again while packing. Never overwrites.
"""
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile

from serdes_flow.project import ROOT

CAMPAIGNS=(
 'results/analog/tx/staggered_ingress/20261106T202607Z',
 'results/analog/tx/staggered_ingress/20261106T200647Z',
 'results/analog/tx/staggered_ingress/20261106T202119Z',
)
FILES=(
 'AGENTS.md','README.md','pyproject.toml','uv.lock',
 'config/work_packages.json','config/tools.toml','config/pdk.toml','config/tx_working_revision.toml',
 'docs/design/tx_word_capture.md','docs/design/tx_ingress.md','docs/design/tx_launch_hold.md',
 'analog/common/cml_mux/spice/cml_lowov_cells.spice',
 'verification/work_packages/bundle_wp005.py',
)
DIRECTORIES=('src/serdes_flow','docs/work_packages','analog/tx/input_register/spice','docs/figures/tx/ingress')


def digest(path):
    value=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):value.update(block)
    return value.hexdigest()


def main():
    inputs={ROOT/p for p in FILES}
    for rel in DIRECTORIES+CAMPAIGNS:
        directory=ROOT/rel
        if not directory.is_dir():raise FileNotFoundError(directory)
        inputs.update(p for p in directory.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc')
    rows=[]
    for p in sorted(inputs):
        if p.is_symlink() or not p.resolve().is_relative_to(ROOT) or not p.is_file():
            raise ValueError(f'unsafe or missing input: {p}')
        rows.append(dict(path=str(p.relative_to(ROOT)),sha256=digest(p),bytes=p.stat().st_size))
    manifest=dict(package_id='WP-005',campaigns=list(CAMPAIGNS),files=rows,
                  scope='Fixed raw/deck/log/source snapshots for read-only audit; not a runnable PDK distribution or design acceptance')
    readme='''# WP-005 外部复核资料包

从本目录读取 docs/work_packages/WP-005-tx-staggered-waveform-audit.md 和通用约定。
固定三批运行的原raw/deck/log、执行源码快照及当前辅助源码都保持相对路径；
输入清单位于 BUNDLE_INPUTS.json，先逐文件核对SHA256。只做任务指定的只读审计，ngspice配额0。

执行环境需已有Python与numpy；可用既有uv环境，或在包根目录用
PYTHONPATH=src python3 verification/work_packages/wp005_staggered_waveforms.py --output docs/work_packages/deliveries/WP-005
运行自己按任务写出的脚本。不要为缺失依赖自动联网安装；报告环境缺项即可。

结果写到WP-005交付目录，源码只写指定提取脚本，不改DUT/规格/原运行/中央状态。
README中的其他模块和运行链接属于原仓库索引，不是本包额外输入。
归还evidence.json、summary.md、handoff.md和新脚本，集成者独立复跑后接受。
不要将本包中的其他既有review或设计文档结论当作独立复核的结果。
'''
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'results/work_packages/bundles'/stamp;folder.mkdir(parents=True,exist_ok=False)
    archive=folder/'WP-005-inputs.tar.gz'
    with archive.open('xb') as raw:
        with tarfile.open(fileobj=raw,mode='w:gz') as tar:
            for row in rows:
                path=ROOT/row['path']
                if digest(path)!=row['sha256']:raise ValueError(f'input changed while packing: {path}')
                tar.add(path,arcname=row['path'],recursive=False)
            for name,text in [('BUNDLE_INPUTS.json',json.dumps(manifest,indent=2,ensure_ascii=False)+'\n'),('BUNDLE.md',readme)]:
                data=text.encode();info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
                tar.addfile(info,io.BytesIO(data))
    # Verify every restored byte against the manifest, without extracting.
    wanted={r['path']:r['sha256'] for r in rows}
    with tarfile.open(archive,'r:gz') as tar:
        for member in tar:
            if not member.isfile():raise ValueError('non-file archive member')
            stream=tar.extractfile(member);h=hashlib.sha256()
            for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
            if member.name in wanted and h.hexdigest()!=wanted.pop(member.name):raise ValueError('archive integrity failed')
    if wanted:raise ValueError('archive missed inputs')
    report=dict(package_id='WP-005',archive=str(archive.relative_to(ROOT)),archive_sha256=digest(archive),
                archive_bytes=archive.stat().st_size,input_files=len(rows),input_bytes=sum(r['bytes'] for r in rows),
                verification='every archived file streamed and matched to SHA256; symlinks rejected',simulation_quota=0)
    (folder/'bundle.json').write_text(json.dumps(report,indent=2)+'\n')
    (ROOT/'results/catalog/work_package_wp005_bundle.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
