# sym9 原型

[版图入口](../../README.md) · [审阅报告](../../review.md) · [几何视图](views/)。

`pll_vco_core_sym9_s32p5` 为 108.6 × 79.8 µm 的四级环＋四缓冲核，来自明确的 `results/layout/pll_vco/vco_core_sym9_20261115_corner_cap_dum/core_s32p5/`，不是按文件时间选取。独立复制与哈希见 [physical_summary.json](physical_summary.json)。

该候选包含每半节点九块融合 MIM、32.5 µm 总开关宽及 buffer 负载 L4.22，有自己的 `_ref.spice`，与当前采用 r6 并不完全等价。`_lvs.spice` 保留实际器件几何，`_pex.spice` 为含耦合的电容提取。原型的浮空 field-poly 导致工作点奇异矩阵，保留作对照；电气回测采用旁边的 [清理候选](../sym9_clean/README.md)。
