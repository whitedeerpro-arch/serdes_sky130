# PLL 反馈 A 与精准分频 B

> **2026-11-26 物理签核状态**：本架构已在 5 Gb/s 双速演进路线落地为 **`div_ab_5g_v2_pdk`**（[pll_div_ab_5g_v2.spice](../../analog/pll/divider/spice/pll_div_ab_5g_v2.spice) · [build_div_ab_5g_v2_pdk.py](../../analog/pll/divider/layout/build_div_ab_5g_v2_pdk.py) · [summary.json](../../analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/summary.json)）：Magic `DRC = 0`、Netgen `LVS = MATCH`、`M5 = 0%`，**6/6 角（12/12 `÷8 / ÷10`）CPEX 全通**，**50/50 `SS −40 °C` 失配 MC 100% 达标**（`|diff_sk| ≤ 4.77 ps`），详见 [5G 签核台账](../../results/catalog/serdes_5g_signoff_20261126.json)；4 Gb/s 独立 ÷8 预分频宏为 [SAFF-TSPC `saff_reclock_2g`](pll_tspc_reclock_divider.md)（[saff_reclock_2g_pdk](../../analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md)）。

本设计将 PFD 反馈（A 链）与数据时钟分频（B 链）解耦：A 负责可编程整数反馈（`÷8 / ÷10`），B 负责同源、相位确定的 `÷2 / ÷4 / ÷8`。两链共享缓冲后的输入时钟，A 的反馈在 TX 空闲和 RX 重训时持续运行。[SAFF-TSPC 架构对照](pll_tspc_reclock_divider.md#2-四架构多角度对比原理图基准)

| 250 MHz 参考 | A 反馈 | B 的 ÷2 / ÷4 / ÷8 |
|---|---|---|
| VCO 2.0 GHz | ÷8 → 250 MHz | 1000 / 500 / 250 MHz |
| VCO 2.5 GHz | ÷10 → 250 MHz | 1250 / 625 / 312.5 MHz |

## A 的计数与输出

异步级联可用于前级预分频或内部计数。现有 C²MOS 纹波链每级除 2，固定抽头覆盖 ÷2、÷4、÷8。首轮可从高速 ÷2 后接小型可配置 ÷4/÷5 开始，覆盖总 ÷8 和 ÷10。固定 ÷2 后的可配整数形成 (N=2M)，若后续确需奇数 N，再评估双模预分频。旧 CMOS 可编程计数器的 M=1–16 档在 250 MHz 台上表征，可参考其配置和输出逻辑，1.25 GHz 的计数级等候选时序验证。[历史实现入口](../../analog/pll/divider/README.md)

在 PFD 引脚前给终端事件做寄存或用干净时钟重定时，按逐周期恰好一个有效上升沿验收。已有同夹具的 2 GHz、20 MHz 电源纹波试验中，SS 冷角注入 40 mVpp，C²MOS 纹波 ÷8 的输出边沿调制约 37.5 pspp，SAFF 重定时约 14.1 pspp。A 的边沿经 PFD 进入环路，须测确定性调制与附加抖动。[原试验方法](../../analog/pll/divider/tb/tspc_study/benchmark.py#L645)

前级 ÷2 后用单边沿实现 ÷5，普通方波会得到 2/3 个周期的高低电平，对应 40/60%。按现行 CMOS 时钟筛查的 45–55%，可用全速时钟定反馈脉宽，或对 ÷2 时钟做双沿整形，保留 PFD 的有效上升沿来自同一相位。比率写入用影子配置，在停传、PFD 复位且 CP 关闭时应用，计数重新起相后再重新捕获。可启用的 N 档受实际 VCO 调谐窗及参考频率约束。[PFD 接口](../../analog/pll/pfd/README.md) · [当前规格](../overview/spec.md)

## B 的相位与最小验证

B 保留 SAFF 或等效的同源重定时结构，按数据通路需要给 ÷2、÷4、÷8 指定起相、占空比与输出负载。2.5 GHz 时 B 的 ÷8 为 312.5 MHz，可对接 16-bit 数据字域。250 MHz、20-bit 数据字域可由四分之一速 1.25 GHz 另做 ÷5。

先用真实前级波形在 SS 低压冷、热角测 2.0 GHz/÷8 和 2.5 GHz/÷10，依次复核计数边沿、占空比、复位及切档、A 附加抖动与参考杂散、A 运行时 B 的相间偏斜。最后用采用的 PFD/CP 和实际负载复核闭环的 320 ns 工程保持。当前 2.8 GHz 的 SAFF 读数来自理想激励，2.5 GHz 的实际驱动及共用负载是后续复核项目。[重定时边界](pll_tspc_reclock_divider.md#2-四架构多角度对比原理图基准)
