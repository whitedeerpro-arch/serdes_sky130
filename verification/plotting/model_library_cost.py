"""Publish compact timing/equivalence data from an explicit library benchmark."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from serdes_flow.project import ROOT


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--summary',type=Path,required=True);a=p.parse_args()
    source=a.summary.resolve();report=json.loads(source.read_text());camp=source.parent
    if report['status']!='three_corner_short_card_and_one_r6_VCO_equivalent_no_production_adoption':
        raise ValueError('benchmark is incomplete')
    for name,h in report['evidence'].items():
        if sha(camp/name)!=h:raise ValueError('benchmark evidence changed: '+name)
    for name,h in report['sources'].items():
        if sha(camp/'execution'/name)!=h:raise ValueError('frozen source changed: '+name)
    def cost(folder):
        log=(folder/'simulator.log').read_text()
        before=log.split('Doing analysis at TEMP',1)[0]
        def value(pattern):
            match=re.search(pattern,before)
            if not match:raise ValueError('missing setup resource measurement')
            return float(match[1])
        return dict(setup_elapsed_s=value(r'Total elapsed time \(seconds\)\s*=\s*([0-9.]+)'),
                    setup_program_mb=value(r'Current ngspice program size\s*=\s*([0-9.]+)'))
    rows=[]
    for row in report['cases']:
        if not row['comparison']['passed']:raise ValueError('short-card equivalence failed')
        rows.append(dict(section=row['section'],full_s=row['runs']['full']['elapsed_s'],reduced_s=row['runs']['reduced']['elapsed_s'],
                         speed_ratio=row['short_card_speed_ratio'],
                         full_setup=cost(camp/row['section']/'full'),reduced_setup=cost(camp/row['section']/'reduced'),
                         equivalence_passed=True))
    v=report['vco']
    if not v['comparison']['passed']:raise ValueError('actual VCO equivalence failed')
    data=dict(status=report['status'],summary=str(source.relative_to(ROOT)),summary_sha256=sha(source),
              scope=report['scope'],short_card=rows,
              vco=dict(identity=v['identity'],devices=v['devices'],full_s=v['runs']['full']['elapsed_s'],
                       reduced_s=v['runs']['reduced']['elapsed_s'],speed_ratio=v['speed_ratio'],comparison=v['comparison']),
              production_default_changed=False,MC_qualified=False,publisher_sha256=sha(Path(__file__)))
    dest=ROOT/'docs/data/model_library_cost.json';dest.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    (ROOT/'results/catalog/model_library_cost.json').write_text(json.dumps(dict(data=str(dest.relative_to(ROOT)),data_sha256=sha(dest),
        summary=data['summary'],summary_sha256=data['summary_sha256'],status=data['status']),indent=2)+'\n')
    print(json.dumps(dict(short_card=rows,vco={k:v for k,v in data['vco'].items() if k not in ('identity','devices')}),indent=2))


if __name__=='__main__':main()
