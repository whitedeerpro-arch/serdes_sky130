# TX guard 时序可行性图：交付

10 fF 负载下，两个 SS 库的四种映射均有负 setup 最小 slack；四个库的 hold 最小 slack 均为正。结果是未评级的探索性 STA，不是签核。

`verification/plotting/tx_ingress_timing.py --collect` 从固定归档 `results/digital/tx/ingress_timing/20261107T052347Z` 的 16 份报告分别解析 SETUP、HOLD 段中真实最差 slack 及起终点，逐项与 summary 对照；数据记录各日志和 summary 的 SHA-256。无参数运行只读 `docs/data/tx_ingress_timing.json` 重绘，不读取 STA 日志，不调用仿真或 STA。绘图使用真实最小 slack，而非正裕量被截为零的 WNS。

```bash
uv run python verification/plotting/tx_ingress_timing.py --collect
uv run python verification/plotting/tx_ingress_timing.py
```

范围是暂定 4 ns 时钟、外部 setup 0.5 ns、标签 1.3 ns 预算和每输出 10 fF；SS 库为 1.60 V，不等于规格的 1.65 V，四库不代表 45 PVT。OpenSTA 的 default operating condition 警告仍未解释，max capacitance 规则检查状态未知。未包含提取后的模拟接口、寄生、CDC、blanking 和复位恢复/移除。候选映射尚未采用。
