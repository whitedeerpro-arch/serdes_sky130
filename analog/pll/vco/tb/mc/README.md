# VCO局部失配

`run.py`是历史r5/4bit全角卡；当前r6不继承其样本结果。`r6_pilot.py`复制明确的r6控制导纳母本快照，完整tt_mm PDK、真实共享BG/定宽电阻、1MΩ/16pF慢尾、四buffer各30fF负载，码9和Vctrl固定。频率散布没有本轮独立验收门槛，记为ungraded；八个样本只作TT局部频率散布初筛，未逐样本重新选码，不证明量程尾部、PVT、闭环锁定、随机相噪或良率。

```bash
uv run python analog/pll/vco/tb/mc/r6_pilot.py --prepare results/analog/pll/vco/ctrl_load_r6/<explicit_parent>
uv run python analog/pll/vco/tb/mc/r6_pilot.py --resume results/analog/pll/vco/mismatch_r6/<run_id>
uv run python analog/pll/vco/tb/mc/r6_pilot.py --analyse results/analog/pll/vco/mismatch_r6/<run_id>
```

固定seed6/chunk4，两块八样本；另跑一份TT名义点、同种子首样本，mc.run_many还在首块前保留单样本完整终点pilot。先独立1ns冒烟，24ns瞬态从14ns后第二至第十二个上升沿测十周期均频；每份输出要求实际24ns终点、完整行数与输入身份。每块最多4样本以限制mc_source内存增长，单worker，与M1合计≤2，全机≤4。原PDK变容模型用于MC；局部noisy副本只在独立噪声审计卡使用，未混用为统计配对输入。

初筛记录、适用边界与固定索引见[持续锁定续做](../../../../../docs/design/r6_lock_confirmation.md)。修改工况、分块或源时准备新campaign，不能在旧目录上更换样本身份。
