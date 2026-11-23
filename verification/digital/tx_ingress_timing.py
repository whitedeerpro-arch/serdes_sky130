"""Archive exploratory SKY130 HD guard mapping and OpenSTA timing, not signoff."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from serdes_flow.project import ROOT, git_revision

STA = Path('/home/host/.local/opt/opensta-focal-20191111/usr/bin/sta')
LIBDIR = Path('/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib')
CORNERS = ['tt_025C_1v80', 'ss_n40C_1v60', 'ss_100C_1v60', 'ff_n40C_1v95']
RTL = Path('digital/tx/rtl/tx_ingress_control.sv')
SCRIPT = Path('verification/digital/tx_ingress_timing.py')
SCOPE = ('Exploratory generic-layout guard timing, ungraded, not design closure. '
         'No analog DFF setup/hold or valid-buffer capacitance extraction, clock_good generation, CDC, '
         'driver blank, parasitics, reset recovery/removal, or complete 45-point PVT. '
         'The 1.60 V and 25 C libraries differ from the specified 1.65 V and 27 C conditions.')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(argv, cwd, log):
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=180)
    output = p.stdout + p.stderr
    log.write_text(output)
    if p.returncode or re.search(r'(?m)^Error:', output):
        raise RuntimeError(f'command failed: {argv[0]} ({p.returncode}), see {log}')
    return output


def main():
    camp = ROOT / 'results/digital/tx/ingress_timing' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    camp.mkdir(parents=True, exist_ok=False)
    snap = camp / 'execution'
    snap.mkdir()
    result = dict(status='failed', scope=SCOPE, git_revision=git_revision(), sources={}, tools={}, commands=[], cases=[])
    error = None
    try:
        for path in [RTL, SCRIPT]:
            target = snap / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
            result['sources'][str(path)] = sha(target)
        libs = {}
        for corner in CORNERS:
            source = LIBDIR / f'sky130_fd_sc_hd__{corner}.lib'
            target = snap / source.name
            shutil.copyfile(source, target)
            match = re.search(r'capacitive_load_unit\s*\(\s*([0-9.eE+-]+)\s*,\s*"(\w+)"\s*\)', target.read_text())
            if not match:
                raise ValueError(f'capacitive unit missing: {source}')
            scale, unit = float(match.group(1)), match.group(2).lower()
            if unit not in ('pf', 'ff') or scale <= 0:
                raise ValueError(f'unsupported capacitive unit {scale} {unit}')
            libs[corner] = (target, scale * (1000 if unit == 'pf' else 1))
            result['sources'][str(source)] = sha(target)
        for name, exe, args in [('yosys', shutil.which('yosys'), ['-V']), ('sta', str(STA), ['-version'])]:
            exe = Path(exe).resolve()
            version = command([str(exe)] + args, snap, camp / f'{name}_version.log').strip()
            result['tools'][name] = dict(path=str(exe), sha256=sha(exe), version=version)

        def run(name, argv):
            result['commands'].append(dict(name=name, argv=argv, cwd=str(snap.relative_to(ROOT)), log=name+'.log'))
            out = command(argv, snap, camp / (name+'.log'))
            result['commands'][-1]['exit_code'] = 0
            return out

        tt = libs[CORNERS[0]][0]
        netlist = snap / 'mapped.v'
        ys = f'read_liberty -lib {tt}; read_verilog -sv {snap / RTL}; hierarchy -check -top tx_ingress_control; synth -top tx_ingress_control; dfflibmap -liberty {tt}; abc -liberty {tt}; clean; check -assert; write_verilog -noattr -noexpr {netlist}'
        (snap / 'mapping.ys').write_text(ys+'\n')
        run('mapping', ['yosys', '-s', str(snap / 'mapping.ys')])
        result['sources']['mapped.v'] = sha(netlist)
        # Check all candidate Liberty pin sets before editing cell names.
        cell_sets = {}
        for corner, (lib, _) in libs.items():
            libtext = lib.read_text()
            cells = {}
            for cell in ('dfrtn_1', 'dfrtn_2', 'dfrtn_4', 'dfrtp_1', 'dfrtp_2', 'dfrtp_4', 'and2_0', 'and2_2', 'and2_4', 'and3_1', 'and3_2', 'and3_4', 'buf_4'):
                m = re.search(r'    cell \(\"sky130_fd_sc_hd__' + cell + r'\"\) \{(.*?)(?=\n    cell \(|\Z)', libtext, re.S)
                cells[cell] = sorted(set(re.findall(r'^        pin \(\"([^\"]+)\"\)', m.group(1), re.M))) if m else None
            for base, variants in [('dfrtp_1', ('dfrtp_2', 'dfrtp_4')), ('and2_0', ('and2_2', 'and2_4')), ('and3_1', ('and3_2', 'and3_4'))]:
                if not cells[base] or any(cells[v] != cells[base] for v in variants):
                    raise ValueError(f'cell pins missing or mismatch: {corner} {base}')
            if cells['buf_4'] != ['A', 'X']:
                raise ValueError(f'buffer cell missing or pin mismatch: {corner}')
            cell_sets[corner] = cells
        result['liberty_cell_pins'] = cell_sets
        result['mapping_iteration'] = 'unadopted textual strength alternatives; dfrtn_1 retained since dfrtn_2/4 absent'
        variants = {'baseline': netlist}
        base_text = netlist.read_text()
        for strength in (2, 4):
            variant = base_text
            for family, old in [('dfrtp', 1), ('and2', 0), ('and3', 1)]:
                source = f'sky130_fd_sc_hd__{family}_{old}'
                replacement = f'sky130_fd_sc_hd__{family}_{strength}'
                if source not in variant:
                    raise ValueError(f'expected mapped cell missing: {source}')
                variant = re.sub(r'\b' + source + r'\b', replacement, variant)
            variant_path = snap / f'mapping_iteration_strength{strength}.v'
            variant_path.write_text(variant)
            variants[f'strength{strength}'] = variant_path
            result['sources'][variant_path.name] = sha(variant_path)
        # Q alone drives the buffer; the original net remains the buffer output.
        buffered = base_text
        for signal in ('word_ready', 'a_valid', 'b_valid'):
            original = f'.Q({signal})'
            if buffered.count(original) != 1:
                raise ValueError(f'unexpected register output topology: {signal}')
            buffered = buffered.replace(original, f'.Q({signal}_raw)')
        insertion = ''.join(f'  wire {sig}_raw;\n  sky130_fd_sc_hd__buf_4 buffer_{sig} (.A({sig}_raw), .X({sig}));\n' for sig in ('word_ready', 'a_valid', 'b_valid'))
        buffered = buffered.replace('endmodule', insertion + 'endmodule')
        buf_path = snap / 'mapping_iteration_outputbuf.v'
        buf_path.write_text(buffered)
        variants['outputbuf'] = buf_path
        result['sources'][buf_path.name] = sha(buf_path)
        for variant_name, variant_netlist in variants.items():
          for corner in CORNERS:
            lib, ff_per_unit = libs[corner]
            for load in (5, 10, 20):
                name = f'{variant_name}_{corner}_{load}ff'
                sdc = f'''create_clock -name word_clk -period 4 -waveform {{0 2}} [get_ports word_clk]
set_input_transition 0.1 [all_inputs]
set_clock_transition 0.1 [get_clocks word_clk]
set_clock_uncertainty -setup 0.05 [get_clocks word_clk]
set_clock_uncertainty -hold 0.05 [get_clocks word_clk]
set_input_delay -clock word_clk -clock_fall -max 0.2 [get_ports {{in_data* in_valid}}]
set_input_delay -clock word_clk -clock_fall -min 0.05 [get_ports {{in_data* in_valid}}]
set_input_delay -clock word_clk -max 0.5 [get_ports {{enable clock_good}}]
set_input_delay -clock word_clk -min 0.05 [get_ports {{enable clock_good}}]
set_case_analysis 1 [get_ports rst_n]
set_output_delay -clock word_clk -max 0.5 [get_ports {{capture_data* capture_valid word_ready}}]
set_output_delay -clock word_clk -min -0.05 [get_ports {{capture_data* capture_valid}}]
set_output_delay -clock word_clk -min 0 [get_ports word_ready]
set_output_delay -clock word_clk -clock_fall -max 1.3 [get_ports a_valid]
set_output_delay -clock word_clk -clock_fall -min 0 [get_ports a_valid]
set_output_delay -clock word_clk -max 1.3 [get_ports b_valid]
set_output_delay -clock word_clk -min 0 [get_ports b_valid]
set_load {load/ff_per_unit:.12g} [all_outputs]
'''
                sdcpath = snap / f'{name}.sdc'
                sdcpath.write_text(sdc)
                tcl = f'''read_liberty {lib}
set_operating_conditions -library sky130_fd_sc_hd__{corner} {corner}
read_verilog {variant_netlist}
link_design tx_ingress_control
read_sdc {sdcpath}
puts "--- SETUP PATHS ---"
report_checks -path_delay max -group_count 10000 -endpoint_count 10000 -format full_clock_expanded -fields {{capacitance slew input_pin net}} -digits 5
puts "--- HOLD PATHS ---"
report_checks -path_delay min -group_count 10000 -endpoint_count 10000 -format full_clock_expanded -fields {{capacitance slew input_pin net}} -digits 5
puts "--- UNCONSTRAINED ---"
report_checks -unconstrained -path_delay min_max -group_count 10000 -endpoint_count 10000
puts "--- CHECK SETUP ---"
check_setup -verbose
puts "--- VIOLATIONS ---"
report_check_types -all_violators -verbose -max_delay -min_delay -max_transition -digits 5
puts "--- WNS ---"
report_wns -digits 5
puts "--- TNS ---"
report_tns -digits 5
exit
'''
                tclpath = snap / f'{name}.tcl'
                tclpath.write_text(tcl)
                text = run(name, [str(STA), '-no_init', '-exit', str(tclpath)])
                if '--- CHECK SETUP ---' not in text or '--- WNS ---' not in text:
                    raise ValueError(f'incomplete STA report {name}')
                sections = text.split('--- SETUP PATHS ---', 1)[1].split('--- HOLD PATHS ---', 1)
                setup_text, hold_text = sections[0], sections[1].split('--- UNCONSTRAINED ---', 1)[0]
                def worst_paths(section):
                    paths = re.split(r'(?=Startpoint: )', section)
                    rows = []
                    for path in paths:
                        start = re.search(r'Startpoint: ([^\s]+)', path)
                        end = re.search(r'Endpoint: ([^\s]+)', path)
                        slack = re.search(r'([-+]?\d+\.\d+)\s+slack \((?:MET|VIOLATED)\)', path)
                        if start and end and slack:
                            rows.append(dict(startpoint=start.group(1), endpoint=end.group(1), slack_ns=float(slack.group(1))))
                    if not rows:
                        raise ValueError(f'no parsed timing paths: {name}')
                    return min(rows, key=lambda x: x['slack_ns'])
                result['cases'].append(dict(mapping=variant_name, setup_worst=worst_paths(setup_text), hold_worst=worst_paths(hold_text), corner=corner, load_ff=load, load_lib_units=load/ff_per_unit,
                    library_capacitance_unit_ff=ff_per_unit, report=name+'.log', sdc_sha256=sha(sdcpath), tcl_sha256=sha(tclpath),
                    wns=re.findall(r'(?m)^wns\s+([^\s]+)', text),
                    note='ungraded; see full report for paths, checks, violations and warnings'))
        result['status'] = 'complete_ungraded'
    except Exception as exc:
        error = exc
        result['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        summary = camp / 'summary.json'
        summary.write_text(json.dumps(result, indent=2)+'\n')
        catalog = ROOT / 'results/catalog/tx_ingress_timing.json'
        index = json.loads(catalog.read_text()) if catalog.exists() else {'campaigns': []}
        index['campaigns'].append(dict(campaign=str(camp.relative_to(ROOT)), status=result['status'], summary_sha256=sha(summary)))
        catalog.write_text(json.dumps(index, indent=2)+'\n')
        print(f'{camp}: {result["status"]}', flush=True)
    if error:
        raise error


if __name__ == '__main__':
    main()
