# 结果记录格式

JSON 模板不是运行结果。复制到每次运行目录，命名为 run.json 和 metrics.json，再据实填写。

- execution_status：not_run / running / completed / failed。
- measurement_status：not_run / ok / unavailable / error。
- verdict：ungraded / pass / fail。
- value：有限数值；未测得为 null，不使用 0 或 NaN 代替。
- requirement：待确定时为 null；确定后包含指标来源、上下界和单位。
- design_view：behavioral / schematic / extracted。
- 数据集存为 CSV 等文件，datasets 记录路径、列名和单位。
- 产物路径相对运行目录；设计输入记录项目路径、内容哈希或源版本。
- 相噪注明频偏、dBc/Hz、单/双边约定、载波频率和积分范围。
- 抖动注明参考时钟、去趋势、边沿阈值和样本数。
- 判定基于明确规格和测量有效性，不能直接使用仿真器退出码。
