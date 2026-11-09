# 公共数字监测单元

通用的慢速监测/校准积木，与具体模块解耦：只接时钟、复位、比较器输出和参数，不含任何 PLL/RX 常数。
使用方（如 PLL 粗码控制）在自己的 RTL 里例化并给参数。配套模拟部分见 [analog/common/monitor](../../analog/common/monitor/README.md)，
整体说明见 [监测工具包](../../docs/design/monitor.md)。

| 模块 | 作用 | 接口要点 |
|---|---|---|
| [mon_sync](rtl/mon_sync.sv) | 多级同步器 | 只用于彼此时序无关的单比特或握手翻转位 |
| [mon_freq_meter](rtl/mon_freq_meter.sv) | 频率计：`window` 个参考周期内数被测时钟上升沿 | 被测时钟异步、可停；结果误差 ±1；`timeout` 内无回应给 `stalled` |
| [mon_persist](rtl/mon_persist.sv) | 持续性滤波：输入在 N 个采样点连续不同才改输出 | 输入须已同步；对称 |
| [mon_sar](rtl/mon_sar.sv) | 逐次逼近：W 位门限码对外部比较器求值 | 比较器异步（内部同步）；门限须随码单调上升；`settle` 个周期等模拟建立；给 `under`/`over` |

测试（仓库根目录）：

```sh
for t in freq_meter persist sar; do
  iverilog -g2012 -s tb_mon_$t -o /tmp/mon_$t.vvp digital/common/rtl/*.sv digital/common/tb/tb_mon_$t.sv && vvp /tmp/mon_$t.vvp
done
verilator --lint-only -Wall --top-module mon_freq_meter digital/common/rtl/mon_sync.sv digital/common/rtl/mon_freq_meter.sv
```

- `tb_mon_freq_meter`：被测周期 0.5 / 3.47 / 4.0 / 4.016 / 4.6 ns、窗口 64–512、四个随机相位，计数都在理想值 ±1 内；停钟给 `stalled`，恢复后正常。
- `tb_mon_persist`：N = 5 时 1–4 次的抖动不改输出，持续变化在第 5 次改。
- `tb_mon_sar`：行为比较器（门限 0.5 + 0.1·码，响应 30 ns），40 个输入（含低于、高于量程）结果和标志都正确。

Icarus 行为检查与 Verilator lint 不等于 SKY130 映射后的时序/CDC 签核。
