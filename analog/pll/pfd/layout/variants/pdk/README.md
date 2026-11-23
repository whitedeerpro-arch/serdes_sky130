# 标准单元 PFD 候选

入口：[版图目录](../../README.md) · [独立审阅](../../review.md) · [生成器](../../build_pfd_sc_pdk.py)。

| 项目 | 身份 |
|---|---|
| 单元 | `pll_pfd_sc_dly_pdk`，25.25 × 5.94 µm |
| 电路 | [pfd_sc.spice](../../../spice/pfd_sc.spice) 的 `pll_pfd_sc_dly` |
| 端口顺序 | `ref fb rst_b up dn vdd vss` |
| 文件 | 同前缀 `.mag`、`_ref.spice`、`_lvs.spice`、`_pex.spice`、`.png`；[summary.json](summary.json) 是生成时的物理摘要 |
| 原生成记录 | `results/layout/pll_pfd/20261115_sc_pdk_v3/` |

UP/DN 的 DFF 和输出缓冲使用上下镜像的两排标准单元，中央共用 VDD，复位线从中点馈入；十颗 tap 提供体接触。复位检测/延迟逻辑的布置及其耦合并不完全镜像，不能从线长相等推断严格零偏斜。标准单元内部器件及其边缘结构按 PDK 保留，不额外插 MOS dummy。

本目录的 DRC/LVS 只证明物理连接和设计参考匹配；寄生后性能、工具边界与验收结论统一见审阅报告，不称作完整 PLL 签核。
