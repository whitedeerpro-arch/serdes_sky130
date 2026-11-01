"""Device cards: gm/ID lookup over SKY130 DC-sweep tables (sizing flow, device level).

Tables come from analog/common/devices/tb/gmid/card.py (card.npz + card.json, one per corner).
Everything is per unit width at the card's finger width; widths scale linearly, so a device of
width W carries Id = (Id/W) * W, Cgg = (Cgg/W) * W, and the same gm/Id, gm/gds, ft, Vgs, Vdsat.
Values are magnitudes (PMOS biased with negated voltages, source at 0).

    card = DeviceCard.load("results/analog/common/devices/gmid_card/<run>/tt")
    op = card.at_gmid("pfet", L=0.5, gmid=15, vds=0.4, temp=27, vsb=0)
    op["id_w"] (A/um), op["gm_gds"], op["ft"] (Hz), op["cgg_w"] (F/um), op["vgs"], op["vdsat"]

Interpolation: along gm/ID on the strong-inversion side of its peak (gm/ID decreasing with Vgs),
linear in Vds between grid lines; L, Vsb and temperature must be grid values.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

QUANTITIES = ("id_w", "gm_gds", "ft", "cgg_w", "vgs", "vdsat", "gm_id", "gds_w", "cgd_w", "vth")


@dataclass
class DeviceCard:
    path: Path
    meta: dict
    arrays: dict

    @classmethod
    def load(cls, path) -> "DeviceCard":
        path = Path(path)
        meta = json.loads((path / "card.json").read_text())
        with np.load(path / "card.npz") as z:
            arrays = {k: z[k] for k in z.files}
        return cls(path, meta, arrays)

    @property
    def vgs(self) -> np.ndarray:
        return np.array(self.meta["vgs"])

    @property
    def vds(self) -> np.ndarray:
        return np.array(self.meta["vds"])

    def _index(self, axis, value):
        vals = list(self.meta[axis])
        for i, v in enumerate(vals):
            if abs(v - value) < 1e-9:
                return i
        raise KeyError(f"{axis}={value} not on the card grid {vals}")

    def curves(self, dev, L, temp=27, vsb=0.0) -> dict:
        """Raw curves [vds, vgs] at one L / temperature / Vsb, plus derived per-width quantities."""
        ti, si = self._index("temps", temp), self._index("vsb", vsb)
        g = lambda q: self.arrays[f"{dev}/L{L}/{q}"][ti, si]
        w = self.meta["w_um"]
        idd, gm, gds = g("id"), g("gm"), g("gds")
        cgg = g("cgg")
        with np.errstate(divide="ignore", invalid="ignore"):
            out = dict(id_w=idd / w, gm_id=gm / idd, gm_gds=gm / gds, ft=gm / (2 * np.pi * cgg), cgg_w=cgg / w,
                       gds_w=gds / w, cgd_w=g("cgd") / w, vdsat=g("vdsat"), vth=g("vth"))
        out["vgs"] = np.broadcast_to(self.vgs, idd.shape)
        return out

    def at_gmid(self, dev, L, gmid, vds, temp=27, vsb=0.0, min_id_w=1e-9) -> dict:
        """Operating point at a target gm/ID and Vds (both magnitudes)."""
        c = self.curves(dev, L, temp, vsb)
        vd = self.vds
        if not vd[0] <= vds <= vd[-1]:
            raise ValueError(f"vds={vds} outside card range {vd[0]}..{vd[-1]}")
        j = int(np.clip(np.searchsorted(vd, vds) - 1, 0, len(vd) - 2))
        f = (vds - vd[j]) / (vd[j + 1] - vd[j])
        rows = [self._row_at_gmid(c, k, gmid, min_id_w) for k in (j, j + 1)]
        return {q: (1 - f) * rows[0][q] + f * rows[1][q] for q in rows[0]}

    @staticmethod
    def _row_at_gmid(c, k, gmid, min_id_w):
        gm_id = c["gm_id"][k]
        ok = np.isfinite(gm_id) & (c["id_w"][k] > min_id_w)
        idx = np.flatnonzero(ok)
        peak = idx[int(np.argmax(gm_id[idx]))]
        seg = idx[idx >= peak]                       # strong-inversion side: gm/ID decreasing
        x = gm_id[seg][::-1]
        if not x[0] <= gmid <= x[-1]:
            raise ValueError(f"gm/ID {gmid} outside {x[0]:.2f}..{x[-1]:.2f} at this bias")
        return {q: float(np.interp(gmid, x, c[q][k][seg][::-1])) for q in QUANTITIES}
