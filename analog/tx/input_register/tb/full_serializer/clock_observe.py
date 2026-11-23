"""Archive ungraded clock-only observations from complete full-TX waveforms.

Requires explicit campaigns. --check validates parameters and metadata only;
it does not read waveform data, create an output directory, or run ngspice.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil

from serdes_flow import project, spice, watch

ROOT=project.ROOT
METRICS=ROOT/'verification/plotting/tx_clock_output_confirmation.py'
spec=importlib.util.spec_from_file_location('tx_clock_output_confirmation',METRICS)
metrics=importlib.util.module_from_spec(spec);spec.loader.exec_module(metrics)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()


def preflight(camps,start,stop):
    if not math.isfinite(start) or not math.isfinite(stop) or start<0 or stop<=start:
        raise ValueError('invalid observation window')
    resolved=[p.resolve() for p in camps]
    if not resolved or len(set(resolved))!=len(resolved):raise ValueError('campaigns must be distinct')
    alive=watch.ngspice_cwds();plans=[]
    for camp in resolved:
        if not camp.is_relative_to(ROOT):raise ValueError('campaign must be inside repository')
        if any(p.is_relative_to(camp) for p in alive):raise ValueError(f'campaign has active ngspice: {camp}')
        plan_path=camp/'plan.json';plan=json.loads(plan_path.read_text())
        if plan.get('mode')!='run' or not math.isclose(plan.get('stop_s',0),120e-9,rel_tol=0,abs_tol=1e-15):
            raise ValueError('requires a full 120 ns dynamic campaign')
        if stop>plan['stop_s']:raise ValueError('observation window exceeds planned stop')
        for rel,expected in plan['snapshot_files'].items():
            if sha(camp/rel)!=expected:raise ValueError(f'checkpoint mismatch: {rel}')
        deck=camp/'execution/physical_tb.cir'
        if sha(deck)!=plan['deck_sha256']:raise ValueError('physical deck hash mismatch')
        if not (camp/'analysis_error.json').is_file():
            raise ValueError(f'missing analysis_error.json: {camp}')
        attempts=[camp/'run']+[d for d in camp.glob('run.r*') if d.name[5:].isdigit()]
        candidates=[]
        for run in attempts:
            if not (run/'execution.json').is_file() or not (run/'tb.cir').is_file():
                continue
            ex=json.loads((run/'execution.json').read_text())
            if (ex.get('exit_code')==0 and not ex.get('timed_out') and not ex.get('log_failures') and
                    ex.get('deck_sha256')==plan['deck_sha256'] and sha(run/'tb.cir')==plan['deck_sha256']):
                candidates.append(run)
        if not candidates:raise ValueError(f'no successful execution with matching deck: {camp}')
        plans.append((camp,plan))
    return plans


def observe(plans,start,stop):
    rows=[]
    for camp,plan in plans:
        raw=spice.case_output(camp,'run','waveforms.raw',plan['stop_s'])
        if raw is None:raise ValueError(f'missing or truncated 120 ns raw: {camp}')
        run=raw.parent;ex_path=run/'execution.json';deck=run/'tb.cir';ex=json.loads(ex_path.read_text())
        if ex.get('exit_code')!=0 or ex.get('timed_out') or ex.get('log_failures') or sha(deck)!=ex.get('deck_sha256') or ex['deck_sha256']!=plan['deck_sha256']:
            raise ValueError(f'waveform execution identity or status invalid: {run}')
        w=spice.Waves(raw)
        if w.t[-1]<plan['stop_s']*(1-1e-6):raise ValueError('waveform did not reach 120 ns')
        error_path=camp/'analysis_error.json'
        rejected=json.loads(error_path.read_text())
        if (ROOT/rejected['waveform']).resolve()!=raw.resolve():
            raise ValueError('analysis rejection belongs to a different waveform attempt')
        rows.append(dict(campaign=str(camp.relative_to(ROOT)),condition=plan['condition'],
            clock_extra_2g=plan.get('clock_extra_2g',1),clock_output_wt=plan.get('clock_output_wt',24),clock_output_r=plan.get('clock_output_r',300),
            raw=str(raw.relative_to(ROOT)),raw_sha256=sha(raw),raw_start_s=float(w.t[0]),raw_end_s=float(w.t[-1]),
            plan_sha256=sha(camp/'plan.json'),execution_sha256=sha(ex_path),deck_sha256=sha(deck),
            analysis_error_text=error_path.read_text(),analysis_error_sha256=sha(error_path),
            clock=metrics.signal_metrics(w,start,stop)))
    return rows


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',type=Path,action='append',required=True)
    p.add_argument('--start-ns',type=float,default=40.);p.add_argument('--stop-ns',type=float,default=100.)
    p.add_argument('--check',action='store_true')
    a=p.parse_args();start=a.start_ns*1e-9;stop=a.stop_ns*1e-9
    plans=preflight(a.campaign,start,stop)
    if a.check:
        print(f'{len(plans)} campaigns passed metadata-only preflight; no waveform read or output written')
        return
    rows=observe(plans,start,stop)
    out=ROOT/'results/analog/tx/clock_only_diagnostic'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    out.mkdir(parents=True,exist_ok=False)
    sources=[Path(__file__).resolve(),METRICS,ROOT/'verification/plotting/tx_parallel_serializer.py']
    sources += [ROOT/'src/serdes_flow'/x for x in ('clock.py','waves.py','spice.py','watch.py','project.py','corners.py','serial.py','mc.py')]
    hashes={}
    for source in sources:
        dest=out/'execution'/source.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest)
        hashes[str(source.relative_to(ROOT))]=sha(dest)
    result=dict(scope='ungraded_clock_observation_not_interface_qualification',
                description='Clock-only observation at explicit absolute times. Original interface analysis rejection is preserved; no serializer scoring or new summary.',
                window_s=[start,stop],analysis_sources=hashes,cases=rows)
    (out/'observation.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(out)


if __name__=='__main__':main()
