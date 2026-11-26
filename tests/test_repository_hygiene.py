import hashlib
import importlib.util
import json

from serdes_flow.project import ROOT


def load_script(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_retired_checks_both_receipt_formats_and_detects_corruption(tmp_path, monkeypatch):
    hygiene = load_script("repository_hygiene", "verification/maintenance/repository_hygiene.py")
    monkeypatch.setattr(hygiene, "ROOT", tmp_path)

    catalog = tmp_path / "results/catalog"
    catalog.mkdir(parents=True)
    archive = tmp_path / "results/archive.mag"
    archive.write_bytes(b"original")
    rows = [
        dict(former_path="analog/one.mag", archive="results/archive.mag"),
        dict(former_path="analog/two.mag", archive_path=str(archive)),
    ]
    for row in rows:
        row.update(bytes=8, sha256=hashlib.sha256(b"original").hexdigest())
    (catalog / "retired_test.json").write_text(json.dumps(dict(files=rows)))
    assert hygiene.verify_retired() == (2, [])

    archive.write_bytes(b"modified")
    count, issues = hygiene.verify_retired()
    assert count == 0
    assert len(issues) == 2
    assert all("SHA-256 mismatch" in issue for issue in issues)

    archive.unlink()
    count, issues = hygiene.verify_retired()
    assert count == 0
    assert len(issues) == 2
    assert all("missing archive" in issue for issue in issues)
