"""Plot the 2026-11-06 clocking evidence, with explicit sources and no simulations.

uv run python verification/plotting/current_clocking.py --collect
uv run python verification/plotting/current_clocking.py

--collect reads the listed campaigns (including complete native waveforms),
and saves a small tracked snapshot. The default redraws from that snapshot.
Historical campaigns are read only. Figures are descriptive, not signoff.
"""
import argparse
import hashlib
import importlib.util
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition, PROCESS, SUPPLY_V, TEMP_C, grid45
from serdes_flow.project import ROOT

SNAPSHOT = ROOT / "docs/data/clocking_progress_20261106.json"
OUTPUTS = {
    "vco_workmap": "clocking/vco/vco_r5_4b_code_kvco_grid",
    "vco_control_windows": "clocking/vco/vco_r5_3b_4b_control_windows",
    "vco_tuning_examples": "clocking/vco/vco_r5_4b_tuning_examples",
    "cp_windows": "clocking/pll/charge_pump/cp_real_bias_dc_windows",
    "div2_feasible_region": "clocking/dividers/div2_w20_clock_feasible_region",
    "native_r5_v3": "tx/clock_distribution/tx_v3_native_r5_static_summary",
    "native_counter_sequence": "tx/clock_distribution/tx_v3_native_r5_counter_sequence",
}
SOURCES = {
    "vco": "results/analog/pll/vco/workmap/20261106T035710Z/summary.json",
    "window4": "results/analog/pll/vco/workmap/20261106T035710Z/extend.json",
    "window3": "results/analog/pll/vco/workmap/20261105T220009Z/extend.json",
    "cp": "results/analog/pll/cp/window/20261106T021356Z/summary.json",
    "div2": "results/analog/pll/divider/div2_map/20261105T215442Z_txcounter/summary.json",
}
NATIVE = ROOT / "results/analog/tx/serializer/native_r5_v3/20261106T121036Z"
LEGACY = ROOT / "results/analog/tx/serializer/clock_replay/counter/v3_probe_20261031T135020Z"
PASSIVE = ("tt", "hh", "ll")
COLORS = ("#247ba0", "#df8545", "#339778")


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect():
    data = {k: json.loads((ROOT / p).read_text()) for k, p in SOURCES.items()}
    data["sources"] = {k: dict(path=p, sha256=digest(ROOT / p)) for k, p in SOURCES.items()}
    probe = load_module("native_r5_report", ROOT / "analog/tx/serializer/tb/native_clock/r5_v3.py")
    rows = {}
    for case in sorted(NATIVE.iterdir()):
        if not (case / "run/tb.cir").exists():
            continue
        tag, rc = case.name.rsplit("_", 1)
        ex_path = case / "run/execution.json"
        ex = json.loads(ex_path.read_text()) if ex_path.exists() else {}
        row = dict(execution=ex, source=str(case.relative_to(ROOT)))
        # Full-duration output is required even when ngspice exits with status 0.
        wave = spice.case_output(case, "run", "waveforms.raw", 46e-9)
        if wave is None:
            row["state"] = "timeout" if ex.get("timed_out") else "incomplete"
        else:
            row.update(state="measured", metrics=probe.analyse(wave.parent),
                       waveform_sha256=digest(wave))
            row["metrics"]["source_warning"] = bool(ex.get("log_failures"))
        rows[f"{tag}:{rc}"] = row
    data["native"] = rows
    probe.counter.WINDOW = (14e-9, 30e-9)
    legacy = {}
    for wave in sorted(LEGACY.glob("*/run/waveforms.raw*")):
        legacy[wave.parents[1].name] = dict(source=str(wave.relative_to(ROOT)),
                                          sha256=digest(wave), metrics=probe.counter.check(spice.Waves(wave)))
    data["legacy_counter_recheck"] = dict(window_s=[14e-9, 30e-9], rows=legacy)
    w = spice.Waves(NATIVE / "ss_v1650_t85_hh/run/waveforms.raw")
    t = np.arange(29e-9, 33e-9, 2e-12)
    trace = dict(time_ns=(t * 1e9).tolist())
    for name, node in (("clock", "xcnt.ck"), ("q0", "q0"), ("q1", "q1"), ("q2", "q2")):
        trace[name] = np.interp(t, w.t, probe.counter.diff(w, node)).tolist()
    data["counter_trace"] = trace
    data["measurement_sources"] = {p: digest(ROOT / p) for p in (
        "src/serdes_flow/clock.py", "analog/tx/serializer/tb/clock_replay/counter.py",
        "analog/tx/serializer/tb/native_clock/r5_v3.py")}
    data["scope"] = "Open-loop, real bias, PDK resistors; hh/ll are joint RC corners. Native data are static; no data eye or bit mapping acceptance."
    SNAPSHOT.write_text(json.dumps(data, indent=1, allow_nan=False) + "\n")
    return data


