"""Resumable multi-corner circuit optimizer (LHS + GP cEI + Pareto + local polish).

Pure ``numpy`` + ``scipy`` implementation with zero external BO dependencies:

* ``ParamSpec`` / ``ParamSpace``: continuous, log-scale, and grid-snapped
  parameters mapped cleanly to the unit hypercube ``[0, 1]^d``.
* ``lhs_sample``: maximin Latin Hypercube Sampling for space-filling init.
* ``GaussianProcess``: ARD or isotropic Matérn-5/2 Gaussian Process with
  progressive Cholesky jitter stabilization and analytical-gradient L-BFGS-B
  log-marginal-likelihood hyperparameter fitting (scalar & multi-output).
* ``suggest_next_batch``: Constrained Expected Improvement (cEI) with
  Kriging Believer parallel batching (matching the repo's ``workers <= 4``
  ngspice concurrency cap).
* ``pareto_front``: exact non-dominated front extraction with feasibility filter.
* ``worst_corner_margin``: 45-corner / boundary-corner minimax margin report.
* ``OptCampaign``: crash-resumable JSONL trial logger (``trials.jsonl``) with
  SHA-256 space/config and per-trial input-identity verification.
* ``polish_local``: bounded Powell / Nelder-Mead local refinement around the
  best feasible surrogate candidate.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np
from scipy.linalg import solve_triangular
from scipy.optimize import minimize
from scipy.spatial.distance import cdist, pdist
from scipy.special import log_ndtr
from scipy.stats import norm

from .robust_sizing import pareto_mask


# ---------------------------------------------------------------- parameter space
@dataclass(frozen=True)
class ParamSpec:
    """Single optimization parameter with optional log scaling and discrete grid step."""

    name: str
    low: float
    high: float
    log: bool = False
    step: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("ParamSpec.name must be non-empty")
        if not (math.isfinite(self.low) and math.isfinite(self.high)) or self.high <= self.low:
            raise ValueError(f"ParamSpec {self.name!r}: require finite low < high, got [{self.low}, {self.high}]")
        if self.log and self.low <= 0.0:
            raise ValueError(f"ParamSpec {self.name!r}: log=True requires low > 0, got {self.low}")
        if self.step is not None and (not math.isfinite(self.step) or self.step <= 0.0):
            raise ValueError(f"ParamSpec {self.name!r}: step must be finite and > 0, got {self.step}")

    def snap(self, value: float) -> float:
        v = float(min(max(value, self.low), self.high))
        if self.step is not None:
            k = round((v - self.low) / self.step)
            v = self.low + k * self.step
            if v > self.high + 1e-12:
                v = self.low + math.floor((self.high - self.low) / self.step + 1e-12) * self.step
            v = min(max(v, self.low), self.high)
            # Clean floating-point representation noise (e.g. 0.30000000000000004).
            decimals = max(0, -int(math.floor(math.log10(self.step))) + 4)
            v = round(v, min(decimals, 12))
        return float(v)

    def to_unit(self, value: float) -> float:
        v = float(min(max(value, self.low), self.high))
        if self.log:
            u = (math.log(v) - math.log(self.low)) / (math.log(self.high) - math.log(self.low))
        else:
            u = (v - self.low) / (self.high - self.low)
        return float(min(max(u, 0.0), 1.0))

    def from_unit(self, u: float, *, snap: bool = True) -> float:
        uc = float(min(max(u, 0.0), 1.0))
        if self.log:
            v = math.exp(math.log(self.low) + uc * (math.log(self.high) - math.log(self.low)))
        else:
            v = self.low + uc * (self.high - self.low)
        return self.snap(v) if snap else float(v)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "low": self.low,
            "high": self.high,
            "log": self.log,
            "step": self.step,
        }


class ParamSpace:
    """Ordered collection of ``ParamSpec`` objects with unit-cube ``[0, 1]^d`` transforms."""

    def __init__(self, params: Sequence[ParamSpec]) -> None:
        items = tuple(params)
        if not items:
            raise ValueError("ParamSpace requires at least one ParamSpec")
        names = [p.name for p in items]
        if len(set(names)) != len(names):
            raise ValueError(f"Duplicate parameter names in ParamSpace: {names}")
        self.params: tuple[ParamSpec, ...] = items
        self._by_name: dict[str, ParamSpec] = {p.name: p for p in items}

    @property
    def dim(self) -> int:
        return len(self.params)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(p.name for p in self.params)

    def to_unit(self, point: Mapping[str, float] | Sequence[float]) -> np.ndarray:
        if isinstance(point, Mapping):
            return np.array([p.to_unit(float(point[p.name])) for p in self.params], dtype=float)
        arr = np.asarray(point, dtype=float)
        if arr.shape != (self.dim,):
            raise ValueError(f"Expected vector of length {self.dim}, got shape {arr.shape}")
        return np.array([p.to_unit(float(v)) for p, v in zip(self.params, arr)], dtype=float)

    def to_unit_batch(self, points: Sequence[Mapping[str, float]]) -> np.ndarray:
        if not points:
            return np.empty((0, self.dim), dtype=float)
        return np.vstack([self.to_unit(pt) for pt in points])

    def from_unit(self, u: Sequence[float] | np.ndarray, *, snap: bool = True) -> dict[str, float]:
        arr = np.asarray(u, dtype=float)
        if arr.shape != (self.dim,):
            raise ValueError(f"Expected unit vector of length {self.dim}, got shape {arr.shape}")
        return {p.name: p.from_unit(float(ui), snap=snap) for p, ui in zip(self.params, arr)}

    def from_unit_batch(self, U: np.ndarray, *, snap: bool = True) -> list[dict[str, float]]:
        arr = np.asarray(U, dtype=float)
        if arr.ndim != 2 or arr.shape[1] != self.dim:
            raise ValueError(f"Expected (N, {self.dim}) unit array, got shape {arr.shape}")
        return [self.from_unit(row, snap=snap) for row in arr]

    def snap(self, point: Mapping[str, float]) -> dict[str, float]:
        return {p.name: p.snap(float(point[p.name])) for p in self.params}

    def contains(self, point: Mapping[str, float], tol: float = 1e-12) -> bool:
        for p in self.params:
            if p.name not in point:
                return False
            v = float(point[p.name])
            if not (p.low - tol <= v <= p.high + tol):
                return False
        return True

    def to_list(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.params]

    def signature(self) -> str:
        raw = json.dumps(self.to_list(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()


def params_sha256(space: ParamSpace, params: Mapping[str, float]) -> str:
    """Canonical SHA-256 identity hash of snapped parameter values."""
    snapped = space.snap(params)
    canonical = {k: float(f"{snapped[k]:.12g}") for k in space.names}
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


# ---------------------------------------------------------------- LHS sampling
def lhs_unit(dim: int, n: int, *, seed: int = 0, candidates: int = 32) -> np.ndarray:
    """Maximin Latin Hypercube Sampling in ``[0, 1]^dim``."""
    if dim < 1:
        raise ValueError(f"dim must be >= 1, got {dim}")
    if n < 0:
        raise ValueError(f"n must be >= 0, got {n}")
    if n == 0:
        return np.empty((0, dim), dtype=float)
    rng = np.random.default_rng(seed)
    if n == 1:
        return rng.uniform(0.0, 1.0, size=(1, dim))

    best_u: np.ndarray | None = None
    best_min_dist = -1.0
    n_cand = max(1, int(candidates))
    for _ in range(n_cand):
        u = np.empty((n, dim), dtype=float)
        for j in range(dim):
            perm = rng.permutation(n)
            u[:, j] = (perm + rng.uniform(0.0, 1.0, size=n)) / n
        min_d = float(np.min(pdist(u)))
        if min_d > best_min_dist:
            best_min_dist = min_d
            best_u = u
    assert best_u is not None
    return best_u


def lhs_sample(
    space: ParamSpace,
    n: int,
    *,
    seed: int = 0,
    candidates: int = 32,
    snap: bool = True,
) -> list[dict[str, float]]:
    """Generate ``n`` maximin Latin Hypercube samples mapped into ``space``."""
    u = lhs_unit(space.dim, n, seed=seed, candidates=candidates)
    return space.from_unit_batch(u, snap=snap)


# ---------------------------------------------------------------- constraints & corner margins
@dataclass(frozen=True)
class ConstraintSpec:
    """Bounds ``low <= metric[key] <= high`` with optional normalization scale."""

    key: str
    low: float | None = None
    high: float | None = None
    scale: float | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("ConstraintSpec.key must be non-empty")
        if self.low is None and self.high is None:
            raise ValueError(f"ConstraintSpec {self.key!r} must specify low and/or high")
        if self.low is not None and self.high is not None and self.low > self.high:
            raise ValueError(f"ConstraintSpec {self.key!r}: low={self.low} > high={self.high}")
        if self.scale is not None and (not math.isfinite(self.scale) or self.scale <= 0.0):
            raise ValueError(f"ConstraintSpec {self.key!r}: scale must be > 0, got {self.scale}")

    def is_satisfied(self, value: float, tol: float = 0.0) -> bool:
        if not math.isfinite(value):
            return False
        if self.low is not None and value < self.low - tol:
            return False
        if self.high is not None and value > self.high + tol:
            return False
        return True

    def margin(self, value: float, *, normalize: bool = False) -> float:
        """Signed margin (positive = passing, negative = violating)."""
        if not math.isfinite(value):
            return -float("inf")
        margins: list[float] = []
        if self.low is not None:
            m = value - self.low
            if normalize:
                denom = self.scale if self.scale is not None else max(abs(self.low), 1e-12)
                m /= denom
            margins.append(m)
        if self.high is not None:
            m = self.high - value
            if normalize:
                denom = self.scale if self.scale is not None else max(abs(self.high), 1e-12)
                m /= denom
            margins.append(m)
        return float(min(margins))

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "low": self.low, "high": self.high, "scale": self.scale}


ConstraintsInput = (
    Sequence[ConstraintSpec]
    | Mapping[str, tuple[float | None, float | None] | ConstraintSpec]
    | None
)


def normalize_constraints(constraints: ConstraintsInput) -> list[ConstraintSpec]:
    """Normalize dict ``{key: (low, high)}`` or sequence of ``ConstraintSpec``."""
    if constraints is None:
        return []
    if isinstance(constraints, Mapping):
        out: list[ConstraintSpec] = []
        for k, spec in constraints.items():
            if isinstance(spec, ConstraintSpec):
                out.append(spec)
            else:
                lo, hi = spec
                out.append(ConstraintSpec(key=str(k), low=lo, high=hi))
        return out
    return [c if isinstance(c, ConstraintSpec) else ConstraintSpec(**c) for c in constraints]


def is_feasible(metrics: Mapping[str, Any], constraints: ConstraintsInput) -> bool:
    """Return True iff every constraint in ``constraints`` is finite and satisfied."""
    for c in normalize_constraints(constraints):
        val = metrics.get(c.key)
        if val is None or not c.is_satisfied(float(val)):
            return False
    return True


@dataclass(frozen=True)
class CornerMarginReport:
    """Minimax corner margin summary across PVT / boundary corners."""

    worst_margin: float
    worst_corner: str
    worst_metric: str
    feasible: bool
    per_corner_min: dict[str, float]
    margins: dict[str, dict[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "worst_margin": self.worst_margin,
            "worst_corner": self.worst_corner,
            "worst_metric": self.worst_metric,
            "feasible": self.feasible,
            "per_corner_min": dict(self.per_corner_min),
            "margins": {cn: dict(m) for cn, m in self.margins.items()},
        }


def worst_corner_margin(
    corner_metrics: Mapping[str, Mapping[str, float]],
    spec_bounds: ConstraintsInput,
    *,
    normalize: bool = False,
) -> CornerMarginReport:
    """Evaluate minimax worst-case signed margin across all supplied corners and specs.

    Positive margin means every spec passes at every corner; negative margin
    identifies the limiting corner and metric.
    """
    specs = normalize_constraints(spec_bounds)
    if not corner_metrics:
        raise ValueError("corner_metrics must be non-empty")
    if not specs:
        raise ValueError("spec_bounds must be non-empty")

    margins: dict[str, dict[str, float]] = {}
    per_corner_min: dict[str, float] = {}
    worst_val = float("inf")
    worst_cn = ""
    worst_key = ""

    for cn, metrics in corner_metrics.items():
        cn_margins: dict[str, float] = {}
        cn_worst = float("inf")
        for s in specs:
            raw = metrics.get(s.key)
            m = -float("inf") if raw is None else s.margin(float(raw), normalize=normalize)
            cn_margins[s.key] = m
            if m < cn_worst:
                cn_worst = m
            if m < worst_val:
                worst_val = m
                worst_cn = str(cn)
                worst_key = s.key
        margins[str(cn)] = cn_margins
        per_corner_min[str(cn)] = cn_worst

    return CornerMarginReport(
        worst_margin=float(worst_val),
        worst_corner=worst_cn,
        worst_metric=worst_key,
        feasible=bool(math.isfinite(worst_val) and worst_val >= 0.0),
        per_corner_min=per_corner_min,
        margins=margins,
    )


# ---------------------------------------------------------------- Gaussian Process (Matérn-5/2)
_SQRT5 = math.sqrt(5.0)
_OPENBLAS_HANDLES: list[tuple[Any, Any]] | None = None


def _discover_openblas() -> list[tuple[Any, Any]]:
    """Locate numpy/scipy OpenBLAS get/set thread symbols once (no-op if absent)."""
    global _OPENBLAS_HANDLES
    if _OPENBLAS_HANDLES is not None:
        return _OPENBLAS_HANDLES
    handles: list[tuple[Any, Any]] = []
    try:
        site_dir = Path(np.__file__).resolve().parent.parent
        for pat in ("numpy.libs/*openblas*.so*", "scipy.libs/*openblas*.so*"):
            for lib_path in site_dir.glob(pat):
                lib = ctypes.CDLL(str(lib_path))
                for prefix in ("scipy_openblas_", "openblas_"):
                    for suffix in ("64_", ""):
                        getter = getattr(lib, f"{prefix}get_num_threads{suffix}", None)
                        setter = getattr(lib, f"{prefix}set_num_threads{suffix}", None)
                        if getter is not None and setter is not None:
                            getter.restype = ctypes.c_int
                            setter.argtypes = [ctypes.c_int]
                            handles.append((getter, setter))
                            break
                    else:
                        continue
                    break
    except OSError:
        handles = []
    _OPENBLAS_HANDLES = handles
    return handles


@contextmanager
def _single_thread_blas() -> Iterator[None]:
    """Avoid OpenBLAS thread-pool contention on small GP matrices during concurrent ngspice runs."""
    handles = _discover_openblas()
    prev: list[tuple[Any, int]] = []
    for getter, setter in handles:
        cur = int(getter())
        if cur != 1:
            setter(1)
            prev.append((setter, cur))
    try:
        yield
    finally:
        for setter, cur in prev:
            setter(cur)


def _cholesky_with_jitter(K: np.ndarray, base_jitter: float = 1e-10) -> tuple[np.ndarray, float]:
    n = K.shape[0]
    eye = np.eye(n, dtype=float)
    for scale in (0.0, 1.0, 1e2, 1e4, 1e6, 1e8):
        jit = base_jitter * scale
        try:
            L = np.linalg.cholesky(K + jit * eye)
            return L, jit
        except np.linalg.LinAlgError:
            continue
    # Final fallback: eigenvalue floor.
    eigvals, eigvecs = np.linalg.eigh(0.5 * (K + K.T))
    floor = max(base_jitter * 1e6, 1e-6 * float(np.max(eigvals)))
    K_psd = (eigvecs * np.maximum(eigvals, floor)) @ eigvecs.T
    return np.linalg.cholesky(K_psd), floor


class _ScalarGP:
    """Single-output Matérn-5/2 GP with ARD/isotropic lengthscales and LML optimization."""

    def __init__(
        self,
        *,
        ard: bool = True,
        noise_floor: float = 1e-6,
        n_restarts: int = 2,
        seed: int = 0,
    ) -> None:
        self.ard = ard
        self.noise_floor = float(noise_floor)
        self.n_restarts = max(1, int(n_restarts))
        self.seed = int(seed)

        self.X_: np.ndarray | None = None
        self.y_mean_: float = 0.0
        self.y_std_: float = 1.0
        self.lengthscales_: np.ndarray | None = None
        self.signal_var_: float = 1.0
        self.noise_var_: float = float(noise_floor)
        self.L_: np.ndarray | None = None
        self.alpha_: np.ndarray | None = None
        self.lml_: float = -float("inf")

    @staticmethod
    def _kernel(X1: np.ndarray, X2: np.ndarray, ls: np.ndarray, signal_var: float) -> np.ndarray:
        A = X1 / ls
        B = X2 / ls
        r = cdist(A, B, metric="euclidean")
        z = _SQRT5 * r
        return signal_var * (1.0 + z + (z * z) / 3.0) * np.exp(-z)

    def _neg_lml_and_grad(self, theta: np.ndarray, X: np.ndarray, y_norm: np.ndarray) -> tuple[float, np.ndarray]:
        n, d = X.shape
        if self.ard:
            log_ls = theta[:d]
            ls = np.exp(log_ls)
            log_sf2 = float(theta[d])
            log_sn2 = float(theta[d + 1])
        else:
            ls = np.full(d, math.exp(float(theta[0])), dtype=float)
            log_sf2 = float(theta[1])
            log_sn2 = float(theta[2])

        sf2 = math.exp(log_sf2)
        sn2 = math.exp(log_sn2)

        # Pairwise scaled squared differences.
        diff = X[:, None, :] - X[None, :, :]          # (n, n, d)
        scaled_sq = (diff / ls[None, None, :]) ** 2   # (n, n, d)
        r2 = np.sum(scaled_sq, axis=2)
        r = np.sqrt(np.maximum(r2, 0.0))
        z = _SQRT5 * r
        exp_mz = np.exp(-z)

        K_sig = sf2 * (1.0 + z + (z * z) / 3.0) * exp_mz
        K = K_sig + sn2 * np.eye(n, dtype=float)
        L, _ = _cholesky_with_jitter(K)

        # alpha = K^-1 y_norm
        v = solve_triangular(L, y_norm, lower=True, check_finite=False)
        alpha = solve_triangular(L.T, v, lower=False, check_finite=False)
        logdet = 2.0 * float(np.sum(np.log(np.diag(L))))
        neg_lml = 0.5 * float(np.dot(y_norm, alpha)) + 0.5 * logdet + 0.5 * n * math.log(2.0 * math.pi)

        # W = K^-1 - alpha alpha^T  =>  d(neg_lml)/d(theta) = 0.5 * sum(W * dK/dtheta)
        L_inv = solve_triangular(L, np.eye(n, dtype=float), lower=True, check_finite=False)
        K_inv = L_inv.T @ L_inv
        W = K_inv - np.outer(alpha, alpha)

        # Exact derivative: dK/d(log l_j) = (5/3) * sf2 * (1 + z) * exp(-z) * (diff_j / l_j)^2
        common = (5.0 / 3.0) * sf2 * (1.0 + z) * exp_mz
        grad = np.empty_like(theta)
        if self.ard:
            for j in range(d):
                dK_dj = common * scaled_sq[:, :, j]
                grad[j] = 0.5 * float(np.sum(W * dK_dj))
            grad[d] = 0.5 * float(np.sum(W * K_sig))
            grad[d + 1] = 0.5 * sn2 * float(np.trace(W))
        else:
            dK_dl = common * r2
            grad[0] = 0.5 * float(np.sum(W * dK_dl))
            grad[1] = 0.5 * float(np.sum(W * K_sig))
            grad[2] = 0.5 * sn2 * float(np.trace(W))

        return neg_lml, grad

    def fit(self, X: np.ndarray, y: np.ndarray, *, optimize: bool = True) -> "_ScalarGP":
        X = np.asarray(X, dtype=float)
        y = np.asarray(y, dtype=float).ravel()
        if X.ndim != 2 or X.shape[0] != y.size or y.size == 0:
            raise ValueError("X must be (N, D) matching 1D y of length N >= 1")
        n, d = X.shape
        self.X_ = X.copy()
        self.y_mean_ = float(np.mean(y))
        std = float(np.std(y))
        self.y_std_ = std if std > 1e-12 else 1.0
        y_norm = (y - self.y_mean_) / self.y_std_

        n_ls = d if self.ard else 1
        ls_bounds = [(math.log(0.03), math.log(10.0))] * n_ls
        bounds = ls_bounds + [
            (math.log(1e-3), math.log(1e2)),
            (math.log(max(self.noise_floor, 1e-10)), math.log(0.5)),
        ]

        with _single_thread_blas():
            if optimize and n >= 3:
                rng = np.random.default_rng(self.seed)
                inits = [np.array([math.log(0.5)] * n_ls + [0.0, math.log(max(self.noise_floor * 10.0, 1e-5))])]
                for _ in range(self.n_restarts - 1):
                    inits.append(
                        np.concatenate([
                            rng.uniform(math.log(0.1), math.log(2.5), size=n_ls),
                            rng.uniform(math.log(0.2), math.log(3.0), size=1),
                            rng.uniform(math.log(max(self.noise_floor, 1e-8)), math.log(1e-2), size=1),
                        ])
                    )

                best_val = float("inf")
                best_theta = inits[0]
                for x0 in inits:
                    res = minimize(
                        self._neg_lml_and_grad,
                        x0,
                        args=(X, y_norm),
                        method="L-BFGS-B",
                        jac=True,
                        bounds=bounds,
                        options={"maxiter": 45, "ftol": 1e-7},
                    )
                    if math.isfinite(res.fun) and res.fun < best_val:
                        best_val = float(res.fun)
                        best_theta = np.asarray(res.x, dtype=float)
                self.lml_ = -best_val
            else:
                if self.lengthscales_ is not None and self.lengthscales_.size == d:
                    best_theta = np.concatenate([
                        np.log(self.lengthscales_) if self.ard else np.array([math.log(float(self.lengthscales_[0]))]),
                        np.array([math.log(self.signal_var_), math.log(max(self.noise_var_, self.noise_floor))]),
                    ])
                else:
                    best_theta = np.array([math.log(0.5)] * n_ls + [0.0, math.log(max(self.noise_floor, 1e-6))])

            if self.ard:
                self.lengthscales_ = np.exp(best_theta[:d])
                self.signal_var_ = math.exp(float(best_theta[d]))
                self.noise_var_ = math.exp(float(best_theta[d + 1]))
            else:
                self.lengthscales_ = np.full(d, math.exp(float(best_theta[0])), dtype=float)
                self.signal_var_ = math.exp(float(best_theta[1]))
                self.noise_var_ = math.exp(float(best_theta[2]))

            K = self._kernel(X, X, self.lengthscales_, self.signal_var_) + self.noise_var_ * np.eye(n, dtype=float)
            self.L_, _ = _cholesky_with_jitter(K)
            v = solve_triangular(self.L_, y_norm, lower=True, check_finite=False)
            self.alpha_ = solve_triangular(self.L_.T, v, lower=False, check_finite=False)
        return self

    def clone_with_fantasy(self, x_new: np.ndarray, y_new: float) -> "_ScalarGP":
        """Return a shallow updated GP incorporating a Kriging Believer fantasy point (fixed kernel)."""
        assert self.X_ is not None and self.lengthscales_ is not None
        X_aug = np.vstack([self.X_, np.atleast_2d(x_new)])
        # Reconstruct unnormalized y from L, alpha: K @ alpha = y_norm.
        y_prev_norm = self.L_ @ (self.L_.T @ self.alpha_)
        y_prev = self.y_mean_ + self.y_std_ * y_prev_norm
        y_aug = np.append(y_prev, float(y_new))

        child = _ScalarGP(ard=self.ard, noise_floor=self.noise_floor, n_restarts=1, seed=self.seed)
        child.lengthscales_ = self.lengthscales_.copy()
        child.signal_var_ = self.signal_var_
        child.noise_var_ = self.noise_var_
        child.fit(X_aug, y_aug, optimize=False)
        return child

    def predict(self, X_test: np.ndarray, *, return_std: bool = True) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
        if self.X_ is None or self.L_ is None or self.alpha_ is None or self.lengthscales_ is None:
            raise RuntimeError("GaussianProcess must be fitted before calling predict()")
        X_q = np.atleast_2d(np.asarray(X_test, dtype=float))
        with _single_thread_blas():
            K_star = self._kernel(X_q, self.X_, self.lengthscales_, self.signal_var_)
            mean = self.y_mean_ + self.y_std_ * (K_star @ self.alpha_)
            if not return_std:
                return mean
            v = solve_triangular(self.L_, K_star.T, lower=True, check_finite=False)
        var_norm = np.maximum(self.signal_var_ - np.sum(v * v, axis=0), 1e-16)
        std = self.y_std_ * np.sqrt(var_norm)
        return mean, std


class GaussianProcess:
    """Matérn-5/2 Gaussian Process supporting scalar (1D) and multi-output (2D) targets."""

    def __init__(
        self,
        *,
        ard: bool = True,
        noise_floor: float = 1e-6,
        n_restarts: int = 3,
        seed: int = 0,
    ) -> None:
        self.ard = ard
        self.noise_floor = float(noise_floor)
        self.n_restarts = max(1, int(n_restarts))
        self.seed = int(seed)
        self._models: list[_ScalarGP] = []
        self._is_scalar: bool = True

    def fit(self, X: np.ndarray, y: np.ndarray) -> "GaussianProcess":
        X_arr = np.asarray(X, dtype=float)
        y_arr = np.asarray(y, dtype=float)
        if y_arr.ndim == 1:
            self._is_scalar = True
            y_2d = y_arr[:, None]
        elif y_arr.ndim == 2:
            self._is_scalar = False
            y_2d = y_arr
        else:
            raise ValueError(f"y must be 1D or 2D, got shape {y_arr.shape}")

        self._models = []
        for m in range(y_2d.shape[1]):
            gp = _ScalarGP(
                ard=self.ard,
                noise_floor=self.noise_floor,
                n_restarts=self.n_restarts,
                seed=self.seed + 37 * m,
            )
            gp.fit(X_arr, y_2d[:, m], optimize=True)
            self._models.append(gp)
        return self

    def predict(
        self,
        X_test: np.ndarray,
        *,
        return_std: bool = True,
    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
        if not self._models:
            raise RuntimeError("GaussianProcess must be fitted before predict()")
        if self._is_scalar:
            return self._models[0].predict(X_test, return_std=return_std)
        if return_std:
            means, stds = zip(*(m.predict(X_test, return_std=True) for m in self._models))
            return np.column_stack(means), np.column_stack(stds)
        means = [m.predict(X_test, return_std=False) for m in self._models]
        return np.column_stack(means)

    @property
    def lengthscales(self) -> np.ndarray:
        if not self._models:
            raise RuntimeError("GaussianProcess is not fitted")
        if self._is_scalar:
            assert self._models[0].lengthscales_ is not None
            return self._models[0].lengthscales_.copy()
        return np.vstack([m.lengthscales_ for m in self._models if m.lengthscales_ is not None])


# ---------------------------------------------------------------- cEI + Kriging Believer
def _expected_improvement(mean: np.ndarray, std: np.ndarray, best_min: float, xi: float = 0.0) -> np.ndarray:
    """Expected Improvement for minimization of objective ``g(x)``."""
    safe_std = np.maximum(std, 1e-12)
    imp = best_min - mean - xi
    z = imp / safe_std
    ei = imp * norm.cdf(z) + safe_std * norm.pdf(z)
    return np.where(std > 1e-12, np.maximum(ei, 0.0), 0.0)


def _constraint_log_pof(
    X_q: np.ndarray,
    constraint_gps: list[tuple[ConstraintSpec, _ScalarGP]],
) -> np.ndarray:
    """Sum of log probabilities of feasibility across all constraints (underflow-safe)."""
    n = X_q.shape[0]
    log_p = np.zeros(n, dtype=float)
    for spec, gp in constraint_gps:
        mu, sd = gp.predict(X_q, return_std=True)
        sd = np.maximum(sd, 1e-12)
        if spec.low is not None and spec.high is not None:
            p_hi = norm.cdf((spec.high - mu) / sd)
            p_lo = norm.cdf((spec.low - mu) / sd)
            prob = np.maximum(p_hi - p_lo, 1e-300)
            log_p += np.log(prob)
        elif spec.low is not None:
            log_p += log_ndtr((mu - spec.low) / sd)
        elif spec.high is not None:
            log_p += log_ndtr((spec.high - mu) / sd)
    return log_p


def _extract_history_arrays(
    history: Sequence[Mapping[str, Any]],
    space: ParamSpace,
    objective_key: str,
    constraints: list[ConstraintSpec],
    minimize_obj: bool,
) -> tuple[np.ndarray, np.ndarray, list[tuple[ConstraintSpec, np.ndarray]], np.ndarray, set[str]]:
    X_rows: list[np.ndarray] = []
    y_rows: list[float] = []
    c_cols: list[list[float]] = [[] for _ in constraints]
    feas_rows: list[bool] = []
    seen_hashes: set[str] = set()

    for rec in history:
        params = rec["params"] if "params" in rec else rec
        metrics = rec["metrics"] if "metrics" in rec else rec
        if rec.get("status", "ok") != "ok":
            seen_hashes.add(params_sha256(space, params))
            continue
        obj_raw = metrics.get(objective_key)
        if obj_raw is None or not math.isfinite(float(obj_raw)):
            seen_hashes.add(params_sha256(space, params))
            continue
        c_vals: list[float] = []
        valid = True
        for c in constraints:
            cv = metrics.get(c.key)
            if cv is None or not math.isfinite(float(cv)):
                valid = False
                break
            c_vals.append(float(cv))
        if not valid:
            seen_hashes.add(params_sha256(space, params))
            continue

        X_rows.append(space.to_unit(params))
        obj_v = float(obj_raw)
        y_rows.append(obj_v if minimize_obj else -obj_v)
        for ci, cv in enumerate(c_vals):
            c_cols[ci].append(cv)
        feas_rows.append(all(c.is_satisfied(cv) for c, cv in zip(constraints, c_vals)))
        seen_hashes.add(params_sha256(space, params))

    if not X_rows:
        return (
            np.empty((0, space.dim), dtype=float),
            np.empty((0,), dtype=float),
            [(c, np.empty((0,), dtype=float)) for c in constraints],
            np.empty((0,), dtype=bool),
            seen_hashes,
        )
    return (
        np.vstack(X_rows),
        np.asarray(y_rows, dtype=float),
        [(c, np.asarray(col, dtype=float)) for c, col in zip(constraints, c_cols)],
        np.asarray(feas_rows, dtype=bool),
        seen_hashes,
    )


def suggest_next_batch(
    history: Sequence[Mapping[str, Any]],
    space: ParamSpace,
    objective_key: str,
    constraints: ConstraintsInput = None,
    *,
    minimize_obj: bool = True,
    batch_size: int = 4,
    seed: int = 0,
    ard: bool = True,
    xi: float = 0.01,
    n_candidates: int | None = None,
) -> list[dict[str, float]]:
    """Suggest ``batch_size`` next parameter sets via Constrained Expected Improvement + Kriging Believer.

    Falls back to maximin LHS when fewer than ``max(space.dim + 1, 3)`` valid
    observations exist in ``history``.
    """
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    specs = normalize_constraints(constraints)
    X, y, c_data, feas_mask, seen_hashes = _extract_history_arrays(
        history, space, objective_key, specs, minimize_obj
    )

    min_obs = max(space.dim + 1, 3)
    rng = np.random.default_rng(seed)

    if X.shape[0] < min_obs:
        # Cold-start with maximin LHS, skipping already-seen snapped points.
        pool = lhs_sample(space, max(batch_size * 4, batch_size + len(seen_hashes)), seed=seed)
        selected: list[dict[str, float]] = []
        for pt in pool:
            h = params_sha256(space, pt)
            if h not in seen_hashes:
                seen_hashes.add(h)
                selected.append(pt)
                if len(selected) == batch_size:
                    return selected
        while len(selected) < batch_size:
            selected.append(space.from_unit(rng.uniform(0.0, 1.0, size=space.dim)))
        return selected

    obj_gp = _ScalarGP(ard=ard, seed=seed).fit(X, y, optimize=True)
    c_gps: list[tuple[ConstraintSpec, _ScalarGP]] = []
    for ci, (spec, cy) in enumerate(c_data):
        cgp = _ScalarGP(ard=ard, seed=seed + 101 * (ci + 1)).fit(X, cy, optimize=True)
        c_gps.append((spec, cgp))

    has_feasible = bool(np.any(feas_mask))
    best_min = float(np.min(y[feas_mask])) if has_feasible else float(np.min(y))
    n_pool = int(n_candidates) if n_candidates is not None else max(512, 128 * space.dim)

    batch: list[dict[str, float]] = []
    cur_obj_gp = obj_gp
    cur_c_gps = list(c_gps)
    cur_X = X.copy()
    cur_best_min = best_min

    # Anchor points for local candidate perturbations (best feasible or lowest violation).
    if has_feasible:
        top_idx = np.argsort(np.where(feas_mask, y, float("inf")))[: min(4, int(np.sum(feas_mask)))]
    else:
        viol = np.zeros(X.shape[0], dtype=float)
        for spec, cy in c_data:
            for i in range(X.shape[0]):
                m = spec.margin(float(cy[i]), normalize=True)
                if m < 0.0:
                    viol[i] += abs(m)
        top_idx = np.argsort(viol)[: min(4, X.shape[0])]
    anchors = X[top_idx]

    for b in range(batch_size):
        # Mix global LHS candidates with local Gaussian perturbations around top points.
        u_global = rng.uniform(0.0, 1.0, size=(n_pool, space.dim))
        n_local = max(96, n_pool // 3)
        a_idx = rng.integers(0, anchors.shape[0], size=n_local)
        scales = rng.choice([0.02, 0.06, 0.15], size=(n_local, 1))
        u_local = np.clip(anchors[a_idx] + rng.normal(0.0, scales, size=(n_local, space.dim)), 0.0, 1.0)
        U_pool = np.vstack([u_global, u_local])

        def _acq(U: np.ndarray) -> np.ndarray:
            mu, sd = cur_obj_gp.predict(U, return_std=True)
            log_pof = _constraint_log_pof(U, cur_c_gps) if cur_c_gps else np.zeros(U.shape[0])
            if has_feasible:
                ei = _expected_improvement(mu, sd, cur_best_min, xi=xi)
                pof = np.exp(np.clip(log_pof, -700.0, 0.0))
                score = ei * pof
                # If EI*PoF underflows everywhere, fall back smoothly to log_pof + small EI tie-break.
                if float(np.max(score)) <= 1e-18:
                    return log_pof + 1e-6 * np.log1p(ei)
                return score
            # No feasible point yet: maximize log probability of feasibility.
            return log_pof

        scores = _acq(U_pool)
        # Two fast vectorized trust-region zoom rounds around the top-6 candidates.
        for zoom_scale in (0.04, 0.01):
            top_seeds = U_pool[np.argsort(scores)[-6:]]
            z_idx = rng.integers(0, top_seeds.shape[0], size=96)
            U_zoom = np.clip(top_seeds[z_idx] + rng.normal(0.0, zoom_scale, size=(96, space.dim)), 0.0, 1.0)
            s_zoom = _acq(U_zoom)
            U_pool = np.vstack([U_pool, U_zoom])
            scores = np.concatenate([scores, s_zoom])

        top_order = np.argsort(scores)[::-1]
        best_u = U_pool[int(top_order[0])].copy()
        best_score = float(scores[int(top_order[0])])

        # Pick highest-scoring snapped candidate not already evaluated or queued in this batch.
        chosen_u: np.ndarray | None = None
        chosen_pt: dict[str, float] | None = None

        cand_list = [best_u] + [U_pool[int(idx)] for idx in top_order[:64]]
        for cu in cand_list:
            pt = space.from_unit(cu, snap=True)
            h = params_sha256(space, pt)
            if h not in seen_hashes:
                chosen_u = space.to_unit(pt)
                chosen_pt = pt
                seen_hashes.add(h)
                break

        if chosen_pt is None:
            # Fallback: pick farthest unseen random candidate from current points.
            u_rand = rng.uniform(0.0, 1.0, size=(256, space.dim))
            dists = np.min(cdist(u_rand, cur_X), axis=1)
            for idx in np.argsort(dists)[::-1]:
                pt = space.from_unit(u_rand[int(idx)], snap=True)
                h = params_sha256(space, pt)
                if h not in seen_hashes:
                    chosen_u = space.to_unit(pt)
                    chosen_pt = pt
                    seen_hashes.add(h)
                    break
        if chosen_pt is None:
            chosen_u = best_u
            chosen_pt = space.from_unit(best_u, snap=True)

        assert chosen_u is not None
        batch.append(chosen_pt)

        # Kriging Believer fantasy update for subsequent members of this parallel batch.
        if b + 1 < batch_size:
            mu_obj = float(cur_obj_gp.predict(np.atleast_2d(chosen_u), return_std=False)[0])
            cur_obj_gp = cur_obj_gp.clone_with_fantasy(chosen_u, mu_obj)
            next_c_gps: list[tuple[ConstraintSpec, _ScalarGP]] = []
            for spec, cgp in cur_c_gps:
                mu_c = float(cgp.predict(np.atleast_2d(chosen_u), return_std=False)[0])
                next_c_gps.append((spec, cgp.clone_with_fantasy(chosen_u, mu_c)))
            cur_c_gps = next_c_gps
            cur_X = np.vstack([cur_X, chosen_u])

    return batch


# ---------------------------------------------------------------- Pareto front
def pareto_front(
    records: Sequence[Mapping[str, Any]],
    minimize_keys: Sequence[str],
    constraints: ConstraintsInput = None,
    *,
    maximize_keys: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Extract exact non-dominated feasible records (delegates core mask to ``robust_sizing.pareto_mask``)."""
    min_keys = list(minimize_keys)
    max_keys = list(maximize_keys)
    if not min_keys and not max_keys:
        raise ValueError("Specify at least one objective key in minimize_keys or maximize_keys")

    specs = normalize_constraints(constraints)
    feasible_records: list[dict[str, Any]] = []
    rows: list[list[float]] = []

    for rec in records:
        if rec.get("status", "ok") != "ok":
            continue
        metrics = rec["metrics"] if "metrics" in rec else rec
        if specs and not is_feasible(metrics, specs):
            continue
        vec: list[float] = []
        valid = True
        for k in min_keys:
            v = metrics.get(k)
            if v is None or not math.isfinite(float(v)):
                valid = False
                break
            vec.append(float(v))
        if not valid:
            continue
        for k in max_keys:
            v = metrics.get(k)
            if v is None or not math.isfinite(float(v)):
                valid = False
                break
            vec.append(-float(v))
        if not valid:
            continue
        feasible_records.append(dict(rec))
        rows.append(vec)

    if not feasible_records:
        return []

    mat = np.asarray(rows, dtype=float)
    mask = pareto_mask(mat)
    front = [(rows[i], feasible_records[i]) for i, keep in enumerate(mask) if keep]
    front.sort(key=lambda item: tuple(item[0]))
    return [rec for _, rec in front]


