"""Testbench rendering, ngspice batch runs and waveform loading.

A run directory holds exactly what was simulated: tb.cir, any copied include
files, .spiceinit, simulator.log, the wrdata output and execution.json.  Run
directories are created fresh and never overwritten.
"""
import gzip
import hashlib
import json
import re
import shutil
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import project

_PLACEHOLDER = re.compile(r"@([A-Z0-9_]+)@")
_LOG_FAILURES = ("error", "aborted", "timestep too small", "singular matrix")


def render(template: str | Path, **values) -> str:
    """Replace @KEY@ placeholders; every placeholder must be supplied."""
    text = Path(template).read_text() if isinstance(template, Path) else template
    missing = set(_PLACEHOLDER.findall(text)) - set(values)
    if missing:
        raise KeyError(f"unfilled placeholders: {sorted(missing)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], text)


def corner_values(cond) -> dict:
    """Standard placeholder values for a PVT condition."""
    return dict(MODEL_LIBRARY=project.model_library(), CORNER=cond.process,
                SUPPLY=cond.supply, TEMP_C=cond.temp, PROJECT_ROOT=project.ROOT)


@dataclass
class Execution:
    run_dir: Path
    exit_code: int | None
    elapsed_s: float
    log_failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.log_failures


def run(deck: str, run_dir: Path, *, files: dict[str, Path] | None = None,
        timeout_s: float = 3600, meta: dict | None = None) -> Execution:
    """Run one ngspice batch job in a new directory.

    `files` maps names inside the run directory to files copied in (stimuli,
    PWL tables).  `meta` is stored in execution.json alongside tool versions.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / ".spiceinit").write_text("set ngbehavior=hsa\n")
    for name, src in (files or {}).items():
        shutil.copy2(src, run_dir / name)
    (run_dir / "tb.cir").write_text(deck)
    start = time.time()
    try:
        proc = subprocess.run([project.ngspice(), "-b", "-o", "simulator.log", "tb.cir"], cwd=run_dir,
                              stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=timeout_s)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        exit_code = None
    log = (run_dir / "simulator.log").read_text(errors="replace") if (run_dir / "simulator.log").exists() else ""
    failures = [l for l in log.splitlines() if any(k in l.lower() for k in _LOG_FAILURES)]
    ex = Execution(run_dir, exit_code, time.time() - start, failures)
    record = dict(
        exit_code=exit_code, elapsed_s=ex.elapsed_s, log_failures=failures, timed_out=exit_code is None,
        ngspice=project.ngspice(), model_library=str(project.model_library()),
        pdk_installation_id=project.pdk_installation_id(), git_revision=project.git_revision(),
        deck_sha256=hashlib.sha256(deck.encode()).hexdigest(),
        inputs_sha256={n: hashlib.sha256((run_dir / n).read_bytes()).hexdigest() for n in (files or {})},
        **(meta or {}),
    )
    (run_dir / "execution.json").write_text(json.dumps(record, indent=2, default=str))
    return ex


def run_many(jobs, *, workers: int = 4):
    """Run (deck, run_dir, kwargs) jobs with at most `workers` concurrent ngspice."""
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run, deck, run_dir, **kw) for deck, run_dir, kw in jobs]
        return [f.result() for f in futures]


class Waves:
    """wrdata output (single time scale, vector names in the header)."""

    def __init__(self, path: Path):
        path = Path(path)
        if not path.exists() and Path(str(path) + ".gz").exists():
            path = Path(str(path) + ".gz")
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt") as f:
            self.names = f.readline().split()
        self.data = np.loadtxt(path, skiprows=1)
        if self.data.ndim != 2 or self.data.shape[1] != len(self.names):
            raise ValueError(f"{path}: header has {len(self.names)} names, data {self.data.shape}")
        if not (np.all(np.isfinite(self.data)) and np.all(np.diff(self.data[:, 0]) > 0)):
            raise ValueError(f"{path}: non-finite values or non-increasing time")
        self.path = path
        self._col = {n: i for i, n in enumerate(self.names)}

    @property
    def t(self) -> np.ndarray:
        return self.data[:, 0]

    def __getitem__(self, name: str) -> np.ndarray:
        return self.data[:, self._col[name]]

    def __contains__(self, name: str) -> bool:
        return name in self._col
