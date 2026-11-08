"""Move result waveforms off the /home partition: the bytes go to /opt, a file symlink stays at the original path.

    uv run python verification/maintenance/waveform_archive.py archive [--older-h 1] [--min-mb 1] [--dry-run]
    uv run python verification/maintenance/waveform_archive.py prune-failed [--dry-run]
    uv run python verification/maintenance/waveform_archive.py verify [--sha]
    uv run python verification/maintenance/waveform_archive.py restore <path prefix under results/>

The disk is cut into fixed partitions: /home (this project) 47 GB, /opt 75 GB.  `archive` takes results/**/*.raw,
*.tsv and their .gz above --min-mb, older than --older-h, outside directories with a live ngspice; copies each to
/opt/serdes_archive/<same relative path>, compares SHA-256, and replaces the original by a symlink to the copy in one
rename (readers never see a missing file).  Everything that opens the path keeps working: spice.Waves, case_output
and resume checks, SHA-256 checks of registered boundary recordings, mc.tsv appends.  Records (tb.cir, logs, json,
snapshots) stay in place.  Code that calls .resolve() on a waveform file sees the /opt path (clock_epoch.py keys).

`prune-failed` deletes waveform output of runs that failed or timed out (execution.json) when a later rerun of
the same deck (<deck>.rN) finished; the failed run's deck, log and execution.json stay.  `verify` checks every
link's target (size; --sha: content).  `restore` moves the bytes of archived files under a prefix back.
Each action writes a manifest under results/maintenance/waveform_archive/<UTC>/.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

from serdes_flow import watch
from serdes_flow.project import ROOT

ARCHIVE = Path("/opt/serdes_archive")
RESULTS = ROOT / "results"
WAVE = re.compile(r"\.(raw|tsv)(\.gz)?$")
LOG = RESULTS / "maintenance/waveform_archive"


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1 << 22), b""):
            h.update(part)
    return h.hexdigest()


def copy_hashed(src, dst):
    """Copy with metadata; SHA-256 of the bytes read."""
    h = hashlib.sha256()
    with open(src, "rb") as f, open(dst, "wb") as g:
        for part in iter(lambda: f.read(1 << 22), b""):
            h.update(part)
            g.write(part)
    shutil.copystat(src, dst)
    return h.hexdigest()


def waveforms(min_mb, prefix=None):
    base = ROOT / prefix if prefix else RESULTS
    for p in base.rglob("*"):
        if WAVE.search(p.name) and not p.is_symlink() and p.is_file() and p.stat().st_size >= min_mb * 1e6 and not p.is_relative_to(RESULTS / "catalog"):
            yield p


def live_dirs():
    return watch.ngspice_cwds()


def is_live(p, alive):
    d = p.parent.resolve()
    return any(a == d or a.is_relative_to(d) or d.is_relative_to(a) for a in alive)


def manifest_dir(action):
    out = LOG / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}_{action}"
    out.mkdir(parents=True)
    return out


def archive(a):
    alive = live_dirs()
    cutoff = time.time() - a.older_h * 3600
    todo, skip = [], dict(recent=0, live=0)
    for p in waveforms(a.min_mb, a.prefix):
        if p.stat().st_mtime > cutoff:
            skip["recent"] += 1
        elif is_live(p, alive):
            skip["live"] += 1
        else:
            todo.append(p)
    total = sum(p.stat().st_size for p in todo)
    free = shutil.disk_usage("/opt").free
    print(f"{len(todo)} files, {total / 1e9:.2f} GB to move to {ARCHIVE}; /opt free {free / 1e9:.1f} GB; skipped {skip}", flush=True)
    if a.dry_run:
        return
    if total > free - 5e9:
        raise SystemExit("not enough space on /opt (keeps 5 GB spare)")
    out = manifest_dir("archive")
    moved = 0
    with (out / "manifest.jsonl").open("w") as man:
        for i, p in enumerate(todo, 1):
            rel = p.relative_to(ROOT)
            dest = ARCHIVE / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise SystemExit(f"{dest} exists; refusing to overwrite")
            size = p.stat().st_size
            tmp = dest.with_name(dest.name + ".tmp")
            digest = copy_hashed(p, tmp)
            if sha(tmp) != digest:
                tmp.unlink()
                raise SystemExit(f"{p}: copy differs, original kept")
            os.replace(tmp, dest)
            link = p.with_name(p.name + ".archlink")
            os.symlink(dest, link)
            os.replace(link, p)                      # atomic: the path never disappears
            man.write(json.dumps(dict(path=str(rel), archive=str(dest), sha256=digest, bytes=size)) + "\n")
            man.flush()
            moved += size
            if i % 200 == 0:
                print(f"{i}/{len(todo)} {moved / 1e9:.2f} GB", flush=True)
    (out / "summary.json").write_text(json.dumps(dict(files=len(todo), bytes=moved, skipped=skip, older_h=a.older_h, min_mb=a.min_mb), indent=1) + "\n")
    print(f"done: {len(todo)} files, {moved / 1e9:.2f} GB moved; manifest {out.relative_to(ROOT)}", flush=True)


def prune_failed(a):
    rows = []
    for ex in RESULTS.rglob("execution.json"):
        d = ex.parent
        try:
            e = json.loads(ex.read_text())
        except (OSError, ValueError):
            continue
        if not (e.get("timed_out") or e.get("exit_code") not in (0, None)):
            continue
        deck = d.name.rsplit(".r", 1)[0] if re.search(r"\.r\d+$", d.name) else d.name
        later = [x for x in d.parent.glob(f"{deck}.r*") if re.fullmatch(rf"{re.escape(deck)}\.r\d+", x.name)
                 and int(x.name.rsplit(".r", 1)[1]) > (int(d.name.rsplit(".r", 1)[1]) if d.name != deck else 1)]
        good = []
        for x in later:
            try:
                ex2 = json.loads((x / "execution.json").read_text())
            except (OSError, ValueError):
                continue
            if ex2.get("exit_code") == 0 and not ex2.get("timed_out"):
                good.append(x)
        for w in d.iterdir():
            # a rerun repeats only the cases the failed run did not finish: delete an output only if a finished
            # rerun wrote the same file
            same = [x for x in good if (x / w.name).exists()]
            if WAVE.search(w.name) and w.is_file() and same:
                rows.append(dict(path=str(w.relative_to(ROOT)), bytes=w.stat().st_size, failed_run=str(d.relative_to(ROOT)),
                                 superseded_by=sorted(str((x / w.name).relative_to(ROOT)) for x in same)))
    print(f"{len(rows)} waveform files of failed runs with a finished rerun, {sum(r['bytes'] for r in rows) / 1e9:.3f} GB", flush=True)
    if a.dry_run or not rows:
        return
    out = manifest_dir("prune_failed")
    with (out / "deleted.jsonl").open("w") as man:
        for r in rows:
            p = ROOT / r["path"]
            if p.is_symlink():
                target = Path(os.readlink(p))
                p.unlink()
                target.unlink(missing_ok=True)
            else:
                p.unlink()
            man.write(json.dumps(r) + "\n")
    print(f"deleted; list {out.relative_to(ROOT)}/deleted.jsonl", flush=True)


def links():
    for p in RESULTS.rglob("*"):
        if p.is_symlink() and Path(os.readlink(p)).is_relative_to(ARCHIVE):
            yield p


def verify(a):
    n = bad = 0
    for p in links():
        n += 1
        target = Path(os.readlink(p))
        if not target.is_file():
            bad += 1
            print(f"MISSING {p.relative_to(ROOT)} -> {target}")
    manifests = sorted(LOG.glob("*_archive/manifest.jsonl"))
    if a.sha:
        for m in manifests:
            for line in m.read_text().splitlines():
                r = json.loads(line)
                p = ROOT / r["path"]
                if p.is_symlink() and sha(p) != r["sha256"]:
                    bad += 1
                    print(f"CHANGED {r['path']}")
    print(f"{n} archived links, {bad} problems" + (" (content checked)" if a.sha else ""))


def restore(a):
    prefix = ROOT / a.prefix
    out = manifest_dir("restore")
    n = 0
    with (out / "manifest.jsonl").open("w") as man:
        for p in links():
            if not p.is_relative_to(prefix):
                continue
            target = Path(os.readlink(p))
            tmp = p.with_name(p.name + ".restore.tmp")
            shutil.copy2(target, tmp)
            if sha(tmp) != sha(target):
                tmp.unlink()
                raise SystemExit(f"{p}: restore copy differs")
            os.replace(tmp, p)
            target.unlink()
            man.write(json.dumps(dict(path=str(p.relative_to(ROOT)), archive=str(target))) + "\n")
            n += 1
    print(f"restored {n} files")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("archive")
    s.add_argument("--older-h", type=float, default=1)
    s.add_argument("--min-mb", type=float, default=1)
    s.add_argument("--prefix", help="only under this path (relative to the project)")
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("prune-failed")
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("verify")
    s.add_argument("--sha", action="store_true")
    s = sub.add_parser("restore")
    s.add_argument("prefix")
    a = ap.parse_args()
    dict(archive=archive, prune_failed=prune_failed, verify=verify, restore=restore)[a.cmd.replace("-", "_")](a)


if __name__ == "__main__":
    main()
