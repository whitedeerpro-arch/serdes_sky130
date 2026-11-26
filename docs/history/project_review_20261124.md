# SerDes 横向审查与退役记录

2026-11-24。独立复跑确认新版核心装配的 99 条受查信号网、8 条电源网及 12 组去耦阵列连通关系。将同一根去耦接地竖干平移 0.20 µm 后，独立全核心副本的两处 M2 间距标记降为 0，复查连通结果一致。另修复 v3.2 独立 CDR 台沿用旧 PI 极性，以及旧版图复现脚本遗漏后续退役批次的问题。[当前状态](../status/current.md) · [片级集成证据](../../results/catalog/chip_integration_20261124.json)

## 覆盖与抽样

逐层从仓库入口、模块地图、当前状态、执行计划和协作登记下钻到 PLL、TX、RX、Bias、LDO、共享器件、Channel 和 Digital。以 20261124 为种子，在 20 个目录分层内按路径哈希排序，固定抽取 76 项，记录当时各层的候选规模及入选路径。阅读关键段落和输入输出合同。定向检查另覆盖生产 RTL 的 RX 位序、CDR 和顶层联接，SST 与 PI 的 SPICE/版图参考，PLL 反馈链，供电阵列以及工作台的源文件索引。样本包含当前工作树中的未跟踪文件。[抽样路径及规则](../data/project_review_20261124.json) · [模块地图](../overview/development_map.md)

| 范围 | 检查重点 |
|---|---|
| PLL、Bias、HV18 LDO | VCO/调谐边界、÷8 分频、PFD、CP、LF、真实反馈拓扑和启动窗。电源宏的参考网表与生产网表身份 |
| TX、RX、Channel、共享器件 | SST 驱动与局部稳压器、PI 开关与动态采样器、C2 回放边界、CML 历史依赖及 Xschem 入口 |
| 数字与顶层物理 | RTL 清单、监视器、BBPD、RX 字界和 PI 码方向，旧宏及当前 v3.2 物理证据 |
| 配置、验证、结果、文档和工作台 | 固定角点及边界、验证脚本的输入身份、历史记录的适用期、归档和导出入口 |

## RTL 回归和历史版图复现

- **独立 CDR。** 同一测试台比较 v1.0 标签和 v3.2 工作树。旧采样模型在标签上 ±300 ppm 均通过，在现行 RTL 上均触发字边界断言。将采样时刻改为随 CMOS PI 码增大而延后，RTL 的 ±300 ppm 各 400,000 UI 均通过，两点各 19,936 字、0 错字、0 缺口、0 滑移。统一顶层四项短测和旧 v2 字入口两种配置也通过。Icarus 运行判据检查 PASS 字样及 FATAL 文本。复跑使用与 GLS 相同的历史步长，RTL 清单中的 VCS GLS 测试台因 SVA 语法从 Icarus 输入排除。[独立测试台](../../digital/pnr/rtl_v3/tb_rx_cdr_closed_loop_v3.sv) · [数字设计](../design/digital_top_v3.md) · [复跑索引](../../results/catalog/chip_integration_20261124.json)
- **初版 Gemini 来件。** 旧版脚本在 `serdes_bandgap.mag` 处报 `KeyError`。修订后读取各批退役清单，兼容 Bias/LDO 迁移前的 `analog/common/` 路径，核对字节数及 SHA-256 后选取输入。复跑检查 40 份导入 MAG 的端口记录并复现 6 个叶单元 DRC、LVS、端口及抽取结果，原始检查中的失败保持原判。新增回归保护旧路径解析及哈希失配报错。[复现脚本](../../verification/layout/review_gemini.py) · [原始来件入口](../../analog/layout/README.md)

从仓库根目录运行脚本并指定新的结果目录可重放历史版图复核。CDR 独立复跑使用下列 Icarus 命令，频偏参数分别取 `300.0` 和 `-300.0`。

```bash
mapfile -t rtl < <(rg '^digital/.+\.sv$' digital/pnr/rtl_v3/rtl_v3.f | rg -v '/tb_')
scratch=$(mktemp -d)
iverilog -g2012 -s tb_rx_cdr_closed_loop_v3 \
  -Ptb_rx_cdr_closed_loop_v3.OFFSET_PPM=300.0 -o "$scratch/cdr.vvp" \
  "${rtl[@]}" digital/pnr/rtl_v3/tb_rx_cdr_closed_loop_v3.sv \
  digital/rx/rtl/rx_deserializer16.sv
vvp "$scratch/cdr.vvp"
uv run python verification/layout/review_gemini.py \
  --output-dir results/layout/gemini_review/replay_20261124
```

## 退役与入口同步

