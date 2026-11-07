"""Output-stage spread attribution and sizing map; no simulation is performed.

    uv run python verification/plotting/tx_output_driver_ddj.py --collect <ddj campaign> ... [--chain <full TX campaign> ...]
    uv run python verification/plotting/tx_output_driver_ddj.py            # redraw from docs/data

--collect reads finished analog/tx/output_driver/tb/ddj campaigns (summary.json rows) and, optionally, full-TX
parallel_serializer run campaigns (serializer / pad / remote check and mapping), and writes docs/data and the figure.
Whether a variant changes the replayed node's load is recomputed from its resolved isolation-buffer size.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from serdes_flow import boundary
from serdes_flow.project import ROOT

DDJ = ROOT / "analog/tx/output_driver/tb/ddj/run.py"
DATA = ROOT / "docs/data/tx_output_driver_ddj.json"
FIG = ROOT / "docs/figures/tx/output_driver/tx_output_driver_ddj"
NODES = ("input", "iso", "pre", "pad", "remote")
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load_ddj():
    spec = importlib.util.spec_from_file_location("ddj_bench", DDJ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def family(params):
    """Which parts differ from the r2 sizes (explicit defaults do not count)."""
    def changed(*pairs):
        return any(str(params.get(k, d)) != d for k, d in pairs)
    iso = changed(("riso", "600"), ("wtiso", "12"), ("wiso", "12"))
    pre = changed(("rpre", "150"), ("wtpre", "48"), ("wpre", "48"))
    out = changed(("wout", "256"), ("wtout", "172"))
    return "+".join(x for x, on in (("iso", iso), ("pre", pre), ("out", out)) if on) or "r2"


def collect(campaigns, chains):
    ddj = load_ddj()
    rows = []
    for camp in campaigns:
        camp = (ROOT / camp).resolve()
        plan = json.loads((camp / "plan.json").read_text())
        summary = json.loads((camp / "summary.json").read_text())
        bc = boundary.get(plan["replay"] or plan["timing_from"]) if (plan.get("replay") or plan.get("timing_from")) else None
        for key, r in summary["rows"].items():
            cond, variant = key.split(":")
            params = r["params"]
            row = dict(campaign=str(camp.relative_to(ROOT)), mode=plan.get("mode", "replay" if plan.get("replay") else "clean"), condition=cond,
                       variant=variant, params=params, family=family(params), power_mw=r["power_w"] * 1e3,
                       nodes={n: dict(spread_ui=r[n]["spread_ui"], eye_mv=r[n]["eye_v"] * 1e3, margin_mv=r[n]["margin_v"] * 1e3,
                                      pp_mv=r[n].get("pp_v", float("nan")) * 1e3, errors=r[n]["errors"]) for n in NODES})
            if plan.get("mode") != "replay" and not plan.get("replay"):
                row.update(cm_below_v=plan.get("cm_below"), edge_s=plan.get("edge"), pp_v=plan.get("pp"))
            if plan.get("replay"):
                row.update(load_changed=ddj.load_changed(bc, params), replay_error_mv={k: v * 1e3 for k, v in r["replay_error_v"].items()})
            rows.append(row)
    chain = []
    for camp in chains:
        camp = (ROOT / camp).resolve()
        plan = json.loads((camp / "plan.json").read_text())
        s = json.loads((camp / "summary.json").read_text())
        out = {}
        for n in ("serializer", "pad", "remote"):
            o = s["outputs"][n]
            out[n] = dict(margin_mv=o["check"]["minimum_signed_margin_v"] * 1e3, spread_ui=o["check"]["transition_spread_ui"],
                          mapping_spread_ui=o["mapping"]["edge_spread_ui"], pp_mv=o["check"]["differential_pp_v"] * 1e3,
                          errors=o["check"]["bit_errors"], in_order=o["mapping"]["in_order"])
        chain.append(dict(campaign=str(camp.relative_to(ROOT)), condition=plan["condition"], driver_params=plan.get("driver_params"),
                          clock_extra_2g=plan["clock_extra_2g"], summary_sha256=sha(camp / "summary.json"), outputs=out))
    data = dict(boundary="tx_extra5_serializer_output_v1", bench=str(DDJ.relative_to(ROOT)), bench_sha256=sha(DDJ),
                collector_sha256=sha(Path(__file__)), rows=rows, chain=chain)
    DATA.write_text(json.dumps(data, indent=1, default=float) + "\n")
    return data


def draw(data):
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED})
    fig, (ax0, ax1) = plt.subplots(1, 2, figsize=(10.5, 4.2), gridspec_kw=dict(width_ratios=(1, 1.25)))
    # left: per-node spread, FS hot r2, three inputs
    fs = [r for r in data["rows"] if r["condition"] == "fs_v1650_t85" and r["variant"] == "r2"]
    pick = {}
    for r in fs:
        label = {"clean": "clean input", "timed": "replayed timing, clean shape", "replay": "replayed serializer waveform"}[r["mode"]]
        if r["mode"] == "clean" and r.get("cm_below_v") != 0.075:
            continue
        if r["mode"] == "timed" and r.get("edge_s") != 20e-12:
            continue
        pick.setdefault(label, r)
    for i, (label, r) in enumerate(pick.items()):
        y = [r["nodes"][n]["spread_ui"] for n in NODES]
        ax0.plot(range(len(NODES)), y, "-o", color=SERIES[i], lw=2, ms=6, label=label)
        ax0.annotate(f"{y[3]:.3f}", (3, y[3]), textcoords="offset points", xytext=(6, -3), color=INK, fontsize=8)
    ax0.axhline(0.15, color=MUTED, lw=1, ls="--")
    ax0.text(0, 0.152, "0.15 UI", color=MUTED, fontsize=8, va="bottom")
    ax0.set_xticks(range(len(NODES)), ["serializer\noutput", "isolation\nbuffer", "predriver", "pad", "remote"])
    ax0.set_ylabel("crossing spread on UI grid (UI)")
    ax0.set_title("FS 1.65 V 85 °C, r2 stage: where the spread grows", fontsize=9, color=INK, loc="left")
    ax0.legend(frameon=False, fontsize=8, loc="center left", bbox_to_anchor=(0, 0.55))
    # right: FS replay map, pad spread vs power
    m = [r for r in data["rows"] if r["mode"] == "replay" and r["condition"] == "fs_v1650_t85"]
    seen, fams = set(), {}
    for r in m:
        if r["variant"] in seen:
            continue
        seen.add(r["variant"])
        fams.setdefault(r["family"], []).append(r)
    order = ["r2", "pre", "iso", "iso+pre", "out", "pre+out"]
    names = {"r2": "r2 (W256, 150 Ω)", "pre": "faster predriver", "iso": "faster isolation buffer", "iso+pre": "both buffers",
             "out": "smaller output pair", "pre+out": "predriver + output pair"}
    for i, f in enumerate(order):
        pts = sorted(fams.get(f, []), key=lambda r: r["power_mw"])
        if not pts:
            continue
        ax1.plot([r["power_mw"] for r in pts], [r["nodes"]["pad"]["spread_ui"] for r in pts], "o" if f != "r2" else "s",
                 color=SERIES[i] if f != "r2" else INK, ms=7, label=names[f], mec="white", mew=1.5)
    for r in m:
        if r["variant"] in ("r2", "p120o192", "o192", "i600p80", "o128"):
            left = r["variant"] == "p120o192"
            ax1.annotate(r["variant"], (r["power_mw"], r["nodes"]["pad"]["spread_ui"]), textcoords="offset points", xytext=(-6, -12) if left else (6, 2),
                         ha="right" if left else "left", fontsize=8, color=INK)
    ax1.axhline(0.15, color=MUTED, lw=1, ls="--")
    ax1.set_xlabel("stage power (mW)")
    ax1.set_ylabel("pad spread (UI)")
    ax1.set_title("FS 1.65 V 85 °C replay: pad spread vs power", fontsize=9, color=INK, loc="left")
    ax1.legend(frameon=False, fontsize=8, loc="upper right")
    for ax in (ax0, ax1):
        ax.grid(color=GRID, lw=0.8)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG.with_suffix(".png"), dpi=150)
    print(FIG.with_suffix(".png").relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", nargs="+")
    ap.add_argument("--chain", nargs="*", default=[])
    a = ap.parse_args()
    data = collect(a.collect, a.chain) if a.collect else json.loads(DATA.read_text())
    draw(data)


if __name__ == "__main__":
    main()
