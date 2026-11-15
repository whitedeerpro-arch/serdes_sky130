"""Shared append-only transient execution for local layout reviews."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from serdes_flow import project, spice, watch


def freeze_includes(deck: str, out: Path) -> str:
    """Snapshot repository includes recursively; never relocate historical runs.

    Source paths can move after preparation: the deck uses only the frozen
    copies. PDK includes stay in the versioned installation identified by run().
    """
    dest = out.resolve() / "inputs"
    dest.mkdir(parents=True, exist_ok=True)
    seen = {}
    pattern = re.compile(r'^(\s*\.include\s+)(?:"([^"]+)"|(\S+))\s*$', re.M | re.I)

    def rewrite(text, base):
        def sub(m):
            source = Path(m[2] or m[3])
            source = (base / source).resolve() if not source.is_absolute() else source.resolve()
            if not source.is_relative_to(project.ROOT) or source.is_relative_to(dest):
                return m[0]
            if source not in seen:
                name = hashlib.sha256(str(source.relative_to(project.ROOT)).encode()).hexdigest()[:12] + "_" + source.name
                target = dest / name
                seen[source] = target
                content = rewrite(source.read_text(), source.parent)
                if target.exists() and target.read_text() != content:
                    raise ValueError(f"Frozen include changed: {source}")
                if not target.exists():
                    target.write_text(content)
            return f'{m[1]}"{seen[source]}"'
        return pattern.sub(sub, text)
    return rewrite(deck, project.ROOT)


def execute(cases, out: Path, *, workers=2, timeout_s=1200):
    """cases maps stable names to (deck, t_end); returns complete output paths.

    Each case has one condition. A rerun appends .rN, and only a successful
    execution with a complete waveform can be reused.
    """
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    jobs, paths, identity = [], {}, {}
    for key, (deck, tend) in cases.items():
        deck = freeze_includes(deck, out)
        identity[key] = dict(deck_sha256=hashlib.sha256(deck.encode()).hexdigest(), t_end=tend)
        old = spice.case_output(out, key, "waveforms.raw", t_end=tend)
        if old is not None:
            ex = old.parent / "execution.json"
            data = json.loads(ex.read_text()) if ex.exists() else {}
            if data.get("exit_code") != 0 or data.get("log_failures"):
                old = None
        if old is None:
            d = spice.next_run_dir(out, key)
            jobs.append((deck, d, dict(timeout_s=timeout_s)))
            paths[key] = d / "waveforms.raw"
        else:
            paths[key] = old
    record = out / "identity.json"
    if record.exists() and json.loads(record.read_text()) != identity:
        raise ValueError("Campaign inputs changed; start a new output directory")
    if not record.exists():
        record.write_text(json.dumps(identity, indent=2) + "\n")
    if len(watch.ngspice_cwds()) + workers > 4:
        raise RuntimeError("ngspice quota occupied")
    # Do not release a whole long queue after the first numerical or model
    # failure. Only one worker batch can already be in flight.
    for start in range(0,len(jobs),workers):
        for ex in spice.run_many(jobs[start:start+workers], workers=workers, smoke=start==0):
            print(ex.run_dir.name, ex.ok, round(ex.elapsed_s, 1), flush=True)
            if not ex.ok:
                raise RuntimeError(f"simulation failed: {ex.run_dir}")
    for key, path in paths.items():
        if spice.Waves(path).t[-1] < cases[key][1] * (1-1e-6):
            raise ValueError(f"truncated: {path}")
    return paths


def save_analysis(out: Path, result: dict) -> Path:
    dest = out / "analysis" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    dest.mkdir(parents=True, exist_ok=False)
    path = dest / "summary.json"
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(path, flush=True)
    return path
