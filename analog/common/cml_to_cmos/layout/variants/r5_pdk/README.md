# r5 全速 CML→CMOS 候选（v6 已修复冷角 RCX 与 MC 离散）

现行版图已升级为 **v6**（`Xbp` 改用 LVT NMOS、去除了在冷角失效并放大失配的 `Xk_rp/Xk_rn + restorer_r5`、后端改为居中平衡 2 级 CMOS 缓冲，并将 `XCac` 竖放压缩横向宽度），本地独立复查与全套 PEX 电学门槛（含 CPEX vs Magic 原生 RCX 极端角、45 角 PVT、200 样本 `ss_v1650_t-40_mm` MC 与 `/8` CMOS 分频器 7 极端角冷上电联调）全部通过；整机 PLL 闭环及高低温耦合 RC 全链仍按顶层计划另行复核。

- 历史基线记录（v3 未采用前）：[复核与固定证据](../../../../../../results/catalog/pll_pending_receiver_review_20261117.json) · [跨模块结论](../../../../../../docs/layout/pll_pending_review_20261117.md) · [历史过程](../../../../../../docs/history/cml_to_cmos_r5_layout_notes_20261117.md)
- v6 独立复查：[rc_summary.json](../../../../../../results/layout_review/cml_to_cmos_r5_20261118T1445Z_v6/rc_summary.json)
- v6 验证活动：`results/analog/common/cml_to_cmos/r5_pdk/20261118T1457Z_v6/`

## 布局与身份

现行 `.mag` 为 **54.49×27.60 µm（1503.92 µm²，较 v3 的 2269.02 µm² 缩小 33.7%）**，7 个端口 `inp inn outp outn vbias vdd vss`。full-rule `DRC=0`、`LVS_MATCH=True`、`LVS_PROPERTY_ERRORS=False`；独立 [review_cell.py --rc](../../../../../../verification/layout/review_cell.py) 复查 `physical_passed=true`、`devices_preserved=true`，提取 142 个 MOS 段落与 1087 个原生约简电阻，`.ext` 零悬空节点，端口电容 `inp/inn=4.063/4.063 fF`、`outp/outn=1.522/1.517 fF`。

耦合电容 `XCac_p/n` 为 **M3–M4 单层竖放 MIM（`w=5.0, l=9.9 µm`，不占用 M5）**，每侧串联三折 `sky130_fd_pr__res_high_po_0p35`（L=6 µm）。数字区为 `Xbp/Xbn`（4.5 LVT-N / 10.0 P）+ `Xk_bp/Xk_bn`（0.6/1.2）→ `Xop/Xon`（3.6/6.4）→ `Xm1p/Xm1n`（1.8/6.0）+ `Xkc_p/Xkc_n`（0.42/1.0）→ `Xo1p/Xo1n`（3.2/8.0），与 [cml_to_cmos_r5.spice](../../../spice/cml_to_cmos_r5.spice) 和 LVS 物理参考 1:1 对齐。r5 AC 耦合适用于连续全速时钟（>= 1 GHz），不能替代 DC 数据电平转换。

## v6 验证摘要（20261118T1457Z_v6）

- **`6corners`（`input_pp=0.3` 上游缓冲输入，输出 20 fF）**：CPEX **6/6 PASS**（`duty = 0.4736–0.5242`），Magic 原生 RCX **6/6 PASS**（`duty = 0.4731–0.5271`，其中 `ss_v1650_t-40` CPEX `0.5240/0.5242`、RCX `0.5264/0.5271`）。
- **`chain_div8`（CPEX `r5_pdk` → CPEX `pll_cmos_prescaler8_2g_pdk`，7 极端角含无源角 `tt/hh/ll`，0.5 ns 冷上电斜坡 + `uic`）**：**7/7 PASS**（`clk=0.474–0.525`、`q2=0.454–0.517`、`q4=0.471–0.516`、`q8=0.486–0.516`，`Prx=2.27–8.06 mW`，`Pdiv=1.07–1.71 mW`；注 `sf_v1650_t-40` 用 t=0 DC 静态点会在对称 latch 处奇异，上电斜坡收敛无异常）。
- **`45corners`（CPEX 45 PVT，18 ns）**：**45/45 PASS**（`duty = 0.4736–0.5242`，`P = 2.16–8.04 mW`）。
- **`mc`（CPEX PEX 失配 MC，`input_pp=0.4`）**：
  - `tt_v1800_t27_mm`：**200/200 toggle，200/200 PASS**（`CI95=[0.9817, 1.0000]`，`duty_p = 0.4920 ± 0.0033`，`duty_n = 0.4922 ± 0.0035`，`tol9973 = [0.4807, 0.5038]`）。
  - `ss_v1650_t-40_mm`：**200/200 toggle，200/200 PASS**（`CI95=[0.9817, 1.0000]`，`duty_p = 0.5202 ± 0.0067 [0.5045, 0.5395]`，`duty_n = 0.5206 ± 0.0069 [0.5022, 0.5391]`，`tol9973 = [0.4980, 0.5433]`）。

限制说明：Magic 原生 `extresist` 将电容接地/约简近似，不等同于真实分布耦合 RC；原生 RC 侧蒙特卡洛、`0.3 Vpp` 蒙特卡洛及 PLL 闭环顶层联调尚未在本单元 bench 内覆盖。

## 运行入口

```bash
uv run python analog/common/cml_to_cmos/layout/build_cml_to_cmos_r5_pdk.py \
  --output-dir results/layout/cml_to_cmos/r5_new
uv run python analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py \
  --stage all --campaign results/analog/common/cml_to_cmos/r5_new --workers 4
```

`verify_r5_pdk.py` 冻结 include 与每工况 deck 身份、校核 `RC` 输入矩阵与原图一致性，并支持断点续跑；更改输入/参数时必须使用新 campaign 目录。
