"""Read-only WP-001 audit of the two fixed historical PLL waveforms.

No simulator is called. Frequencies and crossings use the working-tree shared
measurement functions. A failed check still produces the complete evidence.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from serdes_flow import clock, spice  # noqa: E402

START_S = 8e-9
STOP_S = 24e-9
STOP_RTOL = 1e-7
VDD_V = 1.95
BOUNDARY_ID = "pll_r5_cold_prebiased_state_v1"
CASES = {
    "ll": "results/analog/pll/convergence/20261106T151716Z/ff_v1950_t-40_ll_frontend_sparse_prebiased_native",
    "hh": "results/analog/pll/convergence/20261106T152241Z/ff_v1950_t-40_hh_frontend_sparse_prebiased_native",
}
DIVIDERS = {"div2": ("p02p", "p02n", 2), "div4": ("p04p", "p04n", 4),
            "div8": ("p08p", "p08n", 8)}
CMOS = {**{f"c{i}p": (f"c{i}p", 1, True) for i in range(4)},
        "fb0": ("fb0", 8, False),
        **{f"fb{i}": (f"xpll.fb{i}", 8, False) for i in range(1, 4)}}
CONTEXT_FILES = ["AGENTS.md", "README.md", "docs/work_packages/README.md",
                 "docs/work_packages/WP-001-pll-waveform-audit.md",
                 "src/serdes_flow/clock.py", "src/serdes_flow/spice.py",
                 "src/serdes_flow/waves.py", "config/boundary_conditions.json",
                 "verification/work_packages/wp001_pll_waveforms.py"]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check(report: dict, case: str, name: str, status: str, **detail) -> None:
    assert status in {"pass", "fail", "ungraded", "missing"}
    report["checks"].append({"id": f"{case}.{name}", "status": status,
                             "detail": detail})


def problem(report: dict, case: str, item: str, reason: str) -> None:
    report["unresolved"].append({"case": case, "item": item, "reason": reason})
    report["execution_status"] = "partial"


def line_records(text: str, pattern: str) -> list[dict]:
    return [{"line": i, "text": line} for i, line in enumerate(text.splitlines(), 1)
            if re.search(pattern, line, re.I)]


def deck_observations(text: str) -> dict:
    """Keep actual deck lines and selected IC values, rather than summary labels."""
    ic_lines = line_records(text, r"^\s*\.ic\s")
    selected = {"vdd", "bias_vbg", "vgi_bias", "vbias", "ctrl", "rst_b",
                "cfg0", "cfg1", "cfg2", "cfg3", "xpll.v0p", "xpll.v0n",
                "p02p", "p02n", "p04p", "p04n", "p08p", "p08n",
                "c0p", "fb0", "xpll.fb1"}
    ic_values = []
    for record in ic_lines:
        for match in re.finditer(r"v\(([^)]+)\)\s*=\s*(\S+)", record["text"], re.I):
            if match[1].lower() in selected:
                ic_values.append({**record, "node": match[1],
                                  "voltage_v": spice.spice_number(match[2])})
    return {
        "model_lib_lines": line_records(text, r"^\s*\.lib\s"),
        "tran_lines": line_records(text, r"^\s*\.?tran\s"),
        "has_uic": bool(re.search(r"^\s*\.?tran\s+.*\buic\b", text, re.M | re.I)),
        "ic_count": len(ic_lines),
        "ic_line_range": [ic_lines[0]["line"], ic_lines[-1]["line"]] if ic_lines else None,
        "selected_initial_voltages": ic_values,
        "supply_control_bias_lines": line_records(
            text, r"^\s*(?:\.param\s+supply|\.temp\s|Vdd\s|Vctrl\s|Vcode\d\s|"
            r"Vreset\s|Ikick\s|Xbias_ref\s|Vbias_i\d\s|XIref\s|Xref\s|Xpll\s)"),
        "include_lines": line_records(text, r"^\s*\.include\s"),
        "source_snapshot_scope": "Include paths are preserved from the deck; included source files are not re-opened or compared to current DUTs.",
    }


def waveform_stats(waves, positive: str, negative: str | None = None) -> dict:
    y = waves[positive] - waves[negative] if negative else waves[positive]
    centered = y if negative else y - VDD_V / 2
    stats = clock.period_stats(waves.t, centered, start=START_S, stop=STOP_S)
    mask = (waves.t >= START_S) & (waves.t <= STOP_S)
    rise = clock.edges(waves.t, centered, start=START_S, stop=STOP_S)
    return {"nodes": [positive, negative] if negative else [positive],
            "crossing_level_v": 0.0 if negative else VDD_V / 2,
            "period_stats": stats,
            "window_min_v": float(np.min(y[mask])),
            "window_max_v": float(np.max(y[mask])),
            "window_amplitude_pp_v": float(np.ptp(y[mask])),
            "positive_edges_s": rise.tolist()}


def edge_diagnostic(reference: list[float], signal: list[float], divisor: int) -> dict:
    ref, sig = np.asarray(reference), np.asarray(signal)
    keep = (sig > ref[0]) & (sig < ref[-1]) if len(ref) >= 2 else np.zeros(len(sig), bool)
    selected = sig[keep]
    seq = np.interp(selected, ref, np.arange(len(ref))) if len(ref) >= 2 else np.array([])
    intervals = np.diff(seq)
    bad = np.flatnonzero(np.abs(intervals - divisor) > 0.25)
    anomalies = []
    for i in bad:
        brackets = []
        for edge in selected[i:i + 2]:
            right = int(np.searchsorted(ref, edge, side="right"))
            brackets.append({"vco_edge_indices": [right - 1, right],
                             "vco_edge_times_s": ref[right - 1:right + 1].tolist()})
        anomalies.append({"interval_index": int(i),
                          "divider_edge_indices_in_window": np.flatnonzero(keep)[i:i + 2].tolist(),
                          "divider_edge_times_s": selected[i:i + 2].tolist(),
                          "reference_cycle_indices": seq[i:i + 2].tolist(),
                          "reference_cycle_difference": float(intervals[i]),
                          "adjacent_vco_edges": brackets})
    return {"divisor": divisor, "tolerance_reference_cycles": 0.25,
            "all_divider_edges_s": sig.tolist(),
            "retained_edge_indices_in_window": np.flatnonzero(keep).tolist(),
            "retained_divider_edges_s": selected.tolist(),
            "excluded_unbracketed_edge_indices_in_window": np.flatnonzero(~keep).tolist(),
            "excluded_unbracketed_edges_s": sig[~keep].tolist(),
            "reference_cycle_indices": seq.tolist(),
            "reference_cycle_differences": intervals.tolist(),
            "anomaly_interval_indices": bad.tolist(), "anomalies": anomalies,
            "interval_count": len(intervals),
            "max_absolute_error_reference_cycles": float(np.max(np.abs(intervals - divisor))) if len(intervals) else None}


def missing_measurements(report: dict, case: str, obs: dict, reason: str) -> None:
    obs["signals"] = {name: None for name in ("vco", *DIVIDERS, *CMOS)}
    obs["edge_diagnostics"] = {name: None for name in DIVIDERS}
    for name in (*DIVIDERS, *CMOS):
        check(report, case, f"functional.{name}", "missing", reason=reason)
    for name in DIVIDERS:
        check(report, case, f"edge.{name}", "missing", reason=reason)


def measure(report: dict, case: str, obs: dict, waves) -> None:
    signals = obs["signals"] = {}
    diagnostics = obs["edge_diagnostics"] = {}
    definitions = {"vco": ("xpll.v0p", "xpll.v0n"),
                   **{name: (p, n) for name, (p, n, _) in DIVIDERS.items()},
                   **{name: (node, None) for name, (node, _, _) in CMOS.items()}}
    errors = {}
    for name, nodes in definitions.items():
        try:
            signals[name] = waveform_stats(waves, *nodes)
        except Exception as exc:
            signals[name] = None
            errors[name] = f"{type(exc).__name__}: {exc}"
            problem(report, case, name, errors[name])
    vco = signals["vco"]
    vco_stats = vco["period_stats"] if vco else None
    check(report, case, "vco_reference", "missing" if vco is None else "fail" if vco_stats is None else "pass",
          reason=errors.get("vco"), period_stats=vco_stats,
          criterion="Reference is measurable by clock.period_stats; no absolute 2 GHz accuracy gate is assigned here.")
    for name, (_, _, divisor) in DIVIDERS.items():
        signal = signals[name]
        stats = signal["period_stats"] if signal else None
        ratio_error = abs(stats["frequency_hz"] / (vco_stats["frequency_hz"] / divisor) - 1) if stats and vco_stats else None
        status = "missing" if signal is None or vco is None else "fail" if ratio_error is None or ratio_error > 0.01 else "pass"
        check(report, case, f"functional.{name}", status,
              period_stats=stats, target_frequency_hz=vco_stats["frequency_hz"] / divisor if vco_stats else None,
              relative_frequency_error=ratio_error, maximum_relative_error=0.01,
              reason=errors.get(name) or errors.get("vco"))
        if signal is None or vco is None:
            diagnostics[name] = None
            check(report, case, f"edge.{name}", "missing", reason=errors.get(name) or errors.get("vco"))
            continue
        diag = diagnostics[name] = edge_diagnostic(vco["positive_edges_s"], signal["positive_edges_s"], divisor)
        status = "ungraded" if diag["interval_count"] < 2 else "fail" if diag["anomalies"] else "pass"
        check(report, case, f"edge.{name}", status,
              interval_count=diag["interval_count"], anomaly_interval_indices=diag["anomaly_interval_indices"],
              diagnostic_path=f"observations.cases.{case}.edge_diagnostics.{name}",
              criterion=f"Adjacent interpolated VCO cycle differences must be {divisor} +/- 0.25; at least 2 intervals.",
              interpretation="Loose missing/extra-edge diagnostic; not a phase-noise or jitter acceptance metric.")
    for name, (_, divisor, duty_gate) in CMOS.items():
        signal = signals[name]
        stats = signal["period_stats"] if signal else None
        ratio_error = abs(stats["frequency_hz"] / (vco_stats["frequency_hz"] / divisor) - 1) if stats and vco_stats else None
        gates = {"frequency": ratio_error is not None and ratio_error <= 0.01,
                 "low_level": signal is not None and signal["window_min_v"] < 0.2 * VDD_V,
                 "high_level": signal is not None and signal["window_max_v"] > 0.8 * VDD_V}
        if duty_gate:
            gates["duty"] = bool(stats and stats["duty"] is not None and 0.45 <= stats["duty"] <= 0.55)
        status = "missing" if signal is None or vco is None else "pass" if all(gates.values()) else "fail"
        check(report, case, f"functional.{name}", status, gates=gates,
              frequency_hz=stats["frequency_hz"] if stats else None,
              target_frequency_hz=vco_stats["frequency_hz"] / divisor if vco_stats else None,
              relative_frequency_error=ratio_error, maximum_relative_error=0.01,
              duty=stats["duty"] if stats else None, duty_gate=[0.45, 0.55] if duty_gate else None,
              low_level_v=signal["window_min_v"] if signal else None,
              low_level_must_be_below_v=0.2 * VDD_V,
              high_level_v=signal["window_max_v"] if signal else None,
              high_level_must_be_above_v=0.8 * VDD_V,
              level_definition="Minimum/maximum stored samples in 8-24 ns; no overshoot gate.",
              reason=errors.get(name) or errors.get("vco"))
    check(report, case, "amplitudes_and_cmos_peaks", "ungraded",
          detail="Reported in signals.*.window_min_v/window_max_v/window_amplitude_pp_v; no additional amplitude or overshoot specification is assigned.")


def audit_case(report: dict, case: str, directory: str, boundary: dict | None) -> None:
    obs = report["observations"]["cases"][case] = {"directory": directory}
    texts = {}
    for name in ("tb.cir", "execution.json", "simulator.log"):
        path = ROOT / directory / name
        if path.is_file():
            texts[name] = path.read_text(errors="replace")
    deck = texts.get("tb.cir")
    try:
        execution = json.loads(texts["execution.json"]) if "execution.json" in texts else None
    except (ValueError, TypeError) as exc:
        execution = None
        problem(report, case, "execution.json", f"{type(exc).__name__}: {exc}")
    obs["execution"] = execution
    check(report, case, "execution", "missing" if execution is None else "pass" if execution.get("exit_code") == 0 and execution.get("timed_out") is False and not execution.get("log_failures") else "fail",
          exit_code=execution.get("exit_code") if execution else None,
          timed_out=execution.get("timed_out") if execution else None,
          log_failures=execution.get("log_failures") if execution else None)
    actual_hash = sha256(ROOT / directory / "tb.cir") if deck is not None else None
    check(report, case, "deck_identity", "missing" if actual_hash is None or execution is None else "pass" if actual_hash == execution.get("deck_sha256") else "fail",
          actual_deck_sha256=actual_hash, execution_deck_sha256=execution.get("deck_sha256") if execution else None)
    obs["deck"] = deck_observations(deck) if deck is not None else None
    if deck is not None:
        check(report, case, "prebiased_state", "pass" if obs["deck"]["has_uic"] and obs["deck"]["ic_count"] else "fail",
              has_uic=obs["deck"]["has_uic"], ic_count=obs["deck"]["ic_count"],
              criterion="Deck explicitly supplies .ic voltages and uses uic.")
    else:
        check(report, case, "prebiased_state", "missing", reason="tb.cir missing")
    point = boundary.get("points", {}).get(f"ff_v1950_t-40:{case}") if boundary else None
    obs["registered_boundary_point"] = point
    check(report, case, "registered_deck_identity", "missing" if point is None or actual_hash is None else "pass" if point.get("run") == directory and point.get("deck_sha256") == actual_hash else "fail",
          boundary_id=BOUNDARY_ID, registered_deck_sha256=point.get("deck_sha256") if point else None,
          actual_deck_sha256=actual_hash)
    log = texts.get("simulator.log")
    obs["simulator_log"] = None if log is None else {
        "tail_lines": log.splitlines()[-40:], "tail_line_count": 40,
        "total_line_count": len(log.splitlines()),
        "warning_count": len(re.findall(r"^Warning:", log, re.M)),
        "ignored_parameters": sorted(set(re.findall(r"unrecognized parameter \(([^)]+)\) - ignored", log))),
        "completion_lines": line_records(log, r"No\. of Data Rows|ngspice-47 done|Operating point simulation skipped|TEMP =|Using SPARSE"),
    }
    check(report, case, "simulator_log_present", "pass" if log is not None else "missing",
          detail="Original final 40 lines and model warnings are retained, without assigning a new warning acceptance gate.")
    try:
        waves = spice.Waves(ROOT / directory / "waveforms.raw")
        finite = bool(np.all(np.isfinite(waves.data)))
        increasing = bool(np.all(np.diff(waves.t) > 0))
        reached = bool(np.isclose(waves.t[-1], STOP_S, rtol=STOP_RTOL, atol=0))
        covers = bool(waves.t[0] <= START_S)
        obs["raw"] = {"shape": list(waves.data.shape), "names": waves.names,
                      "first_time_s": float(waves.t[0]), "last_time_s": float(waves.t[-1]),
                      "all_values_finite": finite, "time_strictly_increasing": increasing,
                      "reached_24ns": reached, "covers_measurement_start": covers}
        valid = finite and increasing and reached and covers
        check(report, case, "raw_integrity", "pass" if valid else "fail", **obs["raw"],
              required_stop_s=STOP_S, relative_stop_tolerance=STOP_RTOL)
        if valid:
            measure(report, case, obs, waves)
        else:
            reason = "Raw failed completeness/integrity; downstream measurements are missing."
            missing_measurements(report, case, obs, reason)
            problem(report, case, "raw_integrity", reason)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {exc}"
        obs["raw"] = None
        check(report, case, "raw_integrity", "missing" if isinstance(exc, FileNotFoundError) else "fail", reason=reason)
        missing_measurements(report, case, obs, reason)
        problem(report, case, "waveforms.raw", reason)


def comparison(report: dict) -> None:
    cases = report["observations"]["cases"]
    result = {}
    for name in ("vco", *DIVIDERS, *CMOS):
        ll, hh = (cases[c].get("signals", {}).get(name) for c in ("ll", "hh"))
        if not ll or not hh:
            result[name] = None
            continue
        a, b = ll["period_stats"], hh["period_stats"]
        result[name] = {"frequency_hz_hh_minus_ll": b["frequency_hz"] - a["frequency_hz"] if a and b else None,
                        "amplitude_pp_v_hh_minus_ll": hh["window_amplitude_pp_v"] - ll["window_amplitude_pp_v"],
                        "window_min_v_hh_minus_ll": hh["window_min_v"] - ll["window_min_v"],
                        "window_max_v_hh_minus_ll": hh["window_max_v"] - ll["window_max_v"]}
    report["observations"]["hh_minus_ll"] = result
    check(report, "both", "differences", "ungraded",
          detail="Differences are descriptive: passive corner, code, Vctrl and initial state differ; no isolated causal attribution or acceptance gate.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/work_packages/deliveries/WP-001",
                        help="Directory for evidence.json; no other output file is generated.")
    args = parser.parse_args()
    report = {"schema_version": 1, "package_id": "WP-001", "execution_status": "complete",
              "inputs": [], "observations": {"cases": {}}, "checks": [], "unresolved": []}
    report["observations"]["scope"] = {
        "root": str(ROOT), "condition": "ff_v1950_t-40", "supply_v": VDD_V,
        "temperature_c": -40, "window_s": [START_S, STOP_S], "window_endpoint_inclusion": "inclusive",
        "boundary_id": BOUNDARY_ID, "analysis": "Isolated four-branch r5 frontend, fixed code and Vctrl, real bias / native PDK resistors, prebiased .ic/uic working-state transient.",
        "not_qualified": ["physical power-up", "closed-loop PLL capture or lock", "noise/jitter acceptance", "mismatch", "current DUT revision", "TX/RX loaded fixture"],
        "edge_indexing": "All stored edge and anomaly indices are zero-based; VCO edge indices refer to each case's signals.vco.positive_edges_s.",
        "frequency_algorithm": "clock.period_stats(t, y, start=8e-9, stop=24e-9), default min_cycles=3; CMOS y=node-1.95/2 V.",
        "edge_algorithm": "clock.edges within 8-24 ns; retain divider edges strictly bracketed by in-window VCO rising edges; np.interp(edge, vco_edges, np.arange(len(vco_edges))); diff versus k +/- 0.25.",
        "amplitude_algorithm": "Window extrema/ptp use all stored samples with 8 ns <= t <= 24 ns; period_stats amplitude uses first-to-last complete rising-edge extent as defined in the shared function.",
    }
    files = CONTEXT_FILES + [f"{directory}/{name}" for directory in CASES.values()
                            for name in ("tb.cir", "execution.json", "simulator.log", "waveforms.raw")]
    for relative in files:
        path = ROOT / relative
        item = {"path": relative, "sha256": sha256(path) if path.is_file() else None}
        if item["sha256"] is None:
            item["reason"] = "Input file missing"
            problem(report, "inputs", relative, item["reason"])
        report["inputs"].append(item)
    try:
        entries = json.loads((ROOT / "config/boundary_conditions.json").read_text())
        boundary = next(entry for entry in entries if entry["id"] == BOUNDARY_ID)
        report["observations"]["registered_boundary"] = boundary
    except Exception as exc:
        boundary = None
        problem(report, "both", BOUNDARY_ID, f"{type(exc).__name__}: {exc}")
    for case, directory in CASES.items():
        audit_case(report, case, directory, boundary)
    comparison(report)
    for case in CASES:
        functional = [c for c in report["checks"] if c["id"].startswith(f"{case}.functional.")]
        edges = [c for c in report["checks"] if c["id"].startswith(f"{case}.edge.")]
        assert len(functional) == 11 and len(edges) == 3
    report["check_counts"] = dict(Counter(c["status"] for c in report["checks"]))
    exit_code = 1 if report["check_counts"].get("fail") or report["check_counts"].get("missing") or report["execution_status"] != "complete" else 0
    report["process_exit_code"] = exit_code
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / "evidence.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(output), "execution_status": report["execution_status"],
                      "check_counts": report["check_counts"], "exit_code": exit_code}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
