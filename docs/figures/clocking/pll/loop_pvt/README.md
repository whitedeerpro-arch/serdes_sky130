# PLL 选角闭环与原生短时接回

[报告](../../../../history/pll_loop_pvt.md) / [JSON](../../../../data/pll_loop_pvt.json)。所有时间轴以250ps/UI。

- [pll_loop_pvt_tracking_ui](pll_loop_pvt_tracking_ui.png)：同角实测VCO模型 + 真实PFD/CP/LF；预偏置局部跟踪，不是冷启动或噪声。
- [pll_loop_pvt_lock_summary](pll_loop_pvt_lock_summary.png)：12场景13记录；保留SS高温短记录未通过，延长后通过；非原生整机签核。
- [pfd_cp_pvt_charge](pfd_cp_pvt_charge.png)：45工况±200/0ps三点有效电荷；不能证明无死区或全部输出电压工作。
- [pll_native_handoff_ui](pll_native_handoff_ui.png)：r3原生TT预充断开40ns/PFD释放48ns/停止96ns；不是持续锁定。
