"""Lossless in-place gzip of large result waveforms (docs/verification/methods.md, waveform storage).

    uv run python verification/maintenance/compress_waveforms.py [--min-mb 1] [--older-h 24] [--dry-run]

Candidates: results/**/*.raw and *.tsv above --min-mb, last modified more than --older-h hours ago.  Skipped:
* files whose repository-relative path appears in any git-tracked file (registered boundary recordings in
  config/boundary_conditions.json, docs/data and results/catalog records): their consumers check the raw file's
  SHA-256 at that path;
* directories with a live ngspice.
Each file is compressed to <name>.gz.tmp, decompressed again and compared by SHA-256 with the original, renamed to
<name>.gz, and only then the original is removed.  spice.Waves reads the .gz directly.  A manifest (path, original
SHA-256, sizes) is written under results/maintenance/compress_waveforms/<UTC>/.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

from serdes_flow import watch
from serdes_flow.project import ROOT

REF = re.compile(r"results/[^\s\"'(),;|<>]+?\.(?:raw|tsv)\b")


def sha_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 20), b""):
            h.update(part)
    return h.hexdigest()


def sha_gunzip(path):
    h = hashlib.sha256()
    with subprocess.Popen(["gzip", "-dc", str(path)], stdout=subprocess.PIPE) as p:
        for part in iter(lambda: p.stdout.read(1 << 20), b""):
            h.update(part)
    if p.returncode:
        raise RuntimeError(f"gzip -dc {path}: exit {p.returncode}")
    return h.hexdigest()


def referenced():
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout.split(b"\0")
    refs = set()
    for f in files:
        p = ROOT / f.decode()
        if not f or not p.is_file() or p.stat().st_size > 50e6:
            continue
        try:
            refs.update(REF.findall(p.read_text(errors="ignore")))
        except OSError:
            continue
    return refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-mb", type=float, default=1)
    ap.add_argument("--older-h", type=float, default=24)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    refs = referenced()
    alive = watch.ngspice_cwds()
    cutoff = time.time() - a.older_h * 3600
    todo, skipped = [], dict(referenced=0, recent=0, live=0)
    for p in sorted((ROOT / "results").rglob("*")):
        if p.suffix not in (".raw", ".tsv") or not p.is_file() or p.is_symlink() or p.stat().st_size < a.min_mb * 1e6:
            continue
        rel = str(p.relative_to(ROOT))
        if rel in refs:
            skipped["referenced"] += 1
        elif p.stat().st_mtime > cutoff:
            skipped["recent"] += 1
        elif any(d == p.parent.resolve() or d.is_relative_to(p.parent.resolve()) for d in alive):
            skipped["live"] += 1
        else:
            todo.append(p)
    total = sum(p.stat().st_size for p in todo)
    print(f"{len(todo)} files, {total / 1e9:.2f} GB to compress; skipped {skipped}", flush=True)
    if a.dry_run:
        return
    out = ROOT / "results/maintenance/compress_waveforms" / time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out.mkdir(parents=True)
    rows, saved = [], 0
    with (out / "manifest.jsonl").open("w") as man:
        for i, p in enumerate(todo, 1):
            gz, tmp = p.with_name(p.name + ".gz"), p.with_name(p.name + ".gz.tmp")
            if gz.exists():
                print(f"skip {p}: {gz.name} exists", flush=True)
                continue
            size, digest = p.stat().st_size, sha_file(p)
            with tmp.open("wb") as f:
                subprocess.run(["gzip", "-6", "-c", str(p)], stdout=f, check=True)
            if sha_gunzip(tmp) != digest or sha_file(p) != digest:
                tmp.unlink()
                raise RuntimeError(f"{p}: verification failed, original kept")
            os.replace(tmp, gz)
            os.utime(gz, (p.stat().st_atime, p.stat().st_mtime))
            p.unlink()
            row = dict(path=str(p.relative_to(ROOT)), sha256=digest, bytes=size, gz_bytes=gz.stat().st_size)
            man.write(json.dumps(row) + "\n")
            man.flush()
            saved += size - row["gz_bytes"]
            if i % 100 == 0:
                print(f"{i}/{len(todo)} saved {saved / 1e9:.2f} GB", flush=True)
    (out / "summary.json").write_text(json.dumps(dict(files=len(todo), bytes=total, saved_bytes=saved, skipped=skipped,
                                                      min_mb=a.min_mb, older_h=a.older_h), indent=1) + "\n")
    print(f"done: {len(todo)} files, saved {saved / 1e9:.2f} GB; manifest {out.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