def style():
    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "axes.titleweight": "bold", "figure.facecolor": "#fafbfc",
                         "axes.facecolor": "white", "svg.fonttype": "none"})


def export(fig, name):
    path = ROOT / "docs/figures" / OUTPUTS[name]
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg"):
        fig.savefig(path.with_suffix(f".{suffix}"), dpi=160)
    plt.close(fig)


def save(fig, name, title, note):
    fig.suptitle(title, fontsize=15, fontweight="bold")
    fig.text(0.02, 0.012, note, fontsize=9, color="#505968")
    fig.tight_layout(rect=(0.01, 0.055, 0.99, 0.94))
    export(fig, name)


def vco_map(data):
    rows = data["vco"]["rows"]
    assert set(rows) == {f"{c.tag}:{p}" for c in grid45() for p in PASSIVE}
    fig, axes = plt.subplots(2, 3, figsize=(14, 8))
    cmaps = (plt.get_cmap("viridis", 16), "magma")
    for j, rc in enumerate(PASSIVE):
        for i, field in enumerate(("code", "kvco")):
            vals = np.array([[rows[f"{proc}_v{round(v * 1000)}_t{t}:{rc}"][field]
                              for v in SUPPLY_V for t in TEMP_C] for proc in PROCESS])
            if field == "kvco":
                vals = vals / 1e6
            ax = axes[i, j]
            im = ax.imshow(vals, cmap=cmaps[i], aspect="auto", vmin=0 if i == 0 else 150,
                           vmax=15 if i == 0 else 1150)
            ax.set_title(f"RC {rc} · {'所选粗码' if i == 0 else '局部 Kvco (MHz/V)'}")
            ax.set_yticks(range(5), [p.upper() for p in PROCESS])
            ax.set_xticks(range(9), [f"{v:g} V\n{t}°C" for v in SUPPLY_V for t in TEMP_C])
            ax.tick_params(axis="x", labelsize=8)
            for y, x in np.ndindex(vals.shape):
                ax.text(x, y, f"{vals[y,x]:.0f}", ha="center", va="center", fontsize=8,
                        color="white" if vals[y, x] < (8 if i == 0 else 700) else "black")
            for x in (2.5, 5.5):
                ax.axvline(x, color="white", lw=2)
            fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    save(fig, "vco_workmap", "VCO r5 / 4 bit：135 条件选码与环路增益分布",
         "选码策略：在 0.85–1.35 V 内最接近中点；频率来自仿真点间插值。此图不是 PLL 锁定或噪声验收。")


