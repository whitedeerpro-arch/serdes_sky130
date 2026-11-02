"""Resistors of the project cells as real PDK devices, or a cheap corner emulation.

    text = rcorner.to_pdk(deck_text, workdir)               # ideal R -> sky130 high_po (mismatch, ll/hh, TC)
    text = rcorner.emulate(deck_text, workdir, "hh")        # or "ll", or a float scale

to_pdk(): every ideal resistor (<= 10 MOhm) of every included project cell becomes a high_po device
with the same nominal value: R(w, l) ~ (378 + 317 l) / w ohm (w, l in um; passive card, w 1-2 um),
w = max(1, ceil(1012 / R)) so that l >= ~2 um and the contact heads do not dominate, l from the value.
The library section then moves the resistors too (ll / hh / ss_hh ..., *_mm for mismatch), and their
temperature coefficient is the PDK one.  Bench current references stay ideal: for a resistor corner
with constant-swing bias scale them separately (emulate() does both for ideal resistors).

The PDK ll / hh sections move only PDK resistor devices; the project cells use ideal R elements.
emulate() rewrites the deck so that every resistor in every included project cell (files under
analog/) becomes R * k * (1 + tc1 * (T - 27)) and every bench reference current in CURRENTS is divided
by the same factor: the planned reference I = m * Vbg / R uses the CML load resistor type, so the
swing I * R stays put while currents and R * C time constants move (docs/design/bias.md).
Defaults from the passive card (high_po, w 1 um): hh k = 1.125, ll k = 0.875, tc1 = 300 ppm/C.
Rewritten cell copies go to workdir/rcorner_<k>/ and the deck includes those.  Channel models,
capacitors and sources are not touched; recorded boundary conditions keep their ideal termination.
"""
from __future__ import annotations

import re
from pathlib import Path

from .project import ROOT

PRESET = {"hh": 1.125, "ll": 0.875}
TC1 = 300e-6
CURRENTS = ("iref", "ictle")
_INC = re.compile(r'^\.include\s+"([^"]+)"', re.I | re.M)


def _rewrite_cell(text: str) -> str:
    out = []
    for line in text.splitlines():
        t = line.split()
        if t and t[0][0] in "Rr" and len(t) >= 4 and "=" not in t[3]:
            val = t[3][1:-1] if t[3].startswith("{") and t[3].endswith("}") else t[3]
            rest = " ".join(t[4:])
            tc = "" if "tc1" in rest.lower() else " tc1={rcorner_tc1}"
            line = " ".join(t[:3] + [f"{{({val})*rcorner_k}}"] + ([rest] if rest else [])) + tc
        out.append(line)
    return "\n".join(out) + "\n"


def _pdk_cell(text: str) -> str:
    out = []
    for line in text.splitlines():
        t = line.split()
        if t and t[0][0] in "Rr" and len(t) >= 4 and "=" not in t[3]:
            val = t[3][1:-1] if t[3].startswith("{") and t[3].endswith("}") else t[3]
            try:
                big = float(val.lower().replace("g", "e9").replace("t", "e12").replace("meg", "e6").replace("k", "e3")) > 1e7
            except ValueError:
                big = False
            if not big:
                w = f"max(1,ceil(1012/({val})))"
                line = f"X{t[0]} {t[1]} {t[2]} 0 sky130_fd_pr__res_high_po w={{{w}}} l={{(({val})*{w}-378)/317}}"
        out.append(line)
    return "\n".join(out) + "\n"


def _swap_includes(deck: str, dest: Path, rewrite) -> str:
    analog = (ROOT / "analog").resolve()

    def swap(m):
        src = Path(m[1]).resolve()
        if analog not in src.parents:
            return m[0]
        new = dest / src.relative_to(ROOT)
        new.parent.mkdir(parents=True, exist_ok=True)
        if not new.exists():
            new.write_text(rewrite(src.read_text()))
        return f'.include "{new}"'

    return _INC.sub(swap, deck)


def to_pdk(deck: str, workdir: Path) -> str:
    return _swap_includes(deck, Path(workdir) / "pdk_resistors", _pdk_cell)


def emulate(deck: str, workdir: Path, corner, tc1: float = TC1) -> str:
    k = PRESET[corner] if isinstance(corner, str) else float(corner)
    tag = f"rcorner_{k:.4f}".replace(".", "p")
    text = _swap_includes(deck, Path(workdir) / tag, _rewrite_cell)
    lines = text.splitlines()
    for i, l in enumerate(lines):
        t = l.split()
        if t and t[0].lower() in CURRENTS and len(t) == 4:
            lines[i] = f"B{t[0]} {t[1]} {t[2]} I={t[3]}/(rcorner_k*(1+rcorner_tc1*(temper-27)))"
    lines.insert(1, f".param rcorner_k={k} rcorner_tc1={tc1}")
    return "\n".join(lines) + "\n"
