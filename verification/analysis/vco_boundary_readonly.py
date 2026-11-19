"""Read-only verification of the historical H4 boundary campaign.

The exact SPICE source migration applies only to this analysis context. It does
not modify the original execution or resume checks.
"""
import ast
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

OLD='1ca9376c06a368890787da86d336dcc47960700971e7d19214cc19e8de94691b'
CURRENT='7d97d104f9b938f912515862bc03a9a74c84d1b3de2d43039f9ae3b0b7204d2f'
SPICE='src/serdes_flow/spice.py'
ALLOWED={'Waves','read_raw','_resolve','case_output','_rerun_index','render','corner_values'}
ACTIVE=None


def _audit(event,args):
    if ACTIVE is None: return
    if event=='open':
        mode=args[1]; flags=args[2]
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND)):
            raise PermissionError('read-only verification: write open denied')
    if event=='os.mkdir':
        path=args[0]
        if not os.path.isdir(path): raise PermissionError('read-only verification: new directory denied')
        return
    if event in {'subprocess.Popen','os.system','os.posix_spawn','os.spawn','os.fork','os.forkpty',
                 'os.remove','os.rmdir','os.rename','os.replace','os.link','os.symlink','os.chmod',
                 'os.chown','os.truncate','os.utime','os.chdir'}:
        raise PermissionError(f'read-only verification: {event} denied')


sys.addaudithook(_audit)


def _sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''): h.update(chunk)
    return h.hexdigest()


def _module_nodes(path):
    tree=ast.parse(Path(path).read_text()); result=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'run','log_failures'}: continue
        result.append(ast.dump(node,include_attributes=False))
    return result


class ReadOnlyVerification:
    """Guard the entire verification, including caller's checked/measure operations."""
    def __init__(self,camp,anchor):
        self.camp=Path(camp).resolve(); self.anchor=anchor
        self.report={'spice_old_sha256':OLD,'spice_current_sha256':CURRENT,'spice_calls':[],'ast_equal_excluding':['run','log_failures']}
        self._calls=set(); self._previous=None

    def _profile(self,frame,event,arg):
        if event!='call': return
        filename=Path(frame.f_code.co_filename).resolve()
        root=self.anchor.ROOT
        if filename==root/'src/serdes_flow/mc.py': raise RuntimeError('MC execution denied')
        if filename==root/SPICE:
            name=frame.f_code.co_qualname.split('.')[0]
            if name not in ALLOWED: raise RuntimeError(f'SPICE call denied: {name}')
            self._calls.add(frame.f_code.co_qualname)

    def __enter__(self):
        global ACTIVE
        if ACTIVE is not None: raise RuntimeError('read-only verification already active')
        self._previous=sys.getprofile(); ACTIVE=self; sys.setprofile(self._profile)
        return self

    def __exit__(self,typ,value,tb):
        global ACTIVE
        sys.setprofile(self._previous); ACTIVE=None
        self.report['spice_calls']=sorted(self._calls)
        return False

    def verify(self):
        if ACTIVE is not self: raise RuntimeError('enter context before verification')
        a=self.anchor; camp=self.camp; root=a.ROOT
        plan=json.loads((camp/'plan.json').read_text())
        if plan['pdk_installation_id']!=a.project.pdk_installation_id() or plan['pdk_sha256']!=a.pdk_manifest(): raise ValueError('PDK changed')
        if a.sha(a.SOURCE)!=plan['source_sha256'] or a.sha(a.FILL)!=plan['fill_sha256']: raise ValueError('input summary changed')
        if plan['source_files'].get(SPICE)!=OLD or _sha(camp/'sources'/SPICE)!=OLD or _sha(root/SPICE)!=CURRENT:
            raise ValueError('SPICE migration SHA mismatch')
        before=_module_nodes(camp/'sources'/SPICE); after=_module_nodes(root/SPICE)
        if before!=after:
            differences=[i for i in range(max(len(before),len(after))) if (before[i] if i<len(before) else None)!=(after[i] if i<len(after) else None)]
            raise ValueError(f'SPICE AST mismatch excluding execution definitions, node indices: {differences}')
        for rel,expected in plan['source_files'].items():
            if _sha(camp/'sources'/rel)!=expected: raise ValueError(f'archived source changed {rel}')
            if rel!=SPICE and a.sha(root/rel)!=expected: raise ValueError(f'source changed {rel}')
        for rel,expected in plan['snapshots'].items():
            if a.sha(camp/rel)!=expected: raise ValueError(f'snapshot changed {rel}')
        actual=a.make_plan()
        for key in ('already_complete','selected','no_single_point_candidate','scope'):
            if plan[key]!=actual[key]: raise ValueError(f'plan identity changed {key}')
        groups=defaultdict(list)
        for item in plan['selected']:
            if item['existing_boundary_frequency_hz'] is None: groups[a.group_name(item)].append(item)
        if {g['name'] for g in plan['groups']}!=set(groups): raise ValueError('group identity changed')
        for g in plan['groups']:
            proc,rc=g['name'].split('_'); items=groups[g['name']]
            if g['conditions']!=[x['condition'] for x in items] or (camp/g['deck']).read_text()!=a.wm.deck(proc,rc,a.points(items),camp/'snap'/g['name'],4):
                raise ValueError('prepared deck changed')
        self.report['ast_verified']=True
        return plan,groups