def window_comparison(data):
    names = ("0.95-1.35 V", "0.85-1.35 V", "0.85 V-CP edge", "0.7 V-CP edge")
    labels = ("0.95–1.35 V\n当前 B2", "0.85–1.35 V", "0.85 V–CP 上沿", "0.70 V–CP 上沿")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.7))
    x = np.arange(4)
    for i, (bank, color) in enumerate(zip((3, 4), COLORS)):
        r = [data[f"window{bank}"][f"{bank} bit, simulated: {n}"] for n in names]
        for ax, vals in zip(axes, ([len(z["none"]) for z in r], [z["frozen_ok"] for z in r])):
            bars = ax.bar(x + (i - 0.5) * 0.35, vals, width=0.35, color=color, label=f"{bank} bit，仿真")
            ax.bar_label(bars, padding=3)
    for ax in axes:
        ax.set_xticks(x, labels)
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        ax.legend()
    axes[0].set(title="无可用码的条件数（共 135）", ylim=(0, 13), ylabel="条件数；越低越好")
    axes[1].set(title="单一码覆盖 −40…85°C（共 45 组）", ylim=(0, 50), ylabel="MOS × VDD × RC 组数；越高越好")
    save(fig, "vco_control_windows", "粗码粒度与控制范围：全条件可达 ≠ 一码覆盖全温",
         "按已有 extend.json；控制窗口边界处用仿真频率插值。4 bit / 0.85 V–CP 上沿仍有 3 组需要温漂切码策略。")


def tuning(data):
    rows, vs = data["vco"]["rows"], np.array(data["vco"]["vs"])
    points = ("tt_v1800_t27:tt", "fs_v1650_t85:hh", "sf_v1650_t-40:ll", "ff_v1950_t-40:ll")
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    for ax, point in zip(axes.flat, points):
        r = rows[point]
        cp = data["cp"]["rows"][point]
        ax.axvspan(max(vs[0], cp["lo"]), min(vs[-1], cp["hi"]), color="#e8f3ec")
        for code in r["usable"]:
            ax.plot(vs, np.array(r["f"][str(code)]) / 1e9, "o-", ms=4,
                    lw=2 if code == r["code"] else 1, label=f"码 {code}" + ("（所选）" if code == r["code"] else ""))
        ax.axhline(2, color="#a33b3b", ls="--", lw=1)
        ax.set(title=point, xlabel="Vctrl (V)", ylabel="f (GHz)", xlim=(0.82, 1.38))
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8, ncol=2)
    save(fig, "vco_tuning_examples", "代表工况：相邻粗码调谐曲线与 2 GHz 交点",
         "圆点为实际仿真，连线为插值；绿色为已扫描范围与 CP DC 窗口的交集。只画可达码，未外推未测区域。")


def cp_windows(data):
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    conds = grid45()
    for ax, supply in zip(axes, SUPPLY_V):
        cs = [c for c in conds if c.supply == supply]
        for j, rc in enumerate(PASSIVE):
            r = [data["cp"]["rows"][f"{c.tag}:{rc}"] for c in cs]
            x = np.arange(len(cs)) + (j - 1) * 0.22
            ax.vlines(x, [a["lo"] for a in r], [a["hi"] for a in r], color=COLORS[j], lw=3, alpha=0.75, label=f"RC {rc}")
            ax.scatter(x, [a["hi"] for a in r], c=[100 * a["mismatch"] for a in r],
                       cmap="Reds", vmin=0, vmax=12, s=27, edgecolor="black", linewidth=0.3)
        ax.axhspan(0.95, 1.35, color="#4682b4", alpha=0.08)
        ax.set(title=f"VDD = {supply:g} V", ylabel="CP 输出窗口 (V)", ylim=(0.15, 1.8))
        ax.set_xticks(range(15), [f"{c.process.upper()}\n{c.temp}" for c in cs], fontsize=8)
        ax.grid(axis="y", alpha=0.2)
        ax.legend(loc="lower left", ncol=3, fontsize=8)
    cax = fig.add_axes((0.38, 0.83, 0.26, 0.03))
    fig.colorbar(plt.cm.ScalarMappable(norm=plt.Normalize(0, 12), cmap="Reds"),
                 cax=cax, orientation="horizontal")
    fig.text(0.51, 0.90, "端点圆点颜色：UP/DN 失配 (%)", ha="center", fontsize=10)
    # This figure has a shared colorbar; preserve its manually allocated layout.
    fig.suptitle("CP：电流下垂窗口与 UP/DN 失配是两项约束", y=0.99, fontsize=15, fontweight="bold")
    fig.text(0.02, 0.01, "真实偏置、50 µA 参考；相对 VDD/2 电流下垂 ≤5%。浅蓝为 B2 的 0.95–1.35 V；不代表动态电荷或闭环通过。", fontsize=9)
    fig.subplots_adjust(bottom=0.16, top=0.71, wspace=0.22)
    export(fig, "cp_windows")


