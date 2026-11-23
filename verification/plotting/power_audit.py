#!/usr/bin/env python3
"""Verify representative archived waveforms and plot the offline power audit."""
import hashlib
import json
import re
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/work_packages/deliveries/POWER-20261110/evidence.json'

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def check(row, expected_end):
    raw, deck = ROOT / row['raw'], ROOT / row['deck']
    ex_path = deck.parent / 'execution.json'
    ex = json.loads(ex_path.read_text())
    with raw.open('rb') as f:
        header = b''
        while not header.endswith(b'Binary:\n'):
            line = f.readline()
            if not line:
                raise ValueError('Binary header missing')
            header += line
        offset = f.tell()
    text = header.decode()
    n = int(re.search(r'No. Variables: (\d+)', text)[1])
    points = int(re.search(r'No. Points: (\d+)', text)[1])
    if raw.stat().st_size != offset + points * n * 8:
        raise ValueError('Raw size mismatch')
    wave = np.memmap(raw, mode='r', dtype='<f8', offset=offset, shape=(points, n))
    end = float(wave[-1, 0])
    result = {'raw':row['raw'], 'raw_sha256':sha(raw), 'raw_matches_evidence':sha(raw)==row['raw_sha256'],
              'deck':row['deck'], 'deck_sha256':sha(deck), 'deck_matches_evidence':sha(deck)==row['deck_sha256'],
              'execution':str(ex_path.relative_to(ROOT)), 'execution_sha256':sha(ex_path),
              'execution_deck_sha256_matches':sha(deck)==ex['deck_sha256'], 'exit_code':ex['exit_code'],
              'timed_out':ex['timed_out'], 'log_failures':ex['log_failures'], 'raw_points':points,
              'raw_final_time_s':end, 'expected_t_end_s':expected_end, 'complete_t_end':end >= expected_end*(1-1e-9)}
    assert result['raw_matches_evidence'] and result['deck_matches_evidence'] and result['execution_deck_sha256_matches']
    assert ex['exit_code']==0 and not ex['timed_out'] and not ex['log_failures'] and result['complete_t_end']
    return result

def main():
    e=json.loads(EVIDENCE.read_text())
    data={'source_evidence':str(EVIDENCE.relative_to(ROOT)), 'source_evidence_sha256':sha(EVIDENCE),
          'tx':e['tx'], 'rx_current':e['rx'], 'rx_historical_45':e['rx_historical_45'],
          'ldo_nominal_estimate_ma':{'VCO':3.4, 'four_first_buffers':2.04, 'CP_follower_approx':0.3},
          'representative_checks':{'tx_tt':check(e['tx']['tt_v1800_t27'],120e-9), 'rx_fs_cold':check(e['rx'],44.75e-9)},
          'scope':'TX bench Vdd only; RX bench Vdd only; LDO values are nominal sizing estimates, not simulated PVT limits or whole-SerDes power.'}
    (ROOT/'docs/data/power_audit.json').write_text(json.dumps(data,indent=2,ensure_ascii=False)+'\n')
    fig,(ax,bx)=plt.subplots(1,2,figsize=(11,4.2),layout='constrained',gridspec_kw={'width_ratios':[1.65,1]})
    colors={'tt':'#176c8c','ss':'#7b5595','ff':'#d27732','sf':'#cf4951','fs':'#388c70'}
    for j,corner in enumerate(colors):
        subset=[(k,v) for k,v in e['tx'].items() if k.startswith(corner+'_')]
        for k,v in subset:
            voltage=int(re.search(r'_v(\d+)',k)[1])/1000
            temp=int(re.search(r'_t(-?\d+)',k)[1]); dx={-40:-.19,27:0,85:.19}[temp]
            ax.scatter(j+dx,v['mean_power_mw'],c=colors[corner],marker={1.65:'o',1.8:'s',1.95:'^'}[voltage],s=40,alpha=.85)
    ax.set_xticks(range(5),['TT','SS','FF','SF','FS']); ax.set_ylabel('Vdd supply power (mW)'); ax.set_title('TX: 45 MOS conditions, 24–100 ns')
    for marker,label in [('o','1.65 V'),('s','1.80 V'),('^','1.95 V')]: ax.scatter([],[],c='#666',marker=marker,label=label)
    ax.legend(frameon=False,fontsize=8,title='Voltage'); ax.grid(axis='y',alpha=.2)
    labels=['VCO','4 buffers','CP + follower']; vals=[3.4,2.04,.3]
    bx.barh(labels,vals,color=['#176c8c','#388c70','#d27732']); bx.invert_yaxis(); bx.set_xlabel('Nominal current estimate (mA)'); bx.set_title('Proposed LDO loads: sizing estimate')
    for j,x in enumerate(vals): bx.text(x+.04,j,f'{x:.2f}',va='center',fontsize=9)
    bx.set_xlim(0,4.1); bx.grid(axis='x',alpha=.2)
    fig.suptitle('Bench measurements and nominal estimates; not total SerDes power',fontsize=11)
    fig.savefig(ROOT/'docs/figures/system/power_audit.png',dpi=180); plt.close(fig)
    print(json.dumps(data['representative_checks'],indent=2))

if __name__ == '__main__': main()
