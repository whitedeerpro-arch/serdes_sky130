# 版图与物理实现入口（`docs/layout/`）

项目级采用状态统一见 [current.md](../status/current.md)，片级宏观摆位、5G Plan-C 全片装配与 2026-11-26 实装金属复核见 [chip_floorplan_20261123.md](chip_floorplan_20261123.md)。

---

## 1. 已签核物理宏与全片装配清单

各宏目录保留生成器入口、参考网表、提取与物理检查摘要；全片级控制连接、Padring/ESD、带载 RCX 与 IR/EM 收口见 [执行计划](../status/prelayout_plan.md) 与 [实装复核](chip_floorplan_20261123.md#10-实装金属与分析缺口复核2026-11-26)。

### 1.1 主推 5.0 Gb/s 双速 Plan-C（`serdes_5g_top_pdk`，`0.6084 mm²`）

| 子系统 | 版图与签核入口 |
|---|---|
| **5G Plan-C 全片装配** | [chip_floorplan_20261123.md（第 9–10 节）](chip_floorplan_20261123.md#9-50-gbs-plan-c-全片物理装配与层级签核2026-11-26) · [build_chip_top_5g_pdk.py](../../verification/layout/build_chip_top_5g_pdk.py) · [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json) |
| **5G 紧缩混合去耦瓦片** | [decap_5g_tiles.py](../../verification/layout/decap_5g_tiles.py)（`20.8 × 17.2 µm`，Direct / Damped / HV33 全 DRC=0） |
| **5G 32-bit 数字顶层 `v4p1`** | [hd_pnr_v4p1_5g_coopt](../../digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json) · [run_v4p1_5g_coopt_pnr.py](../../digital/pnr/run_v4p1_5g_coopt_pnr.py) |
| **5G TX SST v5 & VDRV LDO** | [tx/sst/layout/variants/v5_pdk](../../analog/tx/sst/layout/variants/v5_pdk/summary.json) · [v4p5_pdk](../../analog/tx/sst/layout/variants/v4p5_pdk/summary.json) |
| **5G RX 集成顶层（W3 CTLE + PI v3 + 5G Slicer）** | [rx_top_5g_pdk](../../analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/summary.json) · [ctle_shunt_5g_w3_pdk](../../analog/rx/cmos_rx/layout/variants/ctle_shunt_5g_w3_pdk/summary.json) · [v5g_4ph_v3_pdk](../../analog/rx/cmos_rx/layout/variants/v5g_4ph_v3_pdk/summary.json) · [slicer_5g_pdk](../../analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/summary.json) |
| **5G 八边形 LC-VCO & 双速 A/B ÷8/÷10** | [lc_vco_5g_oct_pdk](../../analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/summary.json) · [ind_oct_2n5_pdk](../../analog/pll/vco_5g/layout/variants/ind_oct_2n5_pdk/summary.json) · [div_ab_5g_v2_pdk](../../analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/summary.json) |
| **HV18 Kelvin LDO & BIAS v2** | [v2_cur_kelvin_pdk](../../analog/ldo/layout/variants/v2_cur_kelvin_pdk/README.md) · [bias/layout/variants/v2_pdk](../../analog/bias/layout/variants/v2_pdk/README.md) |
| **共用 PLL 环路与时钟接收器** | [cp/v4_pdk](../../analog/pll/cp/layout/variants/v4_pdk/README.md) · [loop_filter/fused_pdk](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md) · [pfd/pdk](../../analog/pll/pfd/layout/variants/pdk/README.md) · [cml_to_cmos/r5_pdk](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md) |

### 1.2 无电感对照基线：4.0 Gb/s 环振（`v1.0` / `full_v8`，`0.5084 mm²`）

| 子系统 | 版图入口 |
|---|---|
| **4G 片级规划与 `full_v8` 装配** | [chip_floorplan_20261123.md](chip_floorplan_20261123.md) · [chip_physical_audit_20261126.json](../../results/catalog/chip_physical_audit_20261126.json) |
| **数字顶层 v3.1 / v3.2** | [hd_pnr_v3_unified](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) · [hd_pnr_v3p2_cmos_rx](../../digital/pnr/variants/hd_pnr_v3p2_cmos_rx/serdes_digital_top_v3/summary.json) |
| **TX SST v4.3 & RX CMOS v2.2** | [tx/sst/layout/variants/v4_pdk](../../analog/tx/sst/layout/variants/v4_pdk/README.md) · [rx/cmos_rx/layout/variants/v2_pdk](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) |
| **PLL VCO r6 + PTAT & SAFF-TSPC ÷8** | [vco/layout/variants/sym9_clean](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [ptat_bias_pdk](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md) · [saff_reclock_2g_pdk](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md) · [saff_reclock_2g_v2_pdk](../../analog/pll/divider/layout/variants/saff_reclock_2g_v2_pdk/summary.json) |
| **HV18 LDO v2_cur & 慢尾滤波** | [ldo/layout/variants/v2_cur_pdk](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [bias_filter_r4_pdk](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md) |

---

## 2. 版图工程规范、工具与退役索引

- **目录约定**：模块的 `analog/.../layout/README.md` 为稳定入口；`variants/<身份>/` 存放独立参考、提取网表与签核摘要；运行日志、EXT、临时脚本及大波形留在追加式 `results/`。
- **版图公共引擎与规范**：[版图公共工具](../../analog/layout/README.md) · [模拟版图设计准则与 DRC/LVS 避坑规范](vco_sym9_layout_lessons.md)
- **宏微摆位与端口再分布工具**：[`floorplan_opt.py`](../../verification/layout/floorplan_opt.py)（提供 `.mag`/`.def` 宏微调滑动与朝向优化、零交叉 PAV 端口重分布、跨宏总线交叉/偏斜审计与空闲口袋提取）及片级约束摆位优化器 [`optimize_chip_macro_plan.py`](../../verification/layout/optimize_chip_macro_plan.py)（见 [片级报告第 7 节](chip_floorplan_20261123.md#7-片级约束自动摆位试排)）。
- **已退役旧版版图归档**：[波形归档与历史退役清单](../../results/catalog/README.md#波形归档与历史退役清单)维护原路径、归档位置及 SHA-256；2026-11-15 至 11-17 早期阶段审阅文档归档在 git 历史（`v1.0` / `b10e989`）。

---

## 3. 模拟宏间局部自动绕线

对平坦的 SKY130A Magic 单元，[`route_manhattan.py`](../../verification/layout/route_manhattan.py)按实际金属、过孔和 MIM 占位，在 M2–M5 上搜索正交互连（支持按网线宽、pin-escape 间距、全局禁布与差分软耦合排斥）。输入 JSON 给出允许寻路的中心线窗口、各线网的已有接入点和可用层。工具按线长、转弯和过孔开销选路，顺序阻塞或验收失败时逆序重试。每个候选经全规则 Magic DRC、Netgen LVS 和精确端口顺序核对，通过件由运行摘要指向。适用范围为本地短互连。差分匹配、时钟偏斜、IR/EM 与噪声另按相应电气合同验收。[输入范例](../../results/layout/analog_routing_20261125_hskK27/compact6p4_input/job.json)

```sh
uv run python verification/layout/route_manhattan.py input.mag job.json results/layout/new_run --reference reference.spice
```

5G RX W3 对照先逐字节复现实装 `.mag`，然后只撤掉 CTLE 到采样阵列的两根手工馈线，保留两个监测支线。固定摆位时，自动补线的总长度与手工版相同，互容增加 `0.15 fF`。缩位时，仅移除三个无器件、无过孔的横向条带，再自动补接同一对网。

| 实装或复核候选 | RX 宏宽度 | RX 外框面积 | CTLE 两根馈线总长 | CTLE P/N 直接互容 |
|---|---:|---:|---:|---:|
| 实装手工 | 317.3 µm | 63,269.62 µm² | 37.9 µm | 14.35 fF |
| 保持摆位自动补线 | 317.3 µm | 63,269.62 µm² | 37.9 µm | 14.49 fF |
| 横移 5.3 µm，再自动补线 | 312.0 µm | 62,212.80 µm² | 27.3 µm | 14.79 fF |
| 横移 6.4 µm，再自动补线 | 310.9 µm | 61,993.46 µm² | 25.1 µm | 15.20 fF |

压缩 6.4 µm 的候选把馈线端点水平距离由 13.4 降为 7.0 µm，整宏面积少约 2.0%。Magic 全规则与欧氏间距检查为 0，Netgen 整宏 LVS 匹配，72 个端口顺序一致。东侧等端口随压缩迁移，接入片顶前应复查新坐标、带载眼图及电源路径。独立构造的阻塞试例中，程序用一段 18 µm 的 M5 和两个 via4 跨过 M3/M4 屏障，全规则 DRC 为 0，Magic 提取两端同网。[复核数据](../../results/layout/analog_routing_20261125_hskK27/summary.json) · [版图对照](../../results/layout/analog_routing_20261125_hskK27/rx_route_overlay.png)
