# RX CMOS 相位插值器（PI）图集

[返回图目录](../../README.md) · [RX CMOS v2 / 5G 设计文档](../../../design/rx_cmos_v2.md) · [绘图脚本](../../../../verification/plotting/plot_rx_pi_schematic.py)

本目录保存当前纯 CMOS 64 码相位插值器与正交 8 相 `÷2` 的结构说明与内部边沿波形图；端到端签核四合一总图见 [`../rx_cmos_v2_signoff.png`](../rx_cmos_v2_signoff.png)，叠层切片原理图见 [`../../schematics/rx_pi_stacked_slices.png`](../../schematics/rx_pi_stacked_slices.png)。

| 图表 | 用途与内容 |
|---|---|
| [rx_pi_schematic_explained.png](rx_pi_schematic_explained.png) | 2 GHz 64 码纯 CMOS PI（传输门选相 + 高阻多晶/MIM 混合器 + 恢复级 + 正交 `÷2`）电路工作原理解析 |
| [rx_cmos_v2_internal_edges.png](rx_cmos_v2_internal_edges.png) | RX CMOS v2 PI 内部各级节点与 8 相输出边沿时序验证 |
