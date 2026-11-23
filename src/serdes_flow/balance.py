"""Structural timing balance analysis with element constraint models.

The question this answers is structural: given *which* elements sit on each
path, can the relations between the paths hold over the whole PVT grid, and how
much may each kind of element degrade before one breaks?  It does not size or
simulate circuits.

* An element model is a constraint, not a sized cell: delay = TT delay x process
  factor x (1 + alpha*v + beta*t), v = (VDD - 1.8)/0.15, t = (T - 22.5)/62.5.
  Models are fitted from measurements (``fit_element``) or written as targets,
  and kept in a JSON library with their provenance (``load_elements``).
* A structure is a set of named paths.  A path is a list of items: ``Inst`` (an
  element instance; the same id on two paths is one shared instance), ``Fixed``
  (an exact offset such as a VCO phase step) and ``Knob`` (a centring choice).
* Relations between paths: ``Skew`` (relative position inside a periodic
  window), ``Sample`` (a data path sampled by a clock path, setup/hold inside a
  period) and ``Budget`` (a path sum below a limit, e.g. a counter loop).
* Knobs only move nominal offsets.  ``centre`` searches them path by path in
  the structure's order, then refines on the worst margin.  The spread over PVT
  comes from the composition difference between paths.

Outputs per structure: worst margin over the grid, per-process bands (one chip
has one process; its band is the V/T movement), ``lambda_max`` (how far every
element's PVT variation may grow with re-centring), and ``limits``: per element
type, how far its variation and its delay may grow and how much local mismatch
the structure tolerates.  The delay limit is the shrink budget of that element.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .corners import PROCESS, Condition, grid45

GRID = grid45()
PROC_IDX = np.array([PROCESS.index(c.process) for c in GRID])
V = np.array([(c.supply - 1.8) / 0.15 for c in GRID])
T = np.array([(c.temp - 22.5) / 62.5 for c in GRID])


# ---------------------------------------------------------------- elements
@dataclass(frozen=True)
class ElementModel:
    name: str
    tt: float                       # ps at TT / 1.8 V / ~27 C
    factors: dict                   # process -> factor (tt = 1)
    alpha: float = 0.0              # per unit v
    beta: float = 0.0               # per unit t
    track: str | None = None        # designed to track another element type (replica)
    note: str = ""

    def delays(self, lam: float = 1.0, size: float = 1.0) -> np.ndarray:
        """Delay over the 45-point grid; lam scales the PVT variation, size the delay."""
        f = np.array([self.factors[p] for p in PROCESS])[PROC_IDX]
        return self.tt * size * (1 + lam * (f - 1)) * (1 + lam * (self.alpha * V + self.beta * T))


def load_elements(path: str | Path) -> dict[str, ElementModel]:
    data = json.loads(Path(path).read_text())
    return {k: ElementModel(**{f: v for f, v in e.items() if f in ElementModel.__dataclass_fields__})
            for k, e in data["elements"].items()}


def fit_element(samples: dict[str, float], name: str, note: str = "") -> ElementModel:
    """Fit log(delay) = log(m_process) + alpha*v + beta*t to delays (ps) at condition tags."""
    rows, y = [], []
    for tag, d in samples.items():
        c = Condition.parse(tag)
        rows.append([1.0 if c.process == p else 0.0 for p in PROCESS] + [(c.supply - 1.8) / 0.15, (c.temp - 22.5) / 62.5])
        y.append(np.log(d))
    x, *_ = np.linalg.lstsq(np.array(rows), np.array(y), rcond=None)
    m = np.exp(x[:len(PROCESS)])
    seen = {Condition.parse(t).process for t in samples}
    tt = m[PROCESS.index("tt")]
    return ElementModel(name=name, tt=float(tt), factors={p: float(m[i] / tt) if p in seen else 1.0 for i, p in enumerate(PROCESS)},
                        alpha=float(x[-2]), beta=float(x[-1]), note=note)


def fit_residual(model: ElementModel, samples: dict[str, float]) -> float:
    pred = {t: model.delays()[GRID.index(Condition.parse(t))] for t in samples}
    return float(max(abs(samples[t] - pred[t]) for t in samples))


# ---------------------------------------------------------------- structures
@dataclass(frozen=True)
class Inst:
    type: str
    id: str


@dataclass(frozen=True)
class Fixed:
    ps: float
    tap: str = ""                   # source label; two paths from different taps get tap_error


@dataclass(frozen=True)
class Knob:
    name: str


@dataclass(frozen=True)
class KnobSpec:
    kind: str                       # "fixed": values x unit ps, exact | "delay": ps of `type` behaviour | "stages": count of `type`
    values: tuple = ()
    unit: float = 1.0
    type: str = ""
    tap: bool = False               # a "fixed" knob that selects a source tap (adds tap_error between different taps)

    def cost(self, v) -> float:
        return v * 0.02 if self.kind == "delay" else v * 1.0 if self.kind == "stages" else 0.0


@dataclass(frozen=True)
class Skew:
    """pos(b) - pos(a) - target, folded on period, must stay inside +-half."""
    a: str
    b: str
    target: float
    period: float
    half: float
    owner: str
    label: str = ""


@dataclass(frozen=True)
class Sample:
    """Data transitions (data path + k*period) must sit in [hold, period - setup] after a
    sampling edge (clock path + offset)."""
    data: str
    clock: str
    period: float
    setup: float
    hold: float
    owner: str
    offset: float = 0.0
    label: str = ""


@dataclass(frozen=True)
class Budget:
    path: str
    limit: float
    owner: str
    label: str = ""


@dataclass
class Structure:
    key: str
    name: str
    paths: dict
    knobs: dict
    relations: list
    order: list                     # path names in centring order
    meta: dict = field(default_factory=dict)


@dataclass
class Params:
    mismatch: dict = field(default_factory=lambda: {"*": 0.03})   # fraction of TT delay per non-shared instance
    tracking: dict = field(default_factory=dict)                   # type -> fraction of its target's variation it misses
    tap_error: float = 2.0                                         # ps between different source taps
    lam: float = 1.0
    lam_by: dict = field(default_factory=dict)                     # type -> extra multiplier on its PVT variation
    size_by: dict = field(default_factory=dict)                    # type -> multiplier on its delay

    def mis(self, t):
        return self.mismatch.get(t, self.mismatch.get("*", 0.0))


# ---------------------------------------------------------------- evaluation
class _Ctx:
    def __init__(self, elements, params):
        self.E, self.P = elements, params
        self.cache = {}

    def d(self, t):
        if t not in self.cache:
            e = self.E[t]
            lam = self.P.lam * self.P.lam_by.get(e.track or t, 1.0)
            size = self.P.size_by.get(e.track or t, 1.0)
            if e.track:
                q = self.E[e.track]
                dq = q.delays(lam, size)
                self.cache[t] = dq - self.P.tracking.get(t, 0.0) * (dq - q.tt * size)
            else:
                self.cache[t] = e.delays(lam, size)
        return self.cache[t]


def _path_delay(path, S, kv, ctx):
    x = np.zeros(len(GRID))
    for it in path:
        if isinstance(it, Fixed):
            x = x + it.ps
        elif isinstance(it, Inst):
            x = x + ctx.d(it.type)
        else:
            k, v = S.knobs[it.name], kv.get(it.name, 0)
            if k.kind == "fixed":
                x = x + v * k.unit
            elif k.kind == "delay":
                x = x + v * ctx.d(k.type) / ctx.E[k.type].tt
            else:
                x = x + v * ctx.d(k.type)
    return x


def _instances(path, S, kv):
    out = {}
    for it in path:
        if isinstance(it, Inst):
            out[it.id] = it.type
        elif isinstance(it, Knob):
            k, v = S.knobs[it.name], kv.get(it.name, 0)
            if k.kind == "stages":
                out.update({f"{it.name}#{i}": k.type for i in range(v)})
            elif k.kind == "delay" and v:
                out[it.name] = k.type
    return out


def _tap(path, S, kv):
    for it in path:
        if isinstance(it, Fixed):
            return it.tap
        if isinstance(it, Knob) and S.knobs[it.name].tap:
            return f"{it.name}={kv.get(it.name, 0)}"
    return ""


def _mismatch(pa, pb, S, kv, ctx):
    A, B = _instances(pa, S, kv), _instances(pb, S, kv)
    m = sum(ctx.P.mis(t) * ctx.E[t].tt for i, t in A.items() if i not in B)
    m += sum(ctx.P.mis(t) * ctx.E[t].tt for i, t in B.items() if i not in A)
    if _tap(pa, S, kv) != _tap(pb, S, kv):
        m += ctx.P.tap_error
    return m


def _wrap(x, p):
    return (x + p / 2) % p - p / 2


@dataclass
class RelationResult:
    relation: object
    margin: float                   # ps, worst over the grid, mismatch included
    values: np.ndarray | None = None  # per grid point: skew error (Skew), phase (Sample), sum (Budget)
    mismatch: float = 0.0

    def band(self):
        """Per process (lo, hi) of the per-point values: one chip's V/T movement."""
        if self.values is None:
            return {}
        return {p: (float(self.values[PROC_IDX == i].min()), float(self.values[PROC_IDX == i].max()))
                for i, p in enumerate(PROCESS)}


