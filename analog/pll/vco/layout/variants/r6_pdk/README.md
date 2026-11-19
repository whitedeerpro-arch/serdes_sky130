# r6 PLL 叶单元候选

这是当前 PLL 版图目标的工作迭代，不覆盖 Gemini 原始几何。采用与回测状态见[当前状态](../../../../../../docs/status/current.md)，目标/排布取舍见[PLL 版图推进](../../../../../../docs/layout/pll_r6.md)，原始证据见[结果索引](../../../../../../results/catalog/pll_layout_r6.json)。

`pll_vco_cap_unit_r6_pdk.mag` 是收紧底板接触的候选：MIM 仍为 2×2 µm，NMOS 为两指各 0.75 µm、共享漏极，MIM 上极板接 `node`，下极板接共享漏极；`en` 为栅，源/体接 `vss`。MIM 的有效器件来自 PDK，底板接触改为单 via3、小 M4 landing 与 L 形 M3。必须同时评价关断寄生和后续阵列路由，不能仅凭面积采用。

`pll_vco_varactor_clean.mag` 保留 Gemini 的四指主体、栅环、控制极走线和保护环，撤下穿入保护环的两根 dummy 及其专用连接；它们不属于当前参考中的有效器件。后续若重加边缘 dummy，需要重新安置接触并复核电气匹配，不恢复原来的非法交叠。

半单元与变容器的两份 `*_ref.spice` 仅将设计侧叶单元顶层名改成候选名，未改器件来凑匹配。重新生成到新结果目录：

```bash
uv run python analog/pll/vco/layout/build_r6_cap_unit.py --compact-bottom --output-dir results/layout/pll_r6/cap_unit_new
uv run python analog/pll/vco/layout/build_clean_varactor.py --output-dir results/layout/pll_r6/varactor_new
uv run python analog/pll/vco/layout/build_r6_shared_bank.py --output-dir results/layout/pll_r6/bank_new
uv run python analog/pll/vco/layout/build_r6_cml.py --kind delay --output-dir results/layout/pll_r6/delay_new
uv run python analog/pll/vco/layout/build_r6_cml.py --kind buffer --output-dir results/layout/pll_r6/buffer_new
```

单元/放置对照与边界回测：

```bash
uv run python analog/pll/vco/tb/layout_cap_unit/run.py --layout candidate=results/layout/pll_r6/cap_unit_new/pll_vco_cap_unit_r6_pdk_cap.spice --output-dir results/layout/pll_r6/cap_ac_new
uv run python analog/pll/vco/tb/layout_cap_unit/ends.py --pex results/layout/pll_r6/cap_unit_new/pll_vco_cap_unit_r6_pdk_cap.spice --output-dir results/layout/pll_r6/cap_ends_new
uv run python analog/pll/vco/tb/layout_cap_unit/bank_ac.py --pex results/layout/pll_r6/bank_new/pll_vco_cap_bank5_shared_cap.spice --reduced --output-dir results/layout/pll_r6/bank_ac_new
uv run python analog/pll/vco/tb/layout_cap_unit/ends.py --pex results/layout/pll_r6/bank_new/pll_vco_cap_bank5_shared_cap.spice --all-supplies --keep-full-wire --output-dir results/layout/pll_r6/bank_stress_new
```

端点台的3端口输入只替换半单元，7端口输入替换完整bank；均不包含完整提取VCO或PLL闭环。`--resume`只补缺的角，输入身份变化须用新目录。

`pll_vco_cap_bank5_shared.mag`及对应参考是新的同bit共底板候选。每个bit有一块浮动M3板和集中折指开关，31颗2×2 MIM与原总开关宽不变；这与原31个独立浮动板的参考有电气差异，不能称作原电路的LVS等价几何。五组分别检查，再检查整体和未合并器件数。生成器同时输出独立EXT矩阵的`_cap.spice`，用于上述局部台；旧工具产生的`_pex.spice`有节点错移，不能用于结论。

完整bank输入时，端点台默认按原12fF预算扣除bank已覆盖的连接，保留其余相位连线预算；`--keep-full-wire`则把12fF完整保留为额外负载压力。原理图与原r6全角证据不改，候选仍需全角窗口、切码动态及失配复核。实际几何及电容图见[bank图](../../../../../../docs/figures/layout/pll/pll_r6_cap_bank.png)。

`pll_vco_delay_r6_pdk`与`pll_buffer_r6_pdk`为当前参数的CML候选。输入各分为两个相同阵列，按ABBA排列、右半镜像；总宽与总指数保持不变，但拆组增加源端扩散，回灌必须使用实际AD/AS/PD/PS。各组保护环、负载体端接VSS，尾节点单独检查，输入路线长度和输出母线配平。延迟负载仍为每侧两颗2p85/L4.77，buffer负载按当前600Ω定宽映射4.135957 µm取实际可绘制的L4.14，未沿用旧版图参考的4.22。

同时回灌三个叶单元：

```bash
uv run python analog/pll/vco/tb/layout_cap_unit/ends.py --pex results/layout/pll_r6/bank_new/pll_vco_cap_bank5_shared_cap.spice --delay-pex results/layout/pll_r6/delay_new/pll_vco_delay_r6_pdk_pex.spice --buffer-pex results/layout/pll_r6/buffer_new/pll_buffer_r6_pdk_pex.spice --residual-wire-fF 0 --output-dir results/layout/pll_r6/leaves_ends_new
```

此处CML的`_pex.spice`须由已修复、已回归的批量Magic产生（含电阻体的正常导出语义），不同于旧工具的同名文件。`--residual-wire-fF 0`是未绘制跨块/环/变容器连线的最好情况边界；通过也不能作为完整相位或PLL版图资格。原来的约7%是仅bank回灌下的六个名义PVT/电阻角压力点频率余量，没有计入局部随机失配。

## 已撤销的旧大环

旧 `pll_vco_ring4_r6_pdk` 是错误方案，已从现行目录移除；生成器、整环导出和依赖它的顶层摆位草案不再作为候选。撤销清单及原件哈希见[清理记录](../../../../../../results/catalog/obsolete_vco_large_ring_20261115.json)。本目录独立的电容、变容器和 CML 叶单元保留，不代表旧整环可继续使用。

完整核的现行审阅入口为 [sym9 清理候选](../sym9_clean/README.md)，采用边界查[模块审阅](../../review.md)。
