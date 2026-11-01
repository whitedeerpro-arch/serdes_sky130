"""SKY130 device cards: gm/ID lookup tables from DC sweeps (sizing flow, device level).

    uv run python analog/common/devices/tb/gmid/card.py [--corners tt] [--temps -40,27,85] [--resume C] [--pack-only]

Devices nfet_01v8, nfet_01v8_lvt, pfet_01v8 at L = 0.15 / 0.25 / 0.5 / 1 / 2 um and pfet_01v8_lvt at
0.35 / 0.5 / 1 / 2 / 4 um (its model has no bin below 0.35 um),
finger width 5 um x 2 fingers, source at 0 (PMOS see negated voltages).  Per corner one deck:
for every temperature and |Vsb| in (0, 0.3, 0.6) V a nested DC sweep |Vgs| 0..1.8 V (10 mV) x
|Vds| 0.1..1.8 V (0.1 V).  Saved per point: id gm gds gmbs vth vdsat cgg cgs cgd (BSIM4 operating
point values, so gm and gds are not finite differences).

Output: card.npz (arrays [temp, vsb, vds, vgs] per device/L/quantity, absolute values) and
card.json (axes, geometry, provenance).  Lookup by gm/ID: serdes_flow.devices.DeviceCard.
"""
import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from serdes_flow import spice
from serdes_flow.corners import Condition
from serdes_flow.project import ROOT

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "tb_device_card_ngspice.cir.in"
RESULTS = ROOT / "results/analog/common/devices/gmid_card"
DEVICES = {"nfet": ("sky130_fd_pr__nfet_01v8", "n"), "nfet_lvt": ("sky130_fd_pr__nfet_01v8_lvt", "n"),
           "pfet": ("sky130_fd_pr__pfet_01v8", "p"), "pfet_lvt": ("sky130_fd_pr__pfet_01v8_lvt", "p")}
LS = {"nfet": (0.15, 0.25, 0.5, 1.0, 2.0), "nfet_lvt": (0.15, 0.25, 0.5, 1.0, 2.0),
      "pfet": (0.15, 0.25, 0.5, 1.0, 2.0), "pfet_lvt": (0.35, 0.5, 1.0, 2.0, 4.0)}
FINGER_W, NF = 5.0, 2
VG = (0.0, 1.8, 0.01)
VD = (0.1, 1.8, 0.1)
VSB = (0.0, 0.3, 0.6)
PARAMS = ("id", "gm", "gds", "gmbs", "vth", "vdsat", "cgg", "cgs", "cgd")


def inst(dev, li):
    return f"x{dev.replace('_', '')}{li}"


def vec(dev, li, q):
    return f"{dev.replace('_', '')}{li}_{q}"


