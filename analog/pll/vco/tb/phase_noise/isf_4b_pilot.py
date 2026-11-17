"""Four-bit VCO ISF pilot: immutable calibration preparation/check only.

Prepare and check without simulation; --resume runs the explicitly bounded pilot.
"""
import argparse
import fcntl
import math
import os
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import numpy as np

from serdes_flow import bias, pnoise, project, rcorner, spice, watch
from serdes_flow.waves import crossings
from serdes_flow.corners import Condition

ROOT = project.ROOT
HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'tb_vco_isf_ngspice.cir.in'
OUT = ROOT / 'results/analog/pll/vco/phase_noise_isf_4b'
C = Condition.parse('tt_v1800_t27')
SOURCES = [Path(__file__).resolve(), TEMPLATE, ROOT / 'src/serdes_flow/bias.py',
           ROOT / 'src/serdes_flow/rcorner.py', ROOT / 'src/serdes_flow/spice.py',
           ROOT / 'src/serdes_flow/project.py', ROOT / 'src/serdes_flow/pnoise.py',
           ROOT / 'src/serdes_flow/waves.py', ROOT / 'src/serdes_flow/watch.py', ROOT / 'src/serdes_flow/corners.py', ROOT / 'config/pdk.toml', ROOT / 'config/tools.toml']


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()


def pdk_manifest():
    root = project.model_library().parents[2]
    paths = sorted(p for d in (root / 'libs.tech/ngspice', root / 'libs.ref/sky130_fd_pr/spice')
                   for p in d.rglob('*') if p.is_file())
    if not paths:
        raise ValueError('PDK model files missing')
    return {str(p): sha(p) for p in paths}


def make_deck(camp, smoke=False):
    pulse = 'Iinj vdd v0p PWL(0 0 499p 0 500p 0.1666666667m 502p 0.1666666667m 503p 0)' if smoke else ''
    text = spice.render(TEMPLATE, **spice.corner_values(C), VCTRL='1.195', INJECT=pulse, PROBES='',
                        TSTEP='2p', STOP='1n' if smoke else '24n', SAVE_FROM='0' if smoke else '14n',
                        OUT='smoke.raw' if smoke else 'frequency.raw', CFG0=0, CFG1=1.8, CFG2=1.8)
    old = 'ctrl cfg0 cfg1 cfg2 vbias vdd 0 pll_vco_ring4_pvt_candidate'
    if text.count(old) != 1 or text.count('Vb2 cfg2 0 1.8\n') != 1:
        raise ValueError('template identity changed')
    text = text.replace(old, 'ctrl cfg0 cfg1 cfg2 cfg3 vbias vdd 0 pll_vco_ring4_4b')
    # This historical pilot explicitly studies the pre-2026-11-11 bank.
    # The shared ring now defaults to 2.52 x 2.68 / W2.68; do not silently
    # inherit it while plan.json still advertises the older W2.5 experiment.
    text = text.replace('0 pll_vco_ring4_4b\n',
                        '0 pll_vco_ring4_4b capw=2.35 capl=2.5 sw=2.5\n')
    text = text.replace('Vb2 cfg2 0 1.8\n', 'Vb2 cfg2 0 1.8\nVb3 cfg3 0 0\n')
    oldinc = f'.include "{ROOT}/analog/pll/vco/spice/vco_ring4_pvt_candidate.spice"'
    if text.count(oldinc) != 1:
        raise ValueError('template include identity changed')
    text = text.replace(oldinc, f'.include "{ROOT}/analog/pll/vco/spice/cap_bank_4b.spice"\n'
                        f'.include "{ROOT}/analog/pll/vco/spice/vco_ring4_4b.spice"')
    text = bias.real(text)
    includes = [Path(x) for x in re.findall(r'^\.include\s+"([^"]+)"', text, re.M | re.I)]
    sources = {str(p): sha(p) for p in includes}
    return bias.section(rcorner.to_pdk(text, camp / 'snap'), 'tt', 'tt'), sources


