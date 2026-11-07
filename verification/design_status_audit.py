"""Read selected evidence for the block/status map; no simulation or historical writes.

uv run python verification/design_status_audit.py

This checks summary coverage and records identities, not waveform completeness,
model fidelity, or transfer of qualification to a changed circuit revision.
"""
import hashlib
import json
import time
from pathlib import Path

from serdes_flow.corners import grid45
from serdes_flow.project import ROOT


def main():
    sources = []

    def read(path):
        p = ROOT / path
        sources.append(dict(path=path, sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
        return json.loads(p.read_text())

    base = "results/analog/rx/sampler/link_pvt/"
    window_sources = {
        "tt": [base + "rx_c2_far_nominal_ac_trim32_realbias_rtt_20261104T154752Z/summary.json"],
        "hh": [base + "rx_c2_far_nominal_ac_trim32_realbias_rhh_20261104T084749Z/summary.json",
               base + "rx_c2_far_nominal_ac_trim32_realbias_rhh_20261104T122937Z/summary.json"],
        "ll": [base + "rx_c2_far_nominal_ac_trim32_realbias_rll_20261104T124429Z/summary.json"],
    }
    expected = {c.tag for c in grid45()}
    windows = {}
    for rc, paths in window_sources.items():
        rows = {}
        for path in paths:
            summary = read(path)
            for r in summary["rows"]:
                rows[r["condition"]] = dict(source=path, **{k: v for k, v in r.items() if k != "per_code"})
        assert set(rows) == expected, (rc, expected - rows.keys())
        full = [r for r in rows.values() if r["mode"] == "full"]
        gate = [r for r in rows.values() if r["mode"] == "gate"]
        assert len(full) == 6 and len(gate) == 39
        assert all(r["width_ui"] >= 0.5 for r in full)
        assert all(r["gate_pass"] and r["gate_span_ui"] >= 0.5 for r in gate)
        windows[rc] = dict(conditions=len(rows), full=len(full), gate=len(gate),
                           full_scan_min_ui=min(r["width_ui"] for r in full), rows=rows)

    readout_path = "results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32/summary.json"
    ro = read(readout_path)
    assert {r["condition"] for r in ro["rows"]} == expected
    assert all(r["map_ok"] and not r["data_errors"] and not r["edge_errors"] for r in ro["rows"])
    readout = dict(conditions=len(ro["rows"]), data_bits=sum(16 * r["words"] for r in ro["rows"]),
                   determinate_edges=sum(r["edge_determinate"] for r in ro["rows"]),
                   scope="Historical ideal-reference boundary, fixed PI20/trim32; old reports say W80/ideal R but included project circuits lack immutable snapshots; not current W40/real-bias RC qualification")

    pi = {}
    for rc, date in (("hh", "20261104T061420Z"), ("ll", "20261104T062821Z")):
        rows = read(f"results/analog/rx/pi/rotation_pvt/{date}/summary.json")
        assert len(rows) == 6 and all(len(r["codes"]) == 64 for r in rows)
        pi[rc] = dict(conditions=[r["condition"] for r in rows], codes_per_condition=64,
                       scope="Static pressure points, ideal anchors, real bias/PDK R; not transistor mismatch MC")

    ctle = read("results/analog/rx/ctle/offset_mc/20261102T204241Z/summary.json")
    ctle_mc = {k: ctle[k] for k in ("condition", "eq", "pdk_resistors", "samples", "input_offset_mv")}
    assert ctle_mc["input_offset_mv"]["n"] == 200
    cal_mc = []
    for date in ("20261103T082620Z", "20261103T083830Z", "20261103T085053Z"):
        d = read(f"results/analog/rx/sampler/offset_mc/{date}_pdkr_ac_trim_cal/summary.json")
        cal_mc.append({k: d[k] for k in ("condition", "dut", "pdk_resistors", "samples", "seed", "chunk", "hold", "lanes")})
        assert d["samples"] == d["lanes"]["d0"]["n"] == 96

    bias_dc = read("results/analog/common/bias/dist_pvt/20261103T212249Z/summary.json")
    assert len(bias_dc) == 135
    bias_mc = read("results/analog/common/bias/dist_mc/20261103T212743Z/summary.json")
    assert bias_mc["samples"] == 200

    def merged_bias(paths, include_code=False):
        rows = {}
        for path in paths:
            for r in read(path):
                key = f"{r['process']}:{r['supply']}:{r['temp']}:{r['rcorner']}"
                if include_code:
                    key += f":{r['code']}"
                rows[key] = dict(source=path, **r)
        return rows

    startup = merged_bias([
        "results/analog/common/bias/bandgap_startup/20261104T063625Z_ramp1u_dist/summary.json",
        "results/analog/common/bias/bandgap_startup/20261104T064156Z_ramp1u_dist/summary.json",
    ])
    assert len(startup) == 135 and all(r["ok"] for r in startup.values())
    pbuf = merged_bias([
        "results/analog/common/bias/pbuf_pvt/20261104T061421Z/summary.json",
        "results/analog/common/bias/pbuf_pvt/20261104T072912Z/summary.json",
    ], include_code=True)
    assert len(pbuf) == 405
    clocking = read("docs/data/clocking_progress_20261106.json")
    assert len(clocking["vco"]["rows"]) == len(clocking["cp"]["rows"]) == 135
    native = {k: r["state"] for k, r in clocking["native"].items()}

    result = dict(
        checked_local_date="2026-11-06", report="docs/overview/development_map.md", sources=sources,
        scope="Selected summary identity/cardinality checks; no raw-wave remeasurement or electrical signoff; historical variants kept distinct",
        rx_window=windows, old_readout=readout, pi_static=pi, ctle_mc=ctle_mc,
        sampler_calibrated_mc=dict(scope="Single-lane d0, other lanes held; ideal rising-ramp code selection; not actual two-edge SAR or chip yield", rows=cal_mc),
        bias=dict(dc_conditions=len(bias_dc), distribution_mc_samples=bias_mc["samples"], mc_temperatures=bias_mc["temps"],
                  startup_conditions=len(startup), startup_all_ok=True,
                  startup_max_us=max(r["t_settle_us"] for r in startup.values()),
                  pbuf_conditions=len(pbuf), pbuf_final_error_over10mv=sum(abs(r["error_mv"]) > 10 for r in pbuf.values()),
                  pbuf_final_max_abs_error_mv=max(abs(r["error_mv"]) for r in pbuf.values()),
                  pbuf_max_t10_ns=max(r["t10_ns"] for r in pbuf.values())),
        native_static_states=native,
    )
    run = ROOT / "results/verification/design_status_audit" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run.mkdir(parents=True, exist_ok=False)
    payload = json.dumps(result, indent=2, allow_nan=False) + "\n"
    (run / "evidence.json").write_text(payload)
    snapshot = ROOT / "docs/data/design_status_evidence.json"
    snapshot.write_text(payload)
    (ROOT / "results/catalog/design_status_audit.json").write_text(json.dumps(dict(
        report=result["report"], run=str(run.relative_to(ROOT)), snapshot=str(snapshot.relative_to(ROOT)),
        snapshot_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(), sources=sources), indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("old_readout", "bias", "native_static_states")}, indent=2))
    print("RX windows: 135 conditions = 18 full sweeps + 117 gate checks; identities saved to", snapshot.relative_to(ROOT))


if __name__ == "__main__":
    main()
