"""Geometry-aware MIM fusion estimates; dimensions in um, capacitance in fF.

An area match alone does not preserve perimeter, resistance or substrate
coupling. These estimates select physical candidates, not LVS equivalences.
"""
from dataclasses import dataclass
import math
from pathlib import Path
import re

from . import project, spice


@dataclass(frozen=True)
class Mim:
    area_ff_um2: float
    fringe_ff_um: float
    delta_um: float
    sheet_ohm: float
    via_ohm: float

    def cap_ff(self, w, length):
        wc, lc = w + self.delta_um, length + self.delta_um
        if min(wc, lc) <= 0:
            raise ValueError('Nonpositive effective MIM dimension')
        return self.area_ff_um2 * wc * lc + self.fringe_ff_um * 2 * (wc + lc)

    def square_um(self, target_ff):
        if target_ff <= 0:
            raise ValueError('Capacitance must be positive')
        a, b = self.area_ff_um2, 4 * self.fringe_ff_um
        return 2 * target_ff / (b + math.sqrt(b*b + 4*a*target_ff)) - self.delta_um

    def length_um(self, target_ff, width_um):
        """Solve length at a floorplan-selected width; square is not required."""
        if target_ff<=0 or width_um+self.delta_um<=0:
            raise ValueError('Invalid target or width')
        wc=width_um+self.delta_um
        length=(target_ff-2*self.fringe_ff_um*wc)/(self.area_ff_um2*wc+2*self.fringe_ff_um)-self.delta_um
        if length+self.delta_um<=0:raise ValueError('No positive rectangle at selected width')
        return length

    def series_ohm(self, w, length):
        wc, lc = w + self.delta_um, length + self.delta_um
        self.cap_ff(w, length)
        return self.sheet_ohm * lc / wc + self.via_ohm * .56**2 / (wc * lc)


RC_FILES = {
    'tt': 'res_typical__cap_typical', 'hh': 'res_high__cap_high',
    'll': 'res_low__cap_low', 'hl': 'res_high__cap_low', 'lh': 'res_low__cap_high',
}


def _literal(text, name):
    hits = re.findall(r'(?im)^\+?\s*' + re.escape(name) + r'\s*=\s*([^\s;]+)', text)
    if len(hits) != 1:
        raise ValueError('Missing or ambiguous PDK literal: ' + name)
    return spice.spice_number(hits[0])


def installed(rc='tt'):
    """Read the installed r+c coefficient files; no duplicated nominal table."""
    base = project.model_library().parent
    stem = RC_FILES[rc]
    corner = base / 'r+c' / (stem + '.spice')
    linear = base / 'r+c' / (stem + '__lin.spice')
    model = base / 'sky130_fd_pr__model__r+c.model.spice'
    c, lin, mod = corner.read_text(), linear.read_text(), model.read_text()
    result = Mim(_literal(lin, 'camimc') * 1e15, _literal(lin, 'cpmimc') * 1e15,
                 (_literal(mod, 'm3_dw') + _literal(c, 'tol_m3')) * 1e6,
                 _literal(c, 'rm3'), _literal(c, 'rcvia3'))
    return result, [corner, linear, model]


def rounded_square(target_ff, *, grid_um=.005, model=None):
    model = installed()[0] if model is None else model
    side = model.square_um(target_ff)
    choices = [math.floor(side/grid_um)*grid_um, math.ceil(side/grid_um)*grid_um]
    return round(min(choices, key=lambda s: abs(model.cap_ff(s, s) - target_ff)), 6)


def maximum_square_um():
    """Installed PCell parameter guard, not a claim about foundry max area."""
    pdk = project.model_library().parents[1]
    text = (pdk / 'magic/sky130A.tcl').read_text()
    block = re.search(r'proc sky130::sky130_fd_pr__cap_mim_m3_1_defaults \{\} \{(.*?)\n\}', text, re.S)
    if block is None:
        raise ValueError('MIM PCell defaults not found')
    return min(float(re.search(k + r'\s+([\d.]+)', block[1])[1]) for k in ('wmax', 'lmax'))


def require_same_domain(items):
    """MIM electrode orientation and switch domains are part of identity."""
    if not items:
        raise ValueError('Empty fusion group')
    if any(any(item.get(k) is None for k in ('model','upper','lower','body')) for item in items):
        raise ValueError('Missing electrode or body domain')
    keys = ('model', 'upper', 'lower', 'control', 'body')
    signatures = {tuple(item.get(k) for k in keys) for item in items}
    if len(signatures) != 1:
        raise ValueError('Different electrode, control or body domain; fusion changes circuit')
