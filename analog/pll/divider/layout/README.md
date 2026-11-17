# PLL ÷8 与轻 dummy 版图入口

当前原型为 [双翼 prescaler](variants/pdk/README.md)，独立清理候选在 [variants/review_clean/](variants/review_clean/)。布局与寄生后结论见 [review.md](review.md)，不以生成时的 DRC/LVS 摘要替代电气验收。

全速电平转换后接 [CMOS ÷8 候选](variants/cmos_2g_pdk/README.md)是一条独立替代研究，10 端口接口不能直接替换当前 11 端口 CML 分频器。它的重建/双极性波形复核及尚未验收的 sync2 身份差异见[本批复核](../../../../docs/layout/pll_pending_review_20261117.md)；未切换工作修订，原全量 RC 疑点继续暂停。

| 位置 | 职责 |
|---|---|
| [build_prescaler8_pdk.py](build_prescaler8_pdk.py) | r6q 的 h40/h80 latch、三级 ÷2、级间 buffer、本地偏置及轻 dummy |
| [build_divider_pdk.py](build_divider_pdk.py) | 旧叶单元原型，不作为当前完整 ÷8 的入口 |
| [plan/](plan/) | 早期摆位/通道规划，尺寸以选定 `.mag` 为准 |
| [variants/pdk/](variants/pdk/) | 原几何及各叶单元快照 |
| [variants/review_clean/](variants/review_clean/) | 撤除浮空 field-poly 的完整 ÷8 和轻 dummy 候选 |
| [layout_pex/run.py](../tb/layout_pex/run.py) | 2 GHz 实际 buffer 输入＋提取接收器的联合台 |

清理工具 [clean_field_poly.py](../../../../verification/layout/clean_field_poly.py)从独立 EXT 确认浮空岛后创建新几何，重跑 full-rule DRC/LVS，保留原输入和失败尝试；不手工修改提取网表。原生成/检查输出留在新的 `results/` 目录。[固定证据](../../../../results/catalog/pll_layout_review_divider_20261115.json)绑定本轮所有候选和实际运行。
