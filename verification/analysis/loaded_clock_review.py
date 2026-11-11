"""Independent event-coverage/absolute-edge review of loaded-clock card raws."""
import argparse
from datetime import datetime,timezone
import importlib.util
from pathlib import Path
import shutil
import uuid

import numpy as np

from serdes_flow import clock,clock_transfer,project,spice,stage_metrics

ROOT=project.ROOT
HERE=Path(__file__).resolve()
RUNNER=ROOT/'analog/tx/input_register/tb/loaded_clock_card/run.py'
spec=importlib.util.spec_from_file_location('loaded_review_card',RUNNER)
card=importlib.util.module_from_spec(spec);spec.loader.exec_module(card)


def review(summary):
    camp=summary.parents[2];plan,entry=card.check(camp,registered=True);original=card.read(summary)
    if original['status'] not in ('baselines_validated_DOE_pending','loaded_transfer_DOE_measured_no_adoption'):
        raise ValueError('incomplete source analysis')
    if original['plan_sha256']!=card.sha(camp/'plan.json'):raise ValueError('plan changed')
    keys={(r['condition'],r['point']) for r in original['rows']}
    expected={(tag,p['id']) for tag in plan['conditions'] for p in card.POINTS}
    if original['status']=='baselines_validated_DOE_pending':expected={(tag,'baseline') for tag in plan['conditions']}
    if keys!=expected or len(keys)!=len(original['rows']):raise ValueError('missing/duplicate loaded-clock cases')
    result=dict(status='strict_review_complete',campaign=str(camp.relative_to(ROOT)),source_summary=str(summary.relative_to(ROOT)),
                source_summary_sha256=card.sha(summary),plan_sha256=card.sha(camp/'plan.json'),rows=[],
                source_sha256={str(p.relative_to(ROOT)):card.sha(p) for p in (HERE,RUNNER,Path(clock_transfer.__file__),Path(stage_metrics.__file__))},
                scope='Prescribed-voltage local loaded clock, explicit guaranteed input-event window. No full eye, pad, upstream impedance or adoption qualification.')
    start,stop=plan['evaluation_window_s'];max_delay=200e-12
    for row in original['rows']:
        tag,name=row['condition'],row['point'];raw=card.completed(camp,tag,name,plan)
        if raw is None or str(raw.relative_to(ROOT))!=row['raw']:raise ValueError('missing/wrong completed raw')
        for path,value in row['evidence'].items():
            if card.sha(ROOT/path)!=value:raise ValueError('evidence changed')
        recomputed=card.measure(camp,tag,name,raw,plan)
        if not card.collector.equal(recomputed,row['result']):raise ValueError('recorded telemetry differs from raw')
        w=spice.Waves(raw);measured=dict(condition=tag,point=name,raw=row['raw'],raw_sha256=card.sha(raw),
                                      baseline_fidelity=recomputed['baseline_fidelity'],branches=[])
        result['rows'].append(measured)
        if name=='baseline':
            with np.load(camp/'inputs'/f'{tag}.npz') as data:
                edge_errors={}
                for node,p,n in (('e3','e3p','e3n'),('e4','e4p','e4n'),('c2g','sp','sn')):
                    errors=[]
                    for polarity in (-1,1):
                        ref=clock.edges(data['t'],data['ref_'+p]-data['ref_'+n],polarity,start,stop)
                        actual=clock.edges(w.t,w[p+'1']-w[n+'1'],polarity,start,stop)
                        if len(ref)!=len(actual) or not len(ref):raise ValueError('baseline absolute event count differs')
                        for event in ref:
                            hits=actual[np.abs(actual-event)<125e-12]
                            if len(hits)!=1:raise ValueError('ambiguous baseline edge identity')
                            errors.append(float(hits[0]-event))
                    edge_errors[node]=max(map(abs,errors))
                if max(edge_errors.values())>2e-12:raise ValueError('e3/e4/c2g absolute edge calibration failed')
                measured['baseline_absolute_edge_errors_s']=edge_errors
            if not recomputed['baseline_fidelity']['passed']:raise ValueError('baseline voltage calibration failed')
        for i,b in enumerate(recomputed['branches'],1):
            branch={**b,'complete_clock_check':{}};measured['branches'].append(branch)
            paths=[('input_to_e3','ip','inn',f'e3p{i}',f'e3n{i}'),
                   ('e3_to_e4',f'e3p{i}',f'e3n{i}',f'e4p{i}',f'e4n{i}'),
                   ('e4_to_c2g',f'e4p{i}',f'e4n{i}',f'sp{i}',f'sn{i}'),
                   ('input_to_c2g','ip','inn',f'sp{i}',f'sn{i}')]
            for label,ap,an,bp,bn in paths:
                try:
                    branch['complete_clock_check'][label]=clock_transfer.analyze(w.t,w[ap]-w[an],w[bp]-w[bn],start,stop-max_delay,max_delay,minimum_pp_v=.15)
                except ValueError as exc:
                    branch['complete_clock_check'][label]=dict(edges_complete=False,clock_qualified=False,error=str(exc))
            branch['clock_floor_and_events_pass']=all(r['clock_qualified'] for r in branch['complete_clock_check'].values())
            if name=='baseline' and b['mode']=='generic' and not branch['clock_floor_and_events_pass']:
                raise ValueError('generic baseline strict clock transfer failed')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--summary',type=Path,required=True);a=p.parse_args()
    result=review(a.summary.resolve());camp=ROOT/result['campaign']
    archive=camp/'review'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);archive.mkdir(parents=True,exist_ok=False)
    for path in result['source_sha256']:
        dest=archive/'execution'/path;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/path,dest)
    card.dump(archive/'summary.json',result);print(archive/'summary.json')
    for row in result['rows']:
        print(row['condition'],row['point'],row.get('baseline_absolute_edge_errors_s'),[(b['mode'],b['clock_floor_and_events_pass']) for b in row['branches']])


if __name__=='__main__':main()
