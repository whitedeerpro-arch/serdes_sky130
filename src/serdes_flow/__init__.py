"""Shared simulation flow and measurements for the simple_serdes project.

Modules:
    project  - project root, tool and PDK locations from config/*.toml
    corners  - the 45-condition PVT grid and condition tags
    spice    - testbench rendering, ngspice runs, waveform loading
    waves    - crossings and averaging on sampled waveforms
    serial   - training-aligned bit sampling, margin and edge spread
    clock    - frequency, period, duty cycle and relative phase of clocks
"""
