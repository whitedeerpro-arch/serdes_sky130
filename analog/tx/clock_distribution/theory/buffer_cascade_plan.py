"""Plan the loaded buffer cascade from the two published Xe2 cards; no SPICE.

The unchanged Xe3 gives five observations of its 2 GHz amplitude transfer.
Scaling that fitted transfer by the measured joint-A reduction is a hypothesis
for the next cascade experiment, not an independently validated device model.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from serdes_flow import project

ROOT = project.ROOT
SINGLE = ROOT / "docs/data/tx_buffer_local.json"
JOINT = ROOT / "docs/data/tx_buffer_joint.json"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transfer(v, limit, gain):
    return limit * np.tanh(gain * np.asarray(v) / limit)


def plan():
    single, joint = (json.loads(p.read_text()) for p in (SINGLE, JOINT))
    if joint["calibration_sha256"] != digest(SINGLE):
        raise ValueError("joint card uses a different single-axis calibration")
    left = {r["condition"]: r for r in single["results"]}
    right = {r["condition"]: r for r in joint["results"]}
    if set(left) != set(right) or len(left) != 2:
        raise ValueError("expected the two calibrated TT/FS points")
    rows = []
    for tag, s in left.items():
        j = right[tag]
        if not s["result"]["baseline_matches"] or not j["result"]["baseline_matches"]:
            raise ValueError("uncalibrated baseline")
        observations = s["result"]["branches"] + j["result"]["branches"][1:]
        x = np.array([r["nodes"]["xe2_output"]["differential_pp_v"] for r in observations])
        y = np.array([r["nodes"]["xe3_output"]["differential_pp_v"] for r in observations])
        fit = least_squares(lambda q: transfer(x, *q) - y, [.6, 2.0],
                            bounds=([.1, .1], [1.5, 10]))
        if not fit.success:
            raise ValueError(f"fit failed: {tag}")
        base, measured = j["result"]["branches"][:2]
        v_first = measured["nodes"]["xe2_output"]["differential_pp_v"]
        alpha = v_first / base["nodes"]["xe2_output"]["differential_pp_v"]
        # The five-stage input is a stated proxy until the new card saves iso.
        v = base["nodes"]["xe2_input"]["differential_pp_v"]
        proxy = []
        for _ in range(5):
            v = float(alpha * transfer(v, *fit.x))
            proxy.append(v)
        rows.append(dict(condition=tag,
            observations=[dict(source_branch=r["branch"], input_pp_v=float(a), output_pp_v=float(b))
                          for r, a, b in zip(observations, x, y)],
            old_stage_limit_v=float(fit.x[0]), old_stage_low_amplitude_gain=float(fit.x[1]),
            in_sample_max_residual_v=float(np.max(np.abs(transfer(x, *fit.x) - y))),
            joint_a_scale=alpha, assumed_modified_low_amplitude_gain=float(alpha * fit.x[1]),
            two_stages_predicted_xe3_pp_v=float(alpha * transfer(v_first, *fit.x)),
            five_stages_proxy_input_pp_v=base["nodes"]["xe2_input"]["differential_pp_v"],
            five_stages_proxy_outputs_pp_v=proxy))
    return dict(status="prediction_only_not_graded", sources={str(p.relative_to(ROOT)): digest(p) for p in (SINGLE, JOINT)},
        generator_sha256=digest(Path(__file__)), rows=rows,
        assumptions=["2 GHz recorded TT/FS PWL boundaries only; dynamic waveform shape reduced to amplitude",
                     "tanh fit to unchanged Xe3 observations; fit residual is in-sample, not prediction error",
                     "modified-stage transfer assumed to scale by the single measured joint-A amplitude ratio",
                     "five-stage iso input approximated by baseline Xe2 input; final Xe4 has heavier WN32 load",
                     "no c2g, slew, delay, regeneration, PVT, mismatch or noise qualification",
                     "small-amplitude modified transfer and repeated-stage approximation need the new SPICE card"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = plan()
    args.output.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    for row in data["rows"]:
        print(row["condition"], "two-stage Xe3 mV", row["two_stages_predicted_xe3_pp_v"] * 1e3,
              "five-stage proxy mV", [round(v * 1e3, 2) for v in row["five_stages_proxy_outputs_pp_v"]])
