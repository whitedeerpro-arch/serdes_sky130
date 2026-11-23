# PLL 待提交工作复核（2026-11-17）

本页证据绑定 11 月 17 日的 LF 融合 v1 和全速 CML→CMOS r5 v3。后续修订的独立结果见[融合 LF v2](../../analog/pll/loop_filter/layout/variants/fused_pdk/README.md)、[全速转换 r5 v6](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md)和[当前状态](../status/current.md)。

**新版 LF 的局部回归可接受；r4/r5 全速接收器与纯 CMOS ÷8 作为独立候选提交，未切换 PLL 主线。r5 有明确冷角 RC 功能失败。** 旧三叠层 divider 的 `LAYOUT-PLL-DIV-RC-01` 全量 RC 分支继续暂停。

| 交付 | 复核与决定 | 固定入口 |
|---|---|---|
| LF fused dummy 修订 | 按真实栅长补齐 12 根有偏置 dummy；重建、全规则 DRC/LVS 通过；七点 AC 完整，28 组短预充通过本轮局部筛查；Ci/Rz/供电跟随仍为 ungraded | [模块报告](../../analog/pll/loop_filter/layout/review.md)、[证据](../../results/catalog/pll_pending_lf_review_20261117.json) |
| r4 全速接收器 | 当前几何独立 DRC/LVS 通过，作为 CMOS 候选的历史驱动及 r5 生成器的叶实现依赖；已有 SS 冷角 PEX 失配薄弱点，不授予采用资格 | [候选说明](../../results/catalog/retired_pre_release_20261123.json) |
| r5 全速接收器 | 重建与独立 DRC/LVS 通过，无浮空非器件 poly；CPEX 六点正常，原生 RC 冷角停止翻转，`LAYOUT-PLL-RX-R5-01` 保持 changes requested | [候选说明](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md)、[证据](../../results/catalog/pll_pending_receiver_review_20261117.json) |
| 纯 CMOS ÷8 | 重建与独立 DRC/LVS 通过，无浮空非器件 poly；原有 45 个 CPEX 条件及另 7 条件×CPEX/RCX 的双极性波形全部通过局部频率、占空比、电平和缺/多周期复核 | [候选说明](../../results/catalog/retired_pre_release_20261123.json)、[证据](../../results/catalog/pll_pending_cmos_review_20261117.json) |
| sync2 另一条候选 | 本批暂不提交其电气采用结论：旧报告是 5 个宽 25.8 µm 核心叶，现行 routed 摘要的叶宽为 9.15 µm、完整外框 111.45×81.07 µm，输入身份明显不同 | 保留现行工作文件，继续核对新顶层参考、重建、实际 CPEX 与旧 block-PEX 之间的身份，不能移植旧通过数字 |
| 原生 PLL 验证基础设施 | 接受固定输入、完整终点与锁定测量工具；补拒绝停止参考、修复历史 ISF 尺寸身份；不增加本轮原生 PLL 锁定/噪声通过点 | [工具复核](../verification/pll_review_tools_20261117.md) |

## 性能证据的限度

r5 和 CMOS 的历史执行回执均有完整波形及 deck 哈希，但没有 include 内容哈希。现行几何、参考、独立提取和重建可以核对，不能反向证明当时每个 include 的字节身份。因此保留“观测通过/失败”，不补签运行时来源，也不作为最终全 RC/失配/启动/噪声资格。

r5 七点联调旧记录的 hh/ll 标签没有应用到 deck，实际只是对应 MOS/VDD/温度条件；新 bench 已修正无源角加载。新版物理 MIM/分段电阻与研究原理图也有明确身份差异，详见模块入口。原始报告、失败波形和执行回执没有改写。

纯 CMOS ÷8 为 10 端口 CMOS 输入，需要先在 2 GHz 做电平转换；现行三叠层 CML ÷8 为 11 端口，后接 250 MHz C6。两者不能直接同名替换。面积和功耗比较须包含前置转换器，重新核对 VCO 的实际抽头负载、相位平衡、反馈延迟及完整闭环，不能只引用 CMOS 分频器本身约 1.37 mW 的 TT 功耗。

## 目录与复跑

几何、独立参考、必要预览及小摘要位于 `variants/<身份>/`；当前边界在对应 README。所有新复核、重建、AC/短预充、旧波形重算和源码快照追加至 `results/layout_review/pll_pending_20261117/`，通过固定 catalog 引用；旧数据不覆盖。生成器的新顶层输出目录必须不存在，不能在旧结果中覆盖生成。只读发布器为 [pll_pending_review.py](../../verification/analysis/pll_pending_review.py)。

本批未审阅 LDO/Bias/CP，未重启暂停的 divider 全量 RC，未启动新接收器的 45 点或 MC 扫描。其他未提交工作保留原状，随后按独立主题继续复核，不整包提交。

四批提交与剩余文件清单见[收尾记录](../history/worktree_review_20261117.md)。另已独立确认并提交此前 35 个旧训练资料删除项，修正 README 导航，未删除现行版图检查器或电路源码。