# ---------------------------------------------------------------- local polish
@dataclass(frozen=True)
class PolishResult:
    best_params: dict[str, float]
    best_metrics: dict[str, float]
    best_objective: float
    feasible: bool
    n_evals: int
    history: list[dict[str, Any]]


def polish_local(
    eval_fn: Callable[[dict[str, float]], Mapping[str, float]],
    x0: Mapping[str, float],
    space: ParamSpace,
    *,
    objective_key: str,
    constraints: ConstraintsInput = None,
    minimize_obj: bool = True,
    method: str = "Powell",
    max_evals: int = 40,
    penalty_weight: float = 1e4,
    campaign: "OptCampaign | None" = None,
) -> PolishResult:
    """Bounded Powell or Nelder-Mead local refinement around ``x0`` in unit-cube coordinates.

    Caches evaluations by snapped ``params_sha256`` (and logs into ``campaign``
    when provided) so repeated grid snaps incur zero redundant evaluations.
    """
    if method not in ("Powell", "Nelder-Mead"):
        raise ValueError(f"method must be 'Powell' or 'Nelder-Mead', got {method!r}")
    specs = normalize_constraints(constraints)

    cache: dict[str, tuple[dict[str, float], dict[str, float], bool, float]] = {}
    history: list[dict[str, Any]] = []
    eval_count = 0

    if campaign is not None:
        for tr in campaign.trials:
            if tr.status == "ok" and objective_key in tr.metrics and tr.metrics[objective_key] is not None:
                obj_v = float(tr.metrics[objective_key])
                cache[tr.input_sha256] = (tr.params, dict(tr.metrics), tr.feasible, obj_v)

    def _score_metrics(metrics: Mapping[str, float]) -> tuple[bool, float, float]:
        raw_obj = float(metrics[objective_key])
        signed_obj = raw_obj if minimize_obj else -raw_obj
        viol = 0.0
        for s in specs:
            m = s.margin(float(metrics[s.key]), normalize=True)
            if m < 0.0:
                viol += abs(m)
        feas = viol == 0.0
        penalized = signed_obj + penalty_weight * (viol + viol * viol)
        return feas, raw_obj, penalized

    def _eval_unit(u_vec: np.ndarray) -> float:
        nonlocal eval_count
        u_clipped = np.clip(np.asarray(u_vec, dtype=float), 0.0, 1.0)
        # Soft wall penalty outside [0, 1]^d for Nelder-Mead simplex excursions.
        out_of_bounds = float(np.sum(np.maximum(0.0, -u_vec) ** 2 + np.maximum(0.0, u_vec - 1.0) ** 2))
        params = space.from_unit(u_clipped, snap=True)
        h = params_sha256(space, params)

        if h in cache:
            _, metrics, _, _ = cache[h]
            _, _, pen = _score_metrics(metrics)
            return pen + 1e6 * out_of_bounds

        if eval_count >= max_evals:
            return 1e18

        eval_count += 1
        metrics = {k: float(v) for k, v in eval_fn(params).items()}
        feas, raw_obj, pen = _score_metrics(metrics)
        cache[h] = (params, metrics, feas, raw_obj)
        rec = {"params": params, "metrics": metrics, "feasible": feas, "input_sha256": h}
        history.append(rec)
        if campaign is not None:
            campaign.record(params, metrics, meta={"stage": "polish"})
        return pen + 1e6 * out_of_bounds

    u0 = space.to_unit(space.snap(x0))
    # Always evaluate starting point first.
    _eval_unit(u0)

    def _make_simplex(center: np.ndarray, step: float = 0.12) -> np.ndarray:
        d = space.dim
        simp = np.tile(center, (d + 1, 1))
        for j in range(d):
            delta = step if center[j] + step <= 1.0 else -step
            simp[j + 1, j] = float(np.clip(center[j] + delta, 0.0, 1.0))
        return simp

    bounds = [(0.0, 1.0)] * space.dim
    if method == "Powell":
        # When constraints exist, coordinate-aligned Powell can stall on oblique active
        # constraint kinks; follow with a bounded Nelder-Mead simplex pass using remaining budget.
        powell_budget = max(8, int(round(0.55 * max_evals))) if specs else max_evals
        res_p = minimize(
            _eval_unit,
            u0,
            method="Powell",
            bounds=bounds,
            options={"maxfev": powell_budget, "xtol": 1e-3, "ftol": 1e-4},
        )
        rem = max_evals - eval_count
        if specs and rem >= space.dim + 2:
            u_next = np.clip(np.asarray(res_p.x, dtype=float), 0.0, 1.0)
            minimize(
                _eval_unit,
                u_next,
                method="Nelder-Mead",
                options={"initial_simplex": _make_simplex(u_next, 0.10), "maxfev": rem, "xatol": 1e-3, "fatol": 1e-4},
            )
    else:
        minimize(
            _eval_unit,
            u0,
            method="Nelder-Mead",
            options={"initial_simplex": _make_simplex(u0, 0.12), "maxfev": max_evals, "xatol": 1e-3, "fatol": 1e-4},
        )

    # Select best feasible point from cache (or least-violating if none feasible).
    best_entry: tuple[dict[str, float], dict[str, float], bool, float] | None = None
    best_key: tuple[int, float] | None = None
    for params, metrics, feas, raw_obj in cache.values():
        _, _, pen = _score_metrics(metrics)
        signed = raw_obj if minimize_obj else -raw_obj
        key = (0 if feas else 1, signed if feas else pen)
        if best_key is None or key < best_key:
            best_key = key
            best_entry = (params, metrics, feas, raw_obj)

    assert best_entry is not None
    b_params, b_metrics, b_feas, b_obj = best_entry
    return PolishResult(
        best_params=b_params,
        best_metrics=b_metrics,
        best_objective=b_obj,
        feasible=b_feas,
        n_evals=eval_count,
        history=history,
    )


