# Receiver (`analog/rx/`)

## 1. Active 4 Gb/s Mainline — Zero-CML CMOS RX (`cmos_rx/`)

- **Directory**: [`cmos_rx/`](cmos_rx/) (`spice/`, `tb/`, `layout/variants/v2_pdk/`)
- **Design Doc**: [docs/design/rx_cmos_v2.md](../../docs/design/rx_cmos_v2.md)
- **Architecture**: On-die `100 Ω` termination + 4-level tunable CTLE → 2 GHz 64-code pure-CMOS Phase Interpolator + 8-phase 1 GHz quadrature ÷2 → 8× quarter-rate Double-Tail dynamic CMOS slicers (4 Data + 4 Edge) → pitch-matched 8→32 static CMOS deserializer (`250 MHz` word clock).
- **Verification** covers same-deck schematic stress cases, schematic MOS45 replay and RX CPEX replay driven by TX→C2 waveforms. The RX bench uses ideal PI clock anchors. [Current verification boundaries](../../docs/status/current.md)

## 2. Legacy CML Reference Subdirectories

Retained for historical comparison against the earlier CML sampler/PI receiver architecture (`ac_trim/c2/W40`):

| Directory | Historical Role | Design Reference |
|---|---|---|
| [`input/`](input/) | Early 50 Ω termination fixture | [rx_frontend.md](../../docs/design/rx_frontend.md) |
| [`ctle/`](ctle/) | Early standalone LVT CTLE characterization (45×4 AC/DC) | [rx_frontend.md](../../docs/design/rx_frontend.md) |
| [`pi/`](pi/) | Legacy current-weighted CML phase interpolator | [rx_pi_sampler.md](../../docs/design/rx_pi_sampler.md) |
| [`sampler/`](sampler/) | Legacy half-rate CML samplers + readout | [rx_pi_sampler.md](../../docs/design/rx_pi_sampler.md) |
| `cdr/` | Analog CDR placeholder (actual RTL CDR lives in `digital/pnr/rtl_v3/`) | [rx_cdr_digital.md](../../docs/design/rx_cdr_digital.md) |
| [`top/`](top/) | Early TX-PCB-RX loaded link integration benches | [rx_pi_sampler.md](../../docs/design/rx_pi_sampler.md) |