def devices_text():
    w = FINGER_W * NF
    ad = (NF + 1) // 2 * FINGER_W * 0.29
    as_ = (NF + 2) // 2 * FINGER_W * 0.29
    pd = 2 * ((NF + 1) // 2) * (FINGER_W + 0.29)
    ps = 2 * ((NF + 2) // 2) * (FINGER_W + 0.29)
    out = []
    for dev, (model, pol) in DEVICES.items():
        d, g, b = ("d", "g", "bn") if pol == "n" else ("dp", "gp", "bp")
        for li, L in enumerate(LS[dev]):
            out.append(f"{inst(dev, li)} {d} {g} 0 {b} {model} w={w} l={L} nf={NF} "
                       f"ad={ad:.4f} as={as_:.4f} pd={pd:.4f} ps={ps:.4f}")
    return "\n".join(out)


def device_path(dev, li):
    return f"@m.{inst(dev, li)}.m{DEVICES[dev][0]}"


def deck(corner, temps):
    c = Condition(corner, 1.8, temps[0])
    saves = ".save " + " ".join(f"{device_path(d, li)}[{q}]" for d in DEVICES for li in range(len(LS[d])) for q in PARAMS)
    lets = [f"let {vec(d, li, q)}={device_path(d, li)}[{q}]" for d in DEVICES for li in range(len(LS[d])) for q in PARAMS]
    names = " ".join(vec(d, li, q) for d in DEVICES for li in range(len(LS[d])) for q in PARAMS)
    blocks = []
    for t in temps:
        for vsb in VSB:
            blocks.append("\n".join([f"* case t{t}_vsb{vsb}", f"option temp={t}", f"alter Vb dc={-vsb}",
                                     f"dc Vg {VG[0]} {VG[1]} {VG[2]} Vd {VD[0]} {VD[1]} {VD[2]}"] + lets
                                    + ["set filetype=binary", f"write {case_name(t, vsb)}.raw {names}", "destroy all"]))
    return spice.render(TEMPLATE, **spice.corner_values(c), FINGER_W=FINGER_W, NF=NF, DEVICES=devices_text(),
                        SAVES=saves, CASES="\n".join(blocks))


def case_name(t, vsb):
    return f"t{t}_vsb{round(vsb * 1000)}"


def axes():
    vg = np.round(np.arange(VG[0], VG[1] + VG[2] / 2, VG[2]), 6)
    vd = np.round(np.arange(VD[0], VD[1] + VD[2] / 2, VD[2]), 6)
    return vg, vd


def pack(run_dir, corner, temps):
    vg, vd = axes()
    arrays = {}
    for d in DEVICES:
        for li, L in enumerate(LS[d]):
            for q in PARAMS:
                arrays[f"{d}/L{L}/{q}"] = np.empty((len(temps), len(VSB), len(vd), len(vg)))
    for ti, t in enumerate(temps):
        for si, vsb in enumerate(VSB):
            names, data = spice.read_raw(run_dir / f"{case_name(t, vsb)}.raw")
            # binary write labels vectors by type: i(x) for currents, v(x) for voltages
            col = {re.sub(r"^[iv]\((.*)\)$", r"\1", n.lower()): i for i, n in enumerate(names)}
            if data.shape[0] != len(vg) * len(vd):
                raise ValueError(f"{case_name(t, vsb)}: {data.shape[0]} points, expected {len(vg) * len(vd)}")
            for d in DEVICES:
                for li, L in enumerate(LS[d]):
                    for q in PARAMS:
                        x = data[:, col[vec(d, li, q)]].reshape(len(vd), len(vg))
                        arrays[f"{d}/L{L}/{q}"][ti, si] = np.abs(x)
    np.savez_compressed(run_dir / "card.npz", **arrays)
    meta = dict(corner=corner, temps=list(temps), vsb=list(VSB), vds=vd.tolist(), vgs=vg.tolist(), L={d: list(v) for d, v in LS.items()},
                finger_w_um=FINGER_W, nf=NF, w_um=FINGER_W * NF, devices={d: m for d, (m, _) in DEVICES.items()},
                quantities=list(PARAMS), note="absolute values; PMOS biased with negated Vgs/Vds/Vbs, source at 0")
    (run_dir / "card.json").write_text(json.dumps(meta, indent=1))
    return run_dir / "card.npz"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corners", default="tt")
    ap.add_argument("--temps", default="-40,27,85")
    ap.add_argument("--resume")
    ap.add_argument("--pack-only", action="store_true")
    a = ap.parse_args()
    corners = a.corners.split(",")
    temps = [int(x) for x in a.temps.split(",")]
    camp = (ROOT / a.resume) if a.resume else RESULTS / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    camp.mkdir(parents=True, exist_ok=True)
    jobs = [(deck(cn, temps), camp / cn, dict(timeout_s=3600, meta=dict(corner=cn, temps=temps)))
            for cn in corners if not (camp / cn / "execution.json").exists()]
    if not a.pack_only:
        for ex in spice.run_many(jobs, workers=4, smoke=False):
            if not ex.ok:
                raise SystemExit(f"FAILED {ex.run_dir}: {ex.log_failures[:5]}")
    for cn in corners:
        print(pack(camp / cn, cn, temps).relative_to(ROOT))


if __name__ == "__main__":
    main()
