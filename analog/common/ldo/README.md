# HV18 PLL 供电候选

当前 r3 为3.3→1.8 V局部设计，尚未进入现行PLL。详见[设计记录](../../../docs/design/ldo.md)与[工作修订](../../../config/ldo_working_revision.toml)。

电路在 `spice/`：`ldo_hv18_core.spice`为当前核心，r1/r2文件是可比较的历史电路，保留相同subckt名，比较时每次只能include其中一个；`ldo_power_switch.spice`为双向隔离单元，`pll_supply_hv18.spice`为含稳压/旁路、输出电容及反馈的集成候选。三个文件和已有CMOS/bias helpers由bench显式include。DUT无电源源、激励或负载。

测试入口均先`--prepare`保存源、PDK身份和deck，再运行打印出的campaign路径。每个campaign追加结果；不要直接复用历史绝对路径deck启动。最多占2个ngspice名额，全机不超过4个。

```bash
uv run python analog/common/ldo/tb/pass_map/run.py --prepare
uv run python analog/common/ldo/tb/pass_map/run.py --resume <campaign> --workers 2
uv run python analog/common/ldo/tb/regulation/run.py --prepare --rhv-ohm 1000 --chv-pf 50
uv run python analog/common/ldo/tb/regulation/run.py --prepare --real-bias --rhv-ohm 1000 --chv-pf 50
uv run python analog/common/ldo/tb/regulation/run.py --resume <campaign> --workers 2
uv run python analog/common/ldo/tb/stability/run.py --prepare-from <completed-ideal-reference-campaign>
uv run python analog/common/ldo/tb/stability/run.py --resume <campaign> --workers 2
uv run python analog/common/ldo/tb/dynamic/run.py --prepare-from <completed-ideal-reference-campaign>
uv run python analog/common/ldo/tb/dynamic/run.py --resume <campaign> --workers 2
uv run python analog/common/ldo/tb/power_switch/run.py --prepare
uv run python analog/common/ldo/tb/power_switch/run.py --resume <campaign> --workers 2
uv run python analog/common/ldo/tb/modes/run.py --prepare
uv run python analog/common/ldo/tb/modes/run.py --run <campaign>
```

`regulation`把同MOS角的VT和负载合并，`dynamic`把独立阶跃/单音/启动bench放在同一个deck且只共理想地，降低模型解析成本。波形由`spice.Waves`校验finite和单调，另查完整扫描网格/终点、源、deck和execution身份。

续跑前锁定runtime身份；更改runner/shared helper后须新建campaign或恢复记录的版本。`--analyse`允许独立重读旧数据，分析器身份另记。早期试跑曾有noise save列表和raw别名校验问题：失败记录保留，不能作为缺测数据的通过证据。已发布汇总只引用完整结果。

结果目录为`results/analog/common/ldo/`，发布索引为`results/catalog/ldo_characterization.json`；可分享的图与数据在`docs/figures/clocking/pll/core/ldo*`及`docs/data/ldo_characterization.json`。
