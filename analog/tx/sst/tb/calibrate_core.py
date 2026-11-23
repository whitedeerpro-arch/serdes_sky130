"""Quick DC/impedance/LDO calibration for the N-over-N SST unit slice & LDO.

Runs a fast single-deck-per-corner check (max 2 workers) to calibrate:
1. Unit slice R_pu vs R_pd symmetry and nominal 800 ohm target at TT/27C.
2. ZQ code selection across worst PVT+RC corners (SS/hh/1.65V/85C, FF/ll/1.95V/-40C, etc.).
3. On-chip V_drv LDO DC regulation, quiescent current, and load regulation (0..6 mA).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from serdes_flow import project, spice

ROOT = project.ROOT
RESULTS = ROOT / "results/analog/tx/sst"

CORNERS = [
    ("tt", 1.80, 27),
    ("ss_hh", 1.65, 85),
    ("ss_hh", 1.65, -40),
    ("fs_hh", 1.65, 85),
    ("sf_ll", 1.65, -40),
    ("ff_ll", 1.95, -40),
]


def build_cal_deck(corner: str, supply: float, temp_c: int, wpu: float = 4.2, wpd: float = 2.4, lres: float = 3.75) -> str:
    return f"""* SST Unit Slice Rout + Vdrv LDO Calibration ({corner}, {supply}V, {temp_c}C)
.lib "{project.model_library()}" {corner}
.include "{ROOT}/analog/common/devices/spice/sky130_primitives.spice"
.include "{ROOT}/analog/tx/sst/spice/tx_sst_driver.spice"

.param vdd_v={supply}
Vdd vdd 0 {{vdd_v}}
Vbg vbg 0 1.20

* 1. LDO under 3 mA nominal load (test DC voltage and load reg at 0.5mA, 3mA, 6mA)
Xldo vbg vdrv vdd 0 sst_vdrv_ldo
Iload vdrv 0 3.0m

* 2. Unit slice Pull-Up & Pull-Down impedance measurement at V_drv = 0.44 V
* Pad operating voltages during transmission into 50 ohm load:
*   Pull-up: pad_p = 0.33 V (vdrv = 0.44 V -> deltaV = 0.11 V across slice)
*   Pull-down: pad_n = 0.11 V (vss = 0.00 V -> deltaV = 0.11 V across slice)
Vdrv_ref vdrv_ref 0 0.44
Vdinp dinp 0 {{vdd_v}}
Vdinn dinn 0 0
Ven   en   0 {{vdd_v}}
Vpadp padp 0 0.33
Vpadn padn 0 0.11
Xslice dinp dinn en padp padn vdrv_ref vdd 0 sst_slice_unit wpu={wpu} wpd={wpd} lres={lres}

.temp {temp_c}
.options reltol=1e-4 abstol=1p vntol=1u klu
.control
set num_threads=1
op
let vdrv_3m = v(vdrv)
let vref_dc = v(xldo.vref)
let vgate_3m = v(xldo.vgate)
let iq_ua = (-i(Vdd) - 3.0m) * 1e6
let r_pu = (0.44 - 0.33) / i(Vpadp)
let r_pd = (0.11 - 0.00) / (-i(Vpadn))
echo CAL_OP1 corner={corner} vdd={supply} temp={temp_c} vdrv_3m=$&vdrv_3m vref=$&vref_dc vgate=$&vgate_3m iq_uA=$&iq_ua r_pu=$&r_pu r_pd=$&r_pd
alter Iload dc=0.5m
op
let vdrv_0p5m = v(vdrv)
echo CAL_OP2 vdrv_0p5m=$&vdrv_0p5m
alter Iload dc=6.0m
op
let vdrv_6m = v(vdrv)
echo CAL_OP3 vdrv_6m=$&vdrv_6m
quit
.endc
.end
"""


def parse_cal_log(log_path: Path) -> dict:
    out = {}
    for line in log_path.read_text(errors="replace").splitlines():
        if line.startswith(("CAL_OP1 ", "CAL_OP2 ", "CAL_OP3 ")):
            for tok in line.split()[1:]:
                k, v = tok.split("=", 1)
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    if "vdrv_3m" not in out or "vdrv_0p5m" not in out or "vdrv_6m" not in out:
        raise RuntimeError(f"CAL_OP lines missing in {log_path}")
    out["loadreg_mv"] = (out["vdrv_0p5m"] - out["vdrv_6m"]) * 1e3
    return out


def main():
    run_id = time.strftime("%Y%m%dT%H%M%SZ_cal", time.gmtime())
    camp = RESULTS / run_id
    camp.mkdir(parents=True, exist_ok=True)
    jobs = []
    for corner, vdd, temp_c in CORNERS:
        tag = f"{corner}_v{round(vdd*1000)}_t{temp_c}"
        deck = build_cal_deck(corner, vdd, temp_c)
        jobs.append((deck, camp / tag, {"timeout_s": 120}))
    execs = spice.run_many(jobs, workers=2, smoke=False)
    rows = []
    print(f"{'Corner':<18} {'Vdrv(V)':>8} {'Vref(V)':>8} {'LoadReg(mV)':>11} {'R_pu(ohm)':>10} {'R_pd(ohm)':>10} {'R_avg':>8} {'N_zq':>5} {'Rout_50':>8}")
    for ex in execs:
        if not ex.ok:
            print(f"FAILED {ex.run_dir}: {ex.log_failures}")
            continue
        r = parse_cal_log(ex.run_dir / "simulator.log")
        r_avg = 0.5 * (r["r_pu"] + r["r_pd"])
        n_zq = int(round(r_avg / 50.0))
        rout = r_avg / n_zq
        r["r_avg"] = r_avg
        r["n_zq"] = n_zq
        r["rout_cal"] = rout
        rows.append(r)
        print(f"{r['corner']}_v{int(r['vdd']*1000)}_t{int(r['temp']):<4} "
              f"{r['vdrv_3m']:8.4f} {r['vref']:8.4f} {r['loadreg_mv']:11.2f} "
              f"{r['r_pu']:10.1f} {r['r_pd']:10.1f} {r_avg:8.1f} {n_zq:5d} {rout:8.2f}")
    (camp / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"Saved: {camp / 'summary.json'}")


if __name__ == "__main__":
    main()
