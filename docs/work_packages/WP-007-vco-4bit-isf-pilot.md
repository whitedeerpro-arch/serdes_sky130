# 四位 VCO 首轮 ISF：准备边界

历史任务包，当前不自动派发或续跑，也不作为 r6 相噪资格。下文的固定 campaign 与成本仅对应当时实验；现行 runner 已增加显式历史尺寸覆盖，输入身份变化时不能用新脚本恢复旧快照。实际任务释放查[执行计划](../status/prelayout_plan.md)，工具修正见[复核记录](../verification/pll_review_tools_20261117.md)。

先读[公共交付约定](README.md)。本包由集成者统一调度，最多一个ngspice；执行者不得另起同campaign或修改DUT、共享库、旧三位测试。允许改动为新runner `analog/pll/vco/tb/phase_noise/isf_4b_pilot.py`、其离线测试及本包交付目录。原始运行只追加到专用 `results/analog/pll/vco/phase_noise_isf_4b/`。

目标是 TT 1.8 V 27 °C、真实带隙偏置及 PDK Rtt、四个输出 buffer 每个差分输出各 30 fF、四位 bank K=6、开关 W=2.5 µm 的单点 VCO ISF。它是 ungraded 器件级试验，不是 PLL 全环路噪声或 PVT、抖动签核；旧三位 bank 的结果不可混入。

现有 `phase_noise/isf.py` 模板固定三位 bank，`corner.py` 也是三位配置及无边界 secant 调谐，均不能原样用于该任务。`vco_pn.py` 使用 rp 热噪声与 mp、mt 的器件热噪声和拟合闪烁噪声，假定四级对称；它依赖另一个器件噪声表，不应直接用旧三位结果冒充当前电路。当前 rp/mp/mt 注入点没有单独覆盖四位 bank 开关、变容器、载入 buffer 器件的噪声和它们的闪烁/热噪声；器件相关噪声、偏置/供电与控制端噪声、耦合及 PLL 其他噪声还需独立量化，不能把该 ISF 包当完整预算。

先在 Vctrl=1.195 V 测频，瞬态 24 ns、最后 5 ns 测频，前 14 ns 不取数据；该值是当前码表值，频率未实测之前不称 2 GHz。如果偏差超过 1%，只能在已实测频率包围目标的 Vctrl 区间内选点并重测，不能外推；没有有效包围时停下报告。测得真实周期后，以独立 1 ns 单 site 冒烟（不进入统计），再在 rp/mp/mt 三个 site 各跑一次：settle 至少 14 ns、32 相位、每 10 周期注入、覆盖 1.25 周期、电荷 0.5 fC。site 级断点续跑必须验证源、PDK、实际 deck 和 execution 身份及各自波形实际终点；分析只追加，最大相位空隙大于 0.08 则 incomplete/ungraded。

独立 runner 为 `analog/pll/vco/tb/phase_noise/isf_4b_pilot.py`。使用 `--prepare` 建立固定快照，再用 `--check <campaign>` 验证源、PDK 和 deck；两者不运行 ngspice。经集成者调度后用 `--resume <campaign>` 才依序运行冒烟、测频校准和三 site。校准与 site plan、分析均追加记录；续跑只复用身份匹配且波形达到实际终点的结果。未夹住目标或五次内插仍未达 1% 时停止并记录 calibration_required。原始三位脚本、模板与共享库保持原样。

本轮固定campaign为`results/analog/pll/vco/phase_noise_isf_4b/20261109T140720.206962Z_be7f42ae`。使用`--check`验证后续跑此目录，不按最新时间查找。四位bank仍依赖`cap_bank_3b.spice`中的公共`pll_vco_cap_unit`定义，保留该include不等于实例化旧三位阵列。

交付`docs/work_packages/deliveries/WP-007/`的`evidence.json`、`summary.md`、`handoff.md`：列明plan、calibration、site-plan、三个逐site结果与原始deck/ex/raw哈希；复算实际周期、32个相位、环绕gap和h的均值/均方根。缺测、截断、无有效夹区或phase-gap失败必须保留，不能补零或称噪声通过。单site上限至少1800s，具体值保存在运行器；三个site成本粗估10–20分钟，当前四位版本实际成本尚待测量。超时逐项保留；完整性与电路资格分开。
