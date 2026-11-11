# DS-02：折指、端口与保护环的复核

你已能画反相器时，先读[折指VAR与保护环](../inverter_folding_var.md)，不必重复覆盖已有T2b成果。本课重点是解释几何收益、补查端口并学习跨环布线。

## 先补查T2b的D端口

本次捕获的`inv_std2`草稿在LVS日志中出现`disconnected node: d`，但仍报`Circuits match uniquely`；提取器件实际接内部漏极网，外部D没有MOS连接。这个具体版本不能仅凭原三字段验收。

```bash
uv run python verification/layout_training/inverter_audit.py <你的inv_std2_lvs.spice> --cell inv_std2
```

该审计只支持平坦、普通1.8V反相器，核对D/G/S/B、N4/P8总宽及L0.15；复杂层次/别名会记未定，不作为通用LVS替代。

在你自己的生成脚本里让D标签落到两管实际共用的漏极金属上。不要新画一个孤立金属小岛再命名D，也不要为了匹配更改参考。重新构建、DRC/LVS及端口审计；看到输出端口确被所有指的D或S实际使用后再交复核。原参考的W4/W8、nf2不变。

## 三个版图问题

1. 两指源—栅—漏—栅—源，为什么能共享D？在同0.85µm漏扩散深度下，核对PMOS输出面积6.8→3.4µm²、周长17.7→9.7µm；分别数实际接D的AD或AS，而非只统计AD。
2. 中间引G及0.6µm源漏主干只是候选。指出poly接触在哪里、M1瓶颈在哪里，以及为什么加宽后tap连接处也必须重查窄缝。
3. 外圈P+环接VSS、阱内N+tap接VDD；G/D用M2跨M1环。逐一指出接触、via和交叉处，说明为什么它不是深N阱隔离。

教材脚本可在独立副本重现几何，不修改你的生产草稿：

```bash
uv run python verification/layout_training/folded_variants.py <DS-01工作目录>
```

交付生成脚本的改动、明确原始/修改后日志和哈希、外部端口使用表、总宽/面积/周长对照、三类寄生的区分。保留“显式PEX电容不等于总Cout”“DRC不检验电流容量”和未做的电气项目。实际生产修改仍按[任务单](../tasks.md)的文件范围执行。
