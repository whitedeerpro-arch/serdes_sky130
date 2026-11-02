"""Write simulation waveforms as VCD for GTKWave (analog as real variables, logic as bits / buses).

    from serdes_flow import vcd
    vcd.write(path, t, [vcd.Real("ckq_v", y), vcd.Bit("ckq", y, vdd), vcd.Bus("word", 16, values)])

Real signals are written when they move by more than `tol` (default 1 mV); bits are thresholded at
VDD/2 with +-10 % hysteresis; buses take one integer per time point.  Time unit 1 ps.  GTKWave shows
real variables as analog traces (Data Format > Analog); `tcl_view` builds a startup script that adds
signals in groups and sets the formats.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Real:
    name: str
    y: np.ndarray
    tol: float = 1e-3


@dataclass
class Bit:
    name: str
    y: np.ndarray
    vdd: float

    def levels(self):
        hi, lo = 0.6 * self.vdd, 0.4 * self.vdd
        out = np.empty(len(self.y), dtype=np.int64)
        s = int(self.y[0] > self.vdd / 2)
        for i, v in enumerate(self.y):
            if v > hi:
                s = 1
            elif v < lo:
                s = 0
            out[i] = s
        return out


@dataclass
class Bus:
    name: str
    width: int
    values: np.ndarray        # integer per time point


def _ident(i):
    chars = "".join(chr(c) for c in range(33, 127))
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, len(chars))
        s = chars[r] + s
    return s


def write(path, t, signals, scope="tb"):
    """Write signals sampled at times t (s) to a VCD file; returns the path."""
    path = Path(path)
    tps = np.round(np.asarray(t) * 1e12).astype(np.int64)
    events = {}                       # time -> list of value lines
    head = ["$timescale 1ps $end", f"$scope module {scope} $end"]
    for k, s in enumerate(signals):
        ident = _ident(k)
        if isinstance(s, Real):
            head.append(f"$var real 64 {ident} {s.name} $end")
            last = None
            for tt, v in zip(tps, s.y):
                if last is None or abs(v - last) > s.tol:
                    events.setdefault(int(tt), []).append(f"r{v:.5g} {ident}")
                    last = v
        else:
            if isinstance(s, Bit):
                vals, width = s.levels(), 1
            else:
                vals, width = np.asarray(s.values, dtype=np.int64), s.width
            head.append(f"$var wire {width} {ident} {s.name} $end" if width == 1 else
                        f"$var wire {width} {ident} {s.name} [{width - 1}:0] $end")
            change = np.flatnonzero(np.r_[True, vals[1:] != vals[:-1]])
            for i in change:
                v = int(vals[i])
                line = f"{v}{ident}" if width == 1 else f"b{v:b} {ident}"
                events.setdefault(int(tps[i]), []).append(line)
    head += ["$upscope $end", "$enddefinitions $end"]
    with open(path, "w") as f:
        f.write("\n".join(head) + "\n")
        for tt in sorted(events):
            f.write(f"#{tt}\n" + "\n".join(events[tt]) + "\n")
    return path


def tcl_view(groups, scope="tb", markers=()):
    """GTKWave startup script: groups = [(comment, [(signal, format)])], format in
    'analog' | 'hex' | 'bin' | 'dec' | 'signed' | None; markers = [(name letter, time_ps, label)] in the dump's unit (ps)."""
    fmt = {"analog": "/Edit/Data_Format/Analog/Interpolated", "hex": "/Edit/Data_Format/Hex",
           "bin": "/Edit/Data_Format/Binary", "dec": "/Edit/Data_Format/Decimal",
           "signed": "/Edit/Data_Format/Signed_Decimal"}
    lines = []
    for comment, sigs in groups:
        lines.append(f'catch {{gtkwave::/Edit/Insert_Comment "{comment}"}}')
        names = " ".join(f"{scope}.{n}" for n, _ in sigs)
        lines.append(f"gtkwave::addSignalsFromList [list {names}]")
        for f in sorted({f for _, f in sigs if f}):
            sel = " ".join(f"{scope}.{n}" for n, g in sigs if g == f)
            lines += [f"gtkwave::highlightSignalsFromList [list {sel}]", f"catch {{gtkwave::{fmt[f]}}}",
                      "gtkwave::/Edit/UnHighlight_All"]
    for letter, tps, label in markers:
        lines.append(f'gtkwave::setNamedMarker {letter} {int(tps)} "{label}"')
    lines.append("gtkwave::/Time/Zoom/Zoom_Full")
    return "\n".join(lines) + "\n"
