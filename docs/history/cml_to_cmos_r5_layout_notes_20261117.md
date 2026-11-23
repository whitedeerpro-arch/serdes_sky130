# CML→CMOS r5 版图与 CMOS ÷8 联调纪要（2026-11-17）

本页是过程纪要，不是模块当前入口。r5 的采用状态待 45 角 CPEX 与 PEX MC 完成后，再写入 `analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md` 并汇总到 `docs/status/current.md`。

后续独立复核已将当前状态写入[模块入口](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md)，r5 保持 changes requested，未采用。下面是当时过程：复用模拟生成器不能豁免集成 DRC；七点联调旧 hh/ll 标签未实际加载，且旧 include 没有运行时内容哈希。这些限制与冷角 RC 功能失败见[复核报告](../layout/pll_pending_review_20261117.md)，不沿用当时的扩大解释。

## 1. 本轮实际工作流

```mermaid
flowchart LR
  A["原理图改进 r5<br/>(AC 耦合 + 自偏置 + 弱交叉耦合)"] --> B["原理图 45 角 + 200 样本 MC<br/>(带 PEX 估计节点电容)"]
  B --> C["版图生成器<br/>build_cml_to_cmos_r5_pdk.py"]
  C --> D["DRC / LVS 迭代<br/>v1 → v2 → v3"]
  D --> E["review_cell.py --rc<br/>独立复查 + Magic RCX"]
  E --> F["6 极端角 CPEX vs RCX"]
  F --> G["7 角后仿联调<br/>r5_pdk → cmos ÷8 pdk"]
  G --> H["45 角 CPEX + PEX MC<br/>(未完成)"]
  H --> I["README / current.md"]
```

- 原理图阶段在测试台里加上**按 PEX 估计的节点电容**（`Cfp=7f, Cap=4f, Cbp=3f, Crawp=3f`）再跑 PVT 和 MC。r4 的教训是纯原理图结果过于乐观。
- 版图生成器复用 r4 的模拟半边（`import build_cml_to_cmos_r4_pdk as r4`），只新写耦合区和数字半边，所以模拟部分不用重新验证 DRC。
- DRC 迭代时先用 Magic `drc listall why` 导出**每条规则的坐标**，再按坐标对应到代码行修改，不按规则名猜。
- 后仿脚本：[verify_r5_pdk.py](../../analog/common/cml_to_cmos/tb/r5_pex/verify_r5_pdk.py)，分 `6corners / chain_div8 / 45corners / mc` 四个阶段，用 `spice.case_output` 按工况断点续跑。

## 2. 结果快照（只列本轮实际看到的数字）

| 项目 | 结果 | 证据 |
|---|---|---|
| ÷8 CMOS 预分频 `pll_cmos_prescaler8_2g_pdk` | DRC 0、LVS 匹配、面积 1032.33 µm²；后仿 r4_pdk→÷8 45/45 PASS | [README](../../results/catalog/retired_pre_release_20261123.json) |
| r5 原理图 `ss_v1650_t-40_mm` | 200/200 翻转，199/200 占空比合格（v4_1d_final PEX 只有 51/200 翻转） | `results/analog/common/cml_to_cmos/fullrate_pvt/20261117T004128Z_r5_pvt45_and_tt_mc/` |
| r5 版图 v1 | 82=82 器件，DRC 60 处（8 条规则），网络 45 vs 43 | `results/layout/cml_to_cmos/20261117_r5_v1/` |
| r5 版图 v2 | **LVS 匹配**；DRC 剩 via3 尺寸 + capm.11 | `results/layout/cml_to_cmos/20261117_r5_v2/` |
| r5 版图 v3 | **DRC 0 / LVS 匹配 / 无属性错误**，82.21×27.60 µm = 2269.0 µm² | [summary.json](../../analog/common/cml_to_cmos/layout/variants/r5_pdk/summary.json) |
| 独立复查 + RCX | `physical_passed=true`，`devices_preserved=true`，提取电阻 1553 个；inp/inn 4.063/4.063 fF，outp/outn 1.552/1.552 fF | `results/layout_review/cml_to_cmos_r5_20261117T1448Z/` |
| 6 极端角 CPEX（0.3 Vpp） | **6/6 PASS**，占空比 0.4570–0.4998，功耗 3.89–10.47 mW | `results/analog/common/cml_to_cmos/r5_pdk/20261117T1451Z/summary_6corners.json` |
| 6 极端角 RCX（0.3 Vpp） | **5/6**；`ss_v1650_t-40` 不翻转（outp=0、outn=VDD） | 同上 |
| 7 角后仿联调 r5_pdk→÷8 pdk | **7/7 PASS**；q2 0.454–0.511，q4 0.471–0.516，q8 0.486–0.516；Pdiv 1.07–1.71 mW | `summary_chain_div8.json`、`waves_r5_div8_7corners.png` |

