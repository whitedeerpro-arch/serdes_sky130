"""Per-sample trim codes from an untrimmed-code MC run (what rx_offset_cal would settle on).

    uv run python analog/rx/sampler/tb/offset_dac/calcodes.py MC_CAMPAIGN CODES_SUMMARY OUT.json

MC_CAMPAIGN: tb/offset_mc run of a trimmed block at --code 32 (per-sample offsets off32 in its
summary, relative to the zero-trim reference).  CODES_SUMMARY: `run.py codes` of the same block,
mismatch-free threshold per code thr(c) at the MC condition (piecewise linear between the measured
codes).  Code per sample and lane = the c that minimises |off32 + thr(c) - thr(32)| (nearest code:
the SAR + neighbour step of rx_offset_cal rounds when noise dithers the decisions; without noise it may
end one code off).  A sample whose offset is outside the range saturates at 0 or 63.
"""
import json
import sys
from pathlib import Path

import numpy as np

from serdes_flow.project import ROOT

LANES = ("d0", "d1", "e0", "e1")


def main():
    mc_camp, codes_summary, out = sys.argv[1:4]
    s = json.loads((ROOT / mc_camp / "summary.json").read_text())
    cs = json.loads((ROOT / codes_summary).read_text())
    cond = s["condition"]
    if s.get("code") != 32:
        raise SystemExit(f"{mc_camp}: needs a run at --code 32 (has {s.get('code')})")
    thr = cs["conditions"][cond]["threshold_mv"]
    allc = np.arange(64)
    codes, resid = {}, []
    for l in LANES:
        meas = sorted((int(k), v) for k, v in thr[l].items())
        curve = np.interp(allc, [k for k, _ in meas], [v for _, v in meas])
        shift = curve - curve[32]
        off = np.array([np.nan if x is None else x for x in s["offsets_mv"][l]])
        c = np.array([32 if not np.isfinite(o) else int(np.argmin(np.abs(o + shift))) for o in off])
        codes[l] = c.tolist()
        resid.append(off + shift[c])
    r = np.concatenate(resid)
    sat = sum(int(np.sum((np.array(codes[l]) == 0) | (np.array(codes[l]) == 63))) for l in LANES)
    print(f"{cond}: predicted residual |max| {np.nanmax(np.abs(r)):.2f} mV, sigma {np.nanstd(r):.2f} mV; "
          f"codes {min(min(v) for v in codes.values())}..{max(max(v) for v in codes.values())}, saturated lanes {sat}")
    Path(out).write_text(json.dumps(codes))
    print(out)


if __name__ == "__main__":
    main()
