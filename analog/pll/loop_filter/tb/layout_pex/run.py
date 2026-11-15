"""Independent LF schematic/CPEX/native-RC impedance, feedthrough and precharge.

Both 18-MIM and stacked-fused geometries, with ideal supplies and a 500 ohm
precharge source. No CP or VCO connected; Ci/Rz/feedthrough deltas are ungraded.
The precharge functional screen uses the existing 40 mV B2 error envelope.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

import numpy as np
from serdes_flow import bias, project, spice, watch
from serdes_flow.corners import Condition

ROOT = project.ROOT
sys.path.insert(0, str(ROOT / "verification/layout"))
from review_sim import execute, freeze_includes, save_analysis

POINTS = ["tt_v1800_t27:tt", "ss_v1650_t-40:hh", "sf_v1650_t-40:ll", "fs_v1650_t85:hh",
          "ss_v1650_t85:hh", "ff_v1950_t-40:ll", "ff_v1950_t85:ll"]


def models(physical, out):
    entries = []
    out.mkdir(parents=True, exist_ok=True)
    for label,cell in [("original","pll_loop_filter_k4_pdk"),("fused","pll_loop_filter_k4_fused_pdk")]:
        for variant,file in [("schematic","reference.spice"),("cpex",cell+"_pex.spice"),("rcx",cell+"_rcx.spice")]:
            alias = f"lf_{label}_{variant}"
            text = re.sub(rf"\b{cell}\b", alias, (physical / cell / file).read_text())
            path = out / (alias+".spice")
            if path.exists() and path.read_text() != text:
                raise ValueError("LF source changed")
            if not path.exists():
                path.write_text(text)
            entries.append((alias,path))
    return entries


def deck(point, entries, method="gear"):
    tag,rc = point.split(":")
    c=Condition.parse(tag)
    target=min(1.4,c.supply-.44)
    lines=["PLL loop filter physical review", f'.lib "{project.model_library()}" {c.process}']
    lines += [f'.include "{p}"' for _,p in entries]
    lines += [f"Vdd_ac vdd_ac 0 {c.supply} ac 0", f"Vdd_tr vdd_tr 0 PWL(0 0 10n {c.supply})",
              f"Vref pref 0 {target}", f"Vref_tr pref_tr 0 PWL(0 0 10n {target})", "Ven_ac en_ac 0 0",
              f"Ven_tr en_tr 0 PWL(0 0 10n {c.supply} 2u {c.supply} 2.0001u 0)"]
    for i,(alias,_) in enumerate(entries):
        lines += [f"Xac{i} ctrl{i} z{i} pref en_ac vdd_ac 0 {alias}",
                  f"Rdc{i} ctrl{i} pref 1T", f"Iac{i} 0 ctrl{i} dc 0 ac 1"]
        if not alias.endswith("rcx"):
            lines += [f"Rpre{i} pref_tr pre{i} 500", f"Xtr{i} tc{i} tz{i} pre{i} en_tr vdd_tr 0 {alias}",
                      f".ic v(tc{i})=0 v(tz{i})=0"]
    acprobes=" ".join(f"v(ctrl{i})" for i in range(len(entries)))
    trprobes=" ".join(f"v(tc{i}) v(tz{i})" for i,(alias,_) in enumerate(entries) if not alias.endswith("rcx"))
    lines += [f".temp {c.temp}", f".options reltol=1e-4 abstol=1p vntol=1u klu method={method}", ".control",
              "set num_threads=1", "set wr_singlescale", "set wr_vecnames", "set numdgt=12",
              "ac dec 40 1k 1G",f"wrdata impedance.tsv {acprobes}"]
    lines += [f"alter Iac{i} acmag=0" for i in range(len(entries))]
    lines += ["alter Vdd_ac acmag=1", "ac dec 40 1k 1G",f"wrdata feedthrough.tsv {acprobes}",
              "tran 2n 3u 0 2n",spice.binary_output(f"wrdata waveforms.tsv {trprobes}"), "quit", ".endc", ".end", ""]
    text="\n".join(lines)
    # Keep the small complex AC tables as text, transient as binary.
    return bias.section(text,c.process,rc), target


def measure(path,entries,target):
    z=np.loadtxt(path/"impedance.tsv",skiprows=1)
    h=np.loadtxt(path/"feedthrough.tsv",skiprows=1)
    w=spice.Waves(path/"waveforms.raw")
    if w.t[-1]<3e-6*(1-1e-6):raise ValueError("truncated LF precharge")
    rows={}
    for i,(alias,_) in enumerate(entries):
        impedance=z[:,1+2*i]+1j*z[:,2+2*i]
        transfer=h[:,1+2*i]+1j*h[:,2+2*i]
        k10=int(np.argmin(abs(z[:,0]-1e4)))
        k20=int(np.argmin(abs(z[:,0]-20e6)))
        ctrl,znode=(w[f"tc{i}"],w[f"tz{i}"]) if not alias.endswith("rcx") else (None,None)
        errors=[float(np.interp(1.99e-6,w.t,node)-target) for node in (ctrl,znode)] if ctrl is not None else None
        rows[alias]=dict(ci_pf=float(-1/(2*np.pi*z[k10,0]*impedance[k10].imag)*1e12),
                        rz_ohm=float(impedance[k20].real), feedthrough=float(abs(transfer[k20])),
                        ac_probe_frequency_hz=float(z[k20,0]), precharge_error_v=errors,
                        precharge_passed=all(abs(e)<=.04 for e in errors) if errors is not None else None,
                        hold_drift_v=[float(np.interp(3e-6,w.t,node)-np.interp(1.99e-6,w.t,node)) for node in (ctrl,znode)] if ctrl is not None else None)
    return rows


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--physical-dir",type=Path,required=True)
    ap.add_argument("--output-dir",type=Path,required=True)
    ap.add_argument("--points",nargs="+",default=POINTS)
    ap.add_argument("--workers",type=int,default=2,choices=(1,2))
    ap.add_argument("--method",choices=("trap","gear"),default="gear")
    ap.add_argument("--kind",choices=("both","ac","precharge"),default="both")
    ap.add_argument("--precharge-ns",type=float,default=2000.)
    ap.add_argument("--hold-ns",type=float,default=1000.)
    a=ap.parse_args();out=a.output_dir.resolve()
    entries=models(a.physical_dir.resolve(),out/"models")
    if a.kind=="precharge":
        release=a.precharge_ns*1e-9;tend=release+a.hold_ns*1e-9
        sample=release-1e-9
        if release<=20e-9 or a.hold_ns<=0:raise ValueError("Precharge must extend beyond supply ramp")
        cases,targets={},{}
        probes=" ".join(f"v(tc{i}) v(tz{i})" for i,(alias,_) in enumerate(entries) if not alias.endswith("rcx"))
        for point in a.points:
            key=point.replace(":","_")
            text,target=deck(point,entries,a.method)
            supply=Condition.parse(point.split(":")[0]).supply
            text=re.sub(r"^Ven_tr .*",f"Ven_tr en_tr 0 PWL(0 0 10n {supply} {release:.12g} {supply} {release+1e-10:.12g} 0)",text,flags=re.M)
            text=re.sub(r"^Xac\d+ .*\n|^Rdc\d+ .*\n|^Iac\d+ .*\n|^Vdd_ac .*\n|^Ven_ac .*\n|^Vref pref .*\n", "",text,flags=re.M)
            control=spice.binary_output(f".control\nset num_threads=1\ntran 2n {tend:.12g} 0 2n\nwrdata waveforms.tsv {probes}\nquit\n.endc")
            text=re.sub(r"\.control.*?\.endc",lambda _:control,text,flags=re.S)
            cases[key]=(text,tend);targets[key]=target
        paths=execute(cases,out,workers=a.workers,timeout_s=300)
        rows={}
        for key,path in paths.items():
            w=spice.Waves(path);row={}
            for i,(alias,_) in enumerate(entries):
                if alias.endswith("rcx"):continue
                values=[w[f"tc{i}"],w[f"tz{i}"]]
                errors=[float(np.interp(sample,w.t,node)-targets[key]) for node in values]
                row[alias]=dict(precharge_error_v=errors,precharge_passed=all(abs(e)<=.04 for e in errors),
                    hold_drift_v=[float(np.interp(tend,w.t,node)-np.interp(sample,w.t,node)) for node in values])
            rows[key]=row
        save_analysis(out,dict(kind=a.kind,scope=__doc__,precharge_ns=a.precharge_ns,hold_ns=a.hold_ns,rows=rows));return
    if a.kind=="ac":
        jobs=[];paths={}
        for point in a.points:
            key=point.replace(":","_");text,_=deck(point,entries,a.method)
            text=re.sub(r"^Xtr\d+ .*\n|^Rpre\d+ .*\n|^\.ic .*\n|^Vdd_tr .*\n|^Ven_tr .*\n|^Vref_tr .*\n|^tran .*\n|^write waveforms.*\n", "",text,flags=re.M)
            text=freeze_includes(text,out);dest=spice.next_run_dir(out,key)
            jobs.append((text,dest,dict(timeout_s=180)));paths[key]=dest
        if len(watch.ngspice_cwds())+a.workers>4:raise RuntimeError("NG quota occupied")
        for start in range(0,len(jobs),a.workers):
            for ex in spice.run_many(jobs[start:start+a.workers],workers=a.workers,smoke=False):
                if not ex.ok:raise RuntimeError(f"AC failed: {ex.run_dir}")
        rows={}
        for key,path in paths.items():
            z=np.loadtxt(path/"impedance.tsv",skiprows=1);h=np.loadtxt(path/"feedthrough.tsv",skiprows=1)
            if z[-1,0]<1e9 or not np.all(np.isfinite(z)) or not np.all(np.isfinite(h)):
                raise ValueError("incomplete LF AC table")
            k10=int(np.argmin(abs(z[:,0]-1e4)));k20=int(np.argmin(abs(z[:,0]-20e6)))
            row={}
            for i,(alias,_) in enumerate(entries):
                row[alias]=dict(ci_pf=float(-1/(2*np.pi*z[k10,0]*z[k10,2+2*i])*1e12),rz_ohm=float(z[k20,1+2*i]),
                    feedthrough=float(abs(h[k20,1+2*i]+1j*h[k20,2+2*i])),probe_frequency_hz=float(z[k20,0]))
            rows[key]=row
        save_analysis(out,dict(kind=a.kind,scope=__doc__,rows=rows));return
    jobs,paths,targets={}, {}, {}
    for point in a.points:
        key=point.replace(":","_")
        text,target=deck(point,entries,a.method)
        text=freeze_includes(text,out)
        targets[key]=target
        old=spice.case_output(out,key,"waveforms.raw",t_end=3e-6)
        if old is None:
            dest=spice.next_run_dir(out,key)
            jobs[key]=(text,dest,dict(timeout_s=900))
        else:dest=old.parent
        paths[key]=dest
    if len(watch.ngspice_cwds())+a.workers>4:raise RuntimeError("NG quota occupied")
    for ex in spice.run_many(list(jobs.values()),workers=a.workers):
        print(ex.run_dir.name,ex.ok,round(ex.elapsed_s,1),flush=True)
        if not ex.ok:raise RuntimeError(f"LF analysis failed: {ex.run_dir}")
    rows={key:measure(path,entries,targets[key]) for key,path in paths.items()}
    save_analysis(out,dict(scope=__doc__,rows=rows))


if __name__=="__main__":main()
