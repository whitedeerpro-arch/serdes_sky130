# Transmitter (`analog/tx/`)

## 1. Active 4 Gb/s Mainline — Zero-CML SST (`sst/`)

- **Directory**: [`sst/`](sst/) (`spice/`, `tb/`, `layout/variants/v4_pdk/`)
- **Design Doc**: [docs/design/tx_sst_v4.md](../../docs/design/tx_sst_v4.md)
- **Architecture**: Static CMOS 16:4 serializer + 4-phase stagger retimers + 28-slice (23 Main + 5 Post-1 FFE) N-over-N **Source-Series-Terminated (SST)** line driver powered by a compact `1.8 V → 0.44 V` sub-regulator (`sst_vdrv_ldo_pdk`).
- **Signoff**: `231.50 × 146.98 µm = 34,025.9 µm²`, 5/5 cells Magic full-rule `DRC = 0`, Netgen `LVS = MATCH`, `pad_p/n = 46.5 / 42.9 fF`, **22/22 RCX** post-layout corners PASS across `C2_loss6` (`4 Gb/s`).

## 2. Legacy CML Reference Subdirectories

Retained for historical traceability and comparison against the original 45-corner CML transmitter (`v3/extra5`):

| Directory | Historical Role | Design Reference |
|---|---|---|
| [`input_register/`](input_register/) | Legacy 250 MHz word-capture & launch-hold block | [tx_parallel_serializer.md](../../docs/design/tx_parallel_serializer.md) |
| [`clock_distribution/`](clock_distribution/) | Legacy CML select-clock tree & buffer sizing studies | [tx_clock_distribution.md](../../docs/design/tx_clock_distribution.md) |
| [`serializer/`](serializer/README.md) | Legacy 16:1 CML current-steering MUX tree & final retime | [tx_final_retime.md](../../docs/design/tx_final_retime.md) |
| [`output_driver/`](output_driver/README.md) | Legacy 100 Ω CML pre-driver + line driver | [tx_output_driver.md](../../docs/design/tx_output_driver.md) |
