# PLL 环路滤波器版图入口

原 18-MIM 与堆叠融合方案是两份独立候选；人工布局判断和寄生后结论统一见 [review.md](review.md)。当前采用参数仍查 [环路设计](../../../../docs/design/pll_loop.md)，不由面积或 DRC/LVS 自动切换。

| 位置 | 职责 |
|---|---|
| [build_lf_pdk.py](build_lf_pdk.py) / `variants/pdk/`（已归档） | 原 18 个 MIM1、Rz 与双节点预充 |
| [build_lf_fused_pdk.py](build_lf_fused_pdk.py) / [variants/fused_pdk/](variants/fused_pdk/README.md) | 六站点 MIM1＋MIM2 叠层、独立参考 |
| [plan/](plan/) | 摆位规划，不代表已完成跨块 ctrl 线 |
| [layout_pex/run.py](../tb/layout_pex/run.py) | AC、预充分别执行；每次输出到新的结果目录 |

统一使用 `.mag`＋`_ref.spice` 指定被审几何；`_pex.spice` 指电容及实际器件几何，`_rcx.spice` 指原生 Magic 近似分布 RC。实际 EXT、日志、AC 表和波形留在 `results/`；[固定证据](../../../../results/catalog/pll_layout_review_lf_20261115.json)连接原始运行，不按“最新一次”查找。

```bash
uv run python analog/pll/loop_filter/tb/layout_pex/run.py \
  --physical-dir results/layout_review/pll_20261115 \
  --output-dir results/layout_review/lf_ac_new --kind ac
uv run python analog/pll/loop_filter/tb/layout_pex/run.py \
  --physical-dir results/layout_review/pll_20261115 \
  --output-dir results/layout_review/lf_precharge_new --kind precharge \
  --precharge-ns 100 --hold-ns 50
```

短预充卡与长保持不同。不能将前者通过写成任意长的泄漏/保持或实际 PLL 预充通过；长窗数值失败留在报告。
