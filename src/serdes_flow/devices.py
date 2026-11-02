"""Device cards: gm/ID lookup over SKY130 DC-sweep tables (sizing flow, device level).

Tables come from analog/common/devices/tb/gmid/card.py (card.npz + card.json, one per corner).
Everything is per unit width at the card's finger width; widths scale linearly, so a device of
width W carries Id = (Id/W) * W, Cgg = (Cgg/W) * W, and the same gm/Id, gm/gds, ft, Vgs, Vdsat.
Values are magnitudes (PMOS biased with negated voltages, source at 0).

    card = DeviceCard.load("results/analog/common/devices/gmid_card/<run>/tt")
    op = card.at_gmid("pfet", L=0.5, gmid=15, vds=0.4, temp=27, vsb=0)
    op["id_w"] (A/um), op["gm_gds"], op["ft"] (Hz), op["cgg_w"] (F/um), op["vgs"], op["vdsat"]
    op = card.at_id_w("nfet_lvt", L=0.15, id_w=12.5e-6, vds=0.7, temp=85, vsb=0.8)   # by current density

Interpolation: at_gmid along gm/ID on the strong-inversion side of its peak (gm/ID decreasing with
Vgs), linear in Vds, Vsb a grid value; at_id_w along Id/W, bilinear in Vds and Vsb.  L and
temperature are grid values.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

QUANTITIES = ("id_w", "gm_gds", "ft", "cgg_w", "vgs", "vdsat", "gm_id", "gds_w", "gm_w", "cgs_w", "cgd_w", "vth")


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
                       gds_w=gds / w, gm_w=gm / w, cgs_w=g("cgs") / w, cgd_w=g("cgd") / w, vdsat=g("vdsat"), vth=g("vth"))
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

    def at_id_w(self, dev, L, id_w, vds, temp=27, vsb=0.0) -> dict:
        """Operating point at a current density Id/W (A/um), Vds and Vsb (magnitudes).

        Bilinear in Vds and Vsb between grid lines (Vgs found where Id/W matches on each line).
        """
        vs = np.array(self.meta["vsb"])
        if not vs[0] <= vsb <= vs[-1]:
            raise ValueError(f"vsb={vsb} outside card range {vs[0]}..{vs[-1]}")
        js = int(np.clip(np.searchsorted(vs, vsb) - 1, 0, len(vs) - 2))
        fs = (vsb - vs[js]) / (vs[js + 1] - vs[js])
        vd = self.vds
        if not vd[0] <= vds <= vd[-1]:
            raise ValueError(f"vds={vds} outside card range {vd[0]}..{vd[-1]}")
        j = int(np.clip(np.searchsorted(vd, vds) - 1, 0, len(vd) - 2))
        f = (vds - vd[j]) / (vd[j + 1] - vd[j])
        out = None
        for s, ws in ((js, 1 - fs), (js + 1, fs)):
            c = self.curves(dev, L, temp, float(vs[s]))
            for k, wk in ((j, 1 - f), (j + 1, f)):
                x = c["id_w"][k]
                if not x[0] < id_w < x[-1]:
                    raise ValueError(f"Id/W {id_w} outside {x[0]:.3g}..{x[-1]:.3g}")
                row = {q: float(np.interp(id_w, x, c[q][k])) for q in QUANTITIES}
                out = {q: (0.0 if out is None else out[q]) + ws * wk * row[q] for q in QUANTITIES}
        return out

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