def divider_map(data):
    d = data["div2"]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.8))
    for ax, (point, rows) in zip(axes.flat, d["rows"].items()):
        a = np.array([[rows[f"c{round(cm*1000)}_p{round(pp)}"]["swing"] * 1e3 for pp in d["pp"]] for cm in d["cm"]])
        im = ax.imshow(a, cmap="viridis", vmin=0, vmax=600, aspect="auto")
        for y, cm in enumerate(d["cm"]):
            for x, pp in enumerate(d["pp"]):
                r = rows[f"c{round(cm*1000)}_p{round(pp)}"]
                good = r["crossings"] in (19, 20, 21) and r["swing"] >= 0.15
                ax.text(x, y, f"{a[y,x]:.0f}\n{'÷2' if good else '异常'} / {r['crossings']}沿", ha="center", va="center", color="white" if a[y,x] < 400 else "black", fontsize=9)
        ax.set(title=point, xlabel="门极时钟差分摆幅 (mVpp)", ylabel="门极共模 (V)")
        ax.set_xticks(range(len(d["pp"])), [f"{p:g}" for p in d["pp"]])
        ax.set_yticks(range(len(d["cm"])), d["cm"])
        fig.colorbar(im, ax=ax, label="输出差分 mVpp", fraction=0.04)
    save(fig, "div2_feasible_region", "2 GHz 单元可行区：TX 计数器保持管 W20 的接口筛查",
         "真实偏置、PDK R、PLL 型负载；每格 10 ns 观察期应有约 20 个过零沿，且输出 ≥150 mVpp。单元结果不能替代同步计数器。")


def native_summary(data):
    rows = data["native"]
    keys = list(rows)
    fig, axes = plt.subplots(2, 2, figsize=(13, 8))
    measured = [(i, r["metrics"]) for i, r in enumerate(rows.values()) if r["state"] == "measured"]
    x = [i for i, _ in measured]
    axes[0, 0].scatter(x, [r["f0"] / 1e9 for _, r in measured], color=COLORS[0], s=55)
    axes[0, 0].axhline(2, color="#a33b3b", ls="--")
    axes[0, 0].set(title="固定 Vctrl 开环频率", ylabel="GHz", ylim=(1.96, 2.06))
    axes[0, 1].scatter(x, [r["ck_pp"] * 1e3 for _, r in measured], color=COLORS[2], s=55)
    axes[0, 1].axhline(215, color="#a33b3b", ls="--", label="单元筛查参考 215 mVpp")
    axes[0, 1].set(title="计数器门极时钟", ylabel="差分 mVpp", ylim=(150, 500))
    axes[0, 1].legend(fontsize=8)
    for k, label, color in (("setup_min_s", "最小建立", COLORS[0]), ("hold_min_s", "最小保持", COLORS[1])):
        axes[1, 0].scatter(x, [r["counter"][k] * 1e12 for _, r in measured], label=label, color=color)
    axes[1, 0].set(title="次态输入时序（观测值）", ylabel="ps", ylim=(0, 410))
    axes[1, 0].legend(fontsize=8)
    axes[1, 1].bar(x, [r["pclock_w"] * 1e3 for _, r in measured], color=COLORS[0], width=0.65)
    axes[1, 1].set(title="TX 分发功耗（含原有 dummy 输入）", ylabel="mW", ylim=(0, 60))
    labels = []
    for k in keys:
        tag, rc = k.split(":")
        c = Condition.parse(tag)
        labels.append(f"{c.process.upper()}\n{c.supply:g} V\n{c.temp}°C\n{rc}")
    for ax in axes.flat:
        ax.set_xticks(range(len(keys)), labels, fontsize=8)
        ax.set_xlim(-0.6, len(keys) - 0.4)
        ax.grid(axis="y", alpha=0.2)
        ax.set_axisbelow(True)
        for i, r in enumerate(rows.values()):
            if r["state"] != "measured":
                ax.axvspan(i - 0.4, i + 0.4, color="#eeeeee")
                ax.text(i, 0.55, "超时" if r["state"] == "timeout" else "未完成", rotation=90,
                        transform=ax.get_xaxis_transform(), ha="center", color="#777777")
    save(fig, "native_r5_v3", "r5 / 4 bit 原生前端 + TX v3：恢复 8 个完整工况，2 个仍缺失",
         "完整工况计数序列均正确；SS 冷 hh 有可恢复收敛告警。46 ns、静态数据；眼图、位映射和实际数据寄存器尚未验证。")


