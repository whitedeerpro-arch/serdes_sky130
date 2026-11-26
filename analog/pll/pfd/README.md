# PFD 鉴频鉴相器与相位窗口（`analog/pll/pfd/`）

4.0 Gb/s PLL v4 主线与 5.0 Gb/s Plan-C 共享的标准单元三态鉴频鉴相器 **`pll_pfd_sc_dly`** 及锁定检测相位窗口单元。`UP` / `DN` 高有效，`rst_b` 低有效，参考与反馈均为 1.8 V CMOS。详细验证边界与失配 MC 数据见 [docs/design/pll_loop.md](../../../docs/design/pll_loop.md) 与 [docs/status/current.md](../../../docs/status/current.md)。

## 现行源码、版图与测试台

| 文件 / 目录 | 角色与状态 |
|---|---|
| [`spice/pfd_sc.spice`](spice/pfd_sc.spice) | **主线 `pll_pfd_sc_dly`**：基于 `sky130_fd_sc_hd`（`2× dfrtp_1` + `nand2_1` + `2× inv_1` + `dlygate4sd1_1` + `and2_1` + `inv_4→inv_8`），消除 `dfrtp_1` removal 违例，SF/SS 冷角 200 样本失配 MC `0` 卡死、无死区 |
| [`spice/phase_window_pdk.spice`](spice/phase_window_pdk.spice) | 无计数器锁定检测相位窗口单元（45 条件门限 `225–750 ps`，`≥ 2.7×` 静态相差上界） |
| [`layout/README.md`](layout/README.md) · [`layout/variants/pdk/`](layout/variants/pdk/README.md) · [`layout/review.md`](layout/review.md) | `build_pfd_sc_pdk.py` 生成的标准单元 PDK 版图（`DRC=0 / LVS=MATCH`）与物理审阅 |
| [`tb/pfd_cp_sc/run.py`](tb/pfd_cp_sc/run.py) | 7 角名义 PFD + CP 零相位增益与复位脉宽验证 |
| [`tb/pfd_cp_mc/run.py`](tb/pfd_cp_mc/run.py) | PFD + CP 零相位附近局部失配 MC 与死区检查 |
| [`tb/layout_pex/run.py`](tb/layout_pex/run.py) | PFD 后仿寄生回测脚本 |

运行结果追加写入 `results/analog/pll/pfd/`。
