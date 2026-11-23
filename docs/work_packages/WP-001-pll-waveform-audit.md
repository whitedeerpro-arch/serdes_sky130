# WP-001：PLL 冷角原始波形只读复核

你是局部证据复核执行者。目标是独立重算两个已有工作态测试，不设计电路、不启动仿真。工作目录是 本仓库根目录；环境命令用 `uv run python`。遵守[工作包约定](README.md)。

## 输入

只复核以下两例，不自行扩展到其他 campaign：

- ll：`results/analog/pll/convergence/20261106T151716Z/ff_v1950_t-40_ll_frontend_sparse_prebiased_native/`
- hh：`results/analog/pll/convergence/20261106T152241Z/ff_v1950_t-40_hh_frontend_sparse_prebiased_native/`

每个目录读 `tb.cir`、`execution.json`、`simulator.log`、`waveforms.raw`。另读 `src/serdes_flow/clock.py`、`src/serdes_flow/spice.py`、`config/boundary_conditions.json` 中 `pll_r5_cold_prebiased_state_v1`。上下文限定为 FF、1.95 V、−40 °C，固定码/Vctrl，真实偏置/PDK 电阻，明确的偏置就绪 `.ic/uic` 初始电压。不能称为真实上电或 PLL 闭环。

## 步骤与固定算法

1. 对所有读入文件记 SHA256。检查 `execution.json.deck_sha256` 等于实际 `tb.cir` 哈希；列出退出码、超时、原日志末尾及实际 tran 行/模型 `.lib`。从原始 deck 判断是否有 `uic`/`.ic`，不只读 summary 标签。
2. 用 `spice.Waves` 检查 raw 数据全部有限、时间严格递增，末点到达 24 ns（允许相对误差 1e-7）。缺失/截断例保留，后续测量标 missing。
3. 统一在 **8–24 ns** 测量所有频率，使用公共 `clock.period_stats`。VCO 是 `xpll.v0p-xpll.v0n`；÷2/4/8 是 `p02p-p02n`、`p04p-p04n`、`p08p-p08n`。每级频率与 VCO/k 的相对误差 ≤1% 是本包的功能检查，不是抖动验收。
4. 全速 CMOS 是 `c0p/c1p/c2p/c3p`，反馈是 `fb0/xpll.fb1/xpll.fb2/xpll.fb3`。先减 VDD/2 再提边沿。全速频率相对 VCO ≤1%，占空比45–55%，低电平<0.2VDD、高电平>0.8VDD；反馈频率相对 VCO/8 ≤1%，只核对电平与频率，不增设未规定的占空比门槛。
5. 补逐沿关系：用 `clock.edges` 取得测量窗内 VCO 与每级分频的正沿。仅取被两侧 VCO 正沿包围的分频边沿，以 `np.interp(edge, vco_edges, np.arange(len(vco_edges)))` 得连续参考周期序号，相邻分频边沿序号差应为 k±0.25。保存全部差值和异常索引；不足2个间隔标 ungraded。0.25是宽松的漏沿/多沿诊断门槛，不能称为相位噪声或抖动指标。不要屏蔽窗内前几个坏点。
6. 幅度、CMOS峰值、两例差异只报告，不额外放宽/定义规格。不调用先前 `summary.json` 的 metrics 代替重算，也不修改历史文件。

## 唯一允许输出

- `verification/work_packages/wp001_pll_waveforms.py`：支持 `--output DIR`，不启动仿真；输出 evidence JSON，默认写自己的交付目录。用 `ROOT` 解析仓库输入，公共测量函数直接复用；异常记录到对应检查，进程对真实失败返回非零，但仍写出完整报告。
- `docs/work_packages/deliveries/WP-001/evidence.json`
- 同目录手写 `summary.md`、`handoff.md`。

执行与自查：

```sh
uv run python verification/work_packages/wp001_pll_waveforms.py --output docs/work_packages/deliveries/WP-001
```

## 验收 / 升级条件

必须两例都出现，每例有原始完整性、deck身份、11项频率/电平功能检查和3项逐沿诊断，所有窗口/单位明确。若出现坏点，照实交付位置和相邻边沿；不得修测试使结果通过。输入不存在、变量名不符或算法有歧义时，记录精确命令/异常，交给集成者决定。不改共享库。工作区已有未提交内容，不 commit/reset/stash。
