# 粗码上门限与 VCO 实测控制范围

把粗码上门限从码3（VDD−0.41 V）降到码4（VDD−0.44 V），在当前实测数据中仍有 **135/135工况各自存在2 GHz候选码**。这支持继续评估码4；尚未采纳到电路或RTL默认配置。码4改善了[CP静态失配实验](pll_cp_window.md#同样本门限码对照32样本pilot)的上沿余量，同时收窄VCO窗口，必须把两者配对决定。

## 窗口比较

下门限固定为理想0.90 V。芯片组合指MOS×VDD×RC，共45组；温度为−40/27/85 °C。表中数字只计实际电压测点夹住2 GHz、局部Kvco为正的码。

| 上门限码 | 理想上门限 | 各工况存在候选码 | 同一组合三温共用一个码 |
|---|---|---:|---:|
| 3，当前候选 | VDD−0.41 V | 135/135 | 27/45 |
| 4，对照 | VDD−0.44 V | 135/135 | 23/45 |
| 5，对照 | VDD−0.47 V | 135/135 | 19/45 |

码3→4时失去已证实三温共同码的四组为TT/1.65V/ll、SS/1.65V/hh、FF/1.65V/tt、FS/1.65V/ll。各温度仍有候选；这些计数不能证明相邻切码可行或全温无解。控制器本来允许运行中切码，三温固定码只是可用余量的观察量。

![三个上门限的实测候选码数量](../figures/clocking/vco/vco_coarse_control_windows.png)

旧[固定码45/45记录](pll_vco.md#固定码三温补测2026-11-07)使用0.85 V到各工况CP直流上沿的较宽窗口，并包含单独的CP边缘补测。本表使用0.90 V到理想检测门限，以及下面两份明确的数据输入；两种窗口和证据集合不同，不能相互替代。没有找到被括住的共同码只记为缺少证据，不据此宣布电路不可达。

## 输入与插值

本次完成了被中断调谐任务的20个点：FS/ll/1.8V的6点、FS/ll/1.95V的14点。两个续跑deck均正常完成，分别耗时224/497s，波形至24ns。最终汇总有228条完整码曲线；另3条历史额外曲线缺10个未经计划的电压点，单列部分观测，不进入完整曲线矩阵。原计划、旧执行和旧summary保持原样，见[恢复审计](../work_packages/deliveries/vco-fill-resume-audit.md)。

输入为：

- 原工作图：`results/analog/pll/vco/workmap/20261106T035710Z/summary.json`，950条码曲线。
- 完成后的补点：`results/analog/pll/vco/workmap_fill/20261109T044852Z/analysis/20261109T092349.030536Z_0bac2b46/summary.json`，228条完整曲线。

相同工况/码存在完整补点曲线时整条替换原曲线，不混合电压网格或平均不同运行。最终选择1100条曲线；两套输入78个相同电压的重复频率观测差为零。只在相邻实测点之间线性求2 GHz交点，Kvco是该段割线；不外推控制电压，不借邻码温度斜率，不把缺测码当作失败。

## 边界与下一步

电路为r5四位阵列、真实偏置、PDK R tt/hh/ll、四缓冲且每端30 fF。135条件覆盖MOS45×上述RC三段，不含hl/lh；不是实际B2/CP/LF动态加载。当前分析不含门限梯实际误差、比较器失调、CP失配、ctrl−z纹波、决策延迟、噪声或上电，全部为ungraded静态模型证据。

优先用同码本身的实测三温曲线检查相邻切码落点与对边距离，明确标出缺测，取代旧行为模型对单温码借邻码斜率的估计。再把实际门限/比较器和CP静态联合样本叠加，并校准切码后的环路暂态；不先把码4写进默认配置。

## 复算

[小数据](../data/vco_control_windows.json)与[索引](../../results/catalog/vco_control_windows.json)保存135条件、45组三温交集、每个交点的原测量夹区，以及输入/分析器/采集器哈希。复算显式指定输出新文件：

```bash
uv run python verification/analysis/vco_control_windows.py \
  --source results/analog/pll/vco/workmap/20261106T035710Z/summary.json \
  --fill results/analog/pll/vco/workmap_fill/20261109T044852Z/analysis/20261109T092349.030536Z_0bac2b46/summary.json \
  --out results/analog/pll/vco/workmap_fill/20261109T044852Z/analysis/control_windows_recheck.json
uv run python verification/plotting/vco_control_windows.py \
  --analysis results/analog/pll/vco/workmap_fill/20261109T044852Z/analysis/control_windows_recheck.json
```