## 3. 近期经验

### 版图 / DRC
- **SKY130 MIM 电容 `capm.11`**：mimcap 到无关 M3 至少 1.34 µm。电源立柱、via3 焊盘、跳线都要算进去，放耦合区前先把这个间距留够（r5 最后是 bay 加宽到 17.1 µm，出线点放在 `x_bay_cx + 7.1`）。
- **via3** 切口必须 0.32 µm（规则是 `via3.1 + 2×via3.4`），M3/M4 焊盘 0.52×0.52 才满足 `met3.6` ≥ 0.24 µm²。r4 的 `via3_pad` 用的是 0.44 焊盘，单独放时会违规。
- **漏极干线偏移要与实际叉指一致**：`p_nf=2` 时漏极在 0.00。v1 写成 +0.24，结果同时引出 `li.6`（viali 下面是孤立 li 小块）和 LVS 断网。**一个 DRC 小错和一个 LVS 断网同源**的情况值得先查。
- N-well 包 N-tap 至少 0.18 µm；相邻区域的 nwell 在墙处只多出 0.07 µm 时就会报 `diff/tap.10`。墙两侧的阱边界要按 `V_TAP_WALL + 余量` 计算。
- 列间距太紧时，栅连线不要在 li 上横跨相邻管的扩散区，改走 M1 到列隙再拐下来（qpa.G 的处理方法）。

### 工具
- Magic 批处理里写 `select top cell`。写成 `select top box` 会让 `magicdnull` 一直挂住。直接调用 `magic` 时要带 `stdin=DEVNULL`，最好走 `magicutil.run_magic`，否则会碰到 Tcl `init.tcl` 找不到或挂起的问题。
- `spice.case_output(campaign, case_name, wave_name, t_end)`：第二个参数是**工况目录名**，不是 deck 文本。
- `clock.edges(t, y, polarity=±1, start=, stop=)`，没有 `kind=` 参数。

### 后仿判读
- CPEX 与 Magic 原版 RCX 在关键模拟节点上的电容差别明显（RCX 会重新分配或接地部分耦合电容）。例如 `a_451_230#` 是 12.42 fF 对 7.26 fF，`a_6693_1884#` 是 9.34 fF 对 3.96 fF。所以两者要**一起看**，不能只用其中一个签核。
- RCX 在 `ss_v1650_t-40` 0.3 Vpp 下不翻转，CPEX 同一工况通过。原因**还没定位**，可能是 AC 耦合 / 自偏置节点的初始状态或 RC 分布。不能把它说成"低质量通过"，按规格政策它算功能失败，要追。

### 流程
- 本机会意外重启（这次 18:11 也停过一次后台任务）。长扫描要拆成按工况的独立目录，只补缺的工况；本轮 6corners、chain_div8 都按这个方式落盘。
- 汇报时只报实际跑出来的数字。中间失败（v1/v2 DRC、RCX 5/6）也照实列出。

## 4. 待办（按顺序）
1. 定位 RCX `ss_v1650_t-40` 不翻转：先加 0.4 Vpp 和更长的 tran（排除启动），再对比 ap_ac / bp 节点的偏置。
2. 45 角 CPEX（`--stage 45corners`）。
3. 200 样本 PEX MC：`tt_v1800_t27_mm`、`ss_v1650_t-40_mm`（`--stage mc`，8 样本/块）。
4. 写 `variants/r5_pdk/README.md`，再更新 `docs/status/current.md`。
