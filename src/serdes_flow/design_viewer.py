"""Local hierarchical design browser and append-only module iteration records.

    uv run python -m serdes_flow.design_viewer --open
    uv run python -m serdes_flow.design_viewer --export

The browser does not run simulations or alter circuit selection. Source data
are config/design_catalog.json; new records live under docs/design/iterations/.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import unquote, urlsplit
import uuid
import webbrowser
from zoneinfo import ZoneInfo

from .project import ROOT

ASSETS = ROOT / "web/design"
PHASES = {"planning", "model", "circuit", "validation", "conclusion"}
TEXT_FIELDS = ("problem", "model", "changes", "validation", "conclusion")
ALLOWED_TOP = {"docs", "config", "analog", "digital", "verification", "src", "tests"}
ALLOWED_EXT = {".md", ".toml", ".json", ".spice", ".cir", ".in", ".sv", ".py", ".csv", ".tsv", ".png", ".svg", ".pdf", ".dot", ".txt"}


class Workspace:
    def __init__(self, root: Path = ROOT, records: Path | None = None):
        self.root = root.resolve()
        self.records = records if records is not None else self.root / "docs/design/iterations"

    def artifact(self, path: str) -> Path:
        """Resolve an allowed repository artifact, rejecting traversal/symlink escape."""
        raw = Path(path.split("#", 1)[0])
        p = (self.root / raw).resolve()
        if not p.is_relative_to(self.root) or not p.is_file():
            raise ValueError("附件需要是仓库中已有的文件")
        relative = p.relative_to(self.root)
        if relative.parts[0] not in ALLOWED_TOP and str(relative) not in {"README.md", "AGENTS.md"} and relative.parts[:2] != ("results", "catalog"):
            raise ValueError("此目录不在设计资料范围内")
        if p.suffix.lower() not in ALLOWED_EXT:
            raise ValueError("不支持此资料格式")
        return p

    def catalog(self) -> dict:
        data = json.loads((self.root / "config/design_catalog.json").read_text())
        nodes = {n["id"]: n for n in data["nodes"]}
        if len(nodes) != len(data["nodes"]) or "serdes" not in nodes:
            raise ValueError("模块 ID 需要唯一，且应有 serdes 根节点")
        for node in nodes.values():
            seen = {node["id"]}
            parent = node["parent"]
            while parent is not None:
                if parent not in nodes or parent in seen:
                    raise ValueError("模块层次存在缺失父级或循环")
                seen.add(parent)
                parent = nodes[parent]["parent"]
        for path in sorted(self.records.glob("*/*.json")) if self.records.exists() else []:
            record = json.loads(path.read_text())
            if record["module"] not in nodes:
                raise ValueError(f"迭代记录引用了不存在的模块: {path.name}")
            nodes[record["module"]].setdefault("iterations", []).append(record)
        data["mode"] = "workspace"
        return data

    def append_iteration(self, payload: dict) -> dict:
        module = payload.get("module", "")
        ids = {n["id"] for n in self.catalog()["nodes"]}
        if module not in ids or not re.fullmatch(r"[a-z0-9._-]+", module):
            raise ValueError("请选择已有模块")
        title = payload.get("title", "").strip()
        phase = payload.get("phase", "planning")
        if not 2 <= len(title) <= 160 or phase not in PHASES:
            raise ValueError("请填写 2–160 字的标题，并选择有效阶段")
        fields = {}
        for key in TEXT_FIELDS:
            value = payload.get(key, "")
            if not isinstance(value, str) or len(value) > 8000:
                raise ValueError("单个记录字段不能超过 8000 字")
            fields[key] = value.strip()
        if not fields["problem"]:
            raise ValueError("请说明这次迭代要解决的问题")
        attached = payload.get("attachments", [])
        if not isinstance(attached, list) or len(attached) > 20:
            raise ValueError("最多附加 20 个已有资料路径")
        attachments = []
        for item in attached:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError("附件需要包含仓库文件路径")
            p = self.artifact(item["path"])
            attachments.append(dict(title=str(item.get("title") or p.name)[:160], path=str(p.relative_to(self.root))))
        now = datetime.now(timezone.utc)
        record_id = now.strftime("%Y%m%dT%H%M%SZ") + "_" + uuid.uuid4().hex[:10]
        record = dict(id=record_id, module=module, date=now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat(), timestamp=now.isoformat(),
                      title=title, phase=phase, **fields, attachments=attachments)
        directory = self.records / module
        directory.mkdir(parents=True, exist_ok=True)
        # Publish a fully written new file atomically, without replacing any record.
        temp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".pending-", suffix=".tmp", dir=directory, delete=False) as f:
                temp = Path(f.name)
                json.dump(record, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.link(temp, directory / f"{record_id}.json")
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)
        return record


def export_catalog(workspace: Workspace, destination: Path = ASSETS / "catalog.js"):
    data = workspace.catalog()
    data["mode"] = "standalone"
    # External JS supports opening index.html directly, without file:// fetch.
    body = json.dumps(data, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    destination.write_text("// Generated data; edit config/design_catalog.json and module records.\nwindow.DESIGN_CATALOG = " + body + ";\n")


def handler_for(workspace: Workspace):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
                super().log_message(fmt, *args)

        def send(self, status, body: bytes, content_type="application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def json(self, status, value):
            self.send(status, json.dumps(value, ensure_ascii=False).encode())

        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            try:
                if path == "/api/catalog":
                    self.json(200, workspace.catalog())
                elif path.startswith("/repo/"):
                    p = workspace.artifact(path.removeprefix("/repo/"))
                    if p.stat().st_size > 12 * 1024 * 1024:
                        raise ValueError("资料超过 12 MB，请从仓库直接查看")
                    kind = mimetypes.guess_type(p.name)[0] if p.suffix in {".png", ".svg", ".pdf"} else "text/plain; charset=utf-8"
                    self.send(200, p.read_bytes(), kind or "application/octet-stream")
                elif path in {"/", "/index.html", "/app.js", "/style.css", "/catalog.js"}:
                    p = ASSETS / ("index.html" if path == "/" else path[1:])
                    kind = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}[p.suffix]
                    self.send(200, p.read_bytes(), kind + "; charset=utf-8")
                else:
                    self.json(404, dict(error="页面不存在"))
            except (ValueError, FileNotFoundError) as err:
                self.json(404, dict(error=str(err)))

        def do_POST(self):
            if urlsplit(self.path).path != "/api/iterations":
                self.json(404, dict(error="接口不存在"))
                return
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{self.headers.get('Host')}":
                self.json(403, dict(error="请从当前本地工作台保存"))
                return
            if self.headers.get_content_type() != "application/json":
                self.json(415, dict(error="需要 JSON 请求"))
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("记录需要小于 64 KB")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("记录格式不正确")
                self.json(201, workspace.append_iteration(payload))
            except (ValueError, TypeError, AttributeError) as err:
                self.json(400, dict(error=str(err)))

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open the local browser")
    ap.add_argument("--export", action="store_true", help="refresh standalone catalog.js and exit")
    args = ap.parse_args()
    workspace = Workspace()
    export_catalog(workspace)
    if args.export:
        print("Exported web/design/catalog.js")
        return
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(workspace))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Design workspace: {url}", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
