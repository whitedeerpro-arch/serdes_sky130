# 功耗审计：2026-11-10

现有结果不足以给出完整 SerDes 总功耗或拟议 LDO 的实测峰值／全 PVT 上界。TX 当前45点从实际供电波形复算为 **86.15–118.67 mW，TT 1.8 V 27 °C 为 102.86 mW**。当前 RX 真实偏置的 FS 1.65 V −40 °C hh 单点为 **30.36 mW**（24–44 ns 时间加权）；旧版理想偏置45点为 **31.90–52.06 mW，TT 42.42 mW**，不代表当前电路全角。

## LDO 负载证据

拟供 VCO、CP、LF、四个一级 buffer；分频、接收器和 TX/RX 留 host 1.8 V。r5/k4 原生 TT 预充闭环 `results/analog/pll/top/native_k4/20261108T200611Z/tt_v1800_t27_tt/run/loop.raw` 只保存 ref、fb0、ctrl、z、c0p，没有电流，不能从该运行给出负载电流。相同 deck 中 Vdd、Vdummy、Vbias 为独立电源，Vpre、Vref、复位和码也是理想源；Vdummy 供三个假分频/反馈路径，不能并到拟供 LDO 的负载。原生测试不含 B2；理想 Vpre 供预充。四个一级 buffer 和 VCO 同接 Vdd，但该 Vdd 还供其他电路，不等于所需子域。

名义尺寸粗估而非实测：真实偏置的 CML 参考 212.5 µA 对应 W/L 5/0.5；四级 VCO 各 W20/0.5，名义 4×(20/5)×212.5 µA = **3.40 mA**；四个一级 buffer 各 W12/0.5，名义 **2.04 mA**。两者相加 5.44 mA。k4 转向 CP 标称单支约 200 µA 持续流入输出或 dummy，跟随器尾约100 µA，初估合计 **5.74 mA，1.8 V 约 10.33 mW**。不能把上下拉各加一次：转向电流的回路和 follower 供电支路存在重叠，0.3 mA 是名义电路估计而非已测。LF 无静态直流耗流假设不覆盖动态或泄漏；PFD、复制偏置、预充、源驱动、导线以及输出瞬态均未量化。实际镜像误差、PVT、供电域迁移、负载响应和启动峰值未覆盖；这个估计不是保证下界或上界，4 mA 不能作为覆盖该名义估算的 LDO 额定值。

## 各数字的边界

- TX `results/catalog/tx_full_pvt45.json` 所列45个原始运行，各自积分 `-v(vdd)*i(Vdd)`，24–100 ns，实际时间窗和 raw/deck SHA-256 逐点见 `evidence.json`。最小 FS 1.65 V 85 °C，最大 SF 1.95 V −40 °C。含该 bench 的真实带隙、CML 偏置拷贝、字入口、分发、串化器、驱动和其供电流；理想2 GHz及其余理想时钟/数据源能量没有计入 Vdd，PDK电阻固定 tt，线端/通道为模型。并非 PLL 驱动或启动的实测。
- 当前 RX：`results/analog/rx/sampler/cold_readout_full_transient_dc/20261109T134623.873301Z_0c20ee1d/transient_full/`，FS 1.65 V −40 °C hh、PI20/trim32、C2 回放、理想四相源、真实偏置，Vdd 电源时间加权。原已发表的 30.16 mW 是整段保存点的算术均值；本次 30.36 mW 使用24–44 ns时间加权，窗口和算法不同。额外理想源包括单独的 Vref、四个0.7 V参考负载、时钟和输入，未算进 Vdd 功率。
- 旧 RX 45 点 `results/analog/rx/sampler/readout_deser/20261103T124408Z_ac_trim32/summary.json` 采用保存点算术平均、8–44.75 ns，独立 Vref 上的 0.85 mA 理想参考不计入 Vdd；此旧结果不能替代当前 W40／真实偏置 PDK-R 的45点。
- TX、RX 各测试台偏置网络重复，理想源与系统真实时钟边界不同，二者相加会重复带隙且遗漏时钟、CDR、PLL、其他数字及源功率。旧 RX 与当前 RX 是替代测量，不能相加。历史 VCO 6.06 mW 为旧几何／不同边界，不能叠加到上述尺寸估计。

全部 raw、deck、历史 summary 的哈希及逐条件数值见 [evidence.json](evidence.json)；采集器 [collect.py](collect.py) 只读现有结果。没有启动仿真。
