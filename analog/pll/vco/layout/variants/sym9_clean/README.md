# sym9 浮空 poly 清理候选

[版图入口](../../README.md) · [审阅报告](../../review.md) · [预览](pll_vco_core_sym9_s32p5_clean.png)。

顶层为 `pll_vco_core_sym9_s32p5_clean`，端口顺序与原 sym9 相同。仅撤除 216 个无接触孔、无器件端子的 field-poly 岛；[清理清单](cleanup.json)记录原输入哈希和每个删除矩形。有效 MOS、MIM、变容管、负载电阻、已接地电阻 dummy、保护环和布线保留。

[物理复核](physical_summary.json)为 DRC=0、LVS 匹配。[原生 RC 摘要](rc_summary.json)只说明分布电阻提取及器件归属检查；其瞬态数值未完成，不能据此标为 RC 性能通过。`_pex.spice` 保留耦合，用于当前两个量程端点回测；`_rcx.spice` 为原生 Magic 近似 RC 诊断快照。

撤除 field-poly 会改变局部工艺密度，尚未覆盖其系统失配影响。后续若需要该密度补偿，应在合法接触与护环空间中重新设计有明确电位的 dummy，不能把窄条画到护环里或只在网表中添接地电阻。
