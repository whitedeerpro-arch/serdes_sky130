"""Real bias in a bench deck: the ideal reference sources -> bandgap reference + module copies.

    text = bias.real(deck_text)                 # a rendered deck; before rcorner.to_pdk
    text = bias.section(text, "ss", "hh")       # library section MOS corner x resistor corner

The benches so far feed each module's bias diode from an ideal current source on a separate ideal
supply (docs/design/bias.md).  real() swaps every such source for a PMOS copy of the constant-swing
reference (analog/bias/spice/bias_dist.spice) on the bench's main supply, so the reference's
own PVT / resistor-corner behaviour and the supply reach the bias as they would on chip:

  0.85 mA into the CML diode nfet 20 / 0.5 nf 4  -> serdes_bias_pcopy n=85 (212.5 uA) into
                                                    serdes_bias_cml (nfet 5 / 0.5, same density)
  50 uA into the CTLE diode nfet_lvt 8 / 0.5 nf 4 -> serdes_bias_pcopy n=20, diode unchanged
  50 uA into the CP vbn diode nfet 5 / 1          -> serdes_bias_pcopy n=20, diode unchanged
  50 uA out of the CP vbp diode pfet 20 / 1 nf 4  -> nfet 5 / 1 copy of the vbn diode

One serdes_bias_ref (bandgap + V->I, r_ref trim code `trim`) per deck, its four spare outputs into
0.7 V.  A current source that matches none of these raises: convert it explicitly.
"""
from __future__ import annotations

import re

from .project import ROOT

BIAS_INC = ("analog/common/devices/spice/sky130_pfet_lvt.spice", "analog/bias/spice/bandgap.spice",
            "analog/bias/spice/bias_dist.spice")
NODESET = (".nodeset v(bias_vbg)=1.23 v(xbias_ref.xbg.s)=1.23 v(xbias_ref.vg)=0.9 v(vgi_bias)=0.9"
           " v(xbias_ref.xbg.ta)=0.95 v(xbias_ref.xbg.tb)=0.95")
_UNIT = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}


def _num(s: str, params: dict) -> float | None:
    s = s.strip().lower()
    if s.startswith("{") and s.endswith("}"):
        s = s[1:-1].strip()
        if s in params:
            return _num(params[s], params)
        return None
    m = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)(meg|[tgkmunpf])?[a-z]*", s)
    if not m:
        return None
    return float(m[1]) * (_UNIT[m[2]] if m[2] else 1.0)


def _diodes(lines):
    """node -> (line index, kind) for the bench bias diodes (drain = gate = node)."""
    out = {}
    for i, l in enumerate(lines):
        t = l.split()
        if len(t) < 6 or not t[0].lower().startswith("x") or t[1] != t[2]:
            continue
        kw = dict(x.lower().split("=", 1) for x in t[6:] if "=" in x)
        w, ln, nf = _num(kw.get("w", "0"), {}), _num(kw.get("l", "0"), {}), _num(kw.get("nf", "1"), {})
        cell = t[5].lower()
        if cell == "serdes_nfet" and t[3] == t[4] == "0" and (w, ln, nf) == (20, 0.5, 4):
            out[t[1]] = (i, "cml")
        elif cell == "serdes_nfet_lvt" and t[3] == t[4] == "0" and (w, ln, nf) == (8, 0.5, 4):
            out[t[1]] = (i, "ctle")
        elif cell == "serdes_nfet" and t[3] == t[4] == "0" and (w, ln, nf) == (5, 1, 1):
            out[t[1]] = (i, "cpn")
        elif cell == "serdes_pfet" and t[3] == t[4] and (w, ln, nf) == (20, 1, 4):
            out[t[1]] = (i, "cpp")
    return out


def real(deck: str, supply: str = "vdd", trim: int = 15) -> str:
    lines = deck.splitlines()
    params = {}
    for l in lines:
        if l.lower().startswith(".param"):
            for k, v in re.findall(r"(\w+)\s*=\s*(\{[^}]*\}|\S+)", l[6:]):
                params[k.lower()] = v
    diodes = _diodes(lines)
    want = {"cml": 0.85e-3, "ctle": 50e-6, "cpn": 50e-6, "cpp": 50e-6}
    found, vbn = [], None
    for i, l in enumerate(lines):
        t = l.split()
        if len(t) != 4 or not t[0].lower().startswith("i"):
            continue
        val = _num(t[3], params)
        node, sink = (t[2], False) if t[2] in diodes else (t[1], True)
        if node not in diodes:
            continue
        kind = diodes[node][1]
        if sink != (kind == "cpp") or val is None or abs(val - want[kind]) > 1e-3 * want[kind]:
            raise ValueError(f"bias.real: unexpected reference {l!r} on a {kind} diode")
        found.append((i, kind, node))
        if kind == "cpn":
            vbn = node
    if not found:
        raise ValueError("bias.real: no ideal reference source found")
    for i, kind, node in found:
        name = lines[i].split()[0]
        if kind == "cml":
            lines[i] = f"X{name} {node} vgi_bias {supply} serdes_bias_pcopy n=85"
            d = diodes[node][0]
            lines[d] = f"{lines[d].split()[0]} {node} 0 serdes_bias_cml"
        elif kind in ("ctle", "cpn"):
            lines[i] = f"X{name} {node} vgi_bias {supply} serdes_bias_pcopy n=20"
        else:
            if vbn is None:
                raise ValueError("bias.real: a vbp sink without a vbn diode to mirror")
            lines[i] = f"X{name} {node} {vbn} 0 0 serdes_nfet w=5 l=1"
    last = max(k for k, l in enumerate(lines) if l.lower().startswith(".include"))
    have = "\n".join(lines)
    inc = [f'.include "{ROOT / p}"' for p in BIAS_INC if p.split("/")[-1] not in have]
    ref = [f"Xbias_ref bias_vbg bias_i0 bias_i1 bias_i2 bias_i3 vgi_bias {supply} 0 serdes_bias_ref trim={trim}"]
    ref += [f"Vbias_i{k} bias_i{k} 0 0.7" for k in range(4)] + [NODESET]
    lines[last + 1:last + 1] = inc + ref
    return "\n".join(lines) + "\n"


def section(deck: str, process: str, rcorner: str) -> str:
    """Point the model .lib line at the MOS x resistor library section (tt + ll -> ll, ss + hh -> ss_hh)."""
    sec = process if rcorner == "tt" else rcorner if process == "tt" else f"{process}_{rcorner}"
    out, n = re.subn(r'^(\.lib\s+"[^"]+"\s+)(\w+)\s*$', lambda m: m[1] + sec, deck, count=1, flags=re.M | re.I)
    if n != 1:
        raise ValueError("bias.section: no model .lib line")
    return out
