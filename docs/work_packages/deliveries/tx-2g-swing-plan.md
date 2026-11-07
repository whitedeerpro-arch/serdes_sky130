# TX 2 GHz 内部摆幅：局部尺寸约束与扫描计划

I-17 的首要实验是固定输出输入对管宽度，联合减小尾管宽度与负载电阻，在真实末级负载下重新测量摆幅、共模和时序。粗估中 `wn=32、wt=16、R=240 Ω` 在 TT 约 368 mVpp、FS 约 329 mVpp，可作为首轮探索点；`wt=18、R=240 Ω` 的 TT 粗估约 414 mVpp，已高于 400 mVpp 上界，只保留用于定位趋势。两者均是按强假设缩放的估算，不能作为电路采用或规格通过结论。项目规格要求内部 CML 节点不超过 400 mVpp，硬下限 150 mVpp、设计目标至少 200 mVpp，并要求跨 PVT 驱动下一级完整翻转。

## 已知电路与适用范围

[末级重定时记录](../../design/tx_final_retime.md)及[原始汇总](../../data/tx_final_clock_chain.json)给出两个事件、TT 1.8 V 27 °C 与 FS 1.65 V 85 °C 的局部比较。extra=3 时 bit104 的 c2g 差分时域峰峰值分别为 689.43 mV 和 616.97 mV；bit48 为 685.61 mV 和 610.21 mV。它们是加载后的波形观察，非静态电流测量。extra=3 完整 TX 的 TT/FS 两点眼图已恢复，但尚无全 PVT 资格。此处只讨论 2 GHz c2g，不能将局部结果扩展为全串化器通过。

[时钟链](../../../analog/tx/input_register/spice/final_retime_clock_chain.spice) 的 out 级为 `wn=32、wt=24、rload=300 Ω`，输入对由前级驱动；iso 和额外中间级均为 `wn=24、wt=16、R=400 Ω`。输出输入对的 `wn` 和 `nfin` 保持不变以保留前级输入负载，但改变尾流仍可能改变其动态输入阻抗。源 DUT 中 R 是理想名义电阻，但这次局部 bench 经 `rcorner.to_pdk` 转换为 `sky130_fd_pr__res_high_po`，TT 与 FS 均为 PDK R tt。原始器件快照保留的注释仍称理想电阻，实际电阻实例是 `XRp/XRn`；R 参数是生成 PDK 几何的名义值，不能假设实效电阻与名义值严格成正比。[CML 延迟单元](../../../analog/common/cml_buffer/spice/cml_delay_resistive.spice)的尾管为普通 NMOS、输入对为 LVT；此处尚无 PDK 电阻 hh/ll 或版图寄生验证。输出的下游[末级单元](../../../analog/common/cml_mux/spice/cml_lowov_cells.spice)每个极性驱动 A、B 锁存各一个源跟随器以及 MUX 的一个源跟随器，共三个 LVT follower 栅，且还存在连线和其他实际连接负载；每极下游节点也受共模、电容和器件非线性影响。

## 粗模比较

假设同一工况下实效 PDK 电阻与名义 R 参数按比例变化、偏置和尾管工作区不变，尾电流近似与 `wt` 成正比，完全换向，且归一化时动态衰减不变：`A/A0 ≈ (wt/24)(R/300)`。对 TT/FS 各用上面 extra=3 bit104 的实测值作为锚点，而非假定 `I·R` 必然等于波形差分峰峰值。用此假设令 TT 达 400 mVpp，需要 `wt/24 × R/300 ≈ 0.580`；FS 对应约 0.648，两个条件不能通过单一比例同时恰好落在目标。

只为展示假设下的延迟敏感性，假设输出总等效电容不变、输入宽度固定、`gm/gm0 ≈ √(wt/24)`，并人为取基线延迟的 RC 项与 `C/gm` 项各一半：`D/D0 ≈ 0.5(R/300)+0.5/√(wt/24)`。这是未经校准的假设敏感性演示，数值接近 1 不能作为真实延迟或推荐候选的依据；它不是从测得的单级延迟拟合出的模型，也不是输出边沿时间、相位或时序保证；实际应先用小信号与瞬态测量校准两个权重、工作区及负载。原数据中每增加一个中间级在该加载下约 TT 15.7 ps、FS 19.5 ps，是中间级增量，不能直接用于此输出级。

| `wn/wt/R`（µm/µm/Ω） | 相对 `I·R` | TT 估算 mVpp | FS 估算 mVpp | 假设模型 D/D0 |
|---|---:|---:|---:|---:|
| 32/24/300 原样 | 1.000 | 689 | 617 | 1.000 |
| 32/24/200 | 0.667 | 460 | 411 | 0.833 |
| 32/18/300 | 0.750 | 517 | 463 | 1.077 |
| 32/16/300 | 0.667 | 460 | 411 | 1.112 |
| 32/18/240 | 0.600 | 414 | 370 | 0.977 |
| 32/16/240 | 0.533 | 368 | 329 | 1.012 |

表格展示减 R、减尾流及联合缩放的相对方向；结果对尾管沟道调制、压降、换向不全、寄生、动态负载、边沿斜率和 follower 非线性敏感。减 R 通常使单端输出高低电平向 VDD 抬升，减尾流亦改变共模与输入对/尾管余量；两者即便 I·R 相同也不能认为等价。假设 1:1 电流缩放与恒定动态衰减尤其需要 OP 和瞬态验证。

