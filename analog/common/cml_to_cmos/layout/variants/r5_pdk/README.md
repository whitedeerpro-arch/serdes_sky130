# r5 全速 CML→CMOS 候选

**几何交付已独立复核；电气状态为 changes requested，未采用。** `LAYOUT-PLL-RX-R5-01`：SS / 1.65 V / −40°C 的原生 RC 输出不翻转。CPEX 同条件通过，尚不能区分提取近似、AC 自偏置初态与实际分布 RC 的贡献；不得将这一观测记为低质量通过或已确认实际版图根因。

[复核与固定证据](../../../../../../results/catalog/pll_pending_receiver_review_20261117.json) · [跨模块结论](../../../../../../docs/layout/pll_pending_review_20261117.md) · [历史过程](../../../../../../docs/history/cml_to_cmos_r5_layout_notes_20261117.md)。

## 布局与身份

现行 `.mag` 为 82.21×27.60 µm，7 个端口 `inp inn outp outn vbias vdd vss`。独立 full-rule DRC=0、LVS 唯一匹配，无属性/断开端口错误；生成器重建的几何和参考逐字相同，EXT 未发现浮空非器件 poly。上下差分镜像，模拟增益级、耦合区和数字恢复链顺序直通；共享同电位护环和体接触合理，不再加逐管大环。数字回流与模拟输入在最终 PLL 中仍须独立检查。

耦合器件是 **M3–M4 单层 MIM**，不是 MIM1/MIM2 叠层。物理参考为 9×5.5 µm MIM 和每侧三颗 L6 电阻；研究原理图是 7×7 µm MIM 和单颗 L18 电阻。面积相近不等于周长寄生相同，三个电阻端头也不能等同一颗长电阻。本次 LVS 对各自明确的物理参考，不宣称该版图与研究原理图完全等价。r5 AC 耦合适用于连续全速时钟，不能替代 DC 数据电平转换。

## 已有波形复核

固定 20261117T1451Z campaign 的 19 份执行回执、deck 哈希、日志状态、有限波形及真实终点均已核对，未重跑瞬态：

- 六个局部条件：CPEX 6/6 达到 2 GHz、占空比 0.45–0.55 及 0.2/0.8 VDD 电平筛查；原生 RC 为 5/6，冷角失败保留。
- r5 CPEX → CMOS ÷8 CPEX 七点：重新同时检查 clk、q2、q4、q8 的正负两端、逐周期缺/多沿、电平及占空比，7/7 通过。每端输出负载为 q2/q4 15 fF、q8 20 fF。
- `input_pp=0.3` 是上游正弦激励参数，输入经过实际 CML buffer 放大，不是接收器端钳定 300 mVpp；实际输入摆幅在 JSON 中逐点记录。六点 standalone 输出每端 20 fF。

这些旧 deck 仅按 MOS 角加载模型。七点 summary 中的 hh/ll 是未执行的标签，不能当作无源角覆盖；回执的 `inputs_sha256` 为空，运行时 include 内容身份也未固定，不能补签历史输入哈希。以上是完整波形的观测复核，不是可追溯的全 PVT/完整 RC 签核；45 点 CPEX 与 PEX MC 尚未完成。

## 新运行入口

```bash
uv run python analog/common/cml_to_cmos/layout/build_cml_to_cmos_r5_pdk.py \
  --output-dir results/layout/cml_to_cmos/r5_new
uv run python analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py \
  --stage 6corners --campaign results/analog/common/cml_to_cmos/r5_new --workers 2
```

新 bench 冻结 include 和每工况 deck 身份，拒绝旧可变输入 campaign 的静默复用；联调显式加载指定无源角，检查双极性，并按 analysis/plots 追加结果。MC 没有有效翻转时也可完整记录失败。改变输入、终点或激励须新建 campaign。本次只修复入口，未启动 45 点/MC 或原生 RC 长仿真。下一步先区分冷角失败机理，再决定所需补测；候选、采用状态与项目门槛分开。
