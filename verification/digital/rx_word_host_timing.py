"""Pre-layout intra-domain SKY130 HD timing of the RX host path.

Independent clocks are intentionally NOT constrained as synchronous paths or
blanket false-pathed; cross-domain reports are ungraded and physical CDC is open.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

from serdes_flow.project import ROOT

HERE=Path(__file__).resolve()
RTL=[ROOT/f'digital/rx/rtl/{n}.sv' for n in ('rx_word_map','rx_word_align16','rx_async_word_fifo','rx_word_host_path')]
LIBDIR=Path('/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/lib')
STA=Path('/home/host/.local/opt/opensta-focal-20191111/usr/bin/sta')
CORNERS=('tt_025C_1v80','ss_n40C_1v60','ss_100C_1v60','ff_n40C_1v95')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def dump(path,data):path.write_text(json.dumps(data,indent=2,allow_nan=False)+'\n')


def worst_paths(section):
    rows=[]
    for text in re.split(r'(?=Startpoint: )',section):
        a=re.search(r'Startpoint: ([^\s]+)',text);b=re.search(r'Endpoint: ([^\s]+)',text)
        s=re.search(r'([-+]?\d+\.\d+)\s+slack \((MET|VIOLATED)\)',text)
        if a and b and s:rows.append(dict(startpoint=a[1],endpoint=b[1],slack_ns=float(s[1]),status=s[2]))
    if not rows:raise ValueError('no timed paths found')
    return min(rows,key=lambda x:x['slack_ns'])


def split_reports(text):
    labels=['WORD_SETUP','WORD_HOLD','HOST_SETUP','HOST_HOLD','CROSS_WORD_HOST','CROSS_HOST_WORD','UNCONSTRAINED','CHECK_SETUP']
    chunks={}
    for i,label in enumerate(labels):
        start='--- '+label+' ---'; end='--- '+labels[i+1]+' ---' if i+1<len(labels) else '--- END ---'
        if start not in text or end not in text:raise ValueError('missing timing section '+label)
        chunks[label]=text.split(start,1)[1].split(end,1)[0]
    return chunks


def output_driver_pins(verilog,flat=False):
    # Resolve stable hierarchical pins from the generated FIFO netlist.
    body=re.search(r'(?ms)^module '+('rx_word_host_path' if flat else '[^\n]*rx_async_word_fifo')+r'[^\n]*\n(.*?)^endmodule',verilog)
    if body is None:raise ValueError('FIFO mapped module missing')
    found={}
    for _,name,content in re.findall(r'(?ms)^\s*(sky130_fd_sc_hd__\w+)\s+(\S+)\s*\((.*?)\);',body[1]):
        for pin,net in re.findall(r'\.(\w+)\(([^)]+)\)',content):
            net=net.strip().lstrip('\\')
            net={'word_online':'w_online','host_online':'r_online','u_fifo.w_reset_n':'w_reset_n','u_fifo.r_reset_n':'r_reset_n'}.get(net,net)
            if net in ('w_online','r_online','w_reset_n','r_reset_n') and pin in ('X','Y','Q'):
                if net in found:raise ValueError('multiple drivers for '+net)
                found[net]=('' if flat else 'u_fifo/')+name+'/'+pin
    if set(found)!={'w_online','r_online','w_reset_n','r_reset_n'}:raise ValueError('steady-state pins not found')
    return found


def mapped_area(lib,counts):
    text=lib.read_text();areas={}
    for cell,body in re.findall(r'(?ms)^    cell \("([^"]+)"\) \{(.*?)(?=^    cell \(|\Z)',text):
        m=re.search(r'(?m)^\s*area\s*:\s*([0-9.eE+-]+)\s*;',body)
        if m:areas[cell]=float(m[1])
    missing=set(counts)-set(areas)
    if missing:raise ValueError('area absent for mapped cells '+str(sorted(missing)))
    return sum(count*areas[cell] for cell,count in counts.items())


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--mapping',choices=('baseline','abc_timing_flat'),default='baseline');args=parser.parse_args()
    camp=ROOT/'results/digital/rx/word_host_timing'/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')+'_'+uuid.uuid4().hex[:8]);camp.mkdir(parents=True)
    snap=camp/'execution';snap.mkdir();report=dict(status='failed',mapping_strategy=args.mapping,cases=[],sources={},tools={},commands=[],
      scope='TT025/1.8, SS−40/1.60, SS100/1.60, FF−40/1.95 pre-layout local paths only; 1.60V/25C libraries differ from specified 1.65V/27C.',
      ungraded=['all asynchronous cross-domain paths','Gray bus delay/skew, synchronizer MTBF','reset recovery/removal and clock/online startup','physical parasitics and clock-tree skew','physical RX capture timing','full PVT and system qualification'])
    def run(name,argv):
        p=subprocess.run(argv,cwd=snap,capture_output=True,text=True,timeout=240);output=p.stdout+p.stderr;log=camp/(name+'.log');log.write_text(output)
        report['commands'].append(dict(name=name,argv=argv,exit_code=p.returncode,log_sha256=sha(log)))
        if p.returncode or re.search(r'(?im)^\s*(?:ERROR|Error):',output):raise RuntimeError(name+' failed')
        return output
    try:
        sources=RTL+[HERE]
        for p in sources:
            dest=snap/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest);report['sources'][str(p.relative_to(ROOT))]=sha(p)
        libs={}
        for corner in CORNERS:
            src=LIBDIR/f'sky130_fd_sc_hd__{corner}.lib';dst=snap/src.name;shutil.copyfile(src,dst)
            match=re.search(r'capacitive_load_unit\s*\(\s*([0-9.eE+-]+)\s*,\s*"(\w+)"\s*\)',dst.read_text())
            if not match or match[2].lower() not in ('pf','ff'):raise ValueError('invalid capacitance unit')
            libs[corner]=(dst,float(match[1])*(1000 if match[2].lower()=='pf' else 1));report['sources'][str(src)]=sha(src)
        for name,exe,flag in [('yosys',shutil.which('yosys'),'-V'),('sta',str(STA),'-version')]:
            binary=Path(exe).resolve();v=run(name+'_version',[str(binary),flag]);report['tools'][name]=dict(path=str(binary),sha256=sha(binary),version=v.strip())
        tt=libs[CORNERS[0]][0];net=snap/'mapped.v';js=snap/'mapped.json'
        sourcestr=' '.join(str(snap/p.relative_to(ROOT)) for p in RTL)
        if args.mapping=='abc_timing_flat':
            constraint=snap/'abc.constr';constraint.write_text('set_driving_cell sky130_fd_sc_hd__buf_1\nset_load 10\n')
            mapping=f'synth -top rx_word_host_path -flatten -noabc; dfflibmap -liberty {tt}; abc -liberty {tt} -D 4000 -constr {constraint}'
        else:
            mapping=f'synth -top rx_word_host_path; dfflibmap -liberty {tt}; abc -liberty {tt}'
        ys=f'read_liberty -lib {tt}; read_verilog -sv {sourcestr}; hierarchy -check -top rx_word_host_path; {mapping}; clean; check -assert; write_verilog -noattr -noexpr {net}; write_json {js}'
        (snap/'mapping.ys').write_text(ys+'\n');run('mapping',[report['tools']['yosys']['path'],'-s',str(snap/'mapping.ys')])
        design=json.loads(js.read_text());counts=Counter()
        def walk(name):
            for cell in design['modules'][name]['cells'].values():
                typ=cell['type']
                if typ in design['modules'] and not design['modules'][typ].get('attributes',{}).get('blackbox'):walk(typ)
                else:counts[typ]+=1
        walk('rx_word_host_path')
        steady_pins=output_driver_pins(net.read_text(),flat=args.mapping=='abc_timing_flat')
        report['mapping']=dict(netlist_sha256=sha(net),json_sha256=sha(js),cells=dict(counts),total_cells=sum(counts.values()),cell_area_um2=mapped_area(tt,counts),steady_state_pins=steady_pins)
        for corner,(lib,cap_unit_ff) in libs.items():
            sdc=f'''create_clock -name word_clk -period 4 -waveform {{0 2}} [get_ports word_clk]
create_clock -name host_clk -period 4 -waveform {{0 2}} [get_ports host_clk]
set_input_transition 0.1 [all_inputs]
set_clock_transition 0.1 [get_clocks {{word_clk host_clk}}]
set_clock_uncertainty -setup 0.05 [get_clocks {{word_clk host_clk}}]
set_clock_uncertainty -hold 0.05 [get_clocks {{word_clk host_clk}}]
set_case_analysis 1 [get_ports arst_n]
{''.join('set_case_analysis 1 [get_pins '+pin+']'+chr(10) for pin in steady_pins.values())}
set_input_delay -clock word_clk -max 0.2 [get_ports {{phys* training_enable}}]
set_input_delay -clock word_clk -min 0.05 [get_ports {{phys* training_enable}}]
set_input_delay -clock host_clk -max 0.2 [get_ports host_ready]
set_input_delay -clock host_clk -min 0.05 [get_ports host_ready]
set_output_delay -clock word_clk -max 0.5 [get_ports {{word_online aligned offset*}}]
set_output_delay -clock word_clk -min 0 [get_ports {{word_online aligned offset*}}]
set_output_delay -clock host_clk -max 0.5 [get_ports {{host_data* host_valid host_online host_error}}]
set_output_delay -clock host_clk -min 0 [get_ports {{host_data* host_valid host_online host_error}}]
set_load {10/cap_unit_ff:.12g} [all_outputs]
'''
            sp=snap/(corner+'.sdc');sp.write_text(sdc)
            def pathcmd(src,dst,delay):return f'report_checks -from [get_clocks {src}] -to [get_clocks {dst}] -path_delay {delay} -group_count 20 -endpoint_count 5 -format full_clock_expanded -fields {{capacitance slew input_pin net}} -digits 6'
            sections=[('WORD_SETUP',pathcmd('word_clk','word_clk','max')),('WORD_HOLD',pathcmd('word_clk','word_clk','min')),
                      ('HOST_SETUP',pathcmd('host_clk','host_clk','max')),('HOST_HOLD',pathcmd('host_clk','host_clk','min')),
                      ('CROSS_WORD_HOST',pathcmd('word_clk','host_clk','max')),('CROSS_HOST_WORD',pathcmd('host_clk','word_clk','max')),
                      ('UNCONSTRAINED','report_checks -unconstrained -path_delay min_max -group_count 100 -endpoint_count 10'),('CHECK_SETUP','check_setup -verbose')]
            tcl=f'read_liberty {lib}\nset_operating_conditions -library sky130_fd_sc_hd__{corner} {corner}\nread_verilog {net}\nlink_design rx_word_host_path\nread_sdc {sp}\n'
            tcl+='\n'.join('puts "--- '+name+' ---"\n'+cmd for name,cmd in sections)+'\nputs "--- END ---"\nexit\n'
            tp=snap/(corner+'.tcl');tp.write_text(tcl);output=run('sta_'+corner,[report['tools']['sta']['path'],'-no_init','-exit',str(tp)])
            parts=split_reports(output);worst={k:worst_paths(parts[k]) for k in ('WORD_SETUP','WORD_HOLD','HOST_SETUP','HOST_HOLD')}
            report['cases'].append(dict(corner=corner,load_ff=10,library_capacitance_unit_ff=cap_unit_ff,worst=worst,
                violated_local_paths=[k for k,v in worst.items() if v['slack_ns']<0],sdc_sha256=sha(sp),tcl_sha256=sha(tp),steady_state='reset released and both domain online nets forced high; reset/online entry timing ungraded',report='sta_'+corner+'.log',
                cross_domain='reported but ungraded; synchronous relative phase is fictitious',warnings=[line for line in output.splitlines() if re.search(r'(?i)warning',line)]))
        for p in sources:
            if sha(p)!=report['sources'][str(p.relative_to(ROOT))] or sha(snap/p.relative_to(ROOT))!=sha(p):raise ValueError('RTL/source changed')
        for corner,(lib,_) in libs.items():
            if sha(lib)!=report['sources'][str(LIBDIR/lib.name)] or sha(LIBDIR/lib.name)!=sha(lib):raise ValueError('Liberty source or copy changed')
        report['status']='prelayout_local_timing_measured_cross_domain_ungraded'
    except Exception as exc:
        report['error']=f'{type(exc).__name__}: {exc}';raise
    finally:
        report['evidence']={str(p.relative_to(camp)):sha(p) for p in camp.rglob('*') if p.is_file()};dump(camp/'summary.json',report);print(camp/'summary.json',flush=True)


if __name__=='__main__':main()
