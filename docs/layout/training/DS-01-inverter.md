# DS-01：可直接交给DeepSeek的第一课

你在SKY130 SerDes仓库里担任版图执行者。当前任务是理解并复现一个确定的反相器，再只改善其源漏接触覆盖。任务边界是独立教学目录，ngspice配额为0；不改SerDes采用电路，不提交git，不改其他agent正在做的版图。

先读[教材](../deepseek_training.md)，再做下面的步骤。教材包含原理、层的作用、实际正反例和故障排查；不要只执行命令后写“通过”。

## 固定电路

```spice
.subckt inv_std d g vdd vss
Xn d g vss vss sky130_fd_pr__nfet_01v8 w=4 l=0.15
Xp d g vdd vdd sky130_fd_pr__pfet_01v8 w=8 l=0.15
.ends inv_std
```

单指、µm单位，顺序D/G/S/B；端口顺序`d g vdd vss`。只允许改变接触和相应LI/M1连接；不改有源区/沟道、器件类型、W/L/nf、体端或参考网表。

## 执行

1. 从仓库根目录运行`uv run python verification/layout_training/run.py prepare`，记下打印的完整工作目录。
2. 用`run <工作目录> --view baseline`重建原示例。先手写四张网络的端子连接表，再在提取网表中逐一对应。
3. 阅读`<工作目录>/student/analog/common/layout_practice/build_inv_std.py`。指出阱、有源区、栅、接触、漏极连接和四个端口分别由哪段代码生成。
4. 用`contacts_example.py <工作目录>`学习已验证的接触列解答，再执行`run <工作目录>`。你也可另建新目录自己重做，只改学生构建器；已有编辑时解答不会覆盖。
5. 用`fault-demo <工作目录>`看断开漏极的反例。解释为什么DRC仍为0，而LVS的网络数从4变5。保留检查器真实退出码；教学程序捕获预期失败不等于故障版图通过。
6. 用`verify <工作目录>`确认参考、工具和PDK指纹未变。查看对应`attempts/<id>/summary.json`及日志，完成交付。

以上子命令均指`uv run python verification/layout_training/run.py …`；解答入口是`uv run python verification/layout_training/contacts_example.py …`。每次明确传工作目录，不扫描“最新一次”。

## 文件边界

只编辑`<工作目录>/student/analog/common/layout_practice/build_inv_std.py`，并在`student/`下新建交付说明。生成脚本可以写自己的`.mag`/提取/临时文件；不要手改`.mag`后让下一次构建丢失改动。

`baseline/`、`student/verification/layout/`、两侧参考、PDK和`manifest.json`只读。发生基线校验不通过、工具缺失或输入身份变化时，记录具体路径/错误；不改检查器或参考来消除失败。

## 提交给集成者的内容

在`student/summary.md`手写：

- 你用的完整工作目录、输入清单和原始参考哈希。
- 四张网的连接表，提取NMOS/PMOS的D/G/S/B及W/L。
- 改了哪些几何，为什么连续LI/M1和接触间距必须一起考虑。
- NMOS/PMOS每个源漏区的接触数；栅/体接触另计。
- 原版、接触改进、断线反例三次的明确`attempts/<id>`路径、检查器退出码和原始DRC/LVS字段。
- 图片、构建命令及复建方法；未做电流容量/PVT/时序/噪声验证。

本课验收是理解网络映射、复现正反例、保持参考/工具身份，以及交付可复核证据。布局检查满足不等于模拟性能或流片通过。下一课再按[任务单的T2b](../tasks.md)做折指，总宽必须保持；其他生产模块的工作范围仍由集成者分配。
