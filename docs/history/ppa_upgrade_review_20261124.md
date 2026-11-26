# 4 Gb/s PPA 与 5 Gb/s 升级复核

2026-11-24。4 Gb/s 的优先优化对象是时钟分发和 RX PI。对 5 Gb/s，保留 250 MHz 参考并采用 20-bit 字，可让参考、字接口和 CDR 控制保持原频率。若目标还包括亚皮秒抖动，现有数据中优先验证 LC 路线的电感、反馈分频和八相接口。[固定证据](../../results/catalog/ppa_upgrade_review_20261124.json)

## 4 Gb/s 模块与核心 PPA

从 TT 76 ns 同 deck 原始电流重积分 45–75 ns，得到 100.87 mW，折合 25.22 pJ/原始 bit。边界包括旧 CML 反馈 PLL、外部四路 r5、TX 正交 ÷2 和完整模拟 TX/RX。数字控制、实际封装与板级电源另计。RJ、杂散和边沿散布各自按项目判据验收。[原始联合台索引](../../results/catalog/chip_integration_20261124.json) · [测量约定](../verification/measurement_conventions.md)

| 部分 | 受查功耗／面积 | 优化动作及最小对照 |
|---|---|---|
| PLL 与时钟分发 | PLL 外部电源 35.76 mW，四路 r5 加 TX 正交 ÷2 共 24.29 mW。两者占同 deck 模拟输入的 59.5% | 固定 2 GHz、实际八相负载、供电来源和稳态窗口，将 r5、TX ÷2 及 PLL 反馈分别测功耗。先扫末级驱动和布线寄生，用低压慢角边沿、偏斜和接收裕量选点 |
| RX | 24.88 mW，PI 电源 13.45 mW，占 RX 的 54.1%。RX 宏外框 47,932 µm² | 先把 PI 混合器和恢复级调在实际 CPEX 负载上。比较混合 RC、恢复增益和输出缓冲，按 64 码单调性、恢复最小摆幅与 D/E 边沿验收 |
| TX 与信道 | 15.94 mW，SST 宏外框 35,013 µm² | 用相同波形扫 FFE/ZQ、分流和摆幅。先核焊盘 ≥75 mV、≤0.15 UI、阻抗，再看 C2 远端；同时回归 A1 弱负载和 C2 冷/热角 |
| 数字 | v3.2 宏外框 106,330 µm²，占功能外框约 35%。独立 STA 复现 18/18，SS 最小建立裕量 14.5 ps | 优先短化 CDR 步进确认和 RX 跨字对齐路径，再评估放置/扇出和面积。单个慢角的小量正裕量限制了当前可做的压缩 |
| LDO、Bias、被动与布局 | LDO 37,959 µm²，Bias v2 26,878 µm²；尾偏置滤波同值叠层省约 4,113 µm²，已用在新核心 | 保留尾偏置滤波的电气数值，优先做可抽取的同值叠层与摆位。按 VDD_Q、时钟、数字各域提取阻抗与纹波，再判定去耦和压降 |

`full_v3` 的 20 个功能宏外框合计 300,714 µm²，规划核心 0.5084 mm²，去耦预留占 0.1095 mm²。Magic 装配外框约 915 × 655.5 µm，含当前外围走线。核心 GDS 的全规则 DRC 为 0，独立重生成顶层 MAG 逐字节一致。摆位代理的 r5→RX 八相路径平均 317 µm，适合先提取互电容矩阵，比较换层、加间距和时钟接收器位置。顶层 RCX、供电与封装、芯片级 LVS 仍按集成队列验收。[版图复核](../layout/chip_floorplan_20261123.md) · [固定证据](../../results/catalog/ppa_upgrade_review_20261124.json)

### 交付收据的边界

