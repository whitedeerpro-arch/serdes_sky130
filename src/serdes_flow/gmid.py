"""SKY130A gm/ID lookup, monotone interpolation, direct sizing, and SPICE deck helper.

This module provides a self-contained physics-based sizing layer that complements
``serdes_flow.devices.DeviceCard``:

* ``GmIdTable`` stores normalized per-unit-width MOSFET curves keyed by
  ``(device_model, corner, temp_c, vds_v, l_um)`` and serializes cleanly to
  JSON, NPZ, or directory (``table.json`` + ``table.npz``).
* Monotone log-space PCHIP interpolation supports direct synthesis via
  ``size_for_gm`` and ``size_for_id`` across ``gm/ID``, channel length ``L``,
  ``Vds``, and temperature.
* ``snap_sky130_width`` converts continuous target widths into DRC-clean
  SKY130A finger geometries ``(w_total, nf, w_finger)``.
* ``build_spice_char_deck`` emits a single merged ngspice DC/OP characterization
  deck per corner without launching ngspice.
* ``synthetic_ekv_table`` generates smooth, EKV-calibrated SKY130A reference
  tables (``nfet_01v8``, ``nfet_01v8_lvt``, ``pfet_01v8``, ``pfet_01v8_lvt``)
  for fast unit tests and first-pass sizing before SPICE calibration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Mapping, NamedTuple, Sequence

import numpy as np
from scipy.interpolate import PchipInterpolator

from . import project
from .corners import PROCESS

CURVE_FIELDS: tuple[str, ...] = (
    "vgs_v",
    "gm_id",
    "id_w",
    "gm_gds",
    "ft_hz",
    "cgg_w",
    "cdd_w",
    "cgd_w",
    "vdsat_v",
    "vth_v",
)

# Positive physical quantities interpolated in log-space for accuracy over decades.
_LOG_INTERP_FIELDS: frozenset[str] = frozenset(
    {"id_w", "gm_gds", "ft_hz", "cgg_w", "cdd_w", "cgd_w"}
)

# Short-name aliases mapped to canonical SKY130A PDK subcircuit/model names.
SKY130_DEVICE_ALIASES: dict[str, str] = {
    "nfet": "sky130_fd_pr__nfet_01v8",
    "nfet_01v8": "sky130_fd_pr__nfet_01v8",
    "sky130_fd_pr__nfet_01v8": "sky130_fd_pr__nfet_01v8",
    "nfet_lvt": "sky130_fd_pr__nfet_01v8_lvt",
    "nfet_01v8_lvt": "sky130_fd_pr__nfet_01v8_lvt",
    "sky130_fd_pr__nfet_01v8_lvt": "sky130_fd_pr__nfet_01v8_lvt",
    "pfet": "sky130_fd_pr__pfet_01v8",
    "pfet_01v8": "sky130_fd_pr__pfet_01v8",
    "sky130_fd_pr__pfet_01v8": "sky130_fd_pr__pfet_01v8",
    "pfet_lvt": "sky130_fd_pr__pfet_01v8_lvt",
    "pfet_01v8_lvt": "sky130_fd_pr__pfet_01v8_lvt",
    "sky130_fd_pr__pfet_01v8_lvt": "sky130_fd_pr__pfet_01v8_lvt",
}

DEFAULT_L_LIST: dict[str, tuple[float, ...]] = {
    "sky130_fd_pr__nfet_01v8": (0.15, 0.25, 0.5, 1.0, 2.0),
    "sky130_fd_pr__nfet_01v8_lvt": (0.15, 0.25, 0.5, 1.0, 2.0),
    "sky130_fd_pr__pfet_01v8": (0.15, 0.25, 0.5, 1.0, 2.0),
    "sky130_fd_pr__pfet_01v8_lvt": (0.35, 0.5, 1.0, 2.0),
}

GmIdKey = tuple[str, str, float, float, float]


def canonical_device_model(name: str) -> str:
    """Resolve short aliases (e.g. ``nfet_01v8``) to canonical SKY130A names."""
    return SKY130_DEVICE_ALIASES.get(name.strip(), name.strip())


def _canonical_key(key: GmIdKey) -> GmIdKey:
    device_model, corner, temp_c, vds_v, l_um = key
    return (
        canonical_device_model(str(device_model)),
        str(corner).lower(),
        round(float(temp_c), 6),
        round(float(vds_v), 6),
        round(float(l_um), 6),
    )


class GmSizingResult(NamedTuple):
    """Direct sizing result for a target transconductance ``gm``."""

    w_um: float
    id_a: float
    cgg_f: float
    cdd_f: float
    ro_ohm: float
    vdsat_v: float
    vgs_v: float


class IdSizingResult(NamedTuple):
    """Direct sizing result for a target drain current ``Id``."""

    w_um: float
    gm_s: float
    cgg_f: float
    cdd_f: float
    ro_ohm: float
    ft_hz: float
    vdsat_v: float


class FingerGeometry(NamedTuple):
    """DRC-clean SKY130A fingered FET geometry."""

    w_total: float
    nf: int
    w_finger: float


@dataclass(frozen=True)
class GmIdCurve:
    """Normalized per-unit-width MOSFET curves swept over ``vgs_v`` (magnitudes)."""

    vgs_v: np.ndarray
    gm_id: np.ndarray
    id_w: np.ndarray
    gm_gds: np.ndarray
    ft_hz: np.ndarray
    cgg_w: np.ndarray
    cdd_w: np.ndarray
    cgd_w: np.ndarray
    vdsat_v: np.ndarray
    vth_v: np.ndarray

    def __post_init__(self) -> None:
        lengths = set()
        for fname in CURVE_FIELDS:
            arr = np.asarray(getattr(self, fname), dtype=float)
            if arr.ndim != 1 or arr.size < 2:
                raise ValueError(f"{fname} must be a 1D array with at least 2 points")
            if not np.isfinite(arr).all():
                raise ValueError(f"{fname} contains non-finite values")
            object.__setattr__(self, fname, arr)
            lengths.add(arr.size)
        if len(lengths) != 1:
            raise ValueError("All curve arrays must have identical length")
        if np.any(np.diff(self.vgs_v) <= 0.0):
            raise ValueError("vgs_v must be strictly increasing")

    def to_dict(self) -> dict[str, list[float]]:
        return {fname: getattr(self, fname).tolist() for fname in CURVE_FIELDS}

    @classmethod
    def from_dict(cls, data: Mapping[str, Sequence[float]]) -> "GmIdCurve":
        return cls(**{fname: np.asarray(data[fname], dtype=float) for fname in CURVE_FIELDS})

    def eval_at_gmid(self, gm_id_target: float, *, min_id_w: float = 1e-12) -> dict[str, float]:
        """Evaluate all curve quantities at a target ``gm/ID`` on the monotone strong-inversion side."""
        gm_id = self.gm_id
        ok = np.isfinite(gm_id) & (self.id_w > min_id_w) & (gm_id > 0.0)
        idx = np.flatnonzero(ok)
        if idx.size < 2:
            raise ValueError("Curve has fewer than 2 valid operating points")

        peak_pos = int(np.argmax(gm_id[idx]))
        seg = idx[peak_pos:]
        # Enforce strictly decreasing gm/ID along the strong-inversion branch.
        keep = [int(seg[0])]
        for i in seg[1:]:
            if gm_id[i] < gm_id[keep[-1]] - 1e-12:
                keep.append(int(i))
        if len(keep) < 2:
            raise ValueError("Curve does not have a monotone decreasing gm/ID branch")

        # Reverse so x = gm_id is strictly ascending for PchipInterpolator.
        order = np.array(keep[::-1], dtype=int)
        x = gm_id[order]
        lo, hi = float(x[0]), float(x[-1])
        if not (lo - 1e-9 <= gm_id_target <= hi + 1e-9):
            raise ValueError(
                f"gm_id_target={gm_id_target:.4g} outside valid curve range [{lo:.4g}, {hi:.4g}] S/A"
            )
        xq = float(np.clip(gm_id_target, lo, hi))

        out: dict[str, float] = {"gm_id": xq}
        for fname in CURVE_FIELDS:
            if fname == "gm_id":
                continue
            y = getattr(self, fname)[order]
            if fname in _LOG_INTERP_FIELDS and np.all(y > 0.0):
                interp = PchipInterpolator(x, np.log(y))
                out[fname] = float(np.exp(interp(xq)))
            else:
                interp = PchipInterpolator(x, y)
                out[fname] = float(interp(xq))
        return out


def _blend_rows(r0: Mapping[str, float], r1: Mapping[str, float], alpha: float) -> dict[str, float]:
    """Blend two operating-point dicts using log-space interpolation for positive quantities."""
    out: dict[str, float] = {}
    for k in r0:
        v0, v1 = float(r0[k]), float(r1[k])
        if k in _LOG_INTERP_FIELDS and v0 > 0.0 and v1 > 0.0:
            out[k] = float(math.exp((1.0 - alpha) * math.log(v0) + alpha * math.log(v1)))
        else:
            out[k] = float((1.0 - alpha) * v0 + alpha * v1)
    return out


def _bracket(grid: Sequence[float], value: float, axis_name: str, *, log_axis: bool = False) -> tuple[float, float, float]:
    """Return ``(g0, g1, alpha)`` bracketing ``value`` on a sorted grid."""
    vals = sorted(set(float(v) for v in grid))
    if not vals:
        raise KeyError(f"Empty grid for axis {axis_name}")
    for v in vals:
        if abs(v - value) <= 1e-9 * max(1.0, abs(v)):
            return v, v, 0.0
    if value < vals[0] - 1e-9 or value > vals[-1] + 1e-9:
        raise ValueError(f"{axis_name}={value} outside table grid [{vals[0]}, {vals[-1]}]")
    arr = np.asarray(vals, dtype=float)
    hi_idx = int(np.searchsorted(arr, value))
    hi_idx = min(max(hi_idx, 1), len(vals) - 1)
    g0, g1 = float(arr[hi_idx - 1]), float(arr[hi_idx])
    if log_axis and g0 > 0.0 and g1 > 0.0 and value > 0.0:
        alpha = (math.log(value) - math.log(g0)) / (math.log(g1) - math.log(g0))
    else:
        alpha = (value - g0) / (g1 - g0)
    return g0, g1, float(np.clip(alpha, 0.0, 1.0))


@dataclass
class GmIdTable:
    """Multi-device, multi-corner gm/ID table keyed by ``(device_model, corner, temp_c, vds_v, l_um)``."""

    curves: dict[GmIdKey, GmIdCurve] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized: dict[GmIdKey, GmIdCurve] = {}
        for k, curve in self.curves.items():
            normalized[_canonical_key(k)] = curve
        self.curves = normalized

    def add(
        self,
        device_model: str,
        corner: str,
        temp_c: float,
        vds_v: float,
        l_um: float,
        curve: GmIdCurve,
    ) -> None:
        self.curves[_canonical_key((device_model, corner, temp_c, vds_v, l_um))] = curve

    def keys(self) -> list[GmIdKey]:
        return sorted(self.curves.keys())

    def __len__(self) -> int:
        return len(self.curves)

    def __contains__(self, key: GmIdKey) -> bool:
        return _canonical_key(key) in self.curves

    def get(
        self,
        device_model: str,
        corner: str,
        temp_c: float,
        vds_v: float,
        l_um: float,
    ) -> GmIdCurve:
        k = _canonical_key((device_model, corner, temp_c, vds_v, l_um))
        if k not in self.curves:
            raise KeyError(f"Curve key {k} not found in GmIdTable")
        return self.curves[k]

    def _resolve_defaults(
        self,
        device_model: str | None,
        corner: str | None,
        temp_c: float | None,
        vds_v: float | None,
    ) -> tuple[str, str, float, float]:
        if not self.curves:
            raise ValueError("GmIdTable is empty")
        all_keys = list(self.curves.keys())

        if device_model is None:
            models = sorted({k[0] for k in all_keys})
            if len(models) == 1:
                dev = models[0]
            elif "sky130_fd_pr__nfet_01v8" in models:
                dev = "sky130_fd_pr__nfet_01v8"
            else:
                raise ValueError(f"Specify device_model explicitly; table has {models}")
        else:
            dev = canonical_device_model(device_model)

        dev_keys = [k for k in all_keys if k[0] == dev]
        if not dev_keys:
            raise KeyError(f"device_model={dev!r} not in table ({sorted({k[0] for k in all_keys})})")

        if corner is None:
            corners = sorted({k[1] for k in dev_keys})
            cn = corners[0] if len(corners) == 1 else ("tt" if "tt" in corners else corners[0])
        else:
            cn = corner.lower()
        cn_keys = [k for k in dev_keys if k[1] == cn]
        if not cn_keys:
            raise KeyError(f"corner={cn!r} not in table for {dev}")

        if temp_c is None:
            temps = sorted({k[2] for k in cn_keys})
            t = temps[0] if len(temps) == 1 else (27.0 if 27.0 in temps else temps[len(temps) // 2])
        else:
            t = float(temp_c)

        if vds_v is None:
            vds_vals = sorted({k[3] for k in cn_keys})
            vd = vds_vals[0] if len(vds_vals) == 1 else (0.9 if 0.9 in vds_vals else vds_vals[len(vds_vals) // 2])
        else:
            vd = float(vds_v)

        return dev, cn, t, vd

    def lookup(
        self,
        gm_id_target: float,
        l_um: float,
        *,
        device_model: str | None = None,
        corner: str | None = None,
        temp_c: float | None = None,
        vds_v: float | None = None,
        min_id_w: float = 1e-12,
    ) -> dict[str, float]:
        """Interpolate operating point at ``(gm_id_target, l_um)`` across ``(temp_c, vds_v, l_um)``."""
        dev, cn, t_val, vd_val = self._resolve_defaults(device_model, corner, temp_c, vds_v)
        sub = [k for k in self.curves if k[0] == dev and k[1] == cn]
        t0, t1, at = _bracket([k[2] for k in sub], t_val, "temp_c")

        def eval_at_temp(t_grid: float) -> dict[str, float]:
            t_keys = [k for k in sub if abs(k[2] - t_grid) <= 1e-9]
            v0, v1, av = _bracket([k[3] for k in t_keys], vd_val, "vds_v")

            def eval_at_vds(v_grid: float) -> dict[str, float]:
                v_keys = [k for k in t_keys if abs(k[3] - v_grid) <= 1e-9]
                l0, l1, al = _bracket([k[4] for k in v_keys], float(l_um), "l_um", log_axis=True)
                r0 = self.get(dev, cn, t_grid, v_grid, l0).eval_at_gmid(gm_id_target, min_id_w=min_id_w)
                if l0 == l1:
                    return r0
                r1 = self.get(dev, cn, t_grid, v_grid, l1).eval_at_gmid(gm_id_target, min_id_w=min_id_w)
                return _blend_rows(r0, r1, al)

            rv0 = eval_at_vds(v0)
            if v0 == v1:
                return rv0
            rv1 = eval_at_vds(v1)
            return _blend_rows(rv0, rv1, av)

        rt0 = eval_at_temp(t0)
        if t0 == t1:
            return rt0
        rt1 = eval_at_temp(t1)
        return _blend_rows(rt0, rt1, at)

    def size_for_gm(
        self,
        gm_target: float,
        gm_id_target: float,
        l_um: float,
        *,
        device_model: str | None = None,
        corner: str | None = None,
        temp_c: float | None = None,
        vds_v: float | None = None,
    ) -> GmSizingResult:
        """Direct synthesis for target ``gm`` (S) at chosen ``gm/ID`` (S/A) and ``L`` (um).

        Returns ``GmSizingResult(w_um, id_a, cgg_f, cdd_f, ro_ohm, vdsat_v, vgs_v)``.
        """
        if gm_target <= 0.0:
            raise ValueError(f"gm_target must be > 0, got {gm_target}")
        if gm_id_target <= 0.0:
            raise ValueError(f"gm_id_target must be > 0, got {gm_id_target}")
        op = self.lookup(
            gm_id_target,
            l_um,
            device_model=device_model,
            corner=corner,
            temp_c=temp_c,
            vds_v=vds_v,
        )
        id_a = float(gm_target / gm_id_target)
        w_um = float(id_a / op["id_w"])
        cgg_f = float(op["cgg_w"] * w_um)
        cdd_f = float(op["cdd_w"] * w_um)
        ro_ohm = float(op["gm_gds"] / gm_target)
        return GmSizingResult(
            w_um=w_um,
            id_a=id_a,
            cgg_f=cgg_f,
            cdd_f=cdd_f,
            ro_ohm=ro_ohm,
            vdsat_v=float(op["vdsat_v"]),
            vgs_v=float(op["vgs_v"]),
        )

    def size_for_id(
        self,
        id_target: float,
        gm_id_target: float,
        l_um: float,
        *,
        device_model: str | None = None,
        corner: str | None = None,
        temp_c: float | None = None,
        vds_v: float | None = None,
    ) -> IdSizingResult:
        """Direct synthesis for target ``Id`` (A) at chosen ``gm/ID`` (S/A) and ``L`` (um).

        Returns ``IdSizingResult(w_um, gm_s, cgg_f, cdd_f, ro_ohm, ft_hz, vdsat_v)``.
        """
        if id_target <= 0.0:
            raise ValueError(f"id_target must be > 0, got {id_target}")
        if gm_id_target <= 0.0:
            raise ValueError(f"gm_id_target must be > 0, got {gm_id_target}")
        op = self.lookup(
            gm_id_target,
            l_um,
            device_model=device_model,
            corner=corner,
            temp_c=temp_c,
            vds_v=vds_v,
        )
        gm_s = float(id_target * gm_id_target)
        w_um = float(id_target / op["id_w"])
        cgg_f = float(op["cgg_w"] * w_um)
        cdd_f = float(op["cdd_w"] * w_um)
        ro_ohm = float(op["gm_gds"] / gm_s)
        ft_hz = float(gm_s / (2.0 * math.pi * cgg_f))
        return IdSizingResult(
            w_um=w_um,
            gm_s=gm_s,
            cgg_f=cgg_f,
            cdd_f=cdd_f,
            ro_ohm=ro_ohm,
            ft_hz=ft_hz,
            vdsat_v=float(op["vdsat_v"]),
        )

    def save(self, path: str | Path) -> Path:
        """Save table to ``.json``, ``.npz``, or a directory (``table.json`` + ``table.npz``)."""
        p = Path(path)
        ordered_keys = self.keys()
        if p.suffix.lower() == ".json":
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "format": "serdes_flow.gmid.v1",
                "meta": self.meta,
                "entries": [
                    {"key": list(k), "curve": self.curves[k].to_dict()}
                    for k in ordered_keys
                ],
            }
            p.write_text(json.dumps(payload, indent=2) + "\n")
            return p

        if p.suffix.lower() == ".npz":
            p.parent.mkdir(parents=True, exist_ok=True)
            index = [{"id": i, "key": list(k)} for i, k in enumerate(ordered_keys)]
            arrays: dict[str, np.ndarray] = {
                "__meta_json__": np.array(
                    json.dumps({"format": "serdes_flow.gmid.v1", "meta": self.meta, "index": index})
                )
            }
            for i, k in enumerate(ordered_keys):
                c = self.curves[k]
                for fname in CURVE_FIELDS:
                    arrays[f"c{i}__{fname}"] = getattr(c, fname)
            np.savez_compressed(p, **arrays)
            return p

        # Directory bundle: table.json + table.npz
        p.mkdir(parents=True, exist_ok=True)
        index = [{"id": i, "key": list(k)} for i, k in enumerate(ordered_keys)]
        (p / "table.json").write_text(
            json.dumps({"format": "serdes_flow.gmid.v1", "meta": self.meta, "index": index}, indent=2) + "\n"
        )
        arrays = {}
        for i, k in enumerate(ordered_keys):
            c = self.curves[k]
            for fname in CURVE_FIELDS:
                arrays[f"c{i}__{fname}"] = getattr(c, fname)
        np.savez_compressed(p / "table.npz", **arrays)
        return p

    @classmethod
    def load(cls, path: str | Path) -> "GmIdTable":
        """Load table from ``.json``, ``.npz``, or directory bundle."""
        p = Path(path)
        if p.is_dir():
            header = json.loads((p / "table.json").read_text())
            curves: dict[GmIdKey, GmIdCurve] = {}
            with np.load(p / "table.npz") as z:
                for entry in header["index"]:
                    i = entry["id"]
                    k = _canonical_key(tuple(entry["key"]))
                    curves[k] = GmIdCurve(**{f: z[f"c{i}__{f}"] for f in CURVE_FIELDS})
            return cls(curves=curves, meta=dict(header.get("meta", {})))

        if p.suffix.lower() == ".json":
            payload = json.loads(p.read_text())
            curves = {
                _canonical_key(tuple(entry["key"])): GmIdCurve.from_dict(entry["curve"])
                for entry in payload["entries"]
            }
            return cls(curves=curves, meta=dict(payload.get("meta", {})))

        if p.suffix.lower() == ".npz":
            curves = {}
            with np.load(p, allow_pickle=False) as z:
                header = json.loads(str(z["__meta_json__"].item()))
                for entry in header["index"]:
                    i = entry["id"]
                    k = _canonical_key(tuple(entry["key"]))
                    curves[k] = GmIdCurve(**{f: z[f"c{i}__{f}"] for f in CURVE_FIELDS})
            return cls(curves=curves, meta=dict(header.get("meta", {})))

        raise ValueError(f"Unsupported GmIdTable path format: {p}")

    @classmethod
    def from_device_card(
        cls,
        card: Any,
        *,
        vsb: float = 0.0,
        cdd_overlap_ratio: float = 0.45,
    ) -> "GmIdTable":
        """Convert an existing ``serdes_flow.devices.DeviceCard`` into a ``GmIdTable``.

        Because ``DeviceCard`` does not store ``cdd`` separately, ``cdd_w`` is estimated as
        ``cgd_w + cdd_overlap_ratio * max(cgg_w - cgd_w, 0)``.
        """
        meta = card.meta
        corner = str(meta["corner"]).lower()
        vgs = np.asarray(meta["vgs"], dtype=float)
        vds_vals = np.asarray(meta["vds"], dtype=float)
        curves: dict[GmIdKey, GmIdCurve] = {}

        for dev_short, model_name in meta["devices"].items():
            for l_um in meta["L"][dev_short]:
                for temp_c in meta["temps"]:
                    raw = card.curves(dev_short, l_um, temp=temp_c, vsb=vsb)
                    for vi, vds_v in enumerate(vds_vals):
                        id_w = np.maximum(raw["id_w"][vi], 1e-18)
                        gm_id = np.nan_to_num(raw["gm_id"][vi], nan=0.0, posinf=0.0, neginf=0.0)
                        gm_gds = np.nan_to_num(raw["gm_gds"][vi], nan=0.0, posinf=0.0, neginf=0.0)
                        ft_hz = np.nan_to_num(raw["ft"][vi], nan=0.0, posinf=0.0, neginf=0.0)
                        cgg_w = np.maximum(raw["cgg_w"][vi], 1e-21)
                        cgd_w = np.maximum(raw["cgd_w"][vi], 1e-21)
                        cdd_w = cgd_w + cdd_overlap_ratio * np.maximum(cgg_w - cgd_w, 0.0)
                        vdsat_v = np.nan_to_num(raw["vdsat"][vi], nan=0.0)
                        vth_v = np.nan_to_num(raw["vth"][vi], nan=0.0)
                        key = _canonical_key((model_name, corner, float(temp_c), float(vds_v), float(l_um)))
                        curves[key] = GmIdCurve(
                            vgs_v=vgs.copy(),
                            gm_id=gm_id,
                            id_w=id_w,
                            gm_gds=gm_gds,
                            ft_hz=ft_hz,
                            cgg_w=cgg_w,
                            cdd_w=cdd_w,
                            cgd_w=cgd_w,
                            vdsat_v=vdsat_v,
                            vth_v=vth_v,
                        )
        return cls(curves=curves, meta={"source": "DeviceCard", "vsb_v": vsb, "card_path": str(card.path)})


def snap_sky130_width(
    w_um: float,
    nf: int | None = None,
    w_finger_min: float = 0.42,
    w_finger_max: float = 10.0,
    grid_um: float = 0.01,
) -> FingerGeometry:
    """Snap a continuous target width ``w_um`` to DRC-clean SKY130A finger geometry.

    Returns ``FingerGeometry(w_total, nf, w_finger)`` with ``w_finger`` quantized
    to ``grid_um`` inside ``[w_finger_min, w_finger_max]``.
    """
    if not math.isfinite(w_um) or w_um <= 0.0:
        raise ValueError(f"w_um must be finite and > 0, got {w_um}")
    if not math.isfinite(grid_um) or grid_um <= 0.0:
        raise ValueError(f"grid_um must be finite and > 0, got {grid_um}")
    if w_finger_min <= 0.0 or w_finger_max < w_finger_min:
        raise ValueError(f"Invalid finger bounds [{w_finger_min}, {w_finger_max}]")

    wf_min = math.ceil(w_finger_min / grid_um - 1e-12) * grid_um
    wf_max = math.floor(w_finger_max / grid_um + 1e-12) * grid_um
    if wf_min > wf_max + 1e-12:
        raise ValueError(f"No grid multiple of {grid_um} inside [{w_finger_min}, {w_finger_max}]")

    def _quantize(val: float) -> float:
        q = round(val / grid_um) * grid_um
        q = min(max(q, wf_min), wf_max)
        return round(q, 6)

    if nf is not None:
        if not isinstance(nf, (int, np.integer)) or int(nf) < 1:
            raise ValueError(f"nf must be a positive integer, got {nf}")
        nf_int = int(nf)
        wf = _quantize(w_um / nf_int)
        return FingerGeometry(w_total=round(nf_int * wf, 6), nf=nf_int, w_finger=wf)

    if w_um <= wf_min:
        wf = round(wf_min, 6)
        return FingerGeometry(w_total=wf, nf=1, w_finger=wf)

    nf_min = max(1, math.ceil(w_um / wf_max - 1e-12))
    nf_max = max(nf_min, math.floor(w_um / wf_min + 1e-12))
    # Limit search window for very large widths while preserving exact grid matches.
    search_hi = min(nf_max, nf_min + 64)

    best_key: tuple[float, int] | None = None
    best_geom: FingerGeometry | None = None
    for cand_nf in range(nf_min, search_hi + 1):
        wf = _quantize(w_um / cand_nf)
        w_tot = round(cand_nf * wf, 6)
        err = round(abs(w_tot - w_um), 9)
        score = (err, cand_nf)
        if best_key is None or score < best_key:
            best_key = score
            best_geom = FingerGeometry(w_total=w_tot, nf=cand_nf, w_finger=wf)
            if err == 0.0:
                break

    assert best_geom is not None
    return best_geom


def build_spice_char_deck(
    device_model: str,
    corner: str,
    temp_c: float | Sequence[float],
    l_list: Sequence[float],
    vds_list: Sequence[float],
    *,
    vgs_start: float = 0.0,
    vgs_stop: float = 1.8,
    vgs_step: float = 0.01,
    vsb_v: float = 0.0,
    finger_w_um: float = 5.0,
    nf: int = 2,
    model_library: str | Path | None = None,
) -> str:
    """Generate a single merged SKY130A ngspice DC/OP sweep deck (does NOT run ngspice).

    Instantiates one device per ``l_um`` in ``l_list`` sharing ``Vg``/``Vd``/``Vb``
    (with polarity-negated B-sources for PMOS) and sweeps ``vgs`` at each
    ``(temp_c, vds_v)`` point inside one ``.control`` block so the SKY130 PDK
    library is loaded only once per corner.
    """
    model = canonical_device_model(device_model)
    cn = corner.lower()
    if cn not in PROCESS:
        raise ValueError(f"Unsupported SKY130 corner {corner!r}; expected one of {PROCESS}")

    temps = [float(temp_c)] if isinstance(temp_c, (int, float, np.number)) else [float(t) for t in temp_c]
    ls = [float(x) for x in l_list]
    vds_vals = [float(v) for v in vds_list]
    if not temps:
        raise ValueError("temp_c must be non-empty")
    if not ls or any(x <= 0.0 for x in ls):
        raise ValueError("l_list must contain positive channel lengths (um)")
    if not vds_vals or any(v <= 0.0 for v in vds_vals):
        raise ValueError("vds_list must contain positive Vds magnitudes (V)")
    if vgs_step <= 0.0 or vgs_stop <= vgs_start:
        raise ValueError("Require vgs_step > 0 and vgs_stop > vgs_start")
    if finger_w_um <= 0.0 or nf < 1:
        raise ValueError("Require finger_w_um > 0 and nf >= 1")

    is_pmos = "pfet" in model.lower()
    lib_path = Path(model_library) if model_library is not None else project.model_library()

    w_tot = finger_w_um * nf
    ad = ((nf + 1) // 2) * finger_w_um * 0.29
    as_ = ((nf + 2) // 2) * finger_w_um * 0.29
    pd = 2.0 * ((nf + 1) // 2) * (finger_w_um + 0.29)
    ps = 2.0 * ((nf + 2) // 2) * (finger_w_um + 0.29)

    params = ("id", "gm", "gds", "gmbs", "vth", "vdsat", "cgg", "cgs", "cgd", "cdd")
    d_node, g_node, b_node = ("dp", "gp", "bp") if is_pmos else ("d", "g", "bn")

    inst_lines: list[str] = []
    save_tokens: list[str] = []
    let_lines: list[str] = []
    vec_names: list[str] = []

    for li, l_um in enumerate(ls):
        inst = f"xdut{li}"
        dev_path = f"@m.{inst}.m{model}"
        inst_lines.append(
            f"{inst} {d_node} {g_node} 0 {b_node} {model} "
            f"w={w_tot:.4f} l={l_um:.4f} nf={nf} "
            f"ad={ad:.4f} as={as_:.4f} pd={pd:.4f} ps={ps:.4f}"
        )
        for q in params:
            vname = f"dut{li}_{q}"
            save_tokens.append(f"{dev_path}[{q}]")
            let_lines.append(f"let {vname}={dev_path}[{q}]")
            vec_names.append(vname)

    control_blocks: list[str] = []
    vec_list = " ".join(vec_names)
    for t in temps:
        t_tag = f"t{int(round(t))}" if abs(t - round(t)) < 1e-9 else f"t{t:g}"
        for vd in vds_vals:
            vd_mv = int(round(vd * 1000.0))
            raw_name = f"{model}_{cn}_{t_tag}_vd{vd_mv}.raw"
            block = [
                f"* sweep temp={t:g} C, |Vds|={vd:.4g} V, |Vsb|={vsb_v:.4g} V",
                f"option temp={t:g}",
                f"alter Vd dc={vd:.6g}",
                f"alter Vb dc={-abs(vsb_v):.6g}",
                f"dc Vg {vgs_start:.6g} {vgs_stop:.6g} {vgs_step:.6g}",
                *let_lines,
                "set filetype=binary",
                f"write {raw_name} {vec_list}",
                "destroy all",
            ]
            control_blocks.append("\n".join(block))

    sources = [
        "Vg g 0 0",
        f"Vd d 0 {vds_vals[0]:.6g}",
        f"Vb bn 0 {-abs(vsb_v):.6g}",
    ]
    if is_pmos:
        sources.extend([
            "Bgp gp 0 V=-v(g)",
            "Bdp dp 0 V=-v(d)",
            "Bbp bp 0 V=-v(bn)",
        ])

    lines = [
        f"SKY130 gm/ID characterization deck: {model} corner={cn}",
        f"* finger_w={finger_w_um:g} um, nf={nf}, total_w={w_tot:g} um; polarity={'PMOS' if is_pmos else 'NMOS'}",
        f'.lib "{lib_path}" {cn}',
        *sources,
        *inst_lines,
        f".temp {temps[0]:g}",
        ".options reltol=1e-5 abstol=1e-15 vntol=1e-7 klu",
        ".save " + " ".join(save_tokens),
        ".control",
        "set wr_singlescale",
        "set wr_vecnames",
        *control_blocks,
        "quit",
        ".endc",
        ".end",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- synthetic EKV reference curves
@dataclass(frozen=True)
class _EkvDeviceParams:
    vth0: float          # V at L_ref, 27 C, TT, Vds=0.9 V
    n_slope: float       # subthreshold slope factor
    mu_cm2_vs: float     # effective low-field mobility at 27 C (cm^2 / V / s)
    cox_f_um2: float     # oxide capacitance per area (F / um^2)
    ec_v_um: float       # critical velocity-saturation field (V / um)
    lambda_um: float     # channel-length modulation coefficient * L (um / V)
    dibl_v_um: float     # DIBL coefficient * L (um)
    c_ov_f_um: float     # gate-source / gate-drain overlap cap per width (F / um)
    c_jd_f_um: float     # drain junction cap per width (F / um)
    is_pmos: bool


_EKV_PARAMS: dict[str, _EkvDeviceParams] = {
    "sky130_fd_pr__nfet_01v8": _EkvDeviceParams(
        vth0=0.48, n_slope=1.34, mu_cm2_vs=285.0, cox_f_um2=8.4e-15,
        ec_v_um=4.2, lambda_um=0.055, dibl_v_um=0.014,
        c_ov_f_um=0.36e-15, c_jd_f_um=0.52e-15, is_pmos=False,
    ),
    "sky130_fd_pr__nfet_01v8_lvt": _EkvDeviceParams(
        vth0=0.34, n_slope=1.36, mu_cm2_vs=310.0, cox_f_um2=8.4e-15,
        ec_v_um=4.0, lambda_um=0.062, dibl_v_um=0.017,
        c_ov_f_um=0.36e-15, c_jd_f_um=0.52e-15, is_pmos=False,
    ),
    "sky130_fd_pr__pfet_01v8": _EkvDeviceParams(
        vth0=0.50, n_slope=1.38, mu_cm2_vs=95.0, cox_f_um2=8.1e-15,
        ec_v_um=5.8, lambda_um=0.048, dibl_v_um=0.012,
        c_ov_f_um=0.34e-15, c_jd_f_um=0.58e-15, is_pmos=True,
    ),
    "sky130_fd_pr__pfet_01v8_lvt": _EkvDeviceParams(
        vth0=0.35, n_slope=1.40, mu_cm2_vs=105.0, cox_f_um2=8.1e-15,
        ec_v_um=5.5, lambda_um=0.045, dibl_v_um=0.011,
        c_ov_f_um=0.34e-15, c_jd_f_um=0.58e-15, is_pmos=True,
    ),
}

# (dvth_v, mu_scale) per process corner for NMOS / PMOS.
_CORNER_SHIFT_N: dict[str, tuple[float, float]] = {
    "tt": (0.000, 1.00),
    "ss": (+0.055, 0.88),
    "ff": (-0.055, 1.12),
    "sf": (+0.050, 0.90),
    "fs": (-0.050, 1.10),
}
_CORNER_SHIFT_P: dict[str, tuple[float, float]] = {
    "tt": (0.000, 1.00),
    "ss": (+0.055, 0.88),
    "ff": (-0.055, 1.12),
    "sf": (-0.050, 1.10),
    "fs": (+0.050, 0.90),
}


def _ekv_curve(
    model: str,
    corner: str,
    temp_c: float,
    vds_v: float,
    l_um: float,
    vgs: np.ndarray,
) -> GmIdCurve:
    p = _EKV_PARAMS[model]
    cn = corner.lower()
    if cn not in PROCESS:
        raise ValueError(f"Unknown corner {corner!r}")
    dvth_cn, mu_cn = (_CORNER_SHIFT_P if p.is_pmos else _CORNER_SHIFT_N)[cn]

    t_k = temp_c + 273.15
    ut = 8.617333262e-5 * t_k
    n = p.n_slope + 0.03 * (0.15 / max(l_um, 0.15))

    # Threshold voltage with mild reverse short-channel rolloff, tempco, and DIBL.
    vth_scalar = (
        p.vth0
        + dvth_cn
        - 1.1e-3 * (temp_c - 27.0)
        + 0.025 * (1.0 - 0.15 / max(l_um, 0.15))
        - (p.dibl_v_um / l_um) * (vds_v - 0.9)
    )
    vth_scalar = max(vth_scalar, 0.12)

    # Effective mobility: cm^2/(V*s) -> um^2/(V*s) via 1e8, with temperature exponent -1.45.
    mu_um2_vs = p.mu_cm2_vs * 1e8 * mu_cn * ((t_k / 300.15) ** -1.45)
    ispec_w = 2.0 * n * mu_um2_vs * p.cox_f_um2 * (ut ** 2) / l_um  # A / um

    # Velocity-saturation factor theta = 2 * n * Ut / (Ec * L).
    theta = (2.0 * n * ut) / (p.ec_v_um * l_um)
    lam = p.lambda_um / l_um
    dibl = p.dibl_v_um / l_um

    def _id_w_eval(vg_arr: np.ndarray, vd_val: float) -> np.ndarray:
        vth_eff = max(
            p.vth0
            + dvth_cn
            - 1.1e-3 * (temp_c - 27.0)
            + 0.025 * (1.0 - 0.15 / max(l_um, 0.15))
            - dibl * (vd_val - 0.9),
            0.12,
        )
        vf = (vg_arr - vth_eff) / (2.0 * n * ut)
        vr = (vg_arr - vth_eff - n * vd_val) / (2.0 * n * ut)
        qf = np.logaddexp(0.0, vf)
        qr = np.logaddexp(0.0, vr)
        i_f = qf ** 2
        i_r = qr ** 2
        vsat_denom = 1.0 + theta * qf
        return ispec_w * ((i_f - i_r) / vsat_denom) * (1.0 + lam * vd_val)

    id_w = np.maximum(_id_w_eval(vgs, vds_v), 1e-18)

    # Central finite differences on the exact smooth EKV expression for exact gm and gds.
    dvg = 1e-5
    dvd = 1e-5
    gm_w = np.maximum((_id_w_eval(vgs + dvg, vds_v) - _id_w_eval(vgs - dvg, vds_v)) / (2.0 * dvg), 1e-20)
    gds_w = np.maximum((_id_w_eval(vgs, vds_v + dvd) - _id_w_eval(vgs, vds_v - dvd)) / (2.0 * dvd), 1e-22)

    gm_id = gm_w / id_w
    gm_gds = gm_w / gds_w

    # Inversion factor qf for smooth Vdsat and capacitance transition.
    vf = (vgs - vth_scalar) / (2.0 * n * ut)
    qf = np.logaddexp(0.0, vf)
    i_f = qf ** 2
    inv_frac = i_f / (1.0 + i_f)

    # Smooth saturation drain voltage (weak -> ~4*Ut, strong -> velocity-saturated overdrive).
    vov_eff = (2.0 * ut * qf) / (1.0 + 0.5 * theta * qf)
    vdsat_v = 3.5 * ut + vov_eff

    # Capacitances per unit width (F / um).
    cox_l = p.cox_f_um2 * l_um
    triode_frac = 1.0 / (1.0 + np.exp(np.clip((vds_v - vdsat_v) / (3.0 * ut), -40.0, 40.0)))
    c_intrinsic = cox_l * (0.35 + 0.32 * inv_frac + 0.18 * inv_frac * triode_frac)
    cgg_w = c_intrinsic + 2.0 * p.c_ov_f_um
    cgd_w = p.c_ov_f_um + 0.33 * cox_l * inv_frac * triode_frac
    cdd_w = cgd_w + p.c_jd_f_um / math.sqrt(1.0 + vds_v / 0.7)
    ft_hz = gm_w / (2.0 * math.pi * cgg_w)
    vth_v = np.full_like(vgs, vth_scalar)

    return GmIdCurve(
        vgs_v=vgs.copy(),
        gm_id=gm_id,
        id_w=id_w,
        gm_gds=gm_gds,
        ft_hz=ft_hz,
        cgg_w=cgg_w,
        cdd_w=cdd_w,
        cgd_w=cgd_w,
        vdsat_v=vdsat_v,
        vth_v=vth_v,
    )


def synthetic_ekv_table(
    device_models: Sequence[str] = (
        "sky130_fd_pr__nfet_01v8",
        "sky130_fd_pr__nfet_01v8_lvt",
        "sky130_fd_pr__pfet_01v8",
        "sky130_fd_pr__pfet_01v8_lvt",
    ),
    corners: Sequence[str] = ("tt",),
    temps_c: Sequence[float] = (27.0,),
    vds_list: Sequence[float] = (0.45, 0.9, 1.35),
    l_list: Sequence[float] | None = None,
    vgs_grid: np.ndarray | None = None,
) -> GmIdTable:
    """Build an analytic EKV-calibrated SKY130A ``GmIdTable`` (zero ngspice).

    Useful for instant unit testing and coarse first-pass sizing before SPICE
    device-card calibration.
    """
    vgs = (
        np.round(np.linspace(0.05, 1.80, 176), 6)
        if vgs_grid is None
        else np.asarray(vgs_grid, dtype=float)
    )
    curves: dict[GmIdKey, GmIdCurve] = {}
    for raw_model in device_models:
        model = canonical_device_model(raw_model)
        if model not in _EKV_PARAMS:
            raise ValueError(
                f"Unknown synthetic SKY130 model {raw_model!r}; "
                f"supported: {sorted(_EKV_PARAMS)}"
            )
        ls = DEFAULT_L_LIST[model] if l_list is None else tuple(float(x) for x in l_list)
        for cn in corners:
            for t in temps_c:
                for vd in vds_list:
                    for l_um in ls:
                        key = _canonical_key((model, cn, float(t), float(vd), float(l_um)))
                        curves[key] = _ekv_curve(model, cn, float(t), float(vd), float(l_um), vgs)
    return GmIdTable(
        curves=curves,
        meta={
            "source": "synthetic_ekv",
            "pdk": "sky130A",
            "note": "Analytic EKV-calibrated reference curves for first-pass sizing and tests; calibrate with SPICE.",
        },
    )
