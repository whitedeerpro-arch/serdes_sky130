"""Delegation checks must preserve failed/unknown evidence and reject stale input."""
import hashlib
import json

import pytest

from serdes_flow import work_packages as wp


@pytest.fixture
def repository(tmp_path):
    for directory in ("config", "docs/work_packages/deliveries/WP-001", "docs/work_packages/reviews", "verification/work_packages"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/work_packages/README.md").write_text("shared rules")
    (tmp_path / "docs/work_packages/task.md").write_text("fixed instructions")
    (tmp_path / "input.raw").write_bytes(b"original measurement")
    (tmp_path / "verification/work_packages/audit.py").write_text("# read only")
    package = dict(id="WP-001", state="submitted", module="pll.extraction", task="docs/work_packages/task.md", delivery="docs/work_packages/deliveries/WP-001",
                   script="verification/work_packages/audit.py", review="docs/work_packages/reviews/WP-001.md", dependencies=[])
    (tmp_path / "config/work_packages.json").write_text(json.dumps(dict(packages=[package])))
    evidence = dict(package_id="WP-001", execution_status="partial", inputs=[dict(path="input.raw", sha256=hashlib.sha256(b"original measurement").hexdigest())],
                    observations=[], checks=[dict(id="waveform", status="fail", detail="truncated"), dict(id="noise", status="ungraded", detail="not in scope")], unresolved=["restart pending"])
    delivery = tmp_path / package["delivery"]
    (delivery / "evidence.json").write_text(json.dumps(evidence))
    (delivery / "summary.md").write_text("truncated")
    (delivery / "handoff.md").write_text("review required")
    return tmp_path, package, evidence


def test_valid_delivery_keeps_failures_and_does_not_accept(repository):
    root, _, _ = repository
    before = (root / "config/work_packages.json").read_bytes()
    result = wp.check("WP-001", root)
    assert result["declared_checks"]["fail"] == 1
    assert result["declared_checks"]["ungraded"] == 1
    assert result["package_state"] == "submitted"
    assert (root / "config/work_packages.json").read_bytes() == before


def test_changed_input_is_rejected(repository):
    root, _, _ = repository
    (root / "input.raw").write_bytes(b"different measurement")
    with pytest.raises(ValueError, match="input changed"):
        wp.check("WP-001", root)


def test_declared_missing_input_is_preserved_and_cannot_silently_appear(repository):
    root, package, data = repository
    data["inputs"].append(dict(path="absent.raw", sha256=None, reason="file missing"))
    path = root / package["delivery"] / "evidence.json"
    path.write_text(json.dumps(data))
    result = wp.check("WP-001", root)
    assert result["declared_missing_inputs"] == ["absent.raw"]
    assert result["input_files"] == 1
    (root / "absent.raw").write_bytes(b"new run")
    with pytest.raises(ValueError, match="now exists"):
        wp.check("WP-001", root)


def test_wrong_delivery_identity_is_rejected(repository):
    root, package, data = repository
    data["package_id"] = "WP-002"
    (root / package["delivery"] / "evidence.json").write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mismatch"):
        wp.check("WP-001", root)


def test_unknown_status_and_duplicate_checks_are_rejected(repository):
    root, package, data = repository
    path = root / package["delivery"] / "evidence.json"
    data["checks"][0]["status"] = "probably_passed"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="explicit status"):
        wp.check("WP-001", root)
    data["checks"][0]["status"] = "missing"
    data["checks"].append(data["checks"][0])
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unique ids"):
        wp.check("WP-001", root)


def test_dependency_cycle_is_rejected(repository):
    root, package, _ = repository
    second = dict(package, id="WP-002", dependencies=["WP-001"])
    package["dependencies"] = ["WP-002"]
    (root / "config/work_packages.json").write_text(json.dumps(dict(packages=[package, second])))
    with pytest.raises(ValueError, match="cycle"):
        wp.packages(root)


def test_symlink_escape_is_rejected(repository, tmp_path_factory):
    root, _, _ = repository
    outside = tmp_path_factory.mktemp("external") / "evidence"
    outside.write_text("outside")
    (root / "escape").symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        wp.relative_file(root, "escape")


def test_archive_mapping_only_for_matching_results_path(repository, tmp_path_factory, monkeypatch):
    root, _, _ = repository
    external = tmp_path_factory.mktemp('archive-test')
    archive = external / 'archive'
    monkeypatch.setattr(wp, 'ARCHIVE_ROOT', archive)
    target = archive / 'results/run/wave.raw'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'wave')
    link = root / 'results/run/wave.raw'
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    assert wp.relative_file(root, 'results/run/wave.raw').read_bytes() == b'wave'
    wrong = root / 'results/run/wrong.raw'
    wrong.symlink_to(target)
    with pytest.raises(ValueError, match='outside'):
        wp.relative_file(root, 'results/run/wrong.raw')
    outside = external / 'outside.raw'
    outside.write_bytes(b'wave')
    link.unlink()
    link.symlink_to(outside)
    with pytest.raises(ValueError, match='outside'):
        wp.relative_file(root, 'results/run/wave.raw')
    non_results = root / 'other.raw'
    non_results.symlink_to(target)
    with pytest.raises(ValueError, match='outside'):
        wp.relative_file(root, 'other.raw')
    with pytest.raises(ValueError, match='outside'):
        wp.relative_file(root, '../outside.raw')
