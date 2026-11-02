"""RX sampler input offset and clock phase / duty errors from local mismatch (Monte Carlo).

    uv run python analog/rx/sampler/tb/offset_mc/run.py [--samples 200] [--cond tt_v1800_t27] [--seed 1]

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


def netlist(c, section):
    vals = spice.corner_values(c)
    vals["SECTION"] = section
    text = spice.render(TEMPLATE.read_text().replace("@SECTION@", "@SECTION@"), **vals)
    saves = ".save " + " ".join(f"v({l}p) v({l}n)" for l in LANES) + " v(xdut.cdp) v(xdut.cdn) v(xdut.cep) v(xdut.cen)"
    return text + "\n" + saves


def analysis():
    # control-mode meas takes vector names, not v(a,b): form the differences first
    lines = ["tran 2p 46n 0 4p"] + [f"let s_{l} = v({l}p) - v({l}n)" for l in LANES]
    lines += ["let s_cd = v(xdut.cdp) - v(xdut.cdn)", "let s_ce = v(xdut.cep) - v(xdut.cen)"]
    lines += [f"meas tran t_{l} when s_{l}=0 rise=1 from=6n" for l in LANES]
    lines += ["meas tran cd_r when s_cd=0 rise=1 from=20n", "meas tran cd_f when s_cd=0 fall=1 from=20n",
              "meas tran ce_r when s_ce=0 rise=1 from=20n", "meas tran ce_f when s_ce=0 fall=1 from=20n"]
    return "\n".join(lines)


LETS = {f"t_{l}": f"t_{l}" for l in LANES} | {k: k for k in ("cd_r", "cd_f", "ce_r", "ce_f")}


def run(c, section, samples, seed, d, workers=4, pdk_r=False):
    """samples split into chunks of 50 (one ngspice each, see serdes_flow.mc), run in parallel.
    pdk_r: the cells' ideal resistors become high_po devices (their mismatch enters, serdes_flow.rcorner)."""
    parts = mc.chunks(samples, seed)
    net = netlist(c, section)
    if pdk_r:
        net = rcorner.to_pdk(net, d.parent)
    jobs = [(mc.deck(net, n, seed=s, analysis=analysis(), lets=LETS), d / f"chunk{k:02d}",
             dict(timeout_s=max(600, n * 60), meta=dict(condition=c.tag, section=section, samples=n, seed=s)))
            for k, s, n in parts]
    t0 = time.time()
    spice.run_many(jobs, workers=workers, smoke=False)
    rows = mc.read_all([j[1] for j in jobs])
    if not rows:
        raise SystemExit(f"no MC rows in {d}")
    return rows, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--cond", default="tt_v1800_t27")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--pdk-r", action="store_true", help="cell resistors as high_po devices (their mismatch included)")
    a = ap.parse_args()
    c = Condition.parse(a.cond)
    camp = RESULTS / (time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ("_pdkr" if a.pdk_r else ""))
    nom, _ = run(c, c.process, 1, a.seed, camp / "nominal", pdk_r=a.pdk_r)
    rows, elapsed = run(c, f"{c.process}_mm", a.samples, a.seed, camp / "mc", a.workers, pdk_r=a.pdk_r)
    n0 = nom[0]
    col = lambda k: mc.column(rows, k)
    out = dict(condition=c.tag, pdk_resistors=a.pdk_r, samples=len(rows), seed=a.seed, slope_v_per_s=SLOPE, nominal=n0, lanes={}, clocks={})
    print(f"{c.tag}: {len(rows)} samples in {elapsed:.0f} s; nominal crossings " + " ".join(f"{l} {n0[f't_{l}'] * 1e9:.3f} ns" for l in LANES))
    offs = {}
    for l in LANES:
        off = (col(f"t_{l}") - n0[f"t_{l}"]) * SLOPE * 1e3
        ok = np.isfinite(off)
        offs[l] = off
        s = stats.summary(off[ok])
        lo, hi = stats.tolerance(off[ok])
        out["lanes"][l] = dict(s, missing=int((~ok).sum()), tol3_mv=[lo, hi])
        print(f"  offset {l}: mean {s['mean']:+.2f} sigma {s['std']:.2f} mV  (3-sigma tolerance {lo:+.1f}..{hi:+.1f} mV, skew {s['skew']:+.2f}, missing {int((~ok).sum())})")
    allo = np.concatenate([offs[l] for l in LANES])
    allo = allo[np.isfinite(allo)]
    worst = np.nanmax(np.abs(np.vstack([offs[l] for l in LANES])), axis=0)
    out["worst_lane_abs_mv"] = stats.summary(worst[np.isfinite(worst)])
    corr = np.corrcoef(np.vstack([offs[l] for l in LANES]))
    out["lane_correlation"] = corr.tolist()
    print(f"  worst of four per sample |offset|: mean {np.nanmean(worst):.2f}, 99.7th pct {np.nanpercentile(worst, 99.7):.1f} mV; lane correlation {np.mean(corr[np.triu_indices(4, 1)]):.2f}")
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
