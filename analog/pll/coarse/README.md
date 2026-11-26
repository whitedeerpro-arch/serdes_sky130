# PLL 粗码控制与窗口检测（`analog/pll/coarse/`）

PLL 侧粗调窗口检测积木，使用 [监测工具包](../../../docs/design/monitor.md) 的比较器与门限梯构建；数字粗码状态机集成于 [pll_coarse_ctrl.sv (v3)](../../../digital/pnr/rtl_v3/pll_coarse_ctrl.sv) 与 [pll_coarse_ctrl.sv (v4)](../../../digital/pnr/rtl_v4_32b/pll_coarse_ctrl.sv)。现行 4G VCO `r6` + PTAT `28/66` 已实现全 45/45 跨三温单一固定码覆盖（[pll_vco_r6_ptat.md](../../../docs/design/pll_vco_r6_ptat.md)），开机二分粗调后无需运行期动态切码。

| 部分 | 文件 | 说明 |
|---|---|---|
| 窗口检测（CMOS 译码） | [`spice/vctrl_window_cmos.spice`](spice/vctrl_window_cmos.spice) | 感测 LF 积分电容节点 `z`（无 CP 纹波，比较器回踢进 18 pF `Ci`）；`vlo` 对地梯、`vhi` 对电源梯，采用 `serdes_cmp_hv` |
| 数字控制器 | [`digital/pnr/rtl_v3/pll_coarse_ctrl.sv`](../../../digital/pnr/rtl_v3/pll_coarse_ctrl.sv) · [`digital/pnr/rtl_v4_32b/pll_coarse_ctrl.sv`](../../../digital/pnr/rtl_v4_32b/pll_coarse_ctrl.sv) | 5-bit 上电粗搜与越界监测，集成在 `pll_control_top` 中 |
| 历史表征记录 | `tb/window_dc/` · `tb/cp_handoff_mc/` | 窗口翻转点与交接失配表征记录（详见 [monitor.md](../../../docs/design/monitor.md) 与 [pll_loop.md](../../../docs/design/pll_loop.md)） |
