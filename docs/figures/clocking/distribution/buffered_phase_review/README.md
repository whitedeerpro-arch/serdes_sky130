# r3分频buffer相位与奇偶位核对

[报告](../../../../tx_clock_phase_audit.md) / [JSON](../../../../data/tx_clock_phase_audit.json)。原生前端为固定Vctrl开环采样，后接理想化边沿及真实TX负载；未重标定trim、未重验流数据。

- [tx_buffered_clock_phase_ui](tx_buffered_clock_phase_ui.png)：新r3固定控制前端时钟与真实TX负载相位；极性候选未升级，未做流数据验收。
- [tx_even_odd_phase_history](tx_even_odd_phase_history.png)：旧冻结时钟PVT的even/odd按k−2更新历史分组；不能当作r3新时钟数据流。
