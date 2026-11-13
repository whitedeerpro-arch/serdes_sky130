> **Gemini 来件，候选几何。** 以下原交付说明中的尺寸、器件类型、匹配和压降是作者声明，不是本项目验收结论。采用状态见[版图入口](../../../layout/README.md)；必须对当前设计侧 SPICE 独立做 full-rule DRC、LVS 与端口/器件值复核。

# 低压差线性稳压器与尾流滤波子系统（`common/ldo/layout`）版图设计说明

本目录包含 `common/ldo/spice/`（`ldo_hv18_core_r4.spice`、`pll_supply_hv18_r4.spice`、`pll_bias_filter_r4.spice`、`ldo_power_switch.spice`、`ldo_passives.spice`）中全部 10 个核心与无源宏单元的全定制版图实现（`.mag` 与 `.tcl`）、LVS 参考网表（`*_ref.spice`）及参数化生成脚本 `build_ldo_suite.py`。

## 1. 单元清单与物理指标

| 单元名称 | 对应网表子电路 | 版图尺寸 (µm) | 面积 (µm²) | 关键匹配、功率走线与隔离策略 |
| :--- | :--- | :--- | :--- | :--- |
| `serdes_pll_supply_hv18_r4` | `serdes_pll_supply_hv18_r4` | 436.00 × 124.00 | 54,064.0 | 生产级顶层供电宏：左区 6-bit 分压修调 + 1MΩ/16pF 基准滤波，中区 HV18 核心，右区 100pF 输出去耦阵列 |
| `serdes_pll_supply_hv18_r4_probe` | `serdes_pll_supply_hv18_r4_probe` | 436.00 × 124.00 | 54,064.0 | 双注入环路稳定性测试宏：将 `fb_return` 与 `fb_input` 拆分为独立端口 |
| `serdes_ldo_hv18_core_r4` | `serdes_ldo_hv18_core_r4` | 236.00 × 124.00 | 29,264.0 | 5V 共质心误差放大器（`va` 静默阱）+ `Xoff/Xboff` 关断钳位 + 5V Native 零阈值 `Xcas` (W=2000) / `Xpass` (W=1000) + 叶 MIM `Chv/Ccas/Ccomp` |
| `serdes_pll_bias_lowpass_slow_r4` | `serdes_pll_bias_lowpass_slow_r4` | 106.00 × 104.00 | 11,024.0 | Under-MIM 3D 垂直堆叠：底层 32 段 31.25 kΩ `ppolyres` 蛇形链 + 顶层 4×4 叶 MIM（16 pF，相比旧版 DS 节省 68% 面积） |
| `serdes_pll_bias_lowpass_r4` | `serdes_pll_bias_lowpass_r4` | 106.00 × 104.00 | 11,024.0 | Under-MIM 3D 垂直堆叠：底层 8 段 12.5 kΩ `ppolyres` 蛇形链（100 kΩ）+ 顶层 4×4 叶 MIM（16 pF） |
| `serdes_ldo_power_switch` | `serdes_ldo_power_switch` | 78.00 × 62.00 | 4,836.0 | 背靠背共 `mid` 独立 N-Well 5V PMOS 双向隔离电源开关（`Xa/Xb/Xup`）+ `Xdown` + 1 MΩ `Rkeep` |
| `serdes_ldo_ref_res` | `serdes_ldo_ref_res` | 98.00 × 102.00 | 9,996.0 | 32 段匹配串联 31.25 kΩ 高阻多晶硅阵列（1.0 MΩ，`res_high_po_1p41`） |
| `serdes_ldo_mim16` | `serdes_ldo_mim16` | 104.00 × 100.00 | 10,400.0 | 4×4 物理叶 MIM 阵列（16 × 22.2×22.2 µm = 16 pF，满足 `capm.11` 间距规则） |
| `serdes_ldo_mim50` | `serdes_ldo_mim50` | 254.00 × 124.00 | 31,496.0 | 10×5 物理叶 MIM 阵列（50 × 22.2×22.2 µm = 50 pF） |
| `serdes_ldo_mim100` | `serdes_ldo_mim100` | 254.00 × 244.00 | 61,976.0 | 10×10 物理叶 MIM 阵列（100 × 22.2×22.2 µm = 100 pF） |

## 2. 核心模拟与功率版图优化决策

1. **5V 误差放大器静默阱隔离与共质心匹配（`serdes_ldo_hv18_core_r4` 左区）**：
   - 5V PMOS 器件（`Xpl/Xpr`、`Xpd/Xpt`、`Xp2`）全部置于偏置在 RC 滤波后静默节点 `va`（`Rhv=1k` + `Chv=50p`）的独立 N-Well 中，杜绝 `vin` 高压纹波通过体效应耦合进环路。
   - 输入对 `Xpl/Xpr` 采用 `PL-PR-PR-PL` 共质心排布；偏置镜像 `Xnb/Xnr`、有源负载 `Xnl/Xnm` 以及 1:2 PMOS 镜像 `Xpd/Xpt` 均采用 `A-B-B-A` 共质心交指结构。
   - 完整实现 `r4` 新增的偏置关断钳位管 `Xboff` 与栅极关断钳位管 `Xoff`。
2. **大电流 5V Native 零阈值功率阵列与双环防闩锁（`serdes_ldo_hv18_core_r4` 中区）**：
   - 严格按 `nfet_05v0_nvt` 尺寸将 `Xcas`（`W=2000 µm, L=0.9 µm, nf=200`）拆分为 5 行 × 40 指、将 `Xpass`（`W=1000 µm, L=0.9 µm, nf=100`）拆分为 3 行 × 34 指，每行配置左右 Dummy 栅并由独立重型 P+ 保护环包围，宽 M2/M3 汇流排将满载压降控制在 0.5 mV 以内。
3. **物理叶 MIM 阵列与 3D 垂直堆叠**：
   - 遵循 `ldo_passives.spice` 不使用 `mf` 缩放的约束，全部电容均由 22.2×22.2 µm 物理叶 MIM 构成，M3 下极板接 `vss` 形成天然静电屏蔽层。
