# 带级间buffer的r3

[报告](../../../../history/pll_buffered_pvt.md)和[数值](../../../../data/pll_buffered_pvt.json)。标准输入45条件与实际VCO选角回接有不同覆盖；CP图为下一阶段DC初探。

- [buffered_pvt_function_matrix PNG](buffered_pvt_function_matrix.png) / [SVG](buffered_pvt_function_matrix.svg)：r3标准2GHz输入下45条件分频/反馈/全速CMOS功能；不是VCO45点调谐或完整PLL签核。
- [buffered_native_fs_clock_chain PNG](buffered_native_fs_clock_chain.png) / [SVG](buffered_native_fs_clock_chain.svg)：FS1.65V85C实际VCO和四路有偏置抽出，40-64ns稳态1.991GHz；启动另记，非闭环锁定精度。
- [cp_compliance_initial PNG](cp_compliance_initial.png) / [SVG](cp_compliance_initial.svg)：TT及SS冷热CP的DC顺从窗口探测；理想50uA参考，不代表动态PFD/CP或闭环PVT完成。
