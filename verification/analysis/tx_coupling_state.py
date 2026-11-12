"""Inspect charge-state history in the existing TX 45-condition waveforms.

No simulator, prior-result mutation or inference of microsecond steady state.
"""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import uuid

import numpy as np
from serdes_flow import project, spice, stage_metrics, waves

ROOT = project.ROOT
HERE = Path(__file__).resolve()
PRIOR = ROOT/'results/analysis/tx_termination_current/20261111T181313.220139Z_6f967973/summary.json'
COLLECTOR = ROOT/'verification/plotting/tx_parallel_serializer.py'
DEST = ROOT/'results/analysis/tx_coupling_state'
WINDOWS = [('early',10e-9,20e-9),('middle',50e-9,60e-9),('late',100e-9,110e-9)]
LOAD = ['Clpp lqp 0 200f','Clpn lqn 0 200f', 'Rlpp lqp llp .3','Rlpn lqn lln .3',
        'Llpp llp lap .5n','Llpn lln lan .5n','Clacp lap ltp 10n','Clacn lan ltn 10n',
        'Xchannel ltp ltn lxp lxn 0 serdes_diff_rlc16','Rlc0 lxp lrp .01','Rlc1 lxn lrn .01',
        'Clc0 lrp 0 100f','Clc1 lrn 0 100f','Vlcm lcm 0 .9','Rlterm0 lrp lcm 50','Rlterm1 lrn lcm 50']


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def mean(t,y,start,stop):
    return stage_metrics.telemetry(t,y,start,stop)['mean']


def integral(t,y,start,stop):
    tw,yw=stage_metrics.window(t,y,start,stop)
    return float(waves.time_average(yw,tw)*(stop-start))


def main():
    prior=json.loads(PRIOR.read_text())
    if len(prior['rows'])!=45 or prior['source_sha256']!=sha(ROOT/prior['source']):
        raise ValueError('prior source identity or coverage differs')
    spec=importlib.util.spec_from_file_location('coupling_collector',COLLECTOR)
    collector=importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
    result=dict(status='finite_record_coupling_state_no_steady_state_qualification', prior_summary=str(PRIOR.relative_to(ROOT)),prior_summary_sha256=sha(PRIOR),
        windows=[dict(name=n,start_s=a,stop_s=b) for n,a,b in WINDOWS],rows=[],
        sign_conventions='Iremote=(Vlrp+Vlrn−1.8V)/50Ω, positive from remote nodes into 0.9V VCM; Ilocal=sum((VDD−Vpad)/R). Estimated Itail=Ilocal−Iremote; pad/channel stored-charge derivatives and other paths are omitted.',
        limitations=['10nF caps and RLC initial state may retain long charge history; no microsecond steady-state claim or old 45-point failure assertion.',
        'Generic50 linear-R extrapolation below 0.1V and reverse bias follows prior planning estimate; actual local capacitive currents omitted.',
        'Integral Iremote is charge into the remote VCM resistors in the recorded interval; it is not measured capacitor charge or individual capacitor voltage.',
        'Current imbalance includes pad and channel storage; estimated tail is not measured transistor current.',
        'Time weighted waveform averages, not independent statistical samples.'])
    for old in prior['rows']:
        camp=ROOT/old['campaign']; raw=ROOT/old['raw']
        if sha(raw)!=old['raw_sha256'] or sha(camp/'plan.json')!=old['plan_sha256'] or sha(camp/'summary.json')!=old['summary_sha256']:
            raise ValueError('source identity changed')
        case=collector.collect(camp)
        if case['waveform']!=old['raw'] or case['hashes']!=old['collector_hashes']:
            raise ValueError('collector source changed')
        deck=camp/'execution/physical_tb.cir';text=deck.read_text();lines=text.splitlines()
        if sha(deck)!=old['deck_sha256'] or any(lines.count(x)!=1 for x in LOAD):raise ValueError('unexpected direct load')
        plan=json.loads((camp/'plan.json').read_text());vdd=float(plan['condition'].split('_v')[1].split('_')[0])/1000
        expected=f'Vtxen tx_en 0 PWL(0 0 4n 0 4.1n {vdd:g})'
        if lines.count(expected)!=1:raise ValueError('enable stimulus changed: '+expected)
        w=spice.Waves(raw);t=w.t;loc=(w['lqp']+w['lqn'])/2;rem=(w['lrp']+w['lrn'])/2
        remote=(w['lrp']+w['lrn']-1.8)/50; ilp=(w['vdd']-w['lqp'])/old['resistance_ohm'];iln=(w['vdd']-w['lqn'])/old['resistance_ohm'];local=ilp+iln;tail=local-remote
        r=dict(condition=old['condition'],raw=old['raw'],raw_sha256=old['raw_sha256'],source_hashes=case['hashes'],deck_sha256=old['deck_sha256'],
               enable_line=expected,load_lines=LOAD,resistance_ohm=old['resistance_ohm'],record_s=[float(t[0]),float(t[-1])],windows=[])
        for name,a,b in WINDOWS:
            r['windows'].append(dict(name=name,start_s=a,stop_s=b,local_cm_v=mean(t,loc,a,b),remote_cm_v=mean(t,rem,a,b),
                local_p_current_a=mean(t,ilp,a,b),local_n_current_a=mean(t,iln,a,b),local_total_current_a=mean(t,local,a,b),
                remote_vcm_current_a=mean(t,remote,a,b),remote_net_charge_c=integral(t,remote,a,b),
                estimated_tail_current_a=mean(t,tail,a,b)))
        a=float(t[0]);b=float(t[-1]);r['entire_record_remote_net_charge_c']=integral(t,remote,a,b)
        r['late_minus_early']={k:r['windows'][-1][k]-r['windows'][0][k] for k in ('local_cm_v','remote_cm_v','remote_vcm_current_a','local_total_current_a','estimated_tail_current_a')}
        result['rows'].append(r);print(old['condition'],flush=True)
    if len({r['condition'] for r in result['rows']})!=45:raise ValueError('condition coverage failure')
    result['sources_sha256']={str(p.relative_to(ROOT)):sha(p) for p in (HERE,COLLECTOR,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/stage_metrics.py',ROOT/'src/serdes_flow/waves.py')}
    out=DEST/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);out.mkdir(parents=True)
    shutil.copyfile(HERE,out/HERE.name);(out/'summary.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print('RESULT',out,flush=True)


if __name__=='__main__':main()
