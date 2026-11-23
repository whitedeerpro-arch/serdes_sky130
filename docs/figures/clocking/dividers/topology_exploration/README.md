# 锁存器拓扑探索

[完整报告](../../../../history/cml_latch_topology_experiments.md)与[数值](../../../../data/cml_latch_topology_experiments.json)。固定设置、角上重新调节、任意数据和实际波形回放有不同边界。新候选偏置部分理想化，当前工作设计没有被替换。

- [topology_2GHz_selected_corners PNG](topology_2GHz_selected_corners.png) / [SVG](topology_2GHz_selected_corners.png)：10种电路/接口在5个选定条件、固定TT设置的2GHz /2观察；不是PVT签核。
- [tailless_clock_bias_sensitivity PNG](tailless_clock_bias_sensitivity.png) / [SVG](tailless_clock_bias_sensitivity.png)：去独立尾源CML在TT及SS/FS冷热角的偏置/摆幅/功耗扫描；候选共模由理想源设置。
- [resistor_and_pmos_load_waveforms PNG](resistor_and_pmos_load_waveforms.png) / [SVG](resistor_and_pmos_load_waveforms.png)：同一CML内核的电阻、triode PMOS及未调共模PMOS上拉对照；不能代表所有有源负载设计。
- [interstage_buffer_weak_clock_replay PNG](interstage_buffer_weak_clock_replay.png) / [SVG](interstage_buffer_weak_clock_replay.png)：实际FS弱时钟电压记录回放，两级分频与真实CML buffer对照；未保留上游源阻抗。
