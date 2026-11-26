// Generated data; edit config/design_catalog.json and module records.
window.DESIGN_CATALOG = {
  "schema": 1,
  "project": {
    "name": "Simple SerDes",
    "subtitle": "SKY130 · 1.8 V · 4/5 Gb/s",
    "description": "按模块浏览 4/5 Gb/s 双速 SerDes 结构、边界、源码与证据；采用状态与验证数字统一查看 docs/status/current.md。",
    "updated": "2026-11-26"
  },
  "nodes": [
    {
      "id": "serdes",
      "parent": null,
      "name": "SerDes",
      "subtitle": "4/5 Gb/s 双速 NRZ · Plan-C 5G + v1.0 4G",
      "state": "5G 签核 / 4G 基线",
      "summary": "收敛为双速 SKY130A SerDes：5G Plan-C（八边形 LC-VCO + A/B 分频 + SST v5 + CMOS RX 5G + 32-bit 数字 v4p1，0.6084 mm² DRC=0 层级签核）与 4G 环振 PLL v4 + v3.1/full_v8 参考基线并存。",
      "boundary": {
        "inputs": [
          "250 MHz 参考时钟、并行 TX 字（32-bit v4p1 / 16-bit v3）、100 Ω 远端差分串行数据",
          "独立 8 供电域（VDD_HV33 / VDD_Q / VDD_A / VDD_BIAS / VDD_TX / VDD_RX / VDD_D / VSS）"
        ],
        "outputs": [
          "100 Ω 差分 4/5 Gb/s NRZ TX 线、恢复时钟域数据与边沿字及宿主异步 FIFO 接口"
        ],
        "assumptions": [
          "5G Plan-C 全片完成 13 宏装配、131 紧缩去耦瓦片与层级 ext2spice 28/28 连通及 41/41 隔离门控。",
          "参考、复位、LDO 使能及 Padring/ESD/全片 LVS 随顶层集成收口；详见当前状态与片级物理审计。"
        ]
      },
      "planning": {
        "question": "在 SKY130A 1.8 V 工艺上兼顾 4 Gb/s 与 5 Gb/s NRZ 链路，实现紧凑面积、低功耗与可签核物理装配。",
        "model": "TX/RX 全面去 CML（SST + 四分之一速 CMOS），5G 升级八边形 LC-VCO、双速 A/B 分频与 32-bit 降频数字宏，配合紧凑混合去耦瓦片。",
        "parameters": "Plan-C 936 × 650 µm (0.6084 mm²)，13 宏密度 70.3%，131 瓦片 147.03 pF，RX 33-bit 零交叉。",
        "verification": "8/8 模拟单元 CPEX/RCX 签核 + 32-bit 数字 v4p1 6 角 OCV STA + Plan-C Magic DRC=0 与只读物理审计；4G v1.0 / full_v8 保留对照。"
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        },
        {
          "title": "4G / 5G 片级物理审计（2026-11-26）",
          "path": "results/catalog/chip_physical_audit_20261126.json"
        },
        {
          "title": "片级规划、5G Plan-C 与实装复核",
          "path": "docs/layout/chip_floorplan_20261123.md"
        },
        {
          "title": "主线工作修订（4/5 Gb/s）",
          "path": "config/mainline_working_revision.toml"
        },
        {
          "title": "5G 32-bit 数字宏 v4p1 摘要",
          "path": "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json"
        },
        {
          "title": "5G Plan-C 顶层构建脚本",
          "path": "verification/layout/build_chip_top_5g_pdk.py"
        },
        {
          "title": "统一数字顶层 v3.1（4G 基线）",
          "path": "docs/design/digital_top_v3.md"
        },
        {
          "title": "v1.0 4G 子系统证据索引",
          "path": "results/catalog/v1_0_subsystem_evidence.json"
        },
        {
          "title": "4G 片级集成证据",
          "path": "results/catalog/chip_integration_20261124.json"
        },
        {
          "title": "执行计划与退出条件",
          "path": "docs/status/prelayout_plan.md"
        },
        {
          "title": "架构与信号边界",
          "path": "docs/overview/architecture.md"
        },
        {
          "title": "规格",
          "path": "docs/overview/spec.md"
        },
        {
          "title": "项目工作流",
          "path": "docs/status/workflow.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G Plan-C 全片 PDK 顶层版图（serdes_5g_top_pdk）",
          "path": "docs/figures/layout/serdes_5g_top_pdk_20261126.png",
          "scope": "936 × 650 µm (0.6084 mm²)，13 宏密度 70.3%，131 紧缩去耦瓦片，Magic full DRC=0，层级 ext2spice 28/28 连通、41/41 隔离。",
          "report": "docs/layout/chip_floorplan_20261123.md"
        },
        {
          "title": "5G Plan-C v4p1 宏排布与零交叉互连总览",
          "path": "docs/figures/layout/serdes_5g_chip_top_v4p1_20261126.png",
          "scope": "端口协同 32-bit 数字宏 v4p1 与 R90 LC-VCO / R270_MX TX / 东侧 RX 摆位，RX 33-bit 0 交叉。",
          "report": "docs/layout/chip_floorplan_20261123.md"
        },
        {
          "title": "4G 参考基线全片装配（serdes_4g_top_pdk full_v8）",
          "path": "docs/figures/layout/serdes_4g_top_pdk_v8_20261124.png",
          "scope": "4 Gb/s 环振 PLL v4 参考装配，Magic full DRC=0，保留作为 4G 基线对照。",
          "report": "docs/layout/chip_floorplan_20261123.md"
        },
        {
          "title": "5G 顶层模拟链路联合仿真（5 Gb/s）",
          "path": "docs/figures/system/serdes_5g_top_cosim_20261124.png",
          "scope": "5 Gb/s LC-VCO + TX SST + C2 信道 + CMOS RX 端到端短窗联合仿真波形与眼图。",
          "report": "docs/status/current.md"
        },
        {
          "title": "4G 顶层模拟链路联合仿真（4 Gb/s）",
          "path": "docs/figures/system/serdes_4g_top_cosim_20261123.png",
          "scope": "4 Gb/s 同源 PLL→TX→C2_loss6→RX 短窗模拟联调波形对照。",
          "report": "docs/status/current.md"
        }
      ],
      "sources": [
        {
          "title": "5G 双速 32-bit 数字顶层 · serdes_digital_top_v4",
          "path": "digital/pnr/rtl_v4_32b/serdes_digital_top_v4.sv#serdes_digital_top_v4"
        },
        {
          "title": "5G 数字 RTL v4 编译清单",
          "path": "digital/pnr/rtl_v4_32b/rtl_v4.f"
        },
        {
          "title": "4G 统一数字顶层 · serdes_digital_top_v3",
          "path": "digital/pnr/rtl_v3/serdes_digital_top_v3.sv#serdes_digital_top_v3"
        },
        {
          "title": "4G 数字 RTL v3 编译清单",
          "path": "digital/pnr/rtl_v3/rtl_v3.f"
        }
      ]
    },
    {
      "id": "pll",
      "parent": "serdes",
      "name": "PLL",
      "subtitle": "5G 八边形 LC-VCO + A/B 分频 · 4G 环振 PLL v4",
      "state": "5G 宏签核 / 4G 基线",
      "summary": "5G 演进采用 5 GHz 八边形 LC-VCO + 正交 ÷2（2.5 GHz I/Q）及双速 ÷8/÷10 A/B 分频器，复用已签核的 PFD / CP v4 / 融合 LF v2；4G 参考保留 2 GHz 四级环振 r6 + PTAT 与 SAFF-TSPC ÷8。",
      "boundary": {
        "inputs": [
          "250 MHz 参考时钟、HV18 Kelvin 安静轨、BIAS v2 电流参考、粗码与预充控制"
        ],
        "outputs": [
          "5G：2.5 GHz 四相 I/Q 时钟与 250 MHz 反馈（÷8/÷10 双速）",
          "4G：2.0 GHz 八相时钟与 250 MHz 反馈"
        ],
        "assumptions": [
          "5G LC-VCO 与 A/B 分频器完成独立真 CPEX PVT 与失配 MC 签核；4G 闭环锁定台与反馈链边界见当前状态。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        },
        {
          "title": "VCO r6 相噪与 PLL v4 抖动特性",
          "path": "docs/design/pll_vco_r6_perf.md"
        },
        {
          "title": "PLL v4 闭环验证台",
          "path": "analog/pll/top/tb/lock_v4/verify_pll_v4_closed_loop.py"
        },
        {
          "title": "主线工作修订",
          "path": "config/mainline_working_revision.toml"
        },
        {
          "title": "v1.0 4G 子系统证据索引",
          "path": "results/catalog/v1_0_subsystem_evidence.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "PLL v4 固定粗码预充后闭环锁定（4G 参考）",
          "path": "docs/figures/clocking/pll_v4_closed_loop_20261123.png",
          "scope": "7/7 角原理图闭环与 CP v4，通过 320 ns 锁定合同；供电与反馈边界见当前状态。",
          "report": "docs/status/current.md"
        }
      ],
      "sources": [
        {
          "title": "5G 八边形 LC-VCO + 正交 ÷2 顶层",
          "path": "analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice#vco5g_lc_div2_oct_pdk"
        },
        {
          "title": "5G 双速 ÷8/÷10 A/B 分频器",
          "path": "analog/pll/divider/spice/pll_div_ab_5g_v2.spice#pll_div_ab_5g_v2"
        },
        {
          "title": "4G PLL v4 原理图闭环顶层",
          "path": "analog/pll/top/spice/pll_top_r6_v4_upgrade.spice#pll_top_r6_v4_upgrade"
        },
        {
          "title": "4G PLL v4.2 SAFF 反馈候选",
          "path": "analog/pll/top/spice/pll_top_r6_v4p2_saff.spice#pll_clock_frontend_r6_saff"
        },
        {
          "title": "PLL 控制顶层 · pll_control_top (v4)",
          "path": "digital/pnr/rtl_v4_32b/pll_control_top.sv#pll_control_top"
        }
      ]
    },
    {
      "id": "bias",
      "parent": "serdes",
      "name": "Bias & LDO",
      "subtitle": "BIAS v2 带隙与分配 · HV18 Kelvin 安静供电",
      "state": "5G/4G 共享签核",
      "summary": "折叠共栅带隙 BIAS v2 统一生成全局 Vbg/Vcm/预充参考与电流拷贝，HV18 LDO Kelvin 强化版与叠层尾偏置滤波为 PLL 提供低噪安静供电轨。",
      "boundary": {
        "inputs": [
          "3.3 V HV 供电、1.8 V 主模拟供电、带隙与 LDO 修调码"
        ],
        "outputs": [
          "1.8 V 安静域 VDD_Q、滤波尾偏置、Vbg / Vcm / 预充参考及各模块电流拷贝"
        ],
        "assumptions": [
          "4G 与 5G 共享 BIAS v2 与 HV18 LDO；5G Plan-C 采用 Kelvin 采样强化版 v2_cur_kelvin_pdk。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "BIAS v2 设计与后仿",
          "path": "docs/design/bias_v2.md"
        },
        {
          "title": "HV18 LDO v2 / v2_cur 设计",
          "path": "docs/design/ldo_v2.md"
        },
        {
          "title": "HV18 Kelvin 版图摘要",
          "path": "analog/ldo/layout/variants/v2_cur_kelvin_pdk/summary.json"
        },
        {
          "title": "BIAS v2 物理入口",
          "path": "analog/bias/layout/variants/v2_pdk/README.md"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "BIAS v2 统一顶层集成宏版图",
          "path": "analog/bias/layout/variants/v2_pdk/serdes_bias_top_v2_pdk.png",
          "scope": "176.53 × 152.26 µm，全 7 单元 DRC=0 / LVS=MATCH，20 个外边界端口。",
          "report": "docs/design/bias_v2.md"
        },
        {
          "title": "供电 PDN 与 LDO 环路稳定性复核",
          "path": "docs/figures/verification/stability_pdn_20261123.png",
          "scope": "LDO 稳定性裕量与分域阻尼 PDN 阻抗响应对照。",
          "report": "docs/design/ldo_v2.md"
        }
      ],
      "sources": [
        {
          "title": "BIAS v2 顶层与子电路",
          "path": "analog/bias/spice/bias_v2.spice#serdes_bias_top_v2"
        },
        {
          "title": "HV18 v2_cur 电流参考 LDO 顶层",
          "path": "analog/ldo/spice/pll_supply_hv18_v2_cur.spice#serdes_pll_supply_hv18_v2_cur"
        }
      ]
    },
    {
      "id": "tx",
      "parent": "serdes",
      "name": "TX",
      "subtitle": "4/5 Gb/s 16:4 CMOS 串化 → 四相 N-over-N SST",
      "state": "5G v5 / 4G v4.3 签核",
      "summary": "纯静态 CMOS 16:4 串化加四相交错 N-over-N 28-slice SST 线驱动（内置 2-tap FFE 与 ZQ 校准），由片上低压 V_drv 子稳压器供电。v5_pdk 真 CPEX 通过 16/16（5G+4G）签核。",
      "boundary": {
        "inputs": [
          "16 位并行 CMOS 字、四相 1.25 GHz (5G) / 1.0 GHz (4G) 时钟、Vbg 与 ZQ/FFE 控制"
        ],
        "outputs": [
          "4/5 Gb/s NRZ 100 Ω 差分焊盘输出、字时钟"
        ],
        "assumptions": [
          "5G v5_pdk 宏 256.8 × 169.58 µm、38 端口、DRC=0 / LVS=MATCH，真 CPEX 覆盖 12 路 5G + 4 路 4G 工况。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "TX SST 设计与后仿",
          "path": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "TX SST v5_pdk 5G 物理摘要",
          "path": "analog/tx/sst/layout/variants/v5_pdk/summary.json"
        },
        {
          "title": "TX SST v4_pdk 4G 物理入口",
          "path": "analog/tx/sst/layout/variants/v4_pdk/README.md"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G TX SST v5 顶层 PDK 版图",
          "path": "analog/tx/sst/layout/variants/v5_pdk/serdes_tx_sst_top_pdk.png",
          "scope": "256.8 × 169.58 µm，38 端口，DRC=0 / LVS=MATCH，真 CPEX 16/16（12 路 5G + 4 路 4G）PASS。",
          "report": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "TX SST 堆叠切片与 FFE 结构示意",
          "path": "docs/figures/schematics/tx_sst_stacked_slices.png",
          "scope": "四相交错预驱、N-over-N 低压切片阵列与 2-tap FFE 原理结构。",
          "report": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "4G TX SST v4 原理图眼图与 45 角对照",
          "path": "docs/figures/tx/tx_sst_v4_eyes.png",
          "scope": "理想四相 1 GHz 源，含焊盘与 C2_loss6 远端 FFE 对照。",
          "report": "docs/design/tx_sst_v4.md"
        }
      ],
      "sources": [
        {
          "title": "5G SST TX 顶层 · serdes_tx_sst_top_5g",
          "path": "analog/tx/sst/spice/tx_sst_top_5g.spice#serdes_tx_sst_top_5g"
        },
        {
          "title": "4G SST TX 顶层 · serdes_tx_sst_top",
          "path": "analog/tx/sst/spice/tx_sst_top.spice#serdes_tx_sst_top"
        },
        {
          "title": "5G TX 入口控制 · tx_ingress_control_32",
          "path": "digital/pnr/rtl_v4_32b/tx_ingress_control_32.sv#tx_ingress_control_32"
        }
      ]
    },
    {
      "id": "rx",
      "parent": "serdes",
      "name": "RX",
      "subtitle": "4/5 Gb/s CTLE → 纯 CMOS PI → 四分之一速采样 → 解串",
      "state": "5G 宏签核 / 4G v2.2 基线",
      "summary": "5G 升级紧凑并联电感峰化 CTLE（W3）、4→8 相 2.5 GHz CMOS PI v3 与高速 Double-Tail 采样器（8× 切片 + 8→32 解串），集成顶层 rx_top_5g_pdk 全项 DRC=0 / LVS=MATCH；4G v2.2 保留 45/45 基线。",
      "boundary": {
        "inputs": [
          "100 Ω 差分串行输入、四相 2.5 GHz (5G) 或八相 2 GHz (4G) 锚点、EQ / PI / 失调修调控制"
        ],
        "outputs": [
          "恢复字时钟域 16 位数据 + 16 位边沿字（经数字 v4p1 打包至 32-bit 降频域或 v3 16-bit 域）"
        ],
        "assumptions": [
          "rx_top_5g_pdk 完成 DC & Open 双视图 LVS=MATCH 与 8/8 子单元真 CPEX/MC 签核；4G v2.2 边界见当前状态。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "RX CMOS 设计、4G 签核与 5G CTLE 演进",
          "path": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "5G RX 顶层 rx_top_5g_pdk 物理摘要",
          "path": "analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/summary.json"
        },
        {
          "title": "4G RX v2_pdk 物理入口",
          "path": "analog/rx/cmos_rx/layout/variants/v2_pdk/README.md"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G RX CMOS 集成顶层版图（rx_top_5g_pdk）",
          "path": "analog/rx/cmos_rx/layout/variants/rx_top_5g_pdk/serdes_rx_cmos_top_5g_pdk.png",
          "scope": "312.1 × 199.4 µm，DRC=0 / FP=0 / DC & Open LVS=MATCH（72/74 端口），集成 W3 CTLE + PI v3 + 8× slicer_5g + deser16。",
          "report": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "4G RX v2.2 原理图链路与单元签核汇总",
          "path": "docs/figures/rx/rx_cmos_v2_signoff.png",
          "scope": "45/45 原理图回放与 3/3 CPEX 压力点签核，含 C2_loss6 链路、采样窗口与 PI 线性度。",
          "report": "docs/design/rx_cmos_v2.md"
        }
      ],
      "sources": [
        {
          "title": "5G CMOS RX 顶层 · serdes_rx_cmos_top_5g_pdk",
          "path": "analog/rx/cmos_rx/spice/rx_cmos_top_5g_pdk.spice#serdes_rx_cmos_top_5g_pdk"
        },
        {
          "title": "4G CMOS RX 顶层 · serdes_rx_cmos_top",
          "path": "analog/rx/cmos_rx/spice/rx_cmos_top.spice#serdes_rx_cmos_top"
        },
        {
          "title": "5G CDR 顶层 · rx_cdr_loop_v4",
          "path": "digital/pnr/rtl_v4_32b/rx_cdr_loop_v4.sv#rx_cdr_loop_v4"
        },
        {
          "title": "5G RX 32-bit 字对齐与宿主接口 · rx_word_host_32",
          "path": "digital/pnr/rtl_v4_32b/rx_word_host_32.sv#rx_word_host_32"
        }
      ]
    },
    {
      "id": "channel",
      "parent": "serdes",
      "name": "Channel",
      "subtitle": "C0–C5 4/5 Gb/s 共享合成差分 PCB 族",
      "state": "主线",
      "summary": "100 Ω 差分合成 PCB 信道族覆盖 4 Gb/s（2.0 GHz Nyquist）与 5 Gb/s（2.5 GHz Nyquist）设计回归；C2_loss6 为主设计信道，C3_loss10 为挑战信道，RLC16 用于近无损对照。",
      "boundary": {
        "inputs": [
          "TX 差分源与独立装夹模型"
        ],
        "outputs": [
          "RX 100 Ω 端接处的差分信号"
        ],
        "assumptions": [
          "合成 PCB 模型的频响校准、无源性与装夹边界见信道设计文档。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "信道模型与校验",
          "path": "docs/design/channel_model.md"
        },
        {
          "title": "信道族配置（4/5 Gb/s 共享）",
          "path": "config/channel_family.toml"
        },
        {
          "title": "v1.0 子系统证据索引",
          "path": "results/catalog/v1_0_subsystem_evidence.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "PCB 信道族远端脉冲响应",
          "path": "docs/figures/channel/characterization/pcb_channel_family_pulses_ui.png",
          "scope": "C0–C5 合成差分 PCB 信道在 UI 尺度下的远端脉冲响应与拖尾对照。",
          "report": "docs/design/channel_model.md"
        },
        {
          "title": "PCB 信道族插损与频域响应",
          "path": "docs/figures/channel/characterization/pcb_channel_family_frequency.png",
          "scope": "C0–C5 差模插损（SDD21）与回损特性，覆盖 2.0 GHz（4G）及 2.5 GHz（5G）Nyquist 频点。",
          "report": "docs/design/channel_model.md"
        }
      ],
      "sources": [
        {
          "title": "C2_loss6 PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C2_loss6.spice#pcb_c2_loss6"
        },
        {
          "title": "RLC16 近无损负载",
          "path": "verification/models/channel/diff_rlc16.spice#serdes_diff_rlc16"
        }
      ]
    },
    {
      "id": "pll.lc_vco_5g",
      "parent": "pll",
      "name": "5G 八边形 LC-VCO 与 ÷2",
      "subtitle": "5 GHz 谐振槽 → 2.5 GHz 正交 I/Q",
      "state": "5G 签核",
      "summary": "采用 2.5 nH 八边形对称电感与 4-bit 电容阵构建 5 GHz LC-VCO，配合正交 CML ÷2 输出 2.5 GHz 四相 I/Q；全角公共交集 4.469–5.350 GHz，通过 125 °C 冻码与 24/24 失配 MC。",
      "boundary": {
        "inputs": [
          "Vctrl、4-bit 粗码、HV18 Kelvin 安静轨、BIAS v2 偏置"
        ],
        "outputs": [
          "2.5 GHz 四相差分 I/Q 时钟（送 A/B 分频器与时钟宿主）"
        ],
        "assumptions": [
          "真 CPEX 6/6 角 + 125 °C 冻码 3/3 PASS，24/24 SS +85 °C MC 锁定（I/Q σ=0.645 ps）。"
        ]
      },
      "planning": {
        "question": "在 SKY130A 金属栈下实现 5 GHz 低相噪、宽公共调谐交集与紧致电磁串扰抑制。",
        "model": "对比方形 / 八边形 / 8 字形线圈电感与 Q 值，按提取寄生校验 4-bit 阵列与全角覆盖交集。",
        "parameters": "2.5 nH 八边形电感 + 4-bit 开关电容阵 + 正交 CML ÷2，DRC=0 / LVS=MATCH。",
        "verification": "6/6 CPEX PVT、125 °C 冻码 3/3、24× SS +85 °C 失配 MC 及 Plan-C R90 摆位集成。"
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G LC-VCO 物理摘要",
          "path": "analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/summary.json"
        },
        {
          "title": "5G LC-VCO CPEX 验证脚本",
          "path": "analog/pll/vco_5g/tb/verify_lc_vco_oct_cpex.py"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        },
        {
          "title": "片级规划与 5G Plan-C",
          "path": "docs/layout/chip_floorplan_20261123.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G LC-VCO 方形 / 八边形 / 8 字形电感方案对照",
          "path": "docs/figures/layout/vco5g_inductor_sq_oct_fig8_20261124.png",
          "scope": "SKY130A 顶层金属电感几何、Q 值与磁耦合权衡，最终选型八边形 2.5 nH。",
          "report": "docs/layout/chip_floorplan_20261123.md"
        },
        {
          "title": "5G 八边形 LC-VCO + 正交 ÷2 PDK 版图",
          "path": "analog/pll/vco_5g/layout/variants/lc_vco_5g_oct_pdk/vco5g_lc_div2_oct_pdk.png",
          "scope": "lc_vco_5g_oct_pdk 生产宏，DRC=0 / LVS=MATCH，Plan-C 中以 R90 摆位缩短时钟走线。",
          "report": "docs/layout/chip_floorplan_20261123.md"
        }
      ],
      "sources": [
        {
          "title": "5G 八边形 LC-VCO + 正交 ÷2 顶层",
          "path": "analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice#vco5g_lc_div2_oct_pdk"
        },
        {
          "title": "5G LC-VCO 核心 · vco5g_lc_core_oct_pdk",
          "path": "analog/pll/vco_5g/spice/lc_5g_div2_oct_pdk.spice#vco5g_lc_core_oct_pdk"
        }
      ]
    },
    {
      "id": "pll.div_ab_5g",
      "parent": "pll",
      "name": "5G 双速 A/B 分频器",
      "subtitle": "2.5/2.0 GHz → 250 MHz（÷10 / ÷8）",
      "state": "5G 签核",
      "summary": "纯 CMOS 差分/SAFF 双模 A/B 反馈分频器（v2），支持 5G 模式 ÷10（2.5 GHz→250 MHz）与 4G 模式 ÷8（2.0 GHz→250 MHz），零 M5 占用且冷角失配 50/50 达标。",
      "boundary": {
        "inputs": [
          "2.5 / 2.0 GHz 差分 CMOS 时钟、双速分频选择与复位"
        ],
        "outputs": [
          "250 MHz PFD 反馈时钟"
        ],
        "assumptions": [
          "真 CPEX 6/6 角（12/12 ÷8 & ÷10）PASS；SS -40 °C 50/50 MC 100% 通过（|diff_sk| ≤ 4.77 ps）。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G A/B 分频器物理摘要",
          "path": "analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/summary.json"
        },
        {
          "title": "5G 双速签核台账（2026-11-26）",
          "path": "results/catalog/serdes_5g_signoff_20261126.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G 双速 A/B 分频器 v2 PDK 版图",
          "path": "analog/pll/divider/layout/variants/div_ab_5g_v2_pdk/pll_div_ab_5g_v2_pdk.png",
          "scope": "DRC=0 / LVS=MATCH / M5=0%，6/6 角 ÷8/÷10 CPEX 及 50/50 SS 冷角 MC 签核。",
          "report": "docs/status/current.md"
        }
      ],
      "sources": [
        {
          "title": "5G 双速 A/B 分频器 · pll_div_ab_5g_v2",
          "path": "analog/pll/divider/spice/pll_div_ab_5g_v2.spice#pll_div_ab_5g_v2"
        }
      ]
    },
    {
      "id": "pll.pfd_cp_lf",
      "parent": "pll",
      "name": "PFD、CP v4 与融合 LF",
      "subtitle": "延迟复位鉴相、主动伺服 CP 与紧凑 k=4 融合 LF",
      "state": "5G/4G 共享签核",
      "summary": "标准单元延迟复位 PFD 驱动主动伺服匹配电荷泵 CP v4，配合 MIM 下方复用器件的紧凑融合环路滤波器 k=4 与双节点预充。",
      "boundary": {
        "inputs": [
          "250 MHz 参考与反馈时钟、预充控制与参考电压、BIAS v2 电流拷贝"
        ],
        "outputs": [
          "Vctrl 调谐电压（接 LC-VCO 或环振 r6）"
        ],
        "assumptions": [
          "三个物理宏均通过 DRC=0 / LVS=MATCH，在 4G full_v8 与 5G Plan-C 中共用。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "电荷泵 v4 设计",
          "path": "docs/design/pll_cp_v4.md"
        },
        {
          "title": "环路设计",
          "path": "docs/design/pll_loop.md"
        },
        {
          "title": "CP v4 物理入口",
          "path": "analog/pll/cp/layout/variants/v4_pdk/README.md"
        },
        {
          "title": "融合 LF v2 物理入口",
          "path": "analog/pll/loop_filter/layout/variants/fused_pdk/README.md"
        },
        {
          "title": "PFD 物理入口",
          "path": "analog/pll/pfd/layout/variants/pdk/README.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "转向电荷泵 v4 共质心 PDK 版图",
          "path": "analog/pll/cp/layout/variants/v4_pdk/pll_cp_steer_v4_pdk.png",
          "scope": "200 µA 主动伺服匹配电荷泵，DRC=0 / LVS=MATCH，CPEX & RCX 已验证。",
          "report": "analog/pll/cp/layout/variants/v4_pdk/README.md"
        },
        {
          "title": "融合环路滤波器 v2 MIM 下方器件布局",
          "path": "analog/pll/loop_filter/layout/variants/fused_pdk/pll_lf_fused_under_mim.png",
          "scope": "6,382 µm² 紧凑堆叠版图，在 MIM 下方集成 Rz 与双节点预充开关，ctrl CPEX -41.4%。",
          "report": "analog/pll/loop_filter/layout/variants/fused_pdk/README.md"
        },
        {
          "title": "延迟复位标准单元 PFD PDK 版图",
          "path": "analog/pll/pfd/layout/variants/pdk/pll_pfd_sc_dly_pdk.png",
          "scope": "pll_pfd_sc_dly 物理宏，DRC=0 / LVS=MATCH。",
          "report": "analog/pll/pfd/layout/variants/pdk/README.md"
        }
      ],
      "sources": [
        {
          "title": "延迟复位标准单元 PFD · pll_pfd_sc_dly",
          "path": "analog/pll/pfd/spice/pfd_sc.spice#pll_pfd_sc_dly"
        },
        {
          "title": "主动伺服电荷泵 · pll_cp_steer_v4",
          "path": "analog/pll/cp/spice/charge_pump_steer_v4.spice#pll_cp_steer_v4"
        },
        {
          "title": "k=4 融合环路滤波器 · pll_loop_filter_k4_fused",
          "path": "analog/pll/loop_filter/spice/passive_rc_pdk_k4.spice#pll_loop_filter_k4_fused"
        }
      ]
    },
    {
      "id": "pll.r6_ptat",
      "parent": "pll",
      "name": "4G VCO r6 与 PTAT",
      "subtitle": "5-bit 调谐、28/66 尾流温补与八相输出",
      "state": "4G 基线",
      "summary": "四级环振 r6 配合定宽多晶电阻、5-bit MIM 电容阵与 BIAS v2 PTAT (28/66) 尾偏置，45/45 跨三温单码覆盖，sym9_clean CPEX 八相误差 ≤ 0.76 ps。",
      "boundary": {
        "inputs": [
          "Vctrl、5-bit 粗码、HV18 安静轨、PTAT 尾偏置"
        ],
        "outputs": [
          "2 GHz 四对差分八相时钟"
        ],
        "assumptions": [
          "用于 4G v1.0 / full_v8 基线；相噪由 ISF 合成，CPEX 五角验证见 VCO 性能报告。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "VCO r6 相噪与 PLL v4 性能报告",
          "path": "docs/design/pll_vco_r6_perf.md"
        },
        {
          "title": "PTAT 28/66 设计与码窗",
          "path": "docs/design/pll_vco_r6_ptat.md"
        },
        {
          "title": "sym9_clean 版图入口",
          "path": "analog/pll/vco/layout/variants/sym9_clean/README.md"
        },
        {
          "title": "VCO sym9 版图经验总结",
          "path": "docs/layout/vco_sym9_layout_lessons.md"
        },
        {
          "title": "PTAT 偏置物理入口",
          "path": "analog/pll/vco/layout/variants/ptat_bias_pdk/README.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "VCO r6 + PTAT 28/66 性能与 PLL v4 抖动分解",
          "path": "docs/figures/clocking/vco_r6_ptat_perf_20261123.png",
          "scope": "原理图 vs sym9_clean CPEX、ISF 器件相噪分解与 PLL/CDR 抖动预算。",
          "report": "docs/design/pll_vco_r6_perf.md"
        },
        {
          "title": "VCO r6 sym9_clean 对称版图",
          "path": "analog/pll/vco/layout/variants/sym9_clean/pll_vco_core_sym9_s32p5_clean.png",
          "scope": "2×2 对称环布局与 9 块融合 MIM 阵，CPEX 八相误差 ≤ 0.76 ps。",
          "report": "analog/pll/vco/layout/variants/sym9_clean/README.md"
        }
      ],
      "sources": [
        {
          "title": "r6 环振核心 · pll_vco_ring4_r6",
          "path": "analog/pll/vco/spice/vco_ring4_r6.spice#pll_vco_ring4_r6"
        },
        {
          "title": "r6 延迟单元 · pll_vco_delay_r6",
          "path": "analog/pll/vco/spice/vco_delay_r6.spice#pll_vco_delay_r6"
        },
        {
          "title": "五位电容阵 · pll_vco_cap_bank5",
          "path": "analog/pll/vco/spice/cap_bank_5b.spice#pll_vco_cap_bank5"
        },
        {
          "title": "恒流与 PTAT 尾偏置 · serdes_bias_cml_blend_v2",
          "path": "analog/pll/vco/spice/vco_ptat_bias.spice#serdes_bias_cml_blend_v2"
        }
      ]
    },
    {
      "id": "pll.saff_feedback",
      "parent": "pll",
      "name": "r5 接收器与 SAFF-TSPC ÷8",
      "subtitle": "CML→CMOS 转换与 4G 片级反馈分频",
      "state": "5G 复用 r5 / 4G 基线",
      "summary": "r5 CML→CMOS 全速时钟接收器在 5G 时钟宿主与 4G 反馈链中共用；SAFF-TSPC 重定时 ÷8（含加固候选）服务 4G 片级反馈路径。",
      "boundary": {
        "inputs": [
          "2.0–2.5 GHz 差分 CML 时钟与 CMOS 供电"
        ],
        "outputs": [
          "全速恢复 CMOS 时钟与 250 MHz 反馈"
        ],
        "assumptions": [
          "r5 v6 CPEX 45/45、原生 RCX 6 压力点与 200/200 MC 通过；SAFF-TSPC ÷8 边界见设计报告。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "SAFF-TSPC ÷8 设计与边界",
          "path": "docs/design/pll_tspc_reclock_divider.md"
        },
        {
          "title": "CML→CMOS 接收器设计",
          "path": "docs/design/clock_receiver.md"
        },
        {
          "title": "r5 物理入口",
          "path": "analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md"
        },
        {
          "title": "SAFF-TSPC ÷8 物理入口",
          "path": "analog/pll/divider/layout/variants/saff_reclock_2g_pdk/README.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "SAFF-TSPC v2 双端 RCX 波形",
          "path": "docs/figures/clocking/dividers/saff_reclock_v2_waveforms.png",
          "scope": "提取 r5 v6 驱动提取 SAFF-TSPC ÷8，含 TT、FS 低压热角与 SS 低压冷角。",
          "report": "docs/design/pll_tspc_reclock_divider.md"
        },
        {
          "title": "r5 v6 全速 CML→CMOS 转换版图",
          "path": "analog/common/cml_to_cmos/layout/variants/r5_pdk/serdes_cml_to_cmos_r5_pdk.png",
          "scope": "DRC=0 / LVS=MATCH，4G 与 5G 时钟宿主共用接收器。",
          "report": "analog/common/cml_to_cmos/layout/variants/r5_pdk/README.md"
        },
        {
          "title": "SAFF-TSPC ÷8 交错 PDK 版图",
          "path": "analog/pll/divider/layout/variants/saff_reclock_2g_pdk/pll_saff_reclock_prescaler8_2g_pdk.png",
          "scope": "1,705 µm²，DRC=0 / LVS=MATCH，45 角 CPEX 功能通过。",
          "report": "docs/design/pll_tspc_reclock_divider.md"
        }
      ],
      "sources": [
        {
          "title": "r5 CML→CMOS 接收器 · serdes_cml_to_cmos_r5",
          "path": "analog/common/cml_to_cmos/spice/cml_to_cmos_r5.spice#serdes_cml_to_cmos_r5"
        },
        {
          "title": "SAFF-TSPC ÷8 · pll_saff_reclock_prescaler8_2g",
          "path": "analog/pll/divider/spice/tspc_reclock_prescaler8_2g.spice#pll_saff_reclock_prescaler8_2g"
        },
        {
          "title": "加固 SAFF-TSPC ÷8 候选",
          "path": "analog/pll/divider/spice/tspc_reclock_prescaler8_2g_v2_cand.spice#pll_saff_reclock_prescaler8_2g"
        }
      ]
    },
    {
      "id": "pll.digital_control",
      "parent": "pll",
      "name": "数字粗搜与启动 RTL",
      "subtitle": "粗调搜索、锁定检测与启动监督（v4 / v3）",
      "state": "5G/4G 签核",
      "summary": "多速率数字宏负责 PLL 预充时序、粗码搜索、锁定质量判定与状态同步，全部模拟控制端口经寄存器直出防毛刺。",
      "boundary": {
        "inputs": [
          "250 MHz 参考时钟、窗口/锁定监测输入、宿主配置"
        ],
        "outputs": [
          "粗码、precharge_en / pfd_rst_b / cp_en / locked 控制端口"
        ],
        "assumptions": [
          "v4p1 32-bit 宏与 v3.1 16-bit 宏复用相同的无毛刺监督架构。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "统一数字顶层 v3.1",
          "path": "docs/design/digital_top_v3.md"
        },
        {
          "title": "5G 数字宏 v4p1 摘要",
          "path": "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json"
        }
      ],
      "iterations": [],
      "sources": [
        {
          "title": "v4 PLL 控制顶层 · pll_control_top",
          "path": "digital/pnr/rtl_v4_32b/pll_control_top.sv#pll_control_top"
        },
        {
          "title": "v4 预充与启动监督 · pll_startup_supervisor",
          "path": "digital/pnr/rtl_v4_32b/pll_startup_supervisor.sv#pll_startup_supervisor"
        },
        {
          "title": "v4 粗码搜索 · pll_coarse_ctrl",
          "path": "digital/pnr/rtl_v4_32b/pll_coarse_ctrl.sv#pll_coarse_ctrl"
        },
        {
          "title": "v4 锁定检测 · pll_lock_detect",
          "path": "digital/pnr/rtl_v4_32b/pll_lock_detect.sv#pll_lock_detect"
        },
        {
          "title": "v4 状态同步 · mon_sync",
          "path": "digital/pnr/rtl_v4_32b/mon_sync.sv#mon_sync"
        },
        {
          "title": "v4 状态保持检测 · mon_persist",
          "path": "digital/pnr/rtl_v4_32b/mon_persist.sv#mon_persist"
        },
        {
          "title": "v3 PLL 控制顶层 · pll_control_top",
          "path": "digital/pnr/rtl_v3/pll_control_top.sv#pll_control_top"
        },
        {
          "title": "v3 预充与启动监督 · pll_startup_supervisor",
          "path": "digital/pnr/rtl_v3/pll_startup_supervisor.sv#pll_startup_supervisor"
        },
        {
          "title": "v3 粗码搜索 · pll_coarse_ctrl",
          "path": "digital/pnr/rtl_v3/pll_coarse_ctrl.sv#pll_coarse_ctrl"
        },
        {
          "title": "v3 锁定检测 · pll_lock_detect",
          "path": "digital/pnr/rtl_v3/pll_lock_detect.sv#pll_lock_detect"
        },
        {
          "title": "v3 状态同步 · mon_sync",
          "path": "digital/pnr/rtl_v3/mon_sync.sv#mon_sync"
        },
        {
          "title": "v3 状态保持检测 · mon_persist",
          "path": "digital/pnr/rtl_v3/mon_persist.sv#mon_persist"
        }
      ]
    },
    {
      "id": "bias.v2",
      "parent": "bias",
      "name": "BIAS v2 带隙与分配",
      "subtitle": "FC-OTA、共模、预充缓冲与电流拷贝",
      "state": "5G/4G 签核",
      "summary": "单级宽摆幅折叠共栅带隙、16 档真 CMOS 译码预充缓冲与统一 153 指 pcopy 阵，135 角后仿与 200 样本 MC 全过。",
      "boundary": {
        "inputs": [
          "VDD_BIAS 1.8 V、5-bit r_ref 修调与预充码"
        ],
        "outputs": [
          "Vbg、Vcm (1.05 V)、LF 预充参考与各域电流拷贝"
        ],
        "assumptions": [
          "全 7 单元 DRC=0 / LVS=MATCH，20 外边界端口直连顶层。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "BIAS v2 设计与后仿",
          "path": "docs/design/bias_v2.md"
        },
        {
          "title": "BIAS v2 物理入口",
          "path": "analog/bias/layout/variants/v2_pdk/README.md"
        },
        {
          "title": "BIAS v2 物理摘要",
          "path": "analog/bias/layout/variants/v2_pdk/summary.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "BIAS v2 统一顶层集成宏版图",
          "path": "analog/bias/layout/variants/v2_pdk/serdes_bias_top_v2_pdk.png",
          "scope": "26,878.5 µm²，高阻 vgi 全封闭于宏内，135 角 |dVbg| ≤ 1.50 mV。",
          "report": "docs/design/bias_v2.md"
        }
      ],
      "sources": [
        {
          "title": "BIAS v2 顶层与子电路 · serdes_bias_top_v2",
          "path": "analog/bias/spice/bias_v2.spice#serdes_bias_top_v2"
        },
        {
          "title": "PLL PTAT 偏置分支 · serdes_bias_top_v2_ptat",
          "path": "analog/pll/vco/spice/vco_ptat_bias.spice#serdes_bias_top_v2_ptat"
        }
      ]
    },
    {
      "id": "bias.ldo_hv18",
      "parent": "bias",
      "name": "HV18 Kelvin LDO 与尾偏置滤波",
      "subtitle": "v2_cur_kelvin_pdk · 3.3→1.8 V 安静供电",
      "state": "5G/4G 签核",
      "summary": "有源预稳压 + 过冲钳位 + 叠层融合 60 pF MIM2，端口级 Kelvin 采样将等效输出阻抗压降 -92.9%（PSRR ≥ 28.7 dB，100× RCX MC 3σ ≤ 10.76 mV），配合叠层尾偏置低通滤波器。",
      "boundary": {
        "inputs": [
          "3.3 V HV 域、1.8 V 主域、BIAS v2 电流参考 i_ldo0、6-bit 修调码与使能"
        ],
        "outputs": [
          "1.8 V PLL 安静轨 VDD_Q、滤波后低噪尾偏置"
        ],
        "assumptions": [
          "v2_cur_kelvin_pdk 通过 5/5 + SF/FF 冷角 RCX 与 100× MC；4G v1.0 保留 v2_cur_pdk 对照。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "HV18 LDO v2 / v2_cur 设计",
          "path": "docs/design/ldo_v2.md"
        },
        {
          "title": "v2_cur_kelvin_pdk 物理入口",
          "path": "analog/ldo/layout/variants/v2_cur_kelvin_pdk/README.md"
        },
        {
          "title": "v2_cur_kelvin_pdk 物理摘要",
          "path": "analog/ldo/layout/variants/v2_cur_kelvin_pdk/summary.json"
        },
        {
          "title": "叠层尾偏置滤波物理入口",
          "path": "analog/ldo/layout/variants/bias_filter_stacked_pdk/README.md"
        },
        {
          "title": "v2_cur_pdk 4G 物理入口",
          "path": "analog/ldo/layout/variants/v2_cur_pdk/README.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "HV18 LDO Kelvin 强化生产宏版图",
          "path": "analog/ldo/layout/variants/v2_cur_kelvin_pdk/serdes_pll_supply_hv18_v2_cur_pdk.png",
          "scope": "v2_cur_kelvin_pdk，DRC=0 / LVS=MATCH，R_eff 降 92.9%，100× RCX MC 本体 3σ = 8.70–10.76 mV。",
          "report": "analog/ldo/layout/variants/v2_cur_kelvin_pdk/README.md"
        },
        {
          "title": "供电 PDN 与 LDO 稳定性复核",
          "path": "docs/figures/verification/stability_pdn_20261123.png",
          "scope": "Middlebrook 环路相位裕量与分域阻尼去耦阻抗谱。",
          "report": "docs/design/ldo_v2.md"
        },
        {
          "title": "叠层 VCO 尾偏置低通滤波版图",
          "path": "analog/ldo/layout/variants/bias_filter_stacked_pdk/serdes_pll_bias_lowpass_stacked_pdk.png",
          "scope": "1 MΩ / 16 pF 叠层 MIM 慢滤波器，抑制 PTAT 偏置线噪声至 \u003c 0.03 dB。",
          "report": "analog/ldo/layout/variants/bias_filter_stacked_pdk/README.md"
        }
      ],
      "sources": [
        {
          "title": "HV18 v2_cur 电流参考顶层",
          "path": "analog/ldo/spice/pll_supply_hv18_v2_cur.spice#serdes_pll_supply_hv18_v2_cur"
        },
        {
          "title": "HV18 调整管与误差放大器核心",
          "path": "analog/ldo/spice/ldo_hv18_core_v2.spice#serdes_ldo_hv18_core_v2"
        },
        {
          "title": "HV18 v2 无源单元",
          "path": "analog/ldo/spice/ldo_v2_passives.spice"
        },
        {
          "title": "VCO 尾偏置慢滤波 · serdes_pll_bias_lowpass_slow_r4",
          "path": "analog/ldo/spice/pll_bias_filter_r4.spice#serdes_pll_bias_lowpass_slow_r4"
        }
      ]
    },
    {
      "id": "tx.sst",
      "parent": "tx",
      "name": "CMOS 串化与 SST 驱动",
      "subtitle": "5G v5 / 4G v4 · 16:4 串化、四相交错与 2-tap FFE",
      "state": "5G/4G 签核",
      "summary": "四相 1.25 / 1.0 GHz 脉冲选通在 50 Ω 焊盘节点直接合成 5 / 4 Gb/s NRZ 差分信号，免费内置 2-tap FFE；v5_pdk 零冷角直通并通过 16/16 真 CPEX 签核。",
      "boundary": {
        "inputs": [
          "16 位并行字、四相时钟、V_drv、ZQ/FFE 控制"
        ],
        "outputs": [
          "50 Ω 差分焊盘 pad_p/pad_n、字时钟"
        ],
        "assumptions": [
          "v5_pdk (256.8 × 169.58 µm, 38 端口) 覆盖 5G/4G 双速；v4_pdk 保留 4G 基线。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "TX SST 设计与后仿",
          "path": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "TX v5_pdk 物理摘要",
          "path": "analog/tx/sst/layout/variants/v5_pdk/summary.json"
        },
        {
          "title": "TX 后仿验证台",
          "path": "analog/tx/sst/tb/postlayout/verify_tx_v4_pex.py"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G TX SST v5 顶层 PDK 版图",
          "path": "analog/tx/sst/layout/variants/v5_pdk/serdes_tx_sst_top_pdk.png",
          "scope": "完整 16:1 发射机，DRC=0 / LVS=MATCH，真 CPEX 16/16 散布 0.006–0.145 UI，裕量 100.1–226.7 mV。",
          "report": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "5G TX SST v5 驱动器阵列版图",
          "path": "analog/tx/sst/layout/variants/v5_pdk/serdes_tx_sst_driver_pdk.png",
          "scope": "28 片 N-over-N 切片镜像拼接 + M5 加强电源轨。",
          "report": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "TX SST 堆叠切片结构图",
          "path": "docs/figures/schematics/tx_sst_stacked_slices.png",
          "scope": "四相选通与主抽头 / 去加重切片连接原理。",
          "report": "docs/design/tx_sst_v4.md"
        }
      ],
      "sources": [
        {
          "title": "5G SST TX 顶层 · serdes_tx_sst_top_5g",
          "path": "analog/tx/sst/spice/tx_sst_top_5g.spice#serdes_tx_sst_top_5g"
        },
        {
          "title": "5G 16:4 静态 CMOS 串化 · serdes_tx_sst_serializer16_5g",
          "path": "analog/tx/sst/spice/tx_sst_serializer16_5g.spice#serdes_tx_sst_serializer16_5g"
        },
        {
          "title": "5G SST 驱动器与切片 · serdes_tx_sst_driver_5g",
          "path": "analog/tx/sst/spice/tx_sst_driver_5g.spice#serdes_tx_sst_driver_5g"
        },
        {
          "title": "4G SST TX 顶层 · serdes_tx_sst_top",
          "path": "analog/tx/sst/spice/tx_sst_top.spice#serdes_tx_sst_top"
        },
        {
          "title": "4G 16:4 静态 CMOS 串化 · serdes_tx_sst_serializer16",
          "path": "analog/tx/sst/spice/tx_sst_serializer16.spice#serdes_tx_sst_serializer16"
        },
        {
          "title": "4G SST 驱动器与切片 · serdes_tx_sst_driver",
          "path": "analog/tx/sst/spice/tx_sst_driver.spice#serdes_tx_sst_driver"
        },
        {
          "title": "TX 复用的正交 ÷2 · serdes_rx_qdiv2_8ph",
          "path": "analog/rx/cmos_rx/spice/rx_cmos_pi.spice#serdes_rx_qdiv2_8ph"
        }
      ]
    },
    {
      "id": "tx.vdrv_supply",
      "parent": "tx",
      "name": "V_drv 子稳压器",
      "subtitle": "v4.5 / v5 加固 SST 低压轨",
      "state": "5G/4G 签核",
      "summary": "带调零阻尼与泄放优化的 NMOS 源跟随子稳压器，生成约 0.44 V 低压轨；v4p5_pdk / v5_pdk 真 CPEX PM 71.1–85.2°、200× MC 3σ ≤ 15.60 mV，瞬态纹波 ≤ 44.3 mVpp。",
      "boundary": {
        "inputs": [
          "1.8 V TX 电源域、Vbg、28-slice 时变切换负载"
        ],
        "outputs": [
          "约 0.44 V V_drv 低压驱动轨"
        ],
        "assumptions": [
          "v4p5_pdk 独立 200× MC 与 v5_pdk 整机 CPEX 分别签核，见 5G 签核台账。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "TX SST 设计与后仿",
          "path": "docs/design/tx_sst_v4.md"
        },
        {
          "title": "V_drv v4p5_pdk 物理摘要",
          "path": "analog/tx/sst/layout/variants/v4p5_pdk/summary.json"
        },
        {
          "title": "TX v5_pdk 物理摘要",
          "path": "analog/tx/sst/layout/variants/v5_pdk/summary.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "V_drv 子稳压器 v5_pdk 版图",
          "path": "analog/tx/sst/layout/variants/v5_pdk/sst_vdrv_ldo_pdk.png",
          "scope": "3D 堆叠 MIM1+MIM2 置于 poly 电阻上方，200× MC vdrv 3σ ≤ 15.60 mV，满载纹波 ≤ 44.3 mVpp。",
          "report": "docs/design/tx_sst_v4.md"
        }
      ],
      "sources": [
        {
          "title": "5G V_drv 子稳压器 · sst_vdrv_ldo",
          "path": "analog/tx/sst/spice/tx_sst_driver_5g.spice#sst_vdrv_ldo"
        },
        {
          "title": "4G V_drv 子稳压器 · sst_vdrv_ldo",
          "path": "analog/tx/sst/spice/tx_sst_driver.spice#sst_vdrv_ldo"
        }
      ]
    },
    {
      "id": "tx.digital_ingress",
      "parent": "tx",
      "name": "TX 字入口 RTL",
      "subtitle": "5G 32-bit 降频入口 / 4G 16-bit 入口",
      "state": "5G/4G 签核",
      "summary": "承接宿主并行字握手、预热与流水缓冲，向 SST 16:4 串化器提供无毛刺对齐字；v4p1 升级为 32-bit 降频架构满足 5G 6 角 OCV 时序。",
      "boundary": {
        "inputs": [
          "TX 字时钟、宿主握手与并行发送字"
        ],
        "outputs": [
          "发送捕获字与有效控制信号"
        ],
        "assumptions": [
          "v4p1 覆盖 4/5 Gb/s 双速，v3.1 保留 4G 16-bit 基线。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G 数字宏 v4p1 摘要",
          "path": "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json"
        },
        {
          "title": "统一数字顶层 v3.1",
          "path": "docs/design/digital_top_v3.md"
        }
      ],
      "iterations": [],
      "sources": [
        {
          "title": "5G TX 32-bit 入口控制 · tx_ingress_control_32",
          "path": "digital/pnr/rtl_v4_32b/tx_ingress_control_32.sv#tx_ingress_control_32"
        },
        {
          "title": "5G 数字顶层 · serdes_digital_top_v4",
          "path": "digital/pnr/rtl_v4_32b/serdes_digital_top_v4.sv#serdes_digital_top_v4"
        },
        {
          "title": "4G TX 16-bit 入口控制 · tx_ingress_control",
          "path": "digital/pnr/rtl_v3/tx_ingress_control.sv#tx_ingress_control"
        },
        {
          "title": "4G 数字顶层 · serdes_digital_top_v3",
          "path": "digital/pnr/rtl_v3/serdes_digital_top_v3.sv#serdes_digital_top_v3"
        }
      ]
    },
    {
      "id": "rx.ctle_v2",
      "parent": "rx",
      "name": "端接与 CTLE",
      "subtitle": "5G W3 并联电感峰化 / 4G RC 退化",
      "state": "5G/4G 签核",
      "summary": "片上 2×50 Ω 端接建立 1.05 V 共模；5G 采用 M4/M2 紧凑中心抽头并联电感 + W3 退化 CTLE（5,259 µm²，0% M5，45/45 AC + 400× MC）；4G 采用无电感 RC-CTLE。",
      "boundary": {
        "inputs": [
          "100 Ω 差分信道远端输入、Vcm (1.05 V)、EQ 控制码"
        ],
        "outputs": [
          "差分均衡输出驱动 8× 动态采样器"
        ],
        "assumptions": [
          "ctle_shunt_5g_w3_pdk 通过 45/45 AC、C2/C3 眼图与 400× MC（Vos 3σ ≤ 20.28 mV）。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "RX CMOS 设计与 5G CTLE 演进",
          "path": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "5G W3 CTLE 物理摘要",
          "path": "analog/rx/cmos_rx/layout/variants/ctle_shunt_5g_w3_pdk/summary.json"
        },
        {
          "title": "信道模型",
          "path": "docs/design/channel_model.md"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G W3 并联电感峰化 CTLE PDK 版图",
          "path": "analog/rx/cmos_rx/layout/variants/ctle_shunt_5g_w3_pdk/serdes_rx_ctle_shunt_5g_w3_pdk.png",
          "scope": "M4/M2 紧凑叠层差分电感（0% M5），DRC=0 / LVS=MATCH，45/45 AC + 400× MC 签核。",
          "report": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "4G RC-CTLE PDK 版图",
          "path": "analog/rx/cmos_rx/layout/variants/v2_pdk/serdes_rx_ctle_pdk.png",
          "scope": "979.9 µm² 纯 RC 退化 CTLE，180/180（45 角 × 4 EQ）签核。",
          "report": "docs/design/rx_cmos_v2.md"
        }
      ],
      "sources": [
        {
          "title": "5G 并联电感 CTLE · serdes_rx_ctle_shunt_5g_pdk",
          "path": "analog/rx/cmos_rx/spice/rx_ctle_shunt_5g_pdk.spice#serdes_rx_ctle_shunt_5g_pdk"
        },
        {
          "title": "4G 片上端接与 CTLE · serdes_rx_ctle_pdk",
          "path": "analog/rx/cmos_rx/spice/rx_ctle_pdk.spice#serdes_rx_ctle_pdk"
        }
      ]
    },
    {
      "id": "rx.cmos_pi",
      "parent": "rx",
      "name": "CMOS PI 与八相 ÷2",
      "subtitle": "5G 4→8 相 2.5 GHz PI v3 / 4G 64 码 PI",
      "state": "5G/4G 签核",
      "summary": "5G 采用内置 4→8 相八相发生器 + 64 码高阻混合 CMOS PI v3 与确定性正交 ÷2（173.38 × 72.72 µm，0% M5），6/6 角 24/24 全通、冷角 MC 0/24 翻转；4G 沿用 8 相锚点 CMOS PI。",
      "boundary": {
        "inputs": [
          "5G：2.5 GHz 四相 I/Q 锚点；4G：2 GHz 八相锚点；one-hot 选相与 8-bit 温度计细分码"
        ],
        "outputs": [
          "8 相四分之一速数据/边沿采样时钟（1.25 GHz / 1.0 GHz）"
        ],
        "assumptions": [
          "端口与数字 CDR pi_step_commutator 完全兼容；5G v3 详细验证见 5G 签核台账。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "RX CMOS 设计与 PI 结构",
          "path": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "5G PI v3 物理摘要",
          "path": "analog/rx/cmos_rx/layout/variants/v5g_4ph_v3_pdk/summary.json"
        },
        {
          "title": "PI 验证台",
          "path": "analog/rx/cmos_rx/tb/pi/verify_pi.py"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G 4→8 相 CMOS PI v3 PDK 版图",
          "path": "analog/rx/cmos_rx/layout/variants/v5g_4ph_v3_pdk/serdes_rx_pi_4ph_5g_pdk.png",
          "scope": "173.38 × 72.72 µm，43 端口，DRC=0 / LVS=MATCH / M5=0%，6/6 角 24/24 全通、24× 冷角 MC 0/24 翻转。",
          "report": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "CMOS PI 堆叠切片原理图",
          "path": "docs/figures/schematics/rx_pi_stacked_slices.png",
          "scope": "4:1 LVT 传输门选相与 8 片高阻 MIM 线性化混合器结构。",
          "report": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "CMOS PI 原理与相位插值图解",
          "path": "docs/figures/rx/pi/rx_pi_schematic_explained.png",
          "scope": "64 码选相、细分温度计控制与确定性八相 ÷2 工作机制。",
          "report": "docs/design/rx_cmos_v2.md"
        }
      ],
      "sources": [
        {
          "title": "5G 4→8 相 CMOS PI v3 · serdes_rx_pi_4ph_iq_8ph",
          "path": "analog/rx/cmos_rx/spice/rx_pi_4ph_iq_5g_v3.spice#serdes_rx_pi_4ph_iq_8ph"
        },
        {
          "title": "4G CMOS PI 与八相 ÷2 · serdes_rx_cmos_pi_8ph",
          "path": "analog/rx/cmos_rx/spice/rx_cmos_pi.spice#serdes_rx_cmos_pi_8ph"
        }
      ]
    },
    {
      "id": "rx.dt_readout",
      "parent": "rx",
      "name": "Double-Tail 采样与解串",
      "subtitle": "8 路动态采样器（5G / 4G）+ 静态 8→32 解串",
      "state": "5G/4G 签核",
      "summary": "8 路四分之一速动态采样切片直连 CTLE 输出，零迟滞并配 6-bit 失调修调；slicer_5g_pdk 通过 6/6 真 CPEX 与 250/250 MC（σ=6.09–6.77 mV），静态 8→32 解串送出 16 数据 + 16 边沿。",
      "boundary": {
        "inputs": [
          "CTLE 差分输出、8 相采样时钟、6-bit 失调修调码"
        ],
        "outputs": [
          "16 位数据字、16 位边沿字与恢复字时钟 wclk"
        ],
        "assumptions": [
          "slicer_5g_pdk 29.6 × 31.54 µm、0% M5，提供 ≥ 8.05σ 失调修调余量。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "RX CMOS 设计",
          "path": "docs/design/rx_cmos_v2.md"
        },
        {
          "title": "5G Slicer 物理摘要",
          "path": "analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/summary.json"
        },
        {
          "title": "Slicer 验证台",
          "path": "analog/rx/cmos_rx/tb/slicer/verify_slicer.py"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "5G Double-Tail 动态采样切片版图（slicer_5g_pdk）",
          "path": "analog/rx/cmos_rx/layout/variants/slicer_5g_pdk/serdes_rx_dt_slicer_5g_pdk.png",
          "scope": "29.6 × 31.54 µm，DRC=0 / LVS=MATCH / M5=0%，250/250 MC σ=6.09–6.77 mV（3σ ≤ 20.30 mV）。",
          "report": "docs/design/rx_cmos_v2.md"
        }
      ],
      "sources": [
        {
          "title": "5G 动态采样器与再生锁存 · serdes_rx_dt_slicer_5g",
          "path": "analog/rx/cmos_rx/spice/rx_dt_sampler_5g.spice#serdes_rx_dt_slicer_5g"
        },
        {
          "title": "4G Double-Tail 采样器 · serdes_rx_dt_slicer",
          "path": "analog/rx/cmos_rx/spice/rx_dt_sampler.spice#serdes_rx_dt_slicer"
        },
        {
          "title": "静态 CMOS 8→32 解串 · serdes_rx_cmos_deser16",
          "path": "analog/rx/cmos_rx/spice/rx_cmos_deser16.spice#serdes_rx_cmos_deser16"
        }
      ]
    },
    {
      "id": "rx.digital_cdr",
      "parent": "rx",
      "name": "RX CDR RTL",
      "subtitle": "32-bit v4 / 16-bit v3 · 边沿投票、频偏估计与 PI 换码",
      "state": "5G/4G 签核",
      "summary": "在恢复时钟域累计 Alexander BBPD 投票并经二阶环路输出受保护的 PI 步进控制；v4 升级为 32-bit 并行降频处理，满足 5G ±5% OCV 6 角时序。",
      "boundary": {
        "inputs": [
          "解串并重映射后的数据与边沿并行字"
        ],
        "outputs": [
          "PI select_a/b one-hot、fine_b 温度计码与锁定状态"
        ],
        "assumptions": [
          "与 4G/5G 纯 CMOS PI 控制接口 100% 兼容。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G 数字宏 v4p1 摘要",
          "path": "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json"
        },
        {
          "title": "统一数字顶层 v3.1",
          "path": "docs/design/digital_top_v3.md"
        }
      ],
      "iterations": [],
      "sources": [
        {
          "title": "5G CDR 顶层 · rx_cdr_loop_v4",
          "path": "digital/pnr/rtl_v4_32b/rx_cdr_loop_v4.sv#rx_cdr_loop_v4"
        },
        {
          "title": "5G 32-bit Alexander 投票 · bbpd_window_vote32",
          "path": "digital/pnr/rtl_v4_32b/bbpd_window_vote32.sv#bbpd_window_vote32"
        },
        {
          "title": "5G 频率和相位环路 · cdr_phase_frequency_v4",
          "path": "digital/pnr/rtl_v4_32b/cdr_phase_frequency_v4.sv#cdr_phase_frequency_v4"
        },
        {
          "title": "5G PI 控制换码 · pi_step_commutator",
          "path": "digital/pnr/rtl_v4_32b/pi_step_commutator.sv#pi_step_commutator"
        },
        {
          "title": "4G CDR 顶层 · rx_cdr_loop",
          "path": "digital/pnr/rtl_v3/rx_cdr_loop.sv#rx_cdr_loop"
        },
        {
          "title": "4G 16-bit Alexander 投票 · bbpd_window_vote",
          "path": "digital/pnr/rtl_v3/bbpd_window_vote.sv#bbpd_window_vote"
        },
        {
          "title": "4G 频率和相位控制 · cdr_phase_frequency",
          "path": "digital/pnr/rtl_v3/cdr_phase_frequency.sv#cdr_phase_frequency"
        },
        {
          "title": "4G PI 控制换码 · pi_step_commutator",
          "path": "digital/pnr/rtl_v3/pi_step_commutator.sv#pi_step_commutator"
        }
      ]
    },
    {
      "id": "rx.digital_words",
      "parent": "rx",
      "name": "RX 字对齐与异步 FIFO RTL",
      "subtitle": "位映射、16→32 打包、训练对齐与宿主 CDC",
      "state": "5G/4G 签核",
      "summary": "将物理解串字重映射，5G v4p1 经 16→32 打包并在半速域完成 32-bit 训练对齐与双时钟异步 FIFO CDC（26/26 同步器扇出为 1）；4G v3.1 保留 16-bit 路径。",
      "boundary": {
        "inputs": [
          "物理解串并行字、恢复字时钟与宿主时钟"
        ],
        "outputs": [
          "对齐后的并行宿主数据及握手/状态标志"
        ],
        "assumptions": [
          "v4p1 顶层与 rx_top_5g_pdk 间 33-bit 接口实现零交叉直连。"
        ]
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "5G 数字宏 v4p1 摘要",
          "path": "digital/pnr/variants/hd_pnr_v4p1_5g_coopt/serdes_digital_top_v4/summary.json"
        },
        {
          "title": "统一数字顶层 v3.1",
          "path": "docs/design/digital_top_v3.md"
        }
      ],
      "iterations": [],
      "sources": [
        {
          "title": "5G RX 32-bit 宿主路径 · rx_word_host_32",
          "path": "digital/pnr/rtl_v4_32b/rx_word_host_32.sv#rx_word_host_32"
        },
        {
          "title": "5G 物理位映射 · rx_word_map",
          "path": "digital/pnr/rtl_v4_32b/rx_word_map.sv#rx_word_map"
        },
        {
          "title": "5G 16→32 字打包 · rx_pack_16to32",
          "path": "digital/pnr/rtl_v4_32b/rx_pack_16to32.sv#rx_pack_16to32"
        },
        {
          "title": "5G 32-bit 训练字对齐 · rx_word_align32",
          "path": "digital/pnr/rtl_v4_32b/rx_word_align32.sv#rx_word_align32"
        },
        {
          "title": "5G 32-bit 异步 FIFO · async_word_fifo_32",
          "path": "digital/pnr/rtl_v4_32b/async_word_fifo_32.sv#async_word_fifo_32"
        },
        {
          "title": "4G RX 共享字映射与宿主接口 · rx_word_host_shared",
          "path": "digital/pnr/rtl_v3/serdes_digital_top_v3.sv#rx_word_host_shared"
        },
        {
          "title": "4G 物理位映射 · rx_word_map",
          "path": "digital/pnr/rtl_v3/rx_word_map.sv#rx_word_map"
        },
        {
          "title": "4G 16-bit 训练字对齐 · rx_word_align16",
          "path": "digital/pnr/rtl_v3/rx_word_align16.sv#rx_word_align16"
        },
        {
          "title": "4G 16-bit 异步 FIFO · rx_async_word_fifo_core",
          "path": "digital/pnr/rtl_v3/rx_async_word_fifo.sv#rx_async_word_fifo_core"
        }
      ]
    },
    {
      "id": "channel.model",
      "parent": "channel",
      "name": "PCB 与端接模型",
      "key": "X01",
      "subtitle": "RLC16 / C0–C5 / 已登记边界",
      "state": "主线",
      "summary": "合成差分 PCB 族（C0–C5）与 RLC16 等效网表共享服务 4 Gb/s 与 5 Gb/s 链路回归，明确源阻抗、色散损耗与接收负载。",
      "boundary": {
        "inputs": [
          "TX 差分输出阻抗、焊盘与封装/AC 代理"
        ],
        "outputs": [
          "RX 100 Ω 端接处差分信号与频域/脉冲响应"
        ],
        "assumptions": [
          "回放边界统一登记在 config/boundary_conditions.json 并校验负载签名。"
        ]
      },
      "planning": {
        "question": "在 4 Gb/s（2.0 GHz）与 5 Gb/s（2.5 GHz）共享信道族上保持因果、无源且可复现的 ISI 回归边界。",
        "model": "S4P 频域表征 + Foster 损耗集总等效 SPICE 网表对照验证。",
        "parameters": "C2_loss6 为主设计信道，C3_loss10 为挑战信道，C4_stub/C5_skew 覆盖反射与偏斜诊断。",
        "verification": "AC 无源性、脉冲响应对照及端到端 TX+Channel+RX 眼图回归。"
      },
      "references": [
        {
          "title": "当前状态与验证边界",
          "path": "docs/status/current.md"
        },
        {
          "title": "信道模型设计",
          "path": "docs/design/channel_model.md"
        },
        {
          "title": "信道族配置",
          "path": "config/channel_family.toml"
        },
        {
          "title": "边界条件登记表",
          "path": "config/boundary_conditions.json"
        }
      ],
      "iterations": [],
      "figures": [
        {
          "title": "PCB 信道族远端脉冲响应",
          "path": "docs/figures/channel/characterization/pcb_channel_family_pulses_ui.png",
          "scope": "C2 主设计信道与其余合成 PCB 模型的脉冲响应对照。",
          "report": "docs/design/channel_model.md"
        },
        {
          "title": "PCB 信道族频域插损特性",
          "path": "docs/figures/channel/characterization/pcb_channel_family_frequency.png",
          "scope": "C0–C5 差模传输特性，涵盖 2.0 GHz 与 2.5 GHz Nyquist 频点。",
          "report": "docs/design/channel_model.md"
        }
      ],
      "sources": [
        {
          "title": "RLC16 近无损负载",
          "path": "verification/models/channel/diff_rlc16.spice#serdes_diff_rlc16"
        },
        {
          "title": "C2_loss6 PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C2_loss6.spice#pcb_c2_loss6"
        },
        {
          "title": "C0_debug PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C0_debug.spice#pcb_c0_debug"
        },
        {
          "title": "C1_loss3 PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C1_loss3.spice#pcb_c1_loss3"
        },
        {
          "title": "C3_loss10 PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C3_loss10.spice#pcb_c3_loss10"
        },
        {
          "title": "C4_stub PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C4_stub.spice#pcb_c4_stub"
        },
        {
          "title": "C5_skew PCB 等效网表",
          "path": "verification/models/channel/pcb_family/C5_skew.spice#pcb_c5_skew"
        },
        {
          "title": "Foster 损耗单元",
          "path": "verification/models/channel/pcb_family/pcb_foster_cells.spice#pcb_foster_cell"
        }
      ]
    }
  ],
  "mode": "standalone"
};
