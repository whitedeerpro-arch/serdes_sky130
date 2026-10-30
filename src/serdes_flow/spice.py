"""Testbench rendering, ngspice batch runs and waveform loading.

A run directory holds exactly what was simulated: tb.cir, any copied include
files, .spiceinit, simulator.log, the waveform output and execution.json.  Run
directories are created fresh and never overwritten.

Waveform output is either wrdata text (`waveforms.tsv`) or, after
`binary_output`, an ngspice binary raw file (`waveforms.raw`): full double
precision, about half the size, and it loads without text parsing.  `Waves`
reads both.  `skip_output_before` stops ngspice from storing the start-up
part of a transient; the circuit still evolves from t = 0.
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
_WRDATA = re.compile(r"^(\s*)wrdata\s+(\S+?)\.tsv\s+(.+)$", re.M)
_TRAN_ZERO_START = re.compile(r"^(\s*tran\s+\S+\s+\S+\s+)0(?=\s)", re.M)


def render(template: str | Path, **values) -> str:
    """Replace @KEY@ placeholders; every placeholder must be supplied."""
    text = Path(template).read_text() if isinstance(template, Path) else template
    missing = set(_PLACEHOLDER.findall(text)) - set(values)
    if missing:
        raise KeyError(f"unfilled placeholders: {sorted(missing)}")
    return _PLACEHOLDER.sub(lambda m: str(values[m[1]]) if m[1] in values else m[0], text)


def binary_output(deck: str) -> str:
    """Turn every `wrdata name.tsv vecs` into a binary raw `write name.raw vecs`."""
    out, n = _WRDATA.subn(lambda m: f"{m[1]}set filetype=binary\n{m[1]}write {m[2]}.raw {m[3]}", deck)
    if not n:
        raise ValueError("deck has no wrdata line to convert")
    return out


def skip_output_before(deck: str, tstart) -> str:
    """Set tstart of `tran tstep tstop 0 tmax`: no output points before tstart.

    The solver still runs from t = 0 with the same tmax, so later points are
    unaffected; only the stored history shrinks.  Analyses that window data
    (training, power averages) must start after tstart.
    """
    out, n = _TRAN_ZERO_START.subn(lambda m: f"{m[1]}{tstart}", deck)
    if n != 1:
        raise ValueError(f"expected one 'tran tstep tstop 0 ...' line, found {n}")
    return out


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


def read_raw(path: Path):
    """First plot of an ngspice raw file (binary, real data): (names, array)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as f:
        header, names = {}, []
        while True:
            line = f.readline()
            if not line:
                raise ValueError(f"{path}: no Binary: section")
            text = line.decode("latin-1").rstrip("\n")
            if text.startswith("Variables:"):
                for _ in range(int(header["No. Variables"])):
                    names.append(f.readline().decode("latin-1").split()[1])
            elif text.startswith("Binary:"):
                payload = f.read()
                break
            elif text.startswith("Values:"):
                raise ValueError(f"{path}: ASCII raw not supported; use filetype=binary")
            else:
                key, _, value = text.partition(":")
                header[key.strip()] = value.strip()
    if "complex" in header.get("Flags", ""):
        raise ValueError(f"{path}: complex raw data not supported")
    nvar = len(names)
    values = np.frombuffer(payload, dtype="<f8")
    # A raw file streamed through a FIFO reports 0 points; use the payload length.
    npts = int(header.get("No. Points", 0)) or len(values) // nvar
    return names, values[: npts * nvar].reshape(npts, nvar).copy()


def _resolve(path: Path) -> Path:
    """The given path, its .gz, or the binary .raw (optionally .gz) next to it."""
    raw = path.with_suffix(".raw")
    for p in (path, Path(str(path) + ".gz"), raw, Path(str(raw) + ".gz")):
        if p.exists():
            return p
    raise FileNotFoundError(path)


class Waves:
    """Waveform output, single time scale: binary raw or wrdata text with vector names."""

    def __init__(self, path: Path):
        path = _resolve(Path(path))
        if ".raw" in path.suffixes:
            self.names, self.data = read_raw(path)
        else:
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

    def _column(self, name: str) -> int:
        # Binary `write` labels a plain copy of a node voltage (let x=v(n)) and
        # @m...[param] vectors as v(x); wrdata keeps x.  Accept either spelling.
        for key in (name, f"v({name})", name[2:-1] if name.startswith("v(") and name.endswith(")") else None):
            if key in self._col:
                return self._col[key]
        raise KeyError(name)

    def __getitem__(self, name: str) -> np.ndarray:
        return self.data[:, self._column(name)]

    def __contains__(self, name: str) -> bool:
        try:
            self._column(name)
            return True
        except KeyError:
            return False
