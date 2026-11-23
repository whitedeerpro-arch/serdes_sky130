"""PVT conditions.

The project grid is 5 MOS corners x 3 supplies x 3 temperatures = 45
conditions; all of them must meet spec (see docs/overview/spec.md).  Tags
follow the existing results naming, e.g. ``ss_v1650_t-40``.
"""
import re
from dataclasses import dataclass
from itertools import product

PROCESS = ("tt", "ss", "ff", "sf", "fs")
SUPPLY_V = (1.65, 1.8, 1.95)
TEMP_C = (-40, 27, 85)


@dataclass(frozen=True, order=True)
class Condition:
    process: str
    supply: float
    temp: int

    @property
    def tag(self) -> str:
        return f"{self.process}_v{round(self.supply * 1000)}_t{self.temp}"

    def __str__(self) -> str:
        return f"{self.process.upper()}/{self.supply:.2f} V/{self.temp} °C"

    @classmethod
    def parse(cls, tag: str) -> "Condition":
        m = re.fullmatch(r"(tt|ss|ff|sf|fs)_v(\d+)_t(-?\d+)", tag)
        if not m:
            raise ValueError(f"not a condition tag: {tag!r}")
        return cls(m[1], int(m[2]) / 1000, int(m[3]))


NOMINAL = Condition("tt", 1.8, 27)


def grid45() -> list[Condition]:
    return [Condition(p, v, t) for p, v, t in product(PROCESS, SUPPLY_V, TEMP_C)]


# Conditions that have repeatedly been the weakest for the CML circuits so far:
# low supply with slow-NMOS corners, hot and cold.  Use them as the quick
# regression set before spending a full grid.
STRESS = [
    NOMINAL,
    Condition("ss", 1.65, -40),
    Condition("ss", 1.65, 85),
    Condition("fs", 1.65, -40),
    Condition("fs", 1.65, 85),
    Condition("ff", 1.95, -40),
]


def boundary_first(conds: list[Condition]) -> list[Condition]:
    """Expected-weakest first: STRESS members, then low supply, slow-NMOS corners, extreme temperatures.

    Run order only (a long campaign that stops early has its boundary answers); results are
    independent of the order.
    """
    proc = {"fs": 0, "ss": 1, "sf": 2, "tt": 3, "ff": 4}
    temp = {85: 0, -40: 1, 27: 2}
    return sorted(conds, key=lambda c: (c not in STRESS, c.supply, proc[c.process], temp.get(c.temp, 3)))
