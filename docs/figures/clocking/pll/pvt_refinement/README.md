# VCO / CML→CMOS PVT修整

[报告](../../../../history/pll_pvt_refinement.md) · [数值入口](../../../../data/pll_pvt_refinement.json)。独立候选，不替换冻结基线。

- [pvt_vco_tuning_margin PNG](pvt_vco_tuning_margin.png) / [SVG](pvt_vco_tuning_margin.svg)：VCO尺寸/节点MIM扫描及五环境2GHz覆盖；TT相邻码局部重叠；非全码/全角签核。
- [pvt_receiver_internal_margin PNG](pvt_receiver_internal_margin.png) / [SVG](pvt_receiver_internal_margin.svg)：SS低压热角转换器内部动态裕量：原版与独立候选比较。
- [pvt_receiver_temperature_boundary PNG](pvt_receiver_temperature_boundary.png) / [SVG](pvt_receiver_temperature_boundary.svg)：SS电压/温度条件边界；8ns初筛与32ns临界复查分开；非产品温度额定值。
- [pvt_ss_divider_isolation PNG](pvt_ss_divider_isolation.png) / [SVG](pvt_ss_divider_isolation.svg)：转换器已恢复，但SS低压热角CML ÷2摆幅不足、÷4/÷8失效；非PLL通过。
