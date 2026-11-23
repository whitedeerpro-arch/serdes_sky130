"""Count bounded PWL knots for existing demand-card inputs; never simulate."""
import hashlib
import json
from pathlib import Path

import numpy as np
from serdes_flow import project, waves

ROOT = project.ROOT
CAMPAIGN = ROOT / 'results/analog/tx/retime_demand/20261111T065010.025374Z_05fb2e30'
OUTPUT = ROOT / 'docs/data/tx_retime_pwl_cost.json'
VSRC = Path('/home/host/.local/share/simple_serdes_build/ngspice47/ngspice-47/src/spicelib/devices/vsrc/vsrcload.c')
NODES = ('ap', 'an', 'bp', 'bn', 'sp', 'sn', 'vbias', 'vbias_logic', 'vdd')
TOLERANCES = (1e-5, 5e-5, 1e-4)


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def main():
    plan = json.loads((CAMPAIGN / 'plan.json').read_text())
    proposal = json.loads((CAMPAIGN / 'boundary_proposal.json').read_text())
    identity = hashlib.sha256(json.dumps(proposal, sort_keys=True).encode()).hexdigest()
    if identity != plan['boundary_sha256']:
        raise ValueError('boundary changed')
    if set(plan['conditions']) != {'fs_v1650_t85', 'ss_v1650_t-40'}:
        raise ValueError('unexpected conditions')
    binary = Path(project.ngspice())
    if sha(binary) != plan['ngspice_sha256']:
        raise ValueError('configured binary changed')
    cases = []
    for tag in plan['conditions']:
        rel = f'inputs/{tag}.npz'
        path = CAMPAIGN / rel
        if sha(path) != plan['snapshots'][rel]:
            raise ValueError('input snapshot changed: '+tag)
        with np.load(path) as d:
            t = d['t'].copy()
            for tol in TOLERANCES:
                rows = []
                for name in NODES:
                    y = d[name]
                    ts, ys = waves.shift_pwl(t, y, 0., tolerance_v=tol, time_quantum_s=1e-16)
                    err = float(np.max(np.abs(np.interp(t, ts, ys) - y)))
                    if err > tol * (1+1e-9):
                        raise ValueError('original vertex reconstruction exceeds tolerance')
                    rows.append({'source':name, 'knots':len(ts), 'max_original_vertex_error_v':err})
                    print(tag, tol, name, len(ts), f'{err:.3g}', flush=True)
                cases.append({'condition':tag, 'tolerance_v':tol, 'original_vertices':len(t),
                              'nodes':rows, 'total_knots':sum(x['knots'] for x in rows),
                              'max_original_vertex_error_v':max(x['max_original_vertex_error_v'] for x in rows)})
    data = {'scope':'Offline PWL simplification counts and reconstruction error, no ngspice or transient timing benchmark.',
            'campaign':str(CAMPAIGN.relative_to(ROOT)), 'plan_sha256':sha(CAMPAIGN/'plan.json'),
            'boundary_sha256':identity, 'input_sha256':{tag:sha(CAMPAIGN/f'inputs/{tag}.npz') for tag in plan['conditions']},
            'analysis_sha256':sha(Path(__file__).resolve()), 'waves_sha256':sha(ROOT/'src/serdes_flow/waves.py'),
            'method':'Nine original input sources; zero phase shift, 1e-16 s time quantization; shift_pwl enforces its voltage bound at original and retained knots. Independent check records maximum error at all original vertices.',
            'ngspice_source':{'path':str(VSRC),'sha256':sha(VSRC),'line':361,
                              'observation':'PWL interpolation loop begins scanning coefficients at index 2 for each call; implementation clue only, no measured runtime share or binary-source provenance established.'},
            'ngspice_binary':{'path':str(binary),'sha256':sha(binary)},
            'interpretation':'100 uV is inside existing 200 uV input error gate; any revised consumer must still pass unchanged 5 mV per-node and 2 ps absolute-edge baseline gates before scanning. Not evidence of baseline pass or circuit failure.',
            'cases':cases}
    OUTPUT.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')
    print('wrote',OUTPUT,flush=True)


if __name__ == '__main__':
    main()
