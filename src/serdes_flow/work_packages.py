"""Read-only delegation packets and delivery checks; acceptance is human review.

uv run python -m serdes_flow.work_packages list
uv run python -m serdes_flow.work_packages show WP-001
uv run python -m serdes_flow.work_packages check WP-001
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from .project import ROOT

STATES = {"waiting", "ready", "running", "submitted", "accepted", "changes_requested"}
CHECK_STATES = {"pass", "fail", "ungraded", "missing"}
ARCHIVE_ROOT = Path("/opt/serdes_archive")


def relative_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError("paths must be relative to the repository")
    root = root.resolve()
    lexical = Path(os.path.abspath(root / name))
    if not lexical.is_relative_to(root):
        raise ValueError(f"input missing or outside repository: {name}")
    path = lexical.resolve()
    relative = lexical.relative_to(root)
    archived = (relative.parts and relative.parts[0] == "results"
                and path == ARCHIVE_ROOT / relative)
    if not (path.is_relative_to(root) or archived) or not path.is_file():
        raise ValueError(f"input missing or outside repository: {name}")
    return path


def packages(root: Path = ROOT) -> list[dict]:
    data = json.loads((root / "config/work_packages.json").read_text())
    rows = data["packages"]
    ids = {p["id"] for p in rows}
    if len(ids) != len(rows):
        raise ValueError("duplicate work-package id")
    for row in rows:
        if not re.fullmatch(r"WP-\d{3}", row["id"]) or row["state"] not in STATES:
            raise ValueError("invalid work-package identity or state")
        if not set(row["dependencies"]) <= ids or row["id"] in row["dependencies"]:
            raise ValueError("invalid work-package dependencies")
        relative_file(root, row["task"])
    # Detect cycles, including unassigned downstream packages.
    edges = {row["id"]: row["dependencies"] for row in rows}
    def visit(node, ancestors):
        if node in ancestors:
            raise ValueError("work-package dependency cycle")
        for dep in edges[node]:
            visit(dep, ancestors | {node})
    for node in edges:
        visit(node, set())
    return rows


def get(package_id: str, root: Path = ROOT) -> dict:
    for package in packages(root):
        if package["id"] == package_id:
            return package
    raise ValueError(f"unknown work package: {package_id}")


def prompt(package_id: str, root: Path = ROOT) -> str:
    package = get(package_id, root)
    common = relative_file(root, "docs/work_packages/README.md").read_text()
    task = relative_file(root, package["task"]).read_text()
    return f"工作包 {package_id}；状态 {package['state']}；模块 {package['module']}。\n\n{common}\n\n---\n\n{task}"


def check(package_id: str, root: Path = ROOT) -> dict:
    """Validate delivery identity/format only, including explicitly failed checks.

    A valid report may contain failures. Never promote its package state or
    design qualification automatically. Review is recorded in a separate file.
    """
    package = get(package_id, root)
    directory = package["delivery"]
    path = relative_file(root, f"{directory}/evidence.json")
    data = json.loads(path.read_text())
    if data.get("package_id") != package_id:
        raise ValueError("delivery package id mismatch")
    if data.get("execution_status") not in {"complete", "partial", "blocked"}:
        raise ValueError("execution_status must be complete/partial/blocked")
    for field in ("inputs", "checks", "unresolved"):
        if not isinstance(data.get(field), list):
            raise ValueError(f"{field} must be a list")
    if not isinstance(data.get("observations"), (list, dict)):
        raise ValueError("observations must be a list or named object")
    if not data["inputs"] or not data["checks"]:
        raise ValueError("inputs and checks must not be empty")
    seen = set()
    absent = []
    for item in data["inputs"]:
        name, expected = item.get("path"), item.get("sha256")
        if not isinstance(name, str) or name in seen:
            raise ValueError("input paths must be unique")
        if expected is None and item.get("reason") == "file missing":
            candidate = (root / name).resolve()
            if Path(name).is_absolute() or not candidate.is_relative_to(root.resolve()) or candidate.exists():
                raise ValueError(f"declared missing input is unsafe or now exists: {name}")
            seen.add(name)
            absent.append(name)
            continue
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("input paths must be unique and hashes must be SHA256")
        seen.add(name)
        actual = hashlib.sha256(relative_file(root, name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"input changed: {name}")
    seen_checks = set()
    counts = {state: 0 for state in sorted(CHECK_STATES)}
    for item in data["checks"]:
        cid, status = item.get("id"), item.get("status")
        if not isinstance(cid, str) or not cid or cid in seen_checks or status not in CHECK_STATES or not isinstance(item.get("detail"), (str, dict)):
            raise ValueError("checks need unique ids, explicit status and a detail string")
        seen_checks.add(cid)
        counts[status] += 1
    for name in ("summary.md", "handoff.md"):
        relative_file(root, f"{directory}/{name}")
    if package["script"]:
        relative_file(root, package["script"])
    if package["state"] == "accepted":
        relative_file(root, package["review"])
    return dict(package_id=package_id, delivery_format="valid", input_files=len(seen) - len(absent), declared_missing_inputs=absent, execution_status=data["execution_status"],
                declared_checks=counts, package_state=package["state"], engineering_review="separate; this command does not accept the package")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("list", "show", "check"))
    parser.add_argument("package_id", nargs="?")
    args = parser.parse_args()
    if args.command != "list" and args.package_id is None:
        parser.error("package id is required")
    try:
        if args.command == "list":
            for row in packages():
                print(f"{row['id']:7s} {row['state']:18s} {row['module']:20s} {row['difficulty']}")
        elif args.command == "show":
            print(prompt(args.package_id))
        else:
            print(json.dumps(check(args.package_id), ensure_ascii=False, indent=2))
    except (ValueError, KeyError, OSError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
