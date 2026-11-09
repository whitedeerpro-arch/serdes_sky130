"""Monte Carlo with the SKY130 statistical sections (ngspice agauss + mc_source).

    text = mc.deck(netlist, samples=200, seed=1, analysis="op", lets={"vth1": "@m.xm1.msky130...[vth]"})
    ex = spice.run(text, run_dir)
    rows = mc.read(run_dir)            # one dict per sample, keys = the lets

`netlist` is a complete deck without a .control block (and without .end).  Library section:
'<corner>_mm' varies local mismatch only (mc_mm_switch = 1); 'mc' varies global process
(mc_pr_switch = 1).  Per sample: the analysis, the `let` expressions, one `wrdata` row appended to
mc.tsv, then `mc_source`, which re-sources the circuit and re-evaluates every agauss (a new sample)
without reloading the model files (~0.2 s per sample for a few tens of devices; the first model
load is ~15 s).  setseed makes a run reproducible: the agauss values drawn while the netlist is read
come before setseed (not reproducible from run to run), so the deck discards them with one
mc_source right after setseed; every recorded sample k of a run is then fixed by (seed, k), the
basis for paired comparisons (the same mismatch at another temperature / supply).  Runs before
2026-11-03 recorded that load-time draw as sample 0 of every chunk.  The loop counter lives in the const plot and every
analysis plot is destroyed after its row is written, so long runs do not accumulate plots.
Memory: every `mc_source` keeps some memory (bench-dependent: the ac_trim + PDK-R 54 ns pilot grew
115-144 MB per sample); spice.run caps an ngspice at 3 GB, so long runs are split with `chunks` into separate
processes (seed per chunk), which also lets them run in parallel; `read_all` concatenates them.
`analysis` may be several lines (e.g. a `tran` followed by `meas tran ...` statements); every `let`
must reduce to a scalar per sample (op values, meas results).  A `let` whose source is missing in a
sample (a meas that found no crossing) falls back to the sentinel defined in the const plot before the
loop and reads back as NaN; ngspice still logs the failed meas. Use run_many/complete to check count,
exit status and t_end, then judge missing measurements separately from electrical acceptance.
"""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import warnings

import numpy as np

MC_FILE = "mc.tsv"


SENTINEL = -1e30


def deck(netlist: str, samples: int, *, seed: int = 1, analysis: str = "op", lets: dict[str, str],
         setup: str = "", t_end: float | None = None, profile: bool = False) -> str:
    """`setup`: control lines run once before the sample loop (const plot), e.g. `compose` vectors that
    the analysis indexes with mc_k (per-sample settings: `let x = v[mc_k]` then `alter ... dc=$&x`;
    alters belong in the analysis, because mc_source re-reads the circuit)."""
    if samples < 1 or not lets:
        raise ValueError("samples and lets must be nonempty")
    if any(k.startswith("mc_") for k in lets):
        raise ValueError("mc_ names are reserved")
    lets = dict(lets)
    if t_end is not None:
        if t_end <= 0:
            raise ValueError("t_end must be positive")
        lets["mc_t_end"] = "time[length(time)-1]"
    names = list(lets)
    contract = dict(samples=samples, columns=names, t_end=t_end)
    body = [f"  let {k} = {v}" for k, v in lets.items()]
    ana = ["  " + l.strip() for l in analysis.strip().splitlines()]
    ctl = ["", "* mc_contract " + json.dumps(contract, sort_keys=True), ".control", "set num_threads=1", "set wr_vecnames", "set wr_singlescale", "set appendwrite",
           f"setseed {int(seed)}", "mc_source"] + [f"let {k} = {SENTINEL}" for k in names] + [
           l.strip() for l in setup.strip().splitlines()] + ["let mc_k = 0", f"dowhile mc_k < {int(samples)}"] + ana + body + [
           f"  wrdata {MC_FILE} " + " ".join(names)] + (["  rusage all"] if profile else []) + [
           "  destroy all", "  setplot const", "  let mc_k = mc_k + 1",
           f"  if mc_k < {int(samples)}", "    mc_source", "  end", "end", "quit", ".endc", ".end", ""]
    return netlist.rstrip() + "\n" + "\n".join(ctl)


