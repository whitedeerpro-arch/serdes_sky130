# CML→CMOS 时钟接收器版图入口（`analog/common/cml_to_cmos/layout/`）

本目录维护片级 2 GHz 全速交流耦合 CML→CMOS 接收器 **`r5_pdk` (v6)** 的 SKY130A PDK 版图生成器与已签核交付物；设计边界见 [clock_receiver.md](../../../../docs/design/clock_receiver.md)，项目级汇总见 [current.md](../../../../docs/status/current.md)。

| 位置 | 职责与状态 |
|---|---|
| [`variants/r5_pdk/`](variants/r5_pdk/README.md) | **现行采用宏（r5 v6）**：`54.49 × 27.60 µm (1,503.92 µm²)`，full-rule `DRC=0`、Netgen `LVS=MATCH`，CPEX 45/45、原生 RCX 6/6、TT/SS 冷 200/200 MC 全通过 |
| [`build_cml_to_cmos_r5_pdk.py`](build_cml_to_cmos_r5_pdk.py) | `r5_pdk` v6 参数化 SKY130A PDK 版图生成器（M1–M4 竖放 MIM 耦合，零 M5 占用） |
| [`build_cml_to_cmos_r4_pdk.py`](build_cml_to_cmos_r4_pdk.py) | 历史 r4 版图生成器参考 |
| [`../tb/r5_pex/verify_r5_pdk.py`](../tb/r5_pex/verify_r5_pdk.py) | `r5_pdk` CPEX / 原生 RCX / 45 角 / 200 样本 MC 验证台 |

早期 250 MHz 反馈接收器版图（`C6`）及历史 r4 交付目录已按 SHA-256 归档于 [`retired_pre_release_20261123.json`](../../../../results/catalog/retired_pre_release_20261123.json)；早期复核固定证据见 [`pll_pending_receiver_review_20261117.json`](../../../../results/catalog/pll_pending_receiver_review_20261117.json)。工具输出和波形均追加写入 `results/`。
