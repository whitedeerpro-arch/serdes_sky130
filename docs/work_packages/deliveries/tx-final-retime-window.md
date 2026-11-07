# 末级保持窗口：局部电压回放

FS 两个事件中，g3_0 向目标极性的交越分别晚于原本地 A 关闭沿 6.36 ps（bit 48）和 5.15 ps（bit 104）；TT 对应为提前 48.0 和 48.4 ps。将记录的 c2g 整体后移 40 ps 时，FS 两事件在参考关闭沿后 200 ps 的目标极性保持电压由零偏移的 47.9/54.3 mV 变为 234.4/240.7 mV。固定源训练延迟加同一命令偏移得到的输出采样分别为 132.7/182.2 mV，零偏移为 19.3/68.0 mV。这支持进一步检查末级建立窗口，不构成串化器规格通过或物理缓冲器改进的证明。

来源 `results/analog/tx/final_retime/20261107T094213Z`；四个零偏移基线、每输入回放误差、波形哈希、执行记录和完整终点由采集器复核。图和机器数据分别为 `docs/figures/tx/ingress/tx_final_retime_window.png` / `.svg`、`docs/data/tx_final_retime_window.json`；无参数运行 `uv run python verification/plotting/tx_final_retime.py` 可据数据重画。

参考关闭沿取原 trace 的 sap−san 在半字沿后首次下降过零；偏移试验以原关闭沿加命令偏移作为估计参考，未声称测量了偏移 case 的本地关闭沿。输出采样沿用原训练延迟且加命令偏移，未拟合载荷，也未评为规格；最后 200 ps 不评价。范围仅 TT/FS 各两事件及理想电压回放，无上游源阻抗和反馈，不覆盖全码型、45 PVT、失配或噪声。
