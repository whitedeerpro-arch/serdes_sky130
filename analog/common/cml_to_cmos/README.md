# CML → CMOS 时钟接收器（`analog/common/cml_to_cmos/`）

用于将 VCO / CML 差分时钟转换为轨到轨 CMOS 时钟的接收器模块。详细分析与历史演进见 [clock_receiver.md](../../../docs/design/clock_receiver.md)，项目级采用边界见 [current.md](../../../docs/status/current.md)。

## 现行电路与版图入口

| 文件 / 目录 | 角色与状态 |
|---|---|
| [`spice/cml_to_cmos_r5.spice`](spice/cml_to_cmos_r5.spice) | **主线片级 2 GHz 全速 AC 耦合接收器（r5 v6）**；对应版图 [`layout/variants/r5_pdk/README.md`](layout/variants/r5_pdk/README.md)（`54.49 × 27.60 µm`，DRC=0/LVS=MATCH，CPEX 45/45、原生 RCX 6/6、TT/SS 冷 200/200 MC 全通） |
| [`spice/cml_to_cmos_pvt_candidate.spice`](spice/cml_to_cmos_pvt_candidate.spice) | 4G PLL v4 发布闭环台冻结前端使用的 250 MHz ÷8 反馈接收器 |
| [`spice/cml_to_cmos_r4_v4.spice`](spice/cml_to_cmos_r4_v4.spice) · [`spice/cml_to_cmos.spice`](spice/cml_to_cmos.spice) | 历史 r4 / 早期直流耦合 CML→CMOS 接收器参考 |
| [`layout/README.md`](layout/README.md) | PDK 版图生成器（`build_cml_to_cmos_r5_pdk.py`、`build_cml_to_cmos_r4_pdk.py`）与物理交付索引 |
| [`tb/r5_pex/verify_r5_pdk.py`](tb/r5_pex/verify_r5_pdk.py) | `r5_pdk` 后仿验证脚本（6 角 CPEX/RCX、45 角 PVT、200 样本 MC 与 ÷8 冷启动链） |

## 适用边界

- `r5` 采用片上 MIM 交流耦合（`XCac_p/n`），适用于连续高速时钟（`≥ 1 GHz`），不可用于直流静态数据电平转换；主线接收端数据采样已完全采用纯 CMOS Double-Tail 采样器（见 [rx_cmos_v2.md](../../../docs/design/rx_cmos_v2.md)）。
- 依赖 [`../devices/spice/sky130_primitives.spice`](../devices/spice/sky130_primitives.spice) 与 SKY130A 模型库；运行产物追加写入 `results/analog/common/cml_to_cmos/`。
