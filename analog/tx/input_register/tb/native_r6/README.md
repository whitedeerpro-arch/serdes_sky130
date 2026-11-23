# 当前r6与完整TX的加载接口

`loaded_probe.py`在明确的M1/ext源上增加当前v3/extra5、WT16/R240末级时钟、字入口、完整串化/驱动及既有外围负载，数据静态为零。共享一份真实BG，TX另加本地n85电流拷贝/偏置二极管；PLL/BG保留M1冻结的定宽电阻卡，TX保留原完整TX的通用PDK电阻转换。

TX有100/120/133 Ω负载，单只2p85定宽卡的端头电阻为137.6 Ω，直接套用会得到负长度。TX单元在bench内使用独立子电路名以容纳原通用卡，不改变实例名/节点路径、拓扑或尺寸；通用卡各自计算宽度/长度。最初全定宽prepared方案保留诊断，未运行、不计覆盖。新准备还须做静态端口与实际电阻几何核对；联合电路需要自己的电气结果，原理想时钟45点不转为原生资格。

2 GHz极性沿用旧原生联合边界：s2gp←b0n、s2gn←b0p。v3低频输入仅保留输入级负载，明确接d08/d04/d02，实际新增的反馈抽头负载包含在仿真中。全部连接为0 V探针桥，时钟来自同deck PLL，不是回放源。当前2 GHz输入级签名为 `4833a4eeb14e14c5`；counter `.ic` 是既有bench辅助，未代表生产复位。

```bash
uv run python analog/tx/input_register/tb/native_r6/loaded_probe.py --prepare results/analog/pll/top/native_r6/<explicit_parent> --stop 120e-9
uv run python analog/tx/input_register/tb/native_r6/loaded_probe.py --resume results/analog/tx/native_r6_loaded/<run_id> --timeout 2400
uv run python analog/tx/input_register/tb/native_r6/loaded_probe.py --analyse results/analog/tx/native_r6_loaded/<run_id>
```

prepare只生成并冻结输入；resume必须先验证指定父级TT/ext波形完整且满足32周期/320 ns工程锁定合同，再做自己的1 ns冒烟及120 ns短加载probe。父级不满足则不启动NG。资源最多1worker，与当前M1/局部支撑合计≤2，全机≤4。

仅作主线接口支撑时，可显式加 `--exploratory` 做≤120 ns的静态加载卡：要求父级最后一个完整32周期窗口合格，但允许其保持记录尚不足320 ns。结果保留 `contract_passed=false` 及具体父级波形身份，不能计为M1或M2通过，不放宽完整动态链的退出条件。0.6 µs记录保持288 ns的本轮场景正适用这种局部校准；0.8 µs持续锁定记录另跑。

120 ns只用于观察真实时钟、计数器和字时钟接口，不是加载后的持续锁定或动态TX通过。本项成立后仍需较长静态加载记录，登记锁定后实际字时钟的RTL事件边界，再做动态同deck串化、位映射、75 mV/0.15 UI及持续锁定。具体继承范围见[主线复核](../../../../../docs/design/r6_mainline_review.md)。
