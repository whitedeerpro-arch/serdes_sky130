"""Retrospective of the TX select-clock work (2026-10-31): figures and compact data from the
replay campaigns, written before their waveforms are deleted.

    uv run python analog/tx/serializer/tb/clock_replay/retrospective.py

Outputs (results/analog/tx/serializer/clock_replay/retrospective/<ts>/):
  retrospective.json  every number below, per version / point
  traces.npz          eye-density images (serializer and far end) and serializer-input clock
                      snippets, enough to redraw the figures
  versions_15.png     v1 / v2 / v2b / v3 at the 15 native V/T points: eye margin, spread, bit order
  eyes_15.png         serializer eyes, 4 versions x 4 representative points
  positions_15.png    select-clock position vs the r2 placement per version, one lane per process
  clocks_15.png       serializer-input clocks at FS 1.65 V 85 C and SS 1.65 V -40 C, per version
  power_15.png        distribution power per version and point
  study_4.png         r2 / v1 positioning modes at the four first native points
  windows.png         single-clock shift windows of the serializer (ideal clocks)
"""
import json
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import spice
from serdes_flow.corners import PROCESS
from serdes_flow.project import ROOT
from serdes_flow.waves import crossings

CR = ROOT / "results/analog/tx/serializer/clock_replay"
OUT = CR / "retrospective"
UI = 250e-12
TARGET = {"500": 0.162, "1g": 0.320, "2g": 0.982}
SER = {"250": "d250", "500": "d500", "1g": "d1g", "2g": "ds"}
PERIOD = {"250": 4e-9, "500": 2e-9, "1g": 1e-9, "2g": 0.5e-9}
WIN = (20e-9, 60e-9)

VERSIONS = {   # label -> campaign, per-point overrides
    "v1": (CR / "v1_native_20261031T105731Z", {}),
    "v2": (CR / "v2_native_20261031T112025Z", {}),
    "v2b": (CR / "v2b_native_20261031T123344Z", {}),
    "v3 (S4)": (CR / "v3_word_20261031T140506Z", {"fs_v1650_t-40": CR / "v3_word_ic_20261031T145243Z"}),
}
STUDY4 = {     # r2-load recordings, four native points (+ FF cold where run)
    "r2 native": CR / "native_20261031T050022Z",
    "r2 calibrated": CR / "calibrated_20261031T051030Z",
    "r2 target": CR / "r2dist_target_20261031T051906Z",
    "v1 target": CR / "dist_v1_target_20261031T053147Z",
    "v1 fixed": CR / "dist_v1_fixed_20261031T054209Z",
    "v1 fixed, 2G +0.2 UI": CR / "dist_v1_fixed_2g+0.2_20261031T055429Z",
}
WINDOW = ROOT / "results/analog/tx/serializer/clock_states/window_20261030T225151Z/summary.json"
SHOW = ("tt_v1800_t27", "ss_v1650_t85", "fs_v1650_t85", "ff_v1950_t-40")
COLORS = ("#2a78d6", "#eb6834", "#1baf7a", "#c98500")
MARKERS = ("o", "s", "D", "^")
INK, MUTED, GRID = "#1a212b", "#5a6577", "#e3e7ee"


def centroid(t, y, period):
    e, pol = crossings(t, y)
    ph = np.where(pol > 0, e, e - period / 2) / period
    return float(np.angle(np.mean(np.exp(2j * np.pi * ph))) / (2 * np.pi)) * period


def eye_image(t, y, nx=120, ny=90, vmax=0.36):
    sel = (t > WIN[0]) & (t < WIN[1])
    t, y = t[sel], y[sel]
    e, _ = crossings(t, y)
    ph = float(np.angle(np.mean(np.exp(2j * np.pi * e / UI))) / (2 * np.pi)) * UI
    tt = np.arange(t[0], t[-1], 1e-12)                 # uniform resampling: density is per time
    yy = np.interp(tt, t, y)
    x = ((tt - ph) / UI + 0.5) % 2.0 - 0.5
    h, _, _ = np.histogram2d(x, yy, bins=(nx, ny), range=((-0.5, 1.5), (-vmax, vmax)))
    return h.T.astype(np.float32)


