# 2026-10-29 SerDes 阶段审阅与结果整理

当前可以收束为 **4 Gb/s 名义条件下的分层功能原型阶段**。PLL/TX 沿用 v0.1 设计基线；RX 已有实际模拟判决、CDR/串并 RTL 及实时双向接口证据。各层按已经运行的边界验收，整个链路尚未作为一个全晶体管电路共同仿真。

| 范围 | 本阶段已有证据 | 入口 |
|---|---|---|
| PLL、时钟分发、16:1 CML TX | 已冻结设计基线、选定末级锁存参数、分层实际电路窗口 | [v0.1基线](design_freeze_v0p1.md) |
| TX输出级、100Ω PCB、RX前端 | 实际驱动/通道/输入加载短窗、CTLE表征 | [加载联调](rx_loaded_link.md) |
| PI、四相CML采样、CMOS读出 | 名义实际MOS短窗、采样与pair重定时 | [采样与控制](rx_sampler_control.md) / [RX阶段](rx_cdr_closed_loop.md) |
| CDR、训练、16位串并 | 10组实际RTL/行为plant长时跟踪，199360个payload字无错字 | [RTL闭环](rx_cdr_closed_loop.md) |
| 实时数模接口 | 实际RTL和MOS PI/CTLE/采样/CMOS闭环192UI，5个payload字无误；固定模拟控制端对照96UI | [实时联调](mixed_signal_cosim.md) |
| 数据记录与复查 | 连续求解、有限波形窗口、进度/ETA；VCD/FST/GTKWave加载与往返转换检查 | [波形入口](../results/acceptance/20261029-rx-functional/README.md) |

此次收口保留三个后续实现边界：物理16UI降速/整字保持及数字时序、PI控制在全部码型下的更新裕量、系统时钟域接入策略。PVT、失配、噪声、版图提取仍为独立阶段；没有把短窗无错字扩展成统计BER结论。生产CDR参数保持原值，192UI接口测试用单独的快速增益覆盖。

## GTKWave查看

从项目根目录运行：

```bash
verification/mixed_signal/view.sh
```

打开预选信号会话，包含 pair/word 时钟、判决、训练/对齐、16位数据、CDR/PI控制和真实模拟窗口。也可直接打开：

```bash
gtkwave results/acceptance/20261029-rx-functional/waveforms/rx_mixed.fst \
        results/acceptance/20261029-rx-functional/waveforms/rx_mixed.gtkw
```

已提供原始数字VCD、合并模拟/数字VCD和FST，没有生成FSDB。本机GTKWave 3.3.103已实际加载180个信号条目，预选20条信号。合并VCD约3.18MB，FST约1.17MB；30条顶层数字信号与原VCD逐事件一致，12条模拟/窗口信号通过FST往返转换检查。格式与模拟/数字查看支持见[GTKWave官方说明](https://gtkwave.github.io/gtkwave/)。

`ANALOG.window_valid=0` 表示模拟波形没有保存，real值写为NaN；不跨空窗延拓。数字波形覆盖完整48ns。保留1fs物理时间精度，1UI=250ps，并有 `ANALOG.elapsed_ui` 读数；标记A为96UI数据段开始，B为首个完整payload字输出。

## 10ns的耗时和大小

目前没有共同包含 PLL＋TX串化/输出级＋PCB＋RX/CDR 的全晶体管实测时间。因此区分本机记录与规划预算：

| 场景 | 本机记录 | 对10ns的含义 |
|---|---|---|
| 当前实际MOS RX＋RTL | 48ns含模型解析约276s；其中连续求解约240s | 求解约50s，加一次模型解析，约1–2分钟 |
| 实际输出级/PCB/RX采样短窗 | 24ns约192s | 同类场景线性折算约80s；不是完整链路实测 |
| 原生PLL取时钟 | 接受640ns检查点约1948s | 平均折算约30s/10ns；该记录近锁初始化，不代表冷启动 |
| 全链路全晶体管 | 未组合实测 | 先留3–10分钟/10ns预算，收敛困难时可能更长 |

这些数字含不同步长、求解器、并发和电路规模，不能简单相加作为承诺。10ns仅40UI，适合局部电气与时序窗口，不能用于验收PLL/CDR完整捕获时间。

输出大小主要取决于保存节点数：当前合并文件的模拟窗口总长约26.25ns，VCD约3.18MB、FST约1.17MB。保持类似信号选择，10ns通常为 **数MB**。若保存全部内部节点，可能上百MB；以5000–10000个接受点、3000个数值信号为例，双精度数组约120–240MB，文本通常更大。这是规模估算，不是已运行的全节点结果。推荐保留电路连续状态，只选择关心的节点与观测窗口。

## 实验归档

整理前文件总量 **4.190 GB**，整理后约 **1.236 GB**，净节省约 **2.954 GB**。392个大文件打包为314份归档；其中16份PWL输入同时保留原路径副本，净移出376个大结果文件。压缩包总量约0.989GB。数值按文件字节计算，后续索引小文件会略增。

已按模块／实验索引 **550个运行目录、63类实验**，另列出失败/未完成、探索、被替代和文档引用项；分类不改变原判定。

归档结构为 `results/archives/<原模块>/<原实验>/<run>.bulk.tar.xz`；常用目录保留输入快照、日志、指标和小表。失败、未完成、被替代实验保留状态与记录，独立标注，不混入当前选定验收项；“文档引用”也不自动意味着规格通过。

每份归档均完整读回并逐成员核对SHA256后才移走大文件。同一归档内两个完全相同的最终checkpoint/波形副本用硬链接去重。冻结版本59个清单文件保持原哈希。恢复工具已经检查普通文件和去重成员，恢复到原路径后可重做旧分析。

另核对12份当前证据/设计清单的716条文件引用：711条匹配，未丢失引用；5条是清理前已存在的前端README/配置/契约历史哈希与后续工作版本不同，原历史哈希保留并单独记录。归档引用均匹配，未发现电路/数值证据因归档改变。详情见[引用核对记录](../results/catalog/evidence_validation.json)。

```bash
verification/results/artifact.sh locate results/某运行/raw/waveforms.tsv
verification/results/artifact.sh restore results/某运行/raw/waveforms.tsv
```

查看[模块／实验索引](../results/catalog/README.md)、[逐文件归档账本](data/results_archive_manifest.json)与[阶段验收数据](data/stage_review_20261029.json)。历史哈希保持原始内容含义，归档只改变存放方式；清理后验证证据时，应同时查询归档定位表。