def read(run_dir) -> list[dict]:
    """Rows of mc.tsv (a header line precedes every appended row)."""
    rows, names = [], None
    for line in (Path(run_dir) / MC_FILE).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            vals = [float(x) for x in parts]
        except ValueError:
            if names is not None and parts != names:
                raise ValueError(f"{run_dir}: changed or malformed MC header")
            names = parts
            continue
        if names is None or len(vals) != len(names) or len(set(names)) != len(names):
            raise ValueError(f"{run_dir}: incomplete MC row or invalid header")
        rows.append({k: (float("nan") if v <= SENTINEL / 10 else v) for k, v in zip(names, vals)})
    return rows


def column(rows, key):
    return np.array([r[key] for r in rows])


def chunks(samples: int, seed: int, per: int = 50):
    """[(chunk index, chunk seed, chunk samples)] covering `samples`; chunk seeds are seed * 1000 + index."""
    if samples < 1 or per < 1:
        raise ValueError("samples and per must be positive")
    out, k = [], 0
    while samples > 0:
        n = min(per, samples)
        out.append((k, seed * 1000 + k, n))
        samples -= n
        k += 1
    return out


def read_all(run_dirs) -> list[dict]:
    rows = []
    for d in run_dirs:
        if (Path(d) / MC_FILE).exists():
            rows += read(d)
    return rows


def contract(deck_text: str) -> dict:
    """The sample-count/output contract embedded by deck()."""
    m = re.search(r"^\* mc_contract (.+)$", deck_text, re.M)
    if not m:
        raise ValueError("MC deck has no completion contract; regenerate it with mc.deck")
    return json.loads(m[1])


def complete(run_dir, deck_text: str) -> bool:
    """Simulation completion, not design pass. Missing crossings remain NaN observations.

    A truncated transient cannot count as complete even when meas found an early crossing.
    Expected missing crossings (e.g. deliberately held lanes) do not force endless reruns.
    """
    d = Path(run_dir)
    c = contract(deck_text)
    try:
        ex = json.loads((d / "execution.json").read_text())
        rows = read(d)
    except (OSError, ValueError):
        return False
    if ex.get("exit_code") != 0 or ex.get("timed_out") or len(rows) != c["samples"]:
        return False
    if any(any(word in line.lower() for word in ("aborted", "timestep too small", "doanalyses", "not enough memory"))
           for line in ex.get("log_failures", [])):
        return False
    if any(not set(c["columns"]).issubset(r) for r in rows):
        return False
    if c["t_end"] is not None:
        return all(np.isfinite(r["mc_t_end"]) and r["mc_t_end"] >= c["t_end"] * (1 - 1e-6) for r in rows)
    return True


def _signature(deck_text: str, files: dict) -> dict:
    """Hash deck and recursive .include contents; PDK identity comes from project config.

    .lib sections are identified by deck + installed PDK id (the installation is immutable).
    Relative includes are resolved against their including file, or copied input files.
    """
    from . import project
    includes = {}
    pattern = re.compile(r'^\s*\.inc(?:lude)?\s+(?:"([^"]+)"|\x27([^\x27]+)\x27|(\S+))', re.I | re.M)

    def visit(text, parent=None):
        for m in pattern.finditer(text):
            name = next(x for x in m.groups() if x is not None)
            p = Path(files[name]) if parent is None and name in files else Path(name)
            if not p.is_absolute():
                if parent is None:
                    raise ValueError(f"MC include must be absolute or supplied in files: {name}")
                p = parent / p
            p = p.resolve()
            if str(p) in includes:
                continue
            data = p.read_bytes()
            includes[str(p)] = hashlib.sha256(data).hexdigest()
            visit(data.decode(), p.parent)

    visit(deck_text)
    return dict(deck=hashlib.sha256(deck_text.encode()).hexdigest(), includes=includes,
                files={k: hashlib.sha256(Path(v).read_bytes()).hexdigest() for k, v in files.items()},
                pdk=project.pdk_installation_id(), ngspice=project.ngspice())


