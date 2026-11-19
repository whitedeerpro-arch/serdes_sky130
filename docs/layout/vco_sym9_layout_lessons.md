# Ring VCO + CML Buffer 版图设计经验与模型绘图准则（2026-11-15）

**紧凑 Ring VCO＋四路缓冲核的几何为 108.6 × 79.8 µm，原型 DRC/LVS 通过；2026-11-15 独立审阅发现 216 个浮空 field-poly 岛，现有独立清理候选。物理布局、寄生后量程及启动数值边界以 [模块审阅](../../analog/pll/vco/layout/review.md) 为准，不能由本页的几何经验推定性能通过。**

本页汇总 `pll_vco_core_sym9_s32p5` 迭代过程中的物理架构决策、版图配平技巧与 DRC/LVS 避坑规范，供后续接手模型直接复用。

---

## 1. 交付产物与验证基线

| 层级单元 | 生成脚本 | 规划脚本与图 | 版图渲染图 | 尺寸与面积 | 验证状态 |
|---|---|---|---|---|---|
| 5-bit 9 块融合电容阵列 (`pll_vco_cap_bank5_sym9_s32p5`) | [build_cap_bank5_sym9_pdk.py](../../analog/pll/vco/layout/build_cap_bank5_sym9_pdk.py) | [plan_cap_bank.py](../../analog/pll/vco/layout/plan/plan_cap_bank.py) / [cap_bank_plan.png](../../analog/pll/vco/layout/plan/cap_bank_plan.png) | cap_bank5_sym9_w075.png (`../../analog/pll/vco/layout/variants/sym9_pdk/views/cap_bank5_sym9_w075.png`, retired in `retired_legacy_vars_20261120.json`) | `37.48 × 16.70 µm` (`625.92 µm²`) | `DRC = 0, LVS = True` |
| 含嵌合变容管半谐振腔 (`pll_vco_half_tank_sym9_s32p5`) | [build_half_tank_sym9_pdk.py](../../analog/pll/vco/layout/build_half_tank_sym9_pdk.py) | [plan_delay_stage.py](../../analog/pll/vco/layout/plan/plan_delay_stage.py) | half_tank_sym9_s32p5.png (`../../analog/pll/vco/layout/variants/sym9_pdk/views/half_tank_sym9_s32p5.png`, retired in `retired_legacy_vars_20261120.json`) | `38.18 × 16.70 µm` (`637.61 µm²`) | `DRC = 0, LVS = True` |
| 单级 Delay + CML Buffer + 8 列电阻核 (`pll_vco_delay_buf_sym9_c`) | [build_vco_core_sym9_pdk.py](../../analog/pll/vco/layout/build_vco_core_sym9_pdk.py) | [plan_vco_core_buf.py](../../analog/pll/vco/layout/plan/plan_vco_core_buf.py) / [vco_core_buf_plan.png](../../analog/pll/vco/layout/plan/vco_core_buf_plan.png) | delay_buf_core_sym9_c.png (`../../analog/pll/vco/layout/variants/sym9_pdk/views/delay_buf_core_sym9_c.png`, retired in `retired_legacy_vars_20261120.json`) | `37.81 × 34.88 µm` (`1,318.81 µm²`) | `DRC = 0, LVS = True` (10 器件 / 11 网络) |
| 4 级 Ring VCO 裸核 (`pll_vco_ring4_sym9_s32p5`) | [build_vco_ring4_sym9_pdk.py](../../analog/pll/vco/layout/build_vco_ring4_sym9_pdk.py) | [plan_vco_ring4.py](../../analog/pll/vco/layout/plan/plan_vco_ring4.py) / [vco_ring4_plan.png](../../analog/pll/vco/layout/plan/vco_ring4_plan.png) | vco_ring4_sym9_s32p5.png (`../../analog/pll/vco/layout/variants/sym9_pdk/views/vco_ring4_sym9_s32p5.png`, retired in `retired_legacy_vars_20261120.json`) | `101.0 × 79.8 µm` (`8,059.80 µm²`) | `DRC = 0, LVS = True` (172 器件 / 93 网络) |
| 4 级 Ring VCO + 4× CML Buffer 完整核 (`pll_vco_core_sym9_s32p5`) | [build_vco_core_sym9_pdk.py](../../analog/pll/vco/layout/build_vco_core_sym9_pdk.py) | [plan_vco_core_buf.py](../../analog/pll/vco/layout/plan/plan_vco_core_buf.py) / [vco_core_buf_plan.png](../../analog/pll/vco/layout/plan/vco_core_buf_plan.png) | vco_core_sym9_s32p5.png (`../../analog/pll/vco/layout/variants/sym9_pdk/views/vco_core_sym9_s32p5.png`, retired in `retired_legacy_vars_20261120.json`) | `108.6 × 79.8 µm` (`8,666.28 µm²`) | `DRC = 0, LVS = True` (192 器件 / 105 网络) |

