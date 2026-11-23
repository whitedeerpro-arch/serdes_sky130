"""TX select-clock structures compared with serdes_flow.balance (no simulation).

Six ways to build the 250M / 500M / 1G / 2G select clocks of the 16:1 tree from
the 2 GHz four-phase VCO (8 taps, 62.5 ps = 0.25 UI apart).  Element models come
from config/timing_elements.json.  Serializer windows (zero-delay tree model):
    comb     combinational mux ranks: every adjacent pair +-(0.5 - w/2) UI, period 1 UI
             (whole-UI offsets only permute bits, which the remap handles)
    latched  latched boundaries: 1G-2G / 500M-1G / 250M-500M periods 1 / 2 / 4 UI
Target offsets 0.162 / 0.158 / 0.662 UI are the r2 ideal-source placement.

    uv run python analog/tx/clock_distribution/theory/clock_structures.py [--tree comb|latched|both] [--w 0.5]
"""
import argparse
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import balance as bl
from serdes_flow.balance import Budget, Fixed, Inst, Knob, KnobSpec, Sample, Skew, Structure
from serdes_flow.corners import PROCESS
from serdes_flow.project import ROOT

UI, T2G, STEP = 250.0, 500.0, 62.5
RESULTS = ROOT / "results/analog/tx/clock_distribution/clock_theory"
NAME = {"c250": "250M", "c500": "500M", "c1g": "1G", "c2g": "2G"}
PAIRS = (("c250", "c500", 0.162, 4), ("c500", "c1g", 0.158, 2), ("c1g", "c2g", 0.662, 1))


def ph(k):
    return Fixed(k * STEP, tap=f"phi{k}")


def I(t, i):
    return Inst(t, i)


def K(n):
    return Knob(n)


DELAY_B = KnobSpec("delay", tuple(range(0, 251, 10)), type="B")
DELAY_K = KnobSpec("delay", tuple(range(0, 251, 10)), type="K")
INVERT = KnobSpec("fixed", (0, 4), unit=STEP)
PHASE = KnobSpec("fixed", tuple(range(8)), unit=STEP, tap=True)
STAGES = KnobSpec("stages", (0, 1, 2), type="B")
NONE = KnobSpec("stages", (0,), type="B")


def skews(tree, w):
    out = []
    for a, b, tgt, lp in PAIRS:
        per = lp if tree == "latched" else 1
        out.append(Skew(a, b, tgt * UI, per * UI, (per / 2 - w / 2) * UI, owner=b, label=f"{NAME[a]}→{NAME[b]}"))
    return out


def retime(clk, setup, hold):
    return Sample(f"d{clk}", f"k{clk}", T2G, setup, hold, owner=f"c{clk}", offset=T2G / 2, label=f"{NAME['c' + clk]} 打拍器")


