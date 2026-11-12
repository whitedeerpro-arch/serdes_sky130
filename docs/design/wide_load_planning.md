# 宽度与并联数：物理负载联合规划

**先比较电流、阻值、参考跟踪和寄生，再选固定电阻网络。** 2p85的最少合法并联数只解决几何；[耦合初态局部对照](tx_coupling_state.md)已经把所见端接峰值提高到6.619mA。增加宽度可以减少支数，但总导电宽度、匹配阻值所需长度和节点电容须一起计算。

## 当前交付与适用范围

新[器件卡](../../analog/common/devices/tb/passive_card/wide_load_card.py)已准备，尚未完成电气运行；不改变生产DUT、PDK或采用修订。分别校准1p41、2p85、5p73的`A+B·L+C/L`曲线，允许接触系数C为负，几何只在实测长度域内求解，长度网格0.01µm。共享[规划器](../../src/serdes_flow/poly_geometry.py)与旧campaign使用的规划器分开维护，避免改写历史输入身份。

负载目标为当前通用卡的50/120/240/300/400/600Ω名义值所对应的TT实际阻值；50Ω比较2p85的5/8/17/24/32并及5p73的2/4/8/12/16并。计划覆盖5个RC角、三温及10/100/250/500mV负载压降。1Hz小信号阻值对±100µV DC微分复核，2GHz端口导纳另记。串联参考含分布RC，高频实部不要求等于DC斜率。

参考比较采用受控1.23V跨压的112kΩ＋16×780Ω电阻串，另外比较固定1p41的单段/八段主电阻。其余修调段理想旁路，**没有带隙闭环、修调MOS、镜像管或实际I·R输出资格**。几何面积只计电阻膜，不计接触头、保护环和布线。

2p85/1p41使用已验证的[立方导数模型副本](fixed_poly_ac_overlay.md)。5p73原卡立方底数非负，保持原模型；本轮仍须通过低频AC/DC微分检查。

## 电流边界如何使用

PDK给出的500µA/µm模型区间与推荐≤100µA/µm是使用指导，不是新的SerDes门槛，也不是交流EM签核方法。以6.619mA峰值、理想均流作规划：

| 组合 | 总膜宽 µm | 假设峰值电流/宽度 µA/µm |
|---|---:|---:|
| 2p85 × 8 | 22.80 | 290.3 |
| 2p85 × 24 | 68.40 | 96.8 |
| 5p73 × 12 | 68.76 | 96.3 |

表中的电流密度由同一个局部峰值推算；换电阻网络会改变负载电容、实际摆幅和电流，尚不能当作新网络的全PVT电流上界。宽度约翻倍、支数约减半时，总膜宽近似相同；匹配同一电阻值所需的膜长度/面积也会约束寄生，电容不应先假定减半。

## 独立原语版图复核

Terra和集成者分别在新目录调用本机Magic生成2p85、5p73的L10µm原语，`guard=1, doports=1`。两次均完整DRC 0、LVS匹配且无属性差错；提取为独立三端`B/R1/R2`，电阻实际使用两端及体端，保护环标签在衬底接触层。按端口、器件和参数比较两次结果，未要求带生成时间的文件逐字相同。

[复核数据](../data/layout_fixed_resistor_review.json)、[索引](../../results/catalog/layout_fixed_resistor_review.json)、[可复跑脚本](../../verification/analysis/layout_fixed_resistor_review.py)。这是孤立L10原语的构建检查；待选长度、完整并联网络、均流走线、EM、自热和PEX仍须另验。

## 复跑入口与后续验收

准备目录`results/analog/common/devices/wide_load_card/20261112T050902.564688Z_ea0db703`固定源码、计划及模型身份。已有6项几何/拓扑测试通过；电气任务需等全局ngspice空位，单worker运行，按RC角续跑。

```bash
uv run pytest -q tests/test_poly_geometry.py tests/test_wide_load_card.py
uv run python analog/common/devices/tb/passive_card/wide_load_card.py --resume results/analog/common/devices/wide_load_card/20261112T050902.564688Z_ea0db703
```

电气卡完成后由[发布器](../../verification/plotting/wide_load_card.py)重新读取标量raw并核对完整覆盖，画电流/电容/面积及参考比值图。只据联合比较缩小候选；采用前仍需真实参考、当前完整电路边界、全PVT与实际网络版图验证。
