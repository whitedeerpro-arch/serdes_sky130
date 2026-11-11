# WP-TX-CM-001：实际负载卡的共模激励与模型误差复核

面向外部DS或其他执行者的只读、离线任务；无需设计电路或跑SPICE。集成者在交付后独立重算，再决定新模型与新增单元卡。

## 目的与边界

判定当前切口共模−25mV扰动，在Xe4/Xout输入端实际留下了多少独立共模激励；定位代理模型的电压误差。FS三级最大沿误差3.13ps，SS电压误差36.13mV，12/18拟合触边，当前模型不选尺寸。低于1ps的SS级联沿误差不能掩盖电压误差或各级抵消。

只读取明确的8点×3电阻实现，窗口3.5–6.4ns。共模仅在e2g_2输入切口施加；不是每一级直接独立施加。数据/bias/VDD都是理想回放，电阻tt；消费方包含当前driver，不能计为完整TX/焊盘资格。

## 输入与工具

- 设计说明：`docs/design/tx_loaded_clock.md`。
- 紧凑电路测量：`docs/data/tx_loaded_clock.json`；索引：`results/catalog/tx_loaded_clock.json`。
- 代理模型及留出：`docs/data/tx_loaded_clock_model.json`；索引：`results/catalog/tx_loaded_clock_model.json`。
- Campaign：`results/analog/tx/loaded_clock_card/20261111T171205.027336Z_8881ed25`。
- 完整独立复核：上述目录的`review/20261111T174430.556183Z_29ee993e/summary.json`。
- 模型原始结果：上述目录的`model/20261111T174505.452906Z_84e06f0b/summary.json`。
- `uv run python`；波形用`serdes_flow.spice.Waves`，带插值端点的统计用`stage_metrics.telemetry`，预测用`cml_dynamic.drive`。可参照`loaded_buffer_model.py`及`tx_loaded_clock_model.py`。

从明确JSON中的`raw`字段打开文件，逐个核对SHA；不要找“最新一次”。三级顺序`e3/e4/c2g`；第i分支对应`e3p{i}/e3n{i}`、`e4p{i}/e4n{i}`、`sp{i}/sn{i}`，外部输入为`ip/inn`。i=1/2/3对应generic/fixed_short/fixed_long。器件余量和功耗在小数据中已经实测，不能称为代理模型输出。

## 工作

1. 每个条件/电阻/输入点，列出三级的**输入**共模均值、最小/最大/pp及差分pp。将共模单独扰动点对基线、组合点对差分单独扰动点配对，报告共模均值变化及波形最大变化。差分与共模相关时如实记录，不把重复时钟周期当独立样本。
2. 复演保存参数下的一步和三级预测。在相同绝对窗口画实测与预测的差分、共模，至少覆盖两角的fixed_long末级；图用ns/mV，保留输入历史，不重置内部级联为实测。先沿用模型1ps网格、留足6.4ns端点，避免改变采样条件后直接宣称误差变好。
3. 对SS说明单步到级联交越误差减小是否与上游误差抵消相符；同时列出差分/共模误差。无法配对的边沿显式失败，不能跳过后取最大值。
4. 区分“已测现象”与“机制假设”。建议下一张卡最少还需独立激励哪个输入；不修改模型、不重新拟合已看过的留出点、不选择新尺寸。

## 交付与验收

输出一个正常`.py`分析脚本和追加式`results/analysis/tx_loaded_cm/<run_id>/`，包含输入路径/SHA、脚本快照、JSON表格与2–4张图；结论简短。不要改现有源码、文档或结果，不提交别人的文件，不启动ngspice。脚本只用已有共享测量，不另写交越/眼图算法。

集成者复查：24分支齐全、输入身份吻合、窗口和单位正确、原始模型误差可复算、失败未剔除、没有把观察写成新设计通过。该工作包完成只消除模型诊断缺口，不等于I-17或SerDes验收完成。