def evaluate(S: Structure, elements, params: Params, kv: dict):
    ctx = _Ctx(elements, params)
    pos = {name: _path_delay(p, S, kv, ctx) for name, p in S.paths.items()}
    out = []
    for r in S.relations:
        if isinstance(r, Skew):
            mis = _mismatch(S.paths[r.a], S.paths[r.b], S, kv, ctx)
            e = _wrap(pos[r.b] - pos[r.a] - r.target, r.period)
            med = np.median(e)
            e = med + _wrap(e - med, r.period)
            out.append(RelationResult(r, float(r.half - np.abs(e).max() - mis), e, mis))
        elif isinstance(r, Sample):
            mis = _mismatch(S.paths[r.data], S.paths[r.clock], S, kv, ctx)
            ph = (pos[r.data] - pos[r.clock] - r.offset) % r.period
            m = np.minimum(ph - r.hold, r.period - r.setup - ph)
            out.append(RelationResult(r, float(m.min() - mis), ph, mis))
        else:
            out.append(RelationResult(r, float(r.limit - pos[r.path].max()), pos[r.path]))
    return out, pos


def worst(results):
    return min(x.margin for x in results)


# ---------------------------------------------------------------- centring
def _owned_knobs(S):
    """Knobs in the order their owner path first uses them (including relation side paths)."""
    seen, plan = set(), []
    for owner in S.order:
        mine = []
        side = [S.paths[owner]] + [S.paths[r.clock] for r in S.relations if isinstance(r, Sample) and r.owner == owner]
        for p in side:
            for it in p:
                if isinstance(it, Knob) and it.name not in seen:
                    seen.add(it.name)
                    mine.append(it.name)
        plan.append((owner, mine))
    return plan


