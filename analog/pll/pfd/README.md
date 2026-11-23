# PFD 鉴频鉴相器

UP/DN 高有效，rst_b 低有效；分别测相差、频差及复位。

状态：已建立 SKY130 静态 CMOS 晶体管级原型，结果见
[PFD 测试记录](../../../docs/history/pfd_cmos_results.md)。

反馈路径为 CML 分频器 → CML/CMOS 时钟接收器 → PFD；参考端按 1.8 V CMOS 输入。
PFD 使用两个上升沿触发、异步低有效复位的静态主从 DFF，D 固定为 1，
UP/DN 同时置位后经实际 CMOS 门延迟产生公共复位。外部 rst_b 为低时覆盖内部控制。
每个 DFF 的主、从锁存器都清零，时钟采用互锁使能，防止复位释放后在同一高电平内重复置位。

`spice/pfd_cmos.spice` 为 `pll_pfd ref fb rst_b up dn vdd vss`，
依赖 `common/devices/spice/{sky130_primitives,cmos_logic,cmos_dff_reset}.spice` 和本目录的 DFF 兼容包装。
`reset_cap=5f` 是复位门负载预算，尚未映射为版图电容器件；所有延迟来自晶体管门，未使用理想时间延迟。
UP/DN 默认各 20 fF 测试负载，实际 CP 负载与最小有效脉宽待联调。
零相差附近保留共同短脉冲；PFD 端口脉冲响应与 CP 有效电荷死区分开测量。

spice/ 保存晶体管或无源实现，behavioral/ 保存行为模型，schematic/ 保存原理图，layout/ 保存版图，tb/ 保存测试。

| 测试项 | 层次 | 收集指标 |
|---|---|---|
| [functional](tb/functional/case.toml) | block | up_pulse_width, dn_pulse_width, frequency_direction, reset_recovery |
| [dead_zone](tb/dead_zone/case.toml) | block | pulse_width_vs_phase, reset_delay, minimum_pulse_width |

结果：`results/analog/pll/pfd/<case>/<run_id>/`，具体测试台为 `tb/functional/tb_pfd_cmos_ngspice.cir.in`。
当前混合分频联调在 `analog/pll/top/tb/hybrid_divider_pfd/`；`divider_pfd/` 保留原全 CML 方案探索。
实际 CP 与闭环尚未实现，最终规格判定仍为 ungraded。