---

## 2. 模拟版图架构与布局配平准则

### 准则 1：Plan-First（先几何规划与冲突审计，再写 PDK 脚本）

- 在动手拼装 `.mag` 之前，先在 `analog/pll/vco/layout/plan/` 下用轻量 Python 脚本画出所有子模块的**精确外框（含 `pwell` / `psubdiff` 护环边界）、引脚坐标与跨层走线走廊**，导出 `.json` 与 `.png`。
- 在规划阶段直接校核三件事：
  1. **同层器件是否有 `pwell / nwell / psubdiff` 重叠或净空不足**（同电位 `psubdiff` 可直接共边重叠，不同模块留 `≥ 0.32 µm` 裕量）；
  2. **跨层叠放是否正交无冲突**（例如 MIM 电容仅占 `M3/capm/M4`，其正下方是否只放 `poly/diff/li/M1/M2`）；
  3. **四象限旋转/镜像后端口极性与对称性是否严格自洽**。

### 准则 2：三维层间复用（MIM 电容叠放于 Poly 电阻与变容管上方）

- SKY130 的 `sky130_fd_pr__cap_mim_m3_1` 位于 `metal3`、`capm` 与 `metal4` 层，与底层有源区/多晶硅完全隔离。
- **不要把 MIM 电容、变容管、Poly 负载电阻平铺在互不重叠的二维平面上**：
  - 将 Half-Tank 旋转 90° 后向内嵌合，使 `b2 / b3 / b4` 的 MIM 电容直接悬停在负载电阻阵列（`Xrp1, Xrp2, Xrn1, Xrn2, Xbrp, Xbrn` 及外侧电阻 Dummy）和 `cap_var_lvt` 变容管上方（`M3/M4`）；
  - 仅需将电容的 NMOS 开关（`ndiff/poly/li/M1/M2`）排布在电阻与变容管护环外侧，即可消除大块空白，单级宽度压缩约 38%。

### 准则 3：尾电流管内侧紧贴共护环（`[Xbmp | Xbtail_L | Delay_Xt | Xbtail_R | Xbmn]`）

- 当同一象限包含主电路尾电流管（`Delay_Xt`）与缓冲器尾电流管（`Xbtail`）、缓冲器差动对（`Xbmp, Xbmn`）时：
  - 将缓冲器尾电流管一分为二（`Xbtail_L, Xbtail_R`），**紧贴中央 `Delay_Xt` 布置在对称轴内侧**，再将缓冲器差动对 `Xbmp, Xbmn` 紧贴在两侧外缘；
  - 相邻模块的竖直 `psubdiff/locali` 护环边（宽 `0.17 µm`）直接重合共边：
    $$\Delta x = w_{\text{half},A} + w_{\text{half},B} - 0.17\ \mu\text{m}$$
- **内侧布置尾电流管的三大收益**：
  1. 3 个共享 `vbias` 的尾电流管全部聚集在轴心 `x_stage ∈ [-4.31, +4.31] µm`，底部仅需一根 `metal1` 短横条直连，彻底省去跨越差动对的 `M3` 桥接；
  2. `Xbtail_L/R` 漏极与外侧 `Xbmp/Xbmn` 源极在同一高度（`y_stage = -10.80 µm`）由单根 `metal2` 横条（`tail_buf`）直连；
  3. 5 个有源块合一后总宽仅 `18.43 µm`，完整落在变容管与底部 `b4` 电容之间的中央净空窗内。

### 准则 4：原型 Dummy 配置与独立复核修正

原型按主器件栅长在差分管（0.15 µm）、长尾管（0.50 µm）及变容器旁放了 field-poly 条，但没有形成有效接触。栅长相同不等于 dummy 配置完成；这批浮空条在独立候选中撤下。以后若需要该工艺密度，应先规划接触、明确偏置及护环间距，再重新 DRC/LVS/PEX，不在狭窄护环内直接加条或以几何重叠声称已经接地。

