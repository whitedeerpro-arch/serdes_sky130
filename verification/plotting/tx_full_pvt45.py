"""Full TX over the 45 PVT conditions: collect a pvt45 campaign into docs/data and draw it; no simulation.

    uv run python verification/plotting/tx_full_pvt45.py --collect results/analog/tx/full_pvt45/<campaign>
    uv run python verification/plotting/tx_full_pvt45.py            # redraw from docs/data

Reads each condition's state (analog/tx/input_register/tb/full_serializer/pvt45.py) and its run summary.json;
gates as in docs/overview/spec.md: serializer and pad 75 mV / 0.15 UI plus function, remote a comparison screen.
"""
import argparse
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from serdes_flow.project import ROOT

DATA = ROOT / "docs/data/tx_full_pvt45.json"
FIG = ROOT / "docs/figures/tx/ingress/tx_full_pvt45.png"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
COLORS = dict(serializer="#2a78d6", pad="#eb6834", remote="#9a988f")
PROCESS = ("tt", "ss", "ff", "sf", "fs")


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def collect(camp):
    camp = (ROOT / camp).resolve()
    plan = json.loads((camp / "plan.json").read_text())
    rows = []
    for cond in plan["conditions"]:
        f = camp / "state" / f"{cond}.json"
        st = json.loads(f.read_text()) if f.exists() else dict(status="queued")
        row = dict(condition=cond, status=st["status"], probe=st.get("probe"), run=st.get("run"), adopted=st.get("adopted", False),
                   error=st.get("error"))
        if st["status"] == "done":
            run = ROOT / st["run"]
            s = json.loads((run / "summary.json").read_text())
            row.update(summary_sha256=sha(run / "summary.json"), grade=st["grade"],
                       accepted_words=s["accepted_words"])
        rows.append(row)
    data = dict(campaign=str(camp.relative_to(ROOT)), clock=plan["clock"], driver_params=plan["driver_params"], gates=plan["gates"],
                sources=plan["sources"], collector_sha256=sha(Path(__file__)), rows=rows)
    DATA.write_text(json.dumps(data, indent=1) + "\n")
    return data


def key(cond):
    p, v, t = cond.split("_")
    return (int(v[1:]), int(t[1:]), PROCESS.index(p))


def draw(data):
    rows = sorted((r for r in data["rows"] if r["status"] == "done"), key=lambda r: key(r["condition"]))
    plt.rcParams.update({"font.size": 8, "axes.edgecolor": MUTED, "xtick.color": MUTED, "ytick.color": MUTED, "axes.labelcolor": INK})
    fig, (a0, a1) = plt.subplots(2, 1, figsize=(12, 6.2), sharex=True)
    x = range(len(rows))
    for node, marker in (("remote", "s"), ("serializer", "o"), ("pad", "o")):
        ms = 4 if node == "remote" else 6
        a0.plot(x, [r["grade"]["outputs"][node]["margin_mv"] for r in rows], marker, color=COLORS[node], ms=ms, mec="white", mew=1,
                label=node + (" (comparison)" if node == "remote" else " (gate)"))
        a1.plot(x, [r["grade"]["outputs"][node]["spread_ui"] for r in rows], marker, color=COLORS[node], ms=ms, mec="white", mew=1)
    a0.axhline(75, color=MUTED, ls="--", lw=1)
    a0.text(len(rows) - 0.5, 77, "75 mV", ha="right", va="bottom", color=MUTED)
    a1.axhline(0.15, color=MUTED, ls="--", lw=1)
    a1.text(len(rows) - 0.5, 0.152, "0.15 UI", ha="right", va="bottom", color=MUTED)
    a0.set_ylabel("min signed margin (mV)")
    a1.set_ylabel("edge spread (UI)")
    a0.set_ylim(0, None)
    a1.set_ylim(0, 0.2)
    labels = [f"{r['condition'].split('_')[0].upper()}" for r in rows]
    a1.set_xticks(list(x), labels, fontsize=7)
    groups = {}
    for i, r in enumerate(rows):
        p, v, t = r["condition"].split("_")
        groups.setdefault((v, t), []).append(i)
    for (v, t), idx in groups.items():
        a1.text((idx[0] + idx[-1]) / 2, -0.09, f"{int(v[1:]) / 1000:.2f} V {t[1:]} °C", ha="center", va="top", fontsize=7, color=INK,
                transform=a1.get_xaxis_transform())
        for ax in (a0, a1):
            ax.axvspan(idx[0] - 0.5, idx[-1] + 0.5, color=GRID if (list(groups).index((v, t)) % 2) else "white", alpha=0.5, lw=0)
    n_pass = sum(r["grade"]["gates_pass"] for r in rows)
    a0.set_title(f"Full TX, extra2g=5 + driver {data['driver_params']}: {n_pass}/{len(rows)} conditions pass the serializer and pad gates",
                 loc="left", fontsize=9, color=INK)
    a0.legend(frameon=False, ncol=3, loc="lower left", fontsize=8)
    for ax in (a0, a1):
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", color=GRID, lw=0.8)
    fig.tight_layout()
    fig.subplots_adjust(bottom=0.12)
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=150)
    print(FIG.relative_to(ROOT))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect")
    a = ap.parse_args()
    draw(collect(a.collect) if a.collect else json.loads(DATA.read_text()))


if __name__ == "__main__":
    main()
