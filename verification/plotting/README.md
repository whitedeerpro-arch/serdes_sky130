# 绘图与可视化脚本（`verification/plotting/`）

本目录维护当前 4 Gb/s `v1.0` 与 5 Gb/s Plan-C 核心签核图表和 ISSCC 风格电路示意图的生成脚本。生成图表汇总见 [docs/figures/README.md](../../docs/figures/README.md)；2 UI 眼图显示约定（总宽 2 UI、向右平移 0.5 UI、边界回绕断线，不改变原始测量与判定指标）见 [测量约定](../../docs/verification/measurement_conventions.md#2-ui-眼图显示)。

| 脚本 | 作用与主要输出 |
|---|---|
| [plot_5g_characterization.py](plot_5g_characterization.py) | 绘制 5.0 Gb/s 演进子系统表征汇总与对比图 |
| [plot_stacked_schematics.py](plot_stacked_schematics.py) | 生成 ISSCC 风格叠层切片原理图（[`docs/figures/schematics/`](../../docs/figures/schematics/)：`tx_sst_stacked_slices`、`rx_pi_stacked_slices`） |
| [plot_rx_pi_schematic.py](plot_rx_pi_schematic.py) | 生成 2 GHz 64 码纯 CMOS PI 工作原理解析图（[`rx_pi_schematic_explained.png`](../../docs/figures/rx/pi/rx_pi_schematic_explained.png)） |
| [rx_cmos_v2_signoff.py](rx_cmos_v2_signoff.py) | 从已保存结果生成 RX CMOS v2 四合一签核图（[`rx_cmos_v2_signoff.png`](../../docs/figures/rx/rx_cmos_v2_signoff.png)） |
| [tx_sst_v4.py](tx_sst_v4.py) | 从已保存结果生成 TX SST v4 眼图与 45 角对比图（[`tx_sst_v4_eyes.png`](../../docs/figures/tx/tx_sst_v4_eyes.png)） |
| [tspc_divider_study.py](tspc_divider_study.py) | 生成 SAFF-TSPC ÷8 四架构多角度对比图（[`tspc_reclock_multiangle.png`](../../docs/figures/clocking/dividers/tspc_reclock_multiangle.png)） |
| [saff_reclock_waveforms.py](saff_reclock_waveforms.py) | 生成 SAFF-TSPC ÷8 `v2` 双端原生 RCX 波形图（[`saff_reclock_v2_waveforms.png`](../../docs/figures/clocking/dividers/saff_reclock_v2_waveforms.png)） |

所有绘图脚本只读已有仿真数据或固定几何/网表描述，不自动启动 SPICE 仿真。
