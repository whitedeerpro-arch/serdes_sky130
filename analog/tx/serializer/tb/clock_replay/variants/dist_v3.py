"""Compatibility shim re-exporting ``analog/tx/clock_distribution/spice/tx_clock_dist_v3.py``."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from serdes_flow.project import ROOT

_CANONICAL = ROOT / "analog/tx/clock_distribution/spice/tx_clock_dist_v3.py"
_SPEC = importlib.util.spec_from_file_location("tx_clock_dist_v3", _CANONICAL)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)

INCLUDES = _MOD.INCLUDES
DEFAULT = _MOD.DEFAULT
PRESETS = _MOD.PRESETS
resolve = _MOD.resolve
netlist = _MOD.netlist
probe_vectors = _MOD.probe_vectors

if __name__ == "__main__":
    text = netlist(resolve(sys.argv[2] if len(sys.argv) > 2 else {}))
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text)
    else:
        print(text)
