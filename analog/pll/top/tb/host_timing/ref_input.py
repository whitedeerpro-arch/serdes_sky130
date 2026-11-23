"""Host sensitivity of the reference input path as it would be built: pad buffer -> CML stage -> feedback-type receiver.

    uv run python analog/pll/top/tb/host_timing/ref_input.py [--points ...] [--workers 1] [--resume C]

The replica study (ref_replica.py) drove the CML stage with ideal complementary edges whose swing followed the host.
On chip the 250 MHz reference arrives from the board on one pin: modelled as an ideal 0..1.8 V edge, 100 ps, NOT
following the host.  Variants in one deck (all host cells on vh, CML bias on the perturbed vbias as host_timing):
  rep    the replica of ref_replica.py (complementary ideal edges at 0..vh, CML stage, CL 170 fF, receiver) - baseline
  pad    pad buffer sky130_fd_sc_hd inv_2 -> inv_4 on vh, CML stage single-ended (other gate at vh / 2 from a 2 x 20 kOhm
         divider with 1 pF), CL 170 fF, receiver
  pad85  as pad with CL 85 fF (if the pad buffer over-balances)
  padc   pad buffer, then complementary CMOS into the CML stage: pn = inv_4(pad), pp = inv_4(pn) (pp one inverter
         late), CL 170 fF.  Result of 2026-11-12 for `pad`: residual -0.90 ps/mV at FS 1.65 V -40 C hh (rep -0.18):
         with one gate at vh / 2 the low-side tail runs out of headroom, so the stage's delay follows vh differently
  padc85 as padc with CL 85 fF
Each receiver output loaded as the feedback one (20 fF + a PFD input).  Kd = d(receiver output rise at vh / 2 - external
edge at 0.9 V) / dV.  Residual against the feedback path (host_timing campaigns): Kd_fb - Kd_ref.
"""
import argparse
import importlib.util
import json
import time

import numpy as np

from serdes_flow import bias, rcorner, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

_h = importlib.util.spec_from_file_location("host_timing", ROOT / "analog/pll/top/tb/host_timing/run.py")
ht = importlib.util.module_from_spec(_h)
_h.loader.exec_module(ht)
_r = importlib.util.spec_from_file_location("ref_replica", ROOT / "analog/pll/top/tb/host_timing/ref_replica.py")
rr = importlib.util.module_from_spec(_r)
_r.loader.exec_module(rr)
RESULTS = ROOT / "results/analog/pll/top/host_timing_ref_input"
SC_LIB = "/home/host/.volare/sky130A/libs.ref/sky130_fd_sc_hd/spice/sky130_fd_sc_hd.spice"
VARIANTS = ("rep", "pad", "pad85", "padc", "padc85")
TR_EXT = 100e-12


def deck(c, rc, a, camp):
    lines = ["Reference input path: pad buffer -> CML stage -> receiver, host sensitivity",
             f'.lib "{spice.corner_values(c)["MODEL_LIBRARY"]}" {c.process}']
    lines += [f'.include "{ROOT / p}"' for p in rr.INCLUDES] + [f'.include "{SC_LIB}"']
    lines += [f".param supply={c.supply}", "Vdd vdd 0 {supply}", "Vh vh 0 {supply}",
              "Iref vdd vbias .85m", "Xref vbias vbias 0 0 serdes_nfet w=20 l=.5 nf=4", "Vdb vbfe vbias 0",
              # replica drive (as ref_replica): complementary, swing follows vh
              f"Vrefi refi 0 PULSE(0 1 2n {rr.TR:.1e} {rr.TR:.1e} {rr.TREF / 2 - rr.TR:.4e} {rr.TREF:.4e})",
              "Bref refp 0 V=v(refi)*v(vh)", "Brefn refn 0 V=(1-v(refi))*v(vh)",
              # external board clock: fixed 0..1.8 V
              f"Vext ext 0 PULSE(0 1.8 2n {TR_EXT:.1e} {TR_EXT:.1e} {rr.TREF / 2 - TR_EXT:.4e} {rr.TREF:.4e})",
              "Xpb1 ext 0 0 vh vh pb1 sky130_fd_sc_hd__inv_2", "Xpb2 pb1 0 0 vh vh pad sky130_fd_sc_hd__inv_4",
              "Rd1 vh vmid 20k", "Rd2 vmid 0 20k", "Cmid vmid 0 1p",
              "Xpc1 pad 0 0 vh vh pcn sky130_fd_sc_hd__inv_4", "Xpc2 pcn 0 0 vh vh pcp sky130_fd_sc_hd__inv_4",
              f"Vfbi fbi 0 PULSE(0 1 {2e-9 + rr.TREF / 2:.4e} {rr.TR:.1e} {rr.TR:.1e} {rr.TREF / 2 - rr.TR:.4e} {rr.TREF:.4e})",
              "Bfb fbx 0 V=v(fbi)*v(vh)", "Erst rst_b 0 vh 0 1"]
    drive = {"rep": ("refp", "refn", 170e-15), "pad": ("pad", "vmid", 170e-15), "pad85": ("pad", "vmid", 85e-15),
             "padc": ("pcp", "pcn", 170e-15), "padc85": ("pcp", "pcn", 85e-15)}
    for k, var in enumerate(VARIANTS):
        ip, inn, cl = drive[var]
        lines += [f"Xb{k} {ip} {inn} c{k}p c{k}n vbfe vh 0 serdes_cml_buffer wn=12 nfin=4 wt={a.wt} rload=600",
                  f"Cl{k}p c{k}p 0 {cl:.4g}", f"Cl{k}n c{k}n 0 {cl:.4g}",
                  f"Xr{k} c{k}p c{k}n o{k} o{k}n vbfe vh 0 serdes_cml_to_cmos_pvt_candidate", f"Co{k} o{k} 0 20f", f"Co{k}n o{k}n 0 20f",
                  f"Xp{k} o{k} fbx rst_b up{k} dn{k} vh 0 pll_pfd",
                  f".nodeset v(xr{k}.xrestore.qp)=0 v(xr{k}.xrestore.qn)={{supply}}"]
    probes = "v(refp) v(ext) " + " ".join(f"v(o{k})" for k in range(len(VARIANTS)))
    lines += [f".temp {c.temp}", ".options reltol=1e-4 abstol=1p vntol=1u", f".save {probes}", ".control", "set num_threads=1"]
    for name, dh, db in ht.runs(a):
        lines += [f"alter Vh dc={c.supply + dh:.4f}", f"alter Vdb dc={db:.4f}",
                  f"tran 2p {a.stop:.4e} {a.stop / 3:.4e} 2p", f"wrdata {name}.tsv {probes}", "destroy all"]
    lines += ["quit", ".endc", ".end"]
    text = bias.real(spice.binary_output("\n".join(lines) + "\n"))
    return bias.section(rcorner.to_pdk(text, camp), c.process, rc)


