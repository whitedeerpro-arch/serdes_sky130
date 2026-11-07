"""Snapshot/plot explicit convergence campaigns; never rewrites simulations.

uv run python verification/plotting/pll_cold_isolation.py --collect CAMPAIGN ...
uv run python verification/plotting/pll_cold_isolation.py
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import clock, spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

DATA = ROOT / "docs/data/pll_cold_isolation.json"
FIGURE = ROOT / "docs/figures/clocking/pll/r5_cold_frontend_isolation"
LABELS = {"ring": "VCO + 4×30 fF 缓冲", "receivers": "+ 四路实际接收器", "prescaler": "+ 一个实际 ÷8 支路", "frontend": "完整前端（偏置就绪初值）"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured(path, level, supply):
    w = spice.Waves(path)
    if w.t[-1] < 24e-9 * (1 - 1e-7):
        raise ValueError(f"incomplete waveform {path}")
    start = w.t[-1] - 5e-9
    b0 = "pb0" if level == "frontend" else "xpll.b0"
    nodes = {"vco": ("xpll.v0p", "xpll.v0n"), "buffer": (b0 + "p", b0 + "n")}
    if level in {"prescaler", "frontend"}:
        nodes.update({f"div{k}": ((f"p0{k}p", f"p0{k}n") if level == "frontend" else (f"xpll.q{k}p", f"xpll.q{k}n")) for k in (2, 4, 8)})
    metrics = {}
    for name, (p, n) in nodes.items():
        metrics[name] = clock.period_stats(w.t, w[p] - w[n], start=max(w.t[0], w.t[-1] - 16e-9) if name.startswith("div") else start)
    f = metrics["vco"]["frequency_hz"] if metrics["vco"] else None
    metrics["divide_checks"] = {str(k): bool(f and metrics[f"div{k}"] and abs(metrics[f"div{k}"]["frequency_hz"] * k / f - 1) < .01)
                                for k in (2, 4, 8)} if level in {"prescaler", "frontend"} else {}
    for group, count, target in (("fullrate", 4, 1), ("feedback", 4, 1 / 8)):
        group_rows = {}
        for k in range(count):
            if group == "fullrate":
                node = f"c{k}p" if level == "frontend" else f"xpll.cm{k}p"
            else:
                node = "fb0" if k == 0 else f"xpll.fb{k}"
            if node not in w:
                continue
            y = w[node]
            since = max(w.t[0], w.t[-1] - 16e-9) if group == "feedback" else start
            use = w.t >= since
            ps = clock.period_stats(w.t, y - supply / 2, start=since)
            lo, hi = float(y[use].min()), float(y[use].max())
            ok = bool(f and ps and abs(ps["frequency_hz"] / (f * target) - 1) < .01 and lo < .2 * supply and hi > .8 * supply)
            if group == "fullrate":
                ok &= bool(ps and .45 <= ps["duty"] <= .55)
            group_rows[str(k)] = dict(period=ps, low_v=lo, high_v=hi, functional_check=ok)
        metrics[group] = group_rows
    ts = np.linspace(w.t[-1] - 4e-9, w.t[-1], 1001)
    trace = dict(time_ns=((ts - ts[0]) * 1e9).tolist())
    for name, (p, n) in nodes.items():
        trace[name] = np.interp(ts, w.t, w[p] - w[n]).tolist()
    return metrics, trace


def collect(campaigns):
    sources, rows = [], []
    for campaign in campaigns:
        source = campaign / "summary.json"
        sources.append(dict(path=str(source.relative_to(ROOT)), sha256=digest(source)))
        for tag, original in json.loads(source.read_text())["rows"].items():
            row = dict(campaign=str(campaign.relative_to(ROOT)), tag=tag, **original)
            if row["status"] == "measured":
                wave = ROOT / row["waveform"]
                row["metrics"], row["trace"] = measured(wave, row["level"], Condition.parse(row["condition"]).supply)
                row["waveform_sha256"] = digest(wave)
            else:
                attempt = row.get("smoke", row.get("execution", {}))
                if attempt:
                    log = ROOT / attempt["directory"] / "simulator.log"
                    content = log.read_text(errors="replace")
                    row["log_sha256"] = digest(log)
                    row["last_stage"] = ("klu_initial_matrix" if "needed element doesn't exist" in content else
                                         "transient_op" if "Transient op started" in content else
                                         "solver" if "Direct Linear Solver" in content else "model_setup")
            rows.append(row)
    data = dict(scope="FF 1.95 V -40 C local tests; native model unless marked stable; fixed working code/control; prebiased is not power-up qualification; CML amplitude ungraded", sources=sources, rows=rows)
    DATA.write_text(json.dumps(data, indent=1, allow_nan=False) + "\n")
    index = dict(report="docs/history/pll_cold_convergence.md", data=str(DATA.relative_to(ROOT)), figures=[str(FIGURE.with_suffix('.png').relative_to(ROOT))], sources=sources,
                 measured=sum(r["status"] == "measured" for r in rows), incomplete=sum(r["status"] != "measured" for r in rows))
    (ROOT / "results/catalog/pll_cold_convergence.json").write_text(json.dumps(index, indent=2) + "\n")
    return data


def plot(data):
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    selected = [r for r in data["rows"] if r["status"] == "measured" and r["solver"] == "sparse" and r.get("varactor", "native") == "native"]
    selected.sort(key=lambda r: (("ll", "hh", "tt").index(r["passive"]), ("ring", "receivers", "prescaler", "frontend").index(r["level"])))
    fig, axes = plt.subplots(len(selected), 2, figsize=(12, max(3, 2.1 * len(selected))), squeeze=False)
    for (left, right), row in zip(axes, selected):
        tr, m = row["trace"], row["metrics"]
        left.plot(tr["time_ns"], np.array(tr["vco"]) * 1000, color="#276f96", lw=1)
        left.set_ylabel("差分 / mV")
        left.set_title(f'{row["passive"]} · {LABELS[row["level"]]} · {m["vco"]["frequency_hz"] / 1e9:.6f} GHz', loc="left", fontsize=10)
        right.plot(tr["time_ns"], np.array(tr["buffer"]) * 1000, color="#276f96", label="缓冲")
        for k, color in ((2, "#c97a38"), (4, "#379878"), (8, "#9568a7")):
            if f"div{k}" in tr:
                right.plot(tr["time_ns"], np.array(tr[f"div{k}"]) * 1000, color=color, lw=1, label=f"÷{k}")
        right.legend(loc="upper right", fontsize=8, ncol=4)
        right.set_title("该层边界的缓冲 / 分频输出", loc="left", fontsize=10)
        for ax in (left, right):
            ax.axhline(0, color="#aaa", lw=.5)
            ax.set_xlim(0, 4)
            ax.grid(alpha=.15)
    for ax in axes[-1]:
        ax.set_xlabel("末 4 ns 内的相对时间 / ns")
    fig.suptitle("r5 冷角分层测试：按实际加载区分结果", fontsize=15, fontweight="bold")
    fig.text(.02, .01, "FF / 1.95 V / −40 °C；真实偏置、PDK 无源角；固定码和 Vctrl。幅度仅记录，初值测试不证明上电。", fontsize=9)
    fig.tight_layout(rect=(0, .035, 1, .96))
    FIGURE.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(FIGURE.with_suffix(f".{ext}"), dpi=160)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--collect", nargs="+", type=Path)
    a = p.parse_args()
    data = collect([x.resolve() for x in a.collect]) if a.collect else json.loads(DATA.read_text())
    plot(data)
    print(DATA.relative_to(ROOT), FIGURE.with_suffix(".png").relative_to(ROOT))


if __name__ == "__main__":
    main()
