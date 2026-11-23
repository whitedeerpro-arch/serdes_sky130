"""Frozen candidate MC using the established LDO calibration/replay analysis.

The delivered70pF mismatch runner stays unchanged; this adds explicit candidate
selection, including the two-layer MIM model. Never reuse nominal reduced libs.
"""
import argparse
from datetime import datetime,timezone
import importlib.util
import json
from pathlib import Path
import shutil

from serdes_flow import mc,project,watch

SELF=Path(__file__).resolve();ROOT=project.ROOT
sp=importlib.util.spec_from_file_location('ldo_candidate_mc_parent',SELF.with_name('mismatch.py'))
base=importlib.util.module_from_spec(sp);sp.loader.exec_module(base)
caps=base.caps


def prepare(name,samples,chunk,seed,profiles):
    v=next(v for v in caps.VARIANTS if v['name']==name)
    camp=ROOT/'results/analog/ldo/candidate_mismatch'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    (camp/'cells').mkdir(parents=True);(camp/'prepared').mkdir()
    for fn,text in caps.cell_sources(v).items():(camp/'cells'/fn).write_text(text)
    for src in [SELF,base.SELF,caps.SELF,caps.r4.SELF,*[ROOT/f'src/serdes_flow/{n}.py' for n in ('mc','spice','feedback','project','watch')]]:
        dst=camp/'source'/src.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    entries=[]
    for profile in profiles:
        for kind in ('nominal','repro','mc'):
            chunks=([(0,seed,1)] if kind=='nominal' else [(0,seed*1000,1)] if kind=='repro' else mc.chunks(samples,seed,per=chunk))
            for k,s,n in chunks:
                tag=f'{profile}_{kind}_{k:03d}';deck=camp/'prepared'/(tag+'.cir')
                deck.write_text(base.deck(profile,n,s,kind!='nominal'))
                entries.append(dict(name=tag,profile=profile,kind=kind,seed=s,samples=n,deck=str(deck.relative_to(camp))))
    plan=dict(samples=samples,chunk=chunk,seed=seed,profiles=profiles,entries=entries,variant=v,
              pdk=caps.r4.reg.pdk_identity(),gates=caps.GATES,
              sha256={str(p.relative_to(camp)):caps.sha(p) for p in camp.rglob('*') if p.is_file()},
              scope=f'{name}: conditional schematic local mismatch pilot; per-chip64-code calibration then held; full PDK; no PNP/direct g5 Vth/statistical global process/full PVT/PEX/startup/PLL qualification')
    (camp/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');return camp


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);g=ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--prepare',action='store_true');g.add_argument('--resume',type=Path);g.add_argument('--analyse',type=Path)
    ap.add_argument('--variant',default='stack_core70');ap.add_argument('--samples',type=int,default=8)
    ap.add_argument('--chunk',type=int,default=4);ap.add_argument('--seed',type=int,default=71)
    ap.add_argument('--profiles',nargs='+',choices=base.PROFILES,default=['fs','tt'])
    ap.add_argument('--workers',type=int,choices=(1,2),default=2);a=ap.parse_args()
    if a.prepare:print(prepare(a.variant,a.samples,a.chunk,a.seed,a.profiles))
    elif a.resume:
        camp=a.resume.resolve();_,jobs=base.jobs(camp)
        if len(watch.ngspice_cwds())+a.workers>4:raise ValueError('Global ngspice slots occupied')
        mc.run_many(jobs,workers=a.workers);base.analyse(camp)
    else:base.analyse(a.analyse.resolve())
