# 版图与物理实现入口（`docs/layout/`）

项目级采用状态统一见 [current.md](../status/current.md)，片级宏观摆位、引脚对齐与阻尼 PDN 方案见 [chip_floorplan_20261123.md](chip_floorplan_20261123.md)。

## 1. 当前 4 Gb/s NRZ SerDes 已签核物理宏清单

各宏目录保留生成器入口、参考网表、提取与物理检查摘要。上层互连、实际去耦几何与可用电气范围查阅[当前状态](../status/current.md)及[执行计划](../status/prelayout_plan.md)。

| 子系统 | 版图入口 |
|---|---|
| **片级整合规划** | [chip_floorplan_20261123.md](chip_floorplan_20261123.md) |
| **数字顶层 v3.1** | [hd_pnr_v3_unified](../../digital/pnr/variants/hd_pnr_v3_unified/serdes_digital_top_v3/summary.json) |
| **TX SST v4.3** | [tx/sst/layout/variants/v4_pdk](../../analog/tx/sst/layout/variants/v4_pdk/README.md) |
| **RX CMOS v2.2** | [rx/cmos_rx/layout/variants/v2_pdk](../../analog/rx/cmos_rx/layout/variants/v2_pdk/README.md) |
| **PLL VCO r6 + PTAT** | [vco/layout/variants/sym9_clean](../../analog/pll/vco/layout/variants/sym9_clean/README.md) · [ptat_bias_pdk](../../analog/pll/vco/layout/variants/ptat_bias_pdk/README.md) |
| **PLL CP v4 & LF v2** | [cp/layout/variants/v4_pdk](../../analog/pll/cp/layout/variants/v4_pdk/README.md) · [loop_filter/layout/variants/fused_pdk](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md) |
| **PLL PFD & SAFF-TSPC ÷8 & `r5` Rx** | [pfd/variants/pdk](../../analog/pll/pfd/layout/variants/pdk/README.md) · [saff_reclock_2g_pdk](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md) · [cml_to_cmos/r5_pdk](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md) |
| **LDO v2_cur & 慢滤波** | [ldo/layout/variants/v2_cur_pdk](../../analog/ldo/layout/variants/v2_cur_pdk/README.md) · [bias_filter_r4_pdk](../../analog/ldo/layout/variants/bias_filter_r4_pdk/README.md) |
| **BIAS v2** | [bias/layout/variants/v2_pdk](../../analog/bias/layout/variants/v2_pdk/README.md) |

## 2. 物理审阅记录与历史归档

- **工程约定**：模块的 `analog/.../layout/README.md` 为稳定入口；`variants/<身份>/` 存放独立参考、提取网表与签核摘要；运行日志、EXT、临时脚本及大波形留在追加式 `results/`。
- **阶段审阅与专题**：[PLL r6 版图推进](pll_r6.md) · [电容融合研究](capacitor_fusion.md) · [四模块阶段验收（2026-11-15）](pll_acceptance_20261115.md) · [PLL 独立审阅](pll_review_20261115.md) · [后续局部复核（2026-11-17）](pll_pending_review_20261117.md) · [Gemini 迁移汇总](gemini_migration_summary.md) · [版图公共工具](../../analog/layout/README.md)
- **已退役旧版版图归档**：[退役索引](../../results/catalog/README.md#退役索引)维护原路径、归档位置及 SHA-256。

## 3. 模拟宏间局部自动绕线

对平坦的 SKY130A Magic 单元，[`route_manhattan.py`](../../verification/layout/route_manhattan.py)按实际金属、过孔和 MIM 占位，在 M3–M5 上搜索正交互连。输入 JSON 给出允许寻路的中心线窗口、各线网的已有接入点和可用层。工具按线长、转弯和过孔开销选路，顺序阻塞或验收失败时逆序重试。每个候选经全规则 Magic DRC、Netgen LVS 和精确端口顺序核对，通过件由运行摘要指向。适用范围为本地短互连。差分匹配、时钟偏斜、IR/EM 与噪声另按相应电气合同验收。[输入范例](../../results/layout/analog_routing_20261125_hskK27/compact6p4_input/job.json)

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
