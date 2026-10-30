# v0.1 design freeze — 2026-10-28

Scope: PLL, startup extension/supervisor, matched clock extraction/distribution and 16:1 CML serializer.
This is a design baseline frozen by user instruction, with independent qualification pending.

Selected serializer: final A/B latch tail width24um and load200ohm, final output mux unchanged12um/400ohm.
The measured selected candidate is 256 payload bits, zero center errors/extra/missing crossings, edge spread0.0419204UI, signed center margin141.38mV.
The historical 1024-bit physical-clock result uses the old latch settings and does not qualify this selected version.
Current source expresses the measured change through default latch_tail_scale=2 and latch_load_scale=0.5; both1 restore the historical behavior.

PLL: 250MHz reference, CML /8, 2GHz local operating point, 50uA CP and nominal6.5kohm/40pF/2pF LF.
Balanced native core retained. Dual-node precharge/startup core and one-hot RTL supervisor are included as a frozen extension.
Reference driver/DAC, frequency/phase measurement frontend, independent watchdog, automatic coarse search and runtime CSR remain separate unimplemented interfaces.
Native cold-start of the extension, PVT/noise/mismatch/extracted timing and true live PLL-to-serializer load integration remain unqualified.

Source authority: frozen SPICE/RTL and parameters. Schematic exports are not authoritative for this release.
Ideal passives, external biases/references and source waveform idealization boundaries remain as described in evidence.
No off-chip line driver/channel or protocol coding is included in this freeze.

MANIFEST.json hashes every packaged input/evidence file; verification must fail if a frozen file changes.
Evidence files retain original run identifiers and waveform hashes; raw runs remain in the project results directory.
Do not infer an unrun corner or a new joint system qualification from directory presence.
