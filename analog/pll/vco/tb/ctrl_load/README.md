# VCO控制端导纳

`run.py`是旧r5/四bit夹具，结果保留在原campaign。`r6.py`独立建立当前五bit ring、四个真实buffer各30 fF代理、真实共享参考及1 MΩ/16 pF尾线滤波；host/quiet各为1.8 V理想电源。不是完整前端或闭环plant，不把局部卡片结果转作全PVT、PEX或噪声资格。

```bash
uv run python analog/pll/vco/tb/ctrl_load/r6.py --prepare results/analog/pll/vco/r6/map_20261112T062237Z/table.json
uv run python analog/pll/vco/tb/ctrl_load/r6.py --resume results/analog/pll/vco/ctrl_load_r6/<run_id> --timeout 1800
uv run python analog/pll/vco/tb/ctrl_load/r6.py --analyse results/analog/pll/vco/ctrl_load_r6/<run_id>
```

本地仅1worker；和M1合计最多2，全机≤4，启动前查登记和实时进程。先独立1 ns冒烟，随后三个50 MHz工况（0、5、10 mV）和两个±10 mV DC点，每个条件独立终点/超时/续跑。准备后保留源、模型身份、定宽电阻副本、deck和哈希，不重新按最新码表选点。

可另用 `--frequencies 2e7 --amplitudes 0 .01 --no-dc` 准备20 MHz与本底的独立campaign，确认频率依赖；不得修改原50 MHz目录的工况或终点来复用覆盖。

正弦在20 ns开始，丢弃首周期，再在精确的两个完整周期上取当前/电压复比。公共 `serdes_flow.spectral.tone` 用按时间加权的DC、线性漂移及正余弦拟合，处理自适应步长与窗口端点。检查无激励的同频电流泄漏、两档幅度的线性及实际激励幅度，满足后才能解释C/G读数；±10 mV DC点给当前负载代理下局部Kvco。不会将无声瞬态的周期散布当作随机相噪。


## 变容器噪声卡

`varactor_noise.py --run`检查安装PDK原模型；`--run --enable-rg-noise`使用独立本地副本，为表达式电阻rg补`noisy=1`。保留参数及电气表达式，仅更名子电路头尾；安装PDK不改。纯DC单器件端口用1Ω CCVS观察电流噪声，并以同deck RC参考验证4kTRe(Y)，不是振荡器相噪。

```bash
uv run python analog/pll/vco/tb/ctrl_load/varactor_noise.py --run --enable-rg-noise
uv run python analog/pll/vco/tb/ctrl_load/varactor_equivalence.py --help
```

`varactor_equivalence.py`在明确的CG母本上替换八只变容器别名，运行独立1ns冒烟和20ns瞬态，比较相同窗口的电压/控制电流；固定输入与结果见[续做报告](../../../../../docs/design/r6_lock_confirmation.md)。这只证明受检无噪声行为一致，后续ISF/周期噪声预算需显式使用修正副本并记录身份。
