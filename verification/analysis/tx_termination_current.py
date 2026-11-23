"""Offline full-record generic-termination current planning, no simulation."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import uuid

import numpy as np
from serdes_flow import project, spice, stage_metrics, waves
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve()
SOURCE = ROOT/'docs/data/tx_full_pvt45.json'
COLLECTOR = ROOT/'verification/plotting/tx_parallel_serializer.py'
CARD = ROOT/'results/analog/common/devices/fixed_load_card/20261111T133044.144773Z_20c38295'
CARD_SUMMARY = CARD/'analysis/measurement/summary.json'
OUTPUT = ROOT/'results/analysis/tx_termination_current'
RULE_URL = 'https://github.com/google/skywater-pdk/blob/main/docs/rules/device-details/res_high/index.rst'
RP = 'XRp vdd_out qp 0 sky130_fd_pr__res_high_po w={max(1,ceil(1012/(rterm)))} l={((rterm)*max(1,ceil(1012/(rterm)))-378)/317}'
RN = RP.replace('XRp vdd_out qp', 'XRn vdd_out qn')


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def read(p): return json.loads(p.read_text())


def main():
    spec=importlib.util.spec_from_file_location('tx_term_collector',COLLECTOR)
    collector=importlib.util.module_from_spec(spec); spec.loader.exec_module(collector)
    card=read(CARD_SUMMARY); cardplan=read(CARD/'plan.json')
    if card['plan_sha256'] != sha(CARD/'plan.json'): raise ValueError('passive plan mismatch')
    for path,expected in cardplan['pdk_identity'].items():
        if sha(Path(path)) != expected: raise ValueError('passive PDK identity changed: '+path)
    for path,expected in card['evidence'].items():
        p=ROOT/path
        if not p.exists(): p=CARD/path
        if sha(p)!=expected: raise ValueError('passive evidence mismatch: '+path)
    part=next(x for x in cardplan['calibration_parts'] if x['id']=='generic50')
    if (part['w_um'],part['length_um']) != (21,(50*21-378)/317): raise ValueError('generic mapping differs')
    resistance={}; checks={}
    for temp in (-40,27,85):
        rr=[r for r in card['rows'] if r['id']=='generic50' and r['corner']=='tt' and r['temp_c']==temp]
        if sorted(r['drop_v'] for r in rr)!=[.1,.25,.5]:raise ValueError('missing passive measurements')
        vals=np.array([r['resistance_ohm'] for r in rr]); inc=np.array([r['incremental_resistance_ohm'] for r in rr])
        relative=float(max(np.max(abs(vals/vals[0]-1)),np.max(abs(inc/vals-1))))
        if relative>1e-8: raise ValueError('generic resistance not linear in tested range')
        resistance[temp]=float(vals[1]);checks[str(temp)]=dict(samples=rr,max_relative_nonconstant_or_incremental_error=relative)
    src=read(SOURCE)
    if src['campaign']!='results/analog/tx/full_pvt45/20261107T200334Z' or src['clock']!=[5,16,240] or src['driver_params']!='rpre=120 wout=192 wtpre=60' or len(src['rows'])!=45:
        raise ValueError('wrong TX source')
    out=dict(status='planning_estimate_not_EM_or_fixed_resistor_qualification', method='I=(VDD−pad)/R_generic50(T), P=(VDD−pad)^2/R. Each mean and RMS time weighted over the complete saved raw interval; peak is sampled max |I|. Includes idle and payload, not startup before first saved sample. PDK parasitic displacement currents excluded.',
             source=str(SOURCE.relative_to(ROOT)),source_sha256=sha(SOURCE),passive_summary=str(CARD_SUMMARY.relative_to(ROOT)),passive_summary_sha256=sha(CARD_SUMMARY),passive_plan_sha256=sha(CARD/'plan.json'),
             generic_mapping=part,passive_checks=checks, rows=[],rules=dict(url=RULE_URL,model_validity_uA_per_um=500,preferred_uA_per_um=100,width_um=2.85,
             limitation='Model validity and preferred use are not EM, thermal, layout, mismatch or reliability signoff. Parallel equal current sharing is assumed; altered fixed R network may change waveforms and has not been simulated.'),
             analysis_sources_sha256={str(p.relative_to(ROOT)):sha(p) for p in [HERE,COLLECTOR,ROOT/'src/serdes_flow/spice.py',ROOT/'src/serdes_flow/waves.py',ROOT/'src/serdes_flow/stage_metrics.py',ROOT/'src/serdes_flow/corners.py']})
    for row in src['rows']:
        if row['status']!='done' or not row['grade']['gates_pass']:raise ValueError('source qualification missing')
        camp=ROOT/row['run'];summary=camp/'summary.json'
        if sha(summary)!=row['summary_sha256']:raise ValueError('summary hash differs')
        case=collector.collect(camp); plan=read(camp/'plan.json'); cond=Condition.parse(row['condition'])
        if plan['pdk_installation_id'] != project.pdk_installation_id(): raise ValueError('source PDK installation differs')
        if case['condition']!=row['condition'] or plan['driver_params']!=src['driver_params'] or not case['counter']['counting'] or not all(case[k] for k in ('input_boundary_ok','halfword_hold_ok','behavioral_tags_align')) or not case['outputs']['serializer']['mapping']['in_order']:
            raise ValueError('condition or functional identity failed')
        deck=(camp/'execution/physical_tb.cir').read_text(); driver=camp/'snap/run/pdk_resistors/analog/tx/output_driver/spice/cml_line_driver_lowvt_enable.spice'
        lines=driver.read_text().splitlines()
        instance = [l for l in deck.splitlines() if l.startswith('Xdriver qp qn tx_en lqp lqn vbias vdd vdd 0 ')]
        if RP not in lines or RN not in lines or 'rterm=50' not in driver.read_text() or len(instance)!=1 or 'rpre=120 wout=192 wtpre=60' not in instance[0] or 'rterm=' in instance[0]:raise ValueError('source termination or driver differs')
        raw=ROOT/case['waveform']; w=spice.Waves(raw); t=w.t; start=float(t[0]);stop=float(t[-1]); r=resistance[cond.temp]
        drop=[w['vdd']-w[n] for n in ('lqp','lqn')]; rr=dict(condition=row['condition'],campaign=row['run'],raw=case['waveform'],raw_sha256=sha(raw),plan_sha256=sha(camp/'plan.json'),summary_sha256=sha(summary),driver_snapshot_sha256=sha(driver),deck_sha256=sha(camp/'execution/physical_tb.cir'),collector_hashes=case['hashes'],resistance_ohm=r,window_s=[start,stop],branches=[])
        for node,v in zip(('lqp','lqn'),drop):
            if not np.all(np.isfinite(v)):raise ValueError('nonfinite pad drop')
            current=v/r;power=v*v/r; peak=float(np.max(np.abs(current)))
            rr['branches'].append(dict(node=node,drop_v=stage_metrics.telemetry(t,v,start,stop),current_mean_a=float(waves.time_average(current,t)),current_rms_a=float(np.sqrt(waves.time_average(current*current,t))),current_peak_abs_a=peak,
                power_mean_w=float(waves.time_average(power,t)), extrapolates_below_0_1_v=bool(np.min(v)<.1),extrapolates_above_0_5_v=bool(np.max(v)>.5),
                hypothetical_fixed_2p85_equal_share={str(n):dict(peak_uA_per_um=peak*1e6/(n*2.85)) for n in (5,6,8)},
                hypothetical_minimum_count_model=math.ceil(peak*1e6/(500*2.85)),hypothetical_minimum_count_preferred=math.ceil(peak*1e6/(100*2.85))))
        rr['combined_mean_power_w']=sum(b['power_mean_w'] for b in rr['branches']); out['rows'].append(rr)
        print(row['condition'], flush=True)
    if len({x['condition'] for x in out['rows']})!=45:raise ValueError('PVT grid incomplete')
    for field in ('current_peak_abs_a','current_rms_a','power_mean_w'):
        pairs=[(b[field],r['condition'],b['node']) for r in out['rows'] for b in r['branches']];value,condition,node=max(pairs);out.setdefault('extrema',{})[field]=dict(value=value,condition=condition,node=node)
    out['extrema']['maximum_combined_mean_power_w']=max((r['combined_mean_power_w'] for r in out['rows']))
    out['extrapolated_branch_counts']={k:sum(b[k] for r in out['rows'] for b in r['branches']) for k in ('extrapolates_below_0_1_v','extrapolates_above_0_5_v')}
    dest=OUTPUT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);dest.mkdir(parents=True)
    shutil.copyfile(HERE,dest/HERE.name);(dest/'summary.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n');print('RESULT',dest,flush=True)


if __name__=='__main__':main()
