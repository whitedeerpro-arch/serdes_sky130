"""Minimal SPICE subcircuit reader and flattener for static checks (no simulation).

Reads the project's .spice files (subcircuits with `+ params:` defaults, instances with k=v and
{expr} overrides, R / C elements), flattens a top subcircuit and returns primitive devices with
hierarchical node names.  Leaves are PDK devices (sky130_fd_pr__*) and R / C elements; anything
else that is not defined is reported as unknown.  Expressions are evaluated with SPICE number
suffixes and floor / sqrt / min / max / abs.  Enough for the project's netlists, not a SPICE parser.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

_SUFFIX = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
_NUM = re.compile(r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(meg|[tgkmunpf])?[a-zA-Z]*$")


def number(text: str) -> float:
    m = _NUM.match(text.strip().lower())
    if not m:
        raise ValueError(f"not a number: {text!r}")
    return float(m[1]) * _SUFFIX.get(m[2] or "", 1.0)


def _expr(text: str, scope: dict) -> float:
    s = text.strip()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1]
    try:
        return number(s)
    except ValueError:
        pass
    # SPICE literals with suffixes inside expressions, e.g. 0.6p
    s = re.sub(r"(?<![\w.])(\d+\.?\d*|\.\d+)(meg|[tgkmunpf])(?![\w(])",
               lambda m: repr(float(m[1]) * _SUFFIX[m[2].lower()]), s)
    env = dict(floor=math.floor, sqrt=math.sqrt, min=min, max=max, abs=abs, __builtins__={})
    return float(eval(s, env, dict(scope)))


@dataclass
class Element:
    name: str
    nodes: list
    ref: str               # subcircuit / model name, or "R" / "C"
    params: dict           # raw strings


@dataclass
class Subckt:
    name: str
    ports: list
    defaults: dict
    elements: list = field(default_factory=list)


@dataclass
class Device:
    path: str              # hierarchical instance name
    kind: str              # "mos", "R", "C"
    model: str
    nodes: list
    w: float = 0.0
    l: float = 0.0
    nf: int = 1
    value: float = 0.0


def _logical_lines(text):
    out = []
    for raw in text.splitlines():
        line = raw.split("$")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.startswith("+") and out:
            out[-1] += " " + line[1:].strip()
        else:
            out.append(line.strip())
    return out


def _kv(tokens):
    nodes, params = [], {}
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            params[k.lower()] = v
        elif tok.lower() != "params:":
            nodes.append(tok)
    return nodes, params


def parse(files) -> dict[str, Subckt]:
    subs, cur = {}, None
    for f in files:
        for line in _logical_lines(Path(f).read_text(errors="replace")):
            toks = line.split()
            head = toks[0].lower()
            if head == ".subckt":
                ports, defaults = _kv(toks[2:])
                cur = Subckt(toks[1].lower(), [p.lower() for p in ports], defaults)
                subs.setdefault(cur.name, cur)
            elif head.startswith(".ends"):
                cur = None
            elif cur is not None and head[0] in "xrc":
                nodes, params = _kv(toks[1:])
                if head[0] == "x":
                    cur.elements.append(Element(toks[0].lower(), [n.lower() for n in nodes[:-1]], nodes[-1].lower(), params))
                else:
                    val = nodes[2] if len(nodes) > 2 else params.get("value", "0")
                    cur.elements.append(Element(toks[0].lower(), [n.lower() for n in nodes[:2]], head[0].upper(), {"value": val}))
    return subs


def flatten(subs, top: str, overrides: dict | None = None, ports_map: dict | None = None, path: str = ""):
    """Primitive devices of `top`.  Node names: ports as given by ports_map, internals path.node."""
    sc = subs[top.lower()]
    scope = {}
    for k, v in sc.defaults.items():
        scope[k] = _expr(v, scope)
    for k, v in (overrides or {}).items():
        scope[k.lower()] = float(v) if not isinstance(v, str) else _expr(v, scope)
    pm = ports_map or {p: p for p in sc.ports}
    glob = {"0", "vss", "vdd", "gnd"}
    node = lambda n: pm.get(n, n if n in glob else f"{path}{n}")
    out, unknown = [], set()
    for e in sc.elements:
        if e.ref in ("R", "C"):
            out.append(Device(f"{path}{e.name}", e.ref, e.ref, [node(n) for n in e.nodes], value=_expr(e.params["value"], scope)))
        elif e.ref.startswith("sky130_fd_pr__"):
            p = {k: _expr(v, scope) for k, v in e.params.items() if k in ("w", "l", "nf")}
            out.append(Device(f"{path}{e.name}", "mos", e.ref, [node(n) for n in e.nodes[:4]], w=p.get("w", 1.0),
                              l=p.get("l", 0.15), nf=int(p.get("nf", 1))))
        elif e.ref in subs:
            child = subs[e.ref]
            ov = {k: _expr(v, scope) for k, v in e.params.items()}
            cmap = {p: node(n) for p, n in zip(child.ports, e.nodes)}
            devs, unk = flatten(subs, e.ref, ov, cmap, f"{path}{e.name}.")
            out += devs
            unknown |= unk
        else:
            unknown.add(e.ref)
    return out, unknown


def project_files(root: Path):
    return sorted(p for p in (root / "analog").glob("**/spice/*.spice") if "exploratory" not in p.parts)
