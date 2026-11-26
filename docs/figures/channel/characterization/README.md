# 信道模型与 TX/PCB 实验图集

[返回图目录](../../README.md) · [信道模型设计文档](../../../design/channel_model.md) · [信道族数据](../../../data/pcb_channel_family_results.json)

本目录保存共享 `C0–C5` 合成 100 Ω 差分 PCB 信道族的频响、脉冲响应与发射机过信道眼图；均衡原理示意图见 [`../explanations/channel_equalization_pulse_shaping.svg`](../explanations/channel_equalization_pulse_shaping.svg)。

| 图组 | 格式 | 用途与适用范围 |
|---|---|---|
| `pcb_channel_family_frequency` | [PNG](pcb_channel_family_frequency.png) / [SVG](pcb_channel_family_frequency.svg) | 合成 100 Ω PCB 信道族 `C0–C5` 频域插损/回损表征（非实测板线） |
| `pcb_channel_family_pulses_ui` | [PNG](pcb_channel_family_pulses_ui.png) / [SVG](pcb_channel_family_pulses_ui.svg) | 合成 `C0–C5` 单比特脉冲响应与无均衡 ISI 窗口估计 |
| `tx_pcb_channel_2ui` | [SVG](tx_pcb_channel_2ui.svg) | 历史 TX 驱动合成 PCB 信道 2 UI 远端眼图（无 RX CTLE/CDR） |
| `tx_pcb_channel_effects_ui` | [SVG](tx_pcb_channel_effects_ui.svg) | 历史 TX 过不同损耗信道（C0/C2/C3）对眼高与散布的影响 |
