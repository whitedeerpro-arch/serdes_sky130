"""Export a fixed switch-allocation study, with frozen-input verification."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

from serdes_flow import project

ROOT = project.ROOT


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--summary', type=Path, required=True)
    a = ap.parse_args()
    source = a.summary.resolve()
    summary = json.loads(source.read_text())
    campaign = ROOT/summary['campaign']
    plan_path = campaign/'plan.json'
    if sha(plan_path) != summary['plan_sha256']:
        raise ValueError('Plan identity changed')
    plan = json.loads(plan_path.read_text())
    for name, digest in plan['inputs'].items():
        if sha(campaign/name) != digest:
            raise ValueError('Frozen input changed: '+name)
    identity = {str(source.relative_to(ROOT)):sha(source),
                str(plan_path.relative_to(ROOT)):sha(plan_path)}
    data = dict(scope=summary['scope'], profiles=summary['profiles'],
                code_map_by_process=summary['code_map_by_process'], conditions=[], inputs_sha256=identity)
    for row in summary['rows']:
        run = ROOT/row['run']
        for path in run.iterdir():
            if path.is_file() and path.suffix in ('.tsv', '.json', '.cir', '.log'):
                identity[str(path.relative_to(ROOT))] = sha(path)
        data['conditions'].append(dict(condition=row['condition'],
            profiles={name:rows[-1] for name,rows in row['profiles'].items()}))
    dest = ROOT/'results/analog/pll/vco/switch_allocation_review'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    dest.mkdir(parents=True)
    shutil.copyfile(Path(__file__), dest/'export.py')
    identity[str((dest/'export.py').relative_to(ROOT))] = sha(dest/'export.py')
    (dest/'summary.json').write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
    data_path = ROOT/'docs/data/vco_switch_allocation.json'
    data_path.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
    catalog = dict(summary=str((dest/'summary.json').relative_to(ROOT)),
                   summary_sha256=sha(dest/'summary.json'),
                   data=str(data_path.relative_to(ROOT)), data_sha256=sha(data_path),
                   source=str(source.relative_to(ROOT)), source_sha256=sha(source), scope=summary['scope'])
    (ROOT/'results/catalog/vco_switch_allocation.json').write_text(json.dumps(catalog, indent=2)+'\n')
    print(dest/'summary.json')


if __name__ == '__main__':
    main()