def run_dir(camp, point, over):
    return (over.get(point, camp)) / point / "run" / "waveforms.raw"


def collect_versions():
    data, traces = {}, {}
    for label, (camp, over) in VERSIONS.items():
        rows = {r["point"]: r for r in json.loads((camp / "summary.json").read_text())}
        for p, c in over.items():
            rows[p] = {r["point"]: r for r in json.loads((c / "summary.json").read_text())}[p]
        data[label] = {}
        for p in sorted(rows):
            r = rows[p]
            w = spice.Waves(run_dir(camp, p, over))
            sel = (w.t > WIN[0]) & (w.t < WIN[1])
            cen = {k: centroid(w.t[sel], w[v][sel], PERIOD[k]) for k, v in SER.items()}
            pos = {k: float((((cen[k] - cen["250"]) / UI - TARGET[k]) + 0.5) % 1.0 - 0.5) for k in TARGET}
            s, f = r["nodes"]["serializer"], r["nodes"]["far"]
            data[label][p] = dict(
                eye_mv=s["order_free"]["eye_min_abs_v"] * 1e3, spread_ui=s["order_free"]["edge_spread_ui"],
                in_order=bool(s["order_free"]["in_order"]), far_eye_mv=f["order_free"]["eye_min_abs_v"] * 1e3,
                far_spread_ui=f["order_free"]["edge_spread_ui"], clock_pp_mv={k: float(np.ptp(w[v][sel]) * 1e3) for k, v in SER.items()},
                position_error_ui=pos, pclock_mw=float(np.mean(w["pclock"][sel]) * 1e3))
            key = f"{label}|{p}"
            if p in SHOW:
                traces[f"eye_ser|{key}"] = eye_image(w.t, w["dout"])
                traces[f"eye_far|{key}"] = eye_image(w.t, w["line_rx"], vmax=0.30)
            if p in ("fs_v1650_t85", "ss_v1650_t-40"):
                e, pol = crossings(w.t, w["d250"])
                t0 = e[(pol < 0) & (e > 30e-9)][0]
                tt = t0 + np.arange(-2 * UI, 18 * UI, 2e-12)
                traces[f"clk|{key}"] = np.vstack([(tt - t0) / UI] + [np.interp(tt, w.t, w[v]) for v in SER.values()]).astype(np.float32)
            print(f"{label:8s} {p:14s} eye {data[label][p]['eye_mv']:6.1f} mV {data[label][p]['spread_ui']:.3f} UI "
                  f"{'in order' if data[label][p]['in_order'] else 'permuted'}  P {data[label][p]['pclock_mw']:.1f} mW", flush=True)
    return data, traces


def collect_study4():
    out = {}
    for label, camp in STUDY4.items():
        rows = json.loads((camp / "summary.json").read_text())
        out[label] = {r["point"]: dict(eye_mv=r["nodes"]["serializer"]["order_free"]["eye_min_abs_v"] * 1e3,
                                        spread_ui=r["nodes"]["serializer"]["order_free"]["edge_spread_ui"],
                                        in_order=bool(r["nodes"]["serializer"]["order_free"]["in_order"]))
                      for r in rows}
    return out


def collect_windows():
    rows = json.loads(WINDOW.read_text())
    out = {}
    for r in rows:
        of = r["nodes"]["serializer"]["order_free"]
        out.setdefault(r["condition"], {}).setdefault(r["clock"], []).append(
            (r["shift_ui"], of["eye_min_abs_v"] * 1e3, of["edge_spread_ui"]))
    return out


def unwrap(values):
    """Fold on 1 UI around the median so a cluster straddling +-0.5 is not split."""
    v = np.asarray(values, dtype=float)
    med = np.median(v)
    return med + ((v - med + 0.5) % 1.0 - 0.5)


