# TX PVT 与输出使能诊断

[报告](../../../history/tx_pvt.md) / [JSON](../../../data/tx_pvt.json)。固定250ps/UI、2UI眼图；原设计有角上裕量和接管缺口，候选未升级。

- [tx_pvt_margin_matrix](tx_pvt_margin_matrix.png)：45工况基线裕量矩阵；功能45/45不等于裕量或产品PVT合格。
- [tx_pvt_2ui_eyes](tx_pvt_2ui_eyes.png)：四选角真实加载TX；固定250ps/UI，仅训练定相；128bit，不是BER。
- [tx_driver_pvt](tx_driver_pvt.png)：理想400mVpp输入独立输出级；瞬态从已使能DC开始，不覆盖接管。
- [tx_tail_headroom](tx_tail_headroom.png)：原生尾节点范围与同角DC尾管I–V/Vdsat对照；不是完整动态极点分解。
- [tx_enable_diagnosis](tx_enable_diagnosis.png)：使能初态/理想钳位/实际MOS候选；默认设计未升级。
- [tx_pvt_C2_eyes](tx_pvt_C2_eyes.png)：四选角真实TX+固定6dB PCB，无RX/均衡/CDR；弱角有采样错误。

当前眼图仅作+0.5UI显示平移：中央完整眼、两侧半眼，原样本与指标不变；见 [相位/显示核对](../../../history/tx_clock_phase_audit.md)。当前渲染器为 [tx_pvt_eye_display.txt](../../../../verification/plotting/tx_pvt_eye_display.txt)。
