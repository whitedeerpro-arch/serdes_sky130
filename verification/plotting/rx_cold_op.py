"""Publish fixed cold-RX OP diagnostics, including incomplete readout attempts.

Pass the bias and layered summary files explicitly; never choose a latest run.
Execution and voltage observations remain ungraded for RX functionality.
"""
import argparse
import hashlib
import json
import importlib
import sys
from pathlib import Path

from serdes_flow.project import ROOT


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def op_table(path):
    lines = path.read_text().splitlines()
    if len(lines) != 2:
        raise ValueError(f"incomplete OP table: {path}")
    names, vals = lines[0].split(), [float(s) for s in lines[1].split()]
    if len(names) != len(vals):
        raise ValueError("OP columns differ")
    return dict(zip(names, vals))


def solver_route(log, observed):
    """Classify the last evidenced solver route without inferring timeout success."""
    text = log.lower()
    for marker, route in (("transient op finished successfully", "optran_endpoint"),
                          ("source stepping completed", "source_stepping"),
                          ("true gmin stepping completed", "true_gmin_stepping"),
                          ("dynamic gmin stepping completed", "dynamic_gmin_stepping")):
        if marker in text:
            return route
    if observed and "starting" not in text:
        return "direct"
    if not observed:
        for marker, route in (("transient op started", "optran_incomplete"),
                              ("starting source stepping", "source_stepping_incomplete"),
                              ("starting true gmin stepping", "true_gmin_incomplete"),
                              ("starting dynamic gmin stepping", "dynamic_gmin_incomplete")):
            if marker in text:
                return route
    return "unclassified"


def collect_lanes(paths):
    runner_dir = ROOT / "analog/rx/sampler/tb/cold_readout_layers"
    sys.path.insert(0, str(runner_dir))
    try:
        lane = importlib.import_module("lane_op")
    finally:
        sys.path.remove(str(runner_dir))
    rows, inputs = [], {}
    nodes = ['bias_vbg', 'vgi_bias', 'vbias', 'vctle', 'rkp', 'rkn', 'xro.ckq', 'xro.ckqb', 'xro.xwc.j0', 'xro.xwc.j1', 'w']
    for path in paths:
        summary = json.loads(path.read_text())
        row = summary['result']
        campaign = path.parents[2]
        plan = lane.verify(campaign)
        run = ROOT / row['run']
        deck = campaign / 'prepared' / (row['case'] + '.cir')
        execution, raw, log = (run / name for name in ('execution.json', 'op.tsv', 'simulator.log'))
        ex = json.loads(execution.read_text())
        if (sha(execution) != row['execution_sha256'] or sha(raw) != row['op_sha256']
                or sha(run / 'tb.cir') != sha(deck) or ex['deck_sha256'] != sha(deck)
                or ex['exit_code'] != 0 or ex['timed_out'] or ex['log_failures']
                or row['status'] != 'observed' or lane.base.read_op(raw, nodes) != row['stages']):
            raise ValueError(f'lane evidence mismatch: {run}')
        route = solver_route(log.read_text(errors='replace'), True)
        for file in (path, campaign / 'plan.json', deck, run / 'tb.cir', execution, raw, log):
            inputs[str(file.relative_to(ROOT))] = sha(file)
        rows.append(dict(summary=str(path.relative_to(ROOT)), scope=summary['scope'], result=row,
                         solver_route=route, elapsed_s=ex['elapsed_s'], verified_snapshots=plan['snapshots'],
                         verified_sources=plan['source_hashes'], verified_references=plan['reference_execution_hashes']))
    return rows, inputs


