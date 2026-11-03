"""RX sampler input offset and clock phase / duty errors from local mismatch (Monte Carlo).

    uv run python analog/rx/sampler/tb/offset_mc/run.py [--samples 200] [--cond tt_v1800_t27] [--seed 1]
        [--pdk-r] [--dut ac|ac_trim|ac_cal] [--ramp-mv 25] [--code 32 | --codes CODES.json]

serdes_rx_half_rate_samples_ac (input buffer, AC-coupled clock interface c2, four sample DFFs) with
ideal PI-like 2 GHz clocks and a slow differential input ramp (-25 -> +25 mV over 40 ns, 0.625 mV per
lane decision).  Per sample (library section <corner>_mm, serdes_flow.mc):
  offset   for each lane d0 d1 e0 e1 the first rising zero crossing of its output after 6 ns; the
           input-referred offset is the ramp slope times the delay against the same crossing without
           mismatch (section <corner>), so the common latency cancels.  It includes the shared input
           buffer, so the four lanes are correlated.
  clocks   rising / falling zero crossings of the gate clocks cd (D lanes) and ce (E lanes) after
           20 ns: duty error of cd and ce, and the cd -> ce spacing error against 125 ps.
Budget context: the sampler gate is a signed eye margin >= 75 mV at the sampling instant (C2 replay);
every lane's offset subtracts from it (series criterion: each of the four samplers must pass).

Trimmed blocks (--dut ac_trim / ac_cal, analog/rx/sampler/spice/rx_offset_trim.spice / rx_offset_dac.spice):
every lane at --code, or per sample and lane from --codes (JSON {"d0": [codes of samples 0..N-1], ...},
applied inside the MC loop with alter, so sample k gets its own code; the mismatch of sample k is fixed
by (seed, k), serdes_flow.mc).  The offset is then the residual threshold: the reference crossing is
the mean of the mismatch-free block at codes 31 and 32 (+-0.5 LSB around zero trim).  --ramp-mv widens
the ramp (same 1.25 mV/ns, longer run) for offsets beyond +-25 mV.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import mc, rcorner, spice, stats
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_rx_sampler_offset_mc_ngspice.cir.in"
RESULTS = ROOT / "results/analog/rx/sampler/offset_mc"
SLOPE = 0.05 / 40e-9                      # V/s of the differential ramp
LANES = ("d0", "d1", "e0", "e1")
UI = 250e-12


VARIANTS = {"ac": ("serdes_rx_half_rate_samples_ac", []),
            "ac_cal": ("serdes_rx_half_rate_samples_ac_cal", ["rx_offset_dac.spice"]),
            "ac_trim": ("serdes_rx_half_rate_samples_ac_trim", ["rx_offset_dac.spice", "rx_offset_trim.spice"])}
CAL_NODES = [f"{l}b{k}" for l in LANES for k in range(6)]
RAMP_T0 = 5e-9


def ramp_stop(ramp_mv):
    return RAMP_T0 + 2 * ramp_mv * 1e-3 / SLOPE + 1e-9


def netlist(c, section, dut="ac", ramp_mv=25.0, code=None, hold=(), hold_code=63):
    """Bench deck; trimmed variants get their code nodes and sources (all lanes at `code`, altered
    per sample by the analysis when codes come from a file)."""
    vals = spice.corner_values(c)
    vals["SECTION"] = section
    text = spice.render(TEMPLATE, **vals)
    sub, incs = VARIANTS[dut]
    a = ramp_mv * 1e-3
    old_ramp = "Vramp ramp 0 PWL(0 -0.025 5n -0.025 45n 0.025)"
    old_dut = "Xdut ip in dp dn ep en d0p d0n d1p d1n e0p e0n e1p e1n vbias vdd 0 serdes_rx_half_rate_samples_ac rb=2k"
    assert text.count(old_ramp) == 1 and text.count(old_dut) == 1
    text = text.replace(old_ramp, f"Vramp ramp 0 PWL(0 {-a} {RAMP_T0:.4e} {-a} {RAMP_T0 + 2 * a / SLOPE:.4e} {a})")
    if incs:
        text = text.replace(old_dut, old_dut.replace("serdes_rx_half_rate_samples_ac rb=2k", " ".join(CAL_NODES) + f" {sub} rb=2k"))
        inc_line = f'.include "{ROOT}/analog/rx/sampler/spice/rx_half_rate_samples_ac.spice"'
        assert text.count(inc_line) == 1
        text = text.replace(inc_line, inc_line + "".join(f'\n.include "{ROOT}/analog/rx/sampler/spice/{f}"' for f in incs))
        code = 32 if code is None else code
        cc = lambda n: hold_code if n[:2] in hold else code
        text += "\n" + "\n".join(f"Vc{n} {n} 0 dc {c.supply * ((cc(n) >> int(n[-1])) & 1)}" for n in CAL_NODES)
    saves = ".save " + " ".join(f"v({l}p) v({l}n)" for l in LANES) + " v(xdut.cdp) v(xdut.cdn) v(xdut.cep) v(xdut.cen)"
    return text + "\n" + saves


def code_setup(codes, lo, n, hold=()):
    """compose per-lane code vectors for samples lo .. lo+n-1 of a chunk (indexed by mc_k)."""
    return "\n".join(f"compose cl_{l} values " + " ".join(str(int(x)) for x in codes[l][lo:lo + n]) for l in LANES if l not in hold)


def code_alters(supply, hold=()):
    out = []
    for l in LANES:
        if l in hold:
            continue
        for k in range(6):
            out += [f"let cb = (floor(cl_{l}[mc_k] / {2 ** k}) - 2 * floor(cl_{l}[mc_k] / {2 ** (k + 1)})) * {supply}",
                    f"alter vc{l}b{k} dc=$&cb"]
    return out


def analysis(ramp_mv=25.0, alters=()):
    # control-mode meas takes vector names, not v(a,b): form the differences first
    lines = list(alters) + [f"tran 2p {ramp_stop(ramp_mv):.4e} 0 4p"] + [f"let s_{l} = v({l}p) - v({l}n)" for l in LANES]
    lines += ["let s_cd = v(xdut.cdp) - v(xdut.cdn)", "let s_ce = v(xdut.cep) - v(xdut.cen)"]
    lines += [f"meas tran t_{l} when s_{l}=0 rise=1 from=6n" for l in LANES]
    lines += ["meas tran cd_r when s_cd=0 rise=1 from=20n", "meas tran cd_f when s_cd=0 fall=1 from=20n",
              "meas tran ce_r when s_ce=0 rise=1 from=20n", "meas tran ce_f when s_ce=0 fall=1 from=20n"]
    return "\n".join(lines)


LETS = {f"t_{l}": f"t_{l}" for l in LANES} | {k: k for k in ("cd_r", "cd_f", "ce_r", "ce_f")}


def run(c, section, samples, seed, d, workers=4, pdk_r=False, dut="ac", ramp_mv=25.0, code=None, codes=None, per=50, hold=()):
    """samples split into chunks of 50 (one ngspice each, see serdes_flow.mc), run in parallel.
    pdk_r: the cells' ideal resistors become high_po devices (their mismatch enters, serdes_flow.rcorner).
    codes: per-lane lists of per-sample trim codes (sample index over the whole run)."""
    parts = mc.chunks(samples, seed, per)
    net = netlist(c, section, dut, ramp_mv, code, hold)
    if pdk_r:
        net = rcorner.to_pdk(net, d.parent)
    jobs = []
    lo = 0
    for k, s, n in parts:
        setup = code_setup(codes, lo, n, hold) if codes else ""
        ana = analysis(ramp_mv, code_alters(c.supply, hold) if codes else ())
        jobs.append((mc.deck(net, n, seed=s, analysis=ana, lets=LETS, setup=setup), d / f"chunk{k:02d}",
                     dict(timeout_s=max(600, int(n * 60 * ramp_stop(ramp_mv) / 46e-9)),
                          meta=dict(condition=c.tag, section=section, samples=n, seed=s, dut=dut, code=code,
                                    per_sample_codes=bool(codes)))))
        lo += n
    t0 = time.time()
    # --reuse: chunks already run (execution.json present) are read back, not rerun
    spice.run_many([j for j in jobs if not (j[1] / "execution.json").exists()], workers=workers, smoke=False)
    # sample index = chunk start + index in the chunk: a chunk that stops early (ngspice memory cap)
    # leaves NaN rows, so per-sample codes and paired runs stay aligned
    rows = []
    for (k, s, n), (_, rd, _) in zip(parts, jobs):
        got = mc.read(rd) if (rd / mc.MC_FILE).exists() else []
        rows += got[:n] + [{key: float("nan") for key in LETS}] * (n - len(got))
    if not any(np.isfinite(r["t_d0"]) for r in rows):
        raise SystemExit(f"no MC rows in {d}")
    return rows, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pdk-r", action="store_true", help="cell resistors as high_po devices (their mismatch included)")
    ap.add_argument("--dut", choices=sorted(VARIANTS), default="ac")
    ap.add_argument("--ramp-mv", type=float, default=25.0)
    ap.add_argument("--code", type=int, help="trimmed variants: code of every lane (default 32)")
    ap.add_argument("--codes", help="trimmed variants: JSON with per-lane per-sample codes")
    ap.add_argument("--hold", help="trimmed variants: lanes held at code 63 (threshold beyond the ramp, they never flip), e.g. d1,e0,e1: "
                    "isolates the measured lanes from the kickback of lanes deciding near the same input")
    ap.add_argument("--reuse", help="campaign directory: analyse its finished runs again (same options), run only what is missing")
    ap.add_argument("--chunk", type=int, default=50, help="samples per ngspice (the sample set depends on it: keep it equal for paired runs)")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    trimmed = a.dut != "ac"
    codes = json.loads(Path(a.codes).read_text()) if a.codes else None
    camp = (ROOT / a.reuse) if a.reuse else RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ("_pdkr" if a.pdk_r else "")
                                                         + (f"_{a.dut}" if trimmed else "") + ("_cal" if codes else ""))
    hold = tuple(a.hold.split(",")) if a.hold else ()
    kw = dict(pdk_r=a.pdk_r, dut=a.dut, ramp_mv=a.ramp_mv, hold=hold)
    if trimmed and (codes or a.code is None):
        # zero-trim reference: mismatch-free block at codes 31 and 32 (+-0.5 LSB)
        n31, _ = run(c, c.process, 1, a.seed, camp / "nominal31", code=31, **kw)
        n32, _ = run(c, c.process, 1, a.seed, camp / "nominal32", code=32, **kw)
        nom = [{k: (n31[0][k] + n32[0][k]) / 2 for k in n31[0]}]
    else:
        nom, _ = run(c, c.process, 1, a.seed, camp / "nominal", code=a.code, **kw)
    rows, elapsed = run(c, f"{c.process}_mm", a.samples, a.seed, camp / "mc", a.workers, code=a.code, codes=codes, per=a.chunk, **kw)
    n0 = nom[0]
    col = lambda k: mc.column(rows, k)
    out = dict(condition=c.tag, pdk_resistors=a.pdk_r, samples=len(rows), seed=a.seed, slope_v_per_s=SLOPE, nominal=n0,
               dut=a.dut, ramp_mv=a.ramp_mv, code=a.code, codes_file=a.codes, chunk=a.chunk, hold=list(hold), lanes={}, clocks={})
    print(f"{c.tag}: {sum(np.isfinite(r['t_d0']) for r in rows)} of {len(rows)} samples in {elapsed:.0f} s; nominal crossings " + " ".join(f"{l} {n0[f't_{l}'] * 1e9:.3f} ns" for l in LANES))
    offs = {}
    lanes = [l for l in LANES if l not in hold]          # held lanes never cross the ramp
    for l in LANES:
        off = (col(f"t_{l}") - n0[f"t_{l}"]) * SLOPE * 1e3
        ok = np.isfinite(off)
        offs[l] = off
        if l in hold:
            continue
        s = stats.summary(off[ok])
        lo, hi = stats.tolerance(off[ok])
        out["lanes"][l] = dict(s, missing=int((~ok).sum()), tol3_mv=[lo, hi])
        print(f"  offset {l}: mean {s['mean']:+.2f} sigma {s['std']:.2f} mV  (3-sigma tolerance {lo:+.1f}..{hi:+.1f} mV, skew {s['skew']:+.2f}, missing {int((~ok).sum())})")
    out["offsets_mv"] = {l: [None if not np.isfinite(x) else float(x) for x in offs[l]] for l in LANES}   # per sample
    worst = np.nanmax(np.abs(np.vstack([offs[l] for l in lanes])), axis=0)
    out["worst_lane_abs_mv"] = stats.summary(worst[np.isfinite(worst)])
    if len(lanes) > 1:
        stack = np.vstack([offs[l] for l in lanes])
        corr = np.corrcoef(stack[:, np.isfinite(stack).all(axis=0)])
        out["lane_correlation"] = corr.tolist()
        print(f"  worst of {len(lanes)} per sample |offset|: mean {np.nanmean(worst):.2f}, 99.7th pct {np.nanpercentile(worst, 99.7):.1f} mV; "
              f"lane correlation {np.mean(corr[np.triu_indices(len(lanes), 1)]):.2f}")
    duty = lambda r, f: ((col(f) - col(r)) % (2 * UI)) / (2 * UI)
    for name, (r, f) in (("cd", ("cd_r", "cd_f")), ("ce", ("ce_r", "ce_f"))):
        dc = duty(r, f) - (((n0[f] - n0[r]) % (2 * UI)) / (2 * UI))
        s = stats.summary(dc[np.isfinite(dc)] * 2 * UI * 1e12)
        out["clocks"][f"{name}_duty_error_ps"] = s
        print(f"  {name} duty error vs nominal: sigma {s['std']:.2f} ps (mean {s['mean']:+.2f})")
    sp = ((col("ce_r") - col("cd_r")) % (2 * UI)) - ((n0["ce_r"] - n0["cd_r"]) % (2 * UI))
    s = stats.summary(sp[np.isfinite(sp)] * 1e12)
    out["clocks"]["d_to_e_spacing_error_ps"] = s
    print(f"  D->E clock spacing error vs nominal: sigma {s['std']:.2f} ps (nominal {((n0['ce_r'] - n0['cd_r']) % (2 * UI)) * 1e12:.1f} ps)")
    (camp / "summary.json").write_text(json.dumps(out, indent=1))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