def unwrap_positions(data):
    for d in data.values():
        pts = sorted(d)
        for k in TARGET:
            u = unwrap([d[p]["position_error_ui"][k] for p in pts])
            for p, x in zip(pts, u):
                d[p]["position_error_ui"][k] = float(x)


def order_points(points):
    return sorted(points, key=lambda p: (PROCESS.index(p.split("_")[0]), p))


def fig_versions(data, path):
    pts = order_points(next(iter(data.values())))
    fig, axes = plt.subplots(2, 1, figsize=(12, 6.4), sharex=True)
    x = np.arange(len(pts))
    for k, (label, d) in enumerate(data.items()):
        off = (k - 1.5) * 0.17
        for i, p in enumerate(pts):
            r = d[p]
            face = COLORS[k] if r["in_order"] else "none"
            axes[0].plot(x[i] + off, r["eye_mv"], MARKERS[k], ms=6, mfc=face, mec=COLORS[k], label=label if i == 0 else None)
            axes[1].plot(x[i] + off, r["spread_ui"], MARKERS[k], ms=6, mfc=face, mec=COLORS[k])
    axes[0].axhline(75, color=INK, lw=0.8, ls="--")
    axes[1].axhline(0.15, color=INK, lw=0.8, ls="--")
    axes[0].set_ylabel("serializer eye (mV, order-free)")
    axes[1].set_ylabel("edge spread (UI)")
    axes[1].set_ylim(0, 1.0)
    axes[1].set_xticks(x, [p.replace("_v", "\n").replace("_t", " ") for p in pts], fontsize=7)
    for ax in axes:
        ax.grid(axis="y", color=GRID)
        ax.set_axisbelow(True)
    axes[0].legend(frameon=False, ncol=4, fontsize=8, loc="lower left")
    passes = {l: dict(gates=sum(r["eye_mv"] >= 75 and r["spread_ui"] <= 0.15 for r in d.values()),
                      in_order=sum(r["eye_mv"] >= 75 and r["spread_ui"] <= 0.15 and r["in_order"] for r in d.values()))
              for l, d in data.items()}
    fig.suptitle("TX select clocks from the native PLL r4 taps, 15 V/T points (filled = original bit order; dashed = gate)\n"
                 + "   ".join(f"{l}: {n['gates']}/15 within gates ({n['in_order']} in original order)" for l, n in passes.items()),
                 fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return passes


def fig_eyes(data, traces, path, kind="ser"):
    labels = list(data)
    fig, axes = plt.subplots(len(SHOW), len(labels), figsize=(3.2 * len(labels), 2.3 * len(SHOW)), squeeze=False)
    vmax = 0.36 if kind == "ser" else 0.30
    for i, p in enumerate(SHOW):
        for j, l in enumerate(labels):
            ax = axes[i, j]
            img = traces[f"eye_{kind}|{l}|{p}"]
            ax.imshow(np.log1p(img), origin="lower", aspect="auto", extent=(-0.5, 1.5, -vmax, vmax), cmap="Blues")
            r = data[l][p]
            m, s = (r["eye_mv"], r["spread_ui"]) if kind == "ser" else (r["far_eye_mv"], r["far_spread_ui"])
            ax.set_title(f"{l} · {p}\n{m:.0f} mV / {s:.3f} UI{'' if r['in_order'] else ' (permuted)'}", fontsize=8)
            ax.tick_params(labelsize=6)
            if j == 0:
                ax.set_ylabel("V", fontsize=7)
            if i == len(SHOW) - 1:
                ax.set_xlabel("UI", fontsize=7)
    fig.suptitle(("serializer node" if kind == "ser" else "far end (C2 RLC)") + " eye density, 20-60 ns, log scale", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def fig_positions(data, path):
    labels = list(data)
    fig, axes = plt.subplots(len(labels), 3, figsize=(11, 1.8 * len(labels)), sharex=True, squeeze=False)
    for i, l in enumerate(labels):
        for j, k in enumerate(TARGET):
            ax = axes[i, j]
            ax.axvspan(-0.25, 0.25, color="#2b5c9a", alpha=0.12, lw=0)
            for pi, proc in enumerate(PROCESS):
                v = [r["position_error_ui"][k] for p, r in data[l].items() if p.startswith(proc)]
                if v:
                    ax.plot([min(v), max(v)], [pi, pi], color=INK, lw=4, alpha=0.35, solid_capstyle="round")
                    ax.plot(v, [pi] * len(v), "o", ms=3, color=INK)
            ax.set_yticks(range(len(PROCESS)), [p.upper() for p in PROCESS], fontsize=7)
            ax.invert_yaxis()
            ax.set_xlim(-0.5, 0.5)
            ax.set_title(f"{l}: {k.upper()} vs 250M", fontsize=8)
            ax.tick_params(axis="x", labelsize=7)
    for ax in axes[-1]:
        ax.set_xlabel("position - r2 placement (UI, folded on 1 UI)", fontsize=7)
    fig.suptitle("select-clock positions at the serializer per process (band = one chip over V/T; shaded = hot-corner window +-0.25 UI)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def fig_clocks(data, traces, path):
    pts = ("fs_v1650_t85", "ss_v1650_t-40")
    fig, axes = plt.subplots(4, 2, figsize=(12, 7.5), sharex=True)
    for j, p in enumerate(pts):
        for k, l in enumerate(data):
            a = traces[f"clk|{l}|{p}"]
            for i, clk in enumerate(SER):
                axes[i, j].plot(a[0], a[1 + i], color=COLORS[k], lw=1.0, label=l if (i == 0 and j == 0) else None)
        for i, clk in enumerate(SER):
            axes[i, j].set_ylabel(f"{clk} (V)", fontsize=8)
            axes[i, j].axhline(0, color=MUTED, lw=0.5)
            axes[i, j].grid(axis="x", color=GRID)
        axes[0, j].set_title(p, fontsize=9)
        axes[-1, j].set_xlabel("UI after a 250M falling crossing", fontsize=8)
    axes[0, 0].legend(frameon=False, ncol=4, fontsize=8)
    fig.suptitle("serializer-input select clocks per version (start states differ between versions: whole-VCO-cycle shifts)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def fig_power(data, path):
    pts = order_points(next(iter(data.values())))
    fig, ax = plt.subplots(figsize=(12, 3.2))
    x = np.arange(len(pts))
    for k, (l, d) in enumerate(data.items()):
        ax.plot(x, [d[p]["pclock_mw"] for p in pts], MARKERS[k] + "-", color=COLORS[k], ms=5, lw=1, label=l)
    ax.set_xticks(x, [p.replace("_v", "\n").replace("_t", " ") for p in pts], fontsize=7)
    ax.set_ylabel("distribution power (mW)")
    ax.grid(axis="y", color=GRID)
    ax.legend(frameon=False, ncol=4, fontsize=8)
    ax.set_title("clock distribution supply power (v3 includes three dummy tap input stages kept for the recording load)", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_study4(study, path):
    pts = order_points({p for d in study.values() for p in d})
    fig, axes = plt.subplots(1, 2, figsize=(12, 3.6))
    x = np.arange(len(pts))
    n = len(study)
    for k, (l, d) in enumerate(study.items()):
        off = (k - (n - 1) / 2) * 0.13
        for metric, ax in zip(("eye_mv", "spread_ui"), axes):
            xs = [x[i] + off for i, p in enumerate(pts) if p in d]
            ys = [d[p][metric] for p in pts if p in d]
            ax.bar(xs, ys, width=0.12, color=plt.cm.tab10(k), label=l if metric == "eye_mv" else None)
    axes[0].axhline(75, color=INK, lw=0.8, ls="--")
    axes[1].axhline(0.15, color=INK, lw=0.8, ls="--")
    axes[0].set_ylabel("eye (mV, order-free)")
    axes[1].set_ylabel("edge spread (UI)")
    axes[1].set_ylim(0, 0.6)
    for ax in axes:
        ax.set_xticks(x, [p.replace("_v", "\n").replace("_t", " ") for p in pts], fontsize=7)
        ax.grid(axis="y", color=GRID)
        ax.set_axisbelow(True)
    axes[0].legend(frameon=False, fontsize=7, ncol=2)
    fig.suptitle("first native points (r2-load recordings): position vs clock quality", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def fig_windows(win, path):
    conds = sorted(win)
    fig, axes = plt.subplots(2, len(conds), figsize=(3.3 * len(conds), 5.2), sharex=True, squeeze=False)
    for j, c in enumerate(conds):
        for k, (clk, rows) in enumerate(sorted(win[c].items())):
            rows = sorted(rows + [(0.0, np.nan, np.nan)])
            xs = [r[0] for r in rows]
            axes[0, j].plot(xs, [r[1] for r in rows], MARKERS[k] + "-", color=COLORS[k], ms=4, lw=1, label=clk)
            axes[1, j].plot(xs, [r[2] for r in rows], MARKERS[k] + "-", color=COLORS[k], ms=4, lw=1)
        axes[0, j].axhline(75, color=INK, lw=0.8, ls="--")
        axes[1, j].axhline(0.15, color=INK, lw=0.8, ls="--")
        axes[0, j].set_title(c, fontsize=8)
        axes[1, j].set_xlabel("single-clock shift (UI)", fontsize=8)
        axes[1, j].set_ylim(0, 0.9)
    axes[0, 0].set_ylabel("eye (mV)")
    axes[1, 0].set_ylabel("spread (UI)")
    axes[0, 0].legend(frameon=False, fontsize=7)
    fig.suptitle("serializer windows, r2 with ideal clocks: one clock shifted, others at the calibrated placement", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def main():
    out = OUT / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True)
    data, traces = collect_versions()
    unwrap_positions(data)
    study, win = collect_study4(), collect_windows()
    passes = fig_versions(data, out / "versions_15.png")
    fig_eyes(data, traces, out / "eyes_15.png", "ser")
    fig_eyes(data, traces, out / "eyes_far_15.png", "far")
    fig_positions(data, out / "positions_15.png")
    fig_clocks(data, traces, out / "clocks_15.png")
    fig_power(data, out / "power_15.png")
    fig_study4(study, out / "study_4.png")
    fig_windows(win, out / "windows.png")
    np.savez_compressed(out / "traces.npz", **traces)
    sources = {l: [str(c.relative_to(ROOT))] + [str(x.relative_to(ROOT)) for x in o.values()] for l, (c, o) in VERSIONS.items()}
    summary = dict(sources=dict(versions=sources, study4={l: str(c.relative_to(ROOT)) for l, c in STUDY4.items()},
                                windows=str(WINDOW.relative_to(ROOT))),
                   passes_15=passes, versions=data, study4=study, windows=win)
    (out / "retrospective.json").write_text(json.dumps(summary, indent=1, default=float))
    for l, d in data.items():
        v = list(d.values())
        print(f"{l:8s} gates {passes[l]['gates']}/15 (in order {passes[l]['in_order']})  worst eye {min(r['eye_mv'] for r in v):6.1f} mV  worst spread {max(r['spread_ui'] for r in v):.3f}"
              f"  position span 500/1G/2G " + "/".join(f"{np.ptp([r['position_error_ui'][k] for r in v]):.2f}" for k in TARGET)
              + f" UI  power {min(r['pclock_mw'] for r in v):.1f}-{max(r['pclock_mw'] for r in v):.1f} mW")
    print(out.relative_to(ROOT))


if __name__ == "__main__":
    main()
