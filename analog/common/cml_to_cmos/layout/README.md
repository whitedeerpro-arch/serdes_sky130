# PLL 反馈接收器版图入口

当前候选是 [Plan C6](variants/pdk/README.md)。人工布局判断和寄生后边界统一见 [review.md](review.md)，主电路为 [cml_to_cmos_pvt_candidate.spice](../spice/cml_to_cmos_pvt_candidate.spice)。

全速替代研究另见 [r4](variants/r4_pdk/README.md)与 [r5](variants/r5_pdk/README.md)。它们是驱动 CMOS 分频器的独立候选，不自动替换上述 250 MHz 反馈接收器；r5 的冷角原生 RC 功能失败仍开放。[11 月 17 日复核](../../../../docs/layout/pll_pending_review_20261117.md)列出新交付与保留项。

| 位置 | 职责 |
|---|---|
| [build_cml_to_cmos_pdk.py](build_cml_to_cmos_pdk.py) | 实体器件、分域保护环、偏置 dummy 和独立 LVS 参考 |
| [plan/](plan/) | 早期 C2 几何规划，不能作为 C6 的准确端口/外框 |
| [variants/pdk/](variants/pdk/) | C6 几何、参考、提取快照及视图 |
| [联合寄生后台](../../../pll/divider/tb/layout_pex/run.py) | 当前审阅以 ÷8 实际输出驱动接收器，保留 20 fF CMOS 负载 |

工具输出和波形写入追加式 `results/`；本目录的几何摘要不重复维护电气通过数。[固定证据](../../../../results/catalog/pll_layout_review_receiver_20261115.json)绑定本轮真实输入与测试。
