"""Read-only snapshot audit of one explicitly named in-flight r6 map campaign."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import time
import uuid

import numpy as np
from serdes_flow import clock, corners, project, spice

ROOT=project.ROOT
HERE=Path(__file__).resolve()
R6=ROOT/'analog/pll/vco/tb/tuning/r6.py'
WORKMAP=ROOT/'analog/pll/vco/tb/tuning/workmap.py'
CORNERS=('tt','hh','ll')
EXPECTED_CAMPAIGN=ROOT/'results/analog/pll/vco/r6/map_20261112T062237Z'


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def signature(p):
    st=p.stat();return (st.st_size,st.st_mtime_ns,st.st_ino)


def stable_sha(p,minimum_age_s=2):
    before=signature(p)
    if time.time_ns()-before[1]<minimum_age_s*1e9:raise ValueError('recently modified')
    digest=sha(p)
    if before!=signature(p):raise ValueError('changed while hashing')
    return dict(sha256=digest,size=before[0],mtime_ns=before[1],inode=before[2])


def metrics(t,y,start=9e-9,drift_limit=5e-4):
    t,y=np.asarray(t),np.asarray(y)
    if len(t)<2 or len(y)!=len(t) or not np.all(np.isfinite(t)) or not np.all(np.isfinite(y)) or np.any(np.diff(t)<=0):raise ValueError('invalid/non-finite waveform')
    use=t>=start;r=clock.edges(t[use],y[use],1);n=len(r)
    out=dict(rising_edges=n,frequency_hz=None,drift_fraction=None,reader_returns_number=False,qualified_window=False)
    if n>=4:out['frequency_hz']=float((n-1)/(r[-1]-r[0]))
    if n>=6:
        h=n//2;f1=h/(r[h]-r[0]);f2=(n-1-h)/(r[-1]-r[h]);out['drift_fraction']=float(f2/f1-1)
        out['reader_returns_number']=True;out['qualified_window']=bool(abs(out['drift_fraction'])<=drift_limit)
        out['status']='settled' if out['qualified_window'] else 'unsettled_reader_returns_number'
    elif n>=4:out['status']='4_or_5_edges_reader_skips'
    else:out['status']='insufficient_edges'
    return out


def deck_point(deck,name,c,rc,code,v):
    text=deck.read_text()
    # A deck can contain many points, so select the last preceding option rather than first.
    chunks=re.split(r'(?m)(?=^option temp=)',text)
    chunks=[s for s in chunks if re.search(r'(?m)^write '+re.escape(name)+r' v\(v0p\) v\(v0n\)$',s)]
    if len(chunks)!=1:raise ValueError('point not uniquely present in executed deck')
    chunk=chunks[0];expected=[f'option temp={c.temp}',f'alter Vdd dc={c.supply}',f'alter Vref dc={c.supply}',
            *[f'alter Vb{k} dc={c.supply if (code>>k)&1 else 0}' for k in range(5)],f'alter Vctrl dc={v}',
            'tran 4p 1.4000e-08 8.0000e-09',f'write {name} v(v0p) v(v0n)']
    lines=chunk.splitlines()
    if any(lines.count(s)!=1 for s in expected):raise ValueError('point stimulus or analysis differs from declared grid')
    section=c.process if rc=='tt' else rc if c.process=='tt' else c.process+'_'+rc
    if not re.search(r'(?m)^\.lib "[^"]+" '+section+'$',text):raise ValueError('MOS/passive model section differs')
    return text


def freeze_sources(deck,text):
    paths=[Path(x) for x in re.findall(r'(?m)^\.include "([^"]+)"',text)]
    library=re.search(r'(?m)^\.lib "([^"]+)"',text)
    if not library:raise ValueError('missing model library')
    paths.append(Path(library[1]));results={}
    for p in paths:
        if not p.is_file():raise ValueError('missing include '+str(p))
        # PDK libraries may be shared but have their own recorded identity.
        results[str(p)]=stable_sha(p)
    return results


def audit(campaign,out):
    spec=importlib.util.spec_from_file_location('audit_r6_source',R6);r6=importlib.util.module_from_spec(spec);spec.loader.exec_module(r6)
    if campaign.resolve()!=EXPECTED_CAMPAIGN.resolve():raise ValueError('explicit campaign does not match this audit')
    expected=[(c,rc,k,v) for c in corners.grid45() for rc in CORNERS for k in r6.COARSE for v in r6.vgrid(c)]
    if len(expected)!=1620 or r6.COARSE!=(0,15,31) or r6.wm.STOP!=14e-9 or r6.DRIFT!=5e-4:raise ValueError('unexpected current reader/grid')
    source_paths=[HERE,R6,WORKMAP,Path(spice.__file__),Path(clock.__file__),ROOT/'src/serdes_flow/waves.py',ROOT/'src/serdes_flow/corners.py',ROOT/'config/pdk.toml', ROOT/'config/tools.toml']
    sources={str(p.relative_to(ROOT)):stable_sha(p,0) for p in source_paths}
    for p in source_paths:shutil.copyfile(p,out/'execution'/p.name)
    pdk=project.model_library().parents[2]
    model_files=[p for folder in ('libs.tech/ngspice','libs.ref/sky130_fd_pr/spice') for p in (pdk/folder).rglob('*') if p.is_file()]
    model_hashes={str(p):sha(p) for p in sorted(model_files)}
    binary=Path(project.ngspice()); tool=dict(path=str(binary),sha256=sha(binary))
    (out/'pdk_manifest.json').write_text(json.dumps(dict(root=str(pdk),files=model_hashes,ngspice=tool),indent=2)+'\n')
    # Freeze the existence and current identity of every candidate before measurements.
    inventory=[];cache={};now=time.time_ns()
    for c,rc,k,v in expected:
        base=f'{c.process}_{rc}';name=r6.wm.name(c,k,v)
        dirs=[d for d in campaign.glob(base+'.r*') if d.name.rsplit('.r',1)[1].isdigit()]+[campaign/base]
        candidates=[]
        for d in sorted(dirs,key=lambda p:spice._rerun_index(p,base),reverse=True):
            raw=d/name
            if not raw.is_file():continue
            try:
                rawid=stable_sha(raw);deck=d/'tb.cir';deckid=stable_sha(deck)
                key=str(deck)
                if key not in cache:
                    text=deck.read_text();cache[key]=dict(deck=deckid,includes=freeze_sources(deck,text),execution=None,spiceinit=stable_sha(d/'.spiceinit'))
                    if (d/'execution.json').is_file():
                        ex=json.loads((d/'execution.json').read_text());cache[key]['execution']=dict(identity=stable_sha(d/'execution.json'),exit_code=ex['exit_code'],timed_out=ex['timed_out'],log_failures=ex['log_failures'],deck_sha256=ex['deck_sha256'])
                        if ex['deck_sha256']!=deckid['sha256']:raise ValueError('execution/deck hash mismatch')
                text=deck_point(deck,name,c,rc,k,v)
                if signature(deck)!=(deckid['size'],deckid['mtime_ns'],deckid['inode']):raise ValueError('deck changed while reading')
                candidates.append(dict(raw=str(raw.relative_to(ROOT)),identity=rawid,deck=key,execution=cache[key]['execution']))
            except (OSError,ValueError,KeyError) as exc:candidates.append(dict(raw=str(raw.relative_to(ROOT)),error=str(exc)))
        inventory.append(dict(condition=c.tag,rc=rc,code=k,vctrl=v,candidates=candidates))
    (out/'inventory.json').write_text(json.dumps(dict(captured_utc=datetime.now(timezone.utc).isoformat(),source_hashes=sources,decks=cache,points=inventory),indent=2)+'\n')
    rows=[]
    for item in inventory:
        row={k:item[k] for k in ('condition','rc','code','vctrl')};row['status']='missing';reasons=[]
        for cand in item['candidates']:
            if 'error' in cand:reasons.append(cand['error']);continue
            p=ROOT/cand['raw'];ident=cand['identity']
            try:
                if signature(p)!=(ident['size'],ident['mtime_ns'],ident['inode']) or sha(p)!=ident['sha256']:raise ValueError('changed after inventory')
                deckid=cache[cand['deck']]['deck'];d=Path(cand['deck'])
                if signature(d)!=(deckid['size'],deckid['mtime_ns'],deckid['inode']) or sha(d)!=deckid['sha256']:raise ValueError('deck changed after inventory')
                for path,info in cache[cand['deck']]['includes'].items():
                    if signature(Path(path))!=(info['size'],info['mtime_ns'],info['inode']):raise ValueError('include changed after inventory')
                w=spice.Waves(p)
                if not len(w.t) or w.t[-1]<14e-9*(1-1e-6):raise ValueError('truncated before 14ns')
                if signature(p)!=(ident['size'],ident['mtime_ns'],ident['inode']) or sha(p)!=ident['sha256']:raise ValueError('waveform changed during analysis')
                row.update(metrics(w.t,w['v(v0p)']-w['v(v0n)']));row.update(raw=cand['raw'],raw_sha256=ident['sha256'],deck=cand['deck'],deck_sha256=deckid['sha256'],execution=cand['execution'])
                break
            except (OSError,ValueError,KeyError,IndexError) as exc:reasons.append(str(exc))
        if row['status']=='missing' and reasons:row['status']='unavailable_or_writing';row['reasons']=reasons
        rows.append(row)
    for path,info in sources.items():
        if sha(ROOT/path)!=info['sha256']:raise ValueError('analysis source changed after inventory: '+path)
    for entry in cache.values():
        for path,info in entry['includes'].items():
            if sha(Path(path))!=info['sha256']:raise ValueError('deck include changed after inventory: '+path)
    if sha(binary)!=tool['sha256'] or any(sha(Path(p))!=h for p,h in model_hashes.items()):raise ValueError('PDK or binary changed after inventory')
    counts=Counter(r['status'] for r in rows)
    for label in ('settled','unsettled_reader_returns_number','4_or_5_edges_reader_skips','insufficient_edges','unavailable_or_writing','missing'):counts.setdefault(label,0)
    unsettled=[r for r in rows if r['status']=='unsettled_reader_returns_number']
    result=dict(status='partial_campaign_read_only_audit',campaign=str(campaign.relative_to(ROOT)),inventory_sha256=sha(out/'inventory.json'),
        source_hashes=sources,pdk_manifest_sha256=sha(out/'pdk_manifest.json'),ngspice=tool,expected_points=1620,counts=dict(counts),rows=rows,
        worst_absolute_drift=max(unsettled,key=lambda r:abs(r['drift_fraction'])) if unsettled else None,
        scope='Frozen existing records only; missing/writing are not design failures. Settled means only last-5ns drift screen, not PVT/spec qualification. Source current reader returns frequencies for unsettled >=6-edge points; 4/5-edge points are skipped.')
    (out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--campaign',type=Path,required=True);a=p.parse_args();out=ROOT/'results/verification/r6_map_wave_audit'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True);(out/'execution').mkdir();result=audit(a.campaign.resolve(),out);print(out/'summary.json');print(result['counts'])


if __name__=='__main__':main()
