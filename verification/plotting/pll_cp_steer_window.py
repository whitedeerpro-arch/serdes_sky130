"""Collect complete steering-CP DC sweeps and compare the coarse window boundary.

No simulation.  --campaign identifies an immutable prepared campaign; incomplete
groups are rejected before replacing the published data or figures.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from serdes_flow import project, spice
from serdes_flow.corners import Condition, grid45

ROOT = project.ROOT
MONITOR = ROOT / "results/analog/pll/coarse/window_dc/20261109T052834Z/summary.json"
THRESHOLD_MC = ROOT / "results/analog/pll/coarse/window_mc/20261109T055255Z/summary.json"
DATA = ROOT / "docs/data/pll_cp_steer_window.json"
CATALOG = ROOT / "results/catalog/pll_cp_steer_window.json"
FIG = ROOT / "docs/figures/clocking/pll/charge_pump/cp_steer_control_window"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_polarity(path, supply):
    """The source is positive and sink negative at midrail in this E-source bench."""
    waves = spice.Waves(path)
    mid = int(np.argmin(np.abs(waves.t - supply / 2)))
    if waves["i(eu)"][mid] <= 0 or waves["i(ed)"][mid] >= 0:
        raise ValueError(f"reversed source/sink current at midrail: {path}")


def collect(campaign):
    spec = importlib.util.spec_from_file_location("cp_steer_dc", ROOT / "analog/pll/cp/tb/dc/window_steer.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    plan = runner.verify(campaign)
    conditions = {c.tag: c for c in grid45()}
    rows, inputs = [], {}
    for case in plan["cases"]:
        conds = [conditions[t] for t in case["tags"]]
        found = runner.completed(campaign, case["name"], campaign / case["deck"], conds, plan["droop"])
        if found is None:
            raise ValueError(f"incomplete CP group: {case['name']}")
        run, measures = found
        inputs[str((run / "execution.json").relative_to(ROOT))] = sha(run / "execution.json")
        for c in conds:
            path = run / f"{c.tag}.raw"
            require_polarity(path, c.supply)
            inputs[str(path.relative_to(ROOT))] = sha(path)
            rows.append(dict(condition=c.tag, passive=case["passive"], supply=c.supply,
                             run=str(run.relative_to(ROOT)), **measures[c.tag]))
    if len(rows) != 135 or len({(r["condition"], r["passive"]) for r in rows}) != 135:
        raise ValueError("expected all 135 distinct MOS/V/T/resistor conditions")
    monitor = json.loads(MONITOR.read_text())
    if monitor["args"]["code_hi"] != 3 or monitor["args"]["code_lo"] != 5:
        raise ValueError("monitor threshold codes changed")
    def tag(r):
        return Condition(r["process"], r["supply"], r["temp"]).tag
    mon = {(tag(r), r["rcorner"]): r for r in monitor["rows"]}
    if len(mon) != 135 or not all(r["function"] for r in mon.values()):
        raise ValueError("monitor grid incomplete or function failed")
    for r in rows:
        m = mon[(r["condition"], r["passive"])]
        r.update(vlo=m["vlo"], vhi=m["vhi"],
                 upper_gap_mv=(r["hi"] - m["vhi"]) * 1000,
                 lower_gap_mv=(m["vlo"] - r["lo"]) * 1000)
    mc = json.loads(THRESHOLD_MC.read_text())
    if mc["args"]["code_hi"] != 3:
        raise ValueError("MC upper threshold code changed")
    # The MC sections have nominal resistor process; match only R tt.  These
    # are separate experiments, not paired CP/monitor chip simulations.
    lookup = {(r["condition"], r["passive"]): r for r in rows}
    tails = []
    for cond, s in mc["points"].items():
        c = Condition.parse(cond)
        cp = lookup[(cond, "tt")]
        upper = c.supply - s["drop"]["mean"] + s["k"] * s["drop"]["sd"]
        tails.append(dict(condition=cond, samples=s["samples"], k=s["k"],
                          vhi_mean=c.supply - s["drop"]["mean"], vhi_upper_component_screen=upper,
                          cp_nominal_hi=cp["hi"], upper_gap_mv=(cp["hi"] - upper) * 1000,
                          spec_status="ungraded"))
    inputs.update({str(p.relative_to(ROOT)): sha(p) for p in (MONITOR, THRESHOLD_MC, campaign / "plan.json")})
    return dict(campaign=str(campaign.relative_to(ROOT)), cp_params=plan["cp_params"], droop=plan["droop"],
                scope="135 static real-bias k4 steering-CP conditions; DC window diagnostic, not PLL signoff",
                grid_step_v=.01, inputs_sha256=inputs, collector_sha256=sha(Path(__file__)), rows=rows,
                threshold_component_screens=tails,
                limitations=["CP edge is the last sampled point within 5% of each branch's own VDD/2 current; 10 mV grid",
                             "Monitor senses LF z; CP sees ctrl. Ripple, Rz drop and comparator/decision delay are not budgeted here",
                             "MC is monitor-ladder-only at R tt, five points; no paired CP mismatch or yield assertion",
                             "No dynamic switching, startup, noise or hl/lh qualification"])


def draw(data):
    process = {p: i for i, p in enumerate(("tt", "ss", "ff", "sf", "fs"))}
    rows = sorted(data["rows"], key=lambda r: (process[Condition.parse(r["condition"]).process],
                                               r["supply"], Condition.parse(r["condition"]).temp,
                                               ("tt", "hh", "ll").index(r["passive"])))
    x = np.arange(len(rows))
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})
    fig, (a, b) = plt.subplots(2, 1, figsize=(12, 6.7), sharex=True)
    a.plot(x, [(r["supply"] - r["hi"]) * 1000 for r in rows], ".", label="CP 5% upper edge: VDD - hi")
    a.plot(x, [(r["supply"] - r["vhi"]) * 1000 for r in rows], ".", label="Coarse upper threshold: VDD - vhi")
    a.set_ylabel("Drop from VDD (mV)")
    a.set_title("k4 steering CP vs coarse-control boundary | 135 static conditions | 10 mV sweep grid", loc="left")
    a.legend(frameon=False, ncol=2)
    b.plot(x, [r["upper_gap_mv"] for r in rows], ".", label="CP hi minus monitor vhi (nominal)")
    b.axhline(0, color="0.4", lw=1)
    b.set_ylabel("DC upper gap (mV)")
    b.legend(frameon=False)
    for i, p in enumerate(process):
        indices = [k for k, r in enumerate(rows) if Condition.parse(r["condition"]).process == p]
        for ax in (a, b):
            if i % 2 == 0:
                ax.axvspan(indices[0] - .5, indices[-1] + .5, color="0.94", zorder=-1)
            ax.grid(axis="y", alpha=.2)
    b.set_xticks([13 + 27 * i for i in range(5)], [p.upper() for p in process])
    b.set_xlabel("Within MOS: VDD, temperature, resistor tt / hh / ll")
    fig.text(.01, .015, "Nominal DC boundary comparison. Separate ladder MC screens are in JSON; dynamic margin and CP mismatch remain open.", fontsize=8)
    fig.tight_layout(rect=(0, .04, 1, 1))
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG.with_suffix(".png"), dpi=150)
    fig.savefig(FIG.with_suffix(".svg"))
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--campaign", type=Path, required=True)
    args = ap.parse_args()
    data = collect(args.campaign.resolve())
    payload = json.dumps(data, indent=2, allow_nan=False) + "\n"
    DATA.write_text(payload)
    CATALOG.write_text(payload)
    draw(data)
    print(f"135 complete conditions; minimum nominal upper gap {min(r['upper_gap_mv'] for r in data['rows']):.2f} mV")


if __name__ == "__main__":
    main()
