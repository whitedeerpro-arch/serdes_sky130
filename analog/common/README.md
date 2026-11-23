# Shared Analog Primitives (`analog/common/`)

Reusable low-level analog cells and wrappers shared across PLL, TX, and RX.
*(Note: The top-level **BIAS** and **LDO** subsystems have been promoted to [`analog/bias/`](../bias/README.md) and [`analog/ldo/`](../ldo/README.md).)*

| Directory | Role |
|---|---|
| [`cml_to_cmos/`](cml_to_cmos/) | Full-speed (`r5_pdk`, v6 CPEX 45/45 & 200-sample MC PASS) and 250 MHz feedback CML→CMOS clock receivers |
| [`devices/`](devices/) | SKY130A MOSFET/resistor/capacitor thin wrappers & diffusion geometry helpers |
| [`monitor/`](monitor/) | Auxiliary on-chip comparator & temperature-sensor monitor blocks ([monitor.md](../../docs/design/monitor.md)) |
| `pads/` | Pad / ESD parasitic model stubs |
| [`cml_buffer/`](cml_buffer/), [`cml_mux/`](cml_mux/), [`cmos_to_cml/`](cmos_to_cml/) | CML delay/buffer/MUX/level-shifter primitives (VCO delay stage + legacy CML TX/RX reference) |
