"""Publish fixed cold-RX OP diagnostics, including incomplete readout attempts.

Pass the bias and layered summary files explicitly; never choose a latest run.
Execution and voltage observations remain ungraded for RX functionality.
"""
import argparse
import hashlib
import json
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


def collect(bias_summary, layer_summary, parts_summary=None):
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
            rows.append({**row, "run": str(run.relative_to(ROOT)), "elapsed_s": ex["elapsed_s"], "timed_out": ex["timed_out"]})
        out[kind] = dict(scope=summary["scope"], campaign=str(campaign.relative_to(ROOT)), rows=rows)
    return dict(spec_status="ungraded", inputs_sha256=inputs, **out,
                limitations=["Static reduced-load OP diagnostics, not startup or RX functional tests",
                             "Bias-only removes CTLE/PI/sampler/readout; layered experiments progressively restore load",
                             "The FF bias experiment uses the FS cell snapshot at a new FF condition; no FF W40 full-chain result"])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bias-summary", type=Path, required=True)
    ap.add_argument("--layer-summary", type=Path, required=True)
    ap.add_argument("--parts-summary", type=Path)
    args = ap.parse_args()
    data = collect(args.bias_summary.resolve(), args.layer_summary.resolve(),
                   args.parts_summary.resolve() if args.parts_summary else None)
    text = json.dumps(data, indent=2, allow_nan=False) + "\n"
    for path in (ROOT / "docs/data/rx_cold_op.json", ROOT / "results/catalog/rx_cold_op.json"):
        path.write_text(text)
    print({key: {"observed": sum(r["status"] == "observed" for r in value["rows"]),
                 "attempts": len(value["rows"])} for key, value in data.items() if key in {"bias", "layers", "readout_parts"}})


if __name__ == "__main__":
    main()