def structures(tree="comb", w=0.5, setup=130.0, hold=40.0, counter_setup=80.0):
    sk = skews(tree, w)
    order = ["c250", "c500", "c1g", "c2g"]
    ripple = {"d250": [ph(0), I("B", "br0"), I("D", "d1"), I("D", "d2"), I("D", "d3"), I("B", "pre250")],
              "d500": [ph(0), I("B", "br0"), I("D", "d1"), I("D", "d2"), I("B", "pre500")],
              "d1g": [ph(0), I("B", "br0"), I("D", "d1"), I("B", "pre1g")]}
    trims = {"k500": DELAY_B, "k1g": DELAY_B, "k2g": DELAY_B}
    S = []
    S.append(Structure("S0", "现状：三支路独立预分频", {
        "c250": [ph(0), I("B", "br0"), I("D", "p0a"), I("D", "p0b"), I("D", "p0c"), I("B", "t250"), I("O", "o250")],
        "c500": [ph(2), I("B", "br2"), I("D", "p2a"), I("D", "p2b"), I("B", "t500"), K("k500"), I("O", "o500")],
        "c1g": [ph(3), I("B", "br3"), I("D", "p3a"), I("B", "t1g"), K("k1g"), I("O", "o1g")],
        "c2g": [ph(4), I("B", "br0"), I("B", "t2g"), I("B", "x2a"), I("B", "x2b"), K("k2g"), I("O", "o2g")]},
        trims, sk, order, dict(start_states=8, note="b0/b2/b3 支路各一条预分频（÷8/÷4/÷2），2G 取 b0 反相；分发每路 trim 级 + 扇出，2G 多两级")))
    S.append(Structure("S1", "单链逐级 ÷2", {
        "c250": [ph(0), I("B", "br0"), I("D", "d1"), I("D", "d2"), I("D", "d3"), I("B", "t250"), I("O", "o250")],
        "c500": [ph(0), I("B", "br0"), I("D", "d1"), I("D", "d2"), I("B", "t500"), K("k500"), I("O", "o500")],
        "c1g": [ph(0), I("B", "br0"), I("D", "d1"), I("B", "t1g"), K("k1g"), I("O", "o1g")],
        "c2g": [ph(4), I("B", "br0"), I("B", "t2g"), K("k2g"), I("O", "o2g")]},
        trims, sk, order, dict(start_states=1, note="一条 ÷2→÷2→÷2 链，后级由前级输出驱动；各抽头关系固定")))
    spine = [ph(0), I("B", "br0"), I("B", "s1"), I("B", "s2")]
    S.append(Structure("S2", "单链 + 2G 主干打拍（v2b 型）", {
        **{f"k{c}": spine + [K(f"i{c}"), K(f"k{c}")] for c in ("250", "500", "1g")},
        **{f"c{c}": spine + [K(f"i{c}"), K(f"k{c}"), I("Q", f"q{c}"), I("O", f"o{c}")] for c in ("250", "500", "1g")},
        "c2g": [ph(4), I("B", "br0"), I("B", "s1"), K("k2g"), I("O", "o2g")], **ripple},
        {**{f"i{c}": INVERT for c in ("250", "500", "1g")}, **{f"k{c}": DELAY_K for c in ("250", "500", "1g")}, "k2g": DELAY_B},
        sk + [retime(c, setup, hold) for c in ("250", "500", "1g")], order,
        dict(start_states=1, note="÷2 链抽头在 2G buffer 主干上打拍（反相 + 时钟 buffer 对中）；2G 直接输出，不经 clk→q")))
    S.append(Structure("S3", "单链 + VCO 相位打拍 + 2G 复制", {
        **{f"k{c}": [K(f"j{c}"), I("B", f"brj{c}")] for c in ("250", "500", "1g")},
        **{f"c{c}": [K(f"j{c}"), I("B", f"brj{c}"), I("Q", f"q{c}"), K(f"e{c}"), I("O", f"o{c}")] for c in ("250", "500", "1g")},
        "c2g": [K("j2g"), I("B", "brj2g"), I("R", "r2g"), K("e2g"), I("O", "o2g")], **ripple},
        {**{f"j{c}": PHASE for c in ("250", "500", "1g", "2g")}, "e250": NONE, "e500": STAGES, "e1g": STAGES, "e2g": STAGES},
        sk + [retime(c, setup, hold) for c in ("250", "500", "1g")], order,
        dict(start_states=1, note="÷2 链抽头各自在选定 VCO 相位上打拍，2G 经同结构 clk→q 复制单元；相位差 0.25 UI 一档、PVT 下不漂")))
    for key, name, gates, states, note in (
            ("S4", "同步二进制计数器 + 2G 复制", 2, 1, "三个触发器挂在同一相位时钟上（Q0 ÷2、Q1 ÷4、Q2 ÷8，次态为 CML XOR/AND）；状态全部有效，相对关系固定"),
            ("S5", "Johnson 计数器 + 2G 复制", 0, 64, "÷2/÷4/÷8 各一组扭环计数器，同一相位时钟、无逻辑门；三组彼此独立，需同步复位定相，÷8 组有非法态")):
        S.append(Structure(key, name, {
            **{f"c{c}": [K("jc"), I("B", "brc"), I("Q", f"q{c}"), K(f"e{c}"), I("O", f"o{c}")] for c in ("250", "500", "1g")},
            "c2g": [K("j2g"), I("B", "br2g"), I("R", "r2g"), K("e2g"), I("O", "o2g")],
            "loop": [I("Q", "q1g")] + [I("G", f"g{i}") for i in range(gates)]},
            {"jc": PHASE, "j2g": PHASE, "e250": NONE, "e500": STAGES, "e1g": STAGES, "e2g": STAGES},
            sk + [Budget("loop", T2G - counter_setup, owner="c250", label=f"计数器反馈（clk→q + {gates} 级门 + 建立）")], order,
            dict(start_states=states, note=note)))
    return S


def params():
    return bl.Params(mismatch={"*": 0.03, "O": 0.05}, tracking={"R": 0.05}, tap_error=2.0)


def fmt_limit(x, hi):
    return "无解" if x is None else (f"≥{hi:.0f}" if x >= hi else f"{x:.1f}")