def collect_full(paths):
    """Recheck fixed full-RX summaries against runner, execution, logs and raw."""
    runner_dir = ROOT / "analog/rx/sampler/tb/cold_readout_layers"
    sys.path.insert(0, str(runner_dir))
    try:
        modules = {key: importlib.import_module(name) for key, name in
                   (("short", "full_short"), ("seeded", "full_seeded"), ("optran", "full_optran"), ("sparse", "full_sparse_op"), ("newton", "full_dc_newton"))}
    finally:
        sys.path.remove(str(runner_dir))
    output, inputs = [], {}
    for kind, path in paths:
        summary = json.loads(path.read_text())
        row = summary["result"]
        campaign = path.parents[2]
        plan = modules[kind].verify(campaign)
        run = ROOT / row["run"]
        case = row.get("case")
        filename = {'sparse': 'full_sparse_op.cir', 'newton': 'full_dc_newton.cir'}.get(kind, f'full_{kind}.cir')
        deck = campaign / "prepared" / (f"{case}.cir" if kind == "optran" else filename)
        execution = run / "execution.json"
        ex = json.loads(execution.read_text())
        if sha(execution) != row["execution_sha256"] or sha(run / "tb.cir") != sha(deck) or ex["deck_sha256"] != sha(deck):
            raise ValueError(f"execution/deck identity mismatch: {run}")
        if kind == 'newton':
            stages = modules[kind].assess(run, json.loads((campaign / 'seed_nodes.json').read_text()))
        else:
            stages = modules[kind].assess(run) if kind in ("optran", "sparse") else modules["short"].assess(run)
        if stages != row["stages"]:
            raise ValueError(f"summary differs from logs/raw: {run}")
        observed = row['status'] in ('observed', 'observed_direct_newton')
        if observed:
            if ex["exit_code"] != 0 or ex["timed_out"] or ex["log_failures"] or not stages["raw_complete"]:
                raise ValueError(f"observed run failed: {run}")
            if kind == 'newton' and (not stages['direct_configured'] or not stages['optran_deselected'] or stages['any_fallback']):
                raise ValueError('direct Newton evidence used a fallback or missing configuration')
        elif not ex["timed_out"]:
            raise ValueError(f"expected timed-out run: {run}")
        for file in (path, campaign / "plan.json", deck, run / "tb.cir", execution, run / "simulator.log"):
            inputs[str(file.relative_to(ROOT))] = sha(file)
        raw = run / ("op.raw" if kind in ('sparse', 'newton') else "short.raw")
        if raw.exists():
            if sha(raw) != row.get("raw_sha256"):
                raise ValueError(f"raw identity mismatch: {run}")
            inputs[str(raw.relative_to(ROOT))] = sha(raw)
        elif row.get("raw_sha256"):
            raise ValueError(f"raw missing: {run}")
        output.append(dict(kind=kind, summary=str(path.relative_to(ROOT)), scope=summary["scope"],
                           result=row, elapsed_s=ex["elapsed_s"], timed_out=ex["timed_out"],
                           verified_snapshots=plan["snapshots"], verified_sources=plan.get("sources", plan.get("source_hashes", {})),
                           solver_route=solver_route((run / "simulator.log").read_text(errors="replace"), observed)))
    return output, inputs