# ---------------------------------------------------------------- resumable OptCampaign
def _json_clean(obj: Any) -> Any:
    """Convert numpy scalars and replace non-finite floats with JSON null."""
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return v if math.isfinite(v) else None
    if isinstance(obj, (np.integer, int)) and not isinstance(obj, bool):
        return int(obj)
    if isinstance(obj, (np.bool_, bool)):
        return bool(obj)
    if isinstance(obj, Mapping):
        return {str(k): _json_clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_clean(v) for v in obj]
    return obj


@dataclass(frozen=True)
class TrialRecord:
    trial_id: int
    input_sha256: str
    params: dict[str, float]
    metrics: dict[str, float | None]
    feasible: bool
    status: str = "ok"
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trial_id": self.trial_id,
            "input_sha256": self.input_sha256,
            "params": self.params,
            "metrics": self.metrics,
            "feasible": self.feasible,
            "status": self.status,
            "meta": self.meta,
        }


@dataclass(frozen=True)
class OptResult:
    best_trial: TrialRecord | None
    n_trials: int
    n_feasible: int
    polish: PolishResult | None = None


class OptCampaign:
    """Crash-resumable JSONL optimization campaign with SHA-256 input-identity checks."""

    def __init__(
        self,
        campaign_dir: str | Path,
        space: ParamSpace,
        objective_key: str,
        constraints: ConstraintsInput = None,
        *,
        minimize_obj: bool = True,
        meta: Mapping[str, Any] | None = None,
    ) -> None:
        self.dir = Path(campaign_dir)
        self.space = space
        self.objective_key = str(objective_key)
        self.constraints = normalize_constraints(constraints)
        self.minimize_obj = bool(minimize_obj)
        self.dir.mkdir(parents=True, exist_ok=True)

        self.config_path = self.dir / "campaign.json"
        self.trials_path = self.dir / "trials.jsonl"

        self.config_sha256 = self._compute_config_sha256()
        self._trials: list[TrialRecord] = []
        self._by_hash: dict[str, TrialRecord] = {}

        if self.config_path.exists():
            saved = json.loads(self.config_path.read_text())
            if saved.get("config_sha256") != self.config_sha256:
                raise ValueError(
                    f"Campaign config mismatch in {self.config_path}: "
                    f"existing={saved.get('config_sha256')!r} != current={self.config_sha256!r}. "
                    "Use a new campaign directory when changing space, objective, or constraints."
                )
        else:
            payload = {
                "format": "serdes_flow.opt.campaign.v1",
                "config_sha256": self.config_sha256,
                "space_sha256": self.space.signature(),
                "space": self.space.to_list(),
                "objective_key": self.objective_key,
                "minimize_obj": self.minimize_obj,
                "constraints": [c.to_dict() for c in self.constraints],
                "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "meta": _json_clean(dict(meta or {})),
            }
            self.config_path.write_text(json.dumps(payload, indent=2) + "\n")

        self._load_trials()

    def _compute_config_sha256(self) -> str:
        payload = {
            "space_sha256": self.space.signature(),
            "objective_key": self.objective_key,
            "minimize_obj": self.minimize_obj,
            "constraints": [c.to_dict() for c in self.constraints],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

    def _load_trials(self) -> None:
        if not self.trials_path.exists():
            return
        lines = self.trials_path.read_text().splitlines()
        valid_lines: list[str] = []
        truncated_tail = False
        for idx, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                if idx == len(lines) - 1:
                    # Tolerate an incomplete final line left by an abrupt host reboot.
                    truncated_tail = True
                    break
                raise ValueError(f"Corrupted JSONL line {idx + 1} in {self.trials_path}")
            params = self.space.snap(row["params"])
            expected_hash = params_sha256(self.space, params)
            if row.get("input_sha256") != expected_hash:
                raise ValueError(
                    f"Input SHA-256 mismatch at trial {row.get('trial_id')} in {self.trials_path}"
                )
            rec = TrialRecord(
                trial_id=int(row["trial_id"]),
                input_sha256=expected_hash,
                params=params,
                metrics=dict(row.get("metrics", {})),
                feasible=bool(row.get("feasible", False)),
                status=str(row.get("status", "ok")),
                meta=dict(row.get("meta", {})),
            )
            self._trials.append(rec)
            self._by_hash[rec.input_sha256] = rec
            valid_lines.append(line)
        if truncated_tail:
            self.trials_path.write_text(("\n".join(valid_lines) + "\n") if valid_lines else "")

    @property
    def trials(self) -> list[TrialRecord]:
        return list(self._trials)

    @property
    def ok_trials(self) -> list[TrialRecord]:
        return [t for t in self._trials if t.status == "ok"]

    @property
    def feasible_trials(self) -> list[TrialRecord]:
        return [t for t in self._trials if t.status == "ok" and t.feasible]

    def has_params(self, params: Mapping[str, float]) -> bool:
        return params_sha256(self.space, params) in self._by_hash

    def get_trial(self, params: Mapping[str, float]) -> TrialRecord | None:
        return self._by_hash.get(params_sha256(self.space, params))

    def record(
        self,
        params: Mapping[str, float],
        metrics: Mapping[str, Any],
        *,
        status: str = "ok",
        meta: Mapping[str, Any] | None = None,
        allow_duplicate: bool = False,
    ) -> TrialRecord:
        """Append a trial to ``trials.jsonl``; returns existing record on duplicate hash."""
        snapped = self.space.snap(params)
        h = params_sha256(self.space, snapped)
        if not allow_duplicate and h in self._by_hash:
            return self._by_hash[h]

        clean_metrics = _json_clean(dict(metrics))
        feas = (status == "ok") and is_feasible(clean_metrics, self.constraints)
        rec = TrialRecord(
            trial_id=len(self._trials),
            input_sha256=h,
            params=snapped,
            metrics=clean_metrics,
            feasible=feas,
            status=status,
            meta=_json_clean(dict(meta or {})),
        )
        with self.trials_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec.to_dict(), sort_keys=True) + "\n")
            fh.flush()
        self._trials.append(rec)
        self._by_hash[h] = rec
        return rec

    def best(self, *, feasible_only: bool = True) -> TrialRecord | None:
        """Return best feasible trial (or least-violating ok trial when ``feasible_only=False``)."""
        cands = self.feasible_trials
        if cands:
            return min(
                cands,
                key=lambda t: (
                    float(t.metrics[self.objective_key])
                    if self.minimize_obj
                    else -float(t.metrics[self.objective_key])
                ),
            )
        if feasible_only:
            return None
        ok = [
            t for t in self.ok_trials
            if t.metrics.get(self.objective_key) is not None
        ]
        if not ok:
            return None

        def _viol_key(t: TrialRecord) -> tuple[float, float]:
            viol = 0.0
            for c in self.constraints:
                v = t.metrics.get(c.key)
                m = -1e6 if v is None else c.margin(float(v), normalize=True)
                if m < 0.0:
                    viol += abs(m)
            obj = float(t.metrics[self.objective_key])
            return (viol, obj if self.minimize_obj else -obj)

        return min(ok, key=_viol_key)

    def suggest(
        self,
        *,
        batch_size: int = 4,
        init_points: int | None = None,
        seed: int = 0,
        ard: bool = True,
        xi: float = 0.01,
    ) -> list[dict[str, float]]:
        """Suggest the next parallel batch (LHS during init, then cEI + Kriging Believer)."""
        n_init = max(2 * self.space.dim, batch_size) if init_points is None else int(init_points)
        if len(self._trials) < n_init:
            rem = min(batch_size, n_init - len(self._trials))
            pool = lhs_sample(self.space, n_init + 2 * batch_size, seed=seed)
            out: list[dict[str, float]] = []
            local_seen = set(self._by_hash.keys())
            for pt in pool:
                h = params_sha256(self.space, pt)
                if h not in local_seen:
                    local_seen.add(h)
                    out.append(pt)
                    if len(out) == rem:
                        return out
            return out

        history = [t.to_dict() for t in self._trials]
        return suggest_next_batch(
            history,
            self.space,
            self.objective_key,
            self.constraints,
            minimize_obj=self.minimize_obj,
            batch_size=batch_size,
            seed=seed + 31 * len(self._trials),
            ard=ard,
            xi=xi,
        )

    def run(
        self,
        eval_fn: Callable[[dict[str, float]], Mapping[str, Any]] | None = None,
        *,
        eval_batch_fn: Callable[[list[dict[str, float]]], Sequence[Mapping[str, Any]]] | None = None,
        n_trials: int = 24,
        batch_size: int = 4,
        init_points: int | None = None,
        seed: int = 0,
        ard: bool = True,
        xi: float = 0.01,
        polish: bool = False,
        polish_method: str = "Powell",
        polish_evals: int = 30,
    ) -> OptResult:
        """Run or resume Bayesian optimization until ``n_trials`` total trials are recorded."""
        if (eval_fn is None) == (eval_batch_fn is None):
            raise ValueError("Provide exactly one of eval_fn or eval_batch_fn")

        while len(self._trials) < n_trials:
            step_batch = min(batch_size, n_trials - len(self._trials))
            candidates = self.suggest(
                batch_size=step_batch,
                init_points=init_points,
                seed=seed,
                ard=ard,
                xi=xi,
            )
            pending = [pt for pt in candidates if not self.has_params(pt)]
            if not pending:
                break

            t0 = time.monotonic()
            if eval_batch_fn is not None:
                results = list(eval_batch_fn(pending))
                if len(results) != len(pending):
                    raise ValueError(f"eval_batch_fn returned {len(results)} results for {len(pending)} candidates")
                elapsed = time.monotonic() - t0
                for pt, metrics in zip(pending, results):
                    self.record(pt, metrics, meta={"stage": "bo", "batch_elapsed_s": round(elapsed, 4)})
            else:
                assert eval_fn is not None
                for pt in pending:
                    ts = time.monotonic()
                    metrics = eval_fn(pt)
                    self.record(pt, metrics, meta={"stage": "bo", "elapsed_s": round(time.monotonic() - ts, 4)})

        polish_res: PolishResult | None = None
        if polish:
            start = self.best(feasible_only=False)
            if start is not None:
                def _single_eval(pt: dict[str, float]) -> Mapping[str, float]:
                    if eval_fn is not None:
                        return eval_fn(pt)
                    assert eval_batch_fn is not None
                    return eval_batch_fn([pt])[0]

                polish_res = polish_local(
                    _single_eval,
                    start.params,
                    self.space,
                    objective_key=self.objective_key,
                    constraints=self.constraints,
                    minimize_obj=self.minimize_obj,
                    method=polish_method,
                    max_evals=polish_evals,
                    campaign=self,
                )

        return OptResult(
            best_trial=self.best(feasible_only=True) or self.best(feasible_only=False),
            n_trials=len(self._trials),
            n_feasible=len(self.feasible_trials),
            polish=polish_res,
        )