def summarize(rep):
    S, sk = rep.structure, [r for r in rep.results if isinstance(r.relation, Skew)]
    chip = max(max(hi - lo for lo, hi in r.band().values()) for r in sk) / UI
    spread = max(float(np.ptp(r.values)) for r in sk) / UI
    lim = rep.limits
    weakest = min(rep.results, key=lambda r: r.margin)
    return dict(key=S.key, name=S.name, worst_ps=round(rep.worst, 1), weakest=weakest.relation.label,
                lambda_max=round(rep.lambda_max, 2), chip_band_ui=round(chip, 3), spread_ui=round(spread, 3),
                start_states=S.meta["start_states"], knobs=rep.knobs,
                relations={r.relation.label: round(r.margin, 1) for r in rep.results},
                variation_limit={t: fmt_limit(x, 8) for t, x in lim["variation"].items()},
                delay_limit={t: fmt_limit(x, 8) for t, x in lim["delay"].items()},
                mismatch_limit=fmt_limit(lim["mismatch"], 10), note=S.meta["note"])


def figure(reps, path, title):
    fig, axes = plt.subplots(len(reps), 3, figsize=(13, 1.75 * len(reps)), squeeze=False)
    for i, rep in enumerate(reps):
        sk = [r for r in rep.results if isinstance(r.relation, Skew)]
        for j, r in enumerate(sk):
            ax, rel = axes[i, j], r.relation
            lim = rel.period / 2 / UI
            ax.axvspan(-rel.half / UI, rel.half / UI, color="#2b5c9a", alpha=0.12, lw=0)
            for k, (p, (lo, hi)) in enumerate(r.band().items()):
                ok = lo - r.mismatch >= -rel.half and hi + r.mismatch <= rel.half
                col = "#2a7a56" if ok else "#c03a29"
                ax.plot([(lo - r.mismatch) / UI, (hi + r.mismatch) / UI], [k, k], color=col, lw=1)
                ax.plot([lo / UI, max(hi, lo + 0.5) / UI], [k, k], color=col, lw=5, solid_capstyle="round")
                ax.plot(r.values[bl.PROC_IDX == k] / UI, np.full(9, k), "o", ms=2.5, color="#1a212b")
            ax.set_yticks(range(len(PROCESS)), [p.upper() for p in PROCESS], fontsize=7)
            ax.set_xlim(-lim, lim)
            ax.invert_yaxis()
            ax.tick_params(axis="x", labelsize=7)
            ax.set_title(f"{rep.structure.key} {rel.label}: margin {r.margin:.0f} ps", fontsize=8)
        axes[i, 0].set_ylabel(rep.structure.key, fontsize=8)
    for ax in axes[-1]:
        ax.set_xlabel("offset error (UI); band = one chip over V/T, whisker + mismatch", fontsize=7)
    fig.suptitle(title, fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default="both", choices=("comb", "latched", "both"))
    ap.add_argument("--w", type=float, default=0.5)
    a = ap.parse_args()
    E = bl.load_elements(ROOT / "config/timing_elements.json")
    camp = RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True)
    out = {}
    for tree in (("comb", "latched") if a.tree == "both" else (a.tree,)):
        reps = [bl.analyse(S, E, params()) for S in structures(tree, a.w)]
        rows = [summarize(r) for r in reps]
        out[tree] = rows
        print(f"\n== {tree} tree, w = {a.w} UI ==")
        print(f"{'':4s}{'方案':22s}{'最坏':>8s}  {'λmax':>5s}  {'芯片带':>6s}  {'全散布':>6s}  启动态  最紧的一项")
        for r in rows:
            print(f"{r['key']:4s}{r['name']:22s}{r['worst_ps']:7.0f}ps  {r['lambda_max']:5.2f}  {r['chip_band_ui']:6.2f}  "
                  f"{r['spread_ui']:6.2f}  {r['start_states']:5d}   {r['weakest']}")
        print("反推约束（旋钮不动）：PVT 变化可放大 × / 延迟可放大 × / 失配可放大 ×")
        for r in rows:
            print(f"  {r['key']}: 变化 " + " ".join(f"{t}{x}" for t, x in r["variation_limit"].items())
                  + " | 延迟 " + " ".join(f"{t}{x}" for t, x in r["delay_limit"].items()) + f" | 失配 ×{r['mismatch_limit']}")
        figure(reps, camp / f"{tree}.png", f"TX select-clock structures, {tree} tree, w = {a.w} UI")
    (camp / "summary.json").write_text(json.dumps(dict(w=a.w, elements="config/timing_elements.json", results=out),
                                                  indent=1, ensure_ascii=False, default=float))
    print(camp.relative_to(ROOT))


if __name__ == "__main__":
    main()
