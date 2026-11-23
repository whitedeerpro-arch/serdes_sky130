# PLL PVT与物理滤波器候选

[返回图目录](../../../README.md) · [结果报告](../../../../history/pll_pvt_first_results.md)

本轮为探索性筛查，存在调谐、低压接口及高压端电压核对项。

- [pll_pvt_frequency_coverage](pll_pvt_frequency_coverage.png)：九环境开环调谐与固定控制点，非闭环锁频或全PVT签核。
- [pll_lf_poly_mim_corners](pll_lf_poly_mim_corners.png)：七个独立RC/温度条件及滤波器阻抗，不含完整版图寄生。
- [pll_pvt_loop_filter_comparison](pll_pvt_loop_filter_comparison.png)：仅TT实际PFD/CP与理想/物理LF对照，行为VCO/理想分频。
- [pll_pvt_clock_interface_failure](pll_pvt_clock_interface_failure.png)：SS低压热角VCO与buffer保持差分活动，CMOS读出缺失；局部接口证据。