def prepare():
    camp = OUT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
    camp.mkdir(parents=True, exist_ok=False)
    (camp / 'prepared').mkdir()
    frequency, sources = make_deck(camp)
    smoke, more = make_deck(camp, smoke=True)
    sources.update(more)
    sources.update({str(p): sha(p) for p in SOURCES})
    (camp / 'prepared/frequency.cir').write_text(frequency)
    (camp / 'prepared/smoke.cir').write_text(smoke)
    snapshots = {str(p.relative_to(camp)): sha(p) for d in ('snap', 'prepared') for p in (camp / d).rglob('*') if p.is_file()}
    plan = dict(status='prepared', bank=4, switch_w_um=2.5, code=6,
                condition='tt_v1800_t27', passive='tt', bias='real', vctrl_v=1.195,
                loads='four CML buffers, 30 fF per output node', frequency_stop_s=24e-9,
                frequency_measure_start_s=19e-9, smoke_stop_s=1e-9, smoke_counts_as_measurement=False,
                planned_sites=['rp', 'mp', 'mt'], settle_s=14e-9, phases=32, every=10, cover=1.25,
                charge_c=0.5e-15, maximum_phase_gap=0.08, specification='ungraded',
                pdk_installation_id=project.pdk_installation_id(), pdk_sha256=pdk_manifest(),
                sources=sources, snapshots=snapshots)
    (camp / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return camp


def check(camp):
    plan = json.loads((camp / 'plan.json').read_text())
    if plan['pdk_installation_id'] != project.pdk_installation_id() or plan['pdk_sha256'] != pdk_manifest():
        raise ValueError('PDK identity changed')
    for name, digest in plan['sources'].items():
        if sha(name) != digest:
            raise ValueError(f'source changed: {name}')
    for name, digest in plan['snapshots'].items():
        if sha(camp / name) != digest:
            raise ValueError(f'snapshot changed: {name}')
    for smoke in (False, True):
        text, _ = make_deck(camp, smoke)
        if text != (camp / 'prepared' / ('smoke.cir' if smoke else 'frequency.cir')).read_text():
            raise ValueError('prepared deck differs')
    return plan


SITES = {"rp": ("vdd", "v0p"), "mp": ("v0p", "xvco.x0.tail"), "mt": ("xvco.x0.tail", "0")}
LVT = "msky130_fd_pr__nfet_01v8_lvt"
REG = "msky130_fd_pr__nfet_01v8"
PROBES = {"rp": [], "mp": [f"@m.xvco.x0.xmp.{LVT}[gm]", f"@m.xvco.x0.xmp.{LVT}[id]"],
          "mt": [f"@m.xvco.x0.xtail.{REG}[gm]", f"@m.xvco.x0.xtail.{REG}[id]"]}
TARGET = 2e9


def voltage_deck(base, voltage):
    if not .90 <= voltage <= 1.36:
        raise ValueError("Vctrl outside 0.90..1.36 V")
    if base.count("Vctrl ctrl 0 1.195") != 1:
        raise ValueError("Vctrl source mismatch")
    return base.replace("Vctrl ctrl 0 1.195", f"Vctrl ctrl 0 {voltage:.9f}")


def select_bracket(points):
    """Only adjacent measured points straddling target can bound interpolation."""
    points = sorted(points)
    brackets = [(a, b) for a, b in zip(points, points[1:])
                if (a[1] - TARGET) * (b[1] - TARGET) <= 0 and a[1] != b[1]]
    return min(brackets, key=lambda p: p[1][0] - p[0][0]) if brackets else None


def bracket_candidate(points):
    pair = select_bracket(points)
    if pair is None:
        raise ValueError("calibration_required: measured points do not bracket 2 GHz")
    (v0, f0), (v1, f1) = pair
    v = round(v0 + (TARGET - f0) * (v1 - v0) / (f1 - f0), 9)
    if not (v0 <= v <= v1 and .90 <= v <= 1.36) or any(abs(v - x[0]) < 1e-9 for x in points):
        raise ValueError("calibration_required: bracket cannot be refined")
    return v


def phase_gap(x):
    x = np.sort(np.asarray(x, dtype=float))
    if len(x) < 2 or not np.all(np.isfinite(x)) or np.any(x < 0) or np.any(x >= 1):
        return None
    return float(np.max(np.diff(np.r_[x, x[0] + 1])))


def site_deck(base, site, voltage, period):
    if not math.isfinite(period) or period <= 0:
        raise ValueError("invalid period")
    spacing = 10 * period + 1.25 * period / 32
    stop = float(f"{14e-9 + 34 * spacing:.9e}")
    pwl, centres = pnoise.pulse_train(14e-9, spacing, 33, .5e-15)
    a, b = SITES[site]
    text = voltage_deck(base, voltage)
    text = text.replace(".temp 27", f"Iinj {a} {b} {pwl}\n.temp 27")
    text = text.replace("tran 2p 24n 14n 2p", f"tran 1p {stop:.9e} 11n 1p")
    text = text.replace(".save v(v0p) v(v0n) v(xvco.x0.tail) v(ctrl) ",
                        f".save v(v0p) v(v0n) v(xvco.x0.tail) v(ctrl) {' '.join(PROBES[site])}")
    text = text.replace("write frequency.raw v(v0p) v(v0n) v(xvco.x0.tail)",
                        f"write {site}.raw v(v0p) v(v0n) v(xvco.x0.tail) {' '.join(PROBES[site])}")
    if f"write {site}.raw" not in text or "Iinj " not in text or f"tran 1p {stop:.9e}" not in text:
        raise ValueError("site deck transformation failed")
    return text, centres, stop


def _active_count():
    count = 0
    for pid in os.listdir('/proc'):
        if pid.isdigit():
            try:
                count += Path(f'/proc/{pid}/comm').read_text().strip() == 'ngspice'
            except OSError:
                pass
    return count


def completed(camp, name, deck, raw, end, vectors):
    """A result needs exact deck, execution identity, and an untruncated waveform."""
    dirs = [camp / name] + [d for d in camp.glob(name + '.r*') if d.is_dir() and d.name.rsplit('.r', 1)[-1].isdigit()]
    dirs.sort(key=lambda d: int(d.name.rsplit('.r', 1)[-1]) if d.name != name else 1, reverse=True)
    for run in dirs:
        try:
            ex = json.loads((run / 'execution.json').read_text())
            if (ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures'] or
                ex['deck_sha256'] != hashlib.sha256(deck.encode()).hexdigest() or
                ex['pdk_installation_id'] != project.pdk_installation_id() or (run / 'tb.cir').read_text() != deck):
                continue
            wave = spice.Waves(run / raw)
            if (len(wave.t) < 2 or not np.all(np.isfinite(wave.t)) or wave.t[-1] < end * (1 - 1e-6)
                    or any(v not in wave or not np.all(np.isfinite(wave[v])) for v in vectors)):
                continue
            return run, wave
        except (OSError, KeyError, ValueError, IndexError):
            continue
    return None


def ensure(camp, name, deck, raw, end, timeout, vectors):
    check(camp)
    camp = camp.resolve()
    if any(p == camp or p.is_relative_to(camp) for p in watch.ngspice_cwds()):
        raise RuntimeError("ngspice already active in this campaign")
    found = completed(camp, name, deck, raw, end, vectors)
    if found:
        return found
    if _active_count() >= 4:
        raise RuntimeError("global ngspice quota exhausted")
    run = spice.next_run_dir(camp, name)
    ex = spice.run(deck, run, timeout_s=timeout, meta={'pilot': 'vco_4b_isf', 'case': name})
    check(camp)
    found = completed(camp, name, deck, raw, end, vectors)
    if not found:
        raise RuntimeError(f"incomplete {run}: exit={ex.exit_code}, logs={ex.log_failures[:3]}")
    return found


def frequency(w):
    select = w.t >= 19e-9
    t = w.t[select]
    y = (w['v(v0p)'] - w['v(v0n)'])[select]
    times, polarity = crossings(t, y)
    rising = times[polarity > 0]
    if len(rising) < 4:
        raise ValueError("insufficient settled crossings")
    return float((len(rising) - 1) / (rising[-1] - rising[0]))


def checkpoint(camp, category, data):
    directory = camp / category / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'summary.json').write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')
    return directory