撤下七份旧 Bias/HV18 版图交付的参考网表副本。每份与其设计侧 SPICE 逐字节相同，归档保留原路径、规范源、大小及哈希。另撤下一份目标已移出源码区且无当前引用的 r6 CML 图别名，保存 Git 链接对象的原始字节及发布标签位置。旧数模变体仍有活跃测试台或复放依赖时保留，例如 TX 时钟状态探测器和历史 P&R v2 输入。v1.0 标签与 v0.1 历史基线本体保留。[副本清单](../../results/catalog/retired_gemini_duplicate_references_20261124.json) · [图别名清单](../../results/catalog/retired_legacy_figure_alias_20261124.json)

项目状态、执行计划、问题入口、模块文档、工作修订、结果索引及静态工作台已共享同一组固定证据。工作台源码读工作树，数字 v3.1 发布源按 `v1.0` 标签定位。旧 P&R v2 面积汇总在 11 月 23 日已有归档收据，现行统一 P&R 的可选旧版对照仍查原路径，重做历史对照须按收据取回该汇总。[主线工作修订](../../config/mainline_working_revision.toml) · [工作台](../../web/design/README.md) · [旧 P&R v2 归档](../../results/catalog/retired_pre_release_20261123.json)

## 结构预判与最小验证

- **八相时钟先减相间耦合。** 独立 Magic 顶层金属提取给出每相 9–23 fF 对地、相邻相约 12–14 fF 互电容。以单极点近似和 0.5–1.2 kΩ 假设电阻代入 `serdes_flow.balance`，相间电容和的差异就可能贡献 2.4–5.8 ps。先把完整互电容矩阵、实际驱动器及 TX/RX 接收负载接入 TT 与低压冷角短台，比较加间距和分层交错，再用时序与开关能量决定是否加屏蔽或平衡负载。[版图复核](../layout/chip_floorplan_20261123.md#八相时钟的顶层寄生)
- **CDR 建立路径上的步进确认。** 02:17 核心复跑所用宏的 RX 慢路径串过 0.989 ns 延时单元和 0.368 ns 缓冲。02:31 后续宏的 RX 字时钟域在 SS 已转正，最慢建立路径转到 `rx_cdr_phase_applied` 寄存器之后，其中一个延时单元为 0.651 ns。先核该分支的建立及最小保持，尝试只调整该分支的延时与摆位。若逻辑自身仍超时，可对确认与未确认并行计算相债高位，将确认选择移到两支末端。用同周期状态等价检查覆盖饱和、回卷及请求握手，再复跑 ±300 ppm、字边界和 PI 独热断言。[数字设计](../design/digital_top_v3.md) · [装配版 STA 索引](../../results/catalog/chip_integration_20261124.json)
- **PDN 逐域核阻尼。** 208 块双层 MIM 瓦片均有实际归属，TT 模型的标称电容合计约 55.4 pF。规划的 761 pF 来自预留面积和电容密度。先对各独立轨用布线、实际瓦片及封装代理算出阻抗峰值，再在 VDD_Q 和高开关电流轨做最小负载阶跃；能同时改善压降和峰值阻抗的布局才值得加瓦片。[装配复核](../layout/chip_floorplan_20261123.md#5-11-月-24-日独立装配复核)
- **÷8 区分迟起与不分频。** SS 冷的 200 样本里有一例在 24 ns 记录内缺 `q8` 升沿。复看波形时 `q4` 已在 21.312 ns 上升，`q8` 在 22.324 ns 有下降沿。先按原种子和分块身份单独延长，检查 `q4`、`q8` 与反馈边沿配对，再决定是否改动 Xtg2 周围的驱动强度。[候选 ÷8 记录](../design/pll_tspc_reclock_divider.md)

## 片级验收缺口

Gemini 已回执三组顶层短接、去耦接通、候选 ÷8、v4.2 短窗及混合链路。新版核心装配仍需跟进本轮的间距交接、全片 LVS/RCX、分域 IR drop 和焊盘/ESD。02:17 复跑所用 GDS 的 SS 最差建立/保持为 −318.4/+29.3 ps，02:31 后续 GDS 为 −198.5/+171.4 ps。两版按 GDS 哈希与时间对应，最终物理版本须重做 STA 及 GLS。[协作回执](../work_packages/collaboration.md) · [待解决问题](../status/open_issues.md)

真实 r5 + SAFF 的 v4.2 记录在预置粗码及 +20 mV 预充边界下局部 3/3 通过。读取三个原波形，按半供电阈值取参考与反馈上升沿，用 `pll_lock.screen` 核 55–140 ns，三点均为 `insufficient_hold_record`。76 ns 的 4 Gb/s 联合链路数据对应旧 CML ÷8 反馈，其中 TT 同 deck 0/80 数据错、0/34 确定边沿错。下一次关键对照是同一反馈、可比负载和实际时基下，先记录完整的 320 ns 保持门槛，再衔接短链路及独立 RTL CDR。整轮复核使用已有模拟波形与独立 Magic/Icarus，新增 ngspice 运行数为 0。[工程锁定判据](../verification/methods.md) · [片级集成证据](../../results/catalog/chip_integration_20261124.json)