def measure(path, vh, stop):
    w = spice.Waves(path)
    t = w.t
    late = t > stop / 2
    t = t[late]
    out = []
    for k, var in enumerate(VARIANTS):
        ref = ht.crossings(t, w["v(refp)"][late], vh / 2) if var == "rep" else ht.crossings(t, w["v(ext)"][late], 0.9)
        o = ht.crossings(t, w[f"v(o{k})"][late], vh / 2)
        d = ht.after(o, ref)
        d = d[np.isfinite(d) & (d < 3e-9)]
        out.append(float(np.median(d)) if len(d) else float("nan"))
    return out


def main():
    global VARIANTS
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="ss_v1650_t-40:hh,fs_v1650_t-40:hh,ss_v1650_t85:hh,fs_v1650_t85:hh,sf_v1650_t85:hh,"
                                        "tt_v1800_t27:tt,fs_v1950_t-40:hh")
    ap.add_argument("--variants", help="subset of " + ",".join(VARIANTS))
    ap.add_argument("--wt", type=float, default=11.0)
    ap.add_argument("--dh", type=float, default=0.02)
    ap.add_argument("--db", type=float, default=0.005)
    ap.add_argument("--stop", type=float, default=24e-9)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--fb", default="results/analog/pll/top/host_timing/20261111T061902Z,results/analog/pll/top/host_timing/20261111T091746Z")
    ap.add_argument("--resume")
    a = ap.parse_args()
    if a.variants:
        VARIANTS = tuple(a.variants.split(","))
    camp = ROOT / a.resume if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    specs = a.points.split(",")
    jobs = []
    for spec in specs:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        d = camp / spec.replace(":", "_")
        if spice.case_output(d, "run", "bm.raw", a.stop) is not None:
            continue
        jobs.append((deck(c, rc, a, camp / "snap"), spice.next_run_dir(d, "run"), dict(timeout_s=3600, meta=dict(point=spec, variants=VARIANTS))))
    for ex in spice.run_many(jobs, workers=a.workers):
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures[:2]}", flush=True)
    fb = {}
    for cmp in a.fb.split(","):
        fb.update(json.loads((ROOT / cmp / "summary.json").read_text())["rows"])
    rows = {}
    print("Kd ps/mV host / per mV vbias; residual = feedback path - reference path")
    for spec in specs:
        cond, rc = spec.split(":")
        c = Condition.parse(cond)
        d = camp / spec.replace(":", "_")
        m = {}
        for name, dh, db in ht.runs(a):
            p = spice.case_output(d, "run", f"{name}.raw", a.stop)
            if p is None:
                break
            m[name] = measure(p, c.supply + dh, a.stop)
        if len(m) < 5:
            print(f"{spec}: missing")
            continue
        f = fb.get(spec, {})
        row = dict(delay_s=dict(zip(VARIANTS, m["base"])), kd_fb_h=f.get("kd_h"), kd_fb_b=f.get("kd_b"))
        line = f"{spec:18s} fb {f.get('kd_h', np.nan) * 1e9:+.2f}/{f.get('kd_b', np.nan) * 1e9:+.2f} |"
        for k, var in enumerate(VARIANTS):
            kh = (m["hp"][k] - m["hm"][k]) / (2 * a.dh)
            kb = (m["bp"][k] - m["bm"][k]) / (2 * a.db)
            row[var] = dict(kd_h=kh, kd_b=kb, resid_h=f.get("kd_h", np.nan) - kh, resid_b=f.get("kd_b", np.nan) - kb)
            line += f" {var}: {kh * 1e9:+.2f}/{kb * 1e9:+.2f} resid {row[var]['resid_h'] * 1e9:+.2f}/{row[var]['resid_b'] * 1e9:+.2f} |"
        rows[spec] = row
        print(line, flush=True)
    camp.mkdir(parents=True, exist_ok=True)
    (camp / "summary.json").write_text(json.dumps(dict(args=vars(a), variants=VARIANTS, rows=rows), indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
