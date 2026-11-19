"""Static subcircuit port counts for an explicit prepared native TX deck.

Uses the independent project reader; does not invoke ngspice or imply LVS,
electrical correctness, loading qualification or dynamic data correctness.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re

from serdes_flow import netlist,project

ROOT=project.ROOT


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--deck',type=Path,required=True);a=ap.parse_args()
    deck=a.deck.resolve();text=deck.read_text()
    paths=[Path(s) for s in re.findall(r'^\.include\s+"([^"]+)"',text,re.M|re.I)]
    if any(not p.is_file() for p in paths):raise ValueError('An include is missing')
    out=deck.parent.parent/'checks'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');out.mkdir(parents=True)
    root=[];inside=False
    for line in netlist._logical_lines(text.split('.control',1)[0]):
        head=line.split()[0].lower()
        if head=='.subckt':inside=True
        elif head.startswith('.ends'):inside=False
        elif not inside and head.startswith('x'):root.append(line)
    top=out/'top.spice';top.write_text('.subckt __joint_fixture\n'+'\n'.join(root)+'\n.ends __joint_fixture\n')
    subs=netlist.parse([*paths,deck,top]);errors=[];unknown=set();checked=0
    for name,sub in subs.items():
        for e in sub.elements:
            if e.ref in subs:
                checked+=1
                expected=len(subs[e.ref].ports)
                if len(e.nodes)!=expected:errors.append(dict(parent=name,instance=e.name,child=e.ref,actual=len(e.nodes),expected=expected))
            elif e.ref not in ('R','C') and not e.ref.startswith('sky130_fd_pr__'):
                unknown.add(e.ref)
    result=dict(deck=str(deck.relative_to(ROOT)),deck_sha256=hashlib.sha256(deck.read_bytes()).hexdigest(),
        includes=len(paths),subcircuits=len(subs),checked_instances=checked,root_instances=len(root),
        errors=errors,unknown=sorted(unknown),passed=not errors and not unknown,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        parser_sha256=hashlib.sha256(Path(netlist.__file__).read_bytes()).hexdigest(),
        scope='Static X-instance port counts and unresolved references only; not SPICE execution, LVS or electrical qualification')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));print(out.relative_to(ROOT))
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
