# 末级保持切片：执行器已准备，等待原始波形校验

末级电路与回放边界已核对；执行器已实现，但尚未对真实 trace 完成端到端验证，当前不能据此判断 slot 8 根因。未运行 ngspice，未登记边界。

## 电路和边界

切 `g3_0p/n`、`g3_1p/n`、`c2gp/n`、`vbias`、`xtx.xtree.vbias_logic`、`vdd`，直接驱动原 `serdes_cml_latched_mux2_lowov`。由 `serializer16_retimed_lowov` 默认参数展开，末级 wdata=40、wselect=96、wtail=72、nftail=24、rload=400、whold=40、wsf=80、wsf_sink=4，latch_tail_scale=2、latch_load_scale=0.75。输入是理想电压回放，无上游源阻抗和受扰反馈；不是新增缓冲器的物理实现，也不包含失配。

下游保留 qp/qn 各 2 fF、完整驱动器、pad、交流耦合及 RLC16 负载。原始事件在发射使能已打开之后，切片使能保持供电电压。模板中的直连负载实例必须与原 trace deck 逐行一致。vdd 与偏置均应回放实际波形，不应替换成固定理想值。

## 原型和未完成事项

`window.py --register --campaign TRACE_ROOT --boundary-id UNIQUE_ID` 是显式登记入口；在 trace 完整、校准通过后才可由集成者调用。它核验来源及 checkpoint 哈希、trace raw 完整性、原负载实例，并按源捕获字取得实际 A 下降或其后 B 上升沿，登记来源、条件、实际 bit/word/slot、切片时窗及负载哈希。默认 bit 104，另可 `--bits 48,104`；60 ns 不应外推 bit 232。

执行器以事件前 4 ns 和后 2 ns 的原数据插值端点，使用 `simplify_pwl` 的 10 µV 有界误差与 `alter` 向量避免长参数；只整体平移 c2g 两根。`--run --boundary-id ID` 只跑零偏移；之后使用 `--resume CAMPAIGN --boundary-id ID --offsets-ps=-80,-40,40,80,120` 明确扫偏移。qp/qn、ahp/ahn、bhp/bhn 在预先固定的事件评价区间 3.5–5.8 ns 对原 trace 每节点误差 ≤5 mV 是所有偏移结论的前提。末端 200 ps 不评价，避免平移后波形在截取边界钳位影响诊断。下游 RC 的初态无法保证复现，校准失败直接拒绝，不能改窗口求通过。

扫描候选为 −80、−40、0、40、80、120 ps。每 case 独立追加目录，检查 transient 实际终点与所有源哈希再续跑；只补缺失条件。登记与运行校验源单元、树实例参数、物理依赖、检查点、PDK、原始波形和直接负载；仿真按工艺角分组，检查实际终点后续跑缺失 case。纯 Python 已检查源实例、依赖解析与合成波形压缩；真实 trace 的输入重现、基线误差、网表及续跑仍需实测。