def resume(camp):
    with (camp / '.runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = check(camp)
        base = (camp / 'prepared/frequency.cir').read_text()
        smoke = (camp / 'prepared/smoke.cir').read_text()
        ensure(camp, 'smoke_rp', smoke, 'smoke.raw', 1e-9, 600, ['v(v0p)', 'v(v0n)', 'v(xvco.x0.tail)'])
        points, records = [], []
        def measure(v):
            deck = voltage_deck(base, v)
            run, wave = ensure(camp, f'freq_{round(v * 1e9):010d}', deck, 'frequency.raw', 24e-9, 900, ['v(v0p)', 'v(v0n)'])
            f = frequency(wave)
            points.append((v, f))
            records.append(dict(vctrl_v=v, frequency_hz=f, run=str(run.relative_to(ROOT)),
                                raw_sha256=sha(run / 'frequency.raw'), execution_sha256=sha(run / 'execution.json')))
        measure(1.195)
        if abs(points[0][1] / TARGET - 1) > .01:
            measure(1.17)
            measure(1.22)
            if select_bracket(points) is None:
                checkpoint(camp, 'calibration', dict(status='calibration_required', points=records, reason='no measured bracket'))
                raise ValueError('calibration_required: measured points do not bracket 2 GHz')
            for _ in range(5):
                v = bracket_candidate(points)
                measure(v)
                if abs(points[-1][1] / TARGET - 1) <= .01:
                    break
            else:
                checkpoint(camp, 'calibration', dict(status='calibration_required', points=records, reason='five interpolations exhausted'))
                raise ValueError('calibration_required: five interpolations exhausted')
            chosen = points[-1]
        else:
            chosen = points[0]
        voltage, f = chosen
        period = 1 / f
        cal = checkpoint(camp, 'calibration', dict(status='measured', points=records, vctrl_v=voltage,
                         frequency_hz=f, period_s=period, spec_status='ungraded'))
        decks, entries = {}, {}
        for site in SITES:
            deck, centres, stop = site_deck(base, site, voltage, period)
            decks[site] = (deck, centres, stop)
            entries[site] = dict(deck_sha256=hashlib.sha256(deck.encode()).hexdigest(), t_end_s=stop,
                                 centres_s=centres.tolist())
        siteplan = camp / 'site_plans' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '_' + uuid4().hex[:8])
        siteplan.mkdir(parents=True, exist_ok=False)
        for site, (deck, _, _) in decks.items():
            path = siteplan / f'{site}.cir'
            path.write_text(deck)
            if sha(path) != entries[site]['deck_sha256']:
                raise ValueError(f'site deck write mismatch: {site}')
            entries[site]['deck_path'] = str(path.relative_to(ROOT))
        site_metadata = dict(calibration=str(cal.relative_to(ROOT)), calibration_sha256=sha(cal / 'summary.json'),
                             vctrl_v=voltage, frequency_hz=f, period_s=period, sites=entries, spec_status='ungraded',
                             load=plan['loads'], bank=4, code=6, switch_w_um=2.5)
        (siteplan / 'summary.json').write_text(json.dumps(site_metadata, indent=2, allow_nan=False) + '\n')
        results = {}
        for site, (deck, centres, stop) in decks.items():
            if sha(siteplan / f'{site}.cir') != entries[site]['deck_sha256']:
                raise ValueError(f'site deck changed: {site}')
            run, w = ensure(camp, site, deck, f'{site}.raw', stop, max(1800, math.ceil(stop / 1e-9 * 5)),
                            ['v(v0p)', 'v(v0n)', 'v(xvco.x0.tail)', *PROBES[site]])
            record = dict(run=str(run.relative_to(ROOT)), raw_sha256=sha(run / f'{site}.raw'),
                          execution_sha256=sha(run / 'execution.json'), actual_t_end_s=float(w.t[-1]),
                          status='incomplete', spec_status='ungraded', h_rms=None, h_mean=None)
            try:
                imp = pnoise.impulse_response(w.t, w['v(v0p)'] - w['v(v0n)'], centres, .5e-15)
                gap = phase_gap(imp.x)
                good = len(imp.x) == 32 and gap is not None and gap <= .08 and np.all(np.isfinite(imp.h))
                record.update(period_s=imp.period, phase=[float(x) if np.isfinite(x) else None for x in imp.x],
                              response=[float(x) if np.isfinite(x) else None for x in imp.h], gap=gap,
                              status='observed' if good else 'incomplete',
                              h_rms=float(np.sqrt(pnoise.white_coefficient(imp))) if good else None,
                              h_mean=float(pnoise.slow_coefficient(imp)) if good else None)
            except (ValueError, IndexError, KeyError, FloatingPointError) as exc:
                record['reason'] = str(exc)
            results[site] = record
            checkpoint(camp, 'site_analysis', dict(site=site, site_plan=str(siteplan.relative_to(ROOT)),
                       site_plan_sha256=sha(siteplan / 'summary.json'), result=record))
        result = dict(status='complete' if all(r['status'] == 'observed' for r in results.values()) else 'incomplete',
                      spec_status='ungraded', site_plan=str(siteplan.relative_to(ROOT)),
                      site_plan_sha256=sha(siteplan / 'summary.json'), sites=results)
        report = checkpoint(camp, 'analysis', result)
        print(json.dumps({'status': result['status'], 'analysis': str(report.relative_to(ROOT))}))
        if result['status'] != 'complete':
            raise ValueError('phase coverage incomplete; result remains ungraded')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--check', type=Path)
    group.add_argument('--resume', type=Path)
    args = ap.parse_args()
    if args.prepare:
        print(prepare())
    elif args.check:
        plan = check(args.check.resolve())
        print(json.dumps({'status': plan['status'], 'simulation_ready': True, 'code': plan['code']}))
    else:
        resume(args.resume.resolve())


if __name__ == '__main__':
    main()
