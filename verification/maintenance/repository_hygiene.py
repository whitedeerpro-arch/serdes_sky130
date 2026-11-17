"""Find runtime artifacts in source directories; archive them with byte receipts.

Only layout logs/EXT and repository-root waveform files are selected. Test
fixtures, circuit sources, results and release baselines are outside this set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

from serdes_flow.project import ROOT


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def runtime_files():
    files = {p for p in (ROOT / "analog").rglob("*")
             if "layout" in p.relative_to(ROOT).parts and p.suffix in (".log", ".ext")
             and p.is_file() and not p.is_symlink()}
    files.update(p for p in ROOT.iterdir()
                 if p.is_file() and not p.is_symlink() and p.suffix in (".vcd", ".raw", ".fst"))
    return sorted(files)


def archive(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT / "results"):
        raise ValueError("Archive must be under results/")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for source in runtime_files():
        relative = source.relative_to(ROOT)
        target = output / "files" / relative
        expected = digest(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if digest(target) != expected or digest(source) != expected:
            raise ValueError(f"Artifact changed while archiving: {relative}")
        records.append(dict(former_path=str(relative), archive=str(target.relative_to(ROOT)),
                            sha256=expected, bytes=target.stat().st_size))
    manifest = output / "manifest.json"
    manifest.write_text(json.dumps(dict(kind="source_runtime_artifacts", files=records), indent=2) + "\n")
    # All copies and the receipt exist before any source is removed.
    for row in records:
        source = ROOT / row["former_path"]
        if digest(source) != row["sha256"]:
            raise ValueError(f"Artifact changed before removal: {source}")
        source.unlink()
    print(f"Archived {len(records)} files; receipt: {manifest.relative_to(ROOT)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    arch = sub.add_parser("archive")
    arch.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.command == "archive":
        archive(args.output_dir)
    else:
        files = runtime_files()
        for path in files:
            print(path.relative_to(ROOT))
        print(f"Runtime artifacts in source directories: {len(files)}")
        raise SystemExit(bool(files))


if __name__ == "__main__":
    main()
