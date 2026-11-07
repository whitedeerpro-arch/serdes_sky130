# WP-004 交接

以 [evidence.json](evidence.json) 中当前工作区输入哈希、连接和实例行号为事实基准。数据经 CMOS→CML 转换器进入四级树；选择来自 250 MHz、500 MHz、1 GHz、2 GHz 时钟。末级为带 A/B 锁存的选择单元；静态理想表不能证明实际动态顺序或跨字不混合。r5_v3 现有测试只用静态字；旧路径的 src250 输入下降沿加 78.3 ps 外推不构成 r5 动态合同。

可参考 `serdes_cmos_dff_reset` 与现有转换器；先测目标负载及 PVT 下 DFF 的 clk→q、建立/保持和转换器有效输入电容，再测实际树允许的字更新窗、位映射与跨字混合。转换器几何尺寸不能代替电容或时序测量。

集成者需决定入口时钟域与有效沿、字延迟、数据有效/启动/复位合同、时钟与数据延迟和抖动预算及验收范围；这些目前未知。本包未选架构、运行仿真或修改电路。

复现：`uv run python verification/work_packages/wp002_tx_ingress.py --output docs/work_packages/deliveries/WP-002`（退出 0）；`uv run python -m serdes_flow.work_packages check WP-002`。改动范围为本交付目录；提取脚本经审阅未修改。建议 reviewer 抽查末级极性、旧激励外推参考和输入哈希，并独立运行检查；检查通过不代表动态设计通过。
