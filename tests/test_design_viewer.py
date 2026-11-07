import json
from pathlib import Path

import pytest

from serdes_flow.design_viewer import Workspace, export_catalog
from serdes_flow.project import ROOT


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "docs/design").mkdir(parents=True)
    (tmp_path / "docs/design/vco.md").write_text("# VCO\n")
    (tmp_path / "config/design_catalog.json").write_text(json.dumps(dict(nodes=[
        dict(id="serdes", parent=None, name="SerDes", iterations=[]),
        dict(id="pll.vco", parent="serdes", name="VCO", iterations=[]),
    ])))
    return Workspace(tmp_path)


def test_iteration_is_attached_to_module_and_appended_atomically(workspace):
    payload = dict(module="pll.vco", title="工作区改进", phase="model", problem="粗码间重叠需要核对",
                   model="先用周期拟合选码，再检查仿真点", attachments=[dict(path="docs/design/vco.md")])
    first = workspace.append_iteration(payload)
    original = (workspace.records / "pll.vco" / (first["id"] + ".json")).read_bytes()
    second = workspace.append_iteration(payload)
    assert first["id"] != second["id"]
    assert len(list(workspace.records.glob("*/*.json"))) == 2
    assert not list(workspace.records.glob("*/.pending-*"))
    assert (workspace.records / "pll.vco" / (first["id"] + ".json")).read_bytes() == original
    node = next(n for n in workspace.catalog()["nodes"] if n["id"] == "pll.vco")
    assert len(node["iterations"]) == 2
    assert node["iterations"][0]["attachments"][0]["path"] == "docs/design/vco.md"


@pytest.mark.parametrize("payload", [
    dict(module="../outside", title="错误记录", problem="问题"),
    dict(module="pll.vco", title="", problem="问题"),
    dict(module="pll.vco", title="错误记录", problem=""),
    dict(module="pll.vco", title="错误记录", problem="问题", phase="unknown"),
    dict(module="pll.vco", title="错误记录", problem="问题", attachments=[dict(path="../../outside.md")]),
])
def test_invalid_record_does_not_write_files(workspace, payload):
    with pytest.raises(ValueError):
        workspace.append_iteration(payload)
    assert not workspace.records.exists()


def test_artifact_does_not_follow_symlink_outside_repository(workspace, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.md")
    outside.write_text("outside")
    (tmp_path / "docs/linked.md").symlink_to(outside)
    with pytest.raises(ValueError):
        workspace.artifact("docs/linked.md")


def test_standalone_export_contains_attached_records(workspace, tmp_path):
    workspace.append_iteration(dict(module="pll.vco", title="新的推导", problem="输入范围", phase="planning"))
    path = tmp_path / "catalog.js"
    export_catalog(workspace, path)
    assert "window.DESIGN_CATALOG = " in path.read_text()
    data = json.loads(path.read_text().split("window.DESIGN_CATALOG = ", 1)[1].rstrip().removesuffix(";"))
    assert data["mode"] == "standalone"
    assert data["nodes"][1]["iterations"][0]["module"] == "pll.vco"


def test_project_hierarchy_and_evidence_links_are_valid():
    workspace = Workspace(ROOT)
    data = workspace.catalog()
    assert {n["id"] for n in data["nodes"] if n["parent"] == "serdes"} == {"tx", "bias", "rx", "pll", "channel"}
    assert next(n for n in data["nodes"] if n["id"] == "pll")["state"] == "顶层集成已有"
    for node in data["nodes"]:
        assert "boundary" in node
        for ref in node.get("references", []) + [a for record in node.get("iterations", []) for a in record.get("attachments", [])]:
            assert workspace.artifact(ref["path"]).exists()
