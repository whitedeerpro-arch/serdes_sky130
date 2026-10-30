# PLL 低过驱动分频器 PVT

[报告](../../../../history/pll_lowov_pvt.md)和[数值](../../../../data/pll_lowov_pvt.json)给出边界与失败点。三组图依次为标准输入45条件功能矩阵、FS热角时钟共模/分频对照、SS实际VCO回接。FS真实VCO的2GHz回接尚未资格验证；不能用本专题图推断完整PLL全PVT通过。

- [lowov_pvt_function_matrix PNG](lowov_pvt_function_matrix.png) / [SVG](lowov_pvt_function_matrix.svg)：标准2GHz CML输入边界45条件；FS热角96ns稳态复核；全速转换器44/45。非全PLL PVT。
- [lowov_fs_headroom_and_division PNG](lowov_fs_headroom_and_division.png) / [SVG](lowov_fs_headroom_and_division.svg)：FS1.65V85C，真实buffer2GHz输入；源跟随40/80um对比；不是实际VCO回接。
- [lowov_native_ss_reconnection PNG](lowov_native_ss_reconnection.png) / [SVG](lowov_native_ss_reconnection.svg)：SS1.65V85C，实际VCO/四路抽出及供电dummy，2.012GHz开环工作点；不代表FS或闭环捕获。