def completed(jobs) -> list[Path | None]:
    """Analysis without running: per job the newest complete attempt (the base directory or a .rN retry made by
    run_many after an interruption) whose deck is the job's deck; None where no attempt is complete.  Reading the base
    directory alone would take a truncated chunk and miss its retry.  Attempts the manifest lists as unverified are
    skipped, as in run_many."""
    out = []
    for text, base, _ in jobs:
        base = Path(base)
        manifest = base.parent / (base.name + ".inputs.json")
        excluded = json.loads(manifest.read_text()).get("unverified_attempts", []) if manifest.exists() else []
        attempts = [base] + sorted((p for p in base.parent.glob(base.name + ".r*")
                                   if p.is_dir() and p.name.rsplit(".r", 1)[-1].isdigit()),
                                  key=lambda p: int(p.name.rsplit(".r", 1)[-1]))
        out.append(next((p for p in reversed(attempts) if p.exists() and p.name not in excluded and complete(p, text)
                         and (p / "tb.cir").read_text() == text), None))
    return out


def run_many(jobs, *, workers: int = 4) -> list[Path]:
    """Resume MC by whole chunk, retaining its seed/order and all previous attempts.

    Same job tuples as spice.run_many; returns exactly one verified output directory per job.
    All jobs are preflighted before running. Changed inputs require a new campaign. Historical
    chunks without an input manifest are rerun once, since their includes cannot be authenticated.
    An incomplete retry raises rather than silently returning a biased subset of the sample set.
    """
    from . import spice
    if not 1 <= workers <= 4:
        raise ValueError("workers must be between 1 and 4")
    jobs = list(jobs)
    selected, todo = [], []
    manifests = []
    for text, base, kw in jobs:
        contract(text)
        base = Path(base)
        sig = _signature(text, kw.get("files", {}))
        manifest = base.parent / (base.name + ".inputs.json")
        trusted = manifest.exists()
        excluded = []
        if trusted:
            recorded = json.loads(manifest.read_text())
            excluded = recorded.pop("unverified_attempts", [])
            if recorded != sig:
                raise ValueError(f"MC inputs changed: {base}; use a new campaign (keep paired seeds/chunks fixed)")
        attempts = [base] + sorted((p for p in base.parent.glob(base.name + ".r*")
                                   if p.is_dir() and p.name.rsplit(".r", 1)[-1].isdigit()),
                                  key=lambda p: int(p.name.rsplit(".r", 1)[-1]))
        found = next((p for p in reversed(attempts) if trusted and p.name not in excluded and complete(p, text)
                      and (p / "tb.cir").read_text() == text), None)
        if found is None:
            if not trusted and base.exists():
                warnings.warn(f"{base}: legacy inputs unverified; rerunning in a new attempt", stacklevel=2)
            found = spice.next_run_dir(base.parent, base.name)
            todo.append((text, found, kw))
        selected.append(found)
        if not trusted:
            manifests.append((manifest, {**sig, "unverified_attempts": [p.name for p in attempts if p.exists()]}))
    for path, sig in manifests:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x") as f:
            json.dump(sig, f, indent=2)
    # Unlike the waveform smoke helper, retain the full analysis interval and only reduce the
    # sample count. Do not serialize a whole 50-sample chunk before starting the worker pool.
    if todo and not any(complete(d, text) for (text, _, _), d in zip(jobs, selected)):
        text, d, kw = todo[0]
        c = contract(text)
        if c["samples"] > 1:
            c["samples"] = 1
            pilot = re.sub(r"^\* mc_contract .+$", "* mc_contract " + json.dumps(c, sort_keys=True), text, flags=re.M)
            pilot = re.sub(r"(mc_k < )\d+", r"\g<1>1", pilot)
            pd = spice.next_run_dir(d.parent, d.name + ".pilot")
            spice.run(pilot, pd, **{**kw, "meta": {**kw.get("meta", {}), "samples": 1, "phase": "pilot"}})
            if not complete(pd, pilot):
                raise RuntimeError(f"incomplete MC pilot: {pd}; inspect log/rows before resuming")
    spice.run_many(todo, workers=workers, smoke=False)
    failed = [str(d) for (text, _, _), d in zip(jobs, selected) if not complete(d, text)]
    if failed:
        raise RuntimeError("incomplete MC chunks (no statistical summary): " + ", ".join(failed))
    return selected

