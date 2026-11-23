# 共享BG电容局部复核

结论与负载边界见[设计记录](../../../../docs/design/bias_cap_review.md)。当前采用网表保持Cc6/Cvbg5/Cvgi2=13 pF；11 pF、Cc4/Rz30k只是独立候选。这里的探针端口只用于测试，所有电源/负载/双注入源都在bench。

`run.py`冻结当前四份电路源、测试脚本、公共库、模型与deck。核心在放大器输出至公共PMOS控制栅处断环，V→I环在电阻顶端至OTA输入处断环；电压/电流双注入后用共享Middlebrook函数合成。不能改为只断核心差分输入的一侧。每个候选五个边界×轻载/分配两负载；`--pilot`仅TT两负载。`stable60`字段是局部规划护栏，不能用作项目功能通过/失败。

```bash
# 准备目录路径由命令打印，复制实际路径继续，不覆盖旧目录
uv run python analog/bias/tb/cap_sizing/run.py --prepare --reduced --variants phys6 cc4 cc3 cc2 bg3 gi1 gi0 cc4_gi1 cc4_r30 cc3_r40
uv run python analog/bias/tb/cap_sizing/run.py --resume results/analog/bias/cap_sizing/<run_id> --workers 2

# 含端头/寄生的四段物理Rz复核；默认不精简PDK，可显式加--reduced
uv run python analog/bias/tb/cap_sizing/run.py --prepare --reduced --variants phys6_rp cc4_r30p
uv run python analog/bias/tb/cap_sizing/dynamic.py --prepare results/analog/bias/cap_sizing/<physical_rz_run_id>
uv run python analog/bias/tb/cap_sizing/dynamic.py --resume results/analog/bias/cap_sizing/<dynamic_run_id> --workers 2
```

先登记名额并查全机进程，全机≤4，本任务上限2。准备/恢复/分析互斥；两种runner都支持`--analyse <目录>`仅重算指标，输出新analysis目录。续跑校验冻结文件和PDK身份，只跳过完整频轴/瞬态终点及匹配deck的工况。初始DC/AC使用nodeset选择工作态；动态启动移除初值，将所有夹具钳位从零斜坡升起。

`dynamic.py`只取父campaign的TT、SS_hh低压冷、FF_ll高压热，始终使用完整PDK。每项两负载×启动/噪声；启动1 µs斜坡、40 µs处±50 mV供电阶跃、60 µs终点。高压点用负阶跃保持范围。噪声是独立纯DC分析，逐谱立即核验实际器件偏置，积分1 kHz–199.526 MHz，尚无独立BG噪声规格。

`resistor_segments.py`冻结安装目录的BGamp原始LVS与参考网表，并比较四段端头与合并长度的电气差异；卡片几何明确写在脚本里，换版图后必须核对几何并另开campaign。它不会修改版图，也不代替完整R/RC PEX。

```bash
uv run python analog/bias/tb/cap_sizing/resistor_segments.py
uv run python verification/analysis/bias_cap_review.py --manifest config/bias_cap_review_evidence.json
uv run pytest tests/test_bias_cap_sizing.py tests/test_feedback.py tests/test_doc_links.py
```

最后的导出只消费固定清单，不自动挑选新运行。物理电容均显式展开1 pF MIM实例；`phys6_rp/cc4_r30p`的Rz各有四段high_po，包含每段端头及模型寄生，尚非版图PEX。五边界筛选、局部启动和噪声没有替代完整PVT、MC或系统启动资格。
