"""Independently verify and plot the fixed FS cold W40 readout campaign.

Inputs are explicit immutable analysis summaries. No simulation is launched.
"""
import argparse
import ast
import subprocess
import re
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import boundary, eye, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

RUNNER=ROOT/'analog/rx/sampler/tb/cold_readout_layers/full_transient_dc.py'
DATA=ROOT/'docs/data/rx_cold_readout.json'
CATALOG=ROOT/'results/catalog/rx_cold_readout.json'
FIG=ROOT/'docs/figures/rx/readout/fs_cold_w40_words.png'
SCOPE='FS 1.65 V -40 C hh; full W40 readout, PI20, trim32, rb2k; ideal phase sources, original C2 replay and real bias; soft same-DUT DC hints, no .ic/uic; not full PVT, physical startup or BER.'


def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_runner():
    sys.path.insert(0,str(RUNNER.parent))
    try:
        spec=importlib.util.spec_from_file_location('rx_transient_verifier',RUNNER); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
    finally:
        sys.path.pop(0)


def same(a,b):
    if isinstance(a,dict): return isinstance(b,dict) and a.keys()==b.keys() and all(same(a[k],b[k]) for k in a)
    if isinstance(a,list): return isinstance(b,list) and len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
    if isinstance(a,(float,int)) and not isinstance(a,bool): return isinstance(b,(float,int)) and not isinstance(b,bool) and math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10)
    return a==b


# This exception is limited to read-only republication of this historical run.
# It never changes any simulation runner or its resume checks.
HISTORICAL = {
    'src/serdes_flow/spice.py': ('c4cd1d1c', '7d97d104f9b938f912515862bc03a9a74c84d1b3de2d43039f9ae3b0b7204d2f'),
    'src/serdes_flow/mc.py': ('efb4f28f', '4fdf7f31d1b94e793265e0020cfcae6774247ded55acbf620b38a34006517394'),
}
ALLOWED_SPICE = {'_resolve', 'read_raw', '__init__', 't', '_column', '__getitem__', '__contains__'}


def historical_verify(folder,m):
    plan=json.loads((folder/'plan.json').read_text())
    m.dc.verify(m.SOURCE,registered=True)
    oldplan=m.base.verify(m.short.OLD)
    exceptions={}
    for path,h in plan['sources'].items():
        if sha(path)!=h: raise ValueError(f'source changed: {path}')
    for path,expected in plan['analysis_sources'].items():
        relative=Path(path).resolve().relative_to(ROOT).as_posix()
        actual=sha(path)
        if actual==expected: continue
        if relative not in HISTORICAL: raise ValueError(f'analysis source changed: {path}')
        revision,current=HISTORICAL[relative]
        if actual!=current: raise ValueError(f'unrecognized current SHA: {path}')
        previous=subprocess.check_output(['git','show',f'{revision}:{relative}'],cwd=ROOT)
        if hashlib.sha256(previous).hexdigest()!=expected: raise ValueError(f'historical SHA mismatch: {path}')
        exceptions[relative]={'historical_sha256':expected,'current_sha256':actual,'git_revision':revision}
        if relative.endswith('/spice.py'):
            def components(text):
                tree=ast.parse(text)
                found={n.name:ast.dump(n,include_attributes=False) for n in tree.body
                       if isinstance(n,(ast.FunctionDef,ast.ClassDef)) and n.name in {'Waves','read_raw','_resolve'}}
                if set(found)!={'Waves','read_raw','_resolve'}: raise ValueError('reader AST definitions incomplete')
                return found
            if components(previous.decode())!=components(Path(path).read_text()):
                raise ValueError('historical waveform reader AST mismatch')
            exceptions[relative]['verified_equal_ast']=['Waves','read_raw','_resolve']
    if set(exceptions)!=set(HISTORICAL): raise ValueError('historical exception set changed')
    for path,h in plan['snapshots'].items():
        if sha(folder/path)!=h: raise ValueError(f'snapshot changed: {path}')
    nf=folder/'seed_nodes.json';nodes=m.dc.entries(m.RUN/'op.raw');bc=json.loads((folder/'seed_boundary_proposal.json').read_text())
    if (sha(nf)!=plan['seed_nodes_sha256'] or json.loads(nf.read_text())!=nodes or len(nodes)!=plan['node_count']
        or sha(folder/'seed_boundary_proposal.json')!=plan['proposal_sha256'] or bc!=m.proposal(folder,nf)):
        raise ValueError('seed identity changed')
    for case in m.CASES:
        deck=m.deck_for(folder,oldplan,nodes,case)
        if deck!=(folder/'prepared'/f'{case}.cir').read_text() or re.search(r'^\s*\.ic\b|\buic\b',deck,re.I|re.M):
            raise ValueError('deck changed')
    if boundary.get(m.BC)!=bc: raise ValueError('registered BC differs')
    return plan,nodes,exceptions


