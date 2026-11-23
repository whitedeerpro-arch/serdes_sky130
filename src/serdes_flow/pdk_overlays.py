"""Explicit, isolated PDK overlays for investigated simulator expression issues.

The installed PDK is never edited. Every source file and changed model is
identified in the overlay manifest; consumers must opt in to its library path.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil

from . import project


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixed_poly_cube(text):
    """Replace one dynamic contact pow(x,3) with signed x*x*x, and nothing else."""
    if not re.search(r'^\.subckt\s+sky130_fd_pr__res_high_po_(1p41|2p85)\b',text,re.M):
        raise ValueError('not a supported fixed-width high-poly model')
    lines=text.splitlines(keepends=True);changes=[]
    for i,line in enumerate(lines):
        if not re.match(r'^rend\s+r0\s+ra\s+r\s*=',line):continue
        start=0
        while (position:=line.find('pow(',start))>=0:
            depth,comma,end=1,None,None
            for k in range(position+4,len(line)):
                if line[k]=='(':depth+=1
                elif line[k]==')':
                    depth-=1
                    if depth==0:end=k;break
                elif line[k]==',' and depth==1:comma=k
            if comma is None or end is None:raise ValueError('malformed pow expression')
            argument,exponent=line[position+4:comma].strip(),line[comma+1:end].strip()
            if exponent=='3':
                if not argument.startswith('min(') or 'abs(v(r0,r1))' not in argument:
                    raise ValueError('unexpected cube in fixed-card contact resistor')
                replacement=f'(({argument})*({argument})*({argument}))'
                changes.append(dict(original=line[position:end+1],replacement=replacement))
                line=line[:position]+replacement+line[end+1:];start=position+len(replacement)
            else:start=end+1
        lines[i]=line
    if len(changes)!=1:raise ValueError('expected exactly one investigated contact cube')
    return ''.join(lines),changes[0]


def fixed_poly_library(destination):
    """Create a new relative-include-compatible model tree and return its manifest."""
    destination=Path(destination).resolve()
    if destination.exists():raise FileExistsError('overlay destination must be new')
    source=project.model_library().parents[2]
    directories=('libs.tech/ngspice','libs.ref/sky130_fd_pr/spice')
    original={str(p.relative_to(source)):sha(p) for folder in directories for p in (source/folder).rglob('*') if p.is_file()}
    for folder in directories:shutil.copytree(source/folder,destination/folder)
    changes=[]
    for card in ('1p41','2p85'):
        rel=f'libs.ref/sky130_fd_pr/spice/sky130_fd_pr__res_high_po_{card}.model.spice'
        path=destination/rel;after,change=fixed_poly_cube(path.read_text());path.write_text(after)
        changes.append(dict(path=rel,source_sha256=original[rel],overlay_sha256=sha(path),**change))
    changed={c['path']:c['overlay_sha256'] for c in changes}
    for rel,expected in original.items():
        if sha(destination/rel)!=changed.get(rel,expected):raise ValueError('undeclared overlay difference')
        if sha(source/rel)!=expected:raise ValueError('source PDK changed while copying')
    manifest=dict(id='fixed_high_po_signed_contact_cube_v1',source_pdk=str(source),
                  source_installation_id=project.pdk_installation_id(),source_files=original,changes=changes,
                  library=str(destination/'libs.tech/ngspice/sky130.lib.spice'),
                  scope='Only dynamic cubic expression in 1p41/2p85 contact resistance. Same signed DC function; AC derivative correction under project ngspice47/HSA. Not an official PDK update or automatic project default.')
    (destination/'overlay.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest
