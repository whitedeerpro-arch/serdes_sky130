# 局部driver的固定电阻负载候选

**两角generic校准通过；fixed_2p85的FS热点完成，两种初态的局部眼图/位序均满足；FF冷点480s超时，5p73尚未运行，未采用新网络。** [宽卡](wide_load_planning.md)和[实际参考串](physical_reference_card.md)缩小了器件不确定性；本卡保持原参考，隔离合法并联负载变化。下一步先处理成本/数值瓶颈，不盲目延长整组超时。

## 冻结边界与比较对象

源为[耦合状态对照](tx_coupling_state.md)的明确campaign `20261112T043742.580713Z_66e65343`，不是最新运行或完整串化器回放。BC `tx_driver_clean_pair_20261112_v1`在[边界登记](../../config/boundary_conditions.json)固定两角实际/prepared deck、刺激、波形和driver身份。输入400mVpp、20ps、VDD−120mV共模，为零阻抗PWL；保留2fF输入电容。三种实现的Xiso输入签名相同，均经`boundary.check_load`检查。

| 实现 | 每个120Ω前驱负载 | 每个50Ω本地端接 |
|---|---|---|
| generic校准 | 原通用卡 | 原通用卡 |
| fixed_2p85 | 6只2p85，L5.40µm | 24只2p85，L9.84µm |
| fixed_5p73 | 3只5p73，L5.41µm | 12只5p73，L9.87µm |

几何来自已完成宽卡，匹配的是原TT实际阻值，不是精确名义值。每个case复制原全部显式依赖/刺激并固定哈希，显式选择已验证的立方导数模型副本；不改原PDK、原结果或生产DUT。当前依赖均为平铺include；遇到未冻结的嵌套依赖会拒绝准备，不能留工作树隐式引用。

只替换driver的`XRp/XRn`及`Xpre.Xgain.XRp/XRn`。Xpre使用独立命名的buffer/delay；Xiso、器件尺寸、全部偏置和其余电阻保持原generic。pad/package/10nF/RLC16/远端50Ω均保持原边界。

FS1.65V/85°C与FF1.95V/−40°C、RC tt，各实现独立deck；每deck保留“4ns使能”和“已使能DC初态”两份driver，共享该case原真实偏置。**每个case重新求DC解**，不移植generic的电容电荷。不同实现之间偏置隔离；同一pair的共享偏置扰动仍是实验的一部分。92ns数值DC初态不等于自然上电或微秒耦合建立资格。

## 测量与校准门槛

直接保存每支固定电阻内部`rhrpoly_2p85/5p73`导电电流，通用卡保存`rbody`；计算每支及总峰值/RMS。另保存输出和前驱尾管ID/VDSAT、前驱节点、pad/remote及两端耦合节点、vbias/vgi/Vbg和供电电流。记录初始节点/隔直电压及DC电流平衡；前驱余量复用公共`stage_metrics.headroom`，眼图/位序复用原paired测量。

先完成两角generic复现，才运行固定候选。预登记门槛：原样节点最大绝对差≤1mV、相同沿绝对时间差≤0.2ps、原电流峰值/RMS相对差≤1%。门槛失败时保留结果并分析，不自动放宽。

## 执行与后续

[运行器](../../analog/tx/output_driver/tb/physical_load_card/run.py)、[离线测试](../../tests/test_physical_load_card.py)检查替换部位、未改器件、所有分支探针及BC输入签名。集成者复跑通过，补入初始化/工具/PDK配置身份、前驱余量及初始KCL记录后准备：`results/analog/tx/output_driver/physical_load_card/20261112T094542.909159Z_d65944fd`。

原队列结束后独立恢复运行，两角generic校准通过，但fixed_2p85冒烟因电流探针身份错误被拦下。单器件`probe_identity/run`的`show b`确认：ngspice把定宽卡的电压相关R主体展开为`b.<层次>.brhrpoly_<宽度>`，不能用普通R的`@r...`探针。已改成`@b...brhrpoly_[i]`对应的器件电流查询（实际语法为`@b.<层次>.brhrpoly_2p85[i]`或`5p73[i]`），保留原失败及波形。

修正测量后新建`results/analog/tx/output_driver/physical_load_card/20261112T153555.198409Z_2da98456`；两角generic完整92ns约34/33s并通过原校准门。fixed_2p85 FS约435s完成、pad/remote两种初态均满足局部门槛与位序；FF约480s超时，未写完整结果，整组停止，5p73未启动。记录在该目录`analysis/measurement/summary.json`及各case执行记录；超时不判为功能失败。没有改DUT或门槛，旧campaign不能用新源码冒充原身份续跑。

成本差别主要出现在新增行为电阻/内部节点的求解；精简库只解决加载部分。按[成本方法](../verification/methods.md#仿真成本与精简模型库)，下一步先在名义器件卡比较显式并联与倍数合并的DC/AC/瞬态等价性，再决定如何回接。独立失配不能直接合并。

每case先1.001ns冒烟，再完整92ns；二进制raw、按实际终点续跑、不覆盖已有结果。单worker队列只在全局空位稳定后启动，每次运行前仍检查ngspice<4。队列日志在该目录`queue/events.jsonl`，不是仿真完成证据；完成以raw/执行记录和测量为准。

```bash
uv run pytest -q tests/test_physical_load_card.py
uv run python analog/tx/output_driver/tb/physical_load_card/run.py --resume results/analog/tx/output_driver/physical_load_card/20261112T153555.198409Z_2da98456
```

原控制进程仍活跃时不能重复resume。完成后用实际支路电流修正电流密度规划，比较新增C对局部边沿/位序的影响，再回接采用的真实串化器源并扩所需PVT、无源角、噪声/失配与网络版图。局部clean输入通过不代替整链或EM资格。
