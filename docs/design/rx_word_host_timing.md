# RX 字路径的前版图时序初查

**加入时序目标和扁平化后，TT的本域setup可满足假定的4ns周期，两个SS库角仍有负裕量。** 本轮是`rx_word_map → rx_word_align16 → rx_async_word_fifo`的可行性初查，不是物理CDC或系统时序签核。

## 实现与约束

[运行器](../../verification/digital/rx_word_host_timing.py)冻结四个RTL文件、Liberty、工具、映射脚本、网表和SDC。默认映射证据为`results/digital/rx/word_host_timing/20261112T103137.520882Z_e71d48db/summary.json`，时序映射证据为`20261112T153605.802409Z_b8ed73be/summary.json`，索引见[结果目录](../../results/catalog/rx_word_host_timing.json)。两项测试检查负裕量保留、无路径拒绝及库单元面积缺失拒绝。

先用Yosys/TT库默认综合、`dfflibmap`和`abc -liberty`映射，再比较`--mapping abc_timing_flat`：扁平化、`synth -noabc`、单次Liberty ABC，设置4000ps目标、buf_1驱动及10fF负载。两份网表分别由OpenSTA检查四角，RTL和STA边界相同。该比较同时改变映射流程与层次，不把改善归因给其中单一因素；两种映射仍不能证明任何合理实现都无法满足SS要求。

word与host分别假定4ns周期、0.1ns时钟转换时间、0.05ns setup/hold不确定度；输入max/min延迟为0.2/0.05ns，输出为0.5/0ns，输出负载10fF。`phys`及`training_enable`属于word域，`host_ready`属于host域。两域独立，本地检查不依赖它们的相位关系。

两域复位与online网络在稳态强制为高，避免将启动recovery路径混作普通数据setup；启动/复位释放另行未定级。没有全局异步时钟分组或跨域false path，跨域报告保留但不评级。

## 结果

| Liberty角点 | 默认Word / ns | 默认Host / ns | 时序映射Word / ns | 时序映射Host / ns |
|---|---:|---:|---:|---:|
| TT 25°C / 1.8V | +0.342 | −0.476 | +0.566 | +0.906 |
| SS −40°C / 1.60V | −5.118 | −5.875 | −4.278 | −3.055 |
| SS 100°C / 1.60V | −3.547 | −3.909 | −3.156 | −1.633 |
| FF −40°C / 1.95V | +1.787 | +0.857 | +1.902 | +1.862 |

两种映射四角本地最差hold均为正。默认映射最差word路径在对齐器内部，最差host路径为FIFO读指针到`host_data[0]`的组合读出。默认映射1211个单元、库面积和约16616µm²；时序映射1265个单元、约16058µm²。没有布线、时钟树、填充或物理寄生。

## 适用范围与后续

1.60V/25°C库点与项目1.65V/27°C不同，两个SS库还分别使用−40/100°C；这不是项目45条件覆盖。检查针对默认参数、复位完成的稳态本域数据路径，未保证实际host负载与接口时序。

Gray总线到首级同步器的最大延迟/跨位偏斜、同步器放置及MTBF、异步读数据稳定窗口、复位recovery/removal、物理读出到word域的捕获和真实布线寄生仍开。更好的组合映射若仍不足，再按关键路径分离训练检测与数据对齐、比较FIFO读出流水或地址编码；修改必须保持连续吞吐、停顿稳定、满空信用与复位纪元语义。

```bash
uv run python verification/digital/rx_word_host_timing.py
uv run python verification/digital/rx_word_host_timing.py --mapping abc_timing_flat
uv run pytest -q tests/test_rx_word_host_timing.py
```

运行器创建新结果目录，不覆盖本轮证据。不能通过放宽周期、屏蔽本域数据路径或把跨域路径标成通过来关闭当前问题。