class ReadOnlyCallGuard:
    def __init__(self):
        self.calls=set()
    def __call__(self,frame,event,arg):
        if event!='call': return
        filename=frame.f_code.co_filename
        if filename==str(ROOT/'src/serdes_flow/mc.py'):
            raise RuntimeError('MC execution during read-only verification')
        if filename==str(ROOT/'src/serdes_flow/spice.py'):
            name=frame.f_code.co_name
            if name not in ALLOWED_SPICE: raise RuntimeError(f'non-reader SPICE call: {name}')
            self.calls.add(name)


def check_summary(path,case,m,folder,nodes):
    summary=json.loads(path.read_text()); row=summary['result']
    if row['case']!=case or row['status']!='observed' or row['spec_status']!='ungraded': raise ValueError('summary status mismatch')
    run=(ROOT/row['run']).resolve()
    if run.parent!=folder or not run.name.startswith('transient_'+case): raise ValueError('unexpected run')
    ex=json.loads((run/'execution.json').read_text())
    if ex['exit_code']!=0 or ex['timed_out'] or ex['log_failures'] or ex['case']!=case or ex['bc']!=m.base.BC or ex['seed_bc']!=m.BC: raise ValueError('execution mismatch')
    if sha(run/'tb.cir')!=sha(folder/'prepared'/f'{case}.cir') or ex['deck_sha256']!=sha(run/'tb.cir') or sha(run/'execution.json')!=row['execution_sha256'] or sha(run/'wave.raw')!=row['raw_sha256']: raise ValueError('run hashes differ')
    info=m.inspect(run,case,nodes)
    if not same(info,row['stages']) or not info['raw_complete'] or not info['tran_returned'] or not info['raw_written'] or not info['optran_deselected'] or info['any_fallback']: raise ValueError('waveform/stage mismatch')
    if case=='pilot' and not info['health']['numerical_bias_health']: raise ValueError('pilot health mismatch')
    wave=spice.Waves(run/'wave.raw')
    if (len(wave.t)<2 or not np.all(np.isfinite(wave.t)) or np.any(np.diff(wave.t)<=0)
            or any(not np.all(np.isfinite(wave[v])) for v in m.VECTORS)):
        raise ValueError('nonfinite or nonmonotonic waveform')
    return row,run,wave