def counter_trace(data):
    d = data["counter_trace"]
    t = np.array(d["time_ns"])
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True)
    for i, name in enumerate(("clock", "q0", "q1", "q2")):
        axes[0].plot(t, np.array(d[name]) * 1000 + (3 - i) * 700, label=name, lw=1)
    axes[0].set(ylabel="差分 mV（逐路平移）", title="SS 1.65 V / 85°C / hh：稳态波形")
    axes[0].legend(ncol=4, loc="upper right")
    r = data["native"]["ss_v1650_t85:hh"]["metrics"]["counter"]["sequence"]
    st = np.array(r["sample_times_s"]) * 1e9
    state = np.array(r["states"])
    use = (st >= t[0]) & (st <= t[-1])
    axes[1].step(st[use], state[use], where="mid", color=COLORS[2], marker="o", label="相邻下降沿中点采样")
    axes[1].set(xlabel="时间 (ns)", ylabel="q2 q1 q0 状态", yticks=range(8), ylim=(-0.5, 7.5), xlim=(t[0], t[-1]))
    axes[1].legend(loc="upper left")
    for ax in axes:
        ax.grid(alpha=0.2)
    save(fig, "native_counter_sequence", "计数器检查修复：clk→q 约 101 ps，固定 100 ps 读数处在翻转中",
         "中点采样覆盖每个完整周期并检查全部 +1 转移；不丢弃后段错误。状态检查与建立/保持测量分别保留。")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--collect", action="store_true")
    args = ap.parse_args()
    data = collect() if args.collect else json.loads(SNAPSHOT.read_text())
    style()
    for plot in (vco_map, window_comparison, tuning, cp_windows, divider_map, native_summary, counter_trace):
        plot(data)
    measured = [r["metrics"] for r in data["native"].values() if r["state"] == "measured"]
    assert len(measured) == 8
    assert all(r["counter"]["counting"] for r in measured)
    catalog = dict(date="2026-11-06", report="docs/history/clocking_progress_20261106.md",
                   snapshot=dict(path=str(SNAPSHOT.relative_to(ROOT)), sha256=digest(SNAPSHOT)),
                   sources=data["sources"], measurement_sources=data["measurement_sources"],
                   native={k: r["state"] for k, r in data["native"].items()},
                   legacy_replay_window_counting={k: r["metrics"]["counting"] for k, r in data["legacy_counter_recheck"]["rows"].items()},
                   figures=[f"docs/figures/{p}.png" for p in OUTPUTS.values()])
    (ROOT / "results/catalog/clocking_progress_20261106.json").write_text(json.dumps(catalog, indent=2) + "\n")
    print("7 figure groups -> VCO / CP / dividers / TX clock distribution; 8/10 complete native points, all 8 count correctly")


if __name__ == "__main__":
    main()
