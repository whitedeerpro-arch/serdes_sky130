# PLL 四模块阶段验收（2026-11-15）

本页与复核命令绑定 11 月 15 日的输入。LF fused 在 11 月 17 日已有新 dummy 几何，更新验收与新证据查[模块审阅](../../analog/pll/loop_filter/layout/review.md)；原命令遇到该输入变化会拒绝复用旧资格。

**LF、divider、sym9 VCO 和 CML→CMOS 的局部几何交付可接受；电气资格按下表限定，尚不构成完整 PLL 签核。** 本次从现行目录重新运行六份几何的全规则 DRC、独立 LVS 和端口检查，全部通过；当前几何/参考与既有测量身份一致，215 份固定证据文件的哈希核对通过。机器记录见[验收索引](../../results/catalog/pll_layout_acceptance_20261115.json)。

| 模块与验收版本 | 布局验收 | 已通过的寄生后局部检查 | 尚未授予的资格 |
|---|---|---|---|
| [LF 原版及 fused](../../analog/pll/loop_filter/layout/review.md) | 通过。电容列与供电分配合理，护环和 dummy 有明确电位，无需继续修几何 | 七个条件的 AC 完整；两版原理图/CPEX 的 100 ns 预充共 28 组满足 ±40 mV 局部包络，最大误差约 1.824 mV | Ci/Rz/供电跟随没有新增容差合同，记 ungraded；完整环路稳定性、PSRR、真实控制端负载及堆叠电容失配未签核 |
| [divider 与轻 dummy 的 clean 版](../../analog/pll/divider/layout/review.md) | 通过局部几何交付。撤除浮空 field-poly，保留有效器件、已接地 dummy 和护环 | CPEX 在 TT 及 FS/1.65 V/85°C/hh 正确 ÷2/÷4/÷8，并驱动实际提取接收器输出 250 MHz | **完整 RC 电气验收保留**。`LAYOUT-PLL-DIV-RC-01` 待版图核查提取层/端子语义、网络简化与供电接入；全量 RC 分支暂停，未确认实际版图失败 |
| [VCO sym9_s32p5_clean＋四缓冲](../../analog/pll/vco/layout/review.md) | 通过局部几何交付。撤除 216 个浮空 poly 岛，差分/四级排布及既有护环保留 | CPEX 两个量程端点约 2.153/1.724 GHz，包住 2 GHz；最小逐周期缓冲摆幅分别约 472/560 mVpp | 固定校准 DC 偏置、5 ns 缓升和启动扰动、每端 30 fF 的局部边界。原生 RC 数值未完成；真实偏置启动、完整码窗/全角、失配和相噪未签核 |
| [C6 CML→CMOS](../../analog/common/cml_to_cmos/layout/review.md) | 通过。模拟/数字分域、护环与已偏置 dummy 合理，未发现应撤除的浮空 poly | 实际 divider CPEX 输入、真实原理图偏置、每端 20 fF 输出负载，在上述 TT/FS 两点反馈为 250 MHz，无漏跳并达到 CMOS 电平 | 仅授予 PLL 反馈用途的局部资格；不扩展为 2 GHz 接收器。原生 RC 的两颗短接 dummy 扩散属性分配待查，全角/噪声未签核 |

## 身份与适用范围

六份现行 `.mag` 和独立参考由[复核脚本](../../verification/analysis/pll_layout_acceptance.py)显式指定，并与先前物理记录的哈希核对；不搜索“最新一次”。新检查只提取器件几何与耦合电容，不运行原生电阻提取或新瞬态。既有电气数字的完整激励、负载、测量窗口、执行回执和失败记录在各模块审阅及其固定 catalog 中。

VCO 的 sym9 开关宽 32.5 µm、融合 MIM bank 和 buffer 负载 L4.22 有独立电气身份；不是采用电路 r6 的 46.5 µm 开关、31 小 MIM 和 L4.14 buffer 的等价几何。本验收接受候选交付，不切换工作修订参数。撤除浮空 poly 后的工艺密度/系统匹配仍需后续处理，不能把 DRC/LVS 通过解释为 DFM 资格。

45 个 PVT 条件及噪声/抖动的项目门槛仍有效。本次局部压力点没有替代这些项目；未测、数值未完成和没有评分合同的量均不记为通过。LF 的 ±40 mV 是沿用 B2 的局部筛查包络，并非新定义的完整 PLL 预充合同。

## 错误大环的处置

错误的 `pll_vco_ring4_r6_pdk` 已退出候选目录，组装生成器、整环导出以及依赖它的顶层摆位脚本/图片/坐标表一并撤销；sym9 规划图也已去掉该错误基准的面积比较。原件移入结果区，逐文件路径和哈希见[撤销记录](../../results/catalog/obsolete_vco_large_ring_20261115.json)。独立 r6 叶单元和历史基线保留。顶层现状见[模块入口](../../analog/pll/top/layout/README.md)，目前没有有效的完整摆位/布线方案。

重新复核时使用新的追加目录：

```bash
uv run python verification/analysis/pll_layout_acceptance.py \
  --output-dir results/layout_review/pll_acceptance_new
```
