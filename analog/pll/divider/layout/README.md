# PLL ÷8 与轻 dummy 版图入口

当前原型为 [双翼 prescaler](variants/pdk/README.md)，独立清理候选在 [variants/review_clean/](variants/review_clean/)。布局与寄生后结论见 [review.md](review.md)，不以生成时的 DRC/LVS 摘要替代电气验收。

| 位置 | 职责 |
|---|---|
| [build_prescaler8_pdk.py](build_prescaler8_pdk.py) | r6q 的 h40/h80 latch、三级 ÷2、级间 buffer、本地偏置及轻 dummy |
| [build_divider_pdk.py](build_divider_pdk.py) | 旧叶单元原型，不作为当前完整 ÷8 的入口 |
| [plan/](plan/) | 早期摆位/通道规划，尺寸以选定 `.mag` 为准 |
| [variants/pdk/](variants/pdk/) | 原几何及各叶单元快照 |
| [variants/review_clean/](variants/review_clean/) | 撤除浮空 field-poly 的完整 ÷8 和轻 dummy 候选 |
| [layout_pex/run.py](../tb/layout_pex/run.py) | 2 GHz 实际 buffer 输入＋提取接收器的联合台 |

清理工具 [clean_field_poly.py](../../../../verification/layout/clean_field_poly.py)从独立 EXT 确认浮空岛后创建新几何，重跑 full-rule DRC/LVS，保留原输入和失败尝试；不手工修改提取网表。原生成/检查输出留在新的 `results/` 目录。[固定证据](../../../../results/catalog/pll_layout_review_divider_20261115.json)绑定本轮所有候选和实际运行。
