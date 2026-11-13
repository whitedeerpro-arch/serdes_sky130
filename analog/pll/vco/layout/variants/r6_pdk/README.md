# r6 PLL 叶单元候选

这是当前 PLL 版图目标的工作迭代，不覆盖 Gemini 原始几何。采用与回测状态见[当前状态](../../../../../../docs/status/current.md)，目标/排布取舍见[PLL 版图推进](../../../../../../docs/layout/pll_r6.md)，原始证据见[结果索引](../../../../../../results/catalog/pll_layout_r6.json)。

`pll_vco_cap_unit_r6_pdk.mag` 是收紧底板接触的候选：MIM 仍为 2×2 µm，NMOS 为两指各 0.75 µm、共享漏极，MIM 上极板接 `node`，下极板接共享漏极；`en` 为栅，源/体接 `vss`。MIM 的有效器件来自 PDK，底板接触改为单 via3、小 M4 landing 与 L 形 M3。必须同时评价关断寄生和后续阵列路由，不能仅凭面积采用。

`pll_vco_varactor_clean.mag` 保留 Gemini 的四指主体、栅环、控制极走线和保护环，撤下穿入保护环的两根 dummy 及其专用连接；它们不属于当前参考中的有效器件。后续若重加边缘 dummy，需要重新安置接触并复核电气匹配，不恢复原来的非法交叠。

两份 `*_ref.spice` 仅将设计侧叶单元顶层名改成候选名，未改器件来凑匹配。重新生成到新结果目录：

```bash
uv run python analog/pll/vco/layout/build_r6_cap_unit.py --compact-bottom --output-dir results/layout/pll_r6/cap_unit_new
uv run python analog/pll/vco/layout/build_clean_varactor.py --output-dir results/layout/pll_r6/varactor_new
```

单元/放置对照与边界回测：

```bash
uv run python analog/pll/vco/tb/layout_cap_unit/run.py --layout candidate=results/layout/pll_r6/cap_unit_new/pll_vco_cap_unit_r6_pdk_pex.spice --output-dir results/layout/pll_r6/cap_ac_new
uv run python analog/pll/vco/tb/layout_cap_unit/ends.py --pex results/layout/pll_r6/cap_unit_new/pll_vco_cap_unit_r6_pdk_pex.spice --output-dir results/layout/pll_r6/cap_ends_new
```

端点台只替换半单元；不包含实际阵列、环内连线、完整提取 VCO 或 PLL 闭环。`--resume` 只补缺的角，输入身份变化须用新目录。
