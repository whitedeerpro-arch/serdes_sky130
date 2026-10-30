"""Every relative link in the tracked markdown must resolve to an existing path.

results/** is skipped except results/README.md and results/catalog/README.md,
which are tracked; links into results/ from docs must still exist on disk.
"""
import re
from urllib.parse import unquote

from serdes_flow.project import ROOT

LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"(```|~~~).*?\1", re.S)


def _markdown_files():
    for p in ROOT.rglob("*.md"):
        rel = p.relative_to(ROOT)
        if rel.parts[0] in (".venv", ".git"):
            continue
        if rel.parts[0] == "results" and str(rel) not in ("results/README.md", "results/catalog/README.md"):
            continue
        yield p


def test_relative_links_resolve():
    broken = []
    for p in _markdown_files():
        for target in LINK.findall(FENCE.sub("", p.read_text(errors="replace"))):
            if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
                continue
            path = unquote(target.split("#", 1)[0])
            if path and not (p.parent / path).exists():
                broken.append(f"{p.relative_to(ROOT)} -> {target}")
    assert not broken, "\n".join(broken)