## 最小局部扫描与判断

1. 保留并复现原样 `32/24/300`，沿用已登记的 TT/FS 真实时钟、g3 数据、vbias、VDD 回放、实际 extra=3 链、完整下游末级及负载。以原 c2g、qp/qn、保持节点及边沿对齐做原样校准；先确认追溯输入身份和误差，再比较候选。回放忽略上游源阻抗及反馈，需在记录中说明。基线失败即停止解释候选。
2. 起始扫描 5 个候选 `32/24/200、32/18/300、32/16/300、32/18/240、32/16/240`，分别观察减 R、减电流和联合变化；固定其它级、输入 `wn/nfin`、回放、负载和测量窗口。先在 TT 与 FS 各两个既有事件上测，任何候选都保留所有结果，不以模型值替代仿真。若候选边界远离目标，再根据已测趋势局部细化 R 或 wt；不在整条 TX 上盲扫。
3. 每点测 c2g 差分和单端峰峰值、Vcm 高低及其动态范围、波形交越和上/下沿、占空比、相对输入及本地 A/B 关闭时间、相位增量；同时看 follower 输出 `sap/san、sbp/sbn` 和 MUX 内部 follower 的差分、共模、延迟、极性，测输入对和尾管 `Vds/Vgs`、尾流及 follower/sink 的工作点和余量。检查相对上游 g3 建立以及保持节点和选通实际切换，而非只看 c2g 摆幅。
4. 在相同实际负载下标定电流与延迟模型，检查 TT/FS 的幅度变化是否按预计比例及时间变化方向成立。若额外候选导致原有两个事件的输出极性、保持状态、相位窗口或失真恶化，记录失败及原因；窗口评价仍是局部条件比较。以测得数据决定是否进一步探索 `wn`、follower 尺寸或替代输出结构，变更 `wn` 时必须重新校验上游负载。
5. 只将局部可行候选送回完整 TX 做新边界登记及 TT/FS 全码型、位映射、眼图和边沿散布确认，再扩展压力角、45 PVT、失配及噪声。按现行规格检查内部摆幅硬上界 400 mVpp、硬下限 150 mVpp 与设计目标 ≥200 mVpp，并结合实际下一级完整翻转行为评估。候选的局部工作点、驱动源阻抗、PDK 电阻全角及版图寄生影响尚未验证，均为未分级。

## 固定输入身份

| 输入 | SHA-256 |
|---|---|
| `docs/design/tx_final_retime.md` | `c82375cefd253c1498c26ddfeccd0decb8c701efe4501ea319796e28c9789eb5` |
| `docs/data/tx_final_clock_chain.json` | `f04b2e68ac4604d967307f32020d7775374d7378ce1c9ce04535066ce2188981` |
| `analog/tx/input_register/spice/final_retime_clock_chain.spice` | `a47cf774d01b858a2f285f78d2db1bf63259c433ca8077e7854488b1be950d2c` |
| `analog/common/cml_buffer/spice/cml_buffer.spice` | `ed19598c56a902210ea0df4ed0ace36c5944cee674f2d19ad2481b7c5d30c2c9` |
| `analog/common/cml_buffer/spice/cml_delay_resistive.spice` | `f5e8c9f6506253c55483e182fe019972898b6e35d179855ff7def8ebbc9d5cf9` |
| `analog/common/cml_mux/spice/cml_lowov_cells.spice` | `2a8b62f0b8c957a36b89c56013692c7a313b2f6c996195b8decfde95bf4b2a59` |
| `analog/tx/input_register/tb/final_clock_chain/run.py` | `7856743fed882d5af7950c6025c2f619571331b5de41fc720973a4157a178ab8` |

## 本次实测 deck 与快照身份

原 [TT deck](../../../results/analog/tx/final_clock_chain/20261107T094939Z/tt/tb.cir) SHA-256 `c7c2cf04d04f616aeac7b8db847f488d224fa7de4f1a9afb6fa9e1132d87fe2f`；[FS deck](../../../results/analog/tx/final_clock_chain/20261107T094939Z/fs/tb.cir) SHA-256 `a1545015c76458bea3a0828a268dc0d4acfce8e01081b003911177ccb0c34241`。两者各引用其 `snap/<corner>/pdk_resistors/`，对应 MOS 库段分别为 `tt` 和 `fs`，电阻角为 tt。

[TT PDK 电阻转换快照](../../../results/analog/tx/final_clock_chain/20261107T094939Z/snap/tt/pdk_resistors/analog/common/cml_buffer/spice/cml_delay_resistive.spice)和 [FS 对应快照](../../../results/analog/tx/final_clock_chain/20261107T094939Z/snap/fs/pdk_resistors/analog/common/cml_buffer/spice/cml_delay_resistive.spice) 的 SHA-256 同为 `109e9a438051ba16d66bb8c3c891fb0b80d318fec460ec53b637f8b7105724f1`；两个转换后 [时钟链快照](../../../results/analog/tx/final_clock_chain/20261107T094939Z/snap/tt/pdk_resistors/analog/tx/input_register/spice/final_retime_clock_chain.spice) 的 SHA-256 同为 `a47cf774d01b858a2f285f78d2db1bf63259c433ca8077e7854488b1be950d2c`。[规格](../../overview/spec.md) SHA-256 `c32a7d21072eaa477a95daee34f824602e2ac74c14933d86bbb1db20c57f01a9`。
