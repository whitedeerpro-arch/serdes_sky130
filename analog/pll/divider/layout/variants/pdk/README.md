# PLL Divider `/8` & Dummy Load PDK Layout Suite

当前独立结论统一见 [审阅报告](../../review.md)，目录职责见 [模块入口](../../README.md)；本页保留原生成记录。

SKY130 PDK physical layout suite implementing the unmodified schematics in
`analog/pll/divider/spice/{cml_latch,cml_div2,cml_prescaler8}.spice` and
`analog/pll/top/spice/clock_frontend_r6q.spice`.

Built and verified by [`build_prescaler8_pdk.py`](../../build_prescaler8_pdk.py);
build archive (geometry checks only) at `results/layout/pll_divider/20261115T080300Z_prescaler8_j2_sym/`.

## Layout Architecture (Plan J2: Center-Symmetric Dual-Wing + Single Central Grounded Dummy Gate + Merged Resistor Bank)

- **Center-Symmetric Dual-Wing Architecture (`[Left Wing] | Master | Slave | [Right Wing]`, Mirrored Across `x = 0.000`)**:
  - **Center Core (`Master` at `dx = -9.975 µm`, `Slave` at `dx = +9.975 µm`, `mirror_x = True`)**:
    - **Bottom Tail Row (`y = 0.000`)**: `Xtail_M` (`w=3, l=0.5, nf=24`) and `Xtail_S` (`w=3, l=0.5, nf=24`) open their inner guard rings and merge across `x = 0.000`, sharing **one central grounded dummy poly gate (`[-0.250, +0.250] µm`, `G = VSS`)** inside a continuous guard ring (saving 1 dummy gate and 2 vertical guard-ring walls per stage).
    - **Top Load Resistor Row (`y = 25.710 µm`)**: `Xmaster` and `Xslave`'s load resistors merge into a 6-resistor bank `[Rdum_L(-10.640) | Rn_M(-6.660) | Rp_M(-2.220) | Rp_S(+2.220) | Rn_S(+6.660) | Rdum_R(+10.640)]`, and share `Rdum_L(-10.640)` / `Rdum_R(+10.640)` with `pll_div_buffer_pdk`'s `Xr1(-14.620)` / `Xr0(+14.620)` (saving 10 dummy resistors across `prescaler8`).
  - **Symmetric Left & Right Wings (`x < -20.425 µm` and `x > +20.425 µm`)**:
    - **Clock Frontend**: Split symmetrically into Left Wing (`Xsp` at `-21.950, y=0` + `Xfp` folded as `2 × nf=8` at `dx = -22.915, dy = 6.070, 12.640`) and Right Wing (`Xsn` at `+21.950, y=0` + `Xfn` folded as `2 × nf=8` at `dx = +22.915, dy = 6.070, 12.640`).
    - **Interstage Buffer (`pll_div_buffer_pdk` in Stages 2 & 3)**: Split symmetrically into Left Wing (`Xt_L` `w=3, l=0.5, nf=2` at `dx = -25.235, y = 0` + `Xn` `w=3, l=0.15, nf=8` at `dx = -22.915, y = 18.710` + `Xr1` `outp` at `-14.620, y = 25.710`) and Right Wing (`Xt_R` at `+25.235, y = 0` + `Xp` at `+22.915, y = 18.710` + `Xr0` `outn` at `+14.620, y = 25.710`), so `outp -> clkp` (Left Wing) and `outn -> clkn` (Right Wing) are 100% mirror-symmetric local connections within each wing.
    - **Tail Bias (`pll_cml_tail_bias_pdk` in Stage 1)**: Split symmetrically into Stage 1's Upper Left Wing (`Xsink` at `-22.915, y = 18.710` + `Xpd` `w=6, l=0.5, nf=10` at `-21.200, y = 26.200`) and Upper Right Wing (`Xref` at `+22.185, y = 18.710` + `Xpm` `w=6, l=0.5, nf=10` at `+21.200, y = 26.200`).
