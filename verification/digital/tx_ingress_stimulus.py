#!/usr/bin/env python3
"""Replay PHY-clock-domain events through tx_ingress_control using Icarus."""
import argparse
import hashlib
import json
import math
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / 'digital/tx/rtl/tx_ingress_control.sv'
SIGNALS = ['data', 'valid', 'ready', 'a', 'b']


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ticks(value):
    value = float(value)
    if not math.isfinite(value) or value < 0 or abs(value * 1000 - round(value * 1000)) > 1e-6:
        raise ValueError(f'time must be nonnegative and representable in 1 fs: {value}')
    return round(value * 1000)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--schedule', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    s = json.loads(args.schedule.read_text())
    stop, reset, permit = (ticks(s[k]) for k in ('stop_ps', 'reset_release_ps', 'permit_ps'))
    supply = float(s['supply_v'])
    if not math.isfinite(supply) or supply <= 0 or reset > stop or permit > stop:
        raise ValueError('invalid supply or reset/permit time')
    events = []
    for key, level in [('rises_ps', 1), ('falls_ps', 0)]:
        events.extend((ticks(t), 'clk', level) for t in s[key])
    updates = s['updates']
    if not updates:
        raise ValueError('updates must not be empty')
    for u in updates:
        t, word = ticks(u['time_ps']), u['word']
        if not isinstance(word, int) or isinstance(word, bool) or not 0 <= word <= 65535:
            raise ValueError('word must be a 16-bit integer')
        events.append((t, 'update', word))
    update_times = [ticks(u['time_ps']) for u in updates]
    if update_times != sorted(set(update_times)):
        raise ValueError('updates must be strictly ordered')
    events.extend([(reset, 'reset', 1), (permit, 'permit', 1), (update_times[-1] + 4000000, 'valid', 0)])
    if any(t > stop for t, _, _ in events):
        raise ValueError('event exceeds stop time')
    clock = sorted((t, v) for t, kind, v in events if kind == 'clk')
    expected = 0
    previous = -1
    for t, v in clock:
        if t <= previous or v != expected or t == 0:
            raise ValueError('clock edges must strictly alternate, starting with a fall after t=0')
        previous, expected = t, 1 - expected
    if len({t for t, _, _ in events}) != len(events):
        raise ValueError('simultaneous input events are ambiguous')
    falls = {t for t, v in clock if v == 0}
    if any(t - 100000 not in falls for t in update_times):
        raise ValueError('each update must follow a fall by 100 ps')
    events.sort()
    lines = ['`timescale 1ps/1fs', 'module generated_tb;',
             'reg clk=1, rst_n=1, enable=0, good=0, in_valid=0; reg [15:0] in_data=0;',
             'wire ready, cv, av, bv; wire [15:0] data;',
             'integer trace, captures;',
             'tx_ingress_control dut(.word_clk(clk),.rst_n(rst_n),.enable(enable),.clock_good(good),.in_valid(in_valid),.in_data(in_data),.word_ready(ready),.capture_data(data),.capture_valid(cv),.a_valid(av),.b_valid(bv));',
             'initial begin trace=$fopen("trace.tsv","w"); captures=$fopen("captures.tsv","w"); rst_n=0; end',
             'always @(data or cv or ready or av or bv) $fstrobe(trace,"%0.3f\\t%h\\t%b\\t%b\\t%b\\t%b", $realtime,data,cv,ready,av,bv);',
             'always @(posedge clk) $fdisplay(captures,"%0.3f\\t%h\\t%b",$realtime,data,cv);',
             'initial begin']
    last = 0
    for t, kind, val in events:
        action = {'clk': f'clk={val};', 'reset': 'rst_n=1;', 'permit': 'enable=1; good=1;', 'valid': 'in_valid=0;', 'update': f'in_data=16\'h{val:04x}; in_valid=1;'}[kind]
        lines.append(f'  #{(t-last)/1000:.3f} {action}')
        last = t
    lines.extend([f'  #{(stop-last)/1000:.3f} $finish;', 'end', 'endmodule', ''])
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tb = out / 'generated_tb.sv'
    tb.write_text('\n'.join(lines))
    def run(cmd, log):
        p = subprocess.run(cmd, cwd=out, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        (out / log).write_text(p.stdout)
        if p.returncode:
            raise RuntimeError(f'{cmd[0]} failed; see {log}')
    run(['iverilog', '-g2012', '-s', 'generated_tb', '-o', 'simulation.vvp', str(RTL), str(tb)], 'compile.log')
    run(['vvp', 'simulation.vvp'], 'run.log')
    trace = {}
    for line in (out / 'trace.tsv').read_text().splitlines():
        fields = line.split('\t')
        if len(fields) != 6:
            raise ValueError(f'invalid trace: {line}')
        t = ticks(fields[0]); vals = fields[1:]
        if any(any(c in x.lower() for c in 'xz') for x in vals):
            if t >= reset:
                raise ValueError(f'unknown output after reset release: {line}')
            continue
        parsed = (int(vals[0], 16), *(int(v, 2) for v in vals[1:]))
        if t in trace and trace[t] != parsed:
            raise ValueError(f'inconsistent stable strobes at {fields[0]} ps')
        trace[t] = parsed
    captures = []
    for line in (out / 'captures.tsv').read_text().splitlines():
        t, word, valid = line.split('\t')
        if any(c in (word + valid).lower() for c in 'xz'):
            if ticks(t) >= reset:
                raise ValueError(f'unknown capture after reset release: {line}')
            continue
        captures.append({'time_ps': float(t), 'word': int(word, 16), 'valid': int(valid, 2)})
    # At t=0 initial reset drives every exported signal low. Reject transitions
    # whose centered 20 ps ramps overlap, including negative start times.
    source_values = {f'd{i}': [] for i in range(16)}
    source_values.update({f'guard_{x}': [] for x in ('a', 'b', 'ready', 'valid')})
    for t, (data, valid, ready, a, b) in sorted(trace.items()):
        vals = {f'd{i}': (data >> i) & 1 for i in range(16)}
        vals.update(guard_a=a, guard_b=b, guard_ready=ready, guard_valid=valid)
        for name, v in vals.items():
            prior = source_values[name][-1][1] if source_values[name] else 0
            if v != prior:
                source_values[name].append((t, v))
    transition_times = sorted({t for changes in source_values.values() for t, _ in changes})
    if any(b - a < 20000 for a, b in zip(transition_times, transition_times[1:])):
        raise ValueError('distinct output events have overlapping 20 ps ramps')
    inc = []
    for name, changes in source_values.items():
        points = [(0, 0)]
        previous = 0
        for t, v in changes:
            start, end = t - 10000, t + 10000
            if start <= points[-1][0]:
                raise ValueError(f'overlapping or negative PWL ramp for {name} at {t/1000} ps')
            points.extend([(start, previous), (end, v)])
            previous = v
        body = ' '.join(f'{t/1000:.3f}p {v*supply:.9g}' for t, v in points)
        inc.append(f'V{name} {name} 0 PWL({body})')
    (out / 'stimuli.inc').write_text('\n'.join(inc) + '\n')
    outputs = ['generated_tb.sv', 'compile.log', 'run.log', 'trace.tsv', 'captures.tsv', 'stimuli.inc', 'simulation.vvp']
    manifest = {'boundary_id': s['boundary_id'], 'schedule_sha256': sha(args.schedule), 'rtl_sha256': sha(RTL), 'script_sha256': sha(Path(__file__)), 'generated_tb_sha256': sha(tb), 'captures': captures, 'outputs': {name: {'sha256': sha(out / name), 'source': ('iverilog' if name in ('compile.log', 'simulation.vvp') else 'vvp RTL replay' if name in ('run.log', 'trace.tsv', 'captures.tsv') else 'generated from schedule' if name == 'generated_tb.sv' else 'derived from trace.tsv')} for name in outputs}, 'strobe_rule': 'same-time stable values must agree; unknown values before reset release are omitted'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Wrote {out}; {len(trace)} stable trace times, {len(captures)} captures')


if __name__ == '__main__':
    main()
