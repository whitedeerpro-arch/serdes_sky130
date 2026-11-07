# 波形显示

[TX完整入口](../../docs/figures/tx/ingress/README.md)：`tx_parallel_serializer.py --collect <campaign>`可重复采集固定动态点，独立重读raw核对逐位/映射；眼图保留最差采样位，pad/remote明确为比较screen。`tx_ingress_timing.py --collect`核对固定STA报告，无参数从小JSON重画；均不启动仿真。

[当前时钟链路图集](../../docs/figures/clocking/README.md)：`uv run python verification/plotting/current_clocking.py` 从已入库的小数据快照重画 7 组图；加 `--collect` 从显式列出的原始 campaign 采集。只读历史仿真，来源和测量代码哈希写入快照与结果索引。

当前2UI眼图显示约定见 [配置](../../config/eye_display.toml)：横向平移0.5UI，中央一个完整眼、左右各半眼。重排原绘图采样点，并在坐标回绕处断线；原始波形、训练延迟、UI、采样点和判定指标不变。

[TX PVT显示器](tx_pvt_eye_display.txt)从已有结果重画当前两组眼图。历史运行目录内的绘图程序仍保留原来的视图，不批量改写历史实验。