def collect(bias_summary, layer_summary, parts_summary=None, full_summaries=(), lane_summaries=()):
    inputs, out = {}, {}
    sources = [("bias", bias_summary), ("layers", layer_summary)]
    if parts_summary is not None:
        sources.append(("readout_parts", parts_summary))
    for kind, path in sources:
        summary = json.loads(path.read_text())
        inputs[str(path.relative_to(ROOT))] = sha(path)
        campaign = path.parents[2]
        plan = json.loads((campaign / "plan.json").read_text())
        inputs[str((campaign / "plan.json").relative_to(ROOT))] = sha(campaign / "plan.json")
        rows = []
        for row in summary["rows"]:
            name = row.get("name", row.get("case"))
            case = next(c for c in plan["cases"] if c["name"] == name)
            # This campaign's first attempts are fixed here.  An incomplete
            # attempt is retained rather than silently searched past or omitted.
            run = ROOT / row["run"] if "run" in row else campaign / name
            ex_path = run / "execution.json"
            ex = json.loads(ex_path.read_text())
            digest = sha(run / "tb.cir")
            if digest != sha(campaign / case["deck"]) or ex["deck_sha256"] != digest:
                raise ValueError(f"deck identity differs: {run}")
            inputs[str(ex_path.relative_to(ROOT))] = sha(ex_path)
            if row["status"] == "observed":
                if ex["exit_code"] != 0 or ex["log_failures"] or ex["timed_out"]:
                    raise ValueError("successful OP row has failed execution")
                actual = op_table(run / "op.tsv")
                if kind == "bias":
                    if actual != row["values"]:
                        raise ValueError("bias summary differs from raw OP")
                else:
                    observed = {n: actual[f"v{i}"] for i, n in enumerate(case["nodes"])}
                    if observed != row["values"]["voltages"] or any(actual[k] != v for k, v in row["values"]["currents"].items()):
                        raise ValueError("layer summary differs from raw OP")
                inputs[str((run / "op.tsv").relative_to(ROOT))] = sha(run / "op.tsv")
            elif ex["exit_code"] == 0 and not ex["log_failures"] and not ex["timed_out"] and (run / "op.tsv").exists():
                raise ValueError("incomplete row unexpectedly has successful OP output")
            log = run / "simulator.log"
            inputs[str(log.relative_to(ROOT))] = sha(log)
            route = solver_route(log.read_text(errors="replace"), row["status"] == "observed")
            rows.append({**row, "run": str(run.relative_to(ROOT)), "elapsed_s": ex["elapsed_s"], "timed_out": ex["timed_out"], "solver_route": route})
        out[kind] = dict(scope=summary["scope"], campaign=str(campaign.relative_to(ROOT)), rows=rows)
    if full_summaries:
        out["full_diagnostics"], extra = collect_full(full_summaries)
        inputs.update(extra)
    if lane_summaries:
        out["lane_diagnostics"], extra = collect_lanes(lane_summaries)
        inputs.update(extra)
    return dict(spec_status="ungraded", inputs_sha256=inputs, **out,
                limitations=["Static reduced-load OP diagnostics, not startup or RX functional tests",
                             "Bias-only removes CTLE/PI/sampler/readout; layered experiments progressively restore load",
                             "The FF bias experiment uses the FS cell snapshot at a new FF condition; no FF W40 full-chain result"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bias-summary", type=Path, required=True)
    ap.add_argument("--layer-summary", type=Path, required=True)
    ap.add_argument("--parts-summary", type=Path)
    ap.add_argument("--full-short-summary", type=Path)
    ap.add_argument("--full-seeded-summary", type=Path)
    ap.add_argument("--full-optran-summary", type=Path, action="append", default=[])
    ap.add_argument("--full-sparse-summary", type=Path)
    ap.add_argument("--full-newton-summary", type=Path)
    ap.add_argument("--lane-summary", type=Path, action="append", default=[])
    args = ap.parse_args()
    full = [(kind, path.resolve()) for kind, path in [("short", args.full_short_summary),
            ("seeded", args.full_seeded_summary), ("sparse", args.full_sparse_summary), ('newton', args.full_newton_summary), *(("optran", p) for p in args.full_optran_summary)] if path]
    data = collect(args.bias_summary.resolve(), args.layer_summary.resolve(),
                   args.parts_summary.resolve() if args.parts_summary else None, full, [p.resolve() for p in args.lane_summary])
    text = json.dumps(data, indent=2, allow_nan=False) + "\n"
    for path in (ROOT / "docs/data/rx_cold_op.json", ROOT / "results/catalog/rx_cold_op.json"):
        path.write_text(text)
    print({key: {"observed": sum(r["status"] == "observed" for r in value["rows"]),
                 "attempts": len(value["rows"])} for key, value in data.items() if key in {"bias", "layers", "readout_parts"}})


if __name__ == "__main__":
    main()
