# LDO减容物理候选：b32_h2（紧凑核心 + 完整70pF供电宏）

电路和结果见[减容设计](../../../../../../docs/design/ldo_smallcap.md)。当前目录独立于 `r4`，对应 `b32_h2` 70 pF 减容参数（核心放大器供电 `2 kΩ / 32 pF`、隔离栅滤波 `31.25 kΩ / 16 pF`、密勒补偿 `2 pF`；核心外参考慢滤波 `1.0 MΩ / 16 pF`、输出 `4 pF`、`100 kΩ` 泄放电阻与 6-bit 分压网络，LDO 本体合计 `70 pF`，独立尾偏置 `16 pF` 保持）。

## 交付单元与面积对比

全部 7 个物理单元均通过 `verification/layout/check.py`（`DRC_TOTAL 0`、`LVS_MATCH True`、`LVS_PROPERTY_ERRORS False`、显式外部端口顺序一致）：

| 单元 | 尺寸 (µm) | 面积 (µm²) | 对比基准 | 端口数 |
|---|---:|---:|---|---:|
| `serdes_ldo_hv18_smallcap_pdk` | `248.385 × 210.945` | `52,395.57` | 较初版减容核心（`248.385 × 250.0 = 62,096.25 µm²`）再缩 **−15.6%**；较原 `r4` 核心（`87,021.25 µm²`）缩减 **−39.8%** | 7 |
| `serdes_pll_supply_hv18_smallcap_probe_pdk` | `416.520 × 216.235` | `90,066.20` | 含环路断点探针的完整 70 pF 供电宏；较原 `r4` 供电宏（`708.53 × 256.25 = 181,560.03 µm²`）缩减 **−50.4%** | 15 |
| `serdes_pll_supply_hv18_smallcap_pdk` | `416.520 × 216.235` | `90,066.20` | 闭合反馈环路的完整 70 pF 生产供电宏（与原版比缩减 **−50.4%**） | 13 |
| `serdes_pll_bias_lowpass_slow_r4_pdk` | `100.180 × 103.210` | `10,339.58` | 3D MIM 底板屏蔽下置 `1.0 MΩ + 16 pF` 参考低通滤波 | 3 |
| `serdes_ldo_mim32_pdk` / `mim16_pdk` / `mim4_pdk` | `4×8` / `2×8` / `2×2` | — | 8 行等高匹配核心电容阵列与 `2×2` 4 pF 输出电容叶 | 2 |

关键版图修调：
- **核心纵向等高紧凑化**：将左侧有源列从 `250 µm` 压缩至 `210.95 µm`，与右侧 8 行 `32 pF / 16 pF` MIM 阵列（`195.4 µm`）等高对齐；消除旧版 5 处悬空护环残桩与底部绕行 `350 µm` 的 `casg` M4 大回环，改为顶侧直连并将 `Xrcas` 置于接地 MIM 底板下方。
- **完整三列等高供电宏**：左列叠放 `1.0 MΩ + 16 pF` 3D 参考滤波、启停/偏置镜像与 6-bit 调压电阻阵列；中列放置紧凑 HV18 核心；右列紧凑排布 `4 pF` 输出 MIM 与 `100 kΩ` 泄放电阻，跨列采用正交 M2/M3 通道与 M4 `quiet` 电源干线。

## 预览与追溯记录

- [全套减容版图总览](ldo_smallcap_pdk_overview.png)
- [紧凑减容核心预览](serdes_ldo_hv18_smallcap_pdk.png)
- [完整70pF供电宏（Probe）预览](serdes_pll_supply_hv18_smallcap_probe_pdk.png)
- [完整70pF供电宏（Prod）预览](serdes_pll_supply_hv18_smallcap_pdk.png)
- [4pF输出电容预览](serdes_ldo_mim4_pdk.png)
- [运行摘要与哈希清单](summary.json)

## 适用边界与历史PEX快照

- `*_lvs.spice` 与 `*_pex.spice` 为 Magic 提取网表，`*_ref.spice` 为 LVS 对照网表。核心 `serdes_ldo_hv18_smallcap_pdk` 严格保持 `vss out vin off ibias fb ref` 外部端口顺序，直接兼容 `analog/common/ldo/tb/cap_sizing/run.py` 的 `pex_variant` 包装器；完整供电宏端口顺序严格对齐 `pll_supply_hv18_smallcap.spice`。
- [减容设计文档](../../../../../../docs/design/ldo_smallcap.md)与 `config/ldo_smallcap_evidence.json` 引用的初版 `250 µm` 核心电容 PEX 仿真快照原样保留在 `results/layout/ldo_smallcap/20261114_b32_h2/`，未覆盖任何历史结果。当前提取的 `*_pex.spice` 为纯耦合/对地电容 PEX，不含分布金属电阻、ESD 与封装寄生。
- 生成入口为 [build_ldo_smallcap.py](../../build_ldo_smallcap.py)（默认 `--rhv 2000 --chv 32 --ccas 16 --rcas 31250`）；每次使用新 `results/` 目录验证后再安装。
