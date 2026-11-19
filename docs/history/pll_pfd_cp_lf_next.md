# PFD、CP、LF 的下一阶段边界

本轮 r3 分频链验证期间，已开始 CP 的小范围 DC 顺从扫描。原电路保持不变，数据在当前 [r3 campaign](../../results/analog/pll/pvt_buffered/20261029T152825Z/cp_boundary_initial.json)。这是进入下一阶段的初始表征，不是这三个模块已通过 PVT。

## 先把 VCO 需要的控制范围映射到 CP

CP 输出应覆盖实际选定粗调码对应的 Vctrl 范围，同时有足够的源/灌电流、UP/DN 匹配和动态余量。不能只在某个 TT 单点测到约 50 µA 就认为成立。

| 条件 | Vctrl=1.32 V 的 UP / DN | Vctrl=1.40 V 的 UP / DN |
|---|---:|---:|
| TT / 1.8 V / 27°C | 48.4 / 49.9 µA | 47.9 / 49.9 µA |
| SS / 1.65 V / −40°C | 46.2 / 49.1 µA | 42.9 / 49.1 µA |
| SS / 1.65 V / 85°C | 45.5 / 49.3 µA | 40.8 / 49.3 µA |

这里参考电流仍为理想 50 µA 注入真实镜像二极管；CP 本体均为实际 MOS。数据说明高控制电压处的上拉电流和 UP/DN 差异应优先处理，但不能仅凭 DC 电流差宣布 PLL 无法锁定：还需要有效脉冲电荷和闭环验证。

r3 实际 VCO 的 SS 冷角后来选定码 5、Vctrl=1.112 V 达到约 2.002 GHz，避免了码 6 需要的高控制电压区。CP 仍须覆盖捕获、预充接管和调谐余量，不能仅在这一目标点测电流。

## 推进顺序

1. **CP DC/动态输出窗口。** 扩展关键角与输出电压，记录电流、泄漏、UP/DN 差异及参考源条件；结合 VCO 粗细调结果判断实际需要的窗口。比较现有串联开关与已有源端开关候选时，保持负载、参考与电压范围一致。
2. **PFD→CP 有效电荷。** 以 250 MHz 为基准，测正负相差、零相差、频差、复位；看短脉冲实际送入滤波器的电荷、死区和残余偏移。随后覆盖选定 50–500 MHz 参考条件及 PVT，不把理想 UP/DN 脉冲等同于真实 PFD。
3. **LF 与闭环。** 理想 R/C 用于隔离有源问题，已有多晶硅/MIM 候选另做无源角。用同角 VCO 曲线和实际反馈延迟回接，测预充接管、捕获时间、跟踪与带宽；最后选关键工况做原生电路复验。

已有入口为 [CP DC](../../analog/pll/cp/tb/dc/case.toml)、[PFD 功能](../../analog/pll/pfd/tb/functional/case.toml)、物理 LF (`../../analog/pll/loop_filter/tb/pdk_mapping/case.toml`, retired in `retired_legacy_vars_20261120.json`)、[PFD/CP/LF 原型结果](pfd_cp_lf_results.md)。当前 LF 候选 (`../../analog/pll/loop_filter/spice/passive_rc_pdk_candidate.spice`, retired in `retired_legacy_vars_20261120.json`)仍未替换冻结设计。

锁定范围、捕获时间、允许电流失配、抖动和纹波限值仍需作为产品预算定义；探索中先报告测量值。若 SS/−40°C 被纳入额定范围，功能失败不能降格标成“质量一般但合格”。已满足最低要求的工况，才适合进一步按裕量分级。