电阻外侧保留接地的全尺寸 poly dummy（原型位置 `x_stage = ±16.65 µm`，与 buffer 负载外形相近），支持 poly 蚀刻环境补偿；它们没有与有效高阻器件相同的完整注入标记，不能宣称完整工艺密度或系统失配已经合格。保护环合并、尾管聚拢和 MIM 叠放的总体布局可继续使用。

### 准则 5：金属层正交分工与顶层 M4 飞线

| 金属层 | 主导方向与职责 | 关键避让关系 |
|---|---|---|
| `locali` + `metal1` | 器件内部源/漏分离引出、尾电流 `vbias` 栅极短接、中央 8 相交叉网**竖向**走线 | 严禁同层跨越水平 `M1` 栅极母线；多指管 S/D 必须在上下半区分开截断 |
| `metal2` | 器件源/漏水平汇流条、电容开关源/漏引出、中央 8 相交叉网**横向**走线、全局对称 `VSS` 主干 | 中央交叉网只用 `M1 + M2`，不占 `M3`，彻底消除与中央 MIM 电容的层冲突 |
| `metal3` | 电容下极板、象限内振荡节点竖直主干（自动跨接 Buffer 输入栅）、5 根 `cfg0..cfg4` 垂直控制总线 | 象限内侧左右两半共用中央 5 根 `M3` 控制总线（`x ∈ [-1.40, +1.40] µm`） |
| `metal4` | 电容上极板、上下双端对称 `VDD/VSS` 环、`cfg0..cfg4` / `ctrl` / `vbias_q` 跨象限水平飞线 | 在 `[16.00, 36.10] µm` 区间用 `M4` 飞越象限内部 `M3` 主干，在中央走廊落回 `M2` 穿过 `M3` 总线 |

---

## 3. PDK 改版与 DRC / LVS 常见陷阱清单

1. **多指 MOS 管源/漏交错截断与 M1 包边**：
   - PDK 默认生成的 `nfet` 源漏 `viali + metal1` 贯穿整个沟道高度；若直接画水平 `M2` 源/漏母线，过孔会与相邻漏/源列间距不足。
   - **标准做法**：清除 `y ∈ [-W/2, +W/2]` 内的默认 `viali` 与 `metal1`，将源极列重建在下半区（如 `[-1.50, -0.50]`）、漏极列重建在上半区（如 `[-0.46, +1.40]`），且 **`metal1` 端头必须比 `viali` 外延 `≥ 0.06 µm`**，确保 100% 金属包边并给邻近栅极过孔留出 `≥ 0.14 µm` 的 `met1.2` 间距。
2. **裁剪双端栅极接触时切忌漏删 `locali / viali / metal1`**：
   - `conn_gates=1` 的 PCell 上下两端均有栅极接触；裁掉不需要的一端时，必须同时过滤掉该高度范围内的 `polycont`、`locali`、`viali`、`metal1` 并将 `poly` 截断至 `ndiff ± 0.18 µm`，否则残留的孤立金属块会引发隐蔽 DRC 或意外短接。
3. **提取引脚坐标时注意 PCell 双端同名标签**：
   - `tail.pins("G")` 可能返回顶部或底部任一标签坐标；连接单侧栅极母线时应显式按几何中心偏移（如 `tgy = grid(tail_y - 3.425)`）定位底部栅条，防止 `M1` 竖线穿过沟道和漏极母线造成 `vbias - tail - vss` 短路。
4. **跨层级 `via1_2` 下落位置必须避开子单元内部 `M1 / M2` 母线**：
   - 从 `M3` 竖直主干通过 `via1_2` 切换到 `M1` 进入中央交叉网时，不能在下排晶体管紧邻处（如 `y_stage = -12.60 µm`）直接落孔——该处恰有 `ts_y = -12.45 µm` 的 `M2` 地母线与 `tgy = -13.225 µm` 的 `M1` 偏置母线；
   - **标准做法**：让 `M3` 竖线直接飞越整个有源与电源母线区，统一在子单元外侧的净空走廊（如 `y_ring = ±2.40 µm`）落 `via1_2` 转入 `M1`。