def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('--pilot-summary',type=Path,required=True); ap.add_argument('--full-summary',type=Path,required=True); a=ap.parse_args()
    pilot=a.pilot_summary.resolve(); full=a.full_summary.resolve()
    folder=full.parent.parent.parent
    if pilot.parent.parent.parent!=folder: raise ValueError('summaries are not from same campaign')
    m=load_runner(); guard=ReadOnlyCallGuard(); sys.setprofile(guard)
    plan,nodes,exceptions=historical_verify(folder,m)
    p,pr,pw=check_summary(pilot,'pilot',m,folder,nodes); f,fr,w=check_summary(full,'full',m,folder,nodes)
    mod=m.load_analysis(); boundary.check_load(m.base.BC,mod.sp.replay.signature())
    bits=eye.prbs7(mod.sp.link.NBITS); actual=mod.analyse(fr/'wave.raw',Condition('fs',1.65,-40),20,bits)
    if not same(actual,f['readout_analysis']): raise ValueError('independent analysis differs from summary')
    t_from=mod.sp.link.T0+(mod.sp.link.WARM+6)*mod.sp.link.UI
    if not same([t_from,44.75e-9],f['analysis_window_s']): raise ValueError('window mismatch')
    sel=w.t>=t_from; t=w.t[sel]; vdd=float(np.mean(w['v(vdd)'][sel])); et,pol=crossings(t,w['v(w)'][sel],level=vdd/2); wr=et[pol>0]
    start=actual['start']; first=mod.sp.link.WARM-8
    usable=[i for i in range(len(wr)) if start+16*i>=first and start+16*i+20<len(bits)]
    if len(usable)!=actual['words']: raise ValueError('usable word selection differs')
    word_edges=[float(x*1e9) for x in wr]; usable_times=[word_edges[i] for i in usable]
    sys.setprofile(None)
    data=dict(scope=SCOPE,campaign=str(folder.relative_to(ROOT)),pilot_summary=str(pilot.relative_to(ROOT)),full_summary=str(full.relative_to(ROOT)),
       measurement_window_ns=[t_from*1e9,44.75],word_rising_edges_ns=word_edges,word_edge_count=len(wr),usable_edge_indices=usable,usable_word_times_ns=usable_times,
       offset_start_bit=start,offset_rule='readout_deser.word_check minimizes contract mapping errors over candidate PRBS start offsets and requires >=4 usable words',
       usable_words=actual['words'],data_bits=16*actual['words'],data_errors=actual['data_errors'],edge_determinate=actual['edge_determinate'],edge_errors=actual['edge_errors'],
       contract_map_ok=actual['map_ok'],single_lane_ambiguities={k:v for k,v in actual['derived'].items() if len(v)!=1},analysis=actual,
       provenance={'runner':str(RUNNER.relative_to(ROOT)),'runner_sha256':sha(RUNNER),'pilot_summary_sha256':sha(pilot),'full_summary_sha256':sha(full),
                   'pilot_raw_sha256':sha(pr/'wave.raw'),'full_raw_sha256':sha(fr/'wave.raw'),'collector_sha256':sha(__file__),
                   'seed_bc':m.BC,'replay_bc':m.base.BC,'plan_sha256':sha(folder/'plan.json'),
                   'historical_read_only_verification':{'exceptions':exceptions,'profile_guard':'mc.py calls forbidden; spice.py reader-only calls allowed',
                       'observed_spice_calls':sorted(guard.calls),'mc_calls':0}})
    fig,ax=plt.subplots(3,1,figsize=(12,7),sharex=True,layout='constrained')
    ns=w.t*1e9
    ax[0].plot(ns,w['v(rxp)']-w['v(rxn)'],lw=.8,color='#235789'); ax[0].set_ylabel('C2 input\nΔV (V)')
    ax[1].plot(ns,w['v(xro.ckq)'],lw=.6,label='ckq'); ax[1].plot(ns,w['v(w)'],lw=1,label='word clock'); ax[1].legend(loc='upper right',ncol=2,fontsize=8); ax[1].set_ylabel('Clock (V)')
    for j,name in enumerate(('a0_0','b0_2','a1_0','b1_0')):
        ax[2].plot(ns,w[f'v({name})']/1.65+j*1.4,lw=.8,label=name)
    ax[2].set_yticks([0,1.4,2.8,4.2],['a0_0','b0_2','a1_0','b1_0']); ax[2].set_ylabel('Word outputs\n(offset)'); ax[2].set_xlabel('Time (ns)')
    for panel in ax:
        panel.axvspan(0,t_from*1e9,color='0.92',zorder=-5)
        for x in word_edges: panel.axvline(x,color='#b8bdc5',lw=.45)
        for x in usable_times: panel.axvline(x,color='#c33c54',lw=.85,alpha=.8)
        panel.grid(alpha=.2); panel.set_xlim(0,44.75)
    fig.suptitle('FS cold W40 readout: six usable words, 96 data bits, zero errors\nGray: before 12.5 ns; red: usable word edges; b0_2 and a1_0 have two individual fits',fontsize=11)
    FIG.parent.mkdir(parents=True,exist_ok=True); fig.savefig(FIG,dpi=160); plt.close(fig)
    DATA.parent.mkdir(parents=True,exist_ok=True); DATA.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    CATALOG.parent.mkdir(parents=True,exist_ok=True); CATALOG.write_text(json.dumps(dict(campaign=str(folder.relative_to(ROOT)),pilot_summary=str(pilot.relative_to(ROOT)),full_summary=str(full.relative_to(ROOT)),data=str(DATA.relative_to(ROOT)),data_sha256=sha(DATA),figure=str(FIG.relative_to(ROOT)),figure_sha256=sha(FIG),scope=SCOPE),indent=2)+'\n')
    print(json.dumps(dict(word_edges=len(wr),usable=usable,usable_times_ns=usable_times,data_errors=actual['data_errors'],edge_errors=actual['edge_errors'],ambiguities=data['single_lane_ambiguities']),indent=2))


if __name__=='__main__': main()
