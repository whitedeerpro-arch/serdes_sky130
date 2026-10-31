"""Fit element constraint models for serdes_flow.balance from measured runs (no simulation).

Sources
    v2b retime probe (15 V/T points, PLL r4 taps replayed into the retimed distribution):
        Q   retimer clk->q (serdes_cml_dff_lowov, W20 hold) driving one 24/16/400 buffer
        Qh  the same flip-flop driving a 64/64/100 fan-out buffer (4x the load)
        K   clock buffer 24/16/400 driving one buffer (1G retimer clock has 2 more than 500M's)
        B   fan-out buffer 24/16/400 at its serializer load (post stage)
    PLL r4 native recordings (boundary condition pll_r4_taps@tx_in_v1):
        D   one prescaler /2 stage with its interstage buffer; only the drift is measured
            (taps /2, /4, /8 against the 2G tap), the TT value is an assumption (138 ps).
Assumed: O (fan-out driver) = B; G (CML gate) = B scaled to 40 ps; R tracks Q.

    uv run python analog/tx/clock_distribution/theory/fit_elements.py
writes config/timing_elements.json.
"""
import importlib.util
import json

import numpy as np

from serdes_flow import balance, boundary, spice
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

PROBE = ROOT / "results/analog/tx/serializer/clock_replay/retime/v2b_probe_20261031T121808Z"
BC = "pll_r4_taps@tx_in_v1"
D_TT = 138.0
OUT = ROOT / "config/timing_elements.json"

_spec = importlib.util.spec_from_file_location("clock_replay", ROOT / "analog/tx/serializer/tb/clock_replay/run.py")
replay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay)


def _after(ref, x):
    i = np.searchsorted(ref, x) - 1
    return x[i >= 0] - ref[i[i >= 0]]


def probe_delays(run):
    """Median ps: retimer clock fall after the 2G output rise, clk->q, post buffer; per divided clock."""
    w = spice.Waves(run / "waveforms.raw")
    win = lambda e: e[(e > 15e-9) & (e < 29e-9)]
    ds, pds = crossings(w.t, w["ds"])
    out = {}
    for clk, cvec in (("250", "d250"), ("500", "d500"), ("1g", "d1g")):
        k, pk = crossings(w.t, w[f"v(xclocks.xr{clk}.ckp)"] - w[f"v(xclocks.xr{clk}.ckn)"])
        r, _ = crossings(w.t, w[f"v(xclocks.r{clk}p)"] - w[f"v(xclocks.r{clk}n)"])
        c, _ = crossings(w.t, w[cvec])
        out[clk] = dict(ck=float(np.median(_after(ds[pds > 0], win(k[pk < 0])))) * 1e12,
                        q=float(np.median(_after(k[pk < 0], win(r)))) * 1e12,
                        post=float(np.median(_after(r, win(c)))) * 1e12)
    return out


def divider_drift():
    """Per-point drift of one /2 stage from the native taps (/2 = 1 stage, /4 = 2, /8 = 3), ps vs TT."""
    pts = sorted(boundary.get(BC)["points"])
    rel = {}
    for pt in pts:
        run = boundary.point_run(BC, pt)
        w = spice.Waves(run / "waveforms.raw")
        t0 = json.loads((run / "execution.json").read_text())["settle_s"] + 3e-9
        ref = replay.centroid(w.t, w["v(pb0p)"] - w["v(pb0n)"], 0.5e-9, t0, t0 + 16e-9)
        rel[pt] = {n: (replay.centroid(w.t, w[f"v({p})"] - w[f"v({q})"], per, t0, t0 + 16e-9) - ref) % 0.5e-9
                   for n, (p, q, per) in {1: ("p32p", "p32n", 1e-9), 2: ("p24p", "p24n", 2e-9), 3: ("p08p", "p08n", 4e-9)}.items()}
    tt = rel["tt_v1800_t27"]
    out = {}
    for pt in pts:
        d = np.array([((rel[pt][n] - tt[n] + 0.25e-9) % 0.5e-9 - 0.25e-9) * 1e12 for n in (1, 2, 3)])
        out[pt] = float(np.array([1, 2, 3]) @ d / 14)
    return out


def main():
    runs = {p.name: p / "run" for p in sorted(PROBE.iterdir()) if (p / "run/waveforms.raw").exists()}
    meas = {pt: probe_delays(r) for pt, r in runs.items()}
    series = {
        "Q": ({pt: m["1g"]["q"] for pt, m in meas.items()}, "打拍触发器 clk→q（W20 保持，轻载：一个 24/16/400 buffer）"),
        "Qh": ({pt: m["250"]["q"] for pt, m in meas.items()}, "打拍触发器 clk→q（重载：64/64/100 扇出 buffer）"),
        "K": ({pt: (m["1g"]["ck"] - m["500"]["ck"]) / 2 for pt, m in meas.items()}, "时钟 buffer 24/16/400（轻载）"),
        "B": ({pt: m["1g"]["post"] for pt, m in meas.items()}, "CML buffer 24/16/400（串化器负载）"),
        "D": ({pt: D_TT + x for pt, x in divider_drift().items()}, f"逐级 ÷2 级（预分频 W80 保持 + 级间 buffer）；只测了漂移，TT 取 {D_TT:.0f} ps 假设"),
    }
    lib, prov = {}, {}
    for k, (s, note) in series.items():
        m = balance.fit_element(s, name=k, note=note)
        lib[k] = m
        prov[k] = dict(points=len(s), max_residual_ps=round(balance.fit_residual(m, s), 2))
        print(f"{k:3s} TT {m.tt:6.1f} ps  " + " ".join(f"{p}:{f:.3f}" for p, f in m.factors.items())
              + f"  alpha {m.alpha:+.4f} beta {m.beta:+.4f}  max residual {prov[k]['max_residual_ps']} ps")
    b = lib["B"]
    lib["O"] = balance.ElementModel("O", b.tt, b.factors, b.alpha, b.beta, note="扇出驱动级（按 B）")
    lib["G"] = balance.ElementModel("G", 40.0, b.factors, b.alpha, b.beta, note="CML 逻辑门（XOR/AND），按 B 的工艺/V/T 行为，TT 40 ps 假设")
    q = lib["Q"]
    lib["R"] = balance.ElementModel("R", q.tt, q.factors, q.alpha, q.beta, track="Q", note="2G clk→q 复制单元，设计上跟踪 Q")
    OUT.write_text(json.dumps(dict(
        model="delay = tt x factors[process] x (1 + alpha*v + beta*t); v = (VDD-1.8)/0.15, t = (T-22.5)/62.5",
        sources=dict(probe=str(PROBE.relative_to(ROOT)), boundary_condition=BC, fit=prov),
        elements={k: dict(name=m.name, tt=round(m.tt, 2), factors={p: round(f, 4) for p, f in m.factors.items()},
                          alpha=round(m.alpha, 5), beta=round(m.beta, 5), track=m.track, note=m.note)
                  for k, m in lib.items()}), indent=1, ensure_ascii=False) + "\n")
    print(OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
