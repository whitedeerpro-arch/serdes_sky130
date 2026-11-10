# HV18 PLL 供电候选

当前为 **r4：静态供电引脚、参考RC、电压修调、PDK无源**。quiet PLL候选`r5k4q`已接入并完成TT两配置原生预充闭环，压力角进行中；原基线保留。详见[设计与边界](../../../docs/design/ldo_r4.md)、[工作修订](../../../config/ldo_working_revision.toml)、[交接包](../../../docs/work_packages/WP-LDO-002-r4-handoff.md)。

高压配置：Vin3.0–3.6 V，quiet为输出，enable高。外供配置：板上将Vin和quiet同接一条合格1.65–1.95 V电源，enable=0。只在初始化确定配置；不支持Vin=0而quiet单独供电。quiet高压模式的额外电容必须计入稳定性，目前没有任意外接去耦保证。

## 当前电路

| 文件 | 作用 |
|---|---|
| `spice/ldo_passives.spice` | high_po电阻、32段1MΩ、显式1pF叶MIM及组合 |
| `spice/ldo_hv18_core_r4.spice` | 双5V原生NMOS核心，独立隔离级gate RC，关断夹gate和偏置 |
| `spice/pll_supply_hv18_r4.spice` | 静态供电宏、参考传输门/RC/放电、6bit反馈电压码及100pF输出电容 |
| `spice/pll_bias_filter_r4.spice` | 独立1MΩ/16pF尾管栅滤波候选；未接入当前PLL |

生产cell `serdes_pll_supply_hv18_r4`；`_probe`只把反馈断点引出用于双注入。DUT中没有电源源、激励或负载。依赖已有`sky130_primitives.spice`、`sky130_pfet_lvt.spice`、`cmos_logic.spice`和`bias_dist.spice`；真实参考bench另引入`bandgap.spice`。无源卡明确实际模型值，不能用`mf`倍乘名义MIM。

## 复跑与读取

`--prepare`冻结source、PDK、runtime与deck，打印campaign路径；`--resume`只补完整性检查未通过的条件。当前分工最多占2个ngspice，全机不超过4个，启动前检查进程。短DC/AC按MOS/RC合deck，所有仿真单线程。

```bash
uv run python analog/common/ldo/tb/r4/run.py --prepare calibration
uv run python analog/common/ldo/tb/r4/run.py --resume <calibration-campaign> --workers 2
uv run python analog/common/ldo/tb/r4/run.py --prepare grid --calibration <complete-calibration-summary.json>
uv run python analog/common/ldo/tb/r4/run.py --resume <grid-campaign> --workers 2
uv run python analog/common/ldo/tb/r4/startup.py --prepare <complete-calibration-summary.json>
uv run python analog/common/ldo/tb/r4/startup.py --resume <startup-campaign> --workers 2
uv run python analog/common/ldo/tb/r4/dc_noise.py --prepare <startup-campaign>
uv run python analog/common/ldo/tb/r4/dc_noise.py --resume <dc-noise-campaign> --workers 2
uv run python analog/common/ldo/tb/r4/bias_filter.py --prepare --slow
uv run python analog/common/ldo/tb/r4/bias_filter.py --resume <bias-filter-campaign> --workers 2
uv run python analog/common/ldo/tb/r4/cap_load.py --prepare <complete-grid-summary.json>
uv run python analog/common/ldo/tb/r4/cap_load.py --run <cap-load-campaign> --workers 2
uv run python analog/common/ldo/tb/r4/cap_pvt.py --prepare <complete-grid-summary.json> --extra-pf 100
uv run python analog/common/ldo/tb/r4/cap_pvt.py --prepare <complete-grid-summary.json> --extra-pf 100 --rc-crossed
uv run python analog/common/ldo/tb/r4/cap_pvt.py --resume <cap-pvt-campaign> --workers 1
uv run python analog/common/ldo/tb/r4/card.py --help
uv run python analog/common/ldo/tb/r4/noise_check.py --help
```

历史campaign若runtime已变，不要关闭身份检查强行续跑。完整结果可直接读取；`run.py/startup.py/dc_noise.py/cap_load.py --analyse <campaign>`追加新分析而不改原deck/raw。本次清理删除startup末尾无效noise流程，并让noise汇总准确表述为“逐次比对pass电流”；已运行的原始source/deck仍保留在各campaign，发布清单选择清理后的分析。

从[明确清单](../../../config/ldo_r4_evidence.json)发布数据与图，无需新仿真：

```bash
uv run python verification/plotting/ldo_r4.py
dot -Tpng docs/figures/clocking/pll/core/ldo_hv18_r4.dot -o docs/figures/clocking/pll/core/ldo_hv18_r4.png
```

发布脚本核对source/PDK/deck/execution/输出SHA和网格坐标。结果本体在`results/analog/common/ldo/`（不入git），索引为`results/catalog/ldo_r4.json`，小数据和图为`docs/data/ldo_r4.json`及`docs/figures/clocking/pll/core/ldo_r4*.png`。

额外100pF端点的425点补测另有[数据/明确summary参数](../../../docs/data/ldo_r4_pin_cap.json)与[索引](../../../results/catalog/ldo_r4_pin_cap.json)，使用`verification/plotting/ldo_r4_pin_cap.py --base ... --endpoint ... --crossed ...`重画；两个新增campaign保持原同R角校准码，交叉RC不按每条件重新择码。

## 历史与限制

r1/r2/r3核心、`ldo_power_switch.spice`、`pll_supply_hv18.spice`及原有pass_map/regulation/stability/dynamic/power_switch/modes测试台保留作[历史证据](../../../docs/design/ldo.md)，不再是当前供电接口。旧WP-LDO-001复核的是r3，不把它的开关/模式要求用于r4。

本轮不含真实PLL负载/新增抖动、完整MC、PEX/ESD/封装或UVLO/ready控制器。慢RC使noise分析的默认瞬态工作点回退不可靠；`dc_noise.py`改为纯DC源、300µs回退并逐谱比对两条pass电流。早期startup后约6µV的noise无效，禁止引用；逐条pass电流检查也不等于逐个慢节点都已认证。