A1 的 6 点局部筛查通过。A2 的 6 点复位及局部相位筛查通过，按半供电阈值逐个完整周期复算，SS 1.65 V −40 °C 的最小占空比为 **44.01%**，低于项目 45% 的 CMOS 边界。同角 D→E 约 101.7 ps，距 125 ps 目标约 23.3 ps。先定位哪条输出的恢复/负载造成畸变，同时比较稳态占空比与复位漏流。C2 的 SS 热点已有完整的 36.8 ns 波形，复算为 80/80、146.5 mV，但执行日志保留高阻模型指数溢出，严格局部结果为 3/4。GLS 四模式功能通过，严格汇总因 TT/SS 复位纪元的 3/1 条时序提示保持未通过。相同网表与独立复核的诊断均有固定身份。[收据索引](../../results/catalog/ppa_upgrade_review_20261124.json)

## 5 Gb/s 的两种字宽

线速 5 Gb/s 时 UI 为 200 ps。沿用四分之一速架构，半速 VCO 为 2.5 GHz，TX 和 RX 四分之一速本地时钟为 1.25 GHz。

250 MHz 参考的 ÷10 可从前级高速 ÷2 与后级 1.25 GHz 模五计数开始，反馈链由 PLL 自己管理。TX 使能、gearbox 空闲和 RX 重训均不能停掉反馈。先测前级在 SS 低压角的输入摆幅、建立裕量、复位相位和逐沿计数，再按 PFD 所需的高低脉宽选输出方式。

| 选择 | 参考与反馈 | TX/RX 字域 | CDR 域 | 最小改动与代价 |
|---|---|---|---|---|
| 16 bit，保留参考 | 250 MHz，÷10 | 312.5 MHz | 156.25 MHz | 保留字格式。加固 CDR、RX 对齐及 host 路径 |
| 16 bit，更快参考 | 312.5 MHz，÷8 | 312.5 MHz | 156.25 MHz | 可试保留反馈比。还需重核 PFD、分频器、启动监控域和参考源 |
| **20 bit，保留参考** | **250 MHz，÷10** | **250 MHz** | **125 MHz** | 每相 5 bit，1.25 GHz 字分频从 ÷4 改为 ÷5。重做 20→4 TX、RX 打包、字对齐及 FIFO 数据宽度。主机走 20-bit × 250 MHz |

用 03:00 GDS 对应原 DEF/SPEF、三角 Liberty、原 I/O 预算和时钟不确定性重跑 STA，只改时钟周期。在 SS，16-bit/250 MHz 参考方案的建立裕量为 CDR **−1.451 ns**、RX 字 **−0.786 ns**、host **−0.635 ns**、TX 字 **+0.173 ns**。312.5 MHz 参考另带来 `pll_clk_div4` **−0.067 ns**。这些值给 16-bit 提频方案定量定位。20-bit 方案要用加宽后的逻辑重新综合和 STA。[独立 STA 和重放入口](../../results/catalog/ppa_upgrade_review_20261124.json)

TX 与 RX 可独立选字宽。首轮 TX 草案保留局部 16:4 和原发射通道，用 20→16 字宽转换连接 250 MHz 主机。若 TX 局部也要求 250 MHz，再比较直接 20:4。RX 可优先评估直接 20-bit 打包，四相各 5 个时隙，`we[0]` 与上一字最后数据配对。两字 CDR tick 改为 40 UI，仍是 8 ns。若沿用 64 码跨 2 UI 及现行频率限幅，细步平均 6.25 ps，±300 ppm 需每 tick 0.384 步，理论限幅约 ±586 ppm。最小验证是 20-bit 位图和跨字边沿、TT/SS 的 ÷5 局部台，再以 5 Gb/s PI LUT 做 ±300 ppm RTL 回归。[TX 字接口草案](../design/tx_5g_word_interface.md) · [现行 RX 与 PI 接口](../design/rx_cmos_v2.md)

