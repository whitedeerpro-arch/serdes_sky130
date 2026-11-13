> **Gemini 来件，候选几何。** 以下原交付说明中的尺寸、器件类型、匹配和压降是作者声明，不是本项目验收结论。采用状态见[版图入口](../../../layout/README.md)；必须对当前设计侧 SPICE 独立做 full-rule DRC、LVS 与端口/器件值复核。

# 带隙基准与偏置分配子系统（`common/bias/layout`）版图设计说明

本目录包含 `common/bias/spice/bandgap.spice` 与 `common/bias/spice/bias_dist.spice` 中全部 10 个核心与伴随偏置子电路（共 12 个版图单元）的全定制版图实现（`.mag` 与 `.tcl`）、LVS 参考网表（`*_ref.spice`）及参数化生成脚本 `build_bandgap_suite.py`。

## 1. 单元清单与物理指标

| 单元名称 | 对应网表子电路 | 版图尺寸 (µm) | 面积 (µm²) | 关键匹配与物理隔离策略 |
| :--- | :--- | :--- | :--- | :--- |
| `serdes_bandgap` | `serdes_bandgap` (`Cvgi=10p`) | 176.00 × 58.00 | 10,208.0 | 4×3 共质心 PNP 矩阵 + 20 指共质心双排 PMOS 镜像 + 18 条共质心高阻多晶硅 + 顶层屏蔽 MIM |
| `serdes_bias_ref` | `serdes_bias_ref` (`Cvgi=2p, Cvbg=5p`) | 176.00 × 58.00 | 10,208.0 | 集成 `Cvbg=5 pF`（M3 下极板接 `vss` 兼作法拉第静电屏蔽层）与 `Cvgi=2 pF` |
| `serdes_bg_amp` | `serdes_bg_amp` | 148.00 × 48.00 | 7,104.0 | 左区有源（`Xa/Xb`、`Xla/Xlb` 共质心）与右区无源（`Rz=20k` + `Cc=6p`）物理分离，零交叠耦合 |
| `serdes_bg_ota` | `serdes_bg_ota` | 66.00 × 44.00 | 2,904.0 | 单级微电流 OTA：8 指共质心输入对 `A-A-B-B-B-B-A-A` + 8 指共质心 LVT PMOS 负载 |
| `serdes_ref_vbuf` | `serdes_ref_vbuf` | 92.00 × 44.00 | 4,048.0 | RX 端接共模缓冲器：共质心单位增益跟随器 + 右侧 8 段蛇形串联 `Xr=105.2 kΩ` |
| `serdes_ref_pbuf` | `serdes_ref_pbuf` | 144.00 × 46.00 | 6,624.0 | 环路滤波器预充缓冲：`Xr0=95k` + 15 抽头分压链 + 16 路反相器/传输门 MUX + 300 µA 尾流 LVT 跟随器 |
| `serdes_bias_pcopy` | `serdes_bias_pcopy` (`n=4`) | 26.08 × 14.50 | 378.2 | 10 µA 基本单元（4 指 `W=6, L=4` LVT PMOS + 左右 Dummy 栅 + 独立 N-Well 保护环） |
| `serdes_bias_pcopy_n20` | `serdes_bias_pcopy` (`n=20`) | 35.20 × 25.00 | 880.0 | 50 µA CTLE / CP 偏置电流镜像宏单元（2 行 × 10 指） |
| `serdes_bias_pcopy_n85` | `serdes_bias_pcopy` (`n=85`) | 47.44 × 56.50 | 2,680.4 | 212.5 µA CML 尾流偏置镜像宏单元（5 行 × 17 指） |
| `serdes_bias_cml` | `serdes_bias_cml` | 32.00 × 28.00 | 896.0 | CML 本地尾流偏置二极管（`w=5, l=0.5`）+ 顶层堆叠 `Cdec=5 pF` MIM 旁路电容 |
| `serdes_bias_ctle` | `serdes_bias_ctle` | 12.00 × 9.50 | 114.0 | CTLE 本地 LVT 偏置二极管（`nfet_lvt w=8, l=0.5, nf=4`） |
| `serdes_bias_cp` | `serdes_bias_cp` | 16.50 × 22.00 | 363.0 | 电荷泵本地偏置镜像（`Xdn/Xmn` `DN-MN-MN-DN` 共质心）+ `Xdp` PMOS 二极管 |

## 2. 核心模拟版图优化决策

1. **4×3 共质心 PNP 矩阵与双环衬底隔离（Zone 1）**：
   - 将 `Xq1`（1×，发射极 `a`）置于底部 3×3 矩阵几何中心 `(1,1)`，8 个 `Xq2`（`m=8`，发射极 `c`）环绕四周并通过对称 M2 环网汇流，顶部居中放置 `Xq3`（1×，发射极 `d`）并在两侧配置接地的 Dummy PNP 单元，使 `Q1`、`Q2`、`Q3` 处于完全一致的刻蚀与热梯度包络中。
   - 每个 `sky130_fd_pr__pnp_05v5_W3p40L3p40` 单元严格采用 3.40×3.40 µm `pdiff`+`pnp` 发射极、同心 `nwell`+`nsubdiff` 基极环与外围 `psubdiff` 集电极环，外加独立 P+ 保护环隔离。
2. **20 指共质心 PMOS 镜像阵列（Zone 2 Top N-Well）**：
   - 核心 5 支路长沟道镜像 `Xm1..Xm5`（共栅 `vg`）按 `[M4,M4, M1,M1, M2,M2, M3,M3, M5,M5, M5,M5, M3,M3, M2,M2, M1,M1, M4,M4]` 共质心排列，消除一阶与二阶梯度失配。
   - V→I 转换与输出镜像阵列 `Xmv` + `Xo0..Xo3`（共栅 `vgi`）按 `[O0,O0, O1,O1, MV,MV, O2,O2, O3,O3, O3,O3, O2,O2, MV,MV, O1,O1, O0,O0]` 共质心排列，确保 `iout0..3` 与基准支路 `Xmv` 的严格比例复制。
3. **共质心高阻多晶硅阵列与极板屏蔽 MIM 堆叠（Zone 3）**：
   - 全部电阻采用无 `rpm.1` 违例的 `1.41 µm` 宽 `ppolyres` + `xpolycontact` 结构，两端配置 Dummy 电阻条；`Xrsa/Xrsb` 按 `A-B-B-A` 交指匹配，`Xr1` 置于 `Xr2` 串联阵列的几何中心。
   - 密勒电容 `Cc` 的高阻节点 `cz` 接 M4 上极板、低阻输出 `vg` 接 M3 下极板；`Cvgi` 下极板接 `vdd`、`Cvbg` 下极板接 `vss`，利用 M3 下极板形成天然交流静音屏蔽层，杜绝高阻运放节点的衬底寄生耦合。