def centre(S: Structure, elements, params: Params, cap: float = 40.0) -> dict:
    kv = {k: (spec.values[0] if spec.values else 0) for k, spec in S.knobs.items()}
    for owner, mine in _owned_knobs(S):
        if not mine:
            continue
        best = None
        for combo in itertools.product(*(S.knobs[k].values for k in mine)):
            kv.update(zip(mine, combo))
            res, _ = evaluate(S, elements, params, kv)
            ms = [x.margin for x in res if x.relation.owner == owner]
            m = min(min(ms) if ms else 0.0, cap)
            cost = sum(S.knobs[k].cost(v) for k, v in zip(mine, combo))
            if best is None or m > best[0] + 1 or (m > best[0] - 1 and cost < best[2]):
                best = (max(m, best[0]) if best else m, combo, cost)
        kv.update(zip(mine, best[1]))
    cur = worst(evaluate(S, elements, params, kv)[0])
    for _ in range(3):
        changed = False
        for k, spec in S.knobs.items():
            keep = kv[k]
            for v in spec.values:
                if v == keep:
                    continue
                kv[k] = v
                w = worst(evaluate(S, elements, params, kv)[0])
                if w > cur + 0.5:
                    cur, keep, changed = w, v, True
            kv[k] = keep
        if not changed:
            break
    return kv


# ---------------------------------------------------------------- robustness and limits
def lambda_max(S, elements, params: Params, hi=4.0, steps=8) -> float:
    def ok(lam):
        P = replace(params, lam=lam)
        return worst(evaluate(S, elements, P, centre(S, elements, P))[0]) >= 0
    if not ok(0.0):
        return 0.0
    if ok(hi):
        return hi
    lo = 0.0
    for _ in range(steps):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if ok(m) else (lo, m)
    return lo


def _limit(f, hi, steps=10):
    """Largest x >= 1 with f(x) true (reference x = 1); if f(1) fails, largest x in [0, 1) that passes."""
    if f(1.0):
        if f(hi):
            return hi
        lo = 1.0
        for _ in range(steps):
            m = (lo + hi) / 2
            lo, hi = (m, hi) if f(m) else (lo, m)
        return lo
    for x in np.arange(0.9, -1e-9, -0.1):
        if f(float(x)):
            return float(x)
    return None


def element_types(S):
    ts = set()
    for p in S.paths.values():
        for it in p:
            if isinstance(it, Inst):
                ts.add(it.type)
    for k in S.knobs.values():
        if k.type:
            ts.add(k.type)
    return ts


def limits(S, elements, params: Params, kv, hi=8.0):
    """Per element type (knobs kept): variation multiplier, delay multiplier (shrink budget);
    and the mismatch multiplier on params.mismatch."""
    types = sorted({elements[t].track or t for t in element_types(S)})
    ok = lambda P: worst(evaluate(S, elements, P, kv)[0]) >= 0
    var = {t: _limit(lambda x, t=t: ok(replace(params, lam_by={**params.lam_by, t: x})), hi) for t in types}
    size = {t: _limit(lambda x, t=t: ok(replace(params, size_by={**params.size_by, t: x})), hi) for t in types}
    mis = _limit(lambda x: ok(replace(params, mismatch={k: v * x for k, v in params.mismatch.items()})), 10.0)
    return dict(variation=var, delay=size, mismatch=mis)


@dataclass
class Report:
    structure: Structure
    knobs: dict
    results: list
    worst: float
    lambda_max: float
    limits: dict


def analyse(S: Structure, elements, params: Params, with_limits=True) -> Report:
    kv = centre(S, elements, params)
    res, _ = evaluate(S, elements, params, kv)
    return Report(S, kv, res, worst(res), lambda_max(S, elements, params),
                  limits(S, elements, params, kv) if with_limits else {})
