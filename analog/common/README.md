# Shared Analog Primitives (`analog/common/`)

Reusable low-level analog cells and wrappers shared across PLL, TX, and RX.
*(Note: The top-level **BIAS** and **LDO** subsystems live at [`analog/bias/`](../bias/README.md) and [`analog/ldo/`](../ldo/README.md).)*

| Directory | Role |
|---|---|
| [`cml_to_cmos/`](cml_to_cmos/README.md) | Full-speed (`r5_pdk`, v6 CPEX 45/45 & 200-sample MC PASS) and 250 MHz feedback CML→CMOS clock receivers |
| [`devices/`](devices/README.md) | SKY130A MOSFET/resistor/capacitor wrappers & device characterization cards (`gmid/`, `passive_card/`, `mismatch_card/`) |
| [`monitor/`](monitor/README.md) | Auxiliary on-chip comparator & temperature-sensor monitor blocks ([monitor.md](../../docs/design/monitor.md)) |
| [`cml_buffer/`](cml_buffer/) | CML buffer and resistive delay primitives (used by VCO `r6` delay/buffer stages) |
