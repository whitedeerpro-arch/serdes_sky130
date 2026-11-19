# LDO r4 PDK-Extracted Layout Variants (`variants/r4_pdk`)

本目录存放由 `analog/common/ldo/layout/build_ldo_pdk.py` 基于 SKY130 官方 PDK 器件生成器（`sky130::*_draw`）构建并独立通过 `verification/layout/check.py`（full-rule DRC = 0、Netgen LVS = MATCH、无属性错误、无悬空节点、端口完整导出）的全套 LDO `r4` 无源滤波、HV18 核心与 PLL 电源顶层宏版图。

## 1. 验证汇总

| 单元名称 | 对应设计子电路 | 尺寸 (µm) | 面积 (µm²) | full-rule DRC | Netgen LVS | 导出端口 | 结构与物理实现要点 |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| `serdes_ldo_ref_res_pdk` | `serdes_ldo_ref_res` | `48.54 × 103.21` | `5,009.8` | `0` | `MATCH` | `a b sub` | 单一共享 P+ 保护环内 `32 × 31.25 kΩ` (`w=1.0, l=97.39 µm`) `res_high_po` 蛇形串联阵列（总阻值 `1.0 MΩ`，面积较旧候选版图缩小 50%） |
| `serdes_pll_bias_lowpass_slow_r4_pdk` | `serdes_pll_bias_lowpass_slow_r4` | `100.18 × 103.21` | `10,339.6` | `0` | `MATCH` | `original filtered vss` | 3D Under-MIM 垂直堆叠：底层居中放置 `32 × 31.25 kΩ` (`1.0 MΩ`) 多晶硅电阻阵列，顶层 M3/M4 覆盖 `4×4` 物理叶 MIM 阵列（`16 pF`，复用 `serdes_ldo_mim16_pdk`） |
| `serdes_pll_bias_lowpass_r4_pdk` | `serdes_pll_bias_lowpass_r4` | `100.18 × 101.70` | `10,188.3` | `0` | `MATCH` | `original filtered vss` | 3D Under-MIM 垂直堆叠：底层居中放置 `4 × 25 kΩ` (`w=1.0, l=78.57 µm`, 总长 `314.28 µm`, `100 kΩ`) 多晶硅电阻阵列，M2 引出至 MIM 下极板外侧后接 M3/M4 `16 pF` 阵列 |
| `serdes_ldo_hv18_core_r4_pdk` | `serdes_ldo_hv18_core_r4` | `348.09 × 250.00` | `87,021.3` | `0` | `MATCH` | `vss out vin off ibias fb ref` | 左列（`88.09 × 250.0 µm`）采用等宽多行共享保护环阵列 + 全指高 3-via1 M2 绑接 + 电源/偏置加宽主干（`vin/mid` 1.2 µm、`va/vss` 1.0 µm）+ 连续 `va` N-Well + 接地 5V P+ 衬底隔离保护条（隔开底部 30 mA 功率级与上方 µA 级误差放大器）。右列（`251.74 × 250.0 µm`）集成 `Xchv` (`50 pF`) 与 `Xccas` (`50 pF`) 物理叶 MIM 阵列 |
| `serdes_pll_supply_hv18_r4_probe_pdk` | `serdes_pll_supply_hv18_r4_probe` | `713.96 × 254.30` | `181,560.0` | `0` | `MATCH` | `t0 t1 t2 t3 t4 t5 vss fb_return fb_input host bg enable vgi vin quiet` | 三列齐平顶层电源宏（44 器件、34 节点、15 端口）：左列（`100.18 × 250.0 µm`）集成 `Xrefres+Xrefcap` (`1 MΩ + 16 pF`)、`Xrefgate/Xinv/Xrefreset/Xcopy` 控制与偏置行、`Xs0..Xs5` 6 位修调开关及底部对齐的 8 路分压电阻阵列（`Xr0..Xrtop`）与 P+ 衬底保护条；中列集成 `Xcore` (`348.09 × 250.0 µm`)；右列集成 `Xcout` (`100 pF` MIM) 及 3D Under-MIM `Xbleed` (`100 kΩ` 泄放电阻) |
| `serdes_pll_supply_hv18_r4_pdk` | `serdes_pll_supply_hv18_r4` | `713.96 × 254.30` | `181,560.0` | `0` | `MATCH` | `t0 t1 t2 t3 t4 t5 vss host bg enable vgi vin quiet` | 闭环生产版 PLL HV18 `r4` 顶层电源宏（44 器件、33 节点、13 端口）：内部闭合 `fb_return` 与 `fb_input` 反馈环路 |

## 2. 复现命令

```bash
uv run python analog/common/ldo/layout/build_ldo_pdk.py \
    --output-dir results/layout/ldo_pdk/<new-run> \
    --install-dir analog/common/ldo/layout/variants/r4_pdk
```