既有 400 mV SST 在理想 1.25 GHz 四相的四点中，C2 远端最小 85.8 mV、最大 0.1045 UI；C2 的合成 Touchstone 重算在 Nyquist 由 6.00 dB 升至 6.84 dB。保持现行 400 mV SST 作为首轮对照。现行 PI 在 SS 低压热角 2.5 GHz 停振，降低混合器 RC 后有输出、八相误差仍约 23 ps。独立的 5G 解串测试 4×64 bit 正确，输入是理想四分之一速时钟和 PWL 数据。最小物理台应先让带提取负载的 PI 在 SS 冷、热都恢复八相，再用实际 TX 四相、C2 波形及 RX 恢复时钟接起来。[分支及收据索引](../../results/catalog/ppa_upgrade_review_20261124.json)

## 低抖动 PLL 与 VCO

**4 Gb/s 优先改善 r6 核和冷角 CP。** 在已归档的 10 kHz–100 MHz 线性模型中，VCO 约占 TT 随机抖动方差的 79.5%。保持其他项不变，TT 达到 1 ps 需将 VCO 相噪贡献按功率约压低 10.6 dB。SS 冷、FS 热即使将 VCO 噪声置零，其他项仍是 1.32、1.13 ps RMS。先按真实 r5/SAFF 反馈和 v4.1 CP 的静态工作点重测 CP 噪声/脉宽及参考杂散；VCO 局部先比差分换向、摆幅和尾流。尾偏置滤波继续保持，针对高码 CPEX 的频差检查调谐跨三温共同码。原 r6 调谐面九个 FS/hh 条件的码 0 上边界只有 2.239–2.321 GHz，直接提频有硬缺口。[r6 噪声模型](../design/pll_vco_r6_perf.md) · [证据索引](../../results/catalog/ppa_upgrade_review_20261124.json)

**5 Gb/s 分支的模型须带物理面积一起比较。** 以已存五角 VCO/CP 噪声和线性 N=10 环路，约束所有角共用一组 Rz/Ci、PM ≥50°、UGB ≤25 MHz，积分 10 kHz–100 MHz。在 Ci≤60 pF 的网格，稳压 CMOS 环振 A+ 估算最差 **1.22 ps**，LC + ÷2 估算最差 **0.465 ps**。LC 若把 Ci 限至 20 pF，最差约 **0.574 ps**，附加 0.5 pF 控制节点等效电容时约 **0.599 ps**。A+ 只有放到 420 pF 的所扫网格才逼近 1 ps，且自身 TT 模型台约 22.94 mW。LC 约 210×210 µm 的电感几何已占现有规划核心约 8.7%，仍需留周边及滤波电容。原始 LC 台使用集总电感，候选最优结果为模型估算。[共用环路计算](../../verification/analysis/ppa_upgrade_review.py) · [各角结果](../../results/catalog/ppa_upgrade_review_20261124.json)

LC 的现有 ÷2 只给 2.5 GHz I/Q 四个单端相位。原 RX PI 使用每 50 ps 一个的八相锚点。先证实实际电感 Q/自谐振、FS 热角抗启动退化，构造其余四个锚点并按真实负载提取。随后在 250 MHz 参考的 ÷10 上验证固定码捕获及 320 ns 工程保持，再接 5G PI。双速 LC 若共享同一电感，4 GHz 核心模式需比 5 GHz 模式多 56.25% 的总谐振电容，再另留 PVT 与调谐范围。CMOS 环振可保留作无电感路线，优先比较细调增益和稳压器噪声。本轮新增 ngspice 运行数为 0。[下一版入口](../status/next_iteration.md)

## 重放

分支报告用 `git show 92269ec9:docs/design/vco_5g_shootout.md` 和 `git show 92269ec9:docs/design/serdes_5g_feasibility.md` 读取。面积、功耗、信道和噪声模型重算用下列命令。STA 的九份 Tcl、输入 DEF/SPEF/Liberty 哈希及日志见固定收据。

```bash
review=results/verification/ppa_upgrade_review/20261123T192049.841818Z
uv run python verification/analysis/ppa_upgrade_review.py \
  --assembly "$review/full_v3_receipt/summary.json" \
  --output "$review/recheck.json"
```
