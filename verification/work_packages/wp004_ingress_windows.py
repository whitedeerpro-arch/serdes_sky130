"""WP-004: fixed-offset windows for measured ingress envelopes, in ps."""
import argparse
import hashlib
import json
import math
from pathlib import Path

from serdes_flow import balance

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ["docs/data/tx_ingress_card.json", "docs/design/tx_ingress.md",
          "src/serdes_flow/balance.py", "docs/work_packages/deliveries/WP-002/evidence.json",
          "verification/work_packages/wp004_ingress_windows.py", "docs/work_packages/WP-004-tx-capture-model.md"]
CONDITIONS = {"fs_v1650_t85", "fs_v1650_t-40", "ss_v1650_t85",
              "ss_v1650_t-40", "tt_v1800_t27", "ff_v1950_t-40"}
WINDOWS = (50, 100, 150, 200, 250, 500, 1000)
TOLERANCE_PS = 1e-9


def validate(card):
    if card.get("units") != "ps and fF; per-condition envelopes combine two static mux states and rising/falling data; not jitter or full-PVT qualification":
        raise ValueError("unexpected units")
    rows = card["envelopes"]
    expected = {(c, cell) for c in CONDITIONS for cell in ("lean", "reset")}
    keys = [(r["condition"], r["cell"]) for r in rows]
    if len(keys) != len(expected) or set(keys) != expected:
        raise ValueError("missing, duplicate or unexpected condition/cell")
    for r in rows:
        for name in ("tcq", "clock_to_cml"):
            lo, hi = r[name + "_min_ps"], r[name + "_max_ps"]
            if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (lo, hi)) or lo > hi:
                raise ValueError("invalid interval")
    return rows


def window(intervals, width):
    lo = max(-a for a, b in intervals)
    hi = min(width - b for a, b in intervals)
    if abs(hi - lo) <= TOLERANCE_PS:
        lo = hi = (lo + hi) / 2
    return {"phi_lo_ps": lo, "phi_hi_ps": hi, "feasible": lo <= hi,
            "minimum_window_ps": max(b for a, b in intervals) - min(a for a, b in intervals)}


def endpoint(value, width):
    structure = balance.Structure("wp004", "endpoint", {"clock": [], "data": [balance.Fixed(value)]}, {},
        [balance.Sample("data", "clock", 4000, 4000 - width, 0, "data")], ["data"])
    result = balance.evaluate(structure, {}, balance.Params(mismatch={"*": 0}, tap_error=0), {})[0][0]
    return {"arrival_ps": value, "margin_ps": result.margin, "phase_ps": float(result.values[0]),
            "mismatch_ps": result.mismatch}


def calculate(rows):
    output = {}
    for cell in ("lean", "reset"):
        output[cell] = {}
        for kind in ("tcq", "clock_to_cml"):
            intervals = {r["condition"]: [r[kind + "_min_ps"], r[kind + "_max_ps"]]
                         for r in rows if r["cell"] == cell}
            groups = {"all_measured": intervals}
            for process in ("fs", "ss", "tt", "ff"):
                groups[process] = {c: v for c, v in intervals.items() if c.startswith(process + "_")}
            results = {}
            for group, cases in groups.items():
                scans = {}
                for width in WINDOWS:
                    result = window(list(cases.values()), width)
                    if result["feasible"]:
                        phi = (result["phi_lo_ps"] + result["phi_hi_ps"]) / 2
                        result["phi_mid_ps"] = phi
                        result["balance_endpoints"] = {c: [endpoint(a + phi, width), endpoint(b + phi, width)]
                                                       for c, (a, b) in cases.items()}
                    else:
                        result["phi_mid_ps"] = None
                        result["balance_endpoints"] = None
                    scans[str(width)] = result
                results[group] = {"conditions": list(cases), "windows": scans}
            output[cell][kind] = {"intervals_ps": intervals, "groups": results}
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    rows = validate(json.loads((ROOT / INPUTS[0]).read_text()))
    observations = calculate(rows)
    margins = [ep["margin_ps"] for cell in observations.values() for kind in cell.values()
               for group in kind["groups"].values() for scan in group["windows"].values()
               if scan["balance_endpoints"] is not None for pair in scan["balance_endpoints"].values() for ep in pair]
    evidence = {"package_id": "WP-004", "execution_status": "complete",
        "inputs": [{"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()} for p in INPUTS],
        "observations": observations,
        "method": "Phase endpoints within 1e-9 ps are normalized to equality solely for floating-point rounding; zero width is zero margin.",
        "checks": [{"id": "balance_endpoints", "status": "pass" if min(margins) >= -1e-9 else "fail",
                    "detail": {"count": len(margins), "minimum_margin_ps": min(margins), "tolerance_ps": 1e-9}},
                   {"id": "scope", "status": "ungraded", "detail": "Fixed measured endpoints only; balance GRID repeats each value, mismatch and tap error zero; no independent 45-corner evidence."}],
        "unresolved": ["Actual update window and word-clock path/PVT unknown; remaining corners unmeasured.",
                       "Dynamic bit mapping and cross-word consistency unknown; no mismatch evaluation.",
                       "Two 8-bit transparent/hold groups add loading and same-edge hold competition; current clk-to-q minimum cannot prove hold under changed loading."]}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "evidence.json").write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
