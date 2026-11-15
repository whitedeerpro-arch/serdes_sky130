# ÷8 与轻 dummy 清理候选

[模块入口](../../README.md) · [独立审阅](../../review.md)。

`pll_cml_prescaler8_pdk_clean` 与 `pll_frontend_dummy_load_pdk_clean` 分别撤除 138/12 个非器件、无接触孔的浮空 field-poly 岛。每个单元的 `_cleanup.json` 记录删除坐标与原始哈希，`_physical.json` 记录新几何的独立 DRC/LVS，参考仅改顶层名。有效器件、已接地的中央 dummy、负载电阻 dummy 和保护环保留，外框保持 162.77 × 34.80 µm / 20.40 × 20.40 µm。

`_pex.spice` 为保留耦合的电容提取快照；`_rcx.spice` 仅为原生 RC 诊断，电气通过边界查模块报告。生产参数和旧原型均未自动切换。