- **In-Cell Over-the-Cell M3/M4 Routing (`34.80 µm` Uniform Height)**:
  - All 8 horizontal `M3` clock/data/bias tracks (`Y_VBIAS = -2.55 µm`, `Y_VBLOGIC = -1.775 µm`, `Y_CKN = +4.30 µm`, `Y_CKP = +5.20 µm`, `Y_MP = +24.50 µm`, `Y_MN = +25.60 µm`, `Y_QP = +26.70 µm`, `Y_QN = +27.80 µm`) route strictly inside the `VDD` (`+30.90 µm`) and `VSS` (`-3.10 µm`) power rails (`34.80 µm` uniform cell height across the entire pipeline).

## Verified Cells (`DRC = 0`, `LVS = True`, `Property Errors = False`)

| Cell | Ports | BBox Size (µm) | Area (µm²) | Area vs. Plan A+I | Area vs. v1 | Notes |
|---|---:|---|---:|---:|---:|---|
| `pll_frontend_dummy_load_pdk` | 5 (`clkp clkn vbias vdd vss`) | `20.40 × 20.40` | `416.16` | `0.0%` | `-51.4%` | Abutted `80 µm` LVT SF + `4 µm` sink + `64 µm` LVT MOS cap load (`Xdum1..3`) + MOS dummies |
| `pll_cml_tail_bias_pdk` | 4 (`vbias_sf vbias_logic vdd vss`) | `54.79 × 34.80` | `1,906.69` | `(nested)` | `(nested)` | Center-symmetric dual-wing frame nesting 100% into Stage 1 (`Xpd+Xsink` Left Wing, `Xpm+Xref` Right Wing) |
| `pll_cml_latch_h40_pdk` | 9 (`dp dn qp qn clk_track clk_hold vbias vdd vss`) | `21.70 × 34.80` | `755.16` | `-12.8%` | `-47.8%` | Continuous 24f `Xtail` + in-cell port coordinates (`wdata=20, whold=40, wclock=64, wtail=72, R=600`) |
| `pll_cml_latch_h80_pdk` | 9 (`dp dn qp qn clk_track clk_hold vbias vdd vss`) | `21.70 × 34.80` | `755.16` | `-12.8%` | `-47.8%` | `/4` & `/8` latch (`whold=80`, identical `21.70 × 34.80 µm` frame & pin coordinates as `h40`) |
| `pll_cml_div2_biased_h40_pdk` | 10 (`clkp clkn qp qn mp mn vbias vbias_logic vdd vss`) | `54.79 × 34.80` | `1,906.69` | `-25.0%` | `-61.5%` | Center-Symmetric Dual-Wing `/2` stage + 1 shared central grounded tail dummy + 6-resistor bank |
| `pll_cml_div2_biased_h80_pdk` | 10 (`clkp clkn qp qn mp mn vbias vbias_logic vdd vss`) | `54.79 × 34.80` | `1,906.69` | `-25.0%` | `-61.5%` | Center-Symmetric Dual-Wing `/4` & `/8` stage + 1 shared central grounded tail dummy + 6-resistor bank |
| `pll_div_buffer_pdk` | 7 (`inp inn outp outn vbias vdd vss`) | `54.79 × 34.80` | `1,906.69` | `(nested)` | `(nested)` | Center-symmetric dual-wing frame nesting 100% into Stages 2 & 3 (`Xn+Xt_L+Xr1` Left Wing, `Xp+Xt_R+Xr0` Right Wing) |
| `pll_cml_prescaler8_pdk` | 11 (`clkp clkn q2p q2n q4p q4n q8p q8n vbias vdd vss`) | `162.77 × 34.80` | `5,664.40` | **`-45.9%`** | **`-76.1%`** | Center-Symmetric Dual-Wing `/8` Pipeline (`53.99 µm` stage pitch; saves 10 dummy resistors & 3 tail dummy gates) |

Legacy prototype `pll_cml_latch_pdk.mag` (`wclock=24, wtail=12`, from `results/layout/divider_pdk/run3`) is retained alongside the `r6q` candidate cells.

## Reproduction

```bash
uv run python analog/pll/divider/layout/build_prescaler8_pdk.py \
  --output-dir results/layout/pll_divider/prescaler8_new \
  --install-dir analog/pll/divider/layout/variants/pdk
```
